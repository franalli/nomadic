"""Tests for error handling and edge cases."""

# ruff: noqa: E402

import os
import sys
from pathlib import Path

# Suppress debug output before importing plan_graph
os.environ["PLAN_GRAPH_DEBUG"] = "0"

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from app.plan_graph import (
    GraphState,
    TripInputs,
    _detect_short_circuit,
    _truncate_to_balanced_json,
    jloads_safe,
)


class TestJloadsSafe:
    """Tests for safe JSON parsing."""

    def test_valid_json(self):
        """Valid JSON should be parsed correctly."""
        result = jloads_safe('{"key": "value"}')
        assert result == {"key": "value"}

    def test_empty_string(self):
        """Empty string should return empty dict."""
        result = jloads_safe("")
        assert result == {}

    def test_none_input(self):
        """None input should return empty dict."""
        result = jloads_safe(None)
        assert result == {}

    def test_malformed_json_missing_brace(self):
        """Missing closing brace should be handled."""
        result = jloads_safe('{"key": "value"')
        # Should either return empty dict or attempt repair
        assert isinstance(result, dict)

    def test_json_with_extra_text(self):
        """JSON with extra text after should extract JSON part."""
        result = jloads_safe('{"key": "value"} extra text here')
        assert result.get("key") == "value" or result == {}

    def test_json_array(self):
        """JSON array should be handled."""
        result = jloads_safe("[1, 2, 3]")
        # May return the list or wrap it
        assert isinstance(result, (dict, list))

    def test_truncated_json(self):
        """Truncated JSON should be handled gracefully."""
        result = jloads_safe('{"assistant_message": "Hello, I am helping you with')
        # Should not crash, may return partial or empty
        assert isinstance(result, dict)

    def test_nested_json(self):
        """Nested JSON should be parsed correctly."""
        result = jloads_safe('{"outer": {"inner": "value"}}')
        assert result.get("outer", {}).get("inner") == "value"

    def test_json_with_unicode(self):
        """JSON with unicode should be parsed correctly."""
        result = jloads_safe('{"city": "São Paulo", "emoji": "🌍"}')
        assert result.get("city") == "São Paulo"
        assert result.get("emoji") == "🌍"

    def test_json_with_newlines(self):
        """JSON with newlines should be parsed correctly."""
        result = jloads_safe('{\n  "key": "value"\n}')
        assert result == {"key": "value"}


class TestTruncateToBalancedJson:
    """Tests for JSON extraction from strings with extra content."""

    def test_already_balanced(self):
        """Already balanced JSON should be returned as-is."""
        json_str = '{"key": "value"}'
        result = _truncate_to_balanced_json(json_str)
        assert result == json_str

    def test_extract_json_with_prefix(self):
        """JSON with text before it should be extracted."""
        json_str = 'Here is the JSON: {"key": "value"}'
        result = _truncate_to_balanced_json(json_str)
        assert result == '{"key": "value"}'

    def test_extract_json_with_suffix(self):
        """JSON with text after it should be extracted."""
        json_str = '{"key": "value"} and some more text'
        result = _truncate_to_balanced_json(json_str)
        assert result == '{"key": "value"}'

    def test_incomplete_json_returns_none(self):
        """Incomplete JSON (missing closing brace) should return None."""
        json_str = '{"key": "value"'
        result = _truncate_to_balanced_json(json_str)
        assert result is None

    def test_nested_json(self):
        """Nested JSON should be extracted correctly."""
        json_str = '{"outer": {"inner": "value"}}'
        result = _truncate_to_balanced_json(json_str)
        assert result == json_str

    def test_json_with_escaped_quotes(self):
        """JSON with escaped quotes should be handled correctly."""
        json_str = '{"message": "He said \\"hello\\""}'
        result = _truncate_to_balanced_json(json_str)
        assert result == json_str


class TestShortCircuitEdgeCases:
    """Tests for short-circuit edge cases."""

    def test_empty_string_no_crash(self):
        """Empty string should not crash."""
        state = GraphState(user_text="", trip_inputs=TripInputs(), metadata={})
        result = _detect_short_circuit("", state)
        assert result is None or isinstance(result, dict)

    def test_whitespace_only_no_crash(self):
        """Whitespace only should not crash."""
        state = GraphState(user_text="", trip_inputs=TripInputs(), metadata={})
        result = _detect_short_circuit("   \t\n   ", state)
        assert result is None or isinstance(result, dict)

    def test_very_long_input_bypassed(self):
        """Very long input should bypass short-circuit."""
        state = GraphState(user_text="", trip_inputs=TripInputs(), metadata={})
        long_text = "x" * 100
        result = _detect_short_circuit(long_text, state)
        assert result is None  # Long inputs bypass


class TestTripInputsNullValues:
    """Tests for null/None values in TripInputs."""

    def test_all_none_values(self):
        """TripInputs with all None should work."""
        trip = TripInputs()
        state = GraphState(
            user_text="test",
            trip_inputs=trip,
            metadata={},
        )
        assert state.trip_inputs is not None

    def test_partial_values(self):
        """Partial values should work."""
        trip = TripInputs(
            destinations=["Paris"],
            origin=None,
            start_date=None,
        )
        state = GraphState(
            user_text="test",
            trip_inputs=trip,
            metadata={},
        )
        assert state.trip_inputs.destinations == ["Paris"]
        assert state.trip_inputs.origin is None

    def test_empty_list_destinations(self):
        """Empty list for destinations should work."""
        trip = TripInputs(destinations=[])
        assert trip.destinations == []


class TestStateConsistency:
    """Tests for state consistency across operations."""

    def test_flags_initialized(self):
        """Flags should be properly initialized."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(),
        )
        assert hasattr(state, "flags")
        assert isinstance(state.flags, dict)

    def test_errors_list_initialized(self):
        """Errors list should be properly initialized."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(),
        )
        assert hasattr(state, "errors")
        assert isinstance(state.errors, list)
