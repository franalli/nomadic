"""
Thread-safe two-tier caching for Vertical Specialist LLM outputs.

L1: In-memory TTLCache with RLock (1h TTL, 128 entries) - hot path
L2: PostgreSQL response_cache (7d TTL) - warm persistence across restarts

Cache key format:
specialist::v4::{topic}::{dest}::{iso_month}::m::{skill}::{dpref}::{phash}

Usage:
    from app.services.specialist_cache import (
        get_cached_specialist_output,
        set_cached_specialist_output,
    )

    # In vertical_specialist.py
    cached = await get_cached_specialist_output(
        db, topic, dest, start, end, skill_level=skill
    )
    if cached:
        return LLMSpecialistOutput.model_validate(cached)

    # After LLM call
    await set_cached_specialist_output(
        db, topic, dest, start, end, output.model_dump(), skill_level=skill
    )
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.planner.hashing import make_cache_key
from app.services.cache_core import MemoryCache, l2_upsert

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================
L1_TTL_SECONDS = 3600  # 1 hour
L1_MAX_SIZE = 128
# default 168h (7d); override with SPECIALIST_CACHE_TTL_HOURS env var
L2_TTL_HOURS = settings.specialist_cache_ttl_hours

# =============================================================================
# L1: Thread-safe in-memory cache
# =============================================================================
_mem = MemoryCache(maxsize=L1_MAX_SIZE, ttl=L1_TTL_SECONDS)

# Aliases for test compatibility
_cache_get = _mem.get
_cache_set = _mem.set


def _specialist_cache_key(
    topic: str,
    destination: str,
    start_date: Optional[str],
    end_date: Optional[str],
    skill_level: Optional[str] = None,
    day_pref: Optional[int] = None,
) -> str:
    """
    Generate stable cache key with ISO-month bucketing.

    Format:
    specialist::v4::{topic}::{dest}::{iso_month}::m::{skill}::{dpref}::{phash}

    Dates are coarsened to ISO month — specialist content is conceptually
    date-independent. Duration is dropped because d6 vs d7 produces
    unnecessary misses, and specialist plans don't vary by trip length.
    Date-anchored constraints (e.g., diving no-fly buffer) are re-anchored
    by the itinerary builder at schedule time.
    """
    from datetime import date as date_type

    from app.planner.specialist_registry import prompt_hash

    dest_normalized = destination.lower().strip() if destination else "unknown"
    # Coarsen dates to ISO month — a diving plan for Bali is the same whether
    # dates are Mar 15-21 or Mar 22-28. Adjacent-week misses are eliminated.
    try:
        s = date_type.fromisoformat(start_date[:10])
        start = f"{s.year}-{s.month:02d}"
        end = "m"  # Duration dropped — specialist content is duration-agnostic
    except (ValueError, TypeError, AttributeError):
        start = start_date[:7] if start_date else "unknown"
        end = "unknown"
    skill = skill_level or "any"
    dpref = f"dp{day_pref}" if day_pref is not None else "dpany"
    phash = prompt_hash(topic)

    key = make_cache_key(
        "specialist",
        "v4",
        topic,
        dest_normalized,
        start,
        end,
        skill,
        dpref,
        phash,
    )
    logger.info(f"[CACHE_KEY] Generated: {key}")
    return key


# =============================================================================
# Cache Operations (Async)
# =============================================================================


async def get_cached_specialist_output(
    db: AsyncSession,
    topic: str,
    destination: str,
    start_date: Optional[str],
    end_date: Optional[str],
    skill_level: Optional[str] = None,
    day_pref: Optional[int] = None,
) -> Optional[dict]:
    """
    Get cached specialist output: L1 → L2 fallback.

    Args:
        db: Async database session
        topic: Specialist type ("diving", "hiking", etc.)
        destination: Trip destination
        start_date: Trip start date (YYYY-MM-DD)
        end_date: Trip end date (YYYY-MM-DD)
        skill_level: User skill level (differentiates beginner vs expert cache)
        day_pref: User's requested activity count for this topic

    Returns:
        Cached dict (LLMSpecialistOutput.model_dump()) or None if not found
    """

    # Import here to avoid circular imports
    from app.db_models import ResponseCache

    cache_key = _specialist_cache_key(
        topic, destination, start_date, end_date, skill_level, day_pref=day_pref
    )

    from app.debug_utils import _debug_log

    _debug_log(f"[SPECIALIST_CACHE] key={cache_key}")

    # L1: Thread-safe memory check
    cached = _mem.get(cache_key)
    if cached is not None:
        _mem.increment_stat("l1_hits")
        logger.info(f"[CACHE] key={cache_key} → HIT (L1)")
        return cached

    _mem.increment_stat("l1_misses")
    logger.info(f"[CACHE] key={cache_key} → MISS (L1)")

    # L2: Database check
    try:
        result = await db.execute(
            select(ResponseCache)
            .where(ResponseCache.cache_key == cache_key)
            .where(ResponseCache.cache_type == "specialist")
            .where(ResponseCache.expires_at > datetime.now(UTC))
        )
        row = result.scalar_one_or_none()

        if row:
            _mem.increment_stat("l2_hits")
            logger.info(f"[CACHE] key={cache_key} → HIT (L2)")

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
        logger.info(f"[CACHE] key={cache_key} → MISS (L2)")
        return None

    except Exception as e:
        logger.warning(f"[SPECIALIST_CACHE] L2 lookup failed: {e}")
        return None


async def set_cached_specialist_output(
    db: AsyncSession,
    topic: str,
    destination: str,
    start_date: Optional[str],
    end_date: Optional[str],
    output: dict,
    skill_level: Optional[str] = None,
    day_pref: Optional[int] = None,
) -> None:
    """
    Cache specialist output to both L1 and L2.

    Args:
        db: Async database session
        topic: Specialist type
        destination: Trip destination
        start_date: Trip start date
        end_date: Trip end date
        output: LLMSpecialistOutput.model_dump() dict
        skill_level: User skill level (differentiates beginner vs expert cache)
        day_pref: User's requested activity count for this topic
    """

    cache_key = _specialist_cache_key(
        topic, destination, start_date, end_date, skill_level, day_pref=day_pref
    )

    # L1: Thread-safe write
    _mem.set(cache_key, output)

    # L2: Upsert to database
    try:
        await l2_upsert(
            db,
            cache_key=cache_key,
            cache_type="specialist",
            response_json=output,
            ttl=timedelta(hours=L2_TTL_HOURS),
        )
        _mem.increment_stat("writes")
        exp = (datetime.now(UTC) + timedelta(hours=L2_TTL_HOURS)).date()
        logger.info(f"[SPECIALIST_CACHE] Cached: {cache_key} (expires: {exp})")
    except Exception as e:
        logger.warning(f"[SPECIALIST_CACHE] L2 write failed: {e}")
        await db.rollback()


# =============================================================================
# Negative caching — short-TTL sentinel for failed LLM calls
# =============================================================================

_NEGATIVE_SENTINEL_KEY = "_negative_cache"


async def set_negative_cache(
    topic: str,
    destination: str,
    start_date: Optional[str],
    end_date: Optional[str],
    skill_level: Optional[str] = None,
    day_pref: Optional[int] = None,
    error: str = "",
) -> None:
    """Write a negative sentinel to L1 only (no DB write).

    Uses the L1 global TTL (1h). The sentinel prevents retrying an identical
    failing specialist call within the same server lifetime.
    """
    cache_key = _specialist_cache_key(
        topic, destination, start_date, end_date, skill_level, day_pref=day_pref
    )
    sentinel = {_NEGATIVE_SENTINEL_KEY: True, "_error": error[:200]}
    _mem.set(cache_key, sentinel)
    logger.info("[SPECIALIST_CACHE] Negative cache set: %s (error=%s)", cache_key, error[:80])


def is_negative_cache(value: Optional[dict]) -> bool:
    """Return True if *value* is a negative-cache sentinel."""
    return isinstance(value, dict) and value.get(_NEGATIVE_SENTINEL_KEY) is True


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
    """Clear L1 memory cache. Returns count of cleared entries."""
    count = _mem.clear()
    logger.info(f"[SPECIALIST_CACHE] Cleared L1: {count} entries")
    return count


async def clear_db_cache(db: AsyncSession) -> int:
    """Clear specialist L2 cache entries only. Returns count deleted."""
    from app.db_models import ResponseCache

    try:
        result = await db.execute(
            delete(ResponseCache).where(ResponseCache.cache_type == "specialist")
        )
        await db.commit()
        deleted = result.rowcount
        logger.info(f"[SPECIALIST_CACHE] Cleared L2: {deleted} specialist entries")
        return deleted
    except Exception as e:
        logger.warning(f"[SPECIALIST_CACHE] Clear L2 failed: {e}")
        await db.rollback()
        return 0
