"""
Tests for the shared L1 in-memory cache primitive in app.services.cache_core.

Covers:
- Basic get/set operations
- __contains__, __len__, keys()
- __setitem__ alias
- clear() returns evicted count
- TTL expiry
- maxsize eviction
- Stats tracking (increment_stat, get_stats)
- Custom vs default stat_keys
- Thread safety under concurrent access
"""

from __future__ import annotations

import threading
import time

from app.services.cache_core import MemoryCache

# =============================================================================
# Basic Operations
# =============================================================================


class TestBasicGetSet:
    """Tests for get/set core operations."""

    def test_set_then_get(self):
        cache = MemoryCache(maxsize=10, ttl=60)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_missing_returns_none(self):
        cache = MemoryCache(maxsize=10, ttl=60)
        assert cache.get("nonexistent") is None

    def test_overwrite_existing_key(self):
        cache = MemoryCache(maxsize=10, ttl=60)
        cache.set("key", "first")
        cache.set("key", "second")
        assert cache.get("key") == "second"

    def test_stores_various_types(self):
        cache = MemoryCache(maxsize=10, ttl=60)
        cache.set("int", 42)
        cache.set("list", [1, 2, 3])
        cache.set("dict", {"a": 1})
        cache.set("none", None)
        assert cache.get("int") == 42
        assert cache.get("list") == [1, 2, 3]
        assert cache.get("dict") == {"a": 1}
        assert cache.get("none") is None

    def test_setitem_alias(self):
        cache = MemoryCache(maxsize=10, ttl=60)
        cache["key"] = "value"
        assert cache.get("key") == "value"


# =============================================================================
# Container Protocol (__contains__, __len__, keys)
# =============================================================================


class TestContainerProtocol:
    """Tests for __contains__, __len__, and keys()."""

    def test_contains_returns_true_for_set_key(self):
        cache = MemoryCache(maxsize=10, ttl=60)
        cache.set("present", 1)
        assert "present" in cache

    def test_contains_returns_false_for_missing_key(self):
        cache = MemoryCache(maxsize=10, ttl=60)
        assert "missing" not in cache

    def test_len_empty_cache(self):
        cache = MemoryCache(maxsize=10, ttl=60)
        assert len(cache) == 0

    def test_len_after_inserts(self):
        cache = MemoryCache(maxsize=10, ttl=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        assert len(cache) == 3

    def test_keys_returns_list(self):
        cache = MemoryCache(maxsize=10, ttl=60)
        cache.set("x", 1)
        cache.set("y", 2)
        result = cache.keys()
        assert isinstance(result, list)
        assert set(result) == {"x", "y"}

    def test_keys_empty_cache(self):
        cache = MemoryCache(maxsize=10, ttl=60)
        assert cache.keys() == []

    def test_keys_returns_snapshot(self):
        """keys() returns a copy, not a live view."""
        cache = MemoryCache(maxsize=10, ttl=60)
        cache.set("a", 1)
        keys = cache.keys()
        cache.set("b", 2)
        # The snapshot should not include 'b'
        assert "b" not in keys


# =============================================================================
# Clear
# =============================================================================


class TestClear:
    """Tests for clear() operation."""

    def test_clear_returns_evicted_count(self):
        cache = MemoryCache(maxsize=10, ttl=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        count = cache.clear()
        assert count == 3

    def test_clear_empties_cache(self):
        cache = MemoryCache(maxsize=10, ttl=60)
        cache.set("a", 1)
        cache.clear()
        assert len(cache) == 0
        assert cache.get("a") is None

    def test_clear_empty_cache_returns_zero(self):
        cache = MemoryCache(maxsize=10, ttl=60)
        assert cache.clear() == 0


# =============================================================================
# TTL Expiry
# =============================================================================


class TestTTLExpiry:
    """Tests for time-to-live cache expiration."""

    def test_entry_expires_after_ttl(self):
        cache = MemoryCache(maxsize=10, ttl=1)  # 1 second TTL
        cache.set("ephemeral", "data")
        assert cache.get("ephemeral") == "data"
        time.sleep(1.5)
        assert cache.get("ephemeral") is None

    def test_entry_alive_before_ttl(self):
        cache = MemoryCache(maxsize=10, ttl=10)
        cache.set("durable", "data")
        assert cache.get("durable") == "data"

    def test_contains_false_after_expiry(self):
        cache = MemoryCache(maxsize=10, ttl=1)
        cache.set("temp", "val")
        time.sleep(1.5)
        assert "temp" not in cache


# =============================================================================
# Maxsize Eviction
# =============================================================================


class TestMaxsizeEviction:
    """Tests for LRU eviction when maxsize is exceeded."""

    def test_evicts_when_full(self):
        cache = MemoryCache(maxsize=3, ttl=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.set("d", 4)  # should evict oldest
        assert len(cache) == 3
        # 'd' should be present
        assert cache.get("d") == 4

    def test_maxsize_respected(self):
        cache = MemoryCache(maxsize=5, ttl=60)
        for i in range(20):
            cache.set(f"key_{i}", i)
        assert len(cache) <= 5


# =============================================================================
# Stats Tracking
# =============================================================================


class TestStatsTracking:
    """Tests for increment_stat and get_stats."""

    def test_default_stat_keys(self):
        cache = MemoryCache(maxsize=10, ttl=60)
        stats = cache.get_stats()
        expected_keys = {"l1_hits", "l1_misses", "l2_hits", "l2_misses", "writes"}
        assert set(stats.keys()) == expected_keys

    def test_all_default_stats_start_at_zero(self):
        cache = MemoryCache(maxsize=10, ttl=60)
        stats = cache.get_stats()
        for value in stats.values():
            assert value == 0

    def test_custom_stat_keys(self):
        cache = MemoryCache(maxsize=10, ttl=60, stat_keys=["hits", "misses", "evictions"])
        stats = cache.get_stats()
        assert set(stats.keys()) == {"hits", "misses", "evictions"}

    def test_increment_stat(self):
        cache = MemoryCache(maxsize=10, ttl=60)
        cache.increment_stat("l1_hits")
        cache.increment_stat("l1_hits")
        cache.increment_stat("l1_misses")
        stats = cache.get_stats()
        assert stats["l1_hits"] == 2
        assert stats["l1_misses"] == 1

    def test_increment_unknown_stat_creates_it(self):
        cache = MemoryCache(maxsize=10, ttl=60)
        cache.increment_stat("custom_counter")
        stats = cache.get_stats()
        assert stats["custom_counter"] == 1

    def test_get_stats_returns_copy(self):
        """get_stats should return a dict copy, not a reference."""
        cache = MemoryCache(maxsize=10, ttl=60)
        stats1 = cache.get_stats()
        cache.increment_stat("l1_hits")
        stats2 = cache.get_stats()
        assert stats1["l1_hits"] == 0
        assert stats2["l1_hits"] == 1


# =============================================================================
# Thread Safety
# =============================================================================


class TestThreadSafety:
    """Tests for concurrent access from multiple threads."""

    def test_concurrent_set_get(self):
        """100 concurrent writes from 10 threads should not crash."""
        cache = MemoryCache(maxsize=1000, ttl=60)
        errors: list[Exception] = []

        def writer(thread_id: int) -> None:
            try:
                for i in range(100):
                    key = f"t{thread_id}_k{i}"
                    cache.set(key, i)
                    cache.get(key)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(tid,)) for tid in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"

    def test_concurrent_stat_increments(self):
        """Concurrent stat increments should not lose counts."""
        cache = MemoryCache(maxsize=10, ttl=60, stat_keys=["counter"])
        errors: list[Exception] = []
        increments_per_thread = 100
        num_threads = 10

        def incrementer() -> None:
            try:
                for _ in range(increments_per_thread):
                    cache.increment_stat("counter")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=incrementer) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        stats = cache.get_stats()
        assert stats["counter"] == increments_per_thread * num_threads

    def test_concurrent_clear(self):
        """Concurrent clears should not crash."""
        cache = MemoryCache(maxsize=100, ttl=60)
        errors: list[Exception] = []

        def fill_and_clear() -> None:
            try:
                for i in range(50):
                    cache.set(f"key_{threading.current_thread().name}_{i}", i)
                cache.clear()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=fill_and_clear) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_concurrent_contains_and_keys(self):
        """Concurrent __contains__ and keys() should not crash."""
        cache = MemoryCache(maxsize=100, ttl=60)
        for i in range(50):
            cache.set(f"init_{i}", i)
        errors: list[Exception] = []

        def reader() -> None:
            try:
                for i in range(100):
                    _ = f"init_{i % 50}" in cache
                    _ = cache.keys()
                    _ = len(cache)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
