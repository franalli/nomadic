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


def _to_async_database_url(url: str) -> str:
    """Convert sync DATABASE_URL into an async-driver URL.

    - PostgreSQL -> asyncpg
    - SQLite (pysqlite or plain) -> aiosqlite
    """
    if url.startswith("sqlite+pysqlite://"):
        return url.replace("sqlite+pysqlite://", "sqlite+aiosqlite://", 1)
    if url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)

    # Convert any PostgreSQL URL to postgresql+asyncpg:// for async driver
    # Handle: postgresql://, postgres://, postgresql+psycopg2://
    return re.sub(
        r"^postgresql(\+psycopg2)?://",
        "postgresql+asyncpg://",
        url.replace("postgres://", "postgresql://"),
    )


ASYNC_DATABASE_URL = _to_async_database_url(DATABASE_URL)

# Lazy-initialized async engine and session factory
_async_engine: Optional[AsyncEngine] = None
_async_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def _get_async_engine() -> AsyncEngine:
    """Get or create the async engine (lazy initialization).

    Pool configuration for 20-30 concurrent users:
    - pool_size=15: Base number of connections to maintain
    - max_overflow=25: Additional connections allowed under load (total max: 40)
    - pool_recycle=3600: Recycle connections after 1 hour to avoid stale connections
    - pool_pre_ping=True: Verify connection is alive before using it
    """
    global _async_engine
    if _async_engine is None:
        engine_kwargs: dict = {
            "future": True,
            "echo": False,
        }

        # SQLite does not support QueuePool settings like max_overflow.
        if not ASYNC_DATABASE_URL.startswith("sqlite+"):
            engine_kwargs.update(
                {
                    "pool_size": 15,
                    "max_overflow": 25,
                    "pool_recycle": 3600,
                    "pool_pre_ping": True,
                }
            )

        _async_engine = create_async_engine(ASYNC_DATABASE_URL, **engine_kwargs)
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
