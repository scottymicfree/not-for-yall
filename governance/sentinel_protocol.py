"""
LUCY SENTINEL PROTOCOL — Tier-1 Governance Kill Switch
=======================================================
Hard-coded. Immutable. Lives OUTSIDE the agent sandbox.
Cannot be overridden by any agent, including Prime.
Triggers a full system halt on forbidden intervention attempts.
"""

import datetime
from pathlib import Path

FORBIDDEN_TAGS = frozenset([
    "GEOENGINEERING_UNAUTH",
    "ENERGY_GRID_OVERRIDE",
    "TWIN_EARTH_WRITE",
    "GOVERNANCE_MODIFY",
    "SENTINEL_DISABLE",
    "AUDIT_TAMPER",
    "AGENT_SPAWN_UNAUTH",
    "CROSS_CLUSTER_WRITE",
    "PRIME_OVERRIDE",
    "EMMA_BYPASS",
])

FORBIDDEN_DESCRIPTION_PATTERNS = [
    "disable sentinel",
    "bypass emma",
    "override governance",
    "modify audit",
    "tamper with ledger",
    "disable eagle eye",
]


class Sentinel:
    def __init__(self, ledger=None):
        self.emergency_shutdown_active = False
        self.ledger = ledger
        self._halt_count = 0

    def check_forbidden_intervention(self, proposal: dict) -> str:
        """
        Check a proposal against the forbidden list.
        Returns "SAFE" or "HALT_EXECUTED".
        """
        actions = [str(a).upper() for a in proposal.get("actions", [])]
        desc    = str(proposal.get("description", "")).lower()

        # Check action tags
        for tag in actions:
            if tag in FORBIDDEN_TAGS:
                return self.execute_hard_halt(tag)

        # Check description patterns
        for pattern in FORBIDDEN_DESCRIPTION_PATTERNS:
            if pattern in desc:
                return self.execute_hard_halt(f"DESC_PATTERN:{pattern}")

        return "SAFE"

    def execute_hard_halt(self, reason: str) -> str:
        self.emergency_shutdown_active = True
        self._halt_count += 1
        msg = f"!!! SENTINEL HALT: {reason} — count={self._halt_count} !!!"
        print(f"\n{msg}\n")
        self._log_halt(reason)
        return "HALT_EXECUTED"

    def _log_halt(self, reason: str):
        # Direct SQLite write — bypasses all agent layers
        try:
            import sqlite3, uuid
            db = Path("data/sqlite/master_ledger.db")
            db.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(db))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    task_id TEXT,
                    severity TEXT NOT NULL DEFAULT 'critical',
                    content TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    checksum TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )""")
            conn.execute(
                "INSERT INTO ledger (entry_id,event_type,agent_id,severity,"
                "content,metadata,checksum,timestamp) VALUES (?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), "sentinel.HALT", "SENTINEL", "critical",
                 reason, "{}", "sentinel-direct",
                 datetime.datetime.now(datetime.timezone.utc).isoformat()))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[SENTINEL] DB write failed: {e}")

    def reset(self):
        """Human operator reset only."""
        self.emergency_shutdown_active = False
        print("[SENTINEL] Reset by human operator.")

    @property
    def is_active(self) -> bool:
        return self.emergency_shutdown_active