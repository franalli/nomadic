"""
Unit tests for deterministic polish behavior.

MVP Hardening tests covering:
- Deterministic polish does not change question_target
- Deterministic polish does not change suggested_responses
- MVP mode skips LLM polish entirely
- YC compliance: No warm openers/closers (system-style messages)
"""

from app.config import settings
from app.plan_graph import (
    _WARM_CLOSERS,
    _WARM_OPENERS,
    GraphState,
    TripInputs,
    _try_deterministic_polish,
)


class TestDeterministicPolishSafeTransforms:
    """Test that deterministic polish only applies safe transforms."""

    def test_short_dry_message_with_yc_compliance(self):
        """YC compliance: With empty warmth lists, no polishing occurs."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(),
            metadata={},
            flags={},
        )

        msg = "I can help with that."
        result = _try_deterministic_polish(msg, state)

        # YC mode: warmth lists are empty, so no polishing
        if not _WARM_OPENERS or not _WARM_CLOSERS:
            assert result is None
        else:
            # Should either add opener or return None (for LLM polish)
            if result:
                # Should have added something warm
                assert len(result) > len(msg)
                # Original content should be preserved
                assert "help" in result.lower()

    def test_message_with_exclamation_not_modified(self):
        """Messages already with warmth indicators may not need modification."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(),
            metadata={},
            flags={},
        )

        msg = "Great choice! I can help you find the perfect hotel."
        result = _try_deterministic_polish(msg, state)

        # YC mode: no polishing, or if polishing enabled, already warm
        if not _WARM_OPENERS or not _WARM_CLOSERS:
            assert result is None
        elif result:
            assert "!" in result or "?" in result

    def test_empty_message_returns_none(self):
        """Empty message should return None."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(),
            metadata={},
            flags={},
        )

        result = _try_deterministic_polish("", state)
        assert result is None

    def test_none_message_returns_none(self):
        """None message should return None."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(),
            metadata={},
            flags={},
        )

        result = _try_deterministic_polish(None, state)
        assert result is None


class TestDeterministicPolishDoesNotChangeState:
    """Test that deterministic polish doesn't change question_target or suggestions."""

    def test_question_target_preserved(self):
        """question_target should not be modified by polish."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(),
            metadata={},
            flags={},
            question_target="destinations",
        )
        original_target = state.question_target

        msg = "Where would you like to go."
        _try_deterministic_polish(msg, state)

        assert state.question_target == original_target

    def test_suggested_responses_preserved(self):
        """suggested_responses should not be modified by polish."""
        original_suggestions = ["Paris", "Tokyo", "London"]
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(),
            metadata={},
            flags={},
            suggested_responses=original_suggestions.copy(),
        )

        msg = "Where would you like to go."
        _try_deterministic_polish(msg, state)

        assert state.suggested_responses == original_suggestions


class TestPolishMVPMode:
    """Test MVP mode polish behavior."""

    def test_mvp_config_exists(self):
        """enable_response_polish_mvp config should exist."""
        # Just verify the config exists
        assert hasattr(settings, "enable_response_polish_mvp")

    def test_mvp_mode_is_disabled_by_default(self):
        """MVP mode should be False by default (LLM polish disabled)."""
        # MVP mode = False means we skip LLM polish
        assert settings.enable_response_polish_mvp is False


class TestDeterministicPolishPatterns:
    """Test specific deterministic polish patterns."""

    def test_period_ending_with_yc_compliance(self):
        """YC compliance: With empty warmth lists, no closer added."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(),
            metadata={},
            flags={},
        )

        msg = "I found some options."
        result = _try_deterministic_polish(msg, state)

        # YC mode: warmth lists are empty, so no polishing
        if not _WARM_OPENERS or not _WARM_CLOSERS:
            assert result is None
        elif result:
            # Should have added something
            assert len(result) >= len(msg)

    def test_question_not_modified_unnecessarily(self):
        """Questions should not be unnecessarily modified."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(),
            metadata={},
            flags={},
        )

        msg = "Where would you like to go?"
        result = _try_deterministic_polish(msg, state)

        # YC mode: no polishing, or if polishing enabled, preserve question
        if not _WARM_OPENERS or not _WARM_CLOSERS:
            assert result is None
        elif result:
            assert "?" in result


class TestPolishMetadataTracking:
    """Test that polish tracks method in metadata."""

    def test_tracks_polish_method_when_enabled(self):
        """Should track which polish method was used (when warmth lists non-empty)."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(),
            metadata={},
            flags={},
        )

        msg = "I can help."
        result = _try_deterministic_polish(msg, state)

        # YC mode: warmth lists are empty, so no polishing and no metadata
        if not _WARM_OPENERS or not _WARM_CLOSERS:
            assert result is None
            # No metadata set when skipping
        elif result:
            # Should have set polish_method in metadata
            assert "polish_method" in state.metadata
            assert state.metadata["polish_method"].startswith("deterministic")
