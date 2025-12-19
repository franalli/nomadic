"""
Tests for Strategy Stage 2 pagination and section expansion.

Phase 1 Token Optimization: Tests tier detection, section-level caching,
and max_tokens enforcement per tier.
"""

import pytest

from app.plan_graph import (
    STRATEGY_TIER_MAX_TOKENS,
    StrategyExpansionResult,
    StrategyExpansionTarget,
    StrategyTier,
    _is_strategy_expansion_request,
)

# =============================================================================
# TIER DETECTION TESTS
# =============================================================================


class TestTierDetection:
    """Tests for _is_strategy_expansion_request tier detection."""

    def test_no_expansion_detected(self):
        """Non-expansion requests should return is_expansion=False."""
        result = _is_strategy_expansion_request("I want to go hiking in the Alps")
        assert result.is_expansion is False
        assert result.target is None
        assert result.tier is None

    def test_implicit_confirmation_not_expansion(self):
        """Implicit confirmations like 'yes' should NOT trigger expansion."""
        for phrase in ["yes", "okay", "sounds good", "let's do it", "perfect"]:
            result = _is_strategy_expansion_request(phrase)
            assert result.is_expansion is False, f"'{phrase}' should not trigger expansion"


class TestFullTierDetection:
    """Tests for FULL tier (2048 tokens) detection."""

    @pytest.mark.parametrize(
        "phrase",
        [
            "full itinerary",
            "full plan",
            "complete itinerary",
            "complete plan",
            "everything",
            "all the details",
            "the whole thing",
            "entire itinerary",
            "detailed plan",
        ],
    )
    def test_full_tier_triggers(self, phrase):
        """FULL tier phrases should return tier=FULL and target=FULL_EXPANSION."""
        result = _is_strategy_expansion_request(phrase)
        assert result.is_expansion is True
        assert result.tier == StrategyTier.FULL
        assert result.target == StrategyExpansionTarget.FULL_EXPANSION
        assert result.matched_phrase == phrase

    def test_full_tier_embedded_in_sentence(self):
        """FULL tier should trigger even when embedded in longer text."""
        result = _is_strategy_expansion_request("Can you show me the full itinerary please?")
        assert result.is_expansion is True
        assert result.tier == StrategyTier.FULL
        assert result.target == StrategyExpansionTarget.FULL_EXPANSION


class TestSectionTierDetection:
    """Tests for SECTION tier (768 tokens) detection."""

    @pytest.mark.parametrize(
        "phrase,expected_target",
        [
            # Day details
            ("day 1", StrategyExpansionTarget.DAY_DETAILS),
            ("day 2", StrategyExpansionTarget.DAY_DETAILS),
            ("day 3", StrategyExpansionTarget.DAY_DETAILS),
            ("expand day 2", StrategyExpansionTarget.DAY_DETAILS),
            ("first day", StrategyExpansionTarget.DAY_DETAILS),
            ("day-by-day", StrategyExpansionTarget.DAY_DETAILS),
            ("daily breakdown", StrategyExpansionTarget.DAY_DETAILS),
            # Routes and trails
            ("routes", StrategyExpansionTarget.ROUTES_TRAILS),
            ("trails", StrategyExpansionTarget.ROUTES_TRAILS),
            ("hikes", StrategyExpansionTarget.ROUTES_TRAILS),
            ("route options", StrategyExpansionTarget.ROUTES_TRAILS),
            # Logistics
            ("logistics", StrategyExpansionTarget.LOGISTICS),
            ("transport", StrategyExpansionTarget.LOGISTICS),
            ("transfers", StrategyExpansionTarget.LOGISTICS),
            ("getting there", StrategyExpansionTarget.LOGISTICS),
            # Budget
            ("budget", StrategyExpansionTarget.BUDGET),
            ("cost", StrategyExpansionTarget.BUDGET),
            ("costs", StrategyExpansionTarget.BUDGET),
            ("cost breakdown", StrategyExpansionTarget.BUDGET),
            ("expenses", StrategyExpansionTarget.BUDGET),
            # Gear and packing
            ("gear", StrategyExpansionTarget.GEAR_PACKING),
            ("equipment", StrategyExpansionTarget.GEAR_PACKING),
            ("packing list", StrategyExpansionTarget.GEAR_PACKING),
            ("what to bring", StrategyExpansionTarget.GEAR_PACKING),
            # Contingencies
            ("contingencies", StrategyExpansionTarget.CONTINGENCIES),
            ("backup plan", StrategyExpansionTarget.CONTINGENCIES),
            ("weather", StrategyExpansionTarget.CONTINGENCIES),
            ("rain plan", StrategyExpansionTarget.CONTINGENCIES),
            ("alternatives", StrategyExpansionTarget.CONTINGENCIES),
        ],
    )
    def test_section_tier_triggers(self, phrase, expected_target):
        """Section-specific phrases should return tier=SECTION with correct target."""
        result = _is_strategy_expansion_request(phrase)
        assert result.is_expansion is True
        assert result.tier == StrategyTier.SECTION
        assert result.target == expected_target

    def test_section_embedded_in_question(self):
        """Section keywords should trigger when in natural questions."""
        result = _is_strategy_expansion_request("What about the budget for this trip?")
        assert result.is_expansion is True
        assert result.tier == StrategyTier.SECTION
        assert result.target == StrategyExpansionTarget.BUDGET


class TestGenericExpansionDetection:
    """Tests for generic expansion triggers (default to ITINERARY_OUTLINE)."""

    @pytest.mark.parametrize(
        "phrase",
        [
            "expand",
            "show details",
            "show more details",
            "tell me more",
            "more details",
            "elaborate",
            "go deeper",
            "give me more",
        ],
    )
    def test_generic_expansion_triggers(self, phrase):
        """Generic expansion phrases should default to ITINERARY_OUTLINE at SECTION tier."""
        result = _is_strategy_expansion_request(phrase)
        assert result.is_expansion is True
        assert result.tier == StrategyTier.SECTION
        assert result.target == StrategyExpansionTarget.ITINERARY_OUTLINE


class TestTierPrecedence:
    """Tests that FULL tier takes precedence over SECTION when both match."""

    def test_full_takes_precedence_over_section(self):
        """FULL triggers should be checked before section-specific patterns."""
        # "detailed plan" is a FULL trigger, not a section trigger
        result = _is_strategy_expansion_request("detailed plan")
        assert result.tier == StrategyTier.FULL

    def test_full_with_section_keyword(self):
        """If user asks for 'everything including budget', should get FULL tier."""
        result = _is_strategy_expansion_request("give me everything")
        assert result.is_expansion is True
        assert result.tier == StrategyTier.FULL


# =============================================================================
# MAX TOKENS CONFIGURATION TESTS
# =============================================================================


class TestMaxTokensConfig:
    """Tests for STRATEGY_TIER_MAX_TOKENS configuration."""

    def test_tier_max_tokens_values(self):
        """Verify max_tokens for each tier are correctly configured."""
        assert STRATEGY_TIER_MAX_TOKENS[StrategyTier.OUTLINE] == 512
        assert STRATEGY_TIER_MAX_TOKENS[StrategyTier.SECTION] == 768
        assert STRATEGY_TIER_MAX_TOKENS[StrategyTier.FULL] == 2048

    def test_all_tiers_have_max_tokens(self):
        """All StrategyTier values should have max_tokens defined."""
        for tier in StrategyTier:
            assert tier in STRATEGY_TIER_MAX_TOKENS, f"Missing max_tokens for {tier}"


# =============================================================================
# STRATEGY EXPANSION RESULT DATACLASS TESTS
# =============================================================================


class TestStrategyExpansionResult:
    """Tests for StrategyExpansionResult dataclass."""

    def test_result_no_expansion(self):
        """Non-expansion result should have sensible defaults."""
        result = StrategyExpansionResult(is_expansion=False)
        assert result.is_expansion is False
        assert result.target is None
        assert result.tier is None
        assert result.matched_phrase is None

    def test_result_with_expansion(self):
        """Expansion result should contain all fields."""
        result = StrategyExpansionResult(
            is_expansion=True,
            target=StrategyExpansionTarget.DAY_DETAILS,
            tier=StrategyTier.SECTION,
            matched_phrase="day 1",
        )
        assert result.is_expansion is True
        assert result.target == StrategyExpansionTarget.DAY_DETAILS
        assert result.tier == StrategyTier.SECTION
        assert result.matched_phrase == "day 1"


# =============================================================================
# ENUM VALUE TESTS
# =============================================================================


class TestEnumValues:
    """Tests for enum string values (used in JSON serialization)."""

    def test_expansion_target_values(self):
        """StrategyExpansionTarget values should be lowercase snake_case."""
        assert StrategyExpansionTarget.ITINERARY_OUTLINE.value == "itinerary_outline"
        assert StrategyExpansionTarget.DAY_DETAILS.value == "day_details"
        assert StrategyExpansionTarget.ROUTES_TRAILS.value == "routes_trails"
        assert StrategyExpansionTarget.LOGISTICS.value == "logistics"
        assert StrategyExpansionTarget.BUDGET.value == "budget"
        assert StrategyExpansionTarget.GEAR_PACKING.value == "gear_packing"
        assert StrategyExpansionTarget.CONTINGENCIES.value == "contingencies"
        assert StrategyExpansionTarget.FULL_EXPANSION.value == "full_expansion"

    def test_tier_values(self):
        """StrategyTier values should be lowercase."""
        assert StrategyTier.OUTLINE.value == "outline"
        assert StrategyTier.SECTION.value == "section"
        assert StrategyTier.FULL.value == "full"
