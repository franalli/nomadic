from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app import db_models as models
from app.config import generate_session_token

# =============================================================================
# Sync functions (for legacy endpoints and migrations)
# =============================================================================


def get_session_by_token_sync(
    db: Session,
    session_token: str,
    lock_for_update: bool = False,
) -> Optional[models.Session]:
    """Look up a session by token without creating one if missing (sync version)."""
    query = db.query(models.Session).filter(models.Session.session_token == session_token)
    if lock_for_update:
        query = query.with_for_update()
    return query.first()


def get_or_create_session_sync(
    db: Session,
    session_token: str,
    lock_for_update: bool = False,
) -> models.Session:
    """Get or create a session by token (sync version)."""
    if not session_token:
        raise ValueError("session_token is required")

    query = db.query(models.Session).filter(models.Session.session_token == session_token)
    if lock_for_update:
        query = query.with_for_update()

    db_session = query.first()

    if db_session:
        if db_session.is_expired():
            db.delete(db_session)
            db.flush()
            db_session = None
        else:
            db_session.refresh_activity()
            db.flush()
            return db_session

    db_session = models.Session(session_token=session_token)
    db.add(db_session)
    db.flush()
    return db_session


# =============================================================================
# Async functions (for async endpoints and LangGraph)
# =============================================================================


async def get_session_by_token(
    db: AsyncSession,
    session_token: str,
    lock_for_update: bool = False,
) -> Optional[models.Session]:
    """Look up a session by token without creating one if missing (async).

    Args:
        db: Async database session.
        session_token: The session token to look up.
        lock_for_update: If True, acquire a row-level lock on the session.

    Returns:
        The session if found, otherwise None.
    """
    stmt = select(models.Session).filter(models.Session.session_token == session_token)
    if lock_for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_or_create_session(
    db: AsyncSession,
    session_token: str,
    lock_for_update: bool = False,
) -> models.Session:
    """Get or create a session by token (async).

    If an existing session is found but has expired, it will be deleted and
    a new session will be created with the same token.

    Args:
        db: Async database session.
        session_token: The session token to look up or create.
        lock_for_update: If True, acquire a row-level lock on the session.
            Use this when performing operations that could conflict with
            session deletion (e.g., updating plan documents).

    Returns:
        The session (existing with refreshed activity, or newly created).
    """
    if not session_token:
        raise ValueError("session_token is required")

    stmt = select(models.Session).filter(models.Session.session_token == session_token)
    if lock_for_update:
        stmt = stmt.with_for_update()

    result = await db.execute(stmt)
    db_session = result.scalar_one_or_none()

    if db_session:
        # Check if session has expired
        if db_session.is_expired():
            # Delete expired session and create a new one
            await db.delete(db_session)
            await db.flush()
            db_session = None
        else:
            # Refresh activity timestamp
            db_session.refresh_activity()
            await db.flush()
            return db_session

    # Create new session
    db_session = models.Session(session_token=session_token)
    db.add(db_session)
    await db.flush()
    return db_session


async def create_trip_context(
    db: AsyncSession,
    *,
    session: models.Session,
    parent_trip_context: Optional[models.TripContext],
    req_message: str,
) -> models.TripContext:
    ctx = models.TripContext(
        session_id=session.id,
        parent_trip_context_id=parent_trip_context.id if parent_trip_context else None,
        raw_prompt=req_message,
    )
    db.add(ctx)
    await db.flush()
    return ctx


async def get_latest_trip_context_for_session(
    db: AsyncSession,
    *,
    session: models.Session,
) -> Optional[models.TripContext]:
    stmt = (
        select(models.TripContext)
        .filter(models.TripContext.session_id == session.id)
        .order_by(models.TripContext.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def record_chat_message(
    db: AsyncSession,
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
    await db.flush()
    return message


async def fetch_chat_history(
    db: AsyncSession,
    *,
    session: models.Session,
    limit: int = 12,
) -> list[models.ChatMessage]:
    stmt = (
        select(models.ChatMessage)
        .filter(models.ChatMessage.session_id == session.id)
        .order_by(models.ChatMessage.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    messages = list(result.scalars().all())
    return list(reversed(messages))


async def rotate_session(
    db: AsyncSession,
    *,
    old_session: models.Session,
) -> models.Session:
    """
    Rotate a session by creating a new session token while keeping all data (async).

    This is a security measure to prevent session fixation attacks. It should
    be called after sensitive operations like first trip generation.

    The old session_token is replaced with a new one, but the session ID and
    all associated data (chat messages, trip contexts, documents) remain.

    Args:
        db: Async database session.
        old_session: The current session to rotate.

    Returns:
        The same session object with a new session_token.
    """
    new_token = generate_session_token()
    old_session.session_token = new_token
    old_session.refresh_activity()
    await db.flush()
    return old_session


async def should_rotate_session(
    db: AsyncSession,
    *,
    session: models.Session,
) -> bool:
    """
    Determine if a session should be rotated (async).

    A session should be rotated after the first plan generation (when it
    transitions from an anonymous browsing session to one with trip data).

    We detect this by checking if this is the first TripContext for the session.
    """
    from sqlalchemy import func

    stmt = (
        select(func.count())
        .select_from(models.TripContext)
        .filter(models.TripContext.session_id == session.id)
    )
    result = await db.execute(stmt)
    trip_context_count = result.scalar() or 0
    # Rotate after the first trip context is created (count == 1)
    # Don't rotate on subsequent operations
    return trip_context_count == 1


# ─────────────────────────────────────────────────────────────────────────────
# Sync versions for legacy endpoints
# ─────────────────────────────────────────────────────────────────────────────


def get_latest_trip_context_for_session_sync(
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


def record_chat_message_sync(
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


def fetch_chat_history_sync(
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


def rotate_session_sync(
    db: Session,
    *,
    old_session: models.Session,
) -> models.Session:
    """
    Rotate a session by creating a new session token while keeping all data (sync).
    """
    new_token = generate_session_token()
    old_session.session_token = new_token
    old_session.refresh_activity()
    db.flush()
    return old_session


def should_rotate_session_sync(
    db: Session,
    *,
    session: models.Session,
) -> bool:
    """
    Determine if a session should be rotated (sync).
    """
    from sqlalchemy import func

    trip_context_count = (
        db.query(func.count())
        .select_from(models.TripContext)
        .filter(models.TripContext.session_id == session.id)
        .scalar()
    ) or 0
    return trip_context_count == 1
