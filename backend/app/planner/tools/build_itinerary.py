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


def _merge_tiles_by_category(
    state_tiles: Dict[str, Any],
    llm_tiles: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Merge state/specialist tiles with LLM-supplied tiles, deduped by id.

    Both inputs are category-keyed (``{"activities": [...], "hotels": [...]}``).
    State tiles -- which include the specialist tiles just injected by
    ``_inject_specialist_tiles_into_state`` -- take precedence: when the same
    tile id appears in both, the state/specialist copy wins. Genuinely-fresh
    LLM search results (ids not already present) are still included so a real
    post-category-change refresh is not dropped.
    """
    merged: Dict[str, List[Dict[str, Any]]] = {}
    categories = set(state_tiles.keys()) | set(llm_tiles.keys())
    for category in categories:
        state_list = state_tiles.get(category)
        llm_list = llm_tiles.get(category)
        state_list = state_list if isinstance(state_list, list) else []
        llm_list = llm_list if isinstance(llm_list, list) else []

        out: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()
        # State/specialist tiles first so they win on id collisions.
        for tile in list(state_list) + list(llm_list):
            if not isinstance(tile, dict):
                continue
            tile_id = tile.get("id")
            if tile_id:
                if tile_id in seen_ids:
                    continue
                seen_ids.add(tile_id)
            out.append(tile)
        merged[category] = out
    return merged


def _builder_failure_message(error: Optional[str]) -> str:
    """Map an ItineraryResult.error sentinel to a human-readable message.

    The builder returns terse sentinels (e.g. ``"TRIP_TOO_SHORT"``) that mean
    nothing to the model. Translate the known ones into actionable guidance so
    the terminal agent turn can tell the user what is wrong and how to fix it,
    while still passing any other non-empty builder message through verbatim.
    """
    sentinel = (error or "").strip()
    if sentinel == "TRIP_TOO_SHORT":
        return (
            "This trip is too short to build an itinerary -- itineraries need at "
            "least 2 days. Ask the user to extend the travel dates by at least one day."
        )
    if sentinel in (
        "Invalid dates - cannot generate itinerary",
        "End date must be after start date",
    ):
        return f"{sentinel}. Ask the user to check the travel dates."
    # Unknown / internal failures (e.g. a raw exception string from the builder).
    # Do NOT leak internals into model-facing text -- keep it generic + actionable.
    return (
        "Could not build the itinerary due to an internal error. "
        "Ask the user to try again or adjust the trip details."
    )


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
        # Convert specialist advice (named dives/hikes in strategy_sections'
        # content_added) into real activity tiles BEFORE we read state["tiles"]
        # below -- otherwise the builder only sees generic search_tiles results
        # and the specialist's recommendations are silently dropped. In the
        # auto-build path `state` is the live final_state (same dict object), so
        # this also surfaces the dives in the envelope's ACTIVITIES section.
        try:
            from app.planner.coordinator import _inject_specialist_tiles_into_state

            _inject_specialist_tiles_into_state(state)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[build_itinerary] specialist tile injection failed: %s", exc)

        trip_plan: dict[str, Any] = state.get("trip_plan", {})
        destination = destination or trip_plan.get("destination", "")
        start_date = start_date or trip_plan.get("start_date", "")
        end_date = end_date or trip_plan.get("end_date", "")
        origin = origin or trip_plan.get("origin", "")

        if constraints_json == "[]" and state.get("constraints"):
            try:
                constraints_json = json.dumps(state["constraints"])
            except (TypeError, ValueError):
                pass

    # TODO(build-gate): The itinerary build should only fire once the user has
    # explicitly confirmed (a real state flag set by the frontend "Build" signal),
    # not on an LLM-supplied ``confirmed`` argument. The state-flag check belongs
    # here once the frontend Build signal is wired into NomadicAgentState. Until
    # then this tool builds unconditionally so normal operation is unblocked.

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
    llm_tiles_by_category = parse_tiles_json(tiles_json)
    constraints = parse_constraints_json(constraints_json)

    # Leg 2: state tiles (including the specialist tiles just injected by
    # _inject_specialist_tiles_into_state) are authoritative and must ALWAYS be
    # included, even when the LLM supplied a non-default tiles_json refresh.
    # Merge category-keyed dicts, deduping by id with state/specialist tiles
    # winning, so the diving tiles survive while genuinely-fresh search results
    # are still included.
    if state is not None and isinstance(state.get("tiles"), dict):
        tiles_by_category = _merge_tiles_by_category(state["tiles"], llm_tiles_by_category)
    else:
        tiles_by_category = llm_tiles_by_category

    # Build tile ID map for the builder
    tile_id_map = flatten_tiles_to_id_map(tiles_by_category)

    # Leg 1: use the authoritative strategy_sections from agent state when
    # available -- they carry the specialist content_added with POI coordinates
    # that _build_strategy_sections (a lossy synthesis fallback) drops. Only
    # synthesize sections when state has none (standalone / architect-not-run).
    # NOTE: this passes the LIVE state list (not a copy); the builder mutates
    # constraints_applied[].source in place. Verified benign -- the write is
    # additive/idempotent (no extra="forbid" on StrategySection) and matches the
    # existing _build_envelope / _inject_specialist_tiles_into_state precedent.
    state_sections = state.get("strategy_sections") if state is not None else None
    if isinstance(state_sections, list) and state_sections:
        strategy_sections = state_sections
    else:
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

    # Surface builder metadata flat so TurnLifecycleMiddleware._merge_itinerary
    # can populate turn_meta["builder_result"] for chip generation.
    overview_out = result.overview.model_dump() if result.overview is not None else None
    assumptions_out = result.assumptions.model_dump() if result.assumptions is not None else None

    out: Dict[str, Any] = {
        "success": result.success,
        "day_cards": day_cards_out,
        "conflicts": conflicts_out,
        "activities_placed": result.total_activities_placed,
        "total_activities_placed": result.total_activities_placed,
        "activities_dropped": activities_dropped,
        "warnings": result.warnings,
        "overview": overview_out,
        "assumptions": assumptions_out,
    }

    # When the builder fails WITH NO usable schedule (TRIP_TOO_SHORT for a
    # sub-2-day trip, invalid dates, or an internal exception), surface a
    # human-readable "error" so the agent loop can explain the problem instead of
    # returning a silent, reason-less empty plan. The "error" key also signals
    # TurnLifecycleMiddleware.awrap_tool_call to skip _merge_itinerary, leaving
    # any existing day_cards untouched. We do NOT change the 2-day minimum.
    #
    # Gate on EMPTY day_cards: the builder's CONSTRAINT_CONFLICT path also reports
    # success=False but returns a populated partial schedule (itinerary_builder
    # ~801). That partial schedule + conflicts MUST still flow through
    # _merge_itinerary (so builder_result is written and the S3_PARTIAL_CONFLICT
    # view-state is computed), so we must NOT mark it as a tool error.
    if not result.success and not day_cards_out:
        out["error"] = _builder_failure_message(result.error)

    return out
