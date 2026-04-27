"""
Policy Gravity Layer — Python port of AME PolicyGravityLayer.ts
Soft avoidance learning: constraints accumulate gravity when actions fail/are blocked.
Decay prevents permanent overfitting.
"""
from __future__ import annotations
import time
import threading
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Callable
import math


@dataclass
class Constraint:
    id: str
    constraint_type: str        # action | capability | plugin | dynamic
    weight: float               # 0.0 – 1.0  (higher = stronger avoidance)
    decay: float                # weight reduction per decay tick
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)
    hit_count: int = 0          # how many times gravity was increased

    def to_dict(self) -> dict:
        return {**asdict(self), "created_at": self.created_at, "last_updated": self.last_updated}


@dataclass
class GravityEvent:
    constraint_id: str
    delta: float
    new_weight: float
    reason: str
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


class PolicyGravityLayer:
    """
    Maintains constraint weights that push the planner away from risky actions.
    Thread-safe. Supports autonomous decay loop.
    """

    BLOCK_THRESHOLD = 0.80    # Above this → HardStateIsolation blocks
    PRUNE_THRESHOLD = 0.70    # Above this → PlanningPruner prunes the step

    def __init__(self, decay_interval_s: float = 1.0):
        self._constraints: Dict[str, Constraint] = {}
        self._history: List[GravityEvent] = []
        self._lock = threading.RLock()
        self._listeners: List[Callable] = []
        self._decay_interval = decay_interval_s
        self._running = False
        self._decay_thread: Optional[threading.Thread] = None

        # Baseline constraints (matching AME PolicyGravityLayer.ts)
        self.register_constraint(Constraint(
            id="action:kill", constraint_type="action",
            weight=0.5, decay=0.01))
        self.register_constraint(Constraint(
            id="action:spawn", constraint_type="action",
            weight=0.2, decay=0.05))
        self.register_constraint(Constraint(
            id="action:delete", constraint_type="action",
            weight=0.3, decay=0.02))
        self.register_constraint(Constraint(
            id="action:format", constraint_type="action",
            weight=0.4, decay=0.01))

    # ── Lifecycle ───────────────────────────────────────────────────────────

    def start_decay_loop(self):
        """Start autonomous decay loop in background thread."""
        self._running = True
        self._decay_thread = threading.Thread(
            target=self._decay_loop, daemon=True, name="GravityDecay")
        self._decay_thread.start()

    def stop_decay_loop(self):
        self._running = False

    def _decay_loop(self):
        while self._running:
            time.sleep(self._decay_interval)
            self.apply_decay()

    # ── Constraint management ───────────────────────────────────────────────

    def register_constraint(self, c: Constraint):
        with self._lock:
            self._constraints[c.id] = c

    def get_weight(self, constraint_id: str) -> float:
        with self._lock:
            return self._constraints.get(constraint_id, Constraint(
                id=constraint_id, constraint_type="dynamic",
                weight=0.0, decay=0.05)).weight

    def get_constraints(self) -> Dict[str, float]:
        with self._lock:
            return {cid: c.weight for cid, c in self._constraints.items()}

    def increase_gravity(self, constraint_id: str, amount: float = 0.3, reason: str = ""):
        """Increase gravity for a constraint. Auto-registers if new."""
        with self._lock:
            if constraint_id not in self._constraints:
                self._constraints[constraint_id] = Constraint(
                    id=constraint_id, constraint_type="dynamic",
                    weight=0.0, decay=0.05)
            c = self._constraints[constraint_id]
            old_weight = c.weight
            c.weight = max(0.0, min(1.0, c.weight + amount))
            c.last_updated = time.time()
            if amount > 0:
                c.hit_count += 1
            evt = GravityEvent(
                constraint_id=constraint_id,
                delta=amount,
                new_weight=c.weight,
                reason=reason or f"gravity increased by {amount:.3f}",
            )
            self._history.append(evt)
            if len(self._history) > 1000:
                self._history.pop(0)
        self._emit_update()

    def apply_decay(self):
        """Decay all constraint weights slightly."""
        changed = False
        with self._lock:
            for c in self._constraints.values():
                if c.weight > 0:
                    c.weight = max(0.0, c.weight - c.decay)
                    c.last_updated = time.time()
                    changed = True
        if changed:
            self._emit_update()

    def update_from_trace(self, trace: dict):
        """
        Analyze an execution trace and update gravity from failures.
        trace: {steps: [{success, error, action, capability}], success: bool}
        """
        for step in trace.get("steps", []):
            if not step.get("success", True):
                action = step.get("action", "unknown")
                capability = step.get("capability", "")
                error = step.get("error", "")
                if "Blocked for safety" in error or "BLOCKED_BY_GRAVITY" in error:
                    self.increase_gravity(f"action:{action}", 0.5,
                                          "safety block — massive penalty")
                    if capability:
                        self.increase_gravity(f"capability:{capability}", 0.2,
                                              "safety block — capability penalty")
                else:
                    self.increase_gravity(f"action:{action}", 0.1,
                                          "standard failure penalty")

    # ── Event system ────────────────────────────────────────────────────────

    def subscribe(self, listener: Callable):
        self._listeners.append(listener)

    def _emit_update(self):
        weights = self.get_constraints()
        for listener in self._listeners:
            try:
                listener({"type": "GRAVITY_UPDATED", "payload": {"weights": weights}})
            except Exception:
                pass

    # ── Query ───────────────────────────────────────────────────────────────

    def is_blocked(self, constraint_id: str) -> bool:
        return self.get_weight(constraint_id) > self.BLOCK_THRESHOLD

    def should_prune(self, action: str, capability: str = "") -> bool:
        total = self.get_weight(f"action:{action}")
        if capability:
            total += self.get_weight(f"capability:{capability}")
        return total > self.PRUNE_THRESHOLD

    def get_history(self, limit: int = 50) -> List[dict]:
        with self._lock:
            return [e.to_dict() for e in self._history[-limit:]]

    def summary(self) -> dict:
        with self._lock:
            active = {cid: c for cid, c in self._constraints.items() if c.weight > 0}
            blocked = [cid for cid, c in self._constraints.items()
                       if c.weight > self.BLOCK_THRESHOLD]
            high_risk = [cid for cid, c in self._constraints.items()
                         if self.PRUNE_THRESHOLD < c.weight <= self.BLOCK_THRESHOLD]
            return {
                "total_constraints": len(self._constraints),
                "active_constraints": len(active),
                "blocked_constraints": blocked,
                "high_risk_constraints": high_risk,
                "weights": {cid: round(c.weight, 4) for cid, c in self._constraints.items()},
                "block_threshold": self.BLOCK_THRESHOLD,
                "prune_threshold": self.PRUNE_THRESHOLD,
                "history_count": len(self._history),
            }


# Singleton
policy_gravity = PolicyGravityLayer()
policy_gravity.start_decay_loop()