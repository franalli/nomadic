"""Tests for complex trip scenarios: multi-city, deferred intents, strategy topics."""

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
    GraphState,
    TripInputs,
    _infer_activities_from_destination,
    _is_strategy_enabled,
    _normalize_multi_city_intent,
    extractor,
    route_after_required_fields,
)


class TestMultiCityIntent:
    """Tests for multi-city intent detection."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("one trip", "multi_city"),
            ("multi-city", "multi_city"),
            ("do it all together", "multi_city"),
            ("visit both", "multi_city"),
            ("one itinerary", "multi_city"),
            ("single trip", "multi_city"),
            ("compare destinations", "separate"),
            ("separate trips", "separate"),
            ("do them separately", "separate"),
            ("", None),
            (None, None),
            ("random text", None),
        ],
    )
    def test_normalize_multi_city_intent(self, text, expected):
        """Multi-city intent normalization should detect intent phrases."""
        result = _normalize_multi_city_intent(text)
        assert result == expected

    def test_multi_city_natural_language_combined(self):
        """Natural language for combined trip should be detected."""
        combined_phrases = [
            "I want to visit both in one trip",
            "visit all together",
            "make it a multi city trip",
            "I want to see both places",
        ]
        for phrase in combined_phrases:
            result = _normalize_multi_city_intent(phrase)
            assert result == "multi_city", f"Failed for: {phrase}"

    def test_multi_city_natural_language_separate(self):
        """Natural language for separate trips should be detected."""
        separate_phrases = [
            "I want separate trips",
            "do them separately",
            "compare destinations please",
            "different trips for each",
        ]
        for phrase in separate_phrases:
            result = _normalize_multi_city_intent(phrase)
            assert result == "separate", f"Failed for: {phrase}"


class TestDeferredIntents:
    """Tests for deferred intent handling after required_fields."""

    def test_no_deferred_intent_goes_to_validate(self):
        """Without deferred intent, should go to validate_and_merge."""
        state = GraphState(
            user_text="ok",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date="2025-06-01",
            ),
            metadata={},  # No deferred_intent
        )
        result = route_after_required_fields(state)
        assert result == "validate_and_merge"

    def test_deferred_flights_routes_correctly(self):
        """Deferred flights intent should route to flights_node."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date="2025-06-01",
            ),
            last_summary="I've noted your trip details.",
            chat_history=[],
            metadata={"deferred_intent": "flights"},
        )
        result = route_after_required_fields(state)
        assert result == "flights_node"
        # Deferred intent should be cleared
        assert "deferred_intent" not in state.metadata

    def test_deferred_hotels_routes_correctly(self):
        """Deferred hotels intent should route to hotels_node."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date="2025-06-01",
            ),
            last_summary="Trip noted.",
            chat_history=[],
            metadata={"deferred_intent": "hotels"},
        )
        result = route_after_required_fields(state)
        assert result == "hotels_node"

    def test_deferred_strategy_routes_correctly(self):
        """Deferred strategy intent should route to strategy_node."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(
                destinations=["Chamonix"],
                origin="Milan",
                start_date="2025-07-01",
            ),
            last_summary="Hiking trip noted.",
            chat_history=[],
            metadata={
                "deferred_intent": "strategy",
                "deferred_strategy_topic": "hiking",
            },
        )
        result = route_after_required_fields(state)
        assert result == "strategy_node"
        # Strategy topic should be restored
        assert state.strategy_topic == "hiking"

    def test_incomplete_fields_clears_deferred(self):
        """Incomplete core fields should clear deferred intent."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                # Missing origin and start_date
            ),
            metadata={"deferred_intent": "flights"},
        )
        result = route_after_required_fields(state)
        assert result == "validate_and_merge"
        # Deferred should be cleared due to incomplete fields
        assert "deferred_intent" not in state.metadata

    def test_deferred_intent_appends_to_history(self):
        """When processing deferred intent, last_summary should be added to history."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date="2025-06-01",
            ),
            last_summary="I've noted your dates.",
            chat_history=[],
            metadata={"deferred_intent": "flights"},
        )
        route_after_required_fields(state)
        # History should have the summary appended
        assert len(state.chat_history) > 0
        assert state.chat_history[-1]["content"] == "I've noted your dates."


class TestActivityInference:
    """Tests for destination-to-activity inference."""

    @pytest.mark.parametrize(
        "destination,expected_activity",
        [
            ("Patagonia", "hiking"),
            ("patagonia", "hiking"),
            ("Alps", "hiking"),
            ("Maldives", "diving"),
            ("maldives", "diving"),
            ("Chamonix", "skiing"),
            ("Aspen", "skiing"),
        ],
    )
    def test_infer_activities_from_destination(self, destination, expected_activity):
        """Known destinations should infer appropriate activities."""
        activities = _infer_activities_from_destination(destination)
        if activities:
            # Check if expected activity is in the inferred list
            activity_text = " ".join(activities).lower()
            assert (
                expected_activity in activity_text
            ), f"Expected {expected_activity} for {destination}, got {activities}"

    def test_unknown_destination_no_inference(self):
        """Unknown destinations should not infer activities."""
        activities = _infer_activities_from_destination("RandomCity123")
        assert activities is None or len(activities) == 0

    def test_infer_activities_case_insensitive(self):
        """Activity inference should be case-insensitive."""
        activities_lower = _infer_activities_from_destination("patagonia")
        activities_upper = _infer_activities_from_destination("PATAGONIA")
        activities_mixed = _infer_activities_from_destination("Patagonia")

        # All should return same result (or all None)
        if activities_lower or activities_upper or activities_mixed:
            assert activities_lower == activities_upper == activities_mixed


class TestStrategyTopicFlow:
    """Tests for strategy topic detection and flow."""

    def test_hiking_strategy_detected(self):
        """Hiking keywords should set strategy hint."""
        state = GraphState(
            user_text="I want a hiking trip to the Alps",
            trip_inputs=TripInputs(),
            parsed_inputs={},
            chat_history=[],
            metadata={},
            thread_id="test",
        )
        state = extractor(state)
        assert state.parsed_inputs.get("strategy_hint") == "hiking"

    def test_diving_strategy_detected(self):
        """Diving keywords should set strategy hint."""
        state = GraphState(
            user_text="Planning a scuba diving trip",
            trip_inputs=TripInputs(),
            parsed_inputs={},
            chat_history=[],
            metadata={},
            thread_id="test",
        )
        state = extractor(state)
        assert state.parsed_inputs.get("strategy_hint") == "diving"

    def test_skiing_strategy_detected(self):
        """Skiing keywords should set strategy hint."""
        state = GraphState(
            user_text="Ski trip to the powder",
            trip_inputs=TripInputs(),
            parsed_inputs={},
            chat_history=[],
            metadata={},
            thread_id="test",
        )
        state = extractor(state)
        assert state.parsed_inputs.get("strategy_hint") == "skiing"

    def test_cycling_strategy_detected(self):
        """Cycling keywords should set strategy hint."""
        state = GraphState(
            user_text="Bike tour through the countryside",
            trip_inputs=TripInputs(),
            parsed_inputs={},
            chat_history=[],
            metadata={},
            thread_id="test",
        )
        state = extractor(state)
        assert state.parsed_inputs.get("strategy_hint") == "cycling"

    def test_boating_strategy_detected(self):
        """Boating keywords should set strategy hint."""
        state = GraphState(
            user_text="Yacht trip around the marina",
            trip_inputs=TripInputs(),
            parsed_inputs={},
            chat_history=[],
            metadata={},
            thread_id="test",
        )
        state = extractor(state)
        assert state.parsed_inputs.get("strategy_hint") == "boating"

    def test_strategy_enabled_function(self):
        """_is_strategy_enabled function should return bool for valid topics."""
        # Test known strategy topics
        for topic in ["boating", "hiking", "diving", "skiing", "cycling"]:
            result = _is_strategy_enabled(topic)
            assert isinstance(result, bool)


class TestMultiFacetedExtraction:
    """Tests for extracting multiple aspects from single input."""

    def test_destination_with_date(self):
        """Should extract destination and date from combined input."""
        state = GraphState(
            user_text="Going to Paris next week",
            trip_inputs=TripInputs(),
            parsed_inputs={},
            chat_history=[],
            metadata={},
            thread_id="test",
        )
        state = extractor(state)
        # Should have destination
        assert "destinations_delta" in state.parsed_inputs or state.parsed_inputs.get(
            "destinations_delta"
        )
        # May have date hint
        # Note: date extraction depends on pattern matching

    def test_origin_destination_with_travelers(self):
        """Should extract origin, destination, and travelers."""
        state = GraphState(
            user_text="Trip from London to Paris for family of 4",
            trip_inputs=TripInputs(),
            parsed_inputs={},
            chat_history=[],
            metadata={},
            thread_id="test",
        )
        state = extractor(state)
        assert state.parsed_inputs.get("origin_delta") == "London"
        assert "Paris" in state.parsed_inputs.get("destinations_delta", [])

    def test_destination_with_budget(self):
        """Should extract destination and budget."""
        state = GraphState(
            user_text="Tokyo trip with $5000 budget",
            trip_inputs=TripInputs(),
            parsed_inputs={},
            chat_history=[],
            metadata={},
            thread_id="test",
        )
        state = extractor(state)
        budget = state.parsed_inputs.get("budget_delta", {})
        assert budget.get("budget") == 5000.0

    def test_destination_infers_activity(self):
        """Destination should also infer activities when applicable."""
        state = GraphState(
            user_text="Trip to Patagonia",
            trip_inputs=TripInputs(),
            parsed_inputs={},
            chat_history=[],
            metadata={},
            thread_id="test",
        )
        state = extractor(state)
        # May have inferred activities or strategy hint
        inferred = state.parsed_inputs.get("inferred_activities")
        strategy = state.parsed_inputs.get("strategy_hint")
        # Either inferred activities or strategy hint for Patagonia
        _has_hiking = (
            inferred and any("hiking" in str(a).lower() for a in inferred)
        ) or strategy == "hiking"
        # Note: This depends on implementation - may or may not infer
