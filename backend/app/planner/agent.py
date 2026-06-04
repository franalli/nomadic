"""
Agent factory -- creates the create_agent-based planner graph.

Uses ``create_agent`` with middleware-driven dynamic prompt injection
so the LLM sees current trip state every turn.

Middleware order (outermost first):
1. ModelCallLimitMiddleware  -- bounds model rounds per turn (loop/cost ceiling)
2. ToolCallLimitMiddleware   -- bounds tool calls per turn (loop/cost ceiling)
3. ModelSelectionMiddleware  -- upgrades LLM for complex planning turns
4. DynamicPromptMiddleware   -- injects per-turn CURRENT CONTEXT as a trailing message
5. TurnLifecycleMiddleware   -- resets turn_meta; merges tool results; counts model turns

Suggestion chips are generated downstream by the envelope builder, NOT here.
"""

from __future__ import annotations

import logging

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from app.config import settings
from app.planner.agent_constants import AGENT_MAX_TOKENS, AGENT_TEMPERATURE, AGENT_TIMEOUT
from app.planner.llm_factory import get_llm_by_model
from app.planner.middleware import (
    DynamicPromptMiddleware,
    ModelSelectionMiddleware,
    TurnLifecycleMiddleware,
)
from app.planner.prompts.planner import build_static_system_prompt
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
            # Bound each model call so a hung provider request can't stall the
            # whole turn (ModelRetryMiddleware retries the timeout with backoff).
            timeout=AGENT_TIMEOUT,
            max_retries=2,
        )
        model_name = settings.router_model
    elif isinstance(model, str):
        resolved_model = get_llm_by_model(
            model,
            temperature=AGENT_TEMPERATURE,
            max_tokens=AGENT_MAX_TOKENS,
            timeout=AGENT_TIMEOUT,
            max_retries=2,
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

    # Stable cached prefix -- orchestrator instructions + specialist list, no
    # per-turn data. DynamicPromptMiddleware appends the volatile CURRENT
    # CONTEXT as a trailing message so this prefix stays cache-eligible.
    initial_prompt = build_static_system_prompt()

    # Middleware applied outermost-first. Limit middleware first so the loop is
    # bounded before any model/tool work; chips are produced by the envelope.
    middleware = [
        ModelCallLimitMiddleware(run_limit=8, exit_behavior="end"),
        ToolCallLimitMiddleware(run_limit=16, exit_behavior="end"),
        ModelSelectionMiddleware(),
        # Retry transient provider errors (e.g. Gemini 503 UNAVAILABLE) with
        # backoff. Outside DynamicPrompt so a retry re-runs with fresh context.
        ModelRetryMiddleware(max_retries=2, initial_delay=0.5, max_delay=8.0),
        DynamicPromptMiddleware(),
        TurnLifecycleMiddleware(),
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
