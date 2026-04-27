"""
Lucy Prime — Master Orchestrator (LP1-LP12)
Single entry point: takes Emma pipeline result → produces DispatchedResponse.
This is the top-level cognitive integration node of Lucy OS v5.
"""

from __future__ import annotations
import asyncio
import time
import logging
from typing import Any

from lucy_prime.identity    import lp1_identity, lp2_tone, lp3_personality
from lucy_prime.synthesizer import synthesizer_layer, SynthesisPacket
from lucy_prime.output      import lp12_dispatcher, DispatchedResponse

logger = logging.getLogger("lucy_prime")


class LucyPrime:
    """
    Lucy Prime Master Orchestrator.

    Execution flow:
      Emma pipeline result
        → LP1  identity.record_query()
        → LP2  tone selection
        → LP3  personality blend
        → LP4-LP7  synthesizer_layer.build()
        → LP8-LP12 lp12_dispatcher.dispatch()
        → DispatchedResponse
    """

    async def respond(
        self,
        emma_result:    Any,          # EmmaPipelineResult from emma_mesh.pipeline
        query:          str,
        session_id:     str    = "default",
        output_channel: str    = "text",
        earth_context:  dict | None = None,
        fivem_context:  dict | None = None,
    ) -> DispatchedResponse:

        t0 = time.time()

        # ── LP1: Identity tracking ────────────────────────────────────
        lp1_identity.record_query()
        lp1_identity.update_lte(emma_result.lte_score)

        # Shorthand aliases from Emma result
        approved_content  = emma_result.approved_content
        blocked           = emma_result.blocked
        confidence        = emma_result.confidence
        consensus         = emma_result.consensus
        divergence_notes  = emma_result.merged.divergence_notes
        domain            = emma_result.routing.domain
        urgency           = emma_result.routing.urgency
        lte_score         = emma_result.lte_score

        # ── LP2: Tone selection ───────────────────────────────────────
        self_state = lp12_dispatcher.lp11.get().state
        emotion    = emma_result.routing.context_injected.get("emotion", "neutral")

        tone = lp2_tone.select_tone(
            emotion    = emotion,
            domain     = domain,
            urgency    = urgency,
            self_state = self_state,
        )
        toned_content = lp2_tone.apply_tone(approved_content, tone)

        # ── LP3: Personality blend ────────────────────────────────────
        personality_lead = lp3_personality.blend(
            content   = toned_content,
            tone      = tone,
            consensus = consensus,
            domain    = domain,
        )

        # ── LP4-LP7: Synthesizer layer ────────────────────────────────
        packet: SynthesisPacket = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: synthesizer_layer.build(
                approved_content  = toned_content,
                query             = query,
                session_id        = session_id,
                domain            = domain,
                urgency           = urgency,
                consensus         = consensus,
                divergence_notes  = divergence_notes,
                confidence        = confidence,
                tone              = tone,
                personality_lead  = personality_lead,
                output_channel    = output_channel,
                earth_context     = earth_context,
                fivem_context     = fivem_context,
                blocked           = blocked,
                block_reason      = emma_result.safety.block_reason if blocked else "",
            )
        )

        # ── LP8-LP12: Dispatch ────────────────────────────────────────
        dispatched: DispatchedResponse = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: lp12_dispatcher.dispatch(
                packet     = packet,
                session_id = session_id,
                query      = query,
                lte_score  = lte_score,
                confidence = confidence,
                blocked    = blocked,
                channel    = output_channel,
            )
        )

        elapsed_ms = round((time.time() - t0) * 1000, 1)
        logger.info(
            f"[LucyPrime] dispatch_id={dispatched.dispatch_id} "
            f"session={session_id} domain={domain} tone={tone} "
            f"lte={lte_score:.1f} state={dispatched.self_state} "
            f"ms={elapsed_ms}"
        )
        return dispatched

    def respond_sync(
        self,
        emma_result:    Any,
        query:          str,
        session_id:     str    = "default",
        output_channel: str    = "text",
        earth_context:  dict | None = None,
        fivem_context:  dict | None = None,
    ) -> DispatchedResponse:
        """Synchronous wrapper."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    fut = pool.submit(
                        asyncio.run,
                        self.respond(
                            emma_result, query, session_id,
                            output_channel, earth_context, fivem_context
                        )
                    )
                    return fut.result(timeout=20)
            else:
                return loop.run_until_complete(
                    self.respond(
                        emma_result, query, session_id,
                        output_channel, earth_context, fivem_context
                    )
                )
        except Exception as e:
            logger.error(f"[LucyPrime] respond_sync error: {e}")
            raise

    def get_self_state(self) -> dict:
        return lp12_dispatcher.get_self_state()

    def get_identity_profile(self) -> dict:
        return lp1_identity.full_profile()

    def get_reflection_queue(self) -> int:
        return lp12_dispatcher.get_reflection_queue_size()


# Singleton
lucy_prime = LucyPrime()