"""
search_tiles tool -- wraps the logistics_node tile-fetch pipeline.

Delegates directly to ``logistics_node(state)`` (the same path the live
coordinator uses) rather than reimplementing standalone provider fetchers.
Builds a GraphState proxy with the trip_settings/booking_types metadata that
logistics_node reads to decide fetch scope, calls the node, and returns the
resulting flights/hotels/activities tile arrays.

Diving no-fly safety annotation is applied internally by logistics_node during
flight assembly (see ``_calculate_diving_safety``), so this tool no longer
applies it standalone.

State mutation happens in TurnLifecycleMiddleware, not here.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_categories(activity_categories: str) -> List[str]:
    """Parse comma-separated category string into a normalized list."""
    if not activity_categories:
        return []
    return [c.strip().lower() for c in activity_categories.split(",") if c.strip()]


def _build_state_proxy(
    *,
    destination: str,
    start_date: str,
    end_date: str,
    origin: str,
    adults: int,
    children: int,
    budget: float,
    destination_iata: str,
    origin_iata: str,
    hotel_stars: int,
    hotel_style: str,
    flight_cabin: str,
    flight_direct_only: bool,
    categories: List[str],
    requested_types: List[str],
) -> Any:
    """Build a GraphState whose metadata gates logistics_node fetch scope.

    logistics_node resolves its fetch behaviour via ``get_trip_settings(state)``
    which reads ``state.metadata["trip_settings"]``.  In particular it checks
    ``booking_types.{flights,hotels,activities}`` ("off" disables a vertical)
    plus the hotel/flight/activity settings.  We mirror the coordinator's
    ``_search_tiles`` metadata setup so the node fetches exactly the requested
    verticals.
    """
    from app.planner.state.graph_state import GraphState, TripPlan

    plan = TripPlan(
        destination=destination or None,
        origin=origin or None,
        start_date=start_date or None,
        end_date=end_date or None,
        adults=adults if adults else 2,
        children=children if children else 0,
        budget=budget if budget else None,
        origin_iata=origin_iata or None,
        destination_iata=destination_iata or None,
    )

    # Gate verticals: a vertical is fetched only when it is requested AND not
    # explicitly disabled.  logistics_node treats booking_types.flights == "off"
    # as "do not search flights".
    requested = set(requested_types)
    booking_types: Dict[str, str] = {}
    booking_types["flights"] = "suggested" if "flights" in requested else "off"
    booking_types["hotels"] = "suggested" if "hotels" in requested else "off"
    booking_types["activities"] = "suggested" if "activities" in requested else "off"

    hotel_settings: Dict[str, Any] = {}
    if hotel_stars:
        hotel_settings["min_stars"] = hotel_stars
    if hotel_style:
        hotel_settings["style"] = hotel_style

    flight_settings: Dict[str, Any] = {}
    if flight_cabin:
        flight_settings["cabin_class"] = flight_cabin
    if flight_direct_only:
        flight_settings["direct_only"] = True

    activity_settings: Dict[str, Any] = {}
    if categories:
        activity_settings["categories"] = categories

    trip_settings: Dict[str, Any] = {
        "booking_types": booking_types,
        "hotel_settings": hotel_settings,
        "flight_settings": flight_settings,
        "activity_settings": activity_settings,
    }

    metadata: Dict[str, Any] = {
        "trip_settings": trip_settings,
        # Legacy alias still consulted by some downstream helpers.
        "trip_inputs": dict(trip_settings),
        "requested_tile_types": sorted(requested),
    }

    return GraphState(trip_plan=plan, tiles={}, metadata=metadata)


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


@tool
async def search_tiles(
    destination: str,
    start_date: str,
    end_date: str,
    origin: str = "",
    adults: int = 2,
    children: int = 0,
    budget: float = 0,
    hotel_stars: int = 0,
    hotel_style: str = "",
    flight_cabin: str = "",
    flight_direct_only: bool = False,
    activity_categories: str = "",
    destination_iata: str = "",
    origin_iata: str = "",
) -> dict:
    """Search for flights, hotels, and activities. Requires destination and
    dates. Origin required for flights. Returns tile arrays with prices
    and images."""
    from app.planner.nodes.logistics_node import logistics_node

    t0 = time.time()
    categories = _parse_categories(activity_categories)

    # Validate required fields
    if not destination or not start_date:
        return {
            "flights": [],
            "hotels": [],
            "activities": [],
            "flight_search_status": "skipped",
            "summary": "Missing destination or start_date",
        }

    # Flights are only meaningful when an origin is provided.
    requested_types = ["hotels", "activities"]
    if origin:
        requested_types.insert(0, "flights")

    state_proxy = _build_state_proxy(
        destination=destination,
        start_date=start_date,
        end_date=end_date,
        origin=origin,
        adults=adults,
        children=children,
        budget=budget,
        destination_iata=destination_iata,
        origin_iata=origin_iata,
        hotel_stars=hotel_stars,
        hotel_style=hotel_style,
        flight_cabin=flight_cabin,
        flight_direct_only=flight_direct_only,
        categories=categories,
        requested_types=requested_types,
    )

    # Delegate to the maintained logistics_node (handles IATA resolution,
    # provider cascade, hotel filtering, diving no-fly safety, caching).
    try:
        state_proxy = await logistics_node(state_proxy)
    except Exception as exc:
        logger.error("[search_tiles] logistics_node failed: %s", exc)
        return {
            "flights": [],
            "hotels": [],
            "activities": [],
            "flight_search_status": "error",
            "summary": f"Tile search failed: {type(exc).__name__}",
        }

    tiles = state_proxy.tiles if isinstance(state_proxy.tiles, dict) else {}
    flight_dicts: List[Dict[str, Any]] = tiles.get("flights", []) or []
    hotel_dicts: List[Dict[str, Any]] = tiles.get("hotels", []) or []
    activity_dicts: List[Dict[str, Any]] = tiles.get("activities", []) or []

    flight_status = state_proxy.metadata.get("flight_search_status")
    if not isinstance(flight_status, str) or not flight_status:
        flight_status = "searched" if origin else "skipped_no_origin"

    elapsed_ms = int((time.time() - t0) * 1000)
    summary = (
        f"Found {len(flight_dicts)} flights, {len(hotel_dicts)} hotels, "
        f"{len(activity_dicts)} activities in {elapsed_ms}ms"
    )

    logger.debug(
        "[search_tiles] dest=%s origin=%s %s",
        destination,
        origin or "none",
        summary,
    )

    return {
        "flights": flight_dicts,
        "hotels": hotel_dicts,
        "activities": activity_dicts,
        "flight_search_status": flight_status,
        "summary": summary,
    }
