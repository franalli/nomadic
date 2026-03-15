"""
Thin bridge from GraphState to ItineraryBuilder.

Avoids circular import: plan_graph imports from services, services cannot
import from plan_graph.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from app.planner.state import GraphState
from app.planner.state.typed_meta import get_trip_settings
from app.services.itinerary_builder import (
    ItineraryBuilder,
    ItineraryBuilderInput,
    ItineraryResult,
    PreferenceOverrideInput,
)
from app.utils.tile_utils import flatten_tiles_to_id_map

logger = logging.getLogger(__name__)


def _serialize_canonical_constraints(state: GraphState) -> list[dict]:
    """Serialize canonical TripPlan constraints into builder-ready dicts."""
    serialized: list[dict] = []
    for constraint in state.trip_plan.constraints:
        if hasattr(constraint, "model_dump"):
            serialized.append(constraint.model_dump())
        elif isinstance(constraint, dict):
            serialized.append(dict(constraint))
    return serialized


def build_itinerary_from_state(state: GraphState) -> Optional[ItineraryResult]:
    """Build itinerary from graph state. Returns None if preconditions not met."""
    plan = state.trip_plan
    if not plan.start_date or not plan.end_date:
        return None

    sections = state.metadata.get("strategy_sections", [])
    if not sections:
        return None

    settings = get_trip_settings(state)
    activities_off = settings.booking_types.activities == "off"
    raw_categories = settings.activity_settings.categories

    # Keep category semantics aligned with streaming.expand-itinerary:
    # - activities=off  -> []    (explicit clear, skip all activity placement)
    # - activities=on/suggested with no categories -> None (no category filter)
    # - activities=on/suggested with categories    -> categories list
    if activities_off:
        activity_categories: list[str] | None = []
    elif raw_categories:
        activity_categories = raw_categories
    else:
        activity_categories = None

    # Build preferences from user-pinned tiles (fill-day Browse→Add + auto-fill)
    pinned_tiles = state.metadata.get("user_pinned_tiles", {})
    preferences = None
    if pinned_tiles:
        # Filter out pinned tiles whose category no longer matches active categories.
        # Prevents stale fill-day tiles (e.g. diving) from surviving a category change to yoga.
        active_cats = set(c.lower() for c in (settings.activity_settings.categories or []))
        day_map: Dict[str, int] = {}
        priority_map: Dict[str, str] = {}
        filtered_ids: list[str] = []
        for tid, pinned in pinned_tiles.items():
            tile_data = pinned.get("tile", pinned)
            tile_cat = ((tile_data.get("meta") or {}).get("category", "") or "").lower()
            # Keep tile if: no active categories (mixed mode), or tile matches an active category,
            # or tile has no identifiable category (safety: don't drop unknowns)
            if active_cats and tile_cat and tile_cat not in active_cats:
                logger.info(
                    f"[itinerary_adapter] Pruned stale pinned tile {tid} "
                    f"(cat={tile_cat}, active={active_cats})"
                )
                continue
            filtered_ids.append(tid)
            pday = pinned.get("preferred_day")
            if pday is not None:
                day_map[tid] = pday
            priority_map[tid] = pinned.get("priority", "high")
        if filtered_ids:
            preferences = PreferenceOverrideInput(
                preferred_activity_ids=filtered_ids,
                pinned_day_map=day_map,
                pinned_priority_map=priority_map,
            )

    builder_input = ItineraryBuilderInput(
        start_date=plan.start_date,
        end_date=plan.end_date,
        strategy_sections=sections,
        tiles=flatten_tiles_to_id_map(state.tiles),
        destination=plan.destination,
        origin=plan.origin,
        preferences=preferences,
        activity_categories=activity_categories,
        activity_day_preferences=settings.activity_settings.day_preferences or None,
        activities_per_day=settings.activity_settings.activities_per_day,
        adults=plan.adults or 1,
        children=plan.children or 0,
        user_pinned_tiles=pinned_tiles or None,
        canonical_constraints=_serialize_canonical_constraints(state),
    )
    builder = ItineraryBuilder()
    return builder.build(builder_input)
