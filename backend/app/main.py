import os
import sys
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

import app.db_models as db_models
import app.schemas as schemas
from app.config import settings
from app.crud_trip import get_or_create_session, snapshot_tiles_for_branch
from app.db import get_db
from app.plan import plan_trip, plan_trip_event_stream
from app.schemas import (
    PlanRequest,
    PlanResponse,
    SessionSnapshot,
    SessionSnapshotBranch,
    SessionTripContext,
    Tile,
    TilesSearchRequest,
    TilesSearchResponse,
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


def _tile_from_model(tile: db_models.Tile) -> Tile:
    return Tile(
        id=str(tile.id),
        type=tile.type or "hotel",
        partner=tile.partner or "nomadic",
        partner_product_id=tile.partner_product_id or str(tile.id),
        title=tile.title,
        subtitle=tile.subtitle,
        image_url=tile.image_url,
        price_estimate=tile.price_estimate,
        live_price=None,
        currency=tile.currency or "EUR",
        price_basis=tile.price_basis or "per_trip",
        is_estimate_only=tile.is_estimate_only,
        deeplink_url=tile.deeplink_url or "",
        rating=tile.rating,
        review_count=tile.review_count,
        location_label=tile.location_label,
        geo=None,
        tags=tile.tags or [],
        availability_status="unknown",
        meta=tile.meta or {},
        score=None,
        source=None,
    )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "env": settings.env,
    }


@app.post("/v1/tiles/search", response_model=TilesSearchResponse)
def tiles_search(req: TilesSearchRequest, db: Session = db_dependency):
    session = None
    did_mutate = False

    if req.session_id:
        session = get_or_create_session(db, session_token=req.session_id)
        # get_or_create_session flushes when creating a new row
        did_mutate = True

    branch = None
    if req.branch_id is not None:
        branch = db.get(db_models.Branch, req.branch_id)
        if not branch:
            raise HTTPException(status_code=404, detail="Branch not found")

        if (
            session
            and branch.trip_context is not None
            and branch.trip_context.session_id != session.id
        ):
            raise HTTPException(status_code=403, detail="Branch does not belong to session")

    response = search_tiles(req)

    if branch and response.tiles:
        snapshot_tiles_for_branch(
            db,
            branch=branch,
            tiles=response.tiles,
            replace_existing=True,
        )
        did_mutate = True

    if did_mutate:
        db.commit()

    return response


@app.post("/v1/tiles/click")
def track_tile_click(
    event: schemas.TileClickEvent,
    db: Session = db_dependency,
):
    """
    Persist a tile click to tile_clicks and return a simple status.
    """

    # Optional: try to coerce tile_id to int if you’re using integer PKs in tiles;
    # if that fails, just store click without tile FK and rely on request_id/session_id.
    tile_id_int = None
    if event.tile_id is not None:
        try:
            candidate_tile_id = int(event.tile_id)
        except ValueError:
            # For now do not fail the request; you still get click logs.
            candidate_tile_id = None

        if candidate_tile_id is not None:
            tile_exists = db.get(db_models.Tile, candidate_tile_id)
            tile_id_int = candidate_tile_id if tile_exists else None

    branch_id_int = None
    if event.branch_id is not None:
        try:
            candidate_branch_id = int(event.branch_id)
        except (TypeError, ValueError):
            candidate_branch_id = None

        if candidate_branch_id is not None:
            branch_exists = db.get(db_models.Branch, candidate_branch_id)
            branch_id_int = candidate_branch_id if branch_exists else None

    click = db_models.TileClick(
        tile_id=tile_id_int,
        tile_identifier=event.tile_id,
        branch_id=branch_id_int,
        session_id=event.session_id,
        user_id=event.user_id,
        request_id=event.request_id,
    )

    db.add(click)
    db.commit()

    return {"status": "ok"}


@app.post("/v1/plan", response_model=PlanResponse)
def plan(
    req: PlanRequest,
    db: Session = db_dependency,
    stream: bool = Query(False, description="Stream incremental planner events"),
):
    """
    Chat-like planning endpoint:
    message + preferences -> branches via LLM -> tiles for primary branch.
    """
    try:
        if stream:
            return StreamingResponse(
                plan_trip_event_stream(db, req),
                media_type="application/jsonl",
            )

        return plan_trip(db, req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/session/snapshot", response_model=SessionSnapshot)
def get_session_snapshot(
    session_id: str = Query(..., description="Frontend session UUID"),
    db: Session = db_dependency,
):
    session = (
        db.query(db_models.Session).filter(db_models.Session.session_token == session_id).first()
    )

    if not session:
        return SessionSnapshot()

    trip_ctx = (
        db.query(db_models.TripContext)
        .filter(db_models.TripContext.session_id == session.id)
        .order_by(db_models.TripContext.created_at.desc())
        .first()
    )

    if not trip_ctx:
        return SessionSnapshot()

    branches = (
        db.query(db_models.Branch)
        .filter(db_models.Branch.trip_context_id == trip_ctx.id)
        .order_by(db_models.Branch.id.asc())
        .all()
    )

    if not branches:
        return SessionSnapshot()

    primary_branch = next((branch for branch in branches if branch.is_primary), branches[0])

    tile_models = (
        db.query(db_models.Tile)
        .join(db_models.BranchTile, db_models.BranchTile.tile_id == db_models.Tile.id)
        .filter(db_models.BranchTile.branch_id == primary_branch.id)
        .order_by(db_models.BranchTile.position.asc())
        .all()
    )
    tiles = [_tile_from_model(tile_model) for tile_model in tile_models]

    ctx_payload = SessionTripContext(
        id=trip_ctx.id,
        raw_prompt=trip_ctx.raw_prompt,
    )

    return SessionSnapshot(
        branches=[
            SessionSnapshotBranch(
                id=branch.id,
                label=branch.label,
                description=branch.description or "",
                destination=branch.destination,
            )
            for branch in branches
        ],
        primary_branch_id=primary_branch.id,
        tiles=tiles,
        trip_context=ctx_payload,
    )


@app.delete("/v1/session", status_code=204)
def reset_session(
    session_id: str = Query(..., description="Frontend session UUID"),
    db: Session = db_dependency,
):
    session = (
        db.query(db_models.Session).filter(db_models.Session.session_token == session_id).first()
    )
    if not session:
        return Response(status_code=204)

    trip_context_ids = [
        ctx_id
        for (ctx_id,) in (
            db.query(db_models.TripContext.id)
            .filter(db_models.TripContext.session_id == session.id)
            .all()
        )
    ]

    (
        db.query(db_models.ChatMessage)
        .filter(db_models.ChatMessage.session_id == session.id)
        .delete(synchronize_session=False)
    )

    if trip_context_ids:

        branch_ids = [
            branch_id
            for (branch_id,) in (
                db.query(db_models.Branch.id)
                .filter(db_models.Branch.trip_context_id.in_(trip_context_ids))
                .all()
            )
        ]

        if branch_ids:
            tile_ids = [
                tile_id
                for (tile_id,) in (
                    db.query(db_models.BranchTile.tile_id)
                    .filter(db_models.BranchTile.branch_id.in_(branch_ids))
                    .all()
                )
                if tile_id is not None
            ]

            (
                db.query(db_models.BranchTile)
                .filter(db_models.BranchTile.branch_id.in_(branch_ids))
                .delete(synchronize_session=False)
            )
            (
                db.query(db_models.Branch)
                .filter(db_models.Branch.id.in_(branch_ids))
                .delete(synchronize_session=False)
            )

            if tile_ids:
                (
                    db.query(db_models.Tile)
                    .filter(db_models.Tile.id.in_(tile_ids))
                    .delete(synchronize_session=False)
                )

        (
            db.query(db_models.TripContext)
            .filter(db_models.TripContext.id.in_(trip_context_ids))
            .delete(synchronize_session=False)
        )

    (
        db.query(db_models.TileClick)
        .filter(db_models.TileClick.session_id == session_id)
        .delete(synchronize_session=False)
    )

    db.delete(session)
    db.commit()

    return Response(status_code=204)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.backend_host, port=settings.backend_port)
