import asyncio
import json
import logging
import os
import secrets
import warnings
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass
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
from slowapi import Limiter  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402
from slowapi.util import get_remote_address  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.db_models as db_models  # noqa: E402
import app.schemas as schemas  # noqa: E402
from app.config import settings  # noqa: E402
from app.crud_document import (  # noqa: E402
    add_tiles_to_branch,
    apply_planner_update,
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
from app.db import _get_async_session_factory, get_async_db, get_db  # noqa: E402
from app.debug_utils import _debug, _debug_info, log_llm_output, log_user_input  # noqa: E402
from app.graph_plan_utils import (  # noqa: E402
    check_payload_size,
    compute_today_iso,
    ensure_thread_id,
    generate_request_id,
    is_valid_thread_id,
    normalize_trip_inputs,
    sanitize_session_state,
    truncate_assistant_message,
    validate_suggested_responses,
)
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
    TRACE_ENVELOPE,
    checkpoint_stats,
    clear_all_caches,
    clear_all_checkpoints,
    clear_response_caches,
    clear_session_checkpoint,
    condense_long_message,
    create_envelope,
    emit_anomaly_bundle,
    emit_request_end,
    emit_request_start,
    force_verbose_on_anomaly,
    get_graph_stats,
    get_planner_debug_info,
    prewarm_prompts,
    prune_stale_checkpoints,
    response_cache_stats,
    run_turn,
    run_turn_streaming,
    validate_template_coverage,
)
from app.schemas import (  # noqa: E402
    AckUpdate,
    BookingStatus,
    BookingStatusItem,
    ChatHistoryResponse,
    ChatMessageResponse,
    DayBlock,
    DayCard,
    DeleteLastMessageResponse,
    DestinationCard,
    EntityConfidenceInfo,
    ExpandItineraryRequest,
    ExpandItineraryStreamEvent,
    ExtractionConfidenceInfo,
    GraphPlanErrorCode,
    GraphPlanObservability,
    GraphPlanRequest,
    GraphPlanResponse,
    GraphPlanTokens,
    ItineraryAssumptions,
    ItineraryOverview,
    OpenDecision,
    PlanDocumentData,
    PlanDocumentPatch,
    PlanDocumentResponse,
    PlanViewState,
    ReadinessItem,
    RemoveSpecialistRequest,
    StrategySection,
    Tile,
    TileRefreshRequest,
    TileRefreshResponse,
    TilesSearchRequest,
    TripInputValidationRequest,
    TripInputValidationResponse,
)
from app.services.regen_strategy import (  # noqa: E402
    RegenStrategy,
    compute_field_hashes,
    compute_strategy,
    detect_changed_fields,
    get_strategy_description,
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
from app.tile_service.service import search_tiles  # noqa: E402
from app.validation import (  # noqa: E402
    cache_stats,
    clear_cache,
    prewarm_cache,
    validate_input_async,
)

# Configure logging for the graph plan route
logger = logging.getLogger(__name__)


# =============================================================================
# Plan View State Machine Helpers
# =============================================================================


def _has_missing_critical_fields(trip_inputs: dict) -> bool:
    """Check if critical fields are missing for Stage 2.

    For S2_STRATEGY_READY, we only require destination and start_date.
    end_date is optional for strategy display (user can refine later).
    """
    destination = trip_inputs.get("destination")
    start_date = trip_inputs.get("start_date")
    # end_date is NOT required for S2 - strategy can be shown without it
    return not destination or not start_date


@dataclass
class TripReadiness:
    """Simple trip readiness checker."""

    has_origin: bool
    has_destination: bool
    has_dates: bool
    core_complete: bool


def compute_trip_readiness(trip_inputs: Dict[str, Any], errors: List[Any] = None) -> TripReadiness:
    """Compute trip readiness from trip inputs."""
    destination = trip_inputs.get("destination")
    return TripReadiness(
        has_origin=bool(trip_inputs.get("origin")),
        has_destination=bool(destination),
        has_dates=bool(trip_inputs.get("start_date")),
        core_complete=bool(destination and trip_inputs.get("start_date")),
    )


def _check_stage3_gate(metadata: dict, trip_inputs: dict) -> bool:
    """Stage 3 hard gate - all must be true for S3_ITINERARY_READY."""
    open_decisions = metadata.get("open_decisions", [])
    blocking_count = sum(1 for d in open_decisions if d.get("is_blocking"))

    # Use bool() to ensure we return True/False, not the truthy/falsy value itself
    # (e.g., empty list [] should return False, not [])
    return bool(
        blocking_count == 0
        and trip_inputs.get("destination")
        and trip_inputs.get("start_date")
        and trip_inputs.get("end_date")
    )


def _compute_plan_view_state(metadata: dict, trip_inputs: dict) -> PlanViewState:
    """
    Compute the plan view state from session metadata and trip inputs.

    State machine states:
    - S0_BOOTSTRAP: No plan yet (or reset). Placeholders only.
    - S1_FRAMING: Stage 1 output available (shortlist/skeleton)
    - S2_STRATEGY_READY: All relevant Stage 2 strategy nodes complete
    - S2_BLOCKED: Stage 2 incomplete due to missing critical fields
    - S3_ITINERARY_READY: Itinerary generated (day cards)
    - S3_EDITING: User editing itinerary assumptions/constraints
    - S3_BLOCKED: Stage 3 requested but blocked (missing locks)
    """
    strategy_stage = metadata.get("strategy_stage")

    # S0: No strategy stage yet
    if strategy_stage is None or strategy_stage == 0:
        return "S0_BOOTSTRAP"

    # S1: Stage 1 complete (framing/shortlist)
    if strategy_stage == 1:
        return "S1_FRAMING"

    # S2: Strategy nodes running or complete
    if strategy_stage == 2:
        if _has_missing_critical_fields(trip_inputs):
            return "S2_BLOCKED"
        return "S2_STRATEGY_READY"

    # S3: Itinerary stage
    if strategy_stage == 3:
        if metadata.get("needs_refresh"):
            return "S3_EDITING"
        if not _check_stage3_gate(metadata, trip_inputs):
            return "S3_BLOCKED"
        return "S3_ITINERARY_READY"

    # Default fallback
    return "S0_BOOTSTRAP"


def _build_strategy_sections(metadata: dict) -> list:
    """Build StrategySection objects from metadata."""
    raw_sections = metadata.get("strategy_sections", [])
    sections = []
    for s in raw_sections:
        if isinstance(s, dict):
            sections.append(
                StrategySection(
                    id=s.get("id", ""),
                    title=s.get("title", ""),
                    subtitle=s.get("subtitle"),
                    specialist_type=s.get("specialist_type"),
                    # Feasibility fields for filtering infeasible specialists
                    feasibility_status=s.get("feasibility_status"),
                    feasibility_reason=s.get("feasibility_reason"),
                    alternative_suggestion=s.get("alternative_suggestion"),
                    one_liner=s.get("one_liner"),
                    principles=s.get("principles", [])[:4],
                    must_dos=s.get("must_dos", [])[:5],
                    optional_upgrades=s.get("optional_upgrades", [])[:3],
                    logistics_notes=s.get("logistics_notes", [])[:4],
                    tradeoffs_summary=s.get("tradeoffs_summary"),
                    strategy_node_id=s.get("strategy_node_id"),
                    strategy_version=s.get("strategy_version"),
                    booking_artifacts=s.get("booking_artifacts"),
                    impact_areas=s.get("impact_areas", []),
                    # Technical log data for System Log display
                    constraints_applied=s.get("constraints_applied", []),
                    content_added=s.get("content_added", []),
                    trip_summary=s.get("trip_summary"),
                    bullets=s.get("bullets", [])[:6],
                )
            )
    return sections


def _build_open_decisions(metadata: dict) -> list:
    """Build OpenDecision objects from metadata."""
    raw_decisions = metadata.get("open_decisions", [])
    decisions = []
    for d in raw_decisions:
        if isinstance(d, dict):
            decisions.append(
                OpenDecision(
                    id=d.get("id", ""),
                    statement=d.get("statement", ""),
                    related_field=d.get("related_field"),
                    is_blocking=d.get("is_blocking", False),
                )
            )
    return decisions[:4]  # Max 4 open decisions


def _build_itinerary_overview(metadata: dict) -> ItineraryOverview | None:
    """Build ItineraryOverview from metadata."""
    raw_overview = metadata.get("itinerary_overview")
    if not raw_overview or not isinstance(raw_overview, dict):
        return None
    return ItineraryOverview(
        duration_label=raw_overview.get("duration_label", ""),
        base_structure=raw_overview.get("base_structure", ""),
        activity_density=raw_overview.get("activity_density", ""),
    )


def _build_day_cards(metadata: dict) -> list:
    """Build DayCard objects from metadata."""
    raw_cards = metadata.get("day_cards", [])
    cards = []
    for c in raw_cards:
        if isinstance(c, dict):
            blocks = []
            for b in c.get("blocks", [])[:3]:  # Max 3 blocks per day
                if isinstance(b, dict):
                    blocks.append(
                        DayBlock(
                            period=b.get("period", "morning"),
                            activity_type=b.get("activity_type", ""),
                            intensity=b.get("intensity"),
                            summary=b.get("summary", ""),
                        )
                    )
            cards.append(
                DayCard(
                    day_number=c.get("day_number", 0),
                    date=c.get("date"),
                    label=c.get("label", ""),
                    blocks=blocks,
                )
            )
    return cards


def _build_itinerary_assumptions(metadata: dict) -> ItineraryAssumptions | None:
    """Build ItineraryAssumptions from metadata."""
    raw_assumptions = metadata.get("itinerary_assumptions")
    if not raw_assumptions or not isinstance(raw_assumptions, dict):
        return None
    return ItineraryAssumptions(
        assumptions=raw_assumptions.get("assumptions", [])[:4],  # Max 4
        flexible_elements=raw_assumptions.get("flexible_elements", [])[:3],  # Max 3
    )


def _get_trip_input_display_value(ui_key: str, trip_inputs: dict) -> str | None:
    """
    Get human-readable display value for a UI key from trip_inputs.

    Maps canonical UI keys to their corresponding trip_inputs values
    and formats them for display in collapsible message summaries.
    """
    # Map UI key to trip_inputs field(s)
    if ui_key == "destination":
        return trip_inputs.get("destination")
    elif ui_key == "origin":
        return trip_inputs.get("origin")
    elif ui_key == "dates":
        start = trip_inputs.get("start_date")
        end = trip_inputs.get("end_date")
        if start and end:
            return f"{start} – {end}"
        elif start:
            return start
        return None
    elif ui_key == "budget":
        budget = trip_inputs.get("budget")
        currency = trip_inputs.get("currency", "USD")
        return f"{currency} {budget}" if budget else None
    elif ui_key == "travelers":
        adults = trip_inputs.get("adults")
        children = trip_inputs.get("children", 0)
        if adults:
            parts = [f"{adults} adult{'s' if adults != 1 else ''}"]
            if children:
                parts.append(f"{children} child{'ren' if children != 1 else ''}")
            return ", ".join(parts)
        return None
    elif ui_key == "flights":
        if trip_inputs.get("booking_types", {}).get("flights"):
            settings = trip_inputs.get("flight_settings", {})
            parts = []
            if settings.get("direct_only"):
                parts.append("Direct")
            cabin = settings.get("cabin_class", "economy")
            if cabin != "economy":
                parts.append(cabin.title())
            return " · ".join(parts) if parts else "Enabled"
        return None
    elif ui_key == "hotels":
        if trip_inputs.get("booking_types", {}).get("hotels"):
            settings = trip_inputs.get("hotel_settings", {})
            stars = settings.get("min_stars", 0)
            return f"{stars}+ stars" if stars else "Enabled"
        return None
    # =========================================================================
    # Settings keys (dotted notation from NL command extraction)
    # =========================================================================
    elif ui_key == "booking_types.flights":
        toggle = trip_inputs.get("booking_types", {}).get("flights")
        return {"off": "Disabled", "suggested": "Auto", "on": "Enabled"}.get(toggle)
    elif ui_key == "booking_types.hotels":
        toggle = trip_inputs.get("booking_types", {}).get("hotels")
        return {"off": "Disabled", "suggested": "Auto", "on": "Enabled"}.get(toggle)
    elif ui_key == "booking_types.activities":
        toggle = trip_inputs.get("booking_types", {}).get("activities")
        return {"off": "Disabled", "suggested": "Auto", "on": "Enabled"}.get(toggle)
    elif ui_key == "booking_types.ground_transport":
        toggle = trip_inputs.get("booking_types", {}).get("ground_transport")
        return {"off": "Disabled", "suggested": "Auto", "on": "Enabled"}.get(toggle)
    elif ui_key == "flight_settings.direct_only":
        direct = trip_inputs.get("flight_settings", {}).get("direct_only")
        return "Direct flights only" if direct else "Connections OK"
    elif ui_key == "flight_settings.cabin_class":
        cabin = trip_inputs.get("flight_settings", {}).get("cabin_class")
        return cabin.replace("_", " ").title() if cabin else None
    elif ui_key == "flight_settings.round_trip":
        round_trip = trip_inputs.get("flight_settings", {}).get("round_trip")
        return "Round trip" if round_trip else "One way"
    elif ui_key == "hotel_settings.min_stars":
        stars = trip_inputs.get("hotel_settings", {}).get("min_stars")
        if stars is not None:
            return f"{stars}+ stars" if stars > 0 else "Any rating"
        return None
    elif ui_key == "activity_settings.skill_level":
        level = trip_inputs.get("activity_settings", {}).get("skill_level")
        return level.title() if level else None
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan hooks.

    Used instead of deprecated @app.on_event handlers.
    Pre-warms caches and compiles templates to eliminate cold-start latency.
    Validates template coverage at startup - fails fast on mismatch.
    """
    # Configure logging (suppress noisy loggers in non-full modes)
    from app.debug_utils import _debug, configure_logging

    configure_logging()

    # Log build info for cache debugging
    logger.info(
        "[Startup] Build info: prompt_bundle_hash=%s, planner_build_id=%s, cache_schema_version=%s",
        PROMPT_BUNDLE_HASH,
        PLANNER_BUILD_ID,
        CACHE_SCHEMA_VERSION,
    )
    _debug(
        f"[Startup] prompt_bundle_hash={PROMPT_BUNDLE_HASH}, "
        f"planner_build_id={PLANNER_BUILD_ID}, cache_schema_version={CACHE_SCHEMA_VERSION}"
    )

    # Prewarm validation cache
    validation_count = prewarm_cache()
    _debug(f"[Validation] Pre-warmed cache with {validation_count} entries")

    # Prewarm prompts and templates (Jinja2 compilation)
    warmup_stats = prewarm_prompts()
    _debug(
        f"[Warmup] Pre-compiled {warmup_stats['prompts_warmed']} prompts, "
        f"{warmup_stats['templates_loaded']} templates in {warmup_stats['warmup_ms']}ms"
    )

    # Validate template coverage - FATAL on failure
    # This prevents deploy-time prompt/template drift that causes hard-to-debug runtime behavior
    template_validation = validate_template_coverage()
    if not template_validation["valid"]:
        error_msg = (
            f"[FATAL] Template coverage validation failed: "
            f"missing_fields={template_validation['missing_fields']}, "
            f"errors={template_validation['errors'][:3]}"
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    _debug(
        f"[Startup] Template coverage validation passed "
        f"(insufficient_suggestions={template_validation.get('insufficient_suggestions', {})})"
    )

    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# Sync DB dependency for legacy endpoints and migrations
db_dependency = Depends(get_db)
# Async DB dependency for async endpoints
async_db_dependency = Depends(get_async_db)


# =============================================================================
# Rate Limiting (slowapi)
# =============================================================================


def _rate_key(request: Request) -> str:
    """Session cookie -> IP fallback for rate limit keying.

    OPTIONS preflights share a single bucket so CORS preflight requests
    never exhaust a real user's rate limit.
    """
    if request.method == "OPTIONS":
        return "__preflight__"
    return request.cookies.get("session_id") or get_remote_address(request)


limiter = Limiter(key_func=_rate_key, enabled=settings.rate_limit_enabled)
app.state.limiter = limiter


def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
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

_sse_connections: dict[str, int] = defaultdict(int)

MAX_SSE_PER_SESSION = 2
MAX_SSE_PER_IP = 5


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
async def get_destination_image(
    request: Request, req: DestinationImageRequest, db: AsyncSession = async_db_dependency
):
    """
    Get the Unsplash image URL for a destination.

    Called when user selects a destination to show the correct banner image
    immediately, without waiting for plan generation.
    """
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
def admin_clear_validation_cache(request: Request):
    """
    Clear the validation cache. For development/debugging only.
    """
    before = cache_stats()
    count = clear_cache()
    # Re-populate with common values
    new_count = prewarm_cache()
    return {
        "cleared": count,
        "repopulated": new_count,
        "stats": {
            "before": before,
            "after": cache_stats(),
        },
    }


@app.post("/api/admin/fresh-start", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def admin_fresh_start(request: Request):
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
    before_validation = cache_stats()
    before_response = response_cache_stats()
    before_checkpoints = checkpoint_stats()

    # Clear validation caches (preserve rate limiting)
    validation_cleared = clear_cache(preserve_rate_limiting=True)

    # Clear response caches
    response_cleared = await clear_response_caches()

    # Prune stale checkpoints
    checkpoints_pruned = prune_stale_checkpoints()

    # Re-populate validation cache with common values
    validation_repopulated = prewarm_cache()

    return {
        "validation": {
            "cleared": validation_cleared,
            "repopulated": validation_repopulated,
            "before": before_validation,
            "after": cache_stats(),
        },
        "response_caches": {
            "cleared": response_cleared,
            "before": before_response,
            "after": response_cache_stats(),
        },
        "checkpoints": {
            "pruned": checkpoints_pruned,
            "before": before_checkpoints,
            "after": checkpoint_stats(),
        },
    }


@app.get("/api/admin/graph-stats", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
def admin_graph_stats(request: Request):
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
def admin_planner_debug(request: Request):
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
async def admin_clear_all_checkpoints(request: Request):
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
async def admin_clear_all_caches(request: Request, db: AsyncSession = async_db_dependency):
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
    results = {
        "timestamp": datetime.utcnow().isoformat(),
        "caches_cleared": {},
    }

    # 1. Get before stats
    before_validation = cache_stats()
    before_response = response_cache_stats()
    before_checkpoints = checkpoint_stats()
    before_unsplash = get_unsplash_memory_stats()

    # 2. Clear planner caches + validation + checkpointer + prompts
    planner_cleared = clear_all_caches()
    results["caches_cleared"]["planner_and_validation"] = planner_cleared

    # 3. Clear Unsplash memory cache
    unsplash_memory_count = before_unsplash["entries"]
    clear_unsplash_memory_cache()
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
    from app.services.tile_cache import clear_memory_cache as clear_tile_memory

    tile_memory_count = clear_tile_memory()
    results["caches_cleared"]["tile_memory"] = tile_memory_count

    # 7. Clear Router cache (L1 only)
    from app.services.router_cache import clear_cache as clear_router_cache

    router_count = clear_router_cache()
    results["caches_cleared"]["router_memory"] = router_count

    # 8. Summary
    total = (
        planner_cleared
        + unsplash_memory_count
        + unsplash_db_count
        + specialist_memory_count
        + specialist_db_count
        + tile_memory_count
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
        "validation": cache_stats(),
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
async def admin_specialist_cache_stats(request: Request, db: AsyncSession = async_db_dependency):
    """
    Get specialist LLM cache statistics for observability.

    Returns L1 (memory) and L2 (database) hit/miss counts, sizes, and TTLs.
    """
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
async def admin_clear_specialist_cache(request: Request, db: AsyncSession = async_db_dependency):
    """
    Clear both L1 (memory) and L2 (database) specialist caches.

    Use for development/debugging when you want fresh LLM calls.
    """
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
async def admin_tile_cache_stats(request: Request, db: AsyncSession = async_db_dependency):
    """
    Get tile data cache statistics for observability.

    Returns L1 (memory) and L2 (database) hit/miss counts, sizes, and TTLs.
    """
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
async def admin_clear_tile_cache(request: Request, db: AsyncSession = async_db_dependency):
    """
    Clear both L1 (memory) and L2 (database) tile caches.

    Use for development/debugging when you want fresh provider data.
    """
    from sqlalchemy import delete

    from app.db_models import ResponseCache
    from app.services.tile_cache import clear_memory_cache

    l1_cleared = clear_memory_cache()

    # Clear L2 (tiles only)
    result = await db.execute(delete(ResponseCache).where(ResponseCache.cache_type == "tiles"))
    await db.commit()
    l2_cleared = result.rowcount

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
async def admin_router_cache_stats(request: Request):
    """
    Get router extraction cache statistics for observability.

    Note: Router cache is L1-only (no database persistence).
    Shows hits, misses, and skipped context-dependent queries.
    """
    from app.services.router_cache import get_cache_stats

    return get_cache_stats()


@app.post("/api/admin/clear-router-cache", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def admin_clear_router_cache(request: Request):
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
async def admin_all_cache_stats(request: Request, db: AsyncSession = async_db_dependency):
    """
    Get all cache statistics in one call.

    Returns stats for:
    - Specialist cache (L1 + L2)
    - Tile cache (L1 + L2)
    - Router cache (L1 only)
    """
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


@app.post("/api/tiles/click")
@limiter.limit("60/minute")
def track_tile_click(
    request: Request,
    event: schemas.TileClickEvent,
    db: Session = db_dependency,
):
    """
    Persist a tile click for analytics.
    """
    session_id = get_session_from_request(request)
    click = db_models.TileClick(
        tile_identifier=event.tile_id,
        branch_identifier=event.branch_id,
        session_id=session_id,
        request_id=event.request_id,
    )

    db.add(click)
    db.commit()

    return {"status": "ok"}


@app.post("/api/suggestions/click")
@limiter.limit("60/minute")
def track_suggestion_click(
    request: Request,
    event: schemas.SuggestionClickEvent,
    db: Session = db_dependency,
):
    """
    Persist a suggestion pill click for analytics.
    Tracks which LLM-generated suggestions users find valuable.
    """
    session_id = get_session_from_request(request)
    click = db_models.SuggestionClick(
        suggestion_text=event.suggestion_text[:128],  # Truncate to fit column
        suggestion_index=event.suggestion_index,
        session_id=session_id,
        request_id=event.request_id,
    )

    db.add(click)
    db.commit()

    return {"status": "ok"}


@app.post("/api/graph_plan", response_model=GraphPlanResponse)
@limiter.limit("3/minute;15/hour")
async def graph_plan_endpoint(
    request: Request,
    response: Response,
    req: GraphPlanRequest,
    db: AsyncSession = async_db_dependency,
):
    """
    LangGraph-based planning endpoint.

    Accepts a user message and optional session state, runs the graph planner,
    persists document updates, and returns the updated session state.

    Features:
    - Feature flag gating (ENABLE_GRAPH_PLAN_ROUTE)
    - Payload size validation
    - Optimistic concurrency via document versioning
    - Cache-Control: no-store to prevent caching of personalized responses
    """
    # --- Feature flag gate ---
    if not settings.enable_graph_plan_route:
        raise HTTPException(
            status_code=503,
            detail={
                "error_code": GraphPlanErrorCode.ROUTE_DISABLED,
                "message": "Graph plan route is disabled",
            },
        )

    # --- Content-Type validation ---
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("application/json"):
        raise HTTPException(
            status_code=415,
            detail={
                "error_code": GraphPlanErrorCode.UNSUPPORTED_MEDIA_TYPE,
                "message": "Content-Type must be application/json",
            },
        )

    # --- Payload size validation ---
    payload_error = check_payload_size(request)
    if payload_error:
        raise HTTPException(
            status_code=413,
            detail={
                "error_code": GraphPlanErrorCode.PAYLOAD_TOO_LARGE,
                "message": payload_error,
            },
        )

    # --- Generate request ID and compute today_iso ---
    request_id = generate_request_id()
    today_iso = compute_today_iso()

    # --- Validate thread_id if provided ---
    if req.thread_id and not is_valid_thread_id(req.thread_id):
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": GraphPlanErrorCode.INVALID_THREAD_ID,
                "message": "Invalid thread_id format",
            },
        )

    # --- Sanitize and prepare session state ---
    session_state = sanitize_session_state(req.session_state)

    # --- Handle reset parameter: new thread_id when reset=true + empty session_state ---
    if req.reset and not session_state:
        session_state = {}
        session_state["thread_id"] = str(ensure_thread_id(None))  # Force new thread
        # Initialize from trip_inputs if provided
        if req.trip_inputs:
            session_state["trip_inputs"] = normalize_trip_inputs(dict(req.trip_inputs))
    elif not session_state:
        session_state = {}

    # --- Initialize or merge trip_inputs ---
    # CRITICAL: Always merge req.trip_inputs into session_state to ensure
    # the latest frontend values (destination, dates, etc.) are used.
    if "trip_inputs" not in session_state:
        raw_inputs = dict(req.trip_inputs) if req.trip_inputs else {}
        session_state["trip_inputs"] = normalize_trip_inputs(raw_inputs)
    elif req.trip_inputs:
        # Merge incoming trip_inputs into existing (incoming takes precedence)
        existing = session_state.get("trip_inputs", {})
        incoming = dict(req.trip_inputs)
        for key, value in incoming.items():
            if value is not None:
                existing[key] = value
        session_state["trip_inputs"] = normalize_trip_inputs(existing)

    # --- Ensure thread_id is set ---
    if "thread_id" not in session_state:
        session_state["thread_id"] = ensure_thread_id(req.thread_id)

    # --- Inject today_iso into session state for date parsing ---
    session_state["today_iso"] = today_iso

    # --- Get session from request for document persistence ---
    session_id = get_session_from_request(request)
    db_session = await get_or_create_session(db, session_id)

    # --- Create telemetry envelope for this request ---
    thread_id = session_state.get("thread_id", "")
    trace_envelope = create_envelope(
        request=request,
        thread_id=thread_id,
        session_id=session_id,
        redaction_mode=settings.trace_redaction_mode,
    )
    # Store envelope in session_state metadata for downstream access
    session_state.setdefault("metadata", {})[TRACE_ENVELOPE] = trace_envelope.to_dict()

    # --- Inject ui_phase and suggestion_clicked into metadata ---
    if req.ui_phase is not None:
        session_state["metadata"]["ui_phase"] = req.ui_phase
    if req.suggestion_clicked is not None:
        session_state["metadata"]["suggestion_clicked"] = req.suggestion_clicked

    # --- Track previous ready_to_generate for observability ---
    ready_to_generate_prev = session_state.get("metadata", {}).get("ready_to_generate", False)

    # --- Get or create document for this session ---
    document = None
    document_data = None
    document_version = None
    try:
        document = await get_or_create_document(db, session=db_session)
        document_data = get_document_data(document)
        document_version = document.version

        # Check optimistic concurrency if expected_version provided
        if req.expected_version is not None and document_version != req.expected_version:
            msg = (
                f"Document version mismatch: "
                f"expected {req.expected_version}, got {document_version}"
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "error_code": GraphPlanErrorCode.VERSION_CONFLICT,
                    "message": msg,
                    "server_doc_version": document_version,
                    "client_doc_version": req.expected_version,
                    "retry_after_ms": 100,
                },
            )

        # Hydrate session state from document (branches AND trip_inputs)
        if document_data:
            if document_data.branches:
                session_state["branches"] = [b.model_dump() for b in document_data.branches]
            # CRITICAL FIX: Always use document trip_inputs as BASELINE,
            # then merge request on top. This ensures fields set via settings panel
            # (origin, flight_settings, etc.) are preserved when the chat request
            # only has partial trip_inputs.
            # @see docs/plan_graph_analysis.md - Origin sync for flight fetching
            if document_data.trip_inputs:
                doc_inputs = document_data.trip_inputs.model_dump()
                session_inputs = session_state.get("trip_inputs", {})
                # User-owned settings fields — document is SSoT (set via PATCH
                # from frontend sheets). Session may carry stale values from
                # previous graph runs; document always wins for these.
                _USER_OWNED_SETTINGS = {
                    "activity_settings",
                    "hotel_settings",
                    "flight_settings",
                    "transport_settings",
                    "booking_types",
                }
                # Document as baseline, session overrides for graph-owned fields only
                merged = {**doc_inputs}
                for k, v in session_inputs.items():
                    if v is not None and k not in _USER_OWNED_SETTINGS:
                        merged[k] = v
                session_state["trip_inputs"] = normalize_trip_inputs(merged)
                # HARD TRACE: Log doc's activity categories at merge time
                _doc_cats = doc_inputs.get("activity_settings", {}).get("categories", [])
                _final_cats = (
                    session_state["trip_inputs"].get("activity_settings", {}).get("categories", [])
                )
                logger.info(
                    f"[{request_id}] trip_inputs merge: "
                    f"doc.categories={_doc_cats}, "
                    f"final.categories={_final_cats}, "
                    f"doc.origin={doc_inputs.get('origin')}"
                )
    except HTTPException:
        raise  # Re-raise HTTP exceptions (like version conflict)
    except Exception as e:
        logger.warning(f"[{request_id}] Failed to load document for session: {e}")
        # Continue without document - not fatal

    # ── Pass document's user-owned settings to graph state ──
    # _restore_graph_state merges these into state.metadata["trip_inputs"],
    # ensuring the graph sees pill selections / settings panel values
    # even when the session carries stale trip_inputs from a prior turn.
    if document:
        try:
            await db.refresh(document)
            fresh_data = get_document_data(document)
            if fresh_data.trip_inputs:
                ti = fresh_data.trip_inputs
                session_state["_doc_settings"] = {
                    "activity_settings": ti.activity_settings.model_dump()
                    if ti.activity_settings
                    else {},
                    "hotel_settings": ti.hotel_settings.model_dump() if ti.hotel_settings else {},
                    "flight_settings": ti.flight_settings.model_dump()
                    if ti.flight_settings
                    else {},
                    "transport_settings": ti.transport_settings.model_dump()
                    if ti.transport_settings
                    else {},
                    "booking_types": ti.booking_types.model_dump() if ti.booking_types else {},
                }
                # HARD TRACE: Log what we're injecting
                _cats = ti.activity_settings.categories if ti.activity_settings else []
                logger.info(
                    f"[{request_id}] _doc_settings injected: activity_settings.categories={_cats}"
                )
            # ── Sync last_builder_success from document state ──
            # expand-itinerary persists plan_view_state to the document but
            # never updates session_state.metadata.  Bridge the gap here so the
            # constraint guard sees builder success on the next graph turn.
            if fresh_data.plan_view_state == "S3_ITINERARY_READY":
                session_state.setdefault("metadata", {})["last_builder_success"] = True
        except Exception as e:
            logger.error(f"[{request_id}] _doc_settings injection FAILED: {e}")

    # Note: We intentionally do not reject relative date phrases (e.g., "next week").
    # The planner should handle them contextually using today_iso.

    # --- Emit telemetry request start ---
    request_start_ns = emit_request_start(trace_envelope, req.message)

    # --- Log user input for DEBUG=full mode ---
    log_user_input(req.message, request_id)

    # --- Call run_turn with route-level timeout ---
    route_timeout_seconds = settings.graph_plan_route_timeout_ms / 1000.0
    try:
        # Wrap run_turn in asyncio.wait_for for route-level timeout protection
        result = await asyncio.wait_for(
            run_turn(req.message, session_state),
            timeout=route_timeout_seconds,
        )
        logger.info(f"[{request_id}] Graph planner succeeded (LangGraph path)")
    except asyncio.TimeoutError:
        force_verbose_on_anomaly(trace_envelope, session_state.get("metadata", {}))
        emit_anomaly_bundle(
            trace_envelope,
            anomaly_type="timeout",
            metadata={"timeout_seconds": route_timeout_seconds, "session_id": session_id},
        )
        logger.error(
            f"[{request_id}] Route timeout after {route_timeout_seconds}s (session_id={session_id})"
        )
        raise HTTPException(
            status_code=504,
            detail={
                "error_code": GraphPlanErrorCode.LLM_TIMEOUT,
                "message": f"Planning request timed out after {route_timeout_seconds}s",
            },
        ) from None
    except TimeoutError:
        force_verbose_on_anomaly(trace_envelope, session_state.get("metadata", {}))
        emit_anomaly_bundle(
            trace_envelope,
            anomaly_type="timeout",
            metadata={"reason": "TimeoutError"},
        )
        logger.error(f"[{request_id}] run_turn timed out")
        raise HTTPException(
            status_code=504,
            detail={
                "error_code": GraphPlanErrorCode.LLM_TIMEOUT,
                "message": "Planning request timed out",
            },
        ) from None
    except Exception as e:
        force_verbose_on_anomaly(trace_envelope, session_state.get("metadata", {}))
        emit_anomaly_bundle(
            trace_envelope,
            anomaly_type="exception",
            metadata={"error": str(e), "error_type": type(e).__name__},
        )
        logger.error(f"[{request_id}] run_turn failed: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": GraphPlanErrorCode.LLM_ERROR,
                "message": "Planning request failed",
            },
        ) from e

    # --- Extract cache summary for telemetry ---
    cache_summary = result.get("session_state", {}).get("metadata", {}).get("cache_summary", {})

    # --- Emit telemetry request end ---
    emit_request_end(
        envelope=trace_envelope,
        start_ns=request_start_ns,
        cache_summary=cache_summary,
        error=None,
    )

    # --- Validate and sanitize output ---
    assistant_message = result.get("assistant_message", "")
    # Use async LLM re-summarization for long messages, with sync fallback
    if len(assistant_message) > settings.assistant_msg_max_len:
        try:
            assistant_message = await condense_long_message(
                assistant_message,
                settings.assistant_msg_max_len,
            )
        except Exception as e:
            logger.warning(f"[{request_id}] Condense failed, using sync truncation: {e}")
            assistant_message = truncate_assistant_message(assistant_message)

    # Validate suggested responses
    suggested_responses = result.get("suggested_responses", [])
    suggested_responses = validate_suggested_responses(suggested_responses)

    # --- Log LLM output for DEBUG=full mode ---
    log_llm_output(assistant_message, request_id)

    # Extract updated session state
    updated_session_state = result.get("session_state", session_state)

    # Extract branches and trip_inputs from result
    branches = result.get("branches", [])
    trip_inputs = result.get("trip_inputs", updated_session_state.get("trip_inputs", {}))
    ready_to_generate_now = result.get("ready_to_generate", False)
    # Note: errors are in result but not currently surfaced in response

    # --- Compute changes_made by comparing trip_inputs ---
    changes_made = trip_inputs != session_state.get("trip_inputs", {})

    # --- Persist document if we have a document ---
    new_document_version = document_version
    updated_at = datetime.now().isoformat()
    if document:
        try:
            # Convert branches to DocumentBranch objects if needed
            from app.schemas import DocumentBranch, DocumentTripInputs

            branch_objs = []
            for b in branches:
                if isinstance(b, dict):
                    branch_objs.append(DocumentBranch.model_validate(b))
                else:
                    branch_objs.append(b)

            # Convert trip_inputs to DocumentTripInputs if needed
            trip_inputs_obj = None
            if trip_inputs:
                if isinstance(trip_inputs, dict):
                    trip_inputs_obj = DocumentTripInputs.model_validate(trip_inputs)
                else:
                    trip_inputs_obj = trip_inputs

            # Get or create trip context for this session
            trip_context = await get_latest_trip_context_for_session(db, session=db_session)
            trip_context_id = trip_context.id if trip_context else 0

            # Extract viewModel fields from result for persistence
            graph_doc = result.get("document", {})
            graph_strategy_sections = graph_doc.get("strategy_sections", [])
            strategy_section_objs = None
            if graph_strategy_sections:
                strategy_section_objs = [
                    StrategySection(**s) if isinstance(s, dict) else s
                    for s in graph_strategy_sections
                ]

            # Extract tiles from graph document for persistence
            tiles_from_graph = graph_doc.get("tiles", {})
            tiles_dict = {}
            if tiles_from_graph:
                for tile_id, tile_data in tiles_from_graph.items():
                    if isinstance(tile_data, dict):
                        tiles_dict[tile_id] = Tile.model_validate(tile_data)
                    elif isinstance(tile_data, Tile):
                        tiles_dict[tile_id] = tile_data
            logger.info(f"[TILES] Persisting {len(tiles_dict)} tiles to DB (graph_plan)")

            # Extract NL-extracted settings for deep-merge persistence
            nl_extracted = updated_session_state.get("metadata", {}).get("extracted_settings")

            # Apply planner update
            updated_doc = await apply_planner_update(
                db,
                doc=document,
                trip_context_id=trip_context_id,
                trip_inputs=trip_inputs_obj,
                branches=branch_objs if branch_objs else None,
                tiles=tiles_dict if tiles_dict else None,
                # ViewModel fields for session restoration
                plan_view_state=graph_doc.get("plan_view_state"),
                strategy_sections=strategy_section_objs,
                executed_strategy_topics=graph_doc.get("executed_strategy_topics"),
                pending_strategy_topics=graph_doc.get("pending_strategy_topics"),
                day_cards=graph_doc.get("day_cards"),
                can_expand_to_itinerary=graph_doc.get("can_expand_to_itinerary"),
                extracted_settings=nl_extracted,
            )
            if updated_doc:
                new_document_version = updated_doc.version
                document_data = get_document_data(updated_doc)
                await db.commit()
        except Exception as e:
            logger.error(f"[{request_id}] Failed to persist document: {e}")
            await db.rollback()
            # Non-fatal - continue with response

    # --- Build observability data ---
    # Extract confidence data from session state metadata
    extraction_conf_raw = (
        result.get("session_state", {}).get("metadata", {}).get("extraction_confidence", {})
    )
    extraction_confidence = None
    if extraction_conf_raw:
        typo_suggestions_raw = extraction_conf_raw.get("typo_suggestions", [])
        typo_suggestions: list[str]
        if isinstance(typo_suggestions_raw, dict):
            # plan_graph stores typo suggestions as {original: suggested}
            # API schema expects list[str]
            typo_suggestions = [f"{k} -> {v}" for k, v in typo_suggestions_raw.items()]
        elif isinstance(typo_suggestions_raw, list):
            typo_suggestions = [str(x) for x in typo_suggestions_raw]
        else:
            typo_suggestions = []

        # Build destination confidence info list
        dest_confidences = []
        for dest_conf in extraction_conf_raw.get("destinations", []):
            dest_confidences.append(
                EntityConfidenceInfo(
                    value=dest_conf.get("value", ""),
                    confidence=dest_conf.get("confidence", 1.0),
                    needs_confirmation=dest_conf.get("needs_confirmation", False),
                    fuzzy_suggestion=dest_conf.get("fuzzy_suggestion"),
                    ambiguity_type=dest_conf.get("ambiguity_type"),
                )
            )

        # Build origin confidence info if present
        origin_conf_raw = extraction_conf_raw.get("origin")
        origin_confidence = None
        if origin_conf_raw:
            origin_confidence = EntityConfidenceInfo(
                value=origin_conf_raw.get("value", ""),
                confidence=origin_conf_raw.get("confidence", 1.0),
                needs_confirmation=origin_conf_raw.get("needs_confirmation", False),
                fuzzy_suggestion=origin_conf_raw.get("fuzzy_suggestion"),
                ambiguity_type=origin_conf_raw.get("ambiguity_type"),
            )

        extraction_confidence = ExtractionConfidenceInfo(
            overall=extraction_conf_raw.get("overall", 1.0),
            level=extraction_conf_raw.get("level", "high"),
            destinations=dest_confidences,
            origin=origin_confidence,
            detected_language=extraction_conf_raw.get("detected_language"),
            is_english=extraction_conf_raw.get("is_english", True),
            typo_suggestions=typo_suggestions,
        )

    observability = GraphPlanObservability(
        tokens=GraphPlanTokens(prompt=0, completion=0, total=0),  # TODO: populate from LLM
        model_used=result.get("session_state", {}).get("metadata", {}).get("model_used"),
        router_intent=result.get("session_state", {}).get("router_intent"),
        strategy_topic=result.get("session_state", {}).get("strategy_topic"),
        today_iso=today_iso,
        ready_to_generate_prev=ready_to_generate_prev,
        ready_to_generate_now=ready_to_generate_now,
        extraction_confidence=extraction_confidence,
    )

    # --- Set Cache-Control header ---
    response.headers["Cache-Control"] = "no-store"

    # --- Build document data for response ---
    response_document = document_data if document_data else PlanDocumentData()

    # --- Set assistant_message and suggested_responses from this turn's result ---
    response_document.assistant_message = assistant_message
    response_document.suggested_responses = suggested_responses
    response_document.ready_to_generate = ready_to_generate_now

    # --- Set change tracking fields for UI receipts ---
    session_metadata = result.get("session_state", {}).get("metadata", {})
    response_document.applied_updates = session_metadata.get("turn_applied_fields", [])
    response_document.update_provenance = session_metadata.get("update_provenance")
    # Only include undo_snapshot if there were applied updates
    if response_document.applied_updates:
        response_document.undo_snapshot = session_metadata.get("prev_trip_inputs_snapshot")

    # --- Build detailed ack_updates for collapsible messages UI ---
    ack_updates = []
    for ui_key in response_document.applied_updates:
        # Map UI key to trip_inputs field and get current value
        value = _get_trip_input_display_value(ui_key, trip_inputs)
        if value:
            ack_updates.append(AckUpdate(field=ui_key, to=value))
    response_document.ack_updates = ack_updates

    # --- Check for blocking route violations (Logic Guards) ---
    # Route errors (SAME_CITY_ERROR, UNKNOWN_DESTINATION_ERROR) trigger "rejected" status
    constraint_violations = session_metadata.get("constraint_violations", [])
    route_violation = next(
        (
            v
            for v in constraint_violations
            if v.get("category") == "route" and v.get("severity") == "blocking"
        ),
        None,
    )

    # Set ack_status based on violations or applied updates
    if route_violation:
        # Logic Guard rejection - use amber UI pattern (DS Section 20)
        response_document.ack_status = "rejected"
        response_document.ack_updates = [
            AckUpdate(field="route", to=route_violation.get("code", "INVALID_ROUTE"))
        ]
    elif ack_updates:
        response_document.ack_status = "applied"
    elif response_document.applied_updates:
        response_document.ack_status = "partial"
    else:
        response_document.ack_status = "no_change"

    # --- Compute Plan State Envelope fields ---
    # Get ui_phase from request (defaults to "bootstrap")
    response_document.ui_phase = req.ui_phase or "bootstrap"

    # Compute readiness from trip_inputs
    readiness = compute_trip_readiness(trip_inputs, errors=result.get("errors", []))

    # Build readiness array for frontend
    response_document.readiness = [
        ReadinessItem(key="origin", ok=readiness.has_origin),
        ReadinessItem(key="destination", ok=readiness.has_destination),
        ReadinessItem(key="start_date", ok=readiness.has_dates),
        ReadinessItem(key="end_date", ok=bool(trip_inputs.get("end_date"))),
        ReadinessItem(key="travelers", ok=trip_inputs.get("adults") is not None),
        ReadinessItem(key="budget", ok=trip_inputs.get("budget") is not None),
    ]

    # Compute plan_state from readiness and generation state
    # INCOMPLETE: missing required fields
    # RESOLVING: will be set during SSE streaming (not applicable for sync endpoint)
    # STABLE: all fields present
    # LOCKED: not implemented yet
    if not readiness.core_complete:
        response_document.plan_state = "INCOMPLETE"
    else:
        response_document.plan_state = "STABLE"

    # Build destination_card if destination exists
    dest_name = trip_inputs.get("destination")
    if dest_name:
        # Use async version to actually fetch from Unsplash API (sync version only checks cache)
        # Banner image is based on location only, not activities
        dest_image_url = await get_image_for_destination(
            dest_name, variant=0, db=db, width=1600, height=900
        )
        response_document.destination_card = DestinationCard(
            title=dest_name,
            subtitle=f"Your adventure in {dest_name}" if dest_name else None,
            image_url=dest_image_url,
        )

    # resolver is None for sync endpoint (only used during SSE streaming)
    response_document.resolver = None

    # booking_status will be populated based on tiles/branches if available
    # For now, set based on whether we have tiles
    if response_document.tiles:
        flights_count = sum(1 for t in response_document.tiles.values() if t.type == "flight")
        hotels_count = sum(1 for t in response_document.tiles.values() if t.type == "hotel")
        activities_count = sum(1 for t in response_document.tiles.values() if t.type == "activity")
        response_document.booking_status = BookingStatus(
            flights=BookingStatusItem(
                state="ready" if flights_count > 0 else "idle",
                summary=(
                    f"Flights · {flights_count} options"
                    if flights_count
                    else "Flights · not started"
                ),
            ),
            stays=BookingStatusItem(
                state="ready" if hotels_count > 0 else "idle",
                summary=(
                    f"Stays · {hotels_count} options" if hotels_count else "Stays · not started"
                ),
            ),
            activities=BookingStatusItem(
                state="ready" if activities_count > 0 else "idle",
                summary=(
                    f"Activities · {activities_count} options"
                    if activities_count
                    else "Activities · not started"
                ),
            ),
        )

    # --- Graph Output Processing ---
    # Compute plan_view_state based on actual state (tiles/destination/dates)
    graph_document = result.get("document", {})
    response_document.plan_view_state = graph_document.get("plan_view_state", "S0_BOOTSTRAP")

    # Apply strategy sections if present
    graph_strategy_sections = graph_document.get("strategy_sections", [])
    if graph_strategy_sections:
        response_document.strategy_sections = [
            StrategySection(**section) if isinstance(section, dict) else section
            for section in graph_strategy_sections
        ]
        response_document.executed_strategy_topics = graph_document.get(
            "executed_strategy_topics", []
        )
        response_document.pending_strategy_topics = graph_document.get(
            "pending_strategy_topics", []
        )

    # Apply graph tiles if present and response doesn't have tiles
    graph_tiles = graph_document.get("tiles", {})
    if graph_tiles and not response_document.tiles:
        response_document.tiles = {
            tile_id: Tile.model_validate(tile_data) if isinstance(tile_data, dict) else tile_data
            for tile_id, tile_data in graph_tiles.items()
        }

    # Copy origin_just_set flag for frontend flight fetch trigger
    response_document.origin_just_set = graph_document.get("origin_just_set", False)

    # --- Build and return response ---
    return GraphPlanResponse(
        document=response_document,
        session_state=updated_session_state,
        version=new_document_version or 1,
        updated_by="planner",
        updated_at=updated_at,
        changes_made=changes_made,
        request_id=request_id,
        observability=observability,
    )


# =============================================================================
# SSE Streaming Graph Plan Endpoint
# =============================================================================


@app.post("/api/graph_plan/stream")
@limiter.limit("3/minute;15/hour")
async def graph_plan_stream_endpoint(
    request: Request,
    req: GraphPlanRequest,
    db: AsyncSession = async_db_dependency,
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
    session_state = sanitize_session_state(req.session_state)

    # --- Handle reset parameter ---
    if req.reset and not session_state:
        session_state = {}
        session_state["thread_id"] = str(ensure_thread_id(None))
        if req.trip_inputs:
            session_state["trip_inputs"] = normalize_trip_inputs(dict(req.trip_inputs))
    elif not session_state:
        session_state = {}

    # --- Initialize or merge trip_inputs ---
    # CRITICAL: Always merge req.trip_inputs into session_state to ensure
    # the latest frontend values (destination, dates, etc.) are used.
    # This fixes the bug where Setup mode had stale/empty destination.
    if "trip_inputs" not in session_state:
        raw_inputs = dict(req.trip_inputs) if req.trip_inputs else {}
        session_state["trip_inputs"] = normalize_trip_inputs(raw_inputs)
    elif req.trip_inputs:
        # Merge incoming trip_inputs into existing (incoming takes precedence)
        existing = session_state.get("trip_inputs", {})
        incoming = dict(req.trip_inputs)
        for key, value in incoming.items():
            if value is not None:
                existing[key] = value
        session_state["trip_inputs"] = normalize_trip_inputs(existing)

    # --- Ensure thread_id is set ---
    if "thread_id" not in session_state:
        session_state["thread_id"] = ensure_thread_id(req.thread_id)

    # --- Inject today_iso into session state ---
    session_state["today_iso"] = today_iso

    # --- Inject ui_phase and suggestion_clicked into metadata ---
    if "metadata" not in session_state:
        session_state["metadata"] = {}
    if req.ui_phase is not None:
        session_state["metadata"]["ui_phase"] = req.ui_phase
    if req.suggestion_clicked is not None:
        session_state["metadata"]["suggestion_clicked"] = req.suggestion_clicked

    # --- Get session from request for document persistence ---
    session_id = get_session_from_request(request)

    # --- SSE concurrent connection limit ---
    client_ip = request.client.host if request.client else "unknown"
    session_key = f"session:{session_id}"
    ip_key = f"ip:{client_ip}"

    if _sse_connections[session_key] >= MAX_SSE_PER_SESSION:
        return JSONResponse(429, {"detail": "Too many concurrent streams for this session"})
    if _sse_connections[ip_key] >= MAX_SSE_PER_IP:
        return JSONResponse(429, {"detail": "Too many concurrent streams from this IP"})

    _sse_connections[session_key] += 1
    _sse_connections[ip_key] += 1

    async def generate_sse():
        """Generator that yields SSE events from the streaming graph execution."""
        try:
            db_session = await get_or_create_session(db, session_id)

            # Get or create document
            document = None
            document_data = None
            document_version = None
            try:
                document = await get_or_create_document(db, session=db_session)
                document_data = get_document_data(document)
                document_version = document.version

                # Record user message with trip_inputs snapshot for undo functionality
                user_message_content = req.message
                trip_inputs_snapshot = None
                if document_data and document_data.trip_inputs:
                    ti = document_data.trip_inputs
                    trip_inputs_snapshot = {
                        "destination": ti.destination,
                        "origin": ti.origin,
                        "start_date": ti.start_date,
                        "end_date": ti.end_date,
                        "adults": ti.adults,
                        "children": ti.children,
                        "requires_assistance": ti.requires_assistance,
                        "budget": ti.budget,
                        "currency": ti.currency,
                        "booking_types": ti.booking_types.model_dump() if ti.booking_types else {},
                        "flight_settings": (
                            ti.flight_settings.model_dump() if ti.flight_settings else {}
                        ),
                        "hotel_settings": (
                            ti.hotel_settings.model_dump() if ti.hotel_settings else {}
                        ),
                        "activity_settings": (
                            ti.activity_settings.model_dump() if ti.activity_settings else {}
                        ),
                        "transport_settings": (
                            ti.transport_settings.model_dump() if ti.transport_settings else {}
                        ),
                    }

                await record_chat_message(
                    db,
                    session=db_session,
                    trip_context=None,
                    role="user",
                    content=user_message_content,
                    metadata=None,
                    trip_inputs_snapshot=trip_inputs_snapshot,
                )

                # Hydrate session state from document
                if document_data:
                    if document_data.branches:
                        session_state["branches"] = [b.model_dump() for b in document_data.branches]
                    # CRITICAL FIX: Always use document trip_inputs as BASELINE,
                    # then merge request on top. This ensures fields set via settings
                    # panel (origin, flight_settings, etc.) are preserved when the
                    # chat request only has partial trip_inputs.
                    # @see docs/plan_graph_analysis.md - Origin sync for flight fetching
                    if document_data.trip_inputs:
                        doc_inputs = document_data.trip_inputs.model_dump()
                        session_inputs = session_state.get("trip_inputs", {})
                        # User-owned settings fields — document is SSoT (set via PATCH
                        # from frontend sheets). Session may carry stale values from
                        # previous graph runs; document always wins for these.
                        _USER_OWNED_SETTINGS = {
                            "activity_settings",
                            "hotel_settings",
                            "flight_settings",
                            "transport_settings",
                            "booking_types",
                        }
                        # Document as baseline, session overrides for graph-owned fields only
                        merged = {**doc_inputs}
                        for k, v in session_inputs.items():
                            if v is not None and k not in _USER_OWNED_SETTINGS:
                                merged[k] = v
                        session_state["trip_inputs"] = normalize_trip_inputs(merged)

                        # req.trip_inputs is the freshest source for user-owned
                        # settings (Zustand snapshot at send time).  The document
                        # may be stale if ensureSettingsFlushed PATCH hasn't
                        # committed yet, or if get_or_create_document created a
                        # default doc with empty categories.
                        if req.trip_inputs:
                            req_ti = dict(req.trip_inputs)
                            current = session_state["trip_inputs"]
                            for field in _USER_OWNED_SETTINGS:
                                if field in req_ti and req_ti[field] is not None:
                                    val = req_ti[field]
                                    current[field] = (
                                        val.model_dump() if hasattr(val, "model_dump") else val
                                    )
                            session_state["trip_inputs"] = normalize_trip_inputs(current)

                        # HARD TRACE: Log doc's activity categories at merge time
                        _doc_cats = doc_inputs.get("activity_settings", {}).get("categories", [])
                        _final_cats = (
                            session_state["trip_inputs"]
                            .get("activity_settings", {})
                            .get("categories", [])
                        )
                        logger.info(
                            f"[{request_id}] trip_inputs merge: "
                            f"doc.categories={_doc_cats}, "
                            f"final.categories={_final_cats}, "
                            f"doc.origin={doc_inputs.get('origin')}"
                        )
            except Exception as e:
                logger.warning(f"[{request_id}] Failed to load document for session: {e}")

            # ── Pass document's user-owned settings to graph state ──
            # _restore_graph_state merges these into state.metadata["trip_inputs"],
            # ensuring the graph sees pill selections / settings panel values
            # even when the session carries stale trip_inputs from a prior turn.
            if document:
                try:
                    await db.refresh(document)
                    fresh_data = get_document_data(document)
                    if fresh_data.trip_inputs:
                        ti = fresh_data.trip_inputs
                        session_state["_doc_settings"] = {
                            "activity_settings": ti.activity_settings.model_dump()
                            if ti.activity_settings
                            else {},
                            "hotel_settings": ti.hotel_settings.model_dump()
                            if ti.hotel_settings
                            else {},
                            "flight_settings": ti.flight_settings.model_dump()
                            if ti.flight_settings
                            else {},
                            "transport_settings": ti.transport_settings.model_dump()
                            if ti.transport_settings
                            else {},
                            "booking_types": ti.booking_types.model_dump()
                            if ti.booking_types
                            else {},
                        }
                        # Override _doc_settings with req.trip_inputs (most
                        # current source — Zustand snapshot at send time).
                        # Prevents stale/empty doc values from clobbering
                        # correct pill selections in state_serde.restore_graph_state.
                        if req.trip_inputs:
                            req_ti = dict(req.trip_inputs)
                            for field in (
                                "activity_settings",
                                "hotel_settings",
                                "flight_settings",
                                "transport_settings",
                                "booking_types",
                            ):
                                if field in req_ti and req_ti[field] is not None:
                                    val = req_ti[field]
                                    session_state["_doc_settings"][field] = (
                                        val.model_dump() if hasattr(val, "model_dump") else val
                                    )

                        # HARD TRACE: Log what we're injecting
                        _cats = (
                            session_state["_doc_settings"]
                            .get("activity_settings", {})
                            .get("categories", [])
                        )
                        logger.info(
                            f"[{request_id}] _doc_settings injected: "
                            f"activity_settings.categories={_cats}"
                        )
                    # ── Sync last_builder_success from document state ──
                    if fresh_data.plan_view_state == "S3_ITINERARY_READY":
                        session_state.setdefault("metadata", {})["last_builder_success"] = True
                except Exception as e:
                    logger.error(f"[{request_id}] _doc_settings injection FAILED: {e}")

            # --- Log user input for DEBUG=full mode ---
            log_user_input(req.message, request_id)

            # Stream tokens from run_turn_streaming with per-event timeout
            # Use route timeout for total stream duration protection
            route_timeout_seconds = settings.graph_plan_route_timeout_ms / 1000.0
            final_result = None
            token_count = 0
            stream_start = asyncio.get_event_loop().time()

            async for event in run_turn_streaming(req.message, session_state):
                # Check if we've exceeded total stream timeout
                elapsed = asyncio.get_event_loop().time() - stream_start
                if elapsed > route_timeout_seconds:
                    logger.error(
                        f"[{request_id}] Stream timeout after {elapsed:.1f}s "
                        f"(limit: {route_timeout_seconds}s)"
                    )
                    timeout_payload = json.dumps(
                        {"type": "error", "message": f"Stream timed out after {elapsed:.1f}s"}
                    )
                    yield f"event: error\ndata: {timeout_payload}\n\n"
                    return

                if event["type"] == "token":
                    token_count += 1
                    if token_count <= 5 or token_count % 50 == 0:
                        logger.debug(f"[{request_id}] Streaming token #{token_count}")
                    yield f"event: token\ndata: {json.dumps(event)}\n\n"
                elif event["type"] == "node_status":
                    # Forward strategy node status for frontend progress tracking
                    node = event["data"].get("node")
                    status = event["data"].get("status")
                    logger.debug(f"[{request_id}] Node status: {node} - {status}")
                    yield f"event: node_status\ndata: {json.dumps(event)}\n\n"
                elif event["type"] == "complete":
                    logger.debug(f"[{request_id}] Stream complete after {token_count} tokens")
                    final_result = event["data"]
                elif event["type"] == "error":
                    # Forward graph errors to frontend with actual message
                    error_msg = event.get("message", "Unknown graph error")
                    logger.error(f"[{request_id}] Graph error: {error_msg}")
                    error_payload = json.dumps({"type": "error", "message": error_msg})
                    yield f"event: error\ndata: {error_payload}\n\n"
                    return

            if final_result is None:
                error_payload = json.dumps({"type": "error", "message": "No result from graph"})
                yield f"event: error\ndata: {error_payload}\n\n"
                return

            # --- Process and persist final result ---
            assistant_message = final_result.get("assistant_message", "")
            if len(assistant_message) > settings.assistant_msg_max_len:
                try:
                    assistant_message = await condense_long_message(
                        assistant_message,
                        settings.assistant_msg_max_len,
                    )
                except Exception as e:
                    logger.warning(f"[{request_id}] Condense failed: {e}")
                    assistant_message = truncate_assistant_message(assistant_message)

            suggested_responses = validate_suggested_responses(
                final_result.get("suggested_responses", [])
            )

            # --- Log LLM output for DEBUG=full mode ---
            log_llm_output(assistant_message, request_id)

            updated_session_state = final_result.get("session_state", session_state)
            branches = final_result.get("branches", [])
            trip_inputs = final_result.get(
                "trip_inputs", updated_session_state.get("trip_inputs", {})
            )
            ready_to_generate_now = final_result.get("ready_to_generate", False)
            changes_made = trip_inputs != session_state.get("trip_inputs", {})

            # Persist document
            new_document_version = document_version
            updated_at = datetime.now().isoformat()
            if document:
                try:
                    from app.schemas import DocumentBranch, DocumentTripInputs, Tile

                    branch_objs = []
                    for b in branches:
                        if isinstance(b, dict):
                            branch_objs.append(DocumentBranch.model_validate(b))
                        else:
                            branch_objs.append(b)

                    trip_inputs_obj = None
                    if trip_inputs:
                        if isinstance(trip_inputs, dict):
                            trip_inputs_obj = DocumentTripInputs.model_validate(trip_inputs)
                        else:
                            trip_inputs_obj = trip_inputs

                    trip_context = await get_latest_trip_context_for_session(db, session=db_session)
                    trip_context_id = trip_context.id if trip_context else 0

                    # Extract viewModel fields from graph result for persistence
                    graph_doc = final_result.get("document", {})

                    # Extract tiles from graph document (NOT session_state.metadata!)
                    # Tiles are returned in final_result.document.tiles by _format_result
                    tiles_from_graph = graph_doc.get("tiles", {})
                    tiles_dict = {}
                    if tiles_from_graph:
                        for tile_id, tile_data in tiles_from_graph.items():
                            if isinstance(tile_data, dict):
                                tiles_dict[tile_id] = Tile.model_validate(tile_data)
                            elif isinstance(tile_data, Tile):
                                tiles_dict[tile_id] = tile_data
                    logger.info(f"[TILES] Persisting {len(tiles_dict)} tiles to DB")
                    graph_strategy_sections = graph_doc.get("strategy_sections", [])
                    strategy_section_objs = None
                    if graph_strategy_sections:
                        strategy_section_objs = [
                            StrategySection(**s) if isinstance(s, dict) else s
                            for s in graph_strategy_sections
                        ]

                    # Extract NL-extracted settings for deep-merge persistence
                    nl_extracted = updated_session_state.get("metadata", {}).get(
                        "extracted_settings"
                    )

                    updated_doc = await apply_planner_update(
                        db,
                        doc=document,
                        trip_context_id=trip_context_id,
                        trip_inputs=trip_inputs_obj,
                        branches=branch_objs if branch_objs else None,
                        tiles=tiles_dict if tiles_dict else None,
                        # ViewModel fields for session restoration
                        plan_view_state=graph_doc.get("plan_view_state"),
                        strategy_sections=strategy_section_objs,
                        executed_strategy_topics=graph_doc.get("executed_strategy_topics"),
                        pending_strategy_topics=graph_doc.get("pending_strategy_topics"),
                        day_cards=graph_doc.get("day_cards"),
                        can_expand_to_itinerary=graph_doc.get("can_expand_to_itinerary"),
                        extracted_settings=nl_extracted,
                    )
                    if updated_doc:
                        new_document_version = updated_doc.version
                        document_data = get_document_data(updated_doc)

                    # Record assistant message
                    await record_chat_message(
                        db,
                        session=db_session,
                        trip_context=None,
                        role="assistant",
                        content=assistant_message,
                        metadata=None,
                    )

                    await db.commit()
                except Exception as e:
                    logger.error(f"[{request_id}] Failed to persist document: {e}")
                    await db.rollback()

            # Build response document
            response_document = document_data if document_data else PlanDocumentData()
            response_document.assistant_message = assistant_message
            response_document.suggested_responses = suggested_responses
            response_document.ready_to_generate = ready_to_generate_now

            # --- Set change tracking fields for UI receipts ---
            session_metadata = updated_session_state.get("metadata", {})
            response_document.applied_updates = session_metadata.get("turn_applied_fields", [])
            response_document.update_provenance = session_metadata.get("update_provenance")
            if response_document.applied_updates:
                response_document.undo_snapshot = session_metadata.get("prev_trip_inputs_snapshot")

            # --- Build detailed ack_updates for collapsible messages UI ---
            ack_updates = []
            for ui_key in response_document.applied_updates:
                value = _get_trip_input_display_value(ui_key, trip_inputs)
                if value:
                    ack_updates.append(AckUpdate(field=ui_key, to=value))
            response_document.ack_updates = ack_updates

            # --- Check for blocking route violations (Logic Guards) ---
            # Route errors (SAME_CITY_ERROR, UNKNOWN_DESTINATION_ERROR) trigger "rejected" status
            constraint_violations = session_metadata.get("constraint_violations", [])
            route_violation = next(
                (
                    v
                    for v in constraint_violations
                    if v.get("category") == "route" and v.get("severity") == "blocking"
                ),
                None,
            )

            # Set ack_status based on violations or applied updates
            if route_violation:
                # Logic Guard rejection - use amber UI pattern (DS Section 20)
                response_document.ack_status = "rejected"
                response_document.ack_updates = [
                    AckUpdate(field="route", to=route_violation.get("code", "INVALID_ROUTE"))
                ]
            elif ack_updates:
                response_document.ack_status = "applied"
            elif response_document.applied_updates:
                response_document.ack_status = "partial"
            else:
                response_document.ack_status = "no_change"

            # --- Compute Plan State Envelope fields ---
            # Get ui_phase from request (defaults to "bootstrap")
            response_document.ui_phase = req.ui_phase or "bootstrap"

            # Compute readiness from trip_inputs
            readiness = compute_trip_readiness(trip_inputs, errors=final_result.get("errors", []))

            # Build readiness array for frontend
            response_document.readiness = [
                ReadinessItem(key="origin", ok=readiness.has_origin),
                ReadinessItem(key="destination", ok=readiness.has_destination),
                ReadinessItem(key="start_date", ok=readiness.has_dates),
                ReadinessItem(key="end_date", ok=bool(trip_inputs.get("end_date"))),
                ReadinessItem(key="travelers", ok=trip_inputs.get("adults") is not None),
                ReadinessItem(key="budget", ok=trip_inputs.get("budget") is not None),
            ]

            # Compute plan_state from readiness
            if not readiness.core_complete:
                response_document.plan_state = "INCOMPLETE"
            else:
                response_document.plan_state = "STABLE"

            # Build destination_card if destination exists
            dest_name = trip_inputs.get("destination")
            if dest_name:
                # Use async version to actually fetch from Unsplash API
                # Banner image is based on location only, not activities
                dest_image_url = await get_image_for_destination(
                    dest_name, variant=0, db=db, width=1600, height=900
                )
                response_document.destination_card = DestinationCard(
                    title=dest_name,
                    subtitle=f"Your adventure in {dest_name}" if dest_name else None,
                    image_url=dest_image_url,
                )

            # resolver is None at completion (was used during streaming)
            response_document.resolver = None

            # Build booking_status from tiles
            if response_document.tiles:
                flights_count = sum(
                    1 for t in response_document.tiles.values() if t.type == "flight"
                )
                hotels_count = sum(1 for t in response_document.tiles.values() if t.type == "hotel")
                activities_count = sum(
                    1 for t in response_document.tiles.values() if t.type == "activity"
                )
                response_document.booking_status = BookingStatus(
                    flights=BookingStatusItem(
                        state="ready" if flights_count > 0 else "idle",
                        summary=(
                            f"Flights · {flights_count} options"
                            if flights_count
                            else "Flights · not started"
                        ),
                    ),
                    stays=BookingStatusItem(
                        state="ready" if hotels_count > 0 else "idle",
                        summary=(
                            f"Stays · {hotels_count} options"
                            if hotels_count
                            else "Stays · not started"
                        ),
                    ),
                    activities=BookingStatusItem(
                        state="ready" if activities_count > 0 else "idle",
                        summary=(
                            f"Activities · {activities_count} options"
                            if activities_count
                            else "Activities · not started"
                        ),
                    ),
                )

            # --- Graph Output Processing ---
            # Graph generates strategy_sections, plan_view_state, and executed_topics
            graph_document = final_result.get("document", {})
            graph_strategy_sections = graph_document.get("strategy_sections", [])

            # Compute plan_view_state based on actual state (tiles/destination/dates)
            response_document.plan_view_state = graph_document.get(
                "plan_view_state", "S0_BOOTSTRAP"
            )

            # Apply strategy sections if present
            if graph_strategy_sections:
                response_document.strategy_sections = [
                    StrategySection(**section) if isinstance(section, dict) else section
                    for section in graph_strategy_sections
                ]
                response_document.executed_strategy_topics = graph_document.get(
                    "executed_strategy_topics", []
                )
                response_document.pending_strategy_topics = graph_document.get(
                    "pending_strategy_topics", []
                )
                response_document.needs_refresh = False
                response_document.can_expand_to_itinerary = True

            # Apply graph tiles if present - ALWAYS replace DB tiles with fresh graph tiles
            # FIX: Changed from `if graph_tiles and not response_document.tiles` to `if graph_tiles`
            # This ensures destination changes get fresh tiles instead of keeping old DB tiles
            graph_tiles = graph_document.get("tiles", {})
            if graph_tiles:
                response_document.tiles = {
                    tile_id: (
                        Tile.model_validate(tile_data) if isinstance(tile_data, dict) else tile_data
                    )
                    for tile_id, tile_data in graph_tiles.items()
                }

            # Copy origin_just_set flag for frontend flight fetch trigger
            response_document.origin_just_set = graph_document.get("origin_just_set", False)

            _debug(
                f"[MAIN.PY] Graph output: plan_view_state={response_document.plan_view_state}, "
                f"strategy_sections={len(response_document.strategy_sections or [])}, "
                f"tiles={len(response_document.tiles or {})}"
            )

            # Build full response matching GraphPlanResponse
            full_response = {
                "document": (
                    response_document.model_dump()
                    if hasattr(response_document, "model_dump")
                    else response_document
                ),
                "session_state": updated_session_state,
                "version": new_document_version or 1,
                "updated_by": "planner",
                "updated_at": updated_at,
                "changes_made": changes_made,
                "request_id": request_id,
                "observability": {
                    "tokens": {"prompt": 0, "completion": 0, "total": 0},
                    "today_iso": today_iso,
                    "ready_to_generate_now": ready_to_generate_now,
                },
            }

            # DEBUG: Verify strategy_sections in full_response before sending
            doc_in_response = full_response.get("document", {})
            strategy_sections = doc_in_response.get("strategy_sections", [])
            first_id = strategy_sections[0].get("id") if strategy_sections else "none"
            _debug(
                f"[MAIN.PY] SSE complete payload: "
                f"strategy_sections_count={len(strategy_sections)}, "
                f"plan_view_state={doc_in_response.get('plan_view_state')}, "
                f"first_section_id={first_id}"
            )

            complete_payload = json.dumps(
                {"type": "complete", "data": full_response},
                default=str,
            )
            yield f"event: complete\ndata: {complete_payload}\n\n"

        except TimeoutError:
            logger.error(f"[{request_id}] run_turn_streaming timed out")
            timeout_payload = json.dumps({"type": "error", "message": "Request timed out"})
            yield f"event: error\ndata: {timeout_payload}\n\n"
        except Exception as e:
            logger.error(f"[{request_id}] run_turn_streaming failed: {e}")
            error_payload = json.dumps({"type": "error", "message": str(e)})
            yield f"event: error\ndata: {error_payload}\n\n"
        finally:
            _sse_connections[session_key] = max(0, _sse_connections[session_key] - 1)
            _sse_connections[ip_key] = max(0, _sse_connections[ip_key] - 1)

    return StreamingResponse(
        generate_sse(),
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

    # Prune stale checkpoints to prevent memory overflow
    prune_stale_checkpoints()

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
        # Optimistic locking: reject if client's version is stale
        if patch.version != doc.version:
            raise HTTPException(
                status_code=409,
                detail=f"Version mismatch: client={patch.version}, server={doc.version}",
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


@app.post("/api/document/fill-day")
@limiter.limit("10/minute")
async def fill_day_endpoint(
    request: Request,
    body: FillDayRequest,
    db: AsyncSession = async_db_dependency,
):
    """Fill a free day with activity tiles. No LangGraph execution."""
    session_id = get_session_from_request(request)
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

    # Check day is actually free (no non-buffer blocks)
    real_blocks = [b for b in day_card.blocks if not b.is_buffer]
    if real_blocks:
        raise HTTPException(status_code=409, detail=f"Day {body.day_number} already has activities")

    # Determine categories
    categories = body.categories or (
        ti.activity_settings.categories if ti.activity_settings else []
    )
    if not categories:
        raise HTTPException(status_code=400, detail="No activity categories specified")

    # Determine month
    date_str = day_card.date or ti.start_date
    month = date_str[:7] if date_str and len(date_str) >= 7 else "unknown"

    # Generate tiles
    from app.services.experience_generator import generate_experience_tiles_for_day

    budget_int = int(ti.budget) if ti.budget else None
    tiles = await generate_experience_tiles_for_day(
        destination=destination,
        categories=categories,
        month=month,
        day_number=body.day_number,
        budget=budget_int,
        tiles_per_day=3,
    )

    if not tiles:
        return {"day_number": body.day_number, "tiles_added": 0, "version": doc.version}

    # Convert tiles to DayBlocks
    period_cycle = ["morning", "afternoon", "evening"]
    new_blocks = []
    for i, tile in enumerate(tiles[:3]):
        meta = tile.get("meta", {})
        new_blocks.append(
            DayBlock(
                id=tile["id"],
                period=period_cycle[i % 3],
                activity_type=meta.get("category", "activity"),
                intensity="moderate",
                summary=tile.get("title", "Activity")[:60],
            )
        )

    # Preserve buffer blocks, append new activity blocks
    buffer_blocks = [b for b in day_card.blocks if b.is_buffer]
    day_card.blocks = buffer_blocks + new_blocks
    day_card.label = f"Day {body.day_number} — Filled"
    doc_data.day_cards[day_card_idx] = day_card

    # Save
    from app.crud_document import save_document_data

    updated_doc = await save_document_data(db, doc=doc, data=doc_data, updated_by="planner")
    await db.commit()

    return {
        "day_number": body.day_number,
        "tiles_added": len(new_blocks),
        "day_card": day_card.model_dump(),
        "version": updated_doc.version,
    }


# =============================================================================
# Expand Itinerary Endpoint (Stage 2 -> Stage 3)
# =============================================================================

# Simple in-memory idempotency cache (TTL: 5 minutes)
# In production, use Redis with TTL
_idempotency_cache: dict[str, float] = {}
_IDEMPOTENCY_TTL_SECONDS = 300


def _check_idempotency(key: str) -> bool:
    """Check if idempotency key was recently used. Returns True if duplicate."""
    import time

    now = time.time()

    # Clean up old entries
    expired = [k for k, v in _idempotency_cache.items() if now - v > _IDEMPOTENCY_TTL_SECONDS]
    for k in expired:
        del _idempotency_cache[k]

    if key in _idempotency_cache:
        return True  # Duplicate

    _idempotency_cache[key] = now
    return False


@app.post("/api/expand-itinerary")
@limiter.limit("3/minute;15/hour")
async def expand_itinerary_endpoint(
    request: Request,
    req: ExpandItineraryRequest,
):
    """
    Expand strategy into full itinerary (Stage 2 -> Stage 3).

    Streams NDJSON events:
        {"type": "progress", "stage": "itinerary", "message": "...", "pct": 30}
        {"type": "envelope", "plan_envelope": {...}}
        {"type": "done", "plan_view_state": "S3_ITINERARY_READY"}
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
    if _check_idempotency(req.idempotency_key):

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

    async def generate_ndjson():
        """Generator that yields NDJSON events for itinerary generation."""
        # Create fresh database session for this generator
        # (Cannot use FastAPI's injected session - it's closed by the time we run)
        session_factory = _get_async_session_factory()
        async with session_factory() as db:
            try:
                session = await get_session_by_token(db, session_id)
                if not session:
                    event = ExpandItineraryStreamEvent(type="error", message="Session not found")
                    yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                    return

                doc = await get_document(db, session=session)
                if not doc:
                    event = ExpandItineraryStreamEvent(
                        type="error", message="No plan document found"
                    )
                    yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                    return

                doc_data = get_document_data(doc)
                _debug("✅ [expand-itinerary] Session & doc found")

                # Emit progress: starting
                event = ExpandItineraryStreamEvent(
                    type="progress",
                    stage="itinerary",
                    message="Generating itinerary...",
                    pct=10,
                )
                yield json.dumps(event.model_dump(exclude_none=True)) + "\n"

                # Use frontend-provided context if available, else fall back to database
                # This ensures we have the latest strategy_sections from the client
                trip_inputs_data = (
                    req.trip_inputs
                    if req.trip_inputs
                    else (doc_data.trip_inputs.model_dump() if doc_data.trip_inputs else {})
                )
                strategy_sections_data = (
                    req.strategy_sections
                    if req.strategy_sections
                    else (
                        [s.model_dump() for s in doc_data.strategy_sections]
                        if doc_data.strategy_sections
                        else []
                    )
                )

                # Guard: Require at least one strategy section
                # (no specialists = nothing to schedule)
                if not strategy_sections_data:
                    _debug("❌ [expand-itinerary] EARLY RETURN: No strategy sections")
                    event = ExpandItineraryStreamEvent(
                        type="error",
                        message=json.dumps(
                            {
                                "error": "NO_STRATEGY",
                                "message": "Ask about activities before generating itinerary",
                            }
                        ),
                    )
                    yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                    return

                # =================================================================
                # SELECTIVE REGENERATION: Detect strategy based on changed fields
                # =================================================================
                # Compute previous field hashes from document's stored trip_inputs
                # (field_hashes are computed from trip_inputs, not stored separately)
                prev_trip_inputs = doc_data.trip_inputs.model_dump() if doc_data.trip_inputs else {}
                previous_hashes = compute_field_hashes(prev_trip_inputs)

                # Compute current field hashes from request trip_inputs
                current_hashes = compute_field_hashes(trip_inputs_data)

                # Detect which fields changed
                changed_fields = detect_changed_fields(previous_hashes, current_hashes)

                # Compute the regeneration strategy
                regen_strategy = compute_strategy(changed_fields)

                # Force full rebuild if frontend signals structural change (new specialist)
                if req.force_full_rebuild:
                    _debug(
                        "⚡ [expand-itinerary] force_full_rebuild=True - bypassing selective regen"
                    )
                    regen_strategy = RegenStrategy.FULL

                _debug(
                    f"🔄 [expand-itinerary] Selective Regen: "
                    f"strategy={regen_strategy.value}, changed={changed_fields}"
                )

                # For BUILDER strategy, we're already doing the right thing (ItineraryBuilder only)
                # For LOGISTICS/SPECIALISTS/FULL, the frontend would need to trigger graph execution
                # Currently this endpoint only handles BUILDER - log warning for other strategies
                if regen_strategy != RegenStrategy.BUILDER:
                    _debug(
                        f"⚠️ [expand-itinerary] {get_strategy_description(regen_strategy)} "
                        f"- fields changed: {changed_fields}. "
                        f"Note: This endpoint only rebuilds itinerary; "
                        f"tiles/specialists use cached values from last graph run."
                    )

                tiles_count = len(req.tiles) if req.tiles else 0
                _debug(
                    f"📊 [expand-itinerary] Input data: "
                    f"strategy_sections={len(strategy_sections_data)}, "
                    f"destination={trip_inputs_data.get('destination')}, tiles={tiles_count}"
                )
                # Log content_added counts for each section
                for i, section in enumerate(strategy_sections_data):
                    content_count = len(section.get("content_added", []))
                    spec_type = section.get("specialist_type")
                    _debug(
                        f"📦 [expand-itinerary] Section {i}: "
                        f"{spec_type} content_added={content_count}"
                    )
                # Log first section keys for debugging schema issues
                if strategy_sections_data:
                    first_section_keys = list(strategy_sections_data[0].keys())
                    _debug(f"📊 [expand-itinerary] First section keys: {first_section_keys}")

                # NOTE: session_state used to be built here for planner graph
                # but is no longer needed as we build itinerary directly.
                # See CRITICAL comment below for context that was preserved.

                # Emit progress: processing
                event = ExpandItineraryStreamEvent(
                    type="progress",
                    stage="itinerary",
                    message="Building day cards...",
                    pct=30,
                )
                yield json.dumps(event.model_dump(exclude_none=True)) + "\n"

                # Build itinerary using pure Python service (NOT LLM)
                # This is faster and more predictable than run_turn()
                from app.services.itinerary_builder import (
                    ItineraryBuilder,
                    ItineraryBuilderInput,
                    PreferenceOverrideInput,
                )

                # Convert API preferences to builder input format
                preferences_input = None
                if req.preferences:
                    hotel_ids = req.preferences.preferred_hotel_ids or []
                    activity_ids = req.preferences.preferred_activity_ids or []
                    flight_ids = req.preferences.preferred_flight_ids or []
                    _debug(
                        f"🎯 [expand-itinerary] Preferences received: "
                        f"hotels={len(hotel_ids)}, activities={len(activity_ids)}, "
                        f"flights={len(flight_ids)}"
                    )
                    _debug(f"🎯 [expand-itinerary] Hotel IDs: {hotel_ids}")
                    _debug(f"🎯 [expand-itinerary] Activity IDs: {activity_ids}")
                    _debug(f"🎯 [expand-itinerary] Flight IDs: {flight_ids}")
                    preferences_input = PreferenceOverrideInput(
                        preferred_hotel_ids=hotel_ids,
                        preferred_activity_ids=activity_ids,
                        preferred_flight_ids=flight_ids,
                    )
                else:
                    _debug("🎯 [expand-itinerary] No preferences in request")

                # Validate dates - require both start and end for multi-day trips
                start_date = trip_inputs_data.get("start_date")
                end_date = trip_inputs_data.get("end_date")

                # Guard: Require both dates (S0_BOOTSTRAP has neither)
                if not start_date or not end_date:
                    _debug(
                        f"❌ [expand-itinerary] EARLY RETURN: Missing dates "
                        f"(start={start_date}, end={end_date})"
                    )
                    event = ExpandItineraryStreamEvent(
                        type="error",
                        message=json.dumps(
                            {
                                "error": "MISSING_DATES",
                                "message": "Set travel dates to generate itinerary",
                            }
                        ),
                    )
                    yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                    return

                # Guard: Minimum 2-day trip (generates hotel booking, enables constraints)
                if start_date and end_date:
                    from datetime import datetime as dt

                    try:
                        start_dt = dt.fromisoformat(start_date.split("T")[0])
                        end_dt = dt.fromisoformat(end_date.split("T")[0])
                        trip_days = (end_dt - start_dt).days + 1
                        if trip_days < 2:
                            _debug(
                                f"❌ [expand-itinerary] EARLY RETURN: "
                                f"Trip too short: {trip_days} days"
                            )
                            event = ExpandItineraryStreamEvent(
                                type="error",
                                message=json.dumps(
                                    {
                                        "error": "TRIP_TOO_SHORT",
                                        "message": "Trip must be at least 2 days",
                                        "current_days": trip_days,
                                        "minimum_days": 2,
                                    }
                                ),
                            )
                            yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                            return
                    except (ValueError, AttributeError) as e:
                        logger.warning(f"❌ [expand-itinerary] Date parsing error: {e}")

                _debug(
                    f"🔥 [expand-itinerary] BUILDER CALLED: "
                    f"start={start_date}, end={end_date}, "
                    f"sections={len(strategy_sections_data)}, tiles={tiles_count}"
                )

                builder = ItineraryBuilder()
                activity_categories = trip_inputs_data.get("activity_settings", {}).get(
                    "categories"
                )
                day_preferences = trip_inputs_data.get("activity_settings", {}).get(
                    "day_preferences"
                )
                builder_input = ItineraryBuilderInput(
                    start_date=start_date,
                    end_date=end_date,
                    strategy_sections=strategy_sections_data,
                    tiles=req.tiles or {},
                    destination=trip_inputs_data.get("destination"),
                    origin=trip_inputs_data.get("origin"),
                    preferences=preferences_input,
                    activity_categories=activity_categories,
                    activity_day_preferences=day_preferences,
                )

                try:
                    itinerary_result = builder.build(builder_input)
                    _debug(
                        f"✅ [expand-itinerary] Builder result: "
                        f"success={itinerary_result.success}, "
                        f"day_cards={len(itinerary_result.day_cards)}, "
                        f"conflicts={len(itinerary_result.conflicts)}"
                    )
                except Exception as e:
                    logger.exception(f"Itinerary builder failed: {e}")
                    event = ExpandItineraryStreamEvent(
                        type="error", message=f"Itinerary generation failed: {str(e)}"
                    )
                    yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                    return

                # Handle conflicts - return error response with resolutions AND partial schedule
                if not itinerary_result.success:
                    if itinerary_result.conflicts:
                        # NEW: Include partial day_cards in conflict response
                        # Partial schedule shows what CAN be scheduled + unschedulable markers
                        partial_day_cards = (
                            [dc.model_dump() for dc in itinerary_result.day_cards]
                            if itinerary_result.day_cards
                            else []
                        )
                        _debug(
                            f"⚠️ [expand-itinerary] Conflict with partial schedule: "
                            f"conflicts={len(itinerary_result.conflicts)}, "
                            f"partial_day_cards={len(partial_day_cards)}"
                        )

                        # Emit partial schedule envelope FIRST (so frontend can render it)
                        if partial_day_cards:
                            partial_envelope = {
                                "day_cards": partial_day_cards,
                                "plan_view_state": "S3_PARTIAL_CONFLICT",
                            }
                            partial_event = ExpandItineraryStreamEvent(
                                type="envelope",
                                plan_envelope=partial_envelope,
                            )
                            yield json.dumps(partial_event.model_dump(exclude_none=True)) + "\n"

                        # Emit conflict response for frontend to handle
                        conflict_data = {
                            "error": "CONSTRAINT_CONFLICT",
                            "conflicts": [c.model_dump() for c in itinerary_result.conflicts],
                            "resolutions": [r.model_dump() for r in itinerary_result.resolutions],
                            "day_cards": partial_day_cards,  # Include in conflict data too
                        }
                        event = ExpandItineraryStreamEvent(
                            type="error",
                            message=json.dumps(conflict_data),
                        )
                        yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                        return
                    else:
                        event = ExpandItineraryStreamEvent(
                            type="error",
                            message=itinerary_result.error or "Itinerary generation failed",
                        )
                        yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                        return

                # Emit progress: finalizing
                event = ExpandItineraryStreamEvent(
                    type="progress",
                    stage="itinerary",
                    message="Finalizing itinerary...",
                    pct=80,
                )
                yield json.dumps(event.model_dump(exclude_none=True)) + "\n"

                # Build metadata from itinerary result
                # CRITICAL: Include strategy_stage=3 so _compute_plan_view_state
                # returns S3_ITINERARY_READY
                metadata = {
                    "strategy_stage": 3,  # Force stage 3 for proper state computation
                    "day_cards": [dc.model_dump() for dc in itinerary_result.day_cards],
                    "itinerary_overview": (
                        itinerary_result.overview.model_dump()
                        if itinerary_result.overview
                        else None
                    ),
                    "strategy_sections": strategy_sections_data,
                }
                trip_inputs = trip_inputs_data

                # Build envelope update
                plan_envelope = {}

                # Add itinerary fields if present
                if "day_cards" in metadata:
                    plan_envelope["day_cards"] = metadata["day_cards"]
                if "itinerary_overview" in metadata:
                    plan_envelope["itinerary_overview"] = metadata["itinerary_overview"]
                if "itinerary_assumptions" in metadata:
                    plan_envelope["itinerary_assumptions"] = metadata["itinerary_assumptions"]

                # CRITICAL: Builder success = S3_ITINERARY_READY (bypass gate check)
                # The gate check in _compute_plan_view_state may fail if trip_inputs
                # is incomplete, but builder success already proves we have valid dates.
                new_plan_view_state: PlanViewState = "S3_ITINERARY_READY"
                plan_envelope["plan_view_state"] = new_plan_view_state

                # Emit envelope update
                _debug(
                    f"📤 [expand-itinerary] Emitting envelope: "
                    f"day_cards={len(plan_envelope.get('day_cards', []))}, "
                    f"plan_view_state={new_plan_view_state}"
                )
                event = ExpandItineraryStreamEvent(
                    type="envelope",
                    plan_envelope=plan_envelope,
                )
                yield json.dumps(event.model_dump(exclude_none=True)) + "\n"

                # Persist to document if we have itinerary data
                if plan_envelope.get("day_cards"):
                    try:
                        from app.schemas import DocumentTripInputs

                        # Convert trip_inputs to DocumentTripInputs
                        trip_inputs_obj = None
                        if trip_inputs:
                            trip_inputs_obj = DocumentTripInputs.model_validate(trip_inputs)

                        # Get trip context
                        trip_context = await get_latest_trip_context_for_session(
                            db, session=session
                        )
                        trip_context_id = trip_context.id if trip_context else 0

                        # Convert day_cards to DayCard objects for persistence
                        day_card_objs = None
                        if plan_envelope.get("day_cards"):
                            from app.schemas import DayCard

                            day_card_objs = [
                                DayCard(**dc) if isinstance(dc, dict) else dc
                                for dc in plan_envelope["day_cards"]
                            ]

                        await apply_planner_update(
                            db,
                            doc=doc,
                            trip_context_id=trip_context_id,
                            trip_inputs=trip_inputs_obj,
                            # ViewModel fields for session restoration
                            plan_view_state=new_plan_view_state,
                            day_cards=day_card_objs,
                            can_expand_to_itinerary=True,
                        )
                        await db.commit()
                    except Exception as e:
                        logger.warning(f"Failed to persist itinerary: {e}")

                # Emit done with version for frontend sync (prevents 409 on next PATCH)
                event = ExpandItineraryStreamEvent(
                    type="done",
                    plan_view_state=new_plan_view_state,
                    version=doc.version if doc else None,
                    dropped_preferred_count=itinerary_result.dropped_preferred_count or None,
                    warnings=itinerary_result.warnings if itinerary_result.warnings else None,
                )
                yield json.dumps(event.model_dump(exclude_none=True)) + "\n"

            except Exception as e:
                logger.exception(f"Error in expand-itinerary: {e}")
                event = ExpandItineraryStreamEvent(
                    type="error", message=str(e) or "Failed to generate itinerary"
                )
                yield json.dumps(event.model_dump(exclude_none=True)) + "\n"

    return StreamingResponse(
        generate_ndjson(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# =============================================================================
# Remove Specialist Endpoint (Conflict Resolution - Focus on One)
# =============================================================================


@app.post("/api/remove-specialist")
@limiter.limit("3/minute;15/hour")
async def remove_specialist_endpoint(
    request: Request,
    req: RemoveSpecialistRequest,
):
    """
    Remove specialists and regenerate itinerary (conflict resolution).

    When ItineraryBuilder detects a constraint conflict (e.g., diving + hiking
    in 4 days), user can choose "Focus on diving". This endpoint:
    1. Removes other specialists from executed_strategy_topics
    2. Filters strategy_sections to keep only the kept specialist
    3. Clears day_cards (they'll be regenerated)
    4. Re-runs ItineraryBuilder with the simplified plan

    Streams NDJSON events (same format as expand-itinerary):
        {"type": "progress", "stage": "itinerary", "message": "...", "pct": 30}
        {"type": "envelope", "plan_envelope": {...}}
        {"type": "done", "plan_view_state": "S3_ITINERARY_READY"}
        {"type": "error", "message": "..."}
    """
    # Check idempotency
    if _check_idempotency(req.idempotency_key):

        async def duplicate_response():
            event = ExpandItineraryStreamEvent(
                type="error",
                message="Duplicate request - specialist removal already in progress",
            )
            yield json.dumps(event.model_dump(exclude_none=True)) + "\n"

        return StreamingResponse(
            duplicate_response(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    session_id = get_session_from_request(request)

    async def generate_ndjson():
        """Generator that yields NDJSON events for specialist removal + regeneration."""
        session_factory = _get_async_session_factory()
        async with session_factory() as db:
            try:
                session = await get_session_by_token(db, session_id)
                if not session:
                    event = ExpandItineraryStreamEvent(type="error", message="Session not found")
                    yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                    return

                doc = await get_document(db, session=session)
                if not doc:
                    event = ExpandItineraryStreamEvent(
                        type="error", message="No plan document found"
                    )
                    yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                    return

                doc_data = get_document_data(doc)
                _debug(f"✅ [remove-specialist] Keeping: {req.keep_specialist}")

                # Emit progress: starting
                event = ExpandItineraryStreamEvent(
                    type="progress",
                    stage="itinerary",
                    message=f"Focusing on {req.keep_specialist}...",
                    pct=10,
                )
                yield json.dumps(event.model_dump(exclude_none=True)) + "\n"

                # Get trip inputs - use frontend-provided or fall back to DB
                trip_inputs_data = (
                    req.trip_inputs
                    if req.trip_inputs
                    else (doc_data.trip_inputs.model_dump() if doc_data.trip_inputs else {})
                )

                # Filter strategy_sections to keep only the specified specialist
                strategy_sections_data = (
                    req.strategy_sections
                    if req.strategy_sections
                    else (
                        [s.model_dump() for s in doc_data.strategy_sections]
                        if doc_data.strategy_sections
                        else []
                    )
                )

                # Filter to kept specialist
                kept_specialist = req.keep_specialist.lower()
                filtered_sections = [
                    s
                    for s in strategy_sections_data
                    if s.get("specialist_type", "").lower() == kept_specialist
                    or s.get("specialist_type", "").lower() == "general"
                ]

                _debug(
                    f"📊 [remove-specialist] Filtered sections: "
                    f"{len(strategy_sections_data)} -> {len(filtered_sections)}"
                )

                if not filtered_sections:
                    event = ExpandItineraryStreamEvent(
                        type="error",
                        message=f"No strategy sections found for {req.keep_specialist}",
                    )
                    yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                    return

                # Emit progress: filtering complete
                event = ExpandItineraryStreamEvent(
                    type="progress",
                    stage="itinerary",
                    message="Building simplified timeline...",
                    pct=30,
                )
                yield json.dumps(event.model_dump(exclude_none=True)) + "\n"

                # Filter tiles to kept specialist if requested
                tiles_data = req.tiles or {}
                if req.remove_hearted_tiles:
                    # Filter out tiles from removed specialists
                    # For now, tiles don't have specialist_type, so we keep all
                    # Future: filter based on tile.source_specialist if available
                    pass

                # Build itinerary using ItineraryBuilder
                from app.services.itinerary_builder import (
                    ItineraryBuilder,
                    ItineraryBuilderInput,
                    PreferenceOverrideInput,
                )

                # Convert API preferences to builder input format
                preferences_input = None
                if req.preferences:
                    preferences_input = PreferenceOverrideInput(
                        preferred_hotel_ids=req.preferences.preferred_hotel_ids or [],
                        preferred_activity_ids=req.preferences.preferred_activity_ids or [],
                        preferred_flight_ids=req.preferences.preferred_flight_ids or [],
                    )

                # Validate dates
                start_date = trip_inputs_data.get("start_date")
                end_date = trip_inputs_data.get("end_date")

                if start_date and not end_date:
                    event = ExpandItineraryStreamEvent(
                        type="error",
                        message=json.dumps(
                            {
                                "error": "MISSING_END_DATE",
                                "message": "Add return date to see itinerary",
                            }
                        ),
                    )
                    yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                    return

                builder = ItineraryBuilder()
                activity_categories = trip_inputs_data.get("activity_settings", {}).get(
                    "categories"
                )
                day_preferences = trip_inputs_data.get("activity_settings", {}).get(
                    "day_preferences"
                )
                builder_input = ItineraryBuilderInput(
                    start_date=start_date,
                    end_date=end_date,
                    strategy_sections=filtered_sections,
                    tiles=tiles_data,
                    destination=trip_inputs_data.get("destination"),
                    origin=trip_inputs_data.get("origin"),
                    preferences=preferences_input,
                    activity_categories=activity_categories,
                    activity_day_preferences=day_preferences,
                )

                try:
                    itinerary_result = builder.build(builder_input)
                    _debug(
                        f"✅ [remove-specialist] Builder result: "
                        f"success={itinerary_result.success}, "
                        f"day_cards={len(itinerary_result.day_cards)}"
                    )
                except Exception as e:
                    logger.exception(f"Itinerary builder failed: {e}")
                    event = ExpandItineraryStreamEvent(
                        type="error", message=f"Itinerary generation failed: {str(e)}"
                    )
                    yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                    return

                # Handle any remaining conflicts
                if not itinerary_result.success:
                    if itinerary_result.conflicts:
                        # Include partial day_cards in conflict response
                        partial_day_cards = (
                            [dc.model_dump() for dc in itinerary_result.day_cards]
                            if itinerary_result.day_cards
                            else []
                        )
                        conflict_data = {
                            "error": "CONSTRAINT_CONFLICT",
                            "conflicts": [c.model_dump() for c in itinerary_result.conflicts],
                            "resolutions": [r.model_dump() for r in itinerary_result.resolutions],
                            "day_cards": partial_day_cards,
                        }
                        event = ExpandItineraryStreamEvent(
                            type="error",
                            message=json.dumps(conflict_data),
                        )
                        yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                        return
                    else:
                        event = ExpandItineraryStreamEvent(
                            type="error",
                            message=itinerary_result.error or "Itinerary generation failed",
                        )
                        yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                        return

                # Emit progress: finalizing
                event = ExpandItineraryStreamEvent(
                    type="progress",
                    stage="itinerary",
                    message="Finalizing itinerary...",
                    pct=80,
                )
                yield json.dumps(event.model_dump(exclude_none=True)) + "\n"

                # Build envelope update with filtered topics
                filtered_topics = [kept_specialist]
                new_plan_view_state = "S3_ITINERARY_READY"

                plan_envelope = {
                    "day_cards": [dc.model_dump() for dc in itinerary_result.day_cards],
                    "itinerary_overview": (
                        itinerary_result.overview.model_dump()
                        if itinerary_result.overview
                        else None
                    ),
                    "strategy_sections": filtered_sections,
                    "executed_strategy_topics": filtered_topics,
                    "plan_view_state": new_plan_view_state,
                }

                # Emit envelope update
                _debug(
                    f"📤 [remove-specialist] Emitting envelope: "
                    f"day_cards={len(plan_envelope.get('day_cards', []))}"
                )
                event = ExpandItineraryStreamEvent(
                    type="envelope",
                    plan_envelope=plan_envelope,
                )
                yield json.dumps(event.model_dump(exclude_none=True)) + "\n"

                # Persist to document
                try:
                    from app.schemas import DocumentTripInputs

                    trip_inputs_obj = None
                    if trip_inputs_data:
                        trip_inputs_obj = DocumentTripInputs.model_validate(trip_inputs_data)

                    trip_context = await get_latest_trip_context_for_session(db, session=session)
                    trip_context_id = trip_context.id if trip_context else 0

                    day_card_objs = None
                    if plan_envelope.get("day_cards"):
                        from app.schemas import DayCard

                        day_card_objs = [
                            DayCard(**dc) if isinstance(dc, dict) else dc
                            for dc in plan_envelope["day_cards"]
                        ]

                    strategy_section_objs = None
                    if filtered_sections:
                        strategy_section_objs = [
                            StrategySection(**s) if isinstance(s, dict) else s
                            for s in filtered_sections
                        ]

                    await apply_planner_update(
                        db,
                        doc=doc,
                        trip_context_id=trip_context_id,
                        trip_inputs=trip_inputs_obj,
                        plan_view_state=new_plan_view_state,
                        day_cards=day_card_objs,
                        strategy_sections=strategy_section_objs,
                        executed_strategy_topics=filtered_topics,
                        can_expand_to_itinerary=True,
                    )
                    await db.commit()
                except Exception as e:
                    logger.warning(f"Failed to persist specialist removal: {e}")

                # Emit done with version for frontend sync (prevents 409 on next PATCH)
                event = ExpandItineraryStreamEvent(
                    type="done",
                    plan_view_state=new_plan_view_state,
                    version=doc.version if doc else None,
                    dropped_preferred_count=itinerary_result.dropped_preferred_count or None,
                    warnings=itinerary_result.warnings if itinerary_result.warnings else None,
                )
                yield json.dumps(event.model_dump(exclude_none=True)) + "\n"

            except Exception as e:
                logger.exception(f"Error in remove-specialist: {e}")
                event = ExpandItineraryStreamEvent(
                    type="error", message=str(e) or "Failed to remove specialist"
                )
                yield json.dumps(event.model_dump(exclude_none=True)) + "\n"

    return StreamingResponse(
        generate_ndjson(),
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
