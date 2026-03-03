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
  - {"type": "feasibility_warning", "data": {topic, status, reason, alternative}}
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
from urllib.parse import quote

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
from app.planner.specialist_registry import (
    SPECIALIST_REGISTRY,
    TIER1_SPECIALIST_NAMES,
    TIER2_CATEGORY_ALIASES,
)

logger = logging.getLogger(__name__)

# Derived from specialist_registry — per-person price estimate fallbacks
# for specialist tiles when content_added items don't carry a price.
_SPECIALIST_DEFAULT_PRICE: dict[str, float] = {
    topic: cfg.default_price_estimate for topic, cfg in SPECIALIST_REGISTRY.items()
}

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


def _has_local_intel_for_destination(state: Dict[str, Any], destination: str | None) -> bool:
    """Return True when a local_expert section already matches the given destination."""
    dest_norm = (destination or "").strip().lower()
    if not dest_norm:
        return False

    sections = state.get("strategy_sections", [])
    if not isinstance(sections, list):
        return False

    for section in sections:
        if not isinstance(section, dict):
            continue
        if _norm_topic(str(section.get("specialist_type", ""))) != "local_expert":
            continue

        title = str(section.get("title", "")).strip().lower()
        one_liner = str(section.get("one_liner", "")).strip().lower()
        if dest_norm in title or dest_norm in one_liner:
            return True

    return False


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
        "activities_per_day": "preferences",
        "activity_categories": "preferences",
        "skill_level": "preferences",
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
        ChangeType.PREFERENCE,
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


def _normalize_tile_fields(tile: Dict[str, Any]) -> Dict[str, Any]:
    """Add canonical Tile schema fields from provider-specific variants.

    Additive — originals preserved for backward compatibility.
    """
    if not tile.get("geo"):
        coords = tile.get("coordinates")
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            try:
                tile["geo"] = {"lat": float(coords[1]), "lng": float(coords[0])}
            except (TypeError, ValueError):
                pass
    if not tile.get("deeplink_url") and tile.get("deeplink"):
        tile["deeplink_url"] = tile["deeplink"]
    if not tile.get("deeplink") and tile.get("deeplink_url"):
        tile["deeplink"] = tile["deeplink_url"]
    if not tile.get("category"):
        tile["category"] = (
            (tile.get("meta") or {}).get("category")
            or tile.get("type")  # "flight", "hotel", "activity"
            or "activity"
        )
    return tile


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
                    flattened[str(tile_id)] = _normalize_tile_fields(tile)
    return flattened


def _short_circuit_message(intent: str) -> str:
    """Deterministic, no-LLM response for greeting/reset short-circuits."""
    if intent == "RESET":
        return (
            "Are you sure you want to reset? This will clear your entire trip plan and start fresh."
        )
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
    # Clear stale overview/browseable so they don't leak from old destination
    persistent_meta = state.get("persistent_meta", {})
    if isinstance(persistent_meta, dict):
        persistent_meta.pop("itinerary_overview", None)
        persistent_meta.pop("itinerary_assumptions", None)
        persistent_meta.pop("browseable_activities", None)


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

    # Short-circuit GENERATE_PLAN_NOW when planning artifacts already exist.
    # Two tiers:
    #   - day_cards present  → skip to GENERATE_RESPONSE only (full itinerary ready)
    #   - strategy_sections present but no day_cards → skip specialists/local_intel,
    #     run SEARCH_TILES + BUILD_ITINERARY + GENERATE_RESPONSE
    categories_changed = "activity_categories" in state.get("turn_meta", {}).get(
        "fields_changed", []
    )
    if (
        change_type == ChangeType.INITIAL_PLAN
        and classifier.reasoning
        and "GENERATE_PLAN_NOW" in classifier.reasoning
        and not categories_changed
    ):
        if state.get("day_cards"):
            return ExecutionPlan(
                steps=[ExecutionStep(step_type=StepType.GENERATE_RESPONSE)],
                reason="GENERATE_PLAN_NOW — itinerary exists, response only",
                estimated_llm_calls=1,
                estimated_wall_ms=800,
            )
        if state.get("strategy_sections"):
            trip_plan_gp: Dict[str, Any] = state.get("trip_plan", {})
            has_dest_gp = bool(trip_plan_gp.get("destination") or classifier.destination)
            has_dates_gp = bool(
                (trip_plan_gp.get("start_date") or classifier.start_date)
                and (trip_plan_gp.get("end_date") or classifier.end_date)
            )
            gp_steps: List[ExecutionStep] = []
            if has_dest_gp and has_dates_gp:
                gp_steps.append(
                    ExecutionStep(
                        step_type=StepType.SEARCH_TILES,
                        params={"tile_types": ["flights", "hotels", "activities"]},
                    )
                )
                gp_steps.append(ExecutionStep(step_type=StepType.BUILD_ITINERARY))
            gp_steps.append(ExecutionStep(step_type=StepType.GENERATE_RESPONSE))
            return ExecutionPlan(
                steps=gp_steps,
                reason="GENERATE_PLAN_NOW — strategy exists, skip specialists",
                estimated_llm_calls=1,
                estimated_wall_ms=3000,
            )

    # Safety: if classifier says INITIAL_PLAN but itinerary already built and
    # no fields actually changed, skip to response-only.
    if (
        change_type == ChangeType.INITIAL_PLAN
        and state.get("day_cards")
        and not state.get("turn_meta", {}).get("fields_changed")
    ):
        return ExecutionPlan(
            steps=[ExecutionStep(step_type=StepType.GENERATE_RESPONSE)],
            reason="INITIAL_PLAN — itinerary exists + no field changes, response only",
            estimated_llm_calls=1,
            estimated_wall_ms=800,
        )

    # ----- Idempotent input short-circuit -----
    # If classifier extracted fields but none actually changed (all identical to
    # existing state), and a built itinerary already exists, skip the full
    # pipeline and just generate a response.  This avoids re-running specialists
    # + tiles + builder when the user repeats the same inputs.
    # Exclude INITIAL_PLAN to allow genuine "plan it" requests even with no changes.
    turn_meta_fc = state.get("turn_meta", {})
    _fields_changed = (
        turn_meta_fc.get("fields_changed", []) if isinstance(turn_meta_fc, dict) else []
    )
    if (
        not _fields_changed
        and change_type not in (ChangeType.INITIAL_PLAN, ChangeType.RESET, ChangeType.GREETING)
        and state.get("day_cards")
    ):
        logger.info(
            "[coordinator] Idempotent input — no effective field changes, "
            "skipping pipeline (change_type=%s)",
            change_type.value,
        )
        return ExecutionPlan(
            steps=[ExecutionStep(step_type=StepType.GENERATE_RESPONSE)],
            reason=f"Idempotent input ({change_type.value}) — no field changes, response only",
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
    if dispatch_list != sorted(
        _norm_topic(a) for a in (classifier.affects or []) if _norm_topic(a)
    ):
        logger.debug(
            "[coordinator] dispatch_list=%s differs from classifier.affects=%s",
            dispatch_list,
            classifier.affects,
        )
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
    target_destination = classifier.destination or trip_plan.get("destination")
    has_local_intel_for_target = _has_local_intel_for_destination(state, target_destination)
    _activity_change_types = {ChangeType.ADD_ACTIVITY, ChangeType.REMOVE_ACTIVITY}
    _affects_tier1 = bool(
        (
            classifier.affects
            and any(_norm_topic(t) in TIER1_SPECIALIST_NAMES for t in classifier.affects)
        )
        or any(_norm_topic(h) in TIER1_SPECIALIST_NAMES for h in classifier.specialist_hints)
    )
    needs_local_intel = (
        change_type in (ChangeType.INITIAL_PLAN, ChangeType.DESTINATION_CHANGE)
        and not has_local_intel_for_target
    ) or (
        change_type in _activity_change_types
        and _affects_tier1
        and not any(
            isinstance(s, dict) and s.get("specialist_type") == "local_expert"
            for s in state.get("strategy_sections", [])
        )
    )
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

    # Filter out topics that feasibility pre-check marked as infeasible.
    # Caveats are kept — the activity IS possible but with limitations.
    prechecks = state.get("turn_meta", {}).get("feasibility_prechecks", {})
    if prechecks:
        tier1_active = [
            t for t in tier1_active if prechecks.get(t, ("feasible",))[0] != "infeasible"
        ]

    if classifier.change_type in _FULL_INVALIDATION_CHANGES:
        if classifier.change_type == ChangeType.DESTINATION_CHANGE:
            # Dispatch all active Tier 1 categories for the new destination.
            # Categories are preserved through destination change (feasibility
            # pre-check handles viability), so tier1_active includes both
            # carried-forward and newly mentioned categories.
            return tier1_active
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
        return ["flights", "hotels", "activities"]
    if ct in (
        ChangeType.ADD_ACTIVITY,
        ChangeType.REMOVE_ACTIVITY,
        ChangeType.SWAP_ACTIVITY,
    ):
        return ["activities"]
    if ct == ChangeType.PREFERENCE:
        # APD change → regenerate activity tiles with new density
        if classifier.activities_per_day is not None:
            return ["activities"]
        return []
    return []


# ---------------------------------------------------------------------------
# Brief builders
# ---------------------------------------------------------------------------


def _scaled_target(
    topic_pref: Optional[int],
    apd: int,
    num_days: Optional[int],
) -> Optional[int]:
    """Compute effective target activity count for a specialist.

    Explicit per-topic day_preference wins outright.  Otherwise, scale
    available activity days by activities_per_day so the specialist
    generates enough content for the builder to fill each day slot.
    """
    if topic_pref is not None:
        return topic_pref
    if apd is not None and apd > 1:
        available = max(1, (num_days or 7) - 2)
        return min(
            available * apd, 10
        )  # Cap at 10 — structured output reliability drops beyond this
    return None


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
    apd: int = activity_settings.get("activities_per_day") or 2

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
        adults=trip_plan.get("adults") or 1,
        children=trip_plan.get("children") or 0,
        skill_level=classifier.skill_level or activity_settings.get("skill_level"),
        budget_total=budget_total,
        budget_allocation_pct=round(budget_pct, 2),
        reserved_days=sorted(reserved_days),
        target_day_count=_scaled_target(day_preferences.get(topic), apd, num_days),
        activities_per_day=apd,
        hotel_zone=trip_settings.get("hotel_settings", {}).get("location"),
        other_specialist_zones=other_zones,
        trip_vibe=trip_plan.get("vibe"),
        categories=list(activity_settings.get("categories", [])),
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
        removed_cats = {_norm_topic(c) for c in old_cats - new_cats}
        if removed_cats:
            existing_sections = state.get("strategy_sections", [])
            state["strategy_sections"] = [
                s
                for s in existing_sections
                if not isinstance(s, dict)
                or _norm_topic(s.get("specialist_type", "")) not in removed_cats
            ]
            sp = state.get("specialist_plans", {})
            if isinstance(sp, dict):
                for key in list(sp.keys()):
                    if _norm_topic(key) in removed_cats:
                        sp.pop(key, None)


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

    # Clear stale IATA codes when location changes so the resolver re-resolves.
    if "destination" in fields_changed:
        trip_plan.pop("destination_iata", None)
    if "origin" in fields_changed:
        trip_plan.pop("origin_iata", None)

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

    # On destination change, preserve user's category selections (e.g. diving).
    # The feasibility pre-check handles whether an activity is viable at the new
    # destination — the coordinator shouldn't preemptively clear categories.
    # Only clear day_preferences since day assignments are destination-specific.
    if classifier.change_type == ChangeType.DESTINATION_CHANGE:
        if activity_settings.get("day_preferences"):
            activity_settings["day_preferences"] = {}
        # Clear specialist strategy sections — they contain destination-specific
        # content (one_liner, content_added, hero_image) that is stale after
        # destination change. Preserve local_expert sections as they'll be
        # rebuilt independently. Categories persist (user still wants them).
        # Note: for non-GENERATE_PLAN_NOW paths, _clear_planning_artifacts()
        # wipes all sections anyway; this matters for GENERATE_PLAN_NOW reuse.
        existing_sections = state.get("strategy_sections", [])
        state["strategy_sections"] = [
            s
            for s in existing_sections
            if isinstance(s, dict) and s.get("specialist_type") == "local_expert"
        ]

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
        clamped = max(1, min(classifier.activities_per_day, 3))
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
            # Invalidate stale tiles and day_cards so tile scaling
            # re-runs with the updated density preference.
            tiles = state.get("tiles", {})
            if isinstance(tiles, dict) and tiles.get("activities"):
                tiles["activities"] = []
                state["tiles"] = tiles
            state["day_cards"] = []

    # Default activities_per_day to 2 if not explicitly set by user
    if not activity_settings.get("activities_per_day"):
        activity_settings["activities_per_day"] = 2

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
    origin_just_set = False
    booking_types = dict(trip_settings.get("booking_types", {}))
    has_origin_now = bool(trip_plan.get("origin"))
    if has_origin_now and not old_origin:
        origin_just_set = True
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
    if origin_just_set:
        turn_meta["origin_just_set"] = True
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

        # Extract raw user day preference for cache key alignment with
        # the parallel dispatch path (which caches with day_prefs.get(topic)).
        _trip_settings = state.get("trip_settings", {})
        _act_settings = _trip_settings.get("activity_settings", {})
        _raw_day_pref = _act_settings.get("day_preferences", {}).get(topic)

        async with async_session_factory() as db:
            result = await dispatch_specialist_with_brief(
                brief=brief,
                topic=topic,
                replan=replan_request,
                db=db,
                raw_day_pref=_raw_day_pref,
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
        "alternative_suggestion": llm_output.get("alternative_suggestion"),
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
        alternative_suggestion=plan_dict.get("alternative_suggestion"),
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
                "price_estimate": item.get("price_estimate")
                or _SPECIALIST_DEFAULT_PRICE.get(topic, 50.0),
                "price_level": None,
                "currency": "USD",
                "price_basis": "per_person",
                "is_estimate_only": True,
                "deeplink_url": f"https://www.google.com/maps/search/{quote(f'{title} {destination}')}",
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
    if not strategy_sections:
        cats = state.get("trip_settings", {}).get("activity_settings", {}).get("categories", [])
        tier1 = [c for c in cats if c in TIER1_SPECIALIST_NAMES]
        if tier1:
            logger.warning(
                "[coordinator] _inject_specialist_tiles: strategy_sections EMPTY "
                "but Tier 1 categories present: %s — specialist content will be lost",
                tier1,
            )
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


_ENRICHABLE_SOURCES = {"vertical_specialist", "experience_generator"}


async def _prepare_activity_tiles_for_build(state: Dict[str, Any]) -> None:
    """Prepare specialist + experience tiles for the itinerary builder.

    Light-weight pre-build pass: geocode fallback, photo URL signing, and
    Unsplash placeholders. Actual Google Places enrichment is deferred to
    _post_build_enrich_placed_activities (runs after builder places blocks).
    """
    if not settings.use_google_places_provider:
        return
    if not settings.google_places_enrichment_enabled:
        return

    tiles = state.get("tiles", {})
    activity_tiles = tiles.get("activities", [])
    if not isinstance(activity_tiles, list):
        return

    destination = state.get("trip_plan", {}).get("destination", "")
    if not destination:
        return

    try:
        from app.data.demo_curation import is_hero_destination
        from app.tile_service.google_places_provider import (
            _geocode_destination_async,
            _normalize_title_for_cache,
        )

        skip_geocode = is_hero_destination(destination)

        if not skip_geocode:
            # GAP 7: Build lookup from existing tiles that already have geo + google_place_id
            _geo_by_title: dict[str, dict] = {}
            for t in activity_tiles:
                if isinstance(t, dict) and t.get("geo") and t.get("google_place_id"):
                    _geo_by_title[_normalize_title_for_cache(t.get("title", ""))] = t.get("geo")

            # Geocode fallback for tiles missing geo (cheap, needed for builder placement)
            for i, t in enumerate(activity_tiles):
                if (
                    isinstance(t, dict)
                    and t.get("source_agent") in _ENRICHABLE_SOURCES
                    and not t.get("geo")
                ):
                    # GAP 7: Try reuse from existing GP tile first
                    cached_geo = _geo_by_title.get(_normalize_title_for_cache(t.get("title", "")))
                    if cached_geo:
                        t["geo"] = dict(cached_geo)
                        activity_tiles[i] = t
                        continue
                    query = f"{t.get('title', '')}, {destination}"
                    coords = await _geocode_destination_async(query)
                    if coords:
                        t["geo"] = {"lng": coords[1], "lat": coords[0]}
                        activity_tiles[i] = t

            # FIX 15: Destination-level geocode fallback for remaining tiles with no geo
            dest_geo = None
            for i, t in enumerate(activity_tiles):
                if (
                    isinstance(t, dict)
                    and t.get("source_agent") in _ENRICHABLE_SOURCES
                    and not t.get("geo")
                ):
                    if dest_geo is None:
                        coords = await _geocode_destination_async(destination)
                        dest_geo = {"lng": coords[1], "lat": coords[0]} if coords else {}
                    if dest_geo:
                        t["geo"] = dict(dest_geo)
                        activity_tiles[i] = t

        # Resolve photo_name -> signed proxy URL (free, local computation)
        session_id = state.get("session_id", "")
        if session_id:
            from app.tile_service.google_places_provider import build_signed_photo_url

            for tile in activity_tiles:
                if not isinstance(tile, dict):
                    continue
                photo_name = (
                    (tile.get("meta") or {}).get("photo_name") or tile.get("photo_name") or ""
                )
                if photo_name:
                    signed_url = build_signed_photo_url(session_id, photo_name)
                    if signed_url:
                        tile["image_url"] = signed_url

        # Unsplash placeholder fallback (free, local computation)
        from app.placeholders import get_placeholder_image

        for idx, tile in enumerate(activity_tiles):
            if not isinstance(tile, dict):
                continue
            if tile.get("source_agent") not in _ENRICHABLE_SOURCES:
                continue
            if tile.get("image_url"):
                continue
            topic = (tile.get("meta") or {}).get("specialist_type", "activity")
            tile["image_url"] = get_placeholder_image(
                category=topic,
                seed=f"{destination}-{topic}-{idx}",
                width=800,
                height=600,
            )

        tiles["activities"] = activity_tiles
        state["tiles"] = tiles
    except Exception as exc:
        logger.warning("[coordinator] Activity tile pre-build prep failed (graceful): %s", exc)


async def _post_build_enrich_placed_activities(
    state: Dict[str, Any], day_cards: list[Dict[str, Any]]
) -> None:
    """Enrich placed activity blocks with Google Places data after builder runs.

    Only enriches blocks that were actually placed in the itinerary (not dropped),
    and only those missing a google_place_id. Respects enrichment_cap=3 via
    enrich_activities_with_places.
    """
    if not settings.use_google_places_provider:
        return
    if not settings.google_places_enrichment_enabled:
        return

    destination = state.get("trip_plan", {}).get("destination", "")
    if not destination:
        return

    from app.data.demo_curation import is_hero_destination

    if is_hero_destination(destination):
        logger.info("[coordinator] Skipping post-build enrichment for curated: %s", destination)
        return

    try:
        from app.tile_service.google_places_provider import (
            _normalize_title_for_cache,
            build_signed_photo_url,
            enrich_activities_with_places,
        )

        # Build lookup of existing GP-enriched activity tiles to avoid re-searching
        existing_tiles = state.get("tiles", {}).get("activities", [])
        _gp_by_title: dict[str, dict] = {}
        for t in existing_tiles:
            if isinstance(t, dict) and t.get("google_place_id"):
                _gp_by_title[_normalize_title_for_cache(t.get("title", ""))] = t

        # Collect non-buffer blocks missing google_place_id that have a summary
        proxies: list[Dict[str, Any]] = []
        block_locations: list[tuple[int, int]] = []  # (day_idx, block_idx)
        _reused_count = 0
        session_id = state.get("session_id", "")
        for day_idx, card in enumerate(day_cards):
            blocks = card.get("blocks", [])
            for block_idx, block in enumerate(blocks):
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type", "")
                if block_type in ("buffer", "travel", "flight", "hotel_checkin", "hotel_checkout"):
                    continue
                if block.get("google_place_id"):
                    continue
                summary = block.get("summary", "")
                if not summary:
                    continue
                # Check if an existing GP tile matches this block
                existing = _gp_by_title.get(_normalize_title_for_cache(summary))
                if existing:
                    block["google_place_id"] = existing.get("google_place_id")
                    ex_coords = existing.get("coordinates")
                    if isinstance(ex_coords, list) and len(ex_coords) >= 2:
                        block["coordinates"] = {"lng": ex_coords[0], "lat": ex_coords[1]}
                    elif isinstance(ex_coords, dict):
                        block["coordinates"] = ex_coords
                    if existing.get("deeplink"):
                        block["deeplink"] = existing["deeplink"]
                    photo_name = existing.get("photo_name") or ""
                    if photo_name and session_id:
                        signed_url = build_signed_photo_url(session_id, photo_name)
                        if signed_url:
                            block["image_url"] = signed_url
                    elif existing.get("image_url"):
                        block["image_url"] = existing["image_url"]
                    _reused_count += 1
                    continue
                coords = block.get("coordinates")
                proxies.append(
                    {
                        "id": block.get("id", f"post_enrich_{day_idx}_{block_idx}"),
                        "title": summary,
                        "coordinates": coords if isinstance(coords, list) else None,
                        "photo_name": None,
                        "image_url": block.get("image_url"),
                        "meta": {},
                    }
                )
                block_locations.append((day_idx, block_idx))

        if _reused_count:
            logger.info(
                "[coordinator] Reused %d existing GP tiles, skipped enrichment", _reused_count
            )
        if not proxies:
            return

        _tp = state.get("trip_plan", {})
        _travelers = (_tp.get("adults") or 0) + (_tp.get("children") or 0) or 1
        enriched = await enrich_activities_with_places(
            proxies, destination, path_label="post_build_enrich", travelers=_travelers
        )

        # Write enriched fields back to day_card blocks
        enriched_by_id = {t.get("id"): t for t in enriched if isinstance(t, dict)}
        for proxy, (day_idx, block_idx) in zip(proxies, block_locations, strict=True):
            enriched_tile = enriched_by_id.get(proxy["id"])
            if not enriched_tile:
                continue
            block = day_cards[day_idx]["blocks"][block_idx]
            # Coordinates — DayCard schema expects {lat, lng} dict
            coords = enriched_tile.get("coordinates")
            if isinstance(coords, list) and len(coords) >= 2:
                block["coordinates"] = {"lng": coords[0], "lat": coords[1]}
            elif isinstance(coords, dict):
                block["coordinates"] = coords
            # Google Place ID + deeplink
            gp_id = enriched_tile.get("google_place_id")
            if gp_id:
                block["google_place_id"] = gp_id
            deeplink = enriched_tile.get("deeplink")
            if deeplink:
                block["deeplink"] = deeplink
            # Photo: signed URL from photo_name
            photo_name = (
                (enriched_tile.get("meta") or {}).get("photo_name")
                or enriched_tile.get("photo_name")
                or ""
            )
            if photo_name and session_id:
                signed_url = build_signed_photo_url(session_id, photo_name)
                if signed_url:
                    block["image_url"] = signed_url

        logger.info(
            "[coordinator] Post-build enriched %d/%d placed blocks via Google Places",
            len(enriched_by_id),
            len(proxies),
        )
    except Exception as exc:
        logger.warning("[coordinator] Post-build enrichment failed (graceful): %s", exc)


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
            "strategy_sections": strategy_sections,
            "planned_specialist_count": len(executed_topics),
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
    # Always prefer freshly-resolved IATA from logistics_node
    if graph_state.trip_plan.origin_iata:
        state["trip_plan"]["origin_iata"] = graph_state.trip_plan.origin_iata
    if graph_state.trip_plan.destination_iata:
        state["trip_plan"]["destination_iata"] = graph_state.trip_plan.destination_iata
    # Merge booking_types upgrades (flights/hotels auto-enabled by logistics_node)
    gs_settings = graph_state.metadata.get("trip_settings")
    if isinstance(gs_settings, dict):
        gs_bt = gs_settings.get("booking_types", {})
        if isinstance(gs_bt, dict):
            coord_bt = state.setdefault("trip_settings", {}).setdefault("booking_types", {})
            for key in ("flights", "hotels"):
                gs_val = gs_bt.get(key)
                if gs_val and gs_val != "off" and coord_bt.get(key) in ("off", None, ""):
                    coord_bt[key] = gs_val
    flight_status = graph_state.metadata.get("flight_search_status")
    if isinstance(flight_status, str) and flight_status:
        turn_meta["flight_search_status"] = flight_status
    if graph_state.metadata.get("hotel_filter_empty"):
        turn_meta["hotel_filter_empty"] = True
        turn_meta["hotel_filter_min_stars"] = graph_state.metadata.get("hotel_filter_min_stars")
    hotel_cascade = graph_state.metadata.get("hotel_filter_cascaded")
    if isinstance(hotel_cascade, dict):
        turn_meta["hotel_filter_cascaded"] = hotel_cascade
    if "activities" in requested_types:
        browseable = graph_state.metadata.get("browseable_activities")
        turn_meta["browseable_activities"] = browseable if isinstance(browseable, list) else []
    else:
        # Preserve existing browseable from persistent_meta (survives turn_meta reset)
        existing_browseable = state.get("persistent_meta", {}).get("browseable_activities", [])
        if existing_browseable:
            turn_meta["browseable_activities"] = existing_browseable
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

    # Local intel should run once per destination; skip if already present.
    if _has_local_intel_for_destination(state, destination):
        logger.debug("[coordinator] Local intel already present for %s — skipping", destination)
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

            _activity_settings = state.get("trip_settings", {}).get("activity_settings", {})
            _enrich = build_enrichment_closure(
                destination=destination,
                start_date=trip_plan.get("start_date"),
                end_date=trip_plan.get("end_date"),
                adults=trip_plan.get("adults", 1) or 1,
                children=trip_plan.get("children", 0) or 0,
                session_id=session_id,
                budget=trip_plan.get("budget"),
                vibe=trip_plan.get("vibe"),
                origin=trip_plan.get("origin"),
                activity_categories=_activity_settings.get("categories", [])
                if _activity_settings
                else [],
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


async def _refresh_enrichment_states(state: Dict[str, Any], session_id: str) -> None:
    """Refresh stale 'pending' enrichment states from the DB.

    Phase B runs as a background task after the SSE complete event. On the next
    turn, in-memory strategy_sections may still show 'pending' even though
    Phase B has written 'ready'/'failed' to the document. This function reads
    the latest enrichment state from the DB and patches in-memory sections.
    """
    sections = state.get("strategy_sections", [])
    if not isinstance(sections, list):
        return

    has_pending = any(
        isinstance(s, dict)
        and isinstance(s.get("local_expert_enrichment"), dict)
        and s["local_expert_enrichment"].get("state") == "pending"
        for s in sections
    )
    if not has_pending:
        return

    try:
        from app.crud_document import get_document, get_document_data
        from app.crud_trip import get_session_by_token
        from app.db import _get_async_session_factory

        async_session_factory = _get_async_session_factory()
        async with async_session_factory() as db:
            db_session = await get_session_by_token(db, session_id)
            if not db_session:
                return
            doc = await get_document(db, session=db_session)
            if not doc:
                return
            data = get_document_data(doc)
            db_sections = data.strategy_sections or []

            # Build lookup of enrichment states from DB
            db_enrichment_by_type: Dict[str, dict] = {}
            for db_sec in db_sections:
                st = getattr(db_sec, "specialist_type", None)
                enr = getattr(db_sec, "local_expert_enrichment", None)
                if st and enr:
                    enr_dict = enr if isinstance(enr, dict) else enr.model_dump()
                    if enr_dict.get("state") in ("ready", "failed"):
                        db_enrichment_by_type[st] = enr_dict

            # Patch in-memory sections
            for section in sections:
                if not isinstance(section, dict):
                    continue
                enr = section.get("local_expert_enrichment", {})
                if not isinstance(enr, dict) or enr.get("state") != "pending":
                    continue
                st = section.get("specialist_type", "")
                if st in db_enrichment_by_type:
                    section["local_expert_enrichment"] = db_enrichment_by_type[st]
                    logger.debug(
                        "[coordinator] Refreshed enrichment state for %s: %s",
                        st,
                        db_enrichment_by_type[st].get("state"),
                    )

            # If any sections still pending, Phase B may not have finished writing.
            # Brief retry to avoid a wasted turn.
            still_pending = any(
                isinstance(s, dict)
                and isinstance(s.get("local_expert_enrichment"), dict)
                and s["local_expert_enrichment"].get("state") == "pending"
                for s in sections
            )
            if still_pending:
                await asyncio.sleep(0.8)
                doc = await get_document(db, session=db_session)
                if doc:
                    data = get_document_data(doc)
                    db_sections_retry = data.strategy_sections or []
                    for db_sec in db_sections_retry:
                        st = getattr(db_sec, "specialist_type", None)
                        enr = getattr(db_sec, "local_expert_enrichment", None)
                        if st and enr:
                            enr_dict = enr if isinstance(enr, dict) else enr.model_dump()
                            if enr_dict.get("state") in ("ready", "failed"):
                                db_enrichment_by_type[st] = enr_dict
                    for section in sections:
                        if not isinstance(section, dict):
                            continue
                        enr = section.get("local_expert_enrichment", {})
                        if not isinstance(enr, dict) or enr.get("state") != "pending":
                            continue
                        st = section.get("specialist_type", "")
                        if st in db_enrichment_by_type:
                            section["local_expert_enrichment"] = db_enrichment_by_type[st]
                            logger.debug(
                                "[coordinator] Retry refreshed enrichment for %s: %s",
                                st,
                                db_enrichment_by_type[st].get("state"),
                            )
    except Exception as exc:
        logger.debug("[coordinator] Enrichment state refresh failed (non-fatal): %s", exc)


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
        logger.info(
            "[coordinator] _build_itinerary: skipped (missing: start=%s end=%s dest=%s)",
            bool(start_date),
            bool(end_date),
            bool(destination),
        )
        return None

    # Inject specialist content_added items as real tiles
    _inject_specialist_tiles_into_state(state)
    await _prepare_activity_tiles_for_build(state)

    tiles: Dict[str, Any] = state.get("tiles", {})
    strategy_sections = state.get("strategy_sections", [])

    # Need either hotels or activities to build
    if not tiles.get("hotels") and not tiles.get("activities"):
        logger.info(
            "[coordinator] _build_itinerary: skipped (no tiles: %s)",
            {k: len(v) for k, v in tiles.items() if isinstance(v, list)},
        )
        return None

    try:
        from app.services.itinerary_builder import (
            ItineraryBuilder,
            ItineraryBuilderInput,
            PreferenceOverrideInput,
        )
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

        # Build preferences from user-pinned tiles (extends itinerary_adapter
        # pattern with tile-type routing into hotel/flight/activity buckets)
        pinned_tiles = state.get("metadata", {}).get("user_pinned_tiles", {})
        preferences = None
        if pinned_tiles:
            active_cats = set(c.lower() for c in (categories or []))
            day_map: dict[str, int] = {}
            priority_map: dict[str, str] = {}
            pref_activity_ids: list[str] = []
            pref_hotel_ids: list[str] = []
            pref_flight_ids: list[str] = []
            for tid, pinned in pinned_tiles.items():
                tile_data = pinned.get("tile", pinned)
                tile_type = (tile_data.get("type") or "").lower()
                tile_cat = ((tile_data.get("meta") or {}).get("category", "") or "").lower()
                # Classify by tile type
                if tile_type == "hotel":
                    pref_hotel_ids.append(tid)
                elif tile_type == "flight":
                    pref_flight_ids.append(tid)
                else:
                    # Activity — apply category filter
                    if active_cats and tile_cat and tile_cat not in active_cats:
                        continue
                    pref_activity_ids.append(tid)
                pday = pinned.get("preferred_day")
                if pday is not None:
                    day_map[tid] = pday
                priority_map[tid] = pinned.get("priority", "high")
            if pref_activity_ids or pref_hotel_ids or pref_flight_ids:
                preferences = PreferenceOverrideInput(
                    preferred_activity_ids=pref_activity_ids,
                    preferred_hotel_ids=pref_hotel_ids,
                    preferred_flight_ids=pref_flight_ids,
                    pinned_day_map=day_map,
                    pinned_priority_map=priority_map,
                )

        day_preferences = (
            activity_settings.get("day_preferences")
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
            preferences=preferences,
            activity_categories=activity_categories,
            activity_day_preferences=day_preferences,
            activities_per_day=activities_per_day,
            adults=trip_plan.get("adults", 1) or 1,
            children=trip_plan.get("children", 0) or 0,
            user_pinned_tiles=pinned_tiles or None,
            budget=trip_plan.get("budget"),
            currency=trip_plan.get("currency", "USD"),
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
            "overview": result.overview.model_dump() if result.overview else None,
            "assumptions": result.assumptions.model_dump() if result.assumptions else None,
        }
        state["turn_meta"] = turn_meta

        if result.day_cards:
            day_cards = [card.model_dump() for card in result.day_cards]
            state["day_cards"] = day_cards
            await _post_build_enrich_placed_activities(state, day_cards)
            logger.info("[coordinator] _build_itinerary: produced %d day_cards", len(day_cards))
            return day_cards

        # Explicitly clear stale itinerary when builder returns no cards.
        logger.info("[coordinator] _build_itinerary: builder returned no day_cards")
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
            "overview": None,
            "assumptions": None,
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

    # ── Reset confirmation override ──────────────────────────────────
    if state.get("_reset_pending"):
        suggestion_chips = [
            {
                "message": "Yes, reset my trip",
                "action_type": "trigger_action",
                "action_target": "confirm_reset",
                "chip_type": "cta",
                "category": "action",
            },
            {
                "message": "No, keep planning",
                "action_type": "send_message",
                "chip_type": "follow_up",
                "category": "follow_up",
            },
        ]
        persistent_meta = (
            dict(persistent_meta) if not isinstance(persistent_meta, dict) else {**persistent_meta}
        )
        persistent_meta["suggestion_chips"] = suggestion_chips
        persistent_meta["suggestion_chip_texts"] = [c["message"] for c in suggestion_chips]
        persistent_meta["suggestion_chip_meta"] = [
            {"chip_type": c["chip_type"], "category": c["category"], "icon": None}
            for c in suggestion_chips
        ]
        state["persistent_meta"] = persistent_meta
        state.pop("_reset_pending", None)

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

    # Reconcile booking_types with actual tile presence — scoped search
    # overrides (flights="off" when not in this refresh) must not leak
    # into the envelope when tiles actually exist.
    bt = dict(trip_inputs.get("booking_types", {}))
    if tiles.get("flights") and bt.get("flights") in ("off", None):
        bt["flights"] = "suggested"
    if tiles.get("hotels") and bt.get("hotels") in ("off", None):
        bt["hotels"] = "suggested"

    # Second pass: sync from trip_settings state mutations.
    # _apply_classifier_to_state() may have upgraded booking_types (e.g.
    # flights → "suggested" on origin detection) but tiles may not exist
    # yet on this turn, so the tile-based reconciliation above misses it.
    settings_bt = trip_settings.get("booking_types", {})
    if isinstance(settings_bt, dict):
        for btype in ("flights", "hotels", "activities"):
            settings_val = settings_bt.get(btype)
            if settings_val in ("suggested", "on") and bt.get(btype) in ("off", None):
                bt[btype] = settings_val

    trip_inputs["booking_types"] = bt

    # Persist reconciled booking_types back to state for next turn
    existing_bt = trip_settings.get("booking_types", {})
    if bt != existing_bt:
        updated_ts = dict(trip_settings)
        updated_ts["booking_types"] = bt
        state["trip_settings"] = updated_ts

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
    if builder_ran and not builder_result.get("overview"):
        logger.debug(
            "[coordinator] _build_envelope: builder_ran=%s but overview missing, keys=%s",
            builder_ran,
            list(builder_result.keys()),
        )

    if not has_core:
        # Check if we have destination but just missing dates
        has_destination_only = bool(
            trip_plan.get("destination")
            and (not trip_plan.get("start_date") or not trip_plan.get("end_date"))
        )
        if has_destination_only and strategy_sections:
            plan_view_state = "S2_STRATEGY_READY"
        else:
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
    # Persist itinerary_overview and assumptions so they survive across turns where builder doesn't re-run
    if builder_ran and builder_result.get("overview"):
        persistent_meta["itinerary_overview"] = builder_result["overview"]
    if builder_ran and builder_result.get("assumptions"):
        persistent_meta["itinerary_assumptions"] = builder_result["assumptions"]
    # Persist browseable_activities so they survive turn_meta reset between turns
    browseable_from_turn = turn_meta.get("browseable_activities")
    if isinstance(browseable_from_turn, list) and browseable_from_turn:
        persistent_meta["browseable_activities"] = browseable_from_turn
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
                    flattened_tiles[str(tile_id)] = _normalize_tile_fields(tile)

    origin_just_set = bool(turn_meta.get("origin_just_set", False))
    tiles_replaced = bool(turn_meta.get("tiles_replaced", False))
    browseable_activities = turn_meta.get("browseable_activities", [])
    # Normalize deeplink → deeplink_url for browseable activities
    for ba in browseable_activities:
        if not ba.get("deeplink_url") and ba.get("deeplink"):
            ba["deeplink_url"] = ba["deeplink"]

    # Stub fix: resolve stuck "pending" local_expert_enrichment states.
    # Phase B (async enrichment) may not have completed yet on this turn.
    # If the section has populated content, mark it "ready"; if empty, "not_available".
    for section in strategy_sections:
        if not isinstance(section, dict):
            continue
        enr = section.get("local_expert_enrichment")
        if not isinstance(enr, dict) or enr.get("state") != "pending":
            continue
        has_content = bool(
            section.get("constraints_applied")
            or section.get("content_added")
            or section.get("travel_intelligence")
        )
        section["local_expert_enrichment"] = {
            **enr,
            "state": "ready" if has_content else "not_available",
        }

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
        "hotel_filter_cascaded": turn_meta.get("hotel_filter_cascaded"),
        "browseable_activities": browseable_activities,
        "can_expand_to_itinerary": bool(strategy_sections) and ready_to_generate,
        "itinerary_day_cards": (
            [] if coordinator_reset else day_cards if day_cards else ([] if builder_ran else None)
        ),
        "itinerary_overview": (
            builder_result.get("overview")
            if builder_ran
            else persistent_meta.get("itinerary_overview")
        ),
        "itinerary_assumptions": (
            builder_result.get("assumptions")
            if builder_ran
            else persistent_meta.get("itinerary_assumptions")
        ),
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
        "trip_settings": trip_settings,
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
            state["_reset_pending"] = True
        return None

    if step_type == StepType.DISPATCH_SPECIALISTS:
        topics = step.params.get("topics", [])
        is_replan = step.params.get("is_replan", False)
        preserves = step.params.get("preserves", [])
        other_plans = state.get("specialist_plans", {})
        removed_topics = {_norm_topic(t) for t in classifier.removal_targets if _norm_topic(t)}

        # Handle pre-checked infeasible specialists (skip LLM dispatch)
        prechecks = state.get("turn_meta", {}).get("feasibility_prechecks", {})
        infeasible_in_dispatch = {t: prechecks[t] for t in topics if t in prechecks}
        feasible_topics = [t for t in topics if t not in prechecks]

        if feasible_topics:
            results = await _dispatch_specialists_parallel(
                topics=feasible_topics,
                state=state,
                classifier=classifier,
                other_plans=other_plans,
                is_replan=is_replan,
                preserves=preserves,
            )
        else:
            results = {}

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

        # Build sections for infeasible specialists directly (no LLM call).
        # Placed AFTER full invalidation wipe so sections survive initial_plan/destination_change.
        if infeasible_in_dispatch:
            from app.planner.services.section_builder import build_specialist_section

            trip_plan_snap: Dict[str, Any] = state.get("trip_plan", {})
            for inf_topic, (inf_status, inf_reason, inf_alt) in infeasible_in_dispatch.items():
                section = build_specialist_section(
                    topic=inf_topic,
                    destination=trip_plan_snap.get("destination"),
                    start_date=trip_plan_snap.get("start_date"),
                    end_date=trip_plan_snap.get("end_date"),
                    feasibility_status=inf_status,
                    feasibility_reason=inf_reason,
                    alternative_suggestion=inf_alt,
                    constraints=[],
                    content_added=[],
                    enhancements=[],
                    hero_image=None,
                )
                sections = list(state.get("strategy_sections", []))
                sections = [s for s in sections if s.get("specialist_type") != inf_topic]
                sections.append(section)
                state["strategy_sections"] = sections

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
        # Snapshot tile IDs before build to detect new specialist-injected tiles
        pre_ids = {
            t.get("id")
            for cat in (state.get("tiles", {}) or {}).values()
            if isinstance(cat, list)
            for t in cat
            if isinstance(t, dict)
        }
        await _build_itinerary(state)
        # Only emit tile partial if new tiles were injected (avoids duplicate
        # re-render — SEARCH_TILES already emitted the initial set)
        post_ids = {
            t.get("id")
            for cat in (state.get("tiles", {}) or {}).values()
            if isinstance(cat, list)
            for t in cat
            if isinstance(t, dict)
        }
        if post_ids - pre_ids:
            tiles = state.get("tiles", {})
            return {
                "type": "partial",
                "data": {"kind": "tiles", "payload": _flatten_tiles_payload(tiles)},
            }
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
    _unsplash_task = None

    try:
        # Step 0: Reset turn_meta for this turn
        state["turn_meta"] = {}
        _normalize_specialist_plan_keys(state)

        # Step 1: Merge document settings
        _merge_doc_settings(state, doc_settings)

        # Step 2: Classify
        # Pre-flight: empty/whitespace messages skip the LLM entirely
        if not user_message or not user_message.strip():
            classifier = ClassifierOutput(
                intent="GREETING",
                change_type=ChangeType.GREETING,
                reasoning="Empty message — treated as greeting",
                confidence=1.0,
            )
        else:
            summary = build_trip_state_summary(state)

            from app.planner.nodes.router_extraction import classify_change

            classifier = await classify_change(user_message, summary)

        logger.info(
            "[coordinator] Classified: intent=%s change_type=%s affects=%s",
            classifier.intent,
            classifier.change_type.value,
            classifier.affects,
        )

        # Fire Unsplash prefetch as early as possible so cache is warm by tile
        # construction time (~2-5s head start vs. prefetching in _search_tiles).
        _prefetch_dest = classifier.destination or state.get("trip_plan", {}).get("destination")
        if _prefetch_dest and classifier.intent == "PLANNING":
            from app.services.unsplash import prefetch_destination_images

            _unsplash_task = asyncio.create_task(prefetch_destination_images(_prefetch_dest))
            _unsplash_task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

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
                # GENERATE_PLAN_NOW reuses existing strategy/tiles — skip clear
                if not (classifier.reasoning and "GENERATE_PLAN_NOW" in classifier.reasoning):
                    _clear_planning_artifacts(state)
            yield {
                "type": "partial",
                "data": {
                    "kind": "trip_inputs",
                    "payload": _trip_inputs_partial_payload(state),
                },
            }
        elif classifier.intent == "RESET":
            pass

        # Step 4a: Pre-check feasibility for geographic-constrained specialists.
        # Runs BEFORE plan_turn() so _compute_dispatch_list() can filter out
        # infeasible topics — preventing phantom DISPATCH_SPECIALISTS steps.
        if classifier.intent == "PLANNING":
            dest = state.get("trip_plan", {}).get("destination") or classifier.destination
            # Determine candidate topics from activity settings (same source as _compute_dispatch_list)
            activity_settings_fc = state.get("trip_settings", {}).get("activity_settings", {})
            candidate_topics = [
                c for c in activity_settings_fc.get("categories", []) if c in TIER1_SPECIALIST_NAMES
            ]
            if dest and candidate_topics:
                from app.planner.services.feasibility_service import batch_feasibility_precheck

                feasibility_prechecks = await batch_feasibility_precheck(candidate_topics, dest)
                if feasibility_prechecks:
                    state["turn_meta"]["feasibility_prechecks"] = feasibility_prechecks
                    logger.info(
                        "[coordinator] Feasibility pre-check: %s",
                        {t: s for t, (s, _, _) in feasibility_prechecks.items()},
                    )
                    # Emit SSE warnings for immediate frontend toast feedback
                    for topic, (status, reason, alternative) in feasibility_prechecks.items():
                        if status == "infeasible":
                            yield {
                                "type": "feasibility_warning",
                                "data": {
                                    "topic": topic,
                                    "status": status,
                                    "reason": reason,
                                    "alternative": alternative,
                                },
                            }

        # Build strategy sections for infeasible specialists directly (no LLM call).
        # Done here because _compute_dispatch_list filters them out of the dispatch
        # list, so _execute_step's DISPATCH_SPECIALISTS branch never sees them.
        if classifier.intent == "PLANNING":
            _fc_prechecks = state.get("turn_meta", {}).get("feasibility_prechecks", {})
            if _fc_prechecks:
                from app.planner.services.section_builder import build_specialist_section

                _tp_snap: Dict[str, Any] = state.get("trip_plan", {})
                for _fc_topic, (_fc_status, _fc_reason, _fc_alt) in _fc_prechecks.items():
                    if _fc_status != "infeasible":
                        continue
                    _fc_section = build_specialist_section(
                        topic=_fc_topic,
                        destination=_tp_snap.get("destination"),
                        start_date=_tp_snap.get("start_date"),
                        end_date=_tp_snap.get("end_date"),
                        feasibility_status=_fc_status,
                        feasibility_reason=_fc_reason,
                        alternative_suggestion=_fc_alt,
                        constraints=[],
                        content_added=[],
                        enhancements=[],
                        hero_image=None,
                    )
                    _sections = list(state.get("strategy_sections", []))
                    _sections = [s for s in _sections if s.get("specialist_type") != _fc_topic]
                    _sections.append(_fc_section)
                    state["strategy_sections"] = _sections

        # Step 4b: Plan the turn (feasibility prechecks are now available for _compute_dispatch_list)
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

        # Step 7: Await unsplash prefetch (if running), refresh enrichment, build envelope
        if _unsplash_task and not _unsplash_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(_unsplash_task), timeout=2.0)
            except (asyncio.TimeoutError, Exception):
                pass  # Fall back to placeholder gracefully
        await _refresh_enrichment_states(state, session_id)
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
