"""
AME API — FastAPI router for the Autonomous Mesh Engine
Endpoints: core status, query, sessions, event bus, plugins, health
"""

from __future__ import annotations
import time
import asyncio
import json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ame.event_bus  import event_bus, AMEEventBus, BusEvent, Priority
from ame.lucy_core  import lucy_core, SystemState
from ame.plugins    import plugin_manager, PluginType, PluginState

# ── Router ─────────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/ame", tags=["ame"])

# ── Request / Response Models ──────────────────────────────────────────────────

class QueryRequest(BaseModel):
    text:       str
    session_id: Optional[str] = None
    context:    Dict[str, Any] = {}

class QueryResponse(BaseModel):
    query_id:   str
    response:   str
    confidence: float
    lte_score:  float
    consensus:  str
    blocked:    bool
    session_id: str
    latency_ms: float
    state:      str
    timestamp:  float

class PublishRequest(BaseModel):
    topic:    str
    payload:  Any
    priority: str = "NORMAL"   # LOW / NORMAL / HIGH / CRITICAL
    source:   str = "api"
    ttl:      float = 30.0

class BootRequest(BaseModel):
    force: bool = False

class StateRequest(BaseModel):
    state: str   # nominal / reflective / repair / elevated / standby

class PluginLoadRequest(BaseModel):
    file_path: Optional[str] = None   # load from file
    directory: Optional[str] = None   # load from directory

# ── Priority mapper ────────────────────────────────────────────────────────────

_PRIORITY_MAP = {
    "LOW":      Priority.LOW,
    "NORMAL":   Priority.NORMAL,
    "HIGH":     Priority.HIGH,
    "CRITICAL": Priority.CRITICAL,
}

# ── Core Status ────────────────────────────────────────────────────────────────

@router.get("/status", summary="AME Lucy Core full status")
async def ame_status():
    """Return full health snapshot of the 137-node cognitive mesh."""
    return lucy_core.health_snapshot()

@router.get("/layers", summary="Layer-by-layer health status")
async def layer_health():
    """Return health status for each of the 8 cognitive layers."""
    return {
        "layers":    lucy_core.layer_health(),
        "state":     lucy_core.get_state().value,
        "timestamp": time.time(),
    }

@router.get("/state", summary="Current system state")
async def get_state():
    state = lucy_core.get_state()
    return {"state": state.value, "timestamp": time.time()}

@router.post("/state", summary="Set system state")
async def set_state(req: StateRequest):
    """
    Manually transition Lucy Core system state.
    Valid: nominal / reflective / repair / elevated / standby
    """
    try:
        new_state = SystemState(req.state)
    except ValueError:
        valid = [s.value for s in SystemState]
        raise HTTPException(status_code=400,
                            detail=f"Invalid state. Valid: {valid}")
    lucy_core.set_state(new_state)
    return {"state": new_state.value, "timestamp": time.time()}

@router.post("/boot", summary="Boot the AME Lucy Core")
async def boot_core(req: BootRequest, background_tasks: BackgroundTasks):
    """
    Trigger an async boot of the Lucy Core cognitive mesh.
    Returns immediately; boot runs in background.
    Use GET /ame/status to monitor boot progress.
    """
    current = lucy_core.get_state()
    if current == SystemState.NOMINAL and not req.force:
        return {
            "message": "Lucy Core already booted",
            "state":   current.value,
            "timestamp": time.time(),
        }

    async def _do_boot():
        await lucy_core.boot()

    background_tasks.add_task(_do_boot)
    return {
        "message":   "Boot initiated",
        "state":     "booting",
        "timestamp": time.time(),
    }

# ── Query Interface ────────────────────────────────────────────────────────────

@router.post("/query", response_model=QueryResponse, summary="Send a query to Lucy Core")
async def query(req: QueryRequest):
    """
    Route a text query through the full 137-node cognitive mesh.
    Returns response + LTE score + telemetry metadata.
    """
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text cannot be empty")

    result = await lucy_core.query(
        text=req.text,
        session_id=req.session_id,
        context=req.context,
    )
    return QueryResponse(
        query_id=result.query_id,
        response=result.response,
        confidence=result.confidence,
        lte_score=result.lte_score,
        consensus=result.consensus,
        blocked=result.blocked,
        session_id=result.session_id,
        latency_ms=result.latency_ms,
        state=result.state,
        timestamp=result.timestamp,
    )

@router.post("/query/stream", summary="Streaming query response (SSE)")
async def query_stream(req: QueryRequest):
    """
    Stream a Lucy response via Server-Sent Events.
    Each chunk is a JSON-encoded SSE data line.
    """
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text cannot be empty")

    async def _generate():
        session_id = req.session_id or "stream_session"
        try:
            # Try chat engine stream if available
            from chat.chat_engine import chat_engine
            async for chunk in chat_engine.stream(req.text, session_id=session_id):
                data = json.dumps({"type": "chunk", "content": chunk})
                yield f"data: {data}\n\n"
        except Exception:
            # Fallback to non-streaming query
            result = await lucy_core.query(
                text=req.text,
                session_id=req.session_id,
            )
            words = result.response.split()
            for i, word in enumerate(words):
                chunk_data = json.dumps({"type": "chunk", "content": word + " "})
                yield f"data: {chunk_data}\n\n"
                if i % 5 == 0:
                    await asyncio.sleep(0.02)

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )

# ── Session Management ─────────────────────────────────────────────────────────

@router.post("/sessions", summary="Create a new session")
async def create_session(session_id: Optional[str] = None):
    sid = lucy_core.create_session(session_id)
    return {"session_id": sid, "created": True, "timestamp": time.time()}

@router.get("/sessions", summary="List all active sessions")
async def list_sessions():
    return {
        "sessions":  lucy_core.list_sessions(),
        "count":     len(lucy_core.list_sessions()),
        "timestamp": time.time(),
    }

@router.get("/sessions/{session_id}", summary="Get session info")
async def get_session(session_id: str):
    s = lucy_core.get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return {"session_id": session_id, **s, "timestamp": time.time()}

@router.delete("/sessions/{session_id}", summary="Close a session")
async def close_session(session_id: str):
    ok = lucy_core.close_session(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return {"session_id": session_id, "closed": True, "timestamp": time.time()}

# ── Event Bus ─────────────────────────────────────────────────────────────────

@router.get("/bus/stats", summary="Event bus statistics")
async def bus_stats():
    """Return publish/deliver/drop counts and queue depths."""
    return {
        "stats":      event_bus.stats(),
        "topics":     event_bus.topic_stats(),
        "subs":       event_bus.subscriptions(),
        "timestamp":  time.time(),
    }

@router.post("/bus/publish", summary="Publish an event to the bus")
async def bus_publish(req: PublishRequest):
    """
    Publish an arbitrary event to the AME EventBus.
    Use for external integrations, testing, or manual event injection.
    """
    priority = _PRIORITY_MAP.get(req.priority.upper(), Priority.NORMAL)
    eid = await event_bus.publish(
        topic=req.topic,
        payload=req.payload,
        priority=priority,
        source=req.source,
        ttl=req.ttl,
    )
    return {
        "published":  True,
        "event_id":   eid,
        "topic":      req.topic,
        "priority":   req.priority,
        "timestamp":  time.time(),
    }

@router.get("/bus/history", summary="Event bus history")
async def bus_history(
    topic: Optional[str] = Query(default=None),
    limit: int           = Query(default=50, le=500)
):
    """Return recent events from the bus history ring-buffer."""
    return {
        "events":    event_bus.history(topic=topic, limit=limit),
        "count":     limit,
        "topic":     topic or "all",
        "timestamp": time.time(),
    }

@router.get("/bus/dead_letters", summary="Dead-letter queue")
async def dead_letters(limit: int = Query(default=50, le=200)):
    """Return events that could not be delivered."""
    return {
        "dead_letters": event_bus.dead_letters(limit=limit),
        "timestamp":    time.time(),
    }

@router.delete("/bus/dead_letters", summary="Clear dead-letter queue")
async def clear_dead_letters():
    n = event_bus.clear_dead_letters()
    return {"cleared": n, "timestamp": time.time()}

@router.get("/bus/topics", summary="Active bus topics with counts")
async def bus_topics():
    return {"topics": event_bus.topic_stats(), "timestamp": time.time()}

# ── Plugin Management ──────────────────────────────────────────────────────────

@router.get("/plugins", summary="List all registered plugins")
async def list_plugins():
    """Return all registered plugins with state and stats."""
    return {
        "plugins":   plugin_manager.all_plugins(),
        "stats":     plugin_manager.stats(),
        "timestamp": time.time(),
    }

@router.get("/plugins/active", summary="List active plugins")
async def active_plugins():
    active = plugin_manager.active_plugins()
    return {
        "plugins":   [e.to_dict() for e in active],
        "count":     len(active),
        "timestamp": time.time(),
    }

@router.get("/plugins/type/{plugin_type}", summary="Plugins by type")
async def plugins_by_type(plugin_type: str):
    try:
        pt = PluginType(plugin_type)
    except ValueError:
        raise HTTPException(status_code=400,
                            detail=f"Invalid type. Valid: {[t.value for t in PluginType]}")
    entries = plugin_manager.get_by_type(pt)
    return {
        "type":      plugin_type,
        "plugins":   [e.to_dict() for e in entries],
        "count":     len(entries),
        "timestamp": time.time(),
    }

@router.post("/plugins/{plugin_id}/load", summary="Load a plugin")
async def load_plugin(plugin_id: str):
    try:
        ok = await plugin_manager.load(plugin_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Plugin not found: {plugin_id}")
    return {"plugin_id": plugin_id, "loaded": ok, "timestamp": time.time()}

@router.post("/plugins/{plugin_id}/unload", summary="Unload a plugin")
async def unload_plugin(plugin_id: str):
    ok = await plugin_manager.unload(plugin_id)
    return {"plugin_id": plugin_id, "unloaded": ok, "timestamp": time.time()}

@router.post("/plugins/{plugin_id}/pause", summary="Pause a plugin")
async def pause_plugin(plugin_id: str):
    ok = await plugin_manager.pause(plugin_id)
    return {"plugin_id": plugin_id, "paused": ok, "timestamp": time.time()}

@router.post("/plugins/{plugin_id}/resume", summary="Resume a paused plugin")
async def resume_plugin(plugin_id: str):
    ok = await plugin_manager.resume(plugin_id)
    return {"plugin_id": plugin_id, "resumed": ok, "timestamp": time.time()}

@router.post("/plugins/load_file", summary="Load plugin from file path")
async def load_plugin_file(req: PluginLoadRequest):
    """
    Dynamically load a Lucy plugin from a .py file or directory.
    File must contain a LucyPlugin subclass with a valid MANIFEST.
    """
    if req.file_path:
        try:
            pid = await plugin_manager.load_from_file(req.file_path)
            return {"loaded": True, "plugin_id": pid, "timestamp": time.time()}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    elif req.directory:
        try:
            results = await plugin_manager.load_from_directory(req.directory)
            return {"loaded": results, "count": len(results), "timestamp": time.time()}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        raise HTTPException(status_code=400, detail="Provide file_path or directory")

@router.get("/plugins/health", summary="Health check all active plugins")
async def plugins_health():
    results = await plugin_manager.health_check_all()
    return {"health": results, "count": len(results), "timestamp": time.time()}

# ── WebSocket — Live Mesh Feed ─────────────────────────────────────────────────

class _WSManager:
    def __init__(self):
        self._connections: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket):
        try:
            self._connections.remove(ws)
        except ValueError:
            pass

    async def broadcast(self, data: dict):
        msg = json.dumps(data)
        dead = []
        for ws in self._connections:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

_ws_manager = _WSManager()

@router.websocket("/ws/mesh")
async def mesh_websocket(ws: WebSocket):
    """
    WebSocket feed for live 137-node mesh telemetry.
    Sends dashboard summaries every second.
    Messages:
      → {type: "query", text: "...", session_id: "..."}
      ← {type: "ack", ...}
      ← {type: "telemetry", ...}  (periodic)
      ← {type: "response", ...}
      ← {type: "event", topic: "...", ...}
    """
    await _ws_manager.connect(ws)

    # Subscribe to key bus events and forward them
    async def _forward_event(event: BusEvent):
        try:
            await ws.send_text(json.dumps({
                "type":      "event",
                "topic":     event.topic,
                "payload":   event.payload,
                "source":    event.source,
                "timestamp": event.timestamp,
            }))
        except Exception:
            pass

    sub_id = event_bus.subscribe("*", _forward_event)

    # Telemetry push task
    async def _telemetry_push():
        while True:
            try:
                from lte.telemetry import telemetry
                summary = telemetry.dashboard_summary()
                await ws.send_text(json.dumps({
                    "type":      "telemetry",
                    "data":      summary,
                    "timestamp": time.time(),
                }))
            except Exception:
                pass
            await asyncio.sleep(1.0)

    tel_task = asyncio.get_event_loop().create_task(_telemetry_push())

    try:
        await ws.send_text(json.dumps({
            "type":    "connected",
            "message": "Lucy OS v5 mesh connected",
            "state":   lucy_core.get_state().value,
            "version": lucy_core.VERSION,
            "timestamp": time.time(),
        }))

        while True:
            data = await ws.receive_text()
            msg  = json.loads(data)
            msg_type = msg.get("type", "")

            if msg_type == "query":
                text       = msg.get("text", "")
                session_id = msg.get("session_id")
                if text:
                    await ws.send_text(json.dumps({
                        "type": "ack", "status": "processing", "timestamp": time.time()
                    }))
                    result = await lucy_core.query(text=text, session_id=session_id)
                    await ws.send_text(json.dumps({
                        "type":       "response",
                        "query_id":   result.query_id,
                        "response":   result.response,
                        "lte_score":  result.lte_score,
                        "confidence": result.confidence,
                        "latency_ms": result.latency_ms,
                        "blocked":    result.blocked,
                        "timestamp":  result.timestamp,
                    }))

            elif msg_type == "ping":
                await ws.send_text(json.dumps({
                    "type": "pong", "timestamp": time.time()
                }))

            elif msg_type == "status":
                await ws.send_text(json.dumps({
                    "type":   "status",
                    "health": lucy_core.health_snapshot(),
                }))

            elif msg_type == "publish":
                topic   = msg.get("topic", "ws.message")
                payload = msg.get("payload", {})
                await event_bus.publish(topic=topic, payload=payload, source="ws_client")
                await ws.send_text(json.dumps({
                    "type": "ack", "status": "published", "topic": topic,
                    "timestamp": time.time()
                }))

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        tel_task.cancel()
        event_bus.unsubscribe(sub_id)
        _ws_manager.disconnect(ws)

# ── Shutdown ───────────────────────────────────────────────────────────────────

@router.post("/shutdown", summary="Graceful Lucy Core shutdown")
async def shutdown_core():
    """
    Initiate graceful shutdown of the AME Lucy Core.
    Stops heartbeat, unsubscribes all handlers, drains event bus.
    """
    await lucy_core.shutdown()
    return {"shutdown": True, "timestamp": time.time()}

# ── Health ─────────────────────────────────────────────────────────────────────

@router.get("/health", summary="AME quick health check")
async def health():
    state  = lucy_core.get_state()
    layers = lucy_core.layer_health()
    ok     = sum(1 for lh in layers.values() if lh.get("status") == "ok")
    total  = len(layers)
    status = "healthy" if state == SystemState.NOMINAL else (
             "degraded" if state == SystemState.DEGRADED else state.value)
    return {
        "status":      status,
        "state":       state.value,
        "layers_ok":   ok,
        "layers_total": total,
        "plugins":     plugin_manager.stats()["active"],
        "bus_running": event_bus.stats()["running"],
        "timestamp":   time.time(),
    }