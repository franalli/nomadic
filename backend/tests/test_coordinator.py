"""
Unit tests for coordinator.py helpers retained after the deterministic-DAG removal.

The legacy plan_turn()/execute_turn() DAG and its dispatch/preserve/tile-refresh
helpers were deleted with the coordinator rewrite; the planner now runs through the
LangChain create_agent loop (see app/planner/services/agent_runner.py). These tests
cover the pure-Python helpers that survived and are still imported by the agent path:
- _build_envelope(): PlanViewState transitions + envelope shape
- _compute_coordinator_s3_state(): builder result -> S3 sub-state
- _builder_conflicts_to_constraint_violations(): conflict mapping
- _specialist_content_to_tiles() / _post_build_enrich_placed_activities()
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest

from app.planner.coordinator import (
    _builder_conflicts_to_constraint_violations,
    _canonicalize_applied_updates,
    _compute_coordinator_s3_state,
    _norm_topic,
    _post_build_enrich_placed_activities,
    _specialist_content_to_tiles,
    build_trip_state_summary,
)
from app.planner.state.graph_state import ConstraintSeverity, GraphState, TripPlan

# =============================================================================
# Helpers
# =============================================================================


def _make_state(**overrides: Any) -> Dict[str, Any]:
    """Build a minimal agent state dict."""
    state: Dict[str, Any] = {
        "trip_plan": {},
        "trip_settings": {},
        "tiles": {},
        "strategy_sections": [],
        "day_cards": [],
        "constraints": [],
        "specialist_plans": {},
        "persistent_meta": {},
        "turn_meta": {},
    }
    state.update(overrides)
    return state


class TestComputeS3State:
    """Tests for S3 sub-state computation from builder results."""

    def test_builder_success_with_day_cards(self) -> None:
        turn_meta = {"builder_result": {"success": True, "conflicts": []}}
        result = _compute_coordinator_s3_state(turn_meta, [{"day": 1}])
        assert result == "S3_ITINERARY_READY"

    def test_builder_success_with_conflicts(self) -> None:
        turn_meta = {
            "builder_result": {
                "success": True,
                "conflicts": [{"type": "overlap"}],
            }
        }
        result = _compute_coordinator_s3_state(turn_meta, [{"day": 1}])
        assert result == "S3_EDITING"

    def test_builder_success_no_day_cards(self) -> None:
        turn_meta = {"builder_result": {"success": True, "conflicts": []}}
        result = _compute_coordinator_s3_state(turn_meta, [])
        assert result == "S3_BLOCKED"

    def test_builder_failure_with_day_cards(self) -> None:
        turn_meta = {"builder_result": {"success": False, "conflicts": []}}
        result = _compute_coordinator_s3_state(turn_meta, [{"day": 1}])
        assert result == "S3_PARTIAL_CONFLICT"

    def test_builder_failure_no_day_cards(self) -> None:
        turn_meta = {"builder_result": {"success": False, "conflicts": []}}
        result = _compute_coordinator_s3_state(turn_meta, [])
        assert result == "S3_BLOCKED"

    def test_infeasible_zero_activity_result_stays_ready_with_warning(self) -> None:
        turn_meta = {
            "builder_result": {
                "success": True,
                "conflicts": [],
                "activities_placed": 0,
                "warnings": [],
                "infeasible_requested_categories": ["skiing"],
            }
        }
        result = _compute_coordinator_s3_state(turn_meta, [{"day": 1}])
        assert result == "S3_ITINERARY_READY"
        assert any(
            "infeasible" in warning.lower() for warning in turn_meta["builder_result"]["warnings"]
        )


class TestBuilderConflictMapping:
    def test_maps_builder_conflicts_to_constraint_violations(self) -> None:
        mapped = _builder_conflicts_to_constraint_violations(
            [{"type": "temporal_capacity", "message": "Too many blocks", "severity": "warning"}],
            [{"description": "Reduce activities"}],
        )

        assert mapped == [
            {
                "code": "TEMPORAL_CAPACITY",
                "message": "Too many blocks",
                "severity": "warning",
                "category": "itinerary",
                "rule": "temporal_capacity",
                "suggested_action": "Reduce activities",
            }
        ]

    def test_maps_enum_builder_conflict_severity_to_canonical_string(self) -> None:
        mapped = _builder_conflicts_to_constraint_violations(
            [
                {
                    "type": "constraint_clash",
                    "message": "Unsafe overlap",
                    "severity": ConstraintSeverity.BLOCKING,
                }
            ]
        )

        assert mapped[0]["severity"] == "blocking"


# =============================================================================
# _build_envelope — PlanViewState transitions
# =============================================================================


class TestBuildEnvelopeViewState:
    """Test PlanViewState assignment in _build_envelope."""

    @patch("app.planner.services.state_serde.serialize_agent_state", return_value="{}")
    def test_no_destination_returns_s0(self, _mock_serialize: Any) -> None:
        state = _make_state()
        from app.planner.coordinator import _build_envelope

        result = _build_envelope(state, "hello", "sess-1", "Hi there!")
        assert result["document"]["plan_view_state"] == "S0_BOOTSTRAP"

    @patch("app.planner.services.state_serde.serialize_agent_state", return_value="{}")
    def test_strategy_sections_returns_s2(self, _mock_serialize: Any) -> None:
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            },
            strategy_sections=[{"specialist_type": "diving", "content_blocks": []}],
        )
        from app.planner.coordinator import _build_envelope

        result = _build_envelope(state, "plan my trip", "sess-1", "Here is your plan")
        assert result["document"]["plan_view_state"] == "S2_STRATEGY_READY"

    @patch("app.planner.services.state_serde.serialize_agent_state", return_value="{}")
    def test_day_cards_returns_s3_itinerary_ready(self, _mock_serialize: Any) -> None:
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            },
            day_cards=[{"day": 1, "activities": []}],
            turn_meta={
                "builder_result": {"success": True, "conflicts": []},
            },
        )
        from app.planner.coordinator import _build_envelope

        result = _build_envelope(state, "build itinerary", "sess-1", "Done!")
        assert result["document"]["plan_view_state"] == "S3_ITINERARY_READY"

    @patch("app.planner.services.state_serde.serialize_agent_state", return_value="{}")
    def test_builder_conflicts_are_exposed_as_constraint_violations(
        self,
        _mock_serialize: Any,
    ) -> None:
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            },
            day_cards=[{"day": 1, "activities": []}],
            turn_meta={
                "builder_result": {
                    "success": True,
                    "activities_placed": 2,
                    "conflicts": [
                        {
                            "type": "temporal_capacity",
                            "message": "Too many activities",
                            "severity": "warning",
                        }
                    ],
                    "resolutions": [{"description": "Reduce activities"}],
                },
            },
        )
        from app.planner.coordinator import _build_envelope

        result = _build_envelope(state, "build itinerary", "sess-1", "Done!")

        assert result["document"]["plan_view_state"] == "S3_EDITING"
        assert result["document"]["constraint_violations"] == [
            {
                "code": "TEMPORAL_CAPACITY",
                "message": "Too many activities",
                "severity": "warning",
                "category": "itinerary",
                "rule": "temporal_capacity",
                "suggested_action": "Reduce activities",
            }
        ]

    @patch("app.planner.services.state_serde.serialize_agent_state", return_value="{}")
    def test_tiles_only_returns_s2(self, _mock_serialize: Any) -> None:
        state = _make_state(
            trip_plan={
                "destination": "Paris",
                "start_date": "2026-04-01",
                "end_date": "2026-04-05",
            },
            tiles={
                "hotels": [{"id": "h1", "name": "Hotel A"}],
            },
        )
        from app.planner.coordinator import _build_envelope

        result = _build_envelope(state, "find hotels", "sess-1", "Found hotels")
        assert result["document"]["plan_view_state"] == "S2_STRATEGY_READY"

    @patch("app.planner.services.state_serde.serialize_agent_state", return_value="{}")
    def test_flight_tiles_do_not_reenable_explicitly_disabled_flights(
        self,
        _mock_serialize: Any,
    ) -> None:
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "origin": "Rome",
                "start_date": "2026-04-01",
                "end_date": "2026-04-17",
            },
            trip_settings={
                "booking_types": {
                    "flights": "off",
                    "hotels": "suggested",
                    "activities": "suggested",
                }
            },
            tiles={"flights": [{"id": "flight_1"}]},
            persistent_meta={"user_disabled_booking_types": ["flights"]},
        )
        from app.planner.coordinator import _build_envelope

        result = _build_envelope(state, "extend trip", "sess-1", "Updated trip")

        assert result["document"]["trip_inputs"]["booking_types"]["flights"] == "off"
        assert state["trip_settings"]["booking_types"]["flights"] == "off"


# =============================================================================
# Small helpers
# =============================================================================


class TestNormTopic:
    def test_normalizes_case_and_whitespace(self) -> None:
        assert _norm_topic("  Diving ") == "diving"

    def test_empty_string(self) -> None:
        assert _norm_topic("") == ""

    def test_none_safe(self) -> None:
        assert _norm_topic(None) == ""  # type: ignore[arg-type]


class TestCanonicalizeAppliedUpdates:
    def test_maps_date_fields(self) -> None:
        result = _canonicalize_applied_updates(["start_date", "end_date"])
        assert result == ["dates"]

    def test_deduplicates(self) -> None:
        result = _canonicalize_applied_updates(["start_date", "end_date", "trip_duration"])
        assert result.count("dates") == 1

    def test_multiple_categories(self) -> None:
        result = _canonicalize_applied_updates(["destination", "budget", "adults"])
        assert "destination" in result
        assert "budget" in result
        assert "travelers" in result


class TestLogisticsFlightRefresh:
    @pytest.mark.asyncio
    async def test_logistics_does_not_auto_upgrade_when_flights_not_requested(
        self, monkeypatch: Any
    ) -> None:
        import importlib

        logistics_module = importlib.import_module("app.planner.nodes.logistics_node")

        state = GraphState(
            trip_plan=TripPlan(
                destination="Bali",
                origin="Amsterdam",
                start_date="2026-04-01",
                end_date="2026-04-07",
            )
        )
        state.tiles = {"hotels": [], "activities": [], "flights": [{"id": "stale_flight"}]}
        state.metadata.update(
            {
                "trip_settings": {
                    "booking_types": {"flights": "off", "hotels": "suggested", "activities": "on"},
                    "flight_settings": {"direct_only": False, "round_trip": True},
                    "hotel_settings": {"min_stars": 0, "amenities": []},
                    "activity_settings": {"categories": ["diving"]},
                },
                "trip_inputs": {"booking_types": {"flights": "off"}},
                "allow_flight_auto_upgrade": False,
                "requested_tile_types": ["activities"],
            }
        )
        resolve_calls: list[tuple[str, str]] = []

        async def _fake_search_hotels_and_activities(
            state_arg: GraphState, _plan_arg: TripPlan
        ) -> None:
            state_arg.tiles["hotels"] = [{"id": "hotel_1"}]
            state_arg.tiles["activities"] = [{"id": "act_1"}]

        async def _fake_resolve_iata_codes(origin: str, destination: str, _state: GraphState):
            resolve_calls.append((origin, destination))
            if origin:
                raise AssertionError(
                    "Flight refresh should not resolve origin when flights are excluded"
                )
            return "", "DPS"

        monkeypatch.setattr(
            logistics_module,
            "_search_hotels_and_activities",
            _fake_search_hotels_and_activities,
        )
        monkeypatch.setattr(logistics_module, "resolve_iata_codes", _fake_resolve_iata_codes)

        result = await logistics_module.logistics_node(state)

        assert result.metadata.get("flight_search_possible") is False
        assert result.metadata.get("flight_search_status") == "skipped_disabled"
        assert result.metadata.get("flight_skip_reason") == "flights_disabled_in_settings"
        assert result.tiles["flights"] == []
        assert resolve_calls == [("", "Bali")]

    @pytest.mark.asyncio
    async def test_logistics_starts_aviasales_fetch_before_hotel_activity_search_finishes(
        self, monkeypatch: Any
    ) -> None:
        import importlib

        from app.config import settings as app_settings

        logistics_module = importlib.import_module("app.planner.nodes.logistics_node")

        state = GraphState(
            trip_plan=TripPlan(
                destination="Bali",
                origin="Amsterdam",
                start_date="2026-04-01",
                end_date="2026-04-07",
                currency="USD",
            )
        )
        state.tiles = {"hotels": [], "activities": [], "flights": []}
        state.metadata.update(
            {
                "trip_settings": {
                    "booking_types": {
                        "flights": "suggested",
                        "hotels": "suggested",
                        "activities": "on",
                    },
                    "flight_settings": {"direct_only": False, "round_trip": True},
                    "hotel_settings": {"min_stars": 0, "amenities": []},
                    "activity_settings": {"categories": ["diving"]},
                },
                "allow_flight_auto_upgrade": False,
            }
        )

        order: list[str] = []
        flight_started = asyncio.Event()
        release_flights = asyncio.Event()

        async def _fake_search_hotels_and_activities(
            state_arg: GraphState, _plan_arg: TripPlan
        ) -> None:
            order.append("hotels_start")
            await asyncio.wait_for(flight_started.wait(), timeout=0.1)
            order.append("flight_started_before_hotels_end")
            state_arg.tiles["hotels"] = [{"id": "hotel_1"}]
            state_arg.tiles["activities"] = [{"id": "act_1"}]
            release_flights.set()
            order.append("hotels_end")

        async def _fake_resolve_iata_codes(origin: str, destination: str, _state: GraphState):
            return "AMS", "DPS"

        async def _fake_search_aviasales_flights(**kwargs: Any):
            from app.services.aviasales_provider import FlightSearchResult

            order.append("flight_start")
            flight_started.set()
            await asyncio.wait_for(release_flights.wait(), timeout=0.1)
            order.append("flight_end")
            return FlightSearchResult()

        monkeypatch.setattr(app_settings, "aviasales_enabled", True)
        monkeypatch.setattr(
            logistics_module,
            "_search_hotels_and_activities",
            _fake_search_hotels_and_activities,
        )
        monkeypatch.setattr(logistics_module, "resolve_iata_codes", _fake_resolve_iata_codes)
        monkeypatch.setattr(
            logistics_module,
            "search_aviasales_flights",
            _fake_search_aviasales_flights,
        )
        monkeypatch.setattr(logistics_module, "_get_mock_flights", lambda *_args, **_kwargs: [])

        await logistics_module.logistics_node(state)

        assert order.index("flight_start") < order.index("hotels_end")
        assert "flight_started_before_hotels_end" in order


class TestPostBuildPlacedActivityEnrichment:
    @pytest.mark.asyncio
    async def test_reuses_booked_tile_google_places_fields_without_provider_call(
        self, monkeypatch: Any
    ) -> None:
        import app.tile_service.google_places_provider as gp_module
        from app.config import settings as app_settings

        state = _make_state(
            trip_plan={"destination": "Bali"},
            tiles={"activities": []},
            session_id="session-123",
        )
        day_cards = [
            {
                "day_number": 1,
                "blocks": [
                    {
                        "summary": "Village walk",
                        "booked_tile": {
                            "title": "Secret Garden Village",
                            "google_place_id": "gp_secret",
                            "coordinates": {"lat": -8.5, "lng": 115.2},
                            "deeplink": "https://maps.test/secret-garden",
                            "image_url": "https://images.test/secret-garden.jpg",
                            "price_level": 2,
                        },
                    }
                ],
            }
        ]

        monkeypatch.setattr(app_settings, "use_google_places_provider", True)
        monkeypatch.setattr(app_settings, "google_places_enrichment_enabled", True)
        enrich_mock = AsyncMock(side_effect=AssertionError("provider should not be called"))
        monkeypatch.setattr(gp_module, "enrich_activities_with_places", enrich_mock)

        await _post_build_enrich_placed_activities(state, day_cards)

        block = day_cards[0]["blocks"][0]
        assert block["google_place_id"] == "gp_secret"
        assert block["coordinates"] == {"lat": -8.5, "lng": 115.2}
        assert block["deeplink"] == "https://maps.test/secret-garden"
        assert block["image_url"] == "https://images.test/secret-garden.jpg"
        assert block["price_level"] == 2
        enrich_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_prefers_booked_tile_title_for_cached_gp_reuse_when_summary_drifts(
        self, monkeypatch: Any
    ) -> None:
        import app.tile_service.google_places_provider as gp_module
        from app.config import settings as app_settings

        state = _make_state(
            trip_plan={"destination": "Bali"},
            tiles={
                "activities": [
                    {
                        "id": "browse_secret_garden",
                        "title": "Secret Garden Village",
                        "google_place_id": "gp_secret",
                        "coordinates": {"lat": -8.51, "lng": 115.21},
                        "deeplink": "https://maps.test/secret-garden",
                        "photo_name": "places/secret-garden/photo-1",
                        "price_level": 3,
                    }
                ]
            },
            session_id="session-123",
        )
        day_cards = [
            {
                "day_number": 1,
                "blocks": [
                    {
                        "summary": "Village walk",
                        "booked_tile": {"title": "Secret Garden Village"},
                    }
                ],
            }
        ]

        monkeypatch.setattr(app_settings, "use_google_places_provider", True)
        monkeypatch.setattr(app_settings, "google_places_enrichment_enabled", True)
        enrich_mock = AsyncMock(side_effect=AssertionError("provider should not be called"))
        monkeypatch.setattr(gp_module, "enrich_activities_with_places", enrich_mock)
        monkeypatch.setattr(
            gp_module,
            "build_signed_photo_url",
            lambda session_id, photo_name: f"signed://{session_id}/{photo_name}",
        )

        await _post_build_enrich_placed_activities(state, day_cards)

        block = day_cards[0]["blocks"][0]
        assert block["google_place_id"] == "gp_secret"
        assert block["coordinates"] == {"lat": -8.51, "lng": 115.21}
        assert block["deeplink"] == "https://maps.test/secret-garden"
        assert block["image_url"] == "signed://session-123/places/secret-garden/photo-1"
        assert block["price_level"] == 3
        enrich_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_ambiguous_cached_gp_title_reuse_and_queries_places(
        self, monkeypatch: Any
    ) -> None:
        import app.tile_service.google_places_provider as gp_module
        from app.config import settings as app_settings

        state = _make_state(
            trip_plan={"destination": "Bali", "adults": 2, "children": 0},
            tiles={
                "activities": [
                    {
                        "id": "secret_garden_a",
                        "title": "Secret Garden Village",
                        "google_place_id": "gp_a",
                        "coordinates": {"lat": -8.50, "lng": 115.20},
                    },
                    {
                        "id": "secret_garden_b",
                        "title": "Secret Garden Village",
                        "google_place_id": "gp_b",
                        "coordinates": {"lat": -8.60, "lng": 115.30},
                    },
                ]
            },
            session_id="session-123",
        )
        day_cards = [
            {
                "day_number": 1,
                "blocks": [{"summary": "Secret Garden Village"}],
            }
        ]

        monkeypatch.setattr(app_settings, "use_google_places_provider", True)
        monkeypatch.setattr(app_settings, "google_places_enrichment_enabled", True)
        enrich_mock = AsyncMock(
            return_value=[
                {
                    "id": "post_enrich_0_0",
                    "google_place_id": "gp_resolved",
                    "coordinates": {"lat": -8.55, "lng": 115.25},
                    "deeplink": "https://maps.test/resolved",
                    "meta": {"photo_name": "places/resolved/photo-1"},
                    "price_level": 1,
                }
            ]
        )
        monkeypatch.setattr(gp_module, "enrich_activities_with_places", enrich_mock)
        monkeypatch.setattr(
            gp_module,
            "build_signed_photo_url",
            lambda session_id, photo_name: f"signed://{session_id}/{photo_name}",
        )

        await _post_build_enrich_placed_activities(state, day_cards)

        block = day_cards[0]["blocks"][0]
        assert block["google_place_id"] == "gp_resolved"
        assert block["coordinates"] == {"lat": -8.55, "lng": 115.25}
        assert block["deeplink"] == "https://maps.test/resolved"
        assert block["image_url"] == "signed://session-123/places/resolved/photo-1"
        assert block["price_level"] == 1
        enrich_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_preserves_dict_coordinates_on_proxy_when_booked_tile_lacks_place_id(
        self, monkeypatch: Any
    ) -> None:
        import app.tile_service.google_places_provider as gp_module
        from app.config import settings as app_settings

        state = _make_state(
            trip_plan={"destination": "Bali", "adults": 1, "children": 0},
            tiles={"activities": []},
            session_id="session-123",
        )
        day_cards = [
            {
                "day_number": 1,
                "blocks": [
                    {
                        "summary": "Cliff walk",
                        "booked_tile": {
                            "title": "Uluwatu Cliff Walk",
                            "coordinates": {"lat": -8.829, "lng": 115.084},
                        },
                    }
                ],
            }
        ]
        captured_proxies: list[dict[str, Any]] = []

        async def _fake_enrich(
            proxies: list[dict[str, Any]],
            *_args: Any,
            **_kwargs: Any,
        ) -> list[dict[str, Any]]:
            captured_proxies.extend(proxies)
            return []

        monkeypatch.setattr(app_settings, "use_google_places_provider", True)
        monkeypatch.setattr(app_settings, "google_places_enrichment_enabled", True)
        monkeypatch.setattr(gp_module, "enrich_activities_with_places", _fake_enrich)

        await _post_build_enrich_placed_activities(state, day_cards)

        assert captured_proxies == [
            {
                "id": "post_enrich_0_0",
                "title": "Uluwatu Cliff Walk",
                "coordinates": [115.084, -8.829],
                "photo_name": None,
                "image_url": None,
                "meta": {},
            }
        ]


class TestBuildTripStateSummary:
    def test_basic_summary(self) -> None:
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
                "adults": 2,
                "budget": 5000,
            },
            trip_settings={"activity_settings": {"categories": ["diving"]}},
        )
        summary = build_trip_state_summary(state)
        assert summary["destination"] == "Bali"
        assert summary["adults"] == 2
        assert summary["budget"] == 5000
        assert "diving" in summary["categories"]

    def test_empty_state(self) -> None:
        summary = build_trip_state_summary(_make_state())
        assert summary["destination"] is None
        assert summary["categories"] == []
        assert summary["has_itinerary"] is False


class TestSpecialistContentToTiles:
    """Tests for converting specialist content_added items to tile dicts."""

    def test_basic_tile_shape(self) -> None:
        """Converted tile has all required fields matching experience tile shape."""
        section = {
            "content_added": [
                {
                    "title": "USAT Liberty Wreck",
                    "description": "Famous WWII shipwreck dive",
                    "duration_hours": 3.0,
                    "day": 2,
                    "coordinates": [115.59, -8.28],
                    "intensity": "moderate",
                }
            ],
        }
        tiles = _specialist_content_to_tiles("diving", section, "Bali")

        assert len(tiles) == 1
        tile = tiles[0]
        assert tile["id"].startswith("spec_bali_diving_")
        assert tile["type"] == "activity"
        assert tile["source_agent"] == "vertical_specialist"
        assert tile["title"] == "USAT Liberty Wreck"
        assert tile["tags"] == ["activity", "diving", "specialist"]
        assert tile["meta"]["specialist_type"] == "diving"
        assert tile["meta"]["preferred_day"] == 2
        assert tile["meta"]["duration_hours"] == 3.0
        assert tile["geo"] == {"lng": 115.59, "lat": -8.28}

    def test_deterministic_ids(self) -> None:
        """Same topic + title always produces the same tile ID."""
        section = {"content_added": [{"title": "Manta Point"}]}
        tiles_a = _specialist_content_to_tiles("diving", section, "Bali")
        tiles_b = _specialist_content_to_tiles("diving", section, "Bali")
        assert tiles_a[0]["id"] == tiles_b[0]["id"]

    def test_different_titles_different_ids(self) -> None:
        """Different titles produce different tile IDs."""
        section = {
            "content_added": [
                {"title": "Manta Point"},
                {"title": "USAT Liberty Wreck"},
            ]
        }
        tiles = _specialist_content_to_tiles("diving", section, "Bali")
        assert len(tiles) == 2
        assert tiles[0]["id"] != tiles[1]["id"]

    def test_skips_buffer_items(self) -> None:
        """Buffer items (is_buffer=True) are not converted to tiles."""
        section = {
            "content_added": [
                {"title": "Dive Day", "is_buffer": False},
                {"title": "Safety Buffer", "is_buffer": True},
            ]
        }
        tiles = _specialist_content_to_tiles("diving", section, "Bali")
        assert len(tiles) == 1
        assert tiles[0]["title"] == "Dive Day"

    def test_skips_empty_titles(self) -> None:
        """Items with no title are skipped."""
        section = {"content_added": [{"title": ""}, {"title": "Real Activity"}]}
        tiles = _specialist_content_to_tiles("diving", section, "Bali")
        assert len(tiles) == 1

    def test_empty_content_returns_empty(self) -> None:
        """No content_added returns empty list."""
        tiles = _specialist_content_to_tiles("diving", {"content_added": []}, "Bali")
        assert tiles == []

    def test_no_coordinates_empty_geo(self) -> None:
        """Missing coordinates serialize as absent geo coordinates."""
        section = {"content_added": [{"title": "Reef Dive"}]}
        tiles = _specialist_content_to_tiles("diving", section, "Bali")
        assert tiles[0]["geo"] is None

    def test_destination_slug_normalization(self) -> None:
        """Destination with spaces/commas gets slugified in tile ID."""
        section = {"content_added": [{"title": "Trail Run"}]}
        tiles = _specialist_content_to_tiles("hiking", section, "Rome, Italy")
        assert tiles[0]["id"].startswith("spec_rome_italy_hiking_")
