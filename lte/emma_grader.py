"""
LTE Emma Grader — Lucy Telemetry Engine
Computes LTE scores for every Emma pipeline result.

LTE Formula:
  base = conf*40 + top_score*30 + (1-risk)*20 + routing*10
  deductions:
    - divergent consensus  : -8
    - block event          : -15
    - redact event         : -8
    - low novelty (<0.30)  : -5
    - high latency (>3s)   : -5
    - agent timeout        : -10
"""

from __future__ import annotations
import time
import math
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Deque
from collections import deque
import threading

# ── LTE Score Dataclass ────────────────────────────────────────────────────────

@dataclass
class LTEScore:
    raw: float                          # 0–100 float
    grade: str                          # S / A / B / C / D / F
    components: Dict[str, float]        # detailed breakdown
    deductions: Dict[str, float]        # applied deductions
    total_deductions: float
    consensus: str                      # strong / partial / divergent
    blocked: bool
    latency_ms: float
    timestamp: float = field(default_factory=time.time)
    session_id: Optional[str] = None
    query_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def healthy(self) -> bool:
        return self.raw >= 60.0

    @property
    def letter(self) -> str:
        return self.grade

# ── Grade Table ────────────────────────────────────────────────────────────────
_GRADE_TABLE = [
    (90, "S"),
    (80, "A"),
    (70, "B"),
    (55, "C"),
    (40, "D"),
    (0,  "F"),
]

def _assign_grade(raw: float) -> str:
    for threshold, letter in _GRADE_TABLE:
        if raw >= threshold:
            return letter
    return "F"

# ── LTE Emma Grader ────────────────────────────────────────────────────────────

class LTEEmmaGrader:
    """
    Converts an EmmaPipelineResult (or equivalent dict) into a typed LTEScore.

    Input keys expected (all optional with sane defaults):
      confidence      : float  0-1
      top_score       : float  0-1  (highest ranked agent score)
      risk            : float  0-1
      routing_quality : float  0-1  (fraction of preferred agents selected)
      consensus       : str    strong|partial|divergent
      blocked         : bool
      redacted        : bool
      novelty         : float  0-1
      latency_ms      : float
      agent_timeout   : bool
      session_id      : str
      query_id        : str
    """

    # Class constant only
    _HISTORY_MAX = 500

    def __init__(self) -> None:
        # Instance-level state — each instance is independent
        self._history: Deque[LTEScore] = deque(maxlen=self._HISTORY_MAX)
        self._lock = threading.Lock()
        self._total_scored: int = 0
        self._sum_raw: float = 0.0
        self._sum_healthy: int = 0
        self._grade_counts: Dict[str, int] = {g: 0 for _, g in _GRADE_TABLE}

    # ── Core scoring ──────────────────────────────────────────────────────────

    def grade(self, data: Dict[str, Any]) -> LTEScore:
        """Compute and record an LTE score from an Emma pipeline result dict."""
        start = time.perf_counter()

        # Extract signals with defaults
        confidence      = float(data.get("confidence", 0.50))
        top_score       = float(data.get("top_score", confidence))
        risk            = float(data.get("risk", 0.30))
        routing_quality = float(data.get("routing_quality", 0.80))
        consensus       = str(data.get("consensus", "partial"))
        blocked         = bool(data.get("blocked", False))
        redacted        = bool(data.get("redacted", False))
        novelty         = float(data.get("novelty", 0.50))
        latency_ms      = float(data.get("latency_ms", 0.0))
        agent_timeout   = bool(data.get("agent_timeout", False))
        session_id      = data.get("session_id")
        query_id        = data.get("query_id")

        # Clamp inputs
        confidence      = max(0.0, min(1.0, confidence))
        top_score       = max(0.0, min(1.0, top_score))
        risk            = max(0.0, min(1.0, risk))
        routing_quality = max(0.0, min(1.0, routing_quality))
        novelty         = max(0.0, min(1.0, novelty))

        # ── Base components ──────────────────────────────────────────────────
        comp_conf    = confidence      * 40.0
        comp_top     = top_score       * 30.0
        comp_risk    = (1.0 - risk)    * 20.0
        comp_routing = routing_quality * 10.0
        base         = comp_conf + comp_top + comp_risk + comp_routing

        components = {
            "confidence_x40":      round(comp_conf, 3),
            "top_score_x30":       round(comp_top, 3),
            "risk_inverse_x20":    round(comp_risk, 3),
            "routing_quality_x10": round(comp_routing, 3),
            "base":                round(base, 3),
        }

        # ── Deductions ───────────────────────────────────────────────────────
        deductions: Dict[str, float] = {}

        if consensus == "divergent":
            deductions["divergent_consensus"] = -8.0
        if blocked:
            deductions["block_event"] = -15.0
        if redacted:
            deductions["redact_event"] = -8.0
        if novelty < 0.30:
            deductions["low_novelty"] = -5.0
        if latency_ms > 3000.0:
            deductions["high_latency"] = -5.0
        if agent_timeout:
            deductions["agent_timeout"] = -10.0

        total_deductions = sum(deductions.values())
        raw = max(0.0, min(100.0, base + total_deductions))

        grade_letter = _assign_grade(raw)

        score = LTEScore(
            raw=round(raw, 3),
            grade=grade_letter,
            components=components,
            deductions=deductions,
            total_deductions=round(total_deductions, 3),
            consensus=consensus,
            blocked=blocked,
            latency_ms=round(latency_ms, 2),
            timestamp=time.time(),
            session_id=str(session_id) if session_id else None,
            query_id=str(query_id) if query_id else None,
        )

        # Record
        self._record(score)
        return score

    # ── Recording ─────────────────────────────────────────────────────────────

    def _record(self, score: LTEScore) -> None:
        with self._lock:
            self._history.append(score)
            self._total_scored += 1
            self._sum_raw      += score.raw
            if score.healthy:
                self._sum_healthy += 1
            self._grade_counts[score.grade] = self._grade_counts.get(score.grade, 0) + 1

    # ── Statistics ────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            n = self._total_scored
            return {
                "total_scored":    n,
                "avg_lte":         round(self._sum_raw / n, 3) if n else 0.0,
                "health_rate":     round(self._sum_healthy / n, 3) if n else 0.0,
                "grade_counts":    dict(self._grade_counts),
                "history_length":  len(self._history),
            }

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._history)[-limit:]
        return [s.to_dict() for s in reversed(items)]

    def session_scores(self, session_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            items = [s for s in self._history if s.session_id == session_id]
        return [s.to_dict() for s in items]

    def session_avg(self, session_id: str) -> float:
        items = [s for s in self._history if s.session_id == session_id]
        if not items:
            return 0.0
        return round(sum(s.raw for s in items) / len(items), 3)

    def trend(self, window: int = 50) -> Dict[str, Any]:
        """Rolling trend over last `window` scores."""
        with self._lock:
            recent_scores = list(self._history)[-window:]
        if not recent_scores:
            return {"trend": "none", "delta": 0.0, "window": window}
        half = max(1, len(recent_scores) // 2)
        early = sum(s.raw for s in recent_scores[:half]) / half
        late  = sum(s.raw for s in recent_scores[half:]) / max(1, len(recent_scores) - half)
        delta = round(late - early, 3)
        trend = "improving" if delta > 2 else ("declining" if delta < -2 else "stable")
        return {
            "trend": trend,
            "delta": delta,
            "early_avg": round(early, 3),
            "late_avg":  round(late, 3),
            "window":    window,
        }

    def percentile(self, p: float) -> float:
        """Return the p-th percentile LTE score (0–100)."""
        with self._lock:
            scores = sorted(s.raw for s in self._history)
        if not scores:
            return 0.0
        idx = max(0, int(math.ceil(p / 100.0 * len(scores))) - 1)
        return round(scores[idx], 3)

    def grade_distribution(self) -> Dict[str, float]:
        """Return grade distribution as percentages."""
        with self._lock:
            n = self._total_scored
            counts = dict(self._grade_counts)
        if n == 0:
            return {g: 0.0 for _, g in _GRADE_TABLE}
        return {g: round(counts.get(g, 0) / n * 100, 2) for _, g in _GRADE_TABLE}

    def health_snapshot(self) -> Dict[str, Any]:
        """Quick health summary for dashboard."""
        s = self.stats()
        t = self.trend()
        return {
            "avg_lte":        s["avg_lte"],
            "health_rate_pct": round(s["health_rate"] * 100, 1),
            "trend":          t["trend"],
            "trend_delta":    t["delta"],
            "grade_dist":     self.grade_distribution(),
            "total_graded":   s["total_scored"],
            "p50":            self.percentile(50),
            "p90":            self.percentile(90),
        }


# ── Singleton ──────────────────────────────────────────────────────────────────
lte_grader = LTEEmmaGrader()


# ── Convenience function ───────────────────────────────────────────────────────
def grade_emma_result(data: Dict[str, Any]) -> LTEScore:
    """Module-level convenience wrapper."""
    return lte_grader.grade(data)