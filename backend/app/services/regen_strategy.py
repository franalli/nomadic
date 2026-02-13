"""
Selective Regeneration Strategy Computation.

Determines the minimum regeneration strategy based on which trip input fields
changed between requests. This avoids expensive LLM calls when only minor
fields like preferences or travelers change.

Strategy Tiers (lowest to highest cost):
- BUILDER:     Only rebuild itinerary (preferences, origin changes) - ~100ms, no LLM
- LOGISTICS:   Re-fetch tiles + builder (travelers, budget changes) - ~500ms, API calls
- SPECIALISTS: Re-run specialists + logistics + builder (date changes) - ~3-8s, LLM
- FULL:        Complete graph re-execution (destination change) - ~10-15s, full LLM

@see docs/plan_graph_analysis.md - Selective Regeneration
"""

from enum import Enum
from typing import Any, Dict, Optional, Set

from app.debug_utils import _debug
from app.planner.services.state_serde import _field_hash


class RegenStrategy(str, Enum):
    """Regeneration strategy tiers, ordered by cost (ascending)."""

    BUILDER = "builder"  # ~100ms, no LLM - ItineraryBuilder only
    LOGISTICS = "logistics"  # ~500ms, API calls - LogisticsNode + Builder
    SPECIALISTS = "specialists"  # ~3-8s, LLM calls - Specialists + Logistics + Builder
    FULL = "full"  # ~10-15s, full graph - All nodes


# Field-to-strategy impact mapping
# Key insight: Most conservative strategy wins when multiple fields change
FIELD_IMPACT: Dict[str, RegenStrategy] = {
    # FULL - destination changes invalidate everything
    "destination": RegenStrategy.FULL,
    # SPECIALISTS - dates affect seasonal context and activity capacity
    # @see decision: "Bali diving March" vs "Bali diving November" (monsoon)
    "dates": RegenStrategy.SPECIALISTS,
    # SPECIALISTS - activity categories trigger specialist detection
    # @see intent_router._detect_specialists_from_activity_settings()
    "activity_categories": RegenStrategy.SPECIALISTS,
    # LOGISTICS - affects tile availability/pricing, not recommendations
    "travelers": RegenStrategy.LOGISTICS,
    "budget": RegenStrategy.LOGISTICS,
    "flight_settings": RegenStrategy.LOGISTICS,
    "hotel_settings": RegenStrategy.LOGISTICS,
    "activity_skill_level": RegenStrategy.LOGISTICS,
    # BUILDER - only affects itinerary structure, reuse cached tiles
    "origin": RegenStrategy.BUILDER,
}

# Strategy priority order (for computing most conservative)
STRATEGY_PRIORITY = [
    RegenStrategy.FULL,  # Highest priority (most conservative)
    RegenStrategy.SPECIALISTS,
    RegenStrategy.LOGISTICS,
    RegenStrategy.BUILDER,  # Lowest priority (cheapest)
]


def _stable_dict_hash(d: Optional[Dict[str, Any]]) -> str:
    """Compute stable hash for a dict with consistent key ordering."""
    if not d:
        return ""
    # Sort keys for stable ordering
    sorted_items = sorted((str(k), str(v)) for k, v in d.items())
    return "|".join(f"{k}:{v}" for k, v in sorted_items)


def compute_field_hashes(trip_inputs: Dict[str, Any]) -> Dict[str, str]:
    """
    Compute field hashes from trip_inputs dict for comparison.

    This is the frontend-facing version that works with raw trip_inputs.
    """
    # Extract nested settings
    activity_settings = trip_inputs.get("activity_settings") or {}
    if isinstance(activity_settings, dict):
        activity_categories = activity_settings.get("categories", [])
        activity_skill = activity_settings.get("skill_level", "")
    else:
        activity_categories = []
        activity_skill = ""

    return {
        "destination": _field_hash(trip_inputs.get("destination") or ""),
        "dates": _field_hash(
            f"{trip_inputs.get('start_date') or ''}|{trip_inputs.get('end_date') or ''}"
        ),
        "travelers": _field_hash(
            f"{trip_inputs.get('adults') or 1}|{trip_inputs.get('children') or 0}"
        ),
        "budget": _field_hash(str(trip_inputs.get("budget") or "")),
        "origin": _field_hash(trip_inputs.get("origin") or ""),
        # New fields for selective regeneration
        "flight_settings": _field_hash(_stable_dict_hash(trip_inputs.get("flight_settings"))),
        "hotel_settings": _field_hash(_stable_dict_hash(trip_inputs.get("hotel_settings"))),
        "activity_categories": _field_hash(
            "|".join(sorted(activity_categories)) if activity_categories else ""
        ),
        "activity_skill_level": _field_hash(activity_skill or ""),
    }


def detect_changed_fields(
    previous_hashes: Optional[Dict[str, str]],
    current_hashes: Dict[str, str],
) -> Set[str]:
    """
    Detect which fields changed by comparing hashes.

    Returns set of changed field names (e.g., {"dates", "travelers"}).
    """
    if not previous_hashes:
        # No previous state = everything changed, force FULL
        return set(FIELD_IMPACT.keys())

    changed = set()
    for field in FIELD_IMPACT.keys():
        prev = previous_hashes.get(field, "")
        curr = current_hashes.get(field, "")
        if prev != curr:
            changed.add(field)

    return changed


def compute_strategy(changed_fields: Set[str]) -> RegenStrategy:
    """
    Compute the minimum regeneration strategy for given changed fields.

    Most conservative strategy wins - if dates AND origin changed,
    we use SPECIALISTS (not BUILDER) because dates require LLM refresh.
    """
    if not changed_fields:
        # No changes detected = BUILDER only (preferences may have changed)
        return RegenStrategy.BUILDER

    # Find the highest priority (most conservative) strategy needed
    strategies_needed = [FIELD_IMPACT.get(field, RegenStrategy.FULL) for field in changed_fields]

    # Return the most conservative strategy
    for strategy in STRATEGY_PRIORITY:
        if strategy in strategies_needed:
            _debug(
                f"[regen_strategy] Strategy={strategy.value} for changed_fields={changed_fields}"
            )
            return strategy

    # Fallback to BUILDER if no recognized fields changed
    return RegenStrategy.BUILDER


def get_strategy_description(strategy: RegenStrategy) -> str:
    """Get human-readable description for logging/debugging."""
    descriptions = {
        RegenStrategy.BUILDER: "Rebuilding itinerary only (no LLM)",
        RegenStrategy.LOGISTICS: "Re-fetching tiles (API calls only)",
        RegenStrategy.SPECIALISTS: "Re-running specialists (LLM calls)",
        RegenStrategy.FULL: "Full graph re-execution",
    }
    return descriptions.get(strategy, "Unknown strategy")
