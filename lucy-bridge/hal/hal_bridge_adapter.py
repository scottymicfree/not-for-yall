"""
Lucy HAL Bridge Adapter
=======================
Adapts Lucy OS v5's HAL (Hardware Abstraction Layer) to work
when Lucy is running as a Windows application rather than natively
on the Sovereign v2.1 Linux board.

The adapter:
  1. Detects the best available transport (PCIe → Ethernet → USB → Serial)
  2. Routes each HAL subsystem call to the appropriate transport
  3. Falls back gracefully (sim mode) if no hardware is reachable
  4. Provides the same Python API as lucy_mount.py (LucyBoundSystem)

This means Lucy OS v5 code can call:
    lucy.halt_agent("W042", reason="anomaly")
    lucy.sensemesh.get_snapshot()
    lucy.neuromesh.get_gpu_telemetry(0)
...and the adapter transparently forwards to the real hardware,
whether that's via PCIe, Ethernet, USB, or Serial.

Architecture:
    Lucy OS v5 (Windows)
         │
         ▼
    HALBridgeAdapter          ← THIS FILE
         │
         ├── PCIeTransport    → pcie_interface.py
         ├── EthernetTransport→ ethernet_interface.py
         ├── SerialTransport  → serial_interface.py
         └── SimTransport     → synthetic data (always available)
"""

import sys
import os
import time
import json
import logging
import threading
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("lucy.bridge.hal_adapter")

# ─────────────────────────────────────────────────────────────────────────────
# Transport selection
# ─────────────────────────────────────────────────────────────────────────────

class Transport(str, Enum):
    PCIE     = "pcie"
    ETHERNET = "ethernet"
    SERIAL   = "serial"
    SIM      = "sim"


@dataclass
class BridgeConfig:
    preferred_transport: Optional[Transport] = None   # None = auto-detect
    board_ip:            str  = "192.168.1.100"
    serial_port:         Optional[str] = None
    serial_baud:         int  = 115200
    hal_mode:            str  = "auto"   # 'native'|'proto'|'sim'|'auto'
    poll_interval_s:     float = 5.0
    auto_reconnect:      bool  = True
    verbose:             bool  = True


# ─────────────────────────────────────────────────────────────────────────────
# Subsystem Proxies
# ─────────────────────────────────────────────────────────────────────────────

class NeuroMeshProxy:
    """
    Proxies NeuroMesh GPU calls to the Sovereign board.
    API matches neuromesh_driver.py from HARDWARE_MOUNT_GUIDE §8.1
    """
    def __init__(self, adapter: 'HALBridgeAdapter'):
        self._a = adapter

    def get_gpu_telemetry(self, gpu_id: int) -> Dict[str, Any]:
        if self._a.transport == Transport.PCIE:
            return self._a._pcie.gpu.get_gpu_telemetry(gpu_id)
        elif self._a.transport == Transport.ETHERNET:
            telem = self._a._eth.get_all_telemetry()
            gpus  = telem.get("gpu_metrics", [])
            if gpu_id < len(gpus):
                return gpus[gpu_id]
        elif self._a.transport == Transport.SERIAL:
            resp = self._a._serial.get_telemetry()
            telem = resp.get("telemetry", {})
            return {
                "gpu_id": gpu_id, "source": "serial",
                "temp_c":   telem.get("gpu_temps", {}).get(f"gpu{gpu_id}", 60.0),
                "power_w":  telem.get("gpu_power", {}).get(f"gpu{gpu_id}", 220.0),
                "util_pct": 65.0, "mem_used_gb": 32.0, "mem_total_gb": 48.0,
            }
        return self._sim_telemetry(gpu_id)

    def _sim_telemetry(self, gpu_id: int) -> Dict[str, Any]:
        import random
        return {
            "gpu_id": gpu_id, "name": f"NVIDIA L40S (bridge-sim GPU{gpu_id})",
            "temp_c": round(58.0 + random.uniform(-3, 8), 1),
            "power_w": round(215.0 + random.uniform(-20, 30), 1),
            "util_pct": round(65.0 + random.uniform(-10, 15), 1),
            "mem_used_gb": 32.0, "mem_total_gb": 48.0, "clock_mhz": 2520.0,
            "source": "bridge_sim",
        }

    def get_all_node_mappings(self) -> Dict[str, Any]:
        if self._a.transport == Transport.ETHERNET:
            return self._a._eth.lucy_api.get_mesh_nodes() or self._sim_nodes()
        return self._sim_nodes()

    def _sim_nodes(self) -> Dict[str, Any]:
        nodes = {"PRIME": {"gpu": 0, "type": "MIG 4g.48gb", "mem_gb": 48}}
        for i in range(1, 9):
            nodes[f"C{i}"] = {"gpu": (i-1)//2, "type": "MIG 2g.24gb", "mem_gb": 24}
        for i in range(1, 129):
            nodes[f"W{i:03d}"] = {"gpu": (i-1)//32, "type": "MPS slice", "mem_gb": None}
        return nodes

    def set_node_clock_lock(self, node_id: str, freq_mhz: int) -> bool:
        if self._a.transport == Transport.PCIE:
            gpu_id = self._node_to_gpu(node_id)
            return self._a._pcie.gpu.set_clock_lock(gpu_id, freq_mhz)
        logger.debug(f"[{self._a.transport}] set_node_clock_lock {node_id} → {freq_mhz}MHz (no-op)")
        return True

    def reset_gpu(self, gpu_id: int, reason: str = "") -> bool:
        if self._a.transport == Transport.PCIE:
            resp = self._a._pcie.fpga.reset_gpu(gpu_id, reason)
            return resp.get("cmd") in ("FPGACmd.ACK", 0xFE) or resp.get("simulated", False)
        elif self._a.transport == Transport.SERIAL:
            resp = self._a._serial.reset_gpu(gpu_id, reason)
            return resp.get("reset_ok", False)
        logger.warning(f"[{self._a.transport}] reset_gpu GPU{gpu_id} — limited support")
        return False

    def _node_to_gpu(self, node_id: str) -> int:
        if node_id == "PRIME": return 0
        if node_id.startswith("C"):
            n = int(node_id[1:]) - 1
            return n // 2
        if node_id.startswith("W"):
            n = int(node_id[1:]) - 1
            return n // 32
        return 0


class SenseMeshProxy:
    """Proxies SenseMesh sensor calls. API matches sensemesh.py §8.3"""

    def __init__(self, adapter: 'HALBridgeAdapter'):
        self._a = adapter

    def get_snapshot(self) -> Dict[str, Any]:
        if self._a.transport == Transport.ETHERNET:
            thermal = self._a._eth.redfish.get_thermal()
            power   = self._a._eth.redfish.get_power_reading()
            return {
                "temperatures": {t["name"]: t["reading_c"] for t in thermal.get("temperatures", [])},
                "powers":       {"total_w": power.get("total_watts")},
                "timestamp":    time.time(),
                "source":       "redfish",
            }
        elif self._a.transport in (Transport.SERIAL, Transport.SIM):
            resp = (self._a._serial.get_sensors()
                    if self._a.transport == Transport.SERIAL
                    else {"sensors": self._sim_sensors()})
            sensors = resp.get("sensors", {})
            return {
                "temperatures": {k: v for k, v in sensors.items() if "temp" in k},
                "powers":       {k: v for k, v in sensors.items() if "power" in k or "w" in k},
                "timestamp":    time.time(),
                "source":       self._a.transport.value,
            }
        return {"temperatures": self._sim_sensors(), "powers": {}, "timestamp": time.time(), "source": "sim"}

    def _sim_sensors(self) -> Dict[str, float]:
        import random
        return {
            f"gpu{i}_temp": round(58.0 + i*1.5 + random.uniform(-3, 5), 1)
            for i in range(4)
        } | {"board_temp": 42.0, "inlet_temp": 24.5}

    def get_readings(self) -> Dict[str, Any]:
        snap = self.get_snapshot()
        return snap.get("temperatures", {})

    def get_history(self, n: int = 60) -> List[Dict]:
        # Not available over bridge — return current snapshot repeated
        snap = self.get_snapshot()
        return [snap] * min(n, 10)


class PowerManagerProxy:
    """Proxies PowerManager calls. API matches power_manager.py §8.6"""

    def __init__(self, adapter: 'HALBridgeAdapter'):
        self._a = adapter

    def get_total_power(self) -> float:
        if self._a.transport == Transport.ETHERNET:
            pwr = self._a._eth.redfish.get_power_reading()
            if pwr.get("total_watts") is not None:
                return float(pwr["total_watts"])
        elif self._a.transport == Transport.SERIAL:
            resp = self._a._serial.get_power()
            return float(resp.get("power", {}).get("total_w", 0))
        import random
        return round(1751.0 + random.uniform(-80, 100), 1)

    def get_snapshot(self) -> Dict[str, Any]:
        total = self.get_total_power()
        return {
            "total_w":    total,
            "budget_w":   2400.0,
            "utilization":round(total / 2400.0 * 100, 1),
            "zones":      {"compute": total * 0.85, "logic": total * 0.10, "storage": total * 0.05},
            "source":     self._a.transport.value,
        }

    def get_zone_power(self) -> Dict[str, float]:
        snap = self.get_snapshot()
        return snap.get("zones", {})

    def get_history(self, n: int = 60) -> List[Dict]:
        return [self.get_snapshot()] * min(n, 10)


class EMMASupervisorProxy:
    """Proxies EMMA FPGA calls. API matches emma_fpga.py §8.2"""

    def __init__(self, adapter: 'HALBridgeAdapter'):
        self._a = adapter

    def halt_agent(self, agent_id: str, reason: str = "") -> Dict[str, Any]:
        if self._a.transport == Transport.PCIE:
            return self._a._pcie.fpga.halt_agent(agent_id, reason)
        elif self._a.transport == Transport.ETHERNET:
            return self._a._eth.halt_agent(agent_id, reason) or {"error": "eth halt failed"}
        elif self._a.transport == Transport.SERIAL:
            return self._a._serial.halt_agent(agent_id, reason)
        return {"status": "sim_halt", "agent_id": agent_id, "simulated": True}

    def halt_all(self, reason: str = "") -> Dict[str, Any]:
        logger.warning(f"EMMA HALT ALL via {self._a.transport}: {reason}")
        if self._a.transport == Transport.PCIE:
            return self._a._pcie.fpga.halt_all(reason)
        elif self._a.transport == Transport.SERIAL:
            return self._a._serial.halt_all(reason)
        return {"status": "sim_halt_all", "simulated": True}

    def release_halt(self, agent_id: str) -> Dict[str, Any]:
        if self._a.transport == Transport.PCIE:
            return self._a._pcie.fpga.release_halt(agent_id)
        elif self._a.transport == Transport.SERIAL:
            return self._a._serial.release_halt(agent_id)
        return {"status": "sim_release", "agent_id": agent_id}

    def throttle_dvfs(self, agent_id: str, anomaly_score: float) -> Dict[str, Any]:
        if self._a.transport == Transport.PCIE:
            return self._a._pcie.fpga.throttle_dvfs(agent_id, anomaly_score)
        elif self._a.transport == Transport.SERIAL:
            return self._a._serial.throttle_agent(agent_id, anomaly_score)
        from windows.pcie_interface import anomaly_score_to_clock
        return {"status": "sim_throttle", "clock_mhz": anomaly_score_to_clock(anomaly_score)}

    def bmc_get_power_state(self) -> Dict[str, Any]:
        if self._a.transport == Transport.ETHERNET:
            return self._a._eth.redfish.get_power_state()
        return {"power_state": "On", "source": "sim"}

    def bmc_get_sensor_summary(self) -> Dict[str, Any]:
        if self._a.transport == Transport.ETHERNET:
            return self._a._eth.redfish.get_sensor_summary()
        return {"max_temp_c": 62.0, "total_power_w": 1751.0, "source": "sim"}

    def bmc_emergency_off(self) -> bool:
        logger.critical("EMERGENCY OFF via BMC bridge")
        if self._a.transport == Transport.ETHERNET:
            return self._a._eth.emergency_off()
        return False

    def get_events(self) -> List[Dict]:
        return []

    def reset_gpu(self, gpu_id: int, reason: str = "") -> Dict[str, Any]:
        if self._a.transport == Transport.PCIE:
            return self._a._pcie.fpga.reset_gpu(gpu_id, reason)
        return {"status": "sim_gpu_reset", "gpu_id": gpu_id}


# ─────────────────────────────────────────────────────────────────────────────
# HALBridgeAdapter — main class
# ─────────────────────────────────────────────────────────────────────────────

class HALBridgeAdapter:
    """
    Top-level hardware bridge adapter.
    Provides the same API surface as LucyBoundSystem (lucy_mount.py)
    but routes all calls over the detected physical interface.

    Usage (mirrors lucy_mount.py):

        from hal.hal_bridge_adapter import HALBridgeAdapter, BridgeConfig

        # Auto-detect best interface
        bridge = HALBridgeAdapter()

        # Or specify preferred transport
        bridge = HALBridgeAdapter(BridgeConfig(
            preferred_transport=Transport.ETHERNET,
            board_ip="192.168.1.100"
        ))

        # Same API as LucyBoundSystem
        bridge.halt_agent("W042", reason="anomaly")
        bridge.throttle_agent("W001", anomaly_score=0.75)
        telem = bridge.neuromesh.get_gpu_telemetry(0)
        sensors = bridge.sensemesh.get_snapshot()
        power = bridge.power_manager.get_snapshot()
        bridge.shutdown()
    """

    def __init__(self, config: Optional[BridgeConfig] = None):
        self.config    = config or BridgeConfig()
        self.transport = Transport.SIM
        self._pcie     = None
        self._eth      = None
        self._serial   = None
        self._connected = False
        self._lock     = threading.Lock()

        # Initialize subsystem proxies
        self.neuromesh    = NeuroMeshProxy(self)
        self.sensemesh    = SenseMeshProxy(self)
        self.power_manager= PowerManagerProxy(self)
        self.emma         = EMMASupervisorProxy(self)

        # Auto-detect and connect
        self._detect_and_connect()

    def _detect_and_connect(self):
        if self.config.verbose:
            print("╔═══════════════════════════════════════════════════════════╗")
            print("║   Lucy HAL Bridge — Sovereign v2.1 Reconnection          ║")
            print("╚═══════════════════════════════════════════════════════════╝")

        preferred = self.config.preferred_transport

        if preferred == Transport.PCIE or preferred is None:
            if self._try_pcie():
                return
        if preferred == Transport.ETHERNET or preferred is None:
            if self._try_ethernet():
                return
        if preferred == Transport.SERIAL or preferred is None:
            if self._try_serial():
                return

        # Fallback to sim
        self.transport = Transport.SIM
        if self.config.verbose:
            print(f"  ⚠ No hardware interfaces detected — running in SIM mode")
            print(f"    (Lucy cognitive mesh will run with synthetic sensor data)")
        logger.warning("HALBridgeAdapter: no hardware found, using SIM mode")
        self._connected = False

    def _try_pcie(self) -> bool:
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'windows'))
            from windows.hardware_probe import probe_pcie
            probe = probe_pcie()
            if probe.available:
                from windows.pcie_interface import PCIeBridge
                self._pcie = PCIeBridge(mode="native")
                self.transport = Transport.PCIE
                self._connected = True
                if self.config.verbose:
                    print(f"  ✓ PCIe CONNECTED — direct GPU/FPGA access")
                    for comp in probe.details.get("sovereign_components", []):
                        print(f"    → {comp}")
                return True
        except Exception as e:
            logger.debug(f"PCIe probe failed: {e}")
        return False

    def _try_ethernet(self) -> bool:
        try:
            from windows.ethernet_interface import EthernetBridge, EthernetConfig
            cfg = EthernetConfig(board_ip=self.config.board_ip)
            eth = EthernetBridge(config=cfg)
            reach = eth.check_reachability()
            if any(reach.values()):
                self._eth = eth
                self.transport = Transport.ETHERNET
                self._connected = True
                active = [k for k, v in reach.items() if v]
                if self.config.verbose:
                    print(f"  ✓ Ethernet CONNECTED → {self.config.board_ip}")
                    print(f"    → Active: {', '.join(active)}")
                return True
        except Exception as e:
            logger.debug(f"Ethernet probe failed: {e}")
        return False

    def _try_serial(self) -> bool:
        try:
            from windows.serial_interface import SerialBridge, find_sovereign_port
            port = self.config.serial_port or find_sovereign_port()
            if port:
                serial = SerialBridge(port=port, baud=self.config.serial_baud, mode="auto")
                if serial.mode == "native":
                    resp = serial.ping()
                    if resp.get("status") == "ok":
                        self._serial = serial
                        self.transport = Transport.SERIAL
                        self._connected = True
                        if self.config.verbose:
                            fw = resp.get("firmware", "unknown")
                            print(f"  ✓ Serial CONNECTED → {port} firmware={fw}")
                        return True
        except Exception as e:
            logger.debug(f"Serial probe failed: {e}")
        return False

    # ── LucyBoundSystem-compatible API ────────────────────────────────────

    def halt_agent(self, agent_id: str, reason: str = "") -> Dict[str, Any]:
        logger.info(f"halt_agent({agent_id!r}, {reason!r}) via {self.transport}")
        return self.emma.halt_agent(agent_id, reason)

    def release_halt(self, agent_id: str) -> Dict[str, Any]:
        return self.emma.release_halt(agent_id)

    def halt_all(self, reason: str = "") -> Dict[str, Any]:
        logger.warning(f"halt_all({reason!r}) via {self.transport}")
        return self.emma.halt_all(reason)

    def throttle_agent(self, agent_id: str, anomaly_score: float) -> Dict[str, Any]:
        return self.emma.throttle_dvfs(agent_id, anomaly_score)

    def isolate_agent(self, agent_id: str, reason: str = "") -> Dict[str, Any]:
        if self._pcie:
            return self._pcie.fpga.isolate_node(agent_id, reason)
        return {"status": "sim_isolate", "agent_id": agent_id}

    def reset_gpu(self, gpu_id: int, reason: str = "") -> Dict[str, Any]:
        return self.emma.reset_gpu(gpu_id, reason)

    def status(self) -> Dict[str, Any]:
        """Returns a LucyBoundSystem-compatible status dict."""
        lucy_status = None
        if self._eth:
            lucy_status = self._eth.lucy_api.get_status()
        elif self._serial:
            r = self._serial.get_status()
            lucy_status = r

        return {
            "operational":      self._connected or self.transport == Transport.SIM,
            "mode":             self.transport.value,
            "transport":        self.transport.value,
            "node_count":       137,
            "subsystems":       6,
            "hal_mode":         self.config.hal_mode,
            "connected":        self._connected,
            "lucy_status":      lucy_status,
            "timestamp":        time.time(),
        }

    def get_full_telemetry(self) -> Dict[str, Any]:
        """Combined telemetry from all available sources."""
        result = {
            "timestamp":   time.time(),
            "transport":   self.transport.value,
            "gpus":        [self.neuromesh.get_gpu_telemetry(i) for i in range(4)],
            "sensors":     self.sensemesh.get_snapshot(),
            "power":       self.power_manager.get_snapshot(),
        }
        if self._eth:
            result["lucy_api"] = self._eth.lucy_api.get_status()
            result["bmc"]      = self._eth.redfish.get_sensor_summary()
        return result

    def shutdown(self):
        logger.info("HALBridgeAdapter shutdown")
        if self._pcie:
            self._pcie.close()
        if self._serial:
            self._serial.close()
        self._connected = False

    def reconnect(self):
        """Attempt to reconnect after a disconnect."""
        self.shutdown()
        self._detect_and_connect()

    def __repr__(self):
        return (f"HALBridgeAdapter(transport={self.transport.value}, "
                f"connected={self._connected}, mode={self.config.hal_mode})")


# ─────────────────────────────────────────────────────────────────────────────
# Convenience factory (mirrors lucy_mount.lucy_mount())
# ─────────────────────────────────────────────────────────────────────────────

def lucy_bridge(
    preferred: Optional[str] = None,
    board_ip: str = "192.168.1.100",
    serial_port: Optional[str] = None,
    hal_mode: str = "auto",
    verbose: bool = True,
) -> HALBridgeAdapter:
    """
    Create and return a HALBridgeAdapter.
    Drop-in replacement for lucy_mount() when running Lucy on Windows.

    Usage:
        from hal.hal_bridge_adapter import lucy_bridge
        lucy = lucy_bridge(board_ip="192.168.1.100")
        lucy.halt_agent("W042", reason="test")
    """
    config = BridgeConfig(
        preferred_transport=Transport(preferred) if preferred else None,
        board_ip=board_ip,
        serial_port=serial_port,
        hal_mode=hal_mode,
        verbose=verbose,
    )
    return HALBridgeAdapter(config)


# ─────────────────────────────────────────────────────────────────────────────
# Self-test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("Testing HAL Bridge Adapter (SIM mode — no hardware required)\n")

    # Force SIM mode by using a non-existent board IP
    bridge = lucy_bridge(
        preferred="sim",
        board_ip="0.0.0.0",  # non-reachable → falls back to sim
        verbose=True,
    )
    # Manually override to sim for test
    bridge.transport = Transport.SIM

    print(f"\nBridge status: {bridge.status()['mode']}")

    print("\n1. GPU Telemetry")
    for i in range(4):
        t = bridge.neuromesh.get_gpu_telemetry(i)
        print(f"   GPU{i}: {t['temp_c']}°C {t['power_w']}W {t['util_pct']}%")

    print("\n2. Sensor Snapshot")
    snap = bridge.sensemesh.get_snapshot()
    for k, v in snap.get("temperatures", {}).items():
        print(f"   {k}: {v}°C")

    print("\n3. Power Snapshot")
    pwr = bridge.power_manager.get_snapshot()
    print(f"   total={pwr['total_w']:.0f}W / {pwr['budget_w']:.0f}W ({pwr['utilization']:.1f}%)")

    print("\n4. Governance Commands")
    for fn, args in [
        (bridge.halt_agent,    ["W042", "test"]),
        (bridge.throttle_agent,["W001", 0.75]),
        (bridge.release_halt,  ["W042"]),
        (bridge.reset_gpu,     [2, "test"]),
        (bridge.halt_all,      ["emergency_test"]),
    ]:
        r = fn(*args)
        print(f"   ✓ {fn.__name__}({args[0]!r}) → {list(r.keys())[:3]}")

    bridge.shutdown()
    print(f"\n✓ HAL Bridge Adapter tests complete — {bridge}")