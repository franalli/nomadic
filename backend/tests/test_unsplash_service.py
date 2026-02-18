"""Unsplash service behavior tests (fallback + cache guarantees)."""

import asyncio
from unittest.mock import AsyncMock
from urllib.parse import urlparse

import httpx
import pytest

from app.services import unsplash


@pytest.fixture(autouse=True)
async def _clear_unsplash_cache() -> None:
    await unsplash.clear_memory_cache()
    yield
    await unsplash.clear_memory_cache()


@pytest.mark.asyncio
async def test_get_image_for_destination_fallback_is_unsplash_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        unsplash,
        "_fetch_variants_from_unsplash",
        AsyncMock(return_value=[]),
    )

    url = await unsplash.get_image_for_destination("Bali", variant=2, db=None)

    assert urlparse(url).hostname == "images.unsplash.com"
    assert "picsum.photos" not in url


def test_get_image_url_sync_cache_miss_uses_unsplash_placeholder() -> None:
    url = unsplash.get_image_url_sync("Bali", variant=3)

    assert urlparse(url).hostname == "images.unsplash.com"
    assert "picsum.photos" not in url


def test_get_image_url_sync_uses_activity_cache_for_destination_lookup() -> None:
    # Simulate specialist/activity prefetch key present, but base destination key absent.
    unsplash._memory_cache[unsplash._cache_key("Bali", 0, ["diving"])] = unsplash.UnsplashImage(
        image_id="abc123"
    )

    url = unsplash.get_image_url_sync("Bali", variant=0)

    assert "photo-abc123" in url
    assert urlparse(url).hostname == "images.unsplash.com"


def test_get_cached_image_url_uses_activity_cache_for_destination_lookup() -> None:
    unsplash._memory_cache[unsplash._cache_key("Bali", 2, ["surfing"])] = unsplash.UnsplashImage(
        image_id="def456"
    )

    url = unsplash.get_cached_image_url("Bali", variant=2)

    assert url is not None
    assert "photo-def456" in url


def test_get_image_url_sync_activity_lookup_uses_destination_cache() -> None:
    # Simulate destination prefetch key present, but activity key absent.
    unsplash._memory_cache[unsplash._cache_key("Bali", 1)] = unsplash.UnsplashImage(
        image_id="ghi789"
    )

    url = unsplash.get_image_url_sync("Bali", variant=1, activities=["diving"])

    assert "photo-ghi789" in url
    assert urlparse(url).hostname == "images.unsplash.com"


def test_get_cached_image_url_activity_lookup_uses_destination_cache() -> None:
    unsplash._memory_cache[unsplash._cache_key("Bali", 4)] = unsplash.UnsplashImage(
        image_id="jkl012"
    )

    url = unsplash.get_cached_image_url("Bali", variant=4, activities=["surfing"])

    assert url is not None
    assert "photo-jkl012" in url


@pytest.mark.asyncio
async def test_get_image_for_destination_uses_memory_cache_after_first_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_mock = AsyncMock(
        return_value=[
            unsplash.UnsplashImage(image_id="abc123"),
            unsplash.UnsplashImage(image_id="def456"),
        ]
    )
    monkeypatch.setattr(unsplash, "_fetch_variants_from_unsplash", fetch_mock)

    first = await unsplash.get_image_for_destination("Bali", variant=0, db=None)
    second = await unsplash.get_image_for_destination("Bali", variant=0, db=None)

    assert first == second
    assert urlparse(first).hostname == "images.unsplash.com"
    assert fetch_mock.await_count == 1


@pytest.mark.asyncio
async def test_get_image_for_destination_activity_lookup_uses_destination_memory_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsplash._memory_cache[unsplash._cache_key("Bali", 0)] = unsplash.UnsplashImage(
        image_id="mno345"
    )
    fetch_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(unsplash, "_fetch_variants_from_unsplash", fetch_mock)

    url = await unsplash.get_image_for_destination(
        "Bali",
        variant=0,
        db=None,
        activities=["diving"],
    )

    assert "photo-mno345" in url
    assert fetch_mock.await_count == 0


@pytest.mark.asyncio
async def test_fetch_variants_singleflight_dedupes_inflight_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _slow_fetch(*args, **kwargs):
        await asyncio.sleep(0.02)
        return [unsplash.UnsplashImage(image_id="abc123")]

    fetch_once = AsyncMock(side_effect=_slow_fetch)
    monkeypatch.setattr(unsplash, "_fetch_variants_from_unsplash_once", fetch_once)

    first, second = await asyncio.gather(
        unsplash._fetch_variants_from_unsplash("Bali", ["diving"], prefetch=True),
        unsplash._fetch_variants_from_unsplash("Bali", ["diving"], prefetch=False),
    )

    assert len(first) == 1
    assert len(second) == 1
    assert fetch_once.await_count == 1


@pytest.mark.asyncio
async def test_prefetch_failure_cooldown_skips_immediate_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_once = AsyncMock(return_value=[])
    monkeypatch.setattr(unsplash, "_fetch_variants_from_unsplash_once", fetch_once)

    first = await unsplash._fetch_variants_from_unsplash("Bali", ["surfing"], prefetch=True)
    second = await unsplash._fetch_variants_from_unsplash("Bali", ["surfing"], prefetch=True)

    assert first == []
    assert second == []
    assert fetch_once.await_count == 1


@pytest.mark.asyncio
async def test_prefetch_destination_singleflight_coalesces_across_activity_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _slow_fetch(*args, **kwargs):
        await asyncio.sleep(0.02)
        return [unsplash.UnsplashImage(image_id="abc123")]

    fetch_once = AsyncMock(side_effect=_slow_fetch)
    monkeypatch.setattr(unsplash, "_fetch_variants_from_unsplash_once", fetch_once)

    first, second = await asyncio.gather(
        unsplash._fetch_variants_from_unsplash("Bali", ["diving"], prefetch=True),
        unsplash._fetch_variants_from_unsplash("Bali", ["surfing"], prefetch=True),
    )

    assert len(first) == 1
    assert len(second) == 1
    assert fetch_once.await_count == 1
    assert fetch_once.await_args.args[1] is None
    assert fetch_once.await_args.kwargs.get("prefetch") is True


@pytest.mark.asyncio
async def test_prefetch_destination_cooldown_after_timeout_streak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(unsplash, "UNSPLASH_PREFETCH_STREAK_THRESHOLD", 2)
    monkeypatch.setattr(unsplash, "UNSPLASH_PREFETCH_DEST_COOLDOWN_SECONDS", 60.0)
    fetch_once = AsyncMock(return_value=[])
    monkeypatch.setattr(unsplash, "_fetch_variants_from_unsplash_once", fetch_once)

    await unsplash._fetch_variants_from_unsplash("Bali", ["diving"], prefetch=True)
    await unsplash._fetch_variants_from_unsplash("Bali", ["surfing"], prefetch=True)
    third = await unsplash._fetch_variants_from_unsplash("Bali", ["yoga"], prefetch=True)

    assert third == []
    assert fetch_once.await_count == 2
    assert unsplash._prefetch_dest_failure_until.get("bali", 0.0) > 0.0


@pytest.mark.asyncio
async def test_interactive_retry_and_timeout_budget_are_config_driven(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_timeouts: list[float] = []

    class _TimeoutClient:
        is_closed = False

        async def get(self, *args, **kwargs):
            raise httpx.TimeoutException("timeout")

    def _fake_get_http_client(timeout: float = 0.0) -> _TimeoutClient:
        observed_timeouts.append(timeout)
        return _TimeoutClient()

    sleep_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(unsplash, "_get_http_client", _fake_get_http_client)
    monkeypatch.setattr(asyncio, "sleep", sleep_mock)
    monkeypatch.setattr(unsplash.settings, "unsplash_access_key", "test-key", raising=False)
    monkeypatch.setattr(unsplash, "UNSPLASH_REQUEST_TIMEOUT_SECONDS", 0.123)
    monkeypatch.setattr(unsplash, "UNSPLASH_MAX_RETRIES", 2)

    images = await unsplash._fetch_variants_from_unsplash_once("Bali", None, prefetch=False)

    assert images == []
    assert observed_timeouts == [0.123, 0.123, 0.123]
    assert sleep_mock.await_count == 2
