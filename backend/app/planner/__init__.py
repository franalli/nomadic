# backend/app/planner/__init__.py
"""
Planner facade module.

This module exports the stable public API for the planner.
External code should import from here, not from internal modules directly.

Usage:
    from app.planner import GraphState
    from app.planner import get_planner_debug_info
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Stable hashing
from app.planner.hashing import (
    canonicalize_destinations,
    make_cache_key,
    stable_hash,
    stable_hash_short,
)

# State models
from app.planner.state import (
    GraphState,
    ItineraryBlock,
    MissingFieldsResponse,
    SpecialistConstraint,
    SpecialistStateOutput,
    SynthesizerOutput,
    TripPlan,
    TripSegment,
    UIEvent,
    create_missing_fields_response,
    get_missing_fields,
    trip_plan_is_ready,
)

# Test mode detection
from app.planner.test_mode import (
    is_test_mode,
)

# Type checking imports (no runtime cost)
if TYPE_CHECKING:
    from app.planner.coordinator import (
        build_trip_state_summary,
        execute_turn,
    )
    from app.planner.services.admin_utils import (
        CACHE_SCHEMA_VERSION,
        PLANNER_BUILD_ID,
        PROMPT_BUNDLE_HASH,
        checkpoint_stats,
        clear_all_caches,
        clear_all_checkpoints,
        clear_response_caches,
        clear_session_checkpoint,
        condense_long_message,
        get_graph_stats,
        get_planner_debug_info,
        prewarm_prompts,
        response_cache_stats,
        validate_template_coverage,
    )
    from app.planner.services.state_serde import (
        restore_graph_state,
        state_to_session_state,
        trip_plan_to_trip_inputs,
    )


def __getattr__(name: str):
    """Lazy import for admin_utils and state_serde exports to avoid circular imports."""
    # Functions in admin_utils.py
    _ADMIN_UTILS_EXPORTS = {
        "CACHE_SCHEMA_VERSION",
        "PLANNER_BUILD_ID",
        "PROMPT_BUNDLE_HASH",
        "checkpoint_stats",
        "clear_all_caches",
        "clear_all_checkpoints",
        "clear_response_caches",
        "clear_session_checkpoint",
        "condense_long_message",
        "get_graph_stats",
        "get_planner_debug_info",
        "prewarm_prompts",
        "response_cache_stats",
        "validate_template_coverage",
    }

    # Functions extracted to state_serde.py
    _STATE_SERDE_EXPORTS = {
        "restore_graph_state",
        "state_to_session_state",
        "trip_plan_to_trip_inputs",
    }
    _COORDINATOR_EXPORTS = {
        "execute_turn",
        "build_trip_state_summary",
    }

    if name in _ADMIN_UTILS_EXPORTS:
        from app.planner.services import admin_utils

        return getattr(admin_utils, name)

    if name in _STATE_SERDE_EXPORTS:
        from app.planner.services import state_serde

        return getattr(state_serde, name)

    if name in _COORDINATOR_EXPORTS:
        from app.planner import coordinator

        return getattr(coordinator, name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # State types
    "GraphState",
    # State models
    "TripPlan",
    "TripSegment",
    "ItineraryBlock",
    "SpecialistConstraint",
    "SpecialistStateOutput",
    "UIEvent",
    "MissingFieldsResponse",
    "SynthesizerOutput",
    "trip_plan_is_ready",
    "get_missing_fields",
    "create_missing_fields_response",
    # Debug/observability
    "get_planner_debug_info",
    # Cache utilities
    "clear_all_caches",
    "clear_all_checkpoints",
    "clear_response_caches",
    "clear_session_checkpoint",
    # Cache stats
    "checkpoint_stats",
    "response_cache_stats",
    "get_graph_stats",
    # Build metadata
    "CACHE_SCHEMA_VERSION",
    "PLANNER_BUILD_ID",
    "PROMPT_BUNDLE_HASH",
    # Utilities
    "condense_long_message",
    "prewarm_prompts",
    "validate_template_coverage",
    # State serialization
    "restore_graph_state",
    "state_to_session_state",
    "trip_plan_to_trip_inputs",
    # Coordinator
    "execute_turn",
    "build_trip_state_summary",
    # Test mode
    "is_test_mode",
    # Stable hashing
    "stable_hash",
    "stable_hash_short",
    "canonicalize_destinations",
    "make_cache_key",
]
