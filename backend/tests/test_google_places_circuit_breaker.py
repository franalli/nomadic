"""Google Places circuit-breaker and spend-guard protections."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.config import settings
from app.services.spend_guard import clear_spend_guard_counters, spend_guard_scope


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.headers: dict[str, str] = {}

    def json(self) -> dict:
        return self._payload


class _AsyncQuotaClient:
    calls = 0

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args, kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    async def post(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args, kwargs
        _AsyncQuotaClient.calls += 1
        return _FakeResponse(status_code=429, text="quota exceeded")


class _AsyncSuccessClient:
    calls = 0

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args, kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    async def post(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args, kwargs
        _AsyncSuccessClient.calls += 1
        return _FakeResponse(
            status_code=200,
            payload={"places": [{"id": "gp_1", "displayName": {"text": "Beach"}}]},
        )


@pytest.fixture(autouse=True)
def _reset_state():
    from app.tile_service import google_places_provider as provider

    provider.clear_google_places_circuit_breaker()
    clear_spend_guard_counters()
    _AsyncQuotaClient.calls = 0
    _AsyncSuccessClient.calls = 0
    yield
    provider.clear_google_places_circuit_breaker()
    clear_spend_guard_counters()
    _AsyncQuotaClient.calls = 0
    _AsyncSuccessClient.calls = 0


@pytest.mark.asyncio
async def test_places_circuit_opens_and_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tile_service import google_places_provider as provider

    monkeypatch.setattr(settings, "google_maps_api_key", "fake-key")
    monkeypatch.setattr(settings, "google_places_circuit_breaker_enabled", True)
    monkeypatch.setattr(settings, "google_places_circuit_breaker_failure_threshold", 2)
    monkeypatch.setattr(settings, "google_places_circuit_breaker_open_seconds", 120)
    monkeypatch.setattr(settings, "spend_guard_enabled", False)

    with patch("app.tile_service.google_places_provider.httpx.AsyncClient", _AsyncQuotaClient):
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
    assert _AsyncQuotaClient.calls == 2
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

    with patch("app.tile_service.google_places_provider.httpx.AsyncClient", _AsyncSuccessClient):
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
    assert _AsyncSuccessClient.calls == 1
