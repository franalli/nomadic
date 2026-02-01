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
    from app.plan_graph import run_turn, run_turn_streaming
    result = await run_turn(user_message, session_state)
"""

import logging
import os
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, Literal, Optional

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from app.placeholders import get_hero_image
from app.planner.nodes.constraint_guard import constraint_guard
from app.planner.nodes.intent_router import intent_router
from app.planner.nodes.local_expert import local_expert
from app.planner.nodes.logistics_node import logistics_node
from app.planner.nodes.synthesizer import synthesizer
from app.planner.nodes.trip_architect import trip_architect
from app.planner.nodes.vertical_specialist import vertical_specialist
from app.planner.state import GraphState, TripPlan

logger = logging.getLogger(__name__)


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
        "label": "Consulting local expert...",
        "icon_key": "building",
        "estimated_duration_ms": 800,
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
# Input Types (for main.py interface)
# =============================================================================


class TripInputs(BaseModel):
    """TripInputs for main.py interface."""

    destination: Optional[str] = None
    origin: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    requires_assistance: Optional[bool] = None
    budget: Optional[float] = None
    currency: Optional[str] = None
    booking_types: Dict[str, Any] = Field(default_factory=dict)
    flight_settings: Dict[str, Any] = Field(default_factory=dict)
    hotel_settings: Dict[str, Any] = Field(default_factory=dict)
    activity_settings: Dict[str, Any] = Field(default_factory=lambda: {"categories": []})
    transport_settings: Dict[str, Any] = Field(default_factory=dict)
    strategy_settings: Dict[str, Any] = Field(default_factory=dict)
    date_flex: bool = False
    trip_duration: Optional[int] = None
    date_window_start: Optional[str] = None
    date_window_end: Optional[str] = None


def _trip_plan_to_trip_inputs(plan: TripPlan) -> Dict[str, Any]:
    """Convert TripPlan to trip_inputs dict with display fields."""
    # Calculate travelers count
    total_travelers = (plan.adults or 1) + (plan.children or 0)

    # Build dates_text for display
    dates_text = None
    if plan.start_date and plan.end_date:
        dates_text = f"{plan.start_date} - {plan.end_date}"
    elif plan.start_date:
        dates_text = plan.start_date

    # Build budget_text for display
    budget_text = None
    if plan.budget:
        budget_text = f"${plan.budget:,.0f}"

    # Build travelers_text for display
    travelers_text = f"{total_travelers} traveler{'s' if total_travelers != 1 else ''}"

    return {
        # Structured fields
        "destination": plan.destination,
        "origin": plan.origin,
        "start_date": plan.start_date,
        "end_date": plan.end_date,
        "adults": plan.adults,
        "children": plan.children,
        "budget": plan.budget,
        "currency": plan.currency,
        "booking_types": {},
        "flight_settings": {},
        "hotel_settings": {},
        "activity_settings": {"categories": []},
        "transport_settings": {},
        "strategy_settings": {},
        # Legacy display fields for V1 frontend pills
        "destination_text": plan.destination,
        "dates_text": dates_text,
        "travelers_text": travelers_text,
        "budget_text": budget_text,
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
    }


def _restore_graph_state(session_state: Optional[Dict[str, Any]]) -> GraphState:
    """Restore GraphState from session_state dict."""
    from langchain_core.messages import AIMessage, HumanMessage

    from app.debug_utils import _debug_graph

    if not session_state:
        _debug_graph("_restore_graph_state: No session_state provided, returning empty state")
        return GraphState()

    state = GraphState()

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
    state.tiles = metadata.get("tiles", {})
    state.active_specialist = metadata.get("active_specialist")
    state.last_constraint_hash = metadata.get(
        "last_constraint_hash"
    )  # Restore for constraint change detection

    # DEBUG: Log what strategy_sections we're restoring
    incoming_sections = metadata.get("strategy_sections", [])
    restored_sections = state.metadata.get("strategy_sections", [])
    _debug_graph(
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
) -> Literal["specialist", "local_expert", "architect", "synthesizer"]:
    """
    Route based on intent classification.

    If short_circuit_response (GREETING/RESET) → Synthesizer (skip architect)
    If specialist topic detected → VerticalSpecialist or LocalExpert
    Otherwise → TripArchitect (extracts destination first)

    CRITICAL: Specialists need destination to be meaningful.
    If destination is NOT extracted yet, route to Architect FIRST.
    Architect extracts destination, then route_after_architect() sends to specialists.
    """
    from app.debug_utils import _debug_graph

    # Short-circuit responses (GREETING/RESET) skip to synthesizer
    if state.metadata.get("short_circuit_response"):
        return "synthesizer"

    has_destination = bool(state.trip_plan.destination)

    # CRITICAL FIX: If specialists are queued BUT destination is missing,
    # route to Architect FIRST to extract destination from user message.
    # Specialists without destination produce generic/empty content.
    # @see trace: "LOCAL_EXPERT Skipped - no destination set"
    if state.active_specialist and not has_destination:
        _debug_graph(
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
    from app.debug_utils import _debug_graph

    # Check if there are more specialists to process
    # NOTE: We just peek, we don't pop - the specialist node handles that
    if state.pending_specialists:
        next_specialist = state.pending_specialists[0]
        _debug_graph(
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
        _debug_graph("Specialist done, routing to synthesizer (speculative intent - preload only)")
        return "synthesizer"

    # Check if this is a "booking" intent (Build Plan button) or just general chat
    is_booking_intent = state.intent == "booking"
    is_generate_trigger = state.metadata.get("is_generate_trigger", False)

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
            _debug_graph(
                f"Specialist done, routing to logistics ({reason}) - "
                "note: flights disabled, no origin"
            )
        else:
            _debug_graph(f"Specialist done, routing to logistics ({reason})")
        return "logistics"

    # Log skip reason for debugging
    if has_dates and not has_destination:
        _debug_graph("Specialist done, skipping logistics (no destination set)")

    # General intent without dates - skip tile fetching, go to architect for extraction
    _debug_graph("Specialist done, skipping logistics, routing to architect (no dates)")
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
    from app.debug_utils import _debug_graph

    has_destination = bool(state.trip_plan.destination)
    has_origin = bool(state.trip_plan.origin)
    has_dates = bool(state.trip_plan.start_date)
    has_tiles = bool(state.tiles)
    is_speculative = state.intent == "speculative"
    local_expert_ran = state.metadata.get("local_expert_ran", False)  # Persistent flag
    logistics_attempted = state.metadata.get("logistics_attempted", False)

    # SPECIALIST DISPATCH: If specialists were queued but deferred (no destination),
    # now route to them since architect has extracted the destination.
    # @see route_after_router - defers specialists when destination is missing
    if has_destination and state.active_specialist:
        if state.active_specialist == "local_expert":
            _debug_graph(
                f"Architect done, dispatching deferred local_expert "
                f"(destination={state.trip_plan.destination})"
            )
            return "local_expert"
        else:
            _debug_graph(
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
        _debug_graph(
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
            _debug_graph(
                "Architect done, routing to logistics "
                "(dates+destination set, hotels only - no origin)"
            )
        else:
            _debug_graph("Architect done, routing to logistics (dates set, no tiles yet)")
        return "logistics"

    # Skip logistics if no destination - can't search anything
    if has_dates and not has_tiles and not has_destination:
        _debug_graph("Architect done, skipping logistics (no destination set)")

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


def route_after_guard(state: GraphState) -> Literal["architect", "synthesizer"]:
    """
    Route based on constraint violations.

    Logic:
    1. Route Errors (Rome->Rome, Atlantis) → Synthesizer (skip auto-fix)
       NOTE: Rollback happens in constraint_guard node, not here.
    2. Budget/Time Errors → Architect (auto-fix loop, max 1 retry)
    3. No Errors → Synthesizer (success)
    """
    has_blocking = state.metadata.get("has_blocking_violations", False)
    retry_count = state.guard_retry_count
    violations = state.metadata.get("constraint_violations", [])

    # 1. ROUTE ERROR SHORT-CIRCUIT
    # Route errors are unfixable by Architect - skip auto-fix loop.
    # Rollback already happened in constraint_guard node.
    is_route_error = any(v.get("category") == "route" for v in violations)
    if is_route_error:
        logger.debug("Route error detected - skipping auto-fix, going to Synthesizer")
        return "synthesizer"

    # 2. OPTIMIZATION AUTO-FIX (Budget/Schedule - Safe to retry)
    if has_blocking and retry_count < 1:
        logger.debug(f"Auto-fix loop triggered: routing back to Architect (retry {retry_count})")
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
    # GREETING/RESET short-circuits skip directly to Synthesizer
    workflow.add_conditional_edges(
        "router",
        route_after_router,
        {
            "specialist": "specialist",
            "local_expert": "local_expert",
            "architect": "architect",
            "synthesizer": "synthesizer",  # For GREETING/RESET short-circuits
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

    # Logistics → Architect (always)
    # Logistics sanitizes flight data, then Architect builds the plan
    workflow.add_edge("logistics", "architect")

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
# Execution Interface (V1-Compatible)
# =============================================================================


async def run_turn(
    user_message: str,
    session_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Run a single turn of the conversation (V1-compatible interface).

    This is the main entry point for main.py. Returns a dict with:
    - assistant_message: The response text
    - suggested_responses: Quick reply options
    - session_state: Updated state for persistence
    - branches: Empty list (not used)
    - trip_inputs: Extracted trip parameters
    - ready_to_generate: Whether plan is complete

    Args:
        user_message: User's message text
        session_state: Optional previous state to continue from

    Returns:
        V1-compatible result dict
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

    # Run the graph
    try:
        result = await graph.ainvoke(state)
        # LangGraph returns dict, convert back to Pydantic
        if isinstance(result, dict):
            result_state = GraphState(**result)
        else:
            result_state = result
    except Exception as e:
        logger.error(f"Graph execution failed: {e}")
        raise

    # Convert result to V1 format
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
    from langchain_core.messages import HumanMessage

    # PANIC BUTTON - non-LLM kill switch (must be first!)
    if _is_panic_command(user_message):
        logger.info(f"Panic button triggered (streaming): '{user_message}'")
        reset_response = _create_reset_response()
        yield {"type": "token", "data": reset_response["assistant_message"]}
        yield {"type": "complete", "data": reset_response}
        return

    # Get compiled graph
    graph = get_or_create_graph()

    # Restore state from session
    state = _restore_graph_state(session_state)

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

                    # Logic Terminal: Emit routing decision when router completes (DS Section 19.C)
                    # This creates the ">> ROUTING: DIVING" line in the frontend terminal
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

        yield {
            "type": "complete",
            "data": final_result,
        }

    except Exception as e:
        logger.error(f"Streaming execution failed: {e}")
        # Emit error event but don't re-raise to ensure generator completes cleanly
        yield {"type": "error", "message": str(e)}


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
    """
    Ensure local_expert/general is always at index 0 (anchor rule).

    This fixes the ordering flip bug where filter+append pattern
    reverses section order when local_expert runs twice.
    """
    anchor_types = {"local_expert", "general"}
    anchors = [s for s in sections if s.get("specialist_type") in anchor_types]
    others = [s for s in sections if s.get("specialist_type") not in anchor_types]
    return anchors + others


def _format_result(
    state: GraphState,
    original_session_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Format result state for main.py response."""
    from app.debug_utils import _debug_graph
    from app.planner.state import trip_plan_is_ready

    trip_inputs = _trip_plan_to_trip_inputs(state.trip_plan)
    # NOTE: session_state is captured AFTER metadata updates (see below)

    # ==========================================================================
    # Merge extracted settings into trip_inputs (from NL command parsing)
    # ==========================================================================
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

    # ==========================================================================
    # BLOCKING VIOLATION CHECK
    # When there's a blocking constraint violation (e.g., SAME_CITY_ERROR),
    # don't show strategy sections or tiles - return to S0_BOOTSTRAP state.
    # The error message from synthesizer tells user what went wrong.
    # ==========================================================================
    has_blocking_violations = state.metadata.get("has_blocking_violations", False)
    if has_blocking_violations:
        logger.warning("[_format_result] Blocking violations detected - clearing tiles/sections")
        # Clear tiles and strategy sections - user needs to fix the error first
        flattened_tiles = {}
        plan_view_state = "S0_BOOTSTRAP"
        # Clear strategy sections from metadata so they don't persist
        state.metadata["strategy_sections"] = []
        state.metadata["executed_strategy_topics"] = []
        # Clear tiles so they don't persist in session
        state.tiles = {}
    else:
        # Normal path - flatten tiles for frontend
        flattened_tiles = _flatten_tiles_to_id_map(state.tiles)
        plan_view_state = _compute_plan_view_state(state)

    logger.info(
        f"_format_result: plan_view_state={plan_view_state}, "
        f"flattened_tiles_count={len(flattened_tiles)}, "
        f"raw_tiles_count={sum(len(v) for v in state.tiles.values()) if state.tiles else 0}"
    )

    # Generate strategy sections from tiles if not already present
    strategy_sections = state.metadata.get("strategy_sections", [])
    executed_topics = state.metadata.get("executed_strategy_topics", [])

    # DEBUG: Log existing sections
    section_types = [s.get("specialist_type") for s in strategy_sections]
    _debug_graph(
        f"_format_result: BEFORE - {len(strategy_sections)} sections, " f"types={section_types}"
    )
    for s in strategy_sections:
        content_count = len(s.get("content_added", []))
        constraint_count = len(s.get("constraints_applied", []))
        _debug_graph(
            f"  Section '{s.get('specialist_type')}': "
            f"content_added={content_count}, constraints={constraint_count}"
        )

    # Build strategy section for current specialist (accumulates with existing sections)
    # Use last_executed_specialist as fallback since active_specialist is cleared after execution
    last_specialist = state.metadata.get("last_executed_specialist")
    specialist_type = state.active_specialist or last_specialist or "general"

    _debug_graph(
        f"_format_result: active_specialist={state.active_specialist}, "
        f"last_specialist={last_specialist}, specialist_type={specialist_type}"
    )

    # Check if we need to create/update a section for this specialist
    # FIX: Check if section ALREADY EXISTS (not just type) - defensive against
    # nodes that fail silently. This prevents silent failures when a node
    # doesn't create its expected section.
    # @see docs/plan_graph_analysis.md - Nodes should not fail silently
    existing_types = [s.get("specialist_type") for s in strategy_sections]
    specialist_already_has_section = specialist_type in existing_types

    needs_section = (
        flattened_tiles
        # Only skip if the section ALREADY EXISTS in strategy_sections
        and not specialist_already_has_section
        and not (
            specialist_type == "general" and last_specialist
        )  # Don't create general if specialist ran
    )
    _debug_graph(
        f"_format_result: needs_section={needs_section} "
        f"(flattened_tiles={bool(flattened_tiles)})"
    )

    # CRITICAL FIX: Enrich EXISTING specialist sections even when needs_section=False
    # This ensures diving/hiking/skiing sections get hero_image, one_liner, principles
    # even before tiles are fetched (e.g., user hasn't set origin yet)
    # @see docs/ux_unified_architecture.md - Niche specialists need rich data for UI
    strategy_sections = list(strategy_sections)  # Make a copy for mutation
    plan = state.trip_plan
    for section in strategy_sections:
        section_type = section.get("specialist_type")
        # Skip general/local_expert - they have their own logic
        if section_type in ("general", "local_expert", None):
            continue

        # ENRICH: Add hero_image if missing
        if not section.get("hero_image"):
            # Try to get from content_added first
            hero_img = None
            for item in section.get("content_added", []):
                if item.get("image_url"):
                    hero_img = item["image_url"]
                    break
            # Fallback to curated placeholder
            if not hero_img:
                hero_img = get_hero_image(section_type, plan.destination)
            section["hero_image"] = hero_img

        # ENRICH: Add one_liner if missing
        if not section.get("one_liner"):
            constraint_count = len(section.get("constraints_applied", []))
            if constraint_count > 0:
                suffix = "s" if constraint_count > 1 else ""
                section["one_liner"] = (
                    f"{section_type.title()} mode active. "
                    f"{constraint_count} safety constraint{suffix} applied."
                )
            else:
                section["one_liner"] = (
                    f"{section_type.title()} recommendations for "
                    f"{plan.destination or 'your destination'}"
                )
            # Also set editorial_one_liner for niche specialists
            section["editorial_one_liner"] = section["one_liner"]

        # ENRICH: Add principles if missing or empty
        if not section.get("principles"):
            principles = []
            # 1. Try from constraints
            for c in section.get("constraints_applied", [])[:4]:
                if c.get("reason"):
                    principles.append(c["reason"])
                else:
                    rule_text = c.get("rule", "").replace("_", " ").title()
                    principles.append(f"{rule_text} applied")
            # 2. Fallback to domain defaults
            if not principles:
                domain_defaults = {
                    "diving": [
                        "24-hour no-fly buffer after dives",
                        "Depth and time limits for safe diving",
                        "Equipment and certification requirements",
                    ],
                    "hiking": [
                        "Altitude acclimatization schedule",
                        "Daily elevation gain limits",
                        "Rest day planning",
                    ],
                    "skiing": [
                        "Slope difficulty progression",
                        "Weather window optimization",
                        "Equipment rental coordination",
                    ],
                }
                principles = domain_defaults.get(
                    section_type,
                    [
                        f"{section_type.title()} safety protocols active",
                        "Expert recommendations applied",
                        "Optimized scheduling",
                    ],
                )
            section["principles"] = principles

    if needs_section:
        # Build bullets from available data
        bullets = []
        plan = state.trip_plan
        if plan.destination:
            bullets.append(f"Trip to {plan.destination}")
        if plan.start_date:
            date_str = plan.start_date
            if plan.end_date:
                date_str = f"{plan.start_date} to {plan.end_date}"
            bullets.append(f"Dates: {date_str}")
        if plan.adults or plan.children:
            travelers = plan.adults + plan.children
            bullets.append(f"{travelers} traveler{'s' if travelers > 1 else ''}")

        # Add tile summary
        hotels_count = len(
            [
                t
                for t in flattened_tiles.values()
                if t.get("type") in ("hotel", "stay", "accommodation")
            ]
        )
        flights_count = len([t for t in flattened_tiles.values() if t.get("type") == "flight"])
        activities_count = len(
            [
                t
                for t in flattened_tiles.values()
                if t.get("type") in ("activity", "experience", "tour", "attraction")
            ]
        )

        if hotels_count:
            bullets.append(f"{hotels_count} accommodation options found")
        if flights_count:
            bullets.append(f"{flights_count} flight options found")
        if activities_count:
            bullets.append(f"{activities_count} activities available")

        # Build trip_summary for General Agent
        travelers_count = (plan.adults or 1) + (plan.children or 0)
        trip_summary = {
            "destination": plan.destination or "Unknown",
            "dates": (
                f"{plan.start_date} – {plan.end_date}"
                if plan.start_date and plan.end_date
                else plan.start_date or "TBD"
            ),
            "travelers": f"{travelers_count} traveler{'s' if travelers_count > 1 else ''}",
        }

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
                    # Merge in image_url/coordinates if present in specialist section
                    # but missing from our content
                    for ca in content_added:
                        if ca.get("title") == item.get("title"):
                            if item.get("image_url") and not ca.get("image_url"):
                                ca["image_url"] = item.get("image_url")
                            if item.get("coordinates") and not ca.get("coordinates"):
                                ca["coordinates"] = item.get("coordinates")

        # Build must_dos from itinerary_blocks (actual specialist recommendations)
        # NOT from generic trip parameters
        must_dos = []
        for block in plan.itinerary_blocks:
            if block.title and block.title not in must_dos:
                must_dos.append(block.title)
        must_dos = must_dos[:5]  # Limit to 5

        # Build one-liner based on specialist type
        # General: Editorial "magazine" style, evocative
        # Specialist: Technical, domain-focused
        if specialist_type == "general":
            # Try to get editorial summary from Architect metadata (LLM-generated)
            editorial_summary = state.metadata.get("editorial_summary")
            if editorial_summary:
                one_liner = editorial_summary
            else:
                # Fallback: Generate a more evocative one-liner than generic
                if plan.origin and plan.destination:
                    one_liner = f"A journey from {plan.origin} to {plan.destination} awaits"
                elif plan.destination:
                    one_liner = f"Your adventure to {plan.destination} is taking shape"
                else:
                    one_liner = "Your personalized trip is ready to customize"
        elif specialist_type == "local_expert":
            one_liner = f"Local logistics and tips for {plan.destination or 'your destination'}"
        else:
            one_liner = (
                f"{specialist_type.title()} recommendations for "
                f"{plan.destination or 'your destination'}"
            )

        # Build principles based on specialist type
        # General: Trip highlights (destinations, flights, hotels)
        # Niche: Domain-specific strategy principles from constraints/content
        principles = []
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
                # Calculate trip duration
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
            # 1. Get principles from specialist metadata (LLM-generated)
            specialist_output = state.metadata.get("specialist_output", {})
            llm_principles = specialist_output.get("principles", [])
            if llm_principles:
                principles.extend(llm_principles[:5])

            # 2. Fallback: Generate principles from constraints
            if not principles and plan.constraints:
                for c in plan.constraints[:4]:
                    # Convert constraint to principle
                    if c.reason:
                        principles.append(c.reason)
                    else:
                        # Format the rule nicely
                        rule_text = c.rule.replace("_", " ").title()
                        principles.append(f"{rule_text} applied")

            # 3. Fallback: Domain-specific defaults
            if not principles:
                domain_defaults = {
                    "diving": [
                        "24-hour no-fly buffer after dives",
                        "Depth and time limits for safe diving",
                        "Equipment and certification requirements",
                    ],
                    "hiking": [
                        "Altitude acclimatization schedule",
                        "Daily elevation gain limits",
                        "Rest day planning",
                    ],
                    "skiing": [
                        "Slope difficulty progression",
                        "Weather window optimization",
                        "Equipment rental coordination",
                    ],
                }
                principles = domain_defaults.get(
                    specialist_type,
                    [
                        f"{specialist_type.title()} safety protocols active",
                        "Expert recommendations applied",
                        "Optimized scheduling",
                    ],
                )

        # Build vibe_trio for General and Local Expert (destination images)
        # @see docs/ux_unified_architecture.md Section XII - Magazine Style
        # Local Expert also needs images for the magazine layout
        vibe_trio = []
        if specialist_type in ("general", "local_expert"):
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
                    # No destination yet - use generic travel vibes
                    extracted_vibes = [
                        {"label": "Inspiration", "query": "travel inspiration"},
                        {"label": "Adventure", "query": "adventure travel"},
                        {"label": "Relaxation", "query": "luxury resort"},
                    ]

            # 3. Build vibe_trio with curated images (max 3)
            for idx, vibe in enumerate(extracted_vibes[:3]):
                label = vibe.get("label", "Vibe")
                category = (
                    "culture"
                    if "culture" in label.lower()
                    else "adventure" if "adventure" in label.lower() else "destination"
                )
                vibe_trio.append(
                    {
                        "label": label,
                        "image_url": vibe.get("image_url")
                        or get_hero_image(category, f"{plan.destination}-{label}-{idx}"),
                    }
                )

        # Build hero_image for Niche Specialists (single focused action shot)
        # @see docs/ux_unified_architecture.md Section XII - Activity Layout
        hero_image = None
        if specialist_type not in ("general", "local_expert"):
            # 1. Try to get from content_added (first item with image)
            for item in content_added:
                if item.get("image_url"):
                    hero_image = item["image_url"]
                    break

            # 2. Fallback: Use curated placeholder image
            if not hero_image:
                hero_image = get_hero_image(specialist_type, plan.destination)

        new_section = {
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
            # Feasibility state from specialist output (for Red/Amber/Green card states)
            "feasibility_status": state.metadata.get("specialist_output", {}).get(
                "feasibility_status", "feasible"
            ),
            "feasibility_reason": state.metadata.get("specialist_output", {}).get(
                "feasibility_reason"
            ),
            "alternative_suggestion": state.metadata.get("specialist_output", {}).get(
                "alternative_suggestion"
            ),
        }

        # SINGLETON vs HISTORY LOGIC:
        # - General Agent: Singleton (update in place, always at index 0)
        # - Specialists: Append (accumulate, but deduplicate same specialist type)
        strategy_sections = list(strategy_sections)  # Make a copy

        if specialist_type == "general":
            # SINGLETON: Remove existing general section, insert at front
            strategy_sections = [
                s for s in strategy_sections if s.get("specialist_type") != "general"
            ]
            strategy_sections.insert(0, new_section)  # Keep General at top
        else:
            # APPENDABLE: Remove duplicate of same specialist type, then append
            strategy_sections = [
                s for s in strategy_sections if s.get("specialist_type") != specialist_type
            ]
            strategy_sections.append(new_section)

        # Track executed specialist in executed_topics (deduplicates automatically)
        if specialist_type not in executed_topics:
            executed_topics = list(executed_topics)  # Make a copy
            executed_topics.append(specialist_type)

    # CRITICAL: Write accumulated sections back to state.metadata for persistence
    # This ensures sections are preserved across turns via session_state
    # Apply anchor rule: local_expert/general always at index 0
    # BUT: Skip persistence when there are blocking violations (user needs to fix error first)
    if not has_blocking_violations:
        state.metadata["strategy_sections"] = _sort_sections_anchor_first(strategy_sections)
        state.metadata["executed_strategy_topics"] = executed_topics
    else:
        # Keep sections/topics cleared (set earlier in blocking violations check)
        strategy_sections = []
        executed_topics = []

    # CRITICAL: Capture session_state AFTER metadata is updated (not before!)
    # This ensures strategy_sections are persisted for the next turn
    updated_session_state = _state_to_session_state(state)

    # DEBUG: Log what strategy_sections we're saving for next turn
    final_sections = state.metadata["strategy_sections"]
    saved_types = [s.get("specialist_type") for s in final_sections]
    _debug_graph(
        f"_format_result: Saving {len(final_sections)} "
        f"strategy_sections to session_state, types={saved_types}"
    )
    # Enhanced tracing: verify anchor rule was applied
    if saved_types and saved_types[0] not in ("local_expert", "general"):
        _debug_graph(
            f"⚠️ WARNING: Anchor rule violation! First section is '{saved_types[0]}', "
            f"expected 'local_expert' or 'general'"
        )

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
    }

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


async def clear_all_checkpoints() -> None:
    """Clear all checkpoints (no-op)."""
    pass


async def clear_response_caches() -> None:
    """Clear response caches (no-op)."""
    pass


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
