"""
Specialist Node - Shared handler for specialist nodes with JSON retry logic.

This module contains the _specialist function which handles all specialist nodes
(required_fields, flights, hotels, activities, transport, strategy, correction).

Extracted from plan_graph.py as part of the P6 module extraction initiative.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, List

# P2: Module-level imports for non-circular dependencies
from app.config import settings
from app.debug_utils import _debug, _debug_error
from app.graph_plan_utils import jloads_safe
from app.planner.nodes.llm_utils import measure_llm_call
from app.planner.nodes.specialist.groundedness import check_groundedness_guardrail
from app.planner.nodes.specialist.guards import (
    apply_noop_gate_response,
    check_core_field_guard,
    check_default_adults_gate,
    check_domain_keyword_for_default_adults,
    check_noop_gate,
)
from app.planner.nodes.specialist.response_processor import (
    cache_required_fields_response,
    process_llm_response,
)

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
    Invoke the missing_fields_guard to generate a question for missing core fields.

    This is called when a domain specialist is entered but core fields are missing.
    By default uses deterministic templates (saves ~200-250 tokens per call).
    Set settings.guard_use_templates=False to use LLM for more varied phrasing.

    Args:
        state: Current graph state (will be mutated with response)
        missing_fields: List of missing core field names

    Returns:
        True if guard was successful and state was updated, False on error
    """
    # Late imports for plan_graph functions (circular dependency)
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

    # =========================================================================
    # TEMPLATE PATH (Default): Deterministic response without LLM
    # =========================================================================
    # Saves ~200-250 tokens per guard call with minimal UX impact.
    # The questions and suggestions are the same as what the LLM would generate.
    if settings.guard_use_templates:
        # Check if we're in date_clarify_mode - if so, force dates question
        in_date_clarify_mode = state.metadata.get("date_clarify_mode", False)
        has_blocking_errors = bool(state.metadata.get("date_blocking_errors"))

        # Determine question target based on priority and constraints
        if in_date_clarify_mode or has_blocking_errors:
            # Force dates when in date_clarify_mode
            question_target = "dates"
        elif "dates" in missing_fields or "start_date" in missing_fields:
            question_target = "dates"
        elif "destinations" in missing_fields:
            question_target = "destinations"
        elif "origin" in missing_fields:
            question_target = "origin"
        else:
            question_target = missing_fields[0] if missing_fields else "dates"

        # Template questions and suggestions (same as LLM would generate)
        template_responses = {
            "destinations": {
                "question": "Where are you dreaming of going?",
                "suggestions": ["Bali, Indonesia", "Paris, France", "Tokyo, Japan"],
            },
            "origin": {
                "question": "Where will you be flying from?",
                "suggestions": ["New York", "London", "Los Angeles"],
            },
            "dates": {
                "question": "When are you looking to travel?",
                "suggestions": ["Next month", "December 20-27", "First week of January"],
            },
            "adults": {
                "question": "How many travelers will be joining?",
                "suggestions": ["Just me", "2 adults", "Family of 4"],
            },
            "budget": {
                "question": "What's your approximate budget for this trip?",
                "suggestions": ["$2,000", "$5,000", "Flexible budget"],
            },
        }

        response = template_responses.get(
            question_target,
            {"question": "Could you tell me more about your trip?", "suggestions": []},
        )

        # Check for season clarification with specific month suggestions (Issue 4)
        clarify_suggestions = state.metadata.get("date_clarify_suggestions")
        pending_text = state.metadata.get("pending_date_text", "")

        # Build acknowledgment for any newly extracted fields
        ti = state.trip_inputs
        ack_parts = []
        if ti.destinations and "destinations" not in missing_fields:
            ack_parts.append(f"{', '.join(ti.destinations[:2])}")
        if ti.origin and "origin" not in missing_fields:
            ack_parts.append(f"from {ti.origin}")

        ack_prefix = f"{' '.join(ack_parts)} - got it! " if ack_parts else ""

        if in_date_clarify_mode and clarify_suggestions:
            # Use specific month suggestions for season clarification
            state.last_summary = (
                f'{ack_prefix}You mentioned "{pending_text}" - could you be more specific? '
                f"For example, {clarify_suggestions[0]} or {clarify_suggestions[-1]}?"
            )
            state.suggested_responses = clarify_suggestions[:3]
        elif in_date_clarify_mode and pending_text:
            # Generic clarification with context
            state.last_summary = (
                f'{ack_prefix}Could you be more specific about "{pending_text}"? '
                "When exactly are you thinking?"
            )
            state.suggested_responses = response["suggestions"][:3]
        else:
            # Check for extraction failure - add graceful messaging if confidence is low
            extraction_conf = state.metadata.get("extraction_confidence", {})
            confidence_level = extraction_conf.get("level", "high")
            questions_asked = state.metadata.get("questions_asked", {})

            # Graceful failure: same field asked multiple times or low confidence
            times_asked = questions_asked.get(question_target, 0)
            is_low_confidence = confidence_level in ("low", "very_low")
            is_repeated = times_asked >= 1

            if is_low_confidence and is_repeated:
                # Graceful failure message for repeated low-confidence extraction
                failure_hints = {
                    "destinations": (
                        "I'm having trouble finding that destination. "
                        "Could you try a city name or nearby region?"
                    ),
                    "origin": (
                        "I couldn't recognize that location. "
                        "Could you try a different city name or airport?"
                    ),
                    "dates": (
                        "I'm having trouble parsing those dates. "
                        "Could you try a specific format like 'March 15-22'?"
                    ),
                    "travelers": (
                        "I couldn't understand the traveler count. "
                        "Could you say something like '2 adults' or 'solo'?"
                    ),
                    "budget": (
                        "I couldn't parse that budget. "
                        "Could you provide a number like '$2,000' or '2000 dollars'?"
                    ),
                }
                graceful_msg = failure_hints.get(question_target, response["question"])
                state.last_summary = f"{ack_prefix}{graceful_msg}"
                _debug(
                    "GRACEFUL_FAILURE: extraction failed",
                    question_target=question_target,
                    times_asked=times_asked,
                    confidence_level=confidence_level,
                )
            else:
                state.last_summary = (
                    f"{ack_prefix}{response['question']}" if ack_prefix else response["question"]
                )
            state.suggested_responses = response["suggestions"][:3]
        set_question_target(state, question_target, source="missing_fields_guard:template")

        # Map question_target to last_question_field for short-circuit context
        target_to_field = {
            "destinations": "destinations",
            "origin": "origin",
            "dates": "start_date",
            "start_date": "start_date",
        }
        state.metadata["last_question_field"] = target_to_field.get(
            question_target, question_target
        )

        # Store suggestions with field for LQA matching
        store_suggestions_with_field(state, state.suggested_responses, question_target)

        # Track that response was produced this turn (no-stale-summary invariant)
        state.metadata["last_response_turn"] = state.turn_number
        state.metadata["guard_template_path"] = True

        _debug(
            "missing_fields_guard: using template path",
            question_target=question_target,
            question=response["question"],
            tokens_saved="~200-250",
        )
        return True

    # =========================================================================
    # LLM PATH: Use LLM for varied phrasing (when guard_use_templates=False)
    # =========================================================================
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
                # Build acknowledgment for any extracted fields before redirecting
                ti = state.trip_inputs
                ack_parts = []
                if ti.destinations and "destinations" not in missing_fields:
                    ack_parts.append(f"{', '.join(ti.destinations[:2])}")
                if ti.origin and "origin" not in missing_fields:
                    ack_parts.append(f"from {ti.origin}")
                if ack_parts:
                    ack_prefix = f"{' '.join(ack_parts)} - got it! "
                    # Prepend acknowledgment to the LLM response
                    state.last_summary = f"{ack_prefix}Now, when are you looking to travel?"
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
    name: str, state: "GraphState", retry_on_json_error: bool = False
) -> "GraphState":
    """
    Shared handler for specialist nodes with JSON retry logic.

    Args:
        name: Prompt name to load (also used to look up per-node LLM config).
        state: Current graph state.
        retry_on_json_error: If True, attempt repair retries on JSON parse failure.
            Default False to save tokens - relies on deterministic fallbacks instead.
    """
    # Type imports (used for local type hints only)
    from typing import Optional

    # Late imports for plan_graph functions (circular dependency)
    from app.plan_graph import (
        INVALID_JSON_HINT,
        StateViewBuilder,
        ToneAdapter,
        _compute_cache_key,
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
        _record_llm_failure,
        _record_node_tokens,
        _today_iso,
        call_llm_with_timeout,
        can_call_llm,
        get_available_options_context,
        llm_blocked_fallback,
        load_prompt,
        load_specialist_prompt,
        ti_short,
    )
    from app.planner.nodes.specialist.templates import (
        apply_confirmation_template,
        apply_pre_core_template_response,
        apply_template_response,
        check_requires_llm,
        determine_question_target,
        handle_loop_guard,
        select_confirmation_template,
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
            # P3: Extracted to templates.apply_pre_core_template_response
            _debug(
                f"PRE-CORE MODE (DETERMINISTIC): {name} bypassing LLM",
                specialist=name,
                missing=missing_core,
                tokens_saved="~1000-2000 (specialist LLM call avoided)",
            )
            apply_pre_core_template_response(state, name, missing_core)
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

        # =====================================================================
        # P4.2: CONFIRMATION TEMPLATES (before regular template path)
        # =====================================================================
        # Check if we can use deterministic confirmation templates instead of LLM.
        # This handles: multiple_destinations, typo_detected, low_confidence cases.
        if requires_llm and question_target:
            confirmation = select_confirmation_template(state, question_target)
            if confirmation:
                if apply_confirmation_template(state, confirmation):
                    _debug_node_exit(f"specialist:{name}", state, start_ns)
                    return state
                # If application failed, fall through to regular path

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
    # P3: Extracted to groundedness.check_groundedness_guardrail
    groundedness_warning = check_groundedness_guardrail(state, name, available_options)

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
        .replace(
            "{conversation_summary}",
            _generate_conversation_summary(state.chat_history, state=state),
        )
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

            # =====================================================================
            # P3: Process LLM response using extracted module
            # =====================================================================
            process_llm_response(state, j, name, llm_config)

            # Cache the response for required_fields node
            if name == "required_fields" and cache_key is not None:
                cache_required_fields_response(state, cache_key)

            _debug_node_exit(f"specialist:{name}", state, start_ns)
            return state

        except json.JSONDecodeError as e:
            last_error = e
            _debug_error(f"Specialist {name} JSON error on attempt {attempt + 1}", error=str(e))
            if attempt < attempts - 1:
                # Add repair hint to prompt for retry
                system_prompt += INVALID_JSON_HINT
                # Tier 10.12: Exponential backoff - 10ms, 20ms, 40ms
                await asyncio.sleep(0.01 * (2**attempt))
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
