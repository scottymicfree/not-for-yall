"""
AME Event Bus — Autonomous Mesh Engine
Strict async pub/sub — nodes NEVER call each other directly.
All inter-node communication flows through this bus.

Features:
  - Async publish / subscribe
  - Wildcard topic matching (e.g. "swarm.*")
  - Priority queue dispatch (critical > high > normal > low)
  - Dead-letter queue for undelivered events
  - Event history ring buffer (last 1000)
  - Per-topic subscriber counts and throughput stats
  - Circuit breaker per subscriber (auto-disable on repeated failures)
"""

from __future__ import annotations
import asyncio
import time
import uuid
import fnmatch
import threading
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, Deque
from collections import deque, defaultdict
from enum import IntEnum

# ── Priority ───────────────────────────────────────────────────────────────────

class Priority(IntEnum):
    LOW      = 0
    NORMAL   = 1
    HIGH     = 2
    CRITICAL = 3

# ── Event ──────────────────────────────────────────────────────────────────────

@dataclass
class BusEvent:
    topic:      str
    payload:    Any
    priority:   Priority  = Priority.NORMAL
    source:     str        = "unknown"
    event_id:   str        = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp:  float      = field(default_factory=time.time)
    ttl:        float      = 30.0    # seconds before event expires
    meta:       Dict[str, Any] = field(default_factory=dict)

    def expired(self) -> bool:
        return (time.time() - self.timestamp) > self.ttl

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["priority"] = self.priority.name
        return d

# ── Subscription ───────────────────────────────────────────────────────────────

@dataclass
class Subscription:
    sub_id:      str
    topic:       str          # supports wildcards: "swarm.*", "*"
    callback:    Callable
    is_async:    bool
    source_filter: Optional[str] = None   # only receive from this source
    max_failures: int = 5
    _failures:    int = field(default=0, repr=False)
    _disabled:    bool = field(default=False, repr=False)
    _received:    int = field(default=0, repr=False)

    def matches(self, event: BusEvent) -> bool:
        if self._disabled:
            return False
        if self.source_filter and event.source != self.source_filter:
            return False
        return fnmatch.fnmatch(event.topic, self.topic)

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.max_failures:
            self._disabled = True

    def record_success(self) -> None:
        self._failures = max(0, self._failures - 1)
        self._received += 1

    def stats(self) -> Dict[str, Any]:
        return {
            "sub_id":   self.sub_id,
            "topic":    self.topic,
            "received": self._received,
            "failures": self._failures,
            "disabled": self._disabled,
        }

# ── Dead-Letter Queue Entry ────────────────────────────────────────────────────

@dataclass
class DeadLetter:
    event:   BusEvent
    reason:  str
    timestamp: float = field(default_factory=time.time)

# ── AME Event Bus ──────────────────────────────────────────────────────────────

class AMEEventBus:
    """
    Central event bus for the 137-node Lucy OS cognitive mesh.
    All nodes communicate exclusively through this bus.
    """

    _HISTORY_MAX    = 1000
    _DEAD_LETTER_MAX = 200
    _QUEUE_MAXSIZE  = 5000

    def __init__(self) -> None:
        self._subscriptions: Dict[str, Subscription] = {}   # sub_id → Subscription
        self._history:    Deque[BusEvent]   = deque(maxlen=self._HISTORY_MAX)
        self._dead_letter: Deque[DeadLetter] = deque(maxlen=self._DEAD_LETTER_MAX)

        # Priority queues: CRITICAL=3, HIGH=2, NORMAL=1, LOW=0
        self._queues: Dict[Priority, asyncio.Queue] = {}

        # Stats
        self._published:  int = 0
        self._delivered:  int = 0
        self._dropped:    int = 0
        self._topic_counts: Dict[str, int] = defaultdict(int)

        self._lock = threading.Lock()
        self._running = False
        self._dispatch_task: Optional[asyncio.Task] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the async dispatch loop. Must be called inside an async context."""
        if self._running:
            return
        loop = asyncio.get_event_loop()
        self._queues = {
            p: asyncio.Queue(maxsize=self._QUEUE_MAXSIZE)
            for p in Priority
        }
        self._running = True
        self._dispatch_task = loop.create_task(self._dispatch_loop())

    async def stop(self) -> None:
        self._running = False
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass

    # ── Subscribe / Unsubscribe ───────────────────────────────────────────────

    def subscribe(
        self,
        topic:         str,
        callback:      Callable,
        source_filter: Optional[str] = None,
        max_failures:  int = 5,
    ) -> str:
        """
        Subscribe to events matching `topic` (wildcards supported).
        Returns sub_id for later unsubscription.
        """
        sub_id = str(uuid.uuid4())[:8]
        is_async = asyncio.iscoroutinefunction(callback)
        sub = Subscription(
            sub_id=sub_id,
            topic=topic,
            callback=callback,
            is_async=is_async,
            source_filter=source_filter,
            max_failures=max_failures,
        )
        with self._lock:
            self._subscriptions[sub_id] = sub
        return sub_id

    def unsubscribe(self, sub_id: str) -> bool:
        with self._lock:
            if sub_id in self._subscriptions:
                del self._subscriptions[sub_id]
                return True
        return False

    def unsubscribe_all(self, topic: str) -> int:
        with self._lock:
            to_remove = [sid for sid, s in self._subscriptions.items()
                         if s.topic == topic]
            for sid in to_remove:
                del self._subscriptions[sid]
        return len(to_remove)

    # ── Publish ───────────────────────────────────────────────────────────────

    async def publish(
        self,
        topic:    str,
        payload:  Any,
        priority: Priority = Priority.NORMAL,
        source:   str = "unknown",
        ttl:      float = 30.0,
        meta:     Optional[Dict[str, Any]] = None,
    ) -> str:
        """Publish an event. Returns event_id."""
        event = BusEvent(
            topic=topic,
            payload=payload,
            priority=priority,
            source=source,
            ttl=ttl,
            meta=meta or {},
        )
        return await self._enqueue(event)

    def publish_sync(
        self,
        topic:    str,
        payload:  Any,
        priority: Priority = Priority.NORMAL,
        source:   str = "unknown",
    ) -> str:
        """
        Synchronous publish — schedules the event for delivery.
        Safe to call from non-async code.
        """
        event = BusEvent(topic=topic, payload=payload,
                         priority=priority, source=source)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._enqueue(event))
            else:
                loop.run_until_complete(self._enqueue(event))
        except RuntimeError:
            # No event loop available — record as dead letter
            self._dead_letter.append(
                DeadLetter(event=event, reason="no_event_loop")
            )
        return event.event_id

    # ── Internal Enqueue ──────────────────────────────────────────────────────

    async def _enqueue(self, event: BusEvent) -> str:
        with self._lock:
            self._published += 1
            self._topic_counts[event.topic] += 1
            self._history.append(event)

        if not self._running or event.topic not in ("*",) and not self._queues:
            # Bus not started — deliver synchronously
            await self._deliver(event)
            return event.event_id

        q = self._queues.get(event.priority, self._queues[Priority.NORMAL])
        try:
            q.put_nowait((-event.priority.value, time.time(), event))
        except asyncio.QueueFull:
            with self._lock:
                self._dropped += 1
            self._dead_letter.append(
                DeadLetter(event=event, reason="queue_full")
            )
        return event.event_id

    # ── Dispatch Loop ─────────────────────────────────────────────────────────

    async def _dispatch_loop(self) -> None:
        """Continuous dispatch loop — pulls from highest-priority queue first."""
        while self._running:
            delivered = False
            # Poll CRITICAL → HIGH → NORMAL → LOW
            for priority in reversed(list(Priority)):
                q = self._queues[priority]
                if not q.empty():
                    try:
                        _, _, event = q.get_nowait()
                        if not event.expired():
                            await self._deliver(event)
                        else:
                            self._dead_letter.append(
                                DeadLetter(event=event, reason="expired")
                            )
                        q.task_done()
                        delivered = True
                        break
                    except asyncio.QueueEmpty:
                        continue
            if not delivered:
                await asyncio.sleep(0.001)

    # ── Deliver ───────────────────────────────────────────────────────────────

    async def _deliver(self, event: BusEvent) -> None:
        with self._lock:
            subs = list(self._subscriptions.values())

        matched = [s for s in subs if s.matches(event)]

        if not matched:
            self._dead_letter.append(
                DeadLetter(event=event, reason="no_subscribers")
            )
            return

        for sub in matched:
            try:
                if sub.is_async:
                    await sub.callback(event)
                else:
                    sub.callback(event)
                sub.record_success()
                with self._lock:
                    self._delivered += 1
            except Exception as e:
                sub.record_failure()
                self._dead_letter.append(
                    DeadLetter(event=event,
                               reason=f"callback_error:{type(e).__name__}")
                )

    # ── Query ─────────────────────────────────────────────────────────────────

    def history(self, topic: Optional[str] = None,
                limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._history)
        if topic:
            items = [e for e in items if fnmatch.fnmatch(e.topic, topic)]
        return [e.to_dict() for e in items[-limit:]]

    def dead_letters(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._dead_letter)[-limit:]
        return [{"event": dl.event.to_dict(), "reason": dl.reason,
                 "timestamp": dl.timestamp} for dl in items]

    def subscriptions(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [s.stats() for s in self._subscriptions.values()]

    def topic_stats(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._topic_counts)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "published":        self._published,
                "delivered":        self._delivered,
                "dropped":          self._dropped,
                "dead_letters":     len(self._dead_letter),
                "subscriptions":    len(self._subscriptions),
                "history_length":   len(self._history),
                "running":          self._running,
            }

    def clear_dead_letters(self) -> int:
        with self._lock:
            n = len(self._dead_letter)
            self._dead_letter.clear()
        return n

    # ── Convenience: wait_for ─────────────────────────────────────────────────

    async def wait_for(
        self,
        topic:   str,
        timeout: float = 5.0,
        filter_fn: Optional[Callable[[BusEvent], bool]] = None,
    ) -> Optional[BusEvent]:
        """
        Await the next event matching `topic` (and optional filter).
        Returns None on timeout.
        """
        future: asyncio.Future = asyncio.get_event_loop().create_future()

        def _cb(event: BusEvent) -> None:
            if not future.done():
                if filter_fn is None or filter_fn(event):
                    future.set_result(event)

        sub_id = self.subscribe(topic, _cb)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self.unsubscribe(sub_id)

    # ── Standard Lucy OS Topics ───────────────────────────────────────────────

    # Topic constants — use these instead of raw strings to avoid typos
    TOPIC_CHAT_INPUT          = "chat.input"
    TOPIC_CHAT_RESPONSE       = "chat.response"
    TOPIC_SWARM_TASK          = "swarm.task"
    TOPIC_SWARM_RESULT        = "swarm.result"
    TOPIC_SWARM_TIMEOUT       = "swarm.timeout"
    TOPIC_EMMA_RESULT         = "emma.result"
    TOPIC_EMMA_BLOCK          = "emma.block"
    TOPIC_LUCY_DISPATCH       = "lucy.dispatch"
    TOPIC_MEMORY_WRITE        = "memory.write"
    TOPIC_MEMORY_READ         = "memory.read"
    TOPIC_EARTH_QUERY         = "earth.query"
    TOPIC_EARTH_RESULT        = "earth.result"
    TOPIC_FIVEM_EVENT         = "fivem.event"
    TOPIC_FIVEM_COMMAND       = "fivem.command"
    TOPIC_BIOYTH0N_EXECUTE    = "bioyth0n.execute"
    TOPIC_BIOYTH0N_RESULT     = "bioyth0n.result"
    TOPIC_SAFETY_BLOCK        = "safety.block"
    TOPIC_SAFETY_OVERRIDE     = "safety.override"
    TOPIC_UPGRADE_PROPOSAL    = "upgrade.proposal"
    TOPIC_UPGRADE_ACCEPTED    = "upgrade.accepted"
    TOPIC_SENTINEL_ALERT      = "sentinel.alert"
    TOPIC_EAGLE_EYE_UPDATE    = "eagle_eye.update"
    TOPIC_LTE_SCORE           = "lte.score"
    TOPIC_TELEMETRY_PUSH      = "telemetry.push"
    TOPIC_SYSTEM_HEALTH       = "system.health"
    TOPIC_REFLECTION_TRIGGER  = "reflection.trigger"
    TOPIC_SELF_STATE_CHANGE   = "self_state.change"

# ── Singleton ──────────────────────────────────────────────────────────────────
event_bus = AMEEventBus()