"""
Emma Supervisory Mesh — Router Layer (E1-E6)
E1: DomainRouter      — routes input to correct swarm domain agents
E2: UrgencyRouter     — adjusts routing priority by urgency level
E3: CapabilityRouter  — filters agents by required capabilities
E4: LoadRouter        — balances load across available swarm nodes
E5: ContextRouter     — injects session/memory context into routing decisions
E6: FallbackRouter    — handles unroutable or edge-case inputs gracefully
"""

from __future__ import annotations
import asyncio
import uuid
import time
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("emma.router")

# ─────────────────────────────────────────────
# Domain → agent_id ranges (matches swarm_runner + node_registry)
# ─────────────────────────────────────────────
DOMAIN_AGENT_POOLS: dict[str, list[str]] = {
    "general":       ["L1","L2","L3","L17","L18","L29","L39","L40"],
    "technical":     ["L4","L5","L6","L7","L8","L17","L29","L30","L39"],
    "creative":      ["L17","L18","L19","L20","L21","L22","L23","L24","L25","L26","L27","L28"],
    "analytical":    ["L1","L2","L3","L4","L5","L6","L7","L8","L9","L10","L11","L12","L13","L14","L15","L16"],
    "strategic":     ["L29","L30","L31","L32","L33","L34","L35","L36","L37","L38"],
    "reflective":    ["L39","L40","L41","L42","L43","L44","L45","L46","L47","L48"],
    "earth":         ["L5","L6","L9","L10","L29","L30","L39","L40"],
    "fivem":         ["L4","L7","L8","L17","L29","L31","L32","L39"],
    "safety":        ["L11","L12","L14","L15","L39","L41","L42","L43","L44","L45"],
}

URGENCY_SCALE: dict[str, float] = {
    "critical": 1.0,
    "high":     0.80,
    "medium":   0.55,
    "low":      0.30,
}

CAPABILITY_MAP: dict[str, list[str]] = {
    "code_analysis":    ["L4","L5","L6","L7","L8"],
    "earth_data":       ["L5","L6","L9","L10"],
    "game_systems":     ["L4","L7","L8","L17","L29"],
    "safety_audit":     ["L11","L12","L14","L39","L41","L43"],
    "simulation":       ["L9","L10","L13","L29","L30","L31"],
    "creative_writing": ["L17","L18","L19","L20","L21","L22"],
    "strategic_plan":   ["L29","L30","L31","L32","L33","L34"],
    "self_reflection":  ["L39","L40","L41","L42","L43","L44"],
    "memory_ops":       ["L3","L13","L14","L40","L46","L47"],
}

MAX_AGENTS_LOW    = 4
MAX_AGENTS_MEDIUM = 8
MAX_AGENTS_HIGH   = 12
MAX_AGENTS_CRIT   = 20


@dataclass
class RoutingDecision:
    """Output of E1-E6 routing pipeline."""
    routing_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    selected_agents: list[str] = field(default_factory=list)
    domain: str = "general"
    urgency: str = "medium"
    required_capabilities: list[str] = field(default_factory=list)
    context_injected: dict[str, Any] = field(default_factory=dict)
    fallback_triggered: bool = False
    fallback_reason: str = ""
    routing_score: float = 0.0
    load_balanced: bool = False
    trace: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "routing_id": self.routing_id,
            "selected_agents": self.selected_agents,
            "domain": self.domain,
            "urgency": self.urgency,
            "required_capabilities": self.required_capabilities,
            "context_injected": self.context_injected,
            "fallback_triggered": self.fallback_triggered,
            "fallback_reason": self.fallback_reason,
            "routing_score": round(self.routing_score, 4),
            "load_balanced": self.load_balanced,
            "trace": self.trace,
            "timestamp": self.timestamp,
        }


class E1DomainRouter:
    """E1 — Maps perception domain → candidate agent pool."""

    def route(self, domain: str) -> list[str]:
        pool = DOMAIN_AGENT_POOLS.get(domain, DOMAIN_AGENT_POOLS["general"])
        logger.debug(f"[E1] domain={domain} → {len(pool)} candidates")
        return list(pool)


class E2UrgencyRouter:
    """E2 — Scales agent count and priority by urgency level."""

    def apply(self, agents: list[str], urgency: str) -> tuple[list[str], float]:
        scale = URGENCY_SCALE.get(urgency, 0.55)
        limits = {
            "critical": MAX_AGENTS_CRIT,
            "high":     MAX_AGENTS_HIGH,
            "medium":   MAX_AGENTS_MEDIUM,
            "low":      MAX_AGENTS_LOW,
        }
        max_n = limits.get(urgency, MAX_AGENTS_MEDIUM)
        selected = agents[:max_n]
        logger.debug(f"[E2] urgency={urgency} scale={scale} agents→{len(selected)}")
        return selected, scale


class E3CapabilityRouter:
    """E3 — Intersects candidate pool with required capabilities."""

    def filter(self, agents: list[str], capabilities: list[str]) -> list[str]:
        if not capabilities:
            return agents
        required_set: set[str] = set()
        for cap in capabilities:
            required_set.update(CAPABILITY_MAP.get(cap, []))
        if not required_set:
            return agents
        filtered = [a for a in agents if a in required_set]
        # Fallback: if intersection is empty keep originals
        result = filtered if filtered else agents
        logger.debug(f"[E3] caps={capabilities} filtered={len(result)}")
        return result


class E4LoadRouter:
    """E4 — Balances agent selection by current mesh load."""

    def balance(self, agents: list[str]) -> tuple[list[str], bool]:
        try:
            from mesh.node_registry import node_registry
            loads = {}
            for aid in agents:
                node = node_registry.get(aid)
                if node:
                    loads[aid] = node.load
                else:
                    loads[aid] = 0.5
            sorted_agents = sorted(agents, key=lambda a: loads.get(a, 0.5))
            logger.debug(f"[E4] load-balanced {len(sorted_agents)} agents")
            return sorted_agents, True
        except Exception as e:
            logger.debug(f"[E4] load balance skipped: {e}")
            return agents, False


class E5ContextRouter:
    """E5 — Injects session memory + context into routing metadata."""

    def inject(
        self,
        session_id: str,
        perception_packet: dict,
        memory_context: dict | None = None,
    ) -> dict[str, Any]:
        ctx: dict[str, Any] = {
            "session_id": session_id,
            "intent": perception_packet.get("intent", "unknown"),
            "emotion": perception_packet.get("emotion", "neutral"),
            "entities": perception_packet.get("entities", {}),
            "sentiment": perception_packet.get("sentiment", 0.0),
        }
        if memory_context:
            ctx["recent_topics"] = memory_context.get("recent_topics", [])
            ctx["persona"] = memory_context.get("persona", {})
        logger.debug(f"[E5] context injected keys={list(ctx.keys())}")
        return ctx


class E6FallbackRouter:
    """E6 — Handles unroutable, empty, or edge-case scenarios."""

    FALLBACK_POOL = ["L1", "L17", "L29", "L39"]  # one of each type

    def handle(
        self,
        agents: list[str],
        domain: str,
        decision: RoutingDecision,
    ) -> RoutingDecision:
        if not agents:
            decision.selected_agents = self.FALLBACK_POOL
            decision.fallback_triggered = True
            decision.fallback_reason = f"empty_pool_domain={domain}"
            logger.warning(f"[E6] fallback triggered: {decision.fallback_reason}")
        elif len(agents) < 2:
            extras = [a for a in self.FALLBACK_POOL if a not in agents]
            agents.extend(extras[:2])
            decision.selected_agents = agents
            decision.fallback_triggered = True
            decision.fallback_reason = "pool_too_small"
        else:
            decision.selected_agents = agents
        return decision


# ─────────────────────────────────────────────
# Composite Router — runs E1→E6 pipeline
# ─────────────────────────────────────────────

class EmmaRouter:
    """
    E1-E6 composite routing pipeline.
    Input: perception packet + session context.
    Output: RoutingDecision with selected agent IDs.
    """

    def __init__(self):
        self.e1 = E1DomainRouter()
        self.e2 = E2UrgencyRouter()
        self.e3 = E3CapabilityRouter()
        self.e4 = E4LoadRouter()
        self.e5 = E5ContextRouter()
        self.e6 = E6FallbackRouter()

    def route(
        self,
        perception_packet: dict,
        session_id: str = "default",
        memory_context: dict | None = None,
        required_capabilities: list[str] | None = None,
    ) -> RoutingDecision:
        decision = RoutingDecision()
        decision.domain   = perception_packet.get("domain", "general")
        decision.urgency  = perception_packet.get("urgency", "medium")
        decision.required_capabilities = required_capabilities or []

        trace = []

        # E1 — domain pool
        candidates = self.e1.route(decision.domain)
        trace.append(f"E1:domain={decision.domain}→{len(candidates)}agents")

        # E2 — urgency scale
        candidates, urgency_weight = self.e2.apply(candidates, decision.urgency)
        trace.append(f"E2:urgency={decision.urgency}→{len(candidates)}agents")

        # E3 — capability filter
        candidates = self.e3.filter(candidates, decision.required_capabilities)
        trace.append(f"E3:caps={decision.required_capabilities}→{len(candidates)}agents")

        # E4 — load balance
        candidates, lb = self.e4.balance(candidates)
        decision.load_balanced = lb
        trace.append(f"E4:load_balanced={lb}")

        # E5 — context inject
        ctx = self.e5.inject(session_id, perception_packet, memory_context)
        decision.context_injected = ctx
        trace.append(f"E5:ctx_keys={list(ctx.keys())}")

        # E6 — fallback guard
        decision = self.e6.handle(candidates, decision.domain, decision)
        trace.append(f"E6:fallback={decision.fallback_triggered} agents={decision.selected_agents}")

        # routing score = urgency_weight * coverage_ratio
        coverage = len(decision.selected_agents) / max(len(candidates), 1)
        decision.routing_score = round(urgency_weight * min(coverage, 1.0), 4)
        decision.trace = trace

        logger.info(
            f"[EmmaRouter] id={decision.routing_id} "
            f"domain={decision.domain} urgency={decision.urgency} "
            f"agents={decision.selected_agents} score={decision.routing_score}"
        )
        return decision

    async def route_async(
        self,
        perception_packet: dict,
        session_id: str = "default",
        memory_context: dict | None = None,
        required_capabilities: list[str] | None = None,
    ) -> RoutingDecision:
        return await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self.route(perception_packet, session_id, memory_context, required_capabilities),
        )


# Singleton
emma_router = EmmaRouter()