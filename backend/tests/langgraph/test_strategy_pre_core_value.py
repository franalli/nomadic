"""
Unit tests for STRATEGY_PRE_CORE_VALUE gate functionality in plan_graph.py.

Tests cover:
- STRATEGY_PRE_CORE_VALUE gate at precedence 4 (between SPECIALIST_PRE_CORE and CORE_COLLECTION)
- Strategy topic detection for open-ended queries
- Value-first response with single clarifying question
- Context-aware question ordering (prefer dates over destinations)
- Loop guard for repeated questions
- Fallback to required_fields on errors
- "Questions only" bypass
"""

import pytest

from app.plan_graph import (
    GateEvaluator,
    GatePrecedence,
    GraphState,
    TripInputs,
    _infer_trip_shape,
    compute_trip_readiness,
)
from app.planner.nodes.strategy import (
    _should_escalate_from_stage0,
    _track_strategy_pre_core_question,
)


class TestStrategyPreCoreGatePrecedence:
    """Test gate precedence ordering."""

    def test_gate_precedence_order(self):
        """Verify STRATEGY_PRE_CORE_VALUE is between SPECIALIST_PRE_CORE and CORE_COLLECTION."""
        assert GatePrecedence.SPECIALIST_PRE_CORE < GatePrecedence.STRATEGY_PRE_CORE_VALUE
        assert GatePrecedence.STRATEGY_PRE_CORE_VALUE < GatePrecedence.CORE_COLLECTION

    def test_all_gate_precedence_values_unique(self):
        """Verify all gate precedence values are unique."""
        values = [g.value for g in GatePrecedence]
        assert len(values) == len(set(values)), "Duplicate gate precedence values found"


class TestStrategyPreCoreValueDetection:
    """Test strategy topic detection for pre-core value routing."""

    @pytest.mark.parametrize(
        "input_text,expected_topic",
        [
            # Hiking keywords
            ("Plan an adventure trip with hiking", "hiking"),
            ("I want to go on a trek", "hiking"),
            ("Looking for mountain trails", "hiking"),
            # Skiing keywords
            ("I want a skiing vacation", "skiing"),
            ("Snowboarding trip ideas", "skiing"),
            # Diving keywords
            ("Planning a scuba diving trip", "diving"),
            ("I want to snorkel somewhere", "diving"),
            # Cycling keywords
            ("Biking tour ideas", "cycling"),
            ("Cycling vacation planning", "cycling"),
            # Boating keywords
            ("I want to go sailing", "boating"),
            ("Yacht trip planning", "boating"),
        ],
    )
    def test_strategy_topic_detection(self, input_text: str, expected_topic: str):
        """Test that strategy topics are detected correctly from user text."""
        ti = TripInputs()  # Empty - no destinations
        readiness = compute_trip_readiness(ti)
        extraction_conf = {}
        metadata = {}  # No active question - won't trigger suppression

        result = GateEvaluator._check_strategy_pre_core_value(
            input_text.lower(), ti, readiness, extraction_conf, metadata
        )

        assert result is not None, f"Expected topic '{expected_topic}' for '{input_text}'"
        topic, question_target = result
        assert topic == expected_topic


class TestStrategyPreCoreValueGating:
    """Test gate firing conditions."""

    def test_fires_when_strategy_topic_and_no_destinations(self):
        """Gate should fire when strategy topic detected but no destinations."""
        state = GraphState(
            user_text="Plan an adventure trip with hiking",
            trip_inputs=TripInputs(),  # No destinations
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # Should route to strategy_node via STRATEGY_PRE_CORE_VALUE gate
        assert gate_result.gate_fired == GatePrecedence.STRATEGY_PRE_CORE_VALUE
        assert gate_result.destination == "strategy_node"
        assert gate_result.metadata_updates.get("strategy_stage") == 0

    def test_does_not_fire_when_destinations_present(self):
        """Gate should NOT fire when destinations are already set."""
        state = GraphState(
            user_text="Plan a hiking trip",
            trip_inputs=TripInputs(destinations=["Swiss Alps"]),
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # Should NOT fire STRATEGY_PRE_CORE_VALUE (destinations present)
        assert gate_result.gate_fired != GatePrecedence.STRATEGY_PRE_CORE_VALUE

    def test_does_not_fire_when_questions_only_requested(self):
        """Gate should NOT fire when user asks for 'questions only'."""
        questions_only_phrases = [
            "ask me questions",
            "what do you need from me",
            "what info do you need",
            "just ask me",
        ]

        for phrase in questions_only_phrases:
            state = GraphState(
                user_text=f"Plan a hiking trip - {phrase}",
                trip_inputs=TripInputs(),
                metadata={},
                flags={},
            )

            gate_result = GateEvaluator.evaluate(state)

            assert (
                gate_result.gate_fired != GatePrecedence.STRATEGY_PRE_CORE_VALUE
            ), f"Gate should not fire with phrase: {phrase}"


class TestQuestionTargetPriority:
    """Test context-aware question ordering."""

    def test_prefers_dates_when_strategy_topic_no_destinations(self):
        """Should ask about dates before destinations for open-ended queries."""
        ti = TripInputs()  # No destinations, no dates
        readiness = compute_trip_readiness(ti)
        extraction_conf = {}
        metadata = {}  # No active question - won't trigger suppression

        result = GateEvaluator._check_strategy_pre_core_value(
            "plan a hiking adventure", ti, readiness, extraction_conf, metadata
        )

        assert result is not None
        topic, question_target = result
        assert question_target == "dates", "Should ask about dates first"

    def test_asks_origin_after_dates_set(self):
        """Should ask about origin when dates are set."""
        ti = TripInputs(start_date="2025-06-01")  # Has dates, no origin
        readiness = compute_trip_readiness(ti)
        extraction_conf = {}
        metadata = {}  # No active question - won't trigger suppression

        result = GateEvaluator._check_strategy_pre_core_value(
            "plan a hiking adventure", ti, readiness, extraction_conf, metadata
        )

        assert result is not None
        topic, question_target = result
        assert question_target == "origin", "Should ask about origin after dates"

    def test_asks_destination_last(self):
        """Should ask about destination only after dates and origin set."""
        ti = TripInputs(start_date="2025-06-01", origin="London")
        readiness = compute_trip_readiness(ti)
        extraction_conf = {}
        metadata = {}  # No active question - won't trigger suppression

        result = GateEvaluator._check_strategy_pre_core_value(
            "plan a hiking adventure", ti, readiness, extraction_conf, metadata
        )

        assert result is not None
        topic, question_target = result
        assert question_target == "destinations", "Should ask about destination last"


class TestTripShapeInference:
    """Test deterministic trip shape inference."""

    def test_infers_adventure_outdoors_style(self):
        """Should infer adventure_outdoors style from hiking keywords."""
        result = _infer_trip_shape("I want an adventurous hiking trip", "hiking")

        assert result.get("trip_style") == "adventure_outdoors"
        assert "hiking" in result.get("activity_categories", [])
        assert result.get("pace") == "active"

    def test_infers_beach_relaxation_style(self):
        """Should infer beach_relaxation style from beach keywords."""
        result = _infer_trip_shape("Looking for a relaxing beach vacation", None)

        assert result.get("trip_style") == "beach_relaxation"
        assert "beach" in result.get("activity_categories", [])
        assert result.get("pace") == "relaxed"

    def test_infers_high_flexibility_for_vague_queries(self):
        """Should infer high flexibility for vague/open-ended queries."""
        result = _infer_trip_shape("somewhere good for hiking", "hiking")

        assert result.get("planning_flexibility") == "high"

    def test_empty_result_for_empty_text(self):
        """Should return empty dict for empty text."""
        result = _infer_trip_shape("", None)
        assert result == {}


class TestLoopGuard:
    """Test loop guard for stage 0 questions."""

    def test_tracks_questions(self):
        """Should track questions asked in metadata."""
        state = GraphState(
            user_text="hiking trip",
            trip_inputs=TripInputs(),
            metadata={},
            flags={},
        )

        _track_strategy_pre_core_question(state, "start_date")

        assert "strategy_pre_core_questions" in state.metadata
        assert "start_date" in state.metadata["strategy_pre_core_questions"]

    def test_escalates_after_two_ignored_questions(self):
        """Should escalate to required_fields after 2 ignored questions."""
        state = GraphState(
            user_text="hiking trip",
            trip_inputs=TripInputs(),
            metadata={"strategy_pre_core_questions": ["start_date", "origin"]},
            flags={},
        )

        assert _should_escalate_from_stage0(state) is True

    def test_does_not_escalate_for_first_question(self):
        """Should not escalate for first question."""
        state = GraphState(
            user_text="hiking trip",
            trip_inputs=TripInputs(),
            metadata={"strategy_pre_core_questions": ["start_date"]},
            flags={},
        )

        assert _should_escalate_from_stage0(state) is False


class TestPreferDateFirst:
    """Test context-aware question ordering in compute_trip_readiness."""

    def test_normal_order_asks_destination_first(self):
        """Without prefer_date_first, should ask destination first."""
        ti = TripInputs()  # No destinations, no dates
        readiness = compute_trip_readiness(ti, prefer_date_first=False)

        assert readiness.question_target == "destinations"

    def test_prefer_date_first_asks_dates_first(self):
        """With prefer_date_first, should ask dates first."""
        ti = TripInputs()  # No destinations, no dates
        readiness = compute_trip_readiness(ti, prefer_date_first=True)

        assert readiness.question_target == "dates"

    def test_prefer_date_first_only_affects_missing_both(self):
        """prefer_date_first only matters when both destinations and dates missing."""
        # When only destinations missing, should still ask for destinations
        ti = TripInputs(start_date="2025-06-01")
        readiness = compute_trip_readiness(ti, prefer_date_first=True)

        assert readiness.question_target == "destinations"


class TestSpecificPromptBehavior:
    """Test that specific prompts still work normally."""

    def test_specific_destination_bypasses_strategy_pre_core(self):
        """Prompts with specific destinations should go to normal flow."""
        state = GraphState(
            user_text="Plan a trip to Patagonia in March",
            trip_inputs=TripInputs(destinations=["Patagonia"]),  # Has destination
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # Should NOT fire STRATEGY_PRE_CORE_VALUE
        assert gate_result.gate_fired != GatePrecedence.STRATEGY_PRE_CORE_VALUE


class TestGateShadowingPrevention:
    """Test that STRATEGY_PRE_CORE_VALUE is not shadowed by SPECIALIST_PRE_CORE."""

    def test_strategy_topic_with_activities_keyword_routes_to_strategy(self):
        """
        Critical regression test: 'hiking and outdoor activities' should route
        to strategy_node, NOT activities_node.

        The word 'activities' matches SPECIALIST_PRE_CORE_KEYWORDS, but the
        strategy topic 'hiking' should take precedence.
        """
        state = GraphState(
            user_text="Plan an adventure trip with hiking and outdoor activities",
            trip_inputs=TripInputs(),  # No destinations
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # CRITICAL: Must route to strategy_node, NOT activities_node
        assert gate_result.destination == "strategy_node", (
            f"Expected strategy_node but got {gate_result.destination}. "
            f"SPECIALIST_PRE_CORE is shadowing STRATEGY_PRE_CORE_VALUE"
        )
        assert gate_result.gate_fired == GatePrecedence.STRATEGY_PRE_CORE_VALUE

    def test_activities_intent_with_destination_routes_to_activities(self):
        """
        'What hikes should I do in Chamonix?' has a destination, so should
        route to activities_node (pre-core or full depending on core fields).
        """
        state = GraphState(
            user_text="What hikes should I do in Chamonix?",
            trip_inputs=TripInputs(destinations=["Chamonix"]),
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # Should NOT be STRATEGY_PRE_CORE_VALUE (has destinations)
        assert gate_result.gate_fired != GatePrecedence.STRATEGY_PRE_CORE_VALUE

    def test_specialist_pre_core_blocked_when_strategy_eligible(self):
        """
        When strategy_pre_core is eligible, SPECIALIST_PRE_CORE should not win
        even if specialist keywords match.
        """
        # Test multiple phrases that have both strategy and specialist keywords
        test_cases = [
            "Plan a hiking trip with outdoor activities",
            "I want skiing activities",
            "Biking tour with activities",
            "Diving activities somewhere tropical",
        ]

        for text in test_cases:
            state = GraphState(
                user_text=text,
                trip_inputs=TripInputs(),  # No destinations
                metadata={},
                flags={},
            )

            gate_result = GateEvaluator.evaluate(state)

            assert gate_result.gate_fired != GatePrecedence.SPECIALIST_PRE_CORE, (
                f"SPECIALIST_PRE_CORE should not win for '{text}'. "
                f"Got gate={gate_result.gate_fired}, dest={gate_result.destination}"
            )

    def test_pure_activities_query_still_routes_to_activities(self):
        """
        Pure activities query without strategy topic should still go to activities.
        """
        state = GraphState(
            user_text="What activities can I do there?",
            trip_inputs=TripInputs(destinations=["Paris"]),  # Has destination
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # This is a pure activities query with destination, should go to activities
        # (either pre-core or full depending on other core fields)
        assert gate_result.destination in ["activities_node", "required_fields_node"]


class TestGatePrecedenceGuard:
    """Guard tests to ensure gate ordering is correct and stable."""

    def test_gate_precedence_enum_values_are_sorted(self):
        """
        Gate precedence enum values must be in ascending order.
        This catches any accidental reordering of gate definitions.
        """
        gates_in_order = [
            GatePrecedence.SHORT_CIRCUIT,
            GatePrecedence.FAST_PATH,
            GatePrecedence.SPECIALIST_PRE_CORE,
            GatePrecedence.STRATEGY_PRE_CORE_VALUE,
            GatePrecedence.CORE_COLLECTION,
            GatePrecedence.HIGH_CONFIDENCE,
            GatePrecedence.QUESTION_KEYWORD,
            GatePrecedence.KEYWORD_HEURISTIC,
            GatePrecedence.SCORING_ROUTER,
            GatePrecedence.ROUTER_LLM,
        ]

        for i in range(len(gates_in_order) - 1):
            current = gates_in_order[i]
            next_gate = gates_in_order[i + 1]
            assert current.value < next_gate.value, (
                f"Gate ordering violated: {current.name}({current.value}) should be "
                f"less than {next_gate.name}({next_gate.value})"
            )

    def test_strategy_pre_core_value_is_between_specialist_and_core(self):
        """
        STRATEGY_PRE_CORE_VALUE must be evaluated after SPECIALIST_PRE_CORE
        but before CORE_COLLECTION. This is the key ordering invariant.
        It now includes STRATEGY_TOPIC_SWITCH between
        SPECIALIST_PRE_CORE and STRATEGY_PRE_CORE_VALUE.

        Note: Gate precedence values use increments of 10 for intuitive ordering.
        """
        # Verify the ordering invariant (lower value = higher priority)
        assert GatePrecedence.SPECIALIST_PRE_CORE.value < GatePrecedence.STRATEGY_TOPIC_SWITCH.value
        assert (
            GatePrecedence.STRATEGY_TOPIC_SWITCH.value
            < GatePrecedence.STRATEGY_PRE_CORE_VALUE.value
        )
        assert GatePrecedence.STRATEGY_PRE_CORE_VALUE.value < GatePrecedence.CORE_COLLECTION.value
        # Verify specific values (increments of 10)
        assert GatePrecedence.SPECIALIST_PRE_CORE.value == 60
        assert GatePrecedence.STRATEGY_TOPIC_SWITCH.value == 70
        assert GatePrecedence.STRATEGY_PRE_CORE_VALUE.value == 80
        assert GatePrecedence.CORE_COLLECTION.value == 90

    def test_is_strategy_pre_core_eligible_helper(self):
        """Test the eligibility helper used to suppress SPECIALIST_PRE_CORE."""
        # Eligible case: strategy topic + no destinations + core incomplete
        ti = TripInputs()
        readiness = compute_trip_readiness(ti)
        eligible = GateEvaluator._is_strategy_pre_core_eligible(
            "hiking trip with activities", ti, readiness
        )
        assert eligible is True, "Should be eligible for strategy pre-core"

        # Not eligible: has destinations
        ti_with_dest = TripInputs(destinations=["Alps"])
        readiness_with_dest = compute_trip_readiness(ti_with_dest)
        not_eligible = GateEvaluator._is_strategy_pre_core_eligible(
            "hiking trip", ti_with_dest, readiness_with_dest
        )
        assert not_eligible is False, "Should NOT be eligible when destinations present"

        # Not eligible: questions only phrase
        questions_eligible = GateEvaluator._is_strategy_pre_core_eligible(
            "hiking trip - ask me questions", ti, readiness
        )
        assert questions_eligible is False, "Should NOT be eligible with 'ask me questions'"
