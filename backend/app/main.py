import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

import app.db_models as db_models
import app.schemas as schemas
from app.config import settings
from app.crud_document import (
    add_tiles_to_branch,
    apply_planner_update,
    apply_user_patch,
    get_document,
    get_document_data,
    get_or_create_document,
)
from app.crud_trip import (
    delete_messages_from_id,
    fetch_chat_history,
    get_last_user_message,
    get_latest_trip_context_for_session,
    get_or_create_session,
    get_session_by_token,
    get_session_by_token_sync,
    record_chat_message,
)
from app.db import get_async_db, get_db
from app.graph_plan_utils import (
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
from app.middleware import (
    CSRFMiddleware,
    SessionMiddleware,
    clear_session_cookies,
    get_session_from_request,
)
from app.planner import (
    CACHE_SCHEMA_VERSION,
    PLANNER_BUILD_ID,
    PROMPT_BUNDLE_HASH,
    TRACE_ENVELOPE,
    GateEvaluator,
    GraphState,
    TripInputs,
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
from app.planner.gates import compute_trip_readiness
from app.schemas import (
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
    StrategySection,
    TileRefreshRequest,
    TileRefreshResponse,
    TilesSearchRequest,
    TripInputValidationRequest,
    TripInputValidationResponse,
)
from app.services.unsplash import (
    clear_db_cache as clear_unsplash_db_cache,
)
from app.services.unsplash import (
    clear_memory_cache as clear_unsplash_memory_cache,
)
from app.services.unsplash import (
    get_image_for_destination,
)
from app.services.unsplash import (
    get_memory_cache_stats as get_unsplash_memory_stats,
)
from app.tile_service.service import search_tiles
from app.validation import (
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
    destinations = trip_inputs.get("destinations", [])
    start_date = trip_inputs.get("start_date")
    # end_date is NOT required for S2 - strategy can be shown without it
    return not destinations or not start_date


def _check_stage3_gate(metadata: dict, trip_inputs: dict) -> bool:
    """Stage 3 hard gate - all must be true for S3_ITINERARY_READY."""
    open_decisions = metadata.get("open_decisions", [])
    blocking_count = sum(1 for d in open_decisions if d.get("is_blocking"))

    # Use bool() to ensure we return True/False, not the truthy/falsy value itself
    # (e.g., empty list [] should return False, not [])
    return bool(
        blocking_count == 0
        and trip_inputs.get("destinations")
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
                    bullets=s.get("bullets", [])[:6],  # Max 6 bullets
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
        destinations = trip_inputs.get("destinations", [])
        return ", ".join(destinations) if destinations else None
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
    return None


def _populate_plan_view_state_fields(
    response_document: PlanDocumentData,
    metadata: dict,
    trip_inputs: dict,
) -> None:
    """
    Populate plan view state machine fields on the response document.

    This is called at the end of request processing to set:
    - plan_view_state
    - strategy_sections (S2)
    - open_decisions (S2)
    - itinerary_overview (S3)
    - day_cards (S3)
    - itinerary_assumptions (S3)
    - needs_refresh
    - can_expand_to_itinerary
    """
    # Compute plan view state
    plan_view_state = _compute_plan_view_state(metadata, trip_inputs)
    response_document.plan_view_state = plan_view_state

    # Populate S2 fields
    if plan_view_state in ("S2_STRATEGY_READY", "S2_BLOCKED"):
        response_document.strategy_sections = _build_strategy_sections(metadata)
        response_document.open_decisions = _build_open_decisions(metadata)

    # Populate S3 fields
    if plan_view_state in ("S3_ITINERARY_READY", "S3_EDITING", "S3_BLOCKED"):
        response_document.itinerary_overview = _build_itinerary_overview(metadata)
        response_document.day_cards = _build_day_cards(metadata)
        response_document.itinerary_assumptions = _build_itinerary_assumptions(metadata)

    # Set flags
    response_document.needs_refresh = metadata.get("needs_refresh", False)
    response_document.can_expand_to_itinerary = _check_stage3_gate(metadata, trip_inputs)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan hooks.

    Used instead of deprecated @app.on_event handlers.
    Pre-warms caches and compiles templates to eliminate cold-start latency.
    Validates template coverage at startup - fails fast on mismatch.
    """
    # Log build info for cache debugging
    logger.info(
        "[Startup] Build info: prompt_bundle_hash=%s, planner_build_id=%s, cache_schema_version=%s",
        PROMPT_BUNDLE_HASH,
        PLANNER_BUILD_ID,
        CACHE_SCHEMA_VERSION,
    )
    print(
        f"[Startup] prompt_bundle_hash={PROMPT_BUNDLE_HASH}, "
        f"planner_build_id={PLANNER_BUILD_ID}, cache_schema_version={CACHE_SCHEMA_VERSION}"
    )

    # Prewarm validation cache
    validation_count = prewarm_cache()
    print(f"[Validation] Pre-warmed cache with {validation_count} entries")

    # Prewarm prompts and templates (Jinja2 compilation)
    warmup_stats = prewarm_prompts()
    print(
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
        print(error_msg)
        raise RuntimeError(error_msg)
    print(
        f"[Startup] Template coverage validation passed "
        f"(insufficient_suggestions={template_validation.get('insufficient_suggestions', {})})"
    )

    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# Sync DB dependency for legacy endpoints and migrations
db_dependency = Depends(get_db)
# Async DB dependency for async endpoints
async_db_dependency = Depends(get_async_db)


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


@app.post("/v1/validate-trip-input", response_model=TripInputValidationResponse)
async def validate_trip_input(req: TripInputValidationRequest, request: Request):
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


@app.post("/v1/destination-image", response_model=DestinationImageResponse)
async def get_destination_image(req: DestinationImageRequest, db: AsyncSession = db_dependency):
    """
    Get the Unsplash image URL for a destination.

    Called when user selects a destination to show the correct banner image
    immediately, without waiting for plan generation.
    """
    dest_name = req.destination.strip()
    if not dest_name:
        raise HTTPException(status_code=400, detail="Destination is required")

    image_url = await get_image_for_destination(dest_name, variant=0, db=db, width=1600, height=900)

    return DestinationImageResponse(
        image_url=image_url,
        destination=dest_name,
    )


@app.post("/v1/admin/clear-validation-cache")
def admin_clear_validation_cache():
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


@app.post("/v1/admin/fresh-start")
def admin_fresh_start():
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
    response_cleared = clear_response_caches()

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


@app.get("/v1/admin/graph-stats")
def admin_graph_stats():
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


@app.get("/v1/admin/planner")
def admin_planner_debug():
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


@app.post("/v1/admin/clear-all-checkpoints")
def admin_clear_all_checkpoints():
    """
    Clear ALL LangGraph checkpoints regardless of age.

    Use with caution - this will clear all in-progress session states.
    For emergency maintenance only.
    """
    before = checkpoint_stats()
    cleared = clear_all_checkpoints()
    return {
        "cleared": cleared,
        "before": before,
        "after": checkpoint_stats(),
    }


@app.post("/v1/admin/clear-all-caches")
async def admin_clear_all_caches(db: AsyncSession = async_db_dependency):
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

    # 5. Summary
    total = planner_cleared + unsplash_memory_count + unsplash_db_count
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


@app.post("/v1/admin/gate-trace")
def admin_gate_trace(request_body: schemas.GateTraceRequest):
    """
    P2: Debug endpoint that shows gate evaluation trace without executing the graph.

    Evaluates all gates for the provided state and returns detailed trace information
    showing which gates were checked, which fired, and why.

    This is useful for debugging routing issues without modifying state.

    Request body:
        user_text: str - The user message to evaluate
        trip_inputs: dict - Current trip inputs (destinations, dates, etc.)
        metadata: dict - Optional metadata (thread_id, today_iso, etc.)
        turn_number: int - Current turn number (default 0)

    Response:
        gate_fired: str - Name of the gate that matched
        destination: str - Node that would be routed to
        reason: str - Human-readable explanation
        gate_trace: list - Detailed trace of all gates evaluated
        eval_time_ms: float - Time taken to evaluate gates
    """
    from datetime import date

    # Build trip inputs from request
    trip_inputs_dict = request_body.trip_inputs or {}
    trip_inputs = TripInputs(**trip_inputs_dict)

    # Build metadata with defaults
    metadata = request_body.metadata or {}
    if "thread_id" not in metadata:
        metadata["thread_id"] = "gate_trace_debug"
    if "today_iso" not in metadata:
        metadata["today_iso"] = date.today().isoformat()

    # Create minimal state for gate evaluation
    state = GraphState(
        user_text=request_body.user_text,
        trip_inputs=trip_inputs,
        metadata=metadata,
        turn_number=request_body.turn_number,
    )

    # Evaluate gates
    gate_result = GateEvaluator.evaluate(state)

    # Extract gate trace from metadata
    gate_trace = state.metadata.get("gate_trace", [])

    return {
        "gate_fired": gate_result.gate_fired.name if gate_result.gate_fired else None,
        "gate_precedence": gate_result.gate_fired.value if gate_result.gate_fired else None,
        "destination": gate_result.destination,
        "reason": gate_result.reason,
        "gate_trace": gate_trace,
        "eval_time_ms": round(gate_result.eval_time_ms, 3),
        "intent": gate_result.intent,
        "strategy_topic": gate_result.strategy_topic,
        "question_target": gate_result.question_target,
        "skipped_gates": gate_result.skipped_gates,
        "metadata_updates": gate_result.metadata_updates,
    }


@app.post("/v1/tiles/click")
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


@app.post("/v1/suggestions/click")
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


@app.post("/v1/graph_plan", response_model=GraphPlanResponse)
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

    # --- Initialize trip_inputs if not present ---
    if "trip_inputs" not in session_state:
        raw_inputs = dict(req.trip_inputs) if req.trip_inputs else {}
        session_state["trip_inputs"] = normalize_trip_inputs(raw_inputs)

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
            if document_data.trip_inputs:
                # Document trip_inputs override session trip_inputs (document is source of truth)
                session_state["trip_inputs"] = document_data.trip_inputs.model_dump()
    except HTTPException:
        raise  # Re-raise HTTP exceptions (like version conflict)
    except Exception as e:
        logger.warning(f"[{request_id}] Failed to load document for session: {e}")
        # Continue without document - not fatal

    # Note: We intentionally do not reject relative date phrases (e.g., "next week").
    # The planner should handle them contextually using today_iso.

    # --- Emit telemetry request start ---
    request_start_ns = emit_request_start(trace_envelope, req.message)

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
            f"[{request_id}] Route timeout after {route_timeout_seconds}s "
            f"(session_id={session_id})"
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

            # Apply planner update
            updated_doc = await apply_planner_update(
                db,
                doc=document,
                trip_context_id=trip_context_id,
                trip_inputs=trip_inputs_obj,
                branches=branch_objs if branch_objs else None,
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
    # Set ack_status based on whether updates were applied
    if ack_updates:
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
        ReadinessItem(key="destination", ok=readiness.has_destinations),
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
    destinations = trip_inputs.get("destinations", [])
    if destinations and len(destinations) > 0:
        dest_name = destinations[0]
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

    # --- Compute Plan View State Machine fields ---
    _populate_plan_view_state_fields(
        response_document=response_document,
        metadata=session_metadata,
        trip_inputs=trip_inputs,
    )

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


@app.post("/v1/graph_plan/stream")
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

    # --- Initialize trip_inputs if not present ---
    if "trip_inputs" not in session_state:
        raw_inputs = dict(req.trip_inputs) if req.trip_inputs else {}
        session_state["trip_inputs"] = normalize_trip_inputs(raw_inputs)

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
                        "destinations": ti.destinations or [],
                        "origin": ti.origin,
                        "start_date": ti.start_date,
                        "end_date": ti.end_date,
                        "adults": ti.adults,
                        "children": ti.children,
                        "requires_assistance": ti.requires_assistance,
                        "budget": ti.budget,
                        "currency": ti.currency,
                        "multi_city_intent": ti.multi_city_intent,
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
                    if document_data.trip_inputs:
                        session_state["trip_inputs"] = document_data.trip_inputs.model_dump()
            except Exception as e:
                logger.warning(f"[{request_id}] Failed to load document for session: {e}")

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

                    # Extract tiles from session state metadata (generated by tile_search node)
                    tiles_from_metadata = updated_session_state.get("metadata", {}).get("tiles", {})
                    tiles_dict = {}
                    if tiles_from_metadata:
                        for tile_id, tile_data in tiles_from_metadata.items():
                            if isinstance(tile_data, dict):
                                tiles_dict[tile_id] = Tile.model_validate(tile_data)

                    trip_context = await get_latest_trip_context_for_session(db, session=db_session)
                    trip_context_id = trip_context.id if trip_context else 0

                    updated_doc = await apply_planner_update(
                        db,
                        doc=document,
                        trip_context_id=trip_context_id,
                        trip_inputs=trip_inputs_obj,
                        branches=branch_objs if branch_objs else None,
                        tiles=tiles_dict if tiles_dict else None,
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
            if ack_updates:
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
                ReadinessItem(key="destination", ok=readiness.has_destinations),
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
            destinations = trip_inputs.get("destinations", [])
            if destinations and len(destinations) > 0:
                dest_name = destinations[0]
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

            # --- Compute Plan View State Machine fields ---
            _populate_plan_view_state_fields(
                response_document=response_document,
                metadata=session_metadata,
                trip_inputs=trip_inputs,
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

    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@app.delete("/v1/session", status_code=204)
def reset_session(
    request: Request,
    db: Session = db_dependency,
):
    """
    Reset/delete a planning session and all associated data.

    Uses row-level locking to prevent deadlocks with concurrent plan operations.
    Also clears session cookies from the browser and LangGraph checkpoint state.
    """
    session_id = get_session_from_request(request)

    # Clear LangGraph checkpoint for this session (even if session not in DB)
    if session_id:
        clear_session_checkpoint(session_id)

    # Clear response caches (or all caches in dev mode)
    if settings.aggressive_cache_clear:
        clear_all_caches()  # Clear everything including validation caches
    else:
        clear_response_caches()  # Preserve validation cache in production

    # Prune stale checkpoints to prevent memory overflow
    prune_stale_checkpoints()

    # Lock the session row first to prevent deadlocks with concurrent operations
    session = get_session_by_token_sync(db, session_id, lock_for_update=True)
    if not session:
        # Clear cookies even if session not found in DB
        response = Response(status_code=204)
        return clear_session_cookies(response)

    # Delete PlanDocument for this session
    (
        db.query(db_models.PlanDocument)
        .filter(db_models.PlanDocument.session_id == session.id)
        .delete(synchronize_session=False)
    )

    # Delete ChatMessages for this session
    (
        db.query(db_models.ChatMessage)
        .filter(db_models.ChatMessage.session_id == session.id)
        .delete(synchronize_session=False)
    )

    # Delete TripContexts for this session
    (
        db.query(db_models.TripContext)
        .filter(db_models.TripContext.session_id == session.id)
        .delete(synchronize_session=False)
    )

    # Delete TileClicks for this session
    (
        db.query(db_models.TileClick)
        .filter(db_models.TileClick.session_id == session_id)
        .delete(synchronize_session=False)
    )

    # Delete the session itself
    db.delete(session)
    db.commit()

    # Clear cookies from browser
    response = Response(status_code=204)
    return clear_session_cookies(response)


# ─────────────────────────────────────────────────────────────────────────────
# Chat History Endpoint
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/v1/chat", response_model=ChatHistoryResponse)
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


@app.delete("/v1/chat/last", response_model=DeleteLastMessageResponse)
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


@app.get("/v1/document", response_model=PlanDocumentResponse)
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


@app.patch("/v1/document", response_model=PlanDocumentResponse)
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
    session = await get_session_by_token(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    doc = await get_document(db, session=session)
    if not doc:
        raise HTTPException(status_code=404, detail="No plan document for this session")

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
        if "destinations" in fields_set:
            dests = getattr(trip_patch, "destinations", None)
            if dests is not None:
                if len(dests) == 0:
                    changes.append("cleared all destinations")
                else:
                    changes.append(f"set destinations to {dests}")
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


@app.post("/v1/document/tiles/{branch_id}", response_model=PlanDocumentResponse)
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

    # Check if branch already has tiles
    has_tiles = bool(branch.tiles.stays or branch.tiles.flights or branch.tiles.activities)
    if has_tiles:
        # Return current document without refetching
        return PlanDocumentResponse(
            version=doc.version,
            updated_by=doc.updated_by,
            document=doc_data,
            updated_at=doc.updated_at.isoformat(),
            changes_made=False,
        )

    # Fetch tiles for this branch
    primary_dest = branch.destinations[0] if branch.destinations else None
    ti = doc_data.trip_inputs
    tiles_request = TilesSearchRequest(
        session_id=session_id,
        destination=primary_dest,
        destination_hint=primary_dest,
        origin=branch.origin,
        start_date=branch.start_date,
        end_date=branch.end_date,
        adults=branch.adults,
        children=branch.children,
        requires_assistance=branch.requires_assistance,
        # Pass user preference settings for filtering
        flight_settings=ti.flight_settings,
        hotel_settings=ti.hotel_settings,
        activity_settings=ti.activity_settings,
    )

    tiles_response = search_tiles(tiles_request)

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


@app.post("/v1/tiles/refresh", response_model=TileRefreshResponse)
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
    primary_dest = branch.destinations[0] if branch.destinations else None

    # Build request with current settings
    tiles_request = TilesSearchRequest(
        session_id=session_id,
        destination=primary_dest,
        destination_hint=primary_dest,
        origin=branch.origin,
        start_date=branch.start_date,
        end_date=branch.end_date,
        adults=branch.adults,
        children=branch.children,
        requires_assistance=branch.requires_assistance,
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


@app.post("/v1/expand-itinerary")
async def expand_itinerary_endpoint(
    request: Request,
    req: ExpandItineraryRequest,
    db: AsyncSession = async_db_dependency,
):
    """
    Expand strategy into full itinerary (Stage 2 -> Stage 3).

    Streams NDJSON events:
        {"type": "progress", "stage": "itinerary", "message": "...", "pct": 30}
        {"type": "envelope", "plan_envelope": {...}}
        {"type": "done", "plan_view_state": "S3_ITINERARY_READY"}
        {"type": "error", "message": "..."}
    """
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
        try:
            session = await get_session_by_token(db, session_id)
            if not session:
                event = ExpandItineraryStreamEvent(type="error", message="Session not found")
                yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                return

            doc = await get_document(db, session=session)
            if not doc:
                event = ExpandItineraryStreamEvent(type="error", message="No plan document found")
                yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                return

            doc_data = get_document_data(doc)

            # Emit progress: starting
            event = ExpandItineraryStreamEvent(
                type="progress",
                stage="itinerary",
                message="Generating itinerary...",
                pct=10,
            )
            yield json.dumps(event.model_dump(exclude_none=True)) + "\n"

            # Build session state from document for planner
            session_state = {
                "trip_inputs": doc_data.trip_inputs.model_dump() if doc_data.trip_inputs else {},
                "branches": (
                    [b.model_dump() for b in doc_data.branches] if doc_data.branches else []
                ),
                "metadata": {"strategy_stage": 3},  # Force Stage 3
                "today_iso": compute_today_iso(),
            }

            # Emit progress: processing
            event = ExpandItineraryStreamEvent(
                type="progress",
                stage="itinerary",
                message="Building day cards...",
                pct=30,
            )
            yield json.dumps(event.model_dump(exclude_none=True)) + "\n"

            # Run planner to generate itinerary
            # Use a synthetic message to trigger itinerary generation
            try:
                result = await asyncio.wait_for(
                    run_turn("Generate the full day-by-day itinerary", session_state),
                    timeout=60.0,
                )
            except asyncio.TimeoutError:
                event = ExpandItineraryStreamEvent(
                    type="error", message="Itinerary generation timed out"
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

            # Extract itinerary data from result
            new_session_state = result.get("session_state", {})
            metadata = new_session_state.get("metadata", {})
            trip_inputs = new_session_state.get("trip_inputs", {})

            # Build envelope update
            plan_envelope = {}

            # Add itinerary fields if present
            if "day_cards" in metadata:
                plan_envelope["day_cards"] = metadata["day_cards"]
            if "itinerary_overview" in metadata:
                plan_envelope["itinerary_overview"] = metadata["itinerary_overview"]
            if "itinerary_assumptions" in metadata:
                plan_envelope["itinerary_assumptions"] = metadata["itinerary_assumptions"]

            # Compute new plan_view_state
            new_plan_view_state = _compute_plan_view_state(metadata, trip_inputs)
            plan_envelope["plan_view_state"] = new_plan_view_state

            # Emit envelope update
            event = ExpandItineraryStreamEvent(
                type="envelope",
                plan_envelope=plan_envelope,
            )
            yield json.dumps(event.model_dump(exclude_none=True)) + "\n"

            # Persist to document if we have itinerary data
            if plan_envelope.get("day_cards"):
                try:
                    await apply_planner_update(
                        db,
                        doc=doc,
                        session_state=new_session_state,
                        assistant_message=result.get("assistant_message", ""),
                        today_iso=compute_today_iso(),
                    )
                    await db.commit()
                except Exception as e:
                    logger.warning(f"Failed to persist itinerary: {e}")

            # Emit done
            event = ExpandItineraryStreamEvent(
                type="done",
                plan_view_state=new_plan_view_state,
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.backend_host, port=settings.backend_port)
