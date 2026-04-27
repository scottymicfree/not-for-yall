# LUCY OS — HARDWARE MOUNT GUIDE
## Sovereign v2.1 Integration Manual

**Version:** 1.0  
**Date:** 2026-04-25  
**Status:** ✅ SIM-verified (237/237 tests pass)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture Summary](#2-architecture-summary)
3. [Pre-Mount Checklist](#3-pre-mount-checklist)
4. [HAL Modes Explained](#4-hal-modes-explained)
5. [Mounting Lucy — Step by Step](#5-mounting-lucy--step-by-step)
6. [Software Stack Binding](#6-software-stack-binding)
7. [Governance & Safety Systems](#7-governance--safety-systems)
8. [Subsystem Reference](#8-subsystem-reference)
9. [Transitioning SIM → PROTO → NATIVE](#9-transitioning-sim--proto--native)
10. [Troubleshooting](#10-troubleshooting)
11. [Test Suite](#11-test-suite)
12. [File Map](#12-file-map)

---

## 1. Overview

Lucy OS mounts to the Sovereign v2.1 board through a **Hardware Abstraction Layer (HAL)** that provides a clean Python interface to every physical subsystem. The mount sequence boots Lucy in four phases:

```
Phase 1 → Boot Sequence     (POST, Coreboot, LinuxBoot, HAL_Init, Lucy_Ready)
Phase 2 → HAL Mount         (Power → Memory → SenseMesh → QMP → NeuroMesh → EMMA)
Phase 3 → Software Binding  (AuditLedger, ToolExecutor, ValidationPipeline, FastAPI)
Phase 4 → Governance Hooks  (Sentinel → FPGA halt, Power budget → DVFS, Thermal → GPU reset)
```

After all four phases complete, `lucy_mount()` returns a `LucyBoundSystem` object that is your single handle to the entire machine.

---

## 2. Architecture Summary

```
┌─────────────────────────────────────────────────────────┐
│                    Lucy Software Stack                  │
│  AuditLedger │ ToolExecutor │ ValidationPipeline │ API  │
├─────────────────────────────────────────────────────────┤
│                  LucyBoundSystem (lucy_mount.py)        │
├──────────┬──────────┬──────────┬──────────┬────────────┤
│NeuroMesh │  EMMA    │SenseMesh │  QMP     │MemSpine    │
│ Driver   │  FPGA    │ Monitor  │  Drift   │Controller  │
├──────────┴──────────┴──────────┴──────────┴────────────┤
│              HAL Event Bus  │  Device Registry          │
├─────────────────────────────────────────────────────────┤
│                  Sovereign v2.1 Hardware                │
│  4× L40S GPU  │ Versal FPGA │ INA3221 │ SiT5356 OCXO  │
│  4× CM7 NVMe  │ Inf. XDPE   │ TMP112  │ OpenBMC BMC   │
└─────────────────────────────────────────────────────────┘
```

### Node Topology (137 total)

| Role   | Count | GPU    | Type        | Memory  |
|--------|-------|--------|-------------|---------|
| PRIME  | 1     | GPU 0  | MIG 4g.48gb | 48 GB   |
| C1–C2  | 2     | GPU 0  | MIG 2g.24gb | 24 GB each |
| C3–C4  | 2     | GPU 1  | MIG 2g.24gb | 24 GB each |
| C5–C6  | 2     | GPU 2  | MIG 2g.24gb | 24 GB each |
| C7–C8  | 2     | GPU 3  | MIG 2g.24gb | 24 GB each |
| W001–W032 | 32 | GPU 0  | MPS slice   | shared  |
| W033–W064 | 32 | GPU 1  | MPS slice   | shared  |
| W065–W096 | 32 | GPU 2  | MPS slice   | shared  |
| W097–W128 | 32 | GPU 3  | MPS slice   | shared  |

---

## 3. Pre-Mount Checklist

### 3.1 Hardware Requirements (NATIVE mode)

- [ ] Sovereign v2.1 board powered on, VRM rails stable
- [ ] 4× NVIDIA L40S GPUs seated in PCIe slots (bus IDs: `0000:01:00`, `0000:41:00`, `0000:81:00`, `0000:c1:00`)
- [ ] NVIDIA MIG mode enabled on all 4 GPUs: `sudo nvidia-smi mig -e 1`
- [ ] MIG instances created per profile (see `hal_config.yaml → neuromesh.gpus`)
- [ ] MPS daemon running: `sudo nvidia-cuda-mps-control -d`
- [ ] AMD Xilinx Versal FPGA loaded with E.M.M.A. bitstream at `/dev/emma_fpga0`
- [ ] 4× Kioxia CM7 NVMe drives visible (`/dev/nvme0`–`/dev/nvme3`)
- [ ] RAID 10 array assembled: `sudo mdadm --assemble /dev/md0 /dev/nvme0 /dev/nvme1 /dev/nvme2 /dev/nvme3`
- [ ] `/lucy/data` mounted from `/dev/md0`
- [ ] OpenBMC sideband interface active (I3C bus `/dev/i3c-0`, `/dev/i3c-1`)
- [ ] ptp4l running: `sudo systemctl start ptp4l`
- [ ] SiTime SiT5356 OCXO locked (check `phc2sys` offset < 100 ns)
- [ ] Infineon XDPE VRM accessible at I2C address `0x70`
- [ ] IOMMU enabled in kernel: verify `dmesg | grep IOMMU` shows `enabled`
- [ ] eBPF subsystem loaded: `ls /sys/fs/bpf/`

### 3.2 Software Requirements

```bash
pip install fastapi uvicorn httpx pyyaml aiofiles chromadb faiss-cpu
```

- Python ≥ 3.11
- `lucy-os/` directory present with all modules
- `hal_config.yaml` present in `lucy-os/hal/`

### 3.3 Verify SIM Mode Works First

Always verify SIM mode before touching real hardware:

```bash
cd lucy-os
python tests/test_hal.py          # Must show 237/237 PASS
python tests/test_all.py          # Must show 132/132 PASS
python hal/lucy_mount.py --mode sim --start   # Manual smoke test
```

---

## 4. HAL Modes Explained

| Mode     | Description | When to Use |
|----------|-------------|-------------|
| `sim`    | Full software simulation, no hardware needed | Development, CI/CD, testing |
| `proto`  | COTS hardware (any Linux box), real FS/network | Pre-production integration |
| `native` | Full Sovereign v2.1 with all hardware active | Production deployment |

The mode is selected at mount time and flows through every subsystem automatically.

---

## 5. Mounting Lucy — Step by Step

### 5.1 Python API (recommended)

```python
from hal.lucy_mount import lucy_mount

# SIM mode (no hardware)
lucy = lucy_mount(mode="sim")

# PROTO mode (real Linux, COTS hardware)
lucy = lucy_mount(mode="proto", config_path="/path/to/hal_config.yaml")

# NATIVE mode (Sovereign v2.1)
lucy = lucy_mount(mode="native", config_path="/etc/lucy/hal_config.yaml")

# Check mount status
print(lucy.status())
# {'operational': True, 'mode': 'sim', 'node_count': 137, 'subsystems': 6, ...}

# Access subsystems
telem = lucy.neuromesh.get_gpu_telemetry(0)
sensors = lucy.sensemesh.get_snapshot()
power = lucy.power_manager.get_snapshot()

# Governance commands
lucy.halt_agent("W042", reason="anomaly_detected")
lucy.throttle_agent("W001", anomaly_score=0.8)
lucy.isolate_agent("W010", reason="suspicious_behavior")
lucy.reset_gpu(gpu_id=2, reason="thermal_runaway")
lucy.halt_all(reason="emergency_stop")

# Graceful shutdown
lucy.shutdown()
```

### 5.2 CLI Entry Point

```bash
# SIM mode with auto-start
python hal/lucy_mount.py --mode sim --start

# NATIVE mode
python hal/lucy_mount.py --mode native --config /etc/lucy/hal_config.yaml --start
```

### 5.3 Mount Output (what success looks like)

```
╔══════════════════════════════════════════════════════════════╗
║          LUCY OS — HARDWARE MOUNT SEQUENCE                  ║
╚══════════════════════════════════════════════════════════════╝
  Mode: NATIVE | Config: /etc/lucy/hal_config.yaml
--- Phase 1: Boot Sequence ───────────────────────────────────
[BOOT] Stage POST:       ✓ PASS — ECC RAM=512GB OK | VRM=stable
[BOOT] Stage Coreboot:  ✓ PASS — Coreboot+LinuxBoot payload nominal
[BOOT] Stage LinuxBoot: ✓ PASS — Kernel 6.x | IOMMU=on | eBPF=loaded
[BOOT] Stage HAL_Init:  ✓ PASS — All HAL prerequisites satisfied
[BOOT] Stage Lucy_Ready:✓ PASS — Lucy prerequisites satisfied
[BOOT] Boot SUCCESS | 5/5 stages | 412ms total
--- Phase 2: HAL Mount ───────────────────────────────────────
  → [power]     ✓ OK — total=1821W/2400W (75.9%)
  → [memory]    ✓ OK — RAID=clean | mount=/lucy/data | used=12.4%
  → [sensemesh] ✓ OK — 15 sensors | max_temp=61°C | alerts=0
  → [qmp_drift] ✓ OK — offset=12ns | rate=0.01ns/s | corrections=0
  → [neuromesh] ✓ OK — 4 GPUs | 137/137 nodes mapped | mode=NATIVE
  → [emma]      ✓ OK — FPGA=open | halt_active=False | events=0
══ Mount Sequence COMPLETE in 1.2s ══
╔══════════════════════════════════════════════════════════════╗
║  LUCY MOUNTED in 1847ms
║  Status:     MOUNTED
║  Mode:       NATIVE
║  Nodes:      137
║  Subsystems: 6/6 OK
║  Operational: True
╚══════════════════════════════════════════════════════════════╝
```

---

## 6. Software Stack Binding

When `bind_software=True` (default), Phase 3 connects Lucy's cognitive modules to HAL storage paths:

| Module | Binding |
|--------|---------|
| `AuditLedger` | SQLite at `<mount>/sqlite/master_ledger.db` |
| `ToolExecutor` | Sandbox at `<mount>/sandbox/` |
| `ValidationPipeline` | Bound (stateless, no path needed) |
| `FastAPI backend` | Created with 137-node mesh seeded |

Access via `LucyBoundSystem`:

```python
lucy.ledger          # AuditLedger instance
lucy.executor        # ToolExecutor instance
lucy.validator       # ValidationPipeline instance
lucy.api_app         # FastAPI application (pass to uvicorn)
```

To serve the API:

```python
import uvicorn
uvicorn.run(lucy.api_app, host="0.0.0.0", port=8000)
```

---

## 7. Governance & Safety Systems

### 7.1 Automatic Governance Callbacks

When Lucy mounts, four hardware safety callbacks are auto-registered:

| Trigger | Action |
|---------|--------|
| `Sentinel.execute_hard_halt(agent)` | → `emma.halt_agent(agent)` (FPGA HALT) |
| `Sentinel.execute_hard_halt("ALL")` | → `emma.halt_all()` (all 137 nodes) |
| `HAL_ALERT power_budget_critical` | → throttle all W001–W128 at score=0.9 |
| `HAL_ALERT thermal_critical` | → `neuromesh.reset_gpu(gpu_id)` |

### 7.2 DVFS Throttle Map

The E.M.M.A. FPGA translates an `anomaly_score` (0.0–1.0) to GPU clock frequencies:

| Score Range | GPU Clock | CPU Weight | Meaning |
|-------------|-----------|------------|---------|
| 0.00–0.30   | 2520 MHz  | 100        | Full speed |
| 0.30–0.60   | 1890 MHz  | 60         | Mild concern |
| 0.60–0.80   | 1260 MHz  | 30         | Elevated concern |
| 0.80–0.95   | 630 MHz   | 9          | High concern |
| 0.95–1.00   | 735 MHz   | 1          | Critical (safe floor) |

### 7.3 FPGA Command Frame Protocol

All EMMA commands use a **32-byte fixed frame**:

```
Offset  Size  Field
  0       1   magic (0xE5)
  1       1   cmd (FPGACmd enum)
  2       2   payload_len (LE uint16)
  4      16   target (UTF-8 agent_id, zero-padded)
 20       4   param (LE uint32)
 24       4   seq (LE uint32)
 28       4   CRC32 of bytes [0:28]
```

### 7.4 Manual Governance API

```python
# Halt a single agent (FPGA-mediated PCIe FLR)
lucy.halt_agent("W042", reason="policy_violation")

# Halt all 137 nodes (checkpoint halt)
lucy.halt_all(reason="emergency")

# Throttle by anomaly score
lucy.throttle_agent("W001", anomaly_score=0.75)

# IOMMU isolation (PCIe ACS policy)
lucy.isolate_agent("W010", reason="suspicious_dma")

# GPU reset (PERST# via FPGA GPIO)
lucy.reset_gpu(gpu_id=2, reason="unrecoverable_fault")
```

### 7.5 HAL Event Bus

Subscribe to hardware alerts from any module:

```python
# Subscribe to all alerts
lucy.hal.event_bus.subscribe("*", my_callback)

# Subscribe to thermal only
lucy.hal.event_bus.subscribe("HAL_ALERT", my_callback)

# Callback signature
def my_callback(event: dict):
    # event keys: topic, payload, timestamp
    print(event["payload"])
```

---

## 8. Subsystem Reference

### 8.1 NeuroMesh Driver (`neuromesh_driver.py`)

Maps 137 Lucy logical nodes to physical GPU partitions.

```python
nm = lucy.neuromesh

# GPU telemetry (real: nvidia-smi, SIM: synthetic)
telem = nm.get_gpu_telemetry(gpu_id=0)
# {'temp_c': 62.0, 'power_w': 245.0, 'util_pct': 71.0, 'mem_used_gb': 38.5}

# All nodes mapped to hardware
nodes = nm.get_all_node_mappings()

# Lock GPU clock (NATIVE: nvidia-smi -lgc)
nm.set_node_clock_lock("W001", freq_mhz=2520)

# Hard reset (NATIVE: writes to /sys/bus/pci/devices/.../reset)
nm.reset_gpu(gpu_id=1, reason="fault")
```

### 8.2 E.M.M.A. FPGA Bridge (`emma_fpga.py`)

Governance command interface to the Versal AI Edge FPGA.

```python
emma = lucy.emma

emma.halt_agent("W042", reason="...")
emma.halt_all(reason="...")
emma.release_halt("W042")
emma.reset_gpu(gpu_id=1, reason="...")
emma.isolate_node("W010", reason="...")
emma.restore_node("W010", reason="...")
emma.throttle_dvfs("W001", anomaly_score=0.5)
emma.restore_dvfs("W001")
emma.set_ebpf_weight("W001", weight=50)

# BMC queries (NATIVE: Redfish/IPMI; SIM: synthetic)
state = emma.bmc_get_power_state()
sensors = emma.bmc_get_sensor_summary()
emma.bmc_emergency_off()   # ⚠️ cuts power immediately

# Event log
events = emma.get_events()
```

### 8.3 SenseMesh Monitor (`sensemesh.py`)

Polls TI INA3221 (power) + TI TMP112 (thermal) sensors over I3C/I2C.

```python
sm = lucy.sensemesh

# Current readings
readings = sm.get_readings()
# {'gpu0_temp': SensorReading(value=62.3, unit='C'), ...}

# Point-in-time snapshot
snap = sm.get_snapshot()
# {'temperatures': {...}, 'powers': {...}, 'timestamp': ...}

# Historical ring buffer (600 entries at 100ms = 60s)
history = sm.get_history(n=60)
```

### 8.4 QMP Drift Controller (`qmp_drift.py`)

Manages SiTime SiT5356 OCXO synchronization via ptp4l + DVFS response.

```python
qmp = lucy.qmp

offset = qmp.get_current_offset_ns()   # float, nanoseconds
rate   = qmp.get_drift_rate()          # ns/s

# Force correction (returns action taken)
result = qmp.force_correction()
# {'action': 'dvfs_scale', 'offset_ns': 234.1, 'cpu_weight': 60}

# History
samples = qmp.get_samples(n=100)
```

### 8.5 Memory Spine Controller (`memory_spine.py`)

Manages 4× CM7 NVMe RAID 10 array mounted at `/lucy/data`.

```python
ms = lucy.memory_spine

# Storage paths
ms.chroma_path   # /lucy/data/chroma_global
ms.sqlite_path   # /lucy/data/sqlite
ms.faiss_path    # /lucy/data/faiss_local
ms.mount_point   # /lucy/data  (or SIM local path)

# RAID status
status = ms.get_raid_status()
# {'level': 10, 'state': 'clean', 'active_devices': 4}

# Disk metrics
metrics = ms.get_disk_metrics()
# {'total_capacity': '14.4 TB', 'use_pct': 12.4, 'read_mbps': 13716}

# Agent checkpointing
ms.checkpoint_agent("PRIME", {"memory": [...], "state": {...}})
```

### 8.6 Power Manager (`power_manager.py`)

Monitors Infineon XDPE132G5C VRM via PMBus. 2400W total budget.

```python
pm = lucy.power_manager

total = pm.get_total_power()   # watts (float)
zones = pm.get_zone_power()    # {'compute': 1500, 'logic': 180, 'storage_power': 71}

snap  = pm.get_snapshot()
# {'total_w': 1751, 'budget_w': 2400, 'utilization': 72.9, 'zones': {...}}

history = pm.get_history(n=60)
```

---

## 9. Transitioning SIM → PROTO → NATIVE

### Phase A — SIM (no hardware, any Linux)

```bash
python tests/test_hal.py    # 237/237 must pass
```

All subsystems run with synthetic data. No real devices needed.

### Phase B — PROTO (real Linux, partial hardware)

Set `mode="proto"` in your config. The HAL uses the real filesystem and real network but falls back to synthetic values for hardware-specific calls (nvidia-smi, i3ctransfer, etc.) that aren't available on COTS hardware.

```yaml
# hal_config.yaml
board:
  mode: proto
memory_spine:
  mount_point: /data/lucy_storage   # local path, not RAID
```

### Phase C — NATIVE (Sovereign v2.1)

1. Build and flash E.M.M.A. FPGA bitstream to Versal AI Edge
2. Configure MIG instances per `hal_config.yaml → neuromesh.gpus`
3. Assemble RAID 10 and mount at `/lucy/data`
4. Set `mode: native` in `hal_config.yaml`
5. Run:

```bash
sudo python hal/lucy_mount.py --mode native \
    --config /etc/lucy/hal_config.yaml \
    --start
```

### Key NATIVE-mode changes vs SIM

| Subsystem | SIM | NATIVE |
|-----------|-----|--------|
| NeuroMesh | Synthetic telemetry | Real `nvidia-smi` queries |
| EMMA | In-process simulation | `ioctl` to `/dev/emma_fpga0` |
| SenseMesh | Synthetic sensors | Real I3C `i3ctransfer` reads |
| QMP Drift | Synthetic drift model | Real `ptp4l`/`phc2sys` socket |
| Memory Spine | Local directory | `/dev/md0` RAID 10 at `/lucy/data` |
| Power Mgr | Synthetic load cycle | Real PMBus/SMBus `i2c-tools` reads |
| Boot | All stages simulated | Real `cbmem`, `dmesg`, path checks |

---

## 10. Troubleshooting

### "No module named 'lucy_os'"

All HAL imports must be relative (`.module`) not absolute (`lucy_os.hal.module`). Run from inside `lucy-os/`:

```bash
cd lucy-os && python hal/lucy_mount.py --mode sim
```

### MIG instances not found (NATIVE)

```bash
nvidia-smi mig -lgi   # List GPU instances
# If empty, create them:
sudo nvidia-smi mig -cgi 9,14,14,14,14,14,14,14,14 -C -i 0
```

Profile IDs: `9` = `4g.48gb` (PRIME), `14` = `2g.24gb` (Clusters).

### FPGA device not found

```bash
ls /dev/emma_fpga*
# Should show /dev/emma_fpga0
# If missing, check PCIe enumeration:
lspci | grep -i xilinx
```

### RAID not assembling

```bash
sudo mdadm --examine /dev/nvme0n1   # Check RAID metadata
sudo mdadm --assemble --scan        # Auto-assemble
sudo mdadm --detail /dev/md0        # Verify state=clean
```

### ptp4l offset too large (> 500 ns)

```bash
sudo systemctl restart ptp4l
sudo chronyc tracking   # Check reference
# QMP will auto-correct via DVFS once offset < 10µs
```

### Power budget exceeded at startup

The SIM default puts load at ~73% (1751W/2400W). NATIVE boards may have higher idle draw. Adjust in `hal_config.yaml`:

```yaml
power:
  budget_w: 2400
  throttle_at_w: 2200   # lower this if needed
```

---

## 11. Test Suite

Two test suites cover the full stack:

```bash
cd lucy-os

# HAL layer (hardware abstraction)
python tests/test_hal.py
# Expected: 237/237 PASS across 10 sections

# Software stack (governance, execution, validation, API)
python tests/test_all.py
# Expected: 132/132 PASS across 6 sections
```

### Combined: 369 tests, 0 failures

| Suite | Tests | Sections |
|-------|-------|---------|
| `test_all.py` | 132 | Governance, Sentinel, Execution, Validation, Truth/Logging, FastAPI |
| `test_hal.py` | 237 | Config+Registry, NeuroMesh, EMMA, SenseMesh, QMP, MemSpine, PowerMgr, Boot, Mount, Governance |
| **Total** | **369** | **16** |

---

## 12. File Map

```
lucy-os/
├── hal/
│   ├── __init__.py              # Package exports
│   ├── hal_config.yaml          # Board configuration
│   ├── sovereign_hal.py         # HAL entry point, HALMode, DeviceRegistry, EventBus
│   ├── lucy_mount.py            # Top-level mount: LucyBoundSystem, lucy_mount()
│   ├── boot_sequence.py         # 5-stage boot checker
│   ├── neuromesh_driver.py      # 137-node GPU MIG/MPS mapping
│   ├── emma_fpga.py             # FPGA governance bridge, FPGAFrame protocol
│   ├── sensemesh.py             # I3C/I2C sensor monitor
│   ├── qmp_drift.py             # PTP clock sync + DVFS
│   ├── memory_spine.py          # NVMe RAID storage controller
│   └── power_manager.py         # VRM PDN monitoring
├── governance/
│   ├── audit_ledger.py          # Immutable event log
│   ├── mesh_state.py            # 137-node mesh state
│   └── sentinel.py              # Hard/soft halt, anomaly scoring
├── action/
│   ├── tool_executor.py         # Sandboxed tool execution
│   └── validation_pipeline.py  # Pre/post-execution validation
├── dashboard/
│   └── backend.py               # FastAPI REST + WebSocket
├── tests/
│   ├── test_all.py              # 132 software tests
│   └── test_hal.py              # 237 HAL tests
└── HARDWARE_MOUNT_GUIDE.md      # ← this file
```

---

## Quick Reference Card

```
# Minimal mount (SIM)
from hal.lucy_mount import lucy_mount
lucy = lucy_mount(mode="sim")

# Check everything is up
print(lucy.status())

# Read sensors
snap = lucy.sensemesh.get_snapshot()

# Halt a misbehaving worker
lucy.halt_agent("W042", reason="policy_violation")

# Throttle by anomaly score
lucy.throttle_agent("W001", anomaly_score=0.75)

# Full emergency stop
lucy.halt_all(reason="emergency")

# Clean shutdown
lucy.shutdown()
```

---

*Generated by Lucy OS — Sovereign v2.1 HAL Integration*  
*Test verification: 369/369 assertions pass (SIM mode)*