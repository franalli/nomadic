"""
Tests for specialist_cache.py - Thread-safe L1+L2 caching for LLM outputs.

Run with: pytest tests/test_specialist_cache.py -v
"""

from threading import Thread

import pytest


class TestCacheKeyGeneration:
    """Test cache key generation logic."""

    def test_basic_key(self):
        """Test standard cache key format."""
        from app.services.specialist_cache import _specialist_cache_key

        key = _specialist_cache_key("diving", "Bali", "2025-03-15", "2025-03-20")
        assert key == "specialist:diving:bali:2025-03:6"

    def test_normalized_destination(self):
        """Test destination is normalized (lowercase, trimmed)."""
        from app.services.specialist_cache import _specialist_cache_key

        key1 = _specialist_cache_key("diving", "  BALI  ", "2025-03-15", "2025-03-20")
        key2 = _specialist_cache_key("diving", "bali", "2025-03-15", "2025-03-20")
        assert key1 == key2

    def test_month_extraction(self):
        """Test month is extracted from start_date."""
        from app.services.specialist_cache import _specialist_cache_key

        key = _specialist_cache_key("hiking", "Alps", "2025-07-01", "2025-07-10")
        assert "2025-07" in key

    def test_duration_calculation(self):
        """Test duration is calculated correctly."""
        from app.services.specialist_cache import _specialist_cache_key

        # 3-day trip (inclusive: 15, 16, 17)
        key3 = _specialist_cache_key("diving", "Bali", "2025-03-15", "2025-03-17")
        assert key3.endswith(":3")

        # 7-day trip
        key7 = _specialist_cache_key("diving", "Bali", "2025-03-15", "2025-03-21")
        assert key7.endswith(":7")

        # 14-day trip
        key14 = _specialist_cache_key("diving", "Bali", "2025-02-01", "2025-02-14")
        assert key14.endswith(":14")

    def test_missing_dates(self):
        """Test graceful handling of missing dates."""
        from app.services.specialist_cache import _specialist_cache_key

        key = _specialist_cache_key("diving", "Bali", None, None)
        assert "unknown" in key
        assert ":5" in key  # default duration

    def test_different_topics_produce_different_keys(self):
        """Test different topics produce different cache keys."""
        from app.services.specialist_cache import _specialist_cache_key

        diving_key = _specialist_cache_key("diving", "Bali", "2025-03-15", "2025-03-20")
        hiking_key = _specialist_cache_key("hiking", "Bali", "2025-03-15", "2025-03-20")

        assert diving_key != hiking_key
        assert "diving" in diving_key
        assert "hiking" in hiking_key


class TestL1MemoryCache:
    """Test thread-safe L1 memory cache operations."""

    def test_cache_get_set(self):
        """Test basic get/set operations."""
        from app.services.specialist_cache import (
            _cache_get,
            _cache_set,
            clear_memory_cache,
        )

        clear_memory_cache()

        # Initial state: empty
        assert _cache_get("test_key") is None

        # Set value
        _cache_set("test_key", {"value": 42})

        # Get value
        result = _cache_get("test_key")
        assert result is not None
        assert result["value"] == 42

        clear_memory_cache()

    def test_clear_memory_cache(self):
        """Test clearing L1 memory cache."""
        from app.services.specialist_cache import (
            _cache_get,
            _cache_set,
            clear_memory_cache,
        )

        _cache_set("key1", {"a": 1})
        _cache_set("key2", {"b": 2})

        count = clear_memory_cache()
        assert count >= 2

        assert _cache_get("key1") is None
        assert _cache_get("key2") is None


class TestThreadSafety:
    """Test thread safety of L1 cache operations."""

    def test_concurrent_writes(self):
        """Verify no race conditions with concurrent writes."""
        from app.services.specialist_cache import (
            _cache_get,
            _cache_set,
            clear_memory_cache,
        )

        clear_memory_cache()
        errors = []

        def writer(i: int):
            try:
                for _ in range(100):
                    _cache_set(f"key-{i}", {"value": i})
                    result = _cache_get(f"key-{i}")
                    if result is None or result.get("value") != i:
                        errors.append(f"Thread {i}: unexpected value {result}")
            except Exception as e:
                errors.append(f"Thread {i}: {e}")

        threads = [Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Race condition errors: {errors}"
        clear_memory_cache()

    def test_concurrent_reads_writes(self):
        """Test mixed read/write operations don't deadlock."""
        from app.services.specialist_cache import (
            _cache_get,
            _cache_set,
            clear_memory_cache,
        )

        clear_memory_cache()
        _cache_set("shared_key", {"counter": 0})
        errors = []

        def reader():
            try:
                for _ in range(50):
                    _cache_get("shared_key")
            except Exception as e:
                errors.append(f"Reader: {e}")

        def writer(i: int):
            try:
                for j in range(50):
                    _cache_set("shared_key", {"counter": i * 50 + j})
            except Exception as e:
                errors.append(f"Writer {i}: {e}")

        readers = [Thread(target=reader) for _ in range(5)]
        writers = [Thread(target=writer, args=(i,)) for i in range(5)]

        for t in readers + writers:
            t.start()
        for t in readers + writers:
            t.join()

        assert len(errors) == 0, f"Concurrent access errors: {errors}"
        clear_memory_cache()


class TestCacheStats:
    """Test cache statistics."""

    def test_get_cache_stats(self):
        """Test cache stats return expected fields."""
        from app.services.specialist_cache import get_cache_stats, reset_stats

        reset_stats()
        stats = get_cache_stats()

        assert "l1_hits" in stats
        assert "l1_misses" in stats
        assert "l2_hits" in stats
        assert "l2_misses" in stats
        assert "writes" in stats
        assert "l1_size" in stats
        assert "l1_maxsize" in stats
        assert stats["l1_maxsize"] == 128

    def test_reset_stats(self):
        """Test stats reset."""
        from app.services.specialist_cache import get_cache_stats, reset_stats

        reset_stats()
        stats = get_cache_stats()

        assert stats["l1_hits"] == 0
        assert stats["l1_misses"] == 0
        assert stats["l2_hits"] == 0
        assert stats["l2_misses"] == 0
        assert stats["writes"] == 0


# =============================================================================
# Integration Tests (require database)
# =============================================================================


@pytest.mark.asyncio
class TestL2DatabaseCache:
    """Integration tests for L2 PostgreSQL cache."""

    @pytest.fixture
    async def async_db_session(self):
        """Create async database session for testing."""
        from app.db import _get_async_session_factory

        factory = _get_async_session_factory()
        async with factory() as session:
            yield session

    async def test_cache_miss_returns_none(self, async_db_session):
        """Test cache miss returns None."""
        from app.services.specialist_cache import (
            clear_memory_cache,
            get_cached_specialist_output,
        )

        clear_memory_cache()

        result = await get_cached_specialist_output(
            db=async_db_session,
            topic="test_topic",
            destination="test_destination",
            start_date="2099-01-01",  # Future date unlikely to be cached
            end_date="2099-01-07",
        )

        assert result is None

    async def test_full_cache_flow(self, async_db_session):
        """Test miss → write → hit flow."""
        from sqlalchemy import delete

        from app.db_models import ResponseCache
        from app.services.specialist_cache import (
            clear_memory_cache,
            get_cached_specialist_output,
            set_cached_specialist_output,
        )

        clear_memory_cache()

        # Use unique test key
        test_topic = "test_diving"
        test_dest = "test_bali"
        test_start = "2099-12-01"
        test_end = "2099-12-14"

        # Clean up any existing test data
        await async_db_session.execute(
            delete(ResponseCache).where(ResponseCache.cache_key.like(f"specialist:{test_topic}:%"))
        )
        await async_db_session.commit()

        # 1. Initial miss
        result1 = await get_cached_specialist_output(
            db=async_db_session,
            topic=test_topic,
            destination=test_dest,
            start_date=test_start,
            end_date=test_end,
        )
        assert result1 is None

        # 2. Write to cache
        test_output = {
            "feasibility_status": "feasible",
            "feasibility_reason": None,
            "activities": [
                {
                    "title": "Test Dive",
                    "description": "Test description",
                    "location": "Test location",
                    "duration_hours": 3.0,
                    "difficulty": "intermediate",
                }
            ],
            "constraints": [],
        }

        await set_cached_specialist_output(
            db=async_db_session,
            topic=test_topic,
            destination=test_dest,
            start_date=test_start,
            end_date=test_end,
            output=test_output,
        )

        # 3. Hit (L1 since we just wrote)
        result2 = await get_cached_specialist_output(
            db=async_db_session,
            topic=test_topic,
            destination=test_dest,
            start_date=test_start,
            end_date=test_end,
        )

        assert result2 is not None
        assert result2["feasibility_status"] == "feasible"
        assert len(result2["activities"]) == 1
        assert result2["activities"][0]["title"] == "Test Dive"

        # 4. Clear L1, should still hit L2
        clear_memory_cache()

        result3 = await get_cached_specialist_output(
            db=async_db_session,
            topic=test_topic,
            destination=test_dest,
            start_date=test_start,
            end_date=test_end,
        )

        assert result3 is not None
        assert result3["feasibility_status"] == "feasible"

        # Cleanup
        await async_db_session.execute(
            delete(ResponseCache).where(ResponseCache.cache_key.like(f"specialist:{test_topic}:%"))
        )
        await async_db_session.commit()
        clear_memory_cache()
