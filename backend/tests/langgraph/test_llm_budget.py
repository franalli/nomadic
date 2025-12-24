"""
Tests for LLM budget enforcement and question_target SSoT.

These tests verify:
1. LLM budget resets at turn start
2. can_call_llm() blocks when budget exhausted
3. llm_blocked_fallback() produces non-empty responses
4. set_question_target() canonicalizes values
5. question_target SSoT sync at turn boundary
"""

import pytest

from app.plan_graph import (
    GraphState,
    TripInputs,
    can_call_llm,
    canonicalize_question_target,
    get_question_target,
    llm_blocked_fallback,
    set_question_target,
)


def _make_state(**overrides) -> GraphState:
    """Create a GraphState with default values."""
    defaults = {
        "trip_inputs": TripInputs(),
        "user_text": "",
        "metadata": {},
    }
    defaults.update(overrides)
    return GraphState(**defaults)


# =============================================================================
# LLM Budget Tests
# =============================================================================


class TestCanCallLlm:
    """Tests for can_call_llm() budget enforcement."""

    @pytest.fixture
    def state(self):
        """Create a fresh state with question_target set to trigger budget enforcement."""
        return _make_state(
            metadata={"llm_calls_this_turn": 0},
            question_target="dates",  # Must be set to trigger budget enforcement
        )

    def test_first_llm_call_allowed(self, state):
        """First LLM call should be allowed."""
        assert can_call_llm(state, "test_node") is True

    def test_second_llm_call_blocked(self, state):
        """Second LLM call should be blocked (budget=1)."""
        # First call allowed
        assert can_call_llm(state, "test_node") is True
        # Second call blocked (budget exhausted, question_target set)
        assert can_call_llm(state, "test_node2") is False

    def test_blocked_count_tracked(self, state):
        """Blocked LLM calls should be tracked in metadata."""
        # Exhaust budget
        can_call_llm(state, "node1")
        # Block a call
        can_call_llm(state, "node2")

        # llm_call_blocked_count is a dict {node_name: count}
        blocked_counts = state.metadata.get("llm_call_blocked_count", {})
        assert isinstance(blocked_counts, dict)
        assert blocked_counts.get("node2", 0) >= 1


class TestLlmBlockedFallback:
    """Tests for llm_blocked_fallback() deterministic responses."""

    @pytest.fixture
    def state(self):
        """Create a fresh state for testing."""
        return _make_state(metadata={"llm_calls_this_turn": 1})  # Budget exhausted

    def test_fallback_produces_nonempty_response(self, state):
        """Fallback should always produce a non-empty last_summary."""
        llm_blocked_fallback(state, asked_target="dates", source="test")

        assert state.last_summary is not None
        assert len(state.last_summary) > 0
        assert "?" in state.last_summary  # Should have a question

    def test_fallback_sets_question_target(self, state):
        """Fallback should set question_target."""
        llm_blocked_fallback(state, asked_target="destinations", source="test")

        assert state.question_target == "destinations"

    def test_fallback_has_suggestions(self, state):
        """Fallback should provide suggested_responses."""
        llm_blocked_fallback(state, asked_target="origin", source="test")

        assert state.suggested_responses is not None
        assert len(state.suggested_responses) >= 3

    def test_fallback_date_clarify_mode_override(self, state):
        """In date_clarify_mode, fallback should ask about dates."""
        state.metadata["date_clarify_mode"] = True
        llm_blocked_fallback(state, asked_target="destinations", source="test")

        # Should override to dates
        assert state.question_target == "dates"

    def test_fallback_tracks_provenance(self, state):
        """Fallback should set parse_provenance and response_generation_provenance to template."""
        llm_blocked_fallback(state, asked_target="dates", source="test:budget")

        assert state.metadata.get("parse_provenance") == "template"
        assert state.metadata.get("response_generation_provenance") == "template"
        assert state.metadata.get("fallback_source") == "test:budget"


# =============================================================================
# question_target SSoT Tests
# =============================================================================


class TestSetQuestionTarget:
    """Tests for set_question_target() SSoT helper."""

    @pytest.fixture
    def state(self):
        """Create a fresh state for testing."""
        return _make_state(metadata={})

    def test_canonicalizes_start_date(self, state):
        """set_question_target should canonicalize start_date to dates."""
        set_question_target(state, "start_date", source="test")

        assert state.question_target == "dates"
        assert state.metadata.get("question_target") == "dates"

    def test_canonicalizes_end_date(self, state):
        """set_question_target should canonicalize end_date to dates."""
        set_question_target(state, "end_date", source="test")

        assert state.question_target == "dates"

    def test_canonicalizes_adults(self, state):
        """set_question_target should canonicalize adults to travelers."""
        set_question_target(state, "adults", source="test")

        assert state.question_target == "travelers"

    def test_preserves_valid_target(self, state):
        """set_question_target should preserve valid canonical targets."""
        set_question_target(state, "destinations", source="test")

        assert state.question_target == "destinations"

    def test_tracks_source(self, state):
        """set_question_target should track the source for debugging."""
        set_question_target(state, "origin", source="test_node:path")

        assert state.metadata.get("question_target_source") == "test_node:path"

    def test_syncs_metadata_and_state(self, state):
        """set_question_target should sync both metadata and state."""
        set_question_target(state, "budget", source="test")

        assert state.question_target == "budget"
        assert state.metadata.get("question_target") == "budget"

    def test_handles_none(self, state):
        """set_question_target should handle None gracefully."""
        set_question_target(state, None, source="test")

        assert state.question_target is None
        assert state.metadata.get("question_target") is None


class TestGetQuestionTarget:
    """Tests for get_question_target() SSoT reader."""

    @pytest.fixture
    def state(self):
        """Create a fresh state for testing."""
        return _make_state(metadata={"question_target": "dates"})

    def test_reads_from_metadata(self, state):
        """get_question_target should read from metadata SSoT."""
        state.metadata["question_target"] = "destinations"

        assert get_question_target(state) == "destinations"

    def test_returns_none_if_missing(self, state):
        """get_question_target should return None if not set."""
        state.metadata.pop("question_target", None)

        assert get_question_target(state) is None


class TestCanonicalizeQuestionTargetValues:
    """Additional canonicalization tests for stage0 fix."""

    def test_stage0_should_emit_dates_not_start_date(self):
        """Regression: stage0 fallback should use 'dates' not 'start_date'."""
        # This tests the fix applied to strategy_stage0_fallback
        state = _make_state(metadata={})

        # Simulate what the fixed stage0 fallback does
        set_question_target(state, "start_date", source="strategy_stage0_fallback")

        # Should be canonicalized to 'dates'
        assert state.question_target == "dates"
        assert state.metadata.get("question_target") == "dates"

    def test_all_date_variants_canonicalize(self):
        """All date-related variants should canonicalize to 'dates'."""
        # These are the variants defined in the canonicalize function
        variants = ["start_date", "end_date", "date", "timing", "when"]

        for variant in variants:
            result = canonicalize_question_target(variant)
            assert result == "dates", f"{variant} should map to 'dates'"
