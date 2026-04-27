"""
Emma Supervisory Mesh — Merger Layer (E13-E16)
E13: ContentMerger    — fuses top-k candidate texts into unified reasoning
E14: ConfidenceMerger — computes merged confidence from weighted candidates
E15: TraceAggregator  — collects + deduplicates reasoning traces
E16: ConsensusBuilder — detects agreement/disagreement, produces consensus verdict
"""

from __future__ import annotations
import time
import uuid
import logging
from dataclasses import dataclass, field
from typing import Any

from emma_mesh.evaluator import ScoredCandidate

logger = logging.getLogger("emma.merger")

MIN_CONSENSUS_RATIO  = 0.60   # 60% of candidates must agree for consensus
HIGH_CONF_THRESHOLD  = 0.75   # candidate treated as "strong" if composite >= this
MERGE_MAX_CANDIDATES = 5      # hard limit going into merge


@dataclass
class MergedReasoning:
    """Output of E13-E16 merge pipeline — unified reasoning package."""
    merge_id:           str   = field(default_factory=lambda: str(uuid.uuid4())[:8])
    merged_content:     str   = ""
    merged_confidence:  float = 0.0
    consensus:          str   = "none"          # "strong" | "partial" | "divergent" | "none"
    consensus_ratio:    float = 0.0
    dominant_agent:     str   = ""
    contributor_agents: list[str] = field(default_factory=list)
    aggregated_traces:  list[str] = field(default_factory=list)
    divergence_notes:   list[str] = field(default_factory=list)
    merge_strategy:     str   = "weighted_join"
    candidate_count:    int   = 0
    timestamp:          float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "merge_id":           self.merge_id,
            "merged_content":     self.merged_content,
            "merged_confidence":  round(self.merged_confidence, 4),
            "consensus":          self.consensus,
            "consensus_ratio":    round(self.consensus_ratio, 4),
            "dominant_agent":     self.dominant_agent,
            "contributor_agents": self.contributor_agents,
            "aggregated_traces":  self.aggregated_traces,
            "divergence_notes":   self.divergence_notes,
            "merge_strategy":     self.merge_strategy,
            "candidate_count":    self.candidate_count,
            "timestamp":          self.timestamp,
        }


# ─────────────────────────────────────────────
# E13 — Content Merger
# ─────────────────────────────────────────────

class E13ContentMerger:
    """
    E13 — Fuses top-k candidate texts into a single coherent reasoning block.

    Strategy:
    1. If top candidate score >= HIGH_CONF_THRESHOLD → anchor strategy: use top output
       as primary, enrich with unique sentences from supporting candidates.
    2. Otherwise → weighted join: concatenate outputs with contribution markers,
       ordered by composite score.
    """

    def _extract_unique_sentences(self, base: str, others: list[str]) -> list[str]:
        """Pull sentences from others not semantically duplicated in base."""
        base_lower = base.lower()
        unique = []
        for text in others:
            for sentence in text.split("."):
                s = sentence.strip()
                if len(s) < 20:
                    continue
                # Rough dedup: skip if >50% of sentence words are already in base
                words = set(s.lower().split())
                overlap = sum(1 for w in words if w in base_lower)
                if overlap / max(len(words), 1) < 0.50:
                    unique.append(s)
        return unique

    def merge(
        self,
        candidates: list[ScoredCandidate],
        strategy: str = "auto",
    ) -> tuple[str, str]:
        """
        Returns (merged_content, strategy_used).
        """
        if not candidates:
            return ("No reasoning candidates available.", "empty")

        # Cap
        cands = candidates[:MERGE_MAX_CANDIDATES]

        if strategy == "auto":
            strategy = "anchor" if cands[0].composite >= HIGH_CONF_THRESHOLD else "weighted_join"

        if strategy == "anchor":
            primary = cands[0].content
            supporting_texts = [c.content for c in cands[1:]]
            unique_sents = self._extract_unique_sentences(primary, supporting_texts)
            enrichment = ""
            if unique_sents:
                enrichment = "\n\n**Supporting insights:**\n" + " ".join(
                    f"• {s}." for s in unique_sents[:4]
                )
            merged = primary + enrichment

        else:  # weighted_join
            parts = []
            for i, c in enumerate(cands):
                weight_label = f"[{c.agent_type.upper()} | score={c.composite:.3f}]"
                parts.append(f"{weight_label}\n{c.content}")
            merged = "\n\n---\n\n".join(parts)

        logger.debug(f"[E13] strategy={strategy} merged_len={len(merged)}")
        return merged, strategy


# ─────────────────────────────────────────────
# E14 — Confidence Merger
# ─────────────────────────────────────────────

class E14ConfidenceMerger:
    """
    E14 — Computes a single merged confidence score from weighted candidates.
    Uses softmax-weighted average of composite scores as the merged confidence.
    """

    import math as _math

    def merge(self, candidates: list[ScoredCandidate]) -> float:
        if not candidates:
            return 0.0

        import math
        scores = [c.composite for c in candidates]

        # Softmax weights
        max_s = max(scores)
        exps  = [math.exp(s - max_s) for s in scores]
        total = sum(exps)
        weights = [e / total for e in exps]

        merged_conf = sum(w * s for w, s in zip(weights, scores))
        merged_conf = round(min(merged_conf, 1.0), 4)
        logger.debug(f"[E14] merged_confidence={merged_conf} from {len(candidates)} candidates")
        return merged_conf


# ─────────────────────────────────────────────
# E15 — Trace Aggregator
# ─────────────────────────────────────────────

class E15TraceAggregator:
    """
    E15 — Collects all per-node traces, deduplicates, and assembles
    a flat ordered trace list for the merged reasoning package.
    """

    def aggregate(self, candidates: list[ScoredCandidate]) -> list[str]:
        seen: set[str] = set()
        traces: list[str] = []

        for c in candidates:
            header = f"[{c.agent_id}|{c.agent_type}|rank={c.rank}]"
            if header not in seen:
                seen.add(header)
                traces.append(header)
            for t in c.trace:
                key = f"{c.agent_id}:{t}"
                if key not in seen:
                    seen.add(key)
                    traces.append(f"  {t}")

        logger.debug(f"[E15] trace_lines={len(traces)}")
        return traces


# ─────────────────────────────────────────────
# E16 — Consensus Builder
# ─────────────────────────────────────────────

class E16ConsensusBuilder:
    """
    E16 — Detects agreement/disagreement among top candidates.

    Consensus levels:
      strong    — ≥80% of candidates share dominant intent/topic tokens
      partial   — 60-80% agree
      divergent — <60% agree (multiple conflicting positions)
      none      — single candidate or empty

    Also surfaces divergence notes for Lucy Prime to acknowledge uncertainty.
    """

    STOP_WORDS = {
        "the","a","an","is","are","was","were","it","this","that",
        "of","to","in","on","at","for","and","or","but","with","by","i","you"
    }

    def _key_tokens(self, text: str) -> set[str]:
        return {
            t.strip(".,!?;:\"'()")
            for t in text.lower().split()
            if t not in self.STOP_WORDS and len(t) > 3
        }

    def build(
        self,
        candidates: list[ScoredCandidate],
    ) -> tuple[str, float, list[str]]:
        """
        Returns (consensus_level, consensus_ratio, divergence_notes).
        """
        if not candidates:
            return ("none", 0.0, [])
        if len(candidates) == 1:
            return ("none", 1.0, [])

        # Build token sets
        token_sets = [self._key_tokens(c.content) for c in candidates]

        # Find tokens present in majority of candidates
        from collections import Counter
        all_tokens: list[str] = []
        for ts in token_sets:
            all_tokens.extend(ts)

        token_counts = Counter(all_tokens)
        n = len(candidates)
        majority_tokens = {t for t, cnt in token_counts.items() if cnt >= max(2, n * 0.5)}

        # Score each candidate: what fraction of their tokens are "shared"
        agree_scores = []
        for ts in token_sets:
            if not ts:
                agree_scores.append(0.0)
            else:
                shared = len(ts & majority_tokens)
                agree_scores.append(shared / len(ts))

        avg_agreement = sum(agree_scores) / n

        # Consensus level
        if avg_agreement >= 0.80:
            level = "strong"
        elif avg_agreement >= MIN_CONSENSUS_RATIO:
            level = "partial"
        else:
            level = "divergent"

        # Build divergence notes for divergent candidates
        divergence_notes: list[str] = []
        if level == "divergent":
            for c, score in zip(candidates, agree_scores):
                if score < 0.40:
                    divergence_notes.append(
                        f"{c.agent_id}({c.agent_type}) low_agreement={score:.2f}"
                    )

        logger.debug(f"[E16] consensus={level} ratio={avg_agreement:.3f} divergences={len(divergence_notes)}")
        return (level, round(avg_agreement, 4), divergence_notes)


# ─────────────────────────────────────────────
# Composite Merger Pipeline (E13-E16)
# ─────────────────────────────────────────────

class EmmaMerger:
    """
    Runs E13 → E14 → E15 → E16 on the ranked candidate list from EmmaEvaluator.
    Returns a unified MergedReasoning package.
    """

    def __init__(self):
        self.e13 = E13ContentMerger()
        self.e14 = E14ConfidenceMerger()
        self.e15 = E15TraceAggregator()
        self.e16 = E16ConsensusBuilder()

    def merge(
        self,
        candidates: list[ScoredCandidate],
        merge_strategy: str = "auto",
    ) -> MergedReasoning:
        result = MergedReasoning()
        result.candidate_count = len(candidates)

        if not candidates:
            result.merged_content    = "No candidates to merge."
            result.merged_confidence = 0.0
            result.consensus         = "none"
            return result

        # E13 — content merge
        content, strategy = self.e13.merge(candidates, strategy=merge_strategy)
        result.merged_content = content
        result.merge_strategy = strategy

        # E14 — confidence merge
        result.merged_confidence = self.e14.merge(candidates)

        # E15 — trace aggregate
        result.aggregated_traces = self.e15.aggregate(candidates)

        # E16 — consensus
        level, ratio, div_notes = self.e16.build(candidates)
        result.consensus       = level
        result.consensus_ratio = ratio
        result.divergence_notes = div_notes

        # Meta
        result.dominant_agent     = candidates[0].agent_id if candidates else ""
        result.contributor_agents = [c.agent_id for c in candidates]

        logger.info(
            f"[EmmaMerger] merge_id={result.merge_id} "
            f"strategy={strategy} confidence={result.merged_confidence:.4f} "
            f"consensus={level}({ratio:.3f}) "
            f"contributors={result.contributor_agents}"
        )
        return result

    def merge_report(
        self,
        candidates: list[ScoredCandidate],
        merge_strategy: str = "auto",
    ) -> dict[str, Any]:
        t0 = time.time()
        merged = self.merge(candidates, merge_strategy)
        elapsed = round(time.time() - t0, 4)
        d = merged.to_dict()
        d["merge_time_s"] = elapsed
        return d


# Singleton
emma_merger = EmmaMerger()