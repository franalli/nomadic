"""
Unit tests for strategy bootstrap bypass functionality.

Tests the deterministic bypass of extractor LLM for strategy pre-core prompts,
which reduces first-turn latency from 2 LLM calls to 1.

Tests cover:
- Bypass should trigger for simple strategy prompts
- Bypass should NOT trigger when safety gates fail:
  - Place-like entities detected
  - Constraint tokens present (dates, budget, travelers)
  - Multi-intent detected (multiple specialists)
  - Text too long
  - Core fields already present
  - Question target already set
- A/B cohort assignment is stable
- Observability metadata is recorded correctly
"""

from unittest.mock import patch

import pytest

from app.config import settings
from app.pattern_matching import BYPASS_CONSTRAINT_PATTERNS
from app.plan_graph import (
    GraphState,
    TripInputs,
    _detect_strategy_topic_from_text,
    _try_strategy_bootstrap_bypass,
)


class TestStrategyTopicDetection:
    """Test strategy topic detection patterns."""

    @pytest.mark.parametrize(
        "text,expected_topic",
        [
            # Hiking
            ("Plan an adventure trip with hiking", "hiking"),
            ("I want to go on a trek", "hiking"),
            ("mountain hiking vacation", "hiking"),
            # Skiing - with word boundaries
            ("I want to go skiing", "skiing"),
            ("snowboarding trip", "skiing"),
            ("ski vacation ideas", "skiing"),
            # Diving
            ("scuba diving trip", "diving"),
            ("snorkeling adventure", "diving"),
            ("I want to dive", "diving"),
            # Cycling
            ("cycling tour ideas", "cycling"),
            ("biking vacation", "cycling"),
            ("bicycle trip planning", "cycling"),
            # Boating
            ("sailing adventure", "boating"),
            ("yacht trip", "boating"),
            ("I want to go boating", "boating"),
        ],
    )
    def test_topic_detection_positive(self, text: str, expected_topic: str):
        """Strategy topics should be detected correctly."""
        result = _detect_strategy_topic_from_text(text)
        assert result == expected_topic, f"Expected '{expected_topic}' for '{text}', got '{result}'"

    @pytest.mark.parametrize(
        "text",
        [
            # Avoid false positives with word boundaries
            "skippered boat charter",  # 'ski' is a substring but shouldn't match
            "I'm not a diver",  # negation context (still matches - gate catches this)
            "",  # empty text
        ],
    )
    def test_topic_detection_false_positives(self, text: str):
        """Words like 'skippered' should not match 'ski'."""
        if text == "skippered boat charter":
            # 'skippered' should NOT match 'ski' due to word boundary
            result = _detect_strategy_topic_from_text(text)
            # But 'boat' will match 'boating' pattern
            assert result == "boating" or result is None  # depends on pattern priority


class TestBypassPositiveCases:
    """Tests where bypass SHOULD trigger."""

    @pytest.fixture
    def enable_bypass(self):
        """Enable bypass feature flag for tests."""
        with patch.object(settings, "enable_strategy_bootstrap_bypass", True):
            with patch.object(settings, "strategy_bootstrap_bypass_sample_rate", 1.0):
                yield

    def test_bypass_simple_hiking_prompt(self, enable_bypass):
        """Bypass should trigger for 'Plan an adventure trip with hiking'."""
        state = GraphState(
            user_text="Plan an adventure trip with hiking",
            trip_inputs=TripInputs(),
            metadata={"thread_id": "test-session-1"},
            flags={},
        )

        result = _try_strategy_bootstrap_bypass("Plan an adventure trip with hiking", state)

        assert result is not None, "Bypass should trigger"
        assert result["topic"] == "hiking"
        assert result["trip_style"] == "adventure_outdoors"
        assert "hiking" in result["activity_categories"]
        assert result["variant"] == "bypass"

    def test_bypass_simple_skiing_prompt(self, enable_bypass):
        """Bypass should trigger for simple skiing prompt."""
        state = GraphState(
            user_text="I want to go skiing",
            trip_inputs=TripInputs(),
            metadata={"thread_id": "test-session-2"},
            flags={},
        )

        result = _try_strategy_bootstrap_bypass("I want to go skiing", state)

        assert result is not None
        assert result["topic"] == "skiing"
        assert result["trip_style"] == "adventure_outdoors"

    def test_bypass_simple_diving_prompt(self, enable_bypass):
        """Bypass should trigger for simple diving prompt."""
        state = GraphState(
            user_text="Scuba diving vacation",
            trip_inputs=TripInputs(),
            metadata={"thread_id": "test-session-3"},
            flags={},
        )

        result = _try_strategy_bootstrap_bypass("Scuba diving vacation", state)

        assert result is not None
        assert result["topic"] == "diving"


class TestBypassNegativeCases:
    """Tests where bypass should NOT trigger."""

    @pytest.fixture
    def enable_bypass(self):
        """Enable bypass feature flag for tests."""
        with patch.object(settings, "enable_strategy_bootstrap_bypass", True):
            with patch.object(settings, "strategy_bootstrap_bypass_sample_rate", 1.0):
                yield

    def test_no_bypass_with_place_entities(self, enable_bypass):
        """Bypass should NOT trigger when place detected: 'Hiking in Swiss Alps'."""
        state = GraphState(
            user_text="Hiking in Swiss Alps",
            trip_inputs=TripInputs(),
            metadata={"thread_id": "test-session-4"},
            flags={},
        )

        result = _try_strategy_bootstrap_bypass("Hiking in Swiss Alps", state)

        assert result is None, "Bypass should NOT trigger when place is detected"

    def test_no_bypass_with_date_constraint(self, enable_bypass):
        """Bypass should NOT trigger with date constraint: 'Hiking trip next month'."""
        state = GraphState(
            user_text="Hiking trip next month",
            trip_inputs=TripInputs(),
            metadata={"thread_id": "test-session-5"},
            flags={},
        )

        result = _try_strategy_bootstrap_bypass("Hiking trip next month", state)

        assert result is None, "Bypass should NOT trigger with date constraint"

    def test_no_bypass_with_budget_constraint(self, enable_bypass):
        """Bypass should NOT trigger with budget: 'Hiking trip, $2k budget'."""
        state = GraphState(
            user_text="Hiking trip, $2k budget",
            trip_inputs=TripInputs(),
            metadata={"thread_id": "test-session-6"},
            flags={},
        )

        result = _try_strategy_bootstrap_bypass("Hiking trip, $2k budget", state)

        assert result is None, "Bypass should NOT trigger with budget constraint"

    def test_no_bypass_with_traveler_count(self, enable_bypass):
        """Bypass should NOT trigger with travelers: '2 adults, 1 child, hiking trip'."""
        state = GraphState(
            user_text="2 adults, 1 child, hiking trip",
            trip_inputs=TripInputs(),
            metadata={"thread_id": "test-session-7"},
            flags={},
        )

        result = _try_strategy_bootstrap_bypass("2 adults, 1 child, hiking trip", state)

        assert result is None, "Bypass should NOT trigger with traveler count"

    def test_no_bypass_with_multi_intent(self, enable_bypass):
        """Bypass should NOT trigger with multi-intent keywords."""
        state = GraphState(
            user_text="Hiking trip and find hotels and flights",
            trip_inputs=TripInputs(),
            metadata={"thread_id": "test-session-8"},
            flags={},
        )

        result = _try_strategy_bootstrap_bypass("Hiking trip and find hotels and flights", state)

        assert result is None, "Bypass should NOT trigger with multi-intent"

    def test_no_bypass_when_question_target_set(self, enable_bypass):
        """Bypass should NOT trigger when question_target already set."""
        state = GraphState(
            user_text="Plan an adventure trip with hiking",
            trip_inputs=TripInputs(),
            metadata={"thread_id": "test-session-9", "question_target": "start_date"},
            flags={},
        )

        result = _try_strategy_bootstrap_bypass("Plan an adventure trip with hiking", state)

        assert result is None, "Bypass should NOT trigger when question_target is set"

    def test_no_bypass_when_core_fields_present(self, enable_bypass):
        """Bypass should NOT trigger when destinations already extracted."""
        state = GraphState(
            user_text="Plan an adventure trip with hiking",
            trip_inputs=TripInputs(destinations=["Paris"]),
            metadata={"thread_id": "test-session-10"},
            flags={},
        )

        result = _try_strategy_bootstrap_bypass("Plan an adventure trip with hiking", state)

        assert result is None, "Bypass should NOT trigger with core fields present"

    def test_no_bypass_when_text_too_long(self, enable_bypass):
        """Bypass should NOT trigger when text exceeds length limit."""
        long_text = "hiking " + "a " * 100 + "trip"  # Well over 150 chars
        state = GraphState(
            user_text=long_text,
            trip_inputs=TripInputs(),
            metadata={"thread_id": "test-session-11"},
            flags={},
        )

        result = _try_strategy_bootstrap_bypass(long_text, state)

        assert result is None, "Bypass should NOT trigger for long text"

    def test_no_bypass_when_feature_disabled(self):
        """Bypass should NOT trigger when feature flag is disabled."""
        with patch.object(settings, "enable_strategy_bootstrap_bypass", False):
            state = GraphState(
                user_text="Plan an adventure trip with hiking",
                trip_inputs=TripInputs(),
                metadata={"thread_id": "test-session-12"},
                flags={},
            )

            result = _try_strategy_bootstrap_bypass("Plan an adventure trip with hiking", state)

            assert result is None, "Bypass should NOT trigger when feature disabled"

    def test_no_bypass_with_multiple_topics(self, enable_bypass):
        """Bypass should NOT trigger with multiple strategy topics."""
        state = GraphState(
            user_text="Hiking and skiing trip",
            trip_inputs=TripInputs(),
            metadata={"thread_id": "test-session-13"},
            flags={},
        )

        result = _try_strategy_bootstrap_bypass("Hiking and skiing trip", state)

        assert result is None, "Bypass should NOT trigger with multiple topics"


class TestBypassABTesting:
    """Tests for A/B cohort assignment."""

    def test_control_cohort_does_not_bypass(self):
        """Control cohort (sample_rate=0) should not bypass."""
        with patch.object(settings, "enable_strategy_bootstrap_bypass", True):
            with patch.object(settings, "strategy_bootstrap_bypass_sample_rate", 0.0):
                state = GraphState(
                    user_text="Plan an adventure trip with hiking",
                    trip_inputs=TripInputs(),
                    metadata={"thread_id": "test-session-control"},
                    flags={},
                )

                result = _try_strategy_bootstrap_bypass("Plan an adventure trip with hiking", state)

                assert result is None, "Control cohort should not bypass"

    def test_stable_cohort_assignment(self):
        """Same session_id should always get same cohort."""
        with patch.object(settings, "enable_strategy_bootstrap_bypass", True):
            with patch.object(settings, "strategy_bootstrap_bypass_sample_rate", 0.5):
                session_id = "stable-session-id-12345"

                results = []
                for _ in range(10):
                    state = GraphState(
                        user_text="Plan an adventure trip with hiking",
                        trip_inputs=TripInputs(),
                        metadata={"thread_id": session_id},
                        flags={},
                    )
                    result = _try_strategy_bootstrap_bypass(
                        "Plan an adventure trip with hiking", state
                    )
                    results.append(result is not None)

                # All results should be the same (stable)
                assert len(set(results)) == 1, "Cohort assignment should be stable"


class TestConstraintPatterns:
    """Tests for constraint token detection patterns."""

    @pytest.mark.parametrize(
        "text,constraint_type",
        [
            # Date constraints
            ("trip next month", "dates"),
            ("traveling in January", "dates"),
            ("Feb 15 departure", "dates"),
            ("this week vacation", "dates"),
            # Budget constraints
            ("$500 budget", "budget"),
            ("budget of 1000 dollars", "budget"),
            ("€2000 trip", "budget"),
            # Traveler constraints
            ("2 adults traveling", "travelers"),
            ("family trip", "travelers"),
            ("solo adventure", "travelers"),
            ("just me", "travelers"),
            ("couple vacation", "travelers"),
        ],
    )
    def test_constraint_pattern_detection(self, text: str, constraint_type: str):
        """Constraint patterns should be detected."""
        pattern = BYPASS_CONSTRAINT_PATTERNS[constraint_type]
        assert (
            pattern.search(text) is not None
        ), f"Expected '{constraint_type}' constraint in '{text}'"


class TestBypassInvariants:
    """Tests for bypass correctness invariants."""

    @pytest.fixture
    def enable_bypass(self):
        """Enable bypass feature flag for tests."""
        with patch.object(settings, "enable_strategy_bootstrap_bypass", True):
            with patch.object(settings, "strategy_bootstrap_bypass_sample_rate", 1.0):
                yield

    def test_bypass_result_has_required_fields(self, enable_bypass):
        """Bypass result must have all required fields."""
        state = GraphState(
            user_text="Plan an adventure trip with hiking",
            trip_inputs=TripInputs(),
            metadata={"thread_id": "test-invariant-1"},
            flags={},
        )

        result = _try_strategy_bootstrap_bypass("Plan an adventure trip with hiking", state)

        assert result is not None
        required_fields = [
            "topic",
            "trip_style",
            "activity_categories",
            "variant",
            "place_detected_by",
            "constraint_tokens",
        ]
        for field in required_fields:
            assert field in result, f"Missing required field: {field}"

    def test_bypass_topic_matches_detection(self, enable_bypass):
        """Bypass topic must match what detection would return."""
        for text, expected_topic in [
            ("I want to go hiking", "hiking"),
            ("skiing vacation", "skiing"),
            ("scuba diving trip", "diving"),
            ("cycling tour", "cycling"),
            ("sailing adventure", "boating"),
        ]:
            state = GraphState(
                user_text=text,
                trip_inputs=TripInputs(),
                metadata={"thread_id": f"test-topic-{expected_topic}"},
                flags={},
            )

            result = _try_strategy_bootstrap_bypass(text, state)

            if result is not None:
                detected = _detect_strategy_topic_from_text(text)
                assert (
                    result["topic"] == detected
                ), f"Bypass topic '{result['topic']}' != detected '{detected}'"
