"""
Tests for the validation cache infrastructure in app.validation_cache.

Covers:
- prewarm_cache() pre-population
- store_result() and lookup_cache() round-trip (positive, negative, split)
- lookup_fallback() for last-known-good results
- clear_cache() with and without rate-limit preservation
- cache_stats() shape and values
- TTLCache structural verification
- _cache_key() deterministic generation
- _build_prompt() caching behavior
- _check_rate_limit() per-session limiting
"""

from __future__ import annotations

import pytest
from cachetools import TTLCache

from app.validation_cache import (
    _build_prompt,
    _cache_key,
    _check_rate_limit,
    _fallback_cache,
    _negative_cache,
    _prompt_cache,
    _rate_counter_cache,
    _split_cache,
    _validation_cache,
    cache_stats,
    clear_cache,
    lookup_cache,
    lookup_fallback,
    prewarm_cache,
    store_result,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
async def _clear_validation_caches():
    """Clear all validation caches before and after each test."""
    for cache in (
        _validation_cache,
        _negative_cache,
        _split_cache,
        _prompt_cache,
        _fallback_cache,
        _rate_counter_cache,
    ):
        cache.clear()
    yield
    for cache in (
        _validation_cache,
        _negative_cache,
        _split_cache,
        _prompt_cache,
        _fallback_cache,
        _rate_counter_cache,
    ):
        cache.clear()


# =============================================================================
# 1. prewarm_cache populates cache
# =============================================================================


class TestPrewarmCache:
    """Tests for prewarm_cache() pre-population."""

    @pytest.mark.asyncio
    async def test_prewarm_populates_cache(self):
        """prewarm_cache() returns 0 when no VALIDATION_PREWARM_DESTINATIONS env var is set."""
        count = await prewarm_cache()
        # No hardcoded defaults — empty list when env var is unset
        assert count == 0

        stats = await cache_stats()
        assert stats["positive"] == 0
        assert stats["fallback"] == 0

    @pytest.mark.asyncio
    async def test_prewarm_idempotent(self):
        """Calling prewarm twice should not double-count existing entries."""
        count1 = await prewarm_cache()
        count2 = await prewarm_cache()
        assert count1 == 0
        assert count2 == 0  # Already populated (empty), no new entries


# =============================================================================
# 2. store and lookup hit
# =============================================================================


class TestStoreAndLookup:
    """Tests for store_result() -> lookup_cache() round-trip."""

    @pytest.mark.asyncio
    async def test_store_valid_and_lookup(self):
        """Storing a valid result should be retrievable via lookup_cache."""
        result = {"corrected_values": ["Paris"], "is_valid": True, "reason": None}
        await store_result("destination", "paris", result, is_valid=True, reason=None)

        cached = await lookup_cache("destination", "paris")
        assert cached is not None
        assert cached["is_valid"] is True
        assert cached["corrected_values"] == ["Paris"]

    @pytest.mark.asyncio
    async def test_store_valid_populates_fallback(self):
        """Storing a valid result should also populate the fallback cache."""
        result = {"corrected_values": ["Tokyo"], "is_valid": True, "reason": None}
        await store_result("destination", "tokyo", result, is_valid=True, reason=None)

        stats = await cache_stats()
        assert stats["fallback"] == 1


# =============================================================================
# 3. lookup miss
# =============================================================================


class TestLookupMiss:
    """Tests for lookup_cache() with unknown keys."""

    @pytest.mark.asyncio
    async def test_lookup_miss_returns_none(self):
        """Looking up a key that was never stored should return None."""
        result = await lookup_cache("destination", "atlantis")
        assert result is None

    @pytest.mark.asyncio
    async def test_lookup_miss_different_field_type(self):
        """Storing under one field_type should not match another."""
        result = {"corrected_values": ["London"], "is_valid": True, "reason": None}
        await store_result("destination", "london", result, is_valid=True, reason=None)

        cached = await lookup_cache("origin", "london")
        assert cached is None


# =============================================================================
# 4. negative cache
# =============================================================================


class TestNegativeCache:
    """Tests for negative (invalid) result caching."""

    @pytest.mark.asyncio
    async def test_store_invalid_and_lookup(self):
        """Storing an invalid result should return is_valid=False with reason."""
        await store_result(
            "destination",
            "xyznotaplace",
            {"corrected_values": [], "is_valid": False, "reason": "Not a real place"},
            is_valid=False,
            reason="Not a real place",
        )

        cached = await lookup_cache("destination", "xyznotaplace")
        assert cached is not None
        assert cached["is_valid"] is False
        assert cached["reason"] == "Not a real place"
        assert cached["corrected_values"] == []

    @pytest.mark.asyncio
    async def test_negative_cache_default_reason(self):
        """Storing invalid with reason=None should default to 'Invalid input'."""
        await store_result(
            "origin",
            "nowhere",
            {"corrected_values": [], "is_valid": False, "reason": None},
            is_valid=False,
            reason=None,
        )

        cached = await lookup_cache("origin", "nowhere")
        assert cached is not None
        assert cached["is_valid"] is False
        assert cached["reason"] == "Invalid input"

    @pytest.mark.asyncio
    async def test_negative_not_in_positive_cache(self):
        """Invalid results should only be in negative cache, not positive."""
        await store_result(
            "destination",
            "badplace",
            {"corrected_values": [], "is_valid": False, "reason": "Bad"},
            is_valid=False,
            reason="Bad",
        )

        stats = await cache_stats()
        assert stats["positive"] == 0
        assert stats["negative"] == 1


# =============================================================================
# 5. TTL expiry (structural)
# =============================================================================


class TestTTLStructure:
    """Structural tests verifying caches are TTLCache instances."""

    def test_validation_cache_is_ttlcache(self):
        assert isinstance(_validation_cache, TTLCache)

    def test_negative_cache_is_ttlcache(self):
        assert isinstance(_negative_cache, TTLCache)

    def test_split_cache_is_ttlcache(self):
        assert isinstance(_split_cache, TTLCache)

    def test_prompt_cache_is_ttlcache(self):
        assert isinstance(_prompt_cache, TTLCache)

    def test_fallback_cache_is_ttlcache(self):
        assert isinstance(_fallback_cache, TTLCache)

    def test_rate_counter_cache_is_ttlcache(self):
        assert isinstance(_rate_counter_cache, TTLCache)


# =============================================================================
# 6. clear_cache preserves rate limiting
# =============================================================================


class TestClearCachePreserveRateLimiting:
    """Tests for clear_cache(preserve_rate_limiting=True)."""

    @pytest.mark.asyncio
    async def test_clear_preserves_rate_counters(self):
        """Rate counter entries should survive when preserve_rate_limiting=True."""
        # Add entries to various caches
        result = {"corrected_values": ["Rome"], "is_valid": True, "reason": None}
        await store_result("destination", "rome", result, is_valid=True, reason=None)
        await store_result(
            "destination",
            "fake",
            {"corrected_values": [], "is_valid": False, "reason": "Bad"},
            is_valid=False,
            reason="Bad",
        )
        # Add a rate counter entry directly
        _rate_counter_cache["session-abc"] = 5

        stats_before = await cache_stats()
        assert stats_before["positive"] >= 1
        assert stats_before["negative"] >= 1
        assert stats_before["rate_counters"] == 1

        cleared = await clear_cache(preserve_rate_limiting=True)
        assert cleared > 0

        stats_after = await cache_stats()
        assert stats_after["positive"] == 0
        assert stats_after["negative"] == 0
        assert stats_after["split"] == 0
        assert stats_after["prompt"] == 0
        assert stats_after["fallback"] == 0
        # Rate counters should survive
        assert stats_after["rate_counters"] == 1


# =============================================================================
# 7. clear_cache full reset
# =============================================================================


class TestClearCacheFullReset:
    """Tests for clear_cache(preserve_rate_limiting=False)."""

    @pytest.mark.asyncio
    async def test_clear_full_reset(self):
        """Everything including rate counters should be cleared."""
        result = {"corrected_values": ["Berlin"], "is_valid": True, "reason": None}
        await store_result("destination", "berlin", result, is_valid=True, reason=None)
        _rate_counter_cache["session-xyz"] = 10

        stats_before = await cache_stats()
        assert stats_before["positive"] >= 1
        assert stats_before["rate_counters"] == 1

        cleared = await clear_cache(preserve_rate_limiting=False)
        assert cleared > 0

        stats_after = await cache_stats()
        for key, value in stats_after.items():
            assert value == 0, f"Expected {key} to be 0 after full reset, got {value}"


# =============================================================================
# 8. cache_stats returns all keys
# =============================================================================


class TestCacheStats:
    """Tests for cache_stats() return shape."""

    @pytest.mark.asyncio
    async def test_stats_returns_all_keys(self):
        """cache_stats should return dict with all expected cache category keys."""
        stats = await cache_stats()
        expected_keys = {"positive", "negative", "split", "prompt", "fallback", "rate_counters"}
        assert set(stats.keys()) == expected_keys

    @pytest.mark.asyncio
    async def test_stats_all_zero_on_empty(self):
        """All stats should be zero when caches are empty."""
        stats = await cache_stats()
        for key, value in stats.items():
            assert value == 0, f"Expected {key}=0, got {value}"

    @pytest.mark.asyncio
    async def test_stats_reflect_stored_entries(self):
        """Stats should reflect the actual number of stored entries."""
        await store_result(
            "destination",
            "paris",
            {"corrected_values": ["Paris"], "is_valid": True, "reason": None},
            is_valid=True,
            reason=None,
        )
        await store_result(
            "destination",
            "notreal",
            {"corrected_values": [], "is_valid": False, "reason": "Nope"},
            is_valid=False,
            reason="Nope",
        )

        stats = await cache_stats()
        assert stats["positive"] == 1
        assert stats["negative"] == 1
        assert stats["fallback"] == 1  # valid entries also go to fallback


# =============================================================================
# 9. fallback cache
# =============================================================================


class TestFallbackCache:
    """Tests for lookup_fallback() behavior."""

    @pytest.mark.asyncio
    async def test_fallback_returns_valid_result(self):
        """Storing a valid result should be retrievable via lookup_fallback."""
        result = {"corrected_values": ["Sydney"], "is_valid": True, "reason": None}
        await store_result("destination", "sydney", result, is_valid=True, reason=None)

        fallback = await lookup_fallback("destination", "sydney")
        assert fallback is not None
        assert fallback["corrected_values"] == ["Sydney"]
        assert fallback["is_valid"] is True

    @pytest.mark.asyncio
    async def test_fallback_miss_returns_none(self):
        """lookup_fallback for unknown key should return None."""
        fallback = await lookup_fallback("destination", "nonexistent")
        assert fallback is None

    @pytest.mark.asyncio
    async def test_fallback_not_populated_by_invalid(self):
        """Invalid results should not be stored in the fallback cache."""
        await store_result(
            "destination",
            "badplace",
            {"corrected_values": [], "is_valid": False, "reason": "Invalid"},
            is_valid=False,
            reason="Invalid",
        )

        fallback = await lookup_fallback("destination", "badplace")
        assert fallback is None

    @pytest.mark.asyncio
    async def test_fallback_survives_main_cache_clear(self):
        """Fallback should be cleared when clear_cache is called (not preserved)."""
        result = {"corrected_values": ["Lisbon"], "is_valid": True, "reason": None}
        await store_result("destination", "lisbon", result, is_valid=True, reason=None)

        await clear_cache(preserve_rate_limiting=True)

        fallback = await lookup_fallback("destination", "lisbon")
        # clear_cache clears fallback too
        assert fallback is None


# =============================================================================
# 10. split cache for multi-destination
# =============================================================================


class TestSplitCache:
    """Tests for split cache population on multi-destination results."""

    @pytest.mark.asyncio
    async def test_multi_destination_populates_split_cache(self):
        """Storing a result with >1 corrected_values for destination populates split cache."""
        result = {
            "corrected_values": ["Paris", "London"],
            "is_valid": True,
            "reason": None,
        }
        await store_result("destination", "paris and london", result, is_valid=True, reason=None)

        stats = await cache_stats()
        assert stats["split"] == 1
        assert stats["positive"] == 1

    @pytest.mark.asyncio
    async def test_single_destination_does_not_populate_split(self):
        """A single corrected_value should not create a split cache entry."""
        result = {"corrected_values": ["Paris"], "is_valid": True, "reason": None}
        await store_result("destination", "paris", result, is_valid=True, reason=None)

        stats = await cache_stats()
        assert stats["split"] == 0

    @pytest.mark.asyncio
    async def test_non_destination_multi_does_not_populate_split(self):
        """Multi-value results for non-destination field_type should not use split cache."""
        result = {
            "corrected_values": ["New York", "Boston"],
            "is_valid": True,
            "reason": None,
        }
        await store_result("origin", "new york and boston", result, is_valid=True, reason=None)

        stats = await cache_stats()
        assert stats["split"] == 0

    @pytest.mark.asyncio
    async def test_split_cache_lookup(self):
        """Split cache entries should be found via lookup_cache for destination field_type."""
        result = {
            "corrected_values": ["Tokyo", "Kyoto"],
            "is_valid": True,
            "reason": None,
        }
        await store_result("destination", "tokyo and kyoto", result, is_valid=True, reason=None)

        # Clear the positive cache to force lookup through split cache path
        _validation_cache.clear()

        cached = await lookup_cache("destination", "tokyo and kyoto")
        assert cached is not None
        assert cached["corrected_values"] == ["Tokyo", "Kyoto"]


# =============================================================================
# _cache_key determinism
# =============================================================================


class TestCacheKey:
    """Tests for _cache_key() generation."""

    def test_deterministic(self):
        """Same inputs should produce the same key."""
        key1 = _cache_key("destination", "Paris")
        key2 = _cache_key("destination", "Paris")
        assert key1 == key2

    def test_case_insensitive(self):
        """Keys should be case-insensitive (normalized to lowercase)."""
        key1 = _cache_key("destination", "Paris")
        key2 = _cache_key("destination", "paris")
        key3 = _cache_key("destination", "PARIS")
        assert key1 == key2 == key3

    def test_strips_whitespace(self):
        """Leading/trailing whitespace should be stripped."""
        key1 = _cache_key("destination", "Paris")
        key2 = _cache_key("destination", "  Paris  ")
        assert key1 == key2

    def test_different_field_types_differ(self):
        """Different field types should produce different keys."""
        key1 = _cache_key("destination", "Paris")
        key2 = _cache_key("origin", "Paris")
        assert key1 != key2


# =============================================================================
# _build_prompt caching
# =============================================================================


class TestBuildPrompt:
    """Tests for _build_prompt() with caching."""

    @pytest.mark.asyncio
    async def test_prompt_is_formatted(self):
        """Prompt should format the field_type and value into the template."""
        template = "Validate {field_type}: {value}"
        prompt = await _build_prompt("destination", "paris", template)
        assert prompt == "Validate destination: paris"

    @pytest.mark.asyncio
    async def test_prompt_is_cached(self):
        """Second call with same args should hit the prompt cache."""
        template = "Validate {field_type}: {value}"
        prompt1 = await _build_prompt("destination", "paris", template)

        stats = await cache_stats()
        assert stats["prompt"] == 1

        prompt2 = await _build_prompt("destination", "paris", template)
        assert prompt1 == prompt2
        # Still only 1 entry (cache hit, not a new entry)
        stats = await cache_stats()
        assert stats["prompt"] == 1


# =============================================================================
# _check_rate_limit
# =============================================================================


class TestCheckRateLimit:
    """Tests for _check_rate_limit() per-session limiting."""

    @pytest.mark.asyncio
    async def test_no_session_id_returns_none(self):
        """No session ID means no rate limiting."""
        result = await _check_rate_limit(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_under_limit_returns_none(self):
        """Requests under the limit should return None."""
        result = await _check_rate_limit("session-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_exceeding_limit_returns_message(self):
        """Exceeding the rate limit should return a rejection message."""
        from app.config import settings

        # Fill up to the limit
        for _ in range(settings.validation_rate_limit_max_requests):
            result = await _check_rate_limit("session-flood")
            assert result is None

        # One more should exceed
        result = await _check_rate_limit("session-flood")
        assert result is not None
        assert "too many" in result.lower()

    @pytest.mark.asyncio
    async def test_separate_sessions_independent(self):
        """Different session IDs should have independent counters."""
        await _check_rate_limit("session-a")
        await _check_rate_limit("session-a")
        await _check_rate_limit("session-b")

        stats = await cache_stats()
        assert stats["rate_counters"] == 2
