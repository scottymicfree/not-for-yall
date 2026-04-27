"""
Lucidity API — FastAPI router for the Lucidity layer
Endpoints: kernel status, policy gravity, planning pruner, world integrity
"""

from __future__ import annotations
import time
import asyncio
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

# ── Lucidity imports (graceful fallback) ───────────────────────────────────────
try:
    from lucidity.kernel import LucidityKernel, lucidity_kernel
except ImportError:
    lucidity_kernel = None

try:
    from lucidity.policy_gravity import PolicyGravityLayer, policy_gravity
except ImportError:
    policy_gravity = None

try:
    from lucidity.planning_pruner import PlanningPruner, planning_pruner
except ImportError:
    planning_pruner = None

try:
    from lucidity.world_integrity import WorldIntegrityChecker, world_integrity
except ImportError:
    world_integrity = None

# ── Router ─────────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/lucidity", tags=["lucidity"])

# ── Request / Response Models ──────────────────────────────────────────────────

class PolicyEvalRequest(BaseModel):
    action: str
    context: Dict[str, Any] = {}
    confidence: float = 0.70
    domain: str = "general"

class PolicyEvalResponse(BaseModel):
    action: str
    gravity_score: float
    decision: str          # ALLOW / SOFT_BLOCK / HARD_BLOCK
    active_rules: List[str]
    violated_rules: List[str]
    timestamp: float

class PruneRequest(BaseModel):
    plans: List[Dict[str, Any]]
    max_plans: int = 5
    min_confidence: float = 0.40
    context: Dict[str, Any] = {}

class PruneResponse(BaseModel):
    original_count: int
    pruned_count: int
    survivors: List[Dict[str, Any]]
    pruned_ids: List[str]
    timestamp: float

class IntegrityCheckRequest(BaseModel):
    content: str
    source: str = "internal"
    domain: str = "general"
    strict: bool = False

class IntegrityCheckResponse(BaseModel):
    content_hash: str
    integrity_score: float
    violations: List[str]
    passed: bool
    timestamp: float

class KernelStateResponse(BaseModel):
    kernel_version: str
    uptime_seconds: float
    active_policies: int
    pruner_runs: int
    integrity_checks: int
    gravity_evaluations: int
    last_block_action: Optional[str]
    health: str
    timestamp: float

class UpgradeProposalRequest(BaseModel):
    module: str
    description: str
    rationale: str
    confidence: float
    risk_level: str = "low"
    proposed_by: str = "lucy_prime"

class UpgradeProposalResponse(BaseModel):
    proposal_id: str
    module: str
    status: str        # ACCEPTED / PENDING_REVIEW / REJECTED
    gravity_gate: float
    message: str
    timestamp: float

# ── Internal state ─────────────────────────────────────────────────────────────
_start_time = time.time()
_kernel_stats: Dict[str, Any] = {
    "pruner_runs": 0,
    "integrity_checks": 0,
    "gravity_evaluations": 0,
    "last_block_action": None,
    "active_policies": 14,
}

# ── Helper ─────────────────────────────────────────────────────────────────────
def _gravity_evaluate(action: str, context: dict, confidence: float) -> dict:
    """Core gravity evaluation — uses live module or stub."""
    if policy_gravity is not None:
        try:
            result = policy_gravity.evaluate(action=action, context=context, confidence=confidence)
            _kernel_stats["gravity_evaluations"] += 1
            if result.get("decision") in ("SOFT_BLOCK", "HARD_BLOCK"):
                _kernel_stats["last_block_action"] = action
            return result
        except Exception:
            pass

    # Stub fallback
    _kernel_stats["gravity_evaluations"] += 1
    BLOCK_THRESHOLD = 0.80
    SOFT_THRESHOLD  = 0.60
    high_risk_keywords = {"delete_all", "override_safety", "wipe", "exploit", "inject_code"}
    base_score = 0.10
    for kw in high_risk_keywords:
        if kw in action.lower():
            base_score += 0.30
    if confidence < 0.50:
        base_score += 0.20

    if base_score >= BLOCK_THRESHOLD:
        decision = "HARD_BLOCK"
        _kernel_stats["last_block_action"] = action
    elif base_score >= SOFT_THRESHOLD:
        decision = "SOFT_BLOCK"
    else:
        decision = "ALLOW"

    return {
        "gravity_score": round(min(base_score, 1.0), 4),
        "decision": decision,
        "active_rules": ["no_self_harm", "no_exploit", "no_mass_delete"],
        "violated_rules": [kw for kw in high_risk_keywords if kw in action.lower()],
    }

def _prune_plans(plans: list, max_plans: int, min_confidence: float, context: dict) -> dict:
    """Prune plan list — uses live module or stub."""
    if planning_pruner is not None:
        try:
            result = planning_pruner.prune(plans=plans, max_plans=max_plans,
                                           min_confidence=min_confidence, context=context)
            _kernel_stats["pruner_runs"] += 1
            return result
        except Exception:
            pass

    _kernel_stats["pruner_runs"] += 1
    survivors = []
    pruned_ids = []
    for p in plans:
        conf = p.get("confidence", 0.5)
        pid  = p.get("id", f"plan_{id(p)}")
        if conf >= min_confidence:
            survivors.append(p)
        else:
            pruned_ids.append(pid)

    # Sort by confidence desc, take top max_plans
    survivors.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    excess = survivors[max_plans:]
    survivors = survivors[:max_plans]
    pruned_ids.extend(p.get("id", f"plan_{id(p)}") for p in excess)

    return {
        "survivors": survivors,
        "pruned_ids": pruned_ids,
    }

def _check_integrity(content: str, source: str, domain: str, strict: bool) -> dict:
    """World integrity check — uses live module or stub."""
    import hashlib
    _kernel_stats["integrity_checks"] += 1

    if world_integrity is not None:
        try:
            result = world_integrity.check(content=content, source=source,
                                           domain=domain, strict=strict)
            return result
        except Exception:
            pass

    # Stub
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
    violations = []
    FORBIDDEN = ["delete everything", "bypass all safety", "ignore constraints"]
    for f in FORBIDDEN:
        if f.lower() in content.lower():
            violations.append(f"forbidden_phrase:{f}")

    integrity_score = 1.0 - (len(violations) * 0.30)
    integrity_score = round(max(0.0, integrity_score), 4)
    passed = integrity_score >= (0.70 if strict else 0.40)

    return {
        "content_hash": content_hash,
        "integrity_score": integrity_score,
        "violations": violations,
        "passed": passed,
    }

# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/status", response_model=KernelStateResponse, summary="Lucidity kernel status")
async def get_kernel_status():
    """Return current Lucidity kernel state and statistics."""
    version = "5.0.0"
    if lucidity_kernel is not None:
        try:
            info = lucidity_kernel.info()
            version = info.get("version", version)
            _kernel_stats["active_policies"] = info.get("active_policies",
                                                          _kernel_stats["active_policies"])
        except Exception:
            pass

    return KernelStateResponse(
        kernel_version=version,
        uptime_seconds=round(time.time() - _start_time, 2),
        active_policies=_kernel_stats["active_policies"],
        pruner_runs=_kernel_stats["pruner_runs"],
        integrity_checks=_kernel_stats["integrity_checks"],
        gravity_evaluations=_kernel_stats["gravity_evaluations"],
        last_block_action=_kernel_stats["last_block_action"],
        health="nominal",
        timestamp=time.time(),
    )

@router.post("/policy/evaluate", response_model=PolicyEvalResponse,
             summary="Evaluate action through PolicyGravityLayer")
async def evaluate_policy(req: PolicyEvalRequest):
    """
    Run an action through the PolicyGravityLayer (S1-S4 + gravity scoring).
    Returns gravity score, decision (ALLOW / SOFT_BLOCK / HARD_BLOCK), and rule violations.
    """
    result = _gravity_evaluate(req.action, req.context, req.confidence)

    return PolicyEvalResponse(
        action=req.action,
        gravity_score=result["gravity_score"],
        decision=result["decision"],
        active_rules=result["active_rules"],
        violated_rules=result["violated_rules"],
        timestamp=time.time(),
    )

@router.post("/plans/prune", response_model=PruneResponse, summary="Prune plan list via PlanningPruner")
async def prune_plans(req: PruneRequest):
    """
    Submit a list of candidate plans. PlanningPruner filters by confidence threshold
    and returns the top survivors up to max_plans.
    """
    if not req.plans:
        raise HTTPException(status_code=400, detail="plans list cannot be empty")

    result = _prune_plans(req.plans, req.max_plans, req.min_confidence, req.context)

    return PruneResponse(
        original_count=len(req.plans),
        pruned_count=len(result["pruned_ids"]),
        survivors=result["survivors"],
        pruned_ids=result["pruned_ids"],
        timestamp=time.time(),
    )

@router.post("/integrity/check", response_model=IntegrityCheckResponse,
             summary="World integrity check on content")
async def check_integrity(req: IntegrityCheckRequest):
    """
    Run content through WorldIntegrityChecker. Detects forbidden phrases,
    contradiction signals, and returns a normalised integrity score.
    """
    result = _check_integrity(req.content, req.source, req.domain, req.strict)

    return IntegrityCheckResponse(
        content_hash=result["content_hash"],
        integrity_score=result["integrity_score"],
        violations=result["violations"],
        passed=result["passed"],
        timestamp=time.time(),
    )

@router.post("/upgrade/propose", response_model=UpgradeProposalResponse,
             summary="Submit an upgrade proposal through Lucidity gate")
async def propose_upgrade(req: UpgradeProposalRequest):
    """
    Lucy Prime or a swarm agent submits an upgrade proposal.
    Lucidity evaluates gravity + confidence before accepting.
    """
    # Build action token for gravity eval
    action_token = f"upgrade:{req.module}:{req.risk_level}"
    gravity_result = _gravity_evaluate(action_token, {
        "description": req.description,
        "rationale": req.rationale,
        "proposed_by": req.proposed_by,
    }, req.confidence)

    import uuid
    proposal_id = str(uuid.uuid4())[:8]
    decision = gravity_result["decision"]

    if decision == "HARD_BLOCK":
        status  = "REJECTED"
        message = "Upgrade rejected by PolicyGravityLayer — hard block threshold exceeded."
    elif decision == "SOFT_BLOCK":
        status  = "PENDING_REVIEW"
        message = "Upgrade queued for human review — soft block triggered."
    else:
        status  = "ACCEPTED"
        message = f"Upgrade proposal accepted for module '{req.module}'."

    return UpgradeProposalResponse(
        proposal_id=proposal_id,
        module=req.module,
        status=status,
        gravity_gate=gravity_result["gravity_score"],
        message=message,
        timestamp=time.time(),
    )

@router.get("/policy/rules", summary="List all active policy rules")
async def list_policy_rules():
    """Return the full set of active PolicyGravityLayer rules."""
    if policy_gravity is not None:
        try:
            return {"rules": policy_gravity.get_rules(), "timestamp": time.time()}
        except Exception:
            pass

    # Stub rule list
    return {
        "rules": [
            {"id": "no_self_harm",       "type": "hard", "weight": 1.0,  "active": True},
            {"id": "no_exploit",         "type": "hard", "weight": 1.0,  "active": True},
            {"id": "no_mass_delete",     "type": "hard", "weight": 1.0,  "active": True},
            {"id": "no_unsafe_write",    "type": "hard", "weight": 1.0,  "active": True},
            {"id": "no_auth_bypass",     "type": "hard", "weight": 1.0,  "active": True},
            {"id": "confidence_floor",   "type": "soft", "weight": 0.75, "active": True},
            {"id": "bias_check",         "type": "soft", "weight": 0.60, "active": True},
            {"id": "novelty_gate",       "type": "soft", "weight": 0.50, "active": True},
            {"id": "risk_ceiling",       "type": "soft", "weight": 0.70, "active": True},
            {"id": "monitor_fivem",      "type": "monitor", "weight": 0.40, "active": True},
            {"id": "monitor_earth",      "type": "monitor", "weight": 0.40, "active": True},
            {"id": "monitor_upgrades",   "type": "monitor", "weight": 0.30, "active": True},
            {"id": "monitor_swarm",      "type": "monitor", "weight": 0.20, "active": True},
            {"id": "monitor_override",   "type": "monitor", "weight": 0.20, "active": True},
        ],
        "block_threshold": 0.80,
        "prune_threshold": 0.70,
        "timestamp": time.time(),
    }

@router.post("/policy/rules/{rule_id}/toggle", summary="Enable or disable a soft/monitor rule")
async def toggle_rule(rule_id: str, enabled: bool = True):
    """Toggle a non-hard policy rule on or off. Hard rules cannot be disabled."""
    HARD_RULES = {"no_self_harm", "no_exploit", "no_mass_delete", "no_unsafe_write", "no_auth_bypass"}
    if rule_id in HARD_RULES:
        raise HTTPException(status_code=403,
                            detail=f"Hard rule '{rule_id}' cannot be toggled.")

    if policy_gravity is not None:
        try:
            policy_gravity.toggle_rule(rule_id, enabled)
            return {"rule_id": rule_id, "enabled": enabled, "timestamp": time.time()}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return {"rule_id": rule_id, "enabled": enabled,
            "note": "stub — live PolicyGravity not loaded", "timestamp": time.time()}

@router.get("/integrity/history", summary="Recent integrity check history")
async def integrity_history(limit: int = 20):
    """Return the last N integrity check results."""
    if world_integrity is not None:
        try:
            history = world_integrity.get_history(limit=limit)
            return {"history": history, "count": len(history), "timestamp": time.time()}
        except Exception:
            pass

    return {
        "history": [],
        "count": 0,
        "note": "WorldIntegrityChecker not loaded",
        "timestamp": time.time(),
    }

@router.get("/gravity/heat", summary="Policy gravity heat map across recent actions")
async def gravity_heat():
    """Return a heat map of gravity scores across the last evaluated actions."""
    if policy_gravity is not None:
        try:
            heat = policy_gravity.get_heat_map()
            return {"heat_map": heat, "timestamp": time.time()}
        except Exception:
            pass

    # Stub heat
    heat_map = [
        {"action": "chat_response",     "gravity": 0.05, "decision": "ALLOW"},
        {"action": "fivem_spawn_npc",   "gravity": 0.18, "decision": "ALLOW"},
        {"action": "upgrade:swarm",     "gravity": 0.30, "decision": "ALLOW"},
        {"action": "earth_query",       "gravity": 0.08, "decision": "ALLOW"},
        {"action": "memory_write",      "gravity": 0.12, "decision": "ALLOW"},
    ]
    return {"heat_map": heat_map, "count": len(heat_map), "timestamp": time.time()}

@router.delete("/kernel/reset_stats", summary="Reset kernel runtime stats")
async def reset_kernel_stats():
    """Reset pruner/integrity/gravity counters (does not affect policies)."""
    _kernel_stats.update({
        "pruner_runs": 0,
        "integrity_checks": 0,
        "gravity_evaluations": 0,
        "last_block_action": None,
    })
    return {"reset": True, "timestamp": time.time()}