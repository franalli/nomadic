"""
Tests for IATA airport code resolver in app.planner.services.iata_resolver.

Covers:
- Cached code reuse from state (no LLM call)
- LLM-backed resolution when codes are missing
- Graceful handling of LLM failures, None parsed output
- State mutation (codes written back to trip_plan)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.planner.services.iata_resolver import (
    IataResponse,
    clear_iata_cache,
    resolve_iata_codes,
)
from app.planner.state import GraphState, TripPlan


def _make_state(
    origin_iata: str | None = None,
    destination_iata: str | None = None,
) -> GraphState:
    """Build a minimal GraphState with optional pre-set IATA codes."""
    tp = TripPlan(destination="Bali")
    tp.origin_iata = origin_iata
    tp.destination_iata = destination_iata
    return GraphState(trip_plan=tp)


def _mock_llm_structured(codes: dict) -> MagicMock:
    """Return a mock LLM whose with_structured_output().ainvoke() returns parsed IataResponse."""
    parsed = IataResponse(**codes)
    structured_result = {"parsed": parsed, "raw": MagicMock()}

    mock_structured_llm = AsyncMock()
    mock_structured_llm.ainvoke = AsyncMock(return_value=structured_result)

    mock_llm = MagicMock()
    mock_llm.with_structured_output = MagicMock(return_value=mock_structured_llm)
    return mock_llm


@pytest.fixture(autouse=True)
def _clear_shared_cache_between_tests():
    """Keep shared L1 cache deterministic across tests and avoid real DB hits."""
    clear_iata_cache()
    with patch(
        "app.planner.services.iata_resolver._get_async_session_factory",
        side_effect=Exception("db unavailable in unit tests"),
    ):
        yield
    clear_iata_cache()


class TestCachedCodeReuse:
    """When both IATA codes are already on state, no LLM call should happen."""

    @pytest.mark.asyncio
    async def test_returns_cached_codes(self):
        state = _make_state(origin_iata="SFO", destination_iata="DPS")
        with patch("app.planner.services.iata_resolver.get_llm_by_model") as mock_factory:
            origin, dest = await resolve_iata_codes("San Francisco", "Bali", state)
            mock_factory.assert_not_called()
        assert origin == "SFO"
        assert dest == "DPS"

    @pytest.mark.asyncio
    async def test_state_unchanged_when_cached(self):
        state = _make_state(origin_iata="JFK", destination_iata="DXB")
        with patch("app.planner.services.iata_resolver.get_llm_by_model"):
            await resolve_iata_codes("New York", "Dubai", state)
        assert state.trip_plan.origin_iata == "JFK"
        assert state.trip_plan.destination_iata == "DXB"


class TestLLMResolution:
    """LLM is called when one or both codes are missing."""

    @pytest.mark.asyncio
    async def test_resolves_both_codes(self):
        state = _make_state()
        mock_llm = _mock_llm_structured({"origin": "SFO", "destination": "DPS"})
        with patch(
            "app.planner.services.iata_resolver.get_llm_by_model",
            return_value=mock_llm,
        ):
            origin, dest = await resolve_iata_codes("San Francisco", "Bali", state)
        assert origin == "SFO"
        assert dest == "DPS"

    @pytest.mark.asyncio
    async def test_resolves_only_missing_origin(self):
        state = _make_state(destination_iata="DPS")
        mock_llm = _mock_llm_structured({"origin": "JFK"})
        with patch(
            "app.planner.services.iata_resolver.get_llm_by_model",
            return_value=mock_llm,
        ):
            origin, dest = await resolve_iata_codes("New York", "Bali", state)
        assert origin == "JFK"
        assert dest == "DPS"

    @pytest.mark.asyncio
    async def test_resolves_only_missing_destination(self):
        state = _make_state(origin_iata="SFO")
        mock_llm = _mock_llm_structured({"destination": "NRT"})
        with patch(
            "app.planner.services.iata_resolver.get_llm_by_model",
            return_value=mock_llm,
        ):
            origin, dest = await resolve_iata_codes("San Francisco", "Tokyo", state)
        assert origin == "SFO"
        assert dest == "NRT"

    @pytest.mark.asyncio
    async def test_sets_codes_on_state(self):
        state = _make_state()
        mock_llm = _mock_llm_structured({"origin": "LAX", "destination": "CDG"})
        with patch(
            "app.planner.services.iata_resolver.get_llm_by_model",
            return_value=mock_llm,
        ):
            await resolve_iata_codes("Los Angeles", "Paris", state)
        assert state.trip_plan.origin_iata == "LAX"
        assert state.trip_plan.destination_iata == "CDG"


class TestErrorHandling:
    """Graceful degradation when LLM fails or returns garbage."""

    @pytest.mark.asyncio
    async def test_llm_exception_returns_empty_strings(self):
        state = _make_state()
        mock_structured_llm = AsyncMock()
        mock_structured_llm.ainvoke = AsyncMock(side_effect=Exception("API timeout"))
        mock_llm = MagicMock()
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured_llm)
        with patch(
            "app.planner.services.iata_resolver.get_llm_by_model",
            return_value=mock_llm,
        ):
            origin, dest = await resolve_iata_codes("San Francisco", "Bali", state)
        assert origin == ""
        assert dest == ""

    @pytest.mark.asyncio
    async def test_parsed_none_returns_empty_strings(self):
        """When structured output returns None for parsed, return empty strings."""
        state = _make_state()
        structured_result = {"parsed": None, "raw": MagicMock()}
        mock_structured_llm = AsyncMock()
        mock_structured_llm.ainvoke = AsyncMock(return_value=structured_result)
        mock_llm = MagicMock()
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured_llm)
        with patch(
            "app.planner.services.iata_resolver.get_llm_by_model",
            return_value=mock_llm,
        ):
            origin, dest = await resolve_iata_codes("San Francisco", "Bali", state)
        assert origin == ""
        assert dest == ""

    @pytest.mark.asyncio
    async def test_no_llm_call_when_both_cities_empty(self):
        """If origin and destination are empty strings, skip LLM."""
        state = _make_state()
        with patch("app.planner.services.iata_resolver.get_llm_by_model") as mock_factory:
            origin, dest = await resolve_iata_codes("", "", state)
            mock_factory.assert_not_called()
        assert origin == ""
        assert dest == ""


class TestSharedCacheReuse:
    """IATA results should be reusable across independent GraphState instances."""

    @pytest.mark.asyncio
    async def test_shared_l1_cache_reuses_codes_across_states(self):
        first_state = _make_state()
        second_state = _make_state()
        mock_llm = _mock_llm_structured({"origin": "SFO", "destination": "DPS"})

        with patch(
            "app.planner.services.iata_resolver.get_llm_by_model",
            return_value=mock_llm,
        ) as llm_factory:
            first_origin, first_dest = await resolve_iata_codes(
                "San Francisco", "Bali", first_state
            )
            assert llm_factory.call_count == 1

        with patch("app.planner.services.iata_resolver.get_llm_by_model") as llm_factory:
            second_origin, second_dest = await resolve_iata_codes(
                "San Francisco",
                "Bali",
                second_state,
            )
            llm_factory.assert_not_called()

        assert first_origin == "SFO"
        assert first_dest == "DPS"
        assert second_origin == "SFO"
        assert second_dest == "DPS"
        assert second_state.trip_plan.origin_iata == "SFO"
        assert second_state.trip_plan.destination_iata == "DPS"

    @pytest.mark.asyncio
    async def test_ambiguous_city_cache_scoped_by_route_context(self):
        """Same city text with different route context should not reuse stale origin code."""
        first_state = _make_state()
        second_state = _make_state()

        first_llm = _mock_llm_structured({"origin": "SJC", "destination": "LHR"})
        second_llm = _mock_llm_structured({"origin": "SJO", "destination": "OSL"})

        with patch(
            "app.planner.services.iata_resolver.get_llm_by_model",
            return_value=first_llm,
        ) as first_factory:
            first_origin, first_dest = await resolve_iata_codes("San Jose", "London", first_state)
            assert first_factory.call_count == 1

        with patch(
            "app.planner.services.iata_resolver.get_llm_by_model",
            return_value=second_llm,
        ) as second_factory:
            second_origin, second_dest = await resolve_iata_codes("San Jose", "Oslo", second_state)
            assert second_factory.call_count == 1

        assert first_origin == "SJC"
        assert first_dest == "LHR"
        assert second_origin == "SJO"
        assert second_dest == "OSL"
        assert second_state.trip_plan.origin_iata == "SJO"
