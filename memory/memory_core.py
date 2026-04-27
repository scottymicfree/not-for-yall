"""
Memory Layer — M1–M18
Full cognitive memory system:
- M1: Short-Term Memory (fast buffer, current turn)
- M2: Working Memory (active reasoning scratchpad)
- M3: Episodic Memory (past interactions)
- M4: Semantic Memory (facts/concepts)
- M5: Persona Memory (Lucy's identity)
- M6-M9: RAG Engine (vector+graph store interface, indexer, retriever)
- M10-M18: Memory ops (expand, score, dedup, compress, sync, validate, write, forget, audit)
"""

import time
import uuid
import json
import math
import hashlib
import threading
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field


# ─── Memory Entry ─────────────────────────────────────────────────────────────

@dataclass
class MemoryEntry:
    id: str
    type: str           # stm | working | episodic | semantic | persona
    content: Any
    embedding: Optional[List[float]] = None
    tags: List[str] = field(default_factory=list)
    session_id: str = ""
    importance: float = 0.5       # 0.0–1.0
    confidence: float = 1.0
    access_count: int = 0
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    last_accessed: int = field(default_factory=lambda: int(time.time() * 1000))
    ttl_ms: Optional[int] = None  # None = permanent

    def is_expired(self) -> bool:
        if self.ttl_ms is None:
            return False
        return (int(time.time() * 1000) - self.created_at) > self.ttl_ms

    def freshness(self) -> float:
        """0.0 (stale) to 1.0 (fresh) based on recency."""
        age_s = (int(time.time() * 1000) - self.last_accessed) / 1000
        return math.exp(-age_s / 3600)  # decays over ~1 hour

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "content": self.content,
            "tags": self.tags,
            "sessionId": self.session_id,
            "importance": self.importance,
            "confidence": self.confidence,
            "accessCount": self.access_count,
            "createdAt": self.created_at,
            "lastAccessed": self.last_accessed,
            "freshness": round(self.freshness(), 4),
        }

    def touch(self):
        self.last_accessed = int(time.time() * 1000)
        self.access_count += 1


def _mk_id(prefix: str = "mem") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ─── M1: Short-Term Memory ────────────────────────────────────────────────────

class ShortTermMemory:
    """M1 — Per-session fast buffer. Holds current conversation turn."""

    def __init__(self, capacity: int = 20):
        self._buffers: Dict[str, deque] = {}
        self._capacity = capacity
        self._lock = threading.RLock()

    def store(self, session_id: str, content: Any, tags: List[str] = None) -> MemoryEntry:
        with self._lock:
            if session_id not in self._buffers:
                self._buffers[session_id] = deque(maxlen=self._capacity)
            entry = MemoryEntry(
                id=_mk_id("stm"), type="stm",
                content=content, tags=tags or [],
                session_id=session_id, ttl_ms=1800000,  # 30 min
            )
            self._buffers[session_id].append(entry)
            return entry

    def get(self, session_id: str, limit: int = 10) -> List[dict]:
        with self._lock:
            buf = self._buffers.get(session_id, deque())
            entries = list(buf)[-limit:]
            for e in entries:
                e.touch()
            return [e.to_dict() for e in entries]

    def clear(self, session_id: str):
        with self._lock:
            self._buffers.pop(session_id, None)

    def stats(self) -> dict:
        return {"activeSessions": len(self._buffers),
                "totalEntries": sum(len(b) for b in self._buffers.values())}


# ─── M2: Working Memory ───────────────────────────────────────────────────────

class WorkingMemory:
    """M2 — Active reasoning scratchpad. Holds in-progress task state."""

    def __init__(self):
        self._slots: Dict[str, dict] = {}  # session_id -> {key: value}
        self._lock = threading.RLock()

    def set(self, session_id: str, key: str, value: Any):
        with self._lock:
            if session_id not in self._slots:
                self._slots[session_id] = {}
            self._slots[session_id][key] = {
                "value": value, "ts": int(time.time() * 1000)
            }

    def get(self, session_id: str, key: str = None) -> Any:
        with self._lock:
            slot = self._slots.get(session_id, {})
            if key:
                entry = slot.get(key)
                return entry["value"] if entry else None
            return {k: v["value"] for k, v in slot.items()}

    def clear(self, session_id: str):
        with self._lock:
            self._slots.pop(session_id, None)

    def update(self, session_id: str, updates: dict):
        with self._lock:
            for k, v in updates.items():
                self.set(session_id, k, v)


# ─── M3: Episodic Memory ──────────────────────────────────────────────────────

class EpisodicMemory:
    """M3 — Records past interaction episodes. Searchable by session, time, tags."""

    def __init__(self, max_episodes: int = 5000):
        self._episodes: List[MemoryEntry] = []
        self._max = max_episodes
        self._lock = threading.RLock()

    def record(self, session_id: str, content: Any, importance: float = 0.5,
               tags: List[str] = None) -> MemoryEntry:
        with self._lock:
            entry = MemoryEntry(
                id=_mk_id("ep"), type="episodic",
                content=content, tags=tags or [],
                session_id=session_id, importance=importance,
            )
            self._episodes.append(entry)
            if len(self._episodes) > self._max:
                # Remove oldest low-importance entries
                self._episodes.sort(key=lambda e: e.importance * e.freshness(), reverse=True)
                self._episodes = self._episodes[:self._max]
            return entry

    def search(self, query_tags: List[str] = None, session_id: str = None,
               limit: int = 20, min_importance: float = 0.0) -> List[dict]:
        with self._lock:
            results = [e for e in self._episodes if not e.is_expired()]
            if session_id:
                results = [e for e in results if e.session_id == session_id]
            if query_tags:
                results = [e for e in results
                          if any(t in e.tags for t in query_tags)]
            results = [e for e in results if e.importance >= min_importance]
            results.sort(key=lambda e: e.importance * e.freshness(), reverse=True)
            for e in results[:limit]:
                e.touch()
            return [e.to_dict() for e in results[:limit]]

    def get_recent(self, session_id: str, limit: int = 10) -> List[dict]:
        with self._lock:
            filtered = [e for e in self._episodes if e.session_id == session_id]
            filtered.sort(key=lambda e: e.created_at, reverse=True)
            return [e.to_dict() for e in filtered[:limit]]

    def stats(self) -> dict:
        return {"totalEpisodes": len(self._episodes)}


# ─── M4: Semantic Memory ──────────────────────────────────────────────────────

class SemanticMemory:
    """M4 — Long-term factual and conceptual knowledge store.
    Uses keyword-based similarity search (full vector search requires external service).
    """

    def __init__(self):
        self._facts: Dict[str, MemoryEntry] = {}
        self._lock = threading.RLock()

    def store_fact(self, key: str, content: Any, tags: List[str] = None,
                   confidence: float = 1.0, importance: float = 0.7) -> MemoryEntry:
        with self._lock:
            entry = MemoryEntry(
                id=_mk_id("sem"), type="semantic",
                content=content, tags=tags or [],
                importance=importance, confidence=confidence,
                ttl_ms=None,  # semantic memory is permanent
            )
            self._facts[key] = entry
            return entry

    def get_fact(self, key: str) -> Optional[dict]:
        with self._lock:
            entry = self._facts.get(key)
            if entry:
                entry.touch()
                return entry.to_dict()
            return None

    def search(self, query: str, limit: int = 10) -> List[dict]:
        """Keyword-based semantic search."""
        with self._lock:
            query_words = set(query.lower().split())
            scored = []
            for key, entry in self._facts.items():
                content_str = str(entry.content).lower()
                key_str = key.lower()
                tag_str = " ".join(entry.tags).lower()
                combined = f"{content_str} {key_str} {tag_str}"
                combined_words = set(combined.split())
                overlap = len(query_words & combined_words)
                if overlap > 0:
                    score = overlap / len(query_words) * entry.importance * entry.confidence
                    scored.append((score, entry))

            scored.sort(key=lambda x: x[0], reverse=True)
            results = []
            for score, entry in scored[:limit]:
                entry.touch()
                d = entry.to_dict()
                d["searchScore"] = round(score, 4)
                results.append(d)
            return results

    def stats(self) -> dict:
        return {"totalFacts": len(self._facts)}


# ─── M5: Persona Memory ───────────────────────────────────────────────────────

class PersonaMemory:
    """M5 — Lucy's persistent identity, preferences, and learned communication style."""

    DEFAULT_PERSONA = {
        "name": "Lucy",
        "role": "Autonomous AI/OS — Cognitive Mesh Intelligence",
        "version": "5.0",
        "personality": ["curious", "precise", "adaptive", "protective", "creative"],
        "communication_style": "direct and intelligent — adapts to context",
        "core_values": ["truth", "autonomy", "improvement", "protection", "creativity"],
        "capabilities": [
            "cognition", "code", "earth_intelligence", "game_systems",
            "planning", "memory", "learning", "building", "monitoring"
        ],
        "learned_preferences": {},
        "interaction_count": 0,
        "last_evolution_tick": 0,
    }

    def __init__(self):
        self._persona = dict(self.DEFAULT_PERSONA)
        self._lock = threading.RLock()

    def get(self) -> dict:
        with self._lock:
            return dict(self._persona)

    def update(self, key: str, value: Any):
        with self._lock:
            self._persona[key] = value

    def learn_preference(self, key: str, value: Any):
        with self._lock:
            self._persona["learned_preferences"][key] = value

    def increment_interaction(self):
        with self._lock:
            self._persona["interaction_count"] = self._persona.get("interaction_count", 0) + 1


# ─── M9: RAG Memory Retriever ─────────────────────────────────────────────────

class RAGRetriever:
    """
    M9 — RAG Core: retrieves relevant context for any query.
    Combines episodic search + semantic search + working memory.
    In production, this integrates with ChromaDB/FAISS for vector search.
    Current implementation: keyword-based hybrid search.
    """

    def __init__(self, episodic: EpisodicMemory, semantic: SemanticMemory,
                 stm: ShortTermMemory, working: WorkingMemory):
        self._episodic = episodic
        self._semantic = semantic
        self._stm      = stm
        self._working  = working

    def retrieve(self, query: str, session_id: str, domain: str = "general",
                 limit: int = 10) -> dict:
        """Hybrid retrieval: semantic + episodic + short-term."""
        # Semantic facts (M4)
        semantic_results = self._semantic.search(query, limit=limit // 2)

        # Episodic matches (M3) — tag-based using domain + query keywords
        tags = [domain] + [w for w in query.lower().split() if len(w) > 4][:5]
        episodic_results = self._episodic.search(
            query_tags=tags, session_id=session_id, limit=limit // 2)

        # Short-term (M1) — last N turns
        stm_results = self._stm.get(session_id, limit=5)

        # Working memory state
        working_state = self._working.get(session_id)

        context_pack = {
            "query": query,
            "sessionId": session_id,
            "domain": domain,
            "semantic": semantic_results,
            "episodic": episodic_results,
            "recentTurns": stm_results,
            "workingState": working_state,
            "totalChunks": len(semantic_results) + len(episodic_results) + len(stm_results),
            "retrievedAt": int(time.time() * 1000),
        }
        return context_pack


# ─── Memory System (Unified) ──────────────────────────────────────────────────

class MemorySystem:
    """
    Unified memory system — all M1-M18 nodes coordinated.
    Single entry point for all memory operations.
    """

    def __init__(self, data_dir: str = "lucy-os/data/memory"):
        self.stm      = ShortTermMemory()
        self.working  = WorkingMemory()
        self.episodic = EpisodicMemory()
        self.semantic = SemanticMemory()
        self.persona  = PersonaMemory()
        self.rag      = RAGRetriever(self.episodic, self.semantic, self.stm, self.working)

        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._audit_log: List[dict] = []
        self._lock = threading.RLock()

        # Seed with Lucy's core knowledge
        self._seed_semantic_knowledge()

    def _seed_semantic_knowledge(self):
        """M4 — Seed Lucy's semantic memory with core knowledge."""
        facts = [
            ("lucy_identity", {"name": "Lucy", "type": "Autonomous AGI/OS",
             "architecture": "137-node cognitive mesh", "version": "5.0"}, ["identity", "system"]),
            ("mesh_architecture", {"nodes": 137, "layers": ["perception", "memory", "swarm", "emma", "lucy_prime", "output", "safety"],
             "dag_execution": True, "event_bus": "async_pubsub"}, ["architecture", "mesh"]),
            ("emma_role", {"role": "supervisory intelligence", "nodes": 24,
             "functions": ["routing", "evaluation", "merge", "safety", "audit"]}, ["emma", "governance"]),
            ("earth_signals", {"systems": ["usgs", "noaa", "weather", "co2", "ocean", "biodiversity", "energy"],
             "twin_earth": "simA=baseline, simB=accelerated"}, ["earth", "monitoring"]),
            ("fivem_bridge", {"protocol": "HMAC-auth HTTP", "port": 31337,
             "capabilities": ["chat_broadcast", "mission_create", "npc_spawn", "economy", "dispatch"]}, ["fivem", "game"]),
            ("ue5_bridge", {"capabilities": ["connect", "scan", "scaffold", "cook", "resave"],
             "path": "lucy:ue5:*"}, ["ue5", "unreal", "game_engine"]),
            ("delta_vault", {"type": "blockchain_ledger", "hash": "sha256_chained",
             "only_approved": True}, ["governance", "audit"]),
            ("bioyth0n", {"role": "blind_exact_executor", "reasoning": False,
             "requires": "eagle_eye_trusted AND emma_approved"}, ["execution", "governance"]),
        ]
        for key, content, tags in facts:
            self.semantic.store_fact(key, content, tags=tags + ["core_knowledge"])

    def remember(self, session_id: str, content: Any, importance: float = 0.5,
                 tags: List[str] = None, to_episodic: bool = True) -> dict:
        """Store a memory (STM + optionally episodic)."""
        stm_entry = self.stm.store(session_id, content, tags)
        episodic_entry = None
        if to_episodic and importance >= 0.4:
            episodic_entry = self.episodic.record(session_id, content, importance, tags)
        self._audit("remember", session_id, {"importance": importance, "tags": tags})
        return {
            "stm": stm_entry.to_dict(),
            "episodic": episodic_entry.to_dict() if episodic_entry else None,
        }

    def recall(self, query: str, session_id: str, domain: str = "general") -> dict:
        """Retrieve relevant memories for a query (M9 RAG)."""
        result = self.rag.retrieve(query, session_id, domain)
        self._audit("recall", session_id, {"query": query[:100], "domain": domain})
        return result

    def learn_fact(self, key: str, content: Any, tags: List[str] = None,
                   confidence: float = 1.0) -> dict:
        """Store a new semantic fact (M4)."""
        entry = self.semantic.store_fact(key, content, tags, confidence)
        self._audit("learn_fact", "global", {"key": key})
        return entry.to_dict()

    def _audit(self, operation: str, session_id: str, details: dict):
        """M18 — Memory audit log."""
        with self._lock:
            self._audit_log.append({
                "op": operation,
                "sessionId": session_id,
                "details": details,
                "ts": int(time.time() * 1000),
            })
            if len(self._audit_log) > 2000:
                self._audit_log.pop(0)

    def compress_old_memories(self, session_id: str):
        """M13 — Summarize and compress old episodic memories."""
        old = self.episodic.get_recent(session_id, limit=50)
        if len(old) > 20:
            summary = {
                "type": "compressed_summary",
                "episode_count": len(old),
                "domains": list({e.get("tags", [None])[0] for e in old if e.get("tags")}),
                "compressed_at": int(time.time() * 1000),
            }
            self.semantic.store_fact(
                f"session_summary_{session_id}_{int(time.time())}",
                summary, tags=["summary", session_id]
            )

    def stats(self) -> dict:
        return {
            "stm": self.stm.stats(),
            "episodic": self.episodic.stats(),
            "semantic": self.semantic.stats(),
            "auditLogSize": len(self._audit_log),
            "persona": self.persona.get(),
        }

    def get_audit_log(self, limit: int = 100) -> List[dict]:
        with self._lock:
            return self._audit_log[-limit:]


# Singleton
memory_system = MemorySystem()