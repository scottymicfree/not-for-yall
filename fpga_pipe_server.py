"""
fpga_pipe_server.py — EMMA FPGA Named-Pipe Relay Server
=========================================================
Runs as a lightweight Windows service / background process that:
  1. Listens on Windows named pipe  \\.\pipe\lucy_emma_bridge
  2. Accepts clients (Lucy OS Windows app, pcie_interface.py, etc.)
  3. Decodes incoming 32-byte EMMA FPGA command frames
  4. Forwards them to the real hardware via the best available transport:
       Native  → /dev/emma_fpga0  ioctl  (Linux host via SSH tunnel)
       Proto   → Ethernet Redfish / Lucy API
       Serial  → UART FPGA bypass
       SIM     → synthetic ACK
  5. Returns 32-byte ACK frames to the client

Frame format (from HARDWARE_MOUNT_GUIDE §7.3):
  Byte  0    : magic   = 0xE5
  Byte  1    : cmd     (FPGACmd enum)
  Bytes 2-3  : payload_len (uint16 LE)
  Bytes 4-19 : target  (16-byte UTF-8, null-padded)
  Bytes 20-23: param   (uint32 LE)
  Bytes 24-27: seq     (uint32 LE)
  Bytes 28-31: crc32   (uint32 LE, over bytes 0-27)

Usage:
  python fpga_pipe_server.py                 # auto-detect transport
  python fpga_pipe_server.py --mode sim      # force simulation
  python fpga_pipe_server.py --mode native   # force native (SSH tunnel)
  python fpga_pipe_server.py --transport serial --port COM3
"""

from __future__ import annotations

import argparse
import logging
import os
import struct
import sys
import threading
import time
import zlib
from enum import IntEnum
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [fpga_pipe] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fpga_pipe_server")

# ── FRAME constants ────────────────────────────────────────────────────────────
FRAME_MAGIC      = 0xE5
FRAME_SIZE       = 32
FRAME_STRUCT     = struct.Struct("<BB H 16s I I I")   # 32 bytes exactly
ACK_CMD          = 0xAC
NACK_CMD         = 0xDE
PIPE_NAME        = r"\\.\pipe\lucy_emma_bridge"
MAX_CLIENTS      = 8

# ── FPGACmd enum ──────────────────────────────────────────────────────────────
class FPGACmd(IntEnum):
    NOP            = 0x00
    HALT_AGENT     = 0x01
    HALT_ALL       = 0x02
    THROTTLE_DVFS  = 0x03
    RESET_GPU      = 0x04
    ISOLATE_AGENT  = 0x05
    RESUME_AGENT   = 0x06
    SET_CLOCK      = 0x07
    GET_STATUS     = 0x10
    GET_TELEMETRY  = 0x11
    GET_SENSORS    = 0x12
    GET_POWER      = 0x13
    PING           = 0x20
    ACK            = 0xAC
    NACK           = 0xDE


def _crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def build_frame(cmd: int, target: str = "", param: int = 0,
                seq: int = 0, payload_len: int = 0) -> bytes:
    """Build a 32-byte EMMA FPGA command frame."""
    target_b = target.encode("utf-8")[:16].ljust(16, b"\x00")
    header   = FRAME_STRUCT.pack(FRAME_MAGIC, cmd, payload_len,
                                  target_b, param, seq, 0)
    crc      = _crc32(header[:28])
    return header[:28] + struct.pack("<I", crc)


def parse_frame(raw: bytes) -> Optional[dict]:
    """Parse a 32-byte frame. Returns None on bad magic/CRC."""
    if len(raw) < FRAME_SIZE:
        return None
    magic, cmd, payload_len, target_b, param, seq, recv_crc = FRAME_STRUCT.unpack(raw[:FRAME_SIZE])
    if magic != FRAME_MAGIC:
        return None
    calc_crc = _crc32(raw[:28])
    if calc_crc != recv_crc:
        log.warning(f"CRC mismatch: expected {calc_crc:#010x} got {recv_crc:#010x}")
        return None
    return {
        "cmd":         cmd,
        "cmd_name":    FPGACmd(cmd).name if cmd in FPGACmd._value2member_map_ else f"0x{cmd:02x}",
        "payload_len": payload_len,
        "target":      target_b.rstrip(b"\x00").decode("utf-8", errors="replace"),
        "param":       param,
        "seq":         seq,
        "crc":         recv_crc,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Transport backends
# ══════════════════════════════════════════════════════════════════════════════

class SimBackend:
    """Synthetic ACK for all commands."""
    _seq = 0

    def send_frame(self, frame_dict: dict) -> bytes:
        SimBackend._seq += 1
        log.debug(f"[SIM] cmd={frame_dict['cmd_name']} target={frame_dict['target']}")
        return build_frame(
            cmd=ACK_CMD,
            target=frame_dict["target"],
            param=frame_dict["param"],
            seq=SimBackend._seq,
            payload_len=0,
        )

    def close(self): pass


class SerialBackend:
    """Forward frames over UART (line-delimited JSON)."""

    def __init__(self, port: str, baud: int = 115200):
        import serial  # type: ignore
        self._ser = serial.Serial(port, baud, timeout=2.0)
        self._seq = 0
        log.info(f"Serial backend opened {port} @ {baud}")

    def send_frame(self, frame_dict: dict) -> bytes:
        import json
        self._seq += 1
        msg = {
            "cmd":    frame_dict["cmd_name"],
            "target": frame_dict["target"],
            "param":  frame_dict["param"],
            "seq":    self._seq,
        }
        self._ser.write((json.dumps(msg) + "\n").encode())
        line = self._ser.readline()
        try:
            resp = json.loads(line.decode().strip())
            ok = resp.get("ok", False)
        except Exception:
            ok = False
        return build_frame(
            cmd=ACK_CMD if ok else NACK_CMD,
            target=frame_dict["target"],
            param=frame_dict["param"],
            seq=self._seq,
        )

    def close(self):
        try: self._ser.close()
        except Exception: pass


class EthernetBackend:
    """Forward frames to Lucy Bridge Service over HTTP."""

    def __init__(self, base_url: str = "http://127.0.0.1:8765"):
        self._base = base_url.rstrip("/")
        self._seq  = 0
        # Verify connectivity
        try:
            import urllib.request
            with urllib.request.urlopen(f"{self._base}/health", timeout=2) as r:
                log.info(f"Ethernet backend connected to {self._base}")
        except Exception as e:
            log.warning(f"Ethernet backend health check failed: {e}")

    def send_frame(self, frame_dict: dict) -> bytes:
        import json, urllib.request, urllib.error
        self._seq += 1
        cmd_name = frame_dict["cmd_name"]

        # Map FPGA cmd → bridge endpoint
        endpoint_map = {
            "HALT_AGENT":    ("/halt_agent",    {"node_id": frame_dict["target"]}),
            "HALT_ALL":      ("/halt_all",      {"reason": "fpga_pipe"}),
            "THROTTLE_DVFS": ("/throttle_agent",{"node_id": frame_dict["target"],
                                                  "anomaly_score": frame_dict["param"] / 1000.0}),
            "RESET_GPU":     ("/reset_gpu",     {"gpu_index": frame_dict["param"]}),
            "ISOLATE_AGENT": ("/isolate_agent", {"node_id": frame_dict["target"],
                                                  "duration_s": frame_dict["param"]}),
            "PING":          ("/health",        None),
            "GET_STATUS":    ("/status",        None),
            "GET_TELEMETRY": ("/telemetry",     None),
        }

        ok = False
        if cmd_name in endpoint_map:
            path, body = endpoint_map[cmd_name]
            url = self._base + path
            try:
                if body is None:
                    req = urllib.request.Request(url)
                    with urllib.request.urlopen(req, timeout=5) as r:
                        ok = r.status == 200
                else:
                    data = json.dumps(body).encode()
                    req = urllib.request.Request(
                        url, data=data,
                        headers={"Content-Type": "application/json"},
                        method="POST"
                    )
                    with urllib.request.urlopen(req, timeout=5) as r:
                        ok = r.status == 200
            except urllib.error.HTTPError as e:
                log.warning(f"Ethernet cmd {cmd_name} HTTP {e.code}")
            except Exception as e:
                log.warning(f"Ethernet cmd {cmd_name} error: {e}")
        else:
            log.debug(f"No HTTP mapping for cmd {cmd_name}, sending ACK anyway")
            ok = True

        return build_frame(
            cmd=ACK_CMD if ok else NACK_CMD,
            target=frame_dict["target"],
            param=frame_dict["param"],
            seq=self._seq,
        )

    def close(self): pass


class NativeBackend:
    """
    Direct /dev/emma_fpga0 ioctl forwarding.
    On Windows: connects via SSH tunnel to Linux host running the board.
    On Linux:   writes/reads directly to the char device.
    """
    FPGA_DEV       = "/dev/emma_fpga0"
    FPGA_IOC_WRITE = 0x45530001   # _IOW('E','S',1)  — from emma_fpga.h
    FPGA_IOC_READ  = 0x45530002   # _IOR('E','S',2)

    def __init__(self):
        import platform
        self._is_windows = platform.system() == "Windows"
        self._seq = 0

        if self._is_windows:
            self._init_ssh_tunnel()
        else:
            self._init_ioctl()

    def _init_ssh_tunnel(self):
        """On Windows, open SSH tunnel to Linux host and forward ioctl via socket."""
        import socket
        # Lucy Bridge service runs a small TCP relay on port 8766
        self._sock = socket.create_connection(("127.0.0.1", 8766), timeout=5)
        log.info("Native backend: SSH tunnel socket connected on 127.0.0.1:8766")

    def _init_ioctl(self):
        """On Linux: open the FPGA char device directly."""
        self._fd = os.open(self.FPGA_DEV, os.O_RDWR)
        log.info(f"Native backend: opened {self.FPGA_DEV} fd={self._fd}")

    def send_frame(self, frame_dict: dict) -> bytes:
        self._seq += 1
        # Re-serialise original frame bytes for raw forwarding
        raw = build_frame(
            cmd        = frame_dict["cmd"],
            target     = frame_dict["target"],
            param      = frame_dict["param"],
            seq        = frame_dict["seq"],
            payload_len= frame_dict["payload_len"],
        )

        if self._is_windows:
            try:
                self._sock.sendall(raw)
                ack_raw = self._recv_exact(self._sock, FRAME_SIZE)
                parsed = parse_frame(ack_raw)
                if parsed and parsed["cmd"] == ACK_CMD:
                    return ack_raw
            except Exception as e:
                log.error(f"Native SSH tunnel error: {e}")
            # Fall back to NACK
            return build_frame(NACK_CMD, frame_dict["target"],
                               frame_dict["param"], self._seq)
        else:
            import fcntl
            try:
                fcntl.ioctl(self._fd, self.FPGA_IOC_WRITE, raw)
                ack = bytearray(FRAME_SIZE)
                fcntl.ioctl(self._fd, self.FPGA_IOC_READ, ack)
                return bytes(ack)
            except Exception as e:
                log.error(f"FPGA ioctl error: {e}")
                return build_frame(NACK_CMD, frame_dict["target"],
                                   frame_dict["param"], self._seq)

    @staticmethod
    def _recv_exact(sock, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Socket closed mid-frame")
            buf += chunk
        return buf

    def close(self):
        if self._is_windows:
            try: self._sock.close()
            except Exception: pass
        else:
            try: os.close(self._fd)
            except Exception: pass


# ══════════════════════════════════════════════════════════════════════════════
# Named-pipe server (Windows) / Unix-socket server (Linux)
# ══════════════════════════════════════════════════════════════════════════════

def _handle_client(conn, backend, addr=None):
    """Handle one pipe/socket client in its own thread."""
    log.info(f"Client connected: {addr or 'pipe'}")
    try:
        while True:
            # Read exactly 32 bytes per frame
            raw = _read_exact(conn, FRAME_SIZE)
            if raw is None:
                break

            frame = parse_frame(raw)
            if frame is None:
                log.warning("Received invalid frame, sending NACK")
                ack = build_frame(NACK_CMD)
                _send_all(conn, ack)
                continue

            log.info(
                f"FRAME cmd={frame['cmd_name']:<14} "
                f"target={frame['target']:<12} "
                f"param={frame['param']} seq={frame['seq']}"
            )

            try:
                ack = backend.send_frame(frame)
            except Exception as e:
                log.error(f"Backend error: {e}")
                ack = build_frame(NACK_CMD, frame["target"], frame["param"], frame["seq"])

            _send_all(conn, ack)

    except (ConnectionResetError, BrokenPipeError, EOFError):
        pass
    except Exception as e:
        log.error(f"Client handler error: {e}")
    finally:
        try: conn.close()
        except Exception: pass
        log.info("Client disconnected")


def _read_exact(conn, n: int) -> Optional[bytes]:
    """Read exactly n bytes; return None on EOF."""
    buf = b""
    while len(buf) < n:
        try:
            chunk = conn.recv(n - len(buf))
        except Exception:
            return None
        if not chunk:
            return None
        buf += chunk
    return buf


def _send_all(conn, data: bytes):
    total = 0
    while total < len(data):
        sent = conn.send(data[total:])
        if sent == 0:
            raise BrokenPipeError("socket closed")
        total += sent


# ── Windows named-pipe server ─────────────────────────────────────────────────

def run_pipe_server_windows(backend, pipe_name: str = PIPE_NAME):
    """
    Create a Windows named pipe and accept multiple clients.
    Uses win32pipe / win32file (pywin32).
    """
    try:
        import win32pipe   # type: ignore
        import win32file   # type: ignore
        import win32con    # type: ignore
        import pywintypes  # type: ignore
    except ImportError:
        log.error("pywin32 not installed. Install with: pip install pywin32")
        log.info("Falling back to TCP socket server on 127.0.0.1:8767")
        run_tcp_server(backend, port=8767)
        return

    log.info(f"Named pipe server listening on {pipe_name}")

    while True:
        try:
            handle = win32pipe.CreateNamedPipe(
                pipe_name,
                win32pipe.PIPE_ACCESS_DUPLEX,
                win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
                win32pipe.PIPE_UNLIMITED_INSTANCES,
                FRAME_SIZE * 16,   # out buffer
                FRAME_SIZE * 16,   # in  buffer
                0,                 # default timeout
                None               # security attributes
            )

            # Block until a client connects
            win32pipe.ConnectNamedPipe(handle, None)

            # Wrap handle in a file-like object
            class PipeConn:
                def __init__(self, h): self._h = h
                def recv(self, n):
                    try:
                        hr, data = win32file.ReadFile(self._h, n)
                        return data if hr == 0 else b""
                    except pywintypes.error:
                        return b""
                def send(self, data):
                    try:
                        win32file.WriteFile(self._h, data)
                        return len(data)
                    except pywintypes.error:
                        return 0
                def close(self):
                    try: win32file.CloseHandle(self._h)
                    except Exception: pass

            t = threading.Thread(
                target=_handle_client,
                args=(PipeConn(handle), backend, "pipe_client"),
                daemon=True
            )
            t.start()

        except Exception as e:
            log.error(f"Named pipe accept error: {e}")
            time.sleep(1)


# ── TCP socket server (cross-platform fallback) ───────────────────────────────

def run_tcp_server(backend, host: str = "127.0.0.1", port: int = 8767):
    """TCP socket server (Linux / fallback on Windows)."""
    import socket
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(MAX_CLIENTS)
    log.info(f"TCP frame relay listening on {host}:{port}")

    while True:
        try:
            conn, addr = srv.accept()
            t = threading.Thread(
                target=_handle_client,
                args=(conn, backend, f"{addr[0]}:{addr[1]}"),
                daemon=True
            )
            t.start()
        except Exception as e:
            log.error(f"TCP accept error: {e}")
            time.sleep(0.5)


# ══════════════════════════════════════════════════════════════════════════════
# Transport selector
# ══════════════════════════════════════════════════════════════════════════════

def _pick_backend(mode: str, serial_port: str = None,
                  bridge_url: str = "http://127.0.0.1:8765") -> object:
    if mode == "sim":
        log.info("Backend: SIM (synthetic)")
        return SimBackend()

    if mode == "native":
        try:
            b = NativeBackend()
            log.info("Backend: NATIVE (/dev/emma_fpga0 or SSH tunnel)")
            return b
        except Exception as e:
            log.warning(f"Native backend failed ({e}), falling back to Ethernet")
            mode = "proto"

    if mode == "proto":
        try:
            b = EthernetBackend(bridge_url)
            log.info("Backend: ETHERNET (via Lucy Bridge Service)")
            return b
        except Exception as e:
            log.warning(f"Ethernet backend failed ({e}), falling back to Serial")
            mode = "serial"

    if mode == "serial":
        if serial_port:
            try:
                b = SerialBackend(serial_port)
                log.info(f"Backend: SERIAL ({serial_port})")
                return b
            except Exception as e:
                log.warning(f"Serial backend failed ({e}), falling back to SIM")
        else:
            log.warning("No serial port specified for serial mode, falling back to SIM")

    # Auto-detect
    if mode == "auto":
        import platform
        if platform.system() != "Windows":
            if os.path.exists("/dev/emma_fpga0"):
                try:
                    return NativeBackend()
                except Exception:
                    pass
        # Try ethernet
        try:
            b = EthernetBackend(bridge_url)
            # Quick health check
            import urllib.request
            with urllib.request.urlopen(f"{bridge_url}/health", timeout=1):
                pass
            return b
        except Exception:
            pass
        # Try serial
        if serial_port:
            try:
                return SerialBackend(serial_port)
            except Exception:
                pass

    log.info("Backend: SIM (no hardware found)")
    return SimBackend()


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="EMMA FPGA Named-Pipe Relay Server")
    parser.add_argument("--mode",
                        choices=["auto", "sim", "proto", "native", "serial"],
                        default="auto")
    parser.add_argument("--transport",
                        choices=["pipe", "tcp"],
                        default="pipe",
                        help="Use named pipe (Windows) or TCP socket (cross-platform)")
    parser.add_argument("--port",       type=int,   default=8767,
                        help="TCP port (if --transport tcp)")
    parser.add_argument("--serial",     default=None,
                        help="Serial port e.g. COM3 or /dev/ttyUSB0")
    parser.add_argument("--bridge-url", default="http://127.0.0.1:8765",
                        help="URL of Lucy Bridge Service (for Ethernet backend)")
    args = parser.parse_args()

    import platform
    is_windows = platform.system() == "Windows"

    backend = _pick_backend(
        mode       = args.mode,
        serial_port= args.serial,
        bridge_url = args.bridge_url,
    )

    try:
        if args.transport == "pipe" and is_windows:
            run_pipe_server_windows(backend)
        else:
            run_tcp_server(backend, port=args.port)
    except KeyboardInterrupt:
        log.info("Shutting down FPGA pipe server")
    finally:
        backend.close()


if __name__ == "__main__":
    main()