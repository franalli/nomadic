"""
Logistics Node - Fetches tiles (flights, hotels, activities) from providers.

Placed AFTER Specialist nodes (reads constraints) and BEFORE Architect.
This is the "Fetch & Polish" pattern for demo-ready data.

Provider routing strategy (consistent with tile_service):
1. Curated destinations (Dubai, Rome, Chamonix) → CuratedProvider (4K images, prices)
2. Non-curated + Amadeus enabled → AmadeusHotelProvider (real names, placeholder images)
3. Fallback → MockProviders

@see docs/ux_unified_architecture.md Section XIII - Tile Provider Architecture

Key responsibilities:
1. Fetch hotels/activities from providers (curated → amadeus → mock)
2. Fetch flights from curated data or mock (amadeus flights disabled)
3. Sanitize garbage test carriers (XX -> Emirates)
4. Apply 24h no-fly safety logic for diving trips
5. Store results in state.tiles for frontend display
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List

from app.data.demo_curation import CARRIER_MAP, DEMO_MANIFEST
from app.debug_utils import (
    CompactLogger,
    _debug_log,
    _debug_node_end,
    _debug_node_start,
    log,
)
from app.planner.hashing import stable_hash
from app.planner.services.iata_resolver import resolve_iata_codes
from app.planner.state.schemas import GraphState
from app.planner.state.typed_meta import get_trip_settings
from app.tile_service.curated_provider import CuratedProvider
from app.tile_service.mock_provider import MockActivityProvider, MockHotelProvider
from app.tile_service.models import SearchContext

logger = logging.getLogger(__name__)


# =============================================================================
# Cache Key Helper
# =============================================================================
def _logistics_input_hash(state: GraphState) -> str:
    """
    Hash all inputs that affect tile search results.
    This ensures cache is busted when any logistics-relevant parameter changes:
    - Origin/destination
    - Dates
    - Travelers
    - Budget
    - Hotel settings (stars, amenities)
    - Flight settings (cabin, direct)
    - Activity skill level
    """
    tp = state.trip_plan
    settings = get_trip_settings(state)
    return stable_hash(
        {
            "destination": (tp.destination or "").lower(),
            "origin": (tp.origin or "").lower(),
            "start_date": tp.start_date,
            "end_date": tp.end_date,
            "adults": tp.adults,
            "children": tp.children,
            "budget": tp.budget,
            "hotel_settings": settings.hotel_settings.model_dump(),
            "flight_settings": settings.flight_settings.model_dump(),
            "activity_skill_level": settings.activity_settings.skill_level,
            "activity_categories": sorted(settings.activity_settings.categories),
        }
    )


# =============================================================================
# Main Node
# =============================================================================
async def logistics_node(state: GraphState) -> GraphState:
    """
    Logistics Node:
    1. Fetches raw flights from Amadeus (or backup).
    2. Sanitizes carrier names for a pro look.
    3. Applies 24h safety logic if diving constraints exist.
    """
    plan = state.trip_plan
    node_start_time = time.time()

    # Initialize compact logger with request metrics
    metrics = state.metadata.get("_metrics")
    clog = CompactLogger("logistics", metrics=metrics)

    # DEBUG: Node start
    _debug_node_start(
        "logistics",
        "✈️",
        destination=plan.destination,
        origin=plan.origin,
        dates=f"{plan.start_date} to {plan.end_date}",
    )

    # Compact logging: node start
    clog.node_start("LOGISTICS", dest=plan.destination, origin=plan.origin or "None")

    # ==========================================================================
    # SELECTIVE REGENERATION: Hash-based cache check for all logistics inputs
    # Busts cache when ANY logistics-relevant parameter changes:
    # origin, destination, dates, travelers, budget, hotel/flight/activity settings
    # @see docs/plan_graph_analysis.md - Selective Regeneration Strategy
    # ==========================================================================
    has_cached_tiles = bool(
        state.tiles.get("hotels") or state.tiles.get("activities") or state.tiles.get("flights")
    )

    if has_cached_tiles:
        # Compute hash of all logistics-relevant inputs
        current_hash = _logistics_input_hash(state)
        cached_hash = state.metadata.get("_logistics_hash")

        if cached_hash and current_hash == cached_hash:
            log("LOGISTICS", f"Cache HIT: inputs unchanged for {plan.destination}")
            _debug_log(
                f"Tiles cache hit - hotels={len(state.tiles.get('hotels', []))}, "
                f"activities={len(state.tiles.get('activities', []))}, "
                f"flights={len(state.tiles.get('flights', []))}"
            )
            _debug_node_end(
                "logistics",
                "✈️",
                status="cache_hit",
                hotels=len(state.tiles.get("hotels", [])),
                activities=len(state.tiles.get("activities", [])),
                flights=len(state.tiles.get("flights", [])),
            )
            # Mark as attempted for downstream routing
            state.metadata["logistics_attempted"] = True

            # Compact logging: cache hit
            clog.event("cache_hit", "Tiles (all categories)", dest=plan.destination)
            duration_ms = int((time.time() - node_start_time) * 1000)
            clog.node_end(
                "LOGISTICS",
                duration_ms,
                status="cache_hit",
                hotels=len(state.tiles.get("hotels", [])),
                activities=len(state.tiles.get("activities", [])),
            )
            return state

        # Hash changed - INVALIDATE cached tiles
        if cached_hash:
            log("LOGISTICS", f"Cache BUST: inputs changed for {plan.destination}")
            _debug_log(
                f"Logistics inputs changed - refetching tiles "
                f"(old_hash={cached_hash[:8]}..., new_hash={current_hash[:8]}...)"
            )
            # Clear stale tiles
            state.tiles = {"hotels": [], "activities": [], "flights": []}
            state.metadata["tiles_destination"] = None
            clog.event("cache_invalidate", f"inputs changed for {plan.destination}")

    # Store current destination and input hash for future cache checks
    state.metadata["tiles_destination"] = plan.destination
    state.metadata["_logistics_hash"] = _logistics_input_hash(state)

    # Mark that logistics has been attempted (prevents infinite loop in route_after_architect)
    state.metadata["logistics_attempted"] = True

    # ==========================================================================
    # DIAGNOSTIC LOGGING - Track origin sync (Issue 6 investigation)
    # ==========================================================================
    _logistics_settings = get_trip_settings(state)
    flights_enabled = _logistics_settings.booking_types.flights != "off"
    trip_inputs = state.metadata.get("trip_inputs", {})
    trip_inputs_origin = trip_inputs.get("origin")

    _debug_log(f"[LOGISTICS] trip_plan.origin={plan.origin!r}")
    _debug_log(f"[LOGISTICS] flights_enabled={flights_enabled}")

    # Skip flights if disabled in settings (even if origin exists)
    if not flights_enabled:
        _debug_log("[LOGISTICS] ⏭️ Skipping flights - disabled in settings")
    # ==========================================================================

    # Skip if missing required fields
    if not plan.destination or not plan.start_date:
        log("LOGISTICS", "Skipping - no destination or dates")
        _debug_node_end("logistics", "✈️", status="skipped", reason="missing_fields")
        # Compact logging: skipped
        duration_ms = int((time.time() - node_start_time) * 1000)
        clog.node_end("LOGISTICS", duration_ms, status="skipped", reason="missing_fields")
        return state

    # Resolve airport codes for flights (flights need origin, hotels/activities don't)
    # Reads state first (populated by router), falls back to LLM only if missing
    origin_code, dest_code = await resolve_iata_codes(plan.origin or "", plan.destination, state)
    # Can only search flights if: codes resolved + flights not disabled in settings
    can_search_flights = bool(origin_code and dest_code) and flights_enabled

    # CRITICAL FIX: Always search for hotels/activities even without origin
    # Hotels and activities only need destination + dates
    # @see docs/ux_unified_architecture.md - Enable tile search without origin
    await _search_hotels_and_activities(state, plan)

    # Skip flight search if disabled or missing origin
    if not can_search_flights:
        # Determine the specific reason for skipping
        if not flights_enabled:
            skip_reason = "flights_disabled_in_settings"
            log("LOGISTICS", "Skipping flights - disabled in settings")
        elif not plan.origin:
            skip_reason = "no_origin_for_flights"
            log("LOGISTICS", "Skipping flights (no origin) - hotels/activities searched")
            # Extra diagnostic if trip_inputs has origin but trip_plan doesn't
            if trip_inputs_origin:
                _debug_log(
                    f"[LOGISTICS] 🔍 trip_inputs.origin='{trip_inputs_origin}' but "
                    f"trip_plan.origin is empty - sync bug detected!"
                )
        else:
            skip_reason = "airport_code_resolution_failed"
            log("LOGISTICS", "Skipping flights - could not resolve airport codes")

        hotels_count = len(state.tiles.get("hotels", []))
        activities_count = len(state.tiles.get("activities", []))
        logger.info(
            f"[Logistics] Skipped flights ({skip_reason}). "
            f"Hotels/activities tiles: {hotels_count} + {activities_count}"
        )
        _debug_node_end(
            "logistics",
            "✈️",
            status="partial",
            reason=skip_reason,
            hotels=len(state.tiles.get("hotels", [])),
            activities=len(state.tiles.get("activities", [])),
        )
        # Compact logging: partial (flights skipped)
        clog.event("constraint", "Flights skipped", reason=skip_reason)
        duration_ms = int((time.time() - node_start_time) * 1000)
        clog.node_end(
            "LOGISTICS",
            duration_ms,
            status="partial",
            hotels=hotels_count,
            activities=activities_count,
        )
        return state

    log("LOGISTICS", f"Searching flights: {origin_code} -> {dest_code}")
    _debug_log(
        f"Flight search params: origin={origin_code}, dest={dest_code}, "
        f"date={plan.end_date or plan.start_date}"
    )

    # Flight provider routing (consistent with hotels/activities):
    # 1. Curated destinations → curated flights
    # 2. Non-curated destinations → mock flights
    raw_flights = []
    flight_source = "unknown"
    dest_key = plan.destination.lower().strip()
    curated_manifest = DEMO_MANIFEST.get(dest_key, {})
    curated_flights = curated_manifest.get("curated_flights")

    if curated_flights:
        # Use curated flights for hero destinations (Dubai, Rome, Chamonix)
        log(
            "LOGISTICS",
            f"Using curated flights for {plan.destination}",
            data=f"{len(curated_flights)} options",
        )
        raw_flights = _curated_to_amadeus_format(curated_flights, plan.end_date or plan.start_date)
        flight_source = "curated"
        _debug_log(f"Curated flights: {[f.get('carrier_name') for f in curated_flights]}")
    else:
        # Use mock flights for non-curated destinations
        log("LOGISTICS", f"Using mock flights for {plan.destination}")
        raw_flights = _get_mock_flights(plan.end_date or plan.start_date)
        flight_source = "mock"
        _debug_log(f"Mock provider returned {len(raw_flights)} flights")

    # 2. DETECT CONSTRAINTS
    # Check if diving specialist added a "no fly" or "24h" rule
    has_diving_safety_rule = _has_diving_constraints(state)
    if has_diving_safety_rule:
        log("LOGISTICS", "Diving safety constraints detected", data="applying 24h no-fly rule")
        _debug_log("Will calculate surface interval for each flight")

    # 3. PROCESS & SANITIZE
    processed_options = []
    sanitized_carriers = []

    for offer in raw_flights:
        try:
            itinerary = offer["itineraries"][0]
            segment = itinerary["segments"][0]
            carrier_code = segment["carrierCode"]
            dep_time_str = segment["departure"]["at"]
            duration_iso = segment.get("duration", "PT6H")

            # A. Sanitize Carrier (The "Pro" Polish)
            carrier_info = CARRIER_MAP.get(
                carrier_code, {"name": carrier_code, "logo": carrier_code}
            )
            if carrier_code in CARRIER_MAP and carrier_code != carrier_info["logo"]:
                sanitized_carriers.append(f"{carrier_code}->{carrier_info['logo']}")
            logo_url = f"https://pics.avs.io/200/200/{carrier_info['logo']}.png"

            # B. Apply Safety Math (The "Constraint Engine")
            logic_hook = None
            is_safe = True  # Default to safe if no diving constraints
            if has_diving_safety_rule:
                logic_hook, is_safe = _calculate_diving_safety(dep_time_str)

            # C. Format Duration
            duration_clean = duration_iso.replace("PT", "").lower()

            # Build Tile-compatible dict for state.tiles["flights"]
            price_value = float(offer["price"]["total"])
            option = {
                "id": offer["id"],
                "type": "flight",
                "partner": "curated" if flight_source == "curated" else "amadeus",
                "partner_product_id": offer["id"],
                "title": f"{carrier_info['name']} - Direct",
                "subtitle": f"Departs {dep_time_str.split('T')[1][:5]} • {duration_clean}",
                "image_url": logo_url,
                "price_estimate": price_value,
                "currency": "USD",
                "price_basis": "per_person",
                "is_estimate_only": True,
                "deeplink_url": "#",
                "tags": [carrier_info["name"]],
                "availability_status": "available",
                "meta": {
                    "logic_hook": logic_hook,
                    "is_safe": is_safe,  # CRITICAL: Frontend checks this for amber border
                    "carrier_code": carrier_info["logo"],
                    "carrier_name": carrier_info["name"],
                    "departure_time": dep_time_str,
                    "duration": duration_clean,
                },
                "source": flight_source,
                "source_agent": "logistics_node",
            }
            processed_options.append(option)

        except Exception as e:
            logger.warning(f"[Logistics] Skipping malformed offer: {e}")
            _debug_log(f"Malformed offer skipped: {e}")
            continue

    # Log sanitization summary
    if sanitized_carriers:
        _debug_log(f"Sanitized carriers: {', '.join(sanitized_carriers)}")

    # 4. STORE IN STATE - Write to state.tiles["flights"] for frontend display
    state.tiles["flights"] = processed_options
    # Also keep in metadata for backwards compatibility
    state.metadata["flight_options"] = processed_options

    # Update summary
    booking_summary = state.metadata.get("booking_summary", {})
    booking_summary["flights_found"] = len(processed_options)
    state.metadata["booking_summary"] = booking_summary

    # Count safe vs unsafe flights
    safe_count = sum(1 for opt in processed_options if opt.get("is_safe", True))
    unsafe_count = len(processed_options) - safe_count

    # Final logging
    log(
        "LOGISTICS",
        f"Found {len(processed_options)} flight options",
        data=f"safe={safe_count}, unsafe={unsafe_count}" if has_diving_safety_rule else None,
    )
    logger.info(f"[Logistics] Found {len(processed_options)} flight options")

    # DEBUG: Node end
    _debug_node_end(
        "logistics",
        "✈️",
        flights=len(processed_options),
        safe=safe_count,
        unsafe=unsafe_count,
        source=flight_source,
    )

    # Compact logging: node end with all tiles
    duration_ms = int((time.time() - node_start_time) * 1000)
    clog.node_end(
        "LOGISTICS",
        duration_ms,
        flights=len(processed_options),
        hotels=len(state.tiles.get("hotels", [])),
        activities=len(state.tiles.get("activities", [])),
    )

    return state


# =============================================================================
# Helper Functions
# =============================================================================


def _tile_to_dict(tile) -> Dict[str, Any]:
    """Convert a Tile object to a dict for state storage."""
    return {
        "id": tile.id,
        "type": tile.type,
        "partner": tile.partner,
        "partner_product_id": tile.partner_product_id,
        "title": tile.title,
        "subtitle": tile.subtitle,
        "image_url": tile.image_url,
        "price_estimate": tile.price_estimate,
        "currency": tile.currency,
        "price_basis": tile.price_basis,
        "is_estimate_only": tile.is_estimate_only,
        "deeplink_url": tile.deeplink_url,
        "rating": tile.rating,
        "location_label": tile.location_label,
        "tags": tile.tags,
        "availability_status": tile.availability_status,
        "meta": tile.meta,
        "source": tile.source,
        "source_agent": tile.source_agent or "logistics_node",
    }


async def _search_hotels_and_activities(state: GraphState, plan) -> None:
    """
    Search for hotels and activities with L1+L2 caching.

    Provider routing strategy (consistent with tile_service):
    1. Curated destinations (Dubai, Rome, Chamonix) → CuratedProvider (4K images, prices)
    2. Non-curated + Amadeus enabled → AmadeusHotelProvider (real names, placeholder images)
    3. Fallback → MockProviders

    Caching strategy:
    - Check cache before provider calls
    - Store raw results in cache (filter post-retrieval)
    - 24h TTL for tile data (prices change daily)

    @see docs/ux_unified_architecture.md Section XIII - Tile Provider Architecture
    """
    from app.db import _get_async_session_factory
    from app.services.tile_cache import get_cached_tiles, set_cached_tiles

    _debug_log(f"Searching hotels/activities for {plan.destination}...")

    # Read user settings for provider filtering
    _settings = get_trip_settings(state)
    hotel_settings = _settings.hotel_settings.model_dump()
    activity_settings = _settings.activity_settings.model_dump()
    flight_settings = _settings.flight_settings.model_dump()

    # Determine provider and cache key parameters
    dest_key = plan.destination.lower().strip() if plan.destination else ""
    curated_manifest = DEMO_MANIFEST.get(dest_key, {})
    provider = "curated" if curated_manifest else "amadeus"

    start_date = str(plan.start_date) if plan.start_date else ""
    end_date = str(plan.end_date) if plan.end_date else ""

    # Get database session for caching
    async_session_factory = _get_async_session_factory()

    async with async_session_factory() as db:
        # =====================================================================
        # HOTELS CACHE CHECK
        # =====================================================================
        cached_hotels = await get_cached_tiles(
            db, provider, "hotel", plan.destination, start_date, end_date
        )

        if cached_hotels:
            _debug_log(f"[TILE_CACHE] Hotels HIT: {len(cached_hotels)} hotels from cache")
            log(
                "LOGISTICS",
                f"Hotels cache HIT for {plan.destination}",
                data=f"{len(cached_hotels)} hotels",
            )
            hotel_dicts = cached_hotels
        else:
            _debug_log(f"[TILE_CACHE] Hotels MISS - fetching from {provider}")

            # Build search context with user settings for provider-level filtering
            ctx = SearchContext(
                destination=plan.destination,
                origin=plan.origin,
                start_date=start_date or None,
                end_date=end_date or None,
                adults=plan.adults or 1,
                children=plan.children or 0,
                currency="USD",
                verticals=["hotel", "activity"],
                max_results_per_vertical=5,
                hotel_settings=hotel_settings or None,
                activity_settings=activity_settings or None,
                flight_settings=flight_settings or None,
            )

            hotel_tiles = []

            if curated_manifest:
                log(
                    "LOGISTICS",
                    f"Using CuratedProvider for {plan.destination}",
                    data="curated destination",
                )
                curated_provider = CuratedProvider(dest_key)
                all_tiles = curated_provider.search(ctx)
                hotel_tiles = [t for t in all_tiles if t.type == "hotel"]
            else:
                from app.config import settings

                if settings.use_amadeus_provider:
                    log(
                        "LOGISTICS",
                        f"Using Amadeus for hotels in {plan.destination}",
                        data="real hotel names",
                    )
                    from app.tile_service.amadeus_provider import AmadeusHotelProvider

                    hotel_provider = AmadeusHotelProvider()
                    hotel_tiles = hotel_provider.search(ctx)
                else:
                    log(
                        "LOGISTICS",
                        f"Using MockProviders for {plan.destination}",
                        data="amadeus disabled",
                    )
                    hotel_provider = MockHotelProvider()
                    hotel_tiles = hotel_provider.search(ctx)

            # Convert to dicts and cache
            hotel_dicts = [_tile_to_dict(tile) for tile in hotel_tiles]

            if hotel_dicts:
                await set_cached_tiles(
                    db, provider, "hotel", plan.destination, start_date, end_date, hotel_dicts
                )

        # =====================================================================
        # ACTIVITIES CACHE CHECK
        # =====================================================================
        cached_activities = await get_cached_tiles(
            db, provider, "activity", plan.destination, start_date, end_date
        )

        if cached_activities:
            _debug_log(
                f"[TILE_CACHE] Activities HIT: {len(cached_activities)} activities from cache"
            )
            log(
                "LOGISTICS",
                f"Activities cache HIT for {plan.destination}",
                data=f"{len(cached_activities)} activities",
            )
            activity_dicts = cached_activities
        else:
            _debug_log(f"[TILE_CACHE] Activities MISS - fetching from {provider}")

            # Build search context if not already built
            if "ctx" not in locals():
                ctx = SearchContext(
                    destination=plan.destination,
                    origin=plan.origin,
                    start_date=start_date or None,
                    end_date=end_date or None,
                    adults=plan.adults or 1,
                    children=plan.children or 0,
                    currency="USD",
                    verticals=["hotel", "activity"],
                    max_results_per_vertical=5,
                    hotel_settings=hotel_settings or None,
                    activity_settings=activity_settings or None,
                    flight_settings=flight_settings or None,
                )

            activity_tiles = []

            if curated_manifest:
                # Curated activities from same provider call
                curated_provider = CuratedProvider(dest_key)
                all_tiles = curated_provider.search(ctx)
                activity_tiles = [t for t in all_tiles if t.type == "activity"]
            else:
                # Activities always use Mock (no Amadeus activities API)
                activity_provider = MockActivityProvider()
                activity_tiles = activity_provider.search(ctx)

            # Convert to dicts and cache
            activity_dicts = [_tile_to_dict(tile) for tile in activity_tiles]

            if activity_dicts:
                await set_cached_tiles(
                    db, provider, "activity", plan.destination, start_date, end_date, activity_dicts
                )

    # Post-fetch hotel star filter (curated provider filters at search time,
    # but mock/Amadeus/cached tiles need post-fetch filtering)
    min_stars = 0
    if isinstance(hotel_settings, dict):
        min_stars = hotel_settings.get("min_stars", 0) or 0
    if min_stars > 0:
        before = len(hotel_dicts)
        hotel_dicts = [
            h
            for h in hotel_dicts
            if (h.get("meta") or {}).get("stars", h.get("rating") or 0) >= min_stars
        ]
        if before != len(hotel_dicts):
            log(
                "LOGISTICS",
                f"Hotel star filter: {before} → {len(hotel_dicts)} ({min_stars}+ stars)",
            )

    # Store in state
    state.tiles["hotels"] = hotel_dicts
    log("LOGISTICS", f"Found {len(hotel_dicts)} hotels for {plan.destination}")
    _debug_log(f"Hotels found: {len(hotel_dicts)}")

    state.tiles["activities"] = activity_dicts

    # Two-tier activity handling:
    # Tier 1 (specialist): diving, hiking, skiing, cycling, surfing → full specialist run
    # Tier 2 (experience): cooking, yoga, sailing, etc. → LLM-generated experience tiles
    #
    # When a niche specialist is active:
    # - Pure Tier 1 selections → suppress all generic tiles (specialist provides curated content)
    # - Mixed Tier 1 + Tier 2 → generate experience tiles for Tier 2 categories
    # When no niche specialist:
    # - Pure Tier 2 selections → generate experience tiles (most important case)
    from app.planner.nodes.intent_router import TIER1_SPECIALISTS

    NICHE_SPECIALISTS = TIER1_SPECIALISTS
    TIER1_CATEGORIES = TIER1_SPECIALISTS
    executed = state.metadata.get("executed_strategy_topics", [])
    has_niche_specialist = any(t in NICHE_SPECIALISTS for t in executed)
    if has_niche_specialist:
        selected_cats = set(get_trip_settings(state).activity_settings.categories)
        tier2_cats = selected_cats - TIER1_CATEGORIES

        if not tier2_cats:
            # Pure Tier 1 — specialist provides activities, suppress all generic tiles
            active_niche = [t for t in executed if t in NICHE_SPECIALISTS]
            log(
                "LOGISTICS",
                "Suppressing logistics activities - pure Tier 1",
                data=f"specialists={active_niche}",
            )
            state.tiles["activities"] = []
            activity_dicts = []
        else:
            # Mixed — generate Tier 2 experience tiles via LLM
            from app.services.experience_generator import generate_experiences

            month = str(plan.start_date)[:7] if plan.start_date else ""
            active_niche = [t for t in executed if t in NICHE_SPECIALISTS]
            tiles_per_cat = _compute_tiles_per_category(state, tier2_cats)
            experience_tiles = await generate_experiences(
                destination=plan.destination,
                categories=list(tier2_cats),
                month=month,
                budget=plan.budget,
                tier1_specialists=active_niche,
                tiles_per_category=tiles_per_cat,
            )

            if experience_tiles:
                log(
                    "LOGISTICS",
                    f"Generated {len(experience_tiles)} Tier 2 experience tiles",
                    data=f"specialists={active_niche}, tier2={tier2_cats}",
                )
                state.tiles["activities"] = experience_tiles
                activity_dicts = experience_tiles
            else:
                # Fallback: keyword match existing tiles (original behavior)
                matching = [t for t in activity_dicts if _tile_matches_categories(t, tier2_cats)]
                if not matching and activity_dicts:
                    matching = activity_dicts
                    log(
                        "LOGISTICS",
                        f"Experience gen empty, falling back to all {len(activity_dicts)}",
                        data=f"specialists={active_niche}, tier2={tier2_cats}",
                    )
                else:
                    log(
                        "LOGISTICS",
                        (
                            f"Experience gen empty, keyword matched "
                            f"{len(matching)}/{len(activity_dicts)}"
                        ),
                        data=f"specialists={active_niche}, tier2={tier2_cats}",
                    )
                state.tiles["activities"] = matching
                activity_dicts = matching
    else:
        # No niche specialist — check if user selected Tier 2 categories
        selected_cats = set(get_trip_settings(state).activity_settings.categories)
        tier2_only = selected_cats - TIER1_CATEGORIES
        if tier2_only:
            from app.services.experience_generator import generate_experiences

            month = str(plan.start_date)[:7] if plan.start_date else ""
            tiles_per_cat = _compute_tiles_per_category(state, tier2_only)
            experience_tiles = await generate_experiences(
                destination=plan.destination,
                categories=list(tier2_only),
                month=month,
                budget=plan.budget,
                tiles_per_category=tiles_per_cat,
            )
            if experience_tiles:
                log(
                    "LOGISTICS",
                    f"Pure Tier 2: generated {len(experience_tiles)} experience tiles",
                    data=f"categories={tier2_only}",
                )
                state.tiles["activities"] = experience_tiles
                activity_dicts = experience_tiles

    log("LOGISTICS", f"Found {len(activity_dicts)} activities for {plan.destination}")
    _debug_log(f"Activities found: {len(activity_dicts)}")

    # Update booking summary
    booking_summary = state.metadata.get("booking_summary", {})
    booking_summary["hotels_found"] = len(hotel_dicts)
    booking_summary["activities_found"] = len(activity_dicts)
    state.metadata["booking_summary"] = booking_summary


def _compute_tiles_per_category(state: GraphState, tier2_cats: set[str]) -> int:
    """Scale experience tile count based on placeable days.

    free_days = trip_days - specialist_activity_days - 2 (arrival/departure)
    total_placeable = free_days + specialist_days (co-scheduling capacity)
    tiles_per_category = clamp(total_placeable // len(tier2_cats), 2, 4)
    """
    plan = state.trip_plan
    if not plan.start_date or not plan.end_date or not tier2_cats:
        return 2

    try:
        start = datetime.strptime(plan.start_date, "%Y-%m-%d")
        end = datetime.strptime(plan.end_date, "%Y-%m-%d")
        trip_days = (end - start).days + 1
    except ValueError:
        return 2

    # Count items from niche specialist sections as proxy for specialist days
    specialist_days = 0
    for section in state.metadata.get("strategy_sections", []):
        if section.get("specialist_type", "") in ("local_expert", "general"):
            continue
        specialist_days += len(section.get("content_added", []))

    free_days = max(0, trip_days - specialist_days - 2)
    # Specialist days can hold ~1 co-scheduled experience tile each
    total_placeable = free_days + specialist_days
    tiles_per_cat = min(max(2, total_placeable // len(tier2_cats)), 4)
    log(
        "LOGISTICS",
        f"Tile scaling: trip={trip_days}d, specialist={specialist_days}d, "
        f"free={free_days}d, placeable={total_placeable}d, "
        f"cats={len(tier2_cats)}, tiles/cat={tiles_per_cat}",
    )
    return tiles_per_cat


def _tile_matches_categories(tile: dict, categories: set) -> bool:
    """Match tile against selected Tier 2 categories via tags (primary) or text (fallback)."""
    tile_tags = {t.lower() for t in tile.get("tags", [])}
    # Primary: tag intersection
    if tile_tags & {cat.lower() for cat in categories}:
        return True
    # Fallback: keyword in title/subtitle (handles mock tiles without proper tags)
    text = f"{tile.get('title', '')} {tile.get('subtitle', '')}".lower()
    return any(cat.lower() in text for cat in categories)


def _has_diving_constraints(state: GraphState) -> bool:
    """Check if diving specialist added safety constraints."""
    # Check active specialist
    if state.active_specialist == "diving":
        return True

    # Check strategy sections for diving-related constraints
    for section in state.metadata.get("strategy_sections", []):
        if section.get("specialist_type") == "diving":
            return True
        # Also check constraints list if present
        constraints = section.get("constraints_applied", [])
        for c in constraints:
            rule = c.get("rule", "").lower()
            if "24h" in rule or "no_fly" in rule or "surface_interval" in rule:
                return True

    # Check trip_plan constraints
    for c in state.trip_plan.constraints:
        if "24h" in c.rule.lower() or "no_fly" in c.rule.lower():
            return True

    return False


def _calculate_diving_safety(flight_time_str: str) -> tuple[str, bool]:
    """
    Returns (status_string, is_safe_boolean) based on 24h buffer.
    Assumption for MVP: Last dive ends at 14:00 on the day BEFORE flight.
    """
    flight_dt = datetime.fromisoformat(flight_time_str.replace("Z", "+00:00"))

    # Mock "Last Dive" time: Yesterday @ 14:00
    last_dive_finish = flight_dt - timedelta(days=1)
    last_dive_finish = last_dive_finish.replace(hour=14, minute=0, second=0)

    # Calculate buffer
    buffer_hours = (flight_dt - last_dive_finish).total_seconds() / 3600

    # CRITICAL: Create boolean FIRST for frontend safety shield
    is_safe_bool = buffer_hours >= 24

    if is_safe_bool:
        return f"✅ Safe: {int(buffer_hours)}h buffer", True
    else:
        return f"⚠️ Risky: Only {int(buffer_hours)}h buffer", False


def _curated_to_amadeus_format(curated_flights: List[Dict], date_str: str) -> List[Dict]:
    """
    Convert curated flight data to Amadeus-like dict format.

    Curated flights have: carrier_code, carrier_name, departure_time, duration, price
    We need to convert to Amadeus format for unified processing.
    """
    try:
        base_date = date_str[:10] if date_str else "2026-03-20"
    except Exception:
        base_date = "2026-03-20"

    result = []
    for flight in curated_flights:
        result.append(
            {
                "id": flight.get("id", f"curated_{flight.get('carrier_code')}"),
                "price": {"total": str(flight.get("price", 0))},
                "itineraries": [
                    {
                        "segments": [
                            {
                                "carrierCode": flight.get("carrier_code", "EK"),
                                "departure": {
                                    "at": f"{base_date}T{flight.get('departure_time', '12:00')}:00"
                                },
                                "duration": flight.get("duration", "PT6H"),
                            }
                        ]
                    }
                ],
            }
        )
    return result


def _get_mock_flights(date_str: str) -> List[Dict]:
    """
    Mock flight data for non-curated destinations.
    Includes one UNSAFE option (08:00) and two SAFE options (18:00, 21:30)
    to demonstrate the 24h no-fly diving safety logic.
    """
    # Use provided date or default
    try:
        base_date = date_str[:10] if date_str else "2026-03-20"
    except Exception:
        base_date = "2026-03-20"

    return [
        {
            "id": "demo_unsafe",
            "price": {"total": "420.00"},
            "itineraries": [
                {
                    "segments": [
                        {
                            "carrierCode": "XX",  # Maps to Emirates
                            "departure": {"at": f"{base_date}T08:00:00"},
                            "duration": "PT6H30M",
                        }
                    ]
                }
            ],
        },
        {
            "id": "demo_safe_1",
            "price": {"total": "550.00"},
            "itineraries": [
                {
                    "segments": [
                        {
                            "carrierCode": "XX",  # Maps to Emirates
                            "departure": {"at": f"{base_date}T18:00:00"},
                            "duration": "PT6H30M",
                        }
                    ]
                }
            ],
        },
        {
            "id": "demo_safe_2",
            "price": {"total": "480.00"},
            "itineraries": [
                {
                    "segments": [
                        {
                            "carrierCode": "BA",  # British Airways
                            "departure": {"at": f"{base_date}T21:30:00"},
                            "duration": "PT7H15M",
                        }
                    ]
                }
            ],
        },
    ]
