"""
Thread-safe two-tier caching for Vertical Specialist LLM outputs.

L1: In-memory TTLCache with RLock (1h TTL, 128 entries) - hot path
L2: PostgreSQL response_cache (7d TTL) - warm persistence across restarts

Cache key format:
specialist::v2::{topic}::{dest}::{month}::{bucket}::{skill}::{dpref}::{phash}

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
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.planner.hashing import make_cache_key
from app.services.cache_core import MemoryCache

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================
L1_TTL_SECONDS = 3600  # 1 hour
L1_MAX_SIZE = 128
L2_TTL_DAYS = 7

# =============================================================================
# L1: Thread-safe in-memory cache
# =============================================================================
_mem = MemoryCache(maxsize=L1_MAX_SIZE, ttl=L1_TTL_SECONDS)

# Aliases for test compatibility
_cache_get = _mem.get
_cache_set = _mem.set


def _month_from_date(date_str: Optional[str]) -> str:
    """Extract YYYY-MM from a date string for seasonal cache bucketing."""
    if not date_str or len(date_str) < 7:
        return "unknown"
    return date_str[:7]  # "2026-03-15" -> "2026-03"


def _duration_bucket(start_date: Optional[str], end_date: Optional[str]) -> str:
    """
    Bucket trip duration for cache key (max 3-day spread per bucket).

    Specialist recommendations vary by trip length (more spots for longer trips)
    but not by exact day count. Narrow buckets prevent activity count regression
    where a cached 9-day result underserves a 14-day trip.
    """
    if not start_date or not end_date:
        return "unknown"
    try:
        start = datetime.strptime(start_date[:10], "%Y-%m-%d")
        end = datetime.strptime(end_date[:10], "%Y-%m-%d")
        days = (end - start).days + 1  # Inclusive
        if days <= 3:
            return "weekend"  # 1-3d
        if days <= 5:
            return "short"  # 4-5d
        if days <= 8:
            return "week"  # 6-8d
        if days <= 11:
            return "extended"  # 9-11d
        if days <= 15:
            return "twoweek"  # 12-15d
        return "long"  # 16d+
    except (ValueError, TypeError):
        return "unknown"


def _specialist_cache_key(
    topic: str,
    destination: str,
    start_date: Optional[str],
    end_date: Optional[str],
    skill_level: Optional[str] = None,
    day_pref: Optional[int] = None,
) -> str:
    """
    Generate stable cache key with month + duration bucket (not exact dates).

    Format:
    specialist::v2::{topic}::{dest}::{month}::{bucket}::{skill}::{dpref}::{phash}

    Month granularity: diving in Bali in March = same recommendations regardless
    of exact start day. Duration bucket: 5-day vs 11-day trip gets different
    density of recommendations. day_pref: user's requested activity count for
    this topic (from day_preferences stepper).
    """
    from app.planner.specialist_registry import prompt_hash

    dest_normalized = destination.lower().strip() if destination else "unknown"
    month = _month_from_date(start_date)
    bucket = _duration_bucket(start_date, end_date)
    skill = skill_level or "any"
    dpref = f"dp{day_pref}" if day_pref is not None else "dpany"
    phash = prompt_hash(topic)

    key = make_cache_key(
        "specialist",
        "v2",
        topic,
        dest_normalized,
        month,
        bucket,
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

    # Import here to avoid circular imports
    from app.db_models import ResponseCache

    cache_key = _specialist_cache_key(
        topic, destination, start_date, end_date, skill_level, day_pref=day_pref
    )
    expires_at = datetime.now(UTC) + timedelta(days=L2_TTL_DAYS)

    # L1: Thread-safe write
    _mem.set(cache_key, output)

    # L2: Upsert to database
    try:
        stmt = pg_insert(ResponseCache).values(
            cache_key=cache_key,
            cache_type="specialist",
            response_json=output,
            created_at=datetime.now(UTC),
            expires_at=expires_at,
            hit_count=0,
            last_hit_at=None,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["cache_key"],
            set_={
                "response_json": output,
                "created_at": datetime.now(UTC),
                "expires_at": expires_at,
            },
        )
        await db.execute(stmt)
        await db.commit()

        _mem.increment_stat("writes")
        logger.info(f"[SPECIALIST_CACHE] Cached: {cache_key} (expires: {expires_at.date()})")

    except Exception as e:
        logger.warning(f"[SPECIALIST_CACHE] L2 write failed: {e}")
        await db.rollback()


# =============================================================================
# Admin Functions
# =============================================================================


def get_cache_stats() -> dict:
    """Return cache statistics for observability."""
    return {
        **_mem.get_stats(),
        "l1_size": _mem.size(),
        "l1_maxsize": L1_MAX_SIZE,
        "l1_ttl_seconds": L1_TTL_SECONDS,
        "l2_ttl_days": L2_TTL_DAYS,
    }


def clear_memory_cache() -> int:
    """Clear L1 memory cache. Returns count of cleared entries."""
    count = _mem.clear()
    logger.info(f"[SPECIALIST_CACHE] Cleared L1: {count} entries")
    return count


async def clear_db_cache(db: AsyncSession) -> int:
    """Clear all L2 cache entries. Returns count deleted."""
    from app.db_models import ResponseCache

    try:
        result = await db.execute(delete(ResponseCache))
        await db.commit()
        deleted = result.rowcount
        logger.info(f"[SPECIALIST_CACHE] Cleared L2: {deleted} entries")
        return deleted
    except Exception as e:
        logger.warning(f"[SPECIALIST_CACHE] Clear L2 failed: {e}")
        await db.rollback()
        return 0
