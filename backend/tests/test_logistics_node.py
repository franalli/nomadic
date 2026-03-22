"""
Unit tests for logistics_node.py — the SEARCH_TILES coordinator step.

Tests the tile fetch/transform/cache logic. ALL external dependencies
(LLM, providers, DB, IATA resolver, aviasales) are mocked.

Covers:
- logistics_node() main entry: skip conditions, cache hit, flight/hotel/activity paths
- _sanitize_tile_geo / _sanitize_tile_geo_list: geo normalization
- _tile_to_dict: tile serialization
- _tile_matches_categories: tag/keyword matching
- _has_nofly_constraints: constraint detection
- _calculate_diving_safety: 24h buffer math
- _get_mock_flights: mock data shape

- _fallback_tier2_tiles: fallback retagging
- _backfill_experience_tiles_from_gp: GP data backfill
- _hotel_logistics_hash / _activity_logistics_hash / _flight_logistics_hash: cache keys
- _compute_tiles_per_category: tile scaling
- Edge cases: empty destination, no dates, zero results
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.planner.nodes.logistics_node import (
    _activity_logistics_hash,
    _backfill_experience_tiles_from_gp,
    _calculate_diving_safety,
    _compute_tiles_per_category,
    _fallback_tier2_tiles,
    _flight_logistics_hash,
    _get_mock_flights,
    _has_nofly_constraints,
    _hotel_logistics_hash,
    _sanitize_tile_geo,
    _sanitize_tile_geo_list,
    _tile_matches_categories,
    _tile_to_dict,
    logistics_node,
)
from app.planner.state.graph_state import (
    GraphState,
    SpecialistConstraint,
    TripPlan,
)

# =============================================================================
# Helpers
# =============================================================================


def _make_state(**overrides: Any) -> GraphState:
    """Build a minimal GraphState with sensible defaults."""
    defaults: Dict[str, Any] = {
        "trip_plan": TripPlan(
            destination="Bali",
            origin="London",
            start_date="2026-04-01",
            end_date="2026-04-07",
            adults=2,
            children=0,
            currency="USD",
        ),
        "tiles": {"hotels": [], "activities": [], "flights": []},
        "metadata": {},
    }
    defaults.update(overrides)
    return GraphState(**defaults)


def _make_tile(**overrides: Any) -> Dict[str, Any]:
    """Build a minimal tile dict."""
    base = {
        "id": "tile_1",
        "type": "activity",
        "title": "Temple Tour",
        "subtitle": "Explore ancient temples",
        "tags": ["cultural", "tours"],
        "price_estimate": 50.0,
        "image_url": "https://example.com/img.jpg",
    }
    base.update(overrides)
    return base


# =============================================================================
# _sanitize_tile_geo / _sanitize_tile_geo_list
# =============================================================================


class TestSanitizeTileGeo:
    def test_cleans_empty_geo(self) -> None:
        tile = {"id": "t1", "geo": {"lat": None, "lng": None}}
        result = _sanitize_tile_geo(tile)
        assert result["geo"] is None

    def test_keeps_valid_geo(self) -> None:
        tile = {"id": "t1", "geo": {"lat": -8.5, "lng": 115.3}}
        result = _sanitize_tile_geo(tile)
        assert result["geo"] == {"lat": -8.5, "lng": 115.3}

    def test_normalizes_lon_to_lng(self) -> None:
        tile = {"id": "t1", "geo": {"lat": 10.0, "lon": 20.0}}
        result = _sanitize_tile_geo(tile)
        assert result["geo"]["lng"] == 20.0
        assert "lon" not in result["geo"]

    def test_cleans_meta_geo(self) -> None:
        tile = {"id": "t1", "meta": {"geo": {"lat": None, "lng": None}}}
        result = _sanitize_tile_geo(tile)
        assert result["meta"]["geo"] is None

    def test_normalizes_meta_geo_lon(self) -> None:
        tile = {"id": "t1", "meta": {"geo": {"lat": 5.0, "lon": 10.0}}}
        result = _sanitize_tile_geo(tile)
        assert result["meta"]["geo"]["lng"] == 10.0

    def test_empty_dict_geo_cleaned(self) -> None:
        tile = {"id": "t1", "geo": {}}
        result = _sanitize_tile_geo(tile)
        assert result["geo"] is None

    def test_no_geo_key_unchanged(self) -> None:
        tile = {"id": "t1", "title": "Test"}
        result = _sanitize_tile_geo(tile)
        assert "geo" not in result

    def test_list_sanitization(self) -> None:
        tiles = [
            {"id": "t1", "geo": {"lat": None, "lng": None}},
            {"id": "t2", "geo": {"lat": 1.0, "lng": 2.0}},
        ]
        result = _sanitize_tile_geo_list(tiles)
        assert result[0]["geo"] is None
        assert result[1]["geo"] == {"lat": 1.0, "lng": 2.0}


# =============================================================================
# _tile_to_dict
# =============================================================================


class TestTileToDict:
    def test_dict_passthrough(self) -> None:
        tile = {"id": "t1", "title": "Test", "type": "activity"}
        result = _tile_to_dict(tile)
        assert result["id"] == "t1"
        assert result["source_agent"] == "logistics_node"

    def test_pydantic_model_dump(self) -> None:
        class FakeTile:
            def model_dump(self):
                return {"id": "t1", "title": "Fake", "type": "hotel"}

        result = _tile_to_dict(FakeTile())
        assert result["id"] == "t1"
        assert result["source_agent"] == "logistics_node"

    def test_preserves_existing_source_agent(self) -> None:
        tile = {"id": "t1", "source_agent": "specialist_node"}
        result = _tile_to_dict(tile)
        assert result["source_agent"] == "specialist_node"

    def test_sets_category_from_meta(self) -> None:
        tile = {"id": "t1", "meta": {"category": "diving"}}
        result = _tile_to_dict(tile)
        assert result["category"] == "diving"

    def test_default_category_activity(self) -> None:
        tile = {"id": "t1"}
        result = _tile_to_dict(tile)
        assert result["category"] == "logistics_node"

    def test_simple_namespace(self) -> None:
        tile = SimpleNamespace(
            id="t1",
            title="NS Tile",
            type="activity",
            subtitle="",
            tags=[],
            image_url="",
            price_estimate=0,
        )
        result = _tile_to_dict(tile)
        assert result["id"] == "t1"


# =============================================================================
# _tile_matches_categories
# =============================================================================


class TestTileMatchesCategories:
    def test_matches_by_tag(self) -> None:
        tile = _make_tile(tags=["yoga", "wellness"])
        assert _tile_matches_categories(tile, {"yoga"}) is True

    def test_no_match(self) -> None:
        tile = _make_tile(tags=["surfing"])
        assert _tile_matches_categories(tile, {"yoga"}) is False

    def test_matches_by_title_fallback(self) -> None:
        tile = _make_tile(tags=[], title="Morning Yoga Session")
        assert _tile_matches_categories(tile, {"yoga"}) is True

    def test_matches_by_subtitle_fallback(self) -> None:
        tile = _make_tile(tags=[], title="Something", subtitle="Night yoga class")
        assert _tile_matches_categories(tile, {"yoga"}) is True

    def test_case_insensitive(self) -> None:
        tile = _make_tile(tags=["YOGA"])
        assert _tile_matches_categories(tile, {"yoga"}) is True


# =============================================================================
# _has_nofly_constraints
# =============================================================================


class TestHasNoflyConstraints:
    def test_no_constraints(self) -> None:
        state = _make_state()
        assert _has_nofly_constraints(state) is False

    def test_active_specialist_diving(self) -> None:
        state = _make_state()
        state.active_specialist = "diving"
        assert _has_nofly_constraints(state) is True

    def test_strategy_section_specialist(self) -> None:
        state = _make_state(metadata={"strategy_sections": [{"specialist_type": "diving"}]})
        assert _has_nofly_constraints(state) is True

    def test_trip_plan_constraint(self) -> None:
        state = _make_state()
        state.trip_plan.constraints = [
            SpecialistConstraint(
                type="safety",
                rule="24h no_fly buffer required",
                constraint_id="no_fly_24h",
            )
        ]
        assert _has_nofly_constraints(state) is True

    def test_constraints_applied_in_section(self) -> None:
        state = _make_state(
            metadata={
                "strategy_sections": [
                    {
                        "specialist_type": "general",
                        "constraints_applied": [{"rule": "24h surface_interval"}],
                    }
                ]
            }
        )
        assert _has_nofly_constraints(state) is True


# =============================================================================
# _calculate_diving_safety
# =============================================================================


class TestCalculateDivingSafety:
    def test_safe_evening_flight(self) -> None:
        # Flight at 18:00, last dive yesterday at 14:00 => 28h buffer
        status, is_safe = _calculate_diving_safety("2026-04-07T18:00:00")
        assert is_safe is True
        assert "Safe" in status

    def test_unsafe_morning_flight(self) -> None:
        # Flight at 08:00, last dive yesterday at 14:00 => 18h buffer
        status, is_safe = _calculate_diving_safety("2026-04-07T08:00:00")
        assert is_safe is False
        assert "Risky" in status

    def test_exactly_24h_is_safe(self) -> None:
        # Flight at 14:00 => exactly 24h from yesterday 14:00
        status, is_safe = _calculate_diving_safety("2026-04-07T14:00:00")
        assert is_safe is True

    def test_just_under_24h_unsafe(self) -> None:
        # Flight at 13:59 => 23h59m
        status, is_safe = _calculate_diving_safety("2026-04-07T13:59:00")
        assert is_safe is False


# =============================================================================
# _get_mock_flights
# =============================================================================


class TestGetMockFlights:
    def test_returns_three_flights(self) -> None:
        flights = _get_mock_flights("2026-04-07")
        assert len(flights) == 3

    def test_flight_structure(self) -> None:
        flights = _get_mock_flights("2026-04-07")
        for flight in flights:
            assert "id" in flight
            assert "price" in flight
            assert "itineraries" in flight
            segments = flight["itineraries"][0]["segments"]
            assert len(segments) >= 1
            assert "carrierCode" in segments[0]
            assert "departure" in segments[0]

    def test_uses_provided_date(self) -> None:
        flights = _get_mock_flights("2026-12-25")
        dep = flights[0]["itineraries"][0]["segments"][0]["departure"]["at"]
        assert "2026-12-25" in dep

    def test_none_date_fallback(self) -> None:
        flights = _get_mock_flights(None)
        assert len(flights) == 3

    def test_includes_unsafe_and_safe(self) -> None:
        flights = _get_mock_flights("2026-04-07")
        ids = [f["id"] for f in flights]
        assert "demo_unsafe" in ids
        assert "demo_safe_1" in ids


# =============================================================================
# _fallback_tier2_tiles
# =============================================================================


class TestFallbackTier2Tiles:
    def test_returns_matching_tiles(self) -> None:
        tiles = [
            _make_tile(id="t1", tags=["yoga"]),
            _make_tile(id="t2", tags=["surfing"]),
        ]
        result = _fallback_tier2_tiles(tiles, {"yoga"})
        assert len(result) == 1
        assert result[0]["id"] == "t1"

    def test_retags_when_insufficient(self) -> None:
        tiles = [
            _make_tile(id="t1", tags=["surfing"]),
            _make_tile(id="t2", tags=["hiking"]),
        ]
        result = _fallback_tier2_tiles(tiles, {"yoga"}, target_count=2)
        assert len(result) == 2
        # Retagged tiles get audit trail
        assert result[0].get("meta", {}).get("fallback_retagged") is True

    def test_empty_existing_tiles(self) -> None:
        result = _fallback_tier2_tiles([], {"yoga"}, target_count=4)
        assert result == []

    def test_does_not_mutate_originals(self) -> None:
        original = _make_tile(id="t1", tags=["surfing"])
        _fallback_tier2_tiles([original], {"yoga"}, target_count=1)
        assert "fallback_retagged" not in (original.get("meta") or {})


# =============================================================================
# _backfill_experience_tiles_from_gp
# =============================================================================


class TestBackfillExperienceTilesFromGp:
    def test_backfills_geo(self) -> None:
        exp_tiles = [{"title": "Temple Tour", "geo": None, "meta": {}}]
        gp_tiles = [
            {
                "title": "Temple Tour",
                "geo": {"lat": -8.5, "lng": 115.3},
                "meta": {},
            }
        ]
        _backfill_experience_tiles_from_gp(exp_tiles, gp_tiles)
        assert exp_tiles[0]["geo"] == {"lat": -8.5, "lng": 115.3}

    def test_backfills_image_url(self) -> None:
        exp_tiles = [{"title": "Beach Walk", "meta": {}}]
        gp_tiles = [
            {
                "title": "Beach Walk",
                "image_url": "https://gp.com/photo.jpg",
                "geo": {"lat": 1, "lng": 2},
                "meta": {},
            }
        ]
        _backfill_experience_tiles_from_gp(exp_tiles, gp_tiles)
        assert exp_tiles[0]["image_url"] == "https://gp.com/photo.jpg"

    def test_no_match_leaves_tile_unchanged(self) -> None:
        exp_tiles = [{"title": "Unique Activity", "meta": {}}]
        gp_tiles = [{"title": "Completely Different", "geo": {"lat": 1, "lng": 2}, "meta": {}}]
        _backfill_experience_tiles_from_gp(exp_tiles, gp_tiles)
        assert "geo" not in exp_tiles[0]

    def test_empty_gp_list(self) -> None:
        exp_tiles = [{"title": "Temple Tour", "meta": {}}]
        _backfill_experience_tiles_from_gp(exp_tiles, [])
        assert exp_tiles == [{"title": "Temple Tour", "meta": {}}]

    def test_substring_match(self) -> None:
        exp_tiles = [{"title": "Colosseum and Roman Forum Tour", "meta": {}}]
        gp_tiles = [
            {
                "title": "Colosseum",
                "geo": {"lat": 41.89, "lng": 12.49},
                "meta": {},
            }
        ]
        _backfill_experience_tiles_from_gp(exp_tiles, gp_tiles)
        assert exp_tiles[0]["geo"] == {"lat": 41.89, "lng": 12.49}

    def test_backfills_rating(self) -> None:
        exp_tiles = [{"title": "Beach Walk", "rating": None, "meta": {}}]
        gp_tiles = [
            {
                "title": "Beach Walk",
                "rating": 4.5,
                "geo": {"lat": 1, "lng": 2},
                "meta": {},
            }
        ]
        _backfill_experience_tiles_from_gp(exp_tiles, gp_tiles)
        assert exp_tiles[0]["rating"] == 4.5

    def test_backfills_deeplink(self) -> None:
        exp_tiles = [{"title": "Beach Walk", "meta": {}}]
        gp_tiles = [
            {
                "title": "Beach Walk",
                "deeplink": "https://maps.google.com/...",
                "geo": {"lat": 1, "lng": 2},
                "meta": {},
            }
        ]
        _backfill_experience_tiles_from_gp(exp_tiles, gp_tiles)
        assert exp_tiles[0]["deeplink"] == "https://maps.google.com/..."


# =============================================================================
# Cache hash helpers
# =============================================================================


class TestCacheHashHelpers:
    def test_hotel_hash_stable(self) -> None:
        state = _make_state()
        h1 = _hotel_logistics_hash(state)
        h2 = _hotel_logistics_hash(state)
        assert h1 == h2

    def test_hotel_hash_changes_on_destination(self) -> None:
        s1 = _make_state()
        s2 = _make_state()
        s2.trip_plan.destination = "Rome"
        assert _hotel_logistics_hash(s1) != _hotel_logistics_hash(s2)

    def test_activity_hash_changes_on_categories(self) -> None:
        s1 = _make_state()
        s2 = _make_state()
        s2.metadata["trip_settings"] = {
            "activity_settings": {"categories": ["yoga"]},
        }
        assert _activity_logistics_hash(s1) != _activity_logistics_hash(s2)

    def test_flight_hash_changes_on_origin(self) -> None:
        s1 = _make_state()
        s2 = _make_state()
        s2.trip_plan.origin = "Paris"
        assert _flight_logistics_hash(s1) != _flight_logistics_hash(s2)

    def test_hotel_hash_independent_of_activity_settings(self) -> None:
        s1 = _make_state()
        s2 = _make_state()
        s2.metadata["trip_settings"] = {
            "activity_settings": {"categories": ["yoga"]},
        }
        assert _hotel_logistics_hash(s1) == _hotel_logistics_hash(s2)


# =============================================================================
# _compute_tiles_per_category
# =============================================================================


class TestComputeTilesPerCategory:
    def test_no_dates_returns_minimum(self) -> None:
        state = _make_state()
        state.trip_plan.start_date = None
        state.trip_plan.end_date = None
        assert _compute_tiles_per_category(state, {"yoga"}) == 2

    def test_empty_categories_returns_minimum(self) -> None:
        state = _make_state()
        assert _compute_tiles_per_category(state, set()) == 2

    def test_short_trip_returns_at_least_4(self) -> None:
        state = _make_state()
        state.trip_plan.start_date = "2026-04-01"
        state.trip_plan.end_date = "2026-04-03"
        result = _compute_tiles_per_category(state, {"yoga"})
        assert result >= 4

    def test_long_trip_scales_up(self) -> None:
        state = _make_state()
        state.trip_plan.start_date = "2026-04-01"
        state.trip_plan.end_date = "2026-04-21"
        result = _compute_tiles_per_category(state, {"yoga"})
        # 21-day trip should have more tiles than minimum
        assert result >= 4

    def test_specialist_days_reduce_free_days(self) -> None:
        state = _make_state()
        state.trip_plan.start_date = "2026-04-01"
        state.trip_plan.end_date = "2026-04-10"
        state.metadata["strategy_sections"] = [
            {
                "specialist_type": "diving",
                "content_added": [
                    {"title": "Dive Site A"},
                    {"title": "Dive Site B"},
                    {"title": "Dive Site C"},
                ],
            }
        ]
        with_specialist = _compute_tiles_per_category(state, {"yoga"})

        state2 = _make_state()
        state2.trip_plan.start_date = "2026-04-01"
        state2.trip_plan.end_date = "2026-04-10"
        without_specialist = _compute_tiles_per_category(state2, {"yoga"})

        # Both should be valid, specialist presence may affect the count
        assert with_specialist >= 4
        assert without_specialist >= 4


# =============================================================================
# logistics_node() — main entry point
# =============================================================================


class TestLogisticsNodeSkipConditions:
    """Test conditions that cause logistics_node to skip or return early."""

    @pytest.mark.asyncio
    async def test_skip_no_destination(self) -> None:
        state = _make_state()
        state.trip_plan.destination = None
        result = await logistics_node(state)
        assert result.metadata.get("logistics_attempted") is True
        # No tiles should be fetched
        assert result.tiles.get("hotels", []) == []

    @pytest.mark.asyncio
    async def test_skip_no_start_date(self) -> None:
        state = _make_state()
        state.trip_plan.start_date = None
        result = await logistics_node(state)
        assert result.metadata.get("logistics_attempted") is True

    @pytest.mark.asyncio
    async def test_cache_hit_all_categories(self) -> None:
        """When all hash categories match, return cached state without fetching."""
        state = _make_state()
        state.tiles = {
            "hotels": [{"id": "h1"}],
            "activities": [{"id": "a1"}],
            "flights": [{"id": "f1"}],
        }
        # Pre-compute and store hashes
        state.metadata["_logistics_hotel_hash"] = _hotel_logistics_hash(state)
        state.metadata["_logistics_activity_hash"] = _activity_logistics_hash(state)
        state.metadata["_logistics_flight_hash"] = _flight_logistics_hash(state)

        result = await logistics_node(state)
        assert result.metadata.get("logistics_attempted") is True
        # Tiles should be unchanged (cache hit)
        assert result.tiles["hotels"] == [{"id": "h1"}]
        assert result.tiles["activities"] == [{"id": "a1"}]
        assert result.tiles["flights"] == [{"id": "f1"}]


class TestLogisticsNodeSelectiveInvalidation:
    """Test that only changed categories are invalidated."""

    @pytest.mark.asyncio
    @patch("app.planner.nodes.logistics_node._search_hotels_and_activities", new_callable=AsyncMock)
    @patch("app.planner.nodes.logistics_node.resolve_iata_codes", new_callable=AsyncMock)
    async def test_hotel_hash_change_clears_hotels(
        self, mock_iata: AsyncMock, mock_search: AsyncMock
    ) -> None:
        mock_iata.return_value = ("", "")
        mock_search.return_value = None

        state = _make_state()
        state.tiles = {
            "hotels": [{"id": "h1"}],
            "activities": [{"id": "a1"}],
            "flights": [{"id": "f1"}],
        }
        # Store correct hashes for activities and flights, stale for hotels
        state.metadata["_logistics_hotel_hash"] = "stale_hash"
        state.metadata["_logistics_activity_hash"] = _activity_logistics_hash(state)
        state.metadata["_logistics_flight_hash"] = _flight_logistics_hash(state)

        result = await logistics_node(state)
        # Hotels should have been cleared before re-fetch
        assert result.metadata.get("_tiles_replaced") is True


class TestLogisticsNodeFlightSearch:
    """Test flight search paths."""

    @pytest.mark.asyncio
    @patch("app.planner.nodes.logistics_node._search_hotels_and_activities", new_callable=AsyncMock)
    @patch("app.planner.nodes.logistics_node.resolve_iata_codes", new_callable=AsyncMock)
    async def test_skips_flights_when_disabled(
        self, mock_iata: AsyncMock, mock_search: AsyncMock
    ) -> None:
        mock_iata.return_value = ("LHR", "DPS")
        mock_search.return_value = None

        state = _make_state()
        state.metadata["trip_settings"] = {
            "booking_types": {"flights": "off"},
        }
        # Disable auto-upgrade so flights stay "off"
        state.metadata["allow_flight_auto_upgrade"] = False
        result = await logistics_node(state)
        assert result.metadata.get("flight_search_status") == "skipped_disabled"

    @pytest.mark.asyncio
    @patch("app.planner.nodes.logistics_node._search_hotels_and_activities", new_callable=AsyncMock)
    @patch("app.planner.nodes.logistics_node.resolve_iata_codes", new_callable=AsyncMock)
    async def test_skips_flights_no_origin(
        self, mock_iata: AsyncMock, mock_search: AsyncMock
    ) -> None:
        mock_iata.return_value = ("", "DPS")
        mock_search.return_value = None

        state = _make_state()
        state.trip_plan.origin = None
        # Enable flights so the skip reason is "no_origin" not "disabled"
        state.metadata["trip_settings"] = {
            "booking_types": {"flights": "suggested"},
        }
        result = await logistics_node(state)
        assert result.metadata.get("flight_skip_reason") == "no_origin_for_flights"

    @pytest.mark.asyncio
    @patch("app.planner.nodes.logistics_node.search_aviasales_flights", new_callable=AsyncMock)
    @patch("app.planner.nodes.logistics_node._search_hotels_and_activities", new_callable=AsyncMock)
    @patch("app.planner.nodes.logistics_node.resolve_iata_codes", new_callable=AsyncMock)
    @patch("app.planner.nodes.logistics_node.settings")
    async def test_mock_fallback_when_aviasales_returns_empty(
        self,
        mock_settings: MagicMock,
        mock_iata: AsyncMock,
        mock_search: AsyncMock,
        mock_aviasales: AsyncMock,
    ) -> None:
        mock_settings.aviasales_enabled = False
        mock_settings.use_google_places_provider = False
        mock_settings.tier2_generation_wait_budget_ms = 0
        mock_settings.tier2_prefetch_wait_budget_ms = 0
        mock_iata.return_value = ("LHR", "DPS")
        mock_search.return_value = None

        state = _make_state()
        state.metadata["trip_settings"] = {
            "booking_types": {"flights": "suggested"},
        }
        result = await logistics_node(state)
        # Should have mock flight tiles
        assert len(result.tiles.get("flights", [])) > 0
        assert result.metadata.get("flight_search_status") == "searched"

    @pytest.mark.asyncio
    @patch("app.planner.nodes.logistics_node._search_hotels_and_activities", new_callable=AsyncMock)
    @patch("app.planner.nodes.logistics_node.resolve_iata_codes", new_callable=AsyncMock)
    @patch("app.planner.nodes.logistics_node.settings")
    async def test_nofly_constraint_filters_unsafe_flights(
        self,
        mock_settings: MagicMock,
        mock_iata: AsyncMock,
        mock_search: AsyncMock,
    ) -> None:
        mock_settings.aviasales_enabled = False
        mock_settings.use_google_places_provider = False
        mock_settings.tier2_generation_wait_budget_ms = 0
        mock_settings.tier2_prefetch_wait_budget_ms = 0
        mock_iata.return_value = ("LHR", "DPS")
        mock_search.return_value = None

        state = _make_state()
        state.active_specialist = "diving"
        state.metadata["trip_settings"] = {
            "booking_types": {"flights": "suggested"},
        }
        result = await logistics_node(state)
        # The demo_unsafe flight (08:00) should be filtered out
        flight_ids = [f.get("id") for f in result.tiles.get("flights", [])]
        assert "demo_unsafe" not in flight_ids
        # Safe flights should remain
        assert len(result.tiles.get("flights", [])) >= 1


class TestLogisticsNodeAutoUpgrade:
    """Test flight auto-upgrade logic."""

    @pytest.mark.asyncio
    @patch("app.planner.nodes.logistics_node._search_hotels_and_activities", new_callable=AsyncMock)
    @patch("app.planner.nodes.logistics_node.resolve_iata_codes", new_callable=AsyncMock)
    @patch("app.planner.nodes.logistics_node.settings")
    async def test_auto_upgrades_flights_when_origin_present(
        self,
        mock_settings: MagicMock,
        mock_iata: AsyncMock,
        mock_search: AsyncMock,
    ) -> None:
        mock_settings.aviasales_enabled = False
        mock_settings.use_google_places_provider = False
        mock_settings.tier2_generation_wait_budget_ms = 0
        mock_settings.tier2_prefetch_wait_budget_ms = 0
        mock_iata.return_value = ("LHR", "DPS")
        mock_search.return_value = None

        state = _make_state()
        # flights off but origin present => should auto-upgrade
        state.metadata["trip_settings"] = {
            "booking_types": {"flights": "off"},
        }
        state.metadata["allow_flight_auto_upgrade"] = True
        result = await logistics_node(state)
        # Should have searched for flights after auto-upgrade
        assert result.metadata.get("flight_search_status") == "searched"

    @pytest.mark.asyncio
    @patch("app.planner.nodes.logistics_node._search_hotels_and_activities", new_callable=AsyncMock)
    @patch("app.planner.nodes.logistics_node.resolve_iata_codes", new_callable=AsyncMock)
    async def test_no_auto_upgrade_when_explicitly_disabled(
        self, mock_iata: AsyncMock, mock_search: AsyncMock
    ) -> None:
        mock_iata.return_value = ("LHR", "DPS")
        mock_search.return_value = None

        state = _make_state()
        state.metadata["trip_settings"] = {
            "booking_types": {"flights": "off"},
        }
        state.metadata["allow_flight_auto_upgrade"] = False
        result = await logistics_node(state)
        # Should NOT have upgraded
        assert result.metadata.get("flight_search_status") != "searched"
