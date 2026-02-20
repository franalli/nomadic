"""
Google Places provider for hotel and activity tiles.

Uses the Google Places API (New) Text Search to find real hotels and activities.
Provider cascade: curated → google_places → mock

Price estimation: price_level (0-4) × destination cost tier.
Photos: Google Places Photos API (direct URL with API key).
Deeplinks: Google Hotels deeplink for hotels, Google Maps for activities.

Quota exhaustion or API errors → returns empty list → mock fallback applies.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.placeholders import get_placeholder_image
from app.schemas import Geo, Tile

from .models import SearchContext
from .provider_base import Provider

logger = logging.getLogger(__name__)

# Google Places API (New) endpoint
_PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Destination cost tier lookup: estimated nightly hotel rate in USD
# Used to translate price_level (0-4) into a dollar estimate.
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


def _dest_hash(dest: str) -> str:
    """Generate a 6-char hash from destination for tile ID namespacing."""
    return hashlib.md5(dest.lower().strip().encode()).hexdigest()[:6]  # noqa: S324


def _estimate_hotel_price(price_level: Optional[int], nights: int, travelers: int) -> float:
    """Estimate total hotel price from Google Places price_level."""
    level = price_level if price_level is not None else 2  # default: MODERATE
    multiplier = _PRICE_LEVEL_MULTIPLIERS.get(level, 1.0)
    nightly = _BASE_NIGHTLY_RATE_USD * multiplier
    return round(nightly * max(nights, 1) * (1 + 0.05 * max(travelers - 2, 0)), 2)


def _estimate_activity_price(price_level: Optional[int], travelers: int) -> float:
    """Estimate activity price per trip from Google Places price_level."""
    level = price_level if price_level is not None else 2
    multiplier = _PRICE_LEVEL_MULTIPLIERS.get(level, 1.0)
    per_person = max(25.0, 60.0 * multiplier)
    return round(per_person * max(travelers, 1), 2)


def _get_photo_url(photo_name: str) -> Optional[str]:
    """Build a Google Places photo URL from a photo resource name."""
    api_key = settings.google_maps_api_key
    if not photo_name or not api_key:
        return None
    return f"https://places.googleapis.com/v1/{photo_name}/media?maxWidthPx=800&key={api_key}"


_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# In-memory geocode cache to avoid repeat API calls for the same destination
_geocode_cache: dict[str, tuple[float, float] | None] = {}


async def _geocode_destination_async(dest: str) -> tuple[float, float] | None:
    """Return (lat, lng) for a destination string using the Geocoding API, or None on failure.

    Cache key is normalized (lowercased, stripped) to avoid duplicate lookups for the
    same destination under different casing. Only successful results are cached — transient
    failures (network errors, quota) are NOT cached so the next request can retry.
    """
    key = dest.lower().strip()
    if key in _geocode_cache:
        return _geocode_cache[key]
    api_key = settings.google_maps_api_key
    if not api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                _GEOCODE_URL,
                params={"address": dest, "key": api_key},
            )
            data = resp.json() if resp.status_code == 200 else {}
            results = data.get("results", [])
            if results:
                loc = results[0]["geometry"]["location"]
                coords: tuple[float, float] = (loc["lat"], loc["lng"])
                _geocode_cache[key] = coords
                logger.debug("[GOOGLE_PLACES] Geocoded '%s' → %s", dest, coords)
                return coords
            # Destination not found (empty results) — cache None to avoid retrying bad input
            _geocode_cache[key] = None
    except Exception as exc:
        logger.warning("[GOOGLE_PLACES] Geocode failed for '%s': %s", dest, exc)
        # Transient failure — do NOT cache, allow retry on next request
    return None


def _geocode_destination(dest: str) -> tuple[float, float] | None:
    """Sync version of geocoder (used by tile_service/service.py sync path)."""
    key = dest.lower().strip()
    if key in _geocode_cache:
        return _geocode_cache[key]
    api_key = settings.google_maps_api_key
    if not api_key:
        return None
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(_GEOCODE_URL, params={"address": dest, "key": api_key})
            data = resp.json() if resp.status_code == 200 else {}
            results = data.get("results", [])
            if results:
                loc = results[0]["geometry"]["location"]
                coords: tuple[float, float] = (loc["lat"], loc["lng"])
                _geocode_cache[key] = coords
                return coords
            _geocode_cache[key] = None
    except Exception as exc:
        logger.warning("[GOOGLE_PLACES] Geocode failed for '%s': %s", dest, exc)
    return None


def _build_places_request(
    query: str,
    included_type: str,
    max_results: int,
    price_levels: list[str] | None = None,
    geo: tuple[float, float] | None = None,
    location_radius_m: float = 50000.0,
) -> tuple[dict, dict]:
    """Build the payload and headers for a Places API Text Search request.

    Args:
        query: Text query string.
        included_type: Places API type (e.g. "lodging", "tourist_attraction").
        max_results: Maximum results to return (capped at 20).
        price_levels: Optional list of PRICE_LEVEL_* enum strings to filter by.
        geo: Optional (lat, lng) tuple for locationBias circle center.
        location_radius_m: Radius in meters for locationBias circle (default 50km).
    """
    api_key = settings.google_maps_api_key
    payload: dict = {
        "textQuery": query,
        "includedType": included_type,
        "pageSize": min(max_results, 20),
        "languageCode": "en",
    }
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
            "places.rating,"
            "places.userRatingCount,"
            "places.priceLevel,"
            "places.priceRange,"
            "places.photos,"
            "places.location,"
            "places.editorialSummary,"
            "places.primaryType,"
            "places.googleMapsUri,"
            "places.websiteUri"
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
    included_type: str,
    max_results: int = 5,
    price_levels: list[str] | None = None,
    geo: tuple[float, float] | None = None,
) -> List[Dict[str, Any]]:
    """
    Call Google Places API Text Search (New) — async version.
    Returns list of place dicts, or empty list on any error.
    Uses httpx.AsyncClient to avoid blocking the event loop.
    """
    api_key = settings.google_maps_api_key
    if not api_key:
        logger.warning("[GOOGLE_PLACES] Skipped — API key not configured")
        return []

    payload, headers = _build_places_request(query, included_type, max_results, price_levels, geo)
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(_PLACES_SEARCH_URL, json=payload, headers=headers)
            body = response.json() if response.status_code == 200 else {}
            places = _parse_places_response(response.status_code, response.text, body)
            elapsed = int((time.time() - t0) * 1000)
            if places:
                logger.info(
                    "[GOOGLE_PLACES] %s search: query='%s' results=%d latency=%dms",
                    included_type,
                    query,
                    len(places),
                    elapsed,
                )
            else:
                logger.warning(
                    "[GOOGLE_PLACES] %s search EMPTY: query='%s' status=%d latency=%dms",
                    included_type,
                    query,
                    response.status_code,
                    elapsed,
                )
            return places
    except Exception as exc:
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
    included_type: str,
    max_results: int = 5,
    price_levels: list[str] | None = None,
    geo: tuple[float, float] | None = None,
) -> List[Dict[str, Any]]:
    """
    Call Google Places API Text Search (New) — sync version.
    Used by the sync Provider.search() path (tile_service/service.py).
    Returns list of place dicts, or empty list on any error.
    """
    api_key = settings.google_maps_api_key
    if not api_key:
        logger.warning("[GOOGLE_PLACES] Skipped — API key not configured")
        return []

    payload, headers = _build_places_request(query, included_type, max_results, price_levels, geo)
    t0 = time.time()
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(_PLACES_SEARCH_URL, json=payload, headers=headers)
            body = response.json() if response.status_code == 200 else {}
            places = _parse_places_response(response.status_code, response.text, body)
            elapsed = int((time.time() - t0) * 1000)
            if places:
                logger.info(
                    "[GOOGLE_PLACES] %s search: query='%s' results=%d latency=%dms",
                    included_type,
                    query,
                    len(places),
                    elapsed,
                )
            else:
                logger.warning(
                    "[GOOGLE_PLACES] %s search EMPTY: query='%s' status=%d latency=%dms",
                    included_type,
                    query,
                    response.status_code,
                    elapsed,
                )
            return places
    except Exception as exc:
        elapsed = int((time.time() - t0) * 1000)
        logger.error(
            "[GOOGLE_PLACES] %s search FAILED: query='%s' error=%s latency=%dms",
            included_type,
            query,
            exc,
            elapsed,
        )
        return []


def _parse_price_level(price_level: Any) -> int:
    """Normalize Google Places priceLevel (string enum or int) to an int 0-4."""
    price_level_map = {
        "PRICE_LEVEL_FREE": 0,
        "PRICE_LEVEL_INEXPENSIVE": 1,
        "PRICE_LEVEL_MODERATE": 2,
        "PRICE_LEVEL_EXPENSIVE": 3,
        "PRICE_LEVEL_VERY_EXPENSIVE": 4,
    }
    if isinstance(price_level, str):
        return price_level_map.get(price_level, 2)
    if isinstance(price_level, int):
        return price_level
    return 2  # default: MODERATE


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
        max_results = min(ctx.max_results_per_vertical, 10)
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
        )
        return self._build_tiles(ctx, places)

    def search(self, ctx: SearchContext) -> List[Tile]:
        """Sync search — used by tile_service/service.py (non-async path)."""
        dest = ctx.destination or "Somewhere"
        max_results = min(ctx.max_results_per_vertical, 10)
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
        )
        return self._build_tiles(ctx, places)

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

        tiles: List[Tile] = []
        for i, place in enumerate(places):
            place_id = place.get("id", f"gp_hotel_{dest_id}_{i}")
            name = (place.get("displayName") or {}).get("text", f"Hotel in {dest}")
            address = place.get("formattedAddress", dest)
            rating = place.get("rating")
            review_count = place.get("userRatingCount", 0)
            price_level = _parse_price_level(place.get("priceLevel"))

            photos = place.get("photos") or []
            photo_name = photos[0].get("name") if photos else None
            image_url = _get_photo_url(photo_name) or get_placeholder_image(
                "hotel", seed=f"{dest}-hotel-{i}"
            )

            loc = place.get("location") or {}
            geo = None
            if loc.get("latitude") is not None and loc.get("longitude") is not None:
                geo = Geo(lat=loc["latitude"], lng=loc["longitude"])

            # Use priceRange if available for a more accurate estimate.
            # priceRange.startPrice is a Money proto: units (int, major currency unit)
            # + nanos (int, fractional part × 1e9). We only use it for USD — other
            # currencies would need conversion. The startPrice represents the lower end
            # of the hotel's price range; treating it as a per-night base is an
            # approximation (Places API does not document it as strictly per-night).
            price_range = place.get("priceRange") or {}
            start_price_obj = price_range.get("startPrice") or {}
            start_price_currency = start_price_obj.get("currencyCode", "USD")
            start_price_units = start_price_obj.get("units")
            if start_price_units is not None and start_price_currency == "USD":
                try:
                    nanos = int(start_price_obj.get("nanos") or 0)
                    nightly = float(start_price_units) + nanos / 1e9
                    price = round(
                        nightly * max(nights, 1) * (1 + 0.05 * max(total_travelers - 2, 0)), 2
                    )
                except (ValueError, TypeError):
                    price = _estimate_hotel_price(price_level, nights, total_travelers)
            else:
                price = _estimate_hotel_price(price_level, nights, total_travelers)
            tax_and_service = round(price * 0.12, 2)
            property_fee = round(nights * 15, 2)
            total_inclusive = round(price + tax_and_service + property_fee, 2)

            deeplink = (
                place.get("googleMapsUri")
                or f"https://www.google.com/travel/hotels/entity/{place_id}"
            )
            summary = (place.get("editorialSummary") or {}).get("text", "")

            tiles.append(
                Tile(
                    id=f"tile_gp_hotel_{dest_id}_{i}",
                    type="hotel",
                    partner=self.name,
                    partner_product_id=place_id,
                    title=name,
                    subtitle=summary or address,
                    image_url=image_url,
                    price_estimate=price,
                    live_price=None,
                    currency=ctx.currency or "USD",
                    price_basis="per_trip",
                    is_estimate_only=True,
                    deeplink_url=deeplink,
                    rating=rating,
                    review_count=review_count,
                    location_label=address,
                    geo=geo,
                    tags=["hotel", "google_places"],
                    availability_status="unknown",
                    meta={
                        "destination": dest,
                        "price_level": price_level,
                        "nights": nights,
                        "adults": ctx.adults,
                        "children": ctx.children,
                        "place_id": place_id,
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

    async def search_async(self, ctx: SearchContext) -> List[Tile]:
        """Async search — use from async contexts (logistics_node) to avoid blocking the event loop."""
        dest = ctx.destination or "Somewhere"
        max_results = min(ctx.max_results_per_vertical, 10)
        geo: tuple[float, float] | None = None
        if ctx.destination_lat is not None and ctx.destination_lng is not None:
            geo = (ctx.destination_lat, ctx.destination_lng)
        elif dest != "Somewhere":
            geo = await _geocode_destination_async(dest)
        places = await _call_places_api_async(
            query=self._make_query(ctx),
            included_type="tourist_attraction",
            max_results=max_results,
            geo=geo,
        )
        return self._build_tiles(ctx, places)

    def search(self, ctx: SearchContext) -> List[Tile]:
        """Sync search — used by tile_service/service.py (non-async path)."""
        dest = ctx.destination or "Somewhere"
        max_results = min(ctx.max_results_per_vertical, 10)
        geo: tuple[float, float] | None = None
        if ctx.destination_lat is not None and ctx.destination_lng is not None:
            geo = (ctx.destination_lat, ctx.destination_lng)
        elif dest != "Somewhere":
            geo = _geocode_destination(dest)
        places = _call_places_api(
            query=self._make_query(ctx),
            included_type="tourist_attraction",
            max_results=max_results,
            geo=geo,
        )
        return self._build_tiles(ctx, places)

    def _build_tiles(self, ctx: SearchContext, places: List[Dict[str, Any]]) -> List[Tile]:
        """Build Tile objects from raw Places API results."""
        dest = ctx.destination or "Somewhere"
        dest_id = _dest_hash(dest)
        total_travelers = (ctx.adults or 0) + (ctx.children or 0) or 2

        tiles: List[Tile] = []
        for i, place in enumerate(places):
            place_id = place.get("id", f"gp_act_{dest_id}_{i}")
            name = (place.get("displayName") or {}).get("text", f"Activity in {dest}")
            address = place.get("formattedAddress", dest)
            rating = place.get("rating")
            review_count = place.get("userRatingCount", 0)
            price_level = _parse_price_level(place.get("priceLevel"))

            photos = place.get("photos") or []
            photo_name = photos[0].get("name") if photos else None
            image_url = _get_photo_url(photo_name) or get_placeholder_image(
                "activity", seed=f"{dest}-activity-{i}"
            )

            loc = place.get("location") or {}
            geo = None
            if loc.get("latitude") is not None and loc.get("longitude") is not None:
                geo = Geo(lat=loc["latitude"], lng=loc["longitude"])

            price = _estimate_activity_price(price_level, total_travelers)
            tax_and_service = round(price * 0.08, 2)
            total_inclusive = round(price + tax_and_service, 2)

            deeplink = (
                place.get("googleMapsUri")
                or f"https://www.google.com/maps/place/?q=place_id:{place_id}"
            )
            summary = (place.get("editorialSummary") or {}).get("text", "")
            primary_type = place.get("primaryType", "attraction")

            tiles.append(
                Tile(
                    id=f"tile_gp_activity_{dest_id}_{i}",
                    type="activity",
                    partner=self.name,
                    partner_product_id=place_id,
                    title=name,
                    subtitle=summary or address,
                    image_url=image_url,
                    price_estimate=price,
                    live_price=None,
                    currency=ctx.currency or "USD",
                    price_basis="per_trip",
                    is_estimate_only=True,
                    deeplink_url=deeplink,
                    rating=rating,
                    review_count=review_count,
                    location_label=address,
                    geo=geo,
                    tags=["activity", "google_places", primary_type],
                    availability_status="unknown",
                    meta={
                        "destination": dest,
                        "price_level": price_level,
                        "adults": ctx.adults,
                        "children": ctx.children,
                        "place_id": place_id,
                        "category": primary_type,
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

# Lightweight field mask for enrichment (coordinates, photos, rating, price).
_ENRICH_FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.location,"
    "places.photos,"
    "places.rating,"
    "places.userRatingCount,"
    "places.priceLevel,"
    "places.editorialSummary,"
    "places.googleMapsUri"
)


async def _enrich_single_activity(
    client: httpx.AsyncClient,
    activity: dict,
    destination: str,
    api_key: str,
) -> dict:
    """Resolve a single activity against Google Places Text Search.

    On match: overwrite coordinates, image_url; add place_id, deeplink, rating.
    On miss/error: return activity unchanged (graceful degradation).
    """
    title = activity.get("title", "")
    if not title:
        return activity

    query = f"{title} {destination}"
    try:
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
        )
        if resp.status_code == 429:
            logger.warning("[GOOGLE_PLACES] Enrichment quota exhausted for '%s'", title)
            return activity
        if resp.status_code != 200:
            logger.warning(
                "[GOOGLE_PLACES] Enrichment API error %d for '%s': %s",
                resp.status_code,
                title,
                resp.text[:200],
            )
            return activity
        places = resp.json().get("places", [])
    except Exception as e:
        logger.warning("[GOOGLE_PLACES] Enrichment failed for '%s': %s", title, e)
        return activity

    if not places:
        return activity

    try:
        place = places[0]
        loc = place.get("location", {})

        # Overwrite coordinates with verified data ([lng, lat] Mapbox convention)
        if loc.get("latitude") is not None and loc.get("longitude") is not None:
            activity["coordinates"] = [loc["longitude"], loc["latitude"]]

        # Overwrite image with Google Places photo
        photos = place.get("photos") or []
        if photos:
            photo_url = _get_photo_url(photos[0].get("name", ""))
            if photo_url:
                activity["image_url"] = photo_url

        # Add metadata
        place_id = place.get("id", "")
        activity["google_place_id"] = place_id
        activity["rating"] = place.get("rating")
        activity["user_ratings_count"] = place.get("userRatingCount")
        activity["deeplink"] = (
            place.get("googleMapsUri")
            or f"https://www.google.com/maps/place/?q=place_id:{place_id}"
        )

        # Fill price_estimate from Places priceLevel only when the activity has none.
        # Tier 1 specialist tiles never get a price from the LLM pipeline, so this
        # closes the gap. Tier 2 LLM tiles keep their category-aware estimate ($40
        # default) since priceLevel is a coarser signal than the LLM's context.
        if activity.get("price_estimate") is None:
            raw_price_level = place.get("priceLevel")
            if raw_price_level is not None:
                pl = _parse_price_level(raw_price_level)
                # Assume 2 adults as a neutral baseline — enrichment has no traveler count
                activity["price_estimate"] = _estimate_activity_price(pl, travelers=2)
                activity["price_basis"] = "per_person"
                activity["currency"] = "USD"
                activity["is_estimate_only"] = True

        # Enrich description with editorial summary if richer than LLM text
        existing_desc = activity.get("description", "") or (
            (activity.get("meta") or {}).get("description", "")
        )
        editorial = (place.get("editorialSummary") or {}).get("text")
        if editorial and len(editorial) > len(existing_desc):
            activity["editorial_summary"] = editorial

        logger.debug(
            "[GOOGLE_PLACES] Enriched '%s' → place_id=%s coords=%s rating=%s",
            title,
            place_id,
            activity.get("coordinates"),
            activity.get("rating"),
        )
    except Exception as e:
        logger.warning("[GOOGLE_PLACES] Enrichment parse failed for '%s': %s", title, e)

    return activity


async def enrich_activities_with_places(
    activities: list[dict],
    destination: str,
) -> list[dict]:
    """Post-process LLM-generated activities by resolving each against Google Places.

    For each activity:
    1. Search "{title} {destination}" via Text Search
    2. If match: overwrite coordinates + image_url, add place_id/deeplink/rating
    3. If no match: keep LLM data as-is (graceful degradation)

    Feature-gated: caller must check settings.use_google_places_provider before calling.

    Returns the enriched list.
    """
    api_key = settings.google_maps_api_key
    if not api_key or not activities:
        return activities

    t0 = time.time()
    async with httpx.AsyncClient(timeout=5.0) as client:
        coros = [
            _enrich_single_activity(client, activity, destination, api_key)
            for activity in activities
        ]
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
            final.append(activities[i])
        else:
            final.append(r)

    enriched_count = sum(1 for r in final if r.get("google_place_id"))
    elapsed_ms = int((time.time() - t0) * 1000)
    logger.info(
        "[GOOGLE_PLACES] Enriched %d/%d activities for %s in %dms",
        enriched_count,
        len(activities),
        destination,
        elapsed_ms,
    )
    return final
