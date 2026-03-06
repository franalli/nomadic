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
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )

    # Session expiration tracking
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_session_expires_at, nullable=False
    )

    user: Mapped[Optional["User"]] = relationship("User", back_populates="sessions")
    trip_contexts: Mapped[List["TripContext"]] = relationship(
        "TripContext", back_populates="session"
    )
    shared_trips: Mapped[List["SharedTrip"]] = relationship("SharedTrip", back_populates="session")

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


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    google_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    sessions: Mapped[List["Session"]] = relationship("Session", back_populates="user")
    shared_trips: Mapped[List["SharedTrip"]] = relationship("SharedTrip", back_populates="user")


class SharedTrip(Base, TimestampMixin):
    __tablename__ = "shared_trips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    slug: Mapped[str] = mapped_column(String(12), unique=True, index=True, nullable=False)
    session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    snapshot: Mapped[Dict] = mapped_column(JSON, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    destination: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    hero_image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    day_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped[Optional[Session]] = relationship("Session", back_populates="shared_trips")
    user: Mapped[Optional[User]] = relationship("User", back_populates="shared_trips")


class UnsplashImageCache(Base):
    """
    Cache for Unsplash image IDs by destination and variant.
    Stores image_id (not full URLs) for flexibility in URL construction.
    Includes photographer info and URLs for required attribution.
    Supports multiple image variants per destination for unique tile/branch imagery.
    """

    __tablename__ = "unsplash_image_cache"

    destination: Mapped[str] = mapped_column(String(256), primary_key=True)  # Normalized lowercase
    variant: Mapped[int] = mapped_column(
        Integer, primary_key=True, default=0
    )  # 0-5 for different image variants
    image_id: Mapped[str] = mapped_column(String(128), nullable=False)
    photographer: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    photographer_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    # Required for production attribution
    unsplash_url: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )  # Image page on Unsplash
    download_location: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )  # API endpoint to call when image is displayed
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class ResponseCache(Base):
    """
    Generic response cache for LLM outputs and API data.

    Used by specialist_cache.py and tile_cache.py for two-tier caching (L1 memory + L2 database).

    Cache types:
    - 'specialist': Vertical specialist LLM outputs (7 day TTL)
    - 'tiles': Tile data from curated/mock providers (24h TTL)

    Key formats:
    - specialist: "specialist:{topic}:{destination}:{month}:{duration}"
    - tiles: "tiles:{provider}:{type}:{dest}:{start_date}:{end_date}"
    """

    __tablename__ = "response_cache"

    cache_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    cache_type: Mapped[str] = mapped_column(String(50), nullable=False, default="specialist")
    response_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_hit_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
