from __future__ import annotations

import importlib

import pytest

from app.planner.nodes.router_extraction import IntentClassification, RouterOutput
from app.planner.state import ExtractedTripFields
from app.planner.state.typed_meta import get_turn_meta, sync_turn_meta


@pytest.mark.asyncio
async def test_destination_switch_is_blocked_and_requires_reset_button(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Non-live graph regression for destination switching with session_state carry-forward.

    Validates that switching destination after destination is set:
    1) is blocked with RESET-button-required message,
    2) preserves current destination,
    3) does not rerun local_expert/logistics for a new destination.
    """
    plan_graph = importlib.import_module("app.plan_graph")
    router_module = importlib.import_module("app.planner.nodes.intent_router")
    architect_module = importlib.import_module("app.planner.nodes.trip_architect")
    local_expert_destinations: list[str] = []

    async def _stub_classify_and_extract_with_llm(user_text: str, _state):
        text = (user_text or "").lower()
        destination = _state.trip_plan.destination
        start_date = _state.trip_plan.start_date
        end_date = _state.trip_plan.end_date

        if "bali" in text:
            destination = "Bali"
            start_date = "2026-03-01"
            end_date = "2026-03-07"
        elif "rome" in text:
            destination = "Rome"
            start_date = start_date or "2026-03-01"
            end_date = end_date or "2026-03-07"

        return (
            RouterOutput(
                intent="PLANNING",
                confidence=0.9,
                reasoning="stub extraction",
                destination=destination,
                start_date=start_date,
                end_date=end_date,
                planning_intent="modifying" if "switch" in text else "ready",
                has_dates_in_message=bool(start_date and end_date),
            ),
            {},
        )

    async def _stub_classify_intent_with_llm(_user_text: str, _state):
        return (
            IntentClassification(
                intent="PLANNING",
                confidence=0.9,
                reasoning="stub classification",
                specialist_hints=[],
            ),
            {},
        )

    async def _stub_extract_fields_with_llm(user_text: str, current_plan):
        text = (user_text or "").lower()
        if "rome" in text and "switch" in text:
            return ExtractedTripFields(destination="Rome"), {}
        if "bali" in text:
            return (
                ExtractedTripFields(
                    destination="Bali",
                    start_date="2026-03-01",
                    end_date="2026-03-07",
                ),
                {},
            )
        return ExtractedTripFields(), {}

    async def _stub_local_expert(state):
        destination = state.trip_plan.destination or "unknown"
        local_expert_destinations.append(destination)

        state.metadata["local_expert_ran"] = True
        state.metadata["last_executed_specialist"] = "local_expert"
        state.metadata["executed_strategy_topics"] = ["local_expert"]
        state.metadata["strategy_sections"] = [
            {
                "specialist_type": "local_expert",
                "destination": destination,
                "content_added": [],
            }
        ]
        return state

    async def _stub_logistics(state):
        destination = state.trip_plan.destination or "unknown"
        state.tiles = {
            "hotels": [{"id": f"{destination.lower()}-hotel"}],
            "activities": [{"id": f"{destination.lower()}-activity"}],
            "flights": [],
        }
        state.metadata["tiles_destination"] = destination

        turn = get_turn_meta(state)
        turn.logistics_attempted = True
        sync_turn_meta(state, turn)
        return state

    async def _stub_guard(state):
        return state

    async def _stub_synthesizer(state):
        if state.metadata.get("short_circuit_type") == "destination_locked":
            if not state.suggested_replies:
                state.suggested_replies = ["Continue current plan", "Set my dates"]
            return state
        state.last_summary = f"Stub summary for {state.trip_plan.destination}"
        state.suggested_replies = ["Next", "Adjust", "Continue"]
        return state

    async def _stub_vertical_specialist(state):
        return state

    monkeypatch.setattr(
        router_module, "_classify_and_extract_with_llm", _stub_classify_and_extract_with_llm
    )
    monkeypatch.setattr(router_module, "_classify_intent_with_llm", _stub_classify_intent_with_llm)
    monkeypatch.setattr(architect_module, "_extract_fields_with_llm", _stub_extract_fields_with_llm)

    monkeypatch.setattr(plan_graph, "local_expert", _stub_local_expert)
    monkeypatch.setattr(plan_graph, "logistics_node", _stub_logistics)
    monkeypatch.setattr(plan_graph, "constraint_guard", _stub_guard)
    monkeypatch.setattr(plan_graph, "synthesizer", _stub_synthesizer)
    monkeypatch.setattr(plan_graph, "vertical_specialist", _stub_vertical_specialist)
    monkeypatch.setattr(plan_graph, "_graph", None)

    first = await plan_graph.run_turn("I want to go to Bali from March 1 to March 7 2026")
    first_state = first.get("session_state", {})
    assert first_state.get("trip_inputs", {}).get("destination") == "Bali"
    assert local_expert_destinations == ["Bali"]

    second = await plan_graph.run_turn(
        "change to rome",
        session_state=first_state,
    )
    second_state = second.get("session_state", {})
    second_meta = second_state.get("metadata", {})
    second_sections = second_meta.get("strategy_sections", [])

    assert second_state.get("trip_inputs", {}).get("destination") == "Bali"
    assert second_meta.get("short_circuit_type") == "destination_locked"
    assert second_meta.get("destination_switch_blocked") == {"from": "Bali", "to": "Rome"}
    assert "click the **reset** button" in (second.get("assistant_message") or "").lower()
    assert all(reply.lower() != "reset" for reply in second.get("suggested_responses", []))
    assert local_expert_destinations == ["Bali"]
    assert second_meta.get("tiles_destination") == "Bali"
    assert second_sections and second_sections[0].get("destination") == "Bali"
