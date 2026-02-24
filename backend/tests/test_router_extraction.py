# backend/tests/test_router_extraction.py
"""
Unit tests for router_extraction.py.

This file covers:
- _parse_day_preferences: JSON day-count parsing with hallucination guard
- _clamp_date_str: YYYY-MM-DD clamping to valid month end
- RouterOutput: Pydantic schema validation and defaults
- IntentClassification: Pydantic schema validation and defaults
- _build_specialist_keyword_prompt: specialist keyword prompt construction
"""

import pytest
from pydantic import ValidationError

from app.planner.nodes.router_extraction import (
    IntentClassification,
    RouterOutput,
    _build_specialist_keyword_prompt,
    _clamp_date_str,
    _parse_day_preferences,
)

# =============================================================================
# _parse_day_preferences
# =============================================================================


class TestParseDayPreferences:
    """Parses JSON day counts with hallucination guard (requires digits in user_text)."""

    def test_none_raw_returns_empty(self) -> None:
        result = _parse_day_preferences(None, "I want to go diving")
        assert result == {}

    def test_empty_string_raw_returns_empty(self) -> None:
        result = _parse_day_preferences("", "3 days diving")
        assert result == {}

    def test_no_digits_in_user_text_returns_empty(self) -> None:
        """Hallucination guard: LLM invented day counts user never stated."""
        result = _parse_day_preferences('{"diving": 3}', "I want to go diving in Bali")
        assert result == {}

    def test_parses_valid_json_with_digits_in_text(self) -> None:
        result = _parse_day_preferences('{"diving": 3, "hiking": 2}', "3 days diving and 2 hiking")
        assert result == {"diving": 3, "hiking": 2}

    def test_keys_are_lowercased(self) -> None:
        result = _parse_day_preferences('{"Diving": 3, "HIKING": 2}', "3 days Diving")
        assert "diving" in result
        assert "hiking" in result
        assert "Diving" not in result
        assert "HIKING" not in result

    def test_keys_are_stripped(self) -> None:
        result = _parse_day_preferences('{" diving ": 3}', "3 days diving")
        assert "diving" in result

    def test_invalid_json_returns_empty(self) -> None:
        result = _parse_day_preferences("not-valid-json", "3 days diving")
        assert result == {}

    def test_invalid_json_curly_returns_empty(self) -> None:
        result = _parse_day_preferences("{diving: 3}", "3 days diving")
        assert result == {}

    def test_single_activity_with_digit(self) -> None:
        result = _parse_day_preferences('{"surfing": 5}', "5 days of surfing")
        assert result == {"surfing": 5}

    def test_empty_user_text_bypasses_digit_guard(self) -> None:
        """Empty user_text is falsy: 'user_text and ...' short-circuits to False.
        The guard is not triggered, so valid JSON is parsed normally."""
        result = _parse_day_preferences('{"diving": 3}', "")
        assert result == {"diving": 3}

    def test_digit_in_user_text_allows_parse(self) -> None:
        """A single digit anywhere in user_text satisfies the guard."""
        result = _parse_day_preferences('{"yoga": 1}', "at least 1 session of yoga")
        assert result == {"yoga": 1}

    def test_non_dict_json_returns_empty(self) -> None:
        """JSON array is not a dict — returns {}."""
        result = _parse_day_preferences("[3, 2]", "3 days diving")
        assert result == {}

    def test_value_coerced_to_int(self) -> None:
        """Values must be cast to int; floats should work if int()-able."""
        result = _parse_day_preferences('{"diving": 3}', "3 days")
        assert result["diving"] == 3
        assert isinstance(result["diving"], int)

    def test_float_json_value_coerced_to_int(self) -> None:
        """LLM may emit float JSON values (3.0); int() coercion must handle them."""
        result = _parse_day_preferences('{"diving": 3.0}', "3 days")
        assert result["diving"] == 3
        assert isinstance(result["diving"], int)


# =============================================================================
# _clamp_date_str
# =============================================================================


class TestClampDateStr:
    """YYYY-MM-DD clamping: valid dates pass through, overflow days are clamped."""

    def test_valid_date_passes_through(self) -> None:
        assert _clamp_date_str("2026-03-15") == "2026-03-15"

    def test_valid_date_start_of_month(self) -> None:
        assert _clamp_date_str("2026-01-01") == "2026-01-01"

    def test_valid_date_end_of_month(self) -> None:
        assert _clamp_date_str("2026-01-31") == "2026-01-31"

    def test_feb_30_clamped_to_feb_28_non_leap(self) -> None:
        """2026 is not a leap year — Feb 30 → Feb 28."""
        result = _clamp_date_str("2026-02-30")
        assert result == "2026-02-28"

    def test_feb_29_clamped_on_non_leap_year(self) -> None:
        """2026 is not a leap year — Feb 29 → Feb 28."""
        result = _clamp_date_str("2026-02-29")
        assert result == "2026-02-28"

    def test_feb_29_valid_on_leap_year(self) -> None:
        """2024 is a leap year — Feb 29 is valid and passes through."""
        result = _clamp_date_str("2024-02-29")
        assert result == "2024-02-29"

    def test_apr_31_clamped_to_apr_30(self) -> None:
        """April has 30 days."""
        result = _clamp_date_str("2026-04-31")
        assert result == "2026-04-30"

    def test_completely_invalid_string_returns_none(self) -> None:
        assert _clamp_date_str("not-a-date") is None

    def test_invalid_month_returns_none(self) -> None:
        """Month 13 is out of range — returns None."""
        assert _clamp_date_str("2026-13-01") is None

    def test_invalid_month_zero_returns_none(self) -> None:
        assert _clamp_date_str("2026-00-15") is None

    def test_non_date_format_returns_none(self) -> None:
        assert _clamp_date_str("2026/03/15") is None

    def test_partial_date_returns_none(self) -> None:
        assert _clamp_date_str("2026-03") is None

    def test_clamped_value_preserved_exactly(self) -> None:
        """Clamped result has correct zero-padding."""
        result = _clamp_date_str("2026-06-31")
        # June has 30 days
        assert result == "2026-06-30"


# =============================================================================
# RouterOutput schema
# =============================================================================


class TestRouterOutputSchema:
    """Pydantic schema validation for RouterOutput — the combined intent+extraction model."""

    def test_minimal_valid_instance(self) -> None:
        obj = RouterOutput(intent="PLANNING", confidence=0.9, reasoning="User wants to plan a trip")
        assert obj.intent == "PLANNING"
        assert obj.confidence == 0.9
        assert obj.reasoning == "User wants to plan a trip"

    def test_specialist_hints_defaults_to_empty_list(self) -> None:
        obj = RouterOutput(intent="GREETING", confidence=1.0, reasoning="hi")
        assert obj.specialist_hints == []

    def test_activity_categories_defaults_to_empty_list(self) -> None:
        obj = RouterOutput(intent="PLANNING", confidence=0.8, reasoning="planning")
        assert obj.activity_categories == []

    def test_multi_destination_detected_defaults_to_false(self) -> None:
        obj = RouterOutput(intent="PLANNING", confidence=0.8, reasoning="planning")
        assert obj.multi_destination_detected is False

    def test_reset_budget_defaults_to_false(self) -> None:
        obj = RouterOutput(intent="PLANNING", confidence=0.8, reasoning="planning")
        assert obj.reset_budget is False

    def test_has_dates_in_message_defaults_to_false(self) -> None:
        obj = RouterOutput(intent="PLANNING", confidence=0.8, reasoning="planning")
        assert obj.has_dates_in_message is False

    def test_has_activity_in_message_defaults_to_false(self) -> None:
        obj = RouterOutput(intent="PLANNING", confidence=0.8, reasoning="planning")
        assert obj.has_activity_in_message is False

    def test_planning_ready_defaults_to_false(self) -> None:
        obj = RouterOutput(intent="PLANNING", confidence=0.8, reasoning="planning")
        assert obj.planning_ready is False

    def test_confidence_at_zero_is_valid(self) -> None:
        obj = RouterOutput(intent="GREETING", confidence=0.0, reasoning="unsure")
        assert obj.confidence == 0.0

    def test_confidence_at_one_is_valid(self) -> None:
        obj = RouterOutput(intent="GREETING", confidence=1.0, reasoning="certain")
        assert obj.confidence == 1.0

    def test_confidence_above_one_raises(self) -> None:
        with pytest.raises(ValidationError):
            RouterOutput(intent="PLANNING", confidence=1.1, reasoning="r")

    def test_confidence_below_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            RouterOutput(intent="PLANNING", confidence=-0.1, reasoning="r")

    def test_invalid_intent_raises(self) -> None:
        with pytest.raises(ValidationError):
            RouterOutput(intent="UNKNOWN", confidence=0.8, reasoning="r")

    def test_greeting_intent_valid(self) -> None:
        obj = RouterOutput(intent="GREETING", confidence=1.0, reasoning="hi")
        assert obj.intent == "GREETING"

    def test_reset_intent_valid(self) -> None:
        obj = RouterOutput(intent="RESET", confidence=0.95, reasoning="start over")
        assert obj.intent == "RESET"

    def test_optional_fields_default_to_none(self) -> None:
        obj = RouterOutput(intent="PLANNING", confidence=0.8, reasoning="planning")
        assert obj.destination is None
        assert obj.origin is None
        assert obj.start_date is None
        assert obj.end_date is None
        assert obj.adults is None
        assert obj.children is None
        assert obj.budget is None

    def test_specialist_hints_populated(self) -> None:
        obj = RouterOutput(
            intent="PLANNING",
            confidence=0.9,
            reasoning="diving trip",
            specialist_hints=["diving", "hiking"],
        )
        assert obj.specialist_hints == ["diving", "hiking"]

    def test_activity_categories_populated(self) -> None:
        obj = RouterOutput(
            intent="PLANNING",
            confidence=0.9,
            reasoning="r",
            activity_categories=["yoga", "nightlife"],
        )
        assert obj.activity_categories == ["yoga", "nightlife"]

    def test_removal_targets_defaults_to_empty_list(self) -> None:
        obj = RouterOutput(intent="PLANNING", confidence=0.8, reasoning="r")
        assert obj.removal_targets == []

    def test_hotel_amenities_defaults_to_empty_list(self) -> None:
        obj = RouterOutput(intent="PLANNING", confidence=0.8, reasoning="r")
        assert obj.hotel_amenities == []

    def test_date_auto_adjustments_defaults_to_empty_list(self) -> None:
        obj = RouterOutput(intent="PLANNING", confidence=0.8, reasoning="r")
        assert obj.date_auto_adjustments == []


# =============================================================================
# IntentClassification schema
# =============================================================================


class TestIntentClassificationSchema:
    """Pydantic schema for the lighter intent-only classification output."""

    def test_greeting_intent_valid(self) -> None:
        obj = IntentClassification(intent="GREETING", confidence=1.0, reasoning="user said hi")
        assert obj.intent == "GREETING"

    def test_reset_intent_valid(self) -> None:
        obj = IntentClassification(intent="RESET", confidence=0.95, reasoning="start over")
        assert obj.intent == "RESET"

    def test_planning_intent_valid(self) -> None:
        obj = IntentClassification(intent="PLANNING", confidence=0.85, reasoning="wants trip")
        assert obj.intent == "PLANNING"

    def test_invalid_intent_raises(self) -> None:
        with pytest.raises(ValidationError):
            IntentClassification(intent="BOOKING", confidence=0.8, reasoning="r")

    def test_specialist_hints_defaults_to_empty_list(self) -> None:
        obj = IntentClassification(intent="GREETING", confidence=1.0, reasoning="hi")
        assert obj.specialist_hints == []

    def test_specialist_hints_populated(self) -> None:
        obj = IntentClassification(
            intent="PLANNING",
            confidence=0.9,
            reasoning="diving",
            specialist_hints=["diving"],
        )
        assert obj.specialist_hints == ["diving"]

    def test_confidence_bounds_enforced(self) -> None:
        with pytest.raises(ValidationError):
            IntentClassification(intent="PLANNING", confidence=1.5, reasoning="r")

    def test_confidence_default_applied(self) -> None:
        """Default confidence of 0.8 when not provided."""
        obj = IntentClassification(intent="PLANNING", reasoning="r")
        assert obj.confidence == 0.8


# =============================================================================
# _build_specialist_keyword_prompt
# =============================================================================


class TestBuildSpecialistKeywordPrompt:
    """Validates the specialist keyword prompt fragment is coherent."""

    def test_returns_non_empty_string(self) -> None:
        result = _build_specialist_keyword_prompt()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_specialist_keywords(self) -> None:
        """Prompt must include at least some known domain keywords."""
        result = _build_specialist_keyword_prompt()
        # Each line should have the -> arrow mapping format
        assert "->" in result

    def test_each_line_has_topic_mapping(self) -> None:
        """Every line should follow '- "alias" -> "topic"' format."""
        result = _build_specialist_keyword_prompt()
        lines = [line for line in result.splitlines() if line.strip()]
        assert len(lines) > 0
        for line in lines:
            assert line.startswith("- ")
            assert "->" in line

    def test_result_is_deterministic(self) -> None:
        """Two calls must return the same string (sorted, stable)."""
        first = _build_specialist_keyword_prompt()
        second = _build_specialist_keyword_prompt()
        assert first == second

    def test_contains_quoted_keywords(self) -> None:
        """Keywords in the prompt should be double-quoted."""
        result = _build_specialist_keyword_prompt()
        assert '"' in result

    def test_contains_known_tier1_keyword(self) -> None:
        """'diving' is a known Tier 1 specialist — catches registry import regressions."""
        result = _build_specialist_keyword_prompt()
        assert "diving" in result
