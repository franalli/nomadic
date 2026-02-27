"""
Unit tests for patterns_registry.py — regex/keyword pattern registries.

Tests BUDGET_PATTERNS, TRAVELER_PATTERNS, and SETTINGS_KEYWORDS against
known inputs to ensure extraction reliability.
"""

from __future__ import annotations

import re

import pytest

from app.planner.patterns_registry import (
    BUDGET_PATTERNS,
    SETTINGS_KEYWORDS,
    TRAVELER_PATTERNS,
)

# =============================================================================
# Budget pattern tests
# =============================================================================


class TestBudgetPatterns:
    """Test budget extraction from natural language."""

    @pytest.mark.parametrize(
        "text, expected_amount",
        [
            ("budget is $5000", "5000"),
            ("budget of $3,500", "3,500"),
            ("budget around 2000", "2000"),
            ("spending to $10000", "10000"),
            ("$3000 budget", "3000"),
            ("budget is 5000", "5000"),
            ("have $2000 to spend", "2000"),
            ("got $1500 for the trip", "1500"),
            ("up to $8000", "8000"),
            ("maximum $6000", "6000"),
            ("around $4500", "4500"),
            ("about 3000", "3000"),
        ],
    )
    def test_budget_extraction(self, text: str, expected_amount: str) -> None:
        matched = False
        for pattern in BUDGET_PATTERNS:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                # At least one group should match the expected amount
                groups = [g for g in m.groups() if g is not None]
                assert any(expected_amount in g for g in groups), (
                    f"Pattern {pattern!r} matched but groups {groups} "
                    f"don't contain {expected_amount!r}"
                )
                matched = True
                break
        assert matched, f"No pattern matched: {text!r}"

    def test_budget_with_k_suffix(self) -> None:
        """5k should be captured (the 'k' handling is in the pattern, extraction code applies multiplier)."""
        text = "budget is $5k"
        matched = False
        for pattern in BUDGET_PATTERNS:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                matched = True
                break
        assert matched, "No pattern matched '$5k'"

    def test_no_false_positive_on_plain_number(self) -> None:
        """Plain number without budget context should not match most patterns."""
        text = "I want 5 days in Bali"
        matches = 0
        for pattern in BUDGET_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                matches += 1
        # Should not match budget patterns (or at most one loose pattern)
        assert matches <= 1


# =============================================================================
# Traveler pattern tests
# =============================================================================


class TestTravelerPatterns:
    """Test traveler count extraction."""

    def test_combined_adults_and_children(self) -> None:
        """'4 adults and 2 kids' should match the combined pattern first."""
        text = "4 adults and 2 kids"
        # First pattern is the combined one
        m = re.search(TRAVELER_PATTERNS[0], text, re.IGNORECASE)
        assert m is not None
        assert m.group(1) == "4"  # adults
        assert m.group(2) == "2"  # children

    def test_children_only(self) -> None:
        text = "traveling with 3 children"
        m = re.search(TRAVELER_PATTERNS[1], text, re.IGNORECASE)
        assert m is not None
        assert m.group(1) == "3"

    def test_party_of_n(self) -> None:
        text = "party of 6"
        m = re.search(TRAVELER_PATTERNS[2], text, re.IGNORECASE)
        assert m is not None
        assert m.group(1) == "6"

    def test_adults_only(self) -> None:
        text = "2 adults"
        m = re.search(TRAVELER_PATTERNS[3], text, re.IGNORECASE)
        assert m is not None
        assert m.group(1) == "2"

    def test_people_count(self) -> None:
        text = "4 people"
        m = re.search(TRAVELER_PATTERNS[3], text, re.IGNORECASE)
        assert m is not None
        assert m.group(1) == "4"

    def test_solo_traveler(self) -> None:
        text = "traveling solo"
        m = re.search(TRAVELER_PATTERNS[4], text, re.IGNORECASE)
        assert m is not None

    def test_couple(self) -> None:
        text = "we are a couple"
        m = re.search(TRAVELER_PATTERNS[4], text, re.IGNORECASE)
        assert m is not None

    def test_family_of_n(self) -> None:
        text = "family of 5"
        m = re.search(TRAVELER_PATTERNS[4], text, re.IGNORECASE)
        assert m is not None

    def test_pattern_order_combined_before_adults(self) -> None:
        """Combined pattern MUST come before adults-only to avoid partial match."""
        text = "3 adults and 1 child"
        # Combined (index 0) should match before adults-only (index 3)
        combined_match = re.search(TRAVELER_PATTERNS[0], text, re.IGNORECASE)
        assert combined_match is not None
        assert combined_match.group(1) == "3"
        assert combined_match.group(2) == "1"

    @pytest.mark.parametrize(
        "text, expected_count",
        [
            ("2 adults", "2"),
            ("5 travelers", "5"),
            ("3 persons", "3"),
        ],
    )
    def test_various_adult_forms(self, text: str, expected_count: str) -> None:
        m = re.search(TRAVELER_PATTERNS[3], text, re.IGNORECASE)
        assert m is not None
        assert m.group(1) == expected_count


# =============================================================================
# Settings keyword tests
# =============================================================================


class TestSettingsKeywords:
    """Test settings keyword detection."""

    def test_all_keywords_are_lowercase(self) -> None:
        for kw in SETTINGS_KEYWORDS:
            assert kw == kw.lower(), f"Keyword should be lowercase: {kw!r}"

    def test_toggle_keywords_present(self) -> None:
        assert "turn off" in SETTINGS_KEYWORDS
        assert "turn on" in SETTINGS_KEYWORDS
        assert "skip flights" in SETTINGS_KEYWORDS
        assert "skip hotels" in SETTINGS_KEYWORDS

    def test_flight_preference_keywords(self) -> None:
        assert "direct flight" in SETTINGS_KEYWORDS
        assert "nonstop flight" in SETTINGS_KEYWORDS
        assert "business class" in SETTINGS_KEYWORDS
        assert "economy class" in SETTINGS_KEYWORDS
        assert "round trip" in SETTINGS_KEYWORDS

    def test_hotel_preference_keywords(self) -> None:
        assert "star hotel" in SETTINGS_KEYWORDS
        assert "luxury hotel" in SETTINGS_KEYWORDS
        assert "budget hotel" in SETTINGS_KEYWORDS

    def test_no_generic_activity_words(self) -> None:
        """Keywords should be specific enough to avoid false positives on activity descriptions."""
        # These should NOT be in settings keywords as they could match activity descriptions
        generic_words = ["yoga", "cooking", "beach", "hiking", "diving"]
        for word in generic_words:
            assert word not in SETTINGS_KEYWORDS, (
                f"Generic activity word {word!r} should not be a settings keyword"
            )

    @pytest.mark.parametrize(
        "text, should_match",
        [
            ("I want direct flights only", True),
            ("Can you find nonstop flight options?", True),
            ("Turn off hotel search", True),
            ("I love cooking classes in Bali", False),
            ("Let's go hiking tomorrow", False),
            ("Find me a yoga retreat", False),
        ],
    )
    def test_keyword_matching_in_context(self, text: str, should_match: bool) -> None:
        text_lower = text.lower()
        matched = any(kw in text_lower for kw in SETTINGS_KEYWORDS)
        assert matched == should_match, (
            f"Text {text!r}: expected match={should_match}, got {matched}"
        )

    def test_minimum_keyword_count(self) -> None:
        """Sanity check: should have a reasonable number of keywords."""
        assert len(SETTINGS_KEYWORDS) >= 15
