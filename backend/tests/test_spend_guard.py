"""Security guardrail tests: admin auth hardening + LLM spend limits."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import main
from app.config import settings
from app.planner.llm_factory import get_llm_by_model
from app.services.spend_guard import (
    SpendLimitExceeded,
    clear_spend_guard_counters,
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
    monkeypatch.setattr(settings, "spend_guard_global_daily_cap_usd", 0.000001)
    monkeypatch.setattr(settings, "spend_guard_llm_prompt_tokens_estimate", 500)
    monkeypatch.setattr(settings, "spend_guard_llm_completion_tokens_estimate", 500)

    with patch(_OPENAI_TARGET) as mock_cls:
        mock_cls.return_value = MagicMock()
        # No spend_guard_scope(...) set => no principal to budget against.
        get_llm_by_model("gpt-4o")
