import asyncio
import json
import logging
import math
import os
import secrets
import warnings
from datetime import datetime
from typing import Any, Dict, List

# =============================================================================
# EARLY WARNING SUPPRESSION (before any imports that might trigger warnings)
# =============================================================================
# Must happen before OpenAI/Pydantic imports to catch schema validation warnings
_debug_mode = os.getenv("DEBUG", "off").lower().strip()
if _debug_mode != "full":
    warnings.filterwarnings("ignore")
    logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)

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
from app.planner.nodes.router_category_sync import has_explicit_category_intent  # noqa: E402
from app.rate_limit import limiter as _shared_limiter  # noqa: E402
from app.schemas import (  # noqa: E402
    ChatHistoryResponse,
    ChatMessageResponse,
    DayBlock,
    DeleteLastMessageResponse,
    ExpandItineraryRequest,
    ExpandItineraryStreamEvent,
    GraphPlanRequest,
    PlanDocumentData,
    PlanDocumentPatch,
    PlanDocumentResponse,
    PlanViewState,
    Tile,
    TileRefreshRequest,
    TileRefreshResponse,
    TilesSearchRequest,
    TripInputValidationRequest,
    TripInputValidationResponse,
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
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Please slow down."},
        headers={"Retry-After": str(exc.detail)},
    )


app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# =============================================================================
# Admin Endpoint Gate
# =============================================================================


async def require_admin(request: Request) -> None:
    """FastAPI dependency: reject requests without valid X-Admin-Key header.

    In local/development/test environments, admin routes are open if ADMIN_API_KEY is unset.
    In production, ADMIN_API_KEY must be configured or all admin routes return 403.
    """
    key = settings.admin_api_key
    if not key:
        # No key configured — allow in dev, block in prod
        if settings.env not in ("local", "development", "test"):
            raise HTTPException(403, "Admin API key not configured")
        return
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
    if settings.env in ("local", "development", "test"):
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
    allow_headers=["Content-Type", "X-CSRF-Token"],  # Explicitly allow CSRF header
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
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    """Reject payloads exceeding MAX_BODY_BYTES before Pydantic parses them."""
    cl = request.headers.get("content-length")
    if cl and int(cl) > MAX_BODY_BYTES:
        return JSONResponse(status_code=413, content={"detail": "Payload too large"})
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


# =============================================================================
# Trip Input Validation Endpoint
# =============================================================================


@app.post("/api/validate-trip-input", response_model=TripInputValidationResponse)
@limiter.limit("15/minute")
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
        # Tier 11.1: Use async validation with non-blocking retries
        result = await validate_input_async(req.value, req.field_type, session_id=session_id)
        return TripInputValidationResponse(
            corrected_values=result.corrected_values,
            is_valid=result.is_valid,
            reason=result.reason,
        )
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
@limiter.limit("20/minute;120/hour")
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

    # --- Generate request ID and compute today_iso ---
    request_id = generate_request_id()
    today_iso = compute_today_iso()

    # --- Sanitize and prepare session state ---
    session_state = _prepare_graph_plan_session_state(req, today_iso=today_iso)

    # --- Get session from request for document persistence ---
    session_id = get_session_from_request(request)

    # --- SSE concurrent connection limit ---
    client_ip = request.client.host if request.client else "unknown"
    session_key = f"session:{session_id}"
    ip_key = f"ip:{client_ip}"

    limit_scope = await _try_acquire_sse_slot(session_key, ip_key)
    if limit_scope == "session":
        return JSONResponse(429, {"detail": "Too many concurrent streams for this session"})
    if limit_scope == "ip":
        return JSONResponse(429, {"detail": "Too many concurrent streams from this IP"})

    return StreamingResponse(
        generate_sse(
            session_id=session_id,
            req=req,
            session_state=session_state,
            request_id=request_id,
            today_iso=today_iso,
            session_key=session_key,
            ip_key=ip_key,
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
@limiter.limit("60/minute")
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
@limiter.limit("15/minute")
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
@limiter.limit("30/minute")
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
                candidates.append(
                    (
                        s_type,
                        {
                            "id": f"fill_{s_type}_{body.day_number}",
                            "type": "activity",
                            "partner": "specialist",
                            "partner_product_id": f"specialist_{s_type}_{body.day_number}",
                            "deeplink_url": "",
                            "title": title,
                            "subtitle": item.get("subtitle", ""),
                            "image_url": item.get("image_url", ""),
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

        if not tiles:
            return {"day_number": body.day_number, "tiles_added": 0, "version": doc.version}
    else:
        # Pure Tier 1 with all specialist tiles already placed — nothing to fill
        logger.info(f"[FILL-DAY] All specialist tiles for {tier1_requested} already placed")
        return {"day_number": body.day_number, "tiles_added": 0, "version": doc.version}

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
    }


# =============================================================================
# Expand Itinerary Endpoint (Stage 2 -> Stage 3)
# =============================================================================

from app.request_dedup import check_idempotency as _check_idempotency  # noqa: E402


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
    # DEBUG: Log received destination for diagnostics
    received_dest = req.trip_inputs.get("destination") if req.trip_inputs else "NO_TRIP_INPUTS"
    logger.info(f"[API expand-itinerary] Received destination: {received_dest}")

    # Check idempotency - return early if duplicate request
    if await _check_idempotency(req.idempotency_key):

        async def duplicate_response():
            event = ExpandItineraryStreamEvent(
                type="error", message="Duplicate request - itinerary generation already in progress"
            )
            yield json.dumps(event.model_dump(exclude_none=True)) + "\n"

        return StreamingResponse(
            duplicate_response(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Get session from request
    session_id = get_session_from_request(request)

    return StreamingResponse(
        generate_ndjson(
            session_id=session_id,
            req=req,
            resolve_stage3_view_state=_resolve_stage3_view_state,
        ),
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
