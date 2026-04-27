"""
Human Approval System
Python port of humanapproval/deriveHumanApprovalState.ts + decisionStore.js

When Eagle Eye is trusted, medium/high risk Emma approvals surface for
human visibility. Humans can then approve or reject via the API.
"""

import time
import threading
import random
import string
from typing import List, Optional


def _build_id() -> str:
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"ha_{int(time.time() * 1000)}_{suffix}"


class HumanApprovalStore:
    """Thread-safe store for human approval decisions."""

    def __init__(self):
        self._decisions: list = []
        self._lock = threading.RLock()

    def get_decisions(self) -> list:
        with self._lock:
            return list(self._decisions)

    def record_decision(self, item_id: str, decision: str, decided_by: str, reason: str = "") -> dict:
        with self._lock:
            entry = {
                "id": _build_id(),
                "itemId": item_id,
                "decision": decision,
                "decidedBy": decided_by,
                "reason": reason,
                "decidedAt": int(time.time() * 1000),
            }
            self._decisions.append(entry)
            return entry

    def clear(self):
        with self._lock:
            self._decisions.clear()


def derive_human_approval_state(
    emma_reviews: list,
    eagle_eye: dict,
    human_decisions: list = None,
) -> dict:
    """
    If Eagle Eye is NOT trusted → returns empty, invisible report.
    If trusted → surfaces all medium/high Emma approvals for human visibility.
    Filters out items that already have a human decision.
    """
    human_decisions = human_decisions or []
    items = []

    if not eagle_eye.get("trusted", False):
        return {
            "timestamp": int(time.time() * 1000),
            "pendingCount": 0,
            "visible": False,
            "items": items,
        }

    decided_item_ids = {d["itemId"] for d in human_decisions}

    for idx, review in enumerate(emma_reviews):
        if review.get("decision") != "approved":
            continue
        if review.get("level") == "low":
            continue

        item_id = f"ha_{review.get('approvedAt', 0)}_{review.get('level', 'med')}_{idx}"
        if item_id in decided_item_ids:
            continue

        items.append({
            "id": item_id,
            "level": review.get("level"),
            "reason": review.get("reason", ""),
            "createdAt": review.get("approvedAt", int(time.time() * 1000)),
            "status": "pending-human-visibility",
        })

    return {
        "timestamp": int(time.time() * 1000),
        "pendingCount": len(items),
        "visible": len(items) > 0,
        "items": items,
    }


def derive_execution_gate_state(eagle_eye: dict, delta_vault_integrity: dict, human_decisions: list) -> dict:
    """
    Execution gate opens only when:
    1. DeltaVault integrity is verified
    2. Eagle Eye is trusted
    3. At least one human-approved decision exists
    """
    reasons = []

    if not delta_vault_integrity.get("ok"):
        reasons.append("DeltaVault integrity is not verified.")
    if not eagle_eye.get("trusted"):
        reasons.append("Eagle Eye is not trusted.")

    approved_human = [d for d in (human_decisions or []) if d.get("decision") == "approved"]
    if not approved_human:
        reasons.append("No human-approved decisions exist.")

    return {
        "timestamp": int(time.time() * 1000),
        "ready": len(reasons) == 0,
        "blocked": len(reasons) > 0,
        "reasons": reasons,
        "approvedDecisionCount": len(approved_human),
    }


def build_simulation_packet(execution_gate: dict, human_decisions: list, ledger_entries: list) -> dict:
    """Build a dry-run simulation packet if the execution gate is open."""
    reasons = execution_gate.get("reasons", [])

    approved_decisions = sorted(
        [d for d in (human_decisions or []) if d.get("decision") == "approved"],
        key=lambda d: d.get("decidedAt", 0),
        reverse=True,
    )
    approved_decision = approved_decisions[0] if approved_decisions else None

    sorted_ledger = sorted(ledger_entries or [], key=lambda e: e.get("timestamp", 0), reverse=True)
    latest_ledger = sorted_ledger[0] if sorted_ledger else None

    ready = bool(execution_gate.get("ready")) and bool(approved_decision)

    return {
        "timestamp": int(time.time() * 1000),
        "simulationOnly": True,
        "readyForSimulation": ready,
        "blocked": not ready,
        "reasons": [] if ready else (reasons if reasons else ["Simulation gate is not satisfied."]),
        "packetPreview": {
            "sourceHumanDecisionId": approved_decision["id"],
            "sourceItemId": approved_decision["itemId"],
            "decidedBy": approved_decision["decidedBy"],
            "decidedAt": approved_decision["decidedAt"],
            "latestLedgerEntryId": latest_ledger["id"] if latest_ledger else None,
            "latestLedgerActionType": latest_ledger["actionType"] if latest_ledger else None,
            "mode": "dry-run",
        } if ready else None,
    }


# Singleton
human_approval_store = HumanApprovalStore()