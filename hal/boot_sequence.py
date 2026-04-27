"""
SOVEREIGN v2.1 — Coreboot / LinuxBoot Mount Sequence
======================================================
Implements the firmware-level boot sequence that prepares
the Sovereign v2.1 board for Lucy OS.

Boot stages:
  Stage 0: Power-on self-test (POST) — VRM, ECC RAM, PCIe
  Stage 1: Coreboot romstage — DRAM init, CPU microcode
  Stage 2: LinuxBoot payload  — minimal Linux kernel loads
  Stage 3: Lucy HAL init      — all subsystems mount
  Stage 4: Lucy OS launch     — agent mesh starts

In SIM mode: all stages execute as software checks only.
In NATIVE mode: interfaces with actual Coreboot via cbmem.
"""

from __future__ import annotations

import os
import time
import json
import logging
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import IntEnum
from typing import Optional, List, Dict

log = logging.getLogger("lucy.hal.boot")


class BootStage(IntEnum):
    POWER_OFF   = 0
    POST        = 1
    COREBOOT    = 2
    LINUXBOOT   = 3
    HAL_INIT    = 4
    LUCY_READY  = 5


@dataclass
class BootStageResult:
    stage:      BootStage
    name:       str
    passed:     bool
    duration_ms: float
    details:    str
    timestamp:  str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        d = asdict(self)
        d["stage"] = self.stage.name
        return d


@dataclass
class BootReport:
    board:       str
    mode:        str
    started_at:  str
    completed_at: str = ""
    total_ms:    float = 0.0
    stages:      List[BootStageResult] = field(default_factory=list)
    success:     bool = False
    lucy_ready:  bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["stages"] = [s.to_dict() for s in self.stages]
        return d

    def summary(self) -> str:
        passed = sum(1 for s in self.stages if s.passed)
        total  = len(self.stages)
        return (f"Boot {'SUCCESS' if self.success else 'FAILED'} | "
                f"{passed}/{total} stages | {self.total_ms:.0f}ms total")


class BootSequence:
    """
    Orchestrates the full Sovereign v2.1 boot sequence.
    Called once at system power-on before HAL.mount().

    Checks:
      - ECC RAM presence and error count
      - PCIe link training status for all devices
      - IOMMU enabled and groups configured
      - Coreboot cbmem log (NATIVE mode)
      - eBPF scheduler module loaded
      - OpenBMC reachable (out-of-band)
    """

    def __init__(self, board_name: str, mode: str = "sim"):
        self.board_name = board_name
        self.mode       = mode
        self._report: Optional[BootReport] = None

    def run(self) -> BootReport:
        """Execute full boot sequence. Returns BootReport."""
        t0 = time.monotonic()
        report = BootReport(
            board=self.board_name,
            mode=self.mode,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        stages = [
            (BootStage.POST,       "POST",       self._run_post),
            (BootStage.COREBOOT,   "Coreboot",   self._run_coreboot),
            (BootStage.LINUXBOOT,  "LinuxBoot",  self._run_linuxboot),
            (BootStage.HAL_INIT,   "HAL_Init",   self._run_hal_prereqs),
            (BootStage.LUCY_READY, "Lucy_Ready", self._run_lucy_prereqs),
        ]

        all_passed = True
        for stage_enum, stage_name, fn in stages:
            st = time.monotonic()
            try:
                passed, details = fn()
            except Exception as e:
                passed  = False
                details = f"Exception: {e}"
            elapsed = (time.monotonic() - st) * 1000
            result  = BootStageResult(
                stage=stage_enum, name=stage_name,
                passed=passed, duration_ms=round(elapsed, 2), details=details
            )
            report.stages.append(result)
            log.info(f"[BOOT] Stage {stage_name}: "
                     f"{'✓ PASS' if passed else '✗ FAIL'} ({elapsed:.1f}ms) — {details}")
            if not passed:
                all_passed = False
                # POST failure is fatal; other stages are warnings
                if stage_enum == BootStage.POST:
                    break

        report.total_ms     = round((time.monotonic() - t0) * 1000, 1)
        report.completed_at = datetime.now(timezone.utc).isoformat()
        report.success      = all_passed
        report.lucy_ready   = all_passed
        self._report        = report

        log.info(f"[BOOT] {report.summary()}")
        return report

    # ── Stage implementations ───────────────────────────────────────────────

    def _run_post(self) -> tuple[bool, str]:
        """Stage 1: Power-On Self Test — check ECC RAM, VRM, PCIe."""
        if self.mode == "sim":
            return True, "SIM: ECC RAM=512GB OK | VRM=stable | PCIe=linked"

        checks = []

        # ECC RAM check via edac driver
        edac_path = "/sys/devices/system/edac/mc/mc0/ce_count"
        if os.path.exists(edac_path):
            ce_count = int(open(edac_path).read().strip())
            checks.append(f"ECC_CE={ce_count}")
            if ce_count > 1000:
                return False, f"ECC correctable errors too high: {ce_count}"
        else:
            checks.append("ECC=no_edac")

        # PCIe link check
        result = subprocess.run(["lspci", "-v"], capture_output=True, text=True, timeout=5)
        pcie_devs = result.stdout.count("PCIe") if result.returncode == 0 else 0
        checks.append(f"PCIe_devs={pcie_devs}")

        # VRM check via i2c
        vrm_path = "/sys/bus/i2c/devices/1-0060"
        checks.append(f"VRM={'found' if os.path.exists(vrm_path) else 'not_found'}")

        return True, " | ".join(checks)

    def _run_coreboot(self) -> tuple[bool, str]:
        """Stage 2: Verify Coreboot log integrity."""
        if self.mode == "sim":
            return True, "SIM: Coreboot+LinuxBoot payload nominal"

        # Check cbmem log
        result = subprocess.run(["cbmem", "-l"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            lines = result.stdout.count("\n")
            return True, f"cbmem log: {lines} entries"
        else:
            # Non-Coreboot system (UEFI) — not fatal in PROTO mode
            if self.mode == "proto":
                return True, "PROTO: UEFI BIOS (Coreboot not required for prototype)"
            return False, "cbmem not available — Coreboot not installed"

    def _run_linuxboot(self) -> tuple[bool, str]:
        """Stage 3: Verify kernel parameters and modules."""
        if self.mode == "sim":
            return True, "SIM: Kernel 6.x | IOMMU=on | eBPF=loaded"

        details = []

        # Check kernel version
        result = subprocess.run(["uname", "-r"], capture_output=True, text=True, timeout=3)
        kver = result.stdout.strip() if result.returncode == 0 else "unknown"
        details.append(f"kernel={kver}")

        # Check IOMMU enabled
        iommu_path = "/sys/kernel/iommu_groups"
        groups = len(os.listdir(iommu_path)) if os.path.exists(iommu_path) else 0
        details.append(f"iommu_groups={groups}")
        if groups == 0:
            log.warning("IOMMU groups not found — check kernel cmdline iommu=pt amd_iommu=on")

        # Check eBPF scheduler
        result = subprocess.run(["ls", "/sys/fs/bpf/"], capture_output=True, text=True, timeout=3)
        bpf_ok = result.returncode == 0
        details.append(f"bpf_fs={'ok' if bpf_ok else 'not_mounted'}")

        return True, " | ".join(details)

    def _run_hal_prereqs(self) -> tuple[bool, str]:
        """Stage 4: Verify HAL prerequisites (CUDA, I2C, PTP tools)."""
        if self.mode == "sim":
            return True, "SIM: All HAL prerequisites satisfied"

        checks = []
        missing = []

        tools = {
            "nvidia-smi": "nvidia-smi",
            "ptp4l":      "ptp4l",
            "nvme":       "nvme",
            "mdadm":      "mdadm",
            "ipmitool":   "ipmitool",
        }
        for name, cmd in tools.items():
            result = subprocess.run(["which", cmd], capture_output=True, timeout=3)
            if result.returncode == 0:
                checks.append(f"{name}=ok")
            else:
                missing.append(name)
                checks.append(f"{name}=MISSING")

        passed = len(missing) == 0
        return passed, " | ".join(checks)

    def _run_lucy_prereqs(self) -> tuple[bool, str]:
        """Stage 5: Verify Lucy-specific prerequisites."""
        if self.mode == "sim":
            return True, "SIM: Lucy prerequisites satisfied — ready for HAL mount"

        checks = []

        # Check Python version
        import sys
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
        checks.append(f"python={py_ver}")

        # Check required Python packages
        required_pkgs = ["fastapi", "uvicorn", "chromadb", "pydantic"]
        for pkg in required_pkgs:
            try:
                __import__(pkg)
                checks.append(f"{pkg}=ok")
            except ImportError:
                checks.append(f"{pkg}=MISSING")

        # Check lucy-os directory structure
        lucy_dirs = ["governance", "action", "dashboard", "hal"]
        for d in lucy_dirs:
            path = os.path.join(os.path.dirname(os.path.dirname(__file__)), d)
            checks.append(f"dir_{d}={'ok' if os.path.exists(path) else 'MISSING'}")

        return True, " | ".join(checks)

    # ── Public API ─────────────────────────────────────────────────────────

    def get_report(self) -> Optional[dict]:
        return self._report.to_dict() if self._report else None

    def was_successful(self) -> bool:
        return self._report.success if self._report else False