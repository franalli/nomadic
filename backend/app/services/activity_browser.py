"""
Activity Browser Service — on-demand Google Places search for free/buffer days.

Called by POST /api/activities/browse when the user clicks "Browse Activities"
on a free or buffer day. Returns up to 20 activity tiles from Google Places.

Cache key: browse::v1::{destination}::{sorted_categories}::{month}
(month-level granularity — same activities available across the month)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Category → Google Places API types mapping
# Dynamic mapping — works for any destination worldwide
CATEGORY_TO_PLACES_TYPES: Dict[str, List[str]] = {
    "spa": ["spa", "beauty_salon"],
    "cultural": ["museum", "art_gallery", "hindu_temple", "church", "mosque"],
    "food": ["restaurant", "cafe", "bakery"],
    "nature": ["park", "natural_feature", "campground"],
    "shopping": ["shopping_mall", "market", "clothing_store"],
    "nightlife": ["night_club", "bar"],
    "tours": ["tourist_attraction"],
    "wellness": ["gym", "spa"],
}

# Max results per browse request (Places API cost control)
MAX_BROWSE_RESULTS = 20

# In-memory L1 cache: key → list of tile dicts
# TTL is enforced by month-granularity key — no explicit expiry needed for L1
_browse_cache: Dict[str, List[Dict[str, Any]]] = {}
_MAX_CACHE_ENTRIES = 200


def _cache_key(destination: str, categories: List[str], month: str) -> str:
    """Build a deterministic cache key."""
    sorted_cats = ":".join(sorted(categories))
    raw = f"browse::v1::{destination.lower().strip()}::{sorted_cats}::{month}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]  # noqa: S324


def _price_level_to_range(price_level: Optional[int]) -> Optional[str]:
    """Map Google Places price_level (0-4) to human-readable range."""
    mapping = {0: "Free", 1: "$", 2: "$$", 3: "$$$", 4: "$$$$"}
    return mapping.get(price_level) if price_level is not None else None


def _humanize_type(place_type: str) -> str:
    """Convert a Google Places type string to human-readable label."""
    return place_type.replace("_", " ").title()


def _place_to_tile(place: Dict[str, Any], category: str) -> Dict[str, Any]:
    """Transform a Google Places place dict into a browse tile dict."""
    from app.tile_service.google_places_provider import _get_photo_url

    place_id = place.get("id", "")
    name = place.get("displayName", {}).get("text", "Unknown")
    location = place.get("location", {})
    lat = location.get("latitude")
    lng = location.get("longitude")
    address = place.get("formattedAddress", "")
    primary_type = place.get("primaryType", category)
    rating = place.get("rating")
    review_count = place.get("userRatingCount")
    price_level_raw = place.get("priceLevel")
    # priceLevel comes back as a string enum like "PRICE_LEVEL_MODERATE"
    price_level_map = {
        "PRICE_LEVEL_FREE": 0,
        "PRICE_LEVEL_INEXPENSIVE": 1,
        "PRICE_LEVEL_MODERATE": 2,
        "PRICE_LEVEL_EXPENSIVE": 3,
        "PRICE_LEVEL_VERY_EXPENSIVE": 4,
    }
    price_level = price_level_map.get(price_level_raw) if isinstance(price_level_raw, str) else None

    # Photo URL
    photos = place.get("photos", [])
    image_url = None
    if photos:
        photo_name = photos[0].get("name", "")
        image_url = _get_photo_url(photo_name)

    editorial = place.get("editorialSummary", {}).get("text", "")

    maps_uri = place.get("googleMapsUri")
    return {
        "id": f"browse_{place_id}",
        "type": "activity",
        "title": name,
        "subtitle": _humanize_type(primary_type),
        "description": editorial,
        "image_url": image_url,
        "rating": rating,
        "review_count": review_count,
        # Field aliases expected by itinerary_builder
        "user_ratings_count": review_count,
        "google_place_id": place_id,
        "deeplink": maps_uri,
        "location_label": address,
        "geo": {"lat": lat, "lng": lng} if lat and lng else None,
        "price_estimate": _price_level_to_range(price_level),
        "price_level": price_level,
        "source": "google_places",
        "provider": "google_places",
        "category": category,
        "tags": [primary_type],
        # Original field names kept for backward compat
        "place_id": place_id,
        "maps_uri": maps_uri,
    }


async def browse_activities(
    destination: str,
    center: Optional[tuple[float, float]],
    categories: List[str],
    date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Search Google Places for activities in the given categories near the destination.

    Args:
        destination: Destination name (e.g. "Bali")
        center: (lat, lng) tuple for search center, or None to geocode destination
        categories: List of category keys from CATEGORY_TO_PLACES_TYPES
        date: ISO date string (used for month-level cache key)

    Returns:
        List of tile dicts (up to MAX_BROWSE_RESULTS)
    """
    from app.tile_service.google_places_provider import (
        _call_places_api_async,
        _geocode_destination_async,
    )

    # Determine month for cache key
    month = date[:7] if date and len(date) >= 7 else "unknown"

    # Filter to known categories
    valid_categories = [c for c in categories if c in CATEGORY_TO_PLACES_TYPES]
    if not valid_categories:
        valid_categories = ["cultural", "food", "nature"]

    cache_key = _cache_key(destination, valid_categories, month)
    if cache_key in _browse_cache:
        logger.debug("[BROWSE] Cache HIT for %s (%s)", destination, valid_categories)
        return _browse_cache[cache_key]

    # Resolve geo center
    geo = center
    if not geo:
        geo = await _geocode_destination_async(destination)

    if not settings.google_maps_api_key:
        logger.warning("[BROWSE] No Google Maps API key — returning empty results")
        return []

    # Collect Places API types to search
    types_to_search: List[tuple[str, str]] = []  # (places_type, category)
    for cat in valid_categories:
        for place_type in CATEGORY_TO_PLACES_TYPES[cat][:2]:  # Max 2 types per category
            types_to_search.append((place_type, cat))

    # Parallel search across types (max 20 total results)
    results_per_type: Dict[str, List[Dict[str, Any]]] = {}

    async def _search_type(place_type: str, category: str) -> None:
        try:
            places = await _call_places_api_async(
                query=f"{place_type} in {destination}",
                included_type=place_type,
                max_results=4,
                geo=geo,
            )
            results_per_type[f"{category}:{place_type}"] = [
                _place_to_tile(p, category) for p in places
            ]
        except Exception as e:
            logger.warning("[BROWSE] Search failed for %s: %s", place_type, e)
            results_per_type[f"{category}:{place_type}"] = []

    await asyncio.gather(*[_search_type(pt, cat) for pt, cat in types_to_search])

    # Flatten and deduplicate by place_id
    seen_ids: set[str] = set()
    tiles: List[Dict[str, Any]] = []
    for tile_list in results_per_type.values():
        for tile in tile_list:
            pid = tile.get("place_id", "")
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                tiles.append(tile)
            if len(tiles) >= MAX_BROWSE_RESULTS:
                break
        if len(tiles) >= MAX_BROWSE_RESULTS:
            break

    # Cache result (L1)
    if len(_browse_cache) >= _MAX_CACHE_ENTRIES:
        # Evict oldest entry
        oldest = next(iter(_browse_cache))
        del _browse_cache[oldest]
    _browse_cache[cache_key] = tiles

    logger.debug("[BROWSE] Found %d tiles for %s", len(tiles), destination)
    return tiles
