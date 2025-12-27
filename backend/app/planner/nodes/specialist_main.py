"""
Specialist Node - Shared handler for specialist nodes with JSON retry logic.

This module contains the _specialist function which handles all specialist nodes
(required_fields, flights, hotels, activities, transport, strategy, correction).

Extracted from plan_graph.py as part of the P6 module extraction initiative.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from app.plan_graph import GraphState


def _select_required_fields_prompt(state: "GraphState") -> str:
    """
    Select the appropriate prompt for required_fields based on state.

    Returns either:
    - required_fields_confirm: when typos/ambiguities need user confirmation
    - required_fields: for all other cases (collecting missing fields or confirming ready state)
    """
    # Late imports to avoid circular dependencies
    from app.plan_graph import load_prompt

    # Check for typos or ambiguous entities needing confirmation
    extraction_conf = state.metadata.get("extraction_confidence", {})
    typo_suggestions = extraction_conf.get("typo_suggestions", [])

    if typo_suggestions:
        # Use confirmation prompt for typo/ambiguity resolution
        return load_prompt("required_fields_confirm")

    # Check if budget needs clarification (qualitative value was dropped)
    prompt = load_prompt("required_fields")
    if state.metadata.get("budget_needs_clarification"):
        # Clear the flag and inject budget question
        state.metadata["budget_needs_clarification"] = False
        state.question_target = "budget"
        prompt += (
            "\n\nIMPORTANT: The user provided a qualitative budget description."
            " Ask them for an approximate budget in dollars/their currency."
        )

    return prompt


async def _invoke_missing_fields_guard(state: "GraphState", missing_fields: List[str]) -> bool:
    """
    Invoke the lightweight missing_fields_guard prompt to generate a question.

    This is called when a domain specialist is entered but core fields are missing.
    Uses a small model for minimal latency.

    Args:
        state: Current graph state (will be mutated with response)
        missing_fields: List of missing core field names

    Returns:
        True if guard was successful and state was updated, False on error
    """
    # Late imports to avoid circular dependencies
    import json

    from app.config import settings
    from app.debug_utils import _debug, _debug_error
    from app.graph_plan_utils import jloads_safe
    from app.plan_graph import (
        ToneAdapter,
        _count_tokens,
        _get_node_llm_config,
        _record_node_tokens,
        _record_structured_error,
        call_llm_with_timeout,
        can_call_llm,
        llm_blocked_fallback,
        load_prompt,
        set_question_target,
        store_suggestions_with_field,
        ti_short,
    )
    from app.planner.nodes.llm_utils import measure_llm_call

    llm_config = _get_node_llm_config("missing_fields_guard")

    # Generate tone instruction using ToneAdapter (replaces _adapt_tone.txt include)
    user_intent = state.metadata.get("user_intent", "detailed_planner")
    user_tone = state.metadata.get("user_tone", "neutral")
    tone_instruction = ToneAdapter.get_instruction(user_intent, user_tone)

    prompt = load_prompt("missing_fields_guard")
    system_prompt = (
        prompt.replace("{missing_fields}", ", ".join(missing_fields))
        .replace("{trip_inputs}", json.dumps(ti_short(state.trip_inputs)))
        .replace("{tone_instruction}", tone_instruction)
    )

    tokens = _count_tokens(system_prompt)
    _record_node_tokens(state, "missing_fields_guard", tokens, model=llm_config["model_hint"])

    # LLM Budget Gate: Return fallback if budget exhausted
    if not can_call_llm(state, "missing_fields_guard"):
        # Determine best fallback target from missing_fields
        if "dates" in missing_fields or "start_date" in missing_fields:
            fallback_target = "dates"
        elif "destinations" in missing_fields:
            fallback_target = "destinations"
        elif "origin" in missing_fields:
            fallback_target = "origin"
        else:
            fallback_target = missing_fields[0] if missing_fields else "dates"
        _debug(
            f"missing_fields_guard: LLM budget exhausted, using fallback for {fallback_target}",
            missing_fields=missing_fields,
        )
        llm_blocked_fallback(
            state, asked_target=fallback_target, source="missing_fields_guard:budget_blocked"
        )
        return True

    # Check if we're in date_clarify_mode - if so, force dates question
    in_date_clarify_mode = state.metadata.get("date_clarify_mode", False)
    has_blocking_errors = bool(state.metadata.get("date_blocking_errors"))

    try:
        async with measure_llm_call(state):
            out = await call_llm_with_timeout(
                model=llm_config["model_hint"],
                prompt=system_prompt,
                timeout_seconds=settings.llm_timeout_specialist,
                max_tokens=llm_config["max_tokens"],
                temperature=llm_config["temperature"],
                history=[],
                user_message="",
                top_p=llm_config["top_p"],
            )

        j = jloads_safe(out)

        state.last_summary = j.get("assistant_message", "Where would you like to go?")
        state.suggested_responses = j.get("suggested_responses", [])[:3]
        llm_question_target = j.get(
            "question_target", missing_fields[0] if missing_fields else None
        )

        # Enforce date_clarify_mode: refuse field switching when dates have blocking errors
        if in_date_clarify_mode or has_blocking_errors:
            if llm_question_target and llm_question_target not in (
                "dates",
                "start_date",
                "end_date",
            ):
                _debug(
                    "Missing fields guard: refusing field switch during date_clarify_mode",
                    llm_target=llm_question_target,
                    forced_target="dates",
                )
                set_question_target(state, "dates", source="missing_fields_guard:date_clarify")
            else:
                set_question_target(state, llm_question_target, source="missing_fields_guard:llm")
        else:
            set_question_target(state, llm_question_target, source="missing_fields_guard:llm")

        # Map question_target to last_question_field for short-circuit context
        target_to_field = {
            "destinations": "destinations",
            "origin": "origin",
            "dates": "start_date",
            "start_date": "start_date",
        }
        state.metadata["last_question_field"] = target_to_field.get(
            state.question_target, state.question_target
        )

        # Track that response was produced this turn (no-stale-summary invariant)
        state.metadata["last_response_turn"] = state.turn_number

        _debug(
            "Missing fields guard response",
            response_preview=state.last_summary[:50] if state.last_summary else "",
            suggestions=state.suggested_responses,
        )
        return True

    except Exception as e:
        _debug_error("Missing fields guard failed", error=str(e))
        # Record error for proper accounting (errors_count)
        _record_structured_error(
            state,
            code="GUARD_LLM_FAILED",
            node="missing_fields_guard",
            message=str(e),
            severity="warning",
        )
        # Fallback to a simple question (deterministic recovery)
        if "destinations" in missing_fields:
            state.last_summary = "Where are you looking to go?"
            state.suggested_responses = ["Bali, Indonesia", "Paris, France", "Tokyo, Japan"]
            set_question_target(state, "destinations", source="missing_fields_guard:fallback")
            store_suggestions_with_field(state, state.suggested_responses, "destinations")
        elif "origin" in missing_fields:
            state.last_summary = "Where will you be flying from?"
            state.suggested_responses = ["New York", "London", "Los Angeles"]
            set_question_target(state, "origin", source="missing_fields_guard:fallback")
            store_suggestions_with_field(state, state.suggested_responses, "origin")
        else:
            state.last_summary = "When are you looking to travel?"
            state.suggested_responses = ["Next month", "December 20-27", "First week of January"]
            set_question_target(state, "dates", source="missing_fields_guard:fallback")
            store_suggestions_with_field(state, state.suggested_responses, "dates")
        # Track that response was produced this turn (no-stale-summary invariant)
        state.metadata["last_response_turn"] = state.turn_number
        return True


async def _specialist(
    name: str, state: "GraphState", retry_on_json_error: bool = True
) -> "GraphState":
    """
    Shared handler for specialist nodes with JSON retry logic.

    Args:
        name: Prompt name to load (also used to look up per-node LLM config).
        state: Current graph state.
        retry_on_json_error: If True, attempt one repair retry on JSON parse failure.
    """
    # Late imports to avoid circular dependencies
    import json
    from typing import Any, Dict, Optional

    from app.config import settings
    from app.debug_utils import _debug, _debug_error, _debug_suggestions
    from app.graph_plan_utils import jloads_safe
    from app.plan_graph import (
        FALLBACK_SUGGESTIONS,
        INVALID_JSON_HINT,
        QUESTION_TARGET_VALUES,
        TRIP_VALIDATOR,
        StateViewBuilder,
        ToneAdapter,
        _apply_llm_delta,
        _compute_cache_key,
        _count_tokens,
        _debug_cache_hit,
        _debug_node_entry,
        _debug_node_exit,
        _estimate_prompt_tokens,
        _follow_up_cache,
        _generate_conversation_summary,
        _get_cached_response,
        _get_core_fields_state,
        _get_missing_fields_summary,
        _get_node_llm_config,
        _get_suggestions_with_fallback,
        _get_template_response,
        _increment_state_counter,
        _maybe_append_safety_snippet,
        _normalize_branch_spec,
        _record_llm_failure,
        _record_node_tokens,
        _set_cached_response,
        _today_iso,
        call_llm_with_timeout,
        can_call_llm,
        get_available_options_context,
        llm_blocked_fallback,
        load_prompt,
        load_specialist_prompt,
        set_question_target,
        store_suggestions_with_field,
        ti_short,
        track_question_asked,
    )
    from app.planner.gates.constants import CORE_FIELD_PRIORITY
    from app.planner.gates.readiness import compute_trip_readiness
    from app.planner.nodes.llm_utils import measure_llm_call
    from app.planner.nodes.specialist.guards import (
        apply_noop_gate_response,
        check_core_field_guard,
        check_default_adults_gate,
        check_domain_keyword_for_default_adults,
        check_noop_gate,
    )
    from app.planner.nodes.specialist.templates import (
        apply_template_response,
        check_requires_llm,
        determine_question_target,
        handle_loop_guard,
    )

    _, start_ns = _debug_node_entry(f"specialist:{name}", state)

    # =========================================================================
    # HARD GATE: Block ALL domain specialists if core fields are missing
    # =========================================================================
    # This is a HARD GATE - no exceptions. Specialists should never run without
    # core fields (destinations, origin, start_date). This saves ~1000-2000 tokens
    # per specialist call that would otherwise be wasted.
    #
    # The gate applies to: flights, hotels, activities, transport, strategy
    # Exempt: required_fields (collects core fields), correction (fixes infeasibilities)
    #
    # Exception: PRE-CORE MODE
    # When specialist_pre_core_enabled, specialists can handle requests even with
    # missing core fields by acknowledging intent and asking for missing fields inline.
    missing_core = check_core_field_guard(name, state)
    if missing_core is not None:
        # Check if we're in pre-core mode (routed here intentionally)
        pre_core_mode = state.metadata.get("pre_core_mode", False)

        if pre_core_mode and settings.specialist_pre_core_enabled:
            # =====================================================================
            # PRE-CORE MODE (MVP): Deterministic response - bypass LLM entirely
            # =====================================================================
            # Instead of invoking LLM, generate a template-based response that:
            # 1. Acknowledges the user's intent/topic
            # 2. Asks for the next missing core field deterministically
            # 3. Provides template suggestions
            _debug(
                f"PRE-CORE MODE (DETERMINISTIC): {name} bypassing LLM",
                specialist=name,
                missing=missing_core,
                tokens_saved="~1000-2000 (specialist LLM call avoided)",
            )
            state.metadata["specialist_pre_core_active"] = True
            state.metadata["specialist_pre_core_deterministic"] = True

            # Determine next missing field using priority order
            question_target = None
            for field in CORE_FIELD_PRIORITY:
                # Normalize field names for comparison
                check_field = field
                if field == "start_date":
                    check_field = "start_date"
                if check_field in missing_core or field in missing_core:
                    question_target = "dates" if field == "start_date" else field
                    break

            if not question_target and missing_core:
                question_target = (
                    "destinations" if "destinations" in missing_core else missing_core[0]
                )

            # Build acknowledgment based on specialist type and user text
            topic_acknowledgments = {
                "hotels": "hotels and accommodation",
                "flights": "flights",
                "activities": "activities and things to do",
                "transport": "transportation",
                "strategy": state.strategy_topic or "trip planning",
            }
            topic_name = topic_acknowledgments.get(name, name)

            # Get template question and suggestions
            template_response = _get_template_response(question_target, state.strategy_topic)
            if template_response:
                question = template_response["question"]
                suggestions = template_response["suggestions"][:3]
            else:
                # Fallback question
                question = (
                    "Where would you like to go?"
                    if question_target == "destinations"
                    else f"Could you tell me your {question_target}?"
                )
                suggestions = FALLBACK_SUGGESTIONS.copy()

            # Build warm acknowledgment + question
            state.last_summary = f"I'd love to help you find great {topic_name}! {question}"
            state.suggested_responses = suggestions
            set_question_target(state, question_target, source=f"specialist:{name}:pre_core")
            state.metadata["last_question_field"] = question_target
            state.metadata["from_template"] = True
            state.metadata["pre_core_deterministic_path"] = f"{name}:{question_target}"

            # Track question for loop guard
            track_question_asked(state, question_target, state.last_summary)

            # Set provenance for final response tracking (pre-core deterministic)
            state.metadata["response_writer_node"] = f"specialist:{name}:pre_core"
            state.metadata["response_generation_provenance"] = "template"

            _debug(
                f"PRE-CORE DETERMINISTIC: {name} -> {question_target}",
                question=state.last_summary[:80],
                suggestions=suggestions,
            )
            _debug_node_exit(f"specialist:{name}", state, start_ns)
            return state
        else:
            _debug(
                f"SPECIALIST_GATE: {name} BLOCKED (core fields missing)",
                specialist=name,
                missing=missing_core,
                tokens_saved=f"~1000-2000 ({name} LLM call avoided)",
            )
            state.metadata["specialist_gate_triggered"] = name
            state.metadata["specialist_gate_missing"] = missing_core

            # Use small prompt to generate a warm question with suggestions
            guard_result = await _invoke_missing_fields_guard(state, missing_core)
            if guard_result:
                _debug_node_exit(f"specialist:{name}", state, start_ns)
                return state

    # =========================================================================
    # DEFAULT ADULTS LOGIC: When core complete but adults missing, default to 1
    # =========================================================================
    # Uses extracted guard function from specialist.guards module.
    check_default_adults_gate(name, state)

    # =========================================================================
    # NO-OP SPECIALIST GATE: Skip LLM for vague affirmations
    # =========================================================================
    # Uses extracted guard functions from specialist.guards module.
    if check_noop_gate(name, state):
        apply_noop_gate_response(state, name)
        _debug_node_exit(f"specialist:{name}", state, start_ns)
        return state

    # Get per-node LLM configuration
    llm_config = _get_node_llm_config(name)

    # =========================================================================
    # REQUIRED_FIELDS: TEMPLATE-FIRST APPROACH
    # =========================================================================
    # Templates are the PRIMARY path for required_fields. LLM is fallback only.
    # This saves ~900-1500 tokens per turn on simple field collection.
    if name == "required_fields":
        # =====================================================================
        # DEFAULT ADULTS LOGIC (also applies in required_fields)
        # =====================================================================
        # When core fields are complete but adults is missing, and user has a
        # domain keyword in their message, default adults to 1 and route to
        # the appropriate specialist instead of asking about travelers.
        ti = state.trip_inputs
        has_destination = bool(ti.destinations)
        has_dates = bool(ti.start_date)
        has_adults = ti.adults is not None and ti.adults > 0
        core_complete = has_destination and bool(ti.origin) and has_dates

        if settings.default_adults_enabled and core_complete and not has_adults:
            # Check if user message contains a domain keyword using extracted function
            detected_domain = check_domain_keyword_for_default_adults(state)
            if detected_domain:
                # Default adults to 1 and mark for specialist routing
                _debug(
                    "DEFAULT_ADULTS in required_fields: Setting adults=1",
                    detected_domain=detected_domain,
                    destinations=ti.destinations,
                    user_text_preview=(state.user_text or "")[:50],
                )
                state.trip_inputs.adults = 1
                state.metadata["adults_defaulted"] = True
                state.metadata["adults_default_reason"] = "core_complete_with_domain_keyword"
                # Set intent so routing picks up the right specialist
                state.intent = detected_domain
                state.metadata["deferred_intent"] = detected_domain
                # Return early - let the routing mechanism handle it
                _debug_node_exit(f"specialist:{name}", state, start_ns)
                return state

        # =====================================================================
        # TEMPLATE-FIRST PATH: Use extracted functions from specialist.templates
        # =====================================================================
        # Determine question_target based on missing fields (handles stale targets)
        question_target = determine_question_target(state)

        # Check if LLM is required (typos, ambiguity, multi-city)
        requires_llm, llm_reason = check_requires_llm(state, question_target)

        if not requires_llm and question_target:
            # Handle loop guard (prevents repeated questions)
            should_skip, alt_target = handle_loop_guard(state, question_target)
            if should_skip:
                _debug_node_exit(f"specialist:{name}", state, start_ns)
                return state
            if alt_target:
                question_target = alt_target

            # Try template path - returns True if applied
            if apply_template_response(state, question_target, name):
                _debug_node_exit(f"specialist:{name}", state, start_ns)
                return state
            else:
                llm_reason = f"no_template_for:{question_target}"

        if requires_llm:
            _debug(
                "LLM PATH: Required fields requires LLM",
                reason=llm_reason,
                question_target=question_target,
            )

        # Cache check (only if we're going to LLM anyway)
        cache_key: Optional[str] = None
        core_fields = _get_core_fields_state(state.trip_inputs)
        user_intent = state.metadata.get("user_intent", "detailed_planner")
        # Include budget_answered flag in cache key to avoid returning stale
        # "what's your budget?" responses after user said "no specific budget"
        budget_answered_str = "budget_answered" if state.metadata.get("budget_answered") else ""
        cache_key = _compute_cache_key(
            "required_fields", core_fields, user_intent, budget_answered_str
        )
        cached = _get_cached_response(_follow_up_cache, cache_key, state)
        if cached is not None:
            _debug_cache_hit("required_fields", cache_key[:16])
            cached_message = cached.get("assistant_message", "")

            # Check if there's a failed input message to prepend
            failed_msg = state.metadata.get("failed_input_message")
            if failed_msg:
                state.last_summary = f"{failed_msg}\n\n{cached_message}"
                # Clear the message so it's not repeated on next turn
                state.metadata.pop("failed_input_message", None)
                _debug("Prepended failed_input_message to cached response")
            else:
                state.last_summary = cached_message

            state.question_target = cached.get("question_target")
            state.suggested_responses = cached.get("suggested_responses", [])
            summary_snippet = state.last_summary[:50] if state.last_summary else ""
            _debug(f"Required fields cache hit: {summary_snippet}")
            state.metadata["required_fields_path"] = "cache"
            # Set provenance for final response tracking (cached path)
            state.metadata["response_writer_node"] = f"specialist:{name}:cache"
            state.metadata["response_generation_provenance"] = "cached"
            _debug_node_exit(f"specialist:{name}", state, start_ns)
            return state
    else:
        cache_key = None

    # Get today's date for prompt injection
    today_iso = state.metadata.get("today_iso") or _today_iso()

    # Get extraction confidence for confirmation prompts
    extraction_conf = state.metadata.get("extraction_confidence", {})
    confidence_level = extraction_conf.get("level", "unknown")
    typo_suggestions = extraction_conf.get("typo_suggestions", [])

    # Build extraction sources summary from parsed_inputs
    parsed = state.parsed_inputs or {}
    extraction_sources = {
        "destinations": parsed.get("destinations_source"),
        "origin": parsed.get("origin_source"),
        "budget": parsed.get("budget_source"),
        "travelers": parsed.get("travelers_source"),
        "dates": parsed.get("dates_source"),
        "duration": parsed.get("duration_source"),
    }
    # Filter out None values for cleaner output
    extraction_sources = {k: v for k, v in extraction_sources.items() if v}

    # Preserve the current trip_inputs snapshot for fallback normalization
    ti = state.trip_inputs

    # Use split prompts for required_fields to reduce token usage
    # Phase 6: Use load_specialist_prompt for domain specialists (conditional stripping)
    specialist_types = {"flights", "hotels", "transport", "activities"}
    if name == "required_fields":
        prompt = _select_required_fields_prompt(state)
    elif name in specialist_types:
        prompt = load_specialist_prompt(name, state)
    else:
        prompt = load_prompt(name)

    # =========================================================================
    # STATE VIEW: Use minimal state views to reduce token usage
    # =========================================================================
    # Instead of passing full trip_inputs (~50 fields), pass only what the node needs.
    if name == "required_fields":
        state_view = StateViewBuilder.for_required_fields(state)
        view_type = "required_fields"
    elif name in specialist_types:
        state_view = StateViewBuilder.for_specialist(state, name)
        view_type = name
    elif name == "strategy":
        state_view = StateViewBuilder.for_strategy(state)
        view_type = "strategy"
    elif name == "correction":
        # Correction needs core fields + all settings for conflict detection
        state_view = StateViewBuilder.for_correction(state)
        view_type = "correction"
    else:
        # Fallback to full state for unknown nodes - this should be avoided
        state_view = ti_short(state.trip_inputs)
        view_type = "full"
        _debug(
            f"StateView:FALLBACK:{name}",
            message="Using full state view - consider adding dedicated builder method",
        )

    # Phase 6: Validate state view size to catch regressions
    StateViewBuilder.validate_view(state_view, name)

    # Calculate token savings
    full_state_size = len(json.dumps(ti_short(state.trip_inputs)))
    view_size = len(json.dumps(state_view))
    tokens_saved_estimate = (full_state_size - view_size) // 4  # ~4 chars per token

    _debug(
        f"StateView applied: {view_type}",
        full_size=full_state_size,
        view_size=view_size,
        tokens_saved_estimate=tokens_saved_estimate,
    )

    # Generate tone instruction using ToneAdapter (replaces _adapt_tone.txt include)
    user_intent = state.metadata.get("user_intent", "detailed_planner")
    user_tone = state.metadata.get("user_tone", "neutral")
    tone_instruction = ToneAdapter.get_instruction(user_intent, user_tone)

    # Get available options context for grounded responses (tiles data)
    available_options = get_available_options_context(state, name)

    # =========================================================================
    # GROUNDEDNESS GUARDRAIL: Track when we suppress invented details
    # =========================================================================
    # Increment invented_detail_block_count ONLY when ALL conditions are true:
    # 1. Intent is grounding-required: hotels|flights|activities
    # 2. User asked for concrete options OR specialist in "recommendation mode"
    # 3. available_options_context is empty or invalid
    # 4. Specialist output policy explicitly suppresses naming/pricing
    groundedness_warning = ""
    tile_based_specialists = {"hotels", "flights", "activities"}

    if name in tile_based_specialists:
        options_empty = not available_options.strip()
        options_invalid = available_options.strip() and "error" in available_options.lower()

        # Check if user asked for options or specialist is in recommendation mode
        user_text_lower = (state.user_text or "").lower()
        user_asked_for_options = any(
            phrase in user_text_lower
            for phrase in [
                "recommend",
                "suggest",
                "options",
                "choices",
                "what about",
                "show me",
                "find me",
                "any good",
                "best",
                "where to stay",
                "which hotel",
                "which flight",
                "which activit",
            ]
        )
        pre_core_mode = state.metadata.get("pre_core_mode") if state.metadata else False

        # In pre_core_mode, the specialist focuses on collecting missing fields,
        # NOT on providing recommendations. So we should NOT trigger groundedness
        # warnings in pre_core_mode - the specialist will ask for destinations/dates first.
        recommendation_mode = user_asked_for_options and not pre_core_mode

        if (options_empty or options_invalid) and recommendation_mode:
            # Determine reason for blocking
            if options_empty:
                block_reason = "no_tiles"
            elif options_invalid:
                block_reason = "tiles_invalid"
            else:
                block_reason = "tiles_stale"

            groundedness_warning = (
                "\n\nGROUNDEDNESS CONSTRAINT\n"
                "No verified options are currently available for this category.\n"
                "DO NOT invent or fabricate specific names, prices, or details.\n"
                "Instead, acknowledge the request and explain that specific options "
                "are being searched for or will be available shortly.\n"
            )

            # Track with proper tags for observability
            _increment_state_counter("invented_detail_block_count")
            _debug(
                "[GROUNDEDNESS] Blocking potential invention due to missing tiles",
                intent=name,
                node=f"specialist:{name}",
                pre_core_mode=pre_core_mode,
                reason=block_reason,
                user_asked_for_options=user_asked_for_options,
            )

            # Store tags in metadata for downstream analysis
            if state.metadata is None:
                state.metadata = {}
            groundedness_blocks = state.metadata.get("groundedness_blocks", [])
            groundedness_blocks.append(
                {
                    "intent": name,
                    "node": f"specialist:{name}",
                    "pre_core_mode": pre_core_mode,
                    "reason": block_reason,
                    "turn": state.turn_number,
                }
            )
            state.metadata["groundedness_blocks"] = groundedness_blocks

    # Format questions_already_asked for loop prevention in required_fields specialist
    questions_already_asked = "None yet"
    if hasattr(state, "questions_asked") and state.questions_asked:
        asked_list = [f"{field} (asked {count}x)" for field, count in state.questions_asked.items()]
        questions_already_asked = ", ".join(asked_list) if asked_list else "None yet"

    system_prompt = (
        prompt.replace("{trip_inputs}", json.dumps(state_view))
        .replace("{parsed_inputs}", json.dumps(state.parsed_inputs))
        .replace("{today}", today_iso)
        .replace("{user_intent_hint}", user_intent)
        .replace("{user_tone}", user_tone)
        .replace("{tone_instruction}", tone_instruction)
        .replace("{extraction_confidence}", confidence_level)
        .replace("{typo_suggestions}", json.dumps(typo_suggestions) if typo_suggestions else "none")
        .replace(
            "{extraction_sources}", json.dumps(extraction_sources) if extraction_sources else "{}"
        )
        .replace("{missing_fields}", _get_missing_fields_summary(state))
        .replace("{conversation_summary}", _generate_conversation_summary(state.chat_history))
        .replace("{available_options}", available_options + groundedness_warning)
        .replace("{questions_already_asked}", questions_already_asked)
    )

    # Determine timeout based on model type
    timeout = settings.llm_timeout_specialist
    attempts = settings.llm_max_retries if retry_on_json_error else 1
    last_error = None

    tokens = _estimate_prompt_tokens(system_prompt, state.parsed_inputs)
    _record_node_tokens(state, f"specialist:{name}", tokens, model=llm_config["model_hint"])

    # LLM Budget Gate: Return fallback if budget exhausted
    if not can_call_llm(state, f"specialist:{name}"):
        _debug(
            f"specialist:{name}: LLM budget exhausted, using fallback for {question_target}",
            question_target=question_target,
        )
        llm_blocked_fallback(
            state, asked_target=question_target, source=f"specialist:{name}:budget_blocked"
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

            # Debug: log raw LLM response
            _debug(
                f"Specialist {name} LLM response",
                assistant_message=(
                    j.get("assistant_message", "<MISSING>")[:100]
                    if j.get("assistant_message")
                    else "<EMPTY>"
                ),
            )

            # Capture assistant_message early - even if field processing fails, we want this
            assistant_msg = j.get("assistant_message", "")
            if assistant_msg:
                state.last_summary = assistant_msg

            # Apply trip_inputs delta using centralized helper
            delta = j.get("trip_inputs", {}) or {}

            # Handle strategy_hint separately - it belongs in parsed_inputs, not trip_inputs
            # (LLM may return it in trip_inputs when confirming strategy intent)
            if "strategy_hint" in delta:
                strategy_hint = delta.pop("strategy_hint")
                if strategy_hint and isinstance(strategy_hint, str):
                    state.parsed_inputs["strategy_hint"] = strategy_hint
                    _debug(f"Captured strategy_hint from LLM: {strategy_hint}")

            # Domain specialists (flights, hotels, activities, transport) should not overwrite
            # core fields extracted by the extractor. Only required_fields and correction can
            # modify these fields (required_fields for collection, correction for fixing
            # infeasibility).
            _CORE_FIELDS = {
                "destinations",
                "origin",
                "start_date",
                "end_date",
                "adults",
                "children",
                "budget",
                "currency",
            }

            # Correction node can only modify core fields + specific correction-relevant fields
            # This prevents over-broad changes from correction requests
            _CORRECTION_ALLOWED_FIELDS = {
                "destinations",
                "origin",
                "start_date",
                "end_date",
                "adults",
                "children",
                "budget",
                "currency",
                # Allow removal of specific settings if user explicitly rejects
                "flight_settings",
                "hotel_settings",
                "transport_settings",
                "activity_settings",
            }

            # Fields that correction should NEVER modify (to prevent scope creep)
            _CORRECTION_SKIP_FIELDS = {
                "strategy_settings",  # Strategy is complex, shouldn't be corrected inline
                "booking_types",  # Auto-managed, not user-correctable
            }

            # required_fields can modify all fields; correction has restricted scope
            if name == "required_fields":
                skip_fields = None  # Allow all field modifications
            elif name == "correction":
                skip_fields = _CORRECTION_SKIP_FIELDS  # Block specific fields
                _debug(
                    "Correction node field permissions",
                    allowed="core + settings",
                    blocked=list(_CORRECTION_SKIP_FIELDS),
                )
            else:
                skip_fields = _CORE_FIELDS  # Domain specialists: block core fields
            _apply_llm_delta(state, f"specialist:{name}", delta, skip_fields=skip_fields)

            # Validate the updated trip_inputs
            TRIP_VALIDATOR.validate(state.trip_inputs.model_dump())
            llm_message = j.get("assistant_message", "")

            # Check if there's a failed input message to prepend
            failed_msg = state.metadata.get("failed_input_message")
            if failed_msg:
                state.last_summary = f"{failed_msg}\n\n{llm_message}"
                # Clear the message so it's not repeated on next turn
                state.metadata.pop("failed_input_message", None)
                _debug("Prepended failed_input_message to LLM response")
            else:
                state.last_summary = llm_message

            # Early safety snippet injection for international travel
            # This triggers as soon as we have destination+origin, not just at summarize
            if state.last_summary and state.trip_inputs.destinations:
                state.last_summary = _maybe_append_safety_snippet(state)

            # Parse question_target from LLM response for suggestion relevance
            raw_question_target = j.get("question_target")
            if raw_question_target and isinstance(raw_question_target, str):
                normalized_target = raw_question_target.lower().strip()
                if normalized_target in QUESTION_TARGET_VALUES:
                    # =========================================================================
                    # VALIDATION: Prevent LLM from asking about already-set fields
                    # =========================================================================
                    # The LLM may hallucinate and ask about a field that's already set.
                    # This fix validates the question_target against trip_inputs and overrides
                    # if the field is already populated. When this happens, we also replace
                    # the response with a template to avoid showing the wrong question.
                    # =========================================================================
                    ti = state.trip_inputs

                    # Map question_target to field check - covers ALL core field targets
                    # Note: "activities" and "general" are domain targets, not core fields,
                    # so they don't need the "already set" check
                    _QUESTION_TARGET_FIELD_CHECK = {
                        "dates": lambda t: bool(t.start_date),
                        "start_date": lambda t: bool(t.start_date),  # alias
                        "end_date": lambda t: bool(t.end_date),
                        "destinations": lambda t: bool(t.destinations),
                        "origin": lambda t: bool(t.origin),
                        "travelers": lambda t: t.adults is not None,
                        "adults": lambda t: t.adults is not None,  # alias
                        "budget": lambda t: t.budget is not None,
                        "currency": lambda t: bool(t.currency),
                    }

                    field_check = _QUESTION_TARGET_FIELD_CHECK.get(normalized_target)
                    field_is_set = field_check(ti) if field_check else False

                    if field_is_set:
                        # LLM asked about a field that's already set - override to next missing
                        readiness = compute_trip_readiness(ti, metadata=state.metadata)
                        corrected_target = readiness.question_target
                        _debug(
                            "LLM_QUESTION_TARGET_OVERRIDE: LLM asked about already-set field",
                            llm_target=normalized_target,
                            corrected_target=corrected_target,
                            start_date=ti.start_date,
                            origin=ti.origin,
                            destinations=ti.destinations,
                        )
                        normalized_target = corrected_target

                        # Also replace the response with a template for the corrected target
                        # to avoid showing the user a question about an already-set field
                        if corrected_target:
                            template_response = _get_template_response(
                                corrected_target, state.strategy_topic
                            )
                            if template_response:
                                state.last_summary = template_response["question"]
                                state.suggested_responses = template_response["suggestions"]
                                store_suggestions_with_field(
                                    state, template_response["suggestions"], corrected_target
                                )
                                _debug(
                                    "LLM_RESPONSE_REPLACED: Using template for corrected target",
                                    corrected_target=corrected_target,
                                    question=template_response["question"][:50],
                                )

                    if normalized_target:
                        set_question_target(
                            state, normalized_target, source=f"specialist:{name}:llm_response"
                        )
                        # Track this question for loop guard
                        track_question_asked(state, normalized_target, state.last_summary)
                    else:
                        set_question_target(state, None, source=f"specialist:{name}:llm_all_set")
                elif normalized_target == "null" or normalized_target == "none":
                    set_question_target(state, None, source=f"specialist:{name}:llm_null")
                else:
                    _debug(f"Unknown question_target from LLM: {raw_question_target}")
                    set_question_target(state, None, source=f"specialist:{name}:llm_unknown")
            else:
                set_question_target(state, None, source=f"specialist:{name}:no_target")

            # Filter suggested responses with contextual fallback
            raw_suggestions = j.get("suggested_responses", []) or []
            _debug(f"Raw LLM suggested_responses: {raw_suggestions}")
            state.suggested_responses = _get_suggestions_with_fallback(
                raw_suggestions, state, state.question_target
            )
            _debug_suggestions(state.suggested_responses, source=f"specialist:{name}")

            # Only set ready_to_generate if explicitly triggered
            state.ready_to_generate = bool(j.get("ready_to_generate", False)) and state.flags.get(
                "generate_requested", False
            )

            # Only emit branches if generate was explicitly requested
            if state.flags.get("generate_requested", False):
                raw_branches = j.get("branches", []) or []
                fallback = ti.model_dump(exclude_none=True)
                normalized_branches: List[Dict[str, Any]] = []
                for b in raw_branches:
                    normalized = _normalize_branch_spec(b, fallback)
                    if normalized:
                        normalized_branches.append(normalized)
                state.branches = normalized_branches

            state.metadata["model_used"] = llm_config["model_hint"]
            state.metadata["token_estimate"] = _count_tokens(out)

            # Set provenance for final response tracking (LLM path)
            state.metadata["response_writer_node"] = f"specialist:{name}"
            state.metadata["response_generation_provenance"] = "llm"

            # Cache the response for required_fields node
            if name == "required_fields" and cache_key is not None:
                _set_cached_response(
                    _follow_up_cache,
                    cache_key,
                    {
                        "assistant_message": state.last_summary,
                        "question_target": state.question_target,
                        "suggested_responses": state.suggested_responses,
                    },
                )
                # Record path trace for required_fields
                state.metadata["required_fields_path"] = "llm"

            _debug(
                f"Specialist {name} completed",
                ready=state.ready_to_generate,
                branches=len(state.branches),
            )
            _debug_node_exit(f"specialist:{name}", state, start_ns)
            return state

        except json.JSONDecodeError as e:
            last_error = e
            _debug_error(f"Specialist {name} JSON error on attempt {attempt + 1}", error=str(e))
            if attempt < attempts - 1:
                # Add repair hint to prompt for retry
                system_prompt += INVALID_JSON_HINT
                continue
            break
        except TimeoutError as e:
            last_error = e
            _debug_error(f"Specialist {name} timeout on attempt {attempt + 1}")
            break
        except Exception as e:
            last_error = e
            _debug_error(f"Specialist {name} error on attempt {attempt + 1}", error=str(e))
            break

    reason = f"{name} node produced invalid output after {attempts} attempt(s): {last_error}"
    _debug_error(f"Specialist {name} failed", reason=reason)
    return _record_llm_failure(state, reason)
