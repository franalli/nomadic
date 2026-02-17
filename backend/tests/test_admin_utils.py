"""
Tests for admin and debugging utilities in app.planner.services.admin_utils.

Covers:
- Debug/observability functions (planner info, graph stats)
- Startup validation (prompt prewarming, template coverage)
- Message utilities (condense_long_message)
- Cache management (clear_response_caches, checkpoint ops)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.planner.services.admin_utils import (
    CACHE_SCHEMA_VERSION,
    PLANNER_BUILD_ID,
    PROMPT_BUNDLE_HASH,
    checkpoint_stats,
    clear_all_checkpoints,
    clear_response_caches,
    clear_session_checkpoint,
    condense_long_message,
    get_graph_stats,
    get_planner_debug_info,
    prewarm_prompts,
    response_cache_stats,
    validate_template_coverage,
)


class TestGetPlannerDebugInfo:
    """Tests for get_planner_debug_info() observability endpoint."""

    def test_returns_dict(self):
        result = get_planner_debug_info()
        assert isinstance(result, dict)

    def test_contains_required_keys(self):
        result = get_planner_debug_info()
        required = {"version", "build_id", "cache_schema", "prompt_hash", "graph_nodes"}
        assert required.issubset(result.keys())

    def test_version_is_string(self):
        result = get_planner_debug_info()
        assert isinstance(result["version"], str)

    def test_build_id_matches_constant(self):
        result = get_planner_debug_info()
        assert result["build_id"] == PLANNER_BUILD_ID

    def test_cache_schema_matches_constant(self):
        result = get_planner_debug_info()
        assert result["cache_schema"] == CACHE_SCHEMA_VERSION

    def test_prompt_hash_matches_constant(self):
        result = get_planner_debug_info()
        assert result["prompt_hash"] == PROMPT_BUNDLE_HASH

    def test_graph_nodes_is_list(self):
        result = get_planner_debug_info()
        assert isinstance(result["graph_nodes"], list)
        assert len(result["graph_nodes"]) > 0


class TestGetGraphStats:
    """Tests for get_graph_stats() graph topology summary."""

    def test_returns_dict(self):
        result = get_graph_stats()
        assert isinstance(result, dict)

    def test_contains_required_keys(self):
        result = get_graph_stats()
        assert "nodes" in result
        assert "edges" in result
        assert "version" in result

    def test_nodes_is_int(self):
        result = get_graph_stats()
        assert isinstance(result["nodes"], int)
        assert result["nodes"] > 0

    def test_edges_is_int(self):
        result = get_graph_stats()
        assert isinstance(result["edges"], int)
        assert result["edges"] > 0

    def test_version_is_string(self):
        result = get_graph_stats()
        assert isinstance(result["version"], str)


class TestPrewarmPrompts:
    """Tests for prewarm_prompts() startup hook."""

    def test_returns_dict(self):
        result = prewarm_prompts()
        assert isinstance(result, dict)

    def test_contains_required_keys(self):
        result = prewarm_prompts()
        assert "prompts_warmed" in result
        assert "templates_loaded" in result
        assert "warmup_ms" in result

    def test_warmup_ms_non_negative(self):
        result = prewarm_prompts()
        assert result["warmup_ms"] >= 0

    def test_templates_loaded_positive(self):
        result = prewarm_prompts()
        assert result["templates_loaded"] >= 0


class TestValidateTemplateCoverage:
    """Tests for validate_template_coverage() startup validation."""

    def test_returns_dict(self):
        result = validate_template_coverage()
        assert isinstance(result, dict)

    def test_valid_is_true(self):
        result = validate_template_coverage()
        assert result["valid"] is True

    def test_missing_fields_empty(self):
        result = validate_template_coverage()
        assert result["missing_fields"] == []

    def test_errors_empty(self):
        result = validate_template_coverage()
        assert result["errors"] == []


class TestCondenseLongMessage:
    """Tests for condense_long_message() truncation utility."""

    def test_short_message_unchanged(self):
        msg = "Hello world"
        assert condense_long_message(msg, 50) == msg

    def test_exact_boundary_unchanged(self):
        msg = "x" * 10
        assert condense_long_message(msg, 10) == msg

    def test_long_message_truncated_with_ellipsis(self):
        msg = "a" * 100
        result = condense_long_message(msg, 20)
        assert result.endswith("...")
        assert len(result) == 20

    @pytest.mark.parametrize(
        "message,max_len,expected_len",
        [
            ("abcdefghij", 7, 7),
            ("abcdefghij", 5, 5),
            ("abcdefghij", 3, 3),
        ],
    )
    def test_truncated_length_equals_max_len(self, message: str, max_len: int, expected_len: int):
        result = condense_long_message(message, max_len)
        assert len(result) == expected_len

    def test_truncated_content_prefix(self):
        msg = "abcdefghij"
        result = condense_long_message(msg, 7)
        # First 4 chars + "..." = 7
        assert result == "abcd..."

    def test_empty_message_unchanged(self):
        assert condense_long_message("", 10) == ""

    def test_single_char_under_limit(self):
        assert condense_long_message("x", 5) == "x"


class TestCheckpointStats:
    """Tests for checkpoint_stats() summary."""

    def test_returns_dict(self):
        result = checkpoint_stats()
        assert isinstance(result, dict)

    def test_contains_count(self):
        result = checkpoint_stats()
        assert "count" in result

    def test_contains_version(self):
        result = checkpoint_stats()
        assert "version" in result


class TestResponseCacheStats:
    """Tests for response_cache_stats() summary."""

    def test_returns_dict(self):
        result = response_cache_stats()
        assert isinstance(result, dict)

    def test_contains_hits_and_misses(self):
        result = response_cache_stats()
        assert "hits" in result
        assert "misses" in result


class TestClearResponseCaches:
    """Tests for clear_response_caches() async cache clearing."""

    @pytest.mark.asyncio
    async def test_returns_sum_of_l1_and_l2(self):
        """Mock both L1 experience cache and L2 DB deletion."""
        mock_db_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 5
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        mock_db_session.commit = AsyncMock()

        mock_factory = MagicMock(return_value=mock_db_session)
        # AsyncContextManager protocol
        mock_db_session.__aenter__ = AsyncMock(return_value=mock_db_session)
        mock_db_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "app.services.experience_generator.clear_experience_cache",
                return_value=3,
            ) as mock_l1,
            patch(
                "app.db._get_async_session_factory",
                return_value=mock_factory,
            ),
        ):
            result = await clear_response_caches()
            assert result == 8  # 3 (L1) + 5 (L2)
            mock_l1.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_l1_only_on_db_error(self):
        """When DB fails, should still return L1 count."""
        with (
            patch(
                "app.services.experience_generator.clear_experience_cache",
                return_value=2,
            ),
            patch(
                "app.db._get_async_session_factory",
                side_effect=Exception("DB unavailable"),
            ),
        ):
            result = await clear_response_caches()
            assert result == 2


class TestClearCheckpoints:
    """Tests for checkpoint clearing no-ops."""

    @pytest.mark.asyncio
    async def test_clear_all_checkpoints_does_not_raise(self):
        await clear_all_checkpoints()

    @pytest.mark.asyncio
    async def test_clear_session_checkpoint_does_not_raise(self):
        await clear_session_checkpoint("test-session-123")

    @pytest.mark.asyncio
    async def test_clear_session_checkpoint_accepts_any_id(self):
        await clear_session_checkpoint("")
        await clear_session_checkpoint("abc-def-ghi")
