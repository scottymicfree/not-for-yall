"""
Planning Pruner — Python port of AME PlanningPruner.ts
Pre-execution safety gate: prunes or adapts plan steps based on gravity.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from .policy_gravity import PolicyGravityLayer, policy_gravity


@dataclass
class CognitiveStep:
    id: str
    description: str
    capability: str
    action: str
    payload: Optional[Dict[str, Any]] = None
    expected_outcome: str = ""
    status: str = "pending"   # pending | running | completed | failed | pruned | adapted

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "capability": self.capability,
            "action": self.action,
            "payload": self.payload,
            "expected_outcome": self.expected_outcome,
            "status": self.status,
        }


@dataclass
class CognitivePlan:
    id: str
    goal: str
    steps: List[CognitiveStep]
    confidence: float = 0.9
    trace_id: str = ""
    pruned_steps: List[str] = field(default_factory=list)    # IDs of pruned steps
    adapted_steps: List[str] = field(default_factory=list)   # IDs of adapted steps

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "confidence": round(self.confidence, 4),
            "trace_id": self.trace_id,
            "pruned_steps": self.pruned_steps,
            "adapted_steps": self.adapted_steps,
        }


@dataclass
class PruneReport:
    original_step_count: int
    pruned_count: int
    adapted_count: int
    final_confidence: float
    actions_taken: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "original_step_count": self.original_step_count,
            "pruned_count": self.pruned_count,
            "adapted_count": self.adapted_count,
            "final_confidence": round(self.final_confidence, 4),
            "actions_taken": self.actions_taken,
        }


# Safe fallback actions when high-gravity actions are pruned
SAFE_ADAPTATIONS: Dict[str, str] = {
    "spawn": "monitor",
    "kill": "monitor",
    "delete": "inspect",
    "format": "inspect",
    "write": "read",
    "execute": "analyze",
    "deploy": "validate",
    "send": "queue",
}


class PlanningPruner:
    """
    Evaluates a plan against PolicyGravityLayer before execution.
    Prunes high-gravity steps or adapts them to safer alternatives.
    Mirrors AME PlanningPruner.ts behavior.
    """

    def __init__(self, gravity_layer: PolicyGravityLayer = None):
        self._gravity = gravity_layer or policy_gravity

    def prune(self, plan: CognitivePlan, belief: dict = None) -> tuple[CognitivePlan, PruneReport]:
        """
        Evaluate and prune plan steps.
        Returns (pruned_plan, report).
        """
        pruned_steps: List[CognitiveStep] = []
        pruned_ids: List[str] = []
        adapted_ids: List[str] = []
        plan_confidence = plan.confidence
        actions_taken: List[str] = []

        for step in plan.steps:
            action_gravity = self._gravity.get_weight(f"action:{step.action}")
            capability_gravity = self._gravity.get_weight(f"capability:{step.capability}")
            total_gravity = action_gravity + capability_gravity

            if total_gravity > self._gravity.PRUNE_THRESHOLD:
                # Try to adapt to a safe alternative
                safe_action = SAFE_ADAPTATIONS.get(step.action)
                if safe_action:
                    adapted_step = CognitiveStep(
                        id=step.id,
                        description=f"[Adapted] Original '{step.action}' pruned "
                                    f"(gravity={total_gravity:.2f}). "
                                    f"Defaulting to '{safe_action}'.",
                        capability=step.capability,
                        action=safe_action,
                        payload=step.payload,
                        status="adapted",
                    )
                    pruned_steps.append(adapted_step)
                    adapted_ids.append(step.id)
                    plan_confidence *= 0.8
                    actions_taken.append(
                        f"Adapted step '{step.id}': {step.action} → {safe_action} "
                        f"(gravity={total_gravity:.2f})"
                    )
                else:
                    # Drop entirely — no safe adaptation
                    pruned_ids.append(step.id)
                    plan_confidence *= 0.5
                    actions_taken.append(
                        f"Pruned step '{step.id}': {step.action} "
                        f"(gravity={total_gravity:.2f}, no safe adaptation)"
                    )
            else:
                pruned_steps.append(step)

        pruned_plan = CognitivePlan(
            id=plan.id,
            goal=plan.goal,
            steps=pruned_steps,
            confidence=max(0.0, min(1.0, plan_confidence)),
            trace_id=plan.trace_id,
            pruned_steps=pruned_ids,
            adapted_steps=adapted_ids,
        )

        report = PruneReport(
            original_step_count=len(plan.steps),
            pruned_count=len(pruned_ids),
            adapted_count=len(adapted_ids),
            final_confidence=plan_confidence,
            actions_taken=actions_taken,
        )

        return pruned_plan, report