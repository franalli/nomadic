"""
Viator affiliate API provider for activity tile enrichment.

Enriches LLM-generated activity tiles with real pricing, images, ratings,
and affiliate deeplinks from Viator's partner API (Basic Access tier).

Graceful degradation: all functions return empty/None on failure.
"""

from __future__ import annotations

import asyncio
import logging
import re
from threading import Lock
from typing import Any

import httpx

from app.config import settings
from app.services.cache_core import MemoryCache
from app.services.circuit_breaker import CircuitBreaker
from app.services.spend_guard import reserve_partner_api_spend_or_raise

logger = logging.getLogger(__name__)

# -- Constants ----------------------------------------------------------------
VIATOR_BASE = settings.viator_api_url
VIATOR_ACCEPT = "application/json;version=2.0"
VIATOR_TIMEOUT = 8.0  # seconds
MAX_SINGLE_ACTIVITY_MINUTES = 480  # 8 hours — filter multi-day tours

# -- Singleton httpx client ---------------------------------------------------
_viator_client: httpx.AsyncClient | None = None
_viator_client_lock = asyncio.Lock()


async def _get_viator_client() -> httpx.AsyncClient:
    """Return a shared httpx client, creating lazily if needed."""
    global _viator_client
    if _viator_client is not None and not _viator_client.is_closed:
        return _viator_client
    async with _viator_client_lock:
        if _viator_client is None or _viator_client.is_closed:
            _viator_client = httpx.AsyncClient(timeout=VIATOR_TIMEOUT)
        return _viator_client


async def close_viator_http_client() -> None:
    """Close the shared httpx client (call during app shutdown)."""
    global _viator_client
    if _viator_client and not _viator_client.is_closed:
        await _viator_client.aclose()
        _viator_client = None


# -- Circuit breaker ----------------------------------------------------------
_viator_cb = CircuitBreaker("viator", failure_threshold=5, open_seconds=120)


# -- Caches -------------------------------------------------------------------
_NO_MATCH: object = object()  # sentinel for negative match cache entries

_dest_cache = MemoryCache(maxsize=500, ttl=86400 * 30)  # destination taxonomy (static)
_viator_cache_ttl = settings.viator_cache_ttl_hours * 3600
_match_cache = MemoryCache(maxsize=512, ttl=_viator_cache_ttl)  # title->product matches
_browse_viator_cache = MemoryCache(maxsize=256, ttl=_viator_cache_ttl)  # browse results

_GENERIC_ACTIVITY_TOKENS = frozenset(
    {
        "activity",
        "activities",
        "adventure",
        "advanced",
        "afternoon",
        "beginner",
        "boat",
        "class",
        "course",
        "cruise",
        "day",
        "dive",
        "diver",
        "divers",
        "dives",
        "diving",
        "drift",
        "encounter",
        "evening",
        "excursion",
        "experience",
        "for",
        "from",
        "full",
        "group",
        "guided",
        "half",
        "in",
        "intermediate",
        "lesson",
        "morning",
        "optional",
        "private",
        "ray",
        "session",
        "sessions",
        "shore",
        "snorkel",
        "snorkeling",
        "tour",
        "trip",
        "wall",
        "with",
    }
)
_PAREN_SUFFIX_RE = re.compile(r"\([^)]*\)")
_SESSION_SUFFIX_RE = re.compile(r"\bsession\s+\d+\b", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

# -- Telemetry ----------------------------------------------------------------
_VIATOR_COUNTER_FIELDS = ("requests", "successes", "errors", "cache_hits")
_viator_usage_lock = Lock()
_viator_usage_counters: dict[str, int] = {f: 0 for f in _VIATOR_COUNTER_FIELDS}


def record_viator_usage(event: str) -> None:
    field_map = {
        "request": "requests",
        "success": "successes",
        "error": "errors",
        "cache_hit": "cache_hits",
    }
    field = field_map.get(event)
    if field:
        with _viator_usage_lock:
            _viator_usage_counters[field] += 1


def get_viator_usage_counters() -> dict[str, int]:
    with _viator_usage_lock:
        return dict(_viator_usage_counters)


# -- API helpers --------------------------------------------------------------


def _viator_headers() -> dict[str, str]:
    return {
        "exp-api-key": settings.viator_api_key,
        "Accept": VIATOR_ACCEPT,
        "Accept-Language": "en-US",
    }


def _strip_location_prefix(activity_title: str) -> str:
    """Remove short leading location prefixes from specialist-generated titles."""
    clean_title = activity_title
    for sep in (":", " — ", " - "):
        if sep not in clean_title:
            continue
        parts = clean_title.split(sep, 1)
        if len(parts[0].split()) <= 4:
            return parts[1].strip()
    return clean_title


def _clean_activity_title(activity_title: str) -> str:
    """Normalize specialist titles for partner search without losing site names."""
    clean_title = _strip_location_prefix(activity_title or "")
    clean_title = _PAREN_SUFFIX_RE.sub(" ", clean_title)
    clean_title = _SESSION_SUFFIX_RE.sub(" ", clean_title)
    clean_title = re.sub(r"\s+", " ", clean_title).strip(" -")
    return clean_title or activity_title


def _simplify_activity_title(activity_title: str) -> str:
    """Drop generic activity qualifiers while keeping distinctive place/site tokens."""
    clean_title = _clean_activity_title(activity_title)
    simplified_words = [
        word
        for word in clean_title.split()
        if word and word.lower() not in _GENERIC_ACTIVITY_TOKENS
    ]
    simplified = " ".join(simplified_words).strip()
    return simplified or clean_title


def _activity_keyword(activity_title: str) -> str | None:
    """Return a normalized activity keyword for broader fallback search."""
    title_lower = activity_title.lower()
    keyword_map = {
        "div": "scuba diving",
        "snorkel": "snorkeling",
        "surf": "surfing",
        "hik": "hiking",
        "trek": "trekking",
        "climb": "climbing",
        "sail": "sailing",
        "kayak": "kayaking",
        "raft": "rafting",
        "bike": "biking",
        "cycl": "cycling",
        "ski": "skiing",
        "yoga": "yoga",
        "cook": "cooking class",
        "safari": "safari",
        "whale": "whale watching",
    }
    for stem, keyword in keyword_map.items():
        if stem in title_lower:
            return keyword
    return None


def _search_query_variants(activity_title: str, destination: str, dest_id: int | None) -> list[str]:
    """Build a small ordered set of freetext queries for specialist titles."""
    clean_title = _clean_activity_title(activity_title)
    simplified_title = _simplify_activity_title(clean_title)
    keyword = _activity_keyword(clean_title)

    bases: list[str] = []
    for candidate in (clean_title, simplified_title):
        candidate = candidate.strip()
        if candidate and candidate not in bases:
            bases.append(candidate)
    if keyword and simplified_title:
        keyword_query = f"{simplified_title} {keyword}".strip()
        if keyword_query not in bases:
            bases.append(keyword_query)
    if len(simplified_title.split()) > 4:
        short_title = " ".join(simplified_title.split()[:4]).strip()
        if short_title and short_title not in bases:
            bases.append(short_title)

    queries: list[str] = []
    for base in bases:
        query = base if dest_id is not None else f"{base} {destination}".strip()
        if query and query not in queries:
            queries.append(query)
        if len(queries) >= 3:
            break
    return queries


def _match_anchor_tokens(activity_title: str) -> set[str]:
    """Return non-generic tokens that should overlap for a defensible match."""
    tokens = {
        token
        for token in _NON_ALNUM_RE.sub(
            " ", _simplify_activity_title(activity_title).lower()
        ).split()
        if len(token) >= 3 and token not in _GENERIC_ACTIVITY_TOKENS
    }
    return tokens


def _score_product_title(activity_title: str, product_title: str) -> tuple[int, int]:
    """Return (score, anchor_overlap) for a specialist title vs Viator product."""
    from rapidfuzz import fuzz

    clean_title = _clean_activity_title(activity_title).lower()
    simplified_title = _simplify_activity_title(activity_title).lower()
    score_variants = [clean_title]
    if simplified_title and simplified_title != clean_title:
        score_variants.append(simplified_title)

    normalized_product = product_title.lower()
    best_score = 0
    for candidate in score_variants:
        best_score = max(
            best_score,
            fuzz.token_set_ratio(candidate, normalized_product),
            fuzz.partial_ratio(candidate, normalized_product),
        )

    product_tokens = set(_NON_ALNUM_RE.sub(" ", normalized_product).split())
    anchor_overlap = len(_match_anchor_tokens(activity_title) & product_tokens)
    if anchor_overlap:
        best_score += min(anchor_overlap * 6, 18)
    return best_score, anchor_overlap


def _best_scored_product(activity_title: str, products: list[dict]) -> tuple[dict | None, int, int]:
    """Return the highest-scoring product candidate for an activity title."""
    best_product: dict | None = None
    best_score = 0
    best_anchor_overlap = 0
    for product in products:
        product_title = product.get("title", "")
        score, anchor_overlap = _score_product_title(activity_title, product_title)
        if (
            best_product is None
            or score > best_score
            or (score == best_score and anchor_overlap > best_anchor_overlap)
        ):
            best_product = product
            best_score = score
            best_anchor_overlap = anchor_overlap
    return best_product, best_score, best_anchor_overlap


async def resolve_destination_id(
    destination: str,
    *,
    return_status: bool = False,
) -> int | None | tuple[int | None, bool]:
    """Resolve a destination name to a Viator destination ID.

    Returns a tuple of ``(destination_id, is_definitive)`` when ``return_status``
    is true so callers can avoid negative-caching transient taxonomy failures.

    Caches the full taxonomy for 30 days (it's static).
    """
    cache_key = "viator_dest_taxonomy"
    taxonomy = _dest_cache.get(cache_key)

    if taxonomy is None:
        if _viator_cb.is_open():
            result: tuple[int | None, bool] = (None, False)
            return result if return_status else result[0]
        try:
            record_viator_usage("request")
            reserve_partner_api_spend_or_raise("viator")
            client = await _get_viator_client()
            resp = await client.get(
                f"{VIATOR_BASE}/destinations",
                headers=_viator_headers(),
                timeout=VIATOR_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            destinations = data.get("destinations") or data.get("data") or []
            taxonomy = {
                (d.get("destinationName") or "").strip().lower(): d.get("destinationId")
                for d in destinations
                if d.get("destinationName") and d.get("destinationId")
            }
            _dest_cache.set(cache_key, taxonomy)
            _viator_cb.record_success()
            record_viator_usage("success")
            logger.debug("[VIATOR] Cached %d destinations in taxonomy", len(taxonomy))
        except Exception as e:
            _viator_cb.record_failure()
            record_viator_usage("error")
            logger.debug("[VIATOR] Failed to fetch destinations: %s", e)
            result = (None, False)
            return result if return_status else result[0]

    dest_lower = destination.strip().lower()

    # Exact match
    if dest_lower in taxonomy:
        result = (taxonomy[dest_lower], True)
        return result if return_status else result[0]

    # Substring match (e.g. "Bali" in "Bali, Indonesia")
    for name, dest_id in taxonomy.items():
        if dest_lower in name or name in dest_lower:
            result = (dest_id, True)
            return result if return_status else result[0]

    # Fuzzy match via rapidfuzz
    from rapidfuzz import fuzz

    best_score = 0
    best_id = None
    for name, dest_id in taxonomy.items():
        score = fuzz.token_sort_ratio(dest_lower, name)
        if score > best_score:
            best_score = score
            best_id = dest_id
    if best_score >= 70 and best_id is not None:
        result = (best_id, True)
        return result if return_status else result[0]

    logger.debug("[VIATOR] No destination match for '%s'", destination)
    result = (None, True)
    return result if return_status else result[0]


async def search_freetext(
    query: str,
    dest_id: int | None,
    currency: str = "USD",
    count: int = 3,
) -> list[dict]:
    """Freetext search for Viator products."""
    products, _ = await _search_freetext_with_status(query, dest_id, currency=currency, count=count)
    return products


async def _search_freetext_with_status(
    query: str,
    dest_id: int | None,
    currency: str = "USD",
    count: int = 3,
) -> tuple[list[dict], bool]:
    """Return freetext products plus whether the provider answered definitively."""
    if _viator_cb.is_open():
        return [], False

    try:
        record_viator_usage("request")
        reserve_partner_api_spend_or_raise("viator")
        client = await _get_viator_client()
        payload: dict[str, Any] = {
            "searchTerm": query,
            "searchTypes": [
                {"searchType": "PRODUCTS", "pagination": {"offset": 0, "limit": count}}
            ],
            "currency": currency,
        }
        if dest_id is not None:
            payload["filtering"] = {"destination": {"id": str(dest_id)}}

        resp = await client.post(
            f"{VIATOR_BASE}/search/freetext",
            headers=_viator_headers(),
            json=payload,
            timeout=VIATOR_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        products = data.get("products", {}).get("results", [])
        _viator_cb.record_success()
        record_viator_usage("success")
        return products, True
    except Exception as e:
        _viator_cb.record_failure()
        record_viator_usage("error")
        logger.debug("[VIATOR] Freetext search failed: %s", e)
        return [], False


async def search_products_by_destination(
    dest_id: int,
    currency: str = "USD",
    count: int = 10,
) -> list[dict]:
    """Search top-selling products for a destination."""
    if _viator_cb.is_open():
        return []

    try:
        record_viator_usage("request")
        reserve_partner_api_spend_or_raise("viator")
        client = await _get_viator_client()
        payload: dict[str, Any] = {
            "filtering": {"destination": str(dest_id)},
            "sorting": {"sort": "TRAVELER_RATING", "order": "DESCENDING"},
            "pagination": {"offset": 0, "limit": count},
            "currency": currency,
        }

        resp = await client.post(
            f"{VIATOR_BASE}/products/search",
            headers=_viator_headers(),
            json=payload,
            timeout=VIATOR_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        products = data.get("products", [])
        _viator_cb.record_success()
        record_viator_usage("success")
        return products
    except Exception as e:
        _viator_cb.record_failure()
        record_viator_usage("error")
        logger.debug("[VIATOR] Product search failed: %s", e)
        return []


def viator_product_to_tile(product: dict, destination: str) -> dict:
    """Convert a Viator product dict to a Nomadic tile dict."""
    product_code = product.get("productCode", "")
    title = product.get("title", "Viator Activity")

    # Price: use recommendedRetailPrice (NOT partnerNetPrice)
    pricing = product.get("pricing", {})
    summary = pricing.get("summary", {})
    price = summary.get("fromPrice")
    currency = pricing.get("currency", "USD")

    # Image: prefer isCover image, fallback to first
    images = product.get("images", [])
    image_url = ""
    if images:
        cover = next((img for img in images if img.get("isCover")), images[0])
        variants = cover.get("variants", [])

        logger.info(
            "[VIATOR IMG] product=%s variants=%d cover=%s",
            product_code,
            len(variants),
            cover.get("isCover"),
        )
        if variants:
            suitable = [v for v in variants if v.get("url")]
            if suitable:
                best = min(suitable, key=lambda v: abs((v.get("width") or 0) - 720))
                image_url = best.get("url", "")

        if not image_url:
            logger.debug("[VIATOR IMG] No usable image for product=%s", product_code)

    # Reviews
    reviews = product.get("reviews", {})
    rating = reviews.get("combinedAverageRating")
    review_count = reviews.get("totalReviews")

    # Duration
    duration = product.get("duration", {})
    duration_minutes = duration.get("fixedDurationInMinutes")
    duration_hours = round(duration_minutes / 60, 1) if duration_minutes else None
    # Cap absurd durations (multi-day passes like "72h Rome Digital Guide").
    # 12h ceiling for real Viator products; experience_generator uses 4h for LLM estimates.
    if duration_hours is not None and duration_hours > 12:
        logger.info(
            "[VIATOR] Capping duration %sh -> 12h for product=%s",
            duration_hours,
            product_code,
        )
        duration_hours = 12.0

    # Deeplink: productUrl from API is already activity-level with affiliate tracking
    deeplink_url = product.get("productUrl", "")
    logger.info(
        "[VIATOR DEEPLINK] product=%s url=%s",
        product_code,
        deeplink_url[:80] if deeplink_url else "",
    )

    # Extract geo coordinates from Viator product data
    geo: dict[str, float] | None = None
    itinerary = product.get("itinerary", {})
    if isinstance(itinerary, dict):
        for item in itinerary.get("itineraryItems", []):
            if not isinstance(item, dict):
                continue
            poi = item.get("pointOfInterestLocation", {})
            loc = poi.get("location", {}) if isinstance(poi, dict) else {}
            if isinstance(loc, dict) and loc.get("latitude") and loc.get("longitude"):
                geo = {"lat": loc["latitude"], "lng": loc["longitude"]}
                break
    # Fallback: logistics.start or meetingPoint
    if not geo:
        for loc_key in ("logistics", "meetingPoint"):
            loc_data = product.get(loc_key, {})
            if not isinstance(loc_data, dict):
                continue
            start = loc_data.get("start", [loc_data]) if loc_key == "logistics" else [loc_data]
            for s in start if isinstance(start, list) else [start]:
                if not isinstance(s, dict):
                    continue
                loc = s.get("location", s)
                if isinstance(loc, dict) and loc.get("latitude") and loc.get("longitude"):
                    geo = {"lat": loc["latitude"], "lng": loc["longitude"]}
                    break
            if geo:
                break

    tile: dict[str, Any] = {
        "id": f"viator_{product_code}",
        "type": "activity",
        "title": title,
        "partner": "viator",
        "partner_product_id": product_code,
        "provider": "viator",
        "deeplink": deeplink_url,
        "deeplink_url": deeplink_url,  # frontend canonical field
        "destination": destination,
        "is_estimate_only": False,
        "meta": {},
    }

    if geo:
        tile["geo"] = geo

    if price is not None:
        tile["price_estimate"] = price
        tile["live_price"] = price
        tile["currency"] = currency
        tile["price_basis"] = "per_person"

    if image_url:
        tile["image_url"] = image_url

    if rating is not None:
        tile["rating"] = round(rating, 1)
    if review_count is not None:
        tile["review_count"] = review_count

    if duration_hours is not None:
        tile["meta"]["duration_hours"] = duration_hours
    tile["meta"]["viator_product_code"] = product_code

    return tile


async def match_activity_to_viator(
    activity_title: str,
    destination: str,
    currency: str = "USD",
) -> dict | None:
    """Match an activity title to a Viator product. Returns tile dict or None."""
    cache_key = f"viator_match:{destination.lower()}:{activity_title.lower()}"
    cached = _match_cache.get(cache_key)
    if cached is not None:
        record_viator_usage("cache_hit")
        return cached if cached is not _NO_MATCH else None

    dest_id, destination_is_definitive = await resolve_destination_id(
        destination,
        return_status=True,
    )

    clean_title = _clean_activity_title(activity_title)
    query_variants = _search_query_variants(activity_title, destination, dest_id)
    products: list[dict] = []
    seen_products: set[str] = set()
    all_queries_definitive = bool(query_variants) and destination_is_definitive
    for query in query_variants:
        query_products, is_definitive = await _search_freetext_with_status(
            query,
            dest_id,
            currency,
            count=3,
        )
        all_queries_definitive = all_queries_definitive and is_definitive
        for product in query_products:
            if (
                product.get("duration", {}).get("fixedDurationInMinutes")
                or MAX_SINGLE_ACTIVITY_MINUTES
            ) > MAX_SINGLE_ACTIVITY_MINUTES:
                continue

            product_code = str(product.get("productCode") or "").strip()
            product_title = str(product.get("title") or "").strip().lower()
            dedupe_key = product_code or product_title
            if dedupe_key and dedupe_key in seen_products:
                continue
            if dedupe_key:
                seen_products.add(dedupe_key)
            products.append(product)

    if not products:
        if all_queries_definitive:
            _match_cache.set(cache_key, _NO_MATCH)
        return None

    best_product, best_score, best_anchor_overlap = _best_scored_product(clean_title, products)
    if best_score < 55 or best_product is None:
        # Loose fallback: accept best product if it shares an activity keyword
        # and retains at least one non-generic site token when available.
        _ACTIVITY_STEMS = {
            "div",
            "snorkel",
            "surf",
            "hik",
            "trek",
            "climb",
            "sail",
            "kayak",
            "raft",
            "bike",
            "cycl",
            "ski",
            "yoga",
            "cook",
            "safari",
            "whale",
            "dolphin",
        }
        query_lower = clean_title.lower()
        product_title = (best_product.get("title", "") if best_product else "").lower()
        shared = any(stem in query_lower and stem in product_title for stem in _ACTIVITY_STEMS)
        anchor_tokens = _match_anchor_tokens(clean_title)
        has_anchor_support = not anchor_tokens or best_anchor_overlap > 0
        if shared and has_anchor_support and best_product:
            logger.info(
                "[VIATOR] Loose match (score=%d, anchors=%d): '%s' → '%s'",
                best_score,
                best_anchor_overlap,
                clean_title,
                best_product.get("title", ""),
            )
        else:
            if all_queries_definitive:
                _match_cache.set(cache_key, _NO_MATCH)
            return None
    tile = viator_product_to_tile(best_product, destination)

    _match_cache.set(cache_key, tile)
    return tile


async def search_viator_for_destination(
    destination: str,
    currency: str = "USD",
    count: int = 10,
) -> list[dict]:
    """Browse Viator products for a destination. Returns list of tile dicts."""
    cache_key = f"viator_browse:{destination.lower()}:{currency}:{count}"
    cached = _browse_viator_cache.get(cache_key)
    if cached is not None:
        record_viator_usage("cache_hit")
        logger.debug("[VIATOR] L1 cache hit for browse: %s", destination)
        return cached

    dest_id = await resolve_destination_id(destination)

    if dest_id is not None:
        products = await search_products_by_destination(dest_id, currency, count)
    else:
        # Fallback to freetext if no dest_id
        query = f"tours and activities in {destination}"
        products = await search_freetext(query, None, currency, count)

    # Drop multi-day tours (raw duration > 8h)
    products = [
        p
        for p in products
        if (p.get("duration", {}).get("fixedDurationInMinutes") or MAX_SINGLE_ACTIVITY_MINUTES)
        <= MAX_SINGLE_ACTIVITY_MINUTES
    ]

    if not products:
        return []

    tiles = [viator_product_to_tile(p, destination) for p in products]

    # Geo fallback: use destination center for tiles missing coordinates
    geo_null_tiles = [t for t in tiles if not t.get("geo")]
    if geo_null_tiles:
        try:
            from app.tile_service.google_places_provider import (
                _geocode_destination_async,
            )

            coords = await _geocode_destination_async(destination)
            if coords:
                dest_geo = {"lat": coords[0], "lng": coords[1]}
                for t in geo_null_tiles:
                    t["geo"] = dict(dest_geo)
                logger.debug(
                    "[VIATOR] Geo fallback: %d tiles got dest coords for %s",
                    len(geo_null_tiles),
                    destination,
                )
        except Exception as exc:
            logger.debug("[VIATOR] Geo fallback failed for %s: %s", destination, exc)

    _browse_viator_cache.set(cache_key, tiles)
    logger.debug("[VIATOR] Cached %d browse tiles for %s", len(tiles), destination)
    return tiles
