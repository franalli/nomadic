import os
from typing import List

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

import app.db_models as db_models
import app.schemas as schemas
from app.config import settings
from app.crud_document import (
    add_tiles_to_branch,
    apply_user_patch,
    get_document,
    get_document_data,
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
from app.middleware import (
    CSRFMiddleware,
    SessionMiddleware,
    clear_session_cookies,
    get_session_from_request,
    set_new_session_cookies,
)
from app.middleware.session import _generate_csrf_token
from app.plan import plan_trip
from app.schemas import (
    ChatHistoryResponse,
    ChatMessageResponse,
    PlanDocumentPatch,
    PlanDocumentResponse,
    PlanRequest,
    TilesSearchRequest,
    TripInputValidationRequest,
    TripInputValidationResponse,
)
from app.tile_service.service import search_tiles
from app.validation import clear_cache, prewarm_cache, validate_input

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
def validate_trip_input(req: TripInputValidationRequest):
    """
    Validate a trip input (origin or destination).

    Returns corrected values if the input was valid but had typos/formatting issues.
    For destinations, may return multiple values if the input contained multiple
    places (e.g., "Paris and Rome" -> ["Paris", "Rome"]).

    Raises HTTP 503 if validation fails after retries.
    """
    try:
        result = validate_input(req.value, req.field_type)
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
    count = clear_cache()
    # Re-populate with common values
    new_count = prewarm_cache()
    return {
        "cleared": count,
        "repopulated": new_count,
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
