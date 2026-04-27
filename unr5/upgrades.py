"""
Upgrade Proposal Store
Python port of upgrades/proposalStore.js

Lucy or operators can propose system upgrades. Emma reviews them.
Approved upgrades are logged in DeltaVault.
"""

import time
import threading
import random
import string
from typing import Optional, List


def _build_proposal_id() -> str:
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"up_{int(time.time() * 1000)}_{suffix}"


class UpgradeProposalStore:
    """Thread-safe upgrade proposal registry."""

    def __init__(self):
        self._proposals: list = []
        self._lock = threading.RLock()

    def get_proposals(self) -> list:
        with self._lock:
            return [dict(p) for p in self._proposals]

    def create_proposal(self, title: str, summary: str, proposed_by: str, category: str) -> dict:
        with self._lock:
            entry = {
                "id": _build_proposal_id(),
                "title": title,
                "summary": summary,
                "proposedBy": proposed_by,
                "category": category,
                "status": "pending",
                "createdAt": int(time.time() * 1000),
                "decidedAt": None,
                "decidedBy": None,
                "decisionReason": "",
            }
            self._proposals.append(entry)
            return dict(entry)

    def decide_proposal(self, proposal_id: str, decision: str, decided_by: str, reason: str = "") -> Optional[dict]:
        with self._lock:
            for p in self._proposals:
                if p["id"] == proposal_id:
                    if p["status"] != "pending":
                        return dict(p)
                    p["status"] = decision
                    p["decidedAt"] = int(time.time() * 1000)
                    p["decidedBy"] = decided_by
                    p["decisionReason"] = reason
                    return dict(p)
            return None

    def get_by_status(self, status: str) -> list:
        with self._lock:
            return [dict(p) for p in self._proposals if p["status"] == status]

    def clear(self):
        with self._lock:
            self._proposals.clear()


# Singleton
upgrade_store = UpgradeProposalStore()