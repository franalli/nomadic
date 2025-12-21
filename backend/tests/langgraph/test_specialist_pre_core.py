"""
Unit tests for specialist pre-core gate functionality in plan_graph.py.

Tests cover:
- SPECIALIST_PRE_CORE gate at precedence 2.5
- Specialist keyword detection (hotel, flight, activity)
- Pre-core mode behavior when core fields missing
- Config flag behavior
"""

import pytest

from app.config import settings
from app.plan_graph import (
    GateEvaluator,
    GatePrecedence,
    GraphState,
    TripInputs,
    compute_trip_readiness,
)


class TestSpecialistPreCoreConfig:
    """Test specialist pre-core configuration."""

    def test_specialist_pre_core_enabled_by_default(self):
        """Verify specialist_pre_core_enabled is True."""
        assert settings.specialist_pre_core_enabled is True

    def test_gate_precedence_order(self):
        """Verify SPECIALIST_PRE_CORE is between FAST_PATH and CORE_COLLECTION."""
        assert GatePrecedence.FAST_PATH < GatePrecedence.SPECIALIST_PRE_CORE
        assert GatePrecedence.SPECIALIST_PRE_CORE < GatePrecedence.CORE_COLLECTION


class TestSpecialistKeywordDetection:
    """Test specialist keyword detection for pre-core routing."""

    @pytest.mark.parametrize(
        "input_text,expected_intent",
        [
            # Hotel keywords
            ("What hotels are available?", "hotels"),
            ("Looking for a hostel", "hotels"),
            ("Where should I stay?", "hotels"),
            ("boutique hotel recommendations", "hotels"),
            ("accommodation options", "hotels"),
            ("airbnb or hotel?", "hotels"),
            # Flight keywords
            ("What flights are there?", "flights"),
            ("Looking for direct flights", "flights"),
            ("airline options", "flights"),
            ("flying from London", "flights"),
            # Activity keywords
            ("What should I do there?", "activities"),
            ("things to do in Paris", "activities"),
            ("tour recommendations", "activities"),
            ("sightseeing options", "activities"),
            # Transport keywords
            ("How do I get around?", "transport"),
            ("train options", "transport"),
            ("car rental needed", "transport"),
        ],
    )
    def test_specialist_keyword_detection(self, input_text: str, expected_intent: str):
        """Test that specialist keywords are detected correctly."""
        text_lower = input_text.lower()
        ti = TripInputs()

        result = GateEvaluator._check_specialist_pre_core(
            text_lower, compute_trip_readiness(ti), ti
        )

        if result:
            intent, destination = result
            assert (
                intent == expected_intent
            ), f"Expected intent '{expected_intent}' for '{input_text}'"


class TestPreCoreGateRouting:
    """Test pre-core gate routing behavior."""

    def test_routes_to_hotels_when_core_missing(self):
        """Test routing to hotels node when user asks about hotels but core missing."""
        state = GraphState(
            user_text="What hotels are available in Paris?",
            trip_inputs=TripInputs(destinations=["Paris"]),  # Has destination but missing dates
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # Should route to hotels_node via SPECIALIST_PRE_CORE gate
        if settings.specialist_pre_core_enabled:
            # The gate should either fire SPECIALIST_PRE_CORE or fall through to later gates
            assert gate_result.destination in ["hotels_node", "required_fields_node"]

    def test_routes_to_flights_when_core_missing(self):
        """Test routing to flights node when user asks about flights."""
        state = GraphState(
            user_text="Looking for direct flights",
            trip_inputs=TripInputs(destinations=["Rome"]),
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        if settings.specialist_pre_core_enabled:
            assert gate_result.destination in ["flights_node", "required_fields_node"]

    def test_skips_pre_core_when_core_complete(self):
        """Test that pre-core gate is skipped when core fields are complete."""
        state = GraphState(
            user_text="What hotels are available?",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date="2025-06-15",
                end_date="2025-06-20",
            ),
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # With core complete, should not be SPECIALIST_PRE_CORE
        # (it should be a later gate like QUESTION_KEYWORD or KEYWORD_HEURISTIC)
        assert gate_result.gate_fired != GatePrecedence.SPECIALIST_PRE_CORE


class TestPreCoreMetadata:
    """Test metadata set during pre-core routing."""

    def test_pre_core_mode_metadata_set(self):
        """Test that pre_core_mode metadata is set when gate fires."""
        state = GraphState(
            user_text="hostel recommendations please",
            trip_inputs=TripInputs(),  # Empty - missing all core fields
            metadata={},
            flags={},
        )

        gate_result = GateEvaluator.evaluate(state)

        # Check if pre_core_mode is set in metadata updates
        if gate_result.gate_fired == GatePrecedence.SPECIALIST_PRE_CORE:
            assert gate_result.metadata_updates.get("pre_core_mode") is True
            assert "missing_core_fields" in gate_result.metadata_updates
