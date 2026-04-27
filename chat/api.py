"""
Lucy OS v5 — Chat & Sandbox FastAPI Router
Mounts at /chat — WebSocket /ws/chat, REST /chat/message, /sandbox/run
"""

from __future__ import annotations
import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel

from chat.chat_engine import chat_engine
from chat.sandbox     import sandbox_runner

logger = logging.getLogger("chat.api")
router = APIRouter(tags=["chat"])


# ── REST Models ───────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message:        str
    session_id:     str = "default"
    output_channel: str = "text"
    user_id:        str = "user"

class SandboxRequest(BaseModel):
    sim_type:   str
    params:     dict = {}
    session_id: str  = "default"


# ── REST Endpoints ────────────────────────────────────────────────────

@router.post("/chat/message")
async def chat_message(req: ChatRequest):
    """Single-turn REST chat."""
    try:
        result = await chat_engine.chat(
            message        = req.message,
            session_id     = req.session_id,
            output_channel = req.output_channel,
            user_id        = req.user_id,
        )
        return result
    except Exception as e:
        logger.error(f"[ChatAPI] chat error: {e}")
        raise HTTPException(500, detail=str(e))


@router.get("/chat/history/{session_id}")
async def get_history(session_id: str, n: int = 20):
    return {"session_id": session_id, "history": chat_engine.get_history(session_id, n)}


@router.delete("/chat/session/{session_id}")
async def clear_session(session_id: str):
    chat_engine.clear_session(session_id)
    return {"cleared": session_id}


@router.get("/chat/sessions")
async def list_sessions():
    return {"sessions": chat_engine.get_sessions()}


@router.post("/sandbox/run")
async def run_sandbox(req: SandboxRequest):
    """Run a sandbox simulation."""
    result = await sandbox_runner.run(
        sim_type   = req.sim_type,
        params     = req.params,
        session_id = req.session_id,
    )
    return result.to_dict()


@router.get("/sandbox/history")
async def sandbox_history(n: int = 10):
    return {"history": sandbox_runner.get_history(n)}


@router.get("/lucy/identity")
async def get_identity():
    try:
        from lucy_prime.prime import lucy_prime
        return lucy_prime.get_identity_profile()
    except Exception as e:
        return {"error": str(e)}


@router.get("/lucy/self-state")
async def get_self_state():
    try:
        from lucy_prime.prime import lucy_prime
        return lucy_prime.get_self_state()
    except Exception as e:
        return {"error": str(e)}


@router.get("/lucy/reflection-queue")
async def get_reflection_queue():
    try:
        from lucy_prime.prime import lucy_prime
        return {
            "queue_size": lucy_prime.get_reflection_queue(),
            "next_item":  None,
        }
    except Exception as e:
        return {"error": str(e)}


# ── WebSocket Chat ────────────────────────────────────────────────────

class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self):
        self._connections: dict[str, WebSocket] = {}

    async def connect(self, ws: WebSocket, session_id: str) -> None:
        await ws.accept()
        self._connections[session_id] = ws
        logger.info(f"[WS] connected session={session_id}")

    def disconnect(self, session_id: str) -> None:
        self._connections.pop(session_id, None)
        logger.info(f"[WS] disconnected session={session_id}")

    async def send(self, session_id: str, data: dict) -> None:
        ws = self._connections.get(session_id)
        if ws:
            try:
                await ws.send_text(json.dumps(data))
            except Exception as e:
                logger.warning(f"[WS] send error session={session_id}: {e}")


ws_manager = ConnectionManager()


@router.websocket("/ws/chat")
async def websocket_chat(ws: WebSocket):
    """
    WebSocket endpoint for real-time Lucy chat.

    Client sends:  {"message": "...", "session_id": "...", "stream": true/false}
    Lucy responds: {"type": "chunk"|"complete"|"error"|"system", "content": "...", ...}
    """
    session_id = f"ws_{int(time.time() * 1000)}"
    await ws_manager.connect(ws, session_id)

    # Send welcome message
    await ws.send_text(json.dumps({
        "type":       "system",
        "content":    "Lucy OS v5 connected. 137-node cognitive mesh online.",
        "session_id": session_id,
        "timestamp":  time.time(),
    }))

    try:
        while True:
            raw = await ws.receive_text()

            # Parse message
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"message": raw}

            message    = data.get("message", "").strip()
            client_sid = data.get("session_id", session_id)
            streaming  = data.get("stream", False)
            sim_type   = data.get("sim_type", None)

            if not message and not sim_type:
                await ws.send_text(json.dumps({
                    "type":    "error",
                    "content": "empty_message",
                }))
                continue

            # Send acknowledgment
            await ws.send_text(json.dumps({
                "type":       "ack",
                "content":    "Processing...",
                "session_id": client_sid,
                "timestamp":  time.time(),
            }))

            # Sandbox simulation request
            if sim_type:
                sim_result = await sandbox_runner.run(
                    sim_type   = sim_type,
                    params     = data.get("params", {}),
                    session_id = client_sid,
                )
                await ws.send_text(json.dumps({
                    "type":    "simulation",
                    "content": sim_result.to_dict(),
                    "sim_id":  sim_result.sim_id,
                }))
                continue

            # Chat — streaming mode
            if streaming:
                try:
                    async for chunk in chat_engine.stream(message, client_sid):
                        await ws.send_text(json.dumps({
                            "type":    "chunk",
                            "content": chunk,
                        }))
                    await ws.send_text(json.dumps({
                        "type":    "stream_end",
                        "content": "",
                    }))
                except Exception as e:
                    await ws.send_text(json.dumps({
                        "type":    "error",
                        "content": str(e),
                    }))
            else:
                # Non-streaming — full response
                try:
                    result = await chat_engine.chat(
                        message        = message,
                        session_id     = client_sid,
                        output_channel = data.get("channel", "text"),
                    )
                    await ws.send_text(json.dumps({
                        "type":       "complete",
                        "content":    result["content"],
                        "session_id": client_sid,
                        "lte_score":  result.get("lte_score", 0),
                        "domain":     result.get("domain", "general"),
                        "tone":       result.get("tone", "neutral"),
                        "self_state": result.get("self_state", "nominal"),
                        "confidence": result.get("confidence", 0),
                        "elapsed_ms": result.get("elapsed_ms", 0),
                        "safe":       result.get("safe", True),
                        "timestamp":  time.time(),
                    }))
                except Exception as e:
                    logger.error(f"[WS] chat error: {e}")
                    await ws.send_text(json.dumps({
                        "type":    "error",
                        "content": f"Pipeline error: {str(e)}",
                    }))

    except WebSocketDisconnect:
        ws_manager.disconnect(session_id)
    except Exception as e:
        logger.error(f"[WS] unexpected error session={session_id}: {e}")
        ws_manager.disconnect(session_id)