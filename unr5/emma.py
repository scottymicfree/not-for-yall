"""
Emma — AI Approval Service
Python port of emma/approvalService.ts

Emma is the governance gate. She classifies actions by risk level and
approves or rejects based on payload completeness and operator visibility.
Emma does NOT reason freely — she applies deterministic rules.
"""

import time
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class EmmaApprovalResult:
    decision: str          # "approved" | "rejected"
    level: str             # "low" | "medium" | "high"
    reason: str
    approved_at: int

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "level": self.level,
            "reason": self.reason,
            "approvedAt": self.approved_at,
        }


def _classify_level(action_type: str) -> str:
    t = action_type.strip().lower()
    if any(k in t for k in ("twinearth", "projection", "analysis", "chat", "read",
                             "status", "list", "get", "scan", "query", "inspect",
                             "monitor", "view", "health")):
        return "low"
    if any(k in t for k in ("config", "settings", "review", "connect", "scaffold",
                              "propose", "upgrade", "simulate", "tick", "mission")):
        return "medium"
    return "high"


def _is_object(value: Any) -> bool:
    return isinstance(value, dict)


def _validate_by_level(level: str, action_type: str, payload: Any) -> dict:
    if level == "low":
        return {"ok": True, "reason": f'Emma approved low-risk action "{action_type}".'}

    if not _is_object(payload):
        return {
            "ok": False,
            "reason": f'Emma rejected {level}-risk action "{action_type}" — payload must be an object.'
        }

    operator_visible = payload.get("operatorVisible") is True
    requested_by = isinstance(payload.get("requestedBy"), str) and len(payload["requestedBy"]) > 0

    if level == "medium":
        if not operator_visible:
            return {
                "ok": False,
                "reason": f'Emma rejected medium-risk action "{action_type}" — operatorVisible=true required.'
            }
        return {
            "ok": True,
            "reason": f'Emma approved medium-risk action "{action_type}" with operator-visible handling.'
        }

    # high
    if not operator_visible or not requested_by:
        return {
            "ok": False,
            "reason": (
                f'Emma rejected high-risk action "{action_type}" — '
                f'operatorVisible=true and requestedBy are required.'
            )
        }
    return {
        "ok": True,
        "reason": f'Emma approved high-risk action "{action_type}" with explicit operator trace.'
    }


class EmmaApprovalService:
    """
    Emma reviews every action request.
    - Low risk  → auto-approved (analysis, reads, monitoring)
    - Medium risk → requires operatorVisible=true
    - High risk  → requires operatorVisible=true AND requestedBy

    Emma keeps a rolling review memory (max 200 entries).
    """

    def __init__(self, memory_limit: int = 200):
        self._memory: list = []
        self._memory_limit = memory_limit

    def review(self, action_type: str, payload: Any = None) -> EmmaApprovalResult:
        if not action_type or not isinstance(action_type, str) or not action_type.strip():
            result = EmmaApprovalResult(
                decision="rejected",
                level="high",
                reason="Action type is required.",
                approved_at=int(time.time() * 1000),
            )
            self._record(result)
            return result

        level = _classify_level(action_type)
        validation = _validate_by_level(level, action_type, payload)

        result = EmmaApprovalResult(
            decision="approved" if validation["ok"] else "rejected",
            level=level,
            reason=validation["reason"],
            approved_at=int(time.time() * 1000),
        )
        self._record(result)
        return result

    def _record(self, result: EmmaApprovalResult):
        self._memory.append(result)
        if len(self._memory) > self._memory_limit:
            self._memory.pop(0)

    def get_memory(self) -> list:
        return [r.to_dict() for r in self._memory]

    def approval_count(self) -> int:
        return sum(1 for r in self._memory if r.decision == "approved")

    def rejection_count(self) -> int:
        return sum(1 for r in self._memory if r.decision == "rejected")

    def clear_memory(self):
        self._memory.clear()

    def grade_trace(self, trace: dict) -> dict:
        """
        Emma grades an execution trace 0-100.
        Used by LTE (Lucidity Training Engine).
        """
        score = 100
        penalties = []

        steps = trace.get("steps", [])
        if not steps:
            return {"score": 0, "grade": "F", "reason": "No execution steps found."}

        failed = [s for s in steps if not s.get("success", False)]
        adapted = [s for s in steps if s.get("adapted", False)]
        dropped = [s for s in steps if s.get("dropped", False)]

        score -= len(failed) * 15
        score -= len(adapted) * 5
        score -= len(dropped) * 10

        if trace.get("gravity_blocked", False):
            score -= 20
            penalties.append("Gravity block triggered")

        if trace.get("cipher_flagged", False):
            score -= 10
            penalties.append("Suspicious input detected")

        confidence = trace.get("confidence", 1.0)
        if confidence < 0.5:
            score -= 10
            penalties.append("Low confidence plan")

        duration_ms = trace.get("duration_ms", 0)
        if duration_ms > 5000:
            score -= 5
            penalties.append("Slow execution")

        score = max(0, min(100, score))

        if score >= 90:
            grade = "A"
        elif score >= 80:
            grade = "B"
        elif score >= 70:
            grade = "C"
        elif score >= 60:
            grade = "D"
        else:
            grade = "F"

        return {
            "score": score,
            "grade": grade,
            "penalties": penalties,
            "steps_total": len(steps),
            "steps_failed": len(failed),
            "steps_adapted": len(adapted),
            "steps_dropped": len(dropped),
        }


# Singleton
emma = EmmaApprovalService()