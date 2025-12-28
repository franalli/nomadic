"""
Router Node - Intent determination for conversational flow.

This module contains the router node function which determines user intent
and routes to the appropriate next step in the graph (required_fields, strategy, etc.).

Uses a small LLM with timeout but no retry (router should be fast and reliable).
Also refines user intent classification for conversational style adaptation.

Extracted from plan_graph.py as part of the P2 module extraction initiative.
"""

from __future__ import annotations

import json
import random as _random_module
from typing import TYPE_CHECKING

# P2: Module-level imports for non-circular dependencies
from app.config import settings
from app.debug_utils import _debug, _debug_error
from app.graph_plan_utils import jloads_safe
from app.planner.nodes.llm_utils import measure_llm_call

if TYPE_CHECKING:
    from app.plan_graph import GraphState


async def router(state: "GraphState") -> "GraphState":
    """
    Router node to determine intent. Uses timeout but NO retry (router should be fast and reliable).
    Also refines user intent classification for conversational style adaptation.
    """
    # Late imports for plan_graph functions (circular dependency)
    from app.plan_graph import (
        _OFF_TOPIC_DEFLECTIONS,
        USER_INTENT_ARCHETYPES,
        StateViewBuilder,
        _compute_cache_key,
        _debug_cache_hit,
        _debug_node_entry,
        _debug_node_exit,
        _estimate_prompt_tokens,
        _follow_up_cache,
        _get_cached_response,
        _get_core_fields_state,
        _get_node_llm_config,
        _hash_user_text,
        _record_node_tokens,
        _set_cached_response,
        call_llm_with_timeout,
        load_prompt,
    )

    _, start_ns = _debug_node_entry("router", state)

    # Get per-node LLM configuration
    llm_config = _get_node_llm_config("router")

    # Check cache first - router decisions are stable for same inputs
    core_fields = _get_core_fields_state(state.trip_inputs)
    user_text_hash = _hash_user_text(state.user_text or "")
    cache_key = _compute_cache_key("router", core_fields, "", user_text_hash)
    cached = _get_cached_response(_follow_up_cache, cache_key, state)
    if cached is not None:
        _debug_cache_hit("router", cache_key[:16])
        state.intent = cached.get("intent") or "required_fields"
        state.strategy_topic = cached.get("strategy_topic")
        state.metadata["router_notes"] = cached.get("notes", "")
        state.metadata["router_confidence"] = cached.get("confidence", 1.0)
        state.metadata["router_path"] = "cache"
        if cached.get("user_intent"):
            state.metadata["user_intent"] = cached["user_intent"]

        # Update no_progress_turns counter (must happen for cache hits too)
        prev_intent = state.metadata.get("last_intent")
        no_progress_turns = state.metadata.get("no_progress_turns", 0)
        if state.intent == "required_fields" and prev_intent == "required_fields":
            no_progress_turns += 1
        else:
            no_progress_turns = 0
        state.metadata["no_progress_turns"] = no_progress_turns
        state.metadata["last_intent"] = state.intent

        _debug("Router cache hit", intent=state.intent, topic=state.strategy_topic)
        _debug_node_exit("router", state, start_ns)
        return state

    try:
        prompt = load_prompt("router")
        # Include user intent hint from extractor for router to refine
        user_intent_hint = state.metadata.get("user_intent_hint", "")

        # Use minimal state view for router (saves ~75% tokens vs full trip_inputs)
        router_state_view = StateViewBuilder.for_router(state)

        tpl = (
            prompt.replace("{parsed_inputs}", json.dumps(state.parsed_inputs))
            .replace("{trip_inputs}", json.dumps(router_state_view))
            .replace("{user_intent_hint}", user_intent_hint or "none")
        )

        tokens = _estimate_prompt_tokens(tpl, state.parsed_inputs)
        _record_node_tokens(state, "router", tokens, model=llm_config["model_hint"])

        async with measure_llm_call(state):
            out = await call_llm_with_timeout(
                model=llm_config["model_hint"],
                prompt=tpl,
                timeout_seconds=settings.llm_timeout_router,
                max_tokens=llm_config["max_tokens"],
                temperature=llm_config["temperature"],
            )
        j = jloads_safe(out)
        state.intent = j.get("intent") or "required_fields"
        topic = j.get("topic") or state.parsed_inputs.get("strategy_hint")
        state.strategy_topic = topic if state.intent == "strategy" else None
        state.metadata["router_notes"] = j.get("notes", "")
        state.metadata["router_confidence"] = j.get("confidence", 1.0)

        # Cache the router result for future identical requests
        _set_cached_response(
            _follow_up_cache,
            cache_key,
            {
                "intent": state.intent,
                "strategy_topic": state.strategy_topic,
                "notes": state.metadata.get("router_notes", ""),
                "confidence": state.metadata.get("router_confidence", 1.0),
                "user_intent": j.get("user_intent"),
            },
        )

        # Handle off-topic intent with friendly deflection
        if state.intent == "off_topic":
            state.last_summary = _random_module.choice(_OFF_TOPIC_DEFLECTIONS)
            state.metadata["last_question_field"] = "destinations"
            _debug("Off-topic detected, deflecting to travel", response=state.last_summary[:50])
            _debug_node_exit("router", state, start_ns)
            return state

        # Capture refined user intent from router (if provided)
        router_user_intent = j.get("user_intent")
        if router_user_intent and router_user_intent in USER_INTENT_ARCHETYPES:
            # Router refined the intent - update if different from extractor hint
            current_intent = state.metadata.get("user_intent")
            if router_user_intent != current_intent:
                _debug(
                    "Router refined user intent",
                    from_intent=current_intent,
                    to_intent=router_user_intent,
                )
                state.metadata["user_intent"] = router_user_intent
                state.metadata["intent_turn_count"] = 1
                state.metadata["intent_confidence"] = 1.0

        _debug(
            "Router result",
            intent=state.intent,
            confidence=state.metadata.get("router_confidence"),
            topic=state.strategy_topic,
            user_intent=state.metadata.get("user_intent"),
        )

        prev_intent = state.metadata.get("last_intent")
        no_progress_turns = state.metadata.get("no_progress_turns", 0)
        if state.intent == "required_fields" and prev_intent == "required_fields":
            no_progress_turns += 1
        else:
            no_progress_turns = 0
        state.metadata["no_progress_turns"] = no_progress_turns
        state.metadata["last_intent"] = state.intent

        _debug_node_exit("router", state, start_ns)
        return state
    except Exception as exc:
        # Router failure is not critical - default to required_fields for conversational flow
        _debug_error("Router failed, defaulting to required_fields", error=str(exc))
        state.intent = "required_fields"
        state.metadata["router_notes"] = f"Router error: {exc}"
        _debug_node_exit("router", state, start_ns)
        return state
