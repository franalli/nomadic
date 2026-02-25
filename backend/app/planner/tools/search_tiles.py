"""
search_tiles tool -- wraps logistics_node tile fetching pipeline.

Fetches flights, hotels, and activities from the tile provider cascade
(Google Places -> Mock). Applies no-fly buffer for diving
activities. Returns tile arrays with prices and images.

State mutation happens in TurnLifecycleMiddleware, not here.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from typing_extensions import Annotated

from app.planner.nodes.logistics_node import (
    _calculate_diving_safety,
    _curated_to_flight_tiles,
    _get_mock_flights,
)
from app.planner.specialist_registry import SPECIALIST_REGISTRY

logger = logging.getLogger(__name__)

# Registry-derived set of categories that trigger the no-fly buffer.
# Replaces a previously hardcoded {"diving", "scuba", "freediving", "snorkeling"}.

_NOFLY_CATEGORIES: frozenset[str] = frozenset(
    alias
    for name, cfg in SPECIALIST_REGISTRY.items()
    if cfg.has_nofly_buffer
    for alias in cfg.category_mappings
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_state_proxy(
    destination: str,
    start_date: str,
    end_date: str,
    origin: str = "",
    adults: int = 2,
    children: int = 0,
    budget: float = 0,
    destination_iata: str = "",
    origin_iata: str = "",
    hotel_stars: int = 0,
    hotel_style: str = "",
    flight_cabin: str = "",
    flight_direct_only: bool = False,
    activity_categories: str = "",
) -> Any:
    """Build a minimal GraphState for logistics helpers that read state fields.

    The iata_resolver reads state.trip_plan.{origin_iata, destination_iata}
    and writes back resolved codes.
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

    # Build trip_inputs metadata for settings resolution
    trip_inputs: Dict[str, Any] = {}
    if hotel_stars or hotel_style:
        trip_inputs["hotel_settings"] = {}
        if hotel_stars:
            trip_inputs["hotel_settings"]["min_stars"] = hotel_stars
        if hotel_style:
            trip_inputs["hotel_settings"]["style"] = hotel_style
    if flight_cabin or flight_direct_only:
        trip_inputs["flight_settings"] = {}
        if flight_cabin:
            trip_inputs["flight_settings"]["cabin_class"] = flight_cabin
        if flight_direct_only:
            trip_inputs["flight_settings"]["direct_only"] = True
    if activity_categories:
        cats = [c.strip() for c in activity_categories.split(",") if c.strip()]
        trip_inputs["activity_settings"] = {"categories": cats}

    metadata: Dict[str, Any] = {}
    if trip_inputs:
        metadata["trip_inputs"] = trip_inputs

    state = GraphState(trip_plan=plan, metadata=metadata)
    return state


def _parse_categories(activity_categories: str) -> List[str]:
    """Parse comma-separated category string into list."""
    if not activity_categories:
        return []
    return [c.strip().lower() for c in activity_categories.split(",") if c.strip()]


def _has_diving_categories(categories: List[str]) -> bool:
    """Check if any category involves diving (triggers no-fly buffer).

    Uses registry-derived set instead of hardcoded keywords.
    """
    return bool(set(categories) & _NOFLY_CATEGORIES)


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


@tool
async def search_tiles(
    destination: str = "",
    start_date: str = "",
    end_date: str = "",
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
    session_id: str = "",
    # InjectedState -- auto-populated when running inside create_agent;
    # invisible to the LLM's tool-calling schema.  Provides trip_plan
    # and trip_settings from agent state so the LLM does not need to
    # echo back fields it already holds.
    state: Annotated[Optional[dict], InjectedState] = None,
) -> dict:
    """Search for flights, hotels, and activities. Requires destination and
    dates. Origin required for flights. Returns tile arrays with prices
    and images."""
    from app.config import settings
    from app.data.demo_curation import CARRIER_MAP, DEMO_MANIFEST
    from app.db import _get_async_session_factory
    from app.planner.services.iata_resolver import resolve_iata_codes
    from app.services.tile_cache import get_cached_tiles, set_cached_tiles
    from app.tile_service.mock_provider import (
        MockActivityProvider,
        MockHotelProvider,
    )
    from app.tile_service.models import SearchContext

    t0 = time.time()
    categories = _parse_categories(activity_categories)

    # ALWAYS prefer state categories — LLM can hallucinate or echo stale values
    if state is not None:
        _act_settings = state.get("trip_settings", {}).get("activity_settings", {})
        if isinstance(_act_settings, dict):
            _state_cats = _act_settings.get("categories", [])
            if _state_cats:
                _override = [str(c).lower().strip() for c in _state_cats if c]
                if _override != categories:
                    logger.info(
                        "[GUARD:SEARCH_CATS] Overriding LLM categories %s -> state %s",
                        categories,
                        _override,
                    )
                categories = _override

    # Also fill in other state fields if LLM omitted them
    if state is not None:
        _tp = state.get("trip_plan", {})
        destination = destination or _tp.get("destination", "")
        start_date = start_date or _tp.get("start_date", "")
        end_date = end_date or _tp.get("end_date", "")
        origin = origin or _tp.get("origin", "")

    apply_nofly = _has_diving_categories(categories)

    # Validate required fields
    if not destination or not start_date:
        return {
            "flights": [],
            "hotels": [],
            "activities": [],
            "flight_search_status": "skipped",
            "summary": "Missing destination or start_date",
        }

    # ---------------------------------------------------------------
    # IATA resolution (if origin provided but codes missing)
    # ---------------------------------------------------------------
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
        activity_categories=activity_categories,
    )

    resolved_origin_iata = origin_iata
    resolved_dest_iata = destination_iata

    if origin and (not resolved_origin_iata or not resolved_dest_iata):
        try:
            resolved_origin_iata, resolved_dest_iata = await resolve_iata_codes(
                origin, destination, state_proxy
            )
        except Exception as exc:
            logger.warning("[search_tiles] IATA resolution failed: %s", exc)

    # ---------------------------------------------------------------
    # Determine provider
    # ---------------------------------------------------------------
    if settings.use_google_places_provider:
        provider = "google_places"
    else:
        provider = "mock"

    dest_key = destination.lower().strip()

    # ---------------------------------------------------------------
    # Fetch hotels and activities in parallel
    # ---------------------------------------------------------------
    hotel_dicts: List[Dict[str, Any]] = []
    activity_dicts: List[Dict[str, Any]] = []

    # Build search context
    hotel_settings_dict: Dict[str, Any] = {}
    if hotel_stars:
        hotel_settings_dict["min_stars"] = hotel_stars
    if hotel_style:
        hotel_settings_dict["style"] = hotel_style

    activity_settings_dict: Dict[str, Any] = {}
    if categories:
        activity_settings_dict["categories"] = categories

    flight_settings_dict: Dict[str, Any] = {}
    if flight_cabin:
        flight_settings_dict["cabin_class"] = flight_cabin
    if flight_direct_only:
        flight_settings_dict["direct_only"] = True

    ctx = SearchContext(
        destination=destination,
        origin=origin or None,
        start_date=start_date or None,
        end_date=end_date or None,
        adults=adults or 2,
        children=children or 0,
        currency="USD",
        verticals=["hotel", "activity"],
        max_results_per_vertical=5,
        origin_iata=resolved_origin_iata or None,
        destination_iata=resolved_dest_iata or None,
        hotel_settings=hotel_settings_dict or None,
        activity_settings=activity_settings_dict or None,
        flight_settings=flight_settings_dict or None,
    )

    async def _fetch_hotels_standalone() -> List[Dict[str, Any]]:
        """Fetch hotels from provider with L2 cache."""
        # Build hotel cache variant from min_stars
        hotel_cache_variant = f"stars{hotel_stars}" if hotel_stars > 0 else ""

        try:
            async_session_factory = _get_async_session_factory()
            async with async_session_factory() as db:
                cached = await get_cached_tiles(
                    db,
                    provider,
                    "hotel",
                    destination,
                    start_date,
                    end_date,
                    hotel_cache_variant,
                )
                if cached:
                    logger.debug("[search_tiles] Hotels cache HIT: %d", len(cached))
                    return cached
        except Exception as exc:
            logger.warning("[search_tiles] Hotel cache lookup failed: %s", exc)

        # Cache miss -- fetch from provider
        tiles = []
        try:
            if settings.use_google_places_provider:
                from app.tile_service.google_places_provider import (
                    GooglePlacesHotelProvider,
                )

                gp = GooglePlacesHotelProvider()
                tiles = await gp.search_async(ctx)
                if not tiles:
                    tiles = MockHotelProvider().search(ctx)
            else:
                tiles = MockHotelProvider().search(ctx)
        except Exception as exc:
            logger.warning("[search_tiles] Hotel provider failed: %s", exc)
            tiles = MockHotelProvider().search(ctx)

        dicts = []
        for tile in tiles:
            if hasattr(tile, "model_dump"):
                dicts.append(tile.model_dump())
            elif isinstance(tile, dict):
                dicts.append(tile)

        # Cache the results
        if dicts:
            try:
                async_session_factory = _get_async_session_factory()
                async with async_session_factory() as db:
                    await set_cached_tiles(
                        db,
                        provider,
                        "hotel",
                        destination,
                        start_date,
                        end_date,
                        dicts,
                        hotel_cache_variant,
                    )
            except Exception as exc:
                logger.warning("[search_tiles] Hotel cache write failed: %s", exc)

        return dicts

    async def _fetch_activities_standalone() -> List[Dict[str, Any]]:
        """Fetch activities from provider with L2 cache."""
        # Build cache variant from categories so different category sets
        # produce distinct cache entries (mirrors hotel_cache_variant pattern).
        activity_cache_variant = "cats_" + "_".join(sorted(categories)) if categories else ""

        try:
            async_session_factory = _get_async_session_factory()
            async with async_session_factory() as db:
                cached = await get_cached_tiles(
                    db,
                    provider,
                    "activity",
                    destination,
                    start_date,
                    end_date,
                    activity_cache_variant,
                )
                if cached:
                    logger.debug("[search_tiles] Activities cache HIT: %d", len(cached))
                    return cached
        except Exception as exc:
            logger.warning("[search_tiles] Activity cache lookup failed: %s", exc)

        tiles = []
        try:
            if settings.use_google_places_provider:
                from app.tile_service.google_places_provider import (
                    GooglePlacesActivityProvider,
                )

                gp = GooglePlacesActivityProvider()
                tiles = await gp.search_async(ctx)
                if not tiles:
                    if categories and provider != "mock":
                        logger.warning(
                            "[search_tiles] Google Places returned 0 activities for "
                            "categories=%s in %s — no mock fallback",
                            categories,
                            destination,
                        )
                    else:
                        tiles = MockActivityProvider().search(ctx)
            else:
                tiles = MockActivityProvider().search(ctx)
        except Exception as exc:
            logger.warning("[search_tiles] Activity provider failed: %s", exc)
            tiles = MockActivityProvider().search(ctx)

        dicts = []
        for tile in tiles:
            if hasattr(tile, "model_dump"):
                dicts.append(tile.model_dump())
            elif isinstance(tile, dict):
                dicts.append(tile)

        # Cache the results
        if dicts:
            try:
                async_session_factory = _get_async_session_factory()
                async with async_session_factory() as db:
                    await set_cached_tiles(
                        db,
                        provider,
                        "activity",
                        destination,
                        start_date,
                        end_date,
                        dicts,
                        activity_cache_variant,
                    )
            except Exception as exc:
                logger.warning("[search_tiles] Activity cache write failed: %s", exc)

        return dicts

    try:
        hotel_dicts, activity_dicts = await asyncio.gather(
            _fetch_hotels_standalone(),
            _fetch_activities_standalone(),
        )
    except Exception as exc:
        logger.error("[search_tiles] Parallel fetch failed: %s", exc)
        hotel_dicts = []
        activity_dicts = []

    # Regression guard: log what was requested vs returned
    if categories:
        _returned_cats: set[str] = set()
        for _t in activity_dicts:
            if isinstance(_t, dict):
                _cat = (_t.get("meta") or {}).get("category", "")
                if _cat:
                    _returned_cats.add(_cat.lower())
        logger.info(
            "[GUARD:TILE_SEARCH] requested=%s returned_categories=%s "
            "returned_count=%d hotel_count=%d",
            categories,
            sorted(_returned_cats),
            len(activity_dicts),
            len(hotel_dicts),
        )

    # Post-fetch hotel star filter
    if hotel_stars > 0:
        hotel_dicts = [
            h
            for h in hotel_dicts
            if (h.get("meta") or {}).get("stars", h.get("rating") or 0) >= hotel_stars
        ]

    # ---------------------------------------------------------------
    # Flight search (only if origin and IATA codes available)
    # ---------------------------------------------------------------
    flight_dicts: List[Dict[str, Any]] = []
    flight_search_status = "skipped"

    can_search_flights = bool(origin and resolved_origin_iata and resolved_dest_iata)

    if can_search_flights:
        try:
            curated_manifest = DEMO_MANIFEST.get(dest_key, {})
            curated_flights = curated_manifest.get("curated_flights")

            raw_flights: List[Dict[str, Any]] = []
            flight_source = "mock"

            if curated_flights:
                raw_flights = _curated_to_flight_tiles(curated_flights, end_date or start_date)
                flight_source = "curated"
            else:
                raw_flights = _get_mock_flights(end_date or start_date)
                flight_source = "mock"

            for offer in raw_flights:
                try:
                    itinerary = offer["itineraries"][0]
                    segments = itinerary.get("segments", [])
                    if not segments:
                        continue
                    segment = segments[0]
                    carrier_code = segment["carrierCode"]
                    dep_time_str = segment["departure"]["at"]
                    duration_iso = segment.get("duration", "PT6H")
                    stops = max(0, len(segments) - 1)
                    is_direct = stops == 0

                    if flight_direct_only and not is_direct:
                        continue

                    carrier_info = CARRIER_MAP.get(
                        carrier_code,
                        {"name": carrier_code, "logo": carrier_code},
                    )
                    logo_url = f"https://pics.avs.io/200/200/{carrier_info['logo']}.png"

                    # Apply diving no-fly safety check
                    logic_hook = None
                    is_safe = True
                    if apply_nofly:
                        logic_hook, is_safe = _calculate_diving_safety(dep_time_str)

                    duration_clean = duration_iso.replace("PT", "").lower()
                    stops_label = (
                        "Direct" if is_direct else f"{stops} stop{'s' if stops > 1 else ''}"
                    )
                    price_value = float(offer["price"]["total"])

                    flight_dicts.append(
                        {
                            "id": offer["id"],
                            "type": "flight",
                            "partner": ("curated" if flight_source == "curated" else "mock"),
                            "partner_product_id": offer["id"],
                            "title": f"{carrier_info['name']} - {stops_label}",
                            "subtitle": (
                                f"Departs {dep_time_str.split('T')[1][:5]} | {duration_clean}"
                            ),
                            "image_url": logo_url,
                            "price_estimate": price_value,
                            "currency": "USD",
                            "price_basis": "per_person",
                            "is_estimate_only": True,
                            "deeplink_url": "#",
                            "tags": [carrier_info["name"], stops_label.lower()],
                            "availability_status": "available",
                            "meta": {
                                "logic_hook": logic_hook,
                                "is_safe": is_safe,
                                "carrier_code": carrier_info["logo"],
                                "carrier_name": carrier_info["name"],
                                "departure_time": dep_time_str,
                                "duration": duration_clean,
                                "stops": stops,
                                "is_direct": is_direct,
                            },
                            "source": flight_source,
                            "source_agent": "search_tiles",
                        }
                    )
                except Exception as exc:
                    logger.warning("[search_tiles] Skipping malformed flight offer: %s", exc)
                    continue

            flight_search_status = "searched"
        except Exception as exc:
            logger.error("[search_tiles] Flight search failed: %s", exc)
            flight_search_status = "error"
    else:
        if not origin:
            flight_search_status = "skipped_no_origin"
        else:
            flight_search_status = "skipped_no_codes"

    # ---------------------------------------------------------------
    # Build summary
    # ---------------------------------------------------------------
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
        "flight_search_status": flight_search_status,
        "summary": summary,
    }
