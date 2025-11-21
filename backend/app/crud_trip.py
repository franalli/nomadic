from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy.orm import Session

from app import db_models as models
from app.schemas import Tile as TileSchema


def get_or_create_session(
    db: Session,
    session_token: str,
    user_external_id: Optional[str] = None,
) -> models.Session:
    if not session_token:
        raise ValueError("session_token is required")

    db_session = (
        db.query(models.Session).filter(models.Session.session_token == session_token).first()
    )
    if db_session:
        return db_session

    user: Optional[models.User] = None
    if user_external_id:
        user = db.query(models.User).filter(models.User.external_id == user_external_id).first()
        if not user:
            user = models.User(external_id=user_external_id)
            db.add(user)
            db.flush()

    db_session = models.Session(
        session_token=session_token,
        user_id=user.id if user else None,
    )
    db.add(db_session)
    db.flush()
    return db_session


def create_trip_context(
    db: Session,
    *,
    session: models.Session,
    parent_trip_context: Optional[models.TripContext],
    req_message: str,
) -> models.TripContext:
    ctx = models.TripContext(
        session_id=session.id,
        user_id=session.user_id,
        parent_trip_context_id=parent_trip_context.id if parent_trip_context else None,
        raw_prompt=req_message,
    )
    db.add(ctx)
    db.flush()
    return ctx


def get_latest_trip_context_for_session(
    db: Session,
    *,
    session: models.Session,
) -> Optional[models.TripContext]:
    return (
        db.query(models.TripContext)
        .filter(models.TripContext.session_id == session.id)
        .order_by(models.TripContext.created_at.desc())
        .first()
    )


def create_branches_for_context(
    db: Session,
    *,
    trip_context: models.TripContext,
    branch_specs: Sequence[dict],
    primary_index: int = 0,
) -> list[models.Branch]:
    branches: list[models.Branch] = []
    for idx, spec in enumerate(branch_specs):
        label = spec.get("label")
        destination = spec.get("destination")
        if not label or not destination:
            continue

        branch = models.Branch(
            trip_context_id=trip_context.id,
            label=str(label),
            description=str(spec.get("description", "")),
            destination=str(destination),
            is_primary=(idx == primary_index),
        )
        db.add(branch)
        branches.append(branch)

    db.flush()
    return branches


def snapshot_tiles_for_branch(
    db: Session,
    *,
    branch: models.Branch,
    tiles: list[TileSchema],
    replace_existing: bool = False,
) -> None:
    """Persist tiles + branch links for later analytics."""

    if replace_existing:
        (
            db.query(models.BranchTile)
            .filter(models.BranchTile.branch_id == branch.id)
            .delete(synchronize_session=False)
        )

    for idx, tile in enumerate(tiles):
        db_tile = models.Tile(
            type=tile.type,
            partner=tile.partner,
            partner_product_id=tile.partner_product_id,
            title=tile.title,
            subtitle=tile.subtitle,
            image_url=tile.image_url,
            price_estimate=tile.price_estimate,
            currency=tile.currency,
            price_basis=tile.price_basis,
            is_estimate_only=tile.is_estimate_only,
            deeplink_url=tile.deeplink_url,
            rating=tile.rating,
            review_count=tile.review_count,
            tags=tile.tags,
            location_label=tile.location_label,
            meta=tile.meta,
        )
        db.add(db_tile)
        db.flush()

        link = models.BranchTile(
            branch_id=branch.id,
            tile_id=db_tile.id,
            position=idx,
        )
        db.add(link)


def record_chat_message(
    db: Session,
    *,
    session: models.Session,
    trip_context: Optional[models.TripContext],
    role: str,
    content: str,
    metadata: Optional[dict] = None,
) -> models.ChatMessage:
    message = models.ChatMessage(
        session_id=session.id,
        trip_context_id=trip_context.id if trip_context else None,
        role=role,
        content=content,
        meta=metadata,
    )
    db.add(message)
    db.flush()
    return message


def fetch_chat_history(
    db: Session,
    *,
    session: models.Session,
    limit: int = 12,
) -> list[models.ChatMessage]:
    messages = (
        db.query(models.ChatMessage)
        .filter(models.ChatMessage.session_id == session.id)
        .order_by(models.ChatMessage.created_at.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(messages))
