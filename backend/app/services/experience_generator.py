"""
Tier 2 Experience Generator — LLM-generated activity tiles for non-specialist categories.

Generates real, destination-specific experience tiles (yoga, cooking, nightlife, etc.)
via a single gpt-4o-mini structured output call. Cached aggressively so cost is near-zero
after the first unique query.

L1: In-memory TTLCache with RLock (1h TTL, 128 entries)
L2: PostgreSQL response_cache (72h TTL, env-configurable) via ResponseCache table

Cache key format: experience::v2::{destination}::{sorted_categories}::{month}::n{count}

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
import time
from datetime import UTC, datetime, timedelta
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.planner.hashing import make_cache_key
from app.planner.llm_factory import get_llm_by_model
from app.services.cache_core import MemoryCache, l2_upsert
from app.services.task_tracker import track as _track_task

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================
L1_TTL_SECONDS = 3600  # 1 hour
L1_MAX_SIZE = 128
L2_TTL_HOURS = settings.experience_cache_ttl_hours  # default 72h — env: EXPERIENCE_CACHE_TTL_HOURS

# =============================================================================
# L1: Thread-safe in-memory cache
# =============================================================================
_mem = MemoryCache(maxsize=L1_MAX_SIZE, ttl=L1_TTL_SECONDS)

# Aliases for test compatibility
_cache_get = _mem.get
_cache_set = _mem.set

_inflight_generation_lock = asyncio.Lock()
_inflight_generation_tasks: dict[str, asyncio.Task[list[dict]]] = {}


async def cancel_inflight() -> int:
    """Cancel all in-flight experience generation tasks. Called during shutdown."""
    async with _inflight_generation_lock:
        tasks = list(_inflight_generation_tasks.values())
        _inflight_generation_tasks.clear()
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    return len(tasks)


def _set_tier2_generation_source(state, source: str) -> None:
    if state is not None and hasattr(state, "metadata"):
        state.metadata["tier2_generation_source_internal"] = source


def clear_experience_cache() -> int:
    """Clear L1 experience cache. Returns count of cleared entries."""
    return _mem.clear()


async def clear_experience_db_cache(db: AsyncSession) -> int:
    """Clear all L2 experience cache entries. Returns count deleted."""
    from app.db_models import ResponseCache

    try:
        result = await db.execute(
            delete(ResponseCache).where(ResponseCache.cache_type == "experience")
        )
        result_single = await db.execute(
            delete(ResponseCache).where(ResponseCache.cache_type == "experience_single")
        )
        await db.commit()
        deleted = result.rowcount + result_single.rowcount
        return deleted
    except Exception as e:
        logger.warning(f"[EXPERIENCE] Clear L2 failed: {e}")
        await db.rollback()
        return 0


def has_cached(
    destination: str, categories: list[str], month: str, tiles_per_category: int = 2
) -> bool:
    """Check if L1 cache has results for this generation key."""
    key = _experience_cache_key(destination, categories, month, tiles_per_category)
    return _mem.get(key) is not None


# =============================================================================
# Cache Key
# =============================================================================


def _experience_cache_key(
    destination: str, categories: list[str], month: str, tiles_per_category: int = 2
) -> str:
    """
    Generate stable cache key:
    experience::v2::{dest}::{sorted_cats}::{month}::n{count}

    Categories are sorted alphabetically for stable keys regardless of input order.
    Month granularity (not full dates) — experiences are seasonal, not date-specific.

    Example: "experience::v2::bali::cooking|nightlife|yoga::2026-03::n4"
    """
    dest_normalized = destination.lower().strip() if destination else "unknown"
    cats_normalized = "|".join(sorted(c.lower().strip() for c in categories))
    month_normalized = month if month else "unknown"
    key = make_cache_key(
        "experience",
        "v2",
        dest_normalized,
        cats_normalized,
        month_normalized,
        f"n{tiles_per_category}",
    )
    logger.info(f"[EXPERIENCE_CACHE] Key: {key}")
    return key


def _single_category_cache_key(
    destination: str,
    category: str,
    month: str,
    tiles_per_category: int = 2,
) -> str:
    """Stable cache key for single-category generation used by fill-day flows."""
    dest_normalized = destination.lower().strip() if destination else "unknown"
    category_normalized = category.lower().strip() if category else "unknown"
    month_normalized = month if month else "unknown"
    key = make_cache_key(
        "experience_single",
        "v1",
        dest_normalized,
        category_normalized,
        month_normalized,
        f"n{tiles_per_category}",
    )
    logger.info(f"[EXPERIENCE_CACHE] Single key: {key}")
    return key


# =============================================================================
# L2: Database cache operations
# =============================================================================


async def _get_cached(
    db: AsyncSession,
    cache_key: str,
    cache_type: str = "experience",
) -> Optional[list]:
    """Check L2 cache for experience output."""
    from app.db_models import ResponseCache

    try:
        result = await db.execute(
            select(ResponseCache)
            .where(ResponseCache.cache_key == cache_key)
            .where(ResponseCache.cache_type == cache_type)
            .where(ResponseCache.expires_at > datetime.now(UTC))
        )
        row = result.scalar_one_or_none()

        if row:
            _mem.increment_stat("l2_hits")
            logger.info(f"[EXPERIENCE_CACHE] key={cache_key} → HIT (L2:{cache_type})")
            _mem.set(cache_key, row.response_json)  # Promote to L1

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
        logger.info(f"[EXPERIENCE_CACHE] key={cache_key} → MISS (L2:{cache_type})")
        return None

    except Exception as e:
        logger.warning(f"[EXPERIENCE_CACHE] L2 lookup failed: {e}")
        return None


async def _set_cached(
    db: AsyncSession,
    cache_key: str,
    output: list,
    cache_type: str = "experience",
) -> None:
    """Write experience output to L2 cache."""
    try:
        await l2_upsert(
            db,
            cache_key=cache_key,
            cache_type=cache_type,
            response_json=output,
            ttl=timedelta(hours=L2_TTL_HOURS),
        )
        _mem.increment_stat("writes")
        exp = (datetime.now(UTC) + timedelta(hours=L2_TTL_HOURS)).date()
        logger.info(f"[EXPERIENCE_CACHE] Cached: {cache_key} (expires: {exp})")
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

    # Cache-first image lookup with deterministic fallback:
    # 1. Use prefetched Unsplash variant when available.
    # 2. Fall back to sync helper (memory cache or deterministic Unsplash placeholder).
    # This avoids null image_url on day cards when prefetch/network misses.
    from app.services.unsplash import get_cached_image_url, get_image_url_sync

    image_url = get_cached_image_url(destination, variant=index % 6, activities=[tile.category])
    if image_url is None:
        image_url = get_image_url_sync(destination, variant=index % 6, activities=[tile.category])

    # Convert USD price estimate to 0-4 price_level for uniform DayBlock display
    _usd = float(tile.price_estimate)
    if _usd <= 0:
        _price_level = 0
    elif _usd <= 30:
        _price_level = 1
    elif _usd <= 80:
        _price_level = 2
    elif _usd <= 150:
        _price_level = 3
    else:
        _price_level = 4

    return {
        "id": tile_id,
        "type": "activity",
        "partner": "experience_generator",
        "partner_product_id": tile_id,
        "title": tile.title,
        "subtitle": subtitle,  # Derived, not LLM-generated
        "image_url": image_url,
        "price_estimate": float(tile.price_estimate),
        "price_level": _price_level,
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


def _cached_single_category_to_tiles(
    cached_payload: list[dict],
    destination: str,
    base_index: int,
) -> list[dict]:
    """Rehydrate cached activities and apply runtime index offsets for tile IDs."""
    tile_dicts: list[dict] = []
    for idx, payload in enumerate(cached_payload):
        tile = ExperienceTile.model_validate(payload)
        if tile.duration_hours > 4:
            tile.duration_hours = 4
        tile_dicts.append(_experience_to_tile_dict(tile, destination, base_index + idx))
    return tile_dicts


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

    cache_key = _single_category_cache_key(destination, category, month, tiles_per_category)

    # L1: In-memory cache for repeat fill-day category requests
    cached_payload = _mem.get(cache_key)
    if cached_payload is not None:
        _mem.increment_stat("l1_hits")
        try:
            tile_dicts = _cached_single_category_to_tiles(cached_payload, destination, base_index)
            logger.info(
                f"[EXPERIENCE] Single category cache HIT (L1): {category} → {len(tile_dicts)} tiles"
            )
            return tile_dicts
        except (ValidationError, TypeError, ValueError) as e:
            logger.warning(
                "[EXPERIENCE] Single category L1 payload invalid, regenerating: %s",
                e,
            )
    else:
        _mem.increment_stat("l1_misses")

    async_session_factory = None
    try:
        from app.db import _get_async_session_factory

        async_session_factory = _get_async_session_factory()
    except Exception as e:
        logger.warning(f"[EXPERIENCE] Single category DB session unavailable: {e}")

    # L2: Persistent cache (shared across process restarts)
    if async_session_factory is not None:
        try:
            async with async_session_factory() as db:
                l2_cached = await _get_cached(db, cache_key, cache_type="experience_single")
                if l2_cached is not None:
                    try:
                        tile_dicts = _cached_single_category_to_tiles(
                            l2_cached, destination, base_index
                        )
                        logger.info(
                            f"[EXPERIENCE] Single category cache HIT (L2): {category} "
                            f"→ {len(tile_dicts)} tiles"
                        )
                        return tile_dicts
                    except (ValidationError, TypeError, ValueError) as e:
                        logger.warning(
                            "[EXPERIENCE] Single category L2 payload invalid, regenerating: %s",
                            e,
                        )
        except Exception as e:
            logger.warning(f"[EXPERIENCE] Single category L2 lookup failed: {e}")

    start_t = time.time()
    try:
        extra_tiles = max(0, tiles_per_category - 2)
        max_tokens = min(600 + extra_tiles * 100, 1200)

        llm = get_llm_by_model(settings.experience_model, temperature=0.3, max_tokens=max_tokens)
        structured_llm = llm.with_structured_output(
            ExperienceOutput, include_raw=True, method="function_calling"
        )

        user_prompt = _build_user_prompt(
            destination, [category], month, budget, tier1_specialists, tiles_per_category
        )

        result = await structured_llm.ainvoke(
            [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ]
        )

        if isinstance(result, dict) and "parsed" in result:
            parsed: ExperienceOutput = result["parsed"]
            raw = result.get("raw")
            if parsed is None:
                raise ValueError("Structured output returned parsed=None")
        elif hasattr(result, "model_fields"):
            parsed = result
            raw = None
        else:
            raise ValueError(f"Unexpected structured output type: {type(result).__name__}")

        from app.planner.llm_factory import extract_token_usage

        token_usage = extract_token_usage(raw, model=settings.experience_model)
        duration_ms = int((time.time() - start_t) * 1000)
        logger.info(
            f"[EXPERIENCE] Generated {len(parsed.activities)} tiles in {duration_ms}ms"
            f" for {category}" + (f" tokens={token_usage}" if token_usage else "")
        )

    except Exception as e:
        logger.warning(f"[EXPERIENCE] Single category {category} failed: {e}")
        return []

    # Clamp durations
    for tile in parsed.activities:
        if tile.duration_hours > 4:
            tile.duration_hours = 4

    payload = [tile.model_dump() for tile in parsed.activities]
    _mem.set(cache_key, payload)

    if async_session_factory is not None:
        try:
            async with async_session_factory() as db:
                await _set_cached(
                    db,
                    cache_key,
                    payload,
                    cache_type="experience_single",
                )
        except Exception as e:
            logger.warning(f"[EXPERIENCE] Single category L2 write failed: {e}")

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
        # Rotate through real Tier-2 categories so different days get different content.
        # "activities" is not a real category — using it causes the LLM to set
        # meta.category="activities" → specialist_type="activities" → "ACTIVITIES" badge.
        _default_cats = ["cultural", "nature", "food", "tours", "shopping"]
        categories = [_default_cats[day_number % len(_default_cats)]]

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

    # ENRICH: Ground fill-day tiles with Google Places
    if all_tiles and settings.use_google_places_provider:
        try:
            from app.tile_service.google_places_provider import enrich_activities_with_places

            _cap = settings.google_places_enrichment_cap
            to_enrich = all_tiles[:_cap]
            keep_as_is = all_tiles[_cap:]
            enriched = await enrich_activities_with_places(
                to_enrich,
                destination=destination,
                path_label="tier2_enrich",
            )
            all_tiles = enriched + keep_as_is
        except Exception as e:
            logger.warning("[EXPERIENCE] fill-day enrichment failed, using LLM data: %s", e)

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


def _hydrate_generated_tier2_metadata(
    state,
    destination: str,
    categories: list[str],
    tiles: list[dict],
) -> None:
    """Populate state metadata from cached tiles so incremental generation stays consistent."""
    if state is None or not hasattr(state, "metadata") or not tiles:
        return

    tiles_by_category: dict[str, list[dict]] = {}
    for tile in tiles:
        category = (tile.get("meta") or {}).get("category")
        if not category:
            continue
        tiles_by_category.setdefault(category, []).append(tile)

    if not tiles_by_category:
        return

    generated = state.metadata.setdefault("generated_tier2_categories", {})
    dest_generated = generated.setdefault(destination, {})
    for category in categories:
        cat_tiles = tiles_by_category.get(category)
        if cat_tiles:
            dest_generated[category] = cat_tiles


async def _generate_experiences_impl(
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
            _set_tier2_generation_source(state, "cache")
            return []

        try:
            cache_key = _experience_cache_key(destination, categories, month, tiles_per_category)
        except Exception as e:
            logger.error(f"[EXPERIENCE] Cache key computation failed: {e}", exc_info=True)
            _set_tier2_generation_source(state, "cache")
            return []

        # L1: Memory cache check (fast path for exact category match)
        cached = _mem.get(cache_key)
        if cached is not None:
            _mem.increment_stat("l1_hits")
            logger.info(f"[EXPERIENCE] Cache HIT (L1): {len(cached)} tiles")
            _set_tier2_generation_source(state, "cache")
            return _clamp_tile_durations(cached)

        _mem.increment_stat("l1_misses")

        # L2: Database cache check (own session)
        logger.info("[EXPERIENCE] Checking L2 cache...")
        from app.db import _get_async_session_factory

        async_session_factory = _get_async_session_factory()

        try:
            async with async_session_factory() as db:
                l2_cached = await _get_cached(db, cache_key)
                if l2_cached is not None:
                    logger.info(f"[EXPERIENCE] Cache HIT (L2): {len(l2_cached)} tiles")
                    _set_tier2_generation_source(state, "cache")
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
            _mem.set(cache_key, all_tiles)
            _set_tier2_generation_source(state, "cache")
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
                llm = get_llm_by_model(
                    settings.experience_model, temperature=0.3, max_tokens=max_tokens
                )
                structured_llm = llm.with_structured_output(
                    ExperienceOutput, include_raw=True, method="function_calling"
                )

                user_prompt = _build_user_prompt(
                    destination, new_cats, month, budget, tier1_specialists, tiles_per_category
                )

                result = await structured_llm.ainvoke(
                    [
                        SystemMessage(content=SYSTEM_PROMPT),
                        HumanMessage(content=user_prompt),
                    ]
                )

                if isinstance(result, dict) and "parsed" in result:
                    parsed: ExperienceOutput = result["parsed"]
                    raw = result.get("raw")
                    if parsed is None:
                        raise ValueError("Structured output returned parsed=None")
                elif isinstance(result, ExperienceOutput):
                    parsed = result
                    raw = None
                else:
                    raise ValueError(f"Unexpected structured output type: {type(result).__name__}")

                from app.planner.llm_factory import extract_token_usage

                token_usage = extract_token_usage(raw, model=settings.experience_model)
                if token_usage:
                    logger.info(f"[EXPERIENCE] Batch tokens={token_usage}")

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
            _set_tier2_generation_source(state, "llm")
            return []

        # ENRICH: Ground tiles with Google Places (real coords, photos, place_id)
        if settings.use_google_places_provider:
            try:
                from app.tile_service.google_places_provider import enrich_activities_with_places

                _cap = settings.google_places_enrichment_cap
                to_enrich = new_tile_dicts[:_cap]
                keep_as_is = new_tile_dicts[_cap:]
                enriched = await enrich_activities_with_places(
                    to_enrich,
                    destination=destination,
                    path_label="tier2_enrich",
                )
                new_tile_dicts = enriched + keep_as_is
            except Exception as e:
                logger.warning("[EXPERIENCE] Places enrichment failed, using LLM data: %s", e)

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
        task = asyncio.create_task(_background_prefetch())
        _track_task(task)

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
        _mem.set(cache_key, all_tiles)

        async with async_session_factory() as db:
            await _set_cached(db, cache_key, all_tiles)

        logger.info(
            f"[EXPERIENCE] Done: {len(all_tiles)} tiles total "
            f"({len(new_tile_dicts)} new, {len(all_tiles) - len(new_tile_dicts)} existing) "
            f"cached for {destination}"
        )
        _set_tier2_generation_source(state, "llm")
        return all_tiles

    except Exception as e:
        logger.error(
            f"[EXPERIENCE] FATAL unhandled exception: {e}",
            exc_info=True,
        )
        _set_tier2_generation_source(state, "llm")
        return []


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
    Public entrypoint with singleflight dedupe for identical in-flight requests.

    This prevents prefetch and logistics from launching duplicate LLM generation
    for the same destination/category/month request. Waiters reuse the owner's
    result and hydrate state metadata after cache/shared returns.
    """
    normalized_categories = [c.strip() for c in categories if isinstance(c, str) and c.strip()]
    if not destination or not normalized_categories:
        logger.warning(f"[EXPERIENCE] Early return: dest={destination}, cats={categories}")
        return []

    cache_key = _experience_cache_key(destination, normalized_categories, month, tiles_per_category)
    owner = False

    async def _cleanup_inflight(done_task: asyncio.Task[list[dict]]) -> None:
        async with _inflight_generation_lock:
            current = _inflight_generation_tasks.get(cache_key)
            if current is done_task:
                _inflight_generation_tasks.pop(cache_key, None)
                logger.debug("[VERIFY][EXPERIENCE] inflight_cleared key=%s", cache_key)

    async with _inflight_generation_lock:
        existing = _inflight_generation_tasks.get(cache_key)
        if existing and not existing.done():
            task = existing
            logger.info("[EXPERIENCE] Singleflight wait: key=%s", cache_key)
            logger.debug("[VERIFY][EXPERIENCE] singleflight_waiter key=%s", cache_key)
        else:
            task = asyncio.create_task(
                _generate_experiences_impl(
                    destination=destination,
                    categories=normalized_categories,
                    month=month,
                    budget=budget,
                    tier1_specialists=tier1_specialists,
                    tiles_per_category=tiles_per_category,
                    state=state,
                )
            )
            _inflight_generation_tasks[cache_key] = task
            owner = True
            logger.info("[EXPERIENCE] Singleflight owner: key=%s", cache_key)
            logger.debug("[VERIFY][EXPERIENCE] singleflight_owner key=%s", cache_key)

            def _on_done(done_task: asyncio.Task[list[dict]]) -> None:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(_cleanup_inflight(done_task))
                except RuntimeError:
                    # Event loop already closed (e.g., test teardown); cleanup is best effort.
                    pass

            task.add_done_callback(_on_done)

    try:
        tiles = await asyncio.shield(task)
    except Exception as e:
        logger.warning("[EXPERIENCE] Singleflight task failed for %s: %s", cache_key, e)
        return []
    finally:
        if owner and task.done():
            async with _inflight_generation_lock:
                current = _inflight_generation_tasks.get(cache_key)
                if current is task:
                    _inflight_generation_tasks.pop(cache_key, None)

    _hydrate_generated_tier2_metadata(state, destination, normalized_categories, tiles)
    if state is not None and hasattr(state, "metadata"):
        state.metadata.setdefault("tier2_generation_source_internal", "cache")
        hydrated_count = len(
            (state.metadata.get("generated_tier2_categories", {}) or {}).get(destination, {}).keys()
        )
        logger.debug(
            "[VERIFY][EXPERIENCE] metadata_hydrated dest=%s categories=%s tracked=%s",
            destination,
            normalized_categories,
            hydrated_count,
        )
    return _clamp_tile_durations(tiles)
