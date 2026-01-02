"""
Specialist Templates - Template-first approach for field collection.

Contains:
- Template path logic for required_fields
- LLM requirement checks (typos, ambiguity, multi-city)
- Loop guard integration
- Pre-core mode template response

Extracted from specialist_main.py as part of P3 module extraction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from app.plan_graph import GraphState

# Topic acknowledgments for pre-core mode (used for generic fallback)
TOPIC_ACKNOWLEDGMENTS: Dict[str, str] = {
    "hotels": "hotels and accommodation",
    "flights": "flights",
    "activities": "activities and things to do",
    "transport": "transportation",
}


# Strategy topic emoji mapping for context-aware acknowledgments (Tier 6)
STRATEGY_TOPIC_EMOJIS = {
    "hiking": "🥾",
    "skiing": "⛷️",
    "diving": "🤿",
    "cycling": "🚴",
    "boating": "⛵",
}


def _build_context_acknowledgment(
    state: "GraphState",
    specialist_name: str,
) -> str:
    """
    Build a context-aware acknowledgment based on fields already extracted.

    E.g., if user said "I want flights to Paris", returns "Paris for flights - got it!"
    If user said "Hotels in Tokyo from New York", returns "Tokyo from New York - got it!"
    If user said "I want to go hiking", returns "🥾 Hiking sounds amazing! "

    Returns empty string if no context to acknowledge.
    """
    ti = state.trip_inputs
    parts = []

    # Check for pending strategy topic (Tier 6: strategy preconditions UX)
    pending_topic = state.metadata.get("pending_strategy_topic")
    if pending_topic and not ti.destinations and not ti.start_date:
        # User mentioned a strategy topic but we need destinations/dates
        emoji = STRATEGY_TOPIC_EMOJIS.get(pending_topic, "✨")
        return f"{emoji} {pending_topic.capitalize()} sounds amazing! "

    # Collect known context
    if ti.destinations:
        dest_str = ", ".join(ti.destinations[:2])  # Limit to first 2
        parts.append(dest_str)

    if ti.origin:
        parts.append(f"from {ti.origin}")

    if ti.start_date:
        # Format date nicely
        try:
            from datetime import datetime

            dt = datetime.strptime(ti.start_date, "%Y-%m-%d")
            parts.append(f"on {dt.strftime('%B %d')}")
        except ValueError:
            pass

    if ti.adults:
        traveler_word = "traveler" if ti.adults == 1 else "travelers"
        parts.append(f"for {ti.adults} {traveler_word}")

    if not parts:
        return ""

    context = " ".join(parts)
    return f"{context} - got it! "


# Domain-specific warm acknowledgments for pre-core mode (saves ~200-400 tokens)
# Maps (specialist_name, question_target) -> personalized intro
DOMAIN_PRE_CORE_TEMPLATES: Dict[str, Dict[str, str]] = {
    "hotels": {
        "destinations": "I'd love to help find the perfect stay! Where are you dreaming of?",
        "dates": "I'd love to help find the perfect stay! When are you planning your trip?",
        "origin": "I'd love to help find the perfect stay! Where will you be traveling from?",
        "travelers": "I'd love to help find the perfect stay! How many guests will be staying?",
        "budget": "I'd love to help find the perfect stay! What's your budget for lodging?",
    },
    "flights": {
        "destinations": "I can help with your flight search! Where would you like to fly to?",
        "dates": "I can help with your flight search! When are you looking to fly?",
        "origin": "I can help with your flight search! Where will you be flying from?",
        "travelers": "I can help with your flight search! How many passengers?",
        "budget": "I can help with your flight search! What's your flight budget?",
    },
    "activities": {
        "destinations": "Great - I'd love to help plan amazing experiences! Where are you headed?",
        "dates": "Great - I'd love to help plan amazing experiences! When will you be there?",
        "origin": "Great - I'd love to plan amazing experiences! Where are you traveling from?",
        "travelers": "Great - I'd love to plan amazing experiences! How many in your group?",
        "budget": "Great - I'd love to plan amazing experiences! What's your activity budget?",
    },
    "transport": {
        "destinations": "I can help with your ground transportation! Where are you going?",
        "dates": "I can help with your ground transportation! When are you traveling?",
        "origin": "I can help with your ground transportation! Where will you be starting from?",
        "travelers": "I can help with your ground transportation! How many travelers?",
        "budget": "I can help with your ground transportation! What's your transport budget?",
    },
}


def apply_pre_core_template_response(
    state: "GraphState",
    specialist_name: str,
    missing_core: List[str],
) -> "GraphState":
    """
    Apply deterministic template response for pre-core mode.

    When a domain specialist is entered but core fields are missing,
    this generates a warm acknowledgment + question without LLM.

    Args:
        state: Current graph state (will be mutated)
        specialist_name: Name of the specialist (e.g., "hotels", "flights")
        missing_core: List of missing core field names

    Returns:
        Updated state with template response applied
    """
    from app.debug_utils import _debug
    from app.plan_graph import (
        FALLBACK_SUGGESTIONS,
        _get_template_response,
        set_question_target,
        track_question_asked,
    )
    from app.planner.gates.constants import CORE_FIELD_PRIORITY

    state.metadata["specialist_pre_core_active"] = True
    state.metadata["specialist_pre_core_deterministic"] = True

    # Determine next missing field using priority order
    question_target = None
    for field in CORE_FIELD_PRIORITY:
        check_field = field
        if check_field in missing_core or field in missing_core:
            question_target = "dates" if field == "start_date" else field
            break

    if not question_target and missing_core:
        question_target = "destinations" if "destinations" in missing_core else missing_core[0]

    # Get template question and suggestions for the question_target
    template_response = _get_template_response(question_target, state.strategy_topic)
    suggestions = (
        template_response["suggestions"][:3] if template_response else FALLBACK_SUGGESTIONS.copy()
    )

    # Build context-aware acknowledgment based on already-extracted fields
    context_ack = _build_context_acknowledgment(state, specialist_name)

    # Get the question for the missing field
    if template_response:
        question = template_response["question"]
    else:
        question = (
            "Where would you like to go?"
            if question_target == "destinations"
            else f"Could you tell me your {question_target}?"
        )

    # Compose final response
    if context_ack:
        # We have context to acknowledge - use context-aware pattern
        # E.g., "Paris - got it! When are you looking to travel?"
        state.last_summary = f"{context_ack}{question}"
    else:
        # No context yet - use domain-specific warm intro or fallback
        domain_templates = DOMAIN_PRE_CORE_TEMPLATES.get(specialist_name, {})
        domain_question = domain_templates.get(question_target)

        if domain_question:
            state.last_summary = domain_question
        else:
            topic_name = TOPIC_ACKNOWLEDGMENTS.get(
                specialist_name, state.strategy_topic or "trip planning"
            )
            state.last_summary = f"I'd love to help you find great {topic_name}! {question}"
    state.suggested_responses = suggestions
    set_question_target(state, question_target, source=f"specialist:{specialist_name}:pre_core")
    state.metadata["last_question_field"] = question_target
    state.metadata["from_template"] = True
    state.metadata["pre_core_deterministic_path"] = f"{specialist_name}:{question_target}"

    # Track question for loop guard
    track_question_asked(state, question_target, state.last_summary)

    # Set provenance for final response tracking
    state.metadata["response_writer_node"] = f"specialist:{specialist_name}:pre_core"
    state.metadata["response_generation_provenance"] = "template"

    _debug(
        f"PRE-CORE DETERMINISTIC: {specialist_name} -> {question_target}",
        question=state.last_summary[:80],
        suggestions=suggestions,
    )

    return state


def determine_question_target(state: "GraphState") -> Optional[str]:
    """
    Determine the next question target based on missing fields.

    Returns canonical question target or None if all fields set.
    """
    ti = state.trip_inputs

    # First check state for candidate (may be stale)
    question_target_candidate = state.question_target or state.metadata.get("last_question_field")

    # Validate that candidate field is actually still missing
    if question_target_candidate:
        field_values = {
            "destinations": ti.destinations,
            "origin": ti.origin,
            "dates": ti.start_date,
            "travelers": ti.adults,
        }
        if field_values.get(question_target_candidate):
            from app.debug_utils import _debug

            _debug(
                "STALE_TARGET: question_target was set but field is populated, clearing",
                stale_target=question_target_candidate,
                field_value=field_values.get(question_target_candidate),
            )
            state.question_target = None
            state.metadata.pop("last_question_field", None)
            question_target_candidate = None

    # If no valid candidate, compute from actual missing fields
    if question_target_candidate:
        return question_target_candidate

    if not ti.destinations:
        return "destinations"
    elif not ti.origin:
        return "origin"
    elif not ti.start_date:
        return "dates"
    elif not ti.adults:
        return "travelers"

    return None


def check_requires_llm(
    state: "GraphState",
    question_target: Optional[str],
) -> Tuple[bool, Optional[str]]:
    """
    Check if required_fields node requires LLM instead of templates.

    Returns (requires_llm: bool, reason: Optional[str])
    """
    from app.debug_utils import _debug
    from app.plan_graph import _template_stats

    extraction_conf = state.metadata.get("extraction_confidence", {})
    conf_overall = extraction_conf.get("overall", 0.5)

    # 1. Typo suggestions need LLM - but only if low confidence
    if extraction_conf.get("typo_suggestions"):
        if conf_overall < 0.5:
            return True, "typo_suggestions_low_conf"
        _debug(
            "TEMPLATE_SAFE: typo suggestions but high confidence",
            confidence=f"{conf_overall:.2f}",
        )

    # 2. Low confidence needs LLM - but only for complex cases
    elif extraction_conf.get("level") == "low":
        harmless_fields = {"destinations", "origin", "dates", "travelers"}
        if question_target not in harmless_fields:
            return True, "low_confidence_complex_field"
        _template_stats["low_conf_accepted"] += 1
        _debug(
            "HARMLESS_LOW_CONF: accepted without LLM",
            field=question_target,
            confidence_level="low",
            tokens_saved="~900-1500 (required_fields LLM avoided)",
        )

    # 3. Multi-city ambiguity needs LLM
    elif state.trip_inputs.destinations and len(state.trip_inputs.destinations) > 1:
        if not state.trip_inputs.multi_city_intent:
            return True, "multi_city_ambiguity"

    # 4. Ambiguity keywords in confidence reasons
    low_confidence_reasons = extraction_conf.get("low_confidence_reasons") or []
    ambiguity_keywords = ["ambiguous", "unclear", "multiple", "conflict"]
    if any(
        any(kw in reason.lower() for kw in ambiguity_keywords) for reason in low_confidence_reasons
    ):
        return True, f"ambiguity_detected:{low_confidence_reasons[0][:30]}"

    return False, None


# =============================================================================
# P4.2: CONFIRMATION TEMPLATES FOR AMBIGUITY
# =============================================================================


def select_confirmation_template(
    state: "GraphState",
    question_target: Optional[str],
) -> Optional[Dict[str, Any]]:
    """
    Select appropriate confirmation template based on extraction state.

    P4.2 Optimization: Use deterministic templates for common ambiguities
    instead of LLM calls.

    Returns dict with:
    - template_type: str (e.g., "ambiguous_place", "low_confidence", "multiple_destinations")
    - field: str (the field being confirmed)
    - Plus interpolation context (extracted_value, user_input, etc.)

    Returns None if no confirmation needed.
    """
    if not question_target:
        return None

    extraction_conf = state.metadata.get("extraction_confidence", {})
    ti = state.trip_inputs

    # Check for multiple destinations without multi-city intent
    if question_target == "destinations":
        if ti.destinations and len(ti.destinations) > 1:
            if not ti.multi_city_intent:
                return {
                    "template_type": "multiple_destinations",
                    "field": "destinations",
                    "destinations_list": ", ".join(ti.destinations),
                    "first_dest": ti.destinations[0],
                }

    # Check for typo suggestions (use typo_detected template)
    typo_suggestions = extraction_conf.get("typo_suggestions")
    if typo_suggestions and question_target in ("destinations", "origin"):
        # typo_suggestions format: {"original": "suggestion"} or list
        if isinstance(typo_suggestions, dict):
            for user_input, suggestion in typo_suggestions.items():
                return {
                    "template_type": "typo_detected",
                    "field": question_target,
                    "user_input": user_input,
                    "suggestion": suggestion,
                }
        elif isinstance(typo_suggestions, list) and typo_suggestions:
            return {
                "template_type": "typo_detected",
                "field": question_target,
                "user_input": state.user_text[:50] if state.user_text else "",
                "suggestion": typo_suggestions[0],
            }

    # Check for low confidence with extractable value (confirm vs reject)
    conf_overall = extraction_conf.get("overall", 0.5)
    conf_level = extraction_conf.get("level")

    if conf_level == "low" and 0.3 <= conf_overall < 0.7:
        # Get the extracted value for this field
        extracted_value = _get_extracted_value_for_field(state, question_target)
        if extracted_value:
            return {
                "template_type": "low_confidence",
                "field": question_target,
                "extracted_value": extracted_value,
                "confidence": conf_overall,
            }

    return None


def _get_extracted_value_for_field(state: "GraphState", field: str) -> Optional[str]:
    """Get the extracted value for a field from trip_inputs."""
    ti = state.trip_inputs

    if field == "destinations":
        if ti.destinations:
            return ti.destinations[0] if len(ti.destinations) == 1 else ", ".join(ti.destinations)
        return None
    elif field == "origin":
        return ti.origin
    elif field == "dates":
        if ti.start_date:
            if ti.end_date:
                return f"{ti.start_date} to {ti.end_date}"
            return ti.start_date
        return None
    elif field == "travelers":
        if ti.adults:
            if ti.children:
                return f"{ti.adults} adults and {ti.children} children"
            return f"{ti.adults} adults" if ti.adults > 1 else "1 adult"
        return None
    elif field == "budget":
        return ti.budget

    return None


def apply_confirmation_template(
    state: "GraphState",
    confirmation: Dict[str, Any],
) -> bool:
    """
    Apply confirmation template to state (deterministic response).

    P4.2 Optimization: Saves ~900-1500 tokens per confirmation by avoiding LLM.

    Returns True if template was applied, False otherwise.
    """
    import json
    import random
    from pathlib import Path

    from app.debug_utils import _debug
    from app.plan_graph import (
        set_question_target,
        store_suggestions_with_field,
        track_question_asked,
    )

    template_type = confirmation["template_type"]
    field = confirmation["field"]

    # Load templates from JSON
    # Path: app/prompts/required_fields_templates.json (4 levels up from templates.py)
    templates_path = (
        Path(__file__).parent.parent.parent.parent / "prompts" / "required_fields_templates.json"
    )
    try:
        with open(templates_path) as f:
            templates = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        _debug(f"CONFIRMATION_TEMPLATE: Failed to load templates: {e}")
        return False

    # Get clarify templates for the field
    clarify_key = f"{field}_clarify"
    if clarify_key not in templates:
        _debug(f"CONFIRMATION_TEMPLATE: No clarify template for {field}")
        return False

    clarify_templates = templates[clarify_key]
    questions = clarify_templates.get("questions", {}).get(template_type, [])
    suggestions = clarify_templates.get("suggestions", {}).get(template_type, [])

    if not questions:
        _debug(f"CONFIRMATION_TEMPLATE: No questions for {template_type}")
        return False

    # Select a random question template
    question_template = random.choice(questions)

    # Build interpolation context from confirmation dict
    interp = {k: str(v) for k, v in confirmation.items() if k not in ("template_type", "field")}

    # Interpolate question
    try:
        question = question_template.format(**interp)
    except KeyError as e:
        _debug(f"CONFIRMATION_TEMPLATE: Missing interpolation key {e}")
        question = question_template  # Use raw template

    # Interpolate suggestions
    final_suggestions = []
    for sugg in suggestions[:3]:
        try:
            final_suggestions.append(sugg.format(**interp))
        except KeyError:
            final_suggestions.append(sugg)

    # Apply to state
    state.last_summary = question
    state.suggested_responses = final_suggestions if final_suggestions else ["Yes", "No"]
    set_question_target(state, field, source=f"confirmation_template:{template_type}")
    store_suggestions_with_field(state, final_suggestions, field)
    track_question_asked(state, field, question)

    # Set metadata
    state.metadata["last_question_field"] = field
    state.metadata["from_template"] = True
    state.metadata["confirmation_template_applied"] = template_type
    state.metadata["response_writer_node"] = (
        f"specialist:required_fields:confirm_template:{template_type}"
    )
    state.metadata["response_generation_provenance"] = "template"
    state.metadata["required_fields_path"] = f"confirm_template:{template_type}"

    _debug(
        f"CONFIRMATION_TEMPLATE: {template_type} for {field}",
        question=question[:80],
        suggestions=final_suggestions,
        tokens_saved="~900-1500 (LLM confirmation avoided)",
    )

    return True


def apply_template_response(
    state: "GraphState",
    question_target: str,
    name: str = "required_fields",
) -> bool:
    """
    Apply template response for a question target.

    Returns True if template was applied, False if no template found.
    """
    from app.debug_utils import _debug
    from app.plan_graph import (
        _get_template_response,
        _template_stats,
        set_question_target,
        store_suggestions_with_field,
        track_question_asked,
    )

    template_response = _get_template_response(question_target, state.strategy_topic)
    if not template_response:
        _template_stats["template_misses"] += 1
        _debug(
            "Template not found for target, falling through to LLM",
            question_target=question_target,
        )
        return False

    _template_stats["template_hits"] += 1

    # Check if there's a failed input message to prepend
    failed_msg = state.metadata.get("failed_input_message")
    if failed_msg:
        state.last_summary = f"{failed_msg}\n\n{template_response['question']}"
        state.metadata.pop("failed_input_message", None)
        _debug("Prepended failed_input_message to template response")
    else:
        state.last_summary = template_response["question"]

    state.suggested_responses = template_response["suggestions"]
    set_question_target(state, question_target, source=f"specialist:{name}:template")

    # Store suggestions with field info for deterministic echo
    store_suggestions_with_field(state, template_response["suggestions"], question_target)

    # Track this question for loop guard
    track_question_asked(state, question_target, template_response["question"])

    # Map question_target to last_question_field for fast-path context
    target_to_field = {
        "destinations": "destinations",
        "origin": "origin",
        "dates": "dates",
        "travelers": "travelers",
        "budget": "budget",
    }
    state.metadata["last_question_field"] = target_to_field.get(question_target, question_target)
    state.metadata["from_template"] = True
    state.metadata["response_writer_node"] = f"specialist:{name}:template"
    state.metadata["response_generation_provenance"] = "template"
    state.metadata["required_fields_path"] = f"template:{question_target}"

    _debug(
        "TEMPLATE PATH: Required fields using template (LLM BYPASSED)",
        question_target=question_target,
        question=state.last_summary,
        suggestions=state.suggested_responses,
        tokens_saved="~900-1500 (required_fields LLM call avoided)",
    )

    return True


def handle_loop_guard(
    state: "GraphState",
    question_target: str,
) -> Tuple[bool, Optional[str]]:
    """
    Handle loop guard for repeated questions.

    Returns (should_skip: bool, alternative_target: Optional[str])
    """
    from app.debug_utils import _debug
    from app.plan_graph import (
        _summarize_trip_inputs_for_recovery,
        check_and_apply_loop_guard,
    )
    from app.planner.gates.readiness import compute_trip_readiness

    state, should_skip_question = check_and_apply_loop_guard(state, question_target)
    if should_skip_question:
        _debug(
            "LOOP GUARD: Skipping question due to repeated asks",
            question_target=question_target,
            questions_asked=state.questions_asked,
        )
        return True, None

    # Check if "different_field" mitigation was applied
    skip_field = state.metadata.get("loop_guard_skip_field")
    if skip_field and skip_field == question_target:
        readiness = compute_trip_readiness(state.trip_inputs, metadata=state.metadata)

        def _normalize_field_name(f: str) -> str:
            if f == "start_date":
                return "dates"
            elif f == "travelers (adults)":
                return "travelers"
            elif f == "end_date":
                return "dates"
            return f

        alternative_fields = [
            f for f in readiness.missing_all if _normalize_field_name(f) != skip_field
        ]
        if alternative_fields:
            alt_field = _normalize_field_name(alternative_fields[0])
            _debug(
                "LOOP GUARD: Switched to different field",
                skipped=skip_field,
                new_target=alt_field,
            )
            return False, alt_field
        else:
            # No alternative fields - emit recovery summary
            trip_inputs_dict = (
                state.trip_inputs.model_dump()
                if hasattr(state.trip_inputs, "model_dump")
                else dict(state.trip_inputs)
            )
            known_info = _summarize_trip_inputs_for_recovery(trip_inputs_dict)
            state.last_summary = (
                f"I have most of your trip details. Here's what I know:\n\n"
                f"{known_info}\n\n"
                f"Is there anything you'd like to add or change?"
            )
            state.suggested_responses = [
                "Looks good!",
                "Hold on, I want to add more",
                "I'd like to change something",
            ]
            _debug(
                "LOOP GUARD: No alternative fields, emitting recovery summary",
            )
            return True, None

    return False, None
