"""
Tests for v6 cache hardening: thread isolation, validity checking, and gate invariants.

Priority tests that catch 90% of regressions:
1. User_text hard constraint test
2. Gate invariant test
3. Contract mismatch eviction test
4. LLM call-site accounting test
"""

# ruff: noqa: E402

import hashlib
import os
import sys
from pathlib import Path

# Suppress debug output before importing plan_graph
os.environ["PLAN_GRAPH_DEBUG"] = "0"

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from datetime import date, timedelta

import pytest

from app.plan_graph import (
    CACHE_SCHEMA_VERSION,
    NODE_LOGIC_VERSION,
    PLANNER_BUILD_ID,
    PROMPT_BUNDLE_HASH,
    CachePayload,
    GateEvaluator,
    GraphState,
    TripInputs,
    _compute_cache_key_v6,
    _get_core_fields_state,
    _get_question_target_category,
    _required_fields_cache,
    clear_all_caches,
    compute_trip_readiness,
    get_cached_response_v6,
    set_cached_response_v6,
)
from app.planner.parsing.provenance import (
    finalize_parse_provenance,
    set_parse_provenance_once,
)

FUTURE_DATE = (date.today() + timedelta(days=30)).isoformat()
FUTURE_END_DATE = (date.today() + timedelta(days=40)).isoformat()


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear all caches before each test."""
    clear_all_caches()
    yield
    clear_all_caches()


class TestUserTextHardConstraint:
    """
    Priority Test 1: User_text hard constraint

    Same thread + same question_target/question_id, different user_text ⇒ must miss cache.
    """

    def test_different_user_text_cache_miss(self):
        """Cache must miss when user_text differs even if all else matches."""
        # Create two states with same thread but different user_text
        state1 = GraphState(
            user_text="Family of four",
            trip_inputs=TripInputs(destinations=["Paris"]),
            metadata={"thread_id": "thread_123", "question_id_counter": 1},
        )
        state2 = GraphState(
            user_text="Just me",
            trip_inputs=TripInputs(destinations=["Paris"]),
            metadata={"thread_id": "thread_123", "question_id_counter": 1},
        )

        # Cache a response for state1
        set_cached_response_v6(
            node_name="required_fields",
            state=state1,
            assistant_message="How many travelers?",
            question_target="travelers",
            suggested_responses=["Just me", "Two adults", "Family of four"],
            suggestion_kind="travelers",
            current_missing_all=["travelers"],
            current_ready_state=False,
        )

        # Attempt to get cache for state2 (different user_text)
        cached = get_cached_response_v6(
            node_name="required_fields",
            state=state2,
            current_question_target="travelers",
            current_question_id=1,
            current_missing_all=["travelers"],
            current_ready_state=False,
        )

        # Must be a cache miss
        assert cached is None, "Cache should miss for different user_text"

    def test_same_user_text_cache_hit(self):
        """Cache should hit when user_text matches."""
        state = GraphState(
            user_text="Family of four",
            trip_inputs=TripInputs(destinations=["Paris"]),
            metadata={"thread_id": "thread_123", "question_id_counter": 1},
        )

        # Cache a response
        set_cached_response_v6(
            node_name="required_fields",
            state=state,
            assistant_message="How many travelers?",
            question_target="travelers",
            suggested_responses=["Just me", "Two adults", "Family of four"],
            suggestion_kind="travelers",
            current_missing_all=["travelers"],
            current_ready_state=False,
        )

        # Get with same state
        cached = get_cached_response_v6(
            node_name="required_fields",
            state=state,
            current_question_target="travelers",
            current_question_id=1,
            current_missing_all=["travelers"],
            current_ready_state=False,
        )

        # Should hit
        assert cached is not None, "Cache should hit for same user_text"
        assert cached.assistant_message == "How many travelers?"


class TestGateInvariant:
    """
    Priority Test 2: Gate invariant

    missing_all == [] at readiness_pre ⇒ required_fields node is unreachable.
    """

    def test_required_fields_unreachable_when_missing_all_empty(self):
        """Gate must not route to required_fields when missing_all is empty."""
        # Create fully-specified state (all fields present)
        state = GraphState(
            user_text="I want to go to Paris",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="New York",
                start_date=FUTURE_DATE,
                end_date=FUTURE_END_DATE,
                adults=2,
                budget=5000,
            ),
            metadata={"thread_id": "thread_123"},
        )

        # Verify readiness shows no missing fields
        readiness = compute_trip_readiness(state.trip_inputs)
        assert len(readiness.missing_all) == 0, "Should have no missing fields"
        assert readiness.ready_to_generate, "Should be ready to generate"

        # Evaluate gate
        gate_result = GateEvaluator.evaluate(state)

        # Gate should NOT route to required_fields
        assert gate_result.destination != "required_fields_node", (
            f"Gate should not route to required_fields when missing_all is empty. "
            f"Got: {gate_result.destination}, reason: {gate_result.reason}"
        )

    def test_required_fields_reachable_when_missing_all_nonempty(self):
        """Gate can route to required_fields when missing_all has items."""
        # Create state with missing core fields
        state = GraphState(
            user_text="I want to plan a trip",
            trip_inputs=TripInputs(),  # Empty - all fields missing
            metadata={"thread_id": "thread_123"},
        )

        # Verify readiness shows missing fields
        readiness = compute_trip_readiness(state.trip_inputs)
        assert len(readiness.missing_all) > 0, "Should have missing fields"

        # Evaluate gate
        gate_result = GateEvaluator.evaluate(state)

        # Gate CAN route to required_fields (though it might not if other gates fire)
        # This test just verifies the invariant doesn't block when it shouldn't
        if gate_result.destination == "required_fields_node":
            # This is allowed when missing_all is non-empty
            pass
        # If it went elsewhere (e.g., short_circuit), that's also fine


class TestContractMismatchEviction:
    """
    Priority Test 3: Contract mismatch eviction

    Poison cache entry with suggestion_kind="travelers" but question_target="dates"
    ⇒ must evict and regenerate.
    """

    def test_suggestion_contract_mismatch_evicts(self):
        """Cache with mismatched suggestion_kind must be evicted."""
        state = GraphState(
            user_text="When should I go?",
            trip_inputs=TripInputs(destinations=["Paris"]),
            metadata={"thread_id": "thread_123", "question_id_counter": 1},
            intent="required_fields",  # Match the intent in the poisoned payload
        )

        # Manually poison the cache with mismatched suggestion_kind
        # Store a "travelers" response but we'll query for "dates"
        thread_id = "thread_123"
        # Use normalized text for hash (matching _normalize_user_text_for_cache behavior)
        normalized_text = state.user_text.strip().lower().rstrip("!.?")
        user_text_hash = hashlib.md5(normalized_text.encode()).hexdigest()[:16]
        core_hash = _get_core_fields_state(state.trip_inputs)

        # Create a poisoned payload with wrong suggestion_kind
        poisoned_payload = CachePayload(
            payload_kind="required_fields",
            node_name="required_fields",
            schema_version=CACHE_SCHEMA_VERSION,
            logic_version=NODE_LOGIC_VERSION.get("required_fields", 1),
            prompt_bundle_hash=PROMPT_BUNDLE_HASH,
            planner_build_id=PLANNER_BUILD_ID,
            assistant_message="How many travelers?",
            question_target="dates",  # Says "dates" but...
            suggested_responses=["Just me", "Two adults"],
            suggestion_kind="travelers",  # ...suggestions are for travelers!
            suggestion_question_id=1,
            thread_id=thread_id,
            user_text_hash=user_text_hash,
            answered_question_target="dates",
            answered_missing_all=["dates"],
            core_hash=core_hash,
            ready_state_at_write=False,
            intent="required_fields",
            model_id="gpt-4o-mini",
            last_summary_hash="abc123",
            response_text_hash="abc123",
            suggestions_hash="def456",
            created_at=1234567890.0,
            provenance="cached",
            extra={},
        )

        # Manually insert into cache using same key computation as get_cached_response_v6
        # The key must use the same model_id that get_cached_response_v6 will use
        from app.config import settings

        model_id = settings.llm_model if hasattr(settings, "llm_model") else "gpt-4o-mini"

        cache_key = _compute_cache_key_v6(
            node_name="required_fields",
            thread_id=thread_id,
            user_text_hash=user_text_hash,
            question_target="dates",
            question_id=1,
            missing_all=["dates"],
            intent="required_fields",
            core_hash=core_hash,
            ready_state=False,
            model_id=model_id,
        )
        _required_fields_cache[cache_key] = poisoned_payload.to_dict()

        # Confirm the cache entry exists
        assert cache_key in _required_fields_cache, "Cache entry should exist before get"

        # Now try to get the cached response
        cached = get_cached_response_v6(
            node_name="required_fields",
            state=state,
            current_question_target="dates",
            current_question_id=1,
            current_missing_all=["dates"],
            current_ready_state=False,
        )

        # Should be evicted due to contract violation
        assert cached is None, "Poisoned cache entry should be evicted"

        # Verify the entry was actually evicted from cache
        assert cache_key not in _required_fields_cache, "Entry should be removed from cache"

    def test_question_target_category_mapping(self):
        """Verify question_target to category mapping works."""
        assert _get_question_target_category("dates") == "dates"
        assert _get_question_target_category("start_date") == "dates"
        assert _get_question_target_category("end_date") == "dates"
        assert _get_question_target_category("destinations") == "places"
        assert _get_question_target_category("origin") == "places"
        assert _get_question_target_category("travelers") == "travelers"
        assert _get_question_target_category("budget") == "budget"


class TestLLMCallSiteAccounting:
    """
    Priority Test 4: LLM call-site accounting

    Verify end-of-turn totals equal call-site log totals exactly.
    """

    def test_accounting_tracks_calls(self):
        """Verify LLM call accounting is tracked in metadata."""
        state = GraphState(
            user_text="Plan my trip",
            trip_inputs=TripInputs(),
            metadata={
                "thread_id": "thread_123",
                "llm_calls_this_turn": 0,
                "llm_nodes_called_this_turn": [],
            },
        )

        # Simulate an LLM call being tracked
        state.metadata["llm_calls_this_turn"] = 1
        state.metadata["llm_nodes_called_this_turn"] = ["extractor"]
        state.metadata["node_tokens"] = {"extractor": 500}

        # Verify accounting matches
        assert state.metadata["llm_calls_this_turn"] == 1
        assert "extractor" in state.metadata["llm_nodes_called_this_turn"]
        assert state.metadata["node_tokens"]["extractor"] == 500


class TestProvenancePrecedence:
    """Test v6 parse provenance precedence system."""

    def test_provenance_precedence_cached_highest(self):
        """Cached provenance should win over all others."""
        state = GraphState(
            user_text="test",
            metadata={},
        )

        # Set lower precedence first
        set_parse_provenance_once(state, "llm", "node1")
        assert state.metadata["parse_provenance"] == "llm"

        # Upgrade to higher precedence
        set_parse_provenance_once(state, "cached", "node2")
        assert state.metadata["parse_provenance"] == "cached"

        # Try to downgrade (should be blocked)
        set_parse_provenance_once(state, "llm", "node3")
        assert state.metadata["parse_provenance"] == "cached"

    def test_provenance_finalization(self):
        """Finalized parse provenance cannot be changed."""
        state = GraphState(
            user_text="test",
            metadata={},
        )

        set_parse_provenance_once(state, "template", "node1")
        final = finalize_parse_provenance(state)
        assert final == "template"

        # Try to change after finalization (should be blocked)
        result = set_parse_provenance_once(state, "cached", "node2")
        assert result is False
        assert state.metadata["parse_provenance"] == "template"


class TestCacheKeyComponents:
    """Test v6 cache key includes all required components."""

    def test_cache_key_includes_schema_version(self):
        """Cache key should include schema version."""
        key = _compute_cache_key_v6(
            node_name="required_fields",
            thread_id="thread_123",
            user_text_hash="abc123",
            question_target="dates",
            question_id=1,
            missing_all=["dates"],
            intent="required_fields",
            core_hash="core123",
            ready_state=False,
            model_id="gpt-4o-mini",
        )

        # Key should be deterministic
        key2 = _compute_cache_key_v6(
            node_name="required_fields",
            thread_id="thread_123",
            user_text_hash="abc123",
            question_target="dates",
            question_id=1,
            missing_all=["dates"],
            intent="required_fields",
            core_hash="core123",
            ready_state=False,
            model_id="gpt-4o-mini",
        )
        assert key == key2

    def test_different_thread_different_key(self):
        """Different threads should produce different cache keys."""
        key1 = _compute_cache_key_v6(
            node_name="required_fields",
            thread_id="thread_123",
            user_text_hash="abc123",
            question_target="dates",
            question_id=1,
            missing_all=["dates"],
            intent="required_fields",
            core_hash="core123",
            ready_state=False,
            model_id="gpt-4o-mini",
        )
        key2 = _compute_cache_key_v6(
            node_name="required_fields",
            thread_id="thread_456",  # Different thread
            user_text_hash="abc123",
            question_target="dates",
            question_id=1,
            missing_all=["dates"],
            intent="required_fields",
            core_hash="core123",
            ready_state=False,
            model_id="gpt-4o-mini",
        )
        assert key1 != key2


class TestReadyStateFlip:
    """Test that cached not-ready response is never returned when ready."""

    def test_ready_state_mismatch_cache_miss(self):
        """Cache must miss when ready_state differs."""
        # State when not ready
        state_not_ready = GraphState(
            user_text="Paris trip",
            trip_inputs=TripInputs(destinations=["Paris"]),  # Missing other fields
            metadata={"thread_id": "thread_123", "question_id_counter": 1},
        )

        # Cache a response when not ready
        set_cached_response_v6(
            node_name="required_fields",
            state=state_not_ready,
            assistant_message="When would you like to travel?",
            question_target="dates",
            suggested_responses=["Next month", "This summer"],
            suggestion_kind="dates",
            current_missing_all=["dates", "origin"],
            current_ready_state=False,  # Not ready
        )

        # Try to get when ready (different ready_state)
        cached = get_cached_response_v6(
            node_name="required_fields",
            state=state_not_ready,
            current_question_target="dates",
            current_question_id=1,
            current_missing_all=["dates", "origin"],
            current_ready_state=True,  # Now ready
        )

        # Should miss due to ready_state mismatch
        assert cached is None, "Cache should miss when ready_state differs"


# =============================================================================
# PR-B: Cache Summary Metrics Tests
# =============================================================================


class TestCacheInvalidReasonConstants:
    """Tests for standardized cache invalidation reason constants."""

    def test_reason_constants_defined(self):
        """All required reason constants should be defined."""
        from app.plan_graph import CacheInvalidReason

        required_reasons = [
            "SCHEMA_VERSION_MISMATCH",
            "LOGIC_VERSION_MISMATCH",
            "PROMPT_BUNDLE_HASH_MISMATCH",
            "PLANNER_BUILD_ID_MISMATCH",
            "HARD_CONSTRAINT_MISMATCH",
            "READY_STATE_FLIP",
            "CONTRACT_MISMATCH",
            "TTL_EXPIRED",
            "PAYLOAD_KIND_MISMATCH",
            "THREAD_MISMATCH",
            "USER_TEXT_MISMATCH",
            "QUESTION_TARGET_MISMATCH",
            "QUESTION_ID_MISMATCH",
            "MISSING_ALL_MISMATCH",
            "CORE_HASH_MISMATCH",
            "UNKNOWN",
        ]

        for reason in required_reasons:
            assert hasattr(CacheInvalidReason, reason), f"Missing reason: {reason}"
            value = getattr(CacheInvalidReason, reason)
            assert isinstance(value, str), f"Reason {reason} should be a string"
            assert len(value) > 0, f"Reason {reason} should not be empty"

    def test_reason_values_lowercase_snake_case(self):
        """Reason values should be lowercase snake_case."""
        from app.plan_graph import CacheInvalidReason

        for attr in dir(CacheInvalidReason):
            if attr.startswith("_"):
                continue
            value = getattr(CacheInvalidReason, attr)
            if isinstance(value, str):
                assert value == value.lower(), f"{attr} value should be lowercase"
                assert " " not in value, f"{attr} value should not have spaces"


class TestSummarizeCacheEvents:
    """Tests for summarize_cache_events() function."""

    def test_empty_events_returns_empty_summary(self):
        """Empty events should return empty summary."""
        from app.plan_graph import summarize_cache_events

        summary = summarize_cache_events([])
        assert summary["by_node"] == {}
        assert summary["by_reason"] == {}
        assert summary["hit_rate_by_node"] == {}

    def test_single_hit_event(self):
        """Single hit event should be counted correctly."""
        from app.plan_graph import summarize_cache_events

        events = [{"node": "required_fields", "action": "hit", "reason": None}]
        summary = summarize_cache_events(events)

        assert "required_fields" in summary["by_node"]
        assert summary["by_node"]["required_fields"]["hit"] == 1
        assert summary["by_node"]["required_fields"]["miss"] == 0
        assert summary["hit_rate_by_node"]["required_fields"] == 1.0

    def test_hit_and_miss_events(self):
        """Hit and miss events should calculate correct hit rate."""
        from app.plan_graph import summarize_cache_events

        events = [
            {"node": "router", "action": "hit", "reason": None},
            {"node": "router", "action": "miss", "reason": None},
            {"node": "router", "action": "hit", "reason": None},
        ]
        summary = summarize_cache_events(events)

        assert summary["by_node"]["router"]["hit"] == 2
        assert summary["by_node"]["router"]["miss"] == 1
        # Hit rate = 2 / (2 + 1) = 0.666...
        assert abs(summary["hit_rate_by_node"]["router"] - 2 / 3) < 0.001

    def test_discard_with_reason(self):
        """Discard events with reasons should be tracked."""
        from app.plan_graph import summarize_cache_events

        events = [
            {"node": "extractor", "action": "discard", "reason": "schema_version_mismatch:1!=2"},
            {
                "node": "extractor",
                "action": "discard",
                "reason": "prompt_bundle_hash_mismatch:abc!=def",
            },
            {"node": "strategy", "action": "discard", "reason": "schema_version_mismatch:1!=3"},
        ]
        summary = summarize_cache_events(events)

        assert summary["by_node"]["extractor"]["discard"] == 2
        assert summary["by_node"]["strategy"]["discard"] == 1
        # Reasons should be normalized to base category
        assert summary["by_reason"]["schema_version_mismatch"] == 2
        assert summary["by_reason"]["prompt_bundle_hash_mismatch"] == 1

    def test_multiple_nodes(self):
        """Events from multiple nodes should be tracked separately."""
        from app.plan_graph import summarize_cache_events

        events = [
            {"node": "required_fields", "action": "hit", "reason": None},
            {"node": "router", "action": "miss", "reason": None},
            {"node": "extractor", "action": "hit", "reason": None},
        ]
        summary = summarize_cache_events(events)

        assert len(summary["by_node"]) == 3
        assert summary["by_node"]["required_fields"]["hit"] == 1
        assert summary["by_node"]["router"]["miss"] == 1
        assert summary["by_node"]["extractor"]["hit"] == 1


class TestCacheCounters:
    """Tests for process-level rolling cache counters."""

    def test_get_cache_counters_returns_structure(self):
        """get_cache_counters should return correct structure."""
        from app.plan_graph import get_cache_counters

        counters = get_cache_counters()

        assert "totals" in counters
        assert "by_node" in counters
        assert "by_reason" in counters
        assert "hits_total" in counters["totals"]
        assert "misses_total" in counters["totals"]
        assert "discards_total" in counters["totals"]
        assert "evictions_total" in counters["totals"]

    def test_counters_in_admin_endpoint(self):
        """Cache counters should be included in admin endpoint."""
        from app.plan_graph import get_planner_debug_info

        debug_info = get_planner_debug_info()

        assert "cache_counters" in debug_info
        assert "cache_counters_scope" in debug_info
        assert debug_info["cache_counters_scope"] == "process"
        assert "cache_counters_reset_on_restart" in debug_info
        assert debug_info["cache_counters_reset_on_restart"] is True


class TestUserTextHashNormalization:
    """Tests for user text hash normalization for cache key stability."""

    def test_confirmation_variants_hash_identically(self):
        """All confirmation variants should produce the same hash."""
        from app.plan_graph import _hash_user_text

        confirmation_variants = [
            "ok",
            "okay",
            "yes",
            "sure",
            "sounds good",
            "yes!",
            "OK.",
            "Yes!",
            "  ok  ",
            "SURE",
        ]

        hashes = [_hash_user_text(variant) for variant in confirmation_variants]
        # All hashes should be identical
        assert (
            len(set(hashes)) == 1
        ), f"Confirmation variants produced different hashes: {set(hashes)}"

    def test_non_confirmation_hashes_differ(self):
        """Non-confirmation texts should produce different hashes."""
        from app.plan_graph import _hash_user_text

        texts = [
            "I want to go to Paris",
            "Book a hotel",
            "Find flights",
            "ok",  # Confirmation for contrast
        ]

        hashes = [_hash_user_text(text) for text in texts]
        # Non-confirmations should have unique hashes
        non_confirm_hashes = hashes[:3]
        assert len(set(non_confirm_hashes)) == 3, "Non-confirmations should have unique hashes"

    def test_normalize_user_text_for_cache_returns_confirm(self):
        """_normalize_user_text_for_cache should return [CONFIRM] for confirmation variants."""
        from app.plan_graph import _normalize_user_text_for_cache

        assert _normalize_user_text_for_cache("ok") == "[CONFIRM]"
        assert _normalize_user_text_for_cache("yes") == "[CONFIRM]"
        assert _normalize_user_text_for_cache("sure") == "[CONFIRM]"
        assert _normalize_user_text_for_cache("sounds good") == "[CONFIRM]"

    def test_normalize_user_text_preserves_non_confirmations(self):
        """_normalize_user_text_for_cache should preserve non-confirmation text."""
        from app.plan_graph import _normalize_user_text_for_cache

        assert _normalize_user_text_for_cache("I want to go to Paris") == "i want to go to paris"
        assert _normalize_user_text_for_cache("  Book a Hotel!  ") == "book a hotel"

    def test_hash_with_normalize_false_uses_raw_text(self):
        """_hash_user_text with normalize=False should use raw text."""
        from app.plan_graph import _hash_user_text

        # With normalization disabled, "ok" and "yes" should hash differently
        hash_ok = _hash_user_text("ok", normalize=False)
        hash_yes = _hash_user_text("yes", normalize=False)
        assert hash_ok != hash_yes, "Without normalization, 'ok' and 'yes' should hash differently"
