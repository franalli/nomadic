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
from app.planner.hashing import make_cache_key
from app.services.activity_category_conflicts import (
    has_category_conflict as _has_category_conflict,
)
from app.services.cache_core import MemoryCache
from app.services.circuit_breaker import CircuitBreaker

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

_TITLE_CATEGORY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?:hike|hiking|trek|trekking|trail\b)", re.I), "hiking"),
    # Diving is checked BEFORE snorkeling so a combined "scuba + snorkel" product
    # is classified by its harder/primary activity (diving); only a PURE snorkel
    # product (no dive/scuba token) falls through to "snorkeling". Splitting
    # snorkel out of diving keeps the inferred-category taxonomy honest (snorkel
    # is not scuba) so the cross-category mismatch gate can tell them apart.
    (re.compile(r"(?:dive|diving|scuba)", re.I), "diving"),
    (re.compile(r"(?:snorkel|snorkeling|snorkelling)", re.I), "snorkeling"),
    (re.compile(r"(?:surf|surfing)", re.I), "surfing"),
    (re.compile(r"(?:cycle|cycling|bike|biking)\b", re.I), "cycling"),
    (re.compile(r"(?:ski|skiing|snowboard)", re.I), "skiing"),
    (re.compile(r"(?:climb|climbing|bouldering)", re.I), "climbing"),
    (re.compile(r"(?:sail|sailing|kayak|canoe|rafting)", re.I), "sailing"),
    (re.compile(r"(?:safari|wildlife)", re.I), "wildlife_safari"),
    (re.compile(r"(?:canyon|scenic|park|garden|nature|valley|desert|waterfall)", re.I), "nature"),
    (re.compile(r"(?:museum|gallery|heritage|historic|monument|palace|castle)", re.I), "cultural"),
    (re.compile(r"(?:temple|church|mosque|cathedral|shrine)", re.I), "temples"),
    (re.compile(r"(?:food|culinary|cooking|tasting|wine|beer|gastro)", re.I), "food"),
    (re.compile(r"(?:spa|wellness|massage|hot spring)", re.I), "spa"),
    (re.compile(r"(?:yoga)", re.I), "yoga"),
    (re.compile(r"(?:nightlife|club|pub crawl|casino)", re.I), "nightlife"),
    (re.compile(r"(?:shopping|market|bazaar|souk)", re.I), "shopping"),
    (re.compile(r"(?:tour|sightseeing|excursion|day trip)", re.I), "tours"),
]


def _infer_category_from_title(title: str) -> str:
    """Infer an activity category from a product title using keyword patterns."""
    for pattern, category in _TITLE_CATEGORY_PATTERNS:
        if pattern.search(title):
            return category
    return "tours"


# Canonical category labels the title-inference taxonomy can produce. Used to
# decide whether the trusted caller-supplied ``category`` (the specialist topic)
# is on-taxonomy so it can anchor the inferred-mismatch gate instead of the
# noisier title inference (e.g. a "diving" activity titled "Coral Gardens" would
# otherwise infer source_cat="nature" and discard a real scuba match).
_KNOWN_CATEGORIES: frozenset[str] = frozenset(c for _, c in _TITLE_CATEGORY_PATTERNS)


def _resolve_source_category(category: str | None, activity_title: str) -> str:
    """Prefer the trusted caller category over title inference when on-taxonomy."""
    normalized = (category or "").strip().lower().replace(" ", "_")
    if normalized in _KNOWN_CATEGORIES:
        return normalized
    return _infer_category_from_title(activity_title)


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
_SESSION_PAREN_SUFFIX_RE = re.compile(r"\(\s*session\s+\d+\s*\)", re.IGNORECASE)
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


def _normalize_match_cache_title(activity_title: str) -> str:
    """Coalesce only synthetic specialist suffixes while preserving meaningful qualifiers."""
    clean_title = _strip_location_prefix(activity_title or "")
    clean_title = _SESSION_PAREN_SUFFIX_RE.sub(" ", clean_title)
    clean_title = _SESSION_SUFFIX_RE.sub(" ", clean_title)
    clean_title = re.sub(r"\s+", " ", clean_title).strip(" -")
    return clean_title or activity_title


def _normalize_match_cache_category(category: str | None) -> str:
    """Scope match cache entries by category, including uncategorized lookups."""
    if not category or not category.strip():
        return "uncategorized"
    normalized = _NON_ALNUM_RE.sub("_", category.strip().lower()).strip("_")
    return normalized or "uncategorized"


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


# -- Geo resolution (product-detail + locations/bulk) -------------------------
# Product-detail responses expose itinerary stops as location *refs* (string
# tokens), not inline lat/lng -- those refs resolve to centers via
# POST /locations/bulk. We harvest the FIRST itinerary POI ref per product
# (multi-stop tours pin to their first stop -- approximate but no longer
# stacked), batch-resolve all refs in one bulk call, and cache the resulting
# center per product code (L1 + L2) so repeat builds/browse don't re-pay.
# Tighter than VIATOR_TIMEOUT (8s): the geo pass is detail-fetch THEN bulk (a
# sequential dependency), and it runs inside the shared 6s ENRICHMENT_TIMEOUT_S
# ceiling stacked AFTER partner enrichment. Capping each call at 3s bounds the
# pass at ~6s worst case; on a cold-cache timeout the whole pass degrades safely
# (no stamps -> prior centroid/GP fallback, no invented coords) and every result
# is L1+L2 cached so warm builds resolve in milliseconds.
_VIATOR_GEO_TIMEOUT = 3.0
_VIATOR_GEO_L2_TTL_HOURS = max(1, settings.viator_cache_ttl_hours)
_product_geo_cache = MemoryCache(
    maxsize=512, ttl=_viator_cache_ttl
)  # productCode -> {lat,lng}|None


def _inline_geo_from_product(product: dict) -> dict[str, float] | None:
    """Return inline {lat,lng} geo from a product if present (legacy/best-effort).

    Search/freetext products almost never carry inline coordinates; product
    detail responses expose itinerary stops as refs (see ``_first_poi_ref``).
    Kept as the single inline-geo path so ``viator_product_to_tile`` has one
    geo seam. Returns None when no inline lat/lng is found.
    """
    if not isinstance(product, dict):
        return None
    itinerary = product.get("itinerary", {})
    if isinstance(itinerary, dict):
        for item in itinerary.get("itineraryItems", []):
            if not isinstance(item, dict):
                continue
            poi = item.get("pointOfInterestLocation", {})
            loc = poi.get("location", {}) if isinstance(poi, dict) else {}
            if isinstance(loc, dict) and loc.get("latitude") and loc.get("longitude"):
                return {"lat": loc["latitude"], "lng": loc["longitude"]}
    return None


def _first_poi_ref(product: dict) -> str | None:
    """Harvest the FIRST itinerary point-of-interest location ref from a product.

    Decision (A): use ``itinerary.itineraryItems[].pointOfInterestLocation.location.ref``
    -- the first one -- as the product's representative location. ``logistics`` /
    ``meetingPoint`` refs are ignored (they resolve to empty centers). Returns the
    ref string, or None when the product exposes no itinerary POI ref.
    """
    if not isinstance(product, dict):
        return None
    itinerary = product.get("itinerary", {})
    if not isinstance(itinerary, dict):
        return None
    for item in itinerary.get("itineraryItems", []):
        if not isinstance(item, dict):
            continue
        poi = item.get("pointOfInterestLocation", {})
        if not isinstance(poi, dict):
            continue
        loc = poi.get("location", {})
        ref = loc.get("ref") if isinstance(loc, dict) else None
        if isinstance(ref, str) and ref.strip():
            return ref.strip()
    return None


async def _fetch_product_detail(product_code: str) -> dict | None:
    """Fetch a single Viator product detail (GET /products/{code}).

    Returns the product dict, or None on circuit-open / error / timeout.
    """
    if _viator_cb.is_open():
        return None
    try:
        record_viator_usage("request")
        client = await _get_viator_client()
        resp = await client.get(
            f"{VIATOR_BASE}/products/{product_code}",
            headers=_viator_headers(),
            timeout=_VIATOR_GEO_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        _viator_cb.record_success()
        record_viator_usage("success")
        return data if isinstance(data, dict) else None
    except Exception as e:
        _viator_cb.record_failure()
        record_viator_usage("error")
        logger.debug("[VIATOR] Product detail fetch failed for %s: %s", product_code, e)
        return None


async def _resolve_location_refs_bulk(refs: list[str]) -> dict[str, dict[str, float]]:
    """Resolve location refs to {lat,lng} centers via POST /locations/bulk.

    Returns a ``ref -> {lat,lng}`` map. Refs that the API omits or returns
    without a usable center are simply absent from the map (caller falls back).
    Returns an empty map on circuit-open / error / timeout (NOT cached as a
    definitive miss by callers -- transient failures must stay retryable).
    """
    refs = [r for r in dict.fromkeys(refs) if isinstance(r, str) and r.strip()]
    if not refs:
        return {}
    if _viator_cb.is_open():
        return {}
    try:
        record_viator_usage("request")
        client = await _get_viator_client()
        resp = await client.post(
            f"{VIATOR_BASE}/locations/bulk",
            headers=_viator_headers(),
            json={"locations": refs},
            timeout=_VIATOR_GEO_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        _viator_cb.record_success()
        record_viator_usage("success")
    except Exception as e:
        _viator_cb.record_failure()
        record_viator_usage("error")
        logger.debug("[VIATOR] Bulk location resolve failed (%d refs): %s", len(refs), e)
        return {}

    centers: dict[str, dict[str, float]] = {}
    locations = data.get("locations") if isinstance(data, dict) else None
    if not isinstance(locations, list):
        return centers
    for loc in locations:
        if not isinstance(loc, dict):
            continue
        ref = loc.get("reference") or loc.get("ref")
        center = loc.get("center")
        if not (isinstance(ref, str) and ref.strip() and isinstance(center, dict)):
            continue
        lat = center.get("latitude")
        lng = center.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            centers[ref.strip()] = {"lat": float(lat), "lng": float(lng)}
    return centers


async def _product_geo_l2_get(product_code: str) -> dict[str, float] | None:
    """Read a cached product geo from L2 (response_cache) and promote to L1."""
    from app.db import _get_async_session_factory
    from app.db_models import ResponseCache

    cache_key = make_cache_key("viator_geo", "v1", product_code)
    try:
        async_session_factory = _get_async_session_factory()
        async with async_session_factory() as db:
            from datetime import UTC, datetime

            from sqlalchemy import select

            result = await db.execute(
                select(ResponseCache)
                .where(ResponseCache.cache_key == cache_key)
                .where(ResponseCache.cache_type == "tiles")
                .where(ResponseCache.expires_at > datetime.now(UTC))
            )
            row = result.scalar_one_or_none()
            if not row:
                return None
            payload = row.response_json if isinstance(row.response_json, dict) else None
            return payload
    except Exception as e:
        logger.debug("[VIATOR] geo L2 read failed for %s: %s", product_code, e)
        return None


async def _product_geo_l2_set(product_code: str, geo: dict[str, float]) -> None:
    """Persist a resolved product geo to L2 (response_cache)."""
    from datetime import timedelta

    from app.db import _get_async_session_factory
    from app.services.cache_core import l2_upsert

    cache_key = make_cache_key("viator_geo", "v1", product_code)
    try:
        async_session_factory = _get_async_session_factory()
        async with async_session_factory() as db:
            try:
                await l2_upsert(
                    db,
                    cache_key=cache_key,
                    cache_type="tiles",
                    response_json=geo,
                    ttl=timedelta(hours=_VIATOR_GEO_L2_TTL_HOURS),
                )
            except Exception as e:
                await db.rollback()
                logger.debug("[VIATOR] geo L2 write failed for %s: %s", product_code, e)
    except Exception as e:
        logger.debug("[VIATOR] geo L2 session failed for %s: %s", product_code, e)


async def resolve_product_geo_batch(
    product_codes: list[str],
) -> dict[str, dict[str, float]]:
    """Resolve {lat,lng} centers for Viator product codes (batched, cached).

    For each code: L1 -> L2 cache check; for cache misses, fetch all product
    details concurrently, harvest each product's FIRST itinerary POI ref, then
    issue ONE POST /locations/bulk for all refs. Each resolved center is cached
    (L1 + L2) by product code. Codes with no POI ref or no resolved center are
    NOT returned (and not negatively cached -- transient failures stay
    retryable; only the definitive product-detail / bulk results populate cache).

    Returns ``product_code -> {lat,lng}`` for every code that resolved.
    """
    resolved: dict[str, dict[str, float]] = {}
    codes = [c for c in dict.fromkeys(product_codes) if isinstance(c, str) and c.strip()]
    if not codes:
        return resolved
    if not (settings.viator_enabled and settings.viator_api_key):
        return resolved

    pending: list[str] = []
    for code in codes:
        cached = _product_geo_cache.get(code)
        if cached is not None:
            record_viator_usage("cache_hit")
            if cached is not _NO_MATCH and isinstance(cached, dict):
                resolved[code] = cached
            continue
        l2_hit = await _product_geo_l2_get(code)
        if l2_hit is not None:
            record_viator_usage("cache_hit")
            _product_geo_cache.set(code, l2_hit)
            resolved[code] = l2_hit
            continue
        pending.append(code)

    if not pending or _viator_cb.is_open():
        return resolved

    # Fetch all product details concurrently (wall-time ~= slowest single call).
    details = await asyncio.gather(
        *[_fetch_product_detail(code) for code in pending],
        return_exceptions=True,
    )

    # Harvest the first POI ref per product; track ref -> codes (refs may repeat).
    code_ref: dict[str, str] = {}
    ref_to_codes: dict[str, list[str]] = {}
    for code, detail in zip(pending, details, strict=True):
        if isinstance(detail, Exception) or not isinstance(detail, dict):
            continue
        # Some detail responses may still carry inline geo -- prefer it (one call saved).
        inline = _inline_geo_from_product(detail)
        if inline:
            _product_geo_cache.set(code, inline)
            await _product_geo_l2_set(code, inline)
            resolved[code] = inline
            continue
        ref = _first_poi_ref(detail)
        if ref:
            code_ref[code] = ref
            ref_to_codes.setdefault(ref, []).append(code)

    if not ref_to_codes:
        return resolved

    centers = await _resolve_location_refs_bulk(list(ref_to_codes.keys()))
    for ref, center in centers.items():
        for code in ref_to_codes.get(ref, []):
            _product_geo_cache.set(code, center)
            await _product_geo_l2_set(code, center)
            resolved[code] = center

    return resolved


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

    # Extract inline geo coordinates from Viator product data (search/freetext
    # shape rarely carries these; the per-POI ref harvest below is the real
    # source for product-detail responses). Single shared geo path via the
    # harvest helper -- the old loc["latitude"] inline scan never matched the
    # ref-only itinerary shape, so it lived as dead code.
    geo: dict[str, float] | None = _inline_geo_from_product(product)

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
        "meta": {"category": _infer_category_from_title(title)},
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
    category: str | None = None,
) -> dict | None:
    """Match an activity title to a Viator product. Returns tile dict or None."""
    cache_title = _normalize_match_cache_title(activity_title)
    category_key = _normalize_match_cache_category(category)
    cache_key = f"viator_match:{destination.lower()}:{category_key}:{cache_title.lower()}"
    cached = _match_cache.get(cache_key)
    if cached is not None:
        record_viator_usage("cache_hit")
        return cached if cached is not _NO_MATCH else None
    clean_title = _clean_activity_title(activity_title)

    dest_id, destination_is_definitive = await resolve_destination_id(
        destination,
        return_status=True,
    )

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

    # Reject cross-category matches and try next best
    if best_product and _has_category_conflict(category, best_product.get("title", "")):
        logger.info(
            "[VIATOR] Rejected cross-category: category=%s product='%s'",
            category,
            best_product.get("title", ""),
        )
        non_conflicting = [
            p for p in products if not _has_category_conflict(category, p.get("title", ""))
        ]
        if non_conflicting:
            best_product, best_score, best_anchor_overlap = _best_scored_product(
                clean_title, non_conflicting
            )
        else:
            best_product = None
            best_score = 0

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
        if (
            shared
            and has_anchor_support
            and best_product
            and not _has_category_conflict(category, product_title)
        ):
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
    # ── Inferred category mismatch gate ────────────────────────────────
    # Catch cross-domain false positives not covered by explicit CATEGORY_CONFLICTS
    # (e.g., culinary activity matched to cycling tour, yoga matched to bus tour).
    # Anchor on the trusted caller category (the specialist topic) when it is
    # on-taxonomy; title inference alone mis-buckets e.g. a diving activity titled
    # "Coral Gardens" as "nature", which both falsely fires this gate (discarding a
    # real scuba match) AND lets it skip the generic-tours gate below (so an
    # airport-transfer "tours" product gets stamped on a dive).
    source_cat = _resolve_source_category(category, activity_title)
    product_cat = _infer_category_from_title(best_product.get("title", ""))

    if source_cat != product_cat and source_cat != "tours" and product_cat != "tours":
        # Both have specific but different categories — try a compatible product
        compatible = [
            p
            for p in products
            if _infer_category_from_title(p.get("title", "")) in (source_cat, "tours")
            and not _has_category_conflict(category, p.get("title", ""))
        ]
        if compatible:
            best_product, best_score, best_anchor_overlap = _best_scored_product(
                clean_title, compatible
            )
            if best_score < 40:
                logger.info(
                    "[VIATOR] Compatible fallback score too low (%d) for '%s'",
                    best_score,
                    best_product.get("title", "") if best_product else "",
                )
                best_product = None
            else:
                logger.info(
                    "[VIATOR] Inferred category fix: %s→%s, fell back to '%s'",
                    source_cat,
                    product_cat,
                    best_product.get("title", "") if best_product else "",
                )
        else:
            logger.info(
                "[VIATOR] Rejected inferred mismatch: source=%s product=%s title='%s'",
                source_cat,
                product_cat,
                best_product.get("title", ""),
            )
            best_product = None

    # Specific source category matched to generic "tours" — require activity stem overlap
    if (
        best_product
        and source_cat not in ("tours", "nature", "cultural", "temples")
        and _infer_category_from_title(best_product.get("title", "")) == "tours"
    ):
        _STEM_MAP = {
            "nightlife": "night",
            "climbing": "climb",
            "skiing": "ski",
            "cycling": "cycl",
            "sailing": "sail",
            "surfing": "surf",
            "diving": "div",
            "hiking": "hik",
            "cooking": "cook",
            "snorkeling": "snorkel",
        }
        stem = _STEM_MAP.get(source_cat, source_cat[:4]).lower()
        if stem not in best_product.get("title", "").lower():
            logger.info(
                "[VIATOR] Rejected generic tour for specific '%s': '%s'",
                source_cat,
                best_product.get("title", ""),
            )
            best_product = None

    if best_product is None:
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
