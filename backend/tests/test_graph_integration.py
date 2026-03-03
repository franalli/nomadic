"""
Builder-level integration tests for ItineraryBuilder.build().

Tests exercise the full build pipeline (temporal scaffolding, constraint merge,
buffer injection, activity distribution, tile matching) without mocking.
No LLM calls, no network I/O. All assertions target structure, not NL content.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.services.itinerary_builder import (
    DayBlockOutput,
    DayCardOutput,
    ItineraryBuilder,
    ItineraryBuilderInput,
    PreferenceOverrideInput,
)

# =============================================================================
# Fixtures and helpers
# =============================================================================


@pytest.fixture
def builder() -> ItineraryBuilder:
    return ItineraryBuilder()


def _make_dive_input(days: int = 7) -> ItineraryBuilderInput:
    """7-day Bali diving input with 3 dive activities and min_24h_buffer_after_dive."""
    start = date(2026, 3, 15)
    end = start + timedelta(days=days - 1)
    return ItineraryBuilderInput(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        strategy_sections=[
            {
                "specialist_type": "diving",
                "content_added": [
                    {"title": "Tulamben Wall", "duration_hours": 3.0},
                    {"title": "Drop Off", "duration_hours": 3.0},
                    {"title": "Coral Garden", "duration_hours": 2.5},
                ],
                "constraints_applied": [
                    {"rule": "min_24h_buffer_after_dive", "reason": "PADI safety"},
                ],
            }
        ],
        tiles={},
        destination="Bali",
    )


def _make_multi_specialist_input(days: int = 8) -> ItineraryBuilderInput:
    """8-day trip with diving (2 activities + constraints) and hiking (2 activities)."""
    start = date(2026, 3, 15)
    end = start + timedelta(days=days - 1)
    return ItineraryBuilderInput(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        strategy_sections=[
            {
                "specialist_type": "diving",
                "content_added": [
                    {"title": "Liberty Wreck", "duration_hours": 3.0},
                    {"title": "Manta Point", "duration_hours": 3.0},
                ],
                "constraints_applied": [
                    {"rule": "min_24h_buffer_after_dive", "reason": "PADI safety"},
                    {"rule": "no_altitude_after_dive", "reason": "cross-domain buffer"},
                ],
            },
            {
                "specialist_type": "hiking",
                "content_added": [
                    {"title": "Mount Batur Sunrise", "duration_hours": 4.0},
                    {"title": "Campuhan Ridge Walk", "duration_hours": 2.5},
                ],
                "constraints_applied": [],
            },
        ],
        tiles={},
        destination="Bali",
    )


def _all_blocks(day_cards: list[DayCardOutput]) -> list[DayBlockOutput]:
    """Flatten all blocks from all day cards."""
    return [block for day in day_cards for block in day.blocks]


# =============================================================================
# Tests
# =============================================================================


class TestHappyPath:
    """Basic build succeeds and produces expected structure."""

    def test_happy_path_7day_diving(self, builder: ItineraryBuilder) -> None:
        """Build 7-day diving input -> 7 day_cards, all blocks have core fields,
        at least one diving block exists."""
        inp = _make_dive_input(days=7)
        result = builder.build(inp)

        assert result.success, f"Build failed: {result.error}"
        assert len(result.day_cards) == 7, f"Expected 7 day_cards, got {len(result.day_cards)}"

        blocks = _all_blocks(result.day_cards)
        assert len(blocks) > 0, "Expected at least one block across all days"

        # Every block must have id, period, and summary
        for block in blocks:
            assert getattr(block, "id", None) is not None, f"Block missing id: {block}"
            assert getattr(block, "period", None) is not None, f"Block missing period: {block}"
            assert getattr(block, "summary", None) is not None, f"Block missing summary: {block}"

        # At least one block has specialist_type == "diving"
        diving_blocks = [b for b in blocks if getattr(b, "specialist_type", None) == "diving"]
        assert len(diving_blocks) >= 1, "Expected at least 1 diving block"


class TestNoFlyBuffer:
    """Dive blocks carry surface_interval / no_fly constraint tags."""

    def test_nofly_buffer_before_departure(self, builder: ItineraryBuilder) -> None:
        """The last dive day's blocks should carry a no_fly_buffer or
        surface_interval active_constraint tag, OR a no_fly/rest_day buffer
        block should appear after the last dive day."""
        inp = _make_dive_input(days=7)
        result = builder.build(inp)

        assert result.success, f"Build failed: {result.error}"

        # Collect diving blocks (non-buffer) grouped by day
        dive_blocks_by_day: dict[int, list[DayBlockOutput]] = {}
        for day in result.day_cards:
            for block in day.blocks:
                if getattr(block, "specialist_type", None) == "diving" and not getattr(
                    block, "is_buffer", False
                ):
                    dive_blocks_by_day.setdefault(day.day_number, []).append(block)

        assert dive_blocks_by_day, "Should have at least one dive activity day"

        last_dive_day = max(dive_blocks_by_day.keys())
        last_dive_blocks = dive_blocks_by_day[last_dive_day]

        # Check 1: active_constraint tags on the last dive day's blocks
        has_constraint_tag = any(
            any(
                c.get("id") in ("no_fly_buffer", "surface_interval")
                for c in getattr(block, "active_constraints", [])
                if isinstance(c, dict)
            )
            for block in last_dive_blocks
        )

        # Check 2: buffer block after the last dive day
        has_buffer_after = False
        for day in result.day_cards:
            if day.day_number <= last_dive_day:
                continue
            for block in day.blocks:
                bt = getattr(block, "buffer_type", None)
                if bt in ("no_fly", "rest_day"):
                    has_buffer_after = True
                    break
            if has_buffer_after:
                break

        assert has_constraint_tag or has_buffer_after, (
            f"Last dive day {last_dive_day} should have no_fly_buffer/surface_interval "
            f"constraint tag on dive blocks OR a no_fly/rest_day buffer after it"
        )


class TestMultiSpecialistInterleaving:
    """Multiple specialist types are interleaved and buffers are injected."""

    def test_multi_specialist_interleaving(self, builder: ItineraryBuilder) -> None:
        """Both diving and hiking specialist_type appear in blocks, and at least
        one non-arrival/departure buffer block exists."""
        inp = _make_multi_specialist_input(days=8)
        result = builder.build(inp)

        assert result.success, f"Build failed: {result.error}"

        blocks = _all_blocks(result.day_cards)
        specialist_types = {getattr(b, "specialist_type", None) for b in blocks}

        assert "diving" in specialist_types, "Expected diving blocks"
        assert "hiking" in specialist_types, "Expected hiking blocks"

        # At least one buffer block that is NOT arrival/departure
        interior_buffers = [
            b
            for b in blocks
            if getattr(b, "is_buffer", False)
            and getattr(b, "buffer_type", None) not in ("arrival", "departure")
        ]
        assert len(interior_buffers) >= 1, (
            "Expected at least one interior buffer block (not arrival/departure)"
        )


class TestBlockSchemaCompleteness:
    """Every block has minimum required fields for frontend rendering."""

    def test_block_schema_completeness(self, builder: ItineraryBuilder) -> None:
        """Non-buffer blocks must have id, period, activity_type, summary.
        Buffer blocks must have buffer_type set."""
        inp = _make_dive_input(days=7)
        result = builder.build(inp)

        assert result.success, f"Build failed: {result.error}"

        for day in result.day_cards:
            for block in day.blocks:
                if not getattr(block, "is_buffer", False):
                    assert getattr(block, "id", None) is not None, (
                        f"Day {day.day_number}: non-buffer block missing id"
                    )
                    assert getattr(block, "period", None) is not None, (
                        f"Day {day.day_number}: non-buffer block missing period"
                    )
                    assert getattr(block, "activity_type", None) is not None, (
                        f"Day {day.day_number}: non-buffer block missing activity_type"
                    )
                    assert getattr(block, "summary", None) is not None, (
                        f"Day {day.day_number}: non-buffer block missing summary"
                    )
                else:
                    assert getattr(block, "buffer_type", None) is not None, (
                        f"Day {day.day_number}: buffer block missing buffer_type"
                    )


class TestHotelTilePropagation:
    """Hotel tiles propagate to day blocks as hotel_name."""

    def test_hotel_tile_propagation(self, builder: ItineraryBuilder) -> None:
        """When hotel tiles are provided, at least one block across all days
        has hotel_name set (not None, not empty)."""
        start = date(2026, 3, 15)
        end = start + timedelta(days=6)  # 7 days

        tiles = {
            "hotel_1": {
                "id": "hotel_1",
                "type": "hotel",
                "title": "Beach Resort Bali",
                "deeplink_url": "https://www.google.com/travel/hotels/Bali",
                "price_estimate": 120.0,
                "currency": "USD",
            }
        }

        inp = ItineraryBuilderInput(
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            strategy_sections=[
                {
                    "specialist_type": "diving",
                    "content_added": [
                        {"title": "Tulamben Wall", "duration_hours": 3.0},
                        {"title": "Drop Off", "duration_hours": 3.0},
                    ],
                    "constraints_applied": [
                        {"rule": "min_24h_buffer_after_dive", "reason": "PADI safety"},
                    ],
                }
            ],
            tiles=tiles,
            destination="Bali",
            preferences=PreferenceOverrideInput(
                preferred_hotel_ids=["hotel_1"],
            ),
        )

        result = builder.build(inp)
        assert result.success, f"Build failed: {result.error}"

        blocks = _all_blocks(result.day_cards)
        blocks_with_hotel = [
            b
            for b in blocks
            if getattr(b, "hotel_name", None) and str(getattr(b, "hotel_name", "")).strip()
        ]
        assert len(blocks_with_hotel) >= 1, (
            "Expected at least 1 block with hotel_name set when hotel tiles provided"
        )


class TestDeeplinkPropagation:
    """Activities get deeplink URLs for Google Maps integration."""

    def test_deeplink_propagation(self, builder: ItineraryBuilder) -> None:
        """When activity tiles with deeplinks are provided, at least one
        non-buffer block inherits a deeplink field."""
        start = date(2026, 3, 15)
        end = start + timedelta(days=6)  # 7 days

        tiles = {
            "act_1": {
                "id": "act_1",
                "type": "activity",
                "title": "Tulamben Wall Dive",
                "deeplink_url": "https://www.google.com/maps/search/Tulamben+Wall+Bali",
                "price_estimate": 50.0,
                "currency": "USD",
                "tags": ["diving"],
            }
        }

        inp = ItineraryBuilderInput(
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            strategy_sections=[
                {
                    "specialist_type": "diving",
                    "content_added": [
                        {"title": "Tulamben Wall", "duration_hours": 3.0},
                        {"title": "Drop Off", "duration_hours": 3.0},
                        {"title": "Coral Garden", "duration_hours": 2.5},
                    ],
                    "constraints_applied": [
                        {"rule": "min_24h_buffer_after_dive", "reason": "PADI safety"},
                    ],
                }
            ],
            tiles=tiles,
            destination="Bali",
        )

        result = builder.build(inp)
        assert result.success, f"Build failed: {result.error}"

        blocks = _all_blocks(result.day_cards)
        blocks_with_deeplink = [
            b
            for b in blocks
            if not getattr(b, "is_buffer", False)
            and getattr(b, "deeplink", None)
            and str(getattr(b, "deeplink", "")).strip()
        ]
        assert len(blocks_with_deeplink) >= 1, (
            "Expected at least 1 non-buffer block with a deeplink set"
        )
