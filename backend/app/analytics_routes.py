# backend/app/analytics_routes.py
"""Analytics tracking endpoints.

Extracted from main.py to keep the FastAPI app module focused on core routes.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

import app.db_models as db_models
import app.schemas as schemas
from app.db import get_async_db
from app.middleware import get_session_from_request
from app.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["analytics"])

async_db_dependency = Depends(get_async_db)


class TrackEventRequest(BaseModel):
    event_type: str = Field(max_length=48)
    destination: Optional[str] = Field(default=None, max_length=200)
    metadata: Optional[Dict[str, Any]] = None


@router.post("/analytics/event")
@limiter.limit("60/minute")
async def track_event(
    request: Request,
    body: TrackEventRequest,
    db: AsyncSession = async_db_dependency,
):
    """Fire-and-forget event tracking. Never fails the user request."""
    try:
        session_id = getattr(request.state, "session_id", None) or "anonymous"
        event = db_models.TripEvent(
            session_id=str(session_id)[:64],
            event_type=body.event_type,
            destination=body.destination,
            metadata_=body.metadata,
        )
        db.add(event)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.warning("[analytics] Event tracking failed (non-fatal): %s", exc)
    return {"status": "ok"}


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
