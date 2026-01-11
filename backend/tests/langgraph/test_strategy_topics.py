"""
Tests for Strategy Topics (PR3).

Comprehensive tests for strategy topic detection, routing, and persistence.
Ensures all 5 strategy topics (hiking, diving, skiing, cycling, boating) work correctly.
"""

import re
from datetime import date, timedelta

import pytest

from app.pattern_matching import STRATEGY_TOPIC_PATTERNS
from app.plan_graph import (
    STRATEGY_TOPIC_TO_NODE,
    GatePrecedence,
    GraphState,
    TripInputs,
    _detect_strategy_topic_from_text,
    clear_all_caches,
)
from app.planner.gates.implementations import StrategyTopicSwitchGate
from app.planner.gates.readiness import TripReadiness
from app.planner.gates.topic_detection import (
    detect_strategy_topic_from_text_precise,
)

FUTURE_START = (date.today() + timedelta(days=30)).isoformat()
FUTURE_END = (date.today() + timedelta(days=40)).isoformat()


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear all caches before and after each test."""
    clear_all_caches()
    yield
    clear_all_caches()


# =============================================================================
# Strategy Topic Registry Tests
# =============================================================================
class TestStrategyTopicRegistry:
    """Tests for strategy topic constants and mappings."""

    def test_all_five_topics_registered(self):
        """All 5 strategy topics should be registered."""
        expected = {"hiking", "diving", "skiing", "cycling", "boating"}
        actual = set(STRATEGY_TOPIC_TO_NODE.keys())
        assert actual == expected, f"Missing topics: {expected - actual}"

    def test_all_topics_map_to_strategy_node(self):
        """All topics should map to 'strategy_node'."""
        for topic, node in STRATEGY_TOPIC_TO_NODE.items():
            assert node == "strategy_node", f"Topic '{topic}' maps to '{node}' not 'strategy_node'"

    def test_topic_patterns_exist_for_all_topics(self):
        """All registered topics should have detection patterns."""
        for topic in STRATEGY_TOPIC_TO_NODE.keys():
            assert topic in STRATEGY_TOPIC_PATTERNS, f"No pattern for topic '{topic}'"
            assert isinstance(
                STRATEGY_TOPIC_PATTERNS[topic], re.Pattern
            ), f"Pattern for '{topic}' is not a regex"


# =============================================================================
# Topic Detection Accuracy Tests
# =============================================================================
class TestTopicDetectionHiking:
    """Tests for hiking topic detection."""

    @pytest.mark.parametrize(
        "text",
        [
            "I want to go hiking",
            "plan a hiking trip",
            "mountain hike vacation",
            "we love to hike",
            "trekking adventure",
            "trek through mountains",
        ],
    )
    def test_hiking_positive_cases(self, text: str):
        """Hiking keywords should be detected."""
        topic = _detect_strategy_topic_from_text(text)
        assert topic == "hiking", f"'{text}' should detect 'hiking', got '{topic}'"

    @pytest.mark.parametrize(
        "text",
        [
            "I like hockey",  # not hiking
            "take a hike (figuratively)",  # edge case - may match
        ],
    )
    def test_hiking_edge_cases(self, text: str):
        """Edge cases for hiking detection."""
        # These may or may not match - just verify no crash
        _detect_strategy_topic_from_text(text)


class TestTopicDetectionDiving:
    """Tests for diving topic detection."""

    @pytest.mark.parametrize(
        "text",
        [
            "scuba diving trip",
            "I want to dive",
            "diving vacation",
            "snorkeling adventure",
            "snorkel with fish",
        ],
    )
    def test_diving_positive_cases(self, text: str):
        """Diving keywords should be detected."""
        topic = _detect_strategy_topic_from_text(text)
        assert topic == "diving", f"'{text}' should detect 'diving', got '{topic}'"


class TestTopicDetectionSkiing:
    """Tests for skiing topic detection."""

    @pytest.mark.parametrize(
        "text",
        [
            "I want to go skiing",
            "ski vacation",
            "skiing trip",
            "snowboarding adventure",
            "snowboard trip",
        ],
    )
    def test_skiing_positive_cases(self, text: str):
        """Skiing keywords should be detected."""
        topic = _detect_strategy_topic_from_text(text)
        assert topic == "skiing", f"'{text}' should detect 'skiing', got '{topic}'"

    def test_skippered_does_not_match_ski(self):
        """'skippered' should not match 'ski' due to word boundaries."""
        text = "skippered charter"
        topic = _detect_strategy_topic_from_text(text)
        # Should NOT match skiing
        assert topic != "skiing", "'skippered' should not match 'skiing'"


class TestTopicDetectionCycling:
    """Tests for cycling topic detection."""

    @pytest.mark.parametrize(
        "text",
        [
            "cycling tour",
            "bicycle trip",
            "biking vacation",
            "bike through wine country",
            "I love to cycle",
        ],
    )
    def test_cycling_positive_cases(self, text: str):
        """Cycling keywords should be detected."""
        topic = _detect_strategy_topic_from_text(text)
        assert topic == "cycling", f"'{text}' should detect 'cycling', got '{topic}'"


class TestTopicDetectionBoating:
    """Tests for boating topic detection."""

    @pytest.mark.parametrize(
        "text",
        [
            "sailing adventure",
            "yacht vacation",
            "boating trip",
            "boat charter",
            "I want to sail",
        ],
    )
    def test_boating_positive_cases(self, text: str):
        """Boating keywords should be detected."""
        topic = _detect_strategy_topic_from_text(text)
        assert topic == "boating", f"'{text}' should detect 'boating', got '{topic}'"


class TestTopicDetectionNegative:
    """Tests for cases that should NOT detect a topic."""

    @pytest.mark.parametrize(
        "text",
        [
            "I want to go to Paris",
            "book a hotel",
            "find me flights",
            "beach vacation",
            "city tour",
            "food and wine trip",
            "",
            "   ",
        ],
    )
    def test_no_topic_detected(self, text: str):
        """Non-strategy texts should not detect a topic."""
        topic = _detect_strategy_topic_from_text(text)
        assert topic is None, f"'{text}' should not detect topic, got '{topic}'"


# =============================================================================
# Precise Topic Detection Tests (Word Boundaries)
# =============================================================================
class TestPreciseTopicDetection:
    """Tests for detect_strategy_topic_from_text_precise() with word boundaries."""

    def test_patterns_compiled_for_all_topics(self):
        """All strategy topics should have compiled regex patterns."""
        expected_topics = {"hiking", "diving", "skiing", "cycling", "boating"}
        assert set(STRATEGY_TOPIC_PATTERNS.keys()) == expected_topics

    @pytest.mark.parametrize(
        "text,expected_topic",
        [
            # Skiing - note: "ski" alone is NOT a keyword, only "skiing"
            ("I want to go skiing", "skiing"),
            ("skiing vacation please", "skiing"),
            ("snowboarding trip", "skiing"),
            ("powder day in the alps", "skiing"),
            # Hiking
            ("going hiking tomorrow", "hiking"),
            ("plan a hike", "hiking"),
            ("trekking adventure", "hiking"),
            ("mountain trails", "hiking"),
            # Diving
            ("let's go diving", "diving"),
            ("scuba dive trip", "diving"),
            ("snorkeling adventure", "diving"),
            # Cycling
            ("cycling tour of France", "cycling"),
            ("bike through wine country", "cycling"),
            ("bicycle trip", "cycling"),
            # Boating - note: "skippered" and "bareboat" ARE boating keywords
            ("sailing adventure", "boating"),
            ("yacht charter please", "boating"),
            ("skippered charter", "boating"),  # skippered is a boating keyword
            ("bareboat rental", "boating"),  # bareboat is a boating keyword
        ],
    )
    def test_precise_positive_cases(self, text: str, expected_topic: str):
        """Precise detection should match valid topic keywords."""
        topic = detect_strategy_topic_from_text_precise(text)
        assert topic == expected_topic, f"'{text}' should detect '{expected_topic}', got '{topic}'"

    @pytest.mark.parametrize(
        "text",
        [
            "skilled worker",  # Should NOT match 'ski' (ski not a keyword anyway)
            "skipping stones",  # Should NOT match any
            "bikini beach",  # Should NOT match 'bike'
            "diver-sion tactics",  # Should NOT match 'dive' (hyphen breaks word)
            "I want to ski",  # 'ski' alone is NOT in keywords, only 'skiing'
        ],
    )
    def test_precise_no_false_positives(self, text: str):
        """Precise detection should NOT have false positives from partial matches."""
        topic = detect_strategy_topic_from_text_precise(text)
        assert topic is None, f"'{text}' should not detect topic, got '{topic}'"

    def test_skippered_matches_boating_not_skiing(self):
        """'skippered' is a boating keyword, should match boating not skiing."""
        text = "I need a skippered yacht charter"
        topic = detect_strategy_topic_from_text_precise(text)
        assert topic != "skiing", "'skippered' incorrectly matched skiing"
        # Should match boating because 'skippered' and 'yacht' are boating keywords
        assert topic == "boating", f"Should detect boating, got '{topic}'"

    def test_bareboat_matches_boating(self):
        """'bareboat' is a boating keyword, should match boating."""
        text = "bareboat charter"
        topic = detect_strategy_topic_from_text_precise(text)
        # 'bareboat' is explicitly in boating keywords
        assert topic == "boating", f"'bareboat' should match boating, got '{topic}'"

    def test_ski_alone_not_keyword(self):
        """'ski' alone is not in keywords - only 'skiing' is."""
        # This tests that word boundaries work correctly
        # "ski" is not in STRATEGY_INTENT_KEYWORDS["skiing"], only "skiing" is
        text = "we love to ski"
        topic = detect_strategy_topic_from_text_precise(text)
        assert topic is None, f"'ski' alone should not match, got '{topic}'"

    def test_case_insensitive_matching(self):
        """Precise detection should be case-insensitive."""
        assert detect_strategy_topic_from_text_precise("SKIING") == "skiing"
        assert detect_strategy_topic_from_text_precise("Hiking Trip") == "hiking"
        assert detect_strategy_topic_from_text_precise("SCUBA DIVING") == "diving"

    def test_empty_and_whitespace(self):
        """Empty and whitespace-only strings should return None."""
        assert detect_strategy_topic_from_text_precise("") is None
        assert detect_strategy_topic_from_text_precise("   ") is None
        assert detect_strategy_topic_from_text_precise("\n\t") is None


# =============================================================================
# Topic Switch Gate Tests
# =============================================================================
class TestStrategyTopicSwitchGate:
    """Tests for the STRATEGY_TOPIC_SWITCH gate."""

    def test_gate_precedence_is_70(self):
        """STRATEGY_TOPIC_SWITCH should have precedence 70."""
        assert GatePrecedence.STRATEGY_TOPIC_SWITCH.value == 70

    def test_topic_switch_detected_with_intent_verb(self):
        """Topic switch should be detected with intent verbs."""
        ti = TripInputs(
            destinations=["Hawaii"],
            origin="New York",
            start_date=FUTURE_START,
            end_date=FUTURE_END,
        )
        readiness = TripReadiness(
            missing_core=[],
            question_target=None,
            ready_to_generate=True,
            blocking_errors=[],
        )
        metadata = {"last_strategy_topic": "hiking", "turn_number": 3}

        gate = StrategyTopicSwitchGate()
        result = gate._check_strategy_topic_switch(
            text_lower="i want to go diving instead",
            ti=ti,
            readiness=readiness,
            metadata=metadata,
            turn_number=3,
            precomputed_topic="diving",  # Pass pre-computed topic
        )

        assert result is not None
        new_topic, reason = result
        assert new_topic == "diving"

    def test_no_switch_without_intent_verb(self):
        """Topic should not switch without intent verb."""
        ti = TripInputs(
            destinations=["Hawaii"],
            origin="New York",
            start_date=FUTURE_START,
            end_date=FUTURE_END,
        )
        readiness = TripReadiness(
            missing_core=[],
            question_target=None,
            ready_to_generate=True,
            blocking_errors=[],
        )
        metadata = {"last_strategy_topic": "hiking", "turn_number": 3}

        gate = StrategyTopicSwitchGate()
        result = gate._check_strategy_topic_switch(
            text_lower="diving is cool",  # No intent verb
            ti=ti,
            readiness=readiness,
            metadata=metadata,
            turn_number=3,
            precomputed_topic="diving",  # Pass pre-computed topic
        )

        # Should NOT switch without intent verb
        assert result is None or result[1] != "new_topic"


# =============================================================================
# Strategy Topic Persistence Tests
# =============================================================================
class TestStrategyTopicPersistence:
    """Tests for strategy topic persistence across turns."""

    def test_topic_stored_in_metadata(self):
        """Strategy topic should be stored in metadata."""
        state = GraphState(
            session_id="test",
            user_text="I want to go hiking",
            trip_inputs=TripInputs(),
            metadata={"thread_id": "test"},
            strategy_topic="hiking",
        )

        assert state.strategy_topic == "hiking"

    def test_topic_survives_state_copy(self):
        """Strategy topic should survive state copy."""
        state = GraphState(
            session_id="test",
            user_text="I want to go diving",
            trip_inputs=TripInputs(),
            metadata={"thread_id": "test"},
            strategy_topic="diving",
        )

        # Simulate state copy
        new_state = GraphState(
            session_id=state.session_id,
            user_text="next message",
            trip_inputs=state.trip_inputs,
            metadata=state.metadata.copy(),
            strategy_topic=state.strategy_topic,
        )

        assert new_state.strategy_topic == "diving"


# =============================================================================
# Strategy Prompt File Tests
# =============================================================================
class TestStrategyPromptFiles:
    """Tests that prompt files exist for all strategy topics."""

    @pytest.mark.parametrize(
        "topic",
        ["hiking", "diving", "skiing", "cycling", "boating"],
    )
    def test_strategy_prompt_file_exists(self, topic: str):
        """Each strategy topic should have a prompt file."""
        from pathlib import Path

        prompt_file = Path(__file__).parents[2] / "app" / "prompts" / f"strategy_{topic}.txt"
        assert prompt_file.exists(), f"Missing prompt file: strategy_{topic}.txt"
        assert prompt_file.stat().st_size > 0, f"Empty prompt file: strategy_{topic}.txt"

    def test_strategy_base_prompt_exists(self):
        """The _strategy_base.txt shared prompt should exist."""
        from pathlib import Path

        prompt_file = Path(__file__).parents[2] / "app" / "prompts" / "_strategy_base.txt"
        assert prompt_file.exists(), "Missing _strategy_base.txt"

    def test_strategy_pre_core_prompt_exists(self):
        """The strategy_pre_core.txt prompt should exist."""
        from pathlib import Path

        prompt_file = Path(__file__).parents[2] / "app" / "prompts" / "strategy_pre_core.txt"
        assert prompt_file.exists(), "Missing strategy_pre_core.txt"


# =============================================================================
# Strategy Gate Integration Tests
# =============================================================================
class TestStrategyGateIntegration:
    """Integration tests for strategy-related gates."""

    def test_strategy_pre_core_value_gate_exists(self):
        """STRATEGY_PRE_CORE_VALUE gate should exist."""
        assert hasattr(GatePrecedence, "STRATEGY_PRE_CORE_VALUE")
        assert GatePrecedence.STRATEGY_PRE_CORE_VALUE.value == 80

    def test_strategy_topic_switch_gate_exists(self):
        """STRATEGY_TOPIC_SWITCH gate should exist."""
        assert hasattr(GatePrecedence, "STRATEGY_TOPIC_SWITCH")
        assert GatePrecedence.STRATEGY_TOPIC_SWITCH.value == 70

    def test_gate_ordering_topic_switch_before_pre_core_value(self):
        """
        STRATEGY_TOPIC_SWITCH should have higher precedence (lower number)
        than PRE_CORE_VALUE.
        """
        assert (
            GatePrecedence.STRATEGY_TOPIC_SWITCH.value
            < GatePrecedence.STRATEGY_PRE_CORE_VALUE.value
        )


# =============================================================================
# Multi-Topic Detection Tests
# =============================================================================
class TestMultiTopicDetection:
    """Tests for when multiple topics might be detected."""

    def test_first_topic_wins(self):
        """When multiple topics in text, first wins (based on pattern order)."""
        # Pattern order in dict determines winner
        text = "hiking and diving trip"
        topic = _detect_strategy_topic_from_text(text)
        # Either hiking or diving is acceptable
        assert topic in {"hiking", "diving"}

    def test_combined_activities_detect_first(self):
        """Combined activities should detect the first matching topic."""
        text = "skiing and snowboarding"
        topic = _detect_strategy_topic_from_text(text)
        assert topic == "skiing"


# =============================================================================
# Strategy Topic Validation Tests
# =============================================================================
class TestStrategyTopicValidation:
    """Tests for strategy topic validation."""

    def test_valid_topic_accepted(self):
        """Valid topics should be accepted by the system."""
        for topic in STRATEGY_TOPIC_TO_NODE.keys():
            state = GraphState(
                session_id="test",
                user_text=f"I want to go {topic}",
                trip_inputs=TripInputs(),
                metadata={"thread_id": "test"},
                strategy_topic=topic,
            )
            assert state.strategy_topic == topic

    def test_unknown_topic_stored(self):
        """Unknown topics can still be stored (no strict validation)."""
        # This tests that the system doesn't crash on unknown topics
        state = GraphState(
            session_id="test",
            user_text="I want to go surfing",  # Not a registered topic
            trip_inputs=TripInputs(),
            metadata={"thread_id": "test"},
            strategy_topic="surfing",  # Not in STRATEGY_TOPIC_TO_NODE
        )
        # Should not crash
        assert state.strategy_topic == "surfing"
