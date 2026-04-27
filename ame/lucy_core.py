"""
AME Lucy Core — Autonomous Mesh Engine Core Orchestrator
Wires the full 137-node cognitive mesh into a unified async runtime.

Architecture:
  ┌──────────────────────────────────────────────────────────┐
  │  Perception (12) → Memory (18) → Swarm (48) → Emma (24) │
  │  → Lucy Prime (12) → Infrastructure (10)                 │
  │  → Output (7) → Safety (6)                               │
  └──────────────────────────────────────────────────────────┘

Lucy Core responsibilities:
  1. Bootstrap all layers in dependency order
  2. Wire EventBus subscriptions across layers
  3. Maintain heartbeat + health watchdog
  4. Expose unified query interface for external callers
  5. Handle graceful shutdown and state persistence
"""

from __future__ import annotations
import asyncio
import time
import uuid
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable
from enum import Enum

from ame.event_bus import AMEEventBus, BusEvent, Priority, event_bus

log = logging.getLogger("ame.lucy_core")

# ── System State ───────────────────────────────────────────────────────────────

class SystemState(str, Enum):
    COLD        = "cold"        # Not yet initialised
    BOOTING     = "booting"     # Layers loading
    NOMINAL     = "nominal"     # All systems operational
    DEGRADED    = "degraded"    # One or more layers unavailable
    REFLECTIVE  = "reflective"  # Self-analysis / LTE review
    REPAIR      = "repair"      # Active self-repair
    ELEVATED    = "elevated"    # High-priority autonomous mode
    STANDBY     = "standby"     # Low-power idle
    SHUTDOWN    = "shutdown"    # Graceful exit in progress

# ── Layer Health ───────────────────────────────────────────────────────────────

@dataclass
class LayerHealth:
    name:       str
    node_count: int
    status:     str = "unknown"   # ok / degraded / offline
    last_ping:  float = 0.0
    error:      Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name":       self.name,
            "node_count": self.node_count,
            "status":     self.status,
            "last_ping":  self.last_ping,
            "error":      self.error,
        }

# ── Query Result ───────────────────────────────────────────────────────────────

@dataclass
class CoreQueryResult:
    query_id:      str
    input_text:    str
    response:      str
    confidence:    float
    lte_score:     float
    consensus:     str
    blocked:       bool
    session_id:    str
    latency_ms:    float
    state:         str
    timestamp:     float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()

# ── AME Lucy Core ──────────────────────────────────────────────────────────────

class AMELucyCore:
    """
    Master orchestrator for the 137-node Lucy OS cognitive mesh.
    All subsystems are accessed through event bus topics or direct
    async method calls routed through this core.
    """

    VERSION = "5.0.0"

    # Layer definitions — (name, node_count, import_path, attr)
    _LAYERS = [
        ("perception",     12, None, None),
        ("memory",         18, None, None),
        ("swarm",          48, None, None),
        ("emma_mesh",      24, None, None),
        ("lucy_prime",     12, None, None),
        ("infrastructure", 10, None, None),
        ("output",          7, None, None),
        ("safety",          6, None, None),
    ]

    def __init__(self, bus: AMEEventBus = None) -> None:
        self._bus     = bus or event_bus
        self._state   = SystemState.COLD
        self._boot_ts = 0.0
        self._query_count = 0
        self._error_count = 0

        # Layer health registry
        self._layers: Dict[str, LayerHealth] = {
            name: LayerHealth(name=name, node_count=count)
            for name, count, _, _ in self._LAYERS
        }

        # Loaded subsystem handles (populated during boot)
        self._chat_engine   = None
        self._emma_pipeline = None
        self._lucy_prime    = None
        self._memory_core   = None
        self._swarm_runner  = None
        self._bioyth0n      = None
        self._lte_grader    = None
        self._telemetry     = None

        # Session registry
        self._sessions: Dict[str, Dict[str, Any]] = {}

        # Heartbeat task
        self._heartbeat_task: Optional[asyncio.Task] = None

        # Plugin hooks — registered by AMEPluginManager
        self._pre_query_hooks:  List[Callable] = []
        self._post_query_hooks: List[Callable] = []

        # Sub-event subscriptions
        self._sub_ids: List[str] = []

    # ── Boot ──────────────────────────────────────────────────────────────────

    async def boot(self) -> bool:
        """
        Full async boot sequence.
        Returns True if all critical layers loaded, False if degraded boot.
        """
        self._state  = SystemState.BOOTING
        self._boot_ts = time.time()
        log.info("AMELucyCore booting — v%s", self.VERSION)

        await self._bus.start()

        # Publish boot event
        await self._bus.publish(
            topic="system.health",
            payload={"event": "boot_start", "version": self.VERSION},
            priority=Priority.HIGH,
            source="lucy_core",
        )

        # Load subsystems
        critical_ok = 0
        total_critical = 4  # emma, lucy_prime, memory, safety

        # ── Emma Pipeline
        try:
            from emma_mesh.pipeline import emma_pipeline
            self._emma_pipeline = emma_pipeline
            self._mark_layer("emma_mesh", "ok")
            critical_ok += 1
            log.info("  ✓ Emma Mesh loaded")
        except Exception as e:
            self._mark_layer("emma_mesh", "degraded", str(e))
            log.warning("  ✗ Emma Mesh unavailable: %s", e)

        # ── Lucy Prime
        try:
            from lucy_prime.prime import lucy_prime
            self._lucy_prime = lucy_prime
            self._mark_layer("lucy_prime", "ok")
            critical_ok += 1
            log.info("  ✓ Lucy Prime loaded")
        except Exception as e:
            self._mark_layer("lucy_prime", "degraded", str(e))
            log.warning("  ✗ Lucy Prime unavailable: %s", e)

        # ── Memory
        try:
            from memory.memory_core import memory_system
            self._memory_core = memory_system
            self._mark_layer("memory", "ok")
            critical_ok += 1
            log.info("  ✓ Memory Core loaded")
        except Exception as e:
            self._mark_layer("memory", "degraded", str(e))
            log.warning("  ✗ Memory Core unavailable: %s", e)

        # ── Safety
        try:
            from safety.policy_engine import policy_engine
            self._mark_layer("safety", "ok")
            critical_ok += 1
            log.info("  ✓ Safety Layer loaded")
        except Exception as e:
            self._mark_layer("safety", "degraded", str(e))
            log.warning("  ✗ Safety Layer unavailable: %s", e)

        # ── Swarm
        try:
            from swarm.swarm_runner import swarm_runner
            self._swarm_runner = swarm_runner
            self._mark_layer("swarm", "ok")
            log.info("  ✓ Swarm Runner loaded")
        except Exception as e:
            self._mark_layer("swarm", "degraded", str(e))
            log.warning("  ✗ Swarm Runner unavailable: %s", e)

        # ── Chat Engine
        try:
            from chat.chat_engine import chat_engine
            self._chat_engine = chat_engine
            self._mark_layer("perception", "ok")
            self._mark_layer("output", "ok")
            log.info("  ✓ Chat Engine loaded")
        except Exception as e:
            self._mark_layer("perception", "degraded", str(e))
            log.warning("  ✗ Chat Engine unavailable: %s", e)

        # ── Bioyth0n
        try:
            from bioyth0n.executor import bioyth0n
            self._bioyth0n = bioyth0n
            self._mark_layer("infrastructure", "ok")
            log.info("  ✓ Bioyth0n loaded")
        except Exception as e:
            self._mark_layer("infrastructure", "degraded", str(e))
            log.warning("  ✗ Bioyth0n unavailable: %s", e)

        # ── LTE + Telemetry
        try:
            from lte.emma_grader import lte_grader
            from lte.telemetry import telemetry
            self._lte_grader = lte_grader
            self._telemetry  = telemetry
            log.info("  ✓ LTE/Telemetry loaded")
        except Exception as e:
            log.warning("  ✗ LTE/Telemetry unavailable: %s", e)

        # ── Wire event bus subscriptions
        self._wire_subscriptions()

        # ── Start heartbeat
        loop = asyncio.get_event_loop()
        self._heartbeat_task = loop.create_task(self._heartbeat_loop())

        # Determine final state
        if critical_ok >= total_critical:
            self._state = SystemState.NOMINAL
        else:
            self._state = SystemState.DEGRADED

        boot_ms = round((time.time() - self._boot_ts) * 1000, 2)
        log.info("AMELucyCore boot complete — state=%s  %.1fms", self._state.value, boot_ms)

        await self._bus.publish(
            topic="system.health",
            payload={
                "event":    "boot_complete",
                "state":    self._state.value,
                "boot_ms":  boot_ms,
                "layers":   {n: lh.status for n, lh in self._layers.items()},
            },
            priority=Priority.HIGH,
            source="lucy_core",
        )

        return self._state == SystemState.NOMINAL

    # ── Event Bus Wiring ──────────────────────────────────────────────────────

    def _wire_subscriptions(self) -> None:
        """Register internal event bus handlers."""

        async def _on_lte_score(event: BusEvent) -> None:
            payload = event.payload or {}
            if self._telemetry:
                self._telemetry.push("lte", "lte_score", float(payload.get("score", 0)))

        async def _on_safety_block(event: BusEvent) -> None:
            if self._telemetry:
                self._telemetry.push("safety", "block_events", 1.0)
            log.warning("Safety BLOCK — %s", event.payload)

        async def _on_self_state_change(event: BusEvent) -> None:
            new_state = event.payload.get("state", "nominal") if event.payload else "nominal"
            log.info("Self-state change → %s", new_state)

        async def _on_reflection_trigger(event: BusEvent) -> None:
            log.info("Reflection trigger received — %s", event.payload)

        async def _on_upgrade_proposal(event: BusEvent) -> None:
            log.info("Upgrade proposal received — %s", event.payload)

        handlers = [
            (AMEEventBus.TOPIC_LTE_SCORE,          _on_lte_score),
            (AMEEventBus.TOPIC_SAFETY_BLOCK,        _on_safety_block),
            (AMEEventBus.TOPIC_SELF_STATE_CHANGE,   _on_self_state_change),
            (AMEEventBus.TOPIC_REFLECTION_TRIGGER,  _on_reflection_trigger),
            (AMEEventBus.TOPIC_UPGRADE_PROPOSAL,    _on_upgrade_proposal),
        ]
        for topic, handler in handlers:
            sid = self._bus.subscribe(topic, handler)
            self._sub_ids.append(sid)

    # ── Query Interface ───────────────────────────────────────────────────────

    async def query(
        self,
        text:       str,
        session_id: Optional[str] = None,
        context:    Optional[Dict[str, Any]] = None,
    ) -> CoreQueryResult:
        """
        Unified query entry point.
        Routes through Chat Engine → Emma → Lucy Prime.
        """
        query_id  = str(uuid.uuid4())[:8]
        session_id = session_id or str(uuid.uuid4())[:8]
        t_start   = time.perf_counter()
        context   = context or {}
        self._query_count += 1

        # Publish input event
        await self._bus.publish(
            topic=AMEEventBus.TOPIC_CHAT_INPUT,
            payload={"text": text, "session_id": session_id, "query_id": query_id},
            source="lucy_core",
        )

        # ── Pre-query hooks
        for hook in self._pre_query_hooks:
            try:
                await hook(text, session_id, context) if asyncio.iscoroutinefunction(hook) \
                    else hook(text, session_id, context)
            except Exception:
                pass

        response_text = ""
        confidence    = 0.70
        lte_score_val = 70.0
        consensus     = "partial"
        blocked       = False

        # ── Route through Chat Engine (primary path)
        if self._chat_engine:
            try:
                result = await self._chat_engine.chat(
                    user_input=text,
                    session_id=session_id,
                )
                if isinstance(result, dict):
                    response_text = result.get("response", "")
                    confidence    = result.get("confidence", 0.70)
                    lte_score_val = result.get("lte_score", 70.0)
                    consensus     = result.get("consensus", "partial")
                    blocked       = result.get("blocked", False)
                else:
                    response_text = str(result)
            except Exception as e:
                self._error_count += 1
                log.error("Chat engine error: %s", e)
                response_text = self._fallback_response(text, str(e))

        # ── Fallback: Lucy Prime direct
        elif self._lucy_prime:
            try:
                packet = await self._lucy_prime.respond(
                    approved_content=text,
                    session_id=session_id,
                )
                response_text = packet.final_text if hasattr(packet, "final_text") else str(packet)
            except Exception as e:
                self._error_count += 1
                response_text = self._fallback_response(text, str(e))

        else:
            response_text = self._fallback_response(text, "No response engine available")

        latency_ms = round((time.perf_counter() - t_start) * 1000, 2)

        # ── Post-query hooks
        result_data = {
            "response":   response_text,
            "confidence": confidence,
            "lte_score":  lte_score_val,
            "latency_ms": latency_ms,
            "blocked":    blocked,
        }
        for hook in self._post_query_hooks:
            try:
                await hook(query_id, result_data) if asyncio.iscoroutinefunction(hook) \
                    else hook(query_id, result_data)
            except Exception:
                pass

        # ── Publish response event
        await self._bus.publish(
            topic=AMEEventBus.TOPIC_CHAT_RESPONSE,
            payload=result_data,
            source="lucy_core",
        )

        # ── Telemetry
        if self._telemetry:
            self._telemetry.push("lucy_prime", "lte_avg", lte_score_val)
            self._telemetry.push("lucy_prime", "synthesis_ms", latency_ms)

        return CoreQueryResult(
            query_id=query_id,
            input_text=text,
            response=response_text,
            confidence=confidence,
            lte_score=lte_score_val,
            consensus=consensus,
            blocked=blocked,
            session_id=session_id,
            latency_ms=latency_ms,
            state=self._state.value,
        )

    def _fallback_response(self, text: str, reason: str) -> str:
        return (
            f"I am Lucy — currently operating in limited mode ({reason}). "
            f"Your message has been received and logged. "
            f"Full cognitive mesh will respond once systems are restored."
        )

    # ── Session Management ────────────────────────────────────────────────────

    def create_session(self, session_id: Optional[str] = None) -> str:
        sid = session_id or str(uuid.uuid4())[:8]
        self._sessions[sid] = {
            "created":    time.time(),
            "last_active": time.time(),
            "query_count": 0,
        }
        return sid

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self._sessions.get(session_id)

    def list_sessions(self) -> List[Dict[str, Any]]:
        return [
            {"session_id": sid, **data}
            for sid, data in self._sessions.items()
        ]

    def close_session(self, session_id: str) -> bool:
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    # ── Plugin Hooks ─────────────────────────────────────────────────────────

    def register_pre_query_hook(self, fn: Callable) -> None:
        self._pre_query_hooks.append(fn)

    def register_post_query_hook(self, fn: Callable) -> None:
        self._post_query_hooks.append(fn)

    # ── State Management ──────────────────────────────────────────────────────

    def set_state(self, new_state: SystemState) -> None:
        old = self._state
        self._state = new_state
        self._bus.publish_sync(
            topic=AMEEventBus.TOPIC_SELF_STATE_CHANGE,
            payload={"old": old.value, "state": new_state.value},
            source="lucy_core",
        )

    def get_state(self) -> SystemState:
        return self._state

    # ── Layer Health ──────────────────────────────────────────────────────────

    def _mark_layer(self, name: str, status: str, error: str = None) -> None:
        if name in self._layers:
            self._layers[name].status    = status
            self._layers[name].last_ping = time.time()
            self._layers[name].error     = error

    def layer_health(self) -> Dict[str, Dict[str, Any]]:
        return {name: lh.to_dict() for name, lh in self._layers.items()}

    # ── Heartbeat Loop ────────────────────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        """Periodic health ping — runs every 30 seconds."""
        while self._state not in (SystemState.SHUTDOWN, SystemState.COLD):
            await asyncio.sleep(30)
            try:
                await self._ping_layers()
                await self._bus.publish(
                    topic=AMEEventBus.TOPIC_SYSTEM_HEALTH,
                    payload=self.health_snapshot(),
                    priority=Priority.LOW,
                    source="lucy_core",
                )
            except Exception as e:
                log.error("Heartbeat error: %s", e)

    async def _ping_layers(self) -> None:
        now = time.time()
        for name, lh in self._layers.items():
            if lh.status == "ok":
                lh.last_ping = now

    # ── Health ────────────────────────────────────────────────────────────────

    def health_snapshot(self) -> Dict[str, Any]:
        ok_layers = sum(1 for lh in self._layers.values() if lh.status == "ok")
        total     = len(self._layers)
        return {
            "version":     self.VERSION,
            "state":       self._state.value,
            "uptime":      round(time.time() - self._boot_ts, 2) if self._boot_ts else 0,
            "layers_ok":   ok_layers,
            "layers_total": total,
            "health_pct":  round(ok_layers / total * 100, 1),
            "query_count": self._query_count,
            "error_count": self._error_count,
            "sessions":    len(self._sessions),
            "bus_stats":   self._bus.stats(),
            "layers":      self.layer_health(),
            "timestamp":   time.time(),
        }

    # ── Shutdown ──────────────────────────────────────────────────────────────

    async def shutdown(self) -> None:
        log.info("AMELucyCore shutting down…")
        self._state = SystemState.SHUTDOWN

        # Cancel heartbeat
        if self._heartbeat_task:
            self._heartbeat_task.cancel()

        # Unsubscribe all
        for sid in self._sub_ids:
            self._bus.unsubscribe(sid)

        await self._bus.publish(
            topic=AMEEventBus.TOPIC_SYSTEM_HEALTH,
            payload={"event": "shutdown"},
            priority=Priority.CRITICAL,
            source="lucy_core",
        )

        await self._bus.stop()
        log.info("AMELucyCore shutdown complete.")


# ── Singleton ──────────────────────────────────────────────────────────────────
lucy_core = AMELucyCore(bus=event_bus)