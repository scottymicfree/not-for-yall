"""
N1 — Node Registry
All 137 nodes defined, typed, layered.
Each node has: id, name, layer, category, description, status, capabilities.
This is the canonical source of truth for the entire Lucy mesh.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict
import time
import threading


@dataclass
class MeshNode:
    node_id: str
    name: str
    layer: str
    category: str
    description: str
    capabilities: List[str] = field(default_factory=list)
    status: str = "online"          # online | degraded | offline | busy
    load: float = 0.0               # 0.0 - 1.0
    messages_processed: int = 0
    last_active: float = field(default_factory=time.time)
    error_count: int = 0

    def to_dict(self) -> dict:
        return {
            "nodeId": self.node_id,
            "name": self.name,
            "layer": self.layer,
            "category": self.category,
            "description": self.description,
            "capabilities": self.capabilities,
            "status": self.status,
            "load": round(self.load, 3),
            "messagesProcessed": self.messages_processed,
            "lastActive": self.last_active,
            "errorCount": self.error_count,
        }

    def mark_active(self):
        self.last_active = time.time()
        self.messages_processed += 1

    def set_load(self, load: float):
        self.load = max(0.0, min(1.0, load))


# ─── All 137 Nodes ────────────────────────────────────────────────────────────

def _build_all_nodes() -> Dict[str, MeshNode]:
    nodes = {}

    def n(node_id, name, layer, category, description, capabilities=None):
        node = MeshNode(
            node_id=node_id, name=name, layer=layer,
            category=category, description=description,
            capabilities=capabilities or []
        )
        nodes[node_id] = node

    # ── Perception Layer (P1–P12) ──────────────────────────────────────────
    n("P1",  "Text Input Parser",      "perception", "input",    "Parse raw text input into structured form",            ["parse_text", "tokenize", "normalize"])
    n("P2",  "Voice Input Parser",     "perception", "input",    "Transcribe and parse voice input",                     ["transcribe", "parse_audio", "voice_normalize"])
    n("P3",  "Intent Extractor",       "perception", "intent",   "Extract primary intent from structured input",         ["extract_intent", "classify_intent", "confidence_score"])
    n("P4",  "Entity Extractor",       "perception", "entity",   "Extract named entities, refs, objects from input",     ["extract_entities", "link_entities", "resolve_coreference"])
    n("P5",  "Context Builder",        "perception", "context",  "Build rich context object from parsed signals",        ["build_context", "enrich_context", "attach_metadata"])
    n("P6",  "Session Tracker",        "perception", "session",  "Track conversation session state and history",         ["track_session", "get_history", "update_session"])
    n("P7",  "Emotion Detector",       "perception", "affect",   "Detect emotional tone and sentiment",                  ["detect_emotion", "score_sentiment", "detect_frustration"])
    n("P8",  "Urgency Detector",       "perception", "affect",   "Detect urgency and priority level",                    ["detect_urgency", "score_priority", "flag_critical"])
    n("P9",  "Domain Classifier",      "perception", "routing",  "Classify input domain: code/earth/game/science/etc",   ["classify_domain", "multi_label", "confidence_rank"])
    n("P10", "Query Normalizer",       "perception", "transform","Normalize query structure for downstream processing",  ["normalize_query", "expand_abbreviations", "fix_grammar"])
    n("P11", "Noise Filter",           "perception", "quality",  "Remove noise, hallucination hooks, injection attempts",["filter_noise", "detect_injection", "sanitize"])
    n("P12", "Input Validator",        "perception", "quality",  "Validate input completeness and schema compliance",    ["validate_input", "check_schema", "flag_incomplete"])

    # ── Memory Layer (M1–M18) ─────────────────────────────────────────────
    n("M1",  "Short-Term Memory",      "memory", "storage",   "Hold current conversation turn in fast access buffer",   ["store_stm", "get_stm", "clear_stm"])
    n("M2",  "Working Memory",         "memory", "storage",   "Active reasoning scratchpad for current task",           ["store_working", "get_working", "update_working"])
    n("M3",  "Episodic Memory",        "memory", "storage",   "Record and retrieve past interaction episodes",          ["store_episode", "get_episodes", "search_episodes"])
    n("M4",  "Semantic Memory",        "memory", "knowledge", "Long-term factual + conceptual knowledge store",         ["store_fact", "get_fact", "semantic_search"])
    n("M5",  "Persona Memory",         "memory", "identity",  "Lucy's persistent identity, preferences, learned style", ["store_persona", "get_persona", "update_persona"])
    n("M6",  "Vector Store Interface", "memory", "rag",       "Interface to vector embedding store (ChromaDB/FAISS)",   ["embed", "vector_search", "upsert_vector"])
    n("M7",  "Graph Store Interface",  "memory", "rag",       "Interface to knowledge graph store",                     ["graph_query", "add_relation", "traverse_graph"])
    n("M8",  "Memory Indexer",         "memory", "rag",       "Index new memories into vector + graph stores",          ["index_memory", "batch_index", "rebuild_index"])
    n("M9",  "Memory Retriever",       "memory", "rag",       "RAG core: retrieve relevant context for any query",      ["rag_retrieve", "hybrid_search", "rerank"])
    n("M10", "Context Expander",       "memory", "rag",       "Expand retrieved context with related chunks",           ["expand_context", "follow_references", "enrich_chunks"])
    n("M11", "Memory Scorer",          "memory", "quality",   "Score memory relevance and freshness",                   ["score_relevance", "score_freshness", "rank_memories"])
    n("M12", "Memory Deduplicator",    "memory", "quality",   "Remove duplicate or near-duplicate memories",            ["dedup_memories", "similarity_check", "merge_duplicates"])
    n("M13", "Memory Compressor",      "memory", "quality",   "Compress old memories into summaries",                   ["compress_memories", "summarize_episodes", "archive"])
    n("M14", "Memory Sync Node",       "memory", "sync",      "Sync memory across sessions and instances",              ["sync_memory", "resolve_conflicts", "broadcast_update"])
    n("M15", "Memory Validator",       "memory", "quality",   "Validate memory consistency and integrity",              ["validate_memories", "check_contradictions", "flag_stale"])
    n("M16", "Long-Term Writer",       "memory", "storage",   "Write approved memories to persistent long-term store",  ["write_ltm", "batch_write", "checkpoint"])
    n("M17", "Forgetting Engine",      "memory", "lifecycle", "Scheduled decay and removal of low-value memories",      ["decay_memories", "schedule_forget", "prune_old"])
    n("M18", "Memory Audit Node",      "memory", "audit",     "Audit all memory operations for governance compliance",  ["audit_memory_op", "log_access", "generate_report"])

    # ── Little Lucy Swarm — Analytical (L1–L16) ──────────────────────────
    for i in range(1, 17):
        descs = [
            "Formal logic and deductive reasoning",
            "Mathematical computation and proof",
            "Problem decomposition and sub-goal generation",
            "Causal chain analysis",
            "Pattern recognition and statistical inference",
            "Contradiction detection and resolution",
            "First-principles reasoning",
            "Analogical reasoning",
            "Counterfactual analysis",
            "Quantitative data analysis",
            "Constraint satisfaction",
            "Hypothesis generation and testing",
            "Temporal reasoning",
            "Spatial reasoning",
            "Probabilistic inference",
            "Meta-reasoning about reasoning quality",
        ]
        n(f"L{i}", f"Analytical Agent {i}", "swarm", "analytical",
          descs[i-1], ["reason", "analyze", "output_candidate", "score_confidence"])

    # ── Little Lucy Swarm — Creative (L17–L28) ───────────────────────────
    creative_descs = [
        "Free-form ideation and brainstorming",
        "Novel concept synthesis",
        "Metaphor and analogy generation",
        "Narrative construction",
        "Design pattern generation",
        "Cross-domain connection finding",
        "Hypothetical scenario construction",
        "Creative code generation",
        "Artistic and aesthetic reasoning",
        "Divergent thinking expansion",
        "Lateral thinking puzzles",
        "Innovative solution framing",
    ]
    for i, desc in enumerate(creative_descs, 17):
        n(f"L{i}", f"Creative Agent {i-16}", "swarm", "creative",
          desc, ["ideate", "synthesize", "output_candidate", "score_confidence"])

    # ── Little Lucy Swarm — Strategic (L29–L38) ──────────────────────────
    strategic_descs = [
        "Multi-step planning and roadmapping",
        "Resource allocation optimization",
        "Risk assessment and mitigation",
        "Long-horizon goal decomposition",
        "Competitive strategy modeling",
        "Timeline and dependency analysis",
        "Scenario planning (best/worst/likely)",
        "Priority stack management",
        "Stakeholder impact analysis",
        "Strategic coherence checking",
    ]
    for i, desc in enumerate(strategic_descs, 29):
        n(f"L{i}", f"Strategic Agent {i-28}", "swarm", "strategic",
          desc, ["plan", "strategize", "output_candidate", "score_confidence"])

    # ── Little Lucy Swarm — Reflective (L39–L48) ─────────────────────────
    reflective_descs = [
        "Self-evaluation of reasoning quality",
        "Output critique and red-teaming",
        "Consistency checking across agents",
        "Assumption surfacing and challenging",
        "Cognitive bias detection",
        "Reasoning trace audit",
        "Confidence calibration",
        "Uncertainty quantification",
        "Learning signal extraction",
        "Meta-cognitive state monitoring",
    ]
    for i, desc in enumerate(reflective_descs, 39):
        n(f"L{i}", f"Reflective Agent {i-38}", "swarm", "reflective",
          desc, ["reflect", "critique", "output_candidate", "score_confidence"])

    # ── Emma Supervisory Mesh (E1–E24) ────────────────────────────────────
    # Routing (E1–E6)
    for i in range(1, 7):
        routing_descs = [
            "Route perception output to relevant swarm agents",
            "Domain-based agent activation filter",
            "Confidence threshold routing gate",
            "Load-aware agent selection",
            "Priority-based routing",
            "Fallback routing for unknown domains",
        ]
        n(f"E{i}", f"Emma Router {i}", "emma", "routing",
          routing_descs[i-1], ["route", "activate_agents", "filter"])

    # Evaluation (E7–E12)
    eval_descs = [
        "Score swarm outputs by confidence",
        "Score swarm outputs by relevance",
        "Score swarm outputs by novelty",
        "Rank candidates by composite score",
        "Detect outlier or hallucinated outputs",
        "Final quality gate before merge",
    ]
    for i, desc in enumerate(eval_descs, 7):
        n(f"E{i}", f"Emma Evaluator {i-6}", "emma", "evaluation",
          desc, ["score", "rank", "evaluate"])

    # Merge (E13–E16)
    merge_descs = [
        "Merge analytical and creative outputs",
        "Merge strategic and reflective outputs",
        "Cross-validate merged reasoning",
        "Produce unified reasoning package",
    ]
    for i, desc in enumerate(merge_descs, 13):
        n(f"E{i}", f"Emma Merger {i-12}", "emma", "merge",
          desc, ["merge", "unify", "synthesize_outputs"])

    # Safety (E17–E20)
    safety_descs = [
        "Filter unsafe or harmful outputs",
        "Filter logically inconsistent outputs",
        "Filter off-policy or restricted outputs",
        "Final safety validation before Lucy Prime",
    ]
    for i, desc in enumerate(safety_descs, 17):
        n(f"E{i}", f"Emma Safety {i-16}", "emma", "safety",
          desc, ["filter_unsafe", "validate_safety", "block"])

    # Audit (E21–E24)
    audit_descs = [
        "Log all Emma decisions to DeltaVault",
        "Trace reasoning paths end-to-end",
        "Explain Emma decisions in natural language",
        "Generate governance compliance report",
    ]
    for i, desc in enumerate(audit_descs, 21):
        n(f"E{i}", f"Emma Auditor {i-20}", "emma", "audit",
          desc, ["log_decision", "trace", "explain", "report"])

    # ── Lucy Prime (LP1–LP12) ─────────────────────────────────────────────
    lp_specs = [
        ("LP1",  "Identity Core",         "identity",   "Lucy's core self-model, values, and purpose"),
        ("LP2",  "Tone Manager",          "personality","Adapt communication tone to context and user"),
        ("LP3",  "Personality Engine",    "personality","Express Lucy's persistent personality traits"),
        ("LP4",  "Response Synthesizer",  "output",     "Synthesize final response from merged reasoning"),
        ("LP5",  "Token Generator",       "output",     "Generate token-by-token response stream"),
        ("LP6",  "Output Formatter",      "output",     "Format response for target channel (text/voice/action)"),
        ("LP7",  "Consistency Checker",   "quality",    "Ensure response is consistent with prior context"),
        ("LP8",  "Final Safety Check",    "safety",     "Last gate: block unsafe or policy-violating outputs"),
        ("LP9",  "Memory Write Trigger",  "memory",     "Trigger memory write for important interactions"),
        ("LP10", "Reflection Trigger",    "learning",   "Trigger self-reflection after complex tasks"),
        ("LP11", "Self-State Manager",    "identity",   "Maintain Lucy's self-awareness and internal state"),
        ("LP12", "Output Dispatcher",     "output",     "Dispatch final output to correct output layer node"),
    ]
    for node_id, name, cat, desc in lp_specs:
        n(node_id, name, "lucy_prime", cat, desc,
          ["synthesize", "output", "dispatch"])

    # ── NodeMesh Infrastructure (N1–N10) ─────────────────────────────────
    nm_specs = [
        ("N1",  "Node Registry",          "infrastructure", "registry",   "Canonical registry of all 137 mesh nodes"),
        ("N2",  "Cluster Manager",        "infrastructure", "cluster",    "Manage node clusters and groupings"),
        ("N3",  "Load Balancer",          "infrastructure", "load",       "Balance load across equivalent nodes"),
        ("N4",  "Async Scheduler",        "infrastructure", "scheduling", "Schedule and coordinate async node execution"),
        ("N5",  "DAG Builder",            "infrastructure", "dag",        "Build execution DAG per incoming request"),
        ("N6",  "Attention Weight Engine","infrastructure", "attention",  "Compute and apply attention weights to nodes"),
        ("N7",  "Token Flow Controller",  "infrastructure", "flow",       "Control token/message flow rate and priority"),
        ("N8",  "Isolation Manager",      "infrastructure", "isolation",  "Isolate node failures from mesh propagation"),
        ("N9",  "Retry Manager",          "infrastructure", "resilience", "Retry failed node operations with backoff"),
        ("N10", "Health Monitor",         "infrastructure", "health",     "Monitor all node health and trigger repairs"),
    ]
    for node_id, name, layer_name, cat, desc in nm_specs:
        n(node_id, name, layer_name, cat, desc,
          ["monitor", "manage", "coordinate"])

    # ── Output Layer (O1–O7) ──────────────────────────────────────────────
    o_specs = [
        ("O1", "Text Output",          "output", "channel",  "Deliver text response to user interface"),
        ("O2", "Voice Output",         "output", "channel",  "Synthesize and deliver voice response"),
        ("O3", "Action Output",        "output", "action",   "Execute approved actions (tool calls, file writes)"),
        ("O4", "MR Output Adapter",    "output", "channel",  "Deliver output to Mixed Reality interface"),
        ("O5", "Mobile Output Adapter","output", "channel",  "Deliver output to mobile interface"),
        ("O6", "Streaming Output Node","output", "streaming","Stream partial outputs as they generate"),
        ("O7", "Feedback Collector",   "output", "feedback", "Collect user feedback and route to learning loop"),
    ]
    for node_id, name, layer_name, cat, desc in o_specs:
        n(node_id, name, layer_name, cat, desc, ["output", "stream", "deliver"])

    # ── Safety Global Layer (S1–S6) ───────────────────────────────────────
    s_specs = [
        ("S1", "Policy Engine",        "safety", "policy",      "Enforce all Lucy OS policies globally"),
        ("S2", "Constraint Validator", "safety", "constraints", "Validate all outputs against hard constraints"),
        ("S3", "Bias Detector",        "safety", "bias",        "Detect and flag cognitive/data biases"),
        ("S4", "Risk Scorer",          "safety", "risk",        "Score risk level of any proposed action"),
        ("S5", "Override Controller",  "safety", "override",    "Handle safety overrides and escalations"),
        ("S6", "Safety Logger",        "safety", "logging",     "Log all safety events to audit trail"),
    ]
    for node_id, name, layer_name, cat, desc in s_specs:
        n(node_id, name, layer_name, cat, desc, ["enforce", "validate", "log"])

    return nodes


class NodeRegistry:
    """N1 — The canonical source of truth for all 137 Lucy mesh nodes."""

    def __init__(self):
        self._nodes: Dict[str, MeshNode] = _build_all_nodes()
        self._lock = threading.RLock()
        assert len(self._nodes) == 137, f"Expected 137 nodes, got {len(self._nodes)}"

    def get(self, node_id: str) -> Optional[MeshNode]:
        return self._nodes.get(node_id)

    def all(self) -> List[dict]:
        with self._lock:
            return [n.to_dict() for n in self._nodes.values()]

    def by_layer(self, layer: str) -> List[dict]:
        with self._lock:
            return [n.to_dict() for n in self._nodes.values() if n.layer == layer]

    def by_category(self, category: str) -> List[dict]:
        with self._lock:
            return [n.to_dict() for n in self._nodes.values() if n.category == category]

    def summary(self) -> dict:
        with self._lock:
            layers = {}
            statuses = {"online": 0, "degraded": 0, "offline": 0, "busy": 0}
            for node in self._nodes.values():
                layers[node.layer] = layers.get(node.layer, 0) + 1
                statuses[node.status] = statuses.get(node.status, 0) + 1
            return {
                "totalNodes": len(self._nodes),
                "byLayer": layers,
                "byStatus": statuses,
                "healthy": statuses["online"] + statuses["busy"],
            }

    def update_status(self, node_id: str, status: str, load: float = None):
        with self._lock:
            node = self._nodes.get(node_id)
            if node:
                node.status = status
                if load is not None:
                    node.set_load(load)
                node.mark_active()

    def mark_active(self, node_id: str):
        with self._lock:
            node = self._nodes.get(node_id)
            if node:
                node.mark_active()

    def get_online_nodes(self, layer: str = None) -> List[str]:
        with self._lock:
            return [
                nid for nid, n in self._nodes.items()
                if n.status in ("online", "busy")
                and (layer is None or n.layer == layer)
            ]

    def get_swarm_nodes(self) -> List[str]:
        """All 48 Little Lucy agents."""
        return [f"L{i}" for i in range(1, 49)]

    def get_emma_nodes(self) -> List[str]:
        """All 24 Emma supervisory nodes."""
        return [f"E{i}" for i in range(1, 25)]

    def get_perception_nodes(self) -> List[str]:
        return [f"P{i}" for i in range(1, 13)]

    def get_memory_nodes(self) -> List[str]:
        return [f"M{i}" for i in range(1, 19)]

    def get_lucy_prime_nodes(self) -> List[str]:
        return [f"LP{i}" for i in range(1, 13)]

    def get_output_nodes(self) -> List[str]:
        return [f"O{i}" for i in range(1, 8)]

    def get_safety_nodes(self) -> List[str]:
        return [f"S{i}" for i in range(1, 7)]

    def increment_error(self, node_id: str):
        with self._lock:
            node = self._nodes.get(node_id)
            if node:
                node.error_count += 1
                if node.error_count >= 5:
                    node.status = "degraded"


# Singleton
node_registry = NodeRegistry()