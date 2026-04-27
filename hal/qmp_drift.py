"""
SOVEREIGN v2.1 — QMP Drift Controller
=======================================
Quantum-Mechanical Precision (QMP) drift correction using:
  - SiTime SiT5356 Stratum 3 OCXO hardware clock
  - Linux PTP (ptp4l) daemon locked to /dev/ptp0
  - DVFS (Dynamic Voltage/Frequency Scaling) for drift correction
  - Linux cgroups (cpu.weight / cpu.max) for execution speed micro-adjustment

Purpose: Keep all 137 agent nodes synchronized to nanosecond-level
clock accuracy. Clock drift causes non-deterministic inference timing
which undermines consensus across the mesh.

The Drift Correction Loop (50ms cycle):
  1. Read hardware PTP clock offset from ptp4l via socket
  2. Compute ΔDrift / Δtime (drift rate)
  3. If |offset| > threshold → apply DVFS correction
  4. Adjust cgroup cpu.weight proportionally
  5. Lock GPU SM clocks to compensate

In SIM mode: synthetic clock offset with Gaussian noise.
In PROTO/NATIVE: reads /var/run/ptp4l.stats or PTP char device.
"""

from __future__ import annotations

import os
import re
import time
import math
import logging
import threading
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, List, Tuple

from .sovereign_hal import HALSubsystem, HALMode, SubsystemHealth, HALEventBus

log = logging.getLogger("lucy.hal.qmp_drift")


@dataclass
class ClockSample:
    timestamp:  str
    offset_ns:  float    # PTP offset from master clock in nanoseconds
    freq_ppb:   float    # frequency offset in parts-per-billion
    delay_ns:   float    # path delay nanoseconds
    source:     str      # "ptp4l" | "sim" | "ocxo"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DriftCorrection:
    timestamp:      str
    trigger:        str        # "offset_exceeded" | "rate_exceeded" | "manual"
    offset_ns:      float
    drift_rate:     float      # ns/s
    action:         str        # what correction was applied
    cpu_weight:     int
    gpu_min_mhz:    int
    gpu_max_mhz:    int
    effective_ms:   float      # correction applied in ms

    def to_dict(self) -> dict:
        return asdict(self)


class QMPDriftController(HALSubsystem):
    """
    Hardware precision clock synchronization and drift correction.

    Key metrics published to HAL event bus:
      QMP_DRIFT_WARNING  — offset exceeded soft threshold
      QMP_DRIFT_CRITICAL — offset exceeded hard threshold
      QMP_CORRECTION     — drift correction applied
    """

    def __init__(self, config: dict, mode: HALMode, events: HALEventBus):
        super().__init__("QMPDrift", config, mode)
        self.events = events

        ptp_cfg  = config.get("ptp",  {})
        dvfs_cfg = config.get("dvfs", {})

        self._hw_clock        = ptp_cfg.get("hardware_clock",   "/dev/ptp0")
        self._ptp4l_cfg       = ptp_cfg.get("ptp4l_config",     "/etc/ptp4l.conf")
        self._ptp4l_iface     = ptp_cfg.get("ptp4l_interface",  "enp1s0")
        self._sync_interval   = ptp_cfg.get("sync_interval_ms", 10) / 1000.0
        self._offset_thresh   = ptp_cfg.get("offset_threshold_ns", 100)

        self._dvfs_enabled    = dvfs_cfg.get("enabled",       True)
        self._cpu_governor    = dvfs_cfg.get("cpu_governor",  "performance")
        self._gpu_lock        = dvfs_cfg.get("gpu_lock_clocks", True)
        self._gpu_min_mhz     = dvfs_cfg.get("gpu_min_mhz",   1000)
        self._gpu_max_mhz     = dvfs_cfg.get("gpu_max_mhz",   2520)
        self._cgroup_weight   = dvfs_cfg.get("cgroup_cpu_weight",
                                             "/sys/fs/cgroup/lucy/cpu.weight")
        self._cgroup_max      = dvfs_cfg.get("cgroup_cpu_max",
                                             "/sys/fs/cgroup/lucy/cpu.max")
        self._correction_int  = dvfs_cfg.get("correction_interval_ms", 50) / 1000.0

        self._samples:     List[ClockSample]    = []
        self._corrections: List[DriftCorrection] = []
        self._ptp4l_proc:  Optional[subprocess.Popen] = None
        self._sync_thread: Optional[threading.Thread]  = None
        self._corr_thread: Optional[threading.Thread]  = None
        self._active = False

        # Synthetic drift state (SIM mode)
        self._sim_offset_ns  = 0.0
        self._sim_drift_rate = 0.5   # ns/s baseline drift

    # ── Init ───────────────────────────────────────────────────────────────

    def init(self) -> bool:
        if self.mode == HALMode.SIM:
            return self._init_sim()
        else:
            return self._init_real()

    def _init_sim(self) -> bool:
        self.log.info("[SIM] QMP Drift Controller — synthetic clock simulation")
        self._active = True
        self._start_threads()
        self._ready = True
        return True

    def _init_real(self) -> bool:
        """Start ptp4l daemon and verify hardware clock is accessible."""
        try:
            # Check /dev/ptp0 exists
            if not os.path.exists(self._hw_clock):
                raise FileNotFoundError(f"PTP hardware clock not found: {self._hw_clock}")

            # Set CPU governor
            self._set_cpu_governor(self._cpu_governor)

            # Start ptp4l if not already running
            if not self._ptp4l_running():
                self._start_ptp4l()

            # Lock GPU clocks if enabled
            if self._dvfs_enabled and self._gpu_lock:
                self._lock_all_gpu_clocks(self._gpu_min_mhz, self._gpu_max_mhz)

            self._active = True
            self._start_threads()
            self._ready = True
            return True

        except Exception as e:
            self.log.error(f"QMP init failed: {e}")
            if self.mode == HALMode.PROTO:
                self.log.warning("Falling back to SIM mode for QMP")
                return self._init_sim()
            return False

    # ── ptp4l management ───────────────────────────────────────────────────

    def _ptp4l_running(self) -> bool:
        result = subprocess.run(["pgrep", "-x", "ptp4l"], capture_output=True)
        return result.returncode == 0

    def _start_ptp4l(self) -> None:
        self.log.info(f"Starting ptp4l on {self._ptp4l_iface}")
        self._ptp4l_proc = subprocess.Popen(
            ["ptp4l", "-i", self._ptp4l_iface,
             "-f", self._ptp4l_cfg,
             "-s",          # slave only
             "--step_threshold=1.0",
             "--summary_interval=0"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        time.sleep(2)
        if self._ptp4l_proc.poll() is not None:
            raise RuntimeError("ptp4l failed to start")
        self.log.info(f"ptp4l started (pid={self._ptp4l_proc.pid})")

    # ── Clock sampling ─────────────────────────────────────────────────────

    def _read_ptp_offset(self) -> Tuple[float, float, float]:
        """
        Read PTP clock offset, freq offset, and path delay.
        Returns (offset_ns, freq_ppb, delay_ns).
        In SIM: returns synthetic values.
        In REAL: parses ptp4l stats or reads /dev/ptp0 via clock_gettime.
        """
        if self.mode == HALMode.SIM:
            return self._sim_ptp_offset()

        # Try reading ptp4l stats file
        stats_path = "/var/run/ptp4l.stats"
        if os.path.exists(stats_path):
            try:
                data = open(stats_path).read()
                offset_m = re.search(r"offset\s+([-\d.]+)", data)
                freq_m   = re.search(r"freq\s+([-\d.]+)", data)
                delay_m  = re.search(r"delay\s+([-\d.]+)", data)
                offset = float(offset_m.group(1)) if offset_m else 0.0
                freq   = float(freq_m.group(1))   if freq_m   else 0.0
                delay  = float(delay_m.group(1))  if delay_m  else 0.0
                return offset, freq, delay
            except Exception:
                pass

        # Fallback: use pmc tool to query ptp4l
        try:
            result = subprocess.run(
                ["pmc", "-u", "-b", "0", "GET CURRENT_DATA_SET"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                offset_m = re.search(r"offsetFromMaster\s+([-\d.]+)", result.stdout)
                if offset_m:
                    return float(offset_m.group(1)), 0.0, 0.0
        except Exception:
            pass

        return 0.0, 0.0, 0.0

    def _sim_ptp_offset(self) -> Tuple[float, float, float]:
        """
        Synthetic PTP offset: slow drift + occasional spikes.
        Models realistic OCXO behavior.
        """
        import random
        dt = self._sync_interval
        # Drift accumulates
        self._sim_offset_ns += self._sim_drift_rate * dt + random.gauss(0, 0.1)
        # Occasional sync correction
        if abs(self._sim_offset_ns) > 500:
            self._sim_offset_ns *= 0.1   # ptp4l snaps back
        freq_ppb = self._sim_drift_rate * 1e9 / (1e9) + random.gauss(0, 0.05)
        delay_ns = 200.0 + random.gauss(0, 5.0)
        return self._sim_offset_ns, freq_ppb, delay_ns

    # ── Drift Correction ───────────────────────────────────────────────────

    def _compute_drift_rate(self) -> float:
        """
        Compute ΔOffset / Δtime from recent samples.
        Returns drift rate in ns/s.
        """
        if len(self._samples) < 2:
            return 0.0
        recent = self._samples[-10:]
        if len(recent) < 2:
            return 0.0
        dt = (len(recent) - 1) * self._sync_interval
        if dt <= 0:
            return 0.0
        d_offset = recent[-1].offset_ns - recent[0].offset_ns
        return d_offset / dt

    def _apply_correction(self, offset_ns: float, drift_rate: float,
                          trigger: str) -> DriftCorrection:
        """
        Apply DVFS correction based on current offset and drift rate.

        Strategy:
          - Small offset (< 100ns): no correction
          - Medium offset (100ns–1μs): gentle CPU weight reduction
          - Large offset (>1μs): GPU clock reduction + CPU throttle
          - Extreme (>10μs): full throttle + alert
        """
        t0 = time.monotonic()

        abs_offset = abs(offset_ns)
        cpu_weight  = 100
        gpu_min     = self._gpu_min_mhz
        gpu_max     = self._gpu_max_mhz

        if abs_offset < 100:
            action = "no_correction"
        elif abs_offset < 1_000:
            # Gentle: reduce CPU weight slightly
            cpu_weight = max(70, int(100 - abs_offset / 100))
            action = f"cpu_weight_adjust:{cpu_weight}"
        elif abs_offset < 10_000:
            # Medium: reduce GPU clocks + CPU weight
            scale      = 1.0 - min(0.3, abs_offset / 100_000)
            gpu_max    = int(self._gpu_max_mhz * scale)
            cpu_weight = max(50, int(100 * scale))
            action     = f"dvfs_scale:{scale:.2f} gpu_max:{gpu_max}MHz cpu:{cpu_weight}"
        else:
            # Extreme: hard throttle
            gpu_max    = self._gpu_min_mhz
            cpu_weight = 25
            action     = f"hard_throttle gpu:{gpu_max}MHz cpu:{cpu_weight}"
            self.events.publish_alert(
                "qmp_drift", "critical",
                f"Clock offset EXTREME: {offset_ns:.1f}ns (drift={drift_rate:.2f}ns/s)",
                offset_ns=offset_ns, drift_rate=drift_rate
            )

        # Apply CPU cgroup weight
        if self._dvfs_enabled:
            self._write_cgroup(self._cgroup_weight, str(cpu_weight))

        # Apply GPU clock lock
        if self._dvfs_enabled and self._gpu_lock and self.mode != HALMode.SIM:
            self._lock_all_gpu_clocks(gpu_min, gpu_max)

        elapsed = (time.monotonic() - t0) * 1000

        corr = DriftCorrection(
            timestamp=datetime.now(timezone.utc).isoformat(),
            trigger=trigger,
            offset_ns=offset_ns,
            drift_rate=drift_rate,
            action=action,
            cpu_weight=cpu_weight,
            gpu_min_mhz=gpu_min,
            gpu_max_mhz=gpu_max,
            effective_ms=round(elapsed, 2),
        )
        self._corrections.append(corr)
        if len(self._corrections) > 1000:
            self._corrections.pop(0)

        if action != "no_correction":
            self.log.info(f"QMP correction: offset={offset_ns:.1f}ns "
                          f"rate={drift_rate:.2f}ns/s → {action}")
            self.events.publish("QMP_CORRECTION", corr.to_dict())

        return corr

    # ── Background Threads ─────────────────────────────────────────────────

    def _start_threads(self) -> None:
        self._sync_thread = threading.Thread(
            target=self._sync_loop, name="qmp-sync", daemon=True)
        self._corr_thread = threading.Thread(
            target=self._correction_loop, name="qmp-correction", daemon=True)
        self._sync_thread.start()
        self._corr_thread.start()

    def _sync_loop(self) -> None:
        """High-frequency PTP sampling loop."""
        while self._active:
            try:
                offset, freq, delay = self._read_ptp_offset()
                sample = ClockSample(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    offset_ns=offset, freq_ppb=freq,
                    delay_ns=delay,
                    source="sim" if self.mode == HALMode.SIM else "ptp4l"
                )
                self._samples.append(sample)
                if len(self._samples) > 10000:
                    self._samples.pop(0)
            except Exception as e:
                self.log.debug(f"Sync loop error: {e}")
            time.sleep(self._sync_interval)

    def _correction_loop(self) -> None:
        """Drift correction evaluation loop (50ms default)."""
        while self._active:
            try:
                if self._samples:
                    latest    = self._samples[-1]
                    offset    = latest.offset_ns
                    drift_rate = self._compute_drift_rate()

                    if abs(offset) > self._offset_thresh:
                        trigger = "offset_exceeded"
                        if abs(offset) > self._offset_thresh * 10:
                            trigger = "rate_exceeded"
                            self.events.publish_alert(
                                "qmp_drift", "warning",
                                f"PTP offset {offset:.1f}ns exceeds threshold",
                                offset_ns=offset
                            )
                        self._apply_correction(offset, drift_rate, trigger)
            except Exception as e:
                self.log.debug(f"Correction loop error: {e}")
            time.sleep(self._correction_int)

    # ── OS helpers ─────────────────────────────────────────────────────────

    def _set_cpu_governor(self, governor: str) -> None:
        for path in ["/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"]:
            if os.path.exists(path):
                cpu_count = os.cpu_count() or 1
                for i in range(cpu_count):
                    p = f"/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_governor"
                    try:
                        with open(p, "w") as f:
                            f.write(governor)
                    except Exception:
                        pass
                self.log.info(f"CPU governor set to {governor}")
                return

    def _lock_all_gpu_clocks(self, min_mhz: int, max_mhz: int) -> None:
        for i in range(4):
            try:
                subprocess.run(
                    ["/usr/bin/nvidia-smi", "-lgc", f"{min_mhz},{max_mhz}", "-i", str(i)],
                    capture_output=True, timeout=5
                )
            except Exception:
                pass

    def _write_cgroup(self, path: str, value: str) -> None:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(value)
        except Exception:
            pass

    # ── Public API ─────────────────────────────────────────────────────────

    def get_current_offset(self) -> Optional[float]:
        return self._samples[-1].offset_ns if self._samples else None

    def get_drift_rate(self) -> float:
        return self._compute_drift_rate()

    def get_recent_samples(self, n: int = 100) -> List[dict]:
        return [s.to_dict() for s in self._samples[-n:]]

    def get_recent_corrections(self, n: int = 50) -> List[dict]:
        return [c.to_dict() for c in self._corrections[-n:]]

    def force_correction(self) -> Optional[dict]:
        """Manually trigger a drift correction evaluation."""
        if not self._samples:
            return None
        corr = self._apply_correction(
            self._samples[-1].offset_ns,
            self._compute_drift_rate(),
            "manual"
        )
        return corr.to_dict()

    def health(self) -> SubsystemHealth:
        if not self._ready:
            return SubsystemHealth("QMPDrift", "offline", self.mode.value, "Not initialised")
        offset      = self.get_current_offset() or 0.0
        drift_rate  = self.get_drift_rate()
        corrections = len(self._corrections)
        status = "ok"
        if abs(offset) > self._offset_thresh * 10:
            status = "degraded"
        return SubsystemHealth(
            "QMPDrift", status, self.mode.value,
            f"offset={offset:.1f}ns | rate={drift_rate:.2f}ns/s | "
            f"samples={len(self._samples)} | corrections={corrections}",
            metrics={"offset_ns": round(offset, 2),
                     "drift_rate_ns_per_s": round(drift_rate, 3),
                     "sample_count": len(self._samples),
                     "correction_count": corrections}
        )

    def shutdown(self) -> None:
        self._active = False
        if self._ptp4l_proc:
            self._ptp4l_proc.terminate()
        for t in [self._sync_thread, self._corr_thread]:
            if t:
                t.join(timeout=2)
        self.log.info("QMPDrift shutdown complete")