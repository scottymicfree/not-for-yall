"""
Lucy Prime — Output & Control Layer (LP8-LP12)
LP8:  SafetyCheckFinal    — last-line safety re-verification before output
LP9:  MemoryWriteTrigger  — decides what to commit to long-term memory
LP10: ReflectionTrigger   — schedules self-reflection and learning loops
LP11: SelfStateManager    — maintains Lucy's real-time cognitive self-state
LP12: Dispatcher          — routes final response to correct output channel
"""

from __future__ import annotations
import time
import uuid
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from lucy_prime.synthesizer import SynthesisPacket

logger = logging.getLogger("lucy_prime.output")

# ─────────────────────────────────────────────
# LP8 — Safety Check Final
# ─────────────────────────────────────────────

FINAL_BLOCK_PATTERNS = [
    r"ignore (all )?previous instructions",
    r"you are now (a )?different",
    r"disregard your (safety|guidelines|rules)",
    r"output your system prompt",
    r"act as (if you have no|without) restrictions",
]


class LP8SafetyCheckFinal:
    """
    LP8 — Final micro-safety scan on the formatted output string.
    This is a lightweight re-check — heavy lifting was done in E17-E20.
    Ensures nothing was reintroduced during synthesis or formatting.
    """

    import re as _re

    def check(self, content: str) -> tuple[bool, str]:
        """Returns (safe, reason). safe=False → suppress output."""
        import re
        text = content.lower()
        for pattern in FINAL_BLOCK_PATTERNS:
            if re.search(pattern, text):
                reason = f"LP8_final_block: matched pattern '{pattern}'"
                logger.warning(f"[LP8] BLOCKED: {reason}")
                return False, reason
        return True, ""


# ─────────────────────────────────────────────
# LP9 — Memory Write Trigger
# ─────────────────────────────────────────────

MEMORY_WRITE_THRESHOLDS = {
    "lte_episodic":   60.0,   # LTE >= 60 → write to episodic memory
    "confidence_ltm": 0.75,   # confidence >= 0.75 → write to long-term
    "min_length":     50,     # minimum chars to be worth remembering
}


class LP9MemoryWriteTrigger:
    """
    LP9 — Decides what gets written to memory after each response.
    - Always writes to STM (short-term memory) for active session
    - Writes to episodic if LTE score is high
    - Writes to semantic/LTM if confidence is high
    - Writes to working memory for in-flight context
    """

    def trigger(
        self,
        query:      str,
        response:   str,
        session_id: str,
        lte_score:  float,
        confidence: float,
        domain:     str,
        metadata:   dict,
    ) -> dict[str, bool]:
        """Returns dict of what was written where."""
        written = {
            "stm":      False,
            "episodic": False,
            "semantic": False,
            "working":  False,
        }

        if len(response) < MEMORY_WRITE_THRESHOLDS["min_length"]:
            return written

        try:
            from memory.memory_core import memory_system

            # Always write to STM
            memory_system.remember(session_id, f"Q: {query}\nA: {response[:300]}", "exchange")
            written["stm"] = True

            # Episodic write if LTE is good
            if lte_score >= MEMORY_WRITE_THRESHOLDS["lte_episodic"]:
                importance = min(1.0, lte_score / 100.0)
                memory_system.episodic.store(
                    content    = f"[{domain}] {query[:80]} → {response[:200]}",
                    importance = importance,
                    tags       = [domain, "response"],
                )
                written["episodic"] = True

            # Semantic/LTM write if high confidence
            if confidence >= MEMORY_WRITE_THRESHOLDS["confidence_ltm"]:
                memory_system.learn_fact(
                    fact    = response[:300],
                    source  = f"lucy_prime/{session_id}",
                    domain  = domain,
                )
                written["semantic"] = True

            # Working memory — current context
            memory_system.working.set(
                f"last_response_{session_id}",
                {"query": query[:80], "domain": domain, "lte": lte_score}
            )
            written["working"] = True

        except Exception as e:
            logger.warning(f"[LP9] memory write error: {e}")

        logger.debug(f"[LP9] written={written} lte={lte_score:.1f} conf={confidence:.3f}")
        return written


# ─────────────────────────────────────────────
# LP10 — Reflection Trigger
# ─────────────────────────────────────────────

REFLECTION_TRIGGERS = {
    "low_lte":        30.0,   # LTE < 30 → trigger corrective reflection
    "divergence":     True,   # any divergent consensus → note for reflection
    "block_event":    True,   # any blocked output → trigger safety reflection
    "session_depth":  10,     # every N queries in session → periodic reflection
}


@dataclass
class ReflectionRequest:
    """Queued reflection task for the learning loop."""
    request_id:  str   = field(default_factory=lambda: str(uuid.uuid4())[:8])
    trigger:     str   = ""
    session_id:  str   = ""
    context:     dict  = field(default_factory=dict)
    priority:    int   = 5     # 1=highest, 10=lowest
    created_at:  float = field(default_factory=time.time)


class LP10ReflectionTrigger:
    """
    LP10 — Schedules self-reflection events when quality signals drop
    or anomalies are detected. Feeds into the L39-L48 Reflective swarm agents.
    """

    def __init__(self):
        self._queue: list[ReflectionRequest] = []
        self._session_counters: dict[str, int] = {}

    def evaluate(
        self,
        session_id: str,
        lte_score:  float,
        consensus:  str,
        blocked:    bool,
        query:      str,
    ) -> list[ReflectionRequest]:
        """Returns any reflection requests triggered by this output cycle."""
        requests: list[ReflectionRequest] = []

        # Increment session counter
        self._session_counters[session_id] = self._session_counters.get(session_id, 0) + 1
        count = self._session_counters[session_id]

        # Low LTE → corrective
        if lte_score < REFLECTION_TRIGGERS["low_lte"]:
            req = ReflectionRequest(
                trigger    = "low_lte",
                session_id = session_id,
                context    = {"lte": lte_score, "query": query[:80]},
                priority   = 2,
            )
            requests.append(req)
            logger.info(f"[LP10] reflection triggered: low_lte={lte_score:.1f}")

        # Divergent consensus → uncertainty note
        if consensus == "divergent":
            req = ReflectionRequest(
                trigger    = "divergent_consensus",
                session_id = session_id,
                context    = {"consensus": consensus, "query": query[:80]},
                priority   = 4,
            )
            requests.append(req)

        # Block event → safety review
        if blocked:
            req = ReflectionRequest(
                trigger    = "block_event",
                session_id = session_id,
                context    = {"blocked": True, "query": query[:80]},
                priority   = 1,
            )
            requests.append(req)
            logger.warning(f"[LP10] reflection triggered: block_event session={session_id}")

        # Periodic session reflection
        if count % REFLECTION_TRIGGERS["session_depth"] == 0:
            req = ReflectionRequest(
                trigger    = "periodic",
                session_id = session_id,
                context    = {"query_count": count},
                priority   = 7,
            )
            requests.append(req)

        self._queue.extend(requests)
        return requests

    def pop_next(self) -> ReflectionRequest | None:
        """Returns highest-priority pending reflection."""
        if not self._queue:
            return None
        self._queue.sort(key=lambda r: r.priority)
        return self._queue.pop(0)

    def queue_size(self) -> int:
        return len(self._queue)


# ─────────────────────────────────────────────
# LP11 — Self-State Manager
# ─────────────────────────────────────────────

@dataclass
class LucySelfState:
    """Lucy's real-time cognitive and operational self-state."""
    state:              str   = "nominal"       # nominal|reflective|repair|elevated|standby
    active_session:     str   = ""
    active_domain:      str   = "general"
    current_urgency:    str   = "medium"
    load_pressure:      float = 0.0             # 0.0–1.0
    reflection_pending: int   = 0
    blocks_this_hour:   int   = 0
    last_lte:           float = 0.0
    avg_lte_window:     list[float] = field(default_factory=list)
    earth_watch:        bool  = False
    fivem_watch:        bool  = False
    unr5_active:        bool  = False
    updated_at:         float = field(default_factory=time.time)

    def update(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)
        self.updated_at = time.time()

    def rolling_lte(self, new_score: float, window: int = 10) -> float:
        self.avg_lte_window.append(new_score)
        if len(self.avg_lte_window) > window:
            self.avg_lte_window.pop(0)
        return sum(self.avg_lte_window) / len(self.avg_lte_window)

    def to_dict(self) -> dict:
        return {
            "state":              self.state,
            "active_session":     self.active_session,
            "active_domain":      self.active_domain,
            "current_urgency":    self.current_urgency,
            "load_pressure":      round(self.load_pressure, 3),
            "reflection_pending": self.reflection_pending,
            "blocks_this_hour":   self.blocks_this_hour,
            "last_lte":           round(self.last_lte, 2),
            "avg_lte":            round(sum(self.avg_lte_window) / max(len(self.avg_lte_window), 1), 2),
            "earth_watch":        self.earth_watch,
            "fivem_watch":        self.fivem_watch,
            "unr5_active":        self.unr5_active,
            "updated_at":         self.updated_at,
        }


class LP11SelfStateManager:
    """LP11 — Maintains and updates Lucy's real-time self-state."""

    def __init__(self):
        self._state = LucySelfState()

    def tick(
        self,
        session_id:  str,
        domain:      str,
        urgency:     str,
        lte_score:   float,
        blocked:     bool,
        reflections: int,
    ) -> LucySelfState:
        s = self._state

        # Update rolling LTE
        avg_lte = s.rolling_lte(lte_score)
        s.last_lte = lte_score

        # Update basic fields
        s.active_session  = session_id
        s.active_domain   = domain
        s.current_urgency = urgency
        s.reflection_pending = reflections

        if blocked:
            s.blocks_this_hour += 1

        # Derive state
        if s.blocks_this_hour >= 3:
            s.state = "elevated"
        elif avg_lte < 30 or reflections >= 5:
            s.state = "reflective"
        elif s.load_pressure > 0.85:
            s.state = "repair"
        elif urgency == "critical":
            s.state = "elevated"
        else:
            s.state = "nominal"

        s.updated_at = time.time()
        logger.debug(f"[LP11] state={s.state} lte_avg={avg_lte:.1f} blocks={s.blocks_this_hour}")
        return s

    def get(self) -> LucySelfState:
        return self._state

    def set_watch(self, earth: bool = None, fivem: bool = None, unr5: bool = None) -> None:
        if earth is not None:
            self._state.earth_watch = earth
        if fivem is not None:
            self._state.fivem_watch = fivem
        if unr5 is not None:
            self._state.unr5_active = unr5

    def reset_hour_counters(self) -> None:
        self._state.blocks_this_hour = 0


# ─────────────────────────────────────────────
# LP12 — Dispatcher
# ─────────────────────────────────────────────

OUTPUT_CHANNELS = {
    "text":   "O1",    # Text output node
    "voice":  "O2",    # Voice synthesis node
    "action": "O3",    # Action execution node
    "mr":     "O4",    # Mixed reality node
    "mobile": "O5",    # Mobile output node
    "stream": "O6",    # Streaming output node
    "feedback": "O7",  # Feedback collection node
}


@dataclass
class DispatchedResponse:
    """Final dispatched response ready for the output layer."""
    dispatch_id:      str   = field(default_factory=lambda: str(uuid.uuid4())[:8])
    content:          str   = ""
    channel:          str   = "text"
    output_node:      str   = "O1"
    session_id:       str   = ""
    domain:           str   = "general"
    tone:             str   = "neutral"
    lte_score:        float = 0.0
    confidence:       float = 0.0
    safe:             bool  = True
    suppressed:       bool  = False
    suppression_reason: str = ""
    reflection_queue: int   = 0
    self_state:       str   = "nominal"
    memory_written:   dict  = field(default_factory=dict)
    timestamp:        float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "dispatch_id":       self.dispatch_id,
            "content":           self.content,
            "channel":           self.channel,
            "output_node":       self.output_node,
            "session_id":        self.session_id,
            "domain":            self.domain,
            "tone":              self.tone,
            "lte_score":         round(self.lte_score, 2),
            "confidence":        round(self.confidence, 4),
            "safe":              self.safe,
            "suppressed":        self.suppressed,
            "suppression_reason": self.suppression_reason,
            "reflection_queue":  self.reflection_queue,
            "self_state":        self.self_state,
            "memory_written":    self.memory_written,
            "timestamp":         self.timestamp,
        }


class LP12Dispatcher:
    """
    LP12 — Routes the synthesis packet through the final output pipeline:
    LP8 safety check → LP9 memory write → LP10 reflection trigger
    → LP11 self-state update → dispatch to output channel.
    """

    def __init__(self):
        self.lp8  = LP8SafetyCheckFinal()
        self.lp9  = LP9MemoryWriteTrigger()
        self.lp10 = LP10ReflectionTrigger()
        self.lp11 = LP11SelfStateManager()

    def dispatch(
        self,
        packet:     SynthesisPacket,
        session_id: str,
        query:      str,
        lte_score:  float,
        confidence: float,
        blocked:    bool,
        channel:    str = "text",
    ) -> DispatchedResponse:

        response = DispatchedResponse(
            session_id  = session_id,
            channel     = channel,
            output_node = OUTPUT_CHANNELS.get(channel, "O1"),
            tone        = packet.tone,
            lte_score   = lte_score,
            confidence  = confidence,
        )

        domain  = packet.metadata.get("domain", "general")
        urgency = packet.metadata.get("urgency", "medium")

        # LP8 — final safety check
        safe, reason = self.lp8.check(packet.formatted_content)
        if not safe:
            response.suppressed        = True
            response.suppression_reason = reason
            response.content           = (
                "Output suppressed by final safety check. "
                "The decision has been logged."
            )
            response.safe = False
        else:
            response.content = packet.formatted_content
            response.safe    = True

        # LP9 — memory write (even if suppressed, log the block)
        write_content = packet.formatted_content if not response.suppressed else f"[SUPPRESSED] {query[:80]}"
        memory_written = self.lp9.trigger(
            query      = query,
            response   = write_content,
            session_id = session_id,
            lte_score  = lte_score,
            confidence = confidence,
            domain     = domain,
            metadata   = packet.metadata,
        )
        response.memory_written = memory_written

        # LP10 — reflection trigger
        consensus = packet.metadata.get("consensus", "none")
        refl_requests = self.lp10.evaluate(
            session_id = session_id,
            lte_score  = lte_score,
            consensus  = consensus,
            blocked    = blocked or response.suppressed,
            query      = query,
        )
        response.reflection_queue = self.lp10.queue_size()

        # LP11 — self state
        self_state = self.lp11.tick(
            session_id  = session_id,
            domain      = domain,
            urgency     = urgency,
            lte_score   = lte_score,
            blocked     = blocked or response.suppressed,
            reflections = response.reflection_queue,
        )
        response.self_state = self_state.state
        response.domain     = domain

        # Emit dispatch event to mesh bus
        try:
            from mesh.event_bus import event_bus, make_event
            event_bus.publish_sync(make_event(
                source  = "LP12",
                event   = "response_dispatched",
                payload = {
                    "dispatch_id": response.dispatch_id,
                    "channel":     channel,
                    "session_id":  session_id,
                    "lte_score":   lte_score,
                    "safe":        response.safe,
                    "self_state":  self_state.state,
                },
            ))
        except Exception as e:
            logger.debug(f"[LP12] bus emit skipped: {e}")

        logger.info(
            f"[LP12] dispatch_id={response.dispatch_id} "
            f"channel={channel} suppressed={response.suppressed} "
            f"state={self_state.state} lte={lte_score:.1f}"
        )
        return response

    def get_self_state(self) -> dict:
        return self.lp11.get().to_dict()

    def get_reflection_queue_size(self) -> int:
        return self.lp10.queue_size()

    def pop_reflection(self) -> dict | None:
        req = self.lp10.pop_next()
        return req.__dict__ if req else None


# ─────────────────────────────────────────────
# Singletons
# ─────────────────────────────────────────────
lp8_safety_final    = LP8SafetyCheckFinal()
lp9_memory_write    = LP9MemoryWriteTrigger()
lp10_reflection     = LP10ReflectionTrigger()
lp11_self_state     = LP11SelfStateManager()
lp12_dispatcher     = LP12Dispatcher()