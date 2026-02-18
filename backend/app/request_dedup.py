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
