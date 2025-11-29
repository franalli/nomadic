from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app import db_models as models


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
