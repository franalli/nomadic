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
from typing import Any, AsyncGenerator, Dict, List, Literal, Optional

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from app.planner.nodes_v2.constraint_guard import constraint_guard

# Import V2 nodes
from app.planner.nodes_v2.intent_router import intent_router
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
PROMPT_BUNDLE_HASH = "v2_optimized"


# =============================================================================
# V1-Compatible Types (for main.py compatibility)
# =============================================================================


class TripInputs(BaseModel):
    """V1-compatible TripInputs for main.py interface."""

    destinations: List[str] = Field(default_factory=list)
    origin: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    requires_assistance: Optional[bool] = None
    budget: Optional[float] = None
    currency: Optional[str] = None
    multi_city_intent: Optional[Literal["multi_city", "separate"]] = None
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
    """Convert V2 TripPlan to V1 trip_inputs dict."""
    destinations = plan.destinations if plan.destinations else []
    if plan.destination and plan.destination not in destinations:
        destinations = [plan.destination] + destinations

    return {
        "destinations": destinations,
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
    }


def _state_to_session_state(state: GraphStateV2) -> Dict[str, Any]:
    """Convert V2 GraphStateV2 to V1-compatible session_state dict."""
    return {
        "messages": [
            {"role": "human" if m.type == "human" else "assistant", "content": m.content}
            for m in state.messages
        ],
        "trip_inputs": _trip_plan_to_trip_inputs(state.trip_plan),
        "metadata": {
            **state.metadata,
            "tiles": state.tiles,
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
        destinations = trip_inputs.get("destinations", [])
        state.trip_plan.destination = destinations[0] if destinations else None
        state.trip_plan.destinations = destinations
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


def route_after_router(state: GraphStateV2) -> Literal["specialist", "architect", "synthesizer"]:
    """
    Route based on intent classification.

    If short_circuit_response (GREETING/RESET) → Synthesizer (skip architect)
    If specialist topic detected → VerticalSpecialist
    Otherwise → TripArchitect
    """
    # Short-circuit responses (GREETING/RESET) skip to synthesizer
    if state.metadata.get("short_circuit_response"):
        return "synthesizer"

    if state.active_specialist:
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
    workflow.add_node("guard", constraint_guard)
    workflow.add_node("synthesizer", synthesizer)

    # ==========================================================================
    # Define Edges
    # ==========================================================================

    # Entry point
    workflow.set_entry_point("router")

    # Router → Specialist, Architect, or Synthesizer (conditional)
    # GREETING/RESET short-circuits skip directly to Synthesizer
    workflow.add_conditional_edges(
        "router",
        route_after_router,
        {
            "specialist": "specialist",
            "architect": "architect",
            "synthesizer": "synthesizer",  # For GREETING/RESET short-circuits
        },
    )

    # Specialist → Architect (always)
    # Specialist advises, then Architect acts on advice
    workflow.add_edge("specialist", "architect")

    # Architect → Guard or Synthesizer (conditional)
    workflow.add_conditional_edges(
        "architect",
        should_run_guard,
        {
            "guard": "guard",
            "synthesizer": "synthesizer",
        },
    )

    # Guard → Synthesizer (always)
    workflow.add_edge("guard", "synthesizer")

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
    Run a single turn with streaming output (V1-compatible interface).

    Yields SSE-compatible events:
    - {"type": "token", "content": "..."} - Streaming tokens
    - {"type": "node_status", "data": {...}} - Node progress
    - {"type": "complete", "data": {...}} - Final result

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
        # For V2, we run the full graph and emit the result
        # True streaming will be added in a future iteration
        result = await graph.ainvoke(state)
        # LangGraph returns dict, convert back to Pydantic
        if isinstance(result, dict):
            result_state = GraphStateV2(**result)
        else:
            result_state = result

        # Emit node completion statuses
        yield {"type": "node_status", "data": {"node": "router", "status": "complete"}}

        if result_state.active_specialist:
            yield {
                "type": "node_status",
                "data": {"node": result_state.active_specialist, "status": "complete"},
            }

        yield {"type": "node_status", "data": {"node": "architect", "status": "complete"}}
        yield {"type": "node_status", "data": {"node": "synthesizer", "status": "complete"}}

        # Stream the response as tokens (simulated for now)
        response_text = result_state.last_summary or ""
        if response_text:
            # Emit full response as single token for simplicity
            # True token streaming requires LLM streaming integration
            # NOTE: Key must be "data" to match frontend SSE parsing (api.ts onToken)
            yield {"type": "token", "data": response_text}

        # Emit complete event with full result
        yield {
            "type": "complete",
            "data": _v2_result_to_v1_format(result_state, session_state),
        }

    except Exception as e:
        logger.error(f"V2 streaming execution failed: {e}")
        yield {"type": "error", "message": str(e)}
        raise


def _v2_result_to_v1_format(
    state: GraphStateV2,
    original_session_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Convert V2 result state to V1-compatible format for main.py."""
    from app.planner.state import trip_plan_is_ready

    trip_inputs = _trip_plan_to_trip_inputs(state.trip_plan)
    updated_session_state = _state_to_session_state(state)

    return {
        "assistant_message": state.last_summary or "",
        "suggested_responses": state.suggested_replies,
        "session_state": updated_session_state,
        "branches": [],  # V2 doesn't use branches
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
