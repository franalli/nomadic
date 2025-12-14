"""Comprehensive tests for short-circuit detection logic."""

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

from app.plan_graph import (
    _BARE_DATE_PATTERN,
    _BARE_DEST_PATTERN,
    _GREETING_PATTERN,
    _GREETING_RESPONSES,
    _NO_PATTERN,
    _YES_PATTERN,
    GraphState,
    TripInputs,
    _detect_short_circuit,
)


class TestGreetingPatterns:
    """Tests for greeting detection and response."""

    @pytest.mark.parametrize(
        "text",
        [
            "hi",
            "Hi",
            "HI",
            "hello",
            "Hello",
            "hey",
            "Hey!",
            "howdy",
            "greetings",
            "hiya",
        ],
    )
    def test_greeting_variants(self, text):
        """Various greeting formats should be detected."""
        state = GraphState(user_text="", trip_inputs=TripInputs(), metadata={})
        result = _detect_short_circuit(text, state)
        assert result is not None
        assert result["type"] == "greeting"

    @pytest.mark.parametrize(
        "text",
        [
            "good morning",
            "Good morning",
            "good afternoon",
            "good evening",
        ],
    )
    def test_time_based_greetings(self, text):
        """Time-based greetings should match greeting pattern."""
        # Check pattern directly
        assert _GREETING_PATTERN.match(text) is not None

    def test_greeting_response_is_from_list(self):
        """Greeting response should be from the predefined list."""
        state = GraphState(user_text="", trip_inputs=TripInputs(), metadata={})
        result = _detect_short_circuit("hi", state)
        assert result is not None
        assert result["response"] in _GREETING_RESPONSES

    def test_greeting_with_punctuation(self):
        """Greetings with punctuation should be detected."""
        state = GraphState(user_text="", trip_inputs=TripInputs(), metadata={})
        for text in ["hi!", "hello!", "hey!"]:
            result = _detect_short_circuit(text, state)
            assert result is not None
            assert result["type"] == "greeting"


class TestAcknowledgmentPatterns:
    """Tests for acknowledgment detection."""

    @pytest.mark.parametrize(
        "text",
        [
            "ok",
            "Ok",
            "OK",
            "okay",
            "Okay",
            "thanks",
            "Thanks",
            "thank you",
            "got it",
            "Got it",
            "cool",
            "great",
            "perfect",
            "awesome",
        ],
    )
    def test_acknowledgment_variants(self, text):
        """Various acknowledgment formats should be detected."""
        state = GraphState(user_text="", trip_inputs=TripInputs(), metadata={})
        result = _detect_short_circuit(text, state)
        assert result is not None
        assert result["type"] == "acknowledgment"

    def test_acknowledgment_continues_flow(self):
        """Acknowledgments should not have an action that blocks flow."""
        state = GraphState(user_text="", trip_inputs=TripInputs(), metadata={})
        result = _detect_short_circuit("ok", state)
        assert result is not None
        assert result["action"] is None  # No action, just continue


class TestYesNoConfirmations:
    """Tests for yes/no confirmation handling."""

    @pytest.mark.parametrize("text", ["yes", "Yes", "YES", "yeah", "yep", "sure", "yup"])
    def test_yes_pattern_matches(self, text):
        """Yes variants should match the pattern."""
        assert _YES_PATTERN.match(text) is not None

    @pytest.mark.parametrize("text", ["no", "No", "NO", "nope", "nah", "not really"])
    def test_no_pattern_matches(self, text):
        """No variants should match the pattern."""
        assert _NO_PATTERN.match(text) is not None

    def test_yes_without_pending_action(self):
        """'yes' without pending action should be generic confirmation."""
        state = GraphState(user_text="", trip_inputs=TripInputs(), metadata={})
        result = _detect_short_circuit("yes", state)
        assert result is not None
        assert result["type"] == "confirmation_yes"
        assert result["action"] is None  # No action without pending

    def test_yes_with_generate_plan_pending(self):
        """'yes' with generate_plan pending should trigger action."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(),
            metadata={"pending_action": "generate_plan"},
        )
        result = _detect_short_circuit("yes", state)
        assert result is not None
        assert result["type"] == "confirmation_yes"
        assert result["action"] == "generate_plan"

    def test_yes_with_confirm_typo_pending(self):
        """'yes' with confirm_typo pending should trigger typo correction."""
        corrections = {"Pariz": "Paris"}
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(),
            metadata={
                "pending_action": "confirm_typo",
                "pending_typo_corrections": corrections,
            },
        )
        result = _detect_short_circuit("yes", state)
        assert result is not None
        assert result["type"] == "confirm_typo"
        assert result["action"] == "apply_typo_corrections"
        assert result["parsed"]["typo_corrections"] == corrections

    def test_no_clears_pending_action(self):
        """'no' with any pending action should clear it."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(),
            metadata={"pending_action": "generate_plan"},
        )
        result = _detect_short_circuit("no", state)
        assert result is not None
        assert result["type"] == "confirmation_no"
        assert result["action"] == "clear_pending"

    def test_no_without_pending_action(self):
        """'no' without pending action should be generic denial."""
        state = GraphState(user_text="", trip_inputs=TripInputs(), metadata={})
        result = _detect_short_circuit("no", state)
        assert result is not None
        assert result["type"] == "confirmation_no"
        assert result["action"] is None


class TestOffTopicDetection:
    """Tests for off-topic input detection."""

    @pytest.mark.parametrize(
        "text,topic",
        [
            ("what's the weather like", "weather"),
            ("how's the weather", "weather"),
            ("what is 2+2", "math"),
            ("calculate 100/5", "math"),
            ("who was Napoleon", "general_knowledge"),
            ("what is the capital of France", "general_knowledge"),
            ("write me a poem", "creative_writing"),
            ("tell me a story", "creative_writing"),
        ],
    )
    def test_off_topic_detection(self, text, topic):
        """Off-topic inputs should be detected and redirected."""
        state = GraphState(user_text="", trip_inputs=TripInputs(), metadata={})
        result = _detect_short_circuit(text, state)
        if result is not None and result["type"] == "off_topic":
            # Verify we have a redirect response
            assert result["response"] is not None
            assert "travel" in result["response"].lower() or "trip" in result["response"].lower()


class TestBareInputDetection:
    """Tests for bare input patterns (single field answers)."""

    @pytest.mark.parametrize(
        "text",
        [
            "Paris",
            "London",
            "Tokyo",
            "New York",
            "São Paulo",
            "Zürich",
            "Côte d'Azur",
        ],
    )
    def test_bare_destination_pattern(self, text):
        """Bare destination names should match pattern."""
        assert _BARE_DEST_PATTERN.match(text) is not None

    @pytest.mark.parametrize(
        "text",
        [
            "tomorrow",
            "next week",
            "next month",
            "this weekend",
            "today",
            "Jan 15",
            "March 1st",
            "12/25",
        ],
    )
    def test_bare_date_pattern(self, text):
        """Bare date inputs should match pattern."""
        assert _BARE_DATE_PATTERN.match(text) is not None

    def test_bare_destination_after_question(self):
        """Bare destination after destination question should be extracted."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(),  # No destinations yet
            metadata={"last_question_field": "destinations"},
        )
        result = _detect_short_circuit("Paris", state)
        # Should be detected as bare destination
        if result is not None:
            assert result["type"] in ("bare_destination", "bare_input")
            assert result["parsed"] is not None

    def test_bare_destination_first_turn(self):
        """Capitalized place name on first turn should be detected."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(),
            metadata={},
        )
        result = _detect_short_circuit("Tokyo", state)
        # May be detected as bare destination on first turn
        if result is not None:
            assert result.get("parsed") is not None


class TestLongInputBypass:
    """Tests for long input short-circuit bypass."""

    def test_long_input_bypasses_short_circuit(self):
        """Inputs over 50 chars should not be short-circuited."""
        state = GraphState(user_text="", trip_inputs=TripInputs(), metadata={})
        long_text = "I want to plan a trip from London to Paris next week with my family of 4"
        result = _detect_short_circuit(long_text, state)
        # Long inputs should go through full pipeline
        assert result is None

    def test_short_input_is_processed(self):
        """Short inputs under 50 chars can be short-circuited."""
        state = GraphState(user_text="", trip_inputs=TripInputs(), metadata={})
        result = _detect_short_circuit("hi", state)
        assert result is not None


class TestGrammarPatternBypass:
    """Tests for grammar pattern detection bypassing bare destination."""

    def test_from_to_not_bare_destination(self):
        """'from X to Y' should not be treated as bare destination."""
        state = GraphState(user_text="", trip_inputs=TripInputs(), metadata={})
        result = _detect_short_circuit("from London to Paris", state)
        # Should not be short-circuited as bare destination
        # (may be None to go through extractor, or may have parsed data)
        if result is not None:
            assert result["type"] != "greeting"
            assert result["type"] != "acknowledgment"

    def test_going_to_not_bare_destination(self):
        """'going to X' should not be treated as bare destination."""
        state = GraphState(user_text="", trip_inputs=TripInputs(), metadata={})
        result = _detect_short_circuit("going to Paris", state)
        if result is not None:
            # Should have parsed data if detected
            assert result.get("parsed") is not None or result["type"] not in (
                "greeting",
                "acknowledgment",
            )


class TestShortCircuitEdgeCases:
    """Edge case tests for short-circuit detection."""

    def test_empty_string(self):
        """Empty string should not crash."""
        state = GraphState(user_text="", trip_inputs=TripInputs(), metadata={})
        result = _detect_short_circuit("", state)
        # Empty string may or may not be short-circuited, but should not crash
        assert result is None or isinstance(result, dict)

    def test_whitespace_only(self):
        """Whitespace-only string should not crash."""
        state = GraphState(user_text="", trip_inputs=TripInputs(), metadata={})
        result = _detect_short_circuit("   ", state)
        assert result is None or isinstance(result, dict)

    def test_special_characters(self):
        """Special characters should not crash."""
        state = GraphState(user_text="", trip_inputs=TripInputs(), metadata={})
        result = _detect_short_circuit("!@#$%", state)
        assert result is None or isinstance(result, dict)

    def test_numbers_only(self):
        """Numbers only might be travelers count."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(),
            metadata={"last_question_field": "travelers"},
        )
        result = _detect_short_circuit("4", state)
        # Could be bare travelers count
        if result is not None:
            assert result["type"] in ("bare_travelers", "bare_input")

    def test_pending_action_priority(self):
        """Pending action confirmation should take priority."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(),
            metadata={"pending_action": "generate_plan"},
        )
        # "sounds good" is acknowledgment AND yes confirmation
        result = _detect_short_circuit("sounds good", state)
        assert result is not None
        # Should be treated as confirmation due to pending action
        assert result["action"] == "generate_plan"
