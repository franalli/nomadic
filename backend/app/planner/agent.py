"""
Agent factory -- creates the create_agent-based planner graph.

Uses ``create_agent`` with middleware-driven dynamic prompt injection
so the LLM sees current trip state every turn.

Middleware order (outermost first):
1. ModelSelectionMiddleware  -- upgrades LLM for complex planning turns
2. DynamicPromptMiddleware   -- injects per-turn system prompt from state
3. TurnLifecycleMiddleware   -- resets turn_meta; merges tool results
4. SuggestionChipMiddleware  -- generates suggestion chips after final response
"""

from __future__ import annotations

import logging

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from app.config import settings
from app.planner.agent_constants import AGENT_MAX_TOKENS, AGENT_TEMPERATURE
from app.planner.llm_factory import get_llm_by_model
from app.planner.middleware import (
    DynamicPromptMiddleware,
    ModelSelectionMiddleware,
    SuggestionChipMiddleware,
    TurnLifecycleMiddleware,
)
from app.planner.state.agent_state import NomadicAgentState
from app.planner.tools import (
    build_itinerary,
    extract_trip_fields,
    get_local_intel,
    get_specialist_advice,
    search_tiles,
    validate_plan,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_planner_agent(
    *,
    model: str | BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Factory: build and return the compiled planner agent graph.

    Uses ``create_agent`` with a tool-calling loop and dynamic prompt
    middleware so the LLM sees current trip state on every model invocation.

    Parameters
    ----------
    model : str | BaseChatModel | None
        LLM to use.  Defaults to ``settings.router_model`` (gemini-2.5-flash)
        which has strong tool-calling support.  The ModelSelectionMiddleware
        upgrades to gpt-4o for complex planning turns automatically.
    checkpointer : BaseCheckpointSaver | None
        Optional LangGraph checkpointer for persisting state across
        invocations (e.g. ``MemorySaver`` or ``PostgresSaver``).
    """
    # Resolve model -- default to router_model (gemini-2.5-flash, good for
    # tool-calling).  Accepts a pre-built BaseChatModel or a model string.
    if model is None:
        resolved_model = get_llm_by_model(
            settings.router_model,
            temperature=AGENT_TEMPERATURE,
            max_tokens=AGENT_MAX_TOKENS,
        )
        model_name = settings.router_model
    elif isinstance(model, str):
        resolved_model = get_llm_by_model(
            model,
            temperature=AGENT_TEMPERATURE,
            max_tokens=AGENT_MAX_TOKENS,
        )
        model_name = model
    else:
        resolved_model = model
        model_name = getattr(model, "model_name", str(type(model).__name__))

    tools = [
        extract_trip_fields,
        get_specialist_advice,
        search_tiles,
        get_local_intel,
        validate_plan,
        build_itinerary,
    ]

    # Minimal static prompt -- the DynamicPromptMiddleware overrides this
    # with a full state-aware prompt on every model call.
    initial_prompt = (
        "You are Nomadic, a trip-planning assistant. Use the available tools to help plan trips."
    )

    # Middleware applied outermost-first:
    #   ModelSelection > DynamicPrompt > TurnLifecycle > SuggestionChip
    middleware = [
        ModelSelectionMiddleware(),
        DynamicPromptMiddleware(),
        TurnLifecycleMiddleware(),
        SuggestionChipMiddleware(),
    ]

    agent = create_agent(
        model=resolved_model,
        tools=tools,
        system_prompt=initial_prompt,
        middleware=middleware,
        state_schema=NomadicAgentState,
        checkpointer=checkpointer,
        name="nomadic_planner",
    )

    logger.info(
        "Planner agent created: model=%s, tools=%d, middleware=%d, checkpointer=%s",
        model_name,
        len(tools),
        len(middleware),
        type(checkpointer).__name__ if checkpointer else "none",
    )

    return agent
