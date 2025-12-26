# backend/tests/langgraph/test_cache_concurrency.py
"""
Tests for cache concurrency safety.

PR3: Verify that cache operations are thread-safe and don't raise
exceptions under concurrent load.
"""

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from app.planner.cache_access import (
    CacheHandle,
    cache_clear,
    cache_contains,
    cache_delete,
    cache_get,
    cache_len,
    cache_pop,
    cache_set,
    clear_all_cache_handles,
    get_cache_handle,
    init_cache_handles,
    update_counters_safe,
    update_nested_counters_safe,
)


class MockCache:
    """Mock TTLCache for testing without cachetools dependency."""

    def __init__(self, maxsize: int = 100, ttl: float = 60):
        self._data = {}
        self.maxsize = maxsize
        self.ttl = ttl

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __setitem__(self, key, value):
        self._data[key] = value

    def __getitem__(self, key):
        return self._data[key]

    def __contains__(self, key):
        return key in self._data

    def __delitem__(self, key):
        del self._data[key]

    def __len__(self):
        return len(self._data)

    def pop(self, key, default=None):
        return self._data.pop(key, default)

    def clear(self):
        self._data.clear()


@pytest.fixture
def mock_caches():
    """Create mock caches and initialize handles."""
    caches = {
        "follow_up": MockCache(),
        "router": MockCache(),
        "required_fields": MockCache(),
        "extractor": MockCache(),
        "strategy": MockCache(),
        "tile": MockCache(),
    }

    handles = init_cache_handles(
        follow_up_cache=caches["follow_up"],
        router_cache=caches["router"],
        required_fields_cache=caches["required_fields"],
        extractor_cache=caches["extractor"],
        strategy_cache=caches["strategy"],
        tile_cache=caches["tile"],
    )

    yield caches, handles

    # Cleanup
    clear_all_cache_handles()


class TestCacheHandleInit:
    """Test cache handle initialization."""

    def test_init_cache_handles_creates_all_handles(self, mock_caches):
        """init_cache_handles should create handles for all caches."""
        caches, handles = mock_caches

        assert len(handles) == 6
        assert "follow_up" in handles
        assert "router" in handles
        assert "required_fields" in handles
        assert "extractor" in handles
        assert "strategy" in handles
        assert "tile" in handles

    def test_handles_have_locks(self, mock_caches):
        """Each handle should have a threading.Lock."""
        _, handles = mock_caches

        for _name, handle in handles.items():
            assert isinstance(handle, CacheHandle)
            assert isinstance(handle.lock, type(threading.Lock()))

    def test_get_cache_handle_returns_handle(self, mock_caches):
        """get_cache_handle should return the correct handle."""
        _, handles = mock_caches

        handle = get_cache_handle("router")
        assert handle is handles["router"]

    def test_get_cache_handle_returns_none_for_unknown(self, mock_caches):
        """get_cache_handle should return None for unknown cache names."""
        _ = mock_caches  # Initialize handles

        # Type ignore because we're testing with an invalid name
        handle = get_cache_handle("unknown")  # type: ignore
        assert handle is None


class TestCacheOperations:
    """Test basic cache operations are thread-safe."""

    def test_cache_get_returns_value(self, mock_caches):
        """cache_get should return cached value."""
        caches, _ = mock_caches
        caches["router"]["test_key"] = "test_value"

        result = cache_get("router", "test_key")

        assert result == "test_value"

    def test_cache_get_returns_none_for_missing(self, mock_caches):
        """cache_get should return None for missing key."""
        _ = mock_caches

        result = cache_get("router", "nonexistent")

        assert result is None

    def test_cache_set_stores_value(self, mock_caches):
        """cache_set should store value in cache."""
        _ = mock_caches

        cache_set("router", "new_key", "new_value")

        result = cache_get("router", "new_key")
        assert result == "new_value"

    def test_cache_pop_removes_and_returns(self, mock_caches):
        """cache_pop should remove and return value."""
        caches, _ = mock_caches
        caches["router"]["pop_key"] = "pop_value"

        result = cache_pop("router", "pop_key")

        assert result == "pop_value"
        assert cache_get("router", "pop_key") is None

    def test_cache_delete_removes_key(self, mock_caches):
        """cache_delete should remove key and return True."""
        caches, _ = mock_caches
        caches["router"]["del_key"] = "del_value"

        result = cache_delete("router", "del_key")

        assert result is True
        assert cache_get("router", "del_key") is None

    def test_cache_delete_returns_false_for_missing(self, mock_caches):
        """cache_delete should return False for missing key."""
        _ = mock_caches

        result = cache_delete("router", "nonexistent")

        assert result is False

    def test_cache_len_returns_count(self, mock_caches):
        """cache_len should return number of items."""
        caches, _ = mock_caches
        caches["router"]["key1"] = "val1"
        caches["router"]["key2"] = "val2"

        result = cache_len("router")

        assert result == 2

    def test_cache_contains_returns_true(self, mock_caches):
        """cache_contains should return True for existing key."""
        caches, _ = mock_caches
        caches["router"]["exists"] = "value"

        result = cache_contains("router", "exists")

        assert result is True

    def test_cache_contains_returns_false(self, mock_caches):
        """cache_contains should return False for missing key."""
        _ = mock_caches

        result = cache_contains("router", "missing")

        assert result is False

    def test_cache_clear_removes_all(self, mock_caches):
        """cache_clear should remove all items."""
        caches, _ = mock_caches
        caches["router"]["key1"] = "val1"
        caches["router"]["key2"] = "val2"

        cache_clear("router")

        assert cache_len("router") == 0


class TestConcurrency:
    """Test thread safety under concurrent load."""

    def test_concurrent_get_set_no_exceptions(self, mock_caches):
        """Concurrent get/set operations should not raise exceptions."""
        _ = mock_caches
        errors = []
        iterations = 100
        num_threads = 10

        def worker(thread_id):
            try:
                for i in range(iterations):
                    key = f"key_{thread_id}_{i}"
                    value = f"value_{thread_id}_{i}"

                    cache_set("router", key, value)
                    result = cache_get("router", key)

                    # Value might be None if another thread cleared
                    # but we should never get an exception
                    if result is not None and result != value:
                        # This would indicate a race condition
                        # but we're mainly checking for no exceptions
                        pass
            except Exception as e:
                errors.append((thread_id, str(e)))

        threads = []
        for tid in range(num_threads):
            t = threading.Thread(target=worker, args=(tid,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors occurred: {errors}"

    def test_concurrent_mixed_operations(self, mock_caches):
        """Mix of get/set/delete operations should be thread-safe."""
        _ = mock_caches
        errors = []
        iterations = 50
        num_threads = 8

        def worker(thread_id):
            try:
                for i in range(iterations):
                    key = f"shared_key_{i % 10}"  # Overlap keys between threads

                    if i % 3 == 0:
                        cache_set("extractor", key, f"value_{thread_id}_{i}")
                    elif i % 3 == 1:
                        cache_get("extractor", key)
                    else:
                        cache_delete("extractor", key, reason="test")
            except Exception as e:
                errors.append((thread_id, str(e)))

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, tid) for tid in range(num_threads)]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    errors.append(("executor", str(e)))

        assert len(errors) == 0, f"Errors occurred: {errors}"


class TestCounterSafety:
    """Test thread-safe counter updates."""

    def test_update_counters_safe_concurrent(self):
        """Concurrent counter updates should not lose counts."""
        counters = {"total": 0}
        num_threads = 10
        increments_per_thread = 100

        def worker():
            for _ in range(increments_per_thread):
                update_counters_safe(counters, "total", 1)

        threads = []
        for _ in range(num_threads):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        expected = num_threads * increments_per_thread
        assert counters["total"] == expected

    def test_update_nested_counters_safe_concurrent(self):
        """Concurrent nested counter updates should not lose counts."""
        counters = {}
        num_threads = 10
        increments_per_thread = 100

        def worker(thread_id):
            for _ in range(increments_per_thread):
                # Each thread updates its own node
                update_nested_counters_safe(counters, f"node_{thread_id}", "hits", 1)
                # And a shared node
                update_nested_counters_safe(counters, "shared", "hits", 1)

        threads = []
        for tid in range(num_threads):
            t = threading.Thread(target=worker, args=(tid,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Each node should have its count
        for tid in range(num_threads):
            assert counters[f"node_{tid}"]["hits"] == increments_per_thread

        # Shared should have all counts
        expected_shared = num_threads * increments_per_thread
        assert counters["shared"]["hits"] == expected_shared


class TestEventRecording:
    """Test cache event recording integration."""

    def test_cache_get_records_hit(self, mock_caches):
        """cache_get should call record_event_fn on hit."""
        caches, _ = mock_caches
        caches["router"]["key"] = "value"

        events = []

        def record(node, action, reason):
            events.append((node, action, reason))

        cache_get("router", "key", record_event_fn=record)

        assert len(events) == 1
        assert events[0] == ("router", "hit", None)

    def test_cache_get_records_miss(self, mock_caches):
        """cache_get should call record_event_fn on miss."""
        _ = mock_caches

        events = []

        def record(node, action, reason):
            events.append((node, action, reason))

        cache_get("router", "nonexistent", record_event_fn=record)

        assert len(events) == 1
        assert events[0] == ("router", "miss", None)

    def test_cache_set_records_set(self, mock_caches):
        """cache_set should call record_event_fn."""
        _ = mock_caches

        events = []

        def record(node, action, reason):
            events.append((node, action, reason))

        cache_set("router", "key", "value", record_event_fn=record)

        assert len(events) == 1
        assert events[0] == ("router", "set", None)

    def test_cache_delete_records_evict(self, mock_caches):
        """cache_delete should call record_event_fn with reason."""
        caches, _ = mock_caches
        caches["router"]["key"] = "value"

        events = []

        def record(node, action, reason):
            events.append((node, action, reason))

        cache_delete("router", "key", reason="test_reason", record_event_fn=record)

        assert len(events) == 1
        assert events[0] == ("router", "evict", "test_reason")
