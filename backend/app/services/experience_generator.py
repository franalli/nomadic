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

import asyncio
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Optional

from cachetools import TTLCache
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, ValidationError
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


def clear_experience_cache() -> int:
    """Clear L1 experience cache. Returns count of cleared entries."""
    with _cache_lock:
        count = len(_experience_cache)
        _experience_cache.clear()
    return count


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
    """Single experience activity generated by LLM - 6 fields (removed subtitle)."""

    title: str = Field(description="Real activity name, e.g. 'Ubud Morning Vinyasa'")
    # REMOVED: subtitle field (unused by frontend - not rendered anywhere)
    category: str = Field(description="Category from the requested list, e.g. 'yoga'")
    duration_hours: float = Field(default=2.0, description="Activity duration in hours")
    price_estimate: int = Field(default=40, description="Price per person in USD")
    time_of_day: str = Field(
        default="morning", description="When activity happens: morning, afternoon, or evening"
    )
    skill_level: str = Field(default="beginner", description="beginner, intermediate, or advanced")
    description: str = Field(
        default="",
        description="One-sentence hook, e.g. 'Traditional flow with rice paddy views'",
    )


class ExperienceOutput(BaseModel):
    """Structured output from experience generation LLM call."""

    activities: list[ExperienceTile] = Field(description="List of generated experience activities")


# =============================================================================
# Prompt
# =============================================================================

SYSTEM_PROMPT = """Generate real, bookable activities for a destination. Each must be a REAL \
venue or experience (not generic). Single sessions only (1-4h), not multi-day retreats. \
Vary time_of_day (morning/afternoon/evening). Include realistic local pricing in USD. \
For each activity, write a vivid one-sentence description that hooks the traveler.
Example: "Sunrise Yoga at Ubud Studio", description "Traditional flow with rice paddy views"."""
# ~45 tokens (vs ~80 current) - structured output schema already constrains fields


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


def _clamp_tile_durations(tiles: list, max_hours: float = 4.0) -> list:
    """Clamp duration_hours in cached tile dicts. Defensive against stale cache."""
    for tile in tiles:
        meta = tile.get("meta") or {}
        if meta.get("duration_hours", 0) > max_hours:
            logger.info(
                f"[EXPERIENCE] Clamped cached '{tile.get('title')}': "
                f"{meta['duration_hours']}h → {max_hours}h"
            )
            meta["duration_hours"] = max_hours
    return tiles


def _experience_to_tile_dict(
    tile: ExperienceTile,
    destination: str,
    index: int,
) -> dict:
    """Convert an ExperienceTile to a standard tile dict matching schemas.Tile."""
    dest_normalized = destination.lower().strip().replace(" ", "_").replace(",", "")
    tile_id = f"exp_{dest_normalized}_{tile.category}_{index}"

    # Derive subtitle from time_of_day + category
    time_label = tile.time_of_day.capitalize()
    category_label = tile.category.capitalize()
    subtitle = f"{time_label} {category_label}"  # e.g., "Morning Yoga"

    # Use cached Unsplash URL if prefetch populated it; None otherwise.
    # Frontend renders a placeholder shimmer for null image_url.
    from app.services.unsplash import get_cached_image_url

    image_url = get_cached_image_url(destination, variant=index % 6, activities=[tile.category])

    return {
        "id": tile_id,
        "type": "activity",
        "partner": "experience_generator",
        "partner_product_id": tile_id,
        "title": tile.title,
        "subtitle": subtitle,  # Derived, not LLM-generated
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
            "description": tile.description,
        },
        "source": "live",
        "source_agent": "experience_generator",
    }


async def generate_single_category(
    destination: str,
    category: str,
    month: str,
    budget: int | None = None,
    tier1_specialists: list[str] | None = None,
    tiles_per_category: int = 2,
    base_index: int = 0,  # Offset for tile IDs and image variants
) -> list[dict]:
    """Generate tiles for a SINGLE category. Used for parallel generation.

    Uses compressed 6-field schema (no subtitle) matching Tier A optimization.

    Args:
        base_index: Starting index for tile IDs and image variants. When generating
                    multiple categories in parallel, pass incremental offsets to maintain
                    image diversity (e.g., cat1=0, cat2=2, cat3=4 for 2 tiles/cat).
    """
    if not destination or not category:
        return []

    logger.info(
        f"[EXPERIENCE] Generating single category: {category} for {destination}"
        f", base_index={base_index}"
    )

    start_t = time.time()
    try:
        extra_tiles = max(0, tiles_per_category - 2)
        max_tokens = min(600 + extra_tiles * 100, 1200)

        llm = ChatOpenAI(model=EXPERIENCE_MODEL, temperature=0.3, max_tokens=max_tokens)
        # Use compressed schema without include_raw (token logging via usage_metadata when fixed)
        structured_llm = llm.with_structured_output(ExperienceOutput)

        user_prompt = _build_user_prompt(
            destination, [category], month, budget, tier1_specialists, tiles_per_category
        )

        parsed: ExperienceOutput = await structured_llm.ainvoke(
            [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ]
        )

        duration_ms = int((time.time() - start_t) * 1000)
        logger.info(
            f"[EXPERIENCE] Generated {len(parsed.activities)} tiles in {duration_ms}ms"
            f" for {category}"
        )

    except Exception as e:
        logger.warning(f"[EXPERIENCE] Single category {category} failed: {e}")
        return []

    # Clamp durations
    for tile in parsed.activities:
        if tile.duration_hours > 4:
            tile.duration_hours = 4

    # Convert to tile dicts with base_index offset
    tile_dicts = []
    for i, tile in enumerate(parsed.activities):
        tile_dict = _experience_to_tile_dict(tile, destination, base_index + i)
        tile_dicts.append(tile_dict)

    return tile_dicts


async def generate_experience_tiles_for_day(
    destination: str,
    categories: list[str] | None,
    month: str,
    day_number: int,
    budget: int | None = None,
    tiles_per_day: int = 3,
) -> list[dict]:
    """
    Generate experience tiles for a single free day.

    Lightweight endpoint-oriented function that:
    1. Round-robin distributes tiles across user's selected categories
    2. Calls generate_single_category() for each (reuses L1/L2 cache)
    3. Returns up to tiles_per_day tile dicts

    Does NOT run the LangGraph pipeline. Does NOT modify state.
    When categories is None/empty, uses a generic "activities" category
    so the LLM picks destination-appropriate experiences.
    """
    if not destination:
        logger.warning("[EXPERIENCE] fill-day skip: no destination")
        return []

    if not categories:
        categories = ["activities"]

    # Round-robin categories across tile slots
    cat_tile_counts: dict[str, int] = {}
    for i in range(tiles_per_day):
        cat = categories[i % len(categories)]
        cat_tile_counts[cat] = cat_tile_counts.get(cat, 0) + 1

    logger.info(
        f"[EXPERIENCE] fill-day: day={day_number}, cats={cat_tile_counts}, dest={destination}"
    )

    # Generate per-category in parallel (reuses L1/L2 cache)
    tasks = []
    base_index = day_number * 100  # Offset for unique tile IDs
    for cat, count in cat_tile_counts.items():
        tasks.append(
            generate_single_category(
                destination=destination,
                category=cat,
                month=month,
                budget=budget,
                tiles_per_category=count,
                base_index=base_index,
            )
        )
        base_index += count

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_tiles = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            cat = list(cat_tile_counts.keys())[i]
            logger.warning(f"[EXPERIENCE] fill-day category '{cat}' failed: {result}")
            continue
        all_tiles.extend(result)

    all_tiles = all_tiles[:tiles_per_day]
    logger.info(f"[EXPERIENCE] fill-day: generated {len(all_tiles)} tiles for day {day_number}")
    return all_tiles


# =============================================================================
# Main Entry Point
# =============================================================================


async def _parallel_category_generate(
    categories: list[str],
    destination: str,
    month: str,
    budget: int | None,
    tier1_specialists: list[str] | None,
    tiles_per_category: int,
) -> list[dict]:
    """Per-category parallel LLM generation. Returns flat list of tile dicts."""
    start_t = time.time()
    tasks = []
    base_index = 0
    for cat in categories:
        tasks.append(
            generate_single_category(
                destination=destination,
                category=cat,
                month=month,
                budget=budget,
                tier1_specialists=tier1_specialists,
                tiles_per_category=tiles_per_category,
                base_index=base_index,
            )
        )
        base_index += tiles_per_category

    results = await asyncio.gather(*tasks, return_exceptions=True)

    tile_dicts: list[dict] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning(f"[EXPERIENCE] Category '{categories[i]}' failed: {result}")
            continue
        tile_dicts.extend(result)

    duration_ms = int((time.time() - start_t) * 1000)
    logger.info(f"[EXPERIENCE] Parallel generation: {len(tile_dicts)} tiles in {duration_ms}ms")
    return tile_dicts


async def generate_experiences(
    destination: str,
    categories: list[str],
    month: str,
    budget: int | None = None,
    tier1_specialists: list[str] | None = None,
    tiles_per_category: int = 2,
    state=None,
) -> list[dict]:
    """
    Generate Tier 2 experience tiles via gpt-4o-mini structured output.

    Supports incremental generation: if some categories were already generated this session,
    only new categories are generated via LLM and merged with existing tiles.

    Args:
        destination: Trip destination (e.g., "Bali")
        categories: Tier 2 categories (e.g., ["yoga", "cooking", "nightlife"])
        month: Month string "YYYY-MM" for seasonal context
        budget: Optional total trip budget for price constraints
        tier1_specialists: Active Tier 1 specialists to avoid overlap
        tiles_per_category: Number of tiles per category (2-4, scaled by trip length)
        state: GraphState for tracking previously generated categories

    Returns:
        List of tile dicts ready for state.tiles["activities"], or [] on failure.
    """
    # Outer try/except to catch any unhandled exceptions (especially from asyncio.create_task)
    try:
        if not destination or not categories:
            logger.warning(f"[EXPERIENCE] Early return: dest={destination}, cats={categories}")
            return []

        try:
            cache_key = _experience_cache_key(destination, categories, month, tiles_per_category)
        except Exception as e:
            logger.error(f"[EXPERIENCE] Cache key computation failed: {e}", exc_info=True)
            return []

        # L1: Memory cache check (fast path for exact category match)
        cached = _cache_get(cache_key)
        if cached is not None:
            _increment_stat("l1_hits")
            logger.info(f"[EXPERIENCE] Cache HIT (L1): {len(cached)} tiles")
            return _clamp_tile_durations(cached)

        _increment_stat("l1_misses")

        # L2: Database cache check (own session)
        logger.info("[EXPERIENCE] Checking L2 cache...")
        from app.db import _get_async_session_factory

        async_session_factory = _get_async_session_factory()

        try:
            async with async_session_factory() as db:
                l2_cached = await _get_cached(db, cache_key)
                if l2_cached is not None:
                    logger.info(f"[EXPERIENCE] Cache HIT (L2): {len(l2_cached)} tiles")
                    return _clamp_tile_durations(l2_cached)
        except Exception as e:
            logger.warning(f"[EXPERIENCE] L2 cache check failed: {e}")
            # Fall through to generation

        logger.info("[EXPERIENCE] L2 cache MISS")

        # Check for incremental generation opportunity (state metadata)
        new_cats = list(categories)  # Default: generate all categories
        existing_tiles_by_cat = {}

        if state is not None and hasattr(state, "metadata"):
            previously_generated = state.metadata.get("generated_tier2_categories", {})
            existing_tiles_by_cat = previously_generated.get(destination, {})

            # Diff to find NEW categories
            new_cats = [cat for cat in categories if cat not in existing_tiles_by_cat]

            if new_cats != list(categories):
                logger.info(
                    f"[EXPERIENCE] Incremental generation: {len(new_cats)} new categories "
                    f"(already have {len(categories) - len(new_cats)})"
                )

        # If all categories exist in state metadata, merge and return
        if not new_cats and existing_tiles_by_cat:
            all_tiles = []
            for cat in categories:
                all_tiles.extend(existing_tiles_by_cat.get(cat, []))
            logger.info(f"[EXPERIENCE] All categories cached in state: {len(all_tiles)} tiles")
            # Cache composite result
            _cache_set(cache_key, all_tiles)
            return _clamp_tile_durations(all_tiles)

        # Cache miss — generate NEW categories via LLM
        # Structured output degrades >4 tiles; use per-category parallel above that.
        MAX_BATCH_TILES = 4
        total_tiles = tiles_per_category * len(new_cats)
        logger.info(
            f"[EXPERIENCE] Generation: {len(new_cats)} categories, "
            f"{total_tiles} tiles for {destination} "
            f"(path={'batch' if total_tiles <= MAX_BATCH_TILES else 'parallel'})"
        )

        start_t = time.time()

        if total_tiles <= MAX_BATCH_TILES:
            # Small batch: single LLM call (fast for ≤4 tiles)
            try:
                max_tokens = min(200 * total_tiles, 2400)
                llm = ChatOpenAI(model=EXPERIENCE_MODEL, temperature=0.3, max_tokens=max_tokens)
                structured_llm = llm.with_structured_output(ExperienceOutput)

                user_prompt = _build_user_prompt(
                    destination, new_cats, month, budget, tier1_specialists, tiles_per_category
                )

                parsed: ExperienceOutput = await structured_llm.ainvoke(
                    [
                        SystemMessage(content=SYSTEM_PROMPT),
                        HumanMessage(content=user_prompt),
                    ]
                )

                for tile in parsed.activities:
                    if tile.duration_hours > 4:
                        tile.duration_hours = 4

                new_tile_dicts = []
                for i, tile in enumerate(parsed.activities):
                    new_tile_dicts.append(_experience_to_tile_dict(tile, destination, i))

                duration_ms = int((time.time() - start_t) * 1000)
                logger.info(
                    f"[EXPERIENCE] Batch generation: {len(new_tile_dicts)} tiles in {duration_ms}ms"
                )

            except (ValidationError, Exception) as e:
                logger.warning(f"[EXPERIENCE] Batch failed, falling back to parallel: {e}")
                new_tile_dicts = await _parallel_category_generate(
                    new_cats, destination, month, budget, tier1_specialists, tiles_per_category
                )
        else:
            # Large request: per-category parallel calls (avoids structured output degradation)
            new_tile_dicts = await _parallel_category_generate(
                new_cats, destination, month, budget, tier1_specialists, tiles_per_category
            )

        duration_ms = int((time.time() - start_t) * 1000)
        logger.info(
            f"[EXPERIENCE] Total generation: {len(new_tile_dicts)} tiles in {duration_ms}ms"
        )

        if not new_tile_dicts:
            logger.warning("[EXPERIENCE] Parallel generation returned 0 tiles")
            return []

        # Prefetch Unsplash images in background (non-blocking)
        async def _background_prefetch():
            try:
                from app.services.unsplash import prefetch_destination_images

                for category in new_cats:
                    try:
                        await prefetch_destination_images(destination, activities=[category])
                    except Exception:
                        pass  # Non-fatal, falls back to placeholder
            except Exception as e:
                logger.warning(f"[EXPERIENCE] Background prefetch failed: {e}")

        # Fire and forget - images will populate asynchronously
        asyncio.create_task(_background_prefetch())

        # Update state metadata with new tiles by category
        if state is not None and hasattr(state, "metadata"):
            if "generated_tier2_categories" not in state.metadata:
                state.metadata["generated_tier2_categories"] = {}
            if destination not in state.metadata["generated_tier2_categories"]:
                state.metadata["generated_tier2_categories"][destination] = {}

            dest_tiles = state.metadata["generated_tier2_categories"][destination]

            # Track new tiles by category
            for cat in new_cats:
                cat_tiles = [t for t in new_tile_dicts if t.get("meta", {}).get("category") == cat]
                dest_tiles[cat] = cat_tiles

        # Merge existing + new tiles for full composite result
        all_tiles = []
        for cat in categories:
            cat_tiles = existing_tiles_by_cat.get(cat, [])
            if not cat_tiles and state is not None and hasattr(state, "metadata"):
                # Get from newly updated metadata
                dest_tiles = state.metadata.get("generated_tier2_categories", {}).get(
                    destination, {}
                )
                cat_tiles = dest_tiles.get(cat, [])
            all_tiles.extend(cat_tiles)

        # Prefetch path (state=None): merge loop finds nothing, use new tiles directly
        if not all_tiles and new_tile_dicts:
            all_tiles = new_tile_dicts

        # Cache the FULL composite result (L1 + L2)
        _cache_set(cache_key, all_tiles)

        async with async_session_factory() as db:
            await _set_cached(db, cache_key, all_tiles)

        logger.info(
            f"[EXPERIENCE] Done: {len(all_tiles)} tiles total "
            f"({len(new_tile_dicts)} new, {len(all_tiles) - len(new_tile_dicts)} existing) "
            f"cached for {destination}"
        )
        return all_tiles

    except Exception as e:
        logger.error(
            f"[EXPERIENCE] FATAL unhandled exception: {e}",
            exc_info=True,
        )
        return []
