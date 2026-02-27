# backend/tests/test_hashing_behavior.py
"""
Behavioral tests for backend/app/planner/hashing.py.

Covers: stable_hash, stable_hash_short, canonicalize_destinations,
make_cache_key, field_hash.
"""

from __future__ import annotations

import re

import pytest

from app.planner.hashing import (
    canonicalize_destinations,
    field_hash,
    make_cache_key,
    stable_hash,
    stable_hash_short,
)

# ---------------------------------------------------------------------------
# stable_hash
# ---------------------------------------------------------------------------


class TestStableHash:
    def test_same_input_same_output(self):
        """Identical inputs must always produce the same hash."""
        assert stable_hash("hello") == stable_hash("hello")

    def test_different_inputs_different_output(self):
        assert stable_hash("hello") != stable_hash("world")

    def test_dict_key_order_irrelevant(self):
        """sort_keys=True guarantees order-independent hashing for dicts."""
        assert stable_hash({"b": 2, "a": 1}) == stable_hash({"a": 1, "b": 2})

    def test_length_8(self):
        result = stable_hash("test", length=8)
        assert len(result) == 8

    def test_length_32(self):
        result = stable_hash("test", length=32)
        assert len(result) == 32

    def test_default_length_is_16(self):
        result = stable_hash("test")
        assert len(result) == 16

    def test_length_below_1_raises(self):
        with pytest.raises(ValueError, match="length must be 1-64"):
            stable_hash("x", length=0)

    def test_length_above_64_raises(self):
        with pytest.raises(ValueError, match="length must be 1-64"):
            stable_hash("x", length=65)

    def test_non_serializable_falls_back_to_repr(self):
        """Non-JSON-serializable objects should not crash; repr fallback kicks in."""
        obj = object()
        result = stable_hash(obj)
        assert isinstance(result, str)
        assert len(result) == 16

    def test_output_is_hex(self):
        result = stable_hash("abc", length=16)
        assert re.fullmatch(r"[0-9a-f]+", result), f"Expected hex string, got {result}"


# ---------------------------------------------------------------------------
# stable_hash_short
# ---------------------------------------------------------------------------


class TestStableHashShort:
    def test_returns_8_chars(self):
        assert len(stable_hash_short("anything")) == 8

    def test_delegates_to_stable_hash(self):
        """Output must equal stable_hash with length=8."""
        for val in ["hello", 42, {"k": "v"}, [1, 2]]:
            assert stable_hash_short(val) == stable_hash(val, length=8)


# ---------------------------------------------------------------------------
# canonicalize_destinations
# ---------------------------------------------------------------------------


class TestCanonicalizeDestinations:
    def test_none_returns_empty(self):
        assert canonicalize_destinations(None) == ""

    def test_empty_list_returns_empty(self):
        assert canonicalize_destinations([]) == ""

    def test_sorted_lowercase_joined(self):
        assert canonicalize_destinations(["Paris", "London"]) == "london|paris"

    def test_strips_whitespace(self):
        assert canonicalize_destinations(["  Paris  ", "London"]) == "london|paris"

    def test_single_element(self):
        assert canonicalize_destinations(["Paris"]) == "paris"

    def test_empty_strings_filtered(self):
        assert canonicalize_destinations(["Paris", "", "  ", "London"]) == "london|paris"

    def test_all_empty_strings_returns_empty(self):
        assert canonicalize_destinations(["", "  "]) == ""


# ---------------------------------------------------------------------------
# make_cache_key
# ---------------------------------------------------------------------------


class TestMakeCacheKey:
    def test_none_part_becomes_sentinel(self):
        assert make_cache_key(None) == "__NONE__"

    def test_string_passthrough(self):
        assert make_cache_key("router") == "router"

    def test_string_list_canonicalized(self):
        assert make_cache_key(["Paris", "London"]) == "london|paris"

    def test_mixed_list_hashed(self):
        """A list with non-string elements uses stable_hash_short."""
        result = make_cache_key([1, 2, 3])
        assert result == stable_hash_short([1, 2, 3])
        assert len(result) == 8

    def test_dict_hashed(self):
        d = {"key": "value"}
        result = make_cache_key(d)
        assert result == stable_hash_short(d)

    def test_integer_stringified(self):
        assert make_cache_key(42) == "42"

    def test_multiple_parts_joined(self):
        result = make_cache_key("router", "v6", ["Paris", "London"])
        assert result == "router::v6::london|paris"

    def test_all_none_parts(self):
        assert make_cache_key(None, None) == "__NONE__::__NONE__"

    def test_mixed_types(self):
        result = make_cache_key("prefix", 5, None, ["Tokyo"])
        assert result == "prefix::5::__NONE__::tokyo"


# ---------------------------------------------------------------------------
# field_hash
# ---------------------------------------------------------------------------


class TestFieldHash:
    def test_returns_12_char_hex(self):
        result = field_hash("hello")
        assert len(result) == 12
        assert re.fullmatch(r"[0-9a-f]+", result)

    def test_empty_string(self):
        result = field_hash("")
        assert len(result) == 12

    def test_none_coerced_to_empty(self):
        """None is coerced to '' via (value or '')."""
        assert field_hash(None) == field_hash("")

    def test_stability(self):
        assert field_hash("same") == field_hash("same")

    def test_different_inputs_different_output(self):
        assert field_hash("alpha") != field_hash("beta")
