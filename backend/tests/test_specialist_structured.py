"""
Tests for Specialist Structured Output Schemas

Validates that:
1. ConstraintOutput models have valid snake_case IDs
2. FeasibilityAssessment scores are in valid range
3. SpecialistOutput can be serialized and deserialized
4. Constraint types map correctly to severity levels

@see docs/plan_graph_analysis.md Section: VerticalSpecialist Node
"""

import pytest
from pydantic import ValidationError

from app.planner.nodes.specialist_schemas import (
    ConstraintOutput,
    ConstraintType,
    ContentBlock,
    FeasibilityAssessment,
    SpecialistOutput,
    TemporalRequirement,
)
from app.planner.state import ConstraintSeverity, SpecialistConstraint


class TestConstraintOutput:
    """Tests for ConstraintOutput model validation."""

    def test_valid_constraint(self):
        """Valid constraint with all fields."""
        constraint = ConstraintOutput(
            id="min_24h_buffer_after_dive",
            type=ConstraintType.BLOCKING,
            description="No flying within 24 hours of last dive",
            explanation="Prevents decompression sickness",
            priority=10,
            icon="🚫",
        )
        assert constraint.id == "min_24h_buffer_after_dive"
        assert constraint.type == ConstraintType.BLOCKING
        assert constraint.priority == 10

    def test_id_must_be_snake_case(self):
        """Constraint ID must be lowercase snake_case."""
        with pytest.raises(ValidationError):
            ConstraintOutput(
                id="InvalidID",  # Not snake_case
                type=ConstraintType.STRONG,
                description="Test",
                explanation="Test",
                priority=5,
            )

    def test_id_no_spaces(self):
        """Constraint ID cannot contain spaces."""
        with pytest.raises(ValidationError):
            ConstraintOutput(
                id="invalid id",  # Has space
                type=ConstraintType.STRONG,
                description="Test",
                explanation="Test",
                priority=5,
            )

    def test_priority_range(self):
        """Priority must be between 1 and 10."""
        # Valid range
        constraint = ConstraintOutput(
            id="test_constraint",
            type=ConstraintType.SOFT,
            description="Test",
            explanation="Test",
            priority=1,
        )
        assert constraint.priority == 1

        constraint = ConstraintOutput(
            id="test_constraint",
            type=ConstraintType.SOFT,
            description="Test",
            explanation="Test",
            priority=10,
        )
        assert constraint.priority == 10

        # Invalid: below range
        with pytest.raises(ValidationError):
            ConstraintOutput(
                id="test_constraint",
                type=ConstraintType.SOFT,
                description="Test",
                explanation="Test",
                priority=0,
            )

        # Invalid: above range
        with pytest.raises(ValidationError):
            ConstraintOutput(
                id="test_constraint",
                type=ConstraintType.SOFT,
                description="Test",
                explanation="Test",
                priority=11,
            )

    def test_temporal_requirements(self):
        """Constraint can include temporal requirements."""
        constraint = ConstraintOutput(
            id="no_fly_buffer",
            type=ConstraintType.BLOCKING,
            description="No flying after dive",
            explanation="Safety buffer",
            priority=10,
            temporal_requirements=TemporalRequirement(buffer_hours=24),
        )
        assert constraint.temporal_requirements.buffer_hours == 24


class TestFeasibilityAssessment:
    """Tests for FeasibilityAssessment model."""

    def test_valid_feasibility(self):
        """Valid feasibility assessment."""
        assessment = FeasibilityAssessment(
            score=0.85,
            is_feasible=True,
            concerns=["Weather may vary"],
            recommendations=["Book in advance"],
        )
        assert assessment.score == 0.85
        assert assessment.is_feasible is True

    def test_score_range(self):
        """Score must be between 0.0 and 1.0."""
        # Valid boundaries
        assessment = FeasibilityAssessment(score=0.0, is_feasible=False)
        assert assessment.score == 0.0

        assessment = FeasibilityAssessment(score=1.0, is_feasible=True)
        assert assessment.score == 1.0

        # Invalid: below range
        with pytest.raises(ValidationError):
            FeasibilityAssessment(score=-0.1, is_feasible=False)

        # Invalid: above range
        with pytest.raises(ValidationError):
            FeasibilityAssessment(score=1.1, is_feasible=True)

    def test_infeasible_with_blockers(self):
        """Infeasible trip should have blockers."""
        assessment = FeasibilityAssessment(
            score=0.0,
            is_feasible=False,
            blockers=["No snow during requested dates"],
        )
        assert assessment.is_feasible is False
        assert len(assessment.blockers) == 1


class TestSpecialistOutput:
    """Tests for complete SpecialistOutput model."""

    def test_diving_specialist_output(self):
        """Complete diving specialist output."""
        output = SpecialistOutput(
            specialist_type="diving",
            constraints=[
                ConstraintOutput(
                    id="min_24h_buffer_after_dive",
                    type=ConstraintType.BLOCKING,
                    description="No flying within 24 hours",
                    explanation="Decompression sickness risk",
                    priority=10,
                    icon="🚫",
                    temporal_requirements=TemporalRequirement(buffer_hours=24),
                ),
                ConstraintOutput(
                    id="min_18h_surface_interval",
                    type=ConstraintType.STRONG,
                    description="18 hour surface interval",
                    explanation="Allow nitrogen off-gassing",
                    priority=9,
                    icon="⏰",
                ),
            ],
            content_blocks=[
                ContentBlock(
                    type="tip",
                    title="Best Dive Sites",
                    content="Book popular sites in advance",
                    icon="🤿",
                    priority=8,
                ),
            ],
            feasibility=FeasibilityAssessment(
                score=0.85,
                is_feasible=True,
                concerns=["Only 2 dive days due to no-fly buffer"],
            ),
            suggested_activities=["Morning dive", "Night dive"],
        )

        assert output.specialist_type == "diving"
        assert len(output.constraints) == 2
        assert output.constraints[0].id == "min_24h_buffer_after_dive"
        assert output.feasibility.score == 0.85

    def test_serialization_roundtrip(self):
        """Output can be serialized and deserialized."""
        output = SpecialistOutput(
            specialist_type="hiking",
            constraints=[],
            content_blocks=[],
            feasibility=FeasibilityAssessment(
                score=0.9,
                is_feasible=True,
            ),
        )

        # Serialize to dict
        data = output.model_dump()
        assert data["specialist_type"] == "hiking"
        assert data["feasibility"]["score"] == 0.9

        # Deserialize back
        restored = SpecialistOutput(**data)
        assert restored.specialist_type == "hiking"
        assert restored.feasibility.score == 0.9


class TestConstraintTypeMapping:
    """Tests for mapping between LLM ConstraintType and state ConstraintSeverity."""

    def test_type_to_severity_mapping(self):
        """Constraint types map to correct severity levels."""
        mapping = {
            ConstraintType.BLOCKING: ConstraintSeverity.BLOCKING,
            ConstraintType.STRONG: ConstraintSeverity.STRONG,
            ConstraintType.SOFT: ConstraintSeverity.SOFT,
        }

        for llm_type, state_severity in mapping.items():
            assert llm_type.value == state_severity.value

    def test_existing_specialist_constraint_has_severity(self):
        """Existing SpecialistConstraint supports severity field."""
        constraint = SpecialistConstraint(
            type="temporal",
            rule="min_24h_buffer_after_dive",
            applies_to="flights",
            reason="Decompression sickness risk",
            label="24h no-fly buffer",
            icon="🚫",
            severity=ConstraintSeverity.BLOCKING,
            buffer_hours=24,
        )

        assert constraint.severity == ConstraintSeverity.BLOCKING
        assert constraint.label == "24h no-fly buffer"
        assert constraint.icon == "🚫"
        assert constraint.buffer_hours == 24


class TestContentBlock:
    """Tests for ContentBlock model."""

    def test_valid_content_block(self):
        """Valid content block with all fields."""
        block = ContentBlock(
            type="tip",
            title="Early Start",
            content="Start hikes at dawn",
            icon="🌄",
            priority=8,
        )
        assert block.type == "tip"
        assert block.priority == 8

    def test_content_block_types(self):
        """Content block type must be valid."""
        valid_types = ["tip", "warning", "recommendation", "requirement"]

        for block_type in valid_types:
            block = ContentBlock(
                type=block_type,
                title="Test",
                content="Test content",
            )
            assert block.type == block_type
