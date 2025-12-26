# backend/tests/langgraph/test_stable_hashing.py
"""
Tests for stable hashing utilities.

PR5: Stable hashing utilities - verifies that hashes are consistent
across invocations and provides proper canonicalization.
"""

import json
import threading

import pytest

from app.planner.hashing import (
    BANNED_PATTERNS,
    canonicalize_destinations,
    canonicalize_dict,
    canonicalize_missing_fields,
    make_cache_key,
    stable_hash,
    stable_hash_index,
    stable_hash_int,
    stable_hash_short,
)


class TestStableHash:
    """Tests for stable_hash function."""

    def test_string_hash_is_stable(self):
        """Same string should always produce same hash."""
        result1 = stable_hash("hello world")
        result2 = stable_hash("hello world")
        assert result1 == result2

    def test_string_hash_default_length(self):
        """Default length should be 16 characters."""
        result = stable_hash("test")
        assert len(result) == 16

    def test_string_hash_custom_length(self):
        """Custom length should be respected."""
        result = stable_hash("test", length=8)
        assert len(result) == 8

        result = stable_hash("test", length=32)
        assert len(result) == 32

    def test_string_hash_max_length(self):
        """Maximum length is 64."""
        result = stable_hash("test", length=64)
        assert len(result) == 64

    def test_string_hash_invalid_length(self):
        """Invalid lengths should raise ValueError."""
        with pytest.raises(ValueError):
            stable_hash("test", length=0)

        with pytest.raises(ValueError):
            stable_hash("test", length=65)

    def test_dict_hash_order_independent(self):
        """Dict hash should be same regardless of key order."""
        dict1 = {"a": 1, "b": 2, "c": 3}
        dict2 = {"c": 3, "a": 1, "b": 2}

        assert stable_hash(dict1) == stable_hash(dict2)

    def test_list_hash_order_dependent(self):
        """List hash should depend on order."""
        list1 = [1, 2, 3]
        list2 = [3, 2, 1]

        assert stable_hash(list1) != stable_hash(list2)

    def test_different_inputs_different_hashes(self):
        """Different inputs should (almost always) produce different hashes."""
        hashes = set()
        for i in range(100):
            hashes.add(stable_hash(f"test-{i}"))

        # All 100 should be unique
        assert len(hashes) == 100

    def test_nested_structure_hash(self):
        """Nested structures should hash correctly."""
        data = {
            "users": [
                {"name": "Alice", "age": 30},
                {"name": "Bob", "age": 25},
            ],
            "count": 2,
        }

        result1 = stable_hash(data)
        result2 = stable_hash(data)
        assert result1 == result2

    def test_none_hash(self):
        """None should hash to a stable value."""
        result1 = stable_hash(None)
        result2 = stable_hash(None)
        assert result1 == result2

    def test_empty_collections(self):
        """Empty collections should hash distinctly."""
        empty_dict = stable_hash({})
        empty_list = stable_hash([])
        empty_str = stable_hash("")

        # All different
        assert len({empty_dict, empty_list, empty_str}) == 3


class TestStableHashShort:
    """Tests for stable_hash_short function."""

    def test_short_hash_length(self):
        """Short hash should be 8 characters."""
        result = stable_hash_short("test")
        assert len(result) == 8

    def test_short_hash_is_stable(self):
        """Short hash should be stable."""
        result1 = stable_hash_short("hello")
        result2 = stable_hash_short("hello")
        assert result1 == result2

    def test_short_hash_matches_full(self):
        """Short hash should match first 8 chars of full hash."""
        full = stable_hash("test", length=8)
        short = stable_hash_short("test")
        assert full == short


class TestStableHashInt:
    """Tests for stable_hash_int function."""

    def test_int_hash_is_stable(self):
        """Integer hash should be stable."""
        result1 = stable_hash_int("session-123")
        result2 = stable_hash_int("session-123")
        assert result1 == result2

    def test_int_hash_default_modulo(self):
        """Default modulo is 100."""
        result = stable_hash_int("test")
        assert 0 <= result < 100

    def test_int_hash_custom_modulo(self):
        """Custom modulo should be respected."""
        result = stable_hash_int("test", modulo=10)
        assert 0 <= result < 10

        result = stable_hash_int("test", modulo=1000)
        assert 0 <= result < 1000

    def test_int_hash_modulo_one(self):
        """Modulo 1 should always return 0."""
        result = stable_hash_int("anything", modulo=1)
        assert result == 0

    def test_int_hash_invalid_modulo(self):
        """Invalid modulo should raise ValueError."""
        with pytest.raises(ValueError):
            stable_hash_int("test", modulo=0)

        with pytest.raises(ValueError):
            stable_hash_int("test", modulo=-1)

    def test_int_hash_distribution(self):
        """Integer hashes should distribute reasonably."""
        counts = [0] * 10
        for i in range(1000):
            idx = stable_hash_int(f"session-{i}", modulo=10)
            counts[idx] += 1

        # Each bucket should have between 50 and 150 items (10% ± 5%)
        for count in counts:
            assert 50 <= count <= 150, f"Uneven distribution: {counts}"


class TestStableHashIndex:
    """Tests for stable_hash_index function."""

    def test_index_basic(self):
        """Index should be in valid range."""
        items = ["a", "b", "c", "d", "e"]
        idx = stable_hash_index("test", len(items))
        assert 0 <= idx < len(items)

    def test_index_is_stable(self):
        """Index should be stable for same input."""
        idx1 = stable_hash_index("message", 5)
        idx2 = stable_hash_index("message", 5)
        assert idx1 == idx2

    def test_index_different_lengths(self):
        """Same value with different lengths should give valid indices."""
        for length in [1, 5, 10, 100]:
            idx = stable_hash_index("test", length)
            assert 0 <= idx < length

    def test_index_invalid_length(self):
        """Invalid length should raise ValueError."""
        with pytest.raises(ValueError):
            stable_hash_index("test", 0)


class TestCanonicalizeDestinations:
    """Tests for canonicalize_destinations function."""

    def test_basic_sorting(self):
        """Destinations should be sorted."""
        result = canonicalize_destinations(["Paris", "London", "Berlin"])
        assert result == "berlin|london|paris"

    def test_case_insensitive(self):
        """Canonicalization should be case-insensitive."""
        result1 = canonicalize_destinations(["PARIS", "london"])
        result2 = canonicalize_destinations(["Paris", "London"])
        assert result1 == result2

    def test_whitespace_stripped(self):
        """Whitespace should be stripped."""
        result = canonicalize_destinations(["  Paris  ", "London"])
        assert result == "london|paris"

    def test_empty_values_filtered(self):
        """Empty values should be filtered."""
        result = canonicalize_destinations(["Paris", "", "London", "  "])
        assert result == "london|paris"

    def test_none_returns_empty(self):
        """None should return empty string."""
        assert canonicalize_destinations(None) == ""

    def test_empty_list_returns_empty(self):
        """Empty list should return empty string."""
        assert canonicalize_destinations([]) == ""

    def test_order_independence(self):
        """Different input orders should give same result."""
        result1 = canonicalize_destinations(["Paris", "London"])
        result2 = canonicalize_destinations(["London", "Paris"])
        assert result1 == result2


class TestCanonicalizeMissingFields:
    """Tests for canonicalize_missing_fields function."""

    def test_basic_sorting(self):
        """Fields should be sorted."""
        result = canonicalize_missing_fields(["dates", "destinations", "travelers"])
        assert result == "dates|destinations|travelers"

    def test_none_returns_empty(self):
        """None should return empty string."""
        assert canonicalize_missing_fields(None) == ""

    def test_order_independence(self):
        """Different input orders should give same result."""
        result1 = canonicalize_missing_fields(["dates", "destinations"])
        result2 = canonicalize_missing_fields(["destinations", "dates"])
        assert result1 == result2


class TestCanonicalizeDict:
    """Tests for canonicalize_dict function."""

    def test_basic_json(self):
        """Should produce valid JSON."""
        result = canonicalize_dict({"a": 1, "b": 2})
        parsed = json.loads(result)
        assert parsed == {"a": 1, "b": 2}

    def test_key_ordering(self):
        """Keys should be sorted."""
        result = canonicalize_dict({"c": 3, "a": 1, "b": 2})
        assert result == '{"a": 1, "b": 2, "c": 3}'

    def test_none_returns_empty_object(self):
        """None should return empty JSON object."""
        assert canonicalize_dict(None) == "{}"

    def test_empty_dict_returns_empty_object(self):
        """Empty dict should return empty JSON object."""
        assert canonicalize_dict({}) == "{}"


class TestMakeCacheKey:
    """Tests for make_cache_key function."""

    def test_string_parts(self):
        """String parts should be joined."""
        result = make_cache_key("router", "v6", "destinations")
        assert result == "router::v6::destinations"

    def test_none_parts(self):
        """None parts should become empty strings."""
        result = make_cache_key("router", None, "v6")
        assert result == "router::::v6"

    def test_list_parts(self):
        """List parts should be canonicalized."""
        result = make_cache_key("router", ["Paris", "London"])
        assert result == "router::london|paris"

    def test_dict_parts(self):
        """Dict parts should be hashed."""
        result = make_cache_key("cache", {"a": 1})
        parts = result.split("::")
        assert parts[0] == "cache"
        assert len(parts[1]) == 8  # Short hash

    def test_stability(self):
        """Same inputs should give same key."""
        result1 = make_cache_key("router", "v6", ["Paris", "London"])
        result2 = make_cache_key("router", "v6", ["London", "Paris"])
        assert result1 == result2  # Canonicalized


class TestConcurrency:
    """Tests for thread safety of hashing functions."""

    def test_concurrent_stable_hash(self):
        """stable_hash should be thread-safe."""
        results = []
        errors = []

        def hash_worker(value):
            try:
                for _ in range(100):
                    h = stable_hash(value)
                    results.append(h)
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(10):
            t = threading.Thread(target=hash_worker, args=(f"test-{i}",))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 1000  # 10 threads * 100 iterations

    def test_concurrent_stable_hash_int(self):
        """stable_hash_int should be thread-safe."""
        results = []
        errors = []

        def hash_worker(value):
            try:
                for _ in range(100):
                    h = stable_hash_int(value, modulo=100)
                    results.append(h)
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(10):
            t = threading.Thread(target=hash_worker, args=(f"session-{i}",))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 1000


class TestBannedPatterns:
    """Tests for the banned pattern definitions."""

    def test_banned_patterns_exist(self):
        """BANNED_PATTERNS should be defined."""
        assert BANNED_PATTERNS
        assert len(BANNED_PATTERNS) > 0

    def test_banned_patterns_are_valid_regex(self):
        """All banned patterns should be valid regex."""
        import re

        for pattern in BANNED_PATTERNS:
            try:
                re.compile(pattern)
            except re.error as e:
                pytest.fail(f"Invalid regex pattern: {pattern} - {e}")


class TestRealWorldPatterns:
    """Tests verifying real-world usage patterns work correctly."""

    def test_session_cohort_assignment(self):
        """
        Replaces: hash(session_id) % 100

        Used for A/B testing cohort assignment.
        """
        session_id = "abc-123-def-456"

        # Old pattern (unstable):
        # cohort = hash(session_id) % 100

        # New pattern (stable):
        cohort = stable_hash_int(session_id, modulo=100)

        # Verify it's deterministic
        cohort2 = stable_hash_int(session_id, modulo=100)
        assert cohort == cohort2

    def test_warm_opener_selection(self):
        """
        Replaces: hash(msg) % len(_WARM_OPENERS)

        Used for deterministic message polishing.
        """
        openers = ["Great choice! ", "Nice! ", "Perfect! ", "Love it! "]
        msg = "I want to go to Paris"

        # Old pattern (unstable):
        # idx = hash(msg) % len(openers)

        # New pattern (stable):
        idx = stable_hash_index(msg, len(openers))

        assert 0 <= idx < len(openers)

        # Verify deterministic
        idx2 = stable_hash_index(msg, len(openers))
        assert idx == idx2

    def test_cache_key_with_destinations(self):
        """Cache key should be stable regardless of destination order."""
        key1 = make_cache_key("router", "v6", ["Paris", "London"])
        key2 = make_cache_key("router", "v6", ["London", "Paris"])

        assert key1 == key2
