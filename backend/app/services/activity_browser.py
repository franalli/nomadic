"""
Activity Browser Service — on-demand Google Places search for free/buffer days.

Called by POST /api/activities/browse when the user clicks "Browse Activities"
on a free or buffer day. Returns up to 20 activity tiles from Google Places.

Cache key:
    browse::v2::{destination}::{sorted_categories}::{month}::{center_bucket}

Caching layers:
- L1: process memory (fast hot-path)
- L2: ResponseCache persistence (cache_type="tiles")
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app.config import settings
from app.planner.hashing import make_cache_key
from app.planner.llm_factory import (
    gemini_safe_schema,
    resolve_schema_refs,
    strip_unsupported_schema_keys,
)
from app.services.cache_core import MemoryCache, l2_upsert


def _month_from_date(date_str: str | None) -> str:
    """Extract YYYY-MM from date string for cache keying."""
    if date_str and len(date_str) >= 7:
        return date_str[:7]
    return "unknown"


logger = logging.getLogger(__name__)

# Category → Google Places API types mapping
# Dynamic mapping — works for any destination worldwide
CATEGORY_TO_PLACES_TYPES: Dict[str, List[str]] = {
    "spa": ["spa", "beauty_salon"],
    "cultural": ["museum", "art_gallery", "hindu_temple", "church", "mosque"],
    "food": ["restaurant", "cafe", "bakery"],
    "nature": ["park", "campground", "national_park"],
    "shopping": ["shopping_mall", "market", "clothing_store"],
    "nightlife": ["night_club", "bar"],
    "tours": ["tourist_attraction"],
    "wellness": ["gym", "spa"],
}

# Max results per browse request (Places API cost control).
# Google Places textSearch returns up to maxResultCount=20 per call;
# values above 20 trigger a secondary diversified query automatically.
MAX_BROWSE_RESULTS = 20

# Cache tuning
L1_TTL_SECONDS = 21600  # 6h, warm enough for repeated browse usage
L1_MAX_SIZE = 256
L2_TTL_HOURS = settings.google_places_enrichment_cache_ttl_hours

# L1 memory cache and in-flight singleflight tracking.
_browse_cache = MemoryCache(maxsize=L1_MAX_SIZE, ttl=L1_TTL_SECONDS)
_browse_inflight_lock = asyncio.Lock()
_browse_inflight_tasks: dict[str, asyncio.Task[list[dict[str, Any]]]] = {}
_browse_cache_epoch = 0


async def cancel_browse_inflight() -> int:
    """Cancel all inflight browse tasks. Returns count cancelled."""
    async with _browse_inflight_lock:
        tasks = [task for task in _browse_inflight_tasks.values() if not task.done()]
        _browse_inflight_tasks.clear()
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    return len(tasks)


async def invalidate_browse_cache_state() -> int:
    """Bump browse cache generation and cancel stale inflight work."""
    global _browse_cache_epoch

    async with _browse_inflight_lock:
        _browse_cache_epoch += 1
        tasks = [task for task in _browse_inflight_tasks.values() if not task.done()]
        _browse_inflight_tasks.clear()
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    return len(tasks)


def clear_browse_cache() -> int:
    """Clear browse L1 cache. Returns count cleared."""
    count = _browse_cache.clear()
    logger.info(f"[BROWSE_CACHE] Cleared ({count} entries)")
    return count


async def _cache_browse_result_if_current(
    cache_key: str,
    tiles: list[dict[str, Any]],
    cache_epoch: int,
) -> None:
    if cache_epoch != _browse_cache_epoch:
        logger.info(
            "[BROWSE_CACHE] Skip stale write key=%s start_epoch=%s current_epoch=%s",
            cache_key,
            cache_epoch,
            _browse_cache_epoch,
        )
        return
    _browse_cache.set(cache_key, tiles)
    await _set_cached_browse(cache_key, tiles)


_PRICE_BAND_TO_LEVEL: Dict[str, int] = {
    "Free": 0,
    "$": 1,
    "$$": 2,
    "$$$": 3,
    "$$$$": 4,
}


class _BrowseEstimateItem(BaseModel):
    id: str
    duration_hours: float = Field(ge=0.5, le=8.0)
    price_band: str = Field(pattern=r"^(Free|\$|\$\$|\$\$\$|\$\$\$\$)$")


class _BrowseEstimateBatch(BaseModel):
    items: List[_BrowseEstimateItem] = Field(default_factory=list)


# Pre-resolved flat schema for Gemini-compatible structured output.
_BROWSE_ESTIMATE_FLAT_SCHEMA: dict = gemini_safe_schema(
    strip_unsupported_schema_keys(resolve_schema_refs(_BrowseEstimateBatch.model_json_schema()))
)


def _cache_key(
    destination: str,
    categories: List[str],
    month: str,
    center: Optional[tuple[float, float]],
) -> str:
    """Build a deterministic browse cache key with month-level granularity."""
    dest = destination.lower().strip() if destination else "unknown"
    sorted_cats = sorted(c.lower().strip() for c in categories if c and c.strip())
    if center is None:
        center_bucket = "auto"
    else:
        center_bucket = f"{center[0]:.3f},{center[1]:.3f}"
    return make_cache_key("browse", "v2", dest, sorted_cats, month, center_bucket)


async def _get_cached_browse(cache_key: str) -> list[dict[str, Any]] | None:
    """Read browse tiles from L2 cache and update hit counters."""
    from app.db import _get_async_session_factory
    from app.db_models import ResponseCache

    async_session_factory = _get_async_session_factory()
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                select(ResponseCache)
                .where(ResponseCache.cache_key == cache_key)
                .where(ResponseCache.cache_type == "tiles")
                .where(ResponseCache.expires_at > datetime.now(UTC))
            )
            row = result.scalar_one_or_none()
            if not row:
                return None

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

            payload = row.response_json
            if isinstance(payload, list):
                return payload
            return None
    except Exception as e:
        logger.debug("[BROWSE] L2 lookup failed key=%s err=%s", cache_key, e)
        return None


async def _set_cached_browse(cache_key: str, tiles: list[dict[str, Any]]) -> None:
    """Write browse tiles to L2 cache (best effort)."""
    from app.db import _get_async_session_factory

    async_session_factory = _get_async_session_factory()
    try:
        async with async_session_factory() as db:
            await l2_upsert(
                db,
                cache_key=cache_key,
                cache_type="tiles",
                response_json=tiles,
                ttl=timedelta(hours=L2_TTL_HOURS),
            )
    except Exception as e:
        logger.debug("[BROWSE] L2 write failed key=%s err=%s", cache_key, e)


def _duration_hours_to_label(hours: float) -> str:
    clamped = min(8.0, max(0.5, float(hours)))
    rounded = round(clamped * 2.0) / 2.0
    if float(rounded).is_integer():
        whole = int(rounded)
        return f"{whole} hour" if whole == 1 else f"{whole} hours"
    return f"{rounded:.1f} hours"


async def _enrich_tiles_with_llm(
    destination: str,
    categories: List[str],
    tiles: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, str]] = []
    for tile in tiles:
        if not isinstance(tile, dict):
            continue
        if tile.get("duration") and tile.get("price_estimate") is not None:
            continue
        tile_id = tile.get("id")
        title = tile.get("title")
        if not isinstance(tile_id, str) or not isinstance(title, str):
            continue
        candidates.append(
            {
                "id": tile_id,
                "title": title,
                "category": str(tile.get("category") or ""),
                "subtitle": str(tile.get("subtitle") or ""),
            }
        )

    if not candidates:
        return tiles

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.planner.llm_factory import get_llm_by_model

        llm = get_llm_by_model(settings.router_model, temperature=0, max_tokens=900)
        structured_llm = llm.with_structured_output(
            dict(_BROWSE_ESTIMATE_FLAT_SCHEMA),
            include_raw=True,
            method="function_calling",
        )

        prompt = (
            "Estimate typical visit duration and budget band for each activity.\n"
            "Output one item per id.\n"
            "Rules:\n"
            "- duration_hours: 0.5 to 8.0\n"
            "- price_band: one of Free, $, $$, $$$, $$$$\n"
            "  Free = public access (parks, trails, beaches, viewpoints, markets)\n"
            "  $ = under $30 (museum entry, local class, bike rental)\n"
            "  $$ = $30-80 (guided tour, cooking class, spa)\n"
            "  $$$ = $80-150 (private guide, luxury experience)\n"
            "  $$$$ = $150+ (helicopter tour, private charter)\n"
            "- Public/free activities MUST be Free.\n"
            "- Use realistic, conservative tourist defaults for the destination.\n\n"
            f"Destination: {destination}\n"
            f"Categories: {', '.join(categories) if categories else 'general'}\n"
            f"Items:\n{json.dumps(candidates, ensure_ascii=True)}"
        )
        estimates: List[_BrowseEstimateItem] = []
        last_exc: Exception | None = None
        for _attempt in range(2):
            try:
                result = await structured_llm.ainvoke(
                    [
                        SystemMessage(
                            content=(
                                "You are a travel activity estimator. "
                                "Return structured estimates only."
                            )
                        ),
                        HumanMessage(content=prompt),
                    ]
                )

                if isinstance(result, dict) and "parsed" in result:
                    parsed = result.get("parsed")
                    if parsed is None:
                        raise ValueError("Structured output returned parsed=None")
                    # Rehydrate dict → Pydantic (Gemini returns dict when using dict schema)
                    if isinstance(parsed, dict):
                        parsed = _BrowseEstimateBatch.model_validate(parsed)
                    estimates = parsed.items
                elif isinstance(result, _BrowseEstimateBatch):
                    estimates = result.items
                else:
                    raise ValueError(f"Unexpected structured output type: {type(result).__name__}")
                break
            except Exception as exc:  # noqa: PERF203
                last_exc = exc
                estimates = []
                continue

        if not estimates:
            if last_exc is not None:
                raise last_exc
            return tiles

        by_id = {item.id: item for item in estimates}
        if not by_id:
            return tiles

        enriched_count = 0
        for tile in tiles:
            if not isinstance(tile, dict):
                continue
            tile_id = tile.get("id")
            if not isinstance(tile_id, str):
                continue
            est = by_id.get(tile_id)
            if est is None:
                continue

            # price_estimate is Optional[float] — price band string goes to meta only
            if tile.get("price_level") is None:
                tile["price_level"] = _PRICE_BAND_TO_LEVEL.get(est.price_band)
            if not tile.get("duration"):
                tile["duration"] = _duration_hours_to_label(est.duration_hours)
                enriched_count += 1

            meta = tile.get("meta")
            meta_dict = dict(meta) if isinstance(meta, dict) else {}
            if meta_dict.get("duration_hours") is None:
                meta_dict["duration_hours"] = round(float(est.duration_hours), 1)
            if not meta_dict.get("price_band"):
                meta_dict["price_band"] = est.price_band
            tile["meta"] = meta_dict

        if enriched_count:
            logger.debug(
                "[BROWSE] LLM enriched %d fields across %d tiles",
                enriched_count,
                len(tiles),
            )
    except Exception as exc:
        logger.debug("[BROWSE] LLM enrichment skipped: %s", exc)

    return tiles


def _humanize_type(place_type: str) -> str:
    """Convert a Google Places type string to human-readable label."""
    return place_type.replace("_", " ").title()


def _placeholder_category_for_browse(category: str, primary_type: str) -> str:
    """Map browse category/primaryType to placeholder image category.

    Phase 1: match against the user-selected *browse category* string.
    Phase 2: fall back to shared primary_type token matching (same dict used
    by google_places_provider._placeholder_category_for_place_type).
    """
    from app.tile_service.google_places_provider import PLACE_TYPE_CATEGORY_TOKENS

    c = (category or "").strip().lower()

    # Phase 1 — user-selected browse category wins over primary type ambiguity.
    if any(token in c for token in ["food", "cooking"]):
        return "cooking"
    if any(token in c for token in ["cultural", "culture", "tours"]):
        return "culture"
    if any(token in c for token in ["nightlife", "night"]):
        return "nightlife"
    if any(token in c for token in ["spa", "wellness", "yoga"]):
        return "wellness"
    if any(token in c for token in ["hiking", "trail", "mountain", "trek"]):
        return "hiking"
    if any(token in c for token in ["ski", "snow"]):
        return "skiing"
    if any(token in c for token in ["dive", "snorkel", "reef", "scuba"]):
        return "diving"
    if any(token in c for token in ["nature", "park", "garden", "zoo", "beach", "camp"]):
        return "adventure"

    # Phase 2 — shared primary_type token matching.
    p = (primary_type or "").strip().lower()
    if p:
        for cat, tokens in PLACE_TYPE_CATEGORY_TOKENS.items():
            if any(token in p for token in tokens):
                return cat
    return "activity"


def _place_to_tile(place: Dict[str, Any], category: str) -> Dict[str, Any]:
    """Transform a Google Places place dict into a browse tile dict."""
    from app.placeholders import get_placeholder_image
    from app.tile_service.google_places_provider import _get_photo_url

    place_id = place.get("id", "")
    tile_id_suffix = category.strip().lower() if category else "unknown"
    tile_id = (
        f"browse_{place_id}_{tile_id_suffix}" if place_id else f"browse_unknown_{tile_id_suffix}"
    )
    name = place.get("displayName", {}).get("text", "Unknown")
    location = place.get("location", {})
    lat = location.get("latitude")
    lng = location.get("longitude")
    address = place.get("formattedAddress", "")
    primary_type = place.get("primaryType", category)
    # NOTE: rating, userRatingCount, priceLevel, and editorialSummary are
    # Pro-tier fields not included in our field mask — always None/missing.
    # Price estimation is handled by LLM enrichment (_enrich_tiles_with_llm).
    price_estimate = 35.0  # moderate default; refined by LLM enrichment
    price_level = 2

    photos = place.get("photos", [])
    image_url = None
    photo_name = None
    if photos:
        photo_name = photos[0].get("name", "")
        image_url = _get_photo_url(photo_name)
    if not image_url:
        image_url = get_placeholder_image(
            category=_placeholder_category_for_browse(category, primary_type),
            seed=(place_id or name),
        )

    maps_uri = place.get("googleMapsUri")
    return {
        "id": tile_id,
        "type": "activity",
        "title": name,
        "subtitle": _humanize_type(primary_type),
        "description": "",
        "image_url": image_url,
        "rating": None,
        "review_count": None,
        "user_ratings_count": None,
        "google_place_id": place_id,
        "deeplink": maps_uri,
        "location_label": address,
        "geo": {"lat": lat, "lng": lng} if lat and lng else None,
        "price_estimate": price_estimate,
        "price_level": price_level,
        "source": "google_places",
        "provider": "google_places",
        "category": category,
        "tags": [primary_type],
        "place_id": place_id,
        "maps_uri": maps_uri,
        "photo_name": photo_name,
    }


async def _browse_activities_impl(
    destination: str,
    center: Optional[tuple[float, float]],
    valid_categories: list[str],
    cache_key: str,
    max_results: int = MAX_BROWSE_RESULTS,
    cache_epoch: int = 0,
) -> list[dict[str, Any]]:
    from app.tile_service.google_places_provider import (
        _call_places_api_async,
        _geocode_destination_async,
        get_google_places_usage_counters,
        record_google_places_usage,
    )

    cached_l1 = _browse_cache.get(cache_key)
    if cached_l1 is not None:
        record_google_places_usage("browse", "cache_hit", layer="l1")
        logger.debug("[BROWSE] Cache HIT (L1) key=%s", cache_key)
        return cached_l1

    record_google_places_usage("browse", "cache_miss", layer="l1")
    cached_l2 = await _get_cached_browse(cache_key)
    if cached_l2 is not None:
        _browse_cache.set(cache_key, cached_l2)
        record_google_places_usage("browse", "cache_hit", layer="l2")
        logger.debug("[BROWSE] Cache HIT (L2) key=%s", cache_key)
        return cached_l2

    record_google_places_usage("browse", "cache_miss", layer="l2")

    # Try partner tiles: Viator, then GYG supplement (real pricing, images, deeplinks)
    partner_tiles: List[Dict[str, Any]] = []
    if settings.viator_enabled and settings.viator_api_key:
        try:
            from app.services.viator_provider import search_viator_for_destination

            viator_tiles = await search_viator_for_destination(
                destination=destination,
                currency="USD",
                count=max_results,
            )
            if viator_tiles:
                viator_tiles = await _enrich_tiles_with_llm(
                    destination, valid_categories, viator_tiles
                )
                partner_tiles = viator_tiles
                if len(partner_tiles) >= max_results:
                    _browse_cache.set(cache_key, partner_tiles)
                    await _set_cached_browse(cache_key, partner_tiles)
                    logger.debug(
                        "[BROWSE] Viator returned %d tiles for %s", len(partner_tiles), destination
                    )
                    return partner_tiles
                # Fewer than requested — fall through to supplement
                logger.debug(
                    "[BROWSE] Viator returned %d/%d tiles for %s, supplementing",
                    len(partner_tiles),
                    max_results,
                    destination,
                )
        except Exception as e:
            logger.debug("[BROWSE] Viator browse failed, falling back: %s", e)

    # Try GYG supplement (when Viator returned fewer than max_results)
    if settings.get_your_guide_enabled and settings.get_your_guide_api_key:
        try:
            from app.services.gyg_provider import search_gyg_for_destination

            gyg_tiles = await search_gyg_for_destination(
                destination=destination,
                currency="USD",
                count=max_results,
            )
            if gyg_tiles:
                # Dedupe: skip GYG tiles whose titles already appear in partner results
                existing_titles = {t.get("title", "").lower() for t in partner_tiles}
                gyg_tiles = [
                    t for t in gyg_tiles if t.get("title", "").lower() not in existing_titles
                ]
                gyg_tiles = await _enrich_tiles_with_llm(destination, valid_categories, gyg_tiles)
                partner_tiles = partner_tiles + gyg_tiles
                if len(partner_tiles) >= max_results:
                    await _cache_browse_result_if_current(
                        cache_key,
                        partner_tiles[:max_results],
                        cache_epoch,
                    )
                    logger.debug(
                        "[BROWSE] Viator+GYG returned %d tiles for %s",
                        len(partner_tiles),
                        destination,
                    )
                    return partner_tiles[:max_results]
                logger.debug(
                    "[BROWSE] Viator+GYG returned %d/%d tiles for %s, supplementing with GP",
                    len(partner_tiles),
                    max_results,
                    destination,
                )
        except Exception as e:
            logger.debug("[BROWSE] GYG browse failed: %s", e)

    # Resolve geo center
    geo = center
    if not geo:
        geo = await _geocode_destination_async(destination)

    if not settings.google_maps_api_key:
        record_google_places_usage("browse", "error", reason="missing_api_key")
        if partner_tiles:
            logger.warning("[BROWSE] No Google Maps API key — returning partner-only results")
            await _cache_browse_result_if_current(cache_key, partner_tiles, cache_epoch)
            return partner_tiles
        logger.warning("[BROWSE] No Google Maps API key — returning empty results")
        return []

    usage_before = get_google_places_usage_counters().get("browse", {})
    before_errors = int(usage_before.get("errors", 0))
    before_quota = int(usage_before.get("quota_exhausted", 0))

    # Build reverse mapping: Google Places primaryType → list of browse categories
    type_to_categories: Dict[str, List[str]] = {}
    for cat in valid_categories:
        for place_type in CATEGORY_TO_PLACES_TYPES[cat]:
            owners = type_to_categories.setdefault(place_type, [])
            if cat not in owners:
                owners.append(cat)

    # Single broad query instead of per-type parallel searches (1 API call vs 6-8)
    broad_query = f"popular {', '.join(valid_categories)} things to do in {destination}"
    had_search_errors = False
    try:
        places = await _call_places_api_async(
            query=broad_query,
            included_type=None,
            max_results=max_results,
            geo=geo,
            path_label="browse",
        )
    except Exception as e:
        had_search_errors = True
        logger.warning("[BROWSE] Broad search failed: %s", e)
        places = []

    # Post-classify each result by matching primaryType to category owners.
    # Unmatched types round-robin across requested categories for even distribution.
    _rr_idx = 0
    seen_keys: set[tuple[str, str]] = set()
    tiles: List[Dict[str, Any]] = []
    for place in places:
        primary_type = place.get("primaryType", "")
        matched_categories = type_to_categories.get(primary_type)
        if not matched_categories:
            matched_categories = [valid_categories[_rr_idx % len(valid_categories)]]
            _rr_idx += 1
        for category in matched_categories:
            tile = _place_to_tile(place, category)
            pid = tile.get("place_id", "")
            dedupe_key = (pid, category) if pid else (str(tile.get("id", "")), category)
            if dedupe_key not in seen_keys:
                seen_keys.add(dedupe_key)
                tiles.append(tile)
            if len(tiles) >= max_results:
                break
        if len(tiles) >= max_results:
            break

    tiles = await _enrich_tiles_with_llm(destination, valid_categories, tiles)

    # Merge partner tiles (real pricing) with GP supplement tiles
    if partner_tiles:
        partner_titles = {t.get("title", "").lower().strip() for t in partner_tiles}
        gp_deduped = [t for t in tiles if t.get("title", "").lower().strip() not in partner_titles]
        tiles = partner_tiles + gp_deduped
    tiles = tiles[:max_results]

    usage_after = get_google_places_usage_counters().get("browse", {})
    had_places_failures = (
        had_search_errors
        or int(usage_after.get("errors", 0)) > before_errors
        or int(usage_after.get("quota_exhausted", 0)) > before_quota
    )

    # Avoid poisoning cache with empty results caused by transient upstream failures.
    if not tiles and had_places_failures:
        logger.debug("[BROWSE] Skip caching empty result due Places failure key=%s", cache_key)
        return tiles

    # Cache result
    await _cache_browse_result_if_current(cache_key, tiles, cache_epoch)

    logger.debug("[BROWSE] Found %d tiles for %s", len(tiles), destination)
    return tiles


async def browse_activities(
    destination: str,
    center: Optional[tuple[float, float]],
    categories: List[str],
    date: Optional[str] = None,
    max_results: int = MAX_BROWSE_RESULTS,
) -> List[Dict[str, Any]]:
    """
    Search Google Places for activities in the given categories near the destination.

    Args:
        destination: Destination name (e.g. "Bali")
        center: (lat, lng) tuple for search center, or None to geocode destination
        categories: List of category keys from CATEGORY_TO_PLACES_TYPES
        date: ISO date string (used for month-level cache key)
        max_results: Maximum number of tiles to return (default MAX_BROWSE_RESULTS)

    Returns:
        List of tile dicts (up to max_results)
    """
    month = _month_from_date(date)

    # Filter to known categories
    valid_categories = [c for c in categories if c in CATEGORY_TO_PLACES_TYPES]
    if not valid_categories:
        valid_categories = ["cultural", "food", "nature"]

    # Include max_results in cache key when non-default to avoid stale short results
    cache_key_suffix = f":mr{max_results}" if max_results != MAX_BROWSE_RESULTS else ""
    cache_key = _cache_key(destination, valid_categories, month, center) + cache_key_suffix

    # Fast path: L1 hit (before singleflight lock).
    cached = _browse_cache.get(cache_key)
    if cached is not None:
        from app.tile_service.google_places_provider import record_google_places_usage

        record_google_places_usage("browse", "cache_hit", layer="l1")
        logger.debug("[BROWSE] Cache HIT for %s (%s)", destination, valid_categories)
        return cached

    owner = False

    async def _cleanup_inflight(done_task: asyncio.Task[list[dict[str, Any]]]) -> None:
        async with _browse_inflight_lock:
            current = _browse_inflight_tasks.get(cache_key)
            if current is done_task:
                _browse_inflight_tasks.pop(cache_key, None)
                logger.debug("[VERIFY][BROWSE] inflight_cleared key=%s", cache_key)

    async with _browse_inflight_lock:
        existing = _browse_inflight_tasks.get(cache_key)
        if existing and not existing.done():
            task = existing
            logger.debug("[VERIFY][BROWSE] singleflight_waiter key=%s", cache_key)
        else:
            cache_epoch = _browse_cache_epoch
            task = asyncio.create_task(
                _browse_activities_impl(
                    destination,
                    center,
                    valid_categories,
                    cache_key,
                    max_results,
                    cache_epoch,
                )
            )
            _browse_inflight_tasks[cache_key] = task
            owner = True
            logger.debug("[VERIFY][BROWSE] singleflight_owner key=%s", cache_key)

            def _on_done(done_task: asyncio.Task[list[dict[str, Any]]]) -> None:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(_cleanup_inflight(done_task))
                except RuntimeError:
                    pass

            task.add_done_callback(_on_done)

    try:
        return await asyncio.shield(task)
    except Exception as e:
        logger.warning("[BROWSE] Singleflight task failed key=%s err=%s", cache_key, e)
        return []
    finally:
        if owner and task.done():
            async with _browse_inflight_lock:
                current = _browse_inflight_tasks.get(cache_key)
                if current is task:
                    _browse_inflight_tasks.pop(cache_key, None)
