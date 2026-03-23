"""
Infrastructure-level tests for plan items U, V, W, Y.

Covers:
  - Item U: Session turn cap (>=40 HumanMessages triggers cap, 39 does not)
  - Item W: Structured logging (_structured_log emits valid JSON, handles non-serializable)
  - Item V/Y: Health endpoint response structure

Run with: pytest tests/test_plan_items_infra.py -v
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.planner.coordinator import _structured_log, execute_turn
from app.planner.schemas.coordinator_schemas import ChangeType, ClassifierOutput

# =============================================================================
# Helpers
# =============================================================================


def _make_classifier(**overrides: Any) -> ClassifierOutput:
    """Build a ClassifierOutput with sensible defaults, overriding as needed."""
    defaults: Dict[str, Any] = {
        "intent": "PLANNING",
        "confidence": 0.9,
        "reasoning": "test",
        "change_type": ChangeType.INITIAL_PLAN,
    }
    defaults.update(overrides)
    return ClassifierOutput(**defaults)


def _make_state(**overrides: Any) -> Dict[str, Any]:
    """Build a minimal agent state dict."""
    state: Dict[str, Any] = {
        "trip_plan": {},
        "trip_settings": {},
        "tiles": {},
        "strategy_sections": [],
        "day_cards": [],
        "constraints": [],
        "specialist_plans": {},
        "persistent_meta": {},
        "turn_meta": {},
    }
    state.update(overrides)
    return state


# =============================================================================
# Item U: Session turn cap
# =============================================================================


class TestSessionTurnCap:
    """execute_turn enforces a 40-HumanMessage session cap."""

    @pytest.mark.asyncio
    async def test_cap_fires_at_40_messages(self, monkeypatch: Any) -> None:
        """execute_turn yields cap message and returns when >=40 HumanMessages exist."""
        import app.planner.nodes.router_extraction as router_module

        messages = [HumanMessage(content=f"msg {i}") for i in range(40)]
        state = _make_state(messages=messages, trip_plan={"destination": "Bali"})

        # classify_change should NOT be called -- turn cap fires before it
        classify_called = False

        async def _spy_classify(*a: Any, **kw: Any) -> ClassifierOutput:
            nonlocal classify_called
            classify_called = True
            return _make_classifier(intent="GREETING")

        monkeypatch.setattr(router_module, "classify_change", _spy_classify)

        events = [event async for event in execute_turn("one more", state, session_id="s1")]

        # Should yield token + complete
        token_events = [e for e in events if e["type"] == "token"]
        assert len(token_events) == 1
        assert "conversation limit" in token_events[0]["data"]

        complete_events = [e for e in events if e["type"] == "complete"]
        assert len(complete_events) == 1

        # classify_change should not have been called
        assert not classify_called

    @pytest.mark.asyncio
    async def test_cap_fires_above_40_messages(self, monkeypatch: Any) -> None:
        """execute_turn yields cap message when more than 40 HumanMessages exist."""
        import app.planner.nodes.router_extraction as router_module

        messages = [HumanMessage(content=f"msg {i}") for i in range(55)]
        state = _make_state(messages=messages, trip_plan={"destination": "Tokyo"})

        classify_called = False

        async def _spy_classify(*a: Any, **kw: Any) -> ClassifierOutput:
            nonlocal classify_called
            classify_called = True
            return _make_classifier(intent="GREETING")

        monkeypatch.setattr(router_module, "classify_change", _spy_classify)

        events = [event async for event in execute_turn("hello", state, session_id="s2")]

        token_events = [e for e in events if e["type"] == "token"]
        assert len(token_events) == 1
        assert "conversation limit" in token_events[0]["data"]
        assert not classify_called

    @pytest.mark.asyncio
    async def test_cap_appends_messages_to_state(self, monkeypatch: Any) -> None:
        """When cap triggers, user + assistant messages are appended to state."""
        import app.planner.nodes.router_extraction as router_module

        messages = [HumanMessage(content=f"msg {i}") for i in range(40)]
        state = _make_state(messages=messages, trip_plan={"destination": "Bali"})

        monkeypatch.setattr(
            router_module,
            "classify_change",
            AsyncMock(return_value=_make_classifier(intent="GREETING")),
        )

        _ = [event async for event in execute_turn("one more", state, session_id="s1")]

        # Original 40 + user message + AI cap message = 42
        assert len(state["messages"]) == 42
        assert isinstance(state["messages"][-2], HumanMessage)
        assert state["messages"][-2].content == "one more"
        assert isinstance(state["messages"][-1], AIMessage)
        assert "conversation limit" in state["messages"][-1].content

    @pytest.mark.asyncio
    async def test_cap_does_not_fire_at_39_messages(self, monkeypatch: Any) -> None:
        """execute_turn proceeds normally with 39 HumanMessages (below cap)."""
        import app.planner.coordinator as coordinator_module
        import app.planner.nodes.router_extraction as router_module
        import app.planner.services.feasibility_service as feasibility_module
        import app.services.unsplash as unsplash_module

        messages = [HumanMessage(content=f"msg {i}") for i in range(39)]
        state = _make_state(messages=messages, trip_plan={"destination": "Bali"})

        classify_called = False

        async def _spy_classify(*a: Any, **kw: Any) -> ClassifierOutput:
            nonlocal classify_called
            classify_called = True
            return _make_classifier(intent="GREETING")

        monkeypatch.setattr(router_module, "classify_change", _spy_classify)
        monkeypatch.setattr(coordinator_module, "build_trip_state_summary", lambda s: "summary")
        monkeypatch.setattr(
            coordinator_module,
            "_generate_response_streaming",
            AsyncMock(return_value="Hello!"),
        )
        monkeypatch.setattr(coordinator_module, "_refresh_enrichment_states", AsyncMock())
        monkeypatch.setattr(
            coordinator_module,
            "_build_envelope",
            lambda *a, **kw: {"document": {}, "session_state": {}},
        )
        monkeypatch.setattr(
            feasibility_module,
            "batch_feasibility_precheck",
            AsyncMock(return_value={}),
        )
        monkeypatch.setattr(
            unsplash_module,
            "prefetch_destination_images",
            AsyncMock(return_value=None),
        )

        events = [event async for event in execute_turn("one more", state, session_id="s1")]

        # Classification WAS reached (below cap)
        assert classify_called

    @pytest.mark.asyncio
    async def test_cap_complete_envelope_has_expected_shape(self, monkeypatch: Any) -> None:
        """The complete event from a cap response contains a well-formed envelope."""
        import app.planner.nodes.router_extraction as router_module

        messages = [HumanMessage(content=f"msg {i}") for i in range(40)]
        state = _make_state(messages=messages, trip_plan={"destination": "Bali"})

        monkeypatch.setattr(
            router_module,
            "classify_change",
            AsyncMock(return_value=_make_classifier(intent="GREETING")),
        )

        events = [event async for event in execute_turn("one more", state, session_id="s1")]

        complete_events = [e for e in events if e["type"] == "complete"]
        assert len(complete_events) == 1
        envelope = complete_events[0]["data"]
        # Envelope must have the core keys produced by _build_envelope
        assert "document" in envelope or "session_state" in envelope


# =============================================================================
# Item W: Structured logging
# =============================================================================


class TestStructuredLog:
    """_structured_log emits valid JSON log lines."""

    def test_emits_json_with_event_and_session_id(self, caplog: Any) -> None:
        """_structured_log outputs valid JSON with event and session_id."""
        with caplog.at_level(logging.INFO, logger="app.planner.coordinator"):
            _structured_log("turn_start", session_id="s1", intent="PLANNING", wall_ms=123)

        assert len(caplog.records) >= 1
        record = caplog.records[-1]
        payload = json.loads(record.message)
        assert payload["event"] == "turn_start"
        assert payload["session_id"] == "s1"
        assert payload["intent"] == "PLANNING"
        assert payload["wall_ms"] == 123

    def test_handles_non_serializable_fields(self, caplog: Any) -> None:
        """_structured_log uses default=str for non-JSON-serializable fields."""
        with caplog.at_level(logging.INFO, logger="app.planner.coordinator"):
            _structured_log("test", change_type=ChangeType.INITIAL_PLAN)

        record = caplog.records[-1]
        payload = json.loads(record.message)
        assert payload["event"] == "test"
        # ChangeType enum should be stringified via default=str
        assert "INITIAL_PLAN" in payload["change_type"] or "initial_plan" in payload["change_type"]

    def test_default_session_id_is_empty(self, caplog: Any) -> None:
        """_structured_log defaults session_id to empty string."""
        with caplog.at_level(logging.INFO, logger="app.planner.coordinator"):
            _structured_log("simple_event")

        record = caplog.records[-1]
        payload = json.loads(record.message)
        assert payload["event"] == "simple_event"
        assert payload["session_id"] == ""

    def test_extra_fields_included(self, caplog: Any) -> None:
        """Arbitrary keyword arguments are included in the JSON output."""
        with caplog.at_level(logging.INFO, logger="app.planner.coordinator"):
            _structured_log(
                "step_done",
                session_id="s2",
                step="CLASSIFY",
                elapsed_ms=42,
                success=True,
            )

        record = caplog.records[-1]
        payload = json.loads(record.message)
        assert payload["step"] == "CLASSIFY"
        assert payload["elapsed_ms"] == 42
        assert payload["success"] is True

    def test_respects_log_level(self, caplog: Any) -> None:
        """_structured_log respects the level parameter."""
        with caplog.at_level(logging.WARNING, logger="app.planner.coordinator"):
            _structured_log("info_event", session_id="s1", level=logging.INFO)
            _structured_log("warn_event", session_id="s1", level=logging.WARNING)

        # INFO event should be filtered out at WARNING level
        messages = [r.message for r in caplog.records]
        assert not any("info_event" in m for m in messages)
        assert any("warn_event" in m for m in messages)


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
