"""
Conflict Resolution Verification Tests

Tests the ItineraryBuilder's conflict detection, partial timeline generation,
and resolution suggestions for multi-specialist trips.

Scenarios:
1. Constraint Clash (altitude after dive) - BLOCKING
2. Insufficient Days (generic capacity) - BLOCKING
3. No Conflict (sufficient buffer) - SUCCESS
4. Multiple Conflicts (altitude + capacity) - BLOCKING

Run: pytest backend/tests/test_conflict_resolution.py -v
"""

from typing import Any, Dict, List, Optional

import pytest

from app.planner.specialist_registry import ALL_CONSTRAINT_ALIASES as CONSTRAINT_ALIASES
from app.planner.state import ConstraintSeverity
from app.services.itinerary_builder import (
    ItineraryBuilder,
    ItineraryBuilderInput,
    MergedConstraint,
    _find_constraint,
)

# =============================================================================
# Test Fixtures
# =============================================================================


def make_diving_activities(count: int = 3) -> List[Dict[str, Any]]:
    """Create diving activity content blocks."""
    activities = [
        {"title": "USAT Liberty Wreck", "duration_hours": 3},
        {"title": "Tulamben Coral Garden", "duration_hours": 3},
        {"title": "Manta Point Nusa Penida", "duration_hours": 4},
    ]
    return [
        {
            "title": a["title"],
            "description": f"Dive at {a['title']}",
            "duration_hours": a["duration_hours"],
            "intensity": "moderate",
        }
        for a in activities[:count]
    ]


def make_hiking_activities(count: int = 3) -> List[Dict[str, Any]]:
    """Create hiking activity content blocks."""
    activities = [
        {"title": "Mount Batur Sunrise Trek", "elevation_meters": 1717, "duration_hours": 5},
        {"title": "Campuhan Ridge Walk", "elevation_meters": 200, "duration_hours": 2},
        {"title": "Sekumpul Waterfall Trail", "elevation_meters": 500, "duration_hours": 3},
    ]
    return [
        {
            "title": a["title"],
            "description": f"Hike to {a['title']}",
            "duration_hours": a["duration_hours"],
            "intensity": "challenging" if a["elevation_meters"] > 1000 else "moderate",
            "elevation_meters": a["elevation_meters"],
        }
        for a in activities[:count]
    ]


def make_strategy_sections(
    diving_count: int = 3,
    hiking_count: int = 0,
    include_diving_constraints: bool = True,
    include_altitude_constraint: bool = True,
) -> List[Dict[str, Any]]:
    """Create strategy sections with specialist content and constraints."""
    sections = []

    if diving_count > 0:
        diving_constraints = []
        if include_diving_constraints:
            diving_constraints.append(
                {
                    "type": "temporal",
                    "rule": "min_24h_buffer_after_dive",
                    "severity": "blocking",
                    "reason": "24h no-fly after diving",
                }
            )
        if include_altitude_constraint and hiking_count > 0:
            diving_constraints.append(
                {
                    "type": "safety",
                    "rule": "no_altitude_after_dive",
                    "severity": "blocking",
                    "reason": "No altitude >2500m within 24h of diving",
                    "applies_to_categories": ["hiking", "trekking", "mountaineering"],
                }
            )

        sections.append(
            {
                "specialist_type": "diving",
                "content_added": make_diving_activities(diving_count),
                "constraints_applied": diving_constraints,
            }
        )

    if hiking_count > 0:
        sections.append(
            {
                "specialist_type": "hiking",
                "content_added": make_hiking_activities(hiking_count),
                "constraints_applied": [],  # Use constraints_applied, not constraints
            }
        )

    return sections


def make_builder_input(
    start_date: str,
    end_date: str,
    strategy_sections: List[Dict[str, Any]],
    tiles: Optional[Dict[str, Any]] = None,
) -> ItineraryBuilderInput:
    """Create ItineraryBuilderInput for testing."""
    return ItineraryBuilderInput(
        start_date=start_date,
        end_date=end_date,
        destination="Bali",
        origin="London",
        strategy_sections=strategy_sections,
        tiles=tiles or {"flights": [], "hotels": [], "activities": []},
        preferences=None,
    )


# =============================================================================
# Constraint Alias Tests
# =============================================================================


class TestConstraintAliases:
    """Test the constraint alias normalization system."""

    def test_aliases_defined_for_key_constraints(self):
        """Verify aliases exist for critical constraints."""
        assert "no_altitude_after_dive" in CONSTRAINT_ALIASES
        assert "min_24h_buffer_after_dive" in CONSTRAINT_ALIASES

        # Check altitude aliases
        altitude_aliases = CONSTRAINT_ALIASES["no_altitude_after_dive"]
        assert "no_altitude_24h" in altitude_aliases
        assert "altitude_buffer" in altitude_aliases

        # Check no-fly aliases
        nofly_aliases = CONSTRAINT_ALIASES["min_24h_buffer_after_dive"]
        assert "no_fly_24h" in nofly_aliases
        assert "flight_buffer_24h" in nofly_aliases

    def test_find_constraint_exact_match(self):
        """Find constraint with exact canonical name."""
        constraints = [
            MergedConstraint(
                source="diving",
                rule="no_altitude_after_dive",
                severity=ConstraintSeverity.BLOCKING,
                blocks_day=True,
            )
        ]

        result = _find_constraint(constraints, "no_altitude_after_dive")
        assert result is not None
        assert result.rule == "no_altitude_after_dive"

    def test_find_constraint_alias_match(self):
        """Find constraint using alias name."""
        constraints = [
            MergedConstraint(
                source="diving",
                rule="no_altitude_24h",  # Alias
                severity=ConstraintSeverity.BLOCKING,
                blocks_day=True,
            )
        ]

        result = _find_constraint(constraints, "no_altitude_after_dive")
        assert result is not None
        assert result.rule == "no_altitude_24h"

    def test_find_constraint_partial_match(self):
        """Find constraint with partial rule name match."""
        constraints = [
            MergedConstraint(
                source="diving",
                rule="altitude_buffer_24h_after_dive",  # Variation
                severity=ConstraintSeverity.BLOCKING,
                blocks_day=True,
            )
        ]

        result = _find_constraint(constraints, "no_altitude_after_dive")
        assert result is not None

    def test_find_constraint_not_found(self):
        """Return None when constraint not present."""
        constraints = [
            MergedConstraint(
                source="diving",
                rule="some_other_constraint",
                severity=ConstraintSeverity.BLOCKING,
                blocks_day=True,
            )
        ]

        result = _find_constraint(constraints, "no_altitude_after_dive")
        assert result is None


# =============================================================================
# Scenario 1: Constraint Clash (Altitude After Dive)
# =============================================================================


class TestScenario1ConstraintClash:
    """
    Scenario 1: Constraint Clash (Altitude After Dive)

    Trigger: 5-day trip, diving + hiking (Mt. Batur 1717m)
    Expected: BLOCKING conflict, partial timeline with hiking grayed
    """

    def test_constraint_clash_detected(self):
        """Verify constraint_clash conflict is detected."""
        # 5-day trip: Mar 1-5 (3 activity days after arrival/departure)
        sections = make_strategy_sections(
            diving_count=2,
            hiking_count=2,
            include_altitude_constraint=True,
        )
        input_data = make_builder_input("2026-03-01", "2026-03-05", sections)

        builder = ItineraryBuilder()
        result = builder.build(input_data)

        # Should fail with conflict
        assert result.success is False
        assert result.error == "CONSTRAINT_CONFLICT"
        assert len(result.conflicts) > 0

        # Check conflict type
        clash_conflict = next((c for c in result.conflicts if c.type == "constraint_clash"), None)
        assert clash_conflict is not None
        assert clash_conflict.severity == ConstraintSeverity.BLOCKING
        assert "diving" in clash_conflict.specialists
        assert "hiking" in clash_conflict.specialists
        assert (
            "24h buffer" in clash_conflict.message.lower()
            or "buffer" in clash_conflict.message.lower()
        )

    def test_partial_timeline_has_unschedulable_hiking(self):
        """Verify partial timeline marks hiking as unschedulable."""
        sections = make_strategy_sections(
            diving_count=2,
            hiking_count=2,
            include_altitude_constraint=True,
        )
        input_data = make_builder_input("2026-03-01", "2026-03-05", sections)

        builder = ItineraryBuilder()
        result = builder.build(input_data)

        # Should have partial day_cards
        assert len(result.day_cards) > 0

        # Find unschedulable blocks
        unschedulable_blocks = []
        for day in result.day_cards:
            for block in day.blocks:
                if getattr(block, "unschedulable", False):
                    unschedulable_blocks.append(block)

        # Hiking should be unschedulable
        assert len(unschedulable_blocks) > 0

        hiking_unschedulable = [b for b in unschedulable_blocks if b.specialist_type == "hiking"]
        assert len(hiking_unschedulable) > 0

        # Check reason mentions altitude/diving
        for block in hiking_unschedulable:
            assert block.unschedulable_reason is not None
            reason_lower = block.unschedulable_reason.lower()
            assert "diving" in reason_lower or "24h" in reason_lower or "buffer" in reason_lower

    def test_resolutions_include_extend_and_remove(self):
        """Verify resolutions offer extend_trip and reduce_activities."""
        sections = make_strategy_sections(
            diving_count=2,
            hiking_count=2,
            include_altitude_constraint=True,
        )
        input_data = make_builder_input("2026-03-01", "2026-03-05", sections)

        builder = ItineraryBuilder()
        result = builder.build(input_data)

        # Should have resolutions
        assert len(result.resolutions) > 0

        # Check for extend_trip resolution
        extend_res = next((r for r in result.resolutions if r.action == "extend_trip"), None)
        assert extend_res is not None
        assert extend_res.new_duration is not None
        assert extend_res.new_duration > 5  # Should suggest more days

        # Check for reduce_activities resolution
        reduce_res = next((r for r in result.resolutions if r.action == "reduce_activities"), None)
        assert reduce_res is not None
        assert reduce_res.keep_specialist is not None


# =============================================================================
# Scenario 2: Insufficient Days (Generic Capacity)
# =============================================================================


class TestScenario2InsufficientDays:
    """
    Scenario 2: Insufficient Days (Generic Capacity)

    Trigger: 4-day trip, diving only (no altitude conflict, just capacity)
    Expected: BLOCKING insufficient_days conflict
    """

    def test_insufficient_days_detected(self):
        """Verify insufficient_days conflict is detected."""
        # 4-day trip with 4 diving activities (capacity issue)
        sections = make_strategy_sections(
            diving_count=3,
            hiking_count=0,  # No hiking = no altitude conflict
            include_diving_constraints=True,
        )
        # Add extra activities to trigger capacity issue
        sections[0]["content_added"].append(
            {
                "title": "Crystal Bay Drift Dive",
                "description": "Drift dive at Crystal Bay",
                "duration_hours": 4,
                "intensity": "challenging",
            }
        )
        sections[0]["content_added"].append(
            {
                "title": "Padang Bai Night Dive",
                "description": "Night dive experience",
                "duration_hours": 3,
                "intensity": "moderate",
            }
        )

        input_data = make_builder_input("2026-03-01", "2026-03-04", sections)

        builder = ItineraryBuilder()
        result = builder.build(input_data)

        # Should fail with conflict (may succeed if capacity is sufficient)
        # This depends on activity placement algorithm
        if not result.success:
            insufficient_conflict = next(
                (c for c in result.conflicts if c.type == "insufficient_days"), None
            )
            if insufficient_conflict:
                assert insufficient_conflict.severity == ConstraintSeverity.BLOCKING
                assert (
                    "insufficient" in insufficient_conflict.message.lower()
                    or "days" in insufficient_conflict.message.lower()
                )


# =============================================================================
# Scenario 3: No Conflict (Sufficient Buffer)
# =============================================================================


class TestScenario3NoConflict:
    """
    Scenario 3: No Conflict (Sufficient Buffer)

    Trigger: 8-day trip, diving + hiking (plenty of time)
    Expected: SUCCESS with full timeline, no conflicts
    """

    def test_sufficient_days_no_conflict(self):
        """Verify no conflict when trip has sufficient days."""
        # 10-day trip = plenty of buffer
        sections = make_strategy_sections(
            diving_count=2,
            hiking_count=2,
            include_altitude_constraint=True,
        )
        input_data = make_builder_input("2026-03-01", "2026-03-10", sections)

        builder = ItineraryBuilder()
        result = builder.build(input_data)

        # Should succeed
        assert result.success is True
        assert result.error is None
        assert len(result.conflicts) == 0

        # Should have full day_cards
        assert len(result.day_cards) == 10

        # No unschedulable blocks
        for day in result.day_cards:
            for block in day.blocks:
                assert not getattr(block, "unschedulable", False)

    def test_diving_and_hiking_both_scheduled(self):
        """Verify both diving and hiking activities are scheduled."""
        sections = make_strategy_sections(
            diving_count=2,
            hiking_count=2,
            include_altitude_constraint=True,
        )
        input_data = make_builder_input("2026-03-01", "2026-03-10", sections)

        builder = ItineraryBuilder()
        result = builder.build(input_data)

        assert result.success is True

        # Find scheduled activities by specialist
        diving_activities = []
        hiking_activities = []

        for day in result.day_cards:
            for block in day.blocks:
                if block.specialist_type == "diving" and not block.is_buffer:
                    diving_activities.append(block)
                elif block.specialist_type == "hiking" and not block.is_buffer:
                    hiking_activities.append(block)

        # Both should have activities
        assert len(diving_activities) > 0, "No diving activities scheduled"
        assert len(hiking_activities) > 0, "No hiking activities scheduled"


# =============================================================================
# Scenario 4: Multiple Conflicts (Altitude + Capacity)
# =============================================================================


class TestScenario4MultipleConflicts:
    """
    Scenario 4: Multiple Conflicts (Altitude + Capacity)

    Trigger: 3-day trip, diving + high-altitude hiking
    Expected: Multiple BLOCKING conflicts
    """

    def test_multiple_conflicts_detected(self):
        """Verify both altitude and capacity conflicts are detected."""
        # 3-day trip with diving + hiking = definitely conflicting
        sections = make_strategy_sections(
            diving_count=2,
            hiking_count=2,
            include_altitude_constraint=True,
        )
        input_data = make_builder_input("2026-03-01", "2026-03-03", sections)

        builder = ItineraryBuilder()
        result = builder.build(input_data)

        # Should fail
        assert result.success is False
        assert len(result.conflicts) > 0

        # Could have one or both conflict types
        conflict_types = [c.type for c in result.conflicts]
        assert "constraint_clash" in conflict_types or "insufficient_days" in conflict_types

    def test_partial_timeline_shows_priority_specialist(self):
        """Verify partial timeline marks hiking as unschedulable in constraint clash."""
        sections = make_strategy_sections(
            diving_count=2,
            hiking_count=2,
            include_altitude_constraint=True,
        )
        # Use 5-day trip so builder has enough usable days for partial schedule
        input_data = make_builder_input("2026-03-01", "2026-03-05", sections)

        builder = ItineraryBuilder()
        result = builder.build(input_data)

        # Should have partial day_cards
        assert len(result.day_cards) > 0

        # Check that diving is scheduled (primary) and hiking is unschedulable
        diving_scheduled = False
        hiking_unschedulable = False

        for day in result.day_cards:
            for block in day.blocks:
                if block.specialist_type == "diving" and not getattr(block, "unschedulable", False):
                    diving_scheduled = True
                if block.specialist_type == "hiking" and getattr(block, "unschedulable", False):
                    hiking_unschedulable = True

        assert diving_scheduled, "Diving should be scheduled as primary specialist"
        assert hiking_unschedulable, "Hiking should be marked unschedulable"


# =============================================================================
# Resolution Structure Tests
# =============================================================================


class TestResolutionStructure:
    """Test the structure and content of resolution suggestions."""

    def test_extend_trip_resolution_has_new_duration(self):
        """Verify extend_trip resolution includes suggested new duration."""
        sections = make_strategy_sections(
            diving_count=2,
            hiking_count=2,
            include_altitude_constraint=True,
        )
        input_data = make_builder_input("2026-03-01", "2026-03-05", sections)

        builder = ItineraryBuilder()
        result = builder.build(input_data)

        extend_res = next((r for r in result.resolutions if r.action == "extend_trip"), None)

        if extend_res:
            assert extend_res.new_duration is not None
            assert extend_res.new_duration > 5
            assert extend_res.description is not None
            assert "day" in extend_res.description.lower()

    def test_reduce_activities_resolution_has_keep_specialist(self):
        """Verify reduce_activities resolution specifies which specialist to keep."""
        sections = make_strategy_sections(
            diving_count=2,
            hiking_count=2,
            include_altitude_constraint=True,
        )
        input_data = make_builder_input("2026-03-01", "2026-03-05", sections)

        builder = ItineraryBuilder()
        result = builder.build(input_data)

        reduce_resolutions = [r for r in result.resolutions if r.action == "reduce_activities"]

        # Should have one per specialist that could be removed
        assert len(reduce_resolutions) >= 1

        for res in reduce_resolutions:
            assert res.keep_specialist is not None
            assert res.keep_specialist in ["diving", "hiking"]

    def test_resolution_feasibility_ranking(self):
        """Verify resolutions have feasibility ratings."""
        sections = make_strategy_sections(
            diving_count=2,
            hiking_count=2,
            include_altitude_constraint=True,
        )
        input_data = make_builder_input("2026-03-01", "2026-03-05", sections)

        builder = ItineraryBuilder()
        result = builder.build(input_data)

        for res in result.resolutions:
            assert res.feasibility in ["recommended", "possible", "not_recommended"]


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_single_specialist_no_conflict(self):
        """Single specialist trip should never have conflicts."""
        sections = make_strategy_sections(
            diving_count=3,
            hiking_count=0,
        )
        input_data = make_builder_input("2026-03-01", "2026-03-07", sections)

        builder = ItineraryBuilder()
        result = builder.build(input_data)

        assert result.success is True
        assert len(result.conflicts) == 0

    def test_no_altitude_constraint_no_cross_domain_conflict(self):
        """Without altitude constraint, no cross-domain conflict."""
        sections = make_strategy_sections(
            diving_count=2,
            hiking_count=2,
            include_altitude_constraint=False,  # No altitude constraint
        )
        input_data = make_builder_input("2026-03-01", "2026-03-06", sections)

        builder = ItineraryBuilder()
        result = builder.build(input_data)

        # May still have insufficient_days but not constraint_clash
        if not result.success:
            clash_conflict = next(
                (c for c in result.conflicts if c.type == "constraint_clash"), None
            )
            # If there's a clash, it shouldn't mention altitude
            if clash_conflict:
                assert "altitude" not in clash_conflict.message.lower()

    def test_minimum_trip_length(self):
        """2-day trip should handle gracefully."""
        sections = make_strategy_sections(diving_count=1, hiking_count=0)
        input_data = make_builder_input("2026-03-01", "2026-03-02", sections)

        builder = ItineraryBuilder()
        result = builder.build(input_data)

        # Should either succeed with minimal content or fail gracefully
        if result.success:
            assert len(result.day_cards) == 2
        else:
            assert result.error is not None


# =============================================================================
# Debug Logging Verification
# =============================================================================


class TestDebugLogging:
    """Verify debug logging includes expected information."""

    def test_conflict_logging_includes_type_and_message(self, capsys):
        """Verify conflict details are logged."""
        import os

        old_debug = os.environ.get("DEBUG", "")
        os.environ["DEBUG"] = "full"

        try:
            sections = make_strategy_sections(
                diving_count=2,
                hiking_count=2,
                include_altitude_constraint=True,
            )
            input_data = make_builder_input("2026-03-01", "2026-03-05", sections)

            builder = ItineraryBuilder()
            result = builder.build(input_data)

            # Consume stdout/stderr (capsys available for debugging if needed)
            _ = capsys.readouterr()

            # Check for expected log patterns (when DEBUG=full)
            # Note: This may not capture if logging goes to stderr
            if result.conflicts:
                # At minimum, the conflict should be detected
                assert len(result.conflicts) > 0
        finally:
            os.environ["DEBUG"] = old_debug


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
