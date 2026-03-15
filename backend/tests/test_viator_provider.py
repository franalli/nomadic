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
def _reset_viator_state(monkeypatch: pytest.MonkeyPatch):
    """Reset module-level caches and circuit breaker between tests."""
    import app.services.viator_provider as vp

    vp._viator_cb._failures = 0
    vp._viator_cb._open_until = 0.0
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

SPECIALIST_MATCH_PRODUCT = {
    "productCode": "98765P2",
    "title": "Tulamben Shore Dive at USAT Liberty Shipwreck",
    "pricing": {
        "summary": {"fromPrice": 74.0},
        "currency": "USD",
    },
    "images": [
        {
            "isCover": True,
            "variants": [{"width": 720, "height": 480, "url": "https://example.com/usat.jpg"}],
        }
    ],
    "reviews": {"combinedAverageRating": 4.8, "totalReviews": 120},
    "duration": {"fixedDurationInMinutes": 240},
    "productUrl": "https://www.viator.com/tours/test/98765P2",
}

LOW_QUALITY_MATCH_PRODUCT = {
    "productCode": "55555P9",
    "title": "Bali Scuba Diving Experience for Certified Divers",
    "pricing": {
        "summary": {"fromPrice": 68.0},
        "currency": "USD",
    },
    "images": [
        {
            "isCover": True,
            "variants": [{"width": 720, "height": 480, "url": "https://example.com/bali.jpg"}],
        }
    ],
    "reviews": {"combinedAverageRating": 4.3, "totalReviews": 87},
    "duration": {"fixedDurationInMinutes": 240},
    "productUrl": "https://www.viator.com/tours/test/55555P9",
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
        import time

        import app.services.viator_provider as vp

        vp._viator_cb._failures = 10
        vp._viator_cb._open_until = time.monotonic() + 9999
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
        import time

        import app.services.viator_provider as vp

        vp._viator_cb._failures = 10
        vp._viator_cb._open_until = time.monotonic() + 9999
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

    async def test_cleaned_specialist_title_variants_share_positive_cache_entry(self):
        """Equivalent cleaned specialist titles should reuse the same cached Viator match."""
        import app.services.viator_provider as vp

        search_mock = AsyncMock(return_value=([SPECIALIST_MATCH_PRODUCT], True))
        cache_key = "viator_match:bali:uncategorized:usat liberty shipwreck shore dive"

        with (
            patch(
                "app.services.viator_provider.resolve_destination_id",
                new=AsyncMock(return_value=(99, True)),
            ),
            patch(
                "app.services.viator_provider._search_query_variants",
                return_value=["USAT Liberty Shipwreck Shore Dive"],
            ),
            patch(
                "app.services.viator_provider._search_freetext_with_status",
                new=search_mock,
            ),
        ):
            variant_tile = await match_activity_to_viator(
                "Tulamben: USAT Liberty Shipwreck Shore Dive (Session 2)",
                "Bali",
            )
            base_tile = await match_activity_to_viator("USAT Liberty Shipwreck Shore Dive", "Bali")

        assert variant_tile is not None
        assert base_tile is not None
        assert variant_tile["id"] == base_tile["id"] == "viator_98765P2"
        assert search_mock.await_count == 1
        assert vp._match_cache.get(cache_key) == variant_tile

    async def test_specialist_title_falls_back_to_simplified_query(self):
        """Specialist-generated diving titles should retry with a cleaner site-based query."""
        seen_queries: list[str] = []

        async def _fake_search(
            query: str,
            dest_id: int | None,
            currency: str = "USD",
            count: int = 3,
        ) -> tuple[list[dict], bool]:
            seen_queries.append(query)
            if "Session" in query or "Shore Dive" in query:
                return [], True
            if "USAT Liberty Shipwreck" in query:
                return [SPECIALIST_MATCH_PRODUCT], True
            return [], True

        with (
            patch(
                "app.services.viator_provider.resolve_destination_id",
                new=AsyncMock(return_value=(99, True)),
            ),
            patch(
                "app.services.viator_provider._search_freetext_with_status",
                new=AsyncMock(side_effect=_fake_search),
            ),
        ):
            tile = await match_activity_to_viator(
                "Tulamben: USAT Liberty Shipwreck Shore Dive (Session 2)",
                "Bali",
            )

        assert tile is not None
        assert tile["id"] == "viator_98765P2"
        assert any(
            "USAT Liberty Shipwreck" in query and "Session" not in query for query in seen_queries
        )

    async def test_non_empty_low_quality_first_query_does_not_block_better_variant(self):
        """Later site-specific variants should still win over an earlier weak match set."""
        seen_queries: list[str] = []

        async def _fake_search(
            query: str,
            dest_id: int | None,
            currency: str = "USD",
            count: int = 3,
        ) -> tuple[list[dict], bool]:
            seen_queries.append(query)
            if "Shore Dive" in query:
                return [LOW_QUALITY_MATCH_PRODUCT], True
            if "USAT Liberty Shipwreck" in query:
                return [SPECIALIST_MATCH_PRODUCT], True
            return [], True

        with (
            patch(
                "app.services.viator_provider.resolve_destination_id",
                new=AsyncMock(return_value=(99, True)),
            ),
            patch(
                "app.services.viator_provider._search_freetext_with_status",
                new=AsyncMock(side_effect=_fake_search),
            ),
        ):
            tile = await match_activity_to_viator(
                "Tulamben: USAT Liberty Shipwreck Shore Dive (Session 2)",
                "Bali",
            )

        assert tile is not None
        assert tile["id"] == "viator_98765P2"
        assert len(seen_queries) >= 2
        assert any("Shore Dive" in query for query in seen_queries)
        assert any(
            "USAT Liberty Shipwreck" in query and "Shore Dive" not in query
            for query in seen_queries
        )

    async def test_transient_empty_searches_do_not_negative_cache(self):
        """Transient empty responses should not poison the long-lived no-match cache."""
        import app.services.viator_provider as vp

        cache_key = "viator_match:bali:uncategorized:usat liberty shipwreck shore dive"

        with (
            patch(
                "app.services.viator_provider.resolve_destination_id",
                new=AsyncMock(return_value=(99, True)),
            ),
            patch(
                "app.services.viator_provider._search_freetext_with_status",
                new=AsyncMock(return_value=([], False)),
            ),
        ):
            tile = await match_activity_to_viator("USAT Liberty Shipwreck Shore Dive", "Bali")

        assert tile is None
        assert vp._match_cache.get(cache_key) is None

    async def test_definitive_empty_searches_still_negative_cache(self):
        """Confirmed empty provider responses should still cache the no-match sentinel."""
        import app.services.viator_provider as vp

        cache_key = "viator_match:bali:uncategorized:usat liberty shipwreck shore dive"

        with (
            patch(
                "app.services.viator_provider.resolve_destination_id",
                new=AsyncMock(return_value=(99, True)),
            ),
            patch(
                "app.services.viator_provider._search_freetext_with_status",
                new=AsyncMock(return_value=([], True)),
            ),
        ):
            tile = await match_activity_to_viator("USAT Liberty Shipwreck Shore Dive", "Bali")

        assert tile is None
        assert vp._match_cache.get(cache_key) is vp._NO_MATCH

    async def test_cleaned_specialist_title_variants_share_negative_cache_entry(self):
        """Equivalent cleaned titles should reuse the same definitive no-match cache entry."""
        import app.services.viator_provider as vp

        search_mock = AsyncMock(return_value=([], True))
        cache_key = "viator_match:bali:uncategorized:usat liberty shipwreck shore dive"

        with (
            patch(
                "app.services.viator_provider.resolve_destination_id",
                new=AsyncMock(return_value=(99, True)),
            ),
            patch(
                "app.services.viator_provider._search_query_variants",
                return_value=["USAT Liberty Shipwreck Shore Dive"],
            ),
            patch(
                "app.services.viator_provider._search_freetext_with_status",
                new=search_mock,
            ),
        ):
            variant_tile = await match_activity_to_viator(
                "Tulamben: USAT Liberty Shipwreck Shore Dive (Session 2)",
                "Bali",
            )
            base_tile = await match_activity_to_viator("USAT Liberty Shipwreck Shore Dive", "Bali")

        assert variant_tile is None
        assert base_tile is None
        assert search_mock.await_count == 1
        assert vp._match_cache.get(cache_key) is vp._NO_MATCH

    async def test_meaningful_parenthetical_variants_keep_distinct_negative_cache_entries(self):
        """Meaningful parenthetical variants should not reuse a prior no-match cache sentinel."""
        import app.services.viator_provider as vp

        sunrise_cache_key = "viator_match:santorini:uncategorized:sunset sailing cruise (sunrise)"
        sunset_cache_key = "viator_match:santorini:uncategorized:sunset sailing cruise (sunset)"
        search_mock = AsyncMock(side_effect=[([], True), ([SAMPLE_PRODUCT], True)])

        with (
            patch(
                "app.services.viator_provider.resolve_destination_id",
                new=AsyncMock(return_value=(99, True)),
            ),
            patch(
                "app.services.viator_provider._search_query_variants",
                return_value=["Sunset Sailing Cruise"],
            ),
            patch(
                "app.services.viator_provider._search_freetext_with_status",
                new=search_mock,
            ),
        ):
            sunrise_tile = await match_activity_to_viator(
                "Sunset Sailing Cruise (Sunrise)",
                "Santorini",
            )
            sunset_tile = await match_activity_to_viator(
                "Sunset Sailing Cruise (Sunset)",
                "Santorini",
            )

        assert sunrise_tile is None
        assert sunset_tile is not None
        assert sunset_tile["id"] == "viator_12345P1"
        assert search_mock.await_count == 2
        assert vp._match_cache.get(sunrise_cache_key) is vp._NO_MATCH
        assert vp._match_cache.get(sunset_cache_key) == sunset_tile

    async def test_cached_positive_match_does_not_bleed_across_categories(self):
        """Category-scoped cache should not reuse a positive match across conflicting categories."""
        import app.services.viator_provider as vp

        diving_cache_key = "viator_match:bali:diving:bali scuba diving experience"
        snorkeling_cache_key = "viator_match:bali:snorkeling:bali scuba diving experience"
        search_mock = AsyncMock(return_value=([LOW_QUALITY_MATCH_PRODUCT], True))

        with (
            patch(
                "app.services.viator_provider.resolve_destination_id",
                new=AsyncMock(return_value=(99, True)),
            ),
            patch(
                "app.services.viator_provider._search_query_variants",
                return_value=["Bali Scuba Diving Experience"],
            ),
            patch(
                "app.services.viator_provider._search_freetext_with_status",
                new=search_mock,
            ),
        ):
            diving_tile = await match_activity_to_viator(
                "Bali Scuba Diving Experience",
                "Bali",
                category="diving",
            )
            snorkeling_tile = await match_activity_to_viator(
                "Bali Scuba Diving Experience",
                "Bali",
                category="snorkeling",
            )

        assert diving_tile is not None
        assert diving_tile["id"] == "viator_55555P9"
        assert snorkeling_tile is None
        assert search_mock.await_count == 2
        assert vp._match_cache.get(diving_cache_key) == diving_tile
        assert vp._match_cache.get(snorkeling_cache_key) is vp._NO_MATCH

    async def test_cached_negative_match_does_not_bleed_across_categories(self):
        """Category-scoped cache should not reuse a no-match sentinel for another category."""
        import app.services.viator_provider as vp

        snorkeling_cache_key = "viator_match:bali:snorkeling:bali scuba diving experience"
        diving_cache_key = "viator_match:bali:diving:bali scuba diving experience"
        search_mock = AsyncMock(return_value=([LOW_QUALITY_MATCH_PRODUCT], True))

        with (
            patch(
                "app.services.viator_provider.resolve_destination_id",
                new=AsyncMock(return_value=(99, True)),
            ),
            patch(
                "app.services.viator_provider._search_query_variants",
                return_value=["Bali Scuba Diving Experience"],
            ),
            patch(
                "app.services.viator_provider._search_freetext_with_status",
                new=search_mock,
            ),
        ):
            snorkeling_tile = await match_activity_to_viator(
                "Bali Scuba Diving Experience",
                "Bali",
                category="snorkeling",
            )
            diving_tile = await match_activity_to_viator(
                "Bali Scuba Diving Experience",
                "Bali",
                category="diving",
            )

        assert snorkeling_tile is None
        assert diving_tile is not None
        assert diving_tile["id"] == "viator_55555P9"
        assert search_mock.await_count == 2
        assert vp._match_cache.get(snorkeling_cache_key) is vp._NO_MATCH
        assert vp._match_cache.get(diving_cache_key) == diving_tile

    async def test_transient_destination_resolution_does_not_negative_cache(self):
        """Transient destination taxonomy failures should not poison the match cache."""
        import app.services.viator_provider as vp

        cache_key = "viator_match:bali:uncategorized:usat liberty shipwreck shore dive"

        with (
            patch(
                "app.services.viator_provider.resolve_destination_id",
                new=AsyncMock(return_value=(None, False)),
            ),
            patch(
                "app.services.viator_provider._search_freetext_with_status",
                new=AsyncMock(return_value=([], True)),
            ),
        ):
            tile = await match_activity_to_viator("USAT Liberty Shipwreck Shore Dive", "Bali")

        assert tile is None
        assert vp._match_cache.get(cache_key) is None

    async def test_conflicting_best_match_falls_back_to_non_conflicting_product(self):
        """Cross-category matches should be rejected in favor of a clean fallback product."""
        conflicting = {
            "productCode": "200",
            "title": "Blue Lagoon Dive Snorkeling Tour",
            "duration": {"fixedDurationInMinutes": 180},
        }
        non_conflicting = {
            "productCode": "201",
            "title": "Blue Lagoon Scuba Diving Experience",
            "duration": {"fixedDurationInMinutes": 180},
        }

        with (
            patch(
                "app.services.viator_provider.resolve_destination_id",
                new=AsyncMock(return_value=(99, True)),
            ),
            patch(
                "app.services.viator_provider._search_query_variants",
                return_value=["Blue Lagoon Dive"],
            ),
            patch(
                "app.services.viator_provider._search_freetext_with_status",
                new=AsyncMock(return_value=([conflicting, non_conflicting], True)),
            ),
            patch(
                "app.services.viator_provider._best_scored_product",
                side_effect=[
                    (conflicting, 95, 2),
                    (non_conflicting, 82, 1),
                ],
            ),
        ):
            tile = await match_activity_to_viator(
                "Blue Lagoon Dive",
                "Bali",
                category="diving",
            )

        assert tile is not None
        assert tile["id"] == "viator_201"
        assert tile["meta"]["viator_product_code"] == "201"


@pytest.mark.asyncio
class TestCircuitBreaker:
    async def test_circuit_opens_after_threshold_failures(self):
        """Circuit breaker should open after failure_threshold consecutive failures."""
        import app.services.viator_provider as vp

        cb = vp._viator_cb
        for _ in range(cb.failure_threshold):
            cb.record_failure()

        assert cb.is_open() is True

    async def test_circuit_closed_before_threshold(self):
        """Circuit should remain closed below threshold."""
        import app.services.viator_provider as vp

        cb = vp._viator_cb
        for _ in range(cb.failure_threshold - 1):
            cb.record_failure()

        assert cb.is_open() is False

    async def test_success_resets_circuit(self):
        """Recording a success should reset the failure counter."""
        import app.services.viator_provider as vp

        cb = vp._viator_cb
        for _ in range(cb.failure_threshold - 1):
            cb.record_failure()

        cb.record_success()
        assert cb._failures == 0
        assert cb.is_open() is False
