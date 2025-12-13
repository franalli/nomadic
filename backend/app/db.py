# backend/app/db.py
import re
from typing import AsyncGenerator, Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

DATABASE_URL = settings.database_url
if not DATABASE_URL:
    # For local non-docker runs you can hardcode or read from .env
    raise RuntimeError("DATABASE_URL is not set")

# =============================================================================
# Sync Engine (for Alembic migrations and legacy code)
# =============================================================================
engine = create_engine(DATABASE_URL, future=True)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
)

Base = declarative_base()


def get_db() -> Generator:
    """Sync database session dependency (for legacy endpoints)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =============================================================================
# Async Engine (for async endpoints and LangGraph)
# Lazy initialization to avoid breaking Alembic migrations
# =============================================================================

# Convert any PostgreSQL URL to postgresql+asyncpg:// for async driver
# Handle: postgresql://, postgres://, postgresql+psycopg2://
ASYNC_DATABASE_URL = re.sub(
    r"^postgresql(\+psycopg2)?://",
    "postgresql+asyncpg://",
    DATABASE_URL.replace("postgres://", "postgresql://"),
)

# Lazy-initialized async engine and session factory
_async_engine: Optional[AsyncEngine] = None
_async_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def _get_async_engine() -> AsyncEngine:
    """Get or create the async engine (lazy initialization)."""
    global _async_engine
    if _async_engine is None:
        _async_engine = create_async_engine(
            ASYNC_DATABASE_URL,
            future=True,
            echo=False,
        )
    return _async_engine


def _get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the async session factory (lazy initialization)."""
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            _get_async_engine(),
            class_=AsyncSession,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
    return _async_session_factory


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """Async database session dependency for FastAPI."""
    factory = _get_async_session_factory()
    async with factory() as session:
        try:
            yield session
        finally:
            await session.close()
