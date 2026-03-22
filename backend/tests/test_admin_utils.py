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

from app.config import settings
from app.planner.services.admin_utils import (
    CACHE_SCHEMA_VERSION,
    PLANNER_BUILD_ID,
    PROMPT_BUNDLE_HASH,
    checkpoint_stats,
    clear_all_caches,
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
        required = {"version", "build_id", "cache_schema", "prompt_hash", "architecture", "steps"}
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

    def test_steps_is_list(self):
        result = get_planner_debug_info()
        assert isinstance(result["steps"], list)
        assert len(result["steps"]) == 6


class TestGetGraphStats:
    """Tests for get_graph_stats() graph topology summary."""

    def test_returns_dict(self):
        result = get_graph_stats()
        assert isinstance(result, dict)

    def test_contains_required_keys(self):
        result = get_graph_stats()
        assert "architecture" in result
        assert "steps" in result
        assert "middleware" in result
        assert "version" in result

    def test_steps_is_int(self):
        result = get_graph_stats()
        assert isinstance(result["steps"], int)
        assert result["steps"] == 6

    def test_middleware_is_int(self):
        result = get_graph_stats()
        assert isinstance(result["middleware"], int)
        assert result["middleware"] == 4

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
    """Tests for clear_response_caches() reset semantics."""

    @pytest.mark.asyncio
    async def test_returns_sum_of_all_l1_clears(self):
        """All four L1 caches are cleared; their counts are summed."""
        mock_feasibility = MagicMock()
        mock_feasibility.clear = MagicMock(return_value=4)

        with (
            patch(
                "app.services.experience_generator.clear_memory_cache",
                return_value=3,
            ) as mock_exp,
            patch(
                "app.services.specialist_cache.clear_memory_cache",
                return_value=2,
            ) as mock_spec,
            patch(
                "app.services.tile_cache.clear_memory_cache",
                return_value=1,
            ) as mock_tile,
            patch(
                "app.planner.services.feasibility_service._feasibility_cache",
                mock_feasibility,
            ),
        ):
            result = await clear_response_caches()
            assert result == 10  # 3 + 2 + 1 + 4
            mock_exp.assert_called_once()
            mock_spec.assert_called_once()
            mock_tile.assert_called_once()
            mock_feasibility.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_touch_l2_database_when_flag_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """L2 reset stays off unless CLEAR_L2_ON_RESET is enabled."""
        monkeypatch.setattr(settings, "clear_l2_on_session_reset", False)
        monkeypatch.setattr(settings, "pytest_running", False)
        with (
            patch("app.services.experience_generator.clear_memory_cache", return_value=0),
            patch("app.services.specialist_cache.clear_memory_cache", return_value=0),
            patch("app.services.tile_cache.clear_memory_cache", return_value=0),
            patch("app.planner.services.feasibility_service._feasibility_cache") as mock_feas,
            patch("app.db._get_async_session_factory") as mock_factory,
        ):
            mock_feas.clear.return_value = 0
            result = await clear_response_caches()
            assert result == 0
            mock_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_clears_l2_database_when_flag_enabled(self, monkeypatch: pytest.MonkeyPatch):
        """CLEAR_L2_ON_RESET=true must wipe persistent response + Unsplash caches."""
        monkeypatch.setattr(settings, "clear_l2_on_session_reset", True)
        monkeypatch.setattr(settings, "pytest_running", False)

        class _SessionCtx:
            def __init__(self) -> None:
                self.committed = False
                self.rolled_back = False
                self.executed_tables: list[str] = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
                return False

            async def execute(self, stmt):
                table_name = getattr(getattr(stmt, "table", None), "name", "unknown")
                self.executed_tables.append(table_name)
                rowcount = 3 if table_name == "response_cache" else 2
                return MagicMock(rowcount=rowcount)

            async def commit(self):
                self.committed = True

            async def rollback(self):
                self.rolled_back = True

        session_ctx = _SessionCtx()

        def _fake_factory():
            return session_ctx

        with (
            patch("app.services.experience_generator.clear_memory_cache", return_value=0),
            patch("app.services.specialist_cache.clear_memory_cache", return_value=0),
            patch("app.services.tile_cache.clear_memory_cache", return_value=0),
            patch("app.services.router_cache.clear_cache", return_value=0),
            patch("app.services.activity_browser.clear_browse_cache", return_value=0),
            patch("app.planner.services.iata_resolver.clear_iata_cache", return_value=0),
            patch("app.tile_service.google_places_provider._enrich_mem.clear", return_value=0),
            patch("app.planner.services.feasibility_service._feasibility_cache") as mock_feas,
            patch("app.db._get_async_session_factory", return_value=_fake_factory),
        ):
            mock_feas.clear.return_value = 0
            result = await clear_response_caches()

        assert result == 5
        assert session_ctx.executed_tables == ["response_cache", "unsplash_image_cache"]
        assert session_ctx.committed is True
        assert session_ctx.rolled_back is False

    @pytest.mark.asyncio
    async def test_raises_when_l2_clear_fails(self, monkeypatch: pytest.MonkeyPatch):
        """L2 reset failures must surface instead of being silently swallowed."""
        monkeypatch.setattr(settings, "clear_l2_on_session_reset", True)
        monkeypatch.setattr(settings, "pytest_running", False)

        class _SessionCtx:
            def __init__(self) -> None:
                self.rolled_back = False

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
                return False

            async def execute(self, stmt):  # noqa: ARG002
                raise RuntimeError("db down")

            async def commit(self):
                raise AssertionError("commit should not be called on failure")

            async def rollback(self):
                self.rolled_back = True

        session_ctx = _SessionCtx()

        def _fake_factory():
            return session_ctx

        with (
            patch("app.services.experience_generator.clear_memory_cache", return_value=0),
            patch("app.services.specialist_cache.clear_memory_cache", return_value=0),
            patch("app.services.tile_cache.clear_memory_cache", return_value=0),
            patch("app.services.router_cache.clear_cache", return_value=0),
            patch("app.services.activity_browser.clear_browse_cache", return_value=0),
            patch("app.planner.services.iata_resolver.clear_iata_cache", return_value=0),
            patch("app.tile_service.google_places_provider._enrich_mem.clear", return_value=0),
            patch("app.planner.services.feasibility_service._feasibility_cache") as mock_feas,
            patch("app.db._get_async_session_factory", return_value=_fake_factory),
        ):
            mock_feas.clear.return_value = 0
            with pytest.raises(
                RuntimeError, match="Failed to clear L2 caches during session reset"
            ):
                await clear_response_caches()

        assert session_ctx.rolled_back is True

    @pytest.mark.asyncio
    async def test_cancels_inflight_generators_before_clearing(self):
        mock_feasibility = MagicMock()
        mock_feasibility.clear.return_value = 0

        with (
            patch(
                "app.planner.services.admin_utils.cancel_cache_population_tasks",
                new=AsyncMock(return_value={"experience": 1, "browse": 2}),
            ) as mock_cancel,
            patch("app.services.experience_generator.clear_memory_cache", return_value=0),
            patch("app.services.specialist_cache.clear_memory_cache", return_value=0),
            patch("app.services.tile_cache.clear_memory_cache", return_value=0),
            patch("app.services.router_cache.clear_cache", return_value=0),
            patch("app.services.activity_browser.clear_browse_cache", return_value=0),
            patch("app.planner.services.iata_resolver.clear_iata_cache", return_value=0),
            patch("app.tile_service.google_places_provider._enrich_mem.clear", return_value=0),
            patch(
                "app.planner.services.feasibility_service._feasibility_cache",
                mock_feasibility,
            ),
        ):
            await clear_response_caches()

        mock_cancel.assert_awaited_once()


class TestClearAllCaches:
    """Tests for clear_all_caches() contract coverage."""

    @pytest.mark.asyncio
    async def test_clears_validation_cache_with_rate_limit_state(self):
        with (
            patch(
                "app.planner.services.admin_utils.clear_response_caches",
                new=AsyncMock(return_value=4),
            ) as mock_response_clear,
            patch("app.validation.clear_cache", new=AsyncMock(return_value=6)) as mock_validation,
            patch(
                "app.planner.services.admin_utils.clear_all_checkpoints",
                new=AsyncMock(return_value=3),
            ) as mock_checkpoints,
        ):
            result = await clear_all_caches()

        assert result == 13
        mock_response_clear.assert_awaited_once()
        mock_validation.assert_awaited_once_with(preserve_rate_limiting=False)
        mock_checkpoints.assert_awaited_once()


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
