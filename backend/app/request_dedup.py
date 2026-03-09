"""Request deduplication via idempotency key caching.

Extracted from main.py to reduce file size.
Used by the expand-itinerary endpoint to prevent duplicate generation requests.
"""

import asyncio

from cachetools import TTLCache

# Simple in-memory idempotency cache (TTL: 30 seconds, max 1000 entries)
# In production, use Redis with TTL
_idempotency_cache: TTLCache = TTLCache(maxsize=1000, ttl=30)
_idempotency_lock = asyncio.Lock()


async def check_idempotency(key: str | None) -> bool:
    """Check if idempotency key was recently used. Returns True if duplicate."""
    if not key:
        return False
    async with _idempotency_lock:
        if key in _idempotency_cache:
            return True
        _idempotency_cache[key] = True
        return False


async def release_idempotency(key: str | None) -> None:
    """Release an idempotency key so it can be retried after failure."""
    if not key:
        return
    async with _idempotency_lock:
        _idempotency_cache.pop(key, None)


# Per-session expand-itinerary mutex: 1 in-flight per session
# TTLCache auto-expires after 120s so a crashed generator can't permanently lock a session.
# Single-process only (same caveat as idempotency cache above).
_expand_in_flight: TTLCache = TTLCache(maxsize=200, ttl=120)
_expand_lock = asyncio.Lock()


async def acquire_expand_slot(session_id: str) -> bool:
    """Try to acquire the expand-itinerary slot for this session.
    Returns True if acquired (proceed), False if already in-flight (reject)."""
    async with _expand_lock:
        if session_id in _expand_in_flight:
            return False
        _expand_in_flight[session_id] = True
        return True


async def release_expand_slot(session_id: str) -> None:
    """Release the expand-itinerary slot for this session."""
    async with _expand_lock:
        _expand_in_flight.pop(session_id, None)
