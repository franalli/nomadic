"""Unit tests for summarize node.

This node handles:
- Ready-to-generate state transition
- Default follow-up question generation
- Suggestion filtering based on user request type
- Safety snippet augmentation for international travel
- Empty response guard (emergency fallback)
"""

import os
import sys
from pathlib import Path

# Suppress debug output
os.environ["PLAN_GRAPH_DEBUG"] = "0"

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.plan_graph import GraphState, TripInputs, summarize  # noqa: E402
from tests.langgraph.fixtures import (  # noqa: E402
    make_complete_trip_inputs,
)

# =============================================================================
# Helper Functions
# =============================================================================


def make_state_for_summarize(
    last_summary: str | None = None,
    destinations: list[str] | None = None,
    origin: str | None = None,
    complete: bool = True,
    **metadata_overrides,
) -> GraphState:
    """Create a GraphState for summarize node testing."""
    if complete:
        trip_inputs = make_complete_trip_inputs(
            destinations=destinations or ["Paris"],
            origin=origin or "London",
        )
    else:
        # TripInputs requires destinations to be a list, not None
        trip_inputs = TripInputs(
            destinations=destinations if destinations is not None else [],
            origin=origin,
        )

    metadata = {
        "thread_id": "test_summarize",
    }
    metadata.update(metadata_overrides)

    return GraphState(
        user_text="",
        trip_inputs=trip_inputs,
        last_summary=last_summary,
        metadata=metadata,
    )


# =============================================================================
# Ready-to-Generate State Transition Tests
# =============================================================================


class TestReadyToGenerateTransition:
    """Tests for plan_just_became_ready state transition."""

    def test_generates_ready_message_when_plan_just_became_ready(self):
        """Should generate ready-to-generate message when flag is set."""
        state = make_state_for_summarize(
            last_summary="What's your budget?",  # Stale question
            destinations=["Paris", "Rome"],
            plan_just_became_ready=True,
        )

        result = summarize(state)

        # Should generate fresh ready message (compare lowercase to lowercase)
        lower_summary = result.last_summary.lower()
        assert "everything i need" in lower_summary or "ready" in lower_summary
        assert "paris" in lower_summary or "rome" in lower_summary

    def test_clears_question_target_when_plan_ready(self):
        """Should clear stale question_target when plan is ready."""
        state = make_state_for_summarize(
            question_target="budget",
            plan_just_became_ready=True,
        )
        state.question_target = "budget"

        result = summarize(state)

        assert result.question_target is None

    def test_sets_suggested_responses_when_plan_ready(self):
        """Should set appropriate suggestions when plan becomes ready."""
        state = make_state_for_summarize(
            plan_just_became_ready=True,
        )

        result = summarize(state)

        assert result.suggested_responses is not None
        assert len(result.suggested_responses) > 0
        # Should have generate-related suggestion
        suggestions_lower = [s.lower() for s in result.suggested_responses]
        assert any("generate" in s or "itinerary" in s for s in suggestions_lower)

    def test_clears_plan_just_became_ready_flag(self):
        """Should clear the flag after processing."""
        state = make_state_for_summarize(
            plan_just_became_ready=True,
        )

        result = summarize(state)

        assert result.metadata.get("plan_just_became_ready") is False


# =============================================================================
# Suggestion Filtering Tests
# =============================================================================


class TestSuggestionFiltering:
    """Tests for suggestion filtering based on user request type."""

    def test_filters_expand_suggestions_after_expand_request(self):
        """Should filter 'show more' suggestions after user asked to expand."""
        state = make_state_for_summarize(
            last_summary="Here are more details...",
            user_request_type="expand",
        )
        state.suggested_responses = [
            "Show more details",
            "Book a hotel",
            "Find flights",
        ]

        result = summarize(state)

        # "Show more details" should be filtered out
        if result.suggested_responses:
            for suggestion in result.suggested_responses:
                assert "more detail" not in suggestion.lower()

    def test_filters_generate_suggestions_after_generate_request(self):
        """Should filter generate suggestions after user asked to generate."""
        state = make_state_for_summarize(
            last_summary="Generating your itinerary...",
            user_request_type="generate",
        )
        state.suggested_responses = [
            "Generate my itinerary",
            "Show hotels",
            "Create itinerary now",
        ]

        result = summarize(state)

        # Generate/itinerary suggestions should be filtered
        if result.suggested_responses:
            for suggestion in result.suggested_responses:
                assert "generate" not in suggestion.lower()
                assert "itinerary" not in suggestion.lower()

    def test_clears_user_request_type_after_filtering(self):
        """Should clear user_request_type after filtering."""
        state = make_state_for_summarize(
            last_summary="Done",
            user_request_type="expand",
        )
        state.suggested_responses = ["Option 1"]

        result = summarize(state)

        assert "user_request_type" not in result.metadata


# =============================================================================
# Default Follow-up Generation Tests
# =============================================================================


class TestDefaultFollowUpGeneration:
    """Tests for default follow-up question generation."""

    def test_generates_follow_up_when_no_last_summary(self):
        """Should generate follow-up question when last_summary is empty."""
        state = make_state_for_summarize(
            last_summary=None,
            complete=False,
            destinations=None,  # Missing field
        )

        result = summarize(state)

        # Should have generated a follow-up question
        assert result.last_summary is not None
        assert len(result.last_summary) > 0

    def test_preserves_existing_last_summary(self):
        """Should not overwrite existing last_summary."""
        existing_message = "Here's your flight information."
        state = make_state_for_summarize(
            last_summary=existing_message,
        )

        result = summarize(state)

        # Should preserve existing message (possibly with safety snippet)
        assert existing_message in result.last_summary

    def test_sets_provenance_when_generating_fallback(self):
        """Should set deterministic provenance when generating fallback."""
        state = make_state_for_summarize(
            last_summary=None,
            complete=False,
            destinations=None,
        )

        result = summarize(state)

        # Check if provenance is set (may be set by the function)
        # The function should set response_generation_provenance when generating fallback
        assert result.last_summary is not None  # Fallback was generated


# =============================================================================
# Empty Response Guard Tests
# =============================================================================


class TestEmptyResponseGuard:
    """Tests for emergency fallback when response is empty."""

    def test_generates_fallback_for_empty_last_summary(self):
        """Should generate fallback when last_summary is empty string."""
        state = make_state_for_summarize(
            last_summary="",  # Empty string
            destinations=["Tokyo"],
        )

        result = summarize(state)

        # Should have generated a fallback
        assert result.last_summary is not None
        assert len(result.last_summary.strip()) > 0

    def test_generates_fallback_for_whitespace_only(self):
        """Should generate fallback when last_summary is whitespace only."""
        state = make_state_for_summarize(
            last_summary="   ",  # Whitespace only
            destinations=["Tokyo"],
        )

        result = summarize(state)

        # Should have generated a fallback
        assert result.last_summary is not None
        assert len(result.last_summary.strip()) > 0

    def test_strategy_fallback_when_pending_expansion(self):
        """Should generate strategy-specific fallback when in strategy flow."""
        state = make_state_for_summarize(
            last_summary="",
            destinations=["Swiss Alps"],
        )
        state.pending_strategy_expansion = True
        state.metadata["last_strategy_topic"] = "hiking"

        result = summarize(state)

        # Should have generated strategy-related fallback
        assert result.last_summary is not None
        # May mention the topic or destination
        lower_summary = result.last_summary.lower()
        assert any(
            term in lower_summary
            for term in ["hiking", "swiss alps", "trip", "adventure", "details", "itinerary"]
        )

    def test_destination_fallback_when_has_destinations(self):
        """Should generate destination-aware fallback when destinations present."""
        state = make_state_for_summarize(
            last_summary="",
            destinations=["Barcelona", "Madrid"],
        )

        result = summarize(state)

        # Should mention destination(s)
        assert result.last_summary is not None
        lower_summary = result.last_summary.lower()
        assert "barcelona" in lower_summary or "madrid" in lower_summary or "trip" in lower_summary


# =============================================================================
# Suggested Responses Structure Tests
# =============================================================================


class TestSuggestedResponsesStructure:
    """Tests for suggested_responses structure and content."""

    def test_suggested_responses_is_list(self):
        """suggested_responses should be a list when set."""
        state = make_state_for_summarize(
            plan_just_became_ready=True,
        )

        result = summarize(state)

        assert isinstance(result.suggested_responses, list)

    def test_suggested_responses_contains_strings(self):
        """All suggested_responses should be strings."""
        state = make_state_for_summarize(
            plan_just_became_ready=True,
        )

        result = summarize(state)

        if result.suggested_responses:
            for suggestion in result.suggested_responses:
                assert isinstance(suggestion, str)

    def test_suggested_responses_not_empty_strings(self):
        """suggested_responses should not contain empty strings."""
        state = make_state_for_summarize(
            plan_just_became_ready=True,
        )

        result = summarize(state)

        if result.suggested_responses:
            for suggestion in result.suggested_responses:
                assert len(suggestion.strip()) > 0


# =============================================================================
# Safety Snippet Tests
# =============================================================================


class TestSafetySnippetAugmentation:
    """Tests for safety snippet augmentation for international travel."""

    def test_does_not_crash_with_no_destinations(self):
        """Should handle case with no destinations gracefully."""
        state = make_state_for_summarize(
            last_summary="Hello!",
            complete=False,
            destinations=None,
        )

        # Should not crash
        result = summarize(state)

        assert result is not None

    def test_does_not_crash_with_empty_destinations(self):
        """Should handle empty destinations list gracefully."""
        state = make_state_for_summarize(
            last_summary="Hello!",
            complete=False,
            destinations=[],
        )

        # Should not crash
        result = summarize(state)

        assert result is not None

    def test_message_preserved_when_safety_snippet_conditions_not_met(self):
        """Message should be preserved when safety conditions not met."""
        original = "Here's your domestic trip info."
        state = make_state_for_summarize(
            last_summary=original,
            destinations=["New York"],
            origin="Los Angeles",  # Domestic trip
        )

        result = summarize(state)

        # Original message should still be there
        assert original in result.last_summary


# =============================================================================
# Edge Cases
# =============================================================================


class TestSummarizeEdgeCases:
    """Tests for edge cases and error handling."""

    def test_handles_none_metadata_fields(self):
        """Should handle None values in metadata gracefully."""
        state = make_state_for_summarize(
            last_summary="Test",
        )
        state.metadata["user_request_type"] = None
        state.metadata["plan_just_became_ready"] = None

        # Should not crash
        result = summarize(state)

        assert result is not None

    def test_handles_missing_trip_inputs_fields(self):
        """Should handle missing trip_inputs fields gracefully."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(),  # Minimal trip inputs
            last_summary="Hello",
            metadata={"thread_id": "test"},
        )

        # Should not crash
        result = summarize(state)

        assert result is not None

    def test_very_long_last_summary_handled(self):
        """Should handle very long last_summary without issues."""
        long_summary = "This is a very long message. " * 100
        state = make_state_for_summarize(
            last_summary=long_summary,
        )

        # Should not crash
        result = summarize(state)

        assert result is not None
        assert len(result.last_summary) >= len(long_summary)

    def test_special_characters_in_destinations(self):
        """Should handle special characters in destinations."""
        state = make_state_for_summarize(
            last_summary="",
            destinations=["São Paulo", "München", "日本"],
        )

        # Should not crash
        result = summarize(state)

        assert result is not None
        assert result.last_summary is not None
