"""
Tests for Extractor FULL Mode Two-Factor Trigger.

Phase 2 Token Optimization: Tests that FULL mode requires 2+ independent
signals to trigger, preventing misfires from single-factor conditions.
"""

import pytest

from app.plan_graph import (
    GraphState,
    TripInputs,
    _extractor_stats,
    _is_dense_input,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture(autouse=True)
def reset_extractor_stats():
    """Reset extractor stats before each test."""
    for key in _extractor_stats:
        _extractor_stats[key] = 0
    yield


def make_state(**kwargs) -> GraphState:
    """Create a GraphState with optional trip_inputs overrides."""
    trip_inputs_kwargs = kwargs.pop("trip_inputs", {})
    ti = TripInputs(**trip_inputs_kwargs)
    return GraphState(user_text="", trip_inputs=ti, **kwargs)


# =============================================================================
# SIMPLE INPUT TESTS (Should use LIGHT mode)
# =============================================================================


class TestSimpleInputUsesLight:
    """Simple inputs with 0-1 factors should use LIGHT mode."""

    def test_short_simple_input(self):
        """Short simple input should use LIGHT mode."""
        state = make_state()
        is_dense, reason = _is_dense_input("I want to go to Paris", state)
        assert is_dense is False
        assert "simple_input" in reason or "single_factor_rejected" in reason
        assert _extractor_stats["light_mode"] >= 1

    def test_single_keyword_not_enough(self):
        """Single settings keyword alone should NOT trigger FULL."""
        state = make_state()
        # Only one keyword, no other factors
        is_dense, reason = _is_dense_input("I want a direct flight", state)
        assert is_dense is False
        assert "single_factor_rejected" in reason
        assert _extractor_stats["full_rejected_single_factor"] >= 1

    def test_topic_keyword_never_triggers_full(self):
        """Topic keywords (hiking, diving) should NEVER trigger FULL."""
        state = make_state()
        is_dense, reason = _is_dense_input("I want a hiking adventure trip", state)
        assert is_dense is False
        # Topic keywords are routing signals, not extraction triggers

    def test_long_input_alone_not_enough(self):
        """Long input alone (>280 chars) should NOT trigger FULL."""
        state = make_state()
        # Long text but no other signals
        long_text = "I would like to plan a really nice vacation " * 10  # ~450 chars
        is_dense, reason = _is_dense_input(long_text, state)
        assert is_dense is False
        assert "single_factor_rejected" in reason

    def test_multi_sentence_alone_not_enough(self):
        """3+ sentences alone should NOT trigger FULL."""
        state = make_state()
        # 4 sentences but short and no other signals
        text = "I want a trip. It should be fun. Maybe somewhere warm. Any ideas?"
        is_dense, reason = _is_dense_input(text, state)
        assert is_dense is False
        assert "single_factor_rejected" in reason


# =============================================================================
# TWO-FACTOR TESTS (Should use FULL mode)
# =============================================================================


class TestTwoFactorTriggersFull:
    """Two or more factors should trigger FULL mode."""

    def test_keywords_plus_long_input(self):
        """Settings keywords + long input should trigger FULL."""
        state = make_state()
        # Long text with settings keyword
        long_text = "I want a direct nonstop flight to somewhere nice " * 8  # >280 chars
        is_dense, reason = _is_dense_input(long_text, state)
        assert is_dense is True
        assert "multifactor" in reason
        assert _extractor_stats["full_by_multifactor"] >= 1

    def test_keywords_plus_comma_list(self):
        """Settings keywords + comma list should trigger FULL."""
        state = make_state()
        text = "I want to visit Paris, Rome, and Barcelona with a direct flight"
        is_dense, reason = _is_dense_input(text, state)
        assert is_dense is True
        assert "multifactor" in reason

    def test_comma_list_plus_multi_sentence(self):
        """Comma list + multi-sentence should trigger FULL."""
        state = make_state()
        text = (
            "I want to go to Paris, Rome, Barcelona. It should be nice. "
            "We need hotels. What do you think?"
        )
        is_dense, reason = _is_dense_input(text, state)
        assert is_dense is True
        assert "multifactor" in reason

    def test_multiple_keywords_plus_near_ready(self):
        """Multiple keywords + near-ready state should trigger FULL."""
        state = make_state(trip_inputs={"destinations": ["Paris"], "origin": "London"})
        text = "I want a direct business class flight"
        is_dense, reason = _is_dense_input(text, state)
        assert is_dense is True
        assert "multifactor" in reason


# =============================================================================
# EXCEPTION TESTS (Single factor but strong signal)
# =============================================================================


class TestSingleFactorExceptions:
    """Certain single factors are strong enough to trigger FULL alone."""

    def test_near_ready_triggers_full_alone(self):
        """Near-ready state (2+ core fields) should trigger FULL alone."""
        state = make_state(
            trip_inputs={
                "destinations": ["Paris"],
                "origin": "London",
            }
        )
        # Simple text with no other signals
        is_dense, reason = _is_dense_input("ok sounds good", state)
        assert is_dense is True
        assert "near_ready" in reason
        assert _extractor_stats["full_by_near_ready"] >= 1

    def test_three_plus_keywords_triggers_full(self):
        """3+ settings keywords should trigger FULL alone."""
        state = make_state()
        # Many keywords in one message
        text = "I want a direct business class flight with a 4-star hotel with pool"
        is_dense, reason = _is_dense_input(text, state)
        assert is_dense is True
        # Should be triggered by keywords (3+ matches)
        assert "settings_keywords" in reason or "multifactor" in reason


# =============================================================================
# STATS TRACKING TESTS
# =============================================================================


class TestStatsTracking:
    """Test that trigger_reason stats are properly tracked."""

    def test_tracks_multifactor_stat(self):
        """Multifactor triggers should increment full_by_multifactor."""
        state = make_state()
        long_text = "I want a direct nonstop flight to somewhere nice " * 8
        _is_dense_input(long_text, state)
        assert _extractor_stats["full_by_multifactor"] >= 1

    def test_tracks_near_ready_stat(self):
        """Near-ready triggers should increment full_by_near_ready."""
        state = make_state(trip_inputs={"destinations": ["Paris"], "origin": "London"})
        _is_dense_input("ok", state)
        assert _extractor_stats["full_by_near_ready"] >= 1

    def test_tracks_rejected_single_factor(self):
        """Rejected single factors should increment full_rejected_single_factor."""
        state = make_state()
        _is_dense_input("I want a direct flight", state)
        assert _extractor_stats["full_rejected_single_factor"] >= 1

    def test_tracks_light_mode(self):
        """Simple inputs should increment light_mode."""
        state = make_state()
        _is_dense_input("I want to go to Paris", state)
        assert _extractor_stats["light_mode"] >= 1


# =============================================================================
# CORE-COLLECTION PRECONDITION TESTS
# =============================================================================


class TestCoreCollectionPrecondition:
    """Test that core-missing state biases toward LIGHT."""

    def test_core_missing_biases_light(self):
        """When core fields are missing, single factors should use LIGHT."""
        # Empty state - no core fields
        state = make_state()
        # Single long input (would have triggered FULL before)
        long_text = "I want to go somewhere nice for a vacation " * 8
        is_dense, reason = _is_dense_input(long_text, state)
        assert is_dense is False  # Single factor rejected

    def test_core_complete_allows_full(self):
        """When 2+ core fields complete, near_ready triggers FULL."""
        state = make_state(
            trip_inputs={
                "destinations": ["Paris"],
                "origin": "London",
                "start_date": "2026-06-01",
            }
        )
        # Even simple text triggers FULL due to near_ready
        is_dense, reason = _is_dense_input("ok", state)
        assert is_dense is True
        assert "near_ready" in reason


# =============================================================================
# SIGNAL DETECTION TESTS
# =============================================================================


class TestSignalDetection:
    """Test that individual signals are correctly detected."""

    def test_detects_settings_keywords(self):
        """Settings keywords should be detected."""
        state = make_state(trip_inputs={"destinations": ["Paris"], "origin": "London"})
        is_dense, reason = _is_dense_input("I want a direct nonstop flight", state)
        # near_ready + settings_keywords = multifactor
        assert is_dense is True

    def test_detects_comma_list(self):
        """Comma-separated lists should be detected."""
        state = make_state(trip_inputs={"destinations": ["Paris"], "origin": "London"})
        is_dense, reason = _is_dense_input("I want to visit Rome, Barcelona, and Madrid", state)
        # near_ready + structured_list = multifactor
        assert is_dense is True

    def test_detects_multi_destination(self):
        """Multi-destination phrases should be detected."""
        state = make_state(trip_inputs={"destinations": ["Paris"], "origin": "London"})
        is_dense, reason = _is_dense_input(
            "I want to go to Rome and then Barcelona and also Madrid", state
        )
        # near_ready + structured_list = multifactor
        assert is_dense is True

    def test_does_not_detect_topic_as_settings(self):
        """Topic keywords should NOT be counted as settings keywords."""
        state = make_state()
        # Only topic keywords, no settings keywords
        is_dense, reason = _is_dense_input("I want a hiking adventure with diving", state)
        # Should be light - topic keywords don't trigger FULL
        assert is_dense is False
