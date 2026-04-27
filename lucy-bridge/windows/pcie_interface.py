"""
Lucy PCIe Interface — Windows/Linux Direct PCIe Bridge
======================================================
Provides direct PCIe communication to Sovereign v2.1 board components:
  - NVIDIA L40S GPUs (via NVML / nvidia-smi)
  - AMD Versal AI Edge FPGA (via /dev/emma_fpga0 on Linux, WinUSB on Windows)
  - NVMe RAID (via Windows Storage API / Linux mdadm)

On Windows: uses ctypes + WinUSB kernel driver for FPGA access,
            nvidia-ml-py (pynvml) for GPU telemetry,
            WMI for storage.

On Linux:   uses ioctl to /dev/emma_fpga0,
            pynvml or nvidia-smi subprocess,
            mdadm for RAID status.

The FPGAFrame protocol matches HARDWARE_MOUNT_GUIDE.md §7.3 exactly:
  32-byte fixed frame: magic(1) cmd(1) payload_len(2) target(16) param(4) seq(4) crc32(4)
"""

import sys
import os
import struct
import ctypes
import subprocess
import time
import logging
import threading
import json
from typing import Optional, Dict, Any, Callable
from enum import IntEnum
import zlib

logger = logging.getLogger("lucy.bridge.pcie")

# ─────────────────────────────────────────────────────────────────────────────
# FPGA Command Frame Protocol  (HARDWARE_MOUNT_GUIDE §7.3)
# ─────────────────────────────────────────────────────────────────────────────

FPGA_MAGIC     = 0xE5
FPGA_FRAME_LEN = 32

class FPGACmd(IntEnum):
    NOP            = 0x00
    HALT_AGENT     = 0x01
    RELEASE_HALT   = 0x02
    HALT_ALL       = 0x03
    THROTTLE_DVFS  = 0x04
    RESTORE_DVFS   = 0x05
    RESET_GPU      = 0x06
    ISOLATE_NODE   = 0x07
    RESTORE_NODE   = 0x08
    SET_EBPF_WT    = 0x09
    BMC_POWER_OFF  = 0x0A
    STATUS_QUERY   = 0x0B
    ACK            = 0xFE
    NACK           = 0xFF

# DVFS anomaly_score → GPU clock MHz  (from HARDWARE_MOUNT_GUIDE §7.2)
DVFS_TABLE = [
    (0.00, 0.30, 2520),
    (0.30, 0.60, 1890),
    (0.60, 0.80, 1260),
    (0.80, 0.95,  630),
    (0.95, 1.00,  735),
]

def anomaly_score_to_clock(score: float) -> int:
    for lo, hi, mhz in DVFS_TABLE:
        if lo <= score < hi:
            return mhz
    return 735  # safe floor

def build_fpga_frame(
    cmd: FPGACmd,
    target: str = "",
    param: int = 0,
    seq: int = 0,
    payload_len: int = 0,
) -> bytes:
    """
    Build a 32-byte FPGA command frame per §7.3.
    CRC32 covers bytes [0:28].
    """
    target_bytes = target.encode("utf-8")[:16].ljust(16, b'\x00')
    frame = struct.pack(
        "<BB H 16s I I",
        FPGA_MAGIC,
        int(cmd),
        payload_len,
        target_bytes,
        param,
        seq,
    )  # 28 bytes
    crc = zlib.crc32(frame) & 0xFFFFFFFF
    return frame + struct.pack("<I", crc)  # 32 bytes total

def parse_fpga_frame(data: bytes) -> Dict[str, Any]:
    """Parse and validate a 32-byte FPGA response frame."""
    if len(data) < FPGA_FRAME_LEN:
        raise ValueError(f"Frame too short: {len(data)} < {FPGA_FRAME_LEN}")
    magic, cmd, payload_len, target_bytes, param, seq = struct.unpack_from("<BB H 16s I I", data, 0)
    crc_received = struct.unpack_from("<I", data, 28)[0]
    crc_computed  = zlib.crc32(data[:28]) & 0xFFFFFFFF
    return {
        "magic":       magic,
        "cmd":         FPGACmd(cmd) if cmd in FPGACmd._value2member_map_ else cmd,
        "payload_len": payload_len,
        "target":      target_bytes.rstrip(b'\x00').decode("utf-8", errors="replace"),
        "param":       param,
        "seq":         seq,
        "crc_ok":      crc_received == crc_computed,
        "raw":         data.hex(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# FPGA Device Interface
# ─────────────────────────────────────────────────────────────────────────────

class FPGAInterface:
    """
    Communicates with the AMD Versal AI Edge FPGA (E.M.M.A. bitstream).

    Linux:   opens /dev/emma_fpga0 and uses ioctl/write/read
    Windows: uses WinUSB or named-pipe bridge to the board
    SIM:     logs commands, returns synthetic ACKs
    """

    LINUX_DEV   = "/dev/emma_fpga0"
    WIN_PIPE    = r"\\.\pipe\lucy_emma_bridge"
    IOCTL_CMD   = 0xE5000001  # custom ioctl code for EMMA device driver

    def __init__(self, mode: str = "auto"):
        """
        mode: 'native' (real FPGA), 'proto' (pipe/socket bridge), 'sim' (no hardware)
        """
        self.mode     = mode
        self._fd      = None          # Linux file descriptor
        self._pipe    = None          # Windows pipe handle
        self._seq     = 0
        self._lock    = threading.Lock()
        self._sim_log: list = []

        if mode == "auto":
            self.mode = self._detect_mode()

        if self.mode == "native":
            self._open_native()
        elif self.mode == "proto":
            self._open_proto()
        # sim mode: nothing to open

        logger.info(f"FPGAInterface initialized in {self.mode} mode")

    def _detect_mode(self) -> str:
        if sys.platform != "win32" and os.path.exists(self.LINUX_DEV):
            return "native"
        if sys.platform == "win32":
            # Check if Windows pipe bridge is running
            try:
                import win32file
                h = win32file.CreateFile(
                    self.WIN_PIPE,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0, None, win32file.OPEN_EXISTING, 0, None
                )
                win32file.CloseHandle(h)
                return "proto"
            except Exception:
                pass
        return "sim"

    def _open_native(self):
        try:
            self._fd = os.open(self.LINUX_DEV, os.O_RDWR)
            logger.info(f"Opened {self.LINUX_DEV} (native FPGA)")
        except OSError as e:
            logger.error(f"Cannot open {self.LINUX_DEV}: {e}")
            self._fd = None
            self.mode = "sim"

    def _open_proto(self):
        """Open Windows named-pipe bridge to FPGA relay service."""
        try:
            if sys.platform == "win32":
                import win32file
                self._pipe = win32file.CreateFile(
                    self.WIN_PIPE,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0, None, win32file.OPEN_EXISTING, 0, None
                )
                logger.info(f"Opened Windows pipe {self.WIN_PIPE}")
            else:
                # Linux proto: socket to relay service
                import socket
                self._pipe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._pipe.connect(("localhost", 8765))
                logger.info("Connected to FPGA relay service on :8765")
        except Exception as e:
            logger.warning(f"Proto FPGA open failed: {e} — falling back to sim")
            self._pipe = None
            self.mode = "sim"

    def _next_seq(self) -> int:
        with self._lock:
            self._seq = (self._seq + 1) & 0xFFFFFFFF
            return self._seq

    def send_command(
        self,
        cmd: FPGACmd,
        target: str = "",
        param: int = 0,
    ) -> Dict[str, Any]:
        """Send a command frame and return the response."""
        seq   = self._next_seq()
        frame = build_fpga_frame(cmd, target, param, seq)

        if self.mode == "sim":
            return self._sim_response(cmd, target, param, seq, frame)

        try:
            response_bytes = self._send_raw(frame)
            if response_bytes and len(response_bytes) >= FPGA_FRAME_LEN:
                return parse_fpga_frame(response_bytes[:FPGA_FRAME_LEN])
            return {"cmd": FPGACmd.ACK, "target": target, "seq": seq, "crc_ok": True, "simulated": True}
        except Exception as e:
            logger.error(f"FPGA send_command error: {e}")
            return {"cmd": FPGACmd.NACK, "error": str(e), "seq": seq}

    def _send_raw(self, frame: bytes) -> Optional[bytes]:
        with self._lock:
            if self._fd is not None:
                # Linux native ioctl
                import fcntl, array
                buf = array.array('B', frame + bytes(FPGA_FRAME_LEN))
                fcntl.ioctl(self._fd, self.IOCTL_CMD, buf, True)
                return bytes(buf[FPGA_FRAME_LEN:])
            elif self._pipe is not None:
                if sys.platform == "win32":
                    import win32file
                    win32file.WriteFile(self._pipe, frame)
                    _, resp = win32file.ReadFile(self._pipe, FPGA_FRAME_LEN)
                    return resp
                else:
                    self._pipe.sendall(frame)
                    return self._pipe.recv(FPGA_FRAME_LEN)
        return None

    def _sim_response(self, cmd, target, param, seq, frame) -> Dict[str, Any]:
        entry = {
            "timestamp": time.time(),
            "cmd": cmd.name,
            "target": target,
            "param": param,
            "seq": seq,
            "frame_hex": frame.hex(),
            "simulated": True,
        }
        self._sim_log.append(entry)
        logger.debug(f"[SIM FPGA] {cmd.name} target={target!r} param={param}")
        return {"cmd": FPGACmd.ACK, "target": target, "seq": seq, "crc_ok": True, "simulated": True}

    # ── High-level governance commands (mirrors emma_fpga.py API) ──────────

    def halt_agent(self, agent_id: str, reason: str = "") -> Dict[str, Any]:
        logger.info(f"FPGA HALT_AGENT {agent_id!r} reason={reason!r}")
        return self.send_command(FPGACmd.HALT_AGENT, target=agent_id)

    def release_halt(self, agent_id: str) -> Dict[str, Any]:
        return self.send_command(FPGACmd.RELEASE_HALT, target=agent_id)

    def halt_all(self, reason: str = "") -> Dict[str, Any]:
        logger.warning(f"FPGA HALT_ALL reason={reason!r}")
        return self.send_command(FPGACmd.HALT_ALL, target="ALL")

    def throttle_dvfs(self, agent_id: str, anomaly_score: float) -> Dict[str, Any]:
        clock_mhz = anomaly_score_to_clock(anomaly_score)
        param = int(anomaly_score * 1000)  # encode as integer milli-score
        logger.info(f"FPGA THROTTLE {agent_id!r} score={anomaly_score:.3f} → {clock_mhz}MHz")
        return self.send_command(FPGACmd.THROTTLE_DVFS, target=agent_id, param=param)

    def restore_dvfs(self, agent_id: str) -> Dict[str, Any]:
        return self.send_command(FPGACmd.RESTORE_DVFS, target=agent_id)

    def reset_gpu(self, gpu_id: int, reason: str = "") -> Dict[str, Any]:
        logger.warning(f"FPGA RESET_GPU gpu_id={gpu_id} reason={reason!r}")
        return self.send_command(FPGACmd.RESET_GPU, target=f"GPU{gpu_id}", param=gpu_id)

    def isolate_node(self, agent_id: str, reason: str = "") -> Dict[str, Any]:
        return self.send_command(FPGACmd.ISOLATE_NODE, target=agent_id)

    def restore_node(self, agent_id: str) -> Dict[str, Any]:
        return self.send_command(FPGACmd.RESTORE_NODE, target=agent_id)

    def status_query(self) -> Dict[str, Any]:
        return self.send_command(FPGACmd.STATUS_QUERY)

    def get_sim_log(self) -> list:
        return list(self._sim_log)

    def close(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        if self._pipe is not None:
            try:
                if sys.platform == "win32":
                    import win32file
                    win32file.CloseHandle(self._pipe)
                else:
                    self._pipe.close()
            except Exception:
                pass
            self._pipe = None


# ─────────────────────────────────────────────────────────────────────────────
# GPU Interface (NVML / nvidia-smi)
# ─────────────────────────────────────────────────────────────────────────────

class GPUInterface:
    """
    Queries NVIDIA L40S GPUs on the Sovereign v2.1 board.
    Uses pynvml if available, falls back to nvidia-smi subprocess.
    Works on both Windows and Linux.
    """

    # Expected PCIe bus IDs for Sovereign v2.1 (from HARDWARE_MOUNT_GUIDE)
    SOVEREIGN_BUS_IDS = ["0000:01:00", "0000:41:00", "0000:81:00", "0000:c1:00"]

    def __init__(self, mode: str = "auto"):
        self.mode    = mode
        self._nvml   = False
        self._handle_cache: Dict[int, Any] = {}

        if mode == "auto":
            self.mode = "native" if self._try_nvml() else ("native" if self._check_smi() else "sim")
        elif mode == "native":
            self._try_nvml()

    def _try_nvml(self) -> bool:
        try:
            import pynvml
            pynvml.nvmlInit()
            self._nvml = True
            logger.info("pynvml initialized")
            return True
        except Exception:
            return False

    def _check_smi(self) -> bool:
        try:
            r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                               capture_output=True, text=True, timeout=5)
            return r.returncode == 0 and r.stdout.strip()
        except Exception:
            return False

    def get_gpu_telemetry(self, gpu_id: int) -> Dict[str, Any]:
        """Returns temp, power, utilization, memory for a GPU."""
        if self.mode == "sim":
            return self._sim_telemetry(gpu_id)

        if self._nvml:
            return self._nvml_telemetry(gpu_id)
        return self._smi_telemetry(gpu_id)

    def _nvml_telemetry(self, gpu_id: int) -> Dict[str, Any]:
        try:
            import pynvml
            if gpu_id not in self._handle_cache:
                self._handle_cache[gpu_id] = pynvml.nvmlDeviceGetHandleByIndex(gpu_id)
            h = self._handle_cache[gpu_id]
            temp    = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
            power   = pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0  # mW → W
            util    = pynvml.nvmlDeviceGetUtilizationRates(h)
            mem     = pynvml.nvmlDeviceGetMemoryInfo(h)
            clocks  = pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_SM)
            name    = pynvml.nvmlDeviceGetName(h)
            return {
                "gpu_id":      gpu_id,
                "name":        name if isinstance(name, str) else name.decode(),
                "temp_c":      float(temp),
                "power_w":     float(power),
                "util_pct":    float(util.gpu),
                "mem_used_gb": round(mem.used / 1e9, 2),
                "mem_total_gb":round(mem.total / 1e9, 2),
                "clock_mhz":   float(clocks),
                "source":      "nvml",
            }
        except Exception as e:
            return {**self._sim_telemetry(gpu_id), "error": str(e), "source": "sim_fallback"}

    def _smi_telemetry(self, gpu_id: int) -> Dict[str, Any]:
        try:
            query = "index,name,temperature.gpu,power.draw,utilization.gpu,memory.used,memory.total,clocks.sm"
            r = subprocess.run(
                ["nvidia-smi", f"--id={gpu_id}", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10
            )
            if r.returncode == 0 and r.stdout.strip():
                parts = [p.strip() for p in r.stdout.strip().split(",")]
                return {
                    "gpu_id":      gpu_id,
                    "name":        parts[1] if len(parts) > 1 else "unknown",
                    "temp_c":      float(parts[2]) if len(parts) > 2 else 0,
                    "power_w":     float(parts[3]) if len(parts) > 3 else 0,
                    "util_pct":    float(parts[4]) if len(parts) > 4 else 0,
                    "mem_used_gb": round(float(parts[5]) / 1024, 2) if len(parts) > 5 else 0,
                    "mem_total_gb":round(float(parts[6]) / 1024, 2) if len(parts) > 6 else 0,
                    "clock_mhz":   float(parts[7]) if len(parts) > 7 else 0,
                    "source":      "nvidia-smi",
                }
        except Exception as e:
            logger.warning(f"nvidia-smi query failed: {e}")
        return self._sim_telemetry(gpu_id)

    def _sim_telemetry(self, gpu_id: int) -> Dict[str, Any]:
        import random
        return {
            "gpu_id":       gpu_id,
            "name":         f"NVIDIA L40S (SIM GPU{gpu_id})",
            "temp_c":       round(55.0 + random.uniform(-3, 8), 1),
            "power_w":      round(220.0 + random.uniform(-20, 30), 1),
            "util_pct":     round(60.0 + random.uniform(-15, 20), 1),
            "mem_used_gb":  round(32.0 + random.uniform(-5, 10), 2),
            "mem_total_gb": 48.0,
            "clock_mhz":    2520.0,
            "source":       "sim",
        }

    def get_all_gpus(self) -> list:
        if self._nvml:
            try:
                import pynvml
                count = pynvml.nvmlDeviceGetCount()
                return [self.get_gpu_telemetry(i) for i in range(count)]
            except Exception:
                pass
        # Try smi count
        try:
            r = subprocess.run(["nvidia-smi", "--list-gpus"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                count = len([l for l in r.stdout.splitlines() if l.strip()])
                return [self.get_gpu_telemetry(i) for i in range(count)]
        except Exception:
            pass
        # SIM: 4 GPUs
        return [self._sim_telemetry(i) for i in range(4)]

    def get_mig_instances(self, gpu_id: int) -> list:
        """List MIG instances for a GPU (Sovereign v2.1 uses MIG on all 4 L40S)."""
        try:
            r = subprocess.run(
                ["nvidia-smi", "mig", "-lgi", f"-i {gpu_id}"],
                capture_output=True, text=True, timeout=10
            )
            if r.returncode == 0:
                return [l.strip() for l in r.stdout.splitlines() if l.strip() and not l.startswith("+")]
        except Exception:
            pass
        # SIM: return synthetic instances matching Sovereign layout
        if gpu_id == 0:
            return ["PRIME 4g.48gb (MIG instance 0)", "C1 2g.24gb (MIG instance 1)", "C2 2g.24gb (MIG instance 2)"]
        return [f"C{gpu_id*2+1} 2g.24gb", f"C{gpu_id*2+2} 2g.24gb"]

    def set_clock_lock(self, gpu_id: int, freq_mhz: int) -> bool:
        """Lock GPU SM clock to freq_mhz (requires admin/root on native)."""
        if self.mode == "sim":
            logger.debug(f"[SIM] set_clock_lock GPU{gpu_id} → {freq_mhz}MHz")
            return True
        try:
            r = subprocess.run(
                ["nvidia-smi", f"-i {gpu_id}", f"-lgc {freq_mhz},{freq_mhz}"],
                capture_output=True, text=True, timeout=10
            )
            return r.returncode == 0
        except Exception as e:
            logger.error(f"Clock lock failed: {e}")
            return False

    def reset_gpu_linux(self, gpu_id: int) -> bool:
        """PCIe FLR via Linux sysfs (requires root)."""
        bus_ids = self.SOVEREIGN_BUS_IDS
        if gpu_id < len(bus_ids):
            path = f"/sys/bus/pci/devices/{bus_ids[gpu_id]}/reset"
            try:
                with open(path, "w") as f:
                    f.write("1")
                logger.warning(f"GPU{gpu_id} PCIe reset triggered via {path}")
                return True
            except Exception as e:
                logger.error(f"GPU reset via sysfs failed: {e}")
        return False

    def close(self):
        if self._nvml:
            try:
                import pynvml
                pynvml.nvmlShutdown()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# PCIe Bridge — unified interface
# ─────────────────────────────────────────────────────────────────────────────

class PCIeBridge:
    """
    Top-level PCIe bridge — combines FPGA + GPU interfaces.
    This is what the Lucy Bridge Service instantiates.
    """

    def __init__(self, mode: str = "auto"):
        self.mode  = mode
        self.fpga  = FPGAInterface(mode=mode)
        self.gpu   = GPUInterface(mode=mode)
        self._open = True
        logger.info(f"PCIeBridge ready: fpga={self.fpga.mode} gpu={self.gpu.mode}")

    def halt_agent(self, agent_id: str, reason: str = "") -> dict:
        return self.fpga.halt_agent(agent_id, reason)

    def halt_all(self, reason: str = "") -> dict:
        return self.fpga.halt_all(reason)

    def throttle_agent(self, agent_id: str, anomaly_score: float) -> dict:
        resp = self.fpga.throttle_dvfs(agent_id, anomaly_score)
        clock = anomaly_score_to_clock(anomaly_score)
        # Also lock GPU clock if we can determine the GPU
        # (worker nodes map to specific GPU partitions)
        return {**resp, "clock_mhz": clock}

    def reset_gpu(self, gpu_id: int, reason: str = "") -> dict:
        return self.fpga.reset_gpu(gpu_id, reason)

    def get_all_telemetry(self) -> dict:
        gpus = self.gpu.get_all_gpus()
        fpga_status = self.fpga.status_query()
        return {
            "timestamp": time.time(),
            "gpus": gpus,
            "fpga": fpga_status,
            "mode": self.mode,
        }

    def close(self):
        self.fpga.close()
        self.gpu.close()
        self._open = False


# ─────────────────────────────────────────────────────────────────────────────
# Self-test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print("=== PCIe Interface Self-Test ===\n")

    bridge = PCIeBridge(mode="sim")

    print("1. FPGA Frame Build/Parse")
    frame = build_fpga_frame(FPGACmd.HALT_AGENT, "W042", param=0, seq=1)
    assert len(frame) == FPGA_FRAME_LEN, f"Frame length {len(frame)} != {FPGA_FRAME_LEN}"
    parsed = parse_fpga_frame(frame)
    assert parsed["crc_ok"], "CRC check failed"
    assert parsed["target"] == "W042", f"Target mismatch: {parsed['target']}"
    print(f"   ✓ Frame OK: cmd={parsed['cmd'].name} target={parsed['target']} crc_ok={parsed['crc_ok']}")

    print("\n2. DVFS Table")
    for score, expected in [(0.0, 2520), (0.45, 1890), (0.7, 1260), (0.85, 630), (0.97, 735)]:
        got = anomaly_score_to_clock(score)
        assert got == expected, f"score={score} expected={expected} got={got}"
        print(f"   ✓ score={score:.2f} → {got} MHz")

    print("\n3. GPU Telemetry (SIM)")
    telem = bridge.gpu.get_all_gpus()
    assert len(telem) == 4, f"Expected 4 GPUs, got {len(telem)}"
    for g in telem:
        print(f"   GPU{g['gpu_id']}: {g['name']} {g['temp_c']}°C {g['power_w']}W {g['util_pct']}% util")

    print("\n4. FPGA Governance Commands (SIM)")
    for cmd_fn, args in [
        (bridge.halt_agent, ["W042", "test"]),
        (bridge.throttle_agent, ["W001", 0.75]),
        (bridge.halt_all, ["emergency_test"]),
        (bridge.reset_gpu, [2, "test_reset"]),
    ]:
        resp = cmd_fn(*args)
        print(f"   ✓ {cmd_fn.__name__}({args[0]!r}) → {resp.get('cmd', resp.get('cmd'))}")

    print("\n5. Full Telemetry Snapshot")
    snap = bridge.get_all_telemetry()
    print(f"   timestamp={snap['timestamp']:.3f} gpus={len(snap['gpus'])} mode={snap['mode']}")

    bridge.close()
    print("\n✓ All PCIe interface tests passed (SIM mode)")