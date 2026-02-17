"""
Tests for IATA airport code resolver in app.planner.services.iata_resolver.

Covers:
- Cached code reuse from state (no LLM call)
- LLM-backed resolution when codes are missing
- Markdown fence stripping from LLM responses
- Graceful handling of LLM failures, empty responses, invalid JSON
- State mutation (codes written back to trip_plan)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.planner.services.iata_resolver import resolve_iata_codes
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


def _mock_llm_response(content: str) -> AsyncMock:
    """Return a mock LLM whose ainvoke returns the given content string."""
    mock_llm = AsyncMock()
    mock_result = MagicMock()
    mock_result.content = content
    mock_llm.ainvoke = AsyncMock(return_value=mock_result)
    return mock_llm


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
        mock_llm = _mock_llm_response('{"origin": "SFO", "destination": "DPS"}')
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
        mock_llm = _mock_llm_response('{"origin": "JFK"}')
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
        mock_llm = _mock_llm_response('{"destination": "NRT"}')
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
        mock_llm = _mock_llm_response('{"origin": "LAX", "destination": "CDG"}')
        with patch(
            "app.planner.services.iata_resolver.get_llm_by_model",
            return_value=mock_llm,
        ):
            await resolve_iata_codes("Los Angeles", "Paris", state)
        assert state.trip_plan.origin_iata == "LAX"
        assert state.trip_plan.destination_iata == "CDG"


class TestMarkdownFenceStripping:
    """LLM sometimes wraps JSON in markdown code fences."""

    @pytest.mark.asyncio
    async def test_strips_json_fence(self):
        fenced = '```json\n{"origin": "SFO", "destination": "DPS"}\n```'
        state = _make_state()
        mock_llm = _mock_llm_response(fenced)
        with patch(
            "app.planner.services.iata_resolver.get_llm_by_model",
            return_value=mock_llm,
        ):
            origin, dest = await resolve_iata_codes("San Francisco", "Bali", state)
        assert origin == "SFO"
        assert dest == "DPS"

    @pytest.mark.asyncio
    async def test_strips_plain_fence(self):
        fenced = '```\n{"origin": "JFK", "destination": "LHR"}\n```'
        state = _make_state()
        mock_llm = _mock_llm_response(fenced)
        with patch(
            "app.planner.services.iata_resolver.get_llm_by_model",
            return_value=mock_llm,
        ):
            origin, dest = await resolve_iata_codes("New York", "London", state)
        assert origin == "JFK"
        assert dest == "LHR"


class TestErrorHandling:
    """Graceful degradation when LLM fails or returns garbage."""

    @pytest.mark.asyncio
    async def test_llm_exception_returns_empty_strings(self):
        state = _make_state()
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("API timeout"))
        with patch(
            "app.planner.services.iata_resolver.get_llm_by_model",
            return_value=mock_llm,
        ):
            origin, dest = await resolve_iata_codes("San Francisco", "Bali", state)
        assert origin == ""
        assert dest == ""

    @pytest.mark.asyncio
    async def test_empty_llm_response_returns_existing(self):
        state = _make_state()
        mock_llm = _mock_llm_response("")
        with patch(
            "app.planner.services.iata_resolver.get_llm_by_model",
            return_value=mock_llm,
        ):
            origin, dest = await resolve_iata_codes("San Francisco", "Bali", state)
        assert origin == ""
        assert dest == ""

    @pytest.mark.asyncio
    async def test_invalid_json_returns_empty_strings(self):
        state = _make_state()
        mock_llm = _mock_llm_response("not json at all")
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
