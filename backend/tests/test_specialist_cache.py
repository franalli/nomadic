"""
Tests for specialist_cache.py - Thread-safe L1+L2 caching for LLM outputs.

Run with: pytest tests/test_specialist_cache.py -v
"""

from threading import Thread

import pytest


class TestCacheKeyGeneration:
    """Test cache key generation logic."""

    def test_basic_key(self):
        """Test cache key format with month + duration bucket + day_pref.

        Format: specialist::v2::{topic}::{dest}::{month}::{bucket}::{skill}::{dpref}::{phash}.
        """
        from app.services.specialist_cache import _specialist_cache_key

        key = _specialist_cache_key("diving", "Bali", "2025-03-15", "2025-03-20")
        # 6 days = "week" bucket
        assert key.startswith("specialist::v2::diving::bali::2025-03::week::any::dpany::")
        assert len(key.split("::")) == 9  # 9 segments

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

    def test_same_bucket_shares_cache(self):
        """Dates within same month and duration bucket share cache key."""
        from app.services.specialist_cache import _specialist_cache_key

        key1 = _specialist_cache_key("diving", "Bali", "2025-03-15", "2025-03-17")
        key2 = _specialist_cache_key("diving", "Bali", "2025-03-18", "2025-03-20")
        # Both are weekend (3 days), same month -> same key
        assert key1 == key2

    def test_different_buckets_produce_different_keys(self):
        """Different duration buckets produce different cache keys."""
        from app.services.specialist_cache import _specialist_cache_key

        short_key = _specialist_cache_key(
            "diving",
            "Bali",
            "2025-03-15",
            "2025-03-17",
        )  # 3d weekend
        long_key = _specialist_cache_key(
            "diving",
            "Bali",
            "2025-03-15",
            "2025-03-25",
        )  # 11d extended
        assert short_key != long_key
        assert "weekend" in short_key
        assert "extended" in long_key

    def test_duration_buckets(self):
        """Test duration bucket boundaries."""
        from app.services.specialist_cache import _duration_bucket

        assert _duration_bucket("2025-03-01", "2025-03-01") == "weekend"  # 1 day
        assert _duration_bucket("2025-03-01", "2025-03-03") == "weekend"  # 3 days
        assert _duration_bucket("2025-03-01", "2025-03-04") == "short"  # 4 days
        assert _duration_bucket("2025-03-01", "2025-03-05") == "short"  # 5 days
        assert _duration_bucket("2025-03-01", "2025-03-06") == "week"  # 6 days
        assert _duration_bucket("2025-03-01", "2025-03-08") == "week"  # 8 days
        assert _duration_bucket("2025-03-01", "2025-03-09") == "extended"  # 9 days
        assert _duration_bucket("2025-03-01", "2025-03-11") == "extended"  # 11 days
        assert _duration_bucket("2025-03-01", "2025-03-12") == "twoweek"  # 12 days
        assert _duration_bucket("2025-03-01", "2025-03-15") == "twoweek"  # 15 days
        assert _duration_bucket("2025-03-01", "2025-03-16") == "long"  # 16 days
        assert _duration_bucket(None, None) == "unknown"
        assert _duration_bucket("2025-03-01", None) == "unknown"

    def test_missing_dates(self):
        """Test graceful handling of missing dates."""
        from app.services.specialist_cache import _specialist_cache_key

        key = _specialist_cache_key("diving", "Bali", None, None)
        assert "unknown" in key

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
        from app.services.specialist_cache import get_cache_stats

        stats = get_cache_stats()

        assert "l1_hits" in stats
        assert "l1_misses" in stats
        assert "l2_hits" in stats
        assert "l2_misses" in stats
        assert "writes" in stats
        assert "l1_size" in stats
        assert "l1_maxsize" in stats
        assert stats["l1_maxsize"] == 128


# =============================================================================
# Integration Tests (require database)
# =============================================================================


@pytest.mark.asyncio
class TestL2DatabaseCache:
    """Integration tests for L2 PostgreSQL cache."""

    @pytest.fixture
    async def async_db_session(self):
        """Create async database session for testing.

        Resets the cached engine/factory so each test gets a fresh
        connection bound to the current event loop.
        """
        import app.db as db_mod

        db_mod._async_engine = None
        db_mod._async_session_factory = None
        factory = db_mod._get_async_session_factory()
        async with factory() as session:
            yield session
        await db_mod._async_engine.dispose()
        db_mod._async_engine = None
        db_mod._async_session_factory = None

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
            _specialist_cache_key,
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
        test_cache_key = _specialist_cache_key(
            test_topic,
            test_dest,
            test_start,
            test_end,
        )

        # Clean up any existing test data
        await async_db_session.execute(
            delete(ResponseCache).where(ResponseCache.cache_key == test_cache_key)
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
            delete(ResponseCache).where(ResponseCache.cache_key == test_cache_key)
        )
        await async_db_session.commit()
        clear_memory_cache()


# =============================================================================
# Parallel Cache Invalidation Tests
# =============================================================================


class TestParallelCacheInvalidation:
    """
    Test in-memory parallel_llm_results cache invalidation on context changes.

    When destination or month changes, the parallel_llm_results cache must be
    invalidated to prevent stale specialist content (e.g., Bali dive sites
    appearing for a New York trip).

    These tests simulate the invalidation logic from vertical_specialist.py.
    """

    def test_parallel_cache_invalidated_on_destination_change(self):
        """Changing destination should invalidate parallel_llm_results."""
        # Simulate state with cached Bali data
        metadata = {
            "parallel_llm_results": {"diving": {"cached": "bali_data"}},
            "_last_specialist_key": "bali:2026-02",
            "current_specialist_topic": "diving",
        }
        trip_plan_destination = "New York"
        trip_plan_start_date = "2026-02-01"

        # Simulate the invalidation check from vertical_specialist.py
        cached_key = metadata.get("_last_specialist_key", "")
        current_dest = (trip_plan_destination or "").lower().strip()
        current_month = trip_plan_start_date[:7] if trip_plan_start_date else "no-dates"
        current_key = f"{current_dest}:{current_month}"

        assert cached_key == "bali:2026-02"
        assert current_key == "new york:2026-02"
        assert cached_key != current_key, "Cache key should change when destination changes"

        # Verify cache would be cleared
        if cached_key != current_key:
            metadata.pop("parallel_llm_results", None)
        assert "parallel_llm_results" not in metadata, "Cache should be cleared"

    def test_parallel_cache_invalidated_on_month_change(self):
        """Changing month should invalidate parallel_llm_results (seasonal content)."""
        # Simulate state with cached February data
        metadata = {
            "parallel_llm_results": {"diving": {"cached": "feb_rainy_season_data"}},
            "_last_specialist_key": "bali:2026-02",
        }
        trip_plan_destination = "Bali"
        trip_plan_start_date = "2026-08-01"  # Changed to August (dry season)

        # Simulate the invalidation check
        cached_key = metadata.get("_last_specialist_key", "")
        current_dest = (trip_plan_destination or "").lower().strip()
        current_month = trip_plan_start_date[:7] if trip_plan_start_date else "no-dates"
        current_key = f"{current_dest}:{current_month}"

        assert cached_key == "bali:2026-02"
        assert current_key == "bali:2026-08"
        assert cached_key != current_key, "Cache key should change when month changes"

        # Verify cache would be cleared
        if cached_key != current_key:
            metadata.pop("parallel_llm_results", None)
        assert "parallel_llm_results" not in metadata, "Cache should be cleared"

    def test_parallel_cache_preserved_when_unchanged(self):
        """Same destination+month should NOT invalidate cache."""
        # Simulate state with cached data
        metadata = {
            "parallel_llm_results": {"diving": {"cached": "bali_data"}},
            "_last_specialist_key": "bali:2026-02",
        }
        trip_plan_destination = "Bali"
        trip_plan_start_date = "2026-02-15"  # Same month, different day

        # Simulate the invalidation check
        cached_key = metadata.get("_last_specialist_key", "")
        current_dest = (trip_plan_destination or "").lower().strip()
        current_month = trip_plan_start_date[:7] if trip_plan_start_date else "no-dates"
        current_key = f"{current_dest}:{current_month}"

        assert cached_key == current_key, "Cache key should be unchanged"

        # Verify cache is NOT cleared
        assert "parallel_llm_results" in metadata, "Cache should be preserved"
        assert metadata["parallel_llm_results"]["diving"]["cached"] == "bali_data"

    def test_cache_invalidation_with_no_dates(self):
        """Cache should use 'no-dates' fallback when start_date is missing."""
        metadata = {
            "parallel_llm_results": {"diving": {"cached": "old_data"}},
            "_last_specialist_key": "bali:no-dates",
        }
        trip_plan_destination = "Bali"
        trip_plan_start_date = "2026-02-01"  # Now has dates

        # Simulate the invalidation check
        cached_key = metadata.get("_last_specialist_key", "")
        current_dest = (trip_plan_destination or "").lower().strip()
        current_month = trip_plan_start_date[:7] if trip_plan_start_date else "no-dates"
        current_key = f"{current_dest}:{current_month}"

        assert cached_key == "bali:no-dates"
        assert current_key == "bali:2026-02"
        assert cached_key != current_key, "Adding dates should trigger invalidation"

    def test_cache_key_is_case_insensitive(self):
        """Cache key destination should be case-insensitive."""
        metadata = {
            "parallel_llm_results": {"diving": {"cached": "data"}},
            "_last_specialist_key": "bali:2026-02",
        }

        # Same destination, different case
        trip_plan_destination = "BALI"
        trip_plan_start_date = "2026-02-01"

        cached_key = metadata.get("_last_specialist_key", "")
        current_dest = (trip_plan_destination or "").lower().strip()
        current_month = trip_plan_start_date[:7] if trip_plan_start_date else "no-dates"
        current_key = f"{current_dest}:{current_month}"

        assert cached_key == current_key, "Case should not affect cache key match"
        assert "parallel_llm_results" in metadata, "Cache should be preserved"
