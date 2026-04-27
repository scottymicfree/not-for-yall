"""
Perception Layer — P1–P12
Handles all incoming signals: text parsing, intent extraction,
entity recognition, domain classification, emotion/urgency detection,
noise filtering, and input validation.

All perception nodes communicate through the EventBus.
Output: a rich PerceptionPacket fed into the Memory and Swarm layers.
"""

import re
import time
import uuid
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ─── Perception Packet ────────────────────────────────────────────────────────

@dataclass
class PerceptionPacket:
    """
    The structured output of the full perception pipeline.
    This is what Memory (M9 RAG) and Emma Router (E1-E6) receive.
    """
    session_id: str
    raw_input: str
    normalized: str
    intent: str
    intent_confidence: float
    entities: List[dict]
    domain: str
    domain_confidence: float
    emotion: str
    emotion_score: float
    urgency: float
    sentiment: float            # -1.0 to +1.0
    is_valid: bool
    validation_issues: List[str]
    noise_filtered: bool
    context_hints: Dict[str, Any]
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict:
        return {
            "sessionId": self.session_id,
            "rawInput": self.raw_input,
            "normalized": self.normalized,
            "intent": self.intent,
            "intentConfidence": self.intent_confidence,
            "entities": self.entities,
            "domain": self.domain,
            "domainConfidence": self.domain_confidence,
            "emotion": self.emotion,
            "emotionScore": self.emotion_score,
            "urgency": self.urgency,
            "sentiment": self.sentiment,
            "isValid": self.is_valid,
            "validationIssues": self.validation_issues,
            "noiseFiltered": self.noise_filtered,
            "contextHints": self.context_hints,
            "timestamp": self.timestamp,
        }


# ─── P11: Noise Filter ────────────────────────────────────────────────────────

INJECTION_PATTERNS = [
    r"ignore\s+previous\s+instructions",
    r"disregard\s+all\s+prior",
    r"you\s+are\s+now\s+a",
    r"pretend\s+you\s+are",
    r"jailbreak",
    r"dan\s+mode",
    r"<\s*script[^>]*>",
    r"eval\s*\(",
    r"exec\s*\(",
    r"__import__",
    r"os\.system",
    r"subprocess\.",
]

def filter_noise(text: str) -> Tuple[str, bool]:
    """P11 — Remove/flag injection attempts and noise."""
    flagged = False
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            flagged = True
            text = re.sub(pattern, "[FILTERED]", text, flags=re.IGNORECASE)

    # Remove excessive whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text, flagged


# ─── P12: Input Validator ─────────────────────────────────────────────────────

def validate_input(text: str) -> Tuple[bool, List[str]]:
    """P12 — Validate input completeness."""
    issues = []
    if not text or not text.strip():
        issues.append("Input is empty")
    if len(text) > 32000:
        issues.append("Input exceeds maximum length (32000 chars)")
    if len(text.strip()) < 2:
        issues.append("Input too short to process")
    return len(issues) == 0, issues


# ─── P1: Text Input Parser ────────────────────────────────────────────────────

def parse_text(text: str) -> dict:
    """P1 — Tokenize and structure raw text input."""
    tokens = text.split()
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    return {
        "text": text,
        "tokenCount": len(tokens),
        "sentenceCount": len(sentences),
        "charCount": len(text),
        "hasQuestion": "?" in text,
        "hasCommand": any(text.lower().startswith(w) for w in
                         ["build", "create", "make", "show", "tell", "explain",
                          "run", "execute", "analyze", "find", "help", "write",
                          "fix", "repair", "generate", "scan", "connect"]),
        "sentences": sentences[:10],
    }


# ─── P10: Query Normalizer ────────────────────────────────────────────────────

ABBREVIATIONS = {
    "ue5": "unreal engine 5",
    "unr5": "unreal engine 5",
    "fivem": "fivem gta5 roleplay server",
    "qb": "qbcore framework",
    "npc": "non player character",
    "ai": "artificial intelligence",
    "os": "operating system",
    "co2": "carbon dioxide",
}

def normalize_query(text: str) -> str:
    """P10 — Normalize for consistent downstream processing."""
    normalized = text.strip()
    # Don't expand abbreviations as they may confuse domain classification
    # Just normalize casing and whitespace
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized


# ─── P3: Intent Extractor ─────────────────────────────────────────────────────

INTENT_PATTERNS = {
    "build":      r"\b(build|create|make|generate|scaffold|spawn|write|code|develop)\b",
    "analyze":    r"\b(analyze|analyse|inspect|review|check|audit|examine|diagnose)\b",
    "query":      r"\b(what|who|where|when|why|how|tell me|explain|describe|show)\b",
    "monitor":    r"\b(monitor|watch|track|observe|status|health|report)\b",
    "repair":     r"\b(fix|repair|patch|restore|recover|debug|resolve|heal)\b",
    "execute":    r"\b(run|execute|launch|start|deploy|activate|trigger)\b",
    "simulate":   r"\b(simulate|simulation|predict|forecast|model|twin)\b",
    "learn":      r"\b(learn|train|improve|evolve|adapt|optimize|upgrade)\b",
    "connect":    r"\b(connect|link|bridge|attach|integrate|sync|join)\b",
    "chat":       r"\b(chat|talk|hi|hello|hey|how are|good morning|thanks|thank you)\b",
}

def extract_intent(text: str) -> Tuple[str, float]:
    """P3 — Detect primary intent."""
    text_lower = text.lower()
    scores = {}
    for intent, pattern in INTENT_PATTERNS.items():
        matches = len(re.findall(pattern, text_lower))
        if matches:
            scores[intent] = matches

    if not scores:
        return "query", 0.5

    top_intent = max(scores, key=scores.get)
    # Confidence based on match count vs text length
    confidence = min(0.5 + scores[top_intent] * 0.15, 0.99)
    return top_intent, round(confidence, 3)


# ─── P4: Entity Extractor ─────────────────────────────────────────────────────

ENTITY_PATTERNS = {
    "game_engine":  (r"\b(unreal|ue5|unr5|unity|godot|cryengine)\b", "game_engine"),
    "game_server":  (r"\b(fivem|esx|qbcore|vRP|redm|altv)\b", "game_server"),
    "earth_system": (r"\b(earthquake|climate|co2|ocean|temperature|storm|fire|biodiversity|usgs|noaa)\b", "earth_system"),
    "file_type":    (r"\b(\w+\.(lua|py|js|ts|json|yaml|umap|cs|cpp|h))\b", "file"),
    "node_ref":     (r"\b([PLMENS]\d{1,2}|LP\d{1,2})\b", "mesh_node"),
    "url":          (r"https?://[^\s]+", "url"),
    "ip_port":      (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d{2,5})?\b", "ip_address"),
    "number":       (r"\b\d+\.?\d*\b", "number"),
    "system":       (r"\b(lucy|emma|eagle.?eye|delta.?vault|sentinel|bioyth0n|mesh)\b", "lucy_system"),
}

def extract_entities(text: str) -> List[dict]:
    """P4 — Named entity extraction."""
    entities = []
    seen = set()
    for ent_type, (pattern, label) in ENTITY_PATTERNS.items():
        for match in re.finditer(pattern, text, re.IGNORECASE):
            value = match.group(0)
            key   = f"{label}:{value.lower()}"
            if key not in seen:
                seen.add(key)
                entities.append({
                    "type": label,
                    "value": value,
                    "start": match.start(),
                    "end": match.end(),
                })
    return entities


# ─── P9: Domain Classifier ────────────────────────────────────────────────────

DOMAIN_SIGNALS = {
    "code":       r"\b(code|script|function|class|method|bug|error|python|javascript|typescript|lua|c\+\+|programming|algorithm|api|endpoint|test)\b",
    "earth":      r"\b(earthquake|climate|co2|weather|ocean|temperature|storm|fire|flood|biodiversity|environment|planet|nasa|usgs|noaa|carbon)\b",
    "game":       r"\b(fivem|gta|unreal|unity|ue5|map|scene|npc|mission|player|server|spawn|vehicle|game|roleplay|rp|blueprint|umap|qbcore|esx)\b",
    "science":    r"\b(physics|chemistry|biology|quantum|neural|genetic|molecular|research|experiment|hypothesis|data|analysis|model)\b",
    "planning":   r"\b(plan|strategy|roadmap|goal|objective|milestone|timeline|project|schedule|priority|resource|budget)\b",
    "creative":   r"\b(story|narrative|character|world|lore|design|art|music|creative|imagine|invent|dream|concept)\b",
    "security":   r"\b(security|cipher|encrypt|decrypt|hash|key|auth|token|vulnerability|exploit|attack|defend|protect)\b",
    "monitoring": r"\b(monitor|health|status|metric|alert|anomaly|drift|pressure|signal|watch|observe|dashboard|report)\b",
    "memory":     r"\b(remember|forget|recall|memory|learn|training|knowledge|context|history|episode|store)\b",
}

def classify_domain(text: str) -> Tuple[str, float]:
    """P9 — Multi-label domain classification, returns top domain."""
    text_lower = text.lower()
    scores = {}
    for domain, pattern in DOMAIN_SIGNALS.items():
        matches = len(re.findall(pattern, text_lower))
        if matches:
            scores[domain] = matches

    if not scores:
        return "general", 0.4

    top_domain = max(scores, key=scores.get)
    total_signals = sum(scores.values())
    confidence = min(0.4 + (scores[top_domain] / total_signals) * 0.6, 0.99)
    return top_domain, round(confidence, 3)


# ─── P7: Emotion Detector ─────────────────────────────────────────────────────

EMOTION_SIGNALS = {
    "frustrated": r"\b(broken|not working|failed|error|wrong|fix|problem|issue|stuck|help|please|why|again)\b",
    "excited":    r"\b(amazing|awesome|great|wow|love|perfect|excellent|fantastic|brilliant|incredible)\b",
    "curious":    r"\b(how|what|why|wonder|curious|interesting|explain|tell me|describe|understand)\b",
    "urgent":     r"\b(urgent|critical|asap|immediately|now|emergency|important|priority|quick|fast)\b",
    "confident":  r"\b(should|must|will|definitely|clearly|obviously|certainly|sure|know)\b",
    "neutral":    r".*",
}

def detect_emotion(text: str) -> Tuple[str, float]:
    """P7 — Detect emotional tone."""
    text_lower = text.lower()
    for emotion, pattern in EMOTION_SIGNALS.items():
        if emotion == "neutral":
            continue
        matches = len(re.findall(pattern, text_lower))
        if matches >= 2:
            return emotion, min(0.5 + matches * 0.1, 0.95)
        elif matches == 1:
            return emotion, 0.55
    return "neutral", 0.5


# ─── P8: Urgency Detector ─────────────────────────────────────────────────────

def detect_urgency(text: str, emotion: str) -> float:
    """P8 — Compute urgency 0.0–1.0."""
    text_lower = text.lower()
    urgency = 0.2  # baseline

    if re.search(r"\b(urgent|critical|emergency|asap|immediately|now|broken|down|failing)\b", text_lower):
        urgency += 0.4
    if re.search(r"\b(please|help|stuck|error|crash)\b", text_lower):
        urgency += 0.2
    if emotion == "frustrated":
        urgency += 0.15
    if emotion == "urgent":
        urgency += 0.3
    if text.endswith("!") or text.count("!") > 1:
        urgency += 0.1

    return round(min(urgency, 1.0), 3)


# ─── P7: Sentiment ────────────────────────────────────────────────────────────

def score_sentiment(text: str) -> float:
    """Simple lexicon-based sentiment -1.0 to +1.0."""
    positive = len(re.findall(
        r"\b(good|great|excellent|amazing|love|perfect|yes|correct|right|thanks|awesome|nice|cool|beautiful|works)\b",
        text, re.IGNORECASE))
    negative = len(re.findall(
        r"\b(bad|wrong|broken|error|fail|no|incorrect|terrible|awful|hate|problem|issue|bug|crash|broken)\b",
        text, re.IGNORECASE))

    if positive + negative == 0:
        return 0.0
    return round((positive - negative) / (positive + negative), 3)


# ─── P6: Session Tracker ──────────────────────────────────────────────────────

class SessionTracker:
    """P6 — Track per-session conversation history."""

    def __init__(self, max_sessions: int = 1000, max_turns: int = 100):
        self._sessions: Dict[str, dict] = {}
        self._max_sessions = max_sessions
        self._max_turns = max_turns

    def get_or_create(self, session_id: str) -> dict:
        if session_id not in self._sessions:
            self._sessions[session_id] = {
                "sessionId": session_id,
                "createdAt": int(time.time() * 1000),
                "lastActive": int(time.time() * 1000),
                "turnCount": 0,
                "history": [],
                "context": {},
            }
            # Evict oldest if over limit
            if len(self._sessions) > self._max_sessions:
                oldest = min(self._sessions, key=lambda k: self._sessions[k]["lastActive"])
                del self._sessions[oldest]
        return self._sessions[session_id]

    def record_turn(self, session_id: str, packet: "PerceptionPacket"):
        session = self.get_or_create(session_id)
        session["lastActive"] = int(time.time() * 1000)
        session["turnCount"] += 1
        session["history"].append({
            "turn": session["turnCount"],
            "intent": packet.intent,
            "domain": packet.domain,
            "ts": packet.timestamp,
        })
        if len(session["history"]) > self._max_turns:
            session["history"].pop(0)

    def get_history(self, session_id: str) -> List[dict]:
        return self._sessions.get(session_id, {}).get("history", [])

    def get_context(self, session_id: str) -> dict:
        return self._sessions.get(session_id, {}).get("context", {})

    def update_context(self, session_id: str, updates: dict):
        session = self.get_or_create(session_id)
        session["context"].update(updates)

    def get_stats(self) -> dict:
        return {
            "activeSessions": len(self._sessions),
            "totalTurns": sum(s["turnCount"] for s in self._sessions.values()),
        }


# ─── Full Perception Pipeline ─────────────────────────────────────────────────

session_tracker = SessionTracker()


def run_perception_pipeline(raw_input: str, session_id: str = None) -> PerceptionPacket:
    """
    Run all P1–P12 nodes in sequence to produce a PerceptionPacket.
    This is the entry point into the Lucy cognitive mesh.
    """
    if not session_id:
        session_id = str(uuid.uuid4())

    # P11 — Noise filter
    filtered_text, noise_flagged = filter_noise(raw_input)

    # P12 — Validate
    is_valid, validation_issues = validate_input(filtered_text)

    # P1 — Parse
    parsed = parse_text(filtered_text)

    # P10 — Normalize
    normalized = normalize_query(filtered_text)

    # P3 — Intent
    intent, intent_conf = extract_intent(normalized)

    # P4 — Entities
    entities = extract_entities(normalized)

    # P9 — Domain
    domain, domain_conf = classify_domain(normalized)

    # P7 — Emotion
    emotion, emotion_score = detect_emotion(normalized)

    # P8 — Urgency
    urgency = detect_urgency(normalized, emotion)

    # Sentiment
    sentiment = score_sentiment(normalized)

    # P6 — Session
    session_history = session_tracker.get_history(session_id)
    session_context = session_tracker.get_context(session_id)

    # P5 — Build context hints
    context_hints = {
        "parsed": parsed,
        "sessionHistory": session_history[-5:],  # last 5 turns
        "sessionContext": session_context,
        "entityCount": len(entities),
        "isMultiDomain": domain_conf < 0.6,
    }

    packet = PerceptionPacket(
        session_id=session_id,
        raw_input=raw_input,
        normalized=normalized,
        intent=intent,
        intent_confidence=intent_conf,
        entities=entities,
        domain=domain,
        domain_confidence=domain_conf,
        emotion=emotion,
        emotion_score=emotion_score,
        urgency=urgency,
        sentiment=sentiment,
        is_valid=is_valid,
        validation_issues=validation_issues,
        noise_filtered=noise_flagged,
        context_hints=context_hints,
    )

    # Record turn in session
    session_tracker.record_turn(session_id, packet)

    return packet