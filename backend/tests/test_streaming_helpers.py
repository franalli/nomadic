"""Tests for pure helper functions in streaming.py."""

from types import SimpleNamespace

from app.streaming import (
    TripReadiness,
    _conflicts_to_constraint_violations,
    _flatten_request_preferences,
    _get_trip_input_display_value,
    _normalized_preference_ids,
    _seed_trip_plan_from_inputs,
    compute_trip_readiness,
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
