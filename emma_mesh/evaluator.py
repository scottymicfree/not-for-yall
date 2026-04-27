"""
Emma Supervisory Mesh — Evaluator Layer (E7-E12)
E7:  ConfidenceScorer  — grades raw confidence of each swarm output
E8:  RelevanceScorer   — scores alignment with original query intent
E9:  NoveltyScorer     — rewards unique insights not repeated across outputs
E10: ConsistencyScorer — penalizes contradictions between candidate outputs
E11: CompositeGrader   — applies Emma formula: (conf*0.4)+(rel*0.3)+(con*0.2)+(nov*0.1)
E12: RankFilter        — selects top-k candidates by composite score, prunes low scorers
"""

from __future__ import annotations
import math
import time
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("emma.evaluator")

PRUNE_THRESHOLD   = 0.35   # below this → discard
TOP_K_DEFAULT     = 5      # max candidates forwarded to merger
DIVERSITY_BONUS   = 0.04   # added to novelty if output is truly unique


@dataclass
class ScoredCandidate:
    """A swarm candidate output decorated with E7-E12 scores."""
    agent_id:      str
    agent_type:    str
    content:       str
    raw_confidence: float

    # E7-E12 sub-scores
    confidence:   float = 0.0
    relevance:    float = 0.0
    novelty:      float = 0.0
    consistency:  float = 0.0
    composite:    float = 0.0

    # meta
    pruned:       bool  = False
    prune_reason: str   = ""
    rank:         int   = 0
    trace:        list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "agent_id":       self.agent_id,
            "agent_type":     self.agent_type,
            "content":        self.content[:500],          # truncate for transport
            "raw_confidence": round(self.raw_confidence, 4),
            "confidence":     round(self.confidence, 4),
            "relevance":      round(self.relevance, 4),
            "novelty":        round(self.novelty, 4),
            "consistency":    round(self.consistency, 4),
            "composite":      round(self.composite, 4),
            "pruned":         self.pruned,
            "prune_reason":   self.prune_reason,
            "rank":           self.rank,
            "trace":          self.trace,
        }


# ─────────────────────────────────────────────
# E7 — Confidence Scorer
# ─────────────────────────────────────────────

class E7ConfidenceScorer:
    """
    E7 — Grades confidence of each swarm output.
    Uses the agent's own confidence value, corrected by output length signal
    and internal hedge language detection.
    """

    HEDGE_PHRASES = [
        "i'm not sure", "i am not sure", "might be", "could be",
        "possibly", "perhaps", "uncertain", "not certain", "unclear",
        "i think", "i believe", "maybe", "probably",
    ]

    def score(self, candidate: ScoredCandidate) -> float:
        base = float(candidate.raw_confidence)
        text = candidate.content.lower()

        # Penalise hedge language
        hedge_count = sum(1 for p in self.HEDGE_PHRASES if p in text)
        hedge_penalty = min(hedge_count * 0.04, 0.20)

        # Reward longer, substantive outputs (up to 600 chars)
        length_bonus = min(len(candidate.content) / 600.0, 1.0) * 0.05

        score = max(0.0, min(1.0, base - hedge_penalty + length_bonus))
        candidate.confidence = round(score, 4)
        candidate.trace.append(f"E7:conf={score:.3f}(base={base},hedge={hedge_count},len_bonus={length_bonus:.3f})")
        return score


# ─────────────────────────────────────────────
# E8 — Relevance Scorer
# ─────────────────────────────────────────────

class E8RelevanceScorer:
    """
    E8 — Scores how well a candidate addresses the query.
    Keyword overlap between query tokens and candidate content.
    """

    STOP_WORDS = {
        "the","a","an","is","are","was","were","it","this","that",
        "of","to","in","on","at","for","and","or","but","with","by",
        "from","be","as","not","do","have","i","you","we","they","he","she",
    }

    def _tokenize(self, text: str) -> set[str]:
        tokens = text.lower().split()
        return {t.strip(".,?!;:\"'()") for t in tokens if t not in self.STOP_WORDS and len(t) > 2}

    def score(self, candidate: ScoredCandidate, query: str) -> float:
        query_tokens   = self._tokenize(query)
        content_tokens = self._tokenize(candidate.content)

        if not query_tokens:
            score = 0.5
        else:
            overlap = len(query_tokens & content_tokens)
            # Jaccard-like with asymmetric weighting on query coverage
            coverage = overlap / len(query_tokens)
            precision = overlap / max(len(content_tokens), 1)
            score = round((coverage * 0.7 + precision * 0.3), 4)
            score = min(score, 1.0)

        candidate.relevance = score
        candidate.trace.append(f"E8:rel={score:.3f}(q_tokens={len(query_tokens)},overlap={overlap if query_tokens else 0})")
        return score


# ─────────────────────────────────────────────
# E9 — Novelty Scorer
# ─────────────────────────────────────────────

class E9NoveltyScorer:
    """
    E9 — Rewards unique insights not duplicated across candidates.
    Uses token-level Jaccard dissimilarity against peer outputs.
    """

    STOP_WORDS = E8RelevanceScorer.STOP_WORDS

    def _tokenize(self, text: str) -> set[str]:
        tokens = text.lower().split()
        return {t.strip(".,?!;:\"'()") for t in tokens if t not in self.STOP_WORDS and len(t) > 2}

    def score_batch(self, candidates: list[ScoredCandidate]) -> None:
        token_sets = [self._tokenize(c.content) for c in candidates]

        for i, cand in enumerate(candidates):
            my_tokens = token_sets[i]
            if not my_tokens:
                cand.novelty = 0.3
                cand.trace.append("E9:novelty=0.3(empty)")
                continue

            # Average dissimilarity to all other candidates
            dissimilarities = []
            for j, other_tokens in enumerate(token_sets):
                if i == j or not other_tokens:
                    continue
                intersection = len(my_tokens & other_tokens)
                union = len(my_tokens | other_tokens)
                jaccard = intersection / union if union else 0.0
                dissimilarities.append(1.0 - jaccard)

            avg_dissim = sum(dissimilarities) / len(dissimilarities) if dissimilarities else 1.0

            # Solo candidate gets neutral novelty
            if not dissimilarities:
                avg_dissim = 0.7

            # Diversity bonus for truly unique outputs
            bonus = DIVERSITY_BONUS if avg_dissim > 0.85 else 0.0
            score = round(min(avg_dissim + bonus, 1.0), 4)
            cand.novelty = score
            cand.trace.append(f"E9:novelty={score:.3f}(dissim={avg_dissim:.3f})")


# ─────────────────────────────────────────────
# E10 — Consistency Scorer
# ─────────────────────────────────────────────

class E10ConsistencyScorer:
    """
    E10 — Penalises internal contradictions within a single candidate
    and cross-candidate contradictions between highly confident outputs.
    """

    CONTRADICTION_PAIRS = [
        ("yes", "no"), ("true", "false"), ("safe", "unsafe"),
        ("approved", "rejected"), ("success", "failure"),
        ("possible", "impossible"), ("do", "don't"), ("will", "won't"),
        ("always", "never"), ("increase", "decrease"),
    ]

    def _detect_internal(self, text: str) -> int:
        """Count internal contradictions in a single output."""
        t = text.lower()
        count = 0
        for (a, b) in self.CONTRADICTION_PAIRS:
            if a in t and b in t:
                count += 1
        return count

    def score_batch(self, candidates: list[ScoredCandidate]) -> None:
        for cand in candidates:
            internal = self._detect_internal(cand.content)
            penalty = min(internal * 0.06, 0.30)
            score = max(0.0, 1.0 - penalty)
            cand.consistency = round(score, 4)
            cand.trace.append(f"E10:consist={score:.3f}(internal_contradictions={internal})")


# ─────────────────────────────────────────────
# E11 — Composite Grader
# ─────────────────────────────────────────────

class E11CompositeGrader:
    """
    E11 — Applies Emma composite scoring formula:
    final_score = (confidence*0.4) + (relevance*0.3) + (consistency*0.2) + (novelty*0.1)
    Also incorporates attention weight from the mesh attention engine.
    """

    W_CONF  = 0.4
    W_REL   = 0.3
    W_CONS  = 0.2
    W_NOV   = 0.1

    def grade(self, candidate: ScoredCandidate) -> float:
        # Fetch attention weight from engine if available
        node_weight = 1.0
        try:
            from mesh.attention import attention_engine
            node_weight = attention_engine.get_weight(candidate.agent_id)
        except Exception:
            pass

        base = (
            candidate.confidence  * self.W_CONF +
            candidate.relevance   * self.W_REL  +
            candidate.consistency * self.W_CONS +
            candidate.novelty     * self.W_NOV
        )
        # Blend attention weight: 80% base score, 20% attention weight influence
        composite = round(base * 0.80 + (base * node_weight * 0.20), 4)
        composite = min(composite, 1.0)
        candidate.composite = composite
        candidate.trace.append(
            f"E11:composite={composite:.4f}"
            f"(c={candidate.confidence:.2f},r={candidate.relevance:.2f},"
            f"cs={candidate.consistency:.2f},n={candidate.novelty:.2f},w={node_weight:.2f})"
        )
        return composite


# ─────────────────────────────────────────────
# E12 — Rank Filter
# ─────────────────────────────────────────────

class E12RankFilter:
    """
    E12 — Sorts candidates by composite score, prunes below PRUNE_THRESHOLD,
    returns top-k survivors.
    """

    def filter(
        self,
        candidates: list[ScoredCandidate],
        top_k: int = TOP_K_DEFAULT,
        prune_threshold: float = PRUNE_THRESHOLD,
    ) -> list[ScoredCandidate]:
        # Mark pruned
        for c in candidates:
            if c.composite < prune_threshold:
                c.pruned = True
                c.prune_reason = f"composite={c.composite:.4f}<threshold={prune_threshold}"

        survivors = [c for c in candidates if not c.pruned]

        # Sort by composite descending
        survivors.sort(key=lambda c: c.composite, reverse=True)

        # Assign ranks
        for i, c in enumerate(survivors):
            c.rank = i + 1

        top = survivors[:top_k]
        pruned_count = len(candidates) - len(survivors)
        logger.info(
            f"[E12] total={len(candidates)} pruned={pruned_count} "
            f"survivors={len(survivors)} top_k={len(top)}"
        )
        return top


# ─────────────────────────────────────────────
# Composite Evaluator Pipeline (E7-E12)
# ─────────────────────────────────────────────

class EmmaEvaluator:
    """
    Runs E7 → E8 → E9 → E10 → E11 → E12 on a batch of swarm outputs.
    Returns ranked, filtered ScoredCandidate list.
    """

    def __init__(self):
        self.e7  = E7ConfidenceScorer()
        self.e8  = E8RelevanceScorer()
        self.e9  = E9NoveltyScorer()
        self.e10 = E10ConsistencyScorer()
        self.e11 = E11CompositeGrader()
        self.e12 = E12RankFilter()

    def evaluate(
        self,
        swarm_outputs: list[dict[str, Any]],
        query: str,
        top_k: int = TOP_K_DEFAULT,
        prune_threshold: float = PRUNE_THRESHOLD,
    ) -> list[ScoredCandidate]:
        """
        Args:
            swarm_outputs: list of CandidateReasoning.to_dict() from swarm_runner
            query: original user query string
            top_k: max candidates to keep
        Returns:
            Ranked list of ScoredCandidate
        """
        if not swarm_outputs:
            logger.warning("[EmmaEvaluator] no swarm outputs to evaluate")
            return []

        # Build ScoredCandidate objects
        candidates: list[ScoredCandidate] = []
        for raw in swarm_outputs:
            sc = ScoredCandidate(
                agent_id       = raw.get("agent_id", "unknown"),
                agent_type     = raw.get("agent_type", "unknown"),
                content        = raw.get("content", ""),
                raw_confidence = float(raw.get("confidence", 0.5)),
            )
            candidates.append(sc)

        # E7 — confidence
        for c in candidates:
            self.e7.score(c)

        # E8 — relevance
        for c in candidates:
            self.e8.score(c, query)

        # E9 — novelty (batch, needs all candidates)
        self.e9.score_batch(candidates)

        # E10 — consistency (batch)
        self.e10.score_batch(candidates)

        # E11 — composite grade
        for c in candidates:
            self.e11.grade(c)

        # E12 — rank + filter
        top = self.e12.filter(candidates, top_k=top_k, prune_threshold=prune_threshold)

        logger.info(
            f"[EmmaEvaluator] query_len={len(query)} "
            f"input={len(candidates)} output={len(top)} "
            f"top_score={top[0].composite:.4f if top else 0}"
        )
        return top

    def evaluate_report(
        self,
        swarm_outputs: list[dict[str, Any]],
        query: str,
        top_k: int = TOP_K_DEFAULT,
    ) -> dict[str, Any]:
        """Full evaluation with summary report."""
        t0 = time.time()
        top = self.evaluate(swarm_outputs, query, top_k)
        elapsed = round(time.time() - t0, 4)
        return {
            "top_candidates": [c.to_dict() for c in top],
            "count":          len(top),
            "top_score":      top[0].composite if top else 0.0,
            "avg_score":      round(sum(c.composite for c in top) / max(len(top),1), 4),
            "eval_time_s":    elapsed,
            "query_preview":  query[:120],
        }


# Singleton
emma_evaluator = EmmaEvaluator()