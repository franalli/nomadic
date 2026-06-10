"""
Coordinator -- shared data/envelope helpers for the planner.

The deterministic coordinator DAG (``execute_turn``/``plan_turn``/step execution)
has been removed. Planner turns now flow through the LangChain ``create_agent``
loop via ``app.planner.services.agent_runner.run_agent_turn_streaming``.

This module retains the shared, pure-Python helpers the agent path still depends
on: envelope construction (``_build_envelope`` and its closure), settings merging
(``_merge_doc_settings``), trip-state summarization, itinerary/partner enrichment,
and data-normalization utilities.

SSE event contract emitted by the agent path:
  - {"type": "token",       "data": str}
  - {"type": "node_status", "data": {...}}
  - {"type": "partial",     "data": {kind, payload}}
  - {"type": "feasibility_warning", "data": {topic, status, reason, alternative}}
  - {"type": "complete",    "data": {...}}
  - {"type": "error",       "message": str}
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from app.config import settings
from app.planner.hashing import stable_hash, stable_hash_short
from app.planner.specialist_registry import (
    SPECIALIST_REGISTRY,
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

_USER_DISABLED_BOOKING_TYPES_KEY = "user_disabled_booking_types"
_TRACKED_BOOKING_TYPE_KEYS = frozenset({"flights", "hotels", "activities", "ground_transport"})


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


# ---------------------------------------------------------------------------
# SSE event helpers
# ---------------------------------------------------------------------------


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
            if _has_vendor_media(tile):  # vendor already supplied the image -- skip GP photo
                return
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


def _viator_product_code_from_block(block: Dict[str, Any]) -> str | None:
    """Extract a Viator product code from a placed day-card block, or None.

    Only returns a code when the block's partner data is Viator (never GYG) so a
    GYG product id is not sent to the Viator API. Checks, in order:
    block-level ``partner_product_id``/id, then the merged ``booked_tile``
    (``partner_product_id`` -> ``meta.viator_product_code`` -> ``viator_{code}`` id).
    """

    def _is_viator(obj: Dict[str, Any]) -> bool:
        provider = str(obj.get("provider") or "").strip().lower()
        partner = str(obj.get("partner") or "").strip().lower()
        if provider == "viator" or partner == "viator":
            return True
        meta = obj.get("meta")
        return isinstance(meta, dict) and bool(meta.get("viator_product_code"))

    def _code(obj: Dict[str, Any]) -> str | None:
        meta = obj.get("meta") if isinstance(obj.get("meta"), dict) else {}
        candidate = (
            str(meta.get("viator_product_code") or "").strip()
            or str(obj.get("partner_product_id") or "").strip()
        )
        if not candidate:
            obj_id = str(obj.get("id") or "").strip()
            if obj_id.startswith("viator_"):
                candidate = obj_id[len("viator_") :]
        return candidate or None

    if _is_viator(block):
        code = _code(block)
        if code:
            return code
    booked_tile = block.get("booked_tile")
    if isinstance(booked_tile, dict) and _is_viator(booked_tile):
        return _code(booked_tile)
    return None


async def _resolve_viator_block_geo(day_cards: list[Dict[str, Any]], destination: str = "") -> None:
    """Set distinct per-product Viator centers on centroid/coord-less placed blocks.

    Scans placed (non-buffer, non-arrival/departure) blocks for Viator product
    codes, batch-resolves each code's first-itinerary-POI center via
    ``resolve_product_geo_batch`` (one concurrent product-detail fetch per code +
    ONE locations/bulk call, L1+L2 cached), then stamps ``block["coordinates"]``
    ({lat,lng}) on every block whose code resolved. Mutates ``day_cards`` in place.
    Blocks that already carry a REAL per-POI coord (not the destination centroid)
    are skipped -- centroid-stamped blocks (the common stacked case) qualify, which
    is why we resolve the centroid here (best-effort, cached) just like the GP gate.
    """
    from app.services.viator_provider import resolve_product_geo_batch

    centroid: tuple[float, float] | None = None
    if destination:
        try:
            from app.tile_service.google_places_provider import _geocode_destination_async

            centroid = await _geocode_destination_async(destination)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("[coordinator] Viator geo pre-pass centroid geocode failed: %s", exc)

    block_codes: list[tuple[Dict[str, Any], str]] = []
    for card in day_cards:
        if not isinstance(card, dict):
            continue
        for block in card.get("blocks", []):
            if not isinstance(block, dict) or block.get("is_buffer"):
                continue
            at = (block.get("activity_type") or "").lower()
            if at in ("arrival", "departure", "check_in", "check_out", "free_day"):
                continue
            # Skip blocks that already carry a real per-POI coordinate. Centroid-only
            # geo (the stacked case) counts as not-yet-resolved so it qualifies.
            if not _is_centroid_coords(block.get("coordinates"), centroid):
                continue
            code = _viator_product_code_from_block(block)
            if code:
                block_codes.append((block, code))

    if not block_codes:
        return

    geo_by_code = await resolve_product_geo_batch([code for _, code in block_codes])
    if not geo_by_code:
        return

    stamped = 0
    for block, code in block_codes:
        center = geo_by_code.get(code)
        if center:
            block["coordinates"] = {"lat": center["lat"], "lng": center["lng"]}
            stamped += 1
    if stamped:
        logger.info(
            "[coordinator] Viator geo pre-pass: stamped %d/%d placed blocks with "
            "distinct product centers",
            stamped,
            len(block_codes),
        )


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

    # Viator geo pre-pass: resolve a distinct per-product center for PLACED blocks
    # that carry a Viator product code but only centroid/coord-less geo, BEFORE the
    # GP gate (so resolved blocks read as real per-POI coords and GP naturally skips
    # them). Independent of the GP enable flags -- a Viator deployment with GP off
    # still gets distinct pins. Runs even when the activity pool is thin because
    # blocks can carry a booked_tile product code without a matching pool tile.
    has_viator = settings.viator_enabled and settings.viator_api_key
    if has_viator and destination and day_cards:
        await _resolve_viator_block_geo(day_cards, destination)

    # Decide whether to run the post-build GP geocode pass. A block needs GP when it
    # lacks a REAL per-POI coordinate -- partner deeplink/image alone is NOT enough,
    # because every coord-less Viator/specialist block is stamped with the same
    # destination centroid (which stacks all markers on one point). We resolve the
    # centroid once (cached) so centroid-only geo counts as "still needs geocoding".
    _gate_centroid: tuple[float, float] | None = None
    if (
        settings.use_google_places_provider
        and settings.google_places_enrichment_enabled
        and destination
    ):
        from app.tile_service.google_places_provider import _geocode_destination_async

        _gate_centroid = await _geocode_destination_async(destination)

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
            # Real per-POI coords => no GP needed; missing/centroid coords => needs GP.
            if _is_centroid_coords(block.get("coordinates"), _gate_centroid):
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Specialist dispatch
# ---------------------------------------------------------------------------


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


def _inject_specialist_tiles_into_state(state: Dict[str, Any]) -> None:
    """Inject specialist ``content_added`` items as real tiles into state.

    Specialist advice (``get_specialist_advice``) produces named activities
    (e.g. "USAT Liberty Shipwreck Shore Dive") that live only in
    ``strategy_sections[].content_added`` -- they are shown in the Advice panel
    but are NOT in ``tiles.activities``, so the itinerary builder (which
    synthesizes day-card sections from activity tiles) never places them.

    This converts each feasible specialist section's content into activity tiles
    (``meta.specialist_type`` set so the builder groups them) and writes the
    resulting ``tile_id`` back onto the ``content_added`` items. Stale specialist
    tiles from prior runs are dropped so replans stay consistent.

    Must run BEFORE the builder reads ``state["tiles"]`` so the dives flow
    through the same placement path as the generic search_tiles activities.
    Mutates ``state`` in place (idempotent: dedup by deterministic tile id).
    """
    strategy_sections = state.get("strategy_sections", [])
    if not strategy_sections:
        return
    destination = state.get("trip_plan", {}).get("destination", "")
    if not destination:
        return

    # Normalized current destination ("Cozumel, Mexico" -> "cozumel") for
    # comparing against each section's destination stamp.
    def _norm_dest(d: str) -> str:
        return (d or "").strip().lower().split(",")[0].strip()

    current_dest = _norm_dest(destination)

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

        # Skip sections built for a DIFFERENT destination. After a destination
        # change the strategy_sections clear is a no-op (the list reducer ignores
        # an empty-list update), so the previous destination's section can linger;
        # and a build batched in the same round as get_specialist_advice can read
        # it before the fresh section merges. The section's destination stamp
        # ("subtitle", set by build_specialist_section) is the source of truth --
        # never turn another destination's activities into tiles for this trip.
        sec_dest = _norm_dest(section.get("subtitle", ""))
        if current_dest and sec_dest and sec_dest != current_dest:
            logger.info(
                "[coordinator] Skipping stale specialist section '%s' "
                "(built for %r, current destination %r)",
                topic,
                sec_dest,
                current_dest,
            )
            continue

        spec_tiles = _specialist_content_to_tiles(topic, section, destination)

        # Write tile_id back onto content_added items so any consumer that reads
        # the real sections (and the builder's Phase 2.5 id-match) can link them.
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

    # Remove stale specialist tiles from previous runs (keep only current ones).
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


# Geo within this radius (km) of the destination centroid is treated as
# "centroid-only" (i.e. not a real per-POI coordinate). Used to detect blocks
# whose coords are just the destination center so they still get geocoded by
# title -> distinct map markers.
_CENTROID_RADIUS_KM = 1.0


def _coords_to_lat_lng(coords: Any) -> tuple[float, float] | None:
    """Normalize a coordinate value ([lng, lat] list or {lat,lng}/{...} dict) to (lat, lng)."""
    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
        lng, lat = coords[0], coords[1]
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            return (float(lat), float(lng))
        return None
    if isinstance(coords, dict):
        lat = coords.get("lat")
        lng = coords.get("lng")
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            return (float(lat), float(lng))
    return None


def _is_centroid_coords(coords: Any, centroid: tuple[float, float] | None) -> bool:
    """True when coords are missing or essentially the destination centroid.

    Centroid-only geo is NOT a real per-POI coordinate: every coord-less
    Viator/specialist block gets stamped with the same destination center, so
    all markers pile on one point. We treat those as "not yet enriched" so the
    post-build pass geocodes them by title. Robust to the geocode used for the
    centroid differing slightly from the one that produced the block coords
    (haversine threshold), and to the destination string mismatching.
    """
    from app.utils.geo import haversine_km

    point = _coords_to_lat_lng(coords)
    if point is None:
        return True
    if centroid is None:
        return False
    return haversine_km(point, centroid) <= _CENTROID_RADIUS_KM


async def _post_build_enrich_placed_activities(
    state: Dict[str, Any], day_cards: list[Dict[str, Any]]
) -> None:
    """Enrich placed activity blocks with Google Places data after builder runs.

    Only enriches blocks that were actually placed in the itinerary (not dropped).
    A block is "needs enrichment" when it lacks a google_place_id OR carries only
    centroid-level geo (every coord-less Viator/specialist tile gets stamped with
    the same destination center, which stacks all markers on one point). Those
    blocks are geocoded by title (Places Text Search via enrich_activities_with_places)
    so each placed POI gets distinct real coordinates -> distinct map markers.

    Cost: only PLACED blocks are geocoded (never the browse pool); every result is
    cached (L1+L2) keyed by normalized title|destination. The destination centroid
    is kept only as a last-resort fallback when geocoding fails.
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
            _geocode_destination_async,
            _normalize_title_for_cache,
            build_signed_photo_url,
            enrich_activities_with_places,
        )

        # Resolve the destination centroid once (cached) so we can detect blocks
        # whose coords are just the destination center (centroid-stacking) and
        # treat them as not-yet-geocoded. Also used as the last-resort fallback.
        centroid = await _geocode_destination_async(destination)

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

            block_has_viator = _has_vendor_media(block)  # vendor media (Viator/GYG) present
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
                # Skip only blocks that already have a real per-POI coordinate.
                # Centroid-only geo (every coord-less Viator/specialist tile gets
                # stamped with the destination center) is treated as not-yet-geocoded
                # so the title geocode runs and markers stop stacking on one point.
                if block.get("google_place_id") and not _is_centroid_coords(
                    block.get("coordinates"), centroid
                ):
                    continue
                summary = block.get("summary", "")
                if summary.strip().lower().startswith("free day"):
                    continue
                if not summary:
                    continue
                # Apply booked-tile fallback (sets deeplink/image/price + best-effort
                # coords), but only short-circuit when it yielded a REAL per-POI coord.
                # A Viator booked_tile often carries only the destination centroid, so
                # we let those fall through to the title geocode below.
                if _apply_booked_tile_fallback(block) and not _is_centroid_coords(
                    block.get("coordinates"), centroid
                ):
                    _reused_count += 1
                    continue

                booked_tile = block.get("booked_tile")
                title_candidates: list[str] = []
                # Prefer the specialist's clean place name (e.g. "Kuta Beach, Bali")
                # over the lesson-phrased title/summary ("Intro Surf Lesson at Kuta
                # Beach"). Activity-phrased strings fail to geocode to a single POI;
                # the structured ``location`` resolves cleanly. Only used when the
                # specialist supplied it — coord-less generic tours have no location,
                # so they still fall through to the no-centroid-stamp guardrail below.
                block_location = str(block.get("location") or "").strip()
                if block_location:
                    title_candidates.append(block_location)
                if isinstance(booked_tile, dict):
                    booked_title = str(booked_tile.get("title") or "").strip()
                    if booked_title and booked_title not in title_candidates:
                        title_candidates.append(booked_title)
                if summary and summary not in title_candidates:
                    title_candidates.append(summary)

                existing = None
                for candidate in title_candidates:
                    existing = _gp_by_title.get(_normalize_title_for_cache(candidate))
                    if existing:
                        break
                if existing:
                    block_has_viator = _has_vendor_media(block)  # vendor media (Viator/GYG) present
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
                # Pass real coords through (so enrich short-circuits and we don't pay
                # for a redundant search), but force None for missing/centroid-only geo
                # so enrich_activities_with_places actually fires the title search.
                proxy_coords = None
                if not _is_centroid_coords(coords, centroid):
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
        # Geocode EVERY placed block (not just enrichment_cap=3): the goal is one
        # distinct marker per placed POI. Placed-block count is naturally bounded by
        # trip length and each title geocode is L1+L2 cached, so re-builds re-pay
        # nothing. The default cap still governs the browse/tier1/tier2 paths.
        enriched = await enrich_activities_with_places(
            proxies,
            destination,
            path_label="post_build_enrich",
            travelers=_travelers,
            enrich_cap=len(proxies),
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
            block_has_viator = _has_vendor_media(block)  # vendor media (Viator/GYG) present
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

        # No centroid stamp on geocode misses. Generic multi-stop marketing tours
        # ("private full-day driver", "shore excursions", "choose your route") have
        # no single geocodable POI; stamping them all with the destination centroid
        # collapses every such block onto one point and re-stacks the map. Leaving
        # their coordinates absent is honest — a private full-day tour has no single
        # location — and the frontend map (normalizeMapItems) drops coord-less items
        # gracefully, so the block stays in the itinerary timeline with no map pin.
        # Real per-POI coords resolved above are always preserved.
        _unplaced = sum(
            1
            for _, (day_idx, block_idx) in zip(proxies, block_locations, strict=True)
            if not day_cards[day_idx]["blocks"][block_idx].get("coordinates")
        )
        if _unplaced:
            logger.info(
                "[coordinator] %d placed blocks left coord-less (un-geocodable "
                "multi-stop tour / geocode miss) — no centroid stamp, no map pin",
                _unplaced,
            )

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


_VENDOR_MEDIA_HOSTS = ("viator", "getyourguide", "gyg", "tripadvisor")


def _has_vendor_media(obj: Dict[str, Any]) -> bool:
    """True when a partner (Viator/GYG) already supplied this tile/block's image or
    booking link. Vendor-first cost guard: Google Places must NOT mint a (paid) photo
    over media a vendor already provides -- GP photos are reserved for tiles/blocks with
    no vendor media (gap-fill only). Works for both tiles (partner fields) and day-card
    blocks (vendor deeplink / vendor-hosted image_url)."""
    if not isinstance(obj, dict):
        return False
    if _has_partner_enrichment(obj):
        return True
    deeplink = (obj.get("deeplink") or "").lower()
    if any(h in deeplink for h in _VENDOR_MEDIA_HOSTS):
        return True
    image = (obj.get("image_url") or "").lower()
    if image and not image.startswith("/api/media/"):
        return any(h in image for h in _VENDOR_MEDIA_HOSTS)
    return False


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


# ---------------------------------------------------------------------------
# Itinerary building (Phase 2: bridge to ItineraryBuilder)
# ---------------------------------------------------------------------------


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
    # The agent path carries the reset flags in turn_meta (top-level keys are not
    # NomadicAgentState channels, so LangGraph drops them from tool updates); the
    # legacy top-level keys are still honoured for direct callers.
    coordinator_reset = bool(
        state.get("_coordinator_reset", False) or turn_meta.get("coordinator_reset", False)
    )

    # Generate suggestion chips. Prefer the LLM-generated, conversation+state-aware
    # chips produced concurrently in agent_runner (under _llm_suggestion_chips) when
    # they are a non-empty list of valid chip dicts; otherwise fall back to the
    # deterministic template generator. The _reset_pending override below still wins.
    llm_chips = state.get("_llm_suggestion_chips")
    if coordinator_reset:
        # Confirmed reset: the in-loop state still holds the OLD trip (the
        # extract merger skips all field merges on the confirm turn), so both
        # the LLM chips and state-derived chips would describe the trip being
        # wiped. Generate from an EMPTY state view instead so the envelope --
        # and the SSE persist path that stores chips from it -- carries the
        # post-reset bootstrap chips (the generator's no-destination branch
        # produces the "Pick a destination" CTA).
        suggestion_chips = _generate_chips_from_state(
            _normalize_state_for_chips(
                {
                    "trip_plan": {},
                    "trip_settings": {},
                    "tiles": {},
                    "day_cards": [],
                    "strategy_sections": [],
                    "turn_meta": {},
                }
            )
        )
    elif (
        isinstance(llm_chips, list)
        and llm_chips
        and all(isinstance(c, dict) and c.get("message") for c in llm_chips)
    ):
        suggestion_chips = llm_chips
    else:
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
    if state.get("_reset_pending") or turn_meta.get("reset_pending"):
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
            []
            if coordinator_reset
            else day_cards
            if day_cards
            else ([] if (builder_ran or turn_meta.get("removal_pruned")) else None)
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


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
