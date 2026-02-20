"""
D12 regression tests for constraint_guard merge logic.

Tests cover:
- D6/D12: Guard merge skips constraints from specialists no longer in active categories
- Active specialist constraints are correctly merged and applied

These tests call the constraint_guard node directly with pre-built state.
No LLM calls (guard is pure Python). Async tests use pytest-asyncio.
"""

from __future__ import annotations

import pytest

from app.planner.nodes.constraint_guard import constraint_guard
from app.planner.state.graph_state import (
    GraphState,
    SpecialistConstraint,
    TripPlan,
)

# =============================================================================
# Helpers
# =============================================================================


def _make_guard_state(
    destination: str = "Bali",
    start_date: str = "2026-06-01",
    end_date: str = "2026-06-08",
    budget: float | None = None,
    specialist_constraints: dict | None = None,
    trip_plan_constraints: list[SpecialistConstraint] | None = None,
    executed_topics: list[str] | None = None,
) -> GraphState:
    """Build a GraphState for constraint guard tests."""
    state = GraphState(
        trip_plan=TripPlan(
            destination=destination,
            start_date=start_date,
            end_date=end_date,
            budget=budget,
        )
    )
    if specialist_constraints:
        state.metadata["specialist_constraints"] = specialist_constraints
    if trip_plan_constraints:
        state.trip_plan.constraints = list(trip_plan_constraints)
    if executed_topics:
        state.metadata["executed_strategy_topics"] = list(executed_topics)
    return state


# =============================================================================
# D6/D12 — Guard merge skips removed-specialist constraints
# =============================================================================


class TestConstraintMerge:
    """Guard merge behaviour: active constraints in, pruned constraints out."""

    @pytest.mark.asyncio
    async def test_guard_ignores_constraints_from_removed_specialists(self):
        """D6/D12: Guard merge skips constraints from specialists no longer active.

        When the router runs the category gate (D6), it removes diving from
        specialist_constraints. On the NEXT turn, the guard should NOT merge
        diving constraints back into trip_plan.constraints.

        This test simulates a state where the router has already pruned diving
        from specialist_constraints (the D6 fix). The guard should honour that
        and not re-inject the stale constraint.
        """
        # After D6 pruning: specialist_constraints has NO diving key
        state = _make_guard_state(
            destination="Bali",
            start_date="2026-06-01",
            end_date="2026-06-08",
            specialist_constraints={
                # Diving was removed by category gate — not present here
                "local_expert": [],
            },
            trip_plan_constraints=[],  # Empty — diving constraint was purged
            executed_topics=["local_expert"],
        )

        result = await constraint_guard(state)

        # Guard must not add back min_24h_buffer_after_dive since diving was removed
        constraint_rules = {c.rule for c in result.trip_plan.constraints}
        assert "min_24h_buffer_after_dive" not in constraint_rules, (
            "D6/D12: Guard must not merge diving constraints when diving "
            "is not in specialist_constraints"
        )

    @pytest.mark.asyncio
    async def test_guard_merges_constraints_from_active_specialists(self):
        """Active specialist constraints are correctly merged and present after guard runs.

        Simulates a state where trip_plan.constraints was cleared (e.g., after
        a session state reload) but specialist_constraints still holds the diving
        constraint. The guard should merge it back.
        """
        diving_constraint = {
            "type": "safety",
            "rule": "min_24h_buffer_after_dive",
            "constraint_id": "no_fly_24h",
            "severity": "blocking",
            "reason": "PADI Standard - 24h surface interval before flying",
        }

        state = _make_guard_state(
            destination="Bali",
            start_date="2026-06-01",
            end_date="2026-06-08",
            specialist_constraints={
                "diving": [diving_constraint],
            },
            # trip_plan.constraints is empty — simulates cleared state
            trip_plan_constraints=[],
            executed_topics=["diving", "local_expert"],
        )

        result = await constraint_guard(state)

        # Guard should have merged the diving constraint back from specialist_constraints
        constraint_rules = {c.rule for c in result.trip_plan.constraints}
        assert "min_24h_buffer_after_dive" in constraint_rules, (
            "D12: Guard should merge active specialist constraints from "
            "specialist_constraints metadata"
        )
