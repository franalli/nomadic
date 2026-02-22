"""
Tests for Google Places activity enrichment efficiency controls.

Covers:
1. Transient enrichment failures (5xx) retry with backoff.
2. 429 responses honor Retry-After and retry.
3. Malformed JSON responses retry safely.
4. Batch enrichment respects the configured concurrency cap.
5. End-to-end enrichment uses HTTP retry + semaphore without stubbing core helper.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

_GET_CACHE = "app.tile_service.google_places_provider._get_cached_enrichment"
_SET_CACHE = "app.tile_service.google_places_provider._set_cached_enrichment"
_ENRICH_SINGLE = "app.tile_service.google_places_provider._enrich_single_activity"
_ENRICH_MAX_PARALLEL = "app.tile_service.google_places_provider._enrich_max_parallel"
_RETRY_ATTEMPTS = "app.tile_service.google_places_provider._enrich_retry_attempts"
_BACKOFF_SECONDS = "app.tile_service.google_places_provider._enrich_backoff_seconds"
_ASYNCIO_SLEEP = "app.tile_service.google_places_provider.asyncio.sleep"


@pytest.fixture(autouse=True)
def _clear_enrich_l1_cache():
    from app.tile_service.google_places_provider import _enrich_mem

    _enrich_mem.clear()
    yield
    _enrich_mem.clear()


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict | None = None,
        text: str = "",
        headers: dict[str, str] | None = None,
        json_error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.headers = headers or {}
        self._json_error = json_error

    def json(self) -> dict:
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = responses
        self.calls = 0

    async def post(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.calls += 1
        if not self._responses:
            raise AssertionError("No more fake responses configured")
        return self._responses.pop(0)


class _FakeAsyncHttpClient:
    """httpx.AsyncClient test double for end-to-end enrichment tests."""

    def __init__(self, post_handler, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        self._post_handler = post_handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    async def post(self, url, headers=None, json=None):  # noqa: ANN001, ANN002, ANN003
        return await self._post_handler(url=url, headers=headers, json=json)


@pytest.mark.asyncio
async def test_enrich_single_activity_retries_on_transient_5xx():
    from app.tile_service.google_places_provider import _enrich_single_activity

    place = {
        "id": "gp_retry_ok",
        "location": {"latitude": -8.67, "longitude": 115.21},
        "googleMapsUri": "https://maps.google.com/?q=place_id:gp_retry_ok",
    }
    client = _FakeClient(
        responses=[
            _FakeResponse(status_code=503, text="upstream unavailable"),
            _FakeResponse(status_code=200, payload={"places": [place]}),
        ]
    )
    sleep_mock = AsyncMock()

    with (
        patch(_GET_CACHE, new_callable=AsyncMock) as mock_get_cache,
        patch(_SET_CACHE, new_callable=AsyncMock) as mock_set_cache,
        patch(_RETRY_ATTEMPTS, return_value=2),
        patch(_BACKOFF_SECONDS, return_value=0.0),
        patch(_ASYNCIO_SLEEP, new=sleep_mock),
    ):
        mock_get_cache.return_value = None
        enriched = await _enrich_single_activity(
            client=client,
            activity={"title": "Surf Lesson", "description": "Beginner friendly"},
            destination="Bali",
            api_key="fake-key",  # pragma: allowlist secret
            path_label="tier2_enrich",
        )

    assert client.calls == 2
    assert sleep_mock.await_count == 1
    assert enriched.get("google_place_id") == "gp_retry_ok"
    mock_set_cache.assert_awaited()


@pytest.mark.asyncio
async def test_enrich_single_activity_uses_retry_after_on_429():
    from app.tile_service.google_places_provider import _enrich_single_activity

    place = {
        "id": "gp_retry_after_ok",
        "location": {"latitude": -8.67, "longitude": 115.21},
        "googleMapsUri": "https://maps.google.com/?q=place_id:gp_retry_after_ok",
    }
    client = _FakeClient(
        responses=[
            _FakeResponse(
                status_code=429,
                text="rate limited",
                headers={"Retry-After": "1"},
            ),
            _FakeResponse(status_code=200, payload={"places": [place]}),
        ]
    )
    sleep_mock = AsyncMock()

    with (
        patch(_GET_CACHE, new_callable=AsyncMock) as mock_get_cache,
        patch(_SET_CACHE, new_callable=AsyncMock) as mock_set_cache,
        patch(_RETRY_ATTEMPTS, return_value=2),
        patch(_BACKOFF_SECONDS, return_value=0.0),
        patch(_ASYNCIO_SLEEP, new=sleep_mock),
    ):
        mock_get_cache.return_value = None
        enriched = await _enrich_single_activity(
            client=client,
            activity={"title": "Waterfall Tour"},
            destination="Bali",
            api_key="fake-key",  # pragma: allowlist secret
            path_label="tier2_enrich",
        )

    assert client.calls == 2
    sleep_mock.assert_awaited_once_with(1.0)
    assert enriched.get("google_place_id") == "gp_retry_after_ok"
    mock_set_cache.assert_awaited_once()


@pytest.mark.asyncio
async def test_enrich_single_activity_retries_invalid_json_response():
    from app.tile_service.google_places_provider import _enrich_single_activity

    place = {
        "id": "gp_json_ok",
        "location": {"latitude": -8.67, "longitude": 115.21},
        "googleMapsUri": "https://maps.google.com/?q=place_id:gp_json_ok",
    }
    client = _FakeClient(
        responses=[
            _FakeResponse(status_code=200, json_error=ValueError("invalid json")),
            _FakeResponse(status_code=200, payload={"places": [place]}),
        ]
    )
    sleep_mock = AsyncMock()

    with (
        patch(_GET_CACHE, new_callable=AsyncMock) as mock_get_cache,
        patch(_SET_CACHE, new_callable=AsyncMock) as mock_set_cache,
        patch(_RETRY_ATTEMPTS, return_value=2),
        patch(_BACKOFF_SECONDS, return_value=0.0),
        patch(_ASYNCIO_SLEEP, new=sleep_mock),
    ):
        mock_get_cache.return_value = None
        enriched = await _enrich_single_activity(
            client=client,
            activity={"title": "Temple Walk"},
            destination="Bali",
            api_key="fake-key",  # pragma: allowlist secret
            path_label="tier2_enrich",
        )

    assert client.calls == 2
    assert sleep_mock.await_count == 1
    assert enriched.get("google_place_id") == "gp_json_ok"
    mock_set_cache.assert_awaited_once()


@pytest.mark.asyncio
async def test_enrich_activities_respects_concurrency_limit():
    from app.tile_service import google_places_provider as provider

    in_flight = 0
    peak_in_flight = 0

    async def _slow_enrich(client, activity, destination, api_key, path_label):  # noqa: ANN001
        nonlocal in_flight, peak_in_flight
        in_flight += 1
        peak_in_flight = max(peak_in_flight, in_flight)
        await asyncio.sleep(0.02)
        in_flight -= 1
        return {**activity, "google_place_id": f"gp_{activity.get('title', 'x')}"}

    activities = [{"title": f"Activity {i}"} for i in range(6)]

    with (
        patch(_ENRICH_SINGLE, new=AsyncMock(side_effect=_slow_enrich)) as mock_single,
        patch(_ENRICH_MAX_PARALLEL, return_value=2),
        patch.object(provider.settings, "google_maps_api_key", "fake-key"),
    ):
        enriched = await provider.enrich_activities_with_places(
            activities=activities,
            destination="Bali",
            path_label="tier2_enrich",
        )

    assert len(enriched) == len(activities)
    assert mock_single.await_count == len(activities)
    assert peak_in_flight <= 2


@pytest.mark.asyncio
async def test_enrich_activities_http_retry_and_semaphore_integration():
    from app.tile_service import google_places_provider as provider

    in_flight = 0
    peak_in_flight = 0
    calls_by_query: dict[str, int] = {}

    async def _post_handler(url, headers, json):  # noqa: ANN001
        nonlocal in_flight, peak_in_flight
        query = (json or {}).get("textQuery", "")
        calls_by_query[query] = calls_by_query.get(query, 0) + 1

        in_flight += 1
        peak_in_flight = max(peak_in_flight, in_flight)
        await asyncio.sleep(0.02)
        in_flight -= 1

        # First call for Activity 1 fails (5xx), second succeeds via retry.
        if query == "Activity 1 Bali" and calls_by_query[query] == 1:
            return _FakeResponse(status_code=503, text="upstream unavailable")

        place_id = query.lower().replace(" ", "_")
        return _FakeResponse(
            status_code=200,
            payload={
                "places": [
                    {
                        "id": place_id,
                        "location": {"latitude": -8.67, "longitude": 115.21},
                        "googleMapsUri": f"https://maps.google.com/?q=place_id:{place_id}",
                    }
                ]
            },
        )

    activities = [{"title": f"Activity {i}"} for i in range(4)]

    with (
        patch(_GET_CACHE, new_callable=AsyncMock) as mock_get_cache,
        patch(_SET_CACHE, new_callable=AsyncMock) as mock_set_cache,
        patch("app.tile_service.google_places_provider.httpx.AsyncClient") as mock_http_client,
        patch(_ENRICH_MAX_PARALLEL, return_value=2),
        patch(_RETRY_ATTEMPTS, return_value=2),
        patch(_BACKOFF_SECONDS, return_value=0.0),
        patch.object(provider.settings, "google_maps_api_key", "fake-key"),
    ):
        mock_get_cache.return_value = None
        mock_http_client.side_effect = lambda *args, **kwargs: _FakeAsyncHttpClient(
            _post_handler, *args, **kwargs
        )

        enriched = await provider.enrich_activities_with_places(
            activities=activities,
            destination="Bali",
            path_label="tier2_enrich",
        )

    assert len(enriched) == len(activities)
    assert all(item.get("google_place_id") for item in enriched)
    assert calls_by_query.get("Activity 1 Bali") == 2
    assert sum(calls_by_query.values()) == len(activities) + 1
    assert peak_in_flight <= 2
    assert mock_set_cache.await_count == len(activities)
