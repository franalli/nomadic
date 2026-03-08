"""Tests for Viator affiliate API provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.viator_provider import (
    match_activity_to_viator,
    resolve_destination_id,
    search_freetext,
    viator_product_to_tile,
)


@pytest.fixture(autouse=True)
def _reset_viator_state():
    """Reset module-level caches and circuit breaker between tests."""
    import app.services.viator_provider as vp

    vp._viator_circuit_failures = 0
    vp._viator_circuit_open_until = 0.0
    vp._dest_cache._cache.clear()
    vp._match_cache._cache.clear()
    vp._browse_viator_cache._cache.clear()
    yield


SAMPLE_PRODUCT = {
    "productCode": "12345P1",
    "title": "Sunset Sailing Cruise",
    "pricing": {
        "summary": {"fromPrice": 89.99},
        "currency": "USD",
    },
    "images": [
        {
            "isCover": True,
            "variants": [{"width": 480, "height": 320, "url": "https://example.com/img.jpg"}],
        }
    ],
    "reviews": {"combinedAverageRating": 4.7, "totalReviews": 234},
    "duration": {"fixedDurationInMinutes": 180},
    "productUrl": "https://www.viator.com/tours/test/12345P1",
}


class TestViatorProductToTile:
    def test_basic_conversion(self):
        tile = viator_product_to_tile(SAMPLE_PRODUCT, "Santorini")
        assert tile["id"] == "viator_12345P1"
        assert tile["type"] == "activity"
        assert tile["partner"] == "viator"
        assert tile["price_estimate"] == 89.99
        assert tile["rating"] == 4.7
        assert tile["review_count"] == 234
        assert tile["image_url"] == "https://example.com/img.jpg"
        assert tile["deeplink"] == "https://www.viator.com/tours/test/12345P1"
        assert tile["meta"]["duration_hours"] == 3.0

    def test_missing_optional_fields(self):
        minimal = {"productCode": "MIN1", "title": "Basic Tour"}
        tile = viator_product_to_tile(minimal, "Paris")
        assert tile["id"] == "viator_MIN1"
        assert "price_estimate" not in tile
        assert "rating" not in tile
        assert "image_url" not in tile


@pytest.mark.asyncio
class TestResolveDestinationId:
    async def test_exact_match(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "destinations": [
                {"destinationName": "Paris", "destinationId": 51},
                {"destinationName": "Rome", "destinationId": 52},
            ]
        }
        with patch("app.services.viator_provider._get_viator_client") as mock_client:
            client = AsyncMock()
            client.get = AsyncMock(return_value=mock_resp)
            mock_client.return_value = client
            result = await resolve_destination_id("Paris")
            assert result == 51

    async def test_fuzzy_match(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "destinations": [
                {"destinationName": "Santorini, Greece", "destinationId": 99},
            ]
        }
        with patch("app.services.viator_provider._get_viator_client") as mock_client:
            client = AsyncMock()
            client.get = AsyncMock(return_value=mock_resp)
            mock_client.return_value = client
            # Substring match: "Santorini" is in "Santorini, Greece"
            result = await resolve_destination_id("Santorini")
            assert result == 99

    async def test_circuit_open_returns_none(self):
        import app.services.viator_provider as vp

        vp._viator_circuit_failures = 10
        vp._viator_circuit_open_until = 9999999999.0
        result = await resolve_destination_id("Paris")
        assert result is None


@pytest.mark.asyncio
class TestSearchFreetext:
    async def test_returns_products(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"products": {"results": [SAMPLE_PRODUCT]}}
        with patch("app.services.viator_provider._get_viator_client") as mock_client:
            client = AsyncMock()
            client.post = AsyncMock(return_value=mock_resp)
            mock_client.return_value = client
            results = await search_freetext("sailing", None)
            assert len(results) == 1
            assert results[0]["productCode"] == "12345P1"

    async def test_circuit_open_returns_empty(self):
        import app.services.viator_provider as vp

        vp._viator_circuit_failures = 10
        vp._viator_circuit_open_until = 9999999999.0
        results = await search_freetext("test", None)
        assert results == []


@pytest.mark.asyncio
class TestMatchActivityToViator:
    async def test_match_returns_tile(self):
        """Match should call resolve_destination_id + search_freetext and return a tile."""
        mock_dest_resp = MagicMock()
        mock_dest_resp.status_code = 200
        mock_dest_resp.raise_for_status = MagicMock()
        mock_dest_resp.json.return_value = {
            "destinations": [
                {"destinationName": "Santorini", "destinationId": 99},
            ]
        }

        mock_search_resp = MagicMock()
        mock_search_resp.status_code = 200
        mock_search_resp.raise_for_status = MagicMock()
        mock_search_resp.json.return_value = {"products": {"results": [SAMPLE_PRODUCT]}}

        with patch("app.services.viator_provider._get_viator_client") as mock_client:
            client = AsyncMock()
            client.get = AsyncMock(return_value=mock_dest_resp)
            client.post = AsyncMock(return_value=mock_search_resp)
            mock_client.return_value = client

            tile = await match_activity_to_viator("Sunset Sailing Cruise", "Santorini")
            assert tile is not None
            assert tile["id"] == "viator_12345P1"
            assert tile["partner"] == "viator"

    async def test_cache_hit_on_second_call(self):
        """Second call should return cached result without API calls."""
        mock_dest_resp = MagicMock()
        mock_dest_resp.status_code = 200
        mock_dest_resp.raise_for_status = MagicMock()
        mock_dest_resp.json.return_value = {
            "destinations": [
                {"destinationName": "Santorini", "destinationId": 99},
            ]
        }

        mock_search_resp = MagicMock()
        mock_search_resp.status_code = 200
        mock_search_resp.raise_for_status = MagicMock()
        mock_search_resp.json.return_value = {"products": {"results": [SAMPLE_PRODUCT]}}

        with patch("app.services.viator_provider._get_viator_client") as mock_client:
            client = AsyncMock()
            client.get = AsyncMock(return_value=mock_dest_resp)
            client.post = AsyncMock(return_value=mock_search_resp)
            mock_client.return_value = client

            # First call populates cache
            tile1 = await match_activity_to_viator("Sunset Sailing Cruise", "Santorini")
            assert tile1 is not None

            # Second call should use cache (reset mock to verify no new calls)
            client.get.reset_mock()
            client.post.reset_mock()
            tile2 = await match_activity_to_viator("Sunset Sailing Cruise", "Santorini")
            assert tile2 is not None
            assert tile2["id"] == tile1["id"]
            # No new API calls should have been made
            client.post.assert_not_called()


@pytest.mark.asyncio
class TestCircuitBreaker:
    async def test_circuit_opens_after_threshold_failures(self):
        """Circuit breaker should open after _CB_THRESHOLD consecutive failures."""
        import app.services.viator_provider as vp

        for _ in range(vp._CB_THRESHOLD):
            vp._record_viator_circuit_failure()

        assert vp._is_viator_circuit_open() is True

    async def test_circuit_closed_before_threshold(self):
        """Circuit should remain closed below threshold."""
        import app.services.viator_provider as vp

        for _ in range(vp._CB_THRESHOLD - 1):
            vp._record_viator_circuit_failure()

        assert vp._is_viator_circuit_open() is False

    async def test_success_resets_circuit(self):
        """Recording a success should reset the failure counter."""
        import app.services.viator_provider as vp

        for _ in range(vp._CB_THRESHOLD - 1):
            vp._record_viator_circuit_failure()

        vp._record_viator_circuit_success()
        assert vp._viator_circuit_failures == 0
        assert vp._is_viator_circuit_open() is False
