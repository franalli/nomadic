"""
GetYourGuide (GYG) partner API provider for activity tile enrichment.

Enriches LLM-generated activity tiles with real pricing, images, ratings,
and affiliate deeplinks from GYG's partner API.

Graceful degradation: all functions return empty/None on failure.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from rapidfuzz import fuzz

from app.config import settings
from app.services.cache_core import MemoryCache
from app.services.circuit_breaker import CircuitBreaker
from app.services.spend_guard import reserve_partner_api_spend_or_raise

logger = logging.getLogger(__name__)

# -- Constants ----------------------------------------------------------------
GYG_BASE = settings.get_your_guide_api_url
GYG_TIMEOUT = 8.0  # seconds
MAX_SINGLE_ACTIVITY_MINUTES = 480  # 8 hours -- filter multi-day tours

# -- Singleton httpx client ---------------------------------------------------
_gyg_client: httpx.AsyncClient | None = None
_gyg_client_lock = asyncio.Lock()


async def _get_gyg_client() -> httpx.AsyncClient:
    """Return a shared httpx client, creating lazily if needed."""
    global _gyg_client
    if _gyg_client is not None and not _gyg_client.is_closed:
        return _gyg_client
    async with _gyg_client_lock:
        if _gyg_client is None or _gyg_client.is_closed:
            _gyg_client = httpx.AsyncClient(timeout=GYG_TIMEOUT)
        return _gyg_client


async def close_gyg_http_client() -> None:
    """Close the shared httpx client (call during app shutdown)."""
    global _gyg_client
    if _gyg_client and not _gyg_client.is_closed:
        await _gyg_client.aclose()
        _gyg_client = None


# -- Circuit breaker ----------------------------------------------------------
_gyg_cb = CircuitBreaker("gyg", failure_threshold=5, open_seconds=120)


# -- Caches -------------------------------------------------------------------
_NO_MATCH: object = object()  # sentinel for negative match cache entries

_gyg_cache_ttl = settings.get_your_guide_cache_ttl_hours * 3600
_match_cache = MemoryCache(maxsize=512, ttl=_gyg_cache_ttl)  # title->tour matches
_browse_gyg_cache = MemoryCache(maxsize=256, ttl=_gyg_cache_ttl)  # browse results

# -- Concurrency limiter -----------------------------------------------------
_sem = asyncio.Semaphore(5)

# -- API helpers --------------------------------------------------------------


def _gyg_headers() -> dict[str, str]:
    return {
        "X-ACCESS-TOKEN": settings.get_your_guide_api_key,
        "Accept": "application/json",
    }


async def search_tours(
    query: str,
    currency: str = "USD",
    count: int = 3,
) -> list[dict]:
    """Freetext search for GYG tours. Returns raw tour dicts from API."""
    if _gyg_cb.is_open():
        return []

    try:
        async with _sem:
            reserve_partner_api_spend_or_raise("gyg")
            client = await _get_gyg_client()
            resp = await client.get(
                f"{GYG_BASE}/tours",
                params={
                    "q": query,
                    "cnt_language": "en",
                    "currency": currency,
                    "limit": count,
                },
                headers=_gyg_headers(),
                timeout=GYG_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            tours = data.get("data", {}).get("tours", [])
            _gyg_cb.record_success()
            return tours
    except Exception as e:
        _gyg_cb.record_failure()
        logger.debug("[GYG] Tour search failed: %s", e)
        return []


def _parse_duration(tour: dict) -> tuple[float | None, str]:
    """Parse GYG tour duration. Returns (value, unit) or (None, "")."""
    durations = tour.get("durations", [])
    if not durations:
        return None, ""

    d = durations[0]
    value = d.get("duration")
    unit = (d.get("unit") or "").lower()

    if value is None:
        return None, ""

    try:
        return float(value), unit
    except (TypeError, ValueError):
        return None, ""


def _duration_to_minutes(value: float, unit: str) -> float:
    """Convert a duration value+unit to minutes."""
    if unit == "day":
        return value * 24 * 60
    elif unit == "hour":
        return value * 60
    elif unit == "minute":
        return value
    else:
        logger.debug("[GYG] Unknown duration unit '%s', assuming hours", unit)
        return value * 60  # assume hours


def _parse_duration_hours(tour: dict) -> float | None:
    """Extract duration in hours from GYG tour durations array."""
    value, unit = _parse_duration(tour)
    if value is None:
        return None

    minutes = _duration_to_minutes(value, unit)
    hours = minutes / 60

    # Cap absurd durations (multi-day passes)
    if hours > 12:
        logger.info("[GYG] Capping duration %sh -> 12h for tour", hours)
        hours = 12.0

    return round(hours, 1)


def gyg_tour_to_tile(tour: dict, destination: str) -> dict:
    """Convert a GYG tour dict to a Nomadic tile dict."""
    tour_id = tour.get("tour_id", "")
    title = tour.get("title", "GYG Activity")

    # Price
    price_data = tour.get("price", {})
    price_values = price_data.get("values", {})
    price_amount = price_values.get("amount")
    price_desc = (price_data.get("description") or "").lower()
    price_basis = "per_person" if "individual" in price_desc else "per_group"

    # Rating
    rating = tour.get("overall_rating")
    review_count = tour.get("number_of_ratings")

    # Deeplink
    deeplink_url = tour.get("url", "")

    # Geo: GYG uses "long" not "lng"
    coords = tour.get("coordinates", {})
    geo: dict[str, float] | None = None
    if isinstance(coords, dict) and coords.get("lat") and coords.get("long"):
        geo = {"lat": coords["lat"], "lng": coords["long"]}

    # Image: replace {format_id} placeholder with size 31 (500x383)
    image_url = ""
    pictures = tour.get("pictures", [])
    if pictures and isinstance(pictures, list):
        first_pic = pictures[0]
        if isinstance(first_pic, dict):
            ssl_url = first_pic.get("ssl_url", "")
            if ssl_url:
                image_url = ssl_url.replace("{format_id}", "31")

    # Duration
    duration_hours = _parse_duration_hours(tour)

    tile: dict[str, Any] = {
        "id": f"gyg_{tour_id}",
        "type": "activity",
        "title": title,
        "partner": "gyg",
        "partner_product_id": str(tour_id),
        "provider": "gyg",
        "deeplink": deeplink_url,
        "deeplink_url": deeplink_url,
        "destination": destination,
        "is_estimate_only": False,
        "meta": {},
    }

    if geo:
        tile["geo"] = geo

    if price_amount is not None:
        tile["price_estimate"] = price_amount
        tile["live_price"] = price_amount
        tile["currency"] = "USD"
        tile["price_basis"] = price_basis

    if image_url:
        tile["image_url"] = image_url

    if rating is not None:
        tile["rating"] = round(float(rating), 1)
    if review_count is not None:
        tile["review_count"] = review_count

    if duration_hours is not None:
        tile["meta"]["duration_hours"] = duration_hours
    tile["meta"]["gyg_tour_id"] = str(tour_id)

    return tile


async def match_activity_to_gyg(
    activity_title: str,
    destination: str,
    currency: str = "USD",
) -> dict | None:
    """Match an activity title to a GYG tour. Returns tile dict or None."""
    cache_key = f"gyg_match:{destination.lower()}:{activity_title.lower()}"
    cached = _match_cache.get(cache_key)
    if cached is not None:
        return cached if cached is not _NO_MATCH else None

    query = f"{activity_title} {destination}"
    tours = await search_tours(query, currency, count=3)

    # Filter multi-day tours (> 480 minutes = 8 hours)
    tours = [t for t in tours if _tour_duration_minutes(t) <= MAX_SINGLE_ACTIVITY_MINUTES]

    if not tours:
        _match_cache.set(cache_key, _NO_MATCH)
        return None

    # Score by title similarity
    best_score = 0
    best_tour = None
    for t in tours:
        t_title = t.get("title", "")
        score = fuzz.token_sort_ratio(activity_title.lower(), t_title.lower())
        if score > best_score:
            best_score = score
            best_tour = t

    if best_score < 65 or best_tour is None:
        _match_cache.set(cache_key, _NO_MATCH)
        return None

    tile = gyg_tour_to_tile(best_tour, destination)
    _match_cache.set(cache_key, tile)
    return tile


def _tour_duration_minutes(tour: dict) -> float:
    """Return tour duration in minutes, defaulting to MAX_SINGLE_ACTIVITY_MINUTES."""
    value, unit = _parse_duration(tour)
    if value is None:
        return MAX_SINGLE_ACTIVITY_MINUTES  # unknown = assume OK
    return _duration_to_minutes(value, unit)


async def search_gyg_for_destination(
    destination: str,
    currency: str = "USD",
    count: int = 10,
) -> list[dict]:
    """Browse GYG tours for a destination. Returns list of tile dicts."""
    cache_key = f"gyg_browse:{destination.lower()}:{currency}:{count}"
    cached = _browse_gyg_cache.get(cache_key)
    if cached is not None:
        logger.debug("[GYG] L1 cache hit for browse: %s", destination)
        return cached

    query = f"tours and activities in {destination}"
    tours = await search_tours(query, currency, count)

    # Filter multi-day tours
    tours = [t for t in tours if _tour_duration_minutes(t) <= MAX_SINGLE_ACTIVITY_MINUTES]

    if not tours:
        return []

    tiles = [gyg_tour_to_tile(t, destination) for t in tours]
    _browse_gyg_cache.set(cache_key, tiles)
    logger.debug("[GYG] Cached %d browse tiles for %s", len(tiles), destination)
    return tiles
