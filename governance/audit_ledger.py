"""
LUCY AUDIT LEDGER — Truth / Logging System
==========================================
Immutable append-only SQLite ledger.
Every agent action, decision, approval, block, and error is recorded here.
No record can be modified or deleted — only appended.
Thread-safe. Async-safe via connection-per-write pattern.
"""

import sqlite3
import json
import uuid
import hashlib
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass, field, asdict


# ── Event Types ─────────────────────────────────────────────────────────────
class EventType:
    # Lifecycle
    SYSTEM_START    = "system.start"
    SYSTEM_STOP     = "system.stop"
    AGENT_SPAWN     = "agent.spawn"
    AGENT_STOP      = "agent.stop"

    # Task flow
    TASK_RECEIVED   = "task.received"
    TASK_ROUTED     = "task.routed"
    TASK_QUEUED     = "task.queued"
    TASK_STARTED    = "task.started"
    TASK_COMPLETED  = "task.completed"
    TASK_FAILED     = "task.failed"
    TASK_CANCELLED  = "task.cancelled"

    # Governance
    GATE_APPROVED   = "gate.approved"
    GATE_BLOCKED    = "gate.blocked"
    SENTINEL_CHECK  = "sentinel.check"
    SENTINEL_HALT   = "sentinel.HALT"
    GUARDIAN_ALERT  = "guardian.alert"
    GUARDIAN_CLEAR  = "guardian.clear"

    # Execution
    TOOL_CALL       = "tool.call"
    TOOL_RESULT     = "tool.result"
    TOOL_ERROR      = "tool.error"

    # Memory
    MEMORY_WRITE    = "memory.write"
    MEMORY_READ     = "memory.read"

    # Validation
    VALIDATION_PASS = "validation.pass"
    VALIDATION_FAIL = "validation.fail"

    # Communication
    MSG_SENT        = "msg.sent"
    MSG_RECEIVED    = "msg.received"

    # Eagle Eye
    EAGLE_OBSERVE   = "eagle.observe"
    EAGLE_CORRECT   = "eagle.correct"
    EAGLE_DRIFT     = "eagle.drift"

    # Errors
    ERROR           = "error"
    ANOMALY         = "anomaly"


@dataclass
class LedgerEntry:
    event_type: str
    agent_id: str
    content: str
    task_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    severity: str = "info"          # info | warn | error | critical
    # Auto-set
    entry_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    checksum: str = ""              # SHA-256 of content + timestamp (set on insert)


class AuditLedger:
    """
    Immutable append-only audit ledger backed by SQLite.
    Thread-safe. No UPDATE or DELETE ever issued.
    Each record has a SHA-256 checksum for tamper detection.
    """

    _instances: dict = {}
    _lock = threading.Lock()

    def __init__(self, db_path: str = "data/sqlite/master_ledger.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self._init_schema()
        self.log(EventType.SYSTEM_START, "SYSTEM", "AuditLedger initialized",
                 metadata={"db": str(self.db_path)})

    @classmethod
    def get_instance(cls, db_path: str = "data/sqlite/master_ledger.db") -> "AuditLedger":
        """Singleton per db_path."""
        with cls._lock:
            if db_path not in cls._instances:
                cls._instances[db_path] = cls(db_path)
            return cls._instances[db_path]

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                isolation_level=None  # autocommit
            )
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._local.conn

    def _init_schema(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ledger (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id    TEXT    NOT NULL UNIQUE,
                event_type  TEXT    NOT NULL,
                agent_id    TEXT    NOT NULL,
                task_id     TEXT,
                severity    TEXT    NOT NULL DEFAULT 'info',
                content     TEXT    NOT NULL,
                metadata    TEXT    NOT NULL DEFAULT '{}',
                checksum    TEXT    NOT NULL,
                timestamp   TEXT    NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agent    ON ledger(agent_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_event    ON ledger(event_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_task     ON ledger(task_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_time     ON ledger(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_severity ON ledger(severity)")
        conn.commit()
        conn.close()

    # ── Core write ───────────────────────────────────────────────────────────
    def log(self,
            event_type: str,
            agent_id: str,
            content: str,
            task_id: str = None,
            metadata: dict = None,
            severity: str = "info") -> LedgerEntry:

        entry = LedgerEntry(
            event_type=event_type,
            agent_id=agent_id,
            content=str(content)[:4096],    # cap at 4KB
            task_id=task_id,
            metadata=metadata or {},
            severity=severity
        )
        # Compute tamper-proof checksum
        raw = f"{entry.entry_id}{entry.event_type}{entry.agent_id}{entry.content}{entry.timestamp}"
        entry.checksum = hashlib.sha256(raw.encode()).hexdigest()

        with self._write_lock:
            conn = self._conn()
            conn.execute(
                """INSERT INTO ledger
                   (entry_id, event_type, agent_id, task_id, severity,
                    content, metadata, checksum, timestamp)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (entry.entry_id, entry.event_type, entry.agent_id,
                 entry.task_id, entry.severity, entry.content,
                 json.dumps(entry.metadata), entry.checksum, entry.timestamp)
            )
        return entry

    # ── Convenience wrappers ─────────────────────────────────────────────────
    def task_received(self, agent_id: str, task_id: str, description: str):
        return self.log(EventType.TASK_RECEIVED, agent_id, description, task_id=task_id)

    def task_completed(self, agent_id: str, task_id: str, summary: str):
        return self.log(EventType.TASK_COMPLETED, agent_id, summary, task_id=task_id)

    def task_failed(self, agent_id: str, task_id: str, error: str):
        return self.log(EventType.TASK_FAILED, agent_id, error, task_id=task_id, severity="error")

    def gate_approved(self, agent_id: str, task_id: str, reason: str):
        return self.log(EventType.GATE_APPROVED, agent_id, reason, task_id=task_id)

    def gate_blocked(self, agent_id: str, task_id: str, reason: str):
        return self.log(EventType.GATE_BLOCKED, agent_id, reason, task_id=task_id, severity="warn")

    def sentinel_halt(self, reason: str):
        return self.log(EventType.SENTINEL_HALT, "SENTINEL", reason, severity="critical")

    def tool_call(self, agent_id: str, task_id: str, tool: str, inp: str):
        return self.log(EventType.TOOL_CALL, agent_id, f"{tool}({inp[:200]})", task_id=task_id)

    def tool_result(self, agent_id: str, task_id: str, tool: str, result: str):
        return self.log(EventType.TOOL_RESULT, agent_id, f"{tool} → {result[:500]}", task_id=task_id)

    def tool_error(self, agent_id: str, task_id: str, tool: str, error: str):
        return self.log(EventType.TOOL_ERROR, agent_id, f"{tool} ERROR: {error}", task_id=task_id, severity="error")

    def validation_pass(self, agent_id: str, task_id: str, check: str):
        return self.log(EventType.VALIDATION_PASS, agent_id, check, task_id=task_id)

    def validation_fail(self, agent_id: str, task_id: str, reason: str):
        return self.log(EventType.VALIDATION_FAIL, agent_id, reason, task_id=task_id, severity="warn")

    def error(self, agent_id: str, error: str, task_id: str = None):
        return self.log(EventType.ERROR, agent_id, error, task_id=task_id, severity="error")

    # ── Queries ───────────────────────────────────────────────────────────────
    def get_recent(self, limit: int = 50) -> list[dict]:
        conn = self._conn()
        cur = conn.execute(
            "SELECT * FROM ledger ORDER BY id DESC LIMIT ?", (limit,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_by_agent(self, agent_id: str, limit: int = 100) -> list[dict]:
        conn = self._conn()
        cur = conn.execute(
            "SELECT * FROM ledger WHERE agent_id=? ORDER BY id DESC LIMIT ?",
            (agent_id, limit))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_by_task(self, task_id: str) -> list[dict]:
        conn = self._conn()
        cur = conn.execute(
            "SELECT * FROM ledger WHERE task_id=? ORDER BY id ASC", (task_id,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_by_severity(self, severity: str, limit: int = 100) -> list[dict]:
        conn = self._conn()
        cur = conn.execute(
            "SELECT * FROM ledger WHERE severity=? ORDER BY id DESC LIMIT ?",
            (severity, limit))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_stats(self) -> dict:
        conn = self._conn()
        total = conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]
        by_severity = {}
        for row in conn.execute(
            "SELECT severity, COUNT(*) FROM ledger GROUP BY severity"):
            by_severity[row[0]] = row[1]
        by_event = {}
        for row in conn.execute(
            "SELECT event_type, COUNT(*) FROM ledger GROUP BY event_type ORDER BY 2 DESC LIMIT 20"):
            by_event[row[0]] = row[1]
        return {
            "total_entries": total,
            "by_severity": by_severity,
            "top_events": by_event
        }

    def verify_integrity(self, entry_id: str) -> bool:
        """Verify a record has not been tampered with."""
        conn = self._conn()
        row = conn.execute(
            "SELECT entry_id, event_type, agent_id, content, timestamp, checksum "
            "FROM ledger WHERE entry_id=?", (entry_id,)).fetchone()
        if not row:
            return False
        eid, etype, aid, content, ts, stored_checksum = row
        raw = f"{eid}{etype}{aid}{content}{ts}"
        computed = hashlib.sha256(raw.encode()).hexdigest()
        return computed == stored_checksum

    def export_jsonl(self, path: str):
        """Export full ledger as newline-delimited JSON."""
        conn = self._conn()
        rows = conn.execute("SELECT * FROM ledger ORDER BY id ASC").fetchall()
        cols = [d[0] for d in conn.execute("SELECT * FROM ledger LIMIT 0").description]
        with open(path, "w") as f:
            for row in rows:
                f.write(json.dumps(dict(zip(cols, row))) + "\n")
        return len(rows)