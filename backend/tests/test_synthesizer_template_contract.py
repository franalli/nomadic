from __future__ import annotations

from dataclasses import dataclass

import pytest
from langchain_core.messages import HumanMessage

from app.planner.nodes.synthesizer import (
    PILL_ACTION_MAP,
    _build_synthesis_context,
    _get_model_id,
    _render_prompt_for_response_type,
)
from app.planner.state import GraphState, TripPlan


def _new_state(*, metadata: dict | None = None, last_human: str = "hello") -> GraphState:
    state = GraphState(
        trip_plan=TripPlan(destination="Bali", start_date="2025-03-01", end_date="2025-03-08")
    )
    state.messages = [HumanMessage(content=last_human)]
    if metadata:
        state.metadata.update(metadata)
    return state


def test_prompt_specialist_update_isolation() -> None:
    prompt = _render_prompt_for_response_type("specialist_update")

    assert "POST-PLAN UPDATE (YOUR ONLY INSTRUCTION)" in prompt
    assert "FIRST PLAN RESPONSE" not in prompt


def test_prompt_planning_isolation() -> None:
    prompt = _render_prompt_for_response_type("planning")

    assert "FIRST PLAN RESPONSE" in prompt
    assert "POST-PLAN UPDATE (YOUR ONLY INSTRUCTION)" not in prompt


def test_shared_rules_present_only_for_planning_and_specialist_update() -> None:
    planning_prompt = _render_prompt_for_response_type("planning")
    specialist_prompt = _render_prompt_for_response_type("specialist_update")
    greeting_prompt = _render_prompt_for_response_type("greeting")
    exploration_prompt = _render_prompt_for_response_type("exploration")

    assert "SHARED RULES" in planning_prompt
    assert "SHARED RULES" in specialist_prompt
    assert "SHARED RULES" not in greeting_prompt
    assert "SHARED RULES" not in exploration_prompt


class _ModelNameStub:
    model_name = "gpt-4o-mini"


class _ModelStub:
    model = "gemini-1.5-pro"


class _UnknownModelStub:
    pass


@pytest.mark.parametrize(
    ("llm", "expected"),
    [
        (_ModelNameStub(), "gpt-4o-mini"),
        (_ModelStub(), "gemini-1.5-pro"),
        (_UnknownModelStub(), "unknown"),
    ],
)
def test_get_model_id_fallback_matrix(llm: object, expected: str) -> None:
    assert _get_model_id(llm) == expected


@pytest.mark.parametrize(
    ("metadata", "last_human", "expected_change_type"),
    [
        ({"settings_just_updated": True}, "GENERATE_PLAN_NOW", "STEPPER_RERUN"),
        ({"settings_just_updated": True}, "set hotels to 5 star", "SETTINGS_CHANGE"),
        ({"added_categories": ["hiking"]}, "add hiking", "NEW_CATEGORY"),
        ({"turn_applied_fields": ["end_date"]}, "extend trip", "DATE_CHANGE"),
        ({}, "just update", "PLAN_UPDATE"),
    ],
)
def test_change_type_mapping_in_synthesis_context(
    metadata: dict,
    last_human: str,
    expected_change_type: str,
) -> None:
    state = _new_state(metadata=metadata, last_human=last_human)
    context = _build_synthesis_context(state, response_type="specialist_update")

    assert f"- change_type: {expected_change_type}" in context


def test_specialist_breakdown_from_metadata_dict_sections() -> None:
    state = _new_state(
        metadata={
            "strategy_sections": [
                {"specialist_type": "diving", "content_added": [{"id": 1}, {"id": 2}, {"id": 3}]},
                {"specialist_type": "local_expert", "content_added": [{"id": 9}]},
            ]
        }
    )

    context = _build_synthesis_context(state, response_type="specialist_update")

    assert "## Specialist Activities Generated" in context
    assert "- diving: 3 activities" in context
    assert "local_expert" not in context
    assert "Use THESE counts (not day_preferences)" in context


@dataclass
class _SectionObj:
    specialist_type: str
    content_added: list[dict]


def test_specialist_breakdown_from_metadata_object_sections() -> None:
    state = _new_state(
        metadata={
            "strategy_sections": [
                _SectionObj(specialist_type="hiking", content_added=[{"id": 1}, {"id": 2}]),
            ]
        }
    )

    context = _build_synthesis_context(state, response_type="specialist_update")

    assert "## Specialist Activities Generated" in context
    assert "- hiking: 2 activities" in context
    assert "Use THESE counts (not day_preferences)" in context


def test_plan_flight_pref_maps_to_direct_flights_trigger_action() -> None:
    action_type, action_target = PILL_ACTION_MAP["plan_flight_pref"]
    assert action_type == "trigger_action"
    assert action_target == "set_direct_flights_only"


def test_plan_flight_direct_legacy_alias_maps_to_direct_flights_trigger_action() -> None:
    action_type, action_target = PILL_ACTION_MAP["plan_flight_direct"]
    assert action_type == "trigger_action"
    assert action_target == "set_direct_flights_only"
