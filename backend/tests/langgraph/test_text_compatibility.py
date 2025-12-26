"""
Table-driven tests for text_is_compatible_with_target function.

These tests validate that the ownership suppression primitive correctly
identifies when user text is answering a specific question_target.

PR0 deliverable: Lock in behavior for dates/origin/destinations/travelers/budget.
"""

import pytest

from app.pattern_matching import is_text_date_compatible, text_is_compatible_with_target
from app.plan_graph import GateEvaluator


class TestIsTextDateCompatible:
    """Direct tests for the consolidated is_text_date_compatible function."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            # Standalone relative date words (P0 fix)
            ("tomorrow", True),
            ("Tomorrow", True),
            ("TOMORROW", True),
            ("today", True),
            ("tonight", True),
            ("weekend", True),
            # Should not match non-date text
            ("Paris", False),
            ("Swiss Alps", False),
            ("hiking", False),
            ("family of four", False),
        ],
    )
    def test_relative_date_words(self, text: str, expected: bool):
        """Test that relative date words are recognized."""
        result = is_text_date_compatible(text)
        assert result == expected, f"text='{text}' expected {expected}, got {result}"


class TestTextIsCompatibleWithTargetDates:
    """Tests for dates/start_date question target compatibility."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            # Month-to-month ranges
            ("June to November", True),
            ("March through October", True),
            ("Jan-Dec", True),
            ("january to february", True),
            # Single months
            ("November", True),
            ("next June", True),
            ("this March", True),
            # Seasons
            ("next summer", True),
            ("this winter", True),
            ("spring", True),
            ("fall", True),
            ("autumn", True),
            # Relative phrases
            ("next month", True),
            ("this week", True),
            ("next year", True),
            # Relative date words (P0 fix: standalone words like "tomorrow")
            ("tomorrow", True),
            ("Tomorrow", True),  # Case insensitive
            ("TOMORROW", True),  # All caps
            ("today", True),
            ("Today", True),
            ("tonight", True),
            ("Tonight", True),
            ("weekend", True),
            ("Weekend", True),
            # Flexibility
            ("flexible", True),
            ("whenever", True),
            ("anytime", True),
            # Date-like numbers
            ("15/06", True),
            ("2025", True),
            ("March 15th", True),
            ("21st", True),
            # Preposition + month
            ("in December", True),
            ("around January", True),
            ("by March", True),
            ("after June", True),
            # Non-date answers (should be False)
            ("Paris", False),
            ("I want to go hiking", False),
            ("family of four", False),
            ("budget trip", False),
        ],
    )
    def test_dates_compatibility(self, text: str, expected: bool):
        """Test dates target compatibility."""
        result = GateEvaluator.text_is_compatible_with_target(text, "dates")
        assert result == expected, f"text='{text}' expected {expected}, got {result}"

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("June to November", True),
            ("next month", True),
            ("2025-03-15", True),
        ],
    )
    def test_start_date_compatibility(self, text: str, expected: bool):
        """Test start_date target (same as dates)."""
        result = GateEvaluator.text_is_compatible_with_target(text, "start_date")
        assert result == expected


class TestTextIsCompatibleWithTargetOrigin:
    """Tests for origin question target compatibility."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            # City names (capitalized)
            ("New York", True),
            ("London", True),
            ("Sydney", True),
            ("San Francisco", True),
            # Should NOT match strategy keywords
            ("I want to go hiking", False),
            ("diving trip please", False),
            ("skiing adventure", False),
            # Short non-capitalized (may or may not match depending on known_places)
            # Known places should match
            ("paris", True),  # Known place (lowercase)
            ("tokyo", True),  # Known place
        ],
    )
    def test_origin_compatibility(self, text: str, expected: bool):
        """Test origin target compatibility."""
        result = GateEvaluator.text_is_compatible_with_target(text, "origin")
        assert result == expected, f"text='{text}' expected {expected}, got {result}"


class TestTextIsCompatibleWithTargetDestinations:
    """Tests for destinations question target compatibility."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            # Known places
            ("Paris", True),
            ("Tokyo", True),
            ("Maldives", True),
            ("Swiss Alps", True),
            # Multiple places - may not be detected as single known place
            # This depends on is_known_place implementation
            ("Paris and Rome", False),  # Combined text may not match as known place
            # Unknown text (depends on is_known_place)
            ("asdfghjkl", False),
        ],
    )
    def test_destinations_compatibility(self, text: str, expected: bool):
        """Test destinations target compatibility."""
        result = GateEvaluator.text_is_compatible_with_target(text, "destinations")
        assert result == expected, f"text='{text}' expected {expected}, got {result}"


class TestTextIsCompatibleWithTargetTravelers:
    """Tests for travelers question target compatibility."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            # Numbers
            ("2", True),
            ("four", True),
            ("3 adults", True),
            ("two adults and one child", True),
            # Keywords
            ("just me", True),
            ("solo", True),
            ("alone", True),
            ("couple", True),
            ("family", True),
            # Complex patterns
            ("family of four", True),
            # "me and my wife" - depends on pattern matching (may not match)
            ("me and my wife", False),  # Pattern requires specific keywords
            # Non-traveler answers
            ("Paris", False),
            ("next week", False),
        ],
    )
    def test_travelers_compatibility(self, text: str, expected: bool):
        """Test travelers target compatibility."""
        result = GateEvaluator.text_is_compatible_with_target(text, "travelers")
        assert result == expected, f"text='{text}' expected {expected}, got {result}"


class TestTextIsCompatibleWithTargetBudget:
    """Tests for budget question target compatibility."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            # Currency symbols
            ("$5000", True),
            ("€3000", True),
            ("£2000", True),
            # Budget keywords
            ("budget", True),
            ("cheap", True),
            ("luxury", True),
            ("mid-range", True),
            ("moderate", True),
            ("flexible", True),
            # Numbers without currency
            ("5000", True),
            ("around 3000", True),
            # Non-budget answers
            ("Paris", False),
            ("next week", False),
            ("family", False),
        ],
    )
    def test_budget_compatibility(self, text: str, expected: bool):
        """Test budget target compatibility."""
        result = GateEvaluator.text_is_compatible_with_target(text, "budget")
        assert result == expected, f"text='{text}' expected {expected}, got {result}"


class TestTextIsCompatibleWithTargetEdgeCases:
    """Edge case tests for text_is_compatible_with_target."""

    def test_none_target_returns_false(self):
        """None question_target should return False."""
        result = GateEvaluator.text_is_compatible_with_target("anything", None)
        assert result is False

    def test_empty_text_returns_false(self):
        """Empty text should return False."""
        result = GateEvaluator.text_is_compatible_with_target("", "dates")
        assert result is False

    def test_unknown_target_returns_false(self):
        """Unknown question_target should return False (conservative)."""
        result = GateEvaluator.text_is_compatible_with_target("anything", "unknown_target")
        assert result is False

    def test_case_insensitive_matching(self):
        """Matching should be case-insensitive."""
        assert GateEvaluator.text_is_compatible_with_target("JUNE TO NOVEMBER", "dates") is True
        assert GateEvaluator.text_is_compatible_with_target("next SUMMER", "dates") is True


class TestPatternMatchingModuleCompatibility:
    """Tests for the pattern_matching module's text_is_compatible_with_target."""

    @pytest.mark.parametrize(
        "text,target,expected",
        [
            # Budget patterns
            ("$5000", "budget", True),
            ("mid-range", "budget", True),
            ("cheap", "budget", True),
            # Date patterns
            ("June to November", "dates", True),
            ("March through October", "dates", True),
            # Traveler patterns - pattern_matching.py uses different patterns
            ("2 adults", "travelers", True),
            ("just me", "travelers", True),  # Use keyword that actually matches
            # None target
            ("anything", None, True),  # pattern_matching returns True for None
        ],
    )
    def test_pattern_matching_module(self, text: str, target: str | None, expected: bool):
        """Test pattern_matching module implementation."""
        result = text_is_compatible_with_target(text, target)
        assert result == expected, f"text='{text}', target='{target}' expected {expected}"


class TestOwnershipSuppressionScenarios:
    """
    Integration-style tests for ownership suppression scenarios.

    These verify the "active question wins" invariant:
    When question_target is set and text is compatible, no strategy/topic gate should fire.
    """

    @pytest.mark.parametrize(
        "question_target,user_text,should_suppress",
        [
            # Date answers should suppress strategy gates
            ("dates", "June to November", True),
            ("dates", "next summer", True),
            ("dates", "2025-03-15", True),
            # Origin answers should suppress
            ("origin", "New York", True),
            ("origin", "London", True),
            # Destination answers should suppress
            ("destinations", "Paris", True),
            ("destinations", "Tokyo", True),
            # Traveler answers should suppress
            ("travelers", "family of four", True),
            ("travelers", "just me", True),
            # Budget answers should suppress
            ("budget", "$5000", True),
            ("budget", "mid-range", True),
            # Non-answers should NOT suppress (strategy keywords)
            ("dates", "I want to go hiking", False),
            ("dates", "let's go diving", False),
            ("origin", "skiing trip please", False),
        ],
    )
    def test_ownership_suppression_decision(
        self, question_target: str, user_text: str, should_suppress: bool
    ):
        """
        Test that compatible answers suppress topic switches.

        This is the core "active question wins" invariant.
        """
        is_compatible = GateEvaluator.text_is_compatible_with_target(user_text, question_target)
        assert is_compatible == should_suppress, (
            f"question_target='{question_target}', text='{user_text}': "
            f"expected suppress={should_suppress}, got is_compatible={is_compatible}"
        )
