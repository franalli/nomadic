"""
Thread-safe two-tier caching for Tile data (hotels, activities).

L1: In-memory TTLCache (24h TTL, 256 entries) - hot path
L2: PostgreSQL response_cache (24h TTL) - warm persistence across restarts

Cache key format: tiles:{provider}:{type}:{dest}:{start_date}:{end_date}

Usage:
    from app.services.tile_cache import (
        get_cached_tiles,
        set_cached_tiles,
        serialize_tile,
    )

    # In logistics_node.py
    cached = await get_cached_tiles(db, "amadeus", "hotel", dest, start, end)
    if cached:
        return cached

    # After provider call
    tiles_dicts = [serialize_tile(t) for t in tiles]
    await set_cached_tiles(db, "amadeus", "hotel", dest, start, end, tiles_dicts)
"""

import logging
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import List, Optional

from cachetools import TTLCache
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================
L1_TTL_SECONDS = 86400  # 24 hours
L1_MAX_SIZE = 256
L2_TTL_HOURS = 24

# =============================================================================
# L1: Thread-safe in-memory cache
# =============================================================================
_cache_lock = RLock()
_stats_lock = RLock()
_tile_cache: TTLCache = TTLCache(maxsize=L1_MAX_SIZE, ttl=L1_TTL_SECONDS)

# Hit/miss counters for observability
_cache_stats = {
    "l1_hits": 0,
    "l1_misses": 0,
    "l2_hits": 0,
    "l2_misses": 0,
    "writes": 0,
}


def _increment_stat(key: str) -> None:
    """Thread-safe stats increment."""
    with _stats_lock:
        _cache_stats[key] += 1


def _cache_get(key: str) -> Optional[List[dict]]:
    """Thread-safe L1 cache get."""
    with _cache_lock:
        return _tile_cache.get(key)


def _cache_set(key: str, value: List[dict]) -> None:
    """Thread-safe L1 cache set."""
    with _cache_lock:
        _tile_cache[key] = value


def _tile_cache_key(
    provider: str,
    tile_type: str,
    destination: str,
    start_date: str,
    end_date: str,
) -> str:
    """
    Generate stable cache key: tiles:{provider}:{type}:{dest}:{dates}

    Key components:
    - provider: "amadeus", "curated", "mock"
    - tile_type: "hotel", "activity"
    - destination: normalized lowercase, stripped
    - start_date, end_date: YYYY-MM-DD format

    Example: "tiles:amadeus:hotel:bali:2025-02-01:2025-02-14"
    """
    dest_normalized = destination.lower().strip() if destination else "unknown"
    return f"tiles:{provider}:{tile_type}:{dest_normalized}:{start_date}:{end_date}"


# =============================================================================
# Serialization Helper
# =============================================================================


def serialize_tile(tile) -> dict:
    """
    Convert Tile object to dict for caching.

    Centralized here to ensure consistent serialization across all callers.
    Handles both Pydantic models and plain dicts.
    """
    if isinstance(tile, dict):
        return tile
    if hasattr(tile, "model_dump"):
        return tile.model_dump()
    if hasattr(tile, "__dict__"):
        return tile.__dict__
    # Fallback - try to convert to dict
    return dict(tile)


# =============================================================================
# Cache Operations (Async)
# =============================================================================


async def get_cached_tiles(
    db: AsyncSession,
    provider: str,
    tile_type: str,
    destination: str,
    start_date: str,
    end_date: str,
) -> Optional[List[dict]]:
    """
    Get cached tiles: L1 → L2 fallback with error handling.

    Args:
        db: Async database session
        provider: Provider name ("amadeus", "curated", "mock")
        tile_type: Tile type ("hotel", "activity")
        destination: Trip destination
        start_date: Trip start date (YYYY-MM-DD)
        end_date: Trip end date (YYYY-MM-DD)

    Returns:
        List of tile dicts or None if not found
    """
    # Import here to avoid circular imports
    from app.db_models import ResponseCache

    cache_key = _tile_cache_key(provider, tile_type, destination, start_date, end_date)

    # L1: Memory check
    cached = _cache_get(cache_key)
    if cached is not None:
        _increment_stat("l1_hits")
        logger.debug(f"[TILE_CACHE] L1 HIT: {cache_key}")
        return cached

    _increment_stat("l1_misses")

    # L2: Database check with error handling
    try:
        result = await db.execute(
            select(ResponseCache)
            .where(ResponseCache.cache_key == cache_key)
            .where(ResponseCache.cache_type == "tiles")
            .where(ResponseCache.expires_at > datetime.now(UTC))
        )
        row = result.scalar_one_or_none()

        if row:
            _increment_stat("l2_hits")
            logger.info(f"[TILE_CACHE] L2 HIT: {cache_key}")

            # Promote to L1
            _cache_set(cache_key, row.response_json)

            # Update hit counter atomically to prevent lost updates
            stmt = (
                update(ResponseCache)
                .where(ResponseCache.cache_key == cache_key)
                .values(
                    hit_count=ResponseCache.hit_count + 1,
                    last_hit_at=datetime.now(UTC),
                )
            )
            await db.execute(stmt)
            await db.commit()

            return row.response_json

        _increment_stat("l2_misses")
        logger.debug(f"[TILE_CACHE] L2 MISS: {cache_key}")
        return None

    except OperationalError as e:
        # Database connection failed - degrade gracefully
        logger.warning(f"[TILE_CACHE] L2 unavailable (DB error): {e}")
        return None
    except Exception as e:
        logger.error(f"[TILE_CACHE] Unexpected error: {e}")
        return None


async def set_cached_tiles(
    db: AsyncSession,
    provider: str,
    tile_type: str,
    destination: str,
    start_date: str,
    end_date: str,
    tiles: List[dict],
) -> None:
    """
    Cache tiles to both L1 and L2 with error handling.

    Args:
        db: Async database session
        provider: Provider name
        tile_type: Tile type
        destination: Trip destination
        start_date: Trip start date
        end_date: Trip end date
        tiles: List of tile dicts (already serialized)
    """
    # Import here to avoid circular imports
    from app.db_models import ResponseCache

    cache_key = _tile_cache_key(provider, tile_type, destination, start_date, end_date)
    expires_at = datetime.now(UTC) + timedelta(hours=L2_TTL_HOURS)

    # L1: Always write to memory (fast path)
    _cache_set(cache_key, tiles)

    # L2: Best-effort database write
    try:
        stmt = pg_insert(ResponseCache).values(
            cache_key=cache_key,
            cache_type="tiles",
            response_json=tiles,
            created_at=datetime.now(UTC),
            expires_at=expires_at,
            hit_count=0,
            last_hit_at=None,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["cache_key"],
            set_={
                "response_json": tiles,
                "created_at": datetime.now(UTC),
                "expires_at": expires_at,
            },
        )
        await db.execute(stmt)
        await db.commit()

        _increment_stat("writes")
        logger.info(f"[TILE_CACHE] Wrote: {cache_key} ({len(tiles)} tiles)")

    except OperationalError as e:
        # Database unavailable - L1 cache still works
        logger.warning(f"[TILE_CACHE] L2 write failed (DB error): {e}")
    except Exception as e:
        logger.error(f"[TILE_CACHE] Write error: {e}")
        await db.rollback()


# =============================================================================
# Admin Functions
# =============================================================================


def get_cache_stats() -> dict:
    """Return cache statistics for observability."""
    with _cache_lock:
        l1_size = len(_tile_cache)
    with _stats_lock:
        stats_copy = dict(_cache_stats)
    return {
        **stats_copy,
        "l1_size": l1_size,
        "l1_maxsize": L1_MAX_SIZE,
        "l1_ttl_seconds": L1_TTL_SECONDS,
        "l2_ttl_hours": L2_TTL_HOURS,
    }


def clear_memory_cache() -> int:
    """Clear L1 cache. Returns count cleared."""
    with _cache_lock:
        count = len(_tile_cache)
        _tile_cache.clear()
    logger.info(f"[TILE_CACHE] Cleared L1 ({count} entries)")
    return count


def reset_stats() -> None:
    """Reset cache statistics."""
    global _cache_stats
    with _stats_lock:
        _cache_stats = {
            "l1_hits": 0,
            "l1_misses": 0,
            "l2_hits": 0,
            "l2_misses": 0,
            "writes": 0,
        }


async def cleanup_expired(db: AsyncSession) -> int:
    """Remove expired L2 entries. Run on shutdown or daily."""
    from sqlalchemy import delete

    from app.db_models import ResponseCache

    try:
        result = await db.execute(
            delete(ResponseCache)
            .where(ResponseCache.cache_type == "tiles")
            .where(ResponseCache.expires_at < datetime.now(UTC))
        )
        await db.commit()
        deleted = result.rowcount
        if deleted:
            logger.info(f"[TILE_CACHE] Cleaned up {deleted} expired entries")
        return deleted
    except Exception as e:
        logger.warning(f"[TILE_CACHE] Cleanup failed: {e}")
        await db.rollback()
        return 0
