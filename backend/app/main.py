import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

import app.db_models as db_models
import app.schemas as schemas
from app.config import settings
from app.db import get_db
from app.schemas import TilesSearchRequest, TilesSearchResponse
from app.tile_service.service import search_tiles

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


load_dotenv(BACKEND_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env.docker", override=False)

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


@app.post("/v1/tiles/search", response_model=TilesSearchResponse)
def tiles_search(req: TilesSearchRequest):
    return search_tiles(req)


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
        request_id=event.request_id,
    )

    db.add(click)
    db.commit()

    return {"status": "ok"}
