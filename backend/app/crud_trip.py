from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app import db_models as models


def _generate_session_token() -> str:
    """Generate a new cryptographically secure session token."""
    return str(uuid.uuid4())


def get_session_for_update(
    db: Session,
    session_token: str,
) -> Optional[models.Session]:
    """Get a session with a row-level lock to prevent concurrent modifications.

    Uses SELECT ... FOR UPDATE to acquire an exclusive lock on the session row.
    This prevents deadlocks between concurrent operations like DELETE session
    and UPDATE plan_documents.
    """
    if not session_token:
        return None

    return (
        db.query(models.Session)
        .filter(models.Session.session_token == session_token)
        .with_for_update()
        .first()
    )


def get_or_create_session(
    db: Session,
    session_token: str,
    user_external_id: Optional[str] = None,
    lock_for_update: bool = False,
) -> models.Session:
    """Get or create a session by token.

    If an existing session is found but has expired, it will be deleted and
    a new session will be created with the same token.

    Args:
        db: Database session.
        session_token: The session token to look up or create.
        user_external_id: Optional external user ID.
        lock_for_update: If True, acquire a row-level lock on the session.
            Use this when performing operations that could conflict with
            session deletion (e.g., updating plan documents).

    Returns:
        The session (existing with refreshed activity, or newly created).
    """
    if not session_token:
        raise ValueError("session_token is required")

    query = db.query(models.Session).filter(models.Session.session_token == session_token)
    if lock_for_update:
        query = query.with_for_update()

    db_session = query.first()

    if db_session:
        # Check if session has expired
        if db_session.is_expired():
            # Delete expired session and create a new one
            db.delete(db_session)
            db.flush()
            db_session = None
        else:
            # Refresh activity timestamp
            db_session.refresh_activity()
            db.flush()
            return db_session

    # Create new session
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


def rotate_session(
    db: Session,
    *,
    old_session: models.Session,
) -> models.Session:
    """
    Rotate a session by creating a new session token while keeping all data.

    This is a security measure to prevent session fixation attacks. It should
    be called after sensitive operations like first trip generation.

    The old session_token is replaced with a new one, but the session ID and
    all associated data (chat messages, trip contexts, documents) remain.

    Args:
        db: Database session.
        old_session: The current session to rotate.

    Returns:
        The same session object with a new session_token.
    """
    new_token = _generate_session_token()
    old_session.session_token = new_token
    old_session.refresh_activity()
    db.flush()
    return old_session


def should_rotate_session(
    db: Session,
    *,
    session: models.Session,
) -> bool:
    """
    Determine if a session should be rotated.

    A session should be rotated after the first plan generation (when it
    transitions from an anonymous browsing session to one with trip data).

    We detect this by checking if this is the first TripContext for the session.
    """
    trip_context_count = (
        db.query(models.TripContext).filter(models.TripContext.session_id == session.id).count()
    )
    # Rotate after the first trip context is created (count == 1)
    # Don't rotate on subsequent operations
    return trip_context_count == 1
