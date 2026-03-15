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
_RESERVE_SPEND = "app.tile_service.google_places_provider.reserve_places_spend_or_raise"


@pytest.fixture(autouse=True)
def _clear_enrich_state():
    import app.tile_service.google_places_provider as provider

    provider._enrich_mem.clear()
    provider._enrich_inflight.clear()
    provider.clear_geocode_caches()
    # Reset shared httpx client so tests using httpx.AsyncClient mock get a fresh client
    provider._places_http_client = None
    # Reset circuit breaker state from previous tests
    provider.clear_google_places_circuit_breaker()
    yield
    provider._enrich_mem.clear()
    provider._enrich_inflight.clear()
    provider.clear_geocode_caches()
    provider._places_http_client = None


class _TrackingAsyncLock:
    def __init__(self) -> None:
        self.enter_count = 0

    async def __aenter__(self) -> "_TrackingAsyncLock":
        self.enter_count += 1
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return False


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

    is_closed = False

    def __init__(self, post_handler, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        self._post_handler = post_handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    async def post(self, url, headers=None, json=None, **kwargs):  # noqa: ANN001, ANN002, ANN003
        return await self._post_handler(url=url, headers=headers, json=json)


def test_apply_place_to_activity_sets_photo_name_for_proxying():
    from app.tile_service.google_places_provider import _apply_place_to_activity

    activity = {
        "title": "Cooking Class",
        "meta": {"category": "cooking"},
        "image_url": "https://images.unsplash.com/photo-placeholder",
    }
    place = {
        "id": "gp_photo_name",
        "photos": [{"name": "places/abc123/photos/photo456"}],
        "location": {"latitude": 41.89, "longitude": 12.49},
    }

    enriched = _apply_place_to_activity(activity, place, "Cooking Class")

    assert enriched.get("photo_name") == "places/abc123/photos/photo456"
    assert (enriched.get("meta") or {}).get("photo_name") == "places/abc123/photos/photo456"


@pytest.mark.asyncio
async def test_clear_google_places_runtime_caches_drains_inflight_under_lock():
    from app.tile_service import google_places_provider as provider

    provider._geocode_cache["bali"] = (-8.67, 115.21)
    provider._country_code_cache["bali"] = "ID"
    provider._enrich_inflight["bali::reef"] = asyncio.get_running_loop().create_future()
    tracking_lock = _TrackingAsyncLock()

    with patch.object(provider, "_enrich_inflight_lock", tracking_lock):
        cleared = await provider.clear_google_places_runtime_caches()

    assert cleared == {"geocode_cache": 1, "country_code_cache": 1}
    assert provider._enrich_inflight == {}
    assert tracking_lock.enter_count == 1


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
        patch(_RESERVE_SPEND, return_value=None),
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
        patch(_RESERVE_SPEND, return_value=None),
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
        patch(_RESERVE_SPEND, return_value=None),
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
async def test_enrich_activities_short_circuits_when_all_places_are_already_present():
    from app.tile_service import google_places_provider as provider

    activities = [
        {
            "title": "Surf Lesson",
            "google_place_id": "gp_surf",
            "coordinates": {"lat": -8.67, "lng": 115.21},
            "image_url": "https://maps.example/surf.jpg",
            "deeplink": "https://www.google.com/maps/place/?q=place_id:gp_surf",
        },
        {
            "title": "Temple Visit",
            "place_id": "gp_temple",
            "geo": {"lat": -8.50, "lng": 115.15},
            "image_url": "https://maps.example/temple.jpg",
            "deeplink_url": "https://www.google.com/maps/place/?q=place_id:gp_temple",
        },
    ]

    with (
        patch.object(provider.settings, "google_maps_api_key", "fake-key"),
        patch(_ENRICH_SINGLE, new_callable=AsyncMock) as mock_single,
    ):
        enriched = await provider.enrich_activities_with_places(
            activities=activities,
            destination="Bali",
            path_label="tier2_enrich",
        )

    assert enriched == activities
    mock_single.assert_not_awaited()


@pytest.mark.asyncio
async def test_enrich_activities_does_not_short_circuit_without_image_and_link():
    from app.tile_service import google_places_provider as provider

    activities = [
        {
            "title": "Surf Lesson",
            "google_place_id": "gp_surf",
            "coordinates": {"lat": -8.67, "lng": 115.21},
        }
    ]

    with (
        patch.object(provider.settings, "google_maps_api_key", "fake-key"),
        patch.object(provider.settings, "google_places_enrichment_cap", len(activities)),
        patch(
            _ENRICH_SINGLE,
            new=AsyncMock(
                return_value={
                    **activities[0],
                    "image_url": "https://maps.example/surf.jpg",
                    "deeplink": "https://www.google.com/maps/place/?q=place_id:gp_surf",
                }
            ),
        ) as mock_single,
    ):
        enriched = await provider.enrich_activities_with_places(
            activities=activities,
            destination="Bali",
            path_label="tier2_enrich",
        )

    mock_single.assert_awaited_once()
    assert enriched[0]["image_url"] == "https://maps.example/surf.jpg"
    assert enriched[0]["deeplink"] == "https://www.google.com/maps/place/?q=place_id:gp_surf"


@pytest.mark.asyncio
async def test_enrich_activities_respects_concurrency_limit():
    from app.tile_service import google_places_provider as provider

    in_flight = 0
    peak_in_flight = 0

    async def _slow_enrich(  # noqa: ANN001
        client,
        activity,
        destination,
        api_key,
        path_label,
        travelers=1,
    ):
        nonlocal in_flight, peak_in_flight
        assert travelers == 1
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
        patch.object(provider.settings, "google_places_enrichment_cap", len(activities)),
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
        patch(_RESERVE_SPEND, return_value=None),
        patch.object(provider.settings, "google_maps_api_key", "fake-key"),
        patch.object(provider.settings, "google_places_enrichment_cap", len(activities)),
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
