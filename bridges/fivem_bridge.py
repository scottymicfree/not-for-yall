"""
Lucy OS v5 — FiveM Bridge (Python)
Full bidirectional bridge between Lucy and a FiveM server.
READ: player count, server health, resources, latency, economy, jobs, NPC activity,
      police/EMS/fire/gang systems, mission state, logs
WRITE (approved): spawn NPC, generate missions, repair resources, write scripts,
                  dispatch events, balance economy, detect empty loops
"""

from __future__ import annotations
import asyncio
import hashlib
import hmac
import json
import time
import logging
from typing import Any

logger = logging.getLogger("bridges.fivem")

# ─────────────────────────────────────────────
# Configuration (loaded from lucy-os/config or env)
# ─────────────────────────────────────────────

import os

FIVEM_BASE_URL    = os.environ.get("FIVEM_URL",    "http://localhost:30120")
FIVEM_LUCY_URL    = os.environ.get("FIVEM_LUCY_URL", "http://localhost:30120/lucy")
SHARED_SECRET     = os.environ.get("FIVEM_SECRET",  "lucy-bridge-secret-v5")
HEARTBEAT_INTERVAL = int(os.environ.get("FIVEM_HEARTBEAT", "30"))
COMMAND_POLL_INTERVAL = int(os.environ.get("FIVEM_CMD_POLL", "5"))
CONNECT_TIMEOUT   = 5.0
REQUEST_TIMEOUT   = 10.0


def _sign(payload: dict) -> str:
    """HMAC-SHA256 signature for Lucy↔FiveM authentication."""
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hmac.new(
        SHARED_SECRET.encode(), raw.encode(), hashlib.sha256
    ).hexdigest()


def _build_headers(payload: dict) -> dict:
    return {
        "Content-Type":      "application/json",
        "X-Lucy-Signature":  _sign(payload),
        "X-Lucy-Timestamp":  str(int(time.time())),
        "X-Lucy-Version":    "5.0",
    }


# ─────────────────────────────────────────────
# FiveM Bridge Core
# ─────────────────────────────────────────────

class FiveMBridge:
    """
    Full Python bridge to a FiveM server running the lucy_bridge resource.
    All methods are async. Requires aiohttp at runtime.
    """

    def __init__(self):
        self._session = None
        self._connected = False
        self._last_heartbeat = 0.0
        self._server_info: dict = {}

    async def _get_session(self):
        try:
            import aiohttp
            if self._session is None or self._session.closed:
                timeout = aiohttp.ClientTimeout(
                    connect=CONNECT_TIMEOUT, total=REQUEST_TIMEOUT
                )
                self._session = aiohttp.ClientSession(timeout=timeout)
            return self._session
        except ImportError:
            return None

    async def _post(self, endpoint: str, payload: dict) -> dict:
        session = await self._get_session()
        if not session:
            return {"success": False, "error": "aiohttp_not_available"}
        url = f"{FIVEM_LUCY_URL}/{endpoint.lstrip('/')}"
        headers = _build_headers(payload)
        try:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {"success": True, "data": data}
                else:
                    text = await resp.text()
                    return {"success": False, "error": f"http_{resp.status}", "body": text[:200]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _get(self, endpoint: str, params: dict = None) -> dict:
        session = await self._get_session()
        if not session:
            return {"success": False, "error": "aiohttp_not_available"}
        url = f"{FIVEM_BASE_URL}/{endpoint.lstrip('/')}"
        try:
            async with session.get(url, params=params or {}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {"success": True, "data": data}
                else:
                    return {"success": False, "error": f"http_{resp.status}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── READ OPERATIONS ───────────────────────────────────────────────

    async def get_player_count(self) -> dict:
        """Get current player count from FiveM server."""
        result = await self._get("players.json")
        if result["success"]:
            players = result["data"]
            return {
                "success":      True,
                "player_count": len(players),
                "players":      players,
            }
        return result

    async def get_server_info(self) -> dict:
        """Get server info/metadata."""
        result = await self._get("info.json")
        if result["success"]:
            self._server_info = result["data"]
        return result

    async def get_server_health(self) -> dict:
        """Aggregate health check: player count + resources + latency."""
        info_r    = await self._get("info.json")
        players_r = await self._get("players.json")

        player_count = len(players_r.get("data", [])) if players_r["success"] else -1

        health = {
            "success":      True,
            "player_count": player_count,
            "server_name":  info_r.get("data", {}).get("vars", {}).get("sv_projectName", "unknown"),
            "max_players":  info_r.get("data", {}).get("vars", {}).get("sv_maxClients", 0),
            "uptime":       info_r.get("data", {}).get("vars", {}).get("uptime", 0),
            "online":       info_r["success"],
            "checked_at":   time.time(),
        }
        return health

    async def get_resources(self) -> dict:
        """Get list of all server resources and their status."""
        result = await self._post("status", {"type": "resource_list"})
        if not result["success"]:
            # Fallback: try native FiveM endpoint
            result = await self._get("")
        return result

    async def get_resource_status(self, resource_name: str) -> dict:
        """Get status of a specific resource."""
        return await self._post("status", {
            "type":     "resource_status",
            "resource": resource_name,
        })

    async def get_economy_signals(self) -> dict:
        """Read economy signals from the bridge."""
        return await self._post("status", {"type": "economy_signals"})

    async def get_player_jobs(self) -> dict:
        """Read current player job distribution."""
        return await self._post("status", {"type": "player_jobs"})

    async def get_npc_activity(self) -> dict:
        """Read NPC activity state from the server."""
        return await self._post("status", {"type": "npc_activity"})

    async def get_gang_state(self) -> dict:
        """Read gang zone / gang system state."""
        return await self._post("status", {"type": "gang_state"})

    async def get_police_state(self) -> dict:
        """Read police system state (on-duty, calls, etc)."""
        return await self._post("status", {"type": "police_state"})

    async def get_ems_state(self) -> dict:
        """Read EMS system state."""
        return await self._post("status", {"type": "ems_state"})

    async def get_fire_state(self) -> dict:
        """Read fire department system state."""
        return await self._post("status", {"type": "fire_state"})

    async def get_mission_state(self) -> dict:
        """Read current mission director state."""
        return await self._post("status", {"type": "mission_state"})

    async def get_logs(self, tail: int = 50) -> dict:
        """Retrieve recent server logs."""
        return await self._post("logs", {"tail": tail})

    async def detect_empty_rp_loops(self) -> dict:
        """Detect players in empty roleplay loops (AFK/dead/stuck)."""
        return await self._post("status", {"type": "empty_rp_detection"})

    async def get_latency(self) -> dict:
        """Measure round-trip latency to FiveM server."""
        t0 = time.time()
        result = await self._get("info.json")
        latency_ms = round((time.time() - t0) * 1000, 1)
        return {
            "success":    result["success"],
            "latency_ms": latency_ms,
            "reachable":  result["success"],
        }

    async def get_full_snapshot(self) -> dict:
        """
        Comprehensive server snapshot — all read operations in parallel.
        Used by dashboard and TwinEarth FiveM integration.
        """
        results = await asyncio.gather(
            self.get_player_count(),
            self.get_server_health(),
            self.get_economy_signals(),
            self.get_player_jobs(),
            self.get_gang_state(),
            self.get_police_state(),
            self.get_mission_state(),
            self.get_latency(),
            return_exceptions=True,
        )

        labels = [
            "players", "health", "economy", "jobs",
            "gangs", "police", "missions", "latency",
        ]
        snapshot: dict[str, Any] = {"timestamp": time.time()}
        for label, result in zip(labels, results):
            if isinstance(result, Exception):
                snapshot[label] = {"success": False, "error": str(result)}
            else:
                snapshot[label] = result

        snapshot["online"] = snapshot["health"].get("online", False)
        return snapshot

    # ── WRITE OPERATIONS (all require Eagle Eye + Emma approval) ──────

    async def spawn_npc(
        self,
        npc_model: str,
        coords:    dict,
        heading:   float = 0.0,
        scenario:  str   = "",
        faction:   str   = "",
    ) -> dict:
        """Spawn an NPC support entity at coords."""
        payload = {
            "command": "spawn_npc",
            "model":   npc_model,
            "coords":  coords,
            "heading": heading,
            "scenario": scenario,
            "faction":  faction,
        }
        return await self._post("command", payload)

    async def create_mission(
        self,
        mission_type: str,
        mission_data: dict,
    ) -> dict:
        """Inject a new mission into the mission director."""
        payload = {
            "command":      "create_mission",
            "mission_type": mission_type,
            "mission_data": mission_data,
        }
        return await self._post("command", payload)

    async def repair_resource(self, resource_name: str, force: bool = False) -> dict:
        """Restart or repair a broken resource."""
        payload = {
            "command":  "repair_resource",
            "resource": resource_name,
            "force":    force,
        }
        return await self._post("command", payload)

    async def write_script(
        self,
        resource_name: str,
        script_name:   str,
        content:       str,
    ) -> dict:
        """Write a Lua script to a resource (via Lucy bridge approval flow)."""
        # This goes through the file writer, not direct HTTP
        from bioyth0n.file_writer import governed_file_writer
        path = f"fivem_resources/{resource_name}/{script_name}"
        return governed_file_writer.write(path, content)

    async def dispatch_event(
        self,
        event_type:  str,
        location:    dict,
        description: str,
        priority:    str = "medium",
        units:       int = 1,
    ) -> dict:
        """Push a dispatch event to emergency services."""
        payload = {
            "command":     "dispatch_event",
            "event_type":  event_type,
            "location":    location,
            "description": description,
            "priority":    priority,
            "units":       units,
        }
        return await self._post("command", payload)

    async def balance_economy(
        self,
        adjustment_type: str,
        amount:          float,
        target_job:      str = "",
        reason:          str = "",
    ) -> dict:
        """Apply economy balancing adjustment."""
        payload = {
            "command":          "balance_economy",
            "adjustment_type":  adjustment_type,
            "amount":           amount,
            "target_job":       target_job,
            "reason":           reason,
        }
        return await self._post("command", payload)

    async def kick_player(self, player_id: str | int, reason: str = "") -> dict:
        """Kick a player (requires human approval via Bioyth0n gate)."""
        payload = {
            "command":   "kick_player",
            "player_id": str(player_id),
            "reason":    reason or "Action by Lucy OS v5",
        }
        return await self._post("command", payload)

    async def heartbeat(self) -> dict:
        """Send heartbeat to FiveM bridge resource."""
        payload = {"type": "heartbeat", "timestamp": time.time(), "version": "5.0"}
        result  = await self._post("heartbeat", payload)
        if result["success"]:
            self._connected      = True
            self._last_heartbeat = time.time()
        else:
            self._connected = False
        return result

    async def poll_commands(self) -> list[dict]:
        """Poll pending commands queued by the FiveM bridge resource."""
        result = await self._post("poll", {"type": "command_poll"})
        if result["success"]:
            return result.get("data", {}).get("commands", [])
        return []

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def is_connected(self) -> bool:
        return self._connected and (time.time() - self._last_heartbeat < HEARTBEAT_INTERVAL * 2)

    def get_status(self) -> dict:
        return {
            "connected":        self._connected,
            "last_heartbeat":   self._last_heartbeat,
            "server_url":       FIVEM_BASE_URL,
            "heartbeat_age_s":  round(time.time() - self._last_heartbeat, 1),
        }


# Singleton
fivem_bridge = FiveMBridge()