"""
Tests for field modification request detection in strategy flow.

Tests the detect_field_modification_request function which handles cases like:
- "Wait, I want to add budget"
- "I need to add travelers"
- "Can I set my dates?"

These tests verify the fix for the issue where "I want to add budget"
was being ignored during strategy topic flow.
"""

import pytest

from app.planner.nodes.strategy.base import (
    FIELD_MODIFICATION_KEYWORDS,
    FIELD_MODIFICATION_PHRASES,
    detect_field_modification_request,
)


# =============================================================================
# Field Modification Detection Tests
# =============================================================================
class TestFieldModificationDetection:
    """Test the detect_field_modification_request function."""

    @pytest.mark.parametrize(
        "user_text,expected_field",
        [
            # Budget variations
            ("I want to add budget", "budget"),
            ("Wait, I want to add budget", "budget"),
            ("can i add my budget?", "budget"),
            ("let me add a budget", "budget"),
            ("need to add budget", "budget"),
            ("I want to set the budget", "budget"),
            ("want to update the price", "budget"),
            ("actually, I want to add my spending limit", "budget"),
            # Travelers variations
            ("I want to add travelers", "travelers"),
            ("wait, need to add people", "travelers"),
            ("can i add the group size", "travelers"),
            ("I want to set adults", "travelers"),
            ("let me add how many kids", "travelers"),
            # Dates variations
            ("I want to add dates", "dates"),
            ("wait, I need to change the date", "dates"),
            ("can i set my timing?", "dates"),
            ("I want to update when we're going", "dates"),
            # Origin variations
            ("I want to add origin", "origin"),
            ("let me add where I'm departing from", "origin"),
            ("wait, I need to set departure", "origin"),
        ],
    )
    def test_detects_field_modification_requests(self, user_text: str, expected_field: str):
        """Field modification requests should be detected correctly."""
        result = detect_field_modification_request(user_text)
        assert (
            result == expected_field
        ), f"Expected '{expected_field}' for '{user_text}', got '{result}'"

    @pytest.mark.parametrize(
        "user_text",
        [
            # No modification phrase
            "budget",
            "what's my budget?",
            "travelers",
            "3 adults",
            "$5000",
            # Strategy topic keywords (should NOT trigger field detection)
            "advanced hiking spots",
            "beginner-friendly hiking",
            "I want to go hiking",
            "tell me about trails",
            # Random text
            "hello",
            "yes",
            "sounds good",
            "show more details",
            # Missing field keyword (has phrase but no field)
            "I want to add something",
            "let me add more info",
        ],
    )
    def test_no_false_positives(self, user_text: str):
        """Non-field-modification requests should return None."""
        result = detect_field_modification_request(user_text)
        assert result is None, f"Should not detect field for '{user_text}', got '{result}'"


class TestFieldModificationConstants:
    """Test the constants used for field modification detection."""

    def test_field_keywords_cover_all_fields(self):
        """Field keywords should cover budget, travelers, dates, origin."""
        fields = set(FIELD_MODIFICATION_KEYWORDS.values())
        expected_fields = {"budget", "travelers", "dates", "origin"}
        assert fields == expected_fields, f"Missing fields: {expected_fields - fields}"

    def test_modification_phrases_are_lowercase(self):
        """All modification phrases should be lowercase for matching."""
        for phrase in FIELD_MODIFICATION_PHRASES:
            assert phrase == phrase.lower(), f"Phrase '{phrase}' should be lowercase"

    def test_field_keywords_are_lowercase(self):
        """All field keywords should be lowercase for matching."""
        for keyword in FIELD_MODIFICATION_KEYWORDS.keys():
            assert keyword == keyword.lower(), f"Keyword '{keyword}' should be lowercase"


# =============================================================================
# Integration Test - Strategy Relevance Gate
# =============================================================================
class TestStrategyRelevanceGateFieldModification:
    """
    Test that field modification requests are handled correctly
    in the strategy relevance gate.

    This tests the V38 fix where "I want to add budget" during
    an active hiking strategy should prompt for budget, not
    ask about hiking experience.
    """

    def test_budget_request_during_strategy_flow(self):
        """
        When user says 'Wait, I want to add budget' during hiking strategy,
        the system should detect this as a field modification request.
        """
        # The key test case from the bug report
        user_text = "Wait, I want to add budget"
        detected_field = detect_field_modification_request(user_text)

        assert (
            detected_field == "budget"
        ), f"'Wait, I want to add budget' should detect 'budget', got '{detected_field}'"

    def test_travelers_request_during_strategy_flow(self):
        """
        When user says 'Hold on, I need to add travelers' during strategy,
        the system should detect this as a field modification request.
        """
        user_text = "Hold on, I need to add travelers"
        detected_field = detect_field_modification_request(user_text)

        assert (
            detected_field == "travelers"
        ), f"'Hold on, I need to add travelers' should detect 'travelers', got '{detected_field}'"

    def test_dates_request_during_strategy_flow(self):
        """
        When user says 'Actually, I want to change my dates' during strategy,
        the system should detect this as a field modification request.
        """
        user_text = "Actually, I want to change my dates"
        detected_field = detect_field_modification_request(user_text)

        assert (
            detected_field == "dates"
        ), f"'Actually, I want to change my dates' should detect 'dates', got '{detected_field}'"
