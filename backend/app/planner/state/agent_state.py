"""
Agent state for the create_agent-based planner.

Extends LangChain's AgentState (which provides ``messages`` with add_messages
reducer) with trip-planning context fields that persist across turns.

Fields that may receive concurrent updates from parallel tool calls (e.g.,
two get_specialist_advice calls running simultaneously) use ``Annotated``
with a reducer function so LangGraph can merge them without raising
``INVALID_CONCURRENT_GRAPH_UPDATE``.
"""

from __future__ import annotations

from typing import Annotated, Any, NotRequired

from langchain.agents import AgentState

# ---------------------------------------------------------------------------
# Reducer functions for concurrent state updates
# ---------------------------------------------------------------------------


def _merge_dicts(left: dict, right: dict) -> dict:
    """Shallow dict merge — right wins for overlapping keys."""
    if not left:
        return right or {}
    if not right:
        return left
    return {**left, **right}


def _merge_turn_meta(left: dict, right: dict) -> dict:
    """Merge turn_meta dicts from potentially parallel tool calls.

    Special handling:
    - ``tools_called``: concatenation (no dedup) so parallel same-tool calls
      (e.g. two ``get_specialist_advice``) are counted correctly for
      ModelSelectionMiddleware upgrade thresholds.
    - ``tool_call_count``: derived from len(tools_called) after merge
    - All other keys: right wins (validation_result, builder_result, etc.)
    """
    if not left:
        return right or {}
    if not right:
        return left
    merged = {**left, **right}

    # Merge tools_called lists -- simple concatenation preserves duplicates
    left_tools: list[str] = left.get("tools_called", [])
    right_tools: list[str] = right.get("tools_called", [])
    if isinstance(left_tools, list) and isinstance(right_tools, list):
        combined = list(left_tools) + right_tools
        merged["tools_called"] = combined
        merged["tool_call_count"] = len(combined)

    return merged


def _merge_strategy_sections(left: list, right: list) -> list:
    """Merge strategy sections, deduplicating by specialist_type (right wins)."""
    if not left:
        return right or []
    if not right:
        return left

    by_type: dict[str, Any] = {}
    # Left first (preserves order)
    for s in left:
        key = s.get("specialist_type") if isinstance(s, dict) else None
        if key:
            by_type[key] = s
        else:
            by_type[id(s)] = s
    # Right overwrites
    for s in right:
        key = s.get("specialist_type") if isinstance(s, dict) else None
        if key:
            by_type[key] = s
        else:
            by_type[id(s)] = s
    return list(by_type.values())


def _merge_constraints(left: list, right: list) -> list:
    """Merge constraints, deduplicating by constraint_id (right wins)."""
    if not left:
        return right or []
    if not right:
        return left

    by_id: dict[str, Any] = {}
    for c in left:
        cid = c.get("constraint_id") if isinstance(c, dict) else None
        by_id[cid or f"_left_{id(c)}"] = c
    for c in right:
        cid = c.get("constraint_id") if isinstance(c, dict) else None
        by_id[cid or f"_right_{id(c)}"] = c
    return list(by_id.values())


# ---------------------------------------------------------------------------
# Agent state
# ---------------------------------------------------------------------------


class NomadicAgentState(AgentState):
    """Extended agent state for trip planning.

    Inherited from AgentState:
        messages:  list[AnyMessage]  (with add_messages reducer)

    Added fields carry trip context across turns.  Each is a plain
    serializable type so the state can round-trip through LangGraph
    checkpointers without custom serde.

    Fields updated by parallel tool calls use ``Annotated[type, reducer]``
    so LangGraph can merge concurrent ``Command(update={...})`` payloads.
    """

    # Serialized TripPlan core fields (destination, dates, travelers, budget, etc.)
    trip_plan: Annotated[dict, _merge_dicts]

    # Booking types and settings (hotel stars, cabin class, skill level, ...)
    trip_settings: Annotated[dict, _merge_dicts]

    # Tile inventory from logistics/search_tiles
    # Structure: {"flights": [...], "hotels": [...], "activities": [...]}
    tiles: Annotated[dict, _merge_dicts]

    # Strategy-section cards produced by specialist advice
    strategy_sections: Annotated[list, _merge_strategy_sections]

    # Itinerary day cards from build_itinerary
    day_cards: NotRequired[list]

    # Active specialist constraints (no-fly buffer, altitude limits, ...)
    constraints: Annotated[list, _merge_constraints]

    # Coordinator specialist plan outputs keyed by topic (e.g. "diving", "hiking")
    specialist_plans: Annotated[dict, _merge_dicts]

    # Per-turn metadata -- reset at the start of each turn
    turn_meta: Annotated[dict, _merge_turn_meta]

    # Cross-turn metadata (plan_view_state, regen tier, ...)
    persistent_meta: Annotated[dict, _merge_dicts]
