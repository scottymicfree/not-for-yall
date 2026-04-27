"""
Lucy Ethernet Interface — Windows/Linux Network Bridge
=======================================================
Communicates with the Sovereign v2.1 board over Ethernet via:
  1. OpenBMC / Redfish REST API (HTTPS :443) — power, sensors, firmware
  2. IPMI over LAN (:623) — emergency power control
  3. Lucy OS FastAPI (:8000) — cognitive mesh, node status, governance
  4. SSH management (:2222) — shell access for HAL operations
  5. Prometheus metrics (:9100) — real-time telemetry scrape

This is the recommended interface when PCIe is not available
(e.g., Windows machine connected to Sovereign v2.1 via 10GbE).

The Ethernet interface provides:
  - Full Lucy OS API access (same as localhost on the board)
  - BMC Redfish: power state, sensor readings, fan control
  - IPMI: emergency shutdown, SOL console
  - Prometheus: GPU temps, power, network stats

Architecture:
  Windows Lucy App
       │
       │ 10GbE / management LAN
       ▼
  Sovereign v2.1 NIC
       ├── :443  → OpenBMC Redfish (hardware telemetry)
       ├── :623  → IPMI over LAN (emergency control)
       ├── :8000 → Lucy OS FastAPI (cognitive mesh API)
       ├── :2222 → SSH (HAL shell operations)
       └── :9100 → Prometheus (metrics scrape)
"""

import sys
import os
import time
import json
import logging
import asyncio
import threading
import urllib.request
import urllib.error
import urllib.parse
import ssl
import base64
import socket
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass

logger = logging.getLogger("lucy.bridge.ethernet")

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EthernetConfig:
    board_ip:         str   = "192.168.1.100"
    bmc_port:         int   = 443
    ipmi_port:        int   = 623
    lucy_api_port:    int   = 8000
    ssh_port:         int   = 2222
    prometheus_port:  int   = 9100
    bmc_username:     str   = "admin"
    bmc_password:     str   = "sovereign"
    lucy_api_timeout: float = 5.0
    bmc_timeout:      float = 8.0
    verify_ssl:       bool  = False   # Self-signed cert on BMC
    retry_attempts:   int   = 3
    retry_delay:      float = 1.0


# ─────────────────────────────────────────────────────────────────────────────
# OpenBMC / Redfish Client
# ─────────────────────────────────────────────────────────────────────────────

class RedfishClient:
    """
    Minimal Redfish REST client for OpenBMC on Sovereign v2.1.
    Supports: power state, sensor readings, fan control, emergency off.
    Uses only stdlib (no httpx/requests dependency).
    """

    REDFISH_BASE = "/redfish/v1"
    ENDPOINTS = {
        "chassis":    "/redfish/v1/Chassis/1",
        "system":     "/redfish/v1/Systems/1",
        "managers":   "/redfish/v1/Managers/1",
        "thermal":    "/redfish/v1/Chassis/1/Thermal",
        "power":      "/redfish/v1/Chassis/1/Power",
        "sensors":    "/redfish/v1/Chassis/1/Sensors",
        "event_log":  "/redfish/v1/Managers/1/LogServices/EventLog/Entries",
    }

    def __init__(self, config: EthernetConfig):
        self.config  = config
        self._session_token: Optional[str] = None
        self._ssl_ctx = ssl.create_default_context()
        if not config.verify_ssl:
            self._ssl_ctx.check_hostname = False
            self._ssl_ctx.verify_mode    = ssl.CERT_NONE

    def _base_url(self) -> str:
        return f"https://{self.config.board_ip}:{self.config.bmc_port}"

    def _auth_header(self) -> str:
        creds = f"{self.config.bmc_username}:{self.config.bmc_password}"
        return "Basic " + base64.b64encode(creds.encode()).decode()

    def _get(self, path: str, timeout: Optional[float] = None) -> Optional[Dict]:
        url = self._base_url() + path
        req = urllib.request.Request(url, headers={
            "Authorization": self._auth_header(),
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, context=self._ssl_ctx,
                                        timeout=timeout or self.config.bmc_timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.URLError as e:
            logger.warning(f"Redfish GET {path} failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Redfish GET {path} error: {e}")
            return None

    def _post(self, path: str, payload: dict) -> Optional[Dict]:
        url = self._base_url() + path
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Authorization": self._auth_header(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, context=self._ssl_ctx,
                                        timeout=self.config.bmc_timeout) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            logger.error(f"Redfish POST {path} error: {e}")
            return None

    def get_power_state(self) -> Dict[str, Any]:
        data = self._get(self.ENDPOINTS["system"])
        if data:
            return {
                "power_state": data.get("PowerState", "Unknown"),
                "status":      data.get("Status", {}),
                "bios_version":data.get("BiosVersion", ""),
                "model":       data.get("Model", "Sovereign v2.1"),
                "source":      "redfish",
            }
        return {"power_state": "Unknown", "source": "unavailable"}

    def get_thermal(self) -> Dict[str, Any]:
        data = self._get(self.ENDPOINTS["thermal"])
        if not data:
            return {"temperatures": [], "fans": [], "source": "unavailable"}
        temps = []
        for t in data.get("Temperatures", []):
            if t.get("ReadingCelsius") is not None:
                temps.append({
                    "name":        t.get("Name", ""),
                    "reading_c":   t.get("ReadingCelsius"),
                    "upper_thresh":t.get("UpperThresholdCritical"),
                    "status":      t.get("Status", {}).get("Health", "OK"),
                })
        fans = []
        for f in data.get("Fans", []):
            fans.append({
                "name":    f.get("Name", ""),
                "reading": f.get("Reading"),
                "units":   f.get("ReadingUnits", "RPM"),
            })
        return {"temperatures": temps, "fans": fans, "source": "redfish"}

    def get_power_reading(self) -> Dict[str, Any]:
        data = self._get(self.ENDPOINTS["power"])
        if not data:
            return {"total_watts": None, "source": "unavailable"}
        supplies = data.get("PowerSupplies", [])
        controls = data.get("PowerControl", [])
        total = None
        if controls:
            total = controls[0].get("PowerConsumedWatts")
        return {
            "total_watts":    total,
            "power_supplies": len(supplies),
            "source":         "redfish",
        }

    def get_sensor_summary(self) -> Dict[str, Any]:
        thermal = self.get_thermal()
        power   = self.get_power_reading()
        max_temp = max((t["reading_c"] for t in thermal["temperatures"] if t.get("reading_c")), default=None)
        return {
            "max_temp_c":    max_temp,
            "total_power_w": power.get("total_watts"),
            "fan_count":     len(thermal.get("fans", [])),
            "temp_count":    len(thermal.get("temperatures", [])),
            "source":        "redfish",
        }

    def emergency_power_off(self) -> bool:
        """Emergency power off via Redfish Reset action."""
        path = self.ENDPOINTS["system"] + "/Actions/ComputerSystem.Reset"
        result = self._post(path, {"ResetType": "ForceOff"})
        if result is not None:
            logger.critical("EMERGENCY POWER OFF sent via Redfish")
            return True
        logger.error("Emergency power off failed — Redfish unreachable")
        return False

    def graceful_shutdown(self) -> bool:
        path = self.ENDPOINTS["system"] + "/Actions/ComputerSystem.Reset"
        result = self._post(path, {"ResetType": "GracefulShutdown"})
        return result is not None

    def is_reachable(self) -> bool:
        data = self._get(self.REDFISH_BASE, timeout=3.0)
        return data is not None


# ─────────────────────────────────────────────────────────────────────────────
# Lucy OS API Client (FastAPI on :8000)
# ─────────────────────────────────────────────────────────────────────────────

class LucyAPIClient:
    """
    HTTP client for Lucy OS v5 FastAPI on the Sovereign board.
    Mirrors the same endpoints as the Vite proxy in lucy-dashboard.
    """

    def __init__(self, config: EthernetConfig):
        self.config = config
        self._base  = f"http://{config.board_ip}:{config.lucy_api_port}"

    def _get(self, path: str) -> Optional[Dict]:
        url = self._base + path
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.config.lucy_api_timeout) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            logger.warning(f"Lucy API GET {path} failed: {e}")
            return None

    def _post(self, path: str, payload: dict) -> Optional[Dict]:
        url  = self._base + path
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(url, data=data, method="POST",
                                       headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.config.lucy_api_timeout) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            logger.warning(f"Lucy API POST {path} failed: {e}")
            return None

    # ── AME endpoints ─────────────────────────────────────────────────────
    def get_status(self) -> Optional[Dict]:
        return self._get("/ame/status")

    def send_query(self, text: str, session_id: str = "bridge") -> Optional[Dict]:
        return self._post("/ame/query", {"text": text, "session_id": session_id})

    # ── LTE endpoints ─────────────────────────────────────────────────────
    def get_telemetry(self) -> Optional[Dict]:
        return self._get("/lte/telemetry/dashboard")

    # ── UNR5 endpoints ────────────────────────────────────────────────────
    def get_swarm_status(self) -> Optional[Dict]:
        return self._get("/unr5/status")

    # ── Mesh endpoints ────────────────────────────────────────────────────
    def get_mesh_nodes(self) -> Optional[Dict]:
        return self._get("/api/mesh/nodes")

    # ── Safety endpoints ──────────────────────────────────────────────────
    def halt_agent(self, agent_id: str, reason: str = "") -> Optional[Dict]:
        return self._post("/lucy/halt", {"agent_id": agent_id, "reason": reason})

    def is_reachable(self) -> bool:
        result = self._get("/ame/status")
        return result is not None


# ─────────────────────────────────────────────────────────────────────────────
# IPMI over LAN (minimal — emergency use only)
# ─────────────────────────────────────────────────────────────────────────────

class IPMIClient:
    """
    Minimal IPMI over LAN client for emergency power control.
    Uses ipmitool subprocess if available.
    """

    def __init__(self, config: EthernetConfig):
        self.config  = config
        self._available: Optional[bool] = None

    def _cmd(self, *args) -> Optional[str]:
        if self._available is False:
            return None
        base = [
            "ipmitool", "-I", "lanplus",
            "-H", self.config.board_ip,
            "-p", str(self.config.ipmi_port),
            "-U", self.config.bmc_username,
            "-P", self.config.bmc_password,
        ]
        try:
            r = subprocess.run(base + list(args), capture_output=True, text=True, timeout=10)
            self._available = True
            return r.stdout.strip() if r.returncode == 0 else None
        except FileNotFoundError:
            self._available = False
            logger.warning("ipmitool not found — IPMI commands unavailable")
            return None
        except Exception as e:
            logger.error(f"ipmitool error: {e}")
            return None

    def get_power_status(self) -> str:
        result = self._cmd("power", "status")
        return result or "unavailable"

    def power_off(self) -> bool:
        result = self._cmd("power", "off")
        return result is not None

    def power_on(self) -> bool:
        result = self._cmd("power", "on")
        return result is not None

    def get_sensor_list(self) -> List[Dict]:
        result = self._cmd("sdr", "type", "Temperature")
        if not result:
            return []
        sensors = []
        for line in result.splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3:
                sensors.append({"name": parts[0], "value": parts[1], "status": parts[2]})
        return sensors

    def is_available(self) -> bool:
        return self._available is not False


# ─────────────────────────────────────────────────────────────────────────────
# Prometheus Scraper
# ─────────────────────────────────────────────────────────────────────────────

class PrometheusClient:
    """
    Scrapes Prometheus metrics from the Sovereign board's node_exporter/dcgm_exporter.
    Parses the text format for GPU temperature, power, memory metrics.
    """

    def __init__(self, config: EthernetConfig):
        self.config = config
        self._base  = f"http://{config.board_ip}:{config.prometheus_port}"

    def scrape(self) -> Dict[str, float]:
        url = self._base + "/metrics"
        try:
            with urllib.request.urlopen(url, timeout=5.0) as resp:
                text = resp.read().decode()
            return self._parse_text(text)
        except Exception as e:
            logger.warning(f"Prometheus scrape failed: {e}")
            return {}

    def _parse_text(self, text: str) -> Dict[str, float]:
        metrics = {}
        for line in text.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            try:
                if " " in line:
                    key, val = line.rsplit(" ", 1)
                    key = key.split("{")[0].strip()
                    metrics[key] = float(val)
            except (ValueError, IndexError):
                pass
        return metrics

    def get_gpu_metrics(self) -> List[Dict]:
        raw = self.scrape()
        gpus = []
        for i in range(4):
            gpus.append({
                "gpu_id": i,
                "temp_c": raw.get(f"DCGM_FI_DEV_GPU_TEMP{{gpu=\"{i}\"}}", 0),
                "power_w": raw.get(f"DCGM_FI_DEV_POWER_USAGE{{gpu=\"{i}\"}}", 0),
                "util_pct": raw.get(f"DCGM_FI_DEV_GPU_UTIL{{gpu=\"{i}\"}}", 0),
                "mem_used": raw.get(f"DCGM_FI_DEV_FB_USED{{gpu=\"{i}\"}}", 0),
            })
        return gpus


# ─────────────────────────────────────────────────────────────────────────────
# EthernetBridge — unified interface
# ─────────────────────────────────────────────────────────────────────────────

class EthernetBridge:
    """
    Top-level Ethernet bridge — combines all sub-clients.
    Provides the same API surface as PCIeBridge for Lucy OS integration.
    """

    def __init__(self, config: Optional[EthernetConfig] = None, board_ip: Optional[str] = None):
        if config is None:
            config = EthernetConfig()
        if board_ip:
            config.board_ip = board_ip
        self.config     = config
        self.redfish    = RedfishClient(config)
        self.lucy_api   = LucyAPIClient(config)
        self.ipmi       = IPMIClient(config)
        self.prometheus = PrometheusClient(config)
        self._reachable: Optional[bool] = None
        logger.info(f"EthernetBridge → {config.board_ip}")

    def check_reachability(self) -> Dict[str, bool]:
        results = {
            "lucy_api": self.lucy_api.is_reachable(),
            "redfish":  self.redfish.is_reachable(),
            "ipmi":     False,
        }
        # Quick TCP check for IPMI
        try:
            s = socket.socket()
            s.settimeout(2)
            s.connect((self.config.board_ip, self.config.ipmi_port))
            s.close()
            results["ipmi"] = True
        except Exception:
            pass
        self._reachable = any(results.values())
        return results

    def get_full_status(self) -> Dict[str, Any]:
        """Combined status from all sources."""
        return {
            "timestamp":   time.time(),
            "board_ip":    self.config.board_ip,
            "lucy_status": self.lucy_api.get_status(),
            "telemetry":   self.lucy_api.get_telemetry(),
            "power_state": self.redfish.get_power_state(),
            "sensors":     self.redfish.get_sensor_summary(),
            "reachability":self.check_reachability(),
        }

    def halt_agent(self, agent_id: str, reason: str = "") -> Dict[str, Any]:
        """Route halt command through Lucy OS API over Ethernet."""
        result = self.lucy_api.halt_agent(agent_id, reason)
        if result:
            return result
        logger.warning("Lucy API halt failed — trying Redfish graceful shutdown")
        return {"error": "Lucy API unreachable", "agent_id": agent_id}

    def emergency_off(self) -> bool:
        """Last resort: cut power via BMC."""
        logger.critical(f"EMERGENCY OFF via BMC at {self.config.board_ip}")
        if self.redfish.emergency_power_off():
            return True
        return self.ipmi.power_off()

    def get_all_telemetry(self) -> Dict[str, Any]:
        """GPU + mesh telemetry over Ethernet."""
        telem      = self.lucy_api.get_telemetry() or {}
        prom_gpus  = self.prometheus.get_gpu_metrics()
        return {
            "timestamp":     time.time(),
            "lucy_telemetry":telem,
            "gpu_metrics":   prom_gpus,
            "source":        "ethernet",
        }


# ─────────────────────────────────────────────────────────────────────────────
# Self-test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import subprocess
    logging.basicConfig(level=logging.INFO)
    print("=== Ethernet Interface Self-Test ===\n")

    config = EthernetConfig(board_ip="192.168.1.100")
    bridge = EthernetBridge(config=config)

    print("1. Reachability check (board may not be present):")
    reach = bridge.check_reachability()
    for k, v in reach.items():
        print(f"   {k:15s}: {'✓ reachable' if v else '✗ not found'}")

    print("\n2. FPGA Frame protocol test (offline):")
    frame = build_fpga_frame = __import__('pcie_interface', fromlist=['build_fpga_frame']).build_fpga_frame
    from pcie_interface import build_fpga_frame, FPGACmd, parse_fpga_frame
    f = build_fpga_frame(FPGACmd.HALT_AGENT, "W042", 0, 1)
    p = parse_fpga_frame(f)
    print(f"   ✓ Frame CRC OK: {p['crc_ok']} target={p['target']}")

    print("\n✓ Ethernet interface module loaded successfully")
    print("  (Connect Sovereign v2.1 at 192.168.1.100 for full test)")