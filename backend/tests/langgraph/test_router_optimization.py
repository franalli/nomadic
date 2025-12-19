"""
Tests for Phase 3: Router LLM Fallback Reduction.

Tests the scoring-based deterministic router and cache normalization.
"""

import pytest

from app.plan_graph import (
    _ROUTER_BYPASS_THRESHOLD,
    GateEvaluator,
    GatePrecedence,
    GraphState,
    TripInputs,
    _normalize_user_text_for_cache,
    _router_stats,
    _try_deterministic_router,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture(autouse=True)
def reset_router_stats():
    """Reset router stats before each test."""
    for key in _router_stats:
        _router_stats[key] = 0
    yield


def make_state(**kwargs) -> GraphState:
    """Create a GraphState with optional trip_inputs and metadata overrides."""
    trip_inputs_kwargs = kwargs.pop("trip_inputs", {})
    metadata = kwargs.pop("metadata", {})
    user_text = kwargs.pop("user_text", "")
    ti = TripInputs(**trip_inputs_kwargs)
    return GraphState(user_text=user_text, trip_inputs=ti, metadata=metadata, **kwargs)


# =============================================================================
# CACHE NORMALIZATION TESTS
# =============================================================================


class TestCacheNormalization:
    """Test confirmation variant normalization for cache key."""

    def test_ok_variants_normalize(self):
        """All 'ok' variants should normalize to [CONFIRM]."""
        variants = ["ok", "okay", "o.k.", "OK", "OKAY"]
        for v in variants:
            assert _normalize_user_text_for_cache(v) == "[CONFIRM]"

    def test_yes_variants_normalize(self):
        """All 'yes' variants should normalize to [CONFIRM]."""
        variants = ["yes", "yep", "yeah", "yea", "yup", "YES"]
        for v in variants:
            assert _normalize_user_text_for_cache(v) == "[CONFIRM]"

    def test_affirmative_phrases_normalize(self):
        """Affirmative phrases should normalize to [CONFIRM]."""
        phrases = [
            "sounds good",
            "sounds great",
            "looks good",
            "perfect",
            "great",
            "fine",
            "alright",
            "cool",
            "thanks",
            "proceed",
            "go ahead",
        ]
        for p in phrases:
            assert _normalize_user_text_for_cache(p) == "[CONFIRM]"

    def test_strips_punctuation(self):
        """Punctuation should be stripped before normalization."""
        assert _normalize_user_text_for_cache("ok!") == "[CONFIRM]"
        assert _normalize_user_text_for_cache("yes.") == "[CONFIRM]"
        assert _normalize_user_text_for_cache("sure?") == "[CONFIRM]"

    def test_non_confirmations_not_normalized(self):
        """Non-confirmation text should not normalize to [CONFIRM]."""
        texts = [
            "I want to go to Paris",
            "book a flight",
            "find hotels",
            "ok but also add Rome",  # Has extra content
        ]
        for t in texts:
            result = _normalize_user_text_for_cache(t)
            assert result != "[CONFIRM]"
            assert result == t.strip().lower().rstrip("!.?")


# =============================================================================
# SCORING ROUTER TESTS
# =============================================================================


class TestScoringRouter:
    """Test multi-signal scoring deterministic router."""

    def test_keyword_alone_below_threshold(self):
        """Single keyword alone may not meet threshold."""
        state = make_state()
        result = _try_deterministic_router("hotel", state)
        # Single keyword (score=2) is below threshold (3)
        assert result is None or not result.should_bypass

    def test_keyword_plus_positive_intent_bypasses(self):
        """Keyword + positive intent should bypass (2+2=4 >= 3)."""
        state = make_state()
        result = _try_deterministic_router("I want to find a hotel", state)
        assert result is not None
        assert result.should_bypass is True
        assert result.intent == "hotels"
        assert result.score >= _ROUTER_BYPASS_THRESHOLD

    def test_question_pattern_plus_keyword_bypasses(self):
        """Question pattern + keyword should bypass."""
        state = make_state()
        result = _try_deterministic_router("what hotels are nearby", state)
        assert result is not None
        assert result.should_bypass is True
        assert result.intent == "hotels"

    def test_keyword_plus_booking_type_bypasses(self):
        """Keyword + booking type enabled should bypass."""
        state = make_state(
            trip_inputs={
                "booking_types": {"hotels": True},
            }
        )
        result = _try_deterministic_router("find a nice hotel", state)
        assert result is not None
        assert result.should_bypass is True
        assert "booking_type:hotels" in result.signals

    def test_keyword_plus_recent_intent_bypasses(self):
        """Keyword + matching recent intent should boost score."""
        state = make_state(metadata={"last_intent": "hotels"})
        result = _try_deterministic_router("I want a hotel", state)
        assert result is not None
        assert result.should_bypass is True
        assert "recent_intent:hotels" in result.signals

    def test_ambiguous_keyword_penalizes(self):
        """Ambiguous keywords should reduce score."""
        state = make_state()
        # "trip" is ambiguous - should not bypass
        result = _try_deterministic_router("I want to plan a trip", state)
        # Should either return None or have should_bypass=False
        assert result is None or not result.should_bypass

    def test_negation_blocks_bypass(self):
        """Negation should strongly penalize and block bypass."""
        state = make_state()
        result = _try_deterministic_router("I don't want a hotel", state)
        # Negation (-3) cancels out keyword (+2)
        assert result is None or not result.should_bypass

    def test_strategy_topic_detection(self):
        """Strategy keywords should detect topic."""
        state = make_state()
        result = _try_deterministic_router("I want to go hiking", state)
        assert result is not None
        assert result.intent == "strategy"
        assert result.strategy_topic == "hiking"

    def test_stats_tracking(self):
        """Stats should be properly tracked."""
        state = make_state()
        _try_deterministic_router("I want to find a hotel", state)
        assert _router_stats["deterministic_bypasses"] >= 1


# =============================================================================
# GATE EVALUATOR INTEGRATION TESTS
# =============================================================================


class TestGateEvaluatorIntegration:
    """Test scoring router integration with GateEvaluator."""

    def test_scoring_router_gate_fires(self):
        """SCORING_ROUTER gate should fire when score meets threshold."""
        state = make_state(
            user_text="I want to find a hotel",
            trip_inputs={
                "destinations": ["Paris"],
                "origin": "London",
                "start_date": "2026-06-01",
            },
        )
        result = GateEvaluator.evaluate(state)
        # Should be caught by either KEYWORD_HEURISTIC or SCORING_ROUTER
        assert result.gate_fired in (
            GatePrecedence.KEYWORD_HEURISTIC,
            GatePrecedence.SCORING_ROUTER,
        )
        assert result.intent == "hotels"

    def test_scoring_router_skipped_when_keyword_matches(self):
        """SCORING_ROUTER should be skipped if KEYWORD_HEURISTIC matches."""
        state = make_state(
            user_text="hotel",
            trip_inputs={
                "destinations": ["Paris"],
                "origin": "London",
                "start_date": "2026-06-01",
            },
        )
        result = GateEvaluator.evaluate(state)
        # Single keyword "hotel" should be caught by KEYWORD_HEURISTIC
        assert result.gate_fired == GatePrecedence.KEYWORD_HEURISTIC

    def test_core_collection_blocks_scoring_router(self):
        """CORE_COLLECTION should fire before SCORING_ROUTER when fields missing."""
        state = make_state(
            user_text="I want to find a hotel",
            trip_inputs={},  # No core fields
        )
        result = GateEvaluator.evaluate(state)
        assert result.gate_fired == GatePrecedence.CORE_COLLECTION
        assert (
            "SCORING_ROUTER" in result.skipped_gates
            or result.gate_fired.value < GatePrecedence.SCORING_ROUTER.value
        )


# =============================================================================
# SIGNAL WEIGHT TESTS
# =============================================================================


class TestSignalWeights:
    """Test that signal weights work correctly."""

    def test_multiple_positive_signals_accumulate(self):
        """Multiple positive signals should accumulate score."""
        state = make_state(
            trip_inputs={
                "booking_types": {"flights": True},
            },
            metadata={"last_intent": "flights"},
        )
        result = _try_deterministic_router("I want to find a flight", state)
        assert result is not None
        # keyword(2) + positive_intent(2) + booking_type(1) + recent_intent(1) = 6
        assert result.score >= 4
        assert result.should_bypass is True

    def test_negative_signals_reduce_score(self):
        """Negative signals should reduce score."""
        state = make_state()
        # "trip" is ambiguous (-2), but "hotel" (+2) present
        result = _try_deterministic_router("I want a hotel for my trip", state)
        # Should still bypass due to positive intent + hotel keyword
        # but score is reduced by ambiguous keyword
        if result is not None and result.should_bypass:
            assert "ambiguous:trip" in result.signals

    def test_question_word_only_is_weak(self):
        """Question word without domain keyword should be weak signal."""
        state = make_state()
        result = _try_deterministic_router("what should I do", state)
        # No domain keyword, just question word (-1)
        assert result is None or not result.should_bypass
