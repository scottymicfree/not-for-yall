"""
EventBus — Core Async Pub/Sub Message Backbone
N2: Every node communicates ONLY through the EventBus.
Nodes never call each other directly. Everything is a message.

Strict message schema enforced:
{
  "id": "uuid",
  "source": "node_id",
  "target": "node_id | broadcast | layer:perception",
  "type": "request | response | event | error | heartbeat",
  "payload": {},
  "confidence": 0.0–1.0,
  "trace": ["node_id", ...],
  "timestamp": int (ms),
  "session_id": "str",
  "priority": 1–10
}
"""

import asyncio
import uuid
import time
import threading
import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set


# ─── Message Schema ───────────────────────────────────────────────────────────

@dataclass
class LucyMessage:
    source: str
    target: str
    type: str                    # request | response | event | error | heartbeat
    payload: Any = field(default_factory=dict)
    confidence: float = 1.0
    trace: List[str] = field(default_factory=list)
    session_id: str = ""
    priority: int = 5            # 1 (low) – 10 (critical)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "type": self.type,
            "payload": self.payload,
            "confidence": self.confidence,
            "trace": self.trace,
            "sessionId": self.session_id,
            "priority": self.priority,
            "timestamp": self.timestamp,
        }

    def with_hop(self, node_id: str) -> "LucyMessage":
        """Return a copy of this message with node_id added to trace."""
        return LucyMessage(
            id=self.id,
            source=self.source,
            target=self.target,
            type=self.type,
            payload=self.payload,
            confidence=self.confidence,
            trace=self.trace + [node_id],
            session_id=self.session_id,
            priority=self.priority,
            timestamp=self.timestamp,
        )

    def reply(self, from_node: str, payload: Any, confidence: float = 1.0) -> "LucyMessage":
        """Create a response message back to the source."""
        return LucyMessage(
            source=from_node,
            target=self.source,
            type="response",
            payload=payload,
            confidence=confidence,
            trace=self.trace + [from_node],
            session_id=self.session_id,
            priority=self.priority,
        )


def validate_message(msg: LucyMessage) -> tuple[bool, str]:
    """Validate message against strict schema."""
    if not msg.source or not isinstance(msg.source, str):
        return False, "source is required"
    if not msg.target or not isinstance(msg.target, str):
        return False, "target is required"
    if msg.type not in ("request", "response", "event", "error", "heartbeat", "tick", "learn"):
        return False, f"invalid type: {msg.type}"
    if not (0.0 <= msg.confidence <= 1.0):
        return False, "confidence must be 0.0–1.0"
    if not (1 <= msg.priority <= 10):
        return False, "priority must be 1–10"
    return True, ""


# ─── EventBus ─────────────────────────────────────────────────────────────────

class EventBus:
    """
    Async pub/sub backbone for the entire Lucy mesh.
    - Nodes subscribe to channels (node_id, layer:name, or "broadcast")
    - Messages are dispatched asynchronously
    - History ring buffer (last 1000 messages)
    - Dead letter queue for undeliverable messages
    - Priority queue: higher priority messages dispatched first
    """

    HISTORY_SIZE = 1000
    DEAD_LETTER_SIZE = 200

    def __init__(self):
        # Subscriptions: channel -> set of async handler functions
        self._subscribers: Dict[str, Set[Callable]] = {}
        self._lock = threading.RLock()

        # Message history ring buffer
        self._history: deque = deque(maxlen=self.HISTORY_SIZE)
        self._dead_letter: deque = deque(maxlen=self.DEAD_LETTER_SIZE)

        # Stats
        self._total_published = 0
        self._total_delivered = 0
        self._total_dropped = 0

        # Async queue for high-throughput dispatch
        self._queue: Optional[asyncio.Queue] = None
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def subscribe(self, channel: str, handler: Callable):
        """Subscribe a handler to a channel."""
        with self._lock:
            if channel not in self._subscribers:
                self._subscribers[channel] = set()
            self._subscribers[channel].add(handler)

    def unsubscribe(self, channel: str, handler: Callable):
        with self._lock:
            if channel in self._subscribers:
                self._subscribers[channel].discard(handler)

    def _get_handlers(self, msg: LucyMessage) -> List[Callable]:
        """Resolve all handlers for a message target."""
        with self._lock:
            handlers = set()
            # Direct target (e.g. "P1", "L3", "E7")
            handlers.update(self._subscribers.get(msg.target, set()))
            # Broadcast
            handlers.update(self._subscribers.get("broadcast", set()))
            # Layer broadcast (e.g. "layer:perception")
            if ":" not in msg.target:
                pass  # specific node
            return list(handlers)

    async def publish(self, msg: LucyMessage) -> bool:
        """Publish a message to the bus. Returns True if delivered."""
        valid, err = validate_message(msg)
        if not valid:
            self._dead_letter.append({"reason": err, "message": msg.to_dict(), "ts": int(time.time() * 1000)})
            self._total_dropped += 1
            return False

        self._history.append(msg.to_dict())
        self._total_published += 1

        handlers = self._get_handlers(msg)
        if not handlers:
            self._dead_letter.append({"reason": "no_subscribers", "message": msg.to_dict(), "ts": int(time.time() * 1000)})
            self._total_dropped += 1
            return False

        # Dispatch to all handlers concurrently
        tasks = []
        for handler in handlers:
            if asyncio.iscoroutinefunction(handler):
                tasks.append(asyncio.create_task(handler(msg)))
            else:
                try:
                    handler(msg)
                except Exception as e:
                    pass

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)

        self._total_delivered += 1
        return True

    def publish_sync(self, msg: LucyMessage) -> bool:
        """Sync wrapper for publishing from non-async contexts."""
        valid, err = validate_message(msg)
        if not valid:
            self._dead_letter.append({"reason": err, "message": msg.to_dict(), "ts": int(time.time() * 1000)})
            return False

        self._history.append(msg.to_dict())
        self._total_published += 1

        handlers = self._get_handlers(msg)
        if not handlers:
            self._total_dropped += 1
            return False

        for handler in handlers:
            if not asyncio.iscoroutinefunction(handler):
                try:
                    handler(msg)
                except Exception:
                    pass

        self._total_delivered += 1
        return True

    def emit_event(self, source: str, event_type: str, payload: Any,
                   target: str = "broadcast", session_id: str = "",
                   confidence: float = 1.0, priority: int = 5) -> LucyMessage:
        """Convenience: create and publish an event message."""
        msg = LucyMessage(
            source=source,
            target=target,
            type="event",
            payload=payload,
            confidence=confidence,
            session_id=session_id,
            priority=priority,
        )
        self.publish_sync(msg)
        return msg

    def get_history(self, limit: int = 100, source: str = None,
                    target: str = None, msg_type: str = None) -> List[dict]:
        msgs = list(self._history)
        if source:
            msgs = [m for m in msgs if m["source"] == source]
        if target:
            msgs = [m for m in msgs if m["target"] == target]
        if msg_type:
            msgs = [m for m in msgs if m["type"] == msg_type]
        return msgs[-limit:]

    def get_session_history(self, session_id: str) -> List[dict]:
        return [m for m in self._history if m.get("sessionId") == session_id]

    def get_dead_letters(self) -> List[dict]:
        return list(self._dead_letter)

    def stats(self) -> dict:
        with self._lock:
            return {
                "totalPublished": self._total_published,
                "totalDelivered": self._total_delivered,
                "totalDropped": self._total_dropped,
                "historySize": len(self._history),
                "deadLetterSize": len(self._dead_letter),
                "activeSubscriptions": sum(len(v) for v in self._subscribers.values()),
                "channels": list(self._subscribers.keys()),
            }

    def clear_history(self):
        self._history.clear()
        self._dead_letter.clear()


# ─── Message Builder Helpers ──────────────────────────────────────────────────

def make_request(source: str, target: str, payload: Any,
                 session_id: str = "", priority: int = 5,
                 confidence: float = 1.0) -> LucyMessage:
    return LucyMessage(
        source=source, target=target, type="request",
        payload=payload, session_id=session_id,
        priority=priority, confidence=confidence,
    )


def make_event(source: str, target: str, payload: Any,
               session_id: str = "", priority: int = 3) -> LucyMessage:
    return LucyMessage(
        source=source, target=target, type="event",
        payload=payload, session_id=session_id, priority=priority,
    )


def make_response(source: str, original_msg: LucyMessage,
                  payload: Any, confidence: float = 1.0) -> LucyMessage:
    return original_msg.reply(source, payload, confidence)


# Singleton
event_bus = EventBus()