"""
Lucidity Kernel — 5-layer cognitive stack
Layer 1: Cipher Intelligence
Layer 2: Memory Pressure
Layer 3: Hardening (HardStateIsolation)
Layer 4: World Integrity
Layer 5: Self-Evolving Core

Python implementation inspired by AME LucyKernel.ts + LucyCognitiveCore.ts
and the LUCIDITY KERNEL EVOLUTION STACK spec.
"""
from __future__ import annotations
import uuid
import time
import threading
import copy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable

from .policy_gravity import PolicyGravityLayer, policy_gravity
from .planning_pruner import PlanningPruner, CognitivePlan, CognitiveStep, PruneReport
from .world_integrity import WorldModelService, world_model


# ── Layer 1: Cipher Intelligence ───────────────────────────────────────────────

class CipherIntelligenceLayer:
    """
    Analyzes task inputs for encoded/obfuscated payloads.
    Integrates with CipherDetector to flag suspicious inputs.
    """

    def __init__(self):
        try:
            from cipher.detector import detector
            self._detector = detector
            self._available = True
        except ImportError:
            self._available = False

    def analyze(self, text: str) -> dict:
        if not self._available or len(text) < 8:
            return {"flagged": False, "reason": "cipher_layer_unavailable_or_short"}
        result = self._detector.detect(text, top_n=3)
        top = result.top_matches
        flagged = bool(top and top[0].confidence > 0.80 and
                       top[0].category in ("Encoding", "Steganographic"))
        return {
            "flagged": flagged,
            "top_cipher": top[0].to_dict() if top else None,
            "ioc": result.ioc,
            "flags": result.structural_flags,
        }


# ── Layer 2: Memory Pressure ───────────────────────────────────────────────────

class MemoryPressureLayer:
    """
    Monitors memory/context pressure.
    Signals when the kernel should drop old observations or compact memory.
    """

    def __init__(self, max_history: int = 500):
        self._max_history = max_history
        self._history: List[dict] = []
        self._lock = threading.Lock()
        self.compaction_count = 0

    def record(self, entry: dict):
        with self._lock:
            self._history.append({**entry, "ts": time.time()})
            if len(self._history) > self._max_history:
                # Compact: keep recent 80%
                keep = int(self._max_history * 0.8)
                self._history = self._history[-keep:]
                self.compaction_count += 1

    def pressure(self) -> float:
        """Returns 0.0 (empty) to 1.0 (at max capacity)."""
        with self._lock:
            return len(self._history) / self._max_history

    def get_recent(self, n: int = 10) -> List[dict]:
        with self._lock:
            return list(self._history[-n:])

    def summary(self) -> dict:
        with self._lock:
            return {
                "history_size": len(self._history),
                "max_history": self._max_history,
                "pressure": round(self.pressure(), 4),
                "compaction_count": self.compaction_count,
            }


# ── Layer 3: Hardening (HardStateIsolation) ────────────────────────────────────

class HardeningLayer:
    """
    Python port of HardStateIsolation.ts.
    Wraps external/untrusted logic execution with read-only state boundary.
    """

    def __init__(self, gravity: PolicyGravityLayer, world: WorldModelService):
        self._gravity = gravity
        self._world = world
        self._block_count = 0
        self._pass_count = 0

    def execute(self, agent_id: str, action_signature: str,
                logic: Callable[[dict], Any]) -> dict:
        """
        Execute external logic within isolation boundary.
        Returns {success, data, error, gravity_penalty_applied}
        """
        # 1. Create read-only frozen copy of world state
        raw_state = self._world.get_belief_state()
        read_only_state = copy.deepcopy(raw_state)  # deep clone

        # 2. Pre-execution gravity gate
        current_gravity = self._gravity.get_weight(action_signature)
        if current_gravity > self._gravity.BLOCK_THRESHOLD:
            self._block_count += 1
            return {
                "success": False,
                "error": f"BLOCKED_BY_GRAVITY: gravity={current_gravity:.3f} "
                         f"exceeds threshold {self._gravity.BLOCK_THRESHOLD}",
                "gravity_penalty_applied": 0,
            }

        try:
            # 3. Execute in boundary
            result = logic(read_only_state)

            # 4. Reward: slight gravity decay for successful execution
            self._gravity.increase_gravity(action_signature, -0.05,
                                           "successful execution reward")
            self._pass_count += 1
            return {"success": True, "data": result, "gravity_penalty_applied": 0}

        except Exception as e:
            # 5. Failure: penalize with gravity increase
            penalty = 0.2
            self._gravity.increase_gravity(action_signature, penalty,
                                           f"execution failure: {str(e)[:80]}")
            self._block_count += 1
            return {
                "success": False,
                "error": str(e),
                "gravity_penalty_applied": penalty,
            }

    def stats(self) -> dict:
        return {
            "block_count": self._block_count,
            "pass_count": self._pass_count,
            "block_rate": round(
                self._block_count / max(1, self._block_count + self._pass_count), 4),
        }


# ── Layer 5: Self-Evolving Core ────────────────────────────────────────────────

class SelfEvolvingCore:
    """
    Monitors system performance and rewrites threshold parameters.
    Implements the LUCIDITY KERNEL EVOLUTION STACK Layer 5 spec:
    - Tracks success/failure rates
    - Adjusts decay rates and thresholds dynamically
    - Generates evolution events
    """

    def __init__(self, gravity: PolicyGravityLayer):
        self._gravity = gravity
        self._tick_count = 0
        self._success_count = 0
        self._failure_count = 0
        self._evolution_log: List[dict] = []
        self._lock = threading.Lock()

        # Evolution thresholds
        self._failure_rate_threshold = 0.40   # >40% failures → tighten gravity
        self._success_rate_threshold = 0.85   # >85% success → relax gravity

    def record_tick(self, success: bool):
        with self._lock:
            self._tick_count += 1
            if success:
                self._success_count += 1
            else:
                self._failure_count += 1

            # Evolve every 20 ticks
            if self._tick_count % 20 == 0:
                self._evolve()

    def _evolve(self):
        """Rewrite system parameters based on recent performance."""
        total = self._tick_count
        if total == 0:
            return
        failure_rate = self._failure_count / total
        success_rate = self._success_count / total

        evolution_actions = []

        if failure_rate > self._failure_rate_threshold:
            # Too many failures → tighten: increase PRUNE_THRESHOLD sensitivity
            old = self._gravity.PRUNE_THRESHOLD
            self._gravity.PRUNE_THRESHOLD = max(0.50, self._gravity.PRUNE_THRESHOLD - 0.05)
            evolution_actions.append(
                f"TIGHTEN: prune_threshold {old:.2f}→{self._gravity.PRUNE_THRESHOLD:.2f} "
                f"(failure_rate={failure_rate:.2%})")

        if success_rate > self._success_rate_threshold:
            # Great performance → relax: increase PRUNE_THRESHOLD (less pruning)
            old = self._gravity.PRUNE_THRESHOLD
            self._gravity.PRUNE_THRESHOLD = min(0.85, self._gravity.PRUNE_THRESHOLD + 0.02)
            evolution_actions.append(
                f"RELAX: prune_threshold {old:.2f}→{self._gravity.PRUNE_THRESHOLD:.2f} "
                f"(success_rate={success_rate:.2%})")

        if evolution_actions:
            event = {
                "ts": time.time(),
                "tick": self._tick_count,
                "failure_rate": round(failure_rate, 4),
                "success_rate": round(success_rate, 4),
                "actions": evolution_actions,
            }
            self._evolution_log.append(event)
            if len(self._evolution_log) > 100:
                self._evolution_log.pop(0)

    def stats(self) -> dict:
        with self._lock:
            total = max(1, self._tick_count)
            return {
                "tick_count": self._tick_count,
                "success_count": self._success_count,
                "failure_count": self._failure_count,
                "success_rate": round(self._success_count / total, 4),
                "failure_rate": round(self._failure_count / total, 4),
                "prune_threshold_current": self._gravity.PRUNE_THRESHOLD,
                "evolution_events": len(self._evolution_log),
                "recent_evolutions": self._evolution_log[-5:],
            }


# ── Lucidity Kernel (main) ─────────────────────────────────────────────────────

@dataclass
class TickResult:
    success: bool
    output: Any
    error: Optional[str]
    trace_id: str
    duration_ms: float
    prune_report: Optional[dict]
    layers_fired: List[str]

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "trace_id": self.trace_id,
            "duration_ms": round(self.duration_ms, 2),
            "prune_report": self.prune_report,
            "layers_fired": self.layers_fired,
        }


class LucidityKernel:
    """
    5-layer cognitive kernel.
    Perception → Memory → Hardening → WorldIntegrity → SelfEvolution.
    """

    def __init__(self,
                 gravity: PolicyGravityLayer = None,
                 world: WorldModelService = None):
        self._gravity = gravity or policy_gravity
        self._world = world or world_model
        self._pruner = PlanningPruner(self._gravity)

        # Layers
        self.cipher_layer = CipherIntelligenceLayer()
        self.memory_layer = MemoryPressureLayer()
        self.hardening_layer = HardeningLayer(self._gravity, self._world)
        self.evolution_layer = SelfEvolvingCore(self._gravity)

        self._tick_history: List[dict] = []
        self._lock = threading.Lock()

    def tick(self, goal: str, context: dict = None,
             session_id: str = "") -> TickResult:
        """Execute a full cognitive tick through all 5 layers."""
        start = time.time()
        trace_id = str(uuid.uuid4())[:12]
        layers_fired: List[str] = []
        context = context or {}

        try:
            # ── Layer 1: Cipher Intelligence ──────────────────────────────
            layers_fired.append("cipher_intelligence")
            cipher_analysis = self.cipher_layer.analyze(goal)
            if cipher_analysis.get("flagged"):
                return TickResult(
                    success=False,
                    output=None,
                    error=f"CipherLayer: suspicious encoding detected "
                          f"({cipher_analysis.get('top_cipher', {}).get('cipher_name', 'unknown')})",
                    trace_id=trace_id,
                    duration_ms=(time.time() - start) * 1000,
                    prune_report=None,
                    layers_fired=layers_fired,
                )

            # ── Layer 2: Memory Pressure ───────────────────────────────────
            layers_fired.append("memory_pressure")
            self.memory_layer.record({
                "type": "tick_input", "goal": goal[:100],
                "session_id": session_id, "trace_id": trace_id,
            })
            pressure = self.memory_layer.pressure()
            if pressure > 0.95:
                context["memory_pressure_warning"] = True

            # ── Layer 4: World Integrity — sync constraints ────────────────
            layers_fired.append("world_integrity")
            self._world.sync_constraints(self._gravity.get_constraints())
            belief = self._world.get_belief_state()

            # ── Generate raw plan ──────────────────────────────────────────
            raw_plan = self._generate_plan(goal, context, trace_id)

            # ── Layer 3: Hardening — prune plan ───────────────────────────
            layers_fired.append("hardening")
            pruned_plan, prune_report = self._pruner.prune(raw_plan, belief)

            if not pruned_plan.steps:
                return TickResult(
                    success=False,
                    output=None,
                    error="All plan steps were pruned by gravity layer",
                    trace_id=trace_id,
                    duration_ms=(time.time() - start) * 1000,
                    prune_report=prune_report.to_dict(),
                    layers_fired=layers_fired,
                )

            # ── Execute plan ───────────────────────────────────────────────
            trace = self._execute_plan(pruned_plan, session_id)

            # ── Layer 4: World consolidation ───────────────────────────────
            self._world.consolidate_trace(trace)

            # ── Policy Gravity update ──────────────────────────────────────
            self._gravity.update_from_trace(trace)
            self._gravity.apply_decay()

            # ── Layer 5: Self-Evolution ────────────────────────────────────
            layers_fired.append("self_evolution")
            self.evolution_layer.record_tick(trace["success"])

            # ── Memory record ──────────────────────────────────────────────
            duration_ms = (time.time() - start) * 1000
            self.memory_layer.record({
                "type": "tick_result",
                "trace_id": trace_id,
                "success": trace["success"],
                "duration_ms": round(duration_ms, 2),
            })

            result = TickResult(
                success=trace["success"],
                output=trace["steps"][-1].get("output") if trace["steps"] else None,
                error=trace["steps"][-1].get("error") if not trace["success"] else None,
                trace_id=trace_id,
                duration_ms=duration_ms,
                prune_report=prune_report.to_dict(),
                layers_fired=layers_fired,
            )

            with self._lock:
                self._tick_history.append(result.to_dict())
                if len(self._tick_history) > 200:
                    self._tick_history.pop(0)

            return result

        except Exception as e:
            self.evolution_layer.record_tick(False)
            return TickResult(
                success=False, output=None, error=str(e),
                trace_id=trace_id,
                duration_ms=(time.time() - start) * 1000,
                prune_report=None, layers_fired=layers_fired,
            )

    def _generate_plan(self, goal: str, context: dict, trace_id: str) -> CognitivePlan:
        """Generate a raw cognitive plan from goal."""
        goal_lower = goal.lower()

        # Capability/action inference (mirrors AME generateRawPlan)
        if any(w in goal_lower for w in ("kill", "terminate", "stop process")):
            capability, action = "process_management", "kill"
        elif any(w in goal_lower for w in ("spawn", "start", "launch", "run")):
            capability, action = "process_management", "spawn"
        elif any(w in goal_lower for w in ("monitor", "watch", "observe")):
            capability, action = "process_management", "monitor"
        elif any(w in goal_lower for w in ("asset", "generate", "create 3d", "forge")):
            capability, action = "asset_generation", "generate"
        elif any(w in goal_lower for w in ("delete", "remove", "purge")):
            capability, action = "file_system", "delete"
        elif any(w in goal_lower for w in ("write", "save", "store")):
            capability, action = "file_system", "write"
        elif any(w in goal_lower for w in ("read", "load", "fetch file")):
            capability, action = "file_system", "read"
        elif any(w in goal_lower for w in ("deploy", "publish", "release")):
            capability, action = "deployment", "deploy"
        elif any(w in goal_lower for w in ("analyze", "inspect", "check")):
            capability, action = "analysis", "analyze"
        else:
            capability, action = "file_system", "read"

        step = CognitiveStep(
            id="step_1",
            description=f"Execute: {goal[:100]}",
            capability=capability,
            action=action,
            payload=context,
        )

        return CognitivePlan(
            id=str(uuid.uuid4())[:8],
            goal=goal,
            steps=[step],
            confidence=0.9,
            trace_id=trace_id,
        )

    def _execute_plan(self, plan: CognitivePlan, session_id: str) -> dict:
        """Execute the (pruned) plan and return an execution trace."""
        steps = []
        success = True

        for step in plan.steps:
            step_start = time.time()
            try:
                # Execute via hardening layer
                result = self.hardening_layer.execute(
                    agent_id=session_id or "kernel",
                    action_signature=f"action:{step.action}",
                    logic=lambda state, s=step: self._run_step(s, state),
                )
                step_result = {
                    "step_id": step.id,
                    "action": step.action,
                    "capability": step.capability,
                    "success": result["success"],
                    "output": result.get("data"),
                    "error": result.get("error"),
                    "duration_ms": round((time.time() - step_start) * 1000, 2),
                }
                steps.append(step_result)
                if not result["success"]:
                    success = False
                    break
            except Exception as e:
                steps.append({
                    "step_id": step.id,
                    "action": step.action,
                    "capability": step.capability,
                    "success": False,
                    "error": str(e),
                    "duration_ms": round((time.time() - step_start) * 1000, 2),
                })
                success = False
                break

        return {
            "trace_id": plan.trace_id,
            "plan_id": plan.id,
            "goal": plan.goal,
            "steps": steps,
            "success": success,
            "started_at": time.time(),
        }

    def _run_step(self, step: CognitiveStep, read_only_state: dict) -> dict:
        """
        Simulate step execution (in production: calls real plugins/tools).
        Returns output dict.
        """
        # Simulate results per action type
        simulated = {
            "monitor":  {"status": "monitoring", "pid_count": 12, "cpu_avg": 23.4},
            "analyze":  {"status": "analysis_complete", "findings": ["no anomalies"]},
            "read":     {"status": "read_complete", "bytes": 4096},
            "inspect":  {"status": "inspection_complete", "issues": 0},
            "generate": {"status": "asset_generated",
                         "asset_id": f"asset_{int(time.time())}",
                         "path": "/Assets/Generated/Asset.gltf"},
            "queue":    {"status": "queued", "position": 1},
            "validate": {"status": "validation_passed", "checks": 5},
        }
        return simulated.get(step.action, {"status": f"{step.action}_complete"})

    def status(self) -> dict:
        return {
            "gravity": self._gravity.summary(),
            "memory": self.memory_layer.summary(),
            "hardening": self.hardening_layer.stats(),
            "evolution": self.evolution_layer.stats(),
            "world": self._world.summary(),
            "tick_history_size": len(self._tick_history),
        }

    def get_tick_history(self, limit: int = 20) -> List[dict]:
        with self._lock:
            return list(self._tick_history[-limit:])


# Singleton
lucidity_kernel = LucidityKernel()