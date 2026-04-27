"""
Emma Supervisory Mesh — Auditor Layer (E21-E24)
E21: DecisionLogger   — records every Emma pipeline decision to audit log
E22: TraceExplainer   — generates human-readable explanation from trace data
E23: AnomalyDetector  — flags unusual patterns across recent audit entries
E24: AuditReporter    — produces structured audit report + LTE scoring signal
"""

from __future__ import annotations
import time
import uuid
import threading
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("emma.auditor")

MAX_AUDIT_HISTORY   = 500
ANOMALY_WINDOW      = 20    # last N entries to scan for anomalies
BLOCK_RATE_ALERT    = 0.25  # >25% block rate in window → anomaly
CONF_DROP_ALERT     = 0.45  # avg merged_confidence < this → anomaly
DIVERGE_RATE_ALERT  = 0.40  # >40% divergent consensus in window → anomaly


@dataclass
class AuditEntry:
    """Full record of one Emma pipeline run."""
    audit_id:          str   = field(default_factory=lambda: str(uuid.uuid4())[:12])
    session_id:        str   = "default"
    query_preview:     str   = ""

    # Routing
    domain:            str   = "general"
    urgency:           str   = "medium"
    selected_agents:   list[str] = field(default_factory=list)
    routing_score:     float = 0.0

    # Evaluation
    candidate_count:   int   = 0
    top_score:         float = 0.0
    avg_score:         float = 0.0

    # Merge
    merge_strategy:    str   = ""
    merged_confidence: float = 0.0
    consensus:         str   = "none"
    consensus_ratio:   float = 0.0
    divergence_count:  int   = 0

    # Safety
    safety_verdict:    str   = "PASS"
    risk_tier:         str   = "low"
    risk_score:        float = 0.0
    content_flags:     list[str] = field(default_factory=list)
    bias_flags:        list[str] = field(default_factory=list)

    # Pipeline meta
    pipeline_ms:       float = 0.0
    lte_score:         float = 0.0
    timestamp:         float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "audit_id":          self.audit_id,
            "session_id":        self.session_id,
            "query_preview":     self.query_preview,
            "domain":            self.domain,
            "urgency":           self.urgency,
            "selected_agents":   self.selected_agents,
            "routing_score":     round(self.routing_score, 4),
            "candidate_count":   self.candidate_count,
            "top_score":         round(self.top_score, 4),
            "avg_score":         round(self.avg_score, 4),
            "merge_strategy":    self.merge_strategy,
            "merged_confidence": round(self.merged_confidence, 4),
            "consensus":         self.consensus,
            "consensus_ratio":   round(self.consensus_ratio, 4),
            "divergence_count":  self.divergence_count,
            "safety_verdict":    self.safety_verdict,
            "risk_tier":         self.risk_tier,
            "risk_score":        round(self.risk_score, 4),
            "content_flags":     self.content_flags,
            "bias_flags":        self.bias_flags,
            "pipeline_ms":       round(self.pipeline_ms, 2),
            "lte_score":         round(self.lte_score, 4),
            "timestamp":         self.timestamp,
        }


# ─────────────────────────────────────────────
# E21 — Decision Logger
# ─────────────────────────────────────────────

class E21DecisionLogger:
    """
    E21 — Thread-safe rolling audit log of all Emma pipeline decisions.
    Persists to DeltaVault on high-risk or block events.
    """

    def __init__(self):
        self._log: deque[AuditEntry] = deque(maxlen=MAX_AUDIT_HISTORY)
        self._lock = threading.RLock()

    def record(self, entry: AuditEntry) -> None:
        with self._lock:
            self._log.append(entry)

        # Persist critical decisions to DeltaVault
        if entry.safety_verdict in ("BLOCK", "REDACT") or entry.risk_tier in ("high", "critical"):
            self._vault_write(entry)

        logger.debug(
            f"[E21] audit_id={entry.audit_id} verdict={entry.safety_verdict} "
            f"risk={entry.risk_tier} lte={entry.lte_score:.3f}"
        )

    def _vault_write(self, entry: AuditEntry) -> None:
        try:
            from unr5.delta_vault import delta_vault
            delta_vault.append_approved(
                action_type = f"emma_audit_{entry.safety_verdict.lower()}",
                payload     = {
                    "audit_id":       entry.audit_id,
                    "session_id":     entry.session_id,
                    "risk_tier":      entry.risk_tier,
                    "risk_score":     entry.risk_score,
                    "content_flags":  entry.content_flags,
                    "consensus":      entry.consensus,
                },
                approved_by = "E21_DecisionLogger",
            )
        except Exception as e:
            logger.warning(f"[E21] vault_write failed: {e}")

    def get_recent(self, n: int = 20) -> list[AuditEntry]:
        with self._lock:
            entries = list(self._log)
        return entries[-n:]

    def get_all(self) -> list[AuditEntry]:
        with self._lock:
            return list(self._log)

    def stats(self) -> dict:
        with self._lock:
            entries = list(self._log)
        if not entries:
            return {"total": 0}
        verdicts = [e.safety_verdict for e in entries]
        tiers    = [e.risk_tier for e in entries]
        return {
            "total":         len(entries),
            "pass":          verdicts.count("PASS"),
            "redact":        verdicts.count("REDACT"),
            "block":         verdicts.count("BLOCK"),
            "low_risk":      tiers.count("low"),
            "medium_risk":   tiers.count("medium"),
            "high_risk":     tiers.count("high"),
            "critical_risk": tiers.count("critical"),
            "avg_lte":       round(sum(e.lte_score for e in entries) / len(entries), 4),
            "avg_conf":      round(sum(e.merged_confidence for e in entries) / len(entries), 4),
        }


# ─────────────────────────────────────────────
# E22 — Trace Explainer
# ─────────────────────────────────────────────

class E22TraceExplainer:
    """
    E22 — Converts raw trace lists into human-readable explanations.
    Used to produce the 'reasoning_summary' field for Lucy Prime and the dashboard.
    """

    def explain(self, entry: AuditEntry, aggregated_traces: list[str]) -> str:
        lines: list[str] = []

        lines.append(f"# Emma Audit Explanation — {entry.audit_id}")
        lines.append(f"**Session**: {entry.session_id}  |  **Query**: {entry.query_preview}")
        lines.append("")

        # Routing summary
        lines.append(f"## Routing (E1-E6)")
        lines.append(
            f"Domain `{entry.domain}` | Urgency `{entry.urgency}` | "
            f"Agents selected: {entry.selected_agents} | "
            f"Routing score: {entry.routing_score:.3f}"
        )
        lines.append("")

        # Evaluation summary
        lines.append(f"## Evaluation (E7-E12)")
        lines.append(
            f"Candidates: {entry.candidate_count} | "
            f"Top score: {entry.top_score:.4f} | "
            f"Avg score: {entry.avg_score:.4f}"
        )
        lines.append("")

        # Merge summary
        lines.append(f"## Merge (E13-E16)")
        lines.append(
            f"Strategy: `{entry.merge_strategy}` | "
            f"Confidence: {entry.merged_confidence:.4f} | "
            f"Consensus: `{entry.consensus}` ({entry.consensus_ratio:.3f}) | "
            f"Divergences: {entry.divergence_count}"
        )
        lines.append("")

        # Safety summary
        lines.append(f"## Safety (E17-E20)")
        lines.append(
            f"**Verdict**: `{entry.safety_verdict}` | "
            f"Risk: `{entry.risk_tier}` ({entry.risk_score:.4f}) | "
            f"Content flags: {entry.content_flags} | "
            f"Bias flags: {entry.bias_flags}"
        )
        lines.append("")

        # LTE score
        lines.append(f"## LTE Score")
        lines.append(f"**{entry.lte_score:.1f} / 100** (pipeline_ms={entry.pipeline_ms:.1f}ms)")
        lines.append("")

        # Raw traces
        if aggregated_traces:
            lines.append("## Raw Node Traces")
            for t in aggregated_traces[:30]:
                lines.append(f"  {t}")

        return "\n".join(lines)

    def short_summary(self, entry: AuditEntry) -> str:
        return (
            f"[{entry.audit_id}] domain={entry.domain} urgency={entry.urgency} "
            f"agents={len(entry.selected_agents)} consensus={entry.consensus} "
            f"verdict={entry.safety_verdict} risk={entry.risk_tier} "
            f"lte={entry.lte_score:.1f}"
        )


# ─────────────────────────────────────────────
# E23 — Anomaly Detector
# ─────────────────────────────────────────────

class E23AnomalyDetector:
    """
    E23 — Scans rolling audit window for systemic anomalies.
    Raises alerts that feed into Sentinel and dashboard.
    """

    def detect(self, recent: list[AuditEntry]) -> list[dict]:
        anomalies: list[dict] = []
        n = len(recent)
        if n < 3:
            return anomalies

        # Block rate anomaly
        block_count = sum(1 for e in recent if e.safety_verdict == "BLOCK")
        block_rate  = block_count / n
        if block_rate >= BLOCK_RATE_ALERT:
            anomalies.append({
                "type":     "high_block_rate",
                "value":    round(block_rate, 4),
                "threshold": BLOCK_RATE_ALERT,
                "message":  f"Block rate {block_rate:.1%} in last {n} runs exceeds {BLOCK_RATE_ALERT:.0%}",
            })

        # Confidence drop anomaly
        avg_conf = sum(e.merged_confidence for e in recent) / n
        if avg_conf < CONF_DROP_ALERT:
            anomalies.append({
                "type":     "confidence_drop",
                "value":    round(avg_conf, 4),
                "threshold": CONF_DROP_ALERT,
                "message":  f"Avg merged confidence {avg_conf:.3f} below threshold {CONF_DROP_ALERT}",
            })

        # Divergence rate anomaly
        diverge_count = sum(1 for e in recent if e.consensus == "divergent")
        diverge_rate  = diverge_count / n
        if diverge_rate >= DIVERGE_RATE_ALERT:
            anomalies.append({
                "type":     "high_divergence",
                "value":    round(diverge_rate, 4),
                "threshold": DIVERGE_RATE_ALERT,
                "message":  f"Divergence rate {diverge_rate:.1%} in last {n} runs",
            })

        # LTE score drop
        avg_lte = sum(e.lte_score for e in recent) / n
        if avg_lte < 40.0:
            anomalies.append({
                "type":     "lte_score_degradation",
                "value":    round(avg_lte, 2),
                "threshold": 40.0,
                "message":  f"Avg LTE score {avg_lte:.1f} below healthy threshold 40",
            })

        # Pipeline latency spike
        avg_ms = sum(e.pipeline_ms for e in recent) / n
        if avg_ms > 5000:
            anomalies.append({
                "type":     "pipeline_latency_spike",
                "value":    round(avg_ms, 1),
                "threshold": 5000,
                "message":  f"Avg pipeline latency {avg_ms:.0f}ms exceeds 5000ms threshold",
            })

        if anomalies:
            logger.warning(f"[E23] {len(anomalies)} anomalies detected: {[a['type'] for a in anomalies]}")

        return anomalies


# ─────────────────────────────────────────────
# E24 — Audit Reporter
# ─────────────────────────────────────────────

class E24AuditReporter:
    """
    E24 — Produces structured audit reports + LTE scoring signal.

    LTE Score formula (0-100):
    base = merged_confidence * 40
         + top_score * 30
         + (1 - risk_score) * 20
         + routing_score * 10
    deductions: divergent consensus -5, REDACT -3, BLOCK -15, each content_flag -2
    """

    def compute_lte_score(self, entry: AuditEntry) -> float:
        base = (
            entry.merged_confidence * 40.0 +
            entry.top_score         * 30.0 +
            (1.0 - entry.risk_score) * 20.0 +
            entry.routing_score     * 10.0
        )
        deductions = 0.0
        if entry.consensus == "divergent":
            deductions += 5.0
        if entry.safety_verdict == "REDACT":
            deductions += 3.0
        elif entry.safety_verdict == "BLOCK":
            deductions += 15.0
        deductions += len(entry.content_flags) * 2.0
        deductions += len(entry.bias_flags)    * 1.0

        score = max(0.0, min(100.0, base - deductions))
        return round(score, 2)

    def build_report(
        self,
        entry:       AuditEntry,
        anomalies:   list[dict],
        explanation: str,
    ) -> dict[str, Any]:
        return {
            "audit_id":    entry.audit_id,
            "lte_score":   entry.lte_score,
            "entry":       entry.to_dict(),
            "anomalies":   anomalies,
            "explanation": explanation,
            "generated_at": time.time(),
        }

    def summary_stats(self, logger_stats: dict) -> dict[str, Any]:
        """Wrap logger stats for dashboard."""
        return {
            "audit_summary": logger_stats,
            "health": (
                "healthy"   if logger_stats.get("block", 0) == 0 and logger_stats.get("avg_lte", 50) >= 60 else
                "degraded"  if logger_stats.get("avg_lte", 50) >= 40 else
                "critical"
            ),
        }


# ─────────────────────────────────────────────
# Composite Auditor Pipeline (E21-E24)
# ─────────────────────────────────────────────

class EmmaAuditor:
    """
    Runs E21 → E22 → E23 → E24.
    Accepts all upstream pipeline outputs, produces final AuditEntry + report.
    """

    def __init__(self):
        self.e21 = E21DecisionLogger()
        self.e22 = E22TraceExplainer()
        self.e23 = E23AnomalyDetector()
        self.e24 = E24AuditReporter()

    def audit(
        self,
        session_id:        str,
        query:             str,
        routing_result:    dict,
        eval_result:       dict,
        merge_result:      dict,
        safety_result:     dict,
        aggregated_traces: list[str],
        pipeline_start_ts: float,
    ) -> dict[str, Any]:
        """
        Builds AuditEntry, computes LTE score, detects anomalies, explains trace.
        Returns full audit report dict.
        """
        pipeline_ms = round((time.time() - pipeline_start_ts) * 1000, 2)

        entry = AuditEntry(
            session_id        = session_id,
            query_preview     = query[:120],
            # Routing
            domain            = routing_result.get("domain", "general"),
            urgency           = routing_result.get("urgency", "medium"),
            selected_agents   = routing_result.get("selected_agents", []),
            routing_score     = routing_result.get("routing_score", 0.0),
            # Eval
            candidate_count   = eval_result.get("count", 0),
            top_score         = eval_result.get("top_score", 0.0),
            avg_score         = eval_result.get("avg_score", 0.0),
            # Merge
            merge_strategy    = merge_result.get("merge_strategy", ""),
            merged_confidence = merge_result.get("merged_confidence", 0.0),
            consensus         = merge_result.get("consensus", "none"),
            consensus_ratio   = merge_result.get("consensus_ratio", 0.0),
            divergence_count  = len(merge_result.get("divergence_notes", [])),
            # Safety
            safety_verdict    = safety_result.get("verdict", "PASS"),
            risk_tier         = safety_result.get("risk_tier", "low"),
            risk_score        = safety_result.get("risk_score", 0.0),
            content_flags     = safety_result.get("content_flags", []),
            bias_flags        = safety_result.get("bias_flags", []),
            pipeline_ms       = pipeline_ms,
        )

        # E24 — LTE score
        entry.lte_score = self.e24.compute_lte_score(entry)

        # E21 — log
        self.e21.record(entry)

        # E22 — explain
        explanation = self.e22.explain(entry, aggregated_traces)

        # E23 — anomaly detection on recent window
        recent   = self.e21.get_recent(ANOMALY_WINDOW)
        anomalies = self.e23.detect(recent)

        # E24 — build report
        report = self.e24.build_report(entry, anomalies, explanation)

        # Emit audit event to mesh bus
        try:
            from mesh.event_bus import event_bus, make_event
            event_bus.publish_sync(make_event(
                source  = "E24",
                event   = "emma_audit_complete",
                payload = {
                    "audit_id":  entry.audit_id,
                    "lte_score": entry.lte_score,
                    "verdict":   entry.safety_verdict,
                    "anomalies": len(anomalies),
                },
            ))
        except Exception as e:
            logger.debug(f"[E24] bus emit skipped: {e}")

        logger.info(
            f"[EmmaAuditor] audit_id={entry.audit_id} "
            f"lte={entry.lte_score:.1f} verdict={entry.safety_verdict} "
            f"anomalies={len(anomalies)} ms={pipeline_ms:.0f}"
        )
        return report

    def get_stats(self) -> dict[str, Any]:
        stats = self.e21.stats()
        return self.e24.summary_stats(stats)

    def get_recent_entries(self, n: int = 10) -> list[dict]:
        return [e.to_dict() for e in self.e21.get_recent(n)]


# Singleton
emma_auditor = EmmaAuditor()