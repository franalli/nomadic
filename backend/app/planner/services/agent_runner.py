"""
Lightweight turn-execution helper for the create_agent planner.

Wraps agent invocation with state serialization/deserialization so callers
only deal with plain dicts (suitable for DB persistence).  Used by tests
and will later be called from the streaming layer.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from langchain_core.messages import HumanMessage

from app.planner.agent import create_planner_agent
from app.planner.services.state_serde import restore_agent_state, serialize_agent_state

logger = logging.getLogger(__name__)

# Module-level cached agent (created once, reused across calls)
_cached_agent = None


def _get_agent():
    """Lazily create and cache the planner agent."""
    global _cached_agent  # noqa: PLW0603
    if _cached_agent is None:
        _cached_agent = create_planner_agent()
    return _cached_agent


def _reset_agent() -> None:
    """Clear the cached agent so the next call to ``_get_agent`` creates a fresh one.

    Intended for test teardown -- production code should never need this.
    """
    global _cached_agent  # noqa: PLW0603
    _cached_agent = None


async def run_agent_turn(
    user_message: str,
    session_state: Optional[Dict[str, Any]] = None,
    session_id: str = "",
) -> Dict[str, Any]:
    """Execute a single agent turn and return the new session_state.

    Steps:
    1. Restore state from ``session_state`` via ``restore_agent_state()``.
    2. Append the user message as a ``HumanMessage``.
    3. Invoke the agent with the state.
    4. Extract the final state from the result.
    5. Serialize and return the new session_state.

    Parameters
    ----------
    user_message : str
        The user's chat message for this turn.
    session_state : dict | None
        Previously serialized session state from a prior turn, or None for
        the first turn.
    session_id : str
        Optional session identifier for logging/tracking.

    Returns
    -------
    dict
        The serialized session state after this turn completes.  Can be
        passed back as ``session_state`` for the next turn.
    """
    agent = _get_agent()

    # Restore state from previous turn (or fresh defaults)
    state = restore_agent_state(session_state)

    # Append the user message
    state["messages"].append(HumanMessage(content=user_message))

    logger.info(
        "[run_agent_turn] session=%s, messages=%d, user=%r",
        session_id or "(none)",
        len(state["messages"]),
        user_message[:80],
    )

    # Invoke the agent -- returns the full state dict
    config: Dict[str, Any] = {}
    if session_id:
        config["configurable"] = {"thread_id": session_id}

    result = await agent.ainvoke(state, config=config)

    # Result is a dict matching NomadicAgentState
    if not isinstance(result, dict):
        # Defensive: if LangGraph returns something unexpected, convert
        result = dict(result) if hasattr(result, "items") else {"messages": []}

    logger.info(
        "[run_agent_turn] session=%s, result_messages=%d, trip_plan_dest=%s",
        session_id or "(none)",
        len(result.get("messages", [])),
        result.get("trip_plan", {}).get("destination"),
    )

    # Serialize for persistence
    return serialize_agent_state(result)
