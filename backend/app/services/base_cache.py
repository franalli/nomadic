"""
Base class for thread-safe two-tier caching.

Consolidates common patterns from:
- specialist_cache.py
- tile_cache.py
- router_cache.py

Usage:
    class MyCache(BaseLRUCache):
        def __init__(self):
            super().__init__(
                name="my_cache",
                l1_ttl_seconds=3600,
                l1_max_size=128,
                stat_keys=["hits", "misses", "writes"],
            )

        def generate_key(self, *args) -> str:
            return f"my_cache:{':'.join(args)}"
"""

import logging
from abc import ABC, abstractmethod
from threading import RLock
from typing import Any, Dict, List, Optional

from cachetools import TTLCache

logger = logging.getLogger(__name__)


class BaseLRUCache(ABC):
    """
    Thread-safe in-memory LRU cache with TTL.

    Provides:
    - Thread-safe get/set/clear operations via RLock
    - Hit/miss statistics tracking
    - Consistent logging format

    Subclasses should implement:
    - generate_key(): Create cache keys from domain-specific args
    """

    def __init__(
        self,
        name: str,
        l1_ttl_seconds: int,
        l1_max_size: int,
        stat_keys: Optional[List[str]] = None,
    ):
        """
        Initialize the cache.

        Args:
            name: Cache name for logging (e.g., "SPECIALIST_CACHE")
            l1_ttl_seconds: TTL for cache entries in seconds
            l1_max_size: Maximum number of entries in cache
            stat_keys: List of stat counter names (default: hits, misses, writes)
        """
        self.name = name
        self.l1_ttl_seconds = l1_ttl_seconds
        self.l1_max_size = l1_max_size

        # Thread-safe locks
        self._cache_lock = RLock()
        self._stats_lock = RLock()

        # In-memory cache
        self._cache: TTLCache = TTLCache(maxsize=l1_max_size, ttl=l1_ttl_seconds)

        # Statistics
        default_stats = stat_keys or ["hits", "misses", "writes"]
        self._stats: Dict[str, int] = {key: 0 for key in default_stats}

    @abstractmethod
    def generate_key(self, *args: Any, **kwargs: Any) -> str:
        """
        Generate a cache key from domain-specific arguments.

        Subclasses must implement this method.

        Returns:
            A unique string key for the cache entry
        """
        pass

    def _increment_stat(self, key: str) -> None:
        """Thread-safe stats increment."""
        with self._stats_lock:
            if key in self._stats:
                self._stats[key] += 1

    def get(self, key: str) -> Optional[Any]:
        """
        Thread-safe cache get.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found
        """
        with self._cache_lock:
            value = self._cache.get(key)

        if value is not None:
            self._increment_stat("hits")
            logger.debug(f"[{self.name}] HIT: {key[:50]}")
        else:
            self._increment_stat("misses")
            logger.debug(f"[{self.name}] MISS: {key[:50]}")

        return value

    def set(self, key: str, value: Any) -> None:
        """
        Thread-safe cache set.

        Args:
            key: Cache key
            value: Value to cache
        """
        with self._cache_lock:
            self._cache[key] = value

        self._increment_stat("writes")
        logger.debug(f"[{self.name}] SET: {key[:50]}")

    def delete(self, key: str) -> bool:
        """
        Thread-safe cache delete.

        Args:
            key: Cache key

        Returns:
            True if key was deleted, False if not found
        """
        with self._cache_lock:
            if key in self._cache:
                del self._cache[key]
                return True
        return False

    def clear(self) -> int:
        """
        Clear all cache entries.

        Returns:
            Number of entries cleared
        """
        with self._cache_lock:
            count = len(self._cache)
            self._cache.clear()

        logger.info(f"[{self.name}] Cleared: {count} entries")
        return count

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dict with stats, size, maxsize, and ttl
        """
        with self._cache_lock:
            size = len(self._cache)
        with self._stats_lock:
            stats_copy = dict(self._stats)

        return {
            **stats_copy,
            "size": size,
            "maxsize": self.l1_max_size,
            "ttl_seconds": self.l1_ttl_seconds,
        }

    def reset_stats(self) -> None:
        """Reset all statistics counters to zero."""
        with self._stats_lock:
            for key in self._stats:
                self._stats[key] = 0

    def __len__(self) -> int:
        """Return number of items in cache."""
        with self._cache_lock:
            return len(self._cache)

    def __contains__(self, key: str) -> bool:
        """Check if key exists in cache."""
        with self._cache_lock:
            return key in self._cache
