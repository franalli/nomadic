# backend/tests/langgraph/test_invariant_failures.py
"""
Tests for invariant hard-fails in test mode.

PR4: Converts logged anomalies into test failures when PYTEST_RUNNING=1.
These tests verify that invariant violations raise AssertionError in test mode.
"""

import os

import pytest

from app.planner.test_mode import is_test_mode, raise_if_test_mode


class TestTestModeDetection:
    """Test that PYTEST_RUNNING env var is correctly detected."""

    def test_pytest_running_is_set(self):
        """PYTEST_RUNNING should be set by conftest.py."""
        assert os.environ.get("PYTEST_RUNNING") == "1"

    def test_is_test_mode_returns_true(self):
        """is_test_mode() should return True during tests."""
        assert is_test_mode() is True


class TestRaiseIfTestMode:
    """Test raise_if_test_mode helper."""

    def test_raises_in_test_mode(self):
        """raise_if_test_mode should raise AssertionError in tests."""
        with pytest.raises(AssertionError, match="test error message"):
            raise_if_test_mode("test error message")


class TestDoubleWriterInvariant:
    """Test that double-writer attempts raise in test mode."""

    def test_double_claim_raises_assertion_error(self):
        """Second node claiming response_writer should raise AssertionError."""
        from app.plan_graph import GraphState, TripInputs, claim_response_writer
        from app.planner.meta_keys import RESPONSE_CLAIMED_BY

        # Create a minimal state
        state = GraphState(
            user_text="test",
            thread_id="test-thread",
            trip_inputs=TripInputs(),
            metadata={RESPONSE_CLAIMED_BY: "first_node"},
        )

        # Second node trying to claim should raise
        with pytest.raises(AssertionError, match="DOUBLE_WRITER"):
            claim_response_writer(state, "second_node")

    def test_same_node_reclaim_allowed(self):
        """Same node re-claiming should be allowed (e.g., during polish)."""
        from app.plan_graph import GraphState, TripInputs, claim_response_writer
        from app.planner.meta_keys import RESPONSE_CLAIMED_BY

        state = GraphState(
            user_text="test",
            thread_id="test-thread",
            trip_inputs=TripInputs(),
            metadata={RESPONSE_CLAIMED_BY: "same_node"},
        )

        # Same node should be allowed to re-claim
        result = claim_response_writer(state, "same_node")
        assert result is True

    def test_first_claim_succeeds(self):
        """First claim should succeed and set response_claimed_by."""
        from app.plan_graph import GraphState, TripInputs, claim_response_writer
        from app.planner.meta_keys import NODE_RUN_JOURNAL, RESPONSE_CLAIMED_BY

        state = GraphState(
            user_text="test",
            thread_id="test-thread",
            trip_inputs=TripInputs(),
            metadata={
                RESPONSE_CLAIMED_BY: None,
                NODE_RUN_JOURNAL: [{"node_name": "first_node", "produced_response": False}],
            },
        )

        result = claim_response_writer(state, "first_node")

        assert result is True
        assert state.metadata[RESPONSE_CLAIMED_BY] == "first_node"


class TestTripwireInvariants:
    """Test that tripwire violations raise in test mode."""

    def test_repeat_node_raises_assertion_error(self):
        """Node executed twice (non-allowlisted) should raise AssertionError."""
        from app.plan_graph import (
            GraphState,
            TripInputs,
            init_turn_instrumentation,
            record_node_run,
        )
        from app.planner.meta_keys import VISITED_NODES

        metadata = {}
        init_turn_instrumentation(metadata)
        # Pre-add a node to visited set
        metadata[VISITED_NODES].add("test_node")

        state = GraphState(
            user_text="test",
            thread_id="test-thread",
            trip_inputs=TripInputs(),
            metadata=metadata,
        )

        # Second execution of same node should raise
        with pytest.raises(AssertionError, match="TRIPWIRE.*test_node.*twice"):
            record_node_run(state, "test_node")

    def test_allowlisted_node_can_repeat(self):
        """Allowlisted nodes should be able to execute multiple times."""
        from app.plan_graph import (
            MULTI_EXEC_ALLOWLIST,
            GraphState,
            TripInputs,
            init_turn_instrumentation,
            record_node_run,
        )
        from app.planner.meta_keys import VISITED_NODES

        # Skip if no allowlisted nodes
        if not MULTI_EXEC_ALLOWLIST:
            pytest.skip("No nodes in MULTI_EXEC_ALLOWLIST")

        allowlisted_node = next(iter(MULTI_EXEC_ALLOWLIST))

        metadata = {}
        init_turn_instrumentation(metadata)
        # Pre-add to visited
        metadata[VISITED_NODES].add(allowlisted_node)

        state = GraphState(
            user_text="test",
            thread_id="test-thread",
            trip_inputs=TripInputs(),
            metadata=metadata,
        )

        # Allowlisted node should NOT raise
        event_guid = record_node_run(state, allowlisted_node)
        assert event_guid is not None


class TestGateInvariants:
    """Test gate-related invariants."""

    def test_ready_to_generate_implies_no_required_fields_routing(self):
        """When ready_to_generate=True, routing should not go to required_fields."""
        from app.plan_graph import (
            GateEvaluator,
            GatePrecedence,
            GraphState,
            TripInputs,
        )

        # Create a state that is ready_to_generate (future dates to avoid past-date issues)
        trip_inputs = TripInputs(
            destinations=["Paris"],
            start_date="2026-06-01",
            end_date="2026-06-10",
            travelers=2,
        )

        state = GraphState(
            user_text="show me hotels",
            thread_id="test-thread",
            trip_inputs=trip_inputs,
            metadata={},
        )

        # Evaluate gate
        result = GateEvaluator.evaluate(state=state)

        # If ready_to_generate, should not route to required_fields via CORE_COLLECTION gate
        if result.gate_fired == GatePrecedence.CORE_COLLECTION:
            # This would be an invariant violation
            pytest.fail(f"ready_to_generate=True but routed to CORE_COLLECTION gate: {result}")
