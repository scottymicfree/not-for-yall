"""
SOVEREIGN v2.1 — Memory Spine Controller
==========================================
Manages the NVMe RAID 10 storage array and Lucy's persistent
memory layers (ChromaDB, SQLite audit ledger, FAISS indexes).

Hardware:
  4× Kioxia CM7 PCIe Gen 5 NVMe SSDs (4TB each) in RAID 10
  → /dev/md0 mount point: /lucy/data
  Sequential read: ~28 GB/s | Sequential write: ~14 GB/s
  Random 4K read: ~3.2M IOPS | Latency: ~50μs

Lucy memory layers mounted here:
  /lucy/data/chroma_global   → ChromaDB (Prime + Cluster long-term memory)
  /lucy/data/chroma_shards/  → Per-cluster ChromaDB shards
  /lucy/data/sqlite/         → Audit ledger + episodic journal
  /lucy/data/faiss_local/    → Worker FAISS indexes
  /lucy/data/checkpoints/    → Agent state checkpoints
"""

from __future__ import annotations

import os
import re
import time
import json
import shutil
import logging
import subprocess
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict

from .sovereign_hal import HALSubsystem, HALMode, SubsystemHealth, HALEventBus

log = logging.getLogger("lucy.hal.memory_spine")


@dataclass
class NVMeDevice:
    device_id:    int
    model:        str
    path:         str
    capacity_tb:  float
    pcie_gen:     int
    health:       str = "ok"   # "ok" | "degraded" | "failed"
    temp_c:       float = 0.0
    bytes_read:   int   = 0
    bytes_written: int  = 0
    wear_level:   int   = 0    # 0-100% life remaining

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RAIDStatus:
    device:       str
    level:        int
    state:        str    # "clean" | "degraded" | "recovering" | "failed"
    active_devs:  int
    total_devs:   int
    size_gb:      float
    mount_point:  str
    rebuild_pct:  float = 0.0  # 0-100 if rebuilding

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StorageMetrics:
    timestamp:         str
    raid_state:        str
    total_capacity_gb: float
    used_gb:           float
    free_gb:           float
    use_pct:           float
    read_mbps:         float
    write_mbps:        float
    iops:              float
    latency_us:        float
    chroma_size_mb:    float
    sqlite_size_mb:    float
    faiss_size_mb:     float

    def to_dict(self) -> dict:
        return asdict(self)


class MemorySpineController(HALSubsystem):
    """
    Manages NVMe RAID array and Lucy's memory layer directories.

    On init:
      1. Verify/assemble RAID array
      2. Mount /lucy/data
      3. Create Lucy directory structure
      4. Verify each memory layer is accessible
      5. Start background storage monitor
    """

    LUCY_DIRS = [
        "chroma_global",
        "chroma_shards",
        "sqlite",
        "faiss_local",
        "checkpoints",
        "logs",
        "exports",
    ]

    def __init__(self, config: dict, mode: HALMode, events: HALEventBus):
        super().__init__("MemorySpine", config, mode)
        self.events = events

        self._nvme_devs = config.get("nvme_devices", [])
        raid_cfg        = config.get("raid", {})
        self._raid_dev  = raid_cfg.get("device",      "/dev/md0")
        self._mount_pt  = raid_cfg.get("mount_point", "/lucy/data")

        # In SIM mode, use local sandbox paths
        if mode == HALMode.SIM:
            self._mount_pt = str(Path("data/lucy_storage").resolve())

        self._chroma_path  = config.get("chroma_db_path",  f"{self._mount_pt}/chroma_global")
        self._sqlite_path  = config.get("sqlite_path",     f"{self._mount_pt}/sqlite")
        self._faiss_path   = config.get("faiss_path",      f"{self._mount_pt}/faiss_local")

        self._devices: List[NVMeDevice] = []
        self._raid_status: Optional[RAIDStatus] = None
        self._metrics: Optional[StorageMetrics] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._active = False
        self._prev_io = {"read": 0, "write": 0, "time": time.monotonic()}

    # ── Init ───────────────────────────────────────────────────────────────

    def init(self) -> bool:
        if self.mode == HALMode.SIM:
            return self._init_sim()
        else:
            return self._init_real()

    def _init_sim(self) -> bool:
        """SIM mode: use local filesystem paths."""
        self.log.info(f"[SIM] MemorySpine using local path: {self._mount_pt}")

        # Create directory structure
        for d in self.LUCY_DIRS:
            path = os.path.join(self._mount_pt, d)
            os.makedirs(path, exist_ok=True)

        # Simulate NVMe devices
        for i, dev_cfg in enumerate(self._nvme_devs[:4]):
            self._devices.append(NVMeDevice(
                device_id=i,
                model=dev_cfg.get("model", "Kioxia CM7 [SIM]"),
                path=dev_cfg.get("path", f"/dev/nvme{i}n1"),
                capacity_tb=dev_cfg.get("capacity_tb", 4.0),
                pcie_gen=dev_cfg.get("pcie_gen", 5),
            ))

        # Simulate RAID status
        self._raid_status = RAIDStatus(
            device=self._raid_dev,
            level=10, state="clean",
            active_devs=4, total_devs=4,
            size_gb=8192.0, mount_point=self._mount_pt
        )

        self._start_monitor()
        self._ready = True
        self.log.info(f"[SIM] MemorySpine ready: {self._mount_pt}")
        return True

    def _init_real(self) -> bool:
        """Real hardware: assemble RAID, mount, verify."""
        try:
            self._enumerate_nvme()
            self._assemble_raid()
            self._mount_filesystem()
            self._create_lucy_dirs()
            self._verify_memory_layers()
            self._start_monitor()
            self._ready = True
            return True
        except Exception as e:
            self.log.error(f"MemorySpine init failed: {e}")
            if self.mode == HALMode.PROTO:
                self.log.warning("Falling back to SIM mode for storage")
                self.mode = HALMode.SIM
                return self._init_sim()
            return False

    def _enumerate_nvme(self) -> None:
        """Enumerate NVMe devices via nvme-cli."""
        for dev_cfg in self._nvme_devs:
            path = dev_cfg.get("path", "/dev/nvme0n1")
            if not os.path.exists(path):
                self.log.warning(f"NVMe device not found: {path}")
                continue
            try:
                result = subprocess.run(
                    ["nvme", "id-ctrl", path, "-o", "json"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    info = json.loads(result.stdout)
                    dev = NVMeDevice(
                        device_id=dev_cfg.get("id", 0),
                        model=info.get("mn", dev_cfg.get("model", "Unknown")).strip(),
                        path=path,
                        capacity_tb=dev_cfg.get("capacity_tb", 4.0),
                        pcie_gen=dev_cfg.get("pcie_gen", 5),
                        wear_level=info.get("pct_used", 0),
                    )
                    self._devices.append(dev)
                    self.log.info(f"NVMe: {dev.model} @ {path}")
            except Exception as e:
                self.log.warning(f"NVMe enumerate error {path}: {e}")

    def _assemble_raid(self) -> None:
        """Assemble mdadm RAID 10 array."""
        # Check if already assembled
        result = subprocess.run(
            ["mdadm", "--detail", self._raid_dev],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            self.log.info(f"RAID {self._raid_dev} already active")
            self._parse_mdadm_status(result.stdout)
            return

        # Assemble from component devices
        dev_paths = [d.path for d in self._devices]
        if len(dev_paths) < 4:
            raise RuntimeError(f"Need 4 NVMe devices for RAID 10, found {len(dev_paths)}")

        result = subprocess.run(
            ["mdadm", "--assemble", self._raid_dev] + dev_paths,
            capture_output=True, text=True, timeout=30
        )
        if result.returncode not in (0, 2):  # 2 = already assembled
            raise RuntimeError(f"RAID assemble failed: {result.stderr}")
        self.log.info(f"RAID {self._raid_dev} assembled")

    def _mount_filesystem(self) -> None:
        """Mount the RAID array at /lucy/data."""
        os.makedirs(self._mount_pt, exist_ok=True)

        # Check if already mounted
        result = subprocess.run(["mountpoint", "-q", self._mount_pt],
                                 capture_output=True)
        if result.returncode == 0:
            self.log.info(f"{self._mount_pt} already mounted")
            return

        result = subprocess.run(
            ["mount", "-o", "noatime,data=writeback", self._raid_dev, self._mount_pt],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            raise RuntimeError(f"Mount failed: {result.stderr}")
        self.log.info(f"RAID mounted at {self._mount_pt}")

    def _create_lucy_dirs(self) -> None:
        """Create Lucy directory structure on mounted filesystem."""
        for d in self.LUCY_DIRS:
            path = os.path.join(self._mount_pt, d)
            os.makedirs(path, exist_ok=True)
            os.chmod(path, 0o750)
        self.log.info(f"Lucy directory structure created at {self._mount_pt}")

    def _verify_memory_layers(self) -> None:
        """Verify each memory layer path is writable."""
        for path in [self._chroma_path, self._sqlite_path, self._faiss_path]:
            test_file = os.path.join(path, ".lucy_hal_verify")
            try:
                with open(test_file, "w") as f:
                    f.write("ok")
                os.remove(test_file)
                self.log.debug(f"Memory layer verified: {path}")
            except Exception as e:
                raise RuntimeError(f"Memory layer not writable: {path}: {e}")

    def _parse_mdadm_status(self, output: str) -> None:
        """Parse mdadm --detail output into RAIDStatus."""
        state_m = re.search(r"State\s*:\s*(.+)", output)
        devs_m  = re.search(r"Active Devices\s*:\s*(\d+)", output)
        total_m = re.search(r"Total Devices\s*:\s*(\d+)", output)
        size_m  = re.search(r"Array Size\s*:\s*([\d.]+)", output)

        self._raid_status = RAIDStatus(
            device=self._raid_dev,
            level=10,
            state=(state_m.group(1).strip() if state_m else "unknown"),
            active_devs=int(devs_m.group(1)) if devs_m else 0,
            total_devs=int(total_m.group(1))  if total_m else 0,
            size_gb=float(size_m.group(1)) / 1024 if size_m else 0,
            mount_point=self._mount_pt,
        )

    # ── Monitor ────────────────────────────────────────────────────────────

    def _start_monitor(self) -> None:
        self._active = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, name="memory-spine-monitor", daemon=True)
        self._monitor_thread.start()

    def _monitor_loop(self) -> None:
        """Background: update storage metrics every 10s."""
        while self._active:
            try:
                self._update_metrics()
            except Exception as e:
                self.log.debug(f"Monitor error: {e}")
            time.sleep(10)

    def _update_metrics(self) -> None:
        """Collect current storage metrics."""
        if self.mode == HALMode.SIM:
            import random
            used_pct = random.uniform(15, 35)
            total = 8192.0
            used  = total * used_pct / 100
            self._metrics = StorageMetrics(
                timestamp=datetime.now(timezone.utc).isoformat(),
                raid_state="clean",
                total_capacity_gb=total,
                used_gb=round(used, 1),
                free_gb=round(total - used, 1),
                use_pct=round(used_pct, 1),
                read_mbps=round(random.uniform(8000, 14000), 0),
                write_mbps=round(random.uniform(4000, 7000), 0),
                iops=round(random.uniform(800_000, 1_500_000), 0),
                latency_us=round(random.uniform(40, 80), 1),
                chroma_size_mb=round(random.uniform(500, 2000), 0),
                sqlite_size_mb=round(random.uniform(10, 500), 0),
                faiss_size_mb=round(random.uniform(100, 800), 0),
            )
            return

        # Real: use df + /proc/diskstats
        try:
            stat = shutil.disk_usage(self._mount_pt)
            total_gb = stat.total / (1024**3)
            used_gb  = stat.used  / (1024**3)
            free_gb  = stat.free  / (1024**3)
            use_pct  = (stat.used / stat.total) * 100 if stat.total > 0 else 0

            # Directory sizes
            def dir_mb(p: str) -> float:
                try:
                    result = subprocess.run(["du", "-sm", p], capture_output=True,
                                             text=True, timeout=5)
                    if result.returncode == 0:
                        return float(result.stdout.split()[0])
                except Exception:
                    pass
                return 0.0

            self._metrics = StorageMetrics(
                timestamp=datetime.now(timezone.utc).isoformat(),
                raid_state=self._raid_status.state if self._raid_status else "unknown",
                total_capacity_gb=round(total_gb, 1),
                used_gb=round(used_gb, 1),
                free_gb=round(free_gb, 1),
                use_pct=round(use_pct, 1),
                read_mbps=0, write_mbps=0, iops=0, latency_us=0,  # from /proc/diskstats
                chroma_size_mb=dir_mb(self._chroma_path),
                sqlite_size_mb=dir_mb(self._sqlite_path),
                faiss_size_mb=dir_mb(self._faiss_path),
            )
        except Exception as e:
            self.log.debug(f"Metrics update error: {e}")

    # ── Public API ─────────────────────────────────────────────────────────

    @property
    def chroma_path(self) -> str:
        return self._chroma_path

    @property
    def sqlite_path(self) -> str:
        return self._sqlite_path

    @property
    def faiss_path(self) -> str:
        return self._faiss_path

    @property
    def mount_point(self) -> str:
        return self._mount_pt

    def get_raid_status(self) -> Optional[dict]:
        return self._raid_status.to_dict() if self._raid_status else None

    def get_metrics(self) -> Optional[dict]:
        return self._metrics.to_dict() if self._metrics else None

    def get_nvme_devices(self) -> List[dict]:
        return [d.to_dict() for d in self._devices]

    def checkpoint_agent(self, agent_id: str, state: dict) -> str:
        """
        Persist an agent checkpoint to the Memory Spine.
        Returns the checkpoint file path.
        """
        import json
        checkpoint_dir = os.path.join(self._mount_pt, "checkpoints", agent_id)
        os.makedirs(checkpoint_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        path = os.path.join(checkpoint_dir, f"checkpoint_{ts}.json")
        with open(path, "w") as f:
            json.dump({
                "agent_id": agent_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "state": state,
            }, f, indent=2)
        return path

    def health(self) -> SubsystemHealth:
        if not self._ready:
            return SubsystemHealth("MemorySpine", "offline", self.mode.value, "Not initialised")
        m = self._metrics
        raid_state = self._raid_status.state if self._raid_status else "unknown"
        status = "ok" if raid_state in ("clean", "active") else "degraded"
        metrics_dict = {}
        msg = f"RAID={raid_state} | mount={self._mount_pt}"
        if m:
            msg += (f" | used={m.use_pct:.1f}% | "
                    f"read={m.read_mbps:.0f}MB/s write={m.write_mbps:.0f}MB/s")
            metrics_dict = {
                "raid_state": raid_state,
                "use_pct": m.use_pct,
                "free_gb": m.free_gb,
                "read_mbps": m.read_mbps,
                "write_mbps": m.write_mbps,
            }
        return SubsystemHealth("MemorySpine", status, self.mode.value, msg,
                               metrics=metrics_dict)

    def shutdown(self) -> None:
        self._active = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=3)
        if self.mode == HALMode.NATIVE:
            try:
                subprocess.run(["umount", self._mount_pt],
                                capture_output=True, timeout=10)
                self.log.info(f"Unmounted {self._mount_pt}")
            except Exception as e:
                self.log.warning(f"Unmount failed: {e}")
        self.log.info("MemorySpine shutdown complete")