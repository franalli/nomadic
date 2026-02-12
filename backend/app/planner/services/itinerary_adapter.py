"""
Thin bridge from GraphState to ItineraryBuilder.

Avoids circular import: plan_graph imports from services, services cannot
import from plan_graph. The flatten helper is duplicated here (~10 lines).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.planner.state import GraphState
from app.planner.state.typed_meta import get_trip_settings
from app.services.itinerary_builder import (
    ItineraryBuilder,
    ItineraryBuilderInput,
    ItineraryResult,
    PreferenceOverrideInput,
)

logger = logging.getLogger(__name__)


def _flatten_tiles(tiles_by_category: Optional[Dict[str, List]]) -> Dict[str, Any]:
    """Flatten category-grouped tiles to ID-based map (what builder expects).

    Duplicated from plan_graph._flatten_tiles_to_id_map to avoid circular import.
    """
    if not tiles_by_category:
        return {}
    flat: Dict[str, Any] = {}
    for _category, tile_list in tiles_by_category.items():
        if not isinstance(tile_list, list):
            continue
        for tile in tile_list:
            if isinstance(tile, dict):
                tile_id = tile.get("id")
                if tile_id:
                    flat[tile_id] = tile
    return flat


def build_itinerary_from_state(state: GraphState) -> Optional[ItineraryResult]:
    """Build itinerary from graph state. Returns None if preconditions not met."""
    plan = state.trip_plan
    if not plan.start_date or not plan.end_date:
        return None

    sections = state.metadata.get("strategy_sections", [])
    if not sections:
        return None

    settings = get_trip_settings(state)

    # Build preferences from user-pinned tiles (fill-day Browse→Add + auto-fill)
    pinned_tiles = state.metadata.get("user_pinned_tiles", {})
    preferences = None
    if pinned_tiles:
        day_map: Dict[str, int] = {}
        priority_map: Dict[str, str] = {}
        for tid, pinned in pinned_tiles.items():
            pday = pinned.get("preferred_day")
            if pday is not None:
                day_map[tid] = pday
            priority_map[tid] = pinned.get("priority", "high")
        preferences = PreferenceOverrideInput(
            preferred_activity_ids=list(pinned_tiles.keys()),
            pinned_day_map=day_map,
            pinned_priority_map=priority_map,
        )

    builder_input = ItineraryBuilderInput(
        start_date=plan.start_date,
        end_date=plan.end_date,
        strategy_sections=sections,
        tiles=_flatten_tiles(state.tiles),
        destination=plan.destination,
        origin=plan.origin,
        preferences=preferences,
        activity_categories=settings.activity_settings.categories or None,
        activity_day_preferences=settings.activity_settings.day_preferences or None,
    )
    builder = ItineraryBuilder()
    return builder.build(builder_input)
