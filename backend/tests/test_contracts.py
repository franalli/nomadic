"""Static schema-parity tests.

These verify that backend Pydantic models expose the fields the frontend
TypeScript interfaces depend on.  No DB, no LLM, no network -- pure
structural assertions.
"""

from __future__ import annotations

import typing

from app.schemas import DayBlock, DocumentTripInputs, PlanViewState, Tile

# ---------------------------------------------------------------------------
# PlanViewState literal values
# ---------------------------------------------------------------------------


def test_plan_view_state_values():
    """PlanViewState Literal includes all P*/S* values the frontend references."""
    values = set(typing.get_args(PlanViewState))

    # Core P* values
    for v in (
        "P0_MINIMAL",
        "P1_ENRICHED",
        "P2_LOGISTICS",
        "P3_FINALIZED",
        "P3_EDITING",
        "P3_BLOCKED",
    ):
        assert v in values, f"Missing PlanViewState value: {v}"

    # Legacy S* values still in use
    for v in (
        "S0_BOOTSTRAP",
        "S1_FRAMING",
        "S2_STRATEGY_READY",
        "S2_BLOCKED",
        "S3_ITINERARY_READY",
        "S3_EDITING",
        "S3_PARTIAL_CONFLICT",
        "S3_BLOCKED",
    ):
        assert v in values, f"Missing legacy PlanViewState value: {v}"


# ---------------------------------------------------------------------------
# DayBlock fields
# ---------------------------------------------------------------------------


def test_dayblock_has_frontend_fields():
    """DayBlock model has all fields the frontend DayBlock interface expects."""
    fields = set(DayBlock.model_fields.keys())
    required = {
        "id",
        "period",
        "activity_type",
        "summary",
        "is_buffer",
        "buffer_type",
        "buffer_reason",
        "specialist_type",
        "constraints",
        "deeplink",
        "duration",
        "rating",
        "price_level",
        "image_url",
        "coordinates",
        "google_place_id",
        "hotel_name",
        "booked_tile",
        "booking_category",
    }
    missing = required - fields
    assert not missing, f"DayBlock missing frontend fields: {missing}"


# ---------------------------------------------------------------------------
# DocumentTripInputs fields
# ---------------------------------------------------------------------------


def test_trip_inputs_has_core_fields():
    """DocumentTripInputs has all fields the frontend DocumentTripInputs type expects."""
    fields = set(DocumentTripInputs.model_fields.keys())
    required = {
        "destination",
        "origin",
        "start_date",
        "end_date",
        "adults",
        "children",
        "budget",
        "currency",
        "booking_types",
        "activity_settings",
        "missing_fields",
    }
    missing = required - fields
    assert not missing, f"DocumentTripInputs missing frontend fields: {missing}"


# ---------------------------------------------------------------------------
# Tile fields
# ---------------------------------------------------------------------------


def test_tile_has_frontend_fields():
    """Tile model has all fields the frontend Tile type expects."""
    fields = set(Tile.model_fields.keys())
    required = {
        "id",
        "type",
        "title",
        "deeplink_url",
        "price_estimate",
        "rating",
        "geo",
        "currency",
    }
    missing = required - fields
    assert not missing, f"Tile missing frontend fields: {missing}"
