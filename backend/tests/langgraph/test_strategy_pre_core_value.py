"""
Unit tests for STRATEGY_PRE_CORE_VALUE gate functionality in plan_graph.py.

Tests cover:
- STRATEGY_PRE_CORE_VALUE gate at precedence 80 (between STRATEGY_TOPIC_SWITCH and CORE_COLLECTION)
- Strategy topic detection for open-ended queries
- Duration-aware strategy responses (requires ALL core fields OR explicit request)
- Value-first response with single clarifying question
- Context-aware question ordering (prefer dates over destinations)
- Loop guard for repeated questions
- Fallback to required_fields on errors
- "Questions only" bypass
- Explicit itinerary request detection

Note: After the January 2026 routing improvements, STRATEGY_PRE_CORE_VALUE requires:
1. ALL core fields (origin, destinations, dates, AND travelers), OR
2. Explicit itinerary request (e.g., "plan my trip", "create an itinerary")

This prevents premature itinerary generation while core fields are still missing.
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
from app.planner.gates import GateContext
from app.planner.gates.implementations import StrategyPreCoreValueGate
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
    """Test strategy topic detection for pre-core value routing.

    Note: Gate now requires ALL core fields (origin, destinations, dates, travelers)
    OR explicit itinerary request. Tests provide all core fields.
    """

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
        """Test that strategy topics are detected correctly from user text.

        Gate requires ALL core fields to fire, so we provide all of them.
        """
        # Provide ALL core fields (required for gate to fire without explicit request)
        ti = TripInputs(
            destinations=["Swiss Alps"],
            start_date="2026-06-01",
            origin="London",
            adults=2,
        )
        state = GraphState(
            user_text=input_text,
            trip_inputs=ti,
            metadata={},  # No active question - won't trigger suppression
            flags={},
        )
        readiness = compute_trip_readiness(ti)
        ctx = GateContext.from_state(state, readiness)

        gate = StrategyPreCoreValueGate()
        result = gate.evaluate(ctx)

        assert result is not None, f"Expected topic '{expected_topic}' for '{input_text}'"
        assert result.strategy_topic == expected_topic


class TestStrategyPreCoreValueGating:
    """Test gate firing conditions.

    Note: Gate now requires ALL core fields (origin, destinations, dates, travelers)
    OR explicit itinerary request before firing.
    """

    def test_does_not_fire_without_dates(self):
        """Gate should NOT fire when dates are missing (no explicit request)."""
        state = GraphState(
            user_text="Plan an adventure trip with hiking",
            trip_inputs=TripInputs(
                destinations=["Alps"],
                origin="London",
                adults=2,
            ),  # Has everything but dates
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # Should NOT route via STRATEGY_PRE_CORE_VALUE (no dates, no explicit request)
        assert gate_result.gate_fired != GatePrecedence.STRATEGY_PRE_CORE_VALUE

    def test_does_not_fire_without_destinations(self):
        """Gate should NOT fire when destinations are missing (no explicit request)."""
        state = GraphState(
            user_text="Plan an adventure trip with hiking",
            trip_inputs=TripInputs(
                start_date="2026-06-01",
                origin="London",
                adults=2,
            ),  # Has everything but destinations
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # Should NOT route via STRATEGY_PRE_CORE_VALUE (no destinations, no explicit request)
        assert gate_result.gate_fired != GatePrecedence.STRATEGY_PRE_CORE_VALUE

    def test_does_not_fire_without_origin(self):
        """Gate should NOT fire when origin is missing (no explicit request)."""
        state = GraphState(
            user_text="Plan a hiking trip",
            trip_inputs=TripInputs(
                destinations=["Swiss Alps"],
                start_date="2026-06-01",
                adults=2,
            ),  # Has everything but origin
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # Should NOT route via STRATEGY_PRE_CORE_VALUE (no origin, no explicit request)
        assert gate_result.gate_fired != GatePrecedence.STRATEGY_PRE_CORE_VALUE

    def test_does_not_fire_without_travelers(self):
        """Gate should NOT fire when travelers are missing (no explicit request)."""
        state = GraphState(
            user_text="Plan a hiking trip",
            trip_inputs=TripInputs(
                destinations=["Swiss Alps"],
                start_date="2026-06-01",
                origin="London",
            ),  # Has everything but travelers
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # Should NOT route via STRATEGY_PRE_CORE_VALUE (no travelers, no explicit request)
        assert gate_result.gate_fired != GatePrecedence.STRATEGY_PRE_CORE_VALUE

    def test_fires_with_all_core_fields(self):
        """Gate should route to strategy when ALL core fields are present.

        Note: When all fields are complete, READY_NO_FIELDS (precedence 40)
        may fire before STRATEGY_PRE_CORE_VALUE (precedence 80), but both
        route to strategy_node with a strategy topic. We verify the destination.
        """
        state = GraphState(
            user_text="Plan a hiking trip",
            trip_inputs=TripInputs(
                destinations=["Swiss Alps"],
                start_date="2026-06-01",
                origin="London",
                adults=2,
            ),  # All core fields present
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # Should route to strategy_node (either via READY_NO_FIELDS or STRATEGY_PRE_CORE_VALUE)
        assert gate_result.destination == "strategy_node"
        assert gate_result.strategy_topic == "hiking"

    def test_fires_with_explicit_itinerary_request(self):
        """Gate should fire with explicit itinerary request even without all fields."""
        state = GraphState(
            user_text="Help me plan my hiking trip",  # Explicit request phrase
            trip_inputs=TripInputs(
                destinations=["Swiss Alps"],
                start_date="2026-06-01",
            ),  # Missing origin and travelers
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # Should fire STRATEGY_PRE_CORE_VALUE (has explicit request)
        assert gate_result.gate_fired == GatePrecedence.STRATEGY_PRE_CORE_VALUE
        assert gate_result.destination == "strategy_node"
        assert "explicit_request" in gate_result.reason

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
                trip_inputs=TripInputs(
                    destinations=["Alps"],
                    start_date="2026-06-01",
                    origin="London",
                    adults=2,
                ),  # All fields present
                metadata={},
                flags={},
            )

            gate_result = GateEvaluator.evaluate(state)

            assert (
                gate_result.gate_fired != GatePrecedence.STRATEGY_PRE_CORE_VALUE
            ), f"Gate should not fire with phrase: {phrase}"


class TestQuestionTargetPriority:
    """Test context-aware question ordering.

    Note: Gate now requires ALL core fields OR explicit request.
    """

    def test_does_not_fire_when_only_origin_missing(self):
        """Gate should NOT fire when origin is missing (without explicit request)."""
        ti = TripInputs(
            destinations=["Swiss Alps"],
            start_date="2026-06-01",
            adults=2,
        )  # Has dates + destinations + travelers, missing origin
        state = GraphState(
            user_text="plan a hiking adventure",
            trip_inputs=ti,
            metadata={},  # No active question - won't trigger suppression
            flags={},
        )
        readiness = compute_trip_readiness(ti)
        ctx = GateContext.from_state(state, readiness)

        gate = StrategyPreCoreValueGate()
        result = gate.evaluate(ctx)

        # Should NOT fire - missing origin and no explicit request
        assert result is None, "Gate should not fire when origin is missing"

    def test_fires_when_all_core_complete(self):
        """Gate SHOULD fire when all core fields are complete."""
        ti = TripInputs(
            destinations=["Swiss Alps"],
            start_date="2026-06-01",
            origin="London",
            adults=2,
        )  # All core fields complete
        state = GraphState(
            user_text="plan a hiking adventure",
            trip_inputs=ti,
            metadata={},  # No active question - won't trigger suppression
            flags={},
        )
        readiness = compute_trip_readiness(ti)
        ctx = GateContext.from_state(state, readiness)

        gate = StrategyPreCoreValueGate()
        result = gate.evaluate(ctx)

        # Should fire when all core fields are complete
        assert result is not None, "Gate should fire when all core fields are complete"
        assert result.destination == "strategy_node"
        assert "all_fields_complete" in result.reason

    def test_fires_with_explicit_request_and_missing_fields(self):
        """Gate should fire with explicit request even when fields missing."""
        ti = TripInputs(
            destinations=["Swiss Alps"],
            start_date="2026-06-01",
        )  # Missing origin and travelers
        state = GraphState(
            user_text="help me plan my hiking adventure",  # Explicit request
            trip_inputs=ti,
            metadata={},
            flags={},
        )
        readiness = compute_trip_readiness(ti)
        ctx = GateContext.from_state(state, readiness)

        gate = StrategyPreCoreValueGate()
        result = gate.evaluate(ctx)

        # Should fire with explicit request
        assert result is not None, "Gate should fire with explicit itinerary request"
        assert result.destination == "strategy_node"
        assert "explicit_request" in result.reason
        # Should still track missing fields for question_target
        assert result.question_target == "origin", "Should ask about origin"


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
        ti = TripInputs(start_date="2026-06-01")
        readiness = compute_trip_readiness(ti, prefer_date_first=True)

        assert readiness.question_target == "destinations"


class TestSpecificPromptBehavior:
    """Test that specific prompts still work normally."""

    def test_complete_state_with_strategy_topic_routes_to_strategy(self):
        """Prompts with all core fields AND strategy topic should route to strategy.

        Note: When all fields complete, may route via READY_NO_FIELDS or STRATEGY_PRE_CORE_VALUE.
        """
        state = GraphState(
            user_text="Plan a hiking trip to Patagonia",  # Has strategy topic
            trip_inputs=TripInputs(
                destinations=["Patagonia"],
                start_date="2026-03-01",
                end_date="2026-03-15",
                origin="London",
                adults=2,
            ),  # All core fields complete
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # SHOULD route to strategy_node (has all core fields + strategy topic)
        assert gate_result.destination == "strategy_node"
        assert gate_result.strategy_topic == "hiking"

    def test_complete_state_without_strategy_topic_bypasses_strategy(self):
        """Prompts with all core fields but NO strategy topic should bypass strategy_pre_core."""
        state = GraphState(
            user_text="Plan a trip to Paris",  # No strategy topic (no hiking/skiing/etc.)
            trip_inputs=TripInputs(
                destinations=["Paris"],
                start_date="2026-03-01",
                end_date="2026-03-15",
                origin="London",
                adults=2,
            ),  # All core fields complete
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # Should NOT fire STRATEGY_PRE_CORE_VALUE (no strategy topic)
        assert gate_result.gate_fired != GatePrecedence.STRATEGY_PRE_CORE_VALUE


class TestGateShadowingPrevention:
    """Test that STRATEGY_PRE_CORE_VALUE is not shadowed by SPECIALIST_PRE_CORE.

    Note: Gate now requires ALL core fields OR explicit request.
    """

    def test_strategy_topic_with_activities_keyword_routes_to_strategy(self):
        """
        Critical regression test: 'hiking and outdoor activities' should route
        to strategy_node, NOT activities_node.

        The word 'activities' matches SPECIALIST_PRE_CORE_KEYWORDS, but the
        strategy topic 'hiking' should take precedence when conditions are met.
        """
        state = GraphState(
            user_text="Plan an adventure trip with hiking and outdoor activities",
            trip_inputs=TripInputs(
                destinations=["Alps"],
                start_date="2026-06-01",
                origin="London",
                adults=2,
            ),  # Has ALL core fields
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # CRITICAL: Must route to strategy_node, NOT activities_node
        # (may be via READY_NO_FIELDS or STRATEGY_PRE_CORE_VALUE when fields complete)
        assert gate_result.destination == "strategy_node", (
            f"Expected strategy_node but got {gate_result.destination}. "
            f"SPECIALIST_PRE_CORE is shadowing strategy routing"
        )
        assert gate_result.strategy_topic == "hiking"

    def test_hiking_query_with_all_fields_routes_to_strategy(self):
        """
        'What hikes should I do in Chamonix?' has a hiking strategy topic,
        so should route to strategy_node when all core fields are present.
        """
        state = GraphState(
            user_text="What hikes should I do in Chamonix?",
            trip_inputs=TripInputs(
                destinations=["Chamonix"],
                start_date="2026-06-01",
                origin="London",
                adults=2,
            ),  # Has ALL core fields
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # With hiking strategy topic + all core fields, should route to strategy_node
        # (may be via READY_NO_FIELDS or STRATEGY_PRE_CORE_VALUE when fields complete)
        assert gate_result.destination == "strategy_node"
        assert gate_result.strategy_topic == "hiking"

    def test_specialist_pre_core_wins_when_strategy_missing_fields(self):
        """
        When strategy_pre_core is not eligible (missing fields, no explicit request),
        SPECIALIST_PRE_CORE should win if specialist keywords match.
        """
        # Test phrases that have strategy keywords but missing core fields
        state = GraphState(
            user_text="Plan a hiking trip with outdoor activities",
            trip_inputs=TripInputs(
                destinations=["Alps"],
                start_date="2026-06-01",
            ),  # Missing origin and travelers
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # Without all fields and no explicit request, should NOT fire strategy
        assert gate_result.gate_fired != GatePrecedence.STRATEGY_PRE_CORE_VALUE, (
            f"STRATEGY_PRE_CORE_VALUE should not win without all fields. "
            f"Got gate={gate_result.gate_fired}, dest={gate_result.destination}"
        )

    def test_strategy_fires_with_explicit_request_missing_fields(self):
        """Strategy should fire with explicit request even if fields missing."""
        state = GraphState(
            user_text="Help me plan a hiking trip with activities",  # Explicit request
            trip_inputs=TripInputs(
                destinations=["Alps"],
                start_date="2026-06-01",
            ),  # Missing origin and travelers
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # With explicit request, should fire strategy
        assert gate_result.gate_fired == GatePrecedence.STRATEGY_PRE_CORE_VALUE
        assert gate_result.destination == "strategy_node"

    def test_pure_activities_query_routes_appropriately(self):
        """
        Pure activities query without strategy topic should NOT go via strategy gates.
        """
        state = GraphState(
            user_text="What activities can I do in Paris?",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                start_date="2026-06-01",
                origin="London",
                adults=2,
            ),  # Has all fields but no strategy topic (no hiking/skiing/etc.)
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # This is a pure activities query without strategy keywords,
        # it should NOT fire STRATEGY_PRE_CORE_VALUE specifically
        assert gate_result.gate_fired != GatePrecedence.STRATEGY_PRE_CORE_VALUE
        # Note: may route via other gates like READY_NO_FIELDS or QUESTION_KEYWORD


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
            GatePrecedence.QUESTION_KEYWORD,
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
        """Test gate eligibility by checking if evaluate() returns a result.

        Gate now requires ALL core fields OR explicit itinerary request.
        """
        gate = StrategyPreCoreValueGate()

        # Eligible case: strategy topic + ALL core fields
        ti = TripInputs(
            destinations=["Alps"],
            start_date="2026-06-01",
            origin="London",
            adults=2,
        )
        state = GraphState(
            user_text="hiking trip with activities",
            trip_inputs=ti,
            metadata={},
            flags={},
        )
        readiness = compute_trip_readiness(ti)
        ctx = GateContext.from_state(state, readiness)
        result = gate.evaluate(ctx)
        assert result is not None, "Should be eligible for strategy pre-core (has all core fields)"

        # Not eligible: missing origin (no explicit request)
        ti_no_origin = TripInputs(
            destinations=["Alps"],
            start_date="2026-06-01",
            adults=2,
        )
        state_no_origin = GraphState(
            user_text="hiking trip",
            trip_inputs=ti_no_origin,
            metadata={},
            flags={},
        )
        readiness_no_origin = compute_trip_readiness(ti_no_origin)
        ctx_no_origin = GateContext.from_state(state_no_origin, readiness_no_origin)
        result_no_origin = gate.evaluate(ctx_no_origin)
        assert (
            result_no_origin is None
        ), "Should NOT be eligible without origin (no explicit request)"

        # Eligible: missing fields but has explicit request
        ti_partial = TripInputs(
            destinations=["Alps"],
            start_date="2026-06-01",
        )
        state_explicit = GraphState(
            user_text="help me plan my hiking trip",  # Explicit request
            trip_inputs=ti_partial,
            metadata={},
            flags={},
        )
        readiness_partial = compute_trip_readiness(ti_partial)
        ctx_explicit = GateContext.from_state(state_explicit, readiness_partial)
        result_explicit = gate.evaluate(ctx_explicit)
        assert result_explicit is not None, "Should be eligible with explicit itinerary request"

        # Not eligible: questions only phrase (even with all fields)
        state_questions = GraphState(
            user_text="hiking trip - ask me questions",
            trip_inputs=ti,
            metadata={},
            flags={},
        )
        ctx_questions = GateContext.from_state(state_questions, readiness)
        result_questions = gate.evaluate(ctx_questions)
        assert result_questions is None, "Should NOT be eligible with 'ask me questions'"


# =============================================================================
# Destination-Specific Templates Tests (Tier 10.22)
# =============================================================================
class TestDestinationSpecificTemplates:
    """Tests for DESTINATION_TOPIC_TEMPLATES expert knowledge system."""

    def test_destination_topic_templates_populated(self):
        """DESTINATION_TOPIC_TEMPLATES should have entries for popular combinations."""
        from app.planner.nodes.strategy.stage0 import DESTINATION_TOPIC_TEMPLATES

        # Should have at least 10 popular destination+topic combinations
        assert len(DESTINATION_TOPIC_TEMPLATES) >= 10

        # Check some expected entries exist
        expected_entries = [
            ("patagonia", "hiking"),
            ("maldives", "diving"),
            ("switzerland", "skiing"),
            ("croatia", "boating"),
            ("france", "cycling"),
        ]
        for entry in expected_entries:
            assert entry in DESTINATION_TOPIC_TEMPLATES, f"Missing entry: {entry}"

    def test_get_destination_specific_template_returns_expert_content(self):
        """get_destination_specific_template should return expert content for known destinations."""
        from app.planner.nodes.strategy.stage0 import get_destination_specific_template

        # Patagonia hiking should return expert template
        result = get_destination_specific_template("hiking", ["Patagonia"])
        assert result is not None
        assert "Torres del Paine" in result
        assert "refugios" in result.lower() or "Refugios" in result

        # Maldives diving should return expert template
        result = get_destination_specific_template("diving", ["Maldives"])
        assert result is not None
        assert "Manta ray" in result or "manta" in result.lower()
        assert "liveaboard" in result.lower()

    def test_get_destination_specific_template_partial_match(self):
        """get_destination_specific_template should match partial destination names."""
        from app.planner.nodes.strategy.stage0 import get_destination_specific_template

        # "Torres del Paine, Patagonia" should match "patagonia"
        result = get_destination_specific_template("hiking", ["Torres del Paine, Patagonia"])
        assert result is not None
        assert "W Trek" in result or "Fitz Roy" in result

        # "Swiss Alps" should match "switzerland"
        result = get_destination_specific_template("skiing", ["Swiss Alps, Switzerland"])
        assert result is not None
        assert "Zermatt" in result or "Verbier" in result

    def test_get_destination_specific_template_returns_none_for_unknown(self):
        """get_destination_specific_template should return None for unknown destinations."""
        from app.planner.nodes.strategy.stage0 import get_destination_specific_template

        # Unknown destination should return None
        result = get_destination_specific_template("hiking", ["Unknown City"])
        assert result is None

        # Known destination but wrong topic should return None
        result = get_destination_specific_template("skiing", ["Maldives"])
        assert result is None

    def test_get_destination_specific_template_empty_destinations(self):
        """get_destination_specific_template should handle empty destinations."""
        from app.planner.nodes.strategy.stage0 import get_destination_specific_template

        assert get_destination_specific_template("hiking", []) is None
        assert get_destination_specific_template("diving", None) is None  # type: ignore

    def test_template_content_structure(self):
        """Each template entry should have required keys."""
        from app.planner.nodes.strategy.stage0 import DESTINATION_TOPIC_TEMPLATES

        required_keys = ["highlights", "best_season", "key_tips", "duration_note"]

        for (dest, topic), content in DESTINATION_TOPIC_TEMPLATES.items():
            for key in required_keys:
                assert key in content, f"Missing '{key}' in ({dest}, {topic}) template"
                assert isinstance(
                    content[key], str
                ), f"'{key}' should be string in ({dest}, {topic})"
                assert len(content[key]) > 0, f"'{key}' should not be empty in ({dest}, {topic})"

    def test_format_destination_template_includes_all_sections(self):
        """_format_destination_template should include all content sections."""
        from app.planner.nodes.strategy.stage0 import _format_destination_template

        content = {
            "highlights": "Amazing views and trails",
            "best_season": "Summer months",
            "key_tips": "Book ahead",
            "duration_note": "5-7 days ideal",
        }

        result = _format_destination_template(content, "Test Destination", "hiking")

        assert "Test Destination" in result
        assert "Amazing views and trails" in result
        assert "Summer months" in result
        assert "Book ahead" in result
        assert "5-7 days ideal" in result
        assert "🥾" in result  # Hiking emoji
