"""Tests for backend/app/tile_service/service.py.

Covers:
- _build_search_context: field mapping and fallback logic
- _get_providers: provider routing based on settings flags
- search_tiles: error swallowing, summary computation
"""

from __future__ import annotations

from typing import List
from unittest.mock import patch

import pytest

from app.schemas import Tile, TilesSearchRequest
from app.tile_service.models import SearchContext
from app.tile_service.provider_base import Provider
from app.tile_service.service import (
    _build_search_context,
    _get_providers,
    search_tiles,
)

# =============================================================================
# _build_search_context
# =============================================================================


class TestBuildSearchContext:
    """Tests for _build_search_context field mapping."""

    def test_all_fields_mapped(self) -> None:
        req = TilesSearchRequest(
            destination="Tokyo",
            destination_hint="Osaka",
            origin="LAX",
            start_date="2026-03-01",
            end_date="2026-03-10",
            adults=2,
            children=1,
            requires_assistance=True,
            verticals=["hotel", "flight"],
            max_results_per_vertical=3,
            currency="EUR",
            response_mode="live",
            budget=5000.0,
            budget_per_category=1500.0,
        )
        ctx = _build_search_context(req)

        assert ctx.destination == "Tokyo"
        assert ctx.origin == "LAX"
        assert ctx.start_date == "2026-03-01"
        assert ctx.end_date == "2026-03-10"
        assert ctx.adults == 2
        assert ctx.children == 1
        assert ctx.requires_assistance is True
        assert ctx.verticals == ["hotel", "flight"]
        assert ctx.max_results_per_vertical == 3
        assert ctx.currency == "EUR"
        assert ctx.response_mode == "live"
        assert ctx.budget == 5000.0
        assert ctx.budget_per_category == 1500.0

    def test_destination_fallback_to_hint(self) -> None:
        """When destination is None, destination_hint is used."""
        req = TilesSearchRequest(
            destination=None,
            destination_hint="Paris",
        )
        ctx = _build_search_context(req)
        assert ctx.destination == "Paris"

    def test_destination_none_when_both_absent(self) -> None:
        """When both destination and hint are None, context.destination is None."""
        req = TilesSearchRequest(destination=None, destination_hint=None)
        ctx = _build_search_context(req)
        assert ctx.destination is None

    def test_verticals_empty_list(self) -> None:
        """When verticals is an empty list, context.verticals is empty."""
        req = TilesSearchRequest(verticals=[])
        ctx = _build_search_context(req)
        assert ctx.verticals == []


# =============================================================================
# _get_providers
# =============================================================================


class TestGetProviders:
    """Tests for _get_providers routing logic."""

    def _make_ctx(
        self,
        destination: str = "rome",
        verticals: list | None = None,
    ) -> SearchContext:
        return SearchContext(
            destination=destination,
            verticals=verticals or [],
        )

    def test_curated_destination(self) -> None:
        """use_demo_curation=True + dest in DEMO_MANIFEST -> CuratedProvider + MockFlight."""

        ctx = self._make_ctx(destination="dubai")

        with (
            patch("app.tile_service.service.settings") as mock_settings,
            patch(
                "app.tile_service.service.DEMO_MANIFEST",
                {"dubai": {}},
                create=True,
            ),
        ):
            mock_settings.use_demo_curation = True
            mock_settings.use_google_places_provider = False

            # Patch the import inside _get_providers
            with patch.dict(
                "sys.modules",
                {"app.data.demo_curation": type("m", (), {"DEMO_MANIFEST": {"dubai": {}}})()},
            ):
                providers = _get_providers(ctx)

        provider_types = [type(p).__name__ for p in providers]
        assert "CuratedProvider" in provider_types
        assert "MockFlightProvider" in provider_types

    def test_google_places_fallback(self) -> None:
        """use_demo_curation=False, use_google_places_provider=True -> GooglePlaces + MockFlight + GooglePlacesActivity."""

        ctx = self._make_ctx(destination="barcelona")

        with patch("app.tile_service.service.settings") as mock_settings:
            mock_settings.use_demo_curation = False
            mock_settings.use_google_places_provider = True
            providers = _get_providers(ctx)

        provider_types = [type(p).__name__ for p in providers]
        assert "GooglePlacesHotelProvider" in provider_types
        assert "MockFlightProvider" in provider_types
        assert "GooglePlacesActivityProvider" in provider_types

    def test_mock_fallback(self) -> None:
        """Both flags False -> MockHotel + MockFlight + MockActivity."""

        ctx = self._make_ctx(destination="nowhere")

        with patch("app.tile_service.service.settings") as mock_settings:
            mock_settings.use_demo_curation = False
            mock_settings.use_google_places_provider = False
            providers = _get_providers(ctx)

        provider_types = [type(p).__name__ for p in providers]
        assert "MockHotelProvider" in provider_types
        assert "MockFlightProvider" in provider_types
        assert "MockActivityProvider" in provider_types

    def test_vertical_filter_hotel_only(self) -> None:
        """With verticals=['hotel'] filter, only hotel providers returned."""
        ctx = self._make_ctx(destination="nowhere", verticals=["hotel"])

        with patch("app.tile_service.service.settings") as mock_settings:
            mock_settings.use_demo_curation = False
            mock_settings.use_google_places_provider = False
            providers = _get_providers(ctx)

        provider_types = [type(p).__name__ for p in providers]
        assert "MockHotelProvider" in provider_types
        assert "MockFlightProvider" not in provider_types
        assert "MockActivityProvider" not in provider_types

    def test_vertical_filter_flight_only(self) -> None:
        """With verticals=['flight'], only flight provider returned."""
        ctx = self._make_ctx(destination="nowhere", verticals=["flight"])

        with patch("app.tile_service.service.settings") as mock_settings:
            mock_settings.use_demo_curation = False
            mock_settings.use_google_places_provider = False
            providers = _get_providers(ctx)

        provider_types = [type(p).__name__ for p in providers]
        assert "MockFlightProvider" in provider_types
        assert "MockHotelProvider" not in provider_types
        assert "MockActivityProvider" not in provider_types


# =============================================================================
# search_tiles
# =============================================================================


def _make_tile(
    tile_type: str = "hotel",
    price: float | None = 100.0,
    title: str = "Test",
) -> Tile:
    return Tile(
        id=f"tile-{title.lower()}",
        type=tile_type,
        title=title,
        price_estimate=price,
        deeplink_url="https://example.com",
    )


class _GoodProvider(Provider):
    name = "good"

    def __init__(self, tiles: List[Tile]) -> None:
        self._tiles = tiles

    def search(self, ctx: SearchContext) -> List[Tile]:
        return self._tiles


class _FailingProvider(Provider):
    name = "failing"

    def search(self, ctx: SearchContext) -> List[Tile]:
        raise RuntimeError("provider exploded")


class TestSearchTiles:
    """Tests for search_tiles entry point."""

    def test_provider_exception_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A failing provider does not prevent other tiles from being returned."""
        good_tile = _make_tile(title="Good Hotel")

        monkeypatch.setattr(
            "app.tile_service.service._get_providers",
            lambda ctx: [_FailingProvider(), _GoodProvider([good_tile])],
        )

        req = TilesSearchRequest(destination="Test City")
        resp = search_tiles(req)

        assert len(resp.tiles) == 1
        assert resp.tiles[0].title == "Good Hotel"

    def test_summary_min_max_price(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Summary min/max_price_estimate computed correctly."""
        tiles = [
            _make_tile(price=50.0, title="Cheap"),
            _make_tile(price=200.0, title="Mid"),
            _make_tile(price=500.0, title="Expensive"),
        ]

        monkeypatch.setattr(
            "app.tile_service.service._get_providers",
            lambda ctx: [_GoodProvider(tiles)],
        )

        req = TilesSearchRequest(destination="Test City")
        resp = search_tiles(req)

        assert resp.summary["min_price_estimate"] == 50.0
        assert resp.summary["max_price_estimate"] == 500.0

    def test_summary_min_max_with_none_prices(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Tiles with None price are excluded from min/max computation."""
        tiles = [
            _make_tile(price=None, title="NoPriceA"),
            _make_tile(price=120.0, title="HasPrice"),
            _make_tile(price=None, title="NoPriceB"),
        ]

        monkeypatch.setattr(
            "app.tile_service.service._get_providers",
            lambda ctx: [_GoodProvider(tiles)],
        )

        req = TilesSearchRequest(destination="Test City")
        resp = search_tiles(req)

        assert resp.summary["min_price_estimate"] == 120.0
        assert resp.summary["max_price_estimate"] == 120.0

    def test_empty_tiles_min_price_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When no tiles returned, min/max_price_estimate is None."""
        monkeypatch.setattr(
            "app.tile_service.service._get_providers",
            lambda ctx: [_GoodProvider([])],
        )

        req = TilesSearchRequest(destination="Test City")
        resp = search_tiles(req)

        assert resp.tiles == []
        assert resp.summary["min_price_estimate"] is None
        assert resp.summary["max_price_estimate"] is None

    def test_verticals_returned_in_summary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Summary verticals_returned reflects the tile types present."""
        tiles = [
            _make_tile(tile_type="hotel", title="H1"),
            _make_tile(tile_type="flight", title="F1"),
        ]

        monkeypatch.setattr(
            "app.tile_service.service._get_providers",
            lambda ctx: [_GoodProvider(tiles)],
        )

        req = TilesSearchRequest(destination="Test City")
        resp = search_tiles(req)

        assert resp.summary["verticals_returned"] == ["flight", "hotel"]

    def test_response_has_request_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Response contains a non-empty tiles_request_id."""
        monkeypatch.setattr(
            "app.tile_service.service._get_providers",
            lambda ctx: [_GoodProvider([])],
        )

        req = TilesSearchRequest(destination="Test City")
        resp = search_tiles(req)

        assert resp.tiles_request_id
        assert len(resp.tiles_request_id) == 32  # uuid4 hex
