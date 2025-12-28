"""
Specialist Response Processor - LLM response parsing and validation.

Contains:
- LLM response parsing and delta application
- Question target validation (prevents asking about set fields)
- Suggestion processing
- Branch normalization

Extracted from specialist_main.py as part of P3 module extraction.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set

if TYPE_CHECKING:
    from app.plan_graph import GraphState, TripInputs

# Question target to field check mapping
# Covers ALL core field targets; domain targets like "activities" don't need this check
QUESTION_TARGET_FIELD_CHECK: Dict[str, Callable[["TripInputs"], bool]] = {
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

# Core fields that domain specialists should not modify
CORE_FIELDS: Set[str] = {
    "destinations",
    "origin",
    "start_date",
    "end_date",
    "adults",
    "children",
    "budget",
    "currency",
}

# Fields that correction node is allowed to modify
CORRECTION_ALLOWED_FIELDS: Set[str] = {
    "destinations",
    "origin",
    "start_date",
    "end_date",
    "adults",
    "children",
    "budget",
    "currency",
    "flight_settings",
    "hotel_settings",
    "transport_settings",
    "activity_settings",
}

# Fields that correction should NEVER modify (to prevent scope creep)
CORRECTION_SKIP_FIELDS: Set[str] = {
    "strategy_settings",
    "booking_types",
}


def get_skip_fields(name: str) -> Optional[Set[str]]:
    """
    Get the set of fields to skip when applying LLM delta for a specialist.

    required_fields: can modify all fields (returns None)
    correction: has restricted scope (returns CORRECTION_SKIP_FIELDS)
    domain specialists: block core fields (returns CORE_FIELDS)
    """
    if name == "required_fields":
        return None  # Allow all field modifications
    elif name == "correction":
        return CORRECTION_SKIP_FIELDS
    else:
        return CORE_FIELDS


def validate_question_target(
    state: "GraphState",
    raw_target: str,
    specialist_name: str,
) -> Optional[str]:
    """
    Validate and potentially correct a question target from LLM response.

    Prevents LLM from asking about fields that are already set.
    Returns the validated/corrected target or None if all fields set.
    """
    from app.debug_utils import _debug
    from app.plan_graph import (
        QUESTION_TARGET_VALUES,
        _get_template_response,
        set_question_target,
        store_suggestions_with_field,
    )
    from app.planner.gates.readiness import compute_trip_readiness

    normalized_target = raw_target.lower().strip()

    if normalized_target not in QUESTION_TARGET_VALUES:
        if normalized_target in ("null", "none"):
            set_question_target(state, None, source=f"specialist:{specialist_name}:llm_null")
            return None
        else:
            _debug(f"Unknown question_target from LLM: {raw_target}")
            set_question_target(state, None, source=f"specialist:{specialist_name}:llm_unknown")
            return None

    # Validate that the field is actually still missing
    ti = state.trip_inputs
    field_check = QUESTION_TARGET_FIELD_CHECK.get(normalized_target)
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
        if corrected_target:
            template_response = _get_template_response(corrected_target, state.strategy_topic)
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

    return normalized_target


def process_llm_response(
    state: "GraphState",
    response_json: Dict[str, Any],
    specialist_name: str,
    llm_config: Dict[str, Any],
) -> "GraphState":
    """
    Process a successful LLM response and apply it to state.

    This function:
    1. Extracts assistant_message
    2. Handles strategy_hint extraction
    3. Applies trip_inputs delta with proper field filtering
    4. Validates trip_inputs
    5. Processes question_target
    6. Handles suggestions
    7. Sets ready_to_generate and branches if applicable
    8. Records metadata

    Args:
        state: Current graph state (will be mutated)
        response_json: Parsed JSON from LLM response
        specialist_name: Name of the specialist (e.g., "hotels", "required_fields")
        llm_config: LLM configuration dict with model_hint

    Returns:
        Updated state
    """
    from app.debug_utils import _debug, _debug_suggestions
    from app.plan_graph import (
        TRIP_VALIDATOR,
        _apply_llm_delta,
        _count_tokens,
        _get_suggestions_with_fallback,
        _maybe_append_safety_snippet,
        _normalize_branch_spec,
        set_question_target,
        track_question_asked,
    )

    j = response_json

    # Capture assistant_message early - even if field processing fails, we want this
    assistant_msg = j.get("assistant_message", "")
    if assistant_msg:
        state.last_summary = assistant_msg

    # Apply trip_inputs delta using centralized helper
    delta = j.get("trip_inputs", {}) or {}

    # Handle strategy_hint separately - it belongs in parsed_inputs, not trip_inputs
    if "strategy_hint" in delta:
        strategy_hint = delta.pop("strategy_hint")
        if strategy_hint and isinstance(strategy_hint, str):
            state.parsed_inputs["strategy_hint"] = strategy_hint
            _debug(f"Captured strategy_hint from LLM: {strategy_hint}")

    # Get skip fields based on specialist type
    skip_fields = get_skip_fields(specialist_name)

    if specialist_name == "correction" and skip_fields:
        _debug(
            "Correction node field permissions",
            allowed="core + settings",
            blocked=list(skip_fields),
        )

    _apply_llm_delta(state, f"specialist:{specialist_name}", delta, skip_fields=skip_fields)

    # Validate the updated trip_inputs
    TRIP_VALIDATOR.validate(state.trip_inputs.model_dump())
    llm_message = j.get("assistant_message", "")

    # Check if there's a failed input message to prepend
    failed_msg = state.metadata.get("failed_input_message")
    if failed_msg:
        state.last_summary = f"{failed_msg}\n\n{llm_message}"
        state.metadata.pop("failed_input_message", None)
        _debug("Prepended failed_input_message to LLM response")
    else:
        state.last_summary = llm_message

    # Early safety snippet injection for international travel
    if state.last_summary and state.trip_inputs.destinations:
        state.last_summary = _maybe_append_safety_snippet(state)

    # Parse question_target from LLM response
    raw_question_target = j.get("question_target")
    if raw_question_target and isinstance(raw_question_target, str):
        normalized_target = validate_question_target(state, raw_question_target, specialist_name)
        if normalized_target:
            set_question_target(
                state, normalized_target, source=f"specialist:{specialist_name}:llm_response"
            )
            track_question_asked(state, normalized_target, state.last_summary)
        else:
            set_question_target(state, None, source=f"specialist:{specialist_name}:llm_all_set")
    else:
        set_question_target(state, None, source=f"specialist:{specialist_name}:no_target")

    # Filter suggested responses with contextual fallback
    raw_suggestions = j.get("suggested_responses", []) or []
    _debug(f"Raw LLM suggested_responses: {raw_suggestions}")
    state.suggested_responses = _get_suggestions_with_fallback(
        raw_suggestions, state, state.question_target
    )
    _debug_suggestions(state.suggested_responses, source=f"specialist:{specialist_name}")

    # Only set ready_to_generate if explicitly triggered
    state.ready_to_generate = bool(j.get("ready_to_generate", False)) and state.flags.get(
        "generate_requested", False
    )

    # Only emit branches if generate was explicitly requested
    if state.flags.get("generate_requested", False):
        ti = state.trip_inputs
        raw_branches = j.get("branches", []) or []
        fallback = ti.model_dump(exclude_none=True)
        normalized_branches: List[Dict[str, Any]] = []
        for b in raw_branches:
            normalized = _normalize_branch_spec(b, fallback)
            if normalized:
                normalized_branches.append(normalized)
        state.branches = normalized_branches

    # Record metadata
    state.metadata["model_used"] = llm_config["model_hint"]
    state.metadata["token_estimate"] = _count_tokens(json.dumps(j))
    state.metadata["response_writer_node"] = f"specialist:{specialist_name}"
    state.metadata["response_generation_provenance"] = "llm"

    _debug(
        f"Specialist {specialist_name} completed",
        ready=state.ready_to_generate,
        branches=len(state.branches),
    )

    return state


def cache_required_fields_response(
    state: "GraphState",
    cache_key: str,
) -> None:
    """
    Cache the response for required_fields node.

    Args:
        state: Current graph state with response data
        cache_key: Pre-computed cache key
    """
    from app.plan_graph import _follow_up_cache, _set_cached_response

    _set_cached_response(
        _follow_up_cache,
        cache_key,
        {
            "assistant_message": state.last_summary,
            "question_target": state.question_target,
            "suggested_responses": state.suggested_responses,
        },
    )
    state.metadata["required_fields_path"] = "llm"
