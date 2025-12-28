"""
Cache Compatibility Layer - Tier 2.2 Migration.

This module provides backward-compatible function signatures that wrap the new
unified caching framework. It allows gradual migration from the old cache
functions in plan_graph.py to the new CacheNode-based system.

Usage (drop-in replacement):
    # Old imports from plan_graph.py
    from app.plan_graph import _get_extractor_cached, _set_extractor_cached

    # New imports from compatibility layer
    from app.planner.cache.compat import get_extractor_cached, set_extractor_cached

The functions maintain identical signatures and behavior, but use the unified
framework internally for consistent version validation and statistics.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from app.planner.cache.framework import (
    ExtractorCache,
    ResponseCache,
    StrategyCache,
    TileCache,
)

if TYPE_CHECKING:
    from app.plan_graph import GraphState


# =============================================================================
# EXTRACTOR CACHE COMPATIBILITY
# =============================================================================


def get_extractor_cached(
    session_id: str,
    user_text: str,
    core_fields_hash: str,
    extractor_mode: str,
    state: Optional["GraphState"] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get cached extractor result (backward-compatible signature).

    Wraps ExtractorCache.get() with the old function signature.

    Args:
        session_id: Session identifier
        user_text: User input text
        core_fields_hash: Hash of core trip fields
        extractor_mode: "light" or "full"
        state: Optional GraphState for metadata updates

    Returns:
        Cached extraction dict or None if not found/invalid
    """
    from app.config import settings

    cache = ExtractorCache.get_instance()
    model_id = getattr(settings, "llm_model", "gpt-4o-mini")

    key = cache.compute_key(
        session_id=session_id,
        user_text=user_text,
        core_fields_hash=core_fields_hash,
        extractor_mode=extractor_mode,
        model_id=model_id,
    )

    return cache.get(key, state)


def set_extractor_cached(
    session_id: str,
    user_text: str,
    core_fields_hash: str,
    extractor_mode: str,
    result: Dict[str, Any],
) -> None:
    """
    Cache extractor result (backward-compatible signature).

    Wraps ExtractorCache.set() with the old function signature.

    Args:
        session_id: Session identifier
        user_text: User input text
        core_fields_hash: Hash of core trip fields
        extractor_mode: "light" or "full"
        result: Extraction result to cache
    """
    from app.config import settings

    cache = ExtractorCache.get_instance()
    model_id = getattr(settings, "llm_model", "gpt-4o-mini")

    key = cache.compute_key(
        session_id=session_id,
        user_text=user_text,
        core_fields_hash=core_fields_hash,
        extractor_mode=extractor_mode,
        model_id=model_id,
    )

    cache.set(
        key,
        result,
        extra={
            "extractor_mode": extractor_mode,
            "model_id": model_id,
        },
    )


def get_extractor_cache_stats() -> Dict[str, Any]:
    """Get extractor cache statistics (backward-compatible)."""
    cache = ExtractorCache.get_instance()
    return cache.get_stats()


# =============================================================================
# STRATEGY CACHE COMPATIBILITY
# =============================================================================


def get_strategy_cached(
    session_id: str,
    topic: str,
    core_fields_hash: str,
    user_text_hash: str,
    section_id: Optional[str] = None,
    stage0_lifecycle_hash: Optional[str] = None,
    state: Optional["GraphState"] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get cached strategy result (backward-compatible signature).

    Wraps StrategyCache.get() with the old function signature.

    Args:
        session_id: Session identifier
        topic: Strategy topic (hiking, diving, etc.)
        core_fields_hash: Hash of core trip fields
        user_text_hash: Hash of user text
        section_id: Optional section identifier
        stage0_lifecycle_hash: Optional lifecycle hash
        state: Optional GraphState for metadata updates

    Returns:
        Cached strategy dict or None if not found/invalid
    """
    from app.config import settings

    cache = StrategyCache.get_instance()
    model_id = getattr(settings, "llm_model", "gpt-4o-mini")

    key = cache.compute_key(
        session_id=session_id,
        topic=topic,
        core_fields_hash=core_fields_hash,
        user_text_hash=user_text_hash,
        section_id=section_id,
        stage0_lifecycle_hash=stage0_lifecycle_hash,
        model_id=model_id,
    )

    return cache.get(key, state)


def set_strategy_cached(
    session_id: str,
    topic: str,
    core_fields_hash: str,
    user_text_hash: str,
    result: Dict[str, Any],
    section_id: Optional[str] = None,
    stage0_lifecycle_hash: Optional[str] = None,
) -> None:
    """
    Cache strategy result (backward-compatible signature).

    Wraps StrategyCache.set() with the old function signature.

    Args:
        session_id: Session identifier
        topic: Strategy topic
        core_fields_hash: Hash of core trip fields
        user_text_hash: Hash of user text
        result: Strategy result to cache
        section_id: Optional section identifier
        stage0_lifecycle_hash: Optional lifecycle hash
    """
    from app.config import settings

    cache = StrategyCache.get_instance()
    model_id = getattr(settings, "llm_model", "gpt-4o-mini")

    key = cache.compute_key(
        session_id=session_id,
        topic=topic,
        core_fields_hash=core_fields_hash,
        user_text_hash=user_text_hash,
        section_id=section_id,
        stage0_lifecycle_hash=stage0_lifecycle_hash,
        model_id=model_id,
    )

    cache.set(
        key,
        result,
        extra={
            "topic": topic,
            "section_id": section_id,
            "model_id": model_id,
        },
    )


def get_strategy_cache_stats() -> Dict[str, Any]:
    """Get strategy cache statistics (backward-compatible)."""
    cache = StrategyCache.get_instance()
    return cache.get_stats()


# =============================================================================
# RESPONSE/FOLLOW-UP CACHE COMPATIBILITY
# =============================================================================


def get_cached_response(
    node_name: str,
    core_fields_hash: str,
    follow_up_hash: str,
    user_text_hash: str,
    state: Optional["GraphState"] = None,
    model_id: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Get cached response (backward-compatible signature).

    Wraps ResponseCache.get() with the old function signature.

    Note: The original function took a cache instance as first arg.
    This version uses the global ResponseCache singleton.

    Args:
        node_name: Name of the node that generated the response
        core_fields_hash: Hash of core trip fields
        follow_up_hash: Hash of follow-up context
        user_text_hash: Hash of user text
        state: Optional GraphState for metadata updates
        model_id: LLM model ID for cache isolation

    Returns:
        Cached response dict or None if not found/invalid
    """
    cache = ResponseCache.get_instance()

    key = cache.compute_key(
        node_name=node_name,
        core_fields_hash=core_fields_hash,
        follow_up_hash=follow_up_hash,
        user_text_hash=user_text_hash,
        model_id=model_id,
    )

    return cache.get(key, state)


def set_cached_response(
    node_name: str,
    core_fields_hash: str,
    follow_up_hash: str,
    user_text_hash: str,
    response: Dict[str, Any],
    model_id: str = "",
) -> None:
    """
    Cache response (backward-compatible signature).

    Wraps ResponseCache.set() with the old function signature.

    Note: The original function took a cache instance as first arg.
    This version uses the global ResponseCache singleton.

    Args:
        node_name: Name of the node that generated the response
        core_fields_hash: Hash of core trip fields
        follow_up_hash: Hash of follow-up context
        user_text_hash: Hash of user text
        response: Response dict to cache
        model_id: LLM model ID for cache isolation
    """
    cache = ResponseCache.get_instance()

    key = cache.compute_key(
        node_name=node_name,
        core_fields_hash=core_fields_hash,
        follow_up_hash=follow_up_hash,
        user_text_hash=user_text_hash,
        model_id=model_id,
    )

    cache.set(key, response)


def get_response_cache_stats() -> Dict[str, Any]:
    """Get response cache statistics (backward-compatible)."""
    cache = ResponseCache.get_instance()
    return cache.get_stats()


# =============================================================================
# TILE CACHE COMPATIBILITY
# =============================================================================


def get_tile_cached(
    intent: str,
    destinations: List[str],
    start_date: Optional[str],
    end_date: Optional[str],
    origin: Optional[str],
    adults: Optional[int],
    children: Optional[int],
    state: Optional["GraphState"] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get cached tile result (backward-compatible signature).

    Wraps TileCache.get() with the old function signature.

    Args:
        intent: Tile intent (hotels, flights, etc.)
        destinations: List of destination cities
        start_date: Trip start date
        end_date: Trip end date
        origin: Trip origin
        adults: Number of adults
        children: Number of children
        state: Optional GraphState for metadata updates

    Returns:
        Cached tile result or None if not found/invalid
    """
    cache = TileCache.get_instance()

    # Compute query hash from parameters
    # v2: Include end_date, adults, children for correct tile prices/night counts
    query_str = (
        f"{intent}|"
        f"{','.join(sorted(destinations or []))}|"
        f"{start_date or 'none'}|"
        f"{end_date or 'none'}|"
        f"{origin or 'none'}|"
        f"{adults or 0}|"
        f"{children or 0}"
    )
    query_hash = hashlib.md5(query_str.encode()).hexdigest()[:16]

    # Use a session placeholder since tile cache is session-scoped
    session_id = "global"

    key = cache.compute_key(
        session_id=session_id,
        tile_type=intent,
        query_hash=query_hash,
    )

    return cache.get(key, state)


def set_tile_cached(
    intent: str,
    destinations: List[str],
    start_date: Optional[str],
    end_date: Optional[str],
    origin: Optional[str],
    adults: Optional[int],
    children: Optional[int],
    result: Dict[str, Any],
) -> None:
    """
    Cache tile result (backward-compatible signature).

    Wraps TileCache.set() with the old function signature.

    Args:
        intent: Tile intent (hotels, flights, etc.)
        destinations: List of destination cities
        start_date: Trip start date
        end_date: Trip end date
        origin: Trip origin
        adults: Number of adults
        children: Number of children
        result: Tile result to cache
    """
    cache = TileCache.get_instance()

    # Compute query hash from parameters
    # v2: Include end_date, adults, children for correct tile prices/night counts
    query_str = (
        f"{intent}|"
        f"{','.join(sorted(destinations or []))}|"
        f"{start_date or 'none'}|"
        f"{end_date or 'none'}|"
        f"{origin or 'none'}|"
        f"{adults or 0}|"
        f"{children or 0}"
    )
    query_hash = hashlib.md5(query_str.encode()).hexdigest()[:16]

    # Use a session placeholder since tile cache is session-scoped
    session_id = "global"

    key = cache.compute_key(
        session_id=session_id,
        tile_type=intent,
        query_hash=query_hash,
    )

    cache.set(
        key,
        result,
        extra={
            "intent": intent,
            "destinations": destinations,
            "start_date": start_date,
            "end_date": end_date,
            "origin": origin,
            "adults": adults,
            "children": children,
        },
    )


def get_tile_cache_stats() -> Dict[str, Any]:
    """Get tile cache statistics (backward-compatible)."""
    cache = TileCache.get_instance()
    return cache.get_stats()


def clear_tile_cache() -> int:
    """Clear tile cache and return count of cleared entries."""
    cache = TileCache.get_instance()
    count = len(cache._cache)
    cache.clear()
    return count


# =============================================================================
# GLOBAL CACHE MANAGEMENT COMPATIBILITY
# =============================================================================


def clear_all_caches_compat() -> Dict[str, int]:
    """
    Clear all caches and return counts (backward-compatible).

    Returns:
        Dict mapping cache name to count of cleared entries
    """
    counts = {}

    if ExtractorCache._instance:
        counts["extractor"] = len(ExtractorCache._instance._cache)
        ExtractorCache._instance.clear()

    if StrategyCache._instance:
        counts["strategy"] = len(StrategyCache._instance._cache)
        StrategyCache._instance.clear()

    if ResponseCache._instance:
        counts["response"] = len(ResponseCache._instance._cache)
        ResponseCache._instance.clear()

    if TileCache._instance:
        counts["tile"] = len(TileCache._instance._cache)
        TileCache._instance.clear()

    return counts


def get_all_cache_stats_compat() -> Dict[str, Dict[str, Any]]:
    """
    Get statistics from all caches (backward-compatible).

    Returns:
        Dict mapping cache name to stats dict
    """
    stats = {}

    if ExtractorCache._instance:
        stats["extractor"] = ExtractorCache._instance.get_stats()

    if StrategyCache._instance:
        stats["strategy"] = StrategyCache._instance.get_stats()

    if ResponseCache._instance:
        stats["response"] = ResponseCache._instance.get_stats()

    if TileCache._instance:
        stats["tile"] = TileCache._instance.get_stats()

    return stats
