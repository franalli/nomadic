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
    activities_per_day: int | None = None,
    categories: list[str] | None = None,
) -> GraphState:
    """Build a minimal GraphState for tile scaling tests."""
    state = GraphState(
        trip_plan=TripPlan(start_date=start_date, end_date=end_date),
    )
    if strategy_sections is not None:
        state.metadata["strategy_sections"] = strategy_sections
    activity_settings: dict = {}
    if activities_per_day is not None:
        activity_settings["activities_per_day"] = activities_per_day
    if categories is not None:
        activity_settings["categories"] = categories
    if activity_settings:
        state.metadata.setdefault("trip_settings", {})["activity_settings"] = activity_settings
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
        """Mixed diving + yoga: coverage floor lifts count to fill free days."""
        state = _make_state(
            start_date="2026-03-01",
            end_date="2026-03-10",
            strategy_sections=[
                {
                    "specialist_type": "diving",
                    "content_added": [{"title": "Reef Dive"}, {"title": "Wreck Dive"}],
                },
            ],
            categories=["diving"],
        )

        # specialist_days=2, free=6, total_placeable=8
        # apd=2: base=max(2,(8*2)//1)=16, cap=4 (specialist_days>0)
        # APD>1: needed=ceil(6*2/1)=12, tile_cap_ceiling=12, cap=12
        # tiles=min(16,12)=12
        result = _compute_tiles_per_category(state, {"yoga"})
        assert result == 12

    def test_single_category_short_trip_minimum_2(self):
        """4-day yoga trip, no specialist sections: coverage floor lifts count."""
        state = _make_state(
            start_date="2026-03-01",
            end_date="2026-03-04",
            strategy_sections=[],
        )

        # apd=2 (default): base=max(2,(2*2)//1)=4, cap=4, tiles=4
        # Coverage floor (1.5x): needed=ceil(2*2*1.5)=6, planned=4<6
        # min_needed=6, tiles=max(4,min(6,12))=6
        result = _compute_tiles_per_category(state, {"yoga"})
        assert result == 6

    # -----------------------------------------------------------------
    # APD > 1: Tile scaling must honour activities_per_day
    # -----------------------------------------------------------------

    def test_apd2_7day_pure_tier2_generates_enough_tiles(self):
        """7-day trip, APD=2, 1 category: 1.5x overprovision lifts to 12."""
        state = _make_state(
            start_date="2026-03-01",
            end_date="2026-03-07",
            strategy_sections=[],
            activities_per_day=2,
        )

        # trip_days = 7, specialist_days = 0
        # free_days = 7 - 0 - 2 = 5
        # total_placeable = 5
        # target_apd = 2
        # base = max(2, (5 * 2) // 1) = 10
        # cap = 4 (no strategy context, free_days <= 7)
        # APD>1: needed_per_cat = ceil(5 * 2 / 1) = 10 → cap = min(max(4, 10), 12) = 10
        # tiles = min(10, 10) = 10
        # Coverage floor (1.5x): needed=ceil(5*2*1.5)=15, planned=10<15
        # min_needed=15, tiles=max(10,min(15,12))=12
        result = _compute_tiles_per_category(state, {"yoga"})
        assert result == 12, f"Expected 12 tiles for 7-day APD=2 trip, got {result}"

    def test_apd2_mixed_tier1_tier2_scales_cap(self):
        """10-day mixed trip, APD=2: cap must scale beyond base 4."""
        state = _make_state(
            start_date="2026-03-01",
            end_date="2026-03-10",
            strategy_sections=[
                {
                    "specialist_type": "diving",
                    "content_added": [{"title": "Reef Dive"}, {"title": "Wreck Dive"}],
                },
            ],
            activities_per_day=2,
            categories=["diving"],
        )

        # trip_days = 10, specialist_days = 2
        # free_days = max(0, 10 - 2 - 2) = 6
        # total_placeable = 6 + 2 = 8
        # target_apd = 2
        # base = max(2, (8 * 2) // 1) = 16
        # cap = 4 (specialist_days > 0)
        # APD>1: needed_per_cat = ceil(6 * 2 / 1) = 12 → cap = min(max(4, 12), 12) = 12
        # result = min(16, 12) = 12
        result = _compute_tiles_per_category(state, {"yoga"})
        assert result == 12, f"Expected 12 tiles for mixed APD=2 trip, got {result}"

    def test_apd1_mixed_coverage_floor_fills_free_days(self):
        """APD=1 mixed trip: coverage floor lifts count to fill free days."""
        state = _make_state(
            start_date="2026-03-01",
            end_date="2026-03-10",
            strategy_sections=[
                {
                    "specialist_type": "diving",
                    "content_added": [{"title": "Reef Dive"}, {"title": "Wreck Dive"}],
                },
            ],
            activities_per_day=1,
            categories=["diving"],
        )

        # specialist_days=2, free=6, total_placeable=8
        # base = max(2, (8*1)//1) = 8, cap = 4 (specialist_days > 0)
        # APD=1: no needed lift. tiles = min(8, 4) = 4
        # Coverage floor (1.5x): needed=ceil(6*1*1.5)=9, planned=4<9
        # min_needed=ceil(9/1)=9, tiles=max(4,min(9,12))=9
        result = _compute_tiles_per_category(state, {"yoga"})
        assert result == 9, f"APD=1 mixed trip with coverage floor should be 9, got {result}"

    def test_apd2_multiple_tier2_categories(self):
        """APD=2, 3 Tier2 categories: cap must scale per-category for density."""
        state = _make_state(
            start_date="2026-03-01",
            end_date="2026-03-10",
            strategy_sections=[],
            activities_per_day=2,
            categories=["yoga", "cooking", "nightlife"],
        )

        # trip_days = 10, specialist_days = 0
        # free_days = max(0, 10 - 0 - 2) = 8
        # total_placeable = 8
        # target_apd = 2
        # base = max(2, (8 * 2) // 3) = max(2, 5) = 5
        # cap = min(8, max(4, ceil(8/3))) = min(8, 4) = 4
        # APD>1: needed_per_cat = ceil(8 * 2 / 3) = 6 → cap = min(max(4, 6), 12) = 6
        # result = min(5, 6) = 5
        result = _compute_tiles_per_category(state, {"yoga", "cooking", "nightlife"})
        assert result >= 5, f"Expected >= 5 tiles per cat for 3-cat APD=2 trip, got {result}"

    def test_apd3_long_horizon_capped_at_ceiling(self):
        """APD=3 on a 14-day trip: long free-day horizon caps at duration-aware ceiling."""
        state = _make_state(
            start_date="2026-03-01",
            end_date="2026-03-14",
            strategy_sections=[],
            activities_per_day=3,
        )

        # trip_days = 14, free_days = 12, total_placeable = 12
        # base = max(2, (12 * 3) // 1) = 36
        # needed_per_cat = ceil(12 * 3 / 1) = 36
        # tile_cap_ceiling = min(40, max(12, 12*2)) = 24
        # cap = min(max(cap, 36), 24) = 24
        # result = min(36, 24) = 24
        result = _compute_tiles_per_category(state, {"yoga"})
        assert result == 24, f"Should cap at duration-aware ceiling (24), got {result}"

    def test_apd3_boundary_free_days_7_caps_at_ceiling(self):
        """Boundary: free_days==7 caps at duration-aware ceiling."""
        state = _make_state(
            start_date="2026-03-01",
            end_date="2026-03-09",  # 9 days => free_days=7
            strategy_sections=[],
            activities_per_day=3,
        )

        # trip_days = 9, free_days = 7
        # tile_cap_ceiling = min(40, max(12, 7*2)) = 14
        # base = (7 * 3) = 21, needed_per_cat=21, cap=min(max(4,21),14)=14
        # result = min(21, 14) = 14
        result = _compute_tiles_per_category(state, {"yoga"})
        assert result == 14, f"Expected 14 at free_days=7 boundary, got {result}"

    def test_apd2_mixed_long_horizon_caps_at_ceiling(self):
        """Mixed Tier1+Tier2 long trips use the duration-aware ceiling."""
        state = _make_state(
            start_date="2026-03-01",
            end_date="2026-03-15",  # 15 days
            strategy_sections=[
                {
                    "specialist_type": "diving",
                    "content_added": [{"title": "Reef Dive"}, {"title": "Wreck Dive"}],
                },
            ],
            activities_per_day=2,
            categories=["diving"],
        )

        # specialist_days = 2, free_days = 15 - 2 - 2 = 11 (>7)
        # tile_cap_ceiling = min(40, max(12, 11*2)) = 22
        # cap starts at 4 (mixed) then APD raises to min(max(4,22),22)=22
        # base = (free+specialist)*2 = 13*2 = 26, result=min(26,22)=22
        result = _compute_tiles_per_category(state, {"yoga"})
        assert result == 22, f"Expected mixed long-horizon cap of 22, got {result}"
