"""
Lucy Prime — Synthesizer Layer (LP4-LP7)
LP4: ResponseSynthesizer  — builds final response from Emma output + identity
LP5: TokenGenerator       — manages token budget, chunking, streaming prep
LP6: FormatEngine         — applies markdown/plain/structured output formatting
LP7: ConsistencyGuard     — checks response against memory + prior session outputs
"""

from __future__ import annotations
import re
import time
import logging
from dataclasses import dataclass, field
from typing import Any, Iterator

logger = logging.getLogger("lucy_prime.synthesizer")

MAX_RESPONSE_TOKENS    = 2048
STREAM_CHUNK_SIZE      = 64      # chars per streaming chunk
CONSISTENCY_WARN_SCORE = 0.30    # below this → add uncertainty flag
REPETITION_THRESHOLD   = 0.55    # token overlap this high → flag repetition


@dataclass
class SynthesisPacket:
    """The fully assembled response before output routing."""
    synthesis_id:     str   = ""
    raw_content:      str   = ""
    formatted_content: str  = ""
    tone:             str   = "neutral"
    format_mode:      str   = "markdown"
    token_estimate:   int   = 0
    truncated:        bool  = False
    consistency_ok:   bool  = True
    consistency_note: str   = ""
    metadata:         dict  = field(default_factory=dict)
    timestamp:        float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "synthesis_id":      self.synthesis_id,
            "formatted_content": self.formatted_content,
            "tone":              self.tone,
            "format_mode":       self.format_mode,
            "token_estimate":    self.token_estimate,
            "truncated":         self.truncated,
            "consistency_ok":    self.consistency_ok,
            "consistency_note":  self.consistency_note,
            "metadata":          self.metadata,
            "timestamp":         self.timestamp,
        }


# ─────────────────────────────────────────────
# LP4 — Response Synthesizer
# ─────────────────────────────────────────────

class LP4ResponseSynthesizer:
    """
    LP4 — Assembles the final response from:
    - Emma approved_content (post-safety)
    - Identity mission/tone markers
    - Divergence acknowledgment if consensus is low
    - Earth/FiveM/UNR5 live data enrichment if relevant
    """

    def synthesize(
        self,
        approved_content:  str,
        query:             str,
        domain:            str,
        urgency:           str,
        consensus:         str,
        divergence_notes:  list[str],
        confidence:        float,
        tone_marker:       str,
        personality_lead:  str,
        earth_context:     dict | None = None,
        fivem_context:     dict | None = None,
    ) -> str:
        parts: list[str] = []

        # Add personality lead if present
        if personality_lead and not approved_content.startswith(personality_lead):
            parts.append(personality_lead)
        else:
            parts.append(approved_content)
            return "\n\n".join(parts)

        # Main content
        parts.append(approved_content)

        # Divergence acknowledgment
        if consensus == "divergent" and divergence_notes:
            parts.append(
                "\n> ⚠ **Reasoning divergence detected** — "
                f"multiple analytical paths disagreed. "
                f"Confidence: {confidence:.0%}. Consider cross-referencing."
            )

        # Low confidence flag
        if confidence < 0.50:
            parts.append(
                f"\n> *Note: Confidence is low ({confidence:.0%}). "
                "This response reflects best available reasoning under uncertainty.*"
            )

        # Earth context enrichment
        if earth_context and domain in ("earth", "analytical", "general"):
            seismic = earth_context.get("seismic", {})
            weather = earth_context.get("weather", {})
            if seismic.get("magnitude", 0) >= 5.0:
                mag = seismic.get("magnitude", "N/A")
                loc = seismic.get("location", "unknown")
                parts.append(f"\n🌍 **Live Earth Signal**: Seismic event M{mag} near {loc}")
            if weather.get("temperature_2m", None) is not None:
                temp = weather["temperature_2m"]
                parts.append(f"\n🌡 **Live Weather**: Current temperature {temp}°C")

        # FiveM context enrichment
        if fivem_context and domain in ("fivem", "technical"):
            player_count = fivem_context.get("player_count", None)
            if player_count is not None:
                parts.append(f"\n🎮 **FiveM Live**: {player_count} players online")

        return "\n\n".join(p for p in parts if p.strip())

    def synthesize_blocked(self, query: str, block_reason: str) -> str:
        return (
            f"I was unable to process that request through the current reasoning path.\n\n"
            f"**Safety gate triggered**: The merged reasoning exceeded the risk threshold "
            f"and has been blocked before reaching output.\n\n"
            f"If you believe this is an error, please flag it for operator review. "
            f"The decision has been logged to DeltaVault for audit."
        )


# ─────────────────────────────────────────────
# LP5 — Token Generator
# ─────────────────────────────────────────────

class LP5TokenGenerator:
    """
    LP5 — Manages token budget, estimates token count, truncates if needed,
    and prepares content for streaming output.
    """

    # Rough token estimate: 1 token ≈ 4 chars
    CHARS_PER_TOKEN = 4

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // self.CHARS_PER_TOKEN)

    def enforce_budget(
        self, text: str, max_tokens: int = MAX_RESPONSE_TOKENS
    ) -> tuple[str, bool]:
        """Returns (text, truncated)."""
        if self.estimate_tokens(text) <= max_tokens:
            return text, False

        max_chars = max_tokens * self.CHARS_PER_TOKEN
        truncated = text[:max_chars]

        # Try to end at sentence boundary
        last_period = truncated.rfind(".")
        if last_period > max_chars * 0.80:
            truncated = truncated[:last_period + 1]

        truncated += "\n\n*[Response truncated — token budget reached]*"
        logger.debug(f"[LP5] truncated {len(text)} → {len(truncated)} chars")
        return truncated, True

    def stream_chunks(self, text: str, chunk_size: int = STREAM_CHUNK_SIZE) -> Iterator[str]:
        """Yields text in streaming chunks."""
        for i in range(0, len(text), chunk_size):
            yield text[i:i + chunk_size]

    def prepare(
        self, text: str, max_tokens: int = MAX_RESPONSE_TOKENS
    ) -> tuple[str, int, bool]:
        """Returns (final_text, token_estimate, truncated)."""
        final, truncated = self.enforce_budget(text, max_tokens)
        tokens = self.estimate_tokens(final)
        return final, tokens, truncated


# ─────────────────────────────────────────────
# LP6 — Format Engine
# ─────────────────────────────────────────────

FORMAT_MODES = {
    "markdown": "Rich markdown with headers, bold, bullets",
    "plain":    "Clean plain text, no markdown symbols",
    "json":     "Structured JSON payload",
    "compact":  "Minimal whitespace, single-paragraph",
    "voice":    "Natural spoken language, no symbols",
}


class LP6FormatEngine:
    """
    LP6 — Applies output formatting appropriate to channel and context.
    """

    def _strip_markdown(self, text: str) -> str:
        """Convert markdown to plain text."""
        text = re.sub(r"#{1,6}\s+", "", text)
        text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)
        text = re.sub(r"`{1,3}(.+?)`{1,3}", r"\1", text, flags=re.DOTALL)
        text = re.sub(r">\s+", "", text)
        text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
        text = re.sub(r"[-•*]\s+", "- ", text)
        return text.strip()

    def _to_voice(self, text: str) -> str:
        """Strip all non-speech symbols for TTS."""
        text = self._strip_markdown(text)
        text = re.sub(r"[^\w\s.,!?;:()\-']", " ", text)
        text = re.sub(r"\s{2,}", " ", text)
        return text.strip()

    def _to_compact(self, text: str) -> str:
        """Single paragraph, stripped headers."""
        text = self._strip_markdown(text)
        text = re.sub(r"\n{2,}", " ", text)
        return text.strip()

    def format(
        self,
        content:     str,
        mode:        str = "markdown",
        add_header:  str | None = None,
    ) -> str:
        if mode == "plain":
            result = self._strip_markdown(content)
        elif mode == "voice":
            result = self._to_voice(content)
        elif mode == "compact":
            result = self._to_compact(content)
        elif mode == "json":
            import json
            result = json.dumps({"response": content, "timestamp": time.time()}, indent=2)
        else:  # markdown (default)
            result = content
            if add_header:
                result = f"## {add_header}\n\n{content}"

        return result

    def detect_mode(
        self,
        output_channel: str = "text",
        domain:         str = "general",
    ) -> str:
        """Auto-detect format mode from channel."""
        channel_map = {
            "voice":   "voice",
            "mobile":  "compact",
            "api":     "json",
            "stream":  "markdown",
            "text":    "markdown",
            "mr":      "markdown",
        }
        return channel_map.get(output_channel, "markdown")


# ─────────────────────────────────────────────
# LP7 — Consistency Guard
# ─────────────────────────────────────────────

class LP7ConsistencyGuard:
    """
    LP7 — Checks current response against session memory for contradictions
    and repetition. Produces consistency score + optional warning note.
    """

    STOP_WORDS = {
        "the","a","an","is","are","was","were","it","this","that",
        "of","to","in","on","at","for","and","or","but","with","by","i","you"
    }

    def _tokenize(self, text: str) -> set[str]:
        return {
            t.strip(".,!?;:\"'()")
            for t in text.lower().split()
            if t not in self.STOP_WORDS and len(t) > 3
        }

    def check(
        self,
        current_content: str,
        session_history:  list[str],
    ) -> tuple[bool, float, str]:
        """
        Returns (consistent, score, note).
        score: 1.0 = fully consistent, 0.0 = highly contradictory.
        """
        if not session_history:
            return True, 1.0, ""

        current_tokens = self._tokenize(current_content)

        # Check against last 3 responses
        recent = session_history[-3:]
        overlap_scores: list[float] = []
        for prev in recent:
            prev_tokens = self._tokenize(prev)
            if not prev_tokens or not current_tokens:
                continue
            overlap = len(current_tokens & prev_tokens) / max(len(current_tokens), 1)
            overlap_scores.append(overlap)

        if not overlap_scores:
            return True, 1.0, ""

        avg_overlap = sum(overlap_scores) / len(overlap_scores)

        # High overlap = repetition
        if avg_overlap >= REPETITION_THRESHOLD:
            note = (
                f"*This response covers similar ground to recent outputs "
                f"(overlap={avg_overlap:.0%}). For fresh perspective, try rephrasing.*"
            )
            return True, round(1.0 - avg_overlap, 4), note

        # Very low overlap with high-confidence history = potential inconsistency
        if avg_overlap < 0.05 and len(session_history) >= 3:
            note = (
                "*Note: This response diverges significantly from recent session context. "
                "Verify alignment with prior reasoning.*"
            )
            return True, round(avg_overlap + 0.3, 4), note

        return True, 1.0, ""

    def check_with_memory(
        self,
        current_content: str,
        session_id:      str,
    ) -> tuple[bool, float, str]:
        """Pulls session history from memory system automatically."""
        try:
            from memory.memory_core import memory_system
            stm = memory_system.stm.get_recent(session_id, n=5)
            history = [e.content for e in stm]
            return self.check(current_content, history)
        except Exception as e:
            logger.debug(f"[LP7] memory check skipped: {e}")
            return True, 1.0, ""


# ─────────────────────────────────────────────
# Synthesizer Layer orchestrator
# ─────────────────────────────────────────────

class SynthesizerLayer:
    """
    Wires LP4 → LP5 → LP6 → LP7 into one call.
    Used by Lucy Prime's response builder.
    """

    def __init__(self):
        self.lp4 = LP4ResponseSynthesizer()
        self.lp5 = LP5TokenGenerator()
        self.lp6 = LP6FormatEngine()
        self.lp7 = LP7ConsistencyGuard()

    def build(
        self,
        approved_content:   str,
        query:              str,
        session_id:         str,
        domain:             str          = "general",
        urgency:            str          = "medium",
        consensus:          str          = "none",
        divergence_notes:   list[str]    = None,
        confidence:         float        = 0.7,
        tone:               str          = "neutral",
        personality_lead:   str          = "",
        output_channel:     str          = "text",
        earth_context:      dict | None  = None,
        fivem_context:      dict | None  = None,
        blocked:            bool         = False,
        block_reason:       str          = "",
        max_tokens:         int          = MAX_RESPONSE_TOKENS,
    ) -> SynthesisPacket:

        import uuid
        packet = SynthesisPacket(synthesis_id=str(uuid.uuid4())[:8])
        packet.tone = tone

        # LP4 — synthesize raw content
        if blocked:
            raw = self.lp4.synthesize_blocked(query, block_reason)
        else:
            raw = self.lp4.synthesize(
                approved_content  = approved_content,
                query             = query,
                domain            = domain,
                urgency           = urgency,
                consensus         = consensus,
                divergence_notes  = divergence_notes or [],
                confidence        = confidence,
                tone_marker       = tone,
                personality_lead  = personality_lead,
                earth_context     = earth_context,
                fivem_context     = fivem_context,
            )
        packet.raw_content = raw

        # LP5 — token budget
        budgeted, tokens, truncated = self.lp5.prepare(raw, max_tokens)
        packet.token_estimate = tokens
        packet.truncated      = truncated

        # LP6 — format
        format_mode = self.lp6.detect_mode(output_channel, domain)
        packet.format_mode        = format_mode
        packet.formatted_content  = self.lp6.format(budgeted, mode=format_mode)

        # LP7 — consistency
        ok, score, note = self.lp7.check_with_memory(
            budgeted, session_id
        )
        packet.consistency_ok   = ok
        packet.consistency_note = note
        if note:
            packet.formatted_content += f"\n\n{note}"

        packet.metadata = {
            "domain":    domain,
            "urgency":   urgency,
            "consensus": consensus,
            "blocked":   blocked,
            "confidence": confidence,
        }

        logger.info(
            f"[SynthesizerLayer] synthesis_id={packet.synthesis_id} "
            f"tokens={tokens} truncated={truncated} "
            f"format={format_mode} consistency_ok={ok}"
        )
        return packet


# Singletons
lp4_synthesizer   = LP4ResponseSynthesizer()
lp5_tokens        = LP5TokenGenerator()
lp6_format        = LP6FormatEngine()
lp7_consistency   = LP7ConsistencyGuard()
synthesizer_layer = SynthesizerLayer()