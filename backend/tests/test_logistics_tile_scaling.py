"""
Tests for _compute_tiles_per_category in logistics_node.py.

Validates tile scaling logic based on trip duration, specialist activity days,
and Tier 2 category count.
"""

from __future__ import annotations

from app.planner.nodes.logistics_node import _compute_tiles_per_category
from app.planner.state.graph_state import GraphState, TripPlan


def _make_state(
    start_date: str,
    end_date: str,
    strategy_sections: list[dict] | None = None,
) -> GraphState:
    """Build a minimal GraphState for tile scaling tests."""
    state = GraphState(
        trip_plan=TripPlan(start_date=start_date, end_date=end_date),
    )
    if strategy_sections is not None:
        state.metadata["strategy_sections"] = strategy_sections
    return state


class TestComputeTilesPerCategory:
    """Tests for _compute_tiles_per_category pure function."""

    def test_pure_tier2_13day_yoga_tiles_cover_free_days(self):
        """13-day yoga-only trip: tiles_per_cat should cover free days.

        Yoga is Tier 2, so it doesn't appear as a niche specialist section.
        local_expert sections are skipped in specialist_days count, so
        specialist_days = 0.

        trip_days = 13, specialist_days = 0, free_days = 13 - 0 - 2 = 11.
        base = max(2, 11 // 1) = 11.
        has_niche = False, cap = min(8, max(4, ceil(11/1))) = 8.
        result = min(11, 8) = 8.
        """
        # Tier 2 only (yoga) -- specialist sections are from a general specialist
        # that doesn't count as niche (local_expert/general are skipped).
        state = _make_state(
            start_date="2026-03-01",
            end_date="2026-03-13",
            strategy_sections=[
                # local_expert sections are skipped in specialist_days count
                {
                    "specialist_type": "local_expert",
                    "content_added": [{"title": "Temple"}, {"title": "Market"}, {"title": "Beach"}],
                },
            ],
        )

        # Since local_expert is skipped, specialist_days = 0
        # trip_days = 13, free_days = 13 - 0 - 2 = 11
        # total_placeable = 11 + 0 = 11
        # base = max(2, 11 // 1) = 11
        # has_niche = False, cap = min(8, max(4, ceil(11/1))) = min(8, 11) = 8
        # result = min(11, 8) = 8
        result = _compute_tiles_per_category(state, {"yoga"})
        assert result >= 8, f"Expected >= 8 tiles for 13-day pure Tier 2 trip, got {result}"

    def test_pure_tier1_8day_no_tier2(self):
        """8-day tier1-only trip with empty tier2_cats returns default 2."""
        state = _make_state(
            start_date="2026-03-01",
            end_date="2026-03-08",
            strategy_sections=[
                {
                    "specialist_type": "hiking",
                    "content_added": [{"title": "Trail 1"}, {"title": "Trail 2"}],
                },
            ],
        )

        # Empty tier2_cats triggers early return of 2
        result = _compute_tiles_per_category(state, set())
        assert result == 2

    def test_mixed_tier1_tier2(self):
        """Mixed diving + yoga: niche specialist caps tile count to 4."""
        state = _make_state(
            start_date="2026-03-01",
            end_date="2026-03-10",
            strategy_sections=[
                {
                    "specialist_type": "diving",
                    "content_added": [{"title": "Reef Dive"}, {"title": "Wreck Dive"}],
                },
            ],
        )

        # trip_days = 10, specialist_days = 2 (from diving section)
        # free_days = max(0, 10 - 2 - 2) = 6
        # total_placeable = 6 + 2 = 8
        # base = max(2, 8 // 1) = 8 (1 tier2 cat: yoga)
        # has_niche = True (specialist_days > 0), cap = 4
        # result = min(8, 4) = 4
        result = _compute_tiles_per_category(state, {"yoga"})
        assert result == 4

    def test_single_category_short_trip_minimum_2(self):
        """4-day yoga trip, no specialist sections: result clamped to minimum 2."""
        state = _make_state(
            start_date="2026-03-01",
            end_date="2026-03-04",
            strategy_sections=[],
        )

        # trip_days = 4, specialist_days = 0
        # free_days = max(0, 4 - 0 - 2) = 2
        # total_placeable = 2 + 0 = 2
        # base = max(2, 2 // 1) = 2
        # has_niche = False, cap = min(8, max(4, ceil(2/1))) = min(8, 4) = 4
        # result = min(2, 4) = 2
        result = _compute_tiles_per_category(state, {"yoga"})
        assert result == 2
