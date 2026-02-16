"""
Shared L1 in-memory cache primitive with thread-safe stats.

Each service instantiates its own MemoryCache with domain-specific config.
Eliminates copy-pasted _increment_stat / _cache_get / _cache_set / _stats_lock
boilerplate across specialist_cache, tile_cache, router_cache, experience_generator.
"""

from threading import RLock
from typing import Any, Optional

from cachetools import TTLCache


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

    def size(self) -> int:
        with self._cache_lock:
            return len(self._cache)
