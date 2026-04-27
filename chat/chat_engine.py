"""
Lucy OS v5 — Chat Engine
Full conversational core that runs the complete cognitive pipeline:
Perception → Memory → Swarm → Emma → Lucy Prime → Response
"""

from __future__ import annotations
import asyncio
import time
import uuid
import logging
from typing import Any, AsyncIterator

logger = logging.getLogger("chat.engine")


class ChatEngine:
    """
    Lucy's conversational core.
    Orchestrates the full 137-node cognitive pipeline per message.
    """

    def __init__(self):
        self._sessions: dict[str, list[dict]] = {}

    def _get_session(self, session_id: str) -> list[dict]:
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        return self._sessions[session_id]

    async def chat(
        self,
        message:        str,
        session_id:     str  = "default",
        output_channel: str  = "text",
        user_id:        str  = "user",
    ) -> dict[str, Any]:
        """
        Full pipeline chat call.
        Returns a rich response dict with content + metadata.
        """
        t0 = time.time()
        history = self._get_session(session_id)

        # ── Step 1: Perception pipeline (P1-P12) ──────────────────────
        perception_packet = await self._run_perception(message, session_id)

        # ── Step 2: Memory RAG retrieval ──────────────────────────────
        memory_context = await self._run_memory_rag(message, session_id)

        # ── Step 3: Swarm reasoning (L1-L48) ─────────────────────────
        swarm_outputs = await self._run_swarm(perception_packet, memory_context)

        # ── Step 4: Emma pipeline (E1-E24) ────────────────────────────
        emma_result = await self._run_emma(
            perception_packet, swarm_outputs, message, session_id, memory_context
        )

        # ── Step 5: Lucy Prime (LP1-LP12) ────────────────────────────
        dispatched = await self._run_lucy_prime(
            emma_result, message, session_id, output_channel
        )

        # ── Build response ────────────────────────────────────────────
        elapsed_ms = round((time.time() - t0) * 1000, 1)
        response = {
            "message_id":   str(uuid.uuid4())[:8],
            "session_id":   session_id,
            "content":      dispatched.content,
            "suppressed":   dispatched.suppressed,
            "tone":         dispatched.tone,
            "domain":       dispatched.domain,
            "self_state":   dispatched.self_state,
            "lte_score":    dispatched.lte_score,
            "confidence":   dispatched.confidence,
            "consensus":    emma_result.consensus,
            "safe":         dispatched.safe,
            "memory":       dispatched.memory_written,
            "elapsed_ms":   elapsed_ms,
            "timestamp":    time.time(),
        }

        # Store in session history
        history.append({
            "role":    "user",
            "content": message,
            "ts":      time.time(),
        })
        history.append({
            "role":    "lucy",
            "content": dispatched.content,
            "ts":      time.time(),
        })

        logger.info(
            f"[ChatEngine] session={session_id} "
            f"lte={dispatched.lte_score:.1f} "
            f"state={dispatched.self_state} "
            f"ms={elapsed_ms}"
        )
        return response

    async def stream(
        self,
        message:    str,
        session_id: str = "default",
    ) -> AsyncIterator[str]:
        """
        Streaming chat — yields response chunks as they're available.
        Runs pipeline first, then streams the response text.
        """
        result = await self.chat(message, session_id, output_channel="stream")
        content = result.get("content", "")

        # Yield metadata header chunk
        yield f"[META] lte={result['lte_score']:.1f} domain={result['domain']}\n\n"

        # Stream content in chunks
        from lucy_prime.synthesizer import lp5_tokens
        for chunk in lp5_tokens.stream_chunks(content, chunk_size=80):
            yield chunk
            await asyncio.sleep(0.01)   # simulate streaming delay

        yield "\n[END]"

    async def _run_perception(self, message: str, session_id: str) -> dict:
        try:
            from perception.parser import run_perception_pipeline
            return run_perception_pipeline(message, session_id)
        except Exception as e:
            logger.warning(f"[ChatEngine] perception fallback: {e}")
            return {
                "text":      message,
                "intent":    "general_query",
                "domain":    "general",
                "urgency":   "medium",
                "emotion":   "neutral",
                "entities":  {},
                "sentiment": 0.0,
                "valid":     True,
            }

    async def _run_memory_rag(self, message: str, session_id: str) -> dict:
        try:
            from memory.memory_core import memory_system
            rag_results = memory_system.recall(message, session_id)
            facts       = memory_system.semantic.search(message, top_k=3)
            persona     = memory_system.persona.get_all()
            return {
                "rag_results":    rag_results,
                "facts":          facts,
                "persona":        persona,
                "recent_topics":  [r.get("content", "")[:80] for r in rag_results[:3]],
            }
        except Exception as e:
            logger.debug(f"[ChatEngine] memory rag fallback: {e}")
            return {"rag_results": [], "facts": [], "persona": {}, "recent_topics": []}

    async def _run_swarm(
        self,
        perception_packet: dict,
        memory_context:    dict,
    ) -> list[dict]:
        try:
            from swarm.swarm_runner import swarm_runner
            domain  = perception_packet.get("domain", "general")
            urgency = perception_packet.get("urgency", "medium")
            text    = perception_packet.get("text", "")
            results = await swarm_runner.run_swarm(
                query   = text,
                domain  = domain,
                urgency = urgency,
                context = memory_context,
            )
            return [r.to_dict() if hasattr(r, "to_dict") else r for r in results]
        except Exception as e:
            logger.warning(f"[ChatEngine] swarm fallback: {e}")
            return [{
                "agent_id":   "L1",
                "agent_type": "analytical",
                "content":    f"Direct reasoning on: {perception_packet.get('text','')[:200]}",
                "confidence": 0.65,
            }]

    async def _run_emma(
        self,
        perception_packet: dict,
        swarm_outputs:     list[dict],
        query:             str,
        session_id:        str,
        memory_context:    dict,
    ):
        try:
            from emma_mesh.pipeline import emma_pipeline
            return await emma_pipeline.run(
                perception_packet = perception_packet,
                swarm_outputs     = swarm_outputs,
                query             = query,
                session_id        = session_id,
                memory_context    = memory_context,
            )
        except Exception as e:
            logger.warning(f"[ChatEngine] emma fallback: {e}")
            # Minimal fallback Emma result
            return _FallbackEmmaResult(query)

    async def _run_lucy_prime(
        self,
        emma_result,
        query:          str,
        session_id:     str,
        output_channel: str,
    ):
        try:
            from lucy_prime.prime import lucy_prime
            return await lucy_prime.respond(
                emma_result    = emma_result,
                query          = query,
                session_id     = session_id,
                output_channel = output_channel,
            )
        except Exception as e:
            logger.warning(f"[ChatEngine] lucy_prime fallback: {e}")
            return _FallbackDispatchedResponse(
                content = emma_result.approved_content or query,
                session_id = session_id,
            )

    def get_history(self, session_id: str, n: int = 20) -> list[dict]:
        return self._get_session(session_id)[-n:]

    def clear_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def get_sessions(self) -> list[str]:
        return list(self._sessions.keys())


# ─────────────────────────────────────────────
# Fallback objects (used when sub-systems unavailable)
# ─────────────────────────────────────────────

class _FallbackEmmaResult:
    def __init__(self, query: str):
        self.approved_content = f"I processed your message: {query[:200]}"
        self.blocked          = False
        self.confidence       = 0.60
        self.consensus        = "none"
        self.lte_score        = 50.0
        self.audit_id         = "fallback"
        self.merged           = type("M", (), {"divergence_notes": []})()
        self.routing          = type("R", (), {
            "domain": "general", "urgency": "medium",
            "selected_agents": ["L1"], "context_injected": {}
        })()
        self.safety           = type("S", (), {"block_reason": "", "verdict": "PASS"})()


class _FallbackDispatchedResponse:
    def __init__(self, content: str, session_id: str):
        self.content           = content
        self.suppressed        = False
        self.tone              = "neutral"
        self.domain            = "general"
        self.self_state        = "nominal"
        self.lte_score         = 50.0
        self.confidence        = 0.60
        self.safe              = True
        self.memory_written    = {}
        self.dispatch_id       = str(uuid.uuid4())[:8]


# Singleton
chat_engine = ChatEngine()