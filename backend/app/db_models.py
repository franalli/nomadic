# backend/app/db_models.py
from datetime import UTC, datetime, timedelta
from typing import Dict, List, Literal, Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from app.db import Base

UpdatedBy = Literal["user", "planner"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


# Session expiration constants
SESSION_IDLE_TIMEOUT_DAYS = 14  # Expire after 14 days of inactivity
SESSION_ABSOLUTE_TIMEOUT_DAYS = 90  # Expire after 90 days regardless of activity


def _session_expires_at() -> datetime:
    """Default absolute expiration: 90 days from creation."""
    return datetime.now(UTC) + timedelta(days=SESSION_ABSOLUTE_TIMEOUT_DAYS)


class Session(Base, TimestampMixin):
    """
    User session for tracking planning state.

    Session expiration:
    - last_activity_at: Updated on each request; session expires after idle timeout
    - expires_at: Absolute expiration; session expires regardless of activity

    A session is expired if EITHER:
    - now > expires_at (absolute expiry)
    - now > last_activity_at + idle_timeout (idle expiry)
    """

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_token: Mapped[str] = mapped_column(String, index=True, unique=True)

    # Session expiration tracking
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_session_expires_at, nullable=False
    )

    trip_contexts: Mapped[List["TripContext"]] = relationship(
        "TripContext", back_populates="session"
    )

    def is_expired(self) -> bool:
        """Check if session has expired (either idle or absolute).

        Handles both timezone-aware and naive datetimes (e.g., from SQLite).
        Naive datetimes are assumed to be UTC.
        """
        now = datetime.now(UTC)

        # Handle naive datetimes (e.g., from SQLite) by treating them as UTC
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)

        last_activity = self.last_activity_at
        if last_activity.tzinfo is None:
            last_activity = last_activity.replace(tzinfo=UTC)

        # Absolute expiry
        if now > expires_at:
            return True
        # Idle expiry
        idle_threshold = last_activity + timedelta(days=SESSION_IDLE_TIMEOUT_DAYS)
        if now > idle_threshold:
            return True
        return False

    def refresh_activity(self) -> None:
        """Update last_activity_at to current time."""
        self.last_activity_at = datetime.now(UTC)


class TripContext(Base, TimestampMixin):
    __tablename__ = "trip_contexts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    session_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sessions.id"))
    parent_trip_context_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("trip_contexts.id"), nullable=True
    )
    raw_prompt: Mapped[Optional[str]] = mapped_column(String)

    session: Mapped[Optional[Session]] = relationship("Session", back_populates="trip_contexts")
    parent_trip_context: Mapped[Optional["TripContext"]] = relationship(
        "TripContext", remote_side="TripContext.id"
    )


class TileClick(Base, TimestampMixin):
    """
    Track tile clicks for analytics.
    Stores identifiers as strings since tiles are now in the JSON document.
    """

    __tablename__ = "tile_clicks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    tile_identifier: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    branch_identifier: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class SuggestionClick(Base, TimestampMixin):
    """
    Track suggestion pill clicks for analytics.
    Helps measure quality and engagement with LLM-generated suggestions.
    """

    __tablename__ = "suggestion_clicks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    suggestion_text: Mapped[str] = mapped_column(String(128), nullable=False)
    suggestion_index: Mapped[int] = mapped_column(Integer, nullable=False)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class ChatMessage(Base, TimestampMixin):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    trip_context_id: Mapped[Optional[int]] = mapped_column(ForeignKey("trip_contexts.id"))
    role: Mapped[str] = mapped_column(String(16))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(String)
    meta: Mapped[Optional[Dict]] = mapped_column(JSON)
    # Snapshot of trip_inputs at the time this message was sent (for rollback on delete)
    trip_inputs_snapshot: Mapped[Optional[Dict]] = mapped_column(JSON, nullable=True)

    session: Mapped[Session] = relationship("Session")
    trip_context: Mapped[Optional[TripContext]] = relationship("TripContext")


class PlanDocument(Base, TimestampMixin):
    """
    Centralized JSON document storing branches and tiles as source of truth.
    Updated by both the chat planner and user actions.
    Uses CRDT-style merge for conflict resolution.
    """

    __tablename__ = "plan_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), unique=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[UpdatedBy] = mapped_column(String(16))  # "user" | "planner"

    # The main JSON document containing branches, tiles, selections, trip_inputs
    document: Mapped[Dict] = mapped_column(JSON, default=dict)

    session: Mapped[Session] = relationship("Session")
