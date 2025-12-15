"""Tests for caching functionality."""

# ruff: noqa: E402

import os
import sys
from pathlib import Path

# Suppress debug output before importing plan_graph
os.environ["PLAN_GRAPH_DEBUG"] = "0"

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from app.plan_graph import (
    GraphState,
    TripInputs,
    _compute_cache_key,
    _follow_up_cache,
    _get_cached_response,
    _get_core_fields_state,
    _increment_cache_hits,
    _increment_llm_calls,
    _ready_state_cache,
    _set_cached_response,
    load_prompt,
)


class TestComputeCacheKey:
    """Tests for cache key computation."""

    def test_cache_key_consistency(self):
        """Same inputs should produce same cache key."""
        key1 = _compute_cache_key("required_fields", '{"destinations": ["Paris"]}', "quick_booking")
        key2 = _compute_cache_key("required_fields", '{"destinations": ["Paris"]}', "quick_booking")
        assert key1 == key2

    def test_different_prompts_different_keys(self):
        """Different prompt names should produce different keys."""
        key1 = _compute_cache_key("required_fields", '{"destinations": ["Paris"]}', "")
        key2 = _compute_cache_key("flights", '{"destinations": ["Paris"]}', "")
        assert key1 != key2

    def test_different_fields_different_keys(self):
        """Different core fields should produce different keys."""
        key1 = _compute_cache_key("required_fields", '{"destinations": ["Paris"]}', "")
        key2 = _compute_cache_key("required_fields", '{"destinations": ["London"]}', "")
        assert key1 != key2

    def test_different_intent_different_keys(self):
        """Different user intents should produce different keys."""
        key1 = _compute_cache_key("required_fields", '{"destinations": ["Paris"]}', "quick_booking")
        key2 = _compute_cache_key(
            "required_fields", '{"destinations": ["Paris"]}', "detailed_planner"
        )
        assert key1 != key2

    def test_cache_key_is_hex_string(self):
        """Cache key should be a valid hex MD5 hash."""
        key = _compute_cache_key("test", "data", "intent")
        assert len(key) == 32  # MD5 produces 32 hex chars
        assert all(c in "0123456789abcdef" for c in key)


class TestGetCoreFieldsState:
    """Tests for core fields state serialization."""

    def test_serializes_all_core_fields(self):
        """Should serialize destinations, origin, start_date, has_end_date."""
        trip_inputs = TripInputs(
            destinations=["Paris", "London"],
            origin="New York",
            start_date="2025-06-01",
            end_date="2025-06-15",
        )
        state = _get_core_fields_state(trip_inputs)
        assert "Paris" in state
        assert "London" in state
        assert "New York" in state
        assert "2025-06-01" in state
        assert "true" in state.lower() or "True" in state  # has_end_date

    def test_destinations_sorted_for_consistency(self):
        """Destinations should be sorted for consistent keys."""
        trip1 = TripInputs(destinations=["Paris", "London"])
        trip2 = TripInputs(destinations=["London", "Paris"])
        state1 = _get_core_fields_state(trip1)
        state2 = _get_core_fields_state(trip2)
        # After sorting, both should produce same state
        assert state1 == state2

    def test_handles_empty_fields(self):
        """Should handle None/empty fields gracefully."""
        trip_inputs = TripInputs()
        state = _get_core_fields_state(trip_inputs)
        assert isinstance(state, str)
        # Should be valid JSON
        import json

        parsed = json.loads(state)
        assert "destinations" in parsed
        assert "origin" in parsed


class TestCacheOperations:
    """Tests for cache get/set operations."""

    def test_set_and_get_response(self):
        """Should be able to set and retrieve cached response."""
        from cachetools import TTLCache

        test_cache = TTLCache(maxsize=10, ttl=60)

        key = "test_key_123"
        response = {"assistant_message": "Hello!", "parsed_updates": {}}

        _set_cached_response(test_cache, key, response)
        result = _get_cached_response(test_cache, key)

        assert result == response

    def test_cache_miss_returns_none(self):
        """Cache miss should return None."""
        from cachetools import TTLCache

        test_cache = TTLCache(maxsize=10, ttl=60)

        result = _get_cached_response(test_cache, "nonexistent_key")
        assert result is None

    def test_cache_maxsize_eviction(self):
        """Cache should evict old entries when maxsize reached."""
        from cachetools import TTLCache

        small_cache = TTLCache(maxsize=2, ttl=60)

        _set_cached_response(small_cache, "key1", {"value": 1})
        _set_cached_response(small_cache, "key2", {"value": 2})
        _set_cached_response(small_cache, "key3", {"value": 3})

        # First key should be evicted
        assert _get_cached_response(small_cache, "key1") is None
        assert _get_cached_response(small_cache, "key3") is not None


class TestCacheCounters:
    """Tests for cache hit/LLM call counters."""

    def test_increment_cache_hits(self):
        """Cache hit counter should increment."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(),
            metadata={},
        )
        assert state.metadata.get("cache_hits", 0) == 0

        _increment_cache_hits(state)
        assert state.metadata.get("cache_hits") == 1

        _increment_cache_hits(state)
        assert state.metadata.get("cache_hits") == 2

    def test_increment_llm_calls(self):
        """LLM call counter should increment."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(),
            metadata={},
        )
        assert state.metadata.get("llm_calls_made", 0) == 0

        _increment_llm_calls(state)
        assert state.metadata.get("llm_calls_made") == 1

        _increment_llm_calls(state)
        assert state.metadata.get("llm_calls_made") == 2


class TestLoadPromptCache:
    """Tests for prompt loading cache."""

    def test_load_prompt_returns_string(self):
        """load_prompt should return prompt content as string."""
        prompt = load_prompt("router")
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_load_prompt_cache_hit(self):
        """Second call should hit cache (faster)."""
        # First call
        prompt1 = load_prompt("router")
        # Second call (should be cached)
        prompt2 = load_prompt("router")

        assert prompt1 == prompt2

    def test_load_prompt_different_prompts(self):
        """Different prompts should load different content."""
        router_prompt = load_prompt("router")
        monolith_prompt = load_prompt("monolith")

        assert router_prompt != monolith_prompt

    def test_load_prompt_invalid_name(self):
        """Invalid prompt name should raise or return empty."""
        from jinja2.exceptions import TemplateNotFound

        try:
            result = load_prompt("nonexistent_prompt_xyz")
            # If it doesn't raise, should return empty or None
            assert result is None or result == ""
        except (FileNotFoundError, ValueError, TemplateNotFound):
            pass  # Expected behavior


class TestGlobalCacheInstances:
    """Tests for global cache instances."""

    def test_follow_up_cache_exists(self):
        """_follow_up_cache should be a TTLCache instance."""
        from cachetools import TTLCache

        assert isinstance(_follow_up_cache, TTLCache)

    def test_ready_state_cache_exists(self):
        """_ready_state_cache should be a TTLCache instance."""
        from cachetools import TTLCache

        assert isinstance(_ready_state_cache, TTLCache)

    def test_caches_have_reasonable_settings(self):
        """Caches should have reasonable maxsize and TTL."""
        # Check maxsize is reasonable (not too small, not huge)
        assert _follow_up_cache.maxsize >= 50
        assert _follow_up_cache.maxsize <= 1000

        # Check TTL is reasonable (at least 60 seconds, not more than a day)
        assert _follow_up_cache.ttl >= 60
        assert _follow_up_cache.ttl <= 86400
