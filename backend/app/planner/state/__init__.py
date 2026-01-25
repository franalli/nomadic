"""
State Package - V2 Architecture.

This package contains state management for the V2 planner.

V2 Exports (6-node architecture):
    TripPlan, TripSegment, ItineraryBlock, SpecialistConstraint
    GraphStateV2, SpecialistOutput, UIEvent, MissingFieldsResponse
    SynthesizerOutput

Usage:
    from app.planner.state import TripPlan, GraphStateV2
"""

# V2 State Models
from app.planner.state.schemas_v2 import (
    # State
    GraphStateV2,
    ItineraryBlock,
    MissingFieldsResponse,
    SpecialistConstraint,
    # Output models
    SpecialistOutput,
    SynthesizerOutput,
    # Core models
    TripPlan,
    TripSegment,
    UIEvent,
    create_missing_fields_response,
    get_missing_fields,
    # Helpers
    trip_plan_is_ready,
)

__all__ = [
    # V2 Core Models
    "TripPlan",
    "TripSegment",
    "ItineraryBlock",
    "SpecialistConstraint",
    # V2 State
    "GraphStateV2",
    # V2 Output Models
    "SpecialistOutput",
    "UIEvent",
    "MissingFieldsResponse",
    "SynthesizerOutput",
    # V2 Helpers
    "trip_plan_is_ready",
    "get_missing_fields",
    "create_missing_fields_response",
]
