"""Security guardrail tests: admin auth hardening + LLM spend limits."""

from __future__ import annotations

import concurrent.futures
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app import main
from app.config import settings
from app.db_models import RuntimeState
from app.planner.llm_factory import get_llm_by_model
from app.services import spend_guard as sg_module
from app.services.spend_guard import (
    SpendLimitExceeded,
    _reserve_or_raise,
    clear_spend_guard_counters,
    get_spend_guard_snapshot,
    spend_guard_scope,
)

_OPENAI_TARGET = "langchain_openai.ChatOpenAI"


def _request(headers: dict[str, str] | None = None) -> Request:
    raw_headers = []
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode("latin-1"), value.encode("latin-1")))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/admin/planner",
        "raw_path": b"/api/admin/planner",
        "query_string": b"",
        "headers": raw_headers,
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }
    return Request(scope)


@pytest.fixture(autouse=True)
def _runtime_state_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Use an isolated SQLite file DB for shared spend counters in each test."""
    db_path = tmp_path / "spend_guard.sqlite"
    engine = create_engine(
        f"sqlite+pysqlite:///{db_path}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    test_session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        future=True,
    )

    RuntimeState.__table__.create(bind=engine)
    monkeypatch.setattr(sg_module.db_module, "SessionLocal", test_session_local)

    yield test_session_local

    with test_session_local() as db:
        db.execute(delete(RuntimeState))
        db.commit()
    engine.dispose()


@pytest.fixture(autouse=True)
def _reset_spend_guard_state(_runtime_state_db: sessionmaker):
    clear_spend_guard_counters()
    yield
    clear_spend_guard_counters()


def _runtime_rows(test_session_local: sessionmaker) -> list[RuntimeState]:
    with test_session_local() as db:
        return list(db.execute(select(RuntimeState)).scalars())


@pytest.mark.asyncio
async def test_require_admin_rejects_when_key_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main.settings, "admin_api_key", "")

    with pytest.raises(HTTPException) as exc_info:
        await main.require_admin(_request())

    assert exc_info.value.status_code == 403
    assert "not configured" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_require_admin_rejects_wrong_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.settings, "admin_api_key", "expected-key")

    with pytest.raises(HTTPException) as exc_info:
        await main.require_admin(_request({"X-Admin-Key": "wrong-key"}))

    assert exc_info.value.status_code == 403
    assert "invalid" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_require_admin_allows_valid_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.settings, "admin_api_key", "expected-key")
    await main.require_admin(_request({"X-Admin-Key": "expected-key"}))


def test_llm_spend_guard_enforces_session_cap(
    _runtime_state_db: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "spend_guard_enabled", True)
    monkeypatch.setattr(settings, "spend_guard_session_daily_cap_usd", 0.01)
    monkeypatch.setattr(settings, "spend_guard_global_daily_cap_usd", 10.0)
    monkeypatch.setattr(settings, "spend_guard_llm_prompt_tokens_estimate", 500)
    monkeypatch.setattr(settings, "spend_guard_llm_completion_tokens_estimate", 500)

    with patch(_OPENAI_TARGET) as mock_cls:
        mock_cls.return_value = object()
        with spend_guard_scope("session-a"):
            get_llm_by_model("gpt-4o")
            with pytest.raises(SpendLimitExceeded) as exc_info:
                get_llm_by_model("gpt-4o")

    assert exc_info.value.scope == "session"
    assert {row.scope for row in _runtime_rows(_runtime_state_db)} == {
        "global",
        "provider",
        "session",
    }


def test_llm_spend_guard_enforces_global_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "spend_guard_enabled", True)
    monkeypatch.setattr(settings, "spend_guard_session_daily_cap_usd", 10.0)
    monkeypatch.setattr(settings, "spend_guard_global_daily_cap_usd", 0.01)
    monkeypatch.setattr(settings, "spend_guard_llm_prompt_tokens_estimate", 500)
    monkeypatch.setattr(settings, "spend_guard_llm_completion_tokens_estimate", 500)

    with patch(_OPENAI_TARGET) as mock_cls:
        mock_cls.return_value = object()
        with spend_guard_scope("session-a"):
            get_llm_by_model("gpt-4o")
        with spend_guard_scope("session-b"):
            with pytest.raises(SpendLimitExceeded) as exc_info:
                get_llm_by_model("gpt-4o")

    assert exc_info.value.scope == "global"


def test_llm_spend_guard_is_noop_without_session_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "spend_guard_enabled", True)
    monkeypatch.setattr(settings, "spend_guard_session_daily_cap_usd", 0.000001)
    monkeypatch.setattr(settings, "spend_guard_global_daily_cap_usd", 0)
    monkeypatch.setattr(settings, "spend_guard_llm_prompt_tokens_estimate", 500)
    monkeypatch.setattr(settings, "spend_guard_llm_completion_tokens_estimate", 500)
    clear_spend_guard_counters()

    with patch(_OPENAI_TARGET) as mock_cls:
        mock_cls.return_value = object()
        get_llm_by_model("gpt-4o")


def test_dayroll_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Counters reset when the UTC date advances (simulated via _current_day_key mock)."""
    monkeypatch.setattr(settings, "spend_guard_enabled", True)
    monkeypatch.setattr(settings, "spend_guard_session_daily_cap_usd", 1.0)
    monkeypatch.setattr(settings, "spend_guard_global_daily_cap_usd", 1.0)
    clear_spend_guard_counters()

    with spend_guard_scope("sess-day"):
        _reserve_or_raise(provider="llm", estimated_usd=0.50, source="test")

    snap1 = get_spend_guard_snapshot()
    assert snap1["global_spend_usd"] == pytest.approx(0.50)

    monkeypatch.setattr(sg_module, "_current_day_key", lambda: "2099-01-02")

    with spend_guard_scope("sess-day"):
        _reserve_or_raise(provider="llm", estimated_usd=0.10, source="test")

    snap2 = get_spend_guard_snapshot()
    assert snap2["day"] == "2099-01-02"
    assert snap2["global_spend_usd"] == pytest.approx(0.10)


def test_concurrent_access_under_spend_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent reserve calls are serialised by shared state and never exceed the cap."""
    monkeypatch.setattr(settings, "spend_guard_enabled", True)
    monkeypatch.setattr(settings, "spend_guard_session_daily_cap_usd", 100.0)
    monkeypatch.setattr(settings, "spend_guard_global_daily_cap_usd", 1.0)
    clear_spend_guard_counters()

    n_threads = 20
    cost_per_call = 0.10

    def _attempt(idx: int) -> str:
        try:
            with spend_guard_scope(f"sess-{idx}"):
                _reserve_or_raise(
                    provider="llm",
                    estimated_usd=cost_per_call,
                    source=f"thread-{idx}",
                )
            return "ok"
        except SpendLimitExceeded:
            return "exceeded"

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as pool:
        results = list(pool.map(_attempt, range(n_threads)))

    assert results.count("ok") == 10
    assert results.count("exceeded") == 10

    snap = get_spend_guard_snapshot()
    assert snap["global_spend_usd"] == pytest.approx(1.0)


def test_session_less_requests_enforce_global_cap_only(
    _runtime_state_db: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When session_id is None the per-session cap is skipped but global cap is enforced."""
    monkeypatch.setattr(settings, "spend_guard_enabled", True)
    monkeypatch.setattr(settings, "spend_guard_session_daily_cap_usd", 0.001)
    monkeypatch.setattr(settings, "spend_guard_global_daily_cap_usd", 0.50)
    clear_spend_guard_counters()

    _reserve_or_raise(
        provider="llm",
        estimated_usd=0.30,
        session_id=None,
        source="test-no-session",
    )
    snap = get_spend_guard_snapshot()
    assert snap["global_spend_usd"] == pytest.approx(0.30)

    with pytest.raises(SpendLimitExceeded) as exc_info:
        _reserve_or_raise(
            provider="llm",
            estimated_usd=0.30,
            session_id=None,
            source="test-no-session-2",
        )

    assert exc_info.value.scope == "global"
    assert {row.scope for row in _runtime_rows(_runtime_state_db)} == {"global", "provider"}


def test_flush_spend_state_is_safe_noop_for_db_backed_counters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """flush_spend_state should not alter DB-backed counters."""
    monkeypatch.setattr(settings, "spend_guard_enabled", True)

    with spend_guard_scope("session-a"):
        _reserve_or_raise(provider="llm", estimated_usd=0.11, source="test-llm")
        _reserve_or_raise(provider="places", estimated_usd=0.22, source="test-places")

    before = get_spend_guard_snapshot()
    sg_module.flush_spend_state()
    after = get_spend_guard_snapshot()

    assert before["global_spend_usd"] == pytest.approx(0.33)
    assert before["provider_spend_usd"] == {
        "llm": pytest.approx(0.11),
        "places": pytest.approx(0.22),
    }
    assert before["session_count"] == 1
    assert after == before


def test_reserve_or_raise_purges_stale_spend_rows(
    _runtime_state_db: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "spend_guard_enabled", True)
    stale_day = "2000-01-01"

    with _runtime_state_db() as db, db.begin():
        db.add(
            RuntimeState(
                state_key=f"spend:session:stale-session:{stale_day}",
                state_type="spend_counter",
                scope="session",
                session_id="stale-session",
                day_key=stale_day,
                expires_at=datetime.now(UTC) - timedelta(days=1),
                value_micro_usd=123_000,
            )
        )
        db.add(
            RuntimeState(
                state_key=f"spend:global:{stale_day}",
                state_type="spend_counter",
                scope="global",
                session_id=None,
                day_key=stale_day,
                expires_at=None,
                value_micro_usd=456_000,
            )
        )

    with spend_guard_scope("session-a"):
        _reserve_or_raise(provider="llm", estimated_usd=0.10, source="test-purge")

    rows = _runtime_rows(_runtime_state_db)
    current_day = sg_module._current_day_key()
    assert all(row.day_key == current_day for row in rows)
    assert all(row.expires_at is not None for row in rows)
    assert {row.scope for row in rows} == {"global", "provider", "session"}
