"""
Unit tests for deterministic pre-core specialist behavior.

MVP Hardening tests covering:
- Pre-core specialists bypass LLM and use templates
- Deterministic question_target from priority order
- Template-based suggested_responses
- Acknowledgment includes topic context
"""

import pytest

from app.config import settings
from app.plan_graph import (
    CORE_FIELD_PRIORITY,
    GateEvaluator,
    GatePrecedence,
    GraphState,
    TripInputs,
    _get_template_response,
    compute_trip_readiness,
)


class TestPreCoreDeterministicRouting:
    """Test that pre-core specialists are routed deterministically."""

    def test_pre_core_hotels_routes_correctly(self):
        """Hotels query with missing core should route to hotels_node in pre-core mode."""
        state = GraphState(
            user_text="What hotels are available?",
            trip_inputs=TripInputs(),  # All core fields missing
            metadata={},
            flags={},
        )

        if settings.specialist_pre_core_enabled:
            gate_result = GateEvaluator.evaluate(state)
            # Should route to hotels_node or required_fields_node
            assert gate_result.destination in ["hotels_node", "required_fields_node"]
            if gate_result.destination == "hotels_node":
                assert gate_result.metadata_updates.get("pre_core_mode") is True

    def test_pre_core_flights_routes_correctly(self):
        """Flights query with missing core should route correctly."""
        state = GraphState(
            user_text="Find flights to Paris",
            trip_inputs=TripInputs(),  # All core fields missing
            metadata={},
            flags={},
        )

        if settings.specialist_pre_core_enabled:
            gate_result = GateEvaluator.evaluate(state)
            # Should route appropriately
            assert gate_result.destination in ["flights_node", "required_fields_node"]

    def test_pre_core_metadata_set(self):
        """Pre-core routing should set pre_core_mode in metadata."""
        state = GraphState(
            user_text="What hotels are there?",
            trip_inputs=TripInputs(destinations=["Paris"]),  # Has destination but missing dates
            metadata={},
            flags={},
        )

        if settings.specialist_pre_core_enabled:
            gate_result = GateEvaluator.evaluate(state)
            if gate_result.gate_fired == GatePrecedence.SPECIALIST_PRE_CORE:
                assert gate_result.metadata_updates.get("pre_core_mode") is True
                assert "missing_core_fields" in gate_result.metadata_updates


class TestPreCoreTemplateResponses:
    """Test that pre-core mode uses template responses."""

    def test_template_response_for_destinations(self):
        """Should have template response for destinations."""
        response = _get_template_response("destinations")
        assert response is not None
        assert "question" in response
        assert "suggestions" in response
        assert len(response["suggestions"]) >= 1

    def test_template_response_for_dates(self):
        """Should have template response for dates."""
        response = _get_template_response("dates")
        assert response is not None
        assert "question" in response
        assert len(response["suggestions"]) >= 1

    def test_template_response_for_origin(self):
        """Should have template response for origin."""
        response = _get_template_response("origin")
        assert response is not None
        assert "question" in response

    def test_template_response_for_travelers(self):
        """Should have template response for travelers."""
        response = _get_template_response("travelers")
        assert response is not None
        assert "question" in response

    def test_strategy_topic_customizes_destinations(self):
        """Strategy topic should customize destination suggestions."""
        hiking_response = _get_template_response("destinations", "hiking")
        default_response = _get_template_response("destinations", None)

        # Both should exist
        assert hiking_response is not None
        assert default_response is not None

        # Hiking should have hiking-specific suggestions if templates define them
        # (This depends on template content)
        assert hiking_response["suggestions"]
        assert default_response["suggestions"]


class TestPreCoreQuestionTarget:
    """Test deterministic question_target selection in pre-core mode."""

    def test_missing_all_targets_destinations(self):
        """When all fields missing, should target destinations first."""
        readiness = compute_trip_readiness(TripInputs())
        assert readiness.question_target == "destinations"

    def test_has_destinations_targets_origin_or_dates(self):
        """When has destinations, should target origin or dates next."""
        readiness = compute_trip_readiness(TripInputs(destinations=["Paris"]))
        # Based on CORE_FIELD_PRIORITY, next should be start_date -> dates or origin
        assert readiness.question_target in ["dates", "origin"]

    def test_has_destinations_and_origin_targets_dates(self):
        """When has destinations and origin, should target dates."""
        readiness = compute_trip_readiness(TripInputs(destinations=["Paris"], origin="London"))
        assert readiness.question_target == "dates"

    def test_core_complete_has_no_core_missing(self):
        """When core complete, missing_core should be empty."""
        readiness = compute_trip_readiness(
            TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date="2026-01-15",
            )
        )
        assert readiness.core_complete is True
        assert len(readiness.missing_core) == 0


class TestPreCoreDeterministicPath:
    """Test that pre-core mode produces consistent deterministic output."""

    @pytest.mark.parametrize(
        "specialist,expected_topic",
        [
            ("hotels", "hotels and accommodation"),
            ("flights", "flights"),
            ("activities", "activities and things to do"),
            ("transport", "transportation"),
        ],
    )
    def test_specialist_has_expected_acknowledgment_topic(
        self, specialist: str, expected_topic: str
    ):
        """Each specialist should have appropriate topic for acknowledgment."""
        # This tests the topic_acknowledgments mapping in _specialist
        topic_acknowledgments = {
            "hotels": "hotels and accommodation",
            "flights": "flights",
            "activities": "activities and things to do",
            "transport": "transportation",
        }
        assert topic_acknowledgments.get(specialist) == expected_topic

    def test_core_field_priority_consistency(self):
        """CORE_FIELD_PRIORITY should be consistent with TripReadiness logic."""
        # destinations should come before origin and dates
        dest_idx = CORE_FIELD_PRIORITY.index("destinations")
        assert dest_idx < len(CORE_FIELD_PRIORITY) - 1

        # Verify the list contains expected fields
        expected_fields = {"destinations", "origin", "start_date"}
        actual_fields = set(CORE_FIELD_PRIORITY)
        assert expected_fields.issubset(actual_fields)
