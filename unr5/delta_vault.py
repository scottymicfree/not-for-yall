"""
DeltaVault — blockchain-style append-only audit ledger.
Python port of deltavault/ledger.ts
Only approved actions are recorded. Each entry is SHA-256 chained.
"""

import hashlib
import json
import time
import random
import string
import threading
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Any


def _build_entry_id() -> str:
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"dv_{int(time.time() * 1000)}_{suffix}"


def _canonicalize(value: Any) -> str:
    """Stable JSON serialization — keys sorted recursively."""
    def _sort_keys(obj):
        if isinstance(obj, dict):
            return {k: _sort_keys(v) for k, v in sorted(obj.items())}
        if isinstance(obj, list):
            return [_sort_keys(i) for i in obj]
        return obj
    return json.dumps(_sort_keys(value), separators=(',', ':'))


def _compute_hash(entry_id: str, timestamp: int, action_type: str,
                  decision: str, payload: Any, reason: str,
                  previous_hash: Optional[str]) -> str:
    parts = [
        entry_id,
        str(timestamp),
        action_type,
        decision,
        _canonicalize(payload),
        reason,
        previous_hash if previous_hash is not None else "GENESIS",
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass
class DeltaVaultEntry:
    id: str
    timestamp: int
    action_type: str
    decision: str  # always "approved"
    payload: Any
    reason: str
    previous_hash: Optional[str]
    entry_hash: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "actionType": self.action_type,
            "decision": self.decision,
            "payload": self.payload,
            "reason": self.reason,
            "previousHash": self.previous_hash,
            "entryHash": self.entry_hash,
        }


class DeltaVault:
    """Thread-safe blockchain-style audit ledger."""

    def __init__(self):
        self._ledger: List[DeltaVaultEntry] = []
        self._lock = threading.RLock()

    def append_approved(self, action_type: str, payload: Any, reason: str) -> DeltaVaultEntry:
        with self._lock:
            entry_id = _build_entry_id()
            timestamp = int(time.time() * 1000)
            previous_hash = self._ledger[-1].entry_hash if self._ledger else None

            entry_hash = _compute_hash(
                entry_id, timestamp, action_type, "approved",
                payload, reason, previous_hash
            )

            entry = DeltaVaultEntry(
                id=entry_id,
                timestamp=timestamp,
                action_type=action_type,
                decision="approved",
                payload=payload,
                reason=reason,
                previous_hash=previous_hash,
                entry_hash=entry_hash,
            )
            self._ledger.append(entry)
            return entry

    def get_entries(self) -> List[dict]:
        with self._lock:
            return [e.to_dict() for e in self._ledger]

    def verify_integrity(self) -> dict:
        with self._lock:
            for i, entry in enumerate(self._ledger):
                expected_prev = None if i == 0 else self._ledger[i - 1].entry_hash

                if entry.previous_hash != expected_prev:
                    return {"ok": False, "checked": i + 1, "brokenAt": entry.id}

                recomputed = _compute_hash(
                    entry.id, entry.timestamp, entry.action_type,
                    entry.decision, entry.payload, entry.reason,
                    entry.previous_hash
                )
                if entry.entry_hash != recomputed:
                    return {"ok": False, "checked": i + 1, "brokenAt": entry.id}

            return {"ok": True, "checked": len(self._ledger), "brokenAt": None}

    def recent_entries(self, window_ms: int = 300_000) -> List[dict]:
        """Entries from the last window_ms milliseconds (default 5 min)."""
        now = int(time.time() * 1000)
        with self._lock:
            return [e.to_dict() for e in self._ledger if now - e.timestamp <= window_ms]

    def clear(self):
        """Test helper — clears ledger."""
        with self._lock:
            self._ledger.clear()


# Singleton
delta_vault = DeltaVault()