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
from datetime import datetime, timedelta
from typing import Any, Dict, List

from app.data.demo_curation import CARRIER_MAP, DEMO_MANIFEST
from app.debug_utils import _debug_graph, _debug_graph_node_end, _debug_graph_node_start, log
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

    # DEBUG: Node start
    _debug_graph_node_start(
        "logistics",
        "✈️",
        destination=plan.destination,
        origin=plan.origin,
        dates=f"{plan.start_date} to {plan.end_date}",
    )

    # Mark that logistics has been attempted (prevents infinite loop in route_after_architect)
    state.metadata["logistics_attempted"] = True

    # Skip if missing required fields
    if not plan.destination or not plan.start_date:
        log("LOGISTICS", "Skipping - no destination or dates")
        _debug_graph_node_end("logistics", "✈️", status="skipped", reason="missing_fields")
        return state

    # Resolve airport codes for flights (flights need origin, hotels/activities don't)
    origin_code = _city_to_code(plan.origin or "")
    dest_code = _city_to_code(plan.destination)
    can_search_flights = bool(origin_code and dest_code)

    # CRITICAL FIX: Always search for hotels/activities even without origin
    # Hotels and activities only need destination + dates
    # @see docs/ux_unified_architecture.md - Enable tile search without origin
    await _search_hotels_and_activities(state, plan)

    # Skip flight search if missing origin
    if not can_search_flights:
        log("LOGISTICS", "Skipping flights (no origin) - hotels/activities searched")
        hotels_count = len(state.tiles.get("hotels", []))
        activities_count = len(state.tiles.get("activities", []))
        logger.info(
            f"[Logistics] No origin, skipped flights. "
            f"Hotels/activities tiles: {hotels_count} + {activities_count}"
        )
        _debug_graph_node_end(
            "logistics",
            "✈️",
            status="partial",
            reason="no_origin_for_flights",
            hotels=len(state.tiles.get("hotels", [])),
            activities=len(state.tiles.get("activities", [])),
        )
        return state

    log("LOGISTICS", f"Searching flights: {origin_code} -> {dest_code}")
    _debug_graph(
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
        _debug_graph(f"Curated flights: {[f.get('carrier_name') for f in curated_flights]}")
    else:
        # Use mock flights for non-curated destinations
        log("LOGISTICS", f"Using mock flights for {plan.destination}")
        raw_flights = _get_mock_flights(plan.end_date or plan.start_date)
        flight_source = "mock"
        _debug_graph(f"Mock provider returned {len(raw_flights)} flights")

    # 2. DETECT CONSTRAINTS
    # Check if diving specialist added a "no fly" or "24h" rule
    has_diving_safety_rule = _has_diving_constraints(state)
    if has_diving_safety_rule:
        log("LOGISTICS", "Diving safety constraints detected", data="applying 24h no-fly rule")
        _debug_graph("Will calculate surface interval for each flight")

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
            _debug_graph(f"Malformed offer skipped: {e}")
            continue

    # Log sanitization summary
    if sanitized_carriers:
        _debug_graph(f"Sanitized carriers: {', '.join(sanitized_carriers)}")

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
    _debug_graph_node_end(
        "logistics",
        "✈️",
        flights=len(processed_options),
        safe=safe_count,
        unsafe=unsafe_count,
        source=flight_source,
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
    Search for hotels and activities.

    Provider routing strategy (consistent with tile_service):
    1. Curated destinations (Dubai, Rome, Chamonix) → CuratedProvider (4K images, prices)
    2. Non-curated + Amadeus enabled → AmadeusHotelProvider (real names, placeholder images)
    3. Fallback → MockProviders

    @see docs/ux_unified_architecture.md Section XIII - Tile Provider Architecture

    CRITICAL: This runs independently of flight search.
    Hotels/Activities only need destination + dates, not origin.
    """
    _debug_graph(f"Searching hotels/activities for {plan.destination}...")

    # Build search context from trip_plan
    ctx = SearchContext(
        destination=plan.destination,
        origin=plan.origin,  # May be None - that's OK for hotels/activities
        start_date=str(plan.start_date) if plan.start_date else None,
        end_date=str(plan.end_date) if plan.end_date else None,
        adults=plan.adults or 1,
        children=plan.children or 0,
        currency="USD",
        verticals=["hotel", "activity"],
        max_results_per_vertical=5,
    )

    # Check for curated destination (hero destinations for demo)
    dest_key = plan.destination.lower().strip() if plan.destination else ""
    curated_manifest = DEMO_MANIFEST.get(dest_key, {})

    hotel_tiles = []
    activity_tiles = []

    if curated_manifest:
        # Use CuratedProvider for hero destinations
        log(
            "LOGISTICS",
            f"Using CuratedProvider for {plan.destination}",
            data="curated destination",
        )
        _debug_graph(f"Curated destination detected: {dest_key}")

        curated_provider = CuratedProvider(dest_key)
        all_tiles = curated_provider.search(ctx)

        # Separate by type
        for tile in all_tiles:
            if tile.type == "hotel":
                hotel_tiles.append(tile)
            elif tile.type == "activity":
                activity_tiles.append(tile)
    else:
        # 2. AMADEUS SECOND - Real hotel names with placeholder images
        from app.config import settings

        if settings.use_amadeus_provider:
            log(
                "LOGISTICS",
                f"Using Amadeus for hotels in {plan.destination}",
                data="real hotel names",
            )
            _debug_graph("Non-curated destination, using AmadeusHotelProvider")

            from app.tile_service.amadeus_provider import AmadeusHotelProvider

            hotel_provider = AmadeusHotelProvider()
            hotel_tiles = hotel_provider.search(ctx)
        else:
            # 3. MOCK FALLBACK - Development/offline mode
            log(
                "LOGISTICS",
                f"Using MockProviders for {plan.destination}",
                data="amadeus disabled",
            )
            _debug_graph("Amadeus disabled, using MockHotelProvider")

            hotel_provider = MockHotelProvider()
            hotel_tiles = hotel_provider.search(ctx)

        # Activities always use Mock (no Amadeus activities API)
        activity_provider = MockActivityProvider()
        activity_tiles = activity_provider.search(ctx)

    # Convert to dicts for state storage
    hotel_dicts = [_tile_to_dict(tile) for tile in hotel_tiles]
    activity_dicts = [_tile_to_dict(tile) for tile in activity_tiles]

    state.tiles["hotels"] = hotel_dicts
    log("LOGISTICS", f"Found {len(hotel_dicts)} hotels for {plan.destination}")
    _debug_graph(f"Hotels found: {len(hotel_dicts)}")

    state.tiles["activities"] = activity_dicts
    log("LOGISTICS", f"Found {len(activity_dicts)} activities for {plan.destination}")
    _debug_graph(f"Activities found: {len(activity_dicts)}")

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


def _offer_to_dict(offer) -> Dict[str, Any]:
    """Convert FlightOffer object to Amadeus-like dict."""
    return {
        "id": offer.id,
        "price": {"total": str(offer.price)},
        "itineraries": [
            {
                "segments": [
                    {
                        "carrierCode": offer.carrier_code,
                        "departure": {"at": offer.departure_time.isoformat()},
                        "duration": offer.duration,
                    }
                ]
            }
        ],
    }


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
