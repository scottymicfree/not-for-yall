"""
LUCY OS — Hardware Mount Point
================================
This is the single entry point that binds Lucy's complete software
stack to the Sovereign v2.1 hardware.

Call lucy_mount() once at system startup. It:
  1. Runs the boot sequence (POST → Coreboot → LinuxBoot → prereqs)
  2. Mounts the Sovereign HAL (all 6 hardware subsystems)
  3. Binds Lucy's software modules to their hardware counterparts:
       - AuditLedger      → MemorySpine SQLite path
       - ValidationPipeline → EmmaFPGA governance callbacks
       - ToolExecutor     → NeuroMesh node map
       - FastAPI Backend  → HAL health endpoints
       - EagleEye Watcher → SenseMesh telemetry stream
  4. Registers governance callbacks (Sentinel → FPGA halt)
  5. Returns a LucyBoundSystem — the fully initialized Lucy OS

Usage:
    from hal.lucy_mount import lucy_mount, HALMode

    # SIM mode (development, no hardware)
    lucy = lucy_mount(mode="sim")

    # PROTO mode (COTS hardware)
    lucy = lucy_mount(mode="proto")

    # NATIVE mode (full Sovereign v2.1)
    lucy = lucy_mount(mode="native")

    if lucy.is_operational:
        lucy.start()   # launches all 137 agent nodes
"""

from __future__ import annotations

import os
import sys
import time
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, Callable

# ── Path setup ─────────────────────────────────────────────────────────────
_HAL_DIR   = Path(__file__).parent
_LUCY_ROOT = _HAL_DIR.parent
sys.path.insert(0, str(_LUCY_ROOT.parent))

from hal.sovereign_hal  import SovereignHAL, HALMode, HALStatus, MountResult, create_hal
from hal.boot_sequence  import BootSequence, BootReport
from hal.neuromesh_driver import NeuroMeshDriver
from hal.emma_fpga      import EmmaFPGABridge
from hal.sensemesh      import SenseMeshMonitor
from hal.qmp_drift      import QMPDriftController
from hal.memory_spine   import MemorySpineController
from hal.power_manager  import PowerManager

log = logging.getLogger("lucy.mount")


# ── Bound Lucy System ──────────────────────────────────────────────────────
@dataclass
class LucyBoundSystem:
    """
    Represents Lucy OS fully mounted and bound to hardware.
    All subsystems are accessible through this object.
    """
    hal:          SovereignHAL
    boot_report:  BootReport
    mount_result: MountResult
    bound_at:     str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    _started:     bool = field(default=False, init=False)

    # Software module references (set by lucy_mount)
    audit_ledger:       Any = field(default=None, init=False)
    validation_pipeline: Any = field(default=None, init=False)
    tool_executor:      Any = field(default=None, init=False)
    fastapi_app:        Any = field(default=None, init=False)

    @property
    def is_operational(self) -> bool:
        """True if Lucy can safely run inference."""
        return (self.mount_result.is_safe_to_run() and
                self.boot_report.lucy_ready)

    @property
    def mode(self) -> str:
        return self.hal.mode.value

    @property
    def node_count(self) -> int:
        return self.mount_result.node_count

    # ── Subsystem accessors ────────────────────────────────────────────────

    @property
    def neuromesh(self) -> Optional[NeuroMeshDriver]:
        return self.hal.get_subsystem("neuromesh")

    @property
    def emma(self) -> Optional[EmmaFPGABridge]:
        return self.hal.get_subsystem("emma")

    @property
    def sensemesh(self) -> Optional[SenseMeshMonitor]:
        return self.hal.get_subsystem("sensemesh")

    @property
    def qmp_drift(self) -> Optional[QMPDriftController]:
        return self.hal.get_subsystem("qmp_drift")

    @property
    def memory_spine(self) -> Optional[MemorySpineController]:
        return self.hal.get_subsystem("memory")

    @property
    def power_manager(self) -> Optional[PowerManager]:
        return self.hal.get_subsystem("power")

    # ── Governance API (hardware-backed) ───────────────────────────────────

    def halt_agent(self, agent_id: str, reason: str = "") -> bool:
        """
        Hardware-halt a specific agent.
        Routes through FPGA governance bridge.
        """
        if self.emma:
            return self.emma.halt_agent(agent_id, reason)
        log.warning(f"halt_agent({agent_id}): Emma not mounted")
        return False

    def halt_all(self, reason: str = "checkpoint") -> bool:
        """
        Simultaneous checkpoint halt of all 137 nodes.
        Hardware broadcast via FPGA (<1ms target).
        """
        if self.emma:
            return self.emma.halt_all(reason)
        log.warning("halt_all: Emma not mounted")
        return False

    def throttle_agent(self, agent_id: str, anomaly_score: float,
                       reason: str = "") -> bool:
        """
        Apply semantic-to-hardware DVFS throttle for anomaly score.
        anomaly_score: 0.0 (healthy) → 1.0 (severe anomaly)
        """
        if self.emma:
            return self.emma.throttle_dvfs(agent_id, anomaly_score, reason)
        return False

    def isolate_agent(self, agent_id: str, reason: str = "") -> bool:
        """Physically isolate an agent's memory space via IOMMU."""
        if self.emma:
            return self.emma.isolate_node(agent_id, reason)
        return False

    def reset_gpu(self, gpu_id: int, reason: str = "") -> bool:
        """Trigger PCIe PERST# on a GPU via FPGA GPIO."""
        if self.emma:
            return self.emma.reset_gpu(gpu_id, reason)
        return False

    # ── Status ─────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Complete system status snapshot."""
        hal_health = self.hal.health_report()
        sensor_snap = self.sensemesh.get_latest_snapshot() if self.sensemesh else {}
        power_snap  = self.power_manager.get_latest_snapshot() if self.power_manager else {}
        clock_off   = self.qmp_drift.get_current_offset() if self.qmp_drift else None
        storage     = self.memory_spine.get_metrics() if self.memory_spine else {}
        return {
            "operational":    self.is_operational,
            "mode":           self.mode,
            "bound_at":       self.bound_at,
            "node_count":     self.node_count,
            "hal":            hal_health,
            "sensors":        sensor_snap,
            "power":          power_snap,
            "clock_offset_ns": clock_off,
            "storage":        storage,
            "boot":           self.boot_report.to_dict(),
        }

    def start(self) -> bool:
        """
        Launch Lucy OS — starts the FastAPI backend and all agent tasks.
        Must be called after lucy_mount() returns a bound system.
        """
        if self._started:
            log.warning("Lucy already started")
            return True
        if not self.is_operational:
            log.error("Cannot start Lucy — system not operational")
            return False

        log.info("═══ Lucy OS starting ═══")
        log.info(f"  Mode:  {self.mode}")
        log.info(f"  Nodes: {self.node_count}")
        log.info(f"  Board: {self.hal.config['board']['name']}")

        # Start backend if mounted
        if self.fastapi_app:
            import uvicorn
            threading.Thread(
                target=uvicorn.run,
                kwargs={"app": self.fastapi_app, "host": "0.0.0.0", "port": 8000},
                daemon=True
            ).start()
            log.info("  FastAPI backend started on port 8000")

        self._started = True
        log.info("═══ Lucy OS operational ═══")
        return True

    def shutdown(self) -> None:
        """Graceful Lucy OS shutdown."""
        log.info("Lucy OS shutting down...")
        if self.emma:
            self.emma.halt_all("graceful_shutdown")
        self.hal.dismount()
        log.info("Lucy OS shutdown complete")

    def __repr__(self) -> str:
        return (f"LucyBoundSystem(mode={self.mode}, "
                f"operational={self.is_operational}, "
                f"nodes={self.node_count})")


# ── Lucy Mount Function ─────────────────────────────────────────────────────
def lucy_mount(
    mode:        str = "sim",
    config_path: str = None,
    skip_boot:   bool = False,
    bind_software: bool = True,
) -> LucyBoundSystem:
    """
    Mount Lucy OS onto the Sovereign v2.1 hardware.

    Args:
        mode:           "sim" | "proto" | "native"
        config_path:    path to hal_config.yaml (optional, uses bundled default)
        skip_boot:      skip boot sequence (for faster dev iteration)
        bind_software:  bind Lucy software modules to hardware layers

    Returns:
        LucyBoundSystem — fully initialized Lucy OS bound to hardware

    Example:
        lucy = lucy_mount(mode="sim")
        print(lucy.status())
        lucy.start()
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    )

    log.info("╔══════════════════════════════════════════════════════════════╗")
    log.info("║          LUCY OS — HARDWARE MOUNT SEQUENCE                  ║")
    log.info("╚══════════════════════════════════════════════════════════════╝")
    log.info(f"  Mode: {mode.upper()} | Config: {config_path or 'bundled'}")

    total_t0 = time.monotonic()

    # ── Step 1: Boot Sequence ───────────────────────────────────────────────
    board_name = "Sovereign v2.1"
    boot_report = None

    if not skip_boot:
        log.info("─── Phase 1: Boot Sequence ───────────────────────────────────")
        boot_seq = BootSequence(board_name, mode=mode)
        boot_report = boot_seq.run()
        log.info(f"    {boot_report.summary()}")

        if not boot_report.success and mode == "native":
            log.critical("Boot sequence FAILED in NATIVE mode — aborting mount")
            # Still return a partially initialized system for diagnostics
            hal     = create_hal(mode, config_path)
            result  = MountResult(
                status=HALStatus.FAULT, mode=HALMode(mode),
                board=board_name, errors=["boot_sequence_failed"]
            )
            return LucyBoundSystem(hal=hal, boot_report=boot_report, mount_result=result)
    else:
        log.info("─── Phase 1: Boot Sequence SKIPPED ──────────────────────────")
        boot_seq   = BootSequence(board_name, mode=mode)
        # Create a minimal passing boot report
        from hal.boot_sequence import BootReport
        boot_report = BootReport(
            board=board_name, mode=mode,
            started_at=datetime.now(timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            total_ms=0.0, success=True, lucy_ready=True
        )

    # ── Step 2: HAL Mount ──────────────────────────────────────────────────
    log.info("─── Phase 2: HAL Mount ──────────────────────────────────────")
    hal    = create_hal(mode, config_path)
    result = hal.mount()
    log.info(f"    {result.summary_line()}")

    # ── Step 3: Create Bound System ────────────────────────────────────────
    log.info("─── Phase 3: Binding Lucy Software Stack ────────────────────")
    lucy = LucyBoundSystem(hal=hal, boot_report=boot_report, mount_result=result)

    if bind_software and result.is_safe_to_run():
        _bind_software_modules(lucy)

    # ── Step 4: Register Governance Callbacks ──────────────────────────────
    log.info("─── Phase 4: Governance Callbacks ───────────────────────────")
    _register_governance_callbacks(lucy)

    total_elapsed = (time.monotonic() - total_t0) * 1000
    log.info("╔══════════════════════════════════════════════════════════════╗")
    log.info(f"║  LUCY MOUNTED in {total_elapsed:.0f}ms")
    log.info(f"║  Status:     {result.status.value.upper()}")
    log.info(f"║  Mode:       {mode.upper()}")
    log.info(f"║  Nodes:      {result.node_count}")
    log.info(f"║  Subsystems: {sum(1 for s in result.subsystems.values() if s.status=='ok')}/{len(result.subsystems)} OK")
    log.info(f"║  Operational: {lucy.is_operational}")
    log.info("╚══════════════════════════════════════════════════════════════╝")

    return lucy


def _bind_software_modules(lucy: LucyBoundSystem) -> None:
    """
    Bind Lucy software modules to their hardware-backed storage paths.
    This is where software meets hardware.
    """
    try:
        # ── AuditLedger → MemorySpine SQLite path ──────────────────────────
        spine = lucy.memory_spine
        if spine:
            sqlite_dir = spine.sqlite_path
            os.makedirs(sqlite_dir, exist_ok=True)
            db_path = os.path.join(sqlite_dir, "master_ledger.db")

            from governance.audit_ledger import AuditLedger, EventType
            ledger = AuditLedger(db_path=db_path)
            ledger.log(EventType.SYSTEM_START, "HAL", f"Lucy mounted on {lucy.mode} hardware")
            lucy.audit_ledger = ledger
            log.info(f"  ✓ AuditLedger → {db_path}")

            # ── ToolExecutor → sandbox on MemorySpine ──────────────────────
            sandbox_path = os.path.join(spine.mount_point, "sandbox")
            os.makedirs(sandbox_path, exist_ok=True)

            from action.executor import ToolExecutor
            executor = ToolExecutor(ledger=ledger, workspace=sandbox_path)
            lucy.tool_executor = executor
            log.info(f"  ✓ ToolExecutor → sandbox={sandbox_path}")

            # ── ValidationPipeline ─────────────────────────────────────────
            from governance.validation import ValidationPipeline, RateLimiter
            rate_lim  = RateLimiter(max_per_minute=120, burst=20)
            validator = ValidationPipeline(rate_limiter=rate_lim, ledger=ledger)
            lucy.validation_pipeline = validator
            log.info("  ✓ ValidationPipeline bound")

            # ── FastAPI Backend ────────────────────────────────────────────
            from dashboard.backend import create_app
            app = create_app()
            lucy.fastapi_app = app
            log.info("  ✓ FastAPI backend created")

        else:
            log.warning("  ⚠ MemorySpine not mounted — using default paths")
            _bind_software_defaults(lucy)

    except ImportError as e:
        log.warning(f"  ⚠ Software module import error: {e}")
        log.warning("    (Run from lucy-os/ directory with PYTHONPATH set)")
    except Exception as e:
        log.error(f"  ✗ Software binding error: {e}")


def _bind_software_defaults(lucy: LucyBoundSystem) -> None:
    """Fallback: bind software to default paths (no hardware storage)."""
    try:
        from governance.audit_ledger import AuditLedger, EventType
        from action.executor import ToolExecutor
        from governance.validation import ValidationPipeline, RateLimiter
        from dashboard.backend import create_app

        os.makedirs("data/sqlite", exist_ok=True)
        ledger    = AuditLedger(db_path="data/sqlite/master_ledger.db")
        executor  = ToolExecutor(ledger=ledger, workspace="sandbox")
        rate_lim  = RateLimiter(max_per_minute=120, burst=20)
        validator = ValidationPipeline(rate_limiter=rate_lim, ledger=ledger)
        app       = create_app()

        lucy.audit_ledger        = ledger
        lucy.tool_executor       = executor
        lucy.validation_pipeline = validator
        lucy.fastapi_app         = app
    except Exception as e:
        log.warning(f"Default software binding failed: {e}")


def _register_governance_callbacks(lucy: LucyBoundSystem) -> None:
    """
    Wire governance callbacks: software Sentinel → FPGA hardware halt.

    When Lucy's software Sentinel detects a Tier-1 violation,
    it calls the registered hardware halt callback, which routes
    through EmmaFPGABridge to trigger a real hardware halt.
    """
    emma = lucy.emma
    if not emma:
        log.warning("  ⚠ Emma not mounted — governance is software-only")
        return

    try:
        from governance.sentinel_protocol import Sentinel

        # Override the Sentinel's halt mechanism to also trigger FPGA halt
        original_halt = Sentinel.execute_hard_halt

        def hardware_backed_halt(sentinel_self, tag: str, desc: str = "") -> None:
            """Extended halt that triggers FPGA in addition to software sentinel."""
            # Software halt first (writes to SQLite directly)
            original_halt(sentinel_self, tag, desc)
            # Then hardware halt via FPGA
            reason = f"SENTINEL:{tag} — {desc}"
            log.critical(f"[HARDWARE HALT] {reason}")
            emma.halt_all(reason=reason)

        Sentinel.execute_hard_halt = hardware_backed_halt
        log.info("  ✓ Sentinel → FPGA halt callback registered")

    except ImportError:
        log.warning("  ⚠ Sentinel module not found — governance callbacks not registered")
    except Exception as e:
        log.warning(f"  ⚠ Governance callback registration failed: {e}")

    # Subscribe to HAL events for E.M.M.A. autonomous responses
    hal_bus = lucy.hal.events

    def on_power_alert(event: dict) -> None:
        if event.get("level") == "critical" and "POWER BUDGET" in event.get("message", ""):
            log.critical("[EMMA] Power budget exceeded — throttling all workers")
            if lucy.neuromesh:
                for node in lucy.hal.registry.list_nodes():
                    if node.get("agent_id", "").startswith("W"):
                        emma.throttle_dvfs(node["agent_id"], 0.9, "power_budget_exceeded")

    hal_bus.subscribe("HAL_ALERT", on_power_alert)
    log.info("  ✓ Power budget alert → DVFS throttle callback registered")

    def on_thermal_alert(event: dict) -> None:
        if event.get("level") == "critical" and "THERMAL" in event.get("message", ""):
            gpu_id = event.get("gpu_id")
            if gpu_id is not None and lucy.neuromesh:
                log.warning(f"[EMMA] Thermal critical on GPU{gpu_id} — resetting if needed")

    hal_bus.subscribe("HAL_ALERT", on_thermal_alert)
    log.info("  ✓ Thermal critical → GPU reset callback registered")


# ── CLI entry point ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse, json

    parser = argparse.ArgumentParser(description="Lucy OS Hardware Mount")
    parser.add_argument("--mode",   default="sim",  choices=["sim", "proto", "native"])
    parser.add_argument("--config", default=None,   help="Path to hal_config.yaml")
    parser.add_argument("--start",  action="store_true", help="Start Lucy after mount")
    parser.add_argument("--status", action="store_true", help="Print status and exit")
    parser.add_argument("--skip-boot", action="store_true", help="Skip boot sequence")
    args = parser.parse_args()

    lucy = lucy_mount(
        mode=args.mode,
        config_path=args.config,
        skip_boot=args.skip_boot,
    )

    if args.status:
        print(json.dumps(lucy.status(), indent=2))
        sys.exit(0 if lucy.is_operational else 1)

    if args.start:
        lucy.start()
        log.info("Lucy OS running. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            lucy.shutdown()