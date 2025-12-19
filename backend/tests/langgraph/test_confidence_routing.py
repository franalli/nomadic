"""Test confidence-based routing logic."""

# ruff: noqa: E402

import os
import sys
from pathlib import Path

# Suppress debug output before importing plan_graph
os.environ["PLAN_GRAPH_DEBUG"] = "0"

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from datetime import date, timedelta

from app.plan_graph import (
    CONFIDENCE_THRESHOLD_SKIP_ROUTER,
    GraphState,
    TripInputs,
    _apply_typo_corrections,
    route_after_normalize,
)

FUTURE_DATE = (date.today() + timedelta(days=30)).isoformat()


class TestRouteAfterNormalize:
    """Tests for route_after_normalize function."""

    def test_short_circuit_takes_priority(self):
        """Short-circuit flag should route to short_circuit_responder."""
        state = GraphState(
            user_text="hi",
            trip_inputs=TripInputs(),
            flags={"short_circuit": "greeting"},
            metadata={},
        )
        result = route_after_normalize(state)
        assert result == "short_circuit_responder"
        assert state.metadata.get("confidence_routing") == "short_circuit:greeting"

    def test_high_confidence_bypass_with_short_input(self):
        """High confidence + complete fields + short input should bypass router."""
        state = GraphState(
            user_text="ok",  # Short, no intent keywords
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date=FUTURE_DATE,
            ),
            metadata={
                "extraction_confidence": {
                    "overall": 0.95,
                    "level": "high",
                    "typo_suggestions": {},
                }
            },
        )
        result = route_after_normalize(state)
        assert result == "required_fields_node"
        # Confidence routing now uses "high_confidence:X.XX" format
        conf_routing = state.metadata.get("confidence_routing", "")
        assert conf_routing.startswith("high_confidence:")
        # Note: state.intent is set in normalize_inputs node, not in routing function
        # When testing routing in isolation, intent is not set on state

    def test_no_bypass_with_intent_keywords(self):
        """Input with intent keywords routes directly to appropriate node (not generic router)."""
        state = GraphState(
            user_text="what about hiking?",  # Has intent keyword
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date=FUTURE_DATE,
            ),
            metadata={
                "extraction_confidence": {
                    "overall": 0.95,
                    "level": "high",
                    "typo_suggestions": {},
                }
            },
        )
        result = route_after_normalize(state)
        # New behavior: deterministic keyword router goes directly to strategy_node
        assert result == "strategy_node"

    def test_no_bypass_with_long_input(self):
        """Long input should go to router even with high confidence."""
        state = GraphState(
            user_text="I want to make sure we have enough time for everything",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date=FUTURE_DATE,
            ),
            metadata={
                "extraction_confidence": {
                    "overall": 0.95,
                    "level": "high",
                    "typo_suggestions": {},
                }
            },
        )
        result = route_after_normalize(state)
        assert result == "router"

    def test_no_bypass_when_typos_present(self):
        """Typos present should go to router."""
        state = GraphState(
            user_text="ok",
            trip_inputs=TripInputs(
                destinations=["Pariz"],
                origin="London",
                start_date=FUTURE_DATE,
            ),
            metadata={
                "extraction_confidence": {
                    "overall": 0.7,
                    "level": "medium",
                    "typo_suggestions": {"Pariz": "Paris"},
                }
            },
        )
        result = route_after_normalize(state)
        assert result == "router"

    def test_no_bypass_when_core_fields_incomplete(self):
        """Incomplete core fields should route to required_fields_node
        (via CORE_COLLECTION gate)."""
        state = GraphState(
            user_text="ok",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                # No start_date
            ),
            metadata={
                "extraction_confidence": {
                    "overall": 0.95,
                    "level": "high",
                    "typo_suggestions": {},
                }
            },
        )
        result = route_after_normalize(state)
        # New behavior: CORE_COLLECTION gate catches missing fields
        assert result == "required_fields_node"

    def test_default_routes_to_router(self):
        """Default case with missing core fields should route to required_fields_node."""
        state = GraphState(
            user_text="I want to plan a trip",
            trip_inputs=TripInputs(),
            metadata={},
        )
        result = route_after_normalize(state)
        # New behavior: CORE_COLLECTION gate catches missing core fields
        assert result == "required_fields_node"


class TestApplyTypoCorrections:
    """Tests for _apply_typo_corrections helper."""

    def test_applies_destination_corrections(self):
        """Should correct typos in destinations."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(
                destinations=["Patogonia", "Londun"],
                origin="Paris",
            ),
        )
        corrections = {"Patogonia": "Patagonia", "Londun": "London"}
        _apply_typo_corrections(state, corrections)

        assert state.trip_inputs.destinations == ["Patagonia", "London"]
        assert state.trip_inputs.origin == "Paris"  # Unchanged

    def test_applies_origin_corrections(self):
        """Should correct typos in origin."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="Londun",
            ),
        )
        corrections = {"Londun": "London"}
        _apply_typo_corrections(state, corrections)

        assert state.trip_inputs.origin == "London"
        assert state.trip_inputs.destinations == ["Paris"]  # Unchanged

    def test_no_changes_when_no_matching_corrections(self):
        """Should not change anything if corrections don't match."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
            ),
        )
        corrections = {"Tokyo": "Tokio"}  # Doesn't match anything
        _apply_typo_corrections(state, corrections)

        assert state.trip_inputs.destinations == ["Paris"]
        assert state.trip_inputs.origin == "London"

    def test_handles_empty_inputs(self):
        """Should handle empty destinations/origin gracefully."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(),
        )
        corrections = {"Paris": "Paris, France"}
        _apply_typo_corrections(state, corrections)

        assert state.trip_inputs.destinations is None or state.trip_inputs.destinations == []
        assert state.trip_inputs.origin is None


class TestConfidenceThresholds:
    """Tests for confidence threshold constants."""

    def test_threshold_value(self):
        """CONFIDENCE_THRESHOLD_SKIP_ROUTER should be reasonable."""
        assert 0.8 <= CONFIDENCE_THRESHOLD_SKIP_ROUTER <= 1.0
        # Current value is 0.92
        assert CONFIDENCE_THRESHOLD_SKIP_ROUTER == 0.92
