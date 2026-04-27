"""
SOVEREIGN v2.1 — Lucy Hardware Abstraction Layer (HAL)
=======================================================
Central registry and base classes for all hardware subsystems.

Lucy mounts to the Sovereign board through this module.
Every subsystem (GPU mesh, FPGA governance, sensors, PTP, storage)
registers here and exposes a unified interface upward to Lucy's
software stack.

Mount flow:
    SovereignHAL.mount() ->
        NeuroMeshDriver.init()      # MIG partition 137 GPU nodes
        EmmaFPGABridge.init()       # FPGA governance link
        SenseMeshMonitor.init()     # I3C/I2C sensor bus
        QMPDriftController.init()   # PTP + DVFS
        MemorySpineController.init() # NVMe RAID
        PowerManager.init()         # VRM + thermal
    -> LucyMountPoint (bound, ready for inference)
"""

from __future__ import annotations

import os
import sys
import time
import logging
import threading
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Any, Dict, List, Callable

# ── Logging ────────────────────────────────────────────────────────────────
log = logging.getLogger("lucy.hal")


# ── HAL Mode ───────────────────────────────────────────────────────────────
class HALMode(str, Enum):
    """
    SIM    — pure software simulation (no hardware required, for dev/CI)
    PROTO  — COTS hardware (Supermicro H13 + RTX 4090s + Alveo FPGA)
    NATIVE — full Sovereign v2.1 custom PCB
    """
    SIM    = "sim"
    PROTO  = "proto"
    NATIVE = "native"


# ── HAL Status ─────────────────────────────────────────────────────────────
class HALStatus(str, Enum):
    UNMOUNTED   = "unmounted"
    MOUNTING    = "mounting"
    MOUNTED     = "mounted"
    DEGRADED    = "degraded"   # partial mount — some subsystems failed
    FAULT       = "fault"      # critical fault, Lucy cannot run safely
    DISMOUNTING = "dismounting"


# ── Subsystem Health ───────────────────────────────────────────────────────
@dataclass
class SubsystemHealth:
    name:       str
    status:     str          # "ok" | "degraded" | "fault" | "offline"
    mode:       str          # HALMode value
    message:    str  = ""
    last_check: str  = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metrics:    dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ── Base HAL Subsystem ─────────────────────────────────────────────────────
class HALSubsystem(ABC):
    """
    Abstract base for every hardware subsystem driver.
    All subsystems must implement: init(), health(), shutdown().
    """

    def __init__(self, name: str, config: dict, mode: HALMode):
        self.name   = name
        self.config = config
        self.mode   = mode
        self._ready = False
        self._lock  = threading.Lock()
        self.log    = logging.getLogger(f"lucy.hal.{name.lower()}")

    @abstractmethod
    def init(self) -> bool:
        """Initialize the subsystem. Returns True on success."""
        ...

    @abstractmethod
    def health(self) -> SubsystemHealth:
        """Return current health snapshot."""
        ...

    @abstractmethod
    def shutdown(self) -> None:
        """Clean shutdown of this subsystem."""
        ...

    @property
    def is_ready(self) -> bool:
        return self._ready

    def _sim_ok(self, metrics: dict = None) -> SubsystemHealth:
        """Convenience: return a healthy SIM health record."""
        return SubsystemHealth(
            name=self.name, status="ok", mode=HALMode.SIM,
            message=f"[SIM] {self.name} nominal",
            metrics=metrics or {}
        )


# ── HAL Event Bus ──────────────────────────────────────────────────────────
class HALEventBus:
    """
    Lightweight in-process pub/sub for hardware events.
    Subsystems publish events (thermal alerts, FPGA interrupts, etc.)
    Lucy's governance layer subscribes.
    """

    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}
        self._lock = threading.Lock()

    def subscribe(self, event_type: str, callback: Callable) -> None:
        with self._lock:
            self._subscribers.setdefault(event_type, []).append(callback)

    def publish(self, event_type: str, payload: dict) -> None:
        payload["_event_type"] = event_type
        payload["_timestamp"]  = datetime.now(timezone.utc).isoformat()
        callbacks = self._subscribers.get(event_type, []) + \
                    self._subscribers.get("*", [])   # wildcard subscribers
        for cb in callbacks:
            try:
                cb(payload)
            except Exception as e:
                log.error(f"HALEventBus: callback error for {event_type}: {e}")

    def publish_alert(self, source: str, level: str, message: str, **kwargs) -> None:
        self.publish("HAL_ALERT", {
            "source": source, "level": level,
            "message": message, **kwargs
        })


# ── Device Registry ────────────────────────────────────────────────────────
class DeviceRegistry:
    """
    Central registry of all hardware devices discovered during mount.
    Lucy queries this to find which PCIe bus address corresponds to
    which logical agent node (e.g. W042 → GPU1 MIG instance 5).
    """

    def __init__(self):
        self._devices: Dict[str, dict] = {}
        self._node_map: Dict[str, dict] = {}  # agent_id → hardware location
        self._lock = threading.Lock()

    def register_device(self, device_id: str, info: dict) -> None:
        with self._lock:
            self._devices[device_id] = {**info, "registered_at": datetime.now(timezone.utc).isoformat()}
        log.debug(f"DeviceRegistry: registered {device_id}")

    def register_node(self, agent_id: str, hw_location: dict) -> None:
        """Map a Lucy agent ID to its physical hardware location."""
        with self._lock:
            self._node_map[agent_id] = {
                **hw_location,
                "agent_id": agent_id,
                "bound_at": datetime.now(timezone.utc).isoformat()
            }

    def get_device(self, device_id: str) -> Optional[dict]:
        return self._devices.get(device_id)

    def get_node_hw(self, agent_id: str) -> Optional[dict]:
        """Return the hardware location for a given Lucy agent ID."""
        return self._node_map.get(agent_id)

    def list_devices(self, device_type: str = None) -> List[dict]:
        with self._lock:
            devs = list(self._devices.values())
        if device_type:
            devs = [d for d in devs if d.get("type") == device_type]
        return devs

    def list_nodes(self) -> List[dict]:
        with self._lock:
            return list(self._node_map.values())

    def summary(self) -> dict:
        with self._lock:
            return {
                "total_devices": len(self._devices),
                "total_nodes_mapped": len(self._node_map),
                "device_types": list({d.get("type","unknown") for d in self._devices.values()}),
            }


# ── Config Loader ──────────────────────────────────────────────────────────
def load_hal_config(path: str = None) -> dict:
    """
    Load hal_config.yaml. Falls back to bundled defaults.
    Override path via LUCY_HAL_CONFIG env var.
    """
    import yaml   # pyyaml

    config_path = (
        path
        or os.environ.get("LUCY_HAL_CONFIG")
        or str(Path(__file__).parent / "hal_config.yaml")
    )
    try:
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f)
        log.info(f"HAL config loaded from {config_path}")
        return cfg
    except FileNotFoundError:
        log.warning(f"HAL config not found at {config_path}, using minimal defaults")
        return _default_config()
    except Exception as e:
        log.error(f"HAL config load error: {e}")
        return _default_config()


def _default_config() -> dict:
    """Minimal safe defaults for SIM mode when no config file exists."""
    return {
        "board": {"name": "Sovereign v2.1 (defaults)", "revision": "RC1"},
        "neuromesh": {"total_nodes": 137, "gpus": [], "nvidia_smi_path": "/usr/bin/nvidia-smi"},
        "emma": {
            "fpga": {"char_device": "/dev/emma_fpga0", "rust_daemon_socket": "/run/emma/governance.sock"},
            "bmc": {"interface": "ipmi", "ipmi_host": "192.168.1.100"}
        },
        "sensemesh": {"i2c_buses": [], "polling_interval_ms": 100,
                      "alert_thresholds": {"temp_critical_c": 85, "power_critical_w": 2400}},
        "qmp_drift": {
            "ptp": {"hardware_clock": "/dev/ptp0", "sync_interval_ms": 10, "offset_threshold_ns": 100},
            "dvfs": {"enabled": True, "gpu_min_mhz": 1000, "gpu_max_mhz": 2520}
        },
        "memory_spine": {"nvme_devices": [], "raid": {"device": "/dev/md0", "mount_point": "/lucy/data"}},
        "power": {"total_budget_w": 2400, "emergency_throttle_w": 2200},
        "firmware": {"bios": "Coreboot + LinuxBoot", "kernel": "Linux 6.x hardened"},
    }


# ── Mount Result ───────────────────────────────────────────────────────────
@dataclass
class MountResult:
    status:      HALStatus
    mode:        HALMode
    board:       str
    mounted_at:  str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    subsystems:  Dict[str, SubsystemHealth] = field(default_factory=dict)
    node_count:  int = 0
    errors:      List[str] = field(default_factory=list)
    warnings:    List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def is_safe_to_run(self) -> bool:
        """Lucy can operate if MOUNTED or DEGRADED (with warnings)."""
        return self.status in (HALStatus.MOUNTED, HALStatus.DEGRADED)

    def summary_line(self) -> str:
        healthy = sum(1 for s in self.subsystems.values() if s.status == "ok")
        total   = len(self.subsystems)
        return (f"[{self.status.value.upper()}] {self.board} | "
                f"Mode={self.mode.value} | Subsystems={healthy}/{total} OK | "
                f"Nodes={self.node_count} | Errors={len(self.errors)}")


# ── SovereignHAL — Main Entry Point ───────────────────────────────────────
class SovereignHAL:
    """
    Top-level HAL. Lucy calls SovereignHAL.mount() once at startup.

    Usage:
        hal = SovereignHAL(mode=HALMode.SIM)
        result = hal.mount()
        if result.is_safe_to_run():
            lucy.bind(hal)

    In production (NATIVE mode), this initialises every physical
    subsystem on the Sovereign v2.1 board in the correct order
    and registers all 137 agent nodes in the DeviceRegistry.
    """

    def __init__(self, mode: HALMode = HALMode.SIM, config_path: str = None):
        self.mode     = mode
        self.config   = load_hal_config(config_path)
        self.registry = DeviceRegistry()
        self.events   = HALEventBus()
        self._status  = HALStatus.UNMOUNTED
        self._result: Optional[MountResult] = None
        self._subsystems: Dict[str, HALSubsystem] = {}
        self._mount_lock = threading.Lock()

        log.info(f"SovereignHAL created | mode={mode.value} | board={self.config['board']['name']}")

    # ── Public API ─────────────────────────────────────────────────────────

    def mount(self) -> MountResult:
        """
        Mount Lucy onto the Sovereign v2.1 hardware.
        Returns a MountResult describing the outcome.

        Mount order matters:
          1. Power Manager          (VRM must be stable before anything else)
          2. Memory Spine           (storage must be accessible early)
          3. SenseMesh              (telemetry must be live before GPU init)
          4. QMP Drift Controller   (clock must be locked before inference)
          5. NeuroMesh Driver       (GPU MIG partitioning — 137 nodes)
          6. Emma FPGA Bridge       (governance MUST be up before nodes run)
        """
        with self._mount_lock:
            if self._status == HALStatus.MOUNTED:
                log.warning("HAL already mounted — skipping")
                return self._result

            self._status = HALStatus.MOUNTING
            log.info(f"═══ Sovereign v2.1 Mount Sequence START (mode={self.mode.value}) ═══")
            t0 = time.monotonic()

            result = MountResult(
                status=HALStatus.MOUNTING,
                mode=self.mode,
                board=self.config["board"]["name"],
            )

            # Import subsystem drivers lazily (avoids hardware imports in SIM)
            from .power_manager    import PowerManager
            from .memory_spine     import MemorySpineController
            from .sensemesh        import SenseMeshMonitor
            from .qmp_drift        import QMPDriftController
            from .neuromesh_driver import NeuroMeshDriver
            from .emma_fpga        import EmmaFPGABridge

            mount_order = [
                ("power",      PowerManager(self.config.get("power", {}), self.mode, self.events)),
                ("memory",     MemorySpineController(self.config.get("memory_spine", {}), self.mode, self.events)),
                ("sensemesh",  SenseMeshMonitor(self.config.get("sensemesh", {}), self.mode, self.events)),
                ("qmp_drift",  QMPDriftController(self.config.get("qmp_drift", {}), self.mode, self.events)),
                ("neuromesh",  NeuroMeshDriver(self.config.get("neuromesh", {}), self.mode, self.events, self.registry)),
                ("emma",       EmmaFPGABridge(self.config.get("emma", {}), self.mode, self.events, self.registry)),
            ]

            for name, subsys in mount_order:
                self._subsystems[name] = subsys
                log.info(f"  → Initialising [{name}]...")
                try:
                    ok = subsys.init()
                    health = subsys.health()
                    result.subsystems[name] = health
                    if ok:
                        log.info(f"  ✓ [{name}] OK — {health.message}")
                    else:
                        log.warning(f"  ⚠ [{name}] DEGRADED — {health.message}")
                        result.warnings.append(f"{name}: {health.message}")
                except Exception as e:
                    log.error(f"  ✗ [{name}] FAULT — {e}")
                    result.errors.append(f"{name}: {str(e)}")
                    result.subsystems[name] = SubsystemHealth(
                        name=name, status="fault", mode=self.mode.value,
                        message=str(e)
                    )

            # Count mapped nodes
            result.node_count = len(self.registry.list_nodes())

            # Determine overall status
            fault_count = sum(1 for h in result.subsystems.values() if h.status == "fault")
            degraded_count = sum(1 for h in result.subsystems.values() if h.status == "degraded")

            if fault_count == 0 and degraded_count == 0:
                result.status = HALStatus.MOUNTED
            elif fault_count == 0:
                result.status = HALStatus.DEGRADED
            else:
                # Emma FPGA fault = hard FAULT (governance must be up)
                if result.subsystems.get("emma", SubsystemHealth("emma","ok","sim")).status == "fault":
                    result.status = HALStatus.FAULT
                else:
                    result.status = HALStatus.DEGRADED

            self._status = result.status
            self._result = result

            elapsed = (time.monotonic() - t0) * 1000
            log.info(f"═══ Mount Sequence COMPLETE in {elapsed:.1f}ms ═══")
            log.info(f"    {result.summary_line()}")

            return result

    def dismount(self) -> None:
        """Graceful shutdown of all subsystems in reverse order."""
        with self._mount_lock:
            if self._status == HALStatus.UNMOUNTED:
                return
            self._status = HALStatus.DISMOUNTING
            log.info("Sovereign HAL dismounting...")
            for name, subsys in reversed(list(self._subsystems.items())):
                try:
                    subsys.shutdown()
                    log.info(f"  ✓ [{name}] shutdown")
                except Exception as e:
                    log.error(f"  ✗ [{name}] shutdown error: {e}")
            self._status = HALStatus.UNMOUNTED
            log.info("Sovereign HAL unmounted.")

    def get_subsystem(self, name: str) -> Optional[HALSubsystem]:
        return self._subsystems.get(name)

    def health_report(self) -> dict:
        """Full health snapshot of all subsystems."""
        return {
            "hal_status":    self._status.value,
            "mode":          self.mode.value,
            "board":         self.config["board"]["name"],
            "node_count":    len(self.registry.list_nodes()),
            "subsystems":    {n: s.health().to_dict() for n, s in self._subsystems.items()},
            "registry":      self.registry.summary(),
            "timestamp":     datetime.now(timezone.utc).isoformat(),
        }

    @property
    def status(self) -> HALStatus:
        return self._status

    @property
    def is_mounted(self) -> bool:
        return self._status in (HALStatus.MOUNTED, HALStatus.DEGRADED)

    def __repr__(self) -> str:
        return f"SovereignHAL(mode={self.mode.value}, status={self._status.value})"


# ── Convenience factory ─────────────────────────────────────────────────────
def create_hal(mode: str = "sim", config_path: str = None) -> SovereignHAL:
    """
    Convenience factory used by lucy_mount.py.

    mode: "sim" | "proto" | "native"
    """
    try:
        m = HALMode(mode.lower())
    except ValueError:
        log.warning(f"Unknown HAL mode '{mode}', defaulting to SIM")
        m = HALMode.SIM
    return SovereignHAL(mode=m, config_path=config_path)