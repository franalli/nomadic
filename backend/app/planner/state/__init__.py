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
from app.planner.state.graph_state import (
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
    # Settings
    TripSettings,
    UIEvent,
    create_missing_fields_response,
    get_missing_fields,
    # Helpers
    trip_plan_is_ready,
)

# Typed metadata (shadow-mode migration)
from app.planner.state.typed_meta import (
    PersistentMeta,
    TurnMeta,
    get_persistent_meta,
    get_trip_settings,
    get_turn_meta,
    reset_turn_metadata,
    sync_persistent_meta,
    sync_turn_meta,
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
    # Settings
    "TripSettings",
    # Typed Metadata
    "TurnMeta",
    "PersistentMeta",
    "get_turn_meta",
    "get_trip_settings",
    "sync_turn_meta",
    "reset_turn_metadata",
    "get_persistent_meta",
    "sync_persistent_meta",
]
