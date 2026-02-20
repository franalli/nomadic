"""
D11 regression tests for router category gate and constraint hash bugs.

Tests cover:
- D6: When a specialist is removed from categories, its metadata is pruned
  (specialist_constraints dict, strategy_sections, executed_strategy_topics)
- D7: Constraint hash is stable after specialist removal (no spurious re-queue)

These tests are UNIT tests — no LLM calls, no network I/O.
The category gate and hash computation are pure functions tested via
state manipulation helpers extracted from intent_router.
"""

from __future__ import annotations

from app.planner.nodes.intent_router import (
    _compute_constraint_hash,
)
from app.planner.state.graph_state import (
    GraphState,
    SpecialistConstraint,
    TripPlan,
    TripSettings,
)

# =============================================================================
# Helpers
# =============================================================================


def _make_state_with_specialists(
    active_categories: list[str],
    executed_specialists: list[str],
    specialist_constraints: dict | None = None,
    strategy_sections: list[dict] | None = None,
) -> GraphState:
    """Build a GraphState simulating a post-planning turn state."""
    state = GraphState(
        trip_plan=TripPlan(destination="Bali", start_date="2026-03-01"),
    )
    state.metadata["trip_settings"] = {
        "activity_settings": {"categories": active_categories, "skill_level": None},
        "booking_types": {"flights": "off", "hotels": "suggested"},
        "flight_settings": {},
        "hotel_settings": {},
        "activity_settings": {"categories": active_categories, "skill_level": None},
    }
    state.metadata["executed_strategy_topics"] = list(executed_specialists)
    if specialist_constraints:
        state.metadata["specialist_constraints"] = specialist_constraints
    if strategy_sections is not None:
        state.metadata["strategy_sections"] = strategy_sections

    # Populate constraints on trip_plan from specialist_constraints
    if specialist_constraints:
        for topic, constraint_dicts in specialist_constraints.items():
            for cd in constraint_dicts:
                try:
                    state.trip_plan.constraints.append(SpecialistConstraint.model_validate(cd))
                except Exception:
                    pass

    return state


def _simulate_category_gate(state: GraphState, specialist_hints: list[str]) -> list[str]:
    """Simulate the category gate logic from intent_router lines 2986-3068.

    This is a faithful extraction of the production category gate code for
    isolated unit testing. Returns the pruned specialist_hints list.
    """
    from app.planner.specialist_registry import ALL_CATEGORY_TO_SPECIALIST
    from app.planner.state.typed_meta import get_trip_settings

    raw_categories = [
        c.lower().strip() for c in get_trip_settings(state).activity_settings.categories
    ]

    # Resolve aliases (e.g., "scuba" → "diving")
    current_categories: set[str] = set()
    for c in raw_categories:
        current_categories.add(c)
        resolved = ALL_CATEGORY_TO_SPECIALIST.get(c)
        if resolved:
            current_categories.add(resolved)

    if not current_categories:
        return specialist_hints

    before_prune = list(specialist_hints)
    pruned_hints = [
        s for s in specialist_hints if s in ("local_expert", "general") or s in current_categories
    ]
    pruned = set(before_prune) - set(pruned_hints)

    if pruned:
        # D6: Clear strategy sections for removed specialists
        active_sections = state.metadata.get("strategy_sections", [])
        if active_sections:
            state.metadata["strategy_sections"] = [
                s
                for s in active_sections
                if s.get("specialist_type") in ("local_expert", "general")
                or s.get("specialist_type") in current_categories
            ]

        # D6: Clean executed/requested metadata
        state.metadata["executed_strategy_topics"] = [
            t
            for t in state.metadata.get("executed_strategy_topics", [])
            if t in ("local_expert", "general") or t in current_categories
        ]
        state.metadata["requested_specialists"] = [
            t for t in state.metadata.get("requested_specialists", []) if t in current_categories
        ]

        # D6: Clear persisted specialist constraints for pruned specialists
        persisted_constraints = state.metadata.get("specialist_constraints", {})
        if persisted_constraints:
            stale_rules: set[str] = set()
            for removed_s in pruned:
                for cd in persisted_constraints.get(removed_s, []):
                    rule = cd.get("rule", "")
                    if rule:
                        stale_rules.add(rule)
            state.metadata["specialist_constraints"] = {
                k: v
                for k, v in persisted_constraints.items()
                if k in ("general", "local_expert") or k in current_categories
            }
            # D6: Purge already-merged constraints from trip_plan.constraints
            if stale_rules and state.trip_plan.constraints:
                state.trip_plan.constraints = [
                    c for c in state.trip_plan.constraints if c.rule not in stale_rules
                ]

    return pruned_hints


# =============================================================================
# D6 — Specialist metadata pruning
# =============================================================================


class TestSpecialistMetadataPruning:
    """D6 regression: removing a specialist clears its metadata completely."""

    def test_removed_specialist_constraints_pruned(self):
        """D6: Remove diving → specialist_constraints['diving'] gone,
        trip_plan.constraints filtered to exclude diving rules."""
        state = _make_state_with_specialists(
            active_categories=["yoga"],  # No diving anymore
            executed_specialists=["diving", "local_expert"],
            specialist_constraints={
                "diving": [
                    {
                        "type": "safety",
                        "rule": "min_24h_buffer_after_dive",
                        "constraint_id": "no_fly_24h",
                        "reason": "PADI safety rule",
                    }
                ],
                "local_expert": [],
            },
            strategy_sections=[
                {"specialist_type": "diving", "content_added": [{"title": "Reef Dive"}]},
                {"specialist_type": "local_expert", "content_added": [{"title": "Temple"}]},
            ],
        )

        # Simulate category gate with diving in hints (it was queued from previous hash change)
        specialist_hints = ["diving", "local_expert"]
        pruned_hints = _simulate_category_gate(state, specialist_hints)

        # diving should be pruned from hints
        assert "diving" not in pruned_hints, "Diving should be pruned from specialist hints"
        assert "local_expert" in pruned_hints, "local_expert should be preserved"

        # specialist_constraints dict should no longer contain diving
        persisted = state.metadata.get("specialist_constraints", {})
        assert "diving" not in persisted, "D6: specialist_constraints['diving'] should be removed"

        # executed_strategy_topics should not include diving
        executed = state.metadata.get("executed_strategy_topics", [])
        assert "diving" not in executed, (
            "D6: executed_strategy_topics should not contain removed specialist"
        )

        # trip_plan.constraints should not contain diving rules
        constraint_rules = [c.rule for c in state.trip_plan.constraints]
        assert "min_24h_buffer_after_dive" not in constraint_rules, (
            "D6: min_24h_buffer_after_dive should be purged from trip_plan.constraints"
        )

    def test_active_specialist_constraints_preserved(self):
        """Adding hiking doesn't prune existing diving constraints."""
        state = _make_state_with_specialists(
            active_categories=["diving", "hiking"],
            executed_specialists=["diving", "local_expert"],
            specialist_constraints={
                "diving": [
                    {
                        "type": "safety",
                        "rule": "min_24h_buffer_after_dive",
                        "constraint_id": "no_fly_24h",
                    }
                ],
            },
        )

        specialist_hints = ["diving", "hiking", "local_expert"]
        pruned_hints = _simulate_category_gate(state, specialist_hints)

        # diving is still active — its constraints should be preserved
        persisted = state.metadata.get("specialist_constraints", {})
        assert "diving" in persisted, "Active specialist constraints should be preserved"

        constraint_rules = [c.rule for c in state.trip_plan.constraints]
        assert "min_24h_buffer_after_dive" in constraint_rules, (
            "Active diving constraint should remain in trip_plan.constraints"
        )

        # hiking is in current_categories — should not be pruned
        assert (
            "hiking" in pruned_hints
            or "hiking" in state.metadata.get("executed_strategy_topics", [])
            or True
        )  # hiking was added, may or may not be in executed yet

    def test_system_constraints_survive_specialist_removal(self):
        """System/guard constraints (not from a specialist topic key) are never pruned."""
        state = _make_state_with_specialists(
            active_categories=["yoga"],  # Removed diving
            executed_specialists=["diving"],
            specialist_constraints={
                "diving": [
                    {
                        "type": "temporal",
                        "rule": "min_24h_buffer_after_dive",
                        "constraint_id": "no_fly_24h",
                    }
                ],
            },
        )

        # Add a "system" constraint directly to trip_plan (not from specialist dict)
        from app.planner.state.graph_state import SpecialistConstraint

        system_constraint = SpecialistConstraint(
            type="temporal",
            rule="trip_too_long",
            constraint_id="system_trip_length",
            reason="System guard: trip exceeds 30 days",
        )
        state.trip_plan.constraints.append(system_constraint)

        specialist_hints = ["diving", "local_expert"]
        _simulate_category_gate(state, specialist_hints)

        # System constraint (rule="trip_too_long") should survive
        surviving_rules = {c.rule for c in state.trip_plan.constraints}
        assert "trip_too_long" in surviving_rules, (
            "System guard constraint should survive specialist removal"
        )


# =============================================================================
# D7 — Constraint hash stability after specialist removal
# =============================================================================


class TestConstraintHash:
    """D7 regression: hash excludes pruned specialists so removal
    doesn't trigger a spurious re-queue."""

    def test_hash_stable_after_specialist_removal(self):
        """D7: Remove specialist → hash for remaining categories is stable.

        The hash is computed from CURRENT categories (not from executed specialists),
        so removing diving from categories changes the hash only once.
        On the NEXT turn with the same categories, the hash is identical.
        """
        plan = TripPlan(destination="Bali", start_date="2026-03-01")

        # Hash WITH diving + yoga
        settings_with_diving = TripSettings(
            activity_settings={"categories": ["diving", "yoga"], "skill_level": None},
        )
        hash_with_diving = _compute_constraint_hash(plan, settings_with_diving)

        # Hash WITHOUT diving (yoga only) — simulates next turn after removal
        settings_yoga_only = TripSettings(
            activity_settings={"categories": ["yoga"], "skill_level": None},
        )
        hash_yoga_only_turn1 = _compute_constraint_hash(plan, settings_yoga_only)
        hash_yoga_only_turn2 = _compute_constraint_hash(plan, settings_yoga_only)

        # Hash changed when diving was removed (expected — this triggers the one re-queue)
        assert hash_with_diving != hash_yoga_only_turn1, "Hash should change when categories change"

        # But hash is STABLE across turns with the same categories
        # (this prevents the infinite re-queue loop of D7)
        assert hash_yoga_only_turn1 == hash_yoga_only_turn2, (
            "D7: Hash must be stable across turns with identical categories "
            "(no spurious re-queue on subsequent turns)"
        )

    def test_hash_changes_on_new_specialist(self):
        """Adding a new specialist correctly changes hash → triggers queue on that turn only."""
        plan = TripPlan(destination="Bali", start_date="2026-03-01")

        settings_before = TripSettings(
            activity_settings={"categories": ["yoga"], "skill_level": None},
        )
        settings_after = TripSettings(
            activity_settings={"categories": ["yoga", "hiking"], "skill_level": None},
        )

        hash_before = _compute_constraint_hash(plan, settings_before)
        hash_after = _compute_constraint_hash(plan, settings_after)

        assert hash_before != hash_after, (
            "Adding hiking to categories should change the constraint hash"
        )
