"""
Unit tests for loop guard functionality in plan_graph.py.

Tests cover:
- Loop detection threshold (now 1)
- Question tracking across turns
- Mitigation action selection
- Recovery summary generation
- Config flag behavior
"""

from app.config import settings
from app.plan_graph import (
    GraphState,
    TripInputs,
    check_and_apply_loop_guard,
    track_question_asked,
)


class TestLoopGuardConfig:
    """Test loop guard configuration."""

    def test_threshold_is_one(self):
        """Verify loop guard threshold is set to 1 (single repeat triggers)."""
        assert (
            settings.loop_guard_threshold == 1
        ), f"Expected loop_guard_threshold=1, got {settings.loop_guard_threshold}"

    def test_loop_guard_enabled_by_default(self):
        """Verify loop guard is enabled by default."""
        assert settings.loop_guard_enabled is True


class TestQuestionTracking:
    """Test question tracking functionality."""

    def test_track_question_records_field(self):
        """Test that tracking a question records the field."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(),
            questions_asked={},
            turn_number=1,
        )

        track_question_asked(state, "travelers", "How many travelers?")

        assert "travelers" in state.questions_asked
        assert state.questions_asked["travelers"] == 1

    def test_track_multiple_questions_same_field(self):
        """Test tracking multiple questions for the same field."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(),
            questions_asked={},
            turn_number=1,
        )

        track_question_asked(state, "travelers", "How many travelers?")
        track_question_asked(state, "travelers", "How many adults?")

        assert state.questions_asked["travelers"] == 2

    def test_track_questions_different_fields(self):
        """Test tracking questions for different fields."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(),
            questions_asked={},
            turn_number=1,
        )

        track_question_asked(state, "travelers", "How many travelers?")
        track_question_asked(state, "destinations", "Where to?")

        assert "travelers" in state.questions_asked
        assert "destinations" in state.questions_asked


class TestLoopMitigation:
    """Test loop guard mitigation actions."""

    def test_mitigation_skips_question(self):
        """Test that mitigation prevents repeated question.

        With threshold=1, a single prior question triggers loop guard.
        After 2 consecutive triggers, fast-tracks to recovery_summary which skips.
        """
        state = GraphState(
            user_text="ok",
            trip_inputs=TripInputs(destinations=["Paris"]),
            turn_number=2,
        )
        # Set up loop_guard with recent question (used by detect_question_loop)
        state.loop_guard = {
            "recent_questions": [{"field": "travelers", "turn": 1}],
            "consecutive_loop_triggers": 1,  # Already had one trigger
        }

        new_state, should_skip = check_and_apply_loop_guard(state, "travelers")

        # Should skip - threshold=1 means 1 question triggers loop,
        # and consecutive_triggers=2 causes fast-track to recovery_summary
        assert should_skip is True

    def test_no_mitigation_for_new_field(self):
        """Test that new fields are not affected by loop guard."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(),
            questions_asked={"travelers": 1},
            turn_number=2,
        )

        new_state, should_skip = check_and_apply_loop_guard(state, "destinations")

        # Should not skip - different field
        assert should_skip is False


class TestLoopGuardWithDefaultAdults:
    """Test interaction between loop guard and default adults."""

    def test_default_adults_config_enabled(self):
        """
        Verify default_adults_enabled is True, which prevents
        repeated "How many travelers?" questions.
        """
        assert settings.default_adults_enabled is True
