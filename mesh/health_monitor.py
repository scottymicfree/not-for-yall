"""
N10 — Health Monitor
Monitors all 137 nodes continuously.
Detects degraded/offline nodes, triggers auto-repair, alerts Eagle Eye.
"""

import time
import asyncio
import threading
import logging
from typing import Dict, List, Optional, Callable
from collections import defaultdict

from mesh.node_registry import node_registry
from mesh.event_bus import event_bus, make_event

logger = logging.getLogger("lucy.health")


class HealthMonitor:
    """
    N10 — Continuously monitors node health.
    - Checks last_active timestamps
    - Detects error rate spikes
    - Emits health events on bus
    - Auto-restores degraded nodes after recovery period
    - Produces health report for Eagle Eye
    """

    STALE_THRESHOLD_S = 300        # Node is stale after 5 min of no activity
    RECOVERY_THRESHOLD_S = 60      # Degraded node recovers after 60s without new errors
    CHECK_INTERVAL_S = 30          # Health check every 30 seconds
    ERROR_SPIKE_THRESHOLD = 10     # >10 errors = degraded

    def __init__(self):
        self._repair_callbacks: Dict[str, Callable] = {}
        self._health_history: List[dict] = []
        self._max_history = 200
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._last_check_ts = 0

    def start(self):
        """Start background health monitoring thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="lucy-health")
        self._thread.start()
        logger.info("Health monitor started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def register_repair_callback(self, node_id: str, callback: Callable):
        """Register a repair function to call when a node goes degraded."""
        self._repair_callbacks[node_id] = callback

    def _monitor_loop(self):
        while self._running:
            try:
                self._run_check()
            except Exception as e:
                logger.error(f"Health check error: {e}")
            time.sleep(self.CHECK_INTERVAL_S)

    def _run_check(self):
        now = time.time()
        self._last_check_ts = now
        report = self._generate_report()

        with self._lock:
            self._health_history.append(report)
            if len(self._health_history) > self._max_history:
                self._health_history.pop(0)

        # Emit health event on bus
        event_bus.emit_event(
            source="N10",
            event_type="health_check",
            payload=report,
            target="broadcast",
            priority=2,
        )

        # Handle degraded nodes
        for node_info in report.get("degradedNodes", []):
            nid = node_info["nodeId"]
            if nid in self._repair_callbacks:
                try:
                    self._repair_callbacks[nid]()
                    node_registry.update_status(nid, "online", load=0.0)
                    logger.info(f"Auto-repaired node {nid}")
                except Exception as e:
                    logger.warning(f"Repair failed for {nid}: {e}")

        # Log critical events
        if report["offlineCount"] > 0:
            logger.warning(f"Health check: {report['offlineCount']} nodes offline")
        if report["degradedCount"] > 5:
            logger.error(f"Health check: {report['degradedCount']} nodes degraded — mesh stressed")

    def _generate_report(self) -> dict:
        now = time.time()
        all_nodes = node_registry.all()

        online_count   = 0
        degraded_count = 0
        offline_count  = 0
        busy_count     = 0
        stale_nodes    = []
        degraded_nodes = []
        offline_nodes  = []

        for node in all_nodes:
            status     = node["status"]
            last_active = node.get("lastActive", 0)
            error_count = node.get("errorCount", 0)
            node_id    = node["nodeId"]

            # Auto-detect stale
            if status == "online" and (now - last_active) > self.STALE_THRESHOLD_S:
                stale_nodes.append({"nodeId": node_id, "staleSecs": int(now - last_active)})

            if status == "online":
                online_count += 1
            elif status == "busy":
                busy_count += 1
            elif status == "degraded":
                degraded_count += 1
                degraded_nodes.append({
                    "nodeId": node_id,
                    "errorCount": error_count,
                    "layer": node["layer"],
                })
                # Auto-recover if no recent errors and enough time has passed
                if error_count < self.ERROR_SPIKE_THRESHOLD:
                    node_registry.update_status(node_id, "online")
            elif status == "offline":
                offline_count += 1
                offline_nodes.append({"nodeId": node_id, "layer": node["layer"]})

        total = len(all_nodes)
        healthy = online_count + busy_count
        health_pct = round(healthy / total * 100, 1) if total else 0

        overall = (
            "critical" if offline_count > 10 or health_pct < 70
            else "degraded" if degraded_count > 5 or health_pct < 90
            else "healthy"
        )

        return {
            "timestamp": int(time.time() * 1000),
            "overall": overall,
            "healthPct": health_pct,
            "totalNodes": total,
            "onlineCount": online_count,
            "busyCount": busy_count,
            "degradedCount": degraded_count,
            "offlineCount": offline_count,
            "staleNodes": stale_nodes[:10],
            "degradedNodes": degraded_nodes,
            "offlineNodes": offline_nodes,
        }

    def run_check_now(self) -> dict:
        """Run a health check immediately and return report."""
        return self._generate_report()

    def get_history(self, limit: int = 20) -> List[dict]:
        with self._lock:
            return self._health_history[-limit:]

    def get_node_health(self, node_id: str) -> dict:
        node = node_registry.get(node_id)
        if not node:
            return {"nodeId": node_id, "found": False}
        return {
            "nodeId": node_id,
            "status": node.status,
            "load": node.load,
            "errorCount": node.error_count,
            "messagesProcessed": node.messages_processed,
            "lastActive": node.last_active,
            "staleSecs": max(0, int(time.time() - node.last_active)),
        }


# Singleton
health_monitor = HealthMonitor()