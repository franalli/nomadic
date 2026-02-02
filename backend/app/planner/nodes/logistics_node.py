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
from app.planner.state.schemas import GraphState
from app.tile_service.curated_provider import CuratedProvider
from app.tile_service.mock_provider import MockActivityProvider, MockHotelProvider
from app.tile_service.models import SearchContext
from app.tools.amadeus_client import city_to_airport_code

logger = logging.getLogger(__name__)


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
    # SELECTIVE REGENERATION: Check if cached tiles can be reused
    # Logistics tiles are destination + travelers + budget dependent
    # @see docs/plan_graph_analysis.md - Selective Regeneration Strategy
    # ==========================================================================
    has_cached_tiles = bool(
        state.tiles.get("hotels") or state.tiles.get("activities") or state.tiles.get("flights")
    )

    if has_cached_tiles:
        # Check if destination is the same (tiles are destination-specific)
        cached_destination = state.metadata.get("tiles_destination")
        current_destination = plan.destination

        if cached_destination and cached_destination == current_destination:
            log("LOGISTICS", f"Cache HIT: Reusing cached tiles for {current_destination}")
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
            clog.event("cache_hit", "Tiles (all categories)", dest=current_destination)
            duration_ms = int((time.time() - node_start_time) * 1000)
            clog.node_end(
                "LOGISTICS",
                duration_ms,
                status="cache_hit",
                hotels=len(state.tiles.get("hotels", [])),
                activities=len(state.tiles.get("activities", [])),
            )
            return state

    # Store current destination for future cache checks
    state.metadata["tiles_destination"] = plan.destination

    # Mark that logistics has been attempted (prevents infinite loop in route_after_architect)
    state.metadata["logistics_attempted"] = True

    # ==========================================================================
    # DIAGNOSTIC LOGGING - Track origin sync (Issue 6 investigation)
    # ==========================================================================
    trip_inputs = state.metadata.get("trip_inputs", {})
    trip_inputs_origin = trip_inputs.get("origin")
    booking_types = trip_inputs.get("booking_types", {})
    flights_enabled = booking_types.get("flights") != "off"

    _debug_log(f"[LOGISTICS] trip_plan.origin={plan.origin!r}")
    _debug_log(f"[LOGISTICS] metadata.trip_inputs.origin={trip_inputs_origin!r}")
    _debug_log(f"[LOGISTICS] trip_inputs keys: {list(trip_inputs.keys())}")
    _debug_log(f"[LOGISTICS] flights_enabled={flights_enabled}")

    # Check for origin mismatch (reveals where sync breaks)
    if trip_inputs_origin and not plan.origin:
        logger.warning(
            f"[LOGISTICS] ⚠️ ORIGIN MISMATCH: trip_inputs has '{trip_inputs_origin}' "
            f"but trip_plan.origin is empty! Check _restore_graph_state sync in plan_graph.py"
        )

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
    origin_code = _city_to_code(plan.origin or "")
    dest_code = _city_to_code(plan.destination)
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

            # Build search context
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

    # Store in state
    state.tiles["hotels"] = hotel_dicts
    log("LOGISTICS", f"Found {len(hotel_dicts)} hotels for {plan.destination}")
    _debug_log(f"Hotels found: {len(hotel_dicts)}")

    state.tiles["activities"] = activity_dicts
    log("LOGISTICS", f"Found {len(activity_dicts)} activities for {plan.destination}")
    _debug_log(f"Activities found: {len(activity_dicts)}")

    # Update booking summary
    booking_summary = state.metadata.get("booking_summary", {})
    booking_summary["hotels_found"] = len(hotel_dicts)
    booking_summary["activities_found"] = len(activity_dicts)
    state.metadata["booking_summary"] = booking_summary


def _city_to_code(city: str) -> str:
    """Map city name to airport code."""
    if not city:
        return ""
    # Check if already an airport code (3 letters)
    if len(city) == 3 and city.isalpha():
        return city.upper()
    return city_to_airport_code(city) or ""


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
