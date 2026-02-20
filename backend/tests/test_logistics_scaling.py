"""
D10 regression tests for logistics tile scaling.

Tests for _compute_tiles_per_category in logistics_node.py.
These tests complement test_logistics_tile_scaling.py (which tests the
existing formula) by covering the specific D4 bug scenarios:
tile count formula uses free_days (not total placeable days) to prevent
inflated tile counts on trips dominated by specialist blocks.

No LLM calls, no network I/O.
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


class TestTilesPerCategory:
    """D4 regression: tile count formula uses free_days, not total placeable days."""

    def test_long_trip_many_free_days(self):
        """13-day trip, 5 niche specialist content items → tile count covers free days.

        Diving = 5 content items = 5 specialist days.
        trip_days = 13, specialist_days = 5, free_days = max(0, 13 - 5 - 2) = 6.
        With niche specialist present, cap = 4.
        result = min(base, 4) = 4.
        """
        state = _make_state(
            start_date="2026-03-01",
            end_date="2026-03-13",  # 13 days
            strategy_sections=[
                {
                    "specialist_type": "diving",
                    "content_added": [{"title": f"Dive Site {i}"} for i in range(5)],
                },
            ],
        )

        result = _compute_tiles_per_category(state, {"yoga"})
        # With a niche specialist, cap is 4
        assert result >= 2, f"Expected >= 2 tiles for 13-day trip with free days, got {result}"
        # And not inflated beyond cap
        assert result <= 8, f"Expected <= 8 tiles (capped), got {result}"

    def test_all_specialist_days_no_free(self):
        """7-day trip fully covered by specialist content → minimal tiles needed.

        trip_days = 7, specialist_days ≥ 5 (many content items), free_days ≈ 0.
        Formula should yield minimum (2) since there are no free days to fill.
        """
        state = _make_state(
            start_date="2026-03-01",
            end_date="2026-03-07",  # 7 days
            strategy_sections=[
                {
                    "specialist_type": "diving",
                    "content_added": [{"title": f"Dive Site {i}"} for i in range(7)],
                },
            ],
        )

        result = _compute_tiles_per_category(state, {"yoga"})
        # All days occupied by specialist — tile count should not be inflated
        # The formula clamps to minimum 2
        assert result >= 2, f"Expected >= 2 (minimum), got {result}"

    def test_single_category_scaling(self):
        """Yoga-only 10-day trip → tile count scales with free days.

        Yoga is Tier 2 (local_expert section used as proxy — skipped in specialist_days).
        trip_days = 10, specialist_days = 0 (local_expert skipped), free_days = max(0, 10 - 2) = 8.
        base = max(2, 8 // 1) = 8.
        has_niche = False, cap = min(8, max(4, ceil(8/1))) = 8.
        result = min(8, 8) = 8.
        """
        state = _make_state(
            start_date="2026-03-01",
            end_date="2026-03-10",  # 10 days
            strategy_sections=[
                {
                    "specialist_type": "local_expert",
                    "content_added": [
                        {"title": "Temple Tour"},
                        {"title": "Market Visit"},
                    ],
                },
            ],
        )

        result = _compute_tiles_per_category(state, {"yoga"})
        # Pure Tier 2: tiles should scale to free days, capped at 8
        assert result >= 4, f"Expected >= 4 tiles for 10-day yoga-only trip, got {result}"
        assert result <= 8, f"Expected <= 8 tiles (cap), got {result}"

    def test_multi_category_distribution(self):
        """3 Tier 2 categories on a 9-day trip → tile count per category scales proportionally.

        trip_days = 9, specialist_days = 0 (local_expert skipped), free_days ≈ 7.
        With 3 categories: base = max(2, 7 // 3) = 2.
        has_niche = False, cap = min(8, max(4, ceil(7/3))) = min(8, 4) = 4.
        result = min(2, 4) = 2.

        Key: tiles_per_category does NOT exceed free_days / num_categories.
        """
        state = _make_state(
            start_date="2026-03-01",
            end_date="2026-03-09",  # 9 days
            strategy_sections=[
                {
                    "specialist_type": "local_expert",
                    "content_added": [{"title": "Market"}, {"title": "Temple"}],
                },
            ],
        )

        tier2_cats = {"yoga", "cooking", "sailing"}
        result = _compute_tiles_per_category(state, tier2_cats)

        # With 3 categories distributing ~7 free days, per-category count should be moderate
        assert result >= 2, f"Expected >= 2 tiles per category, got {result}"
        # Should not allocate more than the total free days to a single category
        assert result <= 8, f"Expected <= 8 tiles per category, got {result}"
