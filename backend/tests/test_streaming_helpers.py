"""Tests for pure helper functions in streaming.py."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.streaming import (
    TripReadiness,
    _conflicts_to_constraint_violations,
    _flatten_request_preferences,
    _get_trip_input_display_value,
    _normalized_preference_ids,
    _seed_trip_plan_from_inputs,
    compute_trip_readiness,
    generate_sse,
)

# ---------------------------------------------------------------------------
# compute_trip_readiness
# ---------------------------------------------------------------------------


def test_compute_trip_readiness_empty_inputs() -> None:
    result = compute_trip_readiness({})
    assert result == TripReadiness(
        has_origin=False,
        has_destination=False,
        has_dates=False,
        core_complete=False,
    )


def test_compute_trip_readiness_destination_only() -> None:
    result = compute_trip_readiness({"destination": "Bali"})
    assert result.has_destination is True
    assert result.has_origin is False
    assert result.has_dates is False
    assert result.core_complete is False


def test_compute_trip_readiness_destination_and_start_date() -> None:
    result = compute_trip_readiness({"destination": "Bali", "start_date": "2026-06-01"})
    assert result.has_destination is True
    assert result.has_dates is True
    assert result.core_complete is True


def test_compute_trip_readiness_all_fields() -> None:
    result = compute_trip_readiness(
        {
            "destination": "Bali",
            "origin": "Rome",
            "start_date": "2026-06-01",
            "end_date": "2026-06-07",
        }
    )
    assert result.has_origin is True
    assert result.has_destination is True
    assert result.has_dates is True
    assert result.core_complete is True


# ---------------------------------------------------------------------------
# _normalized_preference_ids
# ---------------------------------------------------------------------------


def test_normalized_preference_ids_none() -> None:
    assert _normalized_preference_ids(None) == []


def test_normalized_preference_ids_empty_list() -> None:
    assert _normalized_preference_ids([]) == []


def test_normalized_preference_ids_duplicates() -> None:
    result = _normalized_preference_ids(["b", "a", "b", "c", "a"])
    assert result == ["a", "b", "c"]


def test_normalized_preference_ids_filters_empty_strings() -> None:
    result = _normalized_preference_ids(["x", "", "y", ""])
    assert result == ["x", "y"]


# ---------------------------------------------------------------------------
# _flatten_request_preferences
# ---------------------------------------------------------------------------


def test_flatten_request_preferences_none() -> None:
    assert _flatten_request_preferences(None) == {"preferred_tile_ids": []}


def test_flatten_request_preferences_merges_and_deduplicates() -> None:
    prefs = SimpleNamespace(
        preferred_hotel_ids=["h1", "h2"],
        preferred_activity_ids=["a1", "h1"],
        preferred_flight_ids=["f1"],
    )
    result = _flatten_request_preferences(prefs)
    assert result == {"preferred_tile_ids": ["a1", "f1", "h1", "h2"]}


def test_flatten_request_preferences_handles_none_sublists() -> None:
    prefs = SimpleNamespace(
        preferred_hotel_ids=None,
        preferred_activity_ids=["a1"],
        preferred_flight_ids=None,
    )
    result = _flatten_request_preferences(prefs)
    assert result == {"preferred_tile_ids": ["a1"]}


# ---------------------------------------------------------------------------
# _get_trip_input_display_value
# ---------------------------------------------------------------------------


def test_display_value_destination() -> None:
    assert _get_trip_input_display_value("destination", {"destination": "Bali"}) == "Bali"


def test_display_value_origin() -> None:
    assert _get_trip_input_display_value("origin", {"origin": "Rome"}) == "Rome"


def test_display_value_dates_start_and_end() -> None:
    val = _get_trip_input_display_value(
        "dates", {"start_date": "2026-06-01", "end_date": "2026-06-07"}
    )
    assert val == "2026-06-01 \u2013 2026-06-07"


def test_display_value_dates_start_only() -> None:
    val = _get_trip_input_display_value("dates", {"start_date": "2026-06-01"})
    assert val == "2026-06-01"


def test_display_value_dates_missing() -> None:
    assert _get_trip_input_display_value("dates", {}) is None


def test_display_value_budget() -> None:
    val = _get_trip_input_display_value("budget", {"budget": 5000, "currency": "USD"})
    assert val == "USD 5000"


def test_display_value_budget_default_currency() -> None:
    val = _get_trip_input_display_value("budget", {"budget": 3000})
    assert val == "USD 3000"


def test_display_value_budget_missing() -> None:
    assert _get_trip_input_display_value("budget", {}) is None


def test_display_value_travelers_adults_only() -> None:
    val = _get_trip_input_display_value("travelers", {"adults": 2})
    assert val == "2 adults"


def test_display_value_travelers_one_adult() -> None:
    val = _get_trip_input_display_value("travelers", {"adults": 1})
    assert val == "1 adult"


def test_display_value_travelers_adults_and_children() -> None:
    val = _get_trip_input_display_value("travelers", {"adults": 1, "children": 2})
    assert val == "1 adult, 2 children"


def test_display_value_travelers_one_child() -> None:
    val = _get_trip_input_display_value("travelers", {"adults": 2, "children": 1})
    assert val == "2 adults, 1 child"


def test_display_value_travelers_missing() -> None:
    assert _get_trip_input_display_value("travelers", {}) is None


def test_display_value_flights_direct_only() -> None:
    ti = {
        "booking_types": {"flights": "on"},
        "flight_settings": {"direct_only": True, "cabin_class": "economy"},
    }
    val = _get_trip_input_display_value("flights", ti)
    assert val == "Direct"


def test_display_value_flights_business() -> None:
    ti = {
        "booking_types": {"flights": "on"},
        "flight_settings": {"direct_only": False, "cabin_class": "business"},
    }
    val = _get_trip_input_display_value("flights", ti)
    assert val == "Business"


def test_display_value_flights_enabled_default() -> None:
    ti = {
        "booking_types": {"flights": "on"},
        "flight_settings": {"direct_only": False, "cabin_class": "economy"},
    }
    val = _get_trip_input_display_value("flights", ti)
    assert val == "Enabled"


def test_display_value_flights_disabled() -> None:
    ti = {"booking_types": {"flights": None}}
    assert _get_trip_input_display_value("flights", ti) is None


def test_display_value_hotels_with_stars() -> None:
    ti = {
        "booking_types": {"hotels": "on"},
        "hotel_settings": {"min_stars": 3},
    }
    val = _get_trip_input_display_value("hotels", ti)
    assert val == "3+ stars"


def test_display_value_hotels_enabled_no_stars() -> None:
    ti = {
        "booking_types": {"hotels": "on"},
        "hotel_settings": {"min_stars": 0},
    }
    val = _get_trip_input_display_value("hotels", ti)
    assert val == "Enabled"


def test_display_value_booking_types_flights_on() -> None:
    ti = {"booking_types": {"flights": "on"}}
    assert _get_trip_input_display_value("booking_types.flights", ti) == "Enabled"


def test_display_value_booking_types_flights_off() -> None:
    ti = {"booking_types": {"flights": "off"}}
    assert _get_trip_input_display_value("booking_types.flights", ti) == "Disabled"


def test_display_value_booking_types_flights_suggested() -> None:
    ti = {"booking_types": {"flights": "suggested"}}
    assert _get_trip_input_display_value("booking_types.flights", ti) == "Auto"


def test_display_value_flight_settings_direct_only_true() -> None:
    ti = {"flight_settings": {"direct_only": True}}
    assert _get_trip_input_display_value("flight_settings.direct_only", ti) == "Direct flights only"


def test_display_value_flight_settings_direct_only_false() -> None:
    ti = {"flight_settings": {"direct_only": False}}
    assert _get_trip_input_display_value("flight_settings.direct_only", ti) == "Connections OK"


def test_display_value_flight_settings_cabin_class() -> None:
    ti = {"flight_settings": {"cabin_class": "first_class"}}
    assert _get_trip_input_display_value("flight_settings.cabin_class", ti) == "First Class"


def test_display_value_hotel_settings_min_stars_positive() -> None:
    ti = {"hotel_settings": {"min_stars": 3}}
    assert _get_trip_input_display_value("hotel_settings.min_stars", ti) == "3+ stars"


def test_display_value_hotel_settings_min_stars_zero() -> None:
    ti = {"hotel_settings": {"min_stars": 0}}
    assert _get_trip_input_display_value("hotel_settings.min_stars", ti) == "Any rating"


def test_display_value_hotel_settings_min_stars_none() -> None:
    ti = {"hotel_settings": {}}
    assert _get_trip_input_display_value("hotel_settings.min_stars", ti) is None


def test_display_value_unknown_key() -> None:
    assert _get_trip_input_display_value("nonexistent_key", {"destination": "Bali"}) is None


# ---------------------------------------------------------------------------
# _conflicts_to_constraint_violations
# ---------------------------------------------------------------------------


def _make_conflict(
    type_: str = "temporal_overlap",
    severity: str = "warning",
    message: str = "Activities overlap on day 2",
) -> SimpleNamespace:
    return SimpleNamespace(type=type_, severity=severity, message=message)


def _make_resolution(description: str = "Extend trip by 1 day") -> SimpleNamespace:
    return SimpleNamespace(description=description)


def test_conflicts_to_violations_basic_mapping() -> None:
    conflicts = [_make_conflict()]
    result = _conflicts_to_constraint_violations(conflicts)
    assert len(result) == 1
    v = result[0]
    assert v["code"] == "TEMPORAL_OVERLAP"
    assert v["message"] == "Activities overlap on day 2"
    assert v["severity"] == "warning"
    assert v["category"] == "itinerary"
    assert v["suggested_action"] is None


def test_conflicts_to_violations_with_resolutions() -> None:
    conflicts = [_make_conflict()]
    resolutions = [_make_resolution("Extend trip by 1 day")]
    result = _conflicts_to_constraint_violations(conflicts, resolutions)
    assert result[0]["suggested_action"] == "Extend trip by 1 day"


def test_conflicts_to_violations_multiple() -> None:
    conflicts = [
        _make_conflict("temporal_overlap", "warning", "Overlap on day 2"),
        _make_conflict("capacity_exceeded", "blocking", "Too many activities"),
    ]
    result = _conflicts_to_constraint_violations(conflicts)
    assert len(result) == 2
    assert result[0]["code"] == "TEMPORAL_OVERLAP"
    assert result[1]["code"] == "CAPACITY_EXCEEDED"
    assert result[1]["severity"] == "blocking"


def test_conflicts_to_violations_enum_severity() -> None:
    """Conflict with an enum-style severity (has .value attribute)."""
    severity_enum = SimpleNamespace(value="blocking")
    conflict = SimpleNamespace(
        type="budget_exceeded",
        severity=severity_enum,
        message="Over budget",
    )
    result = _conflicts_to_constraint_violations([conflict])
    assert result[0]["severity"] == "blocking"


def test_conflicts_to_violations_empty_list() -> None:
    assert _conflicts_to_constraint_violations([]) == []


@pytest.mark.asyncio
async def test_generate_sse_releases_slot_when_db_session_open_fails(monkeypatch) -> None:
    """SSE slots must be released even when DB session setup fails after acquisition."""

    class _FailingSessionContext:
        async def __aenter__(self):
            raise RuntimeError("db open failed")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    release_slot = AsyncMock()
    monkeypatch.setattr(
        "app.streaming._get_async_session_factory",
        lambda: (lambda: _FailingSessionContext()),
    )
    monkeypatch.setattr(
        "app.streaming._cleanup_pending_enrichment",
        AsyncMock(return_value=False),
    )

    stream = generate_sse(
        session_id="session-123",
        req=SimpleNamespace(message="Plan Bali", trip_inputs=None),
        session_state={},
        request_id="req-1",
        today_iso="2026-03-11",
        session_key="session:session-123",
        ip_key="ip:127.0.0.1",
        request=SimpleNamespace(),
        try_acquire_sse_slot=AsyncMock(return_value=None),
        release_sse_slot=release_slot,
        sanitize_trip_inputs_for_category_merge=lambda inputs, _message: inputs,
        merge_user_owned_trip_settings=lambda *args, **kwargs: None,
        resolve_itinerary_document_view_state=lambda *args, **kwargs: "S0_BOOTSTRAP",
    )

    with pytest.raises(RuntimeError, match="db open failed"):
        async for _chunk in stream:
            pass

    release_slot.assert_awaited_once_with("session:session-123", "ip:127.0.0.1")


@pytest.mark.asyncio
async def test_generate_sse_closes_coordinator_event_source_on_disconnect(
    monkeypatch,
) -> None:
    """Disconnects should close the coordinator generator immediately."""

    class _SessionContext:
        async def __aenter__(self):
            return SimpleNamespace()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _FakeEventSource:
        def __init__(self, cancel_event: asyncio.Event) -> None:
            self._cancel_event = cancel_event
            self._yielded = False
            self.closed = False
            self.closed_after_cancel = False
            self.aclose_calls = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.closed or self._yielded:
                raise StopAsyncIteration
            self._yielded = True
            return {"type": "token", "data": "hello"}

        async def aclose(self) -> None:
            self.aclose_calls += 1
            self.closed_after_cancel = self._cancel_event.is_set()
            self.closed = True

    release_slot = AsyncMock()
    event_source: _FakeEventSource | None = None

    def _fake_execute_turn(*, cancel_event: asyncio.Event, **_kwargs):
        nonlocal event_source
        event_source = _FakeEventSource(cancel_event)
        return event_source

    monkeypatch.setattr(
        "app.streaming._get_async_session_factory",
        lambda: (lambda: _SessionContext()),
    )
    monkeypatch.setattr(
        "app.streaming.get_or_create_session",
        AsyncMock(return_value=SimpleNamespace()),
    )
    monkeypatch.setattr(
        "app.streaming.get_or_create_document",
        AsyncMock(side_effect=RuntimeError("skip document")),
    )
    monkeypatch.setattr(
        "app.streaming._cleanup_pending_enrichment",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.planner.services.state_serde.restore_agent_state",
        lambda state: state,
    )
    monkeypatch.setattr(
        "app.planner.services.agent_runner.run_agent_turn_streaming",
        _fake_execute_turn,
    )

    stream = generate_sse(
        session_id="session-123",
        req=SimpleNamespace(message="Plan Bali", trip_inputs=None),
        session_state={},
        request_id="req-2",
        today_iso="2026-03-11",
        session_key="session:session-123",
        ip_key="ip:127.0.0.1",
        request=SimpleNamespace(is_disconnected=AsyncMock(return_value=True)),
        try_acquire_sse_slot=AsyncMock(return_value=None),
        release_sse_slot=release_slot,
        sanitize_trip_inputs_for_category_merge=lambda inputs, _message: inputs,
        merge_user_owned_trip_settings=lambda *args, **kwargs: None,
        resolve_itinerary_document_view_state=lambda *args, **kwargs: "S0_BOOTSTRAP",
    )

    chunks = [chunk async for chunk in stream]

    assert chunks == [
        'event: error\ndata: {"type": "error", "message": "No result from graph"}\n\n'
    ]
    assert event_source is not None
    assert event_source.closed is True
    assert event_source.closed_after_cancel is True
    assert event_source.aclose_calls == 1
    release_slot.assert_awaited_once_with("session:session-123", "ip:127.0.0.1")


@pytest.mark.asyncio
async def test_generate_sse_preserves_complete_event_before_disconnect_short_circuit(
    monkeypatch,
) -> None:
    """A just-received complete event must survive a late disconnect."""

    class _SessionContext:
        async def __aenter__(self):
            return SimpleNamespace()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    final_result = {
        "assistant_message": "Finished plan.",
        "session_state": {},
        "document": {
            "plan_view_state": "S0_BOOTSTRAP",
            "strategy_sections": [],
            "tiles": {},
            "trip_inputs": {"destination": "Bali"},
            "itinerary_day_cards": [],
        },
    }

    class _FakeEventSource:
        def __init__(self, cancel_event: asyncio.Event) -> None:
            self._cancel_event = cancel_event
            self._yielded = False
            self.closed = False
            self.closed_after_cancel = False
            self.aclose_calls = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.closed or self._yielded:
                raise StopAsyncIteration
            self._yielded = True
            return {"type": "complete", "data": final_result}

        async def aclose(self) -> None:
            self.aclose_calls += 1
            self.closed_after_cancel = self._cancel_event.is_set()
            self.closed = True

    release_slot = AsyncMock()
    event_source: _FakeEventSource | None = None

    def _fake_execute_turn(*, cancel_event: asyncio.Event, **_kwargs):
        nonlocal event_source
        event_source = _FakeEventSource(cancel_event)
        return event_source

    monkeypatch.setattr(
        "app.streaming._get_async_session_factory",
        lambda: (lambda: _SessionContext()),
    )
    monkeypatch.setattr(
        "app.streaming.get_or_create_session",
        AsyncMock(return_value=SimpleNamespace()),
    )
    monkeypatch.setattr(
        "app.streaming.get_or_create_document",
        AsyncMock(side_effect=RuntimeError("skip document")),
    )
    monkeypatch.setattr(
        "app.streaming._cleanup_pending_enrichment",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.planner.services.state_serde.restore_agent_state",
        lambda state: state,
    )
    monkeypatch.setattr(
        "app.planner.services.agent_runner.run_agent_turn_streaming",
        _fake_execute_turn,
    )

    stream = generate_sse(
        session_id="session-123",
        req=SimpleNamespace(message="Plan Bali", trip_inputs=None, ui_phase=None),
        session_state={},
        request_id="req-3",
        today_iso="2026-03-11",
        session_key="session:session-123",
        ip_key="ip:127.0.0.1",
        request=SimpleNamespace(is_disconnected=AsyncMock(return_value=True)),
        try_acquire_sse_slot=AsyncMock(return_value=None),
        release_sse_slot=release_slot,
        sanitize_trip_inputs_for_category_merge=lambda inputs, _message: inputs,
        merge_user_owned_trip_settings=lambda *args, **kwargs: None,
        resolve_itinerary_document_view_state=lambda *args, **kwargs: "S0_BOOTSTRAP",
    )

    chunks = [chunk async for chunk in stream]

    assert chunks[-1].startswith("event: complete\ndata: ")
    assert all("No result from graph" not in chunk for chunk in chunks)
    assert event_source is not None
    assert event_source.closed is True
    assert event_source.closed_after_cancel is True
    assert event_source.aclose_calls == 1
    release_slot.assert_awaited_once_with("session:session-123", "ip:127.0.0.1")


# ---------------------------------------------------------------------------
# _seed_trip_plan_from_inputs
# ---------------------------------------------------------------------------


def test_seed_trip_plan_copies_present_fields() -> None:
    """Core fields in trip_inputs should be copied to trip_plan."""
    state: dict = {
        "trip_inputs": {
            "destination": "Bali",
            "origin": "London",
            "start_date": "2026-06-01",
            "end_date": "2026-06-07",
        },
        "trip_plan": {"destination": "Old Place"},
    }
    _seed_trip_plan_from_inputs(state)
    assert state["trip_plan"]["destination"] == "Bali"
    assert state["trip_plan"]["origin"] == "London"
    assert state["trip_plan"]["start_date"] == "2026-06-01"
    assert state["trip_plan"]["end_date"] == "2026-06-07"


def test_seed_trip_plan_propagates_none_for_cleared_fields() -> None:
    """Explicitly cleared fields (None) must propagate to trip_plan."""
    state: dict = {
        "trip_inputs": {"origin": None},
        "trip_plan": {"origin": "London", "destination": "Bali"},
    }
    _seed_trip_plan_from_inputs(state)
    assert state["trip_plan"]["origin"] is None
    # Unmentioned fields are untouched
    assert state["trip_plan"]["destination"] == "Bali"


def test_seed_trip_plan_preserves_stale_when_key_absent() -> None:
    """When trip_inputs lacks a key entirely, trip_plan retains its value."""
    state: dict = {
        "trip_inputs": {"destination": "Tokyo"},
        "trip_plan": {"destination": "Old", "origin": "London"},
    }
    _seed_trip_plan_from_inputs(state)
    assert state["trip_plan"]["destination"] == "Tokyo"
    # origin not in trip_inputs → trip_plan keeps its value
    assert state["trip_plan"]["origin"] == "London"


def test_seed_trip_plan_ignores_settings_fields() -> None:
    """Settings fields should NOT be seeded (they flow via _doc_settings)."""
    state: dict = {
        "trip_inputs": {
            "destination": "Bali",
            "booking_types": {"flights": "on"},
            "flight_settings": {"direct_only": True},
        },
        "trip_plan": {},
    }
    _seed_trip_plan_from_inputs(state)
    assert state["trip_plan"]["destination"] == "Bali"
    assert "booking_types" not in state["trip_plan"]
    assert "flight_settings" not in state["trip_plan"]


def test_seed_trip_plan_creates_trip_plan_if_missing() -> None:
    """When trip_plan is absent from session_state, it should be created."""
    state: dict = {
        "trip_inputs": {"destination": "Rome", "adults": 2},
    }
    _seed_trip_plan_from_inputs(state)
    assert state["trip_plan"]["destination"] == "Rome"
    assert state["trip_plan"]["adults"] == 2


def test_seed_trip_plan_empty_inputs() -> None:
    """Empty trip_inputs should leave trip_plan unchanged."""
    state: dict = {
        "trip_inputs": {},
        "trip_plan": {"destination": "Bali"},
    }
    _seed_trip_plan_from_inputs(state)
    assert state["trip_plan"]["destination"] == "Bali"
