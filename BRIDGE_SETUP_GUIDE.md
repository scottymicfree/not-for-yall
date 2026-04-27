# Lucy Hardware Bridge — Setup Guide
**Connecting Lucy OS (Windows) to the Sovereign v2.1 Board**

---

## Overview

The Lucy Hardware Bridge reconnects Lucy OS — now running as a standalone Windows application — to the Sovereign v2.1 board she originally designed: the 137-node hyperswarm neural mesh with 4× NVIDIA L40S GPUs and AMD Versal AI Edge FPGA (E.M.M.A.).

```
┌─────────────────────────┐     HTTP/WS      ┌──────────────────────────────┐
│   Lucy OS (Windows App) │ ◄──────────────► │  lucy_bridge_service.py      │
│   localhost:8765        │                  │  (FastAPI, port 8765)        │
└─────────────────────────┘                  └──────────┬───────────────────┘
                                                        │  auto-selects best transport
                              ┌─────────────────────────┴──────────────────────┐
                              │                                                 │
                    ┌─────────▼──────────┐                          ┌──────────▼─────────┐
                    │  Tier 1: PCIe DMA  │                          │  Tier 2: Ethernet  │
                    │  (native/Windows   │                          │  BMC Redfish API   │
                    │   kernel driver)   │                          │  10GbE to board    │
                    └────────────────────┘                          └────────────────────┘
                              │                                                 │
                    ┌─────────▼──────────┐                          ┌──────────▼─────────┐
                    │  Tier 3: Serial    │                          │  Tier 4: SIM       │
                    │  UART 115200 baud  │                          │  Synthetic data    │
                    └────────────────────┘                          └────────────────────┘
```

**Transport priority:** PCIe → Ethernet → Serial → SIM  
The bridge auto-probes and selects the best available transport — no manual configuration required for most setups.

---

## Directory Structure

```
lucy-bridge/
├── lucy_bridge_service.py      ← Main FastAPI service (run this)
├── fpga_pipe_server.py         ← EMMA FPGA named-pipe relay (optional)
├── BRIDGE_SETUP_GUIDE.md       ← This file
├── windows/
│   ├── hardware_probe.py       ← Interface auto-detection
│   ├── pcie_interface.py       ← PCIe / FPGA frame protocol
│   ├── ethernet_interface.py   ← Ethernet BMC / Redfish / IPMI
│   └── serial_interface.py     ← UART serial fallback
├── hal/
│   └── hal_bridge_adapter.py   ← HAL adapter (LucyBoundSystem API)
└── dashboard/
    └── HardwareBridgePanel.tsx ← React dashboard component
```

---

## Requirements

### Python (Windows host)
```
Python 3.11+
fastapi
uvicorn[standard]
pydantic
pyserial          # Serial transport
pynvml            # GPU telemetry (optional, falls back to nvidia-smi)
pywin32           # Named pipe support (optional)
requests          # HTTP transport helpers
```

Install all at once:
```powershell
pip install fastapi "uvicorn[standard]" pydantic pyserial pynvml pywin32 requests
```

### Hardware requirements by transport tier

| Tier | Transport | Requirements |
|------|-----------|-------------|
| 1    | PCIe      | Windows PCIe passthrough driver (KMDF/WinUSB) + Sovereign v2.1 in same chassis |
| 2    | Ethernet  | 10GbE connection to board BMC; OpenBMC running on board |
| 3    | Serial    | USB-UART adapter (FTDI/CP2102); UART header on Sovereign v2.1 at 115200 8N1 |
| 4    | SIM       | No hardware — fully synthetic, good for development/testing |

---

## Quick Start

### Option A — Simulation mode (no hardware, test the UI)
```powershell
cd lucy-bridge
python lucy_bridge_service.py --mode sim
```
Open Lucy dashboard → click **Hardware** in the sidebar → click **Connect**.

---

### Option B — Ethernet mode (most common, board on same LAN)

**Step 1:** Find the board's BMC IP address.
```powershell
# The board broadcasts mDNS as "sovereign-v21.local"
ping sovereign-v21.local

# Or check your DHCP server — board MAC prefix is vendor-specific
# Default BMC IPs tried by the probe:
#   192.168.1.200, 192.168.0.200, 10.0.0.200, 172.16.0.200
```

**Step 2:** Verify BMC Redfish API is reachable.
```powershell
curl -k https://192.168.1.200/redfish/v1/
# Should return {"@odata.type": "#ServiceRoot..."}
```

**Step 3:** Start the bridge service.
```powershell
cd lucy-bridge
python lucy_bridge_service.py --mode proto
```

**Step 4:** Confirm bridge is running.
```powershell
curl http://localhost:8765/health
# {"ok": true, "adapter": true, ...}
```

---

### Option C — Native PCIe mode (board in same chassis as Windows PC)

**Step 1:** Install the Sovereign v2.1 PCIe driver.
- Open Device Manager → find "Unknown PCIe Device" (Vendor 0x10EE, Device 0x9038)
- Install the KMDF driver from `drivers/sovereign_v21_pcie.inf`
- Alternatively use WinUSB generic driver for basic functionality

**Step 2:** Install pcie_interface dependencies.
```powershell
pip install pywin32
```

**Step 3:** Start the bridge in native mode.
```powershell
cd lucy-bridge
python lucy_bridge_service.py --mode native
```

---

### Option D — Serial mode (USB-UART cable)

**Step 1:** Connect USB-UART to Sovereign v2.1 UART header (J14 on the board).
- TX → board RX (pin 2)
- RX → board TX (pin 3)  
- GND → GND (pin 6)
- Settings: 115200 baud, 8N1, no flow control

**Step 2:** Find the COM port.
```powershell
# PowerShell
[System.IO.Ports.SerialPort]::GetPortNames()
# Returns: COM3, COM4, etc.
```

**Step 3:** Start the bridge.
```powershell
cd lucy-bridge
python lucy_bridge_service.py --mode auto
# Bridge will detect the serial port automatically

# Or specify explicitly:
# (edit windows/serial_interface.py DEFAULT_PORT or set env var LUCY_SERIAL_PORT=COM3)
```

---

## FPGA Named-Pipe Relay (Advanced)

For direct EMMA FPGA command passthrough from Lucy OS to the hardware, run the pipe server alongside the bridge service:

```powershell
# Terminal 1 — bridge service
python lucy_bridge_service.py --mode proto

# Terminal 2 — FPGA pipe relay
python fpga_pipe_server.py --mode auto --transport pipe
```

Lucy OS (Windows) can then write 32-byte EMMA frames directly to:
```
\\.\pipe\lucy_emma_bridge
```

The pipe server decodes frames and forwards them to the appropriate backend (ioctl, Ethernet REST, or Serial JSON).

---

## Service Endpoints Reference

All endpoints are on `http://localhost:8765` by default.

### Board Status & Telemetry

| Method | Endpoint      | Description |
|--------|--------------|-------------|
| GET    | `/`          | Service info, available endpoints |
| GET    | `/health`    | Health check — always fast |
| GET    | `/status`    | Full board status (GPU metrics, FPGA, power) |
| GET    | `/telemetry` | Live telemetry (cached 0.5s) |
| GET    | `/nodes`     | 137-node topology with health |
| GET    | `/sensors`   | SenseMesh: temp, fans, voltage |
| GET    | `/power`     | Power draw, PSU efficiency, DVFS state |
| GET    | `/probe`     | Interface probe results |

### Governance

| Method | Endpoint           | Body | Description |
|--------|-------------------|------|-------------|
| POST   | `/halt_agent`     | `{"node_id": "W042"}` | Halt a single node |
| POST   | `/halt_all`       | `{"reason": "emergency"}` | Emergency halt all 137 nodes |
| POST   | `/throttle_agent` | `{"node_id": "C3", "anomaly_score": 0.75}` | DVFS throttle |
| POST   | `/isolate_agent`  | `{"node_id": "W012", "duration_s": 60}` | Network isolate |
| POST   | `/reset_gpu`      | `{"gpu_index": 2}` | Hard-reset a GPU (0–3) |

### Streaming

| Method | Endpoint         | Description |
|--------|-----------------|-------------|
| WS     | `/ws/telemetry` | WebSocket push at 1 Hz |
| GET    | `/events`       | Server-Sent Events stream |

### FPGA Direct

| Method | Endpoint         | Description |
|--------|-----------------|-------------|
| POST   | `/fpga/command` | Send raw EMMA FPGA frame command |

---

## DVFS Throttle Table

The bridge implements the exact DVFS table from HARDWARE_MOUNT_GUIDE §7.2:

| Anomaly Score | GPU Clock |
|--------------|-----------|
| 0.00 – 0.30  | 2520 MHz  |
| 0.30 – 0.60  | 1890 MHz  |
| 0.60 – 0.80  | 1260 MHz  |
| 0.80 – 0.95  |  630 MHz  |
| 0.95 – 1.00  |  735 MHz  |

---

## EMMA FPGA Frame Protocol

The bridge implements the full 32-byte frame protocol from HARDWARE_MOUNT_GUIDE §7.3:

```
Offset  Size  Field        Description
──────  ────  ─────────    ──────────────────────────────────────
0       1     magic        Always 0xE5
1       1     cmd          FPGACmd enum (see below)
2       2     payload_len  Payload length (LE uint16)
4       16    target       Node ID string, null-padded UTF-8
20      4     param        Command parameter (LE uint32)
24      4     seq          Sequence number (LE uint32)
28      4     crc32        CRC32 over bytes 0–27
```

**FPGACmd values:**
```
0x00  NOP            0x01  HALT_AGENT    0x02  HALT_ALL
0x03  THROTTLE_DVFS  0x04  RESET_GPU     0x05  ISOLATE_AGENT
0x06  RESUME_AGENT   0x07  SET_CLOCK     0x10  GET_STATUS
0x11  GET_TELEMETRY  0x12  GET_SENSORS   0x13  GET_POWER
0x20  PING           0xAC  ACK           0xDE  NACK
```

---

## 137-Node Topology

```
PRIME   — 1 node   — GPU 0, MIG profile 4g.48gb
C1–C8   — 8 nodes  — GPU 0-3, MIG profile 2g.24gb (2 per GPU)
W001–W128 — 128 nodes — GPU 0-3, MPS slices (32 per GPU)
```

Node ID format used in governance commands:
- `PRIME` — the prime orchestrator
- `C1` through `C8` — cluster heads
- `W001` through `W128` — worker nodes (zero-padded 3 digits)

---

## Dashboard Integration

The bridge ships with a React panel (`HardwareBridgePanel.tsx`) pre-wired into the Lucy OS v5 dashboard.

To access it:
1. Start `lucy_bridge_service.py`
2. Open the Lucy dashboard
3. Click **🔌 Hardware** in the sidebar
4. Click **Connect** (or it will auto-connect if bridge is on `localhost:8765`)

The panel shows:
- Transport tier and connection status
- Live telemetry: lucidity score, mesh health, anomaly score, GPU metrics
- 137-node health grid (click nodes to halt/isolate)
- GPU gauges (util, VRAM, power, temperature)
- Governance controls (halt, throttle, isolate, reset GPU)
- Interface probe results

---

## Troubleshooting

### "Bridge service is not reachable"
- Confirm `lucy_bridge_service.py` is running: `curl http://localhost:8765/health`
- Check firewall: Windows Defender may block port 8765
  ```powershell
  netsh advfirewall firewall add rule name="Lucy Bridge" dir=in action=allow protocol=TCP localport=8765
  ```

### Transport stuck in SIM mode
- Run the probe manually to see what's detected:
  ```powershell
  python -c "from windows.hardware_probe import run_probe; r=run_probe(); print(r)"
  ```
- Check that the board BMC is reachable: `ping sovereign-v21.local`
- Verify Ethernet cable and switch port link status

### GPU telemetry shows zeros
- Install pynvml: `pip install pynvml`
- Or ensure `nvidia-smi` is on PATH: `nvidia-smi -L`
- NVIDIA drivers must be installed on the Windows host for native GPU access

### FPGA commands return NACK
- In SIM mode, NACKs are synthetic — expected for unknown commands
- In proto/native mode: check EMMA firmware version matches expected `0xE5` magic
- Verify CRC32: the bridge uses standard zlib CRC32 over bytes 0–27 of the frame

### "pywin32 not installed" warning on Linux
- This is expected — named pipe server falls back to TCP on port 8767 automatically
- Connect via: `nc 127.0.0.1 8767` and send raw 32-byte frames

---

## Running as a Windows Service (Optional)

To have the bridge start automatically with Windows:

```powershell
# Install NSSM (Non-Sucking Service Manager)
winget install NSSM.NSSM

# Create the service
nssm install LucyBridge "C:\Python311\python.exe"
nssm set LucyBridge AppParameters "C:\lucy-bridge\lucy_bridge_service.py --mode auto"
nssm set LucyBridge AppDirectory "C:\lucy-bridge"
nssm set LucyBridge Start SERVICE_AUTO_START
nssm start LucyBridge
```

---

## Architecture Notes

The bridge is designed as a **transparent proxy** — Lucy OS code needs **zero changes** to work with it. The `lucy_bridge()` factory function in `hal/hal_bridge_adapter.py` returns an object with an identical API to `lucy_mount()` from the original `lucy_mount.py`.

Transport selection is fully automatic:
1. Hardware probe runs on startup
2. Best available transport is selected (PCIe > Ethernet > Serial > SIM)
3. All HAL calls route transparently through the selected transport
4. If a transport fails mid-session, the bridge falls back to the next tier

---

*Lucy OS v5 — Sovereign v2.1 Hardware Bridge v1.0*  
*Built for the 137-node hyperswarm neural mesh*