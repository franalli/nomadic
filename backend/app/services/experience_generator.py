"""
Tier 2 Experience Generator — LLM-generated activity tiles for non-specialist categories.

Generates real, destination-specific experience tiles (yoga, cooking, nightlife, etc.)
via a single gpt-4o-mini structured output call. Cached aggressively so cost is near-zero
after the first unique query.

L1: In-memory TTLCache with RLock (1h TTL, 128 entries)
L2: PostgreSQL response_cache (7d TTL) via ResponseCache table

Cache key format: experience:{destination}:{sorted_categories}:{month}

Usage:
    from app.services.experience_generator import generate_experiences

    tiles = await generate_experiences(
        destination="Bali",
        categories=["yoga", "cooking", "nightlife"],
        month="2026-03",
    )
    # Returns list of tile dicts ready for state.tiles["activities"]
"""

import logging
import os
import time
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Optional

from cachetools import TTLCache
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================
L1_TTL_SECONDS = 3600  # 1 hour
L1_MAX_SIZE = 128
L2_TTL_DAYS = 7

EXPERIENCE_MODEL = os.getenv("EXPERIENCE_MODEL", "gpt-4o-mini")

# =============================================================================
# L1: Thread-safe in-memory cache
# =============================================================================
_cache_lock = RLock()
_stats_lock = RLock()
_experience_cache: TTLCache = TTLCache(maxsize=L1_MAX_SIZE, ttl=L1_TTL_SECONDS)

_cache_stats = {
    "l1_hits": 0,
    "l1_misses": 0,
    "l2_hits": 0,
    "l2_misses": 0,
    "writes": 0,
}


def _increment_stat(key: str) -> None:
    with _stats_lock:
        _cache_stats[key] += 1


def _cache_get(key: str) -> Optional[list]:
    with _cache_lock:
        return _experience_cache.get(key)


def _cache_set(key: str, value: list) -> None:
    with _cache_lock:
        _experience_cache[key] = value


# =============================================================================
# Cache Key
# =============================================================================


def _experience_cache_key(
    destination: str, categories: list[str], month: str, tiles_per_category: int = 2
) -> str:
    """
    Generate stable cache key: experience:{dest}:{sorted_cats}:{month}:n{count}

    Categories are sorted alphabetically for stable keys regardless of input order.
    Month granularity (not full dates) — experiences are seasonal, not date-specific.

    Example: "experience:bali:cooking|nightlife|yoga:2026-03:n4"
    """
    dest_normalized = destination.lower().strip() if destination else "unknown"
    cats_normalized = "|".join(sorted(c.lower().strip() for c in categories))
    month_normalized = month if month else "unknown"
    key = f"experience:{dest_normalized}:{cats_normalized}:{month_normalized}:n{tiles_per_category}"
    logger.info(f"[EXPERIENCE_CACHE] Key: {key}")
    return key


# =============================================================================
# L2: Database cache operations
# =============================================================================


async def _get_cached(db: AsyncSession, cache_key: str) -> Optional[list]:
    """Check L2 cache for experience output."""
    from app.db_models import ResponseCache

    try:
        result = await db.execute(
            select(ResponseCache)
            .where(ResponseCache.cache_key == cache_key)
            .where(ResponseCache.cache_type == "experience")
            .where(ResponseCache.expires_at > datetime.now(UTC))
        )
        row = result.scalar_one_or_none()

        if row:
            _increment_stat("l2_hits")
            logger.info(f"[EXPERIENCE_CACHE] key={cache_key} → HIT (L2)")
            _cache_set(cache_key, row.response_json)  # Promote to L1

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
        logger.info(f"[EXPERIENCE_CACHE] key={cache_key} → MISS (L2)")
        return None

    except Exception as e:
        logger.warning(f"[EXPERIENCE_CACHE] L2 lookup failed: {e}")
        return None


async def _set_cached(db: AsyncSession, cache_key: str, output: list) -> None:
    """Write experience output to L2 cache."""
    from app.db_models import ResponseCache

    expires_at = datetime.now(UTC) + timedelta(days=L2_TTL_DAYS)

    try:
        stmt = pg_insert(ResponseCache).values(
            cache_key=cache_key,
            cache_type="experience",
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
        _increment_stat("writes")
        logger.info(f"[EXPERIENCE_CACHE] Cached: {cache_key} (expires: {expires_at.date()})")

    except Exception as e:
        logger.warning(f"[EXPERIENCE_CACHE] L2 write failed: {e}")
        await db.rollback()


# =============================================================================
# Pydantic Models (LLM structured output)
# =============================================================================


class ExperienceTile(BaseModel):
    """Single experience activity generated by LLM."""

    title: str = Field(description="Real activity name, e.g. 'Ubud Morning Vinyasa'")
    subtitle: str = Field(description="Short description, e.g. 'Rice paddy views at sunrise'")
    category: str = Field(description="Category from the requested list, e.g. 'yoga'")
    duration_hours: float = Field(default=2.0, description="Activity duration in hours")
    price_estimate: int = Field(default=40, description="Price per person in USD")
    time_of_day: str = Field(
        default="morning", description="When activity happens: morning, afternoon, or evening"
    )
    skill_level: str = Field(default="beginner", description="beginner, intermediate, or advanced")


class ExperienceOutput(BaseModel):
    """Structured output from experience generation LLM call."""

    activities: list[ExperienceTile] = Field(description="List of generated experience activities")


# =============================================================================
# Prompt
# =============================================================================

SYSTEM_PROMPT = """You are a travel activity generator. Generate real, bookable experience \
activities for a specific destination. Each activity must be a REAL place or experience that \
exists at the destination. Include realistic local pricing. Vary time_of_day across activities \
(morning, afternoon, evening)."""


def _build_user_prompt(
    destination: str,
    categories: list[str],
    month: str,
    budget: int | None = None,
    tier1_specialists: list[str] | None = None,
    tiles_per_category: int = 2,
) -> str:
    """Build the user message for experience generation."""
    # Parse month name from YYYY-MM
    month_name = month
    if month and len(month) >= 7:
        try:
            month_dt = datetime.strptime(month[:7], "%Y-%m")
            month_name = month_dt.strftime("%B %Y")
        except ValueError:
            pass

    parts = [
        f"Generate activities for {destination} in {month_name}.",
        f"Categories: {', '.join(categories)}",
        (
            f"Generate {tiles_per_category} activities per category. "
            "Each must be a REAL place/experience."
        ),
        "Include realistic local pricing in USD.",
    ]

    if budget:
        budget_per_activity = max(20, budget // (len(categories) * tiles_per_category))
        parts.append(f"Budget: each activity should be under ${budget_per_activity} USD.")

    if tier1_specialists:
        specialists_str = ", ".join(tier1_specialists)
        parts.append(
            f"Note: {specialists_str} specialist(s) already handle those domains — "
            f"avoid overlap (e.g., don't suggest snorkeling when diving specialist is active)."
        )

    return "\n".join(parts)


# =============================================================================
# Tile Conversion
# =============================================================================


def _experience_to_tile_dict(
    tile: ExperienceTile,
    destination: str,
    index: int,
) -> dict:
    """Convert an ExperienceTile to a standard tile dict matching schemas.Tile."""
    dest_normalized = destination.lower().strip().replace(" ", "_").replace(",", "")
    tile_id = f"exp_{dest_normalized}_{tile.category}_{index}"

    # Get image URL via existing Unsplash pipeline
    from app.services.unsplash import get_image_url_sync

    image_url = get_image_url_sync(destination, variant=index % 6, activities=[tile.category])

    return {
        "id": tile_id,
        "type": "activity",
        "partner": "experience_generator",
        "partner_product_id": tile_id,
        "title": tile.title,
        "subtitle": tile.subtitle,
        "image_url": image_url,
        "price_estimate": float(tile.price_estimate),
        "currency": "USD",
        "price_basis": "per_person",
        "is_estimate_only": True,
        "deeplink_url": "",
        "rating": None,
        "location_label": destination,
        "tags": ["activity", tile.category, "experience"],
        "availability_status": "available",
        "meta": {
            "category": tile.category,
            "time_of_day": tile.time_of_day,
            "skill_level": tile.skill_level,
            "duration_hours": tile.duration_hours,
        },
        "source": "live",
        "source_agent": "experience_generator",
    }


# =============================================================================
# Main Entry Point
# =============================================================================


async def generate_experiences(
    destination: str,
    categories: list[str],
    month: str,
    budget: int | None = None,
    tier1_specialists: list[str] | None = None,
    tiles_per_category: int = 2,
) -> list[dict]:
    """
    Generate Tier 2 experience tiles via gpt-4o-mini structured output.

    Args:
        destination: Trip destination (e.g., "Bali")
        categories: Tier 2 categories (e.g., ["yoga", "cooking", "nightlife"])
        month: Month string "YYYY-MM" for seasonal context
        budget: Optional total trip budget for price constraints
        tier1_specialists: Active Tier 1 specialists to avoid overlap
        tiles_per_category: Number of tiles per category (2-4, scaled by trip length)

    Returns:
        List of tile dicts ready for state.tiles["activities"], or [] on failure.
    """
    if not destination or not categories:
        return []

    cache_key = _experience_cache_key(destination, categories, month, tiles_per_category)

    # L1: Memory cache check
    cached = _cache_get(cache_key)
    if cached is not None:
        _increment_stat("l1_hits")
        logger.info(f"[EXPERIENCE] Cache HIT (L1): {len(cached)} tiles")
        return cached

    _increment_stat("l1_misses")

    # L2: Database cache check (own session)
    from app.db import _get_async_session_factory

    async_session_factory = _get_async_session_factory()

    async with async_session_factory() as db:
        l2_cached = await _get_cached(db, cache_key)
        if l2_cached is not None:
            logger.info(f"[EXPERIENCE] Cache HIT (L2): {len(l2_cached)} tiles")
            return l2_cached

    # Cache miss — generate via LLM
    logger.info(
        f"[EXPERIENCE] Cache MISS — generating for {destination}, "
        f"categories={categories}, month={month}"
    )

    start_t = time.time()
    try:
        # Scale max_tokens proportionally to tile count
        extra_tiles = max(0, tiles_per_category - 2) * len(categories)
        max_tokens = min(800 + extra_tiles * 100, 1600)

        llm = ChatOpenAI(
            model=EXPERIENCE_MODEL,
            temperature=0.3,
            max_tokens=max_tokens,
        )
        structured_llm = llm.with_structured_output(ExperienceOutput, include_raw=True)

        user_prompt = _build_user_prompt(
            destination, categories, month, budget, tier1_specialists, tiles_per_category
        )

        result = await structured_llm.ainvoke(
            [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ]
        )

        parsed: ExperienceOutput = result["parsed"]
        raw = result["raw"]
        duration_ms = int((time.time() - start_t) * 1000)

        # Token usage logging
        token_usage = {}
        if hasattr(raw, "response_metadata"):
            token_usage = raw.response_metadata.get("token_usage", {})

        logger.info(
            f"[EXPERIENCE] Generated {len(parsed.activities)} tiles in {duration_ms}ms | "
            f"p={token_usage.get('prompt_tokens', '?')} "
            f"c={token_usage.get('completion_tokens', '?')} "
            f"categories={categories} dest={destination}"
        )

    except Exception as e:
        duration_ms = int((time.time() - start_t) * 1000)
        logger.warning(f"[EXPERIENCE] LLM call failed after {duration_ms}ms: {e} — returning empty")
        return []

    if not parsed.activities:
        logger.warning("[EXPERIENCE] LLM returned 0 activities")
        return []

    # Prefetch Unsplash images per category (non-fatal)
    try:
        from app.services.unsplash import prefetch_destination_images

        for category in categories:
            try:
                await prefetch_destination_images(destination, activities=[category])
            except Exception:
                pass  # Non-fatal, falls back to placeholder
    except Exception as e:
        logger.warning(f"[EXPERIENCE] Unsplash prefetch import failed: {e}")

    # Convert to tile dicts
    tile_dicts = []
    for i, tile in enumerate(parsed.activities):
        tile_dict = _experience_to_tile_dict(tile, destination, i)
        tile_dicts.append(tile_dict)

    # Cache the result (L1 + L2)
    _cache_set(cache_key, tile_dicts)

    async with async_session_factory() as db:
        await _set_cached(db, cache_key, tile_dicts)

    logger.info(f"[EXPERIENCE] Done: {len(tile_dicts)} tiles cached for {destination}")
    return tile_dicts
