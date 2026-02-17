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
import logging
import os
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, Literal, Optional

from langgraph.graph import END, StateGraph

from app.planner.nodes.constraint_guard import constraint_guard
from app.planner.nodes.intent_router import intent_router
from app.planner.nodes.local_expert import local_expert
from app.planner.nodes.logistics_node import logistics_node
from app.planner.nodes.synthesizer import synthesizer
from app.planner.nodes.trip_architect import trip_architect
from app.planner.nodes.vertical_specialist import vertical_specialist
from app.planner.services.response_envelope import format_result
from app.planner.services.state_serde import (
    restore_graph_state,
)
from app.planner.state import GraphState, TripPlan, reset_turn_metadata
from app.planner.state.typed_meta import get_persistent_meta, get_turn_meta

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
    1. Any blocking constraint → Synthesizer (no architect retry)
    2. No blocking constraint → Synthesizer (success)

    Architect retry path is intentionally disabled until a deterministic auto-fix
    implementation exists for blocking violations.
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
    destination = "synthesizer"

    # Route decision logging - shows exactly what routing decision was made and why
    logger.info(
        f"[ROUTE] after_guard: blocking={has_blocking} unfixable={is_unfixable} "
        f"retry={retry_count} → {destination}"
    )

    return "synthesizer"


# =============================================================================
# Graph Definition
# =============================================================================


def create_optimized_graph() -> StateGraph:
    """
    Create the optimized 7-node graph.

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
    state = restore_graph_state(session_state)

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
    return format_result(result_state, session_state)


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
    state = restore_graph_state(session_state)

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
                    logger.warning(f"GraphState parse failed: {e}")
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
                            # Tag it so format_result knows parse failed
                            partial_state.metadata["_graph_state_parse_failed"] = True
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
        final_result = format_result(result_state, session_state)

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

        # Diagnostic: what's in the SSE payload the frontend receives
        _doc = final_result.get("document", {})
        _meta = getattr(result_state, "metadata", {}) if result_state is not None else {}
        logger.info(
            "[graph-complete-state] builder_success=%s conflict_count=%s "
            "emitted_plan_view_state=%s "
            "changed_fields=%s",
            _meta.get("last_builder_success"),
            len(_doc.get("constraint_violations") or []),
            _doc.get("plan_view_state"),
            _meta.get("changed_fields"),
        )
        logger.debug(
            f"[SSE_COMPLETE] suggestions={_doc.get('suggested_responses', [])[:3]} "
            f"meta={_doc.get('suggested_response_meta', [])[:2]} "
            f"tiles={len(_doc.get('tiles', {}))} "
            f"day_cards={len(_doc.get('itinerary_day_cards') or [])} "
            f"view_state={_doc.get('plan_view_state')}"
        )

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
    state = restore_graph_state(session_state)

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
_graph_lock = __import__("threading").Lock()


def get_or_create_graph():
    """Get or create the graph instance (singleton pattern)."""
    global _graph
    if _graph is None:
        with _graph_lock:
            if _graph is None:
                _graph = get_graph()
    return _graph


# =============================================================================
# Stub Functions for V1 Compatibility
# =============================================================================
# These functions are imported by main.py for compatibility.
# They provide safe no-op implementations to prevent import errors.


# Note: Admin util functions extracted to admin_utils.py
# Only clear_all_caches remains here (mutates module-level _graph)


async def clear_all_caches() -> None:
    """Clear all caches."""
    from app.planner.services.admin_utils import clear_response_caches

    global _graph
    _graph = None
    await clear_response_caches()
