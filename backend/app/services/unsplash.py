# backend/app/services/unsplash.py
"""
Unsplash image service for dynamic destination images.

Features:
- Fetches multiple images per destination for unique tile/branch imagery
- Two-tier caching: in-memory (runtime) + database (persistent)
- Stores image_id, not raw URLs (best practice)
- Falls back to Picsum on API failure
- Full production attribution support (photographer, Unsplash link, download tracking)
"""

import logging
from datetime import UTC, datetime
from typing import List, Optional

import httpx
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.unsplash_queries import get_query_for_destination

logger = logging.getLogger(__name__)

# UTM parameters for attribution links (required by Unsplash)
UTM_SOURCE = "nomadic"
UTM_MEDIUM = "referral"

# In-memory cache for hot destinations (avoids DB hits in same session)
# Key format: "destination:variant" (e.g., "patagonia:0", "patagonia:1")
_memory_cache: dict[str, "UnsplashImage"] = {}

# Number of image variants to fetch per destination
NUM_VARIANTS = 6


def _cache_key(destination: str, variant: int, activities: list[str] | None = None) -> str:
    """Generate cache key for destination:activity:variant."""
    normalized = destination.lower().strip()
    # Only use activity in key if we have a non-empty activity string
    if activities and len(activities) > 0:
        activity = activities[0].lower().strip()
        if activity:  # Only include if non-empty after strip
            return f"{normalized}:{activity}:{variant}"
    return f"{normalized}:{variant}"


class UnsplashImage(BaseModel):
    """Cached Unsplash image data with full attribution info."""

    image_id: str
    photographer: Optional[str] = None
    photographer_url: Optional[str] = None
    # Required for production attribution
    unsplash_url: Optional[str] = None  # Image page on Unsplash
    download_location: Optional[str] = None  # API endpoint for download tracking


def _add_utm_params(url: Optional[str]) -> Optional[str]:
    """Add required UTM parameters to Unsplash URLs."""
    if not url:
        return None
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}utm_source={UTM_SOURCE}&utm_medium={UTM_MEDIUM}"


def build_image_url(image_id: str, width: int = 800, height: int = 600) -> str:
    """
    Construct Unsplash image URL from image_id.

    Allows dynamic sizing without storing full URLs.
    """
    return f"https://images.unsplash.com/photo-{image_id}?w={width}&h={height}&fit=crop&auto=format&q=80"


def _get_picsum_fallback(
    destination: str, variant: int = 0, width: int = 800, height: int = 600
) -> str:
    """
    Generate deterministic Picsum fallback URL.

    Uses destination + variant as seed for consistent but unique images.
    """
    seed = destination.lower().replace(" ", "-").replace(",", "")
    if variant > 0:
        seed = f"{seed}-{variant}"
    return f"https://picsum.photos/seed/{seed}/{width}/{height}"


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


async def _fetch_variants_from_unsplash(
    destination: str, activities: list[str] | None = None
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

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
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

            logger.info(f"[UNSPLASH-API] Response status: {response.status_code}")

            if response.status_code == 403:
                logger.warning("[UNSPLASH-API] Rate limit exceeded (403)")
                return []

            if response.status_code != 200:
                logger.warning(
                    f"[UNSPLASH-API] Error status: {response.status_code}, "
                    f"body: {response.text[:200]}"
                )
                return []

            data = response.json()
            results = data.get("results", [])
            logger.info(f"[UNSPLASH-API] Got {len(results)} results for {destination}")

            if not results:
                logger.info(f"No Unsplash results for query: {query}")
                return []

            images = []
            for photo in results:
                img = _extract_image_from_photo(photo)
                if img:
                    images.append(img)

            logger.info(f"[UNSPLASH-API] Extracted {len(images)} valid images for {destination}")
            return images

    except httpx.TimeoutException:
        logger.warning(f"Unsplash API timeout for destination: {destination}")
        return []
    except Exception as e:
        logger.warning(f"Unsplash API error for {destination}: {e}")
        return []


async def _get_from_db_cache(
    db: AsyncSession, destination: str, variant: int = 0
) -> Optional[UnsplashImage]:
    """Check database cache for existing image variant."""
    from app.db_models import UnsplashImageCache

    normalized = destination.lower().strip()
    logger.info(f"[UNSPLASH-DB] Checking DB cache for: {normalized}:{variant}")

    try:
        result = await db.execute(
            select(UnsplashImageCache).where(
                UnsplashImageCache.destination == normalized,
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


async def _get_all_variants_from_db(db: AsyncSession, destination: str) -> List[UnsplashImage]:
    """Get all cached variants for a destination from DB."""
    from app.db_models import UnsplashImageCache

    normalized = destination.lower().strip()
    logger.info(f"[UNSPLASH-DB] Checking DB for all variants of: {normalized}")

    try:
        result = await db.execute(
            select(UnsplashImageCache)
            .where(UnsplashImageCache.destination == normalized)
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


async def _save_to_db_cache(
    db: AsyncSession, destination: str, variant: int, image: UnsplashImage
) -> None:
    """Save image variant to database cache."""
    from app.db_models import UnsplashImageCache

    normalized = destination.lower().strip()
    logger.info(f"[UNSPLASH-DB] Saving to DB cache: {normalized}:{variant}")

    try:
        # Upsert: check if exists first
        result = await db.execute(
            select(UnsplashImageCache).where(
                UnsplashImageCache.destination == normalized,
                UnsplashImageCache.variant == variant,
            )
        )
        existing = result.scalar_one_or_none()
    except Exception as e:
        logger.warning(f"[UNSPLASH-DB] Query failed (table may not exist): {e}")
        return

    if existing:
        existing.image_id = image.image_id
        existing.photographer = image.photographer
        existing.photographer_url = image.photographer_url
        existing.unsplash_url = image.unsplash_url
        existing.download_location = image.download_location
        existing.cached_at = datetime.now(UTC)
    else:
        cache_entry = UnsplashImageCache(
            destination=normalized,
            variant=variant,
            image_id=image.image_id,
            photographer=image.photographer,
            photographer_url=image.photographer_url,
            unsplash_url=image.unsplash_url,
            download_location=image.download_location,
        )
        db.add(cache_entry)

    await db.commit()


async def _save_all_variants_to_db(
    db: AsyncSession, destination: str, images: List[UnsplashImage]
) -> None:
    """Save all image variants to database cache in one commit."""
    from app.db_models import UnsplashImageCache

    normalized = destination.lower().strip()
    logger.info(f"[UNSPLASH-DB] Saving {len(images)} variants to DB for: {normalized}")

    try:
        for variant, image in enumerate(images):
            result = await db.execute(
                select(UnsplashImageCache).where(
                    UnsplashImageCache.destination == normalized,
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
                    destination=normalized,
                    variant=variant,
                    image_id=image.image_id,
                    photographer=image.photographer,
                    photographer_url=image.photographer_url,
                    unsplash_url=image.unsplash_url,
                    download_location=image.download_location,
                )
                db.add(cache_entry)

        await db.commit()
        logger.info(f"[UNSPLASH-DB] Saved {len(images)} variants for {normalized}")
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

    # Check DB cache (only if no activity filter - DB cache is destination-only)
    if db and not activities:
        try:
            db_images = await _get_all_variants_from_db(db, destination)
            if db_images:
                # Populate memory cache from DB
                for i, img in enumerate(db_images):
                    _memory_cache[_cache_key(destination, i, activities)] = img
                logger.info(f"[UNSPLASH] Loaded {len(db_images)} variants from DB for {normalized}")
                return len(db_images)
        except Exception as e:
            logger.warning(f"[UNSPLASH] DB lookup failed: {e}")

    # Fetch from Unsplash API
    images = await _fetch_variants_from_unsplash(destination, activities)

    if images:
        # Store all variants in memory cache
        for i, img in enumerate(images):
            _memory_cache[_cache_key(destination, i, activities)] = img

        # Store in DB (only for non-activity queries to avoid DB bloat)
        if db and not activities:
            try:
                await _save_all_variants_to_db(db, destination, images)
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
                for i, img in enumerate(db_images):
                    _memory_cache[_cache_key(destination, i, activities)] = img
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
    2. Database cache (persistent, only for non-activity queries)
    3. Unsplash API (fresh fetch - fetches all variants)
    4. Picsum fallback (on any failure)

    Args:
        destination: The destination name
        variant: Which image variant to return (0-5, default 0)
        db: Optional database session for cache lookup/storage
        width: Image width
        height: Image height
        activities: Optional list of activity categories for activity-specific images

    Returns:
        Image URL (Unsplash or Picsum fallback)
    """
    normalized = destination.lower().strip()
    cache_key = _cache_key(destination, variant, activities)
    activity_str = f", activities={activities}" if activities else ""
    logger.info(
        f"[UNSPLASH] get_image_for_destination: dest={destination}, variant={variant}{activity_str}"
    )

    # 1. Check in-memory cache for this variant
    if cache_key in _memory_cache:
        image = _memory_cache[cache_key]
        url = build_image_url(image.image_id, width, height)
        logger.info(f"[UNSPLASH] Memory cache HIT for {cache_key}: {url[:80]}...")
        return url

    # 2. Check database cache for this variant (only for non-activity queries)
    logger.info(f"[UNSPLASH] Memory cache MISS for {cache_key}, checking DB")
    if db and not activities:
        try:
            cached = await _get_from_db_cache(db, destination, variant)
            if cached:
                _memory_cache[cache_key] = cached
                url = build_image_url(cached.image_id, width, height)
                logger.info(f"[UNSPLASH] DB cache HIT for {cache_key}: {url[:80]}...")
                return url
            logger.info(f"[UNSPLASH] DB cache MISS for {cache_key}")
        except Exception as e:
            logger.warning(f"[UNSPLASH] DB cache lookup failed: {e}")

    # 3. Fetch ALL variants from Unsplash API (better to fetch once)
    logger.info(f"[UNSPLASH] Fetching from Unsplash API for {normalized}{activity_str}...")
    images = await _fetch_variants_from_unsplash(destination, activities)

    if images:
        # Store all fetched variants in memory cache
        for i, img in enumerate(images):
            _memory_cache[_cache_key(destination, i, activities)] = img
        logger.info(
            f"[UNSPLASH] API SUCCESS: cached {len(images)} variants for {normalized}{activity_str}"
        )

        # Store all in DB (only for non-activity queries to avoid DB bloat)
        if db and not activities:
            try:
                await _save_all_variants_to_db(db, destination, images)
                logger.info(f"[UNSPLASH] Saved {len(images)} variants to DB for {normalized}")
            except Exception as e:
                logger.warning(f"[UNSPLASH] DB cache save failed: {e}")

        # Return requested variant (or fallback to variant 0 if not enough results)
        actual_variant = min(variant, len(images) - 1)
        image = images[actual_variant]
        url = build_image_url(image.image_id, width, height)
        logger.info(
            f"[UNSPLASH] Returning Unsplash URL for variant {actual_variant}: {url[:80]}..."
        )
        return url

    # 4. Fallback to Picsum (with variant-aware seed)
    fallback_url = _get_picsum_fallback(destination, variant, width, height)
    logger.info(f"[UNSPLASH] Using Picsum fallback for {destination}:{variant}: {fallback_url}")
    return fallback_url


def clear_memory_cache() -> None:
    """Clear the in-memory cache (useful for testing)."""
    _memory_cache.clear()


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
    return {
        "entries": len(_memory_cache),
        "destinations": len(set(k.split(":")[0] for k in _memory_cache.keys())),
    }


def get_image_url_sync(
    destination: str,
    variant: int = 0,
    width: int = 800,
    height: int = 600,
    activities: list[str] | None = None,
) -> str:
    """
    Synchronous version for use in sync contexts (e.g., mock providers).

    Checks in-memory cache first, falls back to Picsum if not cached.
    For full Unsplash support, use the async `get_image_for_destination`.

    Args:
        destination: The destination name
        variant: Which image variant to return (0-5, default 0)
        width: Image width
        height: Image height
        activities: Optional list of activity categories for activity-specific images

    Returns:
        Image URL (cached Unsplash or Picsum fallback)
    """
    cache_key = _cache_key(destination, variant, activities)
    activity_str = f", activities={activities}" if activities else ""
    logger.info(
        f"[UNSPLASH-SYNC] get_image_url_sync: dest={destination}, "
        f"variant={variant}{activity_str}, cache_size={len(_memory_cache)}"
    )

    # Check in-memory cache (may be populated by previous async calls or prefetch)
    if cache_key in _memory_cache:
        image = _memory_cache[cache_key]
        url = build_image_url(image.image_id, width, height)
        logger.info(f"[UNSPLASH-SYNC] Cache HIT for {cache_key}: {url[:80]}...")
        return url

    # Fall back to activity-aware placeholder if activities specified,
    # otherwise use Picsum for general destination images.
    # NOTE: We intentionally do NOT fall back to base destination key (e.g., "bali:0")
    # when activities are specified - that would return rice terraces for diving trips!
    if activities and len(activities) > 0:
        from app.placeholders import get_activity_image

        activity = activities[0].lower().strip()
        # Use deterministic seed based on destination + variant for variety
        seed_title = f"{destination}-{variant}"
        fallback_url = get_activity_image(activity, destination, seed_title)
        logger.info(
            f"[UNSPLASH-SYNC] Cache MISS for {cache_key}, "
            f"using activity placeholder: {fallback_url}"
        )
    else:
        fallback_url = _get_picsum_fallback(destination, variant, width, height)
        logger.info(f"[UNSPLASH-SYNC] Cache MISS for {cache_key}, using Picsum: {fallback_url}")
    return fallback_url
