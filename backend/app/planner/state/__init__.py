"""
State Package.

This package contains state management for the planner.

Exports:
    TripPlan, TripSegment, ItineraryBlock, SpecialistConstraint
    GraphState, SpecialistOutput, UIEvent, MissingFieldsResponse
    SynthesizerOutput

Usage:
    from app.planner.state import TripPlan, GraphState
"""

# State Models
from app.planner.state.schemas import (
    # Core models
    Activity,
    # Enums
    ConstraintSeverity,
    ExtractedSettingsFields,
    # LLM Extraction
    ExtractedTripFields,
    # State
    GraphState,
    ItineraryBlock,
    MissingFieldsResponse,
    SpecialistConstraint,
    # Output models
    SpecialistOutput,
    SynthesizerOutput,
    TripPlan,
    TripSegment,
    UIEvent,
    create_missing_fields_response,
    get_missing_fields,
    # Helpers
    trip_plan_is_ready,
)

__all__ = [
    # Enums
    "ConstraintSeverity",
    # Core Models
    "Activity",
    "TripPlan",
    "TripSegment",
    "ItineraryBlock",
    "SpecialistConstraint",
    # State
    "GraphState",
    # Output Models
    "SpecialistOutput",
    "UIEvent",
    "MissingFieldsResponse",
    "SynthesizerOutput",
    # Helpers
    "trip_plan_is_ready",
    "get_missing_fields",
    "create_missing_fields_response",
    # LLM Extraction
    "ExtractedTripFields",
    "ExtractedSettingsFields",
]
