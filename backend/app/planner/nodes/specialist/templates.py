"""
Specialist Templates - Template-first approach for field collection.

Contains:
- Template path logic for required_fields
- LLM requirement checks (typos, ambiguity, multi-city)
- Loop guard integration
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    from app.plan_graph import GraphState


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
                "Add more details",
                "Change something",
            ]
            _debug(
                "LOOP GUARD: No alternative fields, emitting recovery summary",
            )
            return True, None

    return False, None
