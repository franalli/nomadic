# plan_graph.py — Minimalist LangGraph with strategy modules
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random as _random_module
import re
import time
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple
from uuid import uuid4

import grapheme
from cachetools import TTLCache
from jinja2 import Environment, FileSystemLoader
from jsonschema import Draft7Validator
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app import db_models as models
from app.config import settings
from app.crud_document import (
    apply_planner_update,
    get_document,
    get_document_data,
    get_or_create_document,
)
from app.crud_trip import (
    create_trip_context,
    fetch_chat_history,
    get_latest_trip_context_for_session,
    get_or_create_session,
    record_chat_message,
)
from app.debug_utils import (
    # PR-E: Debug utilities extracted to debug_utils.py
    _debug,
    _debug_error,
    _debug_suggestions,
    is_debug_enabled,
    safe_debug,
    safe_debug_error,
)
from app.graph_plan_utils import (
    # PR-D: JSON utilities extracted to graph_plan_utils
    jloads_safe,
)
from app.known_places import (
    KNOWN_COUNTRIES,
    extract_city_from_location,
    is_known_place,
    normalize_place_synonym,
    normalize_place_with_fuzzy,
)
from app.pattern_matching import (
    ADDITIVE_INTENT_PATTERN,
    ADVENTUROUS_PATTERNS,
    # Utility patterns
    ANSI_ESCAPE_PATTERN,
    BUDGET_PATTERN,
    BUDGET_TIER_ESTIMATES,
    BYPASS_CONSTRAINT_PATTERNS,
    # Transport patterns
    COMMA_LIST_PATTERN,
    DENSE_INPUT_KEYWORDS,
    ENTHUSIASTIC_TONE_PATTERNS,
    FAMILY_COMPOSITION_PATTERN,
    # Field request pattern (for "set budget", "budget?", etc.)
    FIELD_REQUEST_PATTERN,
    FIELD_REQUEST_TARGET_MAP,
    FROM_VERB_TO_PATTERN,
    FRUSTRATED_TONE_PATTERNS,
    # Generate request pattern
    GENERATE_REQUEST_PATTERN,
    GREETING_BLOCKLIST,
    GREETING_PATTERN,
    # Guard for field request (skip if contains values)
    HAS_VALUE_PATTERN,
    # Hotel patterns
    INFEASIBILITY_SIGNALS,
    # Destination patterns
    INITIAL_DESTINATION_PATTERN,
    INLINE_BUDGET_PATTERN,
    INLINE_DURATION_PATTERN,
    INLINE_TRAVELERS_PATTERN,
    ISO_DATE_PATTERN,
    MONTH_TO_MONTH_RANGE_PATTERN,
    MULTI_CITY_COMBINED_PHRASES,
    MULTI_CITY_SEPARATE_PHRASES,
    MULTI_DESTINATION_PATTERN,
    MULTI_FIELD_PATTERN,
    NO_BUDGET_PHRASES,
    NO_PATTERN,
    ORIGIN_DESTINATION_PATTERN,
    ORIGIN_LOCATION_PATTERN,
    ORIGIN_PREFIX_PATTERN,
    PLACE_SEPARATORS_PATTERN,
    QUICK_BOOKING_PATTERNS,
    RELATIVE_DATE_PATTERNS,
    # Relative date words (consolidated constants)
    SEASON_PATTERN,
    SENTENCE_VERB_PATTERN,
    SHORT_TRIP_PATTERNS,
    STRATEGY_INTENT_KEYWORDS,
    STRATEGY_TOPIC_PATTERNS,
    TOPIC_KEYWORDS,
    TRAILING_ORIGIN_PATTERN,
    TRAVELERS_MICRO_PATTERNS,
    TRAVELERS_PATTERN,
    UNDECIDED_PATTERNS,
    WORD_TO_NUMBER,
    YES_PATTERN,
    # Date compatibility (consolidated)
    is_likely_location,
    is_traveler_detail_answer,
)
from app.planner.gates.checks import (
    # P4: Strategy expansion checks
    STRATEGY_TIER_MAX_TOKENS,
    StrategyTier,
    is_strategy_expansion_request,
)
from app.planner.gates.constants import (
    CANONICAL_FIELD_ORDER,
    CORE_FIELD_PRIORITY,
    DATE_BLOCKING_ERROR_CODES,
)
from app.planner.gates.evaluator_v2 import GateEvaluator
from app.planner.gates.intent_detection import check_question_keyword_combo
from app.planner.gates.precedence import GatePrecedence
from app.planner.gates.readiness import compute_trip_readiness
from app.planner.gates.result import GateResult
from app.planner.hashing import (
    # PR5: Stable hashing utilities
    stable_hash_index,
    stable_hash_int,
)
from app.planner.meta_keys import (
    # PR2: Metadata key constants
    DELTAS_APPLIED_THIS_TURN,
    DUPLICATION_CLASS,
    LLM_CALL_BLOCKED_REASON,
    LLM_CALL_SITES,
    LLM_CALLS_THIS_TURN,
    MUTATION_COUNTER,
    NODE_RUN_JOURNAL,
    PLANNER_SNAPSHOT,
    RESPONSE_CLAIMED_BY,
    RESPONSE_GENERATION_PROVENANCE,
    RESPONSE_SOURCE_NODE,
    STEP_COUNT,
    TRACE_ENVELOPE,
    TRIPWIRE_TRIGGERED,
    TURN_CANARY,
    VISITED_NODES,
)
from app.planner.node_utils import (  # P2: Simple utilities for node files
    ti_short as _ti_short_impl,
)
from app.planner.node_utils import (
    today_iso as _today_iso_impl,
)
from app.planner.nodes import (  # PR6: Extracted node functions
    _specialist,
    extractor,
    lqa_prepass,
    router,
    strategy_node,
)
from app.planner.normalization import (
    # Tier 3: Date and TripInput normalization extracted
    DateNormalizer,
    TripInputNormalizer,
)
from app.planner.normalization import (
    normalize_str as _normalize_str,
)
from app.planner.parsing import (
    _MONTH_NAMES,
    _is_date_like_text,
    set_parse_provenance,
    set_parse_provenance_once,
)
from app.planner.streaming import STREAMING_PARAMS
from app.planner.telemetry import (
    # PR-T: Telemetry instrumentation
    TraceEnvelope,
    emit_node_end,
    emit_node_start,
    force_verbose_on_anomaly,
    now_ns,
)
from app.planner.test_mode import (
    # PR4: Test-mode detection for invariant hard-fails
    raise_if_test_mode,
)
from app.routing_keywords import (
    AMBIGUOUS_KEYWORDS,
    # Routing keywords for intent classification
    KEYWORD_TO_INTENT,
    NEGATION_PATTERNS,
    POSITIVE_INTENT_PATTERNS,
    has_positive_intent,
    is_keyword_negated,
)
from app.schemas import (
    ActivitySettings,
    BookingTypes,
    BranchTileIds,
    DocumentBranch,
    DocumentTripInputs,
    ErrorRecord,
    FlightSettings,
    HotelSettings,
    PlanDocumentData,
    PlanDocumentResponse,
    PlanRequest,
    TilesSearchRequest,
    TransportSettings,
)
from app.schemas import (
    Tile as TileSchema,
)
from app.tile_service import search_tiles

# LangSmith tracing support - optional import
try:
    from langchain_core.tracers import LangChainTracer

    LANGCHAIN_TRACER_AVAILABLE = True
except ImportError:
    LANGCHAIN_TRACER_AVAILABLE = False

# Try to import tiktoken for token counting, fallback to char-based estimation
try:
    import tiktoken

    _TIKTOKEN_AVAILABLE = True
except ImportError:
    tiktoken = None  # type: ignore
    _TIKTOKEN_AVAILABLE = False


def _env_truthy(name: str) -> bool:
    value = os.getenv(name)
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


_KNOWN_COUNTRIES_LOWER = frozenset(c.lower() for c in KNOWN_COUNTRIES)

# NOTE: CORE_FIELD_PRIORITY and CANONICAL_FIELD_ORDER imported from planner.gates.constants

# Schema version for RoutingDecisionFinal - increment only if:
# - Field names/types change
# - redirect_reason algorithm changes
ROUTING_DECISION_SCHEMA_VERSION: int = 1

# Fallback suggestions when template is missing for a field
FALLBACK_SUGGESTIONS: List[str] = [
    "Book flights",
    "Book hotels",
    "Flexible",
]

# =============================================================================
# PR-E: DEBUG LOGGING MOVED TO debug_utils.py
# =============================================================================
# The following functions have been extracted to app/debug_utils.py:
# - _debug() - Conditional debug logging
# - _debug_error() - Error logging with emoji prefix
# - _debug_suggestions() - Suggestion logging for debug visibility
# - safe_debug() - Guaranteed non-throwing debug wrapper
# - safe_debug_error() - Guaranteed non-throwing error debug wrapper
# - is_debug_enabled() - Check if debug logging is enabled
#
# They are imported at the top of this file for backwards compatibility.
# See: from app.debug_utils import _debug, _debug_error, ...

# Cache _DEBUG_LOG for local use (imported functions use their own cache)
_DEBUG_LOG = is_debug_enabled()

# Retry count for API errors (from settings)
_PLAN_MAX_RETRIES = settings.llm_max_retries


# =============================================================================
# NODE RESULT: Structured return type for safe node execution
# =============================================================================
@dataclass
class NodeResult:
    """
    Structured result from node execution for @safe_node decorator.

    This enables nodes to return explicit deltas and messages rather than
    mutating state directly, making it easier to apply or rollback changes.
    """

    # State modifications to apply (field_name -> new_value)
    delta: Dict[str, Any] = field(default_factory=dict)
    # Assistant reply text (goes to last_summary)
    reply: Optional[str] = None
    # Suggested responses to show user
    suggestions: List[str] = field(default_factory=list)
    # Error events that occurred (for journaling)
    error_events: List[Dict[str, Any]] = field(default_factory=list)
    # Whether the node completed successfully
    success: bool = True
    # Optional question target for suggestion relevance
    question_target: Optional[str] = None
    # Whether ready to generate plan
    ready_to_generate: bool = False


def _apply_node_result_to_state(
    state: "GraphState",
    result: NodeResult,
    node_name: str,
) -> "GraphState":
    """
    Apply a NodeResult to GraphState, updating fields appropriately.

    This is the single point where NodeResult changes are written to state,
    making it easy to validate or rollback.
    """
    # Apply delta to trip_inputs if present
    trip_input_fields = {
        "destinations",
        "origin",
        "start_date",
        "end_date",
        "adults",
        "children",
        "budget",
        "currency",
        "requires_assistance",
        "multi_city_intent",
        "booking_types",
        "flight_settings",
        "hotel_settings",
        "activity_settings",
        "transport_settings",
        "strategy_settings",
    }

    trip_updates = {k: v for k, v in result.delta.items() if k in trip_input_fields}
    if trip_updates:
        state, _ = _write_trip_inputs(state, node_name, **trip_updates)

    # Apply other state fields directly
    for key, value in result.delta.items():
        if key not in trip_input_fields and hasattr(state, key):
            setattr(state, key, value)

    # Set reply
    if result.reply is not None:
        state.last_summary = result.reply

    # Set suggestions
    if result.suggestions:
        state.suggested_responses = result.suggestions

    # Set question target
    if result.question_target:
        state.question_target = result.question_target

    # Set ready state
    state.ready_to_generate = result.ready_to_generate

    # Record error events
    if result.error_events:
        if "error_events" not in state.metadata:
            state.metadata["error_events"] = []
        state.metadata["error_events"].extend(result.error_events)

    return state


def safe_node(node_name: str):
    """
    Decorator that wraps a graph node with comprehensive error handling.

    Guarantees:
    1. assistant_response is always set (via fallback if needed)
    2. State is never corrupted - uses snapshot for recovery
    3. Exceptions never propagate to the graph runner
    4. All errors are logged via safe_debug (which cannot throw)

    Usage:
        @safe_node("my_node")
        async def my_node(state: GraphState) -> GraphState:
            # Node implementation
            return state
    """

    def decorator(func: Callable):
        async def wrapper(state: "GraphState") -> "GraphState":
            # Capture pre-node snapshot for potential recovery
            try:
                if hasattr(state.trip_inputs, "model_dump"):
                    pre_node_snapshot = state.trip_inputs.model_dump()
                else:
                    pre_node_snapshot = dict(state.trip_inputs)
            except Exception:
                pre_node_snapshot = {}

            try:
                # Execute the actual node
                result = await func(state)

                # Validate result has required fields
                if result is None:
                    safe_debug_error(
                        f"Node {node_name} returned None, using fallback",
                    )
                    state.last_summary = state.last_summary or "Destination?"
                    return state

                return result

            except StateRegressionError:
                # Re-raise state regression errors - these are handled by run_turn
                raise

            except Exception as e:
                # Log error safely
                safe_debug_error(
                    f"Node {node_name} failed with exception",
                    error_type=type(e).__name__,
                    error_msg=str(e)[:200],
                )

                # Increment error counter
                try:
                    _increment_state_counter("node_error_count")
                except Exception:
                    pass

                # Record error event
                try:
                    if "error_events" not in state.metadata:
                        state.metadata["error_events"] = []
                    state.metadata["error_events"].append(
                        {
                            "type": "NODE_EXCEPTION",
                            "node": node_name,
                            "error": str(e)[:200],
                        }
                    )
                except Exception:
                    pass

                # Restore state from snapshot if needed
                try:
                    # Check if trip_inputs was corrupted
                    current = (
                        state.trip_inputs.model_dump()
                        if hasattr(state.trip_inputs, "model_dump")
                        else {}
                    )
                    if not current and pre_node_snapshot:
                        # State was lost - restore from snapshot
                        for key, value in pre_node_snapshot.items():
                            if hasattr(state.trip_inputs, key):
                                setattr(state.trip_inputs, key, value)
                        safe_debug("Restored trip_inputs from pre-node snapshot", node=node_name)
                except Exception:
                    pass

                # Generate fallback response
                try:
                    state = _record_llm_failure(
                        state,
                        f"Node {node_name} encountered an error: {type(e).__name__}",
                    )
                except Exception:
                    # Ultimate fallback - just set a message
                    state.last_summary = "Unable to process."

                return state

        # Preserve function metadata for debugging
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    return decorator


# Emoji mapping for each node/specialist for high-visibility debug logging
_NODE_EMOJIS: dict[str, str] = {
    # Core nodes
    "extractor": "🔍",
    "normalize_inputs": "📐",
    "router": "🧭",
    "validate_and_merge": "✅",
    "response_polish": "✨",
    "summarize": "📝",
    "branch_postprocess": "🌿",
    "tile_search": "🗺️",
    "short_circuit_responder": "⚡",
    # Short-circuit detection & fast-path routing
    "short_circuit": "🔌",
    "fast_path": "🏎️",
    # Specialists
    "specialist:required_fields": "📋",
    "specialist:hotels": "🏨",
    "specialist:flights": "✈️",
    "specialist:activities": "🎭",
    "specialist:transport": "🚗",
    "specialist:correction": "🔧",
    "specialist:general": "🌐",
    "general_node": "🌐",
    # Strategy
    "strategy_node": "🎯",
    "boating": "⛵",
    "hiking": "🥾",
    "skiing": "⛷️",
    "diving": "🤿",
    "cycling": "🚴",
}

# Cache hit emoji for debug logging
_CACHE_EMOJI = "💾"

# Token usage emoji for high-visibility token logging
_TOKEN_EMOJI = "🪙"


def _debug_cache_hit(cache_name: str, key: str = "", value_preview: str = "") -> None:
    """Log cache hit for debugging with optional value preview."""
    if _DEBUG_LOG:
        key_info = f" key={key[:50]}" if key else ""
        # Show first 80 chars of cached value if provided
        val_info = ""
        if value_preview:
            preview = value_preview.replace("\n", " ")[:80]
            val_info = f" => '{preview}...'"
        print(
            f"[PLAN_GRAPH DEBUG] {_CACHE_EMOJI}{_CACHE_EMOJI}{_CACHE_EMOJI} "
            f"CACHE HIT: {cache_name}{key_info}{val_info}"
        )


def _debug_node_entry(node_name: str, state: "GraphState") -> Tuple[str, int]:
    """
    Log entry into a graph node and record in journal.

    Returns:
        Tuple of (event_guid, start_ns) for this node execution.
        start_ns is used by _debug_node_exit to compute duration.
    """
    # Record in journal (performs tripwire checks, emits telemetry node_start)
    event_guid, start_ns = record_node_run(state, node_name)

    if _DEBUG_LOG:
        ti = state.trip_inputs
        # Get emoji for node, or default rocket
        emoji = _NODE_EMOJIS.get(node_name, "🚀")
        extras = " ".join(
            f"{k}={v}"
            for k, v in {
                "user_text": (
                    state.user_text[:50] + "..." if len(state.user_text) > 50 else state.user_text
                ),
                "destinations": ti.destinations,
                "origin": ti.origin,
                "intent": state.intent,
            }.items()
        )
        print(
            f"[PLAN_GRAPH DEBUG] {emoji}{emoji}{emoji} "
            f"ENTERING {node_name} {emoji}{emoji}{emoji} {extras}"
        )

    return event_guid, start_ns


def _debug_node_exit(
    node_name: str,
    state: "GraphState",
    start_ns: int = 0,
    *,
    produced_response: bool = False,
    error: Optional[str] = None,
) -> None:
    """
    Log exit from a graph node, update journal, and emit telemetry.

    Args:
        node_name: Name of the node
        state: Current graph state
        start_ns: Start timestamp from _debug_node_entry (0 if not tracked)
        produced_response: Whether this node wrote the assistant response
        error: Error message if node failed
    """
    # Update journal entry with final LLM count
    update_node_exit(state, node_name)

    # Emit telemetry node_end if start_ns is valid
    if start_ns > 0:
        mark_node_end(state, node_name, start_ns, produced_response=produced_response, error=error)

    if _DEBUG_LOG:
        emoji = _NODE_EMOJIS.get(node_name, "🚀")
        extras = " ".join(
            f"{k}={v}"
            for k, v in {
                "ready": state.ready_to_generate,
                "errors": len(state.errors),
                "branches": len(state.branches),
            }.items()
        )
        print(
            f"[PLAN_GRAPH DEBUG] {emoji}{emoji}{emoji} "
            f"EXITING {node_name} {emoji}{emoji}{emoji} {extras}"
        )


# =============================================================================
# V12: EXECUTION INSTRUMENTATION (Node Journal, Tripwires, Response Guard)
# =============================================================================
# Provides durable observability for duplicate node detection and prevention.
# Three duplication classes:
#   A. Same node executed twice in one turn (true cycle)
#   B. Multiple nodes wrote user-facing response (double-writer)
#   C. Logging/tracing artifact (events duplicated, execution not)

# Maximum steps per turn before abort (safety tripwire)
MAX_STEPS_PER_TURN: int = 25

# Nodes allowed to execute more than once per turn (explicit allowlist)
# Empty by default - no node should run twice in a healthy graph
MULTI_EXEC_ALLOWLIST: frozenset = frozenset()


class DuplicationClass(str, Enum):
    """Classification of duplication detected in a turn."""

    NONE = "none"  # No duplication
    SAME_NODE_TWICE = "class_a"  # Same node ran twice (true cycle)
    DOUBLE_WRITER = "class_b"  # Multiple nodes wrote response
    LOGGING_ARTIFACT = "class_c"  # Same event logged twice (not real dupe)


@dataclass
class NodeRunEntry:
    """Single entry in the per-turn node execution journal."""

    seq: int  # Monotonic sequence number
    node_name: str  # Name of node executed
    event_guid: str  # Unique GUID for this execution
    router_decision: Optional[str] = None  # Edge/condition that led here
    question_target: Optional[str] = None  # Active question target
    missing_fields: Optional[List[str]] = None  # Missing core fields at entry
    produced_response: bool = False  # Did this node write assistant response?
    llm_calls_before: int = 0  # LLM call count before node
    llm_calls_after: int = 0  # LLM call count after node
    timestamp_ms: float = 0.0  # Timestamp for timing analysis


def _get_trace_envelope(metadata: Dict[str, Any]) -> Optional[TraceEnvelope]:
    """
    Retrieve TraceEnvelope from metadata if present and tracing is enabled.

    Returns None if:
    - No envelope in metadata
    - Envelope has trace_enabled=False
    """
    env_dict = metadata.get(TRACE_ENVELOPE)
    if not env_dict or not isinstance(env_dict, dict):
        return None
    try:
        env = TraceEnvelope.from_dict(env_dict)
        if not env.trace_enabled:
            return None
        return env
    except Exception:
        return None


def init_turn_instrumentation(metadata: Dict[str, Any]) -> str:
    """
    Initialize per-turn instrumentation in metadata.

    Sets up:
    - node_run_journal: Append-only list of NodeRunEntry dicts
    - visited_nodes: Set of nodes executed this turn
    - step_count: Counter for tripwire
    - response_claimed_by: Guard for single response writer
    - turn_canary: UUID to verify state mutations persist

    Returns:
        turn_canary UUID for validation

    Note: This function is kept for backward compatibility.
    PR2: Now delegates to init_turn_metadata from planner.meta
    """
    turn_canary = uuid4().hex
    metadata[NODE_RUN_JOURNAL] = []
    metadata[VISITED_NODES] = set()
    metadata[STEP_COUNT] = 0
    metadata[RESPONSE_CLAIMED_BY] = None
    metadata[TURN_CANARY] = turn_canary
    metadata[MUTATION_COUNTER] = 0
    return turn_canary


def record_node_run(
    state: "GraphState",
    node_name: str,
    *,
    router_decision: Optional[str] = None,
) -> Tuple[str, int]:
    """
    Record a node execution in the journal and perform tripwire checks.

    Call this at the START of each node (after _debug_node_entry).

    Returns:
        Tuple of (event_guid, start_ns) for this execution.
        start_ns is used to compute duration when calling mark_node_end.

    Raises:
        RuntimeError: If tripwire triggered (max steps or repeat node)
    """
    meta = state.metadata
    event_guid = uuid4().hex[:12]
    start_ns = now_ns()

    # Initialize if missing (defensive)
    if NODE_RUN_JOURNAL not in meta:
        init_turn_instrumentation(meta)

    # Increment step counter
    meta[STEP_COUNT] = meta.get(STEP_COUNT, 0) + 1
    step_count = meta[STEP_COUNT]

    # Tripwire: max steps exceeded
    if step_count > MAX_STEPS_PER_TURN:
        journal = meta.get(NODE_RUN_JOURNAL, [])
        _debug_error(
            "TRIPWIRE: Max steps exceeded",
            step_count=step_count,
            max_steps=MAX_STEPS_PER_TURN,
            journal_length=len(journal),
        )
        # Mark in metadata for observability
        meta[TRIPWIRE_TRIGGERED] = "max_steps"
        # Force verbose telemetry on tripwire
        envelope = _get_trace_envelope(meta)
        if envelope:
            force_verbose_on_anomaly(envelope)
            meta[TRACE_ENVELOPE] = envelope.to_dict()
        # PR4: Raise in test mode for immediate failure
        raise_if_test_mode(f"TRIPWIRE: Max steps exceeded: {step_count} > {MAX_STEPS_PER_TURN}")

    # Tripwire: same node executed twice (unless in allowlist)
    visited = meta.get(VISITED_NODES, set())
    if node_name in visited and node_name not in MULTI_EXEC_ALLOWLIST:
        journal = meta.get(NODE_RUN_JOURNAL, [])
        _debug_error(
            "TRIPWIRE: Node executed twice",
            node=node_name,
            step_count=step_count,
            previous_executions=[e for e in journal if e.get("node_name") == node_name],
        )
        # Mark in metadata for observability
        meta[TRIPWIRE_TRIGGERED] = f"repeat_node:{node_name}"
        meta[DUPLICATION_CLASS] = DuplicationClass.SAME_NODE_TWICE.value
        # Force verbose telemetry on tripwire
        envelope = _get_trace_envelope(meta)
        if envelope:
            force_verbose_on_anomaly(envelope)
            meta[TRACE_ENVELOPE] = envelope.to_dict()
        # PR4: Raise in test mode for immediate failure
        raise_if_test_mode(f"TRIPWIRE: Node {node_name} executed twice")

    # Add to visited set
    if isinstance(visited, set):
        visited.add(node_name)
        meta[VISITED_NODES] = visited

    # Increment mutation counter (canary check)
    meta[MUTATION_COUNTER] = meta.get(MUTATION_COUNTER, 0) + 1

    # Get current state for journal entry
    readiness = compute_trip_readiness(state.trip_inputs)
    llm_calls = meta.get(LLM_CALLS_THIS_TURN, 0)

    # Create journal entry
    entry = NodeRunEntry(
        seq=step_count,
        node_name=node_name,
        event_guid=event_guid,
        router_decision=router_decision or meta.get("routing_reason"),
        question_target=state.question_target,
        missing_fields=readiness.missing_core[:3] if readiness.missing_core else None,
        produced_response=False,  # Updated by claim_response_writer
        llm_calls_before=llm_calls,
        llm_calls_after=llm_calls,  # Updated at node exit
        timestamp_ms=time.time() * 1000,
    )

    # Append to journal (as dict for JSON serialization)
    meta[NODE_RUN_JOURNAL].append(asdict(entry))

    # Emit telemetry node_start event
    envelope = _get_trace_envelope(meta)
    if envelope:
        emit_node_start(
            envelope=envelope,
            node=node_name,
            event_guid=event_guid,
        )

    return event_guid, start_ns


def mark_node_end(
    state: "GraphState",
    node_name: str,
    start_ns: int,
    *,
    produced_response: bool = False,
    error: Optional[str] = None,
) -> None:
    """
    Mark the end of a node execution and emit telemetry.

    Call this at the END of each node, before returning state.

    Args:
        state: Current graph state
        node_name: Name of the node that just finished
        start_ns: Start timestamp from record_node_run
        produced_response: Whether this node wrote the assistant response
        error: Error message if node failed
    """
    meta = state.metadata

    # Update journal entry with LLM calls after and get event_guid
    llm_calls = meta.get(LLM_CALLS_THIS_TURN, 0)
    journal = meta.get(NODE_RUN_JOURNAL, [])
    event_guid = ""
    for entry in reversed(journal):
        if entry.get("node_name") == node_name:
            entry["llm_calls_after"] = llm_calls
            event_guid = entry.get("event_guid", "")
            break

    # Compute duration in milliseconds
    end_ns = now_ns()
    duration_ms = (end_ns - start_ns) / 1_000_000 if start_ns > 0 else 0.0

    # Emit telemetry node_end event
    envelope = _get_trace_envelope(meta)
    if envelope and event_guid:
        emit_node_end(
            envelope=envelope,
            node=node_name,
            event_guid=event_guid,
            duration_ms=duration_ms,
            wrote_response=produced_response,
            error=error,
        )


def claim_response_writer(state: "GraphState", node_name: str) -> bool:
    """
    Attempt to claim response writer for this turn.

    Enforces single-response-writer invariant: only one node should set
    the user-facing assistant_response per turn.

    Args:
        state: Current graph state
        node_name: Node attempting to write response

    Returns:
        True if claim successful (this node can write)
        False if already claimed by another node (should skip write)
    """
    meta = state.metadata
    current_writer = meta.get(RESPONSE_CLAIMED_BY)

    if current_writer is None:
        # First writer - claim it
        meta[RESPONSE_CLAIMED_BY] = node_name
        # Update journal entry for this node
        journal = meta.get(NODE_RUN_JOURNAL, [])
        for entry in reversed(journal):
            if entry.get("node_name") == node_name:
                entry["produced_response"] = True
                break
        return True

    if current_writer == node_name:
        # Same node re-claiming (e.g., during polish) - allowed
        return True

    # Different node trying to write - block and log
    _debug(
        "Response writer blocked",
        attempting_node=node_name,
        claimed_by=current_writer,
    )
    meta[DUPLICATION_CLASS] = DuplicationClass.DOUBLE_WRITER.value
    meta.setdefault("blocked_writers", []).append(node_name)
    # PR4: Raise in test mode for immediate failure
    raise_if_test_mode(
        f"DOUBLE_WRITER: response_claimed_by already set to '{current_writer}', "
        f"node '{node_name}' attempted to claim"
    )
    return False


def update_node_exit(state: "GraphState", node_name: str) -> None:
    """
    Update journal entry on node exit with final LLM call count.

    Call this at the END of each node (before _debug_node_exit).
    """
    meta = state.metadata
    journal = meta.get(NODE_RUN_JOURNAL, [])
    llm_calls = meta.get(LLM_CALLS_THIS_TURN, 0)

    # Update the most recent entry for this node
    for entry in reversed(journal):
        if entry.get("node_name") == node_name:
            entry["llm_calls_after"] = llm_calls
            break


def classify_turn_duplication(state: "GraphState") -> DuplicationClass:
    """
    Analyze the turn journal and classify any duplication detected.

    Call this at end-of-turn to get final classification.
    """
    meta = state.metadata

    # Check for explicitly set duplication class
    if DUPLICATION_CLASS in meta:
        return DuplicationClass(meta[DUPLICATION_CLASS])

    journal = meta.get(NODE_RUN_JOURNAL, [])
    if not journal:
        return DuplicationClass.NONE

    # Check for same node appearing twice
    node_counts: Dict[str, int] = {}
    for entry in journal:
        node = entry.get("node_name", "unknown")
        node_counts[node] = node_counts.get(node, 0) + 1

    for node, count in node_counts.items():
        if count > 1 and node not in MULTI_EXEC_ALLOWLIST:
            return DuplicationClass.SAME_NODE_TWICE

    # Check for multiple response writers
    writers = [e for e in journal if e.get("produced_response")]
    if len(writers) > 1:
        return DuplicationClass.DOUBLE_WRITER

    return DuplicationClass.NONE


def dump_turn_journal(state: "GraphState") -> None:
    """
    Dump the turn journal to debug log at end-of-turn.

    Includes duplication classification and summary statistics.
    """
    if not _DEBUG_LOG:
        return

    meta = state.metadata
    journal = meta.get(NODE_RUN_JOURNAL, [])

    if not journal:
        return

    # Compute statistics
    duplication = classify_turn_duplication(state)
    step_count = meta.get(STEP_COUNT, 0)
    total_llm_calls = meta.get(LLM_CALLS_THIS_TURN, 0)
    tripwire = meta.get(TRIPWIRE_TRIGGERED)

    # Node sequence
    node_seq = " → ".join(e.get("node_name", "?") for e in journal)

    _debug(
        "TURN_JOURNAL_SUMMARY",
        step_count=step_count,
        duplication_class=duplication.value,
        llm_calls=total_llm_calls,
        tripwire=tripwire or "none",
        node_sequence=node_seq[:200],
    )

    # If duplication detected, dump full journal for debugging
    if duplication != DuplicationClass.NONE:
        _debug_error(
            "Duplication detected - full journal",
            duplication_class=duplication.value,
        )
        for entry in journal:
            _debug(
                f"  [{entry.get('seq')}] {entry.get('node_name')}",
                guid=entry.get("event_guid"),
                llm_before=entry.get("llm_calls_before"),
                llm_after=entry.get("llm_calls_after"),
                produced_response=entry.get("produced_response"),
            )


# =============================================================================
# OBSERVABILITY HELPERS
# =============================================================================


# P1: GatePrecedence now imported from planner.gates module
# This import provides backwards compatibility

# =============================================================================
# STRATEGY TOPIC TO NODE MAPPING
# =============================================================================
# Explicit mapping from strategy topic to specialist node name
STRATEGY_TOPIC_TO_NODE: Dict[str, str] = {
    "hiking": "strategy_node",
    "diving": "strategy_node",
    "skiing": "strategy_node",
    "cycling": "strategy_node",
    "boating": "strategy_node",
}

# NOTE: TOPIC_SWITCH_OVERRIDE_PHRASES and TOPIC_SWITCH_INTENT_VERBS
# are now imported from pattern_matching.py


# =============================================================================
# GATE EVALUATOR (Phase 6 Consolidation)
# =============================================================================
# Centralized gate evaluation logic. All routing decisions go through here.

# P1: GateResult now imported from planner.gates module
# This import provides backwards compatibility
# P3: Import gate constants from planner.gates
# These are now defined in gates/constants.py

# P3: Import TripReadiness from planner.gates
# The dataclass is now defined in gates/readiness.py


@dataclass
class RoutingDecisionFinal:
    """
    End-of-turn routing decision record for observability and golden trace testing.

    Emitted once at the end of run_turn() to capture the full routing story:
    - gate_result: What the gate decided
    - executed_node: What node actually produced the response
    - redirect_reason: Why they differ (if applicable)

    Schema version changes:
    - Increment ROUTING_DECISION_SCHEMA_VERSION only if field names/types change
      or redirect_reason algorithm changes.
    """

    # Gate's routing decision (immutable copy)
    gate_result: GateResult
    # First message-producing node (from metadata.response_source_node)
    executed_node: str
    # Redirect reason if executed_node != gate_result.destination
    # Values: "llm_budget_blocked", "blocking_errors", "missing_core", "guard_redirect"
    redirect_reason: Optional[str] = None
    # Response generation provenance (template, llm, codegen, etc.)
    response_generation_provenance: str = "unknown"
    # Canonical question_target at end of turn
    question_target_out: Optional[str] = None
    # Canonical field names actually written by _write_trip_inputs (stable sorted)
    deltas_applied: List[str] = field(default_factory=list)
    # LLM nodes called this turn (populated by can_call_llm)
    llm_nodes_called_this_turn: List[str] = field(default_factory=list)
    # End-of-turn LLM budget used
    llm_budget_used: int = 0
    # Error count
    errors_count: int = 0
    # Schema version (for replay tooling compatibility)
    schema_version: int = ROUTING_DECISION_SCHEMA_VERSION
    # Build metadata for trace correlation
    build_git_sha: str = "unknown"
    request_id: str = ""


# Module-level stats for routing decisions (exposed via get_graph_stats)
_routing_stats = {
    "keyword_bypasses": 0,  # Router skipped via keyword heuristic
    "router_calls": 0,  # Router LLM was invoked
    "negation_defers": 0,  # Keyword was negated, deferred to router
    "core_fields_gate_bypasses": 0,  # CORE_FIELDS_GATE triggered
    "high_conf_bypasses": 0,  # High-confidence bypass triggered
    "positive_intent_bypasses": 0,  # Positive intent + keyword bypass
    "noop_gate_triggered": 0,  # No-op gate for vague affirmations
    "total_turns": 0,  # Total routing decisions made
    "normal_collection_path": 0,  # extractor→router→required_fields path
}

# Module-level stats for template usage (exposed via get_graph_stats)
_template_stats = {
    "template_hits": 0,  # Template found and used
    "template_misses": 0,  # No template, fell back to LLM
    "low_conf_accepted": 0,  # Harmless low-conf field accepted
    "suggestions_generated": 0,  # SuggestionBuilder invocations
}

# NOTE: StrategyExpansionTarget, StrategyTier, STRATEGY_TIER_MAX_TOKENS extracted in P4.
# If you need to modify them, edit: backend/app/planner/gates/checks/strategy.py


# Module-level stats for strategy node (exposed via get_graph_stats)
_strategy_stats = {
    "stage1_calls": 0,  # Stage 1 (shortlist) invocations
    "stage2_calls": 0,  # Stage 2 (full itinerary) invocations
    # Tier-based tracking
    "tier_outline": 0,  # OUTLINE tier calls
    "tier_section": 0,  # SECTION tier calls
    "tier_full": 0,  # FULL tier calls
    # Section-based tracking
    "section_day_details": 0,
    "section_routes": 0,
    "section_logistics": 0,
    "section_budget": 0,
    "section_gear": 0,
    "section_contingencies": 0,
}

# Module-level stats for response polish (exposed via get_graph_stats)
_polish_stats = {
    "deterministic_polish": 0,  # Rule-based polish applied
    "llm_polish": 0,  # LLM polish invoked
    "polish_skipped": 0,  # No polish needed
}

# Module-level stats for extractor mode selection (exposed via get_graph_stats)
_extractor_stats = {
    "light_mode": 0,  # Light extractor (128 tokens)
    "full_mode": 0,  # Full extractor (400 tokens)
    "dense_input_chars": 0,  # Triggered by char count
    "dense_input_sentences": 0,  # Triggered by sentence count
    "dense_input_commas": 0,  # Triggered by comma list
    "dense_input_keywords": 0,  # Triggered by settings keywords
    # Phase 2: Two-factor trigger tracking
    "full_by_multifactor": 0,  # FULL triggered by 2+ signals
    "full_by_settings_keywords": 0,  # FULL triggered by settings keywords
    "full_by_near_ready": 0,  # FULL triggered by near-ready state
    "full_by_structured_list": 0,  # FULL triggered by comma/multi-dest list
    "full_by_long_input": 0,  # FULL triggered by long input
    "full_by_multi_sentence": 0,  # FULL triggered by multi-sentence
    "full_rejected_single_factor": 0,  # FULL rejected (only 1 signal)
}

# Phase 5: Gate evaluation stats for observability
# Tracks which gates fire most frequently and in what order
_gate_stats = {
    "short_circuit_fired": 0,  # SHORT_CIRCUIT gate
    "infeasibility_fired": 0,  # INFEASIBILITY_DETECTION gate
    "fast_path_fired": 0,  # FAST_PATH gate
    "strategy_pre_core_value_fired": 0,  # STRATEGY_PRE_CORE_VALUE gate (value-first strategy)
    "core_collection_fired": 0,  # CORE_COLLECTION gate
    "question_keyword_fired": 0,  # QUESTION_KEYWORD gate (question-word + keyword combo)
    "scoring_router_fired": 0,  # Phase 3: Scoring-based deterministic router
    "router_llm_fired": 0,  # ROUTER_LLM fallback
    "total_gate_evaluations": 0,  # Total routing decisions
    # Additional metrics for strategy pre-core value
    "required_fields_first_question_destinations_rate": 0,  # Destinations asked first rate
    "turns_to_first_destination": 0,  # Cumulative turns before destination provided
    "session_end_after_required_fields": 0,  # Sessions ending at required_fields
}

# Phase 7: LQA (Last Question Answer) pre-pass stats for observability
# Tracks how often the LQA pre-pass succeeds in parsing simple answers
_lqa_stats = {
    "attempts": 0,  # Total LQA pre-pass invocations
    "hits": 0,  # Successful deterministic extraction (extractor skipped)
    "successes": 0,  # V36: Suggestion click parsed successfully
    "bails": 0,  # Fell through to extractor
    # Bail reasons breakdown
    "bail_pending_action": 0,  # pending_action was set
    "bail_no_question_target": 0,  # No question_target set
    "bail_too_long": 0,  # Input exceeded lqa_max_length
    "bail_multi_intent": 0,  # Multi-intent pattern detected
    "bail_negation": 0,  # Negation/correction pattern detected
    "bail_validation_fail": 0,  # Field validation failed
}

# =============================================================================
# PHASE 3: ROUTER OPTIMIZATION STATS
# =============================================================================
# Tracks deterministic router bypass rate and cache normalization effectiveness.
_router_stats = {
    "deterministic_bypasses": 0,  # Router LLM avoided via scoring
    "scoring_fallback_to_llm": 0,  # Score too low, fell to LLM
    "cache_normalization_hits": 0,  # Cache hit after normalizing confirmation
}

# =============================================================================
# CONFIRMATION NORMALIZATION FOR CACHE KEY
# =============================================================================
# Map equivalent confirmation variants to a canonical form for cache key stability.
# This improves cache hit rate: "ok", "okay", "yes", "sure" → "[CONFIRM]"
_CONFIRMATION_VARIANTS = frozenset(
    {
        "ok",
        "okay",
        "o.k.",
        "o.k",
        "yes",
        "yep",
        "yeah",
        "yea",
        "yup",
        "sure",
        "sure thing",
        "sounds good",
        "sounds great",
        "looks good",
        "looks great",
        "perfect",
        "great",
        "fine",
        "alright",
        "all right",
        "good",
        "nice",
        "cool",
        "got it",
        "gotcha",
        "understood",
        "thanks",
        "thank you",
        "thx",
        "proceed",
        "go ahead",
        "let's do it",
        "do it",
        # PR7: Additional confirmation variants
        "absolutely",
        "definitely",
        "for sure",
        "of course",
        "works for me",
        "that works",
        "approved",
        "confirmed",
        "affirmative",
        "aye",
        "yessir",
        "roger",
        "agreed",
    }
)


def _normalize_user_text_for_cache(text: str) -> str:
    """
    Normalize user text for cache key computation.

    Maps equivalent confirmation variants to a canonical form to improve
    cache hit rate. For example, "ok", "okay", "yes", "sure" all map to "[CONFIRM]".

    Args:
        text: Raw user text

    Returns:
        Normalized text (canonical form for confirmations, stripped lowercase otherwise)
    """
    stripped = text.strip().lower()
    # Strip common suffixes like "!" or "."
    stripped = stripped.rstrip("!.?")

    # Check for exact confirmation match
    if stripped in _CONFIRMATION_VARIANTS:
        return "[CONFIRM]"

    # Return stripped lowercase for hashing
    return stripped


# Phase 6: Gate evaluation latency tracking (in milliseconds)
_gate_latency_samples: List[float] = []
_GATE_LATENCY_MAX_SAMPLES = 1000  # Keep last N samples for percentile calculation


def _record_gate_latency(duration_ms: float) -> None:
    """Record gate evaluation latency sample."""
    global _gate_latency_samples
    _gate_latency_samples.append(duration_ms)
    # Keep bounded
    if len(_gate_latency_samples) > _GATE_LATENCY_MAX_SAMPLES:
        _gate_latency_samples = _gate_latency_samples[-_GATE_LATENCY_MAX_SAMPLES:]


def _get_gate_latency_percentiles() -> Dict[str, float]:
    """Calculate gate evaluation latency percentiles."""
    if not _gate_latency_samples:
        return {"p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "avg_ms": 0.0}

    sorted_samples = sorted(_gate_latency_samples)
    n = len(sorted_samples)

    def percentile(p: float) -> float:
        idx = int(n * p / 100)
        return sorted_samples[min(idx, n - 1)]

    return {
        "p50_ms": round(percentile(50), 3),
        "p95_ms": round(percentile(95), 3),
        "p99_ms": round(percentile(99), 3),
        "avg_ms": round(sum(sorted_samples) / n, 3),
    }


def _increment_llm_calls(state: "GraphState") -> None:
    """Increment the LLM call counter in state metadata for observability."""
    meta = state.metadata or {}
    meta["llm_calls_made"] = meta.get("llm_calls_made", 0) + 1
    state.metadata = meta


def _record_llm_time(state: "GraphState", duration_ms: float) -> None:
    """Record LLM call duration in state metadata for observability."""
    meta = state.metadata or {}
    meta["llm_time_ms"] = meta.get("llm_time_ms", 0.0) + duration_ms
    state.metadata = meta


def _increment_cache_hits(state: "GraphState") -> None:
    """Increment the cache hit counter in state metadata for observability."""
    meta = state.metadata or {}
    meta["cache_hits"] = meta.get("cache_hits", 0) + 1
    state.metadata = meta


def _resolve_model_name(model_hint: str) -> str:
    """Resolve model hint (small/medium/large) to actual model name (gpt-4o-mini, etc.)."""
    model_map = {
        "small": settings.openai_small_model,
        "medium": settings.openai_medium_model,
        "large": settings.openai_plan_model,
    }
    return model_map.get(model_hint, model_hint)


def _record_node_tokens(state: "GraphState", node_name: str, tokens: int, model: str = "") -> None:
    """Record token usage and model for a specific node in state metadata."""
    meta = state.metadata or {}
    node_tokens = meta.get("node_tokens", {})
    node_tokens[node_name] = node_tokens.get(node_name, 0) + tokens
    meta["node_tokens"] = node_tokens
    meta["total_tokens"] = meta.get("total_tokens", 0) + tokens
    # Track which model each node used (resolve hint to actual model name)
    if model:
        node_models = meta.get("node_models", {})
        node_models[node_name] = _resolve_model_name(model)
        meta["node_models"] = node_models
    state.metadata = meta


def _debug_token_summary(state: "GraphState") -> None:
    """Print a summary of token usage across all nodes at the end of the trace."""
    if not _DEBUG_LOG:
        return
    meta = state.metadata or {}
    node_tokens = meta.get("node_tokens", {})
    total_tokens = meta.get("total_tokens", 0)

    if not node_tokens:
        return

    print("\n" + "=" * 70)
    print(f"[PLAN_GRAPH DEBUG] {_TOKEN_EMOJI} TOKEN USAGE SUMMARY {_TOKEN_EMOJI}")
    print("=" * 70)

    # Sort by token count descending
    node_models = meta.get("node_models", {})
    sorted_nodes = sorted(node_tokens.items(), key=lambda x: x[1], reverse=True)
    for node_name, tokens in sorted_nodes:
        emoji = _NODE_EMOJIS.get(node_name, "🚀")
        model = node_models.get(node_name, "")
        bar_len = min(int(tokens / 100), 40)  # Scale bar (100 tokens = 1 char, max 40)
        bar = "█" * bar_len
        model_suffix = f"  ({model})" if model else ""
        # Use fixed-width formatting: tokens right-aligned, "tokens" left-aligned in 8 chars
        print(f"  {emoji} {node_name:<30} {tokens:>8,} {'tokens':<8} {bar}{model_suffix}")

    print("-" * 70)
    print(f"  {_TOKEN_EMOJI} {'TOTAL':<30} {total_tokens:>8,} {'tokens':<8}")
    print("=" * 70 + "\n")


def _set_confidence_routing(state: "GraphState", routing: str) -> None:
    """Set the confidence routing type in state metadata for observability."""
    meta = state.metadata or {}
    meta["confidence_routing"] = routing
    state.metadata = meta


# =============================================================================
# KEYWORD HEURISTICS FOR ROUTER BYPASS
# =============================================================================
# Binary keyword matching to bypass router LLM for unambiguous intents.
# This saves ~1000 tokens per call when intent is obvious from user text.

# NOTE: KEYWORD_TO_INTENT, AMBIGUOUS_KEYWORDS, NEGATION_PATTERNS, POSITIVE_INTENT_PATTERNS,
# has_positive_intent, and is_keyword_negated are now imported from routing_keywords.py

# Create local aliases for backward compatibility with existing code
_KEYWORD_TO_INTENT = KEYWORD_TO_INTENT
_AMBIGUOUS_KEYWORDS = AMBIGUOUS_KEYWORDS
_NEGATION_PATTERNS = NEGATION_PATTERNS
_POSITIVE_INTENT_PATTERNS = POSITIVE_INTENT_PATTERNS
_has_positive_intent = has_positive_intent
_is_keyword_negated = is_keyword_negated


def _detect_intent_from_keywords(user_text_lower: str) -> tuple[str, str | None] | None:
    """
    Detect user intent from unambiguous keywords in the text.

    Returns:
        Tuple of (intent_name, strategy_topic) if unambiguous match found,
        None if no clear match (should fall through to router LLM).

    This implements binary matching: either we have a clear match or we don't.
    No confidence scoring needed - the keywords are chosen to be unambiguous.

    Negation detection: If a keyword is negated (e.g., "I don't want a hotel"),
    we skip that keyword and continue checking others. If no un-negated keyword
    is found, we defer to router LLM.

    Positive intent: If positive intent pattern detected (e.g., "I want to find"),
    combined with a domain keyword, we increase bypass confidence.

    Multi-domain detection: If 2+ distinct domain keywords are found, route to
    'general' intent for multi-domain handling.
    """
    # Check for ambiguous keywords that should defer to router
    for ambig in _AMBIGUOUS_KEYWORDS:
        if ambig in user_text_lower:
            # Don't bypass router if ambiguous term present
            return None

    # =========================================================================
    # MULTI-DOMAIN DETECTION: Check if message spans multiple domains
    # =========================================================================
    # If 2+ distinct domains detected (flights+hotels, transport+activities, etc.),
    # route to 'general' intent for multi-domain handling.
    domain_keywords = {
        "flights": {
            "flight",
            "flights",
            "fly",
            "flying",
            "plane",
            "airplane",
            "airline",
            "airport",
        },
        "hotels": {
            "hotel",
            "hotels",
            "accommodation",
            "lodging",
            "hostel",
            "airbnb",
            "where to stay",
        },
        "transport": {
            "transport",
            "train",
            "bus",
            "taxi",
            "uber",
            "rental car",
            "car rental",
            "ferry",
        },
        "activities": {
            "activity",
            "activities",
            "things to do",
            "attractions",
            "sightseeing",
            "tour",
            "museum",
            "restaurant",
        },
    }
    detected_domains = set()
    for domain, keywords in domain_keywords.items():
        for kw in keywords:
            if kw in user_text_lower and not _is_keyword_negated(user_text_lower, kw):
                detected_domains.add(domain)
                break  # One keyword per domain is enough

    if len(detected_domains) >= 2:
        _debug(
            "🌐 MULTI_DOMAIN_DETECTED: routing to general",
            domains=list(detected_domains),
            text_snippet=user_text_lower[:60],
        )
        return ("general", None)

    # Check for positive intent patterns (strengthens bypass confidence)
    positive_intent_match = _has_positive_intent(user_text_lower)

    # Check for exact keyword matches
    # We check longer phrases first to avoid partial matches
    for keyword, (intent, topic) in sorted(
        _KEYWORD_TO_INTENT.items(),
        key=lambda x: len(x[0]),
        reverse=True,  # Longer keywords first
    ):
        if keyword in user_text_lower:
            # Check if keyword is negated - if so, skip it and defer to router
            if _is_keyword_negated(user_text_lower, keyword):
                _routing_stats["negation_defers"] += 1
                _debug(
                    "🚫 NEGATION_DETECTED: keyword negated, deferred to router",
                    keyword=keyword,
                    text_snippet=user_text_lower[:50],
                )
                continue

            # If positive intent detected, log with higher confidence
            if positive_intent_match:
                _routing_stats["positive_intent_bypasses"] += 1
                _debug(
                    "✅ POSITIVE_INTENT_BYPASS: strong intent + keyword match",
                    pattern=positive_intent_match,
                    keyword=keyword,
                    intent=intent,
                    tokens_saved="~1000 (router LLM call avoided)",
                )
            return (intent, topic)

    return None


# =============================================================================
# SCORING-BASED DETERMINISTIC ROUTER (Phase 3 Token Optimization)
# =============================================================================
# Multi-signal scoring to bypass router LLM for high-confidence intents.
# Each signal contributes points; if total >= threshold, bypass router.
# This catches cases where keyword heuristic alone isn't enough but
# multiple weaker signals together are reliable.

# Scoring thresholds
_ROUTER_BYPASS_THRESHOLD = 3  # Minimum score to bypass router LLM
_ROUTER_HIGH_CONFIDENCE_THRESHOLD = 5  # Score for very high confidence

# Signal weights for intent scoring
_INTENT_SIGNAL_WEIGHTS = {
    # Core signals (each worth 2 points)
    "keyword_match": 2,  # Domain keyword present
    "positive_intent": 2,  # "I want to...", "find me..."
    "question_pattern": 2,  # "what hotels", "which flights"
    # Supporting signals (each worth 1 point)
    "explicit_booking_type": 1,  # booking_types has intent enabled
    "recent_intent_match": 1,  # Same intent in previous turn
    "category_activation": 1,  # activity_settings has matching category
    # Negative signals (reduce score)
    "ambiguous_keyword": -2,  # "trip", "travel", "help"
    "negation_detected": -3,  # "don't want", "no flights"
    "question_word_only": -1,  # Question word but no domain keyword
}


@dataclass
class RouterScoringResult:
    """Result from scoring-based deterministic router."""

    intent: Optional[str]
    strategy_topic: Optional[str]
    score: int
    signals: List[str]
    should_bypass: bool = False

    def __post_init__(self):
        self.should_bypass = self.score >= _ROUTER_BYPASS_THRESHOLD


def _try_deterministic_router(
    user_text: str,
    state: "GraphState",
) -> Optional[RouterScoringResult]:
    """
    Attempt to determine intent without LLM using multi-signal scoring.

    This is more sophisticated than keyword heuristic - it scores multiple
    signals and only bypasses router if combined score exceeds threshold.

    Args:
        user_text: User input text
        state: Current graph state

    Returns:
        RouterScoringResult if score >= threshold, None to fall through to LLM
    """
    text_lower = user_text.lower().strip()
    ti = state.trip_inputs
    signals: List[str] = []
    score = 0
    detected_intent: Optional[str] = None
    detected_topic: Optional[str] = None

    # =========================================================================
    # SIGNAL 1: Ambiguous keyword detection (negative signal)
    # =========================================================================
    for ambig in _AMBIGUOUS_KEYWORDS:
        if ambig in text_lower:
            score += _INTENT_SIGNAL_WEIGHTS["ambiguous_keyword"]
            signals.append(f"ambiguous:{ambig}")
            break  # One ambiguous keyword is enough to penalize

    # =========================================================================
    # SIGNAL 2: Negation detection (strong negative signal)
    # =========================================================================
    for neg in _NEGATION_PATTERNS:
        if neg in text_lower:
            score += _INTENT_SIGNAL_WEIGHTS["negation_detected"]
            signals.append(f"negation:{neg}")
            break  # One negation is enough

    # =========================================================================
    # SIGNAL 3: Keyword match (core positive signal)
    # =========================================================================
    for keyword, (intent, topic) in sorted(
        _KEYWORD_TO_INTENT.items(),
        key=lambda x: len(x[0]),
        reverse=True,
    ):
        if keyword in text_lower:
            # Skip if keyword is negated
            if _is_keyword_negated(text_lower, keyword):
                continue
            score += _INTENT_SIGNAL_WEIGHTS["keyword_match"]
            signals.append(f"keyword:{keyword}")
            detected_intent = intent
            detected_topic = topic
            break  # Use first (longest) match

    # =========================================================================
    # SIGNAL 4: Positive intent pattern (core positive signal)
    # =========================================================================
    positive_match = _has_positive_intent(text_lower)
    if positive_match:
        score += _INTENT_SIGNAL_WEIGHTS["positive_intent"]
        signals.append(f"positive:{positive_match}")

    # =========================================================================
    # SIGNAL 5: Question pattern with domain keyword (core positive signal)
    # =========================================================================
    question_keyword_result = check_question_keyword_combo(text_lower)
    if question_keyword_result:
        score += _INTENT_SIGNAL_WEIGHTS["question_pattern"]
        intent_name, _ = question_keyword_result
        signals.append(f"question:{intent_name}")
        if detected_intent is None:
            detected_intent = intent_name
    elif any(text_lower.startswith(qw) for qw in ("what ", "which ", "how ", "where ", "when ")):
        # Question word without domain keyword - weak signal
        score += _INTENT_SIGNAL_WEIGHTS["question_word_only"]
        signals.append("question_word_only")

    # =========================================================================
    # SIGNAL 6: Explicit booking type enabled (supporting signal)
    # =========================================================================
    booking_types = ti.booking_types or {}
    if detected_intent:
        intent_to_booking = {
            "flights": "flights",
            "hotels": "hotels",
            "activities": "activities",
            "transport": "transport",
        }
        booking_key = intent_to_booking.get(detected_intent)
        if booking_key and booking_types.get(booking_key):
            score += _INTENT_SIGNAL_WEIGHTS["explicit_booking_type"]
            signals.append(f"booking_type:{booking_key}")

    # =========================================================================
    # SIGNAL 7: Recent intent match (supporting signal)
    # =========================================================================
    last_intent = state.metadata.get("last_intent")
    if last_intent and detected_intent and last_intent == detected_intent:
        score += _INTENT_SIGNAL_WEIGHTS["recent_intent_match"]
        signals.append(f"recent_intent:{last_intent}")

    # =========================================================================
    # SIGNAL 8: Category activation (supporting signal for activities/strategy)
    # =========================================================================
    activity_categories = ti.activity_settings.get("categories", [])
    if detected_intent == "strategy" and detected_topic:
        if detected_topic in [c.lower() for c in activity_categories]:
            score += _INTENT_SIGNAL_WEIGHTS["category_activation"]
            signals.append(f"category:{detected_topic}")
    elif detected_intent == "activities" and activity_categories:
        score += _INTENT_SIGNAL_WEIGHTS["category_activation"]
        signals.append(f"categories:{len(activity_categories)}")

    # =========================================================================
    # DECISION: Score threshold check
    # =========================================================================
    if score >= _ROUTER_BYPASS_THRESHOLD and detected_intent:
        _router_stats["deterministic_bypasses"] += 1
        _debug(
            "🎯 DETERMINISTIC_ROUTER: Bypassing LLM via scoring",
            intent=detected_intent,
            topic=detected_topic,
            score=score,
            threshold=_ROUTER_BYPASS_THRESHOLD,
            signals=signals,
            tokens_saved="~1000",
        )
        return RouterScoringResult(
            intent=detected_intent,
            strategy_topic=detected_topic,
            score=score,
            signals=signals,
            should_bypass=True,
        )

    # Score too low - fall through to LLM
    if score > 0:
        _router_stats["scoring_fallback_to_llm"] += 1
        _debug(
            "🎲 DETERMINISTIC_ROUTER: Score below threshold, falling to LLM",
            score=score,
            threshold=_ROUTER_BYPASS_THRESHOLD,
            signals=signals,
        )

    return None


# =============================================================================
# LLM RESPONSE CACHING (TTLCache) - v6 HARDENED CACHING
# =============================================================================
# Cache LLM responses for common patterns to reduce API calls and latency.
# Uses in-memory TTLCache - suitable for single-instance deployments.
#
# v6 HARDENING: Node-scoped caches with full thread/question isolation to prevent
# stale response cascades. Each cache entry stores a CachePayload with enough
# context for validity checking on read.

# Cache versioning for invalidation on schema/logic changes
# Bump on: gate precedence changes, readiness logic changes, cache view changes
CACHE_SCHEMA_VERSION = 1  # Bump on payload format changes
NODE_LOGIC_VERSION = {
    "required_fields": 1,  # Bump when required_fields logic changes
    "router": 1,  # Bump when router logic changes
    "extractor": 1,  # Bump when extractor logic/schema changes
    "strategy": 1,  # Bump when strategy logic changes
    "tile": 2,  # v2: Cache key includes end_date, adults, children; budget filtered client-side
}

# ---------------------------------------------------------------------------
# GATE EVALUATION CACHE - Metadata/trip_inputs view for deterministic keys
# ---------------------------------------------------------------------------
# Metadata keys that affect routing (whitelist - everything else excluded)
METADATA_CACHE_KEYS: frozenset = frozenset(
    {
        "locale",
        "currency_override",
        "partner_config_version",
        "feature_flags",  # Only if flags affect routing
    }
)

# Trip input fields that affect routing (whitelist)
ROUTING_RELEVANT_FIELDS: frozenset = frozenset(
    {
        "origin",
        "destinations",
        "start_date",
        "end_date",
        "adults",
        "children",
        "budget",
        "currency",
    }
)


def _normalize_for_cache(obj: Any) -> Any:
    """
    Recursively normalize values for deterministic JSON serialization.

    Handles: dicts (sorted keys), sets (sorted lists), datetimes (isoformat), floats (rounded).
    """
    if obj is None:
        return None
    if isinstance(obj, (str, int, bool)):
        return obj
    if isinstance(obj, float):
        return round(obj, 6)  # Avoid float precision drift
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, set):
        return sorted(_normalize_for_cache(v) for v in obj)
    if isinstance(obj, (list, tuple)):
        return [_normalize_for_cache(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _normalize_for_cache(v) for k, v in sorted(obj.items())}
    # Fallback: convert to string (but log warning in debug)
    return str(obj)


def metadata_cache_view(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Extract only routing-relevant metadata for cache key."""
    return {k: metadata[k] for k in METADATA_CACHE_KEYS if k in metadata}


def trip_inputs_cache_view(trip_inputs: Any) -> Dict[str, Any]:
    """Extract only routing-relevant trip_inputs for cache key."""
    if hasattr(trip_inputs, "model_dump"):
        full = trip_inputs.model_dump()
    else:
        full = dict(trip_inputs)
    return {k: full[k] for k in ROUTING_RELEVANT_FIELDS if k in full}


def compute_gate_cache_key(trip_inputs: Any, metadata: Dict[str, Any]) -> str:
    """
    Compute deterministic cache key from whitelisted fields only.

    NOTE: This is for GATE EVALUATION caching only, not plan content caching.
    Excludes per-turn fields (trace_id, request_id, timestamps) that would
    cause cache misses on every request.
    """
    import hashlib

    # Normalize all values for deterministic serialization
    normalized = _normalize_for_cache(
        {
            "v": CACHE_SCHEMA_VERSION,
            "inputs": trip_inputs_cache_view(trip_inputs),
            "metadata": metadata_cache_view(metadata),
        }
    )

    key_data = json.dumps(normalized, sort_keys=True)
    return hashlib.md5(key_data.encode()).hexdigest()


# Compute prompt bundle hash at module load for cache invalidation
def _compute_prompt_bundle_hash() -> str:
    """
    Compute stable hash of prompt templates for cache invalidation.

    Hash normalized raw prompt sources (not rendered) for stability.
    All prompts that affect LLM responses must be included here.
    """
    # All prompts that affect cached LLM responses
    prompt_files = [
        # Core extraction and routing
        "extractor.txt",
        "extractor_light.txt",
        "router.txt",
        "required_fields.txt",
        # Specialist nodes
        "flights.txt",
        "hotels.txt",
        "transport.txt",
        "activities.txt",
        "correction.txt",
        "general.txt",
        # Strategy nodes
        "strategy_pre_core.txt",
        "strategy_hiking.txt",
        "strategy_diving.txt",
        "strategy_skiing.txt",
        "strategy_cycling.txt",
        "strategy_boating.txt",
        # Post-processing
        "response_polish.txt",
        # Template-based responses (no LLM but affects user experience)
        "required_fields_templates.json",
    ]
    prompt_dir = Path(__file__).parent / "prompts"
    content_parts = []
    for pf in sorted(prompt_files):
        fpath = prompt_dir / pf
        if fpath.exists():
            raw = fpath.read_bytes()
            # Normalize: CRLF -> LF, strip trailing whitespace per line
            text = raw.decode("utf-8", errors="replace")
            normalized = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n"))
            content_parts.append(f"{pf}:{hashlib.md5(normalized.encode()).hexdigest()}")
    return hashlib.md5("|".join(content_parts).encode()).hexdigest()[:16]


PROMPT_BUNDLE_HASH = _compute_prompt_bundle_hash()

# Build ID for cross-deploy cache isolation (use git SHA or fallback)
PLANNER_BUILD_ID = os.environ.get("GIT_SHA", os.environ.get("BUILD_ID", "dev"))[:12]

# Gate precedence version for tracking gate logic changes (V15 renumbering)
GATE_PRECEDENCE_VERSION = "v15"


# =============================================================================
# PR-C: STRATEGY OUTPUT SIZE LIMITS
# =============================================================================
# Hard cap on strategy response size to prevent runaway LLM output

# Default truncation footer
_STRATEGY_TRUNCATION_FOOTER = "\n\nAsk if you want me to expand any section."


def truncate_preserving_newlines(
    text: str,
    cap: int,
    footer: str = _STRATEGY_TRUNCATION_FOOTER,
) -> Tuple[str, bool]:
    """
    Truncate text at last newline before cap, preserving structure.

    PR-C: Strategy Output Size Limits

    Args:
        text: Text to truncate
        cap: Maximum character limit
        footer: Footer to append if truncated

    Returns:
        (truncated_text, was_truncated)
    """
    if len(text) <= cap:
        return text, False

    # Find last newline before the cap (leaving room for footer)
    effective_cap = cap - len(footer)
    if effective_cap <= 0:
        # Footer is larger than cap - just truncate at cap
        return text[:cap], True

    # Find last newline before effective_cap
    truncate_point = text.rfind("\n", 0, effective_cap)
    if truncate_point <= 0:
        # No newline found - truncate at word boundary
        truncate_point = text.rfind(" ", 0, effective_cap)
        if truncate_point <= 0:
            truncate_point = effective_cap

    truncated = text[:truncate_point]

    # Check for unclosed markdown code blocks
    # Count ``` occurrences - if odd, we're inside a code block
    code_block_count = truncated.count("```")
    if code_block_count % 2 == 1:
        # Odd count = unclosed code block - close it
        truncated = truncated + "\n```"

    return truncated + footer, True


# =============================================================================
# PLANNER DEBUG INFO (PR-A: Debug/Config Snapshot)
# =============================================================================
def get_planner_debug_info() -> Dict[str, Any]:
    """
    Return planner configuration and build identifiers for ops debugging.

    This is a thin wrapper that reads constants/config and calls existing helpers.
    Designed to be called by /v1/admin/planner endpoint.

    Returns stable schema with admin_endpoint_version for evolution tracking.
    """
    # Compute enabled strategy topics from feature flags
    enabled_topics = []
    enabled_topics_source = "defaults"
    topic_flags = {
        "boating": settings.enable_strategy_boating,
        "hiking": settings.enable_strategy_hiking,
        "diving": settings.enable_strategy_diving,
        "skiing": settings.enable_strategy_skiing,
        "cycling": settings.enable_strategy_cycling,
    }
    for topic, enabled in topic_flags.items():
        if enabled:
            enabled_topics.append(topic)

    # Check if env override exists for strategy topics
    enable_all_override = os.environ.get("ENABLE_ALL_STRATEGY_TOPICS", "").lower() == "true"
    if enable_all_override:
        enabled_topics = list(topic_flags.keys())
        enabled_topics_source = "env_override"

    # Build cache TTL map from settings
    cache_ttl_map = {
        "response": settings.response_cache_ttl_seconds,
        "extractor": settings.extractor_cache_ttl_seconds,
        "strategy": settings.strategy_cache_ttl_seconds,
    }
    cache_ttl_source = "config"

    return {
        # Schema evolution marker
        "admin_endpoint_version": "planner_v1",
        # Build identifiers
        "prompt_bundle_hash": PROMPT_BUNDLE_HASH,
        "planner_build_id": PLANNER_BUILD_ID,
        "cache_schema_version": CACHE_SCHEMA_VERSION,
        # Strategy configuration
        "enabled_strategy_topics": sorted(enabled_topics),
        "enabled_strategy_topics_source": enabled_topics_source,
        "enable_all_strategy_topics": enable_all_override,
        # LLM budget
        "llm_budget_max_calls_non_ready": 1,
        # Hardcoded invariant: max 1 LLM call per non-ready turn
        # Cache configuration
        "cache_ttl_map_seconds": cache_ttl_map,
        "cache_ttl_map_source": cache_ttl_source,
        # Version constants
        "gate_precedence_version": GATE_PRECEDENCE_VERSION,
        "node_logic_version": NODE_LOGIC_VERSION,
        # Strategy output caps
        "strategy_output_caps": {
            "max_chars": settings.strategy_max_output_chars,
            "expansion_max_chars": settings.strategy_expansion_max_output_chars,
        },
        # PR-B: Process-level cache counters
        "cache_counters": get_cache_counters(),
        "cache_counters_scope": "process",
        "cache_counters_reset_on_restart": True,
    }


def get_planner_snapshot() -> Dict[str, Any]:
    """
    Return minimal planner snapshot for per-turn metadata.

    Subset of get_planner_debug_info() for inclusion in state.metadata["planner_snapshot"].
    """
    enabled_topics = []
    for topic, enabled in [
        ("boating", settings.enable_strategy_boating),
        ("hiking", settings.enable_strategy_hiking),
        ("diving", settings.enable_strategy_diving),
        ("skiing", settings.enable_strategy_skiing),
        ("cycling", settings.enable_strategy_cycling),
    ]:
        if enabled:
            enabled_topics.append(topic)

    return {
        "prompt_bundle_hash": PROMPT_BUNDLE_HASH,
        "planner_build_id": PLANNER_BUILD_ID,
        "cache_schema_version": CACHE_SCHEMA_VERSION,
        "enabled_strategy_topics": sorted(enabled_topics),
        "llm_budget_max_calls_non_ready": 1,
        "gate_precedence_version": GATE_PRECEDENCE_VERSION,
    }


@dataclass
class CachePayload:
    """
    Structured cache payload with full context for validity checking.

    V6 Unified: Single payload type with payload_kind for node-specific data.
    Stores enough information to validate applicability on read and
    provide meaningful discard diagnostics.
    """

    # =========================================================================
    # V6 UNIFIED FIELDS
    # =========================================================================
    payload_kind: str  # "required_fields", "router", "extractor", "strategy", "tile"
    node_name: str  # Node that created this payload
    schema_version: int  # CACHE_SCHEMA_VERSION at write time
    logic_version: int  # NODE_LOGIC_VERSION[node] at write time
    prompt_bundle_hash: str  # PROMPT_BUNDLE_HASH at write time
    planner_build_id: str  # PLANNER_BUILD_ID at write time

    # =========================================================================
    # RESPONSE DATA
    # =========================================================================
    assistant_message: str
    question_target: Optional[str]  # Canonical string, not raw object
    suggested_responses: List[str]
    suggestion_kind: Optional[str]  # travelers/dates/destinations/budget/etc
    suggestion_question_id: Optional[int]

    # =========================================================================
    # CONTEXT FOR VALIDITY CHECKING
    # =========================================================================
    thread_id: str
    user_text_hash: str
    answered_question_target: Optional[str]  # What question this answers
    answered_missing_all: List[str]  # Missing fields when cached
    core_hash: str
    ready_state_at_write: bool
    intent: Optional[str]
    model_id: str

    # =========================================================================
    # HASHES FOR DIAGNOSTICS
    # =========================================================================
    last_summary_hash: str
    response_text_hash: str
    suggestions_hash: str

    # =========================================================================
    # METADATA
    # =========================================================================
    created_at: float  # time.time()
    provenance: str = "cached"  # Always "cached" for cache entries

    # =========================================================================
    # NODE-SPECIFIC EXTRA DATA
    # =========================================================================
    # Stores node-specific fields without requiring schema changes
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for cache storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CachePayload":
        """Reconstruct from dict with backward compatibility."""
        # Handle V5 payloads without V6 fields
        if "payload_kind" not in data:
            data["payload_kind"] = "legacy"
        if "node_name" not in data:
            data["node_name"] = "unknown"
        if "schema_version" not in data:
            data["schema_version"] = 0
        if "logic_version" not in data:
            data["logic_version"] = 0
        if "prompt_bundle_hash" not in data:
            data["prompt_bundle_hash"] = ""
        if "planner_build_id" not in data:
            data["planner_build_id"] = ""
        if "extra" not in data:
            data["extra"] = {}
        return cls(**data)


# Cache configuration via settings
_RESPONSE_CACHE_TTL = settings.response_cache_ttl_seconds
_RESPONSE_CACHE_MAXSIZE = settings.response_cache_maxsize

# Legacy shared cache (deprecated, kept for backwards compatibility)
_follow_up_cache: TTLCache = TTLCache(maxsize=_RESPONSE_CACHE_MAXSIZE, ttl=_RESPONSE_CACHE_TTL)

# v6: Node-scoped caches for thread isolation
_required_fields_cache: TTLCache = TTLCache(maxsize=100, ttl=30)  # 30s TTL for question responses
_router_cache: TTLCache = TTLCache(maxsize=100, ttl=30)


# V6 UNIFIED: Cache stats per node (extended for all caches)
# =============================================================================
# PR-B: CACHE INVALID REASON CONSTANTS
# =============================================================================
# Standardized discard/eviction reasons for analytics
class CacheInvalidReason:
    """Standardized cache invalidation reason constants."""

    SCHEMA_VERSION_MISMATCH = "schema_version_mismatch"
    LOGIC_VERSION_MISMATCH = "logic_version_mismatch"
    PROMPT_BUNDLE_HASH_MISMATCH = "prompt_bundle_hash_mismatch"
    PLANNER_BUILD_ID_MISMATCH = "planner_build_id_mismatch"
    HARD_CONSTRAINT_MISMATCH = "hard_constraint_mismatch"
    READY_STATE_FLIP = "ready_state_flip"
    CONTRACT_MISMATCH = "contract_mismatch"
    TTL_EXPIRED = "ttl_expired"
    PAYLOAD_KIND_MISMATCH = "payload_kind_mismatch"
    THREAD_MISMATCH = "thread_mismatch"
    USER_TEXT_MISMATCH = "user_text_mismatch"
    QUESTION_TARGET_MISMATCH = "question_target_mismatch"
    QUESTION_ID_MISMATCH = "question_id_mismatch"
    MISSING_ALL_MISMATCH = "missing_all_mismatch"
    CORE_HASH_MISMATCH = "core_hash_mismatch"
    UNKNOWN = "unknown"


_cache_stats: Dict[str, Dict[str, int]] = {
    "required_fields": {"hits": 0, "misses": 0, "discards": 0, "evictions": 0},
    "router": {"hits": 0, "misses": 0, "discards": 0, "evictions": 0},
    "extractor": {"hits": 0, "misses": 0, "discards": 0, "evictions": 0},
    "strategy": {"hits": 0, "misses": 0, "discards": 0, "evictions": 0},
    "tile": {"hits": 0, "misses": 0, "discards": 0, "evictions": 0},
}

# =============================================================================
# PR-B: PROCESS-LEVEL ROLLING COUNTERS
# =============================================================================
# These counters aggregate across all turns for process-level observability
# Reset on process restart; not persisted
_cache_counters: Dict[str, int] = {
    "hits_total": 0,
    "misses_total": 0,
    "discards_total": 0,
    "evictions_total": 0,
}
_cache_counters_by_node: Dict[str, Dict[str, int]] = {}
_cache_counters_by_reason: Dict[str, int] = {}

# V6 UNIFIED: Per-turn cache events for observability
# Populated during turn execution, cleared at turn start
_cache_events_this_turn: List[Dict[str, Any]] = []


def _record_cache_event(node: str, action: str, reason: Optional[str] = None) -> None:
    """Record a cache event for per-turn observability."""
    _cache_events_this_turn.append(
        {
            "node": node,
            "action": action,  # hit, miss, evict, discard, set
            "reason": reason,
            "ts": time.time(),
        }
    )
    # PR-B: Update rolling counters
    _update_cache_counters(node, action, reason)


def _update_cache_counters(node: str, action: str, reason: Optional[str]) -> None:
    """Update process-level rolling counters for cache events."""
    global _cache_counters, _cache_counters_by_node, _cache_counters_by_reason

    # Update total counters
    if action == "hit":
        _cache_counters["hits_total"] += 1
    elif action == "miss":
        _cache_counters["misses_total"] += 1
    elif action == "discard":
        _cache_counters["discards_total"] += 1
    elif action == "evict":
        _cache_counters["evictions_total"] += 1

    # Update per-node counters
    if node not in _cache_counters_by_node:
        _cache_counters_by_node[node] = {"hits": 0, "misses": 0, "discards": 0, "evictions": 0}
    if action in ("hit", "miss", "discard", "evict"):
        if action == "hit":
            _cache_counters_by_node[node]["hits"] += 1
        elif action == "miss":
            _cache_counters_by_node[node]["misses"] += 1
        elif action == "discard":
            _cache_counters_by_node[node]["discards"] += 1
        elif action == "evict":
            _cache_counters_by_node[node]["evictions"] += 1

    # Update per-reason counters (for discards/evictions)
    if reason and action in ("discard", "evict"):
        # Normalize reason to base category
        reason_base = reason.split(":")[0] if ":" in reason else reason
        _cache_counters_by_reason[reason_base] = _cache_counters_by_reason.get(reason_base, 0) + 1


def get_cache_events_this_turn() -> List[Dict[str, Any]]:
    """Get cache events for current turn (for metadata emission)."""
    return _cache_events_this_turn.copy()


def clear_cache_events_this_turn() -> None:
    """Clear cache events at start of new turn."""
    _cache_events_this_turn.clear()


def summarize_cache_events(cache_events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Summarize cache events into dashboard-friendly per-node totals.

    PR-B: Cache Summary Metrics

    Args:
        cache_events: List of cache event dicts from get_cache_events_this_turn()

    Returns:
        Dict with:
        - by_node: {node: {hit, miss, discard, evict}}
        - by_reason: {reason: count}
        - hit_rate_by_node: {node: float}
    """
    by_node: Dict[str, Dict[str, int]] = {}
    by_reason: Dict[str, int] = {}

    for event in cache_events:
        node = event.get("node", "unknown")
        action = event.get("action", "unknown")
        reason = event.get("reason")

        # Initialize node counters
        if node not in by_node:
            by_node[node] = {"hit": 0, "miss": 0, "discard": 0, "evict": 0}

        # Count actions
        if action in by_node[node]:
            by_node[node][action] += 1

        # Count reasons (for discards/evictions)
        if reason and action in ("discard", "evict"):
            reason_base = reason.split(":")[0] if ":" in reason else reason
            by_reason[reason_base] = by_reason.get(reason_base, 0) + 1

    # Compute hit rates
    hit_rate_by_node: Dict[str, float] = {}
    for node, counts in by_node.items():
        total = counts["hit"] + counts["miss"]
        if total > 0:
            hit_rate_by_node[node] = counts["hit"] / total
        else:
            hit_rate_by_node[node] = 0.0

    return {
        "by_node": by_node,
        "by_reason": by_reason,
        "hit_rate_by_node": hit_rate_by_node,
    }


def get_cache_counters() -> Dict[str, Any]:
    """
    Get process-level rolling cache counters.

    PR-B: Process-level counters for /v1/admin/planner endpoint.

    Returns:
        Dict with totals, by_node, and by_reason counters.
    """
    return {
        "totals": _cache_counters.copy(),
        "by_node": {k: v.copy() for k, v in _cache_counters_by_node.items()},
        "by_reason": _cache_counters_by_reason.copy(),
    }


def _get_node_cache(node_name: str) -> TTLCache:
    """Get the cache for a specific node.

    CONSOLIDATED: Uses unified caching framework for fallback.
    """
    if node_name == "required_fields":
        return _required_fields_cache
    elif node_name == "router":
        return _router_cache
    else:
        # CONSOLIDATED: Use ResponseCache for other nodes
        from app.planner.cache.framework import ResponseCache

        return ResponseCache.get_instance()._cache


# Tier 11.4: Common version suffix for cache keys
def _cache_version_suffix(node_name: str) -> str:
    """
    Build the common version suffix used in all cache keys.

    Consolidates the version string logic that was duplicated across:
    - _compute_cache_key_v6
    - _compute_extractor_cache_key_v6
    - _compute_strategy_cache_key_v6

    Returns:
        Version suffix string: v{schema}.{node}|{prompt_hash}|{build_id}
    """
    node_version = NODE_LOGIC_VERSION.get(node_name, 0)
    return f"v{CACHE_SCHEMA_VERSION}.{node_version}|{PROMPT_BUNDLE_HASH}|{PLANNER_BUILD_ID}"


def _compute_cache_key_v6(
    node_name: str,
    thread_id: str,
    user_text_hash: str,
    question_target: Optional[str],
    question_id: Optional[int],
    missing_all: List[str],
    intent: Optional[str],
    core_hash: str,
    ready_state: bool,
    model_id: str,
) -> str:
    """
    Compute hardened cache key with full thread/question isolation.

    Key components (all required for hit):
    - node_name: Node-scoped namespace
    - thread_id: Session isolation
    - user_text_hash: Input isolation
    - question_target + question_id: Question instance isolation
    - missing_all: State isolation
    - intent: Intent isolation
    - core_hash: Core fields isolation
    - ready_state: Ready state isolation
    - model_id: Model isolation
    - CACHE_SCHEMA_VERSION: Schema version
    - NODE_LOGIC_VERSION[node]: Logic version
    - PROMPT_BUNDLE_HASH: Prompt version
    - PLANNER_BUILD_ID: Build version

    IMPORTANT: question_target is canonicalized to string, never raw object.
    """
    # Canonicalize question_target to string
    qt_str = str(question_target) if question_target else "none"
    qid_str = str(question_id) if question_id else "0"
    missing_str = ",".join(sorted(missing_all)) if missing_all else "none"
    intent_str = intent or "none"
    ready_str = "1" if ready_state else "0"

    # Tier 11.4: Use shared version suffix
    key_parts = (
        f"{node_name}|{thread_id}|{user_text_hash}|{qt_str}:{qid_str}|"
        f"{missing_str}|{intent_str}|{core_hash}|{ready_str}|{model_id}|"
        f"{_cache_version_suffix(node_name)}"
    )
    return hashlib.md5(key_parts.encode()).hexdigest()


def _validate_cache_payload(
    payload: CachePayload,
    state: "GraphState",
    current_question_target: Optional[str],
    current_question_id: Optional[int],
    current_missing_all: List[str],
    current_core_hash: str,
    current_ready_state: bool,
    node_name: str,
) -> Tuple[bool, Optional[str]]:
    """
    Validate cached payload is applicable to current turn.

    V6 UNIFIED: Enforces hard constraints including version checks:
    - Same prompt_bundle_hash (cache invalidation on prompt changes)
    - Same planner_build_id (cache invalidation on deploy)
    - Same schema_version
    - Same logic_version for the node
    - Same thread_id
    - Same user_text_hash
    - Same question_target (canonical)
    - Same question_id (if available)
    - Same missing_all (sorted) OR ready_state_at_write match
    - Same core_hash
    - Same ready_state

    Returns:
        (is_valid, discard_reason) - reason is None if valid
    """
    thread_id = state.metadata.get("thread_id", state.session_id or "")
    normalized_text = _normalize_user_text_for_cache(state.user_text or "")
    user_text_hash = hashlib.md5(normalized_text.encode()).hexdigest()[:16]

    # =========================================================================
    # V6 VERSION CHECKS (fail fast on deploy/prompt changes)
    # =========================================================================
    if payload.prompt_bundle_hash and payload.prompt_bundle_hash != PROMPT_BUNDLE_HASH:
        return (
            False,
            f"prompt_bundle_hash_mismatch:{payload.prompt_bundle_hash[:8]}!={PROMPT_BUNDLE_HASH[:8]}",
        )

    if payload.planner_build_id and payload.planner_build_id != PLANNER_BUILD_ID:
        return False, f"planner_build_id_mismatch:{payload.planner_build_id}!={PLANNER_BUILD_ID}"

    if payload.schema_version and payload.schema_version != CACHE_SCHEMA_VERSION:
        return False, f"schema_version_mismatch:{payload.schema_version}!={CACHE_SCHEMA_VERSION}"

    node_version = NODE_LOGIC_VERSION.get(node_name, 0)
    if payload.logic_version and payload.logic_version != node_version:
        return False, f"logic_version_mismatch:{payload.logic_version}!={node_version}"

    # =========================================================================
    # THREAD/SESSION CHECKS
    # =========================================================================
    if payload.thread_id != thread_id:
        return False, "thread_mismatch"

    if payload.user_text_hash != user_text_hash:
        return False, "user_text_mismatch"

    # =========================================================================
    # QUESTION STATE CHECKS
    # =========================================================================
    if payload.answered_question_target != current_question_target:
        return (
            False,
            f"question_target_mismatch:{payload.answered_question_target}!={current_question_target}",
        )

    if current_question_id is not None and payload.suggestion_question_id != current_question_id:
        return (
            False,
            f"question_id_mismatch:{payload.suggestion_question_id}!={current_question_id}",
        )

    # =========================================================================
    # STATE DRIFT CHECKS (prevent stale-but-valid)
    # =========================================================================
    payload_missing = sorted(payload.answered_missing_all)
    current_missing = sorted(current_missing_all)
    if payload_missing != current_missing:
        return False, f"missing_all_mismatch:{len(payload_missing)}!={len(current_missing)}"

    if payload.core_hash != current_core_hash:
        return False, "core_hash_mismatch"

    # Never serve not-ready response when ready (or vice versa)
    if payload.ready_state_at_write != current_ready_state:
        return False, f"ready_state_mismatch:{payload.ready_state_at_write}!={current_ready_state}"

    # =========================================================================
    # SUGGESTION CONTRACT CHECK
    # =========================================================================
    if payload.suggestion_kind and current_question_target:
        qt_category = _get_question_target_category(current_question_target)
        if payload.suggestion_kind != qt_category:
            return False, f"suggestion_contract_violation:{payload.suggestion_kind}!={qt_category}"

    return True, None


def _get_question_target_category(question_target: Optional[str]) -> Optional[str]:
    """Map question_target to suggestion category for contract validation."""
    if not question_target:
        return None
    qt_lower = question_target.lower()
    if qt_lower in ("dates", "start_date", "end_date"):
        return "dates"
    elif qt_lower in ("destinations", "origin"):
        return "places"
    elif qt_lower in ("travelers", "adults"):
        return "travelers"
    elif qt_lower == "budget":
        return "budget"
    return qt_lower


def _evict_cache_entry(cache: TTLCache, key: str, node_name: str, reason: str) -> None:
    """Evict a cache entry and log the reason."""
    if key in cache:
        del cache[key]
        _cache_stats[node_name]["evictions"] += 1
        _debug(
            "CACHE_EVICT",
            node=node_name,
            key_prefix=key[:16],
            reason=reason,
        )


def get_cached_response_v6(
    node_name: str,
    state: "GraphState",
    current_question_target: Optional[str],
    current_question_id: Optional[int],
    current_missing_all: List[str],
    current_ready_state: bool,
) -> Optional[CachePayload]:
    """
    Get cached response with full validity checking.

    On invalid payload: evicts entry and returns None.
    On valid payload: sets provenance to "cached" and returns payload.

    Returns:
        CachePayload if valid hit, None if miss or invalid
    """
    cache = _get_node_cache(node_name)
    thread_id = state.metadata.get("thread_id", state.session_id or "")
    normalized_text = _normalize_user_text_for_cache(state.user_text or "")
    user_text_hash = hashlib.md5(normalized_text.encode()).hexdigest()[:16]
    core_hash = _get_core_fields_state(state.trip_inputs)
    model_id = settings.llm_model if hasattr(settings, "llm_model") else "gpt-4o-mini"
    intent = state.intent

    # Compute cache key
    cache_key = _compute_cache_key_v6(
        node_name=node_name,
        thread_id=thread_id,
        user_text_hash=user_text_hash,
        question_target=current_question_target,
        question_id=current_question_id,
        missing_all=current_missing_all,
        intent=intent,
        core_hash=core_hash,
        ready_state=current_ready_state,
        model_id=model_id,
    )

    cached_data = cache.get(cache_key)
    if cached_data is None:
        _cache_stats[node_name]["misses"] += 1
        return None

    # Reconstruct payload
    try:
        payload = CachePayload.from_dict(cached_data)
    except (TypeError, KeyError) as e:
        _debug("CACHE_PAYLOAD_CORRUPT", node=node_name, error=str(e))
        _evict_cache_entry(cache, cache_key, node_name, f"corrupt_payload:{e}")
        _cache_stats[node_name]["discards"] += 1
        return None

    # Validate payload applicability
    is_valid, discard_reason = _validate_cache_payload(
        payload=payload,
        state=state,
        current_question_target=current_question_target,
        current_question_id=current_question_id,
        current_missing_all=current_missing_all,
        current_core_hash=core_hash,
        current_ready_state=current_ready_state,
        node_name=node_name,
    )

    if not is_valid:
        # Evict invalid entry (don't leave poisoned entries)
        _evict_cache_entry(cache, cache_key, node_name, discard_reason or "unknown")
        _cache_stats[node_name]["discards"] += 1
        _debug(
            "CACHE_DISCARD",
            node=node_name,
            key_prefix=cache_key[:16],
            reason=discard_reason,
            # Log hashes, not large text
            payload_summary_hash=payload.last_summary_hash[:8],
            payload_question_target=payload.answered_question_target,
        )
        return None

    # Valid hit
    _cache_stats[node_name]["hits"] += 1
    _debug_cache_hit(node_name, cache_key[:16])
    _increment_cache_hits(state)

    # Set parse provenance to "cached"
    set_parse_provenance_once(state, "cached", f"cache_hit:{node_name}")

    return payload


def set_cached_response_v6(
    node_name: str,
    state: "GraphState",
    assistant_message: str,
    question_target: Optional[str],
    suggested_responses: List[str],
    suggestion_kind: Optional[str],
    current_missing_all: List[str],
    current_ready_state: bool,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Cache a response with full context for later validity checking.

    V6 UNIFIED: Creates a CachePayload with all version info for cache invalidation.
    """
    cache = _get_node_cache(node_name)
    thread_id = state.metadata.get("thread_id", state.session_id or "")
    normalized_text = _normalize_user_text_for_cache(state.user_text or "")
    user_text_hash = hashlib.md5(normalized_text.encode()).hexdigest()[:16]
    core_hash = _get_core_fields_state(state.trip_inputs)
    model_id = settings.llm_model if hasattr(settings, "llm_model") else "gpt-4o-mini"
    intent = state.intent
    question_id = state.metadata.get("question_id_counter", 0)
    node_version = NODE_LOGIC_VERSION.get(node_name, 0)

    # Create V6 payload with version info
    payload = CachePayload(
        # V6 unified fields
        payload_kind=node_name,
        node_name=node_name,
        schema_version=CACHE_SCHEMA_VERSION,
        logic_version=node_version,
        prompt_bundle_hash=PROMPT_BUNDLE_HASH,
        planner_build_id=PLANNER_BUILD_ID,
        # Response data
        assistant_message=assistant_message,
        question_target=question_target,
        suggested_responses=suggested_responses,
        suggestion_kind=suggestion_kind,
        suggestion_question_id=question_id,
        # Context for validity
        thread_id=thread_id,
        user_text_hash=user_text_hash,
        answered_question_target=question_target,
        answered_missing_all=current_missing_all,
        core_hash=core_hash,
        ready_state_at_write=current_ready_state,
        intent=intent,
        model_id=model_id,
        # Hashes
        last_summary_hash=hashlib.md5((assistant_message or "").encode()).hexdigest()[:16],
        response_text_hash=hashlib.md5((assistant_message or "").encode()).hexdigest()[:16],
        suggestions_hash=hashlib.md5(json.dumps(sorted(suggested_responses)).encode()).hexdigest()[
            :16
        ],
        # Metadata
        created_at=time.time(),
        provenance="cached",
        # Node-specific extra data
        extra=extra or {},
    )

    # Compute cache key
    cache_key = _compute_cache_key_v6(
        node_name=node_name,
        thread_id=thread_id,
        user_text_hash=user_text_hash,
        question_target=question_target,
        question_id=question_id,
        missing_all=current_missing_all,
        intent=intent,
        core_hash=core_hash,
        ready_state=current_ready_state,
        model_id=model_id,
    )

    cache[cache_key] = payload.to_dict()
    _debug(
        "CACHE_SET",
        node=node_name,
        key_prefix=cache_key[:16],
        question_target=question_target,
        suggestions_count=len(suggested_responses),
        schema_version=CACHE_SCHEMA_VERSION,
    )


def get_cache_stats() -> Dict[str, Any]:
    """V6: Get cache statistics for all node caches.

    CONSOLIDATED: Uses unified caching framework for extractor/strategy/tile stats.
    """
    from app.planner.cache.framework import ExtractorCache, StrategyCache, TileCache

    # Get sizes from unified framework
    extractor_size = len(ExtractorCache.get_instance()._cache) if ExtractorCache._instance else 0
    strategy_size = len(StrategyCache.get_instance()._cache) if StrategyCache._instance else 0
    tile_size = len(TileCache.get_instance()._cache) if TileCache._instance else 0

    return {
        "required_fields": {
            **_cache_stats["required_fields"],
            "size": len(_required_fields_cache),
        },
        "router": {
            **_cache_stats["router"],
            "size": len(_router_cache),
        },
        "extractor": {
            **_cache_stats["extractor"],
            "size": extractor_size,
        },
        "strategy": {
            **_cache_stats["strategy"],
            "size": strategy_size,
        },
        "tile": {
            **_cache_stats["tile"],
            "size": tile_size,
        },
        "schema_version": CACHE_SCHEMA_VERSION,
        "prompt_bundle_hash": PROMPT_BUNDLE_HASH,
        "build_id": PLANNER_BUILD_ID,
        "cache_events_this_turn": get_cache_events_this_turn(),
        # PR-B: Cache summary for this turn
        "cache_summary_this_turn": summarize_cache_events(get_cache_events_this_turn()),
    }


# =============================================================================
# EXTRACTOR CACHE (Turn-level caching with hit tracking)
# =============================================================================
# Cache extractor LLM results for identical inputs within a session.
# Short TTL (60s) since extraction context changes frequently.
# Key: (session_id, user_text_hash, core_fields_hash)

_EXTRACTOR_CACHE_TTL = settings.extractor_cache_ttl_seconds
_EXTRACTOR_CACHE_MAXSIZE = settings.extractor_cache_maxsize

# V6: Extractor result cache with TTL
_extractor_cache: TTLCache = TTLCache(maxsize=_EXTRACTOR_CACHE_MAXSIZE, ttl=_EXTRACTOR_CACHE_TTL)


def _compute_extractor_cache_key_v6(
    session_id: str,
    user_text: str,
    core_fields_hash: str,
    extractor_mode: str,
    model_id: str,
) -> str:
    """
    V6: Compute cache key for extractor LLM results with version isolation.

    Key components:
    - session_id: Session isolation
    - user_text_hash: Input isolation
    - core_fields_hash: State isolation
    - extractor_mode: light/full
    - model_id: Model isolation
    - CACHE_SCHEMA_VERSION, NODE_LOGIC_VERSION, PROMPT_BUNDLE_HASH, PLANNER_BUILD_ID
    """
    normalized_text = _normalize_user_text_for_cache(user_text)
    text_hash = hashlib.md5(normalized_text.encode()).hexdigest()[:16]
    # Tier 11.4: Use shared version suffix
    key_parts = (
        f"extractor_v6|{session_id}|{text_hash}|{core_fields_hash}|{extractor_mode}|"
        f"{model_id}|{_cache_version_suffix('extractor')}"
    )
    return hashlib.md5(key_parts.encode()).hexdigest()


def _get_extractor_cached(
    session_id: str,
    user_text: str,
    core_fields_hash: str,
    extractor_mode: str,
    state: Optional["GraphState"] = None,
) -> Optional[Dict[str, Any]]:
    """
    V6: Try to get cached extractor result with validation.

    MIGRATED: Now delegates to unified caching framework via compat layer.

    Returns:
        Cached extraction dict (parsed, confidence) or None if not cached/invalid.
    """
    from app.planner.cache.compat import get_extractor_cached as _compat_get

    return _compat_get(session_id, user_text, core_fields_hash, extractor_mode, state)


def _set_extractor_cached(
    session_id: str,
    user_text: str,
    core_fields_hash: str,
    extractor_mode: str,
    result: Dict[str, Any],
) -> None:
    """
    V6: Cache an extractor LLM result with version info.

    MIGRATED: Now delegates to unified caching framework via compat layer.
    """
    from app.planner.cache.compat import set_extractor_cached as _compat_set

    _compat_set(session_id, user_text, core_fields_hash, extractor_mode, result)


def get_extractor_cache_stats() -> Dict[str, Any]:
    """
    Get extractor cache hit rate statistics.

    MIGRATED: Now delegates to unified caching framework.

    Returns:
        Dict with hits, misses, hit_rate, and cache_size
    """
    from app.planner.cache.compat import get_extractor_cache_stats as _compat_stats

    return _compat_stats()


# =============================================================================
# STRATEGY CACHE (5-min TTL, topic-keyed) - V6 UNIFIED
# =============================================================================
# Cache strategy node LLM results for repeated queries about same topic.
# Key: (session_id, topic, core_fields_hash, user_text_hash, stage0_lifecycle_hash)
# Longer TTL since strategy advice is more stable than extraction.

_STRATEGY_CACHE_TTL = settings.strategy_cache_ttl_seconds
_STRATEGY_CACHE_MAXSIZE = settings.strategy_cache_maxsize

# V6: Strategy result cache with TTL
_strategy_cache: TTLCache = TTLCache(maxsize=_STRATEGY_CACHE_MAXSIZE, ttl=_STRATEGY_CACHE_TTL)


def _compute_strategy_cache_key_v6(
    session_id: str,
    topic: str,
    core_fields_hash: str,
    user_text_hash: str,
    section_id: Optional[str],
    stage0_lifecycle_hash: Optional[str],
    model_id: str,
) -> str:
    """
    V6: Compute cache key for strategy LLM results with version isolation.

    Key components:
    - session_id, topic, section_id: Scope isolation
    - core_fields_hash, user_text_hash: State/input isolation
    - stage0_lifecycle_hash: Prevents stage0 resurrection after answer
    - model_id, versions: Model/deploy isolation
    """
    section_part = section_id or "stage1"
    lifecycle_part = stage0_lifecycle_hash or "none"
    # Tier 11.4: Use shared version suffix
    key_parts = (
        f"strategy_v6|{session_id}|{topic}|{section_part}|{core_fields_hash}|{user_text_hash}|"
        f"{lifecycle_part}|{model_id}|{_cache_version_suffix('strategy')}"
    )
    return hashlib.md5(key_parts.encode()).hexdigest()


def _get_strategy_cached(
    session_id: str,
    topic: str,
    core_fields_hash: str,
    user_text_hash: str,
    state: Optional["GraphState"] = None,
    section_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    V6: Try to get cached strategy result with validation.

    MIGRATED: Now delegates to unified caching framework via compat layer.

    Returns:
        Cached strategy response dict or None if not cached/invalid.
    """
    from app.planner.cache.compat import get_strategy_cached as _compat_get

    # Compute stage0_lifecycle_hash from state (preserves original behavior)
    stage0_lifecycle_hash = None
    if state is not None:
        active_qid = state.metadata.get("question_id_counter", 0)
        answered_qid = state.metadata.get("last_answered_question_id")
        stage0_lifecycle_hash = f"{active_qid}:{answered_qid or 0}"

    return _compat_get(
        session_id,
        topic,
        core_fields_hash,
        user_text_hash,
        section_id,
        stage0_lifecycle_hash,
        state,
    )


def _set_strategy_cached(
    session_id: str,
    topic: str,
    core_fields_hash: str,
    user_text_hash: str,
    result: Dict[str, Any],
    section_id: Optional[str] = None,
    state: Optional["GraphState"] = None,
) -> None:
    """
    V6: Cache a strategy LLM result with version info.

    MIGRATED: Now delegates to unified caching framework via compat layer.
    """
    from app.planner.cache.compat import set_strategy_cached as _compat_set

    # Compute stage0_lifecycle_hash from state (preserves original behavior)
    stage0_lifecycle_hash = None
    if state is not None:
        active_qid = state.metadata.get("question_id_counter", 0)
        answered_qid = state.metadata.get("last_answered_question_id")
        stage0_lifecycle_hash = f"{active_qid}:{answered_qid or 0}"

    _compat_set(
        session_id,
        topic,
        core_fields_hash,
        user_text_hash,
        result,
        section_id,
        stage0_lifecycle_hash,
    )


def get_strategy_cache_stats() -> Dict[str, Any]:
    """
    Get strategy cache hit rate statistics.

    MIGRATED: Now delegates to unified caching framework.

    Returns:
        Dict with hits, misses, hit_rate, and cache_size
    """
    from app.planner.cache.compat import get_strategy_cache_stats as _compat_stats

    return _compat_stats()


def reset_graph_stats() -> None:
    """
    Reset all graph statistics to initial zero values.

    Used by E2E tests to get per-scenario metrics instead of cumulative stats.
    No thread locking - assumes sequential test execution (asyncio-safe).
    """
    global _gate_latency_samples

    # Reset routing stats
    for key in _routing_stats:
        _routing_stats[key] = 0

    # Reset template stats
    for key in _template_stats:
        _template_stats[key] = 0

    # Reset strategy stats
    for key in _strategy_stats:
        _strategy_stats[key] = 0

    # Reset polish stats
    for key in _polish_stats:
        _polish_stats[key] = 0

    # Reset extractor stats
    for key in _extractor_stats:
        _extractor_stats[key] = 0

    # Reset gate stats
    for key in _gate_stats:
        _gate_stats[key] = 0

    # Reset LQA stats
    for key in _lqa_stats:
        _lqa_stats[key] = 0

    # Reset router optimization stats (Phase 3)
    for key in _router_stats:
        _router_stats[key] = 0

    # Reset gate latency samples
    _gate_latency_samples = []

    # Reset V6 unified cache stats
    for node_name in _cache_stats:
        for key in _cache_stats[node_name]:
            _cache_stats[node_name][key] = 0


def get_graph_stats() -> Dict[str, Any]:
    """
    Get comprehensive graph statistics for observability.

    Returns:
        Dict with routing stats, template stats, strategy stats, polish stats,
        extractor stats, and all cache stats merged.

        Key metrics for validating design intent:
        - router_call_rate: Should be < 30% (most routes via gates)
        - template_hit_rate: Should be > 85% (templates dominate)
        - stage_split_ratio: Should be > 3:1 (most strategy stays at Stage 1)
    """
    # Calculate derived rates for routing
    total_turns = _routing_stats["total_turns"]
    router_call_rate = _routing_stats["router_calls"] / total_turns if total_turns > 0 else 0.0
    routing_total = _routing_stats["keyword_bypasses"] + _routing_stats["router_calls"]
    keyword_bypass_rate = (
        _routing_stats["keyword_bypasses"] / routing_total if routing_total > 0 else 0.0
    )

    # Calculate derived rates for templates
    template_total = _template_stats["template_hits"] + _template_stats["template_misses"]
    template_hit_rate = (
        _template_stats["template_hits"] / template_total if template_total > 0 else 0.0
    )

    stage_split_ratio = (
        _strategy_stats["stage1_calls"] / _strategy_stats["stage2_calls"]
        if _strategy_stats["stage2_calls"] > 0
        else float(_strategy_stats["stage1_calls"]) if _strategy_stats["stage1_calls"] > 0 else 0.0
    )

    # Calculate polish rates
    polish_total = (
        _polish_stats["deterministic_polish"]
        + _polish_stats["llm_polish"]
        + _polish_stats["polish_skipped"]
    )
    llm_polish_rate = _polish_stats["llm_polish"] / polish_total if polish_total > 0 else 0.0

    # Phase 5: Calculate gate firing rates
    gate_total = _gate_stats["total_gate_evaluations"]
    zero_llm_rate = (
        (
            _gate_stats["short_circuit_fired"]
            + _gate_stats["infeasibility_fired"]
            + _gate_stats["fast_path_fired"]
        )
        / gate_total
        if gate_total > 0
        else 0.0
    )

    return {
        "routing": {
            **_routing_stats,
            "router_call_rate": round(router_call_rate, 3),
            "keyword_bypass_rate": round(keyword_bypass_rate, 3),
        },
        "templates": {
            **_template_stats,
            "template_hit_rate": round(template_hit_rate, 3),
        },
        "strategy": {
            **_strategy_stats,
            "stage_split_ratio": round(stage_split_ratio, 2),
        },
        "polish": {
            **_polish_stats,
            "llm_polish_rate": round(llm_polish_rate, 3),
        },
        "extractor": {
            **_extractor_stats,
        },
        "gates": {
            **_gate_stats,
            "zero_llm_rate": round(zero_llm_rate, 3),
            **_get_gate_latency_percentiles(),  # Phase 6: latency tracking
        },
        "lqa": {
            **_lqa_stats,
            "hit_rate": (
                round(_lqa_stats["hits"] / _lqa_stats["attempts"], 3)
                if _lqa_stats["attempts"] > 0
                else 0.0
            ),
        },
        "deterministic_pipeline": {
            **_deterministic_parse_stats,
            "total_hits": sum(
                [
                    _deterministic_parse_stats["suggestion_echo_hits"],
                    _deterministic_parse_stats["season_date_hits"],
                    _deterministic_parse_stats["relative_date_hits"],
                    _deterministic_parse_stats["travelers_hits"],
                    _deterministic_parse_stats["place_single_hits"],
                    _deterministic_parse_stats["place_multi_hits"],
                ]
            ),
        },
        "router_optimization": {
            **_router_stats,
            "deterministic_bypass_rate": (
                round(
                    _router_stats["deterministic_bypasses"]
                    / (
                        _router_stats["deterministic_bypasses"]
                        + _router_stats["scoring_fallback_to_llm"]
                    ),
                    3,
                )
                if (
                    _router_stats["deterministic_bypasses"]
                    + _router_stats["scoring_fallback_to_llm"]
                )
                > 0
                else 0.0
            ),
        },
        "extractor_cache": get_extractor_cache_stats(),
        "strategy_cache": get_strategy_cache_stats(),
        "tile_cache": get_tile_cache_stats(),
        "cache_events_this_turn": get_cache_events_this_turn(),
    }


def _compute_cache_key(
    prompt_name: str,
    core_fields_state: str,
    user_intent: str = "",
    extra: str = "",
) -> str:
    """
    Compute a cache key for LLM response caching.

    Args:
        prompt_name: Name of the prompt being used
        core_fields_state: Serialized state of core trip fields (dest, origin, date)
        user_intent: User intent archetype (quick_booking, detailed_planner, etc.)
        extra: Any additional context to include in key

    Returns:
        MD5 hash string suitable for cache key
    """
    key_parts = f"{prompt_name}|{core_fields_state}|{user_intent}|{extra}"
    return hashlib.md5(key_parts.encode()).hexdigest()


def _get_core_fields_state(trip_inputs: "TripInputs") -> str:
    """Get a serialized representation of core trip fields for cache key."""
    return json.dumps(
        {
            "destinations": sorted(trip_inputs.destinations or []),
            "origin": trip_inputs.origin,
            "start_date": trip_inputs.start_date,
            "end_date": trip_inputs.end_date,
            "budget": trip_inputs.budget,
            "adults": trip_inputs.adults,
            "children": trip_inputs.children,
        },
        sort_keys=True,
    )


def _hash_user_text(text: str, normalize: bool = True) -> str:
    """
    Hash user text for cache key stability.

    Args:
        text: User input text
        normalize: If True, normalize confirmations to canonical form

    Returns:
        MD5 hash string

    Note:
        For confirmations ("[CONFIRM]"), we don't include length suffix since
        the canonical form has a fixed length. This ensures all confirmation
        variants ("ok", "yes", "sure", etc.) hash identically.
    """
    if normalize:
        normalized = _normalize_user_text_for_cache(text)
        # Track cache normalization for observability
        if normalized == "[CONFIRM]":
            _router_stats["cache_normalization_hits"] += 1
            # No length suffix needed - canonical form is always same length
            return hashlib.md5(normalized.encode()).hexdigest()
        return hashlib.md5((normalized[:100] + str(len(normalized))).encode()).hexdigest()
    return hashlib.md5((text[:100] + str(len(text))).encode()).hexdigest()


def _get_cached_response(
    cache_or_key: Any,  # First arg: legacy TTLCache (ignored) or cache key
    key_or_state: Any = None,  # Second arg: key (if legacy) or state
    state: Optional["GraphState"] = None,  # Third arg: state (if legacy)
) -> Optional[Dict[str, Any]]:
    """Get cached response from unified caching framework.

    CONSOLIDATED: Uses ResponseCache singleton.
    Supports both old and new calling conventions:
    - Legacy: _get_cached_response(cache, key, state) - cache is ignored
    - New: _get_cached_response(key, state)

    Returns:
        Cached response dict or None if not found
    """
    from app.planner.cache.framework import ResponseCache

    # Handle both old (cache, key, state) and new (key, state) signatures
    if isinstance(cache_or_key, TTLCache):
        # Old signature: (cache, key, state) - cache is ignored
        actual_key = key_or_state
        actual_state = state
    else:
        # New signature: (key, state)
        actual_key = cache_or_key
        actual_state = key_or_state if isinstance(key_or_state, GraphState) else None

    response_cache = ResponseCache.get_instance()
    result = response_cache._cache.get(actual_key)
    if result is not None:
        _debug_cache_hit("response_cache", actual_key[:16])
        response_cache._stats.record_hit()
        if actual_state is not None:
            _increment_cache_hits(actual_state)
    else:
        response_cache._stats.record_miss()
    return result


def _set_cached_response(
    cache_or_key: Any,  # First arg: legacy TTLCache (ignored) or cache key
    key_or_response: Any = None,  # Second arg: key (if legacy) or response
    response: Optional[Dict[str, Any]] = None,  # Third arg: response (if legacy)
) -> None:
    """Set cached response in unified caching framework.

    CONSOLIDATED: Uses ResponseCache singleton.
    Supports both old and new calling conventions:
    - Legacy: _set_cached_response(cache, key, response) - cache is ignored
    - New: _set_cached_response(key, response)
    """
    from app.planner.cache.framework import ResponseCache

    # Handle both old (cache, key, response) and new (key, response) signatures
    if isinstance(cache_or_key, TTLCache):
        # Old signature: (cache, key, response) - cache is ignored
        actual_key = key_or_response
        actual_response = response
    else:
        # New signature: (key, response)
        actual_key = cache_or_key
        actual_response = key_or_response

    response_cache = ResponseCache.get_instance()
    response_cache._cache[actual_key] = actual_response
    response_cache._stats.record_set()


def clear_response_caches() -> int:
    """
    Clear all LLM response caches.

    CONSOLIDATED: Uses unified caching framework.

    Returns the number of entries that were cleared.
    """
    from app.planner.cache.framework import (
        ExtractorCache,
        GateEvaluationCache,
        ResponseCache,
        StrategyCache,
        TileCache,
        reset_all_cache_stats,
    )

    # Clear unified framework caches
    response_count = 0
    extractor_count = 0
    strategy_count = 0
    tile_count = 0
    gate_evaluation_count = 0

    if ResponseCache._instance:
        response_count = len(ResponseCache._instance._cache)
        ResponseCache._instance.clear()

    if ExtractorCache._instance:
        extractor_count = len(ExtractorCache._instance._cache)
        ExtractorCache._instance.clear()

    if StrategyCache._instance:
        strategy_count = len(StrategyCache._instance._cache)
        StrategyCache._instance.clear()

    if TileCache._instance:
        tile_count = len(TileCache._instance._cache)
        TileCache._instance.clear()

    if GateEvaluationCache._instance:
        gate_evaluation_count = len(GateEvaluationCache._instance._cache)
        GateEvaluationCache._instance.clear()

    # Clear node-scoped caches (still using direct TTLCache)
    required_fields_count = len(_required_fields_cache)
    _required_fields_cache.clear()

    router_count = len(_router_cache)
    _router_cache.clear()

    # Reset unified cache stats
    reset_all_cache_stats()

    # Also reset legacy stats for backward compatibility
    for node_name in _cache_stats:
        _cache_stats[node_name] = {"hits": 0, "misses": 0, "discards": 0, "evictions": 0}

    total = (
        response_count
        + extractor_count
        + strategy_count
        + tile_count
        + gate_evaluation_count
        + required_fields_count
        + router_count
    )
    message_prefix = "Cleared response caches: "
    message_counts = (
        f"{total} entries (response: {response_count}, extractor: {extractor_count}, "
        f"strategy: {strategy_count}, tile: {tile_count}, gate_eval: {gate_evaluation_count}, "
        f"required_fields: {required_fields_count}, router: {router_count})"
    )
    _debug(message_prefix + message_counts)
    return total


def clear_all_caches() -> int:
    """
    Clear ALL caches including response caches, validation caches, and checkpointer.

    This function should be called at the start of each test to ensure
    complete isolation between tests. It clears:
    - LLM response cache (_follow_up_cache)
    - Validation caches (place, flight, hotel, activity caches)
    - MemorySaver checkpointer storage
    - LRU caches (fuzzy_match_place, _load_prompt_cached)
    - Date normalizer singleton (reset reference date)
    - Prompt tracking set (_PROMPTS_LOADED)

    Returns the total number of cache entries cleared.
    """
    global _date_normalizer
    total_cleared = 0
    cleared_caches = []  # Track which caches were cleared for debug logging

    # Clear response caches
    response_count = clear_response_caches()
    total_cleared += response_count
    if response_count > 0:
        cleared_caches.append(f"response_caches: {response_count}")

    # Clear validation caches
    try:
        from app.validation import clear_validation_caches

        validation_count = clear_validation_caches()
        total_cleared += validation_count
        if validation_count > 0:
            cleared_caches.append(f"validation_caches: {validation_count}")
    except ImportError:
        pass  # Validation module may not be available

    # Clear checkpointer storage
    try:
        if hasattr(app, "checkpointer") and app.checkpointer is not None:
            checkpointer = app.checkpointer
            if hasattr(checkpointer, "storage"):
                storage = getattr(checkpointer, "storage", None)
                if storage is not None and isinstance(storage, dict):
                    checkpoint_count = len(storage)
                    storage.clear()
                    total_cleared += checkpoint_count
                    if checkpoint_count > 0:
                        cleared_caches.append(f"checkpointer: {checkpoint_count}")
                    _debug(f"Cleared {checkpoint_count} checkpointer entries")
    except Exception as e:
        _debug_error(f"Failed to clear checkpointer: {e}")

    # Clear prompt LRU cache (32 entries max)
    try:
        cache_info = _load_prompt_cached.cache_info()
        if cache_info.currsize > 0:
            cleared_caches.append(f"prompt_cache: {cache_info.currsize}")
            total_cleared += cache_info.currsize
        _load_prompt_cached.cache_clear()
    except AttributeError:
        pass

    # Clear Jinja2 template cache
    try:
        if hasattr(_JINJA_ENV, "cache") and _JINJA_ENV.cache:
            jinja_count = len(_JINJA_ENV.cache)
            _JINJA_ENV.cache.clear()
            if jinja_count > 0:
                cleared_caches.append(f"jinja_cache: {jinja_count}")
                total_cleared += jinja_count
    except Exception:
        pass

    # Clear prompt tracking set
    if _PROMPTS_LOADED:
        cleared_caches.append(f"prompts_loaded_set: {len(_PROMPTS_LOADED)}")
        _PROMPTS_LOADED.clear()

    # NOTE: DateNormalizer is NOT reset here.
    # DateNormalizer should be turn-scoped (created per turn with the turn's reference date),
    # not tied to cache resets. Use get_turn_date_normalizer(state) to get the proper instance.
    # Legacy: we still keep a singleton for code that hasn't been migrated yet.

    _debug(f"Cleared all caches: {total_cleared} total entries", caches_cleared=cleared_caches)
    return total_cleared


def response_cache_stats() -> dict[str, int]:
    """Return a snapshot of response cache sizes.

    CONSOLIDATED: Uses unified caching framework.
    """
    from app.planner.cache.framework import ResponseCache

    response_size = len(ResponseCache.get_instance()._cache) if ResponseCache._instance else 0
    return {
        "follow_up": response_size,  # Backward compatible key name
    }


# =============================================================================
# STARTUP WARMUP: Pre-compile templates and regexes to eliminate cold-start
# =============================================================================
# Deploy epoch tracking for cache clearing policy
_DEPLOY_EPOCH: Optional[float] = None
_DEPLOY_WINDOW_SECONDS = 300  # Allow cache clears within first 5 min of startup

# Cache hit rate tracking for observability
_warmup_stats: Dict[str, int] = {
    "prompts_warmed": 0,
    "templates_loaded": 0,
    "regexes_compiled": 0,
    "warmup_ms": 0,
}


def prewarm_prompts() -> Dict[str, int]:
    """
    Pre-compile Jinja2 templates and load required_fields_templates.json.

    Call this at startup to eliminate first-request cold-start latency.
    This is synchronous and should complete in < 100ms.

    Returns:
        Dict with warmup stats: prompts_warmed, templates_loaded, warmup_ms
    """
    import time as _time

    global _DEPLOY_EPOCH
    _DEPLOY_EPOCH = _time.time()

    start = _time.perf_counter()
    prompts_warmed = 0
    templates_loaded = 0

    # Pre-compile critical prompts (Jinja2 template compilation)
    critical_prompts = [
        "strategy_pre_core",
        "extractor_light",
        "extractor",
        "required_fields",
        "required_fields_confirm",
        "router",
        # Shared includes get compiled when their parent is compiled
    ]

    # Tier 11.3: Pre-warm strategy topic prompts for common adventure types
    # These are loaded on first request for each topic; warming them eliminates cold-start latency
    strategy_topic_prompts = [
        "strategy_hiking",
        "strategy_diving",
        "strategy_skiing",
        "strategy_cycling",
        "strategy_boating",
    ]
    for topic_prompt in strategy_topic_prompts:
        try:
            load_prompt(topic_prompt)
            prompts_warmed += 1
        except FileNotFoundError:
            # Topic may not have a dedicated prompt file; this is expected
            pass
        except Exception as e:
            _debug_error(f"Failed to prewarm strategy topic prompt: {topic_prompt}", error=str(e))

    for prompt_name in critical_prompts:
        try:
            load_prompt(prompt_name)
            prompts_warmed += 1
        except Exception as e:
            _debug_error(f"Failed to prewarm prompt: {prompt_name}", error=str(e))

    # Pre-load required_fields_templates.json
    try:
        _load_required_fields_templates()
        templates_loaded += 1
    except Exception as e:
        _debug_error("Failed to prewarm required_fields_templates.json", error=str(e))

    # Pre-compile short-circuit regex patterns (they're compiled at module load,
    # but we access them here to ensure any lazy compilation is done)
    try:
        # Access compiled patterns to ensure they're ready
        _ = GREETING_PATTERN.pattern
        _ = YES_PATTERN.pattern
        _ = NO_PATTERN.pattern
        _warmup_stats["regexes_compiled"] = 3
    except Exception:
        pass

    elapsed_ms = int((_time.perf_counter() - start) * 1000)

    _warmup_stats["prompts_warmed"] = prompts_warmed
    _warmup_stats["templates_loaded"] = templates_loaded
    _warmup_stats["warmup_ms"] = elapsed_ms

    _debug(
        "Startup warmup complete",
        prompts_warmed=prompts_warmed,
        templates_loaded=templates_loaded,
        elapsed_ms=elapsed_ms,
    )

    return {
        "prompts_warmed": prompts_warmed,
        "templates_loaded": templates_loaded,
        "warmup_ms": elapsed_ms,
    }


def get_warmup_stats() -> Dict[str, int]:
    """Return warmup statistics for observability."""
    return _warmup_stats.copy()


def get_deterministic_pipeline_stats() -> Dict[str, Any]:
    """
    Return deterministic pipeline statistics for observability.

    These stats track the MVP optimization pipeline that avoids LLM calls
    for simple answers like suggestion clicks, season/month dates, and
    single-place inputs.

    Key metrics:
    - suggestion_echo_hits: User clicked a suggestion (exact match)
    - season_date_hits: Parsed "summer", "spring", etc.
    - relative_date_hits: Parsed "next month", "next week", etc.
    - travelers_hits: Parsed "solo", "couple", "family of 4"
    - place_single_hits: Parsed single known place
    - place_multi_hits: Parsed multi-place "Paris and Rome"
    - date_ambiguous_count: Straddle-today dates requiring clarification
    - extractor_light_blocked_trivial: LLM calls blocked by pipeline
    """
    total_hits = sum(
        [
            _deterministic_parse_stats["suggestion_echo_hits"],
            _deterministic_parse_stats["season_date_hits"],
            _deterministic_parse_stats["relative_date_hits"],
            _deterministic_parse_stats["travelers_hits"],
            _deterministic_parse_stats["place_single_hits"],
            _deterministic_parse_stats["place_multi_hits"],
        ]
    )
    return {
        **_deterministic_parse_stats,
        "total_hits": total_hits,
    }


# =============================================================================
# TYPO CORRECTION HELPERS
# =============================================================================


def _apply_typo_corrections(state: "GraphState", corrections: Dict[str, str]) -> None:
    """
    Apply typo corrections to trip_inputs using the _write_trip_inputs helper.

    Args:
        state: Current graph state to modify
        corrections: Dict mapping original text -> corrected text
    """
    updates: Dict[str, Any] = {}

    # Apply to destinations
    ti = state.trip_inputs
    if ti.destinations:
        corrected_dests = [corrections.get(dest, dest) for dest in ti.destinations]
        if corrected_dests != ti.destinations:
            updates["destinations"] = corrected_dests

    # Apply to origin
    if ti.origin and ti.origin in corrections:
        updates["origin"] = corrections[ti.origin]

    if updates:
        _write_trip_inputs(state, "extractor", **updates)  # Ignore fields_changed
        _debug(
            "Applied typo corrections via _write_trip_inputs",
            corrections=corrections,
            updates=updates,
        )
    else:
        _debug("No typo corrections applied (no matching fields)")


# =============================================================================
# TOKEN ESTIMATION (ported from plan.py)
# =============================================================================

# Precise token counting via tiktoken can be surprisingly expensive in tight loops.
# Default to a cheap char-based estimate unless explicitly enabled.
_PRECISE_TOKEN_COUNT = settings.precise_token_count

# Cached tiktoken encoder singleton for performance
_TIKTOKEN_ENCODER: Optional[Any] = None
_TIKTOKEN_ENCODER_INITIALIZED = False


def _get_tiktoken_encoder() -> Optional[Any]:
    """Get or create the cached tiktoken encoder (singleton pattern)."""
    global _TIKTOKEN_ENCODER, _TIKTOKEN_ENCODER_INITIALIZED
    if not _TIKTOKEN_ENCODER_INITIALIZED:
        _TIKTOKEN_ENCODER_INITIALIZED = True
        if _TIKTOKEN_AVAILABLE:
            try:
                _TIKTOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")  # type: ignore[union-attr]
                _debug("Tiktoken encoder initialized (cl100k_base)")
            except Exception as e:
                _debug_error("Failed to initialize tiktoken encoder", error=str(e))
    return _TIKTOKEN_ENCODER


def _count_tokens(text: str) -> int:
    """Estimate token count for a text block using cached tiktoken encoder."""
    safe_text = text or ""

    # Default: fast estimate (~4 chars/token). Enable precise mode via env var.
    if not _PRECISE_TOKEN_COUNT or not _TIKTOKEN_AVAILABLE:
        return len(safe_text) // 4

    encoder = _get_tiktoken_encoder()
    if encoder is None:
        return len(safe_text) // 4

    try:
        return len(encoder.encode(safe_text))
    except Exception:
        # Fallback to character-based estimation
        return len(safe_text) // 4


def _estimate_prompt_tokens(prompt: str, parsed_inputs: Dict[str, Any]) -> int:
    """Estimate total tokens for a prompt including injected data."""
    token_count = _count_tokens(prompt)
    token_count += _count_tokens(json.dumps(parsed_inputs))
    return token_count


# =============================================================================
# CONSTANTS (ported from plan.py)
# =============================================================================
DEFAULT_CURRENCY = settings.default_trip_currency
SUPPORTED_CURRENCIES = {"USD", "EUR", "GBP", "CAD", "AUD", "JPY"}
DEFAULT_BOOKING_TYPES = {
    "hotels": False,
    "flights": False,
    "ground_transport": False,
    "activities": False,
}
DEFAULT_FLIGHT_SETTINGS = {"round_trip": True, "cabin_class": "economy", "direct_only": False}
DEFAULT_HOTEL_SETTINGS = {"min_stars": 0, "amenities": []}
DEFAULT_ACTIVITY_SETTINGS = {"categories": []}
DEFAULT_TRANSPORT_SETTINGS = {"car": False, "train": False, "bus": False}

# =============================================================================
# DESTINATION EXCLUDE WORDS
# =============================================================================
# Words that indicate a phrase-like destination that should be filtered out.
# These are intent/action words, not actual places.
_DEST_EXCLUDE_WORDS = frozenset(
    {
        "trip",
        "vacation",
        "holiday",
        "getaway",
        "tour",
        "recommend",
        "suggest",
        "help",
        "planning",
        "visit",
        "travel",
        "go to",
        "book",
        "find",
    }
)

# =============================================================================
# ACTIVITY EMOJI MAPPING
# =============================================================================
# Maps activity keywords (lowercase) to their emoji prefixes.
# Used to normalize activities so they all have consistent emoji prefixes.
# The mapping includes synonyms that resolve to canonical activities.
# Based on the emoji mapping in prompts/activities.txt

_ACTIVITY_EMOJI_MAP: Dict[str, str] = {
    # Beach/coastal
    "beach": "🏖️",
    "coastal": "🏖️",
    "seaside": "🏖️",
    # Romantic
    "romantic": "💕",
    "couples": "💕",
    "honeymoon": "💕",
    # Adventure/extreme
    "adventure": "🧗",
    "extreme": "🧗",
    "adrenaline": "🧗",
    "climbing": "🧗",
    "rock climbing": "🧗",
    "bungee": "🧗",
    "skydiving": "🧗",
    "paragliding": "🧗",
    "zip-line": "🧗",
    "zipline": "🧗",
    # Family
    "family": "👨‍👩‍👧",
    "kids": "👨‍👩‍👧",
    "children": "👨‍👩‍👧",
    # Food/culinary
    "food": "🍝",
    "culinary": "🍝",
    "gastronomy": "🍝",
    "food tour": "🍝",
    "cooking class": "🍝",
    "street food": "🍝",
    # Wine/tasting
    "wine": "🍷",
    "vineyard": "🍷",
    "tasting": "🍷",
    "wine tasting": "🍷",
    "brewery": "🍷",
    "distillery": "🍷",
    # Culture/museums
    "culture": "🏛️",
    "museums": "🏛️",
    "galleries": "🏛️",
    "art": "🏛️",
    "exhibitions": "🏛️",
    "sightseeing": "🏛️",
    # History
    "history": "📜",
    "heritage": "📜",
    "ancient": "📜",
    "archaeology": "📜",
    # Theater/shows
    "theater": "🎭",
    "theatre": "🎭",
    "shows": "🎭",
    "opera": "🎭",
    "ballet": "🎭",
    "broadway": "🎭",
    "cabaret": "🎭",
    "comedy": "🎭",
    # Spa/wellness
    "spa": "💆",
    "wellness": "💆",
    "yoga": "💆",
    "meditation": "💆",
    "retreat": "💆",
    "spa day": "💆",
    "massage": "💆",
    # Relaxation
    "relaxation": "😌",
    "chill": "😌",
    "unwind": "😌",
    # Hiking/trekking
    "hiking": "🥾",
    "trekking": "🥾",
    "trails": "🥾",
    "hike": "🥾",
    "trek": "🥾",
    # Dirt riding/motorbike
    "dirt riding": "🏍️",
    "motorbike": "🏍️",
    "atv": "🏍️",
    "quad": "🏍️",
    "off-road": "🏍️",
    "motocross": "🏍️",
    "motogp": "🏍️",
    # Racing/F1
    "f1": "🏎️",
    "racing": "🏎️",
    "motorsport": "🏎️",
    "go-kart": "🏎️",
    "formula 1": "🏎️",
    "grand prix": "🏎️",
    "nascar": "🏎️",
    # Diving/snorkeling
    "diving": "🤿",
    "snorkeling": "🤿",
    "scuba": "🤿",
    # Skiing/winter
    "skiing": "⛷️",
    "snowboarding": "⛷️",
    "winter sports": "⛷️",
    "snow activities": "🎿",
    # Nightlife
    "nightlife": "🎉",
    "clubs": "🎉",
    "bars": "🎉",
    "entertainment": "🎉",
    "party": "🎉",
    "clubbing": "🎉",
    "night out": "🎉",
    # Running
    "running": "🏃",
    "jogging": "🏃",
    "marathon": "🏃",
    "triathlon": "🏃",
    "trail running": "🏃",
    # Backpacking
    "backpacking": "🎒",
    "budget travel": "🎒",
    # Music
    "music": "🎵",
    "concerts": "🎵",
    "festivals": "🎵",
    "live music": "🎵",
    "dj": "🎵",
    "rave": "🎵",
    # Movies/film
    "movies": "🎬",
    "film": "🎬",
    "film festival": "🎬",
    "premiere": "🎬",
    "cinema": "🎬",
    "celebrity events": "🎬",
    # Circus/carnival
    "circus": "🎪",
    "carnival": "🎪",
    "parade": "🎪",
    "celebration": "🎪",
    "fair": "🎪",
    # Shopping
    "shopping": "🛍️",
    "markets": "🛍️",
    "boutiques": "🛍️",
    # Cycling
    "cycling": "🚴",
    "biking": "🚴",
    "mountain biking": "🚴",
    "bmx": "🚴",
    # Surfing/water sports
    "surfing": "🏄",
    "water sports": "🏄",
    "jet ski": "🏄",
    "wakeboard": "🏄",
    # Kayaking/paddling
    "kayaking": "🛶",
    "canoeing": "🛶",
    "paddleboarding": "🛶",
    "rafting": "🛶",
    # Sailing/boating
    "sailing": "⛵",
    "boating": "⛵",
    "yacht": "⛵",
    "cruise": "⛵",
    # Fishing
    "fishing": "🎣",
    "deep sea fishing": "🎣",
    # Safari/wildlife
    "safari": "🦁",
    "wildlife": "🦁",
    "animal watching": "🦁",
    "zoo": "🦁",
    "whale watching": "🦁",
    "wildlife tours": "🦁",
    # Nature
    "nature": "🌲",
    "national parks": "🌲",
    "aurora": "🌲",
    "northern lights": "🌲",
    "outdoor": "🌲",
    "outdoor activities": "🌲",
    # Golf
    "golf": "⛳",
    # Tennis
    "tennis": "🎾",
    # Sports events
    "basketball": "🏀",
    "football": "🏀",
    "soccer": "🏀",
    "sports events": "🏀",
    # Academic
    "academic": "🎓",
    "conference": "🎓",
    "seminar": "🎓",
    "workshop": "🎓",
    "lecture": "🎓",
    "university": "🎓",
    "research": "🎓",
    "study abroad": "🎓",
    # Competition
    "competition": "🏆",
    "hackathon": "🏆",
    "tournament": "🏆",
    "championship": "🏆",
    "esports": "🏆",
    "olympics": "🏆",
    "world cup": "🏆",
    # Tours (generic)
    "tours": "🎫",
    "guided tours": "🎫",
    "excursions": "🎫",
    "day trips": "🎫",
    # Experiences
    "experiences": "🌟",
    "local experiences": "🌟",
}

# Default emoji for activities that don't match any known category
_DEFAULT_ACTIVITY_EMOJI = "✨"

# NOTE: ANSI_ESCAPE_PATTERN is now imported from pattern_matching module


def _strip_ansi_codes(text: str) -> str:
    """Strip ANSI escape codes from a string."""
    return ANSI_ESCAPE_PATTERN.sub("", text)


def _strip_non_printable(text: str) -> str:
    """Remove non-printable characters except spaces."""
    return "".join(c for c in text if c.isprintable() or c.isspace())


def _normalize_activity_with_emoji(activity: str) -> str:
    """
    Normalize an activity string to ensure it has the correct emoji prefix.

    - Strips ANSI escape codes from the input
    - Applies NFC Unicode normalization to fix decomposed emoji codepoints
    - If the activity already starts with an emoji, validate it's correct for the activity type
    - If the emoji is wrong, strip it and apply the correct one
    - Otherwise, look up the activity in the emoji map and add the appropriate emoji
    - If no match found, use the sparkle emoji as default

    Args:
        activity: The activity string (may or may not have emoji prefix)

    Returns:
        The activity string with correct emoji prefix
    """
    import re
    import unicodedata

    activity = activity.strip()
    if not activity:
        return activity

    # Strip ANSI escape codes (e.g., bold, color formatting from terminals)
    activity = _strip_ansi_codes(activity)

    # Apply NFC normalization to combine decomposed emoji codepoints
    # This fixes the "9bf" issue on Windows where NFD characters get split
    activity = unicodedata.normalize("NFC", activity)

    # Check if the activity already starts with an emoji
    # Use grapheme.slice to handle multi-codepoint emojis (e.g., 🥾, 🤿, 👨‍👩‍👧)
    first_grapheme = grapheme.slice(activity, 0, 1)
    first_code_point = ord(first_grapheme[0]) if first_grapheme else 0
    # Check if first character is in emoji ranges (simplified check)
    if first_code_point > 0x1F00:
        # Has emoji prefix - extract the text part to validate
        # Use grapheme.slice to skip the full grapheme (handles multi-codepoint emojis)
        text_part = grapheme.slice(activity, 1, None).lstrip()
        # Also strip ANSI codes from the text part after emoji
        text_part = _strip_ansi_codes(text_part)
        # Strip non-printable characters that may corrupt the text
        text_part = _strip_non_printable(text_part)
        if not text_part:
            return _strip_non_printable(activity)

        # Look up what the correct emoji should be for this activity
        text_lower = text_part.lower()
        correct_emoji = None
        matched_keyword = None

        # Direct match in emoji map
        if text_lower in _ACTIVITY_EMOJI_MAP:
            correct_emoji = _ACTIVITY_EMOJI_MAP[text_lower]
            matched_keyword = text_lower
        else:
            # Try partial matching - prioritize earliest position and longest keyword
            best_match: tuple[int, int, str, str] | None = None
            for keyword, emoji in _ACTIVITY_EMOJI_MAP.items():
                match = re.search(rf"\b{re.escape(keyword)}\b", text_lower)
                if match:
                    pos = match.start()
                    length = len(keyword)
                    if best_match is None or (pos, -length) < (best_match[0], best_match[1]):
                        best_match = (pos, -length, emoji, keyword)
            if best_match:
                correct_emoji = best_match[2]
                matched_keyword = best_match[3]

        # If we found a matching activity keyword, rebuild the string cleanly
        # This removes any garbage characters between emoji and activity text
        if correct_emoji and matched_keyword:
            # Extract just the matched keyword (preserving original case)
            match = re.search(rf"\b{re.escape(matched_keyword)}\b", text_part, re.IGNORECASE)
            if match:
                clean_activity_text = text_part[match.start() :]
                result = f"{correct_emoji} {clean_activity_text}"
                return _strip_non_printable(result)

        # If we found a correct emoji and it differs from current, fix it
        # Use first_grapheme (not first_char) for proper multi-codepoint emoji comparison
        if correct_emoji and first_grapheme != correct_emoji:
            result = f"{correct_emoji} {text_part}"
            return _strip_non_printable(result)

        # Emoji is correct or no match found, return as-is
        return _strip_non_printable(activity)

    # No emoji prefix - add appropriate one
    activity_lower = activity.lower()

    # Direct match in emoji map
    if activity_lower in _ACTIVITY_EMOJI_MAP:
        emoji = _ACTIVITY_EMOJI_MAP[activity_lower]
        result = f"{emoji} {activity}"
        return _strip_non_printable(result)

    # Try matching with common suffixes removed
    for suffix in [" activities", " tours", " experiences"]:
        if activity_lower.endswith(suffix):
            base = activity_lower[: -len(suffix)]
            if base in _ACTIVITY_EMOJI_MAP:
                emoji = _ACTIVITY_EMOJI_MAP[base]
                result = f"{emoji} {activity}"
                return _strip_non_printable(result)

    # Try partial matching - check if any keyword is contained in the activity
    # Prioritize by: 1) earliest position in string, 2) longest keyword (more specific)
    import re

    best_match: tuple[int, int, str] | None = None  # (position, -length, emoji)
    for keyword, emoji in _ACTIVITY_EMOJI_MAP.items():
        match = re.search(rf"\b{re.escape(keyword)}\b", activity_lower)
        if match:
            pos = match.start()
            length = len(keyword)
            # Compare: earlier position wins, then longer keyword wins
            if best_match is None or (pos, -length) < (best_match[0], best_match[1]):
                best_match = (pos, -length, emoji)

    if best_match:
        result = f"{best_match[2]} {activity}"
        return _strip_non_printable(result)

    # No match found, use default sparkle emoji
    result = f"{_DEFAULT_ACTIVITY_EMOJI} {activity}"
    return _strip_non_printable(result)


def _deduplicate_activities_case_insensitive(categories: List[str]) -> List[str]:
    """
    Deduplicate activity categories case-insensitively.

    When comparing, strips the emoji prefix to compare only the activity text.
    Keeps the first occurrence of each unique activity.

    Args:
        categories: List of activity strings (with emoji prefixes)

    Returns:
        Deduplicated list preserving order and first occurrences
    """
    seen_lower: set = set()
    deduped: List[str] = []

    for cat in categories:
        # Extract the text part after emoji for comparison
        text = cat.strip()
        if not text:
            continue

        # Strip ANSI escape codes before processing
        text = _strip_ansi_codes(text)

        # Check if first grapheme is an emoji and skip it
        first_grapheme = grapheme.slice(text, 0, 1)
        first_code_point = ord(first_grapheme[0]) if first_grapheme else 0
        if first_code_point > 0x1F00:
            # Skip the emoji grapheme using grapheme.slice for multi-codepoint emoji support
            text_portion = grapheme.slice(text, 1, None).strip().lower()
        else:
            text_portion = text.lower()

        # Also strip any remaining ANSI codes from text_portion for clean comparison
        text_portion = _strip_ansi_codes(text_portion)

        if text_portion and text_portion not in seen_lower:
            seen_lower.add(text_portion)
            # Store the cleaned version (with ANSI codes stripped)
            if cat != text:
                deduped.append(text)  # Use cleaned version
            else:
                deduped.append(cat)

    return deduped


# =============================================================================
# ACTIVITY CATEGORY CANONICALIZATION
# =============================================================================
# Maps activity aliases/synonyms to canonical values for consistent routing.
# Used by _canonicalize_activity_category() to normalize activity_settings.categories.

ACTIVITY_ALIAS_MAP: Dict[str, str] = {
    # Diving aliases
    "scuba": "diving",
    "scuba diving": "diving",
    "snorkeling": "diving",
    "snorkel": "diving",
    "underwater": "diving",
    # Hiking aliases
    "trekking": "hiking",
    "trek": "hiking",
    "mountaineering": "hiking",
    "trail": "hiking",
    "backpacking": "hiking",
    # Cycling aliases
    "biking": "cycling",
    "bike": "cycling",
    "bicycle": "cycling",
    "mountain biking": "cycling",
    # Skiing aliases
    "snowboarding": "skiing",
    "snowboard": "skiing",
    "alpine": "skiing",
    # Boating aliases
    "sailing": "boating",
    "sail": "boating",
    "yacht": "boating",
    "kayak": "boating",
    "kayaking": "boating",
    "canoe": "boating",
    "canoeing": "boating",
    "cruise": "boating",
}

# Canonical activity category display names (for UI presentation layer)
ACTIVITY_DISPLAY_MAP: Dict[str, str] = {
    "diving": "🤿 Diving",
    "hiking": "🥾 Hiking",
    "cycling": "🚴 Cycling",
    "skiing": "⛷️ Skiing",
    "boating": "⛵ Boating",
    "adventure": "🏔️ Adventure",
}


def canonicalize_activity_category(category: str) -> str:
    """
    Canonicalize an activity category to a standard value.

    This function:
    1. Strips leading emoji and punctuation
    2. Lowercases for comparison
    3. Maps aliases/synonyms to canonical values
    4. Returns the canonical lowercase value

    The canonical value is stored in state. UI/display layers should use
    ACTIVITY_DISPLAY_MAP to get the emoji-prefixed display version.

    Args:
        category: Raw activity category (may have emoji prefix, aliases, etc.)

    Returns:
        Canonical lowercase activity category (e.g., "diving", "hiking")
    """
    if not category:
        return category

    text = category.strip()
    if not text:
        return category

    # Strip ANSI escape codes
    text = _strip_ansi_codes(text)

    # Strip leading emoji if present
    first_grapheme = grapheme.slice(text, 0, 1)
    first_code_point = ord(first_grapheme[0]) if first_grapheme else 0
    if first_code_point > 0x1F00:
        # Skip the emoji grapheme
        text = grapheme.slice(text, 1, None).strip()

    # Lowercase for comparison and canonicalization
    text_lower = text.lower()

    # Check for exact alias match
    if text_lower in ACTIVITY_ALIAS_MAP:
        return ACTIVITY_ALIAS_MAP[text_lower]

    # Check for partial alias match (e.g., "scuba diving trip" contains "scuba diving")
    for alias, canonical in ACTIVITY_ALIAS_MAP.items():
        if alias in text_lower:
            return canonical

    # No alias match - return cleaned lowercase value
    return text_lower


def canonicalize_activity_categories(categories: List[str]) -> List[str]:
    """
    Canonicalize a list of activity categories, deduplicate, and preserve order.

    Args:
        categories: List of raw activity categories

    Returns:
        Deduplicated list of canonical categories (lowercase, no emoji)
    """
    seen: set = set()
    result: List[str] = []

    for cat in categories:
        canonical = canonicalize_activity_category(cat)
        if canonical and canonical not in seen:
            seen.add(canonical)
            result.append(canonical)

    return result


# =============================================================================
# SUGGESTION CONTRACT VALIDATION
# =============================================================================
# Ensures suggestions match the active question_target to prevent misalignment
# like offering destination suggestions when dates are being asked.

# Stats for suggestion contract violations
_suggestion_contract_stats: Dict[str, int] = {
    "violations": 0,
    "validations": 0,
    "rewrites": 0,
}


def validate_suggestion_contract(
    question_target: Optional[str],
    suggested_responses: List[str],
    node_name: str,
    state: Optional["GraphState"] = None,
) -> List[str]:
    """
    Validate and fix suggestions to match the active question_target.

    This contract ensures that clickable suggestions can satisfy the current
    question, preventing misalignment like destination suggestions when dates
    are being asked.

    Args:
        question_target: The active question target (e.g., "dates", "destinations")
        suggested_responses: Current suggestions
        node_name: Node that produced the suggestions (for logging)
        state: Optional GraphState for metadata recording

    Returns:
        Corrected suggestions that match the question_target
    """
    _suggestion_contract_stats["validations"] += 1

    # =========================================================================
    # v7 Final v5: SUGGESTION TARGET OVERRIDE
    # =========================================================================
    # When a suggestion click sets metadata["suggestion_target_override"], use
    # that instead of question_target for validation. Clear after use.
    # =========================================================================
    effective_target = question_target
    if state and state.metadata.get("suggestion_target_override"):
        effective_target = state.metadata["suggestion_target_override"]
        _debug(
            "suggestion_target_override_used",
            override=effective_target,
            original=question_target,
            node=node_name,
        )
        # Clear after use (single-use override)
        del state.metadata["suggestion_target_override"]

    if not effective_target or not suggested_responses:
        return suggested_responses

    # Define suggestion patterns by target type
    date_patterns = {
        "next month",
        "this summer",
        "spring",
        "fall",
        "winter",
        "december",
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "week",
        "weekend",
        "holiday",
        "flexible",
        "2024",
        "2025",
        "2026",
    }

    place_patterns = {
        "paris",
        "tokyo",
        "london",
        "rome",
        "bali",
        "barcelona",
        "new york",
        "los angeles",
        "alps",
        "beach",
        "mountains",
        "city",
        "country",
        "island",
        "coast",
        "valley",
    }

    origin_patterns = {
        "new york",
        "london",
        "los angeles",
        "chicago",
        "boston",
        "san francisco",
        "seattle",
        "miami",
        "denver",
        "austin",
    }

    def is_date_like(s: str) -> bool:
        s_lower = s.lower()
        return any(p in s_lower for p in date_patterns)

    def is_place_like(s: str) -> bool:
        s_lower = s.lower()
        return any(p in s_lower for p in place_patterns | origin_patterns)

    # Check if suggestions match the target (use effective_target for validation)
    target_lower = effective_target.lower()

    if target_lower == "dates":
        # Suggestions should be date-like
        mismatches = [s for s in suggested_responses if is_place_like(s) and not is_date_like(s)]
        if mismatches:
            _suggestion_contract_stats["violations"] += 1
            _suggestion_contract_stats["rewrites"] += 1
            _debug(
                "suggestion_contract_violation",
                node=node_name,
                target=effective_target,
                mismatches=mismatches[:3],
            )
            if state:
                state.metadata["suggestion_contract_violation"] = {
                    "node": node_name,
                    "target": effective_target,
                    "suggestions_preview": suggested_responses[:3],
                }
            # Rewrite with date suggestions
            return ["Next weekend", "In March", "Dec 15-22"]

    elif target_lower in ("destinations", "origin"):
        # Suggestions should be place-like
        mismatches = [s for s in suggested_responses if is_date_like(s) and not is_place_like(s)]
        if mismatches:
            _suggestion_contract_stats["violations"] += 1
            _suggestion_contract_stats["rewrites"] += 1
            _debug(
                "suggestion_contract_violation",
                node=node_name,
                target=effective_target,
                mismatches=mismatches[:3],
            )
            if state:
                state.metadata["suggestion_contract_violation"] = {
                    "node": node_name,
                    "target": effective_target,
                    "suggestions_preview": suggested_responses[:3],
                }
            # Rewrite with place suggestions
            if target_lower == "origin":
                return ["New York", "London", "Los Angeles"]
            else:
                return ["Paris, France", "Tokyo, Japan", "Bali, Indonesia"]

    return suggested_responses


# Required fields for ready_to_generate (only core 3 - matches plan.py)
_REQUIRED_TRIP_INPUT_FIELDS = (
    "destinations",
    "origin",
    "start_date",
)

# Auto-correct typo threshold: fuzzy match score at or above which typos are
# auto-corrected without LLM confirmation. Default 100 means disabled (always confirm).
# Set to 98 to auto-correct very obvious typos like "Londen" -> "London".
AUTO_CORRECT_TYPO_THRESHOLD = settings.auto_correct_typo_threshold

# Confidence threshold for skipping router entirely (high-confidence extraction)
# When confidence >= this AND all core fields present AND no typos -> skip to validate_and_merge
CONFIDENCE_THRESHOLD_SKIP_ROUTER = settings.confidence_threshold_skip_router

# =============================================================================
# STATE OWNERSHIP MAPPING
# =============================================================================
# Defines which node is the "owner" of each state field. Only the owner should
# write to that field; other nodes should read only. Violations are logged as
# warnings in development.
#
# Fields with "specialists" owner can be written by whichever specialist node runs.
# Fields with "any" owner have shared write access (e.g., metadata for observability).
STATE_OWNERSHIP: Dict[str, str] = {
    # Core extraction - written by extractor, consumed by all
    "parsed_inputs": "extractor",
    # Trip inputs - normalize_inputs seeds values from regex extraction;
    # specialists refine them via _apply_llm_delta. Both can write.
    # Users can update ANY trip input at ANY point in the conversation
    # (e.g., "actually flying from Paris", "change to 3 adults").
    "trip_inputs.destinations": "normalize_inputs|specialists",
    "trip_inputs.origin": "normalize_inputs|specialists",
    "trip_inputs.start_date": "normalize_inputs|specialists",
    "trip_inputs.end_date": "normalize_inputs|specialists",
    "trip_inputs.adults": "normalize_inputs|specialists",
    "trip_inputs.children": "normalize_inputs|specialists",
    "trip_inputs.budget": "normalize_inputs|specialists",
    "trip_inputs.currency": "normalize_inputs|specialists",
    "trip_inputs.requires_assistance": "normalize_inputs|specialists",
    "trip_inputs.duration_days": "normalize_inputs|specialists",
    "trip_inputs.multi_city_intent": "normalize_inputs|specialists",
    # Settings fields - normalize_inputs seeds from regex, specialists refine.
    # Users often mention preferences early (e.g., "hiking trip" before activities_node runs).
    "trip_inputs.booking_types": "normalize_inputs|specialists",
    "trip_inputs.flight_settings": "normalize_inputs|specialists",
    "trip_inputs.hotel_settings": "normalize_inputs|specialists",
    "trip_inputs.transport_settings": "normalize_inputs|specialists",
    "trip_inputs.activity_settings": "normalize_inputs|specialists",
    # Control flow
    "ready_to_generate": "validate_and_merge",
    "intent": "router",
    "strategy_topic": "router",
    "active_category": "router",
    # Output fields
    "branches": "branch_postprocess",
    "suggested_responses": "specialists",  # Whichever specialist runs
    "last_summary": "summarize",
    "question_target": "specialists",
    # Shared/observability (any node can write)
    "errors": "any",
    "metadata": "any",
    "flags": "any",
    "chat_history": "any",
}


def _check_state_ownership(node_name: str, field_path: str) -> bool:
    """
    Check if a node is allowed to write to a field based on STATE_OWNERSHIP.

    Returns True if allowed, False if violation (logs a visible warning).
    Writes are still applied even on violation (warn-only mode).

    Supports pipe-separated owners (e.g., "normalize_inputs|specialists") where
    any listed owner is allowed to write.
    """
    owner = STATE_OWNERSHIP.get(field_path)

    if owner is None:
        # Field not in ownership map - allow by default
        return True

    if owner == "any":
        # Shared fields - any node can write
        return True

    # Handle pipe-separated owners (e.g., "normalize_inputs|specialists")
    owners = owner.split("|")

    for o in owners:
        if o == "specialists" and (
            node_name.endswith("_node")
            or node_name.startswith("specialist:")
            or node_name.startswith("strategy:")
        ):
            # Specialist and strategy nodes can write to specialist-owned fields
            return True

        if o == node_name:
            # Exact match - allowed
            return True

    # Violation - log highly visible warning
    _debug(
        "⚠️⚠️⚠️ STATE OWNERSHIP VIOLATION ⚠️⚠️⚠️",
        node=node_name,
        field=field_path,
        expected_owner=owner,
        action="write allowed (warn-only mode)",
    )
    if _DEBUG_LOG:
        print(f"\n{'='*60}")
        print("⚠️ STATE OWNERSHIP VIOLATION")
        print(f"  Node: {node_name}")
        print(f"  Field: {field_path}")
        print(f"  Expected owner: {owner}")
        print("  Action: write allowed (warn-only mode)")
        print(f"{'='*60}\n")
    return False


def _hash_value(value: Any) -> str:
    """Generate a short hash of a value for diff tracking."""
    import hashlib

    try:
        serialized = json.dumps(value, sort_keys=True, default=str)
        return hashlib.md5(serialized.encode()).hexdigest()[:8]
    except Exception:
        # Use blake2s for stable fallback instead of built-in hash()
        # (Inline logic to avoid circular import with app.planner)
        fallback_str = repr(value)
        return hashlib.blake2s(fallback_str.encode("utf-8"), digest_size=32).hexdigest()[:8]


def _write_trip_inputs(
    state: "GraphState",
    node_name: str,
    provenance: str = "inferred",
    **updates: Any,
) -> Tuple["GraphState", List[str]]:
    """
    Safely update trip_inputs with ownership checking and structured diff tracing.

    Uses model_copy(deep=True) to ensure immutability.
    Logs warnings for ownership violations but does not block writes.
    Records structured diffs to turn_journal for post-mortem visibility.

    v5 Routing Observability: Returns fields_changed for RoutingDecisionFinal.deltas_applied.
    Fields are returned in CANONICAL_FIELD_ORDER for stable ordering.

    Args:
        state: Current graph state
        node_name: Name of the calling node (for ownership checking)
        provenance: Source type - "explicit"|"inferred"|"user_confirmed"|"recovery_restore"
        **updates: Field updates to apply to trip_inputs

    Returns:
        Tuple of (updated_state, fields_changed) where fields_changed is a list of
        canonical field names that were actually written (stable sorted).

    Example:
        state, changed = _write_trip_inputs(state, "normalize_inputs", destinations=["Paris"])
        state, changed = _write_trip_inputs(state, "extractor", provenance="explicit", budget=1000)
    """
    ti = state.trip_inputs.model_copy(deep=True)

    # Track diffs for turn journal
    diffs: List[Dict[str, Any]] = []
    fields_changed: List[str] = []

    for field_name, value in updates.items():
        field_path = f"trip_inputs.{field_name}"
        _check_state_ownership(node_name, field_path)

        # Capture old value for diff tracking
        old_value = getattr(ti, field_name, None) if hasattr(ti, field_name) else None
        old_hash = _hash_value(old_value) if old_value is not None else "null"

        # Handle nested dict updates (e.g., booking_types, flight_settings)
        if hasattr(ti, field_name):
            current = getattr(ti, field_name)
            if isinstance(current, dict) and isinstance(value, dict):
                # Merge dict updates
                merged = {**current, **value}
                setattr(ti, field_name, merged)
                new_value = merged
            else:
                setattr(ti, field_name, value)
                new_value = value
        else:
            new_value = value

        new_hash = _hash_value(new_value) if new_value is not None else "null"

        # Record diff if value changed
        if old_hash != new_hash:
            diffs.append(
                {
                    "field": field_name,
                    "old_hash": old_hash,
                    "new_hash": new_hash,
                    "source": node_name,
                    "provenance": provenance,
                    "is_overwrite": old_value is not None,
                }
            )
            fields_changed.append(field_name)

    state.trip_inputs = ti

    # Sort fields_changed by CANONICAL_FIELD_ORDER for stable ordering
    def canonical_sort_key(field: str) -> int:
        try:
            return CANONICAL_FIELD_ORDER.index(field)
        except ValueError:
            return len(CANONICAL_FIELD_ORDER)  # Unknown fields go last

    fields_changed.sort(key=canonical_sort_key)

    # Record diffs to turn journal for structured tracing
    if diffs and state.metadata is not None:
        # Store provenance per field for recovery logic
        trip_inputs_provenance = state.metadata.get("trip_inputs_provenance", {})
        for diff in diffs:
            trip_inputs_provenance[diff["field"]] = diff["provenance"]
        state.metadata["trip_inputs_provenance"] = trip_inputs_provenance

        # Track cumulative deltas applied this turn for RoutingDecisionFinal
        deltas_applied_this_turn = state.metadata.get("deltas_applied_this_turn", [])
        for field in fields_changed:
            if field not in deltas_applied_this_turn:
                deltas_applied_this_turn.append(field)
        # Re-sort cumulative list
        deltas_applied_this_turn.sort(key=canonical_sort_key)
        state.metadata["deltas_applied_this_turn"] = deltas_applied_this_turn

        # Append to turn journal if it exists
        turn_journal = state.metadata.get("turn_journal", [])
        turn_number = getattr(state, "turn_number", 0)

        # Find or create journal entry for this turn
        current_turn_entry = None
        for entry in turn_journal:
            if entry.get("turn") == turn_number:
                current_turn_entry = entry
                break

        if current_turn_entry is None:
            current_turn_entry = {"turn": turn_number, "trip_inputs_diffs": []}
            turn_journal.append(current_turn_entry)

        # Add diffs to journal entry
        current_turn_entry.setdefault("trip_inputs_diffs", []).extend(diffs)

        # Keep journal bounded
        max_journal_size = settings.turn_journal_max_turns
        if len(turn_journal) > max_journal_size:
            turn_journal = turn_journal[-max_journal_size:]

        state.metadata["turn_journal"] = turn_journal

        _debug(
            "trip_inputs update recorded to journal",
            node=node_name,
            fields_changed=fields_changed,
            provenance=provenance,
        )

    return state, fields_changed


def _apply_llm_delta(
    state: "GraphState",
    node_name: str,
    delta: Dict[str, Any],
    skip_fields: Optional[set] = None,
) -> None:
    """
    Apply an LLM-generated trip_inputs delta with RAW merge only.

    This function does MINIMAL processing - just merges values without normalization.
    All normalization happens in normalize_inputs via TripInputNormalizer.

    NOTE: Specialists do NOT re-extract basic trip fields.
    See prompts/_scope_specialist.txt for prompt-level enforcement.
    All normalization happens in normalize_inputs via TripInputNormalizer.

    Args:
        state: Current graph state
        node_name: Name of the calling node (for ownership checking and logging)
        delta: Dict of field updates from LLM response
        skip_fields: Optional set of field names to skip (e.g., {"strategy_settings"})
    """
    if not delta:
        return

    skip_fields = skip_fields or set()
    ti = state.trip_inputs  # Read-only for getting current values
    updates: Dict[str, Any] = {}

    # Get valid field names from TripInputs model
    valid_fields = set(type(ti).model_fields.keys())

    for k, v in delta.items():
        # Map 'travelers' to 'adults' (LLM sometimes uses wrong field name)
        if k == "travelers" and isinstance(v, (int, str)):
            if "children" in delta or "adults" in delta:
                k = "adults"
                _debug(f"Mapped LLM 'travelers' to 'adults': {v}", node=node_name)
            else:
                _debug(
                    f"Skipping ambiguous 'travelers' field: {v} (no adults/children breakdown)",
                    node=node_name,
                )
                continue

        # Skip unknown fields to avoid crashes
        if k not in valid_fields:
            _debug(f"Skipping unknown field from LLM: {k}", node=node_name)
            continue

        # Skip explicitly excluded fields (with warning for observability)
        if k in skip_fields:
            _debug(
                f"⚠️ BLOCKED: field '{k}' from {node_name} (value: {repr(v)[:50]})",
                node=node_name,
                blocked_field=k,
            )
            continue

        # =====================================================================
        # RAW MERGE ONLY - No normalization here!
        # Normalization happens in normalize_inputs via TripInputNormalizer
        # =====================================================================

        if k == "destinations":
            # Coerce string to list (LLM sometimes returns single destination as string)
            if isinstance(v, str):
                v = [v]
                _debug(f"Coerced string destination to list: {v}", node=node_name)
            if not isinstance(v, list):
                _debug(f"Skipping invalid destinations type: {type(v).__name__}", node=node_name)
                continue
            # Simple merge - just add new destinations, skip exact duplicates
            existing_lower = {d.lower() for d in ti.destinations}
            new_destinations = list(ti.destinations)
            for d in v:
                if isinstance(d, str) and d.strip():
                    d_lower = d.strip().lower()
                    if d_lower not in existing_lower:
                        new_destinations.append(d.strip())
                        existing_lower.add(d_lower)
            if new_destinations != ti.destinations:
                updates["destinations"] = new_destinations

        elif k in (
            "flight_settings",
            "hotel_settings",
            "activity_settings",
            "transport_settings",
            "booking_types",
        ):
            # Block flight/hotel settings from domain specialists until destination + dates exist
            # Required_fields and correction specialists are allowed to set these
            if k in ("flight_settings", "hotel_settings"):
                is_domain_specialist = node_name in ("specialist:flights", "specialist:hotels")
                if is_domain_specialist and (not ti.destinations or not ti.start_date):
                    _debug(
                        f"⚠️ BLOCKED {k} delta: missing destination/dates",
                        node=node_name,
                        has_destinations=bool(ti.destinations),
                        has_start_date=bool(ti.start_date),
                    )
                    continue
            # Simple dict merge with normalization for activity categories
            if isinstance(v, dict):
                existing = dict(getattr(ti, k, {}) or {})
                # For activity_settings, normalize the categories to fix emojis
                if k == "activity_settings" and "categories" in v:
                    raw_categories = v.get("categories", [])
                    if isinstance(raw_categories, list):
                        normalized = _normalize_booking_field(
                            "activity_settings", {"categories": raw_categories}
                        )
                        if normalized and "categories" in normalized:
                            existing_cats = list(existing.get("categories", []))
                            for cat in normalized["categories"]:
                                if cat not in existing_cats:
                                    existing_cats.append(cat)
                            # Deduplicate case-insensitively
                            existing["categories"] = _deduplicate_activities_case_insensitive(
                                existing_cats
                            )
                        # Copy other activity_settings fields if present
                        for ak, av in v.items():
                            if ak != "categories":
                                existing[ak] = av
                    else:
                        existing.update(v)
                else:
                    existing.update(v)
                updates[k] = existing

        elif k in ("start_date", "end_date", "origin", "currency", "multi_city_intent"):
            # Pass through string fields as-is
            if v is not None:
                updates[k] = v

        elif k in ("adults", "children"):
            # Basic int coercion only
            if isinstance(v, int):
                updates[k] = v
            elif isinstance(v, str):
                try:
                    updates[k] = int(v)
                except ValueError:
                    pass

        elif k == "budget":
            # Accept int/float directly, try to parse strings
            if isinstance(v, (int, float)):
                updates[k] = float(v)
            elif isinstance(v, str):
                # Detect template literal bugs
                if v.startswith("{") and v.endswith("}"):
                    _debug(
                        f"Dropping template literal budget: {v} (system bug)",
                        node=node_name,
                        level="warn",
                    )
                    continue
                # Try simple numeric extraction
                cleaned = re.sub(r"[^\d.]", "", v)
                if cleaned:
                    try:
                        updates[k] = float(cleaned)
                    except ValueError:
                        pass

        elif k == "requires_assistance":
            if isinstance(v, bool):
                updates[k] = v

        elif _should_skip_field_update(k, v, getattr(ti, k, None)):
            continue

        else:
            updates[k] = v

    # Apply all updates via the helper
    if updates:
        _write_trip_inputs(state, node_name, **updates)  # Ignore fields_changed
        _debug("Applied LLM delta (raw merge)", node=node_name, fields=list(updates.keys()))

    # NOTE: _auto_enable_booking_types is now called ONLY in validate_and_merge
    # to avoid duplicate calls across the graph


# =============================================================================
# USER INTENT ARCHETYPES (for conversational style adaptation)
# =============================================================================
# Priority order: lower number = higher priority (speed preferences win)
# Patterns imported from pattern_matching.py (V26 extraction)
USER_INTENT_ARCHETYPES = {
    "quick_booking": {
        "priority": 1,
        "patterns": QUICK_BOOKING_PATTERNS,
        "description": "Streamlined, minimal questions, skip optional fields",
    },
    "short_trip": {
        "priority": 2,
        "patterns": SHORT_TRIP_PATTERNS,
        "description": "Focus on essentials, suggest compact itineraries",
    },
    "adventurous": {
        "priority": 3,
        "patterns": ADVENTUROUS_PATTERNS,
        "description": "Proactive tips, suggest hidden gems, enthusiastic tone",
    },
    "undecided": {
        "priority": 4,
        "patterns": UNDECIDED_PATTERNS,
        "description": "Curated options, gentle guidance, offer comparisons",
    },
    "detailed_planner": {
        "priority": 5,
        "patterns": [],  # Default fallback - no specific patterns
        "description": "Thorough questions, structured approach, all categories",
    },
}

# User tone detection patterns (for response adaptation)
# Patterns imported from pattern_matching.py (V26 extraction)
USER_TONE_PATTERNS = {
    "enthusiastic": {
        "patterns": ENTHUSIASTIC_TONE_PATTERNS,
    },
    "frustrated": {
        "patterns": FRUSTRATED_TONE_PATTERNS,
    },
    "neutral": {
        "patterns": [],  # Default
    },
}

# Intent persistence decay schedule (confidence by turn count)
INTENT_DECAY_SCHEDULE = {
    1: 1.0,  # Turn 1-2: 100% confidence
    2: 1.0,
    3: 0.75,  # Turn 3: 75% confidence
    4: 0.50,  # Turn 4: 50% confidence
    # Turn 5+: 0% - re-detect from scratch
}


def _detect_user_intent_hint(text: str) -> Optional[str]:
    """
    Detect user intent archetype from text using pre-compiled regex patterns.
    Returns the highest-priority matching intent, or None if no match.
    """
    text_lower = text.lower()
    matches = []

    for intent_name, config in USER_INTENT_ARCHETYPES.items():
        if not config["patterns"]:  # Skip default (detailed_planner)
            continue
        for pattern in config["patterns"]:
            if pattern.search(text_lower):
                matches.append((config["priority"], intent_name))
                break  # One match per intent is enough

    if not matches:
        return None

    # Return highest priority (lowest number)
    matches.sort(key=lambda x: x[0])
    return matches[0][1]


def _detect_user_tone(text: str) -> str:
    """
    Detect user tone from text using pre-compiled regex patterns.
    Returns: 'enthusiastic', 'frustrated', or 'neutral'.
    """
    text_lower = text.lower()

    # Check enthusiastic patterns
    for pattern in USER_TONE_PATTERNS["enthusiastic"]["patterns"]:
        if pattern.search(text_lower):
            return "enthusiastic"

    # Check frustrated patterns
    for pattern in USER_TONE_PATTERNS["frustrated"]["patterns"]:
        if pattern.search(text_lower):
            return "frustrated"

    return "neutral"


def _compute_intent_confidence(turn_count: int) -> float:
    """Compute intent confidence based on turn count since detection."""
    if turn_count >= 5:
        return 0.0
    return INTENT_DECAY_SCHEDULE.get(turn_count, 0.0)


def _should_override_persisted_intent(
    new_hint: Optional[str],
    persisted_intent: Optional[str],
    confidence: float,
) -> bool:
    """
    Determine if new intent hint should override persisted intent.
    Strong new signals override regardless of confidence.
    """
    if not new_hint:
        return False
    if not persisted_intent:
        return True
    if confidence <= 0.5:
        return True  # Low confidence - accept new signal
    # High priority intent overrides lower priority
    new_priority = USER_INTENT_ARCHETYPES.get(new_hint, {}).get("priority", 99)
    old_priority = USER_INTENT_ARCHETYPES.get(persisted_intent, {}).get("priority", 99)
    return new_priority < old_priority


# =============================================================================
# TONE ADAPTER
# =============================================================================
# Replaces _adapt_tone.txt prompt include with a code-computed instruction.
# Saves ~150-200 tokens per LLM call by inlining a single-line instruction
# instead of a multi-line prompt template.


class ToneAdapter:
    """
    Generates tone/intent-aware instructions for LLM prompts.

    Replaces the {% include "_adapt_tone.txt" %} pattern with a computed
    single-line instruction, reducing token usage from ~150 to ~20 tokens.

    Usage:
        instruction = ToneAdapter.get_instruction("quick_booking", "neutral")
        # Returns: "TONE: Be brief but friendly. Keep responses short and efficient."

    Available user_intent values (from USER_INTENT_ARCHETYPES):
        - quick_booking: Fast booking, minimal questions ("just flights", "book now")
        - short_trip: Weekend getaway or brief trip ("weekend", "2-3 days")
        - adventurous: Unique experiences, hidden gems ("explore", "off beaten path")
        - undecided: Needs guidance ("not sure", "help me decide")
        - detailed_planner: Default - comprehensive planning with all details

    Available user_tone values (from USER_TONE_PATTERNS):
        - neutral: Default, no special handling
        - enthusiastic: User shows excitement ("can't wait!", "amazing!")
        - frustrated: User shows frustration ("ugh", "again?", "not working")
        - curious: User is asking questions, exploring options
    """

    # Intent-specific tone instructions - system-style, not conversational
    _INTENT_INSTRUCTIONS = {
        "quick_booking": "Be concise. System-style confirmations only. No chat.",
        "detailed_planner": "Be direct. Acknowledge constraints systematically.",
        "adventurous": "Be concise. Acknowledge preferences directly.",
        "undecided": "Be direct. Present options as labels.",
        "short_trip": "Be concise. Focus on constraints.",
    }

    # Tone modifiers (appended to intent instruction)
    _TONE_MODIFIERS = {
        "frustrated": " Extra concise. Direct answers only.",
        "enthusiastic": "",  # No modifier - stay system-like
        "neutral": "",  # No modifier needed
        "curious": " Direct answers. No fluff.",
    }

    @classmethod
    def get_instruction(cls, user_intent: str, user_tone: str) -> str:
        """
        Get a single-line tone instruction for the LLM prompt.

        Args:
            user_intent: One of: quick_booking, detailed_planner, adventurous,
                         undecided, short_trip. Defaults to warm professional.
            user_tone: One of: neutral, frustrated, enthusiastic, curious.

        Returns:
            A single-line instruction string (~20 tokens) prefixed with "TONE:".
            Example: "TONE: Be brief but friendly. Keep responses short and efficient."
        """
        # Get base instruction from intent
        base = cls._INTENT_INSTRUCTIONS.get(
            user_intent, "Be concise and direct. System-style confirmations."
        )

        # Add tone modifier
        modifier = cls._TONE_MODIFIERS.get(user_tone, "")

        instruction = f"TONE: {base}{modifier}"

        _debug(
            "ToneAdapter",
            intent=user_intent,
            tone=user_tone,
            instruction_len=len(instruction),
        )

        return instruction


# =============================================================================
# SUGGESTION BUILDER
# =============================================================================
# Replaces _suggested_responses.txt prompt include with code-computed suggestions.
# Saves ~66 tokens per LLM call by providing contextual suggestions directly
# instead of relying on LLM to generate them.


class SuggestionBuilder:
    """
    Generates contextual suggested responses for specialist nodes.

    Replaces the {% include "_suggested_responses.txt" %} pattern with
    pre-computed suggestions based on node type, strategy topic, and current state.

    This saves ~66 tokens per call and provides more consistent suggestions.

    Usage:
        suggestions = SuggestionBuilder.for_specialist("hotels", "hiking", state)
        # Returns: ["Mountain lodge", "Boutique hotel", "Eco-friendly stay"]
    """

    # Default suggestions by specialist type
    _SPECIALIST_DEFAULTS = {
        "flights": ["Direct flights only", "Morning departure", "Budget airlines OK"],
        "hotels": ["Central location", "Quiet area", "Near attractions"],
        "activities": ["Outdoor activities", "Cultural experiences", "Food tours"],
        "transport": ["Rental car", "Public transport", "Private transfers"],
        "correction": ["Change dates", "Different hotel", "Add activity"],
    }

    # Strategy-topic-specific suggestions
    _STRATEGY_TOPIC_SUGGESTIONS = {
        "hiking": {
            "flights": ["Early morning arrival", "Extra luggage for gear", "Flexible return"],
            "hotels": ["Mountain lodge", "Trailhead access", "Hiker-friendly"],
            "activities": ["Guided hike", "Multi-day trek", "Day hikes only"],
            "transport": ["4WD rental", "Shuttle to trailheads", "Self-drive"],
        },
        "skiing": {
            "flights": ["Weekend flights", "Early arrival", "Ski bag included"],
            "hotels": ["Ski-in/ski-out", "Near lifts", "Chalet rental"],
            "activities": ["Ski lessons", "Off-piste guiding", "Après-ski"],
            "transport": ["Shuttle from airport", "Car rental", "Resort transfer"],
        },
        "diving": {
            "flights": ["Morning arrival", "Dive gear allowance", "Island hopper"],
            "hotels": ["Dive resort", "Beachfront", "With dive center"],
            "activities": ["PADI certification", "Night dives", "Reef snorkeling"],
            "transport": ["Boat transfers", "Island taxi", "Resort pickup"],
        },
        "boating": {
            "flights": ["Arrive day before", "Morning arrival", "Marina proximity"],
            "hotels": ["Marina-side", "Yacht club", "Waterfront hotel"],
            "activities": ["Skippered charter", "Sailing lessons", "Island hopping"],
            "transport": ["Airport to marina", "Water taxi", "Car not needed"],
        },
        "cycling": {
            "flights": ["Bike box allowance", "Early arrival", "Flexible return"],
            "hotels": ["Bike-friendly", "Secure storage", "Near bike routes"],
            "activities": ["Guided tour", "Self-guided route", "E-bike rental"],
            "transport": ["Bike rental on arrival", "Support vehicle", "Train + bike"],
        },
    }

    # Missing field suggestions (used when state.question_target is set)
    _MISSING_FIELD_SUGGESTIONS = {
        "destinations": {
            "default": ["Paris", "Tokyo", "Barcelona"],
            "hiking": ["Swiss Alps", "Patagonia", "Nepal"],
            "skiing": ["Chamonix", "Whistler", "Niseko"],
            "diving": ["Maldives", "Red Sea", "Great Barrier Reef"],
            "boating": ["Greek Islands", "Croatia", "Caribbean"],
            "cycling": ["Tuscany", "Netherlands", "Loire Valley"],
        },
        "origin": ["London", "New York", "Dubai"],
        "dates": ["Next weekend", "In March", "Dec 15-22"],
        "travelers": ["Solo", "2 adults", "Family of 4"],
        "budget": ["$2,000", "$5,000", "$10,000"],
    }

    @classmethod
    def for_specialist(
        cls,
        specialist_name: str,
        strategy_topic: Optional[str],
        state: "GraphState",
    ) -> List[str]:
        """
        Get contextual suggestions for a specialist node.

        Args:
            specialist_name: One of: flights, hotels, activities, transport, correction
            strategy_topic: Optional topic like hiking, skiing, diving, boating, cycling
            state: Current graph state (used to check question_target, existing values)

        Returns:
            List of 2-3 short suggestion strings
        """
        # Priority 1: If there's a missing field question, suggest answers for that
        question_target = state.question_target
        if question_target and question_target in cls._MISSING_FIELD_SUGGESTIONS:
            field_suggestions = cls._MISSING_FIELD_SUGGESTIONS[question_target]
            if isinstance(field_suggestions, dict):
                # Use topic-specific suggestions if available
                suggestions = field_suggestions.get(
                    strategy_topic, field_suggestions.get("default", [])
                )[:3]
            else:
                suggestions = field_suggestions[:3]
            _template_stats["suggestions_generated"] += 1
            _debug(
                "💡 SUGGESTIONS: generated for missing field",
                specialist=specialist_name,
                question_target=question_target,
                count=len(suggestions),
            )
            return suggestions

        # Priority 2: Topic-specific suggestions for this specialist
        if strategy_topic and strategy_topic in cls._STRATEGY_TOPIC_SUGGESTIONS:
            topic_suggestions = cls._STRATEGY_TOPIC_SUGGESTIONS[strategy_topic]
            if specialist_name in topic_suggestions:
                suggestions = topic_suggestions[specialist_name][:3]
                _template_stats["suggestions_generated"] += 1
                _debug(
                    "💡 SUGGESTIONS: generated for topic",
                    specialist=specialist_name,
                    topic=strategy_topic,
                    count=len(suggestions),
                )
                return suggestions

        # Priority 3: Default suggestions for this specialist
        suggestions = cls._SPECIALIST_DEFAULTS.get(specialist_name, [])[:3]
        if suggestions:
            _template_stats["suggestions_generated"] += 1
            _debug(
                "💡 SUGGESTIONS: generated defaults",
                specialist=specialist_name,
                count=len(suggestions),
            )
        return suggestions

    @classmethod
    def get_suggestions_json(
        cls,
        specialist_name: str,
        strategy_topic: Optional[str],
        state: "GraphState",
    ) -> str:
        """
        Get suggestions as a JSON array string for prompt injection.

        Returns:
            JSON array string like '["Option 1", "Option 2", "Option 3"]'
        """
        suggestions = cls.for_specialist(specialist_name, strategy_topic, state)
        return json.dumps(suggestions)


# =============================================================================
# PER-NODE LLM CONFIGURATION
# =============================================================================
# Each node can have its own LLM parameters optimized for its task.
# - Router: Fast, deterministic classification → low temp, small output
# - Specialists: Focused extraction → low temp, moderate output
# - Strategy: Deeper topic analysis → slightly higher temp
_NODE_LLM_CONFIG: Dict[str, Dict[str, Any]] = {
    "extractor": {
        "model_hint": "small",
        "temperature": 0.1,  # Very deterministic for extraction
        "max_tokens": 400,  # Capped from 512 for token savings
        "top_p": None,
    },
    "extractor_light": {
        "model_hint": "small",
        "temperature": 0.1,  # Very deterministic for extraction
        "max_tokens": 200,  # Allow room for full JSON with multiple fields
        "top_p": None,
    },
    "router": {
        "model_hint": "small",
        "temperature": 0.1,  # Very deterministic for classification
        "max_tokens": 256,  # Only needs short JSON response
        "top_p": None,
    },
    "required_fields": {
        "model_hint": "small",
        "temperature": 0.3,  # Slightly creative for warm phrasing
        "max_tokens": 180,  # Reduced from 256; typical output 100-150 tokens
        "top_p": None,
    },
    "flights": {
        "model_hint": "small",
        "temperature": 0.3,  # Slightly creative for warm phrasing
        "max_tokens": 512,  # Reduced from 1024 - typical output ~150-300 tokens
        "top_p": None,
    },
    "hotels": {
        "model_hint": "small",
        "temperature": 0.3,  # Slightly creative for warm phrasing
        "max_tokens": 512,  # Reduced from 1024 - typical output ~150-300 tokens
        "top_p": None,
    },
    "transport": {
        "model_hint": "small",
        "temperature": 0.3,  # Slightly creative for warm phrasing
        "max_tokens": 512,  # Reduced from 1024 - typical output ~150-300 tokens
        "top_p": None,
    },
    "activities": {
        "model_hint": "small",
        "temperature": 0.3,  # Slightly creative for warm phrasing
        "max_tokens": 512,  # Reduced from 1024 - typical output ~150-300 tokens
        "top_p": None,
    },
    "correction": {
        "model_hint": "small",
        "temperature": 0.3,  # Slightly creative for warm phrasing
        "max_tokens": 512,  # Reduced from 1024 - typical output ~200-350 tokens
        "top_p": None,
    },
    "strategy": {
        "model_hint": "medium",
        "temperature": 0.3,  # Slightly creative for topic advice
        "max_tokens": 1536,  # Deep planning (reduced from 2048, aligned with FULL tier)
        "top_p": None,
    },
    "strategy_stage1": {
        "model_hint": "medium",
        "temperature": 0.3,  # Slightly creative for topic advice
        "max_tokens": 512,  # Stage 1: shortlist + skeleton only
        "top_p": None,
    },
    "strategy_stage2": {
        "model_hint": "medium",
        "temperature": 0.3,  # Slightly creative for topic advice
        "max_tokens": 1536,  # Stage 2: full detailed itinerary (reduced from 2048)
        "top_p": None,
    },
    "response_polish": {
        "model_hint": "small",
        "temperature": 0.4,  # Slightly creative for natural tone
        "max_tokens": 512,  # Must accommodate full polished messages from specialists
        "top_p": None,
    },
    "missing_fields_guard": {
        "model_hint": "small",
        "temperature": 0.3,  # Slightly creative for warm phrasing
        "max_tokens": 100,  # Very short output - just question + 3 suggestions
        "top_p": None,
    },
}


def _get_node_llm_config(node_name: str) -> Dict[str, Any]:
    """Get LLM configuration for a specific node, with fallback to defaults."""
    config = _NODE_LLM_CONFIG.get(node_name, {})
    return {
        "model_hint": config.get("model_hint", "medium"),
        "temperature": config.get("temperature", settings.openai_plan_temperature),
        "max_tokens": config.get("max_tokens", settings.openai_plan_max_tokens),
        "top_p": config.get("top_p"),
    }


# Generate plan trigger message
_GENERATE_PLAN_TRIGGER = "GENERATE_PLAN_NOW"


def _is_generate_plan_trigger(message: str) -> bool:
    """Check if the message is the special generate plan trigger."""
    return message.strip().upper() == _GENERATE_PLAN_TRIGGER


# =============================================================================
# SHORT-CIRCUIT PATTERNS FOR LIGHTWEIGHT FLOW
# =============================================================================
# These patterns detect simple inputs that can bypass the LLM router/specialist
# pipeline, saving ~800 tokens per message.
#
# NOTE: Patterns (GREETING_PATTERN, YES_PATTERN, NO_PATTERN, etc.) are now
# imported from the pattern_matching module.

# Greeting responses (terse, system-style)
_GREETING_RESPONSES = [
    "Destination?",
    "Where to?",
    "Enter destination.",
    "Set destination.",
]

# Off-topic deflection responses (used when router detects non-travel queries)
_OFF_TOPIC_DEFLECTIONS = [
    "Travel planning only. Destination?",
    "Outside scope. Destination?",
    "Travel queries only. Where to?",
    "Set a destination to continue.",
    "Enter destination.",
]


# =============================================================================
# EXTRACTOR MODE SELECTION (Light vs Full)
# =============================================================================
# Light extraction (~128 tokens) is used for early turns with simple input.
# Full extraction (~512 tokens) is used for dense input or when nearing ready_to_generate.
#
# NOTE: TOPIC_KEYWORDS, DENSE_INPUT_KEYWORDS, COMMA_LIST_PATTERN, and
# MULTI_DESTINATION_PATTERN are now imported from the pattern_matching module.


def _is_dense_input(text: str, state: "GraphState") -> tuple[bool, str]:
    """
    Determine if user input requires full extraction (vs light extraction).

    PHASE 2 OPTIMIZATION: Two-factor requirement for FULL mode.
    FULL extraction requires 2+ independent signals to prevent misfires
    from single-factor triggers (e.g., one keyword or just being long).

    Returns (is_dense, reason) where:
    - is_dense: True if full extraction needed (2+ factors present)
    - reason: Explanation for debug logging

    Signal categories (need 2+ from different categories):
    1. SETTINGS_KEYWORDS: Flight/hotel/transport/activity preferences
    2. STRUCTURED_LIST: Comma-separated or multi-destination phrases
    3. NEAR_READY: 2+ core fields already complete
    4. LONG_INPUT: >280 chars suggests complex request
    5. MULTI_SENTENCE: 3+ sentences suggests complex multi-part request

    Special case: Core-collection precondition
    If core fields are missing, require user to provide 2+ concrete core values
    in the same message to trigger FULL. This prevents FULL on simple turns.
    """
    text_lower = text.lower()

    # Track which signals are present
    signals: dict[str, bool] = {
        "settings_keywords": False,
        "structured_list": False,
        "near_ready": False,
        "long_input": False,
        "multi_sentence": False,
    }
    signal_details: dict[str, str] = {}

    # 1. Check for settings keywords (booking preferences, NOT topic/strategy keywords)
    settings_matches = [kw for kw in DENSE_INPUT_KEYWORDS if kw in text_lower]
    topic_matches = [kw for kw in TOPIC_KEYWORDS if kw in text_lower]

    # Log topic keywords for debugging (they affect routing, not extraction mode)
    if topic_matches:
        _debug(
            "📊 TOPIC_KEYWORDS: detected (routing only, not triggering FULL mode)",
            topic_keywords=topic_matches[:3],
        )

    if settings_matches:
        signals["settings_keywords"] = True
        signal_details["settings_keywords"] = ",".join(settings_matches[:3])
        _extractor_stats["dense_input_keywords"] += 1

    # 2. Check for structured list (comma-separated or multi-destination)
    comma_count = text.count(",")
    has_comma_list = comma_count >= 2 and COMMA_LIST_PATTERN.search(text)
    multi_dest_matches = MULTI_DESTINATION_PATTERN.findall(text)
    has_multi_dest = len(multi_dest_matches) >= 2

    if has_comma_list or has_multi_dest:
        signals["structured_list"] = True
        if has_comma_list:
            signal_details["structured_list"] = f"{comma_count}_commas"
            _extractor_stats["dense_input_commas"] += 1
        else:
            signal_details["structured_list"] = f"{len(multi_dest_matches)}_multi_dest"

    # 3. Check if nearing ready_to_generate (2+ core fields complete)
    ti = state.trip_inputs
    core_complete_count = sum(
        [
            bool(ti.destinations),
            bool(ti.origin),
            bool(ti.start_date),
        ]
    )
    if core_complete_count >= 2:
        signals["near_ready"] = True
        signal_details["near_ready"] = f"{core_complete_count}/3_core"

    # 4. Check for very long input
    if len(text) > 280:
        signals["long_input"] = True
        signal_details["long_input"] = f"{len(text)}_chars"
        _extractor_stats["dense_input_chars"] += 1

    # 5. Check for 3+ sentences
    sentence_count = len(re.findall(r"[.!?]+", text))
    if sentence_count >= 3:
        signals["multi_sentence"] = True
        signal_details["multi_sentence"] = f"{sentence_count}_sentences"
        _extractor_stats["dense_input_sentences"] += 1

    # Count active signals
    active_signals = [name for name, active in signals.items() if active]
    signal_count = len(active_signals)

    # ==========================================================================
    # TWO-FACTOR DECISION: Require 2+ signals for FULL mode
    # ==========================================================================
    if signal_count >= 2:
        # Multi-factor trigger - definitely use FULL
        reason = f"multifactor:{'+'.join(active_signals)}"
        _extractor_stats["full_mode"] += 1
        _extractor_stats["full_by_multifactor"] += 1
        _debug(
            "📊 DENSE_INPUT: FULL mode (2+ factors)",
            trigger_reason="multifactor",
            signals=active_signals,
            details=signal_details,
        )
        return True, reason

    elif signal_count == 1:
        # Single factor - apply core-collection precondition
        single_signal = active_signals[0]

        # EXCEPTION 1: near_ready always triggers FULL (user is close to done)
        if single_signal == "near_ready":
            reason = f"near_ready:{signal_details['near_ready']}"
            _extractor_stats["full_mode"] += 1
            _extractor_stats["full_by_near_ready"] += 1
            _debug(
                "📊 DENSE_INPUT: FULL mode (near-ready exception)",
                trigger_reason="near_ready",
                core_fields=core_complete_count,
            )
            return True, reason

        # EXCEPTION 2: settings_keywords with 3+ matches is strong signal
        if single_signal == "settings_keywords" and len(settings_matches) >= 3:
            reason = f"settings_keywords:{signal_details['settings_keywords']}"
            _extractor_stats["full_mode"] += 1
            _extractor_stats["full_by_settings_keywords"] += 1
            _debug(
                "📊 DENSE_INPUT: FULL mode (3+ settings keywords)",
                trigger_reason="settings_keywords",
                keywords=settings_matches[:5],
            )
            return True, reason

        # Otherwise, single factor is not enough - use LIGHT
        _extractor_stats["light_mode"] += 1
        _extractor_stats["full_rejected_single_factor"] += 1
        _debug(
            "📊 DENSE_INPUT: LIGHT mode (single factor rejected)",
            rejected_signal=single_signal,
            details=signal_details.get(single_signal, ""),
        )
        return False, f"single_factor_rejected:{single_signal}"

    # No signals - use LIGHT
    _extractor_stats["light_mode"] += 1
    _debug("Extractor mode: LIGHT", input_len=len(text), core_fields=core_complete_count)
    return False, "simple_input"


# =============================================================================
# PHASE 7: LQA (LAST QUESTION ANSWER) PRE-PASS
# =============================================================================
# Zero-LLM pre-pass that runs BEFORE extractor. When the system just asked
# for a specific field and the user gives a simple answer, we can parse it
# deterministically and skip extractor entirely. This is the highest-impact
# token savings for the common pattern:
#   Assistant: "Where are you flying from?"
#   User: "Amsterdam"
# Instead of ~544 input tokens for light extractor, we use 0 tokens.

# =============================================================================
# MVP OPTIMIZATION: DETERMINISTIC PARSING PIPELINE
# =============================================================================
# Pipeline order: Suggestion echo → Season/Date parser → Travelers parser → Place parser
# Runs BEFORE LQA at the top of lqa_prepass. On hit, returns LQA-shaped delta objects.
#
# Key features:
# - Suggestion echo: exact-match to last_suggestions with normalized fallback
# - Season parser: "next month", "this summer", "spring" → date ranges
# - Travelers parser: "solo", "couple", "family of 4" → adults/children deltas
# - Place parser: multi-value splitter for "Paris and Rome"
# - Conditional question_target advancement (doesn't advance if off-target answer)
# - Ambiguous date handling: straddle-today detection sets date_clarify_mode

# Observability stats for deterministic parsing
_deterministic_parse_stats: Dict[str, int] = {
    "suggestion_echo_hits": 0,
    "season_date_hits": 0,
    "relative_date_hits": 0,
    "travelers_hits": 0,
    "place_single_hits": 0,
    "place_multi_hits": 0,
    "date_ambiguous_count": 0,
    "extractor_light_blocked_trivial": 0,
}

# Season to approximate date range mapping (Northern hemisphere default)
# Returns (start_month, start_day, end_month, end_day)
_SEASON_TO_DATE_RANGE: Dict[str, Tuple[int, int, int, int]] = {
    "spring": (3, 15, 5, 31),  # Mid-March to end of May
    "summer": (6, 1, 8, 31),  # June to August
    "fall": (9, 1, 11, 30),  # September to November
    "autumn": (9, 1, 11, 30),  # Alias for fall
    "winter": (12, 1, 2, 28),  # December to February (cross-year)
}

# NOTE: Date patterns (RELATIVE_DATE_PATTERNS, SEASON_PATTERN), traveler patterns
# (TRAVELERS_MICRO_PATTERNS), place separators (PLACE_SEPARATORS_PATTERN),
# sentence verb pattern, and GREETING_BLOCKLIST are now imported from
# the pattern_matching module.


def _normalize_suggestion_text(text: str) -> str:
    """Normalize text for suggestion matching: trim, collapse spaces, casefold."""
    return " ".join(text.split()).casefold()


# NOTE: _MONTH_TO_MONTH_RANGE_PATTERN moved to pattern_matching.py (V26 extraction)
# Use MONTH_TO_MONTH_RANGE_PATTERN imported at module level


def _parse_month_to_month_range(text: str, state: "GraphState") -> Optional[Dict[str, Any]]:
    """
    Parse month-to-month range expressions like "September-November", "June to October".

    Returns:
        Dict with start_date_hint and end_date_hint, or None if not a month range.
    """
    text_stripped = text.strip()
    match = MONTH_TO_MONTH_RANGE_PATTERN.match(text_stripped)
    if not match:
        return None

    start_month_str = match.group(1).lower()
    end_month_str = match.group(2).lower()

    # Get reference date
    metadata = state.metadata or {}
    today_iso = metadata.get("today_iso")
    if today_iso:
        try:
            reference_date = datetime.strptime(today_iso, "%Y-%m-%d").date()
        except ValueError:
            reference_date = datetime.now(UTC).date()
    else:
        reference_date = datetime.now(UTC).date()

    # Parse month names to numbers
    try:
        start_month_num = datetime.strptime(start_month_str[:3], "%b").month
        end_month_num = datetime.strptime(end_month_str[:3], "%b").month
    except ValueError:
        return None

    year = reference_date.year

    # If start month is in the past this year, use next year
    if start_month_num < reference_date.month:
        year += 1
    elif start_month_num == reference_date.month and reference_date.day > 15:
        # Already mid-month, assume next year
        year += 1

    # Calculate end year - handle cross-year ranges (e.g., "November-February")
    end_year = year
    if end_month_num < start_month_num:
        # Cross-year range (e.g., November to February)
        end_year = year + 1

    # Build date range: 1st of start month to last day of end month
    start_date = f"{year:04d}-{start_month_num:02d}-01"

    # Get last day of end month
    if end_month_num == 12:
        next_month_first = datetime(end_year + 1, 1, 1)
    else:
        next_month_first = datetime(end_year, end_month_num + 1, 1)
    last_day = (next_month_first - timedelta(days=1)).day
    end_date = f"{end_year:04d}-{end_month_num:02d}-{last_day:02d}"

    return {"start_date_hint": start_date, "end_date_hint": end_date}


def _try_suggestion_echo(
    text: str,
    state: "GraphState",
) -> Optional[Dict[str, Any]]:
    """
    Try to match user text against last_suggestions.

    Returns LQA-shaped delta dict if match found, None otherwise.
    First tries raw exact match, then normalized match.

    v5 Lifecycle: Only matches if question_id matches, preventing stale echo.

    v6 Guards:
    - Skip in expanded mode (full planner UI doesn't use suggestion chips)
    - Require explicit click signal (prevents false positives from typed text)
    """
    # Guard 1: Skip in expanded mode (full planner UI)
    ui_phase = state.metadata.get("ui_phase")
    if ui_phase == "expanded":
        _debug("Suggestion echo skipped: ui_phase=expanded")
        return None

    # Guard 2: Require explicit click signal from frontend
    suggestion_clicked = state.metadata.get("suggestion_clicked")
    if not suggestion_clicked:
        _debug("Suggestion echo skipped: no suggestion_clicked signal")
        return None

    # Guard 3: Only process if clicked text matches user input
    if suggestion_clicked.strip().lower() != text.strip().lower():
        _debug(
            "Suggestion echo skipped: clicked text mismatch",
            clicked=suggestion_clicked[:50],
            text=text[:50],
        )
        return None

    last_suggestions = state.metadata.get("last_suggestions", [])
    if not last_suggestions:
        return None

    # v5: Check question_id to prevent stale suggestion echo
    stored_question_id = state.metadata.get("last_suggestions_question_id")
    current_question_id = state.metadata.get("question_id_counter", 0)

    # Only match if this is the immediately following turn (question_id matches)
    # The question_id is incremented when suggestions are stored, so matching
    # means the suggestions were emitted for the current question context
    if stored_question_id is not None and stored_question_id != current_question_id:
        _debug(
            "Suggestion echo skipped: stale question_id",
            stored_id=stored_question_id,
            current_id=current_question_id,
        )
        return None

    text_stripped = text.strip()
    text_normalized = _normalize_suggestion_text(text)

    for suggestion in last_suggestions:
        if isinstance(suggestion, dict):
            sugg_text = suggestion.get("text", "")
            sugg_field = suggestion.get("field", "")
        else:
            # Legacy format: just strings without field info
            sugg_text = str(suggestion)
            sugg_field = None

        if not sugg_text:
            continue

        # Check raw exact match first
        if text_stripped == sugg_text:
            matched = True
        # Then normalized match
        elif _normalize_suggestion_text(sugg_text) == text_normalized:
            matched = True
        else:
            matched = False

        if matched:
            _deterministic_parse_stats["suggestion_echo_hits"] += 1

            # Build delta based on suggestion field type
            delta: Dict[str, Any] = {"lqa_reason": "deterministic:suggestion_echo"}

            if sugg_field == "destinations":
                delta["destinations_delta"] = [sugg_text]
            elif sugg_field == "origin":
                delta["origin_delta"] = sugg_text
            elif sugg_field == "dates":
                # Try to parse the date from suggestion text
                # First try single date
                iso_date = _date_normalizer.normalize(sugg_text)
                if iso_date:
                    delta["start_date_delta"] = iso_date
                else:
                    # Try date range parsing (e.g., "December 20-27")
                    range_start, range_end = _date_normalizer.parse_date_range(sugg_text)
                    if range_start and range_end:
                        delta["start_date_delta"] = range_start
                        delta["end_date_delta"] = range_end
                    else:
                        # Try season/relative date parsing (e.g., "next month", "summer")
                        season_result = _try_season_date_parse(sugg_text, state)
                        if season_result:
                            if "start_date_delta" in season_result:
                                delta["start_date_delta"] = season_result["start_date_delta"]
                            if "end_date_delta" in season_result:
                                delta["end_date_delta"] = season_result["end_date_delta"]
                        else:
                            # Try month-to-month range (e.g., "September-November")
                            month_range_result = _parse_month_to_month_range(sugg_text, state)
                            if month_range_result:
                                if "start_date_hint" in month_range_result:
                                    delta["start_date_delta"] = month_range_result[
                                        "start_date_hint"
                                    ]
                                if "end_date_hint" in month_range_result:
                                    delta["end_date_delta"] = month_range_result["end_date_hint"]
            elif sugg_field == "travelers":
                # Try travelers parsing
                travelers_delta = _try_travelers_micro_parse(sugg_text)
                if travelers_delta:
                    delta.update(travelers_delta)
            else:
                # Unknown field - try to infer from content
                if is_known_place(sugg_text):
                    delta["destinations_delta"] = [sugg_text]
                else:
                    iso_date = _date_normalizer.normalize(sugg_text)
                    if iso_date:
                        delta["start_date_delta"] = iso_date

            _debug(
                "[DETERMINISTIC] Suggestion echo matched",
                suggestion=sugg_text,
                field=sugg_field,
                delta_keys=list(delta.keys()),
            )
            return delta

    return None


def _try_season_date_parse(
    text: str,
    state: "GraphState",
) -> Optional[Dict[str, Any]]:
    """
    Parse season/relative date expressions into date ranges.

    Handles:
    - "next month", "this month"
    - "next week", "this weekend", "next weekend"
    - "spring", "summer", "fall/autumn", "winter"
    - "this summer", "next spring"

    Returns LQA-shaped delta dict with start_date_delta/end_date_delta,
    or sets date_clarify_mode if ambiguous.
    """
    text_stripped = text.strip()
    text_lower = text_stripped.lower()

    # Get reference date
    normalizer = get_turn_date_normalizer(state)
    today = normalizer.today

    delta: Dict[str, Any] = {}

    # Check relative patterns first
    for pattern_name, pattern in RELATIVE_DATE_PATTERNS.items():
        if pattern.match(text_stripped):
            if pattern_name == "next_month":
                # Next month: 1st to last day of next month
                if today.month == 12:
                    start = date(today.year + 1, 1, 1)
                    end = date(today.year + 1, 1, 31)
                else:
                    start = date(today.year, today.month + 1, 1)
                    # Last day of next month
                    if today.month + 1 == 12:
                        end = date(today.year, 12, 31)
                    else:
                        end = date(today.year, today.month + 2, 1) - timedelta(days=1)

                delta["start_date_delta"] = start.strftime("%Y-%m-%d")
                delta["end_date_delta"] = end.strftime("%Y-%m-%d")
                delta["lqa_reason"] = "deterministic:date_answer"
                _deterministic_parse_stats["relative_date_hits"] += 1
                return delta

            elif pattern_name == "this_month":
                start = today
                if today.month == 12:
                    end = date(today.year, 12, 31)
                else:
                    end = date(today.year, today.month + 1, 1) - timedelta(days=1)

                delta["start_date_delta"] = start.strftime("%Y-%m-%d")
                delta["end_date_delta"] = end.strftime("%Y-%m-%d")
                delta["lqa_reason"] = "deterministic:date_answer"
                _deterministic_parse_stats["relative_date_hits"] += 1
                return delta

            elif pattern_name == "next_week":
                # Start next Monday, end next Sunday
                days_until_monday = (7 - today.weekday()) % 7
                if days_until_monday == 0:
                    days_until_monday = 7
                start = today + timedelta(days=days_until_monday)
                end = start + timedelta(days=6)

                delta["start_date_delta"] = start.strftime("%Y-%m-%d")
                delta["end_date_delta"] = end.strftime("%Y-%m-%d")
                delta["lqa_reason"] = "deterministic:date_answer"
                _deterministic_parse_stats["relative_date_hits"] += 1
                return delta

            elif pattern_name in ("this_weekend", "next_weekend"):
                # Saturday to Sunday
                days_until_saturday = (5 - today.weekday()) % 7
                if pattern_name == "next_weekend":
                    days_until_saturday += 7
                elif days_until_saturday == 0 and today.weekday() >= 5:
                    # Already weekend, "this weekend" means this one
                    days_until_saturday = 0 if today.weekday() == 5 else -1

                start = today + timedelta(days=days_until_saturday)
                end = start + timedelta(days=1)

                delta["start_date_delta"] = start.strftime("%Y-%m-%d")
                delta["end_date_delta"] = end.strftime("%Y-%m-%d")
                delta["lqa_reason"] = "deterministic:date_answer"
                _deterministic_parse_stats["relative_date_hits"] += 1
                return delta

            elif pattern_name == "tomorrow":
                start = today + timedelta(days=1)
                delta["start_date_delta"] = start.strftime("%Y-%m-%d")
                delta["lqa_reason"] = "deterministic:date_answer"
                _deterministic_parse_stats["relative_date_hits"] += 1
                return delta

            elif pattern_name == "today":
                delta["start_date_delta"] = today.strftime("%Y-%m-%d")
                delta["lqa_reason"] = "deterministic:date_answer"
                _deterministic_parse_stats["relative_date_hits"] += 1
                return delta

            elif pattern_name in ("next_weekday", "this_weekday"):
                # Extract the day name from the match
                match = pattern.match(text_stripped)
                if match:
                    weekday_names = {
                        "monday": 0,
                        "tuesday": 1,
                        "wednesday": 2,
                        "thursday": 3,
                        "friday": 4,
                        "saturday": 5,
                        "sunday": 6,
                    }
                    target_day = weekday_names[match.group(1).lower()]
                    days_ahead = (target_day - today.weekday()) % 7
                    # "next X" means at least 1 day ahead; if today is that day, go to next week
                    if days_ahead == 0 and pattern_name == "next_weekday":
                        days_ahead = 7
                    start = today + timedelta(days=days_ahead)
                    delta["start_date_delta"] = start.strftime("%Y-%m-%d")
                    delta["lqa_reason"] = "deterministic:date_answer"
                    _deterministic_parse_stats["relative_date_hits"] += 1
                    return delta

    # Check season pattern
    season_match = SEASON_PATTERN.match(text_stripped)
    if season_match:
        season = season_match.group(1).lower()
        if season in _SEASON_TO_DATE_RANGE:
            start_month, start_day, end_month, end_day = _SEASON_TO_DATE_RANGE[season]

            # Determine year: "next" prefix or season in past
            is_next = "next" in text_lower
            is_this = "this" in text_lower
            year = today.year

            # Check if season straddles today (ambiguous without qualifier)
            # Only trigger clarification if no explicit "this" or "next" qualifier
            if not is_next and not is_this:
                season_start_this_year = date(year, start_month, start_day)
                season_end_this_year = date(
                    year if end_month >= start_month else year + 1,
                    end_month,
                    min(end_day, 28) if end_month == 2 else end_day,
                )

                # Check if we're currently in this season (straddle case)
                if season_start_this_year <= today <= season_end_this_year:
                    # Generate specific month suggestions for clarification
                    import calendar

                    current_year = today.year
                    next_year = current_year + 1

                    # Remaining months in current season (this year)
                    remaining_months = []
                    for month in range(today.month, end_month + 1):
                        if month <= 12:
                            month_name = calendar.month_name[month]
                            remaining_months.append(f"{month_name} {current_year}")

                    # Next year's season months
                    next_year_months = []
                    for month in range(start_month, min(end_month + 1, start_month + 3)):
                        if month <= 12:
                            month_name = calendar.month_name[month]
                            next_year_months.append(f"{month_name} {next_year}")

                    # Build suggestions: 2 from remaining + 1 from next year
                    clarify_suggestions = remaining_months[:2] + next_year_months[:1]
                    if not clarify_suggestions:
                        clarify_suggestions = [
                            f"This {season.capitalize()}",
                            f"Next {season.capitalize()}",
                        ]

                    _debug(
                        "[DETERMINISTIC] Season straddles today, triggering clarification",
                        season=season,
                        today=today.strftime("%Y-%m-%d"),
                        suggestions=clarify_suggestions,
                    )
                    _deterministic_parse_stats["season_ambiguous_count"] = (
                        _deterministic_parse_stats.get("season_ambiguous_count", 0) + 1
                    )

                    return {
                        "lqa_reason": "deterministic:season_ambiguous",
                        "_date_clarify_mode": True,
                        "_pending_date_text": text,
                        "_clarify_suggestions": clarify_suggestions,
                        "_season_name": season.capitalize(),
                    }

            # For winter, handle cross-year
            if season == "winter":
                if is_next or today.month >= 3:
                    # Next winter or we're past Feb
                    start = date(year, 12, 1)
                    end = date(year + 1, 2, 28)
                else:
                    # Current winter
                    start = date(year - 1, 12, 1) if today.month <= 2 else date(year, 12, 1)
                    end = date(year, 2, 28)
            else:
                # Check if season is in the past this year
                season_start = date(year, start_month, start_day)
                if season_start < today and not is_next:
                    year += 1
                elif is_next:
                    if season_start >= today:
                        year += 1

                start = date(year, start_month, start_day)
                try:
                    end = date(year, end_month, end_day)
                except ValueError:
                    # Handle Feb 28/29
                    end = date(year, end_month, 28)

            delta["start_date_delta"] = start.strftime("%Y-%m-%d")
            delta["end_date_delta"] = end.strftime("%Y-%m-%d")
            delta["lqa_reason"] = "deterministic:date_answer"
            delta["_season_hemisphere_assumed"] = "north"
            _deterministic_parse_stats["season_date_hits"] += 1

            _debug(
                "[DETERMINISTIC] Season parsed",
                season=season,
                start=delta["start_date_delta"],
                end=delta["end_date_delta"],
            )
            return delta

    return None


def _try_travelers_micro_parse(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse simple travelers expressions.

    Handles:
    - "solo", "just me" → adults=1
    - "couple", "2 of us" → adults=2
    - "family of 4" → adults=2, children=2 (assumes 2 adults)
    - "3 adults", "4 people" → adults=N

    Returns dict with adults_delta and optionally children_delta.
    """
    text_stripped = text.strip()

    # Solo patterns
    if TRAVELERS_MICRO_PATTERNS["solo"].match(text_stripped):
        _deterministic_parse_stats["travelers_hits"] += 1
        return {"adults_delta": 1, "lqa_reason": "deterministic:travelers_answer"}

    # Couple patterns
    if TRAVELERS_MICRO_PATTERNS["couple"].match(text_stripped):
        _deterministic_parse_stats["travelers_hits"] += 1
        return {"adults_delta": 2, "lqa_reason": "deterministic:travelers_answer"}

    # Family of N
    family_match = TRAVELERS_MICRO_PATTERNS["family"].match(text_stripped)
    if family_match:
        total = int(family_match.group(1))
        # Assume 2 adults if family of 4+
        adults = min(2, total)
        children = max(0, total - adults)
        _deterministic_parse_stats["travelers_hits"] += 1
        return {
            "adults_delta": adults,
            "children_delta": children,
            "lqa_reason": "deterministic:travelers_answer",
        }

    # N people/adults
    group_match = TRAVELERS_MICRO_PATTERNS["group"].match(text_stripped)
    if group_match:
        count = int(group_match.group(1))
        if 1 <= count <= 20:
            _deterministic_parse_stats["travelers_hits"] += 1
            return {"adults_delta": count, "lqa_reason": "deterministic:travelers_answer"}

    return None


def _try_place_parse(
    text: str,
    state: "GraphState",
    question_target: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Parse place-like text into destinations or origin delta.

    Handles:
    - Single known places: "Patagonia" → destinations_delta
    - Multi-place with separators: "Paris and Rome" → destinations_delta
    - "from X" prefix for origin questions: "from London" → origin_delta
    - Title-case heuristic for unknown places

    Multi-place split rules:
    - Only split if separator present AND at least one segment is known_place
    - Don't split if verbs present (it's a sentence)
    - Cap at 3 places

    Returns LQA-shaped delta dict or None.
    """
    text_stripped = text.strip()

    # Handle "from X" prefix for origin questions
    if question_target == "origin":
        origin_match = ORIGIN_PREFIX_PATTERN.match(text_stripped)
        if origin_match:
            text_stripped = origin_match.group(2).strip()

    text_lower = text_stripped.lower()

    # Don't parse if it contains verbs (likely a sentence, not place list)
    if SENTENCE_VERB_PATTERN.search(text_stripped):
        return None

    # Check greeting blocklist for title-case false positives
    if text_lower in GREETING_BLOCKLIST:
        return None

    # Try multi-place split first if separator present
    if PLACE_SEPARATORS_PATTERN.search(text_stripped):
        segments = PLACE_SEPARATORS_PATTERN.split(text_stripped)
        segments = [s.strip() for s in segments if s.strip()]

        if len(segments) >= 2:
            # Check if at least one segment is a known place
            known_count = sum(1 for s in segments if is_known_place(s))

            if known_count >= 1:
                # Canonicalize and filter
                places = []
                for s in segments[:3]:  # Cap at 3
                    normalized = normalize_place_synonym(s)
                    if normalized and len(normalized) > 1:
                        places.append(normalized)

                if len(places) >= 2:
                    _deterministic_parse_stats["place_multi_hits"] += 1
                    return {
                        "destinations_delta": places,
                        "lqa_reason": "deterministic:place_answer",
                        "_multi_city_signal": True,
                    }

    # Single place check
    normalized = normalize_place_synonym(text_stripped)
    if is_known_place(normalized) or is_known_place(text_stripped):
        _deterministic_parse_stats["place_single_hits"] += 1

        # Determine if origin or destination based on question_target
        if question_target == "origin":
            return {
                "origin_delta": normalized,
                "lqa_reason": "deterministic:place_answer",
            }
        else:
            return {
                "destinations_delta": [normalized],
                "lqa_reason": "deterministic:place_answer",
            }

    # Title-case heuristic for unknown places
    # Require 2+ capitalized words OR single word with 4+ chars
    words = text_stripped.split()
    capitalized = [w for w in words if w and w[0].isupper() and len(w) > 1]

    if len(capitalized) >= 2:
        # Multiple capitalized words - likely a place
        _deterministic_parse_stats["place_single_hits"] += 1
        if question_target == "origin":
            return {
                "origin_delta": text_stripped,
                "lqa_reason": "deterministic:place_answer",
            }
        else:
            return {
                "destinations_delta": [text_stripped],
                "lqa_reason": "deterministic:place_answer",
            }
    elif len(capitalized) == 1 and len(capitalized[0]) >= 4:
        # Single capitalized word, 4+ chars, not a greeting
        word_lower = capitalized[0].lower()
        if word_lower not in GREETING_BLOCKLIST and word_lower not in _MONTH_NAMES:
            _deterministic_parse_stats["place_single_hits"] += 1
            if question_target == "origin":
                return {
                    "origin_delta": text_stripped,
                    "lqa_reason": "deterministic:place_answer",
                }
            else:
                return {
                    "destinations_delta": [text_stripped],
                    "lqa_reason": "deterministic:place_answer",
                }

    return None


def _run_deterministic_pipeline(
    text: str,
    state: "GraphState",
) -> Optional[Dict[str, Any]]:
    """
    Main entry point for deterministic parsing pipeline.

    Pipeline order: Suggestion echo → Date parser → Travelers parser → Place parser

    v6 ENHANCEMENT: Travelers parser runs UNCONDITIONALLY for short inputs (≤20 chars)
    to catch simple traveler expressions regardless of question_target.

    Top-level guard: Only runs if question_target is set OR last_suggestions non-empty
                     OR input is short (≤20 chars) for unconditional travelers parse.

    Returns LQA-shaped delta dict on hit, None on miss.
    On hit, also sets metadata for conditional question_target advancement.
    """
    question_target = canonicalize_question_target(
        state.question_target or state.metadata.get("last_question_field")
    )
    last_suggestions = state.metadata.get("last_suggestions", [])

    text_stripped = text.strip()
    if not text_stripped:
        return None

    is_short_input = len(text_stripped) <= 20

    # v6: Unconditional travelers parse for short inputs
    # This catches "family of four" etc even when question_target is "destinations"
    if is_short_input:
        # Check if travelers field is unset (only write if not already set)
        ti = state.trip_inputs
        travelers_unset = ti.adults is None or ti.adults == 0

        if travelers_unset:
            travelers_result = _try_travelers_micro_parse(text)
            if travelers_result:
                # Set intent to prevent unrelated question prompts
                travelers_result["_intent_override"] = "update_travelers"
                travelers_result["_provenance_source_node"] = "deterministic_pipeline.travelers"
                travelers_result["_llm_suppressed_reason"] = "deterministic_parse:travelers"
                _debug(
                    "UNCONDITIONAL_TRAVELERS_PARSE",
                    text=text_stripped,
                    result=travelers_result,
                )
                return travelers_result

    # Top-level guard: only run remaining pipeline if we have context
    if not question_target and not last_suggestions:
        return None

    # 1. Suggestion echo (highest priority - user clicked a suggestion)
    result = _try_suggestion_echo(text, state)
    if result:
        return result

    # 1.5 P2.3: Compound travelers+date parsing
    # Catches patterns like "2 adults for next month" in one pass
    from app.planner.parsing import _parse_compound_travelers_date

    compound_result = _parse_compound_travelers_date(text, state)
    if compound_result:
        _deterministic_parse_stats["compound_parse_hits"] = (
            _deterministic_parse_stats.get("compound_parse_hits", 0) + 1
        )
        return compound_result

    # 2. Date/season parser (if question_target is dates or if date-like)
    if question_target in ("dates", "start_date", "end_date") or _is_date_like_text(text):
        result = _try_season_date_parse(text, state)
        if result:
            return result

        # Also try date range parsing with ambiguity detection
        normalizer = get_turn_date_normalizer(state)
        start, end, is_ambiguous = normalizer.parse_date_range_with_ambiguity(text)
        if start and end:
            if is_ambiguous:
                # Set clarify mode, don't return dates
                _deterministic_parse_stats["date_ambiguous_count"] += 1
                return {
                    "lqa_reason": "deterministic:date_ambiguous",
                    "_date_clarify_mode": True,
                    "_pending_date_text": text,
                }
            else:
                _deterministic_parse_stats["relative_date_hits"] += 1
                return {
                    "start_date_delta": start,
                    "end_date_delta": end,
                    "lqa_reason": "deterministic:date_answer",
                }

        # Try month-to-month range parsing (e.g., "September-November")
        month_range_result = _parse_month_to_month_range(text, state)
        if month_range_result:
            _deterministic_parse_stats["relative_date_hits"] += 1
            return {
                "start_date_delta": month_range_result["start_date_hint"],
                "end_date_delta": month_range_result["end_date_hint"],
                "lqa_reason": "deterministic:month_range_answer",
            }

    # 3. Travelers parser (if question_target is travelers)
    # Note: unconditional parse already ran above for short inputs
    if question_target == "travelers" and not is_short_input:
        result = _try_travelers_micro_parse(text)
        if result:
            return result

    # 4. Place parser (for destinations/origin only)
    # When question_target is dates/travelers, do NOT parse place - let existing
    # "not_date_like" / "not_travelers_like" bail logic handle it
    if question_target in ("destinations", "origin"):
        result = _try_place_parse(text, state, question_target)
        if result:
            return result

    return None


# =============================================================================
# LLM CALL CAP HELPER (Centralized enforcement - v5 Routing Observability)
# =============================================================================
# Prevents multiple LLM calls per turn during core field collection.
# Increment-before-call semantics; on exception, do not decrement.
# This is the ONLY place that increments llm_calls_this_turn and tracks nodes.


def can_call_llm(state: "GraphState", node_name: str) -> bool:
    """
    Check if an LLM call is allowed for this turn.

    This is the ONLY function that should:
    - Increment metadata.llm_calls_this_turn
    - Append to metadata.llm_nodes_called_this_turn
    - Set metadata.llm_call_blocked_reason[node_name]

    Enforces at-most-1 LLM call per turn when:
    - readiness.ready == False (still collecting core fields)
    - question_target is set

    Args:
        state: Current graph state
        node_name: Name of node requesting LLM call

    Returns:
        True if LLM call is allowed, False if blocked
    """
    # Initialize counters/trackers if needed (PR2: Use constants)
    if LLM_CALLS_THIS_TURN not in state.metadata:
        state.metadata[LLM_CALLS_THIS_TURN] = 0
    if LLM_CALL_SITES not in state.metadata:
        state.metadata[LLM_CALL_SITES] = []
    if LLM_CALL_BLOCKED_REASON not in state.metadata:
        state.metadata[LLM_CALL_BLOCKED_REASON] = {}
    if "llm_call_blocked_count" not in state.metadata:
        state.metadata["llm_call_blocked_count"] = {}

    # Check if we're in core collection mode
    readiness = compute_trip_readiness(state.trip_inputs)
    question_target = state.question_target or state.metadata.get("last_question_field")

    # If ready or no question_target, no cap
    if readiness.ready_to_generate or not question_target:
        # Still track but don't enforce cap
        state.metadata[LLM_CALLS_THIS_TURN] += 1
        state.metadata[LLM_CALL_SITES].append(node_name)
        return True

    current_calls = state.metadata[LLM_CALLS_THIS_TURN]
    max_calls = (
        settings.max_llm_calls_per_turn if hasattr(settings, "max_llm_calls_per_turn") else 1
    )

    if current_calls >= max_calls:
        _debug(
            "LLM call blocked by cap",
            node=node_name,
            current_calls=current_calls,
            max_calls=max_calls,
        )
        _deterministic_parse_stats["extractor_light_blocked_trivial"] += 1
        # Track blocked reason per node (dict format for v5)
        state.metadata[LLM_CALL_BLOCKED_REASON][node_name] = "budget_exhausted"
        # Track blocked count per node for observability
        blocked_counts = state.metadata["llm_call_blocked_count"]
        blocked_counts[node_name] = blocked_counts.get(node_name, 0) + 1
        return False

    # Increment before call (never decrement on error)
    state.metadata[LLM_CALLS_THIS_TURN] += 1
    state.metadata[LLM_CALL_SITES].append(node_name)

    # V12: Generate unique LLM call ID for tracing
    turn_id = state.metadata.get(TURN_CANARY, "unknown")[:8]
    step = state.metadata.get(STEP_COUNT, 0)
    call_num = state.metadata[LLM_CALLS_THIS_TURN]
    llm_call_id = f"{turn_id}:{node_name}:{step}:{call_num}"

    _debug(
        "LLM call allowed",
        node=node_name,
        call_number=call_num,
        llm_call_id=llm_call_id,
    )
    return True


def llm_blocked_fallback(
    state: "GraphState",
    asked_target: Optional[str],
    *,
    source: str = "unknown",
) -> Dict[str, Any]:
    """
    Produce a deterministic response when LLM budget is exhausted.

    Mutates state with a required_fields template question for asked_target,
    or dates clarify if date_clarify_mode is active.
    Guarantees non-empty assistant_message.

    Args:
        state: Current graph state (will be mutated)
        asked_target: The field being asked about (will be canonicalized)
        source: Node/function name that invoked fallback (for debugging)

    Returns:
        Dict with assistant_message, question_target, fallback_reason
    """
    # If date_clarify_mode, force dates clarification
    if state.metadata.get("date_clarify_mode"):
        asked_target = "dates"

    # Canonicalize target
    target = canonicalize_question_target(asked_target) or "destinations"

    # Load template question for this target
    template_resp = _get_template_response(target, state.strategy_topic)

    if template_resp:
        question = template_resp["question"]
        suggestions = template_resp.get("suggestions", [])
    else:
        # Hardcoded fallback if no template
        fallback_questions = {
            "destinations": "Destination?",
            "dates": "Dates?",
            "duration": "How long is your trip?",
            "travelers": "Travelers?",
            "origin": "Origin?",
            "budget": "Budget?",
        }
        question = fallback_questions.get(target, "Missing constraint.")
        suggestions = []

    # Mutate state with fallback response
    state.last_summary = question
    state.suggested_responses = suggestions if suggestions else []
    state.question_target = target

    # Set parse provenance for template fallback
    set_parse_provenance(state, "template")
    # Also set response generation provenance since we're generating a response
    state.metadata["response_writer_node"] = f"llm_blocked_fallback:{source}"
    state.metadata["response_generation_provenance"] = "template"
    state.metadata["question_target"] = target
    state.metadata["fallback_source"] = source

    _debug(
        "LLM blocked fallback used",
        source=source,
        target=target,
        question_preview=question[:50] if question else None,
    )

    return {
        "assistant_message": question,
        "question_target": target,
        "suggestions": suggestions,
        "fallback_reason": "llm_budget_exhausted",
        "fallback_source": source,
    }


# =============================================================================
# PROVENANCE TRACKING (v6/v7 Hybrid System)
# =============================================================================
# Tier 4: Parse provenance functions extracted to app/planner/parsing/provenance.py
# Imported at module level: PARSE_PROVENANCE_PRECEDENCE, set_parse_provenance_once,
# finalize_parse_provenance, get_parse_provenance, set_parse_provenance
#
# Two provenance types:
# 1. response_generation_provenance: How the FINAL user-facing response was generated
#    - Uses "final producer wins" via set_final_response() at end of run_turn
#    - NOT precedence-based; the last node to produce response text wins
# 2. parse_provenance: How data was EXTRACTED/PARSED from user input
#    - Uses precedence-based write-once semantics (set_parse_provenance_once)
#    - See app/planner/parsing/provenance.py for implementation


# =============================================================================
# RESPONSE SOURCE NODE TRACKING (v5 Routing Observability)
# =============================================================================
# Write-once per turn: tracks which node produced the user-facing response.
# Used by RoutingDecisionFinal.executed_node to compare against gate destination.


def set_response_source(
    state: "GraphState",
    node_name: str,
    provenance: str,
) -> None:
    """
    Set the response source node (write-once per turn).

    Only the FIRST call per turn takes effect - prevents later nodes
    (summarize/polish) from overwriting the original message producer.

    Args:
        state: Graph state to update
        node_name: Name of the node producing the response
        provenance: Response provenance ("template", "llm", "deterministic", "codegen")
    """
    if state.metadata.get("response_source_node") is None:
        state.metadata["response_source_node"] = node_name
        state.metadata["response_generation_provenance"] = provenance
        _debug(
            "Response source set",
            node=node_name,
            provenance=provenance,
        )


def set_final_response(
    state: "GraphState",
    response: str,
    node_name: str,
    provenance: str,
) -> None:
    """
    Finalize response provenance with hash-guarded overwrite.

    This is called at the end of run_turn after polish to ensure provenance
    accurately reflects the final response text. Uses hash comparison to
    detect if the response changed (e.g., polish rewrote it).

    CRITICAL: Must set provenance on first call (when prev_hash is None) AND
    when response text changes. This fixes the bug where LLM responses were
    incorrectly treated as deterministic due to provenance never being set.

    Args:
        state: Graph state to update
        response: The final response text
        node_name: Name of the node that produced the final response
        provenance: Final response provenance
    """
    # Early return if response is empty/None to avoid hashing errors
    if not response:
        _debug(
            "set_final_response: skipping (empty response)",
            node_name=node_name,
            provenance=provenance,
        )
        return

    # Compute stable hash of final response (deterministic across runs)
    response_text_hash = hashlib.sha256(response.encode()).hexdigest()[:16]

    # Check if this is first finalization OR response changed
    prev_hash = state.metadata.get("response_text_hash")
    if prev_hash is None or prev_hash != response_text_hash:
        # First call this turn OR response was modified (e.g., by polish)
        _debug(
            "Finalizing response provenance",
            first_call=(prev_hash is None),
            hash_changed=(prev_hash != response_text_hash if prev_hash else False),
            original_node=state.metadata.get("response_source_node"),
            new_node=node_name,
            new_provenance=provenance,
        )
        state.metadata["response_source_node"] = node_name
        state.metadata["response_generation_provenance"] = provenance

    # Store hash for next comparison
    state.metadata["response_text_hash"] = response_text_hash


def get_response_source_node(state: "GraphState") -> Optional[str]:
    """Get the response source node if set."""
    return state.metadata.get("response_source_node")


# =============================================================================
# SUGGESTION CHANNEL WITH FIELD INFO + QUESTION_ID (v5 Lifecycle)
# =============================================================================
# Stores suggestions with field type for deterministic echo matching.
# Uses question_id to prevent stale suggestion echo matching.


def _increment_question_id(state: "GraphState") -> int:
    """
    Increment and return the question_id counter.

    Called only when emitting a question (not every turn).
    """
    counter = state.metadata.get("question_id_counter", 0) + 1
    state.metadata["question_id_counter"] = counter
    return counter


def should_increment_question_id(
    state: "GraphState",
    assistant_message: str,
    suggestions: List[str],
) -> bool:
    """
    Determine if question_id should be incremented.

    A question emission is defined as:
    - len(suggestions) > 0, OR
    - question_target is set AND assistant_message ends with "?"

    This prevents question_id changing during summaries/recovery messages.
    """
    question_target = state.question_target or state.metadata.get("question_target")
    has_suggestions = len(suggestions) > 0
    ends_with_question = assistant_message.rstrip().endswith("?") if assistant_message else False

    return has_suggestions or (question_target and ends_with_question)


def store_suggestions_with_field(
    state: "GraphState",
    suggestions: List[str],
    field: str,
) -> None:
    """
    Store suggestions in metadata with field type info for deterministic echo.

    This creates the `last_suggestions` list in metadata which is used by
    the deterministic pipeline to match user input to suggestions and
    know what field to set.

    Also stores the question_id for the current question emission to prevent
    stale suggestion echo matching.

    Args:
        state: Graph state to update
        suggestions: List of suggestion strings (e.g., ["Paris", "Tokyo"])
        field: Field type for these suggestions (e.g., "destinations", "dates")
    """
    if not suggestions:
        state.metadata["last_suggestions"] = []
        return

    # Increment question_id for this new question emission
    question_id = _increment_question_id(state)
    state.metadata["last_suggestions_question_id"] = question_id
    state.metadata["last_suggestions_target"] = field

    state.metadata["last_suggestions"] = [
        {"text": s.strip(), "field": field} for s in suggestions if s and s.strip()
    ]

    _debug(
        "Stored suggestions with question_id",
        field=field,
        question_id=question_id,
        suggestion_count=len(suggestions),
    )


# =============================================================================
# APPLY LQA-LIKE DELTAS (v5 Unified Delta Merge)
# =============================================================================
# Unified helper for applying deltas from both LQA and deterministic paths.
# Ensures idempotent, journal-aware, provenance-tracked delta application.
# NEVER advances question_target - only "keeps current" for explicit overrides.


def apply_lqa_like_deltas(
    state: "GraphState",
    deltas: Dict[str, Any],
    *,
    reason: str,
    provenance_node: str,
) -> List[str]:
    """
    Apply deltas from LQA or deterministic parsing paths with unified semantics.

    This is the ONLY function that should apply deltas from:
    - LQA hit path
    - Deterministic pipeline (suggestion echo, date parser, travelers parser, place parser)

    Guarantees:
    - Idempotent: safe to call twice with same deltas
    - Journal-aware: records node and provenance
    - Destinations deduped (no duplicate additions)
    - NEVER advances question_target - only "keeps current" for explicit overrides

    Args:
        state: Graph state to update
        deltas: Dict of field updates
            (e.g., {"destinations_delta": ["Paris"], "origin_delta": "NYC"})
        reason: Extraction path reason (e.g., "lqa:hit", "deterministic:suggestion_echo")
        provenance_node: Node name for journaling (e.g., "lqa_prepass", "deterministic_prepass")

    Returns:
        List of canonical field names actually written (stable sorted by CANONICAL_FIELD_ORDER)
    """
    # Set extraction path metadata
    state.metadata["lqa_reason"] = reason
    state.metadata["extraction_path"] = provenance_node

    # Convert delta keys to canonical field names for _write_trip_inputs
    updates: Dict[str, Any] = {}

    # Handle destinations_delta - dedupe with existing
    if "destinations_delta" in deltas:
        new_dests = deltas["destinations_delta"]
        if isinstance(new_dests, list):
            existing = state.trip_inputs.destinations or []
            # Dedupe: only add destinations not already present
            existing_set = {d.lower() for d in existing}
            deduped = [d for d in new_dests if d.lower() not in existing_set]
            if deduped:
                updates["destinations"] = existing + deduped

    # Handle origin_delta
    if "origin_delta" in deltas and deltas["origin_delta"]:
        updates["origin"] = deltas["origin_delta"]

    # Handle date deltas
    if "start_date_delta" in deltas and deltas["start_date_delta"]:
        updates["start_date"] = deltas["start_date_delta"]
    if "end_date_delta" in deltas and deltas["end_date_delta"]:
        updates["end_date"] = deltas["end_date_delta"]

    # Handle travelers deltas
    if "adults_delta" in deltas and deltas["adults_delta"] is not None:
        updates["adults"] = deltas["adults_delta"]
    if "children_delta" in deltas and deltas["children_delta"] is not None:
        updates["children"] = deltas["children_delta"]

    # Handle budget delta
    if "budget_delta" in deltas and deltas["budget_delta"] is not None:
        updates["budget"] = deltas["budget_delta"]

    # Handle "budget_answered" flag (user said "no budget"/"flexible"/etc.)
    # This marks budget as answered so we don't re-ask
    if deltas.get("budget_answered"):
        state.metadata["budget_answered"] = True
        if deltas.get("budget_tier"):
            state.metadata["budget_tier"] = deltas["budget_tier"]

    if not updates and not deltas.get("budget_answered"):
        return []

    # Apply via _write_trip_inputs with LQA provenance
    _, fields_changed = _write_trip_inputs(
        state,
        provenance_node,
        provenance="explicit",  # LQA/deterministic deltas are user-confirmed
        **updates,
    )

    # Record to journal with node/provenance
    turn_journal = state.metadata.get("turn_journal", [])
    turn_number = getattr(state, "turn_number", 0)
    for entry in turn_journal:
        if entry.get("turn") == turn_number:
            entry["lqa_node"] = provenance_node
            entry["lqa_provenance"] = reason
            break

    _debug(
        "apply_lqa_like_deltas applied",
        reason=reason,
        node=provenance_node,
        fields_changed=fields_changed,
    )

    return fields_changed


# =============================================================================
# v7 Final v5: TRAVELER-DETAIL RECOGNIZER (pre-bail pattern check)
# =============================================================================
# Pattern to detect traveler detail answers like "3 kids ages 5, 8, 12"
# These contain commas for age lists but are NOT multi-intent.
# Must run BEFORE LQA_BAIL_PATTERNS to avoid false-positive bail.
#
# NOTE: TRAVELER_DETAIL_PATTERN, TRAVELER_AGES_ONLY_PATTERN, and
# is_traveler_detail_answer() are now imported from the pattern_matching module.

# Local alias for compatibility
_is_traveler_detail_answer = is_traveler_detail_answer


# =============================================================================
# v7 Final v5: TEXT COMPATIBILITY WITH QUESTION TARGET
# =============================================================================
# Pure deterministic function to check if user text is compatible with the
# current question_target. Used for conservative topic-switch bypass.
#
# NOTE: BUDGET_COMPATIBILITY_PATTERN, DATES_COMPATIBILITY_PATTERN,
# TRAVELERS_COMPATIBILITY_PATTERN, and text_is_compatible_with_target()
# are now imported from the pattern_matching module.

# NOTE: LQA_BAIL_PATTERNS are now imported from the pattern_matching module.


def _try_initial_message_extraction(text: str, state: "GraphState") -> Optional[Dict[str, Any]]:
    """
    Phase 6: Attempt zero-LLM extraction for initial messages.

    Unlike fast-path which requires question_target, this handles first-turn
    messages that clearly express trip intent with recognizable patterns.

    Examples handled:
    - "I want to go to Paris" → destinations: [Paris]
    - "Trip to Rome from London" → destinations: [Rome], origin: London
    - "2 adults, Barcelona, next month" → adults: 2, destinations: [Barcelona], dates
    - "Paris" (when it's clearly a destination) → destinations: [Paris]

    Requirements:
    - Input must be relatively short (<100 chars)
    - Must match at least one field pattern
    - Extracted place names must be known places

    Args:
        text: User input text
        state: Current graph state

    Returns:
        Dict with parsed data if extraction succeeds, None otherwise.
        Dict format: {
            "type": "initial_extraction",
            "fields": [list of extracted field names],
            "parsed": {...},  # Parsed data to merge into parsed_inputs
        }
    """
    text_clean = text.strip()

    # Gate: Only process short-to-medium inputs (first turn messages)
    if len(text_clean) > 100:
        _debug(f"[INITIAL_EXTRACT] MISS: text too long ({len(text_clean)} > 100)")
        return None

    # Gate: Skip if question_target is set (fast-path should handle those)
    question_target = state.question_target or state.metadata.get("last_question_field")
    if question_target:
        _debug(f"[INITIAL_EXTRACT] MISS: question_target set ({question_target})")
        return None

    # Gate: Skip if we already have core fields (not first turn)
    readiness = compute_trip_readiness(state.trip_inputs)
    if readiness.core_complete:
        _debug("[INITIAL_EXTRACT] MISS: core fields already complete")
        return None

    parsed: Dict[str, Any] = {}
    fields_extracted: List[str] = []

    # Try pattern 1: "I want to go to X", "trip to X", etc.
    dest_match = INITIAL_DESTINATION_PATTERN.search(text_clean)
    if dest_match:
        dest_text = dest_match.group(1).strip()
        normalized = normalize_place_synonym(dest_text)
        if is_known_place(normalized):
            parsed["destinations_delta"] = [normalized]
            fields_extracted.append("destinations")
            _debug(f"[INITIAL_EXTRACT] Pattern 1 matched: destinations={normalized}")

    # Try pattern 1b: Extract trailing "from X" when destination already found
    # Handles cases like "going to dubai from rome tomorrow"
    if parsed.get("destinations_delta") and not parsed.get("origin_delta"):
        trailing_from_match = TRAILING_ORIGIN_PATTERN.search(text_clean)
        if trailing_from_match:
            origin_text = trailing_from_match.group(1).strip()
            origin_norm = normalize_place_synonym(origin_text)
            if is_known_place(origin_norm):
                origin_final = normalize_place_with_fuzzy(origin_text)
                parsed["origin_delta"] = origin_final
                fields_extracted.append("origin")
                _debug(f"[INITIAL_EXTRACT] Pattern 1b matched: origin={origin_final}")

    # Try pattern 1c: "from X [verb] to Y" (e.g., "from dubai going to rome")
    # This must be checked BEFORE the generic "from X to Y" pattern to handle
    # travel verbs between origin and destination.
    if not parsed.get("destinations_delta"):
        from_verb_match = FROM_VERB_TO_PATTERN.search(text_clean)
        if from_verb_match:
            origin_text = from_verb_match.group(1).strip()
            dest_text = from_verb_match.group(2).strip()

            # Pre-validate locations
            if is_likely_location(origin_text) and is_likely_location(dest_text):
                origin_norm = normalize_place_synonym(origin_text)
                dest_norm = normalize_place_synonym(dest_text)

                if is_known_place(dest_norm):
                    parsed["destinations_delta"] = [dest_norm]
                    fields_extracted.append("destinations")
                    _debug(f"[INITIAL_EXTRACT] Pattern 1c matched: destinations={dest_norm}")

                if is_known_place(origin_norm):
                    origin_final = normalize_place_with_fuzzy(origin_text)
                    parsed["origin_delta"] = origin_final
                    fields_extracted.append("origin")
                    _debug(f"[INITIAL_EXTRACT] Pattern 1c matched: origin={origin_final}")

    # Try pattern 2: "from X to Y" or "X to Y"
    if not parsed.get("destinations_delta"):
        origin_dest_match = ORIGIN_DESTINATION_PATTERN.search(text_clean)
        if origin_dest_match:
            origin_text = origin_dest_match.group(1).strip()
            dest_text = origin_dest_match.group(2).strip()

            # Pre-validate: reject if extracted text is clearly not a location
            # (e.g., "I need" from "I need to book" or "book" as destination)
            if not is_likely_location(origin_text) or not is_likely_location(dest_text):
                _debug(
                    "[INITIAL_EXTRACT] Pattern 2 rejected: non-location words",
                    origin_text=origin_text,
                    dest_text=dest_text,
                )
            else:
                origin_norm = normalize_place_synonym(origin_text)
                dest_norm = normalize_place_synonym(dest_text)

                if is_known_place(dest_norm):
                    parsed["destinations_delta"] = [dest_norm]
                    fields_extracted.append("destinations")
                    _debug(f"[INITIAL_EXTRACT] Pattern 2 matched: destinations={dest_norm}")

                if origin_norm != dest_norm:
                    origin_is_known = is_known_place(origin_norm)

                    if origin_is_known:
                        # Known place - use with proper casing via fuzzy normalization
                        origin_final = normalize_place_with_fuzzy(origin_text)
                        parsed["origin_delta"] = origin_final
                        fields_extracted.append("origin")
                        _debug(f"[INITIAL_EXTRACT] Pattern 2 matched: origin={origin_final}")
                    else:
                        # For unknown origins, require explicit "from X" pattern
                        # This prevents false positives from generic "X to Y" matches
                        has_explicit_from = bool(
                            re.search(
                                rf"\bfrom\s+{re.escape(origin_text)}\b",
                                text_clean,
                                re.IGNORECASE,
                            )
                        )
                        if not has_explicit_from:
                            _debug(
                                "[INITIAL_EXTRACT] Pattern 2 skipped unknown origin "
                                f"without 'from': {origin_text}"
                            )
                        else:
                            # Unknown place with explicit "from X" - validate via LLM
                            from app.planner.nodes.extractor import _validate_origin_extraction

                            validated_origin, metadata_updates = _validate_origin_extraction(
                                text_clean,
                                origin_norm.title(),
                                is_known=False,
                            )

                            # Only accept if validation returned a value
                            if validated_origin:
                                parsed["origin_delta"] = validated_origin
                                fields_extracted.append("origin")

                                # Propagate any clarification metadata
                                if metadata_updates:
                                    parsed["_origin_metadata"] = metadata_updates

                                _debug(
                                    "[INITIAL_EXTRACT] Pattern 2 matched (verified): "
                                    f"origin={validated_origin}",
                                    metadata=metadata_updates if metadata_updates else None,
                                )
                            else:
                                _debug(
                                    "[INITIAL_EXTRACT] Pattern 2 origin validation failed",
                                    attempted=origin_norm,
                                    metadata=metadata_updates,
                                )

    # Try "based in" origin pattern (Pattern 2b)
    # Note: For explicit "based in X" patterns, we're lenient about is_known_place
    # since the user is explicitly stating their origin location
    if not parsed.get("origin_delta"):
        origin_location_match = ORIGIN_LOCATION_PATTERN.search(text_clean)
        if origin_location_match:
            origin_text = origin_location_match.group(1).strip()

            # Extract city from "city country" patterns (e.g., "Torun Poland" -> "Torun")
            # This prevents fuzzy matching from mangling "Torun Poland" to just "Poland"
            origin_text = extract_city_from_location(origin_text)

            origin_norm = normalize_place_synonym(origin_text)

            # Check if it's a known place (exact or synonym match)
            if is_known_place(origin_norm):
                # Use fuzzy normalizer to get proper casing (e.g., "new york" -> "New York")
                origin_norm = normalize_place_with_fuzzy(origin_text)
                parsed["origin_delta"] = origin_norm
                fields_extracted.append("origin")
                _debug(f"[INITIAL_EXTRACT] Pattern 2b matched: origin={origin_norm}")
            else:
                # Accept anyway - user explicitly said "based in X"
                # Use Title Case for proper formatting, but don't fuzzy match
                # (fuzzy matching might mangle unknown places)
                parsed["origin_delta"] = origin_norm.title()
                fields_extracted.append("origin")
                _debug(
                    f"[INITIAL_EXTRACT] Pattern 2b matched (unverified): "
                    f"origin={origin_norm.title()}"
                )

    # Try pattern 3: Multi-field comma-separated input
    multi_match = MULTI_FIELD_PATTERN.match(text_clean)
    if multi_match:
        # Extract travelers
        travelers_str = multi_match.group(1)
        if travelers_str and not parsed.get("adults_delta"):
            parsed["adults_delta"] = int(travelers_str)
            fields_extracted.append("travelers")
            _debug(f"[INITIAL_EXTRACT] Pattern 3 matched: adults={travelers_str}")

        # Extract destination (if not already found)
        place_str = multi_match.group(2)
        if place_str and not parsed.get("destinations_delta"):
            normalized = normalize_place_synonym(place_str.strip())
            if is_known_place(normalized):
                parsed["destinations_delta"] = [normalized]
                fields_extracted.append("destinations")
                _debug(f"[INITIAL_EXTRACT] Pattern 3 matched: destinations={normalized}")

        # Extract date hint
        date_str = multi_match.group(3)
        if date_str:
            iso_date = _date_normalizer.normalize(date_str)
            if iso_date:
                parsed["start_date_hint"] = iso_date
                fields_extracted.append("dates")
                _debug(f"[INITIAL_EXTRACT] Pattern 3 matched: dates={iso_date}")

    # Try bare city name (single word or two words that's a known place)
    if not parsed.get("destinations_delta"):
        # Check if the entire input (or first significant part) is a known place
        words = text_clean.split()
        for i in range(min(3, len(words)), 0, -1):
            candidate = " ".join(words[:i])
            # Remove trailing punctuation
            candidate = candidate.rstrip(".,!?")
            normalized = normalize_place_synonym(candidate)
            if is_known_place(normalized):
                parsed["destinations_delta"] = [normalized]
                fields_extracted.append("destinations")
                _debug(f"[INITIAL_EXTRACT] Bare city matched: destinations={normalized}")
                break

    # Try inline traveler extraction (Pattern 4: travelers within sentences)
    text_lower = text_clean.lower()
    if not parsed.get("adults_delta"):
        inline_match = INLINE_TRAVELERS_PATTERN.search(text_lower)
        if inline_match:
            # Check which group matched to determine count
            groups = inline_match.groups()

            # Check for solo/alone patterns (no groups captured = solo)
            full_match = inline_match.group(0).strip()
            solo_indicators = ["solo", "alone", "by myself", "just me", "just myself", "on my own"]
            couple_indicators = [
                "partner and i",
                "i and my partner",
                "spouse and i",
                "husband and i",
                "wife and i",
                "two of us",
                "as a couple",
                "boyfriend and i",
                "girlfriend and i",
            ]

            if any(ind in full_match for ind in solo_indicators):
                parsed["adults_delta"] = 1
                fields_extracted.append("travelers")
                _debug("[INITIAL_EXTRACT] Pattern 4: solo traveler detected (adults=1)")
            elif any(ind in full_match for ind in couple_indicators):
                parsed["adults_delta"] = 2
                fields_extracted.append("travelers")
                _debug("[INITIAL_EXTRACT] Pattern 4: couple detected (adults=2)")
            else:
                # Check for numeric captures
                for g in groups:
                    if g and g.isdigit():
                        parsed["adults_delta"] = int(g)
                        fields_extracted.append("travelers")
                        _debug(
                            f"[INITIAL_EXTRACT] Pattern 4: numeric travelers detected (adults={g})"
                        )
                        break

    # Try family composition pattern (Pattern 5: "family of 4", "2 adults and 2 kids")
    family_match = FAMILY_COMPOSITION_PATTERN.search(text_lower)
    if family_match:
        groups = family_match.groups()

        # Helper to convert word numbers to int
        def _word_to_int(val: str) -> int:
            word_map = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
            if val.isdigit():
                return int(val)
            return word_map.get(val.lower(), 0)

        # Group 0: "family of N" - total family count
        if groups[0]:
            total = int(groups[0])
            if not parsed.get("adults_delta"):
                # Assume at least 2 adults if family of 4+, otherwise 1
                parsed["adults_delta"] = min(2, total) if total >= 2 else 1
                fields_extracted.append("travelers")
                debug_msg = (
                    f"[INITIAL_EXTRACT] Pattern 5: family of {total} "
                    f"(adults={parsed['adults_delta']})"
                )
                _debug(debug_msg)
            if total > 2:
                # Assume remaining are children
                parsed["children_delta"] = total - parsed.get("adults_delta", 2)
                if "children" not in fields_extracted:
                    fields_extracted.append("children")
                _debug(f"[INITIAL_EXTRACT] Pattern 5: inferred children={parsed['children_delta']}")
        # Groups 1-2: "N adults and N kids"
        elif groups[1] and groups[2]:
            if not parsed.get("adults_delta"):
                parsed["adults_delta"] = int(groups[1])
                fields_extracted.append("travelers")
                _debug(f"[INITIAL_EXTRACT] Pattern 5: explicit adults={groups[1]}")
            parsed["children_delta"] = int(groups[2])
            if "children" not in fields_extracted:
                fields_extracted.append("children")
            _debug(f"[INITIAL_EXTRACT] Pattern 5: explicit children={groups[2]}")
        # Group 3: "me and my N kids"
        elif groups[3]:
            kids_count = int(groups[3])
            parsed["children_delta"] = kids_count
            if "children" not in fields_extracted:
                fields_extracted.append("children")
            _debug(f"[INITIAL_EXTRACT] Pattern 5: me and my {kids_count} kids")
            if not parsed.get("adults_delta"):
                parsed["adults_delta"] = 1
                fields_extracted.append("travelers")
        # Group 4: "have N kids with us" / "with N kids" (can be words)
        elif groups[4]:
            kids_count = _word_to_int(groups[4])
            if kids_count > 0:
                parsed["children_delta"] = kids_count
                if "children" not in fields_extracted:
                    fields_extracted.append("children")
                _debug(f"[INITIAL_EXTRACT] Pattern 5: have/with {kids_count} kids")
                if not parsed.get("adults_delta"):
                    parsed["adults_delta"] = 1
                    fields_extracted.append("travelers")
        # Group 5: "N kids with us" (can be words)
        elif groups[5]:
            kids_count = _word_to_int(groups[5])
            if kids_count > 0:
                parsed["children_delta"] = kids_count
                if "children" not in fields_extracted:
                    fields_extracted.append("children")
                _debug(f"[INITIAL_EXTRACT] Pattern 5: {kids_count} kids with us")
                if not parsed.get("adults_delta"):
                    parsed["adults_delta"] = 1
                    fields_extracted.append("travelers")
        # Group 6: "traveling with kids" (implies children, count unknown - default 1)
        elif len(groups) > 6 and groups[6]:
            if not parsed.get("children_delta"):
                parsed["children_delta"] = 1  # At least 1 child
                if "children" not in fields_extracted:
                    fields_extracted.append("children")
                _debug("[INITIAL_EXTRACT] Pattern 5: traveling with kids (inferred children=1)")
            if not parsed.get("adults_delta"):
                parsed["adults_delta"] = 1
                fields_extracted.append("travelers")
        # Group 7: "for the kids" / "our kids" (implies children)
        elif len(groups) > 7 and groups[7]:
            if not parsed.get("children_delta"):
                parsed["children_delta"] = 1  # At least 1 child
                if "children" not in fields_extracted:
                    fields_extracted.append("children")
                _debug("[INITIAL_EXTRACT] Pattern 5: for/with the kids (inferred children=1)")
            if not parsed.get("adults_delta"):
                parsed["adults_delta"] = 1
                fields_extracted.append("travelers")
        # Group 8: "family trip" (implies at least 1 adult + children)
        elif len(groups) > 8 and groups[8]:
            if not parsed.get("adults_delta"):
                parsed["adults_delta"] = 2  # Assume 2 adults for family trip
                fields_extracted.append("travelers")
            if not parsed.get("children_delta"):
                parsed["children_delta"] = 1  # At least 1 child for family
                if "children" not in fields_extracted:
                    fields_extracted.append("children")
                _debug("[INITIAL_EXTRACT] Pattern 5: family trip (inferred adults=2, children=1)")

    # Try inline budget pattern (Pattern 6: "budget of $2000", "spending around 5k")
    budget_match = INLINE_BUDGET_PATTERN.search(text_lower)
    if budget_match and not parsed.get("budget_delta"):
        groups = budget_match.groups()
        # Find the first non-None group
        for g in groups:
            if g:
                # Parse the budget value
                budget_str = g.replace(",", "").strip()
                if budget_str.lower().endswith("k"):
                    budget_value = int(float(budget_str[:-1]) * 1000)
                else:
                    budget_value = int(float(budget_str))
                parsed["budget_delta"] = budget_value
                fields_extracted.append("budget")
                _debug(f"[INITIAL_EXTRACT] Pattern 6: budget={budget_value}")
                break

    # Try qualitative budget phrases (Pattern 6b: "limited budget", "cheap trip")
    if not parsed.get("budget_delta"):
        for phrase, estimate in BUDGET_TIER_ESTIMATES.items():
            if phrase in text_lower:
                parsed["budget_delta"] = estimate
                fields_extracted.append("budget")
                _debug(f"[INITIAL_EXTRACT] Pattern 6b: qualitative '{phrase}' -> budget={estimate}")
                break

    # Try inline date extraction (Pattern 7: "tomorrow", "today", "next week", etc.)
    if not parsed.get("start_date_hint"):
        date_patterns = [
            r"\btomorrow\b",
            r"\btoday\b",
            r"\bnext\s+(?:week|month|weekend)\b",
            r"\bthis\s+(?:week|weekend)\b",
            r"\bon\s+((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2}(?:st|nd|rd|th)?)\b",
            r"\b((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2}(?:st|nd|rd|th)?)\b",
        ]
        for pattern in date_patterns:
            date_match = re.search(pattern, text_lower)
            if date_match:
                date_str = date_match.group(0).strip()
                # Remove "on " prefix if present
                if date_str.startswith("on "):
                    date_str = date_str[3:]
                iso_date = _date_normalizer.normalize(date_str)
                if iso_date:
                    parsed["start_date_hint"] = iso_date
                    fields_extracted.append("dates")
                    _debug(f"[INITIAL_EXTRACT] Pattern 7: inline date={date_str} -> {iso_date}")
                    break

    # Try duration extraction (Pattern 8: "10 days", "for a week")
    if not parsed.get("duration_delta"):
        duration_match = INLINE_DURATION_PATTERN.search(text_lower)
        if duration_match:
            num_str = duration_match.group(1)
            unit = duration_match.group(2).lower()

            # Convert word to number if needed
            if num_str.isdigit():
                num = int(num_str)
            else:
                num = WORD_TO_NUMBER.get(num_str.lower(), 0)

            if num > 0:
                # Convert to days
                if "week" in unit:
                    num *= 7
                parsed["duration_delta"] = num
                fields_extracted.append("duration")
                _debug(f"[INITIAL_EXTRACT] Pattern 8: duration={num} days")

    # Try extracting flight settings from the message
    flight_settings: Dict[str, Any] = {}

    # One-way flight detection
    if "one-way" in text_lower or "one way" in text_lower or "oneway" in text_lower:
        flight_settings["round_trip"] = False
        _debug("[INITIAL_EXTRACT] Flight setting: round_trip=False (one-way)")

    # Direct/nonstop flight
    if "direct" in text_lower or "nonstop" in text_lower or "non-stop" in text_lower:
        flight_settings["direct_only"] = True
        _debug("[INITIAL_EXTRACT] Flight setting: direct_only=True")

    # Cabin class
    if "business class" in text_lower or "business-class" in text_lower:
        flight_settings["cabin_class"] = "business"
        _debug("[INITIAL_EXTRACT] Flight setting: cabin_class=business")
    elif "first class" in text_lower or "first-class" in text_lower:
        flight_settings["cabin_class"] = "first"
        _debug("[INITIAL_EXTRACT] Flight setting: cabin_class=first")

    if flight_settings:
        parsed["flight_settings_delta"] = flight_settings
        fields_extracted.append("flight_settings")

    # Return result if we extracted at least one field
    if fields_extracted:
        _debug(
            f"[INITIAL_EXTRACT] HIT: extracted {len(fields_extracted)} fields",
            fields=fields_extracted,
            parsed=parsed,
        )
        return {
            "type": "initial_extraction",
            "fields": fields_extracted,
            "parsed": parsed,
        }

    _debug(f"[INITIAL_EXTRACT] MISS: no patterns matched for '{text_clean[:50]}'")
    return None


def _debug_length_audit(
    context: str,
    text: str,
    threshold: int,
    decision: str,
) -> None:
    """
    Log structured length measurement data for short-circuit auditing.

    Format: [LENGTH_AUDIT] context="..." len=X threshold=Y decision=PASS/FAIL

    Args:
        context: Description of where the measurement is happening.
        text: The text being measured (will be shown truncated).
        threshold: The threshold value being compared against.
        decision: PASS (under threshold) or FAIL (over threshold).
    """
    if not _DEBUG_LOG:
        return
    actual_len = len(text)
    truncated = text[:30] + "..." if len(text) > 30 else text
    print(
        f'[LENGTH_AUDIT] context="{context}" '
        f'input="{truncated}" '
        f"len={actual_len} threshold={threshold} decision={decision}"
    )


def _debug_short_circuit_decision(
    input_text: str,
    detected_type: Optional[str],
    last_field: Optional[str],
    decision: str,
    reason: Optional[str] = None,
    parsed_data: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Log structured observability data for short-circuit decisions.

    Format: [SHORT_CIRCUIT] input="..." type=... last_field=... decision=... reason=...

    Args:
        input_text: The raw user input (truncated for logging).
        detected_type: The short-circuit type detected (or None if bypassed).
        last_field: The last_question_field from previous turn.
        decision: TRIGGERED, BYPASSED, or PATTERN_MISS.
        reason: Optional explanation for the decision.
        parsed_data: Optional parsed data extracted from the input.
    """
    truncated = input_text[:30] + "..." if len(input_text) > 30 else input_text
    parts = [
        f'[SHORT_CIRCUIT] input="{truncated}"',
        f"type={detected_type or 'none'}",
        f"last_field={last_field or 'none'}",
        f"decision={decision}",
    ]
    if reason:
        parts.append(f"reason={reason}")
    if parsed_data:
        parts.append(f"parsed={parsed_data}")
    _debug(" ".join(parts))


# =============================================================================
# DETERMINISTIC INFEASIBILITY DETECTION (Phase 5)
# =============================================================================
# Detect obvious infeasibility signals without LLM - route directly to correction.
# This saves ~1000 tokens by avoiding router LLM when correction is clearly needed.
#
# NOTE: INFEASIBILITY_SIGNALS patterns are now imported from pattern_matching module.

# Local alias for backward compatibility
_INFEASIBILITY_SIGNALS = INFEASIBILITY_SIGNALS


def _has_infeasibility_signals(text: str, state: "GraphState") -> tuple[bool, str | None]:
    """
    Detect deterministic infeasibility signals in user text.

    This function checks for patterns that clearly indicate the user is
    reporting an infeasibility or requesting a correction, allowing us
    to route directly to correction_node without invoking router LLM.

    Args:
        text: User input text
        state: Current graph state (for context like current dates/destinations)

    Returns:
        (has_signal, signal_type) - tuple of whether signal detected and which type
    """
    text_lower = text.lower()

    # Check each infeasibility pattern
    for signal_type, pattern in _INFEASIBILITY_SIGNALS.items():
        if pattern.search(text_lower):
            _debug(
                "🔧 INFEASIBILITY_SIGNAL detected",
                signal_type=signal_type,
                text_preview=text[:50],
            )
            return True, signal_type

    # Check if start_date is in the past (deterministic check)
    ti = state.trip_inputs
    if ti.start_date:
        try:
            start = datetime.fromisoformat(ti.start_date).date()
            today = date.today()
            if start < today:
                _debug(
                    "🔧 INFEASIBILITY_SIGNAL: start_date in past",
                    start_date=ti.start_date,
                    today=str(today),
                )
                return True, "dates_in_past"
        except (ValueError, TypeError):
            pass

    return False, None


def _detect_short_circuit(text: str, state: "GraphState") -> Optional[Dict[str, Any]]:
    """
    Detect if user input can be short-circuited without LLM calls.

    Returns a dict with:
        - type: str - the short-circuit type (greeting, acknowledgment, etc.)
        - response: Optional[str] - a template response, or None to use default follow-up
        - action: Optional[str] - an action to execute (for confirmations)
        - parsed: Optional[Dict] - extracted data to merge (for bare field inputs)

    Returns None if the input should go through the normal LLM pipeline.
    """
    text_clean = text.strip()
    last_field = state.metadata.get("last_question_field")

    # Audit: log actual length measurement for observability
    _debug_length_audit(
        context="short_circuit_entry",
        text=text_clean,
        threshold=settings.short_circuit_max_length,
        decision="FAIL" if len(text_clean) > settings.short_circuit_max_length else "PASS",
    )

    # Skip short-circuit if there's substantial content (configurable, default 200 chars)
    if len(text_clean) > settings.short_circuit_max_length:
        _debug_short_circuit_decision(text, None, last_field, "BYPASSED", reason="input_too_long")
        return None

    # 1. Greetings
    if GREETING_PATTERN.match(text_clean):
        _debug_short_circuit_decision(text, "greeting", last_field, "TRIGGERED")
        return {
            "type": "greeting",
            "response": _random_module.choice(_GREETING_RESPONSES),
            "action": None,
            "parsed": None,
        }

    # 1.5. Explicit generate request detection (regardless of pending_action)
    # This catches phrases like "Yes, generate my itinerary!", "I'm ready", etc.
    # Only trigger if plan is ready (core fields complete)
    if GENERATE_REQUEST_PATTERN.search(text_clean):
        # Check if plan is ready (core fields complete)
        ti = state.trip_inputs
        ti_dict = ti.model_dump(exclude_none=True) if hasattr(ti, "model_dump") else ti
        readiness = compute_trip_readiness(ti_dict)
        if readiness.core_complete:
            _debug_short_circuit_decision(
                text,
                "generate_request",
                last_field,
                "TRIGGERED",
                reason="explicit_generate_pattern",
            )
            return {
                "type": "generate_request",
                "response": None,
                "action": "generate_plan",
                "parsed": None,
                "user_request_type": "generate",
            }
        else:
            _debug_short_circuit_decision(
                text,
                "generate_request",
                last_field,
                "BYPASSED",
                reason=f"core_incomplete:missing={readiness.missing_core}",
            )

    pending = state.metadata.get("pending_action")

    # 2. Pending-action confirmations should be evaluated BEFORE acknowledgments
    # so ambiguous tokens like "sure" or "sounds good" act as a real confirm/deny.
    if pending and YES_PATTERN.match(text_clean):
        pending = state.metadata.get("pending_action")
        if pending == "generate_plan":
            # Execute the pending action
            _debug_short_circuit_decision(
                text, "confirmation_yes", last_field, "TRIGGERED", reason=f"pending={pending}"
            )
            return {
                "type": "confirmation_yes",
                "response": None,
                "action": "generate_plan",
                "parsed": None,
            }
        if pending == "confirm_typo":
            # Apply the typo corrections stored in metadata
            typo_corrections = state.metadata.get("pending_typo_corrections", {})
            _debug_short_circuit_decision(
                text,
                "confirm_typo",
                last_field,
                "TRIGGERED",
                reason=f"pending={pending}",
                parsed_data=typo_corrections,
            )
            return {
                "type": "confirm_typo",
                "response": None,
                "action": "apply_typo_corrections",
                "parsed": {"typo_corrections": typo_corrections},
            }
        # Generic yes without pending action - just acknowledge and continue
        _debug_short_circuit_decision(text, "confirmation_yes", last_field, "TRIGGERED")
        return {
            "type": "confirmation_yes",
            "response": None,
            "action": None,
            "parsed": None,
        }

    if pending and NO_PATTERN.match(text_clean):
        pending = state.metadata.get("pending_action")
        if pending:
            # Clear the pending action
            _debug_short_circuit_decision(
                text, "confirmation_no", last_field, "TRIGGERED", reason=f"pending={pending}"
            )
            return {
                "type": "confirmation_no",
                "response": "Cancelled. Next action:",
                "action": "clear_pending",
                "parsed": None,
            }
        _debug_short_circuit_decision(text, "confirmation_no", last_field, "TRIGGERED")
        return {
            "type": "confirmation_no",
            "response": None,
            "action": None,
            "parsed": None,
        }

    # 3. Acknowledgments - REMOVED: Now handled by LLM extractor for better context awareness

    # 4. Simple confirmations (yes, yeah)
    if YES_PATTERN.match(text_clean):
        pending = state.metadata.get("pending_action")
        if pending == "generate_plan":
            # Execute the pending action
            _debug_short_circuit_decision(
                text, "confirmation_yes", last_field, "TRIGGERED", reason=f"pending={pending}"
            )
            return {
                "type": "confirmation_yes",
                "response": None,
                "action": "generate_plan",
                "parsed": None,
            }
        # Generic yes without pending action - just acknowledge and continue
        return {
            "type": "confirmation_yes",
            "response": None,
            "action": None,
            "parsed": None,
        }

    # 5. Simple negations (no, nope)
    if NO_PATTERN.match(text_clean):
        pending = state.metadata.get("pending_action")
        if pending:
            # Clear the pending action
            return {
                "type": "confirmation_no",
                "response": "Cancelled. Next action:",
                "action": "clear_pending",
                "parsed": None,
            }
        return {
            "type": "confirmation_no",
            "response": None,
            "action": None,
            "parsed": None,
        }

    # 5a. Booking type add pattern (e.g., "Add hotels", "Include flights")
    # Must come BEFORE field_request to intercept these commands and enable booking_types
    # instead of falling through to the "Missing constraint." fallback
    BOOKING_ADD_KEYWORDS = {"hotel", "hotels", "flight", "flights", "activity", "activities"}
    text_clean_lower = text_clean.lower()
    words = set(text_clean_lower.split())
    # Check if this is an "add X" pattern for booking types
    if words & {"add", "include", "yes"} and words & BOOKING_ADD_KEYWORDS:
        # Map to booking_type key
        booking_key = None
        if words & {"hotel", "hotels"}:
            booking_key = "hotels"
        elif words & {"flight", "flights"}:
            booking_key = "flights"
        elif words & {"activity", "activities"}:
            booking_key = "activities"

        if booking_key:
            _debug_short_circuit_decision(
                text,
                "booking_type_add",
                last_field,
                "TRIGGERED",
                reason=f"booking_type_add:{booking_key}",
            )
            # Human-friendly confirmation
            confirmations = {
                "hotels": "Got it, I'll include hotel options.",
                "flights": "Got it, I'll include flight options.",
                "activities": "Got it, I'll include activity options.",
            }
            return {
                "type": "booking_type_add",
                "response": confirmations[booking_key],
                "action": None,
                "parsed": {"booking_types": {booking_key: True}},
                "field_target": None,
            }

    # 5b. Field request pattern (e.g., "Set budget", "budget?", "add budget")
    # GUARD: Skip if text contains digits/currency - let normal extraction handle values
    if not HAS_VALUE_PATTERN.search(text_clean):
        field_match = FIELD_REQUEST_PATTERN.match(text_clean)
        if field_match:
            matched_field = field_match.group(1).lower()
            target_field = FIELD_REQUEST_TARGET_MAP.get(matched_field)
            if target_field:
                _debug_short_circuit_decision(
                    text,
                    "field_request",
                    last_field,
                    "TRIGGERED",
                    reason=f"field_request:{target_field}",
                )
                return {
                    "type": "field_request",
                    "response": None,
                    "action": "ask_field",
                    "parsed": None,
                    "field_target": target_field,
                }

    # 6-10. Off-topic, bare inputs - REMOVED: Now handled by LLM for better accuracy
    # Off-topic detection moved to router node with off_topic intent
    # Bare destination/date/travelers/origin detection removed - too brittle

    # -------------------------------------------------------------------------
    # V36: FIELD-SPECIFIC SHORT-CIRCUIT SAFETY NET
    # -------------------------------------------------------------------------
    # When last_question_field is set, check if input matches field-specific
    # patterns. This provides a safety net for suggestion clicks and simple
    # answers that the LQA prepass might miss.

    # 6a. Budget field safety net
    if last_field == "budget":
        text_lower = text_clean.lower()
        # Check flexible budget phrases (no limit, flexible, skip, etc.)
        for phrase in NO_BUDGET_PHRASES:
            if phrase in text_lower or text_lower == phrase:
                _debug_short_circuit_decision(
                    text,
                    "field_answer",
                    last_field,
                    "TRIGGERED",
                    reason=f"budget_flexible:{phrase}",
                )
                return {
                    "type": "field_answer",
                    "response": None,
                    "action": None,
                    "parsed": {
                        "budget_answered": True,
                        "lqa_reason": "short_circuit:budget_flexible",
                    },
                }
        # Check budget pattern (amounts like "$2000", "2k", etc.)
        budget_match = BUDGET_PATTERN.match(text_clean)
        if budget_match:
            amount_str = budget_match.group(1)
            try:
                if amount_str.lower().endswith("k"):
                    amount = float(amount_str[:-1]) * 1000
                elif "thousand" in amount_str.lower():
                    amount = float(amount_str.lower().replace("thousand", "").strip()) * 1000
                else:
                    amount = float(amount_str.replace(",", ""))
                _debug_short_circuit_decision(
                    text, "field_answer", last_field, "TRIGGERED", reason=f"budget_amount:{amount}"
                )
                return {
                    "type": "field_answer",
                    "response": None,
                    "action": None,
                    "parsed": {"budget_delta": amount, "lqa_reason": "short_circuit:budget_amount"},
                }
            except (ValueError, TypeError):
                pass

    # 6b. Travelers field safety net
    if last_field == "travelers":
        travelers_match = TRAVELERS_PATTERN.match(text_clean)
        if travelers_match:
            # Extract adults count from match groups
            adults = 1  # default
            if travelers_match.group(1):  # "N adults/people"
                adults = int(travelers_match.group(1))
            elif travelers_match.group(2):  # "family of N" / "group of N"
                adults = int(travelers_match.group(2))
            elif travelers_match.group(3):  # "N of us"
                adults = int(travelers_match.group(3))
            elif "just me" in text_clean.lower() or "solo" in text_clean.lower():
                adults = 1
            elif "couple" in text_clean.lower():
                adults = 2
            _debug_short_circuit_decision(
                text,
                "field_answer",
                last_field,
                "TRIGGERED",
                reason=f"travelers_pattern:adults={adults}",
            )
            return {
                "type": "field_answer",
                "response": None,
                "action": None,
                "parsed": {"adults_delta": adults, "lqa_reason": "short_circuit:travelers"},
            }

    # 6c. Dates field safety net - handled by LQA prepass, not duplicated here
    # Date parsing is complex (relative dates, ISO dates, etc.) and is already
    # well-handled by _parse_date_answer in LQA prepass.

    # No short-circuit detected - let LLM handle it
    _debug_short_circuit_decision(
        text, None, last_field, "PATTERN_MISS", reason="no_pattern_matched"
    )
    return None


# =============================================================================
# DOCUMENT SERIALIZATION FOR LLM CONTEXT (ported from plan.py)
# =============================================================================


def _serialize_branches_for_llm(
    branches: List[Dict[str, Any]], tiles: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    Serialize branches and tiles for LLM context.

    This function converts the branches and tiles into a text format that
    the LLM can understand when refining existing plans.

    Args:
        branches: List of branch dictionaries.
        tiles: Optional dict of tile_id -> tile info.

    Returns:
        Optional[str]: A formatted text representation of branches/tiles,
                       or None if no branches exist.
    """
    if not branches:
        return None

    lines: List[str] = []

    # Branches with their info
    lines.append(f"=== EXISTING BRANCHES ({len(branches)}) ===")
    for idx, branch in enumerate(branches):
        primary_marker = " (PRIMARY)" if idx == 0 else ""
        lines.append(f"\nBranch: {branch.get('label', 'Unnamed')}{primary_marker}")
        lines.append(f"  ID: {branch.get('id', 'unknown')}")
        if branch.get("description"):
            lines.append(f"  Description: {branch['description']}")
        if branch.get("destinations"):
            dests = branch["destinations"]
            if isinstance(dests, list):
                lines.append(f"  Destinations: {', '.join(dests)}")
            else:
                lines.append(f"  Destinations: {dests}")
        if branch.get("origin"):
            lines.append(f"  Origin: {branch['origin']}")
        if branch.get("start_date"):
            lines.append(f"  Dates: {branch['start_date']} to {branch.get('end_date', 'TBD')}")
        traveler_parts = []
        if branch.get("adults"):
            traveler_parts.append(f"{branch['adults']} adult(s)")
        if branch.get("children"):
            traveler_parts.append(f"{branch['children']} child(ren)")
        if traveler_parts:
            lines.append(f"  Travelers: {', '.join(traveler_parts)}")
        if branch.get("requires_assistance"):
            lines.append("  Requires assistance: Yes")
        if branch.get("budget") is not None:
            currency = branch.get("currency", "USD")
            lines.append(f"  Budget: {branch['budget']} {currency}")

    # Available tiles (abbreviated) if provided
    if tiles:
        lines.append(f"\n=== AVAILABLE TILES ({len(tiles)}) ===")
        by_type: Dict[str, List[str]] = {"flight": [], "hotel": [], "activity": []}
        for _tile_id, tile in tiles.items():
            if isinstance(tile, dict):
                tile_type = tile.get("type", "activity")
                title = tile.get("title", "Unknown")
                price_info = ""
                if tile.get("live_price") is not None:
                    price_info = f" ({tile['live_price']} {tile.get('currency', '')})"
                elif tile.get("price_estimate") is not None:
                    price_info = f" (~{tile['price_estimate']} {tile.get('currency', '')})"
                by_type.setdefault(tile_type, []).append(f"{title}{price_info}")
        for tile_type, tile_list in by_type.items():
            if tile_list:
                lines.append(f"{tile_type.upper()}S: {', '.join(tile_list[:5])}")
                if len(tile_list) > 5:
                    lines.append(f"  ... and {len(tile_list) - 5} more")

    return "\n".join(lines)


# =============================================================================
# DATE UTILITY FUNCTIONS (ported from plan.py)
# =============================================================================


def _today_iso(timezone_name: Optional[str] = None) -> str:
    """Backward-compatible wrapper - delegates to node_utils.today_iso."""
    return _today_iso_impl(timezone_name)


# =============================================================================
# INPUT NORMALIZATION FUNCTIONS (ported from plan.py)
# =============================================================================
# Tier 3: _normalize_str extracted to app/planner/normalization/date.py
# Imported at module level as: from app.planner.normalization import normalize_str as _normalize_str


def _deduplicate_destinations(destinations: List[str]) -> List[str]:
    """
    Deduplicate destinations by removing sublocations when parent location exists.

    Examples:
    - ["Paris", "Marais district"] → ["Paris"] (Marais is in Paris)
    - ["Tokyo", "Shibuya"] → ["Tokyo"] (Shibuya is in Tokyo)
    - ["Italy", "Rome", "Florence"] → ["Italy"] or keep all if multi-city

    Also removes exact duplicates case-insensitively.
    """
    if not destinations or len(destinations) <= 1:
        return destinations

    # Known city-district relationships
    known_sublocations = {
        "marais": "paris",
        "marais district": "paris",
        "le marais": "paris",
        "montmartre": "paris",
        "latin quarter": "paris",
        "shibuya": "tokyo",
        "shinjuku": "tokyo",
        "ginza": "tokyo",
        "manhattan": "new york",
        "brooklyn": "new york",
        "soho": "london",
        "westminster": "london",
        "trastevere": "rome",
        "vatican": "rome",
        "kreuzberg": "berlin",
        "mitte": "berlin",
    }

    result = []
    seen_lower = set()
    parent_cities = set()

    # First pass: identify parent cities
    for dest in destinations:
        dest_lower = dest.lower().strip()
        # Check if this is a known parent city
        for _subloc, parent in known_sublocations.items():
            if parent == dest_lower:
                parent_cities.add(parent)

    # Second pass: filter out sublocations if parent exists
    for dest in destinations:
        dest_lower = dest.lower().strip()

        # Skip exact duplicates
        if dest_lower in seen_lower:
            continue

        # Skip sublocations if parent city is present
        if dest_lower in known_sublocations:
            parent = known_sublocations[dest_lower]
            if parent in parent_cities or any(parent in d.lower() for d in destinations):
                continue

        seen_lower.add(dest_lower)
        result.append(dest)

    return result if result else destinations  # Never return empty list


# =============================================================================
# DATE PROVENANCE AND NORMALIZER (Tier 3 Extraction)
# =============================================================================
# Extracted to app/planner/normalization/date.py
# Imported at module level: DateNormalizer, DateProvenance
#
# Usage:
#     from app.planner.normalization import DateNormalizer, DateProvenance
#     normalizer = DateNormalizer()
#     iso_date = normalizer.normalize("next week")
#
# =============================================================================


# NOTE: DateNormalizer class (~580 lines) has been extracted to
# app/planner/normalization/date.py and is imported at module level.
# The class includes: relative_to_iso, normalize, normalize_with_info,
# normalize_with_provenance, parse_iso, find_date_in_text, parse_date_range,
# parse_date_range_with_ambiguity, compute_end_from_duration, is_valid_range


# The factory functions below create DateNormalizer instances from the imported class.


# Singleton instance for default usage (legacy - prefer get_turn_date_normalizer)
_date_normalizer = DateNormalizer()


def get_turn_date_normalizer(state: Optional["GraphState"] = None) -> DateNormalizer:
    """
    Get a DateNormalizer scoped to the current turn's reference date.

    The reference date is the "today" used for parsing relative dates like
    "next week" or "tomorrow". It should be stable within a turn but set
    fresh at the start of each turn.

    Priority:
    1. state.metadata["turn_reference_date"] if set (ISO format string)
    2. state.metadata["today_iso"] if set (commonly used for testing)
    3. Current UTC date as fallback

    Args:
        state: Current graph state, or None to use current date

    Returns:
        DateNormalizer instance with the appropriate reference date
    """
    reference_date: Optional[date] = None

    if state is not None:
        metadata = state.metadata or {}

        # Priority 1: Explicit turn reference date
        turn_ref = metadata.get("turn_reference_date")
        if turn_ref:
            try:
                reference_date = datetime.strptime(turn_ref, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                pass

        # Priority 2: today_iso (used in tests)
        if reference_date is None:
            today_iso = metadata.get("today_iso")
            if today_iso:
                try:
                    reference_date = datetime.strptime(today_iso, "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    pass

    # Create normalizer with reference date (defaults to today if None)
    return DateNormalizer(reference_date=reference_date)


def get_turn_trip_normalizer(state: Optional["GraphState"] = None) -> "TripInputNormalizer":
    """
    Get a TripInputNormalizer using the turn-scoped DateNormalizer.

    This ensures date parsing uses the correct reference date for the turn.

    Args:
        state: Current graph state

    Returns:
        TripInputNormalizer instance with turn-scoped date handling
    """
    date_normalizer = get_turn_date_normalizer(state)
    return TripInputNormalizer(date_normalizer=date_normalizer)


# =============================================================================
# EXTRACTION ERROR CODES (V16: Explicit error codes for extraction issues)
# =============================================================================
# These error codes are used for user-in-the-loop clarification when LQA or
# LLM extraction cannot confidently extract place information.
class ExtractionErrorCode:
    """Explicit error codes for extraction-related issues."""

    AMBIGUOUS_PLACE = "EXTRACTION_AMBIGUOUS_PLACE"  # Multiple places possible
    UNKNOWN_PLACE = "EXTRACTION_UNKNOWN_PLACE"  # Place not recognized
    TYPO_DETECTED = "EXTRACTION_TYPO_DETECTED"  # Possible typo in place name
    LOW_CONFIDENCE = "EXTRACTION_LOW_CONFIDENCE"  # LLM confidence below threshold
    PARTIAL_MATCH = "EXTRACTION_PARTIAL_MATCH"  # Partial place name match


EXTRACTION_BLOCKING_ERROR_CODES = frozenset(
    {
        ExtractionErrorCode.AMBIGUOUS_PLACE,
        ExtractionErrorCode.UNKNOWN_PLACE,
    }
)


# =============================================================================
# DATE OBSERVABILITY STATS
# NOTE: DateErrorCode and DATE_BLOCKING_ERROR_CODES imported from planner.gates.constants
# =============================================================================
_date_stats: Dict[str, int] = {
    "lqa_skip_not_date_like": 0,
    "date_ambiguous_year_count": 0,
    "date_range_invalid_count": 0,
    "dates_clarify_shown_count": 0,
    "dates_clarify_resolved_count": 0,
    "turns_in_date_clarify_mode": 0,
}


# =============================================================================
# QUESTION TARGET CANONICALIZATION
# =============================================================================
def canonicalize_question_target(target: Optional[str]) -> Optional[str]:
    """
    Canonicalize question_target to a standard value.

    This function maps field-specific targets to canonical values that LQA
    and template systems understand. It should be called:
    1. At the start of run_turn() before lqa_prepass
    2. Everywhere a question_target is set

    Date Parsing Contract:
    ----------------------
    - LQA and templates are keyed by "dates", not "start_date"/"end_date"
    - This function ensures consistent canonicalization

    Ownership Hierarchy:
    -------------------
    1. LQA pre-pass (deterministic, zero-LLM) - first attempt
    2. FULL extractor (LLM-based) - fallback, authoritative output
    3. Normalizer (validate_date_range) - invariant enforcement only, no guessing

    Clarify Mode Semantics:
    ----------------------
    - date_clarify_mode is stored in metadata, not trip_inputs
    - Set True when DATE_AMBIGUOUS_YEAR or DATE_RANGE_INVALID errors present
    - Cleared when valid ordered range stored AND no date errors remain

    Args:
        target: Raw question_target value

    Returns:
        Canonical target value, or None if target is None
    """
    if target is None:
        return None

    # Normalize to lowercase for comparison
    target_lower = target.lower().strip()

    # Map date-related targets to "dates"
    if target_lower in ("start_date", "end_date", "date", "timing", "when"):
        return "dates"

    # Map traveler-related targets to "travelers"
    if target_lower in ("travelers (adults)", "adults", "traveler", "people", "party_size"):
        return "travelers"

    # Map location-related targets
    if target_lower in ("destination", "where", "location", "place"):
        return "destinations"

    if target_lower in ("from", "departure", "home"):
        return "origin"

    # Return as-is if already canonical or unknown
    if target_lower in QUESTION_TARGET_VALUES:
        return target_lower

    # Preserve original casing for unknown values (logged as warning elsewhere)
    return target


def set_question_target(
    state: "GraphState",
    target: Optional[str],
    *,
    source: str,
) -> None:
    """
    Safe setter that canonicalizes and writes to metadata (SSoT).

    This is the ONLY place question_target should be written.
    All other writes should go through this helper.

    Also tracks active_question_id for bridge suppression - only increments
    when the question target actually CHANGES (not on re-asks of the same target).

    Args:
        state: Graph state
        target: Raw target value (will be canonicalized)
        source: Node/function name for debugging (e.g., "required_fields_node")
    """
    canonical = canonicalize_question_target(target)

    # Validate against allowed set
    if canonical and canonical not in QUESTION_TARGET_VALUES:
        _debug(
            "QUESTION_TARGET_INVALID",
            raw=target,
            canonical=canonical,
            source=source,
        )
        canonical = None

    # Track old target to detect actual question changes
    old_target = state.metadata.get("active_question_target")

    state.metadata["question_target"] = canonical
    state.metadata["question_target_source"] = source
    state.question_target = canonical  # Sync state for this turn

    # Increment active_question_id only when target CHANGES (not on re-asks)
    # This provides stable question instance tracking for bridge suppression
    if canonical and canonical != old_target:
        active_qid = state.metadata.get("active_question_id", 0) + 1
        state.metadata["active_question_id"] = active_qid
        state.metadata["active_question_target"] = canonical
        _debug(
            "Active question changed",
            old_target=old_target,
            new_target=canonical,
            active_question_id=active_qid,
            source=source,
        )


def get_question_target(state: "GraphState") -> Optional[str]:
    """
    Read canonical question_target from metadata (SSoT).

    Returns:
        Canonical question_target value, or None if not set
    """
    return canonicalize_question_target(state.metadata.get("question_target"))


# =============================================================================
# NORMALIZATION ERROR (MIGRATED to planner.normalization.types)
# =============================================================================
# Import from new module for consistency
from app.planner.normalization.types import NormalizationError  # noqa: E402

# =============================================================================
# TRIP INPUT NORMALIZER (Extracted to planner.normalization.trip_inputs)
# =============================================================================
# NOTE: TripInputNormalizer class (~890 lines) has been extracted to
# app/planner/normalization/trip_inputs.py and is imported at module level.
# The factory function below creates instances with all dependencies injected.


def _update_date_stats(key: str, amount: int = 1) -> None:
    """Callback to update _date_stats from TripInputNormalizer."""
    if key in _date_stats:
        _date_stats[key] += amount


def _create_trip_normalizer(
    date_normalizer: Optional[DateNormalizer] = None,
) -> TripInputNormalizer:
    """
    Factory function to create TripInputNormalizer with all dependencies injected.

    This bridges the extracted TripInputNormalizer class with the dependencies
    still defined in plan_graph.py.

    Args:
        date_normalizer: Optional DateNormalizer, uses global singleton if None.

    Returns:
        Configured TripInputNormalizer instance.

    Usage:
        normalizer = _create_trip_normalizer()
        updates, errors = normalizer.normalize_all(trip_inputs, deltas)
    """
    return TripInputNormalizer(
        date_normalizer=date_normalizer or _date_normalizer,
        dest_exclude_words=_DEST_EXCLUDE_WORDS,
        deduplicate_destinations_fn=_deduplicate_destinations,
        deduplicate_activities_fn=_deduplicate_activities_case_insensitive,
        normalize_place_fn=normalize_place_with_fuzzy,
        normalize_int_fn=_normalize_int,
        normalize_budget_fn=_normalize_budget,
        normalize_booking_field_fn=_normalize_booking_field,
        normalize_multi_city_fn=_normalize_multi_city_intent,
        default_currency=DEFAULT_CURRENCY,
        default_booking_types=DEFAULT_BOOKING_TYPES,
        update_stats_fn=_update_date_stats,
    )


# Legacy class alias for backward compatibility - use _create_trip_normalizer() instead
# This alias is kept for code that directly instantiates TripInputNormalizer
# but the factory function should be preferred as it injects all dependencies.


# Singleton declaration - actual initialization happens after all dependencies are defined
# (see line after _normalize_booking_field)
_trip_normalizer: TripInputNormalizer  # Forward declaration, initialized below


def _get_trip_normalizer() -> TripInputNormalizer:
    """Get the singleton TripInputNormalizer instance."""
    return _trip_normalizer


# =============================================================================
# HELPER NORMALIZATION FUNCTIONS
# =============================================================================
# These functions are used by TripInputNormalizer and other parts of the graph.
# They are kept here for backward compatibility and to avoid circular imports.


def _normalize_date(value: Any) -> Optional[str]:
    """Normalize various date formats to ISO format (YYYY-MM-DD)."""
    return _date_normalizer.normalize(value)


def _parse_iso_date(text: Optional[str]) -> Optional[datetime]:
    """Parse an ISO date string to a datetime object."""
    return _date_normalizer.parse_iso(text)


def _normalize_int(value: Any) -> Optional[int]:
    """Convert any value to an integer."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(str(value).strip())
        except Exception:
            return None


# NOTE: TripInputNormalizer class content (~890 lines) has been extracted to
# app/planner/normalization/trip_inputs.py.
# Continuing with helper functions used by TripInputNormalizer and other parts of the graph.
# --- (Orphaned TripInputNormalizer class methods removed - see trip_inputs.py) ---


def _normalize_budget(value: Any) -> Optional[float]:
    """Normalize a budget value to a float, handling currency symbols and dict format."""
    if value is None:
        return None

    # Handle dict format from LLM: {"budget": number, "currency": "USD"}
    if isinstance(value, dict):
        budget_value = value.get("budget")
        if budget_value is not None:
            return _normalize_budget(budget_value)  # Recurse to handle the inner value
        return None

    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # Remove currency symbols and commas, extract number
        cleaned = re.sub(r"[^\d.]", "", value)
        if cleaned:
            try:
                return float(cleaned)
            except ValueError:
                return None
    return None


def _normalize_currency(value: Any, *, default: Optional[str] = None) -> Optional[str]:
    """Normalize a currency value to a supported 3-letter code."""
    if value is None:
        return default

    symbol_map = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}

    text = _normalize_str(value)
    if not text:
        return default

    if text in symbol_map:
        text = symbol_map[text]

    code = text.upper()
    if code in SUPPORTED_CURRENCIES:
        return code

    return default


def _normalize_multi_city_intent(value: Any) -> Optional[str]:
    """
    Normalize multi-city intent from canonical values or natural language phrases.
    """
    if value is None:
        return None

    if isinstance(value, bool):
        return "multi_city" if value else "separate"

    text = _normalize_str(value)
    if not text:
        return None

    normalized = re.sub(r"\s+", " ", text.lower().replace("_", " ").replace("-", " ")).strip()

    # Quick exact matches
    if normalized in {
        "multi city",
        "multicity",
        "multi city trip",
        "multi city itinerary",
        "multi city intent",
    }:
        return "multi_city"
    if normalized in {
        "separate",
        "separate trip",
        "separate trips",
        "separate itinerary",
        "separate itineraries",
    }:
        return "separate"

    # Phrase-based inference using imported constants
    # Use ADDITIVE_INTENT_PATTERN from pattern_matching.py
    if ADDITIVE_INTENT_PATTERN.search(normalized):
        return "multi_city"

    if "not separate" not in normalized:
        for phrase in MULTI_CITY_SEPARATE_PHRASES:
            if phrase in normalized:
                return "separate"

    for phrase in MULTI_CITY_COMBINED_PHRASES:
        if phrase in normalized:
            return "multi_city"

    return None


def _clamp_traveler_value(value: Optional[int]) -> Optional[int]:
    """Constrain a traveler count to valid range [0, 20]."""
    if value is None:
        return None
    return max(0, min(20, value))


def _should_skip_field_update(field: str, value: Any, current_value: Any) -> bool:
    """
    Check if a field update should be skipped to avoid false change detection.

    Returns True if the new value is effectively "no change" compared to the default None.
    This prevents the frontend from showing change animations for fields that weren't
    actually modified by the user.
    """
    # Skip None values
    if value is None:
        return True

    # Skip empty strings for string fields that default to None
    if field in ("origin", "start_date", "end_date", "multi_city_intent") and value == "":
        return True

    # Skip False for boolean fields that default to None
    if field == "requires_assistance" and value is False and current_value is None:
        return True

    # Skip 0 for numeric fields that default to None (only if current is None)
    if field in ("adults", "children", "budget") and value == 0 and current_value is None:
        return True

    return False


# =============================================================================
# BOOKING AUTO-ENABLE LOGIC (ported from plan.py)
# =============================================================================


def _should_enable_booking_for_flights(flight_settings: dict | None) -> bool:
    if not flight_settings or not isinstance(flight_settings, dict):
        return False
    return (
        (
            "cabin_class" in flight_settings
            and flight_settings.get("cabin_class") != DEFAULT_FLIGHT_SETTINGS["cabin_class"]
        )
        or ("direct_only" in flight_settings and flight_settings.get("direct_only") is True)
        or (
            "round_trip" in flight_settings
            and flight_settings.get("round_trip") != DEFAULT_FLIGHT_SETTINGS["round_trip"]
        )
    )


def _should_enable_booking_for_hotels(hotel_settings: dict | None) -> bool:
    if not hotel_settings or not isinstance(hotel_settings, dict):
        return False
    min_stars = hotel_settings.get("min_stars", 0)
    if min_stars and min_stars > 0:
        return True
    amenities = hotel_settings.get("amenities") or []
    return isinstance(amenities, list) and len(amenities) > 0


def _should_enable_booking_for_activities(activity_settings: dict | None) -> bool:
    if not activity_settings or not isinstance(activity_settings, dict):
        return False
    categories = activity_settings.get("categories") or []
    return isinstance(categories, list) and len(categories) > 0


def _should_enable_booking_for_transport(transport_settings: dict | None) -> bool:
    if not transport_settings or not isinstance(transport_settings, dict):
        return False
    return any(transport_settings.get(key) is True for key in ("car", "train", "bus"))


def _is_booking_enabled(state: str | bool | None) -> bool:
    """Check if a booking type state is enabled (suggested or on).

    Tri-state model:
    - 'off' / False / None -> disabled
    - 'suggested' / 'on' / True -> enabled
    """
    if state is None:
        return False
    # Handle legacy boolean values during migration
    if isinstance(state, bool):
        return state
    return state in ("suggested", "on")


def _auto_enable_booking_types(trip_inputs: TripInputs) -> None:
    """Auto-upgrade booking_types from 'off' to 'suggested' based on sub-settings.

    Tri-state invariant: ONLY upgrade 'off' -> 'suggested'.
    NEVER change 'suggested' or 'on' states.
    """
    booking_types = dict(trip_inputs.booking_types) if trip_inputs.booking_types else {}

    # Only upgrade 'off' to 'suggested' if sub-settings indicate interest
    if booking_types.get("flights") == "off" and _should_enable_booking_for_flights(
        trip_inputs.flight_settings
    ):
        booking_types["flights"] = "suggested"
    if booking_types.get("hotels") == "off" and _should_enable_booking_for_hotels(
        trip_inputs.hotel_settings
    ):
        booking_types["hotels"] = "suggested"
    if booking_types.get("activities") == "off" and _should_enable_booking_for_activities(
        trip_inputs.activity_settings
    ):
        booking_types["activities"] = "suggested"
    if booking_types.get("ground_transport") == "off" and _should_enable_booking_for_transport(
        trip_inputs.transport_settings
    ):
        booking_types["ground_transport"] = "suggested"

    trip_inputs.booking_types = booking_types


# =============================================================================
# TRIP SHAPE INFERENCE (Deterministic, no LLM)
# =============================================================================
# Infer trip characteristics from user text keywords. These help with
# strategy routing and personalized recommendations.

# Keyword mappings for trip style inference
_TRIP_STYLE_KEYWORDS = {
    "adventure_outdoors": {
        "adventure",
        "adventurous",
        "hiking",
        "trek",
        "trekking",
        "mountain",
        "climbing",
        "outdoors",
        "outdoor",
        "wilderness",
        "nature",
        "camping",
        "backpacking",
        "expedition",
        "trail",
        "trails",
    },
    "beach_relaxation": {
        "beach",
        "beaches",
        "relaxation",
        "relax",
        "relaxing",
        "spa",
        "resort",
        "seaside",
        "coastal",
        "island",
        "islands",
        "tropical",
        "sun",
        "sunbathing",
    },
    "cultural_historical": {
        "cultural",
        "culture",
        "historical",
        "history",
        "museum",
        "museums",
        "heritage",
        "architecture",
        "archaeological",
        "ancient",
        "ruins",
    },
    "romantic": {"romantic", "romance", "honeymoon", "anniversary", "couples", "couple"},
    "family": {"family", "kids", "children", "kid-friendly", "family-friendly"},
    "luxury": {
        "luxury",
        "luxurious",
        "upscale",
        "premium",
        "five-star",
        "5-star",
        "exclusive",
        "boutique",
    },
    # NOTE: "budget" removed to avoid collision with "no budget" phrases
    # Only unambiguous budget-travel indicators are kept
    "budget": {"cheap", "affordable", "backpacker", "hostel", "low-cost"},
}

# Keywords for activity categories (maps to activity_settings.categories)
_ACTIVITY_CATEGORY_KEYWORDS = {
    "hiking": {"hiking", "hike", "trek", "trekking", "trail", "trails", "mountain"},
    "skiing": {"ski", "skiing", "snowboard", "snowboarding", "slopes", "powder", "alpine"},
    "diving": {"dive", "diving", "scuba", "snorkel", "snorkeling", "underwater"},
    "cycling": {"bike", "biking", "bicycle", "cycling", "cycle", "ride", "pedal"},
    "boating": {"boat", "boating", "sail", "sailing", "yacht", "kayak", "canoe", "cruise"},
    "beach": {"beach", "beaches", "seaside", "coastal"},
    "cultural": {"museum", "museums", "cultural", "heritage", "history", "historical"},
    "food": {"food", "culinary", "cuisine", "gastronomy", "wine", "dining", "foodie"},
    "adventure": {"adventure", "adventurous", "extreme", "adrenaline"},
    "wellness": {"spa", "wellness", "yoga", "meditation", "retreat"},
}

# Keywords for pace inference
_PACE_KEYWORDS = {
    "active": {
        "active",
        "adventure",
        "adventurous",
        "hiking",
        "trekking",
        "cycling",
        "sports",
        "athletic",
        "energetic",
        "action-packed",
        "intense",
    },
    "relaxed": {
        "relaxed",
        "relaxing",
        "leisurely",
        "slow",
        "easy",
        "laid-back",
        "chill",
        "peaceful",
        "quiet",
        "serene",
    },
    "balanced": {"balanced", "mix", "mixture", "varied", "some of everything"},
}


def _infer_trip_shape(
    user_text: str,
    strategy_topic: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Infer trip shape characteristics from user text keywords.

    This is a deterministic function that does NOT call any LLM.
    Uses keyword matching to populate:
    - trip_style: Overall trip theme (adventure_outdoors, beach_relaxation, etc.)
    - activity_categories: Specific activity types (hiking, diving, etc.)
    - pace: Trip pace (active, relaxed, balanced)
    - planning_flexibility: How flexible the user is (high/medium/low)

    Returns:
        Dict with inferred values (only non-empty fields included)
    """
    if not user_text:
        return {}

    text_lower = user_text.lower()
    words = set(text_lower.split())
    result: Dict[str, Any] = {}

    # 1. Infer trip_style
    for style, keywords in _TRIP_STYLE_KEYWORDS.items():
        if words & keywords:  # Set intersection
            result["trip_style"] = style
            break

    # 2. Infer activity_categories
    categories = []
    for cat, keywords in _ACTIVITY_CATEGORY_KEYWORDS.items():
        if words & keywords:
            categories.append(cat)
    if categories:
        result["activity_categories"] = categories[:3]  # Max 3 categories

    # 3. Infer pace (default to "active" if adventure/hiking detected)
    for pace, keywords in _PACE_KEYWORDS.items():
        if words & keywords:
            result["pace"] = pace
            break
    # Default: if strategy_topic is set and no pace inferred, assume active
    if strategy_topic and "pace" not in result:
        result["pace"] = "active"

    # 4. Infer planning_flexibility
    # High flexibility: vague requests without specifics
    flexibility_keywords_high = {"somewhere", "anywhere", "not sure", "open to", "flexible"}
    flexibility_keywords_low = {"must", "exactly", "specifically", "definitely", "only"}

    if any(kw in text_lower for kw in flexibility_keywords_high):
        result["planning_flexibility"] = "high"
    elif any(kw in text_lower for kw in flexibility_keywords_low):
        result["planning_flexibility"] = "low"
    else:
        # Default to high if no specifics given and it's an open-ended query
        if not result.get("trip_style") and len(user_text) < 50:
            result["planning_flexibility"] = "high"

    return result


# =============================================================================
# BOOKING FIELD NORMALIZATION (ported from plan.py)
# =============================================================================


def _normalize_booking_field(field: str, raw_value: dict) -> Optional[dict]:
    """Normalize a booking preference field from LLM output."""
    if not isinstance(raw_value, dict):
        return None

    if field == "booking_types":
        result = {}
        for key in ("hotels", "flights", "ground_transport", "activities"):
            if key in raw_value and isinstance(raw_value[key], bool):
                result[key] = raw_value[key]
        return result if result else None

    if field == "flight_settings":
        result = {}
        if "round_trip" in raw_value and isinstance(raw_value["round_trip"], bool):
            result["round_trip"] = raw_value["round_trip"]
        if "cabin_class" in raw_value:
            cabin = str(raw_value["cabin_class"]).lower().replace(" ", "_")
            if cabin in ("economy", "premium_economy", "business", "first"):
                result["cabin_class"] = cabin
        if "direct_only" in raw_value and isinstance(raw_value["direct_only"], bool):
            result["direct_only"] = raw_value["direct_only"]
        return result if result else None

    if field == "hotel_settings":
        result = {}
        if "min_stars" in raw_value:
            stars = _normalize_int(raw_value["min_stars"])
            if stars is not None:
                result["min_stars"] = max(0, min(5, stars))
        if "amenities" in raw_value:
            amenities = raw_value["amenities"]
            if isinstance(amenities, list):
                normalized_amenities = []
                for a in amenities:
                    a_str = _normalize_str(a)
                    if a_str:
                        normalized_amenities.append(a_str.lower())
                result["amenities"] = normalized_amenities
        return result if result else None

    if field == "activity_settings":
        result = {}
        if "categories" in raw_value:
            categories = raw_value["categories"]
            if isinstance(categories, list):
                # Use canonicalize_activity_categories for consistent lowercase, no-emoji keys
                # This ensures routing comparisons work correctly
                # (e.g., "diving" matches STRATEGY_TOPIC_TO_NODE)
                canonical_categories = canonicalize_activity_categories(categories)
                if canonical_categories:
                    result["categories"] = canonical_categories
        return result if result else None

    if field == "transport_settings":
        result = {}
        for key in ("car", "train", "bus"):
            if key in raw_value and isinstance(raw_value[key], bool):
                result[key] = raw_value[key]
        return result if result else None

    return None


# =============================================================================
# INITIALIZE TRIP NORMALIZER SINGLETON
# =============================================================================
# Now that all dependencies are defined, eagerly initialize the singleton.
# This ensures backward compatibility with code that imports _trip_normalizer directly.
_trip_normalizer = _create_trip_normalizer()


# =============================================================================
# BRANCH NORMALIZATION (ported from plan.py)
# =============================================================================


def _normalize_branch_spec(spec: dict, fallback_inputs: dict) -> Optional[dict]:
    """Normalize a branch specification from LLM output."""
    if not isinstance(spec, dict) or "label" not in spec:
        return None

    # Handle destinations as array
    branch_destinations = spec.get("destinations", [])
    if not isinstance(branch_destinations, list):
        branch_destinations = [branch_destinations] if branch_destinations else []
    branch_destinations = [_normalize_str(d) for d in branch_destinations if d]
    if not branch_destinations:
        branch_destinations = fallback_inputs.get("destinations", [])
    if not branch_destinations:
        return None

    # Normalize other fields with fallbacks
    branch_origin = _normalize_str(spec.get("origin")) or fallback_inputs.get("origin")
    branch_start = _normalize_date(spec.get("start_date")) or fallback_inputs.get("start_date")
    branch_end = _normalize_date(spec.get("end_date")) or fallback_inputs.get("end_date")

    branch_adults = _normalize_int(spec.get("adults"))
    if branch_adults is None:
        branch_adults = _normalize_int(fallback_inputs.get("adults"))
    if branch_adults is not None:
        branch_adults = _clamp_traveler_value(branch_adults)

    branch_children = _normalize_int(spec.get("children"))
    if branch_children is None:
        branch_children = _normalize_int(fallback_inputs.get("children"))
    if branch_children is not None:
        branch_children = _clamp_traveler_value(branch_children)

    branch_requires_assistance = spec.get("requires_assistance")
    if branch_requires_assistance is None:
        branch_requires_assistance = fallback_inputs.get("requires_assistance")
    if branch_requires_assistance is not None and not isinstance(branch_requires_assistance, bool):
        branch_requires_assistance = None

    branch_budget = _normalize_budget(spec.get("budget"))
    if branch_budget is None:
        branch_budget = _normalize_budget(fallback_inputs.get("budget"))
    if branch_budget is not None and isinstance(branch_budget, (int, float)) and branch_budget < 0:
        branch_budget = None

    branch_currency = _normalize_currency(
        spec.get("currency"), default=_normalize_currency(fallback_inputs.get("currency"))
    )
    if branch_currency is None:
        branch_currency = DEFAULT_CURRENCY

    # Strategy-enriched fields (preserve if present)
    branch_vibe = spec.get("vibe") if isinstance(spec.get("vibe"), str) else None
    branch_focus = spec.get("focus") if isinstance(spec.get("focus"), str) else None
    branch_highlights = spec.get("highlights", [])
    if not isinstance(branch_highlights, list):
        branch_highlights = []
    branch_flow = spec.get("flow", [])
    if not isinstance(branch_flow, list):
        branch_flow = []
    branch_notes = spec.get("notes", [])
    if not isinstance(branch_notes, list):
        branch_notes = []

    return {
        "id": spec.get("id") or uuid4().hex[:8],
        "label": str(spec["label"]),
        "description": str(spec.get("description", "")),
        "destinations": branch_destinations,
        "origin": branch_origin,
        "start_date": branch_start,
        "end_date": branch_end,
        "adults": branch_adults,
        "children": branch_children,
        "requires_assistance": branch_requires_assistance,
        "budget": branch_budget,
        "currency": branch_currency,
        # Strategy-enriched fields
        "vibe": branch_vibe,
        "focus": branch_focus,
        "highlights": branch_highlights,
        "flow": branch_flow,
        "notes": branch_notes,
    }


# =============================================================================
# MISSING FIELDS & DEFAULT QUESTION (ported from plan.py)
# =============================================================================


# =============================================================================
# TRIP READINESS (Phase 6 Consolidation)
# =============================================================================
# Single canonical computation for missing fields, question target, and readiness.
# All nodes MUST use this instead of computing missing fields inline.

# P3: TripReadiness dataclass is now imported from planner.gates.readiness
# See line ~1083: from app.planner.gates.readiness import TripReadiness
# The compute_trip_readiness() function below still creates TripReadiness instances.

# NOTE: The following properties are defined on TripReadiness:
#   - has_destinations: bool - True if destinations are set
#   - has_origin: bool - True if origin is set
#   - has_dates: bool - True if start_date is set
#   - has_blocking_errors: bool - True if any blocking errors exist

# NOTE: TripReadiness and compute_trip_readiness extracted in P4.
# If you need to modify them, edit: backend/app/planner/gates/readiness.py


def _default_follow_up_with_field(
    missing_fields: List[str],
    _user_intent: str = "detailed_planner",  # Unused - kept for backward compat
    _user_tone: str = "neutral",  # Unused - kept for backward compat
    _trip_inputs: Optional[dict] = None,  # Unused - kept for backward compat
) -> tuple[Optional[str], Optional[str]]:
    """
    Get the default question and the field being asked about.
    YC style: All prompts are terse, system-like, under 8 words.

    Returns a tuple of (question, field_name) for tracking which field
    was last asked, enabling context-aware clarification responses.
    """
    if not missing_fields:
        return None, None

    # YC style: System-like prompts - terse, declarative
    prompts = {
        "destinations": "Destination?",
        "origin": "Origin?",
        "start_date": "Dates?",
        "duration": "How long is your trip?",
        "end_date": "Return date?",
        "adults": "Travelers?",
        "budget": "Budget?",
    }

    # Find first missing required field
    for required_field in _REQUIRED_TRIP_INPUT_FIELDS:
        if required_field in missing_fields:
            question = prompts.get(required_field, "Missing constraint.")
            if question:
                return question, required_field
    return None, None


# =============================================================================
# SUGGESTED RESPONSES FILTERING (ported from plan.py)
# =============================================================================

# Patterns that indicate assistant-style phrasing (not user voice)
_ASSISTANT_PHRASES = frozenset(
    [
        "i can help",
        "let me",
        "i'll help",
        "would you like",
        "shall i",
        "i suggest",
        "i recommend",
        "we can",
        "we could",
        "here are",
        "here's",
        "feel free",
        "don't hesitate",
        "so i can",
        "assist you",
        "help you",
    ]
)

# Patterns indicating vague/placeholder content
_VAGUE_PATTERNS = frozenset(
    [
        "...",
        "[",
        "]",
        "enter",
        "select",
        "choose",
        "type",
        "input",
        "specify",
        "provide",
    ]
)

# Instruction-style verbs that indicate prompts, not user responses
_INSTRUCTION_STARTS = frozenset(
    [
        "add",
        "include",
        "specify",
        "provide",
        "enter",
        "select",
        "choose",
        "consider",
        "try",
        "explore",
        "look for",
        "looking for",
        "search for",
        "find",
        "get",
        "set",
        "update",
        "change",
    ]
)


def _is_low_quality_suggestion(text: str) -> bool:
    """Check if suggestion is too vague, assistant-style, or instruction-like."""
    lower = text.lower().strip()

    # Reject assistant-style phrases
    for phrase in _ASSISTANT_PHRASES:
        if phrase in lower:
            return True

    # Reject vague/placeholder patterns
    for pattern in _VAGUE_PATTERNS:
        if pattern in lower:
            return True

    # Reject instruction-style starts (these are prompts, not user responses)
    for instruction in _INSTRUCTION_STARTS:
        if lower.startswith(instruction + " ") or lower.startswith(instruction + " a "):
            return True

    # Reject request patterns (user asking the assistant to do something)
    request_patterns = [
        "please ",
        "can you ",
        "could you ",
        "would you ",
        "will you ",
        "i need you to",
        "i want you to",
        "i'd like you to",
    ]
    for pattern in request_patterns:
        if lower.startswith(pattern):
            return True

    # Reject if too short (less than 2 words) UNLESS it looks like a place name
    # Single-word destinations like "Nepal", "Bali", "Peru" are valid
    words = text.split()
    if len(words) < 2:
        # Reject single letters but allow 2-3 char uppercase abbreviations (LA, NYC, UK)
        if len(text) == 1:
            return True
        # Allow all-uppercase abbreviations (LA, UK, NYC, USA) - valid place codes
        if text.isupper() and len(text) <= 4:
            pass  # Allow these
        elif len(text) <= 2:
            # Reject 2-char lowercase or mixed case (not abbreviations)
            return True
        # Reject pure numbers (like "2", "10", "2024")
        if text.isdigit():
            return True
        # Reject common command words that might be capitalized
        command_words = {"go", "try", "set", "get", "add", "run", "use", "see", "ask", "let"}
        if lower in command_words:
            return True
        # Allow single words that start with uppercase (proper nouns = places)
        # or are at least 4 characters (likely a place name or valid term)
        if not (text[0].isupper() or len(text) >= 4):
            return True

    # Reject if too many words (more than 8)
    if len(words) > 8:
        return True

    # Reject generic fillers
    generic_fillers = {"yes", "no", "ok", "okay", "sure", "thanks", "thank you"}
    if lower in generic_fillers:
        return True

    # Reject suggestions that are too generic/vague (no concrete nouns)
    # Use word boundary matching to avoid false positives like "Adventure activities"
    vague_phrases = [
        "a specific",
        "the best",
        "some options",
        "more details",
        "more information",
        "something",
        "anything",
        "anywhere",  # too vague without specifics
        "somewhere",  # too vague without specifics
        "preferences",
        "by the beach",  # vague location
        "near the",
        "around the",
    ]
    for vague in vague_phrases:
        if vague in lower:
            return True

    # Reject if ONLY the word "activities" or "destination" (too generic alone)
    # But allow "Adventure activities", "Beach activities", etc.
    if lower == "activities" or lower == "destination":
        return True

    return False


def _generate_conversation_summary(
    chat_history: List[Dict[str, str]],
    max_turns: int = 5,
    state: Optional["GraphState"] = None,
) -> str:
    """Generate a natural language summary of recent conversation for suggestion context.

    Args:
        chat_history: List of {role, content} message dicts
        max_turns: Maximum number of turns to include (default 5)
        state: Optional GraphState for per-turn caching (Tier 4 optimization)

    Returns:
        Natural language summary of recent conversation context

    Tier 4 Optimization: Caches the summary in state.metadata to avoid
    recomputation within the same turn. Saves ~100-200 tokens per specialist call.
    """
    # Check for cached summary (Tier 4: avoid recomputation within turn)
    cache_key = f"conversation_summary_{max_turns}"
    if state and cache_key in state.metadata:
        _debug("📦 CONVERSATION_SUMMARY_CACHE_HIT: Using cached summary", turns=max_turns)
        return state.metadata[cache_key]

    if not chat_history:
        return "No prior conversation."

    # Get the last N exchanges (user + assistant pairs count as 1 turn)
    recent_messages = chat_history[-(max_turns * 2) :]

    if not recent_messages:
        return "No prior conversation."

    # Build natural language summary
    summary_parts = []
    for msg in recent_messages:
        role = msg.get("role", "")
        content = msg.get("content", "").strip()
        if not content:
            continue

        # Truncate long messages
        if len(content) > 150:
            content = content[:147] + "..."

        if role == "user":
            summary_parts.append(f'User said: "{content}"')
        elif role == "assistant":
            summary_parts.append(f'Assistant replied: "{content}"')

    if not summary_parts:
        return "No prior conversation."

    result = " → ".join(summary_parts)

    # Cache the result for this turn
    if state:
        state.metadata[cache_key] = result

    return result


def _get_missing_fields_summary(state: "GraphState") -> str:
    """Get a summary of missing required fields for prompt injection.

    DEPRECATED: Use compute_trip_readiness().missing_summary instead.

    Args:
        state: Current graph state

    Returns:
        Comma-separated list of missing fields or "none"
    """
    readiness = compute_trip_readiness(state.trip_inputs)
    return readiness.missing_summary


def _filter_suggested_responses(responses: List[Any]) -> List[str]:
    """Filter suggested responses: remove questions, low-quality, limit to 3, handle dict format."""
    result = []
    seen_lower = set()  # Deduplicate case-insensitively

    for r in responses:
        # Handle dict format
        if isinstance(r, dict):
            text = r.get("text") or r.get("response") or r.get("value") or ""
        else:
            text = str(r) if r else ""

        text = text.strip()
        if not text:
            continue

        # Reject questions
        if "?" in text:
            continue

        # Reject low-quality suggestions
        if _is_low_quality_suggestion(text):
            continue

        # Deduplicate case-insensitively
        lower = text.lower()
        if lower in seen_lower:
            continue
        seen_lower.add(lower)

        # Limit length (truncate if needed, but prefer rejection for quality)
        if len(text) > 50:
            text = text[:47] + "..."

        result.append(text)

        if len(result) >= 3:
            break

    return result


# Minimum relevance score threshold - suggestions below this are suppressed
_SUGGESTION_RELEVANCE_THRESHOLD = 0.5
# Minimum number of suggestions to show - if fewer pass threshold, show none
_MIN_SUGGESTIONS_TO_SHOW = 2


def _score_suggestion_relevance(
    suggestion: str,
    question_target: Optional[str],
    user_intent: Optional[str] = None,
) -> float:
    """
    Score how relevant a suggestion is to the question_target.

    Returns a score from 0.0 to 1.0:
    - 1.0: High confidence match
    - 0.7-0.9: Good match
    - 0.4-0.6: Weak match
    - 0.0-0.3: Mismatch

    Args:
        suggestion: The suggestion text to score
        question_target: What field the assistant is asking about
        user_intent: User intent (adventurous, quick_booking, etc.)
    """
    if not suggestion or not question_target:
        # If no question_target, we can't score relevance - accept suggestion
        return 0.8

    lower = suggestion.lower().strip()

    # Pattern matching for each question_target type
    if question_target == "origin":
        # Origin suggestions should start with "From" or be a city name
        if lower.startswith("from "):
            return 1.0
        # Check if it looks like a city (capitalized, no travel verbs)
        if not any(word in lower for word in ["to ", "visit", "go to", "explore"]):
            # Could be a city name without "From" - medium confidence
            return 0.6
        return 0.2  # Likely a destination, not origin

    elif question_target == "destinations":
        # Destination suggestions should NOT start with "From"
        if lower.startswith("from "):
            return 0.1  # This is an origin, not destination
        # Check for place-like patterns (proper nouns, location words)
        destination_indicators = [
            "beach",
            "island",
            "mountain",
            "city",
            "country",
            "alps",
            "coast",
            "bay",
            "valley",
            "lake",
        ]
        if any(ind in lower for ind in destination_indicators):
            return 1.0
        # If it contains comma (like "Paris, France"), likely a destination
        if "," in suggestion:
            return 0.95
        # Check if it matches adventure destinations for intent
        if user_intent == "adventurous":
            adventure_keywords = ["trek", "hike", "climb", "adventure", "explore"]
            if any(kw in lower for kw in adventure_keywords):
                return 0.9
        # Generic place name - accept with medium confidence
        if not any(word in lower for word in ["from ", "next ", "in ", " weeks", " month"]):
            return 0.8
        return 0.3

    elif question_target in ("dates", "start_date", "end_date"):
        # Date suggestions should contain time-related words
        date_indicators = [
            "month",
            "week",
            "december",
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "today",
            "tomorrow",
            "next",
            "in ",
            "spring",
            "summer",
            "fall",
            "winter",
            "christmas",
            "holiday",
            "-",  # For date ranges like "Dec 15-22"
        ]
        if any(ind in lower for ind in date_indicators):
            return 1.0
        # Check for numeric patterns (dates)
        if any(char.isdigit() for char in suggestion):
            return 0.9
        return 0.2  # Doesn't look like a date

    elif question_target in ("travelers", "adults"):
        # Traveler suggestions should mention numbers or group types
        traveler_indicators = [
            "solo",
            "just me",
            "couple",
            "family",
            "adult",
            "child",
            "kid",
            "person",
            "people",
            "1 ",
            "2 ",
            "3 ",
            "4 ",
            "5 ",
            "6 ",
            "me and",
            "with my",
            "group of",
        ]
        if any(ind in lower for ind in traveler_indicators):
            return 1.0
        # Check for numeric patterns
        if any(char.isdigit() for char in suggestion):
            return 0.8
        return 0.2  # Doesn't look like traveler info

    elif question_target == "budget":
        # Budget suggestions should mention money or cost levels
        budget_indicators = [
            "$",
            "€",
            "£",
            "budget",
            "luxury",
            "mid-range",
            "cheap",
            "affordable",
            "expensive",
            "per day",
            "per night",
            "total",
        ]
        if any(ind in lower for ind in budget_indicators):
            return 1.0
        # Check for numeric patterns (budget amounts)
        if any(char.isdigit() for char in suggestion):
            return 0.7
        return 0.2

    elif question_target == "activities":
        # Activity suggestions should mention activity types
        activity_indicators = [
            "sightseeing",
            "hiking",
            "diving",
            "snorkeling",
            "beach",
            "museum",
            "tour",
            "food",
            "wine",
            "spa",
            "adventure",
            "shopping",
            "nightlife",
            "culture",
            "art",
            "history",
            "sports",
            "yoga",
            "safari",
            "cruise",
        ]
        if any(ind in lower for ind in activity_indicators):
            return 1.0
        return 0.5  # Could be an activity

    elif question_target == "general":
        # General questions - accept most suggestions
        return 0.7

    # Unknown question_target - accept with low confidence
    return 0.5


def _infer_question_target_from_missing(state: "GraphState") -> Optional[str]:
    """Infer question_target from missing required fields when LLM doesn't provide one."""
    ti = state.trip_inputs
    # Priority order for missing fields
    if not ti.destinations:
        return "destinations"
    if not ti.origin:
        return "origin"
    if not ti.start_date:
        return "dates"
    if ti.adults is None:
        return "travelers"
    if ti.budget is None:
        return "budget"
    return None


def _get_suggestions_with_fallback(
    raw_suggestions: List[Any],
    state: "GraphState",
    question_target: Optional[str] = None,
) -> List[str]:
    """Filter LLM suggestions by relevance to question_target.

    Args:
        raw_suggestions: Raw suggestions from LLM
        state: Current graph state
        question_target: What field the assistant is asking about

    Returns:
        List of relevant suggestions (may be empty if none are relevant)
    """
    # Infer question_target from missing fields if not provided
    effective_target = question_target
    if not effective_target:
        effective_target = _infer_question_target_from_missing(state)
        if effective_target:
            _debug(f"Inferred question_target from missing fields: {effective_target}")

    filtered = _filter_suggested_responses(raw_suggestions)

    if not filtered:
        # No LLM suggestions - return empty (no static fallbacks)
        _debug("No LLM suggestions - returning empty")
        return []

    # Score each suggestion for relevance
    user_intent = state.metadata.get("user_intent_hint")
    scored_suggestions = []
    for suggestion in filtered:
        score = _score_suggestion_relevance(suggestion, effective_target, user_intent)
        scored_suggestions.append((suggestion, score))
        if _DEBUG_LOG:
            _debug(f"Suggestion score: '{suggestion}' -> {score:.2f} (target={effective_target})")

    # Filter by threshold
    passing = [s for s, score in scored_suggestions if score >= _SUGGESTION_RELEVANCE_THRESHOLD]

    # If not enough pass, suppress entirely (better no suggestions than bad ones)
    if len(passing) < _MIN_SUGGESTIONS_TO_SHOW:
        _debug(
            f"⚠️ Suppressing suggestions: only {len(passing)}/{_MIN_SUGGESTIONS_TO_SHOW} passed "
            f"threshold={_SUGGESTION_RELEVANCE_THRESHOLD:.2f}"
        )
        return []

    return passing[:3]


# -----------------------
# Models & schema
# -----------------------
class TripInputs(BaseModel):
    destinations: List[str] = []
    origin: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    requires_assistance: Optional[bool] = None
    budget: Optional[float] = None
    currency: Optional[str] = None
    multi_city_intent: Optional[Literal["multi_city", "separate"]] = None
    # Tri-state: "off" | "suggested" | "on" (also accepts legacy bool for migration)
    booking_types: Dict[str, Any] = Field(default_factory=dict)
    flight_settings: Dict[str, Any] = Field(default_factory=dict)
    hotel_settings: Dict[str, Any] = Field(default_factory=dict)
    activity_settings: Dict[str, Any] = Field(default_factory=lambda: {"categories": []})
    transport_settings: Dict[str, Any] = Field(default_factory=dict)
    # Strategy-specific persisted preferences (per topic)
    strategy_settings: Dict[str, Any] = Field(default_factory=dict)
    # Flexible dates support (user chose "flexible dates" instead of specific dates)
    date_flex: bool = False  # User chose "flexible dates"
    trip_duration: Optional[int] = None  # Trip length in days (e.g., 7)
    date_window_start: Optional[str] = None  # Earliest possible start (e.g., "2025-02-01")
    date_window_end: Optional[str] = None  # Latest possible start (e.g., "2025-04-30")

    @field_validator("budget", mode="before")
    @classmethod
    def parse_budget_string(cls, v):
        """Parse budget from string with currency symbol if needed."""
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            # Remove currency symbols and commas, extract number
            import re

            cleaned = re.sub(r"[^\d.]", "", v)
            if cleaned:
                try:
                    return float(cleaned)
                except ValueError:
                    return None
        return None


# Valid values for question_target field
QUESTION_TARGET_VALUES = frozenset(
    {
        "destinations",
        "origin",
        "dates",
        "duration",
        "travelers",
        "budget",
        "activities",
        "general",
        None,
    }
)


# =============================================================================
# STATE INTEGRITY FRAMEWORK
# =============================================================================
# Single-writer pattern for state mutations with invariant enforcement.
# Prevents state corruption (reset to {}, lost keys) that caused E2E test failures.


class StateRegressionError(Exception):
    """Raised when state invariants are violated (e.g., trip_inputs reset).

    This exception triggers the recovery handler which restores state from
    the pre-turn snapshot and emits a recovery response to the user.
    """

    def __init__(
        self,
        pre_turn_snapshot: Dict[str, Any],
        post_turn_candidate_state: Dict[str, Any],
        diff_summary: str,
        node_name: str,
        journal_turn_id: str,
    ):
        self.pre_turn_snapshot = pre_turn_snapshot
        self.post_turn_candidate_state = post_turn_candidate_state
        self.diff_summary = diff_summary
        self.node_name = node_name
        self.journal_turn_id = journal_turn_id
        super().__init__(f"State regression in {node_name}: {diff_summary}")


# Observability counters for state integrity metrics
_state_integrity_counters: Dict[str, int] = {
    "state_regression_count": 0,
    "loop_guard_trigger_count": 0,
    "recovery_attempt_count": 0,
    "recovery_success_count": 0,
    "node_error_count": 0,
    "cache_hit_count": 0,
    "cache_miss_count": 0,
    "assistant_response_null_guard_count": 0,  # Times fallback response was used
    "invented_detail_block_count": 0,  # Times specialist blocked invented details
}

# Histograms for per-turn observability (stores last N values for analysis)
_observability_histograms: Dict[str, List[int]] = {
    "trip_inputs_keycount_delta": [],  # Change in trip_inputs key count per turn
    "llm_calls_per_turn": [],  # Number of LLM calls per turn
}
_HISTOGRAM_MAX_SIZE = 100  # Keep last 100 values


def _record_histogram(histogram_name: str, value: int) -> None:
    """Record a value to an observability histogram."""
    if histogram_name in _observability_histograms:
        hist = _observability_histograms[histogram_name]
        hist.append(value)
        # Keep histogram size bounded
        if len(hist) > _HISTOGRAM_MAX_SIZE:
            _observability_histograms[histogram_name] = hist[-_HISTOGRAM_MAX_SIZE:]


def _get_histogram_stats(histogram_name: str) -> Dict[str, Any]:
    """Get statistics for a histogram."""
    if histogram_name not in _observability_histograms:
        return {}
    values = _observability_histograms[histogram_name]
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
        "last_5": values[-5:],
    }


def _get_all_observability_stats() -> Dict[str, Any]:
    """Get all observability counters and histogram stats."""
    stats = _get_state_counters()
    for name in _observability_histograms:
        stats[f"histogram_{name}"] = _get_histogram_stats(name)
    return stats


def _increment_state_counter(counter_name: str, amount: int = 1) -> None:
    """Increment a state integrity counter for observability."""
    if counter_name in _state_integrity_counters:
        _state_integrity_counters[counter_name] += amount


def _get_state_counters() -> Dict[str, int]:
    """Get current state integrity counter values."""
    return _state_integrity_counters.copy()


def _check_state_invariants(
    pre_turn_snapshot: Dict[str, Any],
    post_turn_state: Dict[str, Any],
) -> Optional[str]:
    """Check state invariants and return violation description if any.

    Invariants enforced:
    1. trip_inputs must not become {} if it wasn't {} before (unless explicit reset)
    2. Existing non-null keys cannot be nulled without explicit reset
    3. Core fields (destinations, origin, dates) cannot be lost

    Returns:
        None if no violations, or a description string if violated.
    """
    violations = []

    # Invariant 1: trip_inputs must not reset to empty
    if pre_turn_snapshot and not post_turn_state:
        violations.append("trip_inputs reset to {} from non-empty state")

    # Invariant 2: Non-null keys cannot become null
    for key, value in pre_turn_snapshot.items():
        if value is not None and key in post_turn_state:
            if post_turn_state.get(key) is None:
                violations.append(f"key '{key}' was nulled (was: {value})")

    # Invariant 3: Core fields cannot be lost
    core_fields = ["destinations", "origin", "start_date", "end_date"]
    for core_field in core_fields:
        if pre_turn_snapshot.get(core_field) and not post_turn_state.get(core_field):
            violations.append(f"core field '{core_field}' was lost")

    # Invariant 4: Keys cannot disappear
    lost_keys = set(pre_turn_snapshot.keys()) - set(post_turn_state.keys())
    # Filter out keys that were None in the snapshot (those are allowed to disappear)
    lost_keys = {k for k in lost_keys if pre_turn_snapshot.get(k) is not None}
    if lost_keys:
        violations.append(f"keys lost: {lost_keys}")

    return "; ".join(violations) if violations else None


def _compute_trip_inputs_diff(
    before: Dict[str, Any],
    after: Dict[str, Any],
) -> Dict[str, Any]:
    """Compute a diff between two trip_inputs states.

    Returns a dict with:
    - added: keys that were added
    - changed: keys whose values changed
    - removed: keys that were removed (should trigger invariant violation)
    """
    diff = {"added": {}, "changed": {}, "removed": []}

    all_keys = set(before.keys()) | set(after.keys())
    for key in all_keys:
        before_val = before.get(key)
        after_val = after.get(key)

        if key not in before and key in after:
            diff["added"][key] = after_val
        elif key in before and key not in after:
            diff["removed"].append(key)
        elif before_val != after_val:
            diff["changed"][key] = {"from": before_val, "to": after_val}

    return diff


class GraphState(BaseModel):
    user_text: str
    trip_inputs: TripInputs = Field(default_factory=TripInputs)
    parsed_inputs: Dict[str, Any] = Field(default_factory=dict)
    ready_to_generate: bool = False
    branches: List[Dict[str, Any]] = Field(default_factory=list)
    suggested_responses: List[str] = Field(default_factory=list)
    intent: Optional[str] = (
        None  # required_fields|flights|hotels|transport|activities|correction_needed|strategy
    )
    strategy_topic: Optional[str] = None  # boating|hiking|diving|...
    active_category: Optional[str] = None
    last_summary: Optional[str] = None
    errors: List[ErrorRecord] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    flags: Dict[str, Any] = Field(default_factory=dict)
    # Chat history for LLM context (list of {role, content} dicts) - matches plan.py
    chat_history: List[Dict[str, str]] = Field(default_factory=list)
    # What field the assistant's question is asking about (for suggestion relevance)
    question_target: Optional[str] = (
        None  # destinations|origin|dates|travelers|budget|activities|general
    )
    # Two-stage strategy: True when stage 1 complete, waiting for user to expand
    pending_strategy_expansion: bool = False
    # Session ID for caching purposes
    session_id: Optional[str] = None
    # Strategy expansion tier (outline/section/full) for token budget control
    strategy_expansion_tier: Optional[str] = None  # StrategyTier value
    # Strategy expansion target (which section to expand)
    strategy_expansion_target: Optional[str] = None  # StrategyExpansionTarget value

    # ==========================================================================
    # State Integrity Fields (for loop guard and recovery)
    # ==========================================================================
    # Loop guard state for detecting and mitigating repeated question loops
    loop_guard: Dict[str, Any] = Field(
        default_factory=lambda: {
            "last_questions": [],  # List of {"field": str, "text_hash": str, "turn": int}
            "forced_route_cooldown_until_turn": 0,
            "triggers_this_convo": 0,
        }
    )
    # Questions already asked in this conversation (field -> last turn asked)
    questions_asked: Dict[str, int] = Field(default_factory=dict)
    # Current turn number for tracking
    turn_number: int = 0


# =============================================================================
# TURN UPDATE FUNCTIONS (Single-writer pattern for state integrity)
# =============================================================================


def _create_turn_journal_entry(
    state: "GraphState",
    node_path: List[str],
    routing_decision: Optional[str] = None,
    parsed_inputs_delta: Optional[Dict[str, Any]] = None,
    trip_inputs_diff: Optional[Dict[str, Any]] = None,
    cache_hits: Optional[Dict[str, bool]] = None,
    error_events: Optional[List[Dict[str, Any]]] = None,
    loop_guard_triggered: bool = False,
    loop_guard_action: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a turn journal entry for debugging and post-mortem analysis."""
    from datetime import datetime

    return {
        "turn_id": f"{state.session_id or 'unknown'}_{state.turn_number}",
        "timestamp": datetime.utcnow().isoformat(),
        "node_path": node_path,
        "routing_decision": routing_decision,
        "parsed_inputs_delta": parsed_inputs_delta or {},
        "trip_inputs_diff": trip_inputs_diff or {},
        "cache_hits": cache_hits or {},
        "error_events": error_events or [],
        "loop_guard_triggered": loop_guard_triggered,
        "loop_guard_action": loop_guard_action,
    }


def _append_journal_entry(state: "GraphState", entry: Dict[str, Any]) -> None:
    """Append a journal entry to the state's turn journal (ring buffer)."""
    if "turn_journal" not in state.metadata:
        state.metadata["turn_journal"] = []

    journal = state.metadata["turn_journal"]

    # Ring buffer: keep last N entries
    max_entries = settings.turn_journal_max_turns
    while len(journal) >= max_entries:
        journal.pop(0)

    journal.append(entry)


def _summarize_trip_inputs_for_recovery(trip_inputs: Dict[str, Any]) -> str:
    """Create a human-readable summary of trip_inputs for recovery messages."""
    parts = []

    if trip_inputs.get("destinations"):
        dests = trip_inputs["destinations"]
        if isinstance(dests, list):
            parts.append(f"**Destinations:** {', '.join(dests)}")
        else:
            parts.append(f"**Destination:** {dests}")

    if trip_inputs.get("origin"):
        parts.append(f"**From:** {trip_inputs['origin']}")

    if trip_inputs.get("start_date") or trip_inputs.get("end_date"):
        start = trip_inputs.get("start_date", "?")
        end = trip_inputs.get("end_date", "?")
        parts.append(f"**Dates:** {start} to {end}")

    if trip_inputs.get("adults") or trip_inputs.get("children"):
        adults = trip_inputs.get("adults", 0)
        children = trip_inputs.get("children", 0)
        if children:
            parts.append(f"**Travelers:** {adults} adults, {children} children")
        else:
            parts.append(f"**Travelers:** {adults}")

    if trip_inputs.get("budget"):
        currency = trip_inputs.get("currency", "USD")
        parts.append(f"**Budget:** {trip_inputs['budget']} {currency}")

    # Use double newlines for proper markdown paragraph breaks
    return "\n\n".join(parts) if parts else "No trip details recorded yet."


def apply_turn_update(
    state: "GraphState",
    trip_inputs_delta: Optional[Dict[str, Any]] = None,
    node_name: str = "unknown",
    pre_turn_snapshot: Optional[Dict[str, Any]] = None,
    journal_turn_id: Optional[str] = None,
) -> "GraphState":
    """
    Single-writer for trip_inputs mutations. Enforces state invariants.

    This function is the ONLY place that should mutate trip_inputs during a turn.
    It enforces monotonic merge (existing non-null keys cannot be nulled) and
    raises StateRegressionError if invariants are violated.

    Args:
        state: The current graph state
        trip_inputs_delta: Dict of trip_inputs fields to merge
        node_name: Name of the node requesting the update (for debugging)
        pre_turn_snapshot: Snapshot of trip_inputs at turn start
        journal_turn_id: ID for this turn's journal entry

    Returns:
        The updated state

    Raises:
        StateRegressionError: If state invariants are violated and
            STATE_SNAPSHOT_RESTORE_ENABLED is True
    """
    if trip_inputs_delta is None:
        return state

    # Get pre-turn snapshot from state metadata if not provided
    if pre_turn_snapshot is None:
        pre_turn_snapshot = state.metadata.get("pre_turn_snapshot", {})

    # Convert TripInputs to dict for comparison
    current_inputs = (
        state.trip_inputs.model_dump()
        if hasattr(state.trip_inputs, "model_dump")
        else dict(state.trip_inputs)
    )

    # Compute proposed new state by merging delta
    new_inputs = current_inputs.copy()
    for key, value in trip_inputs_delta.items():
        if value is not None:  # Only update if new value is not None
            new_inputs[key] = value
        elif key not in new_inputs:
            # Allow adding new None keys, but don't overwrite existing with None
            new_inputs[key] = value

    # Check invariants if enabled
    if settings.state_invariants_enabled:
        violations = _check_state_invariants(pre_turn_snapshot, new_inputs)

        if violations:
            # Log the violation
            _debug_error(
                "STATE_REGRESSION detected",
                node=node_name,
                violations=violations,
                journal_turn_id=journal_turn_id,
            )
            _increment_state_counter("state_regression_count")

            if settings.state_snapshot_restore_enabled:
                raise StateRegressionError(
                    pre_turn_snapshot=pre_turn_snapshot,
                    post_turn_candidate_state=new_inputs,
                    diff_summary=violations,
                    node_name=node_name,
                    journal_turn_id=journal_turn_id or "unknown",
                )
            else:
                # Log but continue with the update (reconcile mode)
                _debug(
                    "State regression detected but restore disabled, continuing",
                    violations=violations,
                )

    # Apply the update
    for key, value in new_inputs.items():
        if hasattr(state.trip_inputs, key):
            setattr(state.trip_inputs, key, value)

    # Compute and store diff for journal
    diff = _compute_trip_inputs_diff(current_inputs, new_inputs)
    if "turn_updates" not in state.metadata:
        state.metadata["turn_updates"] = []
    state.metadata["turn_updates"].append(
        {
            "node": node_name,
            "diff": diff,
        }
    )

    return state


# Whitelist for undo snapshot - keeps responses small, avoids nested blob leakage
UNDO_SNAPSHOT_FIELDS = frozenset(
    {
        "origin",
        "destinations",
        "start_date",
        "end_date",
        "adults",
        "children",
        "budget",
        "currency",
    }
)


def _extract_undo_snapshot(trip_inputs: Any) -> Dict[str, Any]:
    """Extract only whitelisted fields for undo snapshot."""
    if hasattr(trip_inputs, "model_dump"):
        full = trip_inputs.model_dump()
    else:
        full = dict(trip_inputs)
    return {k: full[k] for k in UNDO_SNAPSHOT_FIELDS if k in full and full[k] is not None}


def capture_pre_turn_snapshot(
    state: "GraphState", ui_phase: Optional[str] = None
) -> Dict[str, Any]:
    """Capture a snapshot of trip_inputs at the start of a turn.

    This snapshot is used to detect state regression and enable recovery.
    Should be called once at the beginning of each turn.

    Args:
        state: The current graph state
        ui_phase: UI phase from request ("bootstrap" or "expanded")
    """
    from copy import deepcopy

    # Convert TripInputs to dict
    if hasattr(state.trip_inputs, "model_dump"):
        snapshot = state.trip_inputs.model_dump()
    else:
        snapshot = dict(state.trip_inputs)

    # Deep copy to prevent mutation
    snapshot = deepcopy(snapshot)

    # Store in metadata
    state.metadata["pre_turn_snapshot"] = snapshot

    # Store whitelisted undo snapshot for UI receipts
    state.metadata["prev_trip_inputs_snapshot"] = _extract_undo_snapshot(state.trip_inputs)

    # Initialize per-turn change tracking
    state.metadata["turn_applied_fields"] = []  # Will be populated by StateWriter
    state.metadata["update_provenance"] = None

    # Store ui_phase for summarize node
    if ui_phase is not None:
        state.metadata["ui_phase"] = ui_phase

    # Increment turn number
    state.turn_number += 1

    # Generate journal turn ID
    import uuid

    journal_turn_id = f"{state.session_id or 'unknown'}_{state.turn_number}_{uuid.uuid4().hex[:8]}"
    state.metadata["journal_turn_id"] = journal_turn_id

    # Initialize turn journal if needed
    if "turn_journal" not in state.metadata:
        state.metadata["turn_journal"] = []

    # Clear per-turn metadata
    state.metadata["turn_updates"] = []
    state.metadata["error_events"] = []

    return snapshot


def handle_state_regression_error(
    state: "GraphState",
    error: StateRegressionError,
) -> "GraphState":
    """Handle a StateRegressionError by restoring state and emitting recovery response.

    This is called when apply_turn_update() raises StateRegressionError.
    It restores state from the pre-turn snapshot and sets up a recovery message.
    """
    _increment_state_counter("recovery_attempt_count")

    # Restore state from snapshot
    for key, value in error.pre_turn_snapshot.items():
        if hasattr(state.trip_inputs, key):
            setattr(state.trip_inputs, key, value)

    # Set error flags
    if "error_flags" not in state.metadata:
        state.metadata["error_flags"] = {}
    state.metadata["error_flags"]["STATE_REGRESSION"] = True

    # Generate recovery response (system-style)
    known_info = _summarize_trip_inputs_for_recovery(error.pre_turn_snapshot)
    state.last_summary = (
        f"State recovered. Current constraints:\n\n" f"{known_info}\n\n" f"Confirm or update:"
    )

    # Force routing next turn to avoid loops
    state.metadata["force_route_next_turn"] = "required_fields"

    # Track for recovery success validation
    state.metadata["pending_recovery_validation"] = {
        "turn": state.turn_number,
        "type": "snapshot_restore",
    }

    # Record in journal
    _append_journal_entry(
        state,
        _create_turn_journal_entry(
            state,
            node_path=[error.node_name],
            error_events=[
                {
                    "type": "STATE_REGRESSION",
                    "node": error.node_name,
                    "diff_summary": error.diff_summary,
                }
            ],
        ),
    )

    return state


# =============================================================================
# LOOP GUARD: Detect and mitigate repeated question loops
# =============================================================================
# The loop guard detects when the system asks the same question repeatedly
# across turns, which indicates a failure to progress or understand answers.


# Mitigation actions in order of escalation
LOOP_GUARD_MITIGATION_ACTIONS = [
    "different_field",  # Switch to asking about a different field
    "extractor_clarification",  # Run extractor with clarification focus
    "specialist_preroute",  # Force route to a different specialist
    "recovery_summary",  # Emit recovery summary with known info
]


def track_question_asked(
    state: "GraphState",
    field_name: str,
    question_text: Optional[str] = None,
) -> None:
    """
    Track that a question was asked about a specific field.

    Updates the loop_guard state to track question patterns across turns.
    This is called whenever a node asks the user a question about a field.

    Args:
        state: Current graph state
        field_name: The trip_inputs field being asked about (e.g., "destinations")
        question_text: Optional text of the question (for debugging)
    """
    if not settings.loop_guard_enabled and not settings.loop_guard_shadow_mode:
        return

    # Initialize questions_asked if needed
    if not hasattr(state, "questions_asked") or state.questions_asked is None:
        state.questions_asked = {}

    # Increment count for this field
    current_count = state.questions_asked.get(field_name, 0)
    state.questions_asked[field_name] = current_count + 1

    # Update loop_guard with recent question history
    if not hasattr(state, "loop_guard") or state.loop_guard is None:
        state.loop_guard = {}

    # Track last N questions per window
    recent_questions = state.loop_guard.get("recent_questions", [])
    recent_questions.append(
        {
            "field": field_name,
            "turn": state.turn_number,
            "text": question_text[:100] if question_text else None,
        }
    )

    # Keep only questions within the window
    window_size = settings.loop_guard_window_turns
    recent_questions = [q for q in recent_questions if q["turn"] >= state.turn_number - window_size]
    state.loop_guard["recent_questions"] = recent_questions

    _debug(
        "Loop guard: tracked question",
        field=field_name,
        total_count=state.questions_asked[field_name],
        window_questions=len(recent_questions),
    )


def _user_explicitly_provided_field(state: "GraphState", field_name: str) -> bool:
    """
    Check if user explicitly provided the field value in current turn.

    This prevents suppressing questions when user says "my budget is..." etc.
    """
    user_text = (state.user_text or "").lower()

    # Field-specific patterns that indicate explicit provision
    explicit_patterns = {
        "budget": [
            "my budget",
            "budget is",
            "budget of",
            "spend about",
            "afford",
            "$",
            "dollars",
            "euros",
        ],
        "adults": [
            "of us",
            "traveling with",
            "people",
            "adults",
            "party of",
            "just me",
            "solo",
            "alone",
            "by myself",
            "couple",
            "two of us",
            "2 of us",
        ],
        "children": ["kids", "children", "child", "with our", "no kids", "no children"],
        "destinations": ["going to", "want to go", "trip to", "visiting"],
        "origin": ["from ", "flying from", "departing from", "leaving from"],
        "start_date": ["leaving on", "departing", "starting", "begin on"],
        "end_date": ["returning", "coming back", "ending", "until"],
    }

    patterns = explicit_patterns.get(field_name, [])
    return any(p in user_text for p in patterns)


def detect_question_loop(state: "GraphState", field_name: str) -> bool:
    """
    Detect if asking about a field would create a question loop.

    A loop is detected when the same field has been asked about
    >= loop_guard_threshold times within the window.

    Guardrails applied:
    - Don't suppress if user explicitly provides the field value
    - Extended window (6 turns) only activates if no progress for 2+ turns
    - Shadow audit mode logs would-trigger events without enforcing

    Args:
        state: Current graph state
        field_name: The field we're about to ask about

    Returns:
        True if asking would trigger a loop, False otherwise
    """
    # Check if loop guard is disabled entirely
    if not settings.loop_guard_enabled and not settings.loop_guard_shadow_mode:
        return False

    # Guardrail: Don't suppress if user explicitly provided the field this turn
    if _user_explicitly_provided_field(state, field_name):
        _debug(
            "Loop guard: user explicitly provided field, not suppressing",
            field=field_name,
        )
        return False

    # Guardrail: Don't suppress if user provided ANY core field this turn.
    # This handles the case where user answers a different question than asked
    # (e.g., asked for dates, user gave origin). The user is actively engaged
    # and providing info in their preferred order - not a loop.
    deltas_this_turn = state.metadata.get("deltas_applied_this_turn", []) if state.metadata else []
    core_fields_changed = [f for f in deltas_this_turn if f in CORE_FIELD_PRIORITY]
    if core_fields_changed:
        _debug(
            "Loop guard: user provided other core fields, not suppressing",
            field=field_name,
            core_fields_provided=core_fields_changed,
        )
        return False

    threshold = settings.loop_guard_threshold

    # Determine effective window size based on no-progress signal
    # Extended window (6) only activates if no progress for 2+ turns
    no_progress_turns = state.metadata.get("no_progress_turns", 0) if state.metadata else 0
    missing_fields_unchanged = (
        state.metadata.get("missing_fields_unchanged_turns", 0) if state.metadata else 0
    )

    if settings.loop_guard_require_no_progress_for_extended:
        # Use extended window only if: no progress AND missing fields unchanged for 2+ turns
        use_extended = (
            no_progress_turns >= settings.loop_guard_no_progress_turns
            and missing_fields_unchanged >= 2
        )
        window_size = (
            settings.loop_guard_extended_window_turns
            if use_extended
            else settings.loop_guard_window_turns
        )
    else:
        window_size = settings.loop_guard_window_turns

    # Count questions about this field within window
    recent_questions = state.loop_guard.get("recent_questions", []) if state.loop_guard else []
    questions_in_window = [
        q
        for q in recent_questions
        if q["field"] == field_name and q["turn"] >= state.turn_number - window_size
    ]

    is_loop = len(questions_in_window) >= threshold

    # Shadow audit: log would-trigger events for parameter tuning
    if settings.loop_guard_shadow_audit and is_loop:
        _debug(
            "Loop guard AUDIT (would-trigger)",
            field=field_name,
            count_in_window=len(questions_in_window),
            threshold=threshold,
            window_size=window_size,
            no_progress_turns=no_progress_turns,
            enforce_mode=settings.loop_guard_enabled and not settings.loop_guard_shadow_mode,
        )

    if is_loop:
        _debug(
            "Loop guard: loop detected",
            field=field_name,
            count_in_window=len(questions_in_window),
            threshold=threshold,
            window_size=window_size,
        )
        _increment_state_counter("loop_guard_trigger_count")

    return is_loop


def get_loop_guard_mitigation(state: "GraphState", field_name: str) -> Optional[str]:
    """
    Get the appropriate mitigation action for a loop on the given field.

    Returns the next mitigation action to try, escalating through the list:
    1. different_field - Ask about a different required field
    2. extractor_clarification - Run extractor focused on clarification
    3. specialist_preroute - Route to different specialist
    4. recovery_summary - Emit recovery summary

    SPECIAL HANDLING FOR DATE ERRORS:
    When field_name is "dates" and blocking date errors exist
    (DATE_AMBIGUOUS_YEAR, DATE_RANGE_INVALID), immediately escalate to
    dates_clarify template with year-specific suggestions instead of
    repeating the generic dates question.

    ROUTING INTERACTION FIX:
    If explicit specialist intent exists, prefer specialist_preroute over
    different_field to avoid masking routing bugs with loop guard.

    SAFETY GUARDS:
    - Cooldown: Skip mitigation if within cooldown period (forced_route_cooldown_until_turn)
    - Max triggers: Skip mitigation if triggers_this_convo >= max_triggers_per_convo

    Args:
        state: Current graph state
        field_name: The field that triggered the loop

    Returns:
        Mitigation action name, or None if in shadow mode or blocked by guards
    """
    # In shadow mode, just log but don't take action
    if settings.loop_guard_shadow_mode and not settings.loop_guard_enabled:
        _debug(
            "Loop guard (shadow): would mitigate",
            field=field_name,
            action="logged_only",
        )
        return None

    # =========================================================================
    # SAFETY GUARDS: Cooldown and Max Triggers
    # =========================================================================
    loop_guard = state.loop_guard or {}

    # Check cooldown: skip mitigation if within cooldown period
    cooldown_until = loop_guard.get("forced_route_cooldown_until_turn", 0)
    if state.turn_number < cooldown_until:
        _debug(
            "Loop guard: skipping mitigation (within cooldown)",
            field=field_name,
            current_turn=state.turn_number,
            cooldown_until=cooldown_until,
        )
        return None

    # Check max triggers: skip mitigation if already hit max for this conversation
    triggers_this_convo = loop_guard.get("triggers_this_convo", 0)
    if triggers_this_convo >= settings.loop_guard_max_triggers_per_convo:
        _debug(
            "Loop guard: max triggers reached, skipping mitigation",
            field=field_name,
            triggers_this_convo=triggers_this_convo,
            max_triggers=settings.loop_guard_max_triggers_per_convo,
        )
        return None

    # Increment triggers_this_convo and update cooldown for next mitigation
    loop_guard["triggers_this_convo"] = triggers_this_convo + 1
    loop_guard["forced_route_cooldown_until_turn"] = (
        state.turn_number + settings.loop_guard_forced_route_cooldown_turns
    )
    state.loop_guard = loop_guard

    # =========================================================================
    # SPECIAL HANDLING FOR DATE ERRORS
    # =========================================================================
    # When dates loop is detected and blocking date errors exist,
    # escalate immediately to date_clarify mode with year-specific suggestions
    if field_name == "dates":
        has_blocking_date_errors = False

        # Check for blocking date errors
        if state.errors:
            for err in state.errors:
                if isinstance(err, ErrorRecord):
                    if err.severity == "blocking" or err.code in DATE_BLOCKING_ERROR_CODES:
                        has_blocking_date_errors = True
                        break
                elif isinstance(err, NormalizationError) and err.code in DATE_BLOCKING_ERROR_CODES:
                    has_blocking_date_errors = True
                    break
                elif isinstance(err, str) and any(
                    code in err for code in DATE_BLOCKING_ERROR_CODES
                ):
                    has_blocking_date_errors = True
                    break

        # Also check metadata for date_clarify_mode
        if state.metadata.get("date_clarify_mode"):
            has_blocking_date_errors = True

        if has_blocking_date_errors:
            _debug(
                "Loop guard: date errors detected, escalating to dates_clarify",
                field=field_name,
                date_clarify_mode=state.metadata.get("date_clarify_mode"),
            )
            # Set date_clarify_mode to trigger special template
            state.metadata["date_clarify_mode"] = True
            _date_stats["dates_clarify_shown_count"] += 1

            # Update suggestions to year-specific options
            pending_range = state.metadata.get("pending_date_range", {})
            today = datetime.now(UTC).date()
            current_year = today.year
            next_year = current_year + 1

            # Try to extract month from pending dates
            start_date = pending_range.get("start_date", "")
            month_name = "December"  # Default
            if start_date:
                try:
                    dt = datetime.strptime(start_date, "%Y-%m-%d")
                    month_name = dt.strftime("%B")
                except ValueError:
                    pass

            # Override suggestions with year-specific options
            state.suggested_responses = [
                f"This {month_name} ({current_year})",
                f"Next {month_name} ({next_year})",
                f"{next_year}",
            ]

            # Return a special mitigation that signals dates_clarify
            return "dates_clarify"

    # Check for explicit specialist intent - prioritize specialist_preroute
    explicit_specialist_intent = (
        state.metadata.get("explicit_specialist_intent") if state.metadata else None
    )
    pre_core_mode = state.metadata.get("pre_core_mode") if state.metadata else False

    if explicit_specialist_intent or pre_core_mode:
        # When user has clear specialist intent, prefer routing to specialist
        # over switching to a different field (avoids masking routing issues)
        _debug(
            "Loop guard: explicit specialist intent detected, preferring specialist_preroute",
            field=field_name,
            intent=explicit_specialist_intent,
            pre_core_mode=pre_core_mode,
        )
        return "specialist_preroute"

    # Get previous mitigations for this field
    loop_guard = state.loop_guard or {}
    field_mitigations = loop_guard.get("field_mitigations", {})
    mitigation_index = field_mitigations.get(field_name, 0)

    # Check for consecutive loop triggers across any fields - escalate to recovery faster
    # After 2 consecutive loop triggers (any field), jump to recovery_summary
    consecutive_triggers = loop_guard.get("consecutive_loop_triggers", 0) + 1
    loop_guard["consecutive_loop_triggers"] = consecutive_triggers

    if consecutive_triggers >= 2:
        # Fast-track to recovery_summary after 2 consecutive loops
        mitigation_action = "recovery_summary"
        _debug(
            "Loop guard: fast-tracking to recovery_summary after consecutive triggers",
            field=field_name,
            consecutive_triggers=consecutive_triggers,
        )
    elif mitigation_index >= len(LOOP_GUARD_MITIGATION_ACTIONS):
        mitigation_action = LOOP_GUARD_MITIGATION_ACTIONS[-1]  # Stick with recovery
    else:
        mitigation_action = LOOP_GUARD_MITIGATION_ACTIONS[mitigation_index]

    # Record the mitigation
    if "field_mitigations" not in loop_guard:
        loop_guard["field_mitigations"] = {}
    loop_guard["field_mitigations"][field_name] = mitigation_index + 1
    state.loop_guard = loop_guard

    _debug(
        "Loop guard: applying mitigation",
        field=field_name,
        action=mitigation_action,
        escalation_level=mitigation_index,
        consecutive_triggers=consecutive_triggers,
    )

    return mitigation_action


def apply_loop_guard_mitigation(
    state: "GraphState",
    field_name: str,
    mitigation: str,
) -> "GraphState":
    """
    Apply a loop guard mitigation action to the state.

    Args:
        state: Current graph state
        field_name: The field that triggered the loop
        mitigation: The mitigation action to apply

    Returns:
        Modified state with mitigation applied
    """
    # v7 Final v5: Disable field-switch mitigations when plan is ready
    # Loop guard is for escaping deadlocks when missing required info;
    # it should not fire when the plan is complete.
    if state.metadata.get("readiness_pre", {}).get("ready_to_generate"):
        _debug(
            "LOOP_GUARD: skipped mitigation (ready_to_generate=True)",
            field=field_name,
            mitigation=mitigation,
        )
        return state

    if mitigation == "different_field":
        # Find a different required field to ask about
        state.metadata["loop_guard_skip_field"] = field_name
        # The required_fields node will check this and skip to another field

    elif mitigation == "extractor_clarification":
        # Force extractor to focus on clarification
        state.metadata["extractor_mode"] = "clarification"
        state.metadata["clarification_target_field"] = field_name

    elif mitigation == "specialist_preroute":
        # Force routing away from current specialist
        current_intent = state.metadata.get("last_intent")
        excluded = state.metadata.get("loop_guard_excluded_intents", [])
        if current_intent:
            excluded.append(current_intent)
        state.metadata["loop_guard_excluded_intents"] = excluded
        # Router will check this and route elsewhere

    elif mitigation == "recovery_summary":
        # Generate a recovery summary with known info
        trip_inputs = (
            state.trip_inputs.model_dump()
            if hasattr(state.trip_inputs, "model_dump")
            else dict(state.trip_inputs)
        )
        known_info = _summarize_trip_inputs_for_recovery(trip_inputs)
        state.last_summary = f"Current constraints:\n\n{known_info}"
        state.metadata["loop_guard_recovery_emitted"] = True
        # Skip further processing for this turn
        state.flags["short_circuit"] = True
        state.flags["short_circuit_response"] = state.last_summary

    return state


def check_and_apply_loop_guard(
    state: "GraphState",
    field_name: str,
) -> Tuple["GraphState", bool]:
    """
    Check for question loops and apply mitigation if needed.

    This is the main entry point for loop guard checks. Call this before
    asking a question about a field.

    Args:
        state: Current graph state
        field_name: Field we're about to ask about

    Returns:
        Tuple of (modified_state, should_skip_question)
        If should_skip_question is True, don't ask the original question
    """
    if not detect_question_loop(state, field_name):
        return state, False

    mitigation = get_loop_guard_mitigation(state, field_name)

    if mitigation is None:
        # Shadow mode - no action taken
        return state, False

    state = apply_loop_guard_mitigation(state, field_name, mitigation)

    # For recovery_summary, we should skip the question entirely
    should_skip = mitigation == "recovery_summary"

    return state, should_skip


# NOTE: Strategy expansion detection extracted in P4.
# If you need to modify it, edit: backend/app/planner/gates/checks/strategy.py


@dataclass
class StrategyPrediction:
    """Prediction of strategy node execution for SSE progress tracking."""

    will_execute: bool
    stage: int = 0  # 1 = outline, 2 = expansion
    tier: str = "outline"
    topic: str = ""
    max_tokens: int = 512
    estimated_duration_ms: int = 2000


def _predict_strategy_execution(
    state: "GraphState",
    user_text: str,
) -> Optional[StrategyPrediction]:
    """
    Predict if strategy node will execute and with what parameters.

    Used to emit SSE node_status events before graph execution for
    frontend progress tracking.

    Args:
        state: Current graph state (includes pending_strategy_expansion)
        user_text: User's message

    Returns:
        StrategyPrediction if strategy node will execute, None otherwise
    """
    text_lower = user_text.lower().strip()

    # Check for stage 2 expansion (user is expanding an existing strategy)
    if state.pending_strategy_expansion:
        expansion_result = is_strategy_expansion_request(user_text)
        if expansion_result.is_expansion:
            tier = expansion_result.tier or StrategyTier.SECTION
            tier_str = tier.value if isinstance(tier, StrategyTier) else str(tier)
            max_tokens = STRATEGY_TIER_MAX_TOKENS.get(tier, 768)
            # Full expansion takes longer (14s for FULL, 10s for SECTION)
            estimated_ms = 14000 if tier == StrategyTier.FULL else 10000
            return StrategyPrediction(
                will_execute=True,
                stage=2,
                tier=tier_str,
                topic=state.strategy_topic or "hiking",
                max_tokens=max_tokens,
                estimated_duration_ms=estimated_ms,
            )

    # Check for stage 0 or stage 1 (new strategy topic detected)
    # Stage 0: Initial value-first response (core fields may be missing) - 300 tokens
    # Stage 1: Outline generation (after stage 0 completed) - 512 tokens
    metadata = state.metadata or {}
    stage0_completed = metadata.get("strategy_stage0_completed", False)

    for topic, pattern in STRATEGY_TOPIC_PATTERNS.items():
        if pattern.search(text_lower):
            if stage0_completed:
                # Stage 1: Outline generation
                return StrategyPrediction(
                    will_execute=True,
                    stage=1,
                    tier="outline",
                    topic=topic,
                    max_tokens=512,
                    estimated_duration_ms=8000,  # 8 seconds for outline generation
                )
            else:
                # Stage 0: Value-first response
                return StrategyPrediction(
                    will_execute=True,
                    stage=0,
                    tier="outline",
                    topic=topic,
                    max_tokens=300,
                    estimated_duration_ms=6000,  # 6 seconds for initial response
                )

    # Also check intent keywords for broader matching
    for topic, keywords in STRATEGY_INTENT_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            if stage0_completed:
                # Stage 1: Outline generation
                return StrategyPrediction(
                    will_execute=True,
                    stage=1,
                    tier="outline",
                    topic=topic,
                    max_tokens=512,
                    estimated_duration_ms=8000,  # 8 seconds for outline generation
                )
            else:
                # Stage 0: Value-first response
                return StrategyPrediction(
                    will_execute=True,
                    stage=0,
                    tier="outline",
                    topic=topic,
                    max_tokens=300,
                    estimated_duration_ms=6000,  # 6 seconds for initial response
                )

    # Also check for generic adventure keywords that map to hiking
    # These are used in READY_NO_FIELDS gate for post-ready strategy triggers
    ADVENTURE_KEYWORDS = {"adventure", "activities", "things to do", "what can i do"}
    if any(kw in text_lower for kw in ADVENTURE_KEYWORDS):
        if stage0_completed:
            return StrategyPrediction(
                will_execute=True,
                stage=1,
                tier="outline",
                topic="hiking",  # Default adventure topic
                max_tokens=512,
                estimated_duration_ms=8000,
            )
        else:
            return StrategyPrediction(
                will_execute=True,
                stage=0,
                tier="outline",
                topic="hiking",  # Default adventure topic
                max_tokens=450,  # Matches stage0.py max_tokens
                estimated_duration_ms=6000,
            )

    return None


# =============================================================================
# Node Progress Configuration for SSE Progress Tracking
# =============================================================================
# Maps node names to human-readable labels and icon keys for frontend display.
# These are used when emitting node_status SSE events.
# =============================================================================

NODE_PROGRESS_CONFIG: dict[str, dict[str, str]] = {
    "required_fields_node": {
        "label": "Understanding your trip",
        "icon_key": "clipboard",
    },
    "flights_node": {
        "label": "Finding flights",
        "icon_key": "plane",
    },
    "hotels_node": {
        "label": "Searching hotels",
        "icon_key": "building",
    },
    "transport_node": {
        "label": "Planning transport",
        "icon_key": "car",
    },
    "activities_node": {
        "label": "Discovering activities",
        "icon_key": "map-pin",
    },
    "general_node": {
        "label": "Processing request",
        "icon_key": "globe",
    },
    "correction_node": {
        "label": "Adjusting plan",
        "icon_key": "alert-circle",
    },
    "response_polish": {
        "label": "Polishing response",
        "icon_key": "sparkles",
    },
}


def _get_node_progress_duration_ms(node_name: str) -> int:
    """Get the estimated duration in milliseconds for a node's progress bar."""
    duration_map = {
        "required_fields_node": settings.node_progress_required_fields_ms,
        "flights_node": settings.node_progress_flights_ms,
        "hotels_node": settings.node_progress_hotels_ms,
        "transport_node": settings.node_progress_transport_ms,
        "activities_node": settings.node_progress_activities_ms,
        "general_node": settings.node_progress_general_ms,
        "correction_node": settings.node_progress_correction_ms,
        "response_polish": settings.node_progress_response_polish_ms,
    }
    return duration_map.get(node_name, 4000)  # Default 4s


@dataclass
class NodeExecutionPrediction:
    """Prediction of node execution for SSE progress tracking."""

    will_execute: bool
    node: str  # Node name (e.g., "flights_node")
    label: str  # Human-readable label for UI
    icon_key: str  # Frontend icon key
    estimated_duration_ms: int = 4000


def _predict_node_execution(
    state: "GraphState",
    user_text: str,
) -> Optional[NodeExecutionPrediction]:
    """
    Predict which LLM-based node will execute for SSE progress tracking.

    This function is called before graph execution to emit node_status events
    for frontend progress bars. It uses the same routing logic as the graph
    to predict which node will handle the request.

    Args:
        state: Current graph state
        user_text: User's message

    Returns:
        NodeExecutionPrediction if an LLM node will execute, None otherwise
    """
    # Skip if strategy will execute (handled separately)
    strategy_pred = _predict_strategy_execution(state, user_text)
    if strategy_pred and strategy_pred.will_execute:
        return None

    # Check if we have intent from previous extraction or can predict it
    intent = state.intent

    # If no intent yet, try to predict from user text keywords
    if not intent:
        text_lower = user_text.lower().strip()

        # Simple keyword matching for common intents
        # Note: Keywords should be specific enough to avoid false positives.
        # e.g., "stay" alone would match "during my stay" which is not about hotels.
        if any(
            kw in text_lower
            for kw in ["flight", "flights", "fly", "airline", "airport", "book flights"]
        ):
            intent = "flights"
        elif any(
            kw in text_lower
            for kw in [
                "hotel",
                "hotels",
                "accommodation",
                "hostel",
                "airbnb",
                "lodging",
                "where to stay",
                "book hotel",
            ]
        ):
            intent = "hotels"
        elif any(
            kw in text_lower
            for kw in [
                "car rental",
                "rent a car",
                "train",
                "bus",
                "taxi",
                "uber",
                "shuttle",
                "ground transport",
            ]
        ):
            intent = "transport"
        elif any(
            kw in text_lower
            for kw in ["activity", "activities", "things to do", "attractions", "sightseeing"]
        ):
            intent = "activities"
        elif any(
            kw in text_lower for kw in ["change", "modify", "update", "correct", "fix", "wrong"]
        ):
            intent = "correction"

    # Map intent to specialist node
    intent_to_node = {
        "flights": "flights_node",
        "hotels": "hotels_node",
        "transport": "transport_node",
        "activities": "activities_node",
        "general": "general_node",
        "correction": "correction_node",
    }

    predicted_node = intent_to_node.get(intent)

    # Check if this node has progress config
    if predicted_node and predicted_node in NODE_PROGRESS_CONFIG:
        config = NODE_PROGRESS_CONFIG[predicted_node]
        return NodeExecutionPrediction(
            will_execute=True,
            node=predicted_node,
            label=config["label"],
            icon_key=config["icon_key"],
            estimated_duration_ms=_get_node_progress_duration_ms(predicted_node),
        )

    # Check for required_fields (when core fields are incomplete)
    # This happens when destination, dates, or other core fields are missing
    trip_inputs = state.trip_inputs
    if trip_inputs:
        has_destination = bool(trip_inputs.destinations)
        has_dates = bool(trip_inputs.start_date and trip_inputs.end_date)

        # If missing core fields and no clear specialist intent, likely required_fields
        if (not has_destination or not has_dates) and not predicted_node:
            config = NODE_PROGRESS_CONFIG["required_fields_node"]
            return NodeExecutionPrediction(
                will_execute=True,
                node="required_fields_node",
                label=config["label"],
                icon_key=config["icon_key"],
                estimated_duration_ms=_get_node_progress_duration_ms("required_fields_node"),
            )

    return None


TRIP_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "destinations": {"type": "array", "items": {"type": "string"}},
        "origin": {"type": ["string", "null"]},
        "start_date": {"type": ["string", "null"]},
        "end_date": {"type": ["string", "null"]},
        "adults": {"type": ["integer", "null"], "minimum": 1},
        "children": {"type": ["integer", "null"], "minimum": 0},
        "requires_assistance": {"type": ["boolean", "null"]},
        "budget": {"type": ["number", "null"]},
        "currency": {"type": ["string", "null"]},
    },
    "additionalProperties": True,
}
TRIP_VALIDATOR = Draft7Validator(TRIP_JSON_SCHEMA)

# NOTE: ISO pattern moved to pattern_matching.py as ISO_DATE_PATTERN (V26 extraction)
# Backwards compatibility alias:
ISO = ISO_DATE_PATTERN
PROMPTS_DIR = Path(__file__).parent / "prompts"
INVALID_JSON_HINT = (
    "\n\nIMPORTANT: Your previous response was not valid JSON. "
    "Please respond with ONLY valid JSON."
)

# =============================================================================
# PHASE 5: STRATEGY STAGE 1 OPTIMIZATION
# =============================================================================
# Strip verbose includes from Stage 1 prompts to reduce token count.
# Also add budget/season sanity checklist to prevent correction triggers.

# Patterns to strip from Stage 1 prompts (content from these includes is verbose)
_STAGE1_STRIP_PATTERNS = [
    # _scope_specialist.txt content (lines 1-17, ~150 tokens)
    (
        r"={10,}\nSCOPE: SPECIALIST ONLY\n={10,}.*?YOUR ROLE:.*?"
        r"Trust pre-extracted values from the extractor\n"
    ),
    # _markdown_rules.txt content (~120 tokens)
    (r"={10,}\nMARKDOWN FORMATTING\n={10,}.*?" r"Don't over-format short responses\n"),
]

# Budget/season sanity checklist for Stage 1 (~50 tokens, saves ~1000 by avoiding correction)
_STAGE1_SANITY_CHECKLIST = """

STAGE 1 SANITY CHECKLIST (flag issues immediately, don't plan around them):
- Season mismatch: skiing in June-August, beach in Nordic winter
- Budget impossibility: luxury on <$100/day, multi-week on <$500 total
- Date impossibility: start_date in past, end_date before start_date
- Geographic impossibility: landlocked country for diving/sailing
If ANY apply: set "infeasibility_warning" in response and explain briefly.
"""


def _strip_stage1_includes(prompt: str) -> str:
    """
    Strip verbose include content from prompt for Stage 1 strategy.

    Stage 1 only needs shortlist + skeleton - not full formatting rules
    or scope reminders. This saves ~150-270 tokens per call.

    Args:
        prompt: Full prompt with all includes rendered

    Returns:
        Stripped prompt with verbose sections removed
    """
    import re as _re

    result = prompt
    for pattern in _STAGE1_STRIP_PATTERNS:
        result = _re.sub(pattern, "", result, flags=_re.DOTALL | _re.IGNORECASE)
    return result


# -----------------------
# Strategy registry (plug-in)
# -----------------------
STRATEGY_REGISTRY: Dict[str, str] = {}  # topic -> prompt filename (without .txt)


def register_strategy(topic: str, prompt_name: str):
    STRATEGY_REGISTRY[topic] = prompt_name


# Example registrations (create corresponding prompts/*.txt files)
register_strategy("boating", "strategy_boating")
register_strategy("hiking", "strategy_hiking")
register_strategy("diving", "strategy_diving")
register_strategy("skiing", "strategy_skiing")
register_strategy("cycling", "strategy_cycling")
register_strategy("general", "strategy_general")  # Fallback for trips without specific activities


# -----------------------
# Prompt & LLM helpers
# -----------------------

# Jinja2 environment for prompt templating with {% include %} support
_JINJA_ENV = Environment(
    loader=FileSystemLoader(PROMPTS_DIR),
    autoescape=False,  # Prompts are plain text, not HTML
    keep_trailing_newline=True,
)


@lru_cache(maxsize=32)
def _load_prompt_cached(name: str) -> str:
    """Internal cached prompt loader using Jinja2 for {% include %} support."""
    template = _JINJA_ENV.get_template(f"{name}.txt")
    return template.render()


# Track which prompts have been loaded (for cache hit logging)
_PROMPTS_LOADED: set[str] = set()


def load_prompt(name: str) -> str:
    """Load prompt template from file with LRU caching and debug logging.

    Supports Jinja2 {% include %} directives for shared blocks.
    Example: {% include "_never_invent.txt" %}
    """
    result = _load_prompt_cached(name)
    if name in _PROMPTS_LOADED:
        _debug_cache_hit("load_prompt", name, value_preview=result)
    else:
        _PROMPTS_LOADED.add(name)
    return result


def clear_prompt_cache() -> None:
    """Clear the prompt cache. Useful for development/hot-reloading."""
    _load_prompt_cached.cache_clear()
    _PROMPTS_LOADED.clear()
    _JINJA_ENV.cache.clear() if hasattr(_JINJA_ENV, "cache") and _JINJA_ENV.cache else None


# =============================================================================
# PHASE 6: CONDITIONAL INCLUDE STRIPPING FOR SPECIALISTS
# =============================================================================
# Strip _scope_specialist.txt and _never_invent.txt when gates already verified
# domain. Keep _json_output.txt always. Saves ~138w (~184 tokens) per call.

# Include content markers for stripping (approximate content patterns)
_SCOPE_SPECIALIST_MARKER = "IMPORTANT"  # First word of _scope_specialist.txt
_NEVER_INVENT_MARKER = "Never invent"  # Key phrase in _never_invent.txt

# Cache for stripped prompts
_STRIPPED_PROMPTS_CACHE: Dict[str, str] = {}


def _strip_specialist_includes(
    prompt: str,
    gate_verified: bool,
    is_follow_up: bool,
) -> str:
    """
    Phase 6: Strip unnecessary includes from specialist prompts.

    Args:
        prompt: The loaded prompt text (with includes already rendered)
        gate_verified: True if routing gate already verified domain
        is_follow_up: True if user is answering a question (low invention risk)

    Returns:
        Prompt with unnecessary includes stripped
    """
    if not gate_verified and not is_follow_up:
        return prompt

    stripped = prompt
    tokens_saved = 0

    # Strip _scope_specialist content when gate verified domain
    # This ~100 word block enforces domain scope, but gate already verified it
    if gate_verified:
        # Find and remove the scope specialist block
        # Pattern: "IMPORTANT" block that ends before next major section
        scope_patterns = [
            # Pattern 1: IMPORTANT block
            r"IMPORTANT[:\s].*?(?=\n\n[A-Z]|\n\n#|\Z)",
            # Pattern 2: "Stay focused on" directive
            r"Stay focused on \w+ only\..*?(?=\n\n|\Z)",
            # Pattern 3: Domain-specific warning
            r"Do NOT provide .* recommendations\..*?(?=\n\n|\Z)",
        ]
        for pattern in scope_patterns:
            match = re.search(pattern, stripped, re.DOTALL | re.IGNORECASE)
            if match:
                before_len = len(stripped)
                stripped = stripped[: match.start()] + stripped[match.end() :]
                tokens_saved += (before_len - len(stripped)) // 4
                break

    # Strip _never_invent content when user is answering a question
    # This ~38 word block prevents hallucination, but low risk for follow-ups
    if is_follow_up:
        never_invent_pattern = r"Never invent.*?(?=\n\n|\Z)"
        match = re.search(never_invent_pattern, stripped, re.DOTALL | re.IGNORECASE)
        if match:
            before_len = len(stripped)
            stripped = stripped[: match.start()] + stripped[match.end() :]
            tokens_saved += (before_len - len(stripped)) // 4

    if tokens_saved > 0:
        _debug(
            "🔪 INCLUDE_STRIP: stripped includes",
            gate_verified=gate_verified,
            is_follow_up=is_follow_up,
            tokens_saved=tokens_saved,
        )

    return stripped.strip()


def load_specialist_prompt(
    name: str,
    state: "GraphState",
) -> str:
    """
    Load specialist prompt with conditional include stripping.

    Phase 6: Strips _scope_specialist and _never_invent when safe:
    - _scope_specialist: Omit when routing gate verified domain
    - _never_invent: Omit for follow-up turns (user answering questions)
    - _json_output: Always keep (prevents malformed responses)

    Args:
        name: Prompt name (flights, hotels, transport, activities)
        state: Current graph state for context

    Returns:
        Prompt text, possibly with includes stripped
    """
    # Load base prompt with all includes
    prompt = load_prompt(name)

    # Determine if we can strip includes
    metadata = state.metadata or {}

    # Gate verified = routing was done by QUESTION_KEYWORD gate
    gate_verified = metadata.get("router_bypassed", False) and metadata.get("first_gate_fired") in (
        "QUESTION_KEYWORD",
        GatePrecedence.QUESTION_KEYWORD.name,
    )

    # Follow-up = user is answering a question (low hallucination risk)
    question_target = state.question_target or metadata.get("last_question_field")
    is_follow_up = question_target is not None

    # Only strip for domain specialists
    _STRIPPABLE_SPECIALISTS = {"flights", "hotels", "transport", "activities"}
    if name not in _STRIPPABLE_SPECIALISTS:
        return prompt

    # Apply stripping
    stripped = _strip_specialist_includes(prompt, gate_verified, is_follow_up)

    return stripped


# =============================================================================
# REQUIRED FIELDS TEMPLATES (Token-saving template-based responses)
# =============================================================================
# Cache for the loaded templates
_REQUIRED_FIELDS_TEMPLATES: Optional[Dict[str, Any]] = None


def _load_required_fields_templates() -> Dict[str, Any]:
    """Load required fields templates from JSON file with caching."""
    global _REQUIRED_FIELDS_TEMPLATES
    if _REQUIRED_FIELDS_TEMPLATES is not None:
        return _REQUIRED_FIELDS_TEMPLATES

    template_path = Path(__file__).parent / "prompts" / "required_fields_templates.json"
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            _REQUIRED_FIELDS_TEMPLATES = json.load(f)
        _debug("Loaded required_fields_templates.json")
    except Exception as e:
        _debug_error("Failed to load required_fields_templates.json", error=str(e))
        _REQUIRED_FIELDS_TEMPLATES = {}

    return _REQUIRED_FIELDS_TEMPLATES


def validate_template_coverage() -> Dict[str, Any]:
    """
    Validate that templates cover all core fields with sufficient suggestions.

    MVP Hardening: This should be called at startup to fail fast if templates
    are incomplete.

    Returns:
        Dict with validation results:
        - valid: bool
        - missing_fields: List[str] - fields without templates
        - insufficient_suggestions: Dict[str, int] - fields with <4 suggestions
        - errors: List[str] - validation error messages
    """
    templates = _load_required_fields_templates()

    result = {
        "valid": True,
        "missing_fields": [],
        "insufficient_suggestions": {},
        "errors": [],
    }

    # Map CORE_FIELD_PRIORITY to template keys
    # Note: start_date -> dates, adults -> travelers in templates
    field_to_template_key = {
        "destinations": "destinations",
        "start_date": "dates",
        "end_date": "dates",  # shares with start_date
        "origin": "origin",
        "adults": "travelers",
        "budget": "budget",
    }

    min_suggestions = 3  # Require at least 3 suggestions per field

    for core_field in CORE_FIELD_PRIORITY:
        template_key = field_to_template_key.get(core_field, core_field)

        if template_key not in templates:
            result["missing_fields"].append(core_field)
            result["valid"] = False
            result["errors"].append(
                f"Missing template for core field: {core_field} (template key: {template_key})"
            )
            continue

        field_template = templates[template_key]

        # Check questions exist
        questions = field_template.get("questions", [])
        if not questions:
            result["errors"].append(f"No questions defined for {field}")
            result["valid"] = False

        # Check suggestions exist and have minimum count
        suggestions_map = field_template.get("suggestions", {})
        default_suggestions = suggestions_map.get("default", [])

        if len(default_suggestions) < min_suggestions:
            result["insufficient_suggestions"][core_field] = len(default_suggestions)
            # Don't mark as invalid - we have fallbacks
            result["errors"].append(
                (
                    f"Field {core_field} has only {len(default_suggestions)} suggestions "
                    f"(recommend {min_suggestions}+)"
                )
            )

    if result["valid"]:
        _debug("Template coverage validation passed")
    else:
        _debug_error(
            "Template coverage validation failed",
            missing=result["missing_fields"],
            errors=result["errors"][:3],
        )

    return result


def _get_template_response(
    question_target: str,
    strategy_topic: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get a template-based response for a missing field.

    Returns a dict with:
        - question: str
        - suggestions: List[str]

    Returns None if no template available for the question_target.
    """
    templates = _load_required_fields_templates()
    field_templates = templates.get(question_target)

    if not field_templates:
        _debug(f"No template for question_target: {question_target}")
        return None

    # Pick a random question for variety
    questions = field_templates.get("questions", [])
    if not questions:
        return None
    question = _random_module.choice(questions)

    # Get suggestions - prefer strategy-specific if available
    suggestions_map = field_templates.get("suggestions", {})
    if strategy_topic and strategy_topic in suggestions_map:
        suggestions = suggestions_map[strategy_topic]
    else:
        suggestions = suggestions_map.get("default", [])

    return {
        "question": question,
        "suggestions": suggestions[:3],  # Max 3 suggestions
    }


def _is_simple_missing_field(
    question_target: str,
    state: "GraphState",
) -> bool:
    """
    Check if the missing field is simple (no ambiguity) and can use template.

    Returns False if there's ambiguity that requires LLM:
    - Multiple destinations detected but need disambiguation
    - Vague date like "next spring" that needs clarification
    - Conflicting origin (user mentioned multiple places)
    - Typo suggestions that need confirmation

    Returns True if we can use a simple template question.
    """
    extraction_conf = state.metadata.get("extraction_confidence", {})

    # If there are typo suggestions, we need LLM to ask about them
    if extraction_conf.get("typo_suggestions"):
        _debug("Ambiguity detected: typo_suggestions present")
        return False

    # If confidence is low, we might need LLM for clarification
    if extraction_conf.get("level") == "low":
        _debug("Ambiguity detected: low extraction confidence")
        return False

    # Check for specific ambiguity reasons
    low_confidence_reasons = extraction_conf.get("low_confidence_reasons") or []
    ambiguity_keywords = ["ambiguous", "unclear", "multiple", "conflict", "vague"]
    for reason in low_confidence_reasons:
        if any(kw in reason.lower() for kw in ambiguity_keywords):
            _debug(f"Ambiguity detected: {reason}")
            return False

    # Simple case - no ambiguity detected
    return True


# Model size to actual model name mapping
_MODEL_MAP = {
    "small": settings.openai_small_model,
    "medium": settings.openai_medium_model,
    "large": settings.openai_plan_model,
}

# v6: Call-site token accounting
_llm_call_log: List[Dict[str, Any]] = []  # Ring buffer for recent calls


def _log_llm_call(
    node_name: str,
    mode: str,
    prompt_hash: str,
    tokens_in: int,
    tokens_out: int,
    model: str,
    request_id: Optional[str] = None,
    cache_hit: bool = False,
    suppressed_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Log an LLM call at the call site for v6 observability.

    Returns the log entry for immediate use.
    """
    entry = {
        "timestamp": time.time(),
        "node_name": node_name,
        "mode": mode,
        "prompt_hash": prompt_hash[:16],
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "model": model,
        "request_id": request_id or uuid4().hex[:8],
        "cache_hit": cache_hit,
        "suppressed_reason": suppressed_reason,
    }

    # Ring buffer: keep last 100 calls
    while len(_llm_call_log) >= 100:
        _llm_call_log.pop(0)
    _llm_call_log.append(entry)

    _debug(
        "LLM_CALL_SITE",
        node=node_name,
        mode=mode,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cache_hit=cache_hit,
        suppressed=suppressed_reason,
    )

    return entry


def emit_turn_accounting(state: "GraphState") -> Dict[str, Any]:
    """
    Emit structured accounting blob at turn exit.

    Aggregates call-site logs into a single turn summary.
    """
    # Gather LLM calls from metadata
    llm_calls = state.metadata.get("llm_calls_this_turn", 0)
    llm_nodes = state.metadata.get("llm_nodes_called_this_turn", [])
    node_tokens = state.metadata.get("node_tokens", {})
    blocked_reasons = state.metadata.get("llm_call_blocked_reason", {})

    # Gather cache stats
    cache_hits = {
        "required_fields": state.metadata.get("required_fields_cache_hit", False),
        "router": state.metadata.get("router_cache_hit", False),
        "extractor": state.metadata.get("extractor_cache_hit", False),
    }

    cache_discards = state.metadata.get("cache_discards", {})

    accounting = {
        "llm_calls_this_turn": llm_calls,
        "llm_nodes_called_this_turn": llm_nodes,
        "node_tokens": node_tokens,
        "cache_hits": cache_hits,
        "cache_discards": cache_discards,
        "llm_suppressed_reasons": blocked_reasons,
        "parse_provenance_final": state.metadata.get("parse_provenance", "unknown"),
        "parse_provenance_source_node": state.metadata.get("parse_provenance_source_node"),
        "response_generation_provenance": state.metadata.get(
            "response_generation_provenance", "unknown"
        ),
        "response_writer_node": state.metadata.get("response_writer_node"),
    }

    _debug("TURN_ACCOUNTING", **accounting)

    return accounting


def get_llm_call_log() -> List[Dict[str, Any]]:
    """Get recent LLM call log entries for debugging."""
    return list(_llm_call_log)


async def call_llm(
    model: str,
    prompt: str,
    max_tokens: int = 512,
    temperature: float = 0.2,
    history: Optional[List[Dict[str, str]]] = None,
    user_message: Optional[str] = None,
    top_p: Optional[float] = None,
    max_retries: int = _PLAN_MAX_RETRIES,
) -> str:
    """
    Call the LLM provider using AsyncOpenAI. Returns a string (JSON text).

    Uses proper message structure with system prompt + history + user message,
    matching plan.py's approach for better context handling.
    Includes exponential backoff retry for 429/5xx errors (matching plan.py).

    Args:
        model: Model size identifier ("small", "medium", "large").
        prompt: The system prompt to send.
        max_tokens: Maximum tokens in response.
        temperature: Sampling temperature.
        history: Optional list of {role, content} dicts for conversation history.
        user_message: Optional current user message (appended after history).
        top_p: Optional nucleus sampling threshold (used for GPT-4 models).
        max_retries: Maximum retry attempts for transient errors.

    Returns:
        str: LLM response text.
    """
    from app.config import get_async_openai_client

    client = get_async_openai_client()
    if client is None:
        raise RuntimeError("OpenAI client is not configured")

    model_name = _MODEL_MAP.get(model, model)

    # Build messages array - same structure as plan.py
    messages: List[Dict[str, str]] = [{"role": "system", "content": prompt}]

    # Add history as separate messages (not in prompt text)
    if history:
        for msg in history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

    # Add current user message
    if user_message:
        messages.append({"role": "user", "content": user_message})

    # Build params matching plan.py's model-specific logic
    params: Dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }

    # Optional seed for reproducibility
    if settings.openai_plan_seed is not None:
        params["seed"] = settings.openai_plan_seed

    # GPT-4 models: use max_tokens, temperature, top_p
    # Other models: use max_completion_tokens
    if "gpt-4" in model_name.lower():
        params["max_tokens"] = max_tokens
        params["temperature"] = temperature
        if top_p is not None:
            params["top_p"] = top_p
    else:
        params["max_completion_tokens"] = max_tokens

    # Retry logic with exponential backoff for 429/5xx errors (matching plan.py)
    backoff = 0.5
    last_error: Optional[Exception] = None

    for attempt in range(max(1, max_retries)):
        try:
            response = await client.chat.completions.create(**params)
            content = response.choices[0].message.content or ""
            return content
        except Exception as exc:
            last_error = exc
            status_code = getattr(exc, "status_code", None) or getattr(exc, "status", None)
            # Retry on rate limit (429) or server errors (5xx)
            if attempt < max_retries - 1 and (
                status_code == 429 or (isinstance(status_code, int) and status_code >= 500)
            ):
                _debug_error(
                    f"LLM call failed (attempt {attempt + 1}), retrying...", error=str(exc)
                )
                await asyncio.sleep(backoff)
                backoff *= 2
                continue
            raise

    raise last_error or RuntimeError("LLM call failed after retries")


async def call_llm_with_timeout(
    model: str,
    prompt: str,
    timeout_seconds: float,
    max_tokens: int = 512,
    temperature: float = 0.2,
    history: Optional[List[Dict[str, str]]] = None,
    user_message: Optional[str] = None,
    top_p: Optional[float] = None,
    max_retries: int = _PLAN_MAX_RETRIES,
) -> str:
    """
    Call LLM with a timeout using asyncio.wait_for. Raises TimeoutError if the call takes too long.

    Args:
        model: Model identifier.
        prompt: The system prompt to send.
        timeout_seconds: Maximum time to wait for response.
        max_tokens: Maximum tokens in response.
        temperature: Sampling temperature.
        history: Optional list of {role, content} dicts for conversation history.
        user_message: Optional current user message (appended after history).
        top_p: Optional nucleus sampling threshold.
        max_retries: Maximum retry attempts for transient errors.

    Returns:
        str: LLM response text.

    Raises:
        TimeoutError: If the call exceeds timeout_seconds.
        Exception: Any exception from the underlying LLM call.
    """
    try:
        return await asyncio.wait_for(
            call_llm(
                model, prompt, max_tokens, temperature, history, user_message, top_p, max_retries
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        raise TimeoutError(f"LLM call timed out after {timeout_seconds}s") from None


# =============================================================================
# STREAMING LLM SUPPORT
# =============================================================================
# Simulated streaming parameters (hybrid timing for natural LLM-like flow)
# Fast start, gradual deceleration mimics real LLM token generation patterns
# Note: We stream word-by-word (like real LLM tokens) not char-by-char
# Uses centralized streaming params from streaming.py for consistency
_STREAM_BASE_DELAY_MS = STREAMING_PARAMS["base_delay_ms"]  # Starting delay per token (fast burst)
_STREAM_MAX_DELAY_MS = STREAMING_PARAMS[
    "max_delay_ms"
]  # Maximum delay per token (deceleration cap)
_STREAM_ACCEL_FACTOR = 0.015  # How quickly delay increases per token (not in STREAMING_PARAMS)
_STREAM_JITTER_MS = STREAMING_PARAMS["jitter_ms"]  # Random variance for organic feel


async def call_llm_streaming(
    model: str,
    prompt: str,
    max_tokens: int = 512,
    temperature: float = 0.2,
    history: Optional[List[Dict[str, str]]] = None,
    user_message: Optional[str] = None,
    top_p: Optional[float] = None,
):
    """
    Call the LLM with streaming enabled. Yields tokens as they arrive.

    This is used for response_polish and other text-only outputs where
    we want to stream tokens directly to the frontend via SSE.

    Args:
        model: Model size identifier ("small", "medium", "large").
        prompt: The system prompt to send.
        max_tokens: Maximum tokens in response.
        temperature: Sampling temperature.
        history: Optional list of {role, content} dicts for conversation history.
        user_message: Optional current user message (appended after history).
        top_p: Optional nucleus sampling threshold.

    Yields:
        str: Token chunks as they arrive from the LLM.
    """

    from app.config import get_async_openai_client

    client = get_async_openai_client()
    if client is None:
        raise RuntimeError("OpenAI client is not configured")

    model_name = _MODEL_MAP.get(model, model)

    # Build messages array - same structure as call_llm
    messages: List[Dict[str, str]] = [{"role": "system", "content": prompt}]

    if history:
        for msg in history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

    if user_message:
        messages.append({"role": "user", "content": user_message})

    # Build params - note: no response_format for streaming plain text
    params: Dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "stream": True,
    }

    # Optional seed for reproducibility
    if settings.openai_plan_seed is not None:
        params["seed"] = settings.openai_plan_seed

    # GPT-4 models: use max_tokens, temperature, top_p
    if "gpt-4" in model_name.lower():
        params["max_tokens"] = max_tokens
        params["temperature"] = temperature
        if top_p is not None:
            params["top_p"] = top_p
    else:
        params["max_completion_tokens"] = max_tokens

    async for chunk in await client.chat.completions.create(**params):
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


async def simulate_streaming(text: str):
    """
    Simulate streaming for code-generated messages with hybrid timing.

    Uses a fast-start, gradual-deceleration pattern that mimics real LLM
    token generation. Streams word-by-word (like real LLM tokens) for
    faster delivery while maintaining natural pacing.

    Timing pattern:
    - First ~20 tokens: ~15-20ms/token (fast burst)
    - Mid section: gradual slowdown to ~30-35ms/token
    - Random jitter ±8ms prevents robotic feel

    Args:
        text: The complete text to simulate streaming for.

    Yields:
        str: Tokens (words/punctuation) with natural variable delay.
    """
    import random
    import re

    # Split into tokens: words, punctuation, and whitespace
    # This matches how real LLMs tokenize text
    tokens = re.findall(r"\S+|\s+", text)
    total_tokens = len(tokens)

    for i, token in enumerate(tokens):
        # Progress through text (0.0 to 1.0)
        progress = i / max(total_tokens, 1)

        # Base delay increases with progress (fast start, slower end)
        base_delay = _STREAM_BASE_DELAY_MS + (
            (_STREAM_MAX_DELAY_MS - _STREAM_BASE_DELAY_MS) * progress * _STREAM_ACCEL_FACTOR * 100
        )
        base_delay = min(base_delay, _STREAM_MAX_DELAY_MS)

        # Add jitter for organic feel
        jitter = random.uniform(-_STREAM_JITTER_MS, _STREAM_JITTER_MS)
        delay_ms = max(8, base_delay + jitter)  # Floor at 8ms

        yield token
        await asyncio.sleep(delay_ms / 1000.0)


# Fast streaming parameters for LLM responses (no artificial delays)
_FAST_STREAM_CHUNK_SIZE = 1500  # ~1.5KB chunks for fast delivery


async def fast_stream_buffered(text: str):
    """
    Fast streaming for LLM responses that are already buffered.

    When provenance is 'llm' but we have the complete text (e.g., from
    strategy_stage0), emit in large chunks without artificial delays.
    This prevents 15s timeout issues with longer responses.

    Args:
        text: The complete text to stream quickly.

    Yields:
        str: Large text chunks with minimal delay.
    """
    # Emit in large chunks for fast delivery
    for i in range(0, len(text), _FAST_STREAM_CHUNK_SIZE):
        chunk = text[i : i + _FAST_STREAM_CHUNK_SIZE]
        yield chunk
        # Minimal yield point for async context switching, no artificial delay
        await asyncio.sleep(0)


# =============================================================================
# PR-D: JSON UTILITIES MOVED TO graph_plan_utils.py
# =============================================================================
# The following functions have been extracted to app/graph_plan_utils.py:
# - _truncate_to_balanced_json() -> truncate_to_balanced_json()
# - jloads_safe() (unchanged name)
# - _extract_message_from_malformed_json() -> extract_message_from_malformed_json()
#
# They are imported at the top of this file for backwards compatibility.
# See: from app.graph_plan_utils import jloads_safe, ...


def ti_short(ti: TripInputs) -> Dict[str, Any]:
    """Backward-compatible wrapper - delegates to node_utils.ti_short."""
    return _ti_short_impl(ti)


# =============================================================================
# STATE VIEW BUILDER
# =============================================================================
# Provides minimal state views for different node types to reduce token usage.
# Instead of passing full trip_inputs (~50+ fields), each node gets only what it needs.


class StateViewBuilder:
    """
    Builds minimal state views for LLM prompts to reduce token usage.

    Each node type gets a tailored view containing only the fields it needs:
    - Router: core fields + flags for intent classification
    - Required fields: core fields + missing fields + context for questions
    - Specialists: core fields (read-only) + their specific settings
    - Strategy: destinations + dates + activity categories + strategy settings
    """

    @staticmethod
    def for_router(state: "GraphState") -> Dict[str, Any]:
        """
        Minimal view for router node (~5-10 fields instead of ~50).
        Router only needs to classify intent, not full trip details.
        """
        ti = state.trip_inputs
        view = {
            "destinations": ti.destinations or [],
            "origin": ti.origin,
            "start_date": ti.start_date,
            "has_dates": bool(ti.start_date),
            "has_budget": bool(ti.budget),
            "has_travelers": bool(ti.adults),
            "activity_categories": ti.activity_settings.get("categories", []),
        }
        _debug(
            "StateView:router",
            field_count=len([v for v in view.values() if v]),
            view_keys=list(view.keys()),
        )
        return view

    @staticmethod
    def for_required_fields(state: "GraphState") -> Dict[str, Any]:
        """
        Minimal view for required_fields node (~10 fields).
        Only needs core fields and context for asking questions.
        """
        ti = state.trip_inputs
        view = {
            "destinations": ti.destinations or [],
            "origin": ti.origin,
            "start_date": ti.start_date,
            "end_date": ti.end_date,
            "adults": ti.adults,
            "budget": ti.budget,
            "currency": ti.currency,
        }
        _debug(
            "StateView:required_fields",
            field_count=len([v for v in view.values() if v]),
        )
        return view

    @staticmethod
    def for_specialist(state: "GraphState", specialist_type: str) -> Dict[str, Any]:
        """
        Minimal view for domain specialists (flights, hotels, transport, activities).
        Core fields (read-only) + their specific settings block.
        """
        ti = state.trip_inputs

        # Core fields all specialists need (read-only context)
        view = {
            "destinations": ti.destinations or [],
            "origin": ti.origin,
            "start_date": ti.start_date,
            "end_date": ti.end_date,
            "adults": ti.adults,
            "children": ti.children,
            "budget": ti.budget,
        }

        # Add specialist-specific settings
        if specialist_type == "flights":
            view["flight_settings"] = ti.flight_settings or {}
        elif specialist_type == "hotels":
            view["hotel_settings"] = ti.hotel_settings or {}
        elif specialist_type == "transport":
            view["transport_settings"] = ti.transport_settings or {}
        elif specialist_type == "activities":
            view["activity_settings"] = ti.activity_settings or {}

        _debug(
            f"StateView:{specialist_type}",
            field_count=len([v for v in view.values() if v]),
        )
        return view

    @staticmethod
    def for_strategy(state: "GraphState") -> Dict[str, Any]:
        """
        Minimal view for strategy node.
        Destinations + dates + budget + travelers + activity context.
        V36: Added budget, duration for richer trip context in responses.
        """
        ti = state.trip_inputs

        # Calculate duration if both dates are set
        duration_days = None
        if ti.start_date and ti.end_date:
            try:
                from datetime import datetime as dt

                start = dt.fromisoformat(ti.start_date)
                end = dt.fromisoformat(ti.end_date)
                duration_days = (end - start).days + 1  # Inclusive
            except (ValueError, TypeError):
                pass

        view = {
            "destinations": ti.destinations or [],
            "start_date": ti.start_date,
            "end_date": ti.end_date,
            "duration_days": duration_days,
            "adults": ti.adults,
            "children": ti.children,
            "budget": ti.budget,
            "currency": ti.currency or "USD",
            "activity_categories": ti.activity_settings.get("categories", []),
            "strategy_settings": ti.strategy_settings or {},
        }
        _debug(
            "StateView:strategy",
            field_count=len([v for v in view.values() if v]),
        )
        return view

    @staticmethod
    def for_correction(state: "GraphState") -> Dict[str, Any]:
        """
        Minimal view for correction node.
        Core fields only - infeasibility context is in user_text.
        """
        ti = state.trip_inputs
        view = {
            "destinations": ti.destinations or [],
            "origin": ti.origin,
            "start_date": ti.start_date,
            "end_date": ti.end_date,
            "adults": ti.adults,
        }
        _debug(
            "StateView:correction",
            field_count=len([v for v in view.values() if v]),
        )
        return view

    @staticmethod
    def for_general(state: "GraphState") -> Dict[str, Any]:
        """
        Minimal view for general specialist node.
        Handles generic requests that don't fit specific domains.
        Provides core trip context for generating helpful responses.
        """
        ti = state.trip_inputs
        view = {
            "destinations": ti.destinations or [],
            "origin": ti.origin,
            "start_date": ti.start_date,
            "end_date": ti.end_date,
            "adults": ti.adults,
            "budget": ti.budget,
            "currency": ti.currency,
        }
        _debug(
            "StateView:general",
            field_count=len([v for v in view.values() if v]),
        )
        return view

    # -------------------------------------------------------------------------
    # Phase 6: Runtime Validation
    # -------------------------------------------------------------------------
    # Maximum acceptable field count for a state view.
    # Full TripInputs has ~50 fields; views should have <20.
    _MAX_VIEW_FIELDS = 20
    # Warning threshold (will log warning but not fail)
    _WARN_VIEW_FIELDS = 15

    @classmethod
    def validate_view(cls, view: Dict[str, Any], node_name: str) -> None:
        """
        Validate that a state view is minimal enough.

        Phase 6: Fail-fast if a node accidentally passes full trip_inputs.
        This catches regressions where nodes bypass StateViewBuilder.

        Args:
            view: The state view dictionary
            node_name: Name of the node for error messages

        Raises:
            ValueError: If view exceeds maximum field count
        """
        field_count = len(view)

        # Count nested fields too (settings dicts)
        nested_count = sum(len(v) if isinstance(v, dict) else 0 for v in view.values())
        total_fields = field_count + nested_count

        if total_fields > cls._MAX_VIEW_FIELDS:
            # Log full details for debugging
            _debug(
                f"StateView:VALIDATION_FAILED:{node_name}",
                total_fields=total_fields,
                top_level_fields=field_count,
                nested_fields=nested_count,
                view_keys=list(view.keys()),
            )
            raise ValueError(
                f"StateView for {node_name} has {total_fields} fields "
                f"(max {cls._MAX_VIEW_FIELDS}). Use StateViewBuilder methods "
                "instead of passing full trip_inputs."
            )
        elif total_fields > cls._WARN_VIEW_FIELDS:
            _debug(
                f"StateView:WARN:{node_name}",
                total_fields=total_fields,
                warning="View approaching maximum field count",
            )


def _deserialize_errors(raw_errors: List[Any]) -> List[ErrorRecord]:
    """
    Deserialize errors from session_state into ErrorRecord objects.

    Handles:
    - ErrorRecord objects (pass through)
    - Dict objects (reconstruct from JSON)
    - String objects (skip with warning - corrupted data)

    Args:
        raw_errors: List of errors from session_state (may be mixed types)

    Returns:
        List of valid ErrorRecord objects
    """
    result: List[ErrorRecord] = []
    for err in raw_errors:
        if isinstance(err, ErrorRecord):
            result.append(err)
        elif isinstance(err, dict):
            try:
                result.append(ErrorRecord(**err))
            except Exception as e:
                _debug(f"Failed to deserialize error dict: {err}, error: {e}")
        elif isinstance(err, str):
            # String errors are corrupted - skip but log
            _debug(f"Skipping string error (corrupted data): {err[:100]}...")
        else:
            _debug(f"Unknown error type: {type(err)}")
    return result


def _record_structured_error(
    state: GraphState,
    code: str,
    node: str,
    message: str,
    severity: Literal["blocking", "warning", "info"] = "warning",
) -> None:
    """
    Record a structured error to state.errors for proper accounting.

    All errors should use this function to ensure consistent format
    and proper errors_count tracking.

    Args:
        state: Current graph state
        code: Error code (e.g., "LLM_FAILED", "GUARD_ERROR", "VALIDATION_FAILED")
        node: Node name where error occurred
        message: Human-readable error message
        severity: "blocking", "warning", or "info"
    """
    state.errors.append(
        ErrorRecord(
            code=code,
            node=node,
            severity=severity,
            message=message,
        )
    )


def _record_llm_failure(state: GraphState, reason: str) -> GraphState:
    """Record an LLM failure and provide a conversational fallback message."""
    failures = state.metadata.get("validator_failures", 0) + 1
    state.metadata["validator_failures"] = failures

    # Record structured error for proper accounting
    _record_structured_error(
        state,
        code="LLM_FAILED",
        node=state.metadata.get("current_node", "unknown"),
        message=reason,
        severity="blocking",
    )

    # Always provide a user-facing message - be conversational
    # Use the default follow-up question based on missing fields, adapted to user intent/tone
    trip_inputs_dict = state.trip_inputs.model_dump(exclude_none=True)
    missing = compute_trip_readiness(trip_inputs_dict).missing_core
    user_intent = state.metadata.get("user_intent", "detailed_planner")
    user_tone = state.metadata.get("user_tone", "neutral")
    fallback_msg, _ = _default_follow_up_with_field(
        missing, user_intent, user_tone, trip_inputs_dict
    )
    if fallback_msg:
        state.last_summary = fallback_msg
    else:
        state.last_summary = "Where are you looking to travel?"

    state.ready_to_generate = False
    return state


# NOTE: _STRATEGY_TOPIC_PATTERNS moved to pattern_matching.py (V26 extraction)
# Use STRATEGY_TOPIC_PATTERNS imported at module level


def _detect_strategy_topic_from_text(text: str) -> Optional[str]:
    """
    Detect strategy topic from user text using word boundary patterns.

    Returns the first matched topic or None.
    Uses regex word boundaries to avoid false positives like 'skippered' matching 'ski'.
    """
    if not text:
        return None

    for topic, pattern in STRATEGY_TOPIC_PATTERNS.items():
        if pattern.search(text):
            return topic
    return None


# =============================================================================
# STRATEGY BOOTSTRAP BYPASS: Deterministic bypass of extractor LLM
# =============================================================================
# Constants for bypass safety guards
_BYPASS_MAX_TEXT_LENGTH = 150  # Skip bypass for long/dense prompts

# NOTE: _BYPASS_CONSTRAINT_PATTERNS moved to pattern_matching.py (V26 extraction)
# Use BYPASS_CONSTRAINT_PATTERNS imported at module level

# Multi-intent detection: vertical keywords that suggest multiple booking types
_MULTI_INTENT_KEYWORDS = frozenset(
    {"flights", "flight", "hotel", "hotels", "car", "rental", "transport", "activities"}
)


def _contains_known_place(text: str) -> bool:
    """
    Check if any known place appears within the text.

    Uses sliding window to check 1-word, 2-word, and 3-word phrases
    against the known places database.
    """
    from app.known_places import _ALL_KNOWN_PLACES_LOWER

    words = text.split()

    # Check 1-word, 2-word, and 3-word combinations
    for window_size in [1, 2, 3]:
        for i in range(len(words) - window_size + 1):
            phrase = " ".join(words[i : i + window_size]).lower()
            # Remove trailing punctuation
            phrase = phrase.rstrip(".,!?;:")
            if phrase in _ALL_KNOWN_PLACES_LOWER:
                return True

    return False


def _try_strategy_bootstrap_bypass(
    text: str,
    state: "GraphState",
) -> Optional[Dict[str, Any]]:
    """
    Try to bypass extractor LLM for strategy pre-core prompts.

    Returns bypass result dict if bypass should be taken, None otherwise.

    Bypass conditions (all must be true):
    1. Feature flag enabled (settings.enable_strategy_bootstrap_bypass)
    2. Sample rate check (A/B testing support)
    3. No question_target set (first turn or open-ended)
    4. Core fields are empty (no destinations, dates)
    5. Strategy topic detected in text
    6. No place-like entities detected
    7. Short text (< 150 chars)
    8. No constraint tokens (dates, budget, travelers)
    9. No multi-intent (multiple specialists or topics)

    Invariant check (after bypass decision):
    - strategy_topic is set
    - question_target will be set to "dates"
    """
    reject_reasons: List[str] = []

    # Gate 1: Feature flag
    if not settings.enable_strategy_bootstrap_bypass:
        return None

    # Gate 2: Sample rate (A/B testing)
    # Use deterministic hash for stable cohort assignment
    session_id = state.metadata.get("thread_id", "") if state.metadata else ""
    sample_rate = settings.strategy_bootstrap_bypass_sample_rate
    if sample_rate < 1.0:
        hash_val = stable_hash_int(session_id, modulo=100)
        if hash_val >= int(sample_rate * 100):
            # Control cohort - record but don't bypass
            _debug(
                "Strategy bootstrap bypass: control cohort (A/B)",
                session_id=session_id[:8] if session_id else "unknown",
                sample_rate=sample_rate,
            )
            return None

    # Gate 3: No question_target (open-ended prompt)
    question_target = state.metadata.get("question_target") if state.metadata else None
    if question_target:
        reject_reasons.append(f"question_target_set:{question_target}")
        _debug(
            "Strategy bootstrap bypass: rejected (question_target set)",
            question_target=question_target,
        )
        return None

    # Gate 4: Core fields empty
    ti = state.trip_inputs
    if ti and (ti.destinations or ti.start_date or ti.end_date):
        reject_reasons.append("core_fields_present")
        return None

    # Gate 5: Strategy topic detected
    topic = _detect_strategy_topic_from_text(text)
    if not topic:
        return None  # No logging - most prompts won't match

    # Gate 6: No place-like entities
    # Check if any known place appears within the text
    place_detected_by = "none"
    if _contains_known_place(text):
        place_detected_by = "known_places"
        reject_reasons.append(f"place_detected:{place_detected_by}")
        _debug(
            "Strategy bootstrap bypass: rejected (known place in text)",
            topic=topic,
        )
        return None

    # Gate 7: Short text
    if len(text) > _BYPASS_MAX_TEXT_LENGTH:
        reject_reasons.append(f"text_too_long:{len(text)}")
        _debug(
            "Strategy bootstrap bypass: rejected (text too long)",
            topic=topic,
            text_length=len(text),
        )
        return None

    # Gate 8: No constraint tokens
    constraint_tokens: Dict[str, bool] = {}
    for constraint_type, pattern in BYPASS_CONSTRAINT_PATTERNS.items():
        if pattern.search(text):
            constraint_tokens[constraint_type] = True
            reject_reasons.append(f"constraint:{constraint_type}")

    if constraint_tokens:
        _debug(
            "Strategy bootstrap bypass: rejected (constraint tokens)",
            topic=topic,
            constraints=list(constraint_tokens.keys()),
        )
        return None

    # Gate 9: No multi-intent (multiple vertical keywords or strategy topics)
    text_lower = text.lower()
    text_words = set(text_lower.split())
    intent_keywords_found = text_words & _MULTI_INTENT_KEYWORDS
    if len(intent_keywords_found) >= 2:
        reject_reasons.append(f"multi_intent:{','.join(intent_keywords_found)}")
        _debug(
            "Strategy bootstrap bypass: rejected (multi-intent)",
            topic=topic,
            intents=list(intent_keywords_found),
        )
        return None

    # Check for multiple strategy topics
    topics_found = []
    for t, pattern in STRATEGY_TOPIC_PATTERNS.items():
        if pattern.search(text):
            topics_found.append(t)
    if len(topics_found) > 1:
        reject_reasons.append(f"multi_topic:{','.join(topics_found)}")
        _debug(
            "Strategy bootstrap bypass: rejected (multiple topics)",
            topics=topics_found,
        )
        return None

    # All gates passed - prepare bypass result
    # Determine trip_style based on topic
    topic_to_style = {
        "hiking": "adventure_outdoors",
        "skiing": "adventure_outdoors",
        "diving": "adventure_outdoors",
        "cycling": "adventure_outdoors",
        "boating": "adventure_outdoors",
    }

    topic_to_activity = {
        "hiking": ["hiking", "trekking"],
        "skiing": ["skiing", "snowboarding"],
        "diving": ["diving", "snorkeling"],
        "cycling": ["cycling", "biking"],
        "boating": ["boating", "sailing"],
    }

    _debug(
        "Strategy bootstrap bypass: taking bypass",
        topic=topic,
        text_length=len(text),
    )

    return {
        "topic": topic,
        "trip_style": topic_to_style.get(topic, "adventure_outdoors"),
        "activity_categories": topic_to_activity.get(topic, [topic]),
        "variant": "bypass",
        "place_detected_by": place_detected_by,
        "constraint_tokens": {k: False for k in BYPASS_CONSTRAINT_PATTERNS.keys()},
    }


# -----------------------
# Normalize inputs node (new)
# -----------------------
def normalize_inputs(state: GraphState) -> GraphState:
    """
    Apply normalization to extracted inputs and merge into trip_inputs.

    This node runs after extractor and before router. It is the SINGLE location
    where all normalization occurs in the graph. Uses TripInputNormalizer for
    unified normalization logic.

    NOTE: All normalization happens here. Specialists and validate_and_merge
    should NOT duplicate normalization logic.
    """
    _, start_ns = _debug_node_entry("normalize_inputs", state)

    # Early exit for short-circuits with no parsed data (greetings, acknowledgments, off-topic)
    # These don't need any normalization work
    sc_type = state.flags.get("short_circuit")
    if sc_type and sc_type in (
        "greeting",
        "acknowledgment",
        "off_topic",
        "confirmation_yes",
        "confirmation_no",
    ):
        if not state.parsed_inputs:
            _debug(f"Skipping normalize_inputs for short-circuit: {sc_type}")
            _debug_node_exit("normalize_inputs", state, start_ns)
            return state

    parsed = state.parsed_inputs or {}
    ti = state.trip_inputs  # Read-only reference for reading current values

    # =========================================================================
    # CAPTURE READINESS STATE BEFORE NORMALIZATION
    # =========================================================================
    # Used to detect transition to core_complete (for plan_just_became_ready flag)
    readiness_before = compute_trip_readiness(ti.model_dump(exclude_none=True))
    was_core_complete = readiness_before.core_complete

    # =========================================================================
    # FALLBACK: Parse user_text directly for date ranges if LLM missed it
    # =========================================================================
    # If no dates were extracted but user_text looks like a date range, parse it
    user_text = state.user_text or ""
    if not parsed.get("start_date_hint") and not ti.start_date:
        range_start, range_end = _date_normalizer.parse_date_range(user_text.strip())
        if range_start and range_end:
            parsed["start_date_hint"] = range_start
            parsed["end_date_hint"] = range_end
            _debug(
                "Fallback: parsed date range from user_text",
                user_text=user_text,
                start=range_start,
                end=range_end,
            )

    # =========================================================================
    # FALLBACK: Parse user_text for family composition if LLM missed it
    # =========================================================================
    # If no travelers were extracted but user_text mentions kids/family, extract
    if not parsed.get("children_delta") and not ti.children:
        text_lower = user_text.lower()
        family_match = FAMILY_COMPOSITION_PATTERN.search(text_lower)
        if family_match:
            groups = family_match.groups()

            # Helper to convert word numbers to int
            def _word_to_int(val: str) -> int:
                word_map = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
                if val and val.isdigit():
                    return int(val)
                return word_map.get((val or "").lower(), 0)

            # Check groups for children indicators
            if groups[0]:  # "family of N"
                total = int(groups[0])
                if total > 2:
                    parsed["children_delta"] = total - 2
                    if not parsed.get("adults_delta") and not ti.adults:
                        parsed["adults_delta"] = 2
                    _debug(f"Fallback: extracted family of {total} from user_text")
            elif groups[1] and groups[2]:  # "N adults and N kids"
                if not parsed.get("adults_delta") and not ti.adults:
                    parsed["adults_delta"] = int(groups[1])
                parsed["children_delta"] = int(groups[2])
                _debug(
                    f"Fallback: extracted {groups[1]} adults and {groups[2]} kids from user_text"
                )
            elif groups[3]:  # "me and my N kids"
                parsed["children_delta"] = int(groups[3])
                if not parsed.get("adults_delta") and not ti.adults:
                    parsed["adults_delta"] = 1
                _debug(f"Fallback: extracted 'me and my {groups[3]} kids' from user_text")
            elif groups[4]:  # "with N kids"
                kids_count = _word_to_int(groups[4])
                if kids_count > 0:
                    parsed["children_delta"] = kids_count
                    if not parsed.get("adults_delta") and not ti.adults:
                        parsed["adults_delta"] = 1
                    _debug(f"Fallback: extracted 'with {kids_count} kids' from user_text")
            elif groups[5]:  # "N kids with us"
                kids_count = _word_to_int(groups[5])
                if kids_count > 0:
                    parsed["children_delta"] = kids_count
                    if not parsed.get("adults_delta") and not ti.adults:
                        parsed["adults_delta"] = 1
                    _debug(f"Fallback: extracted '{kids_count} kids with us' from user_text")
            elif len(groups) > 6 and groups[6]:  # "traveling with kids"
                parsed["children_delta"] = 1
                if not parsed.get("adults_delta") and not ti.adults:
                    parsed["adults_delta"] = 1
                _debug("Fallback: extracted 'traveling with kids' from user_text (children=1)")
            elif len(groups) > 7 and groups[7]:  # "for the kids" / "with the kids"
                parsed["children_delta"] = 1
                if not parsed.get("adults_delta") and not ti.adults:
                    parsed["adults_delta"] = 1
                _debug("Fallback: extracted 'for/with the kids' from user_text (children=1)")
            elif len(groups) > 8 and groups[8]:  # "family trip"
                parsed["children_delta"] = 1
                if not parsed.get("adults_delta") and not ti.adults:
                    parsed["adults_delta"] = 2
                _debug("Fallback: extracted 'family trip' from user_text (adults=2, children=1)")

    # =========================================================================
    # FALLBACK: Parse user_text for budget if LLM missed it
    # =========================================================================
    if not parsed.get("budget_delta") and not ti.budget:
        budget_match = INLINE_BUDGET_PATTERN.search(user_text.lower())
        if budget_match:
            groups = budget_match.groups()
            for g in groups:
                if g:
                    budget_str = g.replace(",", "").strip()
                    if budget_str.lower().endswith("k"):
                        budget_value = int(float(budget_str[:-1]) * 1000)
                    else:
                        budget_value = int(float(budget_str))
                    parsed["budget_delta"] = budget_value
                    _debug(f"Fallback: extracted budget={budget_value} from user_text")
                    break

    # =========================================================================
    # HANDLE budget_answered FLAG FROM LQA (user said "no budget"/"flexible")
    # =========================================================================
    # When LQA detects a flexible budget answer, it sets budget_answered: True
    # in parsed_inputs. We need to propagate this to metadata so that
    # _compute_missing_fields_and_target doesn't re-ask about budget.
    if parsed.get("budget_answered"):
        state.metadata["budget_answered"] = True
        if parsed.get("budget_tier"):
            state.metadata["budget_tier"] = parsed["budget_tier"]
        _debug("Set budget_answered=True from LQA", tier=parsed.get("budget_tier"))

    # =========================================================================
    # HANDLE ORIGIN VERIFICATION METADATA
    # =========================================================================
    # When an unknown origin is extracted and verified via LLM, the extractor
    # or initial extraction may set _origin_metadata with clarification info.
    origin_metadata = parsed.pop("_origin_metadata", None)
    if origin_metadata:
        if origin_metadata.get("origin_correction_pending"):
            correction = origin_metadata["origin_correction_pending"]
            # Use existing typo confirmation flow
            state.metadata["typo_suggestions"] = {correction["original"]: correction["suggested"]}
            state.metadata["pending_action"] = "confirm_typo"
            state.metadata["pending_typo_corrections"] = {
                correction["original"]: correction["suggested"]
            }
            _debug(f"[ORIGIN_VERIFY] Setup correction confirmation: {correction}")

        elif origin_metadata.get("origin_clarification_needed"):
            clarification = origin_metadata["origin_clarification_needed"]
            # Force required_fields to ask about origin
            state.metadata["force_required_fields_reason"] = "origin_unverified"
            state.metadata["origin_clarification"] = clarification
            _debug(f"[ORIGIN_VERIFY] Setup clarification: {clarification}")

    # =========================================================================
    # USE TripInputNormalizer FOR UNIFIED NORMALIZATION
    # =========================================================================
    # This is the SINGLE normalization pass. All field normalization, validation,
    # and error collection happens here via TripInputNormalizer.

    # -------------------------------------------------------------------------
    # Destination replacement detection (P4.1 negation handling)
    # -------------------------------------------------------------------------
    # Check if user is replacing (not adding) destinations based on negation signals
    # from LQA prepass. "actually I want Paris" should replace, not add.
    # But "actually I also want Paris" should add (additive signal overrides).
    negation_type = state.metadata.get("negation_type")
    replace_destinations = False
    if negation_type and "destinations_delta" in parsed:
        # Negation types that indicate replacement intent
        replacement_negation_types = (
            "actually",
            "instead_of",
            "x_instead",
            "change_to",
            "not_but",
            "not_maybe",
        )
        if negation_type in replacement_negation_types:
            # Check for additive signals that override replacement intent
            user_text_lower = (user_text or "").lower()
            additive_signals = ("also", "too", "as well", "and also", "addition")
            has_additive_signal = any(signal in user_text_lower for signal in additive_signals)
            if not has_additive_signal:
                replace_destinations = True
                _debug(
                    "DESTINATION_REPLACE: Negation detected, replacing destinations",
                    negation_type=negation_type,
                    new_destinations=parsed.get("destinations_delta"),
                )

    # Pass turn number for provenance tracking
    parsed["_turn_number"] = state.turn_number
    updates, norm_errors = _trip_normalizer.normalize_all(
        ti, parsed, user_text=user_text, replace_destinations=replace_destinations
    )

    # =========================================================================
    # DATE PROVENANCE MERGE PROTECTION (Explicit Year Wins)
    # =========================================================================
    # Handle date provenance updates with explicit year protection
    new_provenance = updates.pop("_date_provenance", None)
    if new_provenance:
        # Get existing provenance from metadata
        existing_provenance = state.metadata.get("date_provenance", {})

        for date_field in ("start_date", "end_date"):
            if date_field in new_provenance:
                new_prov = new_provenance[date_field]
                existing_prov = existing_provenance.get(date_field, {})

                # MERGE RULE: If existing has explicit_year=True and new has explicit_year=False,
                # preserve the existing year but allow day/month updates
                if existing_prov.get("explicit_year") and not new_prov.get("explicit_year"):
                    # Extract year from existing value, apply to new value
                    existing_value = existing_prov.get("value", "")
                    new_value = new_prov.get("value", "")
                    if existing_value and new_value:
                        existing_year = existing_value[:4]
                        new_month_day = new_value[5:]  # "-MM-DD"
                        protected_value = f"{existing_year}{new_month_day}"

                        _debug(
                            f"DATE_PROVENANCE: Protected explicit year for {date_field}",
                            existing_year=existing_year,
                            original_new_value=new_value,
                            protected_value=protected_value,
                        )

                        # Update the value but keep existing provenance
                        updates[date_field] = protected_value
                        new_prov["value"] = protected_value
                        new_prov["explicit_year"] = True  # Inherit from existing
                        new_prov["parsed_from"] = "year_protected"

                existing_provenance[date_field] = new_prov

        # Store updated provenance in metadata
        state.metadata["date_provenance"] = existing_provenance

        # Also store schema version for future migration
        if "schema_version" not in state.metadata:
            state.metadata["schema_version"] = "1.0.0"

    # Handle partial date notifications (stored in updates by normalizer)
    partial_date_notifications = updates.pop("_partial_date_notifications", None)
    if partial_date_notifications:
        # Build human-readable notification messages
        notifications = []
        for notif in partial_date_notifications:
            if "start_date" in notif:
                start_iso = updates.get("start_date") or ti.start_date
                if start_iso:
                    dt = _parse_iso_date(start_iso)
                    if dt:
                        readable = dt.strftime("%B %d, %Y")
                        notifications.append(f"Start: {readable}.")
            elif "end_date" in notif:
                end_iso = updates.get("end_date") or ti.end_date
                if end_iso:
                    dt = _parse_iso_date(end_iso)
                    if dt:
                        readable = dt.strftime("%B %d, %Y")
                        notifications.append(f"End: {readable}.")
        if notifications:
            state.metadata["partial_date_notifications"] = notifications
            _debug("Partial date defaults applied", notifications=notifications)

    # Store raw date hints for specialist nodes
    if "start_date_hint" in parsed:
        if "raw_date_hints" not in state.metadata:
            state.metadata["raw_date_hints"] = {}
        state.metadata["raw_date_hints"]["start_date"] = parsed["start_date_hint"]
    if "end_date_hint" in parsed:
        if "raw_date_hints" not in state.metadata:
            state.metadata["raw_date_hints"] = {}
        state.metadata["raw_date_hints"]["end_date"] = parsed["end_date_hint"]

    # Apply inferred activities from destination (multi-faceted extraction)
    # These are activities implied by the destination, e.g., "Patagonia" → hiking
    if "inferred_activity_categories" in parsed:
        inferred = parsed["inferred_activity_categories"]
        existing_settings = dict(ti.activity_settings) if ti.activity_settings else {}
        existing_cats = list(existing_settings.get("categories", []))

        # Normalize via _normalize_booking_field for consistency
        normalized = _normalize_booking_field("activity_settings", {"categories": inferred})
        if normalized and "categories" in normalized:
            for cat in normalized["categories"]:
                if cat not in existing_cats:
                    existing_cats.append(cat)

        # Deduplicate case-insensitively after merge
        existing_cats = _deduplicate_activities_case_insensitive(existing_cats)
        existing_settings["categories"] = existing_cats
        updates["activity_settings"] = existing_settings

        # Also enable activities booking type
        existing_booking = dict(updates.get("booking_types") or ti.booking_types or {})
        existing_booking["activities"] = True
        updates["booking_types"] = existing_booking

        _debug(
            "Applied inferred activities from destination",
            categories=existing_cats,
        )

    # =========================================================================
    # AUTO-INFER MULTI_CITY_INTENT FROM USER TEXT
    # =========================================================================
    # Uses multiple signals to detect multi-city trips:
    # 1. multi_city_signal from deterministic parser (e.g., "Paris and Barcelona")
    # 2. Additive markers (too/also/as well) + destination count increase
    #
    # The multi_city_signal is set when the deterministic parser detects
    # conjunction patterns like "Paris and Barcelona" or "Paris, Barcelona".
    if "destinations" in updates and not updates.get("multi_city_intent"):
        new_dests = updates.get("destinations", [])
        old_dests = ti.destinations or []

        # Signal 1: Destination count increased (user added a destination)
        destination_count_increased = len(new_dests) > len(old_dests)

        # Signal 2: At least 2 destinations in the updated list
        has_multiple_destinations = len(new_dests) >= 2

        # Only proceed if both signals are present
        if destination_count_increased and has_multiple_destinations:
            # Check if multi_city_intent is not already set on trip_inputs
            if not ti.multi_city_intent:
                # Priority 1: Check multi_city_signal from deterministic parser
                # This is set when "Paris and Barcelona" or "Paris, Barcelona" is parsed
                if state.metadata.get("multi_city_signal"):
                    updates["multi_city_intent"] = "multi_city"
                    state.metadata["multi_city_confidence"] = 0.9
                    _debug(
                        "Auto-inferred multi_city_intent from deterministic multi_city_signal",
                        destinations=new_dests,
                        confidence=0.9,
                    )
                else:
                    # Priority 2: Check user text for additive phrases
                    user_text_lower = (state.user_text or "").lower()
                    additive_patterns = [
                        r"\btoo\b",  # "go to X too", "visit X too"
                        r"\balso\b",  # "also visit X", "also go to X"
                        r"\bas well\b",  # "visit X as well"
                        r"\band\s+also\b",  # "and also X"
                        r"\badd\b",  # "add X to the trip"
                    ]

                    # Count how many additive patterns match
                    pattern_matches = sum(
                        1 for pattern in additive_patterns if re.search(pattern, user_text_lower)
                    )

                    # Require at least one additive pattern match
                    if pattern_matches >= 1:
                        updates["multi_city_intent"] = "multi_city"
                        state.metadata["multi_city_confidence"] = min(
                            0.3 + (pattern_matches * 0.2), 1.0
                        )
                        _debug(
                            "Auto-inferred multi_city_intent from additive phrase + "
                            "destination increase",
                            pattern_matches=pattern_matches,
                            confidence=state.metadata["multi_city_confidence"],
                            old_count=len(old_dests),
                            new_count=len(new_dests),
                        )

    # =========================================================================
    # INFER TRIP SHAPE FROM USER TEXT (Deterministic, no LLM)
    # =========================================================================
    # Infer trip_style, activity_categories, pace, planning_flexibility
    # from keywords in user text. These help with strategy routing and
    # personalized recommendations without additional LLM calls.
    trip_shape = _infer_trip_shape(state.user_text or "", state.strategy_topic)
    if trip_shape:
        # Merge into activity_settings with "only set if missing" semantics
        existing_settings = dict(updates.get("activity_settings") or ti.activity_settings or {})

        # Add inferred categories (merge, don't replace)
        if trip_shape.get("activity_categories"):
            existing_cats = list(existing_settings.get("categories", []))
            for cat in trip_shape["activity_categories"]:
                if cat not in existing_cats:
                    existing_cats.append(cat)
            existing_settings["categories"] = existing_cats

        # Add trip_style if not set
        if trip_shape.get("trip_style") and not existing_settings.get("trip_style"):
            existing_settings["trip_style"] = trip_shape["trip_style"]

        # Add pace if not set
        if trip_shape.get("pace") and not existing_settings.get("pace"):
            existing_settings["pace"] = trip_shape["pace"]

        # Add planning_flexibility if not set
        if trip_shape.get("planning_flexibility") and not existing_settings.get(
            "planning_flexibility"
        ):
            existing_settings["planning_flexibility"] = trip_shape["planning_flexibility"]

        updates["activity_settings"] = existing_settings
        state.metadata["trip_shape_inferred"] = trip_shape
        _debug("Inferred trip shape from user text", trip_shape=trip_shape)

    # =========================================================================
    # EXTRACT PRIVATE KEYS BEFORE _write_trip_inputs (they're metadata, not fields)
    # =========================================================================
    # Pop keys that start with "_" - these are metadata signals, not TripInputs fields
    needs_date_clarify = updates.pop("_needs_date_clarify", False)
    rejected_date_answer = updates.pop("_rejected_date_answer", None)

    if needs_date_clarify:
        state.metadata["date_clarify_mode"] = True
        _debug("Date clarification mode enabled due to validation failure")

    if rejected_date_answer:
        state.metadata["rejected_date_answer"] = rejected_date_answer
        # Generate user-facing message for date rejection
        reasons = rejected_date_answer.get("rejection_reasons", [])
        parsed_start = rejected_date_answer.get("parsed_start")
        parsed_end = rejected_date_answer.get("parsed_end")
        if reasons and parsed_start:
            # Create a helpful clarification message
            if "past" in " ".join(reasons).lower():
                state.metadata["failed_input_message"] = (
                    f"Invalid: {parsed_start} to {parsed_end} has passed. Future dates required."
                )
            elif "ambiguous" in " ".join(reasons).lower():
                state.metadata["failed_input_message"] = (
                    f"Ambiguous: {parsed_start} to {parsed_end}. Specify year."
                )
            else:
                state.metadata["failed_input_message"] = (
                    f"Invalid dates: {parsed_start} to {parsed_end}. Re-enter dates."
                )
        _debug(
            "📋 Stored rejected date answer for clarification reference",
            user_text=rejected_date_answer.get("user_text", "")[:50],
            parsed_start=parsed_start,
            parsed_end=parsed_end,
            reasons=reasons,
        )

    failed_inputs = updates.pop("_failed_inputs", None)
    if failed_inputs:
        # Store failed inputs for reference
        existing_failed = state.metadata.get("failed_inputs", [])
        state.metadata["failed_inputs"] = existing_failed + failed_inputs
        # Use the first failed input's user_message as the clarification message
        # (prioritize showing one clear message rather than overwhelming the user)
        if not state.metadata.get("failed_input_message"):
            first_failure = failed_inputs[0]
            state.metadata["failed_input_message"] = first_failure.get("user_message", "")
        for inp in failed_inputs:
            _debug(
                f"📋 USER INPUT FAILED AND STORED: {inp['field']}",
                raw_value=inp.get("raw_value"),
                reason=inp.get("reason"),
            )

    # =========================================================================
    # SETTINGS CHANGE DETECTION (for response invalidation)
    # =========================================================================
    # Track when domain-specific settings change. This is used to:
    # 1. Clear stale last_summary (prevents asking same question twice)
    # 2. Invalidate cached responses for the affected specialist
    # 3. Route to appropriate specialist to acknowledge the change
    #
    # IMPORTANT: Only detect user-driven changes, not inferred metadata fields.
    # Inferred fields (like planning_flexibility) should not trigger change detection.
    INFERRED_SETTINGS_FIELDS = {"planning_flexibility"}

    def _is_user_driven_settings_change(old: Optional[Dict], new: Optional[Dict]) -> bool:
        """Check if settings change is user-driven (not just inferred metadata)."""
        old_filtered = {k: v for k, v in (old or {}).items() if k not in INFERRED_SETTINGS_FIELDS}
        new_filtered = {k: v for k, v in (new or {}).items() if k not in INFERRED_SETTINGS_FIELDS}
        return old_filtered != new_filtered

    settings_changed_this_turn: Dict[str, bool] = {}
    if updates:
        settings_fields = ["flight_settings", "hotel_settings", "activity_settings"]
        for field in settings_fields:
            if field in updates:
                old_value = getattr(ti, field, None)
                new_value = updates[field]
                # Only consider it changed if user-driven fields differ (not inferred metadata)
                if _is_user_driven_settings_change(old_value, new_value):
                    settings_changed_this_turn[field] = True
                    _debug(
                        f"SETTINGS_CHANGE_DETECTED: {field}",
                        old=old_value,
                        new=new_value,
                    )

    # Apply all updates via the helper (this does ownership checking and deep copy)
    if updates:
        _write_trip_inputs(state, "normalize_inputs", **updates)  # Ignore fields_changed
        _debug(
            "normalize_inputs applied updates via _write_trip_inputs", fields=list(updates.keys())
        )

    # =========================================================================
    # CLEAR STALE RESPONSE WHEN SETTINGS CHANGE (prevents question loop)
    # =========================================================================
    # When user answers a preference question (e.g., "open to layovers"),
    # the settings change (direct_only: false). We clear last_summary to
    # prevent echoing the old response that asked the same question.
    if settings_changed_this_turn:
        state.metadata["settings_changed_this_turn"] = settings_changed_this_turn
        # Clear stale last_summary so specialist/summarize generates fresh response
        if state.last_summary:
            _debug(
                "SETTINGS_CHANGE: Clearing stale last_summary",
                changed_settings=list(settings_changed_this_turn.keys()),
                old_summary_preview=state.last_summary[:80] if state.last_summary else "",
            )
            state.last_summary = None
        # Also clear stale suggested_responses
        if state.suggested_responses:
            state.suggested_responses = []

    # Add normalization errors to state errors
    if norm_errors:
        for err in norm_errors:
            _record_structured_error(
                state,
                code=f"NORMALIZATION_{err.severity.upper()}",
                node="normalize_inputs",
                message=f"{err.field}: {err.message}",
                severity=err.severity,
            )
        _debug(f"Normalization produced {len(norm_errors)} errors/warnings")

    # =========================================================================
    # READINESS TRANSITION DETECTION (plan_just_became_ready)
    # =========================================================================
    # Detect when core_complete transitions from False → True.
    # This triggers the "ready to generate" message in summarize node.
    ti_after = state.trip_inputs
    readiness_after = compute_trip_readiness(ti_after.model_dump(exclude_none=True))

    if not was_core_complete and readiness_after.core_complete:
        state.metadata["plan_just_became_ready"] = True
        # Clear stale last_summary so summarize generates fresh response
        state.last_summary = None
        _debug(
            "READINESS_TRANSITION: core_complete became True",
            missing_before=readiness_before.missing_core,
            missing_after=readiness_after.missing_core,
        )

    # =========================================================================
    # PRE-COMPUTE GATE EVALUATION (for routing and observability)
    # =========================================================================
    # Perform gate evaluation here in the node (where state mutations persist)
    # rather than in the routing function (where mutations are lost).
    # Store results in metadata for route_after_normalize to read.
    gate_result = GateEvaluator.evaluate(state)

    # Apply state mutations that would otherwise be lost in routing function
    if gate_result.intent:
        state.intent = gate_result.intent
    if gate_result.strategy_topic:
        state.strategy_topic = gate_result.strategy_topic
    if gate_result.question_target:
        state.question_target = gate_result.question_target

    # v5: Store immutable deep copy of full GateResult for RoutingDecisionFinal
    state.metadata["gate_result"] = deepcopy(gate_result)

    # Store gate result in metadata for routing function to use (legacy format)
    state.metadata["_gate_result_destination"] = gate_result.destination
    state.metadata["_gate_result_gate_fired"] = (
        gate_result.gate_fired.name
        if hasattr(gate_result.gate_fired, "name")
        else str(gate_result.gate_fired)
    )
    state.metadata["_gate_result_reason"] = gate_result.reason
    state.metadata["_gate_result_eval_time_ms"] = gate_result.eval_time_ms
    state.metadata["_gate_result_skipped_gates"] = gate_result.skipped_gates

    # Apply metadata updates from gate result
    for key, value in gate_result.metadata_updates.items():
        state.metadata[key] = value

    _debug_node_exit("normalize_inputs", state, start_ns)
    return state


# -----------------------
# Specialists (shared handler)
# -----------------------
# NOTE: _select_required_fields_prompt, _invoke_missing_fields_guard, and _specialist
# extracted to app/planner/nodes/specialist.py in P6.
# If you need to modify them, edit: backend/app/planner/nodes/specialist.py


async def required_fields_node(state: GraphState) -> GraphState:
    return await _specialist("required_fields", state)


async def flights_node(state: GraphState) -> GraphState:
    state.active_category = "flights"
    return await _specialist("flights", state)


async def hotels_node(state: GraphState) -> GraphState:
    state.active_category = "hotels"
    return await _specialist("hotels", state)


async def transport_node(state: GraphState) -> GraphState:
    state.active_category = "transport"
    return await _specialist("transport", state)


async def activities_node(state: GraphState) -> GraphState:
    state.active_category = "activities"
    return await _specialist("activities", state)


async def correction_node(state: GraphState) -> GraphState:
    return await _specialist("correction", state)


async def general_node(state: GraphState) -> GraphState:
    """Handle multi-domain queries spanning flights, hotels, transport, activities."""
    state.active_category = "general"
    return await _specialist("general", state)


# -----------------------
# Strategy node - imported from app.planner.nodes.strategy
# Functions: _is_strategy_enabled, _strategy_stage0, _generate_date_suggestions,
#            _track_strategy_pre_core_question, _should_escalate_from_stage0, strategy_node
# See: from app.planner.nodes import strategy_node, _strategy_stage0
# -----------------------


# -----------------------
# Validation & summarization (enhanced with plan.py logic)
# -----------------------
def validate_and_merge(state: GraphState) -> GraphState:
    """
    Compute ready_to_generate state and enable booking types.

    NOTE: All normalization (dates, travelers, currency, destinations) now
    happens in normalize_inputs via TripInputNormalizer. This node only:
    1. Computes ready_to_generate based on required fields
    2. Calls _auto_enable_booking_types (single call location)
    3. Generates any final validation messages
    4. Manages date_clarify_mode lifecycle (invariant check)
    """
    _, start_ns = _debug_node_entry("validate_and_merge", state)

    ti = state.trip_inputs  # Read-only reference

    # =========================================================================
    # DATE CLARIFY MODE LIFECYCLE MANAGEMENT
    # =========================================================================
    # Invariant: date_clarify_mode should only be True when date errors exist
    # Clear it when:
    # 1. Valid ordered range exists (start_date and end_date both set)
    # 2. No blocking date errors remain
    if state.metadata.get("date_clarify_mode"):
        has_blocking_date_errors = False

        # Check for blocking date errors in state.errors
        for err in state.errors:
            if isinstance(err, ErrorRecord):
                if err.severity == "blocking" or err.code in DATE_BLOCKING_ERROR_CODES:
                    has_blocking_date_errors = True
                    break
            elif isinstance(err, NormalizationError) and err.code in DATE_BLOCKING_ERROR_CODES:
                has_blocking_date_errors = True
                break
            elif isinstance(err, str) and any(code in err for code in DATE_BLOCKING_ERROR_CODES):
                has_blocking_date_errors = True
                break

        # Check if we now have a valid date range
        has_valid_range = bool(ti.start_date and ti.end_date)
        if has_valid_range:
            # Verify dates are ordered correctly
            start_dt = _date_normalizer.parse_iso(ti.start_date)
            end_dt = _date_normalizer.parse_iso(ti.end_date)
            if start_dt and end_dt and end_dt < start_dt:
                has_valid_range = False

        # Clear date_clarify_mode if conditions are met
        if has_valid_range and not has_blocking_date_errors:
            state.metadata["date_clarify_mode"] = False
            state.metadata.pop("pending_date_range", None)
            _date_stats["dates_clarify_resolved_count"] += 1
            _debug("Cleared date_clarify_mode: valid range and no blocking errors")

        # Also clear if there are no blocking errors (even without end_date)
        elif not has_blocking_date_errors and ti.start_date:
            state.metadata["date_clarify_mode"] = False
            state.metadata.pop("pending_date_range", None)
            _debug("Cleared date_clarify_mode: no blocking errors, start_date set")

    # =========================================================================
    # AUTO-ENABLE BOOKING TYPES (single call location)
    # =========================================================================
    # This is the ONLY place where _auto_enable_booking_types is called.
    # It was previously called in _apply_llm_delta and normalize_inputs too.
    _auto_enable_booking_types(ti)

    # =========================================================================
    # COMPUTE READY STATE
    # =========================================================================
    # Only require: destinations, origin, start_date (matches plan.py)
    missing = compute_trip_readiness(ti.model_dump(exclude_none=True)).missing_core

    # Check for blocking date errors that prevent generation
    has_blocking_date_errors = state.metadata.get("date_clarify_mode", False)
    if not has_blocking_date_errors:
        for err in state.errors:
            if isinstance(err, NormalizationError) and err.code in DATE_BLOCKING_ERROR_CODES:
                has_blocking_date_errors = True
                break

    # Check if user explicitly requested generation (should be respected)
    # EXCEPTION: Block if blocking date errors exist
    if state.flags.get("generate_requested") and ti.destinations:
        if has_blocking_date_errors:
            # Block generation due to date errors
            state.ready_to_generate = False
            _debug(
                "Generation blocked: date errors present",
                date_clarify_mode=state.metadata.get("date_clarify_mode"),
            )
        else:
            # User explicitly asked to generate and we have destinations
            # Respect their request even with partial data
            state.ready_to_generate = True
    else:
        # ready_to_generate: all required fields complete AND no blocking errors
        state.ready_to_generate = bool(
            not state.errors
            and not missing
            and ti.destinations
            and ti.origin
            and ti.start_date
            and not has_blocking_date_errors
        )

    _debug(
        "Validation complete",
        missing=missing,
        ready=state.ready_to_generate,
        errors_count=len(state.errors),
        date_clarify_mode=state.metadata.get("date_clarify_mode"),
    )
    _debug_node_exit("validate_and_merge", state, start_ns)
    return state


# -----------------------
# Response polish node (for natural conversational tone)
# -----------------------
# Minimum length threshold for polishing (chars)
_POLISH_MIN_LENGTH = 100

# Patterns that indicate content would benefit from polish formatting
_POLISH_LIST_PATTERNS = (
    "\n- ",  # Markdown bullet list
    "\n* ",  # Alternative bullet
    "\n1. ",  # Numbered list
    "\n2. ",  # Numbered list continuation
    "option",  # Multiple options being presented
    "could ",  # Suggesting alternatives
    "either ",  # Presenting choices
)


def _should_skip_polish(s: GraphState) -> tuple[bool, str]:
    """
    Determine if response polishing should be skipped.
    Returns (should_skip, reason).

    Phase 5: Tightened conditions to push LLM polish rate below 10%.
    Phase 6: Further tightened - skip more aggressively.
    Phase 7: Use explicit skip_polish flag, not fast_path (clarity).
    Phase 8: Use response_provenance for single-source-of-truth decision.

    Polish is SKIPPED for:
    - Feature disabled
    - Response provenance is "template" or "deterministic" (MVP optimization)
    - Short-circuit/template responses (already polished)
    - Cached responses (explicit skip_polish flag)
    - Fast-path responses ONLY when explicitly marked for skip
    - Initial extraction responses (Phase 6)
    - Frustrated users (avoid delays)
    - Already formatted messages (emoji + exclamation + bold)
    - Very short messages (<100 chars) that have any warmth indicator
    - Messages that end with ? and have any warmth (questions don't need polish)
    - Template-generated warm questions (Phase 6)

    Polish is APPLIED for:
    - Responses containing lists (bullet points, numbered items)
    - Longer responses (>200 chars) that would benefit from formatting
    - Medium-length dry responses without warmth indicators
    """
    # Check feature flag
    if not settings.enable_response_polish:
        return True, "feature_disabled"

    # MVP OPTIMIZATION: Use response_generation_provenance as single-source-of-truth
    # This checks how the RESPONSE was generated (not how input was parsed)
    # Uses final-writer-wins semantics from response_writer_node
    response_gen_provenance = s.metadata.get("response_generation_provenance")
    if response_gen_provenance == "template":
        return True, "provenance:template"
    if response_gen_provenance == "deterministic":
        return True, "provenance:deterministic"
    if response_gen_provenance == "codegen":
        return True, "provenance:codegen"
    if response_gen_provenance == "cached":
        return True, "provenance:cached"

    # Short-circuited responses are already template-based and don't need polish
    if s.flags.get("short_circuit"):
        return True, "short_circuit"

    # Explicit skip_polish flag (set by nodes that produce polished output)
    if s.flags.get("skip_polish"):
        return True, "skip_polish_flag"

    # Phase 7: Only skip polish for fast_path if:
    # 1. It's a strategy_bootstrap (deterministic template output)
    # 2. OR skip_polish was explicitly set
    # This prevents fast_path from incorrectly suppressing polish on LLM responses
    if s.flags.get("fast_path"):
        fast_path_field = s.flags.get("fast_path_field", "")
        # Strategy bootstrap outputs are already warm templates
        if fast_path_field == "strategy_bootstrap":
            return True, "fast_path:strategy_bootstrap"
        # LQA and initial extraction outputs are simple - skip polish
        if fast_path_field in ("lqa", "initial"):
            return True, f"fast_path:{fast_path_field}"
        # Other fast_path types: check if template-generated
        if s.metadata.get("from_template") or s.metadata.get("template_used"):
            return True, "fast_path:template"

    # Phase 6: Initial extraction responses (zero-LLM) are handled deterministically
    extraction_path = s.metadata.get("extraction_path", "")
    if extraction_path.startswith("initial:"):
        return True, "initial_extraction"

    # Phase 5: Template responses are already warm
    if s.metadata.get("template_used"):
        return True, "template_response"

    # No message to polish
    if not s.last_summary:
        return True, "no_message"

    # Frustrated user - avoid perceived delays, but prompts now include warmth
    if s.metadata.get("user_tone") == "frustrated":
        return True, "frustrated_user"

    msg = s.last_summary

    # Phase 6: Messages under 100 chars with ANY warmth indicator - skip
    if len(msg) < 100:
        has_warmth = "!" in msg or "?" in msg or "😊" in msg or "✨" in msg
        if has_warmth:
            return True, "short_with_warmth"

    # Phase 6: Questions ending with ? - skip if any warmth indicators
    if msg.rstrip().endswith("?"):
        has_emoji = any(c in msg for c in "✈️🏨🎉🌴☀️😊👍🎊🗺️📍✨🌟💫🎯🥾🌊⛷️🚴🤿")
        has_any_warmth = (
            has_emoji
            or "!" in msg
            or any(w in msg.lower() for w in ["great", "wonderful", "perfect", "love", "excited"])
        )
        if has_any_warmth:
            return True, "question_with_warmth"

    # Phase 6: Template-generated warm questions (from required_fields templates)
    required_fields_path = s.metadata.get("required_fields_path", "")
    if required_fields_path == "template" and msg.rstrip().endswith("?"):
        return True, "template_question"

    # Check if message contains list-like content that would benefit from polish
    has_list_content = any(pattern in msg.lower() for pattern in _POLISH_LIST_PATTERNS)

    # Check if message is long enough to benefit from formatting
    is_long_enough = len(msg) >= _POLISH_MIN_LENGTH

    # Check for warmth indicators - if missing, message may sound robotic
    has_emoji = any(c in msg for c in "✈️🏨🎉🌴☀️😊👍🎊🗺️📍✨🌟💫🎯🥾🌊⛷️🚴🤿")
    has_exclamation = "!" in msg
    has_bold = "**" in msg  # Already has markdown bold formatting
    has_question_mark = "?" in msg

    # Message already seems warm AND well-formatted
    if has_emoji and has_exclamation and has_bold and len(msg) > 50:
        return True, "already_formatted"

    # Phase 6: Message has multiple warmth indicators - likely already good
    warmth_count = sum([has_emoji, has_exclamation, has_question_mark, has_bold])
    if warmth_count >= 2 and len(msg) < 150:
        return True, "multiple_warmth_indicators"

    # Very short, potentially abrupt responses should still be polished
    # These often come from specialist nodes and sound robotic
    is_very_short = len(msg) < 80
    looks_abrupt = msg.rstrip().endswith(".") and not has_exclamation and not has_question_mark

    # Medium-length dry responses (80-200 chars) without warmth indicators should be polished
    # These often come from strategy/specialist nodes and sound robotic
    is_medium_length = 80 <= len(msg) < _POLISH_MIN_LENGTH
    looks_dry = not has_emoji and not has_exclamation

    # Only skip polish if the content truly doesn't need it
    if not has_list_content and not is_long_enough:
        # Polish if: very short + abrupt, OR medium-length + dry
        should_polish = (is_very_short and looks_abrupt) or (is_medium_length and looks_dry)
        if not should_polish:
            return True, "short_simple_response"

    return False, ""


# =============================================================================
# DETERMINISTIC POLISH (Token-saving warmth injection)
# =============================================================================
# Apply simple deterministic rules to add warmth.
# Empty lists = no warmth injection (professional, system-like tone).

_WARM_OPENERS: list[str] = []
_WARM_CLOSERS: list[str] = []


# =============================================================================
# DETERMINISTIC STRIPPING (Professional tone enforcement)
# =============================================================================
# Strip emojis and filler phrases for professional, system-like tone.
# Unlike _try_deterministic_polish which ADDS warmth, this REMOVES excess enthusiasm.

# Emoji pattern for stripping (broad coverage)
_STRIP_EMOJI_PATTERN = re.compile(
    r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
    r"\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF"
    r"\U00002702-\U000027B0\U000024C2-\U0001F251]+"
)

# Filler phrases to strip (at sentence start only)
_STRIP_PHRASES = frozenset(
    {
        "Got it!",
        "Great!",
        "Perfect!",
        "Awesome!",
        "Wonderful!",
        "I'd be happy to",
        "I'd love to",
        "Absolutely!",
    }
)


def apply_deterministic_strip(msg: str) -> str:
    """
    Strip emojis and filler phrases for professional tone.

    Unlike _try_deterministic_polish which ADDS warmth,
    this REMOVES excess enthusiasm.

    Safety: Only strips at START of message, never globally (protects hotel names, URLs, etc.)
    """
    if not msg:
        return msg or ""

    result = msg

    # Strip emojis
    result = _STRIP_EMOJI_PATTERN.sub("", result)

    # Strip emoji artifacts (variation selector, ZWJ, keycap combining mark)
    result = result.replace("\ufe0f", "").replace("\u200d", "").replace("\u20e3", "")

    # Strip filler phrases at sentence start ONLY
    for phrase in _STRIP_PHRASES:
        if result.startswith(phrase):
            result = result[len(phrase) :].lstrip()
            # Only capitalize if next char is lowercase letter (not URL, code, proper noun)
            if result and result[0].islower():
                result = result[0].upper() + result[1:]
            break  # Only strip one phrase

    # Clean whitespace (but preserve single spaces)
    result = " ".join(result.split())

    return result


def _try_deterministic_polish(msg: str, state: GraphState) -> str | None:
    """
    Try to polish message deterministically without LLM.

    Returns:
        Polished message if deterministic rules apply, None if LLM needed.

    Deterministic polish handles:
    1. Messages that are already warm (just clean up formatting)
    2. Short messages that need a warm opener/closer
    3. Messages with common patterns that can be rule-enhanced
    """
    if not msg:
        return None

    # No warmth injection when lists are empty (professional tone)
    if not _WARM_OPENERS or not _WARM_CLOSERS:
        return None

    # Check warmth indicators
    has_exclamation = "!" in msg
    has_question = "?" in msg

    # Already warm enough - just ensure clean ending
    if has_exclamation and has_question:
        return None  # Already conversational

    # Very short dry messages (<100 chars) - add warm opener
    if len(msg) < 100 and not has_exclamation:
        # Don't modify if it's a question
        if not has_question:
            # Use deterministic selection based on message hash for consistency
            opener_idx = stable_hash_index(msg, len(_WARM_OPENERS))
            opener = _WARM_OPENERS[opener_idx]

            # Make first char lowercase if prepending
            if msg[0].isupper() and not msg.startswith(("I ", "I'")):
                msg_lower_first = msg[0].lower() + msg[1:]
                polished = opener + msg_lower_first
            else:
                polished = opener + msg

            _debug(
                "Deterministic polish: warm opener added",
                original_len=len(msg),
                polished_len=len(polished),
            )
            state.metadata["polish_method"] = "deterministic:opener"
            return polished

    # Messages ending with period but no warmth - add warm closer
    if msg.rstrip().endswith(".") and not has_exclamation and not has_question:
        if len(msg) < 150:  # Only for shorter messages
            closer_idx = stable_hash_index(msg, len(_WARM_CLOSERS))
            closer = _WARM_CLOSERS[closer_idx]
            polished = msg.rstrip(".") + "!" + closer

            _debug(
                "Deterministic polish: warm closer added",
                original_len=len(msg),
                polished_len=len(polished),
            )
            state.metadata["polish_method"] = "deterministic:closer"
            return polished

    # Can't deterministically polish - fall through to LLM
    return None


async def response_polish(state: GraphState) -> GraphState:
    """
    Polish the assistant message for professional tone.
    Applies deterministic stripping only (no LLM).
    """
    _, start_ns = _debug_node_entry("response_polish", state)

    # Check if we should skip polishing
    should_skip, skip_reason = _should_skip_polish(state)
    if should_skip:
        state.metadata["polish_skipped_reason"] = skip_reason
        _polish_stats["polish_skipped"] += 1
        _debug(f"Response polish skipped: {skip_reason}")
        _debug_node_exit("response_polish", state, start_ns)
        return state

    # =========================================================================
    # DETERMINISTIC STRIPPING (removes emojis/filler phrases)
    # =========================================================================
    if state.last_summary:
        stripped = apply_deterministic_strip(state.last_summary)
        if stripped != state.last_summary:
            state.last_summary = stripped
            state.metadata["polish_stripped"] = True
            _debug("📝 DETERMINISTIC_STRIP: Applied emoji/filler removal")

    # =========================================================================
    # DETERMINISTIC POLISH (warmth injection if lists are non-empty)
    # =========================================================================
    deterministic_result = _try_deterministic_polish(state.last_summary, state)
    if deterministic_result is not None:
        state.last_summary = deterministic_result
        _polish_stats["deterministic_polish"] += 1
        _debug(
            "📝 DETERMINISTIC_POLISH: Applied",
            method=state.metadata.get("polish_method", "deterministic"),
        )

    _debug_node_exit("response_polish", state, start_ns)
    return state


# -----------------------
# Message condensation (for long responses)
# -----------------------
# Timeout for condensation LLM call (ms)
_CONDENSE_TIMEOUT_MS = 500


async def condense_long_message(
    message: str,
    max_length: int,
    timeout_ms: int = _CONDENSE_TIMEOUT_MS,
) -> str:
    """
    Condense a message that exceeds max_length using LLM re-summarization.

    Instead of abruptly truncating with ellipsis, this function asks the LLM
    to produce a shorter version that naturally concludes and preserves
    all essential information.

    Args:
        message: The original message to condense.
        max_length: Target maximum character length.
        timeout_ms: Timeout for the LLM call in milliseconds.

    Returns:
        Condensed message, or gracefully truncated fallback if LLM fails.
    """
    if not message or len(message) <= max_length:
        return message

    try:
        prompt = load_prompt("condense")
        # Target ~90% of max length to leave buffer
        target_length = int(max_length * 0.9)
        tpl = prompt.replace("{message}", message).replace("{target_length}", str(target_length))

        timeout_seconds = timeout_ms / 1000.0

        out = await call_llm_with_timeout(
            model="small",
            prompt=tpl,
            timeout_seconds=timeout_seconds,
            max_tokens=512,
            temperature=0.3,
        )

        j = jloads_safe(out)
        condensed = j.get("condensed_message", "").strip()

        if condensed and len(condensed) > 50:
            _debug(
                "Message condensed successfully",
                original_len=len(message),
                condensed_len=len(condensed),
            )
            # If still too long, do a graceful fallback truncation
            if len(condensed) > max_length:
                return _graceful_truncate(condensed, max_length)
            return condensed
        else:
            _debug("Condense returned empty/short response, using fallback")

    except TimeoutError:
        _debug(f"Condense timed out after {timeout_ms}ms, using fallback")
    except Exception as exc:
        _debug_error("Condense failed", error=str(exc))

    # Fallback: graceful truncation at sentence/word boundary
    return _graceful_truncate(message, max_length)


def _graceful_truncate(message: str, max_length: int) -> str:
    """
    Truncate message gracefully at a natural boundary (sentence or word).

    Unlike simple truncation with "...", this finds the last complete
    sentence or word that fits, preserving readability.
    """
    if len(message) <= max_length:
        return message

    # Leave room for ellipsis
    target = max_length - 3

    if target <= 0:
        return message[:max_length]

    truncated = message[:target]

    # Try to find last sentence ending (. ! ?)
    last_sentence = -1
    for punct in ".!?":
        idx = truncated.rfind(punct)
        if idx > last_sentence:
            last_sentence = idx

    # If we found a sentence ending in the last ~30% of text, use it
    if last_sentence > target * 0.7:
        return message[: last_sentence + 1]

    # Otherwise find last word boundary
    last_space = truncated.rfind(" ")
    if last_space > target * 0.5:
        return message[:last_space] + "..."

    # Final fallback
    return truncated + "..."


# =============================================================================
# TILE BUDGET FILTERING (CLIENT-SIDE)
# =============================================================================
# Filter cached tiles by budget constraint without requiring refetch.
# This enables instant budget changes without API calls.

# Budget allocation per vertical (matches mock_provider.py allocations)
_TILE_BUDGET_ALLOCATIONS = {
    "hotel": 0.40,  # 40% of budget for hotels
    "flight": 0.30,  # 30% for flights
    "activity": 0.30,  # 30% for activities
}


def filter_tiles_by_budget(
    tiles_dict: Dict[str, Any],
    budget: Optional[float],
) -> Dict[str, Any]:
    """
    Filter cached tiles by budget constraint (client-side filtering).

    This enables instant budget changes without requiring a refetch of tiles.
    Budget is excluded from the cache key specifically to allow this optimization.

    Args:
        tiles_dict: Dict of tile_id -> tile data
        budget: Total trip budget (filters all tiles)

    Returns:
        Filtered tiles dict with only budget-compliant tiles
    """
    if not budget or not tiles_dict:
        return tiles_dict

    filtered = {}
    for tile_id, tile in tiles_dict.items():
        tile_type = tile.get("type")
        price = tile.get("price_estimate") or tile.get("live_price")

        if price is None:
            # Keep tiles without price info
            filtered[tile_id] = tile
            continue

        # Calculate budget limit for this tile type
        allocation = _TILE_BUDGET_ALLOCATIONS.get(tile_type, 0.33)
        limit = budget * allocation

        if price <= limit:
            filtered[tile_id] = tile

    return filtered


# =============================================================================
# TILE CONTEXT FORMATTING FOR PROMPTS
# =============================================================================
# Format tile data as bullet lists for inclusion in specialist prompts.
# This enables grounded responses that reference real hotel/activity options.


def format_tiles_for_prompt(
    state: "GraphState",
    tile_type: str,
    max_tiles: int = 5,
) -> str:
    """
    Format tiles of a given type for inclusion in specialist prompts.

    Args:
        state: Graph state containing tiles in metadata
        tile_type: One of "hotel", "flight", "activity"
        max_tiles: Maximum number of tiles to include

    Returns:
        Formatted string with bullet list of tile options, or empty string if no tiles
    """
    tiles_dict = state.metadata.get("tiles", {})
    if not tiles_dict:
        return ""

    # Filter tiles by type
    matching_tiles = [tile for tile in tiles_dict.values() if tile.get("type") == tile_type][
        :max_tiles
    ]

    if not matching_tiles:
        return ""

    lines = []
    for tile in matching_tiles:
        # Build bullet point with key fields only (name, price, rating if present)
        name = tile.get("name", "Unknown")
        parts = [f"• {name}"]

        if tile.get("price"):
            price = tile["price"]
            currency = tile.get("currency", "USD")
            parts.append(f"({currency} {price})")

        if tile.get("rating"):
            parts.append(f"★{tile['rating']}")

        if tile.get("neighborhood"):
            parts.append(f"in {tile['neighborhood']}")

        lines.append(" ".join(parts))

    return "\n".join(lines)


def get_available_options_context(state: "GraphState", intent: str) -> str:
    """
    Get formatted tile context for a specialist based on intent.

    Args:
        state: Graph state
        intent: Specialist intent (hotels, flights, activities)

    Returns:
        Formatted context string for prompt injection, or empty string
    """
    type_map = {
        "hotels": "hotel",
        "flights": "flight",
        "activities": "activity",
    }
    tile_type = type_map.get(intent)
    if not tile_type:
        return ""

    tiles_context = format_tiles_for_prompt(state, tile_type)
    if not tiles_context:
        return ""

    return f"\n\nAvailable {intent.title()} Options:\n{tiles_context}\n"


# =============================================================================
# SAFETY SNIPPET INJECTION (Travel advisory augmentation)
# =============================================================================
# Loads safety snippets from JSON and appends to responses for international travel.

_SAFETY_SNIPPETS_CACHE: Optional[Dict[str, Any]] = None


def _load_safety_snippets() -> Dict[str, Any]:
    """Load safety snippets from JSON file (cached)."""
    global _SAFETY_SNIPPETS_CACHE
    if _SAFETY_SNIPPETS_CACHE is not None:
        return _SAFETY_SNIPPETS_CACHE

    snippets_path = Path(__file__).parent / "safety_snippets.json"
    try:
        with open(snippets_path, "r", encoding="utf-8") as f:
            _SAFETY_SNIPPETS_CACHE = json.load(f)
    except Exception as e:
        _debug_error("Failed to load safety snippets", error=str(e))
        _SAFETY_SNIPPETS_CACHE = {"regions": {}, "country_to_region": {}}

    return _SAFETY_SNIPPETS_CACHE


def _get_region_for_place(place: str, snippets: Dict[str, Any]) -> Optional[str]:
    """Map a place name to its region."""
    country_map = snippets.get("country_to_region", {})

    # Direct lookup
    if place in country_map:
        return country_map[place]

    # Case-insensitive lookup
    place_lower = place.lower()
    for country, region in country_map.items():
        if country.lower() == place_lower:
            return region

    # Check if place is a known region directly
    regions = snippets.get("regions", {})
    if place in regions:
        return place

    return None


def _get_safety_snippet(
    origin: Optional[str],
    destinations: List[str],
    snippets: Dict[str, Any],
) -> Optional[str]:
    """
    Generate a safety snippet for international travel.

    Args:
        origin: Origin city/country
        destinations: List of destination cities/countries
        snippets: Loaded safety snippets data

    Returns:
        1-2 line safety snippet, or None if not applicable
    """
    if not destinations:
        return None

    # Get origin region
    origin_region = _get_region_for_place(origin, snippets) if origin else None

    # Get destination regions
    dest_regions = set()
    for dest in destinations:
        region = _get_region_for_place(dest, snippets)
        if region:
            dest_regions.add(region)

    if not dest_regions:
        return None

    # Check if trip is international (origin region != destination region)
    if origin_region and origin_region in dest_regions and len(dest_regions) == 1:
        # Domestic trip - no safety snippet needed
        return None

    regions_data = snippets.get("regions", {})

    # Build snippet from first destination region that has data
    for dest_region in dest_regions:
        region_data = regions_data.get(dest_region)
        if not region_data:
            continue

        # Start with default entry text
        default_data = region_data.get("default", {})
        entry_text = default_data.get("entry", "")

        # Check for origin-specific override
        if origin_region:
            by_origin = region_data.get("by_origin_region", {})
            origin_override = by_origin.get(origin_region, {})
            if origin_override.get("entry"):
                entry_text = origin_override["entry"]

        if entry_text:
            return entry_text

    return None


def _maybe_append_safety_snippet(state: GraphState) -> str:
    """
    Append safety snippet to last_summary if conditions are met.

    Conditions:
    - destinations is non-empty
    - trip is international (origin region != destination region)
    - snippet not yet shown for this destination set

    Returns:
        Updated message with safety snippet appended, or original message
    """
    msg = state.last_summary or ""
    if not msg:
        return msg

    ti = state.trip_inputs
    if not ti.destinations:
        return msg

    # Check if safety snippet already shown for these destinations
    shown_for = set(state.metadata.get("safety_snippet_shown_for", []))
    dest_key = ",".join(sorted(ti.destinations))

    if dest_key in shown_for:
        return msg

    # Load snippets and generate
    snippets = _load_safety_snippets()
    snippet = _get_safety_snippet(ti.origin, ti.destinations, snippets)

    if not snippet:
        return msg

    # Mark as shown
    shown_for.add(dest_key)
    state.metadata["safety_snippet_shown_for"] = list(shown_for)

    # Append snippet to message
    _debug("Appending safety snippet", destinations=ti.destinations, origin=ti.origin)

    # Add a line break and the snippet
    if msg.rstrip().endswith("?"):
        # If message ends with question, put snippet on new line
        return f"{msg}\n\n{snippet}"
    else:
        # Otherwise append after a space/newline
        return f"{msg}\n\n{snippet}"


def _are_suggestions_stale(ti: "TripInputs", suggestions: List[str]) -> bool:
    """
    Check if suggestions are stale (about booking types already enabled).

    Returns True if suggestions mention booking types that are already complete,
    indicating they should be refreshed with new booking options.
    """
    if not suggestions:
        return True

    booking_types = ti.booking_types or {}
    suggestions_lower = [s.lower() for s in suggestions]
    joined = " ".join(suggestions_lower)

    # Check if suggestions are about flights when flights already enabled
    if _is_booking_enabled(booking_types.get("flights")):
        flight_keywords = ["economy", "business", "first class", "direct flight", "cabin", "flight"]
        if any(kw in joined for kw in flight_keywords):
            return True

    # Check if suggestions are about hotels when hotels already enabled
    if _is_booking_enabled(booking_types.get("hotels")):
        hotel_keywords = ["star", "hotel", "amenities", "resort", "boutique"]
        if any(kw in joined for kw in hotel_keywords):
            return True

    # Check if suggestions are about activities when activities already enabled
    if _is_booking_enabled(booking_types.get("activities")):
        activity_keywords = ["activity", "tour", "adventure", "excursion"]
        if any(kw in joined for kw in activity_keywords):
            return True

    return False


def _build_booking_suggestions(
    ti: "TripInputs",
    primary_action: Optional[str] = None,
    max_suggestions: int = 3,
) -> List[str]:
    """
    Build context-aware suggestions that advance the booking.

    Prioritizes booking actions (flights, hotels, activities) that aren't yet enabled,
    then falls back to budget if missing.

    Args:
        ti: TripInputs to check booking_types and budget
        primary_action: Optional primary suggestion to always include first (e.g., "Yes, generate!")
        max_suggestions: Maximum number of suggestions to return

    Returns:
        List of actionable suggestions
    """
    suggestions = []

    # Add primary action first if provided
    if primary_action:
        suggestions.append(primary_action)

    # Fallback: suggest budget if still missing and we have room
    if len(suggestions) < max_suggestions and ti.budget is None:
        suggestions.append("Set budget")

    # No generic fallback - only show actionable suggestions

    return suggestions[:max_suggestions]


def _should_generate_suggestions(state: GraphState) -> bool:
    """
    Check if suggestions should be generated based on ui_phase.

    Returns False when ui_phase == "expanded" (full planner UI) since
    suggestions are redundant when all input controls are visible.
    Default (None or "bootstrap") returns True.
    """
    ui_phase = state.metadata.get("ui_phase") or "bootstrap"
    return ui_phase != "expanded"


def summarize(state: GraphState) -> GraphState:
    """Optional micro-summarizer node."""
    _, start_ns = _debug_node_entry("summarize", state)
    # Track if we generated a fallback response
    generated_fallback = False

    # =========================================================================
    # READY-TO-GENERATE STATE TRANSITION (v14 - stale budget loop fix)
    # =========================================================================
    # When plan_just_became_ready is True, we need to:
    # 1. Clear the stale last_summary (which was asking for fields)
    # 2. Clear stale suggested_responses
    # 3. Generate a fresh "ready to generate" message
    # This prevents the bug where budget questions keep repeating after
    # user provides the budget and plan is complete.
    # =========================================================================
    plan_just_ready = state.metadata.get("plan_just_became_ready", False)
    if plan_just_ready:
        ti = state.trip_inputs
        destinations = ti.destinations or []
        dest_str = ", ".join(destinations) if destinations else "your destination"

        # Build brief acknowledgment instead of verbose constraints display
        # Format: "Got it, [destination] from [origin] on [date]" or similar
        ack_parts = []
        if destinations:
            ack_parts.append(dest_str)
        if ti.origin:
            ack_parts.append(f"from {ti.origin}")
        if ti.start_date:
            # Format date nicely
            try:
                from datetime import datetime

                date_obj = datetime.strptime(ti.start_date, "%Y-%m-%d")
                date_str = date_obj.strftime("%b %d")  # e.g., "Jan 21"
            except (ValueError, TypeError):
                date_str = ti.start_date
            ack_parts.append(f"on {date_str}")

        # Generate brief acknowledgment
        if ack_parts:
            state.last_summary = f"Got it, {' '.join(ack_parts)}."
        else:
            state.last_summary = "Ready to generate your plan."
        # Build context-aware suggestions focused on advancing the booking
        state.suggested_responses = _build_booking_suggestions(ti, primary_action="Generate plan")
        state.question_target = None  # Clear stale question target
        state.metadata["question_target"] = None  # SSoT sync
        state.metadata["response_writer_node"] = "summarize:ready"
        state.metadata["response_generation_provenance"] = "deterministic"
        # Set pending_action so YES_PATTERN triggers generate_plan
        state.metadata["pending_action"] = "generate_plan"
        # Clear the flag so it doesn't fire again
        state.metadata["plan_just_became_ready"] = False

        _debug(
            "Summarize: generated ready-to-generate message (plan just became ready)",
            destinations=dest_str,
        )
        _debug_node_exit("summarize", state, start_ns)
        return state

    # =========================================================================
    # SUGGESTION FILTERING BASED ON USER REQUEST TYPE
    # =========================================================================
    # When user made an explicit request (generate, expand), don't show redundant suggestions
    user_request_type = state.metadata.get("user_request_type")
    if user_request_type and state.suggested_responses:
        filtered_suggestions = []
        for suggestion in state.suggested_responses:
            suggestion_lower = suggestion.lower()
            # Don't show "Show more details" if user just asked for it
            if user_request_type == "expand" and "more detail" in suggestion_lower:
                continue
            # Don't show "generate" suggestions if user just asked to generate
            if user_request_type == "generate" and (
                "generate" in suggestion_lower or "itinerary" in suggestion_lower
            ):
                continue
            filtered_suggestions.append(suggestion)
        if filtered_suggestions != state.suggested_responses:
            _debug(
                "Filtered suggestions based on user_request_type",
                user_request_type=user_request_type,
                original_count=len(state.suggested_responses),
                filtered_count=len(filtered_suggestions),
            )
            state.suggested_responses = filtered_suggestions
        # Clear the request type after filtering
        state.metadata.pop("user_request_type", None)

    # If no assistant message, generate a default follow-up question
    if not state.last_summary:
        trip_inputs_dict = state.trip_inputs.model_dump(exclude_none=True)
        missing = compute_trip_readiness(trip_inputs_dict).missing_core
        _debug(
            "Summarize fallback triggered",
            missing=missing,
            last_summary_was=repr(state.last_summary),
        )
        user_intent = state.metadata.get("user_intent", "detailed_planner")
        user_tone = state.metadata.get("user_tone", "neutral")
        # Use the version that returns both question and field for tracking
        default_question, asked_field = _default_follow_up_with_field(
            missing, user_intent, user_tone, trip_inputs_dict
        )
        if default_question:
            state.last_summary = default_question
            generated_fallback = True
            if asked_field:
                state.metadata["last_question_field"] = asked_field
                _debug(
                    "Summarize set default question", question=default_question, field=asked_field
                )
            else:
                _debug("Summarize set default question", question=default_question)
        else:
            _debug("Summarize: no default question available")
    else:
        _debug(
            "Summarize: last_summary already set",
            preview=state.last_summary[:80] if state.last_summary else "",
        )
        # Even when message is set, refresh suggestions to reflect current booking state
        # This prevents stale suggestions from specialists when their category is complete
        ti = state.trip_inputs
        if not state.suggested_responses or _are_suggestions_stale(ti, state.suggested_responses):
            state.suggested_responses = _build_booking_suggestions(ti)
            _debug(
                "Summarize: refreshed stale suggestions",
                new_suggestions=state.suggested_responses,
            )

    # =========================================================================
    # SAFETY SNIPPET AUGMENTATION
    # =========================================================================
    # Append safety snippet for international travel if not already shown
    if state.last_summary:
        state.last_summary = _maybe_append_safety_snippet(state)

    # Set provenance if summarize generated the fallback response
    if generated_fallback:
        state.metadata["response_writer_node"] = "summarize"
        state.metadata["response_generation_provenance"] = "deterministic"

    # =========================================================================
    # EMPTY RESPONSE GUARD (v15 - prevent empty responses)
    # =========================================================================
    # Ensure we never return an empty response to the user. This catches edge cases
    # where LLM parsing failed or no fallback was generated.
    if not state.last_summary or not state.last_summary.strip():
        _debug("Summarize: empty response detected, generating emergency fallback")
        ti = state.trip_inputs
        destinations = ti.destinations or []

        # Check context to provide relevant fallback
        if state.pending_strategy_expansion:
            # User was in strategy flow
            topic = state.metadata.get("last_strategy_topic", "trip")
            dest_str = destinations[0] if destinations else "destination"
            state.last_summary = f"{topic.capitalize()} to {dest_str}."
            state.suggested_responses = _build_booking_suggestions(
                ti, primary_action="Generate plan"
            )
            state.metadata["response_writer_node"] = "summarize:strategy_fallback"
        elif len(destinations) > 0:
            # Has destinations - offer to generate
            dest_str = ", ".join(destinations)
            trip_inputs_dict = ti.model_dump(exclude_none=True) if hasattr(ti, "model_dump") else ti
            readiness = compute_trip_readiness(trip_inputs_dict)
            if readiness.core_complete:
                state.last_summary = f"Ready to generate. {dest_str}."
                state.suggested_responses = _build_booking_suggestions(
                    ti, primary_action="Generate plan"
                )
                state.metadata["pending_action"] = "generate_plan"
            else:
                # Still missing core fields - state what's needed
                missing_str = ", ".join(readiness.missing_core[:2])
                state.last_summary = f"{dest_str}. Missing: {missing_str}."
                state.suggested_responses = _build_booking_suggestions(ti)
            state.metadata["response_writer_node"] = "summarize:dest_fallback"
        else:
            # No context - ask for destination
            state.last_summary = "Destination?"
            state.suggested_responses = ["Beach", "City", "Mountains"]
            state.metadata["response_writer_node"] = "summarize:generic_fallback"

        state.metadata["response_generation_provenance"] = "template"
        _debug(
            "Summarize: generated emergency fallback",
            response_writer_node=state.metadata.get("response_writer_node"),
        )

    # =========================================================================
    # UI PHASE BASED SUGGESTION SUPPRESSION
    # =========================================================================
    # In expanded mode, clear suggestions since all input controls are visible
    if not _should_generate_suggestions(state):
        if state.suggested_responses:
            _debug(
                "Summarize: suppressing suggestions for ui_phase=expanded",
                suppressed_count=len(state.suggested_responses),
            )
        state.suggested_responses = []

    _debug_node_exit("summarize", state, start_ns)
    return state


# -----------------------
# Branch post-processing (new node)
# -----------------------
def branch_postprocess(state: GraphState) -> GraphState:
    """
    Post-process branches: split by destination if multi_city_intent != 'multi_city',
    normalize all branch specs, and generate unique IDs.
    """
    _, start_ns = _debug_node_entry("branch_postprocess", state)

    if not state.branches:
        _debug("No branches to post-process")
        _debug_node_exit("branch_postprocess", state, start_ns)
        return state

    ti = state.trip_inputs
    fallback_inputs = ti.model_dump(exclude_none=True)

    # If multi_city_intent is not "multi_city" and we have multiple destinations,
    # split branches by destination
    if ti.multi_city_intent != "multi_city" and len(ti.destinations) > 1:
        _debug("Splitting branches by destination", destinations=ti.destinations)
        new_branches: List[Dict[str, Any]] = []
        for branch in state.branches:
            branch_dests = branch.get("destinations", [])
            if len(branch_dests) > 1:
                # Split this branch into one per destination
                for dest in branch_dests:
                    split_branch = dict(branch)
                    split_branch["id"] = uuid4().hex[:8]
                    split_branch["destinations"] = [dest]
                    split_branch["label"] = f"{dest} Trip"
                    normalized = _normalize_branch_spec(split_branch, fallback_inputs)
                    if normalized:
                        new_branches.append(normalized)
            else:
                normalized = _normalize_branch_spec(branch, fallback_inputs)
                if normalized:
                    new_branches.append(normalized)
        state.branches = new_branches
    else:
        # Just normalize all branches - filter out None values explicitly
        normalized_branches: List[Dict[str, Any]] = []
        for b in state.branches:
            normalized = _normalize_branch_spec(b, fallback_inputs)
            if normalized:
                normalized_branches.append(normalized)
        state.branches = normalized_branches

    # Ensure all branches have unique IDs
    seen_ids: set[str] = set()
    for branch in state.branches:
        if not branch.get("id") or branch["id"] in seen_ids:
            branch["id"] = uuid4().hex[:8]
        seen_ids.add(branch["id"])

    _debug("Branch post-processing complete", branches=len(state.branches))
    _debug_node_exit("branch_postprocess", state, start_ns)
    return state


# =============================================================================
# TILE SEARCH GATING (MVP Hardening)
# =============================================================================
# Just-in-time tile search with strict gating on core field readiness.


def should_run_tile_search(state: "GraphState", intent: str) -> bool:
    """
    Check if tile search prerequisites are met for a given intent.

    Returns True only if:
    - Intent is tile-searchable (hotels, activities, flights)
    - Required core fields are present for that intent

    Args:
        state: Current graph state
        intent: The specialist intent (hotels, activities, flights)

    Returns:
        True if tile search can run, False otherwise
    """
    ti = state.trip_inputs

    # Only these intents use tiles
    tile_intents = {"hotels", "activities", "flights"}
    if intent not in tile_intents:
        return False

    # Must have destinations
    if not ti.destinations:
        _debug(f"Tile search blocked for {intent}: missing destinations")
        return False

    # Must have start_date
    if not ti.start_date:
        _debug(f"Tile search blocked for {intent}: missing start_date")
        return False

    # Flights additionally require origin
    if intent == "flights" and not ti.origin:
        _debug(f"Tile search blocked for {intent}: missing origin")
        return False

    return True


def needs_tiles(intent: str, state: "GraphState") -> bool:
    """
    Check if a specialist needs tile context for grounding.

    Returns True if:
    - Intent is in {hotels, activities, flights} (grounding-required)
    - AND either booking_types for that domain is True
    - OR user asked for "options/prices/book" signals

    Args:
        intent: The specialist intent
        state: Current graph state

    Returns:
        True if tiles are needed for grounding, False otherwise
    """
    # Only these intents use tiles for grounding
    tile_intents = {"hotels", "activities", "flights"}
    if intent not in tile_intents:
        return False

    # Check if booking_types enabled for this domain
    booking_types = state.trip_inputs.booking_types or {}
    booking_type_map = {
        "hotels": "hotels",
        "activities": "activities",
        "flights": "flights",
    }
    booking_key = booking_type_map.get(intent)
    if booking_key and booking_types.get(booking_key):
        return True

    # Check for "options/prices/book" signals in user text
    user_text_lower = (state.user_text or "").lower()
    option_signals = {
        "options",
        "prices",
        "book",
        "booking",
        "availability",
        "show me",
        "find me",
        "what are",
        "compare",
        "recommend",
    }
    if any(signal in user_text_lower for signal in option_signals):
        return True

    return False


# =============================================================================
# TILE CACHE (V6 UNIFIED) - Bounded with TTL
# =============================================================================
# Cache tile search results per session/intent/destination.
# TTL: 5 minutes (tiles change infrequently within session)
# Bounded: max 100 entries to prevent memory leaks

_TILE_CACHE_TTL = 300  # 5 minutes
_TILE_CACHE_MAXSIZE = 100

_tile_cache: TTLCache = TTLCache(maxsize=_TILE_CACHE_MAXSIZE, ttl=_TILE_CACHE_TTL)


def _compute_settings_hash(intent: str, trip_inputs: "TripInputs") -> str:
    """
    Compute a hash of the settings relevant to a specific vertical.

    This ensures cache invalidation when user preferences change:
    - hotel: min_stars, amenities
    - flight: cabin_class, direct_only, round_trip
    - activity: categories, skill_level

    Args:
        intent: The vertical type (hotel, flight, activity)
        trip_inputs: The TripInputs containing settings

    Returns:
        16-char hash of relevant settings, or "default" if no settings
    """
    settings_str = ""

    # Helper to get attribute from dict or model
    def _get(obj, key, default=None):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    if intent == "hotel" and trip_inputs.hotel_settings:
        hs = trip_inputs.hotel_settings
        # Sort amenities for consistent hashing
        amenities = ",".join(sorted(_get(hs, "amenities") or []))
        settings_str = f"stars:{_get(hs, 'min_stars', 0)}|amenities:{amenities}"

    elif intent == "flight" and trip_inputs.flight_settings:
        fs = trip_inputs.flight_settings
        cabin = _get(fs, "cabin_class", "economy")
        direct = _get(fs, "direct_only", False)
        rt = _get(fs, "round_trip", True)
        settings_str = f"cabin:{cabin}|direct:{direct}|rt:{rt}"

    elif intent == "activity" and trip_inputs.activity_settings:
        acts = trip_inputs.activity_settings
        # Sort categories for consistent hashing
        categories = ",".join(sorted(_get(acts, "categories") or []))
        settings_str = f"cats:{categories}|skill:{_get(acts, 'skill_level') or 'any'}"

    if not settings_str:
        return "default"

    return hashlib.md5(settings_str.encode()).hexdigest()[:16]


def _compute_tile_cache_key_v6(
    intent: str,
    destinations: List[str],
    start_date: Optional[str],
    origin: Optional[str],
) -> str:
    """V6: Compute cache key for tile search results with version isolation."""
    dest_hash = hashlib.md5(",".join(sorted(destinations or [])).encode()).hexdigest()[:16]
    node_version = NODE_LOGIC_VERSION.get("tile", 0)
    key_parts = (
        f"tile_v6|{intent}|{dest_hash}|{start_date or 'none'}|{origin or 'none'}|"
        f"v{CACHE_SCHEMA_VERSION}.{node_version}|{PLANNER_BUILD_ID}"
    )
    return hashlib.md5(key_parts.encode()).hexdigest()


def ensure_tiles(
    state: "GraphState",
    intent: str,
    timeout_ms: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    MIGRATED: Now delegates to unified caching framework.

    Ensure tiles are available for grounding, with validated caching.

    Args:
        state: Current graph state
        intent: The specialist intent
        timeout_ms: Optional timeout override (defaults to settings.tile_search_timeout_ms)

    Returns:
        Dict of tiles if available, None if not needed or failed
    """
    from app.planner.cache.framework import TileCache

    # Gate check
    if not needs_tiles(intent, state) or not should_run_tile_search(state, intent):
        return None

    ti = state.trip_inputs
    tile_cache = TileCache.get_instance()

    # Compute query hash from parameters (matches compat.py pattern)
    # v2: Include end_date, adults, children for correct tile prices/night counts
    # v3: Include settings hash for cache invalidation on preference changes
    # Note: budget excluded - filtered client-side for instant budget changes
    settings_hash = _compute_settings_hash(intent, ti)
    query_str = (
        f"{intent}|"
        f"{','.join(sorted(ti.destinations or []))}|"
        f"{ti.start_date or 'none'}|"
        f"{ti.end_date or 'none'}|"
        f"{ti.origin or 'none'}|"
        f"{ti.adults or 0}|"
        f"{ti.children or 0}|"
        f"{settings_hash}"
    )
    query_hash = hashlib.md5(query_str.encode()).hexdigest()[:16]

    cache_key = tile_cache.compute_key(
        session_id="global",
        tile_type=intent,
        query_hash=query_hash,
    )

    # Use framework's get method with version validation
    result = tile_cache.get(cache_key, state)
    if result is not None:
        _debug(f"Tile cache hit for {intent}", cache_key=cache_key[:16])
        state.metadata["tile_cache_hit"] = True
        return result

    # Cache miss
    state.metadata["tile_cache_miss"] = True
    state.metadata["tiles_needed_for"] = intent

    return None


def set_tile_cached(
    intent: str,
    destinations: List[str],
    start_date: Optional[str],
    end_date: Optional[str],
    origin: Optional[str],
    adults: Optional[int],
    children: Optional[int],
    result: Dict[str, Any],
    settings_hash: str = "default",
) -> None:
    """MIGRATED: Now delegates to unified caching framework."""
    from app.planner.cache.framework import TileCache

    tile_cache = TileCache.get_instance()

    # Compute query hash from parameters (matches ensure_tiles pattern)
    # v2: Include end_date, adults, children for correct tile prices/night counts
    # v3: Include settings hash for cache invalidation on preference changes
    query_str = (
        f"{intent}|"
        f"{','.join(sorted(destinations or []))}|"
        f"{start_date or 'none'}|"
        f"{end_date or 'none'}|"
        f"{origin or 'none'}|"
        f"{adults or 0}|"
        f"{children or 0}|"
        f"{settings_hash}"
    )
    query_hash = hashlib.md5(query_str.encode()).hexdigest()[:16]

    cache_key = tile_cache.compute_key(
        session_id="global",
        tile_type=intent,
        query_hash=query_hash,
    )

    tile_cache.set(
        cache_key,
        result,
        extra={
            "intent": intent,
            "destinations": destinations,
            "start_date": start_date,
            "end_date": end_date,
            "origin": origin,
            "adults": adults,
            "children": children,
            "settings_hash": settings_hash,
        },
    )

    _debug(
        "TILE_CACHE_SET",
        key_prefix=cache_key[:16],
        intent=intent,
    )


def clear_tile_cache() -> int:
    """MIGRATED: Now delegates to unified caching framework."""
    from app.planner.cache.framework import TileCache

    tile_cache = TileCache.get_instance()
    count = len(tile_cache._cache)
    tile_cache.clear()
    return count


def get_tile_cache_stats() -> Dict[str, Any]:
    """MIGRATED: Now delegates to unified caching framework."""
    from app.planner.cache.framework import TileCache

    tile_cache = TileCache.get_instance()
    return tile_cache.get_stats()


# -----------------------
# Tile search node (integrated with tile_service)
# -----------------------
async def tile_search(state: GraphState) -> GraphState:
    """
    Search for tiles based on branches and booking_types.
    Calls tile_service.search_tiles for each branch.
    Pre-fetches Unsplash images for destinations to populate cache.

    MVP Hardening: Now includes strict gating on core field readiness.
    """
    _, start_ns = _debug_node_entry("tile_search", state)

    # =========================================================================
    # MVP GATE: Check core field prerequisites before tile search
    # =========================================================================
    ti = state.trip_inputs
    if not ti.destinations or not ti.start_date:
        _debug(
            "Tile search blocked: missing core prerequisites",
            has_destinations=bool(ti.destinations),
            has_start_date=bool(ti.start_date),
        )
        state.metadata["tile_search_blocked"] = "missing_core_fields"
        _debug_node_exit("tile_search", state, start_ns)
        return state

    # Check if any booking types are enabled (tri-state: suggested or on)
    booking_types = state.trip_inputs.booking_types or {}
    any_enabled = any(_is_booking_enabled(v) for v in booking_types.values())

    if not any_enabled:
        _debug("No booking types enabled, skipping tile search")
        _debug_node_exit("tile_search", state, start_ns)
        return state

    if not state.branches:
        _debug("No branches to search tiles for")
        _debug_node_exit("tile_search", state, start_ns)
        return state

    ti = state.trip_inputs
    tiles_dict: Dict[str, Any] = {}

    # Determine which verticals to search based on booking_types (tri-state)
    verticals: List[str] = []
    if _is_booking_enabled(booking_types.get("hotels")):
        verticals.append("hotel")
    if _is_booking_enabled(booking_types.get("flights")):
        verticals.append("flight")
    if _is_booking_enabled(booking_types.get("activities")):
        verticals.append("activity")

    if not verticals:
        _debug("No verticals enabled despite booking types set")
        _debug_node_exit("tile_search", state, start_ns)
        return state

    # Search tiles for the primary branch only (idx == 0), matching plan.py behavior
    for idx, branch in enumerate(state.branches):
        if idx != 0:
            # plan.py only searches tiles for the primary branch
            continue

        branch_id = branch.get("id", f"branch_{idx}")
        branch_destinations = branch.get("destinations", [])
        primary_dest = branch_destinations[0] if branch_destinations else None

        if not primary_dest:
            _debug(f"Branch {branch_id} has no destination, skipping tile search")
            continue

        # Pre-fetch ALL Unsplash image variants for destination to populate cache
        # This ensures tiles and branches use cached Unsplash images with unique variants
        try:
            from app.services.unsplash import prefetch_destination_images

            num_cached = await prefetch_destination_images(primary_dest)
            _debug(f"Pre-fetched {num_cached} image variants for destination: {primary_dest}")
        except Exception as e:
            _debug(f"Image prefetch failed for {primary_dest}: {e}")

        try:
            # =================================================================
            # CACHE CHECK: Try to get cached tiles for each vertical
            # =================================================================
            verticals_to_fetch: List[str] = []
            cache_hits = 0
            cache_misses = 0

            for vertical in verticals:
                cached_result = ensure_tiles(state, vertical)
                if cached_result:
                    # Cache hit - use cached tiles
                    cache_hits += 1
                    cached_tiles = cached_result if isinstance(cached_result, dict) else {}
                    # Regenerate image URLs using current cache (may have fresh Unsplash images)
                    from app.services.unsplash import get_image_url_sync

                    for tile_id, tile_data in cached_tiles.items():
                        # Update image_url if we have a better one from Unsplash cache
                        if "image_url" in tile_data and primary_dest:
                            # Use tile index for variant selection
                            tile_idx = list(cached_tiles.keys()).index(tile_id)
                            new_url = get_image_url_sync(
                                primary_dest, variant=tile_idx % 6, width=400, height=250
                            )
                            if "unsplash" in new_url:
                                tile_data["image_url"] = new_url
                        tiles_dict[tile_id] = tile_data
                    _debug(f"Tile cache HIT for {vertical}", count=len(cached_tiles))
                else:
                    # Cache miss - need to fetch this vertical
                    cache_misses += 1
                    verticals_to_fetch.append(vertical)
                    _debug(f"Tile cache MISS for {vertical}")

            # =================================================================
            # FETCH: Only fetch verticals that are cache misses
            # =================================================================
            if verticals_to_fetch:
                tiles_request = TilesSearchRequest(
                    branch_id=branch_id,
                    destination=primary_dest,
                    destination_hint=primary_dest,
                    origin=branch.get("origin") or ti.origin,
                    start_date=branch.get("start_date") or ti.start_date,
                    end_date=branch.get("end_date") or ti.end_date,
                    adults=branch.get("adults") or ti.adults,
                    children=branch.get("children") or ti.children,
                    requires_assistance=branch.get("requires_assistance") or ti.requires_assistance,
                    currency=branch.get("currency") or ti.currency or DEFAULT_CURRENCY,
                    verticals=verticals_to_fetch,  # type: ignore
                    max_results_per_vertical=5,
                    budget=ti.budget,  # Pass budget for tile filtering
                    # Pass user preference settings for filtering
                    flight_settings=ti.flight_settings,
                    hotel_settings=ti.hotel_settings,
                    activity_settings=ti.activity_settings,
                )

                _debug(
                    f"Fetching tiles for branch {branch_id}",
                    destination=primary_dest,
                    verticals=verticals_to_fetch,
                )
                tiles_response = search_tiles(tiles_request)

                # Group fetched tiles by vertical for caching
                tiles_by_vertical: Dict[str, Dict[str, Any]] = {}
                for tile in tiles_response.tiles:
                    tile_data = tile.model_dump()
                    tiles_dict[tile.id] = tile_data
                    vertical_key = tile.type
                    if vertical_key not in tiles_by_vertical:
                        tiles_by_vertical[vertical_key] = {}
                    tiles_by_vertical[vertical_key][tile.id] = tile_data

                # =================================================================
                # CACHE SET: Store fetched tiles in cache per vertical
                # =================================================================
                for vertical, vertical_tiles in tiles_by_vertical.items():
                    set_tile_cached(
                        intent=vertical,
                        destinations=ti.destinations or [],
                        start_date=ti.start_date,
                        end_date=ti.end_date,
                        origin=ti.origin,
                        adults=ti.adults,
                        children=ti.children,
                        result=vertical_tiles,
                        settings_hash=_compute_settings_hash(vertical, ti),
                    )
                    _debug(f"Cached {len(vertical_tiles)} tiles for {vertical}")

            # Store tiles and update branch tile IDs
            branch_tiles: Dict[str, List[str]] = {"stays": [], "flights": [], "activities": []}

            for tile_id, tile_data in tiles_dict.items():
                tile_type = tile_data.get("type")
                if tile_type == "hotel":
                    branch_tiles["stays"].append(tile_id)
                elif tile_type == "flight":
                    branch_tiles["flights"].append(tile_id)
                elif tile_type == "activity":
                    branch_tiles["activities"].append(tile_id)

            # Update branch with tile IDs
            branch["tiles"] = branch_tiles

            _debug(
                f"Tiles found for branch {branch_id}",
                hotels=len(branch_tiles["stays"]),
                flights=len(branch_tiles["flights"]),
                activities=len(branch_tiles["activities"]),
                cache_hits=cache_hits,
                cache_misses=cache_misses,
            )

        except Exception as e:
            _debug_error(f"Tile search failed for branch {branch_id}", error=str(e))
            continue

    # =================================================================
    # BUDGET FILTER: Apply client-side budget filtering to all tiles
    # =================================================================
    if ti.budget:
        tiles_dict = filter_tiles_by_budget(tiles_dict, ti.budget)
        _debug(f"Applied budget filter ({ti.budget})", remaining_tiles=len(tiles_dict))

    # Store tiles in metadata for later persistence
    state.metadata["tiles"] = tiles_dict
    state.metadata["tile_search_attempted"] = True
    state.metadata["tile_search_booking_types"] = verticals

    _debug(
        "Tile search completed",
        total_tiles=len(tiles_dict),
        enabled_verticals=verticals,
    )
    _debug_node_exit("tile_search", state, start_ns)
    return state


# -----------------------
# Generate responder (handles GENERATE_PLAN_NOW trigger)
# -----------------------
async def generate_responder(state: GraphState) -> GraphState:
    """
    Handle explicit plan generation requests.

    This node is reached when the user triggers plan generation
    (e.g., "GENERATE_PLAN_NOW" or confirmation of generate action).

    It creates default branches from trip_inputs and sets ready_to_generate=True.
    When the user explicitly requests generation, we proceed even with partial data.

    Also calls relevant strategy nodes to enrich branches with vibe, highlights, flow, notes.
    """
    from app.planner.nodes.strategy.orchestrator import (
        merge_strategy_results,
        orchestrate_strategies,
    )

    _, start_ns = _debug_node_entry("generate_responder", state)

    # Clear stale strategy_sections to prevent showing old data during destination changes
    if state.metadata:
        state.metadata.pop("strategy_sections", None)

    ti = state.trip_inputs

    # Minimum requirement: at least destinations must be set
    # When user explicitly requests generation, we're more lenient
    if not ti.destinations or len(ti.destinations) == 0:
        # Absolutely cannot generate without destinations
        state.last_summary = "Missing: destination."
        state.question_target = "destinations"
        state.ready_to_generate = False
        _debug("Generate blocked - no destinations")
        _debug_node_exit("generate_responder", state, start_ns)
        return state

    # All core fields complete - create branches and set ready
    state.ready_to_generate = True
    state.last_summary = "Generating plan."

    # NOTE: We intentionally do NOT auto-enable booking types here.
    # The tri-state model (off/suggested/on) means user scope preferences
    # are preserved. Tile search treats 'suggested' and 'on' as enabled.

    # Call strategy orchestrator to get enriched content
    strategy_results = await orchestrate_strategies(state)
    merged_content = merge_strategy_results(strategy_results)

    _debug(
        "Strategy orchestration complete",
        topics=list(strategy_results.keys()),
        has_vibe=bool(merged_content.vibe),
        highlights_count=len(merged_content.highlights),
    )

    # Set strategy_stage to 2 (S2_STRATEGY_READY) after strategy orchestration
    # This enables the frontend to display the plan view state correctly
    meta = state.metadata or {}
    meta["strategy_stage"] = 2
    state.metadata = meta

    # Create a default branch from trip_inputs with strategy enrichment
    fallback_inputs = ti.model_dump(exclude_none=True)
    default_branch = {
        "id": uuid4().hex[:8],
        "label": f"{ti.destinations[0]} Trip" if ti.destinations else "Your Trip",
        "description": merged_content.vibe or f"Your adventure in {ti.destinations[0]}",
        "destinations": ti.destinations or [],
        "origin": ti.origin,
        "start_date": ti.start_date,
        "end_date": ti.end_date,
        "adults": ti.adults,
        "children": ti.children,
        "booking_types": ti.booking_types,
        "flight_settings": ti.flight_settings,
        "hotel_settings": ti.hotel_settings,
        "transport_settings": ti.transport_settings,
        "activity_settings": ti.activity_settings,
        # Strategy-enriched fields
        "vibe": merged_content.vibe or None,
        "focus": merged_content.focus or None,
        "highlights": merged_content.highlights if merged_content.highlights else [],
        "flow": merged_content.flow if merged_content.flow else [],
        "notes": merged_content.notes if merged_content.notes else [],
    }

    normalized = _normalize_branch_spec(default_branch, fallback_inputs)
    if normalized:
        state.branches = [normalized]
    else:
        # Fallback to the raw branch if normalization fails
        state.branches = [default_branch]

    # Populate strategy_sections from branches for UI rendering
    # Uses resilient field access with fallbacks
    if state.branches:
        strategy_sections = []
        for i, branch in enumerate(state.branches[:3]):
            title = branch.get("label") or branch.get("name") or f"Option {i+1}"
            bullets = branch.get("highlights") or branch.get("bullets") or []
            strategy_sections.append(
                {
                    "id": branch.get("id") or f"section_{i}",
                    "title": title,
                    "bullets": bullets[:6],
                }
            )
        state.metadata["strategy_sections"] = strategy_sections

    _debug(
        "Generate responder complete",
        ready=state.ready_to_generate,
        branches=len(state.branches),
        strategies_called=list(strategy_results.keys()),
    )
    _debug_node_exit("generate_responder", state, start_ns)
    return state


# -----------------------
# Short-circuit responder (lightweight node for simple inputs)
# -----------------------
def short_circuit_responder(state: GraphState) -> GraphState:
    """
    Handle short-circuited inputs without LLM calls.

    This node is reached when the extractor detects a simple input pattern
    (greeting or yes/no confirmation) that can be handled with template-based
    responses instead of going through the full LLM pipeline.

    Only handles: greeting, confirmation_yes, confirmation_no
    All other input types (including acknowledgments, bare inputs) go through LLM.
    """
    _, start_ns = _debug_node_entry("short_circuit_responder", state)

    sc_type = state.flags.get("short_circuit", "unknown")
    sc_response = state.flags.get("short_circuit_response")
    sc_action = state.flags.get("short_circuit_action")

    _debug(f"Short-circuit responder handling: {sc_type}", action=sc_action)

    # Get trip context for generating follow-up questions
    trip_inputs_dict = state.trip_inputs.model_dump(exclude_none=True)
    missing = compute_trip_readiness(trip_inputs_dict).missing_core
    user_intent = state.metadata.get("user_intent", "detailed_planner")
    user_tone = state.metadata.get("user_tone", "neutral")

    # Handle based on short-circuit type
    if sc_response:
        # Use the pre-defined template response (greetings)
        state.last_summary = sc_response
        if sc_type == "greeting":
            state.metadata["last_question_field"] = "destinations"
        _debug("Using template response", response=sc_response[:50])
    elif sc_type == "field_request":
        # User explicitly requested a specific field (e.g., "Set budget", "budget?")
        # The extractor already set up the question via llm_blocked_fallback()
        # Just preserve that state - don't regenerate or overwrite
        _debug(
            "Preserving field_request question",
            question_target=state.question_target,
            last_summary=state.last_summary[:50] if state.last_summary else None,
        )
    elif sc_type == "booking_type_add":
        # User requested to add a booking type (e.g., "Add hotels", "Include flights")
        # Response was already set by _detect_short_circuit, parsed data flows
        # through normalize_inputs. Just preserve the state - don't regenerate.
        _debug(
            "Booking type add - preserving response",
            response_preview=state.last_summary[:50] if state.last_summary else None,
        )
    else:
        # Generate a contextual follow-up question with field tracking
        follow_up, asked_field = _default_follow_up_with_field(
            missing, user_intent, user_tone, trip_inputs_dict
        )
        if asked_field:
            state.metadata["last_question_field"] = asked_field
            _debug(f"Tracking question field: {asked_field}")

        if follow_up:
            if sc_type in ("confirmation_yes", "confirmation_no"):
                if sc_action == "generate_plan":
                    # Plan generation was triggered - this will be handled by the graph
                    state.last_summary = "Generating plan."
                else:
                    state.last_summary = follow_up
            else:
                state.last_summary = follow_up
        else:
            # No follow-up needed, we might be ready to generate
            state.last_summary = "Constraints complete."
            state.metadata["pending_action"] = "generate_plan"
            state.metadata["last_question_field"] = None  # Clear - we're asking for confirmation
            state.question_target = None

    # Always regenerate contextual suggestions to match the current question
    # (Previous suggestions may be stale from a different question)
    # Note: We no longer use static fallback suggestions - LLM generates them
    # Don't overwrite question_target for field_request or booking_type_add
    # (extractor already set it)
    if sc_type not in ("field_request", "booking_type_add"):
        question_target = state.metadata.get("last_question_field")
        state.question_target = question_target
    state.suggested_responses = []  # LLM will generate context-aware suggestions
    _debug_suggestions(state.suggested_responses, source="short_circuit_responder")

    # Set intent for logging purposes
    state.intent = f"short_circuit:{sc_type}"

    # Set provenance for final response tracking (deterministic/template path)
    state.metadata["response_writer_node"] = "short_circuit_responder"
    state.metadata["response_generation_provenance"] = "deterministic"

    _debug_node_exit("short_circuit_responder", state, start_ns)
    return state


# -----------------------
# Conditional routing after normalize_inputs
# -----------------------
def route_after_normalize(state: GraphState) -> str:
    """
    Route after normalize_inputs completes.

    Phase 6: Uses centralized GateEvaluator for all routing decisions.
    Gate evaluation is done once and results are applied to state.

    Routing priority (via GateEvaluator - see GatePrecedence enum for full list):
    1. SHORT_CIRCUIT → short_circuit_responder (no LLM)
    2. FAST_PATH → required_fields_node (no LLM)
    3. CORE_COLLECTION → required_fields_node (no LLM)
    4. QUESTION_KEYWORD → specialist nodes (no LLM)
    5. ROUTER_LLM → router (LLM fallback)
    """
    # Track total turns for observability
    _routing_stats["total_turns"] += 1
    _gate_stats["total_gate_evaluations"] += 1

    # =========================================================================
    # READ PRE-COMPUTED GATE RESULT FROM normalize_inputs
    # =========================================================================
    # Gate evaluation is now done in normalize_inputs where state mutations persist.
    # We read the cached result here to avoid re-computing and to ensure consistency.
    destination = state.metadata.get("_gate_result_destination")
    gate_fired_name = state.metadata.get("_gate_result_gate_fired")
    reason = state.metadata.get("_gate_result_reason", "")
    eval_time_ms = state.metadata.get("_gate_result_eval_time_ms", 0.0)
    skipped_gates = state.metadata.get("_gate_result_skipped_gates", [])

    # Fallback if gate result not pre-computed (shouldn't happen in normal flow)
    if not destination:
        result = GateEvaluator.evaluate(state)
        destination = result.destination
        gate_fired_name = (
            result.gate_fired.name if hasattr(result.gate_fired, "name") else str(result.gate_fired)
        )
        reason = result.reason
        eval_time_ms = result.eval_time_ms
        skipped_gates = result.skipped_gates

    # Update gate-specific stats
    gate_stat_map = {
        "SHORT_CIRCUIT": "short_circuit_fired",
        "FAST_PATH": "fast_path_fired",
        "CORE_COLLECTION": "core_collection_fired",
        "QUESTION_KEYWORD": "question_keyword_fired",
        "ROUTER_LLM": "router_llm_fired",
    }

    # Handle infeasibility (uses SHORT_CIRCUIT priority but different stat)
    if "infeasibility" in reason:
        _gate_stats["infeasibility_fired"] += 1
        _routing_stats["core_fields_gate_bypasses"] += 1
    elif gate_fired_name in gate_stat_map:
        _gate_stats[gate_stat_map[gate_fired_name]] += 1

    # Update routing stats based on gate
    if gate_fired_name == "ROUTER_LLM":
        _routing_stats["router_calls"] += 1
    elif gate_fired_name == "CORE_COLLECTION":
        _routing_stats["core_fields_gate_bypasses"] += 1
    elif gate_fired_name == "QUESTION_KEYWORD":
        _routing_stats["keyword_bypasses"] += 1

    # Store first_gate_fired for observability (may already be set by normalize_inputs)
    if "first_gate_fired" not in state.metadata:
        state.metadata["first_gate_fired"] = gate_fired_name
    state.metadata["gate_eval_time_ms"] = eval_time_ms
    state.metadata["skipped_gates"] = skipped_gates

    # Set confidence routing for stats
    _set_confidence_routing(state, reason)

    # Debug logging
    _debug(
        f"🚦 GATE_EVAL: {gate_fired_name}",
        destination=destination,
        reason=reason,
        eval_time_ms=f"{eval_time_ms:.2f}",
        skipped=len(skipped_gates),
    )

    return destination


# -----------------------
# Conditional routing after required_fields (for deferred intent handling)
# -----------------------
def route_after_required_fields(state: GraphState) -> str:
    """
    Route after required_fields completes.

    If there's a deferred_intent (original intent that was postponed until core fields
    were extracted), route to that specialist. Otherwise, go to validate_and_merge.

    This enables multi-faceted extraction: "direct flight from Rome to Patagonia next week"
    first extracts destinations/origin/dates via required_fields, then routes to flights
    specialist for flight-specific preferences.
    """
    deferred_intent = state.metadata.get("deferred_intent")

    if deferred_intent:
        # Core fields should now be extracted - check if we should proceed with deferred intent
        ti = state.trip_inputs
        core_fields_complete = ti.destinations and ti.origin and ti.start_date

        if core_fields_complete:
            # Append the required_fields response to chat history to avoid repetition
            if state.last_summary:
                state.chat_history.append(
                    {
                        "role": "assistant",
                        "content": state.last_summary,
                    }
                )

            # Clear deferred intent to prevent loops
            state.metadata.pop("deferred_intent", None)
            deferred_topic = state.metadata.pop("deferred_strategy_topic", None)

            _debug(
                "Routing to deferred intent after core fields extracted",
                deferred_intent=deferred_intent,
                deferred_topic=deferred_topic,
            )

            # Restore strategy topic if it was a strategy intent
            if deferred_intent == "strategy" and deferred_topic:
                state.strategy_topic = deferred_topic
                return "strategy_node"

            # Map intent to node
            intent_to_node = {
                "flights": "flights_node",
                "hotels": "hotels_node",
                "transport": "transport_node",
                "activities": "activities_node",
                "correction_needed": "correction_node",
                "general": "general_node",
            }
            return intent_to_node.get(deferred_intent, "validate_and_merge")
        else:
            # Core fields still incomplete - clear deferred and continue to validate
            _debug(
                "Core fields still incomplete, clearing deferred intent",
                destinations=bool(ti.destinations),
                origin=bool(ti.origin),
                start_date=bool(ti.start_date),
            )
            state.metadata.pop("deferred_intent", None)
            state.metadata.pop("deferred_strategy_topic", None)

    return "validate_and_merge"


# -----------------------
# Conditional routing after branch_postprocess
# -----------------------
def route_after_branch_postprocess(state: GraphState) -> str:
    """Route to tile_search if any booking types are enabled, otherwise to summarize."""
    booking_types = state.trip_inputs.booking_types or {}
    any_enabled = any(booking_types.values())

    if any_enabled and state.branches:
        _debug(
            "Routing to tile_search",
            enabled_booking_types=[k for k, v in booking_types.items() if v],
        )
        return "tile_search"
    else:
        _debug("Skipping tile_search, routing to summarize")
        return "summarize"


# -----------------------
# Graph assembly (updated with new nodes)
# -----------------------
_graph = StateGraph(GraphState)
_graph.add_node("extractor", extractor)
_graph.add_node("normalize_inputs", normalize_inputs)
_graph.add_node("generate_responder", generate_responder)
_graph.add_node("short_circuit_responder", short_circuit_responder)
_graph.add_node("router", router)
_graph.add_node("required_fields_node", required_fields_node)
_graph.add_node("flights_node", flights_node)
_graph.add_node("hotels_node", hotels_node)
_graph.add_node("transport_node", transport_node)
_graph.add_node("activities_node", activities_node)
_graph.add_node("strategy_node", strategy_node)
_graph.add_node("correction_node", correction_node)
_graph.add_node("general_node", general_node)
_graph.add_node("validate_and_merge", validate_and_merge)
_graph.add_node("branch_postprocess", branch_postprocess)
_graph.add_node("tile_search", tile_search)
_graph.add_node("summarize", summarize)
_graph.add_node("response_polish", response_polish)
_graph.add_node("lqa_prepass", lqa_prepass)  # Phase 7: LQA pre-pass before extractor


# Routing function after lqa_prepass - determines if extractor can be skipped
def route_after_lqa_prepass(state: GraphState) -> str:
    """
    Route after LQA pre-pass.

    If LQA successfully parsed the user's answer (flags["lqa_prepass"] == True),
    skip extractor entirely and go directly to normalize_inputs.

    Otherwise, fall through to extractor for full extraction.
    """
    if state.flags.get("lqa_prepass"):
        _debug("[LQA] Routing: LQA hit, skipping extractor → normalize_inputs")
        return "normalize_inputs"
    _debug("[LQA] Routing: LQA bail, falling through → extractor")
    return "extractor"


# Routing function after extractor - fast-path for pure short-circuits
def route_after_extractor(state: GraphState) -> str:
    """
    Route immediately after extractor for maximum responsiveness.

    Pure short-circuits (greeting, acknowledgment, off-topic, yes/no without parsed data)
    bypass normalize_inputs entirely.

    Short-circuits with parsed data (bare_destination, bare_date, etc.) go through
    normalize_inputs to apply the extracted data.
    """
    sc_type = state.flags.get("short_circuit")
    if sc_type:
        # Pure short-circuits with no data to normalize - go directly to responder
        if sc_type in ("greeting", "acknowledgment", "off_topic"):
            _debug(f"Fast-path: bypassing normalize_inputs for {sc_type}")
            return "short_circuit_responder"
        # Yes/no confirmations without pending action that would change state
        if sc_type in ("confirmation_yes", "confirmation_no") and not state.parsed_inputs:
            _debug(f"Fast-path: bypassing normalize_inputs for {sc_type}")
            return "short_circuit_responder"
    # All other cases go through normalize_inputs
    return "normalize_inputs"


# Flow: START → lqa_prepass → (conditional) normalize_inputs or extractor
# LQA pre-pass attempts zero-LLM parsing of simple answers to the last question.
# If successful, extractor is skipped entirely, saving ~500-2000 tokens.
_graph.add_edge(START, "lqa_prepass")

# Conditional edge after lqa_prepass: hit → normalize_inputs, bail → extractor
_graph.add_conditional_edges(
    "lqa_prepass",
    route_after_lqa_prepass,
    {
        "normalize_inputs": "normalize_inputs",
        "extractor": "extractor",
    },
)

# Conditional edge after extractor: fast-path for pure short-circuits
_graph.add_conditional_edges(
    "extractor",
    route_after_extractor,
    {
        "normalize_inputs": "normalize_inputs",
        "short_circuit_responder": "short_circuit_responder",
    },
)

# Conditional edge: normalize_inputs → router OR short_circuit_responder OR specialist nodes
# GateEvaluator can route directly to specialist nodes via KEYWORD_HEURISTIC, QUESTION_KEYWORD,
# or SCORING_ROUTER gates, bypassing the router LLM entirely.
# READY_NO_FIELDS gate routes directly to summarize when all fields are complete.
_graph.add_conditional_edges(
    "normalize_inputs",
    route_after_normalize,
    {
        "router": "router",
        "generate_responder": "generate_responder",
        "short_circuit_responder": "short_circuit_responder",
        "required_fields_node": "required_fields_node",
        "flights_node": "flights_node",
        "hotels_node": "hotels_node",
        "transport_node": "transport_node",
        "activities_node": "activities_node",
        "strategy_node": "strategy_node",
        "correction_node": "correction_node",
        "general_node": "general_node",
        "summarize": "summarize",
    },
)

# generate_responder → validate_and_merge (process branches)
_graph.add_edge("generate_responder", "validate_and_merge")

# short_circuit_responder → summarize (bypass validate_and_merge, branch_postprocess)
_graph.add_edge("short_circuit_responder", "summarize")


def route_after_router(state: GraphState) -> str:
    # =========================================================================
    # OFF-TOPIC HANDLING
    # =========================================================================
    # Off-topic queries have already been handled in the router node with a
    # friendly deflection response. Skip to summarize to output the response.
    if state.intent == "off_topic":
        _debug("Routing off_topic to summarize")
        return "summarize"

    # =========================================================================
    # ROUTER CONFIDENCE THRESHOLD
    # =========================================================================
    # If router returned low confidence (<0.3), don't trust the intent.
    # Fall back to required_fields which has better contextual understanding.
    # This saves wasted specialist calls when router is uncertain.
    ROUTER_CONFIDENCE_THRESHOLD = 0.3
    router_confidence = state.metadata.get("router_confidence", 1.0)

    if router_confidence < ROUTER_CONFIDENCE_THRESHOLD and state.intent not in (
        "required_fields",
        "correction_needed",
        "off_topic",
    ):
        _debug(
            "🎯 ROUTER_LOW_CONFIDENCE: Falling back to required_fields",
            router_confidence=f"{router_confidence:.2f}",
            threshold=ROUTER_CONFIDENCE_THRESHOLD,
            original_intent=state.intent,
            reason="Router uncertain about intent - using required_fields for safety",
        )
        # Store original intent in case we want to revisit
        state.metadata["router_low_confidence_fallback"] = True
        state.metadata["router_original_intent"] = state.intent
        if state.strategy_topic:
            state.metadata["router_original_topic"] = state.strategy_topic
        state.intent = "required_fields"
        return "required_fields_node"

    # =========================================================================
    # EXTRACTION CONFIDENCE-BASED ROUTING
    # =========================================================================
    # Force required_fields for low confidence extractions
    # This allows the LLM to validate/correct entities like typos or non-English
    extraction_conf = state.metadata.get("extraction_confidence", {})
    confidence_level = extraction_conf.get("level", "medium")
    confidence_score = extraction_conf.get("overall", 0.5)

    # Low confidence forces LLM extraction only when we didn't extract any meaningful updates.
    # Many preference-only turns (e.g., "direct business class", "rent a car") won't extract new
    # places and would otherwise be mis-routed to required_fields.
    meaningful_turn_update = any(
        k in (state.parsed_inputs or {})
        for k in (
            "budget_delta",
            "adults_delta",
            "children_delta",
            "requires_assistance_delta",
            "multi_city_intent_delta",
            "flight_settings_delta",
            "hotel_settings_delta",
            "transport_settings_delta",
            "category_activation",
            "strategy_hint",
        )
    )

    if (
        confidence_level == "low"
        and not meaningful_turn_update
        and state.intent not in ("correction_needed", "required_fields")
    ):
        low_reasons = extraction_conf.get("low_confidence_reasons") or []
        state.metadata["force_required_fields_reason"] = "low_extraction_confidence"
        state.metadata["deferred_intent"] = state.intent
        if state.strategy_topic:
            state.metadata["deferred_strategy_topic"] = state.strategy_topic
        _debug(
            "Forcing required_fields due to low extraction confidence",
            confidence=f"{confidence_score:.2f}",
            level=confidence_level,
            reasons=low_reasons[:3],
        )
        return "required_fields_node"

    # Non-English detected with high confidence → force LLM extraction
    if not extraction_conf.get("is_english", True):
        lang = extraction_conf.get("detected_language", "unknown")
        lang_conf = extraction_conf.get("language_confidence", 0)
        if lang_conf > 0.8 and state.intent not in ("correction_needed", "required_fields"):
            state.metadata["force_required_fields_reason"] = f"non_english:{lang}"
            state.metadata["deferred_intent"] = state.intent
            _debug(
                "Forcing required_fields due to non-English input",
                detected_language=lang,
                language_confidence=f"{lang_conf:.2f}",
            )
            return "required_fields_node"

    # Typo suggestions present → force LLM extraction to confirm/correct
    typo_suggestions = extraction_conf.get("typo_suggestions", {})
    if typo_suggestions and state.intent not in ("correction_needed", "required_fields"):
        state.metadata["force_required_fields_reason"] = "typo_detected"
        state.metadata["typo_suggestions"] = typo_suggestions
        state.metadata["deferred_intent"] = state.intent
        # Set up pending action for short-circuit typo confirmation on next turn
        state.metadata["pending_action"] = "confirm_typo"
        state.metadata["pending_typo_corrections"] = typo_suggestions
        _debug(
            "Forcing required_fields due to potential typos",
            typo_suggestions=typo_suggestions,
        )
        return "required_fields_node"

    # NOTE: Strategy exemption removed - strategy nodes now also require core fields.
    # The node guard in strategy_node provides a fallback if this routing is bypassed.

    # CRITICAL: Force required_fields when core fields are missing
    # This ensures destination extraction happens even when router detects
    # activity/flight/strategy keywords. The required_fields specialist has the best
    # extraction logic for bare place names, typos, etc.
    ti = state.trip_inputs
    core_fields_missing = not ti.destinations or not ti.origin or not ti.start_date

    if core_fields_missing and state.intent not in ("correction_needed", "required_fields"):
        # Store the original intent to route to after required_fields completes
        original_intent = state.intent
        original_topic = state.strategy_topic

        # Only defer if there's a meaningful intent to come back to
        if original_intent and original_intent != "required_fields":
            state.metadata["deferred_intent"] = original_intent
            if original_topic:
                state.metadata["deferred_strategy_topic"] = original_topic
            (
                print(
                    f"[PLAN_GRAPH DEBUG] 🧭 Deferring intent until core fields extracted "
                    f"deferred_intent={original_intent} deferred_topic={original_topic} "
                    f"destinations={bool(ti.destinations)} origin={bool(ti.origin)} "
                    f"start_date={bool(ti.start_date)}"
                )
                if _DEBUG_LOG
                else None
            )
        else:
            (
                print(
                    "[PLAN_GRAPH DEBUG] 🧭 Forcing required_fields route "
                    "due to missing core fields "
                    f"destinations={bool(ti.destinations)} "
                    f"origin={bool(ti.origin)} "
                    f"start_date={bool(ti.start_date)}"
                )
                if _DEBUG_LOG
                else None
            )
        return "required_fields_node"

    intent = state.intent or "required_fields"
    return {
        "required_fields": "required_fields_node",
        "flights": "flights_node",
        "hotels": "hotels_node",
        "transport": "transport_node",
        "activities": "activities_node",
        "correction_needed": "correction_node",
        "strategy": "strategy_node",
        "general": "general_node",
    }.get(intent, "required_fields_node")


_graph.add_conditional_edges(
    "router",
    route_after_router,
    {
        "strategy_node": "strategy_node",
        "required_fields_node": "required_fields_node",
        "flights_node": "flights_node",
        "hotels_node": "hotels_node",
        "transport_node": "transport_node",
        "activities_node": "activities_node",
        "correction_node": "correction_node",
        "general_node": "general_node",
        "summarize": "summarize",
    },
)

# required_fields_node has special conditional routing for deferred intents
_graph.add_conditional_edges(
    "required_fields_node",
    route_after_required_fields,
    {
        "validate_and_merge": "validate_and_merge",
        "flights_node": "flights_node",
        "hotels_node": "hotels_node",
        "transport_node": "transport_node",
        "activities_node": "activities_node",
        "strategy_node": "strategy_node",
        "correction_node": "correction_node",
        "general_node": "general_node",
    },
)

# Other workers go directly to validate_and_merge
for n in [
    "flights_node",
    "hotels_node",
    "transport_node",
    "activities_node",
    "strategy_node",
    "correction_node",
    "general_node",
]:
    _graph.add_edge(n, "validate_and_merge")

# validate_and_merge → branch_postprocess
_graph.add_edge("validate_and_merge", "branch_postprocess")

# branch_postprocess → conditional routing to tile_search or summarize
_graph.add_conditional_edges(
    "branch_postprocess",
    route_after_branch_postprocess,
    {
        "tile_search": "tile_search",
        "summarize": "summarize",
    },
)

# tile_search → summarize → response_polish → END
_graph.add_edge("tile_search", "summarize")
_graph.add_edge("summarize", "response_polish")
_graph.add_edge("response_polish", END)

app = _graph.compile(checkpointer=MemorySaver())


def clear_session_checkpoint(session_id: str) -> None:
    """
    Clear the LangGraph checkpoint for a session.

    Called when a session is reset to ensure the graph state doesn't persist.
    The MemorySaver stores checkpoints by thread_id, which is 'session_{session_id}'.
    """
    thread_id = f"session_{session_id}"
    try:
        # MemorySaver stores checkpoints in a dict keyed by thread_id
        # Access the internal storage to clear it
        if hasattr(app, "checkpointer") and app.checkpointer is not None:
            checkpointer = app.checkpointer
            if hasattr(checkpointer, "storage"):
                storage = getattr(checkpointer, "storage", None)
                if storage is not None and thread_id in storage:
                    del storage[thread_id]
                    _debug(f"Cleared LangGraph checkpoint for thread_id={thread_id}")
    except Exception as e:
        _debug_error(f"Failed to clear checkpoint for {thread_id}: {e}")


# Checkpoint TTL from settings
_CHECKPOINT_TTL_HOURS = settings.checkpoint_ttl_hours


def prune_stale_checkpoints() -> int:
    """
    Remove LangGraph checkpoints that have been idle for longer than CHECKPOINT_TTL_HOURS.

    This helps prevent memory overflow from accumulated thread checkpoints.
    The MemorySaver stores checkpoints in-memory, so this is important for
    long-running instances.

    Returns the number of checkpoints that were pruned.
    """
    pruned_count = 0
    try:
        if not hasattr(app, "checkpointer") or app.checkpointer is None:
            return 0

        checkpointer = app.checkpointer
        if not hasattr(checkpointer, "storage"):
            return 0

        storage = getattr(checkpointer, "storage", None)
        if storage is None or not isinstance(storage, dict):
            return 0

        now = datetime.now(UTC)
        ttl_delta = timedelta(hours=_CHECKPOINT_TTL_HOURS)
        threads_to_remove = []

        # Iterate over storage to find stale checkpoints
        for thread_id, checkpoint_data in storage.items():
            # MemorySaver stores checkpoints with metadata including timestamps
            # Try to extract the last access/update time
            try:
                # Check if checkpoint has timestamp metadata
                if isinstance(checkpoint_data, dict):
                    # Look for common timestamp fields
                    ts = checkpoint_data.get("ts") or checkpoint_data.get("timestamp")
                    if ts:
                        if isinstance(ts, str):
                            last_access = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        elif isinstance(ts, (int, float)):
                            last_access = datetime.fromtimestamp(ts, tz=UTC)
                        else:
                            last_access = now  # Can't parse, skip

                        if now - last_access > ttl_delta:
                            threads_to_remove.append(thread_id)
                    else:
                        # No timestamp, mark for removal if we're in strict mode
                        # For now, skip entries without timestamps
                        pass
            except Exception:
                # If we can't parse the checkpoint, skip it
                continue

        # Remove stale checkpoints
        for thread_id in threads_to_remove:
            try:
                del storage[thread_id]
                pruned_count += 1
                _debug(f"Pruned stale checkpoint: {thread_id}")
            except KeyError:
                pass

        if pruned_count > 0:
            _debug(f"Pruned {pruned_count} stale checkpoints (TTL: {_CHECKPOINT_TTL_HOURS}h)")

    except Exception as e:
        _debug_error(f"Failed to prune stale checkpoints: {e}")

    return pruned_count


def clear_all_checkpoints() -> int:
    """
    Clear ALL LangGraph checkpoints regardless of age.

    Use with caution - this will clear all in-progress session states.
    Returns the number of checkpoints that were cleared.
    """
    cleared_count = 0
    try:
        if not hasattr(app, "checkpointer") or app.checkpointer is None:
            return 0

        checkpointer = app.checkpointer
        if not hasattr(checkpointer, "storage"):
            return 0

        storage = getattr(checkpointer, "storage", None)
        if storage is not None and isinstance(storage, dict):
            cleared_count = len(storage)
            storage.clear()
            _debug(f"Cleared all {cleared_count} LangGraph checkpoints")

    except Exception as e:
        _debug_error(f"Failed to clear all checkpoints: {e}")

    return cleared_count


def checkpoint_stats() -> dict[str, int]:
    """Return a snapshot of checkpoint storage size."""
    try:
        if hasattr(app, "checkpointer") and app.checkpointer is not None:
            checkpointer = app.checkpointer
            if hasattr(checkpointer, "storage"):
                storage = getattr(checkpointer, "storage", None)
                if storage is not None and isinstance(storage, dict):
                    return {"checkpoint_count": len(storage)}
    except Exception:
        pass
    return {"checkpoint_count": 0}


# -----------------------
# Public entrypoint
# -----------------------


def _required_done(ti: TripInputs) -> bool:
    # Match READY STATE rule (destinations, origin, start_date)
    return bool(ti.destinations and ti.origin and ti.start_date)


def _progress_signal(before: TripInputs, after: TripInputs) -> bool:
    # Register progress if any required field newly completed or any field changed
    if _required_done(before) != _required_done(after):
        return True
    # Shallow diff on a few high-signal keys
    keys = [
        "destinations",
        "origin",
        "start_date",
        "end_date",
        "budget",
        "currency",
        "activity_settings",
        "strategy_settings",
        "booking_types",
        "flight_settings",
        "hotel_settings",
        "transport_settings",
    ]
    b = before.model_dump(exclude_none=True)
    a = after.model_dump(exclude_none=True)
    return any(b.get(k) != a.get(k) for k in keys)


# =============================================================================
# EXIT CONTRACT ENFORCEMENT (MVP Hardening)
# =============================================================================
# Ensures every turn ends with valid output: non-empty assistant_message,
# deterministic missing_fields, and suggested_responses when asking a question.


def _validate_question_target(question_target: Optional[str]) -> Optional[str]:
    """
    Validate and sanitize question_target.

    Returns None if invalid (e.g., contains pipe characters from LLM echo).
    """
    if not question_target:
        return None

    # Guard against LLM echo failure (e.g., "destinations|origin|dates|...")
    if "|" in question_target:
        _debug_error(
            "Invalid question_target detected (contains pipe)",
            raw_value=question_target[:50],
        )
        return None

    # Validate against known enum values
    valid_targets = {
        "destinations",
        "origin",
        "dates",
        "travelers",
        "budget",
        "end_date",
        "start_date",
        "adults",
        "children",
        "hotel_preferences",
        "flight_preferences",
        "activity_preferences",
    }

    # Normalize common aliases
    if question_target == "start_date":
        return "dates"
    if question_target == "travelers (adults)" or question_target == "adults":
        return "travelers"

    if question_target.lower() in valid_targets:
        return question_target.lower()

    _debug(f"Unknown question_target: {question_target}, treating as valid")
    return question_target


def _get_deterministic_suggestions(
    question_target: str,
    strategy_topic: Optional[str] = None,
) -> List[str]:
    """
    Get deterministic suggestions for a question target from templates.
    Falls back to FALLBACK_SUGGESTIONS if template not found.
    """
    template_response = _get_template_response(question_target, strategy_topic)
    if template_response and template_response.get("suggestions"):
        return template_response["suggestions"][:3]

    return FALLBACK_SUGGESTIONS.copy()


def _enforce_exit_contract(state: "GraphState") -> "GraphState":
    """
    Enforce output invariants before returning from run_turn.

    This is the LAST-WRITER for invalid/missing output fields only.
    It does NOT overwrite valid responses from specialists/required_fields.

    Invariants enforced:
    1. assistant_message must be non-empty string
    2. missing_fields computed deterministically via compute_trip_readiness
    3. If missing_fields non-empty: question_target must be set and valid
    4. If question_target set: suggested_responses must be non-empty
    5. If missing_fields empty: question_target can be null
    """
    patched = False

    # Compute canonical readiness state
    readiness = compute_trip_readiness(state.trip_inputs)

    # Store missing fields in metadata for observability
    state.metadata["exit_contract_missing_fields"] = readiness.missing_all
    state.metadata["exit_contract_core_complete"] = readiness.core_complete

    # 1. Validate question_target if present
    if state.question_target:
        validated_target = _validate_question_target(state.question_target)
        if validated_target != state.question_target:
            _debug(
                "Exit contract: sanitized question_target",
                original=state.question_target,
                sanitized=validated_target,
            )
            state.question_target = validated_target
            patched = True

    # 2. If missing fields exist but no question_target, set deterministically
    if readiness.missing_all and not state.question_target:
        # Use priority order from readiness
        state.question_target = readiness.question_target
        _debug(
            "Exit contract: set question_target from readiness",
            question_target=state.question_target,
            missing_fields=readiness.missing_all,
        )
        patched = True

    # 3. If question_target set but no suggestions, add deterministic suggestions
    if state.question_target and not state.suggested_responses:
        state.suggested_responses = _get_deterministic_suggestions(
            state.question_target,
            state.strategy_topic,
        )
        _debug(
            "Exit contract: added deterministic suggestions",
            question_target=state.question_target,
            suggestions=state.suggested_responses,
        )
        patched = True

    # 4. Validate suggested_responses are non-empty strings
    if state.suggested_responses:
        valid_suggestions = [
            s for s in state.suggested_responses if s and isinstance(s, str) and s.strip()
        ]
        if len(valid_suggestions) != len(state.suggested_responses):
            state.suggested_responses = (
                valid_suggestions if valid_suggestions else FALLBACK_SUGGESTIONS.copy()
            )
            patched = True

    # 5. If missing_fields is empty, question_target should be null (plan is ready)
    if not readiness.missing_all and readiness.core_complete:
        # Don't clear question_target if specialist set it for preference questions
        pass  # Keep specialist's question_target for preference collection

    # Track that exit contract was applied
    if patched:
        state.metadata["exit_contract_patched"] = True
        _increment_state_counter("exit_contract_patches")

    return state


async def run_turn(
    user_text: str, session_state: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Public entrypoint for running a single turn of the planning graph (async).

    Args:
        user_text: The user's message.
        session_state: Optional session state from previous turns.

    Returns:
        Dict with assistant_message, trip_inputs, ready_to_generate, branches, etc.
    """
    _debug("=" * 60)
    _debug("RUN_TURN START", user_text=user_text)
    _debug("=" * 60)

    session_state = session_state or {}
    thread_id = session_state.get("thread_id") or str(uuid4())

    # Previous state snapshot for progress heuristics
    prev_ti = TripInputs(**session_state.get("trip_inputs", {}))

    # Build metadata with today_iso from session_state (defaults to current date)
    metadata = deepcopy(session_state.get("metadata", {}))
    if "today_iso" in session_state:
        metadata["today_iso"] = session_state["today_iso"]
    elif "today_iso" not in metadata:
        metadata["today_iso"] = date.today().isoformat()

    # Reset turn-specific metadata counters that shouldn't persist across turns
    # These should start fresh each turn for consistent routing behavior
    metadata.pop("validator_failures", None)
    metadata.pop("no_progress_turns", None)
    metadata.pop("last_intent", None)
    # Clear turn-scoped context fields - nodes will re-set them as needed
    # last_question_field is set by nodes that ask questions, cleared here so stale
    # context from previous turns doesn't influence short-circuit detection
    metadata.pop("last_question_field", None)
    # Clear pending actions to prevent stale actions from triggering on unrelated inputs
    metadata.pop("pending_action", None)
    metadata.pop("pending_typo_corrections", None)
    # Clear deferred intent/strategy to prevent stale deferrals
    metadata.pop("deferred_intent", None)
    metadata.pop("deferred_strategy_topic", None)
    # Clear routing_reason (set fresh each turn by gate evaluator)
    metadata.pop("routing_reason", None)

    # =========================================================================
    # LLM BUDGET: Reset per-turn counters (PR2: Use constants)
    # =========================================================================
    metadata[LLM_CALLS_THIS_TURN] = 0  # Integer counter for LLM call budget
    metadata[LLM_CALL_BLOCKED_REASON] = {}  # v5: dict for per-node tracking
    metadata[LLM_CALL_SITES] = []  # v5: track which nodes called LLM
    metadata[DELTAS_APPLIED_THIS_TURN] = []  # v5: track field changes this turn
    metadata[RESPONSE_SOURCE_NODE] = None  # v5: first node to produce response
    metadata[RESPONSE_GENERATION_PROVENANCE] = None  # v5: response generation provenance
    # Note: llm_call_blocked_count is cumulative (not reset per turn)

    # =========================================================================
    # PR-A: PLANNER SNAPSHOT (set once per turn for observability)
    # =========================================================================
    metadata[PLANNER_SNAPSHOT] = get_planner_snapshot()

    # =========================================================================
    # v7 Final v5: Reset per-turn metadata keys to avoid stale overrides
    # =========================================================================
    # These keys are turn-scoped and must be cleared to prevent previous-turn
    # state from leaking into routing/scoring decisions.
    metadata.pop("answered_question_target_this_turn", None)
    metadata.pop("answered_question_id_this_turn", None)
    metadata.pop("suggestion_target_override", None)
    metadata.pop("extractor_skipped_reason", None)
    metadata.pop("response_writer_node", None)
    metadata.pop("parse_provenance", None)
    metadata.pop("response_text_hash", None)  # Reset for set_final_response

    # =========================================================================
    # V12: Initialize per-turn instrumentation (node journal, tripwires)
    # =========================================================================
    init_turn_instrumentation(metadata)

    # Build input state
    # Reset turn-specific flags to prevent stale state from persisting
    incoming_flags = deepcopy(session_state.get("flags", {}))
    incoming_flags.pop("generate_plan", None)
    incoming_flags.pop("generate_requested", None)
    # Clear short-circuit flags so each turn re-detects from scratch
    incoming_flags.pop("short_circuit", None)
    incoming_flags.pop("short_circuit_response", None)
    incoming_flags.pop("short_circuit_action", None)
    # Clear fast-path and polish flags - these are turn-specific
    incoming_flags.pop("fast_path", None)
    incoming_flags.pop("fast_path_field", None)
    incoming_flags.pop("skip_polish", None)
    incoming_flags.pop("lqa_prepass", None)
    incoming_flags.pop("lqa_field", None)
    incoming_flags.pop("lqa_bail_reason", None)
    incoming_flags.pop("deterministic_place_parse", None)

    # =========================================================================
    # V16: Store previous turn's suggestions for suggestion-click detection
    # =========================================================================
    prev_suggestions = session_state.get("suggested_responses", [])
    if prev_suggestions:
        metadata["last_offered_suggestions"] = [s for s in prev_suggestions if isinstance(s, str)]
    else:
        metadata.pop("last_offered_suggestions", None)

    state = GraphState(
        user_text=user_text,
        trip_inputs=TripInputs(**session_state.get("trip_inputs", {})),
        metadata=metadata,
        flags=incoming_flags,
        last_summary=session_state.get("last_summary"),
        branches=deepcopy(session_state.get("branches", [])),
        suggested_responses=deepcopy(session_state.get("suggested_responses", [])),
        errors=_deserialize_errors(session_state.get("errors", [])),
        chat_history=deepcopy(
            session_state.get("chat_history", [])
        ),  # Pass chat history for LLM context
        # Persist strategy expansion context across turns (V35: added pending_strategy_expansion)
        strategy_expansion_tier=session_state.get("strategy_expansion_tier"),
        strategy_expansion_target=session_state.get("strategy_expansion_target"),
        pending_strategy_expansion=session_state.get("pending_strategy_expansion", False),
        # Carry forward loop guard and turn tracking state
        loop_guard=deepcopy(session_state.get("loop_guard", {})),
        questions_asked=deepcopy(session_state.get("questions_asked", {})),
        turn_number=session_state.get("turn_number", 0),
    )

    # V37: Restore end_date_bypassed from session_state
    if session_state.get("end_date_bypassed", False):
        state.metadata["end_date_bypassed"] = True

    # =========================================================================
    # CANONICALIZE QUESTION_TARGET (before LQA prepass)
    # =========================================================================
    # Ensures consistent target values (e.g., "start_date" -> "dates")
    # This must happen BEFORE lqa_prepass reads the target
    # =========================================================================
    # CANONICALIZE QUESTION_TARGET (SSoT at turn boundary)
    # =========================================================================
    # Ensures consistent target values (e.g., "start_date" -> "dates")
    # This must happen BEFORE lqa_prepass reads the target
    # SSoT: metadata is the canonical source, state is synced for this turn
    raw_question_target = session_state.get("question_target") or metadata.get("question_target")
    if raw_question_target:
        canonical_qt = canonicalize_question_target(raw_question_target)
        state.question_target = canonical_qt
        metadata["question_target"] = canonical_qt  # Sync to metadata (SSoT)
        _debug(
            "Canonicalized question_target at turn boundary",
            raw=raw_question_target,
            canonical=canonical_qt,
        )
    else:
        state.question_target = None
        metadata["question_target"] = None

    # =========================================================================
    # CLEAR BOOTSTRAP FLAGS AFTER TURN 1
    # =========================================================================
    # Strategy bootstrap is a first-turn optimization only. After turn 1, we must
    # clear the fast_path flags to allow normal gate evaluation (including
    # STRATEGY_TOPIC_SWITCH) to fire on subsequent turns.
    strategy_bootstrap_turn = metadata.get("strategy_bootstrap_turn", 0)
    current_turn = state.turn_number
    if (
        current_turn > strategy_bootstrap_turn
        and incoming_flags.get("fast_path_field") == "strategy_bootstrap"
    ):
        _debug(
            "Clearing bootstrap fast_path flags (turn > bootstrap_turn)",
            current_turn=current_turn,
            bootstrap_turn=strategy_bootstrap_turn,
        )
        incoming_flags["strategy_bootstrap_active"] = False
        # Don't clear fast_path entirely - just deactivate bootstrap
        # Other fast_path sources (LQA, etc.) should still work
        state.flags = incoming_flags

    # =========================================================================
    # PENDING STRATEGY TOPIC AUTO-FIRE
    # =========================================================================
    # If a topic switch was deferred due to blocking errors last turn, and
    # blocking errors are now cleared, auto-fire the topic switch.
    pending_topic = metadata.get("pending_strategy_topic")
    if pending_topic:
        # Check if blocking errors are now cleared
        readiness = compute_trip_readiness(
            state.trip_inputs,
            errors=state.errors,
            metadata=metadata,
        )
        if not readiness.has_blocking_errors:
            _debug(
                "Auto-firing pending strategy topic (blocking errors cleared)",
                pending_topic=pending_topic,
            )
            # Set up state to trigger STRATEGY_TOPIC_SWITCH gate
            # The gate will detect this topic and route appropriately
            metadata["auto_fire_topic_switch"] = pending_topic
            metadata.pop("pending_strategy_topic", None)
            state.metadata = metadata

    # =========================================================================
    # DATE CLARIFY MODE TRACKING
    # =========================================================================
    # Track turns spent in date_clarify_mode for observability
    if metadata.get("date_clarify_mode"):
        _date_stats["turns_in_date_clarify_mode"] += 1

    # Phase 1: Capture pre-turn snapshot for state integrity checking
    pre_turn_snapshot = capture_pre_turn_snapshot(state)

    # Use a unique thread_id per turn to prevent LangGraph from restoring stale checkpoint state
    # We manage state ourselves via session_state, so we don't need checkpoint persistence
    turn_thread_id = f"{thread_id}_{uuid4().hex[:8]}"

    # Build config with optional LangSmith tracing
    # When LANGSMITH_TRACING=true in .env, we use a LangChainTracer callback
    # to capture the actual LangSmith run UUID for trace enrichment
    tracing_enabled = settings.langsmith_tracing_enabled and settings.langsmith_api_key
    tracer = None
    config: Dict[str, Any] = {"configurable": {"thread_id": turn_thread_id}}

    if tracing_enabled and LANGCHAIN_TRACER_AVAILABLE:
        # Ensure LangChain env vars are set for the tracer to work
        if settings.langsmith_api_key:
            os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
            os.environ["LANGCHAIN_TRACING_V2"] = "true"
            os.environ["LANGCHAIN_ENDPOINT"] = settings.langsmith_endpoint
            os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project

        # Extract test metadata for trace tagging
        scenario_id = metadata.get("scenario_id", "")
        is_test_run = metadata.get("test_run", False)

        # Create tracer with tags for searchability
        # Note: LangChainTracer doesn't accept metadata param - we encode info in tags
        tracer = LangChainTracer(
            project_name=settings.langsmith_project,
            tags=[
                "nomadic",
                f"thread:{thread_id}",
                *(["e2e-test"] if is_test_run else []),
                *([f"scenario:{scenario_id}"] if scenario_id else []),
            ],
        )
        config["callbacks"] = [tracer]
        config["run_name"] = f"run_turn_{thread_id[:8]}"

    # Execute the graph with state integrity error handling
    result: GraphState | dict
    try:
        result = await app.ainvoke(state, config=config)
    except StateRegressionError as e:
        # State integrity violation detected - recover using snapshot
        _debug_error(
            "StateRegressionError caught in run_turn",
            node=e.node_name,
            diff_summary=e.diff_summary,
        )
        # Handle recovery by restoring from snapshot
        state = handle_state_regression_error(state, e)
        result = state

    # Capture the actual LangSmith run ID from the tracer (if available)
    # This is the real UUID that can be used to fetch trace details
    langsmith_run_id: Optional[str] = turn_thread_id  # Fallback to correlator
    if tracer is not None and hasattr(tracer, "latest_run") and tracer.latest_run:
        langsmith_run_id = str(tracer.latest_run.id)
    elif tracer is not None and hasattr(tracer, "run_map") and tracer.run_map:
        # Alternative: get the root run from run_map
        root_runs = [r for r in tracer.run_map.values() if r.parent_run_id is None]
        if root_runs:
            langsmith_run_id = str(root_runs[0].id)

    # Normalize to GraphState in case the graph returns a plain dict (e.g., from checkpoints)
    if isinstance(result, dict):
        result = GraphState.model_validate(result)

    # ==========================================================================
    # POST-TURN INVARIANT CHECK: Detect state regression that wasn't caught
    # Uses "restore-then-reapply-safe-deltas" approach to avoid both:
    # 1. Losing state entirely (trip_inputs -> {})
    # 2. Undoing valid new input from the current turn
    #
    # SAFE DELTAS DEFINITION:
    # - user-confirmed/explicit fields from current turn (provenance = "explicit")
    # - non-destructive additions (new keys, not overwrites)
    # - overwrites ONLY if provenance "explicit" > "inferred"
    # Inferred updates should NOT overwrite snapshot values during recovery
    # ==========================================================================
    try:
        post_turn_state = (
            result.trip_inputs.model_dump() if hasattr(result.trip_inputs, "model_dump") else {}
        )
        violation = _check_state_invariants(pre_turn_snapshot, post_turn_state)
        if violation:
            _debug_error("Post-turn state invariant violation detected", violation=violation)
            _increment_state_counter("state_regression_count")
            _increment_state_counter("recovery_attempt_count")

            # Get provenance tracking from metadata
            trip_inputs_provenance = (
                result.metadata.get("trip_inputs_provenance", {}) if result.metadata else {}
            )

            # Step 1: Identify safe deltas with provenance-aware logic
            # Safe delta criteria:
            # a) New key (not in pre-turn OR was null in pre-turn)
            # b) Overwrite ONLY if provenance is "explicit" or "user_confirmed"
            safe_deltas: Dict[str, Any] = {}
            for key, value in post_turn_state.items():
                if value is not None:
                    pre_value = pre_turn_snapshot.get(key)
                    key_provenance = trip_inputs_provenance.get(key, "inferred")
                    is_explicit = key_provenance in ("explicit", "user_confirmed")

                    if pre_value is None:
                        # New key or was null - always safe
                        safe_deltas[key] = value
                        safe_debug(
                            f"Safe delta (new key): {key}",
                            provenance=key_provenance,
                        )
                    elif is_explicit and pre_value != value:
                        # Explicit overwrite - safe because user confirmed
                        safe_deltas[key] = value
                        safe_debug(
                            f"Safe delta (explicit overwrite): {key}",
                            old_value=str(pre_value)[:50],
                            new_value=str(value)[:50],
                            provenance=key_provenance,
                        )
                    # Inferred overwrites are NOT safe - skip them
                    elif pre_value != value:
                        safe_debug(
                            f"Blocked inferred overwrite during recovery: {key}",
                            provenance=key_provenance,
                        )

            # Step 2: Restore ALL non-null fields from pre-turn snapshot
            for key, value in pre_turn_snapshot.items():
                if value is not None and hasattr(result.trip_inputs, key):
                    setattr(result.trip_inputs, key, value)
            safe_debug(
                "Restored trip_inputs from pre-turn snapshot",
                restored_keys=list(k for k, v in pre_turn_snapshot.items() if v is not None),
            )

            # Step 3: Re-apply safe deltas (explicit/user-confirmed from this turn)
            for key, value in safe_deltas.items():
                if hasattr(result.trip_inputs, key):
                    setattr(result.trip_inputs, key, value)
            if safe_deltas:
                safe_debug(
                    "Re-applied safe deltas from current turn",
                    safe_delta_keys=list(safe_deltas.keys()),
                    provenance_info={
                        k: trip_inputs_provenance.get(k, "inferred") for k in safe_deltas
                    },
                )

            _increment_state_counter("recovery_success_count")
            result.metadata["state_recovered"] = True

            # Add recovery note to response if significant fields were lost
            core_lost = any(
                field in violation.lower()
                for field in ["destinations", "origin", "start_date", "end_date"]
            )
            if core_lost and result.last_summary:
                result.metadata["core_fields_recovered"] = True
    except Exception as e:
        safe_debug_error("Post-turn invariant check failed", error=str(e)[:100])

    # Update simple "no progress" metric used by conversation quality tracking
    try:
        made_progress = _progress_signal(prev_ti, result.trip_inputs)
        meta = result.metadata or {}
        if made_progress:
            meta["no_progress_turns"] = 0
        else:
            meta["no_progress_turns"] = int(meta.get("no_progress_turns", 0)) + 1
        result.metadata = meta
    except Exception:
        # Do not let metrics break the turn
        pass

    # Track missing_fields_unchanged_turns for extended loop guard window gating
    try:
        readiness = compute_trip_readiness(result.trip_inputs)
        current_missing = frozenset(readiness.missing) if readiness.missing else frozenset()
        meta = result.metadata or {}
        prev_missing = meta.get("prev_missing_fields_set")

        if prev_missing is not None:
            prev_missing_set = frozenset(prev_missing)
            if current_missing == prev_missing_set:
                meta["missing_fields_unchanged_turns"] = (
                    int(meta.get("missing_fields_unchanged_turns", 0)) + 1
                )
            else:
                meta["missing_fields_unchanged_turns"] = 0
        else:
            meta["missing_fields_unchanged_turns"] = 0

        # Store current missing set for next turn comparison
        meta["prev_missing_fields_set"] = list(current_missing)
        result.metadata = meta
    except Exception:
        # Do not let metrics break the turn
        pass

    # ==========================================================================
    # RECORD OBSERVABILITY HISTOGRAMS
    # ==========================================================================
    try:
        # Record trip_inputs keycount delta (change in non-null keys)
        post_keycount = len(
            [k for k, v in (post_turn_state if "post_turn_state" in dir() else {}).items() if v]
        )
        pre_keycount = len([k for k, v in pre_turn_snapshot.items() if v])
        keycount_delta = post_keycount - pre_keycount
        _record_histogram("trip_inputs_keycount_delta", keycount_delta)

        # Record LLM calls this turn
        llm_calls_this_turn = result.metadata.get("llm_calls_made", 0)
        _record_histogram("llm_calls_per_turn", llm_calls_this_turn)
    except Exception:
        # Don't let histogram recording break the turn
        pass

    # Extract observability metrics from result state
    result_meta = result.metadata or {}
    result_flags = result.flags or {}

    # Print token usage summary at end of trace
    _debug_token_summary(result)

    # Log final suggestions being returned
    _debug_suggestions(result.suggested_responses, source="FINAL RESPONSE")

    # ==========================================================================
    # NULL-RESPONSE GUARD: Ensure assistant_message is never null/empty
    # ==========================================================================
    if not result.last_summary or not result.last_summary.strip():
        _increment_state_counter("assistant_response_null_guard_count")
        safe_debug_error(
            "Null response guard triggered - no assistant message produced",
            turn_number=getattr(result, "turn_number", 0),
        )
        # Generate fallback response based on state
        trip_inputs = (
            result.trip_inputs.model_dump() if hasattr(result.trip_inputs, "model_dump") else {}
        )
        destinations = trip_inputs.get("destinations", [])
        if destinations:
            fallback_msg = f"{', '.join(destinations)}. Continue?"
        else:
            fallback_msg = "Destination?"
        result.last_summary = fallback_msg

    # ==========================================================================
    # STALE SUMMARY INVARIANT: Ensure response was produced this turn
    # ==========================================================================
    # Prevents guard failures from silently reusing previous turn's response
    result_meta = result.metadata or {}
    current_turn = result.turn_number
    last_response_turn = result_meta.get("last_response_turn")

    if last_response_turn is not None and last_response_turn != current_turn:
        _increment_state_counter("stale_summary_violation_count")
        _debug_error(
            "Stale summary invariant violated - response from previous turn",
            current_turn=current_turn,
            last_response_turn=last_response_turn,
        )
        # Record error for observability
        _record_structured_error(
            result,
            code="STALE_SUMMARY",
            node="run_turn",
            message=f"Response from turn {last_response_turn} reused in turn {current_turn}",
            severity="warning",
        )
        # Generate fresh deterministic recovery message
        trip_inputs = (
            result.trip_inputs.model_dump() if hasattr(result.trip_inputs, "model_dump") else {}
        )
        readiness = compute_trip_readiness(trip_inputs)
        # Use question_target from readiness (handles duration, dates, etc.)
        target = readiness.question_target
        if target:
            result.question_target = canonicalize_question_target(target)
            result_meta["question_target"] = result.question_target
            if target == "destinations":
                result.last_summary = "Destination:"
                result.suggested_responses = ["Paris", "Tokyo", "Bali"]
            elif target == "origin":
                result.last_summary = "Origin city:"
                result.suggested_responses = ["New York", "London", "Dubai"]
            elif target in ("start_date", "dates"):
                result.last_summary = "Travel dates:"
                result.suggested_responses = ["Next weekend", "In March", "Dec 15-22"]
            elif target == "duration":
                result.last_summary = "Trip duration:"
                result.suggested_responses = ["3 days", "5 days", "1 week", "10 days", "2 weeks"]
            else:
                result.last_summary = "Constraints needed."
                result.suggested_responses = [
                    "Add flights",
                    "Add hotels",
                    "Generate plan",
                ]
        # Update last_response_turn to current
        result_meta["last_response_turn"] = current_turn
        result.metadata = result_meta

    # ==========================================================================
    # V5 OBSERVABILITY: Emit RoutingDecisionFinal for analytics
    # ==========================================================================
    gate_result_snapshot: Optional[GateResult] = result_meta.get("gate_result")
    if gate_result_snapshot is not None:
        # Determine executed node (first response-producing node or gate destination)
        executed_node = result_meta.get("response_source_node") or gate_result_snapshot.destination

        # Compute redirect_reason algorithmically if executed_node differs from gate destination
        redirect_reason: Optional[str] = None
        if executed_node != gate_result_snapshot.destination:
            blocked_reasons = result_meta.get("llm_call_blocked_reason", {})
            if blocked_reasons.get(gate_result_snapshot.destination):
                redirect_reason = "llm_budget_blocked"
            elif gate_result_snapshot.date_clarify_mode:
                redirect_reason = "blocking_errors"
            else:
                # Check readiness for missing_core
                trip_inputs_check = (
                    result.trip_inputs.model_dump()
                    if hasattr(result.trip_inputs, "model_dump")
                    else {}
                )
                readiness_check = compute_trip_readiness(trip_inputs_check)
                if readiness_check.blocking_errors:
                    redirect_reason = "blocking_errors"
                elif readiness_check.missing_core:
                    redirect_reason = "missing_core"
                else:
                    redirect_reason = "guard_redirect"

        # Build RoutingDecisionFinal
        routing_decision_final = RoutingDecisionFinal(
            gate_result=gate_result_snapshot,
            executed_node=executed_node,
            redirect_reason=redirect_reason,
            response_generation_provenance=result_meta.get(
                "response_generation_provenance", "unknown"
            ),
            question_target_out=result.question_target,
            deltas_applied=result_meta.get("deltas_applied_this_turn", []),
            llm_nodes_called_this_turn=result_meta.get("llm_nodes_called_this_turn", []),
            llm_budget_used=result_meta.get("llm_calls_this_turn", 0),
            errors_count=len(result.errors) if result.errors else 0,
            schema_version=ROUTING_DECISION_SCHEMA_VERSION,
            build_git_sha=os.environ.get("BUILD_GIT_SHA", "unknown"),
            request_id=langsmith_run_id or "",
        )

        # Store immutable copy for debugging/replay
        result_meta["last_routing_decision_final"] = deepcopy(asdict(routing_decision_final))

        # Emit JSON-lines log for analytics pipeline
        # P0/P1: Include gate_fired from GatePrecedence enum (from planner.gates module)
        _debug(
            "ROUTING_DECISION_FINAL",
            schema_version=routing_decision_final.schema_version,
            gate_fired=(
                gate_result_snapshot.gate_fired.name if gate_result_snapshot.gate_fired else None
            ),
            gate_destination=gate_result_snapshot.destination,
            executed_node=executed_node,
            redirect_reason=redirect_reason,
            response_generation_provenance=routing_decision_final.response_generation_provenance,
            question_target_out=routing_decision_final.question_target_out,
            deltas_applied=routing_decision_final.deltas_applied,
            llm_nodes_called=routing_decision_final.llm_nodes_called_this_turn,
            llm_budget_used=routing_decision_final.llm_budget_used,
            errors_count=routing_decision_final.errors_count,
            request_id=routing_decision_final.request_id,
        )

    # ==========================================================================
    # SUGGESTION CONTRACT VALIDATION: Ensure suggestions match question_target
    # ==========================================================================
    if result.suggested_responses and result.question_target:
        result.suggested_responses = validate_suggestion_contract(
            result.question_target,
            result.suggested_responses,
            node_name="run_turn_exit",
            state=result,
        )

    # ==========================================================================
    # v7 Final v5: FINALIZE RESPONSE PROVENANCE
    # ==========================================================================
    # Set final response provenance with hash-guarded overwrite to ensure
    # provenance accurately reflects the final response text.
    # Uses response_writer_node and response_generation_provenance set by
    # the node that produced the response (e.g., strategy_stage0, specialist).
    # ==========================================================================
    if result.last_summary:
        writer_node = (
            result.metadata.get("response_writer_node")
            or result.metadata.get("response_source_node")
            or "unknown"
        )
        provenance_kind = result.metadata.get("response_generation_provenance") or "unknown"
        set_final_response(
            result,
            result.last_summary,
            writer_node,
            provenance_kind,
        )

        # ==========================================================================
        # END-OF-TURN PROVENANCE SUMMARY (debugging guard)
        # ==========================================================================
        # Single-line summary for easy grep/correlation of provenance regressions
        prev_hash = result.metadata.get("response_text_hash")
        _debug(
            "PROVENANCE_SUMMARY",
            response_writer_node=result.metadata.get("response_writer_node"),
            response_generation_provenance=result.metadata.get("response_generation_provenance"),
            response_text_hash_changed=(prev_hash is not None),
            parse_provenance=result.metadata.get("parse_provenance"),
        )

    # ==========================================================================
    # V12: END-OF-TURN JOURNAL DUMP (duplication detection)
    # ==========================================================================
    dump_turn_journal(result)

    # ==========================================================================
    # QUESTION_TARGET TRIPWIRE: Detect direct writes that bypassed set_question_target
    # ==========================================================================
    # This helps identify writers that need migration to set_question_target()
    if result.question_target != result.metadata.get("question_target"):
        _debug(
            "QUESTION_TARGET_WRITE_VIOLATION: state/metadata mismatch",
            state_value=result.question_target,
            metadata_value=result.metadata.get("question_target"),
            last_source=result.metadata.get("question_target_source"),
        )

    # ==========================================================================
    # EXIT CONTRACT ENFORCEMENT: Ensure consistent output structure
    # ==========================================================================
    result = _enforce_exit_contract(result)

    # ==========================================================================
    # ENRICH BRANCHES WITH IMAGES: Add Unsplash/Picsum images to branches
    # Uses different variants for each hero image slot:
    # - variant 0: Main branch image (image_url) + first hero (signature view)
    # - variant 1: Second hero image (daylight wander)
    # - variant 2: Third hero image (evening vibe)
    # ==========================================================================
    enriched_branches = []
    if result.branches:
        from app.services.unsplash import get_image_url_sync, prefetch_destination_images

        # Get activities for activity-specific images
        activities = None
        if (
            hasattr(result.trip_inputs, "activity_settings")
            and result.trip_inputs.activity_settings
        ):
            activities = getattr(result.trip_inputs.activity_settings, "categories", None)

        # Pre-fetch Unsplash images for all branch destinations to populate cache
        # Always prefetch base destination first (no activities) as fallback,
        # then optionally prefetch activity-specific variants
        for branch in result.branches:
            dests = branch.get("destinations", [])
            if dests and dests[0]:
                try:
                    # First, ensure base destination images are cached
                    await prefetch_destination_images(dests[0])
                    # Then, if activities specified, try activity-specific images
                    if activities:
                        await prefetch_destination_images(dests[0], activities=activities)
                except Exception as e:
                    _debug(f"Image prefetch failed for {dests[0]}: {e}")

        for branch in result.branches:
            branch_copy = dict(branch)  # Don't mutate original
            dests = branch_copy.get("destinations", [])
            primary_dest = dests[0] if dests else "travel"
            # Add image fields if not already present (using different variants)
            # If activities provided, images will be activity-specific (e.g., "Dubai hiking")
            if "image_url" not in branch_copy:
                branch_copy["image_url"] = get_image_url_sync(
                    primary_dest, variant=0, width=1600, height=900, activities=activities
                )
            if "hero_images" not in branch_copy:
                branch_copy["hero_images"] = [
                    get_image_url_sync(
                        primary_dest, variant=0, width=1600, height=900, activities=activities
                    ),  # Signature view
                    get_image_url_sync(
                        primary_dest, variant=1, width=900, height=600, activities=activities
                    ),  # Daylight wander
                    get_image_url_sync(
                        primary_dest, variant=2, width=900, height=600, activities=activities
                    ),  # Evening vibe
                ]
            enriched_branches.append(branch_copy)
        _debug(f"Enriched {len(enriched_branches)} branches with images (activities={activities})")

    # Assemble response
    resp = {
        "assistant_message": result.last_summary or "",
        "trip_inputs": result.trip_inputs.model_dump(exclude_none=True),
        "ready_to_generate": result.ready_to_generate,
        "branches": enriched_branches if enriched_branches else result.branches,
        "suggested_responses": result.suggested_responses,
        "errors": result.errors,
        "run_id": langsmith_run_id,  # LangSmith trace ID for E2E evaluation
        "session_state": {
            "trip_inputs": result.trip_inputs.model_dump(),
            "metadata": result_meta,
            "flags": result_flags,
            "last_summary": result.last_summary,
            "branches": enriched_branches if enriched_branches else result.branches,
            "suggested_responses": result.suggested_responses,
            "errors": result.errors,
            "thread_id": thread_id,
            # Observability metrics for analytics
            "router_intent": getattr(result, "intent", None),
            "strategy_topic": getattr(result, "strategy_topic", None),
            "short_circuit_type": result_flags.get("short_circuit"),
            "llm_calls_made": result_meta.get("llm_calls_made", 0),
            "cache_hits": result_meta.get("cache_hits", 0),
            "confidence_routing": result_meta.get("confidence_routing"),
            # Token and timing metrics for diagnostics
            "total_tokens": result_meta.get("total_tokens", 0),
            "node_tokens": result_meta.get("node_tokens", {}),
            "llm_time_ms": result_meta.get("llm_time_ms", 0.0),
            # Strategy expansion context for tier-based token optimization
            # (V35: added pending_strategy_expansion)
            "strategy_expansion_tier": getattr(result, "strategy_expansion_tier", None),
            "strategy_expansion_target": getattr(result, "strategy_expansion_target", None),
            "pending_strategy_expansion": getattr(result, "pending_strategy_expansion", False),
            # V37: Persist end_date_bypassed for flexible return date option
            "end_date_bypassed": (result.metadata or {}).get("end_date_bypassed", False),
            # State integrity tracking (Phase 1)
            "loop_guard": getattr(result, "loop_guard", {}),
            "questions_asked": getattr(result, "questions_asked", {}),
            "turn_number": getattr(result, "turn_number", 0),
            # State counters for observability
            "state_counters": _get_state_counters(),
            # PR-B: Cache summary for this turn
            "cache_summary_this_turn": summarize_cache_events(get_cache_events_this_turn()),
        },
    }
    return resp


# =============================================================================
# STREAMING RUN_TURN (SSE support)
# =============================================================================


async def run_turn_streaming(user_text: str, session_state: Optional[Dict[str, Any]] = None):
    """
    Streaming version of run_turn that yields SSE events.

    Runs the graph normally until response_polish, then streams the final
    assistant message. For code-only paths (short-circuit), simulates streaming.

    Yields SSE events in the format:
        {"type": "token", "data": "..."} - streaming token
        {"type": "complete", "data": {...}} - final state with all extractions

    Args:
        user_text: The user's message.
        session_state: Optional session state from previous turns.

    Yields:
        Dict with SSE event data.
    """

    _debug("=" * 60)
    _debug("RUN_TURN_STREAMING START", user_text=user_text)
    _debug("=" * 60)

    session_state = session_state or {}
    thread_id = session_state.get("thread_id") or str(uuid4())

    # Previous state snapshot for progress heuristics
    prev_ti = TripInputs(**session_state.get("trip_inputs", {}))

    # Build metadata with today_iso from session_state (defaults to current date)
    metadata = deepcopy(session_state.get("metadata", {}))
    if "today_iso" in session_state:
        metadata["today_iso"] = session_state["today_iso"]
    elif "today_iso" not in metadata:
        metadata["today_iso"] = date.today().isoformat()

    # =========================================================================
    # REAL-TIME STREAMING: Create streaming context for LLM nodes
    # =========================================================================
    # This context allows specialist/strategy nodes to emit tokens in real-time
    # while the graph continues executing. Tokens are consumed below via
    # the background task pattern.
    # NOTE: StreamingContext is stored in a module-level registry (NOT state.metadata)
    # because asyncio.Queue is not serializable by LangGraph's checkpointer.
    from app.planner.streaming import (
        StreamingContext,
        register_streaming_context,
        unregister_streaming_context,
    )

    streaming_ctx = StreamingContext()
    # Store thread_id in metadata so nodes can look up the streaming context
    # The actual StreamingContext is in the registry, not metadata (to avoid serialization issues)

    # Reset turn-specific metadata counters
    metadata.pop("validator_failures", None)
    metadata.pop("no_progress_turns", None)
    metadata.pop("last_intent", None)
    # Clear turn-scoped context fields - nodes will re-set them as needed
    # last_question_field is set by nodes that ask questions, cleared here so stale
    # context from previous turns doesn't influence short-circuit detection
    metadata.pop("last_question_field", None)
    # Clear pending actions to prevent stale actions from triggering on unrelated inputs
    metadata.pop("pending_action", None)
    metadata.pop("pending_typo_corrections", None)
    # Clear deferred intent/strategy to prevent stale deferrals
    metadata.pop("deferred_intent", None)
    metadata.pop("deferred_strategy_topic", None)
    # Clear routing_reason (set fresh each turn by gate evaluator)
    metadata.pop("routing_reason", None)

    # =========================================================================
    # LLM BUDGET: Reset per-turn counters (must match run_turn) (PR2: Use constants)
    # =========================================================================
    metadata[LLM_CALLS_THIS_TURN] = 0  # Integer counter for LLM call budget
    metadata[LLM_CALL_BLOCKED_REASON] = {}  # v5: dict for per-node tracking
    metadata[LLM_CALL_SITES] = []  # v5: track which nodes called LLM
    metadata[DELTAS_APPLIED_THIS_TURN] = []  # v5: track field changes this turn
    metadata[RESPONSE_SOURCE_NODE] = None  # v5: first node to produce response
    metadata[RESPONSE_GENERATION_PROVENANCE] = None  # v5: response generation provenance

    # =========================================================================
    # v7 Final v5: Reset per-turn metadata keys to avoid stale overrides
    # =========================================================================
    # These keys are turn-scoped and must be cleared to prevent previous-turn
    # state from leaking into routing/scoring decisions.
    metadata.pop("answered_question_target_this_turn", None)
    metadata.pop("answered_question_id_this_turn", None)
    metadata.pop("suggestion_target_override", None)
    metadata.pop("extractor_skipped_reason", None)
    metadata.pop("response_writer_node", None)
    metadata.pop("parse_provenance", None)
    metadata.pop("response_text_hash", None)  # Reset for set_final_response

    # =========================================================================
    # V12: Initialize per-turn instrumentation (node journal, tripwires)
    # =========================================================================
    init_turn_instrumentation(metadata)

    # Build input state
    # Reset turn-specific flags to prevent stale state from persisting
    incoming_flags = deepcopy(session_state.get("flags", {}))
    incoming_flags.pop("generate_plan", None)
    incoming_flags.pop("generate_requested", None)
    # Clear short-circuit flags so each turn re-detects from scratch
    incoming_flags.pop("short_circuit", None)
    incoming_flags.pop("short_circuit_response", None)
    incoming_flags.pop("short_circuit_action", None)
    # Clear fast-path and polish flags - these are turn-specific
    incoming_flags.pop("fast_path", None)
    incoming_flags.pop("fast_path_field", None)
    incoming_flags.pop("skip_polish", None)
    incoming_flags.pop("lqa_prepass", None)
    incoming_flags.pop("lqa_field", None)
    incoming_flags.pop("lqa_bail_reason", None)
    incoming_flags.pop("deterministic_place_parse", None)

    # =========================================================================
    # V16: Store previous turn's suggestions for suggestion-click detection
    # =========================================================================
    prev_suggestions = session_state.get("suggested_responses", [])
    if prev_suggestions:
        metadata["last_offered_suggestions"] = [s for s in prev_suggestions if isinstance(s, str)]
    else:
        metadata.pop("last_offered_suggestions", None)

    state = GraphState(
        user_text=user_text,
        trip_inputs=TripInputs(**session_state.get("trip_inputs", {})),
        metadata=metadata,
        flags=incoming_flags,
        last_summary=session_state.get("last_summary"),
        branches=deepcopy(session_state.get("branches", [])),
        suggested_responses=deepcopy(session_state.get("suggested_responses", [])),
        errors=_deserialize_errors(session_state.get("errors", [])),
        chat_history=deepcopy(session_state.get("chat_history", [])),
        # Persist question_target across turns for LQA to intercept direct answers
        question_target=session_state.get("question_target"),
        # Persist strategy_topic for topic-aware template suggestions
        strategy_topic=session_state.get("strategy_topic"),
        # Persist strategy expansion context across turns (V35: added pending_strategy_expansion)
        strategy_expansion_tier=session_state.get("strategy_expansion_tier"),
        strategy_expansion_target=session_state.get("strategy_expansion_target"),
        pending_strategy_expansion=session_state.get("pending_strategy_expansion", False),
        # Carry forward loop guard and turn tracking state
        loop_guard=deepcopy(session_state.get("loop_guard", {})),
        questions_asked=deepcopy(session_state.get("questions_asked", {})),
        turn_number=session_state.get("turn_number", 0),
    )

    # V37: Restore end_date_bypassed from session_state
    if session_state.get("end_date_bypassed", False):
        state.metadata["end_date_bypassed"] = True

    # Phase 1: Capture pre-turn snapshot for state integrity checking
    _ = capture_pre_turn_snapshot(state)

    # Use a unique thread_id per turn
    turn_thread_id = f"{thread_id}_{uuid4().hex[:8]}"

    # Register streaming context with turn_thread_id (for lookup by nodes)
    # Store turn_thread_id in metadata so nodes can look up the streaming context
    register_streaming_context(turn_thread_id, streaming_ctx)
    state.metadata["_streaming_thread_id"] = turn_thread_id

    # ==========================================================================
    # PREDICT NODE EXECUTION FOR SSE PROGRESS TRACKING
    # ==========================================================================
    # Check if this turn will execute an LLM node and emit node_status event
    # for frontend to show progress bar instead of loading dots
    # ==========================================================================
    strategy_prediction = _predict_strategy_execution(state, user_text)
    if strategy_prediction and strategy_prediction.will_execute:
        # Strategy node has special handling with stage/tier/topic
        yield {
            "type": "node_status",
            "data": {
                "node": "strategy_node",
                "status": "started",
                "label": f"Planning {strategy_prediction.topic}",
                "icon_key": strategy_prediction.topic,
                "stage": strategy_prediction.stage,
                "tier": strategy_prediction.tier,
                "topic": strategy_prediction.topic,
                "max_tokens": strategy_prediction.max_tokens,
                "estimated_duration_ms": strategy_prediction.estimated_duration_ms,
            },
        }
    else:
        # Check for other LLM-based nodes (specialist nodes, required_fields, etc.)
        node_prediction = _predict_node_execution(state, user_text)
        if node_prediction and node_prediction.will_execute:
            yield {
                "type": "node_status",
                "data": {
                    "node": node_prediction.node,
                    "status": "started",
                    "label": node_prediction.label,
                    "icon_key": node_prediction.icon_key,
                    "estimated_duration_ms": node_prediction.estimated_duration_ms,
                },
            }

    # =========================================================================
    # RUN GRAPH WITH REAL-TIME TOKEN STREAMING
    # =========================================================================
    # Run graph in background task while consuming tokens from streaming context.
    # LLM nodes emit tokens via streaming_ctx during execution.
    # After graph completes, fall back to simulated streaming if no tokens were emitted.
    result: GraphState | dict = state  # Initialize with current state; updated by run_graph
    tokens_streamed_during_execution = 0

    async def run_graph():
        """Execute the graph and finalize streaming context when done."""
        nonlocal result
        try:
            result = await app.ainvoke(
                state, config={"configurable": {"thread_id": turn_thread_id}}
            )
        except StateRegressionError as e:
            _debug_error(
                "StateRegressionError caught in run_turn_streaming",
                node=e.node_name,
                diff_summary=e.diff_summary,
            )
            result = handle_state_regression_error(state, e)
        finally:
            # Signal end of streaming
            await streaming_ctx.finalize()

    # Start graph execution in background
    graph_task = asyncio.create_task(run_graph())

    # Consume tokens as they arrive from LLM nodes during graph execution
    try:
        async for token in streaming_ctx.tokens(timeout=0.1):
            tokens_streamed_during_execution += 1
            yield {"type": "token", "data": token}
    except Exception as e:
        _debug_error("Error consuming streaming tokens", error=str(e))

    # Wait for graph to complete if not already done
    await graph_task

    # Cleanup: unregister streaming context from registry
    unregister_streaming_context(turn_thread_id)

    _debug(
        "REAL_TIME_STREAMING_COMPLETE",
        tokens_streamed=tokens_streamed_during_execution,
    )

    # Normalize to GraphState
    if isinstance(result, dict):
        result = GraphState.model_validate(result)

    # Update progress metrics
    try:
        made_progress = _progress_signal(prev_ti, result.trip_inputs)
        meta = result.metadata or {}
        if made_progress:
            meta["no_progress_turns"] = 0
        else:
            meta["no_progress_turns"] = int(meta.get("no_progress_turns", 0)) + 1
        result.metadata = meta
    except Exception:
        pass

    result_meta = result.metadata or {}
    result_flags = result.flags or {}

    # Print token usage summary
    _debug_token_summary(result)
    _debug_suggestions(result.suggested_responses, source="FINAL RESPONSE (STREAMING)")

    # Get the final assistant message to stream
    final_message = result.last_summary or ""

    # ==========================================================================
    # FINALIZE RESPONSE PROVENANCE (before streaming decision)
    # ==========================================================================
    # Set final response provenance BEFORE streaming decision so the decision
    # uses the correct, finalized provenance value.
    # ==========================================================================
    if final_message:
        writer_node = (
            result_meta.get("response_writer_node")
            or result_meta.get("response_source_node")
            or "unknown"
        )
        provenance_kind = result_meta.get("response_generation_provenance") or "unknown"
        set_final_response(
            result,
            final_message,
            writer_node,
            provenance_kind,
        )
        # Re-read result_meta after finalization
        result_meta = result.metadata or {}

        # ==========================================================================
        # END-OF-TURN PROVENANCE SUMMARY (debugging guard)
        # ==========================================================================
        prev_hash = result_meta.get("response_text_hash")
        _debug(
            "PROVENANCE_SUMMARY",
            response_writer_node=result_meta.get("response_writer_node"),
            response_generation_provenance=result_meta.get("response_generation_provenance"),
            response_text_hash_changed=(prev_hash is not None),
            parse_provenance=result_meta.get("parse_provenance"),
        )

    # ==========================================================================
    # V12: END-OF-TURN JOURNAL DUMP (duplication detection)
    # ==========================================================================
    dump_turn_journal(result)

    # Determine if this was a deterministic/template/codegen response (simulated streaming)
    # or an LLM response (real-time streaming behavior)
    is_short_circuit = bool(result_flags.get("short_circuit"))
    response_gen_provenance = result_meta.get("response_generation_provenance", "unknown")

    # Import streaming mode detection
    from app.planner.streaming import StreamingMode, get_streaming_mode

    # Use finalized response_generation_provenance to decide streaming mode
    # LLM responses should NOT use simulated streaming (which adds artificial delays)
    is_deterministic_response = response_gen_provenance in (
        "template",
        "deterministic",
        "codegen",
        "cached",
    )

    # Stream the message
    if final_message:
        # P0: Track streaming duration for timeout debugging
        stream_start_time = time.perf_counter()
        tokens_streamed = 0

        # Get streaming mode using centralized detection
        response_writer = result_meta.get("response_writer_node", "")
        stream_mode = get_streaming_mode(result, response_writer, response_gen_provenance)

        # =====================================================================
        # REAL-TIME vs POST-HOC STREAMING DECISION
        # =====================================================================
        # If tokens were already streamed during graph execution (real-time from LLM),
        # skip post-hoc streaming entirely. Otherwise, use simulated streaming for
        # non-LLM responses (deterministic, template, cached, short_circuit).
        # =====================================================================
        if tokens_streamed_during_execution > 0:
            # Tokens were already streamed in real-time during graph execution
            stream_mode = StreamingMode.REAL_LLM
            tokens_streamed = tokens_streamed_during_execution
            _debug(
                "Real-time LLM streaming completed",
                tokens_streamed=tokens_streamed_during_execution,
                response_length=len(final_message),
            )
            # No additional streaming needed - tokens already sent
        elif is_short_circuit or is_deterministic_response:
            # Simulated streaming for code-generated/template messages
            stream_mode = {
                "template": StreamingMode.SIMULATED_TEMPLATE,
                "cached": StreamingMode.SIMULATED_CACHED,
            }.get(response_gen_provenance, StreamingMode.SIMULATED_DETERMINISTIC)
            _debug(
                "Simulating streaming for non-LLM response",
                reason=(
                    f"provenance:{response_gen_provenance}"
                    if is_deterministic_response
                    else "short_circuit"
                ),
            )
            async for token in simulate_streaming(final_message):
                tokens_streamed += 1
                yield {"type": "token", "data": token}
        else:
            # =====================================================================
            # FALLBACK: SIMULATED STREAMING FOR UNEXPECTED NON-STREAMED LLM RESPONSES
            # =====================================================================
            # If an LLM response somehow didn't stream tokens (e.g., cache hit path),
            # use simulated streaming to maintain consistent UX.
            # =====================================================================
            stream_mode = StreamingMode.SIMULATED_LLM_FALLBACK
            _debug(
                "Fallback simulated streaming for LLM response (no real-time tokens)",
                provenance=response_gen_provenance,
                response_length=len(final_message),
            )
            async for token in simulate_streaming(final_message):
                tokens_streamed += 1
                yield {"type": "token", "data": token}

        # P0: Log streaming duration for timeout analysis
        stream_duration_ms = (time.perf_counter() - stream_start_time) * 1000
        warn_threshold = settings.streaming_warn_threshold_ms
        is_slow = stream_duration_ms > warn_threshold
        _debug(
            "STREAMING_DURATION" + (" [SLOW]" if is_slow else ""),
            mode=stream_mode,
            duration_ms=round(stream_duration_ms, 1),
            threshold_ms=warn_threshold,
            tokens_streamed=tokens_streamed,
            response_length=len(final_message),
            chars_per_second=(
                round(len(final_message) / (stream_duration_ms / 1000), 1)
                if stream_duration_ms > 0
                else 0
            ),
        )

    # Enrich branches with Unsplash images before returning
    # Pre-fetch Unsplash images first to populate cache
    # Uses different variants for each hero image slot:
    # - variant 0: Main branch image (image_url) + first hero (signature view)
    # - variant 1: Second hero image (daylight wander)
    # - variant 2: Third hero image (evening vibe)
    enriched_branches = []
    if result.branches:
        from app.services.unsplash import get_image_url_sync, prefetch_destination_images

        # Get activities for activity-specific images
        activities = None
        if (
            hasattr(result.trip_inputs, "activity_settings")
            and result.trip_inputs.activity_settings
        ):
            activities = getattr(result.trip_inputs.activity_settings, "categories", None)

        # Pre-fetch Unsplash images for all branch destinations to populate cache
        # Always prefetch base destination first (no activities) as fallback,
        # then optionally prefetch activity-specific variants
        for branch in result.branches:
            dests = branch.get("destinations", [])
            if dests and dests[0]:
                try:
                    # First, ensure base destination images are cached
                    await prefetch_destination_images(dests[0])
                    # Then, if activities specified, try activity-specific images
                    if activities:
                        await prefetch_destination_images(dests[0], activities=activities)
                except Exception as e:
                    _debug(f"Image prefetch failed for {dests[0]}: {e}")

        for branch in result.branches:
            branch_copy = dict(branch)  # Don't mutate original
            dests = branch_copy.get("destinations", [])
            primary_dest = dests[0] if dests else "travel"
            # Add image fields if not already present (using different variants)
            # If activities provided, images will be activity-specific (e.g., "Dubai hiking")
            if "image_url" not in branch_copy:
                branch_copy["image_url"] = get_image_url_sync(
                    primary_dest, variant=0, width=1600, height=900, activities=activities
                )
            if "hero_images" not in branch_copy:
                branch_copy["hero_images"] = [
                    get_image_url_sync(
                        primary_dest, variant=0, width=1600, height=900, activities=activities
                    ),  # Signature view
                    get_image_url_sync(
                        primary_dest, variant=1, width=900, height=600, activities=activities
                    ),  # Daylight wander
                    get_image_url_sync(
                        primary_dest, variant=2, width=900, height=600, activities=activities
                    ),  # Evening vibe
                ]
            enriched_branches.append(branch_copy)
        _debug(f"Enriched {len(enriched_branches)} branches with images (activities={activities})")

    # Build final response (same as run_turn)
    resp = {
        "assistant_message": final_message,
        "trip_inputs": result.trip_inputs.model_dump(exclude_none=True),
        "ready_to_generate": result.ready_to_generate,
        "branches": enriched_branches if enriched_branches else result.branches,
        "suggested_responses": result.suggested_responses,
        "errors": result.errors,
        "session_state": {
            "trip_inputs": result.trip_inputs.model_dump(),
            "metadata": result_meta,
            "flags": result_flags,
            "last_summary": result.last_summary,
            "branches": enriched_branches if enriched_branches else result.branches,
            "suggested_responses": result.suggested_responses,
            "errors": result.errors,
            "thread_id": thread_id,
            "router_intent": getattr(result, "intent", None),
            "strategy_topic": getattr(result, "strategy_topic", None),
            "question_target": getattr(result, "question_target", None),
            "short_circuit_type": result_flags.get("short_circuit"),
            "llm_calls_made": result_meta.get("llm_calls_made", 0),
            "cache_hits": result_meta.get("cache_hits", 0),
            "confidence_routing": result_meta.get("confidence_routing"),
            # Strategy expansion context for tier-based token optimization
            # (V35: added pending_strategy_expansion)
            "strategy_expansion_tier": getattr(result, "strategy_expansion_tier", None),
            "strategy_expansion_target": getattr(result, "strategy_expansion_target", None),
            "pending_strategy_expansion": getattr(result, "pending_strategy_expansion", False),
            # V37: Persist end_date_bypassed for flexible return date option
            "end_date_bypassed": (result.metadata or {}).get("end_date_bypassed", False),
            # State integrity tracking (Phase 1)
            "loop_guard": getattr(result, "loop_guard", {}),
            "questions_asked": getattr(result, "questions_asked", {}),
            "turn_number": getattr(result, "turn_number", 0),
            # State counters for observability
            "state_counters": _get_state_counters(),
        },
    }

    # Yield complete event with full state
    yield {"type": "complete", "data": resp}


# =============================================================================
# DATABASE-INTEGRATED ENTRYPOINT (matches plan.py's plan_trip)
# =============================================================================


def _history_to_messages(history: List[models.ChatMessage]) -> List[Dict[str, str]]:
    """
    Convert database ChatMessage objects to message format for state.

    Filters out empty messages (e.g., unfilled assistant placeholders).
    """
    messages: List[Dict[str, str]] = []
    for entry in history:
        content = entry.content or ""
        if not content.strip():
            continue
        messages.append({"role": entry.role, "content": content})
    return messages


async def _resolve_parent_trip_context(
    db: AsyncSession,
    *,
    session: models.Session,
    requested_parent_id: Optional[int],
) -> Optional[models.TripContext]:
    """
    Resolve the parent TripContext for the current planning request (async).
    """
    if requested_parent_id is not None:
        parent_ctx = await db.get(models.TripContext, requested_parent_id)
        if not parent_ctx:
            raise ValueError("trip_context_id not found")
        if parent_ctx.session_id != session.id:
            raise ValueError("trip_context_id does not belong to this session")
        return parent_ctx

    return await get_latest_trip_context_for_session(db, session=session)


def _trip_inputs_to_document(ti: TripInputs) -> DocumentTripInputs:
    """Convert graph TripInputs to DocumentTripInputs for persistence.

    Includes all fields including booking preferences to match plan.py behavior.
    """
    # Convert booking_types dict to BookingTypes model (tri-state defaults)
    booking_types_data = ti.booking_types or {}
    booking_types = BookingTypes(
        hotels=booking_types_data.get("hotels", "suggested"),
        flights=booking_types_data.get("flights", "off"),
        ground_transport=booking_types_data.get("ground_transport", "off"),
        activities=booking_types_data.get("activities", "suggested"),
    )

    # Convert flight_settings dict to FlightSettings model
    # Note: Use explicit None checks because .get() returns None if key exists with None value
    flight_settings_data = ti.flight_settings or {}
    round_trip_val = flight_settings_data.get("round_trip")
    cabin_class_val = flight_settings_data.get("cabin_class")
    direct_only_val = flight_settings_data.get("direct_only")
    flight_settings = FlightSettings(
        round_trip=round_trip_val if round_trip_val is not None else True,
        cabin_class=cabin_class_val if cabin_class_val is not None else "economy",
        direct_only=direct_only_val if direct_only_val is not None else False,
    )

    # Convert hotel_settings dict to HotelSettings model
    hotel_settings_data = ti.hotel_settings or {}
    hotel_settings = HotelSettings(
        min_stars=hotel_settings_data.get("min_stars", 0),
        amenities=hotel_settings_data.get("amenities", []),
    )

    # Convert activity_settings dict to ActivitySettings model
    activity_settings_data = ti.activity_settings or {}
    activity_settings = ActivitySettings(
        categories=activity_settings_data.get("categories", []),
    )

    # Convert transport_settings dict to TransportSettings model
    transport_settings_data = ti.transport_settings or {}
    transport_settings = TransportSettings(
        car=transport_settings_data.get("car", False),
        train=transport_settings_data.get("train", False),
        bus=transport_settings_data.get("bus", False),
    )

    return DocumentTripInputs(
        destinations=ti.destinations or [],
        origin=ti.origin,
        start_date=ti.start_date,
        end_date=ti.end_date,
        adults=ti.adults,
        children=ti.children,
        requires_assistance=ti.requires_assistance,
        budget=int(ti.budget) if ti.budget else None,
        currency=ti.currency or DEFAULT_CURRENCY,
        multi_city_intent=ti.multi_city_intent,
        missing_fields=compute_trip_readiness(ti.model_dump(exclude_none=True)).missing_core,
        # Booking preferences - match plan.py behavior
        booking_types=booking_types,
        flight_settings=flight_settings,
        hotel_settings=hotel_settings,
        activity_settings=activity_settings,
        transport_settings=transport_settings,
    )


def _branches_to_document(
    branches: List[Dict[str, Any]],
    trip_context_id: int,
    activities: list[str] | None = None,
) -> List[DocumentBranch]:
    """Convert graph branches to DocumentBranch list for persistence."""
    doc_branches: List[DocumentBranch] = []
    _debug(f"_branches_to_document called with {len(branches)} branches, activities={activities}")

    # Import here to avoid circular imports
    from app.services.unsplash import get_image_url_sync

    for idx, spec in enumerate(branches):
        branch_destinations = spec.get("destinations", []) or []
        if not isinstance(branch_destinations, list):
            branch_destinations = [branch_destinations] if branch_destinations else []

        # Generate images based on first destination (using different variants)
        # variant 0: Main branch image + signature view
        # variant 1: Daylight wander
        # variant 2: Evening vibe
        # If activities provided, images will be activity-specific (e.g., "Dubai hiking")
        primary_dest = branch_destinations[0] if branch_destinations else "travel"
        _debug(
            f"Branch {idx}: generating images for dest: {primary_dest}, " f"activities={activities}"
        )
        branch_image_url = get_image_url_sync(
            primary_dest, variant=0, width=1600, height=900, activities=activities
        )
        _debug(f"Branch {idx}: image_url={branch_image_url[:80]}...")
        # Generate hero images with different variants for unique imagery
        branch_hero_images = [
            get_image_url_sync(
                primary_dest, variant=0, width=1600, height=900, activities=activities
            ),
            get_image_url_sync(
                primary_dest, variant=1, width=900, height=600, activities=activities
            ),
            get_image_url_sync(
                primary_dest, variant=2, width=900, height=600, activities=activities
            ),
        ]
        _debug(f"Branch {idx}: hero_images generated, first={branch_hero_images[0][:80]}...")

        doc_branch = DocumentBranch(
            id=spec.get("id") or f"branch_{trip_context_id}_{idx}",
            label=str(spec.get("label", "")),
            description=str(spec.get("description", "")),
            destinations=branch_destinations,
            origin=_normalize_str(spec.get("origin")),
            start_date=_normalize_date(spec.get("start_date")),
            end_date=_normalize_date(spec.get("end_date")),
            adults=_normalize_int(spec.get("adults")),
            children=_normalize_int(spec.get("children")),
            requires_assistance=spec.get("requires_assistance"),
            budget=_normalize_budget(spec.get("budget")),
            currency=(
                _normalize_currency(spec.get("currency"), default=DEFAULT_CURRENCY)
                or DEFAULT_CURRENCY
            ),
            is_primary=(idx == 0),
            tiles=BranchTileIds(
                stays=spec.get("tiles", {}).get("stays", []),
                flights=spec.get("tiles", {}).get("flights", []),
                activities=spec.get("tiles", {}).get("activities", []),
            ),
            image_url=branch_image_url,
            hero_images=branch_hero_images,
        )
        doc_branches.append(doc_branch)

    return doc_branches


async def plan_trip_graph(
    db: AsyncSession, session_id: str, req: PlanRequest
) -> PlanDocumentResponse:
    """
    Main planning flow using the LangGraph-based planner (async).

    This is the database-integrated entry point that:
    1. Gets/creates session and document
    2. Fetches chat history
    3. Runs the LangGraph planning flow
    4. Persists results to the database

    Args:
        db: SQLAlchemy async database session.
        session_id: Session ID from cookie.
        req: PlanRequest containing user message.

    Returns:
        PlanDocumentResponse: The complete response including document state.
    """
    _debug("=" * 60)
    _debug("PLAN_TRIP_GRAPH START", session_id=session_id, user_message=req.message[:50])
    _debug("=" * 60)

    # 1. Setup session and context
    db_session = await get_or_create_session(db, session_token=session_id, lock_for_update=True)

    # Fetch chat history
    history_rows = await fetch_chat_history(
        db, session=db_session, limit=settings.plan_chat_history_limit
    )
    history_messages = _history_to_messages(history_rows)

    # Get existing document and parent context
    existing_doc = await get_document(db, session=db_session)
    existing_doc_data: Optional[PlanDocumentData] = None
    parent_trip_context_id: Optional[int] = None

    if existing_doc:
        existing_doc_data = get_document_data(existing_doc)
        parent_trip_context_id = existing_doc_data.trip_context_id

    parent_ctx = await _resolve_parent_trip_context(
        db,
        session=db_session,
        requested_parent_id=parent_trip_context_id,
    )

    try:
        # Create trip context for this turn
        trip_ctx = await create_trip_context(
            db,
            session=db_session,
            parent_trip_context=parent_ctx,
            req_message=req.message,
        )

        # 2. Record user message with trip_inputs snapshot for rollback
        user_message_content = (
            "Generate my trip options" if _is_generate_plan_trigger(req.message) else req.message
        )
        # Capture current trip_inputs as snapshot for undo functionality
        trip_inputs_snapshot = None
        if existing_doc_data and existing_doc_data.trip_inputs:
            ti = existing_doc_data.trip_inputs
            trip_inputs_snapshot = {
                "destinations": ti.destinations or [],
                "origin": ti.origin,
                "start_date": ti.start_date,
                "end_date": ti.end_date,
                "adults": ti.adults,
                "children": ti.children,
                "requires_assistance": ti.requires_assistance,
                "budget": ti.budget,
                "currency": ti.currency,
                "multi_city_intent": ti.multi_city_intent,
                "booking_types": ti.booking_types.model_dump() if ti.booking_types else {},
                "flight_settings": ti.flight_settings.model_dump() if ti.flight_settings else {},
                "hotel_settings": ti.hotel_settings.model_dump() if ti.hotel_settings else {},
                "activity_settings": (
                    ti.activity_settings.model_dump() if ti.activity_settings else {}
                ),
                "transport_settings": (
                    ti.transport_settings.model_dump() if ti.transport_settings else {}
                ),
            }
        await record_chat_message(
            db,
            session=db_session,
            trip_context=trip_ctx,
            role="user",
            content=user_message_content,
            metadata=None,
            trip_inputs_snapshot=trip_inputs_snapshot,
        )

        # 3. Prepare placeholder for assistant message
        assistant_chat = await record_chat_message(
            db,
            session=db_session,
            trip_context=trip_ctx,
            role="assistant",
            content="",
            metadata=None,
        )

        # 4. Build initial state from existing document
        initial_trip_inputs: Dict[str, Any] = {}
        initial_branches: List[Dict[str, Any]] = []

        if existing_doc_data and existing_doc_data.trip_inputs:
            ti = existing_doc_data.trip_inputs
            initial_trip_inputs = {
                "destinations": ti.destinations or [],
                "origin": ti.origin,
                "start_date": ti.start_date,
                "end_date": ti.end_date,
                "adults": ti.adults,
                "children": ti.children,
                "requires_assistance": ti.requires_assistance,
                "budget": ti.budget,
                "currency": ti.currency,
                "multi_city_intent": ti.multi_city_intent,
                "booking_types": ti.booking_types.model_dump() if ti.booking_types else {},
                "flight_settings": ti.flight_settings.model_dump() if ti.flight_settings else {},
                "hotel_settings": ti.hotel_settings.model_dump() if ti.hotel_settings else {},
                "activity_settings": (
                    ti.activity_settings.model_dump() if ti.activity_settings else {}
                ),
                "transport_settings": (
                    ti.transport_settings.model_dump() if ti.transport_settings else {}
                ),
            }
            # Load existing branches
            if existing_doc_data.branches:
                initial_branches = [b.model_dump() for b in existing_doc_data.branches]

        # 5. Run the graph
        today_iso = _today_iso(req.timezone)

        # Build metadata with ui_phase and suggestion_clicked from request
        metadata = {
            "today_iso": today_iso,
            "tiles": (
                {t_id: t.model_dump() for t_id, t in (existing_doc_data.tiles or {}).items()}
                if existing_doc_data
                else {}
            ),
        }
        if req.ui_phase is not None:
            metadata["ui_phase"] = req.ui_phase
        if req.suggestion_clicked is not None:
            metadata["suggestion_clicked"] = req.suggestion_clicked

        session_state = {
            "trip_inputs": initial_trip_inputs,
            "branches": initial_branches,
            "metadata": metadata,
            "flags": {},
            "last_summary": None,
            "suggested_responses": [],
            "errors": [],
            "thread_id": f"session_{session_id}",
            "chat_history": history_messages,  # Pass chat history for LLM context
        }

        result = await run_turn(req.message, session_state)

        # 6. Update assistant message
        assistant_chat.content = result.get("assistant_message", "")

        # 7. Get or create the PlanDocument
        plan_doc = await get_or_create_document(db, session=db_session, updated_by="planner")

        try:
            await db.refresh(plan_doc)
        except Exception:
            pass

        # 8. Build document structures from result
        trip_inputs_model = _trip_inputs_to_document(TripInputs(**result.get("trip_inputs", {})))

        doc_branches: List[DocumentBranch] = []
        tiles_dict: Dict[str, TileSchema] = {}

        result_branches = result.get("branches", [])
        _debug(f"PLAN_TRIP_GRAPH: result_branches count={len(result_branches)}")
        if result_branches:
            _debug(f"PLAN_TRIP_GRAPH: Processing {len(result_branches)} branches for images")
            # Pre-fetch ALL Unsplash image variants for all branch destinations
            # before building documents. This populates the in-memory cache so
            # branches get unique Unsplash images.
            from app.services.unsplash import prefetch_destination_images

            # Get activities for activity-specific images
            trip_inputs_dict = result.get("trip_inputs", {})
            activities = trip_inputs_dict.get("activity_settings", {}).get("categories", [])

            for branch_spec in result_branches:
                branch_dests = branch_spec.get("destinations", [])
                if branch_dests and isinstance(branch_dests, list) and branch_dests[0]:
                    try:
                        # First, ensure base destination images are cached (with DB persistence)
                        num_base = await prefetch_destination_images(branch_dests[0], db)
                        _debug(
                            f"Pre-fetched {num_base} base image variants for "
                            f"branch destination: {branch_dests[0]}"
                        )
                        # Then, if activities specified, try activity-specific images
                        if activities:
                            num_activity = await prefetch_destination_images(
                                branch_dests[0], db, activities=activities
                            )
                            _debug(
                                f"Pre-fetched {num_activity} activity-specific image variants for "
                                f"branch destination: {branch_dests[0]} (activities={activities})"
                            )
                    except Exception as e:
                        _debug(f"Image prefetch failed for {branch_dests[0]}: {e}")

            doc_branches = _branches_to_document(
                result_branches, trip_ctx.id, activities=activities
            )

            # Get tiles from metadata
            tiles_from_search = result.get("session_state", {}).get("metadata", {}).get("tiles", {})
            for tile_id, tile_data in tiles_from_search.items():
                if isinstance(tile_data, dict):
                    tiles_dict[tile_id] = TileSchema(**tile_data)

        # 9. Apply the planner update to the document
        # Only provide branches if the graph actually generated new ones.
        # If branches=None, apply_planner_update keeps existing branches and still
        # cascades trip_inputs changes into the primary branch.
        branches_to_apply = doc_branches if doc_branches else None

        plan_doc = await apply_planner_update(
            db,
            doc=plan_doc,
            trip_context_id=trip_ctx.id,
            trip_inputs=trip_inputs_model,
            branches=branches_to_apply,
            tiles=tiles_dict or None,
        )

        doc_data = get_document_data(plan_doc)

        # 10. Build response
        doc_data_dict = doc_data.model_dump()
        doc_data_dict["assistant_message"] = assistant_chat.content
        doc_data_dict["assistant_message_id"] = str(assistant_chat.id)
        doc_data_dict["ready_to_generate"] = result.get("ready_to_generate", False)
        doc_data_dict["suggested_responses"] = result.get("suggested_responses", [])

        if _DEBUG_LOG:
            print("[DEBUG] === AFTER MERGE ===")
            print(json.dumps(doc_data_dict, indent=2, default=str))
            print("=" * 80)

        doc_data_with_chat = PlanDocumentData(**doc_data_dict)

        response = PlanDocumentResponse(
            version=plan_doc.version,
            updated_by=plan_doc.updated_by,
            document=doc_data_with_chat,
            updated_at=plan_doc.updated_at.isoformat(),
            changes_made=True,
        )

        await db.commit()
        _debug("PLAN_TRIP_GRAPH COMPLETE", version=plan_doc.version)
        return response

    except Exception:
        await db.rollback()
        raise
