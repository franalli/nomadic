# backend/app/db_models.py
from datetime import UTC, date, datetime
from typing import Dict, List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from app.db import Base


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

    origin: Mapped[Optional[str]] = mapped_column(String(16))
    destination_hint: Mapped[Optional[str]] = mapped_column(String(64))
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    budget_bucket: Mapped[Optional[str]] = mapped_column(String(32))
    group_size: Mapped[Optional[int]] = mapped_column(Integer)
    vibes: Mapped[Optional[List[str]]] = mapped_column(JSON)
    raw_prompt: Mapped[Optional[str]] = mapped_column(String)

    session: Mapped[Optional[Session]] = relationship("Session", back_populates="trip_contexts")
    parent_trip_context: Mapped[Optional["TripContext"]] = relationship(
        "TripContext", remote_side="TripContext.id"
    )
    branches: Mapped[List["Branch"]] = relationship("Branch", back_populates="trip_context")


class Branch(Base, TimestampMixin):
    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    trip_context_id: Mapped[int] = mapped_column(ForeignKey("trip_contexts.id"))

    label: Mapped[str] = mapped_column(String(128))
    description: Mapped[Optional[str]] = mapped_column(String)
    destination: Mapped[str] = mapped_column(String(64))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    trip_context: Mapped[TripContext] = relationship("TripContext", back_populates="branches")
    branch_tiles: Mapped[List["BranchTile"]] = relationship(
        "BranchTile", back_populates="branch", cascade="all, delete-orphan"
    )


class Tile(Base, TimestampMixin):
    __tablename__ = "tiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    type: Mapped[str] = mapped_column(String(32))  # "flight" | "hotel" | "activity"
    partner: Mapped[Optional[str]] = mapped_column(String(64))
    partner_product_id: Mapped[Optional[str]] = mapped_column(String(128))

    title: Mapped[str] = mapped_column(String)
    subtitle: Mapped[Optional[str]] = mapped_column(String)
    image_url: Mapped[Optional[str]] = mapped_column(String)

    price_estimate: Mapped[Optional[float]] = mapped_column(Float)
    currency: Mapped[Optional[str]] = mapped_column(String(8))
    price_basis: Mapped[Optional[str]] = mapped_column(String(32))
    is_estimate_only: Mapped[bool] = mapped_column(Boolean, default=True)
    deeplink_url: Mapped[Optional[str]] = mapped_column(String)

    rating: Mapped[Optional[float]] = mapped_column(Float)
    review_count: Mapped[Optional[int]] = mapped_column(Integer)

    tags: Mapped[Optional[List[str]]] = mapped_column(JSON)
    location_label: Mapped[Optional[str]] = mapped_column(String(128))
    meta: Mapped[Optional[Dict]] = mapped_column(JSON)

    branch_tiles: Mapped[List["BranchTile"]] = relationship(
        "BranchTile", back_populates="tile", cascade="all, delete-orphan"
    )
    clicks: Mapped[List["TileClick"]] = relationship(
        "TileClick", back_populates="tile", cascade="all, delete-orphan"
    )


class BranchTile(Base):
    __tablename__ = "branch_tiles"

    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), primary_key=True)
    tile_id: Mapped[int] = mapped_column(ForeignKey("tiles.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    branch: Mapped[Branch] = relationship("Branch", back_populates="branch_tiles")
    tile: Mapped[Tile] = relationship("Tile", back_populates="branch_tiles")


class TileClick(Base, TimestampMixin):
    __tablename__ = "tile_clicks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # make nullable=True so you can log clicks even before tiles are in the DB
    tile_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tiles.id"), nullable=True)
    tile_identifier: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    branch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("branches.id"), nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    tile: Mapped[Optional["Tile"]] = relationship("Tile", back_populates="clicks")


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
