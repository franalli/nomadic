"""
Tests for tile data caching (L1 memory + L2 database).

Tests cover:
- Cache key generation and normalization
- L1 memory cache operations
- L2 database cache operations (requires test database)
- Thread safety
- Error handling
"""

import pytest

from app.services.tile_cache import (
    _tile_cache_key,
    clear_memory_cache,
    get_cache_stats,
    serialize_tile,
)


class TestTileCacheKeyGeneration:
    """Tests for cache key generation."""

    def test_basic_key(self):
        """Test basic cache key format."""
        key = _tile_cache_key("mock", "hotel", "Bali", "2025-03-01", "2025-03-14")
        assert key == "tile::v2::mock::hotel::bali::2025-03-01::2025-03-14"

    def test_normalized_destination(self):
        """Test destination normalization (lowercase, stripped)."""
        key1 = _tile_cache_key("mock", "hotel", "  BALI  ", "2025-03-01", "2025-03-14")
        key2 = _tile_cache_key("mock", "hotel", "bali", "2025-03-01", "2025-03-14")
        assert key1 == key2

    def test_different_providers_different_keys(self):
        """Test that different providers produce different keys."""
        key_mock = _tile_cache_key("mock", "hotel", "Bali", "2025-03-01", "2025-03-14")
        key_curated = _tile_cache_key("curated", "hotel", "Bali", "2025-03-01", "2025-03-14")
        assert key_mock != key_curated

    def test_different_types_different_keys(self):
        """Test that different tile types produce different keys."""
        key_hotel = _tile_cache_key("mock", "hotel", "Bali", "2025-03-01", "2025-03-14")
        key_activity = _tile_cache_key("mock", "activity", "Bali", "2025-03-01", "2025-03-14")
        assert key_hotel != key_activity

    def test_different_dates_different_keys(self):
        """Test that different dates produce different keys."""
        key1 = _tile_cache_key("mock", "hotel", "Bali", "2025-03-01", "2025-03-14")
        key2 = _tile_cache_key("mock", "hotel", "Bali", "2025-03-15", "2025-03-28")
        assert key1 != key2

    def test_empty_destination_fallback(self):
        """Test fallback for empty/None destination."""
        key = _tile_cache_key("mock", "hotel", "", "2025-03-01", "2025-03-14")
        assert "unknown" in key


class TestSerializeTile:
    """Tests for tile serialization helper."""

    def test_dict_passthrough(self):
        """Test that dicts pass through unchanged."""
        tile = {"id": "123", "type": "hotel", "title": "Test Hotel"}
        result = serialize_tile(tile)
        assert result == tile

    def test_object_with_model_dump(self):
        """Test serialization of Pydantic-like objects."""

        class FakeTile:
            def model_dump(self):
                return {"id": "123", "type": "hotel"}

        tile = FakeTile()
        result = serialize_tile(tile)
        assert result == {"id": "123", "type": "hotel"}

    def test_object_with_dict(self):
        """Test serialization of plain objects."""

        class FakeTile:
            def __init__(self):
                self.id = "123"
                self.type = "hotel"

        tile = FakeTile()
        result = serialize_tile(tile)
        assert result["id"] == "123"
        assert result["type"] == "hotel"


class TestL1MemoryCache:
    """Tests for L1 memory cache operations."""

    def setup_method(self):
        """Clear cache before each test."""
        clear_memory_cache()

    def test_stats_have_expected_fields(self):
        """Test that stats contain expected counter fields."""
        stats = get_cache_stats()
        assert "l1_hits" in stats
        assert "l1_misses" in stats
        assert "writes" in stats
        assert "l1_size" in stats
        assert "l1_maxsize" in stats

    def test_clear_returns_count(self):
        """Test that clear returns the count of cleared entries."""
        # Note: We can't easily populate the cache without async,
        # but we can test that clear works on empty cache
        count = clear_memory_cache()
        assert count >= 0

    def test_stats_contain_config(self):
        """Test that stats include configuration values."""
        stats = get_cache_stats()
        assert "l1_size" in stats
        assert "l1_maxsize" in stats
        assert "l1_ttl_seconds" in stats
        assert stats["l1_maxsize"] == 256
        assert stats["l1_ttl_seconds"] == 86400  # 24 hours


class TestThreadSafety:
    """Tests for thread safety (basic sanity checks)."""

    def test_concurrent_stats_access(self):
        """Test that stats can be accessed concurrently without error."""
        import threading

        errors = []

        def access_stats():
            try:
                for _ in range(100):
                    get_cache_stats()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=access_stats) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"

    def test_concurrent_clear(self):
        """Test that clear can be called concurrently without error."""
        import threading

        errors = []

        def clear_cache():
            try:
                for _ in range(100):
                    clear_memory_cache()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=clear_cache) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"


# =============================================================================
# Database-dependent tests (require test database)
# =============================================================================


@pytest.mark.slow
@pytest.mark.asyncio
class TestL2DatabaseCache:
    """Tests for L2 database cache operations."""

    @pytest.fixture
    async def async_db_session(self):
        """Create async database session for testing.

        Resets the cached engine/factory so each test gets a fresh
        connection bound to the current event loop.
        """
        from sqlalchemy import text

        import app.db as db_mod

        db_mod._async_engine = None
        db_mod._async_session_factory = None
        factory = db_mod._get_async_session_factory()
        async with factory() as session:
            try:
                await session.execute(text("SELECT 1"))
            except Exception as exc:  # pragma: no cover - environment-dependent
                pytest.skip(f"L2 DB cache tests require reachable PostgreSQL: {exc}")
            yield session
        await db_mod._async_engine.dispose()
        db_mod._async_engine = None
        db_mod._async_session_factory = None

    @pytest.fixture(autouse=True)
    def setup(self):
        """Clear memory cache before each test."""
        clear_memory_cache()

    async def test_miss_write_hit_flow(self, async_db_session):
        """Test full cache miss → write → hit flow."""
        from sqlalchemy import delete

        from app.db_models import ResponseCache
        from app.services.tile_cache import get_cached_tiles, set_cached_tiles

        # Clean up stale test data from previous runs
        cache_key = _tile_cache_key("mock", "hotel", "TestCity", "2025-03-01", "2025-03-14")
        await async_db_session.execute(
            delete(ResponseCache).where(ResponseCache.cache_key == cache_key)
        )
        await async_db_session.commit()
        clear_memory_cache()

        # Miss
        result1 = await get_cached_tiles(
            async_db_session, "mock", "hotel", "TestCity", "2025-03-01", "2025-03-14"
        )
        assert result1 is None

        stats = get_cache_stats()
        assert stats["l1_misses"] >= 1

        # Write
        tiles = [
            {"id": "test-1", "type": "hotel", "title": "Test Hotel 1"},
            {"id": "test-2", "type": "hotel", "title": "Test Hotel 2"},
        ]
        await set_cached_tiles(
            async_db_session,
            "mock",
            "hotel",
            "TestCity",
            "2025-03-01",
            "2025-03-14",
            tiles,
        )

        stats = get_cache_stats()
        assert stats["writes"] >= 1

        # Hit (L1)
        result2 = await get_cached_tiles(
            async_db_session, "mock", "hotel", "TestCity", "2025-03-01", "2025-03-14"
        )
        assert result2 is not None
        assert len(result2) == 2
        assert result2[0]["id"] == "test-1"

        # Cleanup
        await async_db_session.execute(
            delete(ResponseCache).where(ResponseCache.cache_key == cache_key)
        )
        await async_db_session.commit()
        clear_memory_cache()

    async def test_l2_hit_after_l1_clear(self, async_db_session):
        """Test that L2 provides data after L1 is cleared."""
        from sqlalchemy import delete

        from app.db_models import ResponseCache
        from app.services.tile_cache import get_cached_tiles, set_cached_tiles

        # Clean up stale test data
        cache_key = _tile_cache_key("mock", "hotel", "PersistCity", "2025-04-01", "2025-04-14")
        await async_db_session.execute(
            delete(ResponseCache).where(ResponseCache.cache_key == cache_key)
        )
        await async_db_session.commit()
        clear_memory_cache()

        # Write to both L1 and L2
        tiles = [{"id": "persist-test", "type": "hotel"}]
        await set_cached_tiles(
            async_db_session,
            "mock",
            "hotel",
            "PersistCity",
            "2025-04-01",
            "2025-04-14",
            tiles,
        )

        # Clear L1
        clear_memory_cache()

        # Should hit L2
        result = await get_cached_tiles(
            async_db_session, "mock", "hotel", "PersistCity", "2025-04-01", "2025-04-14"
        )
        assert result is not None
        assert result[0]["id"] == "persist-test"

        stats = get_cache_stats()
        assert stats["l2_hits"] >= 1

        # Cleanup
        await async_db_session.execute(
            delete(ResponseCache).where(ResponseCache.cache_key == cache_key)
        )
        await async_db_session.commit()
        clear_memory_cache()
