"""
Bug-driven tests for intent_router.py pure functions.

Tests:
- _detect_specialists_from_activity_settings
- _compute_constraint_hash
- _clear_stale_specialist_content
"""

from __future__ import annotations

from app.planner.nodes.intent_router import (
    _clear_stale_specialist_content,
    _compute_constraint_hash,
    _detect_specialists_from_activity_settings,
)
from app.planner.state.graph_state import GraphState, TripPlan, TripSettings


def _make_state_with_categories(categories: list[str]) -> GraphState:
    """Build a GraphState with activity_settings.categories set."""
    state = GraphState()
    state.metadata["trip_settings"] = {
        "activity_settings": {"categories": categories},
    }
    return state


# =============================================================================
# 1. _detect_specialists_from_activity_settings
# =============================================================================


class TestDetectSpecialistsFromActivitySettings:
    """Tests for detecting specialist types from activity categories."""

    def test_detect_specialists_tier1_categories(self):
        """Tier 1 categories (diving, hiking) map to their specialist names."""
        state = _make_state_with_categories(["diving", "hiking"])
        result = _detect_specialists_from_activity_settings(state)

        assert "diving" in result, "Should detect diving specialist"
        assert "hiking" in result, "Should detect hiking specialist"

    def test_detect_specialists_tier2_categories(self):
        """Tier 2 categories (yoga, cooking) map to their category name as specialist."""
        state = _make_state_with_categories(["yoga", "cooking"])
        result = _detect_specialists_from_activity_settings(state)

        assert "yoga" in result, "Should detect yoga as Tier 2 specialist"
        assert "cooking" in result, "Should detect cooking as Tier 2 specialist"

    def test_empty_categories_returns_empty(self):
        """Empty categories produces no specialists."""
        state = _make_state_with_categories([])
        result = _detect_specialists_from_activity_settings(state)
        assert result == []

    def test_mixed_tier1_tier2(self):
        """Mixed Tier 1 + Tier 2 categories all detected."""
        state = _make_state_with_categories(["diving", "yoga"])
        result = _detect_specialists_from_activity_settings(state)

        assert "diving" in result
        assert "yoga" in result


# =============================================================================
# 2. _compute_constraint_hash
# =============================================================================


class TestComputeConstraintHash:
    """Tests for constraint hash computation (cache invalidation key)."""

    def test_constraint_hash_deterministic(self):
        """Same inputs produce the same hash."""
        plan = TripPlan(destination="Bali", start_date="2026-03-01")
        settings = TripSettings(
            activity_settings={"categories": ["diving", "hiking"], "skill_level": None},
        )

        hash1 = _compute_constraint_hash(plan, settings)
        hash2 = _compute_constraint_hash(plan, settings)
        assert hash1 == hash2

    def test_different_categories_different_hash(self):
        """Different categories produce different hashes."""
        plan = TripPlan(destination="Bali", start_date="2026-03-01")
        settings_a = TripSettings(
            activity_settings={"categories": ["diving"], "skill_level": None},
        )
        settings_b = TripSettings(
            activity_settings={"categories": ["hiking"], "skill_level": None},
        )

        hash_a = _compute_constraint_hash(plan, settings_a)
        hash_b = _compute_constraint_hash(plan, settings_b)
        assert hash_a != hash_b

    def test_constraint_hash_category_order_independent(self):
        """Category order does not affect the hash (sorted internally)."""
        plan = TripPlan(destination="Bali", start_date="2026-03-01")
        settings_ab = TripSettings(
            activity_settings={"categories": ["hiking", "diving"], "skill_level": None},
        )
        settings_ba = TripSettings(
            activity_settings={"categories": ["diving", "hiking"], "skill_level": None},
        )

        hash_ab = _compute_constraint_hash(plan, settings_ab)
        hash_ba = _compute_constraint_hash(plan, settings_ba)
        assert hash_ab == hash_ba

    def test_different_destination_different_hash(self):
        """Different destinations produce different hashes."""
        settings = TripSettings(
            activity_settings={"categories": ["diving"], "skill_level": None},
        )
        plan_a = TripPlan(destination="Bali", start_date="2026-03-01")
        plan_b = TripPlan(destination="Thailand", start_date="2026-03-01")

        assert _compute_constraint_hash(plan_a, settings) != _compute_constraint_hash(
            plan_b, settings
        )


# =============================================================================
# 3. _clear_stale_specialist_content
# =============================================================================


class TestClearStaleSpecialistContent:
    """Tests for clearing stale specialist data on constraint change."""

    def test_clear_stale_specialist_content(self):
        """After clearing, itinerary_blocks, constraints, and tiles are empty."""
        state = GraphState()
        # Populate with stale data
        from app.planner.state.graph_state import ItineraryBlock, SpecialistConstraint

        state.trip_plan.itinerary_blocks = [
            ItineraryBlock(
                day=1,
                title="Old dive",
                description="Stale",
                type="activity",
                source_specialist="diving",
            )
        ]
        state.trip_plan.constraints = [
            SpecialistConstraint(type="safety", rule="min_24h_buffer_after_dive")
        ]
        state.tiles = {
            "flights": [{"id": "f1"}],
            "activities": [{"id": "a1"}],
        }
        state.metadata["strategy_sections"] = [
            {"specialist_type": "diving", "content_added": [{"title": "Dive"}]}
        ]
        state.metadata["specialist_infeasible"] = True
        state.metadata["specialist_infeasible_reason"] = "Too far"
        state.metadata["specialist_alternative"] = "Try X"

        _clear_stale_specialist_content(state)

        assert state.trip_plan.itinerary_blocks == []
        assert state.trip_plan.constraints == []
        assert state.tiles == {}
        assert state.metadata.get("strategy_sections") == []
        assert "specialist_infeasible" not in state.metadata
        assert "specialist_infeasible_reason" not in state.metadata
        assert "specialist_alternative" not in state.metadata

    def test_clear_preserves_trip_plan_core_fields(self):
        """Clearing stale content preserves destination, dates, etc."""
        state = GraphState(
            trip_plan=TripPlan(
                destination="Bali",
                start_date="2026-03-01",
                end_date="2026-03-10",
                budget=5000.0,
            )
        )
        state.tiles = {"flights": [{"id": "old"}]}

        _clear_stale_specialist_content(state)

        assert state.trip_plan.destination == "Bali"
        assert state.trip_plan.start_date == "2026-03-01"
        assert state.trip_plan.end_date == "2026-03-10"
        assert state.trip_plan.budget == 5000.0
