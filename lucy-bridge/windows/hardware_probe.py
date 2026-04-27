"""
Lucy Hardware Probe — Windows Interface Detection
=================================================
Detects all available physical interfaces between the Windows host
and the Sovereign v2.1 board. Runs automatically at bridge startup
and reports the best available path for each subsystem.

Interface Priority (highest to lowest):
  1. PCIe (direct — lowest latency, highest bandwidth)
  2. Ethernet (10GbE to board BMC/Linux stack)
  3. USB 3.x (fallback — adequate for control plane)
  4. Serial/UART (last resort — basic command/control only)

Each interface returns an InterfaceStatus with:
  - available: bool
  - transport: str
  - latency_class: 'microsecond' | 'millisecond' | 'tens_of_ms'
  - bandwidth_class: 'high' | 'medium' | 'low'
  - details: dict
"""

import sys
import os
import subprocess
import socket
import time
import json
import struct
import logging
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any
from enum import Enum

logger = logging.getLogger("lucy.bridge.probe")


class InterfaceType(str, Enum):
    PCIE    = "pcie"
    ETH     = "ethernet"
    USB     = "usb"
    SERIAL  = "serial"
    NONE    = "none"


class LatencyClass(str, Enum):
    MICROSECOND  = "microsecond"    # <100µs   — PCIe DMA
    MILLISECOND  = "millisecond"    # 1–10ms   — GbE/10GbE
    TENS_OF_MS   = "tens_of_ms"     # 10–50ms  — USB 3.x
    HUNDREDS_MS  = "hundreds_of_ms" # >100ms   — Serial/UART


@dataclass
class InterfaceStatus:
    type: InterfaceType
    available: bool
    transport: str
    latency_class: LatencyClass
    bandwidth_mbps: float           # theoretical max
    details: Dict[str, Any]
    error: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d['type'] = self.type.value
        d['latency_class'] = self.latency_class.value
        return d


@dataclass
class ProbeResult:
    timestamp: float
    platform: str
    recommended_interface: InterfaceType
    recommended_reason: str
    interfaces: Dict[str, InterfaceStatus]
    sovereign_board_detected: bool
    lucy_hal_mode: str              # 'native' | 'proto' | 'sim'

    def best_interface(self) -> InterfaceStatus:
        priority = [InterfaceType.PCIE, InterfaceType.ETH, InterfaceType.USB, InterfaceType.SERIAL]
        for itype in priority:
            iface = self.interfaces.get(itype.value)
            if iface and iface.available:
                return iface
        return self.interfaces.get(InterfaceType.NONE.value, InterfaceStatus(
            type=InterfaceType.NONE, available=False, transport="none",
            latency_class=LatencyClass.HUNDREDS_MS, bandwidth_mbps=0, details={}
        ))


# ─────────────────────────────────────────────────────────────────────────────
# PCIe Detection
# ─────────────────────────────────────────────────────────────────────────────

# Sovereign v2.1 PCIe endpoint IDs
SOVEREIGN_PCIE_IDS = [
    {"vendor": "10DE", "device": None,  "desc": "NVIDIA L40S GPU"},        # NVIDIA
    {"vendor": "1604", "device": None,  "desc": "AMD Versal AI Edge FPGA"}, # Xilinx/AMD
    {"vendor": "10EE", "device": None,  "desc": "Xilinx FPGA"},
    {"vendor": "1000", "device": "0097", "desc": "Kioxia CM7 NVMe (LSI)"},
]

def probe_pcie() -> InterfaceStatus:
    """
    Windows: uses wmic/powershell to enumerate PCI devices.
    Linux: uses lspci.
    Looks for Sovereign v2.1 board components.
    """
    details: Dict[str, Any] = {
        "method": "unknown",
        "devices_found": [],
        "sovereign_components": [],
    }
    error = None

    try:
        if sys.platform == "win32":
            # PowerShell PnP device enumeration
            cmd = [
                "powershell", "-NoProfile", "-Command",
                "Get-PnpDevice | Where-Object {$_.Class -eq 'Display' -or "
                "$_.Class -eq 'Net' -or $_.InstanceId -like '*PCI*'} | "
                "Select-Object FriendlyName,InstanceId,Status | ConvertTo-Json"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            details["method"] = "powershell_pnp"
            if result.returncode == 0 and result.stdout.strip():
                try:
                    devices = json.loads(result.stdout)
                    if isinstance(devices, dict):
                        devices = [devices]
                    details["devices_found"] = [
                        {"name": d.get("FriendlyName",""), "id": d.get("InstanceId","")}
                        for d in devices if isinstance(d, dict)
                    ]
                    # Check for NVIDIA / Xilinx components
                    for dev in devices:
                        name = (dev.get("FriendlyName") or "").lower()
                        iid = (dev.get("InstanceId") or "").upper()
                        if any(sig in name for sig in ["nvidia", "l40", "l40s", "xilinx", "versal"]):
                            details["sovereign_components"].append(dev.get("FriendlyName",""))
                        for pid in SOVEREIGN_PCIE_IDS:
                            if pid["vendor"] in iid:
                                details["sovereign_components"].append(
                                    f"{pid['desc']} ({pid['vendor']})"
                                )
                except json.JSONDecodeError:
                    pass

            # Also try wmic for more detail
            wmic_cmd = ["wmic", "path", "Win32_PnPEntity", "get", "Name,DeviceID", "/format:csv"]
            try:
                wr = subprocess.run(wmic_cmd, capture_output=True, text=True, timeout=10)
                details["wmic_available"] = wr.returncode == 0
                if wr.returncode == 0:
                    for line in wr.stdout.splitlines():
                        lc = line.lower()
                        if any(sig in lc for sig in ["l40", "l40s", "versal", "xilinx", "kioxia", "cm7"]):
                            details["sovereign_components"].append(line.strip())
            except Exception:
                details["wmic_available"] = False

        else:
            # Linux: lspci
            result = subprocess.run(["lspci", "-nn"], capture_output=True, text=True, timeout=5)
            details["method"] = "lspci"
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    details["devices_found"].append(line)
                    lc = line.lower()
                    lid = line.upper()
                    if any(sig in lc for sig in ["l40", "l40s", "versal", "xilinx", "kioxia"]):
                        details["sovereign_components"].append(line.strip())
                    for pid in SOVEREIGN_PCIE_IDS:
                        if pid["vendor"] in lid:
                            details["sovereign_components"].append(line.strip())

        # Deduplicate
        details["sovereign_components"] = list(set(details["sovereign_components"]))
        sovereign_found = len(details["sovereign_components"]) > 0

        return InterfaceStatus(
            type=InterfaceType.PCIE,
            available=sovereign_found,
            transport="PCIe Gen4 x16 (direct DMA via WinUSB/KMDF or Linux sysfs)",
            latency_class=LatencyClass.MICROSECOND,
            bandwidth_mbps=64000,  # PCIe Gen4 x16 ~64 GB/s
            details=details,
            error=None if sovereign_found else "Sovereign v2.1 PCIe endpoints not detected on this host",
        )

    except Exception as e:
        error = str(e)
        return InterfaceStatus(
            type=InterfaceType.PCIE, available=False,
            transport="PCIe (probe failed)",
            latency_class=LatencyClass.MICROSECOND, bandwidth_mbps=64000,
            details=details, error=error,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Ethernet Detection
# ─────────────────────────────────────────────────────────────────────────────

# Default Sovereign v2.1 BMC / management IP
SOVEREIGN_DEFAULT_IPS = [
    "192.168.1.100",   # Default BMC IP
    "10.0.0.100",      # Alt management net
    "172.16.0.1",      # Alt private net
]
SOVEREIGN_PORTS = [
    (443,  "Redfish HTTPS"),
    (623,  "IPMI over LAN"),
    (8000, "Lucy OS FastAPI"),
    (2222, "SSH management"),
    (9100, "Prometheus metrics"),
]

def probe_ethernet(
    target_ips: Optional[List[str]] = None,
    timeout: float = 1.5
) -> InterfaceStatus:
    """
    Scans for Sovereign v2.1 board on the network.
    Tries default BMC IPs and Lucy OS API port.
    """
    if target_ips is None:
        target_ips = SOVEREIGN_DEFAULT_IPS

    details: Dict[str, Any] = {
        "scanned_ips": target_ips,
        "open_ports": {},
        "lucy_api_reachable": False,
        "bmc_reachable": False,
        "latency_ms": None,
    }

    found_ip = None
    best_latency = None

    for ip in target_ips:
        for port, desc in SOVEREIGN_PORTS:
            try:
                t0 = time.perf_counter()
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                result = sock.connect_ex((ip, port))
                latency_ms = (time.perf_counter() - t0) * 1000
                sock.close()

                if result == 0:
                    if ip not in details["open_ports"]:
                        details["open_ports"][ip] = []
                    details["open_ports"][ip].append({"port": port, "desc": desc, "latency_ms": round(latency_ms, 2)})
                    found_ip = ip
                    if best_latency is None or latency_ms < best_latency:
                        best_latency = latency_ms
                    if port == 8000:
                        details["lucy_api_reachable"] = True
                    if port in (443, 623):
                        details["bmc_reachable"] = True
            except Exception:
                pass

    details["latency_ms"] = round(best_latency, 2) if best_latency else None
    details["best_ip"] = found_ip

    available = found_ip is not None
    return InterfaceStatus(
        type=InterfaceType.ETH,
        available=available,
        transport=f"Ethernet → {found_ip or 'not found'} (10GbE management / BMC Redfish)",
        latency_class=LatencyClass.MILLISECOND,
        bandwidth_mbps=10000,  # 10GbE
        details=details,
        error=None if available else f"No Sovereign v2.1 endpoints found at {target_ips}",
    )


# ─────────────────────────────────────────────────────────────────────────────
# USB Detection
# ─────────────────────────────────────────────────────────────────────────────

SOVEREIGN_USB_IDS = [
    {"vid": "0x10DE", "desc": "NVIDIA USB debug"},
    {"vid": "0x0403", "desc": "FTDI USB-Serial (UART bridge)"},
    {"vid": "0x1D6B", "desc": "Linux Foundation USB"},   # USB gadget from board
    {"vid": "0x04B4", "desc": "Cypress USB bridge"},
    {"vid": "0x03FD", "desc": "Xilinx USB-JTAG"},
]

def probe_usb() -> InterfaceStatus:
    details: Dict[str, Any] = {
        "method": "unknown",
        "devices": [],
        "sovereign_devices": [],
    }

    try:
        if sys.platform == "win32":
            cmd = [
                "powershell", "-NoProfile", "-Command",
                "Get-PnpDevice -Class USB | Select-Object FriendlyName,InstanceId,Status | ConvertTo-Json"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            details["method"] = "powershell_pnp_usb"
            if result.returncode == 0 and result.stdout.strip():
                try:
                    devices = json.loads(result.stdout)
                    if isinstance(devices, dict):
                        devices = [devices]
                    for d in devices:
                        if isinstance(d, dict):
                            name = d.get("FriendlyName", "")
                            iid = (d.get("InstanceId") or "").upper()
                            details["devices"].append(name)
                            for uid in SOVEREIGN_USB_IDS:
                                if uid["vid"][2:].upper() in iid:
                                    details["sovereign_devices"].append(f"{name} [{uid['desc']}]")
                except json.JSONDecodeError:
                    pass
        else:
            # Linux: lsusb
            result = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5)
            details["method"] = "lsusb"
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    details["devices"].append(line)
                    for uid in SOVEREIGN_USB_IDS:
                        if uid["vid"][2:].lower() in line.lower():
                            details["sovereign_devices"].append(line.strip())

        details["sovereign_devices"] = list(set(details["sovereign_devices"]))
        available = len(details["sovereign_devices"]) > 0

        return InterfaceStatus(
            type=InterfaceType.USB,
            available=available,
            transport="USB 3.x (WinUSB/libusb — control plane, firmware updates)",
            latency_class=LatencyClass.TENS_OF_MS,
            bandwidth_mbps=625,  # USB 3.1 Gen1 ~5Gbps
            details=details,
            error=None if available else "No Sovereign v2.1 USB devices detected",
        )

    except Exception as e:
        return InterfaceStatus(
            type=InterfaceType.USB, available=False,
            transport="USB (probe failed)",
            latency_class=LatencyClass.TENS_OF_MS, bandwidth_mbps=625,
            details=details, error=str(e),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Serial/UART Detection
# ─────────────────────────────────────────────────────────────────────────────

def probe_serial() -> InterfaceStatus:
    """
    Scans for serial ports — UART bridge to board debug console.
    On Sovereign v2.1 this is typically COM port via FTDI or CP2102 USB-UART.
    """
    details: Dict[str, Any] = {
        "ports": [],
        "sovereign_ports": [],
    }

    try:
        try:
            import serial.tools.list_ports as list_ports
            ports = list(list_ports.comports())
            details["method"] = "pyserial"
            for p in ports:
                info = {
                    "device": p.device,
                    "description": p.description,
                    "hwid": p.hwid,
                    "manufacturer": p.manufacturer,
                }
                details["ports"].append(info)
                desc_lower = (p.description or "").lower()
                hwid_lower = (p.hwid or "").lower()
                if any(sig in desc_lower or sig in hwid_lower
                       for sig in ["ftdi", "cp210", "ch340", "uart", "serial", "0403", "10c4"]):
                    details["sovereign_ports"].append(info)
        except ImportError:
            # Fallback: Windows COM port scan via registry
            if sys.platform == "win32":
                cmd = [
                    "powershell", "-NoProfile", "-Command",
                    "[System.IO.Ports.SerialPort]::GetPortNames() | ConvertTo-Json"
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                details["method"] = "powershell_serialport"
                if result.returncode == 0 and result.stdout.strip():
                    try:
                        port_names = json.loads(result.stdout)
                        if isinstance(port_names, str):
                            port_names = [port_names]
                        details["ports"] = [{"device": p} for p in (port_names or [])]
                    except Exception:
                        pass
            else:
                import glob
                port_names = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyS*") + glob.glob("/dev/ttyACM*")
                details["method"] = "glob_dev"
                details["ports"] = [{"device": p} for p in port_names]
                details["sovereign_ports"] = [{"device": p} for p in port_names if "USB" in p]

        available = len(details["ports"]) > 0

        return InterfaceStatus(
            type=InterfaceType.SERIAL,
            available=available,
            transport=f"Serial/UART {[p.get('device','') for p in details['ports'][:3]]} (115200 baud, ASCII command protocol)",
            latency_class=LatencyClass.HUNDREDS_MS,
            bandwidth_mbps=0.115,  # 115200 baud
            details=details,
            error=None if available else "No serial ports found",
        )

    except Exception as e:
        return InterfaceStatus(
            type=InterfaceType.SERIAL, available=False,
            transport="Serial (probe failed)",
            latency_class=LatencyClass.HUNDREDS_MS, bandwidth_mbps=0.115,
            details=details, error=str(e),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Master Probe
# ─────────────────────────────────────────────────────────────────────────────

def run_probe(target_ips: Optional[List[str]] = None, verbose: bool = True) -> ProbeResult:
    """
    Run all interface probes and return a ProbeResult with recommendations.
    """
    if verbose:
        print("╔══════════════════════════════════════════════════════════╗")
        print("║   Lucy Hardware Probe — Sovereign v2.1 Interface Scan   ║")
        print("╚══════════════════════════════════════════════════════════╝")

    results = {}

    for label, probe_fn, args in [
        ("pcie",     probe_pcie,     []),
        ("ethernet", probe_ethernet, [target_ips] if target_ips else []),
        ("usb",      probe_usb,      []),
        ("serial",   probe_serial,   []),
    ]:
        if verbose:
            print(f"  Probing {label.upper():10s}...", end="", flush=True)
        iface = probe_fn(*args)
        results[label] = iface
        if verbose:
            status = "✓ FOUND" if iface.available else "✗ NOT FOUND"
            print(f" {status}  {iface.transport[:60]}")

    # Determine recommended interface
    priority = ["pcie", "ethernet", "usb", "serial"]
    recommended = InterfaceType.NONE
    reason = "No hardware interfaces detected — running in SIM mode"

    for key in priority:
        if results[key].available:
            recommended = InterfaceType(key)
            reasons = {
                "pcie":     "Direct PCIe connection — lowest latency, full bandwidth, real-time GPU/FPGA control",
                "ethernet": "Ethernet to BMC/Lucy OS stack — full API access, moderate latency",
                "usb":      "USB bridge — adequate for control plane, limited bandwidth",
                "serial":   "Serial/UART — basic command/control only, high latency",
            }
            reason = reasons[key]
            break

    # Detect if Sovereign board is present
    sovereign_detected = (
        results["pcie"].available or
        results["ethernet"].details.get("lucy_api_reachable") or
        results["ethernet"].details.get("bmc_reachable")
    )

    # Determine HAL mode
    if results["pcie"].available:
        hal_mode = "native"
    elif results["ethernet"].available or results["usb"].available:
        hal_mode = "proto"
    else:
        hal_mode = "sim"

    probe = ProbeResult(
        timestamp=time.time(),
        platform=sys.platform,
        recommended_interface=recommended,
        recommended_reason=reason,
        interfaces=results,
        sovereign_board_detected=sovereign_detected,
        lucy_hal_mode=hal_mode,
    )

    if verbose:
        print(f"\n  Recommended:  {recommended.value.upper()} — {reason}")
        print(f"  HAL Mode:     {hal_mode.upper()}")
        print(f"  Board Found:  {'YES ✓' if sovereign_detected else 'NO — will use SIM/PROTO mode'}")
        print()

    return probe


def probe_to_json(target_ips: Optional[List[str]] = None) -> str:
    result = run_probe(target_ips=target_ips, verbose=False)
    return json.dumps({
        "timestamp": result.timestamp,
        "platform": result.platform,
        "recommended_interface": result.recommended_interface.value,
        "recommended_reason": result.recommended_reason,
        "sovereign_board_detected": result.sovereign_board_detected,
        "lucy_hal_mode": result.lucy_hal_mode,
        "interfaces": {k: v.to_dict() for k, v in result.interfaces.items()},
    }, indent=2)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Lucy Hardware Probe")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--ip", nargs="+", help="Target IPs to scan", default=None)
    args = parser.parse_args()

    if args.json:
        print(probe_to_json(target_ips=args.ip))
    else:
        result = run_probe(target_ips=args.ip, verbose=True)
        print(f"Best interface: {result.best_interface().transport}")