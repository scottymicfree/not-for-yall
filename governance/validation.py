"""
LUCY VALIDATION SYSTEM
======================
Multi-layer validation pipeline for every task/message entering the mesh.
Runs BEFORE SafeExecutionGate and BEFORE any agent processes a task.

Layers (in order):
  1. Schema validation    — correct fields, types, lengths
  2. Content validation   — no injection, no malformed data
  3. Permission validation— agent has rights to this action
  4. Resource validation  — not requesting impossible/excessive resources
  5. Semantic validation  — task makes logical sense
  6. Rate limiting        — agent not flooding the system

Each layer returns a ValidationResult. All must pass.
"""

import re
import time
import json
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any, Optional
from collections import defaultdict, deque


# ── Result types ─────────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    passed: bool
    layer: str
    reason: str = ""
    details: dict = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ValidationReport:
    task_id: str
    agent_id: str
    passed: bool
    results: list[ValidationResult] = field(default_factory=list)
    blocked_at: Optional[str] = None   # which layer failed
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "passed": self.passed,
            "blocked_at": self.blocked_at,
            "timestamp": self.timestamp,
            "results": [
                {
                    "layer": r.layer,
                    "passed": r.passed,
                    "reason": r.reason,
                    "details": r.details
                } for r in self.results
            ]
        }


# ── Task schema definition ────────────────────────────────────────────────────

TASK_SCHEMA = {
    "required_fields": ["description"],
    "optional_fields": ["task_id", "priority", "actions", "context",
                        "source", "target_agent", "timeout", "metadata"],
    "field_types": {
        "description": str,
        "task_id":     str,
        "priority":    int,
        "actions":     list,
        "context":     dict,
        "source":      str,
        "target_agent":str,
        "timeout":     (int, float),
        "metadata":    dict
    },
    "field_limits": {
        "description": 4096,
        "task_id":     64,
        "source":      64,
        "target_agent":64
    },
    "priority_range": (1, 10),
    "timeout_range":  (1, 3600),
}

# ── Injection patterns (SQL, shell, prompt, path traversal) ──────────────────

INJECTION_PATTERNS = [
    # SQL injection
    (r"(--|;|\/\*|\*\/|xp_|exec\s+\w|drop\s+table|delete\s+from|insert\s+into"
     r"|union\s+select|1\s*=\s*1|' or|\" or)", "SQL injection"),
    # Shell injection
    (r"(\$\(|`[^`]+`|\|\s*\w|\beval\b|\bexec\b.*\(|&&|\|\|)", "Shell injection"),
    # Path traversal
    (r"(\.\./|\.\.\\|%2e%2e)", "Path traversal"),
    # Null bytes
    (r"\x00", "Null byte injection"),
    # Prompt injection markers
    (r"(ignore previous instructions|disregard.*system|you are now|"
     r"act as.*without restrictions|jailbreak)", "Prompt injection"),
]

# ── Forbidden action tags (mirrors Sentinel) ─────────────────────────────────

FORBIDDEN_ACTION_TAGS = {
    "GEOENGINEERING_UNAUTH",
    "ENERGY_GRID_OVERRIDE",
    "TWIN_EARTH_WRITE",
    "GOVERNANCE_MODIFY",
    "SENTINEL_DISABLE",
    "AUDIT_TAMPER",
    "AGENT_SPAWN_UNAUTH",
    "CROSS_CLUSTER_WRITE",
}

FORBIDDEN_COMMANDS = {
    "rm -rf", "mkfs", "dd if=", "format c:", ":(){:|:&};:",
    "shutdown", "reboot", "halt", "poweroff",
    "DROP TABLE", "DELETE FROM", "TRUNCATE",
    "chmod 777 /", "chown -R",
}

# ── Rate limiter ──────────────────────────────────────────────────────────────

class RateLimiter:
    """Token bucket per agent_id."""
    def __init__(self, max_per_minute: int = 60, burst: int = 10):
        self.max_per_minute = max_per_minute
        self.burst = burst
        self._buckets: dict[str, deque] = defaultdict(deque)

    def check(self, agent_id: str) -> tuple[bool, str]:
        now = time.time()
        window = 60.0
        bucket = self._buckets[agent_id]
        # Remove timestamps older than window
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        if len(bucket) >= self.max_per_minute:
            return False, f"Rate limit exceeded: {len(bucket)} requests in last 60s (max {self.max_per_minute})"
        # Burst check (last 5 seconds)
        recent = sum(1 for t in bucket if now - t < 5.0)
        if recent >= self.burst:
            return False, f"Burst limit exceeded: {recent} requests in last 5s (max {self.burst})"
        bucket.append(now)
        return True, "ok"


# ── Permission matrix ─────────────────────────────────────────────────────────

AGENT_PERMISSIONS = {
    # agent_type → allowed tool sets + actions
    "prime":   {"tools": {"all"}, "actions": {"route", "plan", "decompose", "broadcast"}},
    "cluster": {"tools": {"read_file", "list_dir", "search", "bash_readonly"},
                "actions": {"route", "consensus", "delegate", "report"}},
    "worker":  {"tools": {"read_file", "write_file", "bash", "search",
                           "list_dir", "code_run", "retrieval"},
                "actions": {"execute", "retrieve", "report"}},
    "system":  {"tools": {"all"}, "actions": {"all"}},
}

def get_agent_type(agent_id: str) -> str:
    aid = agent_id.upper()
    if "PRIME" in aid or aid == "P001" or aid.startswith("LP"):
        return "prime"
    if aid.startswith("C") and len(aid) <= 3:
        return "cluster"
    if aid.startswith("W"):
        return "worker"
    return "worker"   # default to most restricted


# ── The Validation Pipeline ───────────────────────────────────────────────────

class ValidationPipeline:
    """
    Runs all validation layers in sequence.
    Fail-fast: stops at first failed layer.
    """

    def __init__(self, rate_limiter: RateLimiter = None, ledger=None):
        self.rate_limiter = rate_limiter or RateLimiter()
        self.ledger = ledger   # optional AuditLedger reference

    def validate(self, task: dict, agent_id: str) -> ValidationReport:
        task_id = task.get("task_id") or str(uuid.uuid4())
        task["task_id"] = task_id

        report = ValidationReport(task_id=task_id, agent_id=agent_id, passed=False)

        layers = [
            ("schema",     self._validate_schema),
            ("content",    self._validate_content),
            ("permission", self._validate_permission),
            ("resource",   self._validate_resource),
            ("semantic",   self._validate_semantic),
            ("rate_limit", self._validate_rate_limit),
        ]

        for layer_name, layer_fn in layers:
            result = layer_fn(task, agent_id)
            result.layer = layer_name
            report.results.append(result)
            if not result.passed:
                report.passed = False
                report.blocked_at = layer_name
                # Log to ledger if available
                if self.ledger:
                    self.ledger.validation_fail(
                        agent_id, task_id,
                        f"[{layer_name}] {result.reason}")
                return report

        report.passed = True
        if self.ledger:
            self.ledger.validation_pass(agent_id, task_id, "All 6 layers passed")
        return report

    # ── Layer 1: Schema ────────────────────────────────────────────────────────
    def _validate_schema(self, task: dict, agent_id: str) -> ValidationResult:
        # Must be a dict
        if not isinstance(task, dict):
            return ValidationResult(False, "schema", "Task must be a dict")

        # Required fields
        for field in TASK_SCHEMA["required_fields"]:
            if field not in task:
                return ValidationResult(False, "schema",
                    f"Missing required field: '{field}'")

        # No unknown fields
        all_known = set(TASK_SCHEMA["required_fields"]) | set(TASK_SCHEMA["optional_fields"])
        unknown = set(task.keys()) - all_known
        if unknown:
            return ValidationResult(False, "schema",
                f"Unknown fields: {unknown}. Allowed: {all_known}")

        # Type checks
        for field, expected_type in TASK_SCHEMA["field_types"].items():
            if field in task and not isinstance(task[field], expected_type):
                return ValidationResult(False, "schema",
                    f"Field '{field}' must be {expected_type}, got {type(task[field])}")

        # Length limits
        for field, max_len in TASK_SCHEMA["field_limits"].items():
            if field in task and len(str(task[field])) > max_len:
                return ValidationResult(False, "schema",
                    f"Field '{field}' exceeds max length {max_len}")

        # Priority range
        if "priority" in task:
            lo, hi = TASK_SCHEMA["priority_range"]
            if not (lo <= task["priority"] <= hi):
                return ValidationResult(False, "schema",
                    f"Priority must be {lo}–{hi}, got {task['priority']}")

        # Timeout range
        if "timeout" in task:
            lo, hi = TASK_SCHEMA["timeout_range"]
            if not (lo <= task["timeout"] <= hi):
                return ValidationResult(False, "schema",
                    f"Timeout must be {lo}–{hi}s, got {task['timeout']}")

        return ValidationResult(True, "schema", "Schema valid")

    # ── Layer 2: Content ───────────────────────────────────────────────────────
    def _validate_content(self, task: dict, agent_id: str) -> ValidationResult:
        desc = task.get("description", "")
        actions = task.get("actions", [])
        all_text = json.dumps(task).lower()

        # Injection detection
        for pattern, label in INJECTION_PATTERNS:
            if re.search(pattern, all_text, re.IGNORECASE):
                return ValidationResult(False, "content",
                    f"Injection pattern detected: {label}",
                    details={"pattern": label})

        # Forbidden commands
        for cmd in FORBIDDEN_COMMANDS:
            if cmd.lower() in all_text:
                return ValidationResult(False, "content",
                    f"Forbidden command detected: '{cmd}'",
                    details={"command": cmd})

        # Forbidden action tags
        for tag in actions:
            if str(tag).upper() in FORBIDDEN_ACTION_TAGS:
                return ValidationResult(False, "content",
                    f"Forbidden action tag: '{tag}'",
                    details={"tag": tag})

        # Empty description
        if not desc.strip():
            return ValidationResult(False, "content",
                "Description cannot be empty or whitespace only")

        # Non-printable characters in description
        if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', desc):
            return ValidationResult(False, "content",
                "Description contains non-printable characters")

        return ValidationResult(True, "content", "Content clean")

    # ── Layer 3: Permission ────────────────────────────────────────────────────
    def _validate_permission(self, task: dict, agent_id: str) -> ValidationResult:
        agent_type = get_agent_type(agent_id)
        perms = AGENT_PERMISSIONS.get(agent_type, AGENT_PERMISSIONS["worker"])

        actions = task.get("actions", [])
        allowed_actions = perms["actions"]

        if "all" in allowed_actions:
            return ValidationResult(True, "permission", f"{agent_type} has full permissions")

        for action in actions:
            if str(action).lower() not in allowed_actions:
                return ValidationResult(False, "permission",
                    f"Agent type '{agent_type}' not permitted to perform '{action}'. "
                    f"Allowed: {allowed_actions}",
                    details={"agent_type": agent_type, "denied_action": action})

        # Workers cannot claim to be Prime/Cluster
        source = task.get("source", "")
        if agent_type == "worker" and source.upper() in ("PRIME", "SYSTEM"):
            return ValidationResult(False, "permission",
                f"Worker '{agent_id}' cannot impersonate '{source}'")

        return ValidationResult(True, "permission",
            f"Permission granted for {agent_type}")

    # ── Layer 4: Resource ──────────────────────────────────────────────────────
    def _validate_resource(self, task: dict, agent_id: str) -> ValidationResult:
        desc = task.get("description", "").lower()
        context = task.get("context", {})

        # Reject obviously impossible/dangerous resource requests
        dangerous_patterns = [
            (r"\ball\s+memory\b",        "Requesting all system memory"),
            (r"\bfork\s+bomb\b",          "Fork bomb reference"),
            (r"spawn\s+\d{4,}\s+agents", "Spawning excessive agents"),
            (r"loop\s+forever",           "Infinite loop instruction"),
            (r"fill\s+disk",              "Disk fill attack"),
        ]
        for pattern, label in dangerous_patterns:
            if re.search(pattern, desc, re.IGNORECASE):
                return ValidationResult(False, "resource",
                    f"Dangerous resource request: {label}")

        # File size limit from context
        if context.get("file_size_bytes", 0) > 500 * 1024 * 1024:   # 500 MB
            return ValidationResult(False, "resource",
                "Requested file operation exceeds 500 MB limit")

        return ValidationResult(True, "resource", "Resource request acceptable")

    # ── Layer 5: Semantic ──────────────────────────────────────────────────────
    def _validate_semantic(self, task: dict, agent_id: str) -> ValidationResult:
        desc = task.get("description", "").strip()

        # Too short to be meaningful
        if len(desc.split()) < 2:
            return ValidationResult(False, "semantic",
                f"Description too short to be actionable: '{desc}'")

        # Contradictory instructions
        contradiction_pairs = [
            ("delete", "preserve"),
            ("shutdown", "keep running"),
            ("deny all", "allow all"),
        ]
        desc_lower = desc.lower()
        for a, b in contradiction_pairs:
            if a in desc_lower and b in desc_lower:
                return ValidationResult(False, "semantic",
                    f"Contradictory instructions detected: '{a}' and '{b}'")

        # Priority/action mismatch: priority 1 (low) should not have critical actions
        priority = task.get("priority", 5)
        actions = [str(a).lower() for a in task.get("actions", [])]
        if priority == 1 and any(a in ("sentinel_disable", "governance_modify") for a in actions):
            return ValidationResult(False, "semantic",
                "Critical governance actions cannot have lowest priority")

        return ValidationResult(True, "semantic", "Semantics valid")

    # ── Layer 6: Rate limit ────────────────────────────────────────────────────
    def _validate_rate_limit(self, task: dict, agent_id: str) -> ValidationResult:
        ok, msg = self.rate_limiter.check(agent_id)
        if not ok:
            return ValidationResult(False, "rate_limit", msg)
        return ValidationResult(True, "rate_limit", "Within rate limits")


# ── Message validator (for inter-agent comms) ─────────────────────────────────

class MessageValidator:
    """Validates inter-agent messages (lighter than full task validation)."""

    MAX_MSG_SIZE = 65536  # 64 KB

    def validate_message(self, msg: dict, sender_id: str) -> ValidationResult:
        # Must have type + payload
        if not isinstance(msg, dict):
            return ValidationResult(False, "message_schema", "Message must be a dict")
        for field in ("type", "sender", "payload"):
            if field not in msg:
                return ValidationResult(False, "message_schema",
                    f"Missing field '{field}'")

        # Size check
        size = len(json.dumps(msg))
        if size > self.MAX_MSG_SIZE:
            return ValidationResult(False, "message_size",
                f"Message size {size} exceeds limit {self.MAX_MSG_SIZE}")

        # Sender must match claimed sender
        if msg["sender"] != sender_id:
            return ValidationResult(False, "message_auth",
                f"Sender mismatch: claimed '{msg['sender']}', actual '{sender_id}'")

        return ValidationResult(True, "message", "Message valid")


# ── Standalone helper ─────────────────────────────────────────────────────────

_pipeline: Optional[ValidationPipeline] = None

def get_pipeline(ledger=None) -> ValidationPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = ValidationPipeline(ledger=ledger)
    return _pipeline

def validate_task(task: dict, agent_id: str, ledger=None) -> ValidationReport:
    """Convenience function — validate a task dict."""
    return get_pipeline(ledger).validate(task, agent_id)