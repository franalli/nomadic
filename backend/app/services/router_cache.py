"""
Thread-safe L1-only caching for Router extraction results.

L1: In-memory TTLCache (1h TTL, 500 entries)
No L2: Extraction depends on conversation context, short TTL makes L2 ineffective

CRITICAL: Only caches self-contained queries (no context dependencies).
Context-dependent queries like "Show me diving there" would return wrong results
if cached across different conversations.

Cache key format: SHA256({normalized_text}:{today_date})[:32]

Usage:
    from app.services.router_cache import (
        get_cached_extraction,
        set_cached_extraction,
    )

    # In intent_router.py
    today_date = datetime.now().strftime("%Y-%m-%d")
    cached = get_cached_extraction(user_text, today_date)
    if cached:
        return RouterOutput.model_validate(cached)

    # After LLM call
    set_cached_extraction(user_text, today_date, output.model_dump())
"""

import hashlib
import logging
from threading import RLock
from typing import Optional

from cachetools import TTLCache

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================
L1_TTL_SECONDS = 3600  # 1 hour
L1_MAX_SIZE = 500

# =============================================================================
# L1: Thread-safe in-memory cache
# =============================================================================
_cache_lock = RLock()
_stats_lock = RLock()
_router_cache: TTLCache = TTLCache(maxsize=L1_MAX_SIZE, ttl=L1_TTL_SECONDS)

# Hit/miss counters for observability
_cache_stats = {
    "hits": 0,
    "misses": 0,
    "skipped_context_dependent": 0,
}


def _increment_stat(key: str) -> None:
    """Thread-safe stats increment."""
    with _stats_lock:
        _cache_stats[key] += 1


def _router_cache_key(user_text: str, today_date: str) -> str:
    """
    Generate cache key with SHA256 (not truncated MD5).

    CRITICAL: Key includes today_date because relative dates like "next Friday"
    depend on when the query is made.

    Args:
        user_text: User's message text
        today_date: Current date in YYYY-MM-DD format

    Returns:
        SHA256 hash truncated to 32 characters
    """
    normalized = user_text.lower().strip()
    content = f"{normalized}:{today_date}"
    return hashlib.sha256(content.encode()).hexdigest()[:32]


def _is_self_contained_query(user_text: str, extraction: dict) -> bool:
    """
    Only cache queries that don't depend on conversation context.

    Context-dependent queries like "Show me diving there" would return
    wrong results if cached across different conversations.

    Args:
        user_text: User's message text
        extraction: Extracted fields from router

    Returns:
        True if query is self-contained and safe to cache

    Example context-dependent queries (should return False):
        - "Show me diving there" (where is "there"?)
        - "I want that one" (which one?)
        - "Book it now" (what is "it"?)
        - "Same dates as before" (what dates?)
    """
    # Words that reference previous messages
    context_words = [
        "there",
        "that",
        "this",
        "it",
        "them",
        "same",
        "again",
        "too",
        "also",
        "extend",
        "shorten",
        "more days",
        "fewer days",
    ]
    text_lower = user_text.lower()

    # Check if any context word appears as a standalone word
    # Use word boundaries to avoid false positives (e.g., "weather" contains "the")
    for word in context_words:
        # Check for word in middle of sentence
        if f" {word} " in f" {text_lower} ":
            return False
        # Check for word at end of sentence
        if text_lower.endswith(f" {word}"):
            return False
        # Check for word at start (rare but possible)
        if text_lower.startswith(f"{word} "):
            return False

    # Must have extracted a destination (indicates self-contained trip info)
    if not extraction.get("destination"):
        return False

    return True


# =============================================================================
# Cache Operations
# =============================================================================


def get_cached_extraction(user_text: str, today_date: str) -> Optional[dict]:
    """
    Get cached router extraction (L1 only).

    Args:
        user_text: User's message text
        today_date: Current date in YYYY-MM-DD format

    Returns:
        Cached extraction dict or None if not found
    """
    key = _router_cache_key(user_text, today_date)

    with _cache_lock:
        cached = _router_cache.get(key)

    if cached is not None:
        _increment_stat("hits")
        dest = cached.get("destination", "?")
        logger.info(f"[ROUTER_CACHE] ✅ HIT: '{user_text[:40]}' → dest={dest}")
        return cached

    _increment_stat("misses")
    logger.info(f"[ROUTER_CACHE] ❌ MISS: '{user_text[:40]}'")
    return None


def set_cached_extraction(user_text: str, today_date: str, extraction: dict) -> None:
    """
    Cache router extraction (L1 only).

    CRITICAL: Only caches self-contained queries to prevent cross-conversation pollution.

    Args:
        user_text: User's message text
        today_date: Current date in YYYY-MM-DD format
        extraction: RouterOutput.model_dump() dict
    """
    # Validate before caching
    if not _is_self_contained_query(user_text, extraction):
        _increment_stat("skipped_context_dependent")
        logger.info(f"[ROUTER_CACHE] ⚠️ SKIP (context-dependent): '{user_text[:40]}'")
        return

    key = _router_cache_key(user_text, today_date)

    with _cache_lock:
        _router_cache[key] = extraction

    dest = extraction.get("destination", "?")
    logger.info(f"[ROUTER_CACHE] 💾 CACHED: '{user_text[:40]}' → dest={dest}")


# =============================================================================
# Admin Functions
# =============================================================================


def get_cache_stats() -> dict:
    """Return cache statistics for observability."""
    with _cache_lock:
        size = len(_router_cache)
    with _stats_lock:
        stats_copy = dict(_cache_stats)
    return {
        **stats_copy,
        "size": size,
        "maxsize": L1_MAX_SIZE,
        "ttl_seconds": L1_TTL_SECONDS,
    }


def clear_cache() -> int:
    """Clear cache. Returns count cleared."""
    with _cache_lock:
        count = len(_router_cache)
        _router_cache.clear()
    logger.info(f"[ROUTER_CACHE] Cleared ({count} entries)")
    return count
