# backend/app/planner/__init__.py
"""
Planner facade module.

This module exports the stable public API for the planner.
External code should import from here, not from plan_graph.py directly.

Usage:
    from app.planner import run_turn, run_turn_streaming
    from app.planner import GraphState
    from app.planner import get_planner_debug_info
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Cache access
from app.planner.cache_access import (
    cache_clear,
    cache_contains,
    cache_delete,
    cache_get,
    cache_len,
    cache_pop,
    cache_set,
    update_counters_safe,
    update_nested_counters_safe,
)

# Stable hashing
from app.planner.hashing import (
    canonicalize_destinations,
    canonicalize_dict,
    make_cache_key,
    stable_hash,
    stable_hash_short,
)

# Metadata helpers
from app.planner.meta import (
    init_turn_metadata,
    meta_append,
    meta_get,
    meta_increment,
    meta_set,
    meta_set_once,
)
from app.planner.meta_keys import (
    ALL_META_KEYS,
    PER_TURN_KEYS,
    TRACE_ENVELOPE,
)

# State models
from app.planner.state import (
    GraphState,
    ItineraryBlock,
    MissingFieldsResponse,
    SpecialistConstraint,
    SpecialistOutput,
    SynthesizerOutput,
    TripPlan,
    TripSegment,
    UIEvent,
    create_missing_fields_response,
    get_missing_fields,
    trip_plan_is_ready,
)

# Telemetry
from app.planner.telemetry import (
    TraceEnvelope,
    compute_latency_breakdown,
    create_envelope,
    emit_anomaly_bundle,
    emit_cache_event,
    emit_event,
    emit_gate_eval_end,
    emit_llm_call_end,
    emit_node_end,
    emit_node_start,
    emit_request_end,
    emit_request_start,
    force_verbose_on_anomaly,
    now_ns,
    redact_prompt,
    redact_text,
)

# Test mode detection
from app.planner.test_mode import (
    is_test_mode,
)

# Type checking imports (no runtime cost)
if TYPE_CHECKING:
    from app.plan_graph import (
        clear_all_caches,
        run_turn,
        run_turn_streaming,
    )
    from app.planner.services.admin_utils import (
        CACHE_SCHEMA_VERSION,
        PLANNER_BUILD_ID,
        PROMPT_BUNDLE_HASH,
        checkpoint_stats,
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
    """Lazy import for plan_graph and admin_utils exports to avoid circular imports."""
    # Functions still in plan_graph.py
    _PLAN_GRAPH_EXPORTS = {
        "clear_all_caches",  # Kept in plan_graph (mutates global _graph)
        "run_turn",
        "run_turn_streaming",
    }

    # Functions extracted to admin_utils.py
    _ADMIN_UTILS_EXPORTS = {
        "CACHE_SCHEMA_VERSION",
        "PLANNER_BUILD_ID",
        "PROMPT_BUNDLE_HASH",
        "checkpoint_stats",
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

    if name in _PLAN_GRAPH_EXPORTS:
        from app import plan_graph

        return getattr(plan_graph, name)

    if name in _ADMIN_UTILS_EXPORTS:
        from app.planner.services import admin_utils

        return getattr(admin_utils, name)

    if name in _STATE_SERDE_EXPORTS:
        from app.planner.services import state_serde

        return getattr(state_serde, name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Entry points
    "run_turn",
    "run_turn_streaming",
    # State types
    "GraphState",
    # State models
    "TripPlan",
    "TripSegment",
    "ItineraryBlock",
    "SpecialistConstraint",
    "SpecialistOutput",
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
    # Metadata
    "init_turn_metadata",
    "meta_get",
    "meta_set",
    "meta_set_once",
    "meta_append",
    "meta_increment",
    "ALL_META_KEYS",
    "PER_TURN_KEYS",
    "TRACE_ENVELOPE",
    # Test mode
    "is_test_mode",
    # Cache access
    "cache_get",
    "cache_set",
    "cache_pop",
    "cache_delete",
    "cache_clear",
    "cache_len",
    "cache_contains",
    "update_counters_safe",
    "update_nested_counters_safe",
    # Stable hashing
    "stable_hash",
    "stable_hash_short",
    "canonicalize_destinations",
    "canonicalize_dict",
    "make_cache_key",
    # Telemetry
    "TraceEnvelope",
    "create_envelope",
    "emit_event",
    "emit_request_start",
    "emit_request_end",
    "emit_gate_eval_end",
    "emit_node_start",
    "emit_node_end",
    "emit_llm_call_end",
    "emit_cache_event",
    "emit_anomaly_bundle",
    "force_verbose_on_anomaly",
    "redact_text",
    "redact_prompt",
    "now_ns",
    "compute_latency_breakdown",
]
