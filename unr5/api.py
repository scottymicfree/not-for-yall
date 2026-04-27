"""
Lucy OS v5 — UNR5 FastAPI Router
All UNR5 endpoints: earth, sentinel, eagle_eye, emma, trust, vault, upgrades,
human_approval, simulation, ue5/unity bridge, auto_builder
"""

from __future__ import annotations
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = APIRouter
router = APIRouter(prefix="/unr5", tags=["unr5"])
logger = logging.getLogger("unr5.api")


# ── Request models ────────────────────────────────────────────────────

class BuilderRequest(BaseModel):
    prompt: str

class HumanDecisionRequest(BaseModel):
    item_id:  str
    decision: str     # "approve" | "reject"
    reason:   str = ""

class UpgradeDecisionRequest(BaseModel):
    proposal_id: str
    decision:    str   # "approve" | "reject"
    notes:       str = ""

class SimulationRequest(BaseModel):
    sim_id:        str = "sim_001"
    delta_overrides: dict = {}

class UE5TaskRequest(BaseModel):
    workspace_path: str
    task:           str
    params:         dict = {}

class ScaffoldRequest(BaseModel):
    workspace_path: str
    name:           str

class EagleEyeRequest(BaseModel):
    signals:   list[dict] = []
    ledger:    list[dict] = []
    emma_data: dict = {}


# ── Earth endpoints ───────────────────────────────────────────────────

@router.get("/earth/baseline")
async def earth_baseline():
    try:
        from unr5.earth import fetch_earth_baseline_sync
        return fetch_earth_baseline_sync()
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@router.get("/earth/twin")
async def earth_twin():
    try:
        from unr5.earth import fetch_earth_baseline_sync, build_twin_earth_state
        baseline = fetch_earth_baseline_sync()
        return build_twin_earth_state(baseline)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# ── Sentinel endpoints ────────────────────────────────────────────────

@router.get("/sentinel/signals")
async def sentinel_signals():
    try:
        from unr5.sentinel import sentinel_engine
        from unr5.earth    import fetch_earth_baseline_sync, build_twin_earth_state
        baseline = fetch_earth_baseline_sync()
        twin     = build_twin_earth_state(baseline)
        signals  = sentinel_engine.detect_signals(baseline, twin)
        return {"signals": signals, "count": len(signals)}
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@router.get("/sentinel/trend")
async def sentinel_trend():
    try:
        from unr5.sentinel import sentinel_engine
        return {"trend": sentinel_engine.get_trend_history()}
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# ── Eagle Eye endpoints ───────────────────────────────────────────────

@router.post("/eagle-eye/evaluate")
async def eagle_eye_evaluate(req: EagleEyeRequest):
    try:
        from unr5.eagle_eye import EagleEye
        ee     = EagleEye()
        report = ee.full_report(
            signals   = req.signals,
            ledger    = req.ledger,
            emma_data = req.emma_data,
        )
        return report
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# ── Emma endpoints ────────────────────────────────────────────────────

@router.get("/emma/status")
async def emma_status():
    try:
        from unr5.emma import emma
        return emma.get_status()
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@router.get("/emma/audit")
async def emma_audit(n: int = 20):
    try:
        from emma_mesh.auditor import emma_auditor
        return {
            "stats":   emma_auditor.get_stats(),
            "recent":  emma_auditor.get_recent_entries(n),
        }
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# ── Trust & Reward endpoints ──────────────────────────────────────────

@router.get("/trust")
async def get_trust():
    try:
        from unr5.trust import derive_trust_state, derive_reward_state
        from unr5.delta_vault import delta_vault
        from unr5.emma import emma
        ledger     = delta_vault.recent_entries(20)
        emma_stats = emma.get_status()
        trust      = derive_trust_state(ledger, emma_stats)
        reward     = derive_reward_state(
            trust_state = trust,
            ee_trusted  = True,
            confidence  = 0.75,
        )
        return {"trust": trust, "reward": reward}
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# ── DeltaVault endpoints ──────────────────────────────────────────────

@router.get("/vault/entries")
async def vault_entries(n: int = 20):
    try:
        from unr5.delta_vault import delta_vault
        return {
            "entries":  delta_vault.recent_entries(n),
            "verified": delta_vault.verify_integrity(),
        }
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@router.get("/vault/integrity")
async def vault_integrity():
    try:
        from unr5.delta_vault import delta_vault
        return delta_vault.verify_integrity()
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# ── Human Approval endpoints ──────────────────────────────────────────

@router.get("/human-approval/pending")
async def get_pending_approvals():
    try:
        from unr5.human_approval import human_approval_store, derive_human_approval_state
        ee_state = {"trusted": True, "confidence": 0.80, "integrity": {"ok": True}}
        return derive_human_approval_state(human_approval_store, ee_state)
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@router.post("/human-approval/decide")
async def decide_approval(req: HumanDecisionRequest):
    try:
        from unr5.human_approval import human_approval_store
        human_approval_store.record_decision(
            item_id  = req.item_id,
            decision = req.decision,
            reason   = req.reason,
        )
        return {"recorded": True, "item_id": req.item_id, "decision": req.decision}
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# ── Upgrade Proposals endpoints ───────────────────────────────────────

@router.get("/upgrades")
async def get_upgrades(status: str = "pending"):
    try:
        from unr5.upgrades import upgrade_store
        return {"proposals": upgrade_store.get_by_status(status)}
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@router.post("/upgrades/decide")
async def decide_upgrade(req: UpgradeDecisionRequest):
    try:
        from unr5.upgrades import upgrade_store
        upgrade_store.decide(req.proposal_id, req.decision, req.notes)
        return {"updated": True, "proposal_id": req.proposal_id}
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# ── Simulation endpoints ──────────────────────────────────────────────

@router.post("/simulation/run")
async def run_simulation(req: SimulationRequest):
    try:
        from unr5.human_approval import build_simulation_packet
        from unr5.earth import fetch_earth_baseline_sync, build_twin_earth_state
        baseline = fetch_earth_baseline_sync()
        twin     = build_twin_earth_state(baseline)
        packet   = build_simulation_packet(
            sim_id         = req.sim_id,
            earth_state    = twin,
            delta_overrides= req.delta_overrides,
        )
        return packet
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# ── UE5 Bridge endpoints ──────────────────────────────────────────────

@router.post("/ue5/scaffold")
async def ue5_scaffold(req: ScaffoldRequest):
    try:
        from unr5.ue5_bridge import ue5_bridge
        result = ue5_bridge.create_map_scaffold(req.workspace_path, req.name)
        return {"result": result}
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@router.post("/ue5/task")
async def ue5_task(req: UE5TaskRequest):
    try:
        from unr5.ue5_bridge import ue5_bridge
        result = ue5_bridge.execute_task(req.workspace_path, req.task, req.params)
        return result
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@router.get("/ue5/status")
async def ue5_status():
    try:
        from unr5.ue5_bridge import ue5_bridge
        return ue5_bridge.get_status()
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# ── Unity Bridge endpoints ────────────────────────────────────────────

@router.post("/unity/scaffold")
async def unity_scaffold(req: ScaffoldRequest):
    try:
        from unr5.ue5_bridge import unity_bridge
        result = unity_bridge.create_scene_scaffold(req.workspace_path, req.name)
        return {"result": result}
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@router.get("/unity/status")
async def unity_status():
    try:
        from unr5.ue5_bridge import unity_bridge
        return unity_bridge.get_status()
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# ── Auto Builder endpoints ────────────────────────────────────────────

@router.post("/builder/run")
async def auto_builder(req: BuilderRequest):
    try:
        from unr5.auto_builder import run_builder
        import asyncio
        loop   = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, run_builder, req.prompt)
        return result
    except Exception as e:
        raise HTTPException(500, detail=str(e))