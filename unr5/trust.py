"""
Trust + Reward State Derivation
Python ports of trust/deriveTrustState.ts + reward/deriveRewardState.ts
"""

import time


def _round2(v: float) -> float:
    return round(v, 2)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ─── Trust ────────────────────────────────────────────────────────────────────

def derive_trust_state(ledger_entries: list, emma_reviews: list) -> dict:
    """
    Trust score 0-100:
    - Each approved ledger entry: +6
    - Each Emma rejection: -12
    - Each high-risk approval: -3
    Base score: 50
    """
    approved_count       = len(ledger_entries)
    rejection_count      = sum(1 for r in emma_reviews if r.get("decision") == "rejected")
    high_risk_approved   = sum(
        1 for r in emma_reviews
        if r.get("decision") == "approved" and r.get("level") == "high"
    )

    score = _clamp(
        50 + (approved_count * 6) - (rejection_count * 12) - (high_risk_approved * 3),
        0, 100
    )

    if score >= 85:
        level = "strong"
    elif score >= 65:
        level = "stable"
    elif score >= 40:
        level = "guarded"
    else:
        level = "low"

    return {
        "timestamp": int(time.time() * 1000),
        "score": _round2(score),
        "level": level,
        "metrics": [
            {
                "key": "approved-actions",
                "value": approved_count,
                "summary": f"{approved_count} approved actions recorded in DeltaVault.",
            },
            {
                "key": "rejections",
                "value": rejection_count,
                "summary": f"{rejection_count} Emma rejections recorded in review memory.",
            },
            {
                "key": "high-risk-approvals",
                "value": high_risk_approved,
                "summary": f"{high_risk_approved} high-risk approvals observed.",
            },
        ],
    }


# ─── Reward ───────────────────────────────────────────────────────────────────

def derive_reward_state(ledger_entries: list, emma_reviews: list, trust: dict, eagle_eye: dict) -> dict:
    """
    Reward score 0-100:
    - Trust score * 0.45
    - Approved ledger entries * 4
    - Rejected reviews * -8
    - Medium/high approvals * -2
    - Eagle Eye confidence bonus * 10
    - Monitoring penalty if not trusted
    """
    approved_count      = len(ledger_entries)
    rejected_count      = sum(1 for r in emma_reviews if r.get("decision") == "rejected")
    medium_high_approvals = sum(
        1 for r in emma_reviews
        if r.get("decision") == "approved" and r.get("level") in ("medium", "high")
    )

    base_score = (
        trust.get("score", 50) * 0.45 +
        approved_count * 4 -
        rejected_count * 8 -
        medium_high_approvals * 2
    )

    ee_trusted     = eagle_eye.get("trusted", False)
    contradictions = eagle_eye.get("contradictionCount", 0)
    confidence     = eagle_eye.get("confidence", 0.5)

    monitoring_penalty   = 0.0 if ee_trusted else (15 + contradictions * 5)
    confidence_adjustment = confidence * 10

    score = _clamp(base_score + confidence_adjustment - monitoring_penalty, 0, 100)

    if score >= 85:
        level = "strong"
    elif score >= 65:
        level = "stable"
    elif score >= 40:
        level = "building"
    else:
        level = "low"

    eligible = ee_trusted and trust.get("score", 0) >= 50

    return {
        "timestamp": int(time.time() * 1000),
        "score": _round2(score),
        "level": level,
        "eligible": eligible,
        "metrics": [
            {
                "key": "approved-actions",
                "value": approved_count,
                "summary": f"{approved_count} approved actions contribute to reward state.",
            },
            {
                "key": "rejections",
                "value": rejected_count,
                "summary": f"{rejected_count} rejections reduce reward state.",
            },
            {
                "key": "monitoring-confidence",
                "value": _round2(confidence),
                "summary": f"Eagle Eye confidence is {_round2(confidence)}.",
            },
            {
                "key": "trust-score",
                "value": _round2(trust.get("score", 50)),
                "summary": f"Trust score is {_round2(trust.get('score', 50))}.",
            },
        ],
    }