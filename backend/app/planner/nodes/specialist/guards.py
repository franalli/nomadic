"""
Specialist Guards - Core field protection and optimization gates.

Contains:
- Core field guard: Blocks domain specialists if core fields missing
- Default adults gate: Sets adults=1 when core complete but adults missing
- No-op gate: Skips LLM for vague affirmations with no missing fields
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Set

if TYPE_CHECKING:
    from app.plan_graph import GraphState

# Domain specialists that require core fields
GUARDED_SPECIALISTS: Set[str] = {
    "flights",
    "hotels",
    "activities",
    "transport",
    "strategy",
}

# Specialists that can skip LLM on vague affirmations
NOOP_GATE_SPECIALISTS: Set[str] = {"flights", "hotels", "activities", "transport"}


def check_core_field_guard(
    name: str,
    state: "GraphState",
) -> Optional[List[str]]:
    """
    Check if specialist should be blocked due to missing core fields.

    Args:
        name: Specialist name
        state: Current graph state

    Returns:
        List of missing core fields if guard triggers, None otherwise
    """
    if name not in GUARDED_SPECIALISTS:
        return None

    from app.planner.gates.readiness import compute_trip_readiness

    readiness = compute_trip_readiness(state.trip_inputs)
    if readiness.core_complete:
        return None

    return readiness.missing_core


def check_default_adults_gate(
    name: str,
    state: "GraphState",
) -> bool:
    """
    Check if adults should be defaulted to 1.

    Returns True if adults was defaulted, False otherwise.
    """
    from app.config import settings

    if not settings.default_adults_enabled:
        return False

    if name not in GUARDED_SPECIALISTS:
        return False

    ti = state.trip_inputs
    has_destination = bool(ti.destinations)
    has_dates = bool(ti.start_date)
    has_adults = ti.adults is not None and ti.adults > 0

    if has_destination and has_dates and not has_adults:
        from app.debug_utils import _debug

        _debug(
            "DEFAULT_ADULTS: Setting adults=1 (solo traveler assumed)",
            destinations=ti.destinations,
            start_date=ti.start_date,
        )
        state.trip_inputs.adults = 1
        state.metadata["adults_defaulted"] = True
        state.metadata["adults_default_reason"] = "core_complete_without_explicit_count"
        return True

    return False


def check_noop_gate(
    name: str,
    state: "GraphState",
) -> bool:
    """
    Check if specialist can skip LLM due to vague affirmation.

    Returns True if LLM should be skipped, False otherwise.
    """
    if name not in NOOP_GATE_SPECIALISTS:
        return False

    from app.planner.gates.checks import is_vague_affirmation
    from app.planner.gates.readiness import compute_trip_readiness

    user_text = state.user_text or ""
    readiness = compute_trip_readiness(state.trip_inputs.model_dump(exclude_none=True))

    return is_vague_affirmation(user_text) and not readiness.missing_core


def apply_noop_gate_response(state: "GraphState", name: str) -> "GraphState":
    """
    Apply standard no-op gate response to state.

    Mutates state and returns it.
    """
    from app.debug_utils import _debug
    from app.plan_graph import _routing_stats

    _routing_stats["noop_gate_triggered"] += 1
    _debug(
        f"NO-OP GATE: {name} skipped (vague affirmation, no missing fields)",
        specialist=name,
        user_text=(state.user_text or "")[:30],
        tokens_saved="~800-1500 (specialist LLM call avoided)",
    )
    state.metadata["noop_gate_triggered"] = name
    state.last_summary = (
        "Great! Is there anything else you'd like to add or should I proceed with the plan?"
    )
    state.suggested_responses = [
        "Proceed with plan",
        "Add more details",
        "Change something",
    ]
    return state


def check_domain_keyword_for_default_adults(
    state: "GraphState",
) -> Optional[str]:
    """
    Check if user message contains domain keywords for default adults routing.

    Returns detected domain name if found, None otherwise.
    """
    user_text_lower = (state.user_text or "").lower()

    domain_keywords = {
        "activities": {
            "activity",
            "activities",
            "things to do",
            "attractions",
            "sightseeing",
            "tour",
            "museum",
            "restaurant",
        },
        "hotels": {
            "hotel",
            "hotels",
            "accommodation",
            "stay",
            "lodging",
            "hostel",
            "airbnb",
        },
        "flights": {"flight", "flights", "fly", "flying", "plane", "airline", "airport"},
        "transport": {
            "transport",
            "train",
            "bus",
            "taxi",
            "uber",
            "rental car",
            "car rental",
        },
    }

    for domain, keywords in domain_keywords.items():
        if any(kw in user_text_lower for kw in keywords):
            return domain

    return None
