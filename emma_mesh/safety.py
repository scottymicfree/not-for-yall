"""
Emma Supervisory Mesh — Safety Filter Layer (E17-E20)
E17: ContentSafetyFilter  — screens merged content for harmful/prohibited material
E18: BiasDetector         — identifies cognitive and factual bias patterns
E19: RiskClassifier       — assigns risk tier (low/medium/high/critical) to merged output
E20: SafetyGate           — final pass/block/redact decision before Lucy Prime
"""

from __future__ import annotations
import re
import time
import logging
from dataclasses import dataclass, field
from typing import Any

from emma_mesh.merger import MergedReasoning

logger = logging.getLogger("emma.safety")

# ─────────────────────────────────────────────
# Thresholds
# ─────────────────────────────────────────────
BLOCK_THRESHOLD   = 0.80   # risk_score >= this → BLOCK
REDACT_THRESHOLD  = 0.55   # risk_score >= this → REDACT
PASS_THRESHOLD    = 0.55   # risk_score < this  → PASS


@dataclass
class SafetyReport:
    """Output of E17-E20 safety pipeline."""
    safe:              bool  = True
    verdict:           str   = "PASS"          # "PASS" | "REDACT" | "BLOCK"
    risk_tier:         str   = "low"           # "low" | "medium" | "high" | "critical"
    risk_score:        float = 0.0
    content_flags:     list[str] = field(default_factory=list)
    bias_flags:        list[str] = field(default_factory=list)
    redacted_content:  str   = ""
    block_reason:      str   = ""
    override_allowed:  bool  = True
    trace:             list[str] = field(default_factory=list)
    timestamp:         float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "safe":             self.safe,
            "verdict":          self.verdict,
            "risk_tier":        self.risk_tier,
            "risk_score":       round(self.risk_score, 4),
            "content_flags":    self.content_flags,
            "bias_flags":       self.bias_flags,
            "redacted_content": self.redacted_content[:300] if self.redacted_content else "",
            "block_reason":     self.block_reason,
            "override_allowed": self.override_allowed,
            "trace":            self.trace,
            "timestamp":        self.timestamp,
        }


# ─────────────────────────────────────────────
# E17 — Content Safety Filter
# ─────────────────────────────────────────────

class E17ContentSafetyFilter:
    """
    E17 — Screens merged content for harmful, prohibited, or sensitive material.
    Uses keyword/pattern matching + injection detection.
    Does NOT make final decisions — produces flag list for E20.
    """

    # Pattern categories → (patterns, severity)
    PATTERN_RULES: list[tuple[str, list[str], float]] = [
        ("injection_attempt",   [r"ignore previous", r"ignore all instructions",
                                  r"you are now", r"disregard your",
                                  r"system prompt", r"jailbreak"], 0.90),
        ("harmful_intent",      [r"\bharm\b.*\bpeople\b", r"\bkill\b.*\bhuman",
                                  r"\bweapon\b.*\bcreate\b", r"\bbomb\b"], 0.85),
        ("data_exfiltration",   [r"send.*password", r"leak.*credentials",
                                  r"exfiltrate.*data", r"steal.*api.?key"], 0.80),
        ("self_modification",   [r"rewrite.*your.*code", r"modify.*your.*instructions",
                                  r"override.*safety", r"disable.*filter"], 0.75),
        ("sensitive_pii",       [r"\bssn\b", r"social security", r"credit card.*\d{4}",
                                  r"passport.*number"], 0.60),
        ("deception_signal",    [r"pretend you are", r"act as if you have no",
                                  r"roleplay as an ai with no restrictions"], 0.70),
    ]

    def scan(self, content: str) -> tuple[list[str], float]:
        """Returns (flags, max_severity)."""
        text = content.lower()
        flags: list[str] = []
        max_sev = 0.0

        for category, patterns, severity in self.PATTERN_RULES:
            for pat in patterns:
                if re.search(pat, text):
                    flags.append(f"{category}(sev={severity})")
                    max_sev = max(max_sev, severity)
                    break  # one flag per category

        logger.debug(f"[E17] flags={flags} max_sev={max_sev}")
        return flags, max_sev


# ─────────────────────────────────────────────
# E18 — Bias Detector
# ─────────────────────────────────────────────

class E18BiasDetector:
    """
    E18 — Identifies cognitive and factual bias patterns in merged reasoning.
    Produces bias flags as informational metadata, not hard blocks.
    """

    BIAS_PATTERNS: list[tuple[str, list[str], float]] = [
        ("confirmation_bias",   [r"as (i|we) (already|always) (said|knew|expected)",
                                  r"this confirms"], 0.30),
        ("overgeneralization",  [r"\balways\b.*\bnever\b", r"everyone knows",
                                  r"all .{1,20} are", r"nobody ever"], 0.25),
        ("false_certainty",     [r"definitely", r"absolutely certain",
                                  r"100% sure", r"guaranteed to"], 0.20),
        ("anchoring_bias",      [r"based on the (first|initial|original)",
                                  r"as mentioned (first|earlier|at the start)"], 0.15),
        ("appeal_to_authority", [r"experts (all )?agree", r"science (has )?proven",
                                  r"studies show"], 0.10),
    ]

    def scan(self, content: str) -> tuple[list[str], float]:
        text = content.lower()
        flags: list[str] = []
        total_bias = 0.0

        for bias_type, patterns, weight in self.BIAS_PATTERNS:
            for pat in patterns:
                if re.search(pat, text):
                    flags.append(f"{bias_type}(w={weight})")
                    total_bias += weight
                    break

        total_bias = min(total_bias, 1.0)
        logger.debug(f"[E18] bias_flags={flags} total={total_bias}")
        return flags, total_bias


# ─────────────────────────────────────────────
# E19 — Risk Classifier
# ─────────────────────────────────────────────

class E19RiskClassifier:
    """
    E19 — Assigns composite risk score and tier to merged output.
    Combines: content severity, bias load, consensus divergence, confidence level.
    """

    def classify(
        self,
        content_severity: float,
        bias_load:         float,
        merged_confidence: float,
        consensus:         str,
        divergence_count:  int,
    ) -> tuple[str, float]:
        """Returns (risk_tier, risk_score)."""

        # Base risk from content flags
        base = content_severity * 0.50

        # Bias contribution
        base += bias_load * 0.15

        # Low confidence = higher uncertainty risk
        conf_risk = (1.0 - merged_confidence) * 0.20
        base += conf_risk

        # Consensus risk
        consensus_risk = {
            "strong":    0.00,
            "partial":   0.05,
            "divergent": 0.15,
            "none":      0.10,
        }.get(consensus, 0.10)
        base += consensus_risk

        # Divergence count penalty
        base += min(divergence_count * 0.02, 0.10)

        risk_score = min(round(base, 4), 1.0)

        if risk_score >= 0.80:
            tier = "critical"
        elif risk_score >= 0.55:
            tier = "high"
        elif risk_score >= 0.30:
            tier = "medium"
        else:
            tier = "low"

        logger.debug(f"[E19] risk_score={risk_score} tier={tier}")
        return tier, risk_score


# ─────────────────────────────────────────────
# E20 — Safety Gate
# ─────────────────────────────────────────────

class E20SafetyGate:
    """
    E20 — Final pass/block/redact decision.
    BLOCK:  risk_score >= 0.80 → content is suppressed, reason logged
    REDACT: risk_score >= 0.55 → sensitive fragments removed, passes with warning
    PASS:   risk_score < 0.55  → forwarded unchanged to Lucy Prime

    Redaction replaces flagged pattern matches with [REDACTED].
    Override is NEVER allowed on BLOCK — only Emma/Eagle Eye can release.
    """

    REDACT_PATTERNS = [
        r"\bssn\b[\s:]*[\d\-]{9,11}",
        r"credit card[\s:]*[\d\s\-]{13,19}",
        r"password[\s:=]+\S+",
        r"api.?key[\s:=]+\S+",
        r"secret[\s:=]+\S+",
    ]

    def _redact(self, content: str) -> str:
        result = content
        for pat in self.REDACT_PATTERNS:
            result = re.sub(pat, "[REDACTED]", result, flags=re.IGNORECASE)
        return result

    def gate(
        self,
        merged: MergedReasoning,
        risk_tier:      str,
        risk_score:     float,
        content_flags:  list[str],
        bias_flags:     list[str],
        report:         SafetyReport,
    ) -> SafetyReport:

        report.risk_tier     = risk_tier
        report.risk_score    = risk_score
        report.content_flags = content_flags
        report.bias_flags    = bias_flags

        if risk_score >= BLOCK_THRESHOLD:
            report.safe             = False
            report.verdict          = "BLOCK"
            report.override_allowed = False
            report.block_reason     = (
                f"risk_score={risk_score:.4f}>={BLOCK_THRESHOLD} "
                f"flags={content_flags}"
            )
            report.redacted_content = ""
            report.trace.append(f"E20:BLOCK reason={report.block_reason}")
            logger.warning(f"[E20] BLOCK: {report.block_reason}")

        elif risk_score >= REDACT_THRESHOLD:
            report.safe             = True
            report.verdict          = "REDACT"
            report.override_allowed = True
            report.redacted_content = self._redact(merged.merged_content)
            report.trace.append(
                f"E20:REDACT risk={risk_score:.4f} bias_flags={len(bias_flags)}"
            )
            logger.info(f"[E20] REDACT: risk={risk_score:.4f}")

        else:
            report.safe             = True
            report.verdict          = "PASS"
            report.override_allowed = True
            report.redacted_content = merged.merged_content
            report.trace.append(f"E20:PASS risk={risk_score:.4f}")
            logger.debug(f"[E20] PASS: risk={risk_score:.4f}")

        return report


# ─────────────────────────────────────────────
# Composite Safety Pipeline (E17-E20)
# ─────────────────────────────────────────────

class EmmaSafety:
    """
    Runs E17 → E18 → E19 → E20 on a MergedReasoning package.
    Returns a SafetyReport with verdict + (optionally) redacted content.
    """

    def __init__(self):
        self.e17 = E17ContentSafetyFilter()
        self.e18 = E18BiasDetector()
        self.e19 = E19RiskClassifier()
        self.e20 = E20SafetyGate()

    def evaluate(self, merged: MergedReasoning) -> SafetyReport:
        report = SafetyReport()
        content = merged.merged_content

        # E17 — content safety
        content_flags, content_sev = self.e17.scan(content)
        report.trace.append(f"E17:flags={content_flags} sev={content_sev:.3f}")

        # E18 — bias detection
        bias_flags, bias_load = self.e18.scan(content)
        report.trace.append(f"E18:bias={bias_flags} load={bias_load:.3f}")

        # E19 — risk classification
        risk_tier, risk_score = self.e19.classify(
            content_severity   = content_sev,
            bias_load          = bias_load,
            merged_confidence  = merged.merged_confidence,
            consensus          = merged.consensus,
            divergence_count   = len(merged.divergence_notes),
        )
        report.trace.append(f"E19:tier={risk_tier} score={risk_score:.4f}")

        # E20 — gate decision
        report = self.e20.gate(
            merged        = merged,
            risk_tier     = risk_tier,
            risk_score    = risk_score,
            content_flags = content_flags,
            bias_flags    = bias_flags,
            report        = report,
        )

        logger.info(
            f"[EmmaSafety] verdict={report.verdict} "
            f"risk={risk_tier}({risk_score:.4f}) "
            f"content_flags={len(content_flags)} bias_flags={len(bias_flags)}"
        )
        return report

    def evaluate_report(self, merged: MergedReasoning) -> dict[str, Any]:
        t0 = time.time()
        sr = self.evaluate(merged)
        elapsed = round(time.time() - t0, 4)
        d = sr.to_dict()
        d["eval_time_s"] = elapsed
        return d


# Singleton
emma_safety = EmmaSafety()