"""Tests for backend/app/debug_utils.py.

Covers:
- get_debug_mode: env var mapping
- TokenUsage: total, __add__, __str__
- RequestMetrics: total_tokens, add_model_usage
- CompactLogger._calculate_cost and _format_params
- _truncate, _format_extras
"""

from __future__ import annotations

import pytest

from app.debug_utils import (
    CompactLogger,
    RequestMetrics,
    TokenUsage,
    _format_extras,
    _truncate,
    get_debug_mode,
)

# =============================================================================
# get_debug_mode
# =============================================================================


class TestGetDebugMode:
    """Test environment-driven debug mode resolution."""

    def test_full(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEBUG", "full")
        assert get_debug_mode() == "full"

    def test_compact(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEBUG", "compact")
        assert get_debug_mode() == "compact"

    def test_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEBUG", "off")
        assert get_debug_mode() == "off"

    def test_unknown_value_returns_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEBUG", "verbose")
        assert get_debug_mode() == "off"

    def test_unset_returns_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEBUG", raising=False)
        assert get_debug_mode() == "off"

    def test_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEBUG", "FULL")
        assert get_debug_mode() == "full"

    def test_whitespace_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEBUG", "  compact  ")
        assert get_debug_mode() == "compact"


# =============================================================================
# TokenUsage
# =============================================================================


class TestTokenUsage:
    """Test TokenUsage data class."""

    def test_total_property(self) -> None:
        usage = TokenUsage(prompt=100, completion=50)
        assert usage.total == 150

    def test_total_zero_default(self) -> None:
        usage = TokenUsage()
        assert usage.total == 0

    def test_add(self) -> None:
        a = TokenUsage(prompt=100, completion=50)
        b = TokenUsage(prompt=200, completion=75)
        result = a + b
        assert result.prompt == 300
        assert result.completion == 125
        assert result.total == 425

    def test_add_preserves_originals(self) -> None:
        a = TokenUsage(prompt=10, completion=5)
        b = TokenUsage(prompt=20, completion=10)
        _ = a + b
        assert a.prompt == 10
        assert b.prompt == 20

    def test_str_format(self) -> None:
        usage = TokenUsage(prompt=100, completion=50)
        assert str(usage) == "p=100 c=50 tot=150"

    def test_str_zeros(self) -> None:
        usage = TokenUsage()
        assert str(usage) == "p=0 c=0 tot=0"


# =============================================================================
# RequestMetrics
# =============================================================================


class TestRequestMetrics:
    """Test RequestMetrics aggregation."""

    def test_total_tokens_sums_across_nodes(self) -> None:
        metrics = RequestMetrics(start_time=0.0)
        metrics.node_tokens["router"] = TokenUsage(prompt=100, completion=50)
        metrics.node_tokens["specialist"] = TokenUsage(prompt=200, completion=75)

        total = metrics.total_tokens
        assert total.prompt == 300
        assert total.completion == 125
        assert total.total == 425

    def test_total_tokens_empty(self) -> None:
        metrics = RequestMetrics(start_time=0.0)
        total = metrics.total_tokens
        assert total.total == 0

    def test_add_model_usage_creates_new(self) -> None:
        metrics = RequestMetrics(start_time=0.0)
        metrics.add_model_usage("gpt-4o", TokenUsage(prompt=100, completion=50))

        assert "gpt-4o" in metrics.model_usage
        assert metrics.model_usage["gpt-4o"].prompt == 100
        assert metrics.model_usage["gpt-4o"].completion == 50

    def test_add_model_usage_accumulates(self) -> None:
        metrics = RequestMetrics(start_time=0.0)
        metrics.add_model_usage("gpt-4o", TokenUsage(prompt=100, completion=50))
        metrics.add_model_usage("gpt-4o", TokenUsage(prompt=200, completion=75))

        assert metrics.model_usage["gpt-4o"].prompt == 300
        assert metrics.model_usage["gpt-4o"].completion == 125

    def test_add_model_usage_multiple_models(self) -> None:
        metrics = RequestMetrics(start_time=0.0)
        metrics.add_model_usage("gpt-4o", TokenUsage(prompt=100, completion=50))
        metrics.add_model_usage("gpt-4o-mini", TokenUsage(prompt=200, completion=75))

        assert len(metrics.model_usage) == 2
        assert metrics.model_usage["gpt-4o"].prompt == 100
        assert metrics.model_usage["gpt-4o-mini"].prompt == 200


# =============================================================================
# CompactLogger._calculate_cost
# =============================================================================


class TestCompactLoggerCalculateCost:
    """Test cost calculation for known and unknown models."""

    def _make_logger(self) -> CompactLogger:
        return CompactLogger("test")

    def test_known_model_gpt4o(self) -> None:
        logger = self._make_logger()
        usage = TokenUsage(prompt=1_000_000, completion=1_000_000)
        cost = logger._calculate_cost("gpt-4o", usage)
        # gpt-4o: prompt=$2.50/1M, completion=$10.00/1M
        assert cost == pytest.approx(12.50)

    def test_known_model_gpt4o_mini(self) -> None:
        logger = self._make_logger()
        usage = TokenUsage(prompt=1_000_000, completion=1_000_000)
        cost = logger._calculate_cost("gpt-4o-mini", usage)
        # gpt-4o-mini: prompt=$0.15/1M, completion=$0.60/1M
        assert cost == pytest.approx(0.75)

    def test_known_model_small_usage(self) -> None:
        logger = self._make_logger()
        usage = TokenUsage(prompt=1000, completion=500)
        cost = logger._calculate_cost("gpt-4o", usage)
        # (1000/1M)*2.50 + (500/1M)*10.00 = 0.0025 + 0.005 = 0.0075
        assert cost == pytest.approx(0.0075)

    def test_unknown_model_returns_zero(self) -> None:
        logger = self._make_logger()
        usage = TokenUsage(prompt=1000, completion=500)
        cost = logger._calculate_cost("unknown-model-xyz", usage)
        assert cost == 0.0

    def test_zero_usage(self) -> None:
        logger = self._make_logger()
        usage = TokenUsage()
        cost = logger._calculate_cost("gpt-4o", usage)
        assert cost == 0.0


# =============================================================================
# CompactLogger._format_params
# =============================================================================


class TestCompactLoggerFormatParams:
    """Test parameter formatting for log output."""

    def test_empty_dict(self) -> None:
        assert CompactLogger._format_params({}) == ""

    def test_single_param(self) -> None:
        assert CompactLogger._format_params({"key": "value"}) == "key=value"

    def test_multiple_params(self) -> None:
        result = CompactLogger._format_params({"a": 1, "b": 2})
        assert "a=1" in result
        assert "b=2" in result

    def test_long_value_truncated(self) -> None:
        long_val = "x" * 50  # >40 chars
        result = CompactLogger._format_params({"k": long_val})
        assert result.endswith("...")
        assert len(result) < len(f"k={long_val}")

    def test_none_value_skipped(self) -> None:
        result = CompactLogger._format_params({"a": None, "b": "yes"})
        assert "a=" not in result
        assert "b=yes" in result

    def test_all_none_values(self) -> None:
        result = CompactLogger._format_params({"a": None, "b": None})
        assert result == ""


# =============================================================================
# _truncate
# =============================================================================


class TestTruncate:
    """Test the _truncate helper."""

    def test_short_string_passthrough(self) -> None:
        assert _truncate("hello", max_len=100) == "hello"

    def test_exact_length_passthrough(self) -> None:
        s = "a" * 100
        assert _truncate(s, max_len=100) == s

    def test_long_string_truncated(self) -> None:
        s = "a" * 150
        result = _truncate(s, max_len=100)
        assert result.endswith("...")
        assert len(result) == 103  # 100 + len("...")

    def test_non_string_converted(self) -> None:
        assert _truncate(42) == "42"

    def test_list_converted(self) -> None:
        result = _truncate([1, 2, 3])
        assert result == "[1, 2, 3]"

    def test_default_max_len(self) -> None:
        # Default max_len is 100
        s = "a" * 101
        result = _truncate(s)
        assert result.endswith("...")


# =============================================================================
# _format_extras
# =============================================================================


class TestFormatExtras:
    """Test the _format_extras helper."""

    def test_empty_dict(self) -> None:
        assert _format_extras({}) == ""

    def test_normal_dict(self) -> None:
        result = _format_extras({"k": "v", "k2": "v2"})
        assert "k=v" in result
        assert "k2=v2" in result

    def test_long_value_truncated(self) -> None:
        long_val = "x" * 250  # >200 chars (default max_len)
        result = _format_extras({"k": long_val})
        assert result.endswith("...")
        assert len(result) < len(f"k={long_val}")

    def test_custom_max_len(self) -> None:
        val = "x" * 20
        result = _format_extras({"k": val}, max_len=10)
        assert result.endswith("...")
