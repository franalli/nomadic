"""
Tests for the MVP deterministic parsing pipeline.

This pipeline runs BEFORE extractor LLM to parse simple answers like:
- Suggestion echo (user clicks a suggestion)
- Season/month dates ("next summer", "December")
- Relative dates ("next month", "next week")
- Travelers ("solo", "couple", "family of 4")
- Single known places ("Patagonia")
- Multi-place ("Paris and Rome")

Key invariants:
1. Deterministic hits set parse_provenance = "deterministic"
2. lqa_reason reflects parse type (e.g., "deterministic:suggestion_echo")
3. Date ambiguity sets date_clarify_mode instead of returning deltas
4. Multi-place split only fires when separator AND ≥1 known place
5. Pipeline order: suggestion echo → date → travelers → place
"""

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

# Import the functions we're testing
from app.plan_graph import (
    GraphState,
    TripInputs,
    _normalize_suggestion_text,
    _run_deterministic_pipeline,
    _try_place_parse,
    _try_season_date_parse,
    _try_suggestion_echo,
    _try_travelers_micro_parse,
    get_deterministic_pipeline_stats,
    store_suggestions_with_field,
)


def _make_state(
    question_target: str | None = None,
    last_suggestions: list | None = None,
    today_iso: str | None = None,
) -> GraphState:
    """Helper to create GraphState for tests."""
    state = GraphState(user_text="", trip_inputs=TripInputs())
    if question_target:
        state.question_target = question_target
    if last_suggestions is not None:
        state.metadata["last_suggestions"] = last_suggestions
    if today_iso:
        state.metadata["today_iso"] = today_iso
    return state


class TestSuggestionEcho:
    """Tests for suggestion echo matching."""

    def test_exact_match_returns_delta(self):
        """Suggestion echo returns delta on exact match."""
        state = _make_state(last_suggestions=[{"text": "Paris", "field": "destinations"}])
        state.metadata["suggestion_clicked"] = "Paris"  # Required signal
        result = _try_suggestion_echo("Paris", state)
        assert result is not None
        assert result["destinations_delta"] == ["Paris"]
        assert result["lqa_reason"] == "deterministic:suggestion_echo"

    def test_normalized_match_returns_delta(self):
        """Suggestion echo matches with normalized text (trim, collapse spaces, casefold)."""
        state = _make_state(last_suggestions=[{"text": "New York City", "field": "destinations"}])
        state.metadata["suggestion_clicked"] = "  new  york  city  "  # Must match text being passed
        # Different casing and extra spaces
        result = _try_suggestion_echo("  new  york  city  ", state)
        assert result is not None
        assert result["destinations_delta"] == ["New York City"]

    def test_no_match_returns_none(self):
        """Suggestion echo returns None when no match."""
        state = _make_state(last_suggestions=[{"text": "Paris", "field": "destinations"}])
        result = _try_suggestion_echo("Tokyo", state)
        assert result is None

    def test_empty_suggestions_returns_none(self):
        """Suggestion echo returns None when no suggestions."""
        state = _make_state(last_suggestions=[])
        result = _try_suggestion_echo("Paris", state)
        assert result is None

    def test_origin_field_suggestion(self):
        """Suggestion echo sets origin_delta for origin field."""
        state = _make_state(last_suggestions=[{"text": "London", "field": "origin"}])
        state.metadata["suggestion_clicked"] = "London"  # Required signal
        result = _try_suggestion_echo("London", state)
        assert result is not None
        assert result["origin_delta"] == "London"
        assert "destinations_delta" not in result

    def test_dates_field_suggestion(self):
        """Suggestion echo parses dates suggestion."""
        state = _make_state(
            last_suggestions=[{"text": "2025-03-15", "field": "dates"}],
            today_iso="2025-01-15",
        )
        state.metadata["suggestion_clicked"] = "2025-03-15"  # Required signal
        result = _try_suggestion_echo("2025-03-15", state)
        assert result is not None
        assert result.get("start_date_delta") == "2025-03-15"


class TestSeasonDateParse:
    """Tests for season/relative date parsing."""

    @pytest.fixture
    def state_january(self):
        """State with reference date in January 2025."""
        return _make_state(question_target="dates", today_iso="2025-01-15")

    def test_next_month_parse(self, state_january):
        """'next month' parses to next calendar month range."""
        result = _try_season_date_parse("next month", state_january)
        assert result is not None
        assert result["start_date_delta"] == "2025-02-01"
        assert result["end_date_delta"] == "2025-02-28"
        assert result["lqa_reason"] == "deterministic:date_answer"

    def test_next_week_parse(self, state_january):
        """'next week' parses to next Monday-Sunday range."""
        result = _try_season_date_parse("next week", state_january)
        assert result is not None
        # Should be next Monday (Jan 20) to Sunday (Jan 26)
        assert result["start_date_delta"] == "2025-01-20"
        assert result["end_date_delta"] == "2025-01-26"

    def test_this_weekend_parse(self, state_january):
        """'this weekend' parses to upcoming Saturday-Sunday."""
        result = _try_season_date_parse("this weekend", state_january)
        assert result is not None
        # Jan 15 2025 is Wednesday, so weekend is Jan 18-19
        assert "start_date_delta" in result
        assert "end_date_delta" in result

    def test_summer_parse(self, state_january):
        """'summer' parses to June-August range."""
        result = _try_season_date_parse("summer", state_january)
        assert result is not None
        assert result["start_date_delta"] == "2025-06-01"
        assert result["end_date_delta"] == "2025-08-31"
        assert result.get("_season_hemisphere_assumed") == "north"

    def test_next_summer_parse(self, state_january):
        """'next summer' parses to next year's summer if current summer is upcoming."""
        result = _try_season_date_parse("next summer", state_january)
        assert result is not None
        # In Jan 2025, "next summer" should be 2026
        assert result["start_date_delta"].startswith("2026")

    def test_winter_cross_year(self, state_january):
        """Winter season crosses year boundary (Dec-Feb)."""
        result = _try_season_date_parse("winter", state_january)
        assert result is not None
        # In January, we're IN winter, so should be current winter
        assert "start_date_delta" in result
        assert "end_date_delta" in result

    def test_spring_parse(self, state_january):
        """'spring' parses correctly."""
        result = _try_season_date_parse("spring", state_january)
        assert result is not None
        assert result["start_date_delta"] == "2025-03-15"
        assert result["end_date_delta"] == "2025-05-31"

    def test_non_date_text_returns_none(self, state_january):
        """Non-date text returns None."""
        result = _try_season_date_parse("Patagonia", state_january)
        assert result is None


class TestTravelersMicroParse:
    """Tests for travelers micro-parser."""

    def test_solo_variations(self):
        """'solo', 'just me', 'alone' all parse to adults=1."""
        for text in ["solo", "just me", "only me", "alone", "by myself"]:
            result = _try_travelers_micro_parse(text)
            assert result is not None, f"Failed for: {text}"
            assert result["adults_delta"] == 1
            assert result["lqa_reason"] == "deterministic:travelers_answer"

    def test_couple_variations(self):
        """'couple', '2 of us' parse to adults=2."""
        for text in ["couple", "2 of us", "two of us", "me and my partner"]:
            result = _try_travelers_micro_parse(text)
            assert result is not None, f"Failed for: {text}"
            assert result["adults_delta"] == 2

    def test_family_of_n(self):
        """'family of N' splits into adults and children."""
        result = _try_travelers_micro_parse("family of 4")
        assert result is not None
        assert result["adults_delta"] == 2
        assert result["children_delta"] == 2

        result = _try_travelers_micro_parse("family of 5")
        assert result is not None
        assert result["adults_delta"] == 2
        assert result["children_delta"] == 3

    def test_group_count(self):
        """'N people/adults' parses to adults=N."""
        result = _try_travelers_micro_parse("3 people")
        assert result is not None
        assert result["adults_delta"] == 3

        result = _try_travelers_micro_parse("4 adults")
        assert result is not None
        assert result["adults_delta"] == 4

    def test_invalid_traveler_text(self):
        """Non-traveler text returns None."""
        result = _try_travelers_micro_parse("Paris")
        assert result is None

        result = _try_travelers_micro_parse("next week")
        assert result is None


class TestPlaceParse:
    """Tests for place parsing."""

    def test_single_known_place(self):
        """Single known place parses to destinations_delta."""
        state = _make_state(question_target="destinations")
        result = _try_place_parse("Paris", state, "destinations")
        assert result is not None
        assert "destinations_delta" in result
        assert result["lqa_reason"] == "deterministic:place_answer"

    def test_origin_question_target(self):
        """Origin question_target sets origin_delta instead."""
        state = _make_state(question_target="origin")
        result = _try_place_parse("London", state, "origin")
        assert result is not None
        assert "origin_delta" in result
        assert "destinations_delta" not in result

    def test_multi_place_with_and(self):
        """'Paris and Rome' splits into multiple destinations."""
        state = _make_state(question_target="destinations")
        result = _try_place_parse("Paris and Rome", state, "destinations")
        assert result is not None
        assert len(result.get("destinations_delta", [])) == 2
        assert result.get("_multi_city_signal") is True

    def test_multi_place_with_comma(self):
        """'Paris, Tokyo, Rome' splits into multiple destinations."""
        state = _make_state(question_target="destinations")
        result = _try_place_parse("Paris, Tokyo, Rome", state, "destinations")
        assert result is not None
        # Capped at 3
        assert len(result.get("destinations_delta", [])) <= 3

    def test_no_split_without_known_place(self):
        """Multi-split requires at least one known place."""
        state = _make_state(question_target="destinations")
        # Random words with separator
        result = _try_place_parse("foo and bar", state, "destinations")
        # Should not split or should return None
        assert result is None or len(result.get("destinations_delta", [])) == 0

    def test_sentence_not_parsed_as_place(self):
        """Text with verbs is rejected (it's a sentence, not a place)."""
        state = _make_state(question_target="destinations")
        result = _try_place_parse("I want to go to Paris", state, "destinations")
        assert result is None

    def test_greeting_not_parsed_as_place(self):
        """Greetings are rejected despite capitalization."""
        state = _make_state(question_target="destinations")
        result = _try_place_parse("Hello", state, "destinations")
        assert result is None


class TestDeterministicPipeline:
    """Tests for the full deterministic pipeline."""

    def test_suggestion_echo_takes_priority(self):
        """Suggestion echo runs before other parsers."""
        state = _make_state(
            question_target="dates",
            last_suggestions=[{"text": "Tokyo", "field": "destinations"}],
        )
        state.metadata["suggestion_clicked"] = "Tokyo"  # Required signal
        # Even though question_target is dates, suggestion echo should match
        result = _run_deterministic_pipeline("Tokyo", state)
        assert result is not None
        assert "destinations_delta" in result
        assert result["lqa_reason"] == "deterministic:suggestion_echo"

    def test_date_parser_for_dates_target(self):
        """Date parser runs when question_target is dates."""
        state = _make_state(question_target="dates", today_iso="2025-01-15")
        result = _run_deterministic_pipeline("next month", state)
        assert result is not None
        assert "start_date_delta" in result
        assert "end_date_delta" in result

    def test_travelers_parser_for_travelers_target(self):
        """Travelers parser runs when question_target is travelers."""
        state = _make_state(question_target="travelers")
        result = _run_deterministic_pipeline("just me", state)
        assert result is not None
        assert result["adults_delta"] == 1

    def test_place_parser_for_destinations_target(self):
        """Place parser runs when question_target is destinations."""
        state = _make_state(question_target="destinations")
        result = _run_deterministic_pipeline("Paris", state)
        assert result is not None
        assert "destinations_delta" in result

    def test_off_target_place_answer(self):
        """Place given when asked for dates: pipeline returns None (lets LQA bail)."""
        # When asking for dates but user gives a place name, the deterministic
        # pipeline should NOT parse it. Instead, it returns None and lets the
        # existing LQA "not_date_like" bail logic handle it.
        state = _make_state(question_target="dates")
        result = _run_deterministic_pipeline("Paris", state)
        assert result is None

    def test_no_context_returns_none(self):
        """Pipeline returns None when no question_target and no suggestions."""
        state = _make_state(question_target=None, last_suggestions=None)
        result = _run_deterministic_pipeline("Paris", state)
        assert result is None


class TestStoreSuggestionsWithField:
    """Tests for suggestion channel storage."""

    def test_stores_suggestions_with_field(self):
        """Suggestions are stored with field info."""
        state = _make_state()
        store_suggestions_with_field(state, ["Paris", "Tokyo"], "destinations")

        last_suggestions = state.metadata.get("last_suggestions", [])
        assert len(last_suggestions) == 2
        assert last_suggestions[0] == {"text": "Paris", "field": "destinations"}
        assert last_suggestions[1] == {"text": "Tokyo", "field": "destinations"}

    def test_filters_empty_suggestions(self):
        """Empty strings are filtered out."""
        state = _make_state()
        store_suggestions_with_field(state, ["Paris", "", "  ", "Tokyo"], "destinations")

        last_suggestions = state.metadata.get("last_suggestions", [])
        assert len(last_suggestions) == 2

    def test_empty_list_clears_suggestions(self):
        """Empty list clears existing suggestions."""
        state = _make_state()
        state.metadata["last_suggestions"] = [{"text": "Old", "field": "old"}]
        store_suggestions_with_field(state, [], "destinations")

        assert state.metadata["last_suggestions"] == []


class TestNormalizeSuggestionText:
    """Tests for suggestion text normalization."""

    def test_trim_whitespace(self):
        """Trims leading and trailing whitespace."""
        assert _normalize_suggestion_text("  Paris  ") == "paris"

    def test_collapse_spaces(self):
        """Collapses multiple spaces."""
        assert _normalize_suggestion_text("New   York   City") == "new york city"

    def test_casefold(self):
        """Converts to lowercase for comparison."""
        assert _normalize_suggestion_text("PARIS") == "paris"

    def test_combined_normalization(self):
        """Handles combined normalization."""
        assert _normalize_suggestion_text("  NEW   YORK  ") == "new york"


class TestDeterministicPipelineStats:
    """Tests for stats and observability."""

    def test_stats_function_returns_dict(self):
        """get_deterministic_pipeline_stats returns expected keys."""
        stats = get_deterministic_pipeline_stats()
        assert "suggestion_echo_hits" in stats
        assert "season_date_hits" in stats
        assert "relative_date_hits" in stats
        assert "travelers_hits" in stats
        assert "place_single_hits" in stats
        assert "place_multi_hits" in stats
        assert "total_hits" in stats

    def test_total_hits_is_sum(self):
        """total_hits is sum of individual hit counters."""
        stats = get_deterministic_pipeline_stats()
        expected_total = sum(
            [
                stats["suggestion_echo_hits"],
                stats["season_date_hits"],
                stats["relative_date_hits"],
                stats["travelers_hits"],
                stats["place_single_hits"],
                stats["place_multi_hits"],
            ]
        )
        assert stats["total_hits"] == expected_total
