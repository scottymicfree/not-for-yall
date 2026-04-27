"""
Sentinel — Earth Signal Detection + Governance Trend Monitor
Python port of sentinel/detectSignals.ts

Compares SimA vs SimB drift, builds governance trend from DeltaVault + Emma memory,
maintains rolling 20-point trend history.
"""

import time
import threading
from collections import deque
from typing import List, Dict, Any, Optional


def _round3(v: float) -> float:
    return round(v, 3)


def _get_signal_level(value: float) -> str:
    if value >= 0.12:
        return "warning"
    if value >= 0.05:
        return "watch"
    return "normal"


class SentinelEngine:
    """
    Sentinel monitors Earth drift (SimA vs SimB), governance activity,
    and Emma rejection patterns. Maintains rolling trend memory.
    """

    def __init__(self, max_trend_points: int = 20):
        self._trend_memory: deque = deque(maxlen=max_trend_points)
        self._lock = threading.RLock()

    def detect_signals(
        self,
        earth_baseline: dict,
        twin_earth: dict,
        ledger_entries: List[dict] = None,
        emma_reviews: List[dict] = None,
    ) -> dict:
        ledger_entries = ledger_entries or []
        emma_reviews = emma_reviews or []

        sim_a = twin_earth.get("simA", {}).get("earth", {})
        sim_b = twin_earth.get("simB", {}).get("earth", {})

        stability_delta  = _round3(abs(sim_b.get("stability", 0)      - sim_a.get("stability", 0)))
        climate_delta    = _round3(abs(sim_b.get("climatePressure", 0) - sim_a.get("climatePressure", 0)))
        seismic_delta    = _round3(abs(sim_b.get("seismicPressure", 0) - sim_a.get("seismicPressure", 0)))
        resource_delta   = _round3(abs(sim_b.get("resourceStrain", 0)  - sim_a.get("resourceStrain", 0)))

        drift_index = _round3((stability_delta + climate_delta + seismic_delta + resource_delta) / 4.0)

        ts = earth_baseline.get("timestamp", int(time.time() * 1000))
        trend_point = {
            "timestamp": ts,
            "driftIndex": drift_index,
            "stabilityDelta": stability_delta,
            "climateDelta": climate_delta,
            "seismicDelta": seismic_delta,
            "resourceDelta": resource_delta,
        }

        with self._lock:
            self._trend_memory.append(trend_point)
            trend = self._compute_trend(drift_index)

        governance = self._build_governance_trend(ledger_entries, emma_reviews)

        signals = [
            {
                "key": "stability-drift",
                "level": _get_signal_level(stability_delta),
                "value": stability_delta,
                "summary": f"Stability drift is {stability_delta}.",
            },
            {
                "key": "climate-drift",
                "level": _get_signal_level(climate_delta),
                "value": climate_delta,
                "summary": f"Climate pressure drift is {climate_delta}.",
            },
            {
                "key": "seismic-drift",
                "level": _get_signal_level(seismic_delta),
                "value": seismic_delta,
                "summary": f"Seismic pressure drift is {seismic_delta}.",
            },
            {
                "key": "resource-drift",
                "level": _get_signal_level(resource_delta),
                "value": resource_delta,
                "summary": f"Resource strain drift is {resource_delta}.",
            },
            {
                "key": "composite-drift",
                "level": _get_signal_level(drift_index),
                "value": drift_index,
                "summary": f"Composite Earth/Twin Earth drift is {drift_index}.",
            },
            {
                "key": "governance-review-spike",
                "level": "watch" if governance["reviewSpike"] else "normal",
                "value": governance["approvalCount"] + governance["rejectionCount"],
                "summary": (
                    "Governance review volume is elevated."
                    if governance["reviewSpike"] else
                    "Governance review volume is normal."
                ),
            },
            {
                "key": "deltavault-write-burst",
                "level": "warning" if governance["ledgerBurst"] else "normal",
                "value": governance["recentEntries"],
                "summary": (
                    "DeltaVault write burst detected."
                    if governance["ledgerBurst"] else
                    "DeltaVault write activity is normal."
                ),
            },
            {
                "key": "emma-rejection-pattern",
                "level": (
                    "warning" if governance["rejectionCount"] >= 3
                    else "watch" if governance["rejectionCount"] >= 1
                    else "normal"
                ),
                "value": governance["rejectionCount"],
                "summary": (
                    "Emma rejection count is unusually high."
                    if governance["rejectionCount"] >= 3
                    else "Emma has recent rejections to review."
                    if governance["rejectionCount"] >= 1
                    else "Emma rejection pattern is normal."
                ),
            },
        ]

        return {
            "timestamp": int(time.time() * 1000),
            "driftIndex": drift_index,
            "stabilityDelta": stability_delta,
            "climateDelta": climate_delta,
            "seismicDelta": seismic_delta,
            "resourceDelta": resource_delta,
            "signals": signals,
            "trend": trend,
            "governance": governance,
        }

    def _compute_trend(self, latest_drift: float) -> dict:
        points = list(self._trend_memory)
        if not points:
            return {"points": [], "direction": "stable", "averageDrift": 0.0, "latestDrift": latest_drift}

        avg = _round3(sum(p["driftIndex"] for p in points) / len(points))
        direction = "stable"
        if len(points) >= 2:
            prev = points[-2]["driftIndex"]
            if latest_drift > prev:
                direction = "rising"
            elif latest_drift < prev:
                direction = "falling"

        return {
            "points": points,
            "direction": direction,
            "averageDrift": avg,
            "latestDrift": latest_drift,
        }

    def _build_governance_trend(self, ledger_entries: List[dict], emma_reviews: List[dict]) -> dict:
        now = int(time.time() * 1000)
        recent_window_ms = 5 * 60 * 1000  # 5 minutes

        recent_entries = sum(
            1 for e in ledger_entries
            if now - e.get("timestamp", 0) <= recent_window_ms
        )

        approval_count  = sum(1 for r in emma_reviews if r.get("decision") == "approved")
        rejection_count = sum(1 for r in emma_reviews if r.get("decision") == "rejected")

        return {
            "totalEntries":   len(ledger_entries),
            "recentEntries":  recent_entries,
            "approvalCount":  approval_count,
            "rejectionCount": rejection_count,
            "reviewSpike":    len(emma_reviews) >= 5,
            "ledgerBurst":    recent_entries >= 3,
        }

    def get_trend_memory(self) -> list:
        with self._lock:
            return list(self._trend_memory)


# Singleton
sentinel_engine = SentinelEngine()