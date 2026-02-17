"""
Validation Cache Infrastructure
================================

Cache layer for the trip input validation module. Extracted from validation.py
to separate cache management concerns from validation logic.

Provides:
- 6 TTL caches (positive, negative, split, prompt, fallback, rate counter)
- Async lock for thread-safe cache access
- Cache key generation
- Prompt building with caching
- Rate limiting per session
- Prewarm, clear, and stats functions
"""

import asyncio
import logging
from typing import Optional

from cachetools import TTLCache

from app.config import settings
from app.planner.hashing import make_cache_key

logger = logging.getLogger(__name__)

# =============================================================================
# CACHE INITIALIZATION
# =============================================================================

# TTL cache: per-worker, entries expire after validation_cache_ttl seconds
_validation_cache: TTLCache = TTLCache(
    maxsize=settings.validation_cache_size,
    ttl=settings.validation_cache_ttl,
)
_negative_cache: TTLCache = TTLCache(
    maxsize=settings.validation_negative_cache_size,
    ttl=settings.validation_negative_cache_ttl,
)
# Split cache stores destination splits so repeat requests skip LLM parsing.
_split_cache: TTLCache = TTLCache(
    maxsize=settings.validation_split_cache_size,
    ttl=settings.validation_cache_ttl,
)
# Prompt cache avoids repeatedly formatting identical prompts.
_prompt_cache: TTLCache = TTLCache(
    maxsize=settings.validation_prompt_cache_size,
    ttl=settings.validation_cache_ttl,
)
# Fallback cache returns the last known good answer if the live call fails.
_fallback_cache: TTLCache = TTLCache(
    maxsize=settings.validation_fallback_cache_size,
    ttl=settings.validation_cache_ttl,
)
# Per-session counters provide a lightweight request budget.
_rate_counter_cache: TTLCache = TTLCache(
    maxsize=10_000,
    ttl=settings.validation_rate_limit_window,
)

# Async lock for all validation caches
# All callers are async (endpoints, lifespan) — asyncio.Lock avoids blocking the event loop
_validation_cache_lock = asyncio.Lock()


# =============================================================================
# CACHE KEY GENERATION
# =============================================================================


def _cache_key(field_type: str, value: str) -> str:
    """Generate a cache key from field type and normalized value."""
    normalized = value.strip().lower()
    return make_cache_key("validation", "v2", field_type, normalized)


async def _build_prompt(field_type: str, normalized_value: str, location_prompt: str) -> str:
    """Render or reuse the minimal validation prompt."""
    cache_key = _cache_key(field_type, normalized_value)
    async with _validation_cache_lock:
        cached_prompt = _prompt_cache.get(cache_key)
        if cached_prompt is not None:
            return cached_prompt

    prompt = location_prompt.format(
        field_type=field_type,
        value=normalized_value,
    )
    async with _validation_cache_lock:
        _prompt_cache[cache_key] = prompt
    return prompt


async def _check_rate_limit(session_id: Optional[str]) -> Optional[str]:
    """Increment per-session validation counter; return reason if exceeded."""
    if not settings.validation_rate_limit_enabled or not session_id:
        return None

    async with _validation_cache_lock:
        count = _rate_counter_cache.get(session_id, 0) + 1
        _rate_counter_cache[session_id] = count

    if count > settings.validation_rate_limit_max_requests:
        return "Too many validation attempts. Please try again later."
    return None


# =============================================================================
# CACHE LOOKUP / STORE
# =============================================================================


async def lookup_cache(field_type: str, normalized_value: str) -> Optional[dict]:
    """Check positive, negative, and split caches. Returns dict or None."""
    cache_key = _cache_key(field_type, normalized_value)
    async with _validation_cache_lock:
        cached = _validation_cache.get(cache_key)
        if cached is not None:
            return cached

        if settings.validation_negative_cache_enabled:
            negative_reason = _negative_cache.get(cache_key)
            if negative_reason is not None:
                return {
                    "corrected_values": [],
                    "is_valid": False,
                    "reason": negative_reason,
                }

        # Destination splitting cache
        split_key = normalized_value.lower()
        if field_type == "destination":
            split_cached = _split_cache.get(split_key)
            if split_cached is not None:
                return split_cached

    return None


async def lookup_fallback(field_type: str, normalized_value: str) -> Optional[dict]:
    """Check the fallback cache for a previously known-good result."""
    cache_key = _cache_key(field_type, normalized_value)
    async with _validation_cache_lock:
        return _fallback_cache.get(cache_key)


async def store_result(
    field_type: str,
    normalized_value: str,
    result_dict: dict,
    is_valid: bool,
    reason: Optional[str],
) -> None:
    """Store a validation result in the appropriate caches."""
    cache_key = _cache_key(field_type, normalized_value)
    split_key = normalized_value.lower()

    async with _validation_cache_lock:
        if is_valid:
            _validation_cache[cache_key] = result_dict
            _fallback_cache[cache_key] = result_dict

            corrected_values = result_dict.get("corrected_values", [])
            if field_type == "destination" and len(corrected_values) > 1:
                _split_cache[split_key] = result_dict
        elif settings.validation_negative_cache_enabled:
            _negative_cache[cache_key] = reason or "Invalid input"


# =============================================================================
# CACHE MANAGEMENT (PUBLIC)
# =============================================================================


async def prewarm_cache() -> int:
    """
    Pre-populate the cache with common destinations.

    Called on server startup. Returns the number of entries added.
    """
    # Common destinations (top ~50 cities)
    common_destinations = [
        "Paris",
        "London",
        "New York City",
        "Tokyo",
        "Rome",
        "Barcelona",
        "Amsterdam",
        "Dubai",
        "Singapore",
        "Hong Kong",
        "Los Angeles",
        "San Francisco",
        "Miami",
        "Las Vegas",
        "Chicago",
        "Sydney",
        "Melbourne",
        "Bangkok",
        "Bali",
        "Phuket",
        "Berlin",
        "Munich",
        "Vienna",
        "Prague",
        "Budapest",
        "Lisbon",
        "Madrid",
        "Milan",
        "Venice",
        "Florence",
        "Athens",
        "Istanbul",
        "Cairo",
        "Marrakech",
        "Cape Town",
        "Rio de Janeiro",
        "Buenos Aires",
        "Mexico City",
        "Cancun",
        "Toronto",
        "Vancouver",
        "Montreal",
        "Reykjavik",
        "Dublin",
        "Edinburgh",
        "Copenhagen",
        "Stockholm",
        "Oslo",
        "Helsinki",
        "Zurich",
    ]

    count = 0

    # Pre-populate destinations (valid for both origin and destination)
    async with _validation_cache_lock:
        for dest in common_destinations:
            for field_type in ("origin", "destination"):
                cache_key = _cache_key(field_type, dest)
                if cache_key not in _validation_cache:
                    entry = {
                        "corrected_values": [dest],
                        "is_valid": True,
                        "reason": None,
                    }
                    _validation_cache[cache_key] = entry
                    _fallback_cache[cache_key] = entry
                    count += 1

    return count


async def clear_cache(preserve_rate_limiting: bool = True) -> int:
    """
    Clear all validation caches.

    Args:
        preserve_rate_limiting: If True (default), preserves the rate counter cache
                                to prevent abuse. Set to False only for full system reset.

    Returns the number of entries that were cleared across caches.
    """
    async with _validation_cache_lock:
        count = (
            len(_validation_cache)
            + len(_negative_cache)
            + len(_split_cache)
            + len(_prompt_cache)
            + len(_fallback_cache)
        )
        _validation_cache.clear()
        _negative_cache.clear()
        _split_cache.clear()
        _prompt_cache.clear()
        _fallback_cache.clear()

        if not preserve_rate_limiting:
            count += len(_rate_counter_cache)
            _rate_counter_cache.clear()

    return count


async def cache_stats() -> dict[str, int]:
    """Return a snapshot of validation cache sizes."""
    async with _validation_cache_lock:
        return {
            "positive": len(_validation_cache),
            "negative": len(_negative_cache),
            "split": len(_split_cache),
            "prompt": len(_prompt_cache),
            "fallback": len(_fallback_cache),
            "rate_counters": len(_rate_counter_cache),
        }
