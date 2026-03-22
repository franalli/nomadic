"""Google Places circuit-breaker and spend-guard protections."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.services import spend_guard as sg_module
from app.services.spend_guard import SpendLimitExceeded, spend_guard_scope


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.headers: dict[str, str] = {}

    def json(self) -> dict:
        return self._payload


class _FakeQuotaClient:
    """Fake httpx client that returns 429 and counts calls."""

    calls = 0

    async def post(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args, kwargs
        _FakeQuotaClient.calls += 1
        return _FakeResponse(status_code=429, text="quota exceeded")


class _FakeSuccessClient:
    """Fake httpx client that returns success and counts calls."""

    calls = 0

    async def post(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args, kwargs
        _FakeSuccessClient.calls += 1
        return _FakeResponse(
            status_code=200,
            payload={"places": [{"id": "gp_1", "displayName": {"text": "Beach"}}]},
        )


@pytest.fixture(autouse=True)
def _reset_state():
    from app.tile_service import google_places_provider as provider

    provider.clear_google_places_circuit_breaker()
    _FakeQuotaClient.calls = 0
    _FakeSuccessClient.calls = 0
    yield
    provider.clear_google_places_circuit_breaker()
    _FakeQuotaClient.calls = 0
    _FakeSuccessClient.calls = 0


@pytest.mark.asyncio
async def test_places_circuit_opens_and_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tile_service import google_places_provider as provider

    monkeypatch.setattr(settings, "google_maps_api_key", "fake-key")
    monkeypatch.setattr(settings, "google_places_circuit_breaker_enabled", True)
    monkeypatch.setattr(settings, "google_places_circuit_breaker_failure_threshold", 2)
    monkeypatch.setattr(settings, "google_places_circuit_breaker_open_seconds", 120)
    monkeypatch.setattr(settings, "spend_guard_enabled", False)

    fake_client = _FakeQuotaClient()
    mock_get_client = AsyncMock(return_value=fake_client)

    with patch.object(provider, "_get_places_http_client", mock_get_client):
        result_1 = await provider._call_places_api_async(
            query="beaches in bali",
            included_type="tourist_attraction",
            path_label="browse",
        )
        result_2 = await provider._call_places_api_async(
            query="beaches in bali",
            included_type="tourist_attraction",
            path_label="browse",
        )
        # Third call should short-circuit before client.post.
        result_3 = await provider._call_places_api_async(
            query="beaches in bali",
            included_type="tourist_attraction",
            path_label="browse",
        )

    assert result_1 == []
    assert result_2 == []
    assert result_3 == []
    assert _FakeQuotaClient.calls == 2
    state = provider.get_google_places_circuit_breaker_state()
    assert state["browse"]["open"] is True


@pytest.mark.asyncio
async def test_places_spend_guard_blocks_second_call_without_hitting_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tile_service import google_places_provider as provider

    monkeypatch.setattr(settings, "google_maps_api_key", "fake-key")
    monkeypatch.setattr(settings, "google_places_circuit_breaker_enabled", False)
    monkeypatch.setattr(settings, "spend_guard_enabled", True)
    monkeypatch.setattr(settings, "spend_guard_session_daily_cap_usd", 0.03)
    monkeypatch.setattr(settings, "spend_guard_global_daily_cap_usd", 10.0)
    monkeypatch.setattr(settings, "spend_guard_places_estimated_call_usd", 0.02)

    # In-memory spend tracking to avoid runtime_state DB dependency
    session_spend: dict[str, float] = {}

    def _mock_reserve_or_raise(
        *, provider: str, estimated_usd: float, session_id: str | None = None, source: str = ""
    ) -> None:
        if not settings.spend_guard_enabled:
            return
        sid = session_id or sg_module._session_id_ctx.get()
        key = f"{sid}:{provider}"
        current = session_spend.get(key, 0.0)
        if current + estimated_usd > float(settings.spend_guard_session_daily_cap_usd):
            raise SpendLimitExceeded(
                provider=provider,
                scope="session",
                limit_usd=float(settings.spend_guard_session_daily_cap_usd),
                current_usd=current,
                requested_usd=estimated_usd,
                source=source,
            )
        session_spend[key] = current + estimated_usd

    monkeypatch.setattr(sg_module, "_reserve_or_raise", _mock_reserve_or_raise)

    fake_client = _FakeSuccessClient()
    mock_get_client = AsyncMock(return_value=fake_client)

    with patch.object(provider, "_get_places_http_client", mock_get_client):
        with spend_guard_scope("session-places"):
            result_1 = await provider._call_places_api_async(
                query="museums in rome",
                included_type="museum",
                path_label="browse",
            )
            # Cap exceeded after first successful call; second should return [] without API call.
            result_2 = await provider._call_places_api_async(
                query="parks in rome",
                included_type="park",
                path_label="browse",
            )

    assert len(result_1) == 1
    assert result_2 == []
    assert _FakeSuccessClient.calls == 1
