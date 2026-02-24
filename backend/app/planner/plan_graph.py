"""
Streaming core -- translates create_agent events into the SSE contract.

This module provides ``run_turn_streaming()``, the primary streaming entry
point for the planner agent.  It consumes ``astream_events(version="v2")``
from the compiled agent and yields event dicts that ``streaming.generate_sse()``
consumes:

- ``{"type": "token",       "data": str}``
- ``{"type": "node_status", "data": {...}}``
- ``{"type": "partial",     "data": {...}}``
- ``{"type": "complete",    "data": {...}}``
- ``{"type": "error",       "message": str}``

Integration requirements for ``streaming.py``:
- Error events use flat format ``{"type": "error", "message": "..."}`` (no ``data``
  wrapper), matching the contract that ``generate_sse()`` consumes.
- The ``complete`` event ``data.document`` dict must include ``plan_view_state``
  with proper S3 sub-states derived from builder metadata in ``turn_meta``.
- ``suggested_response_meta`` carries chip progression metadata (list of dicts),
  distinct from ``suggestion_chips`` which holds the full chip objects.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, Dict, Optional

from langchain_core.messages import AIMessage, HumanMessage

from app.planner.services.agent_runner import _get_agent
from app.planner.services.state_serde import (
    restore_agent_state,
    serialize_agent_state,
)

logger = logging.getLogger(__name__)

# Agent graph name -- must match the ``name`` kwarg in ``create_planner_agent()``.
_AGENT_GRAPH_NAME = "nomadic_planner"

# ---------------------------------------------------------------------------
# Tool status configuration
# ---------------------------------------------------------------------------
# Maps tool names to human-readable status metadata emitted as ``node_status``
# events.  The frontend progress indicator renders these as step indicators.

_TOOL_STATUS_MAP: Dict[str, Dict[str, Any]] = {
    "extract_trip_fields": {
        "label": "Reading your message...",
        "icon": "brain",
        "duration": 300,
    },
    "get_specialist_advice": {
        "label": "Consulting expert...",
        "icon": "star",
        "duration": 3000,
    },
    "get_local_intel": {
        "label": "Loading local knowledge...",
        "icon": "building",
        "duration": 50,
    },
    "search_tiles": {
        "label": "Searching flights & hotels...",
        "icon": "search",
        "duration": 2000,
    },
    "validate_plan": {
        "label": "Checking your plan...",
        "icon": "shield",
        "duration": 100,
    },
    "build_itinerary": {
        "label": "Building itinerary...",
        "icon": "calendar",
        "duration": 200,
    },
}

# Tools whose results should be emitted as ``partial`` events so the
# frontend can update the UI incrementally before the final response.
_TOOL_PARTIAL_KIND: Dict[str, str] = {
    "extract_trip_fields": "trip_inputs",
    "search_tiles": "tiles",
    "get_specialist_advice": "strategy_sections",
    "get_local_intel": "strategy_sections",
}


# ---------------------------------------------------------------------------
# Tool result extraction helpers
# ---------------------------------------------------------------------------


def _parse_tool_result(content: Any) -> Optional[Dict[str, Any]]:
    """Parse a tool message content string into a dict, or return None."""
    if isinstance(content, dict):
        return content
    if not content or not isinstance(content, str):
        return None
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _extract_partial_payload(
    tool_name: str,
    result_dict: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Build a partial event payload from a tool result, or return None.

    Only tools listed in ``_TOOL_PARTIAL_KIND`` produce partial events.
    The ``kind`` field tells the frontend which UI region to update:

    - ``trip_inputs``        -> setup bar / trip DNA
    - ``tiles``              -> tile carousel
    - ``strategy_sections``  -> strategy cards
    """
    kind = _TOOL_PARTIAL_KIND.get(tool_name)
    if kind is None:
        return None

    if kind == "trip_inputs":
        # Emit the trip_plan dict directly -- TurnLifecycleMiddleware has
        # already merged extracted fields into state by the time the
        # ToolMessage is emitted, but the raw result carries the delta.
        payload = {}
        for field in (
            "destination",
            "origin",
            "start_date",
            "end_date",
            "adults",
            "children",
            "budget",
            "currency",
            "origin_iata",
            "destination_iata",
        ):
            val = result_dict.get(field)
            if val is not None:
                payload[field] = val
        return {"kind": kind, "payload": payload} if payload else None

    if kind == "tiles":
        # Emit ID-keyed tiles to match document.tiles shape on the frontend.
        tiles: Dict[str, Any] = {}
        for category in ("flights", "hotels", "activities"):
            cat_tiles = result_dict.get(category)
            if not isinstance(cat_tiles, list):
                continue
            for tile in cat_tiles:
                if not isinstance(tile, dict):
                    continue
                tile_id = tile.get("id")
                if tile_id:
                    tiles[tile_id] = tile
        return {"kind": kind, "payload": tiles} if tiles else None

    if kind == "strategy_sections":
        # Specialist advice returns ``strategy_section`` (singular);
        # local intel returns ``section``.
        section = result_dict.get("strategy_section") or result_dict.get("section")
        if section:
            return {"kind": kind, "payload": [section]}
        return None

    return None


# ---------------------------------------------------------------------------
# S3 sub-state computation
# ---------------------------------------------------------------------------


def _compute_s3_view_state(turn_meta: Dict[str, Any], day_cards: list) -> str:
    """Derive the correct S3 sub-state from builder metadata in turn_meta.

    The build_itinerary tool merger in TurnLifecycleMiddleware stores
    builder result info in ``turn_meta``.  Use it to determine:

    - ``S3_ITINERARY_READY``   -- success=True, conflicts=0
    - ``S3_EDITING``           -- success=True, conflicts>0
    - ``S3_PARTIAL_CONFLICT``  -- success=False with partial cards
    - ``S3_BLOCKED``           -- success=False, no cards
    """
    builder_result = turn_meta.get("builder_result", {})
    builder_success = builder_result.get("success", True)
    # _merge_itinerary stores conflicts as a list; derive count from its length.
    conflicts = builder_result.get("conflicts", [])
    conflict_count = len(conflicts) if isinstance(conflicts, list) else 0

    if builder_success:
        if conflict_count > 0:
            return "S3_EDITING"
        return "S3_ITINERARY_READY"
    else:
        if day_cards:
            return "S3_PARTIAL_CONFLICT"
        return "S3_BLOCKED"


# ---------------------------------------------------------------------------
# Result envelope builder
# ---------------------------------------------------------------------------


def _build_complete_envelope(
    state: Dict[str, Any],
    assistant_message: str,
) -> Dict[str, Any]:
    """Build the ``complete`` event data dict matching streaming.py expectations."""
    serialized = serialize_agent_state(state)

    trip_plan: Dict[str, Any] = state.get("trip_plan", {})
    trip_settings: Dict[str, Any] = state.get("trip_settings", {})
    tiles: Dict[str, Any] = state.get("tiles", {})
    strategy_sections: list = state.get("strategy_sections", [])
    day_cards: list = state.get("day_cards", [])
    persistent_meta: Dict[str, Any] = state.get("persistent_meta", {})
    turn_meta: Dict[str, Any] = state.get("turn_meta", {})

    # Suggestion chips from SuggestionChipMiddleware
    suggestion_chips = persistent_meta.get("suggestion_chips", [])
    suggested_replies = [c.get("message", "") for c in suggestion_chips if isinstance(c, dict)]

    # Build trip_inputs from trip_plan + trip_settings
    trip_inputs: Dict[str, Any] = {}
    for field in (
        "destination",
        "origin",
        "origin_iata",
        "destination_iata",
        "start_date",
        "end_date",
        "adults",
        "children",
        "budget",
        "currency",
    ):
        val = trip_plan.get(field)
        if val is not None:
            trip_inputs[field] = val

    # Merge settings sub-dicts into trip_inputs for frontend
    for settings_field in (
        "booking_types",
        "flight_settings",
        "hotel_settings",
        "activity_settings",
        "transport_settings",
    ):
        val = trip_settings.get(settings_field)
        if val:
            trip_inputs[settings_field] = val

    # Determine ready_to_generate
    ready_to_generate = bool(
        trip_plan.get("destination") and trip_plan.get("start_date") and trip_plan.get("end_date")
    )

    # Compute plan_view_state with proper S3 sub-states
    has_core = bool(
        trip_plan.get("destination") and trip_plan.get("start_date") and trip_plan.get("end_date")
    )
    if not has_core:
        plan_view_state = "S0_BOOTSTRAP"
    elif day_cards:
        plan_view_state = _compute_s3_view_state(turn_meta, day_cards)
    elif tiles or strategy_sections:
        plan_view_state = "S2_STRATEGY_READY"
    else:
        plan_view_state = "S2_STRATEGY_READY" if has_core else "S0_BOOTSTRAP"

    # Executed topics from strategy sections
    executed_topics = list(
        {
            s.get("specialist_type")
            for s in strategy_sections
            if isinstance(s, dict) and s.get("specialist_type")
        }
    )

    # Validation result from turn_meta
    validation_result = turn_meta.get("validation_result", {})
    constraint_violations = validation_result.get("violations", [])
    # constraints_validated mirrors v1: list of constraint check names that ran
    constraints_validated = ["validate_plan"] if validation_result.get("valid") is not None else []

    # Blocking violation handling from turn_meta
    has_blocking = turn_meta.get("has_blocking_violations", False)
    blocking_violations = turn_meta.get("constraint_violations", [])
    if has_blocking and blocking_violations:
        constraint_violations = blocking_violations

    # Flatten tiles from category format to ID-based map
    flattened_tiles: Dict[str, Any] = {}
    for _category, tile_list in tiles.items():
        if not isinstance(tile_list, list):
            continue
        for tile in tile_list:
            if isinstance(tile, dict):
                tile_id = tile.get("id")
                if tile_id:
                    flattened_tiles[tile_id] = tile

    # Derive origin_just_set and tiles_replaced from turn_meta
    origin_just_set = bool(turn_meta.get("origin_just_set", False))
    tiles_replaced = bool(turn_meta.get("tiles_replaced", False))

    # Browseable activities from turn_meta (Tier 1 suppressed tiles)
    browseable_activities = turn_meta.get("browseable_activities", [])

    document: Dict[str, Any] = {
        "trip_context_id": None,
        "trip_inputs": trip_inputs,
        "branches": [],
        "tiles": flattened_tiles,
        "assistant_message": assistant_message,
        "ready_to_generate": ready_to_generate,
        "suggested_responses": suggested_replies,
        "suggested_response_meta": persistent_meta.get("suggestion_chip_meta", []),
        "suggestion_chips": suggestion_chips,
        "plan_view_state": plan_view_state,
        "strategy_sections": strategy_sections,
        "pending_strategy_topics": [],
        "executed_strategy_topics": executed_topics,
        "origin_just_set": origin_just_set,
        "tiles_replaced": tiles_replaced,
        "constraints_validated": constraints_validated,
        "constraint_violations": constraint_violations,
        "browseable_activities": browseable_activities,
        "itinerary_day_cards": day_cards if day_cards else None,
        "_debug": {},
    }

    return {
        "session_state": serialized,
        "assistant_message": assistant_message,
        "suggestion_chips": suggestion_chips,
        "suggested_responses": suggested_replies,
        "trip_inputs": trip_inputs,
        "branches": [],
        "ready_to_generate": ready_to_generate,
        "changes_made": True,
        "document": document,
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_turn_streaming(
    user_message: str,
    session_state: Optional[Dict[str, Any]] = None,
    doc_settings: Optional[Dict[str, Any]] = None,
    session_id: str = "",
) -> AsyncGenerator[Dict[str, Any], None]:
    """Streaming entry point for the planner agent.

    Yields SSE-compatible events consumed by ``streaming.generate_sse()``:

    - ``{"type": "token",       "data": str}``           -- streaming text chunks
    - ``{"type": "node_status", "data": {...}}``         -- tool execution status
    - ``{"type": "partial",     "data": {...}}``         -- incremental data
    - ``{"type": "complete",    "data": {...}}``         -- final result envelope
    - ``{"type": "error",       "message": str}``        -- errors (flat format)

    Parameters
    ----------
    user_message : str
        The user's chat message.
    session_state : dict | None
        Previously serialized session state, or None for a fresh conversation.
    doc_settings : dict | None
        User-owned settings from the document (activity_settings, booking_types,
        etc.).  Merged into ``trip_settings`` before the agent sees state.
    session_id : str
        Session identifier for logging and config threading.
    """
    wall_start = time.monotonic()

    # ------------------------------------------------------------------
    # 1. Restore agent state from session
    # ------------------------------------------------------------------
    state = restore_agent_state(session_state)

    # Merge doc_settings into trip_settings.
    if doc_settings:
        trip_settings = dict(state.get("trip_settings", {}))
        for field, value in doc_settings.items():
            if value is not None:
                trip_settings[field] = value
        state["trip_settings"] = trip_settings

    # Append the user message
    state["messages"].append(HumanMessage(content=user_message))

    logger.info(
        "[run_turn_streaming] session=%s, messages=%d, user=%r",
        session_id or "(none)",
        len(state["messages"]),
        user_message[:80],
    )

    # ------------------------------------------------------------------
    # 2. Get the agent and prepare config
    # ------------------------------------------------------------------
    agent = _get_agent()

    config: Dict[str, Any] = {
        "configurable": {"thread_id": session_id} if session_id else {},
    }

    # ------------------------------------------------------------------
    # 3. Stream events with timeout
    # ------------------------------------------------------------------
    STREAM_TIMEOUT_SECONDS = 60

    active_tool: Optional[str] = None
    assistant_chunks: list[str] = []
    final_state: Optional[Dict[str, Any]] = None

    # Track whether the current LLM invocation has issued tool calls.
    # When True, any interleaved text tokens are intermediate reasoning
    # (e.g. chain-of-thought before tool use) and must NOT be streamed.
    _current_invocation_has_tools = False

    try:
        async with asyncio.timeout(STREAM_TIMEOUT_SECONDS):
            async for event in agent.astream_events(
                state,
                config=config,
                version="v2",
            ):
                event_type = event.get("event")

                # ---------------------------------------------------------
                # Tool start -> emit node_status "started"
                # ---------------------------------------------------------
                if event_type == "on_tool_start":
                    tool_name = event.get("name", "")
                    active_tool = tool_name

                    status_meta = _TOOL_STATUS_MAP.get(tool_name, {})
                    yield {
                        "type": "node_status",
                        "data": {
                            "node": tool_name,
                            "status": "started",
                            "label": status_meta.get("label", tool_name),
                            "icon_key": status_meta.get("icon", "cog"),
                            "estimated_duration_ms": status_meta.get("duration", 1000),
                        },
                    }

                # ---------------------------------------------------------
                # Tool end -> emit partial + node_status "completed"
                # ---------------------------------------------------------
                elif event_type == "on_tool_end":
                    tool_name = event.get("name", active_tool or "")
                    output = event.get("data", {}).get("output")

                    # Parse tool result and emit partial if applicable
                    if output is not None:
                        # output may be a ToolMessage or raw content
                        content = output.content if hasattr(output, "content") else output
                        result_dict = _parse_tool_result(content)
                        if result_dict is not None:
                            partial = _extract_partial_payload(tool_name, result_dict)
                            if partial is not None:
                                yield {
                                    "type": "partial",
                                    "data": partial,
                                }

                    yield {
                        "type": "node_status",
                        "data": {
                            "node": tool_name,
                            "status": "completed",
                        },
                    }
                    active_tool = None

                # ---------------------------------------------------------
                # LLM streaming -> emit token events (final response only)
                # ---------------------------------------------------------
                elif event_type == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk is None:
                        continue

                    # Detect whether this chunk carries tool-call data.
                    # Once any tool_call_chunks appear in the current LLM
                    # invocation, all subsequent text from the SAME
                    # invocation is intermediate reasoning -- skip it.
                    has_tool_calls = False
                    if hasattr(chunk, "tool_call_chunks") and chunk.tool_call_chunks:
                        has_tool_calls = True
                    elif hasattr(chunk, "tool_calls") and chunk.tool_calls:
                        has_tool_calls = True

                    if has_tool_calls:
                        _current_invocation_has_tools = True
                        continue

                    # Skip text tokens from an invocation that already
                    # issued tool calls (intermediate reasoning).
                    if _current_invocation_has_tools:
                        continue

                    # Text content with no tool calls -> final response
                    content = getattr(chunk, "content", None)
                    if content:
                        assistant_chunks.append(content)
                        yield {"type": "token", "data": content}

                # ---------------------------------------------------------
                # Chat model start -> reset per-invocation tool flag
                # ---------------------------------------------------------
                elif event_type == "on_chat_model_start":
                    _current_invocation_has_tools = False

                # ---------------------------------------------------------
                # Chain end -> capture final agent state
                # ---------------------------------------------------------
                elif event_type == "on_chain_end":
                    # Only capture the top-level agent graph output, not
                    # intermediate chain_end events from tools or sub-chains.
                    ev_name = event.get("name", "")
                    output = event.get("data", {}).get("output")
                    if (
                        ev_name == _AGENT_GRAPH_NAME
                        and isinstance(output, dict)
                        and "messages" in output
                    ):
                        final_state = output

        # ------------------------------------------------------------------
        # 4. Build and emit the complete event
        # ------------------------------------------------------------------
        assistant_message = "".join(assistant_chunks)

        # Use the final state from the agent if captured, otherwise
        # fall back to the input state (should not happen in practice).
        result_state = final_state if final_state is not None else state

        # If no tokens were streamed but the last AI message has content,
        # emit it as a single token so the frontend always gets text.
        if not assistant_chunks:
            messages = result_state.get("messages", [])
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
                    assistant_message = msg.content
                    yield {"type": "token", "data": assistant_message}
                    break

        envelope = _build_complete_envelope(result_state, assistant_message)

        wall_ms = int((time.monotonic() - wall_start) * 1000)
        logger.info(
            "[run_turn_streaming] session=%s, wall=%dms, tokens=%d, tools=%s",
            session_id or "(none)",
            wall_ms,
            len(assistant_chunks),
            result_state.get("turn_meta", {}).get("tools_called", []),
        )

        yield {"type": "complete", "data": envelope}

    except TimeoutError:
        logger.error(
            "[run_turn_streaming] Stream timed out after %ds (session=%s)",
            STREAM_TIMEOUT_SECONDS,
            session_id,
        )
        yield {"type": "error", "message": "Request timed out. Please try again."}

    except Exception as exc:
        logger.error(
            "[run_turn_streaming] Stream failed (session=%s): %s",
            session_id,
            exc,
            exc_info=True,
        )
        yield {"type": "error", "message": str(exc)}
