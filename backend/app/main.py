import logging
import os
from datetime import datetime
from typing import Any, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
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
    fetch_chat_history,
    get_latest_trip_context_for_session,
    get_or_create_session,
    get_session_by_token,
    record_chat_message,
    rotate_session,
    should_rotate_session,
)
from app.db import get_db
from app.graph_plan_utils import (
    check_payload_size,
    compute_today_iso,
    ensure_thread_id,
    generate_request_id,
    is_date_ambiguous,
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
    set_new_session_cookies,
)
from app.middleware.session import _generate_csrf_token
from app.plan import plan_trip
from app.plan_graph import run_turn
from app.schemas import (
    ChatHistoryResponse,
    ChatMessageResponse,
    GraphPlanErrorCode,
    GraphPlanObservability,
    GraphPlanRequest,
    GraphPlanResponse,
    GraphPlanTokens,
    PlanDocumentData,
    PlanDocumentPatch,
    PlanDocumentResponse,
    PlanRequest,
    TilesSearchRequest,
    TripInputValidationRequest,
    TripInputValidationResponse,
)
from app.tile_service.service import search_tiles
from app.validation import cache_stats, clear_cache, prewarm_cache, validate_input

# Configure logging for the graph plan route
logger = logging.getLogger(__name__)


APP_NAME = os.getenv("APP_NAME", "Nomadic Backend")

app = FastAPI(title=APP_NAME)

db_dependency = Depends(get_db)


# =============================================================================
# Startup Event - Pre-warm validation cache
# =============================================================================


@app.on_event("startup")
async def startup_event():
    """Pre-warm the validation cache with common destinations."""
    count = prewarm_cache()
    print(f"[Validation] Pre-warmed cache with {count} entries")


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
    }


# =============================================================================
# Trip Input Validation Endpoint
# =============================================================================


@app.post("/v1/validate-trip-input", response_model=TripInputValidationResponse)
def validate_trip_input(req: TripInputValidationRequest, request: Request):
    """
    Validate a trip input (origin or destination).

    Returns corrected values if the input was valid but had typos/formatting issues.
    For destinations, may return multiple values if the input contained multiple
    places (e.g., "Paris and Rome" -> ["Paris", "Rome"]).

    Raises HTTP 503 if validation fails after retries.
    """
    try:
        session_id = get_session_from_request(request)
        result = validate_input(req.value, req.field_type, session_id=session_id)
        return TripInputValidationResponse(
            corrected_values=result.corrected_values,
            is_valid=result.is_valid,
            reason=result.reason,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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


@app.post("/v1/graph_plan", response_model=GraphPlanResponse)
def graph_plan_endpoint(
    request: Request,
    response: Response,
    req: GraphPlanRequest,
    db: Session = db_dependency,
):
    """
    LangGraph-based planning endpoint.

    Accepts a user message and optional session state, runs the graph planner,
    persists document updates, and returns the updated session state.

    Features:
    - Feature flag gating (ENABLE_GRAPH_PLAN_ROUTE)
    - Payload size validation
    - Optimistic concurrency via document versioning
    - Fallback to legacy planner on failure (GRAPH_FALLBACK_TO_LEGACY)
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
    db_session = get_or_create_session(db, session_id)

    # --- Track previous ready_to_generate for observability ---
    ready_to_generate_prev = session_state.get("metadata", {}).get("ready_to_generate", False)

    # --- Get or create document for this session ---
    document = None
    document_data = None
    document_version = None
    try:
        document = get_or_create_document(db, session=db_session)
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

    # --- Check for date ambiguity in user message - return 400 if ambiguous ---
    if is_date_ambiguous(req.message):
        logger.info(f"[{request_id}] Date ambiguity detected in message")
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": GraphPlanErrorCode.DATE_AMBIGUOUS,
                "message": (
                    "Date in message is ambiguous. "
                    "Please specify an exact date (e.g., 2025-01-15) or provide more context."
                ),
            },
        )

    # --- Call run_turn with timeout ---
    try:
        # run_turn is synchronous; timeout is handled within plan_graph.py
        result = run_turn(req.message, session_state)
        logger.info(f"[{request_id}] Graph planner succeeded (LangGraph path)")
    except TimeoutError:
        logger.error(f"[{request_id}] run_turn timed out")
        if settings.graph_fallback_to_legacy:
            logger.info(f"[{request_id}] Falling back to legacy planner (reason: timeout)")
            return _fallback_to_legacy(
                request,
                response,
                req,
                db,
                session_id,
                request_id,
                document_data,
                document_version,
                today_iso,
                ready_to_generate_prev,
            )
        raise HTTPException(
            status_code=504,
            detail={
                "error_code": GraphPlanErrorCode.LLM_TIMEOUT,
                "message": "Planning request timed out",
            },
        ) from None
    except Exception as e:
        logger.error(f"[{request_id}] run_turn failed: {e}")
        if settings.graph_fallback_to_legacy:
            logger.info(f"[{request_id}] Falling back to legacy planner (reason: {e})")
            return _fallback_to_legacy(
                request,
                response,
                req,
                db,
                session_id,
                request_id,
                document_data,
                document_version,
                today_iso,
                ready_to_generate_prev,
            )
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": GraphPlanErrorCode.LLM_ERROR,
                "message": "Planning request failed",
            },
        ) from e

    # --- Validate and sanitize output ---
    assistant_message = result.get("assistant_message", "")
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
            trip_context = get_latest_trip_context_for_session(db, db_session.id)
            trip_context_id = trip_context.id if trip_context else 0

            # Apply planner update
            updated_doc = apply_planner_update(
                db,
                doc=document,
                trip_context_id=trip_context_id,
                trip_inputs=trip_inputs_obj,
                branches=branch_objs if branch_objs else None,
            )
            if updated_doc:
                new_document_version = updated_doc.version
                document_data = get_document_data(updated_doc)
                db.commit()
        except Exception as e:
            logger.error(f"[{request_id}] Failed to persist document: {e}")
            db.rollback()
            # Non-fatal - continue with response

    # --- Build observability data ---
    observability = GraphPlanObservability(
        tokens=GraphPlanTokens(prompt=0, completion=0, total=0),  # TODO: populate from LLM
        model_used=result.get("session_state", {}).get("metadata", {}).get("model_used"),
        router_intent=result.get("session_state", {}).get("router_intent"),
        strategy_topic=result.get("session_state", {}).get("strategy_topic"),
        monolith_used=result.get("session_state", {}).get("flags", {}).get("force_monolith", False),
        fallback_to_legacy=False,
        today_iso=today_iso,
        ready_to_generate_prev=ready_to_generate_prev,
        ready_to_generate_now=ready_to_generate_now,
    )

    # --- Set Cache-Control header ---
    response.headers["Cache-Control"] = "no-store"

    # --- Build document data for response ---
    response_document = document_data if document_data else PlanDocumentData()

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


def _fallback_to_legacy(
    request: Request,
    response: Response,
    req: GraphPlanRequest,
    db: Session,
    session_id: int,
    request_id: str,
    document_data: Any,
    document_version: Optional[int],
    today_iso: str,
    ready_to_generate_prev: bool,
) -> GraphPlanResponse:
    """
    Fallback to the legacy planner when graph planning fails.

    Converts the GraphPlanRequest to a PlanRequest and calls plan_trip,
    then wraps the result in a GraphPlanResponse.
    """
    logger.info(f"[{request_id}] Falling back to legacy planner")

    try:
        # Convert GraphPlanRequest to PlanRequest
        legacy_req = PlanRequest(
            message=req.message,
            trip_inputs=req.trip_inputs,
            preferences=None,  # Legacy planner uses trip_inputs
        )

        # Call the legacy planner
        result = plan_trip(db, session_id, legacy_req)

        # Build document for response using the legacy planner output if available
        response_document = getattr(result, "document", None) or document_data or PlanDocumentData()
        ready_to_generate_now = False
        trip_inputs = {}
        if getattr(result, "document", None):
            trip_inputs = result.document.trip_inputs.model_dump()
            ready_to_generate_now = result.document.ready_to_generate
        elif response_document:
            # Fallback to response_document values when legacy output missing
            trip_inputs = response_document.trip_inputs.model_dump()
            ready_to_generate_now = response_document.ready_to_generate

        # Convert PlanDocumentResponse to GraphPlanResponse
        return GraphPlanResponse(
            document=response_document,
            session_state={
                "trip_inputs": trip_inputs,
            },
            version=getattr(result, "version", None) or document_version or 1,
            updated_by="planner",
            updated_at=datetime.now().isoformat(),
            changes_made=True,
            request_id=request_id,
            observability=GraphPlanObservability(
                tokens=GraphPlanTokens(prompt=0, completion=0, total=0),
                fallback_to_legacy=True,
                today_iso=today_iso,
                ready_to_generate_prev=ready_to_generate_prev,
                ready_to_generate_now=ready_to_generate_now,
            ),
        )
    except Exception as e:
        logger.error(f"[{request_id}] Legacy fallback also failed: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": GraphPlanErrorCode.LLM_ERROR,
                "message": "Both graph and legacy planners failed",
            },
        ) from e


@app.post("/v1/plan", response_model=PlanDocumentResponse)
def plan(
    request: Request,
    response: Response,
    req: PlanRequest,
    db: Session = db_dependency,
):
    """
    Chat-like planning endpoint:
    message + preferences -> branches via LLM -> tiles for primary branch.
    Returns the full plan document with branches, tiles, and chat response.

    Session rotation:
    After the first trip context is created, the session token is rotated
    to prevent session fixation attacks. New cookies are set on the response.
    """
    session_id = get_session_from_request(request)
    try:
        result = plan_trip(db, session_id, req)

        # Check if we should rotate the session (after first trip creation)
        db_session = get_or_create_session(db, session_id)
        if should_rotate_session(db, session=db_session):
            # Rotate the session token
            rotated_session = rotate_session(db, old_session=db_session)
            db.commit()

            # Set new cookies with the rotated session token
            new_csrf = _generate_csrf_token()
            set_new_session_cookies(response, rotated_session.session_token, new_csrf)

        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/v1/session", status_code=204)
def reset_session(
    request: Request,
    db: Session = db_dependency,
):
    """
    Reset/delete a planning session and all associated data.

    Uses row-level locking to prevent deadlocks with concurrent plan operations.
    Also clears session cookies from the browser.
    """
    session_id = get_session_from_request(request)

    # Lock the session row first to prevent deadlocks with concurrent operations
    session = get_session_by_token(db, session_id, lock_for_update=True)
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
def get_chat_history(
    request: Request,
    db: Session = db_dependency,
):
    """
    Get chat history for the current session.

    Returns the last 50 messages in chronological order (oldest first).
    Used by the frontend to restore chat state on page load.
    """
    session_id = get_session_from_request(request)
    session = get_session_by_token(db, session_id)

    # Return empty history for new sessions (no error)
    if not session:
        return ChatHistoryResponse(messages=[])

    # Fetch messages (returns oldest first after reversal)
    messages = fetch_chat_history(db, session=session, limit=50)

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


# ─────────────────────────────────────────────────────────────────────────────
# Plan Document Endpoints - Centralized source of truth for branches & tiles
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/v1/document", response_model=PlanDocumentResponse)
def get_plan_document(
    request: Request,
    db: Session = db_dependency,
):
    """
    Get the current plan document for a session.
    Returns the centralized source of truth for branches and tiles.
    """
    session_id = get_session_from_request(request)
    session = get_session_by_token(db, session_id)
    if not session:
        # No session in DB yet - return 204 (no document)
        return Response(status_code=204)

    doc = get_document(db, session=session)
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
def patch_plan_document(
    request: Request,
    patch: PlanDocumentPatch,
    db: Session = db_dependency,
):
    """
    Apply a partial update to the plan document.
    Uses CRDT-style merge: additions win, deletions require explicit flags.
    """
    session_id = get_session_from_request(request)
    session = get_session_by_token(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    doc = get_document(db, session=session)
    if not doc:
        raise HTTPException(status_code=404, detail="No plan document for this session")

    # Apply the patch using CRDT merge
    updated_doc = apply_user_patch(db, doc=doc, patch=patch)

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
            latest_ctx = get_latest_trip_context_for_session(db, session=session)

            record_chat_message(
                db,
                session=session,
                trip_context=latest_ctx,
                role="system",
                content=system_msg,
                metadata={"ui_edit": True},
            )

    db.commit()

    doc_data = get_document_data(updated_doc)

    return PlanDocumentResponse(
        version=updated_doc.version,
        updated_by=updated_doc.updated_by,
        document=doc_data,
        updated_at=updated_doc.updated_at.isoformat(),
        changes_made=True,
    )


@app.post("/v1/document/tiles/{branch_id}", response_model=PlanDocumentResponse)
def fetch_tiles_for_branch(
    request: Request,
    branch_id: str,
    db: Session = db_dependency,
):
    """
    Fetch tiles for a specific branch and add them to the document.
    Used when switching branches to load tiles on demand.
    """
    session_id = get_session_from_request(request)
    session = get_session_by_token(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    doc = get_document(db, session=session)
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
    )

    tiles_response = search_tiles(tiles_request)

    if tiles_response.tiles:
        # Add tiles to the document
        updated_doc = add_tiles_to_branch(
            db,
            doc=doc,
            branch_id=branch_id,
            tiles=tiles_response.tiles,
            updated_by="planner",
        )
        db.commit()

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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.backend_host, port=settings.backend_port)
