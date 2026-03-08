"""Coordinate/constraint helper tests for fill-day day-block mapping."""

from app.main import (
    _extract_day_block_coordinates,
    _first_trip_anchor_coordinates,
    _resolve_fill_day_block_constraints,
)
from app.schemas import DayBlock, DayCard, PlanDocumentData, Tile


def test_extract_coordinates_from_mapbox_array() -> None:
    coords = _extract_day_block_coordinates({}, {"coordinates": [55.2708, 25.2048]})
    assert coords == {"lat": 25.2048, "lng": 55.2708}


def test_extract_coordinates_from_lat_lng_dict() -> None:
    coords = _extract_day_block_coordinates({}, {"coordinates": {"lat": 34.05, "lng": -118.24}})
    assert coords == {"lat": 34.05, "lng": -118.24}


def test_extract_coordinates_from_tile_geo() -> None:
    coords = _extract_day_block_coordinates({"geo": {"lat": -8.65, "lon": 115.22}}, {})
    assert coords == {"lat": -8.65, "lng": 115.22}


def test_extract_coordinates_returns_none_when_unavailable() -> None:
    assert _extract_day_block_coordinates({}, {}) is None


def test_extract_coordinates_rejects_out_of_range_values() -> None:
    coords = _extract_day_block_coordinates({}, {"coordinates": [181, 91]})
    assert coords is None


def test_first_trip_anchor_coordinates_prefers_existing_day_blocks() -> None:
    doc_data = PlanDocumentData(
        day_cards=[
            DayCard(
                day_number=1,
                label="Day 1",
                blocks=[
                    DayBlock(
                        period="morning",
                        activity_type="Dive briefing",
                        summary="Dive briefing",
                        coordinates={"lat": -8.65, "lng": 115.22},
                    )
                ],
            )
        ]
    )

    coords = _first_trip_anchor_coordinates(doc_data)
    assert coords == {"lat": -8.65, "lng": 115.22}


def test_first_trip_anchor_coordinates_falls_back_to_tiles() -> None:
    doc_data = PlanDocumentData(
        tiles={
            "hotel_1": Tile(
                id="hotel_1",
                type="hotel",
                partner="mock",
                partner_product_id="h1",
                deeplink="",
                title="Hotel",
                currency="USD",
                geo={"lat": 25.2048, "lng": 55.2708},
            )
        }
    )

    coords = _first_trip_anchor_coordinates(doc_data)
    assert coords == {"lat": 25.2048, "lng": 55.2708}


def test_first_trip_anchor_coordinates_skips_invalid_day_block_coords() -> None:
    doc_data = PlanDocumentData(
        day_cards=[
            DayCard(
                day_number=1,
                label="Day 1",
                blocks=[
                    DayBlock(
                        period="morning",
                        activity_type="Dive briefing",
                        summary="Dive briefing",
                        coordinates={"lat": 999, "lng": 999},
                    )
                ],
            )
        ],
        tiles={
            "hotel_1": Tile(
                id="hotel_1",
                type="hotel",
                partner="mock",
                partner_product_id="h1",
                deeplink="",
                title="Hotel",
                currency="USD",
                geo={"lat": 25.2048, "lng": 55.2708},
            )
        },
    )

    coords = _first_trip_anchor_coordinates(doc_data)
    assert coords == {"lat": 25.2048, "lng": 55.2708}


def test_resolve_fill_day_block_constraints_includes_tier1_rules() -> None:
    constraints = _resolve_fill_day_block_constraints("diving", {})
    assert "min_24h_buffer_after_dive" in constraints
