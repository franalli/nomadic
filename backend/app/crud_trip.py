from __future__ import annotations

from datetime import date
from typing import Optional, Sequence

from sqlalchemy.orm import Session

from app import db_models as models
from app.schemas import Tile as TileSchema


def _to_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


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
    req_message: str,
    origin: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
    budget_bucket: Optional[str],
    group_size: Optional[int],
    vibes: Optional[list[str]],
) -> models.TripContext:
    ctx = models.TripContext(
        session_id=session.id,
        user_id=session.user_id,
        origin=origin,
        destination_hint=None,
        start_date=_to_date(start_date),
        end_date=_to_date(end_date),
        budget_bucket=budget_bucket,
        group_size=group_size,
        vibes=vibes or [],
        raw_prompt=req_message,
    )
    db.add(ctx)
    db.flush()
    return ctx


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
