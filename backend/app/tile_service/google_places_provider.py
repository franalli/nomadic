"""
Google Places provider for hotel and activity tiles.

Uses the Google Places API (New) Text Search to find real hotels and activities.
Provider cascade: curated → google_places → mock

Price estimation: price_level (0-4) × destination cost tier.
Photos: Placeholder images only (avoid exposing Google API keys in client URLs).
Deeplinks: Google Travel Hotels (preferred) with Maps fallback for hotels, Google Maps for activities.

Quota exhaustion or API errors → returns empty list → mock fallback applies.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
import time
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any, Dict, List, Optional

import httpx
from cachetools import TTLCache
from sqlalchemy import select, update

from app.config import get_media_signing_secret, settings
from app.placeholders import get_placeholder_image
from app.planner.hashing import make_cache_key, stable_hash
from app.schemas import Geo, Tile
from app.services.cache_core import MemoryCache, l2_upsert
from app.services.spend_guard import SpendLimitExceeded, reserve_places_spend_or_raise

from .models import SearchContext
from .provider_base import Provider
from .title_utils import simplify_specialist_title as _simplify_specialist_title
from .title_utils import token_overlap_ratio as _token_overlap_ratio

logger = logging.getLogger(__name__)

# ── Shared httpx client (connection reuse) ────────────────────────────────
_places_http_client: httpx.AsyncClient | None = None
_places_client_lock = asyncio.Lock()


async def _get_places_http_client() -> httpx.AsyncClient:
    """Return a shared httpx client, creating lazily if needed.

    Timeouts are set per-request, not on the client, since geocode (3s)
    and search (5s) have different requirements.
    """
    global _places_http_client
    if _places_http_client is not None and not _places_http_client.is_closed:
        return _places_http_client
    async with _places_client_lock:
        if _places_http_client is None or _places_http_client.is_closed:
            _places_http_client = httpx.AsyncClient(timeout=10.0)
        return _places_http_client


async def close_places_http_client() -> None:
    """Close the shared httpx client (call during app shutdown)."""
    global _places_http_client
    if _places_http_client and not _places_http_client.is_closed:
        await _places_http_client.aclose()
        _places_http_client = None


# ── Shared sync httpx client (connection reuse for sync methods) ──────────
_sync_client: httpx.Client | None = None
_sync_client_lock = Lock()


def _get_sync_client() -> httpx.Client:
    """Return a shared sync httpx client, creating lazily if needed."""
    global _sync_client
    if _sync_client is not None and not _sync_client.is_closed:
        return _sync_client
    with _sync_client_lock:
        if _sync_client is None or _sync_client.is_closed:
            _sync_client = httpx.Client(timeout=5.0)
    return _sync_client


def close_sync_client() -> None:
    """Close the shared sync httpx client (call during app shutdown)."""
    global _sync_client
    if _sync_client and not _sync_client.is_closed:
        _sync_client.close()
        _sync_client = None


# Explicit Google Places usage labels for telemetry.
_PLACES_PATH_LABELS = {
    "browse",
    "tier1_enrich",
    "tier2_enrich",
    "logistics",
    "geocode",
    "photo_proxy",
}
_PLACES_COUNTER_FIELDS = (
    "requests",
    "successes",
    "empty",
    "errors",
    "quota_exhausted",
    "cache_hits",
    "cache_misses",
)
_places_usage_lock = Lock()
_places_usage_counters: dict[str, dict[str, int]] = {
    label: {field: 0 for field in _PLACES_COUNTER_FIELDS} for label in _PLACES_PATH_LABELS
}


def _normalize_places_path(path_label: str) -> str:
    normalized = (path_label or "").strip().lower()
    return normalized if normalized in _PLACES_PATH_LABELS else "logistics"


def record_google_places_usage(path_label: str, event: str, **context: Any) -> None:
    """Record path-labeled Places usage counters and emit concise debug telemetry."""
    path = _normalize_places_path(path_label)
    field_map = {
        "request": "requests",
        "success": "successes",
        "empty": "empty",
        "error": "errors",
        "quota": "quota_exhausted",
        "cache_hit": "cache_hits",
        "cache_miss": "cache_misses",
    }
    counter_field = field_map.get(event)

    snapshot: dict[str, int] | None = None
    if counter_field:
        with _places_usage_lock:
            _places_usage_counters[path][counter_field] += 1
            snapshot = dict(_places_usage_counters[path])

    if snapshot is not None:
        logger.debug(
            "[VERIFY][GOOGLE_PLACES][path=%s] event=%s counters=%s ctx=%s",
            path,
            event,
            snapshot,
            context,
        )
    else:
        logger.debug("[VERIFY][GOOGLE_PLACES][path=%s] event=%s ctx=%s", path, event, context)


def get_google_places_usage_counters() -> dict[str, dict[str, int]]:
    """Expose usage counters for observability/tests."""
    with _places_usage_lock:
        return {path: dict(values) for path, values in _places_usage_counters.items()}


# Circuit breaker state per usage path.
_places_circuit_lock = Lock()
_places_circuit_state: dict[str, dict[str, float | int]] = {
    label: {"failures": 0, "open_until": 0.0} for label in _PLACES_PATH_LABELS
}


def _circuit_threshold() -> int:
    try:
        return max(1, int(settings.google_places_circuit_breaker_failure_threshold))
    except (TypeError, ValueError):
        return 5


def _circuit_open_seconds() -> int:
    try:
        return max(1, int(settings.google_places_circuit_breaker_open_seconds))
    except (TypeError, ValueError):
        return 120


def _is_places_circuit_open(path_label: str) -> bool:
    if not settings.google_places_circuit_breaker_enabled:
        return False

    path = _normalize_places_path(path_label)
    now = time.time()
    with _places_circuit_lock:
        state = _places_circuit_state[path]
        open_until = float(state.get("open_until", 0.0))
        if open_until <= 0:
            return False
        if now >= open_until:
            state["open_until"] = 0.0
            state["failures"] = 0
            return False
        return True


def _record_places_circuit_success(path_label: str) -> None:
    if not settings.google_places_circuit_breaker_enabled:
        return
    path = _normalize_places_path(path_label)
    with _places_circuit_lock:
        state = _places_circuit_state[path]
        state["failures"] = 0
        state["open_until"] = 0.0


def _record_places_circuit_failure(path_label: str, *, status_code: int | None = None) -> None:
    if not settings.google_places_circuit_breaker_enabled:
        return

    # Only upstream service failures/quotas should influence breaker state.
    if status_code is not None and status_code != 429 and status_code < 500:
        return

    path = _normalize_places_path(path_label)
    threshold = _circuit_threshold()
    open_seconds = _circuit_open_seconds()
    with _places_circuit_lock:
        state = _places_circuit_state[path]
        failures = int(state.get("failures", 0)) + 1
        state["failures"] = failures
        if failures >= threshold:
            state["open_until"] = time.time() + open_seconds
            logger.warning(
                "[GOOGLE_PLACES][%s] circuit OPEN after %d failures for %ds",
                path,
                failures,
                open_seconds,
            )


def clear_google_places_circuit_breaker() -> None:
    """Reset breaker state for all Google Places paths."""
    with _places_circuit_lock:
        for path in _places_circuit_state:
            _places_circuit_state[path]["failures"] = 0
            _places_circuit_state[path]["open_until"] = 0.0


def get_google_places_circuit_breaker_state() -> dict[str, dict[str, float | int | bool]]:
    """Expose breaker state for observability/tests."""
    now = time.time()
    with _places_circuit_lock:
        out: dict[str, dict[str, float | int | bool]] = {}
        for path, state in _places_circuit_state.items():
            open_until = float(state.get("open_until", 0.0))
            out[path] = {
                "failures": int(state.get("failures", 0)),
                "open_until": open_until,
                "open": open_until > now,
            }
        return out


# Google Places API (New) endpoint
_PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Destination cost tier lookup: estimated nightly hotel rate in USD
# Used by _estimate_activity_price only (hotels use rating-based estimation).
# Hard coding is NOT world data — this is a 4-tier multiplier table.
_PRICE_LEVEL_MULTIPLIERS = {
    0: 0.0,  # FREE (rarely applies to hotels)
    1: 0.5,  # INEXPENSIVE
    2: 1.0,  # MODERATE (baseline)
    3: 2.0,  # EXPENSIVE
    4: 4.0,  # VERY_EXPENSIVE
}

# Baseline nightly rate in USD (moderate hotel, 2 adults)
_BASE_NIGHTLY_RATE_USD = 120.0

# Destination cost tier multipliers (rough regional adjustment)
# Using broad regions only — NOT specific city data (rule: no hardcoded world data)
_DEFAULT_DEST_MULTIPLIER = 1.0  # default for unknown destinations


def dest_hash(dest: str) -> str:
    """Generate a 6-char hash from destination for tile ID namespacing.

    SECURITY: md5 is intentional -- used for deterministic cache key generation,
    not for authentication or integrity. Collision resistance is not required.
    """
    return hashlib.md5(dest.lower().strip().encode()).hexdigest()[:6]  # noqa: S324


# Backward-compatible alias for internal usage
_dest_hash = dest_hash


def _rating_multiplier(rating: Optional[float]) -> float:
    """Map Google Places rating (1-5) to a price multiplier.

    Two-segment linear interpolation:
      3.0 → 0.50 (budget)     gentle slope 3.0–4.0
      4.0 → 1.00 (baseline)   steeper slope 4.0–5.0
      5.0 → 2.50 (luxury)
    Below 3.0 clamps to 0.50; None returns 1.0 (no change).
    """
    if rating is None:
        return 1.0
    if rating <= 3.0:
        return 0.5
    if rating <= 4.0:
        # 3.0→0.5, 4.0→1.0  slope = 0.5/1.0
        return 0.5 + (rating - 3.0) * 0.5
    # 4.0→1.0, 5.0→2.5  slope = 1.5/1.0
    return min(1.0 + (rating - 4.0) * 1.5, 2.5)


_STYLE_BOOST: dict[str, float] = {
    "luxury": 1.6,
    "boutique": 1.3,
    "resort": 1.4,
    "budget": 0.7,
    "hostel": 0.5,
}


def _preference_multiplier(min_stars: int = 0, style: Optional[str] = None) -> float:
    """Adjust price estimate based on user hotel preferences.

    Upward: max(star_boost, style_boost).
    Downward: budget/hostel style overrides to lower estimate.
    """
    style_key = (style or "").strip().lower()
    style_boost = _STYLE_BOOST.get(style_key, 1.0)

    # Budget/hostel styles force downward regardless of star preference
    if style_boost < 1.0:
        return style_boost

    star_boost = 1.0
    if min_stars >= 5:
        star_boost = 1.8
    elif min_stars >= 4:
        star_boost = 1.4
    elif min_stars >= 3:
        star_boost = 1.1

    return max(star_boost, style_boost)


def _estimate_hotel_price(
    nights: int,
    travelers: int,
    rating: Optional[float] = None,
    min_stars: int = 0,
    style: Optional[str] = None,
) -> float:
    """Estimate total hotel price from Google Places rating + user preferences."""
    nightly = (
        _BASE_NIGHTLY_RATE_USD
        * _rating_multiplier(rating)
        * _preference_multiplier(min_stars, style)
    )
    return round(nightly * max(nights, 1) * (1 + 0.05 * max(travelers - 2, 0)), 2)


def _estimate_activity_price(price_level: Optional[int], travelers: int) -> float:
    """Estimate activity price per trip from Google Places price_level."""
    level = price_level if price_level is not None else 2
    multiplier = _PRICE_LEVEL_MULTIPLIERS.get(level, 1.0)
    per_person = 60.0 * multiplier
    return round(per_person * max(travelers, 1), 2)


# Shared mapping: placeholder category → token substrings matched against primaryType.
# Authoritative superset used by both google_places_provider and activity_browser.
PLACE_TYPE_CATEGORY_TOKENS: dict[str, list[str]] = {
    "culture": [
        "museum",
        "landmark",
        "monument",
        "gallery",
        "temple",
        "church",
        "mosque",
        "synagogue",
        "historic",
        "plaza",
        "ruins",
        "fountain",
        "attraction",
        "point_of_interest",
        "tour",
        "travel_agency",
    ],
    "cooking": ["restaurant", "cafe", "bar", "bakery", "meal", "food"],
    "nightlife": ["nightlife", "night", "club"],
    "wellness": ["spa", "wellness", "beauty", "gym", "massage", "yoga"],
    "hiking": ["hike", "trail", "mountain", "trek"],
    "skiing": ["ski", "snow"],
    "diving": ["dive", "snorkel", "reef", "scuba"],
    "adventure": ["nature", "park", "garden", "zoo", "beach", "camp"],
}


def _placeholder_category_for_place_type(primary_type: Optional[str]) -> str:
    """Map Google Places primaryType to placeholder image category."""
    key = (primary_type or "").strip().lower()
    if not key:
        return "activity"

    for category, tokens in PLACE_TYPE_CATEGORY_TOKENS.items():
        if any(token in key for token in tokens):
            return category
    return "activity"


def _get_photo_url(photo_name: str) -> Optional[str]:
    """Do not expose API-keyed photo URLs to clients.

    Returning None forces safe placeholder usage in downstream tile builders.
    """
    _ = photo_name
    return None


_PHOTO_NAME_RE = re.compile(r"^places/[A-Za-z0-9_-]+/photos/[A-Za-z0-9_-]+$")
_PHOTO_SIGNED_TTL_MAX = settings.google_places_photo_signed_ttl_max


def _media_signing_secret() -> str:
    """Return server-side secret for signing media proxy URLs."""
    return get_media_signing_secret()


def build_signed_photo_url(
    session_id: str,
    photo_name: str,
    *,
    max_width: int = 256,
    max_height: int = 256,
    ttl_seconds: int = 3600,
) -> Optional[str]:
    """Construct a signed proxy URL for a Google Places photo.

    Mirrors the signing logic from main._build_signed_google_places_photo_url
    to avoid circular imports. The proxy endpoint at
    /api/media/google-places-photo validates these signatures.

    Returns None when photos are disabled so callers fall back to Unsplash placeholders.
    """
    if not settings.google_places_photos_enabled:
        return None
    if not isinstance(photo_name, str) or not _PHOTO_NAME_RE.fullmatch(photo_name.strip()):
        return None
    secret = _media_signing_secret()
    if not secret:
        return None
    photo_name = photo_name.strip()
    ttl = max(60, min(ttl_seconds, _PHOTO_SIGNED_TTL_MAX))
    exp = int(time.time()) + ttl
    payload = f"{session_id}\n{photo_name}\n{max_width}\n{max_height}\n{exp}".encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    from urllib.parse import urlencode

    query = urlencode(
        {
            "name": photo_name,
            "max_width": max_width,
            "max_height": max_height,
            "exp": exp,
            "sig": sig,
        }
    )
    return f"/api/media/google-places-photo?{query}"


_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# In-memory geocode cache to avoid repeat API calls for the same destination.
# Single threading.Lock is safe here — critical sections are microsecond dict ops.
_geocode_cache: TTLCache = TTLCache(maxsize=1000, ttl=86400)
# threading.Lock OK: <1us critical section (dict lookup + optional API call guard)
_geocode_thread_lock = Lock()


def _parse_geocode_response(data: dict) -> tuple[float, float] | None:
    """Extract (lat, lng) from a Geocoding API response JSON.

    Shared parsing logic used by both async and sync geocode paths.
    Returns None if no results are present.
    """
    results = data.get("results", [])
    if not results:
        return None
    loc = results[0].get("geometry", {}).get("location", {})
    lat = loc.get("lat")
    lng = loc.get("lng")
    if lat is not None and lng is not None:
        return (lat, lng)
    return None


def _extract_country_code(data: dict) -> str | None:
    """Extract ISO country code from a Geocoding API response JSON."""
    results = data.get("results", [])
    if not results:
        return None
    for component in results[0].get("address_components", []):
        if "country" in component.get("types", []):
            return component.get("short_name")
    return None


# Module-level country code cache (populated by geocode calls).
# TTLCache (24h, max 512) prevents unbounded growth; protected by _geocode_thread_lock.
_country_code_cache: TTLCache = TTLCache(maxsize=512, ttl=86400)


def get_country_code(destination: str) -> str | None:
    """Return the cached ISO country code for a destination, or None."""
    key = destination.lower().strip()
    with _geocode_thread_lock:
        return _country_code_cache.get(key)


def get_geocache_stats() -> dict[str, int]:
    """Return geocode + country_code cache stats for admin observability."""
    with _geocode_thread_lock:
        return {
            "geocode_cache_size": len(_geocode_cache),
            "geocode_cache_maxsize": _geocode_cache.maxsize,
            "country_code_cache_size": len(_country_code_cache),
            "country_code_cache_maxsize": _country_code_cache.maxsize,
        }


def clear_geocode_caches() -> dict[str, int]:
    """Clear geocode + country_code caches and return counts of evicted entries."""
    with _geocode_thread_lock:
        geo_count = len(_geocode_cache)
        cc_count = len(_country_code_cache)
        _geocode_cache.clear()
        _country_code_cache.clear()
    return {"geocode_cache": geo_count, "country_code_cache": cc_count}


async def clear_google_places_runtime_caches() -> dict[str, int]:
    """Clear geocode caches and drain enrichment singleflight state under its lock."""
    counts = clear_geocode_caches()
    async with _enrich_inflight_lock:
        _enrich_inflight.clear()
    return counts


async def _geocode_destination_async(dest: str) -> tuple[float, float] | None:
    """Return (lat, lng) for a destination string using the Geocoding API, or None on failure.

    Cache key is normalized (lowercased, stripped) to avoid duplicate lookups for the
    same destination under different casing. Only successful results are cached -- transient
    failures (network errors, quota) are NOT cached so the next request can retry.

    Lock-protected read then release before network I/O to prevent TOCTOU races
    when multiple async tasks geocode the same destination concurrently.
    """
    key = dest.lower().strip()
    path = "geocode"

    with _geocode_thread_lock:
        if key in _geocode_cache:
            record_google_places_usage(path, "cache_hit", cache="geocode")
            return _geocode_cache[key]
    record_google_places_usage(path, "cache_miss", cache="geocode")

    if _is_places_circuit_open(path):
        record_google_places_usage(path, "error", reason="circuit_open", mode="geocode")
        logger.warning("[GOOGLE_PLACES][%s] Circuit open — skipping geocode", path)
        return None

    api_key = settings.google_maps_api_key
    if not api_key:
        record_google_places_usage(path, "error", reason="missing_api_key", mode="geocode")
        return None
    try:
        reserve_places_spend_or_raise(source="google_places:geocode")
        record_google_places_usage(path, "request", mode="geocode")
        client = await _get_places_http_client()
        resp = await client.get(
            _GEOCODE_URL,
            params={"address": dest, "key": api_key},
            timeout=3.0,
        )
        data = resp.json() if resp.status_code == 200 else {}
        if resp.status_code == 429 or resp.status_code >= 500:
            _record_places_circuit_failure(path, status_code=resp.status_code)
            if resp.status_code == 429:
                record_google_places_usage(path, "quota", mode="geocode")
            else:
                record_google_places_usage(
                    path,
                    "error",
                    mode="geocode",
                    status=resp.status_code,
                )
            return None
        _record_places_circuit_success(path)
        coords = _parse_geocode_response(data)
        if coords is not None:
            with _geocode_thread_lock:
                _geocode_cache[key] = coords
                # Cache country code from same response
                cc = _extract_country_code(data)
                if cc:
                    _country_code_cache[key] = cc
            record_google_places_usage(path, "success", mode="geocode")
            logger.debug("[GOOGLE_PLACES] Geocoded '%s' → %s", dest, coords)
            return coords
        # Destination not found (empty results) — cache None to avoid retrying bad input
        with _geocode_thread_lock:
            _geocode_cache[key] = None
        record_google_places_usage(path, "empty", mode="geocode")
    except SpendLimitExceeded as exc:
        record_google_places_usage(path, "error", reason="spend_cap", mode="geocode")
        logger.warning("[GOOGLE_PLACES][%s] Spend guard blocked geocode: %s", path, exc)
    except Exception as exc:
        _record_places_circuit_failure(path, status_code=None)
        record_google_places_usage(path, "error", reason="exception", mode="geocode")
        logger.warning("[GOOGLE_PLACES] Geocode failed for '%s': %s", dest, exc)
        # Transient failure — do NOT cache, allow retry on next request
    return None


def _geocode_destination(dest: str) -> tuple[float, float] | None:
    """Sync version of geocoder (used by tile_service/service.py sync path).

    Uses _geocode_thread_lock to guard _geocode_cache against concurrent
    access (same lock shared by async path for microsecond dict ops).
    """
    key = dest.lower().strip()
    path = "geocode"
    with _geocode_thread_lock:
        if key in _geocode_cache:
            record_google_places_usage(path, "cache_hit", cache="geocode")
            return _geocode_cache[key]
    record_google_places_usage(path, "cache_miss", cache="geocode")

    if _is_places_circuit_open(path):
        record_google_places_usage(path, "error", reason="circuit_open", mode="geocode")
        logger.warning("[GOOGLE_PLACES][%s] Circuit open — skipping geocode", path)
        return None
    api_key = settings.google_maps_api_key
    if not api_key:
        record_google_places_usage(path, "error", reason="missing_api_key", mode="geocode")
        return None
    try:
        reserve_places_spend_or_raise(source="google_places:geocode")
        record_google_places_usage(path, "request", mode="geocode")
        client = _get_sync_client()
        resp = client.get(_GEOCODE_URL, params={"address": dest, "key": api_key}, timeout=3.0)
        data = resp.json() if resp.status_code == 200 else {}
        if resp.status_code == 429 or resp.status_code >= 500:
            _record_places_circuit_failure(path, status_code=resp.status_code)
            if resp.status_code == 429:
                record_google_places_usage(path, "quota", mode="geocode")
            else:
                record_google_places_usage(
                    path,
                    "error",
                    mode="geocode",
                    status=resp.status_code,
                )
            return None
        _record_places_circuit_success(path)
        coords = _parse_geocode_response(data)
        if coords is not None:
            with _geocode_thread_lock:
                _geocode_cache[key] = coords
                # Cache country code from same response
                cc = _extract_country_code(data)
                if cc:
                    _country_code_cache[key] = cc
            record_google_places_usage(path, "success", mode="geocode")
            return coords
        with _geocode_thread_lock:
            _geocode_cache[key] = None
        record_google_places_usage(path, "empty", mode="geocode")
    except SpendLimitExceeded as exc:
        record_google_places_usage(path, "error", reason="spend_cap", mode="geocode")
        logger.warning("[GOOGLE_PLACES][%s] Spend guard blocked geocode: %s", path, exc)
    except Exception as exc:
        _record_places_circuit_failure(path, status_code=None)
        record_google_places_usage(path, "error", reason="exception", mode="geocode")
        logger.warning("[GOOGLE_PLACES] Geocode failed for '%s': %s", dest, exc)
    return None


def _build_places_request(
    query: str,
    included_type: str | None,
    max_results: int,
    price_levels: list[str] | None = None,
    geo: tuple[float, float] | None = None,
    location_radius_m: float = 50000.0,
) -> tuple[dict, dict]:
    """Build the payload and headers for a Places API Text Search request.

    Args:
        query: Text query string.
        included_type: Places API type (e.g. "lodging", "tourist_attraction").
            None omits the filter, letting text relevance drive results.
        max_results: Maximum results to return (capped at 20).
        price_levels: Optional list of PRICE_LEVEL_* enum strings to filter by.
        geo: Optional (lat, lng) tuple for locationBias circle center.
        location_radius_m: Radius in meters for locationBias circle (default 50km).
    """
    api_key = settings.google_maps_api_key
    payload: dict = {
        "textQuery": query,
        "pageSize": min(max_results, 20),
        "languageCode": "en",
    }
    if included_type:
        payload["includedType"] = included_type
    if price_levels:
        payload["priceLevels"] = price_levels
    if geo:
        payload["locationBias"] = {
            "circle": {
                "center": {"latitude": geo[0], "longitude": geo[1]},
                "radius": location_radius_m,
            }
        }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key or "",
        "X-Goog-FieldMask": (
            "places.id,"
            "places.displayName,"
            "places.formattedAddress,"
            "places.photos,"
            "places.location,"
            "places.primaryType,"
            "places.googleMapsUri"
        ),
    }
    return payload, headers


def _parse_places_response(
    response_status: int, response_text: str, response_json: dict
) -> List[Dict[str, Any]]:
    """Parse a Places API response into a list of place dicts."""
    if response_status == 429:
        logger.warning("[GOOGLE_PLACES] Quota exhausted — falling back to mock")
        return []
    if response_status != 200:
        logger.warning("[GOOGLE_PLACES] API error %d: %s", response_status, response_text[:200])
        return []
    return response_json.get("places", [])


async def _call_places_api_async(
    query: str,
    included_type: str | None,
    max_results: int = 5,
    price_levels: list[str] | None = None,
    geo: tuple[float, float] | None = None,
    path_label: str = "logistics",
) -> List[Dict[str, Any]]:
    """
    Call Google Places API Text Search (New) — async version.
    Returns list of place dicts, or empty list on any error.
    Uses httpx.AsyncClient to avoid blocking the event loop.
    """
    path = _normalize_places_path(path_label)
    if _is_places_circuit_open(path):
        record_google_places_usage(path, "error", reason="circuit_open")
        logger.warning("[GOOGLE_PLACES][%s] Circuit open — skipping paid call", path)
        return []

    api_key = settings.google_maps_api_key
    if not api_key:
        record_google_places_usage(path, "error", reason="missing_api_key")
        logger.warning("[GOOGLE_PLACES] Skipped — API key not configured")
        return []

    payload, headers = _build_places_request(query, included_type, max_results, price_levels, geo)
    t0 = time.time()
    record_google_places_usage(path, "request", included_type=included_type)
    try:
        reserve_places_spend_or_raise(source=f"google_places:{path}")
        client = await _get_places_http_client()
        response = await client.post(_PLACES_SEARCH_URL, json=payload, headers=headers, timeout=5.0)
        body = response.json() if response.status_code == 200 else {}
        places = _parse_places_response(response.status_code, response.text, body)
        elapsed = int((time.time() - t0) * 1000)
        if response.status_code == 429 or response.status_code >= 500:
            _record_places_circuit_failure(path, status_code=response.status_code)
        else:
            _record_places_circuit_success(path)
        if places:
            record_google_places_usage(
                path,
                "success",
                included_type=included_type,
                results=len(places),
            )
            logger.info(
                "[GOOGLE_PLACES] %s search: query='%s' results=%d latency=%dms",
                included_type,
                query,
                len(places),
                elapsed,
            )
        else:
            if response.status_code == 429:
                record_google_places_usage(path, "quota", included_type=included_type)
            elif response.status_code >= 400:
                record_google_places_usage(
                    path,
                    "error",
                    included_type=included_type,
                    status=response.status_code,
                )
            else:
                record_google_places_usage(path, "empty", included_type=included_type)
            logger.warning(
                "[GOOGLE_PLACES] %s search EMPTY: query='%s' status=%d latency=%dms",
                included_type,
                query,
                response.status_code,
                elapsed,
            )
        return places
    except SpendLimitExceeded as exc:
        record_google_places_usage(path, "error", included_type=included_type, reason="spend_cap")
        logger.warning("[GOOGLE_PLACES][%s] Spend guard blocked call: %s", path, exc)
        return []
    except Exception as exc:
        _record_places_circuit_failure(path, status_code=None)
        record_google_places_usage(path, "error", included_type=included_type)
        elapsed = int((time.time() - t0) * 1000)
        logger.error(
            "[GOOGLE_PLACES] %s search FAILED: query='%s' error=%s latency=%dms",
            included_type,
            query,
            exc,
            elapsed,
        )
        return []


def _call_places_api(
    query: str,
    included_type: str | None,
    max_results: int = 5,
    price_levels: list[str] | None = None,
    geo: tuple[float, float] | None = None,
    path_label: str = "logistics",
) -> List[Dict[str, Any]]:
    """
    Call Google Places API Text Search (New) — sync version.
    Used by the sync Provider.search() path (tile_service/service.py).
    Returns list of place dicts, or empty list on any error.
    """
    path = _normalize_places_path(path_label)
    if _is_places_circuit_open(path):
        record_google_places_usage(path, "error", reason="circuit_open")
        logger.warning("[GOOGLE_PLACES][%s] Circuit open — skipping paid call", path)
        return []

    api_key = settings.google_maps_api_key
    if not api_key:
        record_google_places_usage(path, "error", reason="missing_api_key")
        logger.warning("[GOOGLE_PLACES] Skipped — API key not configured")
        return []

    payload, headers = _build_places_request(query, included_type, max_results, price_levels, geo)
    t0 = time.time()
    record_google_places_usage(path, "request", included_type=included_type)
    try:
        reserve_places_spend_or_raise(source=f"google_places:{path}")
        client = _get_sync_client()
        response = client.post(_PLACES_SEARCH_URL, json=payload, headers=headers, timeout=5.0)
        body = response.json() if response.status_code == 200 else {}
        places = _parse_places_response(response.status_code, response.text, body)
        elapsed = int((time.time() - t0) * 1000)
        if response.status_code == 429 or response.status_code >= 500:
            _record_places_circuit_failure(path, status_code=response.status_code)
        else:
            _record_places_circuit_success(path)
        if places:
            record_google_places_usage(
                path,
                "success",
                included_type=included_type,
                results=len(places),
            )
            logger.info(
                "[GOOGLE_PLACES] %s search: query='%s' results=%d latency=%dms",
                included_type,
                query,
                len(places),
                elapsed,
            )
        else:
            if response.status_code == 429:
                record_google_places_usage(path, "quota", included_type=included_type)
            elif response.status_code >= 400:
                record_google_places_usage(
                    path,
                    "error",
                    included_type=included_type,
                    status=response.status_code,
                )
            else:
                record_google_places_usage(path, "empty", included_type=included_type)
            logger.warning(
                "[GOOGLE_PLACES] %s search EMPTY: query='%s' status=%d latency=%dms",
                included_type,
                query,
                response.status_code,
                elapsed,
            )
        return places
    except SpendLimitExceeded as exc:
        record_google_places_usage(path, "error", included_type=included_type, reason="spend_cap")
        logger.warning("[GOOGLE_PLACES][%s] Spend guard blocked call: %s", path, exc)
        return []
    except Exception as exc:
        _record_places_circuit_failure(path, status_code=None)
        record_google_places_usage(path, "error", included_type=included_type)
        elapsed = int((time.time() - t0) * 1000)
        logger.error(
            "[GOOGLE_PLACES] %s search FAILED: query='%s' error=%s latency=%dms",
            included_type,
            query,
            exc,
            elapsed,
        )
        return []


def _hotel_query(dest: str, hotel_settings: Any) -> str:
    """Build a hotel search query that reflects user star preference."""
    settings_dict: dict = {}
    if hasattr(hotel_settings, "model_dump"):
        settings_dict = hotel_settings.model_dump()
    elif isinstance(hotel_settings, dict):
        settings_dict = hotel_settings
    min_stars: int = settings_dict.get("min_stars") or 0

    # Map star preference to a text qualifier — reinforces priceLevels filter in the API call
    if min_stars >= 5:
        qualifier = "5 star luxury hotels"
    elif min_stars >= 4:
        qualifier = "4 star hotels"
    elif min_stars >= 3:
        qualifier = "3 star hotels"
    elif min_stars >= 1:
        qualifier = "budget hotels"
    else:
        qualifier = "hotels"  # no preference — let Google rank by prominence

    return f"{qualifier} in {dest}"


def _hotel_price_levels(hotel_settings: Any) -> list[str] | None:
    """Map min_stars to a priceLevels filter list for the Places API.

    Passes an explicit server-side filter in addition to the text query qualifier,
    giving Google two independent signals about price tier.
    Returns None when no preference (no filter applied).
    """
    settings_dict: dict = {}
    if hasattr(hotel_settings, "model_dump"):
        settings_dict = hotel_settings.model_dump()
    elif isinstance(hotel_settings, dict):
        settings_dict = hotel_settings
    min_stars: int = settings_dict.get("min_stars") or 0

    if min_stars >= 5:
        return ["PRICE_LEVEL_VERY_EXPENSIVE"]
    if min_stars >= 4:
        return ["PRICE_LEVEL_EXPENSIVE", "PRICE_LEVEL_VERY_EXPENSIVE"]
    if min_stars >= 3:
        return ["PRICE_LEVEL_MODERATE", "PRICE_LEVEL_EXPENSIVE", "PRICE_LEVEL_VERY_EXPENSIVE"]
    if min_stars >= 1:
        return ["PRICE_LEVEL_INEXPENSIVE", "PRICE_LEVEL_MODERATE"]
    return None  # no filter — let Google rank freely


class GooglePlacesHotelProvider(Provider):
    name = "google_places_hotel"

    async def search_async(self, ctx: SearchContext) -> List[Tile]:
        """Async search — use from async contexts (logistics_node) to avoid blocking the event loop."""
        dest = ctx.destination or "Somewhere"
        # Cap at 3: UI shows 3-5 hotels, builder uses top-1. Saves ~40% hotel photo proxy calls.
        max_results = min(ctx.max_results_per_vertical, 3)
        geo: tuple[float, float] | None = None
        if ctx.destination_lat is not None and ctx.destination_lng is not None:
            geo = (ctx.destination_lat, ctx.destination_lng)
        elif dest != "Somewhere":
            geo = await _geocode_destination_async(dest)
        places = await _call_places_api_async(
            query=_hotel_query(dest, ctx.hotel_settings),
            included_type="lodging",
            max_results=max_results,
            price_levels=_hotel_price_levels(ctx.hotel_settings),
            geo=geo,
            path_label="logistics",
        )
        tiles = self._build_tiles(ctx, places)
        return tiles

    def search(self, ctx: SearchContext) -> List[Tile]:
        """Sync search — used by tile_service/service.py (non-async path)."""
        dest = ctx.destination or "Somewhere"
        # Cap at 3: UI shows 3-5 hotels, builder uses top-1. Saves ~40% hotel photo proxy calls.
        max_results = min(ctx.max_results_per_vertical, 3)
        geo: tuple[float, float] | None = None
        if ctx.destination_lat is not None and ctx.destination_lng is not None:
            geo = (ctx.destination_lat, ctx.destination_lng)
        elif dest != "Somewhere":
            geo = _geocode_destination(dest)
        places = _call_places_api(
            query=_hotel_query(dest, ctx.hotel_settings),
            included_type="lodging",
            max_results=max_results,
            price_levels=_hotel_price_levels(ctx.hotel_settings),
            geo=geo,
            path_label="logistics",
        )
        tiles = self._build_tiles(ctx, places)
        return tiles

    def _build_tiles(self, ctx: SearchContext, places: List[Dict[str, Any]]) -> List[Tile]:
        """Build Tile objects from raw Places API results."""
        dest = ctx.destination or "Somewhere"
        dest_id = _dest_hash(dest)
        total_travelers = (ctx.adults or 0) + (ctx.children or 0) or 2

        # Estimate nights
        nights = 4
        if ctx.start_date and ctx.end_date:
            try:
                from datetime import datetime

                sd = datetime.strptime(ctx.start_date, "%Y-%m-%d")
                ed = datetime.strptime(ctx.end_date, "%Y-%m-%d")
                nights = max((ed - sd).days, 1)
            except ValueError:
                pass

        # Extract user hotel preferences for price estimation
        _hs_dict: dict = {}
        if hasattr(ctx.hotel_settings, "model_dump"):
            _hs_dict = ctx.hotel_settings.model_dump()
        elif isinstance(ctx.hotel_settings, dict):
            _hs_dict = ctx.hotel_settings
        _min_stars: int = _hs_dict.get("min_stars") or 0
        _style: Optional[str] = _hs_dict.get("style")

        tiles: List[Tile] = []
        for i, place in enumerate(places):
            place_id = place.get("id", f"gp_hotel_{dest_id}_{i}")
            name = (place.get("displayName") or {}).get("text", f"Hotel in {dest}")
            address = place.get("formattedAddress", dest)
            # rating/userRatingCount are Enterprise fields — not in our Pro field mask.
            rating = None
            review_count = None

            photos = place.get("photos") or []
            photo_name = photos[0].get("name") if photos else None
            image_url = _get_photo_url(photo_name) or get_placeholder_image(
                "hotel", seed=f"{dest}-hotel-{i}"
            )

            loc = place.get("location") or {}
            geo = None
            if loc.get("latitude") is not None and loc.get("longitude") is not None:
                geo = Geo(lat=loc["latitude"], lng=loc["longitude"])

            # Enterprise fields (priceLevel, priceRange, rating, userRatingCount)
            # stripped from FieldMask to stay on Pro tier ($5/1k vs $32/1k).
            total_price = _estimate_hotel_price(
                nights, total_travelers, rating=rating, min_stars=_min_stars, style=_style
            )
            # Positional variance: top-ranked results skew ~15% pricier
            n = len(places)
            if n > 1:
                position_factor = 1.0 + 0.15 * (n - i - 1) / (n - 1)
                total_price = round(total_price * position_factor, 2)
            nightly_rate = round(total_price / max(nights, 1), 2)
            tax_and_service = round(total_price * 0.12, 2)
            property_fee = round(nights * 15, 2)
            total_inclusive = round(total_price + tax_and_service + property_fee, 2)

            deeplink = (
                f"https://www.google.com/travel/hotels/entity/{place_id}"
                if place_id and not place_id.startswith("gp_hotel_")
                else place.get("googleMapsUri", "")
            ) or place.get("googleMapsUri", "")
            # editorialSummary is Enterprise+Atmosphere — not in our Pro field mask.
            tiles.append(
                Tile(
                    id=f"tile_gp_hotel_{dest_id}_{i}",
                    type="hotel",
                    partner=self.name,
                    partner_product_id=place_id,
                    title=name,
                    subtitle=address,
                    image_url=image_url,
                    price_estimate=nightly_rate,
                    live_price=None,
                    currency=ctx.currency or "USD",
                    price_basis="per_night",
                    is_estimate_only=True,
                    deeplink=deeplink,
                    rating=rating,
                    review_count=review_count,
                    location_label=address,
                    geo=geo,
                    tags=["hotel", "google_places"],
                    availability_status="unknown",
                    meta={
                        "destination": dest,
                        "nights": nights,
                        "adults": ctx.adults,
                        "children": ctx.children,
                        "place_id": place_id,
                        "photo_name": photo_name,
                    },
                    score=0.8 - 0.02 * i,
                    source="live",
                    total_inclusive=total_inclusive,
                    tax_and_service_fee=tax_and_service,
                    property_fee=property_fee,
                    is_refundable=False,
                    cancel_policy_summary="Contact hotel for cancellation policy",
                    provider="google_places",
                )
            )

        return tiles


class GooglePlacesActivityProvider(Provider):
    name = "google_places_activity"

    def _make_query(self, ctx: SearchContext) -> str:
        """Build the Places text query from activity category settings."""
        dest = ctx.destination or "Somewhere"
        activity_settings = ctx.activity_settings or {}
        if hasattr(activity_settings, "model_dump"):
            activity_settings = activity_settings.model_dump()
        categories: List[str] = []
        if isinstance(activity_settings, dict):
            categories = activity_settings.get("categories") or []
        if categories:
            return f"{' or '.join(categories[:3])} activities in {dest}"
        return f"tourist attractions and activities in {dest}"

    def _has_categories(self, ctx: SearchContext) -> bool:
        """True when the user selected explicit activity categories."""
        act = ctx.activity_settings or {}
        if hasattr(act, "model_dump"):
            act = act.model_dump()
        if isinstance(act, dict):
            return bool(act.get("categories"))
        return False

    async def search_async(self, ctx: SearchContext) -> List[Tile]:
        """Async search — use from async contexts (logistics_node) to avoid blocking the event loop."""
        dest = ctx.destination or "Somewhere"
        max_results = min(ctx.max_results_per_vertical, 10)
        geo: tuple[float, float] | None = None
        if ctx.destination_lat is not None and ctx.destination_lng is not None:
            geo = (ctx.destination_lat, ctx.destination_lng)
        elif dest != "Somewhere":
            geo = await _geocode_destination_async(dest)
        # When user categories are set, omit includedType so Google's text
        # search handles relevance (nightclubs, bike tours, etc. aren't
        # "tourist_attraction").  Keep the filter for the generic fallback.
        type_filter = None if self._has_categories(ctx) else "tourist_attraction"
        places = await _call_places_api_async(
            query=self._make_query(ctx),
            included_type=type_filter,
            max_results=max_results,
            geo=geo,
            path_label="logistics",
        )
        tiles = self._build_tiles(ctx, places)
        return tiles

    def search(self, ctx: SearchContext) -> List[Tile]:
        """Sync search — used by tile_service/service.py (non-async path)."""
        dest = ctx.destination or "Somewhere"
        max_results = min(ctx.max_results_per_vertical, 10)
        geo: tuple[float, float] | None = None
        if ctx.destination_lat is not None and ctx.destination_lng is not None:
            geo = (ctx.destination_lat, ctx.destination_lng)
        elif dest != "Somewhere":
            geo = _geocode_destination(dest)
        type_filter = None if self._has_categories(ctx) else "tourist_attraction"
        places = _call_places_api(
            query=self._make_query(ctx),
            included_type=type_filter,
            max_results=max_results,
            geo=geo,
            path_label="logistics",
        )
        tiles = self._build_tiles(ctx, places)
        return tiles

    def _build_tiles(self, ctx: SearchContext, places: List[Dict[str, Any]]) -> List[Tile]:
        """Build Tile objects from raw Places API results."""
        dest = ctx.destination or "Somewhere"
        dest_id = _dest_hash(dest)
        # Include category hash in tile IDs so different category searches
        # produce distinct IDs (prevents frontend false-dedup).
        _act_settings = ctx.activity_settings or {}
        if hasattr(_act_settings, "model_dump"):
            _act_settings = _act_settings.model_dump()
        _act_cats = _act_settings.get("categories", []) if isinstance(_act_settings, dict) else []
        if _act_cats:
            _cat_sig = _dest_hash("_".join(sorted(str(c).lower() for c in _act_cats)))
            dest_id = f"{dest_id}_{_cat_sig}"
        total_travelers = (ctx.adults or 0) + (ctx.children or 0) or 2

        # Extract user categories from ctx so tiles carry the semantic categories
        # that produced them (fixes taxonomy mismatch: Google primaryType != user cats).
        _user_cats: list[str] = []
        _ctx_act = ctx.activity_settings or {}
        if hasattr(_ctx_act, "model_dump"):
            _ctx_act = _ctx_act.model_dump()
        if isinstance(_ctx_act, dict):
            _user_cats = [str(c).lower().strip() for c in _ctx_act.get("categories", []) if c]

        tiles: List[Tile] = []
        for i, place in enumerate(places):
            place_id = place.get("id", f"gp_act_{dest_id}_{i}")
            name = (place.get("displayName") or {}).get("text", f"Activity in {dest}")
            address = place.get("formattedAddress", dest)
            # rating/userRatingCount are Enterprise fields — not in our Pro field mask.
            rating = None
            review_count = None

            photos = place.get("photos") or []
            photo_name = photos[0].get("name") if photos else None
            primary_type = place.get("primaryType", "attraction")
            placeholder_category = _placeholder_category_for_place_type(primary_type)
            image_url = _get_photo_url(photo_name) or get_placeholder_image(
                placeholder_category,
                seed=f"{dest}-{primary_type}-{place_id}",
            )

            loc = place.get("location") or {}
            geo = None
            if loc.get("latitude") is not None and loc.get("longitude") is not None:
                geo = Geo(lat=loc["latitude"], lng=loc["longitude"])

            # Enterprise fields (priceLevel, priceRange, rating, userRatingCount)
            # stripped from FieldMask — use heuristic estimate
            price = _estimate_activity_price(None, total_travelers)
            tax_and_service = round(price * 0.08, 2)
            total_inclusive = round(price + tax_and_service, 2)

            deeplink = (
                place.get("googleMapsUri")
                or f"https://www.google.com/maps/place/?q=place_id:{place_id}"
            )
            # editorialSummary is Enterprise+Atmosphere — not in our Pro field mask.
            tiles.append(
                Tile(
                    id=f"tile_gp_activity_{dest_id}_{i}",
                    type="activity",
                    partner=self.name,
                    partner_product_id=place_id,
                    title=name,
                    subtitle=address,
                    image_url=image_url,
                    price_estimate=price,
                    live_price=None,
                    currency=ctx.currency or "USD",
                    price_basis="per_trip",
                    is_estimate_only=True,
                    deeplink=deeplink,
                    rating=rating,
                    review_count=review_count,
                    location_label=address,
                    geo=geo,
                    tags=["activity", "google_places", primary_type],
                    availability_status="unknown",
                    meta={
                        "destination": dest,
                        "adults": ctx.adults,
                        "children": ctx.children,
                        "place_id": place_id,
                        "category": primary_type,
                        "source_categories": _user_cats,
                        "photo_name": photo_name,
                    },
                    score=0.75 - 0.02 * i,
                    source="live",
                    total_inclusive=total_inclusive,
                    tax_and_service_fee=tax_and_service,
                    property_fee=None,
                    is_refundable=True,
                    cancel_policy_summary="Free cancellation typically available",
                    provider="google_places",
                )
            )

        return tiles


# =============================================================================
# Activity Enrichment — ground LLM-generated activities with Google Places
# =============================================================================

# Field mask for enrichment — Pro tier only ($5/1k).
# Enterprise fields (rating, userRatingCount, editorialSummary, priceLevel,
# priceRange) deliberately excluded to avoid $32/1k Enterprise billing.
_ENRICH_FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.location,"
    "places.photos,"
    "places.googleMapsUri,"
    "places.shortFormattedAddress"
)


# Aggressive enrichment cache: L1 memory + L2 ResponseCache.
_ENRICH_L1_TTL_SECONDS = 86400  # 24h hot cache
_ENRICH_L1_MAX_SIZE = 2048
_ENRICH_L2_TTL_HOURS = int(
    getattr(
        settings, "google_places_enrichment_cache_ttl_hours", settings.google_places_cache_ttl_hours
    )
)
_enrich_mem = MemoryCache(maxsize=_ENRICH_L1_MAX_SIZE, ttl=_ENRICH_L1_TTL_SECONDS)
_ENRICH_MAX_PARALLEL_DEFAULT = 4
_ENRICH_RETRY_ATTEMPTS_DEFAULT = 2
_ENRICH_RETRY_BASE_MS_DEFAULT = 250

# Singleflight dedup for concurrent enrichment of the same activity title.
_enrich_inflight: dict[str, asyncio.Future[dict]] = {}
_enrich_inflight_lock = asyncio.Lock()


def _transplant_enrichment(target: dict, source: dict) -> dict:
    """Copy GP enrichment fields from source to target activity."""
    out = dict(target)
    for key in ("google_place_id", "coordinates", "deeplink", "photo_name"):
        if source.get(key):
            out[key] = source[key]
    if source.get("meta", {}).get("photo_name"):
        out.setdefault("meta", {})["photo_name"] = source["meta"]["photo_name"]
    return out


def _normalize_for_cache(value: str) -> str:
    return " ".join((value or "").lower().strip().split())


def _normalize_title_for_cache(title: str) -> str:
    """Strip specialist qualifiers before normalizing for cache key.

    E.g. "USAT Liberty Shipwreck Dive" and "USAT Liberty Shipwreck Diving
    Experience" collapse to the same key, sharing one cache entry.

    Tradeoff: titles differing only by sport qualifier (e.g. "Kuta Reef Dive"
    vs "Kuta Reef Surf") will share a cache entry. This is acceptable because
    the Google Places query uses the full destination for disambiguation, and
    the same physical location is returned regardless of sport qualifier.
    """
    simplified = _simplify_specialist_title(title)
    return _normalize_for_cache(simplified)


def _enrich_max_parallel() -> int:
    raw = getattr(settings, "google_places_enrichment_max_parallel", _ENRICH_MAX_PARALLEL_DEFAULT)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return _ENRICH_MAX_PARALLEL_DEFAULT


def _enrich_retry_attempts() -> int:
    raw = getattr(
        settings,
        "google_places_enrichment_retry_attempts",
        _ENRICH_RETRY_ATTEMPTS_DEFAULT,
    )
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return _ENRICH_RETRY_ATTEMPTS_DEFAULT


def _enrich_backoff_seconds(attempt: int) -> float:
    raw = getattr(settings, "google_places_enrichment_retry_base_ms", _ENRICH_RETRY_BASE_MS_DEFAULT)
    try:
        base_ms = max(1, int(raw))
    except (TypeError, ValueError):
        base_ms = _ENRICH_RETRY_BASE_MS_DEFAULT
    return (base_ms * (2**attempt)) / 1000.0


def _retry_after_seconds(header: str | None) -> float | None:
    if not header:
        return None
    try:
        seconds = float(header)
    except (TypeError, ValueError):
        return None
    return max(0.0, seconds)


def _enrich_cache_key(title: str, destination: str) -> str:
    title_norm = _normalize_title_for_cache(title) or "unknown"
    dest_norm = _normalize_for_cache(destination) or "unknown"
    query_sig = stable_hash(
        {
            "text_query": f"{title_norm} {dest_norm}".strip(),
            "page_size": 1,
            "language_code": "en",
            "field_mask": _ENRICH_FIELD_MASK,
        }
    )
    return make_cache_key(
        "places",
        "enrich",
        "v3",
        dest_norm[:80],
        title_norm[:120],
        f"q{query_sig}",
    )


async def _get_cached_enrichment(cache_key: str) -> dict[str, Any] | None:
    """Load enrichment payload from L2 and promote to L1."""
    from app.db import _get_async_session_factory
    from app.db_models import ResponseCache

    cached = _enrich_mem.get(cache_key)
    if cached is not None:
        return cached

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

            _enrich_mem.set(cache_key, row.response_json)
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
    except Exception as e:
        logger.debug("[GOOGLE_PLACES] Enrichment L2 read failed key=%s err=%s", cache_key, e)
        return None


async def _set_cached_enrichment(cache_key: str, payload: dict[str, Any]) -> None:
    """Write enrichment payload to L1 + L2 cache."""
    from app.db import _get_async_session_factory

    _enrich_mem.set(cache_key, payload)
    async_session_factory = _get_async_session_factory()
    try:
        async with async_session_factory() as db:
            try:
                await l2_upsert(
                    db,
                    cache_key=cache_key,
                    cache_type="tiles",
                    response_json=payload,
                    ttl=timedelta(hours=_ENRICH_L2_TTL_HOURS),
                )
            except Exception as e:
                await db.rollback()
                logger.debug(
                    "[GOOGLE_PLACES] Enrichment L2 write failed key=%s err=%s", cache_key, e
                )
    except Exception as e:
        logger.debug("[GOOGLE_PLACES] Enrichment L2 session failed key=%s err=%s", cache_key, e)


def _apply_place_to_activity(activity: dict, place: dict, title: str, travelers: int = 1) -> dict:
    """Apply a cached/live Places match onto one activity payload."""
    enriched = dict(activity)
    loc = place.get("location", {})

    # Overwrite coordinates with verified data ([lng, lat] Mapbox convention)
    if loc.get("latitude") is not None and loc.get("longitude") is not None:
        enriched["coordinates"] = [loc["longitude"], loc["latitude"]]

    # Overwrite image with Google Places photo
    photos = place.get("photos") or []
    if photos:
        photo_name = photos[0].get("name", "")
        if isinstance(photo_name, str) and photo_name:
            enriched["photo_name"] = photo_name
            meta = dict(enriched.get("meta") or {})
            meta["photo_name"] = photo_name
            enriched["meta"] = meta

        photo_url = _get_photo_url(photo_name)
        if photo_url:
            enriched["image_url"] = photo_url

    # Add metadata
    place_id = place.get("id", "")
    enriched["google_place_id"] = place_id
    enriched["deeplink"] = (
        place.get("googleMapsUri") or f"https://www.google.com/maps/place/?q=place_id:{place_id}"
    )

    # rating/userRatingCount are Enterprise-tier fields — NOT in our Pro field mask.
    # LLM-sourced ratings (from specialist output) are preserved; no Places override.

    # Provide heuristic price for tiles without LLM price.
    if enriched.get("price_estimate") is None:
        enriched["price_estimate"] = _estimate_activity_price(None, travelers=travelers)
        enriched["price_basis"] = "per_person"
        enriched["currency"] = "USD"
        enriched["is_estimate_only"] = True

    # Store human-readable location label for detail views
    location_label = place.get("shortFormattedAddress")
    if location_label:
        enriched["location_label"] = location_label

    # editorialSummary is Enterprise+Atmosphere — not in our Pro field mask.

    logger.debug(
        "[GOOGLE_PLACES] Enriched '%s' → place_id=%s coords=%s",
        title,
        place_id,
        enriched.get("coordinates"),
    )
    return enriched


async def _enrich_single_activity(
    client: httpx.AsyncClient,
    activity: dict,
    destination: str,
    api_key: str,
    path_label: str,
    travelers: int = 1,
) -> dict:
    """Resolve a single activity against Google Places Text Search.

    On match: overwrite coordinates, image_url; add place_id, deeplink.
    On miss/error: return activity unchanged (graceful degradation).
    """
    title = activity.get("title", "")
    if not title:
        return activity

    # Skip enrichment if activity already has coordinates and photo
    coords = activity.get("coordinates")
    has_coords = (
        isinstance(coords, list)
        and len(coords) == 2
        and all(isinstance(v, (int, float)) for v in coords[:2])
    ) or (
        isinstance(coords, dict)
        and isinstance(coords.get("lat"), (int, float))
        and isinstance(coords.get("lng"), (int, float))
    )
    has_photo = bool(activity.get("photo_name") or activity.get("image_url"))
    if has_coords and has_photo:
        return activity

    path = _normalize_places_path(path_label)
    cache_key = _enrich_cache_key(title, destination)
    cached_payload = await _get_cached_enrichment(cache_key)
    if cached_payload is not None:
        record_google_places_usage(path, "cache_hit", cache="enrichment")
        if cached_payload.get("matched"):
            place = cached_payload.get("place")
            if isinstance(place, dict):
                try:
                    return _apply_place_to_activity(activity, place, title, travelers=travelers)
                except Exception as e:
                    logger.warning(
                        "[GOOGLE_PLACES] Cached enrichment parse failed for '%s': %s", title, e
                    )
        return activity

    record_google_places_usage(path, "cache_miss", cache="enrichment")

    # Simplify specialist titles for better GP matching
    simplified = _simplify_specialist_title(title)
    query = f"{simplified} {destination}"
    max_attempts = _enrich_retry_attempts()
    places: list[dict] = []
    for attempt in range(max_attempts):
        if _is_places_circuit_open(path):
            record_google_places_usage(path, "error", mode="enrichment", reason="circuit_open")
            logger.warning("[GOOGLE_PLACES][%s] Circuit open — skipping enrichment", path)
            return activity

        record_google_places_usage(path, "request", mode="enrichment")
        try:
            reserve_places_spend_or_raise(source=f"google_places_enrich:{path}")
            resp = await client.post(
                _PLACES_SEARCH_URL,
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": api_key,
                    "X-Goog-FieldMask": _ENRICH_FIELD_MASK,
                },
                json={
                    "textQuery": query,
                    "pageSize": 1,
                    "languageCode": "en",
                },
                timeout=8.0,
            )
        except SpendLimitExceeded as exc:
            record_google_places_usage(path, "error", mode="enrichment", reason="spend_cap")
            logger.warning("[GOOGLE_PLACES][%s] Spend guard blocked enrichment: %s", path, exc)
            return activity
        except Exception as e:
            _record_places_circuit_failure(path, status_code=None)
            if attempt < max_attempts - 1:
                await asyncio.sleep(_enrich_backoff_seconds(attempt))
                continue
            record_google_places_usage(path, "error", mode="enrichment")
            logger.warning("[GOOGLE_PLACES] Enrichment failed for '%s': %s", title, e)
            return activity

        if resp.status_code == 429:
            _record_places_circuit_failure(path, status_code=429)
            record_google_places_usage(path, "quota", mode="enrichment")
            if attempt < max_attempts - 1:
                retry_after = _retry_after_seconds(resp.headers.get("Retry-After"))
                await asyncio.sleep(
                    retry_after if retry_after is not None else _enrich_backoff_seconds(attempt)
                )
                continue
            logger.warning("[GOOGLE_PLACES] Enrichment quota exhausted for '%s'", title)
            return activity

        if resp.status_code >= 500:
            _record_places_circuit_failure(path, status_code=resp.status_code)
            record_google_places_usage(
                path,
                "error",
                mode="enrichment",
                status=resp.status_code,
            )
            if attempt < max_attempts - 1:
                await asyncio.sleep(_enrich_backoff_seconds(attempt))
                continue
            logger.warning(
                "[GOOGLE_PLACES] Enrichment API error %d for '%s': %s",
                resp.status_code,
                title,
                resp.text[:200],
            )
            return activity

        if resp.status_code != 200:
            record_google_places_usage(
                path,
                "error",
                mode="enrichment",
                status=resp.status_code,
            )
            logger.warning(
                "[GOOGLE_PLACES] Enrichment API error %d for '%s': %s",
                resp.status_code,
                title,
                resp.text[:200],
            )
            return activity

        try:
            body = resp.json()
        except Exception as e:
            record_google_places_usage(
                path,
                "error",
                mode="enrichment",
                status=resp.status_code,
                reason="invalid_json",
            )
            if attempt < max_attempts - 1:
                await asyncio.sleep(_enrich_backoff_seconds(attempt))
                continue
            logger.warning(
                "[GOOGLE_PLACES] Enrichment response parse failed for '%s': %s", title, e
            )
            return activity

        _record_places_circuit_success(path)
        places = body.get("places", [])
        break

    if not places:
        record_google_places_usage(path, "empty", mode="enrichment")
        await _set_cached_enrichment(cache_key, {"matched": False})
        # Fallback deeplink for un-enriched tiles so they never have empty deeplinks
        if not activity.get("deeplink") and not activity.get("deeplink_url"):
            from urllib.parse import quote

            tile_name = activity.get("title", "")
            activity["deeplink"] = (
                f"https://www.google.com/maps/search/{quote(f'{tile_name} {destination}')}"
            )
        return activity

    try:
        place = places[0]
        # Validate relevance via token overlap — specialist titles like
        # "USAT Liberty Shipwreck Dive" may get an unrelated GP result.
        # Reject GP results below 60% overlap to avoid enriching with
        # unrelated places (e.g. a restaurant matching a dive site name).
        gp_name = ""
        display_name = place.get("displayName")
        if isinstance(display_name, dict):
            gp_name = display_name.get("text", "")
        simplified_title = _simplify_specialist_title(title)
        overlap = _token_overlap_ratio(simplified_title, gp_name)
        # Also check reverse overlap — GP name tokens found in simplified title.
        # Accept if EITHER direction meets threshold (handles partial name matches
        # like GP "Liberty Wreck" for specialist "USAT Liberty Shipwreck").
        reverse_overlap = _token_overlap_ratio(gp_name, simplified_title) if gp_name else 0.0
        best_overlap = max(overlap, reverse_overlap)
        if best_overlap < 0.45 and gp_name:
            logger.debug(
                "[GOOGLE_PLACES] Low overlap (%.0f%%) for '%s' vs GP '%s' — rejecting",
                best_overlap * 100,
                title,
                gp_name,
            )
            await _set_cached_enrichment(cache_key, {"matched": False})
            record_google_places_usage(path, "empty", mode="enrichment", reason="low_overlap")
            # Fallback deeplink so tile is never without a link
            if not activity.get("deeplink") and not activity.get("deeplink_url"):
                from urllib.parse import quote as _quote

                activity["deeplink"] = (
                    f"https://www.google.com/maps/search/"
                    f"{_quote(f'{simplified_title} {destination}')}"
                )
            return activity
        enriched = _apply_place_to_activity(activity, place, title, travelers=travelers)
        await _set_cached_enrichment(cache_key, {"matched": True, "place": place})
        record_google_places_usage(path, "success", mode="enrichment")
        return enriched
    except Exception as e:
        record_google_places_usage(path, "error", mode="enrichment")
        logger.warning("[GOOGLE_PLACES] Enrichment parse failed for '%s': %s", title, e)

    return activity


async def enrich_activities_with_places(
    activities: list[dict],
    destination: str,
    path_label: str = "tier2_enrich",
    travelers: int = 1,
) -> list[dict]:
    """Post-process LLM-generated activities by resolving each against Google Places.

    For each activity:
    1. Search "{title} {destination}" via Text Search
    2. If match: overwrite coordinates + image_url, add place_id/deeplink
    3. If no match: keep LLM data as-is (graceful degradation)

    Feature-gated: caller must check settings.use_google_places_provider before calling.

    Returns the enriched list.
    """
    api_key = settings.google_maps_api_key
    if not api_key or not activities:
        return activities

    def _has_enrichment_image(activity: dict[str, Any]) -> bool:
        meta = activity.get("meta")
        meta_dict = meta if isinstance(meta, dict) else {}
        return bool(
            activity.get("image_url") or activity.get("photo_name") or meta_dict.get("photo_name")
        )

    def _has_enrichment_deeplink(activity: dict[str, Any]) -> bool:
        return bool(
            activity.get("deeplink") or activity.get("deeplink_url") or activity.get("maps_uri")
        )

    def _has_usable_coordinates(activity: dict[str, Any]) -> bool:
        coords = activity.get("coordinates")
        if isinstance(coords, dict):
            lat = coords.get("lat")
            lng = coords.get("lng")
            return isinstance(lat, (int, float)) and isinstance(lng, (int, float))
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            lng, lat = coords[0], coords[1]
            return isinstance(lat, (int, float)) and isinstance(lng, (int, float))

        geo = activity.get("geo")
        if isinstance(geo, dict):
            lat = geo.get("lat")
            lng = geo.get("lng")
            return isinstance(lat, (int, float)) and isinstance(lng, (int, float))
        return False

    if all(
        isinstance(activity, dict)
        and bool(activity.get("google_place_id") or activity.get("place_id"))
        and _has_usable_coordinates(activity)
        and _has_enrichment_image(activity)
        and _has_enrichment_deeplink(activity)
        for activity in activities
    ):
        return activities

    path = _normalize_places_path(path_label)
    t0 = time.time()
    semaphore = asyncio.Semaphore(_enrich_max_parallel())

    # Enrich all provided activities; concurrency is controlled by semaphore.
    max_enrich = min(len(activities), settings.google_places_enrichment_cap)
    to_enrich = activities[:max_enrich]
    passthrough = activities[max_enrich:]

    client = await _get_places_http_client()

    async def _enrich_with_limit(activity: dict) -> dict:
        title_key = (
            _normalize_title_for_cache(activity.get("title", ""))
            + "::"
            + _normalize_for_cache(destination)
        )

        # Register-or-join under a single lock acquisition
        future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        async with _enrich_inflight_lock:
            existing_future = _enrich_inflight.get(title_key)
            if existing_future is not None:
                pass_to_wait = existing_future
            else:
                _enrich_inflight[title_key] = future
                pass_to_wait = None

        if pass_to_wait is not None:
            try:
                result = await asyncio.shield(pass_to_wait)
                return _transplant_enrichment(activity, result)
            except Exception:
                return activity

        try:
            async with semaphore:
                result = await _enrich_single_activity(
                    client, activity, destination, api_key, path, travelers=travelers
                )
            future.set_result(result)
            return result
        except Exception as exc:
            if not future.done():
                future.set_exception(exc)
            raise
        finally:
            async with _enrich_inflight_lock:
                _enrich_inflight.pop(title_key, None)

    coros = [_enrich_with_limit(activity) for activity in to_enrich]
    raw_results = await asyncio.gather(*coros, return_exceptions=True)

    # On exception, keep original activity (graceful degradation)
    final: list[dict] = []
    for i, r in enumerate(raw_results):
        if isinstance(r, Exception):
            logger.warning(
                "[GOOGLE_PLACES] Enrichment failed for activity %d: %s",
                i,
                r,
            )
            final.append(to_enrich[i])
        else:
            final.append(r)
    final.extend(passthrough)

    enriched_count = sum(1 for r in final if r.get("google_place_id"))
    elapsed_ms = int((time.time() - t0) * 1000)
    logger.info(
        "[GOOGLE_PLACES][%s] Enriched %d/%d activities for %s in %dms",
        path,
        enriched_count,
        len(activities),
        destination,
        elapsed_ms,
    )
    return final
