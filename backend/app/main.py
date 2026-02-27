import asyncio
import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
import time
import warnings
from datetime import datetime
from typing import Any, Dict, List
from urllib.parse import urlencode

import httpx

# =============================================================================
# EARLY WARNING SUPPRESSION (before any imports that might trigger warnings)
# =============================================================================
# Must happen before OpenAI/Pydantic imports to catch schema validation warnings.
# Bootstrap exception: importing `settings` here would instantiate pydantic_settings,
# triggering the very warnings we're suppressing. Reads same DEBUG env var as
# settings.debug_mode (Field alias="DEBUG") — single source of truth in config.py.
_debug_mode = os.getenv("DEBUG", "off").lower().strip()
if _debug_mode != "full":
    warnings.filterwarnings("ignore")
    logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)


class _PhotoProxyLogFilter(logging.Filter):
    """Suppress noisy access logs for the Google Places photo proxy endpoints."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return "/api/media/google-places-photo" not in msg


logging.getLogger("uvicorn.access").addFilter(_PhotoProxyLogFilter())

from fastapi import Depends, FastAPI, HTTPException, Request, Response  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse, StreamingResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

import app.db_models as db_models  # noqa: E402
from app.analytics_routes import router as analytics_router  # noqa: E402
from app.config import settings  # noqa: E402
from app.crud_document import (  # noqa: E402
    add_tiles_to_branch,
    apply_user_patch,
    get_document,
    get_document_data,
    get_or_create_document,
)
from app.crud_trip import (  # noqa: E402
    delete_messages_from_id,
    fetch_chat_history,
    get_last_user_message,
    get_latest_trip_context_for_session,
    get_or_create_session,
    get_session_by_token,
    record_chat_message,
)
from app.db import get_async_db  # noqa: E402
from app.debug_utils import _debug_info  # noqa: E402
from app.graph_plan_utils import (  # noqa: E402
    compute_today_iso,
    ensure_thread_id,
    generate_request_id,
    normalize_trip_inputs,
    sanitize_session_state,
)
from app.lifespan import lifespan as _lifespan  # noqa: E402
from app.middleware import (  # noqa: E402
    CSRFMiddleware,
    SessionMiddleware,
    clear_session_cookies,
    get_session_from_request,
)
from app.planner import (  # noqa: E402
    CACHE_SCHEMA_VERSION,
    PLANNER_BUILD_ID,
    PROMPT_BUNDLE_HASH,
    checkpoint_stats,
    clear_all_caches,
    clear_all_checkpoints,
    clear_response_caches,
    clear_session_checkpoint,
    get_graph_stats,
    get_planner_debug_info,
    response_cache_stats,
)
from app.planner.specialist_registry import has_explicit_category_intent  # noqa: E402
from app.rate_limit import limiter as _shared_limiter  # noqa: E402
from app.schemas import (  # noqa: E402
    ArrangementApplyRequest,
    ArrangementResult,
    ArrangementValidateRequest,
    BlockViolation,
    BrowseActivitiesRequest,
    ChatHistoryResponse,
    ChatMessageResponse,
    DayBlock,
    DayCard,
    DeleteLastMessageResponse,
    ExpandItineraryRequest,
    ExpandItineraryStreamEvent,
    GraphPlanRequest,
    InsertActivityBlockRequest,
    InsertActivityBlockResponse,
    PlanDocumentData,
    PlanDocumentPatch,
    PlanDocumentResponse,
    PlanViewState,
    RemoveBlockRequest,
    RemoveBlockResponse,
    RestoreSnapshotRequest,
    RestoreSnapshotResponse,
    SpecialistEnrichmentResponse,
    Tile,
    TileRefreshRequest,
    TileRefreshResponse,
    TilesSearchRequest,
    TripInputValidationRequest,
    TripInputValidationResponse,
)
from app.services.itinerary_builder import POI_TYPE_ALIASES as _POI_TYPE_ALIASES  # noqa: E402
from app.services.itinerary_builder import (  # noqa: E402
    _price_estimate_to_level,
)
from app.services.spend_guard import (  # noqa: E402
    SpendLimitExceeded,
    reserve_places_spend_or_raise,
    spend_guard_scope,
)
from app.services.unsplash import (  # noqa: E402
    clear_db_cache as clear_unsplash_db_cache,
)
from app.services.unsplash import (  # noqa: E402
    clear_memory_cache as clear_unsplash_memory_cache,
)
from app.services.unsplash import (  # noqa: E402
    get_image_for_destination,
)
from app.services.unsplash import (  # noqa: E402
    get_memory_cache_stats as get_unsplash_memory_stats,
)
from app.sse_state import (  # noqa: E402
    MAX_SSE_PER_IP,
    MAX_SSE_PER_SESSION,
    _sse_connections,
    _sse_state_lock,
)
from app.streaming import (  # noqa: E402
    generate_ndjson,
    generate_sse,
)
from app.tile_service.service import search_tiles  # noqa: E402
from app.validation import (  # noqa: E402
    cache_stats,
    clear_cache,
    prewarm_cache,
    validate_input_async,
)

# Configure logging for the graph plan route
logger = logging.getLogger(__name__)

_GOOGLE_PLACES_PHOTO_NAME_RE = re.compile(r"^places/[A-Za-z0-9_-]+/photos/[A-Za-z0-9_-]+$")

_GOOGLE_PLACES_PHOTO_MAX_SIGNED_TTL_SECONDS = 30 * 60


def _media_proxy_signing_secret() -> str:
    """Return server-side secret used to sign media proxy URLs."""
    secret = (
        settings.media_proxy_signing_key
        or settings.admin_api_key
        or settings.google_maps_api_secret
        or settings.google_maps_api_key
        or ""
    ).strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Media proxy signing key not configured")
    return secret


def _sign_google_places_photo_request(
    *,
    session_id: str,
    name: str,
    max_width: int,
    max_height: int,
    exp: int,
) -> str:
    payload = f"{session_id}\n{name}\n{max_width}\n{max_height}\n{exp}".encode("utf-8")
    secret = _media_proxy_signing_secret().encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def _build_signed_google_places_photo_url(
    *,
    session_id: str,
    name: str,
    max_width: int,
    max_height: int,
    ttl_seconds: int,
) -> str:
    now = int(time.time())
    ttl = max(60, min(ttl_seconds, _GOOGLE_PLACES_PHOTO_MAX_SIGNED_TTL_SECONDS))
    exp = now + ttl
    sig = _sign_google_places_photo_request(
        session_id=session_id,
        name=name,
        max_width=max_width,
        max_height=max_height,
        exp=exp,
    )
    query = urlencode(
        {
            "name": name,
            "max_width": max_width,
            "max_height": max_height,
            "exp": exp,
            "sig": sig,
        }
    )
    return f"/api/media/google-places-photo?{query}"


def _attach_signed_photo_urls_to_browse_tiles(
    tiles: list[dict[str, Any]],
    *,
    session_id: str,
    max_width: int = 256,
    max_height: int = 256,
    ttl_seconds: int = 300,
) -> list[dict[str, Any]]:
    """Rewrite browse tile image URLs to signed proxy URLs when photo_name is present."""
    for tile in tiles:
        if not isinstance(tile, dict):
            continue
        raw_photo_name = tile.get("photo_name")
        if not isinstance(raw_photo_name, str):
            continue
        photo_name = raw_photo_name.strip()
        if not _GOOGLE_PLACES_PHOTO_NAME_RE.fullmatch(photo_name):
            continue
        tile["image_url"] = _build_signed_google_places_photo_url(
            session_id=session_id,
            name=photo_name,
            max_width=max_width,
            max_height=max_height,
            ttl_seconds=ttl_seconds,
        )
    return tiles


def _resolve_stage3_view_state(builder_success: bool, conflicts: List[Any]) -> PlanViewState:
    """Resolve Stage 3 state from ItineraryBuilder output.

    Rules:
    - success + no conflicts => S3_ITINERARY_READY
    - success + conflicts    => S3_EDITING
    - failure + conflicts    => S3_PARTIAL_CONFLICT
    - failure + no conflicts => S3_BLOCKED
    """
    conflict_count = len(conflicts or [])
    if builder_success:
        return "S3_EDITING" if conflict_count > 0 else "S3_ITINERARY_READY"
    return "S3_PARTIAL_CONFLICT" if conflict_count > 0 else "S3_BLOCKED"


def _resolve_itinerary_document_view_state(
    fallback_state: str | None,
    itinerary_day_cards: List[Any] | None,
    constraint_violations: List[Any] | None = None,
) -> str:
    """Resolve final document view state from persisted graph output shape."""
    if not itinerary_day_cards:
        return fallback_state or "S0_BOOTSTRAP"
    # Preserve explicitly emitted Stage 3 states from upstream payloads.
    if fallback_state in {"S3_ITINERARY_READY", "S3_EDITING", "S3_PARTIAL_CONFLICT"}:
        return fallback_state
    return _resolve_stage3_view_state(
        True, constraint_violations if constraint_violations is not None else []
    )


def _is_question_like_message(message: str) -> bool:
    """Heuristic for question-like turns that should avoid category snapshot overrides."""
    text = (message or "").strip().lower()
    if not text:
        return False
    if text.endswith("?"):
        return True
    question_starts = (
        "what ",
        "how ",
        "do ",
        "does ",
        "is ",
        "are ",
        "can ",
        "could ",
        "should ",
        "where ",
        "when ",
        "which ",
        "who ",
    )
    return text.startswith(question_starts)


def _sanitize_trip_inputs_for_category_merge(
    incoming: Dict[str, Any], message: str
) -> Dict[str, Any]:
    """
    Keep document categories authoritative on generate/question turns unless
    the user explicitly requested category changes in this message.
    """
    if not incoming:
        return incoming

    text = (message or "").strip()
    is_generate_turn = text.upper() == "GENERATE_PLAN_NOW"
    if not (is_generate_turn or _is_question_like_message(text)):
        return incoming
    if has_explicit_category_intent(text):
        return incoming

    activity_settings = incoming.get("activity_settings")
    if hasattr(activity_settings, "model_dump"):
        activity_settings = activity_settings.model_dump()
    if not isinstance(activity_settings, dict) or "categories" not in activity_settings:
        return incoming

    sanitized = dict(incoming)
    activity_copy = dict(activity_settings)
    activity_copy.pop("categories", None)
    sanitized["activity_settings"] = activity_copy
    return sanitized


def _to_plain_dict(value: Any) -> Any:
    """Return Pydantic models as dicts while leaving plain values unchanged."""
    return value.model_dump() if hasattr(value, "model_dump") else value


def _merge_user_owned_trip_setting(
    existing: Any,
    incoming: Any,
    *,
    preserve_categories_if_missing: bool = False,
) -> Any:
    """
    Merge nested user-owned setting payloads without clobbering omitted keys.

    This is critical for `activity_settings`: on generate/question turns we strip
    `categories` from request snapshots, so missing categories must preserve the
    existing document/session value instead of replacing the whole dict.
    """
    incoming_value = _to_plain_dict(incoming)
    if incoming_value is None:
        return _to_plain_dict(existing)
    if not isinstance(incoming_value, dict):
        return incoming_value

    existing_value = _to_plain_dict(existing)
    if not isinstance(existing_value, dict):
        existing_value = {}

    merged = {**existing_value, **incoming_value}
    if preserve_categories_if_missing and "categories" not in incoming_value:
        if "categories" in existing_value:
            merged["categories"] = existing_value["categories"]

    return merged


def _merge_user_owned_trip_settings(
    target_trip_inputs: Dict[str, Any],
    incoming_trip_inputs: Dict[str, Any],
    *,
    user_owned_fields: set[str],
) -> None:
    """In-place deep merge for user-owned settings fields."""
    for field in user_owned_fields:
        if field not in incoming_trip_inputs or incoming_trip_inputs[field] is None:
            continue
        target_trip_inputs[field] = _merge_user_owned_trip_setting(
            target_trip_inputs.get(field),
            incoming_trip_inputs[field],
            preserve_categories_if_missing=(field == "activity_settings"),
        )


def _prepare_graph_plan_session_state(
    req: GraphPlanRequest,
    *,
    today_iso: str,
) -> Dict[str, Any]:
    """Normalize session state bootstrap/merge logic shared by graph endpoints."""
    session_state = sanitize_session_state(req.session_state)

    # Handle reset parameter: new thread_id when reset=true + empty session_state
    if req.reset and not session_state:
        session_state = {}
        session_state["thread_id"] = str(ensure_thread_id(None))  # Force new thread
        if req.trip_inputs:
            session_state["trip_inputs"] = normalize_trip_inputs(
                _sanitize_trip_inputs_for_category_merge(dict(req.trip_inputs), req.message)
            )
    elif not session_state:
        session_state = {}

    # Always merge request trip inputs into session state (incoming non-None values win)
    if "trip_inputs" not in session_state:
        raw_inputs = dict(req.trip_inputs) if req.trip_inputs else {}
        raw_inputs = _sanitize_trip_inputs_for_category_merge(raw_inputs, req.message)
        session_state["trip_inputs"] = normalize_trip_inputs(raw_inputs)
    elif req.trip_inputs:
        user_owned_fields = {
            "activity_settings",
            "hotel_settings",
            "flight_settings",
            "transport_settings",
            "booking_types",
        }
        existing = session_state.get("trip_inputs", {})
        incoming = _sanitize_trip_inputs_for_category_merge(dict(req.trip_inputs), req.message)
        for key, value in incoming.items():
            if key in user_owned_fields:
                continue
            if value is not None:
                existing[key] = value
        _merge_user_owned_trip_settings(
            existing,
            incoming,
            user_owned_fields=user_owned_fields,
        )
        session_state["trip_inputs"] = normalize_trip_inputs(existing)

    # Ensure thread_id is set and inject date anchor for parser logic.
    if "thread_id" not in session_state:
        session_state["thread_id"] = ensure_thread_id(req.thread_id)
    session_state["today_iso"] = today_iso

    # Merge frontend metadata hints when provided.
    metadata = session_state.setdefault("metadata", {})
    if req.ui_phase is not None:
        metadata["ui_phase"] = req.ui_phase
    if req.suggestion_clicked is not None:
        metadata["suggestion_clicked"] = req.suggestion_clicked

    return session_state


def _extract_day_block_coordinates(
    tile: Dict[str, Any], meta: Dict[str, Any]
) -> Dict[str, float] | None:
    """Normalize tile coordinate payloads into DayBlock `{lat, lng}` format."""

    def _coerce_pair(lat_value: Any, lng_value: Any) -> Dict[str, float] | None:
        if lat_value is None or lng_value is None:
            return None
        try:
            lat = float(lat_value)
            lng = float(lng_value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(lat) or not math.isfinite(lng):
            return None
        if abs(lat) > 90 or abs(lng) > 180:
            return None
        return {"lat": lat, "lng": lng}

    raw_coordinates = meta.get("coordinates")
    if raw_coordinates is None:
        raw_coordinates = tile.get("coordinates")

    if isinstance(raw_coordinates, dict):
        lng_value = raw_coordinates.get(
            "lng",
            raw_coordinates.get("lon", raw_coordinates.get("longitude")),
        )
        normalized = _coerce_pair(
            raw_coordinates.get("lat", raw_coordinates.get("latitude")),
            lng_value,
        )
        if normalized:
            return normalized

    if isinstance(raw_coordinates, (list, tuple)) and len(raw_coordinates) >= 2:
        # Mapbox arrays are [lng, lat]
        normalized = _coerce_pair(raw_coordinates[1], raw_coordinates[0])
        if normalized:
            return normalized

    raw_geo = tile.get("geo")
    if isinstance(raw_geo, dict):
        return _coerce_pair(raw_geo.get("lat"), raw_geo.get("lng", raw_geo.get("lon")))

    if hasattr(raw_geo, "lat"):
        geo_lat = getattr(raw_geo, "lat", None)
        geo_lng = getattr(raw_geo, "lng", getattr(raw_geo, "lon", None))
        return _coerce_pair(geo_lat, geo_lng)

    return None


def _first_trip_anchor_coordinates(doc_data: PlanDocumentData) -> Dict[str, float] | None:
    """Best-effort anchor coordinate for map fallback when a tile has no coordinates."""

    def _coerce_dict(coords: Any) -> Dict[str, float] | None:
        if not isinstance(coords, dict):
            return None
        lat = coords.get("lat")
        lng = coords.get("lng")
        if lat is None or lng is None:
            return None
        try:
            lat_num = float(lat)
            lng_num = float(lng)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(lat_num) or not math.isfinite(lng_num):
            return None
        if abs(lat_num) > 90 or abs(lng_num) > 180:
            return None
        return {"lat": lat_num, "lng": lng_num}

    # Prefer existing itinerary block coordinates (already aligned to the current trip).
    for day_card in doc_data.day_cards:
        for block in day_card.blocks:
            normalized = _coerce_dict(getattr(block, "coordinates", None))
            if normalized:
                return normalized

    # Fall back to any persisted tile coordinates/geo in the document.
    for tile in doc_data.tiles.values():
        tile_dict = tile.model_dump() if hasattr(tile, "model_dump") else tile
        if not isinstance(tile_dict, dict):
            continue
        normalized = _extract_day_block_coordinates(tile_dict, tile_dict.get("meta") or {})
        if normalized:
            return normalized

    return None


# _price_estimate_to_level imported from app.services.itinerary_builder


def _resolve_fill_day_block_constraints(tile_specialist: str, meta: Dict[str, Any]) -> List[str]:
    """Attach Tier-1 specialist constraint rules to fill-day blocks."""
    constraints: List[str] = []

    raw_meta_constraints = meta.get("constraints")
    if isinstance(raw_meta_constraints, list):
        constraints.extend(str(c) for c in raw_meta_constraints if c)

    from app.planner.specialist_registry import SPECIALIST_REGISTRY

    config = SPECIALIST_REGISTRY.get((tile_specialist or "").lower())
    if config:
        for constraint in config.hardcoded_constraints:
            rule = constraint.get("rule")
            if isinstance(rule, str) and rule:
                constraints.append(rule)

    # Preserve order while deduplicating.
    return list(dict.fromkeys(constraints))


app = FastAPI(title=settings.app_name, lifespan=_lifespan)
app.include_router(analytics_router)

# Async DB dependency for async endpoints
async_db_dependency = Depends(get_async_db)


# =============================================================================
# Rate Limiting (slowapi)
# =============================================================================


limiter = _shared_limiter  # local alias used by route decorators in this file
app.state.limiter = limiter


def _rate_limit_exceeded_handler(  # noqa: ARG001
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    _ = request
    # slowapi exc.detail is like "60 per 1 minute" — not a valid Retry-After
    # value per RFC 7231.  Parse the window into numeric seconds so the
    # frontend can respect the header.
    retry_after = 60  # sensible default
    detail_str = str(exc.detail) if exc.detail else ""
    if "per" in detail_str:
        try:
            parts = detail_str.split("per")[-1].strip().split()
            amount = int(parts[0]) if len(parts) >= 2 else 1
            unit = parts[1].rstrip("s") if len(parts) >= 2 else "minute"
            multipliers = {"second": 1, "minute": 60, "hour": 3600}
            retry_after = amount * multipliers.get(unit, 60)
        except (ValueError, IndexError):
            pass
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Please slow down."},
        headers={"Retry-After": str(retry_after)},
    )


app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# =============================================================================
# Admin Endpoint Gate
# =============================================================================


async def require_admin(request: Request) -> None:
    """FastAPI dependency: reject requests without valid X-Admin-Key header.

    ADMIN_API_KEY must be configured in every environment.
    """
    key = settings.admin_api_key
    if not key:
        raise HTTPException(403, "Admin API key not configured")
    if not secrets.compare_digest(request.headers.get("X-Admin-Key", ""), key):
        raise HTTPException(403, "Invalid admin key")


# =============================================================================
# SSE Concurrent Connection Limiter
# =============================================================================


async def _try_acquire_sse_slot(session_key: str, ip_key: str) -> str | None:
    """Reserve one SSE slot if capacity allows, otherwise return limiter scope."""
    async with _sse_state_lock:
        if _sse_connections[session_key] >= MAX_SSE_PER_SESSION:
            return "session"
        if _sse_connections[ip_key] >= MAX_SSE_PER_IP:
            return "ip"

        _sse_connections[session_key] += 1
        _sse_connections[ip_key] += 1
        return None


async def _release_sse_slot(session_key: str, ip_key: str) -> None:
    """Release one SSE slot and prune zero-value entries."""
    async with _sse_state_lock:
        for key in (session_key, ip_key):
            val = max(0, _sse_connections[key] - 1)
            if val == 0:
                _sse_connections.pop(key, None)
            else:
                _sse_connections[key] = val


async def _wait_for_session_stream_idle(session_key: str) -> None:
    """Queue until this session has no active graph SSE streams."""
    logged_wait = False
    while True:
        async with _sse_state_lock:
            active_streams = _sse_connections.get(session_key, 0)
        if active_streams <= 0:
            return

        if not logged_wait:
            logger.info(
                "[FILL-DAY] Queued behind %d active stream(s) for %s",
                active_streams,
                session_key,
            )
            logged_wait = True
        await asyncio.sleep(0.05)


# Build allowed origins list from config
# In production, this should be a single explicit origin
def _get_allowed_origins() -> List[str]:
    """Get list of allowed CORS origins."""
    origins = []

    # Add configured frontend origin
    if settings.frontend_origin:
        origins.append(settings.frontend_origin)

    # In local/development, also allow common local origins
    if settings.is_dev:
        origins.extend(
            [
                "http://localhost:3000",
                "http://127.0.0.1:3000",
            ]
        )

    return list(set(origins))  # Deduplicate


# Add CORS middleware first (must be before other middleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_allowed_origins(),
    allow_credentials=True,  # Required for cookies
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "X-CSRF-Token",
        "X-Client-Request-Id",
        "X-Client-Attempt",
    ],
    expose_headers=["Vary"],
)

# Add session middleware (issues session_id and csrf cookies)
app.add_middleware(SessionMiddleware)

# Add CSRF middleware (validates X-CSRF-Token header on unsafe methods)
app.add_middleware(CSRFMiddleware)


# =============================================================================
# Security Middleware (added after CSRF — LIFO means these run before CSRF)
# =============================================================================

MAX_BODY_BYTES = 524_288  # 512KB — expand-itinerary sends tiles + strategy_sections


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # unsafe-eval only in dev — required for Next.js HMR / Webpack eval source maps
    script_src = "'self' 'unsafe-inline'"
    if settings.is_dev:
        script_src += " 'unsafe-eval'"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        f"script-src {script_src}; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https://images.unsplash.com https://*.mapbox.com blob:; "
        "connect-src 'self' https://api.mapbox.com https://events.mapbox.com wss:; "
        "font-src 'self' data:; "
        "frame-ancestors 'none'"
    )
    return response


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    """Reject payloads exceeding MAX_BODY_BYTES before Pydantic parses them."""
    cl = request.headers.get("content-length")
    if cl:
        try:
            cl_int = int(cl)
        except (ValueError, TypeError):
            return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length"})
        if cl_int > MAX_BODY_BYTES:
            return JSONResponse(status_code=413, content={"detail": "Payload too large"})
    if not cl and request.method in {"POST", "PUT", "PATCH"}:
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            return JSONResponse(status_code=413, content={"detail": "Payload too large"})
    return await call_next(request)


@app.middleware("http")
async def exempt_options_from_rate_limit(request: Request, call_next):
    """Mark OPTIONS preflight requests as rate-limit-complete.

    CORSMiddleware handles preflight responses, but slowapi's @limiter.limit()
    decorator fires inside the route wrapper. If the preflight somehow reaches
    a route (e.g., non-standard OPTIONS without CORS headers), the decorator
    would count it against the user's rate-limit bucket. Setting this flag
    causes slowapi to skip the check entirely.
    """
    if request.method == "OPTIONS":
        request.state._rate_limiting_complete = True
    return await call_next(request)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "env": settings.env,
        "prompt_bundle_hash": PROMPT_BUNDLE_HASH,
        "planner_build_id": PLANNER_BUILD_ID,
        "cache_schema_version": CACHE_SCHEMA_VERSION,
    }


@app.get("/api/media/google-places-photo")
@limiter.limit("120/minute")
async def proxy_google_places_photo(
    request: Request,
    name: str,
    max_width: int = 640,
    max_height: int = 480,
    exp: int = 0,
    sig: str = "",
    db: AsyncSession = async_db_dependency,
):
    """
    Server-side proxy for Google Places photos.

    Keeps API keys on the backend while returning image bytes to the client.
    """
    session_id = get_session_from_request(request)
    session = await get_session_by_token(db, session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Session missing or expired")

    photo_name = (name or "").strip()
    if not _GOOGLE_PLACES_PHOTO_NAME_RE.fullmatch(photo_name):
        raise HTTPException(status_code=400, detail="Invalid Google photo reference")

    if not settings.google_maps_api_key:
        raise HTTPException(status_code=503, detail="Google Maps API key not configured")

    max_width = max(64, min(max_width, 1600))
    max_height = max(64, min(max_height, 1600))

    now = int(time.time())
    if exp <= now:
        raise HTTPException(status_code=403, detail="Signed photo URL expired")
    if exp > now + _GOOGLE_PLACES_PHOTO_MAX_SIGNED_TTL_SECONDS:
        raise HTTPException(status_code=403, detail="Signed photo URL has invalid expiry")
    expected_sig = _sign_google_places_photo_request(
        session_id=session_id,
        name=photo_name,
        max_width=max_width,
        max_height=max_height,
        exp=exp,
    )
    if not sig or not secrets.compare_digest(sig, expected_sig):
        raise HTTPException(status_code=403, detail="Invalid signed photo URL")

    # ETag based on photo resource name — enables conditional requests (304 Not Modified)
    etag = f'"{hashlib.md5(photo_name.encode()).hexdigest()}"'
    if_none_match = request.headers.get("if-none-match")
    if if_none_match and etag in [t.strip() for t in if_none_match.split(",")]:
        return Response(
            status_code=304,
            headers={"ETag": etag, "Cache-Control": "private, max-age=604800"},
        )

    from app.tile_service.google_places_provider import (
        _is_places_circuit_open,
        _record_places_circuit_failure,
        _record_places_circuit_success,
        record_google_places_usage,
    )

    if _is_places_circuit_open("photo_proxy"):
        return JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable"})

    try:
        with spend_guard_scope(session_id):
            reserve_places_spend_or_raise(source="google_places_photo:proxy")
    except SpendLimitExceeded as exc:
        raise HTTPException(
            status_code=429, detail=str(exc), headers={"Retry-After": "60"}
        ) from exc

    upstream_url = f"https://places.googleapis.com/v1/{photo_name}/media"
    params = {
        "maxWidthPx": max_width,
        "maxHeightPx": max_height,
        "key": settings.google_maps_api_key,
    }

    record_google_places_usage("photo_proxy", "request")

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            upstream = await client.get(upstream_url, params=params, headers={"Accept": "image/*"})
    except httpx.HTTPError as exc:
        record_google_places_usage("photo_proxy", "error", reason="httpx_error")
        _record_places_circuit_failure("photo_proxy")
        raise HTTPException(status_code=502, detail="Google Places photo fetch failed") from exc

    if upstream.status_code == 404:
        record_google_places_usage("photo_proxy", "error", reason="not_found")
        raise HTTPException(status_code=404, detail="Google Places photo not found")
    if upstream.status_code == 429:
        record_google_places_usage("photo_proxy", "error", reason="rate_limited")
        _record_places_circuit_failure("photo_proxy", status_code=429)
        raise HTTPException(status_code=429, detail="Google Places photo rate-limited")
    if upstream.status_code >= 400:
        record_google_places_usage("photo_proxy", "error", reason=f"http_{upstream.status_code}")
        _record_places_circuit_failure("photo_proxy", status_code=upstream.status_code)
        raise HTTPException(status_code=502, detail="Google Places photo upstream error")

    content_type = (upstream.headers.get("content-type") or "").split(";")[0].strip().lower()
    if not content_type.startswith("image/"):
        raise HTTPException(
            status_code=502, detail="Google Places photo returned non-image payload"
        )

    _record_places_circuit_success("photo_proxy")
    record_google_places_usage("photo_proxy", "success")

    headers = {
        "Cache-Control": "private, max-age=604800",  # 7 days — photo resource names are stable
        "ETag": etag,
    }
    content_length = upstream.headers.get("content-length")
    if content_length:
        headers["Content-Length"] = content_length

    return Response(content=upstream.content, media_type=content_type, headers=headers)


@app.get("/api/media/google-places-photo-url")
@limiter.limit("240/minute")
async def signed_google_places_photo_url(
    request: Request,
    name: str,
    max_width: int = 640,
    max_height: int = 480,
    ttl_seconds: int = 300,
    db: AsyncSession = async_db_dependency,
):
    """Issue short-lived, session-bound signed URLs for Google Places photo proxy."""
    session_id = get_session_from_request(request)
    session = await get_session_by_token(db, session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Session missing or expired")

    photo_name = (name or "").strip()
    if not _GOOGLE_PLACES_PHOTO_NAME_RE.fullmatch(photo_name):
        raise HTTPException(status_code=400, detail="Invalid Google photo reference")

    if not settings.google_maps_api_key:
        raise HTTPException(status_code=503, detail="Google Maps API key not configured")

    width = max(64, min(max_width, 1600))
    height = max(64, min(max_height, 1600))
    ttl = max(60, min(ttl_seconds, _GOOGLE_PLACES_PHOTO_MAX_SIGNED_TTL_SECONDS))
    signed_url = _build_signed_google_places_photo_url(
        session_id=session_id,
        name=photo_name,
        max_width=width,
        max_height=height,
        ttl_seconds=ttl,
    )
    return {
        "url": signed_url,
        "expires_in_seconds": ttl,
    }


# =============================================================================
# Trip Input Validation Endpoint
# =============================================================================


@app.post("/api/validate-trip-input", response_model=TripInputValidationResponse)
@limiter.limit("6/minute")
async def validate_trip_input(request: Request, req: TripInputValidationRequest):
    """
    Validate a trip input (origin or destination).

    Returns corrected values if the input was valid but had typos/formatting issues.
    For destinations, may return multiple values if the input contained multiple
    places (e.g., "Paris and Rome" -> ["Paris", "Rome"]).

    Raises HTTP 503 if validation fails after retries.

    Tier 11.1: Uses async validation with non-blocking retries for better concurrency.
    """
    try:
        session_id = get_session_from_request(request)
        with spend_guard_scope(session_id):
            # Tier 11.1: Use async validation with non-blocking retries
            result = await validate_input_async(req.value, req.field_type, session_id=session_id)
        return TripInputValidationResponse(
            corrected_values=result.corrected_values,
            is_valid=result.is_valid,
            reason=result.reason,
        )
    except SpendLimitExceeded as exc:
        raise HTTPException(
            status_code=429, detail=str(exc), headers={"Retry-After": "60"}
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# =============================================================================
# Destination Image Endpoint
# =============================================================================


class DestinationImageRequest(BaseModel):
    """Request for destination image."""

    destination: str


class DestinationImageResponse(BaseModel):
    """Response with destination image URL."""

    image_url: str
    destination: str


@app.post("/api/destination-image", response_model=DestinationImageResponse)
@limiter.limit("15/minute")
async def get_destination_image(  # noqa: ARG001
    request: Request, req: DestinationImageRequest, db: AsyncSession = async_db_dependency
):
    """
    Get the Unsplash image URL for a destination.

    Called when user selects a destination to show the correct banner image
    immediately, without waiting for plan generation.
    """
    _ = request
    dest_name = req.destination.strip()
    if not dest_name:
        raise HTTPException(status_code=400, detail="Destination is required")

    image_url = await get_image_for_destination(
        dest_name,
        variant=0,
        db=db,
        width=1600,
        height=900,
    )

    return DestinationImageResponse(
        image_url=image_url,
        destination=dest_name,
    )


@app.post("/api/admin/clear-validation-cache", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def admin_clear_validation_cache(request: Request):  # noqa: ARG001
    """
    Clear the validation cache. For development/debugging only.
    """
    before = await cache_stats()
    count = await clear_cache()
    # Re-populate with common values
    new_count = await prewarm_cache()
    return {
        "cleared": count,
        "repopulated": new_count,
        "stats": {
            "before": before,
            "after": await cache_stats(),
        },
    }


@app.post("/api/admin/fresh-start", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def admin_fresh_start(request: Request):  # noqa: ARG001
    """
    Perform a complete system cache and checkpoint cleanup.

    This clears:
    - All validation caches (preserving rate limiting)
    - All LLM response caches
    - All stale LangGraph checkpoints (>24h idle)

    For development/debugging and maintenance only.
    Does NOT clear rate limiting cache to prevent abuse.
    """
    # Get before stats
    before_validation = await cache_stats()
    before_response = response_cache_stats()
    before_checkpoints = checkpoint_stats()

    # Clear validation caches (preserve rate limiting)
    validation_cleared = await clear_cache(preserve_rate_limiting=True)

    # Clear response caches
    response_cleared = await clear_response_caches()

    # Re-populate validation cache with common values
    validation_repopulated = await prewarm_cache()

    return {
        "validation": {
            "cleared": validation_cleared,
            "repopulated": validation_repopulated,
            "before": before_validation,
            "after": await cache_stats(),
        },
        "response_caches": {
            "cleared": response_cleared,
            "before": before_response,
            "after": response_cache_stats(),
        },
        "checkpoints": {
            "before": before_checkpoints,
            "after": checkpoint_stats(),
        },
    }


@app.get("/api/admin/graph-stats", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
def admin_graph_stats(request: Request):  # noqa: ARG001
    """
    Get comprehensive graph statistics for observability.

    Returns routing decisions, template usage, and cache performance metrics.
    Useful for monitoring token savings and optimization effectiveness.

    Response:
    {
        "routing": {
            "keyword_bypasses": int,  # Router skipped via keyword heuristic
            "router_calls": int,      # Router LLM was invoked
            "negation_defers": int,   # Keyword was negated, deferred to router
            "keyword_bypass_rate": float
        },
        "templates": {
            "template_hits": int,    # Template found and used
            "template_misses": int,  # No template, fell back to LLM
            "template_hit_rate": float
        },
        "extractor_cache": {...},
        "strategy_cache": {...}
    }
    """
    return get_graph_stats()


@app.get("/api/admin/planner", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
def admin_planner_debug(request: Request):  # noqa: ARG001
    """
    Get planner configuration and build identifiers for ops debugging.

    Returns stable JSON schema with behavioral config and build info.
    Useful for verifying deployment state and debugging cache issues.

    Response includes:
    - admin_endpoint_version: Schema version for evolution tracking
    - prompt_bundle_hash: Hash of prompt templates
    - planner_build_id: Git SHA or build ID
    - cache_schema_version: Cache payload schema version
    - enabled_strategy_topics: List of enabled strategy topics
    - enabled_strategy_topics_source: "defaults" or "env_override"
    - enable_all_strategy_topics: Whether env override is active
    - llm_budget_max_calls_non_ready: Max LLM calls per non-ready turn
    - cache_ttl_map_seconds: TTL per cache type
    - gate_precedence_version: Gate logic version
    - node_logic_version: Per-node logic versions
    - strategy_output_caps: Max output characters for strategy responses
    """
    return get_planner_debug_info()


@app.post("/api/admin/clear-all-checkpoints", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def admin_clear_all_checkpoints(request: Request):  # noqa: ARG001
    """
    Clear ALL LangGraph checkpoints regardless of age.

    Use with caution - this will clear all in-progress session states.
    For emergency maintenance only.
    """
    before = checkpoint_stats()
    cleared = await clear_all_checkpoints()
    return {
        "cleared": cleared,
        "before": before,
        "after": checkpoint_stats(),
    }


@app.post("/api/admin/clear-all-caches", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def admin_clear_all_caches(  # noqa: ARG001
    request: Request, db: AsyncSession = async_db_dependency
):
    """
    Clear ALL caches in the system - comprehensive cache reset.

    Clears:
    - All LangGraph/planner caches (Response, Extractor, Strategy, Tile, GateEvaluation)
    - All validation caches (including rate limiting)
    - Unsplash memory cache
    - Unsplash database cache
    - All LangGraph checkpoints
    - Prompt/template caches

    WARNING: Destructive operation for development/maintenance only.
    """
    _ = request
    results = {
        "timestamp": datetime.utcnow().isoformat(),
        "caches_cleared": {},
    }

    # 1. Get before stats
    before_validation = await cache_stats()
    before_response = response_cache_stats()
    before_checkpoints = checkpoint_stats()
    before_unsplash = get_unsplash_memory_stats()

    # 2. Clear planner caches + validation + checkpointer + prompts
    planner_cleared = await clear_all_caches()
    results["caches_cleared"]["planner_and_validation"] = planner_cleared

    # 3. Clear Unsplash memory cache
    unsplash_memory_count = before_unsplash["entries"]
    await clear_unsplash_memory_cache()
    results["caches_cleared"]["unsplash_memory"] = unsplash_memory_count

    # 4. Clear Unsplash database cache
    unsplash_db_count = await clear_unsplash_db_cache(db)
    results["caches_cleared"]["unsplash_database"] = unsplash_db_count

    # 5. Clear Specialist LLM cache (L1 + L2)
    from app.services.specialist_cache import clear_db_cache as clear_specialist_db
    from app.services.specialist_cache import clear_memory_cache as clear_specialist_memory

    specialist_memory_count = clear_specialist_memory()
    specialist_db_count = await clear_specialist_db(db)
    results["caches_cleared"]["specialist_memory"] = specialist_memory_count
    results["caches_cleared"]["specialist_database"] = specialist_db_count

    # 6. Clear Tile cache (L1 + L2)
    from app.services.tile_cache import clear_db_cache as clear_tile_db
    from app.services.tile_cache import clear_memory_cache as clear_tile_memory

    tile_memory_count = clear_tile_memory()
    tile_db_count = await clear_tile_db(db)
    results["caches_cleared"]["tile_memory"] = tile_memory_count
    results["caches_cleared"]["tile_database"] = tile_db_count

    # 7. Clear Experience cache (L1 + L2)
    from app.services.experience_generator import (
        clear_experience_cache,
        clear_experience_db_cache,
    )

    experience_memory_count = clear_experience_cache()
    experience_db_count = await clear_experience_db_cache(db)
    results["caches_cleared"]["experience_memory"] = experience_memory_count
    results["caches_cleared"]["experience_database"] = experience_db_count

    # 8. Clear Router cache (L1 only)
    from app.services.router_cache import clear_cache as clear_router_cache

    router_count = clear_router_cache()
    results["caches_cleared"]["router_memory"] = router_count

    # 9. Summary
    total = (
        planner_cleared
        + unsplash_memory_count
        + unsplash_db_count
        + specialist_memory_count
        + specialist_db_count
        + tile_memory_count
        + tile_db_count
        + experience_memory_count
        + experience_db_count
        + router_count
    )
    results["total_entries_cleared"] = total
    results["before"] = {
        "validation": before_validation,
        "response": before_response,
        "checkpoints": before_checkpoints,
        "unsplash_memory": before_unsplash,
    }
    results["after"] = {
        "validation": await cache_stats(),
        "response": response_cache_stats(),
        "checkpoints": checkpoint_stats(),
        "unsplash_memory": get_unsplash_memory_stats(),
    }

    return results


@app.post("/api/admin/clear-l1-l2-caches", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def admin_clear_l1_l2_caches(  # noqa: ARG001
    request: Request, db: AsyncSession = async_db_dependency
):
    """
    Force-clear cache layers (L1 memory + L2 DB) used by planner/services.

    Clears:
    - L1: specialist, tile, experience, router, feasibility, browse, enrichment,
      exploration-answer, iata, unsplash memory
    - L2: ALL rows in response_cache + unsplash image cache rows

    Does NOT clear:
    - Validation/rate-limit caches
    - LangGraph checkpoints
    - Session/chat/document data
    """
    _ = request
    from sqlalchemy import delete, func, select

    from app.db_models import ResponseCache
    from app.planner.services.feasibility_service import _feasibility_cache
    from app.planner.services.iata_resolver import clear_iata_cache
    from app.services.activity_browser import _browse_cache
    from app.services.experience_generator import clear_experience_cache
    from app.services.router_cache import clear_cache as clear_router_cache
    from app.services.specialist_cache import clear_memory_cache as clear_specialist_memory
    from app.services.tile_cache import clear_memory_cache as clear_tile_memory
    from app.tile_service.google_places_provider import _enrich_mem

    l2_before_by_type: Dict[str, int] = {}
    l2_before_total = 0
    try:
        grouped = await db.execute(
            select(ResponseCache.cache_type, func.count())
            .select_from(ResponseCache)
            .group_by(ResponseCache.cache_type)
        )
        for cache_type, count in grouped.all():
            key = str(cache_type or "unknown")
            value = int(count or 0)
            l2_before_by_type[key] = value
            l2_before_total += value
    except Exception:
        l2_before_by_type = {}
        l2_before_total = 0

    unsplash_memory_before = int(get_unsplash_memory_stats().get("entries", 0))

    l1_cleared = {
        "specialist_memory": clear_specialist_memory(),
        "tile_memory": clear_tile_memory(),
        "experience_memory": clear_experience_cache(),
        "router_memory": clear_router_cache(),
        "feasibility_memory": _feasibility_cache.clear(),
        "browse_memory": _browse_cache.clear(),
        "places_enrichment_memory": _enrich_mem.clear(),
        "iata_memory": clear_iata_cache(),
        "unsplash_memory": unsplash_memory_before,
    }

    await clear_unsplash_memory_cache()

    l2_response_cache = 0
    try:
        response_cache_delete = await db.execute(delete(ResponseCache))
        await db.commit()
        l2_response_cache = int(response_cache_delete.rowcount or 0)
    except Exception:
        await db.rollback()

    unsplash_db_cleared = await clear_unsplash_db_cache(db)

    l2_cleared = {
        "response_cache_rows": l2_response_cache,
        "unsplash_database": unsplash_db_cleared,
    }

    total_l1 = sum(int(value) for value in l1_cleared.values())
    total_l2 = sum(int(value) for value in l2_cleared.values())
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "before": {
            "l2": {
                "response_cache_total": l2_before_total,
                "response_cache_by_type": l2_before_by_type,
            }
        },
        "cleared": {
            "l1": l1_cleared,
            "l2": l2_cleared,
        },
        "totals": {
            "l1": total_l1,
            "l2": total_l2,
            "overall": total_l1 + total_l2,
        },
    }


# =============================================================================
# Specialist Cache Admin Endpoints
# =============================================================================


@app.get("/api/admin/specialist-cache-stats", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def admin_specialist_cache_stats(  # noqa: ARG001
    request: Request, db: AsyncSession = async_db_dependency
):
    """
    Get specialist LLM cache statistics for observability.

    Returns L1 (memory) and L2 (database) hit/miss counts, sizes, and TTLs.
    """
    _ = request
    from sqlalchemy import func, select

    from app.db_models import ResponseCache
    from app.services.specialist_cache import get_cache_stats

    stats = get_cache_stats()

    # Add L2 database stats
    try:
        total_result = await db.execute(select(func.count()).select_from(ResponseCache))
        stats["l2_entries"] = total_result.scalar() or 0

        total_hits = await db.execute(
            select(func.sum(ResponseCache.hit_count)).select_from(ResponseCache)
        )
        stats["l2_total_hits"] = total_hits.scalar() or 0
    except Exception:
        stats["l2_entries"] = "error"
        stats["l2_total_hits"] = "error"

    return stats


@app.post("/api/admin/clear-specialist-cache", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def admin_clear_specialist_cache(  # noqa: ARG001
    request: Request, db: AsyncSession = async_db_dependency
):
    """
    Clear both L1 (memory) and L2 (database) specialist caches.

    Use for development/debugging when you want fresh LLM calls.
    """
    _ = request
    from app.services.specialist_cache import clear_db_cache, clear_memory_cache

    l1_cleared = clear_memory_cache()
    l2_cleared = await clear_db_cache(db)

    return {
        "cleared": {
            "l1_memory": l1_cleared,
            "l2_database": l2_cleared,
        },
        "total": l1_cleared + l2_cleared,
    }


# =============================================================================
# Tile Cache Admin Endpoints
# =============================================================================


@app.get("/api/admin/tile-cache-stats", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def admin_tile_cache_stats(  # noqa: ARG001
    request: Request, db: AsyncSession = async_db_dependency
):
    """
    Get tile data cache statistics for observability.

    Returns L1 (memory) and L2 (database) hit/miss counts, sizes, and TTLs.
    """
    _ = request
    from sqlalchemy import func, select

    from app.db_models import ResponseCache
    from app.services.tile_cache import get_cache_stats

    stats = get_cache_stats()

    # Add L2 database stats
    try:
        total_result = await db.execute(
            select(func.count())
            .select_from(ResponseCache)
            .where(ResponseCache.cache_type == "tiles")
        )
        stats["l2_entries"] = total_result.scalar() or 0
    except Exception:
        stats["l2_entries"] = "error"

    return stats


@app.post("/api/admin/clear-tile-cache", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def admin_clear_tile_cache(  # noqa: ARG001
    request: Request, db: AsyncSession = async_db_dependency
):
    """
    Clear both L1 (memory) and L2 (database) tile caches.

    Use for development/debugging when you want fresh provider data.
    """
    _ = request
    from app.services.tile_cache import clear_db_cache, clear_memory_cache

    l1_cleared = clear_memory_cache()
    l2_cleared = await clear_db_cache(db)

    return {
        "cleared": {
            "l1_memory": l1_cleared,
            "l2_database": l2_cleared,
        },
        "total": l1_cleared + l2_cleared,
    }


# =============================================================================
# Router Cache Admin Endpoints
# =============================================================================


@app.get("/api/admin/router-cache-stats", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def admin_router_cache_stats(request: Request):  # noqa: ARG001
    """
    Get router extraction cache statistics for observability.

    Note: Router cache is L1-only (no database persistence).
    Shows hits, misses, and skipped context-dependent queries.
    """
    from app.services.router_cache import get_cache_stats

    return get_cache_stats()


@app.post("/api/admin/clear-router-cache", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def admin_clear_router_cache(request: Request):  # noqa: ARG001
    """
    Clear router extraction cache (L1 memory only).

    Use for development/debugging when you want fresh extractions.
    """
    from app.services.router_cache import clear_cache

    count = clear_cache()

    return {
        "cleared": {
            "l1_memory": count,
        },
        "total": count,
    }


# =============================================================================
# Unified Cache Stats Endpoint
# =============================================================================


@app.get("/api/admin/cache-stats", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def admin_all_cache_stats(  # noqa: ARG001
    request: Request, db: AsyncSession = async_db_dependency
):
    """
    Get all cache statistics in one call.

    Returns stats for:
    - Specialist cache (L1 + L2)
    - Tile cache (L1 + L2)
    - Router cache (L1 only)
    """
    _ = request
    from sqlalchemy import func, select

    from app.db_models import ResponseCache
    from app.services import router_cache, specialist_cache, tile_cache

    # Specialist stats
    specialist_stats = specialist_cache.get_cache_stats()
    try:
        specialist_count = await db.execute(
            select(func.count())
            .select_from(ResponseCache)
            .where(ResponseCache.cache_type == "specialist")
        )
        specialist_stats["l2_entries"] = specialist_count.scalar() or 0
    except Exception:
        specialist_stats["l2_entries"] = "error"

    # Tile stats
    tile_stats = tile_cache.get_cache_stats()
    try:
        tiles_count = await db.execute(
            select(func.count())
            .select_from(ResponseCache)
            .where(ResponseCache.cache_type == "tiles")
        )
        tile_stats["l2_entries"] = tiles_count.scalar() or 0
    except Exception:
        tile_stats["l2_entries"] = "error"

    # Router stats (L1 only)
    router_stats = router_cache.get_cache_stats()

    return {
        "specialist": specialist_stats,
        "tiles": tile_stats,
        "router": router_stats,
    }


# =============================================================================
# SSE Streaming Graph Plan Endpoint
# =============================================================================


@app.post("/api/graph_plan/stream")
@limiter.limit("6/minute;30/hour")
async def graph_plan_stream_endpoint(
    request: Request,
    req: GraphPlanRequest,
):
    """
    Streaming version of the graph plan endpoint using Server-Sent Events (SSE).

    Streams tokens as they are generated, then sends a final 'complete' event
    with the full response data including session state and extracted trip inputs.

    SSE Event Format:
        event: token
        data: {"type": "token", "data": "..."}

        event: complete
        data: {"type": "complete", "data": {...}}

        event: error
        data: {"type": "error", "message": "..."}
    """
    # --- Feature flag gate ---
    if not settings.enable_graph_plan_route:

        async def error_stream():
            payload = json.dumps({"type": "error", "message": "Graph plan route is disabled"})
            yield f"event: error\ndata: {payload}\n\n"

        return StreamingResponse(
            error_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # --- Fast message length check (before any DB work) ---
    from app.planner.nodes.input_gate_config import (
        GATE_THRESHOLDS as _GATE_THRESHOLDS,  # noqa: E402
    )

    _max_msg_chars = _GATE_THRESHOLDS["max_user_message_chars"]
    if len(req.message) > _max_msg_chars:
        return JSONResponse(
            status_code=422,
            content={"detail": f"Message too long (max {_max_msg_chars} chars)."},
        )

    # --- Generate request ID and compute today_iso ---
    request_id = generate_request_id()
    today_iso = compute_today_iso()
    client_request_id = request.headers.get("X-Client-Request-Id")
    client_attempt = request.headers.get("X-Client-Attempt")
    logger.info(
        "[graph_plan/stream] rid=%s attempt=%s generated_request_id=%s",
        client_request_id,
        client_attempt,
        request_id,
    )

    # --- Sanitize and prepare session state ---
    session_state = _prepare_graph_plan_session_state(req, today_iso=today_iso)

    # --- Get session from request for document persistence ---
    session_id = get_session_from_request(request)

    # --- SSE concurrent connection limit ---
    client_ip = request.client.host if request.client else "unknown"
    session_key = f"session:{session_id}"
    ip_key = f"ip:{client_ip}"

    return StreamingResponse(
        generate_sse(
            session_id=session_id,
            req=req,
            session_state=session_state,
            request_id=request_id,
            today_iso=today_iso,
            session_key=session_key,
            ip_key=ip_key,
            request=request,
            try_acquire_sse_slot=_try_acquire_sse_slot,
            release_sse_slot=_release_sse_slot,
            sanitize_trip_inputs_for_category_merge=_sanitize_trip_inputs_for_category_merge,
            merge_user_owned_trip_settings=_merge_user_owned_trip_settings,
            resolve_itinerary_document_view_state=_resolve_itinerary_document_view_state,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@app.delete("/api/session", status_code=204)
@limiter.limit("60/minute")
async def reset_session(
    request: Request,
    db: AsyncSession = async_db_dependency,
):
    """
    Reset/delete a planning session and all associated data.

    Uses row-level locking to prevent deadlocks with concurrent plan operations.
    Also clears session cookies from the browser and LangGraph checkpoint state.
    """
    from sqlalchemy import delete

    session_id = get_session_from_request(request)

    # Clear LangGraph checkpoint for this session (even if session not in DB)
    if session_id:
        await clear_session_checkpoint(session_id)

    # Clear response caches (or all caches in dev mode)
    if settings.aggressive_cache_clear:
        await clear_all_caches()  # Clear everything including validation caches
    else:
        await clear_response_caches()  # Preserve validation cache in production

    # Lock the session row first to prevent deadlocks with concurrent operations
    session = await get_session_by_token(db, session_id, lock_for_update=True)
    if not session:
        # Clear cookies even if session not found in DB
        response = Response(status_code=204)
        return clear_session_cookies(response)

    # Delete PlanDocument for this session
    await db.execute(
        delete(db_models.PlanDocument).where(db_models.PlanDocument.session_id == session.id)
    )

    # Delete ChatMessages for this session
    await db.execute(
        delete(db_models.ChatMessage).where(db_models.ChatMessage.session_id == session.id)
    )

    # Delete TripContexts for this session
    await db.execute(
        delete(db_models.TripContext).where(db_models.TripContext.session_id == session.id)
    )

    # Delete TileClicks for this session
    await db.execute(
        delete(db_models.TileClick).where(db_models.TileClick.session_id == session_id)
    )

    # Delete the session itself
    await db.delete(session)
    await db.commit()

    # Clear cookies from browser
    response = Response(status_code=204)
    return clear_session_cookies(response)


# ─────────────────────────────────────────────────────────────────────────────
# Chat History Endpoint
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/api/chat", response_model=ChatHistoryResponse)
@limiter.limit("60/minute")
async def get_chat_history(
    request: Request,
    db: AsyncSession = async_db_dependency,
):
    """
    Get chat history for the current session.

    Returns the last 50 messages in chronological order (oldest first).
    Used by the frontend to restore chat state on page load.
    """
    session_id = get_session_from_request(request)
    session = await get_session_by_token(db, session_id)

    # Return empty history for new sessions (no error)
    if not session:
        return ChatHistoryResponse(messages=[])

    # Fetch messages (returns oldest first after reversal)
    messages = await fetch_chat_history(db, session=session, limit=50)

    # Convert to response format, filtering out empty and system messages
    # System messages are internal audit logs (e.g., UI edit tracking) not meant for display
    response_messages = [
        ChatMessageResponse(
            id=str(msg.id),
            role=msg.role,
            content=msg.content,
            created_at=msg.created_at.isoformat(),
        )
        for msg in messages
        if msg.content and msg.content.strip() and msg.role in ("user", "assistant")
    ]

    return ChatHistoryResponse(messages=response_messages)


@app.delete("/api/chat/last", response_model=DeleteLastMessageResponse)
@limiter.limit("60/minute")
async def delete_last_message(
    request: Request,
    db: AsyncSession = async_db_dependency,
):
    """
    Delete the last user message and its associated assistant response.

    This operation:
    1. Finds the most recent user message
    2. Retrieves the trip_inputs snapshot from that message (if available)
    3. Deletes the user message and all subsequent messages
    4. Restores trip_inputs from the snapshot (if available)
    5. Returns the deleted count, restored trip_inputs, and remaining messages

    Used for "undo" functionality to revert the last chat turn.
    """
    session_id = get_session_from_request(request)
    session = await get_session_by_token(db, session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Find the last user message
    last_user_msg = await get_last_user_message(db, session=session)
    if not last_user_msg:
        raise HTTPException(status_code=404, detail="No user message to delete")

    # Get the snapshot for rollback
    restored_trip_inputs = last_user_msg.trip_inputs_snapshot

    # Delete the message and all subsequent messages
    deleted_count = await delete_messages_from_id(db, session=session, message_id=last_user_msg.id)

    # Restore trip_inputs if we have a snapshot
    if restored_trip_inputs:
        doc = await get_document(db, session=session)
        if doc:
            doc_data = doc.document or {}
            doc_data["trip_inputs"] = restored_trip_inputs
            doc.document = doc_data
            await db.flush()

    # Fetch remaining messages
    remaining_messages = await fetch_chat_history(db, session=session, limit=50)
    response_messages = [
        ChatMessageResponse(
            id=str(msg.id),
            role=msg.role,
            content=msg.content,
            created_at=msg.created_at.isoformat(),
        )
        for msg in remaining_messages
        if msg.content and msg.content.strip() and msg.role in ("user", "assistant")
    ]

    await db.commit()

    return DeleteLastMessageResponse(
        deleted_count=deleted_count,
        restored_trip_inputs=restored_trip_inputs,
        messages=response_messages,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Plan Document Endpoints - Centralized source of truth for branches & tiles
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/api/document", response_model=PlanDocumentResponse)
@limiter.limit("60/minute")
async def get_plan_document(
    request: Request,
    db: AsyncSession = async_db_dependency,
):
    """
    Get the current plan document for a session.
    Returns the centralized source of truth for branches and tiles.
    """
    session_id = get_session_from_request(request)
    session = await get_session_by_token(db, session_id)
    if not session:
        # No session in DB yet - return 204 (no document)
        return Response(status_code=204)

    doc = await get_document(db, session=session)
    if not doc:
        return Response(status_code=204)

    doc_data = get_document_data(doc)
    return PlanDocumentResponse(
        version=doc.version,
        updated_by=doc.updated_by,
        document=doc_data,
        updated_at=doc.updated_at.isoformat(),
        changes_made=False,
    )


@app.get("/api/specialist/{section_id}/enrichment")
@limiter.limit("30/minute")
async def get_specialist_enrichment(
    request: Request,
    section_id: str,
    db: AsyncSession = async_db_dependency,
):
    """
    Fetch enriched specialist section data (Phase B result).

    Returns 200 with section data if Phase B enrichment has completed.
    Returns 202 with {"status": "pending"} if Phase B is still running or hasn't produced data yet.

    Called by frontend on specialist card open (Option B3 fetch-on-open pattern).
    """
    session_id = get_session_from_request(request)
    session = await get_session_by_token(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    doc = await get_document(db, session=session)
    if not doc:
        raise HTTPException(status_code=404, detail="No plan document")

    doc_data = get_document_data(doc)
    section = next(
        (s for s in (doc_data.strategy_sections or []) if s.id == section_id),
        None,
    )
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")

    # For local_expert: check if travel_intelligence has been populated by Phase B
    if section.specialist_type == "local_expert":
        status_blob = section.local_expert_enrichment or {}
        enrichment_state = ""
        error_code = None
        if isinstance(status_blob, dict):
            enrichment_state = str(status_blob.get("state") or "").lower().strip()
            error_code = status_blob.get("error_code")

        if enrichment_state == "ready":
            return SpecialistEnrichmentResponse(
                section_id=section_id,
                status="ready",
                data=section.model_dump(),
            )

        if enrichment_state == "failed":
            return SpecialistEnrichmentResponse(
                section_id=section_id,
                status="failed",
                error_code=error_code,
            )

        if enrichment_state == "pending":
            return JSONResponse(
                status_code=202,
                content={"status": "pending", "section_id": section_id, "retry_after_ms": 1500},
            )

        # Backward compatibility for documents that predate local_expert_enrichment.
        ti = section.travel_intelligence or {}
        if not ti or not any(v for v in ti.values() if v):
            return JSONResponse(
                status_code=202,
                content={"status": "pending", "section_id": section_id, "retry_after_ms": 1500},
            )
        return SpecialistEnrichmentResponse(
            section_id=section_id,
            status="ready",
            data=section.model_dump(),
        )

    # For niche specialists: data is from the main LLM call (not Phase B)
    # Return section as-is — it's either fully populated or not
    return SpecialistEnrichmentResponse(
        section_id=section_id,
        status="ready",
        data=section.model_dump(),
    )


@app.patch("/api/document", response_model=PlanDocumentResponse)
@limiter.limit("60/minute")
async def patch_plan_document(
    request: Request,
    patch: PlanDocumentPatch,
    db: AsyncSession = async_db_dependency,
):
    """
    Apply a partial update to the plan document.
    Uses CRDT-style merge: additions win, deletions require explicit flags.
    """
    session_id = get_session_from_request(request)
    # get_or_create_session: the frontend may PATCH pill settings before the
    # first graph_plan call, which is the only other path that creates the
    # DB session row.  Without this, the PATCH returns 404 after a session
    # reset (DELETE /api/session) because the cookie exists but the row doesn't.
    session = await get_or_create_session(db, session_id)

    doc = await get_document(db, session=session)
    if not doc:
        # Create document for first-time PATCH (pill settings before first chat).
        # Frontend sends settings via PATCH before graph_plan creates the doc.
        doc = await get_or_create_document(db, session=session, updated_by="user")
        # Skip version check — frontend couldn't know version of a new doc
    else:
        # Last-writer-wins: single user per session, no real conflict.
        # Version drift happens when graph stream saves doc (incrementing version)
        # before the SSE event updates the frontend's stored version.
        if patch.version != doc.version:
            logger.info(
                f"[PATCH] Version drift (client={patch.version}, server={doc.version}), "
                f"reloading and applying"
            )
            doc = await get_document(db, session=session)
            if not doc:
                raise HTTPException(status_code=404, detail="Document not found")

    def _trip_inputs_patch_has_real_diff(existing_ti, patch_ti) -> bool:
        patch_fields = getattr(patch_ti, "model_fields_set", set())
        for field_name in patch_fields:
            patch_val = getattr(patch_ti, field_name, None)
            existing_val = getattr(existing_ti, field_name, None)
            if hasattr(patch_val, "model_dump") and hasattr(existing_val, "model_dump"):
                if patch_val.model_dump() != existing_val.model_dump():
                    return True
            elif patch_val != existing_val:
                return True
        return False

    has_non_trip_mutations = any(
        (
            patch.branches is not None,
            patch.remove_branch_ids is not None,
            patch.tiles is not None,
            patch.remove_tile_ids is not None,
            patch.selections is not None,
            patch.preferred_tile_ids is not None,
        )
    )

    # Universal diff guard: skip write if this PATCH is a pure no-op.
    if patch.trip_inputs is not None and not has_non_trip_mutations:
        doc_data = get_document_data(doc)
        if not _trip_inputs_patch_has_real_diff(doc_data.trip_inputs, patch.trip_inputs):
            patch_fields = sorted(getattr(patch.trip_inputs, "model_fields_set", set()))
            logger.debug(
                "[VERIFY][PATCH_DEDUPE] no-op skip fields=%s version=%s",
                patch_fields,
                doc.version,
            )
            logger.info("[PATCH] No-op: patch matches current doc, skipping write")
            return PlanDocumentResponse(
                version=doc.version,
                updated_by=doc.updated_by,
                document=doc_data,
                updated_at=doc.updated_at.isoformat(),
                changes_made=False,
            )

    # Apply the patch using CRDT merge
    updated_doc = await apply_user_patch(db, doc=doc, patch=patch)

    # Record a system message describing the user's field changes
    # so the LLM knows what the user modified via the UI
    if patch.trip_inputs is not None:
        changes: list[str] = []
        trip_patch = patch.trip_inputs
        # Check which fields were explicitly set in the patch
        fields_set = getattr(trip_patch, "model_fields_set", set())

        # For each field that was set, describe the change
        if "destination" in fields_set:
            dest = getattr(trip_patch, "destination", None)
            if dest:
                changes.append(f"set destination to '{dest}'")
            else:
                changes.append("cleared destination")
        if "origin" in fields_set:
            val = getattr(trip_patch, "origin", None)
            if val:
                changes.append(f"set origin to '{val}'")
            else:
                changes.append("cleared origin")
        if "start_date" in fields_set:
            val = getattr(trip_patch, "start_date", None)
            if val:
                changes.append(f"set start date to '{val}'")
            else:
                changes.append("cleared start date")
        if "end_date" in fields_set:
            val = getattr(trip_patch, "end_date", None)
            if val:
                changes.append(f"set end date to '{val}'")
            else:
                changes.append("cleared end date")
        if "adults" in fields_set:
            val = getattr(trip_patch, "adults", None)
            if val:
                changes.append(f"set adults to {val}")
            else:
                changes.append("cleared adults")
        if "children" in fields_set:
            val = getattr(trip_patch, "children", None)
            if val is not None:
                changes.append(f"set children to {val}")
            else:
                changes.append("cleared children")
        if "requires_assistance" in fields_set:
            val = getattr(trip_patch, "requires_assistance", None)
            if val:
                changes.append("enabled requires assistance")
            else:
                changes.append("disabled requires assistance")
        if "budget" in fields_set:
            val = getattr(trip_patch, "budget", None)
            if val:
                changes.append(f"set budget to ${val}")
            else:
                changes.append("cleared budget")
        if "activity_settings" in fields_set:
            val = getattr(trip_patch, "activity_settings", None)
            categories = getattr(val, "categories", None) if val else None
            if categories:
                changes.append(f"set activity categories to {categories}")
            elif val is not None:
                changes.append("cleared activity categories")

        if changes:
            changes_text = ", ".join(changes)
            system_msg = f"[User edited trip inputs via UI: {changes_text}]"

            # Get the latest trip context for this session
            latest_ctx = await get_latest_trip_context_for_session(db, session=session)

            await record_chat_message(
                db,
                session=session,
                trip_context=latest_ctx,
                role="system",
                content=system_msg,
                metadata={"ui_edit": True},
            )

    await db.commit()

    doc_data = get_document_data(updated_doc)

    return PlanDocumentResponse(
        version=updated_doc.version,
        updated_by=updated_doc.updated_by,
        document=doc_data,
        updated_at=updated_doc.updated_at.isoformat(),
        changes_made=True,
    )


@app.post("/api/document/tiles/{branch_id}", response_model=PlanDocumentResponse)
@limiter.limit("12/minute")
async def fetch_tiles_for_branch(
    request: Request,
    branch_id: str,
    db: AsyncSession = async_db_dependency,
):
    """
    Fetch tiles for a specific branch and add them to the document.
    Used when switching branches to load tiles on demand.
    """
    session_id = get_session_from_request(request)
    session = await get_session_by_token(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    doc = await get_document(db, session=session)
    if not doc:
        raise HTTPException(status_code=404, detail="No plan document for this session")

    doc_data = get_document_data(doc)

    # Find the branch in the document
    branch = next((b for b in doc_data.branches if b.id == branch_id), None)
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found in document")

    # Check which tile categories are missing
    has_stays = bool(branch.tiles.stays)
    has_flights = bool(branch.tiles.flights)
    has_activities = bool(branch.tiles.activities)
    has_all_tiles = has_stays and has_flights and has_activities

    _debug_info(
        "TILES",
        f"Branch {branch_id}: stays={len(branch.tiles.stays)}, "
        f"flights={len(branch.tiles.flights)}, activities={len(branch.tiles.activities)}",
    )
    _debug_info("TILES", f"has_all_tiles={has_all_tiles}")

    if has_all_tiles:
        # All categories present, return current document
        _debug_info("TILES", "All categories present, returning cached")
        return PlanDocumentResponse(
            version=doc.version,
            updated_by=doc.updated_by,
            document=doc_data,
            updated_at=doc.updated_at.isoformat(),
            changes_made=False,
        )

    # Determine which verticals to fetch (only missing ones)
    verticals_to_fetch = []
    if not has_stays:
        verticals_to_fetch.append("hotel")
    if not has_flights:
        verticals_to_fetch.append("flight")
    if not has_activities:
        verticals_to_fetch.append("activity")

    # Fetch tiles for this branch
    primary_dest = branch.destination
    ti = doc_data.trip_inputs

    _debug_info("TILES", f"Fetching missing verticals: {verticals_to_fetch}")
    _debug_info("TILES", f"origin: branch={branch.origin}, trip_inputs={ti.origin}")
    tiles_request = TilesSearchRequest(
        session_id=session_id,
        destination=primary_dest,
        destination_hint=primary_dest,
        # Fall back to trip_inputs for missing branch fields (needed for flights)
        origin=branch.origin or ti.origin,
        start_date=branch.start_date or ti.start_date,
        end_date=branch.end_date or ti.end_date,
        adults=branch.adults or ti.adults,
        children=branch.children or ti.children,
        requires_assistance=branch.requires_assistance or ti.requires_assistance,
        verticals=verticals_to_fetch,  # Only fetch missing categories
        # Pass user preference settings for filtering
        flight_settings=ti.flight_settings,
        hotel_settings=ti.hotel_settings,
        activity_settings=ti.activity_settings,
    )

    with spend_guard_scope(session_id):
        tiles_response = search_tiles(tiles_request)

    _debug_info("TILES", f"search_tiles returned {len(tiles_response.tiles)} tiles")
    for t in tiles_response.tiles:
        _debug_info("TILES", f"  - {t.type}: {t.title}")

    if tiles_response.tiles:
        # Add tiles to the document
        updated_doc = await add_tiles_to_branch(
            db,
            doc=doc,
            branch_id=branch_id,
            tiles=tiles_response.tiles,
            updated_by="planner",
        )
        await db.commit()

        doc_data = get_document_data(updated_doc)

        return PlanDocumentResponse(
            version=updated_doc.version,
            updated_by=updated_doc.updated_by,
            document=doc_data,
            updated_at=updated_doc.updated_at.isoformat(),
            changes_made=True,
        )

    # No tiles found, return current document
    return PlanDocumentResponse(
        version=doc.version,
        updated_by=doc.updated_by,
        document=doc_data,
        updated_at=doc.updated_at.isoformat(),
        changes_made=False,
    )


@app.post("/api/tiles/refresh", response_model=TileRefreshResponse)
@limiter.limit("6/minute")
async def refresh_tiles(
    request: Request,
    body: TileRefreshRequest,
    db: AsyncSession = async_db_dependency,
):
    """
    Force refresh tiles for a branch with current settings.

    Use this endpoint when user preferences (hotel_settings, flight_settings,
    activity_settings) change to get updated tiles reflecting the new filters.

    The cache key includes settings hashes, so changing settings will trigger
    a cache miss and fresh fetch.
    """
    session_id = get_session_from_request(request)
    session = await get_session_by_token(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    doc = await get_document(db, session=session)
    if not doc:
        raise HTTPException(status_code=404, detail="No plan document for this session")

    doc_data = get_document_data(doc)

    # Find the branch in the document
    branch = next((b for b in doc_data.branches if b.id == body.branch_id), None)
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found in document")

    # Determine which verticals to refresh
    verticals = body.verticals or ["hotel", "flight", "activity"]

    # Get current settings from trip_inputs
    ti = doc_data.trip_inputs
    primary_dest = branch.destination

    # Build request with current settings
    tiles_request = TilesSearchRequest(
        session_id=session_id,
        destination=primary_dest,
        destination_hint=primary_dest,
        # Fall back to trip_inputs for missing branch fields (needed for flights)
        origin=branch.origin or ti.origin,
        start_date=branch.start_date or ti.start_date,
        end_date=branch.end_date or ti.end_date,
        adults=branch.adults or ti.adults,
        children=branch.children or ti.children,
        requires_assistance=branch.requires_assistance or ti.requires_assistance,
        verticals=verticals,  # type: ignore
        # Pass current settings - cache key includes settings hash
        # so changed settings will cause cache miss and fresh fetch
        flight_settings=ti.flight_settings,
        hotel_settings=ti.hotel_settings,
        activity_settings=ti.activity_settings,
    )

    # Fetch fresh tiles (cache will miss due to changed settings hash)
    with spend_guard_scope(session_id):
        tiles_response = search_tiles(tiles_request)

    # Update document with new tiles
    if tiles_response.tiles:
        await add_tiles_to_branch(
            db,
            doc=doc,
            branch_id=body.branch_id,
            tiles=tiles_response.tiles,
            updated_by="planner",
        )
        await db.commit()

    return TileRefreshResponse(
        tiles=tiles_response.tiles,
        refreshed_at=datetime.utcnow().isoformat(),
        verticals_refreshed=verticals,
    )


# =============================================================================
# Fill Day Endpoint (Stage 12B)
# =============================================================================


class FillDayRequest(BaseModel):
    """Request to fill a free day with activity tiles."""

    day_number: int
    categories: List[str] | None = None
    pinned_tile_ids: List[str] | None = None  # Place existing tiles instead of generating


@app.post("/api/document/fill-day")
@limiter.limit("8/minute")
async def fill_day_endpoint(
    request: Request,
    body: FillDayRequest,
    db: AsyncSession = async_db_dependency,
):
    """Fill a free day with activity tiles. No LangGraph execution."""
    session_id = get_session_from_request(request)
    session_key = f"session:{session_id}"
    await _wait_for_session_stream_idle(session_key)
    session = await get_session_by_token(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    doc = await get_document(db, session=session)
    if not doc:
        raise HTTPException(status_code=404, detail="No plan document")

    doc_data = get_document_data(doc)
    ti = doc_data.trip_inputs

    destination = ti.destination
    if not destination:
        raise HTTPException(status_code=400, detail="No destination set")

    async def _enrich_generated_tiles_with_places(
        generated_tiles: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Best-effort Places enrichment for fill-day generated activities."""
        if not generated_tiles or not settings.google_maps_api_key:
            return generated_tiles
        try:
            from app.tile_service.google_places_provider import enrich_activities_with_places

            async def _run_enrichment() -> list[dict[str, Any]]:
                with spend_guard_scope(session_id):
                    result = await enrich_activities_with_places(
                        generated_tiles,
                        destination=destination,
                        path_label="fill_day",
                    )
                return result or generated_tiles

            # Keep fill-day UX responsive: never block day-card return on slow Places calls.
            enriched = await asyncio.wait_for(_run_enrichment(), timeout=1.5)
            return enriched or generated_tiles
        except asyncio.TimeoutError:
            logger.warning("[FILL-DAY] Places enrichment timed out; using original tiles")
            return generated_tiles
        except Exception as exc:
            logger.warning("[FILL-DAY] Places enrichment failed; using original tiles: %s", exc)
            return generated_tiles

    # Find target day card
    day_card_idx = next(
        (i for i, dc in enumerate(doc_data.day_cards) if dc.day_number == body.day_number),
        None,
    )
    if day_card_idx is None:
        raise HTTPException(status_code=404, detail=f"Day {body.day_number} not found")

    day_card = doc_data.day_cards[day_card_idx]

    # Check day is actually free (no non-buffer, non-placeholder blocks)
    real_blocks = [b for b in day_card.blocks if not b.is_buffer and b.activity_type != "free_day"]
    logger.debug(
        f"[FILL-DAY] day={body.day_number} doc_version={doc.version} "
        f"real_blocks={len(real_blocks)} block_types={[b.activity_type for b in day_card.blocks]}"
    )
    if real_blocks:
        logger.warning(
            f"[FILL-DAY] 409 rejected: day={body.day_number} "
            f"real_blocks={[(b.activity_type, b.id) for b in real_blocks]}"
        )
        raise HTTPException(status_code=409, detail=f"Day {body.day_number} already has activities")

    # Determine categories — separate Tier 1 (specialist) from Tier 2 (experience gen).
    # Tier 1 categories (diving, hiking, etc.) are handled by specialists with constraints
    # and proper metadata. The experience generator produces mediocre content for these.
    from app.planner.specialist_registry import (
        SPECIALIST_REGISTRY,
        TIER1_SPECIALIST_NAMES,
        validate_fill_day_placement,
    )

    raw_categories = (
        body.categories or (ti.activity_settings.categories if ti.activity_settings else []) or None
    )
    tier1_requested = []
    tier2_categories = None
    if raw_categories:
        tier1_requested = [c for c in raw_categories if c.lower() in TIER1_SPECIALIST_NAMES]
        tier2_only = [c for c in raw_categories if c.lower() not in TIER1_SPECIALIST_NAMES]
        tier2_categories = tier2_only or None
    categories = tier2_categories  # experience generator only gets Tier 2

    # ── Registry-driven constraint validation (replaces hardcoded adjacent filter) ──
    from datetime import datetime as _dt

    # Derive effective total days from BOTH trip inputs and itinerary cards.
    # This avoids stale no-fly rejections when one source lags the other.
    trip_span_days = 0
    has_end_date = False
    if ti.start_date and ti.end_date:
        try:
            d0 = _dt.fromisoformat(ti.start_date)
            d1 = _dt.fromisoformat(ti.end_date)
            trip_span_days = max(0, (d1 - d0).days + 1)
            has_end_date = True
        except ValueError:
            trip_span_days = 0

    cards_span_days = 0
    sorted_cards = sorted(doc_data.day_cards, key=lambda dc: dc.day_number)
    if sorted_cards:
        first_date = sorted_cards[0].date
        last_date = sorted_cards[-1].date
        if first_date and last_date:
            try:
                cd0 = _dt.fromisoformat(first_date)
                cd1 = _dt.fromisoformat(last_date)
                cards_span_days = max(0, (cd1 - cd0).days + 1)
            except ValueError:
                cards_span_days = 0
        # Fallback when card dates are absent/invalid: use max day_number span.
        if cards_span_days == 0:
            cards_span_days = max((dc.day_number for dc in sorted_cards), default=0)

    effective_total_days = max(trip_span_days, cards_span_days)
    if effective_total_days == 0:
        effective_total_days = len(doc_data.day_cards)

    has_departure_buffer = any(
        b.buffer_type == "departure" for dc in doc_data.day_cards for b in dc.blocks
    )
    has_departure = has_departure_buffer or has_end_date
    logger.debug(
        "[FILL-DAY] effective_total_days=%d (trip_span=%d cards_span=%d) has_departure=%s",
        effective_total_days,
        trip_span_days,
        cards_span_days,
        has_departure,
    )

    # Gate Tier 1 placement: validate constraints before placing specialist tiles
    for t1_cat in tier1_requested:
        rejection = validate_fill_day_placement(
            target_day=body.day_number,
            specialist_type=t1_cat.lower(),
            day_cards=doc_data.day_cards,
            total_days=effective_total_days,
            has_departure_flight=has_departure,
        )
        if rejection:
            logger.info(
                "[FILL-DAY] Constraint rejected: day=%d specialist=%s code=%s",
                body.day_number,
                t1_cat,
                rejection.code,
            )
            return {
                "day_number": body.day_number,
                "tiles_added": 0,
                "rejected": True,
                "rejection_reason": rejection.reason,
                "rejection_code": rejection.code,
                "rejection_suggestion": rejection.suggestion,
                "version": doc.version,
            }

    # Also validate pinned tiles that carry a Tier 1 specialist_type
    if body.pinned_tile_ids:
        for tid in body.pinned_tile_ids:
            tile_model = doc_data.tiles.get(tid)
            if not tile_model:
                continue
            st = ((tile_model.meta or {}).get("specialist_type") or "").lower()
            if st and st in TIER1_SPECIALIST_NAMES:
                rejection = validate_fill_day_placement(
                    target_day=body.day_number,
                    specialist_type=st,
                    day_cards=doc_data.day_cards,
                    total_days=effective_total_days,
                    has_departure_flight=has_departure,
                )
                if rejection:
                    logger.info(
                        "[FILL-DAY] Pinned tile constraint rejected: day=%d tile=%s code=%s",
                        body.day_number,
                        tid,
                        rejection.code,
                    )
                    return {
                        "day_number": body.day_number,
                        "tiles_added": 0,
                        "rejected": True,
                        "rejection_reason": rejection.reason,
                        "rejection_code": rejection.code,
                        "rejection_suggestion": rejection.suggestion,
                        "version": doc.version,
                    }

    # Tier 2 exclusions from cross-domain blocks (registry-driven)
    excluded_categories: set[str] = set()

    # Check A: Buffer blocks on THIS day exclude their source specialist's cross-domain targets.
    # A rest_day buffer caused by diving should not generate hiking/climbing on the same day.
    target_day_card = next(
        (dc for dc in doc_data.day_cards if dc.day_number == body.day_number), None
    )
    if target_day_card:
        for block in target_day_card.blocks:
            if not block.is_buffer:
                continue
            buf_st = (block.specialist_type or "").lower()
            if buf_st:
                buf_cfg = SPECIALIST_REGISTRY.get(buf_st)
                if buf_cfg:
                    for xd in buf_cfg.cross_domain_blocks:
                        excluded_categories.update(xd.target_specialists)

    # Check B: Adjacent day cross-domain exclusions (original logic).
    adjacent_days = [dc for dc in doc_data.day_cards if abs(dc.day_number - body.day_number) == 1]
    for adj_day in adjacent_days:
        for block in adj_day.blocks:
            st = (block.specialist_type or "").lower()
            if not st:
                continue
            adj_config = SPECIALIST_REGISTRY.get(st)
            if not adj_config:
                continue
            for xd in adj_config.cross_domain_blocks:
                excluded_categories.update(xd.target_specialists)

    if excluded_categories:
        if categories:
            safe = [c for c in categories if c.lower() not in excluded_categories]
            categories = safe if safe else ["activities"]
        else:
            categories = ["activities"]
        logger.info(
            "fill_day: day %d excluded %s, using %s",
            body.day_number,
            excluded_categories,
            categories,
        )
    # ── End constraint validation ─────────────────────────────────────

    # ── Tier 1 specialist tile reuse: pick unplaced specialist activities ──
    # When user selected diving/hiking/etc., reuse activities already generated
    # by the specialist (have constraints, images, proper metadata) rather than
    # calling the generic experience generator which produces inferior content.
    # Round-robin: pick from the least-placed category to distribute evenly.
    specialist_tiles_for_day: list[dict] = []
    if tier1_requested:
        tier1_lower = {c.lower() for c in tier1_requested}
        # Collect placed activity_type values and per-category placement counts.
        # activity_type is the display title and the stable join key
        # against content_added[].title per the data contract.
        placed_titles: set[str] = set()
        placed_per_category: dict[str, int] = {}
        for dc in doc_data.day_cards:
            for block in dc.blocks:
                if block.activity_type:
                    placed_titles.add(block.activity_type)
                st = (block.specialist_type or "").lower()
                if st in tier1_lower:
                    placed_per_category[st] = placed_per_category.get(st, 0) + 1

        # Collect ALL unplaced candidates across matching sections
        candidates: list[tuple[str, dict]] = []  # (category, tile_dict)
        logger.debug(
            "[FILL-DAY] Reuse scan: tier1=%s sections=%d placed=%s",
            tier1_lower,
            len(doc_data.strategy_sections),
            placed_titles,
        )
        for section in doc_data.strategy_sections:
            s_type = (section.specialist_type or "").lower()
            if s_type not in tier1_lower:
                continue
            logger.debug(
                "[FILL-DAY] Section %s: %d content_added items",
                s_type,
                len(section.content_added),
            )
            for item in section.content_added:
                title = (item.get("title") or "").strip()
                if not title or title in placed_titles:
                    continue
                title_slug = title.lower().replace(" ", "_")[:20]
                candidates.append(
                    (
                        s_type,
                        {
                            "id": f"fill_{s_type}_{title_slug}_{body.day_number}",
                            "type": "activity",
                            "partner": "specialist",
                            "partner_product_id": f"specialist_{s_type}_{body.day_number}",
                            "deeplink_url": "",
                            "title": title,
                            "subtitle": item.get("subtitle", ""),
                            "image_url": item.get("image_url", ""),
                            "rating": item.get("rating"),
                            "user_ratings_count": item.get("user_ratings_count"),
                            "price_level": item.get("price_level"),
                            "google_place_id": item.get("google_place_id"),
                            "location_label": item.get("location_label"),
                            "deeplink": item.get("deeplink"),
                            "tags": [s_type],
                            "specialist_type": s_type,
                            "meta": {
                                "pinned_day": body.day_number,
                                "specialist_type": s_type,
                                "source": "fill_day_specialist_reuse",
                                "intensity": item.get("intensity"),
                                "duration_hours": item.get("duration_hours"),
                                "coordinates": item.get("coordinates"),
                            },
                            "source_agent": "vertical_specialist",
                        },
                    )
                )

        if candidates:
            # Pick from least-placed category (round-robin across specialists)
            candidates.sort(key=lambda x: placed_per_category.get(x[0], 0))
            specialist_tiles_for_day = [candidates[0][1]]

    # ── Priority chain: specialist reuse → pinned → experience generator ──
    if specialist_tiles_for_day:
        # Priority 1: Reuse unplaced specialist activities (best quality)
        tiles = specialist_tiles_for_day
        logger.info(
            f"[FILL-DAY] Reusing specialist tile: {tiles[0]['title']} "
            f"(specialist={tiles[0].get('specialist_type')})"
        )
    elif body.pinned_tile_ids:
        # Priority 2: Place pinned tiles from browse drawer
        pinned_tiles = []
        for tid in body.pinned_tile_ids:
            tile_model = doc_data.tiles.get(tid)
            if tile_model:
                td = tile_model.model_dump()
                td.setdefault("meta", {})["pinned_day"] = body.day_number
                pinned_tiles.append(td)
        if not pinned_tiles:
            raise HTTPException(status_code=404, detail="No matching tiles found in document")
        tiles = pinned_tiles
    elif categories or not tier1_requested:
        # Priority 3: Experience generator for Tier 2 categories (or no categories)
        date_str = day_card.date or ti.start_date
        month = date_str[:7] if date_str and len(date_str) >= 7 else "unknown"

        from app.services.experience_generator import generate_experience_tiles_for_day

        budget_int = int(ti.budget) if ti.budget else None
        with spend_guard_scope(session_id):
            tiles = await generate_experience_tiles_for_day(
                destination=destination,
                categories=categories,
                month=month,
                day_number=body.day_number,
                budget=budget_int,
                tiles_per_day=1,
            )

        # Tag fill-day tiles so the builder won't redistribute them
        for tile in tiles:
            tile.setdefault("meta", {})["pinned_day"] = body.day_number

        # Cross-day deduplication: filter tiles whose titles are already placed on other days.
        # Without this, cached experience tiles (same destination/category/month) would appear
        # identically on every free day the user fills.
        if tiles:
            placed_titles_elsewhere: set[str] = {
                (b.activity_type or "").lower().strip()
                for dc in doc_data.day_cards
                for b in dc.blocks
                if dc.day_number != body.day_number
                and b.activity_type
                and b.activity_type not in ("free_day", "placeholder", "arrival", "departure")
            }
            deduped = [
                t
                for t in tiles
                if (t.get("title") or "").lower().strip() not in placed_titles_elsewhere
            ]
            if deduped:  # Only apply dedup when at least one tile survives
                tiles = deduped

        tiles = await _enrich_generated_tiles_with_places(tiles)

        if not tiles:
            return {
                "day_number": body.day_number,
                "tiles_added": 0,
                "version": doc.version,
                "excluded_categories": sorted(excluded_categories),
            }
    else:
        # All Tier 1 specialist tiles already placed — fall back to experience generator
        # so free days on specialist trips still get activities (cultural, food, etc.)
        # rather than staying empty and confusing the user.
        logger.info(
            "[FILL-DAY] All specialist tiles for %s placed, falling back to experience generator "
            "for day %d",
            tier1_requested,
            body.day_number,
        )
        date_str = day_card.date or ti.start_date
        month = date_str[:7] if date_str and len(date_str) >= 7 else "unknown"

        from app.services.experience_generator import generate_experience_tiles_for_day

        budget_int = int(ti.budget) if ti.budget else None
        with spend_guard_scope(session_id):
            tiles = await generate_experience_tiles_for_day(
                destination=destination,
                categories=None,  # day_number rotation picks the category
                month=month,
                day_number=body.day_number,
                budget=budget_int,
                tiles_per_day=1,
            )

        for tile in tiles:
            tile.setdefault("meta", {})["pinned_day"] = body.day_number

        tiles = await _enrich_generated_tiles_with_places(tiles)

        if not tiles:
            return {
                "day_number": body.day_number,
                "tiles_added": 0,
                "version": doc.version,
                "excluded_categories": sorted(excluded_categories),
            }

    # Convert tiles to rich DayBlocks
    _VALID_PERIODS = {"morning", "afternoon", "evening"}
    period_cycle = ["morning", "afternoon", "evening"]
    fallback_coordinates = _first_trip_anchor_coordinates(doc_data)
    new_blocks = []
    for i, tile in enumerate(tiles[:3]):
        meta = tile.get("meta", {})
        block_coordinates = _extract_day_block_coordinates(tile, meta) or fallback_coordinates
        # Format duration: 2.0 -> "2 hours", 1.5 -> "1.5 hours"
        raw_hrs = meta.get("duration_hours")
        duration_str = None
        if raw_hrs:
            hrs = float(raw_hrs)
            duration_str = (
                f"{int(hrs)} hour{'s' if int(hrs) != 1 else ''}"
                if hrs == int(hrs)
                else f"{hrs} hours"
            )
        # Use tile's time_of_day when valid, fallback to round-robin
        time_of_day = meta.get("time_of_day", "").lower()
        period = time_of_day if time_of_day in _VALID_PERIODS else period_cycle[i % 3]

        # Resolve specialist_type: tile-level (specialist reuse) → requested
        # Tier 1 category → meta.category → fallback "experience"
        tile_specialist = (tile.get("specialist_type") or meta.get("specialist_type") or "").lower()
        if not tile_specialist or tile_specialist == "experience":
            for cat in tier1_requested:
                if cat.lower() in TIER1_SPECIALIST_NAMES:
                    tile_specialist = cat.lower()
                    break
        if not tile_specialist:
            tile_specialist = meta.get("category", "experience")
        # Only show specialist badge for Tier 1 specialists (diving, hiking, etc.).
        # Tier 2 / generic experience tiles (cultural, food, etc.) should not show a badge.
        if tile_specialist and tile_specialist not in TIER1_SPECIALIST_NAMES:
            tile_specialist = ""
        block_constraints = _resolve_fill_day_block_constraints(tile_specialist, meta)

        new_blocks.append(
            DayBlock(
                id=tile["id"],
                period=period,
                activity_type=tile.get("title", "Experience"),
                intensity="moderate",
                summary=tile.get("title", "Experience"),
                specialist_type=tile_specialist,
                constraints=block_constraints,
                image_url=tile.get("image_url"),
                duration=duration_str,
                coordinates=block_coordinates,
                booked_tile=tile,
                booking_category="activity",
                rating=tile.get("rating"),
                review_count=tile.get("user_ratings_count") or tile.get("review_count"),
                price_level=(
                    tile.get("price_level") or _price_estimate_to_level(tile.get("price_estimate"))
                ),
                google_place_id=tile.get("google_place_id"),
                deeplink=tile.get("deeplink"),
            )
        )

    # Add generated tiles to document tile map (enables hearting/referencing)
    for tile in tiles[:3]:
        tile_id = tile["id"]
        doc_data.tiles[tile_id] = Tile(**{k: v for k, v in tile.items() if k in Tile.model_fields})

    # Persist tiles for rebuild survival — tagged by source and priority
    for tile in tiles[:3]:
        td = {**tile}
        td["source_agent"] = "experience_generator"
        td.setdefault("meta", {})["pinned_day"] = body.day_number
        is_browse_add = bool(body.pinned_tile_ids)
        doc_data.user_pinned_tiles[td["id"]] = {
            "tile": td,
            "source": "browse_add" if is_browse_add else "auto_fill",
            "priority": "high" if is_browse_add else "low",
            "category": (td.get("meta") or {}).get("category", "activities"),
            "preferred_day": body.day_number,
        }

    # Preserve buffer blocks, append new activity blocks
    buffer_blocks = [b for b in day_card.blocks if b.is_buffer]
    day_card.blocks = buffer_blocks + new_blocks

    # Category-aware label (same pattern as itinerary_builder._handle_empty_days)
    unique_cats = list(
        dict.fromkeys(
            tile.get("meta", {}).get("category", "")
            for tile in tiles[:3]
            if tile.get("meta", {}).get("category") not in (None, "", "activities")
        )
    )
    if unique_cats:
        day_card.label = " & ".join(c.title() for c in unique_cats) + " Day"
    else:
        day_card.label = f"Day {body.day_number} — Exploration"

    doc_data.day_cards[day_card_idx] = day_card

    # Save
    from app.crud_document import save_document_data

    updated_doc = await save_document_data(db, doc=doc, data=doc_data, updated_by="planner")
    await db.commit()

    return {
        "day_number": body.day_number,
        "tiles_added": len(new_blocks),
        "day_card": day_card.model_dump(),
        "tiles": {tile["id"]: tile for tile in tiles[:3]},
        "version": updated_doc.version,
        "excluded_categories": sorted(excluded_categories),
    }


# =============================================================================
# Arrangement Validation / Apply Endpoints (Stage 13A)
# =============================================================================


@app.post("/api/document/validate-arrangement")
@limiter.limit("60/minute")
async def validate_arrangement(
    request: Request,
    body: ArrangementValidateRequest,
    db: AsyncSession = async_db_dependency,
) -> ArrangementResult:
    """
    Pure Python constraint check on proposed block moves.
    Target: <50ms. No LLM, no graph execution.
    """
    from app.planner.nodes.constraint_guard import validate_block_arrangement

    session_id = get_session_from_request(request)
    session = await get_session_by_token(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    doc = await get_document(db, session=session)
    if not doc:
        raise HTTPException(status_code=404, detail="No plan document")

    doc_data = get_document_data(doc)
    day_cards = [dc.model_dump() for dc in doc_data.day_cards]

    if not day_cards:
        raise HTTPException(status_code=400, detail="No itinerary to rearrange")

    moves = [m.model_dump() for m in body.moves]
    violations = validate_block_arrangement(day_cards, moves, doc_data.trip_inputs)

    return ArrangementResult(
        valid=len([v for v in violations if v["severity"] == "blocking"]) == 0,
        violations=[BlockViolation(**v) for v in violations],
    )


@app.post("/api/document/apply-arrangement")
@limiter.limit("30/minute")
async def apply_arrangement(
    request: Request,
    body: ArrangementApplyRequest,
    db: AsyncSession = async_db_dependency,
) -> ArrangementResult:
    """
    Validate + persist block moves. Uses optimistic concurrency.
    """
    from app.crud_document import save_document_data
    from app.planner.nodes.constraint_guard import (
        _apply_moves_to_cards,
        validate_block_arrangement,
    )

    session_id = get_session_from_request(request)
    session_key = f"session:{session_id}"
    await _wait_for_session_stream_idle(session_key)

    session = await get_session_by_token(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    doc = await get_document(db, session=session)
    if not doc:
        raise HTTPException(status_code=404, detail="No plan document")

    if doc.version != body.expected_version:
        raise HTTPException(status_code=409, detail="Version conflict — reload and retry")

    doc_data = get_document_data(doc)
    day_cards = [dc.model_dump() for dc in doc_data.day_cards]
    moves = [m.model_dump() for m in body.moves]

    # Validate first
    violations = validate_block_arrangement(day_cards, moves, doc_data.trip_inputs)
    blocking = [v for v in violations if v["severity"] == "blocking"]
    if blocking:
        return ArrangementResult(
            valid=False,
            violations=[BlockViolation(**v) for v in violations],
        )

    # Apply moves
    rearranged = _apply_moves_to_cards(day_cards, moves)

    # Recompute position-dependent constraints and detect stale buffers
    from app.services.itinerary_builder import recompute_constraints_after_arrangement

    rearranged, buffer_violations = recompute_constraints_after_arrangement(
        rearranged, doc_data.trip_inputs
    )

    # Persist
    doc_data.day_cards = [DayCard(**dc) for dc in rearranged]
    saved = await save_document_data(db, doc=doc, data=doc_data, updated_by="user")
    await db.commit()

    warnings = [v for v in violations if v["severity"] != "blocking"] + buffer_violations
    return ArrangementResult(
        valid=True,
        violations=[BlockViolation(**v) for v in warnings],
        day_cards=[dc.model_dump() for dc in doc_data.day_cards],
        version=saved.version,
    )


# =============================================================================
# Remove Block Endpoint (Stage 13)
# =============================================================================


@app.post("/api/document/remove-block")
@limiter.limit("30/minute")
async def remove_block(
    request: Request,
    body: RemoveBlockRequest,
    db: AsyncSession = async_db_dependency,
) -> RemoveBlockResponse:
    """
    Remove a single block from the itinerary. Pure Python, <10ms.
    No LLM, no constraint validation (removal can only relax constraints).
    """
    from app.crud_document import save_document_data

    session_id = get_session_from_request(request)
    session_key = f"session:{session_id}"
    await _wait_for_session_stream_idle(session_key)

    session = await get_session_by_token(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    doc = await get_document(db, session=session)
    if not doc:
        raise HTTPException(status_code=404, detail="No plan document")

    if doc.version != body.expected_version:
        raise HTTPException(status_code=409, detail="Version conflict — reload and retry")

    doc_data = get_document_data(doc)

    # Find the day card
    day_card = None
    day_idx = -1
    for i, dc in enumerate(doc_data.day_cards):
        if dc.day_number == body.day_number:
            day_card = dc
            day_idx = i
            break
    if day_card is None:
        raise HTTPException(status_code=404, detail=f"Day {body.day_number} not found")

    # Find the block
    block_idx = -1
    target_block = None
    for j, blk in enumerate(day_card.blocks):
        if blk.id == body.block_id:
            block_idx = j
            target_block = blk
            break
    if target_block is None:
        raise HTTPException(
            status_code=404,
            detail=f"Block {body.block_id} not found in day {body.day_number}",
        )

    # Check if block is removable
    LOCKED_ACTIVITY_TYPES = {"arrival", "departure", "check-in", "check-out"}
    if target_block.is_buffer:
        raise HTTPException(status_code=400, detail="Buffer blocks cannot be removed")
    if target_block.activity_type in LOCKED_ACTIVITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"'{target_block.activity_type}' blocks cannot be removed",
        )

    # Remove block
    day_card.blocks.pop(block_idx)

    # If day now has no activity blocks, insert free_day placeholder
    has_activities = any(
        not b.is_buffer and b.activity_type not in LOCKED_ACTIVITY_TYPES for b in day_card.blocks
    )
    if not has_activities:
        day_card.blocks = [
            b for b in day_card.blocks if b.is_buffer or b.activity_type in LOCKED_ACTIVITY_TYPES
        ] + [
            DayBlock(
                id=f"free_day_{body.day_number}",
                period="morning",
                activity_type="free_day",
                summary="Free day — tap to fill",
            )
        ]
        day_card.label = "Free Day"

    # Clean user_pinned_tiles if the removed block had a pinned tile
    if target_block.booked_tile and isinstance(target_block.booked_tile, dict):
        tile_id = target_block.booked_tile.get("id")
        if tile_id and tile_id in doc_data.user_pinned_tiles:
            del doc_data.user_pinned_tiles[tile_id]

    # Persist
    doc_data.day_cards[day_idx] = day_card
    saved = await save_document_data(db, doc=doc, data=doc_data, updated_by="user")
    await db.commit()

    return RemoveBlockResponse(
        day_number=body.day_number,
        day_card=day_card.model_dump(),
        version=saved.version,
        removed_block_id=body.block_id,
    )


# =============================================================================
# Insert Activity Block Endpoint (Browse Activities Sheet)
# =============================================================================


def _canonical_poi_type_for_block(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    key = raw.strip().lower().replace(" ", "_")
    if not key:
        return None
    mapped = _POI_TYPE_ALIASES.get(key)
    if mapped:
        return mapped
    if any(token in key for token in ("culture", "cultural", "heritage")):
        return "cultural"
    if any(
        token in key
        for token in (
            "museum",
            "landmark",
            "historic",
            "monument",
            "plaza",
            "fountain",
            "mosque",
            "synagogue",
        )
    ):
        return "cultural"
    if any(token in key for token in ("temple", "church", "worship")):
        return "temples"
    if any(token in key for token in ("restaurant", "cafe", "bar", "bakery", "food", "meal")):
        return "food"
    if any(token in key for token in ("park", "garden", "nature", "zoo", "camp")):
        return "nature"
    if any(token in key for token in ("shop", "store", "market", "mall")):
        return "shopping"
    if any(token in key for token in ("spa", "wellness", "gym", "beauty")):
        return "spa"
    if any(token in key for token in ("tour", "point_of_interest", "visitor", "travel_agency")):
        return "tours"
    return None


@app.post("/api/document/insert-activity-block")
@limiter.limit("30/minute")
async def insert_activity_block(
    request: Request,
    body: InsertActivityBlockRequest,
    db: AsyncSession = async_db_dependency,
) -> InsertActivityBlockResponse:
    """
    Insert an activity tile as a new block into a day card.
    Pure Python, <10ms. No LLM, no constraint validation.
    Used by Browse Activities sheet when user taps a tile.
    """
    from app.crud_document import save_document_data

    session_id = get_session_from_request(request)
    session_key = f"session:{session_id}"
    await _wait_for_session_stream_idle(session_key)

    session = await get_session_by_token(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    doc = await get_document(db, session=session)
    if not doc:
        raise HTTPException(status_code=404, detail="No plan document")

    doc_data = get_document_data(doc)
    day_cards = doc_data.day_cards or []

    # Find target day card
    day_card = None
    day_idx = -1
    for i, dc in enumerate(day_cards):
        if dc.day_number == body.day_number:
            day_card = dc
            day_idx = i
            break
    if day_card is None:
        raise HTTPException(status_code=404, detail=f"Day {body.day_number} not found")

    tile = body.tile
    block_id = f"browse_activity_{tile.get('id', 'unknown')}_{body.day_number}"

    # Map geo → coordinates dict (DayBlock.coordinates is {lat, lng})
    geo = tile.get("geo")
    coordinates: dict[str, float] | None = None
    if isinstance(geo, dict):
        lat = geo.get("lat")
        lng = geo.get("lng")
        if lat is not None and lng is not None:
            coordinates = {"lat": lat, "lng": lng}
    elif isinstance(geo, list) and len(geo) == 2:
        # [lng, lat] convention throughout pipeline
        coordinates = {"lat": geo[1], "lng": geo[0]}

    # Build new block from tile data.
    # activity_type is intentionally empty so the renderer falls through to summary
    # (the place name). Setting it to the category word ("shopping") would show
    # "Shopping" as the heading instead of the actual venue name.
    # Build tile dict with pinned_day meta for rebuild survival.
    # Deep-copy meta to avoid mutating the original body.tile dict.
    tile_with_meta = {
        **tile,
        "id": tile.get("id") or block_id,
        "meta": {**(tile.get("meta") or {}), "pinned_day": body.day_number, "source": "browse_add"},
    }
    map_type = (
        _canonical_poi_type_for_block(tile.get("browse_category"))
        or _canonical_poi_type_for_block(tile.get("category"))
        or _canonical_poi_type_for_block((tile.get("meta") or {}).get("category"))
    )

    new_block = DayBlock(
        id=block_id,
        period="morning",
        activity_type="",
        summary=tile.get("title", "Activity"),
        image_url=tile.get("image_url"),
        duration=tile.get("duration"),
        rating=tile.get("rating"),
        review_count=tile.get("review_count"),
        price_level=tile.get("price_level") or (tile.get("meta") or {}).get("price_level"),
        coordinates=coordinates,
        intensity=None,
        is_buffer=False,
        specialist_type=tile.get("browse_category") or tile.get("category") or None,
        map_type=map_type,
        activity_domain="tier2",
        activity_provenance="user_browse_added",
        booked_tile=tile_with_meta,
        constraints=[],
        preference_status="user_preferred",
    )

    # Pin browse tile so itinerary builder re-places it on graph re-run.
    # Uses the same user_pinned_tiles mechanism as fill-day Browse→Add.
    browse_tile_id = tile.get("id") or block_id
    # Write into doc_data.tiles so the builder can look up the tile in Phase 5.25
    try:
        doc_data.tiles[browse_tile_id] = Tile(
            **{k: v for k, v in tile_with_meta.items() if k in Tile.model_fields}
        )
    except Exception:
        pass  # Non-critical: builder will skip if tile doesn't validate
    doc_data.user_pinned_tiles[browse_tile_id] = {
        "tile": tile_with_meta,
        "source": "browse_add",
        "priority": "high",
        "category": tile.get("category", "activities"),
        "preferred_day": body.day_number,
    }

    # Append block, inserting before free_day placeholders if present and removing them
    free_day_idx = next(
        (i for i, b in enumerate(day_card.blocks) if b.activity_type == "free_day"),
        None,
    )
    if free_day_idx is not None:
        day_card.blocks.insert(free_day_idx, new_block)
        # Remove free_day placeholder now that the day has an activity
        day_card.blocks = [b for b in day_card.blocks if b.activity_type != "free_day"]
        day_card.label = "Activity Day"
    else:
        day_card.blocks.append(new_block)

    # Persist
    doc_data.day_cards[day_idx] = day_card
    saved = await save_document_data(db, doc=doc, data=doc_data, updated_by="user")
    await db.commit()

    return InsertActivityBlockResponse(
        day_number=body.day_number,
        day_card=day_card.model_dump(),
        version=saved.version,
        inserted_block_id=block_id,
    )


# =============================================================================
# Restore Snapshot Endpoint (Stage 18 — Undo Stack)
# =============================================================================


@app.post("/api/document/restore-snapshot")
@limiter.limit("20/minute")
async def restore_snapshot(
    request: Request,
    body: RestoreSnapshotRequest,
    db: AsyncSession = async_db_dependency,
) -> RestoreSnapshotResponse:
    """
    Restore day_cards to a previous snapshot. Pure Python, <10ms.
    Used by the frontend undo stack. No constraint validation — the snapshot
    was captured from a valid state immediately before the mutation.
    """
    from app.crud_document import save_document_data

    session_id = get_session_from_request(request)
    session_key = f"session:{session_id}"
    await _wait_for_session_stream_idle(session_key)

    session = await get_session_by_token(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    doc = await get_document(db, session=session)
    if not doc:
        raise HTTPException(status_code=404, detail="No plan document")

    if doc.version != body.expected_version:
        raise HTTPException(status_code=409, detail="Version conflict — plan was modified")

    doc_data = get_document_data(doc)
    doc_data.day_cards = [DayCard(**dc) for dc in body.day_cards]

    saved = await save_document_data(db, doc=doc, data=doc_data, updated_by="user")
    await db.commit()

    return RestoreSnapshotResponse(
        day_cards=[dc.model_dump() for dc in doc_data.day_cards],
        version=saved.version,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Activity Browser Endpoint
# ─────────────────────────────────────────────────────────────────────────────


@app.post("/api/activities/browse")
@limiter.limit("5/minute")
async def browse_activities_endpoint(
    request: Request,
    body: BrowseActivitiesRequest,
    db: AsyncSession = async_db_dependency,
):
    """
    On-demand activity search for free/buffer days.

    Priority order:
    1. Document's browseable_activities (Tier 1 suppressed tiles — free, already fetched)
    2. Google Places API (new fetch — ~$0.12/request, cached by dest+categories+month)

    Rate limited to 5 req/min per session to cap Places API spend.
    """
    from app.services.activity_browser import browse_activities

    session_id = get_session_from_request(request)
    session = await get_session_by_token(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Check document for stashed browseable_activities first (no API cost)
    doc = await get_document(db, session=session)
    if doc:
        doc_data = get_document_data(doc)
        stashed = doc_data.browseable_activities or []
        if stashed:
            signed_stashed = _attach_signed_photo_urls_to_browse_tiles(
                list(stashed),
                session_id=session_id,
            )
            return {"tiles": signed_stashed, "total": len(signed_stashed), "source": "stashed"}

    # Resolve center from hotel_location if provided
    center = None
    if body.hotel_location:
        lat = body.hotel_location.get("lat")
        lng = body.hotel_location.get("lng")
        if lat is not None and lng is not None:
            center = (float(lat), float(lng))

    with spend_guard_scope(session_id):
        tiles = await browse_activities(
            destination=body.destination,
            center=center,
            categories=body.categories,
            date=body.date,
        )
    signed_tiles = _attach_signed_photo_urls_to_browse_tiles(
        list(tiles),
        session_id=session_id,
    )
    return {"tiles": signed_tiles, "total": len(signed_tiles), "source": "places"}


# =============================================================================
# Expand Itinerary Endpoint (Stage 2 -> Stage 3)
# =============================================================================

from app.request_dedup import (  # noqa: E402
    acquire_expand_slot as _acquire_expand_slot,
)
from app.request_dedup import (  # noqa: E402
    check_idempotency as _check_idempotency,
)
from app.request_dedup import (  # noqa: E402
    release_expand_slot as _release_expand_slot,
)


@app.post("/api/expand-itinerary")
@limiter.limit("20/minute")  # Builder-only (no LLM) — frontend mutex prevents abuse
async def expand_itinerary_endpoint(
    request: Request,
    req: ExpandItineraryRequest,
):
    """
    Expand strategy into full itinerary (Stage 2 -> Stage 3).

    Streams NDJSON events:
        {"type": "progress", "stage": "itinerary", "message": "...", "pct": 30}
        {"type": "envelope", "plan_envelope": {...}}
        {"type": "done", "plan_view_state": "S3_ITINERARY_READY|S3_EDITING|S3_PARTIAL_CONFLICT"}
        {"type": "error", "message": "..."}

    NOTE: This endpoint does NOT use FastAPI's db dependency injection because
    StreamingResponse generators run AFTER the endpoint returns, at which point
    the injected session is closed. Instead, we create a fresh session inside
    the generator using the session factory.
    """
    client_request_id = request.headers.get("X-Client-Request-Id")
    client_attempt = request.headers.get("X-Client-Attempt")
    logger.info(
        "[expand-itinerary] rid=%s attempt=%s idempotency_key=%s",
        client_request_id,
        client_attempt,
        req.idempotency_key,
    )

    # DEBUG: Log received destination for diagnostics
    received_dest = req.trip_inputs.get("destination") if req.trip_inputs else "NO_TRIP_INPUTS"
    logger.info(f"[API expand-itinerary] Received destination: {received_dest}")

    # Check idempotency - return early if duplicate request
    if await _check_idempotency(req.idempotency_key):

        async def duplicate_response():
            event = ExpandItineraryStreamEvent(
                type="done",
                message="duplicate_noop",
            )
            yield json.dumps(event.model_dump(exclude_none=True)) + "\n"

        return StreamingResponse(
            duplicate_response(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Get session from request (must be before the mutex check)
    session_id = get_session_from_request(request)

    # Per-session expand mutex: reject if another expand is in-flight for this session
    if not await _acquire_expand_slot(session_id):
        return JSONResponse(
            status_code=429,
            content={"detail": "Itinerary expansion already in progress for this session"},
            headers={"Retry-After": "5"},
        )

    async def _ndjson_with_release():
        try:
            async for chunk in generate_ndjson(
                session_id=session_id,
                req=req,
                resolve_stage3_view_state=_resolve_stage3_view_state,
            ):
                yield chunk
        finally:
            await _release_expand_slot(session_id)

    return StreamingResponse(
        _ndjson_with_release(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    import uvicorn

    # Respect DEBUG mode for uvicorn logging (suppresses WatchFiles warnings in demo/off)
    log_level = "debug" if _debug_mode == "full" else "error"
    uvicorn.run(
        app,
        host=settings.backend_host,
        port=settings.backend_port,
        log_level=log_level,
    )
