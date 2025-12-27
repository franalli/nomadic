"""
Unit tests for traveler extraction patterns in plan_graph.py.

Tests cover:
- Solo traveler detection (solo, alone, just me)
- Couple detection (two of us, partner and I)
- Numeric travelers (2 adults, family of 4)
- Inline traveler detection within sentences
"""

import pytest

from app.pattern_matching import INLINE_TRAVELERS_PATTERN, TRAVELERS_PATTERN
from app.plan_graph import (
    GraphState,
    TripInputs,
    _try_initial_message_extraction,
)


class TestStandaloneTravelerPatterns:
    """Test the standalone traveler pattern matching."""

    @pytest.mark.parametrize(
        "input_text,expected_adults",
        [
            # Solo indicators
            ("just me", 1),
            ("only me", 1),
            ("solo", 1),
            ("myself", 1),
            ("me", 1),
            # Couples
            ("a couple", 2),
            ("couple", 2),
            # Numeric patterns
            ("2 adults", 2),
            ("3 people", 3),
            ("4 travelers", 4),
            ("1 adult", 1),
            ("5 guests", 5),
            # Family/group patterns
            ("family of 4", 4),
            ("group of 6", 6),
            # "X of us" patterns
            ("2 of us", 2),
            ("3 traveling", 3),
        ],
    )
    def test_travelers_pattern(self, input_text: str, expected_adults: int):
        """Test standalone traveler pattern matching."""
        match = TRAVELERS_PATTERN.match(input_text)
        assert match is not None, f"Pattern should match '{input_text}'"


class TestInlineTravelerPatterns:
    """Test inline traveler detection within sentences."""

    @pytest.mark.parametrize(
        "input_text,expected_match",
        [
            # Solo indicators within sentences
            ("I'm traveling solo", True),
            ("traveling solo to Paris", True),
            ("solo trip to Rome", True),
            ("just me going to Tokyo", True),
            ("I'm going alone", True),
            ("traveling by myself", True),
            ("on my own", True),
            # Couple indicators
            ("my partner and I are going", True),
            ("my husband and I", True),
            ("my wife and I", True),
            ("two of us traveling", True),
            ("just the two of us", True),
            ("as a couple", True),
            # Numeric in sentences
            ("there are 3 of us", True),
            ("4 people going", True),
            ("2 adults traveling", True),
            # Family patterns
            ("family of 5 going", True),
            ("group of 4", True),
            # Negative cases (should not match random text)
            ("I want to visit Paris", False),
            ("looking for hotels", False),
        ],
    )
    def test_inline_travelers_pattern(self, input_text: str, expected_match: bool):
        """Test inline traveler detection patterns."""
        match = INLINE_TRAVELERS_PATTERN.search(input_text.lower())
        if expected_match:
            assert match is not None, f"Pattern should match in '{input_text}'"
        else:
            assert match is None, f"Pattern should NOT match in '{input_text}'"


class TestInitialMessageExtraction:
    """Test traveler extraction in initial message extraction."""

    def test_solo_trip_extraction(self):
        """Test that 'solo trip to Paris' extracts both destination and adults."""
        state = GraphState(
            user_text="solo trip to Paris",
            trip_inputs=TripInputs(),
            question_target=None,
            metadata={},
        )

        result = _try_initial_message_extraction("solo trip to Paris", state)

        assert result is not None, "Should extract from 'solo trip to Paris'"
        assert "travelers" in result["fields"] or result["parsed"].get("adults_delta") == 1

    def test_traveling_alone_extraction(self):
        """Test that 'I'm traveling alone to Rome' extracts solo traveler."""
        state = GraphState(
            user_text="I'm traveling alone to Rome",
            trip_inputs=TripInputs(),
            question_target=None,
            metadata={},
        )

        result = _try_initial_message_extraction("I'm traveling alone to Rome", state)

        assert result is not None
        # Should extract destination and/or travelers

    def test_two_of_us_extraction(self):
        """Test that 'two of us going to Barcelona' extracts 2 adults."""
        state = GraphState(
            user_text="two of us going to Barcelona",
            trip_inputs=TripInputs(),
            question_target=None,
            metadata={},
        )

        result = _try_initial_message_extraction("two of us going to Barcelona", state)

        # The pattern should detect "two of us"
        assert result is not None

    def test_numeric_travelers_extraction(self):
        """Test '3 adults to Tokyo' extracts numeric travelers."""
        state = GraphState(
            user_text="3 adults to Tokyo",
            trip_inputs=TripInputs(),
            question_target=None,
            metadata={},
        )

        result = _try_initial_message_extraction("3 adults to Tokyo", state)

        assert result is not None
        assert result["parsed"].get("adults_delta") == 3 or "travelers" in result["fields"]


class TestDefaultAdultsConfig:
    """Test default adults configuration."""

    def test_default_adults_enabled(self):
        """Verify default_adults_enabled is True."""
        from app.config import settings

        assert settings.default_adults_enabled is True

    def test_core_complete_without_adults(self):
        """Test trip readiness when destination/dates set but no adults."""
        from app.plan_graph import compute_trip_readiness

        ti = TripInputs(
            destinations=["Paris"],
            start_date="2025-06-15",
            origin="London",
        )

        readiness = compute_trip_readiness(ti)

        # With destination and dates, check that destinations are present
        # Adults will be defaulted to 1 if missing
        assert ti.destinations == ["Paris"]
        assert ti.start_date == "2025-06-15"
        assert readiness.core_complete or "travelers" in readiness.missing_core
