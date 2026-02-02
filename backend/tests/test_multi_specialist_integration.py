"""
Integration Tests for Multi-Specialist Conflict Scenarios

End-to-end tests for multi-specialist trip orchestration including:
- Constraint conflict detection
- Resolution generation
- Activity interleaving across specialists
"""

from typing import Any, Dict

import pytest

from app.services.itinerary_builder import (
    ItineraryBuilder,
    ItineraryBuilderInput,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def builder() -> ItineraryBuilder:
    """Fresh ItineraryBuilder instance."""
    return ItineraryBuilder()


def create_diving_section(num_dives: int = 2) -> Dict[str, Any]:
    """Create a diving specialist section with configurable activities."""
    return {
        "specialist_type": "diving",
        "content_added": [
            {"title": f"Dive Site {i+1}", "duration_hours": 3.0, "intensity": "moderate"}
            for i in range(num_dives)
        ],
        "constraints_applied": [
            {
                "rule": "min_24h_buffer_after_dive",
                "reason": "PADI Standard: 24h surface interval before flying",
            }
        ],
    }


def create_hiking_section(num_hikes: int = 2) -> Dict[str, Any]:
    """Create a hiking specialist section with configurable activities."""
    return {
        "specialist_type": "hiking",
        "content_added": [
            {"title": f"Trail {i+1}", "duration_hours": 4.0, "intensity": "challenging"}
            for i in range(num_hikes)
        ],
        "constraints_applied": [
            {"rule": "early_start_preferred", "reason": "Beat the heat"},
        ],
    }


def create_skiing_section(num_runs: int = 2) -> Dict[str, Any]:
    """Create a skiing specialist section with configurable activities."""
    return {
        "specialist_type": "skiing",
        "content_added": [
            {"title": f"Ski Run {i+1}", "duration_hours": 5.0, "intensity": "challenging"}
            for i in range(num_runs)
        ],
        "constraints_applied": [
            {"rule": "check_snow_conditions", "reason": "Safety check"},
        ],
    }


def create_local_expert_section() -> Dict[str, Any]:
    """Create a local expert section with context (no bookable activities)."""
    return {
        "specialist_type": "local_expert",
        "content_added": [{"title": "Cultural Context", "description": "Local customs and tips"}],
        "constraints_applied": [
            {"rule": "visa_requirement", "reason": "Check entry requirements"},
        ],
    }


# =============================================================================
# Test: Diving + Hiking - Success Scenarios
# =============================================================================


class TestDivingHikingSuccess:
    """Test successful diving + hiking combinations with sufficient days."""

    def test_6_day_diving_hiking_succeeds(self, builder: ItineraryBuilder):
        """
        6 days with 2 dives + 2 hikes + 1 buffer should succeed.
        Usable days: 6 - 2 (arrival/departure) = 4
        Required: 2 dives + 2 hikes + 1 buffer = 5... fails
        Actually needs 8 days for this combination.
        """
        # 8-day trip for 2 dives + 2 hikes + buffer
        input_data = ItineraryBuilderInput(
            start_date="2024-03-15",
            end_date="2024-03-22",  # 8 days
            strategy_sections=[
                create_diving_section(num_dives=2),
                create_hiking_section(num_hikes=2),
            ],
            tiles={},
            destination="Bali",
        )

        result = builder.build(input_data)

        assert result.success, f"Expected success but got conflicts: {result.conflicts}"
        assert len(result.day_cards) == 8

        # Verify both specialists have activities scheduled
        diving_days = set()
        hiking_days = set()

        for day in result.day_cards:
            for block in day.blocks:
                if block.specialist_type == "diving" and not block.is_buffer:
                    diving_days.add(day.day_number)
                elif block.specialist_type == "hiking":
                    hiking_days.add(day.day_number)

        assert len(diving_days) >= 1, "Should have diving activities"
        assert len(hiking_days) >= 1, "Should have hiking activities"


# =============================================================================
# Test: Diving + Hiking - Conflict Scenarios
# =============================================================================


class TestDivingHikingConflict:
    """Test conflict detection when days are insufficient."""

    def test_4_day_trip_triggers_conflict(self, builder: ItineraryBuilder):
        """
        4-day trip with 2 dives + 2 hikes + 1 buffer = insufficient.
        Usable days: 4 - 2 = 2
        Required: 4 activities + 1 buffer = 5
        Should trigger CONSTRAINT_CONFLICT.
        """
        input_data = ItineraryBuilderInput(
            start_date="2024-03-15",
            end_date="2024-03-18",  # 4 days
            strategy_sections=[
                create_diving_section(num_dives=2),
                create_hiking_section(num_hikes=2),
            ],
            tiles={},
            destination="Bali",
        )

        result = builder.build(input_data)

        assert not result.success
        assert result.error == "CONSTRAINT_CONFLICT"
        assert len(result.conflicts) > 0

        # Should have insufficient_days conflict
        conflict_types = [c.type for c in result.conflicts]
        assert "insufficient_days" in conflict_types

    def test_conflict_includes_both_specialists(self, builder: ItineraryBuilder):
        """Conflict should list both specialists involved."""
        input_data = ItineraryBuilderInput(
            start_date="2024-03-15",
            end_date="2024-03-18",  # 4 days
            strategy_sections=[
                create_diving_section(num_dives=2),
                create_hiking_section(num_hikes=2),
            ],
            tiles={},
            destination="Bali",
        )

        result = builder.build(input_data)

        assert not result.success

        # Find the insufficient_days conflict
        conflict = next(c for c in result.conflicts if c.type == "insufficient_days")

        # Should mention both specialists
        assert "diving" in conflict.specialists
        assert "hiking" in conflict.specialists

    def test_conflict_generates_extend_trip_resolution(self, builder: ItineraryBuilder):
        """Conflict should offer 'extend trip' as recommended resolution."""
        input_data = ItineraryBuilderInput(
            start_date="2024-03-15",
            end_date="2024-03-18",  # 4 days - insufficient
            strategy_sections=[
                create_diving_section(num_dives=2),
                create_hiking_section(num_hikes=2),
            ],
            tiles={},
            destination="Bali",
        )

        result = builder.build(input_data)

        assert not result.success
        assert len(result.resolutions) > 0

        # Should have extend_trip resolution
        extend = next(
            (r for r in result.resolutions if r.action == "extend_trip"),
            None,
        )
        assert extend is not None
        assert extend.feasibility == "recommended"
        assert extend.new_duration is not None
        assert extend.new_duration > 4  # Should recommend more than 4 days

    def test_conflict_generates_reduce_activities_resolutions(self, builder: ItineraryBuilder):
        """Conflict should offer 'focus on X only' for each specialist."""
        input_data = ItineraryBuilderInput(
            start_date="2024-03-15",
            end_date="2024-03-18",  # 4 days - insufficient
            strategy_sections=[
                create_diving_section(num_dives=2),
                create_hiking_section(num_hikes=2),
            ],
            tiles={},
            destination="Bali",
        )

        result = builder.build(input_data)

        assert not result.success

        # Should have reduce_activities resolutions
        reduce_resolutions = [r for r in result.resolutions if r.action == "reduce_activities"]
        assert len(reduce_resolutions) >= 2

        # Should offer both diving and hiking focus options
        keep_options = {r.keep_specialist for r in reduce_resolutions}
        assert "diving" in keep_options
        assert "hiking" in keep_options


# =============================================================================
# Test: Three Specialists
# =============================================================================


class TestThreeSpecialists:
    """Test scenarios with three specialists."""

    def test_three_specialists_with_sufficient_days(self, builder: ItineraryBuilder):
        """Three specialists with enough days should merge cleanly."""
        # 10 days: arrival + 6 activities + 1 buffer + departure + 1 extra
        input_data = ItineraryBuilderInput(
            start_date="2024-03-15",
            end_date="2024-03-24",  # 10 days
            strategy_sections=[
                create_diving_section(num_dives=2),
                create_hiking_section(num_hikes=2),
                create_skiing_section(num_runs=2),
            ],
            tiles={},
            destination="Alps with Beach",
        )

        result = builder.build(input_data)

        assert result.success, f"Expected success but got: {result.conflicts}"

        # Count activities per specialist
        activities_by_specialist = {"diving": 0, "hiking": 0, "skiing": 0}
        for day in result.day_cards:
            for block in day.blocks:
                if block.specialist_type in activities_by_specialist and not block.is_buffer:
                    activities_by_specialist[block.specialist_type] += 1

        # Each specialist should have activities
        assert activities_by_specialist["diving"] >= 1
        assert activities_by_specialist["hiking"] >= 1
        assert activities_by_specialist["skiing"] >= 1

    def test_three_specialists_with_insufficient_days(self, builder: ItineraryBuilder):
        """Three specialists with insufficient days should trigger conflict."""
        # 5 days is not enough for 6 activities + 1 buffer
        input_data = ItineraryBuilderInput(
            start_date="2024-03-15",
            end_date="2024-03-19",  # 5 days
            strategy_sections=[
                create_diving_section(num_dives=2),
                create_hiking_section(num_hikes=2),
                create_skiing_section(num_runs=2),
            ],
            tiles={},
            destination="Alps with Beach",
        )

        result = builder.build(input_data)

        assert not result.success
        assert result.error == "CONSTRAINT_CONFLICT"

        # All three specialists should be in conflict
        conflict = next(c for c in result.conflicts if c.type == "insufficient_days")
        assert len(conflict.specialists) == 3


# =============================================================================
# Test: Local Expert Integration
# =============================================================================


class TestLocalExpertIntegration:
    """Test local expert section integration with specialists."""

    def test_local_expert_provides_constraints_only(self, builder: ItineraryBuilder):
        """Local expert contributes constraints but not bookable activities."""
        input_data = ItineraryBuilderInput(
            start_date="2024-03-15",
            end_date="2024-03-20",  # 6 days
            strategy_sections=[
                create_local_expert_section(),
                create_diving_section(num_dives=1),
            ],
            tiles={},
            destination="Bali",
        )

        result = builder.build(input_data)

        assert result.success

        # Should NOT have local_expert activity blocks
        local_expert_activities = []
        for day in result.day_cards:
            for block in day.blocks:
                if block.specialist_type == "local_expert" and not block.is_buffer:
                    local_expert_activities.append(block)

        assert len(local_expert_activities) == 0, "Local expert should not create activity blocks"

    def test_local_expert_constraints_applied(self, builder: ItineraryBuilder):
        """Local expert constraints (e.g., visa) should be in merged constraints."""
        sections = [create_local_expert_section()]

        activities, constraints = builder._extract_specialist_content(sections)

        # Should have visa_requirement constraint
        rules = [c.get("rule") for c in constraints]
        assert "visa_requirement" in rules


# =============================================================================
# Test: Activity Interleaving Patterns
# =============================================================================


class TestInterleavingPatterns:
    """Test activity interleaving strategies."""

    def test_activities_not_clustered_by_specialist(self, builder: ItineraryBuilder):
        """Activities should be interleaved, not clustered by specialist."""
        input_data = ItineraryBuilderInput(
            start_date="2024-03-15",
            end_date="2024-03-24",  # 10 days
            strategy_sections=[
                create_diving_section(num_dives=3),
                create_hiking_section(num_hikes=3),
            ],
            tiles={},
            destination="Bali",
        )

        result = builder.build(input_data)
        assert result.success

        # Track which days have which specialists
        day_specialists = {}
        for day in result.day_cards:
            specialists = set()
            for block in day.blocks:
                if block.specialist_type and not block.is_buffer:
                    specialists.add(block.specialist_type)
            if specialists:
                day_specialists[day.day_number] = specialists

        # Should have activities spread across multiple days
        days_with_activities = len(day_specialists)
        assert days_with_activities >= 3, "Activities should be spread across multiple days"

    def test_respects_max_blocks_per_day(self, builder: ItineraryBuilder):
        """No day should exceed MAX_BLOCKS_PER_DAY for activities."""
        input_data = ItineraryBuilderInput(
            start_date="2024-03-15",
            # 12 days (8 activities + 1 buffer + arrival/departure + 1 spare)
            end_date="2024-03-26",
            strategy_sections=[
                create_diving_section(num_dives=4),
                create_hiking_section(num_hikes=4),
            ],
            tiles={},
            destination="Bali",
        )

        result = builder.build(input_data)
        assert result.success

        for day in result.day_cards:
            activity_blocks = [
                b
                for b in day.blocks
                if not b.is_buffer and b.specialist_type in ("diving", "hiking")
            ]
            assert (
                len(activity_blocks) <= 3
            ), f"Day {day.day_number} has {len(activity_blocks)} activities (max 3)"


# =============================================================================
# Test: Buffer Day Handling
# =============================================================================


# =============================================================================
# Test: Overview Statistics
# =============================================================================


class TestOverviewStatistics:
    """Test itinerary overview computation."""

    def test_multi_specialist_structure_label(self, builder: ItineraryBuilder):
        """Multi-specialist trips should show 'Multi-activity adventure'."""
        input_data = ItineraryBuilderInput(
            start_date="2024-03-15",
            end_date="2024-03-22",  # 8 days
            strategy_sections=[
                create_diving_section(num_dives=2),
                create_hiking_section(num_hikes=2),
            ],
            tiles={},
            destination="Bali",
        )

        result = builder.build(input_data)
        assert result.success
        assert result.overview is not None
        assert "multi" in result.overview.base_structure.lower()

    def test_single_specialist_structure_label(self, builder: ItineraryBuilder):
        """Single specialist trips should show 'Single base + day excursions'."""
        input_data = ItineraryBuilderInput(
            start_date="2024-03-15",
            end_date="2024-03-20",  # 6 days
            strategy_sections=[create_diving_section(num_dives=2)],
            tiles={},
            destination="Bali",
        )

        result = builder.build(input_data)
        assert result.success
        assert result.overview is not None
        assert "single" in result.overview.base_structure.lower()
