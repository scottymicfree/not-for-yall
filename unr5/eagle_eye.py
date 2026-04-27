"""
Eagle Eye — System-Wide Watchdog + Confidence Scorer
Python port of eagleeye/deriveWatchState.ts + validateInputs + detectContradictions + scoreConfidence

Eagle Eye synthesizes Sentinel signals + DeltaVault integrity into a unified
pressure index and confidence score. If trusted=True, the execution gate opens.
"""

import time
from typing import List, Optional


def _round3(v: float) -> float:
    return round(v, 3)


def _to_level(score: float) -> str:
    if score >= 0.6:
        return "warning"
    if score >= 0.25:
        return "watch"
    return "stable"


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ─── Input Validation ────────────────────────────────────────────────────────

def validate_inputs(sentinel: dict, integrity: dict) -> dict:
    issues = []

    ts = sentinel.get("timestamp")
    if not isinstance(ts, (int, float)) or ts <= 0:
        issues.append("Sentinel timestamp is invalid.")

    drift = sentinel.get("driftIndex")
    if not isinstance(drift, (int, float)) or not (0 <= drift <= 1):
        issues.append("Sentinel driftIndex is out of range.")

    if not isinstance(sentinel.get("signals"), list):
        issues.append("Sentinel signals must be a list.")

    gov = sentinel.get("governance", {})
    for key in ("totalEntries", "recentEntries", "approvalCount", "rejectionCount"):
        if not isinstance(gov.get(key), (int, float)):
            issues.append(f"Sentinel governance.{key} is invalid.")

    if isinstance(gov.get("recentEntries"), int) and isinstance(gov.get("totalEntries"), int):
        if gov["recentEntries"] > gov["totalEntries"]:
            issues.append("Recent DeltaVault entries exceed total entries.")

    if not isinstance(integrity.get("ok"), bool):
        issues.append("DeltaVault integrity flag is invalid.")

    if not isinstance(integrity.get("checked"), (int, float)) or integrity.get("checked", -1) < 0:
        issues.append("DeltaVault integrity checked count is invalid.")

    if integrity.get("ok") is True and integrity.get("brokenAt") is not None:
        issues.append("DeltaVault integrity reports brokenAt while ok=True.")

    return {"valid": len(issues) == 0, "issues": issues}


# ─── Contradiction Detection ──────────────────────────────────────────────────

def detect_contradictions(sentinel: dict, integrity: dict) -> dict:
    issues = []
    signals = sentinel.get("signals", [])
    gov = sentinel.get("governance", {})
    drift = sentinel.get("driftIndex", 0)

    warning_count = sum(1 for s in signals if s.get("level") == "warning")

    if drift < 0.05 and warning_count >= 2:
        issues.append("Warning signal count is high while composite drift is low.")

    if gov.get("ledgerBurst") and gov.get("recentEntries", 0) == 0:
        issues.append("Ledger burst flag is true while recent entry count is zero.")

    if gov.get("reviewSpike") and (gov.get("approvalCount", 0) + gov.get("rejectionCount", 0)) < 5:
        issues.append("Review spike flag is true while review count is below threshold.")

    if not integrity.get("ok") and gov.get("totalEntries", 0) == 0:
        issues.append("Integrity failed while no DeltaVault entries exist.")

    rejection = gov.get("rejectionCount", 0)
    approval  = gov.get("approvalCount", 0)
    if rejection > approval * 3 and drift < 0.03:
        issues.append("Heavy rejection pattern is present while system drift remains unusually low.")

    return {"count": len(issues), "issues": issues}


# ─── Confidence Scoring ───────────────────────────────────────────────────────

def score_confidence(sentinel: dict, integrity: dict, validation: dict, contradictions: dict) -> dict:
    score = 1.0
    gov = sentinel.get("governance", {})

    if not validation.get("valid"):
        score -= len(validation.get("issues", [])) * 0.2

    if not integrity.get("ok"):
        score -= 0.35

    score -= contradictions.get("count", 0) * 0.15
    score -= min(gov.get("rejectionCount", 0) * 0.03, 0.2)

    if gov.get("reviewSpike"):
        score -= 0.05
    if gov.get("ledgerBurst"):
        score -= 0.08

    score -= min(sentinel.get("driftIndex", 0) * 0.2, 0.12)

    confidence = _round3(_clamp(score, 0.0, 1.0))
    trusted = (
        confidence >= 0.65 and
        validation.get("valid", False) and
        integrity.get("ok", False) and
        contradictions.get("count", 0) == 0
    )

    return {"confidence": confidence, "trusted": trusted}


# ─── Main Eagle Eye Derive ────────────────────────────────────────────────────

def derive_watch_state(sentinel: dict, integrity: dict) -> dict:
    validation     = validate_inputs(sentinel, integrity)
    contradictions = detect_contradictions(sentinel, integrity)
    confidence_res = score_confidence(sentinel, integrity, validation, contradictions)

    signals      = sentinel.get("signals", [])
    gov          = sentinel.get("governance", {})
    drift        = sentinel.get("driftIndex", 0)

    warning_count = sum(1 for s in signals if s.get("level") == "warning")
    watch_count   = sum(1 for s in signals if s.get("level") == "watch")

    integrity_pressure   = 0.0 if integrity.get("ok") else 1.0
    governance_pressure  = (
        (0.25 if gov.get("reviewSpike") else 0.0) +
        (0.35 if gov.get("ledgerBurst") else 0.0) +
        min(gov.get("rejectionCount", 0) * 0.1, 0.4)
    )
    signal_pressure      = min(warning_count * 0.25 + watch_count * 0.08 + drift, 1.0)
    contradiction_pressure = min(contradictions["count"] * 0.18, 0.5)
    validation_pressure  = (
        0.0 if validation["valid"]
        else min(len(validation["issues"]) * 0.15, 0.5)
    )
    confidence_penalty   = 1.0 - confidence_res["confidence"]

    pressure_index = _round3(_clamp(
        signal_pressure +
        governance_pressure +
        integrity_pressure +
        contradiction_pressure +
        validation_pressure +
        confidence_penalty * 0.5,
        0.0, 1.0
    ))

    metrics = [
        {
            "key": "sentinel-drift",
            "level": _to_level(drift),
            "value": drift,
            "summary": f"Sentinel composite drift is {drift}.",
        },
        {
            "key": "warning-signal-count",
            "level": _to_level(min(warning_count * 0.25, 1.0)),
            "value": warning_count,
            "summary": f"{warning_count} warning-level Sentinel signals detected.",
        },
        {
            "key": "governance-rejections",
            "level": _to_level(min(gov.get("rejectionCount", 0) * 0.12, 1.0)),
            "value": gov.get("rejectionCount", 0),
            "summary": f"{gov.get('rejectionCount', 0)} Emma rejections observed in memory.",
        },
        {
            "key": "review-spike",
            "level": "watch" if gov.get("reviewSpike") else "stable",
            "value": gov.get("reviewSpike", False),
            "summary": (
                "Governance review volume is elevated."
                if gov.get("reviewSpike") else
                "Governance review volume is stable."
            ),
        },
        {
            "key": "ledger-burst",
            "level": "warning" if gov.get("ledgerBurst") else "stable",
            "value": gov.get("ledgerBurst", False),
            "summary": (
                "DeltaVault write burst detected."
                if gov.get("ledgerBurst") else
                "DeltaVault write activity is stable."
            ),
        },
        {
            "key": "ledger-integrity",
            "level": "stable" if integrity.get("ok") else "warning",
            "value": integrity.get("ok", False),
            "summary": (
                f"DeltaVault integrity verified across {integrity.get('checked', 0)} entries."
                if integrity.get("ok") else
                f"DeltaVault integrity failure detected at {integrity.get('brokenAt')}."
            ),
        },
        {
            "key": "confidence",
            "level": (
                "stable" if confidence_res["trusted"]
                else "watch" if confidence_res["confidence"] >= 0.5
                else "warning"
            ),
            "value": confidence_res["confidence"],
            "summary": (
                f"Eagle Eye confidence is {confidence_res['confidence']} and trusted."
                if confidence_res["trusted"] else
                f"Eagle Eye confidence is {confidence_res['confidence']} and not trusted."
            ),
        },
        {
            "key": "contradictions",
            "level": (
                "stable" if contradictions["count"] == 0
                else "watch" if contradictions["count"] < 3
                else "warning"
            ),
            "value": contradictions["count"],
            "summary": (
                "No monitoring contradictions detected."
                if contradictions["count"] == 0 else
                f"{contradictions['count']} monitoring contradictions detected."
            ),
        },
    ]

    return {
        "timestamp": int(time.time() * 1000),
        "overall": _to_level(pressure_index),
        "pressureIndex": pressure_index,
        "confidence": confidence_res["confidence"],
        "trusted": confidence_res["trusted"],
        "contradictionCount": contradictions["count"],
        "validationIssues": validation["issues"],
        "contradictionIssues": contradictions["issues"],
        "metrics": metrics,
    }