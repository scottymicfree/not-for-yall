"""
LTE API — FastAPI router for the Lucy Telemetry Engine
Endpoints: scores, stats, trends, raw signals, subsystem snapshots, anomalies, SSE stream
"""

from __future__ import annotations
import time
import asyncio
import json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from lte.emma_grader import lte_grader, LTEScore
from lte.telemetry   import telemetry

# ── Router ─────────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/lte", tags=["lte"])

# ── Request / Response Models ──────────────────────────────────────────────────

class GradeRequest(BaseModel):
    confidence:      float = 0.70
    top_score:       float = 0.70
    risk:            float = 0.25
    routing_quality: float = 0.80
    consensus:       str   = "partial"
    blocked:         bool  = False
    redacted:        bool  = False
    novelty:         float = 0.60
    latency_ms:      float = 0.0
    agent_timeout:   bool  = False
    session_id:      Optional[str] = None
    query_id:        Optional[str] = None

class GradeResponse(BaseModel):
    raw:               float
    grade:             str
    components:        Dict[str, float]
    deductions:        Dict[str, float]
    total_deductions:  float
    consensus:         str
    blocked:           bool
    latency_ms:        float
    healthy:           bool
    timestamp:         float

class PushSignalRequest(BaseModel):
    subsystem: str
    metric:    str
    value:     float
    unit:      str = ""
    tags:      Dict[str, str] = {}

class AnomalyResponse(BaseModel):
    anomalies: Dict[str, str]
    count:     int
    timestamp: float

# ── Helper ─────────────────────────────────────────────────────────────────────

def _score_to_response(s: LTEScore) -> GradeResponse:
    return GradeResponse(
        raw=s.raw,
        grade=s.grade,
        components=s.components,
        deductions=s.deductions,
        total_deductions=s.total_deductions,
        consensus=s.consensus,
        blocked=s.blocked,
        latency_ms=s.latency_ms,
        healthy=s.healthy,
        timestamp=s.timestamp,
    )

# ── LTE Grader Endpoints ───────────────────────────────────────────────────────

@router.post("/grade", response_model=GradeResponse, summary="Grade a single Emma result")
async def grade_result(req: GradeRequest):
    """
    Submit an Emma pipeline result payload and receive a typed LTE score.
    Grade table: S(≥90) A(≥80) B(≥70) C(≥55) D(≥40) F(<40)
    """
    score = lte_grader.grade(req.dict())
    return _score_to_response(score)

@router.get("/scores/recent", summary="Recent LTE scores")
async def recent_scores(limit: int = Query(default=20, le=200)):
    """Return the last N LTE scores in reverse-chronological order."""
    return {
        "scores": lte_grader.recent(limit=limit),
        "count":  min(limit, lte_grader.stats()["history_length"]),
        "timestamp": time.time(),
    }

@router.get("/scores/session/{session_id}", summary="LTE scores for a session")
async def session_scores(session_id: str):
    """Return all LTE scores recorded for a specific session."""
    scores = lte_grader.session_scores(session_id)
    avg    = lte_grader.session_avg(session_id)
    return {
        "session_id": session_id,
        "scores":     scores,
        "count":      len(scores),
        "avg_lte":    avg,
        "timestamp":  time.time(),
    }

@router.get("/stats", summary="LTE grader aggregate statistics")
async def lte_stats():
    """Return aggregate LTE statistics: avg, health rate, grade distribution."""
    s = lte_grader.stats()
    h = lte_grader.health_snapshot()
    return {
        "stats":     s,
        "health":    h,
        "timestamp": time.time(),
    }

@router.get("/trend", summary="LTE rolling trend")
async def lte_trend(window: int = Query(default=50, le=500)):
    """Return trend analysis over the last N scores (improving / stable / declining)."""
    return {
        "trend":     lte_grader.trend(window=window),
        "timestamp": time.time(),
    }

@router.get("/percentile", summary="LTE percentile score")
async def lte_percentile(p: float = Query(default=50.0, ge=0.0, le=100.0)):
    """Return the p-th percentile LTE score across all graded results."""
    return {
        "percentile": p,
        "value":      lte_grader.percentile(p),
        "timestamp":  time.time(),
    }

@router.get("/grades/distribution", summary="LTE grade distribution")
async def grade_distribution():
    """Return percentage breakdown across grade tiers S/A/B/C/D/F."""
    return {
        "distribution": lte_grader.grade_distribution(),
        "total":        lte_grader.stats()["total_scored"],
        "timestamp":    time.time(),
    }

# ── Telemetry Endpoints ────────────────────────────────────────────────────────

@router.get("/telemetry/snapshot", summary="Full telemetry snapshot")
async def telemetry_snapshot():
    """Return aggregated telemetry windows for all subsystems."""
    return telemetry.snapshot()

@router.get("/telemetry/dashboard", summary="Dashboard summary tile data")
async def dashboard_summary():
    """Compact per-subsystem summary for live dashboard tiles."""
    return {
        "summary":   telemetry.dashboard_summary(),
        "timestamp": time.time(),
    }

@router.get("/telemetry/subsystem/{name}", summary="Single subsystem telemetry")
async def subsystem_telemetry(name: str):
    """Return detailed metric windows for one subsystem."""
    snap = telemetry.subsystem_snapshot(name)
    if "error" in snap:
        raise HTTPException(status_code=404, detail=snap["error"])
    return {"subsystem": name, "metrics": snap, "timestamp": time.time()}

@router.get("/telemetry/raw", summary="Raw signal ring-buffer")
async def raw_signals(
    subsystem: Optional[str] = Query(default=None),
    limit:     int           = Query(default=100, le=500)
):
    """Return recent raw telemetry signals, optionally filtered by subsystem."""
    signals = telemetry.raw_signals(subsystem=subsystem, limit=limit)
    return {
        "signals":   signals,
        "count":     len(signals),
        "subsystem": subsystem or "all",
        "timestamp": time.time(),
    }

@router.post("/telemetry/push", summary="Push a telemetry signal")
async def push_signal(req: PushSignalRequest):
    """Manually push a telemetry signal into the engine (for external integrations)."""
    telemetry.push(req.subsystem, req.metric, req.value, req.unit, req.tags)
    return {
        "pushed":    True,
        "subsystem": req.subsystem,
        "metric":    req.metric,
        "value":     req.value,
        "timestamp": time.time(),
    }

@router.get("/telemetry/anomalies", response_model=AnomalyResponse,
            summary="Active telemetry anomalies")
async def get_anomalies():
    """Return currently active anomaly flags detected by the telemetry engine."""
    a = telemetry.anomalies()
    return AnomalyResponse(
        anomalies=a,
        count=len(a),
        timestamp=time.time(),
    )

@router.delete("/telemetry/anomalies/{subsystem}/{metric}",
               summary="Clear a specific anomaly flag")
async def clear_anomaly(subsystem: str, metric: str):
    """Manually clear an anomaly flag after investigation."""
    telemetry.clear_anomaly(subsystem, metric)
    return {"cleared": True, "subsystem": subsystem, "metric": metric,
            "timestamp": time.time()}

@router.get("/telemetry/export", summary="Export telemetry as JSON")
async def export_telemetry(subsystem: Optional[str] = Query(default=None)):
    """Export full or subsystem-scoped telemetry as downloadable JSON."""
    raw_json = telemetry.export_json(subsystem=subsystem)
    return StreamingResponse(
        iter([raw_json]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=lucy_telemetry.json"},
    )

# ── SSE Live Stream ────────────────────────────────────────────────────────────

@router.get("/telemetry/stream", summary="SSE live telemetry dashboard stream")
async def telemetry_sse(interval: float = Query(default=1.0, ge=0.5, le=10.0)):
    """
    Server-Sent Events stream of dashboard telemetry summaries.
    Connect with EventSource('/lte/telemetry/stream') in the browser.
    """
    async def event_generator():
        try:
            async for summary in telemetry.stream_dashboard(interval=interval):
                payload = json.dumps({"data": summary, "timestamp": time.time()})
                yield f"data: {payload}\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

# ── Ingest Convenience Endpoints ───────────────────────────────────────────────

@router.post("/ingest/emma", summary="Ingest Emma pipeline result into telemetry")
async def ingest_emma(data: Dict[str, Any]):
    """Push an EmmaPipelineResult dict into the telemetry engine and grade it."""
    telemetry.ingest_emma_result(data)
    score = lte_grader.grade(data)
    return {
        "ingested":  True,
        "lte_score": score.raw,
        "grade":     score.grade,
        "healthy":   score.healthy,
        "timestamp": time.time(),
    }

@router.post("/ingest/lucy_prime", summary="Ingest Lucy Prime metrics")
async def ingest_lucy_prime(data: Dict[str, Any]):
    telemetry.ingest_lucy_prime(data)
    return {"ingested": True, "subsystem": "lucy_prime", "timestamp": time.time()}

@router.post("/ingest/swarm", summary="Ingest swarm metrics")
async def ingest_swarm(data: Dict[str, Any]):
    telemetry.ingest_swarm(data)
    return {"ingested": True, "subsystem": "swarm", "timestamp": time.time()}

@router.post("/ingest/fivem", summary="Ingest FiveM bridge metrics")
async def ingest_fivem(data: Dict[str, Any]):
    telemetry.ingest_fivem(data)
    return {"ingested": True, "subsystem": "fivem", "timestamp": time.time()}

@router.post("/ingest/bioyth0n", summary="Ingest Bioyth0n execution metrics")
async def ingest_bioyth0n(data: Dict[str, Any]):
    telemetry.ingest_bioyth0n(data)
    return {"ingested": True, "subsystem": "bioyth0n", "timestamp": time.time()}

@router.post("/ingest/safety", summary="Ingest safety layer metrics")
async def ingest_safety(data: Dict[str, Any]):
    telemetry.ingest_safety(data)
    return {"ingested": True, "subsystem": "safety", "timestamp": time.time()}

# ── Health ─────────────────────────────────────────────────────────────────────

@router.get("/health", summary="LTE subsystem health check")
async def lte_health():
    """Quick health check for the LTE subsystem."""
    h = lte_grader.health_snapshot()
    a = telemetry.anomalies()
    status = "degraded" if a else ("healthy" if h["avg_lte"] >= 60 else "warning")
    return {
        "status":      status,
        "avg_lte":     h["avg_lte"],
        "health_rate": h["health_rate_pct"],
        "anomalies":   len(a),
        "trend":       h["trend"],
        "timestamp":   time.time(),
    }