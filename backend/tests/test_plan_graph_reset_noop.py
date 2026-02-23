from __future__ import annotations

import pytest

from app.plan_graph import run_turn, run_turn_streaming


@pytest.mark.asyncio
async def test_run_turn_plain_reset_is_noop_and_does_not_invoke_graph(monkeypatch):
    import app.plan_graph as plan_graph

    def _should_not_run_graph():
        raise AssertionError("graph should not be invoked for plain chat reset")

    monkeypatch.setattr(plan_graph, "get_or_create_graph", _should_not_run_graph)

    session_state = {
        "trip_inputs": {"destination": "Amsterdam"},
        "metadata": {"plan_view_state": "S0_BOOTSTRAP"},
    }
    result = await run_turn("reset", session_state=session_state)

    assert result["assistant_message"] == ""
    assert result["session_state"] == session_state
    assert result["trip_inputs"]["destination"] == "Amsterdam"
    assert result["ui_events"] == []


@pytest.mark.asyncio
async def test_run_turn_reset_noop_preserves_ready_state():
    session_state = {
        "trip_inputs": {
            "destination": "Amsterdam",
            "start_date": "2026-03-01",
            "end_date": "2026-03-07",
        },
        "metadata": {"plan_view_state": "S1_SETUP"},
    }
    result = await run_turn("reset", session_state=session_state)

    assert result["ready_to_generate"] is True


@pytest.mark.asyncio
async def test_run_turn_streaming_plain_reset_emits_single_complete_noop_event():
    session_state = {
        "trip_inputs": {"destination": "Amsterdam"},
        "metadata": {"plan_view_state": "S0_BOOTSTRAP"},
    }

    events = []
    async for event in run_turn_streaming("reset", session_state=session_state):
        events.append(event)

    assert len(events) == 1
    assert events[0]["type"] == "complete"
    payload = events[0]["data"]
    assert payload["assistant_message"] == ""
    assert payload["session_state"] == session_state
    assert payload["ui_events"] == []


@pytest.mark.asyncio
async def test_run_turn_streaming_reset_noop_preserves_ready_state():
    session_state = {
        "trip_inputs": {
            "destination": "Amsterdam",
            "start_date": "2026-03-01",
            "end_date": "2026-03-07",
        },
        "metadata": {"plan_view_state": "S1_SETUP"},
    }

    events = []
    async for event in run_turn_streaming("reset", session_state=session_state):
        events.append(event)

    payload = events[0]["data"]
    assert payload["ready_to_generate"] is True


@pytest.mark.asyncio
async def test_run_turn_slash_reset_is_noop():
    session_state = {
        "trip_inputs": {"destination": "Amsterdam"},
        "metadata": {"plan_view_state": "S0_BOOTSTRAP"},
    }
    result = await run_turn("/reset", session_state=session_state)

    assert result["assistant_message"] == ""
    assert result["ui_events"] == []
    assert result["session_state"] == session_state


@pytest.mark.asyncio
async def test_run_turn_stop_and_clear_are_noop():
    session_state = {
        "trip_inputs": {"destination": "Amsterdam"},
        "metadata": {"plan_view_state": "S0_BOOTSTRAP"},
    }

    stop_result = await run_turn("stop", session_state=session_state)
    clear_result = await run_turn("clear", session_state=session_state)

    assert stop_result["assistant_message"] == ""
    assert clear_result["assistant_message"] == ""
    assert stop_result["ui_events"] == []
    assert clear_result["ui_events"] == []
    assert stop_result["session_state"] == session_state
    assert clear_result["session_state"] == session_state
