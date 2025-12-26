# backend/tests/langgraph/test_meta_keys.py
"""
Tests for planner metadata constants and helpers.

PR2: Metadata helpers + centralized turn init
"""


from app.planner.meta import (
    init_turn_metadata,
    meta_append,
    meta_get,
    meta_increment,
    meta_set,
    meta_set_once,
    validate_turn_metadata,
)
from app.planner.meta_keys import (
    ALL_META_KEYS,
    CACHE_EVENTS,
    DELTAS_APPLIED_THIS_TURN,
    DUPLICATION_CLASS,
    LLM_CALL_BLOCKED_REASON,
    LLM_CALL_SITES,
    LLM_CALLS_THIS_TURN,
    NODE_RUN_JOURNAL,
    PER_TURN_KEYS,
    PLANNER_SNAPSHOT,
    RESPONSE_CLAIMED_BY,
    RESPONSE_GENERATION_PROVENANCE,
    RESPONSE_SOURCE_NODE,
    STEP_COUNT,
    TRIPWIRE_TRIGGERED,
    TURN_CANARY,
    VISITED_NODES,
)
from app.planner.test_mode import is_test_mode


class MockState:
    """Mock GraphState for testing metadata helpers."""

    def __init__(self, metadata: dict = None):
        self.metadata = metadata if metadata is not None else {}


class TestMetaKeysUniqueness:
    """Test that all metadata keys are unique."""

    def test_all_meta_keys_unique(self):
        """ALL_META_KEYS should contain no duplicates."""
        assert len(set(ALL_META_KEYS)) == len(ALL_META_KEYS), (
            f"Duplicate keys found in ALL_META_KEYS: "
            f"{[k for k in ALL_META_KEYS if ALL_META_KEYS.count(k) > 1]}"
        )

    def test_per_turn_keys_subset_of_all_keys(self):
        """PER_TURN_KEYS should be a subset of ALL_META_KEYS."""
        all_set = set(ALL_META_KEYS)
        per_turn_set = set(PER_TURN_KEYS)

        missing = per_turn_set - all_set
        assert not missing, f"PER_TURN_KEYS contains keys not in ALL_META_KEYS: {missing}"

    def test_key_constants_are_strings(self):
        """All key constants should be strings."""
        for key in ALL_META_KEYS:
            assert isinstance(key, str), f"Key {key!r} is not a string"

    def test_key_constants_non_empty(self):
        """All key constants should be non-empty strings."""
        for key in ALL_META_KEYS:
            assert key, "Found empty key in ALL_META_KEYS"


class TestInitTurnMetadata:
    """Test init_turn_metadata function."""

    def test_returns_turn_canary(self):
        """init_turn_metadata should return a turn_canary UUID."""
        metadata = {}
        canary = init_turn_metadata(metadata)

        assert isinstance(canary, str)
        assert len(canary) == 32  # UUID hex without hyphens
        assert metadata[TURN_CANARY] == canary

    def test_initializes_llm_budget_keys(self):
        """LLM budget tracking keys should be initialized."""
        metadata = {}
        init_turn_metadata(metadata)

        assert metadata[LLM_CALLS_THIS_TURN] == 0
        assert metadata[LLM_CALL_SITES] == []
        assert metadata[LLM_CALL_BLOCKED_REASON] == {}

    def test_initializes_node_journal_keys(self):
        """Node execution journal keys should be initialized."""
        metadata = {}
        init_turn_metadata(metadata)

        assert metadata[NODE_RUN_JOURNAL] == []
        assert isinstance(metadata[VISITED_NODES], set)
        assert metadata[STEP_COUNT] == 0

    def test_initializes_response_writer_guard(self):
        """Response writer guard should be initialized to None."""
        metadata = {}
        init_turn_metadata(metadata)

        assert metadata[RESPONSE_CLAIMED_BY] is None

    def test_initializes_deltas_tracking(self):
        """Field change tracking should be initialized."""
        metadata = {}
        init_turn_metadata(metadata)

        assert metadata[DELTAS_APPLIED_THIS_TURN] == []

    def test_initializes_response_provenance(self):
        """Response provenance keys should be initialized."""
        metadata = {}
        init_turn_metadata(metadata)

        assert metadata[RESPONSE_SOURCE_NODE] is None
        assert metadata[RESPONSE_GENERATION_PROVENANCE] is None

    def test_clears_tripwire(self):
        """TRIPWIRE_TRIGGERED should be cleared."""
        metadata = {TRIPWIRE_TRIGGERED: "max_steps"}
        init_turn_metadata(metadata)

        assert TRIPWIRE_TRIGGERED not in metadata

    def test_clears_duplication_class(self):
        """DUPLICATION_CLASS should be cleared."""
        metadata = {DUPLICATION_CLASS: "double_writer"}
        init_turn_metadata(metadata)

        assert DUPLICATION_CLASS not in metadata

    def test_planner_snapshot_with_callback(self):
        """PLANNER_SNAPSHOT should be set if callback provided."""
        metadata = {}
        snapshot = {"version": "test", "build_id": "123"}

        init_turn_metadata(metadata, planner_snapshot_fn=lambda: snapshot)

        assert metadata[PLANNER_SNAPSHOT] == snapshot

    def test_planner_snapshot_without_callback(self):
        """PLANNER_SNAPSHOT should not be set if no callback provided."""
        metadata = {}
        init_turn_metadata(metadata)

        # The key might exist with empty value or might not exist
        # depending on implementation
        assert metadata.get(PLANNER_SNAPSHOT) is None or PLANNER_SNAPSHOT not in metadata

    def test_cache_events_initialized(self):
        """CACHE_EVENTS should be initialized to empty list."""
        metadata = {}
        init_turn_metadata(metadata)

        assert metadata[CACHE_EVENTS] == []


class TestValidateTurnMetadata:
    """Test validate_turn_metadata function."""

    def test_valid_metadata_returns_empty_errors(self):
        """Valid metadata should return no errors."""
        metadata = {}
        init_turn_metadata(metadata)

        errors = validate_turn_metadata(metadata)
        assert errors == []

    def test_missing_keys_reported(self):
        """Missing required keys should be reported."""
        metadata = {}  # Empty, missing all required keys

        errors = validate_turn_metadata(metadata)

        assert len(errors) > 0
        assert any(LLM_CALLS_THIS_TURN in e for e in errors)

    def test_wrong_type_reported(self):
        """Wrong types should be reported."""
        metadata = {}
        init_turn_metadata(metadata)
        metadata[LLM_CALLS_THIS_TURN] = "not an int"

        errors = validate_turn_metadata(metadata)

        assert any("wrong type" in e.lower() for e in errors)


class TestMetaHelpers:
    """Test meta_get, meta_set, meta_append, meta_increment helpers."""

    def test_meta_get_returns_value(self):
        """meta_get should return existing value."""
        state = MockState({LLM_CALLS_THIS_TURN: 5})

        result = meta_get(state, LLM_CALLS_THIS_TURN)

        assert result == 5

    def test_meta_get_returns_default(self):
        """meta_get should return default if key missing."""
        state = MockState({})

        result = meta_get(state, LLM_CALLS_THIS_TURN, default=42)

        assert result == 42

    def test_meta_get_handles_missing_metadata_attr(self):
        """meta_get should handle objects without metadata attr."""

        class NoMetadata:
            pass

        result = meta_get(NoMetadata(), LLM_CALLS_THIS_TURN, default=99)

        assert result == 99

    def test_meta_set_sets_value(self):
        """meta_set should set value on metadata."""
        state = MockState({})

        meta_set(state, LLM_CALLS_THIS_TURN, 10)

        assert state.metadata[LLM_CALLS_THIS_TURN] == 10

    def test_meta_append_creates_list(self):
        """meta_append should create list if key missing."""
        state = MockState({})

        meta_append(state, LLM_CALL_SITES, "extractor")

        assert state.metadata[LLM_CALL_SITES] == ["extractor"]

    def test_meta_append_appends_to_existing_list(self):
        """meta_append should append to existing list."""
        state = MockState({LLM_CALL_SITES: ["extractor"]})

        meta_append(state, LLM_CALL_SITES, "router")

        assert state.metadata[LLM_CALL_SITES] == ["extractor", "router"]

    def test_meta_increment_creates_counter(self):
        """meta_increment should create counter if missing."""
        state = MockState({})

        result = meta_increment(state, LLM_CALLS_THIS_TURN)

        assert result == 1
        assert state.metadata[LLM_CALLS_THIS_TURN] == 1

    def test_meta_increment_increments_existing(self):
        """meta_increment should increment existing counter."""
        state = MockState({LLM_CALLS_THIS_TURN: 5})

        result = meta_increment(state, LLM_CALLS_THIS_TURN)

        assert result == 6
        assert state.metadata[LLM_CALLS_THIS_TURN] == 6

    def test_meta_increment_custom_amount(self):
        """meta_increment should support custom increment amount."""
        state = MockState({LLM_CALLS_THIS_TURN: 5})

        result = meta_increment(state, LLM_CALLS_THIS_TURN, amount=3)

        assert result == 8


class TestMetaSetOnce:
    """Test meta_set_once function."""

    def test_sets_value_when_unset(self):
        """meta_set_once should set value when key is not present."""
        state = MockState({})

        result = meta_set_once(state, RESPONSE_CLAIMED_BY, "summarize")

        assert result is True
        assert state.metadata[RESPONSE_CLAIMED_BY] == "summarize"

    def test_returns_true_for_same_value(self):
        """meta_set_once should return True when setting same value."""
        state = MockState({RESPONSE_CLAIMED_BY: "summarize"})

        result = meta_set_once(state, RESPONSE_CLAIMED_BY, "summarize")

        assert result is True

    def test_overwrites_in_prod_by_default(self):
        """meta_set_once should overwrite different value in prod mode."""
        # Ensure we're not in test mode for this test
        import os

        orig = os.environ.get("PYTEST_RUNNING")
        try:
            os.environ.pop("PYTEST_RUNNING", None)

            state = MockState({RESPONSE_CLAIMED_BY: "summarize"})

            # Should overwrite (allow_overwrite_in_prod=True is default)
            result = meta_set_once(
                state, RESPONSE_CLAIMED_BY, "router", allow_overwrite_in_prod=True
            )

            assert result is True
            assert state.metadata[RESPONSE_CLAIMED_BY] == "router"
        finally:
            if orig is not None:
                os.environ["PYTEST_RUNNING"] = orig

    def test_skips_overwrite_when_disabled(self):
        """meta_set_once should skip overwrite when allow_overwrite_in_prod=False."""
        import os

        orig = os.environ.get("PYTEST_RUNNING")
        try:
            os.environ.pop("PYTEST_RUNNING", None)

            state = MockState({RESPONSE_CLAIMED_BY: "summarize"})

            result = meta_set_once(
                state, RESPONSE_CLAIMED_BY, "router", allow_overwrite_in_prod=False
            )

            assert result is False
            assert state.metadata[RESPONSE_CLAIMED_BY] == "summarize"
        finally:
            if orig is not None:
                os.environ["PYTEST_RUNNING"] = orig


class TestIsTestMode:
    """Test is_test_mode helper."""

    def test_returns_true_when_env_set(self):
        """is_test_mode should return True when PYTEST_RUNNING=1."""
        import os

        orig = os.environ.get("PYTEST_RUNNING")
        try:
            os.environ["PYTEST_RUNNING"] = "1"

            assert is_test_mode() is True
        finally:
            if orig is not None:
                os.environ["PYTEST_RUNNING"] = orig
            else:
                os.environ.pop("PYTEST_RUNNING", None)

    def test_returns_false_when_env_not_set(self):
        """is_test_mode should return False when PYTEST_RUNNING not set."""
        import os

        orig = os.environ.get("PYTEST_RUNNING")
        try:
            os.environ.pop("PYTEST_RUNNING", None)

            assert is_test_mode() is False
        finally:
            if orig is not None:
                os.environ["PYTEST_RUNNING"] = orig
