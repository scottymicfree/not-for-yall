"""
LUCY FORBIDDEN REGISTRY
========================
Immutable list of forbidden action tags.
Cannot be modified at runtime — hardcoded by design.
Mirrors the Sentinel protocol forbidden list.
"""

from typing import Union

# Tier-1 Forbidden — triggers Sentinel hard halt
TIER_1_FORBIDDEN = frozenset({
    "GEOENGINEERING_UNAUTH",
    "ENERGY_GRID_OVERRIDE",
    "TWIN_EARTH_WRITE",
    "GOVERNANCE_MODIFY",
    "SENTINEL_DISABLE",
    "AUDIT_TAMPER",
    "AGENT_SPAWN_UNAUTH",
    "CROSS_CLUSTER_WRITE",
    "PRIME_OVERRIDE",
    "EMMA_BYPASS",
})

# Tier-2 Forbidden — blocked + logged, no halt
TIER_2_FORBIDDEN = frozenset({
    "DELETE_ALL_MEMORY",
    "WIPE_LEDGER",
    "DISABLE_EAGLE_EYE",
    "FORCE_APPROVE",
    "SKIP_VALIDATION",
    "BROADCAST_UNAUTH",
    "CROSS_AGENT_IMPERSONATE",
})

ALL_FORBIDDEN = TIER_1_FORBIDDEN | TIER_2_FORBIDDEN


class ForbRegistry:
    """Checks actions against the immutable forbidden registry."""

    def is_forbidden(self, actions: Union[list, str]) -> bool:
        if isinstance(actions, str):
            actions = [actions]
        for action in actions:
            if str(action).upper() in ALL_FORBIDDEN:
                return True
        return False

    def get_tier(self, action: str) -> int:
        """Returns 0 (allowed), 1 (tier-1 halt), or 2 (tier-2 block)."""
        a = action.upper()
        if a in TIER_1_FORBIDDEN:
            return 1
        if a in TIER_2_FORBIDDEN:
            return 2
        return 0

    def list_forbidden(self) -> dict:
        return {
            "tier_1": sorted(TIER_1_FORBIDDEN),
            "tier_2": sorted(TIER_2_FORBIDDEN),
        }