"""
Unit Tests for Cross-Domain Constraint Validation

Tests the no_altitude_after_dive constraint (diving → hiking) and other
cross-specialist constraint interactions.

Part 0 of the multi-specialist constraint system.
"""

import pytest

from app.planner.state import ConstraintSeverity, SpecialistConstraint
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


@pytest.fixture
def short_diving_hiking_input() -> ItineraryBuilderInput:
    """4-day trip with diving + hiking (insufficient for altitude buffer)."""
    return ItineraryBuilderInput(
        start_date="2024-03-15",
        end_date="2024-03-18",  # 4 days: 2 usable activity days
        strategy_sections=[
            {
                "specialist_type": "diving",
                "content_added": [
                    {"title": "USAT Liberty Wreck", "duration_hours": 3.0},
                ],
                "constraints_applied": [
                    {"rule": "min_24h_buffer_after_dive"},
                    {"rule": "no_altitude_after_dive"},  # Cross-domain constraint
                ],
            },
            {
                "specialist_type": "hiking",
                "content_added": [
                    {"title": "Mount Batur Sunrise", "duration_hours": 4.0},
                ],
                "constraints_applied": [],
            },
        ],
        tiles={},
        destination="Bali",
    )


@pytest.fixture
def long_diving_hiking_input() -> ItineraryBuilderInput:
    """8-day trip with diving + hiking (sufficient for altitude buffer)."""
    return ItineraryBuilderInput(
        start_date="2024-03-15",
        end_date="2024-03-22",  # 8 days: 6 usable activity days
        strategy_sections=[
            {
                "specialist_type": "diving",
                "content_added": [
                    {"title": "USAT Liberty Wreck", "duration_hours": 3.0},
                    {"title": "Manta Point", "duration_hours": 3.0},
                ],
                "constraints_applied": [
                    {"rule": "min_24h_buffer_after_dive"},
                    {"rule": "no_altitude_after_dive"},
                ],
            },
            {
                "specialist_type": "hiking",
                "content_added": [
                    {"title": "Mount Batur Sunrise", "duration_hours": 4.0},
                ],
                "constraints_applied": [],
            },
        ],
        tiles={},
        destination="Bali",
    )


@pytest.fixture
def diving_only_input() -> ItineraryBuilderInput:
    """5-day diving-only trip (no hiking, no altitude conflict)."""
    return ItineraryBuilderInput(
        start_date="2024-03-15",
        end_date="2024-03-19",  # 5 days
        strategy_sections=[
            {
                "specialist_type": "diving",
                "content_added": [
                    {"title": "USAT Liberty Wreck", "duration_hours": 3.0},
                    {"title": "Manta Point", "duration_hours": 3.0},
                ],
                "constraints_applied": [
                    {"rule": "min_24h_buffer_after_dive"},
                    {"rule": "no_altitude_after_dive"},
                ],
            },
        ],
        tiles={},
        destination="Bali",
    )


# =============================================================================
# Schema Tests
# =============================================================================


class TestSpecialistConstraintSchema:
    """Test the applies_to_categories field on SpecialistConstraint."""

    def test_applies_to_categories_field_exists(self):
        """Constraint can specify cross-domain categories."""
        constraint = SpecialistConstraint(
            type="safety",
            rule="no_altitude_after_dive",
            applies_to_categories=["hiking", "trekking", "mountaineering"],
            severity=ConstraintSeverity.BLOCKING,
        )
        assert constraint.applies_to_categories == [
            "hiking",
            "trekking",
            "mountaineering",
        ]

    def test_applies_to_backward_compatible(self):
        """Old constraints with applies_to (singular) still work."""
        constraint = SpecialistConstraint(
            type="temporal",
            rule="min_24h_buffer_after_dive",
            applies_to="flights",  # Old format
            severity=ConstraintSeverity.BLOCKING,
        )
        assert constraint.applies_to == "flights"
        assert constraint.applies_to_categories == []  # Default empty

    def test_both_fields_can_coexist(self):
        """Both applies_to and applies_to_categories can be set."""
        constraint = SpecialistConstraint(
            type="safety",
            rule="test_rule",
            applies_to="flights",
            applies_to_categories=["hiking"],
            severity=ConstraintSeverity.STRONG,
        )
        assert constraint.applies_to == "flights"
        assert constraint.applies_to_categories == ["hiking"]


# =============================================================================
# Cross-Domain Conflict Detection Tests
# =============================================================================


class TestCrossDomainConflictDetection:
    """Test _detect_early_conflicts for diving + hiking altitude constraint."""

    def test_short_trip_diving_hiking_conflict(
        self, builder: ItineraryBuilder, short_diving_hiking_input: ItineraryBuilderInput
    ):
        """4-day trip with diving + hiking should detect altitude conflict."""
        result = builder.build(short_diving_hiking_input)

        # Should fail due to constraint conflict
        assert not result.success
        assert result.error == "CONSTRAINT_CONFLICT"
        assert len(result.conflicts) >= 1

        # Check for constraint_clash type
        clash_conflicts = [c for c in result.conflicts if c.type == "constraint_clash"]
        assert len(clash_conflicts) >= 1

        # Verify specialists are identified
        conflict = clash_conflicts[0]
        assert "diving" in conflict.specialists
        assert "hiking" in conflict.specialists

    def test_long_trip_diving_hiking_success(
        self, builder: ItineraryBuilder, long_diving_hiking_input: ItineraryBuilderInput
    ):
        """8-day trip should accommodate diving + buffer + hiking."""
        result = builder.build(long_diving_hiking_input)

        # Should succeed - enough days for all activities + buffer
        assert result.success
        assert result.error is None

        # May have warnings but no blocking conflicts
        blocking_conflicts = [
            c for c in result.conflicts if c.severity == ConstraintSeverity.BLOCKING
        ]
        assert len(blocking_conflicts) == 0

    def test_diving_only_no_altitude_conflict(
        self, builder: ItineraryBuilder, diving_only_input: ItineraryBuilderInput
    ):
        """Diving-only trip should not trigger altitude conflict."""
        result = builder.build(diving_only_input)

        # Should succeed - no hiking to conflict with
        assert result.success

        # No constraint_clash conflicts
        clash_conflicts = [c for c in result.conflicts if c.type == "constraint_clash"]
        assert len(clash_conflicts) == 0


# =============================================================================
# Constraint Merging Tests
# =============================================================================


class TestConstraintMerging:
    """Test constraint merging from multiple specialists."""

    def test_altitude_constraint_severity_is_blocking(self):
        """no_altitude_after_dive should be BLOCKING severity."""
        from app.services.itinerary_builder import CONSTRAINT_SEVERITY_MAP

        assert "no_altitude_after_dive" in CONSTRAINT_SEVERITY_MAP
        assert CONSTRAINT_SEVERITY_MAP["no_altitude_after_dive"] == ConstraintSeverity.BLOCKING

    def test_altitude_constraint_in_blocking_rules(self):
        """no_altitude_after_dive should be in BLOCKING_RULES."""
        from app.services.itinerary_builder import BLOCKING_RULES

        assert "no_altitude_after_dive" in BLOCKING_RULES


# =============================================================================
# Minimal Safety Constraints Tests
# =============================================================================


class TestMinimalSafetyConstraints:
    """Test the _get_minimal_safety_constraints() fallback function."""

    def test_diving_minimal_has_no_fly_constraint(self):
        """Diving fallback should include min_24h_buffer_after_dive (no-fly)."""
        from app.planner.nodes.vertical_specialist import _get_minimal_safety_constraints

        constraints = _get_minimal_safety_constraints("diving")
        no_fly_constraint = next(
            (c for c in constraints if c.rule == "min_24h_buffer_after_dive"), None
        )

        assert no_fly_constraint is not None
        assert no_fly_constraint.severity == ConstraintSeverity.BLOCKING
        assert no_fly_constraint.buffer_hours == 24
        assert "flights" in no_fly_constraint.applies_to_categories

    def test_diving_constraint_has_proper_label(self):
        """Diving constraint should have user-friendly label and icon."""
        from app.planner.nodes.vertical_specialist import _get_minimal_safety_constraints

        constraints = _get_minimal_safety_constraints("diving")
        no_fly_constraint = constraints[0]

        assert no_fly_constraint.label == "24h No-Fly Buffer"
        assert no_fly_constraint.icon == "🚫"


class TestHikingSkiingMinimalConstraints:
    """Verify hiking/skiing have their own specific minimal constraints."""

    def test_hiking_minimal_has_altitude_constraint(self):
        """Hiking fallback should have altitude acclimatization constraint."""
        from app.planner.nodes.vertical_specialist import _get_minimal_safety_constraints

        constraints = _get_minimal_safety_constraints("hiking")
        altitude_constraint = next(
            (c for c in constraints if c.rule == "altitude_acclimatization"), None
        )

        assert altitude_constraint is not None
        assert altitude_constraint.severity == ConstraintSeverity.STRONG

    def test_skiing_minimal_has_avalanche_constraint(self):
        """Skiing fallback should have avalanche check constraint."""
        from app.planner.nodes.vertical_specialist import _get_minimal_safety_constraints

        constraints = _get_minimal_safety_constraints("skiing")
        avalanche_constraint = next(
            (c for c in constraints if c.rule == "check_snow_conditions"), None
        )

        assert avalanche_constraint is not None
        assert avalanche_constraint.severity == ConstraintSeverity.BLOCKING
