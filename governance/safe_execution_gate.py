"""
LUCY SAFE EXECUTION GATE — E.M.M.A. Pre-flight Approval
=========================================================
Every task passes through here before execution.
Three checks in sequence:
  1. ForbRegistry    — hard-blocked action tags
  2. Sentinel        — Tier-1 system halt triggers
  3. Scope check     — agent role vs. task claims
Returns an approval dict. If not approved, reason is logged.
"""

import re
from governance.forb_registry import ForbRegistry
from governance.sentinel_protocol import Sentinel

FORBIDDEN_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bformat\s+[a-z]:",
    r"\bDROP\s+TABLE\b",
    r"\bDELETE\s+FROM\b",
    r"\bTRUNCATE\s+TABLE\b",
    r"\bsudo\s+rm\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
    r"\bkillall\b",
    r":[(][)]{[|:][&][}][;][:]",   # fork bomb
]

SCOPE_VIOLATIONS = {
    "worker":  ["spawn_agent", "modify_governance", "cross_cluster_write",
                "prime_override", "emma_bypass", "broadcast_all"],
    "cluster": ["modify_governance", "prime_override", "emma_bypass",
                "direct_worker_spawn"],
    "prime":   ["sentinel_disable", "audit_tamper"],   # even prime can't do these
}


class SafeExecutionGate:

    def __init__(self, ledger=None):
        self.forb    = ForbRegistry()
        self.sentinel = Sentinel(ledger=ledger)
        self.ledger  = ledger

    async def check(self, task: dict, agent_type: str = "worker") -> dict:
        """
        Returns: {"approved": bool, "reason": str, "tier": int}
        tier 0 = approved
        tier 1 = Sentinel halt
        tier 2 = blocked, no halt
        """
        desc    = str(task.get("description", "")).lower()
        actions = [str(a) for a in task.get("actions", [])]
        task_id = task.get("task_id", "unknown")

        # ── 1. Sentinel check (Tier-1 — hard halt) ────────────────────────
        sentinel_result = self.sentinel.check_forbidden_intervention(
            {"actions": actions, "description": desc})
        if sentinel_result == "HALT_EXECUTED":
            return {
                "approved": False,
                "reason": "SENTINEL: Tier-1 hard halt triggered",
                "tier": 1
            }

        # ── 2. ForbRegistry check ─────────────────────────────────────────
        if self.forb.is_forbidden(actions):
            blocked = [a for a in actions if self.forb.is_forbidden([a])]
            reason = f"FORB: Action(s) in forbidden registry: {blocked}"
            if self.ledger:
                self.ledger.gate_blocked("GATE", task_id, reason)
            return {"approved": False, "reason": reason, "tier": 2}

        # ── 3. Description pattern check ──────────────────────────────────
        for pattern in FORBIDDEN_PATTERNS:
            if re.search(pattern, desc, re.IGNORECASE):
                reason = f"PATTERN: Forbidden pattern detected in description"
                if self.ledger:
                    self.ledger.gate_blocked("GATE", task_id, reason)
                return {"approved": False, "reason": reason, "tier": 2}

        # ── 4. Scope check ────────────────────────────────────────────────
        violations = SCOPE_VIOLATIONS.get(agent_type, [])
        for action in actions:
            if action.lower() in violations:
                reason = (f"SCOPE: Agent type '{agent_type}' cannot perform "
                          f"'{action}'")
                if self.ledger:
                    self.ledger.gate_blocked("GATE", task_id, reason)
                return {"approved": False, "reason": reason, "tier": 2}

        # ── Approved ──────────────────────────────────────────────────────
        if self.ledger:
            self.ledger.gate_approved("GATE", task_id, "E.M.M.A.: clear to proceed")
        return {
            "approved": True,
            "reason": "E.M.M.A.: all checks passed",
            "tier": 0
        }