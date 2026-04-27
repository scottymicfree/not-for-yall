"""
N5 — DAG Builder
Builds a Directed Acyclic Graph of node execution per request.
Each request gets its own DAG based on domain, urgency, context.

DAG Flow:
Input → Perception (P1-P12) → Memory RAG (M9) → Swarm (L1-L48 parallel)
      → Emma Evaluate (E7-E12) → Emma Merge (E13-E16) → Safety (S1-S4)
      → Lucy Prime (LP1-LP12) → Output (O1-O7)

Emma Router (E1-E6) decides which swarm agents activate.
"""

import uuid
import time
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional, Any
from enum import Enum


class ExecutionPhase(str, Enum):
    PERCEPTION   = "perception"
    MEMORY       = "memory"
    ROUTING      = "routing"
    SWARM        = "swarm"
    EVALUATION   = "evaluation"
    MERGE        = "merge"
    SAFETY       = "safety"
    LUCY_PRIME   = "lucy_prime"
    OUTPUT       = "output"


@dataclass
class DAGNode:
    node_id: str
    phase: ExecutionPhase
    depends_on: List[str] = field(default_factory=list)
    parallel_group: Optional[str] = None   # nodes in same group run in parallel
    weight: float = 1.0                    # attention weight
    required: bool = True                  # if False, skip on failure
    timeout_ms: int = 5000


@dataclass
class ExecutionDAG:
    dag_id: str
    session_id: str
    domain: str
    urgency: float
    nodes: List[DAGNode]
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    metadata: dict = field(default_factory=dict)

    def get_phase(self, phase: ExecutionPhase) -> List[DAGNode]:
        return [n for n in self.nodes if n.phase == phase]

    def get_parallel_groups(self, phase: ExecutionPhase) -> Dict[str, List[DAGNode]]:
        groups: Dict[str, List[DAGNode]] = {}
        for node in self.get_phase(phase):
            g = node.parallel_group or node.node_id
            groups.setdefault(g, []).append(node)
        return groups

    def to_dict(self) -> dict:
        return {
            "dagId": self.dag_id,
            "sessionId": self.session_id,
            "domain": self.domain,
            "urgency": self.urgency,
            "nodeCount": len(self.nodes),
            "phases": list({n.phase.value for n in self.nodes}),
            "createdAt": self.created_at,
            "metadata": self.metadata,
        }


# ─── Domain → Agent Activation Map ───────────────────────────────────────────

DOMAIN_AGENT_MAP = {
    "code":        {"analytical": [1,2,3,4,5,6,7,8], "creative": [19,20,21], "strategic": [29,30]},
    "earth":       {"analytical": [4,5,10,15],        "creative": [17,18],   "strategic": [31,32,33]},
    "game":        {"analytical": [3,5,8],             "creative": [17,18,19,20,21,22], "strategic": [29,30,34]},
    "science":     {"analytical": [1,2,4,5,6,12,13,14,15], "creative": [23,24], "strategic": [31]},
    "planning":    {"analytical": [3,4,9,11],          "creative": [17,25],   "strategic": [29,30,31,32,33,34,35,36,37,38]},
    "creative":    {"analytical": [1,8],               "creative": list(range(17,29)), "strategic": [29]},
    "fivem":       {"analytical": [3,5,8,11],          "creative": [17,18,20,21], "strategic": [29,30,34]},
    "analysis":    {"analytical": list(range(1,17)),   "creative": [23,24,25], "strategic": [31,32]},
    "security":    {"analytical": [1,6,12,15,16],      "creative": [],        "strategic": [33,37]},
    "reflection":  {"analytical": [16],                "creative": [],        "strategic": [],       "reflective": list(range(39,49))},
    "general":     {"analytical": [1,2,3,4,5],         "creative": [17,18,19], "strategic": [29,30]},
}

REFLECTIVE_ALWAYS = [39, 40, 41, 42]  # Always-on reflective agents


def _select_swarm_agents(domain: str, urgency: float, context: dict) -> List[str]:
    """
    Select which Little Lucy agents to activate based on domain and urgency.
    Higher urgency = fewer, faster agents. Lower urgency = full swarm.
    """
    mapping = DOMAIN_AGENT_MAP.get(domain, DOMAIN_AGENT_MAP["general"])
    selected = []

    # Scale selection by urgency
    scale = 0.5 if urgency > 0.7 else (0.75 if urgency > 0.4 else 1.0)

    for category, indices in mapping.items():
        n = max(1, int(len(indices) * scale))
        selected.extend([f"L{i}" for i in indices[:n]])

    # Always add reflective agents
    for i in REFLECTIVE_ALWAYS:
        agent = f"L{i}"
        if agent not in selected:
            selected.append(agent)

    return list(set(selected))


class DAGBuilder:
    """N5 — Builds execution DAG for each request."""

    def build(self, session_id: str, domain: str, urgency: float = 0.3,
              context: dict = None, custom_agents: List[str] = None) -> ExecutionDAG:
        context = context or {}
        dag_id  = f"dag_{session_id[:8]}_{int(time.time()*1000)}"
        nodes   = []

        # ── Phase 1: Perception ──────────────────────────────────────────
        # P1-P12 run in sequence (each enriches the context object)
        perception_sequence = [
            ("P11", 1.0, []),           # filter first
            ("P12", 1.0, ["P11"]),      # validate
            ("P1",  1.0, ["P12"]),      # parse
            ("P10", 0.8, ["P1"]),       # normalize
            ("P3",  1.0, ["P10"]),      # intent
            ("P4",  1.0, ["P10"]),      # entities
            ("P9",  1.0, ["P3","P4"]), # domain classify
            ("P7",  0.7, ["P3"]),       # emotion
            ("P8",  0.9, ["P3"]),       # urgency
            ("P6",  1.0, ["P3"]),       # session
            ("P5",  1.0, ["P3","P4","P6","P7","P8","P9"]),  # context build
        ]
        for nid, weight, deps in perception_sequence:
            nodes.append(DAGNode(node_id=nid, phase=ExecutionPhase.PERCEPTION,
                                 depends_on=deps, weight=weight))

        # ── Phase 2: Memory (RAG) ────────────────────────────────────────
        nodes.append(DAGNode("M9",  ExecutionPhase.MEMORY, ["P5"], weight=1.0))   # retrieve
        nodes.append(DAGNode("M10", ExecutionPhase.MEMORY, ["M9"],  weight=0.8))  # expand
        nodes.append(DAGNode("M11", ExecutionPhase.MEMORY, ["M10"], weight=0.7))  # score
        nodes.append(DAGNode("M2",  ExecutionPhase.MEMORY, ["M9"],  weight=1.0))  # working mem
        nodes.append(DAGNode("M1",  ExecutionPhase.MEMORY, ["P5"],  weight=1.0))  # STM update

        # ── Phase 3: Emma Routing ────────────────────────────────────────
        for i in range(1, 7):
            deps = ["P5", "M9", "M10"] if i == 1 else [f"E{i-1}"]
            nodes.append(DAGNode(f"E{i}", ExecutionPhase.ROUTING, deps, weight=1.0))

        # ── Phase 4: Swarm (parallel) ────────────────────────────────────
        agents = custom_agents or _select_swarm_agents(domain, urgency, context)
        for agent_id in agents:
            nodes.append(DAGNode(
                node_id=agent_id,
                phase=ExecutionPhase.SWARM,
                depends_on=["E6", "M10", "M2"],  # need routing + memory
                parallel_group="swarm_parallel",
                weight=1.0,
                timeout_ms=8000,
            ))

        # ── Phase 5: Emma Evaluation ─────────────────────────────────────
        swarm_done = agents
        for i in range(7, 13):
            nodes.append(DAGNode(
                f"E{i}", ExecutionPhase.EVALUATION,
                depends_on=swarm_done,
                parallel_group="emma_eval_parallel",
                weight=1.0,
            ))

        # ── Phase 6: Emma Merge ──────────────────────────────────────────
        eval_done = [f"E{i}" for i in range(7, 13)]
        nodes.append(DAGNode("E13", ExecutionPhase.MERGE, eval_done, weight=1.0))
        nodes.append(DAGNode("E14", ExecutionPhase.MERGE, eval_done, weight=1.0))
        nodes.append(DAGNode("E15", ExecutionPhase.MERGE, ["E13","E14"], weight=1.0))
        nodes.append(DAGNode("E16", ExecutionPhase.MERGE, ["E15"], weight=1.0))

        # Emma Audit
        for i in range(21, 25):
            nodes.append(DAGNode(f"E{i}", ExecutionPhase.MERGE, ["E16"],
                                 required=False, weight=0.5))

        # Emma Safety
        for i in range(17, 21):
            nodes.append(DAGNode(f"E{i}", ExecutionPhase.SAFETY, ["E16"], weight=1.0,
                                 parallel_group="emma_safety_parallel"))

        # ── Phase 7: Global Safety ───────────────────────────────────────
        emma_safety_done = [f"E{i}" for i in range(17, 21)]
        for i in range(1, 5):
            nodes.append(DAGNode(f"S{i}", ExecutionPhase.SAFETY,
                                 emma_safety_done,
                                 parallel_group="global_safety_parallel",
                                 weight=1.0))

        # ── Phase 8: Lucy Prime ──────────────────────────────────────────
        safety_done = [f"S{i}" for i in range(1, 5)]
        nodes.append(DAGNode("LP1",  ExecutionPhase.LUCY_PRIME, safety_done, weight=1.0))
        nodes.append(DAGNode("LP11", ExecutionPhase.LUCY_PRIME, ["LP1"],     weight=1.0))
        nodes.append(DAGNode("LP2",  ExecutionPhase.LUCY_PRIME, ["LP1"],     weight=0.8))
        nodes.append(DAGNode("LP3",  ExecutionPhase.LUCY_PRIME, ["LP1"],     weight=0.8))
        nodes.append(DAGNode("LP4",  ExecutionPhase.LUCY_PRIME, ["LP2","LP3","LP11"], weight=1.0))
        nodes.append(DAGNode("LP5",  ExecutionPhase.LUCY_PRIME, ["LP4"],     weight=1.0))
        nodes.append(DAGNode("LP6",  ExecutionPhase.LUCY_PRIME, ["LP5"],     weight=1.0))
        nodes.append(DAGNode("LP7",  ExecutionPhase.LUCY_PRIME, ["LP6"],     weight=1.0))
        nodes.append(DAGNode("LP8",  ExecutionPhase.LUCY_PRIME, ["LP7"],     weight=1.0))
        nodes.append(DAGNode("LP9",  ExecutionPhase.LUCY_PRIME, ["LP8"],     weight=0.7, required=False))
        nodes.append(DAGNode("LP10", ExecutionPhase.LUCY_PRIME, ["LP8"],     weight=0.6, required=False))
        nodes.append(DAGNode("LP12", ExecutionPhase.LUCY_PRIME, ["LP8"],     weight=1.0))

        # Safety logging
        nodes.append(DAGNode("S5", ExecutionPhase.LUCY_PRIME, ["LP8"], weight=0.5, required=False))
        nodes.append(DAGNode("S6", ExecutionPhase.LUCY_PRIME, ["LP8"], weight=0.5, required=False))

        # ── Phase 9: Output ──────────────────────────────────────────────
        nodes.append(DAGNode("O1", ExecutionPhase.OUTPUT, ["LP12"], weight=1.0))
        nodes.append(DAGNode("O6", ExecutionPhase.OUTPUT, ["LP5"],  weight=1.0))  # streaming starts early
        nodes.append(DAGNode("O7", ExecutionPhase.OUTPUT, ["O1"],   weight=0.5, required=False))

        return ExecutionDAG(
            dag_id=dag_id,
            session_id=session_id,
            domain=domain,
            urgency=urgency,
            nodes=nodes,
            metadata={
                "swarmAgents": agents,
                "agentCount": len(agents),
                "totalNodes": len(nodes),
            }
        )


# Singleton
dag_builder = DAGBuilder()