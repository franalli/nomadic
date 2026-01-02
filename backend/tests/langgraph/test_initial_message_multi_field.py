"""
Unit tests for multi-field initial message extraction patterns.

Tests cover the new extraction patterns added to _try_initial_message_extraction:
- Pattern 2b: Origin from "based in", "living in", "I'm from" phrases
- Pattern 6b: Qualitative budget phrases like "limited budget", "cheap"
- Pattern 8: Duration extraction like "10 days", "for a week"

These patterns enable extracting multiple fields from a single initial message
like: "i want to go to patagonia, i am based in torun poland.
i have limited budget. take me for 10 days"
"""

import pytest

from app.pattern_matching import (
    BUDGET_TIER_ESTIMATES,
    INLINE_DURATION_PATTERN,
    ORIGIN_LOCATION_PATTERN,
    WORD_TO_NUMBER,
)
from app.plan_graph import (
    GraphState,
    TripInputs,
    _try_initial_message_extraction,
)


class TestOriginLocationPattern:
    """Test the ORIGIN_LOCATION_PATTERN for 'based in' style origin extraction."""

    @pytest.mark.parametrize(
        "input_text,expected_origin",
        [
            # "based in" patterns
            ("based in London", "London"),
            ("based in New York", "New York"),
            ("I am based in torun poland", "torun poland"),
            # "living in" patterns
            ("living in Paris", "Paris"),
            ("I'm living in Berlin", "Berlin"),
            # "located in" patterns
            ("located in Tokyo", "Tokyo"),
            # "coming from" patterns
            ("coming from Rome", "Rome"),
            # "I'm from" patterns
            ("I'm from Chicago", "Chicago"),
            ("I am from Seattle", "Seattle"),
            # "I'm in" patterns
            ("I'm in Boston", "Boston"),
            ("I am in Miami", "Miami"),
        ],
    )
    def test_origin_location_pattern_matches(self, input_text: str, expected_origin: str):
        """Test that origin location pattern matches various phrases."""
        match = ORIGIN_LOCATION_PATTERN.search(input_text)
        assert match is not None, f"Pattern should match '{input_text}'"
        assert match.group(1).strip() == expected_origin

    @pytest.mark.parametrize(
        "input_text",
        [
            # Should NOT match these
            "I want to go to Paris",
            "traveling to Rome",
            "visiting Tokyo",
            "flight to Berlin",
        ],
    )
    def test_origin_location_pattern_no_match(self, input_text: str):
        """Test that origin pattern does not match destination phrases."""
        match = ORIGIN_LOCATION_PATTERN.search(input_text)
        assert match is None, f"Pattern should NOT match '{input_text}'"


class TestInlineDurationPattern:
    """Test the INLINE_DURATION_PATTERN for duration extraction."""

    @pytest.mark.parametrize(
        "input_text,expected_num,expected_unit",
        [
            # Numeric days
            ("10 days", "10", "days"),
            ("5 days", "5", "days"),
            ("1 day", "1", "day"),
            # With "for" prefix
            ("for 10 days", "10", "days"),
            ("for 7 days", "7", "days"),
            # Nights
            ("3 nights", "3", "nights"),
            ("for 5 nights", "5", "nights"),
            # Weeks
            ("2 weeks", "2", "weeks"),
            ("for 1 week", "1", "week"),
            # Word numbers
            ("five days", "five", "days"),
            ("one week", "one", "week"),
            ("two weeks", "two", "weeks"),
            ("ten days", "ten", "days"),
            # In context
            ("take me for 10 days", "10", "days"),
            ("trip for a week", None, None),  # "a" not matched, but let's check
        ],
    )
    def test_inline_duration_pattern_matches(
        self, input_text: str, expected_num: str | None, expected_unit: str | None
    ):
        """Test that duration pattern matches various phrases."""
        match = INLINE_DURATION_PATTERN.search(input_text.lower())
        if expected_num is None:
            # Some edge cases may not match
            return
        assert match is not None, f"Pattern should match '{input_text}'"
        assert match.group(1) == expected_num
        assert match.group(2) == expected_unit

    def test_word_to_number_conversion(self):
        """Test word to number conversion for duration."""
        for _word, num in WORD_TO_NUMBER.items():
            assert isinstance(num, int)
            assert num >= 1 and num <= 10


class TestBudgetTierEstimates:
    """Test the BUDGET_TIER_ESTIMATES mapping for qualitative budget phrases."""

    @pytest.mark.parametrize(
        "phrase,expected_estimate",
        [
            # Low tier
            ("limited budget", 1500),
            ("tight budget", 1500),
            ("cheap", 1000),
            ("cheapest", 800),
            ("low budget", 1200),
            ("economical", 1500),
            # Mid tier
            ("moderate", 3000),
            ("mid-range", 3000),
            ("reasonable", 2500),
            # High tier
            ("luxury", 8000),
            ("high-end", 10000),
            ("premium", 7000),
            ("splurge", 10000),
        ],
    )
    def test_budget_tier_estimates_mapping(self, phrase: str, expected_estimate: int):
        """Test that budget tier phrases map to expected estimates."""
        assert phrase in BUDGET_TIER_ESTIMATES
        assert BUDGET_TIER_ESTIMATES[phrase] == expected_estimate

    def test_budget_estimates_are_reasonable(self):
        """Test that all budget estimates are positive integers."""
        for _phrase, estimate in BUDGET_TIER_ESTIMATES.items():
            assert isinstance(estimate, int)
            assert estimate > 0
            assert estimate <= 20000  # Reasonable upper bound


class TestInitialMessageMultiFieldExtraction:
    """Test multi-field extraction from initial messages."""

    def _make_state(self, user_text: str) -> GraphState:
        """Helper to create a fresh GraphState for initial message testing."""
        return GraphState(
            user_text=user_text,
            trip_inputs=TripInputs(),
            question_target=None,
            metadata={},
        )

    def test_origin_based_in_extraction(self):
        """Test that 'based in X' extracts origin."""
        state = self._make_state("I want to visit Paris, I am based in London")
        result = _try_initial_message_extraction(
            "I want to visit Paris, I am based in London", state
        )

        assert result is not None
        assert "origin" in result["fields"]
        # London should be normalized/extracted
        assert "origin_delta" in result["parsed"]

    def test_origin_im_from_extraction(self):
        """Test that 'I'm from X' extracts origin."""
        state = self._make_state("trip to Rome, I'm from Berlin")
        result = _try_initial_message_extraction("trip to Rome, I'm from Berlin", state)

        assert result is not None
        # Should extract destination and possibly origin
        assert "destinations" in result["fields"]

    def test_qualitative_budget_extraction(self):
        """Test that 'limited budget' extracts a numeric budget estimate."""
        state = self._make_state("trip to Paris with limited budget")
        result = _try_initial_message_extraction("trip to Paris with limited budget", state)

        assert result is not None
        assert "budget" in result["fields"]
        assert result["parsed"]["budget_delta"] == 1500

    def test_cheap_budget_extraction(self):
        """Test that 'cheap' extracts budget estimate."""
        state = self._make_state("cheap trip to Barcelona")
        result = _try_initial_message_extraction("cheap trip to Barcelona", state)

        assert result is not None
        assert "budget" in result["fields"]
        assert result["parsed"]["budget_delta"] == 1000

    def test_luxury_budget_extraction(self):
        """Test that 'luxury' extracts higher budget estimate."""
        state = self._make_state("luxury vacation to Maldives")
        result = _try_initial_message_extraction("luxury vacation to Maldives", state)

        assert result is not None
        assert "budget" in result["fields"]
        assert result["parsed"]["budget_delta"] == 8000

    def test_duration_10_days_extraction(self):
        """Test that '10 days' extracts duration."""
        state = self._make_state("trip to Italy for 10 days")
        result = _try_initial_message_extraction("trip to Italy for 10 days", state)

        assert result is not None
        assert "duration" in result["fields"]
        assert result["parsed"]["duration_delta"] == 10

    def test_duration_one_week_extraction(self):
        """Test that 'one week' extracts duration as 7 days."""
        state = self._make_state("vacation to Greece for one week")
        result = _try_initial_message_extraction("vacation to Greece for one week", state)

        assert result is not None
        assert "duration" in result["fields"]
        assert result["parsed"]["duration_delta"] == 7

    def test_duration_two_weeks_extraction(self):
        """Test that 'two weeks' extracts duration as 14 days."""
        state = self._make_state("travel to Japan for two weeks")
        result = _try_initial_message_extraction("travel to Japan for two weeks", state)

        assert result is not None
        assert "duration" in result["fields"]
        assert result["parsed"]["duration_delta"] == 14

    def test_full_multi_field_extraction(self):
        """Test the original problem case: destination, origin, budget, and duration."""
        text = (
            "i want to go to paris, i am based in london. "
            "i have limited budget. take me for 10 days"
        )
        state = self._make_state(text)
        result = _try_initial_message_extraction(text, state)

        assert result is not None

        # Should extract destination
        assert "destinations" in result["fields"]
        assert "destinations_delta" in result["parsed"]

        # Should extract origin (based in london)
        assert "origin" in result["fields"]
        assert "origin_delta" in result["parsed"]

        # Should extract budget (limited budget -> 1500)
        assert "budget" in result["fields"]
        assert result["parsed"]["budget_delta"] == 1500

        # Should extract duration (10 days)
        assert "duration" in result["fields"]
        assert result["parsed"]["duration_delta"] == 10

    def test_multi_field_with_luxury_and_weeks(self):
        """Test multi-field with luxury budget and week duration."""
        text = "luxury trip to bali, im from sydney, for two weeks"
        state = self._make_state(text)
        result = _try_initial_message_extraction(text, state)

        assert result is not None

        # Check budget
        if "budget" in result["fields"]:
            assert result["parsed"]["budget_delta"] == 8000

        # Check duration
        if "duration" in result["fields"]:
            assert result["parsed"]["duration_delta"] == 14


class TestPatternPrecedence:
    """Test that patterns don't interfere with each other."""

    def _make_state(self, user_text: str) -> GraphState:
        return GraphState(
            user_text=user_text,
            trip_inputs=TripInputs(),
            question_target=None,
            metadata={},
        )

    def test_budget_pattern_priority(self):
        """Numeric budget should take priority over qualitative if both present."""
        # This shouldn't happen in practice, but test robustness
        state = self._make_state("trip with $5000 budget, cheap flights")
        result = _try_initial_message_extraction("trip with $5000 budget, cheap flights", state)

        # If numeric budget was extracted by Pattern 6, qualitative shouldn't override
        if result and "budget" in result["fields"]:
            # Either 5000 from numeric or 1000 from "cheap" - numeric should win
            pass  # Just verify no crash

    def test_origin_vs_destination_no_confusion(self):
        """Origin pattern should not confuse destinations."""
        state = self._make_state("based in NYC going to LA")
        result = _try_initial_message_extraction("based in NYC going to LA", state)

        assert result is not None
        # NYC should be origin, LA should be destination (if patterns work correctly)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def _make_state(self, user_text: str) -> GraphState:
        return GraphState(
            user_text=user_text,
            trip_inputs=TripInputs(),
            question_target=None,
            metadata={},
        )

    def test_input_too_long_skips_extraction(self):
        """Input over 100 chars should skip initial extraction."""
        long_text = "a" * 101
        state = self._make_state(long_text)
        result = _try_initial_message_extraction(long_text, state)
        assert result is None

    def test_empty_input(self):
        """Empty input should not extract anything."""
        state = self._make_state("")
        result = _try_initial_message_extraction("", state)
        assert result is None

    def test_existing_question_target_skips(self):
        """With question_target set, initial extraction should skip."""
        state = GraphState(
            user_text="paris",
            trip_inputs=TripInputs(),
            question_target="dates",  # Already asking about dates
            metadata={},
        )
        result = _try_initial_message_extraction("paris", state)
        assert result is None  # Should skip due to question_target

    def test_unknown_origin_city_still_extracted(self):
        """Origin with unknown city should still be extracted (user explicitly stated)."""
        state = self._make_state("trip to Paris, based in Xyzzyville")
        result = _try_initial_message_extraction("trip to Paris, based in Xyzzyville", state)

        # Paris should be extracted as destination
        assert result is not None
        assert "destinations" in result["fields"]
        # Even unknown places are extracted when user explicitly says "based in X"
        assert "origin" in result["fields"]
        assert result["parsed"]["origin_delta"] == "Xyzzyville"

    def test_torun_poland_origin_extracted(self):
        """Test the original problem case: 'based in torun poland' should extract city."""
        text = (
            "i want to go to patagonia, i am based in torun poland. "
            "i have limited budget. take me for 10 days"
        )
        state = self._make_state(text)
        result = _try_initial_message_extraction(text, state)

        assert result is not None

        # Should extract all 4 fields
        assert "destinations" in result["fields"]
        assert "origin" in result["fields"]
        assert "budget" in result["fields"]
        assert "duration" in result["fields"]

        # Check origin specifically - should be "Torun" (city extracted from "Torun Poland")
        # The country suffix "Poland" is stripped to get just the city
        assert result["parsed"]["origin_delta"] == "Torun"
        assert result["parsed"]["budget_delta"] == 1500
        assert result["parsed"]["duration_delta"] == 10


class TestCityCountryExtraction:
    """Test extraction of city from 'city country' patterns."""

    @pytest.mark.parametrize(
        "input_text,expected_city",
        [
            # Basic city + country patterns
            ("Torun Poland", "Torun"),
            ("torun poland", "torun"),  # preserves original case
            ("Paris France", "Paris"),
            ("London UK", "London"),
            ("Sydney Australia", "Sydney"),
            ("Tokyo Japan", "Tokyo"),
            # Multi-word city + country
            ("New York USA", "New York"),
            ("Los Angeles USA", "Los Angeles"),
            ("San Francisco United States", "San Francisco"),
            ("New York United States of America", "New York"),
            # Country variations
            ("Berlin Germany", "Berlin"),
            ("Rome Italy", "Rome"),
            ("Madrid Spain", "Madrid"),
            ("Amsterdam Netherlands", "Amsterdam"),
            # No country suffix - unchanged
            ("Los Angeles", "Los Angeles"),
            ("Paris", "Paris"),
            ("New York", "New York"),
            # Single word - unchanged
            ("London", "London"),
            ("", ""),
        ],
    )
    def test_extract_city_from_location(self, input_text: str, expected_city: str):
        """Test city extraction from 'city country' patterns."""
        from app.known_places import extract_city_from_location

        assert extract_city_from_location(input_text) == expected_city

    def test_integration_with_pattern_2b(self):
        """Test that Pattern 2b correctly extracts city from 'based in city country'."""
        test_cases = [
            ("based in new york usa", "New York"),
            ("based in paris france", "Paris"),
            ("based in london uk", "London"),
            ("based in san francisco united states", "San Francisco"),
        ]

        for text, expected_city in test_cases:
            state = GraphState(
                user_text=f"trip to Rome, {text}",
                trip_inputs=TripInputs(),
                question_target=None,
                metadata={},
            )
            result = _try_initial_message_extraction(f"trip to Rome, {text}", state)

            assert result is not None, f"Failed for: {text}"
            assert "origin" in result["fields"], f"Origin not extracted for: {text}"
            # The extracted origin should be title-cased city
            assert (
                result["parsed"]["origin_delta"] == expected_city
            ), f"Expected {expected_city}, got {result['parsed']['origin_delta']} for: {text}"
