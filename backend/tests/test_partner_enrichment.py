"""Tests for unified partner enrichment."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _partner_settings(monkeypatch: pytest.MonkeyPatch):
    """Reset provider flags per test."""
    import app.services.partner_enrichment as pe

    monkeypatch.setattr(pe.settings, "viator_enabled", False, raising=False)
    monkeypatch.setattr(pe.settings, "viator_api_key", "", raising=False)
    monkeypatch.setattr(pe.settings, "get_your_guide_enabled", False, raising=False)
    monkeypatch.setattr(pe.settings, "get_your_guide_api_key", "", raising=False)
    yield


def _enable_all_partners(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.partner_enrichment as pe

    monkeypatch.setattr(pe.settings, "viator_enabled", True, raising=False)
    monkeypatch.setattr(pe.settings, "viator_api_key", "viator-key", raising=False)
    monkeypatch.setattr(pe.settings, "get_your_guide_enabled", True, raising=False)
    monkeypatch.setattr(pe.settings, "get_your_guide_api_key", "gyg-key", raising=False)


VIATOR_TILE = {
    "partner": "viator",
    "provider": "viator",
    "partner_product_id": "V-1",
    "price_estimate": 120.0,
    "live_price": 120.0,
    "currency": "USD",
    "price_basis": "per_person",
    "rating": 4.8,
    "review_count": 80,
    "image_url": "https://example.com/viator.jpg",
    "deeplink": "https://viator.example/tour",
    "geo": {"lat": 1.0, "lng": 2.0},
    "meta": {"viator_product_code": "V-1", "duration_hours": 4.0, "category": "diving"},
}

GYG_TILE = {
    "partner": "gyg",
    "provider": "gyg",
    "partner_product_id": "G-1",
    "price_estimate": 99.0,
    "live_price": 99.0,
    "currency": "USD",
    "price_basis": "per_person",
    "rating": 4.9,
    "review_count": 120,
    "image_url": "https://example.com/gyg.jpg",
    "deeplink_url": "https://gyg.example/tour",
    "geo": {"lat": 3.0, "lng": 4.0},
    "meta": {"gyg_tour_id": "G-1", "duration_hours": 3.5, "category": "diving"},
}


@pytest.mark.asyncio
class TestMatchActivityToBestPartner:
    async def test_prefers_highest_rating_then_lower_price_then_viator(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from app.services.partner_enrichment import match_activity_to_best_partner

        _enable_all_partners(monkeypatch)

        with (
            patch(
                "app.services.viator_provider.match_activity_to_viator",
                new=AsyncMock(return_value=VIATOR_TILE),
            ),
            patch(
                "app.services.gyg_provider.match_activity_to_gyg",
                new=AsyncMock(return_value=GYG_TILE),
            ),
        ):
            winner = await match_activity_to_best_partner("Blue Hole Dive", "Bali")

        assert winner is not None
        assert winner["partner"] == "gyg"

        viator_tie = {**VIATOR_TILE, "rating": 4.9, "price_estimate": 99.0}
        gyg_tie = {**GYG_TILE, "rating": 4.9, "price_estimate": 99.0}

        with (
            patch(
                "app.services.viator_provider.match_activity_to_viator",
                new=AsyncMock(return_value=viator_tie),
            ),
            patch(
                "app.services.gyg_provider.match_activity_to_gyg",
                new=AsyncMock(return_value=gyg_tie),
            ),
        ):
            winner = await match_activity_to_best_partner("Blue Hole Dive", "Bali")

        assert winner is not None
        assert winner["partner"] == "viator"

    async def test_ignores_provider_exceptions(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from app.services.partner_enrichment import match_activity_to_best_partner

        _enable_all_partners(monkeypatch)

        with (
            patch(
                "app.services.viator_provider.match_activity_to_viator",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
            patch(
                "app.services.gyg_provider.match_activity_to_gyg",
                new=AsyncMock(return_value=GYG_TILE),
            ),
        ):
            winner = await match_activity_to_best_partner("Blue Hole Dive", "Bali")

        assert winner is not None
        assert winner["partner"] == "gyg"

    async def test_returns_none_when_all_partners_disabled(self):
        from app.services.partner_enrichment import match_activity_to_best_partner

        winner = await match_activity_to_best_partner("Blue Hole Dive", "Bali")

        assert winner is None


@pytest.mark.asyncio
class TestEnrichTilesWithPartners:
    async def test_updates_eligible_tiles_and_skips_existing_partner_tiles(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from app.services.partner_enrichment import enrich_tiles_with_partners

        _enable_all_partners(monkeypatch)

        tiles = [
            {
                "title": "Blue Hole Dive",
                "meta": {"specialist_type": "diving", "category": "snorkeling"},
            },
            {
                "title": "Already Viator",
                "provider": "viator",
                "meta": {},
            },
            {
                "title": "Already Tagged",
                "meta": {"gyg_tour_id": "existing"},
            },
            {
                "title": "No Match",
                "meta": {"category": "diving"},
            },
        ]

        # Isolate merge logic from the centroid geo-compat check (covered
        # separately below): with no source coords and centroid unresolved, the
        # synthetic GYG_TILE geo (3,4) must not be geo-rejected.
        with (
            patch(
                "app.services.partner_enrichment.match_activity_to_best_partner",
                new=AsyncMock(side_effect=[GYG_TILE, None]),
            ) as mock_match,
            patch(
                "app.tile_service.google_places_provider._geocode_destination_async",
                new=AsyncMock(return_value=None),
            ),
        ):
            await enrich_tiles_with_partners(tiles, "Bali")

        assert mock_match.await_count == 2
        first_call = mock_match.await_args_list[0]
        assert first_call.args == ("Blue Hole Dive", "Bali", "USD")
        assert first_call.kwargs["category"] == "diving"

        enriched = tiles[0]
        assert enriched["partner"] == "gyg"
        assert enriched["provider"] == "gyg"
        assert enriched["partner_product_id"] == "G-1"
        assert enriched["price_estimate"] == 99.0
        assert enriched["live_price"] == 99.0
        assert enriched["rating"] == 4.9
        assert enriched["review_count"] == 120
        assert enriched["image_url"] == "https://example.com/gyg.jpg"
        assert enriched["deeplink"] == "https://gyg.example/tour"
        assert enriched["deeplink_url"] == "https://gyg.example/tour"
        assert enriched["geo"] == {"lat": 3.0, "lng": 4.0}
        assert enriched["meta"]["gyg_tour_id"] == "G-1"
        assert enriched["meta"]["duration_hours"] == 3.5
        assert enriched["meta"]["category"] == "diving"

        assert tiles[1]["provider"] == "viator"
        assert tiles[2]["meta"]["gyg_tour_id"] == "existing"
        assert "partner" not in tiles[3]

    async def test_no_op_when_no_providers_enabled(self):
        from app.services.partner_enrichment import enrich_tiles_with_partners

        tiles = [{"title": "Blue Hole Dive", "meta": {"category": "diving"}}]

        with patch(
            "app.services.partner_enrichment.match_activity_to_best_partner",
            new=AsyncMock(),
        ) as mock_match:
            await enrich_tiles_with_partners(tiles, "Bali")

        mock_match.assert_not_awaited()
        assert "partner" not in tiles[0]

    async def test_skips_tiles_with_persisted_partner_product_id(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from app.services.partner_enrichment import enrich_tiles_with_partners

        _enable_all_partners(monkeypatch)

        tiles = [
            {
                "title": "Blue Hole Dive",
                "type": "activity",
                "partner_product_id": "V-1",
                "live_price": 120.0,
                "is_estimate_only": False,
                "deeplink": "https://www.viator.com/tours/Bali/blue-hole",
                "meta": {"category": "diving"},
            }
        ]

        with patch(
            "app.services.partner_enrichment.match_activity_to_best_partner",
            new=AsyncMock(return_value=VIATOR_TILE),
        ) as mock_match:
            await enrich_tiles_with_partners(tiles, "Bali")

        mock_match.assert_not_awaited()
        assert tiles[0]["partner_product_id"] == "V-1"
        assert tiles[0]["live_price"] == 120.0

    async def test_skips_non_activity_or_hotel_tagged_tiles(self, monkeypatch: pytest.MonkeyPatch):
        from app.services.partner_enrichment import enrich_tiles_with_partners

        _enable_all_partners(monkeypatch)

        tiles = [
            {
                "title": "Rome Cavalieri, A Waldorf Astoria Hotel",
                "type": "hotel",
                "provider": "google_places",
                "meta": {"category": "luxury"},
            },
            {
                "title": "Blue Hole Dive",
                "type": "activity",
                "meta": {"category": "diving"},
            },
            {
                "title": "Rome Cavalieri, A Waldorf Astoria Hotel",
                "type": "activity",
                "tags": ["hotel"],
                "meta": {"category": "shopping"},
            },
        ]

        with patch(
            "app.services.partner_enrichment.match_activity_to_best_partner",
            new=AsyncMock(return_value=VIATOR_TILE),
        ) as mock_match:
            await enrich_tiles_with_partners(tiles, "Rome")

        mock_match.assert_awaited_once()
        assert mock_match.await_args.args == ("Blue Hole Dive", "Rome", "USD")
        assert "partner" not in tiles[0]
        assert tiles[1]["partner"] == "viator"
        assert "partner" not in tiles[2]

    async def test_rejects_geo_mismatched_partner_matches(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from app.services.partner_enrichment import enrich_tiles_with_partners

        _enable_all_partners(monkeypatch)

        tiles = [
            {
                "title": "Mercato Centrale",
                "type": "activity",
                "meta": {"category": "food"},
                "geo": {"lat": 41.9028, "lng": 12.4964},  # Rome
            }
        ]
        far_match = {
            **VIATOR_TILE,
            "partner_product_id": "NAPLES-1",
            "geo": {"lat": 40.8518, "lng": 14.2681},  # Naples
        }

        with patch(
            "app.services.partner_enrichment.match_activity_to_best_partner",
            new=AsyncMock(return_value=far_match),
        ):
            await enrich_tiles_with_partners(tiles, "Rome")

        assert "partner" not in tiles[0]
        assert tiles[0]["geo"] == {"lat": 41.9028, "lng": 12.4964}
