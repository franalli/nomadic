"""
Thread-safe two-tier caching for Tile data (hotels, activities).

L1: In-memory TTLCache (24h TTL, 256 entries) - hot path
L2: PostgreSQL response_cache (72h TTL, env-configurable) - warm persistence across restarts

Cache key format: tile::v2::{provider}::{type}::{dest}::{start_date}::{end_date}[::{variant}]

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
from typing import List, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.planner.hashing import make_cache_key
from app.services.cache_core import MemoryCache, l2_upsert

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================
L1_TTL_SECONDS = 86400  # 24 hours
L1_MAX_SIZE = 256
L2_TTL_HOURS = settings.tile_cache_ttl_hours  # default 72h — env: TILE_CACHE_TTL_HOURS

# =============================================================================
# L1: Thread-safe in-memory cache
# =============================================================================
_mem = MemoryCache(maxsize=L1_MAX_SIZE, ttl=L1_TTL_SECONDS)


def _tile_cache_key(
    provider: str,
    tile_type: str,
    destination: str,
    start_date: str,
    end_date: str,
    variant: str = "",
) -> str:
    """
    Generate stable cache key:
    tile::v2::{provider}::{type}::{dest}::{start_date}::{end_date}[::{variant}]

    Key components:
    - provider: "google_places", "amadeus", "mock"
    - tile_type: "hotel", "activity"
    - destination: normalized lowercase, stripped
    - start_date, end_date: YYYY-MM-DD format
    - variant: optional differentiator (e.g. "stars3" for min_stars=3 hotel queries)

    Example: "tile::v2::google_places::hotel::bali::2025-02-01::2025-02-14::stars3"
    """
    dest_normalized = destination.lower().strip() if destination else "unknown"
    parts = ["tile", "v2", provider, tile_type, dest_normalized, start_date, end_date]
    if variant:
        parts.append(variant)
    return make_cache_key(*parts)


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
    variant: str = "",
) -> Optional[List[dict]]:
    """
    Get cached tiles: L1 → L2 fallback with error handling.

    Args:
        db: Async database session
        provider: Provider name ("google_places", "amadeus", "mock")
        tile_type: Tile type ("hotel", "activity")
        destination: Trip destination
        start_date: Trip start date (YYYY-MM-DD)
        end_date: Trip end date (YYYY-MM-DD)
        variant: Optional cache variant (e.g. "stars3" for min_stars=3 hotel queries)

    Returns:
        List of tile dicts or None if not found
    """
    # Import here to avoid circular imports
    from app.db_models import ResponseCache

    cache_key = _tile_cache_key(provider, tile_type, destination, start_date, end_date, variant)

    # L1: Memory check
    cached = _mem.get(cache_key)
    if cached is not None:
        _mem.increment_stat("l1_hits")
        logger.debug(f"[TILE_CACHE] L1 HIT: {cache_key}")
        return cached

    _mem.increment_stat("l1_misses")

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
            _mem.increment_stat("l2_hits")
            logger.info(f"[TILE_CACHE] L2 HIT: {cache_key}")

            # Promote to L1
            _mem.set(cache_key, row.response_json)

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

        _mem.increment_stat("l2_misses")
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
    variant: str = "",
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
        variant: Optional cache variant (e.g. "stars3" for min_stars=3 hotel queries)
    """
    cache_key = _tile_cache_key(provider, tile_type, destination, start_date, end_date, variant)

    # L1: Always write to memory (fast path)
    _mem.set(cache_key, tiles)

    # L2: Best-effort database write
    try:
        await l2_upsert(
            db,
            cache_key=cache_key,
            cache_type="tiles",
            response_json=tiles,
            ttl=timedelta(hours=L2_TTL_HOURS),
        )
        _mem.increment_stat("writes")
        logger.info(f"[TILE_CACHE] Wrote: {cache_key} ({len(tiles)} tiles)")
    except OperationalError as e:
        logger.warning(f"[TILE_CACHE] L2 write failed (DB error): {e}")
        await db.rollback()
    except Exception as e:
        logger.error(f"[TILE_CACHE] Write error: {e}")
        await db.rollback()


# =============================================================================
# Admin Functions
# =============================================================================


def get_cache_stats() -> dict:
    """Return cache statistics for observability."""
    return {
        **_mem.get_stats(),
        "l1_size": len(_mem),
        "l1_maxsize": L1_MAX_SIZE,
        "l1_ttl_seconds": L1_TTL_SECONDS,
        "l2_ttl_hours": L2_TTL_HOURS,
    }


def clear_memory_cache() -> int:
    """Clear L1 cache. Returns count cleared."""
    count = _mem.clear()
    logger.info(f"[TILE_CACHE] Cleared L1 ({count} entries)")
    return count


async def clear_db_cache(db: AsyncSession) -> int:
    """Clear all L2 tile cache entries. Returns count deleted."""
    from app.db_models import ResponseCache

    try:
        result = await db.execute(delete(ResponseCache).where(ResponseCache.cache_type == "tiles"))
        await db.commit()
        deleted = result.rowcount
        logger.info(f"[TILE_CACHE] Cleared L2: {deleted} entries")
        return deleted
    except Exception as e:
        logger.warning(f"[TILE_CACHE] Clear L2 failed: {e}")
        await db.rollback()
        return 0
