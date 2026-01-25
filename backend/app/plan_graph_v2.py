"""
Plan Graph V2 - Simplified 6-Node "Core + Specialist" Architecture.

This is the optimized graph that replaces the 19-node architecture:
- 19 nodes → 6 nodes
- 27 prompts → 10 prompts
- 60% complexity reduction, 100% capability preserved

Nodes:
1. IntentRouter - LLM (Fast): Classify intent
2. TripArchitect - LLM (Smart): The Core, manages TripPlan
3. VerticalSpecialist - LLM (Expert): Domain logic (diving/hiking/skiing)
4. ConstraintGuard - Python: Deterministic validation
5. Synthesizer - LLM (Writer): Unified response generation

Key Principles:
- "Flights/Hotels are NOT Agents" - They are data fetchers (TileService tool)
- "Diving IS an Agent" - It requires domain logic (VerticalSpecialist)
- "Architect sees the whole picture" - Avoids context fracture

Usage:
    from app.plan_graph_v2 import run_turn, run_turn_streaming
    result = await run_turn(user_message, session_state)
"""

import logging
import os
from typing import Any, AsyncGenerator, Dict, Literal, Optional

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from app.planner.nodes_v2.constraint_guard import constraint_guard

# Import V2 nodes
from app.planner.nodes_v2.intent_router import intent_router
from app.planner.nodes_v2.local_expert import local_expert
from app.planner.nodes_v2.synthesizer import synthesizer
from app.planner.nodes_v2.trip_architect import trip_architect
from app.planner.nodes_v2.vertical_specialist import vertical_specialist
from app.planner.state import GraphStateV2, TripPlan

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
PLANNER_BUILD_ID = "v2.0.0"
CACHE_SCHEMA_VERSION = "v2"


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


PROMPT_BUNDLE_HASH = "v2_optimized"


# =============================================================================
# V1-Compatible Types (for main.py compatibility)
# =============================================================================


class TripInputs(BaseModel):
    """V1-compatible TripInputs for main.py interface."""

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


# Alias for backward compatibility
GraphState = GraphStateV2


def _trip_plan_to_trip_inputs(plan: TripPlan) -> Dict[str, Any]:
    """Convert V2 TripPlan to V1 trip_inputs dict with legacy display fields."""
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


def _state_to_session_state(state: GraphStateV2) -> Dict[str, Any]:
    """Convert V2 GraphStateV2 to V1-compatible session_state dict."""
    # Keep tiles in CATEGORY format for V2 state restoration
    # V2 stores: {"hotels": [tile1, tile2], "flights": [tile3]}
    # We preserve this format so state can be restored correctly on next request

    return {
        "messages": [
            {"role": "human" if m.type == "human" else "assistant", "content": m.content}
            for m in state.messages
        ],
        "trip_inputs": _trip_plan_to_trip_inputs(state.trip_plan),
        "metadata": {
            **state.metadata,
            "tiles": state.tiles,  # Keep in category format for V2 restoration
            "active_specialist": state.active_specialist,
            "constraints_violated": state.constraints_violated,
        },
    }


def _session_state_to_v2_state(session_state: Optional[Dict[str, Any]]) -> GraphStateV2:
    """Convert V1 session_state dict to V2 GraphStateV2."""
    from langchain_core.messages import AIMessage, HumanMessage

    if not session_state:
        return GraphStateV2()

    state = GraphStateV2()

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
    state.tiles = metadata.get("tiles", {})
    state.active_specialist = metadata.get("active_specialist")

    return state


# =============================================================================
# Routing Functions
# =============================================================================


def route_after_router(
    state: GraphStateV2,
) -> Literal["specialist", "local_expert", "architect", "synthesizer"]:
    """
    Route based on intent classification.

    If short_circuit_response (GREETING/RESET) → Synthesizer (skip architect)
    If specialist topic detected → VerticalSpecialist or LocalExpert
    Otherwise → TripArchitect
    """
    # Short-circuit responses (GREETING/RESET) skip to synthesizer
    if state.metadata.get("short_circuit_response"):
        return "synthesizer"

    if state.active_specialist:
        # Route to local_expert node if that's the active specialist
        if state.active_specialist == "local_expert":
            return "local_expert"
        return "specialist"
    return "architect"


def should_run_guard(state: GraphStateV2) -> Literal["guard", "synthesizer"]:
    """
    Determine if we should run constraint checking.

    Run guard if:
    - We have tiles to validate
    - We have specialist constraints to check
    """
    if state.tiles or state.trip_plan.constraints:
        return "guard"
    return "synthesizer"


def route_after_guard(state: GraphStateV2) -> Literal["architect", "synthesizer"]:
    """
    Route based on constraint violations (Auto-Fix Loop).

    If blocking violations AND retry_count < 1 → Architect (for auto-fix)
    Otherwise → Synthesizer

    This allows the Architect to self-correct one time before showing
    errors to the user. The user never sees "Budget exceeded", they just
    get a corrected plan with cheaper options.
    """
    has_blocking = state.metadata.get("has_blocking_violations", False)
    retry_count = state.guard_retry_count

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
    # Initialize the graph with V2 state
    workflow = StateGraph(GraphStateV2)

    # ==========================================================================
    # Add Nodes
    # ==========================================================================
    workflow.add_node("router", intent_router)
    workflow.add_node("architect", trip_architect)
    workflow.add_node("specialist", vertical_specialist)
    workflow.add_node("local_expert", local_expert)
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

    # Specialist → Architect (always)
    # Specialist advises, then Architect acts on advice
    workflow.add_edge("specialist", "architect")

    # LocalExpert → Architect (always)
    # LocalExpert provides logistics, then Architect continues
    workflow.add_edge("local_expert", "architect")

    # Architect → Guard or Synthesizer (conditional)
    workflow.add_conditional_edges(
        "architect",
        should_run_guard,
        {
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
    - branches: Empty list (V2 doesn't use branches)
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
    graph = get_or_create_v2_graph()

    # Convert V1 session state to V2
    state = _session_state_to_v2_state(session_state)

    # Add user message
    state.messages.append(HumanMessage(content=user_message))

    # Run the graph
    try:
        result = await graph.ainvoke(state)
        # LangGraph returns dict, convert back to Pydantic
        if isinstance(result, dict):
            result_state = GraphStateV2(**result)
        else:
            result_state = result
    except Exception as e:
        logger.error(f"V2 graph execution failed: {e}")
        raise

    # Convert result to V1 format
    return _v2_result_to_v1_format(result_state, session_state)


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
    graph = get_or_create_v2_graph()

    # Convert V1 session state to V2
    state = _session_state_to_v2_state(session_state)

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
                    # Always capture the latest output - it might be a dict or GraphStateV2
                    final_output = output

        # Emit final node completion
        if current_node:
            yield {
                "type": "node_status",
                "data": {"node": current_node, "status": "completed"},
            }

        # Convert final output to GraphStateV2
        if final_output is not None:
            if isinstance(final_output, dict):
                try:
                    result_state = GraphStateV2(**final_output)
                except Exception as e:
                    logger.warning(f"Failed to parse final output as GraphStateV2: {e}")
            elif isinstance(final_output, GraphStateV2):
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
        final_result = _v2_result_to_v1_format(result_state, session_state)

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
        logger.error(f"V2 streaming execution failed: {e}")
        # Emit error event but don't re-raise to ensure generator completes cleanly
        yield {"type": "error", "message": str(e)}


def _compute_plan_view_state(state: GraphStateV2) -> str:
    """
    Compute plan_view_state for frontend stage rendering.

    V2 simplified state machine:
    - S0_BOOTSTRAP: Show "Finish setup" checklist. CTA enabled when dest+dates set.
    - S2_STRATEGY_READY: Tiles loaded. Show strategy/tiles.
    - S3_*: Itinerary states (handled by expand-itinerary endpoint)

    S1_FRAMING is deprecated in V2 - we stay in S0_BOOTSTRAP until tiles load.
    """
    # S2: Has tiles → strategy ready
    if state.tiles and any(state.tiles.values()):
        return "S2_STRATEGY_READY"

    # S0: No tiles yet → show setup checklist (CTA enabled/disabled based on dest+dates)
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


def _v2_result_to_v1_format(
    state: GraphStateV2,
    original_session_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Convert V2 result state to V1-compatible format for main.py."""
    from datetime import datetime

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

    # Flatten tiles for frontend
    flattened_tiles = _flatten_tiles_to_id_map(state.tiles)
    plan_view_state = _compute_plan_view_state(state)

    logger.info(
        f"_v2_result_to_v1_format: plan_view_state={plan_view_state}, "
        f"flattened_tiles_count={len(flattened_tiles)}, "
        f"raw_tiles_count={sum(len(v) for v in state.tiles.values()) if state.tiles else 0}"
    )

    # Generate strategy sections from tiles if not already present
    strategy_sections = state.metadata.get("strategy_sections", [])
    executed_topics = state.metadata.get("executed_strategy_topics", [])

    # Build strategy section for current specialist (accumulates with existing sections)
    specialist_type = state.active_specialist or "general"

    # Check if we need to create/update a section for this specialist
    needs_section = flattened_tiles and specialist_type not in [
        s.get("specialist_type") for s in strategy_sections
    ]

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

        # Extract content added from itinerary_blocks
        content_added = []
        for block in plan.itinerary_blocks:
            content_added.append(
                {
                    "title": block.title,
                    "day": block.day,
                    "type": block.type,
                }
            )

        new_section = {
            "id": f"strategy_{specialist_type}",
            "title": (
                f"{specialist_type.title()} Strategy"
                if specialist_type != "general"
                else "Trip Strategy"
            ),
            "subtitle": plan.destination,
            "specialist_type": specialist_type,
            "one_liner": (
                f"Your trip to {plan.destination or 'your destination'} is ready to customize"
            ),
            "bullets": bullets,
            "principles": [],
            "must_dos": bullets[:5],
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
    state.metadata["strategy_sections"] = strategy_sections
    state.metadata["executed_strategy_topics"] = executed_topics

    # CRITICAL: Capture session_state AFTER metadata is updated (not before!)
    # This ensures strategy_sections are persisted for the next turn
    updated_session_state = _state_to_session_state(state)

    # Build document object matching PlanDocumentData type expected by frontend
    document = {
        "trip_context_id": None,
        "trip_inputs": trip_inputs,
        "branches": [],  # V2 doesn't use branches
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


async def run_turn_v2(
    graph: Any,
    user_message: str,
    session_state: Optional[Dict[str, Any]] = None,
) -> GraphStateV2:
    """
    Run a single turn (V2-native interface).

    For internal use - prefer run_turn() for compatibility.
    """
    from langchain_core.messages import HumanMessage

    # Convert session state to V2
    state = _session_state_to_v2_state(session_state)

    # Add user message
    state.messages.append(HumanMessage(content=user_message))

    # Run the graph
    result = await graph.ainvoke(state)

    # LangGraph returns dict, convert back to Pydantic if needed
    if isinstance(result, dict):
        result = GraphStateV2(**result)

    return result


def get_response_from_state(state: GraphStateV2) -> Dict[str, Any]:
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


def get_v2_graph():
    """
    Factory function to get a compiled V2 graph.

    Usage:
        graph = get_v2_graph()
        result = await run_turn_v2(graph, "I want to go diving in Bali")
    """
    workflow = create_optimized_graph()
    return compile_graph(workflow)


# =============================================================================
# Module-level graph instance (lazy initialization)
# =============================================================================

_v2_graph = None


def get_or_create_v2_graph():
    """Get or create the V2 graph instance (singleton pattern)."""
    global _v2_graph
    if _v2_graph is None:
        _v2_graph = get_v2_graph()
    return _v2_graph


# =============================================================================
# Stub Functions for V1 Compatibility
# =============================================================================
# These functions are imported by main.py but may not be needed in V2.
# They provide safe no-op implementations to prevent import errors.


def get_planner_debug_info() -> Dict[str, Any]:
    """Return debug info for V2 planner."""
    return {
        "version": "v2",
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
        "version": "v2",
    }


def prewarm_prompts() -> Dict[str, Any]:
    """Pre-warm prompts (no-op in V2, prompts are loaded on demand)."""
    return {
        "prompts_warmed": 0,
        "templates_loaded": 5,  # V2 has ~5 prompt templates
        "warmup_ms": 0,
    }


def validate_template_coverage() -> Dict[str, Any]:
    """Validate all templates are covered (always valid in V2)."""
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
    global _v2_graph
    _v2_graph = None


async def clear_all_checkpoints() -> None:
    """Clear all checkpoints (no-op in V2)."""
    pass


async def clear_response_caches() -> None:
    """Clear response caches (no-op in V2)."""
    pass


async def clear_session_checkpoint(session_id: str) -> None:
    """Clear session checkpoint (no-op in V2)."""
    pass


def checkpoint_stats() -> Dict[str, Any]:
    """Return checkpoint statistics."""
    return {"count": 0, "version": "v2"}


def response_cache_stats() -> Dict[str, Any]:
    """Return response cache statistics."""
    return {"hits": 0, "misses": 0, "version": "v2"}


def prune_stale_checkpoints(max_age_hours: int = 24) -> int:
    """Prune stale checkpoints (no-op in V2)."""
    return 0
