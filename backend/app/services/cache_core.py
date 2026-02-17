"""
Shared L1 in-memory cache primitive with thread-safe stats.

Each service instantiates its own MemoryCache with domain-specific config.
Eliminates copy-pasted _increment_stat / _cache_get / _cache_set / _stats_lock
boilerplate across specialist_cache, tile_cache, router_cache, experience_generator.
"""

from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any, Optional

from cachetools import TTLCache
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession


class MemoryCache:
    """Thread-safe TTLCache wrapper with built-in hit/miss counters."""

    def __init__(self, maxsize: int, ttl: int, stat_keys: list[str] | None = None) -> None:
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)
        self._cache_lock = RLock()
        self._stats_lock = RLock()
        default_keys = ["l1_hits", "l1_misses", "l2_hits", "l2_misses", "writes"]
        self._stats: dict[str, int] = {k: 0 for k in (stat_keys or default_keys)}

    # -- Stats --

    def increment_stat(self, key: str) -> None:
        with self._stats_lock:
            self._stats[key] = self._stats.get(key, 0) + 1

    def get_stats(self) -> dict[str, int]:
        with self._stats_lock:
            return dict(self._stats)

    # -- Cache ops --

    def get(self, key: str) -> Optional[Any]:
        with self._cache_lock:
            return self._cache.get(key)

    def set(self, key: str, value: Any) -> None:
        with self._cache_lock:
            self._cache[key] = value

    def clear(self) -> int:
        with self._cache_lock:
            count = len(self._cache)
            self._cache.clear()
        return count

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __contains__(self, key: str) -> bool:
        with self._cache_lock:
            return key in self._cache

    def __len__(self) -> int:
        with self._cache_lock:
            return len(self._cache)

    def keys(self) -> list[str]:
        """Return snapshot of current cache keys (thread-safe copy)."""
        with self._cache_lock:
            return list(self._cache.keys())


async def l2_upsert(
    db: AsyncSession,
    *,
    cache_key: str,
    cache_type: str,
    response_json: Any,
    ttl: timedelta,
) -> None:
    """Upsert a row into ResponseCache (L2). Shared by all cache modules.

    Commits internally — callers should NOT commit again after a successful call.
    On failure, callers are responsible for rollback.

    Args:
        db: Async database session
        cache_key: Unique cache key
        cache_type: Cache partition ("specialist", "tiles", "experience")
        response_json: JSON-serializable payload
        ttl: Time-to-live as timedelta
    """
    from app.db_models import ResponseCache

    now = datetime.now(UTC)
    expires_at = now + ttl

    stmt = pg_insert(ResponseCache).values(
        cache_key=cache_key,
        cache_type=cache_type,
        response_json=response_json,
        created_at=now,
        expires_at=expires_at,
        hit_count=0,
        last_hit_at=None,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["cache_key"],
        set_={
            "response_json": response_json,
            "created_at": now,
            "expires_at": expires_at,
        },
    )
    await db.execute(stmt)
    await db.commit()
