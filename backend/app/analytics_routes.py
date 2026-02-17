# backend/app/analytics_routes.py
"""Analytics tracking endpoints (tile clicks, suggestion clicks).

Extracted from main.py to keep the FastAPI app module focused on core routes.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

import app.db_models as db_models
import app.schemas as schemas
from app.db import get_async_db
from app.middleware import get_session_from_request
from app.rate_limit import limiter

router = APIRouter(prefix="/api", tags=["analytics"])

async_db_dependency = Depends(get_async_db)


@router.post("/tiles/click")
@limiter.limit("60/minute")
async def track_tile_click(
    request: Request,
    event: schemas.TileClickEvent,
    db: AsyncSession = async_db_dependency,
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
    await db.commit()

    return {"status": "ok"}


@router.post("/suggestions/click")
@limiter.limit("60/minute")
async def track_suggestion_click(
    request: Request,
    event: schemas.SuggestionClickEvent,
    db: AsyncSession = async_db_dependency,
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
    await db.commit()

    return {"status": "ok"}
