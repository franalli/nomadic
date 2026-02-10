"""
Plan Graph - 7-Node "Core + Specialist" Architecture.

Nodes:
1. IntentRouter - LLM (Fast): Classify intent → route to appropriate node
2. TripArchitect - LLM (Smart): The Core, manages TripPlan and tools
3. VerticalSpecialist - LLM (Expert): Domain logic (diving/hiking/skiing)
4. LocalExpert - LLM (Expert): Cultural & local knowledge
5. LogisticsNode - Python: Data fetching (flights/hotels via TileService)
6. ConstraintGuard - Python: Deterministic validation (safety buffers, conflicts)
7. Synthesizer - LLM (Writer): Unified response generation

Key Principles:
- "Flights/Hotels are NOT Agents" - They are data fetchers (LogisticsNode)
- "Diving IS an Agent" - It requires domain logic (VerticalSpecialist)
- "Architect sees the whole picture" - Avoids context fracture
- "One Voice" - Synthesizer ensures consistent tone

Usage:
    from app.plan_graph import run_turn_streaming
    async for event in run_turn_streaming(user_message, session_state):
        ...
"""

import asyncio
import hashlib
import logging
import os
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, Literal, Optional

from langgraph.graph import END, StateGraph

from app.placeholders import get_hero_image
from app.planner.nodes.constraint_guard import constraint_guard
from app.planner.nodes.intent_router import intent_router
from app.planner.nodes.local_expert import local_expert
from app.planner.nodes.logistics_node import logistics_node
from app.planner.nodes.synthesizer import synthesizer
from app.planner.nodes.trip_architect import trip_architect
from app.planner.nodes.vertical_specialist import vertical_specialist
from app.planner.services.section_builder import (
    mark_topic_executed,
    sort_sections_anchor_first,
    upsert_section,
)
from app.planner.specialist_registry import ALL_DOMAIN_DEFAULT_PRINCIPLES, DOMAIN_DEFAULT_FALLBACK
from app.planner.state import GraphState, TripPlan, TripSettings, reset_turn_metadata
from app.planner.state.typed_meta import get_persistent_meta, get_trip_settings, get_turn_meta
from app.schemas import (
    ActivitySettings,
    BookingTypes,
    FlightSettings,
    HotelSettings,
    TransportSettings,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Domain Default Principles (for strategy sections)
# Used by _format_result() for both enrichment and new section paths
# =============================================================================


# =============================================================================
# Panic Button - Non-LLM Kill Switch
# =============================================================================

PANIC_COMMANDS = frozenset({"/reset", "reset", "stop", "clear", "/stop", "/clear"})


def _is_panic_command(text: str) -> bool:
    """Check if user input is a panic command (hard-coded, no LLM)."""
    return text.strip().lower() in PANIC_COMMANDS


def _create_reset_response() -> Dict[str, Any]:
    """Create a reset response without running the graph."""
    return {
        "assistant_message": (
            "No problem! Let's start fresh. What kind of trip are you thinking about?"
        ),
        "suggested_responses": ["Relaxing vacation", "Adventure trip", "Cultural exploration"],
        "session_state": {},  # Clear state
        "branches": [],
        "trip_inputs": {},
        "ready_to_generate": False,
        "ui_events": ["UI_RESET"],
    }


# =============================================================================
# Graph Configuration
# =============================================================================

DEBUG = bool(os.getenv("DEBUG_PLAN_MESSAGES"))

# Build identifiers for cache compatibility
PLANNER_BUILD_ID = "1.0.0"
CACHE_SCHEMA_VERSION = "1"

# Graph execution timeout (seconds) - prevents infinite spinners on node hangs
GRAPH_TIMEOUT_SECONDS = 45


# =============================================================================
# Node Status Configuration (for granular streaming events)
# =============================================================================

NODE_STATUS_CONFIG = {
    # Main nodes
    "router": {
        "label": "Reading your message...",
        "icon_key": "brain",
        "estimated_duration_ms": 300,
    },
    "architect": {
        "label": "Understanding your request...",
        "icon_key": "building",
        "estimated_duration_ms": 800,
    },
    "specialist": {
        "label": "Consulting expert...",
        "icon_key": "star",
        "estimated_duration_ms": 1000,
    },
    "local_expert": {
        "label": "Loading local knowledge...",
        "icon_key": "building",
        "estimated_duration_ms": 50,
    },
    "logistics": {
        "label": "Fetching flight options...",
        "icon_key": "plane",
        "estimated_duration_ms": 2000,
    },
    "guard": {
        "label": "Checking constraints...",
        "icon_key": "shield",
        "estimated_duration_ms": 100,
    },
    "synthesizer": {
        "label": "Writing response...",
        "icon_key": "pen",
        "estimated_duration_ms": 1500,
    },
    # Sub-node statuses (for granular updates within nodes)
    "architect_extracting": {
        "label": "Parsing dates and details...",
        "icon_key": "calendar",
        "estimated_duration_ms": 400,
    },
    "architect_planning": {
        "label": "Planning your trip...",
        "icon_key": "map",
        "estimated_duration_ms": 1500,
    },
    "tiles_loading": {
        "label": "Searching live options...",
        "icon_key": "search",
        "estimated_duration_ms": 2000,
    },
}


def _get_node_label(node_name: str) -> str:
    """Get human-readable label for a node."""
    config = NODE_STATUS_CONFIG.get(node_name, {})
    return config.get("label", node_name.replace("_", " ").title())


def _get_node_icon(node_name: str) -> str:
    """Get icon key for a node."""
    config = NODE_STATUS_CONFIG.get(node_name, {})
    return config.get("icon_key", "cog")


def _get_node_duration(node_name: str) -> int:
    """Get estimated duration in ms for a node."""
    config = NODE_STATUS_CONFIG.get(node_name, {})
    return config.get("estimated_duration_ms", 1000)


PROMPT_BUNDLE_HASH = "optimized"


# =============================================================================
# Input Types
# =============================================================================


def _trip_plan_to_trip_inputs(plan: TripPlan) -> Dict[str, Any]:
    """Convert TripPlan to trip_inputs dict for frontend document envelope."""
    return {
        "destination": plan.destination,
        "origin": plan.origin,
        "origin_iata": plan.origin_iata,
        "destination_iata": plan.destination_iata,
        "start_date": plan.start_date,
        "end_date": plan.end_date,
        "adults": plan.adults,
        "children": plan.children,
        "budget": plan.budget,
        "currency": plan.currency,
        # NOTE: Settings fields (booking_types, flight_settings, etc.) intentionally
        # OMITTED — they live on the document (set via PATCH from frontend sheets).
    }


def _field_hash(value: str) -> str:
    """Stable hash for selective regeneration change detection."""
    return hashlib.sha256((value or "").encode()).hexdigest()[:12]


def _compute_field_hashes(trip_plan: TripPlan) -> Dict[str, str]:
    """
    Compute field hashes for selective regeneration strategy.

    These hashes allow the expand-itinerary endpoint to detect which
    fields changed and compute the minimum regeneration strategy.

    @see docs/plan_graph_analysis.md - Selective Regeneration
    """
    return {
        "destination": _field_hash(trip_plan.destination or ""),
        "dates": _field_hash(f"{trip_plan.start_date or ''}|{trip_plan.end_date or ''}"),
        "travelers": _field_hash(f"{trip_plan.adults or 1}|{trip_plan.children or 0}"),
        "budget": _field_hash(str(trip_plan.budget or "")),
        "origin": _field_hash(trip_plan.origin or ""),
    }


def _state_to_session_state(state: GraphState) -> Dict[str, Any]:
    """Convert GraphState to session_state dict for persistence."""
    # Keep tiles in CATEGORY format for state restoration
    # Stored as: {"hotels": [tile1, tile2], "flights": [tile3]}
    # We preserve this format so state can be restored correctly on next request

    return {
        "messages": [
            {"role": "human" if m.type == "human" else "assistant", "content": m.content}
            for m in state.messages
        ],
        "trip_inputs": _trip_plan_to_trip_inputs(state.trip_plan),
        "metadata": {
            **state.metadata,
            "tiles": state.tiles,  # Keep in category format for state restoration
            "active_specialist": state.active_specialist,
            "constraints_violated": state.constraints_violated,
            # Persist for constraint change detection
            "last_constraint_hash": state.last_constraint_hash,
        },
        # NEW: Field hashes for selective regeneration strategy
        "field_hashes": _compute_field_hashes(state.trip_plan),
    }


def _restore_graph_state(session_state: Optional[Dict[str, Any]]) -> GraphState:
    """Restore GraphState from session_state dict."""
    from langchain_core.messages import AIMessage, HumanMessage

    from app.debug_utils import _debug_log

    if not session_state:
        _debug_log("_restore_graph_state: No session_state provided, returning empty state")
        state = GraphState()
        # Ensure typed settings exist even on first turn
        state.metadata["trip_inputs"] = {}
        state.metadata["trip_settings"] = TripSettings().model_dump()
        return state

    state = GraphState()

    # NOTE: Per-turn flag resets moved to reset_turn_metadata() at turn boundary.
    # Called from run_turn_streaming() and run_turn_internal() after _restore_graph_state().

    # Convert messages
    for msg in session_state.get("messages", []):
        if isinstance(msg, dict):
            if msg.get("role") == "human":
                state.messages.append(HumanMessage(content=msg.get("content", "")))
            else:
                state.messages.append(AIMessage(content=msg.get("content", "")))
        else:
            state.messages.append(msg)

    # Convert trip_inputs to TripPlan
    trip_inputs = session_state.get("trip_inputs", {})
    if trip_inputs:
        state.trip_plan.destination = trip_inputs.get("destination")
        state.trip_plan.origin = trip_inputs.get("origin")
        state.trip_plan.origin_iata = trip_inputs.get("origin_iata")
        state.trip_plan.destination_iata = trip_inputs.get("destination_iata")
        state.trip_plan.start_date = trip_inputs.get("start_date")
        state.trip_plan.end_date = trip_inputs.get("end_date")
        state.trip_plan.adults = trip_inputs.get("adults", 1) or 1
        state.trip_plan.children = trip_inputs.get("children", 0) or 0
        state.trip_plan.budget = trip_inputs.get("budget")
        state.trip_plan.currency = trip_inputs.get("currency", "USD") or "USD"

    # Restore metadata
    metadata = session_state.get("metadata", {})
    state.metadata = {k: v for k, v in metadata.items() if k not in ("tiles", "active_specialist")}

    # Also store trip_inputs in metadata for consistent access (router, specialist detection)
    state.metadata["trip_inputs"] = trip_inputs

    # ── Merge document's user-owned settings (SSoT) ──
    # Session may carry stale defaults from a prior graph run (e.g.,
    # activity_settings.categories=[] even though the user selected
    # ['diving'] via the pill UI).  The document is the SSoT for these
    # fields — main.py reads the latest doc and passes them here.
    doc_settings = session_state.get("_doc_settings", {})
    for field, value in doc_settings.items():
        if value:
            state.metadata["trip_inputs"][field] = value

    # ── Shadow-write: build typed TripSettings from merged trip_inputs ──
    _merged = {**trip_inputs}
    for field, value in doc_settings.items():
        if value:
            _merged[field] = value
    state.metadata["trip_settings"] = TripSettings(
        booking_types=BookingTypes(**(_merged.get("booking_types") or {})),
        flight_settings=FlightSettings(**(_merged.get("flight_settings") or {})),
        hotel_settings=HotelSettings(**(_merged.get("hotel_settings") or {})),
        activity_settings=ActivitySettings(**(_merged.get("activity_settings") or {})),
        transport_settings=TransportSettings(**(_merged.get("transport_settings") or {})),
        date_flex=_merged.get("date_flex", False),
        trip_duration=_merged.get("trip_duration"),
        date_window_start=_merged.get("date_window_start"),
        date_window_end=_merged.get("date_window_end"),
    ).model_dump()

    # HARD TRACE: Log the exact activity_settings reaching the graph
    final_activity = state.metadata["trip_inputs"].get("activity_settings", {})
    final_cats = final_activity.get("categories", []) if isinstance(final_activity, dict) else []
    logger.info(
        f"[RESTORE] activity_settings.categories={final_cats}, "
        f"_doc_settings_keys={list(doc_settings.keys())}, "
        f"doc_activity={doc_settings.get('activity_settings', 'NOT_SET')}"
    )

    state.tiles = metadata.get("tiles", {})
    state.active_specialist = metadata.get("active_specialist")
    state.last_constraint_hash = metadata.get(
        "last_constraint_hash"
    )  # Restore for constraint change detection

    # DEBUG: Log what strategy_sections we're restoring
    incoming_sections = metadata.get("strategy_sections", [])
    restored_sections = state.metadata.get("strategy_sections", [])
    _debug_log(
        f"_restore_graph_state: Incoming strategy_sections={len(incoming_sections)}, "
        f"Restored={len(restored_sections)}, "
        f"types={[s.get('specialist_type') for s in incoming_sections]}"
    )

    return state


# =============================================================================
# Routing Functions
# =============================================================================


def route_after_router(
    state: GraphState,
) -> Literal["specialist", "local_expert", "architect", "synthesizer", "logistics"]:
    """
    Route based on intent classification.

    If origin_only_logistics → LogisticsNode (fast path for origin/settings changes)
    If short_circuit_response (GREETING/RESET) → Synthesizer (skip architect)
    If specialist topic detected → VerticalSpecialist or LocalExpert
    Otherwise → TripArchitect (extracts destination first)

    CRITICAL: Specialists need destination to be meaningful.
    If destination is NOT extracted yet, route to Architect FIRST.
    Architect extracts destination, then route_after_architect() sends to specialists.
    """
    from app.debug_utils import _debug_log

    turn = get_turn_meta(state)

    # ORIGIN/SETTINGS FAST PATH: Route directly to logistics for flight/hotel fetch
    # Skips architect/specialists - only fetches tiles and rebuilds itinerary
    # @see intent_router origin detection block
    if turn.origin_only_logistics:
        _debug_log(
            f"Origin/settings change detected - fast path to logistics "
            f"(origin={state.trip_plan.origin})"
        )
        return "logistics"

    # Short-circuit responses (GREETING/RESET) skip to synthesizer
    if turn.short_circuit_response:
        return "synthesizer"

    has_destination = bool(state.trip_plan.destination)

    # CRITICAL FIX: If specialists are queued BUT destination is missing,
    # route to Architect FIRST to extract destination from user message.
    # Specialists without destination produce generic/empty content.
    # @see trace: "LOCAL_EXPERT Skipped - no destination set"
    if state.active_specialist and not has_destination:
        _debug_log(
            f"Specialists queued ({state.active_specialist}) but no destination - "
            "routing to architect first for extraction"
        )
        return "architect"

    # Explicit Niche Specialist (Diving, Skiing, etc.)
    # Only route here if destination is already known
    if state.active_specialist and state.active_specialist != "local_expert":
        return "specialist"

    # Explicit LocalExpert request
    # Only route here if destination is already known
    if state.active_specialist == "local_expert":
        return "local_expert"

    # Default: Route to Architect for field extraction
    # For "Rome to Dubai tomorrow", Architect extracts destination=Dubai, dates, etc.
    # Then route_after_architect() will route to LocalExpert if needed
    return "architect"


def route_after_specialist(
    state: GraphState,
) -> Literal["specialist", "local_expert", "logistics", "architect", "synthesizer"]:
    """
    Route after specialist completes - check for more pending specialists.

    CRITICAL: Routing functions CANNOT mutate state in LangGraph!
    State mutations must happen in NODES. The specialist node pops from
    pending_specialists at the START of its execution.

    This function only reads state and returns the routing decision.

    Flow:
    - If more pending specialists: route to next specialist
    - If speculative intent: Specialist → Synthesizer (preload content, no tiles)
    - If booking intent: Specialist → Logistics → Architect (fetch tiles)
    - If general intent: Specialist → Architect (extract fields, no tiles)
    """
    from app.debug_utils import _debug_log

    turn = get_turn_meta(state)

    # Check if there are more specialists to process
    # NOTE: We just peek, we don't pop - the specialist node handles that
    if state.pending_specialists:
        next_specialist = state.pending_specialists[0]
        _debug_log(
            f"Multi-specialist routing: next='{next_specialist}', "
            f"queue_len={len(state.pending_specialists)}"
        )

        if next_specialist == "local_expert":
            return "local_expert"
        return "specialist"

    # No more pending specialists

    # SPECULATIVE: Skip logistics (fetching prices) and architect (planning)
    # Go straight to synthesizer to emit the preview cards.
    if state.intent == "speculative":
        _debug_log("Specialist done, routing to synthesizer (speculative intent - preload only)")
        return "synthesizer"

    # Check if this is a "booking" intent (Build Plan button) or just general chat
    is_booking_intent = state.intent == "booking"
    is_generate_trigger = turn.is_generate_trigger

    # AUTO-FETCH RULE: Route to logistics when we have enough data to search
    # @see docs/ux_unified_architecture.md Section VI - "Dates = Search Trigger"
    #
    # CRITICAL FIX: Allow logistics routing when destination+dates exist (for hotels/activities)
    # even without origin. Hotels don't need origin - only flights do.
    # Previously this required origin, blocking hotel search.
    has_dates = bool(state.trip_plan.start_date)
    has_origin = bool(state.trip_plan.origin)
    has_destination = bool(state.trip_plan.destination)

    # Route to logistics if:
    # 1. Booking intent (Build Plan button) AND have destination
    # 2. Generate trigger AND have destination
    # 3. Dates set AND destination set (can search hotels even without origin)
    can_search = has_destination and (is_booking_intent or is_generate_trigger or has_dates)

    if can_search:
        if is_booking_intent:
            reason = "booking intent"
        elif has_dates:
            reason = "dates+destination set (auto-fetch hotels/activities)"
        else:
            reason = "generate trigger"

        # Log flight limitation if no origin
        if not has_origin:
            _debug_log(
                f"Specialist done, routing to logistics ({reason}) - "
                "note: flights disabled, no origin"
            )
        else:
            _debug_log(f"Specialist done, routing to logistics ({reason})")
        return "logistics"

    # Log skip reason for debugging
    if has_dates and not has_destination:
        _debug_log("Specialist done, skipping logistics (no destination set)")

    # OPTIMIZATION: If architect already ran this turn, skip to guard/synthesizer
    # Prevents double-call: router→logistics(skip)→architect→local_expert→architect(again)
    if turn.architect_ran_this_turn:
        _debug_log("[SPECIALIST→] Skipping architect (already ran this turn)")
        return _should_run_guard(state)

    # General intent without dates - skip tile fetching, go to architect for extraction
    _debug_log("Specialist done, skipping logistics, routing to architect (no dates)")
    return "architect"


def route_after_architect(
    state: GraphState,
) -> Literal["specialist", "local_expert", "logistics", "guard", "synthesizer"]:
    """
    Route after architect completes.

    SPECIALIST DISPATCH: If specialists were queued (from router) but deferred
    because destination was missing, NOW dispatch them since architect extracted it.

    LOCAL EXPERT RULE: If intent is general/planning, destination is set,
    and local_expert hasn't run yet, route to LocalExpert for content generation.
    This ensures the UI gets destination vibes, local tips, etc.
    @see docs/plan_graph_analysis.md - "Local Expert Fallback"

    AUTO-FETCH RULE: If dates are set but tiles are empty, route to logistics.
    This ensures tile search happens automatically when user provides dates in chat.
    @see docs/ux_unified_architecture.md Section VI - "Dates = Search Trigger"

    Flow:
    1. First pass: Architect extracts destination → Queued specialists (local_expert first)
    2. Specialists generate content → Logistics (if dates) or Guard
    3. OR: Architect extracts dates → Logistics → Architect (second pass) → Guard
    """
    from app.debug_utils import _debug_log

    turn = get_turn_meta(state)
    persistent = get_persistent_meta(state)

    has_destination = bool(state.trip_plan.destination)
    has_origin = bool(state.trip_plan.origin)
    has_dates = bool(state.trip_plan.start_date)
    has_tiles = bool(state.tiles)
    is_speculative = state.intent == "speculative"
    local_expert_ran = persistent.local_expert_ran
    logistics_attempted = turn.logistics_attempted

    # SPECIALIST DISPATCH: If specialists were queued but deferred (no destination),
    # now route to them since architect has extracted the destination.
    # @see route_after_router - defers specialists when destination is missing
    if has_destination and state.active_specialist:
        if state.active_specialist == "local_expert":
            _debug_log(
                f"Architect done, dispatching deferred local_expert "
                f"(destination={state.trip_plan.destination})"
            )
            return "local_expert"
        else:
            _debug_log(
                f"Architect done, dispatching deferred specialist={state.active_specialist} "
                f"(destination={state.trip_plan.destination})"
            )
            return "specialist"

    # LOCAL EXPERT RULE: Route to LocalExpert for general planning intent
    # Conditions: destination extracted + no specialist ran yet + general intent
    # This ensures "Rome to Dubai tomorrow" gets local content before logistics
    is_general_intent = state.intent in ("general", "planning", None)
    needs_local_expert = (
        has_destination
        and not local_expert_ran
        and is_general_intent
        and not state.active_specialist  # No niche specialist active
    )

    if needs_local_expert:
        _debug_log(
            f"Architect done, routing to local_expert "
            f"(destination={state.trip_plan.destination}, local_expert_ran={local_expert_ran})"
        )
        return "local_expert"

    # Auto-fetch: dates set but no tiles yet, and not speculative intent
    # CRITICAL FIX: Allow logistics routing with destination+dates (for hotels/activities)
    # even without origin. Hotels don't need origin - only flights do.
    # Only block if logistics has already been attempted (prevents infinite loop)
    can_fetch_logistics = has_destination and not logistics_attempted
    if has_dates and not has_tiles and not is_speculative and can_fetch_logistics:
        if not has_origin:
            _debug_log(
                "Architect done, routing to logistics "
                "(dates+destination set, hotels only - no origin)"
            )
        else:
            _debug_log("Architect done, routing to logistics (dates set, no tiles yet)")
        return "logistics"

    # Skip logistics if no destination - can't search anything
    if has_dates and not has_tiles and not has_destination:
        _debug_log("Architect done, skipping logistics (no destination set)")

    # Fall through to existing guard logic
    return _should_run_guard(state)


def _should_run_guard(state: GraphState) -> Literal["guard", "synthesizer"]:
    """
    Determine if we should run constraint checking.

    Run guard if:
    - We have tiles to validate
    - We have specialist constraints to check
    - We have a destination set (for route validation - SAME_CITY, UNKNOWN_PLACE)
    """
    # Always run guard if destination is set (route validation)
    if state.trip_plan.destination:
        return "guard"
    # Also run for tiles/constraints
    if state.tiles or state.trip_plan.constraints:
        return "guard"
    return "synthesizer"


def route_after_logistics(state: GraphState) -> Literal["architect", "guard", "synthesizer"]:
    """
    Skip architect if fields already extracted this turn.

    After logistics fetches tiles, architect typically runs to "finalize" the plan.
    But if architect already ran earlier in the same turn (extracted fields, set mode),
    there's nothing new to extract - skip to guard/synthesizer.

    This saves ~800ms + one GPT-4o call per plan with tiles.
    """
    from app.debug_utils import _debug_log

    turn = get_turn_meta(state)

    # If architect already ran this turn, skip to guard/synthesizer
    if turn.architect_ran_this_turn:
        _debug_log("[LOGISTICS→] Skipping architect (already ran this turn)")
        return _should_run_guard(state)  # Reuse existing helper
    return "architect"


def route_after_guard(state: GraphState) -> Literal["architect", "synthesizer"]:
    """
    Route based on constraint violations.

    Logic:
    1. Route Errors (Rome->Rome, Atlantis) → Synthesizer (skip auto-fix)
       NOTE: Rollback happens in constraint_guard node, not here.
    2. Budget/Time Errors → Architect (auto-fix loop, max 1 retry)
    3. No Errors → Synthesizer (success)
    """
    turn = get_turn_meta(state)
    has_blocking = turn.has_blocking_violations
    retry_count = state.guard_retry_count
    violations = turn.constraint_violations

    # 1. UNFIXABLE CONSTRAINT SHORT-CIRCUIT
    # Route and specialist errors are unfixable by Architect - skip auto-fix loop.
    # - Route: Rome->Rome, invalid destination (rollback already happened in constraint_guard)
    # - Specialist: departure buffer, cross-domain conflicts
    #   (Architect can't reschedule specialist output)
    unfixable_categories = {"route", "specialist"}
    is_unfixable = any(v.get("category") in unfixable_categories for v in violations)

    # Determine destination for logging
    if is_unfixable:
        destination = "synthesizer"
    elif has_blocking and retry_count < 1:
        destination = "architect"
    else:
        destination = "synthesizer"

    # Route decision logging - shows exactly what routing decision was made and why
    logger.info(
        f"[ROUTE] after_guard: blocking={has_blocking} unfixable={is_unfixable} "
        f"retry={retry_count} → {destination}"
    )

    if is_unfixable:
        return "synthesizer"

    # 2. OPTIMIZATION AUTO-FIX (Budget/Schedule - Safe to retry)
    if has_blocking and retry_count < 1:
        return "architect"

    return "synthesizer"


# =============================================================================
# Graph Definition
# =============================================================================


def create_optimized_graph() -> StateGraph:
    """
    Create the optimized 6-node graph.

    Flow:
    START → router → [specialist →] architect → [guard →] synthesizer → END

    The specialist and guard nodes are conditional based on state.
    """
    # Initialize the graph with state
    workflow = StateGraph(GraphState)

    # ==========================================================================
    # Add Nodes
    # ==========================================================================
    workflow.add_node("router", intent_router)
    workflow.add_node("architect", trip_architect)
    workflow.add_node("specialist", vertical_specialist)
    workflow.add_node("local_expert", local_expert)
    workflow.add_node("logistics", logistics_node)
    workflow.add_node("guard", constraint_guard)
    workflow.add_node("synthesizer", synthesizer)

    # ==========================================================================
    # Define Edges
    # ==========================================================================

    # Entry point
    workflow.set_entry_point("router")

    # Router → Specialist, LocalExpert, Architect, or Synthesizer (conditional)
    # Route after router: specialists, architect, synthesizer, or logistics (fast path)
    workflow.add_conditional_edges(
        "router",
        route_after_router,
        {
            "specialist": "specialist",
            "local_expert": "local_expert",
            "architect": "architect",
            "synthesizer": "synthesizer",  # For GREETING/RESET short-circuits
            "logistics": "logistics",  # For origin/settings fast path (skip architect)
        },
    )

    # Specialist → Next specialist, Logistics, Architect, or Synthesizer (conditional)
    # Multi-specialist support: loop through pending_specialists queue
    # Speculative intent: go to synthesizer (preload content, no tiles)
    # Booking intent: go to logistics (fetch tiles), General intent: go to architect (extract only)
    workflow.add_conditional_edges(
        "specialist",
        route_after_specialist,
        {
            "specialist": "specialist",
            "local_expert": "local_expert",
            "logistics": "logistics",
            "architect": "architect",  # General intent - extract fields, skip tiles
            "synthesizer": "synthesizer",  # Speculative intent - preload only
        },
    )

    # LocalExpert → Next specialist, Logistics, Architect, or Synthesizer (conditional)
    # Same multi-specialist routing logic
    workflow.add_conditional_edges(
        "local_expert",
        route_after_specialist,
        {
            "specialist": "specialist",
            "local_expert": "local_expert",
            "logistics": "logistics",
            "architect": "architect",  # General intent - extract fields, skip tiles
            "synthesizer": "synthesizer",  # Speculative intent - preload only
        },
    )

    # Logistics → Architect (conditional: skip if architect already ran)
    # Logistics sanitizes flight data, then Architect builds the plan
    # OPTIMIZATION: If architect already extracted fields this turn, skip to guard
    workflow.add_conditional_edges(
        "logistics",
        route_after_logistics,
        {
            "architect": "architect",
            "guard": "guard",
            "synthesizer": "synthesizer",
        },
    )

    # Architect → LocalExpert, Logistics, Guard, or Synthesizer (conditional)
    # LOCAL EXPERT: If destination extracted and general intent, route to local_expert
    # AUTO-FETCH: If dates extracted but no tiles, route to logistics
    workflow.add_conditional_edges(
        "architect",
        route_after_architect,
        {
            "specialist": "specialist",  # For deferred specialists after destination extracted
            "local_expert": "local_expert",  # For general intent after destination extracted
            "logistics": "logistics",
            "guard": "guard",
            "synthesizer": "synthesizer",
        },
    )

    # Guard → Architect (retry) or Synthesizer (conditional)
    # Auto-fix loop: if blocking violations and retry < 1, loop back to Architect
    workflow.add_conditional_edges(
        "guard",
        route_after_guard,
        {
            "architect": "architect",
            "synthesizer": "synthesizer",
        },
    )

    # Synthesizer → END
    workflow.add_edge("synthesizer", END)

    return workflow


def compile_graph(workflow: StateGraph) -> Any:
    """Compile the graph for execution."""
    return workflow.compile()


# =============================================================================
# Execution Interface (Non-Streaming)
# =============================================================================


async def run_turn(
    user_message: str,
    session_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Run a single turn of the conversation (non-streaming).

    Used by main.py POST /api/graph_plan endpoint.

    Args:
        user_message: User's message text
        session_state: Optional previous state to continue from

    Returns:
        Result dict with assistant_message, session_state, document, etc.
    """
    from langchain_core.messages import HumanMessage

    # PANIC BUTTON - non-LLM kill switch (must be first!)
    if _is_panic_command(user_message):
        logger.info(f"Panic button triggered: '{user_message}'")
        return _create_reset_response()

    # Get compiled graph
    graph = get_or_create_graph()

    # Restore state from session
    state = _restore_graph_state(session_state)

    # Add user message
    state.messages.append(HumanMessage(content=user_message))

    # Run the graph with timeout to prevent infinite spinners
    try:
        result = await asyncio.wait_for(
            graph.ainvoke(state),
            timeout=GRAPH_TIMEOUT_SECONDS,
        )
        # LangGraph returns dict, convert back to Pydantic
        if isinstance(result, dict):
            result_state = GraphState(**result)
        else:
            result_state = result
    except asyncio.TimeoutError:
        logger.error(f"Graph execution timed out after {GRAPH_TIMEOUT_SECONDS}s")
        # Return graceful degradation response
        return {
            "assistant_message": (
                "I'm taking longer than expected to plan this. "
                "Could you try again? If the issue persists, try simplifying your request."
            ),
            "suggested_responses": ["Try again", "Start over"],
            "session_state": session_state or {},
            "branches": [],
            "trip_inputs": session_state.get("trip_inputs", {}) if session_state else {},
            "ready_to_generate": False,
            "ui_events": ["UI_TIMEOUT"],
            "document": {
                "trip_inputs": session_state.get("trip_inputs", {}) if session_state else {},
                "assistant_message": "I'm taking longer than expected. Please try again.",
                "suggested_responses": ["Try again", "Start over"],
                "plan_view_state": (
                    session_state.get("metadata", {}).get("plan_view_state", "S0_BOOTSTRAP")
                    if session_state
                    else "S0_BOOTSTRAP"
                ),
                "strategy_sections": (
                    session_state.get("metadata", {}).get("strategy_sections", [])
                    if session_state
                    else []
                ),
                "tiles": {},
                "ready_to_generate": False,
            },
            "updated_by": "ai",
            "updated_at": datetime.now().isoformat(),
            "changes_made": False,
            "request_id": state.metadata.get("request_id", ""),
            "errors": [],
        }
    except Exception as e:
        logger.error(f"Graph execution failed: {e}")
        raise

    # Convert result to response format
    return _format_result(result_state, session_state)


async def run_turn_streaming(
    user_message: str,
    session_state: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Run a single turn with true LLM token streaming via astream_events.

    Yields SSE-compatible events:
    - {"type": "token", "data": "..."} - Streaming tokens from Synthesizer LLM
    - {"type": "node_status", "data": {...}} - Node progress
    - {"type": "complete", "data": {...}} - Final result

    Uses LangGraph's astream_events to:
    - Tap into Synthesizer's LLM token stream
    - Let LangGraph handle checkpointing automatically
    - Avoid "amnesia" where bot forgets its own responses

    Args:
        user_message: User's message text
        session_state: Optional previous state to continue from

    Yields:
        Stream events for SSE
    """
    import time

    from langchain_core.messages import HumanMessage

    from app.debug_utils import CompactLogger, RequestMetrics

    # PANIC BUTTON - non-LLM kill switch (must be first!)
    if _is_panic_command(user_message):
        logger.info(f"Panic button triggered (streaming): '{user_message}'")
        reset_response = _create_reset_response()
        yield {"type": "token", "data": reset_response["assistant_message"]}
        yield {"type": "complete", "data": reset_response}
        return

    # Initialize request metrics for token tracking (compact logging mode)
    metrics = RequestMetrics(start_time=time.time())

    # Get compiled graph
    graph = get_or_create_graph()

    # Restore state from session
    state = _restore_graph_state(session_state)

    # Canonical turn boundary — all per-turn flags start clean
    reset_turn_metadata(state)

    # Store metrics in state for nodes to access
    state.metadata["_metrics"] = metrics

    # Add user message
    state.messages.append(HumanMessage(content=user_message))

    # Emit node status for router
    yield {"type": "node_status", "data": {"node": "router", "status": "running"}}

    try:
        current_node = None
        result_state = None
        streamed_tokens = []
        final_output = None

        # Use astream_events to tap into LLM streaming
        # This runs the full graph and captures token events from the Synthesizer
        # Wrap with asyncio.timeout to cancel if node hangs (no events = suspended loop)
        async with asyncio.timeout(GRAPH_TIMEOUT_SECONDS):
            async for event in graph.astream_events(state, version="v2"):
                event_type = event.get("event")

                # Track node transitions via chain events
                if event_type == "on_chain_start":
                    node_name = event.get("metadata", {}).get("langgraph_node")
                    if node_name and node_name != current_node:
                        # Emit completion for previous node
                        if current_node:
                            yield {
                                "type": "node_status",
                                "data": {"node": current_node, "status": "completed"},
                            }
                        # Emit start for new node
                        current_node = node_name
                        yield {
                            "type": "node_status",
                            "data": {
                                "node": node_name,
                                "status": "started",
                                "label": _get_node_label(node_name),
                                "icon_key": _get_node_icon(node_name),
                                "estimated_duration_ms": _get_node_duration(node_name),
                            },
                        }

                # Stream tokens from Synthesizer's LLM
                elif event_type == "on_chat_model_stream":
                    # Only stream from synthesizer node
                    node = event.get("metadata", {}).get("langgraph_node")
                    if node == "synthesizer":
                        chunk = event.get("data", {}).get("chunk")
                        if chunk and hasattr(chunk, "content") and chunk.content:
                            streamed_tokens.append(chunk.content)
                            # NOTE: Key must be "data" to match frontend SSE parsing
                            yield {"type": "token", "data": chunk.content}

                # Capture final state on chain end - be more permissive
                elif event_type == "on_chain_end":
                    node = event.get("metadata", {}).get("langgraph_node")
                    output = event.get("data", {}).get("output")
                    if output is not None:
                        # Always capture the latest output - it might be a dict or GraphState
                        final_output = output

                        # Logic Terminal: Emit routing decision when router
                        # completes (DS Section 19.C). This creates the
                        # ">> ROUTING: DIVING" line in the frontend terminal
                        if node == "router":
                            # Extract active_specialist from output (dict or GraphState)
                            active_specialist = None
                            if isinstance(output, dict):
                                active_specialist = output.get("active_specialist")
                            elif hasattr(output, "active_specialist"):
                                active_specialist = output.active_specialist

                            # Emit logic_reveal for non-general specialists
                            if active_specialist and active_specialist not in ("general", None):
                                yield {
                                    "type": "node_status",
                                    "data": {
                                        "node": "logic_reveal",
                                        "label": f"ROUTING: {active_specialist.upper()}",
                                        "status": "completed",
                                    },
                                }

        # Emit final node completion
        if current_node:
            yield {
                "type": "node_status",
                "data": {"node": current_node, "status": "completed"},
            }

        # Convert final output to GraphState
        if final_output is not None:
            if isinstance(final_output, dict):
                try:
                    result_state = GraphState(**final_output)
                except Exception as e:
                    logger.warning(f"Failed to parse final output as GraphState: {e}")
                    # PARTIAL RECOVERY: Extract key fields even if full parse fails
                    # This preserves tiles/sections instead of losing all node-computed state
                    try:
                        partial_state = state  # Start from input state
                        if "tiles" in final_output and final_output["tiles"]:
                            partial_state.tiles = final_output["tiles"]
                        if "trip_plan" in final_output:
                            if isinstance(final_output["trip_plan"], dict):
                                partial_state.trip_plan = TripPlan(**final_output["trip_plan"])
                            elif isinstance(final_output["trip_plan"], TripPlan):
                                partial_state.trip_plan = final_output["trip_plan"]
                        if "metadata" in final_output and isinstance(
                            final_output["metadata"], dict
                        ):
                            partial_state.metadata.update(final_output["metadata"])
                        if streamed_tokens:
                            partial_state.last_summary = "".join(streamed_tokens)
                        result_state = partial_state
                        logger.info("Partial state recovery succeeded — tiles/plan preserved")
                    except Exception as e2:
                        logger.warning(f"Partial state recovery also failed: {e2}")
            elif isinstance(final_output, GraphState):
                result_state = final_output

        # If still no state, construct from input state + streamed tokens
        if result_state is None:
            logger.warning("No state captured from events, using input state with streamed content")
            result_state = state
            # Update last_summary with streamed content if any
            if streamed_tokens:
                result_state.last_summary = "".join(streamed_tokens)

        # If we didn't stream any tokens, emit the full response as a single token
        if not streamed_tokens and result_state.last_summary:
            yield {"type": "token", "data": result_state.last_summary}

        # Emit complete event with full result
        final_result = _format_result(result_state, session_state)

        # Summary of graph execution
        from app.debug_utils import log_complete

        log_complete(
            tiles=len(final_result.get("document", {}).get("tiles", {})),
            strategy_sections=len(final_result.get("document", {}).get("strategy_sections", [])),
            view_state=final_result.get("document", {}).get("plan_view_state", "unknown"),
        )

        # Compact logging: emit request summary with token tracking and cost
        clog = CompactLogger("graph", metrics=metrics)
        clog.request_summary()

        yield {
            "type": "complete",
            "data": final_result,
        }

    except TimeoutError:
        # asyncio.timeout() raises TimeoutError when deadline expires
        logger.error(f"Streaming execution timed out after {GRAPH_TIMEOUT_SECONDS}s")
        yield {"type": "token", "data": "\n\n(Taking longer than expected, please try again)"}
        yield {"type": "error", "message": "Request timed out. Please try again."}
        return

    except Exception as e:
        import traceback

        error_traceback = traceback.format_exc()
        logger.error(f"Streaming execution failed: {e}\n{error_traceback}")
        # Emit error event but don't re-raise to ensure generator completes cleanly
        yield {"type": "error", "message": f"{type(e).__name__}: {str(e)}"}


def _compute_plan_view_state(state: GraphState) -> str:
    """
    Compute plan_view_state for frontend stage rendering.

    State machine:
    - S0_BOOTSTRAP: Setup checklist, no specialist content yet.
    - S2_STRATEGY_READY: Strategy preview (specialist content) OR full logistics (tiles).
    - S3_*: Itinerary states (handled by expand-itinerary endpoint)

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
    """
    Convert category-based tiles to ID-based map for frontend.

    Backend stores: {"flights": [tile1, tile2], "hotels": [tile3]}
    Frontend expects: {"tile1_id": tile1, "tile2_id": tile2, "tile3_id": tile3}
    """
    if not tiles_by_category:
        return {}

    result: Dict[str, Any] = {}
    tiles_without_id = 0
    for category, tile_list in tiles_by_category.items():
        if not isinstance(tile_list, list):
            logger.warning(f"_flatten_tiles_to_id_map: {category} is not a list: {type(tile_list)}")
            continue
        for tile in tile_list:
            if isinstance(tile, dict):
                tile_id = tile.get("id")
                if tile_id:
                    result[tile_id] = tile
                else:
                    tiles_without_id += 1
                    logger.warning(
                        f"_flatten_tiles_to_id_map: Tile without ID in {category}: "
                        f"keys={list(tile.keys())[:5]}"
                    )

    return result


def _sort_sections_anchor_first(sections: list) -> list:
    """Delegate to canonical implementation in section_builder service."""
    return sort_sections_anchor_first(sections)


# =============================================================================
# _format_result: Extracted Sub-Functions
# =============================================================================

# Settings fields owned by frontend UI (not in TripPlan)
_USER_SETTINGS_FIELDS = (
    "activity_settings",
    "hotel_settings",
    "flight_settings",
    "transport_settings",
    "booking_types",
)


def _build_trip_inputs_with_settings(state: GraphState) -> Dict[str, Any]:
    """Convert TripPlan to trip_inputs and merge user/extracted settings."""
    trip_inputs = _trip_plan_to_trip_inputs(state.trip_plan)

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
            logger.warning("[_format_result] Route error - clearing tiles/sections")
            flattened_tiles: Dict[str, Any] = {}
            plan_view_state = "S0_BOOTSTRAP"
            state.metadata["strategy_sections"] = []
            state.metadata["executed_strategy_topics"] = []
            state.tiles = {}
        else:
            # Specialist violations (diving buffer, altitude, etc.) - preserve state
            # User can still see their plan, Synthesizer explains the constraint
            logger.info("[_format_result] Specialist violation - preserving tiles/sections")
            flattened_tiles = _flatten_tiles_to_id_map(state.tiles)
            plan_view_state = _compute_plan_view_state(state)
    else:
        # Normal path - flatten tiles for frontend
        flattened_tiles = _flatten_tiles_to_id_map(state.tiles)
        plan_view_state = _compute_plan_view_state(state)
        is_route_error = False

    logger.info(
        f"_format_result: plan_view_state={plan_view_state}, "
        f"flattened_tiles_count={len(flattened_tiles)}, "
        f"raw_tiles_count={sum(len(v) for v in state.tiles.values()) if state.tiles else 0}"
    )

    return flattened_tiles, plan_view_state, has_blocking_violations, is_route_error


# =============================================================================
# _build_new_section: Sub-Functions
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
        f"_format_result: needs_section={needs_section} (flattened_tiles={bool(flattened_tiles)})"
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
        f"_format_result: Saving {len(final_sections)} "
        f"strategy_sections to session_state, types={saved_types}"
    )
    if saved_types and saved_types[0] not in ("local_expert", "general"):
        _debug_log(
            f"⚠️ WARNING: Anchor rule violation! First section is '{saved_types[0]}', "
            f"expected 'local_expert' or 'general'"
        )

    return strategy_sections, executed_topics


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
    from app.planner.state import trip_plan_is_ready
    from app.schemas import StrategySection as StrategySectionModel

    # Shadow-validate strategy sections against Pydantic model (log only)
    for section_dict in strategy_sections:
        try:
            StrategySectionModel(**section_dict)
        except Exception as e:
            logger.warning(f"StrategySection validation: {section_dict.get('id')}: {e}")

    # CRITICAL: Capture session_state AFTER metadata is updated (not before!)
    updated_session_state = _state_to_session_state(state)

    # Build document object matching PlanDocumentData type expected by frontend
    document = {
        "trip_context_id": None,
        "trip_inputs": trip_inputs,
        "branches": [],  # Not used
        "tiles": flattened_tiles,  # Flattened to ID-based map for frontend
        "assistant_message": state.last_summary or "",
        "ready_to_generate": trip_plan_is_ready(state.trip_plan),
        "suggested_responses": state.suggested_replies,
        # Plan view state for right panel stage rendering
        "plan_view_state": plan_view_state,
        # Strategy content for AgentCards
        "strategy_sections": strategy_sections,
        "pending_strategy_topics": state.metadata.get("pending_strategy_topics", []),
        "executed_strategy_topics": executed_topics,
        # Origin update flag for frontend to trigger flight fetch
        "origin_just_set": state.metadata.get("origin_just_set", False),
        # Constraint validation receipts for Trip DNA bar badges
        "constraints_validated": state.metadata.get("constraints_validated", []),
        "constraint_violations": state.metadata.get("constraint_violations", []),
        # Itinerary day cards (computed by ItineraryBuilder, None until S2_STRATEGY_READY)
        "itinerary_day_cards": itinerary_day_cards,
    }

    # DEBUG: Log origin_just_set for troubleshooting
    if state.metadata.get("origin_just_set"):
        logger.info(f"[_format_result] origin_just_set=True, origin={trip_inputs.get('origin')}")

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
        "suggested_responses": state.suggested_replies,
        "branches": [],
        "trip_inputs": trip_inputs,
        "ready_to_generate": trip_plan_is_ready(state.trip_plan),
        "errors": state.constraints_violated,
    }


# =============================================================================
# _format_result: Orchestrator
# =============================================================================


def _format_result(
    state: GraphState,
    original_session_state: Optional[Dict[str, Any]] = None,
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
    _debug_log(f"_format_result: BEFORE - {len(strategy_sections)} sections, types={section_types}")
    for s in strategy_sections:
        content_count = len(s.get("content_added", []))
        constraint_count = len(s.get("constraints_applied", []))
        _debug_log(
            f"  Section '{s.get('specialist_type')}': "
            f"content_added={content_count}, constraints={constraint_count}"
        )
    _debug_log(
        f"_format_result: active_specialist={state.active_specialist}, "
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
    itinerary_day_cards = None
    if plan_view_state == "S2_STRATEGY_READY" and not has_blocking:
        try:
            from app.planner.services.itinerary_adapter import build_itinerary_from_state

            result = build_itinerary_from_state(state)
            if result and result.success:
                itinerary_day_cards = [dc.model_dump() for dc in result.day_cards]
        except Exception as e:
            logger.warning(f"[_format_result] Itinerary build failed (shadow): {e}")

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


async def run_turn_internal(
    graph: Any,
    user_message: str,
    session_state: Optional[Dict[str, Any]] = None,
) -> GraphState:
    """
    Run a single turn (internal interface).

    For internal use - prefer run_turn() for compatibility.
    """
    from langchain_core.messages import HumanMessage

    # Restore state from session
    state = _restore_graph_state(session_state)

    # Canonical turn boundary — all per-turn flags start clean
    reset_turn_metadata(state)

    # Add user message
    state.messages.append(HumanMessage(content=user_message))

    # Run the graph
    result = await graph.ainvoke(state)

    # LangGraph returns dict, convert back to Pydantic if needed
    if isinstance(result, dict):
        result = GraphState(**result)

    return result


def get_response_from_state(state: GraphState) -> Dict[str, Any]:
    """
    Extract the response data from state for frontend.

    Returns dict with:
    - message: The response text
    - suggested_replies: Quick reply options
    - tiles: Fetched inventory
    - ui_events: Frontend events to trigger
    - trip_plan: Current plan state
    """
    return {
        "message": state.last_summary or "",
        "suggested_replies": state.suggested_replies,
        "tiles": state.tiles,
        "ui_events": state.ui_events,
        "trip_plan": state.trip_plan.model_dump() if state.trip_plan else {},
        "constraints_violated": state.constraints_violated,
        "active_specialist": state.active_specialist,
        "active_agent_id": state.active_agent_id,
    }


# =============================================================================
# Factory Function
# =============================================================================


def get_graph():
    """
    Factory function to get a compiled graph.

    Usage:
        graph = get_graph()
        result = await run_turn_internal(graph, "I want to go diving in Bali")
    """
    workflow = create_optimized_graph()
    return compile_graph(workflow)


# =============================================================================
# Module-level graph instance (lazy initialization)
# =============================================================================

_graph = None


def get_or_create_graph():
    """Get or create the graph instance (singleton pattern)."""
    global _graph
    if _graph is None:
        _graph = get_graph()
    return _graph


# =============================================================================
# Stub Functions for V1 Compatibility
# =============================================================================
# These functions are imported by main.py for compatibility.
# They provide safe no-op implementations to prevent import errors.


def get_planner_debug_info() -> Dict[str, Any]:
    """Return debug info for planner."""
    return {
        "version": "1.0",
        "build_id": PLANNER_BUILD_ID,
        "cache_schema": CACHE_SCHEMA_VERSION,
        "prompt_hash": PROMPT_BUNDLE_HASH,
        "graph_nodes": ["router", "specialist", "architect", "guard", "synthesizer"],
    }


def get_planner_snapshot() -> Dict[str, Any]:
    """Return planner snapshot for debugging."""
    return get_planner_debug_info()


def get_graph_stats() -> Dict[str, Any]:
    """Return graph statistics."""
    return {
        "nodes": 5,
        "edges": 6,
        "version": "1.0",
    }


def prewarm_prompts() -> Dict[str, Any]:
    """Pre-warm prompts (no-op, prompts are loaded on demand)."""
    return {
        "prompts_warmed": 0,
        "templates_loaded": 5,  # ~5 prompt templates
        "warmup_ms": 0,
    }


def validate_template_coverage() -> Dict[str, Any]:
    """Validate all templates are covered."""
    return {
        "valid": True,
        "missing_fields": [],
        "errors": [],
    }


def condense_long_message(message: str, max_len: int) -> str:
    """Truncate long messages (simple implementation)."""
    if len(message) <= max_len:
        return message
    return message[: max_len - 3] + "..."


async def clear_all_caches() -> None:
    """Clear all caches."""
    global _graph
    _graph = None
    await clear_response_caches()


async def clear_all_checkpoints() -> None:
    """Clear all checkpoints (no-op)."""
    pass


async def clear_response_caches() -> int:
    """Clear response caches (experience L1 + L2)."""
    from app.services.experience_generator import clear_experience_cache

    # L1: in-memory
    l1_cleared = clear_experience_cache()

    # L2: database (experience entries only)
    l2_cleared = 0
    try:
        from sqlalchemy import delete

        from app.db import _get_async_session_factory
        from app.db_models import ResponseCache

        factory = _get_async_session_factory()
        async with factory() as db:
            result = await db.execute(
                delete(ResponseCache).where(ResponseCache.cache_type == "experience")
            )
            l2_cleared = result.rowcount
            await db.commit()
    except Exception:
        pass

    return l1_cleared + l2_cleared


async def clear_session_checkpoint(session_id: str) -> None:
    """Clear session checkpoint (no-op)."""
    pass


def checkpoint_stats() -> Dict[str, Any]:
    """Return checkpoint statistics."""
    return {"count": 0, "version": "1.0"}


def response_cache_stats() -> Dict[str, Any]:
    """Return response cache statistics."""
    return {"hits": 0, "misses": 0, "version": "1.0"}


def prune_stale_checkpoints(max_age_hours: int = 24) -> int:
    """Prune stale checkpoints (no-op)."""
    return 0
