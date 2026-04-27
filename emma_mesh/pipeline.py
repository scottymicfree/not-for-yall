"""
Emma Supervisory Mesh — Full Pipeline Orchestrator (E1-E24)
Wires Router → Evaluator → Merger → Safety → Auditor into one async call.
This is the single entry point used by Lucy Prime and the DAG scheduler.
"""

from __future__ import annotations
import asyncio
import time
import logging
from typing import Any

from emma_mesh.router   import emma_router,    RoutingDecision
from emma_mesh.evaluator import emma_evaluator, ScoredCandidate
from emma_mesh.merger   import emma_merger,    MergedReasoning
from emma_mesh.safety   import emma_safety,    SafetyReport
from emma_mesh.auditor  import emma_auditor

logger = logging.getLogger("emma.pipeline")


class EmmaPipelineResult:
    """Full output of one Emma pipeline run."""

    def __init__(
        self,
        routing:   RoutingDecision,
        candidates: list[ScoredCandidate],
        merged:    MergedReasoning,
        safety:    SafetyReport,
        audit:     dict,
    ):
        self.routing    = routing
        self.candidates = candidates
        self.merged     = merged
        self.safety     = safety
        self.audit      = audit

        # Convenience shortcuts used by Lucy Prime
        self.approved_content: str   = (
            safety.redacted_content if safety.verdict != "BLOCK" else ""
        )
        self.blocked:           bool  = (safety.verdict == "BLOCK")
        self.confidence:        float = merged.merged_confidence
        self.consensus:         str   = merged.consensus
        self.lte_score:         float = audit.get("lte_score", 0.0)
        self.audit_id:          str   = audit.get("audit_id", "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_id":         self.audit_id,
            "approved_content": self.approved_content[:800],
            "blocked":          self.blocked,
            "confidence":       round(self.confidence, 4),
            "consensus":        self.consensus,
            "lte_score":        round(self.lte_score, 2),
            "safety_verdict":   self.safety.verdict,
            "risk_tier":        self.safety.risk_tier,
            "risk_score":       round(self.safety.risk_score, 4),
            "merge_strategy":   self.merged.merge_strategy,
            "candidate_count":  self.merged.candidate_count,
            "dominant_agent":   self.merged.dominant_agent,
            "contributors":     self.merged.contributor_agents,
            "routing": {
                "domain":          self.routing.domain,
                "urgency":         self.routing.urgency,
                "selected_agents": self.routing.selected_agents,
                "routing_score":   round(self.routing.routing_score, 4),
                "fallback":        self.routing.fallback_triggered,
            },
        }


class EmmaPipeline:
    """
    Full E1-E24 Emma Supervisory Mesh pipeline.

    Call flow:
      run(perception_packet, swarm_outputs, query, session_id)
        → E1-E6 Route
        → E7-E12 Evaluate
        → E13-E16 Merge
        → E17-E20 Safety
        → E21-E24 Audit
        → EmmaPipelineResult
    """

    async def run(
        self,
        perception_packet:    dict[str, Any],
        swarm_outputs:        list[dict[str, Any]],
        query:                str,
        session_id:           str = "default",
        memory_context:       dict | None = None,
        required_capabilities: list[str] | None = None,
        top_k:                int = 5,
    ) -> EmmaPipelineResult:

        pipeline_start = time.time()
        logger.info(
            f"[EmmaPipeline] START session={session_id} "
            f"swarm_outputs={len(swarm_outputs)} query_len={len(query)}"
        )

        # ── E1-E6: Route ──────────────────────────────────────────────
        routing = await emma_router.route_async(
            perception_packet      = perception_packet,
            session_id             = session_id,
            memory_context         = memory_context,
            required_capabilities  = required_capabilities,
        )
        logger.debug(f"[EmmaPipeline] routing done: {routing.selected_agents}")

        # ── E7-E12: Evaluate ──────────────────────────────────────────
        # Run in thread pool (CPU-bound scoring)
        loop = asyncio.get_event_loop()
        candidates: list[ScoredCandidate] = await loop.run_in_executor(
            None,
            lambda: emma_evaluator.evaluate(swarm_outputs, query, top_k=top_k),
        )
        eval_report = {
            "count":     len(candidates),
            "top_score": candidates[0].composite if candidates else 0.0,
            "avg_score": round(sum(c.composite for c in candidates) / max(len(candidates), 1), 4),
        }
        logger.debug(f"[EmmaPipeline] evaluation done: {len(candidates)} candidates")

        # ── E13-E16: Merge ────────────────────────────────────────────
        merged: MergedReasoning = await loop.run_in_executor(
            None,
            lambda: emma_merger.merge(candidates),
        )
        merge_report = merged.to_dict()
        logger.debug(f"[EmmaPipeline] merge done: confidence={merged.merged_confidence:.4f}")

        # ── E17-E20: Safety ───────────────────────────────────────────
        safety: SafetyReport = await loop.run_in_executor(
            None,
            lambda: emma_safety.evaluate(merged),
        )
        safety_report = safety.to_dict()
        logger.debug(f"[EmmaPipeline] safety done: verdict={safety.verdict}")

        # ── E21-E24: Audit ────────────────────────────────────────────
        audit_report = await loop.run_in_executor(
            None,
            lambda: emma_auditor.audit(
                session_id        = session_id,
                query             = query,
                routing_result    = routing.to_dict(),
                eval_result       = eval_report,
                merge_result      = merge_report,
                safety_result     = safety_report,
                aggregated_traces = merged.aggregated_traces,
                pipeline_start_ts = pipeline_start,
            ),
        )
        logger.debug(f"[EmmaPipeline] audit done: lte={audit_report.get('lte_score',0):.1f}")

        result = EmmaPipelineResult(
            routing    = routing,
            candidates = candidates,
            merged     = merged,
            safety     = safety,
            audit      = audit_report,
        )

        elapsed_ms = round((time.time() - pipeline_start) * 1000, 1)
        logger.info(
            f"[EmmaPipeline] DONE audit_id={result.audit_id} "
            f"blocked={result.blocked} confidence={result.confidence:.4f} "
            f"lte={result.lte_score:.1f} ms={elapsed_ms}"
        )
        return result

    def run_sync(
        self,
        perception_packet:    dict[str, Any],
        swarm_outputs:        list[dict[str, Any]],
        query:                str,
        session_id:           str = "default",
        memory_context:       dict | None = None,
        required_capabilities: list[str] | None = None,
        top_k:                int = 5,
    ) -> EmmaPipelineResult:
        """Synchronous wrapper for non-async callers."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        asyncio.run,
                        self.run(
                            perception_packet, swarm_outputs, query,
                            session_id, memory_context, required_capabilities, top_k,
                        )
                    )
                    return future.result(timeout=30)
            else:
                return loop.run_until_complete(
                    self.run(
                        perception_packet, swarm_outputs, query,
                        session_id, memory_context, required_capabilities, top_k,
                    )
                )
        except Exception as e:
            logger.error(f"[EmmaPipeline] run_sync error: {e}")
            raise


# Singleton
emma_pipeline = EmmaPipeline()