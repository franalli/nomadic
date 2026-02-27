"""
Coordinator -- orchestrates specialist invocations based on change classification.

Phase 1: Trip state summary builder + primary zone extraction.
Phase 2: Full coordinator loop with ExecutionPlan dispatch.

The coordinator is PURE PYTHON for planning decisions (no LLM). It reads
the ClassifierOutput + trip state to produce a deterministic ExecutionPlan,
then executes each step, delegating to existing specialist/logistics/builder
functions.

SSE event contract is identical to plan_graph.py:
  - {"type": "token",       "data": str}
  - {"type": "node_status", "data": {...}}
  - {"type": "partial",     "data": {kind, payload}}
  - {"type": "complete",    "data": {...}}
  - {"type": "error",       "message": str}
"""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage

from app.config import settings
from app.planner.hashing import stable_hash, stable_hash_short
from app.planner.nodes.router_extraction import _clamp_date_str
from app.planner.schemas.coordinator_schemas import (
    ChangeType,
    ClassifierOutput,
    ExecutionPlan,
    ExecutionStep,
    ReplanRequest,
    SpecialistPlan,
    StepType,
    TripBrief,
)
from app.planner.specialist_registry import TIER1_SPECIALIST_NAMES, TIER2_CATEGORY_ALIASES

logger = logging.getLogger(__name__)

# Keys used for change-detection snapshots (snapshot creation + envelope comparison).
_CHANGE_DETECTION_KEYS = (
    "trip_plan",
    "trip_settings",
    "specialist_plans",
    "strategy_sections",
    "tiles",
    "day_cards",
    "persistent_meta",
)

# Human-readable labels for partial parallel failures surfaced in ack_updates.
_FAILURE_LABELS = {
    "search_tiles": "Flights & hotels temporarily unavailable",
    "dispatch_specialists": "Some specialist advice unavailable",
    "local_intel": "Local knowledge temporarily unavailable",
}


# =============================================================================
# Normalization helpers
# =============================================================================


def _norm_topic(topic: str) -> str:
    """Normalize specialist topic IDs to lowercase canonical form."""
    return (topic or "").strip().lower()


def _normalize_specialist_plan_keys(state: Dict[str, Any]) -> None:
    """Normalize `specialist_plans` keys in-place to canonical lowercase IDs."""
    specialist_plans = state.get("specialist_plans")
    if not isinstance(specialist_plans, dict):
        return
    normalized: Dict[str, Any] = {}
    for topic, plan in specialist_plans.items():
        key = _norm_topic(str(topic))
        if key:
            normalized[key] = plan
    state["specialist_plans"] = normalized


def _canonicalize_applied_updates(fields_changed: List[str]) -> List[str]:
    """Map granular change fields to canonical UI keys."""
    mapping = {
        "origin": "origin",
        "destination": "destination",
        "start_date": "dates",
        "end_date": "dates",
        "trip_duration": "dates",
        "duration_days": "dates",
        "date_window_start": "dates",
        "date_window_end": "dates",
        "date_flex": "dates",
        "adults": "travelers",
        "children": "travelers",
        "budget": "budget",
        "currency": "budget",
    }
    canonical: List[str] = []
    for field in fields_changed:
        key = mapping.get(field)
        if key and key not in canonical:
            canonical.append(key)
    return canonical


# =============================================================================
# Trip State Summary Builder
# =============================================================================


def build_trip_state_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    """Build a compact trip-state summary for the classifier prompt context.

    Reads from the NomadicAgentState dict shape (as stored in LangGraph
    checkpointer). The summary gives the classifier enough context to
    determine what changed and which specialists are affected.

    Args:
        state: NomadicAgentState as a plain dict (keys: trip_plan,
               trip_settings, tiles, strategy_sections, constraints,
               persistent_meta, turn_meta).

    Returns:
        Compact dict suitable for serializing into an LLM prompt.
    """
    trip_plan: Dict[str, Any] = state.get("trip_plan", {})
    trip_settings: Dict[str, Any] = state.get("trip_settings", {})
    strategy_sections: List[Dict[str, Any]] = state.get("strategy_sections", [])
    constraints: List[Dict[str, Any]] = state.get("constraints", [])
    tiles: Dict[str, Any] = state.get("tiles", {})

    # -- Core trip fields (always present, even if None) --
    summary: Dict[str, Any] = {
        "destination": None,
        "dates": {"start": None, "end": None},
        "categories": [],
        "specialist_plans": {},
        "has_itinerary": False,
    }

    destination = trip_plan.get("destination")
    if destination:
        summary["destination"] = destination

    origin = trip_plan.get("origin")
    if origin:
        summary["origin"] = origin

    start_date = trip_plan.get("start_date")
    end_date = trip_plan.get("end_date")
    summary["dates"] = {"start": start_date, "end": end_date}

    duration = trip_plan.get("trip_duration")
    if duration is None:
        duration = trip_plan.get("duration_days")
    if duration is not None:
        summary["trip_duration"] = duration
        summary["duration_days"] = duration

    adults = trip_plan.get("adults")
    children = trip_plan.get("children")
    if adults:
        summary["adults"] = adults
    if children:
        summary["children"] = children

    budget = trip_plan.get("budget")
    if budget:
        summary["budget"] = budget
        summary["currency"] = trip_plan.get("currency", "USD")

    # -- Activity categories (from trip_settings) --
    activity_settings = trip_settings.get("activity_settings", {})
    categories: List[str] = activity_settings.get("categories", [])
    summary["categories"] = categories

    day_preferences: Dict[str, int] = activity_settings.get("day_preferences", {})
    if day_preferences:
        summary["day_preferences"] = day_preferences

    # -- Specialist plans (compact summaries, not full plans) --
    specialist_plans: Dict[str, Any] = state.get("specialist_plans", {})
    plan_summaries: Dict[str, Any] = {}
    for topic, plan in specialist_plans.items():
        if plan:
            day_plans = plan.get("day_plans", [])
            plan_summaries[topic] = {
                "days_planned": len(day_plans),
                "zone": (day_plans[0].get("location") if day_plans else None),
                "feasibility": plan.get("feasibility_status", "feasible"),
            }
    summary["specialist_plans"] = plan_summaries

    # -- Has itinerary --
    day_cards: List[Any] = state.get("day_cards", [])
    summary["has_itinerary"] = bool(day_cards)

    # -- Executed specialists (from strategy sections) --
    executed_specialists: List[str] = []
    for section in strategy_sections:
        spec_type = section.get("specialist_type")
        if spec_type:
            executed_specialists.append(spec_type)
    if executed_specialists:
        summary["executed_specialists"] = executed_specialists

    # -- Active constraints --
    if constraints:
        constraint_summaries: List[str] = []
        for c in constraints:
            label = c.get("label") or c.get("rule", "unknown")
            severity = c.get("severity", "unknown")
            constraint_summaries.append(f"{label} ({severity})")
        summary["active_constraints"] = constraint_summaries

    # -- Tile inventory (just counts, not full data) --
    tile_counts: Dict[str, int] = {}
    for tile_type, tile_list in tiles.items():
        if isinstance(tile_list, list) and tile_list:
            tile_counts[tile_type] = len(tile_list)
    if tile_counts:
        summary["tile_counts"] = tile_counts

    # -- Hotel/flight preferences (from trip_settings) --
    hotel_settings = trip_settings.get("hotel_settings", {})
    if hotel_settings:
        prefs: Dict[str, Any] = {}
        min_stars = hotel_settings.get("min_stars")
        if min_stars:
            prefs["min_stars"] = min_stars
        style = hotel_settings.get("style")
        if style:
            prefs["style"] = style
        if prefs:
            summary["hotel_preferences"] = prefs

    flight_settings = trip_settings.get("flight_settings", {})
    if flight_settings:
        prefs = {}
        direct_only = flight_settings.get("direct_only")
        if direct_only is not None:
            prefs["direct_only"] = direct_only
        cabin_class = flight_settings.get("cabin_class")
        if cabin_class:
            prefs["cabin_class"] = cabin_class
        if prefs:
            summary["flight_preferences"] = prefs

    # -- Primary zone (geographic context) --
    primary_zone = _extract_primary_zone(trip_plan, strategy_sections)
    if primary_zone:
        summary["primary_zone"] = primary_zone

    return summary


def _extract_primary_zone(
    trip_plan: Dict[str, Any],
    strategy_sections: List[Dict[str, Any]],
) -> Optional[str]:
    """Extract the primary geographic zone from trip state.

    This is a lightweight heuristic -- not a geocoding call. It combines
    destination + any location hints from strategy sections to give the
    classifier a sense of geographic scope.

    Returns:
        A short zone string like "Bali, Indonesia" or "Swiss Alps", or None.
    """
    destination = trip_plan.get("destination")
    if not destination:
        return None

    # Check strategy sections for location refinements
    # (e.g., specialist may specify "Tulamben" for diving in Bali)
    location_hints: List[str] = []
    for section in strategy_sections:
        content_blocks = section.get("content_blocks", [])
        for block in content_blocks:
            location = block.get("location")
            if location and location.lower() != destination.lower():
                location_hints.append(location)

    if location_hints:
        unique_hints = sorted(set(location_hints))[:3]  # Cap at 3 sub-locations
        return f"{destination} ({', '.join(unique_hints)})"

    return destination


# =============================================================================
# Phase 2: Coordinator Module
# =============================================================================

# Keys from doc_settings that are allowed to merge into trip_settings.
_ALLOWED_DOC_SETTINGS_KEYS: frozenset[str] = frozenset(
    {
        "booking_types",
        "flight_settings",
        "hotel_settings",
        "activity_settings",
        "transport_settings",
    }
)

# Change types that invalidate ALL specialist plans.
_FULL_INVALIDATION_CHANGES: frozenset[ChangeType] = frozenset(
    {
        ChangeType.DESTINATION_CHANGE,
        ChangeType.INITIAL_PLAN,
        ChangeType.RESET,
    }
)

# Change types that require tile refresh.
_TILE_REFRESH_CHANGES: frozenset[ChangeType] = frozenset(
    {
        ChangeType.INITIAL_PLAN,
        ChangeType.DESTINATION_CHANGE,
        ChangeType.DATE_CHANGE,
        ChangeType.LOGISTICS,
        ChangeType.SETTINGS,
        ChangeType.ADD_ACTIVITY,
        ChangeType.REMOVE_ACTIVITY,
        ChangeType.SWAP_ACTIVITY,
    }
)


# ---------------------------------------------------------------------------
# SSE event helpers
# ---------------------------------------------------------------------------


def _node_status(
    node: str,
    status: str,
    label: str,
    icon: str = "circle",
    duration: int = 500,
    **extra: Any,
) -> Dict[str, Any]:
    """Build a node_status SSE event dict."""
    data: Dict[str, Any] = {
        "node": node,
        "status": status,
        "label": label,
        "icon_key": icon,
        "estimated_duration_ms": duration,
    }
    data.update(extra)
    return {"type": "node_status", "data": data}


def _trip_inputs_partial_payload(state: Dict[str, Any]) -> Dict[str, Any]:
    """Build ``trip_inputs`` payload for partial SSE updates."""
    trip_plan: Dict[str, Any] = state.get("trip_plan", {})
    trip_settings: Dict[str, Any] = state.get("trip_settings", {})

    payload: Dict[str, Any] = {}
    for field in (
        "destination",
        "origin",
        "origin_iata",
        "destination_iata",
        "start_date",
        "end_date",
        "adults",
        "children",
        "budget",
        "currency",
    ):
        val = trip_plan.get(field)
        if val is not None:
            payload[field] = val

    for settings_field in (
        "booking_types",
        "flight_settings",
        "hotel_settings",
        "activity_settings",
        "transport_settings",
    ):
        val = trip_settings.get(settings_field)
        if val:
            payload[settings_field] = val

    return payload


def _flatten_tiles_payload(tiles: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten category-keyed tiles into ID-keyed map for partial SSE updates."""
    flattened: Dict[str, Any] = {}
    if not isinstance(tiles, dict):
        return flattened

    for tile_list in tiles.values():
        if not isinstance(tile_list, list):
            continue
        for tile in tile_list:
            if isinstance(tile, dict):
                tile_id = tile.get("id")
                if tile_id:
                    flattened[str(tile_id)] = tile
    return flattened


def _short_circuit_message(intent: str) -> str:
    """Deterministic, no-LLM response for greeting/reset short-circuits."""
    if intent == "RESET":
        return "Reset complete. Tell me your destination and dates to start a new trip."
    if intent == "GREETING":
        return "Hi! Share your destination and dates and I can start planning."
    return ""


def _clear_planning_artifacts(state: Dict[str, Any]) -> None:
    """Clear derived planning artifacts while keeping core trip inputs/settings."""
    state["tiles"] = {}
    state["strategy_sections"] = []
    state["day_cards"] = []
    state["constraints"] = []
    state["specialist_plans"] = {}


# ---------------------------------------------------------------------------
# Turn planning (pure Python -- no LLM)
# ---------------------------------------------------------------------------


def plan_turn(
    classifier: ClassifierOutput,
    state: Dict[str, Any],
) -> ExecutionPlan:
    """Deterministic turn planner. Reads classifier output + state, returns
    an ordered list of execution steps.

    No LLM call. Pure Python decision logic.
    """
    intent = classifier.intent
    change_type = classifier.change_type

    # ----- Short circuits for non-planning intents -----
    if intent == "GREETING":
        return ExecutionPlan(
            steps=[
                ExecutionStep(step_type=StepType.SHORT_CIRCUIT, params={"reason": "greeting"}),
            ],
            reason="Greeting — short circuit",
            estimated_llm_calls=0,
            estimated_wall_ms=100,
        )

    if intent == "RESET":
        return ExecutionPlan(
            steps=[
                ExecutionStep(step_type=StepType.SHORT_CIRCUIT, params={"reason": "reset"}),
            ],
            reason="Reset — short circuit",
            estimated_llm_calls=0,
            estimated_wall_ms=100,
        )

    if intent == "QUESTION":
        return ExecutionPlan(
            steps=[
                ExecutionStep(step_type=StepType.SHORT_CIRCUIT, params={"reason": "question"}),
                ExecutionStep(step_type=StepType.GENERATE_RESPONSE),
            ],
            reason="Question — answer without plan changes",
            estimated_llm_calls=1,
            estimated_wall_ms=800,
        )

    # ----- PLANNING intent -----
    steps: List[ExecutionStep] = []
    estimated_llm_calls = 0
    estimated_wall_ms = 0

    trip_plan: Dict[str, Any] = state.get("trip_plan", {})
    has_destination = bool(trip_plan.get("destination") or classifier.destination)
    has_dates = bool(
        (trip_plan.get("start_date") or classifier.start_date)
        and (trip_plan.get("end_date") or classifier.end_date)
    )

    # Specialist dispatch
    dispatch_list = _compute_dispatch_list(classifier, state)
    preserve_list = _compute_preserve_list(classifier, state)
    if dispatch_list and has_destination:
        steps.append(
            ExecutionStep(
                step_type=StepType.DISPATCH_SPECIALISTS,
                params={
                    "topics": dispatch_list,
                    "preserves": preserve_list,
                    "is_replan": change_type not in _FULL_INVALIDATION_CHANGES,
                },
            )
        )
        estimated_llm_calls += len(dispatch_list)
        estimated_wall_ms += 4000  # Parallel, so one specialist's time

    # Local intel (for initial plans, destination changes, or Tier 1 activity changes)
    _activity_change_types = {ChangeType.ADD_ACTIVITY, ChangeType.REMOVE_ACTIVITY}
    _affects_tier1 = bool(
        (
            classifier.affects
            and any(_norm_topic(t) in TIER1_SPECIALIST_NAMES for t in classifier.affects)
        )
        or any(_norm_topic(h) in TIER1_SPECIALIST_NAMES for h in classifier.specialist_hints)
    )
    needs_local_intel = change_type in (
        ChangeType.INITIAL_PLAN,
        ChangeType.DESTINATION_CHANGE,
        ChangeType.DATE_CHANGE,
    ) or (change_type in _activity_change_types and _affects_tier1)
    if needs_local_intel and has_destination:
        steps.append(
            ExecutionStep(
                step_type=StepType.LOCAL_INTEL,
            )
        )
        estimated_wall_ms += 100  # Phase A is instant; Phase B is background

    # Tile search
    if _needs_tile_refresh(classifier) and has_destination and has_dates:
        tile_types = _tile_refresh_types(classifier)
        # No activity tiles yet + user has categories → force-include activities
        # so the first "dates added" turn doesn't skip the activity pipeline.
        if "activities" not in tile_types:
            existing_tiles = state.get("tiles", {})
            if not existing_tiles.get("activities"):
                act_settings = state.get("trip_settings", {}).get("activity_settings", {})
                if isinstance(act_settings, dict) and act_settings.get("categories"):
                    tile_types = [*tile_types, "activities"]
        # Tiles can run in parallel with specialists when both are needed
        parallel_with = StepType.DISPATCH_SPECIALISTS if dispatch_list else None
        steps.append(
            ExecutionStep(
                step_type=StepType.SEARCH_TILES,
                params={"tile_types": tile_types},
                parallel_with=parallel_with,
            )
        )
        estimated_wall_ms += 2000

    # Itinerary build (after specialists + tiles)
    if has_destination and has_dates:
        steps.append(ExecutionStep(step_type=StepType.BUILD_ITINERARY))
        estimated_wall_ms += 200

    # Always end with response generation
    steps.append(ExecutionStep(step_type=StepType.GENERATE_RESPONSE))
    estimated_llm_calls += 1
    estimated_wall_ms += 800

    reason_parts: List[str] = []
    if dispatch_list:
        reason_parts.append(f"dispatch {dispatch_list}")
    if _needs_tile_refresh(classifier):
        reason_parts.append("refresh tiles")
    reason_parts.append("generate response")

    return ExecutionPlan(
        steps=steps,
        reason=f"PLANNING ({change_type.value}): {', '.join(reason_parts)}",
        estimated_llm_calls=estimated_llm_calls,
        estimated_wall_ms=estimated_wall_ms,
    )


# ---------------------------------------------------------------------------
# Dispatch / Preserve helpers
# ---------------------------------------------------------------------------


def _compute_dispatch_list(
    classifier: ClassifierOutput,
    state: Dict[str, Any],
) -> List[str]:
    """Determine which specialists need (re-)dispatch.

    For initial plans or destination changes, dispatch all active categories
    that are Tier 1. For targeted changes, only dispatch affected topics.
    """
    trip_settings: Dict[str, Any] = state.get("trip_settings", {})
    activity_settings = trip_settings.get("activity_settings", {})
    categories: List[str] = activity_settings.get("categories", [])
    removed_topics = {_norm_topic(t) for t in classifier.removal_targets if _norm_topic(t)}

    # Merge categories from classifier (may have new ones from user message)
    all_categories = [_norm_topic(c) for c in categories if _norm_topic(c)]
    for cat in classifier.activity_categories:
        cat_norm = _norm_topic(cat)
        if cat_norm and cat_norm not in all_categories:
            all_categories.append(cat_norm)
    for hint in classifier.specialist_hints:
        hint_norm = _norm_topic(hint)
        if hint_norm and hint_norm not in all_categories:
            all_categories.append(hint_norm)
    if removed_topics:
        all_categories = [c for c in all_categories if _norm_topic(c) not in removed_topics]

    # Filter to Tier 1 specialists only (Tier 2 are handled via tiles)
    tier1_active = sorted({c for c in all_categories if c in TIER1_SPECIALIST_NAMES})

    if classifier.change_type in _FULL_INVALIDATION_CHANGES:
        # Fresh start — dispatch all active Tier 1 specialists
        return tier1_active

    # Targeted change — only dispatch affected specialists
    if classifier.affects:
        # Classifier told us exactly which to re-dispatch
        affected_tier1 = sorted(
            {
                _norm_topic(t)
                for t in classifier.affects
                if _norm_topic(t) in TIER1_SPECIALIST_NAMES and _norm_topic(t) not in removed_topics
            }
        )
        if affected_tier1:
            return affected_tier1
        # classifier.affects contained only Tier 2 topics — fall through to
        # the activity-change fallback so new Tier 1 categories still dispatch.
        logger.debug(
            "[coordinator] affects=%s had no Tier 1 — falling through to activity fallback",
            classifier.affects,
        )

    # Fallback: if change_type targets activity changes, dispatch relevant ones
    if classifier.change_type in (
        ChangeType.DAY_COUNT,
        ChangeType.SWAP_ACTIVITY,
        ChangeType.ADD_ACTIVITY,
        ChangeType.REMOVE_ACTIVITY,
    ):
        return tier1_active

    # Date changes affect all existing specialists
    if classifier.change_type == ChangeType.DATE_CHANGE:
        existing_plans: Dict[str, Any] = state.get("specialist_plans", {})
        return sorted(
            {_norm_topic(t) for t in existing_plans if _norm_topic(t) in TIER1_SPECIALIST_NAMES}
        )

    return []


def _compute_preserve_list(
    classifier: ClassifierOutput,
    state: Dict[str, Any],
) -> List[str]:
    """Determine which specialist plans to keep unchanged."""
    existing_plans: Dict[str, Any] = state.get("specialist_plans", {})
    removed_topics = {_norm_topic(t) for t in classifier.removal_targets if _norm_topic(t)}
    if classifier.preserves:
        preserve_set = {_norm_topic(t) for t in classifier.preserves if _norm_topic(t)}
        return [
            t
            for t in existing_plans
            if _norm_topic(t) in preserve_set and _norm_topic(t) not in removed_topics
        ]
    dispatch = {_norm_topic(t) for t in _compute_dispatch_list(classifier, state)}
    return [
        t
        for t in existing_plans
        if _norm_topic(t) not in dispatch and _norm_topic(t) not in removed_topics
    ]


def _needs_tile_refresh(classifier: ClassifierOutput) -> bool:
    """Does this change require tile re-fetch?"""
    return classifier.change_type in _TILE_REFRESH_CHANGES


def _tile_refresh_types(classifier: ClassifierOutput) -> List[str]:
    """Which tile types to refresh."""
    ct = classifier.change_type
    if ct in (ChangeType.INITIAL_PLAN, ChangeType.DESTINATION_CHANGE):
        return ["flights", "hotels", "activities"]
    if ct == ChangeType.LOGISTICS:
        return ["flights"]
    if ct == ChangeType.SETTINGS:
        # Hotel/flight settings changes
        types: List[str] = []
        if classifier.hotel_min_stars is not None or classifier.hotel_style:
            types.append("hotels")
        if classifier.flight_direct_only is not None or classifier.flight_cabin_class:
            types.append("flights")
        return types or ["flights", "hotels"]
    if ct == ChangeType.DATE_CHANGE:
        return ["flights", "hotels"]
    if ct in (
        ChangeType.ADD_ACTIVITY,
        ChangeType.REMOVE_ACTIVITY,
        ChangeType.SWAP_ACTIVITY,
    ):
        return ["activities"]
    return []


# ---------------------------------------------------------------------------
# Brief builders
# ---------------------------------------------------------------------------


def build_brief(
    topic: str,
    state: Dict[str, Any],
    classifier: ClassifierOutput,
    other_plans: Dict[str, Any],
) -> TripBrief:
    """Assemble a TripBrief for a specialist from current state.

    The specialist never sees raw user text. It sees this structured brief.
    The coordinator builds it from trip_plan + trip_settings + other plans.
    """
    trip_plan: Dict[str, Any] = state.get("trip_plan", {})
    trip_settings: Dict[str, Any] = state.get("trip_settings", {})
    activity_settings = trip_settings.get("activity_settings", {})
    day_preferences: Dict[str, int] = activity_settings.get("day_preferences", {})

    # Use classifier destination if trip_plan doesn't have one yet
    destination = trip_plan.get("destination") or classifier.destination or ""
    start_date = trip_plan.get("start_date") or classifier.start_date or ""
    end_date = trip_plan.get("end_date") or classifier.end_date or ""

    # Compute num_days
    num_days = _compute_num_days(start_date, end_date)

    # Reserved days from other specialists' day_plans
    reserved_days: List[int] = []
    for other_topic, plan_dict in other_plans.items():
        if other_topic == topic:
            continue
        if isinstance(plan_dict, dict):
            for dp in plan_dict.get("day_plans", []):
                day_num = dp.get("day_number")
                if day_num is not None and day_num not in reserved_days:
                    reserved_days.append(day_num)

    # Other specialist zones for spatial context
    other_zones: Dict[str, str] = {}
    for other_topic, plan_dict in other_plans.items():
        if other_topic == topic or not isinstance(plan_dict, dict):
            continue
        day_plans = plan_dict.get("day_plans", [])
        if day_plans:
            zone = day_plans[0].get("location")
            if zone:
                other_zones[other_topic] = zone

    # Budget allocation uses configured activity share,
    # then splits equally among active specialists.
    budget_total = trip_plan.get("budget")
    activities_share = settings.budget_allocation_activities
    active_count = max(1, len(other_plans) + 1)  # +1 for this specialist
    budget_pct = activities_share / active_count

    return TripBrief(
        destination=destination,
        start_date=start_date,
        end_date=end_date,
        num_days=num_days,
        adults=trip_plan.get("adults", 1),
        children=trip_plan.get("children", 0),
        skill_level=classifier.skill_level or activity_settings.get("skill_level"),
        budget_total=budget_total,
        budget_allocation_pct=round(budget_pct, 2),
        reserved_days=sorted(reserved_days),
        target_day_count=day_preferences.get(topic),
        hotel_zone=trip_settings.get("hotel_settings", {}).get("location"),
        other_specialist_zones=other_zones,
        trip_vibe=trip_plan.get("vibe"),
    )


def build_replan_request(
    topic: str,
    state: Dict[str, Any],
    classifier: ClassifierOutput,
    other_plans: Dict[str, Any],
    pre_change_state: Optional[Dict[str, Any]] = None,
) -> ReplanRequest:
    """Build a ReplanRequest for iteration on an existing specialist plan.

    Used when the user modifies an existing plan (e.g., '3 dive days not 4')
    rather than starting fresh.

    Args:
        pre_change_state: State snapshot from before _apply_classifier_to_state.
            If provided, used to build original_brief reflecting pre-change
            state. If None, both briefs reflect post-change state (Phase 2
            limitation).
    """
    existing_plans: Dict[str, Any] = state.get("specialist_plans", {})
    original_plan_dict = existing_plans.get(topic, {})

    # Build briefs — original from pre-change state, updated from current
    original_state = pre_change_state if pre_change_state else state
    original_brief = build_brief(topic, original_state, classifier, other_plans)
    updated_brief = build_brief(topic, state, classifier, other_plans)

    # Convert original plan dict to SpecialistPlan for the request
    original_plan = SpecialistPlan(
        topic=topic,
        feasibility_status=original_plan_dict.get("feasibility_status", "feasible"),
        day_plans=[],  # Simplified — full day plan conversion in Phase 3
        editorial=original_plan_dict.get("editorial", ""),
        confidence=original_plan_dict.get("confidence", 0.8),
    )

    # Cross-specialist context
    cross_context: Dict[str, Any] = {}
    for other_topic, plan_dict in other_plans.items():
        if other_topic != topic and isinstance(plan_dict, dict):
            cross_context[other_topic] = {
                "day_count": len(plan_dict.get("day_plans", [])),
                "zone": _extract_plan_zone(plan_dict),
            }

    # Build change trigger description
    trigger_parts: List[str] = []
    if classifier.fields_changed:
        trigger_parts.append(f"fields changed: {classifier.fields_changed}")
    if classifier.activity_day_preferences:
        trigger_parts.append(f"day preferences: {classifier.activity_day_preferences}")
    change_trigger = "; ".join(trigger_parts) or f"change_type={classifier.change_type.value}"

    return ReplanRequest(
        original_brief=original_brief,
        original_plan=original_plan,
        change_trigger=change_trigger,
        change_type=classifier.change_type,
        updated_brief=updated_brief,
        cross_specialist_context=cross_context,
        preserve=classifier.preserves,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_num_days(start_date: str, end_date: str) -> int:
    """Compute trip duration in days from date strings."""
    if not start_date or not end_date:
        return 5  # Default
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        return max(1, (end - start).days + 1)
    except (ValueError, TypeError):
        return 5


def _extract_plan_zone(plan_dict: Dict[str, Any]) -> Optional[str]:
    """Extract primary zone from a specialist plan dict."""
    day_plans = plan_dict.get("day_plans", [])
    if day_plans and isinstance(day_plans[0], dict):
        return day_plans[0].get("location")
    return None


# ---------------------------------------------------------------------------
# State mutation helpers
# ---------------------------------------------------------------------------


def _merge_doc_settings(
    state: Dict[str, Any],
    doc_settings: Optional[Dict[str, Any]],
) -> None:
    """Merge document settings into state trip_settings. Mutates state in place.

    Mirrors the doc_settings merge logic from plan_graph.run_turn_streaming.
    """
    if not doc_settings:
        return

    trip_settings = dict(state.get("trip_settings", {}))
    previous_settings = dict(trip_settings)
    old_as = trip_settings.get("activity_settings", {})
    old_cats = set(old_as.get("categories", []) if isinstance(old_as, dict) else [])

    for field, value in doc_settings.items():
        if value is not None and field in _ALLOWED_DOC_SETTINGS_KEYS:
            trip_settings[field] = value
    state["trip_settings"] = trip_settings

    # Track settings deltas so persistence can correctly apply explicit clears.
    turn_meta = dict(state.get("turn_meta", {}))
    fields_changed = list(turn_meta.get("fields_changed", []))
    turn_steps = list(turn_meta.get("turn_steps", []))
    for field in _ALLOWED_DOC_SETTINGS_KEYS:
        old_val = previous_settings.get(field)
        new_val = trip_settings.get(field)
        if old_val == new_val:
            continue
        if field == "activity_settings":
            old_categories = old_val.get("categories", []) if isinstance(old_val, dict) else []
            new_categories = new_val.get("categories", []) if isinstance(new_val, dict) else []
            if old_categories != new_categories and "activity_categories" not in fields_changed:
                fields_changed.append("activity_categories")
                turn_steps.append(
                    {
                        "type": "activity_categories",
                        "summary": f"activity_categories: {old_categories} -> {new_categories}",
                    }
                )
        elif field not in fields_changed:
            fields_changed.append(field)
            turn_steps.append({"type": field, "summary": f"{field} updated from doc settings"})
    if fields_changed or turn_steps:
        turn_meta["fields_changed"] = fields_changed
        turn_meta["turn_steps"] = turn_steps
        state["turn_meta"] = turn_meta

    # Clear stale data when categories change
    new_as = trip_settings.get("activity_settings", {})
    new_cats = set(new_as.get("categories", []) if isinstance(new_as, dict) else [])
    if old_cats != new_cats and (old_cats or new_cats):
        state["day_cards"] = []
        tiles = state.get("tiles", {})
        if isinstance(tiles, dict):
            tiles["activities"] = []
            state["tiles"] = tiles
        turn_meta = state.get("turn_meta", {})
        if isinstance(turn_meta, dict):
            turn_meta["tiles_replaced"] = True
            state["turn_meta"] = turn_meta
        logger.info(
            "[coordinator] Categories changed %s -> %s — cleared day_cards + activity tiles",
            sorted(old_cats),
            sorted(new_cats),
        )


def _apply_classifier_to_state(
    state: Dict[str, Any],
    classifier: ClassifierOutput,
) -> None:
    """Apply extracted fields from classifier to state. Mutates state in place.

    Only writes non-None fields from the classifier into trip_plan and
    trip_settings, preserving existing values for fields the classifier
    did not extract.
    """
    trip_plan = dict(state.get("trip_plan", {}))
    trip_settings = dict(state.get("trip_settings", {}))
    old_origin = trip_plan.get("origin")

    # Core trip fields
    _FIELD_MAP: List[tuple[str, str]] = [
        ("destination", "destination"),
        ("origin", "origin"),
        ("origin_iata", "origin_iata"),
        ("destination_iata", "destination_iata"),
        ("start_date", "start_date"),
        ("end_date", "end_date"),
        ("adults", "adults"),
        ("children", "children"),
        ("budget", "budget"),
    ]

    fields_changed: List[str] = []
    turn_steps: List[Dict[str, Any]] = []

    for classifier_field, state_field in _FIELD_MAP:
        value = getattr(classifier, classifier_field, None)
        if value is not None:
            if state_field in {"start_date", "end_date"} and isinstance(value, str):
                clamped = _clamp_date_str(value)
                if clamped is None:
                    continue
                value = clamped
            old_val = trip_plan.get(state_field)
            if old_val != value:
                trip_plan[state_field] = value
                fields_changed.append(state_field)
                turn_steps.append(
                    {
                        "type": state_field,
                        "summary": f"{state_field}: {old_val} -> {value}",
                    }
                )

    # Duration days
    if classifier.duration_days is not None:
        old_duration = trip_plan.get("trip_duration", trip_plan.get("duration_days"))
        trip_plan["trip_duration"] = classifier.duration_days
        trip_plan.pop("duration_days", None)
        if old_duration != classifier.duration_days:
            fields_changed.append("trip_duration")
            turn_steps.append(
                {
                    "type": "trip_duration",
                    "summary": f"trip_duration: {old_duration} -> {classifier.duration_days}",
                }
            )
        if not classifier.end_date:
            start_date_to_use = trip_plan.get("start_date")
            if isinstance(start_date_to_use, str) and start_date_to_use:
                try:
                    from datetime import timedelta

                    start_dt = datetime.strptime(start_date_to_use, "%Y-%m-%d")
                    end_dt = start_dt + timedelta(days=classifier.duration_days - 1)
                    derived_end = end_dt.strftime("%Y-%m-%d")
                    old_end = trip_plan.get("end_date")
                    if old_end != derived_end:
                        trip_plan["end_date"] = derived_end
                        if "end_date" not in fields_changed:
                            fields_changed.append("end_date")
                        turn_steps.append(
                            {
                                "type": "end_date",
                                "summary": f"end_date: {old_end} -> {derived_end}",
                            }
                        )
                except ValueError:
                    pass

    # Budget reset
    if classifier.reset_budget:
        had_budget = "budget" in trip_plan
        trip_plan.pop("budget", None)
        if had_budget:
            fields_changed.append("budget")
            turn_steps.append({"type": "budget", "summary": "Budget cleared"})

    state["trip_plan"] = trip_plan

    # Activity categories from classifier
    activity_settings = dict(trip_settings.get("activity_settings", {}))
    existing_cats: List[str] = list(activity_settings.get("categories", []))
    new_cats = list(existing_cats)

    # Add specialist hints as categories
    for hint in classifier.specialist_hints:
        if hint and hint.lower() not in [c.lower() for c in new_cats]:
            new_cats.append(hint.lower())

    # Add activity categories
    for cat in classifier.activity_categories:
        normalized = (
            TIER2_CATEGORY_ALIASES.get(
                cat.lower().strip().replace("_", " "),
                cat.lower().strip().replace("_", " "),
            )
            if cat
            else ""
        )
        if normalized and normalized.lower() not in [c.lower() for c in new_cats]:
            new_cats.append(normalized.lower())

    # Handle removal targets
    for target in classifier.removal_targets:
        new_cats = [c for c in new_cats if c.lower() != target.lower()]

    if new_cats != existing_cats:
        activity_settings["categories"] = new_cats
        fields_changed.append("activity_categories")
        turn_steps.append(
            {
                "type": "activity_categories",
                "summary": f"activity_categories: {existing_cats} -> {new_cats}",
            }
        )

    # Day preferences
    if classifier.activity_day_preferences:
        try:
            import json

            day_prefs = json.loads(classifier.activity_day_preferences)
            if isinstance(day_prefs, dict):
                existing_prefs = dict(activity_settings.get("day_preferences", {}))
                if not day_prefs:
                    if existing_prefs:
                        activity_settings["day_preferences"] = {}
                        fields_changed.append("day_preferences")
                        turn_steps.append(
                            {
                                "type": "day_preferences",
                                "summary": "day_preferences cleared",
                            }
                        )
                else:
                    mentioned = {
                        TIER2_CATEGORY_ALIASES.get(
                            str(c).lower().strip().replace("_", " "),
                            str(c).lower().strip().replace("_", " "),
                        )
                        for c in (
                            list(classifier.activity_categories) + list(classifier.specialist_hints)
                        )
                        if str(c).strip()
                    }
                    normalized_day_prefs = {
                        str(k).lower().strip(): v for k, v in day_prefs.items() if str(k).strip()
                    }
                    if mentioned:
                        normalized_day_prefs = {
                            k: v for k, v in normalized_day_prefs.items() if k in mentioned
                        }
                    merged_prefs = dict(existing_prefs)
                    merged_prefs.update(normalized_day_prefs)
                    if merged_prefs != existing_prefs:
                        activity_settings["day_preferences"] = merged_prefs
                        fields_changed.append("day_preferences")
                        turn_steps.append(
                            {
                                "type": "day_preferences",
                                "summary": f"day_preferences updated: {normalized_day_prefs}",
                            }
                        )
            elif day_prefs is None:
                existing_prefs = dict(activity_settings.get("day_preferences", {}))
                if existing_prefs:
                    activity_settings["day_preferences"] = {}
                    fields_changed.append("day_preferences")
                    turn_steps.append(
                        {
                            "type": "day_preferences",
                            "summary": "day_preferences cleared",
                        }
                    )
        except (json.JSONDecodeError, TypeError):
            logger.debug(
                "[coordinator] Could not parse activity_day_preferences: %s",
                classifier.activity_day_preferences,
            )

    # Activities per day (density preference)
    if classifier.activities_per_day is not None:
        clamped = max(1, min(classifier.activities_per_day, 5))
        old_apd = activity_settings.get("activities_per_day")
        if old_apd != clamped:
            activity_settings["activities_per_day"] = clamped
            fields_changed.append("activities_per_day")
            turn_steps.append(
                {
                    "type": "activities_per_day",
                    "summary": f"activities_per_day set to {clamped}",
                }
            )

    # Skill level
    if classifier.skill_level:
        old_skill_level = activity_settings.get("skill_level")
        activity_settings["skill_level"] = classifier.skill_level
        if old_skill_level != classifier.skill_level:
            fields_changed.append("skill_level")
            turn_steps.append(
                {
                    "type": "skill_level",
                    "summary": f"skill_level: {old_skill_level} -> {classifier.skill_level}",
                }
            )

    trip_settings["activity_settings"] = activity_settings

    # Hotel settings
    hotel_settings = dict(trip_settings.get("hotel_settings", {}))
    if classifier.reset_hotel:
        had_hotel_settings = bool(hotel_settings)
        hotel_settings = {}
        if had_hotel_settings:
            fields_changed.append("hotel_settings")
            turn_steps.append({"type": "hotel_settings", "summary": "hotel_settings cleared"})
    else:
        if classifier.hotel_min_stars is not None:
            old_val = hotel_settings.get("min_stars")
            hotel_settings["min_stars"] = classifier.hotel_min_stars
            if old_val != classifier.hotel_min_stars:
                fields_changed.append("hotel_min_stars")
                turn_steps.append(
                    {
                        "type": "hotel_min_stars",
                        "summary": f"hotel_min_stars: {old_val} -> {classifier.hotel_min_stars}",
                    }
                )
        if classifier.hotel_style:
            old_val = hotel_settings.get("style")
            hotel_settings["style"] = classifier.hotel_style
            if old_val != classifier.hotel_style:
                fields_changed.append("hotel_style")
                turn_steps.append(
                    {
                        "type": "hotel_style",
                        "summary": f"hotel_style: {old_val} -> {classifier.hotel_style}",
                    }
                )
        if classifier.hotel_amenities:
            old_val = hotel_settings.get("amenities")
            hotel_settings["amenities"] = classifier.hotel_amenities
            if old_val != classifier.hotel_amenities:
                fields_changed.append("hotel_amenities")
                turn_steps.append(
                    {
                        "type": "hotel_amenities",
                        "summary": f"hotel_amenities updated: {classifier.hotel_amenities}",
                    }
                )
        if classifier.hotel_location:
            old_val = hotel_settings.get("location")
            hotel_settings["location"] = classifier.hotel_location
            if old_val != classifier.hotel_location:
                fields_changed.append("hotel_location")
                turn_steps.append(
                    {
                        "type": "hotel_location",
                        "summary": f"hotel_location: {old_val} -> {classifier.hotel_location}",
                    }
                )
    trip_settings["hotel_settings"] = hotel_settings

    # Flight settings
    flight_settings = dict(trip_settings.get("flight_settings", {}))
    if classifier.flight_direct_only is not None:
        old_val = flight_settings.get("direct_only")
        flight_settings["direct_only"] = classifier.flight_direct_only
        if old_val != classifier.flight_direct_only:
            fields_changed.append("flight_direct_only")
            turn_steps.append(
                {
                    "type": "flight_direct_only",
                    "summary": f"flight_direct_only: {old_val} -> {classifier.flight_direct_only}",
                }
            )
    if classifier.flight_cabin_class:
        old_val = flight_settings.get("cabin_class")
        flight_settings["cabin_class"] = classifier.flight_cabin_class
        if old_val != classifier.flight_cabin_class:
            fields_changed.append("flight_cabin_class")
            turn_steps.append(
                {
                    "type": "flight_cabin_class",
                    "summary": f"flight_cabin_class: {old_val} -> {classifier.flight_cabin_class}",
                }
            )
    trip_settings["flight_settings"] = flight_settings

    # Auto-enable flight search when origin is newly captured.
    booking_types = dict(trip_settings.get("booking_types", {}))
    has_origin_now = bool(trip_plan.get("origin"))
    if has_origin_now and not old_origin:
        current_flights_mode = booking_types.get("flights")
        if current_flights_mode in (None, "off", ""):
            booking_types["flights"] = "suggested"
            fields_changed.append("booking_types.flights")
            turn_steps.append(
                {
                    "type": "booking_types.flights",
                    "summary": "booking_types.flights: off -> suggested",
                }
            )
    trip_settings["booking_types"] = booking_types

    state["trip_settings"] = trip_settings

    # Record changes in turn_meta
    turn_meta = dict(state.get("turn_meta", {}))
    existing_fields = list(turn_meta.get("fields_changed", []))
    merged_fields = list(existing_fields)
    for field in fields_changed:
        if field not in merged_fields:
            merged_fields.append(field)
    existing_turn_steps = list(turn_meta.get("turn_steps", []))
    turn_meta["fields_changed"] = merged_fields
    turn_meta["turn_steps"] = existing_turn_steps + turn_steps
    state["turn_meta"] = turn_meta


# ---------------------------------------------------------------------------
# Specialist dispatch
# ---------------------------------------------------------------------------


async def _dispatch_specialists_parallel(
    topics: List[str],
    state: Dict[str, Any],
    classifier: ClassifierOutput,
    other_plans: Dict[str, Any],
    is_replan: bool = False,
    preserves: Optional[List[str]] = None,
) -> Dict[str, Optional[Dict[str, Any]]]:
    """Dispatch multiple specialists in parallel.

    Delegates to ``dispatch_specialist_with_brief()`` so coordinator brief +
    replan pathways match graph specialist behavior.

    Returns dict of topic -> LLMSpecialistOutput dict (or None on failure).
    """
    from app.db import _get_async_session_factory
    from app.planner.nodes.vertical_specialist import dispatch_specialist_with_brief

    if not topics:
        return {}

    existing_plans: Dict[str, Any] = state.get("specialist_plans", {})
    # NOTE: build_brief() reads only trip_plan + trip_settings from state.
    # If it gains new state key reads, update _pre_change_briefs snapshot in execute_turn().
    pre_change_briefs = state.get("_pre_change_briefs")
    pre_change_state = (
        {
            "trip_plan": pre_change_briefs.get("trip_plan", {}),
            "trip_settings": pre_change_briefs.get("trip_settings", {}),
        }
        if isinstance(pre_change_briefs, dict)
        else None
    )
    classifier_for_dispatch = (
        classifier.model_copy(update={"preserves": preserves or []})
        if preserves is not None
        else classifier
    )
    async_session_factory = _get_async_session_factory()

    logger.info(
        "[coordinator] Dispatching specialists: %s (replan=%s preserves=%s)",
        topics,
        is_replan,
        preserves or [],
    )

    output: Dict[str, Optional[Dict[str, Any]]] = {}

    async def _dispatch_one(topic: str) -> tuple[str, Optional[Dict[str, Any]]]:
        topic_other_plans = {
            k: v for k, v in other_plans.items() if isinstance(v, dict) and k != topic
        }
        brief = build_brief(topic, state, classifier_for_dispatch, topic_other_plans)

        replan_request: Optional[ReplanRequest] = None
        if is_replan and isinstance(existing_plans.get(topic), dict) and existing_plans.get(topic):
            replan_request = build_replan_request(
                topic=topic,
                state=state,
                classifier=classifier_for_dispatch,
                other_plans=topic_other_plans,
                pre_change_state=pre_change_state if isinstance(pre_change_state, dict) else None,
            )

        async with async_session_factory() as db:
            result = await dispatch_specialist_with_brief(
                brief=brief,
                topic=topic,
                replan=replan_request,
                db=db,
            )

        return topic, result.model_dump() if result is not None else None

    results = await asyncio.gather(
        *[_dispatch_one(topic) for topic in topics],
        return_exceptions=True,
    )

    for topic, result in zip(topics, results, strict=False):
        if isinstance(result, Exception):
            logger.error(
                "[coordinator] Specialist dispatch failed for %s: %s",
                topic,
                result,
                exc_info=result,
            )
            output[topic] = None
            continue

        out_topic, out_dict = result
        output[out_topic] = out_dict

    return output


def _llm_output_to_plan_dict(
    topic: str,
    llm_output: Dict[str, Any],
    brief: TripBrief,
) -> Dict[str, Any]:
    """Bridge LLMSpecialistOutput dict to SpecialistPlan-compatible dict.

    The LLMSpecialistOutput has {feasibility_status, activities, constraints}.
    The SpecialistPlan has {topic, day_plans, constraints, editorial, ...}.
    This maps between the two shapes.
    """
    activities = llm_output.get("activities", [])
    constraints = llm_output.get("constraints", [])

    day_plans: List[Dict[str, Any]] = []
    for i, activity in enumerate(activities):
        day_plans.append(
            {
                "day_number": activity.get("day", i + 1),
                "period": "morning",
                "title": activity.get("title", ""),
                "description": activity.get("description", ""),
                "location": activity.get("location"),
                "lat": activity.get("lat"),
                "lng": activity.get("lng"),
                "duration_hours": activity.get("duration_hours", 3.0),
                "difficulty": activity.get("difficulty", "beginner"),
                "depth_meters": activity.get("depth_meters"),
                "elevation_meters": activity.get("elevation_meters"),
                "certification_required": activity.get("certification_required"),
                "logic_hook": activity.get("logic_hook"),
            }
        )

    constraint_dicts: List[Dict[str, Any]] = []
    for c in constraints:
        constraint_dicts.append(
            {
                "constraint_id": c.get("constraint_id", ""),
                "constraint_type": c.get("constraint_type", "blocking"),
                "applies_to_categories": c.get("applies_to_categories", []),
                "buffer_hours": c.get("buffer_hours"),
                "reason": c.get("reason", ""),
                "label": c.get("label"),
                "icon": c.get("icon"),
            }
        )

    return {
        "topic": topic,
        "feasibility_status": llm_output.get("feasibility_status", "feasible"),
        "feasibility_reason": llm_output.get("feasibility_reason"),
        "day_plans": day_plans,
        "constraints": constraint_dicts,
        "transit_requirements": [],
        "estimated_cost": None,
        "editorial": llm_output.get("editorial", ""),
        "confidence": 0.8,
    }


def _plan_to_strategy_section(
    topic: str,
    plan_dict: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """Convert a SpecialistPlan-compatible dict to a strategy section dict.

    Bridges the coordinator's plan format into the strategy_sections format
    that the frontend expects.
    """
    from app.placeholders import get_activity_image
    from app.planner.services.section_builder import build_specialist_section

    trip_plan: Dict[str, Any] = state.get("trip_plan", {})
    trip_settings: Dict[str, Any] = state.get("trip_settings", {})
    activity_settings = trip_settings.get("activity_settings", {})

    # Convert day_plans to content_blocks format
    content_added: List[Dict[str, Any]] = []
    for dp in plan_dict.get("day_plans", []):
        content_added.append(
            {
                "title": dp.get("title", ""),
                "description": dp.get("description", ""),
                "logic_hook": dp.get("logic_hook"),
                "type": "activity",
                "day": dp.get("day_number"),
                "image_url": None,
                "coordinates": (
                    [dp["lng"], dp["lat"]]
                    if dp.get("lat") is not None and dp.get("lng") is not None
                    else None
                ),
                "intensity": "moderate",
                "duration_hours": dp.get("duration_hours", 3.0),
            }
        )

    # Hero image
    hero_image = None
    if content_added:
        hero_image = get_activity_image(topic, trip_plan.get("destination", ""), topic)

    # Constraints
    constraints = [
        {
            "rule": c.get("reason", ""),
            "reason": c.get("reason", ""),
            "type": c.get("constraint_type", "blocking"),
            "severity": c.get("constraint_type", "blocking"),
        }
        for c in plan_dict.get("constraints", [])
    ]

    return build_specialist_section(
        topic=topic,
        destination=trip_plan.get("destination"),
        start_date=trip_plan.get("start_date"),
        end_date=trip_plan.get("end_date"),
        feasibility_status=plan_dict.get("feasibility_status", "feasible"),
        feasibility_reason=plan_dict.get("feasibility_reason"),
        alternative_suggestion=None,
        constraints=constraints,
        content_added=content_added,
        enhancements=[],
        hero_image=hero_image,
        day_pref=activity_settings.get("day_preferences", {}).get(topic),
        skill_level=activity_settings.get("skill_level"),
    )


def _specialist_content_to_tiles(
    topic: str,
    section: Dict[str, Any],
    destination: str,
) -> List[Dict[str, Any]]:
    """Convert specialist content_added items into tile dicts.

    Produces tiles matching the experience_generator._experience_to_tile_dict()
    shape so the existing Phase 2.5 + Phase 5 enrichment/placement pipelines
    work without changes.

    Tile IDs are deterministic (survive replans) using stable_hash_short.
    """
    content_added = section.get("content_added", [])
    if not content_added:
        return []

    dest_slug = destination.lower().strip().replace(" ", "_").replace(",", "")
    tiles: List[Dict[str, Any]] = []

    for item in content_added:
        if item.get("is_buffer"):
            continue

        title = item.get("title", "")
        if not title:
            continue

        hash_key = f"{dest_slug}:{topic}:{title}"
        tile_id = f"spec_{dest_slug}_{topic}_{stable_hash_short(hash_key)}"

        coords = item.get("coordinates")  # [lng, lat] or None
        geo: Dict[str, Any] = {}
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            geo = {"lng": coords[0], "lat": coords[1]}

        tiles.append(
            {
                "id": tile_id,
                "type": "activity",
                "partner": "vertical_specialist",
                "partner_product_id": tile_id,
                "title": title,
                "subtitle": f"{topic.capitalize()} activity",
                "image_url": item.get("image_url"),
                "price_estimate": None,
                "price_level": None,
                "currency": "USD",
                "price_basis": "per_person",
                "is_estimate_only": True,
                "deeplink_url": "",
                "rating": None,
                "location_label": destination,
                "tags": ["activity", topic, "specialist"],
                "availability_status": "available",
                "meta": {
                    "specialist_type": topic,
                    "category": topic,
                    "duration_hours": item.get("duration_hours", 3.0),
                    "description": item.get("description", ""),
                    "preferred_day": item.get("day"),
                    "intensity": item.get("intensity"),
                },
                "geo": geo,
                "source": "live",
                "source_agent": "vertical_specialist",
            }
        )

    return tiles


def _inject_specialist_tiles_into_state(state: Dict[str, Any]) -> None:
    """Inject specialist content_added items as real tiles into state.

    Called at the top of _build_itinerary() after DISPATCH_SPECIALISTS +
    SEARCH_TILES have both completed. Writes tile_id back to each content_added
    item so Phase 2 reads it during ActivityBlock construction.
    """
    strategy_sections = state.get("strategy_sections", [])
    destination = state.get("trip_plan", {}).get("destination", "")
    if not destination:
        return

    tiles = state.get("tiles", {})
    activity_tiles = tiles.get("activities", [])
    if not isinstance(activity_tiles, list):
        activity_tiles = []

    existing_ids = {t.get("id") for t in activity_tiles if isinstance(t, dict) and t.get("id")}
    new_spec_ids: set[str] = set()
    new_tiles: List[Dict[str, Any]] = []

    for section in strategy_sections:
        topic = _norm_topic(section.get("specialist_type", ""))
        if not topic or topic in ("general", "local_expert"):
            continue
        if section.get("feasibility_status") == "infeasible":
            continue

        spec_tiles = _specialist_content_to_tiles(topic, section, destination)

        # Write tile_id back onto content_added items for Phase 2 ActivityBlock
        content_added = section.get("content_added", [])
        tile_by_title: Dict[str, str] = {}
        for t in spec_tiles:
            key = (t.get("title") or "").strip().lower()
            if key:
                tile_by_title[key] = t["id"]

        for item in content_added:
            if item.get("is_buffer"):
                continue
            key = (item.get("title") or "").strip().lower()
            tid = tile_by_title.get(key)
            if tid:
                item["tile_id"] = tid

        for t in spec_tiles:
            new_spec_ids.add(t["id"])
            if t["id"] not in existing_ids:
                new_tiles.append(t)

    # Remove stale specialist tiles from previous runs
    activity_tiles = [
        t
        for t in activity_tiles
        if not isinstance(t, dict)
        or t.get("source_agent") != "vertical_specialist"
        or t.get("id") in new_spec_ids
    ]

    activity_tiles.extend(new_tiles)
    tiles["activities"] = activity_tiles
    state["tiles"] = tiles

    if new_tiles:
        logger.info(
            "[coordinator] Injected %d specialist tiles (%d total specialist)",
            len(new_tiles),
            len(new_spec_ids),
        )


async def _enrich_specialist_tiles(state: Dict[str, Any]) -> None:
    """Enrich specialist tiles with Google Places data (photos, ratings, coordinates).

    Gated by settings.use_google_places_provider. Graceful degradation: tiles
    work with LLM coordinates if enrichment fails.
    """
    if not settings.use_google_places_provider:
        return

    tiles = state.get("tiles", {})
    activity_tiles = tiles.get("activities", [])
    if not isinstance(activity_tiles, list):
        return

    specialist_tiles = [
        t
        for t in activity_tiles
        if isinstance(t, dict) and t.get("source_agent") == "vertical_specialist"
    ]
    if not specialist_tiles:
        return

    destination = state.get("trip_plan", {}).get("destination", "")
    if not destination:
        return

    try:
        from app.tile_service.google_places_provider import enrich_activities_with_places

        enriched = await enrich_activities_with_places(
            specialist_tiles, destination, path_label="specialist_enrich"
        )

        # Replace specialist tiles in the activity list with enriched versions
        enriched_by_id = {t.get("id"): t for t in enriched if isinstance(t, dict)}
        for i, t in enumerate(activity_tiles):
            if isinstance(t, dict) and t.get("id") in enriched_by_id:
                enriched_tile = enriched_by_id[t["id"]]
                # Sync geo from verified Google Places coordinates so Phase 2.5
                # (which reads geo, not coordinates) gets the best data.
                coords = enriched_tile.get("coordinates")
                if isinstance(coords, list) and len(coords) == 2:
                    enriched_tile["geo"] = {"lng": coords[0], "lat": coords[1]}
                activity_tiles[i] = enriched_tile

        tiles["activities"] = activity_tiles
        state["tiles"] = tiles
        logger.info(
            "[coordinator] Enriched %d specialist tiles via Google Places",
            len(enriched),
        )
    except Exception as exc:
        logger.warning("[coordinator] Specialist tile enrichment failed (graceful): %s", exc)


# ---------------------------------------------------------------------------
# Tile search (Phase 2: minimal bridge)
# ---------------------------------------------------------------------------


async def _search_tiles(
    state: Dict[str, Any],
    classifier: ClassifierOutput,
    tile_types: Optional[List[str]] = None,
    session_id: str = "",
) -> Dict[str, Any]:
    """Fetch tiles directly through logistics_node (no @tool wrapper)."""
    from app.planner.nodes.logistics_node import logistics_node
    from app.planner.state.graph_state import GraphState, TripPlan

    trip_plan: Dict[str, Any] = state.get("trip_plan", {})
    trip_settings: Dict[str, Any] = state.get("trip_settings", {})
    requested_types = set(tile_types or ["flights", "hotels", "activities"])
    existing_tiles = state.get("tiles", {})
    merged_tiles = dict(existing_tiles) if isinstance(existing_tiles, dict) else {}

    # Limit fetched verticals by requested tile types.
    settings_for_search = dict(trip_settings) if isinstance(trip_settings, dict) else {}
    booking_types = dict(settings_for_search.get("booking_types", {}))

    # Always include activities when Tier 2 categories exist — plan_turn() may
    # exclude them for date_change (assuming specialists handle content), but
    # Tier 2 categories (yoga, nightlife, tours) have no specialist and rely
    # on logistics_node's experience generator.
    if "activities" not in requested_types:
        activity_settings = trip_settings.get("activity_settings", {})
        categories = set(
            activity_settings.get("categories", []) if isinstance(activity_settings, dict) else []
        )
        tier2_cats = categories - TIER1_SPECIALIST_NAMES
        if tier2_cats:
            requested_types.add("activities")

    if "flights" not in requested_types:
        booking_types["flights"] = "off"
    if "activities" not in requested_types:
        booking_types["activities"] = "off"
    if "hotels" not in requested_types:
        booking_types["hotels"] = "off"
    settings_for_search["booking_types"] = booking_types

    strategy_sections = state.get("strategy_sections", [])
    executed_topics = [
        _norm_topic(s.get("specialist_type"))
        for s in strategy_sections
        if isinstance(s, dict) and s.get("specialist_type")
    ]
    if not executed_topics:
        activity_settings = settings_for_search.get("activity_settings", {})
        categories = (
            activity_settings.get("categories", []) if isinstance(activity_settings, dict) else []
        )
        executed_topics = [
            _norm_topic(c) for c in categories if _norm_topic(c) in TIER1_SPECIALIST_NAMES
        ]
    executed_topics = sorted({t for t in executed_topics if t})

    graph_trip_plan = TripPlan(
        destination=trip_plan.get("destination"),
        origin=trip_plan.get("origin"),
        origin_iata=trip_plan.get("origin_iata"),
        destination_iata=trip_plan.get("destination_iata"),
        start_date=trip_plan.get("start_date"),
        end_date=trip_plan.get("end_date"),
        adults=trip_plan.get("adults", 1) or 1,
        children=trip_plan.get("children", 0) or 0,
        budget=trip_plan.get("budget"),
        currency=trip_plan.get("currency", "USD"),
    )
    graph_state = GraphState(
        trip_plan=graph_trip_plan,
        tiles={
            key: value if isinstance(value, list) else []
            for key, value in merged_tiles.items()
            if isinstance(key, str)
        },
        metadata={
            "trip_settings": settings_for_search,
            "trip_inputs": {
                **settings_for_search,
                "date_flex": bool(trip_plan.get("date_flex", False)),
                "trip_duration": trip_plan.get("trip_duration"),
                "date_window_start": trip_plan.get("date_window_start"),
                "date_window_end": trip_plan.get("date_window_end"),
            },
            "executed_strategy_topics": executed_topics,
        },
    )

    logger.info(
        "[coordinator] Refreshing tiles via logistics_node (change_type=%s types=%s)",
        classifier.change_type.value,
        sorted(requested_types),
    )

    try:
        graph_state = await logistics_node(graph_state)
    except Exception as exc:
        logger.warning("[coordinator] logistics_node tile fetch failed: %s", exc)
        return merged_tiles

    refreshed_tiles = graph_state.tiles if isinstance(graph_state.tiles, dict) else {}
    for tile_type in ("flights", "hotels", "activities"):
        if tile_type not in requested_types:
            continue
        tile_list = refreshed_tiles.get(tile_type, [])
        merged_tiles[tile_type] = tile_list if isinstance(tile_list, list) else []

    turn_meta = dict(state.get("turn_meta", {}))
    turn_meta["tiles_replaced"] = True
    flight_status = graph_state.metadata.get("flight_search_status")
    if isinstance(flight_status, str) and flight_status:
        turn_meta["flight_search_status"] = flight_status
    if "activities" in requested_types:
        browseable = graph_state.metadata.get("browseable_activities")
        turn_meta["browseable_activities"] = browseable if isinstance(browseable, list) else []
    turn_meta["tile_search_summary"] = (
        f"Found {len(merged_tiles.get('flights', []))} flights, "
        f"{len(merged_tiles.get('hotels', []))} hotels, "
        f"{len(merged_tiles.get('activities', []))} activities"
    )
    state["turn_meta"] = turn_meta

    return merged_tiles


# ---------------------------------------------------------------------------
# Local intel (Phase 2: skeleton only)
# ---------------------------------------------------------------------------


async def _run_local_intel(
    state: Dict[str, Any],
    session_id: str = "",
) -> Optional[Dict[str, Any]]:
    """Run local expert Phase A (instant skeleton) + stash Phase B enrichment.

    Returns a strategy section dict or None.
    """
    trip_plan: Dict[str, Any] = state.get("trip_plan", {})
    destination = trip_plan.get("destination")
    if not destination:
        return None

    try:
        from app.planner.nodes.expert_constraints import _get_constraints_as_list
        from app.planner.services.section_builder import build_local_expert_section

        constraint_list = _get_constraints_as_list(destination)
        warning_constraints = [c for c in constraint_list if c["severity"] == "warning"]

        if warning_constraints:
            joined = " & ".join(list({c["type"] for c in warning_constraints})[:2])
            one_liner = f"{destination}: review {joined} requirements before your trip"
        else:
            one_liner = f"Your adventure in {destination}"

        # Gallery images
        from app.data.demo_curation import DEMO_MANIFEST
        from app.placeholders import get_destination_gallery

        dest_key = destination.lower().strip()
        gallery = DEMO_MANIFEST.get(dest_key, {}).get("destination_gallery", [])
        if not gallery:
            gallery = get_destination_gallery(destination)

        constraints_applied = [
            {
                "rule": c["desc"],
                "type": c["type"],
                "severity": c["severity"],
                "reason": c["desc"],
            }
            for c in constraint_list
        ]

        section = build_local_expert_section(
            destination=destination,
            one_liner=one_liner,
            bullets=[c["desc"] for c in constraint_list[:3]],
            must_dos=[],
            logistics_notes=[],
            constraints_applied=constraints_applied,
            content_added=[],
            gallery_images=gallery,
            travel_intelligence={},
            principles=[c["desc"] for c in warning_constraints[:4]],
        )

        # Phase B: stash enrichment closure so streaming.py fires it after db.commit()
        from app.config import settings as _settings

        if _settings.local_expert_use_llm and session_id:
            from app.planner.nodes.local_expert import (
                _MAX_PENDING_ENRICHMENTS,
                _pending_enrichments,
                _pending_lock,
                build_enrichment_closure,
            )

            _enrich = build_enrichment_closure(
                destination=destination,
                start_date=trip_plan.get("start_date"),
                end_date=trip_plan.get("end_date"),
                adults=trip_plan.get("adults", 1),
                children=trip_plan.get("children", 0),
                session_id=session_id,
            )
            async with _pending_lock:
                if len(_pending_enrichments) >= _MAX_PENDING_ENRICHMENTS:
                    _oldest = next(iter(_pending_enrichments))
                    _pending_enrichments.pop(_oldest)
                    logger.warning("[coordinator] Evicting stale enrichment for %s", _oldest)
                _pending_enrichments[session_id] = (_enrich, time.monotonic())
            section["local_expert_enrichment"] = {
                "state": "pending",
                "error_code": None,
            }
            logger.debug("[coordinator] Phase B: enrichment stashed for %s", session_id)
        else:
            section["local_expert_enrichment"] = {
                "state": "ready",
                "error_code": None,
            }

        return section

    except Exception as exc:
        logger.warning("[coordinator] Local intel skeleton failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Itinerary building (Phase 2: bridge to ItineraryBuilder)
# ---------------------------------------------------------------------------


async def _build_itinerary(
    state: Dict[str, Any],
) -> Optional[List[Dict[str, Any]]]:
    """Build itinerary day cards from current state.

    Phase 2: Uses ItineraryBuilder directly with state dicts.
    Returns list of day card dicts, or None if preconditions not met.
    """
    trip_plan: Dict[str, Any] = state.get("trip_plan", {})
    start_date = trip_plan.get("start_date")
    end_date = trip_plan.get("end_date")
    destination = trip_plan.get("destination")

    if not start_date or not end_date or not destination:
        return None

    # Inject specialist content_added items as real tiles
    _inject_specialist_tiles_into_state(state)
    await _enrich_specialist_tiles(state)

    tiles: Dict[str, Any] = state.get("tiles", {})
    strategy_sections = state.get("strategy_sections", [])

    # Need either hotels or activities to build
    if not tiles.get("hotels") and not tiles.get("activities"):
        return None

    try:
        from app.services.itinerary_builder import ItineraryBuilder, ItineraryBuilderInput
        from app.utils.tile_utils import flatten_tiles_to_id_map

        tile_id_map = flatten_tiles_to_id_map(tiles)

        activity_settings = state.get("trip_settings", {}).get("activity_settings", {})
        booking_types = state.get("trip_settings", {}).get("booking_types", {})
        activities_off = (
            isinstance(booking_types, dict) and booking_types.get("activities") == "off"
        )
        categories = (
            activity_settings.get("categories", []) if isinstance(activity_settings, dict) else []
        )
        if activities_off:
            activity_categories: list[str] | None = []
        else:
            activity_categories = categories or None

        activities_per_day = (
            activity_settings.get("activities_per_day")
            if isinstance(activity_settings, dict)
            else None
        )

        builder_input = ItineraryBuilderInput(
            start_date=start_date,
            end_date=end_date,
            strategy_sections=strategy_sections if strategy_sections else [],
            tiles=tile_id_map,
            destination=destination,
            origin=trip_plan.get("origin"),
            activity_categories=activity_categories,
            activities_per_day=activities_per_day,
        )

        builder = ItineraryBuilder()
        result = await asyncio.to_thread(builder.build, builder_input)

        # Store builder result in turn_meta for downstream state computation.
        turn_meta = dict(state.get("turn_meta", {}))
        turn_meta["builder_result"] = {
            "success": result.success,
            "activities_placed": result.total_activities_placed,
            "activities_dropped": max(
                0, result.total_activities_input - result.total_activities_placed
            ),
            "conflicts": [c.model_dump() for c in result.conflicts],
            "warnings": result.warnings,
        }
        state["turn_meta"] = turn_meta

        if result.day_cards:
            day_cards = [card.model_dump() for card in result.day_cards]
            state["day_cards"] = day_cards
            return day_cards

        # Explicitly clear stale itinerary when builder returns no cards.
        state["day_cards"] = []
        return []

    except Exception as exc:
        logger.warning("[coordinator] Itinerary build failed: %s", exc)
        turn_meta = dict(state.get("turn_meta", {}))
        turn_meta["builder_result"] = {
            "success": False,
            "activities_placed": 0,
            "activities_dropped": 0,
            "conflicts": [],
            "warnings": [str(exc)],
        }
        state["turn_meta"] = turn_meta
        state["day_cards"] = []

    return None


# ---------------------------------------------------------------------------
# Response generation (Phase 5: streaming via conversationalist)
# ---------------------------------------------------------------------------


async def _generate_response_streaming(
    state: Dict[str, Any],
    classifier: ClassifierOutput,
    user_message: str,
) -> AsyncGenerator[str, None]:
    """Stream the assistant response token by token via the conversationalist.

    Delegates to ``conversationalist.generate_response_streaming()`` which
    builds a context-rich system prompt and streams the LLM response.
    """
    from app.planner.conversationalist import generate_response_streaming

    async for chunk in generate_response_streaming(state, classifier, user_message):
        yield chunk


# ---------------------------------------------------------------------------
# Envelope builder
# ---------------------------------------------------------------------------


def _normalize_state_for_chips(state: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure state has keys/shape expected by `_generate_chips_from_state`."""
    chip_state = dict(state)
    chip_state.setdefault("persistent_meta", {})
    chip_state.setdefault("day_cards", state.get("day_cards") or [])
    if not isinstance(chip_state.get("trip_plan"), dict):
        chip_state["trip_plan"] = {}
    if not isinstance(chip_state.get("trip_settings"), dict):
        chip_state["trip_settings"] = {}
    return chip_state


def _build_envelope(
    state: Dict[str, Any],
    user_message: str,
    session_id: str,
    assistant_message: str = "",
) -> Dict[str, Any]:
    """Build the final ``complete`` event data dict.

    MUST match the shape produced by ``_build_complete_envelope()`` in
    ``plan_graph.py`` so the frontend renders identically.
    """
    from app.planner.chip_generator import _generate_chips_from_state
    from app.planner.services.state_serde import serialize_agent_state

    trip_plan: Dict[str, Any] = state.get("trip_plan", {})
    trip_settings: Dict[str, Any] = state.get("trip_settings", {})
    tiles: Dict[str, Any] = state.get("tiles", {})
    strategy_sections: list = state.get("strategy_sections", [])
    day_cards: list = state.get("day_cards", [])
    persistent_meta: Dict[str, Any] = state.get("persistent_meta", {})
    turn_meta: Dict[str, Any] = state.get("turn_meta", {})
    coordinator_reset = bool(state.get("_coordinator_reset", False))

    # Generate suggestion chips
    suggestion_chips = _generate_chips_from_state(_normalize_state_for_chips(state))
    if suggestion_chips:
        persistent_meta = dict(persistent_meta)
        persistent_meta["suggestion_chips"] = suggestion_chips
        persistent_meta["suggestion_chip_texts"] = [
            c.get("message", "") for c in suggestion_chips if isinstance(c, dict)
        ]
        persistent_meta["suggestion_chip_meta"] = [
            {
                "chip_type": c.get("chip_type", "follow_up"),
                "category": c.get("category", ""),
                "icon": c.get("icon"),
            }
            for c in suggestion_chips
            if isinstance(c, dict)
        ]
        state["persistent_meta"] = persistent_meta

    if not isinstance(suggestion_chips, list):
        suggestion_chips = []

    suggested_replies = [c.get("message", "") for c in suggestion_chips if isinstance(c, dict)]
    suggestion_chip_meta = persistent_meta.get("suggestion_chip_meta", [])
    if not isinstance(suggestion_chip_meta, list):
        suggestion_chip_meta = []

    # Build trip_inputs from trip_plan + trip_settings
    trip_inputs: Dict[str, Any] = {}
    for field in (
        "destination",
        "origin",
        "origin_iata",
        "destination_iata",
        "start_date",
        "end_date",
        "date_flex",
        "trip_duration",
        "date_window_start",
        "date_window_end",
        "adults",
        "children",
        "budget",
        "currency",
    ):
        val = trip_plan.get(field)
        if val is not None:
            trip_inputs[field] = val

    # Merge settings sub-dicts
    for settings_field in (
        "booking_types",
        "flight_settings",
        "hotel_settings",
        "activity_settings",
        "transport_settings",
    ):
        val = trip_settings.get(settings_field)
        if val is not None:
            trip_inputs[settings_field] = val

    is_flex_dates = bool(trip_plan.get("date_flex"))

    # Suppress day_cards for flex dates
    if is_flex_dates and day_cards:
        day_cards = []
        state["day_cards"] = []

    # Determine ready_to_generate
    ready_to_generate = bool(
        trip_plan.get("destination")
        and trip_plan.get("start_date")
        and trip_plan.get("end_date")
        and not is_flex_dates
    )

    # Compute plan_view_state
    has_core = bool(
        trip_plan.get("destination")
        and trip_plan.get("start_date")
        and trip_plan.get("end_date")
        and not is_flex_dates
    )

    builder_result = turn_meta.get("builder_result", {})
    builder_ran = isinstance(builder_result, dict) and builder_result.get("success") is not None

    if not has_core:
        plan_view_state = "S0_BOOTSTRAP"
    elif builder_ran:
        plan_view_state = _compute_coordinator_s3_state(turn_meta, day_cards or [])
    elif day_cards:
        plan_view_state = _compute_coordinator_s3_state(turn_meta, day_cards)
    elif strategy_sections:
        plan_view_state = "S2_STRATEGY_READY"
    elif tiles.get("hotels") or tiles.get("activities"):
        plan_view_state = "S2_STRATEGY_READY"
    else:
        plan_view_state = "S0_BOOTSTRAP"

    # Write to persistent_meta
    persistent_meta = dict(state.get("persistent_meta", {}))
    persistent_meta["plan_view_state"] = plan_view_state
    state["persistent_meta"] = persistent_meta

    # Compute whether state changed this turn via hash comparison.
    pre_change_hashes = state.get("_pre_change_hashes", {})
    if not isinstance(pre_change_hashes, dict):
        pre_change_hashes = {}
    changes_made = bool(
        coordinator_reset
        or any(
            stable_hash(state.get(k)) != pre_change_hashes.get(k) for k in _CHANGE_DETECTION_KEYS
        )
    )

    # Strip ephemeral keys before serialization
    state.pop("_pre_change_hashes", None)
    state.pop("_pre_change_briefs", None)
    state.pop("_coordinator_reset", None)

    # Serialize state
    serialized = serialize_agent_state(state)

    # Executed topics from strategy sections
    executed_topics = list(
        {
            s.get("specialist_type")
            for s in strategy_sections
            if isinstance(s, dict) and s.get("specialist_type")
        }
    )

    # Validation result from turn_meta
    validation_result = turn_meta.get("validation_result", {})
    raw_constraint_violations = validation_result.get("violations", [])
    constraint_violations = (
        raw_constraint_violations if isinstance(raw_constraint_violations, list) else []
    )
    raw_fields_changed = turn_meta.get("fields_changed", [])
    fields_changed = raw_fields_changed if isinstance(raw_fields_changed, list) else []
    raw_turn_steps = turn_meta.get("turn_steps", [])
    turn_steps = raw_turn_steps if isinstance(raw_turn_steps, list) else []
    ack_updates = [
        {
            "field": str(step.get("type", "update")),
            "to": str(step.get("summary", "")).strip(),
        }
        for step in turn_steps
        if isinstance(step, dict) and str(step.get("summary", "")).strip()
    ]

    # Surface partial parallel failures as ack_updates
    partial_failures = turn_meta.get("partial_failures", [])
    if isinstance(partial_failures, list) and partial_failures:
        for step_name in partial_failures:
            label = _FAILURE_LABELS.get(step_name, f"{step_name} temporarily unavailable")
            ack_updates.append({"field": "partial_failure", "to": label})

    # Ack status
    has_blocking = turn_meta.get("has_blocking_violations", False)
    raw_blocking_violations = turn_meta.get("constraint_violations", [])
    blocking_violations = (
        raw_blocking_violations if isinstance(raw_blocking_violations, list) else []
    )
    if has_blocking and blocking_violations:
        constraint_violations = blocking_violations
    route_violation = next(
        (v for v in constraint_violations if isinstance(v, dict) and v.get("category") == "route"),
        None,
    )
    has_field_changes = any(u.get("field") != "partial_failure" for u in ack_updates)
    if route_violation:
        ack_status = "rejected"
        ack_updates = [{"field": "route", "to": route_violation.get("code", "INVALID_ROUTE")}]
    elif has_field_changes:
        ack_status = "applied"
    elif partial_failures:
        ack_status = "partial"
    else:
        ack_status = "no_change"

    constraints_validated = (
        [
            {
                "validator": "validate_plan",
                "valid": bool(validation_result.get("valid")),
            }
        ]
        if validation_result.get("valid") is not None
        else []
    )

    # Flatten tiles
    flattened_tiles: Dict[str, Any] = {}
    for _category, tile_list in tiles.items():
        if not isinstance(tile_list, list):
            continue
        for tile in tile_list:
            if isinstance(tile, dict):
                tile_id = tile.get("id")
                if tile_id:
                    flattened_tiles[tile_id] = tile

    origin_just_set = bool(turn_meta.get("origin_just_set", False))
    tiles_replaced = bool(turn_meta.get("tiles_replaced", False))
    browseable_activities = turn_meta.get("browseable_activities", [])

    document: Dict[str, Any] = {
        "trip_context_id": None,
        "trip_inputs": trip_inputs,
        "branches": [],
        "tiles": flattened_tiles,
        "assistant_message": assistant_message,
        "ready_to_generate": ready_to_generate,
        "suggested_responses": suggested_replies,
        "suggested_response_meta": suggestion_chip_meta,
        "suggestion_chips": suggestion_chips,
        "plan_view_state": plan_view_state,
        "strategy_sections": strategy_sections,
        "pending_strategy_topics": [],
        "executed_strategy_topics": executed_topics,
        "origin_just_set": origin_just_set,
        "tiles_replaced": tiles_replaced,
        "constraints_validated": constraints_validated,
        "constraint_violations": constraint_violations,
        "browseable_activities": browseable_activities,
        "can_expand_to_itinerary": bool(strategy_sections) and ready_to_generate,
        "itinerary_day_cards": [] if coordinator_reset else (day_cards if day_cards else None),
        "ack_status": ack_status,
        "ack_updates": ack_updates,
        "applied_updates": _canonicalize_applied_updates(fields_changed),
        "_debug": {"applied_updates_raw": fields_changed},
    }

    return {
        "session_state": serialized,
        "assistant_message": assistant_message,
        "suggestion_chips": suggestion_chips,
        "suggested_responses": suggested_replies,
        "trip_inputs": trip_inputs,
        "branches": [],
        "ready_to_generate": ready_to_generate,
        "changes_made": changes_made,
        "document": document,
        "errors": [],
        "coordinator_reset": coordinator_reset,
    }


def _compute_coordinator_s3_state(
    turn_meta: Dict[str, Any],
    day_cards: list,
) -> str:
    """Compute S3 sub-state from builder metadata."""
    builder_result = turn_meta.get("builder_result", {})
    builder_success = builder_result.get("success", True)
    conflicts = builder_result.get("conflicts", [])
    conflict_count = len(conflicts) if isinstance(conflicts, list) else 0

    if builder_success:
        if not day_cards:
            return "S3_BLOCKED"
        return "S3_EDITING" if conflict_count > 0 else "S3_ITINERARY_READY"
    else:
        return "S3_PARTIAL_CONFLICT" if day_cards else "S3_BLOCKED"


# ---------------------------------------------------------------------------
# Step execution
# ---------------------------------------------------------------------------


async def _execute_step(
    step: ExecutionStep,
    state: Dict[str, Any],
    classifier: ClassifierOutput,
    user_message: str,
    session_id: str = "",
) -> Optional[Dict[str, Any]]:
    """Execute a single step from the execution plan.

    Returns an SSE event dict to yield, or None if no event needed.
    """
    step_type = step.step_type

    if step_type == StepType.SHORT_CIRCUIT:
        reason = step.params.get("reason", "")
        if reason == "reset":
            # Clear state
            state["trip_plan"] = {}
            state["trip_settings"] = {}
            _clear_planning_artifacts(state)
            state["persistent_meta"] = {}
            state["_coordinator_reset"] = True
        return None

    if step_type == StepType.DISPATCH_SPECIALISTS:
        topics = step.params.get("topics", [])
        is_replan = step.params.get("is_replan", False)
        preserves = step.params.get("preserves", [])
        other_plans = state.get("specialist_plans", {})
        removed_topics = {_norm_topic(t) for t in classifier.removal_targets if _norm_topic(t)}

        results = await _dispatch_specialists_parallel(
            topics=topics,
            state=state,
            classifier=classifier,
            other_plans=other_plans,
            is_replan=is_replan,
            preserves=preserves,
        )

        # Store specialist plans and build strategy sections
        specialist_plans = dict(state.get("specialist_plans", {}))
        if removed_topics:
            specialist_plans = {
                topic: plan
                for topic, plan in specialist_plans.items()
                if _norm_topic(topic) not in removed_topics
            }
            state["strategy_sections"] = [
                section
                for section in state.get("strategy_sections", [])
                if isinstance(section, dict)
                and _norm_topic(str(section.get("specialist_type", ""))) not in removed_topics
            ]
            # Removed specialist content invalidates previously built itinerary cards.
            state["day_cards"] = []
        if classifier.change_type in _FULL_INVALIDATION_CHANGES:
            specialist_plans = {}
            state["strategy_sections"] = [
                s
                for s in state.get("strategy_sections", [])
                if isinstance(s, dict) and s.get("specialist_type") == "local_expert"
            ]
        for topic, llm_output_dict in results.items():
            if llm_output_dict is not None:
                brief = build_brief(topic, state, classifier, specialist_plans)
                plan_dict = _llm_output_to_plan_dict(topic, llm_output_dict, brief)
                specialist_plans[topic] = plan_dict

                # Build strategy section
                section = _plan_to_strategy_section(topic, plan_dict, state)
                # Upsert into strategy_sections
                sections = list(state.get("strategy_sections", []))
                sections = [s for s in sections if s.get("specialist_type") != topic]
                sections.append(section)
                state["strategy_sections"] = sections

        state["specialist_plans"] = specialist_plans
        return {
            "type": "partial",
            "data": {"kind": "strategy_sections", "payload": state.get("strategy_sections", [])},
        }

    if step_type == StepType.LOCAL_INTEL:
        section = await _run_local_intel(state, session_id=session_id)
        if section:
            sections = list(state.get("strategy_sections", []))
            sections = [
                s for s in sections if s.get("specialist_type") != section.get("specialist_type")
            ]
            sections.insert(0, section)  # Local expert goes first (anchor)
            state["strategy_sections"] = sections
            return {
                "type": "partial",
                "data": {"kind": "strategy_sections", "payload": sections},
            }
        return None

    if step_type == StepType.SEARCH_TILES:
        tile_types = step.params.get("tile_types", [])
        tiles = await _search_tiles(
            state,
            classifier,
            tile_types=tile_types,
            session_id=session_id,
        )
        state["tiles"] = tiles
        return {
            "type": "partial",
            "data": {"kind": "tiles", "payload": _flatten_tiles_payload(tiles)},
        }

    if step_type == StepType.BUILD_ITINERARY:
        await _build_itinerary(state)
        return None

    if step_type == StepType.GENERATE_RESPONSE:
        # Response generation handled in execute_turn
        return None

    logger.warning("[coordinator] Unknown step type: %s", step_type)
    return None


async def _execute_parallel_group(
    steps: List[ExecutionStep],
    state: Dict[str, Any],
    classifier: ClassifierOutput,
    user_message: str,
    session_id: str = "",
) -> List[Dict[str, Any]]:
    """Execute a group of steps in parallel via asyncio.gather.

    Note on state mutation: parallel steps mutate the same state dict.
    This is safe in asyncio (single-threaded) as long as steps write
    to different keys. Current parallel groups:
    - DISPATCH_SPECIALISTS writes specialist_plans + strategy_sections
    - SEARCH_TILES writes tiles
    LOCAL_INTEL runs sequentially to avoid concurrent strategy_sections writes.
    """
    if not steps:
        return []

    tasks = [
        _execute_step(step, state, classifier, user_message, session_id=session_id)
        for step in steps
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)
    partial_events: List[Dict[str, Any]] = []

    failures: List[str] = []
    # Log any exceptions from parallel steps
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            failures.append(steps[i].step_type.value)
            logger.error(
                "[coordinator] Parallel step %s failed: %s",
                steps[i].step_type.value,
                result,
                exc_info=result,
            )
        elif isinstance(result, dict):
            partial_events.append(result)

    if failures:
        logger.warning(
            "[coordinator] Partial parallel failure (%s) — continuing with %d successful results",
            ", ".join(failures),
            len(partial_events),
        )
        turn_meta = dict(state.get("turn_meta", {}))
        existing = list(turn_meta.get("partial_failures", []))
        existing.extend(failures)
        turn_meta["partial_failures"] = existing
        state["turn_meta"] = turn_meta

    return partial_events


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def execute_turn(
    user_message: str,
    state: Dict[str, Any],
    session_id: str,
    doc_settings: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Main coordinator entry point. Yields SSE events.

    Steps:
    1. Merge doc_settings into state
    2. Classify the user message
    3. Apply extracted fields to state
    4. Plan the turn (pure Python)
    5. Execute plan steps
    6. Generate response
    7. Build and yield complete envelope

    Parameters
    ----------
    user_message : str
        The user's chat message.
    state : dict
        NomadicAgentState as a plain dict (already restored from session).
    session_id : str
        Session identifier for logging.
    doc_settings : dict | None
        User-owned settings from the document.

    Yields
    ------
    dict
        SSE event dicts: node_status, partial, token, complete, error.
    """
    wall_start = time.monotonic()

    try:
        # Step 0: Reset turn_meta for this turn
        state["turn_meta"] = {}
        _normalize_specialist_plan_keys(state)

        # Step 1: Merge document settings
        _merge_doc_settings(state, doc_settings)

        # Step 2: Classify
        summary = build_trip_state_summary(state)

        from app.planner.nodes.router_extraction import classify_change

        classifier = await classify_change(user_message, summary)

        logger.info(
            "[coordinator] Classified: intent=%s change_type=%s affects=%s",
            classifier.intent,
            classifier.change_type.value,
            classifier.affects,
        )

        # Backward-compatible node_status naming for extraction tool.
        if classifier.intent == "PLANNING":
            yield _node_status(
                "extract_trip_fields",
                "started",
                "Reading your message...",
                "brain",
                300,
            )
            yield _node_status(
                "extract_trip_fields",
                "completed",
                "Message understood",
                "brain",
                300,
            )

        # Step 3: Snapshot pre-change state, then apply extracted fields.
        # Only deepcopy the 2 keys needed by replan; hash the rest for change detection.
        state["_pre_change_briefs"] = {
            "trip_plan": copy.deepcopy(state.get("trip_plan", {})),
            "trip_settings": copy.deepcopy(state.get("trip_settings", {})),
        }
        state["_pre_change_hashes"] = {k: stable_hash(state.get(k)) for k in _CHANGE_DETECTION_KEYS}
        if classifier.intent == "PLANNING":
            _apply_classifier_to_state(state, classifier)
            if classifier.change_type in _FULL_INVALIDATION_CHANGES:
                _clear_planning_artifacts(state)
            yield {
                "type": "partial",
                "data": {
                    "kind": "trip_inputs",
                    "payload": _trip_inputs_partial_payload(state),
                },
            }
        elif classifier.intent == "RESET":
            yield {
                "type": "partial",
                "data": {
                    "kind": "trip_inputs",
                    "payload": {},
                },
            }

        # Step 4: Plan the turn
        plan = plan_turn(classifier, state)
        logger.info(
            "[coordinator] Execution plan: %s (steps=%d, est_llm=%d)",
            plan.reason,
            len(plan.steps),
            plan.estimated_llm_calls,
        )

        # Step 5: Execute plan steps
        # Group parallel steps together
        sequential_groups: List[List[ExecutionStep]] = []
        current_group: List[ExecutionStep] = []
        seen_parallel_with: set[StepType] = set()

        for step in plan.steps:
            if step.step_type == StepType.GENERATE_RESPONSE:
                # Response generation is always last, handled separately
                continue

            if step.parallel_with is not None:
                # This step runs in parallel with another
                seen_parallel_with.add(step.step_type)
                # Find or create the group containing the parallel target
                added = False
                for group in sequential_groups:
                    if any(s.step_type == step.parallel_with for s in group):
                        group.append(step)
                        added = True
                        break
                if not added:
                    current_group.append(step)
            else:
                if step.step_type in seen_parallel_with:
                    # Already added to a parallel group
                    continue
                if current_group:
                    sequential_groups.append(current_group)
                    current_group = []
                current_group = [step]

        if current_group:
            sequential_groups.append(current_group)

        for group in sequential_groups:
            if len(group) == 1:
                step = group[0]
                label, icon, duration = _step_status_info(step, state, classifier)
                node_name = _step_node_name(step)
                if node_name:
                    yield _node_status(node_name, "started", label, icon, duration)

                step_event = await _execute_step(
                    step,
                    state,
                    classifier,
                    user_message,
                    session_id=session_id,
                )
                if step_event is not None:
                    yield step_event

                if node_name:
                    yield _node_status(node_name, "completed", label, icon, duration)
            else:
                # Parallel group
                for step in group:
                    label, icon, duration = _step_status_info(step, state, classifier)
                    node_name = _step_node_name(step)
                    if node_name:
                        yield _node_status(node_name, "started", label, icon, duration)

                step_events = await _execute_parallel_group(
                    group,
                    state,
                    classifier,
                    user_message,
                    session_id=session_id,
                )
                for step_event in step_events:
                    yield step_event

                for step in group:
                    label, icon, duration = _step_status_info(step, state, classifier)
                    node_name = _step_node_name(step)
                    if node_name:
                        yield _node_status(node_name, "completed", label, icon, duration)

        # Step 6: Generate response (LLM only when planned)
        should_generate_response = any(
            step.step_type == StepType.GENERATE_RESPONSE for step in plan.steps
        )
        assistant_message = ""

        if should_generate_response:
            yield _node_status("response", "started", "Writing response...", "message-square", 800)

            response_chunks: List[str] = []
            async for chunk in _generate_response_streaming(state, classifier, user_message):
                response_chunks.append(chunk)
                yield {"type": "token", "data": chunk}

            assistant_message = "".join(response_chunks)
            if not assistant_message.strip():
                assistant_message = (
                    "I'm working on your trip plan. Let me know if you'd like to adjust anything."
                )
                logger.warning("[coordinator] Empty response from conversationalist")

            yield _node_status("response", "completed", "Response ready", "message-square", 800)
        else:
            assistant_message = _short_circuit_message(classifier.intent)
            if assistant_message:
                yield {"type": "token", "data": assistant_message}

        # Append user + assistant messages to state messages
        state.setdefault("messages", []).append(HumanMessage(content=user_message))
        state["messages"].append(AIMessage(content=assistant_message))

        # Step 7: Build and yield complete envelope
        envelope = _build_envelope(state, user_message, session_id, assistant_message)

        wall_ms = int((time.monotonic() - wall_start) * 1000)
        logger.info(
            "[coordinator] Turn complete: %s (%d ms)",
            plan.reason,
            wall_ms,
        )

        yield {"type": "complete", "data": envelope}

    except Exception as exc:
        logger.error("[coordinator] Turn failed: %s", exc, exc_info=True)
        yield {"type": "error", "message": str(exc)}


def _step_status_info(
    step: ExecutionStep,
    state: Optional[Dict[str, Any]] = None,
    classifier: Optional[ClassifierOutput] = None,
) -> tuple[str, str, int]:
    """Return (label, icon, estimated_duration_ms) for a step — context-aware."""
    dest = ""
    if state:
        dest = (state.get("trip_plan") or {}).get("destination", "") or ""

    st = step.step_type

    if st == StepType.CLASSIFY:
        return ("Reading your message...", "brain", 300)

    if st == StepType.SHORT_CIRCUIT:
        return ("Processing...", "zap", 100)

    if st == StepType.DISPATCH_SPECIALISTS:
        if classifier and classifier.affects:
            names = ", ".join(a.replace("_", " ") for a in classifier.affects[:2])
            return (f"Consulting {names} specialist...", "star", 3000)
        return ("Consulting specialists...", "star", 3000)

    if st == StepType.SEARCH_TILES:
        settings = (state or {}).get("trip_settings", {})
        booking = settings.get("booking_types", {})
        cats = settings.get("activity_settings", {}).get("categories", [])
        parts: list[str] = []
        if booking.get("hotels") != "off":
            parts.append("hotels")
        if booking.get("flights") not in ("off", None):
            parts.append("flights")
        if cats:
            parts.extend(cats[:2])
        search_str = " & ".join(parts) if parts else "options"
        loc = f" in {dest}" if dest else ""
        return (f"Finding {search_str}{loc}...", "search", 2000)

    if st == StepType.LOCAL_INTEL:
        loc = f" {dest}" if dest else ""
        return (f"Loading{loc} travel intelligence...", "building", 50)

    if st == StepType.BUILD_ITINERARY:
        plan = (state or {}).get("trip_plan", {})
        start = plan.get("start_date")
        end = plan.get("end_date")
        if start and end:
            try:
                s = datetime.strptime(start, "%Y-%m-%d")
                e = datetime.strptime(end, "%Y-%m-%d")
                days = (e - s).days + 1
                return (f"Building {days}-day itinerary...", "calendar", 200)
            except ValueError:
                pass
        return ("Building itinerary...", "calendar", 200)

    if st == StepType.GENERATE_RESPONSE:
        return ("Writing response...", "message-square", 800)

    return ("Processing...", "circle", 500)


def _step_node_name(step: ExecutionStep) -> Optional[str]:
    """Map coordinator step types to legacy node/tool names for SSE compatibility."""
    _NODE_MAP: Dict[StepType, Optional[str]] = {
        StepType.SHORT_CIRCUIT: None,
        StepType.DISPATCH_SPECIALISTS: "get_specialist_advice",
        StepType.SEARCH_TILES: "search_tiles",
        StepType.BUILD_ITINERARY: "build_itinerary",
        StepType.GENERATE_RESPONSE: "response",
        StepType.LOCAL_INTEL: "get_local_intel",
        StepType.CLASSIFY: None,
    }
    return _NODE_MAP.get(step.step_type, step.step_type.value)
