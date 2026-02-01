"""
Specialist Schemas

Pydantic models for structured LLM output from vertical specialists.
These enable consistent, type-safe constraint generation across all specialist types.

@see docs/plan_graph_analysis.md Section: VerticalSpecialist Node
"""

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class ConstraintType(str, Enum):
    """Severity level of a constraint."""

    BLOCKING = "blocking"  # Cannot be violated - safety critical
    STRONG = "strong"  # Strongly recommended - should not be violated
    SOFT = "soft"  # Informational - nice to follow


class TemporalRequirement(BaseModel):
    """Temporal requirements for a constraint."""

    buffer_hours: Optional[int] = Field(default=None, description="Required buffer time in hours")
    min_duration_hours: Optional[int] = Field(
        default=None, description="Minimum duration for the activity"
    )
    max_duration_hours: Optional[int] = Field(
        default=None, description="Maximum recommended duration"
    )
    time_of_day: Optional[Literal["morning", "afternoon", "evening", "flexible"]] = Field(
        default=None, description="Preferred time of day for the activity"
    )


class ConstraintOutput(BaseModel):
    """A single constraint from a specialist."""

    id: str = Field(..., description="Unique snake_case identifier")
    type: ConstraintType = Field(..., description="Severity level")
    description: str = Field(..., description="Short description of the constraint")
    explanation: str = Field(..., description="Detailed explanation for user-facing display")
    priority: int = Field(..., ge=1, le=10, description="Priority 1-10, 10 being highest")
    temporal_requirements: Optional[TemporalRequirement] = Field(
        default=None, description="Time-based requirements"
    )
    applies_to_categories: list[str] = Field(
        default_factory=list, description="Activity categories this applies to"
    )
    icon: str = Field(default="⚠️", description="Emoji icon for UI display")

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Ensure ID is lowercase snake_case."""
        if not v.islower() or " " in v:
            raise ValueError("Constraint ID must be lowercase snake_case")
        return v


class ContentBlock(BaseModel):
    """A content block for specialist tips/warnings."""

    type: Literal["tip", "warning", "recommendation", "requirement"] = Field(
        ..., description="Type of content block"
    )
    title: str = Field(..., description="Block title")
    content: str = Field(..., description="Block content/body")
    icon: str = Field(default="💡", description="Emoji icon")
    priority: int = Field(default=5, ge=1, le=10, description="Display priority")


class FeasibilityAssessment(BaseModel):
    """Assessment of trip feasibility from specialist perspective."""

    score: float = Field(..., ge=0.0, le=1.0, description="Feasibility score 0-1")
    is_feasible: bool = Field(..., description="Whether the trip is feasible")
    blockers: list[str] = Field(
        default_factory=list, description="Blocking issues that prevent the trip"
    )
    concerns: list[str] = Field(
        default_factory=list, description="Non-blocking concerns to address"
    )
    recommendations: list[str] = Field(
        default_factory=list, description="Suggestions to improve the trip"
    )


class SpecialistOutput(BaseModel):
    """Complete output from a vertical specialist LLM call."""

    specialist_type: Literal["diving", "hiking", "skiing", "surfing", "cycling"] = Field(
        ..., description="Type of specialist"
    )
    constraints: list[ConstraintOutput] = Field(
        default_factory=list, description="Safety and logistical constraints"
    )
    content_blocks: list[ContentBlock] = Field(
        default_factory=list, description="Tips, warnings, and recommendations"
    )
    feasibility: FeasibilityAssessment = Field(..., description="Overall feasibility assessment")
    critique: Optional[str] = Field(
        default=None, description="Optional critique of the current plan"
    )
    suggested_activities: list[str] = Field(
        default_factory=list, description="Recommended activities for this specialist type"
    )
