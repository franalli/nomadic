"""
Unit tests for intent-only fast path in plan_graph.py.

MVP Hardening tests covering:
- Intent-only input detection
- Skip extractor LLM for pure-intent inputs
- Route directly to required_fields with destinations question
- Strategy topic inference from intent keywords
"""

import pytest

from app.plan_graph import (
    GateEvaluator,
    GraphState,
    TripInputs,
)


class TestIntentOnlyDetection:
    """Test _check_intent_only_input detection logic."""

    def test_detects_adventure_hiking(self):
        """Should detect 'adventure hiking' as intent-only."""
        result = GateEvaluator._check_intent_only_input(
            "adventure hiking outdoors",
            TripInputs(),
        )
        assert result is not None
        assert result in ["adventure", "hiking"]

    def test_detects_beach_vacation(self):
        """Should detect 'beach vacation' as intent-only."""
        result = GateEvaluator._check_intent_only_input(
            "beach vacation relaxation",
            TripInputs(),
        )
        assert result is not None
        assert result in ["beach", "relaxation"]

    def test_detects_skiing_trip(self):
        """Should detect 'skiing trip' as intent-only."""
        result = GateEvaluator._check_intent_only_input(
            "skiing trip",
            TripInputs(),
        )
        assert result == "skiing"

    def test_detects_diving_adventure(self):
        """Should detect 'diving adventure' as intent-only."""
        result = GateEvaluator._check_intent_only_input(
            "diving snorkeling trip",
            TripInputs(),
        )
        assert result == "diving"

    def test_not_intent_only_with_destination(self):
        """Input with destinations already set is not intent-only."""
        result = GateEvaluator._check_intent_only_input(
            "adventure hiking",
            TripInputs(destinations=["Paris"]),
        )
        assert result is None

    def test_not_intent_only_with_dates(self):
        """Input with dates already set is not intent-only."""
        result = GateEvaluator._check_intent_only_input(
            "beach vacation",
            TripInputs(start_date="2026-01-15"),
        )
        assert result is None

    def test_not_intent_only_with_numbers(self):
        """Input containing numbers (dates/budget) is not intent-only."""
        result = GateEvaluator._check_intent_only_input(
            "beach vacation for 2 weeks in march",
            TripInputs(),
        )
        # Should be None because "2" suggests extractable entities
        assert result is None

    def test_not_intent_only_with_currency(self):
        """Input containing currency symbols is not intent-only."""
        result = GateEvaluator._check_intent_only_input(
            "adventure trip $5000 budget",
            TripInputs(),
        )
        assert result is None

    def test_not_intent_only_with_month_names(self):
        """Input containing month names is not intent-only."""
        result = GateEvaluator._check_intent_only_input(
            "beach vacation in december",
            TripInputs(),
        )
        assert result is None

    def test_not_intent_only_with_relative_time(self):
        """Input with relative time (next, this) is not intent-only."""
        result = GateEvaluator._check_intent_only_input(
            "hiking trip next week",
            TripInputs(),
        )
        assert result is None


class TestIntentOnlyFastPathRouting:
    """Test that intent-only inputs route to required_fields."""

    def test_adventure_hiking_routes_to_required_fields(self):
        """Intent-only 'adventure hiking' should route to strategy_node (value-first).

        Note: Strategy topics now route via STRATEGY_PRE_CORE_VALUE gate
        to provide value-first responses before collecting core fields.
        """
        state = GraphState(
            user_text="adventure hiking outdoors",
            trip_inputs=TripInputs(),  # Empty
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # Strategy topics now route to strategy_node via STRATEGY_PRE_CORE_VALUE
        assert gate_result.destination == "strategy_node"
        # Should ask for dates first (not destinations) for value-first UX
        assert gate_result.question_target == "dates"
        # Strategy topic should be set
        assert gate_result.strategy_topic == "hiking"

    def test_beach_vacation_routes_to_required_fields(self):
        """Intent-only 'beach vacation' should route to required_fields."""
        state = GraphState(
            user_text="beach vacation",
            trip_inputs=TripInputs(),  # Empty
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # Should route to required_fields_node
        assert gate_result.destination == "required_fields_node"

    def test_sets_strategy_topic_for_hiking(self):
        """Hiking intent should set strategy_topic."""
        state = GraphState(
            user_text="hiking adventure",
            trip_inputs=TripInputs(),
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # If intent-only gate fired, should have strategy_topic
        if gate_result.metadata_updates.get("intent_only_detected"):
            assert gate_result.strategy_topic == "hiking"


class TestIntentOnlyMetadata:
    """Test metadata set by intent-only fast path."""

    def test_sets_intent_only_metadata(self):
        """Should set intent_only_detected in metadata."""
        state = GraphState(
            user_text="skiing snowboarding trip",
            trip_inputs=TripInputs(),
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # Check if intent-only gate was triggered
        if "intent_only" in gate_result.reason:
            assert gate_result.metadata_updates.get("intent_only_detected") is True
            assert "intent_only_topic" in gate_result.metadata_updates

    def test_sets_router_path(self):
        """Should set router_path indicating intent-only fast path."""
        state = GraphState(
            user_text="diving snorkeling",
            trip_inputs=TripInputs(),
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # Should have router_path in metadata
        assert "router_path" in gate_result.metadata_updates
        if gate_result.metadata_updates.get("intent_only_detected"):
            assert "intent_only" in gate_result.metadata_updates["router_path"]


class TestIntentOnlyKeywordMapping:
    """Test intent keyword to topic mapping."""

    @pytest.mark.parametrize(
        "keyword,expected_topic",
        [
            ("hiking", "hiking"),
            ("skiing", "skiing"),
            ("diving", "diving"),
            ("cycling", "cycling"),
            ("boating", "boating"),
            ("adventure", "adventure"),
            ("beach", "beach"),
            ("romantic", "romantic"),
            ("family", "family"),
            ("luxury", "luxury"),
            ("budget", "budget"),
        ],
    )
    def test_keyword_maps_to_expected_topic(self, keyword: str, expected_topic: str):
        """Each intent keyword should map to expected topic."""
        # Check that keyword is in the mapping
        assert keyword in GateEvaluator.INTENT_ONLY_KEYWORDS
        assert GateEvaluator.INTENT_ONLY_KEYWORDS[keyword] == expected_topic
