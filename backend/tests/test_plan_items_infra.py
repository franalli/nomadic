"""
Infrastructure-level tests for plan items V, Y.

Covers:
  - Item V/Y: Health endpoint response structure
  - Item Y: Stale session cleanup logic

Run with: pytest tests/test_plan_items_infra.py -v
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# =============================================================================
# Item V/Y: Health endpoint response structure
# =============================================================================


class TestHealthEndpoint:
    """GET /health returns expected JSON structure."""

    @pytest.mark.asyncio
    async def test_health_returns_ok_with_pool_stats(self) -> None:
        """Health endpoint returns DB pool stats and 'ok' status when DB is reachable."""
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        # Mock the async engine with pool stats
        mock_pool = MagicMock()
        mock_pool.size.return_value = 5
        mock_pool.checkedin.return_value = 3
        mock_pool.checkedout.return_value = 2
        mock_pool.overflow.return_value = 0

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        mock_engine = MagicMock()
        mock_engine.pool = mock_pool
        mock_engine.connect = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_conn),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        with patch("app.db._get_async_engine", return_value=mock_engine):
            transport = ASGITransport(app=app, raise_app_exceptions=False)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "db" in data
        assert data["db"]["ok"] is True
        pool = data["db"]["pool"]
        assert pool["size"] == 5
        assert pool["checkedin"] == 3
        assert pool["checkedout"] == 2
        assert pool["overflow"] == 0

    @pytest.mark.asyncio
    async def test_health_returns_degraded_when_db_fails(self) -> None:
        """Health endpoint returns 'degraded' when DB connection raises."""
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        with patch("app.db._get_async_engine", side_effect=RuntimeError("no db")):
            transport = ASGITransport(app=app, raise_app_exceptions=False)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["db"]["ok"] is False

    @pytest.mark.asyncio
    async def test_health_response_has_build_info(self) -> None:
        """Health endpoint includes env, prompt_bundle_hash, planner_build_id, cache_schema_version."""
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        # Engine failure is fine -- we just want to check the non-DB fields
        with patch("app.db._get_async_engine", side_effect=RuntimeError("no db")):
            transport = ASGITransport(app=app, raise_app_exceptions=False)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/health")

        data = resp.json()
        assert "env" in data
        assert "prompt_bundle_hash" in data
        assert "planner_build_id" in data
        assert "cache_schema_version" in data


# =============================================================================
# Item Y: Stale session cleanup logic
# =============================================================================


class TestCleanupExpiredSessions:
    """_cleanup_expired_sessions deletes stale sessions via cascading deletes."""

    @pytest.mark.asyncio
    async def test_cleanup_skips_when_no_stale_sessions(self) -> None:
        """When no stale sessions exist, cleanup sleeps without deleting."""
        import asyncio

        from app.lifespan import _cleanup_expired_sessions

        # Mock the DB session factory to return an empty result
        mock_result = MagicMock()
        mock_result.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_factory = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_db),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        with patch("app.db._get_async_session_factory", return_value=mock_factory):
            # Run the cleanup task and cancel it after the first sleep
            task = asyncio.create_task(_cleanup_expired_sessions())
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # execute was called once (the SELECT query), commit was NOT called
        mock_db.execute.assert_called_once()
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_deletes_stale_sessions(self) -> None:
        """When stale sessions exist, cleanup issues cascade deletes and commits."""
        import asyncio

        from app.lifespan import _cleanup_expired_sessions

        # Mock the DB session factory to return stale session IDs
        mock_select_result = MagicMock()
        mock_select_result.all.return_value = [("sess-1",), ("sess-2",)]

        call_count = 0

        async def _fake_execute(stmt: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_select_result
            # All subsequent calls (deletes, update) return a mock
            return MagicMock()

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=_fake_execute)

        mock_factory = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_db),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        with patch("app.db._get_async_session_factory", return_value=mock_factory):
            task = asyncio.create_task(_cleanup_expired_sessions())
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Should have called execute multiple times:
        # 1 SELECT + 4 DELETEs (ChatMessage, PlanDocument, TripContext update,
        #   TripContext delete, Session delete) = 6 total
        assert call_count >= 6
        # commit should have been called after the cascade
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_handles_db_errors_gracefully(self, caplog: Any) -> None:
        """DB errors during cleanup are logged, not propagated."""
        import asyncio

        from app.lifespan import _cleanup_expired_sessions

        # First call: factory raises RuntimeError (caught by except Exception).
        # Second call: factory returns empty result, hitting await asyncio.sleep
        # where task.cancel() takes effect.
        error_factory = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(side_effect=RuntimeError("db exploded")),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        mock_empty_result = MagicMock()
        mock_empty_result.all.return_value = []
        ok_db = AsyncMock()
        ok_db.execute = AsyncMock(return_value=mock_empty_result)
        ok_factory = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=ok_db),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        call_count = 0

        def _factory_switcher() -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return error_factory
            return ok_factory

        with (
            patch("app.db._get_async_session_factory", side_effect=_factory_switcher),
            caplog.at_level(logging.WARNING, logger="app.lifespan"),
        ):
            task = asyncio.create_task(_cleanup_expired_sessions())
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # The error was caught and logged, not propagated
        assert call_count >= 2
        assert any("cleanup" in r.message.lower() for r in caplog.records)
