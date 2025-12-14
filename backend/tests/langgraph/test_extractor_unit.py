"""Unit tests for the extractor function and regex patterns."""

# ruff: noqa: E402

import os
import sys
from pathlib import Path

# Suppress debug output before importing plan_graph
os.environ["PLAN_GRAPH_DEBUG"] = "0"

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest

from app.plan_graph import (
    _ACCESSIBILITY_PATTERN,
    _BUDGET_CODE_PATTERN,
    _BUDGET_SYMBOL_PATTERN,
    _DATE_NEXT_WEEK_PATTERN,
    _DATE_TODAY_PATTERN,
    _DATE_TOMORROW_PATTERN,
    _FLIGHT_BUSINESS_PATTERN,
    _FLIGHT_DIRECT_PATTERN,
    _HOTEL_STARS_PATTERN,
    _ORIGIN_DEST_BARE_TO_PATTERN,
    _ORIGIN_DEST_FROM_TO_PATTERN,
    _ORIGIN_DEST_TO_FROM_PATTERN,
    _STRATEGY_DIVING_PATTERN,
    _STRATEGY_HIKING_PATTERN,
    _TRANSPORT_CAR_PATTERN,
    _TRAVELER_ADULTS_KIDS_PATTERN,
    _TRAVELER_COUPLE_PATTERN,
    _TRAVELER_FAMILY_PATTERN,
    _TRAVELER_SOLO_PATTERN,
    GraphState,
    TripInputs,
    extractor,
)


class TestBudgetPatterns:
    """Tests for budget extraction patterns."""

    @pytest.mark.parametrize(
        "text,expected_symbol,expected_amount",
        [
            ("$1000", "$", "1000"),
            ("$1,000", "$", "1,000"),
            ("€500", "€", "500"),
            ("£2500", "£", "2500"),
            ("¥50000", "¥", "50000"),
            ("$ 1500", "$", "1500"),
            ("$5,000.50", "$", "5,000.50"),
        ],
    )
    def test_budget_symbol_pattern(self, text, expected_symbol, expected_amount):
        """Symbol-before-amount pattern should extract currency and amount."""
        match = _BUDGET_SYMBOL_PATTERN.search(text)
        assert match is not None
        assert match.group("cur") == expected_symbol
        assert match.group("amt") == expected_amount

    @pytest.mark.parametrize(
        "text,expected_amount,expected_code",
        [
            ("1000 USD", "1000", "USD"),
            ("500 EUR", "500", "EUR"),
            ("2500 GBP", "2500", "GBP"),
            ("1500 CAD", "1500", "CAD"),
            ("3000 AUD", "3000", "AUD"),
            ("50000 JPY", "50000", "JPY"),
            ("1,000 usd", "1,000", "usd"),
        ],
    )
    def test_budget_code_pattern(self, text, expected_amount, expected_code):
        """Amount-before-code pattern should extract amount and currency code."""
        match = _BUDGET_CODE_PATTERN.search(text)
        assert match is not None
        assert match.group("amt") == expected_amount
        assert match.group("cur").upper() == expected_code.upper()

    def test_budget_no_match_invalid(self):
        """Invalid budget formats should not match."""
        invalid_inputs = [
            "budget around thousand",
            "no money",
            "free",
            "$$",
            "USD",
        ]
        for text in invalid_inputs:
            assert _BUDGET_SYMBOL_PATTERN.search(text) is None
            assert _BUDGET_CODE_PATTERN.search(text) is None


class TestOriginDestinationPatterns:
    """Tests for origin/destination extraction patterns."""

    @pytest.mark.parametrize(
        "text,expected_origin,expected_dest",
        [
            ("from London to Paris", "London", "Paris"),
            ("from New York to Tokyo", "New York", "Tokyo"),
            ("from the UK to the Alps", "UK", "Alps"),
            ("from São Paulo to Rio", "São Paulo", "Rio"),
            ("from St. Petersburg to Moscow", "St. Petersburg", "Moscow"),
        ],
    )
    def test_from_to_pattern(self, text, expected_origin, expected_dest):
        """'from X to Y' pattern should extract origin and destination."""
        match = _ORIGIN_DEST_FROM_TO_PATTERN.search(text)
        assert match is not None
        assert match.group("o").strip() == expected_origin
        assert match.group("d").strip() == expected_dest

    @pytest.mark.parametrize(
        "text,expected_origin,expected_dest",
        [
            ("to Paris from London", "London", "Paris"),
            ("to Tokyo from New York", "New York", "Tokyo"),
        ],
    )
    def test_to_from_pattern(self, text, expected_origin, expected_dest):
        """'to Y from X' pattern should extract origin and destination."""
        match = _ORIGIN_DEST_TO_FROM_PATTERN.search(text)
        assert match is not None
        assert match.group("o").strip() == expected_origin
        assert match.group("d").strip() == expected_dest

    @pytest.mark.parametrize(
        "text,expected_origin,expected_dest",
        [
            ("London to Paris", "London", "Paris"),
            ("NYC to LA", "NYC", "LA"),
        ],
    )
    def test_bare_to_pattern(self, text, expected_origin, expected_dest):
        """'X to Y' pattern (no 'from') should extract origin and destination."""
        match = _ORIGIN_DEST_BARE_TO_PATTERN.search(text)
        assert match is not None
        assert match.group("o").strip() == expected_origin
        assert match.group("d").strip() == expected_dest


class TestTravelerPatterns:
    """Tests for traveler extraction patterns."""

    @pytest.mark.parametrize(
        "text",
        [
            "solo trip",
            "just me",
            "traveling alone",
            "by myself",
        ],
    )
    def test_solo_pattern(self, text):
        """Solo traveler patterns should match."""
        assert _TRAVELER_SOLO_PATTERN.search(text) is not None

    @pytest.mark.parametrize(
        "text",
        [
            "couple trip",
            "me and my partner",
            "me and my wife",
            "me and my husband",
        ],
    )
    def test_couple_pattern(self, text):
        """Couple patterns should match."""
        assert _TRAVELER_COUPLE_PATTERN.search(text) is not None

    @pytest.mark.parametrize(
        "text,expected_count",
        [
            ("family of 4", "4"),
            ("family of 5", "5"),
            ("family of 3", "3"),
        ],
    )
    def test_family_pattern(self, text, expected_count):
        """'family of N' should extract the count."""
        match = _TRAVELER_FAMILY_PATTERN.search(text)
        assert match is not None
        assert match.group(1) == expected_count

    @pytest.mark.parametrize(
        "text,expected_adults,expected_kids",
        [
            ("2 adults and 2 kids", "2", "2"),
            ("3 adults, 1 kid", "3", "1"),
            ("4 adults and 3 children", "4", "3"),
        ],
    )
    def test_adults_kids_pattern(self, text, expected_adults, expected_kids):
        """Adults + kids pattern should extract both counts."""
        match = _TRAVELER_ADULTS_KIDS_PATTERN.search(text)
        assert match is not None
        assert match.group(1) == expected_adults
        assert match.group(2) == expected_kids


class TestDatePatterns:
    """Tests for date extraction patterns."""

    @pytest.mark.parametrize("text", ["today", "tonight", "now"])
    def test_today_pattern(self, text):
        """Today/tonight/now patterns should match."""
        assert _DATE_TODAY_PATTERN.search(text) is not None

    def test_tomorrow_pattern(self):
        """Tomorrow pattern should match."""
        assert _DATE_TOMORROW_PATTERN.search("tomorrow") is not None

    def test_next_week_pattern(self):
        """Next week pattern should match."""
        assert _DATE_NEXT_WEEK_PATTERN.search("next week") is not None


class TestAccessibilityPattern:
    """Tests for accessibility keyword extraction."""

    @pytest.mark.parametrize(
        "text",
        [
            "wheelchair accessible",
            "need accessibility options",
            "disabled access",
            "mobility assistance",
            "requires assistance",
        ],
    )
    def test_accessibility_keywords(self, text):
        """Accessibility keywords should match."""
        assert _ACCESSIBILITY_PATTERN.search(text) is not None


class TestFlightSettingsPatterns:
    """Tests for flight settings extraction patterns."""

    @pytest.mark.parametrize("text", ["nonstop flight", "non-stop", "direct flight"])
    def test_direct_flight_pattern(self, text):
        """Direct/nonstop patterns should match."""
        assert _FLIGHT_DIRECT_PATTERN.search(text) is not None

    @pytest.mark.parametrize("text", ["business class", "fly business"])
    def test_business_class_pattern(self, text):
        """Business class patterns should match."""
        assert _FLIGHT_BUSINESS_PATTERN.search(text) is not None


class TestHotelSettingsPatterns:
    """Tests for hotel settings extraction patterns."""

    @pytest.mark.parametrize(
        "text,expected_stars",
        [
            ("5 star hotel", "5"),
            ("4-star resort", "4"),
            ("3 star", "3"),
        ],
    )
    def test_star_rating_pattern(self, text, expected_stars):
        """Star rating patterns should extract the number."""
        match = _HOTEL_STARS_PATTERN.search(text)
        assert match is not None
        assert match.group(1) == expected_stars


class TestTransportSettingsPatterns:
    """Tests for transport settings extraction patterns."""

    @pytest.mark.parametrize(
        "text",
        [
            "rent a car",
            "car rental",
            "driving",
            "drive there",
        ],
    )
    def test_car_pattern(self, text):
        """Car/driving patterns should match."""
        assert _TRANSPORT_CAR_PATTERN.search(text) is not None


class TestStrategyPatterns:
    """Tests for strategy detection patterns."""

    @pytest.mark.parametrize(
        "text",
        [
            "hiking trip",
            "mountain trek",
            "alpine adventure",
            "trail exploration",
        ],
    )
    def test_hiking_pattern(self, text):
        """Hiking/trekking patterns should match."""
        assert _STRATEGY_HIKING_PATTERN.search(text) is not None

    @pytest.mark.parametrize(
        "text",
        [
            "diving trip",
            "scuba adventure",
            "snorkeling",
        ],
    )
    def test_diving_pattern(self, text):
        """Diving/scuba patterns should match."""
        assert _STRATEGY_DIVING_PATTERN.search(text) is not None


class TestExtractorIntegration:
    """Integration tests for the full extractor function."""

    def test_extracts_budget_from_user_text(self):
        """Extractor should extract budget from user input."""
        state = GraphState(
            user_text="I have a budget of $5000 for this trip",
            trip_inputs=TripInputs(),
            parsed_inputs={},
            chat_history=[],
            metadata={},
            thread_id="test",
        )
        state = extractor(state)
        assert "budget_delta" in state.parsed_inputs
        assert state.parsed_inputs["budget_delta"]["budget"] == 5000.0
        assert state.parsed_inputs["budget_delta"]["currency"] == "USD"

    def test_extracts_origin_destination(self):
        """Extractor should extract origin and destination."""
        state = GraphState(
            user_text="I want to fly from London to Tokyo",
            trip_inputs=TripInputs(),
            parsed_inputs={},
            chat_history=[],
            metadata={},
            thread_id="test",
        )
        state = extractor(state)
        assert state.parsed_inputs.get("origin_delta") == "London"
        assert "Tokyo" in state.parsed_inputs.get("destinations_delta", [])

    def test_extracts_travelers(self):
        """Extractor should extract traveler count."""
        state = GraphState(
            user_text="Trip for family of 5",
            trip_inputs=TripInputs(),
            parsed_inputs={},
            chat_history=[],
            metadata={},
            thread_id="test",
        )
        state = extractor(state)
        # Family of 5 should set adults or be extracted
        assert (
            state.parsed_inputs.get("adults_delta") == 5
            or "adults_delta" in state.parsed_inputs
            or "children_delta" in state.parsed_inputs
        )

    def test_extracts_accessibility_flag(self):
        """Extractor should set accessibility flag."""
        state = GraphState(
            user_text="Need wheelchair accessible hotels in Paris",
            trip_inputs=TripInputs(),
            parsed_inputs={},
            chat_history=[],
            metadata={},
            thread_id="test",
        )
        state = extractor(state)
        assert state.parsed_inputs.get("requires_assistance_delta") is True

    def test_extracts_flight_settings(self):
        """Extractor should extract flight preferences."""
        state = GraphState(
            user_text="Looking for direct business class flights",
            trip_inputs=TripInputs(),
            parsed_inputs={},
            chat_history=[],
            metadata={},
            thread_id="test",
        )
        state = extractor(state)
        flight_settings = state.parsed_inputs.get("flight_settings_delta", {})
        assert (
            flight_settings.get("direct_only") is True
            or flight_settings.get("cabin_class") == "business"
        )

    def test_extracts_strategy_hint(self):
        """Extractor should detect strategy topics."""
        state = GraphState(
            user_text="Planning a hiking trip to the Alps",
            trip_inputs=TripInputs(),
            parsed_inputs={},
            chat_history=[],
            metadata={},
            thread_id="test",
        )
        state = extractor(state)
        assert state.parsed_inputs.get("strategy_hint") == "hiking"

    def test_extracts_multiple_destinations(self):
        """Extractor should handle multiple destinations."""
        state = GraphState(
            user_text="Trip from Rome to Paris and London",
            trip_inputs=TripInputs(),
            parsed_inputs={},
            chat_history=[],
            metadata={},
            thread_id="test",
        )
        state = extractor(state)
        destinations = state.parsed_inputs.get("destinations_delta", [])
        assert len(destinations) >= 1  # At least one destination extracted

    def test_empty_user_text(self):
        """Extractor should handle empty user text gracefully."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(),
            parsed_inputs={},
            chat_history=[],
            metadata={},
            thread_id="test",
        )
        state = extractor(state)
        # Should not crash, state should be valid
        assert state is not None
        assert isinstance(state.parsed_inputs, dict)

    def test_unicode_in_destinations(self):
        """Extractor should handle unicode characters."""
        state = GraphState(
            user_text="Travel from São Paulo to Zürich",
            trip_inputs=TripInputs(),
            parsed_inputs={},
            chat_history=[],
            metadata={},
            thread_id="test",
        )
        state = extractor(state)
        origin = state.parsed_inputs.get("origin_delta", "")
        destinations = state.parsed_inputs.get("destinations_delta", [])
        # Should extract at least one of these
        assert origin or destinations

    def test_sets_extraction_confidence(self):
        """Extractor should set extraction confidence in metadata."""
        state = GraphState(
            user_text="from London to Paris next week",
            trip_inputs=TripInputs(),
            parsed_inputs={},
            chat_history=[],
            metadata={},
            thread_id="test",
        )
        state = extractor(state)
        conf = state.metadata.get("extraction_confidence", {})
        assert "overall" in conf
        assert "level" in conf
        assert conf["level"] in ("high", "medium", "low")
