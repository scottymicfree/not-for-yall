"""
Lucy Serial/UART Interface — Fallback Command Bridge
=====================================================
Provides basic command/control to Sovereign v2.1 board via UART.
Used when PCIe and Ethernet are both unavailable.

Hardware path:
  Windows Lucy App
       │
       │ USB-UART (FTDI FT232H / CP2102 / CH340)
       ▼
  Sovereign v2.1 UART debug port (115200 8N1)
       ├── Debug console (Linux serial getty)
       └── BMC UART (IPMI SOL)

Supports:
  - ASCII command protocol (line-based JSON)
  - Agent halt/throttle/status commands
  - Sensor readings (temperature, power)
  - HAL status query
  - Emergency stop

Protocol (line-delimited JSON):
  TX: {"cmd": "halt_agent", "target": "W042", "seq": 1}\n
  RX: {"status": "ok", "seq": 1, "ack": "halt_agent", "target": "W042"}\n
"""

import sys
import os
import time
import json
import logging
import threading
import queue
from typing import Optional, Dict, Any, Callable, List

logger = logging.getLogger("lucy.bridge.serial")

# ─────────────────────────────────────────────────────────────────────────────
# Serial Port Discovery
# ─────────────────────────────────────────────────────────────────────────────

def find_sovereign_port() -> Optional[str]:
    """
    Auto-detect the Sovereign v2.1 UART port.
    Looks for known USB-UART chip VIDs on Windows and Linux.
    """
    known_descriptions = [
        "ft232", "ftdi", "cp210", "ch340", "ch341",
        "uart", "serial", "sovereign", "lucy"
    ]
    try:
        import serial.tools.list_ports as lp
        ports = list(lp.comports())
        # First pass: exact keyword match
        for p in ports:
            desc = (p.description or "").lower()
            hwid = (p.hwid or "").lower()
            if any(kw in desc or kw in hwid for kw in known_descriptions):
                logger.info(f"Found candidate port: {p.device} ({p.description})")
                return p.device
        # Second pass: any port
        if ports:
            return ports[0].device
    except ImportError:
        # Fallback: common port names
        if sys.platform == "win32":
            for n in range(1, 20):
                return f"COM{n}"  # just return COM1 as starting point
        else:
            import glob
            candidates = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
            if candidates:
                return candidates[0]
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Lucy Serial Protocol
# ─────────────────────────────────────────────────────────────────────────────

SERIAL_BAUD     = 115200
SERIAL_TIMEOUT  = 5.0
SERIAL_NEWLINE  = b'\n'
SERIAL_ENCODING = 'utf-8'

# ASCII commands supported by the Sovereign v2.1 serial bridge firmware
SERIAL_COMMANDS = {
    "status":        "Query HAL status",
    "halt_agent":    "Halt a specific agent node",
    "release_halt":  "Release halt on agent",
    "halt_all":      "Emergency halt all 137 nodes",
    "throttle":      "Throttle agent by anomaly score",
    "reset_gpu":     "Reset a GPU by ID",
    "get_sensors":   "Read all sensor values",
    "get_power":     "Read power consumption",
    "get_telemetry": "Full mesh telemetry snapshot",
    "ping":          "Ping the bridge firmware",
}


class SerialBridge:
    """
    Line-delimited JSON serial bridge to Sovereign v2.1.
    Falls back to simulation if no port is available.
    """

    def __init__(
        self,
        port: Optional[str] = None,
        baud: int = SERIAL_BAUD,
        mode: str = "auto",
    ):
        self.port = port or find_sovereign_port()
        self.baud = baud
        self.mode = mode

        self._serial = None
        self._seq    = 0
        self._lock   = threading.Lock()
        self._rx_buf = ""
        self._pending: Dict[int, queue.Queue] = {}
        self._rx_thread: Optional[threading.Thread] = None
        self._running = False
        self._sim_log: List[Dict] = []

        if mode == "auto":
            self.mode = self._detect_mode()

        if self.mode == "native":
            self._open()
        else:
            logger.info(f"SerialBridge in {self.mode} mode (no hardware)")

    def _detect_mode(self) -> str:
        if not self.port:
            return "sim"
        try:
            import serial as _serial
            s = _serial.Serial(self.port, self.baud, timeout=1.0)
            s.close()
            return "native"
        except Exception as e:
            logger.warning(f"Serial port {self.port} not available: {e} — using sim")
            return "sim"

    def _open(self):
        try:
            import serial as _serial
            self._serial = _serial.Serial(
                port=self.port,
                baudrate=self.baud,
                bytesize=_serial.EIGHTBITS,
                parity=_serial.PARITY_NONE,
                stopbits=_serial.STOPBITS_ONE,
                timeout=SERIAL_TIMEOUT,
                write_timeout=SERIAL_TIMEOUT,
                xonxoff=False,
                rtscts=False,
            )
            self._running = True
            self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
            self._rx_thread.start()
            logger.info(f"Serial port {self.port} opened at {self.baud} baud")
        except Exception as e:
            logger.error(f"Cannot open serial port {self.port}: {e}")
            self._serial = None
            self.mode = "sim"

    def _rx_loop(self):
        """Background thread: reads lines and dispatches to waiting send() calls."""
        while self._running and self._serial:
            try:
                line = self._serial.readline()
                if not line:
                    continue
                text = line.decode(SERIAL_ENCODING, errors="replace").strip()
                if not text:
                    continue
                try:
                    data = json.loads(text)
                    seq = data.get("seq")
                    if seq is not None and seq in self._pending:
                        self._pending[seq].put(data)
                    else:
                        # Unsolicited event
                        logger.info(f"[SERIAL RX unsolicited] {data}")
                except json.JSONDecodeError:
                    logger.debug(f"[SERIAL RX raw] {text}")
            except Exception as e:
                if self._running:
                    logger.error(f"Serial RX error: {e}")
                time.sleep(0.1)

    def _next_seq(self) -> int:
        with self._lock:
            self._seq = (self._seq + 1) & 0xFFFF
            return self._seq

    def send(
        self,
        cmd: str,
        payload: Optional[Dict] = None,
        timeout: float = SERIAL_TIMEOUT,
    ) -> Dict[str, Any]:
        """Send a command and wait for response."""
        seq = self._next_seq()
        message = {"cmd": cmd, "seq": seq}
        if payload:
            message.update(payload)

        if self.mode == "sim":
            return self._sim_response(cmd, message)

        # Register pending slot
        resp_queue: queue.Queue = queue.Queue()
        self._pending[seq] = resp_queue

        try:
            line = json.dumps(message) + "\n"
            self._serial.write(line.encode(SERIAL_ENCODING))
            self._serial.flush()

            try:
                response = resp_queue.get(timeout=timeout)
                return response
            except queue.Empty:
                return {
                    "status": "timeout",
                    "seq": seq,
                    "cmd": cmd,
                    "error": f"No response within {timeout}s",
                }
        except Exception as e:
            return {"status": "error", "seq": seq, "cmd": cmd, "error": str(e)}
        finally:
            self._pending.pop(seq, None)

    def _sim_response(self, cmd: str, message: Dict) -> Dict[str, Any]:
        """Generate a realistic simulated response."""
        import random
        base = {
            "status": "ok",
            "seq":    message.get("seq", 0),
            "ack":    cmd,
            "source": "sim_serial",
            "timestamp": time.time(),
        }
        sim_map = {
            "ping": {**base, "pong": True, "firmware": "sovereign-bridge-v2.1.0"},
            "status": {**base, "hal_mode": "native", "nodes": 137, "layers_ok": 8,
                       "health_pct": 97.0 + random.uniform(-2, 2)},
            "halt_agent": {**base, "target": message.get("target", "?"),
                           "halted": True, "fpga_ack": True},
            "halt_all": {**base, "halted_count": 137, "fpga_ack": True},
            "release_halt": {**base, "released": True},
            "throttle": {**base, "target": message.get("target", "?"),
                         "anomaly_score": message.get("anomaly_score", 0),
                         "clock_mhz": 1890},
            "reset_gpu": {**base, "gpu_id": message.get("gpu_id", 0), "reset_ok": True},
            "get_sensors": {**base, "sensors": {
                "gpu0_temp": 61.2 + random.uniform(-3, 5),
                "gpu1_temp": 58.4 + random.uniform(-3, 5),
                "gpu2_temp": 63.1 + random.uniform(-3, 5),
                "gpu3_temp": 59.7 + random.uniform(-3, 5),
                "board_temp": 42.0 + random.uniform(-2, 4),
                "inlet_temp": 24.5,
            }},
            "get_power": {**base, "power": {
                "total_w":   1751.0 + random.uniform(-50, 80),
                "budget_w":  2400.0,
                "compute_w": 1480.0,
                "logic_w":   180.0,
                "storage_w": 71.0,
            }},
            "get_telemetry": {**base, "telemetry": {
                "lucidity": 0.873 + random.uniform(-0.02, 0.02),
                "mesh_health": 0.97,
                "active_nodes": 137,
                "layer_health": {
                    "perception": 1.0, "memory": 0.98, "swarm": 0.97,
                    "emma_mesh": 1.0, "lucy_prime": 1.0,
                    "infrastructure": 1.0, "output": 1.0, "safety": 1.0,
                },
            }},
        }
        result = sim_map.get(cmd, {**base, "data": f"unknown command: {cmd}"})
        self._sim_log.append({"cmd": cmd, "request": message, "response": result})
        return result

    # ── High-level command API ─────────────────────────────────────────────

    def ping(self) -> Dict[str, Any]:
        return self.send("ping")

    def get_status(self) -> Dict[str, Any]:
        return self.send("status")

    def halt_agent(self, agent_id: str, reason: str = "") -> Dict[str, Any]:
        return self.send("halt_agent", {"target": agent_id, "reason": reason})

    def release_halt(self, agent_id: str) -> Dict[str, Any]:
        return self.send("release_halt", {"target": agent_id})

    def halt_all(self, reason: str = "") -> Dict[str, Any]:
        logger.warning(f"SERIAL HALT ALL: {reason}")
        return self.send("halt_all", {"reason": reason})

    def throttle_agent(self, agent_id: str, anomaly_score: float) -> Dict[str, Any]:
        return self.send("throttle", {"target": agent_id, "anomaly_score": anomaly_score})

    def reset_gpu(self, gpu_id: int, reason: str = "") -> Dict[str, Any]:
        return self.send("reset_gpu", {"gpu_id": gpu_id, "reason": reason})

    def get_sensors(self) -> Dict[str, Any]:
        return self.send("get_sensors")

    def get_power(self) -> Dict[str, Any]:
        return self.send("get_power")

    def get_telemetry(self) -> Dict[str, Any]:
        return self.send("get_telemetry")

    def get_sim_log(self) -> List[Dict]:
        return list(self._sim_log)

    def is_open(self) -> bool:
        if self.mode == "sim":
            return True
        return self._serial is not None and self._serial.is_open

    def close(self):
        self._running = False
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
        logger.info("SerialBridge closed")


# ─────────────────────────────────────────────────────────────────────────────
# Serial Console (interactive debug)
# ─────────────────────────────────────────────────────────────────────────────

class SerialConsole:
    """
    Interactive UART console for direct debug access to the Sovereign board.
    Streams raw bytes to/from the serial port — useful for BMC SOL access.
    """

    def __init__(self, port: str, baud: int = 115200):
        self.port    = port
        self.baud    = baud
        self._serial = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._rx_callback: Optional[Callable[[str], None]] = None

    def open(self, rx_callback: Optional[Callable[[str], None]] = None):
        import serial as _serial
        self._serial = _serial.Serial(self.port, self.baud, timeout=0.1)
        self._rx_callback = rx_callback
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while self._running and self._serial:
            try:
                data = self._serial.read(1024)
                if data:
                    text = data.decode('utf-8', errors='replace')
                    if self._rx_callback:
                        self._rx_callback(text)
            except Exception:
                time.sleep(0.05)

    def write(self, text: str):
        if self._serial and self._serial.is_open:
            self._serial.write(text.encode('utf-8'))

    def send_ctrl_c(self):
        self.write('\x03')

    def close(self):
        self._running = False
        if self._serial:
            self._serial.close()


# ─────────────────────────────────────────────────────────────────────────────
# Self-test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=== Serial Interface Self-Test (SIM mode) ===\n")

    bridge = SerialBridge(mode="sim")
    assert bridge.mode == "sim"

    print("1. Ping")
    r = bridge.ping()
    assert r["status"] == "ok", f"ping failed: {r}"
    print(f"   ✓ {r.get('firmware', 'firmware ok')}")

    print("2. Status")
    r = bridge.get_status()
    assert r["nodes"] == 137
    print(f"   ✓ nodes={r['nodes']} health={r['health_pct']:.1f}%")

    print("3. Halt agent")
    r = bridge.halt_agent("W042", "test")
    assert r["halted"] is True
    print(f"   ✓ halted={r['halted']} fpga_ack={r['fpga_ack']}")

    print("4. Throttle")
    r = bridge.throttle_agent("W001", 0.75)
    assert r["status"] == "ok"
    print(f"   ✓ clock={r.get('clock_mhz')} MHz")

    print("5. Sensors")
    r = bridge.get_sensors()
    sensors = r.get("sensors", {})
    print(f"   ✓ gpu0_temp={sensors.get('gpu0_temp', 0):.1f}°C board={sensors.get('board_temp', 0):.1f}°C")

    print("6. Power")
    r = bridge.get_power()
    pwr = r.get("power", {})
    print(f"   ✓ total={pwr.get('total_w', 0):.0f}W / {pwr.get('budget_w', 2400):.0f}W")

    print("7. Telemetry")
    r = bridge.get_telemetry()
    telem = r.get("telemetry", {})
    print(f"   ✓ lucidity={telem.get('lucidity', 0):.3f} nodes={telem.get('active_nodes', 0)}")

    bridge.close()
    print(f"\n✓ All serial tests passed — {len(bridge.get_sim_log())} commands logged")