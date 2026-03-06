"""
Tests for activity_browser.py — browse_activities() integration.

Covers:
1. Happy path — returns correctly structured activity tiles
2. Empty result from Google Places — returns empty list without error
3. Google Places raises an exception — handled gracefully (returns empty)
4. Cache key deduplication — second call with same args hits L1 cache
5. Invalid/unknown categories — falls back to default categories
6. No API key configured — returns empty list without error

Run with: pytest tests/test_activity_browser.py -v

Patch strategy: browse_activities() imports _call_places_api_async and
_geocode_destination_async lazily (inside the function body) from
app.tile_service.google_places_provider, so we must patch at the source
module, not at app.services.activity_browser.
settings is imported at module level from app.config, so we patch
app.services.activity_browser.settings directly.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Patch targets — match where the names are looked up at call time
_PLACES_API = "app.tile_service.google_places_provider._call_places_api_async"
_GEOCODE_API = "app.tile_service.google_places_provider._geocode_destination_async"
_SETTINGS = "app.services.activity_browser.settings"
_BROWSE_L2_GET = "app.services.activity_browser._get_cached_browse"
_BROWSE_L2_SET = "app.services.activity_browser._set_cached_browse"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_place(
    place_id: str = "gp_abc123",
    name: str = "Cool Museum",
    lat: float = -8.67,
    lng: float = 115.21,
    address: str = "Jl. Raya, Ubud, Bali",
    primary_type: str = "museum",
    rating: float = 4.5,
    review_count: int = 200,
    price_level: str = "PRICE_LEVEL_MODERATE",
    editorial: str = "A wonderful place.",
    maps_uri: str = "https://maps.google.com/?q=place_id:gp_abc123",
    photo_name: str = "places/gp_abc123/photos/photo1",
) -> dict:
    """Build a minimal Google Places API place dict."""
    return {
        "id": place_id,
        "displayName": {"text": name},
        "location": {"latitude": lat, "longitude": lng},
        "formattedAddress": address,
        "primaryType": primary_type,
        "rating": rating,
        "userRatingCount": review_count,
        "priceLevel": price_level,
        "editorialSummary": {"text": editorial},
        "googleMapsUri": maps_uri,
        "photos": [{"name": photo_name}],
    }


def _make_settings(api_key: str | None = "fake-key") -> MagicMock:
    """Build a mock settings object with google_maps_api_key set."""
    mock = MagicMock()
    mock.google_maps_api_key = api_key
    return mock


def _clear_browse_cache() -> None:
    """Clear the activity_browser L1 cache between tests."""
    from app.services.activity_browser import _browse_cache

    _browse_cache.clear()


@pytest.fixture(autouse=True)
def _stub_browse_l2_cache():
    """Default all tests to no-op L2 cache to keep unit tests deterministic."""
    with (
        patch(_BROWSE_L2_GET, new_callable=AsyncMock) as mock_l2_get,
        patch(_BROWSE_L2_SET, new_callable=AsyncMock) as mock_l2_set,
    ):
        mock_l2_get.return_value = None
        yield mock_l2_get, mock_l2_set


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestBrowseActivitiesHappyPath:
    """browse_activities() returns correctly structured tiles when Google Places responds."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        _clear_browse_cache()
        yield
        _clear_browse_cache()

    @pytest.mark.asyncio
    async def test_returns_tiles_with_required_fields(self):
        with (
            patch(_PLACES_API, new_callable=AsyncMock) as mock_places,
            patch(_GEOCODE_API, new_callable=AsyncMock) as mock_geocode,
            patch(_SETTINGS, _make_settings("fake-key")),
        ):
            mock_geocode.return_value = (-8.67, 115.21)
            mock_places.return_value = [_make_place()]

            from app.services.activity_browser import browse_activities

            results = await browse_activities(
                destination="Bali",
                center=None,
                categories=["cultural"],
                date="2026-06-15",
            )

        assert isinstance(results, list)
        assert len(results) >= 1

        tile = results[0]
        # Required identity fields
        assert "id" in tile
        assert tile["id"].startswith("browse_")
        assert tile["type"] == "activity"
        assert tile["source"] == "google_places"
        assert tile["provider"] == "google_places"

        # Content fields
        assert tile["title"] == "Cool Museum"
        assert tile["google_place_id"] == "gp_abc123"
        assert tile["deeplink"] == "https://maps.google.com/?q=place_id:gp_abc123"
        # rating/review_count are Pro-tier fields not in our field mask — always None
        assert tile["rating"] is None
        assert tile["review_count"] is None
        assert tile["location_label"] == "Jl. Raya, Ubud, Bali"
        assert tile["category"] == "cultural"

        # Geo
        assert tile["geo"] is not None
        assert tile["geo"]["lat"] == pytest.approx(-8.67)
        assert tile["geo"]["lng"] == pytest.approx(115.21)

        # Tags
        assert isinstance(tile["tags"], list)
        assert "museum" in tile["tags"]

    @pytest.mark.asyncio
    async def test_deduplicates_by_place_id(self):
        """Same place returned by multiple type searches is included only once."""
        with (
            patch(_PLACES_API, new_callable=AsyncMock) as mock_places,
            patch(_GEOCODE_API, new_callable=AsyncMock) as mock_geocode,
            patch(_SETTINGS, _make_settings("fake-key")),
        ):
            mock_geocode.return_value = (-8.67, 115.21)
            mock_places.return_value = [_make_place(place_id="shared_id")]

            from app.services.activity_browser import browse_activities

            results = await browse_activities(
                destination="Bali",
                center=None,
                categories=["cultural"],
                date="2026-06-15",
            )

        ids = [t["place_id"] for t in results]
        assert ids.count("shared_id") == 1

    @pytest.mark.asyncio
    async def test_deduplicates_shared_places_types_via_single_broad_query(self):
        """Shared Places types across categories use a single broad query, not per-type calls."""
        with (
            patch(_PLACES_API, new_callable=AsyncMock) as mock_places,
            patch(_GEOCODE_API, new_callable=AsyncMock) as mock_geocode,
            patch(_SETTINGS, _make_settings("fake-key")),
        ):
            mock_geocode.return_value = (-8.67, 115.21)
            mock_places.return_value = [_make_place(primary_type="spa")]

            from app.services.activity_browser import browse_activities

            await browse_activities(
                destination="Bali",
                center=None,
                categories=["spa", "wellness"],
                date="2026-06-20",
            )

        # Current implementation uses a single broad text search instead of per-type calls.
        assert mock_places.await_count == 1
        call_kwargs = mock_places.await_args_list[0].kwargs
        assert call_kwargs["included_type"] is None
        assert "spa" in call_kwargs["query"]
        assert "wellness" in call_kwargs["query"]

    @pytest.mark.asyncio
    async def test_shared_type_results_keep_all_matching_categories(self):
        """A place whose primaryType maps to multiple categories appears under each."""
        with (
            patch(_PLACES_API, new_callable=AsyncMock) as mock_places,
            patch(_GEOCODE_API, new_callable=AsyncMock) as mock_geocode,
            patch(_SETTINGS, _make_settings("fake-key")),
        ):
            mock_geocode.return_value = (-8.67, 115.21)
            # primaryType="spa" maps to both "spa" and "wellness" in type_to_categories
            mock_places.return_value = [_make_place(place_id="shared_spa", primary_type="spa")]

            from app.services.activity_browser import browse_activities

            results = await browse_activities(
                destination="Bali",
                center=None,
                categories=["spa", "wellness"],
                date="2026-06-20",
            )

        shared = [tile for tile in results if tile.get("place_id") == "shared_spa"]
        categories = {tile.get("category") for tile in shared}
        assert categories == {"spa", "wellness"}
        assert len(shared) == 2

    @pytest.mark.asyncio
    async def test_uses_provided_center_skips_geocode(self):
        """When center is provided, geocode should not be called."""
        with (
            patch(_PLACES_API, new_callable=AsyncMock) as mock_places,
            patch(_GEOCODE_API, new_callable=AsyncMock) as mock_geocode,
            patch(_SETTINGS, _make_settings("fake-key")),
        ):
            mock_places.return_value = [_make_place()]

            from app.services.activity_browser import browse_activities

            results = await browse_activities(
                destination="Bali",
                center=(-8.67, 115.21),
                categories=["cultural"],
                date="2026-06-15",
            )

            mock_geocode.assert_not_called()

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_price_level_mapped_correctly(self):
        """Default moderate price_level=2 and price_estimate=35 (GP priceLevel not in field mask)."""
        with (
            patch(_PLACES_API, new_callable=AsyncMock) as mock_places,
            patch(_GEOCODE_API, new_callable=AsyncMock) as mock_geocode,
            patch(_SETTINGS, _make_settings("fake-key")),
        ):
            mock_geocode.return_value = None
            mock_places.return_value = [_make_place(price_level="PRICE_LEVEL_MODERATE")]

            from app.services.activity_browser import browse_activities

            results = await browse_activities(
                destination="Bali",
                center=(-8.0, 115.0),
                categories=["cultural"],
                date="2026-07-01",
            )

        assert len(results) >= 1
        assert results[0]["price_estimate"] == 35
        assert results[0]["price_level"] == 2

    @pytest.mark.asyncio
    async def test_l1_cache_hit_on_second_call(self):
        """Second call with identical args returns cached result without re-querying Places."""
        with (
            patch(_PLACES_API, new_callable=AsyncMock) as mock_places,
            patch(_GEOCODE_API, new_callable=AsyncMock) as mock_geocode,
            patch(_SETTINGS, _make_settings("fake-key")),
        ):
            mock_geocode.return_value = (-8.67, 115.21)
            mock_places.return_value = [_make_place()]

            from app.services.activity_browser import browse_activities

            result1 = await browse_activities(
                destination="Bali",
                center=None,
                categories=["cultural"],
                date="2026-08-10",
            )
            call_count_after_first = mock_places.await_count

            result2 = await browse_activities(
                destination="Bali",
                center=None,
                categories=["cultural"],
                date="2026-08-10",
            )

            # Places API should not have been called again (cache hit)
            assert mock_places.await_count == call_count_after_first

        assert result1 == result2


# ---------------------------------------------------------------------------
# Empty result from Google
# ---------------------------------------------------------------------------


class TestBrowseActivitiesEmptyResult:
    """browse_activities() returns empty list when Google Places returns no places."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        _clear_browse_cache()
        yield
        _clear_browse_cache()

    @pytest.mark.asyncio
    async def test_empty_places_returns_empty_list(self):
        with (
            patch(_PLACES_API, new_callable=AsyncMock) as mock_places,
            patch(_GEOCODE_API, new_callable=AsyncMock) as mock_geocode,
            patch(_SETTINGS, _make_settings("fake-key")),
        ):
            mock_geocode.return_value = (-8.67, 115.21)
            mock_places.return_value = []  # Empty response from Places API

            from app.services.activity_browser import browse_activities

            results = await browse_activities(
                destination="Nowhere",
                center=None,
                categories=["cultural"],
                date="2026-01-01",
            )

        assert results == []

    @pytest.mark.asyncio
    async def test_no_api_key_returns_empty_list(self):
        """When google_maps_api_key is not set, returns empty without calling Places."""
        with (
            patch(_PLACES_API, new_callable=AsyncMock) as mock_places,
            patch(_GEOCODE_API, new_callable=AsyncMock),
            patch(_SETTINGS, _make_settings(api_key=None)),
        ):
            from app.services.activity_browser import browse_activities

            results = await browse_activities(
                destination="Bali",
                center=(-8.0, 115.0),
                categories=["cultural"],
                date="2026-02-01",
            )

            assert results == []
            mock_places.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_categories_fall_back_to_defaults(self):
        """Entirely unknown categories fall back to ['cultural', 'food', 'nature']."""
        with (
            patch(_PLACES_API, new_callable=AsyncMock) as mock_places,
            patch(_GEOCODE_API, new_callable=AsyncMock) as mock_geocode,
            patch(_SETTINGS, _make_settings("fake-key")),
        ):
            mock_geocode.return_value = (-8.67, 115.21)
            mock_places.return_value = []

            from app.services.activity_browser import browse_activities

            results = await browse_activities(
                destination="Bali",
                center=None,
                categories=["nonexistent_category_xyz"],
                date="2026-03-01",
            )

            # Should not raise; Places was called (for default fallback categories)
            assert isinstance(results, list)
            assert mock_places.await_count > 0


# ---------------------------------------------------------------------------
# Exception handling
# ---------------------------------------------------------------------------


class TestBrowseActivitiesExceptionHandling:
    """browse_activities() handles Google Places errors gracefully."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        _clear_browse_cache()
        yield
        _clear_browse_cache()

    @pytest.mark.asyncio
    async def test_places_api_exception_returns_empty_not_raises(self):
        """When Places fails, browse returns empty and does not cache the failure."""
        with (
            patch(_PLACES_API, new_callable=AsyncMock) as mock_places,
            patch(_GEOCODE_API, new_callable=AsyncMock) as mock_geocode,
            patch(_BROWSE_L2_SET, new_callable=AsyncMock) as mock_l2_set,
            patch(_SETTINGS, _make_settings("fake-key")),
        ):
            mock_geocode.return_value = (-8.67, 115.21)
            mock_places.side_effect = Exception("Network timeout")

            from app.services.activity_browser import browse_activities

            # Must not raise — broad search catches the exception.
            results_1 = await browse_activities(
                destination="Bali",
                center=None,
                categories=["cultural"],
                date="2026-04-01",
            )

            results_2 = await browse_activities(
                destination="Bali",
                center=None,
                categories=["cultural"],
                date="2026-04-01",
            )

        assert isinstance(results_1, list)
        assert isinstance(results_2, list)
        assert results_1 == []
        assert results_2 == []
        # Single broad query per call; no failure-cache means both calls retry.
        assert mock_places.await_count == 2
        mock_l2_set.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_then_retry_succeeds(self):
        """First browse call fails (broad search error), second call succeeds."""
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Quota exceeded")
            return [_make_place(place_id=f"gp_{call_count}")]

        with (
            patch(_PLACES_API, new_callable=AsyncMock) as mock_places,
            patch(_GEOCODE_API, new_callable=AsyncMock) as mock_geocode,
            patch(_SETTINGS, _make_settings("fake-key")),
        ):
            mock_geocode.return_value = (-8.67, 115.21)
            mock_places.side_effect = _side_effect

            from app.services.activity_browser import browse_activities

            # First call — broad search raises, returns empty
            results_1 = await browse_activities(
                destination="Bali",
                center=None,
                categories=["cultural"],
                date="2026-05-01",
            )
            assert results_1 == []

            # Second call — broad search succeeds, returns results
            results_2 = await browse_activities(
                destination="Bali",
                center=None,
                categories=["cultural"],
                date="2026-05-01",
            )

        assert isinstance(results_2, list)
        assert len(results_2) >= 1


class TestBrowseActivitiesPersistentCacheAndSingleflight:
    """Verify L2 browse caching + in-flight singleflight dedupe behavior."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        _clear_browse_cache()
        yield
        _clear_browse_cache()

    @pytest.mark.asyncio
    async def test_l2_cache_hit_skips_places_calls(self):
        l2_tiles = [
            {
                "id": "browse_cached",
                "type": "activity",
                "title": "Cached Place",
                "place_id": "cached_1",
                "provider": "google_places",
                "source": "google_places",
            }
        ]
        with (
            patch(_PLACES_API, new_callable=AsyncMock) as mock_places,
            patch(_GEOCODE_API, new_callable=AsyncMock) as mock_geocode,
            patch(_BROWSE_L2_GET, new_callable=AsyncMock) as mock_l2_get,
            patch(_BROWSE_L2_SET, new_callable=AsyncMock),
            patch(_SETTINGS, _make_settings("fake-key")),
        ):
            mock_geocode.return_value = (-8.67, 115.21)
            mock_l2_get.return_value = l2_tiles

            from app.services.activity_browser import browse_activities

            results = await browse_activities(
                destination="Bali",
                center=None,
                categories=["cultural"],
                date="2026-09-10",
            )

        assert results == l2_tiles
        mock_places.assert_not_called()
        assert mock_l2_get.await_count == 1

    @pytest.mark.asyncio
    async def test_singleflight_dedupes_identical_concurrent_requests(self):
        async def _slow_places(*args, **kwargs):
            await asyncio.sleep(0.05)
            return [_make_place(place_id="gp_cultural", primary_type="museum")]

        with (
            patch(_PLACES_API, new_callable=AsyncMock) as mock_places,
            patch(_GEOCODE_API, new_callable=AsyncMock) as mock_geocode,
            patch(_BROWSE_L2_GET, new_callable=AsyncMock) as mock_l2_get,
            patch(_BROWSE_L2_SET, new_callable=AsyncMock) as mock_l2_set,
            patch(_SETTINGS, _make_settings("fake-key")),
        ):
            mock_geocode.return_value = (-8.67, 115.21)
            mock_places.side_effect = _slow_places
            mock_l2_get.return_value = None

            from app.services.activity_browser import browse_activities

            req1 = browse_activities(
                destination="Bali",
                center=None,
                categories=["cultural"],
                date="2026-10-10",
            )
            req2 = browse_activities(
                destination="Bali",
                center=None,
                categories=["cultural"],
                date="2026-10-10",
            )
            result1, result2 = await asyncio.gather(req1, req2)

        assert result1 == result2
        # Single broad query; singleflight means only 1 API call for both concurrent requests.
        assert mock_places.await_count == 1
        assert mock_l2_set.await_count == 1

    @pytest.mark.asyncio
    async def test_geocode_failure_still_searches_without_geo(self):
        """Geocode returning None does not block the Places search (geo becomes None)."""
        with (
            patch(_PLACES_API, new_callable=AsyncMock) as mock_places,
            patch(_GEOCODE_API, new_callable=AsyncMock) as mock_geocode,
            patch(_SETTINGS, _make_settings("fake-key")),
        ):
            mock_geocode.return_value = None  # geocode lookup failed
            mock_places.return_value = [_make_place()]

            from app.services.activity_browser import browse_activities

            results = await browse_activities(
                destination="Bali",
                center=None,
                categories=["cultural"],
                date="2026-06-01",
            )

        assert isinstance(results, list)
        assert len(results) >= 1
