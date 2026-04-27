"""
World Integrity / World Model Service
Python port of AME WorldModelService.ts + WorldBelief types.
Maintains the cognitive belief state of Lucy OS.
"""
from __future__ import annotations
import time
import threading
from dataclasses import dataclass, field, asdict
from typing import Dict, Set, List, Optional, Any


@dataclass
class WorldEntity:
    id: str
    entity_type: str            # process | file | agent | resource | task
    state: Dict[str, Any] = field(default_factory=dict)
    last_observed: float = field(default_factory=time.time)
    confidence: float = 1.0
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "state": self.state,
            "last_observed": self.last_observed,
            "confidence": self.confidence,
            "tags": self.tags,
        }


@dataclass
class VolatileObservation:
    step_id: str
    action: str
    output: Any
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


class WorldBeliefState:
    """
    Central in-memory belief state.
    Tracks entities, constraints, stable rules, and volatile observations.
    Thread-safe.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self.entities: Dict[str, WorldEntity] = {}
        self.constraints: Dict[str, float] = {}     # constraint_id → weight
        self.stable_rules: Set[str] = set()
        self.volatile_observations: List[VolatileObservation] = []
        self._max_volatile = 100

    def get_snapshot(self) -> dict:
        with self._lock:
            return {
                "entities": {eid: e.to_dict() for eid, e in self.entities.items()},
                "constraints": dict(self.constraints),
                "stable_rules": list(self.stable_rules),
                "volatile_observations": [
                    o.to_dict() for o in self.volatile_observations[-20:]
                ],
                "entity_count": len(self.entities),
                "rule_count": len(self.stable_rules),
                "observation_count": len(self.volatile_observations),
                "timestamp": time.time(),
            }

    def sync_constraints(self, constraint_weights: Dict[str, float]):
        with self._lock:
            self.constraints = dict(constraint_weights)

    def add_entity(self, entity: WorldEntity):
        with self._lock:
            self.entities[entity.id] = entity

    def update_entity(self, entity_id: str, state_update: dict):
        with self._lock:
            if entity_id in self.entities:
                self.entities[entity_id].state.update(state_update)
                self.entities[entity_id].last_observed = time.time()

    def remove_entity(self, entity_id: str):
        with self._lock:
            self.entities.pop(entity_id, None)

    def add_stable_rule(self, rule: str):
        with self._lock:
            self.stable_rules.add(rule)

    def add_observation(self, obs: VolatileObservation):
        with self._lock:
            self.volatile_observations.append(obs)
            if len(self.volatile_observations) > self._max_volatile:
                self.volatile_observations.pop(0)

    def consolidate_trace(self, trace: dict):
        """
        Update belief state from an execution trace.
        Mirrors AME WorldModelService.consolidateTrace().
        """
        now = time.time()
        with self._lock:
            for step in trace.get("steps", []):
                if step.get("success") and step.get("output"):
                    obs = VolatileObservation(
                        step_id=step.get("step_id", "unknown"),
                        action=step.get("action", "unknown"),
                        output=step.get("output"),
                        timestamp=now,
                    )
                    self.volatile_observations.append(obs)
                    if len(self.volatile_observations) > self._max_volatile:
                        self.volatile_observations.pop(0)

                    # Entity extraction: process spawn
                    output = step.get("output", {})
                    if isinstance(output, dict):
                        status = output.get("status", "")
                        if status in ("process_spawned", "simulated_native_success"):
                            import uuid as _uuid
                            eid = f"process_{_uuid.uuid4().hex[:6]}"
                            self.entities[eid] = WorldEntity(
                                id=eid, entity_type="process",
                                state=output, last_observed=now, confidence=1.0)

            # Extract stable rules from repeated successes
            if trace.get("success") and trace.get("steps"):
                action = trace["steps"][0].get("action", "unknown")
                self.stable_rules.add(
                    f"Action '{action}' is generally stable in current context.")


class WorldModelService:
    """
    Service wrapper around WorldBeliefState.
    Singleton-friendly.
    """

    def __init__(self):
        self._belief = WorldBeliefState()

    def get_belief_state(self) -> dict:
        return self._belief.get_snapshot()

    def sync_constraints(self, weights: Dict[str, float]):
        self._belief.sync_constraints(weights)

    def consolidate_trace(self, trace: dict):
        self._belief.consolidate_trace(trace)

    def add_entity(self, entity: WorldEntity):
        self._belief.add_entity(entity)

    def update_entity(self, entity_id: str, state_update: dict):
        self._belief.update_entity(entity_id, state_update)

    def add_stable_rule(self, rule: str):
        self._belief.add_stable_rule(rule)

    def get_entities(self) -> Dict[str, dict]:
        with self._belief._lock:
            return {eid: e.to_dict() for eid, e in self._belief.entities.items()}

    def get_rules(self) -> List[str]:
        with self._belief._lock:
            return list(self._belief.stable_rules)

    def summary(self) -> dict:
        snap = self.get_belief_state()
        return {
            "entity_count": snap["entity_count"],
            "rule_count": snap["rule_count"],
            "observation_count": snap["observation_count"],
            "constraint_count": len(snap["constraints"]),
            "timestamp": snap["timestamp"],
        }


# Singleton
world_model = WorldModelService()