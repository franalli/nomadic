"""
Response envelope builder — formats GraphState for frontend consumption.

Orchestrates:
1. Trip inputs merging (TripPlan + settings + extracted_settings)
2. Blocking violation resolution
3. Strategy section building (General, Specialist, Local Expert)
4. Itinerary shadow build (if S2_STRATEGY_READY)
5. Final response envelope assembly

Public API:
- format_result(state, original_session_state) -> Dict[str, Any]

Extracted from plan_graph.py (Stage 7, Phase 2).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from app.placeholders import get_hero_image
from app.planner.services.section_builder import (
    mark_topic_executed,
    sort_sections_anchor_first,
    upsert_section,
)
from app.planner.services.state_serde import (
    state_to_session_state,
    trip_plan_to_trip_inputs,
)
from app.planner.specialist_registry import (
    ALL_DOMAIN_DEFAULT_PRINCIPLES,
    DOMAIN_DEFAULT_FALLBACK,
)
from app.planner.state import GraphState, TripPlan, trip_plan_is_ready
from app.planner.state.typed_meta import get_trip_settings
from app.schemas import StrategySection as StrategySectionModel
from app.utils.tile_utils import flatten_tiles_to_id_map

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Settings fields owned by frontend UI (not in TripPlan)
_USER_SETTINGS_FIELDS = (
    "activity_settings",
    "hotel_settings",
    "flight_settings",
    "transport_settings",
    "booking_types",
)


# =============================================================================
# View State Computation
# =============================================================================


def _compute_plan_view_state(state: GraphState) -> str:
    """
    Compute plan_view_state for frontend stage rendering.

    State machine:
    - S0_BOOTSTRAP: Setup checklist, no specialist content yet.
    - S2_STRATEGY_READY: Strategy preview (specialist content) OR full logistics (tiles).
    - S3_*: Itinerary states (promoted after shadow itinerary build when day cards exist)

    Bridge State: Promotes to S2 when specialist content exists (even without dates/tiles)
    to show Strategy Cards + Sample Day Flow + POI Map immediately.
    """
    # S2: Has tiles → full logistics mode (dates set, real prices)
    if state.tiles and any(state.tiles.values()):
        return "S2_STRATEGY_READY"

    # S2: Has specialist content → strategy preview mode (inspiration, no prices)
    # This enables the "Bridge State" - showing diving/skiing/hiking cards before dates
    sections = state.metadata.get("strategy_sections", [])
    has_specialist_content = any(
        s.get("specialist_type") not in ("general", None) for s in sections
    )
    if has_specialist_content:
        return "S2_STRATEGY_READY"

    # S0: No tiles or specialist content → blank slate / setup checklist
    return "S0_BOOTSTRAP"


def _flatten_tiles_to_id_map(tiles_by_category: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Convert category-based tiles to ID-based map for frontend.

    Backend stores: {"flights": [tile1, tile2], "hotels": [tile3]}
    Frontend expects: {"tile1_id": tile1, "tile2_id": tile2, "tile3_id": tile3}

    Delegates core flattening to ``flatten_tiles_to_id_map`` (shared utility)
    and enriches each tile with a pre-formatted ``price_display`` field that
    the frontend renders directly.
    """
    result = flatten_tiles_to_id_map(tiles_by_category)

    # Enrich with price_display for frontend rendering
    for tile in result.values():
        tile["price_display"] = (
            f"${tile.get('price_estimate', 0):.0f}" if tile.get("price_estimate") else None
        )

    return result


# =============================================================================
# Trip Inputs Building
# =============================================================================


def _build_trip_inputs_with_settings(state: GraphState) -> Dict[str, Any]:
    """Convert TripPlan to trip_inputs and merge user/extracted settings."""
    trip_inputs = trip_plan_to_trip_inputs(state.trip_plan)

    # Read typed settings (SSoT) and serialize sub-models into trip_inputs output.
    # Must go BEFORE extracted_settings merge so NL commands override UI selections.
    settings = get_trip_settings(state)
    for field in _USER_SETTINGS_FIELDS:
        val = getattr(settings, field, None)
        if val is not None:
            trip_inputs[field] = val.model_dump() if hasattr(val, "model_dump") else val

    # FIX: Preserve in-turn category writes from router's sync block.
    # The router writes detected specialists to metadata["trip_inputs"]["activity_settings"]
    # but typed settings (trip_settings) may carry stale values from graph startup.
    meta_activity = state.metadata.get("trip_inputs", {}).get("activity_settings", {})
    if isinstance(meta_activity, dict) and meta_activity.get("categories"):
        trip_inputs["activity_settings"] = meta_activity

    # Merge extracted settings into trip_inputs (from NL command parsing)
    extracted_settings = state.metadata.get("extracted_settings", {})
    if extracted_settings:
        # Merge booking_types
        booking_types = trip_inputs.get("booking_types", {})
        if extracted_settings.get("flights_toggle"):
            booking_types["flights"] = extracted_settings["flights_toggle"]
        if extracted_settings.get("hotels_toggle"):
            booking_types["hotels"] = extracted_settings["hotels_toggle"]
        if extracted_settings.get("activities_toggle"):
            booking_types["activities"] = extracted_settings["activities_toggle"]
        if extracted_settings.get("ground_transport_toggle"):
            booking_types["ground_transport"] = extracted_settings["ground_transport_toggle"]
        if booking_types:
            trip_inputs["booking_types"] = booking_types

        # Merge flight_settings
        flight_settings = trip_inputs.get("flight_settings", {})
        if extracted_settings.get("flight_direct_only") is not None:
            flight_settings["direct_only"] = extracted_settings["flight_direct_only"]
        if extracted_settings.get("flight_cabin_class"):
            flight_settings["cabin_class"] = extracted_settings["flight_cabin_class"]
        if extracted_settings.get("flight_round_trip") is not None:
            flight_settings["round_trip"] = extracted_settings["flight_round_trip"]
        if flight_settings:
            trip_inputs["flight_settings"] = flight_settings

        # Merge hotel_settings
        hotel_settings = trip_inputs.get("hotel_settings", {})
        if extracted_settings.get("hotel_min_stars") is not None:
            hotel_settings["min_stars"] = extracted_settings["hotel_min_stars"]
        if hotel_settings:
            trip_inputs["hotel_settings"] = hotel_settings

        # Merge activity_settings
        activity_settings = trip_inputs.get("activity_settings", {})
        if extracted_settings.get("activity_skill_level"):
            activity_settings["skill_level"] = extracted_settings["activity_skill_level"]
        if activity_settings:
            trip_inputs["activity_settings"] = activity_settings

        logger.info(
            f"Merged extracted settings into trip_inputs: {list(extracted_settings.keys())}"
        )

    return trip_inputs


# =============================================================================
# Violation Resolution
# =============================================================================


def _resolve_blocking_violations(
    state: GraphState,
) -> tuple:
    """Handle blocking violations: compute tiles, view state, and whether route error occurred.

    Returns:
        (flattened_tiles, plan_view_state, has_blocking_violations, is_route_error)
    """
    has_blocking_violations = state.metadata.get("has_blocking_violations", False)
    if has_blocking_violations:
        violations = state.metadata.get("constraint_violations", [])
        is_route_error = any(v.get("category") == "route" for v in violations)

        if is_route_error:
            # Route errors are catastrophic - user gave invalid destination
            # Wipe state and return to S0_BOOTSTRAP
            logger.warning("[format_result] Route error - clearing tiles/sections")
            flattened_tiles: Dict[str, Any] = {}
            plan_view_state = "S0_BOOTSTRAP"
            state.metadata["strategy_sections"] = []
            state.metadata["executed_strategy_topics"] = []
            state.tiles = {}
        else:
            # Specialist violations (diving buffer, altitude, etc.) - preserve state
            # User can still see their plan, Synthesizer explains the constraint
            logger.info("[format_result] Specialist violation - preserving tiles/sections")
            flattened_tiles = _flatten_tiles_to_id_map(state.tiles)
            plan_view_state = _compute_plan_view_state(state)
    else:
        # Normal path - flatten tiles for frontend
        flattened_tiles = _flatten_tiles_to_id_map(state.tiles)
        plan_view_state = _compute_plan_view_state(state)
        is_route_error = False

    # Persist for next turn so intent_router can detect active plan
    state.metadata["plan_view_state"] = plan_view_state

    logger.info(
        f"format_result: plan_view_state={plan_view_state}, "
        f"flattened_tiles_count={len(flattened_tiles)}, "
        f"raw_tiles_count={sum(len(v) for v in state.tiles.values()) if state.tiles else 0}"
    )

    return flattened_tiles, plan_view_state, has_blocking_violations, is_route_error


# =============================================================================
# Section Building Helpers
# =============================================================================


def _count_tiles_by_type(flattened_tiles: Dict[str, Any]) -> tuple:
    """Count tiles by category for principles generation.

    Returns:
        (hotels_count, flights_count, activities_count)
    """
    hotels_count = len(
        [t for t in flattened_tiles.values() if t.get("type") in ("hotel", "stay", "accommodation")]
    )
    flights_count = len([t for t in flattened_tiles.values() if t.get("type") == "flight"])
    activities_count = len(
        [
            t
            for t in flattened_tiles.values()
            if t.get("type") in ("activity", "experience", "tour", "attraction")
        ]
    )
    return hotels_count, flights_count, activities_count


def _build_trip_summary(plan: "TripPlan") -> Dict[str, Any]:
    """Build trip_summary dict for General Agent section."""
    travelers_count = (plan.adults or 1) + (plan.children or 0)
    return {
        "destination": plan.destination or "Unknown",
        "dates": (
            f"{plan.start_date} – {plan.end_date}"
            if plan.start_date and plan.end_date
            else plan.start_date or "TBD"
        ),
        "travelers": f"{travelers_count} traveler{'s' if travelers_count > 1 else ''}",
    }


def _extract_section_content(
    state: GraphState,
    specialist_type: str,
    strategy_sections: list,
) -> tuple:
    """Extract constraints, content_added, and must_dos for a new section.

    Returns:
        (constraints_applied, content_added, must_dos)
    """
    plan = state.trip_plan

    # Extract constraints applied from TripPlan
    constraints_applied = []
    for c in plan.constraints:
        constraints_applied.append(
            {
                "rule": c.rule,
                "type": c.type,
                "severity": getattr(c, "severity", "strong"),
                "reason": c.reason or "",
            }
        )

    # Extract content added from itinerary_blocks (PRESERVE RICH DATA)
    content_added = []
    for block in plan.itinerary_blocks:
        content_added.append(
            {
                "title": block.title,
                "day": block.day,
                "type": block.type,
                "description": block.description,  # Rich description for UI
                "logic_hook": getattr(block, "logic_hook", None),  # Pro tip for UI
                "image_url": getattr(block, "image_url", None),  # Curated image
                "coordinates": getattr(block, "coordinates", None),  # [lng, lat] for Mapbox
            }
        )

    # Merge image_url and coordinates from specialist sections (rich curated content)
    # This ensures images and map POIs are preserved even when rebuilding content_added
    for section in strategy_sections:
        if section.get("specialist_type") == specialist_type:
            existing_content = section.get("content_added", [])
            for item in existing_content:
                for ca in content_added:
                    if ca.get("title") == item.get("title"):
                        if item.get("image_url") and not ca.get("image_url"):
                            ca["image_url"] = item.get("image_url")
                        if item.get("coordinates") and not ca.get("coordinates"):
                            ca["coordinates"] = item.get("coordinates")

    # Build must_dos from itinerary_blocks (actual specialist recommendations)
    must_dos = []
    for block in plan.itinerary_blocks:
        if block.title and block.title not in must_dos:
            must_dos.append(block.title)
    must_dos = must_dos[:5]  # Limit to 5

    return constraints_applied, content_added, must_dos


def _build_one_liner(state: GraphState, specialist_type: str) -> str:
    """Build one-liner based on specialist type.

    General: Editorial "magazine" style, evocative.
    Specialist: Technical, domain-focused.
    """
    plan = state.trip_plan
    if specialist_type == "general":
        editorial_summary = state.metadata.get("editorial_summary")
        if editorial_summary:
            return editorial_summary
        if plan.origin and plan.destination:
            return f"A journey from {plan.origin} to {plan.destination} awaits"
        elif plan.destination:
            return f"Your adventure to {plan.destination} is taking shape"
        else:
            return "Your personalized trip is ready to customize"
    elif specialist_type == "local_expert":
        return f"Local logistics and tips for {plan.destination or 'your destination'}"
    else:
        return (
            f"{specialist_type.title()} recommendations for "
            f"{plan.destination or 'your destination'}"
        )


def _build_principles(
    state: GraphState,
    specialist_type: str,
    hotels_count: int,
    flights_count: int,
    activities_count: int,
) -> list:
    """Build principles based on specialist type.

    General: Trip highlights (destinations, flights, hotels).
    Niche: Domain-specific strategy principles from constraints/content.
    """
    plan = state.trip_plan
    principles: list = []

    if specialist_type == "general":
        if plan.origin and plan.destination:
            principles.append(f"{plan.origin} → {plan.destination} adventure")
        elif plan.destination:
            principles.append(f"Exploring {plan.destination}")
        if flights_count:
            principles.append(f"{flights_count} flight options to compare")
        if hotels_count:
            principles.append(f"{hotels_count} accommodation choices")
        if activities_count:
            principles.append(f"{activities_count} activities to discover")
        if plan.start_date and plan.end_date:
            try:
                start = datetime.fromisoformat(plan.start_date)
                end = datetime.fromisoformat(plan.end_date)
                days = (end - start).days + 1
                principles.append(f"{days}-day itinerary")
            except (ValueError, TypeError):
                pass
        if not principles:
            principles.append("Your personalized trip is taking shape")
    elif specialist_type not in ("general", "local_expert"):
        # NICHE SPECIALIST: Build principles from constraints + specialist output
        specialist_output = state.metadata.get("specialist_output", {})
        llm_principles = specialist_output.get("principles", [])
        if llm_principles:
            principles.extend(llm_principles[:5])

        if not principles and plan.constraints:
            for c in plan.constraints[:4]:
                if c.reason:
                    principles.append(c.reason)
                else:
                    rule_text = c.rule.replace("_", " ").title()
                    principles.append(f"{rule_text} applied")

        if not principles:
            principles = ALL_DOMAIN_DEFAULT_PRINCIPLES.get(
                specialist_type,
                [
                    p.format(specialist_type=specialist_type.title())
                    for p in DOMAIN_DEFAULT_FALLBACK
                ],
            )

    return principles


def _build_vibe_trio(state: GraphState, specialist_type: str) -> list:
    """Build vibe_trio for General and Local Expert (destination images).

    Returns empty list for niche specialists.
    """
    if specialist_type not in ("general", "local_expert"):
        return []

    plan = state.trip_plan
    # 1. Try to get vibes from Architect metadata (LLM-generated)
    extracted_vibes = state.metadata.get("trip_vibes", [])

    # 2. If no LLM-generated vibes, create fallback vibes based on destination
    if not extracted_vibes:
        if plan.destination:
            destination_slug = plan.destination.lower().replace(" ", ",")
            extracted_vibes = [
                {"label": "City Highlights", "query": f"{destination_slug} landmark"},
                {"label": "Local Culture", "query": f"{destination_slug} culture"},
                {"label": "Hidden Gems", "query": f"{destination_slug} street scene"},
            ]
        else:
            extracted_vibes = [
                {"label": "Inspiration", "query": "travel inspiration"},
                {"label": "Adventure", "query": "adventure travel"},
                {"label": "Relaxation", "query": "luxury resort"},
            ]

    # 3. Build vibe_trio with curated images (max 3)
    vibe_trio = []
    for idx, vibe in enumerate(extracted_vibes[:3]):
        label = vibe.get("label", "Vibe")
        category = (
            "culture"
            if "culture" in label.lower()
            else "adventure"
            if "adventure" in label.lower()
            else "destination"
        )
        vibe_trio.append(
            {
                "label": label,
                "image_url": vibe.get("image_url")
                or get_hero_image(category, f"{plan.destination}-{label}-{idx}"),
            }
        )

    return vibe_trio


def _build_hero_image(
    specialist_type: str,
    content_added: list,
    destination: Optional[str],
) -> Optional[str]:
    """Build hero_image for Niche Specialists (single focused action shot).

    Returns None for general/local_expert.
    """
    if specialist_type in ("general", "local_expert"):
        return None

    for item in content_added:
        if item.get("image_url"):
            return item["image_url"]

    return get_hero_image(specialist_type, destination)


# =============================================================================
# Main Section Builder
# =============================================================================


def _build_new_section(
    state: GraphState,
    specialist_type: str,
    flattened_tiles: Dict[str, Any],
    strategy_sections: list,
) -> Optional[Dict[str, Any]]:
    """Build a new strategy section for the active specialist, if needed.

    Returns None if no section is needed (specialist already has one, or no tiles).
    """
    # Check if we need to create a section
    existing_types = [s.get("specialist_type") for s in strategy_sections]
    specialist_already_has_section = specialist_type in existing_types
    last_specialist = state.metadata.get("last_executed_specialist")

    needs_section = (
        flattened_tiles
        and not specialist_already_has_section
        and not (
            specialist_type == "general" and last_specialist
        )  # Don't create general if specialist ran
    )

    from app.debug_utils import _debug_log

    _debug_log(
        f"format_result: needs_section={needs_section} (flattened_tiles={bool(flattened_tiles)})"
    )

    if not needs_section:
        return None

    plan = state.trip_plan

    # Build all sub-components
    hotels_count, flights_count, activities_count = _count_tiles_by_type(flattened_tiles)
    trip_summary = _build_trip_summary(plan)
    constraints_applied, content_added, must_dos = _extract_section_content(
        state, specialist_type, strategy_sections
    )
    one_liner = _build_one_liner(state, specialist_type)
    principles = _build_principles(
        state, specialist_type, hotels_count, flights_count, activities_count
    )
    vibe_trio = _build_vibe_trio(state, specialist_type)
    hero_image = _build_hero_image(specialist_type, content_added, plan.destination)

    # Assemble the section dict
    return {
        "id": f"strategy_{specialist_type}",
        "title": (
            f"{specialist_type.title()} Strategy"
            if specialist_type != "general"
            else "Trip Overview"
        ),
        "subtitle": plan.destination,
        "specialist_type": specialist_type,
        "one_liner": one_liner,
        # Magazine-style fields for General and Local Expert
        "editorial_one_liner": (
            one_liner if specialist_type in ("general", "local_expert") else None
        ),
        "vibe_trio": vibe_trio if specialist_type in ("general", "local_expert") else None,
        # Niche specialist hero image (single focused action shot)
        "hero_image": hero_image,
        "bullets": [],  # No longer show generic trip params
        "principles": principles,
        "must_dos": must_dos,  # Actual specialist recommendations
        "optional_upgrades": [],
        "logistics_notes": [],
        "booking_artifacts": {
            "hotels_count": hotels_count,
            "flights_count": flights_count,
            "activities_count": activities_count,
        },
        "impact_areas": (
            ["Accommodations", "Transportation", "Activities"] if flattened_tiles else []
        ),
        # Technical log data for System Log display
        "trip_summary": trip_summary if specialist_type == "general" else None,
        "constraints_applied": constraints_applied,
        "content_added": content_added,
        "content_blocks": content_added,
        # Feasibility state from specialist output (for Red/Amber/Green card states)
        "feasibility_status": state.metadata.get("specialist_output", {}).get(
            "feasibility_status", "feasible"
        ),
        "feasibility_reason": state.metadata.get("specialist_output", {}).get("feasibility_reason"),
        "alternative_suggestion": state.metadata.get("specialist_output", {}).get(
            "alternative_suggestion"
        ),
    }


# =============================================================================
# Section Persistence
# =============================================================================


def _upsert_section_and_persist(
    state: GraphState,
    strategy_sections: list,
    new_section: Optional[Dict[str, Any]],
    specialist_type: str,
    executed_topics: list,
    has_blocking_violations: bool,
    is_route_error: bool,
) -> tuple:
    """Apply SINGLETON/APPENDABLE upsert, persist to state.metadata, enforce anchor rule.

    Returns:
        (final_strategy_sections, final_executed_topics)
    """
    from app.debug_utils import _debug_log

    # CRITICAL: Write accumulated sections back to state.metadata for persistence
    # Only skip persistence for ROUTE errors (catastrophic), preserve for specialist violations
    if has_blocking_violations and is_route_error:
        strategy_sections = []
        executed_topics = []
    else:
        # Seed metadata with enriched sections before service calls
        state.metadata["strategy_sections"] = list(strategy_sections)
        state.metadata["executed_strategy_topics"] = list(executed_topics)

        if new_section is not None:
            # SINGLETON (general) vs APPENDABLE (specialists) — handled by service
            mode = "singleton" if specialist_type == "general" else "appendable"
            upsert_section(state.metadata, new_section, mode=mode)
            mark_topic_executed(state.metadata, specialist_type)
        else:
            # Still apply anchor sort even without new section
            state.metadata["strategy_sections"] = sort_sections_anchor_first(
                state.metadata["strategy_sections"]
            )

        strategy_sections = state.metadata["strategy_sections"]
        executed_topics = state.metadata["executed_strategy_topics"]

    # DEBUG: Log what strategy_sections we're saving for next turn
    final_sections = state.metadata["strategy_sections"]
    saved_types = [s.get("specialist_type") for s in final_sections]
    _debug_log(
        f"format_result: Saving {len(final_sections)} "
        f"strategy_sections to session_state, types={saved_types}"
    )
    if saved_types and saved_types[0] not in ("local_expert", "general"):
        _debug_log(
            f"⚠️ WARNING: Anchor rule violation! First section is '{saved_types[0]}', "
            f"expected 'local_expert' or 'general'"
        )

    return strategy_sections, executed_topics


# =============================================================================
# Response Envelope
# =============================================================================


def _build_response_envelope(
    state: GraphState,
    trip_inputs: Dict[str, Any],
    flattened_tiles: Dict[str, Any],
    plan_view_state: str,
    strategy_sections: list,
    executed_topics: list,
    itinerary_day_cards: Optional[list] = None,
) -> Dict[str, Any]:
    """Build the final response dict (document + session_state + legacy fields)."""
    # Shadow-validate strategy sections against Pydantic model (log only)
    for section_dict in strategy_sections:
        try:
            StrategySectionModel(**section_dict)
        except Exception as e:
            logger.warning(f"StrategySection validation: {section_dict.get('id')}: {e}")

    # CRITICAL: Capture session_state AFTER metadata is updated (not before!)
    updated_session_state = state_to_session_state(state)

    # Build document object matching PlanDocumentData type expected by frontend
    document = {
        "trip_context_id": None,
        "trip_inputs": trip_inputs,
        "branches": [],  # Not used
        "tiles": flattened_tiles,  # Flattened to ID-based map for frontend
        "assistant_message": state.last_summary or "",
        "ready_to_generate": trip_plan_is_ready(state.trip_plan),
        "suggested_responses": (
            state.suggested_replies
            or state.metadata.get("synthesizer_output", {}).get("suggested_replies", [])
        ),
        "suggested_response_meta": state.metadata.get("suggestion_chip_meta", []),
        "suggestion_chips": state.metadata.get("suggestion_chips", []),
        # Plan view state for right panel stage rendering
        "plan_view_state": plan_view_state,
        # Strategy content for AgentCards
        "strategy_sections": strategy_sections,
        "pending_strategy_topics": state.metadata.get("pending_strategy_topics", []),
        "executed_strategy_topics": executed_topics,
        # Origin update flag for frontend to trigger flight fetch
        "origin_just_set": state.metadata.get("origin_just_set", False),
        # Tile replace signal — frontend should REPLACE tiles, not merge additively
        "tiles_replaced": bool(state.metadata.get("_tiles_replaced", False)),
        # Constraint validation receipts for Trip DNA bar badges
        "constraints_validated": state.metadata.get("constraints_validated", []),
        "constraint_violations": state.metadata.get("constraint_violations", []),
        # Itinerary day cards (computed by ItineraryBuilder, None until S2_STRATEGY_READY)
        "itinerary_day_cards": itinerary_day_cards,
        # Backend-only observability fields -- not consumed by frontend
        "_debug": {
            "router_extraction_failed": state.metadata.get("router_extraction_failed", False),
        },
    }

    # DEBUG: Log origin_just_set for troubleshooting
    if state.metadata.get("origin_just_set"):
        logger.info(f"[format_result] origin_just_set=True, origin={trip_inputs.get('origin')}")

    return {
        # PlanDocumentResponse fields
        "version": 1,
        "updated_by": "ai",
        "updated_at": datetime.now().isoformat(),
        "document": document,  # Document wrapper for frontend
        # GraphPlanResponse fields
        "session_state": updated_session_state,
        "request_id": state.metadata.get("request_id", ""),
        "changes_made": True,
        # Legacy fields for backward compatibility
        "assistant_message": state.last_summary or "",
        "suggested_responses": (
            state.suggested_replies
            or state.metadata.get("synthesizer_output", {}).get("suggested_replies", [])
        ),
        "branches": [],
        "trip_inputs": trip_inputs,
        "ready_to_generate": trip_plan_is_ready(state.trip_plan),
        "errors": state.constraints_violated,
    }


# =============================================================================
# Public API: Orchestrator
# =============================================================================


def format_result(
    state: GraphState,
    _original_session_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Format result state for main.py response."""
    from app.debug_utils import _debug_log

    # 1. Build trip_inputs with settings merged
    trip_inputs = _build_trip_inputs_with_settings(state)

    # 2. Resolve blocking violations → tiles, view state
    flattened_tiles, plan_view_state, has_blocking, is_route_error = _resolve_blocking_violations(
        state
    )

    # 3. Determine specialist context
    strategy_sections = state.metadata.get("strategy_sections", [])
    executed_topics = state.metadata.get("executed_strategy_topics", [])
    last_specialist = state.metadata.get("last_executed_specialist")
    specialist_type = state.active_specialist or last_specialist or "general"

    # DEBUG: Log existing sections
    section_types = [s.get("specialist_type") for s in strategy_sections]
    _debug_log(f"format_result: BEFORE - {len(strategy_sections)} sections, types={section_types}")
    for s in strategy_sections:
        content_count = len(s.get("content_added", []))
        constraint_count = len(s.get("constraints_applied", []))
        _debug_log(
            f"  Section '{s.get('specialist_type')}': "
            f"content_added={content_count}, constraints={constraint_count}"
        )
    _debug_log(
        f"format_result: active_specialist={state.active_specialist}, "
        f"last_specialist={last_specialist}, specialist_type={specialist_type}"
    )

    # 4. (Deleted Stage 2B.4: sections now created complete by section_builder)

    # 5. Build new section if needed
    new_section = _build_new_section(state, specialist_type, flattened_tiles, strategy_sections)

    # 6. Upsert + persist
    strategy_sections, executed_topics = _upsert_section_and_persist(
        state,
        strategy_sections,
        new_section,
        specialist_type,
        executed_topics,
        has_blocking,
        is_route_error,
    )

    # 6.5 (Shadow): Build itinerary if strategy ready
    # Stores last_builder_success in metadata so the constraint guard on the NEXT
    # turn can decide whether to suppress cross-domain violations. If the builder
    # failed (trip too short), the guard re-surfaces the violation for the synthesizer.
    itinerary_day_cards = None
    itinerary_cache_key = (
        f"{state.trip_plan.destination or ''}|"
        f"{state.trip_plan.start_date or ''}|"
        f"{state.trip_plan.end_date or ''}"
    )
    if plan_view_state == "S2_STRATEGY_READY" and not has_blocking:
        short_circuit_type = state.metadata.get("short_circuit_type")
        can_reuse_cached_itinerary = short_circuit_type in {"question_answer", "exploration"}
        cached_day_cards = state.metadata.get("last_itinerary_day_cards")
        cached_view_state = state.metadata.get("last_itinerary_view_state")
        cached_key = state.metadata.get("last_itinerary_cache_key")

        if (
            can_reuse_cached_itinerary
            and isinstance(cached_day_cards, list)
            and cached_day_cards
            and cached_key == itinerary_cache_key
        ):
            itinerary_day_cards = cached_day_cards
            if isinstance(cached_view_state, str) and cached_view_state.startswith("S3"):
                plan_view_state = cached_view_state
                state.metadata["plan_view_state"] = plan_view_state
            state.metadata["last_builder_success"] = True
            _debug_log(
                "[format_result] Reused cached itinerary_day_cards "
                f"(short_circuit_type={short_circuit_type}, cards={len(cached_day_cards)})"
            )
        else:
            try:
                from app.planner.services.itinerary_adapter import build_itinerary_from_state

                # Re-inject user-pinned tiles into tile pool so builder can place them.
                # Must happen AFTER logistics suppression — pinned tiles are user intent.
                pinned_tiles = state.metadata.get("user_pinned_tiles", {})
                if pinned_tiles:
                    # Filter against active categories before re-injection
                    active_cats = set(
                        c.lower()
                        for c in (get_trip_settings(state).activity_settings.categories or [])
                    )
                    existing_ids: set = set()
                    for cat_tiles in state.tiles.values():
                        if isinstance(cat_tiles, list):
                            for t in cat_tiles:
                                if isinstance(t, dict):
                                    existing_ids.add(t.get("id"))
                    for tid, pinned in pinned_tiles.items():
                        if tid not in existing_ids:
                            tile_data = pinned.get("tile", pinned)
                            tile_cat = (
                                (tile_data.get("meta") or {}).get("category", "") or ""
                            ).lower()
                            # Skip tiles from removed categories
                            if active_cats and tile_cat and tile_cat not in active_cats:
                                continue
                            cat = pinned.get("category", "activities")
                            state.tiles.setdefault(cat, []).append(tile_data)

                result = build_itinerary_from_state(state)
                if result and result.success:
                    itinerary_day_cards = [dc.model_dump() for dc in result.day_cards]
                    # Keep graph completion state consistent with emitted payload.
                    plan_view_state = "S3_EDITING" if result.conflicts else "S3_ITINERARY_READY"
                    state.metadata["plan_view_state"] = plan_view_state
                    state.metadata["last_builder_success"] = True
                    state.metadata["last_itinerary_day_cards"] = itinerary_day_cards
                    state.metadata["last_itinerary_view_state"] = plan_view_state
                    state.metadata["last_itinerary_cache_key"] = itinerary_cache_key
                    # Track drop ratio for guard suppression accuracy
                    if result.total_activities_input > 0:
                        state.metadata["last_builder_drop_ratio"] = 1.0 - (
                            result.total_activities_placed / result.total_activities_input
                        )
                    else:
                        state.metadata["last_builder_drop_ratio"] = 0.0
                    # Persist counts for synthesizer drop reporting
                    state.metadata["builder_activities_input"] = result.total_activities_input
                    state.metadata["builder_activities_placed"] = result.total_activities_placed
                    # Surface post-placement conflicts for synthesizer
                    if result.conflicts:
                        state.metadata["builder_conflicts"] = [
                            {
                                "day": c.day if hasattr(c, "day") else None,
                                "type": c.type,
                                "severity": (
                                    c.severity.value
                                    if hasattr(c.severity, "value")
                                    else str(c.severity)
                                ),
                                "message": c.message,
                            }
                            for c in result.conflicts
                        ]
                        state.metadata["constraint_violations"] = [
                            {
                                "code": c.type.upper(),
                                "message": c.message,
                                "severity": (
                                    c.severity.value
                                    if hasattr(c.severity, "value")
                                    else str(c.severity)
                                ),
                                "category": "itinerary",
                                "rule": c.type,
                            }
                            for c in result.conflicts
                        ]
                else:
                    state.metadata["last_builder_success"] = False
                    state.metadata["last_builder_drop_ratio"] = 1.0
                    if result and result.conflicts and result.day_cards:
                        itinerary_day_cards = [dc.model_dump() for dc in result.day_cards]
                        plan_view_state = "S3_PARTIAL_CONFLICT"
                        state.metadata["plan_view_state"] = plan_view_state
                        state.metadata["last_itinerary_day_cards"] = itinerary_day_cards
                        state.metadata["last_itinerary_view_state"] = plan_view_state
                        state.metadata["last_itinerary_cache_key"] = itinerary_cache_key
                    if result and result.resolutions:
                        state.metadata["last_builder_resolutions"] = [
                            r.model_dump() for r in result.resolutions
                        ]
            except Exception as e:
                logger.warning(f"[format_result] Itinerary build failed (shadow): {e}")
                state.metadata["last_builder_success"] = False
    elif has_blocking:
        # Shadow build skipped due to blocking violations — builder can't enforce
        state.metadata["last_builder_success"] = False

    # 7. Build response envelope
    return _build_response_envelope(
        state,
        trip_inputs,
        flattened_tiles,
        plan_view_state,
        strategy_sections,
        executed_topics,
        itinerary_day_cards,
    )
