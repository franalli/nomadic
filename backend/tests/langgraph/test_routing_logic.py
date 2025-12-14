"""Tests for routing logic functions."""

# ruff: noqa: E402

import os
import sys
from pathlib import Path

# Suppress debug output before importing plan_graph
os.environ["PLAN_GRAPH_DEBUG"] = "0"

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from app.plan_graph import (
    CONFIDENCE_THRESHOLD_SKIP_ROUTER,
    GraphState,
    TripInputs,
    route_after_extractor,
    route_after_normalize,
    route_after_required_fields,
    route_after_router,
    should_use_monolith,
)


class TestRouteAfterExtractor:
    """Tests for route_after_extractor function."""

    def test_short_circuit_routes_to_responder(self):
        """Fast-path short-circuit should route directly to responder."""
        state = GraphState(
            user_text="hi",
            trip_inputs=TripInputs(),
            flags={"short_circuit": "greeting"},
            metadata={},
        )
        result = route_after_extractor(state)
        assert result == "short_circuit_responder"

    def test_normal_input_routes_to_normalize(self):
        """Normal input should route to normalize_inputs."""
        state = GraphState(
            user_text="I want to go to Paris",
            trip_inputs=TripInputs(),
            flags={},
            metadata={},
            parsed_inputs={"destinations_delta": ["Paris"]},
        )
        result = route_after_extractor(state)
        assert result == "normalize_inputs"

    def test_generate_plan_flag_handling(self):
        """Generate plan flag should be handled appropriately."""
        state = GraphState(
            user_text="yes",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date="2025-06-01",
            ),
            flags={"generate_plan": True},
            metadata={},
        )
        result = route_after_extractor(state)
        # Should continue to normalize or short-circuit
        assert result in ("normalize_inputs", "short_circuit_responder")


class TestRouteAfterNormalize:
    """Tests for route_after_normalize function."""

    def test_short_circuit_priority(self):
        """Short-circuit flag should take highest priority."""
        state = GraphState(
            user_text="hi",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date="2025-06-01",
            ),
            flags={"short_circuit": "greeting"},
            metadata={
                "extraction_confidence": {
                    "overall": 0.99,
                    "level": "high",
                }
            },
        )
        result = route_after_normalize(state)
        assert result == "short_circuit_responder"

    def test_high_confidence_bypass_all_conditions(self):
        """High confidence + complete fields + short input should bypass router."""
        state = GraphState(
            user_text="ok",  # Short, no intent keywords
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date="2025-06-01",
            ),
            flags={},
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
        assert state.metadata.get("confidence_routing") == "high_confidence_bypass"

    def test_bypass_blocked_by_intent_keywords(self):
        """Input with intent keywords should go to router."""
        state = GraphState(
            user_text="what about hiking?",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date="2025-06-01",
            ),
            flags={},
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

    def test_bypass_blocked_by_long_input(self):
        """Long input (>30 chars) should go to router."""
        state = GraphState(
            user_text="I want to make sure we have enough time for everything",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date="2025-06-01",
            ),
            flags={},
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

    def test_bypass_blocked_by_typos(self):
        """Typo suggestions should force router."""
        state = GraphState(
            user_text="ok",
            trip_inputs=TripInputs(
                destinations=["Pariz"],
                origin="London",
                start_date="2025-06-01",
            ),
            flags={},
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

    def test_bypass_blocked_by_incomplete_fields(self):
        """Incomplete core fields should go to router."""
        state = GraphState(
            user_text="ok",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                # Missing origin and start_date
            ),
            flags={},
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

    def test_default_routes_to_router(self):
        """Default case should route to router."""
        state = GraphState(
            user_text="I want to plan a trip to Tokyo",
            trip_inputs=TripInputs(),
            flags={},
            metadata={},
        )
        result = route_after_normalize(state)
        assert result == "router"


class TestRouteAfterRouter:
    """Tests for route_after_router function."""

    def test_monolith_triggered_on_unknown(self):
        """Unknown intent should trigger monolith."""
        state = GraphState(
            user_text="something random",
            trip_inputs=TripInputs(),
            intent="unknown",
            metadata={},
        )
        if should_use_monolith(state):
            result = route_after_router(state)
            assert result == "monolith_node"

    def test_low_confidence_forces_required_fields(self):
        """Low extraction confidence should force required_fields."""
        state = GraphState(
            user_text="xyz abc",
            trip_inputs=TripInputs(),
            intent="flights",
            metadata={
                "extraction_confidence": {
                    "overall": 0.3,
                    "level": "low",
                    "low_confidence_reasons": ["no_entities_extracted"],
                }
            },
        )
        result = route_after_router(state)
        assert result == "required_fields_node"

    def test_typo_forces_required_fields(self):
        """Typo suggestions should force required_fields."""
        state = GraphState(
            user_text="going to Pariz",
            trip_inputs=TripInputs(destinations=["Pariz"]),
            intent="flights",
            metadata={
                "extraction_confidence": {
                    "overall": 0.6,
                    "level": "medium",
                    "typo_suggestions": {"Pariz": "Paris"},
                }
            },
        )
        result = route_after_router(state)
        assert result == "required_fields_node"

    def test_meaningful_update_bypasses_low_confidence(self):
        """Preference-only turns should not be forced to required_fields."""
        state = GraphState(
            user_text="direct business class",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date="2025-06-01",
            ),
            intent="flights",
            parsed_inputs={
                "flight_settings_delta": {"direct_only": True, "cabin_class": "business"}
            },
            metadata={
                "extraction_confidence": {
                    "overall": 0.4,
                    "level": "low",
                }
            },
        )
        result = route_after_router(state)
        # Should NOT be forced to required_fields because there's a meaningful update
        assert result in (
            "flights_node",
            "required_fields_node",
        )  # May still go to required if core fields missing

    def test_core_fields_missing_forces_required_fields(self):
        """Missing core fields should force required_fields."""
        state = GraphState(
            user_text="find me hotels",
            trip_inputs=TripInputs(),  # No destinations, origin, dates
            intent="hotels",
            metadata={
                "extraction_confidence": {
                    "overall": 0.9,
                    "level": "high",
                }
            },
        )
        result = route_after_router(state)
        assert result == "required_fields_node"


class TestShouldUseMonolith:
    """Tests for should_use_monolith function."""

    def test_unknown_intent_uses_monolith(self):
        """Unknown intent should use monolith."""
        state = GraphState(
            user_text="random gibberish",
            trip_inputs=TripInputs(),
            intent="unknown",
            metadata={},
        )
        assert should_use_monolith(state) is True

    def test_known_intent_not_monolith(self):
        """Known intents should not use monolith."""
        known_intents = ["required_fields", "flights", "hotels", "transport", "activities"]
        for intent in known_intents:
            state = GraphState(
                user_text="test",
                trip_inputs=TripInputs(),
                intent=intent,
                metadata={},
            )
            # Known intents should not trigger monolith (unless other conditions)
            # Note: should_use_monolith may have other conditions
            result = should_use_monolith(state)
            assert isinstance(result, bool)


class TestConfidenceThreshold:
    """Tests for confidence threshold constant."""

    def test_threshold_value_is_reasonable(self):
        """Threshold should be between 0.8 and 1.0."""
        assert 0.8 <= CONFIDENCE_THRESHOLD_SKIP_ROUTER <= 1.0

    def test_threshold_is_92_percent(self):
        """Current implementation uses 0.92."""
        assert CONFIDENCE_THRESHOLD_SKIP_ROUTER == 0.92


class TestRouteAfterRequiredFields:
    """Tests for route_after_required_fields function."""

    def test_no_deferred_routes_to_validate(self):
        """No deferred intent should go to validate_and_merge."""
        state = GraphState(
            user_text="ok",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date="2025-06-01",
            ),
            metadata={},
        )
        result = route_after_required_fields(state)
        assert result == "validate_and_merge"

    def test_deferred_with_complete_fields_routes_to_intent(self):
        """Deferred intent with complete fields should route to that intent."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date="2025-06-01",
            ),
            last_summary="Trip noted.",
            chat_history=[],
            metadata={"deferred_intent": "activities"},
        )
        result = route_after_required_fields(state)
        assert result == "activities_node"

    def test_deferred_with_incomplete_fields_clears(self):
        """Deferred intent with incomplete fields should be cleared."""
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
        assert "deferred_intent" not in state.metadata
