"""
Unified Caching Package - P2 Module Extraction.

This package provides the unified caching infrastructure for the planner.

Usage:
    from app.planner.cache import (
        ResponseCache,
        ExtractorCache,
        StrategyCache,
        TileCache,
        CacheStats,
        CachePayload,
        DiscardReason,
        clear_all_caches,
        get_all_cache_stats,
    )

    # Using singleton pattern
    cache = ExtractorCache.get_instance()
    key = cache.compute_key(session_id, user_text, core_fields_hash, mode, model)
    result = cache.get(key, state)
    if result is None:
        result = compute_extraction()
        cache.set(key, result)

    # Per-turn observability
    from app.planner.cache import (
        get_cache_events_this_turn,
        clear_cache_events_this_turn,
        summarize_cache_events,
    )
"""

# Compatibility layer for gradual migration from plan_graph.py
from app.planner.cache.compat import (
    # Global management
    clear_all_caches_compat,
    clear_tile_cache,
    get_all_cache_stats_compat,
    # Response cache
    get_cached_response,
    get_extractor_cache_stats,
    # Extractor cache
    get_extractor_cached,
    get_response_cache_stats,
    get_strategy_cache_stats,
    # Strategy cache
    get_strategy_cached,
    get_tile_cache_stats,
    # Tile cache
    get_tile_cached,
    set_cached_response,
    set_extractor_cached,
    set_strategy_cached,
    set_tile_cached,
)
from app.planner.cache.framework import (
    CacheEvent,
    CacheEventTracker,
    # Abstract Base
    CacheNode,
    CachePayload,
    # Stats and Events
    CacheStats,
    # Enums and Types
    DiscardReason,
    ExtractorCache,
    # Concrete Implementations
    ResponseCache,
    StrategyCache,
    TileCache,
    # Global Management
    clear_all_caches,
    clear_cache_events_this_turn,
    get_all_cache_stats,
    # Event Functions
    get_cache_events_this_turn,
    reset_all_cache_stats,
    summarize_cache_events,
)

__all__ = [
    # Enums and Types
    "DiscardReason",
    # Stats and Events
    "CacheStats",
    "CacheEvent",
    "CacheEventTracker",
    "CachePayload",
    # Abstract Base
    "CacheNode",
    # Concrete Implementations
    "ResponseCache",
    "ExtractorCache",
    "StrategyCache",
    "TileCache",
    # Event Functions
    "get_cache_events_this_turn",
    "clear_cache_events_this_turn",
    "summarize_cache_events",
    # Global Management
    "clear_all_caches",
    "reset_all_cache_stats",
    "get_all_cache_stats",
    # Compatibility layer
    "get_extractor_cached",
    "set_extractor_cached",
    "get_extractor_cache_stats",
    "get_strategy_cached",
    "set_strategy_cached",
    "get_strategy_cache_stats",
    "get_cached_response",
    "set_cached_response",
    "get_response_cache_stats",
    "get_tile_cached",
    "set_tile_cached",
    "get_tile_cache_stats",
    "clear_tile_cache",
    "clear_all_caches_compat",
    "get_all_cache_stats_compat",
]
