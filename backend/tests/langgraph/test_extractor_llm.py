"""
Integration tests for LLM-based extraction.

These tests verify that the LLM extractor correctly extracts trip inputs
from natural language user messages. Tests use mocked LLM responses to
ensure deterministic behavior.

NOTE: These tests patch `_try_initial_message_extraction` to return None,
forcing the LLM code path. This is because the current architecture uses
zero-LLM extraction for simple inputs that match known patterns, which
would bypass the mocked LLM and cause test failures.
"""

# ruff: noqa: E402

import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest

# Suppress debug output before importing plan_graph
os.environ["PLAN_GRAPH_DEBUG"] = "0"

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.plan_graph import (
    GraphState,
    TripInputs,
    extractor,
)


@contextmanager
def force_llm_path():
    """
    Context manager that bypasses zero-LLM initial extraction.

    The extractor uses `_try_initial_message_extraction` for simple inputs
    (e.g., "I want to go to Paris") which bypasses the LLM entirely.
    To test the LLM code path, we patch this function to return None.
    """
    with patch("app.plan_graph._try_initial_message_extraction", return_value=None):
        yield


def make_state(user_text: str, **kwargs) -> GraphState:
    """Create a GraphState with the given user text."""
    return GraphState(
        user_text=user_text,
        trip_inputs=kwargs.get("trip_inputs", TripInputs()),
        parsed_inputs=kwargs.get("parsed_inputs", {}),
        metadata=kwargs.get("metadata", {"today_iso": "2025-12-17"}),
        flags=kwargs.get("flags", {}),
    )


def mock_llm_response(response: Dict[str, Any]) -> str:
    """Create a JSON string from the response dict."""
    return json.dumps(response)


class TestExtractorDestinations:
    """Tests for destination extraction."""

    @pytest.mark.asyncio
    async def test_extracts_single_destination(self):
        """LLM extractor should extract a single destination."""
        state = make_state("I want to go to Paris")

        llm_response = mock_llm_response(
            {
                "destinations_delta": ["Paris"],
                "confidence": 0.95,
                "confidence_reasons": [],
            }
        )

        with (
            force_llm_path(),
            patch("app.plan_graph.call_llm_with_timeout", new_callable=AsyncMock) as mock_llm,
        ):
            mock_llm.return_value = llm_response
            result = await extractor(state)

        assert result.parsed_inputs.get("destinations_delta") == ["Paris"]
        conf = result.metadata.get("extraction_confidence", {})
        assert conf.get("level") == "high"
        assert conf.get("method") == "llm"

    @pytest.mark.asyncio
    async def test_extracts_multiple_destinations(self):
        """LLM extractor should extract multiple destinations."""
        state = make_state("Planning a trip to Paris, Rome, and Barcelona")

        llm_response = mock_llm_response(
            {
                "destinations_delta": ["Paris", "Rome", "Barcelona"],
                "multi_city_intent_delta": "multi_city",
                "confidence": 0.90,
                "confidence_reasons": [],
            }
        )

        with (
            force_llm_path(),
            patch("app.plan_graph.call_llm_with_timeout", new_callable=AsyncMock) as mock_llm,
        ):
            mock_llm.return_value = llm_response
            result = await extractor(state)

        assert result.parsed_inputs.get("destinations_delta") == ["Paris", "Rome", "Barcelona"]
        assert result.parsed_inputs.get("multi_city_intent_delta") == "multi_city"

    @pytest.mark.asyncio
    async def test_filters_non_destination_words(self):
        """LLM should not extract non-destination words like 'too'."""
        state = make_state("I want to visit the cinema too")

        # LLM correctly identifies there's no destination
        llm_response = mock_llm_response(
            {
                "confidence": 0.3,
                "confidence_reasons": ["no_clear_destination"],
            }
        )

        with (
            force_llm_path(),
            patch("app.plan_graph.call_llm_with_timeout", new_callable=AsyncMock) as mock_llm,
        ):
            mock_llm.return_value = llm_response
            result = await extractor(state)

        # No destination should be extracted
        assert not result.parsed_inputs.get("destinations_delta")


class TestExtractorOrigin:
    """Tests for origin extraction."""

    @pytest.mark.asyncio
    async def test_extracts_origin_from_pattern(self):
        """LLM extractor should extract origin from 'from X to Y' pattern."""
        state = make_state("Flying from London to Tokyo next week")

        llm_response = mock_llm_response(
            {
                "origin_delta": "London",
                "destinations_delta": ["Tokyo"],
                "start_date_hint": "next week",
                "confidence": 0.95,
                "confidence_reasons": [],
            }
        )

        with (
            force_llm_path(),
            patch("app.plan_graph.call_llm_with_timeout", new_callable=AsyncMock) as mock_llm,
        ):
            mock_llm.return_value = llm_response
            result = await extractor(state)

        assert result.parsed_inputs.get("origin_delta") == "London"
        assert result.parsed_inputs.get("destinations_delta") == ["Tokyo"]


class TestExtractorDates:
    """Tests for date extraction."""

    @pytest.mark.asyncio
    async def test_extracts_relative_dates(self):
        """LLM extractor should extract relative dates."""
        state = make_state("Going to Bali next week for 10 days")

        llm_response = mock_llm_response(
            {
                "destinations_delta": ["Bali"],
                "start_date_hint": "next week",
                "duration_days": 10,
                "confidence": 0.90,
                "confidence_reasons": [],
            }
        )

        with (
            force_llm_path(),
            patch("app.plan_graph.call_llm_with_timeout", new_callable=AsyncMock) as mock_llm,
        ):
            mock_llm.return_value = llm_response
            result = await extractor(state)

        assert result.parsed_inputs.get("start_date_hint") == "next week"
        assert result.parsed_inputs.get("duration_days") == 10

    @pytest.mark.asyncio
    async def test_extracts_specific_dates(self):
        """LLM extractor should extract specific dates."""
        state = make_state("Trip to Paris from December 25 to January 2")

        llm_response = mock_llm_response(
            {
                "destinations_delta": ["Paris"],
                "start_date_hint": "December 25",
                "end_date_hint": "January 2",
                "confidence": 0.95,
                "confidence_reasons": [],
            }
        )

        with (
            force_llm_path(),
            patch("app.plan_graph.call_llm_with_timeout", new_callable=AsyncMock) as mock_llm,
        ):
            mock_llm.return_value = llm_response
            result = await extractor(state)

        assert result.parsed_inputs.get("start_date_hint") == "December 25"
        assert result.parsed_inputs.get("end_date_hint") == "January 2"


class TestExtractorTravelers:
    """Tests for traveler extraction."""

    @pytest.mark.asyncio
    async def test_extracts_solo_traveler(self):
        """LLM extractor should recognize solo travel."""
        state = make_state("Solo trip to Iceland")

        llm_response = mock_llm_response(
            {
                "destinations_delta": ["Iceland"],
                "adults_delta": 1,
                "confidence": 0.90,
                "confidence_reasons": [],
            }
        )

        with (
            force_llm_path(),
            patch("app.plan_graph.call_llm_with_timeout", new_callable=AsyncMock) as mock_llm,
        ):
            mock_llm.return_value = llm_response
            result = await extractor(state)

        assert result.parsed_inputs.get("adults_delta") == 1

    @pytest.mark.asyncio
    async def test_extracts_family_travelers(self):
        """LLM extractor should recognize family composition."""
        state = make_state("Family trip with 2 adults and 3 kids to Disney World")

        llm_response = mock_llm_response(
            {
                "destinations_delta": ["Disney World"],
                "adults_delta": 2,
                "children_delta": 3,
                "confidence": 0.95,
                "confidence_reasons": [],
            }
        )

        with (
            force_llm_path(),
            patch("app.plan_graph.call_llm_with_timeout", new_callable=AsyncMock) as mock_llm,
        ):
            mock_llm.return_value = llm_response
            result = await extractor(state)

        assert result.parsed_inputs.get("adults_delta") == 2
        assert result.parsed_inputs.get("children_delta") == 3


class TestExtractorBudget:
    """Tests for budget extraction."""

    @pytest.mark.asyncio
    async def test_extracts_budget_with_currency(self):
        """LLM extractor should extract budget with currency."""
        state = make_state("Trip to Japan with a budget of $5000")

        llm_response = mock_llm_response(
            {
                "destinations_delta": ["Japan"],
                "budget_delta": {"budget": 5000, "currency": "USD"},
                "confidence": 0.95,
                "confidence_reasons": [],
            }
        )

        with (
            force_llm_path(),
            patch("app.plan_graph.call_llm_with_timeout", new_callable=AsyncMock) as mock_llm,
        ):
            mock_llm.return_value = llm_response
            result = await extractor(state)

        budget = result.parsed_inputs.get("budget_delta", {})
        assert budget.get("budget") == 5000
        assert budget.get("currency") == "USD"


class TestExtractorActivities:
    """Tests for activity extraction."""

    @pytest.mark.asyncio
    async def test_extracts_hiking_activity(self):
        """LLM should extract hiking activity when user mentions it."""
        state = make_state("I wanna go hiking in Patagonia")

        llm_response = mock_llm_response(
            {
                "destinations_delta": ["Patagonia"],
                "activity_categories_delta": ["🥾 hiking"],
                "strategy_hint": "hiking",
                "confidence": 0.95,
                "confidence_reasons": [],
            }
        )

        with (
            force_llm_path(),
            patch("app.plan_graph.call_llm_with_timeout", new_callable=AsyncMock) as mock_llm,
        ):
            mock_llm.return_value = llm_response
            result = await extractor(state)

        assert result.parsed_inputs.get("inferred_activity_categories") == ["🥾 hiking"]
        assert result.parsed_inputs.get("strategy_hint") == "hiking"

    @pytest.mark.asyncio
    async def test_extracts_diving_activity(self):
        """LLM should extract diving activity."""
        state = make_state("Looking for a diving trip to the Maldives")

        llm_response = mock_llm_response(
            {
                "destinations_delta": ["Maldives"],
                "activity_categories_delta": ["🤿 diving"],
                "strategy_hint": "diving",
                "confidence": 0.95,
                "confidence_reasons": [],
            }
        )

        with (
            force_llm_path(),
            patch("app.plan_graph.call_llm_with_timeout", new_callable=AsyncMock) as mock_llm,
        ):
            mock_llm.return_value = llm_response
            result = await extractor(state)

        assert "🤿 diving" in result.parsed_inputs.get("inferred_activity_categories", [])


class TestExtractorSettings:
    """Tests for flight/hotel/transport settings extraction."""

    @pytest.mark.asyncio
    async def test_extracts_flight_settings(self):
        """LLM should extract flight preferences."""
        state = make_state("Direct business class flights to Singapore")

        llm_response = mock_llm_response(
            {
                "destinations_delta": ["Singapore"],
                "category_activation": {"flights": True},
                "flight_settings_delta": {
                    "direct_only": True,
                    "cabin_class": "business",
                },
                "confidence": 0.95,
                "confidence_reasons": [],
            }
        )

        with (
            force_llm_path(),
            patch("app.plan_graph.call_llm_with_timeout", new_callable=AsyncMock) as mock_llm,
        ):
            mock_llm.return_value = llm_response
            result = await extractor(state)

        flight_settings = result.parsed_inputs.get("flight_settings_delta", {})
        assert flight_settings.get("direct_only") is True
        assert flight_settings.get("cabin_class") == "business"

    @pytest.mark.asyncio
    async def test_extracts_hotel_settings(self):
        """LLM should extract hotel preferences."""
        state = make_state("Need a 5-star hotel with pool and spa in Dubai")

        llm_response = mock_llm_response(
            {
                "destinations_delta": ["Dubai"],
                "category_activation": {"hotels": True},
                "hotel_settings_delta": {
                    "min_stars": 5,
                    "amenities": ["pool", "spa"],
                },
                "confidence": 0.95,
                "confidence_reasons": [],
            }
        )

        with (
            force_llm_path(),
            patch("app.plan_graph.call_llm_with_timeout", new_callable=AsyncMock) as mock_llm,
        ):
            mock_llm.return_value = llm_response
            result = await extractor(state)

        hotel_settings = result.parsed_inputs.get("hotel_settings_delta", {})
        assert hotel_settings.get("min_stars") == 5
        assert "pool" in hotel_settings.get("amenities", [])


class TestExtractorShortCircuits:
    """Tests for short-circuit detection (bypasses LLM)."""

    @pytest.mark.asyncio
    async def test_greeting_short_circuit(self):
        """Greetings should short-circuit without calling LLM."""
        state = make_state("Hello!")

        with patch("app.plan_graph.call_llm_with_timeout", new_callable=AsyncMock) as mock_llm:
            result = await extractor(state)

        # LLM should NOT be called for greetings
        mock_llm.assert_not_called()
        assert result.flags.get("short_circuit") == "greeting"


class TestExtractorConfidence:
    """Tests for LLM confidence reporting."""

    @pytest.mark.asyncio
    async def test_high_confidence_extraction(self):
        """LLM reporting high confidence should result in high confidence level."""
        state = make_state("Trip from NYC to Paris on January 15")

        llm_response = mock_llm_response(
            {
                "origin_delta": "New York City",
                "destinations_delta": ["Paris"],
                "start_date_hint": "January 15",
                "confidence": 0.95,
                "confidence_reasons": [],
            }
        )

        with (
            force_llm_path(),
            patch("app.plan_graph.call_llm_with_timeout", new_callable=AsyncMock) as mock_llm,
        ):
            mock_llm.return_value = llm_response
            result = await extractor(state)

        conf = result.metadata.get("extraction_confidence", {})
        assert conf.get("overall") == 0.95
        assert conf.get("level") == "high"
        assert conf.get("method") == "llm"

    @pytest.mark.asyncio
    async def test_low_confidence_extraction(self):
        """LLM reporting low confidence should result in low confidence level."""
        state = make_state("maybe somewhere warm?")

        llm_response = mock_llm_response(
            {
                "confidence": 0.3,
                "confidence_reasons": ["vague_input", "no_specific_destination"],
            }
        )

        with (
            force_llm_path(),
            patch("app.plan_graph.call_llm_with_timeout", new_callable=AsyncMock) as mock_llm,
        ):
            mock_llm.return_value = llm_response
            result = await extractor(state)

        conf = result.metadata.get("extraction_confidence", {})
        assert conf.get("overall") == 0.3
        assert conf.get("level") == "low"
        assert "vague_input" in conf.get("low_confidence_reasons", [])


class TestExtractorTimeout:
    """Tests for LLM timeout handling."""

    @pytest.mark.asyncio
    async def test_timeout_sets_low_confidence(self):
        """LLM timeout should result in low confidence."""
        state = make_state("Trip to Tokyo")

        with (
            force_llm_path(),
            patch("app.plan_graph.call_llm_with_timeout", new_callable=AsyncMock) as mock_llm,
        ):
            mock_llm.side_effect = TimeoutError("LLM timeout")
            result = await extractor(state)

        conf = result.metadata.get("extraction_confidence", {})
        assert conf.get("level") == "low"
        assert conf.get("method") == "llm_timeout"
        assert "llm_timeout" in conf.get("low_confidence_reasons", [])


class TestExtractorEdgeCases:
    """Tests for edge cases and complex inputs."""

    @pytest.mark.asyncio
    async def test_multilingual_input(self):
        """LLM should handle non-English destination names."""
        state = make_state("Viaje a São Paulo y Río de Janeiro")

        llm_response = mock_llm_response(
            {
                "destinations_delta": ["São Paulo", "Rio de Janeiro"],
                "multi_city_intent_delta": "multi_city",
                "confidence": 0.85,
                "confidence_reasons": [],
            }
        )

        with (
            force_llm_path(),
            patch("app.plan_graph.call_llm_with_timeout", new_callable=AsyncMock) as mock_llm,
        ):
            mock_llm.return_value = llm_response
            result = await extractor(state)

        dests = result.parsed_inputs.get("destinations_delta", [])
        assert "São Paulo" in dests
        assert "Rio de Janeiro" in dests

    @pytest.mark.asyncio
    async def test_complex_trip_request(self):
        """LLM should handle complex multi-field requests."""
        state = make_state(
            "Planning a 2-week family vacation from Boston to Italy - "
            "Rome, Florence, and Venice - with 2 adults and 2 kids, "
            "budget around €8000, need direct flights and 4-star hotels with pool"
        )

        llm_response = mock_llm_response(
            {
                "origin_delta": "Boston",
                "destinations_delta": ["Rome", "Florence", "Venice"],
                "multi_city_intent_delta": "multi_city",
                "adults_delta": 2,
                "children_delta": 2,
                "duration_days": 14,
                "budget_delta": {"budget": 8000, "currency": "EUR"},
                "category_activation": {"flights": True, "hotels": True},
                "flight_settings_delta": {"direct_only": True},
                "hotel_settings_delta": {"min_stars": 4, "amenities": ["pool"]},
                "confidence": 0.92,
                "confidence_reasons": [],
            }
        )

        with (
            force_llm_path(),
            patch("app.plan_graph.call_llm_with_timeout", new_callable=AsyncMock) as mock_llm,
        ):
            mock_llm.return_value = llm_response
            result = await extractor(state)

        parsed = result.parsed_inputs
        assert parsed.get("origin_delta") == "Boston"
        assert len(parsed.get("destinations_delta", [])) == 3
        assert parsed.get("adults_delta") == 2
        assert parsed.get("children_delta") == 2
        assert parsed.get("budget_delta", {}).get("budget") == 8000
