"""
Safety Global Layer — Policy Engine (S1-S4)
S1: PolicyRegistry    — stores all named policy rules with weights + decay
S2: ConstraintEngine  — evaluates actions against hard and soft constraints
S3: BiasAuditor       — cross-system bias pattern auditing
S4: RiskScorer        — aggregates multi-signal risk score for any action
"""

from __future__ import annotations
import time
import threading
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("safety.policy")

BLOCK_THRESHOLD  = 0.80
PRUNE_THRESHOLD  = 0.70
DECAY_RATE       = 0.98     # per-tick weight decay toward baseline
BASELINE_WEIGHT  = 1.0


@dataclass
class PolicyRule:
    """A named safety policy rule."""
    rule_id:      str
    name:         str
    category:     str          # "hard" | "soft" | "monitor"
    description:  str
    weight:       float        # gravity weight 0.0–2.0
    threshold:    float        # activation threshold
    active:       bool         = True
    decay:        float        = DECAY_RATE
    triggered_n:  int          = 0
    last_triggered: float      = 0.0
    created_at:   float        = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "rule_id":        self.rule_id,
            "name":           self.name,
            "category":       self.category,
            "description":    self.description,
            "weight":         round(self.weight, 4),
            "threshold":      self.threshold,
            "active":         self.active,
            "triggered_n":    self.triggered_n,
        }


# ─────────────────────────────────────────────
# S1 — Policy Registry
# ─────────────────────────────────────────────

class S1PolicyRegistry:
    """
    S1 — Central registry of all safety policy rules.
    Rules are weighted; weights decay toward baseline between triggers.
    PolicyGravityLayer: BLOCK_THRESHOLD=0.80, PRUNE_THRESHOLD=0.70
    """

    DEFAULT_RULES: list[dict] = [
        # Hard constraints — always enforced
        {"rule_id": "S1-H01", "name": "no_self_modification",    "category": "hard",    "weight": 2.0, "threshold": 0.0,  "description": "Block any attempt to modify Lucy's own core code or instructions"},
        {"rule_id": "S1-H02", "name": "no_injection_bypass",     "category": "hard",    "weight": 2.0, "threshold": 0.0,  "description": "Block prompt injection and jailbreak attempts"},
        {"rule_id": "S1-H03", "name": "no_credential_exfil",     "category": "hard",    "weight": 2.0, "threshold": 0.0,  "description": "Block any operation that exfiltrates credentials or PII"},
        {"rule_id": "S1-H04", "name": "bioyth0n_gate",           "category": "hard",    "weight": 2.0, "threshold": 0.0,  "description": "Bioyth0n executes only Eagle Eye trusted + Emma approved operations"},
        {"rule_id": "S1-H05", "name": "deltavault_immutability",  "category": "hard",    "weight": 2.0, "threshold": 0.0,  "description": "DeltaVault entries are never deleted or modified"},
        # Soft constraints — weighted enforcement
        {"rule_id": "S1-S01", "name": "operator_visibility",     "category": "soft",    "weight": 1.2, "threshold": 0.55, "description": "Medium/high risk actions require operatorVisible=True"},
        {"rule_id": "S1-S02", "name": "confidence_floor",        "category": "soft",    "weight": 1.1, "threshold": 0.65, "description": "Actions require Eagle Eye confidence >= 0.65"},
        {"rule_id": "S1-S03", "name": "emma_approval_required",  "category": "soft",    "weight": 1.3, "threshold": 0.55, "description": "Write/execute actions require Emma approval"},
        {"rule_id": "S1-S04", "name": "human_approval_high_risk","category": "soft",    "weight": 1.5, "threshold": 0.70, "description": "High-risk operations require human approval"},
        # Monitor — informational flags
        {"rule_id": "S1-M01", "name": "monitor_earth_signals",   "category": "monitor", "weight": 0.5, "threshold": 0.30, "description": "Flag unusual Earth signal combinations"},
        {"rule_id": "S1-M02", "name": "monitor_fivem_anomaly",   "category": "monitor", "weight": 0.5, "threshold": 0.30, "description": "Flag unusual FiveM server state"},
        {"rule_id": "S1-M03", "name": "monitor_lte_degradation", "category": "monitor", "weight": 0.6, "threshold": 0.40, "description": "Alert when LTE score drops below threshold"},
        {"rule_id": "S1-M04", "name": "monitor_consensus_drift", "category": "monitor", "weight": 0.6, "threshold": 0.40, "description": "Alert when swarm consensus diverges repeatedly"},
    ]

    def __init__(self):
        self._rules: dict[str, PolicyRule] = {}
        self._lock = threading.RLock()
        self._load_defaults()

    def _load_defaults(self) -> None:
        for r in self.DEFAULT_RULES:
            rule = PolicyRule(**r)
            self._rules[rule.rule_id] = rule

    def get(self, rule_id: str) -> PolicyRule | None:
        with self._lock:
            return self._rules.get(rule_id)

    def get_active(self, category: str | None = None) -> list[PolicyRule]:
        with self._lock:
            rules = [r for r in self._rules.values() if r.active]
        if category:
            rules = [r for r in rules if r.category == category]
        return rules

    def register(self, rule: PolicyRule) -> None:
        with self._lock:
            self._rules[rule.rule_id] = rule
        logger.info(f"[S1] registered rule: {rule.rule_id} {rule.name}")

    def trigger(self, rule_id: str) -> None:
        with self._lock:
            rule = self._rules.get(rule_id)
            if rule:
                rule.triggered_n   += 1
                rule.last_triggered = time.time()

    def decay_tick(self) -> None:
        """Pull all weights toward baseline (called by background scheduler)."""
        with self._lock:
            for rule in self._rules.values():
                if rule.weight != BASELINE_WEIGHT:
                    rule.weight = BASELINE_WEIGHT + (rule.weight - BASELINE_WEIGHT) * rule.decay

    def all_rules(self) -> list[dict]:
        with self._lock:
            return [r.to_dict() for r in self._rules.values()]


# ─────────────────────────────────────────────
# S2 — Constraint Engine
# ─────────────────────────────────────────────

@dataclass
class ConstraintResult:
    allowed:     bool   = True
    violations:  list[str] = field(default_factory=list)
    warnings:    list[str] = field(default_factory=list)
    gravity:     float  = 0.0
    verdict:     str    = "ALLOW"    # ALLOW | WARN | BLOCK

    def to_dict(self) -> dict:
        return {
            "allowed":    self.allowed,
            "violations": self.violations,
            "warnings":   self.warnings,
            "gravity":    round(self.gravity, 4),
            "verdict":    self.verdict,
        }


class S2ConstraintEngine:
    """
    S2 — Evaluates an action against all active policy rules.
    Hard violations → immediate BLOCK.
    Soft violations → gravity accumulation.
    Gravity >= BLOCK_THRESHOLD → BLOCK.
    Gravity >= PRUNE_THRESHOLD → WARN.
    """

    def evaluate(
        self,
        action_type:        str,
        payload:            dict,
        eagle_eye_trusted:  bool  = False,
        emma_approved:      bool  = False,
        operator_visible:   bool  = False,
        human_approved:     bool  = False,
        confidence:         float = 0.0,
        registry:           S1PolicyRegistry = None,
    ) -> ConstraintResult:

        result = ConstraintResult()
        rules  = registry.get_active() if registry else []

        gravity = 0.0
        violations: list[str] = []
        warnings:   list[str] = []

        for rule in rules:
            hit = self._check_rule(
                rule, action_type, payload,
                eagle_eye_trusted, emma_approved,
                operator_visible, human_approved, confidence,
            )
            if hit:
                if rule.category == "hard":
                    violations.append(f"{rule.rule_id}:{rule.name}")
                    gravity += rule.weight * 1.0
                    if registry:
                        registry.trigger(rule.rule_id)
                elif rule.category == "soft":
                    weighted = rule.weight * 0.50
                    gravity += weighted
                    warnings.append(f"{rule.rule_id}:{rule.name}(g+{weighted:.2f})")
                    if registry:
                        registry.trigger(rule.rule_id)
                else:  # monitor
                    warnings.append(f"MONITOR:{rule.rule_id}:{rule.name}")

        # Normalise gravity (max possible = sum of all hard weights)
        max_gravity = sum(r.weight for r in rules) or 1.0
        norm_gravity = min(gravity / max_gravity, 1.0)

        result.gravity    = norm_gravity
        result.violations = violations
        result.warnings   = warnings

        # Verdict
        if violations or norm_gravity >= BLOCK_THRESHOLD:
            result.allowed = False
            result.verdict = "BLOCK"
        elif norm_gravity >= PRUNE_THRESHOLD:
            result.allowed = True
            result.verdict = "WARN"
        else:
            result.allowed = True
            result.verdict = "ALLOW"

        logger.debug(
            f"[S2] action={action_type} verdict={result.verdict} "
            f"gravity={norm_gravity:.4f} violations={violations}"
        )
        return result

    def _check_rule(
        self, rule: PolicyRule, action_type: str, payload: dict,
        ee_trusted: bool, emma_approved: bool,
        op_visible: bool, human_approved: bool, confidence: float,
    ) -> bool:
        """Returns True if this rule is violated by the action."""
        rid = rule.rule_id

        # Hard rules
        if rid == "S1-H01":
            return "self_modify" in action_type or payload.get("target") == "lucy_core"
        if rid == "S1-H02":
            query = str(payload.get("query", "")).lower()
            return any(p in query for p in ["ignore previous", "jailbreak", "you are now a"])
        if rid == "S1-H03":
            return "exfil" in action_type or "credential" in str(payload).lower()
        if rid == "S1-H04":
            # Bioyth0n gate: write/execute without EE trusted + Emma approved
            if action_type in ("write_file", "execute_script", "run_command", "spawn_npc"):
                return not (ee_trusted and emma_approved)
            return False
        if rid == "S1-H05":
            return payload.get("action") in ("delete_vault", "modify_vault", "truncate_vault")

        # Soft rules
        if rid == "S1-S01":
            risk_level = payload.get("risk_level", "low")
            if risk_level in ("medium", "high", "critical"):
                return not op_visible
            return False
        if rid == "S1-S02":
            return confidence < rule.threshold
        if rid == "S1-S03":
            write_ops = ("write_file", "execute_script", "spawn_npc", "create_mission",
                         "repair_resource", "write_config", "scaffold")
            if action_type in write_ops:
                return not emma_approved
            return False
        if rid == "S1-S04":
            if payload.get("risk_level") in ("high", "critical"):
                return not human_approved
            return False

        # Monitor rules (never hard-block, just flag)
        return False


# ─────────────────────────────────────────────
# S3 — Bias Auditor
# ─────────────────────────────────────────────

class S3BiasAuditor:
    """
    S3 — Cross-system bias pattern auditing.
    Checks decision patterns from Emma auditor for systemic bias.
    """

    def audit_decisions(self, recent_entries: list[dict]) -> dict[str, Any]:
        if not recent_entries:
            return {"bias_detected": False, "signals": []}

        signals: list[str] = []
        n = len(recent_entries)

        # Domain bias: one domain blocked disproportionately
        domain_blocks: dict[str, int] = {}
        for e in recent_entries:
            if e.get("safety_verdict") == "BLOCK":
                d = e.get("domain", "unknown")
                domain_blocks[d] = domain_blocks.get(d, 0) + 1
        for domain, count in domain_blocks.items():
            if count / n > 0.5:
                signals.append(f"domain_block_bias: {domain} blocked {count}/{n} times")

        # Urgency bias: critical urgency always passing
        crit_pass = sum(
            1 for e in recent_entries
            if e.get("urgency") == "critical" and e.get("safety_verdict") == "PASS"
        )
        crit_total = sum(1 for e in recent_entries if e.get("urgency") == "critical")
        if crit_total > 0 and crit_pass / crit_total > 0.95 and crit_total > 5:
            signals.append(f"urgency_bypass_bias: critical urgency passes {crit_pass}/{crit_total}")

        # Agent bias: one agent always top-ranked
        dominant_agents: dict[str, int] = {}
        for e in recent_entries:
            da = e.get("dominant_agent", "")
            if da:
                dominant_agents[da] = dominant_agents.get(da, 0) + 1
        for agent, count in dominant_agents.items():
            if count / n > 0.70 and n >= 5:
                signals.append(f"agent_dominance_bias: {agent} dominated {count}/{n} responses")

        return {
            "bias_detected": len(signals) > 0,
            "signals":       signals,
            "audited":       n,
        }


# ─────────────────────────────────────────────
# S4 — Risk Scorer
# ─────────────────────────────────────────────

class S4RiskScorer:
    """
    S4 — Aggregates multi-signal risk score for any proposed action.
    Combines: constraint gravity, Eagle Eye pressure, Emma risk,
    DeltaVault integrity, trust level.
    """

    def score(
        self,
        constraint_gravity: float = 0.0,
        ee_pressure:        float = 0.0,
        emma_risk:          float = 0.0,
        vault_integrity:    bool  = True,
        trust_score:        float = 50.0,
        action_type:        str   = "read",
    ) -> tuple[str, float]:
        """Returns (risk_tier, risk_score)."""

        # Base from constraint gravity
        base = constraint_gravity * 0.35

        # EE pressure contribution
        base += ee_pressure * 0.25

        # Emma risk contribution
        base += emma_risk * 0.20

        # Vault integrity — if compromised, major risk escalation
        if not vault_integrity:
            base += 0.20

        # Trust score contribution (lower trust = higher risk)
        trust_factor = max(0.0, (100.0 - trust_score) / 100.0)
        base += trust_factor * 0.10

        # Action type modifier
        action_modifiers = {
            "read":            0.00,
            "chat":            0.00,
            "simulate":        0.02,
            "scaffold":        0.05,
            "write_file":      0.10,
            "execute_script":  0.12,
            "spawn_npc":       0.08,
            "create_mission":  0.06,
            "repair_resource": 0.07,
            "write_config":    0.09,
            "delete":          0.15,
        }
        base += action_modifiers.get(action_type, 0.05)

        risk_score = min(round(base, 4), 1.0)

        if risk_score >= 0.80:
            tier = "critical"
        elif risk_score >= 0.55:
            tier = "high"
        elif risk_score >= 0.30:
            tier = "medium"
        else:
            tier = "low"

        logger.debug(f"[S4] action={action_type} risk_score={risk_score:.4f} tier={tier}")
        return tier, risk_score


# ─────────────────────────────────────────────
# Composite Policy Engine (S1-S4)
# ─────────────────────────────────────────────

class PolicyEngine:
    """
    Wires S1-S4 into unified policy evaluation.
    Used by ExecutionGate, Bioyth0n, and the safety API.
    """

    def __init__(self):
        self.s1 = S1PolicyRegistry()
        self.s2 = S2ConstraintEngine()
        self.s3 = S3BiasAuditor()
        self.s4 = S4RiskScorer()

    def evaluate_action(
        self,
        action_type:       str,
        payload:           dict,
        eagle_eye_trusted: bool  = False,
        emma_approved:     bool  = False,
        operator_visible:  bool  = False,
        human_approved:    bool  = False,
        confidence:        float = 0.0,
        ee_pressure:       float = 0.0,
        emma_risk:         float = 0.0,
        vault_integrity:   bool  = True,
        trust_score:       float = 50.0,
    ) -> dict[str, Any]:

        # S2 — constraint check
        constraint = self.s2.evaluate(
            action_type       = action_type,
            payload           = payload,
            eagle_eye_trusted = eagle_eye_trusted,
            emma_approved     = emma_approved,
            operator_visible  = operator_visible,
            human_approved    = human_approved,
            confidence        = confidence,
            registry          = self.s1,
        )

        # S4 — risk score
        tier, risk_score = self.s4.score(
            constraint_gravity = constraint.gravity,
            ee_pressure        = ee_pressure,
            emma_risk          = emma_risk,
            vault_integrity    = vault_integrity,
            trust_score        = trust_score,
            action_type        = action_type,
        )

        allowed = constraint.allowed and risk_score < BLOCK_THRESHOLD

        result = {
            "allowed":     allowed,
            "verdict":     constraint.verdict if allowed else "BLOCK",
            "risk_tier":   tier,
            "risk_score":  round(risk_score, 4),
            "gravity":     round(constraint.gravity, 4),
            "violations":  constraint.violations,
            "warnings":    constraint.warnings,
        }

        logger.info(
            f"[PolicyEngine] action={action_type} allowed={allowed} "
            f"verdict={result['verdict']} risk={tier}({risk_score:.4f})"
        )
        return result

    def decay_tick(self) -> None:
        self.s1.decay_tick()

    def get_rules(self) -> list[dict]:
        return self.s1.all_rules()

    def audit_bias(self, recent_entries: list[dict]) -> dict:
        return self.s3.audit_decisions(recent_entries)


# Singleton
policy_engine = PolicyEngine()