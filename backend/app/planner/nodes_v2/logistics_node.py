"""
Logistics Node - Fetches and sanitizes flight data from Amadeus.

Placed AFTER Specialist nodes (reads constraints) and BEFORE Architect.
This is the "Fetch & Polish" pattern for demo-ready data.

Key responsibilities:
1. Fetch flights from Amadeus API
2. Sanitize garbage test carriers (XX -> Emirates)
3. Apply 24h no-fly safety logic
4. Store results in state.metadata["flight_options"]
5. Fall back to demo backup if API fails
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

from app.data.demo_curation import CARRIER_MAP, DEMO_MANIFEST
from app.debug_utils import _debug_v2, _debug_v2_node_end, _debug_v2_node_start, log
from app.planner.state.schemas_v2 import GraphStateV2
from app.tools.amadeus_client import AmadeusClient, city_to_airport_code

logger = logging.getLogger(__name__)


# =============================================================================
# Main Node
# =============================================================================
async def logistics_node(state: GraphStateV2) -> GraphStateV2:
    """
    Logistics Node:
    1. Fetches raw flights from Amadeus (or backup).
    2. Sanitizes carrier names for a pro look.
    3. Applies 24h safety logic if diving constraints exist.
    """
    plan = state.trip_plan

    # DEBUG: Node start
    _debug_v2_node_start(
        "logistics",
        "✈️",
        destination=plan.destination,
        origin=plan.origin,
        dates=f"{plan.start_date} to {plan.end_date}",
    )

    # Skip if missing required fields
    if not plan.destination or not plan.start_date:
        log("LOGISTICS", "Skipping - no destination or dates")
        _debug_v2_node_end("logistics", "✈️", status="skipped", reason="missing_fields")
        return state

    origin_code = _city_to_code(plan.origin or "")
    dest_code = _city_to_code(plan.destination)

    if not origin_code or not dest_code:
        log("LOGISTICS", f"Could not resolve airport codes: {plan.origin} -> {plan.destination}")
        logger.warning(
            f"[Logistics] Could not resolve airport codes: {plan.origin} -> {plan.destination}"
        )
        _debug_v2_node_end("logistics", "✈️", status="skipped", reason="no_airport_codes")
        return state

    log("LOGISTICS", f"Searching flights: {origin_code} -> {dest_code}")
    _debug_v2(
        f"Flight search params: origin={origin_code}, dest={dest_code}, "
        f"date={plan.end_date or plan.start_date}"
    )

    # 1. CHECK FOR CURATED FLIGHTS (hero destinations)
    raw_flights = []
    flight_source = "unknown"
    dest_key = plan.destination.lower().strip()
    curated_manifest = DEMO_MANIFEST.get(dest_key, {})
    curated_flights = curated_manifest.get("curated_flights")

    if curated_flights:
        # Use curated flights for demo destinations (Dubai, Rome, Chamonix)
        log(
            "LOGISTICS",
            f"Using curated flights for {plan.destination}",
            data=f"{len(curated_flights)} options",
        )
        raw_flights = _curated_to_amadeus_format(curated_flights, plan.end_date or plan.start_date)
        flight_source = "curated"
        _debug_v2(f"Curated flights: {[f.get('carrier_name') for f in curated_flights]}")
    else:
        # 2. FETCH from Amadeus for non-curated destinations
        client = AmadeusClient()

        if client.is_configured():
            _debug_v2("Amadeus client configured, calling API...")
            try:
                # Use return date for the flight search (end of trip)
                departure_date = plan.end_date or plan.start_date
                offers = await client.search_flights(
                    origin=origin_code,
                    destination=dest_code,
                    departure_date=departure_date,
                    adults=plan.adults or 1,
                    max_results=5,
                )
                # Convert FlightOffer objects to Amadeus-like dicts for processing
                raw_flights = [_offer_to_dict(o) for o in offers]
                flight_source = "amadeus"
                _debug_v2(f"Amadeus returned {len(raw_flights)} flight offers")
            except Exception as e:
                log("LOGISTICS", f"Amadeus API failed: {e}", data="using fallback")
                logger.warning(f"[Logistics] Amadeus API failed: {e}")
                raw_flights = []
        else:
            _debug_v2("Amadeus client not configured, skipping API call")

    # 3. Fallback: If nothing found, use Demo Backup
    if not raw_flights:
        log("LOGISTICS", "Using DEMO BACKUP flight data", data="no curated or API data")
        raw_flights = _get_demo_backup_flights(plan.end_date or plan.start_date)
        flight_source = "demo_backup"
        _debug_v2(f"Demo backup provided {len(raw_flights)} flights")

    # 2. DETECT CONSTRAINTS
    # Check if diving specialist added a "no fly" or "24h" rule
    has_diving_safety_rule = _has_diving_constraints(state)
    if has_diving_safety_rule:
        log("LOGISTICS", "Diving safety constraints detected", data="applying 24h no-fly rule")
        _debug_v2("Will calculate surface interval for each flight")

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
            _debug_v2(f"Malformed offer skipped: {e}")
            continue

    # Log sanitization summary
    if sanitized_carriers:
        _debug_v2(f"Sanitized carriers: {', '.join(sanitized_carriers)}")

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
    _debug_v2_node_end(
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


def _city_to_code(city: str) -> str:
    """Map city name to airport code."""
    if not city:
        return ""
    # Check if already an airport code (3 letters)
    if len(city) == 3 and city.isalpha():
        return city.upper()
    return city_to_airport_code(city) or ""


def _has_diving_constraints(state: GraphStateV2) -> bool:
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


def _get_demo_backup_flights(date_str: str) -> List[Dict]:
    """
    Guaranteed data if API fails.
    Includes one UNSAFE option (08:00) and two SAFE options (18:00, 21:30).
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
