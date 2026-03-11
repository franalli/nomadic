"""Security guardrail tests: admin auth hardening + LLM spend limits."""

from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import main
from app.config import settings
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
def _reset_spend_guard_state():
    clear_spend_guard_counters()
    yield
    clear_spend_guard_counters()


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


def test_llm_spend_guard_enforces_session_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "spend_guard_enabled", True)
    monkeypatch.setattr(settings, "spend_guard_session_daily_cap_usd", 0.01)
    monkeypatch.setattr(settings, "spend_guard_global_daily_cap_usd", 10.0)
    monkeypatch.setattr(settings, "spend_guard_llm_prompt_tokens_estimate", 500)
    monkeypatch.setattr(settings, "spend_guard_llm_completion_tokens_estimate", 500)

    with patch(_OPENAI_TARGET) as mock_cls:
        mock_cls.return_value = MagicMock()
        with spend_guard_scope("session-a"):
            get_llm_by_model("gpt-4o")
            with pytest.raises(SpendLimitExceeded) as exc_info:
                get_llm_by_model("gpt-4o")

    assert exc_info.value.scope == "session"


def test_llm_spend_guard_enforces_global_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "spend_guard_enabled", True)
    monkeypatch.setattr(settings, "spend_guard_session_daily_cap_usd", 10.0)
    monkeypatch.setattr(settings, "spend_guard_global_daily_cap_usd", 0.01)
    monkeypatch.setattr(settings, "spend_guard_llm_prompt_tokens_estimate", 500)
    monkeypatch.setattr(settings, "spend_guard_llm_completion_tokens_estimate", 500)

    with patch(_OPENAI_TARGET) as mock_cls:
        mock_cls.return_value = MagicMock()
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
    # Global cap=0 disables global enforcement — test verifies session-level is
    # a no-op without a session, not that global cap blocks.
    monkeypatch.setattr(settings, "spend_guard_global_daily_cap_usd", 0)
    monkeypatch.setattr(settings, "spend_guard_llm_prompt_tokens_estimate", 500)
    monkeypatch.setattr(settings, "spend_guard_llm_completion_tokens_estimate", 500)
    clear_spend_guard_counters()

    with patch(_OPENAI_TARGET) as mock_cls:
        mock_cls.return_value = MagicMock()
        # No spend_guard_scope(...) set => no principal to budget against.
        get_llm_by_model("gpt-4o")


# ---------------------------------------------------------------------------
# Day-roll reset
# ---------------------------------------------------------------------------
def test_dayroll_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Counters reset when the UTC date advances (simulated via _current_day_key mock)."""
    monkeypatch.setattr(settings, "spend_guard_enabled", True)
    monkeypatch.setattr(settings, "spend_guard_session_daily_cap_usd", 1.0)
    monkeypatch.setattr(settings, "spend_guard_global_daily_cap_usd", 1.0)
    clear_spend_guard_counters()

    # Spend some budget on day-1
    with spend_guard_scope("sess-day"):
        _reserve_or_raise(provider="llm", estimated_usd=0.50, source="test")

    snap1 = get_spend_guard_snapshot()
    assert snap1["global_spend_usd"] == pytest.approx(0.50)

    # Simulate date advancing to tomorrow
    monkeypatch.setattr(sg_module, "_current_day_key", lambda: "2099-01-02")

    # Next reservation triggers rollover; counters should be zero + the new reservation
    with spend_guard_scope("sess-day"):
        _reserve_or_raise(provider="llm", estimated_usd=0.10, source="test")

    snap2 = get_spend_guard_snapshot()
    assert snap2["day"] == "2099-01-02"
    assert snap2["global_spend_usd"] == pytest.approx(0.10)


# ---------------------------------------------------------------------------
# Concurrent access under _spend_lock
# ---------------------------------------------------------------------------
def test_concurrent_access_under_spend_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent reserve calls are serialised by _spend_lock and never exceed the cap."""
    monkeypatch.setattr(settings, "spend_guard_enabled", True)
    monkeypatch.setattr(settings, "spend_guard_session_daily_cap_usd", 100.0)
    # Global cap allows exactly 10 x $0.10 = $1.00
    monkeypatch.setattr(settings, "spend_guard_global_daily_cap_usd", 1.0)
    clear_spend_guard_counters()

    n_threads = 20
    cost_per_call = 0.10
    successes: list[bool] = []
    failures: list[bool] = []

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

    successes = [r for r in results if r == "ok"]
    failures = [r for r in results if r == "exceeded"]

    # Exactly 10 should succeed ($1.00 cap / $0.10 per call)
    assert len(successes) == 10
    assert len(failures) == 10

    snap = get_spend_guard_snapshot()
    assert snap["global_spend_usd"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Session-less requests enforce global cap only
# ---------------------------------------------------------------------------
def test_session_less_requests_enforce_global_cap_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When session_id is None the per-session cap is skipped but global cap is enforced."""
    monkeypatch.setattr(settings, "spend_guard_enabled", True)
    # Tiny session cap — should NOT trigger because there is no session
    monkeypatch.setattr(settings, "spend_guard_session_daily_cap_usd", 0.001)
    monkeypatch.setattr(settings, "spend_guard_global_daily_cap_usd", 0.50)
    clear_spend_guard_counters()

    # First call: no session context, should succeed (global cap not reached)
    _reserve_or_raise(
        provider="llm",
        estimated_usd=0.30,
        session_id=None,
        source="test-no-session",
    )
    snap = get_spend_guard_snapshot()
    assert snap["global_spend_usd"] == pytest.approx(0.30)

    # Second call: still no session, pushes past global cap
    with pytest.raises(SpendLimitExceeded) as exc_info:
        _reserve_or_raise(
            provider="llm",
            estimated_usd=0.30,
            session_id=None,
            source="test-no-session-2",
        )

    assert exc_info.value.scope == "global"


def test_load_state_ignores_legacy_partner_provider_spend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Legacy persisted partner spend is ignored during startup restore."""
    state_file = tmp_path / "spend_guard_state.json"
    monkeypatch.setattr(sg_module, "_SPEND_STATE_FILE", state_file)

    state_file.write_text(
        json.dumps(
            {
                "day": sg_module._spend_day_key,
                "global_spend_usd": 1.23,
                "provider_spend_usd": {
                    "llm": 0.11,
                    "places": 0.22,
                    "partner": 0.33,
                },
                "session_spend_usd": {"session-a": 0.44},
            }
        ),
        encoding="utf-8",
    )

    sg_module._global_spend_usd = 0.0
    sg_module._provider_spend_usd["llm"] = 0.0
    sg_module._provider_spend_usd["places"] = 0.0
    sg_module._session_spend_usd.clear()

    sg_module._load_state()

    snapshot = get_spend_guard_snapshot()
    assert snapshot["global_spend_usd"] == pytest.approx(1.23)
    assert snapshot["provider_spend_usd"] == {
        "llm": pytest.approx(0.11),
        "places": pytest.approx(0.22),
    }
    assert "partner" not in snapshot["provider_spend_usd"]
    assert snapshot["session_count"] == 1
