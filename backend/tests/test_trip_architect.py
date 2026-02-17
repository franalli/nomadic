# backend/tests/test_trip_architect.py
"""
Snapshot tests for trip_architect.py — field extraction, pivot detection, settings parsing.

No LLM mocking needed for these tests — they exercise pure logic functions.
"""

import pytest

from app.planner.nodes.trip_architect import (
    TripArchitect,
    _auto_toggle_flights,
    _detect_and_handle_pivot,
    _has_settings_keywords,
    _resolve_flexible_dates,
)
from app.planner.state.graph_state import GraphState, TripPlan


def _make_state(
    destination: str | None = None,
    origin: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    **meta_overrides: object,
) -> GraphState:
    """Build a minimal GraphState for testing."""
    plan = TripPlan(
        destination=destination,
        origin=origin,
        start_date=start_date,
        end_date=end_date,
        adults=2,
    )
    metadata: dict = {
        "strategy_sections": [],
        "executed_strategy_topics": [],
        "pending_strategy_topics": [],
        "plan_view_state": "S2_STRATEGY_READY",
    }
    metadata.update(meta_overrides)
    return GraphState(trip_plan=plan, messages=[], metadata=metadata)


# =============================================================================
# _detect_and_handle_pivot
# =============================================================================


class TestDetectAndHandlePivot:
    """Pivot detection clears dependent state when destination changes."""

    def test_pivot_clears_state(self) -> None:
        state = _make_state(destination="Tokyo")
        state.trip_plan.itinerary_blocks = [{"day": 1}]
        state.trip_plan.constraints = [{"rule": "no-fly-24h"}]
        state.tiles = {"hotel": [{"id": "h1"}]}

        assert _detect_and_handle_pivot(state, "Bali") is True

        assert state.trip_plan.itinerary_blocks == []
        assert state.trip_plan.constraints == []
        assert state.tiles == {}
        assert state.metadata["strategy_sections"] == []
        assert state.metadata["pivot_detected"] == {"from": "Bali", "to": "Tokyo"}

    def test_no_pivot_same_destination(self) -> None:
        state = _make_state(destination="Bali")
        assert _detect_and_handle_pivot(state, "Bali") is False

    def test_no_pivot_case_insensitive(self) -> None:
        state = _make_state(destination="bali")
        assert _detect_and_handle_pivot(state, "BALI") is False

    def test_no_pivot_initial_setup(self) -> None:
        state = _make_state(destination="Bali")
        assert _detect_and_handle_pivot(state, None) is False

    def test_no_pivot_no_new_destination(self) -> None:
        state = _make_state(destination=None)
        assert _detect_and_handle_pivot(state, "Bali") is False


# =============================================================================
# _has_settings_keywords
# =============================================================================


class TestHasSettingsKeywords:
    """Settings keyword detection gates the settings LLM extraction call."""

    @pytest.mark.parametrize(
        "text",
        [
            "I want direct flight only",
            "business class please",
            "5 star hotel",
            "luxury hotel",
            "nonstop flight",
        ],
    )
    def test_detects_settings_keywords(self, text: str) -> None:
        assert _has_settings_keywords(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "I want to go to Bali",
            "plan a trip for 2 adults",
            "what's the weather like",
        ],
    )
    def test_rejects_non_settings(self, text: str) -> None:
        assert _has_settings_keywords(text) is False


# =============================================================================
# _resolve_flexible_dates
# =============================================================================


class TestResolveFlexibleDates:
    """Flexible date resolution converts 'whenever' into concrete dates."""

    def test_resolves_flexible(self) -> None:
        plan = TripPlan(destination="Bali", adults=2)
        metadata: dict = {}
        result = _resolve_flexible_dates(plan, "I'm flexible on dates", metadata)
        assert result.start_date is not None
        assert result.end_date is not None
        assert metadata.get("flexible_date_resolved") is True

    def test_resolves_whenever(self) -> None:
        plan = TripPlan(destination="Bali", adults=2)
        metadata: dict = {}
        result = _resolve_flexible_dates(plan, "whenever works", metadata)
        assert result.start_date is not None

    def test_skips_if_dates_already_set(self) -> None:
        plan = TripPlan(destination="Bali", adults=2, start_date="2026-06-01")
        metadata: dict = {}
        result = _resolve_flexible_dates(plan, "I'm flexible", metadata)
        assert result.start_date == "2026-06-01"
        assert "flexible_date_resolved" not in metadata

    def test_skips_non_flexible_text(self) -> None:
        plan = TripPlan(destination="Bali", adults=2)
        metadata: dict = {}
        result = _resolve_flexible_dates(plan, "June 15 to June 22", metadata)
        assert result.start_date is None


# =============================================================================
# _auto_toggle_flights
# =============================================================================


class TestAutoToggleFlights:
    """Flight auto-toggle based on origin presence."""

    def test_enables_flights_when_origin_set(self) -> None:
        plan = TripPlan(destination="Bali", origin="London", adults=2)
        metadata: dict = {}
        _auto_toggle_flights(plan, None, {}, metadata)
        assert metadata["auto_toggle_flights"]["action"] == "enabled"
        assert metadata["extracted_settings"]["flights_toggle"] == "suggested"

    def test_disables_flights_when_origin_removed(self) -> None:
        plan = TripPlan(destination="Bali", adults=2)
        metadata: dict = {}
        _auto_toggle_flights(plan, "London", {}, metadata)
        assert metadata["auto_toggle_flights"]["action"] == "disabled"
        assert metadata["extracted_settings"]["flights_toggle"] == "off"

    def test_no_change_when_origin_unchanged(self) -> None:
        plan = TripPlan(destination="Bali", origin="London", adults=2)
        metadata: dict = {}
        _auto_toggle_flights(plan, "London", {}, metadata)
        assert "auto_toggle_flights" not in metadata

    def test_explicit_user_preference_wins(self) -> None:
        plan = TripPlan(destination="Bali", origin="London", adults=2)
        metadata: dict = {}
        _auto_toggle_flights(plan, None, {"flights_toggle": "off"}, metadata)
        assert "auto_toggle_flights" not in metadata


# =============================================================================
# TripArchitect.determine_mode
# =============================================================================


class TestDetermineMode:
    """Mode determination routes the architect to the correct response path."""

    def test_pre_core_without_destination(self) -> None:
        state = _make_state()
        architect = TripArchitect()
        assert architect.determine_mode(state) == "pre_core"

    def test_missing_fields_with_destination_no_dates(self) -> None:
        state = _make_state(destination="Bali")
        architect = TripArchitect()
        mode = architect.determine_mode(state)
        # Without dates, should be missing_fields or pre_core depending on readiness
        assert mode in ("missing_fields", "pre_core")

    def test_planning_with_full_plan(self) -> None:
        state = _make_state(
            destination="Bali",
            origin="London",
            start_date="2026-06-01",
            end_date="2026-06-08",
        )
        architect = TripArchitect()
        assert architect.determine_mode(state) == "planning"
