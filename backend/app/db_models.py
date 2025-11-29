# backend/app/db_models.py
from datetime import UTC, datetime
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


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    sessions: Mapped[List["Session"]] = relationship("Session", back_populates="user")


class Session(Base, TimestampMixin):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    session_token: Mapped[str] = mapped_column(String, index=True, unique=True)

    user: Mapped[Optional[User]] = relationship("User", back_populates="sessions")
    trip_contexts: Mapped[List["TripContext"]] = relationship(
        "TripContext", back_populates="session"
    )


class TripContext(Base, TimestampMixin):
    __tablename__ = "trip_contexts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
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
    user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class ChatMessage(Base, TimestampMixin):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    trip_context_id: Mapped[Optional[int]] = mapped_column(ForeignKey("trip_contexts.id"))
    role: Mapped[str] = mapped_column(String(16))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(String)
    meta: Mapped[Optional[Dict]] = mapped_column(JSON)

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
