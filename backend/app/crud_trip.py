from __future__ import annotations

from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app import db_models as models

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
    trip_inputs_snapshot: Optional[dict] = None,
) -> models.ChatMessage:
    message = models.ChatMessage(
        session_id=session.id,
        trip_context_id=trip_context.id if trip_context else None,
        role=role,
        content=content,
        meta=metadata,
        trip_inputs_snapshot=trip_inputs_snapshot,
    )
    db.add(message)
    await db.flush()
    return message


async def get_last_user_message(
    db: AsyncSession,
    *,
    session: models.Session,
) -> Optional[models.ChatMessage]:
    """Get the most recent user message for a session."""
    stmt = (
        select(models.ChatMessage)
        .filter(
            models.ChatMessage.session_id == session.id,
            models.ChatMessage.role == "user",
        )
        .order_by(models.ChatMessage.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def delete_messages_from_id(
    db: AsyncSession,
    *,
    session: models.Session,
    message_id: int,
) -> int:
    """
    Delete a message and all messages after it (by ID) for a session.
    Returns the number of messages deleted.
    """
    stmt = delete(models.ChatMessage).where(
        models.ChatMessage.session_id == session.id,
        models.ChatMessage.id >= message_id,
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount


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
