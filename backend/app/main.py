import os
import sys
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Response
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
from app.db import get_db
from app.plan import plan_trip
from app.schemas import (
    PlanDocumentPatch,
    PlanDocumentResponse,
    PlanRequest,
    TilesSearchRequest,
)
from app.tile_service.service import search_tiles

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


APP_NAME = os.getenv("APP_NAME", "Nomadic Backend")

app = FastAPI(title=APP_NAME)

db_dependency = Depends(get_db)

origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    # add prod frontend origin later, e.g. "https://app.yourdomain.com"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "env": settings.env,
    }


@app.post("/v1/tiles/click")
def track_tile_click(
    event: schemas.TileClickEvent,
    db: Session = db_dependency,
):
    """
    Persist a tile click for analytics.
    """
    click = db_models.TileClick(
        tile_identifier=event.tile_id,
        branch_identifier=event.branch_id,
        session_id=event.session_id,
        user_id=event.user_id,
        request_id=event.request_id,
    )

    db.add(click)
    db.commit()

    return {"status": "ok"}


@app.post("/v1/plan", response_model=PlanDocumentResponse)
def plan(
    req: PlanRequest,
    db: Session = db_dependency,
):
    """
    Chat-like planning endpoint:
    message + preferences -> branches via LLM -> tiles for primary branch.
    Returns the full plan document with branches, tiles, and chat response.
    """
    try:
        return plan_trip(db, req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/v1/session", status_code=204)
def reset_session(
    session_id: str = Query(..., description="Frontend session UUID"),
    db: Session = db_dependency,
):
    """
    Reset/delete a planning session and all associated data.

    Uses row-level locking to prevent deadlocks with concurrent plan operations.
    """
    # Lock the session row first to prevent deadlocks with concurrent operations
    session = (
        db.query(db_models.Session)
        .filter(db_models.Session.session_token == session_id)
        .with_for_update()
        .first()
    )
    if not session:
        return Response(status_code=204)

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

    return Response(status_code=204)


# ─────────────────────────────────────────────────────────────────────────────
# Plan Document Endpoints - Centralized source of truth for branches & tiles
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/v1/document", response_model=PlanDocumentResponse)
def get_plan_document(
    session_id: str = Query(..., description="Frontend session UUID"),
    db: Session = db_dependency,
):
    """
    Get the current plan document for a session.
    Returns the centralized source of truth for branches and tiles.
    """
    session = (
        db.query(db_models.Session).filter(db_models.Session.session_token == session_id).first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    doc = get_document(db, session=session)
    if not doc:
        raise HTTPException(status_code=404, detail="No plan document for this session")

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
    patch: PlanDocumentPatch,
    session_id: str = Query(..., description="Frontend session UUID"),
    db: Session = db_dependency,
):
    """
    Apply a partial update to the plan document.
    Uses CRDT-style merge: additions win, deletions require explicit flags.
    """
    session = (
        db.query(db_models.Session).filter(db_models.Session.session_token == session_id).first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    doc = get_document(db, session=session)
    if not doc:
        raise HTTPException(status_code=404, detail="No plan document for this session")

    # Apply the patch using CRDT merge
    updated_doc = apply_user_patch(db, doc=doc, patch=patch)
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
    branch_id: str,
    session_id: str = Query(..., description="Frontend session UUID"),
    db: Session = db_dependency,
):
    """
    Fetch tiles for a specific branch and add them to the document.
    Used when switching branches to load tiles on demand.
    """
    session = (
        db.query(db_models.Session).filter(db_models.Session.session_token == session_id).first()
    )
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
        traveler_count=branch.traveler_count,
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
