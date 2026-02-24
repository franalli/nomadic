"""
build_itinerary tool -- wraps ItineraryBuilder.build().

Builds a day-by-day itinerary from tiles and constraints. Pure Python
scheduling with no LLM calls. Parses tile/constraint JSON strings,
constructs ItineraryBuilderInput, and delegates to the existing builder.

When running inside a ``create_agent`` graph the ``InjectedState``
annotation auto-populates trip fields and tiles/constraints from agent
state so the LLM does not need to serialize large JSON payloads.

State mutation happens in TurnLifecycleMiddleware, not here.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from typing_extensions import Annotated

from app.planner.tools._parsing import parse_constraints_json, parse_tiles_json
from app.utils.tile_utils import flatten_tiles_to_id_map

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_strategy_sections(
    tiles_by_category: Dict[str, List[Dict[str, Any]]],
    constraints: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build minimal strategy sections from tiles.

    This is a simplified fallback for when real strategy sections aren't
    available from the agent context (e.g., the architect node hasn't run
    or the tool is invoked standalone). The full graph populates
    strategy_sections via the architect node; this approximation groups
    tiles by specialist type and attaches matching constraints so the
    builder has enough structure to generate a day skeleton.

    The ItineraryBuilder expects strategy_sections (output of the architect
    node). When the tool is called outside the full graph, we synthesize
    lightweight sections from the tile categories so the builder has
    something to work with.
    """
    sections: List[Dict[str, Any]] = []

    # Group activity tiles by specialist_type or category
    activity_tiles = tiles_by_category.get("activities", [])
    specialist_groups: Dict[str, List[Dict[str, Any]]] = {}
    for tile in activity_tiles:
        meta = tile.get("meta") or {}
        specialist = meta.get("specialist_type") or meta.get("category") or "local_expert"
        specialist_groups.setdefault(specialist, []).append(tile)

    for specialist_type, tiles in specialist_groups.items():
        content_added: List[Dict[str, Any]] = []
        for tile in tiles:
            content_added.append(
                {
                    "type": "activity",
                    "title": tile.get("title", ""),
                    "description": tile.get("subtitle", ""),
                    "duration_hours": (tile.get("meta") or {}).get("duration_hours", 3.0),
                    "tile_id": tile.get("id"),
                }
            )

        # Attach constraints that match this specialist
        section_constraints: List[Dict[str, Any]] = []
        for c in constraints:
            applies_to = c.get("applies_to_categories", [])
            if not applies_to or specialist_type in applies_to:
                section_constraints.append(
                    {
                        "constraint_id": c.get("constraint_id", ""),
                        "type": c.get("type", ""),
                        "rule": c.get("rule", ""),
                        "severity": c.get("severity", "soft"),
                        "reason": c.get("reason", ""),
                    }
                )

        sections.append(
            {
                "specialist_type": specialist_type,
                "content_added": content_added,
                "constraints_applied": section_constraints,
            }
        )

    # If no activity tiles, add a placeholder local_expert section
    # so the builder still generates a day skeleton
    if not sections:
        sections.append(
            {
                "specialist_type": "local_expert",
                "content_added": [],
                "constraints_applied": [],
            }
        )

    return sections


def _parse_id_list(ids_str: str) -> List[str]:
    """Parse comma-separated ID string into list."""
    if not ids_str:
        return []
    return [s.strip() for s in ids_str.split(",") if s.strip()]


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


@tool
async def build_itinerary(
    destination: str = "",
    start_date: str = "",
    end_date: str = "",
    origin: str = "",
    tiles_json: str = "{}",
    constraints_json: str = "[]",
    preferred_hotel_ids: str = "",
    preferred_activity_ids: str = "",
    # InjectedState -- auto-populated when running inside create_agent;
    # invisible to the LLM's tool-calling schema.  Provides trip_plan,
    # tiles, and constraints from agent state so the LLM does not need
    # to pass large JSON payloads.
    state: Annotated[Optional[dict], InjectedState] = None,
) -> dict:
    """Build a day-by-day itinerary from tiles and constraints. Requires
    destination and dates. Pure Python scheduling, no LLM calls."""
    from app.services.itinerary_builder import (
        ItineraryBuilder,
        ItineraryBuilderInput,
        PreferenceOverrideInput,
    )

    # When InjectedState is available, fill in defaults from agent state
    if state is not None:
        trip_plan: dict[str, Any] = state.get("trip_plan", {})
        destination = destination or trip_plan.get("destination", "")
        start_date = start_date or trip_plan.get("start_date", "")
        end_date = end_date or trip_plan.get("end_date", "")
        origin = origin or trip_plan.get("origin", "")

        # Pull tiles and constraints from state when not passed explicitly
        if tiles_json == "{}" and state.get("tiles"):
            try:
                tiles_json = json.dumps(state["tiles"])
            except (TypeError, ValueError):
                pass
        if constraints_json == "[]" and state.get("constraints"):
            try:
                constraints_json = json.dumps(state["constraints"])
            except (TypeError, ValueError):
                pass

    # Validate required fields
    if not destination or not start_date or not end_date:
        return {
            "success": False,
            "day_cards": [],
            "conflicts": [],
            "activities_placed": 0,
            "activities_dropped": 0,
            "error": "Missing required fields: destination, start_date, end_date",
        }

    # Parse JSON inputs
    tiles_by_category = parse_tiles_json(tiles_json)
    constraints = parse_constraints_json(constraints_json)

    # Build tile ID map for the builder
    tile_id_map = flatten_tiles_to_id_map(tiles_by_category)

    # Build strategy sections from tiles
    strategy_sections = _build_strategy_sections(tiles_by_category, constraints)

    # Build preferences if any IDs provided
    hotel_ids = _parse_id_list(preferred_hotel_ids)
    activity_ids = _parse_id_list(preferred_activity_ids)
    preferences: Optional[PreferenceOverrideInput] = None
    if hotel_ids or activity_ids:
        preferences = PreferenceOverrideInput(
            preferred_hotel_ids=hotel_ids,
            preferred_activity_ids=activity_ids,
        )

    # Construct builder input
    builder_input = ItineraryBuilderInput(
        start_date=start_date,
        end_date=end_date,
        strategy_sections=strategy_sections,
        tiles=tile_id_map,
        destination=destination,
        origin=origin or None,
        preferences=preferences,
    )

    # Run the builder
    try:
        builder = ItineraryBuilder()
        result = builder.build(builder_input)
    except Exception as exc:
        logger.error("[build_itinerary] Builder failed: %s", exc)
        return {
            "success": False,
            "day_cards": [],
            "conflicts": [],
            "activities_placed": 0,
            "activities_dropped": 0,
            "error": f"Builder error: {type(exc).__name__}: {exc}",
        }

    # Serialize day cards and conflicts
    day_cards_out: List[Dict[str, Any]] = []
    for card in result.day_cards:
        day_cards_out.append(card.model_dump())

    conflicts_out: List[Dict[str, Any]] = []
    for conflict in result.conflicts:
        conflicts_out.append(conflict.model_dump())

    activities_dropped = max(0, result.total_activities_input - result.total_activities_placed)

    logger.debug(
        "[build_itinerary] dest=%s days=%d placed=%d dropped=%d conflicts=%d",
        destination,
        len(day_cards_out),
        result.total_activities_placed,
        activities_dropped,
        len(conflicts_out),
    )

    return {
        "success": result.success,
        "day_cards": day_cards_out,
        "conflicts": conflicts_out,
        "activities_placed": result.total_activities_placed,
        "activities_dropped": activities_dropped,
        "warnings": result.warnings,
    }
