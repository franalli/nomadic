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
import json as _json
import logging
import re
import time
import uuid
from collections import defaultdict
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


def _structured_log(
    event: str,
    *,
    session_id: str = "",
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Emit a structured JSON log line for key coordinator events."""
    logger.log(
        level, "%s", _json.dumps({"event": event, "session_id": session_id, **fields}, default=str)
    )


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

_USER_DISABLED_BOOKING_TYPES_KEY = "user_disabled_booking_types"
_TRACKED_BOOKING_TYPE_KEYS = frozenset({"flights", "hotels", "activities", "ground_transport"})
_PENDING_ITINERARY_ENRICHMENT_TASK_KEY = "_pending_itinerary_enrichment_task"


# =============================================================================
# Normalization helpers
# =============================================================================


def _norm_topic(topic: str) -> str:
    """Normalize specialist topic IDs to lowercase canonical form."""
    return (topic or "").strip().lower()


def _get_user_disabled_booking_types(state: Dict[str, Any]) -> set[str]:
    """Return booking types the user explicitly disabled across turns."""
    persistent_meta = state.get("persistent_meta", {})
    if not isinstance(persistent_meta, dict):
        return set()
    raw_disabled = persistent_meta.get(_USER_DISABLED_BOOKING_TYPES_KEY, [])
    if not isinstance(raw_disabled, (list, tuple, set)):
        return set()
    return {
        key for item in raw_disabled if (key := str(item).strip()) in _TRACKED_BOOKING_TYPE_KEYS
    }


def _set_user_disabled_booking_type(
    state: Dict[str, Any],
    booking_type: str,
    disabled: bool,
) -> None:
    """Persist explicit user-disabled booking toggles in internal metadata only."""
    booking_type = str(booking_type).strip()
    if booking_type not in _TRACKED_BOOKING_TYPE_KEYS:
        return

    disabled_types = _get_user_disabled_booking_types(state)
    if disabled:
        disabled_types.add(booking_type)
    else:
        disabled_types.discard(booking_type)

    persistent_meta = state.get("persistent_meta", {})
    persistent_meta = dict(persistent_meta) if isinstance(persistent_meta, dict) else {}
    if disabled_types:
        persistent_meta[_USER_DISABLED_BOOKING_TYPES_KEY] = sorted(disabled_types)
    else:
        persistent_meta.pop(_USER_DISABLED_BOOKING_TYPES_KEY, None)
    state["persistent_meta"] = persistent_meta


def _sync_booking_type_overrides(
    state: Dict[str, Any],
    previous_settings: Dict[str, Any],
    trip_settings: Dict[str, Any],
) -> None:
    """Track explicit user flight disables without mutating public trip settings."""
    previous_booking_types = previous_settings.get("booking_types", {})
    next_booking_types = trip_settings.get("booking_types", {})
    if not isinstance(previous_booking_types, dict) or not isinstance(next_booking_types, dict):
        return

    previous_flights = previous_booking_types.get("flights")
    next_flights = next_booking_types.get("flights")
    if previous_flights == next_flights:
        return

    if next_flights == "off" and previous_flights != "off":
        _set_user_disabled_booking_type(state, "flights", True)
    elif next_flights in ("suggested", "on"):
        _set_user_disabled_booking_type(state, "flights", False)


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
        "vibe": "preferences",
    }
    canonical: List[str] = []
    for field in fields_changed:
        key = mapping.get(field)
        if key and key not in canonical:
            canonical.append(key)
    return canonical


def _resolve_activity_category_filters(
    state: Dict[str, Any],
) -> tuple[list[str], list[str] | None, list[str], bool]:
    """Return requested, effective, and infeasible activity filters for the builder."""
    trip_settings: Dict[str, Any] = state.get("trip_settings", {})
    activity_settings = trip_settings.get("activity_settings", {})
    booking_types = trip_settings.get("booking_types", {})
    activities_off = isinstance(booking_types, dict) and booking_types.get("activities") == "off"

    requested_categories: list[str] = []
    if isinstance(activity_settings, dict):
        requested_categories = [
            _norm_topic(str(category))
            for category in activity_settings.get("categories", [])
            if _norm_topic(str(category))
        ]

    if activities_off:
        return requested_categories, [], [], True

    prechecks = state.get("turn_meta", {}).get("feasibility_prechecks", {})
    infeasible_requested: list[str] = []
    effective_categories: list[str] = []
    for category in requested_categories:
        precheck = prechecks.get(category) if isinstance(prechecks, dict) else None
        status = precheck[0] if isinstance(precheck, (list, tuple)) and precheck else None
        if category in TIER1_SPECIALIST_NAMES and status == "infeasible":
            infeasible_requested.append(category)
            continue
        if category not in effective_categories:
            effective_categories.append(category)

    if requested_categories and not effective_categories:
        return requested_categories, [], infeasible_requested, False

    return requested_categories, (effective_categories or None), infeasible_requested, False


def _builder_conflicts_to_constraint_violations(
    conflicts: Any,
    resolutions: Any = None,
) -> list[Dict[str, Any]]:
    """Map builder conflicts into the existing constraint_violations shape."""
    if not isinstance(conflicts, list) or not conflicts:
        return []

    suggested_action = None
    if isinstance(resolutions, list) and resolutions:
        first_resolution = resolutions[0]
        if isinstance(first_resolution, dict):
            suggested_action = first_resolution.get("description")

    mapped: list[Dict[str, Any]] = []
    for conflict in conflicts:
        if not isinstance(conflict, dict):
            continue
        raw_severity = conflict.get("severity", "warning")
        severity = getattr(raw_severity, "value", raw_severity)
        mapped.append(
            {
                "code": str(conflict.get("type", "itinerary_conflict")).upper(),
                "message": str(conflict.get("message", "Itinerary conflict detected")),
                "severity": str(severity).lower(),
                "category": "itinerary",
                "rule": str(conflict.get("type", "itinerary_conflict")),
                "suggested_action": suggested_action,
            }
        )
    return mapped


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
        ChangeType.DAY_COUNT,
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


def _flatten_tiles_payload_filtered(
    tiles: Dict[str, Any],
    categories: tuple[str, ...],
) -> Dict[str, Any]:
    """Flatten only specified category keys into ID-keyed map."""
    return _flatten_tiles_payload({k: v for k, v in tiles.items() if k in categories})


def _pre_sign_envelope_photos(
    tiles: Dict[str, Any],
    day_cards: list,
    browseable_activities: list,
    session_id: str,
) -> None:
    """Sign all raw photo_name references in-place before envelope emission.

    Covers hotel tiles, browseable activities, and day-card blocks that may
    carry a ``photo_name`` without a signed ``image_url``.  Activity tiles are
    already signed by ``_prepare_activity_tiles_for_build``; this catches the
    remaining surfaces.  Pure HMAC computation — zero network calls.
    """
    if not session_id:
        return
    from app.tile_service.google_places_provider import build_signed_photo_url

    def _sign(tile: dict) -> None:
        if not isinstance(tile, dict):
            return
        photo_name = (tile.get("meta") or {}).get("photo_name") or tile.get("photo_name") or ""
        if photo_name and not (tile.get("image_url") or "").startswith("/api/media/"):
            signed = build_signed_photo_url(session_id, photo_name)
            if signed:
                tile["image_url"] = signed

    for category_tiles in tiles.values():
        if not isinstance(category_tiles, list):
            continue
        for tile in category_tiles:
            _sign(tile)

    for ba in browseable_activities:
        _sign(ba)

    for card in day_cards:
        if not isinstance(card, dict):
            continue
        for block in card.get("blocks", []):
            if not isinstance(block, dict):
                continue
            booked = block.get("booked_tile")
            if isinstance(booked, dict):
                _sign(booked)
            _sign(block)


def _compute_trip_cost_estimate(
    tiles: Dict[str, Any],
    day_cards: list,
    trip_plan: Dict[str, Any],
) -> Dict[str, Any] | None:
    """Compute trip cost estimate from tile prices.  Pure arithmetic, no LLM."""
    adults = trip_plan.get("adults", 1) or 1
    trip_nights = max(0, len(day_cards) - 1) if day_cards else 0
    currency = trip_plan.get("currency", "USD")

    # Use selected hotel if set (frontend action), otherwise cheapest available.
    hotel_cost = 0.0
    best_hotel_price = float("inf")
    for ht in tiles.get("hotels") or []:
        if not isinstance(ht, dict):
            continue
        hp = ht.get("price_estimate") or ht.get("live_price") or 0
        try:
            hp = float(hp)
        except (ValueError, TypeError):
            hp = 0
        if hp <= 0:
            continue
        is_selected = ht.get("selected")
        if is_selected:
            best_hotel_price = hp
            break
        if hp < best_hotel_price:
            best_hotel_price = hp
    if best_hotel_price < float("inf"):
        basis = "per_night"  # default hotel pricing
        hotel_cost = best_hotel_price * trip_nights if basis == "per_night" else best_hotel_price

    flight_cost = 0.0
    flight_tiles = tiles.get("flights") or []
    if flight_tiles:
        prices: list[float] = []
        for ft in flight_tiles:
            if not isinstance(ft, dict):
                continue
            fp = ft.get("price_estimate") or 0
            try:
                fp = float(fp)
            except (ValueError, TypeError):
                fp = 0
            if fp > 0:
                prices.append(fp)
        if prices:
            ft0 = flight_tiles[0] if isinstance(flight_tiles[0], dict) else {}
            basis = ft0.get("price_basis", "per_person")
            cheapest = min(prices)
            flight_cost = cheapest * adults if basis == "per_person" else cheapest

    activity_cost = 0.0
    activity_count = 0
    for at in tiles.get("activities") or []:
        if not isinstance(at, dict):
            continue
        ap = at.get("price_estimate") or 0
        try:
            ap = float(ap)
        except (ValueError, TypeError):
            ap = 0
        if ap > 0:
            basis = at.get("price_basis", "per_person")
            activity_cost += ap * adults if basis == "per_person" else ap
            activity_count += 1

    total = hotel_cost + flight_cost + activity_cost
    if total <= 0:
        return None

    return {
        "hotel_total": round(hotel_cost, 2) if hotel_cost else None,
        "hotel_per_night": round(hotel_cost / trip_nights, 2)
        if hotel_cost and trip_nights
        else None,
        "flight_total": round(flight_cost, 2) if flight_cost else None,
        "activities_total": round(activity_cost, 2),
        "activity_count": activity_count,
        "estimated_total": round(total, 2),
        "currency": currency,
        "note": "Excludes meals and local transport",
    }


def _requested_specialist_topics(topics: List[str]) -> List[str]:
    """Return normalized requested specialist topics in first-seen order."""
    requested_topics: List[str] = []
    for topic in topics:
        normalized = _norm_topic(topic)
        if normalized and normalized not in requested_topics:
            requested_topics.append(normalized)
    return requested_topics


def _ordered_requested_specialist_plans(
    specialist_plans: Dict[str, Any],
    topics: List[str],
) -> Dict[str, Any]:
    """Keep dispatched specialist plans in requested topic order."""
    requested_topics = _requested_specialist_topics(topics)
    if not requested_topics:
        return dict(specialist_plans)

    topic_filter = set(requested_topics)
    ordered_plans = {
        topic: plan
        for topic, plan in specialist_plans.items()
        if _norm_topic(topic) not in topic_filter
    }

    for topic in requested_topics:
        if topic in specialist_plans:
            ordered_plans[topic] = specialist_plans[topic]

    return ordered_plans


def _ordered_requested_specialist_sections(
    sections: List[Any],
    topics: List[str],
) -> List[Any]:
    """Keep dispatched specialist sections in requested topic order."""
    requested_topics = _requested_specialist_topics(topics)
    if not requested_topics:
        return list(sections)

    topic_filter = set(requested_topics)
    base_sections: List[Any] = []
    requested_sections: Dict[str, Any] = {}

    for section in sections:
        if not isinstance(section, dict):
            base_sections.append(section)
            continue

        topic = _norm_topic(section.get("specialist_type", ""))
        if topic in topic_filter:
            requested_sections[topic] = section
            continue
        base_sections.append(section)

    return base_sections + [
        requested_sections[topic] for topic in requested_topics if topic in requested_sections
    ]


def _specialist_preview_payload(
    state: Dict[str, Any],
    topics: List[str],
) -> Dict[str, Any]:
    """Build a frontend-friendly preview payload for freshly dispatched specialists."""
    requested_topics = _requested_specialist_topics(topics)
    topic_filter = set(requested_topics)
    preview_activities: List[Dict[str, Any]] = []
    previews: List[Dict[str, Any]] = []

    for section in state.get("strategy_sections", []):
        if not isinstance(section, dict):
            continue

        topic = _norm_topic(section.get("specialist_type", ""))
        if not topic or topic not in topic_filter:
            continue

        content_added = section.get("content_added", [])
        content_items = content_added if isinstance(content_added, list) else []
        highlights = [
            str(item.get("title", "")).strip()
            for item in content_items
            if isinstance(item, dict) and str(item.get("title", "")).strip()
        ]
        for item in content_items:
            if not isinstance(item, dict) or item.get("is_buffer"):
                continue

            title = str(item.get("title", "")).strip()
            if not title:
                continue

            preview_activities.append(
                {
                    "title": title,
                    "day": item.get("day"),
                    "specialist_type": topic,
                    "duration_hours": item.get("duration_hours", 3),
                    "description": item.get("description"),
                    "image_url": item.get("image_url"),
                    "coordinates": item.get("coordinates"),
                }
            )

        previews.append(
            {
                "id": section.get("id"),
                "specialist_type": topic,
                "title": section.get("title"),
                "one_liner": section.get("one_liner"),
                "hero_image": section.get("hero_image"),
                "feasibility_status": section.get("feasibility_status"),
                "feasibility_reason": section.get("feasibility_reason"),
                "alternative_suggestion": section.get("alternative_suggestion"),
                "content_count": len(content_items),
                "highlights": highlights[:3],
            }
        )

    return {
        "destination": state.get("trip_plan", {}).get("destination"),
        "topics": requested_topics,
        "activities": preview_activities,
        "sections": previews,
        "strategy_sections": state.get("strategy_sections", []),
    }


def _partial_plan_view_state(
    state: Dict[str, Any],
    day_cards: list[Dict[str, Any]],
) -> str | None:
    """Resolve the best available plan state for progressive itinerary payloads."""
    turn_meta = state.get("turn_meta")
    if isinstance(turn_meta, dict) and turn_meta.get("builder_result"):
        return _compute_coordinator_s3_state(turn_meta, day_cards)
    if day_cards:
        return "S3_ITINERARY_READY"
    return "S3_BLOCKED"


def _day_cards_partial_context(
    state: Dict[str, Any],
    day_cards: list[Dict[str, Any]],
) -> Dict[str, Any] | None:
    """Expose envelope-adjacent itinerary context on progressive day-card partials."""
    turn_meta = state.get("turn_meta", {})
    if not isinstance(turn_meta, dict):
        return None

    builder_result = turn_meta.get("builder_result")
    if not isinstance(builder_result, dict) or not builder_result:
        return None

    context: Dict[str, Any] = {
        "plan_view_state": _partial_plan_view_state(state, day_cards),
        "itinerary_overview": builder_result.get("overview"),
        "itinerary_assumptions": builder_result.get("assumptions"),
    }

    constraint_violations = _builder_conflicts_to_constraint_violations(
        builder_result.get("conflicts"),
        builder_result.get("resolutions"),
    )
    if constraint_violations:
        context["constraint_violations"] = constraint_violations

    warnings = builder_result.get("warnings")
    if isinstance(warnings, list) and warnings:
        context["warnings"] = warnings

    return {key: value for key, value in context.items() if value is not None}


def _day_cards_partial_payload(
    state: Dict[str, Any],
    day_cards: list[Dict[str, Any]],
    *,
    tiles_payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build the rich itinerary payload consumed by progressive frontend renders."""
    payload: Dict[str, Any] = {
        "day_cards": day_cards,
        "tiles": tiles_payload
        if tiles_payload is not None
        else _flatten_tiles_payload(state.get("tiles", {})),
        "strategy_sections": state.get("strategy_sections", []),
    }

    plan_view_state = _partial_plan_view_state(state, day_cards)
    if plan_view_state is not None:
        payload["plan_view_state"] = plan_view_state

    context = _day_cards_partial_context(state, day_cards)
    if context:
        payload.update(context)

    return payload


def _day_cards_partial_event(
    state: Dict[str, Any],
    day_cards: list[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build the progressive itinerary partial emitted immediately after the builder."""
    return {
        "type": "partial",
        "data": {
            "kind": "day_cards",
            "payload": _day_cards_partial_payload(state, day_cards),
        },
    }


def _tile_enrichment_partial_event(
    state: Dict[str, Any],
    day_cards: list[Dict[str, Any]],
    tiles_payload: Dict[str, Any],
    *,
    day_cards_changed: bool,
    tiles_changed: bool,
) -> Dict[str, Any] | None:
    """Build a dedicated post-response enrichment partial."""
    if not day_cards_changed and not tiles_changed:
        return None

    partial_data: Dict[str, Any] = {
        "kind": "tile_enrichment",
        "payload": _day_cards_partial_payload(
            state,
            day_cards,
            tiles_payload=tiles_payload,
        ),
    }
    partial_data["payload"]["day_cards_changed"] = day_cards_changed
    partial_data["payload"]["tiles_changed"] = tiles_changed

    turn_meta = state.get("turn_meta") or {}
    if turn_meta.get("tiles_replaced"):
        partial_data["tiles_replaced"] = True

    return {"type": "partial", "data": partial_data}


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


def _should_clear_planning_artifacts(
    classifier: ClassifierOutput,
    state: Dict[str, Any],
) -> bool:
    """Return True when full-invalidation turns should wipe derived artifacts.

    No-op turns must preserve existing strategy/itinerary long enough for the
    `plan_turn()` reuse guards to short-circuit before any rebuild work starts.
    """
    if classifier.change_type not in _FULL_INVALIDATION_CHANGES:
        return False

    turn_meta = state.get("turn_meta", {})
    raw_fields_changed = turn_meta.get("fields_changed", []) if isinstance(turn_meta, dict) else []
    fields_changed = raw_fields_changed if isinstance(raw_fields_changed, list) else []
    if not fields_changed:
        return False

    categories_changed = "activity_categories" in fields_changed
    dates_changed = any(f in fields_changed for f in ("start_date", "end_date"))
    is_gpn = bool(classifier.reasoning and "GENERATE_PLAN_NOW" in classifier.reasoning)
    return not is_gpn or categories_changed or dates_changed


def _is_response_only_plan(plan: ExecutionPlan) -> bool:
    """Return True when a planning turn can skip all rebuild work."""
    return [step.step_type for step in plan.steps] == [StepType.GENERATE_RESPONSE]


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
        # Fetch local intel only when (a) destination is known, (b) the question is
        # destination-related (question_type set by router, or specialist_hints detected),
        # and (c) no local_expert section for this destination is already cached.
        _q_destination = classifier.destination or (state.get("trip_plan") or {}).get("destination")
        _q_has_local = _has_local_intel_for_destination(state, _q_destination)
        _q_is_dest_question = bool(
            classifier.question_type or (classifier.specialist_hints and _q_destination)
        )
        q_steps: List[ExecutionStep] = []
        if _q_destination and _q_is_dest_question and not _q_has_local:
            q_steps.append(ExecutionStep(step_type=StepType.LOCAL_INTEL))
        q_steps.append(ExecutionStep(step_type=StepType.GENERATE_RESPONSE))
        return ExecutionPlan(
            steps=q_steps,
            reason="Question — enrich with local intel if destination-related and not yet cached",
            estimated_llm_calls=1,  # LOCAL_INTEL Phase B is deferred; only GENERATE_RESPONSE is synchronous
            estimated_wall_ms=1000 if len(q_steps) > 1 else 800,
        )

    # Short-circuit GENERATE_PLAN_NOW when planning artifacts already exist.
    # Two tiers:
    #   - day_cards present  → skip to GENERATE_RESPONSE only (full itinerary ready)
    #   - strategy_sections present but no day_cards → skip specialists/local_intel,
    #     run SEARCH_TILES + BUILD_ITINERARY + GENERATE_RESPONSE
    _gpn_fields_changed = state.get("turn_meta", {}).get("fields_changed", [])
    categories_changed = "activity_categories" in _gpn_fields_changed
    dates_changed = any(f in _gpn_fields_changed for f in ("start_date", "end_date"))
    if (
        change_type == ChangeType.INITIAL_PLAN
        and classifier.reasoning
        and "GENERATE_PLAN_NOW" in classifier.reasoning
        and not categories_changed
        and not dates_changed
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
        tile_types = _tile_refresh_types(classifier, state)
        # No activity tiles yet + user has categories → force-include activities
        # so the first "dates added" turn doesn't skip the activity pipeline.
        if "activities" not in tile_types:
            existing_tiles = state.get("tiles", {})
            if not existing_tiles.get("activities"):
                act_settings = state.get("trip_settings", {}).get("activity_settings", {})
                if isinstance(act_settings, dict) and act_settings.get("categories"):
                    tile_types = [*tile_types, "activities"]
        # Tiles can run in parallel with specialists when both are needed,
        # EXCEPT for swap/add where specialists must update categories first
        parallel_with = StepType.DISPATCH_SPECIALISTS if dispatch_list else None
        if dispatch_list and change_type in (ChangeType.SWAP_ACTIVITY, ChangeType.ADD_ACTIVITY):
            parallel_with = None  # Force sequential: specialists → tiles
        # Single SEARCH_TILES step with all tile_types — logistics_node.py
        # already runs hotels + activities concurrently via asyncio.gather,
        # so splitting into sequential steps only adds overhead.
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

    if classifier.change_type == ChangeType.DATE_CHANGE:
        existing_plans: Dict[str, Any] = state.get("specialist_plans", {})
        dispatch_topics: set[str] = set()
        existing_topics = {_norm_topic(topic) for topic in existing_plans}
        preserved_topics: set[str] = set()

        for topic, plan in existing_plans.items():
            topic_norm = _norm_topic(topic)
            if topic_norm not in TIER1_SPECIALIST_NAMES:
                continue
            if _should_preserve_specialist_for_date_change(topic_norm, plan, state):
                preserved_topics.add(topic_norm)
                continue
            dispatch_topics.add(topic_norm)

        for topic in tier1_active:
            if topic not in existing_topics and topic not in removed_topics:
                dispatch_topics.add(topic)

        if classifier.affects:
            for topic in classifier.affects:
                topic_norm = _norm_topic(topic)
                if (
                    topic_norm in TIER1_SPECIALIST_NAMES
                    and topic_norm not in removed_topics
                    and topic_norm not in preserved_topics
                ):
                    dispatch_topics.add(topic_norm)

        return sorted(dispatch_topics)

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


def _active_specialist_topics(state: Dict[str, Any]) -> set[str]:
    """Collect current specialist topics from persisted trip state."""
    topics: set[str] = set()

    trip_settings = state.get("trip_settings", {})
    activity_settings = trip_settings.get("activity_settings", {})
    if isinstance(activity_settings, dict):
        topics.update(
            _norm_topic(value)
            for value in activity_settings.get("categories", [])
            if _norm_topic(value)
        )

    for section in state.get("strategy_sections", []):
        if not isinstance(section, dict):
            continue
        topic = _norm_topic(section.get("specialist_type", ""))
        if topic:
            topics.add(topic)

    specialist_plans = state.get("specialist_plans", {})
    if isinstance(specialist_plans, dict):
        topics.update(_norm_topic(topic) for topic in specialist_plans if _norm_topic(topic))

    return {topic for topic in topics if topic in SPECIALIST_REGISTRY}


def _has_current_or_future_nofly_specialist(
    classifier: ClassifierOutput,
    state: Dict[str, Any],
) -> bool:
    """Return True when the current or resulting plan includes a no-fly specialist."""
    nofly_topics = {
        topic for topic, config in SPECIALIST_REGISTRY.items() if config.has_nofly_buffer
    }
    if not nofly_topics:
        return False

    current_topics = _active_specialist_topics(state)
    next_topics = set(current_topics)
    for values in (
        classifier.affects,
        classifier.preserves,
        classifier.specialist_hints,
        classifier.activity_categories,
    ):
        next_topics.update(_norm_topic(value) for value in values if _norm_topic(value))
    for target in classifier.removal_targets:
        next_topics.discard(_norm_topic(target))

    return bool((current_topics & nofly_topics) or (next_topics & nofly_topics))


def _classifier_has_activity_refresh_signal(classifier: ClassifierOutput) -> bool:
    """Return True when activity tiles should be recomputed for this change."""
    return bool(
        classifier.activity_categories
        or classifier.specialist_hints
        or classifier.affects
        or classifier.removal_targets
        or classifier.activity_day_preferences
        or classifier.activities_per_day is not None
    )


def _should_allow_flight_auto_upgrade(
    classifier: ClassifierOutput,
    state: Dict[str, Any],
    requested_types: set[str],
) -> bool:
    """Allow flight auto-upgrade only on origin/logistics flows, not safety refreshes."""
    if "flights" not in requested_types:
        return False
    if "flights" in _get_user_disabled_booking_types(state):
        return False

    turn_meta = state.get("turn_meta", {})
    if isinstance(turn_meta, dict) and turn_meta.get("origin_just_set"):
        return True

    trip_plan = state.get("trip_plan", {})
    has_origin = isinstance(trip_plan, dict) and bool(trip_plan.get("origin"))

    if classifier.change_type in (
        ChangeType.INITIAL_PLAN,
        ChangeType.DESTINATION_CHANGE,
        ChangeType.LOGISTICS,
    ):
        return has_origin

    return classifier.change_type == ChangeType.SETTINGS and (
        classifier.flight_direct_only is not None or bool(classifier.flight_cabin_class)
    )


def _tile_refresh_types(
    classifier: ClassifierOutput,
    state: Dict[str, Any],
) -> List[str]:
    """Which tile types to refresh."""
    ct = classifier.change_type
    if ct in (ChangeType.INITIAL_PLAN, ChangeType.DESTINATION_CHANGE):
        return ["flights", "hotels", "activities"]
    if ct == ChangeType.DAY_COUNT:
        return ["activities", "flights", "hotels"]
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
        types = ["activities"]
        if _has_current_or_future_nofly_specialist(classifier, state):
            types.append("flights")
        return types
    if ct == ChangeType.PREFERENCE:
        types: List[str] = []
        if _classifier_has_activity_refresh_signal(classifier):
            types.append("activities")
        if classifier.activities_per_day is not None and "activities" not in types:
            types.append("activities")
        if types and _has_current_or_future_nofly_specialist(classifier, state):
            types.append("flights")
        return types
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


def _specialist_month_bucket(start_date: str | None, end_date: str | None) -> str | None:
    """Return the specialist cache month bucket for a date range."""
    if not start_date or not end_date:
        return None
    try:
        start = datetime.strptime(str(start_date)[:10], "%Y-%m-%d").date()
        end = datetime.strptime(str(end_date)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    if end < start:
        end = start
    midpoint = start + (end - start) / 2
    return f"{midpoint.year}-{midpoint.month:02d}"


def _normalize_activity_settings_for_date_continuity(activity_settings: Any) -> Dict[str, Any]:
    """Normalize activity settings for date-continuity comparisons."""
    if not isinstance(activity_settings, dict):
        return {}

    categories = activity_settings.get("categories", [])
    normalized_categories = sorted(
        _norm_topic(category) for category in categories if _norm_topic(category)
    )

    day_preferences = activity_settings.get("day_preferences", {})
    if not isinstance(day_preferences, dict):
        day_preferences = {}
    normalized_day_preferences = {
        _norm_topic(topic): value for topic, value in day_preferences.items() if _norm_topic(topic)
    }

    skill_level = activity_settings.get("skill_level")
    normalized_skill_level = str(skill_level).strip().lower() if skill_level else None

    return {
        "categories": normalized_categories,
        "day_preferences": normalized_day_preferences,
        "activities_per_day": activity_settings.get("activities_per_day"),
        "skill_level": normalized_skill_level,
    }


def _specialist_target_count_from_inputs(
    topic: str,
    trip_plan: Dict[str, Any],
    trip_settings: Dict[str, Any],
) -> Optional[int]:
    """Compute the coordinator brief target for a specialist from raw state inputs."""
    activity_settings = trip_settings.get("activity_settings", {})
    if not isinstance(activity_settings, dict):
        activity_settings = {}
    day_preferences = activity_settings.get("day_preferences", {})
    if not isinstance(day_preferences, dict):
        day_preferences = {}
    apd = activity_settings.get("activities_per_day") or 2
    if not isinstance(apd, int):
        apd = 2
    num_days = _compute_num_days(
        str(trip_plan.get("start_date") or ""),
        str(trip_plan.get("end_date") or ""),
    )
    return _scaled_target(day_preferences.get(topic), apd, num_days)


def _parse_trip_date_range(trip_plan: Dict[str, Any]) -> tuple[Any, Any] | None:
    """Parse and normalize a trip date range into date objects."""
    start_date = trip_plan.get("start_date")
    end_date = trip_plan.get("end_date")
    if not start_date or not end_date:
        return None
    try:
        start = datetime.strptime(str(start_date)[:10], "%Y-%m-%d").date()
        end = datetime.strptime(str(end_date)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    if end < start:
        end = start
    return start, end


def _specialist_trip_duration_days(trip_plan: Dict[str, Any]) -> int:
    """Return exact trip duration days for specialist reuse checks."""
    return _compute_num_days(
        str(trip_plan.get("start_date") or ""),
        str(trip_plan.get("end_date") or ""),
    )


def _has_reusable_specialist_content(topic: str, plan: Any, state: Dict[str, Any]) -> bool:
    """Return True when an existing specialist plan has content worth preserving."""
    if isinstance(plan, dict):
        day_plans = plan.get("day_plans", [])
        if isinstance(day_plans, list) and any(isinstance(dp, dict) for dp in day_plans):
            return True

    for section in state.get("strategy_sections", []):
        if not isinstance(section, dict):
            continue
        if _norm_topic(section.get("specialist_type", "")) != topic:
            continue
        if section.get("feasibility_status") == "infeasible":
            continue
        content_added = section.get("content_added", [])
        if isinstance(content_added, list) and content_added:
            return True

    return False


def _is_pure_tail_extension(
    previous_trip_plan: Dict[str, Any],
    current_trip_plan: Dict[str, Any],
) -> bool:
    """Return True when the new dates extend the existing trip at the tail only."""
    previous_range = _parse_trip_date_range(previous_trip_plan)
    current_range = _parse_trip_date_range(current_trip_plan)
    if not previous_range or not current_range:
        return False

    previous_destination = str(previous_trip_plan.get("destination") or "").strip().lower()
    current_destination = str(current_trip_plan.get("destination") or "").strip().lower()
    if not previous_destination or previous_destination != current_destination:
        return False

    previous_start, previous_end = previous_range
    current_start, current_end = current_range
    return current_start == previous_start and current_end > previous_end


def _should_preserve_specialist_for_date_change(
    topic: str,
    plan: Any,
    state: Dict[str, Any],
) -> bool:
    """Keep an existing specialist plan on safe continuity-preserving date changes."""
    if not isinstance(plan, dict) or not plan:
        return False

    pre_change = state.get("_pre_change_briefs")
    if not isinstance(pre_change, dict):
        return False

    previous_trip_plan = pre_change.get("trip_plan", {})
    previous_trip_settings = pre_change.get("trip_settings", {})
    current_trip_plan = state.get("trip_plan", {})
    current_trip_settings = state.get("trip_settings", {})
    if not isinstance(previous_trip_plan, dict) or not isinstance(previous_trip_settings, dict):
        return False
    if not isinstance(current_trip_plan, dict) or not isinstance(current_trip_settings, dict):
        return False

    previous_bucket = _specialist_month_bucket(
        previous_trip_plan.get("start_date"),
        previous_trip_plan.get("end_date"),
    )
    current_bucket = _specialist_month_bucket(
        current_trip_plan.get("start_date"),
        current_trip_plan.get("end_date"),
    )
    if not previous_bucket or previous_bucket != current_bucket:
        return False

    previous_target = _specialist_target_count_from_inputs(
        topic,
        previous_trip_plan,
        previous_trip_settings,
    )
    current_target = _specialist_target_count_from_inputs(
        topic,
        current_trip_plan,
        current_trip_settings,
    )
    if previous_target != current_target:
        return False

    previous_duration = _specialist_trip_duration_days(previous_trip_plan)
    current_duration = _specialist_trip_duration_days(current_trip_plan)
    if previous_duration == current_duration:
        return True
    if current_duration < previous_duration:
        return False

    return _is_pure_tail_extension(
        previous_trip_plan,
        current_trip_plan,
    ) and _has_reusable_specialist_content(topic, plan, state)


def _refresh_preserved_specialist_section_metadata(
    state: Dict[str, Any],
    topics: List[str],
) -> None:
    """Refresh cache metadata on preserved specialist sections after date changes."""
    target_topics = {_norm_topic(topic) for topic in topics if _norm_topic(topic)}
    if not target_topics:
        return

    trip_plan = state.get("trip_plan", {})
    trip_settings = state.get("trip_settings", {})
    if not isinstance(trip_plan, dict) or not isinstance(trip_settings, dict):
        return

    start_date = trip_plan.get("start_date")
    end_date = trip_plan.get("end_date")
    if not start_date or not end_date:
        return

    activity_settings = trip_settings.get("activity_settings", {})
    if not isinstance(activity_settings, dict):
        activity_settings = {}
    day_preferences = activity_settings.get("day_preferences", {})
    if not isinstance(day_preferences, dict):
        day_preferences = {}

    current_dates = f"{start_date}:{end_date}"
    destination = trip_plan.get("destination")
    skill_level = activity_settings.get("skill_level")

    sections = state.get("strategy_sections", [])
    if not isinstance(sections, list):
        return

    for section in sections:
        if not isinstance(section, dict):
            continue
        topic = _norm_topic(section.get("specialist_type", ""))
        if topic not in target_topics:
            continue
        section["subtitle"] = destination
        section["_cache_dates"] = current_dates
        section["_cache_day_pref"] = day_preferences.get(topic)
        section["_cache_skill_level"] = skill_level


def _date_change_continuity_details(
    classifier: ClassifierOutput,
    state: Dict[str, Any],
    plan: ExecutionPlan,
) -> Optional[Dict[str, Any]]:
    """Summarize whether a DATE_CHANGE preserved safe trip continuity."""
    if classifier.change_type != ChangeType.DATE_CHANGE:
        return None

    pre_change = state.get("_pre_change_briefs")
    previous_trip_plan = pre_change.get("trip_plan", {}) if isinstance(pre_change, dict) else {}
    previous_trip_settings = (
        pre_change.get("trip_settings", {}) if isinstance(pre_change, dict) else {}
    )
    current_trip_plan = state.get("trip_plan", {})
    current_trip_settings = state.get("trip_settings", {})

    same_month_bucket = False
    same_activity_settings = False
    safe_tail_extension = False
    if (
        isinstance(previous_trip_plan, dict)
        and isinstance(previous_trip_settings, dict)
        and isinstance(current_trip_plan, dict)
        and isinstance(current_trip_settings, dict)
    ):
        previous_bucket = _specialist_month_bucket(
            previous_trip_plan.get("start_date"),
            previous_trip_plan.get("end_date"),
        )
        current_bucket = _specialist_month_bucket(
            current_trip_plan.get("start_date"),
            current_trip_plan.get("end_date"),
        )
        same_month_bucket = bool(previous_bucket and previous_bucket == current_bucket)
        same_activity_settings = _normalize_activity_settings_for_date_continuity(
            previous_trip_settings.get("activity_settings")
        ) == _normalize_activity_settings_for_date_continuity(
            current_trip_settings.get("activity_settings")
        )
        safe_tail_extension = (
            same_month_bucket
            and same_activity_settings
            and _is_pure_tail_extension(previous_trip_plan, current_trip_plan)
        )

    dispatch_topics: set[str] = set()
    preserve_topics = {_norm_topic(topic) for topic in _compute_preserve_list(classifier, state)}
    preserve_topics.discard("")
    for step in plan.steps:
        if step.step_type != StepType.DISPATCH_SPECIALISTS:
            continue
        params = step.params if isinstance(step.params, dict) else {}
        dispatch_topics.update(
            _norm_topic(topic) for topic in params.get("topics", []) if _norm_topic(topic)
        )
        preserve_topics.update(
            _norm_topic(topic) for topic in params.get("preserves", []) if _norm_topic(topic)
        )

    return {
        "safe_tail_extension": safe_tail_extension,
        "same_month_bucket": same_month_bucket,
        "same_activity_settings": same_activity_settings,
        "dispatch": sorted(dispatch_topics),
        "preserve": sorted(preserve_topics),
    }


def _normalize_activity_title_key(value: Any) -> str:
    """Normalize activity/block titles for post-build tile matching."""
    if not isinstance(value, str):
        return ""
    normalized = value.strip().lower().replace("&", " and ")
    normalized = re.sub(r"\s*\([^)]*\)\s*$", "", normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _normalize_activity_exact_title_key(value: Any) -> str:
    """Normalize titles conservatively for exact-title rehydration matching."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().lower().split())


def _apply_activity_tile_enrichment_to_day_cards(
    activity_tiles: list[Dict[str, Any]],
    day_cards: list[Dict[str, Any]],
) -> None:
    """Patch itinerary blocks from enriched activity tiles after the builder returns.

    Builder normally inherits deeplinks/images from already-enriched tiles. When
    partner enrichment moves off the pre-builder path, we need a post-build pass
    to rehydrate those affiliate fields on the rendered blocks before the final
    envelope is emitted.
    """
    if not activity_tiles or not day_cards:
        return

    def _provider_priority(tile: Dict[str, Any]) -> int:
        provider = str(tile.get("provider") or "").lower()
        partner = str(tile.get("partner") or "").lower()
        if provider == "viator" or partner == "viator":
            return 3
        if provider == "gyg" or partner in {"gyg", "getyourguide", "get_your_guide"}:
            return 2
        if partner:
            return 1
        return 0

    tile_by_id: dict[str, Dict[str, Any]] = {}
    tile_by_partner_product_id: dict[str, Dict[str, Any]] = {}
    exact_title_candidates: dict[str, list[Dict[str, Any]]] = defaultdict(list)
    relaxed_title_candidates: dict[str, list[Dict[str, Any]]] = defaultdict(list)
    for tile in activity_tiles:
        if not isinstance(tile, dict):
            continue
        tile_id = str(tile.get("id") or "").strip()
        if tile_id:
            tile_by_id[tile_id] = tile
        partner_product_id = str(tile.get("partner_product_id") or "").strip()
        if partner_product_id:
            existing = tile_by_partner_product_id.get(partner_product_id)
            if existing is None or _provider_priority(tile) > _provider_priority(existing):
                tile_by_partner_product_id[partner_product_id] = tile

        exact_title_key = _normalize_activity_exact_title_key(tile.get("title"))
        if exact_title_key:
            exact_title_candidates[exact_title_key].append(tile)
        title_key = _normalize_activity_title_key(tile.get("title"))
        if title_key:
            relaxed_title_candidates[title_key].append(tile)

    def _select_unique_title_matches(
        candidates: dict[str, list[Dict[str, Any]]],
    ) -> dict[str, Dict[str, Any]]:
        unique_matches: dict[str, Dict[str, Any]] = {}
        for key, tiles_for_key in candidates.items():
            unique_ids = {
                str(tile.get("id") or tile.get("partner_product_id") or "").strip()
                for tile in tiles_for_key
            }
            unique_ids.discard("")
            if len(unique_ids) > 1:
                continue
            unique_matches[key] = max(tiles_for_key, key=_provider_priority)
        return unique_matches

    tile_by_exact_title = _select_unique_title_matches(exact_title_candidates)
    tile_by_title = _select_unique_title_matches(relaxed_title_candidates)

    for card in day_cards:
        if not isinstance(card, dict):
            continue
        blocks = card.get("blocks", [])
        if not isinstance(blocks, list):
            continue

        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("is_buffer"):
                continue
            if block.get("activity_type") == "free_day":
                continue

            block_id = str(block.get("id") or "").strip()
            tile = tile_by_id.get(block_id) if block_id else None
            booked_tile = block.get("booked_tile")
            if tile is None and isinstance(booked_tile, dict):
                booked_tile_id = str(booked_tile.get("id") or "").strip()
                if booked_tile_id:
                    tile = tile_by_id.get(booked_tile_id)
            if tile is None and isinstance(booked_tile, dict):
                partner_product_id = str(booked_tile.get("partner_product_id") or "").strip()
                if partner_product_id:
                    tile = tile_by_partner_product_id.get(partner_product_id)
            if tile is None:
                title_candidates = []
                if isinstance(booked_tile, dict):
                    title_candidates.append(booked_tile.get("title"))
                title_candidates.append(block.get("summary"))
                for candidate in title_candidates:
                    exact_title_key = _normalize_activity_exact_title_key(candidate)
                    if exact_title_key:
                        tile = tile_by_exact_title.get(exact_title_key)
                    if tile is not None:
                        break
                    title_key = _normalize_activity_title_key(candidate)
                    if not title_key:
                        continue
                    tile = tile_by_title.get(title_key)
                    if tile is not None:
                        break
            if tile is None:
                continue

            partner_override = _provider_priority(tile) >= 2
            tile_deeplink = tile.get("deeplink") or tile.get("deeplink_url") or tile.get("maps_uri")
            tile_image = tile.get("image_url")
            tile_coords = tile.get("coordinates")
            tile_geo = tile.get("geo") or (tile.get("meta") or {}).get("geo") or {}

            if not block.get("id") and tile.get("id"):
                block["id"] = tile["id"]
            if tile_deeplink and (not block.get("deeplink") or partner_override):
                block["deeplink"] = tile_deeplink
            if tile_image and (not block.get("image_url") or partner_override):
                block["image_url"] = tile_image
            if tile.get("rating") is not None and (block.get("rating") is None or partner_override):
                block["rating"] = tile["rating"]
            if tile.get("review_count") is not None and (
                block.get("review_count") is None or partner_override
            ):
                block["review_count"] = tile["review_count"]
            if tile.get("price_level") is not None and block.get("price_level") is None:
                block["price_level"] = tile["price_level"]
            if tile.get("price_estimate") is not None and block.get("price_estimate") is None:
                block["price_estimate"] = tile["price_estimate"]
            if tile.get("google_place_id") and not block.get("google_place_id"):
                block["google_place_id"] = tile["google_place_id"]
            if not block.get("booked_tile"):
                block["booked_tile"] = tile
            if block.get("booked_tile"):
                block["requires_booking"] = True
            if block.get("booking_category") is None and block.get("booked_tile"):
                block["booking_category"] = "activity"

            if block.get("coordinates"):
                continue
            if isinstance(tile_coords, dict) and {
                "lat",
                "lng",
            }.issubset(tile_coords):
                block["coordinates"] = {"lat": tile_coords["lat"], "lng": tile_coords["lng"]}
                continue
            if isinstance(tile_coords, list) and len(tile_coords) >= 2:
                block["coordinates"] = {"lng": tile_coords[0], "lat": tile_coords[1]}
                continue
            if (
                isinstance(tile_geo, dict)
                and tile_geo.get("lat") is not None
                and tile_geo.get("lng") is not None
            ):
                block["coordinates"] = {"lat": tile_geo["lat"], "lng": tile_geo["lng"]}


async def _run_itinerary_enrichment_pipeline(
    trip_plan: Dict[str, Any],
    activity_tiles: list[Dict[str, Any]],
    day_cards: list[Dict[str, Any]],
    session_id: str = "",
) -> Dict[str, Any]:
    """Run deferred tile/day-card enrichment outside the builder critical path."""
    destination = trip_plan.get("destination", "")
    currency = trip_plan.get("currency") or "USD"
    has_viator = settings.viator_enabled and settings.viator_api_key
    has_gyg = settings.get_your_guide_enabled and settings.get_your_guide_api_key

    if destination and activity_tiles and (has_viator or has_gyg):
        from app.services.partner_enrichment import enrich_tiles_with_partners

        # Only enrich tiles placed in the itinerary to avoid wasted partner API calls
        placed_ids: set[str] = set()
        for dc in day_cards:
            if not isinstance(dc, dict):
                continue
            for block in dc.get("blocks", []):
                if not isinstance(block, dict):
                    continue
                bid = block.get("id")
                if bid:
                    placed_ids.add(bid)
                bt = block.get("booked_tile")
                if isinstance(bt, dict) and bt.get("id"):
                    placed_ids.add(bt["id"])

        tiles_to_enrich = (
            [t for t in activity_tiles if t.get("id") in placed_ids]
            if placed_ids
            else activity_tiles
        )
        await enrich_tiles_with_partners(tiles_to_enrich, destination, currency)
        _apply_activity_tile_enrichment_to_day_cards(activity_tiles, day_cards)

    # Skip GP enrichment when all placed blocks already have partner or GP data.
    _blocks_needing_gp = 0
    for dc in day_cards:
        if not isinstance(dc, dict):
            continue
        for block in dc.get("blocks", []):
            if not isinstance(block, dict) or block.get("is_buffer"):
                continue
            at = (block.get("activity_type") or "").lower()
            if at in ("arrival", "departure", "check_in", "check_out", "free_day"):
                continue
            has_data = bool(
                block.get("deeplink") or block.get("image_url") or block.get("google_place_id")
            )
            if not has_data:
                _blocks_needing_gp += 1

    if _blocks_needing_gp == 0 and day_cards:
        logger.info("[coordinator] All placed blocks have partner/GP data — skipping GP enrichment")
    elif day_cards:
        shadow_state = {
            "trip_plan": trip_plan,
            "tiles": {"activities": activity_tiles},
            "session_id": session_id,
        }
        await _post_build_enrich_placed_activities(shadow_state, day_cards)

    return {"activities": activity_tiles, "day_cards": day_cards}


def _cancel_pending_itinerary_enrichment(state: Dict[str, Any]) -> None:
    """Cancel any deferred itinerary enrichment task still attached to state."""
    task = state.pop(_PENDING_ITINERARY_ENRICHMENT_TASK_KEY, None)
    if isinstance(task, asyncio.Task) and not task.done():
        task.cancel()


async def _cleanup_pending_itinerary_enrichment(state: Dict[str, Any]) -> None:
    """Cancel and await any deferred itinerary enrichment task still attached to state."""
    task = state.pop(_PENDING_ITINERARY_ENRICHMENT_TASK_KEY, None)
    if not isinstance(task, asyncio.Task):
        return

    if not task.done():
        task.cancel()

    await asyncio.gather(task, return_exceptions=True)


def _start_pending_itinerary_enrichment(
    state: Dict[str, Any],
    session_id: str = "",
) -> None:
    """Start deferred enrichment so builder output can stream before it finishes."""
    _cancel_pending_itinerary_enrichment(state)

    trip_plan = state.get("trip_plan", {})
    destination = trip_plan.get("destination", "")
    activity_tiles = (state.get("tiles") or {}).get("activities", [])
    day_cards = state.get("day_cards", [])
    if not isinstance(activity_tiles, list):
        activity_tiles = []
    if not isinstance(day_cards, list):
        day_cards = []

    has_partner_enrichment = (
        bool(destination)
        and bool(activity_tiles)
        and (
            (settings.viator_enabled and settings.viator_api_key)
            or (settings.get_your_guide_enabled and settings.get_your_guide_api_key)
        )
    )
    has_post_build_enrichment = (
        bool(destination)
        and bool(day_cards)
        and settings.use_google_places_provider
        and settings.google_places_enrichment_enabled
    )
    if not has_partner_enrichment and not has_post_build_enrichment:
        return

    state[_PENDING_ITINERARY_ENRICHMENT_TASK_KEY] = asyncio.create_task(
        _run_itinerary_enrichment_pipeline(
            trip_plan=copy.deepcopy(trip_plan),
            activity_tiles=copy.deepcopy(activity_tiles),
            day_cards=copy.deepcopy(day_cards),
            session_id=session_id,
        )
    )


async def _await_pending_itinerary_enrichment(state: Dict[str, Any]) -> None:
    """Apply deferred itinerary enrichment results back onto live state."""
    task = state.pop(_PENDING_ITINERARY_ENRICHMENT_TASK_KEY, None)
    if not isinstance(task, asyncio.Task):
        return

    try:
        result = await task
    except asyncio.CancelledError:
        return
    except Exception as exc:
        logger.warning("[coordinator] Deferred itinerary enrichment failed: %s", exc)
        return

    if not isinstance(result, dict):
        return

    activities = result.get("activities")
    if isinstance(activities, list):
        tiles = state.setdefault("tiles", {})
        if isinstance(tiles, dict):
            tiles["activities"] = activities

    day_cards = result.get("day_cards")
    if isinstance(day_cards, list):
        state["day_cards"] = day_cards


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
    _sync_booking_type_overrides(state, previous_settings, trip_settings)

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


def _rehydrate_trimmed_booked_tiles(state: Dict[str, Any]) -> None:
    """Backfill display fields onto booked_tile dicts trimmed by session serialization.

    Session state trims booked_tile to _SESSION_BOOKED_TILE_KEYS (excludes
    image_url, geo) to stay within the 64KB session budget. On non-rebuild turns
    the trimmed day_cards pass through to the envelope, causing empty cards.

    Fix: rehydrate from activity tiles in the tiles dict, which retain image_url
    and geo via _SESSION_TILE_KEYS.
    """
    day_cards = state.get("day_cards")
    if not isinstance(day_cards, list) or not day_cards:
        return

    activity_tiles = (state.get("tiles") or {}).get("activities", [])
    if not isinstance(activity_tiles, list) or not activity_tiles:
        return

    tile_by_id: Dict[str, Dict[str, Any]] = {
        str(t["id"]): t for t in activity_tiles if isinstance(t, dict) and t.get("id")
    }
    if not tile_by_id:
        return

    _REHYDRATE_FIELDS = ("image_url", "geo")
    patched = 0
    for card in day_cards:
        if not isinstance(card, dict):
            continue
        for block in card.get("blocks", []):
            if not isinstance(block, dict):
                continue
            booked = block.get("booked_tile")
            if not isinstance(booked, dict):
                continue
            full_tile = tile_by_id.get(str(booked.get("id") or ""))
            if not full_tile:
                continue
            for field in _REHYDRATE_FIELDS:
                if not booked.get(field) and full_tile.get(field):
                    booked[field] = full_tile[field]
                    patched += 1

    if patched:
        logger.debug("[coordinator] Rehydrated %d booked_tile fields from tiles", patched)


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
        trip_plan.pop("country_code", None)  # re-resolve at envelope build
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
            from datetime import timedelta

            start_date_to_use = trip_plan.get("start_date") or None
            # Auto-derive start_date when only duration is given (e.g. "about a week")
            if start_date_to_use is None and not classifier.start_date:
                default_start = (datetime.now() + timedelta(weeks=2)).strftime("%Y-%m-%d")
                clamped_start = _clamp_date_str(default_start)
                if clamped_start:
                    trip_plan["start_date"] = clamped_start
                    start_date_to_use = clamped_start
                if "start_date" not in fields_changed:
                    fields_changed.append("start_date")
                turn_steps.append(
                    {
                        "type": "start_date",
                        "summary": f"start_date: None -> {default_start} (derived from duration)",
                    }
                )
            if isinstance(start_date_to_use, str) and start_date_to_use:
                try:
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

    # Default duration fallback: if we have start_date but no end_date and
    # the classifier didn't extract duration_days, default to 7 days so the
    # first turn can build tiles + itinerary instead of producing an empty plan.
    if (
        not trip_plan.get("end_date")
        and trip_plan.get("start_date")
        and classifier.duration_days is None
        and not classifier.end_date
        and classifier.change_type in (ChangeType.INITIAL_PLAN, ChangeType.DESTINATION_CHANGE)
    ):
        from datetime import timedelta

        existing = trip_plan.get("trip_duration")
        default_duration = existing if existing is not None and existing > 0 else 7
        try:
            start_dt = datetime.strptime(trip_plan["start_date"], "%Y-%m-%d")
            end_dt = start_dt + timedelta(days=default_duration - 1)
            derived_end = end_dt.strftime("%Y-%m-%d")
            trip_plan["end_date"] = derived_end
            if "end_date" not in fields_changed:
                fields_changed.append("end_date")
            turn_steps.append(
                {
                    "type": "end_date",
                    "summary": (
                        f"end_date: None -> {derived_end} (default {default_duration}-day trip)"
                    ),
                }
            )
            if not trip_plan.get("trip_duration"):
                trip_plan["trip_duration"] = default_duration
                if "trip_duration" not in fields_changed:
                    fields_changed.append("trip_duration")
                turn_steps.append(
                    {
                        "type": "trip_duration",
                        "summary": f"trip_duration: None -> {default_duration} (default)",
                    }
                )
            logger.info(
                "[coordinator] Default duration applied: %d days (%s -> %s)",
                default_duration,
                trip_plan["start_date"],
                derived_end,
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

    # On destination change: clear day_preferences (destination-specific),
    # clear specialist strategy sections (stale content), and drop Tier 1
    # categories not re-mentioned in the new message. This prevents stale
    # specialists from re-dispatching at the new destination. Categories
    # that ARE mentioned persist and get feasibility-checked later.
    # Tier 2 categories (yoga, nightlife) are preserved since they're
    # not specialist-dispatched.
    if classifier.change_type == ChangeType.DESTINATION_CHANGE:
        if activity_settings.get("day_preferences"):
            activity_settings["day_preferences"] = {}
        # Clear specialist strategy sections — they contain destination-specific
        # content (one_liner, content_added, hero_image) that is stale after
        # destination change. Preserve local_expert sections as they'll be
        # rebuilt independently.
        # Note: for non-GENERATE_PLAN_NOW paths, _clear_planning_artifacts()
        # wipes all sections anyway; this matters for GENERATE_PLAN_NOW reuse.
        existing_sections = state.get("strategy_sections", [])
        state["strategy_sections"] = [
            s
            for s in existing_sections
            if isinstance(s, dict) and s.get("specialist_type") == "local_expert"
        ]
        # Clear Tier 1 categories not mentioned in the new message —
        # prevents stale specialists (e.g. diving) from re-dispatching
        # at the new destination when the user didn't ask for them.
        mentioned = {
            _norm_topic(c)
            for c in list(classifier.specialist_hints) + list(classifier.activity_categories)
            if c and _norm_topic(c)
        }
        stale = [
            c
            for c in new_cats
            if _norm_topic(c) in TIER1_SPECIALIST_NAMES and _norm_topic(c) not in mentioned
        ]
        if stale:
            new_cats = [c for c in new_cats if c not in stale]

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

    # Traveler style → trip_plan.vibe
    if classifier.traveler_style:
        old_vibe = trip_plan.get("vibe")
        if old_vibe != classifier.traveler_style:
            trip_plan["vibe"] = classifier.traveler_style
            fields_changed.append("vibe")
            turn_steps.append(
                {
                    "type": "vibe",
                    "summary": f"vibe: {old_vibe} -> {classifier.traveler_style}",
                }
            )

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
        user_disabled_flights = "flights" in _get_user_disabled_booking_types(state)
        if current_flights_mode in (None, "off", "") and not user_disabled_flights:
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
) -> AsyncGenerator[tuple[str, Optional[Dict[str, Any]]], None]:
    """Dispatch multiple specialists in parallel.

    Delegates to ``dispatch_specialist_with_brief()`` so coordinator brief +
    replan pathways match graph specialist behavior.

    Yields topic/result pairs as each specialist finishes. Result is ``None``
    when a specialist fails so callers preserve the existing graceful failure
    behavior without waiting for the slowest sibling.
    """
    from app.db import _get_async_session_factory
    from app.planner.nodes.vertical_specialist import dispatch_specialist_with_brief

    if not topics:
        return

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

    async def _dispatch_one(
        topic: str,
    ) -> tuple[str, Optional[Dict[str, Any]], Exception | None]:
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

        try:
            async with async_session_factory() as db:
                result = await dispatch_specialist_with_brief(
                    brief=brief,
                    topic=topic,
                    replan=replan_request,
                    db=db,
                    raw_day_pref=_raw_day_pref,
                )
        except Exception as exc:  # pragma: no cover - exercised via caller assertions
            return topic, None, exc

        return topic, result.model_dump() if result is not None else None, None

    tasks = [asyncio.create_task(_dispatch_one(topic)) for topic in topics]

    try:
        for task in asyncio.as_completed(tasks):
            topic, out_dict, error = await task
            if error is not None:
                logger.error(
                    "[coordinator] Specialist dispatch failed for %s: %s",
                    topic,
                    error,
                    exc_info=error,
                )
                yield topic, None
                continue

            yield topic, out_dict
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


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
                "price_estimate": activity.get("price_estimate"),
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
                "price_estimate": dp.get("price_estimate"),
            }
        )

    # Backfill image_url for content blocks
    from app.planner.nodes.vertical_specialist import _get_curated_image

    dest = trip_plan.get("destination", "")
    for item in content_added:
        if not item.get("image_url"):
            item["image_url"] = _get_curated_image(
                topic, dest, item.get("title", "")
            ) or get_activity_image(topic, dest, item.get("title", ""))

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
        geo: Dict[str, Any] | None = None
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
                if item.get("price_estimate") is not None
                else _SPECIALIST_DEFAULT_PRICE.get(topic, 20.0),
                "price_level": None,
                "currency": "USD",
                "price_basis": "per_person",
                "is_estimate_only": True,
                "deeplink": f"https://www.google.com/maps/search/{quote(f'{title} {destination}')}",
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


def _normalize_constraint_key(constraint: Dict[str, Any]) -> str:
    """Build a stable dedupe key for canonical builder constraints."""
    rule = str(constraint.get("rule") or constraint.get("constraint_id") or "").strip().lower()
    return rule.replace("-", "_").replace(" ", "_")


def _collect_canonical_builder_constraints(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Collect canonical trip constraints for the itinerary builder."""
    collected: List[Dict[str, Any]] = []
    seen: set[str] = set()
    active_topics = _active_specialist_topics(state)

    raw_sources = [state.get("constraints")]
    trip_plan = state.get("trip_plan", {})
    if isinstance(trip_plan, dict):
        raw_sources.append(trip_plan.get("constraints"))

    for raw_constraints in raw_sources:
        if not isinstance(raw_constraints, list):
            continue
        for constraint in raw_constraints:
            if hasattr(constraint, "model_dump"):
                payload = constraint.model_dump()
            elif isinstance(constraint, dict):
                payload = dict(constraint)
            else:
                continue
            key = _normalize_constraint_key(payload)
            if not key or key in seen:
                continue
            seen.add(key)
            collected.append(payload)

    violation_to_rule = {
        "ALTITUDE_AFTER_DIVE": "no_altitude_after_dive",
    }
    for topic in sorted(active_topics):
        config = SPECIALIST_REGISTRY.get(topic)
        if not config:
            continue
        for cross_domain in config.cross_domain_blocks:
            if not active_topics.intersection(
                {_norm_topic(target) for target in cross_domain.target_specialists}
            ):
                continue
            canonical_rule = violation_to_rule.get(cross_domain.violation_code)
            if not canonical_rule:
                continue
            key = _normalize_constraint_key({"rule": canonical_rule})
            if key in seen:
                continue
            seen.add(key)
            collected.append(
                {
                    "constraint_id": canonical_rule,
                    "type": "temporal",
                    "rule": canonical_rule,
                    "severity": cross_domain.severity,
                    "reason": cross_domain.reason,
                    "buffer_hours": cross_domain.buffer_hours,
                }
            )

    return collected


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
            _dest_geo_resolved = False
            dest_geo = None
            for i, t in enumerate(activity_tiles):
                if (
                    isinstance(t, dict)
                    and t.get("source_agent") in _ENRICHABLE_SOURCES
                    and not t.get("geo")
                ):
                    if not _dest_geo_resolved:
                        coords = await _geocode_destination_async(destination)
                        dest_geo = {"lng": coords[1], "lat": coords[0]} if coords else None
                        _dest_geo_resolved = True
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

    try:
        from app.tile_service.google_places_provider import (
            _normalize_title_for_cache,
            build_signed_photo_url,
            enrich_activities_with_places,
        )

        # Build lookup of existing GP-enriched activity tiles to avoid re-searching
        existing_tiles = state.get("tiles", {}).get("activities", [])
        _gp_title_candidates: dict[str, list[dict]] = defaultdict(list)
        for t in existing_tiles:
            if isinstance(t, dict) and t.get("google_place_id"):
                title_key = _normalize_title_for_cache(t.get("title", ""))
                if title_key:
                    _gp_title_candidates[title_key].append(t)

        _gp_by_title: dict[str, dict] = {}
        for title_key, candidates in _gp_title_candidates.items():
            unique_ids = {
                str(candidate.get("id") or candidate.get("google_place_id") or "").strip()
                for candidate in candidates
            }
            unique_ids.discard("")
            if len(unique_ids) > 1:
                continue
            _gp_by_title[title_key] = candidates[0]

        def _apply_booked_tile_fallback(block: dict[str, Any]) -> bool:
            booked_tile = block.get("booked_tile")
            if not isinstance(booked_tile, dict):
                return False

            block_has_viator = "viator.com" in (block.get("deeplink") or "")
            tile_coords = booked_tile.get("coordinates")
            tile_geo = booked_tile.get("geo") or (booked_tile.get("meta") or {}).get("geo") or {}

            if not block.get("coordinates"):
                if isinstance(tile_coords, list) and len(tile_coords) >= 2:
                    block["coordinates"] = {"lng": tile_coords[0], "lat": tile_coords[1]}
                elif isinstance(tile_coords, dict) and {
                    "lat",
                    "lng",
                }.issubset(tile_coords):
                    block["coordinates"] = {"lat": tile_coords["lat"], "lng": tile_coords["lng"]}
                elif (
                    isinstance(tile_geo, dict)
                    and tile_geo.get("lat") is not None
                    and tile_geo.get("lng") is not None
                ):
                    block["coordinates"] = {"lat": tile_geo["lat"], "lng": tile_geo["lng"]}

            if booked_tile.get("google_place_id") and not block.get("google_place_id"):
                block["google_place_id"] = booked_tile["google_place_id"]

            if not block_has_viator and not block.get("deeplink"):
                deeplink = (
                    booked_tile.get("deeplink")
                    or booked_tile.get("deeplink_url")
                    or booked_tile.get("maps_uri")
                )
                if deeplink:
                    block["deeplink"] = deeplink

            if not block_has_viator and not block.get("image_url") and booked_tile.get("image_url"):
                block["image_url"] = booked_tile["image_url"]

            if booked_tile.get("price_level") is not None and block.get("price_level") is None:
                block["price_level"] = booked_tile["price_level"]

            if booked_tile.get("rating") is not None and block.get("rating") is None:
                block["rating"] = booked_tile["rating"]

            if booked_tile.get("review_count") is not None and block.get("review_count") is None:
                block["review_count"] = booked_tile["review_count"]

            return bool(block.get("google_place_id") and block.get("coordinates"))

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
                if block.get("activity_type") == "free_day":
                    continue
                if block.get("google_place_id") and block.get("coordinates"):
                    continue
                summary = block.get("summary", "")
                if summary.strip().lower().startswith("free day"):
                    continue
                if not summary:
                    continue
                if _apply_booked_tile_fallback(block):
                    _reused_count += 1
                    continue

                booked_tile = block.get("booked_tile")
                title_candidates: list[str] = []
                if isinstance(booked_tile, dict):
                    booked_title = str(booked_tile.get("title") or "").strip()
                    if booked_title:
                        title_candidates.append(booked_title)
                if summary and summary not in title_candidates:
                    title_candidates.append(summary)

                existing = None
                for candidate in title_candidates:
                    existing = _gp_by_title.get(_normalize_title_for_cache(candidate))
                    if existing:
                        break
                if existing:
                    block_has_viator = "viator.com" in (block.get("deeplink") or "")
                    block["google_place_id"] = existing.get("google_place_id")
                    ex_coords = existing.get("coordinates")
                    if isinstance(ex_coords, list) and len(ex_coords) >= 2:
                        block["coordinates"] = {"lng": ex_coords[0], "lat": ex_coords[1]}
                    elif isinstance(ex_coords, dict):
                        block["coordinates"] = ex_coords
                    # Deeplink/image — skip if Viator already set
                    if not block_has_viator:
                        if existing.get("deeplink"):
                            block["deeplink"] = existing["deeplink"]
                        photo_name = existing.get("photo_name") or ""
                        if photo_name and session_id:
                            signed_url = build_signed_photo_url(session_id, photo_name)
                            if signed_url:
                                block["image_url"] = signed_url
                        elif existing.get("image_url"):
                            block["image_url"] = existing["image_url"]
                    if existing.get("price_level") is not None and block.get("price_level") is None:
                        block["price_level"] = existing["price_level"]
                    _reused_count += 1
                    continue
                lookup_title = title_candidates[0] if title_candidates else summary
                coords = block.get("coordinates")
                proxy_coords = None
                if isinstance(coords, list):
                    proxy_coords = coords
                elif (
                    isinstance(coords, dict)
                    and coords.get("lat") is not None
                    and coords.get("lng") is not None
                ):
                    proxy_coords = [coords["lng"], coords["lat"]]
                proxies.append(
                    {
                        "id": block.get("id", f"post_enrich_{day_idx}_{block_idx}"),
                        "title": lookup_title,
                        "coordinates": proxy_coords,
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
            logger.info(
                "[POST_BUILD] block='%s' deeplink=%s image=%s",
                (block.get("summary") or "")[:40],
                (block.get("deeplink") or "NONE")[:60],
                (block.get("image_url") or "NONE")[:60],
            )
            # Preserve Viator data — GP backfills coordinates only
            block_has_viator = "viator.com" in (block.get("deeplink") or "")
            # Coordinates — DayCard schema expects {lat, lng} dict
            coords = enriched_tile.get("coordinates")
            if isinstance(coords, list) and len(coords) >= 2:
                block["coordinates"] = {"lng": coords[0], "lat": coords[1]}
            elif isinstance(coords, dict):
                block["coordinates"] = coords
            # Google Place ID + deeplink (skip if Viator already set)
            gp_id = enriched_tile.get("google_place_id")
            if gp_id:
                block["google_place_id"] = gp_id
            if not block_has_viator:
                deeplink = enriched_tile.get("deeplink")
                if deeplink:
                    block["deeplink"] = deeplink
            # Rating propagation disabled — no real provider sources exist
            if enriched_tile.get("price_level") is not None and block.get("price_level") is None:
                block["price_level"] = enriched_tile["price_level"]
            # Photo: signed URL from photo_name (skip if Viator image already set)
            if not block_has_viator:
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


def _normalize_step_events(
    step_result: Any,
) -> list[Dict[str, Any]]:
    """Normalize step return values into a flat list of SSE events."""
    if step_result is None:
        return []
    if isinstance(step_result, dict):
        return [step_result]
    if isinstance(step_result, list):
        return [event for event in step_result if isinstance(event, dict)]
    return []


def _is_step_event_stream(step_result: Any) -> bool:
    """Return True when a step result must be consumed as an async event stream."""
    return hasattr(step_result, "__aiter__") and hasattr(step_result, "__anext__")


# ---------------------------------------------------------------------------
# Tile search (Phase 2: minimal bridge)
# ---------------------------------------------------------------------------


def _preserved_specialist_tiles_for_turn(
    state: Dict[str, Any],
    classifier: ClassifierOutput,
    existing_activity_tiles: Any,
) -> List[Dict[str, Any]]:
    """Collect prior specialist tiles that should survive the current refresh."""
    if not isinstance(existing_activity_tiles, list):
        return []

    preserved_topics = {
        _norm_topic(topic)
        for topic in _compute_preserve_list(classifier, state)
        if _norm_topic(topic) in TIER1_SPECIALIST_NAMES
    }
    if not preserved_topics:
        return []

    preserved_tiles: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for tile in existing_activity_tiles:
        if not isinstance(tile, dict):
            continue
        tile_id = str(tile.get("id") or "")
        if not tile_id or tile_id in seen_ids:
            continue
        meta = tile.get("meta", {})
        if not isinstance(meta, dict):
            meta = {}
        specialist_type = _norm_topic(meta.get("specialist_type") or meta.get("category") or "")
        if specialist_type not in preserved_topics:
            continue
        if (
            tile.get("source_agent") != "vertical_specialist"
            and tile.get("partner") != "vertical_specialist"
            and not tile_id.startswith("spec_")
        ):
            continue
        seen_ids.add(tile_id)
        preserved_tiles.append(tile)

    return preserved_tiles


def _merge_activity_tiles(
    refreshed_tiles: Any,
    preserved_specialist_tiles: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Append preserved specialist tiles after fresh results without duplicate IDs."""
    merged: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()

    if isinstance(refreshed_tiles, list):
        for tile in refreshed_tiles:
            if not isinstance(tile, dict):
                continue
            tile_id = str(tile.get("id") or "")
            if tile_id:
                seen_ids.add(tile_id)
            merged.append(tile)

    for tile in preserved_specialist_tiles:
        tile_id = str(tile.get("id") or "")
        if tile_id and tile_id in seen_ids:
            continue
        if tile_id:
            seen_ids.add(tile_id)
        merged.append(tile)

    return merged


def _partner_tile_priority(tile: Dict[str, Any]) -> int:
    """Prefer stronger affiliate matches when multiple prior tiles could match."""
    provider = str(tile.get("provider") or "").lower()
    partner = str(tile.get("partner") or "").lower()
    if provider == "viator" or partner == "viator":
        return 3
    if provider == "gyg" or partner in {"gyg", "getyourguide", "get_your_guide"}:
        return 2
    if partner:
        return 1
    return 0


def _has_partner_enrichment(tile: Dict[str, Any]) -> bool:
    """Return True when an activity tile already carries affiliate match data."""
    if not isinstance(tile, dict):
        return False

    provider = str(tile.get("provider") or "").lower()
    partner = str(tile.get("partner") or "").lower()
    if provider in {"viator", "gyg"} or partner in {"viator", "gyg", "getyourguide"}:
        return True

    meta = tile.get("meta")
    if not isinstance(meta, dict):
        return False
    return bool(meta.get("viator_product_code") or meta.get("gyg_tour_id"))


def _copy_partner_enrichment_fields(
    source_tile: Dict[str, Any],
    target_tile: Dict[str, Any],
) -> None:
    """Copy affiliate fields from a previous matching tile onto a refreshed tile."""
    if _has_partner_enrichment(target_tile):
        return

    for field in (
        "price_estimate",
        "live_price",
        "currency",
        "price_basis",
        "is_estimate_only",
        "image_url",
        "rating",
        "review_count",
        "deeplink",
        "deeplink_url",
        "partner",
        "partner_product_id",
        "provider",
    ):
        value = source_tile.get(field)
        if value is None or value == "":
            continue
        target_tile[field] = value

    if not target_tile.get("geo") and source_tile.get("geo"):
        target_tile["geo"] = source_tile["geo"]

    source_meta = source_tile.get("meta")
    if not isinstance(source_meta, dict):
        return
    target_meta = target_tile.get("meta")
    if not isinstance(target_meta, dict):
        target_meta = {}

    for field in ("viator_product_code", "gyg_tour_id", "duration_hours"):
        value = source_meta.get(field)
        if value is None or value == "":
            continue
        target_meta[field] = value
    if not target_meta.get("category") and source_meta.get("category"):
        target_meta["category"] = source_meta["category"]
    target_tile["meta"] = target_meta


def _partner_tile_category_contexts(tile: Dict[str, Any]) -> set[str]:
    """Collect normalized category context fields used for conservative reuse."""
    values: set[str] = set()
    meta = tile.get("meta")
    meta_dict = meta if isinstance(meta, dict) else {}
    for raw in (
        tile.get("category"),
        tile.get("browse_category"),
        meta_dict.get("category"),
    ):
        if not isinstance(raw, str):
            continue
        normalized = re.sub(r"[^a-z0-9]+", "_", raw.strip().lower()).strip("_")
        if normalized:
            values.add(normalized)
    return values


def _partner_tile_context_compatible(
    source_tile: Dict[str, Any],
    target_tile: Dict[str, Any],
) -> bool:
    """Reject reuse when the prior and refreshed tiles clearly represent different categories."""
    source_contexts = _partner_tile_category_contexts(source_tile)
    target_contexts = _partner_tile_category_contexts(target_tile)
    if not source_contexts or not target_contexts:
        return True
    return not source_contexts.isdisjoint(target_contexts)


def _resolve_partner_rehydration_candidate(
    candidates: list[Dict[str, Any]],
    target_tile: Dict[str, Any],
) -> Dict[str, Any] | None:
    """Resolve one conservative carry-forward candidate or return None when ambiguous."""
    compatible = [
        candidate
        for candidate in candidates
        if isinstance(candidate, dict) and _partner_tile_context_compatible(candidate, target_tile)
    ]
    if not compatible:
        return None

    unique_ids = {
        str(
            candidate.get("id")
            or candidate.get("google_place_id")
            or candidate.get("place_id")
            or candidate.get("partner_product_id")
            or ""
        ).strip()
        for candidate in compatible
    }
    unique_ids.discard("")
    if len(unique_ids) > 1:
        return None

    return max(compatible, key=_partner_tile_priority)


def _carry_forward_partner_enrichment(
    refreshed_tiles: Any,
    existing_tiles: Any,
) -> List[Dict[str, Any]]:
    """Rehydrate refreshed activity tiles from matching prior affiliate-enriched tiles."""
    if not isinstance(refreshed_tiles, list):
        return []
    if not isinstance(existing_tiles, list):
        return refreshed_tiles

    prior_partner_tiles = [
        tile for tile in existing_tiles if isinstance(tile, dict) and _has_partner_enrichment(tile)
    ]
    if not prior_partner_tiles:
        return refreshed_tiles

    tiles_by_id: dict[str, list[Dict[str, Any]]] = defaultdict(list)
    tiles_by_place_id: dict[str, list[Dict[str, Any]]] = defaultdict(list)
    title_candidates: dict[str, list[Dict[str, Any]]] = defaultdict(list)

    for tile in prior_partner_tiles:
        tile_id = str(tile.get("id") or "").strip()
        if tile_id:
            tiles_by_id[tile_id].append(tile)

        for place_key in ("google_place_id", "place_id"):
            place_id = str(tile.get(place_key) or "").strip()
            if not place_id:
                continue
            tiles_by_place_id[place_id].append(tile)

        title_key = _normalize_activity_exact_title_key(tile.get("title"))
        if title_key:
            title_candidates[title_key].append(tile)

    for tile in refreshed_tiles:
        if not isinstance(tile, dict) or _has_partner_enrichment(tile):
            continue

        match: Dict[str, Any] | None = None
        tile_id = str(tile.get("id") or "").strip()
        if tile_id:
            match = _resolve_partner_rehydration_candidate(tiles_by_id.get(tile_id, []), tile)

        if match is None:
            for place_key in ("google_place_id", "place_id"):
                place_id = str(tile.get(place_key) or "").strip()
                if place_id:
                    match = _resolve_partner_rehydration_candidate(
                        tiles_by_place_id.get(place_id, []), tile
                    )
                if match is not None:
                    break

        if match is None:
            title_key = _normalize_activity_exact_title_key(tile.get("title"))
            if title_key:
                match = _resolve_partner_rehydration_candidate(
                    title_candidates.get(title_key, []), tile
                )

        if match is not None:
            _copy_partner_enrichment_fields(match, tile)

    return refreshed_tiles


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
    allow_flight_auto_upgrade = _should_allow_flight_auto_upgrade(
        classifier, state, requested_types
    )
    existing_tiles = state.get("tiles", {})
    existing_activity_tiles = (
        existing_tiles.get("activities", []) if isinstance(existing_tiles, dict) else []
    )
    merged_tiles = dict(existing_tiles) if isinstance(existing_tiles, dict) else {}
    preserved_specialist_tiles = _preserved_specialist_tiles_for_turn(
        state,
        classifier,
        existing_activity_tiles,
    )

    # Limit fetched verticals by requested tile types.
    settings_for_search = dict(trip_settings) if isinstance(trip_settings, dict) else {}
    booking_types = dict(settings_for_search.get("booking_types", {}))
    flights_explicitly_off = booking_types.get("flights") == "off" and not allow_flight_auto_upgrade

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

    if "flights" in requested_types and booking_types.get("flights") == "off":
        # Keep internal flight refreshes available for safety/date recomputes
        # without leaking a user-visible re-enable back into coordinator state.
        booking_types["flights"] = "suggested"
    elif "flights" not in requested_types:
        booking_types["flights"] = "off"
    if "activities" not in requested_types:
        booking_types["activities"] = "off"
    if "hotels" not in requested_types:
        booking_types["hotels"] = "off"
    settings_for_search["booking_types"] = booking_types
    if flights_explicitly_off:
        merged_tiles.pop("flights", None)

    strategy_sections = state.get("strategy_sections", [])
    executed_topics = [
        _norm_topic(s.get("specialist_type"))
        for s in strategy_sections
        if isinstance(s, dict)
        and s.get("specialist_type")
        and s.get("feasibility_status") != "infeasible"
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

    has_origin = bool(trip_plan.get("origin"))
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
            "requested_tile_types": sorted(requested_types),
            "allow_flight_auto_upgrade": allow_flight_auto_upgrade,
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
        if tile_type == "flights" and flights_explicitly_off:
            continue
        tile_list = refreshed_tiles.get(tile_type, [])
        if tile_type == "activities":
            carried_forward = _carry_forward_partner_enrichment(tile_list, existing_activity_tiles)
            merged_tiles[tile_type] = _merge_activity_tiles(
                carried_forward, preserved_specialist_tiles
            )
            continue
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
                if not gs_val or gs_val == "off":
                    continue
                current_val = coord_bt.get(key)
                if key == "flights":
                    if has_origin and (
                        current_val in (None, "")
                        or (current_val == "off" and allow_flight_auto_upgrade)
                    ):
                        coord_bt[key] = gs_val
                    continue
                if current_val in ("off", None, ""):
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
    # Thread date flex suggestion from logistics metadata to turn_meta
    date_flex = graph_state.metadata.get("date_flex_suggestion")
    if isinstance(date_flex, dict):
        turn_meta["date_flex_suggestion"] = date_flex
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
        from app.planner.services.section_builder import build_local_expert_section

        one_liner = f"Your adventure in {destination}"

        # Gallery images
        from app.data.demo_curation import DEMO_MANIFEST
        from app.placeholders import get_destination_gallery

        dest_key = destination.lower().strip()
        gallery = DEMO_MANIFEST.get(dest_key, {}).get("destination_gallery", [])
        if not gallery:
            gallery = get_destination_gallery(destination)

        constraints_applied: list[dict] = []

        section = build_local_expert_section(
            destination=destination,
            one_liner=one_liner,
            bullets=[],
            must_dos=[],
            logistics_notes=[],
            constraints_applied=constraints_applied,
            content_added=[],
            gallery_images=gallery,
            travel_intelligence={},
            principles=[],
        )

        # Propagate local-expert constraints to session state so they
        # are available (e.g. for conversationalist) even without a
        # Tier 1 specialist dispatch.
        if constraints_applied and not state.get("constraints"):
            state["constraints"] = list(constraints_applied)

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

            # Build lookup of enrichment states + travel_intelligence from DB
            db_enrichment_by_type: Dict[str, dict] = {}
            db_ti_by_type: Dict[str, dict] = {}
            for db_sec in db_sections:
                st = getattr(db_sec, "specialist_type", None)
                enr = getattr(db_sec, "local_expert_enrichment", None)
                if st and enr:
                    enr_dict = enr if isinstance(enr, dict) else enr.model_dump()
                    if enr_dict.get("state") in ("ready", "failed"):
                        db_enrichment_by_type[st] = enr_dict
                ti = getattr(db_sec, "travel_intelligence", None)
                if st and ti:
                    ti_dict = ti if isinstance(ti, dict) else ti.model_dump()
                    if ti_dict:
                        db_ti_by_type[st] = ti_dict

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
                if st in db_ti_by_type and not section.get("travel_intelligence"):
                    section["travel_intelligence"] = db_ti_by_type[st]
                    logger.debug("[coordinator] Refreshed travel_intelligence for %s", st)

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
                        ti = getattr(db_sec, "travel_intelligence", None)
                        if st and ti:
                            ti_dict = ti if isinstance(ti, dict) else ti.model_dump()
                            if ti_dict:
                                db_ti_by_type[st] = ti_dict
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
                        if st in db_ti_by_type and not section.get("travel_intelligence"):
                            section["travel_intelligence"] = db_ti_by_type[st]
    except Exception as exc:
        logger.debug("[coordinator] Enrichment state refresh failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Itinerary building (Phase 2: bridge to ItineraryBuilder)
# ---------------------------------------------------------------------------


async def _build_itinerary(
    state: Dict[str, Any],
    session_id: str = "",
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
        requested_categories, activity_categories, infeasible_requested, _ = (
            _resolve_activity_category_filters(state)
        )

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
            active_cats = set(c.lower() for c in (activity_categories or []))
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
            canonical_constraints=_collect_canonical_builder_constraints(state),
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
            "resolutions": [r.model_dump() for r in result.resolutions],
            "warnings": result.warnings,
            "overview": result.overview.model_dump() if result.overview else None,
            "assumptions": result.assumptions.model_dump() if result.assumptions else None,
            "requested_activity_categories": requested_categories,
            "effective_activity_categories": activity_categories,
            "infeasible_requested_categories": infeasible_requested,
        }
        state["turn_meta"] = turn_meta

        if result.day_cards:
            day_cards = [card.model_dump() for card in result.day_cards]
            state["day_cards"] = day_cards
            _start_pending_itinerary_enrichment(state, session_id=session_id)
            logger.info("[coordinator] _build_itinerary: produced %d day_cards", len(day_cards))
            return day_cards

        # Explicitly clear stale itinerary when builder returns no cards.
        logger.info("[coordinator] _build_itinerary: builder returned no day_cards")
        state["day_cards"] = []
        _start_pending_itinerary_enrichment(state, session_id=session_id)
        return []

    except Exception as exc:
        logger.warning("[coordinator] Itinerary build failed: %s", exc)
        turn_meta = dict(state.get("turn_meta", {}))
        turn_meta["builder_result"] = {
            "success": False,
            "activities_placed": 0,
            "activities_dropped": 0,
            "conflicts": [],
            "resolutions": [],
            "warnings": [str(exc)],
            "overview": None,
            "assumptions": None,
            "requested_activity_categories": [],
            "effective_activity_categories": None,
            "infeasible_requested_categories": [],
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

    # Inject country_code from geocode cache into trip_plan (if available)
    _dest = trip_plan.get("destination")
    if _dest and not trip_plan.get("country_code"):
        from app.tile_service.google_places_provider import get_country_code

        _cc = get_country_code(_dest)
        if _cc:
            trip_plan["country_code"] = _cc

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
        "country_code",
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
    if tiles.get("flights") and bt.get("flights") in (None, ""):
        bt["flights"] = "suggested"
    if tiles.get("hotels") and bt.get("hotels") in ("off", None, ""):
        bt["hotels"] = "suggested"

    # Second pass: sync from trip_settings state mutations.
    # _apply_classifier_to_state() may have upgraded booking_types (e.g.
    # flights → "suggested" on origin detection) but tiles may not exist
    # yet on this turn, so the tile-based reconciliation above misses it.
    settings_bt = trip_settings.get("booking_types", {})
    if isinstance(settings_bt, dict):
        for btype in ("flights", "hotels", "activities"):
            settings_val = settings_bt.get(btype)
            current_val = bt.get(btype)
            if btype == "flights":
                if settings_val in ("suggested", "on") and current_val in (None, ""):
                    bt[btype] = settings_val
                continue
            if settings_val in ("suggested", "on") and current_val in ("off", None, ""):
                bt[btype] = settings_val

    trip_inputs["booking_types"] = bt

    # Persist reconciled booking_types back to state for next turn
    existing_bt = trip_settings.get("booking_types", {})
    if bt != existing_bt:
        updated_ts = dict(trip_settings)
        updated_ts["booking_types"] = bt
        state["trip_settings"] = updated_ts
        trip_settings = state["trip_settings"]

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
    # Persist travel_intelligence per specialist so it survives async Phase B timing
    active_specialist_types: set[str] = set()
    for section in strategy_sections:
        if isinstance(section, dict):
            ti = section.get("travel_intelligence")
            st = section.get("specialist_type", "")
            if st:
                active_specialist_types.add(st)
            if ti and ti != {} and st:
                persistent_meta[f"travel_intelligence_{st}"] = ti
    # Clean orphaned travel_intelligence keys for removed specialists
    stale_keys = [
        k
        for k in persistent_meta
        if k.startswith("travel_intelligence_")
        and k[len("travel_intelligence_") :] not in active_specialist_types
    ]
    for k in stale_keys:
        del persistent_meta[k]
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
    if not constraint_violations and builder_ran:
        constraint_violations = _builder_conflicts_to_constraint_violations(
            builder_result.get("conflicts"),
            builder_result.get("resolutions"),
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
    booking_types = trip_settings.get("booking_types", {})
    flights_visible = not (
        isinstance(booking_types, dict) and booking_types.get("flights") == "off"
    )
    for _category, tile_list in tiles.items():
        if not isinstance(tile_list, list):
            continue
        if _category == "flights" and not flights_visible:
            continue
        for tile in tile_list:
            if isinstance(tile, dict):
                tile_id = tile.get("id")
                if tile_id:
                    flattened_tiles[str(tile_id)] = _normalize_tile_fields(tile)

    origin_just_set = bool(turn_meta.get("origin_just_set", False))
    tiles_replaced = bool(turn_meta.get("tiles_replaced", False))
    browseable_activities = turn_meta.get("browseable_activities", [])
    if not browseable_activities:
        browseable_activities = persistent_meta.get("browseable_activities", [])
    # Normalize deeplink_url → deeplink for browseable activities (legacy compat)
    for ba in browseable_activities:
        if not ba.get("deeplink") and ba.get("deeplink_url"):
            ba["deeplink"] = ba["deeplink_url"]

    # Pre-sign any raw photo_name references so the frontend never needs to
    # issue individual /api/media/google-places-photo-url signing requests.
    _pre_sign_envelope_photos(tiles, day_cards, browseable_activities, session_id)

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

    # Backfill travel_intelligence from persistent_meta (async Phase B may not have completed)
    for section in strategy_sections:
        if not isinstance(section, dict):
            continue
        ti = section.get("travel_intelligence")
        if not ti:
            st = section.get("specialist_type", "")
            pm_ti = persistent_meta.get(f"travel_intelligence_{st}")
            if pm_ti:
                section["travel_intelligence"] = pm_ti

    # Strip internal _cache_* keys before emitting to SSE (F6)
    strategy_sections_clean = [
        {k: v for k, v in s.items() if not k.startswith("_cache_")} if isinstance(s, dict) else s
        for s in strategy_sections
    ]

    document: Dict[str, Any] = {
        "trip_context_id": None,
        "trip_inputs": trip_inputs,
        "branches": [],
        "tiles": flattened_tiles,
        "assistant_message": assistant_message,
        "assistant_message_id": str(uuid.uuid4()),
        "ready_to_generate": ready_to_generate,
        "suggested_responses": suggested_replies,
        "suggested_response_meta": suggestion_chip_meta,
        "suggestion_chips": suggestion_chips,
        "plan_view_state": plan_view_state,
        "strategy_sections": strategy_sections_clean,
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
            if builder_ran and builder_result.get("overview")
            else persistent_meta.get("itinerary_overview")
        ),
        "itinerary_assumptions": (
            builder_result.get("assumptions")
            if builder_ran and builder_result.get("assumptions")
            else persistent_meta.get("itinerary_assumptions")
        ),
        "ack_status": ack_status,
        "ack_updates": ack_updates,
        "applied_updates": _canonicalize_applied_updates(fields_changed),
        "trip_cost_estimate": _compute_trip_cost_estimate(tiles, day_cards, trip_plan),
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
        "response_degraded": bool(turn_meta.get("response_degraded")),
        "response_error_type": turn_meta.get("response_error_type"),
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

    activities_placed = builder_result.get("activities_placed", -1)
    infeasible_requested = builder_result.get("infeasible_requested_categories", [])

    if builder_success:
        if not day_cards:
            return "S3_BLOCKED"
        # If builder produced day_cards but placed 0 activities, add warning
        if activities_placed == 0:
            warnings = builder_result.get("warnings", [])
            if infeasible_requested:
                if not any("infeasible" in w.lower() for w in warnings):
                    warnings.append(
                        "Requested activities are infeasible for this destination. "
                        "Change activities to continue."
                    )
                    builder_result["warnings"] = warnings
            if not any("no activities" in w.lower() for w in warnings):
                warnings.append(
                    "No activities could be placed — trip may be too short. "
                    "Consider extending by 1-2 days."
                )
                builder_result["warnings"] = warnings
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
) -> Optional[Dict[str, Any] | List[Dict[str, Any]] | AsyncGenerator[Dict[str, Any], None]]:
    """Execute a single step from the execution plan.

    Returns one or more SSE events to yield, or None if no event needed.
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

        # Handle pre-checked infeasible specialists (skip LLM dispatch).
        # Capture ALL infeasible prechecks (not just those in dispatch list)
        # so sections are rebuilt after the full invalidation wipe below.
        prechecks = state.get("turn_meta", {}).get("feasibility_prechecks", {})
        all_infeasible = {t: v for t, v in prechecks.items() if v[0] == "infeasible"}
        feasible_topics = [t for t in topics if t not in prechecks]

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
        if all_infeasible:
            from app.planner.services.section_builder import build_specialist_section

            trip_plan_snap: Dict[str, Any] = state.get("trip_plan", {})
            for inf_topic, (inf_status, inf_reason, inf_alt) in all_infeasible.items():
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
                state["strategy_sections"] = _ordered_requested_specialist_sections(
                    sections,
                    topics,
                )

        _refresh_preserved_specialist_section_metadata(state, preserves)
        state["specialist_plans"] = _ordered_requested_specialist_plans(
            specialist_plans,
            topics,
        )

        async def _stream_specialist_dispatch_events() -> AsyncGenerator[Dict[str, Any], None]:
            emitted_preview = False

            if feasible_topics:
                async for topic, llm_output_dict in _dispatch_specialists_parallel(
                    topics=feasible_topics,
                    state=state,
                    classifier=classifier,
                    other_plans=other_plans,
                    is_replan=is_replan,
                    preserves=preserves,
                ):
                    if llm_output_dict is None:
                        continue

                    brief = build_brief(topic, state, classifier, specialist_plans)
                    plan_dict = _llm_output_to_plan_dict(topic, llm_output_dict, brief)
                    specialist_plans[topic] = plan_dict
                    state["specialist_plans"] = _ordered_requested_specialist_plans(
                        specialist_plans,
                        topics,
                    )

                    section = _plan_to_strategy_section(topic, plan_dict, state)
                    sections = list(state.get("strategy_sections", []))
                    sections = [s for s in sections if s.get("specialist_type") != topic]
                    sections.append(section)
                    state["strategy_sections"] = _ordered_requested_specialist_sections(
                        sections,
                        topics,
                    )

                    emitted_preview = True
                    yield {
                        "type": "partial",
                        "data": {
                            "kind": "specialist_preview",
                            "payload": _specialist_preview_payload(state, topics),
                        },
                    }
                    yield {
                        "type": "partial",
                        "data": {
                            "kind": "strategy_sections",
                            "payload": state.get("strategy_sections", []),
                        },
                    }

            state["specialist_plans"] = _ordered_requested_specialist_plans(
                specialist_plans,
                topics,
            )
            if emitted_preview:
                return

            yield {
                "type": "partial",
                "data": {
                    "kind": "specialist_preview",
                    "payload": _specialist_preview_payload(state, topics),
                },
            }
            yield {
                "type": "partial",
                "data": {
                    "kind": "strategy_sections",
                    "payload": state.get("strategy_sections", []),
                },
            }

        return _stream_specialist_dispatch_events()

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
        turn_meta = state.get("turn_meta") or {}
        tiles_replaced = bool(turn_meta.get("tiles_replaced"))

        # Split emission: hotels+flights first, activities second
        hotel_flight_payload = _flatten_tiles_payload_filtered(tiles, ("hotels", "flights"))
        activity_payload = _flatten_tiles_payload_filtered(tiles, ("activities",))

        events: list[dict[str, Any]] = []

        # tiles_replaced is a turn-level signal: attach to whichever partial fires first
        replaced_emitted = False

        if hotel_flight_payload:
            hf_data: dict[str, Any] = {"kind": "tiles", "payload": hotel_flight_payload}
            if tiles_replaced and not replaced_emitted:
                hf_data["tiles_replaced"] = True
                replaced_emitted = True
            events.append({"type": "partial", "data": hf_data})

        if activity_payload:
            act_data: dict[str, Any] = {"kind": "tiles", "payload": activity_payload}
            if tiles_replaced and not replaced_emitted:
                act_data["tiles_replaced"] = True
                replaced_emitted = True
            events.append({"type": "partial", "data": act_data})

        if not events:
            combined: dict[str, Any] = {"kind": "tiles", "payload": _flatten_tiles_payload(tiles)}
            if tiles_replaced:
                combined["tiles_replaced"] = True
            events.append({"type": "partial", "data": combined})

        # Emit date flex suggestion when available
        date_flex = turn_meta.get("date_flex_suggestion")
        if isinstance(date_flex, dict) and date_flex:
            events.append(
                {"type": "partial", "data": {"kind": "date_flex_suggestion", "payload": date_flex}}
            )

        return events[0] if len(events) == 1 else events

    if step_type == StepType.BUILD_ITINERARY:
        # Snapshot tile IDs before build to detect new specialist-injected tiles
        pre_ids = {
            t.get("id")
            for cat in (state.get("tiles", {}) or {}).values()
            if isinstance(cat, list)
            for t in cat
            if isinstance(t, dict)
        }
        await _build_itinerary(state, session_id=session_id)
        events: list[Dict[str, Any]] = []
        day_cards = state.get("day_cards", [])
        if isinstance(day_cards, list):
            events.append(_day_cards_partial_event(state, day_cards))
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
            partial_data = {"kind": "tiles", "payload": _flatten_tiles_payload(tiles)}
            turn_meta = state.get("turn_meta") or {}
            if turn_meta.get("tiles_replaced"):
                partial_data["tiles_replaced"] = True
            events.append({"type": "partial", "data": partial_data})
        if not events:
            return None
        return events[0] if len(events) == 1 else events

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
) -> AsyncGenerator[tuple[ExecutionStep, List[Dict[str, Any]], bool], None]:
    """Execute a parallel group and yield step results as each task completes.

    Note on state mutation: parallel steps mutate the same state dict.
    This is safe in asyncio (single-threaded) as long as steps write
    to different keys. Current parallel groups:
    - DISPATCH_SPECIALISTS writes specialist_plans + strategy_sections
    - SEARCH_TILES writes tiles
    LOCAL_INTEL runs sequentially to avoid concurrent strategy_sections writes.
    """
    if not steps:
        return

    event_queue: asyncio.Queue[
        tuple[ExecutionStep, List[Dict[str, Any]], bool, Exception | None]
    ] = asyncio.Queue()

    async def _run_parallel_step(step: ExecutionStep) -> None:
        try:
            result = await _execute_step(
                step,
                state,
                classifier,
                user_message,
                session_id=session_id,
            )
            if _is_step_event_stream(result):
                async for event in result:
                    await event_queue.put((step, [event], False, None))
            else:
                step_events = _normalize_step_events(result)
                if step_events:
                    await event_queue.put((step, step_events, False, None))
            await event_queue.put((step, [], True, None))
        except Exception as exc:  # pragma: no cover - exercised via caller assertions
            await event_queue.put((step, [], True, exc))

    tasks = [asyncio.create_task(_run_parallel_step(step)) for step in steps]

    failures: List[str] = []
    successful_events = 0
    pending_steps = len(steps)

    try:
        while pending_steps > 0:
            step, step_events, completed, error = await event_queue.get()
            if error is not None:
                failures.append(step.step_type.value)
                logger.error(
                    "[coordinator] Parallel step %s failed: %s",
                    step.step_type.value,
                    error,
                    exc_info=error,
                )
                pending_steps -= 1
                yield step, [], True
                continue

            successful_events += len(step_events)
            if step_events or completed:
                yield step, step_events, completed
            if completed:
                pending_steps -= 1
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    if failures:
        logger.warning(
            "[coordinator] Partial parallel failure (%s) — continuing with %d successful results",
            ", ".join(failures),
            successful_events,
        )
        turn_meta = dict(state.get("turn_meta", {}))
        existing = list(turn_meta.get("partial_failures", []))
        existing.extend(failures)
        turn_meta["partial_failures"] = existing
        state["turn_meta"] = turn_meta


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def execute_turn(
    user_message: str,
    state: Dict[str, Any],
    session_id: str,
    doc_settings: Optional[Dict[str, Any]] = None,
    cancel_event: Optional[asyncio.Event] = None,
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
    cancel_event : asyncio.Event | None
        When set, the coordinator will stop executing at the next step boundary.
        Used by the SSE generator to signal client disconnection.

    Yields
    ------
    dict
        SSE event dicts: node_status, partial, token, complete, error.
    """
    wall_start = time.monotonic()
    _unsplash_task: asyncio.Task[Any] | None = None

    async def _cleanup_unsplash_task(
        *,
        cancel: bool,
        timeout: float | None = None,
    ) -> None:
        """Consume or cancel the prefetch task so it never runs detached."""
        nonlocal _unsplash_task

        task = _unsplash_task
        if not isinstance(task, asyncio.Task):
            return

        try:
            if cancel and not task.done():
                task.cancel()
            if not task.done():
                if timeout is None:
                    await asyncio.shield(task)
                else:
                    await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except asyncio.TimeoutError:
            return
        except asyncio.CancelledError:
            if not task.done():
                raise
        except Exception:
            return
        finally:
            if task.done():
                await asyncio.gather(task, return_exceptions=True)
                if _unsplash_task is task:
                    _unsplash_task = None

    try:
        # Step 0: Reset turn_meta for this turn
        await _cleanup_pending_itinerary_enrichment(state)
        state["turn_meta"] = {}
        # Carry forward patch-driven field changes (e.g. dates changed via
        # PATCH pill but not through chat). These bypass the classifier's
        # field extraction and must propagate into turn_meta so plan_turn()
        # can avoid short-circuiting.
        _patch_changed = state.pop("_patch_changed_fields", None)
        if _patch_changed:
            state["turn_meta"]["fields_changed"] = list(_patch_changed)
        _normalize_specialist_plan_keys(state)

        # Session turn cap — prevent runaway LLM spend
        _human_turns = sum(1 for m in (state.get("messages") or []) if isinstance(m, HumanMessage))
        if _human_turns >= 40:
            _cap_msg = (
                "You've reached the conversation limit for this session. "
                "Please start a new trip to continue planning."
            )
            yield {"type": "token", "data": _cap_msg}
            state.setdefault("messages", []).append(HumanMessage(content=user_message))
            state["messages"].append(AIMessage(content=_cap_msg))
            yield {
                "type": "complete",
                "data": _build_envelope(state, user_message, session_id, _cap_msg),
            }
            return

        # Step 1: Merge document settings
        _merge_doc_settings(state, doc_settings)
        _rehydrate_trimmed_booked_tiles(state)

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

        _structured_log(
            "turn_start",
            session_id=session_id,
            intent=classifier.intent,
            change_type=classifier.change_type.value,
            affects=classifier.affects,
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
            if _should_clear_planning_artifacts(classifier, state):
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

        # Step 4a: Speculatively start feasibility check BEFORE plan_turn() so
        # the LLM call (~600ms) overlaps with plan computation.  We use a
        # lightweight heuristic (PLANNING intent + not GPN) to decide; the
        # response-only guard is checked after plan_turn() when we await.
        is_gpn_trigger = user_message.strip().upper() in (
            "GENERATE_PLAN_NOW",
            "GENERATE_PLAN_TRIGGER",
        ) or (classifier.reasoning and "GENERATE_PLAN_NOW" in classifier.reasoning)
        _feasibility_task: asyncio.Task | None = None
        if classifier.intent == "PLANNING" and not is_gpn_trigger:
            dest = state.get("trip_plan", {}).get("destination") or classifier.destination
            activity_settings_fc = state.get("trip_settings", {}).get("activity_settings", {})
            _feasibility_candidates = [
                c for c in activity_settings_fc.get("categories", []) if c in TIER1_SPECIALIST_NAMES
            ]
            existing_plans = state.get("specialist_plans", {})
            if existing_plans:
                _feasibility_candidates = [
                    t
                    for t in _feasibility_candidates
                    if t not in existing_plans or not existing_plans[t]
                ]
            if dest and _feasibility_candidates:
                from app.planner.services.feasibility_service import batch_feasibility_precheck

                _feasibility_task = asyncio.create_task(
                    batch_feasibility_precheck(_feasibility_candidates, dest)
                )

        # Step 4b: Compute plan while feasibility runs in the background.
        plan = plan_turn(classifier, state)

        # Step 4c: Await feasibility results and re-plan if infeasible topics found.
        # Cancel the speculative task for response-only plans (no dispatch needed).
        if _feasibility_task is not None and _is_response_only_plan(plan):
            _feasibility_task.cancel()
            _feasibility_task = None
        if _feasibility_task is not None:
            try:
                feasibility_prechecks = await _feasibility_task
            except Exception:
                feasibility_prechecks = None
            if feasibility_prechecks:
                state["turn_meta"]["feasibility_prechecks"] = feasibility_prechecks
                logger.info(
                    "[coordinator] Feasibility pre-check: %s",
                    {t: s for t, (s, _, _) in feasibility_prechecks.items()},
                )
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

            plan = plan_turn(classifier, state)

        # Step 4c: Finalize the execution plan after any feasibility prechecks.
        logger.info(
            "[coordinator] Execution plan: %s (steps=%d, est_llm=%d)",
            plan.reason,
            len(plan.steps),
            plan.estimated_llm_calls,
        )

        continuity = _date_change_continuity_details(classifier, state, plan)
        if continuity is not None:
            logger.info(
                "[coordinator] Date change continuity: "
                "safe_tail_extension=%s same_month_bucket=%s same_activity_settings=%s "
                "dispatch=%s preserve=%s",
                str(continuity["safe_tail_extension"]).lower(),
                str(continuity["same_month_bucket"]).lower(),
                str(continuity["same_activity_settings"]).lower(),
                continuity["dispatch"],
                continuity["preserve"],
            )

        if (
            classifier.intent == "PLANNING"
            and classifier.change_type == ChangeType.DATE_CHANGE
            and not any(s.step_type == StepType.DISPATCH_SPECIALISTS for s in plan.steps)
        ):
            _refresh_preserved_specialist_section_metadata(
                state,
                _compute_preserve_list(classifier, state),
            )

        # Build infeasible sections when no DISPATCH_SPECIALISTS step will run
        # (all topics infeasible → dispatch_list is empty). When a dispatch step
        # DOES run, its _execute_step branch builds infeasible sections AFTER the
        # full invalidation wipe, preventing the wipe from destroying them.
        has_dispatch_step = any(s.step_type == StepType.DISPATCH_SPECIALISTS for s in plan.steps)
        if not has_dispatch_step and classifier.intent == "PLANNING":
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

        # Step 5: Execute plan steps
        # Group parallel steps together
        sequential_groups: List[List[ExecutionStep]] = []
        current_group: List[ExecutionStep] = []
        seen_parallel_ids: set[int] = set()

        for step in plan.steps:
            if step.step_type == StepType.GENERATE_RESPONSE:
                # Response generation is always last, handled separately
                continue

            if step.parallel_with is not None:
                # This step runs in parallel with another
                seen_parallel_ids.add(id(step))
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
                if id(step) in seen_parallel_ids:
                    # Already added to a parallel group
                    continue
                if current_group:
                    sequential_groups.append(current_group)
                    current_group = []
                current_group = [step]

        if current_group:
            sequential_groups.append(current_group)

        for group in sequential_groups:
            if cancel_event and cancel_event.is_set():
                logger.info("[coordinator] Cancel event set — stopping step execution")
                break

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
                if _is_step_event_stream(step_event):
                    async for event in step_event:
                        yield event
                else:
                    for event in _normalize_step_events(step_event):
                        yield event

                if node_name:
                    yield _node_status(node_name, "completed", label, icon, duration)
            else:
                # Parallel group
                completed_parallel_ids: set[int] = set()
                for step in group:
                    label, icon, duration = _step_status_info(step, state, classifier)
                    node_name = _step_node_name(step)
                    if node_name:
                        yield _node_status(node_name, "started", label, icon, duration)

                async for completed_step, step_events, completed in _execute_parallel_group(
                    group,
                    state,
                    classifier,
                    user_message,
                    session_id=session_id,
                ):
                    for step_event in step_events:
                        yield step_event

                    if not completed:
                        continue

                    completed_parallel_ids.add(id(completed_step))
                    label, icon, duration = _step_status_info(completed_step, state, classifier)
                    node_name = _step_node_name(completed_step)
                    if node_name:
                        yield _node_status(node_name, "completed", label, icon, duration)

                for step in group:
                    if id(step) in completed_parallel_ids:
                        continue
                    label, icon, duration = _step_status_info(step, state, classifier)
                    node_name = _step_node_name(step)
                    if node_name:
                        yield _node_status(node_name, "completed", label, icon, duration)

        if cancel_event and cancel_event.is_set():
            logger.info("[coordinator] Cancel event set — skipping response/envelope")
            return

        # Compute field diffs for conversationalist context
        _pre_briefs = state.get("_pre_change_briefs", {})
        if isinstance(_pre_briefs, dict) and _pre_briefs:
            field_diffs: Dict[str, Any] = {}
            for key in ("trip_plan", "trip_settings"):
                pre_val = _pre_briefs.get(key, {})
                post_val = state.get(key, {})
                if isinstance(pre_val, dict) and isinstance(post_val, dict):
                    for field in set(list(pre_val.keys()) + list(post_val.keys())):
                        old = pre_val.get(field)
                        new = post_val.get(field)
                        if old != new:
                            field_diffs[f"{key}.{field}"] = {"from": old, "to": new}
            if field_diffs:
                turn_meta = state.setdefault("turn_meta", {})
                turn_meta["field_diffs"] = field_diffs

        # Step 6: Generate response (LLM only when planned)
        should_generate_response = any(
            step.step_type == StepType.GENERATE_RESPONSE for step in plan.steps
        )
        assistant_message = ""

        if should_generate_response:
            yield _node_status("response", "started", "Writing response...", "message-square", 800)

            response_chunks: List[str] = []
            try:
                async for chunk in _generate_response_streaming(state, classifier, user_message):
                    response_chunks.append(chunk)
                    yield {"type": "token", "data": chunk}
            except Exception as resp_err:
                logger.error(
                    "[coordinator] Response generation failed: %s",
                    resp_err,
                    exc_info=True,
                )
                _tm = state.setdefault("turn_meta", {})
                _tm["response_degraded"] = True
                # Classify error type for frontend retry UX
                err_str = str(resp_err).lower()
                if "429" in err_str or "quota" in err_str or "rate" in err_str:
                    _tm["response_error_type"] = "rate_limit"
                elif "timeout" in err_str or isinstance(resp_err, TimeoutError):
                    _tm["response_error_type"] = "timeout"
                else:
                    _tm["response_error_type"] = "generation_error"

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
        # Emit the complete envelope FIRST without blocking on partner enrichment.
        # The enrichment task (started during BUILD_ITINERARY) runs concurrently
        # and its results are applied via follow-up partials below.
        await _cleanup_unsplash_task(cancel=False, timeout=2.0)
        await _refresh_enrichment_states(state, session_id)

        pre_enrichment_day_cards_hash = stable_hash(state.get("day_cards", []))
        pre_enrichment_tiles_hash = stable_hash(_flatten_tiles_payload(state.get("tiles", {})))

        envelope = _build_envelope(state, user_message, session_id, assistant_message)

        wall_ms = int((time.monotonic() - wall_start) * 1000)
        _structured_log(
            "turn_complete",
            session_id=session_id,
            reason=plan.reason,
            wall_ms=wall_ms,
            steps=len(plan.steps),
        )

        yield {"type": "complete", "data": envelope}

        # Non-blocking enrichment: await the background partner enrichment
        # task AFTER the complete envelope has been emitted.  streaming.py
        # continues to iterate the generator after capturing the complete
        # event, so any follow-up partials are forwarded to the client
        # before the SSE complete payload is flushed.
        await _await_pending_itinerary_enrichment(state)

        post_enrichment_day_cards = state.get("day_cards", [])
        day_cards_changed = (
            isinstance(post_enrichment_day_cards, list)
            and stable_hash(post_enrichment_day_cards) != pre_enrichment_day_cards_hash
        )

        post_enrichment_tiles_payload = _flatten_tiles_payload(state.get("tiles", {}))
        tiles_changed = stable_hash(post_enrichment_tiles_payload) != pre_enrichment_tiles_hash

        if isinstance(post_enrichment_day_cards, list):
            enrichment_event = _tile_enrichment_partial_event(
                state,
                post_enrichment_day_cards,
                post_enrichment_tiles_payload,
                day_cards_changed=day_cards_changed,
                tiles_changed=tiles_changed,
            )
            if enrichment_event is not None:
                yield enrichment_event

        if day_cards_changed and isinstance(post_enrichment_day_cards, list):
            yield _day_cards_partial_event(state, post_enrichment_day_cards)

        if tiles_changed:
            tiles_partial_data: dict[str, Any] = {
                "kind": "tiles",
                "payload": post_enrichment_tiles_payload,
            }
            turn_meta = state.get("turn_meta") or {}
            if turn_meta.get("tiles_replaced"):
                tiles_partial_data["tiles_replaced"] = True
            yield {"type": "partial", "data": tiles_partial_data}

    except Exception as exc:
        await _cleanup_unsplash_task(cancel=True)
        _structured_log(
            "llm_error",
            session_id=session_id,
            level=logging.ERROR,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        logger.error("[coordinator] Turn failed: %s", exc, exc_info=True)
        yield {"type": "error", "message": str(exc)}
    finally:
        await _cleanup_unsplash_task(cancel=True)
        await _cleanup_pending_itinerary_enrichment(state)


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
        step_tile_types = set(step.params.get("tile_types", []))
        parts: list[str] = []
        if (not step_tile_types or "hotels" in step_tile_types) and booking.get("hotels") != "off":
            parts.append("hotels")
        if (not step_tile_types or "flights" in step_tile_types) and booking.get("flights") not in (
            "off",
            None,
        ):
            parts.append("flights")
        if (not step_tile_types or "activities" in step_tile_types) and cats:
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
