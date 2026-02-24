"""
Agent state for the create_agent-based planner.

Extends LangChain's AgentState (which provides ``messages`` with add_messages
reducer) with trip-planning context fields that persist across turns.

All extra fields use ``NotRequired`` so they are optional at graph invocation
time -- callers only need to supply ``messages``.
"""

from __future__ import annotations

from typing import NotRequired

from langchain.agents import AgentState


class NomadicAgentState(AgentState):
    """Extended agent state for trip planning.

    Inherited from AgentState:
        messages:  list[AnyMessage]  (with add_messages reducer)

    Added fields carry trip context across turns.  Each is a plain
    serializable type so the state can round-trip through LangGraph
    checkpointers without custom serde.
    """

    # Serialized TripPlan core fields (destination, dates, travelers, budget, etc.)
    trip_plan: NotRequired[dict]

    # Booking types and settings (hotel stars, cabin class, skill level, ...)
    trip_settings: NotRequired[dict]

    # Tile inventory from logistics/search_tiles
    # Structure: {"flights": [...], "hotels": [...], "activities": [...]}
    tiles: NotRequired[dict]

    # Strategy-section cards produced by specialist advice
    strategy_sections: NotRequired[list]

    # Itinerary day cards from build_itinerary
    day_cards: NotRequired[list]

    # Active specialist constraints (no-fly buffer, altitude limits, ...)
    constraints: NotRequired[list]

    # Per-turn metadata -- reset at the start of each turn
    turn_meta: NotRequired[dict]

    # Cross-turn metadata (plan_view_state, regen tier, ...)
    persistent_meta: NotRequired[dict]
