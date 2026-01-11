"""
Geocoding service for place name validation and normalization.

Uses Nominatim (OpenStreetMap) for geocoding with in-memory caching.
This provides authoritative location data for any valid place worldwide,
not just the ~900 hardcoded places in known_places.py.

Rate limiting: Nominatim requires max 1 request/second.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# Nominatim API endpoint (free, OSM-based)
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# User-Agent required by Nominatim usage policy
USER_AGENT = "Nomadic-Travel-Planner/1.0"

# Cache TTL in seconds (24 hours)
CACHE_TTL_SECONDS = 86400

# Rate limiting: minimum seconds between requests
MIN_REQUEST_INTERVAL = 1.1  # Slightly over 1 second for safety


@dataclass
class GeocodingResult:
    """Result from geocoding a place name."""

    display_name: str  # Full formatted name (e.g., "South Bend, St. Joseph County, Indiana, USA")
    city: Optional[str]  # City/town name
    state: Optional[str]  # State/province
    country: str  # Country name
    country_code: str  # ISO country code (e.g., "us", "gb")
    lat: float
    lng: float

    @property
    def short_name(self) -> str:
        """Return a shorter display name (city, country or city, state for US)."""
        if self.country_code == "us" and self.state:
            return f"{self.city}, {self.state}" if self.city else self.state
        return f"{self.city}, {self.country}" if self.city else self.country


class GeocodingCache:
    """Simple in-memory cache with TTL for geocoding results."""

    def __init__(self, ttl_seconds: int = CACHE_TTL_SECONDS):
        self._cache: Dict[str, tuple[GeocodingResult, float]] = {}
        self._ttl = ttl_seconds

    def get(self, key: str) -> Optional[GeocodingResult]:
        """Get cached result if not expired."""
        key_lower = key.lower().strip()
        if key_lower in self._cache:
            result, timestamp = self._cache[key_lower]
            if time.time() - timestamp < self._ttl:
                return result
            # Expired - remove it
            del self._cache[key_lower]
        return None

    def set(self, key: str, result: GeocodingResult) -> None:
        """Cache a result with current timestamp."""
        key_lower = key.lower().strip()
        self._cache[key_lower] = (result, time.time())

    def clear(self) -> int:
        """Clear all cached entries. Returns count of cleared entries."""
        count = len(self._cache)
        self._cache.clear()
        return count


# Global cache instance
_geocoding_cache = GeocodingCache()

# Rate limiting state
_last_request_time: float = 0.0
_rate_limit_lock = asyncio.Lock()


async def _rate_limit() -> None:
    """Ensure we don't exceed Nominatim's rate limit (1 req/sec)."""
    global _last_request_time
    async with _rate_limit_lock:
        now = time.time()
        elapsed = now - _last_request_time
        if elapsed < MIN_REQUEST_INTERVAL:
            await asyncio.sleep(MIN_REQUEST_INTERVAL - elapsed)
        _last_request_time = time.time()


def _parse_nominatim_response(data: dict) -> Optional[GeocodingResult]:
    """Parse Nominatim API response into GeocodingResult."""
    if not data:
        return None

    address = data.get("address", {})

    # Extract city - Nominatim uses various keys depending on place type
    city = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("municipality")
        or address.get("hamlet")
    )

    # Extract state/province
    state = address.get("state") or address.get("province") or address.get("region")

    # Country is required
    country = address.get("country")
    country_code = address.get("country_code", "").lower()

    if not country:
        return None

    try:
        lat = float(data.get("lat", 0))
        lng = float(data.get("lon", 0))
    except (ValueError, TypeError):
        lat, lng = 0.0, 0.0

    return GeocodingResult(
        display_name=data.get("display_name", ""),
        city=city,
        state=state,
        country=country,
        country_code=country_code,
        lat=lat,
        lng=lng,
    )


async def geocode_place(
    place: str, timeout: float = 5.0, use_cache: bool = True
) -> Optional[GeocodingResult]:
    """
    Geocode a place name using Nominatim.

    Args:
        place: The place name to geocode (e.g., "South Bend, Indiana")
        timeout: Request timeout in seconds
        use_cache: Whether to use the cache (default True)

    Returns:
        GeocodingResult if found, None otherwise
    """
    if not place or not place.strip():
        return None

    place_clean = place.strip()

    # Check cache first
    if use_cache:
        cached = _geocoding_cache.get(place_clean)
        if cached:
            logger.debug(f"[GEOCODE] cache hit: '{place_clean}'")
            return cached

    # Rate limit before making request
    await _rate_limit()

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                NOMINATIM_URL,
                params={
                    "q": place_clean,
                    "format": "json",
                    "addressdetails": 1,
                    "limit": 1,
                },
                headers={"User-Agent": USER_AGENT},
            )
            response.raise_for_status()
            data = response.json()

            if not data:
                logger.debug(f"[GEOCODE] no results: '{place_clean}'")
                return None

            result = _parse_nominatim_response(data[0])
            if result and use_cache:
                _geocoding_cache.set(place_clean, result)
                logger.debug(
                    f"[GEOCODE] success: '{place_clean}' → "
                    f"'{result.short_name}' ({result.country_code})"
                )

            return result

    except httpx.TimeoutException:
        logger.warning(f"[GEOCODE] timeout: '{place_clean}'")
        return None
    except httpx.HTTPStatusError as e:
        logger.warning(f"[GEOCODE] HTTP error {e.response.status_code}: '{place_clean}'")
        return None
    except Exception as e:
        logger.warning(f"[GEOCODE] error: '{place_clean}' - {e}")
        return None


def geocode_place_sync(
    place: str, timeout: float = 5.0, use_cache: bool = True
) -> Optional[GeocodingResult]:
    """
    Synchronous wrapper for geocode_place.

    Use this in sync contexts. Uses synchronous HTTP directly to avoid
    event loop complications.
    """
    if not place or not place.strip():
        return None

    place_clean = place.strip()

    # Check cache first (no async needed)
    if use_cache:
        cached = _geocoding_cache.get(place_clean)
        if cached:
            logger.debug(f"[GEOCODE] cache hit: '{place_clean}'")
            return cached

    # Use synchronous HTTP directly - simpler and avoids event loop issues
    return _geocode_sync_http(place_clean, timeout, use_cache)


def _geocode_sync_http(
    place: str, timeout: float = 5.0, use_cache: bool = True
) -> Optional[GeocodingResult]:
    """Pure synchronous HTTP geocoding (fallback when async isn't available)."""
    import time as sync_time

    global _last_request_time

    place_clean = place.strip()

    # Simple rate limiting for sync
    elapsed = sync_time.time() - _last_request_time
    if elapsed < MIN_REQUEST_INTERVAL:
        sync_time.sleep(MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = sync_time.time()

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(
                NOMINATIM_URL,
                params={
                    "q": place_clean,
                    "format": "json",
                    "addressdetails": 1,
                    "limit": 1,
                },
                headers={"User-Agent": USER_AGENT},
            )
            response.raise_for_status()
            data = response.json()

            if not data:
                return None

            result = _parse_nominatim_response(data[0])
            if result and use_cache:
                _geocoding_cache.set(place_clean, result)

            return result

    except Exception as e:
        logger.warning(f"[GEOCODE] sync error: '{place_clean}' - {e}")
        return None


def clear_geocoding_cache() -> int:
    """Clear the geocoding cache. Returns count of cleared entries."""
    return _geocoding_cache.clear()


def get_geocoding_cache_size() -> int:
    """Get current size of geocoding cache."""
    return len(_geocoding_cache._cache)
