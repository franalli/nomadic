"""
Logistics Node - Fetches tiles (flights, hotels, activities) from providers.

Placed AFTER Specialist nodes (reads constraints) and BEFORE Architect.
This is the "Fetch & Polish" pattern for demo-ready data.

Provider routing strategy (consistent with tile_service):
1. Google Places enabled → GooglePlacesProvider (real names + photos)
2. Fallback → MockProviders

@see docs/ux_unified_architecture.md Section XIII - Tile Provider Architecture

Key responsibilities:
1. Fetch hotels/activities from providers (google_places → mock)
2. Fetch flights from curated data or mock
3. Sanitize garbage test carriers (XX -> Emirates)
4. Apply 24h no-fly safety logic for diving trips
5. Store results in state.tiles for frontend display
"""

import asyncio
import logging
import math
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List

from app.config import settings
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
from app.planner.state.graph_state import GraphState
from app.planner.state.typed_meta import get_trip_settings
from app.services.task_tracker import track as _track_task
from app.tile_service.mock_provider import MockActivityProvider, MockHotelProvider
from app.tile_service.models import SearchContext

logger = logging.getLogger(__name__)


# =============================================================================
# Cache Key Helpers — separate hotel/activity hashes to prevent cross-busting
# =============================================================================
def _hotel_logistics_hash(state: GraphState) -> str:
    """Hash inputs that affect hotel tile search. Changing activity settings won't bust this."""
    tp = state.trip_plan
    trip_settings = get_trip_settings(state)
    return stable_hash(
        {
            "destination": (tp.destination or "").lower(),
            "start_date": tp.start_date,
            "end_date": tp.end_date,
            "adults": tp.adults,
            "children": tp.children,
            "budget": tp.budget,
            "hotel_settings": trip_settings.hotel_settings.model_dump(),
        }
    )


def _activity_logistics_hash(state: GraphState) -> str:
    """Hash inputs that affect activity tile search. Changing hotel settings won't bust this."""
    tp = state.trip_plan
    trip_settings = get_trip_settings(state)
    return stable_hash(
        {
            "destination": (tp.destination or "").lower(),
            "start_date": tp.start_date,
            "end_date": tp.end_date,
            "adults": tp.adults,
            "children": tp.children,
            "activity_skill_level": trip_settings.activity_settings.skill_level,
            "activity_categories": sorted(trip_settings.activity_settings.categories),
        }
    )


def _flight_logistics_hash(state: GraphState) -> str:
    """Hash inputs that affect flight search."""
    tp = state.trip_plan
    trip_settings = get_trip_settings(state)
    return stable_hash(
        {
            "destination": (tp.destination or "").lower(),
            "origin": (tp.origin or "").lower(),
            "start_date": tp.start_date,
            "end_date": tp.end_date,
            "adults": tp.adults,
            "children": tp.children,
            "flight_settings": trip_settings.flight_settings.model_dump(),
        }
    )


def _tier2_generation_key(
    destination: str,
    month: str,
    categories: set[str],
    tiles_per_category: int,
) -> str:
    normalized_destination = (destination or "").strip().lower()
    normalized_month = (month or "").strip().lower()
    normalized_categories = "|".join(sorted(c.strip().lower() for c in categories if c.strip()))
    return (
        f"tier2:{normalized_destination}:{normalized_month}:"
        f"{normalized_categories}:n{tiles_per_category}"
    )


def _cached_tier2_tiles_for_categories(
    state: GraphState,
    destination: str,
    categories: set[str],
) -> list[dict]:
    generated = state.metadata.get("generated_tier2_categories", {}) or {}
    destination_tiles = generated.get(destination, {}) or {}
    tiles: list[dict] = []
    for category in sorted(categories):
        cat_tiles = destination_tiles.get(category, [])
        if not cat_tiles:
            return []
        tiles.extend(cat_tiles)
    return tiles


def _fallback_tier2_tiles(existing_tiles: list[dict], categories: set[str]) -> list[dict]:
    matching = [t for t in existing_tiles if _tile_matches_categories(t, categories)]
    return matching or existing_tiles


async def _resolve_tier2_experience_tiles(
    *,
    state: GraphState,
    destination: str,
    month: str,
    categories: set[str],
    tiles_per_category: int,
    budget: int | None,
    tier1_specialists: list[str] | None,
    fallback_tiles: list[dict],
    consume_prefetch,
    allow_prefetch_wait: bool = True,
    generate_fn=None,
    create_task_fn=None,
) -> list[dict]:
    from app.services.experience_generator import generate_experiences

    generate_fn = generate_fn or generate_experiences
    create_task_fn = create_task_fn or asyncio.create_task

    started_at = time.monotonic()
    generation_key = _tier2_generation_key(destination, month, categories, tiles_per_category)
    previous_key = state.metadata.get("tier2_generation_key")
    cached_tiles = _cached_tier2_tiles_for_categories(state, destination, categories)
    source = "llm"
    reason = "none"
    experience_tiles: list[dict] | None = None

    if previous_key == generation_key and cached_tiles:
        source = "reuse"
        reason = "matching_generation_key"
        experience_tiles = cached_tiles

    if experience_tiles is None and allow_prefetch_wait:
        prefetched = await consume_prefetch()
        if prefetched:
            source = "prefetch"
            reason = "router_prefetch"
            experience_tiles = prefetched

    if experience_tiles is None:
        wait_budget_ms = max(0, settings.tier2_generation_wait_budget_ms)
        wait_budget_seconds = wait_budget_ms / 1000.0
        try:
            if wait_budget_seconds > 0:
                experience_tiles = await asyncio.wait_for(
                    generate_fn(
                        destination=destination,
                        categories=list(categories),
                        month=month,
                        budget=budget,
                        tier1_specialists=tier1_specialists,
                        tiles_per_category=tiles_per_category,
                        state=state,
                    ),
                    timeout=wait_budget_seconds,
                )
            else:
                experience_tiles = await generate_fn(
                    destination=destination,
                    categories=list(categories),
                    month=month,
                    budget=budget,
                    tier1_specialists=tier1_specialists,
                    tiles_per_category=tiles_per_category,
                    state=state,
                )
            source = state.metadata.pop("tier2_generation_source_internal", "llm")
            reason = "llm_generation" if source == "llm" else "cache_generation"
        except asyncio.TimeoutError:
            source = "fallback_timeout"
            reason = "timeout"
            experience_tiles = _fallback_tier2_tiles(fallback_tiles, categories)
            _debug_log(
                "[VERIFY][TIER2] generation_timeout "
                f"key={generation_key} budget_ms={wait_budget_ms}"
            )

            async def _background_prewarm() -> None:
                try:
                    await generate_fn(
                        destination=destination,
                        categories=list(categories),
                        month=month,
                        budget=budget,
                        tier1_specialists=tier1_specialists,
                        tiles_per_category=tiles_per_category,
                        state=None,
                    )
                except Exception:
                    pass

            create_task_fn(_background_prewarm())
        except Exception as e:
            source = "fallback_timeout"
            reason = f"error:{type(e).__name__}"
            experience_tiles = _fallback_tier2_tiles(fallback_tiles, categories)
            _debug_log(
                f"[VERIFY][TIER2] generation_error key={generation_key} err={type(e).__name__}"
            )

            async def _background_prewarm() -> None:
                try:
                    await generate_fn(
                        destination=destination,
                        categories=list(categories),
                        month=month,
                        budget=budget,
                        tier1_specialists=tier1_specialists,
                        tiles_per_category=tiles_per_category,
                        state=None,
                    )
                except Exception:
                    pass

            create_task_fn(_background_prewarm())

    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    state.metadata["tier2_generation_key"] = generation_key
    state.metadata["tier2_generation_source"] = source
    state.metadata["tier2_generation_elapsed_ms"] = elapsed_ms
    state.metadata["tier2_generation_reason"] = reason
    _debug_log(f"[VERIFY][TIER2] key={generation_key} source={source} elapsed_ms={elapsed_ms}")
    _debug_log(
        "[VERIFY][LLM_LATENCY] "
        f"component=experience source={source} elapsed_ms={elapsed_ms} reason={reason}"
    )

    return experience_tiles or []


# =============================================================================
# Main Node
# =============================================================================
async def logistics_node(state: GraphState) -> GraphState:
    """
    Logistics Node:
    1. Fetches raw flights from curated data or mock providers.
    2. Sanitizes carrier names for a pro look.
    3. Applies 24h safety logic if no-fly constraints exist.
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
    # SELECTIVE REGENERATION: Per-category hash-based cache check
    # Separate hotel/activity/flight hashes prevent cross-busting:
    # changing hotel_settings won't refetch activities, and vice versa.
    # @see docs/plan_graph_analysis.md - Selective Regeneration Strategy
    # ==========================================================================
    has_cached_tiles = bool(
        state.tiles.get("hotels") or state.tiles.get("activities") or state.tiles.get("flights")
    )

    if has_cached_tiles:
        cur_hotel_hash = _hotel_logistics_hash(state)
        cur_activity_hash = _activity_logistics_hash(state)
        cur_flight_hash = _flight_logistics_hash(state)
        cached_hotel_hash = state.metadata.get("_logistics_hotel_hash")
        cached_activity_hash = state.metadata.get("_logistics_activity_hash")
        cached_flight_hash = state.metadata.get("_logistics_flight_hash")

        hotel_ok = cached_hotel_hash and cur_hotel_hash == cached_hotel_hash
        activity_ok = cached_activity_hash and cur_activity_hash == cached_activity_hash
        flight_ok = cached_flight_hash and cur_flight_hash == cached_flight_hash

        if hotel_ok and activity_ok and flight_ok:
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
            state.metadata["logistics_attempted"] = True
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

        # Selective invalidation — only clear changed categories
        changed = []
        if not hotel_ok:
            state.tiles["hotels"] = []
            changed.append("hotels")
        if not activity_ok:
            state.tiles["activities"] = []
            changed.append("activities")
        if not flight_ok:
            state.tiles["flights"] = []
            changed.append("flights")

        if cached_hotel_hash or cached_activity_hash or cached_flight_hash:
            log(
                "LOGISTICS",
                f"State invalidation (L1): {', '.join(changed)} changed for {plan.destination}",
            )
            _debug_log(f"[TILE_STATE] Selective invalidation (L1): {', '.join(changed)}")
            state.metadata["_tiles_replaced"] = True
            clog.event("cache_invalidate", f"{', '.join(changed)} changed for {plan.destination}")

    # Store current hashes for future cache checks
    state.metadata["tiles_destination"] = plan.destination
    state.metadata["_logistics_hotel_hash"] = _hotel_logistics_hash(state)
    state.metadata["_logistics_activity_hash"] = _activity_logistics_hash(state)
    state.metadata["_logistics_flight_hash"] = _flight_logistics_hash(state)

    # Mark that logistics has been attempted (prevents infinite loop in route_after_architect)
    state.metadata["logistics_attempted"] = True

    # ==========================================================================
    # DIAGNOSTIC LOGGING - Track origin sync (Issue 6 investigation)
    # ==========================================================================
    _logistics_settings = get_trip_settings(state)
    flights_requested = _logistics_settings.booking_types.flights != "off"

    # Auto-upgrade flights when origin is available but flights still at default 'off'.
    # Mirrors frontend logic in documentStore.ts:52 ("Upgrades to 'suggested' when origin is set")
    # but runs server-side where origin is available in-time (frontend PATCH races the graph).
    if not flights_requested and plan.origin:
        _debug_log("[LOGISTICS] ✈️ Auto-upgrading flights: off → suggested (origin present)")
        flights_requested = True
        # Persist so frontend stays in sync on next document fetch
        trip_inputs_bt = state.metadata.get("trip_inputs", {}).get("booking_types", {})
        trip_inputs_bt["flights"] = "suggested"

    direct_only_requested = bool(_logistics_settings.flight_settings.direct_only)
    trip_inputs = state.metadata.get("trip_inputs", {})
    trip_inputs_origin = trip_inputs.get("origin")

    _debug_log(f"[LOGISTICS] trip_plan.origin={plan.origin!r}")
    _debug_log(
        f"[LOGISTICS] flights_requested={flights_requested} origin_present={bool(plan.origin)}"
    )

    # Skip flights if disabled in settings (even if origin exists)
    if not flights_requested:
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

    # Resolve airport codes only when flight search is actually possible.
    # Avoids unnecessary LLM latency when flights are disabled or origin is missing.
    origin_code = ""
    dest_code = ""
    if flights_requested and plan.origin:
        # Reads state first (populated by router), falls back to LLM only if missing.
        origin_code, dest_code = await resolve_iata_codes(
            plan.origin or "", plan.destination, state
        )

    # Can only search flights if: flights enabled + origin provided + codes resolved
    can_search_flights = flights_requested and bool(plan.origin) and bool(origin_code and dest_code)

    state.metadata["flight_search_possible"] = can_search_flights

    # CRITICAL FIX: Always search for hotels/activities even without origin
    # Hotels and activities only need destination + dates
    # @see docs/ux_unified_architecture.md - Enable tile search without origin
    await _search_hotels_and_activities(state, plan)

    # Skip flight search if disabled or missing origin
    if not can_search_flights:
        # Determine the specific reason for skipping
        if not flights_requested:
            skip_reason = "flights_disabled_in_settings"
            status = "skipped_disabled"
            log("LOGISTICS", "Skipping flights - disabled in settings")
        elif not plan.origin:
            skip_reason = "no_origin_for_flights"
            status = "skipped_no_origin"
            log("LOGISTICS", "Skipping flights (no origin) - hotels/activities searched")
            # Extra diagnostic if trip_inputs has origin but trip_plan doesn't
            if trip_inputs_origin:
                _debug_log(
                    f"[LOGISTICS] 🔍 trip_inputs.origin='{trip_inputs_origin}' but "
                    f"trip_plan.origin is empty - sync bug detected!"
                )
        else:
            skip_reason = "airport_code_resolution_failed"
            status = "skipped_code_resolution"
            log("LOGISTICS", "Skipping flights - could not resolve airport codes")

        state.metadata["flight_search_status"] = status
        state.metadata["flight_skip_reason"] = skip_reason

        hotels_count = len(state.tiles.get("hotels", []))
        activities_count = len(state.tiles.get("activities", []))
        booking_summary = state.metadata.get("booking_summary", {})
        booking_summary["flights_found"] = 0
        state.metadata["booking_summary"] = booking_summary
        logger.info(
            f"[Logistics] Skipped flights ({skip_reason}). "
            f"Hotels/activities tiles: {hotels_count} + {activities_count}"
        )
        _debug_log(
            "[VERIFY][FLIGHTS] "
            f"requested={flights_requested} search_possible={can_search_flights} "
            f"status={status} reason={skip_reason} origin_present={bool(plan.origin)}"
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
        raw_flights = _curated_to_flight_tiles(curated_flights, plan.end_date or plan.start_date)
        flight_source = "curated"
        _debug_log(f"Curated flights: {[f.get('carrier_name') for f in curated_flights]}")
    else:
        # Use mock flights for non-curated destinations
        log("LOGISTICS", f"Using mock flights for {plan.destination}")
        raw_flights = _get_mock_flights(plan.end_date or plan.start_date)
        flight_source = "mock"
        _debug_log(f"Mock provider returned {len(raw_flights)} flights")

    # 2. DETECT CONSTRAINTS
    # Check if any specialist has a no-fly buffer constraint (e.g., diving 24h rule)
    has_nofly_safety_rule = _has_nofly_constraints(state)
    if has_nofly_safety_rule:
        log("LOGISTICS", "No-fly safety constraints detected", data="applying no-fly buffer rule")
        _debug_log("Will calculate surface interval for each flight")

    # 3. PROCESS & SANITIZE
    processed_options = []
    sanitized_carriers = []
    dropped_non_direct = 0

    for offer in raw_flights:
        try:
            itinerary = offer["itineraries"][0]
            segments = itinerary.get("segments", [])
            if not segments:
                logger.warning("[Logistics] Skipping offer with no segments")
                continue
            segment = segments[0]
            carrier_code = segment["carrierCode"]
            dep_time_str = segment["departure"]["at"]
            duration_iso = segment.get("duration", "PT6H")
            stops = max(0, len(segments) - 1)
            is_direct = stops == 0

            if direct_only_requested and not is_direct:
                dropped_non_direct += 1
                continue

            # A. Sanitize Carrier (The "Pro" Polish)
            carrier_info = CARRIER_MAP.get(
                carrier_code, {"name": carrier_code, "logo": carrier_code}
            )
            if carrier_code in CARRIER_MAP and carrier_code != carrier_info["logo"]:
                sanitized_carriers.append(f"{carrier_code}->{carrier_info['logo']}")
            logo_url = f"https://pics.avs.io/200/200/{carrier_info['logo']}.png"

            # B. Apply Safety Math (The "Constraint Engine")
            logic_hook = None
            is_safe = True  # Default to safe if no no-fly constraints
            if has_nofly_safety_rule:
                logic_hook, is_safe = _calculate_diving_safety(dep_time_str)

            # C. Format Duration
            duration_clean = duration_iso.replace("PT", "").lower()
            stops_label = "Direct" if is_direct else f"{stops} stop{'s' if stops > 1 else ''}"

            # Build Tile-compatible dict for state.tiles["flights"]
            price_value = float(offer["price"]["total"])
            option = {
                "id": offer["id"],
                "type": "flight",
                "partner": "curated" if flight_source == "curated" else "mock",
                "partner_product_id": offer["id"],
                "title": f"{carrier_info['name']} - {stops_label}",
                "subtitle": f"Departs {dep_time_str.split('T')[1][:5]} • {duration_clean}",
                "image_url": logo_url,
                "price_estimate": price_value,
                "currency": plan.currency or "USD",
                "price_basis": "per_person",
                "is_estimate_only": True,
                "deeplink_url": "#",
                "tags": [carrier_info["name"], stops_label.lower()],
                "availability_status": "available",
                "meta": {
                    "logic_hook": logic_hook,
                    "is_safe": is_safe,  # CRITICAL: Frontend checks this for amber border
                    "carrier_code": carrier_info["logo"],
                    "carrier_name": carrier_info["name"],
                    "departure_time": dep_time_str,
                    "duration": duration_clean,
                    "stops": stops,
                    "is_direct": is_direct,
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
    if direct_only_requested and dropped_non_direct > 0:
        log(
            "LOGISTICS",
            "Direct-flight filter applied",
            data=f"removed {dropped_non_direct} non-direct options",
        )
        _debug_log(f"[VERIFY][FLIGHTS] direct_only=true removed_non_direct={dropped_non_direct}")

    # 4. STORE IN STATE - Write to state.tiles["flights"] for frontend display
    state.tiles["flights"] = processed_options
    # Also keep in metadata for backwards compatibility
    state.metadata["flight_options"] = processed_options
    state.metadata["flight_search_status"] = "searched"
    state.metadata["flight_skip_reason"] = None
    state.metadata["flight_search_possible"] = True

    # Update summary
    booking_summary = state.metadata.get("booking_summary", {})
    booking_summary["flights_found"] = len(processed_options)
    state.metadata["booking_summary"] = booking_summary

    # Count safe vs unsafe flights
    safe_count = sum(1 for opt in processed_options if (opt.get("meta") or {}).get("is_safe", True))
    unsafe_count = len(processed_options) - safe_count

    # Final logging
    log(
        "LOGISTICS",
        f"Found {len(processed_options)} flight options",
        data=f"safe={safe_count}, unsafe={unsafe_count}" if has_nofly_safety_rule else None,
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
    """Convert a Tile object to a dict for state storage.

    Supports both Pydantic models (model_dump) and plain objects used by tests
    (SimpleNamespace, MagicMock). The source_agent default is applied after
    serialization to preserve logistics attribution.
    """
    d: Dict[str, Any] = {}

    model_dump = getattr(tile, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump()
            if isinstance(dumped, dict):
                d = dumped
        except Exception:
            d = {}

    if not d:
        if isinstance(tile, dict):
            d = dict(tile)
        else:
            from app.schemas import Tile as TileSchema

            attrs = vars(tile) if hasattr(tile, "__dict__") else {}
            if attrs:
                d = {field: attrs[field] for field in TileSchema.model_fields if field in attrs}
            else:
                # Fallback for attribute-only objects without __dict__.
                for field in TileSchema.model_fields:
                    if hasattr(tile, field):
                        value = getattr(tile, field)
                        if not callable(value):
                            d[field] = value

    if not d.get("source_agent"):
        d["source_agent"] = "logistics_node"
    return d


async def _fetch_hotels(
    async_session_factory,
    plan,
    hotel_settings,
    provider,
    dest_key,
    start_date,
    end_date,
    activity_settings,
    flight_settings,
    dest_lat: float | None = None,
    dest_lng: float | None = None,
):
    """
    Fetch hotel tiles with L1+L2 caching.

    Runs in parallel with _fetch_activities() for latency optimization.
    """
    from app.services.tile_cache import get_cached_tiles, set_cached_tiles

    # Build hotel cache variant from min_stars so changing star preference busts the cache
    _min_stars = (
        int(hotel_settings.get("min_stars") or 0) if isinstance(hotel_settings, dict) else 0
    )
    hotel_cache_variant = f"stars{_min_stars}" if _min_stars > 0 else ""

    async with async_session_factory() as db:
        # =====================================================================
        # HOTELS CACHE CHECK
        # =====================================================================
        cached_hotels = await get_cached_tiles(
            db, provider, "hotel", plan.destination, start_date, end_date, hotel_cache_variant
        )

        if cached_hotels:
            _debug_log(f"[TILE_CACHE] Hotels HIT: {len(cached_hotels)} hotels from cache")
            log(
                "LOGISTICS",
                f"Provider cache HIT (L2): hotels for {plan.destination}",
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
                currency=plan.currency or "USD",
                verticals=["hotel", "activity"],
                max_results_per_vertical=5,
                origin_iata=plan.origin_iata or None,
                destination_iata=plan.destination_iata or None,
                hotel_settings=hotel_settings or None,
                activity_settings=activity_settings or None,
                flight_settings=flight_settings or None,
                destination_lat=dest_lat,
                destination_lng=dest_lng,
            )

            hotel_tiles = []
            _provider_t0 = time.time()

            from app.config import settings

            if settings.use_google_places_provider:
                log(
                    "LOGISTICS",
                    f"Using GooglePlaces for hotels in {plan.destination}",
                    data="real hotel names + photos",
                )
                from app.tile_service.google_places_provider import GooglePlacesHotelProvider

                hotel_provider = GooglePlacesHotelProvider()
                hotel_tiles = await hotel_provider.search_async(ctx)
                # Fallback to mock if Places returned nothing (quota, error, etc.)
                if not hotel_tiles:
                    log("LOGISTICS", "GooglePlaces returned 0 hotels — using mock fallback")
                    hotel_tiles = await asyncio.to_thread(MockHotelProvider().search, ctx)
            else:
                log(
                    "LOGISTICS",
                    f"Using MockProviders for {plan.destination}",
                    data="live providers disabled",
                )
                hotel_provider = MockHotelProvider()
                hotel_tiles = await asyncio.to_thread(hotel_provider.search, ctx)

            _provider_ms = int((time.time() - _provider_t0) * 1000)
            _debug_log(f"Hotel provider ({provider}): {_provider_ms}ms, {len(hotel_tiles)} tiles")

            # Convert to dicts and cache
            hotel_dicts = [_tile_to_dict(tile) for tile in hotel_tiles]

            if hotel_dicts:
                await set_cached_tiles(
                    db,
                    provider,
                    "hotel",
                    plan.destination,
                    start_date,
                    end_date,
                    hotel_dicts,
                    hotel_cache_variant,
                )

    return hotel_dicts


async def _fetch_activities(
    async_session_factory,
    plan,
    activity_settings,
    provider,
    dest_key,
    start_date,
    end_date,
    hotel_settings,
    flight_settings,
    max_results: int = 5,
    dest_lat: float | None = None,
    dest_lng: float | None = None,
):
    """
    Fetch activity tiles with L1+L2 caching.

    Runs in parallel with _fetch_hotels() for latency optimization.
    """
    from app.services.tile_cache import get_cached_tiles, set_cached_tiles

    async with async_session_factory() as db:
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
                f"Provider cache HIT (L2): activities for {plan.destination}",
                data=f"{len(cached_activities)} activities",
            )
            activity_dicts = cached_activities
        else:
            _debug_log(f"[TILE_CACHE] Activities MISS - fetching from {provider}")

            # Build search context — scale activity count by trip length
            ctx = SearchContext(
                destination=plan.destination,
                origin=plan.origin,
                start_date=start_date or None,
                end_date=end_date or None,
                adults=plan.adults or 1,
                children=plan.children or 0,
                currency=plan.currency or "USD",
                verticals=["hotel", "activity"],
                max_results_per_vertical=max_results,
                origin_iata=plan.origin_iata or None,
                destination_iata=plan.destination_iata or None,
                hotel_settings=hotel_settings or None,
                activity_settings=activity_settings or None,
                flight_settings=flight_settings or None,
                destination_lat=dest_lat,
                destination_lng=dest_lng,
            )

            activity_tiles = []

            from app.config import settings

            if settings.use_google_places_provider:
                from app.tile_service.google_places_provider import GooglePlacesActivityProvider

                activity_provider = GooglePlacesActivityProvider()
                activity_tiles = await activity_provider.search_async(ctx)
                if not activity_tiles:
                    log("LOGISTICS", "GooglePlaces returned 0 activities — using mock fallback")
                    activity_tiles = await asyncio.to_thread(MockActivityProvider().search, ctx)
            else:
                # Activities always use Mock (no live API)
                activity_provider = MockActivityProvider()
                activity_tiles = await asyncio.to_thread(activity_provider.search, ctx)

            # Convert to dicts and cache
            activity_dicts = [_tile_to_dict(tile) for tile in activity_tiles]

            if activity_dicts:
                await set_cached_tiles(
                    db, provider, "activity", plan.destination, start_date, end_date, activity_dicts
                )

    return activity_dicts


async def _search_hotels_and_activities(state: GraphState, plan) -> None:
    """
    Search for hotels and activities with L1+L2 caching.

    Provider routing strategy (consistent with tile_service):
    1. Google Places enabled → GooglePlacesProvider (real names + photos)
    2. Fallback → MockProviders

    Caching strategy:
    - Check cache before provider calls
    - Store raw results in cache (filter post-retrieval)
    - 24h TTL for tile data (prices change daily)

    Hotels and activities are fetched in PARALLEL using asyncio.gather() for latency optimization.

    @see docs/ux_unified_architecture.md Section XIII - Tile Provider Architecture
    """
    from app.db import _get_async_session_factory

    _debug_log(f"Searching hotels/activities for {plan.destination}...")

    def _activity_tile_id_set(tiles) -> set[str]:
        if not isinstance(tiles, list):
            return set()
        return {
            str(tile.get("id"))
            for tile in tiles
            if isinstance(tile, dict) and tile.get("id") is not None
        }

    # Read user settings for provider filtering
    _settings = get_trip_settings(state)
    hotel_settings = _settings.hotel_settings.model_dump()
    activity_settings = _settings.activity_settings.model_dump()
    flight_settings = _settings.flight_settings.model_dump()
    activities_requested = _settings.booking_types.activities != "off"

    # Determine provider and cache key parameters
    dest_key = plan.destination.lower().strip() if plan.destination else ""
    if settings.use_google_places_provider:
        provider = "google_places"
    else:
        provider = "mock"

    log(
        "LOGISTICS",
        f"[TILE_CASCADE] destination={dest_key} provider={provider}",
        data=f"gp={settings.use_google_places_provider}",
    )

    start_date = str(plan.start_date) if plan.start_date else ""
    end_date = str(plan.end_date) if plan.end_date else ""

    # Get database session factory for caching
    async_session_factory = _get_async_session_factory()

    # Scale activity fetch count by trip length (longer trips need more base tiles)
    activity_max_results = 5  # default
    if start_date and end_date:
        try:
            _sd = datetime.strptime(start_date, "%Y-%m-%d")
            _ed = datetime.strptime(end_date, "%Y-%m-%d")
            _trip_days = (_ed - _sd).days + 1
            activity_max_results = min(max(5, _trip_days - 2), 10)
        except ValueError:
            pass

    # Geocode destination once for locationBias (both hotels and activities share the result)
    dest_lat: float | None = None
    dest_lng: float | None = None
    if settings.use_google_places_provider and dest_key:
        from app.tile_service.google_places_provider import _geocode_destination_async

        geo = await _geocode_destination_async(plan.destination or dest_key)
        if geo:
            dest_lat, dest_lng = geo
            _debug_log(f"[TILE_GEOCODE] {plan.destination} → ({dest_lat:.4f}, {dest_lng:.4f})")

    # Fetch hotels and activities in PARALLEL (unless activities are explicitly disabled).
    # booking_types.activities='off' means "never show or search activities".
    _gather_t0 = time.time()
    if activities_requested:
        hotel_dicts, activity_dicts = await asyncio.gather(
            _fetch_hotels(
                async_session_factory,
                plan,
                hotel_settings,
                provider,
                dest_key,
                start_date,
                end_date,
                activity_settings,
                flight_settings,
                dest_lat=dest_lat,
                dest_lng=dest_lng,
            ),
            _fetch_activities(
                async_session_factory,
                plan,
                activity_settings,
                provider,
                dest_key,
                start_date,
                end_date,
                hotel_settings,
                flight_settings,
                max_results=activity_max_results,
                dest_lat=dest_lat,
                dest_lng=dest_lng,
            ),
        )
    else:
        hotel_dicts = await _fetch_hotels(
            async_session_factory,
            plan,
            hotel_settings,
            provider,
            dest_key,
            start_date,
            end_date,
            activity_settings,
            flight_settings,
            dest_lat=dest_lat,
            dest_lng=dest_lng,
        )
        activity_dicts = []
    _gather_ms = int((time.time() - _gather_t0) * 1000)
    _debug_log(
        f"Hotel+Activity gather: {_gather_ms}ms "
        f"(hotels={len(hotel_dicts)}, activities={len(activity_dicts)})"
    )

    # Post-fetch hotel star filter (curated provider filters at search time,
    # but mock/cached tiles need post-fetch filtering)
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

    if not activities_requested:
        state.tiles["activities"] = []
        state.metadata.pop("browseable_activities", None)
        state.metadata.pop("active_plan_categories", None)
        state.metadata.pop("tier2_generation_key", None)
        state.metadata.pop("tier2_generation_source", None)
        state.metadata.pop("tier2_generation_elapsed_ms", None)
        state.metadata.pop("tier2_generation_reason", None)
        state.metadata.pop("tier2_new_content_generated", None)

        log(
            "LOGISTICS",
            "Activities disabled in settings — skipped activity fetch/generation",
        )
        _debug_log("[LOGISTICS] activities_requested=False -> no activity tiles generated")

        booking_summary = state.metadata.get("booking_summary", {})
        booking_summary["hotels_found"] = len(hotel_dicts)
        booking_summary["activities_found"] = 0
        state.metadata["booking_summary"] = booking_summary
        return

    previous_activity_ids = _activity_tile_id_set(state.tiles.get("activities", []))
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
    from app.planner.specialist_registry import TIER1_SPECIALIST_NAMES

    NICHE_SPECIALISTS = TIER1_SPECIALIST_NAMES
    TIER1_CATEGORIES = TIER1_SPECIALIST_NAMES
    executed = state.metadata.get("executed_strategy_topics", [])
    used_tier2_categories: set[str] = set()
    tier2_attempted = False

    async def _consume_tier2_prefetch(
        expected_categories: set[str],
        expected_tiles_per_category: int,
        expected_destination: str,
        expected_month: str,
    ) -> list[dict] | None:
        wait_started_at = time.monotonic()
        prefetch_task = state.metadata.get("tier2_prefetch_task")
        prefetch_cats = set(state.metadata.get("tier2_prefetch_categories", []))
        prefetch_tiles_per_cat = state.metadata.get("tier2_prefetch_tiles_per_category")
        prefetch_destination = state.metadata.get("tier2_prefetch_destination")
        prefetch_month = state.metadata.get("tier2_prefetch_month")
        prefetch_key = state.metadata.get("tier2_prefetch_key")
        wait_budget_ms = max(0, settings.tier2_prefetch_wait_budget_ms)
        wait_budget_seconds = wait_budget_ms / 1000.0
        expected_key = _tier2_generation_key(
            expected_destination,
            expected_month,
            expected_categories,
            expected_tiles_per_category,
        )

        if not prefetch_task:
            _debug_log("[VERIFY][PREFETCH] no task present")
            return None
        if prefetch_key != expected_key:
            _debug_log(f"[VERIFY][PREFETCH] key_skip expected={expected_key} got={prefetch_key}")
            log(
                "LOGISTICS",
                (
                    "[PREFETCH] Key mismatch - skipping prefetch "
                    f"(expected={expected_key}, got={prefetch_key})"
                ),
            )
            return None
        _debug_log(f"[VERIFY][PREFETCH] key_match key={expected_key}")
        if prefetch_destination != expected_destination or prefetch_month != expected_month:
            _debug_log(
                "[VERIFY][PREFETCH] skip=context "
                f"expected={expected_destination}:{expected_month} "
                f"got={prefetch_destination}:{prefetch_month}"
            )
            log(
                "LOGISTICS",
                (
                    "[PREFETCH] Context mismatch - skipping prefetch "
                    f"(expected={expected_destination}:{expected_month}, "
                    f"got={prefetch_destination}:{prefetch_month})"
                ),
            )
            return None
        if prefetch_cats != expected_categories:
            _debug_log(
                "[VERIFY][PREFETCH] skip=categories "
                f"expected={sorted(expected_categories)} got={sorted(prefetch_cats)}"
            )
            log(
                "LOGISTICS",
                (
                    "[PREFETCH] Category mismatch - skipping prefetch "
                    f"(expected={expected_categories}, got={prefetch_cats})"
                ),
            )
            return None
        if prefetch_tiles_per_cat != expected_tiles_per_category:
            _debug_log(
                "[VERIFY][PREFETCH] skip=tile_count "
                f"expected={expected_tiles_per_category} got={prefetch_tiles_per_cat}"
            )
            log(
                "LOGISTICS",
                (
                    "[PREFETCH] Tile-count mismatch - using prefetch as warmup "
                    f"(expected={expected_tiles_per_category}, got={prefetch_tiles_per_cat})"
                ),
            )
            return None
        if wait_budget_seconds <= 0:
            _debug_log("[VERIFY][PREFETCH] skip=budget_zero")
            return None

        # Skip wait if L1 is cold — prefetch hasn't populated the cache yet,
        # so waiting just wastes the budget. Singleflight in generate_experiences()
        # will join the running task anyway.
        from app.services.experience_generator import has_cached as _exp_has_cached

        if prefetch_task.done():
            pass  # Task finished — always consume result
        elif not _exp_has_cached(
            expected_destination,
            sorted(expected_categories),
            expected_month,
            expected_tiles_per_category,
        ):
            _debug_log("[VERIFY][PREFETCH] skip=l1_cold (singleflight will join)")
            log("LOGISTICS", "[PREFETCH] L1 cold — skipping wait, singleflight will join")
            return None

        log(
            "LOGISTICS",
            (
                "[PREFETCH] Waiting for Router prefetch "
                f"(cats={len(expected_categories)}, budget={wait_budget_ms}ms)"
            ),
        )
        done, _ = await asyncio.wait({prefetch_task}, timeout=wait_budget_seconds)
        if not done:
            elapsed_ms = int((time.monotonic() - wait_started_at) * 1000)
            _debug_log(
                "[VERIFY][PREFETCH] fallback=timeout "
                f"elapsed_ms={elapsed_ms} budget_ms={wait_budget_ms}"
            )
            log(
                "LOGISTICS",
                f"[PREFETCH] Budget exhausted ({wait_budget_ms}ms) - falling back",
            )
            return None

        try:
            result = prefetch_task.result()
        except Exception as e:
            elapsed_ms = int((time.monotonic() - wait_started_at) * 1000)
            _debug_log(
                "[VERIFY][PREFETCH] fallback=task_error "
                f"elapsed_ms={elapsed_ms} err={type(e).__name__}"
            )
            log("LOGISTICS", f"[PREFETCH] Prefetch task failed - falling back: {e}")
            return None

        elapsed_ms = int((time.monotonic() - wait_started_at) * 1000)
        _debug_log(
            "[VERIFY][PREFETCH] consumed "
            f"tiles={len(result)} elapsed_ms={elapsed_ms} budget_ms={wait_budget_ms}"
        )
        log("LOGISTICS", f"[PREFETCH] Consumed {len(result)} tiles from prefetch")
        return result

    has_niche_specialist = any(t in NICHE_SPECIALISTS for t in executed)
    if has_niche_specialist:
        selected_cats = set(get_trip_settings(state).activity_settings.categories)
        tier2_cats = selected_cats - TIER1_CATEGORIES

        if not tier2_cats:
            # Pure Tier 1 — specialist provides curated activities.
            # Suppress generic tiles from auto-scheduling; fetch per-category
            # browse tiles (6 parallel Places queries) so the Browse Activities
            # sheet has rich, categorized results instead of ~6 generic "tours".
            active_niche = [t for t in executed if t in NICHE_SPECIALISTS]
            existing = state.tiles.get("activities", [])
            existing_list = existing if isinstance(existing, list) else []

            # Per-category fetch via activity_browser (parallel, L1-cached)
            from app.services.activity_browser import browse_activities as _browse_activities

            geo_center: tuple[float, float] | None = (
                (dest_lat, dest_lng) if dest_lat is not None and dest_lng is not None else None
            )
            browse_date = start_date or None
            all_categories = ["cultural", "food", "nature", "spa", "tours", "shopping"]
            try:
                browse_tiles = await _browse_activities(
                    destination=plan.destination or "",
                    center=geo_center,
                    categories=all_categories,
                    date=browse_date,
                )
            except Exception as _be:
                log("LOGISTICS", f"[BROWSE] Per-category fetch failed: {_be} — fallback to generic")
                browse_tiles = []

            if browse_tiles:
                # activity_browser tiles have a 'category' field; alias to browse_category
                # so BrowseActivitiesSheet category filter works (it checks both fields).
                stash = []
                for t in browse_tiles:
                    td = dict(t)
                    td.setdefault("browse_category", td.get("category", "tours"))
                    stash.append(td)
                state.metadata["browseable_activities"] = stash
                log(
                    "LOGISTICS",
                    f"[BROWSE] Per-category fetch: {len(stash)} tiles across"
                    f" {len(all_categories)} categories",
                    data=f"specialists={active_niche}",
                )
            elif existing_list:
                # Fallback: stash the generic tiles with browse_category annotation
                _PLACES_TYPE_TO_BROWSE_CAT: dict[str, str] = {
                    "tourist_attraction": "tours",
                    "travel_agency": "tours",
                    "amusement_park": "tours",
                    "museum": "cultural",
                    "art_gallery": "cultural",
                    "hindu_temple": "cultural",
                    "temple": "cultural",
                    "church": "cultural",
                    "place_of_worship": "cultural",
                    "park": "nature",
                    "natural_feature": "nature",
                    "national_park": "nature",
                    "campground": "nature",
                    "restaurant": "food",
                    "cafe": "food",
                    "bar": "food",
                    "food": "food",
                    "spa": "spa",
                    "beauty_salon": "spa",
                    "gym": "spa",
                    "shopping_mall": "shopping",
                    "market": "shopping",
                    "store": "shopping",
                    "clothing_store": "shopping",
                }
                annotated = []
                for tile in existing_list:
                    tile_dict = dict(tile) if not isinstance(tile, dict) else tile
                    tags = tile_dict.get("tags", [])
                    browse_cat = next(
                        (
                            _PLACES_TYPE_TO_BROWSE_CAT[t]
                            for t in tags
                            if t in _PLACES_TYPE_TO_BROWSE_CAT
                        ),
                        None,
                    )
                    if browse_cat is None:
                        meta_cat = tile_dict.get("meta", {}).get("category", "")
                        browse_cat = _PLACES_TYPE_TO_BROWSE_CAT.get(meta_cat, "tours")
                    tile_dict["browse_category"] = browse_cat
                    annotated.append(tile_dict)
                state.metadata["browseable_activities"] = annotated
                log(
                    "LOGISTICS",
                    f"[BROWSE] Fallback: stashed {len(annotated)} generic tiles for browse",
                    data=f"specialists={active_niche}",
                )

            state.tiles["activities"] = []
            activity_dicts = []
            log(
                "LOGISTICS",
                f"Suppressing {len(existing_list)} logistics activities — pure Tier 1",
                data=f"specialists={active_niche}",
            )
        else:
            # Mixed — generate Tier 2 experience tiles via LLM
            from app.services.unsplash import prefetch_destination_images

            # Prefetch Unsplash for Tier 2 categories (non-blocking, ~2-3s head start)
            for cat in tier2_cats:
                t = asyncio.create_task(
                    prefetch_destination_images(plan.destination, activities=[cat])
                )
                _track_task(t)

            month = str(plan.start_date)[:7] if plan.start_date else ""
            active_niche = [t for t in executed if t in NICHE_SPECIALISTS]
            tiles_per_cat = _compute_tiles_per_category(state, tier2_cats)
            allow_prefetch_wait = bool(
                state.metadata.get("tier2_prefetch_intent", "activity") == "activity"
            )
            tier2_attempted = True
            experience_tiles = await _resolve_tier2_experience_tiles(
                state=state,
                destination=str(plan.destination),
                month=month,
                categories=tier2_cats,
                tiles_per_category=tiles_per_cat,
                budget=plan.budget,
                tier1_specialists=active_niche,
                fallback_tiles=activity_dicts if isinstance(activity_dicts, list) else [],
                consume_prefetch=lambda: _consume_tier2_prefetch(
                    tier2_cats,
                    tiles_per_cat,
                    str(plan.destination),
                    month,
                ),
                allow_prefetch_wait=allow_prefetch_wait,
            )

            if experience_tiles:
                source = state.metadata.get("tier2_generation_source", "llm")
                log(
                    "LOGISTICS",
                    f"Generated {len(experience_tiles)} Tier 2 experience tiles",
                    data=f"specialists={active_niche}, tier2={tier2_cats}, source={source}",
                )
                state.tiles["activities"] = experience_tiles
                activity_dicts = experience_tiles
                used_tier2_categories = set(tier2_cats)
                # Mark that Tier 2 tiles were generated (for synthesizer gate)
                state.metadata["tier2_tiles_generated"] = True
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
            from app.services.unsplash import prefetch_destination_images

            # Prefetch Unsplash for Tier 2 categories (non-blocking, ~2-3s head start)
            for cat in tier2_only:
                t = asyncio.create_task(
                    prefetch_destination_images(plan.destination, activities=[cat])
                )
                _track_task(t)

            month = str(plan.start_date)[:7] if plan.start_date else ""
            tiles_per_cat = _compute_tiles_per_category(state, tier2_only)
            allow_prefetch_wait = bool(
                state.metadata.get("tier2_prefetch_intent", "activity") == "activity"
            )
            tier2_attempted = True
            experience_tiles = await _resolve_tier2_experience_tiles(
                state=state,
                destination=str(plan.destination),
                month=month,
                categories=tier2_only,
                tiles_per_category=tiles_per_cat,
                budget=plan.budget,
                tier1_specialists=None,
                fallback_tiles=activity_dicts if isinstance(activity_dicts, list) else [],
                consume_prefetch=lambda: _consume_tier2_prefetch(
                    tier2_only,
                    tiles_per_cat,
                    str(plan.destination),
                    month,
                ),
                allow_prefetch_wait=allow_prefetch_wait,
            )
            if experience_tiles:
                source = state.metadata.get("tier2_generation_source", "llm")
                log(
                    "LOGISTICS",
                    f"Pure Tier 2: generated {len(experience_tiles)} experience tiles",
                    data=f"categories={tier2_only}, source={source}",
                )
                state.tiles["activities"] = experience_tiles
                activity_dicts = experience_tiles
                used_tier2_categories = set(tier2_only)
                # Mark that Tier 2 tiles were generated (for synthesizer gate)
                state.metadata["tier2_tiles_generated"] = True

    # Prefetch metadata is single-turn only. Always clear to avoid stale reuse.
    state.metadata.pop("tier2_prefetch_task", None)
    state.metadata.pop("tier2_prefetch_categories", None)
    state.metadata.pop("tier2_prefetch_tiles_per_category", None)
    state.metadata.pop("tier2_prefetch_started_at", None)
    state.metadata.pop("tier2_prefetch_destination", None)
    state.metadata.pop("tier2_prefetch_month", None)
    state.metadata.pop("tier2_prefetch_key", None)
    state.metadata.pop("tier2_prefetch_intent", None)
    _debug_log("[VERIFY][PREFETCH] metadata_cleared")
    if not tier2_attempted:
        state.metadata.pop("tier2_generation_key", None)
        state.metadata.pop("tier2_generation_source", None)
        state.metadata.pop("tier2_generation_elapsed_ms", None)
        state.metadata.pop("tier2_generation_reason", None)

    if tier2_attempted:
        current_activity_ids = _activity_tile_id_set(activity_dicts)
        tier2_source = state.metadata.get("tier2_generation_source")
        tier2_new_content_generated = bool(
            tier2_source != "reuse" and current_activity_ids != previous_activity_ids
        )
        state.metadata["tier2_new_content_generated"] = tier2_new_content_generated
        _debug_log(
            "[VERIFY][TIER2_CONTENT] "
            f"source={tier2_source} "
            f"prev_ids={len(previous_activity_ids)} "
            f"curr_ids={len(current_activity_ids)} "
            f"new_content={tier2_new_content_generated}"
        )
    else:
        state.metadata.pop("tier2_new_content_generated", None)

    log("LOGISTICS", f"Found {len(activity_dicts)} activities for {plan.destination}")
    _debug_log(f"Activities found: {len(activity_dicts)}")

    # Snapshot categories actively represented in the current plan output.
    # Router uses this as category baseline to avoid stale persisted carryover.
    active_categories = set(t for t in executed if t in TIER1_CATEGORIES) | used_tier2_categories
    if active_categories:
        state.metadata["active_plan_categories"] = sorted(active_categories)
        _debug_log(
            f"[VERIFY][CATEGORY_BASELINE] active_plan_categories={sorted(active_categories)}"
        )
        _debug_log(f"[LOGISTICS] active_plan_categories={sorted(active_categories)}")
    else:
        state.metadata.pop("active_plan_categories", None)
        _debug_log("[VERIFY][CATEGORY_BASELINE] active_plan_categories cleared")

    # Update booking summary
    booking_summary = state.metadata.get("booking_summary", {})
    booking_summary["hotels_found"] = len(hotel_dicts)
    booking_summary["activities_found"] = len(activity_dicts)
    state.metadata["booking_summary"] = booking_summary


def _compute_tiles_per_category(state: GraphState, tier2_cats: set[str]) -> int:
    """Scale experience tile count based on placeable days.

    free_days = trip_days - specialist_activity_days - 2 (arrival/departure)
    total_placeable = free_days + specialist_days (co-scheduling capacity)
    tiles_per_category = clamp(base, 2, cap)

    Cap strategy:
    - Mixed Tier1+Tier2 (specialist_days > 0): cap at 4.
    - Pure Tier2 with strategy context and long free-day horizon (>7 days):
      expand cap up to 8 to avoid under-filling long trips.
    - Otherwise: cap at 4.
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
    base = max(2, total_placeable // len(tier2_cats))

    if specialist_days > 0:
        cap = 4
    else:
        strategy_sections = state.metadata.get("strategy_sections", [])
        has_strategy_context = isinstance(strategy_sections, list) and len(strategy_sections) > 0
        if has_strategy_context and free_days > 7:
            cap = min(8, max(4, math.ceil(free_days / len(tier2_cats))))
        else:
            cap = 4

    tiles_per_cat = min(base, cap)
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


def _has_nofly_constraints(state: GraphState) -> bool:
    """Check if any active specialist has a no-fly buffer constraint (registry-driven)."""
    from app.planner.specialist_registry import SPECIALIST_REGISTRY

    nofly_specialists = {name for name, cfg in SPECIALIST_REGISTRY.items() if cfg.has_nofly_buffer}

    # Check active specialist
    if state.active_specialist in nofly_specialists:
        return True

    # Check strategy sections for specialists with no-fly buffer
    for section in state.metadata.get("strategy_sections", []):
        if section.get("specialist_type") in nofly_specialists:
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


def _curated_to_flight_tiles(curated_flights: List[Dict], date_str: str) -> List[Dict]:
    """
    Convert curated flight data to flight tile dict format consumed by the UI.

    Curated flights have: carrier_code, carrier_name, departure_time, duration, price
    Curated values are normalized to the same tile shape as mock and API-derived flights.
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
