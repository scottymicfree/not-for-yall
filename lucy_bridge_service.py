"""
lucy_bridge_service.py — Lucy OS Hardware Bridge Service
=========================================================
A FastAPI service that runs on the Windows host alongside Lucy OS.
It auto-detects the best available transport to Sovereign v2.1:
  PCIe (direct DMA) → Ethernet (BMC Redfish) → USB → Serial → SIM

Lucy OS calls this service at http://localhost:8765/...  as if it were
talking directly to the HAL layer. Zero changes needed in Lucy OS code.

Endpoints mirror the LucyBoundSystem API from lucy_mount.py:
  GET  /status                  — full board status
  GET  /telemetry               — live telemetry (latency-optimised)
  POST /halt_agent              — governance: halt a node
  POST /halt_all                — governance: halt all nodes
  POST /throttle_agent          — DVFS throttle
  POST /isolate_agent           — network-isolate a node
  POST /reset_gpu               — GPU reset
  GET  /nodes                   — 137-node topology
  GET  /sensors                 — SenseMesh readings
  GET  /power                   — power/thermal readings
  GET  /probe                   — interface probe result
  WS   /ws/telemetry            — live telemetry stream (1 Hz)
  SSE  /events                  — Server-Sent Events stream

Usage:
  python lucy_bridge_service.py                 # auto-detect
  python lucy_bridge_service.py --mode sim      # simulation
  python lucy_bridge_service.py --mode proto    # prototype (Ethernet)
  python lucy_bridge_service.py --mode native   # Sovereign v2.1
  python lucy_bridge_service.py --port 8765     # custom port
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, Optional

# ── FastAPI / Uvicorn ──────────────────────────────────────────────────────────
try:
    from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import StreamingResponse, JSONResponse
    from pydantic import BaseModel
    import uvicorn
except ImportError:
    print("[bridge] Installing fastapi + uvicorn …")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install",
                           "fastapi", "uvicorn[standard]", "pydantic"])
    from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import StreamingResponse, JSONResponse
    from pydantic import BaseModel
    import uvicorn

# ── Bridge modules (relative import with fallback path insertion) ───────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

try:
    from windows.hardware_probe import run_probe, ProbeResult, InterfaceType
    from hal.hal_bridge_adapter import lucy_bridge, HALBridgeAdapter
    _BRIDGE_MODULES_OK = True
except ImportError as e:
    print(f"[bridge] Warning: bridge modules not found ({e}). Running in stub mode.")
    _BRIDGE_MODULES_OK = False

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [bridge] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("lucy_bridge")

# ── Global state ──────────────────────────────────────────────────────────────
_adapter: Optional["HALBridgeAdapter"] = None
_probe_result: Optional[Any] = None
_telemetry_cache: Dict[str, Any] = {}
_telemetry_ts: float = 0.0
TELEMETRY_CACHE_TTL = 0.5          # seconds — refresh at max 2 Hz
_ws_clients: list[WebSocket] = []

# ══════════════════════════════════════════════════════════════════════════════
# Pydantic request models
# ══════════════════════════════════════════════════════════════════════════════

class HaltAgentRequest(BaseModel):
    node_id: str
    reason: Optional[str] = "external_command"

class ThrottleRequest(BaseModel):
    node_id: str
    anomaly_score: float          # 0.0 – 1.0

class IsolateRequest(BaseModel):
    node_id: str
    duration_s: Optional[int] = 60

class ResetGPURequest(BaseModel):
    gpu_index: int                # 0–3

class HaltAllRequest(BaseModel):
    reason: Optional[str] = "emergency"

# ══════════════════════════════════════════════════════════════════════════════
# Lifespan — boot bridge on startup
# ══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _adapter, _probe_result

    log.info("=== Lucy Bridge Service starting ===")

    if _BRIDGE_MODULES_OK:
        mode_arg = getattr(app.state, "hal_mode", None)
        log.info("Running hardware probe …")
        try:
            _probe_result = run_probe()
            mode = mode_arg or _probe_result.hal_mode
            log.info(
                f"Probe complete — transport={_probe_result.recommended_interface.name}, "
                f"mode={mode}"
            )
        except Exception as exc:
            log.warning(f"Hardware probe failed ({exc}), falling back to SIM")
            mode = "sim"
            _probe_result = None

        try:
            _adapter = lucy_bridge(mode=mode)
            log.info(f"HAL bridge adapter initialised (mode={mode})")
        except Exception as exc:
            log.error(f"HAL bridge adapter init failed: {exc}")
            _adapter = None
    else:
        log.warning("Bridge modules unavailable — all endpoints return synthetic data")
        _adapter = None
        _probe_result = None

    # Start background telemetry refresh task
    asyncio.create_task(_telemetry_refresh_loop())

    yield

    log.info("=== Lucy Bridge Service stopping ===")
    if _adapter:
        try:
            _adapter.close()
        except Exception:
            pass


def create_app(hal_mode: str = None) -> FastAPI:
    app = FastAPI(
        title="Lucy Hardware Bridge",
        description="Connects Lucy OS (Windows) to Sovereign v2.1 hardware",
        version="1.0.0",
        lifespan=lifespan,
    )
    if hal_mode:
        app.state.hal_mode = hal_mode

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app

app = create_app()

# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _adapter_required():
    """Raise 503 if adapter is unavailable."""
    if _adapter is None:
        raise HTTPException(
            status_code=503,
            detail="Hardware bridge adapter not initialised. Check /probe for transport status."
        )

def _synthetic_status() -> Dict[str, Any]:
    """Return synthetic board status when adapter is unavailable."""
    import random, math
    t = time.time()
    return {
        "mode": "sim",
        "transport": "none",
        "timestamp": t,
        "board": "Sovereign v2.1 (synthetic)",
        "node_count": 137,
        "online": True,
        "health_pct": 97.2,
        "lucidity_score": 0.93 + 0.03 * math.sin(t / 10),
        "layer_count": 8,
        "gpus": [
            {
                "index": i,
                "name": "NVIDIA L40S",
                "bus_id": f"0000:{0x01 + i*0x40:02x}:00.0",
                "temp_c": round(58 + random.uniform(-3, 3), 1),
                "power_w": round(180 + random.uniform(-10, 10), 1),
                "util_pct": round(72 + random.uniform(-8, 8), 1),
                "mem_used_mb": round(32000 + random.uniform(-500, 500)),
                "mem_total_mb": 46068,
            }
            for i in range(4)
        ],
        "fpga": {
            "status": "operational",
            "temp_c": 42.0,
            "version": "EMMA-v2.1",
        },
        "power": {
            "board_w": round(720 + random.uniform(-20, 20), 1),
            "psu_efficiency_pct": 94.0,
        },
    }

def _synthetic_telemetry() -> Dict[str, Any]:
    """Return synthetic telemetry when adapter unavailable."""
    import random, math
    t = time.time()
    return {
        "timestamp": t,
        "mode": "sim",
        "lucidity_score": round(0.93 + 0.03 * math.sin(t / 10), 4),
        "mesh_health": round(97.0 + random.uniform(-1, 1), 2),
        "anomaly_score": round(max(0, 0.08 + 0.04 * math.sin(t / 7)), 4),
        "active_nodes": 137,
        "gpu_util_avg": round(71 + 5 * math.sin(t / 13), 2),
        "gpu_temp_max": round(60 + random.uniform(-2, 2), 1),
        "gpu_power_total_w": round(722 + random.uniform(-15, 15), 1),
        "fpga_queue_depth": random.randint(0, 12),
        "memory_spine_gb": round(1.83 + random.uniform(-0.05, 0.05), 2),
        "layer_states": {
            "perception": "active",
            "memory": "active",
            "swarm_unr5": "active",
            "emma_lte": "active",
            "lucy_prime": "active",
            "infrastructure": "active",
            "output": "active",
            "safety": "active",
        },
    }

# ══════════════════════════════════════════════════════════════════════════════
# Background telemetry refresh
# ══════════════════════════════════════════════════════════════════════════════

async def _telemetry_refresh_loop():
    """Refresh telemetry cache every 1 s and push to WebSocket clients."""
    global _telemetry_cache, _telemetry_ts
    while True:
        try:
            await asyncio.sleep(1.0)
            now = time.time()
            if now - _telemetry_ts < TELEMETRY_CACHE_TTL:
                continue

            if _adapter:
                try:
                    loop = asyncio.get_event_loop()
                    data = await loop.run_in_executor(None, _adapter.get_telemetry)
                    _telemetry_cache = data if isinstance(data, dict) else {"raw": data}
                except Exception as exc:
                    log.debug(f"Telemetry fetch error: {exc}")
                    _telemetry_cache = _synthetic_telemetry()
            else:
                _telemetry_cache = _synthetic_telemetry()

            _telemetry_ts = now

            # Push to all WebSocket clients
            if _ws_clients:
                dead = []
                msg = json.dumps(_telemetry_cache)
                for ws in list(_ws_clients):
                    try:
                        await ws.send_text(msg)
                    except Exception:
                        dead.append(ws)
                for ws in dead:
                    if ws in _ws_clients:
                        _ws_clients.remove(ws)

        except asyncio.CancelledError:
            break
        except Exception as exc:
            log.warning(f"Telemetry loop error: {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# REST endpoints
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/", tags=["meta"])
async def root():
    return {
        "service": "Lucy Hardware Bridge",
        "version": "1.0.0",
        "status": "running",
        "adapter": _adapter is not None,
        "transport": (
            _probe_result.recommended_interface.name
            if _probe_result else "none"
        ),
        "endpoints": [
            "/status", "/telemetry", "/nodes", "/sensors", "/power", "/probe",
            "/halt_agent", "/halt_all", "/throttle_agent", "/isolate_agent",
            "/reset_gpu", "/ws/telemetry", "/events",
        ],
    }


@app.get("/probe", tags=["meta"])
async def get_probe():
    """Return the hardware interface probe result."""
    if _probe_result is None:
        return {
            "probed": False,
            "recommended_interface": "NONE",
            "hal_mode": "sim",
            "interfaces": {},
        }
    return {
        "probed": True,
        "recommended_interface": _probe_result.recommended_interface.name,
        "hal_mode": _probe_result.hal_mode,
        "interfaces": {
            k.name: {
                "available": v.available,
                "latency_ms": v.latency_ms,
                "latency_class": v.latency_class.name,
                "detail": v.detail,
                "error": v.error,
            }
            for k, v in _probe_result.interfaces.items()
        },
    }


@app.get("/status", tags=["board"])
async def get_status():
    """Full board status — health, GPU metrics, FPGA state."""
    if _adapter is None:
        return _synthetic_status()
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _adapter.get_status)
        return result if isinstance(result, dict) else {"raw": str(result)}
    except Exception as exc:
        log.error(f"/status error: {exc}")
        return _synthetic_status()


@app.get("/telemetry", tags=["board"])
async def get_telemetry():
    """Live telemetry — low-latency, cached 0.5 s."""
    if _telemetry_cache:
        return _telemetry_cache
    return _synthetic_telemetry()


@app.get("/nodes", tags=["board"])
async def get_nodes():
    """137-node topology with individual health."""
    if _adapter is None:
        return _build_synthetic_nodes()
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _adapter.list_nodes)
        return result
    except Exception as exc:
        log.error(f"/nodes error: {exc}")
        return _build_synthetic_nodes()


def _build_synthetic_nodes():
    import random
    nodes = []
    nodes.append({
        "id": "PRIME", "role": "prime", "gpu": 0,
        "mig_profile": "4g.48gb", "health": "nominal",
        "util_pct": round(65 + random.uniform(-5, 5), 1),
    })
    for ci in range(1, 9):
        nodes.append({
            "id": f"C{ci}", "role": "cluster",
            "gpu": (ci - 1) // 2, "mig_profile": "2g.24gb",
            "health": "nominal",
            "util_pct": round(60 + random.uniform(-10, 10), 1),
        })
    for wi in range(1, 129):
        gpu = (wi - 1) // 32
        nodes.append({
            "id": f"W{wi:03d}", "role": "worker",
            "gpu": gpu, "mig_profile": "mps_slice",
            "health": "nominal" if random.random() > 0.02 else "degraded",
            "util_pct": round(55 + random.uniform(-15, 15), 1),
        })
    return {"nodes": nodes, "total": len(nodes), "mode": "sim"}


@app.get("/sensors", tags=["board"])
async def get_sensors():
    """SenseMesh sensor readings (temp, voltage, fan)."""
    if _adapter is None:
        return _synthetic_sensors()
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _adapter.sense_mesh.read_all)
        return result if isinstance(result, dict) else {"raw": str(result)}
    except Exception as exc:
        log.error(f"/sensors error: {exc}")
        return _synthetic_sensors()


def _synthetic_sensors():
    import random
    return {
        "mode": "sim",
        "timestamp": time.time(),
        "thermal": [
            {"zone": f"GPU{i}", "temp_c": round(58 + random.uniform(-4, 4), 1)}
            for i in range(4)
        ] + [
            {"zone": "FPGA", "temp_c": round(42 + random.uniform(-2, 2), 1)},
            {"zone": "VRM", "temp_c": round(52 + random.uniform(-3, 3), 1)},
            {"zone": "NVMe_RAID", "temp_c": round(38 + random.uniform(-2, 2), 1)},
        ],
        "fans": [
            {"id": f"FAN{i}", "rpm": round(2400 + random.uniform(-100, 100))}
            for i in range(6)
        ],
        "voltage": {
            "12v_rail": round(12.04 + random.uniform(-0.05, 0.05), 3),
            "3v3_rail": round(3.31 + random.uniform(-0.02, 0.02), 3),
        },
    }


@app.get("/power", tags=["board"])
async def get_power():
    """Power and thermal summary from BMC."""
    if _adapter is None:
        return _synthetic_power()
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _adapter.power_manager.get_power_state)
        return result if isinstance(result, dict) else {"raw": str(result)}
    except Exception as exc:
        log.error(f"/power error: {exc}")
        return _synthetic_power()


def _synthetic_power():
    import random
    gpus = [round(178 + random.uniform(-12, 12), 1) for _ in range(4)]
    return {
        "mode": "sim",
        "timestamp": time.time(),
        "board_total_w": round(sum(gpus) + 85, 1),
        "gpu_power_w": gpus,
        "fpga_power_w": round(22 + random.uniform(-1, 1), 1),
        "nvme_power_w": round(18 + random.uniform(-1, 1), 1),
        "psu_efficiency_pct": 94.2,
        "dvfs_state": {
            "anomaly_score": 0.12,
            "clock_mhz": 2520,
            "policy": "performance",
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# Governance endpoints
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/halt_agent", tags=["governance"])
async def halt_agent(req: HaltAgentRequest):
    """Halt a specific node (governance command)."""
    log.info(f"GOVERNANCE halt_agent node={req.node_id} reason={req.reason}")
    if _adapter is None:
        return {"ok": True, "mode": "sim", "node_id": req.node_id, "action": "halted"}
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _adapter.governance.halt_agent(req.node_id, req.reason)
        )
        return result if isinstance(result, dict) else {"ok": True, "result": str(result)}
    except Exception as exc:
        log.error(f"/halt_agent error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/halt_all", tags=["governance"])
async def halt_all(req: HaltAllRequest):
    """Emergency halt of ALL 137 nodes."""
    log.warning(f"GOVERNANCE halt_all reason={req.reason}")
    if _adapter is None:
        return {"ok": True, "mode": "sim", "nodes_halted": 137, "reason": req.reason}
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _adapter.governance.halt_all(req.reason)
        )
        return result if isinstance(result, dict) else {"ok": True, "result": str(result)}
    except Exception as exc:
        log.error(f"/halt_all error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/throttle_agent", tags=["governance"])
async def throttle_agent(req: ThrottleRequest):
    """Apply DVFS throttle to a node based on anomaly_score."""
    log.info(f"GOVERNANCE throttle node={req.node_id} score={req.anomaly_score:.3f}")
    if _adapter is None:
        clock = _score_to_clock(req.anomaly_score)
        return {
            "ok": True, "mode": "sim",
            "node_id": req.node_id,
            "anomaly_score": req.anomaly_score,
            "clock_mhz": clock,
        }
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _adapter.governance.throttle_agent(req.node_id, req.anomaly_score)
        )
        return result if isinstance(result, dict) else {"ok": True, "result": str(result)}
    except Exception as exc:
        log.error(f"/throttle_agent error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


def _score_to_clock(score: float) -> int:
    """DVFS table from HARDWARE_MOUNT_GUIDE §7.2."""
    if score < 0.30:  return 2520
    if score < 0.60:  return 1890
    if score < 0.80:  return 1260
    if score < 0.95:  return 630
    return 735


@app.post("/isolate_agent", tags=["governance"])
async def isolate_agent(req: IsolateRequest):
    """Network-isolate a node for the given duration."""
    log.info(f"GOVERNANCE isolate node={req.node_id} duration={req.duration_s}s")
    if _adapter is None:
        return {
            "ok": True, "mode": "sim",
            "node_id": req.node_id,
            "isolated_for_s": req.duration_s,
        }
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _adapter.governance.isolate_agent(req.node_id, req.duration_s)
        )
        return result if isinstance(result, dict) else {"ok": True, "result": str(result)}
    except Exception as exc:
        log.error(f"/isolate_agent error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/reset_gpu", tags=["governance"])
async def reset_gpu(req: ResetGPURequest):
    """Hard-reset a GPU (index 0–3)."""
    if req.gpu_index not in range(4):
        raise HTTPException(status_code=400, detail="gpu_index must be 0–3")
    log.warning(f"GOVERNANCE reset_gpu gpu={req.gpu_index}")
    if _adapter is None:
        return {"ok": True, "mode": "sim", "gpu_index": req.gpu_index, "action": "reset"}
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _adapter.governance.reset_gpu(req.gpu_index)
        )
        return result if isinstance(result, dict) else {"ok": True, "result": str(result)}
    except Exception as exc:
        log.error(f"/reset_gpu error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ══════════════════════════════════════════════════════════════════════════════
# Streaming endpoints
# ══════════════════════════════════════════════════════════════════════════════

@app.websocket("/ws/telemetry")
async def ws_telemetry(websocket: WebSocket):
    """WebSocket — pushes telemetry at 1 Hz."""
    await websocket.accept()
    _ws_clients.append(websocket)
    log.info(f"WebSocket client connected ({len(_ws_clients)} total)")
    try:
        while True:
            # Keep-alive: read any ping messages from client
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                if data == "ping":
                    await websocket.send_text(json.dumps({"pong": True}))
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in _ws_clients:
            _ws_clients.remove(websocket)
        log.info(f"WebSocket client disconnected ({len(_ws_clients)} remaining)")


@app.get("/events", tags=["streaming"])
async def sse_events():
    """Server-Sent Events — telemetry stream for dashboard."""

    async def event_generator() -> AsyncGenerator[str, None]:
        last_ts = 0.0
        while True:
            await asyncio.sleep(1.0)
            global _telemetry_cache
            data = _telemetry_cache if _telemetry_cache else _synthetic_telemetry()
            ts = data.get("timestamp", time.time())
            if ts != last_ts:
                last_ts = ts
                yield f"data: {json.dumps(data)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# Health check
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health", tags=["meta"])
async def health():
    return {
        "ok": True,
        "ts": time.time(),
        "adapter": _adapter is not None,
        "ws_clients": len(_ws_clients),
        "telemetry_age_s": round(time.time() - _telemetry_ts, 2),
    }


# ══════════════════════════════════════════════════════════════════════════════
# FPGA direct command endpoint (advanced)
# ══════════════════════════════════════════════════════════════════════════════

class FPGACommandRequest(BaseModel):
    cmd: str                       # e.g. "HALT_AGENT", "THROTTLE_DVFS"
    target: Optional[str] = ""     # node_id string, padded to 16 bytes
    param: Optional[int] = 0       # 4-byte param
    raw: Optional[bool] = False    # return raw 32-byte hex frame

@app.post("/fpga/command", tags=["fpga"])
async def fpga_command(req: FPGACommandRequest):
    """Send a raw EMMA FPGA 32-byte frame command."""
    if _adapter is None:
        return {
            "ok": True, "mode": "sim",
            "cmd": req.cmd, "target": req.target,
            "ack": "simulated",
        }
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _adapter.emma.send_command(req.cmd, req.target, req.param)
        )
        return result if isinstance(result, dict) else {"ok": True, "result": str(result)}
    except Exception as exc:
        log.error(f"/fpga/command error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Lucy Hardware Bridge Service")
    parser.add_argument("--mode",  choices=["sim", "proto", "native", "auto"],
                        default="auto", help="HAL mode override")
    parser.add_argument("--port",  type=int, default=8765, help="HTTP port")
    parser.add_argument("--host",  default="127.0.0.1", help="Bind address")
    parser.add_argument("--reload", action="store_true", help="Hot-reload (dev)")
    args = parser.parse_args()

    hal_mode = None if args.mode == "auto" else args.mode
    app.state.hal_mode = hal_mode

    log.info(f"Starting Lucy Bridge on {args.host}:{args.port} (HAL mode: {args.mode})")

    uvicorn.run(
        "lucy_bridge_service:app",
        host=args.host,
        port=args.port,
        log_level="info",
        reload=args.reload,
    )


if __name__ == "__main__":
    main()