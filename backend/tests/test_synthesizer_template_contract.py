from __future__ import annotations

import importlib
import time
from dataclasses import dataclass

import pytest
from langchain_core.messages import HumanMessage

from app.debug_utils import RequestMetrics
from app.planner.nodes.synthesizer import (
    PILL_ACTION_MAP,
    _build_synthesis_context,
    _get_model_id,
    _ground_flight_response,
    _render_prompt_for_response_type,
)
from app.planner.state import GraphState, TripPlan

synthesizer_module = importlib.import_module("app.planner.nodes.synthesizer")


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


def test_synthesis_context_includes_no_origin_flight_guardrail() -> None:
    state = _new_state(
        metadata={
            "trip_inputs": {"booking_types": {"flights": "on"}},
            "flight_search_status": "skipped_no_origin",
            "flight_skip_reason": "no_origin_for_flights",
        }
    )
    context = _build_synthesis_context(state, response_type="specialist_update")

    assert "- status: skipped_no_origin" in context
    assert "- skip_reason: no_origin_for_flights" in context
    assert "Do NOT claim flights were found" in context


def test_ground_flight_response_removes_hallucinated_counts_and_prompts_origin() -> None:
    state = _new_state(
        metadata={
            "trip_inputs": {"booking_types": {"flights": "on"}},
            "flight_search_status": "skipped_no_origin",
            "flight_skip_reason": "no_origin_for_flights",
        }
    )
    state.tiles = {"flights": []}

    grounded = _ground_flight_response(
        "Now showing direct flights. Found **2 flights**.",
        state,
    )

    assert "Found **2 flights**" not in grounded
    assert "Now showing direct flights." not in grounded
    assert "departure city" in grounded


@pytest.mark.asyncio
async def test_synthesizer_settings_only_uses_terse_ack_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _new_state(
        metadata={
            "settings_just_updated": True,
            "actionable_acknowledgment": "Applied your preference.",
            "constraint_violations": [],
            "added_categories": [],
            "tier2_tiles_generated": False,
            "tier2_new_content_generated": False,
        },
        last_human="direct flights",
    )
    calls = {"llm": 0}

    async def _fake_enrich_with_images(_state: GraphState) -> None:
        return None

    async def _fake_synthesize_with_llm(_state: GraphState, _response_type: str):
        calls["llm"] += 1
        return ("should not be used", None)

    monkeypatch.setattr(synthesizer_module, "enrich_with_images", _fake_enrich_with_images)
    monkeypatch.setattr(synthesizer_module, "synthesize_with_llm", _fake_synthesize_with_llm)
    monkeypatch.setattr(synthesizer_module, "generate_suggestions", lambda _state: [])

    await synthesizer_module.synthesizer(state)

    assert calls["llm"] == 0
    assert state.last_summary == "Applied your preference."
    assert state.metadata.get("synthesizer_output", {}).get("used_llm") is False


@pytest.mark.asyncio
async def test_synthesizer_ignores_legacy_tier2_generated_flag_when_no_new_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _new_state(
        metadata={
            "settings_just_updated": True,
            "actionable_acknowledgment": "Applied your preference.",
            "constraint_violations": [],
            "added_categories": [],
            "tier2_tiles_generated": True,  # legacy flag can still be present
            "tier2_new_content_generated": False,
        },
        last_human="direct flights",
    )
    calls = {"llm": 0}

    async def _fake_enrich_with_images(_state: GraphState) -> None:
        return None

    async def _fake_synthesize_with_llm(_state: GraphState, _response_type: str):
        calls["llm"] += 1
        return ("should not be used", None)

    monkeypatch.setattr(synthesizer_module, "enrich_with_images", _fake_enrich_with_images)
    monkeypatch.setattr(synthesizer_module, "synthesize_with_llm", _fake_synthesize_with_llm)
    monkeypatch.setattr(synthesizer_module, "generate_suggestions", lambda _state: [])

    await synthesizer_module.synthesizer(state)

    assert calls["llm"] == 0
    assert state.metadata.get("synthesizer_output", {}).get("used_llm") is False


@pytest.mark.asyncio
async def test_synthesizer_tracks_llm_tokens_in_compact_logger_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _new_state(
        metadata={
            "settings_just_updated": True,
            "constraint_violations": [],
            "added_categories": ["nightlife"],
            "tier2_tiles_generated": True,
            "tier2_new_content_generated": True,
            "_metrics": RequestMetrics(start_time=time.time()),
        },
        last_human="add nightlife",
    )
    calls = {"llm": 0}

    async def _fake_enrich_with_images(_state: GraphState) -> None:
        return None

    async def _fake_synthesize_with_llm(_state: GraphState, _response_type: str):
        calls["llm"] += 1
        return (
            "LLM response",
            {
                "model": "gemini-2.5-flash",
                "prompt_tokens": 123,
                "completion_tokens": 45,
                "total_tokens": 168,
            },
        )

    monkeypatch.setattr(synthesizer_module, "enrich_with_images", _fake_enrich_with_images)
    monkeypatch.setattr(synthesizer_module, "synthesize_with_llm", _fake_synthesize_with_llm)
    monkeypatch.setattr(synthesizer_module, "generate_suggestions", lambda _state: [])

    await synthesizer_module.synthesizer(state)

    assert calls["llm"] == 1
    assert state.metadata.get("synthesizer_output", {}).get("used_llm") is True
    node_tokens = state.metadata["_metrics"].node_tokens.get("SYNTHESIZER")
    assert node_tokens is not None
    assert node_tokens.prompt == 123
    assert node_tokens.completion == 45
