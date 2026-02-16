from __future__ import annotations

import importlib
from types import SimpleNamespace

from app.planner.services.response_envelope import format_result
from app.planner.state import GraphState, TripPlan

itinerary_adapter_module = importlib.import_module("app.planner.services.itinerary_adapter")


def _strategy_ready_state() -> GraphState:
    state = GraphState(
        trip_plan=TripPlan(destination="Bali", start_date="2026-02-15", end_date="2026-02-20")
    )
    state.tiles = {
        "activities": [{"id": "act_1", "type": "activity", "title": "Activity 1"}],
        "hotels": [],
        "flights": [],
    }
    state.metadata.update(
        {
            "strategy_sections": [
                {
                    "id": "strategy_diving",
                    "specialist_type": "diving",
                    "content_added": [{"title": "Dive"}],
                    "constraints_applied": [],
                }
            ],
            "executed_strategy_topics": ["diving"],
            "last_executed_specialist": "diving",
        }
    )
    state.last_summary = "ok"
    return state


def test_format_result_reuses_cached_itinerary_for_question_answer(monkeypatch):
    state = _strategy_ready_state()
    cache_key = "Bali|2026-02-15|2026-02-20"
    cached_cards = [{"day_number": 1, "label": "Day 1", "blocks": []}]
    state.metadata.update(
        {
            "short_circuit_type": "question_answer",
            "last_itinerary_day_cards": cached_cards,
            "last_itinerary_view_state": "S3_ITINERARY_READY",
            "last_itinerary_cache_key": cache_key,
        }
    )
    calls = {"builder": 0}

    def _fail_builder(_state):
        calls["builder"] += 1
        raise AssertionError("builder should not run when cached itinerary is reused")

    monkeypatch.setattr(itinerary_adapter_module, "build_itinerary_from_state", _fail_builder)

    result = format_result(state)

    assert calls["builder"] == 0
    assert result["document"]["itinerary_day_cards"] == cached_cards
    assert result["document"]["plan_view_state"] == "S3_ITINERARY_READY"


def test_format_result_builds_itinerary_when_cache_missing(monkeypatch):
    state = _strategy_ready_state()
    state.metadata["short_circuit_type"] = "question_answer"
    calls = {"builder": 0}

    class _Card:
        def model_dump(self):
            return {"day_number": 1, "label": "Day 1", "blocks": []}

    fake_result = SimpleNamespace(
        success=True,
        day_cards=[_Card()],
        conflicts=[],
        total_activities_input=0,
        total_activities_placed=0,
        resolutions=[],
    )

    def _fake_builder(_state):
        calls["builder"] += 1
        return fake_result

    monkeypatch.setattr(itinerary_adapter_module, "build_itinerary_from_state", _fake_builder)

    result = format_result(state)

    assert calls["builder"] == 1
    assert result["document"]["plan_view_state"] == "S3_ITINERARY_READY"
    assert result["document"]["itinerary_day_cards"] == [
        {"day_number": 1, "label": "Day 1", "blocks": []}
    ]
    assert state.metadata["last_itinerary_day_cards"] == result["document"]["itinerary_day_cards"]
