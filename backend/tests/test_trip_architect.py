# backend/tests/test_trip_architect.py
"""
Snapshot tests for trip_architect.py — field extraction, pivot detection, settings parsing.

Covers both pure logic functions and LLM-backed extraction (mocked).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.planner.nodes.trip_architect import (
    TripArchitect,
    _auto_toggle_flights,
    _detect_and_handle_pivot,
    _extract_fields_with_llm,
    _has_settings_keywords,
    _resolve_flexible_dates,
    _update_trip_plan_from_llm,
)
from app.planner.state.graph_state import (
    ExtractedTripFields,
    GraphState,
    MissingFieldsResponse,
    TripPlan,
    create_missing_fields_response,
    get_missing_fields,
)


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


# =============================================================================
# _update_trip_plan_from_llm (mocked extraction)
# =============================================================================


class TestUpdateTripPlanFromLlm:
    """LLM-backed plan update merges extracted fields into TripPlan."""

    @pytest.mark.asyncio
    async def test_destination_extracted_updates_plan(self) -> None:
        plan = TripPlan(adults=2)
        extracted = ExtractedTripFields(destination="bali")
        token_usage = {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60}

        with patch(
            "app.planner.nodes.trip_architect._extract_fields_with_llm",
            new_callable=AsyncMock,
            return_value=(extracted, token_usage),
        ):
            updated, tokens = await _update_trip_plan_from_llm(plan, "I want to go to Bali")

        # Destination should be title-cased
        assert updated.destination == "Bali"
        assert tokens == token_usage

    @pytest.mark.asyncio
    async def test_budget_extracted_updates_plan(self) -> None:
        plan = TripPlan(destination="Tokyo", adults=2)
        extracted = ExtractedTripFields(budget=3000.0)

        with patch(
            "app.planner.nodes.trip_architect._extract_fields_with_llm",
            new_callable=AsyncMock,
            return_value=(extracted, {}),
        ):
            updated, _ = await _update_trip_plan_from_llm(plan, "budget is 3k")

        assert updated.budget == 3000.0
        # Destination unchanged
        assert updated.destination == "Tokyo"

    @pytest.mark.asyncio
    async def test_duration_days_calculates_end_date(self) -> None:
        plan = TripPlan(adults=2)
        extracted = ExtractedTripFields(
            destination="paris",
            start_date="2026-06-01",
            duration_days=5,
        )

        with patch(
            "app.planner.nodes.trip_architect._extract_fields_with_llm",
            new_callable=AsyncMock,
            return_value=(extracted, {}),
        ):
            updated, _ = await _update_trip_plan_from_llm(plan, "Paris for 5 days starting June 1")

        assert updated.destination == "Paris"
        assert updated.start_date == "2026-06-01"
        assert updated.end_date == "2026-06-06"

    @pytest.mark.asyncio
    async def test_duration_days_ignored_without_start_date(self) -> None:
        """duration_days without start_date should NOT compute end_date."""
        plan = TripPlan(adults=2)
        extracted = ExtractedTripFields(duration_days=5)

        with patch(
            "app.planner.nodes.trip_architect._extract_fields_with_llm",
            new_callable=AsyncMock,
            return_value=(extracted, {}),
        ):
            updated, _ = await _update_trip_plan_from_llm(plan, "5 days trip")

        assert updated.end_date is None

    @pytest.mark.asyncio
    async def test_explicit_end_date_wins_over_duration(self) -> None:
        """When both end_date and duration_days are extracted, end_date takes precedence."""
        plan = TripPlan(adults=2)
        extracted = ExtractedTripFields(
            start_date="2026-06-01",
            end_date="2026-06-10",
            duration_days=5,
        )

        with patch(
            "app.planner.nodes.trip_architect._extract_fields_with_llm",
            new_callable=AsyncMock,
            return_value=(extracted, {}),
        ):
            updated, _ = await _update_trip_plan_from_llm(plan, "June 1 to June 10")

        # Explicit end_date wins; duration_days branch not reached
        assert updated.end_date == "2026-06-10"

    @pytest.mark.asyncio
    async def test_null_fields_leave_plan_unchanged(self) -> None:
        plan = TripPlan(
            destination="Tokyo",
            origin="London",
            start_date="2026-06-01",
            end_date="2026-06-08",
            adults=2,
            budget=5000.0,
        )
        # All-null extraction: nothing mentioned
        extracted = ExtractedTripFields()

        with patch(
            "app.planner.nodes.trip_architect._extract_fields_with_llm",
            new_callable=AsyncMock,
            return_value=(extracted, {}),
        ):
            updated, _ = await _update_trip_plan_from_llm(plan, "what is the weather like?")

        assert updated.destination == "Tokyo"
        assert updated.origin == "London"
        assert updated.start_date == "2026-06-01"
        assert updated.end_date == "2026-06-08"
        assert updated.budget == 5000.0

    @pytest.mark.asyncio
    async def test_token_usage_passthrough(self) -> None:
        plan = TripPlan(adults=2)
        extracted = ExtractedTripFields(destination="rome")
        token_usage = {"prompt_tokens": 120, "completion_tokens": 25, "total_tokens": 145}

        with patch(
            "app.planner.nodes.trip_architect._extract_fields_with_llm",
            new_callable=AsyncMock,
            return_value=(extracted, token_usage),
        ):
            _, tokens = await _update_trip_plan_from_llm(plan, "Rome please")

        assert tokens["prompt_tokens"] == 120
        assert tokens["completion_tokens"] == 25
        assert tokens["total_tokens"] == 145

    @pytest.mark.asyncio
    async def test_origin_title_cased(self) -> None:
        plan = TripPlan(adults=2)
        extracted = ExtractedTripFields(origin="new york")

        with patch(
            "app.planner.nodes.trip_architect._extract_fields_with_llm",
            new_callable=AsyncMock,
            return_value=(extracted, {}),
        ):
            updated, _ = await _update_trip_plan_from_llm(plan, "flying from new york")

        assert updated.origin == "New York"

    @pytest.mark.asyncio
    async def test_travelers_updated(self) -> None:
        plan = TripPlan(adults=2, children=0)
        extracted = ExtractedTripFields(adults=3, children=2)

        with patch(
            "app.planner.nodes.trip_architect._extract_fields_with_llm",
            new_callable=AsyncMock,
            return_value=(extracted, {}),
        ):
            updated, _ = await _update_trip_plan_from_llm(plan, "3 adults and 2 kids")

        assert updated.adults == 3
        assert updated.children == 2
        assert updated.travelers == 5

    @pytest.mark.asyncio
    async def test_trip_type_extracted(self) -> None:
        plan = TripPlan(destination="Bali", adults=2)
        extracted = ExtractedTripFields(trip_type="diving")

        with patch(
            "app.planner.nodes.trip_architect._extract_fields_with_llm",
            new_callable=AsyncMock,
            return_value=(extracted, {}),
        ):
            updated, _ = await _update_trip_plan_from_llm(plan, "I want a diving trip")

        assert updated.trip_type == "diving"


# =============================================================================
# get_missing_fields / create_missing_fields_response
# =============================================================================


class TestMissingFields:
    """Missing field detection and response generation."""

    def test_no_destination_in_missing(self) -> None:
        plan = TripPlan(adults=2)
        missing = get_missing_fields(plan)
        assert "destination" in missing

    def test_no_dates_in_missing(self) -> None:
        plan = TripPlan(destination="Bali", adults=2)
        missing = get_missing_fields(plan)
        assert "dates" in missing
        assert "destination" not in missing

    def test_complete_plan_no_missing(self) -> None:
        plan = TripPlan(
            destination="Bali",
            start_date="2026-06-01",
            end_date="2026-06-08",
            adults=2,
        )
        missing = get_missing_fields(plan)
        assert missing == []

    def test_missing_both_destination_and_dates(self) -> None:
        plan = TripPlan(adults=2)
        missing = get_missing_fields(plan)
        assert "destination" in missing
        assert "dates" in missing

    def test_create_response_with_missing_destination(self) -> None:
        plan = TripPlan(adults=2)
        response = create_missing_fields_response(plan)
        assert response is not None
        assert isinstance(response, MissingFieldsResponse)
        assert "destination" in response.fields
        assert response.message  # non-empty message

    def test_create_response_with_missing_dates(self) -> None:
        plan = TripPlan(destination="Bali", adults=2)
        response = create_missing_fields_response(plan)
        assert response is not None
        assert "dates" in response.fields

    def test_create_response_complete_plan_returns_none(self) -> None:
        plan = TripPlan(
            destination="Bali",
            start_date="2026-06-01",
            end_date="2026-06-08",
            adults=2,
        )
        response = create_missing_fields_response(plan)
        assert response is None

    def test_architect_generate_missing_fields_response(self) -> None:
        """TripArchitect.generate_missing_fields_response wraps the state helper."""
        state = _make_state(destination="Bali")
        architect = TripArchitect()
        result = architect.generate_missing_fields_response(state)
        assert result["type"] == "missing_fields"
        assert "dates" in result["fields"]

    def test_architect_generate_missing_fields_complete(self) -> None:
        """Complete plan returns 'Ready to plan!' fallback."""
        state = _make_state(
            destination="Bali",
            start_date="2026-06-01",
            end_date="2026-06-08",
        )
        architect = TripArchitect()
        result = architect.generate_missing_fields_response(state)
        assert result["message"] == "Ready to plan!"
        assert result["fields"] == []


# =============================================================================
# _extract_fields_with_llm (mocked LLM)
# =============================================================================


class TestExtractFieldsWithLlm:
    """LLM extraction via structured output, fully mocked."""

    @pytest.mark.asyncio
    async def test_basic_extraction(self) -> None:
        """Mock LLM returns structured fields for 'Bali for 5 days'."""
        parsed = ExtractedTripFields(destination="Bali", duration_days=5)
        mock_raw = MagicMock()
        mock_raw.response_metadata = {
            "token_usage": {"prompt_tokens": 80, "completion_tokens": 15, "total_tokens": 95}
        }

        mock_structured_llm = AsyncMock()
        mock_structured_llm.ainvoke.return_value = {"parsed": parsed, "raw": mock_raw}

        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured_llm

        with patch(
            "app.planner.nodes.trip_architect.get_llm_by_model",
            return_value=mock_llm,
        ):
            plan = TripPlan(adults=2)
            result, token_usage = await _extract_fields_with_llm("Bali for 5 days", plan)

        assert result.destination == "Bali"
        assert result.duration_days == 5
        assert token_usage["prompt_tokens"] == 80
        assert token_usage["total_tokens"] == 95

    @pytest.mark.asyncio
    async def test_token_usage_captured_from_metadata(self) -> None:
        parsed = ExtractedTripFields(destination="Tokyo")
        mock_raw = MagicMock()
        mock_raw.response_metadata = {
            "token_usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
        }

        mock_structured_llm = AsyncMock()
        mock_structured_llm.ainvoke.return_value = {"parsed": parsed, "raw": mock_raw}

        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured_llm

        with patch(
            "app.planner.nodes.trip_architect.get_llm_by_model",
            return_value=mock_llm,
        ):
            _, token_usage = await _extract_fields_with_llm("Tokyo trip", TripPlan(adults=2))

        assert token_usage["prompt_tokens"] == 100
        assert token_usage["completion_tokens"] == 20

    @pytest.mark.asyncio
    async def test_no_response_metadata_returns_empty_tokens(self) -> None:
        """If raw has no response_metadata, token_usage should be empty dict."""
        parsed = ExtractedTripFields(destination="Rome")
        mock_raw = MagicMock(spec=[])  # no response_metadata attribute

        mock_structured_llm = AsyncMock()
        mock_structured_llm.ainvoke.return_value = {"parsed": parsed, "raw": mock_raw}

        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured_llm

        with patch(
            "app.planner.nodes.trip_architect.get_llm_by_model",
            return_value=mock_llm,
        ):
            result, token_usage = await _extract_fields_with_llm("Rome", TripPlan(adults=2))

        assert result.destination == "Rome"
        assert token_usage == {}

    @pytest.mark.asyncio
    async def test_llm_error_returns_empty_fields(self) -> None:
        """If LLM raises, return empty ExtractedTripFields and empty token dict."""
        mock_structured_llm = AsyncMock()
        mock_structured_llm.ainvoke.side_effect = RuntimeError("LLM unavailable")

        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured_llm

        with patch(
            "app.planner.nodes.trip_architect.get_llm_by_model",
            return_value=mock_llm,
        ):
            result, token_usage = await _extract_fields_with_llm("Bali trip", TripPlan(adults=2))

        # Should return defaults (all None)
        assert result.destination is None
        assert result.start_date is None
        assert result.budget is None
        assert token_usage == {}
