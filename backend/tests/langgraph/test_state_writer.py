"""
Tests for StateWriter - P2 SSoT Enforcement.

These tests verify that StateWriter correctly wraps state mutations
and provides an audit trail for debugging.
"""

import pytest

from app.plan_graph import GraphState, TripInputs
from app.planner.state import StateWriter


@pytest.fixture
def minimal_state() -> GraphState:
    """Create a minimal GraphState for testing."""
    return GraphState(
        user_text="I want to go hiking",
        trip_inputs=TripInputs(),
        metadata={"thread_id": "test-thread", "today_iso": "2025-01-15"},
        turn_number=1,
    )


class TestStateWriterBasics:
    """Test basic StateWriter functionality."""

    def test_set_question_target(self, minimal_state: GraphState):
        """StateWriter should set question_target via SSoT function."""
        writer = StateWriter(state=minimal_state, node_name="test_node")

        writer.set_question_target("dates")
        state = writer.apply()

        assert state.question_target == "dates"
        assert state.metadata.get("question_target") == "dates"
        assert state.metadata.get("question_target_source") == "test_node"

    def test_set_question_target_canonicalizes(self, minimal_state: GraphState):
        """StateWriter should canonicalize question_target values."""
        writer = StateWriter(state=minimal_state, node_name="test_node")

        # start_date should be canonicalized to dates
        writer.set_question_target("start_date")
        state = writer.apply()

        assert state.question_target == "dates"

    def test_write_single_trip_input(self, minimal_state: GraphState):
        """StateWriter should write a single trip_input field."""
        writer = StateWriter(state=minimal_state, node_name="test_node")

        writer.write_trip_input("destinations", ["Paris", "Rome"])
        state = writer.apply()

        assert state.trip_inputs.destinations == ["Paris", "Rome"]

    def test_write_multiple_trip_inputs(self, minimal_state: GraphState):
        """StateWriter should write multiple trip_input fields."""
        writer = StateWriter(state=minimal_state, node_name="test_node")

        writer.write_trip_inputs(
            provenance="explicit",
            destinations=["Tokyo"],
            origin="London",
        )
        state = writer.apply()

        assert state.trip_inputs.destinations == ["Tokyo"]
        assert state.trip_inputs.origin == "London"

    def test_method_chaining(self, minimal_state: GraphState):
        """StateWriter methods should support chaining."""
        writer = StateWriter(state=minimal_state, node_name="test_node")

        state = (
            writer.set_question_target("destinations")
            .write_trip_input("origin", "NYC")
            .set_metadata("some_key", "some_value")
            .apply()
        )

        assert state.question_target == "destinations"
        assert state.trip_inputs.origin == "NYC"
        assert state.metadata.get("some_key") == "some_value"


class TestStateWriterAuditTrail:
    """Test StateWriter audit trail functionality."""

    def test_mutations_recorded(self, minimal_state: GraphState):
        """StateWriter should record all mutations."""
        writer = StateWriter(state=minimal_state, node_name="strategy_stage0")

        writer.set_question_target("dates")
        writer.write_trip_input("destinations", ["Paris"])
        writer.set_metadata("strategy_topic", "hiking")

        mutations = writer.get_mutations()

        assert len(mutations) == 3
        assert mutations[0].mutation_type == "question_target"
        assert mutations[0].field == "question_target"
        assert mutations[0].source == "strategy_stage0"
        assert mutations[1].mutation_type == "trip_input"
        assert mutations[1].field == "destinations"
        assert mutations[2].mutation_type == "metadata"
        assert mutations[2].field == "strategy_topic"

    def test_mutation_summary(self, minimal_state: GraphState):
        """StateWriter should provide mutation summary by type."""
        writer = StateWriter(state=minimal_state, node_name="test_node")

        writer.set_question_target("dates")
        writer.write_trip_input("destinations", ["Paris"])
        writer.write_trip_input("origin", "London")
        writer.set_metadata("key1", "value1")
        writer.set_metadata("key2", "value2")

        summary = writer.get_mutation_summary()

        assert summary == {
            "question_target": ["question_target"],
            "trip_input": ["destinations", "origin"],
            "metadata": ["key1", "key2"],
        }

    def test_empty_mutations_before_apply(self, minimal_state: GraphState):
        """StateWriter should have empty mutations list initially."""
        writer = StateWriter(state=minimal_state, node_name="test_node")

        assert writer.get_mutations() == []
        assert writer.get_mutation_summary() == {}


class TestStateWriterIntegration:
    """Integration tests for StateWriter with real state operations."""

    def test_full_node_simulation(self, minimal_state: GraphState):
        """Simulate a node using StateWriter for all mutations."""
        # Simulate strategy_stage0 behavior
        writer = StateWriter(state=minimal_state, node_name="strategy_stage0")

        # Set question target (SSoT)
        writer.set_question_target("dates")

        # Set metadata (P2: tracked mutations)
        writer.set_metadata("strategy_stage0_completed", True)
        writer.set_metadata("strategy_stage0_topic", "hiking")
        writer.set_metadata("response_writer_node", "strategy_node:stage0")

        # Apply all mutations
        state = writer.apply()

        # Verify state
        assert state.question_target == "dates"
        assert state.metadata.get("strategy_stage0_completed") is True
        assert state.metadata.get("strategy_stage0_topic") == "hiking"

        # Verify audit trail
        mutations = writer.get_mutations()
        assert len(mutations) == 4  # 1 question_target + 3 metadata
        assert all(m.source == "strategy_stage0" for m in mutations)

    def test_provenance_tracking(self, minimal_state: GraphState):
        """StateWriter should track provenance correctly."""
        writer = StateWriter(state=minimal_state, node_name="extractor")

        # Write with explicit provenance
        writer.write_trip_inputs(
            provenance="explicit",
            destinations=["Berlin"],
            start_date="2025-06-01",
        )

        state = writer.apply()

        # Verify provenance in trip_inputs (if tracked)
        assert state.trip_inputs.destinations == ["Berlin"]
        assert state.trip_inputs.start_date == "2025-06-01"
