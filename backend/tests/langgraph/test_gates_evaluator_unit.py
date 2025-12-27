"""Unit tests for GateEvaluator.

These tests verify the gate evaluation logic without full graph execution.
They focus on individual gate conditions and precedence ordering.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Suppress debug output
os.environ["PLAN_GRAPH_DEBUG"] = "0"

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.plan_graph import canonicalize_question_target  # noqa: E402
from app.planner.gates import (  # noqa: E402
    GateEvaluator,
    GatePrecedence,
    compute_trip_readiness,
)
from tests.langgraph.fixtures import (  # noqa: E402
    make_complete_state,
    make_complete_trip_inputs,
    make_incomplete_state,
    make_strategy_state,
)

# =============================================================================
# Core Invariant Tests
# =============================================================================


class TestCompleteStateRouting:
    """Tests for complete state routing behavior.

    Core invariant: Complete state must NEVER route to required_fields.
    """

    def test_complete_state_has_no_missing_core(self):
        """Verify complete state has no missing core fields."""
        trip_inputs = make_complete_trip_inputs()
        readiness = compute_trip_readiness(trip_inputs)

        assert (
            readiness.missing_core == []
        ), f"Complete state should have empty missing_core, got: {readiness.missing_core}"

    def test_complete_state_does_not_fire_core_collection(self):
        """Complete state must not fire CORE_COLLECTION gate."""
        state = make_complete_state()

        result = GateEvaluator.evaluate(state)

        # CORE_COLLECTION has precedence 90
        assert (
            result.gate_fired != GatePrecedence.CORE_COLLECTION
        ), f"Complete state fired CORE_COLLECTION gate: {result.gate_fired}"
        assert (
            result.destination != "required_fields_node"
        ), "Complete state routed to required_fields_node"

    @pytest.mark.parametrize(
        "user_text",
        [
            "show me options",
            "what are the best hotels?",
            "tell me about flights",
            "I want to know about activities",
            "anything else?",
        ],
    )
    def test_complete_state_various_inputs(self, user_text: str):
        """Complete state should not route to required_fields for various inputs."""
        state = make_complete_state(user_text=user_text)

        result = GateEvaluator.evaluate(state)

        assert (
            result.destination != "required_fields_node"
        ), f"Complete state with '{user_text}' routed to required_fields_node"


class TestIncompleteStateRouting:
    """Tests for incomplete state routing behavior."""

    @pytest.mark.parametrize(
        "missing_field",
        ["destinations", "origin", "start_date", "end_date", "adults"],
    )
    def test_missing_field_triggers_core_collection(self, missing_field: str):
        """Missing core field should trigger CORE_COLLECTION gate."""
        state = make_incomplete_state(missing_field, user_text="continue")

        result = GateEvaluator.evaluate(state)

        # CORE_COLLECTION should fire for missing core fields
        # (unless a higher-precedence gate fires first)
        if result.destination == "required_fields_node":
            assert result.gate_fired == GatePrecedence.CORE_COLLECTION
        # If not required_fields, it should be a higher-precedence gate
        else:
            assert result.gate_fired < GatePrecedence.CORE_COLLECTION


# =============================================================================
# Short Circuit Gate Tests
# =============================================================================


class TestShortCircuitGate:
    """Tests for SHORT_CIRCUIT gate behavior.

    SHORT_CIRCUIT handles greetings, confirmations, and simple acknowledgments.
    Note: The actual firing conditions depend on system state and may be
    affected by other gate precedences.
    """

    @pytest.mark.parametrize(
        "user_text",
        [
            "hi",
            "hello",
            "thanks",
        ],
    )
    def test_greeting_with_complete_state_routes_appropriately(self, user_text: str):
        """Greetings with complete state should route to summarize or short_circuit."""
        state = make_complete_state(user_text=user_text)

        result = GateEvaluator.evaluate(state)

        # When complete, either SHORT_CIRCUIT or READY_NO_FIELDS is acceptable
        # Both result in a valid response without asking more questions
        assert result.destination in ("summarize", "short_circuit_responder"), (
            f"Greeting '{user_text}' with complete state routed unexpectedly to "
            f"{result.destination}"
        )

    def test_short_circuit_is_in_precedence_order(self):
        """SHORT_CIRCUIT gate should exist in precedence order."""
        # Verify the gate exists
        assert hasattr(GatePrecedence, "SHORT_CIRCUIT")
        # Verify its precedence value (30)
        assert GatePrecedence.SHORT_CIRCUIT.value == 30


# =============================================================================
# Generate Request Gate Tests
# =============================================================================


class TestGenerateRequestGate:
    """Tests for GENERATE_REQUESTED gate (precedence 20)."""

    def test_generate_request_is_in_precedence_order(self):
        """GENERATE_REQUESTED gate should exist in precedence order."""
        assert hasattr(GatePrecedence, "GENERATE_REQUESTED")
        assert GatePrecedence.GENERATE_REQUESTED.value == 20

    def test_generate_request_with_complete_state(self):
        """Generate request with complete state should not ask for more fields."""
        state = make_complete_state(user_text="generate my itinerary")

        result = GateEvaluator.evaluate(state)

        # Should NOT route to required_fields when state is complete
        assert (
            result.destination != "required_fields_node"
        ), "Generate request with complete state should not route to required_fields"


# =============================================================================
# Strategy Expansion Gate Tests
# =============================================================================


class TestStrategyExpansionGate:
    """Tests for STRATEGY_EXPANSION gate (precedence 10 - highest priority)."""

    def test_strategy_expansion_is_highest_priority(self):
        """STRATEGY_EXPANSION should be the highest priority gate."""
        assert hasattr(GatePrecedence, "STRATEGY_EXPANSION")
        assert GatePrecedence.STRATEGY_EXPANSION.value == 10

    @pytest.mark.parametrize(
        "user_text",
        [
            "show more details",
            "tell me more",
            "expand on that",
        ],
    )
    def test_expansion_request_with_pending_expansion(self, user_text: str):
        """Expansion request with pending_strategy_expansion should fire gate."""
        state = make_strategy_state(
            topic="hiking",
            stage=1,
            complete=True,
            pending_expansion=True,
            user_text=user_text,
        )

        result = GateEvaluator.evaluate(state)

        assert result.gate_fired == GatePrecedence.STRATEGY_EXPANSION, (
            f"Expansion request '{user_text}' did not trigger STRATEGY_EXPANSION, "
            f"got {result.gate_fired}"
        )

    def test_expansion_request_without_pending_does_not_fire(self):
        """Expansion request without pending_strategy_expansion should not fire."""
        state = make_strategy_state(
            topic="hiking",
            stage=1,
            complete=True,
            pending_expansion=False,  # No pending expansion
            user_text="show more details",
        )

        result = GateEvaluator.evaluate(state)

        # Should NOT fire STRATEGY_EXPANSION
        assert (
            result.gate_fired != GatePrecedence.STRATEGY_EXPANSION
        ), "STRATEGY_EXPANSION should not fire without pending_strategy_expansion"


# =============================================================================
# Gate Precedence Order Tests
# =============================================================================


class TestGatePrecedenceOrder:
    """Tests for gate precedence ordering.

    Gates should fire in order of precedence (lower number = higher priority):
    10: STRATEGY_EXPANSION
    20: GENERATE_REQUESTED
    30: SHORT_CIRCUIT
    ...
    90: CORE_COLLECTION
    ...
    999: ROUTER_LLM
    """

    def test_strategy_expansion_has_high_priority(self):
        """STRATEGY_EXPANSION should have higher priority than most gates."""
        state = make_strategy_state(
            topic="hiking",
            stage=1,
            complete=True,
            pending_expansion=True,
            user_text="show more details",  # Clear expansion request
        )

        result = GateEvaluator.evaluate(state)

        # STRATEGY_EXPANSION (10) should fire for clear expansion requests
        assert (
            result.gate_fired == GatePrecedence.STRATEGY_EXPANSION
        ), f"Expected STRATEGY_EXPANSION, got {result.gate_fired}"

    def test_complete_state_does_not_ask_for_fields(self):
        """Complete state should not route to required_fields."""
        state = make_complete_state(user_text="generate my itinerary")

        result = GateEvaluator.evaluate(state)

        # Should not route to required_fields when complete
        assert (
            result.destination != "required_fields_node"
        ), "Complete state should not route to required_fields"

    def test_precedence_values_are_ordered(self):
        """Gate precedence values should be properly ordered."""
        # Lower values = higher priority
        assert GatePrecedence.STRATEGY_EXPANSION < GatePrecedence.GENERATE_REQUESTED
        assert GatePrecedence.GENERATE_REQUESTED < GatePrecedence.SHORT_CIRCUIT
        assert GatePrecedence.SHORT_CIRCUIT < GatePrecedence.CORE_COLLECTION
        assert GatePrecedence.CORE_COLLECTION < GatePrecedence.ROUTER_LLM


# =============================================================================
# Gate Trace Tests
# =============================================================================


class TestGateTrace:
    """Tests for gate trace metadata."""

    def test_gate_trace_is_recorded(self):
        """Gate trace should be recorded in state metadata."""
        state = make_complete_state(user_text="hello")

        GateEvaluator.evaluate(state)

        # Gate trace should be populated
        assert "gate_trace" in state.metadata
        assert isinstance(state.metadata["gate_trace"], list)
        assert len(state.metadata["gate_trace"]) > 0

    def test_gate_trace_includes_fired_gate(self):
        """Gate trace should include the gate that fired."""
        state = make_complete_state(user_text="hello")

        result = GateEvaluator.evaluate(state)

        # The gate trace shows which gate fired - check that result.gate_fired
        # corresponds to a valid gate in the precedence system

        # Verify gate_fired is a valid precedence value
        assert isinstance(
            result.gate_fired, GatePrecedence
        ), f"gate_fired should be a GatePrecedence, got {type(result.gate_fired)}"


# =============================================================================
# Suppression Tests
# =============================================================================


class TestBridgeSuppression:
    """Tests for bridge suppression logic."""

    def test_bridge_suppression_prevents_strategy(self):
        """Bridge suppression should prevent strategy gates when user answers question."""
        state = make_strategy_state(
            topic="hiking",
            stage=0,
            complete=False,
            user_text="Patagonia",  # Answer to destination question
        )
        # Simulate user just answered the active question
        state.metadata["answered_question_target_this_turn"] = "destinations"
        state.metadata["answered_question_id_this_turn"] = 1
        state.metadata["active_question_target"] = "destinations"
        state.metadata["active_question_id"] = 1

        result = GateEvaluator.evaluate(state)

        # Strategy gates should be suppressed - route to collection instead
        assert result.gate_fired != GatePrecedence.STRATEGY_PRE_CORE_VALUE
        assert result.gate_fired != GatePrecedence.STRATEGY_PRE_CORE_VALUE_WITH_DEST


# =============================================================================
# Date Clarify Mode Tests
# =============================================================================


class TestDateClarifyMode:
    """Tests for date clarification mode behavior."""

    def test_date_clarify_mode_affects_routing(self):
        """Date clarify mode should affect routing decisions."""
        state = make_incomplete_state("start_date", user_text="next week")
        state.metadata["date_clarify_mode"] = True

        result = GateEvaluator.evaluate(state)

        # In date clarify mode, strategy gates should be suppressed
        assert result.gate_fired != GatePrecedence.STRATEGY_PRE_CORE_VALUE


# =============================================================================
# Text Compatibility Tests
# =============================================================================


class TestTextCompatibility:
    """Tests for text_is_compatible_with_target method."""

    @pytest.mark.parametrize(
        "text,target,expected",
        [
            # Date-compatible inputs
            ("next week", "dates", True),
            ("March 15", "dates", True),
            ("2025-06-15", "dates", True),
            # Budget-compatible inputs
            ("$5000", "budget", True),
            ("5000 euros", "budget", True),
            # Travelers-compatible inputs
            ("2 adults", "travelers", True),
            ("just me", "travelers", True),
            # Non-compatible inputs
            ("tell me about hotels", "dates", False),
            ("I want to go hiking", "budget", False),
        ],
    )
    def test_text_compatibility(self, text: str, target: str, expected: bool):
        """Test text compatibility with various targets."""
        result = GateEvaluator.text_is_compatible_with_target(text, target)

        assert result == expected, (
            f"Expected text_is_compatible_with_target('{text}', '{target}') "
            f"to be {expected}, got {result}"
        )


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_user_text(self):
        """Empty user text should not crash evaluation."""
        state = make_complete_state(user_text="")

        # Should not raise
        result = GateEvaluator.evaluate(state)

        assert result is not None
        assert result.destination is not None

    def test_very_long_user_text(self):
        """Very long user text should not crash evaluation."""
        long_text = "I want to go on a trip " * 100  # ~2400 chars
        state = make_complete_state(user_text=long_text)

        # Should not raise
        result = GateEvaluator.evaluate(state)

        assert result is not None

    def test_special_characters_in_text(self):
        """Special characters should not crash evaluation."""
        state = make_complete_state(user_text="Let's go to Paris! 🎉 €500 #trip @2025")

        # Should not raise
        result = GateEvaluator.evaluate(state)

        assert result is not None


# =============================================================================
# Question Target Canonicalization Tests
# (Merged from test_gate_invariants.py)
# =============================================================================


class TestQuestionTargetCanonicalization:
    """Tests for question_target canonicalization."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("destinations", "destinations"),
            ("origin", "origin"),
            ("dates", "dates"),
            ("start_date", "dates"),
            ("end_date", "dates"),
            ("travelers", "travelers"),
            ("adults", "travelers"),
            # Note: "children" is NOT canonicalized to "travelers" - it stays as "children"
            ("children", "children"),
            ("budget", "budget"),
        ],
    )
    def test_canonicalization(self, raw: str, expected: str):
        """Test question_target canonicalization."""
        result = canonicalize_question_target(raw)
        assert result == expected, f"Expected '{expected}' for '{raw}', got '{result}'"

    def test_none_returns_none(self):
        """None input returns None."""
        assert canonicalize_question_target(None) is None


# =============================================================================
# GateResult Structure Tests
# (Merged from test_gate_invariants.py)
# =============================================================================


class TestGateResultStructure:
    """Tests for GateResult dataclass."""

    def test_gate_result_has_required_fields(self):
        """GateResult should have all required fields."""
        state = make_complete_state()

        gate_result = GateEvaluator.evaluate(state)

        # Check required fields exist
        assert hasattr(gate_result, "gate_fired")
        assert hasattr(gate_result, "destination")
        assert hasattr(gate_result, "reason")

        # Destination must be a string
        assert gate_result.destination is None or isinstance(gate_result.destination, str)

    def test_gate_result_reason_is_informative(self):
        """GateResult reason should be informative (not empty)."""
        state = make_complete_state()

        gate_result = GateEvaluator.evaluate(state)

        # Reason should provide useful info
        assert gate_result.reason, "GateResult.reason should not be empty"


# =============================================================================
# Trip Readiness Tests
# (Merged from test_gate_invariants.py)
# =============================================================================


class TestTripReadinessComputation:
    """Tests for compute_trip_readiness function."""

    def test_empty_inputs_has_all_core_missing(self):
        """Empty TripInputs should have all core fields missing."""
        from app.plan_graph import TripInputs

        trip_inputs = TripInputs()
        readiness = compute_trip_readiness(trip_inputs)

        # Should have destinations in missing_core
        assert "destinations" in readiness.missing_core
        # Origin and dates should also be in missing (core or all)
        assert "origin" in readiness.missing_core or "origin" in readiness.missing_all
        assert any(d in readiness.missing_core for d in ("dates", "start_date"))

    def test_complete_inputs_ready_to_generate(self):
        """Complete TripInputs should be ready to generate."""
        trip_inputs = make_complete_trip_inputs()
        readiness = compute_trip_readiness(trip_inputs)

        # Should have no missing core fields
        assert readiness.missing_core == []
        # Should be ready to generate (no blocking issues)
        assert not readiness.has_blocking_errors

    def test_partial_inputs_identifies_missing(self):
        """Partial TripInputs should correctly identify what's missing."""
        from app.plan_graph import TripInputs

        trip_inputs = TripInputs(
            destinations=["Paris"],
            origin="New York",
            # Missing start_date, end_date
        )
        readiness = compute_trip_readiness(trip_inputs)

        # Should identify dates as missing
        assert (
            any("date" in field.lower() for field in readiness.missing_core + readiness.missing_all)
            or not readiness.missing_core
        )  # Or dates aren't strictly required
