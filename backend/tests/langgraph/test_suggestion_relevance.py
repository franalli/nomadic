"""
Tests for prompt suggestion relevance scoring and filtering.

Tests include:
- Unit tests for _score_suggestion_relevance() function
- Suggestion filtering based on question_target
- Contextual fallback generation
- Integration tests with mock LLM responses
- Edge cases (empty suggestions, null question_target, etc.)
"""

# ruff: noqa: E402

import sys
from pathlib import Path
from typing import List, Optional

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.plan_graph import (
    _MIN_SUGGESTIONS_TO_SHOW,
    _SUGGESTION_RELEVANCE_THRESHOLD,
    QUESTION_TARGET_VALUES,
    GraphState,
    TripInputs,
    _filter_suggested_responses,
    _generate_contextual_suggestions,
    _get_suggestions_with_fallback,
    _is_low_quality_suggestion,
    _score_suggestion_relevance,
)

# =============================================================================
# Helper Functions
# =============================================================================


def create_test_state(
    user_text: str = "test",
    destinations: Optional[List[str]] = None,
    origin: Optional[str] = None,
    start_date: Optional[str] = None,
    chat_history: Optional[List[dict]] = None,
    user_intent: Optional[str] = None,
) -> GraphState:
    """Create a GraphState for testing."""
    ti = TripInputs(
        destinations=destinations or [],
        origin=origin,
        start_date=start_date,
    )
    metadata = {}
    if user_intent:
        metadata["user_intent_hint"] = user_intent
    return GraphState(
        user_text=user_text,
        trip_inputs=ti,
        chat_history=chat_history or [],
        metadata=metadata,
    )


def assert_suggestions_match_target(
    suggestions: List[str],
    question_target: str,
    min_passing: int = 2,
) -> None:
    """Assert that suggestions are relevant to the question_target."""
    if not suggestions:
        # Empty suggestions are acceptable (suppressed)
        return

    passing = 0
    for suggestion in suggestions:
        score = _score_suggestion_relevance(suggestion, question_target)
        if score >= _SUGGESTION_RELEVANCE_THRESHOLD:
            passing += 1

    assert passing >= min(min_passing, len(suggestions)), (
        f"Only {passing} of {len(suggestions)} suggestions match "
        f"question_target='{question_target}' with threshold {_SUGGESTION_RELEVANCE_THRESHOLD}"
    )


# =============================================================================
# Unit Tests for _score_suggestion_relevance
# =============================================================================


class TestScoreSuggestionRelevance:
    """Unit tests for the suggestion scoring function."""

    def test_origin_suggestions_with_from_prefix(self):
        """Suggestions with 'From X' should score high for origin questions."""
        assert _score_suggestion_relevance("From London", "origin") == 1.0
        assert _score_suggestion_relevance("From New York", "origin") == 1.0
        assert _score_suggestion_relevance("From Sydney", "origin") == 1.0

    def test_origin_suggestions_without_from_prefix(self):
        """City names without 'From' should score medium for origin questions."""
        score = _score_suggestion_relevance("London", "origin")
        assert 0.5 <= score <= 0.7

    def test_destination_suggestions_penalized_for_origin(self):
        """Destination-style suggestions should score low for origin questions."""
        score = _score_suggestion_relevance("Visit Paris", "origin")
        assert score < 0.5

    def test_destination_suggestions_with_location(self):
        """Place names should score high for destination questions."""
        assert _score_suggestion_relevance("Paris, France", "destinations") >= 0.9
        assert _score_suggestion_relevance("Bali, Indonesia", "destinations") >= 0.9
        assert _score_suggestion_relevance("The Maldives", "destinations") >= 0.7

    def test_destination_suggestions_from_prefix_penalized(self):
        """'From X' suggestions should score low for destination questions."""
        score = _score_suggestion_relevance("From London", "destinations")
        assert score < 0.3

    def test_date_suggestions(self):
        """Date-related suggestions should score high for date questions."""
        assert _score_suggestion_relevance("Next month", "dates") == 1.0
        assert _score_suggestion_relevance("December 15-22", "dates") >= 0.9
        assert _score_suggestion_relevance("In 2 weeks", "dates") == 1.0
        assert _score_suggestion_relevance("This December", "dates") == 1.0

    def test_non_date_suggestions_for_dates(self):
        """Non-date suggestions should score low for date questions."""
        score = _score_suggestion_relevance("Paris, France", "dates")
        assert score < 0.3

    def test_traveler_suggestions(self):
        """Traveler count suggestions should score high for traveler questions."""
        assert _score_suggestion_relevance("Just me", "travelers") == 1.0
        assert _score_suggestion_relevance("2 adults", "travelers") == 1.0
        assert _score_suggestion_relevance("Family of 4", "travelers") == 1.0

    def test_non_traveler_suggestions_for_travelers(self):
        """Non-traveler suggestions should score low for traveler questions."""
        score = _score_suggestion_relevance("Paris, France", "travelers")
        assert score < 0.3

    def test_budget_suggestions(self):
        """Budget suggestions should score high for budget questions."""
        assert _score_suggestion_relevance("$2000", "budget") == 1.0
        assert _score_suggestion_relevance("Mid-range budget", "budget") == 1.0
        assert _score_suggestion_relevance("Luxury trip", "budget") == 1.0

    def test_activity_suggestions(self):
        """Activity suggestions should score high for activity questions."""
        assert _score_suggestion_relevance("Hiking and trekking", "activities") == 1.0
        assert _score_suggestion_relevance("Beach activities", "activities") == 1.0
        assert _score_suggestion_relevance("Food and wine tours", "activities") == 1.0

    def test_general_target_accepts_most(self):
        """General question_target should accept most suggestions."""
        assert _score_suggestion_relevance("Paris, France", "general") >= 0.6
        assert _score_suggestion_relevance("From London", "general") >= 0.6
        assert _score_suggestion_relevance("Next month", "general") >= 0.6

    def test_null_question_target_accepts_all(self):
        """Without question_target, all suggestions should be accepted."""
        assert _score_suggestion_relevance("Paris, France", None) >= 0.7
        assert _score_suggestion_relevance("From London", None) >= 0.7
        assert _score_suggestion_relevance("Random text", None) >= 0.7

    def test_empty_suggestion(self):
        """Empty suggestions should score high (filtered elsewhere)."""
        assert _score_suggestion_relevance("", "destinations") >= 0.7


class TestScoringWithUserIntent:
    """Test that user intent affects destination scoring."""

    def test_adventure_destinations_boost(self):
        """Adventure destinations should score higher for adventurous intent."""
        score_with_intent = _score_suggestion_relevance(
            "Trek to Everest Base Camp", "destinations", user_intent="adventurous"
        )
        score_without_intent = _score_suggestion_relevance(
            "Trek to Everest Base Camp", "destinations", user_intent=None
        )
        # Adventure keywords should boost score
        assert score_with_intent >= score_without_intent


# =============================================================================
# Tests for _get_suggestions_with_fallback
# =============================================================================


class TestGetSuggestionsWithFallback:
    """Tests for the main suggestion filtering function."""

    def test_filters_mismatched_origin_suggestions_for_destination_question(self):
        """Origin suggestions should be filtered out when asking about destinations."""
        state = create_test_state()
        raw_suggestions = ["From Sydney", "From Los Angeles", "From London"]

        result = _get_suggestions_with_fallback(raw_suggestions, state, "destinations")

        # Should be suppressed or replaced with destination suggestions
        for suggestion in result:
            score = _score_suggestion_relevance(suggestion, "destinations")
            assert (
                score >= _SUGGESTION_RELEVANCE_THRESHOLD
            ), f"'{suggestion}' should not appear for destination question"

    def test_filters_mismatched_destination_suggestions_for_origin_question(self):
        """Destination suggestions should be filtered out when asking about origin."""
        state = create_test_state()
        raw_suggestions = ["Paris, France", "Bali, Indonesia", "Tokyo, Japan"]

        result = _get_suggestions_with_fallback(raw_suggestions, state, "origin")

        # Should be suppressed or replaced with origin suggestions
        for suggestion in result:
            score = _score_suggestion_relevance(suggestion, "origin")
            assert (
                score >= _SUGGESTION_RELEVANCE_THRESHOLD
            ), f"'{suggestion}' should not appear for origin question"

    def test_keeps_matching_suggestions(self):
        """Matching suggestions should be kept."""
        state = create_test_state()
        raw_suggestions = ["Paris, France", "Bali, Indonesia", "Tokyo, Japan"]

        result = _get_suggestions_with_fallback(raw_suggestions, state, "destinations")

        assert len(result) >= 2
        for suggestion in result:
            assert (
                _score_suggestion_relevance(suggestion, "destinations")
                >= _SUGGESTION_RELEVANCE_THRESHOLD
            )

    def test_suppresses_when_too_few_pass(self):
        """Should suppress all suggestions if fewer than MIN pass threshold."""
        state = create_test_state()
        # Mix of bad suggestions (origin for destination question)
        raw_suggestions = ["From London", "Maybe Paris"]  # Only 1 might pass

        result = _get_suggestions_with_fallback(raw_suggestions, state, "destinations")

        # Either empty or contextual fallbacks
        if result:
            assert_suggestions_match_target(result, "destinations")

    def test_uses_contextual_fallback_when_llm_empty(self):
        """Should use contextual fallback when LLM returns empty suggestions."""
        state = create_test_state(user_intent="adventurous")
        raw_suggestions = []

        result = _get_suggestions_with_fallback(raw_suggestions, state, "destinations")

        # Should get contextual adventure destinations
        assert len(result) >= 2

    def test_no_question_target_accepts_good_suggestions(self):
        """Without question_target, good suggestions should be accepted."""
        state = create_test_state()
        raw_suggestions = ["Paris, France", "Next month", "2 adults"]

        result = _get_suggestions_with_fallback(raw_suggestions, state, None)

        # All should be accepted as quality suggestions
        assert len(result) >= 2

    def test_limits_to_three_suggestions(self):
        """Should return at most 3 suggestions."""
        state = create_test_state()
        raw_suggestions = [
            "Paris, France",
            "Bali, Indonesia",
            "Tokyo, Japan",
            "Rome, Italy",
            "Barcelona, Spain",
        ]

        result = _get_suggestions_with_fallback(raw_suggestions, state, "destinations")

        assert len(result) <= 3


# =============================================================================
# Tests for _generate_contextual_suggestions
# =============================================================================


class TestGenerateContextualSuggestions:
    """Tests for contextual suggestion generation."""

    def test_generates_origin_suggestions(self):
        """Should generate origin suggestions with 'From' prefix."""
        state = create_test_state()
        result = _generate_contextual_suggestions(state, "origin")

        assert len(result) == 3
        for suggestion in result:
            assert suggestion.startswith("From ")

    def test_generates_destination_suggestions(self):
        """Should generate destination suggestions without 'From' prefix."""
        state = create_test_state()
        result = _generate_contextual_suggestions(state, "destinations")

        assert len(result) >= 2
        for suggestion in result:
            assert not suggestion.startswith("From ")

    def test_generates_adventure_destinations_for_intent(self):
        """Should generate adventure destinations for adventurous intent."""
        state = create_test_state(user_intent="adventurous")
        result = _generate_contextual_suggestions(state, "destinations")

        assert len(result) >= 2
        # Should include adventure-related destinations
        adventure_keywords = ["alps", "patagonia", "nepal", "zealand", "costa rica", "iceland"]
        has_adventure = any(any(kw in s.lower() for kw in adventure_keywords) for s in result)
        assert has_adventure, f"Expected adventure destinations, got: {result}"

    def test_generates_date_suggestions(self):
        """Should generate date suggestions."""
        state = create_test_state()
        result = _generate_contextual_suggestions(state, "dates")

        assert len(result) == 3
        date_keywords = ["month", "week", "december", "next", "in "]
        for suggestion in result:
            has_date_word = any(kw in suggestion.lower() for kw in date_keywords)
            assert has_date_word, f"'{suggestion}' doesn't look like a date"

    def test_generates_traveler_suggestions(self):
        """Should generate traveler suggestions."""
        state = create_test_state()
        result = _generate_contextual_suggestions(state, "travelers")

        assert len(result) == 3
        traveler_keywords = ["me", "adult", "family"]
        for suggestion in result:
            has_traveler_word = any(kw in suggestion.lower() for kw in traveler_keywords)
            assert has_traveler_word, f"'{suggestion}' doesn't look like traveler info"

    def test_returns_empty_for_no_question_target(self):
        """Should return empty list when no question_target is provided."""
        state = create_test_state()
        result = _generate_contextual_suggestions(state, None)

        assert result == []


# =============================================================================
# Integration Tests
# =============================================================================


class TestSuggestionIntegration:
    """Integration tests for the full suggestion flow."""

    def test_adventure_trip_gets_destination_suggestions(self):
        """Adventure trip asking for destination should get adventure destinations."""
        state = create_test_state(
            user_text="Plan an adventure trip with hiking",
            chat_history=[{"role": "user", "content": "Plan an adventure trip with hiking"}],
            user_intent="adventurous",
        )

        # Simulate LLM returning mismatched origin suggestions
        raw_suggestions = ["From Sydney", "From Los Angeles", "From London"]

        result = _get_suggestions_with_fallback(raw_suggestions, state, "destinations")

        # Should either be empty or contain destination suggestions
        if result:
            for suggestion in result:
                assert not suggestion.startswith(
                    "From "
                ), f"'{suggestion}' is an origin suggestion for destination question"

    def test_beach_trip_gets_beach_destinations(self):
        """Beach trip should get beach-related destinations."""
        state = create_test_state(
            user_text="I want a beach vacation",
            chat_history=[{"role": "user", "content": "I want a beach vacation"}],
        )

        result = _generate_contextual_suggestions(state, "destinations")

        # Should include beach destinations
        beach_keywords = ["bali", "maldives", "cancun", "phuket", "hawaii", "fiji"]
        has_beach = any(any(kw in s.lower() for kw in beach_keywords) for s in result)
        assert has_beach, f"Expected beach destinations, got: {result}"


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_raw_suggestions(self):
        """Empty raw suggestions should use contextual fallback."""
        state = create_test_state()
        result = _get_suggestions_with_fallback([], state, "destinations")

        assert len(result) >= 2

    def test_all_suggestions_filtered_out(self):
        """When all suggestions are filtered, should return contextual or empty."""
        state = create_test_state()
        # All low-quality suggestions
        raw_suggestions = ["?", "...", "a"]

        result = _get_suggestions_with_fallback(raw_suggestions, state, "destinations")

        # Should be contextual fallbacks or empty
        if result:
            assert_suggestions_match_target(result, "destinations")

    def test_mixed_quality_suggestions(self):
        """Should keep only high-quality matching suggestions."""
        state = create_test_state()
        raw_suggestions = [
            "Paris, France",  # Good destination
            "From London",  # Bad - origin for destination
            "Tokyo, Japan",  # Good destination
        ]

        result = _get_suggestions_with_fallback(raw_suggestions, state, "destinations")

        # Should have at least 2 (Paris and Tokyo)
        assert len(result) >= 2
        for suggestion in result:
            assert not suggestion.startswith("From ")

    def test_single_word_destinations_accepted(self):
        """Single-word destination names like Nepal, Bali, Peru should be accepted."""
        # These are valid destination suggestions that should NOT be filtered
        valid_single_words = ["Nepal", "Bali", "Peru", "Iceland", "Norway", "Fiji"]
        for word in valid_single_words:
            assert not _is_low_quality_suggestion(
                word
            ), f"'{word}' should be accepted as a valid destination"

    def test_single_word_destinations_in_filter(self):
        """Single-word destinations should pass through _filter_suggested_responses."""
        raw = ["Nepal", "Bali", "Peru"]
        result = _filter_suggested_responses(raw)
        assert len(result) == 3, f"Expected all 3, got {result}"
        assert "Nepal" in result
        assert "Bali" in result
        assert "Peru" in result

    def test_very_short_non_place_words_rejected(self):
        """Very short lowercase words should still be rejected."""
        assert _is_low_quality_suggestion("ok")
        assert _is_low_quality_suggestion("hi")
        assert _is_low_quality_suggestion("no")

    def test_question_target_values_constant(self):
        """Verify QUESTION_TARGET_VALUES contains expected values."""
        expected = {
            "destinations",
            "origin",
            "dates",
            "travelers",
            "budget",
            "activities",
            "general",
            None,
        }
        assert QUESTION_TARGET_VALUES == expected

    def test_threshold_constants(self):
        """Verify threshold constants are sensible."""
        assert 0.5 <= _SUGGESTION_RELEVANCE_THRESHOLD <= 0.9
        assert 1 <= _MIN_SUGGESTIONS_TO_SHOW <= 3


# =============================================================================
# Performance Tests (optional - can be skipped in CI)
# =============================================================================


class TestSuggestionPerformance:
    """Performance-related tests."""

    def test_scoring_is_fast(self):
        """Scoring should be fast enough for real-time use."""
        import time

        suggestions = ["Paris, France", "From London", "Next month"] * 100

        start = time.perf_counter()
        for suggestion in suggestions:
            _score_suggestion_relevance(suggestion, "destinations")
        elapsed = time.perf_counter() - start

        # Should complete in under 100ms for 300 suggestions
        assert elapsed < 0.1, f"Scoring took {elapsed:.3f}s for {len(suggestions)} suggestions"
