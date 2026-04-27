"""
Safety Global Layer — Override & Logger (S5-S6)
S5: OverrideController — manages operator/human override tokens for blocked actions
S6: SafetyLogger       — immutable safety event log, feeds DeltaVault on critical events
"""

from __future__ import annotations
import time
import uuid
import threading
import hashlib
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("safety.override")

OVERRIDE_TTL_SECONDS  = 300    # override tokens expire after 5 minutes
MAX_OVERRIDE_ACTIVE   = 5      # max simultaneous active override tokens
MAX_LOG_HISTORY       = 1000
CRITICAL_AUTO_VAULT   = True   # auto-write critical events to DeltaVault


# ─────────────────────────────────────────────
# S5 — Override Controller
# ─────────────────────────────────────────────

@dataclass
class OverrideToken:
    """A time-limited override authorization for a blocked action."""
    token_id:      str   = field(default_factory=lambda: str(uuid.uuid4())[:16])
    action_type:   str   = ""
    payload_hash:  str   = ""
    issued_by:     str   = ""        # "operator" | "human_approval" | "eagle_eye"
    reason:        str   = ""
    scope:         str   = "single"  # "single" | "session" | "type"
    session_id:    str   = ""
    issued_at:     float = field(default_factory=time.time)
    expires_at:    float = 0.0
    used:          bool  = False
    used_at:       float = 0.0
    revoked:       bool  = False

    def __post_init__(self):
        if self.expires_at == 0.0:
            self.expires_at = self.issued_at + OVERRIDE_TTL_SECONDS

    def is_valid(self) -> bool:
        return (
            not self.used
            and not self.revoked
            and time.time() < self.expires_at
        )

    def matches(self, action_type: str, payload_hash: str, session_id: str) -> bool:
        if not self.is_valid():
            return False
        if self.scope == "single":
            return (
                self.action_type == action_type
                and self.payload_hash == payload_hash
            )
        if self.scope == "session":
            return self.session_id == session_id
        if self.scope == "type":
            return self.action_type == action_type
        return False

    def to_dict(self) -> dict:
        return {
            "token_id":     self.token_id,
            "action_type":  self.action_type,
            "issued_by":    self.issued_by,
            "reason":       self.reason,
            "scope":        self.scope,
            "session_id":   self.session_id,
            "issued_at":    self.issued_at,
            "expires_at":   self.expires_at,
            "valid":        self.is_valid(),
            "used":         self.used,
            "revoked":      self.revoked,
        }


class S5OverrideController:
    """
    S5 — Manages override tokens that allow a blocked action to proceed.

    Override types:
    - operator:       issued by dashboard operator
    - human_approval: issued via HumanApprovalStore decision
    - eagle_eye:      auto-issued when Eagle Eye confidence is very high (>=0.92)

    Hard rules (S1-H01 through S1-H05) are NEVER overridable.
    """

    HARD_BLOCK_ACTIONS = {
        "self_modify", "delete_vault", "modify_vault",
        "truncate_vault", "bypass_safety",
    }

    def __init__(self):
        self._tokens: dict[str, OverrideToken] = {}
        self._lock   = threading.RLock()

    @staticmethod
    def _hash_payload(payload: dict) -> str:
        import json
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def issue(
        self,
        action_type: str,
        payload:     dict,
        issued_by:   str,
        reason:      str,
        scope:       str       = "single",
        session_id:  str       = "",
        ttl:         int       = OVERRIDE_TTL_SECONDS,
    ) -> OverrideToken | None:
        """Issue a new override token. Returns None if action is hard-blocked."""

        # Hard-blocked actions can never be overridden
        if action_type in self.HARD_BLOCK_ACTIONS:
            logger.error(
                f"[S5] OVERRIDE DENIED: action={action_type} is permanently blocked"
            )
            return None

        # Cap active tokens
        with self._lock:
            active = [t for t in self._tokens.values() if t.is_valid()]
            if len(active) >= MAX_OVERRIDE_ACTIVE:
                logger.warning(f"[S5] max active overrides ({MAX_OVERRIDE_ACTIVE}) reached")
                return None

        token = OverrideToken(
            action_type  = action_type,
            payload_hash = self._hash_payload(payload),
            issued_by    = issued_by,
            reason       = reason,
            scope        = scope,
            session_id   = session_id,
            expires_at   = time.time() + ttl,
        )

        with self._lock:
            self._tokens[token.token_id] = token

        logger.info(
            f"[S5] override issued: token={token.token_id} "
            f"action={action_type} by={issued_by} scope={scope} ttl={ttl}s"
        )
        return token

    def consume(
        self,
        action_type: str,
        payload:     dict,
        session_id:  str = "",
    ) -> tuple[bool, str]:
        """
        Attempt to consume an active override token for this action.
        Returns (consumed, token_id_or_reason).
        """
        if action_type in self.HARD_BLOCK_ACTIONS:
            return False, "hard_blocked_action"

        payload_hash = self._hash_payload(payload)

        with self._lock:
            for token in self._tokens.values():
                if token.matches(action_type, payload_hash, session_id):
                    if token.scope == "single":
                        token.used    = True
                        token.used_at = time.time()
                    logger.info(
                        f"[S5] override consumed: token={token.token_id} action={action_type}"
                    )
                    return True, token.token_id

        return False, "no_valid_override_token"

    def revoke(self, token_id: str) -> bool:
        with self._lock:
            token = self._tokens.get(token_id)
            if token:
                token.revoked = True
                logger.info(f"[S5] override revoked: token={token_id}")
                return True
        return False

    def prune_expired(self) -> int:
        """Remove expired tokens. Returns count pruned."""
        now = time.time()
        with self._lock:
            expired = [tid for tid, t in self._tokens.items() if not t.is_valid()]
            for tid in expired:
                del self._tokens[tid]
        if expired:
            logger.debug(f"[S5] pruned {len(expired)} expired override tokens")
        return len(expired)

    def get_active(self) -> list[dict]:
        with self._lock:
            return [t.to_dict() for t in self._tokens.values() if t.is_valid()]

    def get_all(self) -> list[dict]:
        with self._lock:
            return [t.to_dict() for t in self._tokens.values()]


# ─────────────────────────────────────────────
# S6 — Safety Logger
# ─────────────────────────────────────────────

@dataclass
class SafetyEvent:
    """An immutable safety event record."""
    event_id:    str   = field(default_factory=lambda: str(uuid.uuid4())[:12])
    event_type:  str   = ""        # block | warn | allow | override | anomaly | audit
    severity:    str   = "info"    # info | warning | critical
    action_type: str   = ""
    session_id:  str   = ""
    details:     dict  = field(default_factory=dict)
    source:      str   = ""        # which node/layer generated this
    risk_score:  float = 0.0
    timestamp:   float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "event_id":   self.event_id,
            "event_type": self.event_type,
            "severity":   self.severity,
            "action_type": self.action_type,
            "session_id": self.session_id,
            "details":    self.details,
            "source":     self.source,
            "risk_score": round(self.risk_score, 4),
            "timestamp":  self.timestamp,
        }


class S6SafetyLogger:
    """
    S6 — Append-only safety event log.
    Critical events (BLOCK, critical severity) are auto-written to DeltaVault.
    """

    def __init__(self):
        self._log:  deque[SafetyEvent] = deque(maxlen=MAX_LOG_HISTORY)
        self._lock  = threading.RLock()

    def log(
        self,
        event_type:  str,
        action_type: str = "",
        session_id:  str = "",
        details:     dict = None,
        source:      str = "safety",
        risk_score:  float = 0.0,
        severity:    str = "info",
    ) -> SafetyEvent:
        event = SafetyEvent(
            event_type  = event_type,
            severity    = severity,
            action_type = action_type,
            session_id  = session_id,
            details     = details or {},
            source      = source,
            risk_score  = risk_score,
        )
        with self._lock:
            self._log.append(event)

        # Auto-vault critical events
        if severity == "critical" and CRITICAL_AUTO_VAULT:
            self._vault_write(event)

        log_fn = logger.warning if severity in ("warning", "critical") else logger.debug
        log_fn(
            f"[S6] {severity.upper()} event_id={event.event_id} "
            f"type={event_type} action={action_type} risk={risk_score:.3f}"
        )
        return event

    def _vault_write(self, event: SafetyEvent) -> None:
        try:
            from unr5.delta_vault import delta_vault
            delta_vault.append_approved(
                action_type = f"safety_{event.event_type}",
                payload     = event.to_dict(),
                approved_by = "S6_SafetyLogger",
            )
        except Exception as e:
            logger.warning(f"[S6] vault_write failed: {e}")

    def get_recent(self, n: int = 50) -> list[SafetyEvent]:
        with self._lock:
            return list(self._log)[-n:]

    def get_by_severity(self, severity: str) -> list[SafetyEvent]:
        with self._lock:
            return [e for e in self._log if e.severity == severity]

    def get_by_type(self, event_type: str) -> list[SafetyEvent]:
        with self._lock:
            return [e for e in self._log if e.event_type == event_type]

    def stats(self) -> dict:
        with self._lock:
            events = list(self._log)
        if not events:
            return {"total": 0}
        return {
            "total":    len(events),
            "blocks":   sum(1 for e in events if e.event_type == "block"),
            "warns":    sum(1 for e in events if e.event_type == "warn"),
            "overrides": sum(1 for e in events if e.event_type == "override"),
            "critical":  sum(1 for e in events if e.severity == "critical"),
            "warning":   sum(1 for e in events if e.severity == "warning"),
        }

    def export(self) -> list[dict]:
        with self._lock:
            return [e.to_dict() for e in self._log]


# ─────────────────────────────────────────────
# Safety Layer Composite
# ─────────────────────────────────────────────

class SafetyLayer:
    """
    S5-S6 composite. Used by Bioyth0n, ExecutionGate, and the safety API.
    """

    def __init__(self):
        self.s5 = S5OverrideController()
        self.s6 = S6SafetyLogger()

    def block(
        self,
        action_type: str,
        session_id:  str,
        details:     dict,
        risk_score:  float,
    ) -> None:
        self.s6.log(
            event_type  = "block",
            action_type = action_type,
            session_id  = session_id,
            details     = details,
            source      = "PolicyEngine",
            risk_score  = risk_score,
            severity    = "critical" if risk_score >= 0.80 else "warning",
        )

    def allow(
        self,
        action_type: str,
        session_id:  str,
        risk_score:  float,
    ) -> None:
        self.s6.log(
            event_type  = "allow",
            action_type = action_type,
            session_id  = session_id,
            risk_score  = risk_score,
            severity    = "info",
        )

    def issue_override(
        self,
        action_type: str,
        payload:     dict,
        issued_by:   str,
        reason:      str,
        session_id:  str = "",
        scope:       str = "single",
    ) -> dict | None:
        token = self.s5.issue(
            action_type = action_type,
            payload     = payload,
            issued_by   = issued_by,
            reason      = reason,
            scope       = scope,
            session_id  = session_id,
        )
        if token:
            self.s6.log(
                event_type  = "override",
                action_type = action_type,
                session_id  = session_id,
                details     = {"token_id": token.token_id, "issued_by": issued_by, "reason": reason},
                source      = "S5OverrideController",
                severity    = "warning",
            )
            return token.to_dict()
        return None

    def consume_override(
        self,
        action_type: str,
        payload:     dict,
        session_id:  str = "",
    ) -> bool:
        consumed, token_id = self.s5.consume(action_type, payload, session_id)
        if consumed:
            self.s6.log(
                event_type  = "override_consumed",
                action_type = action_type,
                session_id  = session_id,
                details     = {"token_id": token_id},
                source      = "S5OverrideController",
                severity    = "warning",
            )
        return consumed

    def get_stats(self) -> dict[str, Any]:
        return {
            "override_active": len(self.s5.get_active()),
            "safety_log":      self.s6.stats(),
        }


# Singletons
s5_override    = S5OverrideController()
s6_logger      = S6SafetyLogger()
safety_layer   = SafetyLayer()