"""
Specialist Base - Shared constants and utilities for specialist nodes.

Contains:
- Constants for specialist configuration
- Prompt selection helpers
- Pre-core mode handling
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Set

if TYPE_CHECKING:
    from app.plan_graph import GraphState

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

# Fields that correction should NEVER modify
CORRECTION_SKIP_FIELDS: Set[str] = {
    "strategy_settings",
    "booking_types",
}

# Specialist types that use domain-specific prompts
SPECIALIST_TYPES: Set[str] = {"flights", "hotels", "transport", "activities"}

# Valid question target values
QUESTION_TARGET_FIELD_MAP = {
    "dates": lambda t: bool(t.start_date),
    "start_date": lambda t: bool(t.start_date),
    "end_date": lambda t: bool(t.end_date),
    "destinations": lambda t: bool(t.destinations),
    "origin": lambda t: bool(t.origin),
    "travelers": lambda t: t.adults is not None,
    "adults": lambda t: t.adults is not None,
    "budget": lambda t: t.budget is not None,
    "currency": lambda t: bool(t.currency),
}


def select_required_fields_prompt(state: "GraphState") -> str:
    """
    Select the appropriate prompt for required_fields based on state.

    Returns either:
    - required_fields_confirm: when typos/ambiguities need user confirmation
    - required_fields: for all other cases
    """
    from app.plan_graph import load_prompt

    extraction_conf = state.metadata.get("extraction_confidence", {})
    typo_suggestions = extraction_conf.get("typo_suggestions", [])

    if typo_suggestions:
        return load_prompt("required_fields_confirm")

    prompt = load_prompt("required_fields")
    if state.metadata.get("budget_needs_clarification"):
        state.metadata["budget_needs_clarification"] = False
        state.question_target = "budget"
        prompt += (
            "\n\nIMPORTANT: The user provided a qualitative budget description."
            " Ask them for an approximate budget in dollars/their currency."
        )

    return prompt


def get_skip_fields_for_specialist(name: str) -> Set[str]:
    """
    Get the set of fields to skip when applying LLM delta for a specialist.

    required_fields: can modify all fields
    correction: has restricted scope
    domain specialists: block core fields
    """
    if name == "required_fields":
        return set()  # Allow all field modifications
    elif name == "correction":
        return CORRECTION_SKIP_FIELDS
    else:
        return CORE_FIELDS


def handle_pre_core_mode(
    state: "GraphState",
    name: str,
    missing_core: list,
) -> "GraphState":
    """
    Handle pre-core mode for specialists with missing core fields.

    In pre-core mode, generate a deterministic template response that:
    1. Acknowledges the user's intent/topic
    2. Asks for the next missing core field
    3. Provides template suggestions
    """
    from app.debug_utils import _debug
    from app.plan_graph import (
        FALLBACK_SUGGESTIONS,
        _get_template_response,
        set_question_target,
        track_question_asked,
    )
    from app.planner.gates.constants import CORE_FIELD_PRIORITY

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
        check_field = field
        if field == "start_date":
            check_field = "start_date"
        if check_field in missing_core or field in missing_core:
            question_target = "dates" if field == "start_date" else field
            break

    if not question_target and missing_core:
        question_target = "destinations" if "destinations" in missing_core else missing_core[0]

    # Build acknowledgment based on specialist type
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

    # Set provenance
    state.metadata["response_writer_node"] = f"specialist:{name}:pre_core"
    state.metadata["response_generation_provenance"] = "template"

    _debug(
        f"PRE-CORE DETERMINISTIC: {name} -> {question_target}",
        question=state.last_summary[:80],
        suggestions=suggestions,
    )

    return state
