"""
Unified Caching Framework - P2 Module Extraction.

This module provides a unified caching infrastructure that consolidates
the 4 parallel cache systems from plan_graph.py into a single, reusable
framework with consistent behavior.

Key Benefits:
- Single source of truth for cache behavior
- Consistent version validation across all caches
- Unified statistics and observability
- Reduced code duplication (~300 lines saved per cache type)

Usage:
    from app.planner.cache import ResponseCache, ExtractorCache, StrategyCache

    # Get cached value
    result = ResponseCache.get(key, state)
    if result is None:
        result = compute_expensive_value()
        ResponseCache.set(key, result)

    # Get stats
    stats = ResponseCache.get_stats()
"""

from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Generic, List, Optional, TypeVar

from cachetools import TTLCache

if TYPE_CHECKING:
    from app.plan_graph import GraphState


# =============================================================================
# VERSION CONSTANTS (imported from plan_graph at runtime to avoid cycles)
# =============================================================================


def _get_cache_schema_version() -> int:
    """Get CACHE_SCHEMA_VERSION from plan_graph (deferred import)."""
    from app.plan_graph import CACHE_SCHEMA_VERSION

    return CACHE_SCHEMA_VERSION


def _get_prompt_bundle_hash() -> str:
    """Get PROMPT_BUNDLE_HASH from plan_graph (deferred import)."""
    from app.plan_graph import PROMPT_BUNDLE_HASH

    return PROMPT_BUNDLE_HASH


def _get_planner_build_id() -> str:
    """Get PLANNER_BUILD_ID from plan_graph (deferred import)."""
    from app.plan_graph import PLANNER_BUILD_ID

    return PLANNER_BUILD_ID


def _get_node_logic_version(node_name: str) -> int:
    """Get NODE_LOGIC_VERSION[node] from plan_graph (deferred import)."""
    from app.plan_graph import NODE_LOGIC_VERSION

    return NODE_LOGIC_VERSION.get(node_name, 0)


# =============================================================================
# CACHE DISCARD REASONS
# =============================================================================


class DiscardReason(str, Enum):
    """Reasons for discarding a cached entry during validation."""

    SCHEMA_VERSION_MISMATCH = "schema_version_mismatch"
    PROMPT_BUNDLE_HASH_MISMATCH = "prompt_bundle_hash_mismatch"
    PLANNER_BUILD_ID_MISMATCH = "planner_build_id_mismatch"
    LOGIC_VERSION_MISMATCH = "logic_version_mismatch"
    PAYLOAD_CORRUPT = "payload_corrupt"
    EXPIRED = "expired"


# =============================================================================
# CACHE STATISTICS
# =============================================================================


@dataclass
class CacheStats:
    """Statistics for a single cache instance.

    Tracks hits, misses, discards, and evictions for observability.
    Thread-safe counters would require threading.Lock in production.
    """

    hits: int = 0
    misses: int = 0
    discards: int = 0
    evictions: int = 0
    sets: int = 0

    def hit_rate(self) -> float:
        """Calculate hit rate as hits / (hits + misses)."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    def record_hit(self) -> None:
        """Record a cache hit."""
        self.hits += 1

    def record_miss(self) -> None:
        """Record a cache miss."""
        self.misses += 1

    def record_discard(self) -> None:
        """Record a cache discard (stale entry)."""
        self.discards += 1

    def record_eviction(self) -> None:
        """Record a cache eviction (capacity limit)."""
        self.evictions += 1

    def record_set(self) -> None:
        """Record a cache set operation."""
        self.sets += 1

    def reset(self) -> None:
        """Reset all counters to zero."""
        self.hits = 0
        self.misses = 0
        self.discards = 0
        self.evictions = 0
        self.sets = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "discards": self.discards,
            "evictions": self.evictions,
            "sets": self.sets,
            "hit_rate": self.hit_rate(),
        }


# =============================================================================
# CACHE EVENTS (PER-TURN OBSERVABILITY)
# =============================================================================


@dataclass
class CacheEvent:
    """A single cache event for per-turn observability."""

    node: str
    action: str  # hit, miss, discard, evict, set
    reason: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "node": self.node,
            "action": self.action,
            "reason": self.reason,
            "ts": self.timestamp,
        }


class CacheEventTracker:
    """Tracks cache events for current turn.

    Events are accumulated during turn execution and cleared at turn start.
    """

    def __init__(self) -> None:
        self._events: List[CacheEvent] = []

    def record(self, node: str, action: str, reason: Optional[str] = None) -> None:
        """Record a cache event."""
        self._events.append(CacheEvent(node=node, action=action, reason=reason))

    def get_events(self) -> List[Dict[str, Any]]:
        """Get all events as dictionaries."""
        return [e.to_dict() for e in self._events]

    def clear(self) -> None:
        """Clear events for new turn."""
        self._events.clear()

    def summarize(self) -> Dict[str, Any]:
        """Summarize events into per-node totals.

        Returns:
            Dict with:
            - by_node: {node: {hit, miss, discard, evict, set}}
            - by_reason: {reason: count}
            - hit_rate_by_node: {node: float}
        """
        by_node: Dict[str, Dict[str, int]] = {}
        by_reason: Dict[str, int] = {}

        for event in self._events:
            if event.node not in by_node:
                by_node[event.node] = {"hit": 0, "miss": 0, "discard": 0, "evict": 0, "set": 0}

            if event.action in by_node[event.node]:
                by_node[event.node][event.action] += 1

            if event.reason:
                reason_base = event.reason.split(":")[0]
                by_reason[reason_base] = by_reason.get(reason_base, 0) + 1

        # Calculate hit rates
        hit_rate_by_node = {}
        for node, counts in by_node.items():
            total = counts["hit"] + counts["miss"]
            hit_rate_by_node[node] = counts["hit"] / total if total > 0 else 0.0

        return {
            "by_node": by_node,
            "by_reason": by_reason,
            "hit_rate_by_node": hit_rate_by_node,
        }


# Global event tracker (singleton pattern)
_event_tracker = CacheEventTracker()


def get_cache_events_this_turn() -> List[Dict[str, Any]]:
    """Get cache events for current turn."""
    return _event_tracker.get_events()


def clear_cache_events_this_turn() -> None:
    """Clear cache events at start of new turn."""
    _event_tracker.clear()


def summarize_cache_events() -> Dict[str, Any]:
    """Summarize cache events into dashboard-friendly totals."""
    return _event_tracker.summarize()


# =============================================================================
# CACHE PAYLOAD WRAPPER
# =============================================================================


@dataclass
class CachePayload:
    """Wrapper for cached data with version metadata.

    All cached values are wrapped in this structure to enable
    version validation and safe invalidation on deploy.
    """

    payload_kind: str  # e.g., "response", "extractor", "strategy"
    node_name: str
    schema_version: int
    logic_version: int
    prompt_bundle_hash: str
    planner_build_id: str
    created_at: float
    data: Any
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "payload_kind": self.payload_kind,
            "node_name": self.node_name,
            "schema_version": self.schema_version,
            "logic_version": self.logic_version,
            "prompt_bundle_hash": self.prompt_bundle_hash,
            "planner_build_id": self.planner_build_id,
            "created_at": self.created_at,
            "data": self.data,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Optional["CachePayload"]:
        """Create from dictionary, returning None if invalid."""
        try:
            return cls(
                payload_kind=d.get("payload_kind", "unknown"),
                node_name=d.get("node_name", "unknown"),
                schema_version=d.get("schema_version", 0),
                logic_version=d.get("logic_version", 0),
                prompt_bundle_hash=d.get("prompt_bundle_hash", ""),
                planner_build_id=d.get("planner_build_id", ""),
                created_at=d.get("created_at", 0.0),
                data=d.get("data"),
                extra=d.get("extra", {}),
            )
        except Exception:
            return None


# =============================================================================
# ABSTRACT CACHE NODE BASE CLASS
# =============================================================================

T = TypeVar("T")


class CacheNode(ABC, Generic[T]):
    """Abstract base class for all cache nodes.

    Provides consistent behavior for:
    - Key computation with version isolation
    - Payload wrapping and validation
    - Statistics tracking
    - Event recording for observability

    Subclasses implement:
    - compute_key_parts(): Return key components for hashing
    - get_node_name(): Return node name for stats
    - get_payload_kind(): Return payload type identifier

    Example subclass:
        class ExtractorCache(CacheNode[Dict[str, Any]]):
            def get_node_name(self) -> str:
                return "extractor"

            def get_payload_kind(self) -> str:
                return "extractor"

            def compute_key_parts(self, session_id: str, text: str, ...) -> str:
                return f"{session_id}|{hash(text)}|..."
    """

    def __init__(
        self,
        maxsize: int,
        ttl: float,
        *,
        validate_versions: bool = True,
    ) -> None:
        """Initialize cache with size and TTL.

        Args:
            maxsize: Maximum number of entries
            ttl: Time-to-live in seconds
            validate_versions: Whether to validate version fields on get
        """
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)
        self._stats = CacheStats()
        self._maxsize = maxsize
        self._ttl = ttl
        self._validate_versions = validate_versions

    @abstractmethod
    def get_node_name(self) -> str:
        """Return the node name for this cache (e.g., 'extractor')."""
        ...

    @abstractmethod
    def get_payload_kind(self) -> str:
        """Return the payload kind identifier (e.g., 'extractor')."""
        ...

    def compute_key(self, *args: Any, **kwargs: Any) -> str:
        """Compute cache key from arguments.

        Combines node-specific key parts with version identifiers
        to ensure cache isolation across deploys.
        """
        key_parts = self._compute_key_parts(*args, **kwargs)
        node_version = _get_node_logic_version(self.get_node_name())

        full_key = (
            f"{self.get_payload_kind()}_v6|{key_parts}|"
            f"v{_get_cache_schema_version()}.{node_version}|"
            f"{_get_prompt_bundle_hash()}|{_get_planner_build_id()}"
        )
        return hashlib.md5(full_key.encode()).hexdigest()

    @abstractmethod
    def _compute_key_parts(self, *args: Any, **kwargs: Any) -> str:
        """Compute node-specific key parts (without version info).

        Subclasses implement this to define their key structure.
        """
        ...

    def get(
        self,
        key: str,
        state: Optional["GraphState"] = None,
    ) -> Optional[T]:
        """Get cached value if valid.

        Args:
            key: Cache key from compute_key()
            state: Optional GraphState for metadata updates

        Returns:
            Cached data or None if not found/invalid
        """
        cached_raw = self._cache.get(key)

        if cached_raw is None:
            self._stats.record_miss()
            _event_tracker.record(self.get_node_name(), "miss")
            return None

        # Parse and validate payload
        if isinstance(cached_raw, dict):
            payload = CachePayload.from_dict(cached_raw)
            if payload is None:
                self._discard(key, DiscardReason.PAYLOAD_CORRUPT)
                return None

            if self._validate_versions:
                discard_reason = self._validate_payload(payload)
                if discard_reason:
                    self._discard(key, discard_reason)
                    return None

            # Extract data from payload
            result = payload.data
        else:
            # Legacy format (pre-payload wrapper)
            result = cached_raw

        self._stats.record_hit()
        _event_tracker.record(self.get_node_name(), "hit")

        # Update state metadata if provided
        if state is not None:
            self._update_state_on_hit(state)

        return result

    def set(
        self,
        key: str,
        value: T,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Set cached value with version metadata.

        Args:
            key: Cache key from compute_key()
            value: Data to cache
            extra: Optional extra metadata to store
        """
        payload = CachePayload(
            payload_kind=self.get_payload_kind(),
            node_name=self.get_node_name(),
            schema_version=_get_cache_schema_version(),
            logic_version=_get_node_logic_version(self.get_node_name()),
            prompt_bundle_hash=_get_prompt_bundle_hash(),
            planner_build_id=_get_planner_build_id(),
            created_at=time.time(),
            data=value,
            extra=extra or {},
        )

        self._cache[key] = payload.to_dict()
        self._stats.record_set()
        _event_tracker.record(self.get_node_name(), "set")

    def invalidate(self, key: str) -> bool:
        """Remove a specific key from cache.

        Returns:
            True if key was present and removed
        """
        try:
            del self._cache[key]
            self._stats.record_eviction()
            _event_tracker.record(self.get_node_name(), "evict", "manual")
            return True
        except KeyError:
            return False

    def clear(self) -> None:
        """Clear all entries from cache."""
        self._cache.clear()

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with hits, misses, discards, hit_rate, cache_size, etc.
        """
        stats = self._stats.to_dict()
        stats.update(
            {
                "cache_size": len(self._cache),
                "max_size": self._maxsize,
                "ttl_seconds": self._ttl,
                "schema_version": _get_cache_schema_version(),
            }
        )
        return stats

    def reset_stats(self) -> None:
        """Reset statistics counters."""
        self._stats.reset()

    def _validate_payload(self, payload: CachePayload) -> Optional[DiscardReason]:
        """Validate payload version fields.

        Returns:
            DiscardReason if invalid, None if valid
        """
        if payload.schema_version != _get_cache_schema_version():
            return DiscardReason.SCHEMA_VERSION_MISMATCH

        if payload.prompt_bundle_hash != _get_prompt_bundle_hash():
            return DiscardReason.PROMPT_BUNDLE_HASH_MISMATCH

        if payload.planner_build_id != _get_planner_build_id():
            return DiscardReason.PLANNER_BUILD_ID_MISMATCH

        expected_logic_version = _get_node_logic_version(self.get_node_name())
        if payload.logic_version != expected_logic_version:
            return DiscardReason.LOGIC_VERSION_MISMATCH

        return None

    def _discard(self, key: str, reason: DiscardReason) -> None:
        """Discard a cached entry and record the event."""
        try:
            del self._cache[key]
        except KeyError:
            pass
        self._stats.record_discard()
        _event_tracker.record(self.get_node_name(), "discard", reason.value)

    def _update_state_on_hit(self, state: "GraphState") -> None:
        """Update GraphState metadata on cache hit.

        Subclasses can override for node-specific behavior.
        """
        # Import here to avoid circular dependencies
        from app.plan_graph import _increment_cache_hits

        _increment_cache_hits(state)


# =============================================================================
# CONCRETE CACHE IMPLEMENTATIONS
# =============================================================================


class ResponseCache(CacheNode[Dict[str, Any]]):
    """Cache for specialist/follow-up LLM responses.

    Key components:
    - node_name: Which node generated the response
    - core_fields_hash: Hash of current trip state
    - follow_up_hash: Hash of follow-up question context
    - user_text_hash: Hash of user input
    """

    _instance: Optional["ResponseCache"] = None

    def __init__(self, maxsize: int = 500, ttl: float = 1800.0) -> None:
        super().__init__(maxsize=maxsize, ttl=ttl)

    @classmethod
    def get_instance(cls) -> "ResponseCache":
        """Get singleton instance."""
        if cls._instance is None:
            from app.config import settings

            cls._instance = cls(
                maxsize=settings.response_cache_maxsize,
                ttl=settings.response_cache_ttl_seconds,
            )
        return cls._instance

    def get_node_name(self) -> str:
        return "response"

    def get_payload_kind(self) -> str:
        return "response"

    def _compute_key_parts(
        self,
        node_name: str,
        core_fields_hash: str,
        follow_up_hash: str,
        user_text_hash: str,
    ) -> str:
        """Compute key parts for response cache."""
        return f"{node_name}|{core_fields_hash}|{follow_up_hash}|{user_text_hash}"

    def _update_state_on_hit(self, state: "GraphState") -> None:
        super()._update_state_on_hit(state)
        state.metadata["response_cache_hit"] = True


class ExtractorCache(CacheNode[Dict[str, Any]]):
    """Cache for extractor LLM results.

    Key components:
    - session_id: Session isolation
    - user_text_hash: Input isolation
    - core_fields_hash: State isolation
    - extractor_mode: light/full
    - model_id: Model isolation
    """

    _instance: Optional["ExtractorCache"] = None

    def __init__(self, maxsize: int = 500, ttl: float = 3600.0) -> None:
        super().__init__(maxsize=maxsize, ttl=ttl)

    @classmethod
    def get_instance(cls) -> "ExtractorCache":
        """Get singleton instance."""
        if cls._instance is None:
            from app.config import settings

            cls._instance = cls(
                maxsize=settings.extractor_cache_maxsize,
                ttl=settings.extractor_cache_ttl_seconds,
            )
        return cls._instance

    def get_node_name(self) -> str:
        return "extractor"

    def get_payload_kind(self) -> str:
        return "extractor"

    def _compute_key_parts(
        self,
        session_id: str,
        user_text: str,
        core_fields_hash: str,
        extractor_mode: str,
        model_id: str,
    ) -> str:
        """Compute key parts for extractor cache."""
        text_hash = hashlib.md5(user_text.encode()).hexdigest()[:16]
        return f"{session_id}|{text_hash}|{core_fields_hash}|{extractor_mode}|{model_id}"

    def _update_state_on_hit(self, state: "GraphState") -> None:
        super()._update_state_on_hit(state)
        state.metadata["extractor_cache_hit"] = True


class StrategyCache(CacheNode[Dict[str, Any]]):
    """Cache for strategy LLM results.

    Key components:
    - session_id: Session isolation
    - topic: Strategy topic (hiking, diving, etc.)
    - core_fields_hash: State isolation
    - user_text_hash: Input isolation
    - section_id: Stage identifier
    - stage0_lifecycle_hash: Prevents resurrection after answer
    - model_id: Model isolation
    """

    _instance: Optional["StrategyCache"] = None

    def __init__(self, maxsize: int = 200, ttl: float = 300.0) -> None:
        super().__init__(maxsize=maxsize, ttl=ttl)

    @classmethod
    def get_instance(cls) -> "StrategyCache":
        """Get singleton instance."""
        if cls._instance is None:
            from app.config import settings

            cls._instance = cls(
                maxsize=settings.strategy_cache_maxsize,
                ttl=settings.strategy_cache_ttl_seconds,
            )
        return cls._instance

    def get_node_name(self) -> str:
        return "strategy"

    def get_payload_kind(self) -> str:
        return "strategy"

    def _compute_key_parts(
        self,
        session_id: str,
        topic: str,
        core_fields_hash: str,
        user_text_hash: str,
        section_id: Optional[str],
        stage0_lifecycle_hash: Optional[str],
        model_id: str,
    ) -> str:
        """Compute key parts for strategy cache."""
        section_part = section_id or "stage1"
        lifecycle_part = stage0_lifecycle_hash or "none"
        return (
            f"{session_id}|{topic}|{core_fields_hash}|{user_text_hash}"
            f"|{section_part}|{lifecycle_part}|{model_id}"
        )


class TileCache(CacheNode[Dict[str, Any]]):
    """Cache for tile API results.

    Key components:
    - session_id: Session isolation
    - tile_type: Type of tile (hotel, flight, etc.)
    - query_hash: Hash of query parameters
    """

    _instance: Optional["TileCache"] = None

    def __init__(self, maxsize: int = 100, ttl: float = 300.0) -> None:
        super().__init__(maxsize=maxsize, ttl=ttl)

    @classmethod
    def get_instance(cls) -> "TileCache":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls(maxsize=100, ttl=300.0)
        return cls._instance

    def get_node_name(self) -> str:
        return "tile"

    def get_payload_kind(self) -> str:
        return "tile"

    def _compute_key_parts(
        self,
        session_id: str,
        tile_type: str,
        query_hash: str,
    ) -> str:
        """Compute key parts for tile cache."""
        return f"{session_id}|{tile_type}|{query_hash}"


# =============================================================================
# GLOBAL CACHE MANAGEMENT
# =============================================================================


def clear_all_caches() -> None:
    """Clear all cache instances."""
    if ResponseCache._instance:
        ResponseCache._instance.clear()
    if ExtractorCache._instance:
        ExtractorCache._instance.clear()
    if StrategyCache._instance:
        StrategyCache._instance.clear()
    if TileCache._instance:
        TileCache._instance.clear()


def reset_all_cache_stats() -> None:
    """Reset statistics for all cache instances."""
    if ResponseCache._instance:
        ResponseCache._instance.reset_stats()
    if ExtractorCache._instance:
        ExtractorCache._instance.reset_stats()
    if StrategyCache._instance:
        StrategyCache._instance.reset_stats()
    if TileCache._instance:
        TileCache._instance.reset_stats()


def get_all_cache_stats() -> Dict[str, Dict[str, Any]]:
    """Get statistics from all cache instances.

    Returns:
        Dict mapping cache name to stats dict
    """
    stats = {}

    if ResponseCache._instance:
        stats["response"] = ResponseCache._instance.get_stats()
    if ExtractorCache._instance:
        stats["extractor"] = ExtractorCache._instance.get_stats()
    if StrategyCache._instance:
        stats["strategy"] = StrategyCache._instance.get_stats()
    if TileCache._instance:
        stats["tile"] = TileCache._instance.get_stats()

    return stats
