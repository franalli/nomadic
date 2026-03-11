"""Tests for the GetYourGuide partner provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.gyg_provider import (
    _NO_MATCH,
    gyg_tour_to_tile,
    match_activity_to_gyg,
    search_gyg_for_destination,
)


@pytest.fixture(autouse=True)
def _reset_gyg_state():
    """Reset module-level caches and circuit breaker between tests."""
    import app.services.gyg_provider as gyg

    gyg._gyg_cb._failures = 0
    gyg._gyg_cb._open_until = 0.0
    gyg._match_cache._cache.clear()
    gyg._browse_gyg_cache._cache.clear()
    yield


SAMPLE_TOUR = {
    "tour_id": "12345",
    "title": "Sunset Sailing Cruise",
    "price": {
        "values": {"amount": 89.99},
        "description": "Individual ticket",
    },
    "pictures": [{"ssl_url": "https://example.com/image-{format_id}.jpg"}],
    "overall_rating": 4.7,
    "number_of_ratings": 234,
    "url": "https://www.getyourguide.com/tour/12345",
    "coordinates": {"lat": 36.39, "long": 25.46},
    "durations": [{"duration": 3, "unit": "hour"}],
}

MULTI_DAY_TOUR = {
    "tour_id": "99999",
    "title": "Santorini Multi-Day Pass",
    "durations": [{"duration": 2, "unit": "day"}],
}


class TestGygTourToTile:
    def test_basic_conversion(self):
        tile = gyg_tour_to_tile(SAMPLE_TOUR, "Santorini")

        assert tile["id"] == "gyg_12345"
        assert tile["partner"] == "gyg"
        assert tile["provider"] == "gyg"
        assert tile["price_estimate"] == 89.99
        assert tile["rating"] == 4.7
        assert tile["review_count"] == 234
        assert tile["image_url"] == "https://example.com/image-31.jpg"
        assert tile["deeplink"] == "https://www.getyourguide.com/tour/12345"
        assert tile["geo"] == {"lat": 36.39, "lng": 25.46}
        assert tile["meta"]["duration_hours"] == 3.0
        assert tile["meta"]["gyg_tour_id"] == "12345"

    def test_missing_optional_fields(self):
        tile = gyg_tour_to_tile({"tour_id": "MIN1", "title": "Basic Tour"}, "Paris")

        assert tile["id"] == "gyg_MIN1"
        assert "price_estimate" not in tile
        assert "rating" not in tile
        assert "image_url" not in tile
        assert tile["meta"]["gyg_tour_id"] == "MIN1"


@pytest.mark.asyncio
class TestMatchActivityToGyg:
    async def test_match_returns_tile_and_uses_cache(self):
        with patch(
            "app.services.gyg_provider.search_tours",
            new=AsyncMock(return_value=[SAMPLE_TOUR]),
        ) as mock_search:
            tile1 = await match_activity_to_gyg("Sunset Sailing Cruise", "Santorini")
            tile2 = await match_activity_to_gyg("Sunset Sailing Cruise", "Santorini")

        assert tile1 is not None
        assert tile2 is not None
        assert tile1["id"] == "gyg_12345"
        assert tile2["id"] == tile1["id"]
        assert mock_search.await_count == 1

    async def test_no_match_negative_caches_empty_results(self):
        import app.services.gyg_provider as gyg

        cache_key = "gyg_match:santorini:unknown tour"

        with patch(
            "app.services.gyg_provider.search_tours",
            new=AsyncMock(return_value=[]),
        ) as mock_search:
            first = await match_activity_to_gyg("Unknown Tour", "Santorini")
            second = await match_activity_to_gyg("Unknown Tour", "Santorini")

        assert first is None
        assert second is None
        assert gyg._match_cache.get(cache_key) is _NO_MATCH
        assert mock_search.await_count == 1

    async def test_conflicting_best_match_falls_back_to_non_conflicting_tour(self):
        conflicting = {
            "tour_id": "200",
            "title": "Blue Lagoon Dive Snorkeling Tour",
            "durations": [{"duration": 3, "unit": "hour"}],
        }
        non_conflicting = {
            "tour_id": "201",
            "title": "Blue Lagoon Scuba Diving Experience",
            "durations": [{"duration": 3, "unit": "hour"}],
        }

        with (
            patch(
                "app.services.gyg_provider.search_tours",
                new=AsyncMock(return_value=[conflicting, non_conflicting]),
            ),
            patch(
                "app.services.gyg_provider.fuzz.token_sort_ratio",
                side_effect=[95, 80, 80],
            ),
        ):
            tile = await match_activity_to_gyg(
                "Blue Lagoon Dive",
                "Bali",
                category="diving",
            )

        assert tile is not None
        assert tile["id"] == "gyg_201"
        assert tile["meta"]["gyg_tour_id"] == "201"


@pytest.mark.asyncio
class TestSearchGygForDestination:
    async def test_filters_multi_day_tours_and_uses_cache(self):
        with patch(
            "app.services.gyg_provider.search_tours",
            new=AsyncMock(return_value=[SAMPLE_TOUR, MULTI_DAY_TOUR]),
        ) as mock_search:
            tiles1 = await search_gyg_for_destination("Santorini", count=5)
            tiles2 = await search_gyg_for_destination("Santorini", count=5)

        assert len(tiles1) == 1
        assert tiles2 == tiles1
        assert tiles1[0]["id"] == "gyg_12345"
        assert mock_search.await_count == 1
