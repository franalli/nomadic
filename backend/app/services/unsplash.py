# backend/app/services/unsplash.py
"""
Unsplash image service for dynamic destination images.

Features:
- Fetches multiple images per destination for unique tile/branch imagery
- Two-tier caching: in-memory (runtime) + database (persistent)
- Stores image_id, not raw URLs (best practice)
- Falls back to deterministic Unsplash placeholders on API failure
- Full production attribution support (photographer, Unsplash link, download tracking)
"""

import asyncio
import logging
import threading
import time
from datetime import UTC, datetime
from typing import List, Optional

import httpx
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.placeholders import get_placeholder_image
from app.planner.hashing import make_cache_key
from app.services.cache_core import MemoryCache
from app.services.unsplash_queries import get_query_for_destination

logger = logging.getLogger(__name__)

# In-memory cache for hot destinations (avoids DB hits in same session)
# Key format: "unsplash::v2::{destination}[::{activity}]::variant-{n}"
# Capped at 512 entries with 2h TTL — MemoryCache provides internal RLock.
_memory_cache: MemoryCache = MemoryCache(maxsize=512, ttl=7200)
_memory_cache_lock = asyncio.Lock()
# Threading lock for sync access paths (get_cached_image_url, get_image_url_sync,
# clear_memory_cache, get_memory_cache_stats). The asyncio.Lock above only
# protects async callers; sync functions called from thread-pool executors need this.
_sync_lock = threading.RLock()
# In-flight fetch dedupe (destination/activity scoped).
_inflight_fetches: dict[str, asyncio.Task[List["UnsplashImage"]]] = {}
_inflight_fetches_lock = asyncio.Lock()
# Destination-level prefetch coalescing.
_prefetch_destination_inflight: dict[str, asyncio.Task[List["UnsplashImage"]]] = {}
# Cooldown map for prefetch-only failures to reduce timeout churn.
_prefetch_failure_until: dict[str, float] = {}
_prefetch_timeout_streak: dict[str, int] = {}
_prefetch_dest_failure_until: dict[str, float] = {}
_prefetch_cooldown_lock = asyncio.Lock()

# Number of image variants to fetch per destination
NUM_VARIANTS = 6

# Unsplash request resiliency settings (for hero banner reliability).
UNSPLASH_REQUEST_TIMEOUT_SECONDS = settings.unsplash_request_timeout_seconds
UNSPLASH_MAX_RETRIES = settings.unsplash_max_retries
UNSPLASH_RETRY_BASE_DELAY_SECONDS = 0.25
UNSPLASH_PREFETCH_TIMEOUT_SECONDS = settings.unsplash_prefetch_timeout_seconds
UNSPLASH_PREFETCH_MAX_RETRIES = settings.unsplash_prefetch_max_retries
UNSPLASH_PREFETCH_FAILURE_COOLDOWN_SECONDS = settings.unsplash_prefetch_failure_cooldown_seconds
UNSPLASH_PREFETCH_DEST_COOLDOWN_SECONDS = settings.unsplash_prefetch_dest_cooldown_seconds
UNSPLASH_PREFETCH_STREAK_THRESHOLD = settings.unsplash_prefetch_streak_threshold
_MAX_COOLDOWN_ENTRIES = 500  # Safety valve — way beyond realistic traffic

_http_client: httpx.AsyncClient | None = None
_http_init_lock = asyncio.Lock()


async def _get_http_client(timeout: float = UNSPLASH_REQUEST_TIMEOUT_SECONDS) -> httpx.AsyncClient:
    """Get or create shared HTTP client for connection reuse."""
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        return _http_client
    async with _http_init_lock:
        if _http_client is None or _http_client.is_closed:
            _http_client = httpx.AsyncClient(timeout=timeout)
        return _http_client


async def close_http_client() -> None:
    """Close the shared HTTP client. Call during shutdown."""
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


def _prune_expired_cooldowns() -> int:
    """Remove expired entries from cooldown dicts. Returns count removed."""
    now = time.monotonic()
    pruned = 0
    for key in list(_prefetch_failure_until):
        if _prefetch_failure_until[key] <= now:
            del _prefetch_failure_until[key]
            pruned += 1
    # Track which dest-level cooldowns were just removed (fully expired)
    expired_dests: set[str] = set()
    for key in list(_prefetch_dest_failure_until):
        if _prefetch_dest_failure_until[key] <= now:
            del _prefetch_dest_failure_until[key]
            expired_dests.add(key)
            pruned += 1
    # Only prune streaks for destinations whose dest-level cooldown has expired.
    # Streaks still accumulating (no dest cooldown yet) must be kept.
    for dest in list(_prefetch_timeout_streak):
        if dest in expired_dests:
            del _prefetch_timeout_streak[dest]
            pruned += 1
    # Hard cap: evict oldest entries if dicts grow beyond safety valve
    for d in (_prefetch_failure_until, _prefetch_dest_failure_until):
        if len(d) > _MAX_COOLDOWN_ENTRIES:
            sorted_keys = sorted(d, key=d.get)
            for k in sorted_keys[: len(d) - _MAX_COOLDOWN_ENTRIES]:
                del d[k]
                pruned += 1
    if len(_prefetch_timeout_streak) > _MAX_COOLDOWN_ENTRIES:
        _prefetch_timeout_streak.clear()
        pruned += 1
    return pruned


def _cache_key(destination: str, variant: int, activities: list[str] | None = None) -> str:
    """Generate namespaced cache key for destination/activity variant entries."""
    normalized = destination.lower().strip()
    parts: list[str] = ["unsplash", "v2", normalized]
    # Only use activity in key if we have a non-empty activity string.
    if activities and len(activities) > 0:
        activity = activities[0].lower().strip()
        if activity:
            parts.append(activity)
    parts.append(f"variant-{variant}")
    return make_cache_key(*parts)


def _fetch_key(destination: str, activities: list[str] | None = None) -> str:
    """Key for coalescing concurrent Unsplash API fetches."""
    normalized = destination.lower().strip()
    if activities and len(activities) > 0:
        activity = activities[0].lower().strip()
        if activity:
            return f"{normalized}:{activity}"
    return normalized


def _destination_key(destination: str) -> str:
    return destination.lower().strip()


async def _record_prefetch_outcome(
    *,
    key: str,
    destination: str,
    succeeded: bool,
) -> None:
    async with _prefetch_cooldown_lock:
        if succeeded:
            _prefetch_failure_until.pop(key, None)
            _prefetch_timeout_streak.pop(destination, None)
            if _prefetch_dest_failure_until.pop(destination, None) is not None:
                logger.debug("[VERIFY][UNSPLASH] dest_cooldown_cleared dest=%s", destination)
            logger.debug("[VERIFY][UNSPLASH] cooldown_cleared key=%s streak=0", key)
            return

        _prefetch_failure_until[key] = time.monotonic() + UNSPLASH_PREFETCH_FAILURE_COOLDOWN_SECONDS
        streak = _prefetch_timeout_streak.get(destination, 0) + 1
        _prefetch_timeout_streak[destination] = streak
        logger.debug(
            "[VERIFY][UNSPLASH] cooldown_set key=%s streak=%s seconds=%.1f",
            key,
            streak,
            UNSPLASH_PREFETCH_FAILURE_COOLDOWN_SECONDS,
        )
        if streak >= max(1, UNSPLASH_PREFETCH_STREAK_THRESHOLD):
            _prefetch_dest_failure_until[destination] = (
                time.monotonic() + UNSPLASH_PREFETCH_DEST_COOLDOWN_SECONDS
            )
            logger.debug(
                "[VERIFY][UNSPLASH] dest_cooldown_set dest=%s seconds=%.1f streak=%s",
                destination,
                UNSPLASH_PREFETCH_DEST_COOLDOWN_SECONDS,
                streak,
            )


def _candidate_cache_keys(
    destination: str, variant: int, activities: list[str] | None = None
) -> list[str]:
    """
    Build deterministic cache lookup order for a destination/variant lookup.

    Order:
    1. Exact key for the requested scope.
    2. If activity-scoped request: base destination key.
    3. Any activity-scoped sibling keys for same destination/variant.
    """
    normalized = destination.lower().strip()
    exact_key = _cache_key(destination, variant, activities)
    base_key = _cache_key(destination, variant)
    prefix = make_cache_key("unsplash", "v2", normalized)
    suffix = f"::variant-{variant}"

    activity_keys = sorted(
        key
        for key in _memory_cache.keys()
        if key.startswith(f"{prefix}::") and key.endswith(suffix) and len(key.split("::")) == 5
    )

    ordered: list[str] = [exact_key]
    if activities:
        ordered.append(base_key)
    ordered.extend(activity_keys)

    deduped: list[str] = []
    seen: set[str] = set()
    for key in ordered:
        if key not in seen:
            deduped.append(key)
            seen.add(key)
    return deduped


class UnsplashImage(BaseModel):
    """Cached Unsplash image data with full attribution info."""

    image_id: str
    photographer: Optional[str] = None
    photographer_url: Optional[str] = None
    # Required for production attribution
    unsplash_url: Optional[str] = None  # Image page on Unsplash
    download_location: Optional[str] = None  # API endpoint for download tracking


def build_image_url(image_id: str, width: int = 800, height: int = 600) -> str:
    """
    Construct Unsplash image URL from image_id.

    Allows dynamic sizing without storing full URLs.
    """
    return f"https://images.unsplash.com/photo-{image_id}?w={width}&h={height}&fit=crop&auto=format&q=80"


def _get_unsplash_placeholder_fallback(
    destination: str, variant: int = 0, width: int = 800, height: int = 600
) -> str:
    """
    Generate deterministic Unsplash placeholder fallback URL.

    Uses destination + variant as seed for consistent but unique images.
    """
    seed = destination.lower().replace(" ", "-").replace(",", "")
    if variant > 0:
        seed = f"{seed}-{variant}"
    return get_placeholder_image(
        category="destination",
        seed=seed,
        width=width,
        height=height,
    )


def _extract_image_from_photo(photo: dict) -> Optional[UnsplashImage]:
    """Extract UnsplashImage from API response photo object."""
    # Extract image ID from the photo URL
    # URL format: https://images.unsplash.com/photo-{id}?...
    raw_url = photo.get("urls", {}).get("raw", "")
    image_id = ""
    if "photo-" in raw_url:
        # Extract ID: everything between "photo-" and "?"
        start = raw_url.index("photo-") + 6
        end = raw_url.index("?") if "?" in raw_url else len(raw_url)
        image_id = raw_url[start:end]

    if not image_id:
        # Fallback: use the photo's ID directly
        image_id = photo.get("id", "")

    if not image_id:
        return None

    # Extract all attribution fields
    user = photo.get("user", {})
    links = photo.get("links", {})

    return UnsplashImage(
        image_id=image_id,
        photographer=user.get("name"),
        photographer_url=user.get("links", {}).get("html"),
        unsplash_url=links.get("html"),
        download_location=links.get("download_location"),
    )


async def _fetch_variants_from_unsplash_once(
    destination: str,
    activities: list[str] | None = None,
    *,
    prefetch: bool = False,
) -> List[UnsplashImage]:
    """
    Fetch multiple images from Unsplash API for a destination.

    Returns list of UnsplashImage (up to NUM_VARIANTS).
    Returns empty list on any error (rate limit, network, invalid response).
    """
    api_key = settings.unsplash_access_key
    if not api_key:
        logger.warning("[UNSPLASH-API] UNSPLASH_ACCESS_KEY not configured!")
        return []

    logger.info(f"[UNSPLASH-API] API key configured (length={len(api_key)})")
    query = get_query_for_destination(destination, activities)
    logger.info(f"[UNSPLASH-API] Query for '{destination}' (activities={activities}): {query}")

    timeout_seconds = (
        UNSPLASH_PREFETCH_TIMEOUT_SECONDS if prefetch else UNSPLASH_REQUEST_TIMEOUT_SECONDS
    )
    max_retries = UNSPLASH_PREFETCH_MAX_RETRIES if prefetch else UNSPLASH_MAX_RETRIES

    for attempt in range(max_retries + 1):
        try:
            client = await _get_http_client(timeout=timeout_seconds)
            response = await client.get(
                "https://api.unsplash.com/search/photos",
                params={
                    "query": query,
                    "per_page": NUM_VARIANTS,
                    "orientation": "landscape",
                    "order_by": "relevant",
                    "content_filter": "high",
                },
                headers={
                    "Authorization": f"Client-ID {api_key}",
                },
            )

            logger.info(
                f"[UNSPLASH-API] Response status={response.status_code} attempt={attempt + 1}"
            )

            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])
                logger.info(f"[UNSPLASH-API] Got {len(results)} results for {destination}")

                # Broader-query retry: if the initial (possibly specific) query
                # returned nothing, try once more with a simple destination query.
                if not results:
                    broader = f"{destination} travel landmark"
                    logger.info(
                        "[UNSPLASH-API] 0 results for '%s', retrying broader query: '%s'",
                        query,
                        broader,
                    )
                    resp2 = await client.get(
                        "https://api.unsplash.com/search/photos",
                        params={
                            "query": broader,
                            "per_page": NUM_VARIANTS,
                            "orientation": "landscape",
                            "order_by": "relevant",
                            "content_filter": "high",
                        },
                        headers={
                            "Authorization": f"Client-ID {api_key}",
                        },
                    )
                    if resp2.status_code == 200:
                        results = resp2.json().get("results", [])
                        logger.info(
                            "[UNSPLASH-API] Broader retry got %d results for %s",
                            len(results),
                            destination,
                        )

                if not results:
                    logger.info(f"No Unsplash results for query: {query}")
                    return []

                images = []
                for photo in results:
                    img = _extract_image_from_photo(photo)
                    if img:
                        images.append(img)

                logger.info(
                    f"[UNSPLASH-API] Extracted {len(images)} valid images for {destination}"
                )
                return images

            # 403 indicates auth/rate limits; retries usually won't help.
            if response.status_code == 403:
                logger.warning("[UNSPLASH-API] Rate limit exceeded (403)")
                return []

            should_retry = response.status_code >= 500 or response.status_code in {408, 425, 429}
            logger.warning(
                f"[UNSPLASH-API] Error status: {response.status_code}, body: {response.text[:200]}"
            )
            if not should_retry or attempt >= max_retries:
                return []

        except httpx.TimeoutException:
            logger.warning(
                "[UNSPLASH-API] Timeout for destination=%s attempt=%s mode=%s",
                destination,
                attempt + 1,
                "prefetch" if prefetch else "interactive",
            )
            if attempt >= max_retries:
                return []
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"[UNSPLASH-API] Error for destination={destination} attempt={attempt + 1}: {e}"
            )
            if attempt >= max_retries:
                return []

        delay = UNSPLASH_RETRY_BASE_DELAY_SECONDS * (2**attempt)
        logger.info(f"[UNSPLASH-API] Retrying in {delay:.2f}s (attempt {attempt + 2})")
        await asyncio.sleep(delay)

    return []


async def _fetch_variants_from_unsplash(
    destination: str,
    activities: list[str] | None = None,
    *,
    prefetch: bool = False,
) -> List[UnsplashImage]:
    """
    Fetch multiple images from Unsplash API with in-flight dedupe.

    Concurrent requests for the same destination/activity share one network call.
    """
    key = _fetch_key(destination, activities)
    destination_key = _destination_key(destination)
    now = time.monotonic()

    if prefetch:
        async with _prefetch_cooldown_lock:
            # Periodic pruning under lock (cheap, ~O(n) on small dicts)
            _prune_expired_cooldowns()
            dest_until = _prefetch_dest_failure_until.get(destination_key)
            until = _prefetch_failure_until.get(key)

        if dest_until and dest_until > now:
            logger.debug(
                "[VERIFY][UNSPLASH] cooldown_skip key=%s dest=%s remaining_s=%.1f",
                key,
                destination_key,
                dest_until - now,
            )
            return []

        if until and until > now:
            logger.debug(
                "[VERIFY][UNSPLASH] cooldown_skip key=%s remaining_s=%.1f",
                key,
                until - now,
            )
            return []

        owner = False
        async with _inflight_fetches_lock:
            existing = _prefetch_destination_inflight.get(destination_key)
            if existing and not existing.done():
                task = existing
                logger.debug(
                    "[VERIFY][UNSPLASH] singleflight_waiter key=%s dest=%s",
                    key,
                    destination_key,
                )
            else:
                task = asyncio.create_task(
                    _fetch_variants_from_unsplash_once(destination, None, prefetch=True)
                )
                _prefetch_destination_inflight[destination_key] = task
                owner = True
                logger.debug(
                    "[VERIFY][UNSPLASH] singleflight_owner key=%s dest=%s",
                    key,
                    destination_key,
                )

        try:
            result = await asyncio.shield(task)
            if owner:
                await _record_prefetch_outcome(
                    key=key,
                    destination=destination_key,
                    succeeded=bool(result),
                )
            return result
        finally:
            if owner:
                async with _inflight_fetches_lock:
                    current = _prefetch_destination_inflight.get(destination_key)
                    if current is task:
                        _prefetch_destination_inflight.pop(destination_key, None)
                        logger.debug(
                            "[VERIFY][UNSPLASH] inflight_cleared dest=%s",
                            destination_key,
                        )

    owner = False
    joined_prefetch = False
    async with _inflight_fetches_lock:
        prefetch_task = _prefetch_destination_inflight.get(destination_key)
        if prefetch_task and not prefetch_task.done():
            task = prefetch_task
            joined_prefetch = True
            logger.info(
                "[UNSPLASH-API] In-flight dedupe hit for key=%s via destination prefetch",
                key,
            )
            logger.debug(
                "[VERIFY][UNSPLASH] singleflight_waiter key=%s dest=%s",
                key,
                destination_key,
            )
        else:
            existing = _inflight_fetches.get(key)
            if existing and not existing.done():
                task = existing
                logger.info("[UNSPLASH-API] In-flight dedupe hit for key=%s", key)
                logger.debug("[VERIFY][UNSPLASH] singleflight_waiter key=%s", key)
            else:
                task = asyncio.create_task(
                    _fetch_variants_from_unsplash_once(destination, activities, prefetch=False)
                )
                _inflight_fetches[key] = task
                owner = True
                logger.debug("[VERIFY][UNSPLASH] singleflight_owner key=%s", key)

    try:
        return await asyncio.shield(task)
    finally:
        if owner and not joined_prefetch:
            async with _inflight_fetches_lock:
                current = _inflight_fetches.get(key)
                if current is task:
                    _inflight_fetches.pop(key, None)
                    logger.debug("[VERIFY][UNSPLASH] inflight_cleared key=%s", key)


def _db_destination_key(destination: str, activities: list[str] | None = None) -> str:
    """Build DB destination key, encoding activity for cache partitioning.

    Returns e.g. "bali" or "bali:diving" — fits in String(256) PK.
    """
    normalized = destination.lower().strip()
    if activities and len(activities) > 0:
        activity = activities[0].lower().strip()
        if activity:
            return f"{normalized}:{activity}"
    return normalized


async def _get_from_db_cache(
    db: AsyncSession,
    destination: str,
    variant: int = 0,
    activities: list[str] | None = None,
) -> Optional[UnsplashImage]:
    """Check database cache for existing image variant."""
    from app.db_models import UnsplashImageCache

    db_key = _db_destination_key(destination, activities)
    logger.info(f"[UNSPLASH-DB] Checking DB cache for: {db_key}:{variant}")

    try:
        result = await db.execute(
            select(UnsplashImageCache).where(
                UnsplashImageCache.destination == db_key,
                UnsplashImageCache.variant == variant,
            )
        )
        cached = result.scalar_one_or_none()
    except Exception as e:
        logger.warning(f"[UNSPLASH-DB] Query failed (table may not exist): {e}")
        return None

    if cached:
        return UnsplashImage(
            image_id=cached.image_id,
            photographer=cached.photographer,
            photographer_url=cached.photographer_url,
            unsplash_url=cached.unsplash_url,
            download_location=cached.download_location,
        )
    return None


async def _get_all_variants_from_db(
    db: AsyncSession,
    destination: str,
    activities: list[str] | None = None,
) -> List[UnsplashImage]:
    """Get all cached variants for a destination from DB."""
    from app.db_models import UnsplashImageCache

    db_key = _db_destination_key(destination, activities)
    logger.info(f"[UNSPLASH-DB] Checking DB for all variants of: {db_key}")

    try:
        result = await db.execute(
            select(UnsplashImageCache)
            .where(UnsplashImageCache.destination == db_key)
            .order_by(UnsplashImageCache.variant)
        )
        cached_list = list(result.scalars().all())
    except Exception as e:
        logger.warning(f"[UNSPLASH-DB] Query failed (table may not exist): {e}")
        return []

    images = []
    for cached in cached_list:
        images.append(
            UnsplashImage(
                image_id=cached.image_id,
                photographer=cached.photographer,
                photographer_url=cached.photographer_url,
                unsplash_url=cached.unsplash_url,
                download_location=cached.download_location,
            )
        )
    return images


async def _save_all_variants_to_db(
    db: AsyncSession,
    destination: str,
    images: List[UnsplashImage],
    activities: list[str] | None = None,
) -> None:
    """Save all image variants to database cache in one commit."""
    from app.db_models import UnsplashImageCache

    db_key = _db_destination_key(destination, activities)
    logger.info(f"[UNSPLASH-DB] Saving {len(images)} variants to DB for: {db_key}")

    try:
        for variant, image in enumerate(images):
            result = await db.execute(
                select(UnsplashImageCache).where(
                    UnsplashImageCache.destination == db_key,
                    UnsplashImageCache.variant == variant,
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.image_id = image.image_id
                existing.photographer = image.photographer
                existing.photographer_url = image.photographer_url
                existing.unsplash_url = image.unsplash_url
                existing.download_location = image.download_location
                existing.cached_at = datetime.now(UTC)
            else:
                cache_entry = UnsplashImageCache(
                    destination=db_key,
                    variant=variant,
                    image_id=image.image_id,
                    photographer=image.photographer,
                    photographer_url=image.photographer_url,
                    unsplash_url=image.unsplash_url,
                    download_location=image.download_location,
                )
                db.add(cache_entry)

        await db.commit()
        logger.info(f"[UNSPLASH-DB] Saved {len(images)} variants for {db_key}")
    except Exception as e:
        logger.warning(f"[UNSPLASH-DB] Save failed: {e}")
        await db.rollback()


async def prefetch_destination_images(
    destination: str,
    db: Optional[AsyncSession] = None,
    activities: list[str] | None = None,
) -> int:
    """
    Prefetch all image variants for a destination.

    Fetches NUM_VARIANTS images from Unsplash and caches them all.
    Call this when a destination is first selected to populate the cache.

    Args:
        destination: The destination name
        db: Optional database session for cache storage
        activities: Optional list of activity categories for activity-specific images

    Returns:
        Number of images successfully cached
    """
    normalized = destination.lower().strip()
    activity_str = f" (activities={activities})" if activities else ""
    logger.info(f"[UNSPLASH] Prefetching images for: {normalized}{activity_str}")

    # Check if we already have variants cached
    cache_key_0 = _cache_key(destination, 0, activities)
    async with _memory_cache_lock:
        if cache_key_0 in _memory_cache:
            # Count how many variants we have
            count = sum(
                1
                for i in range(NUM_VARIANTS)
                if _cache_key(destination, i, activities) in _memory_cache
            )
            logger.info(
                f"[UNSPLASH] Already have {count} variants cached for {normalized}{activity_str}"
            )
            return count
        # Activity prefetch fast-path:
        # if destination base variants are already cached, alias them immediately
        # under the activity-partitioned keys to avoid new API calls/timeouts.
        if activities:
            base_count = sum(
                1 for i in range(NUM_VARIANTS) if _cache_key(destination, i) in _memory_cache
            )
            if base_count > 0:
                for i in range(NUM_VARIANTS):
                    base_key = _cache_key(destination, i)
                    base_img = _memory_cache.get(base_key)
                    if base_img is not None:
                        _memory_cache.set(_cache_key(destination, i, activities), base_img)
                logger.info(
                    "[UNSPLASH] Reused %s base variants for %s%s",
                    base_count,
                    normalized,
                    activity_str,
                )
                return base_count

    # Check DB cache (activity-aware key partitions base vs activity-specific images)
    # DB/API fetches happen outside the lock
    if db:
        try:
            db_images = await _get_all_variants_from_db(db, destination, activities)
            if db_images:
                # Populate memory cache from DB
                async with _memory_cache_lock:
                    for i, img in enumerate(db_images):
                        _memory_cache.set(_cache_key(destination, i, activities), img)
                logger.info(f"[UNSPLASH] Loaded {len(db_images)} variants from DB for {normalized}")
                return len(db_images)
            # Activity prefetch DB fast-path: reuse base destination DB cache
            # before hitting the API if activity-specific DB rows are absent.
            if activities:
                base_images = await _get_all_variants_from_db(db, destination)
                if base_images:
                    async with _memory_cache_lock:
                        for i, img in enumerate(base_images):
                            _memory_cache.set(_cache_key(destination, i, activities), img)
                    logger.info(
                        f"[UNSPLASH] Reused {len(base_images)} base DB variants for "
                        f"{normalized}{activity_str}"
                    )
                    return len(base_images)
        except Exception as e:
            logger.warning(f"[UNSPLASH] DB lookup failed: {e}")

    # Fetch from Unsplash API
    images = await _fetch_variants_from_unsplash(destination, activities, prefetch=True)

    if images:
        # Store destination-scoped images once, then alias activity keys to base.
        async with _memory_cache_lock:
            for i, img in enumerate(images):
                base_key = _cache_key(destination, i)
                canonical = _memory_cache.get(base_key)
                if canonical is None:
                    _memory_cache.set(base_key, img)
                    canonical = img
                scoped_key = _cache_key(destination, i, activities)
                _memory_cache.set(scoped_key, canonical)

        # Store in DB (activity-aware key prevents collisions)
        if db:
            try:
                db_activities = activities if activities else None
                await _save_all_variants_to_db(db, destination, images, db_activities)
            except Exception as e:
                logger.warning(f"[UNSPLASH] DB save failed: {e}")

        logger.info(f"[UNSPLASH] Cached {len(images)} variants for {normalized}{activity_str}")
        return len(images)

    # If API returned no images and activities were provided, fall back to base destination
    # This ensures we use cached destination images even if activity-specific query fails
    if activities and db:
        logger.info("[UNSPLASH] Activity query returned no images, trying base destination from DB")
        try:
            db_images = await _get_all_variants_from_db(db, destination)
            if db_images:
                # Populate memory cache with base destination images
                # (using activity key for consistency)
                async with _memory_cache_lock:
                    for i, img in enumerate(db_images):
                        _memory_cache.set(_cache_key(destination, i, activities), img)
                logger.info(
                    f"[UNSPLASH] Fallback: loaded {len(db_images)} base "
                    f"variants from DB for {normalized}"
                )
                return len(db_images)
        except Exception as e:
            logger.warning(f"[UNSPLASH] DB fallback lookup failed: {e}")

    logger.info(f"[UNSPLASH] No images fetched for {normalized}{activity_str}")
    return 0


async def get_image_for_destination(
    destination: str,
    variant: int = 0,
    db: Optional[AsyncSession] = None,
    width: int = 800,
    height: int = 600,
    activities: list[str] | None = None,
) -> str:
    """
    Get image URL for a destination.

    Lookup order:
    1. In-memory cache (fastest)
    2. Database cache (persistent, including activity/base fallback)
    3. Unsplash API (fresh fetch - fetches all variants)
    4. Deterministic Unsplash placeholder fallback (on any failure)

    Args:
        destination: The destination name
        variant: Which image variant to return (0-5, default 0)
        db: Optional database session for cache lookup/storage
        width: Image width
        height: Image height
        activities: Optional list of activity categories for activity-specific images

    Returns:
        Image URL (Unsplash API/cache result or Unsplash placeholder fallback)
    """
    normalized = destination.lower().strip()
    cache_key = _cache_key(destination, variant, activities)
    activity_str = f", activities={activities}" if activities else ""
    logger.info(
        f"[UNSPLASH] get_image_for_destination: dest={destination}, variant={variant}{activity_str}"
    )

    # 1. Check in-memory cache for this variant (with scoped fallbacks)
    async with _memory_cache_lock:
        for key in _candidate_cache_keys(destination, variant, activities):
            image = _memory_cache.get(key)
            if image is not None:
                url = build_image_url(image.image_id, width, height)
                logger.info(
                    f"[UNSPLASH] Memory cache HIT for {cache_key} using {key}: {url[:80]}..."
                )
                return url

    # 2. Check database cache for this variant (activity-aware)
    # DB/API fetches happen outside the lock
    logger.info(f"[UNSPLASH] Memory cache MISS for {cache_key}, checking DB")
    if db:
        try:
            cached = await _get_from_db_cache(db, destination, variant, activities)
            if cached:
                async with _memory_cache_lock:
                    _memory_cache.set(cache_key, cached)
                url = build_image_url(cached.image_id, width, height)
                logger.info(f"[UNSPLASH] DB cache HIT for {cache_key}: {url[:80]}...")
                return url
            # Activity-specific lookup fallback: reuse base destination DB image.
            if activities:
                base_cached = await _get_from_db_cache(db, destination, variant)
                if base_cached:
                    async with _memory_cache_lock:
                        _memory_cache.set(cache_key, base_cached)
                    url = build_image_url(base_cached.image_id, width, height)
                    logger.info(
                        f"[UNSPLASH] DB fallback HIT for {cache_key} using "
                        f"{_cache_key(destination, variant)}: {url[:80]}..."
                    )
                    return url
            logger.info(f"[UNSPLASH] DB cache MISS for {cache_key}")
        except Exception as e:
            logger.warning(f"[UNSPLASH] DB cache lookup failed: {e}")

    # 3. Fetch ALL variants from Unsplash API (better to fetch once)
    logger.info(f"[UNSPLASH] Fetching from Unsplash API for {normalized}{activity_str}...")
    images = await _fetch_variants_from_unsplash(destination, activities)

    if images:
        # Store all fetched variants in memory cache
        async with _memory_cache_lock:
            for i, img in enumerate(images):
                _memory_cache.set(_cache_key(destination, i, activities), img)
        logger.info(
            f"[UNSPLASH] API SUCCESS: cached {len(images)} variants for {normalized}{activity_str}"
        )

        # Store all in DB (activity-aware key prevents collisions)
        if db:
            try:
                await _save_all_variants_to_db(db, destination, images, activities)
                logger.info(f"[UNSPLASH] Saved {len(images)} variants to DB for {normalized}")
            except Exception as e:
                logger.warning(f"[UNSPLASH] DB cache save failed: {e}")

        # Return requested variant (or fallback to variant 0 if not enough results)
        actual_variant = variant % len(images)
        image = images[actual_variant]
        url = build_image_url(image.image_id, width, height)
        logger.info(
            f"[UNSPLASH] Returning Unsplash URL for variant {actual_variant}: {url[:80]}..."
        )
        return url

    # 4. Fallback to deterministic Unsplash placeholder (no Picsum host usage)
    fallback_url = _get_unsplash_placeholder_fallback(destination, variant, width, height)
    logger.warning(
        "[UNSPLASH] Using Unsplash placeholder fallback for "
        f"{destination}:{variant}: {fallback_url}"
    )
    return fallback_url


async def clear_memory_cache() -> None:
    """Clear the in-memory cache (useful for testing)."""
    _memory_cache.clear()  # MemoryCache has internal RLock — safe from any context

    async with _inflight_fetches_lock:
        _inflight_fetches.clear()

    async with _prefetch_cooldown_lock:
        for task in _prefetch_destination_inflight.values():
            if not task.done():
                task.cancel()
        _prefetch_destination_inflight.clear()
        _prefetch_failure_until.clear()
        _prefetch_timeout_streak.clear()
        _prefetch_dest_failure_until.clear()

    # Close shared HTTP client so it's recreated fresh
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


async def clear_db_cache(db: AsyncSession) -> int:
    """
    Clear all cached Unsplash images from the database.

    This removes all persistent image cache entries. Use with caution
    as it will require re-fetching images from Unsplash API.

    Args:
        db: Async database session

    Returns:
        Number of cache entries deleted
    """
    from sqlalchemy import delete, func

    from app.db_models import UnsplashImageCache

    try:
        # Count before delete
        count_result = await db.execute(select(func.count()).select_from(UnsplashImageCache))
        count = count_result.scalar() or 0

        # Delete all entries
        await db.execute(delete(UnsplashImageCache))
        await db.commit()

        logger.info(f"[UNSPLASH-DB] Cleared {count} cached images from database")
        return count
    except Exception as e:
        logger.warning(f"[UNSPLASH-DB] Failed to clear cache: {e}")
        await db.rollback()
        return 0


def get_memory_cache_stats() -> dict:
    """Return statistics about the in-memory Unsplash cache."""
    with _sync_lock:
        destinations = {
            parts[2]
            for key in _memory_cache.keys()
            for parts in [key.split("::")]
            if len(parts) >= 4 and parts[0] == "unsplash" and parts[1] == "v2"
        }
        return {
            "entries": len(_memory_cache),
            "destinations": len(destinations),
        }


def get_cached_image_url(
    destination: str,
    variant: int = 0,
    width: int = 800,
    height: int = 600,
    activities: list[str] | None = None,
) -> str | None:
    """Return cached Unsplash URL or None. No blocking I/O."""
    with _sync_lock:
        for key in _candidate_cache_keys(destination, variant, activities):
            image = _memory_cache.get(key)
            if image is not None:
                return build_image_url(image.image_id, width, height)
        return None


def get_image_url_sync(
    destination: str,
    variant: int = 0,
    width: int = 800,
    height: int = 600,
    activities: list[str] | None = None,
) -> str:
    """
    Synchronous version for use in sync contexts (e.g., mock providers).

    Checks in-memory cache first, falls back to deterministic Unsplash placeholder if not cached.
    For full Unsplash support, use the async `get_image_for_destination`.

    Args:
        destination: The destination name
        variant: Which image variant to return (0-5, default 0)
        width: Image width
        height: Image height
        activities: Optional list of activity categories for activity-specific images

    Returns:
        Image URL (cached Unsplash or deterministic Unsplash placeholder fallback)
    """
    cache_key = _cache_key(destination, variant, activities)
    activity_str = f", activities={activities}" if activities else ""
    logger.debug(
        f"[UNSPLASH-SYNC] get_image_url_sync: dest={destination}, "
        f"variant={variant}{activity_str}, cache_size={len(_memory_cache)}"
    )

    # Check in-memory cache (may be populated by previous async calls or prefetch)
    with _sync_lock:
        for key in _candidate_cache_keys(destination, variant, activities):
            image = _memory_cache.get(key)
            if image is not None:
                url = build_image_url(image.image_id, width, height)
                logger.debug(
                    f"[UNSPLASH-SYNC] Cache HIT for {cache_key} using {key}: {url[:80]}..."
                )
                return url

    # Fall back to activity-aware placeholder if activities specified,
    # otherwise use deterministic Unsplash destination placeholder.
    if activities and len(activities) > 0:
        from app.placeholders import get_activity_image

        activity = activities[0].lower().strip()
        # Use deterministic seed based on destination + variant for variety
        seed_title = f"{destination}-{variant}"
        fallback_url = get_activity_image(activity, destination, seed_title)
        logger.debug(
            f"[UNSPLASH-SYNC] Cache MISS for {cache_key}, "
            f"using activity placeholder: {fallback_url}"
        )
    else:
        fallback_url = _get_unsplash_placeholder_fallback(destination, variant, width, height)
        logger.debug(
            "[UNSPLASH-SYNC] Cache MISS for "
            f"{cache_key}, using destination placeholder: {fallback_url}"
        )
    return fallback_url
