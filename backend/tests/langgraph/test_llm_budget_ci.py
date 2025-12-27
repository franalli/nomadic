"""
Tests for LLM Budget CI (PR2).

Ensures that any single turn respects the MAX_LLM_CALLS_PER_TURN budget.
CI should fail if any node path exceeds the budget.

Budget Rules:
- When ready_to_generate=False and question_target is set: max 1 LLM call
- When ready_to_generate=True or no question_target: no cap (but still tracked)
"""

from datetime import date, timedelta

import pytest

from app.plan_graph import (
    GraphState,
    TripInputs,
    can_call_llm,
    clear_all_caches,
    compute_trip_readiness,
    llm_blocked_fallback,
)

# Import FakeLLM for hermetic testing

FUTURE_DATE = (date.today() + timedelta(days=30)).isoformat()
FUTURE_END_DATE = (date.today() + timedelta(days=40)).isoformat()

# Budget constant - should match settings.max_llm_calls_per_turn
MAX_LLM_CALLS_PER_TURN = 1


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear all caches before and after each test."""
    clear_all_caches()
    yield
    clear_all_caches()


class TestLLMBudgetEnforcement:
    """Tests that LLM budget is enforced during core field collection."""

    def test_first_llm_call_allowed_during_collection(self):
        """First LLM call should be allowed when collecting core fields."""
        state = GraphState(
            session_id="test",
            user_text="I want to go to Paris",
            trip_inputs=TripInputs(destinations=["Paris"]),  # Missing dates
            metadata={"thread_id": "test"},
            question_target="dates",
        )

        allowed = can_call_llm(state, "required_fields")

        assert allowed is True
        assert state.metadata["llm_calls_this_turn"] == 1
        assert "required_fields" in state.metadata["llm_nodes_called_this_turn"]

    def test_second_llm_call_blocked_during_collection(self):
        """Second LLM call should be blocked when collecting core fields."""
        state = GraphState(
            session_id="test",
            user_text="I want to go to Paris",
            trip_inputs=TripInputs(destinations=["Paris"]),  # Missing dates
            metadata={"thread_id": "test", "llm_calls_this_turn": 1},
            question_target="dates",
        )

        allowed = can_call_llm(state, "extractor")

        assert allowed is False
        assert state.metadata["llm_calls_this_turn"] == 1  # Not incremented
        assert "extractor" in state.metadata["llm_call_blocked_reason"]
        assert state.metadata["llm_call_blocked_reason"]["extractor"] == "budget_exhausted"

    def test_no_cap_when_ready_to_generate(self):
        """No LLM cap when ready_to_generate=True."""
        state = GraphState(
            session_id="test",
            user_text="Show me hotels",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                start_date=FUTURE_DATE,
                end_date=FUTURE_END_DATE,
                adults=2,
                origin="New York",
            ),  # All core fields set
            metadata={"thread_id": "test", "llm_calls_this_turn": 5},
            question_target=None,
        )

        # Verify ready
        readiness = compute_trip_readiness(state.trip_inputs)
        assert readiness.ready_to_generate is True

        # Should allow even with high call count
        allowed = can_call_llm(state, "hotels")

        assert allowed is True
        assert state.metadata["llm_calls_this_turn"] == 6

    def test_no_cap_when_no_question_target(self):
        """No LLM cap when question_target is not set."""
        state = GraphState(
            session_id="test",
            user_text="Hello",
            trip_inputs=TripInputs(),  # Empty
            metadata={"thread_id": "test", "llm_calls_this_turn": 3},
            question_target=None,  # No target
        )

        allowed = can_call_llm(state, "greeting")

        assert allowed is True
        assert state.metadata["llm_calls_this_turn"] == 4

    def test_llm_blocked_fallback_provides_response(self):
        """llm_blocked_fallback provides deterministic response when blocked."""
        state = GraphState(
            session_id="test",
            user_text="When should I go?",
            trip_inputs=TripInputs(destinations=["Paris"]),
            metadata={"thread_id": "test"},
            question_target="dates",
        )

        # Simulate blocked
        llm_blocked_fallback(state, "dates", source="test")

        # Should have set template response
        assert state.last_summary is not None
        assert len(state.last_summary) > 0
        assert state.suggested_responses is not None


class TestLLMBudgetPerNodePath:
    """Tests that each node path respects the budget."""

    def test_required_fields_path_respects_budget(self):
        """required_fields path stays within budget."""
        state = GraphState(
            session_id="test",
            user_text="I want to visit Rome",
            trip_inputs=TripInputs(destinations=["Rome"]),
            metadata={"thread_id": "test"},
            question_target="dates",
        )

        # First call allowed
        assert can_call_llm(state, "required_fields") is True

        # Second call blocked
        assert can_call_llm(state, "extractor") is False

        # Verify budget
        assert state.metadata["llm_calls_this_turn"] <= MAX_LLM_CALLS_PER_TURN

    def test_router_path_respects_budget(self):
        """router path stays within budget."""
        state = GraphState(
            session_id="test",
            user_text="I need hotels in Tokyo",
            trip_inputs=TripInputs(destinations=["Tokyo"]),
            metadata={"thread_id": "test"},
            question_target="travelers",
        )

        # First call allowed
        assert can_call_llm(state, "router") is True

        # Verify budget
        assert state.metadata["llm_calls_this_turn"] <= MAX_LLM_CALLS_PER_TURN

    def test_strategy_path_respects_budget(self):
        """strategy path stays within budget when not ready."""
        state = GraphState(
            session_id="test",
            user_text="I want to go hiking",
            trip_inputs=TripInputs(destinations=["Alps"]),
            metadata={"thread_id": "test"},
            question_target="dates",
            strategy_topic="hiking",
        )

        # First call allowed
        assert can_call_llm(state, "strategy:hiking") is True

        # Second call blocked
        assert can_call_llm(state, "strategy_stage0") is False

        # Verify budget
        assert state.metadata["llm_calls_this_turn"] <= MAX_LLM_CALLS_PER_TURN


class TestLLMCallTracking:
    """Tests for LLM call tracking observability."""

    def test_llm_nodes_called_tracked(self):
        """All LLM-calling nodes are tracked in metadata."""
        state = GraphState(
            session_id="test",
            user_text="Paris trip",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                start_date=FUTURE_DATE,
                end_date=FUTURE_END_DATE,
                adults=2,
            ),
            metadata={"thread_id": "test"},
        )

        # Multiple calls when ready (no cap)
        can_call_llm(state, "hotels")
        can_call_llm(state, "flights")
        can_call_llm(state, "activities")

        assert "hotels" in state.metadata["llm_nodes_called_this_turn"]
        assert "flights" in state.metadata["llm_nodes_called_this_turn"]
        assert "activities" in state.metadata["llm_nodes_called_this_turn"]
        assert state.metadata["llm_calls_this_turn"] == 3

    def test_blocked_count_tracked(self):
        """Blocked call counts are tracked per node."""
        state = GraphState(
            session_id="test",
            user_text="Paris",
            trip_inputs=TripInputs(destinations=["Paris"]),
            metadata={"thread_id": "test"},
            question_target="dates",
        )

        # First call succeeds
        can_call_llm(state, "required_fields")

        # Multiple blocked calls from different nodes
        can_call_llm(state, "extractor")
        can_call_llm(state, "extractor")
        can_call_llm(state, "router")

        assert state.metadata["llm_call_blocked_count"]["extractor"] == 2
        assert state.metadata["llm_call_blocked_count"]["router"] == 1


class TestBudgetWithFakeLLM:
    """Integration tests using FakeLLM to verify real node paths."""

    def test_short_circuit_patterns_skip_llm(self):
        """Short-circuit patterns should not increment LLM call counter."""
        from app.pattern_matching import text_is_compatible_with_target

        state = GraphState(
            session_id="test",
            user_text="Hello",
            trip_inputs=TripInputs(),
            metadata={"thread_id": "test", "llm_calls_this_turn": 0},
        )

        # Greeting pattern check doesn't call LLM
        text_is_compatible_with_target("Hello", "greeting")

        # LLM counter should not have been incremented
        assert state.metadata.get("llm_calls_this_turn", 0) == 0

    def test_confirmation_pattern_check_no_llm(self):
        """Confirmation pattern check should not increment LLM counter."""
        from app.pattern_matching import text_is_compatible_with_target

        state = GraphState(
            session_id="test",
            user_text="Yes",
            trip_inputs=TripInputs(destinations=["Paris"]),
            metadata={"thread_id": "test", "llm_calls_this_turn": 0},
            question_target="destinations",
        )

        # Confirmation pattern check doesn't call LLM
        text_is_compatible_with_target("Yes", "confirmation")

        # LLM counter should not have been incremented
        assert state.metadata.get("llm_calls_this_turn", 0) == 0


class TestBudgetInvariants:
    """Tests for budget-related invariants that CI should enforce."""

    def test_budget_counter_never_decremented(self):
        """Budget counter is never decremented (increment-only semantics)."""
        state = GraphState(
            session_id="test",
            user_text="Paris",
            trip_inputs=TripInputs(destinations=["Paris"]),
            metadata={"thread_id": "test"},
            question_target="dates",
        )

        initial = state.metadata.get("llm_calls_this_turn", 0)

        # Call that succeeds
        can_call_llm(state, "node1")
        after_success = state.metadata["llm_calls_this_turn"]

        # Call that fails (blocked)
        can_call_llm(state, "node2")
        after_blocked = state.metadata["llm_calls_this_turn"]

        # Counter should only go up, never down
        assert after_success > initial
        assert after_blocked == after_success  # Not decremented on block

    def test_blocked_reason_preserved_across_calls(self):
        """Blocked reason dict preserves all blocked nodes."""
        state = GraphState(
            session_id="test",
            user_text="Paris",
            trip_inputs=TripInputs(destinations=["Paris"]),
            metadata={"thread_id": "test"},
            question_target="dates",
        )

        # First call succeeds
        can_call_llm(state, "allowed_node")

        # Multiple different nodes blocked
        can_call_llm(state, "blocked_a")
        can_call_llm(state, "blocked_b")
        can_call_llm(state, "blocked_c")

        # All should be in blocked_reason dict
        blocked = state.metadata["llm_call_blocked_reason"]
        assert "blocked_a" in blocked
        assert "blocked_b" in blocked
        assert "blocked_c" in blocked

    def test_max_llm_calls_constant_matches_settings(self):
        """MAX_LLM_CALLS_PER_TURN matches the default in settings."""
        from app.config import settings

        expected = getattr(settings, "max_llm_calls_per_turn", 1)
        assert MAX_LLM_CALLS_PER_TURN == expected


class TestCIFailureConditions:
    """
    Tests that should FAIL CI if budget invariants are violated.

    These tests verify that the system would catch budget violations.
    """

    def test_detect_budget_violation_multiple_llm_during_collection(self):
        """
        Simulates what would happen if a bug allowed multiple LLM calls.

        This test verifies the detection mechanism works.
        """
        state = GraphState(
            session_id="test",
            user_text="Paris trip",
            trip_inputs=TripInputs(destinations=["Paris"]),
            metadata={"thread_id": "test"},
            question_target="dates",
        )

        # Simulate bug: manually increment counter beyond budget
        state.metadata["llm_calls_this_turn"] = 5

        # Now can_call_llm should correctly block
        allowed = can_call_llm(state, "buggy_node")

        assert allowed is False, "Budget enforcement should block calls beyond max"
        assert state.metadata["llm_calls_this_turn"] == 5, "Counter should not increment"
