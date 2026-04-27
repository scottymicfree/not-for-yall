"""
Lucy OS v5 — Sandbox Simulator
Run isolated simulations: TwinEarth scenarios, FiveM dry-runs,
code inspection, upgrade proposals, and learning loops.
"""

from __future__ import annotations
import asyncio
import time
import uuid
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("chat.sandbox")

SIM_TIMEOUT = 30.0    # seconds max per simulation


@dataclass
class SimulationResult:
    sim_id:       str   = field(default_factory=lambda: str(uuid.uuid4())[:10])
    sim_type:     str   = ""
    status:       str   = "pending"    # pending | running | complete | failed | timeout
    input_data:   dict  = field(default_factory=dict)
    output_data:  dict  = field(default_factory=dict)
    logs:         list[str] = field(default_factory=list)
    duration_ms:  float = 0.0
    timestamp:    float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "sim_id":      self.sim_id,
            "sim_type":    self.sim_type,
            "status":      self.status,
            "input_data":  self.input_data,
            "output_data": self.output_data,
            "logs":        self.logs,
            "duration_ms": round(self.duration_ms, 2),
            "timestamp":   self.timestamp,
        }


class SandboxRunner:
    """
    Executes sandbox simulations in isolation.
    Supports: earth, fivem, code, upgrade, learning_loop, auto_builder
    """

    def __init__(self):
        self._history: list[SimulationResult] = []

    async def run(
        self,
        sim_type:   str,
        params:     dict,
        session_id: str = "default",
    ) -> SimulationResult:
        result = SimulationResult(sim_type=sim_type, input_data=params)
        result.status = "running"
        t0 = time.time()

        try:
            runner = self._get_runner(sim_type)
            if not runner:
                result.status = "failed"
                result.output_data = {"error": f"unknown_sim_type:{sim_type}"}
            else:
                output = await asyncio.wait_for(runner(params, result), timeout=SIM_TIMEOUT)
                result.output_data = output or {}
                result.status = "complete"

        except asyncio.TimeoutError:
            result.status = "timeout"
            result.output_data = {"error": "simulation_timed_out"}
            result.logs.append(f"TIMEOUT after {SIM_TIMEOUT}s")
        except Exception as e:
            result.status = "failed"
            result.output_data = {"error": str(e)}
            result.logs.append(f"ERROR: {e}")
            logger.error(f"[Sandbox] sim_type={sim_type} error: {e}")

        result.duration_ms = round((time.time() - t0) * 1000, 2)
        self._history.append(result)

        logger.info(
            f"[Sandbox] sim_id={result.sim_id} type={sim_type} "
            f"status={result.status} ms={result.duration_ms:.0f}"
        )
        return result

    def _get_runner(self, sim_type: str):
        return {
            "earth":         self._run_earth_sim,
            "twin_earth":    self._run_twin_earth,
            "fivem":         self._run_fivem_sim,
            "code_inspect":  self._run_code_inspect,
            "upgrade":       self._run_upgrade_proposal,
            "learning_loop": self._run_learning_loop,
            "auto_builder":  self._run_auto_builder,
            "sentinel":      self._run_sentinel_scan,
            "health_check":  self._run_health_check,
        }.get(sim_type)

    # ── Earth Simulation ─────────────────────────────────────────────

    async def _run_earth_sim(self, params: dict, result: SimulationResult) -> dict:
        result.logs.append("Fetching Earth baseline (SimA)...")
        try:
            from unr5.earth import fetch_earth_baseline_sync
            baseline = fetch_earth_baseline_sync()
            result.logs.append(f"SimA fetched: {len(baseline)} signals")
            return {"sima": baseline, "source": "live_apis"}
        except Exception as e:
            result.logs.append(f"Earth API error: {e}")
            return {"error": str(e), "sima": {}}

    async def _run_twin_earth(self, params: dict, result: SimulationResult) -> dict:
        result.logs.append("Building TwinEarth (SimA + SimB)...")
        try:
            from unr5.earth import fetch_earth_baseline_sync, build_twin_earth_state
            baseline = fetch_earth_baseline_sync()
            twin     = build_twin_earth_state(baseline)
            result.logs.append(f"SimB computed. Drift index: {twin.get('drift_index', 'N/A')}")
            return twin
        except Exception as e:
            result.logs.append(f"TwinEarth error: {e}")
            return {"error": str(e)}

    async def _run_fivem_sim(self, params: dict, result: SimulationResult) -> dict:
        result.logs.append("Running FiveM server snapshot (dry-run)...")
        try:
            from bridges.fivem_bridge import fivem_bridge
            snapshot = await fivem_bridge.get_full_snapshot()
            result.logs.append(
                f"FiveM {'online' if snapshot.get('online') else 'offline'} — "
                f"players={snapshot.get('players', {}).get('player_count', 'N/A')}"
            )
            return snapshot
        except Exception as e:
            result.logs.append(f"FiveM bridge error: {e}")
            return {"error": str(e), "online": False}

    # ── Code Inspection ──────────────────────────────────────────────

    async def _run_code_inspect(self, params: dict, result: SimulationResult) -> dict:
        file_path = params.get("file_path", "")
        result.logs.append(f"Inspecting: {file_path}")

        if not file_path:
            return {"error": "no_file_path"}

        try:
            from bioyth0n.file_writer import governed_file_writer
            read_result = governed_file_writer.read(file_path)
            if not read_result["success"]:
                return {"error": read_result.get("error", "read_failed")}

            content = read_result["content"]
            lines   = content.split("\n")
            result.logs.append(f"Read {len(lines)} lines")

            # Basic static analysis
            issues:   list[str] = []
            warnings: list[str] = []

            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                # Check for common issues
                if "TODO" in stripped or "FIXME" in stripped:
                    warnings.append(f"L{i}: {stripped[:80]}")
                if "except:" in stripped or "except Exception:" in stripped:
                    issues.append(f"L{i}: broad exception handler")
                if "print(" in stripped and "debug" not in stripped.lower():
                    warnings.append(f"L{i}: unchecked print statement")
                if len(line) > 120:
                    warnings.append(f"L{i}: line length {len(line)} > 120")

            # Attempt import check
            imports = [l.strip() for l in lines if l.strip().startswith(("import ", "from "))]

            return {
                "file_path":   file_path,
                "lines":       len(lines),
                "imports":     imports[:20],
                "issues":      issues[:10],
                "warnings":    warnings[:10],
                "size_bytes":  read_result.get("bytes", 0),
                "summary":     f"{len(issues)} issues, {len(warnings)} warnings in {len(lines)} lines",
            }
        except Exception as e:
            return {"error": str(e)}

    # ── Upgrade Proposal ─────────────────────────────────────────────

    async def _run_upgrade_proposal(self, params: dict, result: SimulationResult) -> dict:
        title         = params.get("title", "Untitled Upgrade")
        description   = params.get("description", "")
        target_module = params.get("target_module", "unknown")
        result.logs.append(f"Creating upgrade proposal: {title}")

        try:
            from unr5.upgrades import upgrade_store
            proposal = upgrade_store.create(
                title           = title,
                description     = description,
                target_module   = target_module,
                priority        = params.get("priority", "medium"),
                estimated_impact= params.get("estimated_impact", ""),
            )
            result.logs.append(f"Proposal created: {proposal.get('id', 'N/A')}")
            return {"proposal": proposal, "status": "created"}
        except Exception as e:
            result.logs.append(f"Upgrade store error: {e}")
            return {
                "proposal": {
                    "title":          title,
                    "target_module":  target_module,
                    "description":    description,
                    "status":         "draft",
                },
                "status": "draft",
            }

    # ── Learning Loop ────────────────────────────────────────────────

    async def _run_learning_loop(self, params: dict, result: SimulationResult) -> dict:
        session_id = params.get("session_id", "default")
        result.logs.append(f"Running learning loop for session: {session_id}")

        signals: list[str] = []

        # Pull reflection queue
        try:
            from lucy_prime.output import lp12_dispatcher
            queue_size = lp12_dispatcher.get_reflection_queue_size()
            result.logs.append(f"Reflection queue: {queue_size} items")
            signals.append(f"reflection_queue={queue_size}")
        except Exception as e:
            result.logs.append(f"Reflection queue error: {e}")

        # Memory compression
        try:
            from memory.memory_core import memory_system
            memory_system.compress_old_memories(session_id)
            result.logs.append("Memory compression run")
            signals.append("memory_compressed=true")
        except Exception as e:
            result.logs.append(f"Memory compression error: {e}")

        # Attention weight decay
        try:
            from mesh.attention import attention_engine
            attention_engine.decay_tick()
            result.logs.append("Attention weights decayed")
            signals.append("attention_decayed=true")
        except Exception as e:
            result.logs.append(f"Attention decay error: {e}")

        # Policy decay
        try:
            from safety.policy_engine import policy_engine
            policy_engine.decay_tick()
            result.logs.append("Policy weights decayed")
            signals.append("policy_decayed=true")
        except Exception as e:
            result.logs.append(f"Policy decay error: {e}")

        return {
            "session_id": session_id,
            "signals":    signals,
            "status":     "learning_loop_complete",
        }

    # ── Auto Builder ─────────────────────────────────────────────────

    async def _run_auto_builder(self, params: dict, result: SimulationResult) -> dict:
        prompt = params.get("prompt", "")
        result.logs.append(f"Running AutoBuilder: {prompt[:80]}")
        try:
            from unr5.auto_builder import run_builder
            loop = asyncio.get_event_loop()
            build_result = await loop.run_in_executor(None, run_builder, prompt)
            result.logs.append(f"AutoBuilder complete: {build_result.get('status', 'unknown')}")
            return build_result
        except Exception as e:
            result.logs.append(f"AutoBuilder error: {e}")
            return {"error": str(e), "prompt": prompt}

    # ── Sentinel Scan ────────────────────────────────────────────────

    async def _run_sentinel_scan(self, params: dict, result: SimulationResult) -> dict:
        result.logs.append("Running Sentinel signal scan...")
        try:
            from unr5.sentinel import sentinel_engine
            from unr5.earth    import fetch_earth_baseline_sync, build_twin_earth_state
            baseline = fetch_earth_baseline_sync()
            twin     = build_twin_earth_state(baseline)
            signals  = sentinel_engine.detect_signals(baseline, twin)
            result.logs.append(f"Detected {len(signals)} signals")
            return {"signals": signals, "count": len(signals)}
        except Exception as e:
            result.logs.append(f"Sentinel error: {e}")
            return {"error": str(e)}

    # ── Health Check ─────────────────────────────────────────────────

    async def _run_health_check(self, params: dict, result: SimulationResult) -> dict:
        result.logs.append("Running mesh health check...")
        try:
            from mesh.health_monitor import health_monitor
            report = health_monitor.run_check_now()
            result.logs.append(f"Health: {report.get('overall', 'unknown')}")
            return report
        except Exception as e:
            result.logs.append(f"Health monitor error: {e}")
            return {"error": str(e)}

    def get_history(self, n: int = 10) -> list[dict]:
        return [r.to_dict() for r in self._history[-n:]]


# Singleton
sandbox_runner = SandboxRunner()