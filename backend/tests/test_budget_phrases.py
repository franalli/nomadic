"""
Tests for budget phrase recognition and compatibility checks.

This module tests:
1. FLEXIBLE_BUDGET_PHRASES are recognized as valid budget answers
2. BUDGET_TIER_PHRASES are recognized as valid budget answers
3. text_is_compatible_with_target correctly identifies budget answers
4. Numeric budgets still work correctly
5. Budget compatibility pattern matches expected phrases
"""

import pytest

from app.pattern_matching import (
    BUDGET_COMPATIBILITY_PATTERN,
    BUDGET_TIER_PHRASES,
    FLEXIBLE_BUDGET_PHRASES,
    NO_BUDGET_PHRASES,
    text_is_compatible_with_target,
)


class TestFlexibleBudgetPhrases:
    """Test that flexible budget phrases are recognized."""

    @pytest.mark.parametrize(
        "phrase",
        [
            "no budget",
            "no limit",
            "flexible",
            "flexible budget",
            "no specific budget",
            "unlimited",
            "no preference",
            "any budget",
            "doesn't matter",
            "don't care",
            "whatever works",
            "open",
            "open budget",
            "no max",
            "no maximum",
            "skip",
            "pass",
        ],
    )
    def test_flexible_phrase_in_set(self, phrase: str) -> None:
        """Test that key flexible phrases are in FLEXIBLE_BUDGET_PHRASES."""
        assert phrase in FLEXIBLE_BUDGET_PHRASES

    @pytest.mark.parametrize(
        "phrase",
        list(FLEXIBLE_BUDGET_PHRASES),
    )
    def test_flexible_phrase_compatibility(self, phrase: str) -> None:
        """Test that all flexible phrases pass budget compatibility check."""
        assert text_is_compatible_with_target(
            phrase, "budget"
        ), f"'{phrase}' should be compatible with budget target"

    @pytest.mark.parametrize(
        "phrase",
        list(FLEXIBLE_BUDGET_PHRASES),
    )
    def test_flexible_phrase_pattern_match(self, phrase: str) -> None:
        """Test that all flexible phrases match BUDGET_COMPATIBILITY_PATTERN."""
        assert BUDGET_COMPATIBILITY_PATTERN.search(
            phrase
        ), f"'{phrase}' should match BUDGET_COMPATIBILITY_PATTERN"


class TestBudgetTierPhrases:
    """Test that budget tier phrases are recognized."""

    @pytest.mark.parametrize(
        "phrase",
        [
            "budget-friendly",
            "budget friendly",
            "cheap",
            "cheapest",
            "mid-range",
            "midrange",
            "moderate",
            "luxury",
            "high-end",
            "premium",
            "splurge",
        ],
    )
    def test_tier_phrase_in_set(self, phrase: str) -> None:
        """Test that key tier phrases are in BUDGET_TIER_PHRASES."""
        assert phrase in BUDGET_TIER_PHRASES

    @pytest.mark.parametrize(
        "phrase",
        list(BUDGET_TIER_PHRASES),
    )
    def test_tier_phrase_compatibility(self, phrase: str) -> None:
        """Test that all tier phrases pass budget compatibility check."""
        assert text_is_compatible_with_target(
            phrase, "budget"
        ), f"'{phrase}' should be compatible with budget target"

    @pytest.mark.parametrize(
        "phrase",
        list(BUDGET_TIER_PHRASES),
    )
    def test_tier_phrase_pattern_match(self, phrase: str) -> None:
        """Test that all tier phrases match BUDGET_COMPATIBILITY_PATTERN."""
        assert BUDGET_COMPATIBILITY_PATTERN.search(
            phrase
        ), f"'{phrase}' should match BUDGET_COMPATIBILITY_PATTERN"


class TestNoBudgetPhrasesBackwardCompat:
    """Test NO_BUDGET_PHRASES is the union of flexible and tier phrases."""

    def test_union_composition(self) -> None:
        """Test that NO_BUDGET_PHRASES is the union of the two sets."""
        expected = FLEXIBLE_BUDGET_PHRASES | BUDGET_TIER_PHRASES
        assert NO_BUDGET_PHRASES == expected

    def test_flexible_subset(self) -> None:
        """Test that FLEXIBLE_BUDGET_PHRASES is a subset of NO_BUDGET_PHRASES."""
        assert FLEXIBLE_BUDGET_PHRASES.issubset(NO_BUDGET_PHRASES)

    def test_tier_subset(self) -> None:
        """Test that BUDGET_TIER_PHRASES is a subset of NO_BUDGET_PHRASES."""
        assert BUDGET_TIER_PHRASES.issubset(NO_BUDGET_PHRASES)


class TestNumericBudgets:
    """Test that numeric budgets still work correctly."""

    @pytest.mark.parametrize(
        "text",
        [
            "$2000",
            "2000 dollars",
            "around $3000",
            "about 5000 euros",
            "under $1500",
            "5k dollars",  # "5k" alone is ambiguous, needs currency context
            "€500",
            "£1000",
            "around 2000 euros",  # Bare number needs context
            "per person",
            "per night",
        ],
    )
    def test_numeric_budget_compatibility(self, text: str) -> None:
        """Test that numeric budgets pass compatibility check."""
        assert text_is_compatible_with_target(
            text, "budget"
        ), f"'{text}' should be compatible with budget target"

    @pytest.mark.parametrize(
        "text",
        [
            "$2000",
            # Bare numbers need currency context to avoid false positives like "2 adults"
            "2000 dollars",
            "5000 euros",
            "€500",
            "£1000",
        ],
    )
    def test_numeric_budget_pattern_match(self, text: str) -> None:
        """Test that numeric budgets match BUDGET_COMPATIBILITY_PATTERN."""
        assert BUDGET_COMPATIBILITY_PATTERN.search(
            text
        ), f"'{text}' should match BUDGET_COMPATIBILITY_PATTERN"


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_no_specific_budget_exact(self) -> None:
        """Test the exact phrase that caused the original issue."""
        phrase = "No specific budget"
        assert text_is_compatible_with_target(phrase, "budget")
        assert BUDGET_COMPATIBILITY_PATTERN.search(phrase.lower())

    def test_case_insensitive(self) -> None:
        """Test that budget compatibility is case insensitive."""
        assert text_is_compatible_with_target("NO LIMIT", "budget")
        assert text_is_compatible_with_target("Flexible", "budget")
        assert text_is_compatible_with_target("LUXURY", "budget")

    def test_embedded_phrases(self) -> None:
        """Test phrases embedded in sentences."""
        assert text_is_compatible_with_target("I have no specific budget", "budget")
        assert text_is_compatible_with_target("My budget is flexible", "budget")
        assert text_is_compatible_with_target("Looking for something budget-friendly", "budget")

    def test_non_budget_text(self) -> None:
        """Test that non-budget text does not match."""
        # These should NOT match the budget pattern
        non_budget_texts = [
            "hello",
            "I want to go to Paris",
            "tomorrow",
            "2 adults",
        ]
        for text in non_budget_texts:
            assert not BUDGET_COMPATIBILITY_PATTERN.search(
                text
            ), f"'{text}' should NOT match budget pattern"


class TestCompatibilityFunctionTarget:
    """Test text_is_compatible_with_target with budget target."""

    def test_budget_target_with_flexible_phrase(self) -> None:
        """Test budget target with flexible phrases."""
        assert text_is_compatible_with_target("no limit", "budget")
        assert text_is_compatible_with_target("flexible", "budget")
        assert text_is_compatible_with_target("doesn't matter", "budget")

    def test_budget_target_with_tier_phrase(self) -> None:
        """Test budget target with tier phrases."""
        assert text_is_compatible_with_target("budget-friendly", "budget")
        assert text_is_compatible_with_target("luxury", "budget")
        assert text_is_compatible_with_target("mid-range", "budget")

    def test_budget_target_with_numeric(self) -> None:
        """Test budget target with numeric values."""
        assert text_is_compatible_with_target("$2000", "budget")
        assert text_is_compatible_with_target("around 3000", "budget")

    def test_no_target_returns_true(self) -> None:
        """Test that None target returns True."""
        assert text_is_compatible_with_target("anything", None)
        assert text_is_compatible_with_target("no budget", None)
