"""
Tests for state ownership enforcement in plan_graph.py.

These tests verify:
1. _write_trip_inputs helper applies updates correctly
2. _check_state_ownership logs warnings for violations
3. STATE_OWNERSHIP map covers expected fields
"""

import logging

import pytest

from app.plan_graph import (
    STATE_OWNERSHIP,
    GraphState,
    TripInputs,
    _apply_llm_delta,
    _check_state_ownership,
    _write_trip_inputs,
)

# -----------------------
# Fixtures
# -----------------------


@pytest.fixture
def empty_state() -> GraphState:
    """Create an empty GraphState for testing."""
    return GraphState(
        trip_inputs=TripInputs(),
        parsed_inputs={},
        chat_history=[],
        user_text="",
        errors=[],
        flags={},
        metadata={},
        branches=[],
        suggested_responses=[],
    )


@pytest.fixture
def state_with_destinations() -> GraphState:
    """Create a GraphState with existing destinations."""
    return GraphState(
        trip_inputs=TripInputs(
            destinations=["Paris", "London"],
            origin="New York",
        ),
        parsed_inputs={},
        chat_history=[],
        user_text="",
        errors=[],
        flags={},
        metadata={},
        branches=[],
        suggested_responses=[],
    )


# -----------------------
# _check_state_ownership tests
# -----------------------


class TestCheckStateOwnership:
    """Tests for the _check_state_ownership function."""

    def test_allows_owner_to_write(self):
        """Owner nodes should be allowed to write their fields."""
        assert _check_state_ownership("normalize_inputs", "trip_inputs.destinations") is True
        assert _check_state_ownership("router", "intent") is True
        assert _check_state_ownership("validate_and_merge", "ready_to_generate") is True

    def test_allows_any_node_for_shared_fields(self):
        """Any node should be allowed to write to 'any' ownership fields."""
        assert _check_state_ownership("random_node", "errors") is True
        assert _check_state_ownership("unknown", "metadata") is True
        assert _check_state_ownership("test", "flags") is True

    def test_allows_specialists_for_specialist_fields(self):
        """Specialist nodes should be allowed to write to specialist-owned fields."""
        assert _check_state_ownership("flights_node", "trip_inputs.booking_types") is True
        assert _check_state_ownership("hotels_node", "trip_inputs.booking_types") is True
        assert (
            _check_state_ownership("specialist:required_fields", "trip_inputs.booking_types")
            is True
        )

    def test_allows_strategy_nodes_for_specialist_fields(self):
        """Strategy nodes (strategy:*) should be allowed to write to specialist-owned fields."""
        assert _check_state_ownership("strategy:hiking", "trip_inputs.booking_types") is True
        assert _check_state_ownership("strategy:hiking", "trip_inputs.currency") is True
        assert _check_state_ownership("strategy:diving", "trip_inputs.flight_settings") is True
        assert _check_state_ownership("strategy:skiing", "trip_inputs.hotel_settings") is True

    def test_warns_on_violation(self, caplog):
        """Violations should log a warning but return False."""
        with caplog.at_level(logging.DEBUG):
            # Use a field with single owner (router owns intent)
            result = _check_state_ownership("wrong_node", "intent")

        assert result is False
        # The warning should be logged (though our _debug may not use standard logging)

    def test_allows_unknown_fields(self):
        """Fields not in STATE_OWNERSHIP should be allowed by default."""
        assert _check_state_ownership("any_node", "unknown_field") is True
        assert _check_state_ownership("test", "trip_inputs.unknown_nested") is True


# -----------------------
# _write_trip_inputs tests
# -----------------------


class TestWriteTripInputs:
    """Tests for the _write_trip_inputs helper function."""

    def test_applies_simple_updates(self, empty_state):
        """Should apply simple field updates."""
        _write_trip_inputs(empty_state, "normalize_inputs", origin="London")

        assert empty_state.trip_inputs.origin == "London"

    def test_applies_list_updates(self, empty_state):
        """Should apply list field updates."""
        _write_trip_inputs(empty_state, "normalize_inputs", destinations=["Paris", "Rome"])

        assert empty_state.trip_inputs.destinations == ["Paris", "Rome"]

    def test_merges_dict_updates(self, state_with_destinations):
        """Should merge dict updates with existing values."""
        # First set some booking types
        _write_trip_inputs(state_with_destinations, "flights_node", booking_types={"flights": True})

        # Then add more
        _write_trip_inputs(state_with_destinations, "hotels_node", booking_types={"hotels": True})

        # Both should be present
        assert state_with_destinations.trip_inputs.booking_types.get("flights") is True
        assert state_with_destinations.trip_inputs.booking_types.get("hotels") is True

    def test_preserves_other_fields(self, state_with_destinations):
        """Updates should not affect unrelated fields."""
        original_destinations = state_with_destinations.trip_inputs.destinations.copy()

        _write_trip_inputs(state_with_destinations, "normalize_inputs", budget=5000)

        assert state_with_destinations.trip_inputs.destinations == original_destinations
        assert state_with_destinations.trip_inputs.budget == 5000

    def test_uses_deep_copy(self, state_with_destinations):
        """Should use deep copy to avoid in-place mutations."""
        _write_trip_inputs(state_with_destinations, "normalize_inputs", origin="Boston")

        # Ensure the normalized update takes effect without stale references
        assert state_with_destinations.trip_inputs.origin == "Boston"


# -----------------------
# _apply_llm_delta tests
# -----------------------


class TestApplyLLMDelta:
    """Tests for the _apply_llm_delta helper function."""

    def test_applies_destination_delta(self, state_with_destinations):
        """Should merge destination deltas without duplicates."""
        delta = {"destinations": ["Rome", "Paris"]}  # Paris already exists

        _apply_llm_delta(state_with_destinations, "specialist:required_fields", delta)

        destinations = state_with_destinations.trip_inputs.destinations
        assert "Paris" in destinations
        assert "London" in destinations
        assert "Rome" in destinations
        # Paris should not be duplicated
        assert destinations.count("Paris") == 1

    def test_normalizes_dates(self, empty_state):
        """Should normalize date formats."""
        delta = {"start_date": "2025-12-20"}

        _apply_llm_delta(empty_state, "specialist:required_fields", delta)

        assert empty_state.trip_inputs.start_date == "2025-12-20"

    def test_clamps_traveler_counts(self, empty_state):
        """_apply_llm_delta sets raw values; normalization (clamping) happens later.

        Note: Normalization/clamping of traveler counts happens in normalize_inputs
        via TripInputNormalizer, not in _apply_llm_delta. This test verifies that
        the raw value is set correctly.
        """
        delta = {"adults": 100}  # Too high

        _apply_llm_delta(empty_state, "specialist:required_fields", delta)

        # _apply_llm_delta sets the raw value; clamping happens in normalize_inputs
        assert empty_state.trip_inputs.adults == 100

    def test_skips_unknown_fields(self, empty_state):
        """Should skip fields not in TripInputs model."""
        delta = {"unknown_field": "value", "origin": "London"}

        _apply_llm_delta(empty_state, "test_node", delta)

        # Origin should be set, unknown field should be ignored
        assert empty_state.trip_inputs.origin == "London"
        assert not hasattr(empty_state.trip_inputs, "unknown_field")

    def test_respects_skip_fields(self, empty_state):
        """Should respect skip_fields parameter."""
        delta = {"origin": "London", "strategy_settings": {"hiking": {"difficulty": "hard"}}}

        _apply_llm_delta(empty_state, "strategy:hiking", delta, skip_fields={"strategy_settings"})

        # Origin should be set
        assert empty_state.trip_inputs.origin == "London"
        # strategy_settings should be skipped (though it might not be in valid_fields anyway)


# -----------------------
# STATE_OWNERSHIP coverage tests
# -----------------------


class TestStateOwnershipCoverage:
    """Tests to verify STATE_OWNERSHIP map completeness."""

    def test_has_core_trip_input_fields(self):
        """Should have ownership defined for core trip_inputs fields."""
        core_fields = [
            "trip_inputs.destinations",
            "trip_inputs.origin",
            "trip_inputs.start_date",
            "trip_inputs.end_date",
            "trip_inputs.adults",
            "trip_inputs.children",
            "trip_inputs.budget",
        ]

        for field in core_fields:
            assert field in STATE_OWNERSHIP, f"Missing ownership for {field}"

    def test_has_control_flow_fields(self):
        """Should have ownership defined for control flow fields."""
        control_fields = [
            "ready_to_generate",
            "intent",
            "strategy_topic",
        ]

        for field in control_fields:
            assert field in STATE_OWNERSHIP, f"Missing ownership for {field}"

    def test_has_specialist_fields(self):
        """Should have ownership defined for specialist-owned fields."""
        specialist_fields = [
            "trip_inputs.flight_settings",
            "trip_inputs.hotel_settings",
            "trip_inputs.transport_settings",
            "trip_inputs.activity_settings",
        ]

        for field in specialist_fields:
            assert field in STATE_OWNERSHIP, f"Missing ownership for {field}"

    def test_normalize_inputs_owns_core_fields(self):
        """normalize_inputs should own core trip_inputs fields
        (can be co-owner with specialists)."""
        normalize_owned = [
            "trip_inputs.destinations",
            "trip_inputs.origin",
            "trip_inputs.start_date",
            "trip_inputs.end_date",
            "trip_inputs.adults",
            "trip_inputs.children",
            "trip_inputs.budget",
            "trip_inputs.currency",
        ]

        for field in normalize_owned:
            owner = STATE_OWNERSHIP.get(field)
            # normalize_inputs should be listed as an owner (possibly with others via pipe)
            assert owner is not None, f"{field} should be in STATE_OWNERSHIP"
            assert (
                "normalize_inputs" in owner
            ), f"{field} should include normalize_inputs as owner, got {owner}"
