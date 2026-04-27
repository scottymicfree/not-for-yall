"""
Bioyth0n — Blind Exact Executor
The executioner. Does NOT reason. Does NOT chat. Does NOT decide.
Only executes pre-approved operations that passed Eagle Eye + Emma gates.
Every execution is logged to DeltaVault. Zero free reasoning.
"""

from __future__ import annotations
import time
import uuid
import threading
import logging
from dataclasses import dataclass, field
from typing import Any

from bioyth0n.approved_ops  import approved_ops, ApprovedOp
from bioyth0n.file_writer   import governed_file_writer

logger = logging.getLogger("bioyth0n")

# ─────────────────────────────────────────────
# Execution record
# ─────────────────────────────────────────────

@dataclass
class ExecutionRecord:
    """Immutable record of one Bioyth0n execution."""
    exec_id:      str   = field(default_factory=lambda: str(uuid.uuid4())[:12])
    op_id:        str   = ""
    op_name:      str   = ""
    session_id:   str   = ""
    payload:      dict  = field(default_factory=dict)
    result:       dict  = field(default_factory=dict)
    success:      bool  = False
    error:        str   = ""
    gate_passed:  bool  = False
    vault_logged: bool  = False
    duration_ms:  float = 0.0
    timestamp:    float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "exec_id":     self.exec_id,
            "op_id":       self.op_id,
            "op_name":     self.op_name,
            "session_id":  self.session_id,
            "payload":     {k: v for k, v in self.payload.items() if k != "content"},
            "success":     self.success,
            "error":       self.error,
            "gate_passed": self.gate_passed,
            "vault_logged": self.vault_logged,
            "duration_ms": round(self.duration_ms, 2),
            "timestamp":   self.timestamp,
        }


# ─────────────────────────────────────────────
# Gate Check — all conditions that must be met
# ─────────────────────────────────────────────

class BioyTh0nGate:
    """
    Checks execution gate conditions before Bioyth0n runs anything.
    Gate passes only when ALL required conditions are satisfied.
    This is the ONLY decision logic in Bioyth0n — and it's binary.
    """

    def check(
        self,
        op:              ApprovedOp,
        eagle_eye_state: dict,
        emma_decision:   dict,
        human_approved:  bool = False,
    ) -> tuple[bool, list[str]]:
        """Returns (gate_passed, list_of_failures)."""
        failures: list[str] = []

        # Eagle Eye gate
        if op.requires_ee:
            if not eagle_eye_state.get("trusted", False):
                failures.append("eagle_eye_not_trusted")
            if not eagle_eye_state.get("integrity", {}).get("ok", False):
                failures.append("vault_integrity_failed")
            ee_conf = eagle_eye_state.get("confidence", 0.0)
            if ee_conf < 0.65:
                failures.append(f"ee_confidence_too_low:{ee_conf:.3f}")

        # Emma approval gate
        if op.requires_emma:
            if not emma_decision.get("approved", False):
                failures.append("emma_not_approved")

        # Human approval gate
        if op.requires_human:
            if not human_approved:
                failures.append("human_approval_required")

        # Op must be enabled
        if not op.enabled:
            failures.append("op_disabled")

        passed = len(failures) == 0
        return passed, failures


# ─────────────────────────────────────────────
# Operation Executors — one per category
# (These contain ZERO reasoning — only mechanical execution)
# ─────────────────────────────────────────────

class _FileOps:
    """Executes file category operations."""

    def run(self, op_name: str, payload: dict) -> dict:
        if op_name == "write_text_file":
            return governed_file_writer.write(
                file_path   = payload["file_path"],
                content     = payload["content"],
                append_mode = payload.get("append_mode", False),
                encoding    = payload.get("encoding", "utf-8"),
            )
        if op_name == "read_file":
            return governed_file_writer.read(
                file_path = payload["file_path"],
                max_bytes = payload.get("max_bytes", 1024 * 1024),
                encoding  = payload.get("encoding", "utf-8"),
            )
        if op_name == "append_to_file":
            return governed_file_writer.write(
                file_path   = payload["file_path"],
                content     = payload["content"],
                append_mode = True,
                encoding    = payload.get("encoding", "utf-8"),
            )
        if op_name == "create_directory":
            return governed_file_writer.create_directory(
                dir_path = payload["dir_path"],
                parents  = payload.get("parents", True),
            )
        if op_name == "list_directory":
            return governed_file_writer.list_directory(
                dir_path   = payload["dir_path"],
                recursive  = payload.get("recursive", False),
                filter_ext = payload.get("filter_ext", ""),
            )
        return {"success": False, "error": f"unknown_file_op:{op_name}"}


class _ScaffoldOps:
    """Executes scaffold category operations."""

    def run(self, op_name: str, payload: dict) -> dict:
        if op_name == "ue5_create_map_scaffold":
            try:
                from unr5.ue5_bridge import ue5_bridge
                result = ue5_bridge.create_map_scaffold(
                    payload.get("workspace_path", ""),
                    payload["map_name"],
                )
                return {"success": True, "result": result}
            except Exception as e:
                return {"success": False, "error": str(e)}

        if op_name == "unity_create_scene_scaffold":
            try:
                from unr5.ue5_bridge import unity_bridge
                result = unity_bridge.create_scene_scaffold(
                    payload.get("workspace_path", ""),
                    payload["scene_name"],
                )
                return {"success": True, "result": result}
            except Exception as e:
                return {"success": False, "error": str(e)}

        if op_name in ("fivem_write_resource_script", "write_python_module"):
            path    = payload.get("module_path") or f"fivem_resources/{payload.get('resource_name','res')}/{payload.get('script_name','script.lua')}"
            content = payload["content"]
            return governed_file_writer.write(path, content)

        return {"success": False, "error": f"unknown_scaffold_op:{op_name}"}


class _FiveMOps:
    """Executes FiveM category operations."""

    def run(self, op_name: str, payload: dict) -> dict:
        try:
            from bridges.fivem_bridge import fivem_bridge
        except Exception:
            fivem_bridge = None

        if op_name == "spawn_npc_support":
            if not fivem_bridge:
                return {"success": False, "error": "fivem_bridge_unavailable"}
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                result = loop.run_until_complete(
                    fivem_bridge.spawn_npc(
                        npc_model = payload["npc_model"],
                        coords    = payload["coords"],
                        heading   = payload.get("heading", 0.0),
                        scenario  = payload.get("scenario", ""),
                    )
                )
                return result
            except Exception as e:
                return {"success": False, "error": str(e)}

        if op_name == "generate_mission":
            if not fivem_bridge:
                return {"success": False, "error": "fivem_bridge_unavailable"}
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                result = loop.run_until_complete(
                    fivem_bridge.create_mission(
                        mission_type = payload["mission_type"],
                        mission_data = payload["mission_data"],
                    )
                )
                return result
            except Exception as e:
                return {"success": False, "error": str(e)}

        if op_name == "repair_resource":
            if not fivem_bridge:
                return {"success": False, "error": "fivem_bridge_unavailable"}
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                result = loop.run_until_complete(
                    fivem_bridge.repair_resource(payload["resource_name"])
                )
                return result
            except Exception as e:
                return {"success": False, "error": str(e)}

        if op_name == "create_dispatch_event":
            if not fivem_bridge:
                return {"success": False, "error": "fivem_bridge_unavailable"}
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                result = loop.run_until_complete(
                    fivem_bridge.dispatch_event(
                        event_type  = payload["event_type"],
                        location    = payload["location"],
                        description = payload["description"],
                        priority    = payload.get("priority", "medium"),
                    )
                )
                return result
            except Exception as e:
                return {"success": False, "error": str(e)}

        if op_name == "balance_economy":
            if not fivem_bridge:
                return {"success": False, "error": "fivem_bridge_unavailable"}
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                result = loop.run_until_complete(
                    fivem_bridge.balance_economy(
                        adjustment_type = payload["adjustment_type"],
                        amount          = payload["amount"],
                        target_job      = payload.get("target_job", ""),
                    )
                )
                return result
            except Exception as e:
                return {"success": False, "error": str(e)}

        if op_name == "kick_empty_loop_player":
            if not fivem_bridge:
                return {"success": False, "error": "fivem_bridge_unavailable"}
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                result = loop.run_until_complete(
                    fivem_bridge.kick_player(
                        player_id = payload["player_id"],
                        reason    = payload.get("reason", "Empty roleplay loop detected"),
                    )
                )
                return result
            except Exception as e:
                return {"success": False, "error": str(e)}

        return {"success": False, "error": f"unknown_fivem_op:{op_name}"}


class _EarthOps:
    """Executes Earth/simulation category operations."""

    def run(self, op_name: str, payload: dict) -> dict:
        if op_name == "fetch_earth_snapshot":
            try:
                from unr5.earth import fetch_earth_baseline_sync, build_twin_earth_state
                baseline = fetch_earth_baseline_sync()
                result   = {"sima": baseline}
                if payload.get("include_simb", False):
                    twin = build_twin_earth_state(baseline)
                    result["simb"] = twin.get("simb", {})
                return {"success": True, "data": result}
            except Exception as e:
                return {"success": False, "error": str(e)}

        if op_name == "run_twin_earth_sim":
            try:
                from unr5.earth import fetch_earth_baseline_sync, build_twin_earth_state
                baseline = fetch_earth_baseline_sync()
                twin     = build_twin_earth_state(baseline)
                return {"success": True, "data": twin, "sim_id": payload["sim_id"]}
            except Exception as e:
                return {"success": False, "error": str(e)}

        if op_name == "trigger_sentinel_scan":
            try:
                from unr5.sentinel import sentinel_engine
                from unr5.earth import fetch_earth_baseline_sync, build_twin_earth_state
                baseline = fetch_earth_baseline_sync()
                twin     = build_twin_earth_state(baseline)
                signals  = sentinel_engine.detect_signals(baseline, twin)
                return {"success": True, "signals": signals}
            except Exception as e:
                return {"success": False, "error": str(e)}

        return {"success": False, "error": f"unknown_earth_op:{op_name}"}


class _MemoryOps:
    """Executes memory category operations."""

    def run(self, op_name: str, payload: dict) -> dict:
        try:
            from memory.memory_core import memory_system
        except Exception as e:
            return {"success": False, "error": f"memory_unavailable:{e}"}

        if op_name == "write_episodic_memory":
            memory_system.episodic.store(
                content    = payload["content"],
                importance = float(payload["importance"]),
                tags       = payload.get("tags", []),
            )
            return {"success": True, "op": "write_episodic_memory"}

        if op_name == "compress_old_memories":
            memory_system.compress_old_memories(
                session_id = payload["session_id"],
                age_threshold_s = payload.get("age_threshold_s", 3600),
            )
            return {"success": True, "op": "compress_old_memories"}

        if op_name == "forget_stale_entries":
            memory_system.episodic.forget_old(
                min_importance = payload.get("min_importance", 0.3),
                max_age_s      = payload.get("max_age_s", 86400),
            )
            return {"success": True, "op": "forget_stale_entries"}

        return {"success": False, "error": f"unknown_memory_op:{op_name}"}


class _SystemOps:
    """Executes system category operations."""

    def run(self, op_name: str, payload: dict) -> dict:
        if op_name == "run_health_check":
            try:
                from mesh.health_monitor import health_monitor
                report = health_monitor.run_check_now()
                return {"success": True, "report": report}
            except Exception as e:
                return {"success": False, "error": str(e)}

        if op_name == "decay_attention_weights":
            try:
                from mesh.attention import attention_engine
                attention_engine.decay_tick()
                return {"success": True, "op": "decay_attention_weights"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        if op_name == "propose_upgrade":
            try:
                from unr5.upgrades import upgrade_store
                proposal = upgrade_store.create(
                    title           = payload["title"],
                    description     = payload["description"],
                    target_module   = payload["target_module"],
                    priority        = payload.get("priority", "medium"),
                    estimated_impact= payload.get("estimated_impact", ""),
                )
                return {"success": True, "proposal": proposal}
            except Exception as e:
                return {"success": False, "error": str(e)}

        if op_name == "emit_mesh_event":
            try:
                from mesh.event_bus import event_bus, make_event
                event_bus.publish_sync(make_event(
                    source  = payload.get("source_node", "bioyth0n"),
                    event   = payload["event_name"],
                    payload = payload["payload"],
                ))
                return {"success": True, "op": "emit_mesh_event"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        return {"success": False, "error": f"unknown_system_op:{op_name}"}


# ─────────────────────────────────────────────
# Bioyth0n Executor — The Blind Exact Executioner
# ─────────────────────────────────────────────

class BioyTh0nExecutor:
    """
    THE BLIND EXACT EXECUTIONER.

    Rules (absolute, never violated):
    1. Does NOT reason freely.
    2. Does NOT chat or explain.
    3. Does NOT decide what to execute.
    4. ONLY executes ops that are:
       a. In the ApprovedOpsRegistry
       b. Have passed the BioyTh0nGate (EE trusted + Emma approved + human if required)
    5. Every execution is recorded to DeltaVault.
    6. Every failure is recorded to the safety logger.
    """

    def __init__(self):
        self._gate       = BioyTh0nGate()
        self._file_ops   = _FileOps()
        self._scaffold   = _ScaffoldOps()
        self._fivem      = _FiveMOps()
        self._earth      = _EarthOps()
        self._memory     = _MemoryOps()
        self._system     = _SystemOps()
        self._history: list[ExecutionRecord] = []
        self._lock       = threading.RLock()

        self._category_map = {
            "file":     self._file_ops,
            "scaffold": self._scaffold,
            "fivem":    self._fivem,
            "earth":    self._earth,
            "memory":   self._memory,
            "system":   self._system,
        }

    def execute(
        self,
        op_name:         str,
        payload:         dict,
        eagle_eye_state: dict,
        emma_decision:   dict,
        session_id:      str  = "default",
        human_approved:  bool = False,
    ) -> ExecutionRecord:
        """
        The one and only execution entry point.
        No reasoning, no decisions — gate check then execute.
        """
        t0 = time.time()
        record = ExecutionRecord(
            op_name    = op_name,
            session_id = session_id,
            payload    = payload,
        )

        # Step 1 — Look up op in registry (NO reasoning about what op to use)
        valid, reason, op = approved_ops.validate(op_name, payload)
        if not valid:
            record.success = False
            record.error   = f"op_validation_failed:{reason}"
            self._log_failure(record)
            return record

        record.op_id = op.op_id

        # Step 2 — Gate check (binary pass/fail — NO reasoning)
        gate_passed, failures = self._gate.check(
            op              = op,
            eagle_eye_state = eagle_eye_state,
            emma_decision   = emma_decision,
            human_approved  = human_approved,
        )
        record.gate_passed = gate_passed

        if not gate_passed:
            record.success = False
            record.error   = f"gate_failed:{','.join(failures)}"
            logger.warning(
                f"[Bioyth0n] GATE BLOCKED op={op_name} "
                f"session={session_id} failures={failures}"
            )
            self._log_failure(record)
            return record

        # Step 3 — Execute (mechanical, no reasoning)
        executor = self._category_map.get(op.category)
        if not executor:
            record.success = False
            record.error   = f"no_executor_for_category:{op.category}"
            self._log_failure(record)
            return record

        try:
            result = executor.run(op_name, payload)
            record.result  = result
            record.success = result.get("success", False)
            if not record.success:
                record.error = result.get("error", "execution_failed")
        except Exception as e:
            record.success = False
            record.error   = f"execution_exception:{str(e)}"
            logger.error(f"[Bioyth0n] exception op={op_name}: {e}")

        record.duration_ms = round((time.time() - t0) * 1000, 2)

        # Step 4 — Log to DeltaVault (unconditional — every execution is recorded)
        self._vault_log(record, op)

        # Step 5 — Store in local history
        with self._lock:
            self._history.append(record)
            if len(self._history) > 500:
                self._history.pop(0)

        logger.info(
            f"[Bioyth0n] EXECUTED op={op_name} op_id={op.op_id} "
            f"success={record.success} ms={record.duration_ms:.1f} "
            f"session={session_id}"
        )
        return record

    def _vault_log(self, record: ExecutionRecord, op: ApprovedOp) -> None:
        try:
            from unr5.delta_vault import delta_vault
            delta_vault.append_approved(
                action_type = f"bioyth0n_{op.category}_{record.op_name}",
                payload     = {
                    "exec_id":    record.exec_id,
                    "op_id":      record.op_id,
                    "op_name":    record.op_name,
                    "session_id": record.session_id,
                    "success":    record.success,
                    "error":      record.error,
                    "duration_ms": record.duration_ms,
                    "gate_passed": record.gate_passed,
                },
                approved_by = "BioyTh0n",
            )
            record.vault_logged = True
        except Exception as e:
            logger.warning(f"[Bioyth0n] vault log failed: {e}")

    def _log_failure(self, record: ExecutionRecord) -> None:
        try:
            from safety.override import s6_logger
            s6_logger.log(
                event_type  = "bioyth0n_failure",
                action_type = record.op_name,
                session_id  = record.session_id,
                details     = {"error": record.error, "exec_id": record.exec_id},
                source      = "BioyTh0n",
                severity    = "warning",
            )
        except Exception:
            pass
        with self._lock:
            self._history.append(record)

    def get_history(self, n: int = 20) -> list[dict]:
        with self._lock:
            return [r.to_dict() for r in self._history[-n:]]

    def get_stats(self) -> dict:
        with self._lock:
            records = list(self._history)
        if not records:
            return {"total": 0}
        return {
            "total":       len(records),
            "success":     sum(1 for r in records if r.success),
            "failed":      sum(1 for r in records if not r.success),
            "gate_blocks": sum(1 for r in records if not r.gate_passed),
            "avg_ms":      round(sum(r.duration_ms for r in records) / len(records), 2),
        }


# ─────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────
bioyth0n = BioyTh0nExecutor()