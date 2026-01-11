"""
Strategy node functions for LangGraph planner.

Extracted from plan_graph.py for modularity.

Contains:
- _strategy_stage0: Pre-core value-first strategy response
- strategy_node: Main strategy node entry point

Helper functions are imported from strategy.base module.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Dict, List

# P2: Module-level imports for non-circular dependencies
from app.config import settings
from app.debug_utils import _debug, _debug_error
from app.graph_plan_utils import _extract_message_from_malformed_json, jloads_safe
from app.planner.gates.checks import (
    STRATEGY_TIER_MAX_TOKENS,
    StrategyExpansionTarget,
    StrategyTier,
    is_strategy_expansion_request,
)
from app.planner.gates.readiness import compute_trip_readiness
from app.planner.gates.suppression import SuppressionPredicates
from app.planner.nodes.llm_utils import measure_llm_call

# Import shared strategy utilities from base module (avoid duplication)
from app.planner.nodes.strategy.base import (
    detect_field_modification_request,
    detect_strategy_switch,
    detect_topic_switch,
)
from app.planner.nodes.strategy.base import (
    has_strategy_keyword as _has_strategy_keyword,
)
from app.planner.nodes.strategy.base import (
    is_strategy_enabled as _is_strategy_enabled,
)

if TYPE_CHECKING:
    from app.plan_graph import GraphState


async def _strategy_stage0(state: "GraphState", topic: str) -> "GraphState":
    """
    Stage 0: Pre-core value-first strategy response.

    Provides immediate value (destination archetypes + mini itinerary) with
    a single clarifying question, before core fields are complete.

    This is triggered by:
    - STRATEGY_PRE_CORE_VALUE gate: topic detected, no destinations
    - STRATEGY_PRE_CORE_VALUE_WITH_DEST gate: topic + destinations present

    When destinations are present (strategy_dest_known=True), generates
    destination-specific guidance and asks for dates.

    NOTE: This function delegates to Stage0Coordinator in strategy/stage0.py.
    The implementation has been consolidated there to avoid duplication.
    """
    from app.planner.nodes.strategy.stage0 import Stage0Coordinator

    return await Stage0Coordinator.execute(state, topic)


async def strategy_node(state: "GraphState") -> "GraphState":
    """
    Main strategy node entry point.

    Handles strategy-specific trip planning with multi-stage progression:
    - Stage 0: Pre-core value-first (destination archetypes + single question)
    - Stage 1: Initial strategy response (shortlist + skeleton)
    - Stage 2: Section expansion (detailed content for specific topics)
    """
    # Late imports for plan_graph functions (circular dependency)
    from app.plan_graph import (
        _STAGE1_SANITY_CHECKLIST,
        INVALID_JSON_HINT,
        QUESTION_TARGET_VALUES,
        STRATEGY_REGISTRY,
        TRIP_VALIDATOR,
        StateViewBuilder,
        ToneAdapter,
        _apply_llm_delta,
        _debug_node_entry,
        _debug_node_exit,
        _debug_suggestions,
        _estimate_prompt_tokens,
        _generate_conversation_summary,
        _get_core_fields_state,
        _get_missing_fields_summary,
        _get_node_llm_config,
        _get_strategy_cached,
        _get_suggestions_with_fallback,
        _hash_user_text,
        _normalize_branch_spec,
        _record_llm_failure,
        _record_node_tokens,
        _set_strategy_cached,
        _strategy_stats,
        _strip_stage1_includes,
        _write_trip_inputs,
        call_llm_with_timeout,
        can_call_llm,
        llm_blocked_fallback,
        load_prompt,
        required_fields_node,
        set_question_target,
        truncate_preserving_newlines,
    )

    # Late imports for cross-node dependencies (circular via nodes/__init__.py)
    from app.planner.nodes import _specialist
    from app.planner.nodes.specialist import _invoke_missing_fields_guard

    _, start_ns = _debug_node_entry("strategy_node", state)

    topic = state.strategy_topic or "boating"

    # Log selected specialist for observability (routing correctness tracking)
    specialist_name = f"strategy_{topic}"
    state.metadata["selected_specialist"] = specialist_name
    _debug(
        "Strategy topic selected",
        topic=topic,
        specialist=specialist_name,
        routing_path=state.metadata.get("router_path", "unknown"),
    )

    # =========================================================================
    # STAGE 0: PRE-CORE VALUE-FIRST MODE
    # =========================================================================
    # When routed via STRATEGY_PRE_CORE_VALUE gate, provide immediate value
    # (destination archetypes + mini itinerary) with a single clarifying question.
    # This bypasses the core fields guard since we're intentionally providing
    # inspiration before collecting details.
    is_stage0 = state.metadata.get("strategy_stage") == 0
    if is_stage0:
        # =====================================================================
        # LIFECYCLE SUPPRESSION CHECK (P0 fix: router path bypass)
        # =====================================================================
        # The gate path checks lifecycle in GateEvaluator, but router LLM path
        # bypasses that. Apply the same check here to prevent re-running stage0
        # for the same topic+destinations+origin combination.
        # =====================================================================
        ti = state.trip_inputs
        destinations = ti.destinations or []
        origin = ti.origin
        current_sig = SuppressionPredicates.compute_stage0_signature(topic, destinations, origin)
        completed_sig = state.metadata.get("stage0_completed_sig")
        if completed_sig == current_sig:
            _debug(
                "strategy_node stage0 skipped: lifecycle suppression (router path)",
                current_sig=current_sig,
                completed_sig=completed_sig,
                reason="stage0 already completed for this topic+destinations+origin",
            )
            # Fall through to required_fields instead of re-running stage0
            state.metadata["strategy_stage0_skipped_lifecycle"] = True
            return await required_fields_node(state)

        _debug(
            "📋 STRATEGY STAGE 0: Pre-core value-first mode",
            topic=topic,
            question_target=state.question_target,
        )
        _strategy_stats["stage0_calls"] = _strategy_stats.get("stage0_calls", 0) + 1
        from app.plan_graph import _gate_stats

        _gate_stats["strategy_pre_core_value_fired"] += 1
        return await _strategy_stage0(state, topic)

    # =========================================================================
    # NODE GUARD 1: Block strategy if core fields are missing
    # =========================================================================
    # Strategy nodes need destination context to provide relevant advice.
    # This guard catches cases where routing exemption allowed strategy through.
    readiness = compute_trip_readiness(state.trip_inputs)
    missing_core = readiness.missing_core
    if not readiness.core_complete:
        _debug(
            "⚠️ Node guard triggered: missing core fields for strategy",
            strategy=topic,
            missing=missing_core,
        )
        # Use small prompt to generate a warm question with suggestions
        guard_result = await _invoke_missing_fields_guard(state, missing_core)
        if guard_result:
            _debug_node_exit("strategy_node", state, start_ns)
            return state

    # =========================================================================
    # NODE GUARD 1.5: Collect end_date for duration-aware itinerary planning
    # =========================================================================
    # If start_date is set but end_date is missing, ask for return date before
    # proceeding to Stage 1/2. Stage 0 is exempt since it's pre-core and only
    # provides destination inspiration. Duration context enables better itineraries.
    # =========================================================================
    ti = state.trip_inputs
    end_date_bypassed = state.metadata.get("end_date_bypassed", False)
    if (
        ti.start_date
        and not ti.end_date
        and not end_date_bypassed
        and not state.flags.get("is_stage0")  # Stage 0 exempt
    ):
        # Check for skip phrases: "flexible", "open-ended", "skip return date", "I'm flexible"
        user_text_lower_guard = (state.user_text or "").lower()
        skip_phrases = {
            "flexible",
            "i'm flexible",
            "im flexible",
            "open-ended",
            "open ended",
            "skip return date",
            "skip return",
            "no return date",
            "don't know return",
            "not sure when",
            "whenever",
        }
        is_skip_response = any(phrase in user_text_lower_guard for phrase in skip_phrases)

        if is_skip_response:
            # User chose to skip - warm response, mark bypassed
            _debug(
                "📅 NODE GUARD 1.5: User skipped return date (flexible)",
                topic=topic,
                user_text_preview=user_text_lower_guard[:50],
            )
            state.metadata["end_date_bypassed"] = True
            state.last_summary = (
                "No problem! I'll suggest a flexible itinerary that you can "
                "adapt to your schedule. "
                "Now let me help you plan your adventure! 🌟"
            )
            # Continue to strategy processing - don't return, let guard 2 run
        else:
            # Ask for return date with suggestions
            _debug(
                "📅 NODE GUARD 1.5: Asking for return date before Stage 1/2",
                topic=topic,
                start_date=ti.start_date,
            )
            state.question_target = "end_date"
            state.metadata["question_target"] = "end_date"

            # Format the start date nicely for the message
            try:
                from datetime import datetime as dt

                start_dt = dt.strptime(ti.start_date, "%Y-%m-%d")
                start_formatted = start_dt.strftime("%B %d")
            except (ValueError, TypeError):
                start_formatted = ti.start_date

            state.last_summary = (
                f"Great! You're departing on **{start_formatted}**. "
                f"When are you planning to return? This helps me suggest "
                f"the right itinerary length."
            )
            state.suggested_responses = [
                "A week",
                "10 days",
                "2 weeks",
                "I'm flexible",
            ]
            # Set provenance for streaming mode decision
            state.metadata["response_writer_node"] = "strategy_node:guard1.5"
            state.metadata["response_generation_provenance"] = "template"
            _debug_node_exit("strategy_node", state, start_ns)
            return state

    # =========================================================================
    # NODE GUARD 2: Verify strategy topic relevance
    # =========================================================================
    # Only invoke strategy LLM if user text actually contains strategy-related terms.
    # This prevents wasted tokens when router incorrectly routes to strategy.
    # Uses extracted detection functions from strategy.base module.
    user_text = state.user_text or ""
    has_strategy_keyword = _has_strategy_keyword(user_text, topic)

    # Also check if strategy was explicitly routed via keyword heuristic
    was_keyword_routed = state.metadata.get("router_path", "").startswith("keyword_heuristic:")

    # V36 FIX: Check if this is a stage 2 expansion request (e.g., "show more details")
    # This bypasses the keyword check since expansion is a meta-request that doesn't
    # need to repeat the topic - the topic context is already established from stage 1.
    expansion_result = is_strategy_expansion_request(user_text)
    is_expansion_request = state.pending_strategy_expansion and expansion_result.is_expansion

    # V37 FIX: Detect topic switches using extracted functions
    # Check for strategy-to-strategy switches (e.g., hiking -> cycling)
    detected_strategy_switch = detect_strategy_switch(user_text, topic)
    # Check for category switches (e.g., strategy -> hotels)
    detected_topic_switch = detect_topic_switch(user_text)

    if not has_strategy_keyword and not was_keyword_routed and not is_expansion_request:
        # Strategy was routed but user text doesn't mention the topic

        # V37: If user wants a DIFFERENT strategy topic, switch to that topic
        if detected_strategy_switch:
            _debug(
                "🔄 Strategy topic switch: user wants different strategy",
                from_topic=topic,
                to_topic=detected_strategy_switch,
                user_text_preview=user_text[:50],
                action="switching strategy topic",
            )
            state.metadata["strategy_gate_fallback"] = True
            state.metadata["strategy_gate_reason"] = (
                f"strategy_switch:{topic}->{detected_strategy_switch}"
            )
            state.strategy_topic = detected_strategy_switch
            state.pending_strategy_expansion = False  # Reset expansion state for new topic
            # Recursively call strategy_node with new topic
            _debug_node_exit("strategy_node", state, start_ns)
            return await strategy_node(state)

        # V37: If user is clearly asking about a different category, route to that specialist
        if detected_topic_switch:
            # Map category names to specialist names
            specialist_map = {
                "hotels": "hotels",
                "flights": "flights",
                "ground_transport": "transport",
                "activities": "activities",
            }
            specialist_name = specialist_map.get(detected_topic_switch, detected_topic_switch)
            _debug(
                "⚠️ Strategy relevance gate: topic switch detected",
                topic=topic,
                detected_switch=detected_topic_switch,
                user_text_preview=user_text[:50],
                action=f"routing to {specialist_name} specialist",
            )
            state.metadata["strategy_gate_fallback"] = True
            state.metadata["strategy_gate_reason"] = f"topic_switch:{detected_topic_switch}"
            state.intent = specialist_name
            # Route to the appropriate domain specialist
            _debug_node_exit("strategy_node", state, start_ns)
            return await _specialist(specialist_name, state)

        # V38: Check if user wants to modify a trip field (e.g., "I want to add budget")
        # This handles cases where user interrupts strategy flow to add/modify fields
        detected_field = detect_field_modification_request(user_text)
        if detected_field:
            _debug(
                "📝 Strategy relevance gate: field modification request detected",
                topic=topic,
                detected_field=detected_field,
                user_text_preview=user_text[:50],
                action="asking for field value",
            )
            state.metadata["strategy_gate_fallback"] = True
            state.metadata["strategy_gate_reason"] = f"field_modification:{detected_field}"

            # Generate field-specific question and suggestions
            field_questions = {
                "budget": "What's your budget for this trip?",
                "travelers": "How many people will be traveling?",
                "dates": "When are you planning to travel?",
                "origin": "Where will you be traveling from?",
            }
            field_suggestions = {
                "budget": ["$2,000", "$5,000", "Flexible budget"],
                "travelers": ["Just me", "2 adults", "Family of 4"],
                "dates": ["Next month", "In 3 months", "I'm flexible"],
                "origin": [],  # Location-specific, leave empty
            }

            state.last_summary = field_questions.get(
                detected_field, f"What {detected_field} would you like to set?"
            )
            state.suggested_responses = field_suggestions.get(detected_field, [])
            state.metadata["last_question_field"] = detected_field
            state.question_target = detected_field

            # Set provenance for streaming mode decision
            state.metadata["response_writer_node"] = (
                f"strategy_node:field_modification:{detected_field}"
            )
            state.metadata["response_generation_provenance"] = "template"
            _debug_suggestions(
                state.suggested_responses,
                source=f"strategy_node:field_modification:{detected_field}",
            )
            _debug_node_exit("strategy_node", state, start_ns)
            return state

        # No topic switch detected - ask about current strategy topic
        _debug(
            "⚠️ Strategy relevance gate: topic keywords not found in user text",
            topic=topic,
            user_text_preview=user_text[:50],
            action="falling back to required_fields",
        )
        state.metadata["strategy_gate_fallback"] = True
        state.metadata["strategy_gate_reason"] = f"no_{topic}_keywords"
        # Instead of wasting strategy LLM, give a helpful response
        state.last_summary = (
            f"I'd be happy to help with {topic} planning! "
            f"Can you tell me more about what kind of {topic} experience you're looking for?"
        )
        state.suggested_responses = [
            f"Beginner-friendly {topic}",
            f"Advanced {topic} spots",
            "Equipment rental info",
        ]
        # Set provenance for streaming mode decision
        state.metadata["response_writer_node"] = "strategy_node:relevance_gate"
        state.metadata["response_generation_provenance"] = "template"
        _debug_suggestions(state.suggested_responses, source="strategy_node:relevance_gate")
        _debug_node_exit("strategy_node", state, start_ns)
        return state

    # Check feature flag - if disabled, fallback to activities-lite
    if not _is_strategy_enabled(topic):
        _debug(f"Strategy {topic} is disabled, falling back to activities")
        state.last_summary = (
            f"The {topic} planning module is currently unavailable. "
            "I can help with general activity planning instead."
        )
        state.active_category = "activities"
        return await _specialist("activities", state)

    prompt_name = STRATEGY_REGISTRY.get(topic)
    if not prompt_name:
        # Fallback: gentle notice; no state changes
        _debug(f"No prompt for strategy {topic}")
        state.last_summary = (
            f"I can draft a detailed {topic} plan soon. For now, which preferences matter most?"
        )
        state.suggested_responses = [
            "Beginner skill level",
            "Prefer skippered",
            "Max 4 hours daily",
        ]
        # Set provenance for streaming mode decision
        state.metadata["response_writer_node"] = "strategy_node:no_prompt"
        state.metadata["response_generation_provenance"] = "template"
        _debug_suggestions(state.suggested_responses, source="strategy_node:fallback")
        _debug_node_exit("strategy_node", state, start_ns)
        return state

    # =========================================================================
    # THREE-TIER STRATEGY LOGIC (Phase 1: Token Optimization)
    # =========================================================================
    # Stage 1 (OUTLINE tier): Returns shortlist + skeleton (max_tokens 512)
    #   Sets pending_strategy_expansion = True, ends with expansion suggestions
    # Stage 2 (SECTION tier): Expands single section (max_tokens 600)
    #   User asks about specific topic: day details, routes, budget, gear, etc.
    # Stage 2 (FULL tier): Complete detailed itinerary (max_tokens 1536)
    #   Only when user explicitly requests "full itinerary", "everything", etc.
    #
    # Stage 2 triggers only on explicit phrases - NOT on implicit confirmations.
    # NOTE: expansion_result and is_expansion_request already computed above in guard 2
    is_stage2 = is_expansion_request  # Alias for clarity

    if is_stage2:
        # Stage 2: User explicitly asked for expansion
        # Determine tier based on expansion target
        expansion_tier = expansion_result.tier or StrategyTier.SECTION
        expansion_target = expansion_result.target or StrategyExpansionTarget.ITINERARY_OUTLINE

        # Get max_tokens for this tier
        max_tokens = STRATEGY_TIER_MAX_TOKENS.get(expansion_tier, 768)

        # Use stage2 config but override max_tokens based on tier
        llm_config = _get_node_llm_config("strategy_stage2")
        llm_config["max_output_tokens"] = max_tokens

        stage_name = "stage2"
        _strategy_stats["stage2_calls"] += 1

        # Track tier-specific stats
        if expansion_tier == StrategyTier.FULL:
            _strategy_stats["tier_full"] += 1
        else:
            _strategy_stats["tier_section"] += 1

        # Track section-specific stats
        section_stat_map = {
            StrategyExpansionTarget.DAY_DETAILS: "section_day_details",
            StrategyExpansionTarget.ROUTES_TRAILS: "section_routes",
            StrategyExpansionTarget.LOGISTICS: "section_logistics",
            StrategyExpansionTarget.BUDGET: "section_budget",
            StrategyExpansionTarget.GEAR_PACKING: "section_gear",
            StrategyExpansionTarget.CONTINGENCIES: "section_contingencies",
        }
        if expansion_target in section_stat_map:
            _strategy_stats[section_stat_map[expansion_target]] += 1

        # Store tier/target in state for caching and session persistence
        state.strategy_expansion_tier = expansion_tier.value
        state.strategy_expansion_target = expansion_target.value

        _debug(
            "🔍 STRATEGY STAGE 2: Section expansion",
            topic=topic,
            tier=expansion_tier.value,
            target=expansion_target.value,
            max_tokens=max_tokens,
            matched_phrase=expansion_result.matched_phrase,
            stage="2",
        )
    else:
        # Stage 1: Initial strategy response (shortlist + skeleton)
        llm_config = _get_node_llm_config("strategy_stage1")
        stage_name = "stage1"
        expansion_tier = StrategyTier.OUTLINE
        expansion_target = None
        _strategy_stats["stage1_calls"] += 1
        _strategy_stats["tier_outline"] += 1
        _debug(
            "📋 STRATEGY STAGE 1: Generating shortlist + skeleton",
            topic=topic,
            pending_expansion=state.pending_strategy_expansion,
            stage="1",
        )

    # Use timeout and retry logic
    timeout = settings.llm_timeout_specialist
    attempts = settings.llm_max_retries
    last_error = None

    # Generate tone instruction using ToneAdapter (replaces _adapt_tone.txt include)
    user_intent = state.metadata.get("user_intent", "detailed_planner")
    user_tone = state.metadata.get("user_tone", "neutral")
    tone_instruction = ToneAdapter.get_instruction(user_intent, user_tone)

    prompt = load_prompt(prompt_name)

    # Phase 5: For Stage 1, strip verbose includes (_scope_specialist, _markdown_rules)
    # to reduce token count. Stage 1 only needs shortlist + skeleton, not full formatting.
    if not is_stage2:
        prompt = _strip_stage1_includes(prompt)
        # Add budget/season sanity checklist for Stage 1 to prevent correction triggers
        prompt = prompt + _STAGE1_SANITY_CHECKLIST

        # =====================================================================
        # DESTINATION-KNOWN MODE: Add context for destination-specific advice
        # =====================================================================
        # When strategy_dest_known is True, the user has already chosen a destination.
        # The LLM should provide destination-specific advice, NOT a shortlist of destinations.
        # =====================================================================
        dest_known_mode = state.metadata.get("strategy_dest_known", False)
        destinations = state.trip_inputs.destinations
        if dest_known_mode and destinations:
            dest_list = ", ".join(destinations)
            dest_context = (
                f"\n\n==============================\n"
                f"DESTINATION ALREADY CHOSEN: {dest_list}\n"
                f"==============================\n"
                f"The user has ALREADY selected {dest_list} as their destination.\n"
                f"DO NOT ask which destination they prefer or suggest alternative destinations.\n"
                f"Instead, provide:\n"
                f"1. Specific {topic} recommendations for {dest_list}\n"
                f"2. Best trails/routes/spots in this region\n"
                f"3. Seasonal considerations for their travel dates\n"
                f"4. Practical tips specific to {dest_list}\n"
                f"5. Ask about preferences (difficulty, duration, etc.) if needed\n\n"
            )
            prompt = prompt + dest_context
            _debug(
                "📍 STRATEGY_DEST_KNOWN: Added destination-specific context",
                destinations=destinations,
                topic=topic,
            )

    elif expansion_target and expansion_target != StrategyExpansionTarget.FULL_EXPANSION:
        # Stage 2 section expansion: Add focus instruction to prompt
        section_focus = (
            "\n\nFOCUS: User requested expansion of **"
            f"{expansion_target.value.replace('_', ' ')}"
            "** section only. Provide detailed content for this section. "
            "Do not repeat the full itinerary.\n"
        )
        prompt = prompt + section_focus

    # Use minimal state view for strategy (saves ~75% tokens vs full trip_inputs)
    strategy_state_view = StateViewBuilder.for_strategy(state)

    # =========================================================================
    # STAGE 2 SKELETON REUSE (Tier 3 optimization)
    # =========================================================================
    # For Stage 2, check if we have a cached Stage 1 skeleton.
    # If yes, use condensed context instead of full conversation_summary.
    # This saves ~1000-1500 tokens per Stage 2 expansion call.
    # =========================================================================
    if is_stage2 and state.metadata.get("stage1_skeleton"):
        cached_skeleton = state.metadata["stage1_skeleton"]
        skeleton_topic = state.metadata.get("stage1_skeleton_topic", topic)

        # Build condensed context with skeleton reference
        expansion_desc = (
            expansion_target.value.replace("_", " ") if expansion_target else "full itinerary"
        )
        conversation_context = (
            f"Previous {skeleton_topic} skeleton:\n"
            f"---\n{cached_skeleton[:1500]}{'...' if len(cached_skeleton) > 1500 else ''}\n---\n"
            f"User requested expansion of: {expansion_desc}"
        )
        _debug(
            "📦 STAGE2_SKELETON_REUSE: Using cached Stage 1 skeleton",
            topic=topic,
            skeleton_topic=skeleton_topic,
            skeleton_len=len(cached_skeleton),
            tokens_saved="~1000-1500 (vs full conversation_summary)",
        )
    else:
        # Fallback to full conversation summary (with caching via state)
        conversation_context = _generate_conversation_summary(state.chat_history, state=state)

    system_prompt = (
        prompt.replace("{trip_inputs}", json.dumps(strategy_state_view))
        .replace("{parsed_inputs}", json.dumps(state.parsed_inputs))
        .replace("{topic}", topic)
        .replace("{missing_fields}", _get_missing_fields_summary(state))
        .replace("{conversation_summary}", conversation_context)
        .replace("{tone_instruction}", tone_instruction)
    )

    # =========================================================================
    # STRATEGY CACHE CHECK (5-min TTL, topic + section keyed)
    # Key: (session_id, topic, section_id, core_fields_hash, user_text_hash)
    # Saves ~2000-3000 tokens when user asks similar strategy questions
    # Section-level caching prevents re-rendering when user tweaks one detail
    # =========================================================================
    session_id = state.session_id or "unknown"
    core_fields_hash = _get_core_fields_state(state.trip_inputs)
    user_text_hash = _hash_user_text(state.user_text or "")
    # Use section_id for Stage 2 expansions, None for Stage 1
    section_id = expansion_target.value if (is_stage2 and expansion_target) else None

    cached_strategy = _get_strategy_cached(
        session_id, topic, core_fields_hash, user_text_hash, state, section_id
    )
    if cached_strategy is not None:
        _debug(
            "📦 STRATEGY_CACHE_HIT: Using cached strategy response",
            topic=topic,
            session=f"{session_id[:8]}...",
            tokens_saved="~2000-3000 (strategy LLM call avoided)",
        )
        # Restore cached state
        state.last_summary = cached_strategy.get("assistant_message", "")
        state.suggested_responses = cached_strategy.get("suggested_responses", [])
        state.question_target = cached_strategy.get("question_target")

        # Apply cached strategy_settings
        if cached_strategy.get("strategy_settings"):
            current_ss = (
                dict(state.trip_inputs.strategy_settings)
                if state.trip_inputs.strategy_settings
                else {}
            )
            current_ss[topic] = cached_strategy["strategy_settings"]
            _write_trip_inputs(
                state, f"strategy:{topic}:cache", strategy_settings=current_ss
            )  # Ignore fields_changed

        state.metadata["strategy_path"] = f"cache:{topic}"
        # Set provenance for streaming mode decision (cached responses use simulate_streaming)
        state.metadata["response_writer_node"] = f"strategy_node:{topic}:cache"
        state.metadata["response_generation_provenance"] = "cached"
        _debug_node_exit("strategy_node", state, start_ns)
        return state

    tokens = _estimate_prompt_tokens(system_prompt, state.parsed_inputs)
    _record_node_tokens(state, f"strategy:{topic}", tokens, model=llm_config["model_hint"])

    # LLM Budget Gate: Return fallback if budget exhausted
    # Determine best fallback target from missing core fields
    fallback_target = None
    if not (state.trip_inputs.start_date and state.trip_inputs.end_date):
        fallback_target = "dates"
    elif not state.trip_inputs.destinations:
        fallback_target = "destinations"
    elif not state.trip_inputs.origin:
        fallback_target = "origin"

    if not can_call_llm(state, f"strategy:{topic}"):
        _debug(
            f"⚠️ strategy:{topic}: LLM budget exhausted, using fallback",
            fallback_target=fallback_target,
        )
        llm_blocked_fallback(
            state, asked_target=fallback_target, source=f"strategy:{topic}:budget_blocked"
        )
        return state

    for attempt in range(attempts):
        try:
            # Pass history as separate messages for better context
            async with measure_llm_call(state):
                out = await call_llm_with_timeout(
                    model=llm_config["model_hint"],
                    prompt=system_prompt,
                    timeout_seconds=timeout,
                    max_tokens=llm_config["max_tokens"],
                    temperature=llm_config["temperature"],
                    history=state.chat_history,
                    user_message=state.user_text,
                    top_p=llm_config["top_p"],
                )
            j = jloads_safe(out)

            # Handle strategy_settings specially (keyed by topic)
            strategy_data = j.get("strategy_settings", {})
            if strategy_data:
                current_ss = (
                    dict(state.trip_inputs.strategy_settings)
                    if state.trip_inputs.strategy_settings
                    else {}
                )
                current_ss[topic] = strategy_data
                _write_trip_inputs(
                    state, f"strategy:{topic}", strategy_settings=current_ss
                )  # Ignore fields_changed

            # Apply remaining trip_inputs delta using centralized helper
            # Strategy nodes should NOT overwrite core fields - only activity_settings
            delta = j.get("trip_inputs", {}) or {}
            _STRATEGY_SKIP_FIELDS = {
                "strategy_settings",  # Handled specially above
                "destinations",
                "origin",
                "start_date",
                "end_date",
                "adults",
                "children",
                "budget",
                "currency",
            }
            _apply_llm_delta(state, f"strategy:{topic}", delta, skip_fields=_STRATEGY_SKIP_FIELDS)

            # Validate the updated trip_inputs
            TRIP_VALIDATOR.validate(state.trip_inputs.model_dump())
            state.last_summary = j.get("assistant_message", "")

            # PR-C: Apply strategy output size limits
            # Use expansion cap for stage2, regular cap for stage0/stage1
            _strategy_cap = (
                settings.strategy_expansion_max_output_chars
                if stage_name == "stage2"
                else settings.strategy_max_output_chars
            )
            state.last_summary, _was_truncated = truncate_preserving_newlines(
                state.last_summary, _strategy_cap
            )
            if _was_truncated:
                state.metadata["strategy_truncated"] = True
                state.metadata["strategy_truncate_cap"] = _strategy_cap
                _debug(
                    "✂️ STRATEGY OUTPUT TRUNCATED",
                    stage=stage_name,
                    cap=_strategy_cap,
                    original_len=len(j.get("assistant_message", "")),
                    truncated_len=len(state.last_summary),
                )

            # Parse question_target from LLM response for suggestion relevance
            raw_question_target = j.get("question_target")
            if raw_question_target and isinstance(raw_question_target, str):
                normalized_target = raw_question_target.lower().strip()
                if normalized_target in QUESTION_TARGET_VALUES:
                    set_question_target(
                        state, normalized_target, source="strategy_node:llm_response"
                    )
                elif normalized_target == "null" or normalized_target == "none":
                    set_question_target(state, None, source="strategy_node:llm_null")
                else:
                    set_question_target(state, None, source="strategy_node:llm_unknown")
            else:
                set_question_target(state, None, source="strategy_node:no_target")

            # Filter suggested responses with relevance scoring
            raw_suggestions = j.get("suggested_responses", []) or []
            _debug(f"Raw LLM suggested_responses: {raw_suggestions}")
            state.suggested_responses = _get_suggestions_with_fallback(
                raw_suggestions, state, state.question_target
            )
            _debug_suggestions(state.suggested_responses, source="strategy_node")

            # Only set ready_to_generate if explicitly triggered
            state.ready_to_generate = bool(j.get("ready_to_generate", False)) and state.flags.get(
                "generate_requested", False
            )

            # Only emit branches if generate was explicitly requested
            if state.flags.get("generate_requested", False):
                raw_branches = j.get("branches", []) or []
                fallback = state.trip_inputs.model_dump(exclude_none=True)
                normalized_branches: List[Dict[str, Any]] = []
                for b in raw_branches:
                    normalized = _normalize_branch_spec(b, fallback)
                    if normalized:
                        normalized_branches.append(normalized)
                state.branches = normalized_branches

            state.metadata["model_used"] = llm_config["model_hint"]
            state.metadata["token_estimate"] = len(out) // 4  # Approximation
            state.metadata["strategy_stage"] = stage_name
            # Set provenance for streaming mode decision
            state.metadata["response_writer_node"] = f"strategy_node:{topic}:{stage_name}"
            state.metadata["response_generation_provenance"] = "llm"

            # =========================================================================
            # TWO-STAGE EXPANSION STATE MANAGEMENT
            # =========================================================================
            if stage_name == "stage1":
                # Stage 1 complete: Set pending expansion flag
                state.pending_strategy_expansion = True

                # Set Stage 1 lifecycle signature to prevent re-firing
                # Note: SuppressionPredicates is imported at module level (line 29)
                stage1_sig = SuppressionPredicates.compute_stage1_signature(
                    topic,
                    state.trip_inputs.destinations or [],
                    state.trip_inputs.origin,
                )
                state.metadata["stage1_completed_sig"] = stage1_sig

                # =====================================================================
                # STAGE 1 SKELETON CACHING (Tier 3 optimization)
                # =====================================================================
                # Cache Stage 1 output for Stage 2 context reuse.
                # When Stage 2 fires, it uses this cached skeleton instead of
                # regenerating full conversation_summary - saves ~1000-1500 tokens.
                # =====================================================================
                state.metadata["stage1_skeleton"] = state.last_summary
                state.metadata["stage1_skeleton_topic"] = topic

                # Add expansion prompt to suggestions
                if "Show more details" not in state.suggested_responses:
                    state.suggested_responses = ["Show more details"] + state.suggested_responses[
                        :2
                    ]
                _debug(
                    "📋 STRATEGY STAGE 1 COMPLETE: pending_strategy_expansion=True",
                    topic=topic,
                    stage1_sig=stage1_sig,
                    skeleton_cached=True,
                )
            elif stage_name == "stage2":
                # Stage 2 complete: Clear pending expansion flag
                state.pending_strategy_expansion = False
                _debug(
                    "🔍 STRATEGY STAGE 2 COMPLETE: Full itinerary delivered",
                    topic=topic,
                )

            # Cache the strategy result for future identical requests (5-min TTL)
            # Use section_id for section-level caching on Stage 2 expansions
            _set_strategy_cached(
                session_id,
                topic,
                core_fields_hash,
                user_text_hash,
                {
                    "assistant_message": state.last_summary,
                    "suggested_responses": state.suggested_responses,
                    "question_target": state.question_target,
                    "strategy_settings": j.get("strategy_settings", {}),
                    "expansion_tier": expansion_tier.value if expansion_tier else None,
                    "expansion_target": expansion_target.value if expansion_target else None,
                },
                section_id,
                state=state,  # V6: Pass state for lifecycle hash
            )

            _debug_node_exit("strategy_node", state, start_ns)
            return state

        except json.JSONDecodeError as e:
            last_error = e
            _debug_error(f"Strategy {topic} JSON error on attempt {attempt + 1}", error=str(e))

            # =====================================================================
            # JSON RECOVERY: Try to extract useful content from malformed response
            # =====================================================================
            # Before retrying with INVALID_JSON_HINT, attempt to salvage the message
            recovered_message = _extract_message_from_malformed_json(out if "out" in dir() else "")
            if recovered_message and len(recovered_message) > 50:
                _debug(
                    "📦 JSON_RECOVERY: Extracted message from malformed JSON",
                    topic=topic,
                    message_length=len(recovered_message),
                )
                state.last_summary = recovered_message

                # PR-C: Apply strategy output size limits to recovered message
                _strategy_cap = (
                    settings.strategy_expansion_max_output_chars
                    if stage_name == "stage2"
                    else settings.strategy_max_output_chars
                )
                state.last_summary, _was_truncated = truncate_preserving_newlines(
                    state.last_summary, _strategy_cap
                )
                if _was_truncated:
                    state.metadata["strategy_truncated"] = True
                    state.metadata["strategy_truncate_cap"] = _strategy_cap

                state.metadata["response_writer_node"] = f"strategy:{topic}:json_recovery"
                state.metadata["response_generation_provenance"] = "llm_fallback"
                state.metadata["strategy_stage"] = stage_name

                # Set pending expansion for stage 1 even on recovery
                if stage_name == "stage1":
                    state.pending_strategy_expansion = True
                    state.suggested_responses = ["Show more details", "What else should I know?"]

                    # Set Stage 1 lifecycle signature to prevent re-firing
                    # Note: SuppressionPredicates is imported at module level (line 29)
                    stage1_sig = SuppressionPredicates.compute_stage1_signature(
                        topic,
                        state.trip_inputs.destinations or [],
                        state.trip_inputs.origin,
                    )
                    state.metadata["stage1_completed_sig"] = stage1_sig

                    # Cache Stage 1 skeleton for Stage 2 reuse (even on recovery)
                    state.metadata["stage1_skeleton"] = state.last_summary
                    state.metadata["stage1_skeleton_topic"] = topic

                _debug_node_exit("strategy_node", state, start_ns)
                return state

            # If recovery failed, try again with hint
            if attempt < attempts - 1:
                system_prompt += INVALID_JSON_HINT
                continue
            break
        except Exception as e:
            last_error = e
            _debug_error(f"Strategy {topic} error on attempt {attempt + 1}", error=str(e))
            break

    reason = (
        f"strategy node for {topic} produced invalid output after {attempts} attempt(s): "
        f"{last_error}"
    )
    _debug_error(f"Strategy {topic} failed", reason=reason)
    return _record_llm_failure(state, reason)
