"""
Tests for CachePayload V6 Migration (PR1).

Verifies:
- Cache hit path and forced miss conditions
- Version-based cache invalidation (prompt_bundle_hash, planner_build_id,
  schema_version, logic_version)
- Stale-but-valid prevention (missing_all drift, ready_state flip)
- Per-node cache event tracking
"""

import hashlib
import time


class TestExtractorCacheV6:
    """Tests for V6 extractor cache with version validation."""

    def test_extractor_cache_hit_path(self):
        """Extractor cache returns result on valid hit."""
        from app.plan_graph import (
            _get_extractor_cached,
            _set_extractor_cached,
            clear_response_caches,
        )

        clear_response_caches()

        session_id = "test-session-1"
        user_text = "I want to go to Paris next week"
        core_hash = "abc123"
        mode = "light"

        # Set cache
        result = {"parsed": {"destinations": ["Paris"]}, "confidence": {"overall": 0.9}}
        _set_extractor_cached(session_id, user_text, core_hash, mode, result)

        # Get cache - should hit
        cached = _get_extractor_cached(session_id, user_text, core_hash, mode)
        assert cached is not None
        assert cached["parsed"]["destinations"] == ["Paris"]

    def test_extractor_cache_miss_on_user_text_change(self):
        """Extractor cache misses when user text changes."""
        from app.plan_graph import (
            _get_extractor_cached,
            _set_extractor_cached,
            clear_response_caches,
        )

        clear_response_caches()

        session_id = "test-session-1"
        user_text = "I want to go to Paris"
        core_hash = "abc123"
        mode = "light"

        result = {"parsed": {"destinations": ["Paris"]}, "confidence": {"overall": 0.9}}
        _set_extractor_cached(session_id, user_text, core_hash, mode, result)

        # Different user text - should miss
        cached = _get_extractor_cached(session_id, "Different text", core_hash, mode)
        assert cached is None

    def test_extractor_cache_miss_on_core_hash_change(self):
        """Extractor cache misses when core_hash changes."""
        from app.plan_graph import (
            _get_extractor_cached,
            _set_extractor_cached,
            clear_response_caches,
        )

        clear_response_caches()

        session_id = "test-session-1"
        user_text = "I want to go to Paris"
        core_hash = "abc123"
        mode = "light"

        result = {"parsed": {"destinations": ["Paris"]}, "confidence": {"overall": 0.9}}
        _set_extractor_cached(session_id, user_text, core_hash, mode, result)

        # Different core_hash - should miss
        cached = _get_extractor_cached(session_id, user_text, "different_hash", mode)
        assert cached is None

    def test_extractor_cache_miss_on_prompt_bundle_hash_mismatch(self):
        """Extractor cache discards entry when prompt_bundle_hash mismatches."""
        from app.plan_graph import (
            PROMPT_BUNDLE_HASH,
            _extractor_cache,
            _get_extractor_cached,
            clear_response_caches,
        )

        clear_response_caches()

        # Manually insert a payload with different prompt_bundle_hash
        session_id = "test-session-1"
        user_text = "I want to go to Paris"
        core_hash = "abc123"
        mode = "light"
        model_id = "gpt-4o-mini"

        # Compute the key manually (matching V6 key computation)
        text_hash = hashlib.md5(user_text.encode()).hexdigest()[:16]
        key_parts = (
            f"extractor_v6|{session_id}|{text_hash}|{core_hash}|{mode}|"
            f"{model_id}|v1.1|{PROMPT_BUNDLE_HASH}|dev"
        )
        cache_key = hashlib.md5(key_parts.encode()).hexdigest()

        # Insert with WRONG prompt_bundle_hash
        stale_payload = {
            "payload_kind": "extractor",
            "schema_version": 1,
            "prompt_bundle_hash": "WRONG_HASH_12345",  # Mismatch!
            "planner_build_id": "dev",
            "extra": {"extraction_result": {"parsed": {}}},
        }
        _extractor_cache[cache_key] = stale_payload

        # Get should discard due to hash mismatch
        cached = _get_extractor_cached(session_id, user_text, core_hash, mode)

        # The key mismatch means it won't find it anyway (key includes hash)
        # But if found with wrong hash, should discard
        assert cached is None

    def test_extractor_cache_stats_tracked(self):
        """Extractor cache tracks hits, misses, and discards."""
        from app.plan_graph import (
            _cache_stats,
            _get_extractor_cached,
            _set_extractor_cached,
            clear_response_caches,
        )

        clear_response_caches()

        # Initial state
        assert _cache_stats["extractor"]["hits"] == 0
        assert _cache_stats["extractor"]["misses"] == 0

        session_id = "test-session-1"
        user_text = "I want to go to Paris"
        core_hash = "abc123"
        mode = "light"

        # Miss
        _get_extractor_cached(session_id, user_text, core_hash, mode)
        assert _cache_stats["extractor"]["misses"] == 1

        # Set and hit
        _set_extractor_cached(session_id, user_text, core_hash, mode, {"parsed": {}})
        _get_extractor_cached(session_id, user_text, core_hash, mode)
        assert _cache_stats["extractor"]["hits"] == 1


class TestStrategyCacheV6:
    """Tests for V6 strategy cache with lifecycle hash."""

    def test_strategy_cache_hit_path(self):
        """Strategy cache returns result on valid hit."""
        from app.plan_graph import (
            _get_strategy_cached,
            _set_strategy_cached,
            clear_response_caches,
        )

        clear_response_caches()

        session_id = "test-session-1"
        topic = "hiking"
        core_hash = "abc123"
        user_text_hash = "def456"

        result = {"assistant_message": "Great hiking options!", "suggested_responses": []}
        _set_strategy_cached(session_id, topic, core_hash, user_text_hash, result)

        # Get cache - should hit
        cached = _get_strategy_cached(session_id, topic, core_hash, user_text_hash)
        assert cached is not None
        assert cached["assistant_message"] == "Great hiking options!"

    def test_strategy_cache_miss_on_topic_change(self):
        """Strategy cache misses when topic changes."""
        from app.plan_graph import (
            _get_strategy_cached,
            _set_strategy_cached,
            clear_response_caches,
        )

        clear_response_caches()

        session_id = "test-session-1"
        topic = "hiking"
        core_hash = "abc123"
        user_text_hash = "def456"

        result = {"assistant_message": "Great hiking options!", "suggested_responses": []}
        _set_strategy_cached(session_id, topic, core_hash, user_text_hash, result)

        # Different topic - should miss
        cached = _get_strategy_cached(session_id, "diving", core_hash, user_text_hash)
        assert cached is None

    def test_strategy_cache_stats_tracked(self):
        """Strategy cache tracks hits and misses."""
        from app.plan_graph import (
            _cache_stats,
            _get_strategy_cached,
            _set_strategy_cached,
            clear_response_caches,
        )

        clear_response_caches()

        assert _cache_stats["strategy"]["hits"] == 0
        assert _cache_stats["strategy"]["misses"] == 0

        session_id = "test-session-1"
        topic = "hiking"
        core_hash = "abc123"
        user_text_hash = "def456"

        # Miss
        _get_strategy_cached(session_id, topic, core_hash, user_text_hash)
        assert _cache_stats["strategy"]["misses"] == 1

        # Set and hit
        _set_strategy_cached(session_id, topic, core_hash, user_text_hash, {"result": "ok"})
        _get_strategy_cached(session_id, topic, core_hash, user_text_hash)
        assert _cache_stats["strategy"]["hits"] == 1


class TestTileCacheV6:
    """Tests for V6 tile cache with bounded TTL."""

    def test_tile_cache_is_bounded(self):
        """Tile cache uses TTLCache with maxsize."""
        from app.plan_graph import _TILE_CACHE_MAXSIZE, _TILE_CACHE_TTL, _tile_cache

        assert _TILE_CACHE_MAXSIZE == 100
        assert _TILE_CACHE_TTL == 300  # 5 minutes
        assert hasattr(_tile_cache, "ttl")  # TTLCache attribute

    def test_tile_cache_set_and_get(self):
        """Tile cache set and get work correctly."""
        from app.plan_graph import (
            clear_tile_cache,
            get_tile_cache_stats,
            set_tile_cached,
        )

        clear_tile_cache()

        intent = "hotels"
        destinations = ["Paris", "Rome"]
        start_date = "2025-03-15"
        origin = "New York"
        result = {"tiles": [{"id": "tile1"}, {"id": "tile2"}]}

        set_tile_cached(intent, destinations, start_date, origin, result)

        stats = get_tile_cache_stats()
        assert stats["cache_size"] == 1

    def test_tile_cache_stats_include_schema_version(self):
        """Tile cache stats include V6 version info."""
        from app.plan_graph import CACHE_SCHEMA_VERSION, get_tile_cache_stats

        stats = get_tile_cache_stats()

        assert "schema_version" in stats
        assert stats["schema_version"] == CACHE_SCHEMA_VERSION
        assert "hits" in stats
        assert "misses" in stats
        assert "discards" in stats


class TestCachePayloadV6Fields:
    """Tests for CachePayload V6 unified structure."""

    def test_cache_payload_has_v6_fields(self):
        """CachePayload includes payload_kind, schema_version, etc."""
        # Verify V6 fields exist in dataclass
        import dataclasses

        from app.plan_graph import CachePayload

        field_names = [f.name for f in dataclasses.fields(CachePayload)]

        assert "payload_kind" in field_names
        assert "node_name" in field_names
        assert "schema_version" in field_names
        assert "logic_version" in field_names
        assert "prompt_bundle_hash" in field_names
        assert "planner_build_id" in field_names
        assert "extra" in field_names

    def test_cache_payload_from_dict_backward_compatible(self):
        """CachePayload.from_dict handles legacy payloads without V6 fields."""
        from app.plan_graph import CachePayload

        # Legacy payload (missing V6 fields)
        legacy_data = {
            "assistant_message": "Hello",
            "question_target": "dates",
            "suggested_responses": ["Next week"],
            "suggestion_kind": "dates",
            "suggestion_question_id": 1,
            "thread_id": "abc",
            "user_text_hash": "def",
            "answered_question_target": "dates",
            "answered_missing_all": [],
            "core_hash": "ghi",
            "ready_state_at_write": False,
            "intent": None,
            "model_id": "gpt-4o-mini",
            "last_summary_hash": "jkl",
            "response_text_hash": "mno",
            "suggestions_hash": "pqr",
            "created_at": 1234567890.0,
            "provenance": "cached",
        }

        # Should not raise - backward compatible
        payload = CachePayload.from_dict(legacy_data)

        assert payload.payload_kind == "legacy"
        assert payload.schema_version == 0
        assert payload.extra == {}


class TestCacheEventTracking:
    """Tests for per-turn cache event tracking."""

    def test_cache_events_recorded(self):
        """Cache events are recorded during operations."""
        from app.plan_graph import (
            _record_cache_event,
            clear_cache_events_this_turn,
            get_cache_events_this_turn,
        )

        clear_cache_events_this_turn()

        _record_cache_event("extractor", "hit")
        _record_cache_event("strategy", "miss")
        _record_cache_event("tile", "discard", "schema_version_mismatch")

        events = get_cache_events_this_turn()

        assert len(events) == 3
        assert events[0]["node"] == "extractor"
        assert events[0]["action"] == "hit"
        assert events[1]["node"] == "strategy"
        assert events[1]["action"] == "miss"
        assert events[2]["node"] == "tile"
        assert events[2]["action"] == "discard"
        assert events[2]["reason"] == "schema_version_mismatch"

    def test_cache_events_cleared_between_turns(self):
        """Cache events are cleared between turns."""
        from app.plan_graph import (
            _record_cache_event,
            clear_cache_events_this_turn,
            get_cache_events_this_turn,
        )

        _record_cache_event("extractor", "hit")
        assert len(get_cache_events_this_turn()) >= 1

        clear_cache_events_this_turn()
        assert len(get_cache_events_this_turn()) == 0


class TestCacheValidationV6:
    """Tests for V6 cache payload validation."""

    def test_validate_cache_payload_rejects_schema_version_mismatch(self):
        """Cache validation rejects payload with different schema_version."""
        from app.plan_graph import (
            PLANNER_BUILD_ID,
            PROMPT_BUNDLE_HASH,
            CachePayload,
            GraphState,
            TripInputs,
            _validate_cache_payload,
        )

        state = GraphState(
            session_id="test",
            user_text="hello",
            trip_inputs=TripInputs(),
            metadata={"thread_id": "test"},
        )

        payload = CachePayload(
            payload_kind="required_fields",
            node_name="required_fields",
            schema_version=999,  # Wrong version
            logic_version=1,
            prompt_bundle_hash=PROMPT_BUNDLE_HASH,  # Use correct hash so schema check triggers
            planner_build_id=PLANNER_BUILD_ID,  # Use correct build id
            assistant_message="Hello",
            question_target="dates",
            suggested_responses=[],
            suggestion_kind="dates",
            suggestion_question_id=1,
            thread_id="test",
            user_text_hash="abc",
            answered_question_target="dates",
            answered_missing_all=[],
            core_hash="",
            ready_state_at_write=False,
            intent=None,
            model_id="gpt-4o-mini",
            last_summary_hash="",
            response_text_hash="",
            suggestions_hash="",
            created_at=time.time(),
            extra={},
        )

        is_valid, reason = _validate_cache_payload(
            payload=payload,
            state=state,
            current_question_target="dates",
            current_question_id=1,
            current_missing_all=[],
            current_core_hash="",
            current_ready_state=False,
            node_name="required_fields",
        )

        assert is_valid is False
        assert "schema_version_mismatch" in reason

    def test_validate_cache_payload_rejects_ready_state_mismatch(self):
        """Cache validation rejects payload with different ready_state."""
        from app.plan_graph import (
            CACHE_SCHEMA_VERSION,
            PLANNER_BUILD_ID,
            PROMPT_BUNDLE_HASH,
            CachePayload,
            GraphState,
            TripInputs,
            _validate_cache_payload,
        )

        state = GraphState(
            session_id="test",
            user_text="hello",
            trip_inputs=TripInputs(),
            metadata={"thread_id": "test"},
        )

        payload = CachePayload(
            payload_kind="required_fields",
            node_name="required_fields",
            schema_version=CACHE_SCHEMA_VERSION,
            logic_version=1,
            prompt_bundle_hash=PROMPT_BUNDLE_HASH,
            planner_build_id=PLANNER_BUILD_ID,
            assistant_message="Hello",
            question_target="dates",
            suggested_responses=[],
            suggestion_kind="dates",
            suggestion_question_id=1,
            thread_id="test",
            user_text_hash="5d41402abc4b2a76",  # hash of "hello"  # pragma: allowlist secret
            answered_question_target="dates",
            answered_missing_all=[],
            core_hash="",
            ready_state_at_write=False,  # Payload says NOT ready
            intent=None,
            model_id="gpt-4o-mini",
            last_summary_hash="",
            response_text_hash="",
            suggestions_hash="",
            created_at=time.time(),
            extra={},
        )

        # But current state IS ready
        is_valid, reason = _validate_cache_payload(
            payload=payload,
            state=state,
            current_question_target="dates",
            current_question_id=1,
            current_missing_all=[],
            current_core_hash="",
            current_ready_state=True,  # Mismatch!
            node_name="required_fields",
        )

        assert is_valid is False
        assert "ready_state_mismatch" in reason


class TestNodeLogicVersion:
    """Tests for NODE_LOGIC_VERSION constant."""

    def test_node_logic_version_includes_all_cache_nodes(self):
        """NODE_LOGIC_VERSION includes entries for all cached nodes."""
        from app.plan_graph import NODE_LOGIC_VERSION

        assert "required_fields" in NODE_LOGIC_VERSION
        assert "router" in NODE_LOGIC_VERSION
        assert "extractor" in NODE_LOGIC_VERSION
        assert "strategy" in NODE_LOGIC_VERSION
        assert "tile" in NODE_LOGIC_VERSION

        # All should be integers >= 1
        for _node, version in NODE_LOGIC_VERSION.items():
            assert isinstance(version, int)
            assert version >= 1


class TestGetCacheStats:
    """Tests for unified get_cache_stats function."""

    def test_get_cache_stats_includes_all_caches(self):
        """get_cache_stats returns stats for all V6 caches."""
        from app.plan_graph import get_cache_stats

        stats = get_cache_stats()

        assert "required_fields" in stats
        assert "router" in stats
        assert "extractor" in stats
        assert "strategy" in stats
        assert "tile" in stats
        assert "schema_version" in stats
        assert "prompt_bundle_hash" in stats
        assert "build_id" in stats
        assert "cache_events_this_turn" in stats

    def test_get_cache_stats_includes_size_per_cache(self):
        """Each cache in stats includes current size."""
        from app.plan_graph import get_cache_stats

        stats = get_cache_stats()

        for cache_name in ["required_fields", "router", "extractor", "strategy", "tile"]:
            assert "size" in stats[cache_name]
            assert isinstance(stats[cache_name]["size"], int)
