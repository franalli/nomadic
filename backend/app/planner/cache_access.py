# backend/app/planner/cache_access.py
"""
Thread-safe cache accessors for planner caches.

PR3: Cache concurrency safety - wraps cache operations with locks
to prevent race conditions in FastAPI async/threaded environments.

Note: Cache instances remain in plan_graph.py; this module provides
safe accessor functions with locking.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Literal, Optional

# Type alias for cache names
CacheName = Literal["follow_up", "router", "required_fields", "extractor", "strategy", "tile"]


@dataclass
class CacheHandle:
    """
    Handle wrapping a cache instance with its lock.

    Attributes:
        cache_obj: The underlying TTLCache instance
        lock: Threading lock for synchronization
        name: Name of the cache for observability
    """

    cache_obj: Any  # TTLCache, but we don't import it here to avoid coupling
    lock: threading.Lock = field(default_factory=threading.Lock)
    name: str = ""


# Global registry of cache handles
_cache_handles: Dict[CacheName, CacheHandle] = {}

# Initialization flag to guard against access before init
_initialized = False

# Lock for protecting _cache_counters updates
_cache_counters_lock = threading.Lock()


def get_cache_handle(name: CacheName) -> Optional[CacheHandle]:
    """
    Get a cache handle by name.

    Raises:
        RuntimeError: If called before init_cache_handles()
    """
    if not _initialized:
        raise RuntimeError(
            f"Cache '{name}' accessed before initialization. Call init_cache_handles() first."
        )
    return _cache_handles.get(name)


def cache_get(
    name: CacheName,
    key: str,
    *,
    record_event_fn: Optional[Callable[[str, str, Optional[str]], None]] = None,
) -> Optional[Any]:
    """
    Thread-safe cache get operation.

    Args:
        name: Name of the cache
        key: Cache key
        record_event_fn: Optional callback to record cache event (node, action, reason)

    Returns:
        Cached value or None if not found
    """
    handle = _cache_handles.get(name)
    if handle is None:
        return None

    with handle.lock:
        value = handle.cache_obj.get(key)

    # Record event outside lock to avoid holding lock during I/O
    if record_event_fn is not None:
        if value is not None:
            record_event_fn(name, "hit", None)
        else:
            record_event_fn(name, "miss", None)

    return value


def cache_set(
    name: CacheName,
    key: str,
    value: Any,
    *,
    record_event_fn: Optional[Callable[[str, str, Optional[str]], None]] = None,
) -> None:
    """
    Thread-safe cache set operation.

    Args:
        name: Name of the cache
        key: Cache key
        value: Value to cache
        record_event_fn: Optional callback to record cache event
    """
    handle = _cache_handles.get(name)
    if handle is None:
        return

    with handle.lock:
        handle.cache_obj[key] = value

    if record_event_fn is not None:
        record_event_fn(name, "set", None)


def cache_pop(
    name: CacheName,
    key: str,
    *,
    reason: str = "explicit",
    record_event_fn: Optional[Callable[[str, str, Optional[str]], None]] = None,
) -> Optional[Any]:
    """
    Thread-safe cache pop (get and remove) operation.

    Args:
        name: Name of the cache
        key: Cache key
        reason: Reason for eviction (for observability)
        record_event_fn: Optional callback to record cache event

    Returns:
        The removed value or None if not found
    """
    handle = _cache_handles.get(name)
    if handle is None:
        return None

    with handle.lock:
        value = handle.cache_obj.pop(key, None)

    if value is not None and record_event_fn is not None:
        record_event_fn(name, "evict", reason)

    return value


def cache_delete(
    name: CacheName,
    key: str,
    *,
    reason: str = "explicit",
    record_event_fn: Optional[Callable[[str, str, Optional[str]], None]] = None,
) -> bool:
    """
    Thread-safe cache delete operation.

    Args:
        name: Name of the cache
        key: Cache key
        reason: Reason for eviction
        record_event_fn: Optional callback to record cache event

    Returns:
        True if key was deleted, False if not found
    """
    handle = _cache_handles.get(name)
    if handle is None:
        return False

    with handle.lock:
        if key in handle.cache_obj:
            del handle.cache_obj[key]
            deleted = True
        else:
            deleted = False

    if deleted and record_event_fn is not None:
        record_event_fn(name, "evict", reason)

    return deleted


def cache_clear(name: CacheName) -> None:
    """
    Thread-safe cache clear operation.

    Args:
        name: Name of the cache to clear
    """
    handle = _cache_handles.get(name)
    if handle is None:
        return

    with handle.lock:
        handle.cache_obj.clear()


def cache_len(name: CacheName) -> int:
    """
    Thread-safe cache length query.

    Args:
        name: Name of the cache

    Returns:
        Number of items in the cache
    """
    handle = _cache_handles.get(name)
    if handle is None:
        return 0

    with handle.lock:
        return len(handle.cache_obj)


def cache_contains(name: CacheName, key: str) -> bool:
    """
    Thread-safe check if key exists in cache.

    Args:
        name: Name of the cache
        key: Cache key

    Returns:
        True if key exists in cache
    """
    handle = _cache_handles.get(name)
    if handle is None:
        return False

    with handle.lock:
        return key in handle.cache_obj


def update_counters_safe(
    counters: Dict[str, int],
    key: str,
    amount: int = 1,
) -> None:
    """
    Thread-safe counter increment.

    Uses the global _cache_counters_lock.

    Args:
        counters: The counter dict to update
        key: Counter key
        amount: Amount to increment
    """
    with _cache_counters_lock:
        counters[key] = counters.get(key, 0) + amount


def update_nested_counters_safe(
    counters: Dict[str, Dict[str, int]],
    outer_key: str,
    inner_key: str,
    amount: int = 1,
) -> None:
    """
    Thread-safe nested counter increment.

    Uses the global _cache_counters_lock.

    Args:
        counters: The nested counter dict to update
        outer_key: Outer dict key
        inner_key: Inner dict key
        amount: Amount to increment
    """
    with _cache_counters_lock:
        if outer_key not in counters:
            counters[outer_key] = {}
        counters[outer_key][inner_key] = counters[outer_key].get(inner_key, 0) + amount
