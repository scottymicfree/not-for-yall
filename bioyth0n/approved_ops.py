"""
Bioyth0n — Approved Operations Registry
Defines every operation Bioyth0n is permitted to execute.
Bioyth0n NEVER reasons about these — it only checks the registry and executes.
"""

from __future__ import annotations
import time
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("bioyth0n.ops")


@dataclass
class ApprovedOp:
    """A single pre-approved operation template."""
    op_id:        str
    name:         str
    category:     str        # file | fivem | scaffold | system | earth | memory
    description:  str
    required_fields: list[str]   # payload fields that MUST be present
    optional_fields: list[str]   # payload fields that may be present
    risk_level:   str        # low | medium | high
    requires_ee:  bool       # requires Eagle Eye trusted=True
    requires_emma: bool      # requires Emma approved=True
    requires_human: bool     # requires human approval
    enabled:      bool = True

    def validate_payload(self, payload: dict) -> tuple[bool, str]:
        """Check all required fields are present."""
        for f in self.required_fields:
            if f not in payload:
                return False, f"missing_required_field:{f}"
        return True, ""

    def to_dict(self) -> dict:
        return {
            "op_id":          self.op_id,
            "name":           self.name,
            "category":       self.category,
            "description":    self.description,
            "required_fields": self.required_fields,
            "risk_level":     self.risk_level,
            "requires_ee":    self.requires_ee,
            "requires_emma":  self.requires_emma,
            "requires_human": self.requires_human,
            "enabled":        self.enabled,
        }


# ─────────────────────────────────────────────
# Master Approved Operations List
# ─────────────────────────────────────────────

APPROVED_OPS: list[ApprovedOp] = [

    # ── FILE OPERATIONS ──────────────────────────────────────────────
    ApprovedOp(
        op_id="OP-FILE-01", name="write_text_file", category="file",
        description="Write text content to an approved file path",
        required_fields=["file_path", "content"],
        optional_fields=["encoding", "append_mode"],
        risk_level="medium", requires_ee=True, requires_emma=True, requires_human=False,
    ),
    ApprovedOp(
        op_id="OP-FILE-02", name="read_file", category="file",
        description="Read text content from a file path",
        required_fields=["file_path"],
        optional_fields=["encoding", "max_bytes"],
        risk_level="low", requires_ee=False, requires_emma=False, requires_human=False,
    ),
    ApprovedOp(
        op_id="OP-FILE-03", name="append_to_file", category="file",
        description="Append content to an existing file",
        required_fields=["file_path", "content"],
        optional_fields=["encoding"],
        risk_level="medium", requires_ee=True, requires_emma=True, requires_human=False,
    ),
    ApprovedOp(
        op_id="OP-FILE-04", name="create_directory", category="file",
        description="Create a directory at an approved path",
        required_fields=["dir_path"],
        optional_fields=["parents"],
        risk_level="low", requires_ee=True, requires_emma=False, requires_human=False,
    ),
    ApprovedOp(
        op_id="OP-FILE-05", name="list_directory", category="file",
        description="List contents of a directory",
        required_fields=["dir_path"],
        optional_fields=["recursive", "filter_ext"],
        risk_level="low", requires_ee=False, requires_emma=False, requires_human=False,
    ),

    # ── SCAFFOLD OPERATIONS ───────────────────────────────────────────
    ApprovedOp(
        op_id="OP-SCAF-01", name="ue5_create_map_scaffold", category="scaffold",
        description="Create UE5 map scaffold under Content/LucyGenerated/",
        required_fields=["map_name"],
        optional_fields=["workspace_path", "include_blueprints"],
        risk_level="medium", requires_ee=True, requires_emma=True, requires_human=False,
    ),
    ApprovedOp(
        op_id="OP-SCAF-02", name="unity_create_scene_scaffold", category="scaffold",
        description="Create Unity scene scaffold under Assets/LucyGenerated/",
        required_fields=["scene_name"],
        optional_fields=["workspace_path", "include_scripts"],
        risk_level="medium", requires_ee=True, requires_emma=True, requires_human=False,
    ),
    ApprovedOp(
        op_id="OP-SCAF-03", name="fivem_write_resource_script", category="scaffold",
        description="Write a Lua script to an approved FiveM resource path",
        required_fields=["resource_name", "script_name", "content"],
        optional_fields=["resource_path"],
        risk_level="high", requires_ee=True, requires_emma=True, requires_human=True,
    ),
    ApprovedOp(
        op_id="OP-SCAF-04", name="write_python_module", category="scaffold",
        description="Write a Python module to the lucy-os project",
        required_fields=["module_path", "content"],
        optional_fields=["overwrite"],
        risk_level="high", requires_ee=True, requires_emma=True, requires_human=True,
    ),

    # ── FIVEM OPERATIONS ──────────────────────────────────────────────
    ApprovedOp(
        op_id="OP-FM-01", name="spawn_npc_support", category="fivem",
        description="Spawn an NPC support entity at specified coordinates",
        required_fields=["npc_model", "coords"],
        optional_fields=["heading", "scenario", "faction"],
        risk_level="medium", requires_ee=True, requires_emma=True, requires_human=False,
    ),
    ApprovedOp(
        op_id="OP-FM-02", name="generate_mission", category="fivem",
        description="Generate and inject a mission script into the server",
        required_fields=["mission_type", "mission_data"],
        optional_fields=["target_zone", "reward_amount"],
        risk_level="medium", requires_ee=True, requires_emma=True, requires_human=False,
    ),
    ApprovedOp(
        op_id="OP-FM-03", name="repair_resource", category="fivem",
        description="Restart or repair a broken FiveM resource",
        required_fields=["resource_name"],
        optional_fields=["force_restart"],
        risk_level="medium", requires_ee=True, requires_emma=True, requires_human=False,
    ),
    ApprovedOp(
        op_id="OP-FM-04", name="create_dispatch_event", category="fivem",
        description="Push a dispatch event to police/EMS/fire systems",
        required_fields=["event_type", "location", "description"],
        optional_fields=["priority", "units_required"],
        risk_level="low", requires_ee=True, requires_emma=False, requires_human=False,
    ),
    ApprovedOp(
        op_id="OP-FM-05", name="balance_economy", category="fivem",
        description="Apply economy balance adjustment to the server",
        required_fields=["adjustment_type", "amount"],
        optional_fields=["target_job", "reason"],
        risk_level="medium", requires_ee=True, requires_emma=True, requires_human=False,
    ),
    ApprovedOp(
        op_id="OP-FM-06", name="kick_empty_loop_player", category="fivem",
        description="Flag and kick a player detected in an empty roleplay loop",
        required_fields=["player_id"],
        optional_fields=["reason", "notify_admin"],
        risk_level="high", requires_ee=True, requires_emma=True, requires_human=True,
    ),

    # ── EARTH / SIMULATION OPERATIONS ────────────────────────────────
    ApprovedOp(
        op_id="OP-EARTH-01", name="fetch_earth_snapshot", category="earth",
        description="Fetch current Earth baseline data (SimA)",
        required_fields=[],
        optional_fields=["include_sima", "include_simb"],
        risk_level="low", requires_ee=False, requires_emma=False, requires_human=False,
    ),
    ApprovedOp(
        op_id="OP-EARTH-02", name="run_twin_earth_sim", category="earth",
        description="Run TwinEarth simulation with specified delta parameters",
        required_fields=["sim_id"],
        optional_fields=["delta_overrides", "steps"],
        risk_level="low", requires_ee=False, requires_emma=False, requires_human=False,
    ),
    ApprovedOp(
        op_id="OP-EARTH-03", name="trigger_sentinel_scan", category="earth",
        description="Trigger a Sentinel signal scan for anomaly detection",
        required_fields=[],
        optional_fields=["include_governance"],
        risk_level="low", requires_ee=False, requires_emma=False, requires_human=False,
    ),

    # ── MEMORY OPERATIONS ─────────────────────────────────────────────
    ApprovedOp(
        op_id="OP-MEM-01", name="write_episodic_memory", category="memory",
        description="Write an important episode to long-term episodic memory",
        required_fields=["content", "importance"],
        optional_fields=["tags", "session_id"],
        risk_level="low", requires_ee=False, requires_emma=False, requires_human=False,
    ),
    ApprovedOp(
        op_id="OP-MEM-02", name="compress_old_memories", category="memory",
        description="Run memory compression (M13) on aged STM entries",
        required_fields=["session_id"],
        optional_fields=["age_threshold_s"],
        risk_level="low", requires_ee=False, requires_emma=False, requires_human=False,
    ),
    ApprovedOp(
        op_id="OP-MEM-03", name="forget_stale_entries", category="memory",
        description="Apply forgetting engine (M18) to prune low-importance memories",
        required_fields=[],
        optional_fields=["min_importance", "max_age_s"],
        risk_level="low", requires_ee=False, requires_emma=False, requires_human=False,
    ),

    # ── SYSTEM OPERATIONS ─────────────────────────────────────────────
    ApprovedOp(
        op_id="OP-SYS-01", name="run_health_check", category="system",
        description="Run mesh health monitor check across all 137 nodes",
        required_fields=[],
        optional_fields=[],
        risk_level="low", requires_ee=False, requires_emma=False, requires_human=False,
    ),
    ApprovedOp(
        op_id="OP-SYS-02", name="decay_attention_weights", category="system",
        description="Run one decay tick on the attention weight engine",
        required_fields=[],
        optional_fields=[],
        risk_level="low", requires_ee=False, requires_emma=False, requires_human=False,
    ),
    ApprovedOp(
        op_id="OP-SYS-03", name="propose_upgrade", category="system",
        description="Submit an upgrade proposal to the upgrade store",
        required_fields=["title", "description", "target_module"],
        optional_fields=["priority", "estimated_impact"],
        risk_level="low", requires_ee=False, requires_emma=False, requires_human=False,
    ),
    ApprovedOp(
        op_id="OP-SYS-04", name="emit_mesh_event", category="system",
        description="Emit a named event onto the mesh event bus",
        required_fields=["event_name", "payload"],
        optional_fields=["source_node", "target_node"],
        risk_level="low", requires_ee=False, requires_emma=False, requires_human=False,
    ),
]


class ApprovedOpsRegistry:
    """Registry of all Bioyth0n-approved operations. Read-only at runtime."""

    def __init__(self):
        self._ops: dict[str, ApprovedOp] = {op.op_id: op for op in APPROVED_OPS}
        self._by_name: dict[str, ApprovedOp] = {op.name: op for op in APPROVED_OPS}

    def get_by_id(self, op_id: str) -> ApprovedOp | None:
        return self._ops.get(op_id)

    def get_by_name(self, name: str) -> ApprovedOp | None:
        return self._by_name.get(name)

    def get_by_category(self, category: str) -> list[ApprovedOp]:
        return [op for op in self._ops.values() if op.category == category and op.enabled]

    def all_enabled(self) -> list[ApprovedOp]:
        return [op for op in self._ops.values() if op.enabled]

    def all_dicts(self) -> list[dict]:
        return [op.to_dict() for op in self._ops.values()]

    def validate(self, op_name: str, payload: dict) -> tuple[bool, str, ApprovedOp | None]:
        """
        Validates that op_name exists and payload is complete.
        Returns (valid, reason, op_or_None).
        """
        op = self.get_by_name(op_name)
        if not op:
            return False, f"op_not_found:{op_name}", None
        if not op.enabled:
            return False, f"op_disabled:{op_name}", None
        ok, msg = op.validate_payload(payload)
        if not ok:
            return False, msg, op
        return True, "ok", op


# Singleton
approved_ops = ApprovedOpsRegistry()