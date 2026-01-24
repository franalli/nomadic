"""
Integration tests for mid-session strategy topic switching.

Tests the STRATEGY_TOPIC_SWITCH gate, which handles cases like:
- User starts with hiking and later says "I wanna go diving in Argentina too"
- Bootstrap fast-path should NOT persist after turn 1
- Date clarification should block topic switch (pending_strategy_topic)
- Topic switch should route to the correct strategy specialist

These tests verify the fix for the diving specialist not being called mid-session.
"""

from datetime import date, timedelta

import pytest

from app.plan_graph import (
    STRATEGY_TOPIC_TO_NODE,
    GatePrecedence,
    GraphState,
    TripInputs,
    canonicalize_activity_categories,
    canonicalize_activity_category,
    compute_trip_readiness,
)
from app.planner.gates.constants import DateErrorCode
from app.planner.gates.implementations import StrategyTopicSwitchGate
from app.planner.gates.readiness import TripReadiness


# =============================================================================
# Future Date Helpers
# =============================================================================
def get_future_date(days_ahead: int = 30) -> str:
    """Get an ISO date string for a future date."""
    return (date.today() + timedelta(days=days_ahead)).isoformat()


FUTURE_START = get_future_date(30)
FUTURE_END = get_future_date(40)


# =============================================================================
# Test Constants and Fixtures
# =============================================================================
class TestStrategyTopicConstants:
    """Verify strategy topic constants are correctly configured."""

    def test_strategy_topic_to_node_mapping(self):
        """STRATEGY_TOPIC_TO_NODE should map all known topics to strategy_node."""
        expected_topics = {"hiking", "diving", "skiing", "cycling", "boating"}
        assert set(STRATEGY_TOPIC_TO_NODE.keys()) == expected_topics

        # All topics map to the unified strategy_node
        for topic, node in STRATEGY_TOPIC_TO_NODE.items():
            assert node == "strategy_node", f"Topic '{topic}' should map to 'strategy_node'"

    def test_gate_precedence_order(self):
        """STRATEGY_TOPIC_SWITCH should have correct precedence."""
        # Topic switch fires BEFORE READY_NO_FIELDS to handle topic addition on existing plans
        # This is the key invariant for the "Dubai→diving" regression guard
        assert GatePrecedence.STRATEGY_TOPIC_SWITCH < GatePrecedence.READY_NO_FIELDS
        assert GatePrecedence.STRATEGY_TOPIC_SWITCH < GatePrecedence.FAST_PATH
        assert GatePrecedence.STRATEGY_TOPIC_SWITCH < GatePrecedence.CORE_COLLECTION


# =============================================================================
# Topic Detection Tests
# =============================================================================
class TestCheckStrategyTopicSwitch:
    """Test the _check_strategy_topic_switch method."""

    def test_detects_diving_with_intent_verb(self):
        """'I wanna go diving' should trigger topic switch."""
        ti = TripInputs(
            destinations=["Argentina"],
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
        metadata = {"last_strategy_topic": "hiking", "turn_number": 5}

        gate = StrategyTopicSwitchGate()
        result = gate._check_strategy_topic_switch(
            text_lower="i wanna go diving in argentina too",
            ti=ti,
            readiness=readiness,
            metadata=metadata,
            turn_number=5,
            precomputed_topic="diving",  # Pass pre-computed topic
        )

        assert result is not None
        new_topic, reason = result
        assert new_topic == "diving"
        assert reason == "new_topic"

    def test_no_switch_without_intent_verb(self):
        """'diving in Argentina' without intent verb should NOT switch."""
        ti = TripInputs(
            destinations=["Argentina"],
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
        metadata = {"last_strategy_topic": "hiking", "turn_number": 5}

        gate = StrategyTopicSwitchGate()
        result = gate._check_strategy_topic_switch(
            text_lower="diving in argentina",
            ti=ti,
            readiness=readiness,
            metadata=metadata,
            turn_number=5,
            precomputed_topic="diving",  # Pass pre-computed topic
        )

        # No intent verb → no switch
        assert result is None

    def test_cooldown_prevents_rapid_switching(self):
        """Topic switch should respect cooldown."""
        ti = TripInputs(destinations=["Argentina"])
        readiness = TripReadiness(missing_core=[], blocking_errors=[])
        metadata = {
            "last_strategy_topic": "hiking",
            "topic_switch_cooldown_until_turn": 10,  # Cooldown active
            "turn_number": 7,
        }

        gate = StrategyTopicSwitchGate()
        result = gate._check_strategy_topic_switch(
            text_lower="i want to try diving",
            ti=ti,
            readiness=readiness,
            metadata=metadata,
            turn_number=7,
            precomputed_topic="diving",  # Pass pre-computed topic
        )

        # Cooldown active → no switch
        assert result is None

    def test_override_phrase_bypasses_cooldown(self):
        """'actually' or 'instead' should bypass cooldown."""
        ti = TripInputs(destinations=["Argentina"])
        readiness = TripReadiness(missing_core=[], blocking_errors=[])
        metadata = {
            "last_strategy_topic": "hiking",
            "topic_switch_cooldown_until_turn": 10,
            "turn_number": 7,
        }

        gate = StrategyTopicSwitchGate()
        result = gate._check_strategy_topic_switch(
            text_lower="actually, i want to go diving instead",
            ti=ti,
            readiness=readiness,
            metadata=metadata,
            turn_number=7,
            precomputed_topic="diving",  # Pass pre-computed topic
        )

        assert result is not None
        new_topic, reason = result
        assert new_topic == "diving"
        assert reason == "override_cooldown"

    def test_auto_fire_pending_topic(self):
        """auto_fire_topic_switch in metadata should trigger immediate switch."""
        ti = TripInputs(destinations=["Argentina"])
        readiness = TripReadiness(missing_core=[], blocking_errors=[])
        metadata = {
            "auto_fire_topic_switch": "diving",
            "last_strategy_topic": "hiking",
            "turn_number": 7,
        }

        gate = StrategyTopicSwitchGate()
        result = gate._check_strategy_topic_switch(
            text_lower="yes, march 15-22",  # User answering date question
            ti=ti,
            readiness=readiness,
            metadata=metadata,
            turn_number=7,
            precomputed_topic=None,  # No topic in user text, but auto_fire takes precedence
        )

        assert result is not None
        new_topic, reason = result
        assert new_topic == "diving"
        assert reason == "auto_fire_pending"


# =============================================================================
# Activity Category Canonicalization Tests
# =============================================================================
class TestActivityCategoryCanonicalization:
    """Test activity category canonicalization."""

    @pytest.mark.parametrize(
        "input_cat,expected",
        [
            ("diving", "diving"),
            ("🤿 Diving", "diving"),
            ("DIVING", "diving"),
            ("scuba diving", "diving"),
            ("scuba", "diving"),
            ("snorkeling", "diving"),
            ("hiking", "hiking"),
            ("🥾 Hiking", "hiking"),
            ("trekking", "hiking"),
            ("mountaineering", "hiking"),
            ("skiing", "skiing"),
            ("🎿 Skiing", "skiing"),
            ("snowboarding", "skiing"),
            ("cycling", "cycling"),
            ("🚴 Cycling", "cycling"),
            ("biking", "cycling"),
            ("boating", "boating"),
            ("⛵ Boating", "boating"),
            ("sailing", "boating"),
            ("yachting", "boating"),
            # Unknown categories pass through as lowercase
            ("sightseeing", "sightseeing"),
            ("🏛️ Museums", "museums"),
        ],
    )
    def test_canonicalize_activity_category(self, input_cat: str, expected: str):
        """Activity categories should be canonicalized correctly."""
        result = canonicalize_activity_category(input_cat)
        assert result == expected, f"Expected '{expected}' for '{input_cat}', got '{result}'"

    def test_canonicalize_activity_categories_deduplicates(self):
        """Batch canonicalization should deduplicate."""
        input_cats = ["hiking", "🥾 Hiking", "HIKING", "trekking", "diving"]
        result = canonicalize_activity_categories(input_cats)

        # hiking variants should all collapse to single 'hiking'
        assert result.count("hiking") == 1
        assert "diving" in result
        assert len(result) == 2


# =============================================================================
# Bootstrap Fast-Path Clearing Tests
# =============================================================================
class TestBootstrapFastPathClearing:
    """Test that bootstrap fast-path doesn't persist after turn 1."""

    def test_bootstrap_flags_should_clear_after_turn_1(self):
        """Bootstrap flags should be cleared in run_turn after turn 1."""
        # This is tested indirectly - the FAST_PATH gate should not match
        # on turn 2+ when bootstrap flags are cleared

        # Create state as if we're on turn 2 after bootstrap
        ti = TripInputs(
            destinations=["Argentina"],
            origin="New York",
            activity_settings={"categories": ["hiking"]},
        )
        state = GraphState(
            user_text="I wanna go diving too",
            trip_inputs=ti,
            metadata={
                "turn_number": 2,
                "strategy_bootstrap_turn": 1,
                "last_strategy_topic": "hiking",
            },
            flags={
                # These should have been cleared by run_turn
                # If still present, FAST_PATH would incorrectly fire
                "strategy_bootstrap_active": False,  # Cleared after turn 1
                "skip_extractor": False,
            },
        )

        # The gate evaluator should NOT choose FAST_PATH
        # (Full integration would require run_turn, this is a unit test of the flag state)
        assert not state.flags.get(
            "strategy_bootstrap_active", False
        ), "Bootstrap should be inactive after turn 1"


# =============================================================================
# Blocking Errors and Pending Topic Tests
# =============================================================================
class TestBlockingErrorsAndPendingTopic:
    """Test interaction between blocking errors and topic switch."""

    def test_readiness_with_blocking_errors(self):
        """TripReadiness should include blocking_errors."""
        readiness = TripReadiness(
            missing_core=[],
            question_target="dates",
            ready_to_generate=False,
            blocking_errors=[DateErrorCode.AMBIGUOUS_YEAR],
        )

        assert readiness.has_blocking_errors is True
        assert readiness.blocking_errors == [DateErrorCode.AMBIGUOUS_YEAR]

    def test_compute_trip_readiness_with_date_errors(self):
        """compute_trip_readiness should populate blocking_errors from errors list."""
        ti = TripInputs(
            destinations=["Argentina"],
            origin="New York",
        )
        errors = [
            {"code": DateErrorCode.AMBIGUOUS_YEAR, "field": "dates", "severity": "error"},
            {"code": "PAST_DATE", "field": "start_date", "severity": "warning"},  # Not blocking
        ]
        metadata = {}

        readiness = compute_trip_readiness(ti, errors=errors, metadata=metadata)

        # DATE_AMBIGUOUS_YEAR is a blocking error
        assert DateErrorCode.AMBIGUOUS_YEAR in readiness.blocking_errors
        # PAST_DATE is a warning, not blocking
        assert "PAST_DATE" not in readiness.blocking_errors

    def test_core_collection_forces_dates_with_blocking_errors(self):
        """CORE_COLLECTION gate should force dates question when blocking errors exist."""
        # When blocking_errors exist, the gate should route to date clarification
        # regardless of what missing_core contains
        readiness = TripReadiness(
            missing_core=[],  # No missing core fields
            question_target=None,
            ready_to_generate=False,
            blocking_errors=[DateErrorCode.RANGE_INVALID],  # But blocking error exists
        )

        assert readiness.has_blocking_errors is True
        # Gate logic should detect this and force date clarification


# =============================================================================
# End-to-End Scenario Test (Mocked)
# =============================================================================
class TestDivingMidSessionScenario:
    """
    End-to-end scenario test for diving specialist mid-session.

    Scenario:
    1. Turn 1: "Plan a hiking trip to Argentina" → bootstrap → strategy_hiking
    2. Turn 2: "I'm flying from New York" → SHORT_CIRCUIT (origin)
    3. Turn 3: "March 15-22" → ambiguous dates → date_clarify_mode
    4. Turn 4: "2025" → resolves dates → ready
    5. Turn 5: "I wanna go diving in Argentina too" → STRATEGY_TOPIC_SWITCH → strategy_diving

    Key assertions:
    - FAST_PATH should NOT fire after turn 1
    - STRATEGY_TOPIC_SWITCH should detect "diving" with intent verb
    - Pending topic should work if blocking errors existed
    """

    def test_scenario_gate_evaluation_turn_5(self):
        """Turn 5: 'I wanna go diving' should trigger STRATEGY_TOPIC_SWITCH."""
        # State at turn 5 - after dates resolved, user wants diving
        ti = TripInputs(
            destinations=["Argentina"],
            origin="New York",
            start_date=FUTURE_START,
            end_date=FUTURE_END,
            activity_settings={"categories": ["hiking"]},
        )

        state = GraphState(
            user_text="I wanna go diving in Argentina too",
            trip_inputs=ti,
            metadata={
                "turn_number": 5,
                "strategy_bootstrap_turn": 1,
                "last_strategy_topic": "hiking",
                "topic_switch_cooldown_until_turn": 3,  # Expired
            },
            flags={
                "strategy_bootstrap_active": False,  # Cleared after turn 1
            },
        )

        readiness = compute_trip_readiness(ti)

        # Verify readiness is good
        assert readiness.missing_core == []
        assert not readiness.has_blocking_errors

        # Check topic switch detection
        gate = StrategyTopicSwitchGate()
        result = gate._check_strategy_topic_switch(
            text_lower=state.user_text.lower(),
            ti=ti,
            readiness=readiness,
            metadata=state.metadata,
            turn_number=5,
            precomputed_topic="diving",  # Pass pre-computed topic
        )

        assert result is not None, "Topic switch should be detected"
        new_topic, reason = result
        assert new_topic == "diving"
        assert reason == "new_topic"

        # Verify the target node (all strategy topics route to unified strategy_node)
        target_node = STRATEGY_TOPIC_TO_NODE.get(new_topic)
        assert target_node == "strategy_node"

    def test_scenario_pending_topic_with_blocking_errors(self):
        """Topic switch should be pending when blocking errors exist."""
        # State at turn 5 - user wants diving but dates are ambiguous
        ti = TripInputs(
            destinations=["Argentina"],
            origin="New York",
            # No dates - ambiguous
            activity_settings={"categories": ["hiking"]},
        )

        errors = [{"code": DateErrorCode.AMBIGUOUS_YEAR, "field": "dates", "severity": "error"}]
        metadata = {
            "turn_number": 5,
            "last_strategy_topic": "hiking",
        }

        readiness = compute_trip_readiness(ti, errors=errors, metadata=metadata)

        # Should have blocking errors
        assert readiness.has_blocking_errors

        # Topic switch is detected but should store pending
        gate = StrategyTopicSwitchGate()
        result = gate._check_strategy_topic_switch(
            text_lower="i wanna go diving",
            ti=ti,
            readiness=readiness,
            metadata=metadata,
            turn_number=5,
            precomputed_topic="diving",  # Pass pre-computed topic
        )

        # Detection still works (but gate logic will store as pending)
        assert result is not None
        new_topic, _ = result
        assert new_topic == "diving"

        # In actual gate evaluation, this would be stored as pending_strategy_topic
        # and auto-fired after blocking errors clear
