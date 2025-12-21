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
from enum import Enum, IntEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple
from uuid import uuid4
from zoneinfo import ZoneInfo

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
from app.known_places import (
    KNOWN_COUNTRIES,
    is_known_place,
    normalize_place_synonym,
)
from app.schemas import (
    ActivitySettings,
    BookingTypes,
    BranchTileIds,
    DocumentBranch,
    DocumentTripInputs,
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

# =============================================================================
# CORE FIELD PRIORITY (MVP Hardening)
# =============================================================================
# Single authoritative priority order for missing field collection.
# Used consistently in: compute_trip_readiness, pre-core specialists,
# required_fields_node, and exit contract enforcement.
CORE_FIELD_PRIORITY: List[str] = [
    "destinations",
    "start_date",
    "end_date",
    "origin",
    "adults",
    "budget",
]

# =============================================================================
# CANONICAL FIELD ORDER (v5 Routing Observability)
# =============================================================================
# Stable ordering for deltas_applied in RoutingDecisionFinal.
# Used to ensure deterministic field ordering across Python versions.
CANONICAL_FIELD_ORDER: List[str] = [
    "destinations",
    "origin",
    "start_date",
    "end_date",
    "adults",
    "children",
    "budget",
    "activity_settings",
    "flight_settings",
    "hotel_settings",
    "transport_settings",
    "booking_types",
    "strategy_settings",
]

# Schema version for RoutingDecisionFinal - increment only if:
# - Field names/types change
# - redirect_reason algorithm changes
ROUTING_DECISION_SCHEMA_VERSION: int = 1

# Fallback suggestions when template is missing for a field
FALLBACK_SUGGESTIONS: List[str] = [
    "Not sure yet",
    "I'm flexible",
    "Suggest options",
]

# =============================================================================
# DEBUG LOGGING
# =============================================================================
_DEBUG_LOG = settings.debug_plan_messages

# Retry count for API errors (from settings)
_PLAN_MAX_RETRIES = settings.llm_max_retries


def _debug(message: str, **kwargs: Any) -> None:
    """Print debug message if DEBUG_PLAN_MESSAGES is enabled.

    This function is designed to be non-fatal - any error during logging
    is silently caught to prevent debug code from crashing production.
    """
    if not _DEBUG_LOG:
        return
    try:
        # Truncate message if too long
        max_len = 2000
        if len(message) > max_len:
            message = message[:max_len] + "...(truncated)"

        # Safely format kwargs, handling any serialization errors
        extras_parts = []
        for k, v in kwargs.items():
            try:
                v_str = str(v)
                if len(v_str) > 200:
                    v_str = v_str[:200] + "..."
                extras_parts.append(f"{k}={v_str}")
            except Exception:
                extras_parts.append(f"{k}=<unserializable>")
        extras = " ".join(extras_parts) if extras_parts else ""
        print(f"[PLAN_GRAPH DEBUG] {message} {extras}".strip())
    except Exception:
        # Never re-raise - debug logging must not crash production
        pass


def _debug_error(message: str, **kwargs: Any) -> None:
    """Print ERROR message - always visible and prominent.

    This function is designed to be non-fatal - any error during logging
    is silently caught to prevent debug code from crashing production.
    """
    if not _DEBUG_LOG:
        return
    try:
        # Truncate message if too long
        max_len = 2000
        if len(message) > max_len:
            message = message[:max_len] + "...(truncated)"

        # Safely format kwargs, handling any serialization errors
        extras_parts = []
        for k, v in kwargs.items():
            try:
                v_str = str(v)
                if len(v_str) > 200:
                    v_str = v_str[:200] + "..."
                extras_parts.append(f"{k}={v_str}")
            except Exception:
                extras_parts.append(f"{k}=<unserializable>")
        extras = " ".join(extras_parts) if extras_parts else ""
        print(f"[PLAN_GRAPH ERROR] ❌ {message} {extras}".strip())
    except Exception:
        # Never re-raise - debug logging must not crash production
        pass


def _debug_suggestions(suggestions: List[str], source: str = "") -> None:
    """Print user prompt suggestions for debug visibility.

    This function is designed to be non-fatal - any error during logging
    is silently caught to prevent debug code from crashing production.
    """
    if not _DEBUG_LOG:
        return
    try:
        src_tag = f" ({source})" if source else ""
        if suggestions:
            # Truncate each suggestion and limit count
            truncated = [s[:100] + "..." if len(s) > 100 else s for s in suggestions[:5]]
            suggestions_str = " | ".join(truncated)
            print(f"[PLAN_GRAPH DEBUG] 💡 Prompt suggestions{src_tag}: [{suggestions_str}]")
        else:
            print(f"[PLAN_GRAPH DEBUG] 💡 Prompt suggestions{src_tag}: (none)")
    except Exception:
        # Never re-raise - debug logging must not crash production
        pass


# =============================================================================
# SAFE DEBUG: Guaranteed non-throwing debug for use in safety wrappers
# =============================================================================
def safe_debug(message: str, **kwargs: Any) -> None:
    """
    Guaranteed non-throwing debug function for use inside @safe_node and recovery code.

    Unlike _debug(), this function wraps EVERYTHING in try/except including
    the initial condition check and all string formatting. Use this in places
    where even a debug failure could break critical recovery paths.
    """
    try:
        _debug(message, **kwargs)
    except Exception:
        # Absolutely never throw - this is the safety net
        pass


def safe_debug_error(message: str, **kwargs: Any) -> None:
    """Guaranteed non-throwing error debug for safety wrappers."""
    try:
        _debug_error(message, **kwargs)
    except Exception:
        pass


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
                    state.last_summary = state.last_summary or "How can I help with your trip?"
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
                    state.last_summary = "I'm having trouble processing that. Could you try again?"

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


def _debug_node_entry(node_name: str, state: "GraphState") -> None:
    """Log entry into a graph node."""
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


def _debug_node_exit(node_name: str, state: "GraphState") -> None:
    """Log exit from a graph node."""
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
# OBSERVABILITY HELPERS
# =============================================================================


# Gate Precedence Enum - explicit ordering of routing gates
# Lower values = higher priority (checked first)
class GatePrecedence(IntEnum):
    """
    Explicit ordering of routing gates in _route_after_extraction().
    Gates are checked in priority order; first match wins.

    Gate Ordering Rationale:
    - SHORT_CIRCUIT: Highest priority for greetings/confirmations
    - FAST_PATH: Bootstrap optimization (turn 1 only when strategy_bootstrap_active)
    - SPECIALIST_PRE_CORE: Domain keywords before core complete
    - STRATEGY_TOPIC_SWITCH: Mid-session topic changes (e.g., adding "diving")
    - STRATEGY_PRE_CORE_VALUE: First-turn strategy value-first responses
    - CORE_COLLECTION: Collect missing core fields
    - Remaining gates for various heuristic routing
    """

    SHORT_CIRCUIT = 1  # Greeting, acknowledgment, off-topic
    FAST_PATH = 2  # Direct field updates (bootstrap only when strategy_bootstrap_active)
    SPECIALIST_PRE_CORE = 3  # Specialist keyword when core fields missing (pre-core mode)
    STRATEGY_TOPIC_SWITCH = 4  # Mid-session strategy topic change (e.g., "diving")
    STRATEGY_PRE_CORE_VALUE = 5  # Strategy topic detected + core missing → value-first response
    CORE_COLLECTION = 6  # Core fields missing → required_fields
    HIGH_CONFIDENCE = 7  # High conf + short input + no intent keywords
    QUESTION_KEYWORD = 8  # Phase 6: Question-word + domain keyword combo
    KEYWORD_HEURISTIC = 9  # Unambiguous domain keywords
    SCORING_ROUTER = 10  # Phase 3: Multi-signal scoring deterministic router
    ROUTER_LLM = 99  # Default: invoke router LLM


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

# Override phrases that bypass topic switch cooldown
TOPIC_SWITCH_OVERRIDE_PHRASES: frozenset = frozenset(
    {
        "actually",
        "instead",
        "switch to",
        "change to",
        "rather",
        "forget",
        "no wait",
    }
)

# Intent verb patterns that indicate topic switch request
TOPIC_SWITCH_INTENT_VERBS: frozenset = frozenset(
    {
        "want",
        "wanna",
        "go",
        "do",
        "plan",
        "try",
        "include",
        "add",
        "also",
    }
)


# =============================================================================
# GATE EVALUATOR (Phase 6 Consolidation)
# =============================================================================
# Centralized gate evaluation logic. All routing decisions go through here.


@dataclass
class GateResult:
    """Result of gate evaluation - computed once per routing decision.

    Stored immutably in state.metadata["gate_result"] for observability.
    """

    gate_fired: GatePrecedence
    destination: str  # Node to route to
    reason: str  # Human-readable explanation
    skipped_gates: List[str] = field(default_factory=list)  # Gates evaluated but not fired
    eval_time_ms: float = 0.0  # Time taken to evaluate all gates
    # For mutating state in the router function
    intent: Optional[str] = None
    strategy_topic: Optional[str] = None
    question_target: Optional[str] = None
    metadata_updates: Dict[str, Any] = field(default_factory=dict)
    # v5 Routing Observability fields
    lqa_reason: Optional[str] = None  # e.g., "lqa:hit", "deterministic:place_answer"
    llm_budget_used: int = 0  # Value of llm_calls_this_turn at gate evaluation time
    date_clarify_mode: bool = False  # Whether date clarification is active


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
    # Response provenance (template, llm, codegen, etc.)
    response_provenance: str = "unknown"
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


class GateEvaluator:
    """
    Centralized gate evaluator for routing decisions.

    All routing gates are evaluated here in priority order.
    Nodes should read the GateResult from state rather than re-deriving conditions.
    """

    # Phase 6: Question words that, combined with domain keywords, indicate clear intent
    QUESTION_WORDS = frozenset(
        {
            "what",
            "which",
            "how",
            "where",
            "when",
            "can",
            "could",
            "should",
            "do",
            "does",
            "are",
            "is",
        }
    )

    # Domain keywords for question-word combo detection
    DOMAIN_KEYWORDS = {
        "flights": {"flight", "flights", "flying", "fly", "airline", "airlines", "airport"},
        "hotels": {
            "hotel",
            "hotels",
            "stay",
            "accommodation",
            "lodging",
            "room",
            "rooms",
            "resort",
        },
        "transport": {
            "transport",
            "train",
            "trains",
            "bus",
            "car rental",
            "rental car",
            "drive",
            "driving",
        },
        "activities": {
            "activity",
            "activities",
            "things to do",
            "tour",
            "tours",
            "excursion",
            "sightseeing",
        },
    }

    @classmethod
    def evaluate(cls, state: "GraphState") -> GateResult:
        """
        Evaluate all gates and return the result.

        This is the ONLY place where routing decisions should be made.

        Args:
            state: Current graph state

        Returns:
            GateResult with gate_fired, destination, and metadata
        """
        start_time = time.perf_counter()
        skipped_gates = []

        # Extract commonly used values
        user_text = state.user_text or ""
        user_text_lower = user_text.lower()
        ti = state.trip_inputs
        flags = state.flags
        extraction_conf = state.metadata.get("extraction_confidence", {})

        # Determine if we should prefer dates over destinations for question ordering
        # This applies when: strategy topic detected but no destinations extracted
        prefer_date_first = cls._should_prefer_date_first(user_text_lower, ti)

        # Use TripReadiness for consistent missing-fields computation
        readiness = compute_trip_readiness(ti, prefer_date_first=prefer_date_first)

        # Gate 0: GENERATE_REQUESTED
        # When user triggers plan generation (e.g., "GENERATE_PLAN_NOW"), route
        # directly to generate handling. This takes priority over everything else.
        # EXCEPTION: Block if blocking date errors exist (DATE_AMBIGUOUS_YEAR, DATE_RANGE_INVALID)
        if flags.get("generate_requested"):
            # Check for blocking date errors
            has_blocking_date_errors = False
            if state.errors:
                for err in state.errors:
                    if (
                        isinstance(err, NormalizationError)
                        and err.code in DATE_BLOCKING_ERROR_CODES
                    ):
                        has_blocking_date_errors = True
                        break
                    # Also check string errors for backwards compatibility
                    if isinstance(err, str) and any(
                        code in err for code in DATE_BLOCKING_ERROR_CODES
                    ):
                        has_blocking_date_errors = True
                        break

            # Also check metadata for date_clarify_mode
            if state.metadata.get("date_clarify_mode"):
                has_blocking_date_errors = True

            if has_blocking_date_errors:
                # Block generation and redirect to dates clarification
                _debug(
                    "GENERATE_REQUESTED blocked due to date errors",
                    errors_count=len(state.errors),
                    date_clarify_mode=state.metadata.get("date_clarify_mode"),
                )
                _date_stats["dates_clarify_shown_count"] += 1
                return cls._build_result(
                    gate=GatePrecedence.CORE_COLLECTION,
                    destination="required_fields",
                    reason="generate_blocked:date_errors",
                    start_time=start_time,
                    skipped=skipped_gates,
                    state=state,
                    metadata_updates={
                        "router_path": "generate_blocked:date_errors",
                        "router_bypassed": True,
                        "date_clarify_mode": True,
                    },
                )

            return cls._build_result(
                gate=GatePrecedence.SHORT_CIRCUIT,  # High priority
                destination="generate_responder",
                reason="generate_requested",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                metadata_updates={
                    "router_path": "generate_requested",
                    "router_bypassed": True,
                },
            )
        skipped_gates.append("GENERATE_REQUESTED")

        # Gate 1: SHORT_CIRCUIT
        if flags.get("short_circuit"):
            sc_type = flags.get("short_circuit")
            return cls._build_result(
                gate=GatePrecedence.SHORT_CIRCUIT,
                destination="short_circuit_responder",
                reason=f"short_circuit:{sc_type}",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                metadata_updates={"router_path": f"short_circuit:{sc_type}"},
            )
        skipped_gates.append("SHORT_CIRCUIT")

        # Gate 1b: INFEASIBILITY_DETECTION
        # Import here to avoid circular dependency (function defined later)
        has_infeasibility, infeasibility_type = _has_infeasibility_signals(user_text, state)
        if has_infeasibility:
            return cls._build_result(
                gate=GatePrecedence.SHORT_CIRCUIT,  # Same priority as short_circuit
                destination="correction_node",
                reason=f"infeasibility:{infeasibility_type}",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                intent="correction_needed",
                metadata_updates={
                    "router_path": f"infeasibility_detection:{infeasibility_type}",
                    "router_bypassed": True,
                    "router_bypass_reason": f"infeasibility:{infeasibility_type}",
                },
            )
        skipped_gates.append("INFEASIBILITY_DETECTION")

        # Gate 2: FAST_PATH
        # IMPORTANT: Only fire for strategy bootstrap when strategy_bootstrap_active is True
        # This prevents bootstrap from suppressing STRATEGY_TOPIC_SWITCH on subsequent turns
        if flags.get("fast_path"):
            fp_field = flags.get("fast_path_field", "unknown")
            # Strategy bootstrap fast path only fires when bootstrap is active (turn 1)
            if fp_field == "strategy_bootstrap":
                if not flags.get("strategy_bootstrap_active", False):
                    _debug(
                        "FAST_PATH skipped: strategy_bootstrap expired",
                        fast_path_field=fp_field,
                        strategy_bootstrap_active=flags.get("strategy_bootstrap_active"),
                    )
                    skipped_gates.append("FAST_PATH:bootstrap_expired")
                else:
                    return cls._build_result(
                        gate=GatePrecedence.FAST_PATH,
                        destination="required_fields_node",
                        reason=f"fast_path:{fp_field}",
                        start_time=start_time,
                        skipped=skipped_gates,
                        state=state,
                        intent="required_fields",
                        metadata_updates={"router_path": f"fast_path:{fp_field}"},
                    )
            else:
                # Non-bootstrap fast paths can fire normally
                return cls._build_result(
                    gate=GatePrecedence.FAST_PATH,
                    destination="required_fields_node",
                    reason=f"fast_path:{fp_field}",
                    start_time=start_time,
                    skipped=skipped_gates,
                    state=state,
                    intent="required_fields",
                    metadata_updates={"router_path": f"fast_path:{fp_field}"},
                )
        skipped_gates.append("FAST_PATH")

        # Gate 2.3: INTENT_ONLY_FAST_PATH (MVP Hardening)
        # When user provides only topic/intent keywords (e.g., "adventure hiking outdoors")
        # with no extractable entities, skip extractor LLM and route directly to
        # required_fields asking for destinations.
        # NOTE: Strategy topics (hiking, skiing, etc.) are handled by STRATEGY_PRE_CORE_VALUE
        # gate instead, which provides value-first responses.
        if not readiness.core_complete:
            intent_only_result = cls._check_intent_only_input(user_text_lower, ti)
            if intent_only_result:
                detected_topic = intent_only_result
                # If it's a strategy topic, let STRATEGY_PRE_CORE_VALUE handle it
                is_strategy_topic = detected_topic in {
                    "hiking",
                    "skiing",
                    "diving",
                    "cycling",
                    "boating",
                }
                if is_strategy_topic:
                    # Skip this gate, let STRATEGY_PRE_CORE_VALUE provide value-first response
                    _debug(
                        "INTENT_ONLY_FAST_PATH: deferring to STRATEGY_PRE_CORE_VALUE",
                        topic=detected_topic,
                    )
                else:
                    return cls._build_result(
                        gate=GatePrecedence.FAST_PATH,  # Same priority as fast_path
                        destination="required_fields_node",
                        reason=f"intent_only:{detected_topic}",
                        start_time=start_time,
                        skipped=skipped_gates,
                        state=state,
                        intent="required_fields",
                        question_target="destinations",
                        strategy_topic=None,
                        metadata_updates={
                            "router_path": f"intent_only_fast_path:{detected_topic}",
                            "router_bypassed": True,
                            "router_bypass_reason": f"intent_only:{detected_topic}",
                            "intent_only_detected": True,
                            "intent_only_topic": detected_topic,
                        },
                    )
        skipped_gates.append("INTENT_ONLY_FAST_PATH")

        # Gate 2.5: SPECIALIST_PRE_CORE
        # When specialist_pre_core_enabled, route to specialist nodes even before core
        # fields are complete if user clearly asks about hotels/flights/activities.
        # The specialist will acknowledge intent and ask for minimal missing fields inline.
        # IMPORTANT: Skip this gate entirely if strategy_pre_core is eligible, to avoid
        # shadowing the value-first strategy path for open-ended planning prompts.
        strategy_pre_core_eligible = cls._is_strategy_pre_core_eligible(
            user_text_lower, ti, readiness
        )
        if settings.specialist_pre_core_enabled and not readiness.core_complete:
            if strategy_pre_core_eligible:
                _debug(
                    "SPECIALIST_PRE_CORE skipped: strategy_pre_core_eligible",
                    missing_core=readiness.missing_core,
                )
            else:
                pre_core_result = cls._check_specialist_pre_core(user_text_lower, readiness, ti)
                if pre_core_result:
                    intent_name, destination = pre_core_result
                    return cls._build_result(
                        gate=GatePrecedence.SPECIALIST_PRE_CORE,
                        destination=destination,
                        reason=f"specialist_pre_core:{intent_name}",
                        start_time=start_time,
                        skipped=skipped_gates,
                        state=state,
                        intent=intent_name,
                        metadata_updates={
                            "router_path": f"specialist_pre_core:{intent_name}",
                            "router_bypassed": True,
                            "router_bypass_reason": f"specialist_pre_core:{intent_name}",
                            "pre_core_mode": True,
                            "missing_core_fields": readiness.missing_core,
                        },
                    )
        skipped_gates.append("SPECIALIST_PRE_CORE")

        # =====================================================================
        # Gate 3.5: STRATEGY_TOPIC_SWITCH
        # =====================================================================
        # Mid-session strategy topic change detection (e.g., user adds "diving")
        #
        # Triggers when:
        # 1. New strategy keyword detected in user text
        # 2. User expresses intent via verb patterns ("wanna", "go", "plan", "try")
        # 3. Topic differs from last_strategy_topic OR explicitly re-requested
        # 4. Cooldown has passed OR override phrase used ("actually", "instead")
        #
        # Behavior:
        # - If blocking_errors exist: store pending_strategy_topic, route to date clarify
        # - If core complete + no blocking errors: route to strategy stage 1
        # - If destinations missing: route to strategy stage 0
        # =====================================================================
        topic_switch_result = cls._check_strategy_topic_switch(
            user_text_lower, ti, readiness, state.metadata, state.turn_number
        )
        if topic_switch_result:
            new_topic, switch_reason = topic_switch_result

            # Check for blocking errors - must handle dates first
            if readiness.has_blocking_errors:
                _debug(
                    "STRATEGY_TOPIC_SWITCH: deferred due to blocking errors",
                    new_topic=new_topic,
                    blocking_errors=readiness.blocking_errors,
                )
                # Store pending topic for auto-fire after errors clear
                return cls._build_result(
                    gate=GatePrecedence.STRATEGY_TOPIC_SWITCH,
                    destination="required_fields_node",
                    reason=f"topic_switch_deferred:{new_topic}:blocking_errors",
                    start_time=start_time,
                    skipped=skipped_gates,
                    state=state,
                    intent="required_fields",
                    question_target="dates",
                    strategy_topic=new_topic,
                    metadata_updates={
                        "router_path": f"topic_switch_deferred:{new_topic}",
                        "router_bypassed": True,
                        "pending_strategy_topic": new_topic,
                        "date_clarify_mode": True,
                        "topic_switch_reason": switch_reason,
                    },
                )

            # Determine stage based on readiness
            if readiness.core_complete:
                # Core complete - route to strategy stage 1
                strategy_stage = 1
            elif not ti.destinations:
                # No destinations - route to strategy stage 0 (value-first)
                strategy_stage = 0
            else:
                # Has destinations but missing other core - stage 1
                strategy_stage = 1

            destination = STRATEGY_TOPIC_TO_NODE.get(new_topic, "strategy_node")
            return cls._build_result(
                gate=GatePrecedence.STRATEGY_TOPIC_SWITCH,
                destination=destination,
                reason=f"topic_switch:{new_topic}:{switch_reason}",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                intent="strategy",
                strategy_topic=new_topic,
                metadata_updates={
                    "router_path": f"strategy_topic_switch:{new_topic}",
                    "router_bypassed": True,
                    "router_bypass_reason": f"topic_switch:{new_topic}",
                    "strategy_stage": strategy_stage,
                    "last_strategy_topic": new_topic,
                    "last_strategy_topic_turn": state.turn_number,
                    "topic_switch_cooldown_until_turn": state.turn_number + 1,
                    "topic_switch_reason": switch_reason,
                },
            )
        skipped_gates.append("STRATEGY_TOPIC_SWITCH")

        # Gate 4: STRATEGY_PRE_CORE_VALUE
        # Route to strategy_node (stage 0) when:
        # 1. Strategy topic detected (hiking, skiing, diving, cycling, boating)
        # 2. Core fields are missing (not readiness.core_complete)
        # 3. No destination entities extracted
        # 4. User did NOT explicitly ask for "questions only"
        strategy_pre_core_result = cls._check_strategy_pre_core_value(
            user_text_lower, ti, readiness, extraction_conf
        )
        if strategy_pre_core_result:
            topic, question_target = strategy_pre_core_result
            return cls._build_result(
                gate=GatePrecedence.STRATEGY_PRE_CORE_VALUE,
                destination="strategy_node",
                reason=f"strategy_pre_core_value:{topic}",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                intent="strategy",
                strategy_topic=topic,
                question_target=question_target,
                metadata_updates={
                    "router_path": f"strategy_pre_core_value:{topic}",
                    "router_bypassed": True,
                    "router_bypass_reason": f"strategy_pre_core_value:{topic}",
                    "pre_core_mode": True,
                    "strategy_stage": 0,
                    "missing_core_fields": readiness.missing_core,
                },
            )
        skipped_gates.append("STRATEGY_PRE_CORE_VALUE")

        # Gate 5: CORE_COLLECTION
        # HARD CAP: Never route to required_fields when missing_core is empty
        # and there are no blocking errors. This prevents question churn.
        if readiness.has_blocking_errors:
            # Blocking date errors - force date clarification
            return cls._build_result(
                gate=GatePrecedence.CORE_COLLECTION,
                destination="required_fields_node",
                reason=f"blocking_errors:{','.join(readiness.blocking_errors)}",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                intent="required_fields",
                question_target="dates",
                metadata_updates={
                    "router_path": "blocking_errors_gate",
                    "router_bypassed": True,
                    "date_clarify_mode": True,
                },
            )

        if not readiness.core_complete:
            # Determine question_target from readiness
            question_target = readiness.question_target

            # Infer strategy_topic from activity_settings if present
            activity_categories = ti.activity_settings.get("categories", [])
            strategy_topics = {"hiking", "skiing", "diving", "cycling", "boating"}
            inferred_topic = None
            for cat in activity_categories:
                if cat.lower() in strategy_topics:
                    inferred_topic = cat.lower()
                    break

            return cls._build_result(
                gate=GatePrecedence.CORE_COLLECTION,
                destination="required_fields_node",
                reason=f"missing:{','.join(readiness.missing_core)}",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                intent="required_fields",
                question_target=question_target,
                strategy_topic=inferred_topic,
                metadata_updates={
                    "router_path": "core_fields_gate",
                    "router_bypassed": True,
                    "router_bypass_reason": f"missing:{','.join(readiness.missing_core)}",
                },
            )
        skipped_gates.append("CORE_COLLECTION")

        # Gate 4: HIGH_CONFIDENCE
        conf_level = extraction_conf.get("level", "medium")
        conf_overall = extraction_conf.get("overall", 0.5)
        no_typos = not extraction_conf.get("typo_suggestions", {})
        is_short_input = len(user_text.strip()) <= 30

        # Check for intent keywords that would require routing
        intent_keywords = (
            "cycling",
            "hiking",
            "diving",
            "skiing",
            "boating",
            "flight",
            "flights",
            "hotel",
            "hotels",
            "boutique",
            "accommodation",
            "stay",
            "where to stay",
            "transport",
            "train",
            "car rental",
            "activity",
            "activities",
            "things to do",
            "how",
            "what",
            "when",
            "where",
            "should",
            "recommend",
            "suggest",
            "find",
            "book",
            # Flight preference keywords (should route to flights specialist)
            "direct",
            "nonstop",
            "business",
            "first class",
            "economy",
            "cabin",
            "layover",
            # Hotel preference keywords (should route to hotels specialist)
            "star",
            "amenities",
            "breakfast",
            "gym",
            "pool",
            "spa",
        )
        has_intent_keywords = any(kw in user_text_lower for kw in intent_keywords)

        # Phase 6: Relaxed threshold from 0.92 to 0.88 for short inputs
        conf_threshold = 0.88 if is_short_input else CONFIDENCE_THRESHOLD_SKIP_ROUTER

        if (
            conf_overall >= conf_threshold
            and readiness.core_complete
            and no_typos
            and conf_level == "high"
            and is_short_input
            and not has_intent_keywords
        ):
            return cls._build_result(
                gate=GatePrecedence.HIGH_CONFIDENCE,
                destination="required_fields_node",
                reason=f"high_confidence:{conf_overall:.2f}",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                intent="required_fields",
                metadata_updates={
                    "router_path": "high_confidence_bypass",
                    "router_bypassed": True,
                },
            )
        skipped_gates.append("HIGH_CONFIDENCE")

        # Gate 4.5 (Phase 6): QUESTION_KEYWORD combo
        # "What hotels...", "Which flights...", "How do I get transport..."
        question_keyword_result = cls._check_question_keyword_combo(user_text_lower)
        if question_keyword_result:
            intent_name, destination = question_keyword_result
            return cls._build_result(
                gate=GatePrecedence.QUESTION_KEYWORD,
                destination=destination,
                reason=f"question_keyword:{intent_name}",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                intent=intent_name,
                metadata_updates={
                    "router_path": f"question_keyword:{intent_name}",
                    "router_bypassed": True,
                    "router_bypass_reason": f"question_keyword:{intent_name}",
                },
            )
        skipped_gates.append("QUESTION_KEYWORD")

        # Gate 5: KEYWORD_HEURISTIC
        # Import _detect_intent_from_keywords (defined later in file)
        keyword_intent = _detect_intent_from_keywords(user_text_lower)
        if keyword_intent:
            intent_name, strategy_topic = keyword_intent
            # Map intent to destination
            destination_map = {
                "strategy": "strategy_node",
                "flights": "flights_node",
                "hotels": "hotels_node",
                "transport": "transport_node",
                "activities": "activities_node",
            }
            destination = destination_map.get(intent_name, "required_fields_node")

            return cls._build_result(
                gate=GatePrecedence.KEYWORD_HEURISTIC,
                destination=destination,
                reason=f"keyword:{intent_name}",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                intent=intent_name,
                strategy_topic=strategy_topic,
                metadata_updates={
                    "router_path": f"keyword_heuristic:{intent_name}",
                    "router_bypassed": True,
                    "router_bypass_reason": f"keyword:{intent_name}",
                },
            )
        skipped_gates.append("KEYWORD_HEURISTIC")

        # Gate 6 (Phase 3): SCORING_ROUTER
        # Multi-signal scoring for cases where keyword heuristic alone isn't enough
        # but combined signals are reliable enough to bypass router LLM
        scoring_result = _try_deterministic_router(user_text, state)
        if scoring_result and scoring_result.should_bypass:
            destination_map = {
                "strategy": "strategy_node",
                "flights": "flights_node",
                "hotels": "hotels_node",
                "transport": "transport_node",
                "activities": "activities_node",
            }
            destination = destination_map.get(scoring_result.intent, "required_fields_node")

            return cls._build_result(
                gate=GatePrecedence.SCORING_ROUTER,
                destination=destination,
                reason=f"scoring:{scoring_result.intent}:{scoring_result.score}",
                start_time=start_time,
                skipped=skipped_gates,
                state=state,
                intent=scoring_result.intent,
                strategy_topic=scoring_result.strategy_topic,
                metadata_updates={
                    "router_path": f"scoring_router:{scoring_result.intent}",
                    "router_bypassed": True,
                    "router_bypass_reason": f"score:{scoring_result.score}",
                    "scoring_signals": scoring_result.signals,
                },
            )
        skipped_gates.append("SCORING_ROUTER")

        # Gate 99: ROUTER_LLM (default fallback)
        return cls._build_result(
            gate=GatePrecedence.ROUTER_LLM,
            destination="router",
            reason="no_gate_matched",
            start_time=start_time,
            skipped=skipped_gates,
            state=state,
            metadata_updates={
                "router_path": "llm",
                "why_not_bypassed": "no_gate_matched",
            },
        )

    @classmethod
    def _check_question_keyword_combo(cls, text_lower: str) -> Optional[tuple[str, str]]:
        """
        Phase 6: Check for question-word + domain keyword combinations.

        Examples:
        - "What hotels are available?" → hotels_node
        - "Which flights should I take?" → flights_node
        - "How do I get around?" → transport_node

        Returns:
            (intent_name, destination_node) if match, None otherwise
        """
        words = text_lower.split()
        if not words:
            return None

        # Check if starts with question word
        first_word = words[0].rstrip("?.,")
        if first_word not in cls.QUESTION_WORDS:
            return None

        # Check for domain keywords
        for intent_name, keywords in cls.DOMAIN_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                destination_map = {
                    "flights": "flights_node",
                    "hotels": "hotels_node",
                    "transport": "transport_node",
                    "activities": "activities_node",
                }
                return (intent_name, destination_map[intent_name])

        return None

    # Keywords that strongly indicate specialist intent (used in pre-core mode)
    SPECIALIST_PRE_CORE_KEYWORDS = {
        "hotels": {
            "hotel",
            "hotels",
            "hostel",
            "hostels",
            "boutique hotel",
            "accommodation",
            "lodging",
            "where to stay",
            "stay",
            "airbnb",
            "resort",
            "resorts",
            "motel",
            "guest house",
            "guesthouse",
            "bed and breakfast",
            "b&b",
        },
        "flights": {
            "flight",
            "flights",
            "flying",
            "fly",
            "airline",
            "airlines",
            "airport",
            "airfare",
            "plane",
            "direct flight",
            "nonstop",
            "layover",
        },
        "activities": {
            "things to do",
            "what to do",
            "activities",
            "activity",
            "tour",
            "tours",
            "excursion",
            "excursions",
            "sightseeing",
            "attractions",
            "visit",
        },
        "transport": {
            "transport",
            "transportation",
            "train",
            "trains",
            "bus",
            "buses",
            "car rental",
            "rental car",
            "drive",
            "taxi",
            "uber",
            "get around",
        },
    }

    # Intent-only keywords (for MVP fast path)
    # These indicate user is expressing trip intent without concrete details
    INTENT_ONLY_KEYWORDS = {
        "adventure": "adventure",
        "hiking": "hiking",
        "outdoors": "adventure",
        "nature": "adventure",
        "beach": "beach",
        "relaxation": "relaxation",
        "skiing": "skiing",
        "snowboarding": "skiing",
        "diving": "diving",
        "snorkeling": "diving",
        "cycling": "cycling",
        "biking": "cycling",
        "boating": "boating",
        "sailing": "boating",
        "romantic": "romantic",
        "honeymoon": "romantic",
        "family": "family",
        "kids": "family",
        "cultural": "cultural",
        "historical": "cultural",
        "food": "culinary",
        "culinary": "culinary",
        "wine": "culinary",
        "luxury": "luxury",
        "budget": "budget",
        "backpacking": "budget",
    }

    @classmethod
    def _check_intent_only_input(cls, text_lower: str, ti: "TripInputs") -> Optional[str]:
        """
        Check if input is intent-only (topic keywords without extractable entities).

        Intent-only inputs like "adventure hiking outdoors" or "beach vacation"
        have no destinations, dates, origin, budget, or travelers to extract.
        We can skip the extractor LLM and route directly to required_fields.

        Args:
            text_lower: Lowercase user input
            ti: Current trip inputs

        Returns:
            Detected topic/intent if intent-only, None otherwise
        """
        # If we already have any concrete data, not intent-only
        if ti.destinations or ti.origin or ti.start_date or ti.budget or ti.adults:
            return None

        # Check for intent keywords
        words = text_lower.split()
        detected_topics = []
        for word in words:
            # Clean punctuation
            clean_word = word.strip(".,!?;:")
            if clean_word in cls.INTENT_ONLY_KEYWORDS:
                detected_topics.append(cls.INTENT_ONLY_KEYWORDS[clean_word])

        if not detected_topics:
            return None

        # Check for extractable entities that would require LLM
        # Simple heuristics: look for numbers (dates/budget), place-like words
        entity_patterns = [
            r"\d",  # Numbers (dates, prices, travelers)
            r"\$|€|£|¥",  # Currency symbols
            r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec",  # Month names
            r"next|this|last",  # Relative time
            r"week|month|year",  # Time units
            r"from|departing",  # Origin indicators
        ]

        import re

        for pattern in entity_patterns:
            if re.search(pattern, text_lower):
                # Has extractable entities, not intent-only
                return None

        # Check for known place names (simplified - could be enhanced)
        # For now, check if any word is capitalized in original (before lowercasing)
        # This is a heuristic - place names are usually capitalized
        # Since we only have text_lower, skip this check

        # Intent-only detected - return the most specific topic
        # Prefer strategy topics over general ones
        strategy_topics = {"hiking", "skiing", "diving", "cycling", "boating"}
        for topic in detected_topics:
            if topic in strategy_topics:
                _debug(f"Intent-only fast path: detected strategy topic '{topic}'")
                return topic

        # Return first detected topic
        _debug(f"Intent-only fast path: detected topic '{detected_topics[0]}'")
        return detected_topics[0]

    @classmethod
    def _is_strategy_pre_core_eligible(
        cls, text_lower: str, ti: "TripInputs", readiness: "TripReadiness"
    ) -> bool:
        """
        Check if the current input qualifies for STRATEGY_PRE_CORE_VALUE gate.

        This is used to suppress other gates (like SPECIALIST_PRE_CORE) when
        the user is asking for open-ended strategy planning without destinations.

        Conditions:
        1. Core fields are missing (not readiness.core_complete)
        2. No destination entities extracted
        3. Strategy topic detected in user text or activity_settings
        4. User did NOT ask for "questions only"

        Args:
            text_lower: Lowercase user input
            ti: Current trip inputs
            readiness: Current trip readiness state

        Returns:
            True if strategy pre-core value path should take precedence
        """
        # Guard: must have core fields missing
        if readiness.core_complete:
            return False

        # Guard: must NOT have destinations
        if ti.destinations:
            return False

        # Guard: check for "questions only" phrases
        for phrase in cls.QUESTIONS_ONLY_PHRASES:
            if phrase in text_lower:
                return False

        # Check for strategy topic in user text
        for _topic, keywords in cls.STRATEGY_INTENT_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return True

        # Also check activity_settings for inferred topic
        activity_categories = ti.activity_settings.get("categories", [])
        for cat in activity_categories:
            if cat.lower() in cls.STRATEGY_TOPICS:
                return True

        return False

    @classmethod
    def _check_specialist_pre_core(
        cls, text_lower: str, readiness: "TripReadiness", ti: "TripInputs"
    ) -> Optional[tuple[str, str]]:
        """
        Check if user is asking about a specialist domain before core fields are complete.

        This enables "pre-core mode" where specialists can acknowledge intent and
        ask for minimal missing fields inline, rather than always routing to required_fields.

        IMPORTANT: This gate yields to STRATEGY_PRE_CORE_VALUE when strategy topics
        are detected without destinations. The caller must check _is_strategy_pre_core_eligible
        before calling this method.

        Args:
            text_lower: Lowercase user input
            readiness: Current trip readiness state
            ti: Current trip inputs (used for strategy eligibility check)

        Returns:
            (intent_name, destination_node) if specialist keyword detected, None otherwise
        """
        # Only trigger if we have at least destination (most important core field)
        # This prevents routing to specialist when user hasn't even mentioned where they're going
        ti_has_destination = bool(readiness.ti.destinations) if hasattr(readiness, "ti") else False

        # Check for specialist keywords
        for intent_name, keywords in cls.SPECIALIST_PRE_CORE_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                # CRITICAL: Yield to STRATEGY_PRE_CORE_VALUE for "activities" when
                # a strategy topic is also detected. "Plan a hiking trip with outdoor
                # activities" should go to strategy_node, not activities_node.
                if intent_name == "activities":
                    # Check if any strategy keywords are present
                    for topic, strategy_kws in cls.STRATEGY_INTENT_KEYWORDS.items():
                        if any(kw in text_lower for kw in strategy_kws):
                            _debug(
                                "specialist_pre_core yielding to strategy_pre_core",
                                intent=intent_name,
                                strategy_topic=topic,
                            )
                            return None  # Let STRATEGY_PRE_CORE_VALUE handle it

                destination_map = {
                    "flights": "flights_node",
                    "hotels": "hotels_node",
                    "transport": "transport_node",
                    "activities": "activities_node",
                }
                _debug(
                    "specialist_pre_core triggered",
                    intent=intent_name,
                    missing_core=readiness.missing_core,
                    has_destination=ti_has_destination,
                )
                return (intent_name, destination_map[intent_name])

        return None

    # Phrases indicating user wants only questions (bypass strategy_pre_core_value)
    QUESTIONS_ONLY_PHRASES = frozenset(
        {
            "ask me questions",
            "what do you need from me",
            "what do you need to know",
            "what info do you need",
            "what information do you need",
            "need more info",
            "what else do you need",
            "just ask me",
            "go ahead and ask",
        }
    )

    # Strategy topics that qualify for pre-core value-first responses
    STRATEGY_TOPICS = frozenset({"hiking", "skiing", "diving", "cycling", "boating"})

    # Keywords that indicate strategy intent (broader than strict topic names)
    STRATEGY_INTENT_KEYWORDS = {
        "hiking": {
            "hike",
            "hiking",
            "trek",
            "trekking",
            "trail",
            "trails",
            "mountain",
            "mountains",
        },
        # boating MUST come before skiing: "skippered" and "bareboat" contain "ski"
        "boating": {
            "boat",
            "boating",
            "sail",
            "sailing",
            "yacht",
            "kayak",
            "canoe",
            "cruise",
            "skippered",
            "bareboat",
        },
        "skiing": {"skiing", "snowboard", "snowboarding", "slopes", "powder", "alpine"},
        "diving": {"dive", "diving", "scuba", "snorkel", "snorkeling", "underwater"},
        "cycling": {"bike", "biking", "bicycle", "cycling", "cycle", "ride", "pedal"},
    }

    @classmethod
    def _check_strategy_pre_core_value(
        cls,
        text_lower: str,
        ti: "TripInputs",
        readiness: "TripReadiness",
        extraction_conf: Dict[str, Any],
    ) -> Optional[tuple[str, str]]:
        """
        Check if we should route to strategy_node stage 0 for value-first response.

        Fires when:
        1. Strategy topic detected (hiking, skiing, diving, cycling, boating)
        2. Core fields are missing (not readiness.core_complete)
        3. No destination entities extracted
        4. User did NOT explicitly ask for "questions only"

        Returns:
            (strategy_topic, question_target) if should fire, None otherwise
        """
        # Guard: must have core fields missing
        if readiness.core_complete:
            return None

        # Guard: must NOT have destinations (otherwise go to normal strategy flow)
        if ti.destinations:
            return None

        # Guard: check for "questions only" phrases - user wants to be asked
        for phrase in cls.QUESTIONS_ONLY_PHRASES:
            if phrase in text_lower:
                _debug(
                    "strategy_pre_core_value bypassed: questions_only phrase detected",
                    phrase=phrase,
                )
                return None

        # Detect strategy topic from user text
        detected_topic = None
        for topic, keywords in cls.STRATEGY_INTENT_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                detected_topic = topic
                break

        # Also check activity_settings for inferred topic
        if not detected_topic:
            activity_categories = ti.activity_settings.get("categories", [])
            for cat in activity_categories:
                if cat.lower() in cls.STRATEGY_TOPICS:
                    detected_topic = cat.lower()
                    break

        if not detected_topic:
            return None

        # Determine question_target with priority:
        # 1. dates (ask month/season first - helps with strategy recommendations)
        # 2. origin (logistics)
        # 3. destinations (fallback only)
        # NOTE: Always use "dates" (not "start_date") for LQA/template compatibility
        question_target = "dates"  # Default: ask about timing first (canonical form)
        if ti.start_date:
            question_target = "origin"
        if ti.start_date and ti.origin:
            question_target = "destinations"

        _debug(
            "strategy_pre_core_value triggered",
            topic=detected_topic,
            missing_core=readiness.missing_core,
            question_target=question_target,
        )

        return (detected_topic, question_target)

    @classmethod
    def _check_strategy_topic_switch(
        cls,
        text_lower: str,
        ti: "TripInputs",
        readiness: "TripReadiness",
        metadata: Dict[str, Any],
        turn_number: int,
    ) -> Optional[tuple[str, str]]:
        """
        Check if user is requesting a mid-session strategy topic switch.

        This gate handles cases like "I wanna go diving in Argentina too" when
        the session already has hiking as the strategy topic.

        Triggers when:
        1. Auto-fire pending topic (deferred from previous turn due to blocking errors)
        2. Strategy keyword detected in user text
        3. User expresses intent via verb patterns ("wanna", "go", "plan", "try")
        4. Topic differs from last_strategy_topic OR explicitly re-requested
        5. Cooldown has passed OR override phrase used ("actually", "instead")

        Args:
            text_lower: Lowercase user input
            ti: Current trip inputs
            readiness: Current trip readiness state
            metadata: Session metadata containing topic switch state
            turn_number: Current turn number

        Returns:
            (new_topic, switch_reason) if topic switch should fire, None otherwise
        """
        # Check for auto-fire pending topic (from previous turn's deferred switch)
        auto_fire_topic = metadata.get("auto_fire_topic_switch")
        if auto_fire_topic:
            _debug(
                "STRATEGY_TOPIC_SWITCH: auto-firing pending topic",
                topic=auto_fire_topic,
            )
            return (auto_fire_topic, "auto_fire_pending")

        # =====================================================================
        # TURN 1 GUARD: Topic switch is for mid-session changes, not first turn
        # =====================================================================
        # On turn 1, use STRATEGY_PRE_CORE_VALUE instead (priority 5).
        # Topic switch (priority 4) should only fire when:
        # - turn_number >= 2, OR
        # - last_strategy_topic is set (indicates prior strategy interaction)
        last_strategy_topic = metadata.get("last_strategy_topic")
        if turn_number < 2 and not last_strategy_topic:
            _debug(
                "STRATEGY_TOPIC_SWITCH: skipped on turn 1 (use STRATEGY_PRE_CORE_VALUE)",
                turn_number=turn_number,
            )
            return None

        # Detect strategy topic from user text
        detected_topic = None
        for topic, keywords in cls.STRATEGY_INTENT_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                detected_topic = topic
                break

        if not detected_topic:
            return None

        # Check for intent verb patterns - user must be expressing desire
        has_intent_verb = any(verb in text_lower for verb in TOPIC_SWITCH_INTENT_VERBS)
        if not has_intent_verb:
            _debug(
                "STRATEGY_TOPIC_SWITCH: no intent verb detected",
                topic=detected_topic,
                text_preview=text_lower[:50],
            )
            return None

        # Get last strategy topic state
        last_topic = metadata.get("last_strategy_topic")
        cooldown_until = metadata.get("topic_switch_cooldown_until_turn", 0)

        # Check if this is the same topic as before (not a switch)
        if detected_topic == last_topic:
            # Check for explicit re-request patterns
            has_override = any(phrase in text_lower for phrase in TOPIC_SWITCH_OVERRIDE_PHRASES)
            if not has_override:
                _debug(
                    "STRATEGY_TOPIC_SWITCH: same topic, no override phrase",
                    topic=detected_topic,
                    last_topic=last_topic,
                )
                return None
            # User explicitly wants to revisit the same topic
            return (detected_topic, "explicit_revisit")

        # Different topic - check cooldown
        if turn_number <= cooldown_until:
            # Check for override phrases that bypass cooldown
            has_override = any(phrase in text_lower for phrase in TOPIC_SWITCH_OVERRIDE_PHRASES)
            if not has_override:
                _debug(
                    "STRATEGY_TOPIC_SWITCH: cooldown active, no override",
                    topic=detected_topic,
                    cooldown_until=cooldown_until,
                    turn_number=turn_number,
                )
                return None
            # Override phrase detected - allow switch
            return (detected_topic, "override_cooldown")

        # New topic, cooldown expired - allow switch
        return (detected_topic, "new_topic")

    @classmethod
    def _should_prefer_date_first(cls, text_lower: str, ti: "TripInputs") -> bool:
        """
        Check if we should prefer asking about dates before destinations.

        Returns True when intent is broad (strategy topic detected) but no
        destination entities have been extracted. In these cases, asking about
        timing first helps provide better strategy recommendations.

        Args:
            text_lower: Lowercase user input
            ti: Current trip inputs

        Returns:
            True if dates should be prioritized over destinations
        """
        # If destinations already exist, use normal priority
        if ti.destinations:
            return False

        # Check if strategy topic is detected in user text
        for topic, keywords in cls.STRATEGY_INTENT_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                _debug(
                    "prefer_date_first: strategy topic detected without destinations",
                    topic=topic,
                )
                return True

        # Also check activity_settings for inferred topic
        activity_categories = ti.activity_settings.get("categories", [])
        for cat in activity_categories:
            if cat.lower() in cls.STRATEGY_TOPICS:
                _debug(
                    "prefer_date_first: strategy category in activity_settings",
                    category=cat,
                )
                return True

        return False

    @classmethod
    def _build_result(
        cls,
        gate: GatePrecedence,
        destination: str,
        reason: str,
        start_time: float,
        skipped: List[str],
        state: "GraphState",
        intent: Optional[str] = None,
        strategy_topic: Optional[str] = None,
        question_target: Optional[str] = None,
        metadata_updates: Optional[Dict[str, Any]] = None,
    ) -> GateResult:
        """Build a GateResult with timing and v5 observability fields."""
        eval_time_ms = (time.perf_counter() - start_time) * 1000
        _record_gate_latency(eval_time_ms)

        # v5 fields: capture state at gate evaluation time
        llm_budget_used = state.metadata.get("llm_calls_this_turn", 0)
        date_clarify_mode = bool(state.metadata.get("date_clarify_mode", False))
        lqa_reason = state.metadata.get("lqa_reason")

        return GateResult(
            gate_fired=gate,
            destination=destination,
            reason=reason,
            skipped_gates=skipped,
            eval_time_ms=eval_time_ms,
            intent=intent,
            strategy_topic=strategy_topic,
            question_target=question_target,
            metadata_updates=metadata_updates or {},
            # v5 Routing Observability fields
            lqa_reason=lqa_reason,
            llm_budget_used=llm_budget_used,
            date_clarify_mode=date_clarify_mode,
        )


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

# =============================================================================
# STRATEGY EXPANSION TIERS (Phase 1: Token Optimization)
# =============================================================================


class StrategyExpansionTarget(str, Enum):
    """Expansion targets for strategy Stage 2 section-based expansion."""

    ITINERARY_OUTLINE = "itinerary_outline"  # High-level day-by-day skeleton
    DAY_DETAILS = "day_details"  # Detailed breakdown for specific day(s)
    ROUTES_TRAILS = "routes_trails"  # Specific routes, trails, or paths
    LOGISTICS = "logistics"  # Transport, transfers, timing
    BUDGET = "budget"  # Cost breakdown, money-saving tips
    GEAR_PACKING = "gear_packing"  # Equipment, packing list
    CONTINGENCIES = "contingencies"  # Weather backup, rest days, alternatives
    FULL_EXPANSION = "full_expansion"  # Complete detailed itinerary (legacy Stage 2)


class StrategyTier(str, Enum):
    """Output tier for strategy responses, controlling max_tokens."""

    OUTLINE = "outline"  # 512 tokens - Stage 1 shortlist + skeleton
    SECTION = "section"  # 768 tokens - Single section expansion
    FULL = "full"  # 2048 tokens - Complete expansion (user must explicitly request)


# Map tiers to max_tokens
STRATEGY_TIER_MAX_TOKENS = {
    StrategyTier.OUTLINE: 512,
    StrategyTier.SECTION: 768,
    StrategyTier.FULL: 2048,
}


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
    "high_confidence_fired": 0,  # HIGH_CONFIDENCE gate
    "keyword_heuristic_fired": 0,  # KEYWORD_HEURISTIC gate
    "question_keyword_fired": 0,  # Phase 6: Question-word + keyword combo gate
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

# Mapping from keywords to (intent_name, strategy_topic)
# strategy_topic is only set for strategy-related keywords
_KEYWORD_TO_INTENT: dict[str, tuple[str, str | None]] = {
    # Hotel keywords
    "hotel": ("hotels", None),
    "hotels": ("hotels", None),
    "accommodation": ("hotels", None),
    "accommodations": ("hotels", None),
    "stay": ("hotels", None),
    "lodging": ("hotels", None),
    "hostel": ("hotels", None),
    "airbnb": ("hotels", None),
    "booking": ("hotels", None),
    # Hotel preference keywords (route to hotels for settings updates)
    "star": ("hotels", None),
    "breakfast": ("hotels", None),
    "amenities": ("hotels", None),
    "gym": ("hotels", None),
    "pool": ("hotels", None),
    "spa": ("hotels", None),
    # Flight keywords
    "flight": ("flights", None),
    "flights": ("flights", None),
    "fly": ("flights", None),
    "flying": ("flights", None),
    "plane": ("flights", None),
    "airplane": ("flights", None),
    "airline": ("flights", None),
    "airport": ("flights", None),
    # Flight preference keywords (route to flights for settings updates)
    "direct": ("flights", None),
    "nonstop": ("flights", None),
    "business class": ("flights", None),
    "first class": ("flights", None),
    "economy class": ("flights", None),
    "cabin class": ("flights", None),
    "layover": ("flights", None),
    "one-way": ("flights", None),
    "round-trip": ("flights", None),
    # Transport keywords
    "transport": ("transport", None),
    "transportation": ("transport", None),
    "train": ("transport", None),
    "bus": ("transport", None),
    "taxi": ("transport", None),
    "uber": ("transport", None),
    "rental car": ("transport", None),
    "car rental": ("transport", None),
    "ferry": ("transport", None),
    # Activity keywords
    "activity": ("activities", None),
    "activities": ("activities", None),
    "things to do": ("activities", None),
    "attractions": ("activities", None),
    "sightseeing": ("activities", None),
    "tour": ("activities", None),
    "tours": ("activities", None),
    "museum": ("activities", None),
    "restaurant": ("activities", None),
    "restaurants": ("activities", None),
    # Strategy keywords (with topics)
    "hiking": ("strategy", "hiking"),
    "hike": ("strategy", "hiking"),
    "trek": ("strategy", "hiking"),
    "trekking": ("strategy", "hiking"),
    "trail": ("strategy", "hiking"),
    "mountain": ("strategy", "hiking"),
    "diving": ("strategy", "diving"),
    "scuba": ("strategy", "diving"),
    "snorkeling": ("strategy", "diving"),
    "underwater": ("strategy", "diving"),
    "skiing": ("strategy", "skiing"),
    "ski": ("strategy", "skiing"),
    "snowboard": ("strategy", "skiing"),
    "snowboarding": ("strategy", "skiing"),
    "slopes": ("strategy", "skiing"),
    "cycling": ("strategy", "cycling"),
    "bike": ("strategy", "cycling"),
    "biking": ("strategy", "cycling"),
    "bicycle": ("strategy", "cycling"),
    "boating": ("strategy", "boating"),
    "boat": ("strategy", "boating"),
    "sailing": ("strategy", "boating"),
    "yacht": ("strategy", "boating"),
    "kayak": ("strategy", "boating"),
    "kayaking": ("strategy", "boating"),
}

# Keywords that are ambiguous and should NOT trigger keyword bypass
# (user might mean something else, defer to router LLM)
_AMBIGUOUS_KEYWORDS = frozenset(
    {
        "book",  # Could be hotel booking or "read a book"
        "trip",  # General planning, not specific
        "travel",  # General planning
        "vacation",  # General planning
        "help",  # General assistance
        "plan",  # General planning
        "itinerary",  # General planning
    }
)

# Negation patterns that should cause keyword bypass to defer to router LLM
# Example: "I don't want a hotel" should NOT route to hotels specialist
_NEGATION_PATTERNS = frozenset(
    {
        "don't",
        "dont",
        "do not",
        "no ",
        "not ",
        "skip",
        "without",
        "avoid",
        "don't need",
        "dont need",
        "don't want",
        "dont want",
        "not interested",
        "cancel",
    }
)

# Positive intent patterns that strengthen keyword bypass confidence
# When positive intent + domain keyword detected, bypass router with high confidence
# Example: "I want to find a hotel" → positive intent + hotel = strong bypass
_POSITIVE_INTENT_PATTERNS = frozenset(
    {
        "i want",
        "i need",
        "i'd like",
        "i would like",
        "looking for",
        "find me",
        "find a",
        "search for",
        "show me",
        "get me",
        "can you find",
        "can you show",
        "help me find",
        "recommend",
        "suggest",
        # Phase 5 additions for higher bypass rate
        "compare",
        "options for",
        "recommend me",
        "itinerary for",
        "road trip",
        "multi-city",
        "multi city",
        "plan a",
        "planning a",
        "book a",
        "arrange",
    }
)


def _has_positive_intent(text: str) -> Optional[str]:
    """
    Check if text contains a positive intent pattern.

    Args:
        text: Lowercase user text

    Returns:
        The matched pattern if found, None otherwise
    """
    for pattern in _POSITIVE_INTENT_PATTERNS:
        if pattern in text:
            return pattern
    return None


def _is_keyword_negated(text: str, keyword: str, window: int = 20) -> bool:
    """
    Check if a keyword is negated in the text.

    Looks for negation patterns within `window` characters before the keyword.
    Examples:
        "I don't want a hotel" + "hotel" → True (negated)
        "I want a hotel" + "hotel" → False (not negated)
        "no flights please" + "flight" → True (negated)

    Args:
        text: Lowercase user text
        keyword: The keyword to check for negation
        window: Number of characters before keyword to search for negation

    Returns:
        True if keyword appears to be negated, False otherwise
    """
    keyword_pos = text.find(keyword)
    if keyword_pos == -1:
        return False

    # Get the window of text before the keyword
    start_pos = max(0, keyword_pos - window)
    prefix = text[start_pos:keyword_pos]

    # Check for any negation pattern in the prefix
    for neg in _NEGATION_PATTERNS:
        if neg in prefix:
            return True

    return False


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
        "hotels": {"hotel", "hotels", "accommodation", "stay", "lodging", "hostel", "airbnb"},
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
    question_keyword_result = GateEvaluator._check_question_keyword_combo(text_lower)
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
# LLM RESPONSE CACHING (TTLCache)
# =============================================================================
# Cache LLM responses for common patterns to reduce API calls and latency.
# Uses in-memory TTLCache - suitable for single-instance deployments.

# Cache configuration via settings
_RESPONSE_CACHE_TTL = settings.response_cache_ttl_seconds
_RESPONSE_CACHE_MAXSIZE = settings.response_cache_maxsize

# Response cache for LLM responses
_follow_up_cache: TTLCache = TTLCache(maxsize=_RESPONSE_CACHE_MAXSIZE, ttl=_RESPONSE_CACHE_TTL)

# =============================================================================
# EXTRACTOR CACHE (Turn-level caching with hit tracking)
# =============================================================================
# Cache extractor LLM results for identical inputs within a session.
# Short TTL (60s) since extraction context changes frequently.
# Key: (session_id, user_text_hash, core_fields_hash)

_EXTRACTOR_CACHE_TTL = settings.extractor_cache_ttl_seconds
_EXTRACTOR_CACHE_MAXSIZE = settings.extractor_cache_maxsize

# Extractor result cache
_extractor_cache: TTLCache = TTLCache(maxsize=_EXTRACTOR_CACHE_MAXSIZE, ttl=_EXTRACTOR_CACHE_TTL)

# Hit rate tracking for observability
_extractor_cache_stats = {"hits": 0, "misses": 0}


def _compute_extractor_cache_key(
    session_id: str,
    user_text: str,
    core_fields_hash: str,
    extractor_mode: str,
) -> str:
    """
    Compute cache key for extractor LLM results.

    Args:
        session_id: The session ID (conversation ID)
        user_text: The user's input text
        core_fields_hash: Hash of core trip fields (dest, origin, date)
        extractor_mode: "light" or "full"

    Returns:
        MD5 hash string for cache lookup
    """
    # Hash user text for stability
    text_hash = hashlib.md5(user_text.encode()).hexdigest()[:16]
    key_parts = f"extractor|{session_id}|{text_hash}|{core_fields_hash}|{extractor_mode}"
    return hashlib.md5(key_parts.encode()).hexdigest()


def _get_extractor_cached(
    session_id: str,
    user_text: str,
    core_fields_hash: str,
    extractor_mode: str,
    state: Optional["GraphState"] = None,
) -> Optional[Dict[str, Any]]:
    """
    Try to get cached extractor result.

    Returns:
        Cached extraction dict or None if not cached.
        On hit, also increments hit counter and state cache_hits.
    """
    key = _compute_extractor_cache_key(session_id, user_text, core_fields_hash, extractor_mode)
    result = _extractor_cache.get(key)

    if result is not None:
        _extractor_cache_stats["hits"] += 1
        _debug_cache_hit("extractor_cache", key[:16])
        if state is not None:
            _increment_cache_hits(state)
            state.metadata["extractor_cache_hit"] = True
        return result

    _extractor_cache_stats["misses"] += 1
    return None


def _set_extractor_cached(
    session_id: str,
    user_text: str,
    core_fields_hash: str,
    extractor_mode: str,
    result: Dict[str, Any],
) -> None:
    """Cache an extractor LLM result."""
    key = _compute_extractor_cache_key(session_id, user_text, core_fields_hash, extractor_mode)
    _extractor_cache[key] = result


def get_extractor_cache_stats() -> Dict[str, Any]:
    """
    Get extractor cache hit rate statistics.

    Returns:
        Dict with hits, misses, hit_rate, and cache_size
    """
    hits = _extractor_cache_stats["hits"]
    misses = _extractor_cache_stats["misses"]
    total = hits + misses
    hit_rate = hits / total if total > 0 else 0.0

    return {
        "hits": hits,
        "misses": misses,
        "hit_rate": hit_rate,
        "cache_size": len(_extractor_cache),
        "max_size": _EXTRACTOR_CACHE_MAXSIZE,
        "ttl_seconds": _EXTRACTOR_CACHE_TTL,
    }


# =============================================================================
# STRATEGY CACHE (5-min TTL, topic-keyed)
# =============================================================================
# Cache strategy node LLM results for repeated queries about same topic.
# Key: (session_id, topic, core_fields_hash, user_text_hash)
# Longer TTL since strategy advice is more stable than extraction.

_STRATEGY_CACHE_TTL = settings.strategy_cache_ttl_seconds
_STRATEGY_CACHE_MAXSIZE = settings.strategy_cache_maxsize

# Strategy result cache
_strategy_cache: TTLCache = TTLCache(maxsize=_STRATEGY_CACHE_MAXSIZE, ttl=_STRATEGY_CACHE_TTL)

# Hit rate tracking
_strategy_cache_stats = {"hits": 0, "misses": 0}


def _compute_strategy_cache_key(
    session_id: str,
    topic: str,
    core_fields_hash: str,
    user_text_hash: str,
    section_id: Optional[str] = None,
) -> str:
    """
    Compute cache key for strategy LLM results.

    Args:
        session_id: The session ID (conversation ID)
        topic: The strategy topic (hiking, diving, etc.)
        core_fields_hash: Hash of core trip fields
        user_text_hash: Hash of user text
        section_id: Optional expansion section (day_details, routes, etc.)

    Returns:
        MD5 hash string for cache lookup
    """
    section_part = section_id or "stage1"
    key_parts = f"strategy|{session_id}|{topic}|{section_part}|{core_fields_hash}|{user_text_hash}"
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
    Try to get cached strategy result.

    Returns:
        Cached strategy response dict or None if not cached.
    """
    key = _compute_strategy_cache_key(
        session_id, topic, core_fields_hash, user_text_hash, section_id
    )
    result = _strategy_cache.get(key)

    if result is not None:
        _strategy_cache_stats["hits"] += 1
        _debug_cache_hit("strategy_cache", key[:16])
        if state is not None:
            _increment_cache_hits(state)
            state.metadata["strategy_cache_hit"] = True
        return result

    _strategy_cache_stats["misses"] += 1
    return None


def _set_strategy_cached(
    session_id: str,
    topic: str,
    core_fields_hash: str,
    user_text_hash: str,
    result: Dict[str, Any],
    section_id: Optional[str] = None,
) -> None:
    """Cache a strategy LLM result."""
    key = _compute_strategy_cache_key(
        session_id, topic, core_fields_hash, user_text_hash, section_id
    )
    _strategy_cache[key] = result


def get_strategy_cache_stats() -> Dict[str, Any]:
    """
    Get strategy cache hit rate statistics.

    Returns:
        Dict with hits, misses, hit_rate, and cache_size
    """
    hits = _strategy_cache_stats["hits"]
    misses = _strategy_cache_stats["misses"]
    total = hits + misses
    hit_rate = hits / total if total > 0 else 0.0

    return {
        "hits": hits,
        "misses": misses,
        "hit_rate": hit_rate,
        "cache_size": len(_strategy_cache),
        "max_size": _STRATEGY_CACHE_MAXSIZE,
        "ttl_seconds": _STRATEGY_CACHE_TTL,
    }


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

    # Reset cache hit counters
    _extractor_cache_stats["hits"] = 0
    _extractor_cache_stats["misses"] = 0
    _strategy_cache_stats["hits"] = 0
    _strategy_cache_stats["misses"] = 0


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
            "has_end_date": trip_inputs.end_date is not None,
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
    """
    if normalize:
        normalized = _normalize_user_text_for_cache(text)
        # Track cache normalization for observability
        if normalized == "[CONFIRM]":
            _router_stats["cache_normalization_hits"] += 1
        return hashlib.md5((normalized[:100] + str(len(normalized))).encode()).hexdigest()
    return hashlib.md5((text[:100] + str(len(text))).encode()).hexdigest()


def _get_cached_response(
    cache: TTLCache, key: str, state: Optional["GraphState"] = None
) -> Optional[Dict[str, Any]]:
    """Try to get a cached response. Increments cache hit counter if state provided."""
    result = cache.get(key)
    if result is not None:
        _debug_cache_hit("response_cache", key[:16])
        if state is not None:
            _increment_cache_hits(state)
    return result


def _set_cached_response(cache: TTLCache, key: str, response: Dict[str, Any]) -> None:
    """Cache an LLM response."""
    cache[key] = response


def clear_response_caches() -> int:
    """
    Clear all LLM response caches.

    Returns the number of entries that were cleared.
    """
    count = len(_follow_up_cache)
    _follow_up_cache.clear()

    # Also clear extractor cache
    extractor_count = len(_extractor_cache)
    _extractor_cache.clear()

    # Reset extractor cache stats
    _extractor_cache_stats["hits"] = 0
    _extractor_cache_stats["misses"] = 0

    # Also clear strategy cache
    strategy_count = len(_strategy_cache)
    _strategy_cache.clear()

    # Reset strategy cache stats
    _strategy_cache_stats["hits"] = 0
    _strategy_cache_stats["misses"] = 0

    total = count + extractor_count + strategy_count
    _debug(
        (
            "Cleared response caches: "
            f"{total} entries (follow_up: {count}, extractor: {extractor_count}, "
            f"strategy: {strategy_count})"
        )
    )
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
    """Return a snapshot of response cache sizes."""
    return {
        "follow_up": len(_follow_up_cache),
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
        _ = _GREETING_PATTERN.pattern
        _ = _YES_PATTERN.pattern if "_YES_PATTERN" in dir() else None
        _ = _NO_PATTERN.pattern if "_NO_PATTERN" in dir() else None
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

# Regex pattern to strip ANSI escape codes (color, bold, etc.)
# Handles both ESC (\x1b) and CSI (\x9b) control sequences
_ANSI_ESCAPE_PATTERN = re.compile(r"(\x1b|\x9b)\[[0-9;:]*[A-Za-z]")


def _strip_ansi_codes(text: str) -> str:
    """Strip ANSI escape codes from a string."""
    return _ANSI_ESCAPE_PATTERN.sub("", text)


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

    if not question_target or not suggested_responses:
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

    # Check if suggestions match the target
    target_lower = question_target.lower()

    if target_lower == "dates":
        # Suggestions should be date-like
        mismatches = [s for s in suggested_responses if is_place_like(s) and not is_date_like(s)]
        if mismatches:
            _suggestion_contract_stats["violations"] += 1
            _suggestion_contract_stats["rewrites"] += 1
            _debug(
                "suggestion_contract_violation",
                node=node_name,
                target=question_target,
                mismatches=mismatches[:3],
            )
            if state:
                state.metadata["suggestion_contract_violation"] = {
                    "node": node_name,
                    "target": question_target,
                    "suggestions_preview": suggested_responses[:3],
                }
            # Rewrite with date suggestions
            return ["Next month", "This summer", "I'm flexible on dates"]

    elif target_lower in ("destinations", "origin"):
        # Suggestions should be place-like
        mismatches = [s for s in suggested_responses if is_date_like(s) and not is_place_like(s)]
        if mismatches:
            _suggestion_contract_stats["violations"] += 1
            _suggestion_contract_stats["rewrites"] += 1
            _debug(
                "suggestion_contract_violation",
                node=node_name,
                target=question_target,
                mismatches=mismatches[:3],
            )
            if state:
                state.metadata["suggestion_contract_violation"] = {
                    "node": node_name,
                    "target": question_target,
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
        return str(hash(str(value)))[:8]


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
# Patterns are pre-compiled for efficiency
USER_INTENT_ARCHETYPES = {
    "quick_booking": {
        "priority": 1,
        "patterns": [
            re.compile(
                r"\b(just\s+flights?|book\s+now|asap|fastest|quick\s+book|just\s+need)\b", re.I
            ),
            re.compile(r"\b(hurry|urgent|immediately|right\s+away)\b", re.I),
        ],
        "description": "Streamlined, minimal questions, skip optional fields",
    },
    "short_trip": {
        "priority": 2,
        "patterns": [
            re.compile(
                r"\b(weekend|quick\s+trip|2-3\s+days|getaway|short\s+trip|day\s+trip)\b", re.I
            ),
            re.compile(r"\b(mini\s+vacation|long\s+weekend|brief\s+visit)\b", re.I),
        ],
        "description": "Focus on essentials, suggest compact itineraries",
    },
    "adventurous": {
        "priority": 3,
        "patterns": [
            re.compile(
                r"\b(explore|off\s+the?\s+beaten\s+path|unique|adventure|hidden\s+gems?)\b", re.I
            ),
            re.compile(r"\b(authentic|local\s+experience|undiscovered|unusual)\b", re.I),
        ],
        "description": "Proactive tips, suggest hidden gems, enthusiastic tone",
    },
    "undecided": {
        "priority": 4,
        "patterns": [
            re.compile(
                r"\b(not\s+sure|help\s+me|suggestions?|ideas?|recommend|where\s+should)\b", re.I
            ),
            re.compile(r"\b(can\'t\s+decide|options?|what\s+do\s+you\s+think)\b", re.I),
        ],
        "description": "Curated options, gentle guidance, offer comparisons",
    },
    "detailed_planner": {
        "priority": 5,
        "patterns": [],  # Default fallback - no specific patterns
        "description": "Thorough questions, structured approach, all categories",
    },
}

# User tone detection patterns (for response adaptation)
# Patterns are pre-compiled for efficiency
USER_TONE_PATTERNS = {
    "enthusiastic": {
        "patterns": [
            re.compile(r"!{2,}", re.I),  # Multiple exclamation marks
            re.compile(r"\b(can\'t\s+wait|so\s+excited|amazing|awesome|love\s+it|perfect)\b", re.I),
            re.compile(r"\b(yay|woohoo|fantastic|incredible|thrilled)\b", re.I),
        ],
    },
    "frustrated": {
        "patterns": [
            re.compile(r"\b(ugh|again\??|still|already\s+told|not\s+working)\b", re.I),
            re.compile(r"\b(confused|frustrat|annoying|wrong|doesn\'t\s+work)\b", re.I),
        ],
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

    # Intent-specific tone instructions (condensed from former _adapt_tone.txt)
    _INTENT_INSTRUCTIONS = {
        "quick_booking": "Be brief but friendly. Keep responses short and efficient.",
        "detailed_planner": "Be helpful with details. Provide context when useful.",
        "adventurous": "Match their energy! Use emojis sparingly. Be enthusiastic.",
        "undecided": "Be a helpful guide. Suggest options gently.",
        "short_trip": "Acknowledge time constraints. Focus on efficiency.",
    }

    # Tone modifiers (appended to intent instruction)
    _TONE_MODIFIERS = {
        "frustrated": " Be calm, direct, and helpful. No fluff.",
        "enthusiastic": " Mirror their excitement!",
        "neutral": "",  # No modifier needed
        "curious": " Be informative and engaging.",
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
            user_intent, "Be warm and professional. Keep it conversational."
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
        "flights": ["Direct flights only", "Flexible dates", "Budget airlines OK"],
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
            "flights": ["Arrive day before", "Flexible dates", "Marina proximity"],
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
            "default": ["Paris, France", "Tokyo, Japan", "Barcelona, Spain"],
            "hiking": ["Swiss Alps", "Patagonia", "Nepal"],
            "skiing": ["Chamonix", "Whistler", "Niseko"],
            "diving": ["Maldives", "Red Sea", "Great Barrier Reef"],
            "boating": ["Greek Islands", "Croatia", "Caribbean"],
            "cycling": ["Tuscany", "Netherlands", "Loire Valley"],
        },
        "origin": ["London", "New York", "Los Angeles"],
        "dates": ["Next month", "March 15-22", "First week of summer"],
        "travelers": ["Just me", "2 adults", "Family of 4"],
        "budget": ["Around $2000", "Flexible budget", "Budget-friendly"],
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
        "max_tokens": 128,  # Minimal output for core fields only
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
        "max_tokens": 256,  # Phase 5: Reduced from 512; fallback never uses full 512
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
        "max_tokens": 2048,  # Deep planning needs more space (used for stage 2)
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
        "max_tokens": 2048,  # Stage 2: full detailed itinerary
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

# Pattern: Greetings (hi, hello, hey, good morning, etc.)
_GREETING_PATTERN = re.compile(
    r"^(h(i|ey|ello|iya|owdy)|yo|sup|good\s+(morning|afternoon|evening|day)|"
    r"what'?s\s+up|greetings?)[\s\.\!\?]*$",
    re.IGNORECASE,
)

# Pattern: Simple confirmations (yes, yeah, yep, yup)
_YES_PATTERN = re.compile(
    r"^(yes|yeah|yep|yup|yea|ya|sure|ok(ay)?|alright|all\s+right|"
    r"sounds?\s+good|absolutely|definitely|of\s+course|please|do\s+it|go\s+ahead|"
    r"let'?s\s+do\s+(it|this|that)|ok(ay)?\s+go\s+ahead)[\s\.\!\?]*$",
    re.IGNORECASE,
)

# Pattern: Simple negations (no, nope, nah, not really)
_NO_PATTERN = re.compile(
    r"^(no|nope|nah|not\s+really|no\s+thanks?|never\s*mind|cancel|"
    r"don'?t|stop|wait|hold\s+on)[\s\.\!\?]*$",
    re.IGNORECASE,
)

# Friendly greeting responses (randomized for variety)
_GREETING_RESPONSES = [
    "Hi! 👋 Where are you looking to travel?",
    "Hello! What destination is calling your name?",
    "Hey! Ready to plan a trip. Where to?",
    "Hi there! Where would you like to go?",
]

# Off-topic deflection responses (used when router detects non-travel queries)
_OFF_TOPIC_DEFLECTIONS = [
    "I'm here to help with travel planning! Where would you like to go?",
    "That's outside my expertise—but I'd love to help plan your next trip! 🌍",
    "I specialize in travel! Got a destination in mind?",
    "I'm your travel assistant! Tell me where you'd like to explore.",
    "That's not quite my area, but I'm great at planning adventures! Where to?",
]


# =============================================================================
# EXTRACTOR MODE SELECTION (Light vs Full)
# =============================================================================
# Light extraction (~128 tokens) is used for early turns with simple input.
# Full extraction (~512 tokens) is used for dense input or when nearing ready_to_generate.

# Keywords indicating dense input requiring full extraction
# Topic keywords - used for routing/strategy detection, NOT for triggering FULL extraction mode
# These are intents/themes, not concrete booking preferences
_TOPIC_KEYWORDS = frozenset(
    [
        # Strategy/activity topics
        "hiking",
        "diving",
        "skiing",
        "cycling",
        "boating",
        "snorkeling",
        "surfing",
        "climbing",
        "trekking",
        "safari",
        "cruise",
        # Trip style/intent
        "adventure",
        "relaxation",
        "beach",
        "mountain",
        "city break",
        "road trip",
        "honeymoon",
        "backpacking",
        "luxury",
        "budget-friendly",
    ]
)

# Settings keywords - concrete booking preferences that require FULL extraction mode
# These indicate the user is specifying detailed preferences
_DENSE_INPUT_KEYWORDS = frozenset(
    [
        # Flight settings
        "direct",
        "nonstop",
        "non-stop",
        "business",
        "first class",
        "economy",
        "one-way",
        "round-trip",
        "round trip",
        "layover",
        "stopover",
        "cabin",
        # Hotel settings
        "star",
        "stars",
        "boutique",
        "resort",
        "hostel",
        "airbnb",
        "pool",
        "spa",
        "gym",
        "amenities",
        "breakfast",
        "wifi",
        "parking",
        # Transport settings
        "car rental",
        "rent a car",
        "train",
        "bus",
        "ferry",
        "taxi",
        "uber",
        "transfer",
        # Generic activity keywords (not strategy topics)
        "tour",
        "museum",
    ]
)

# Patterns indicating complex/dense input
_COMMA_LIST_PATTERN = re.compile(r",\s*(?:and\s+)?[A-Z][a-z]+", re.IGNORECASE)
_MULTI_DESTINATION_PATTERN = re.compile(r"\b(?:and|then|also|plus)\s+[A-Z][a-z]+", re.IGNORECASE)


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
    settings_matches = [kw for kw in _DENSE_INPUT_KEYWORDS if kw in text_lower]
    topic_matches = [kw for kw in _TOPIC_KEYWORDS if kw in text_lower]

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
    has_comma_list = comma_count >= 2 and _COMMA_LIST_PATTERN.search(text)
    multi_dest_matches = _MULTI_DESTINATION_PATTERN.findall(text)
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

# Relative date patterns for deterministic parsing
_RELATIVE_DATE_PATTERNS = {
    "next_month": re.compile(r"^next\s+month$", re.IGNORECASE),
    "this_month": re.compile(r"^this\s+month$", re.IGNORECASE),
    "next_week": re.compile(r"^next\s+week$", re.IGNORECASE),
    "this_weekend": re.compile(r"^this\s+weekend$", re.IGNORECASE),
    "next_weekend": re.compile(r"^next\s+weekend$", re.IGNORECASE),
}

# Season patterns
_SEASON_PATTERN = re.compile(
    r"^(?:this\s+|next\s+)?(spring|summer|fall|autumn|winter)(?:\s+\d{4})?$", re.IGNORECASE
)

# Travelers patterns for micro-parser
_TRAVELERS_MICRO_PATTERNS = {
    "solo": re.compile(
        r"^(?:solo|just\s+me|only\s+me|me|myself|alone|by\s+myself)$", re.IGNORECASE
    ),
    "couple": re.compile(
        r"^(?:couple|2\s+of\s+us|two\s+of\s+us|me\s+and\s+(?:my\s+)?(?:partner|spouse|wife|husband|boyfriend|girlfriend))$",
        re.IGNORECASE,
    ),
    "family": re.compile(r"^family\s+of\s+(\d+)$", re.IGNORECASE),
    "group": re.compile(r"^(\d+)\s*(?:people|adults?|travelers?|of\s+us)$", re.IGNORECASE),
}

# Multi-place separators
_PLACE_SEPARATORS = re.compile(r"\s*(?:,|/|\band\b|&|\+)\s*", re.IGNORECASE)

# Verb patterns that indicate a sentence (not a place list)
_SENTENCE_VERB_PATTERN = re.compile(
    r"\b(want|go|plan|visit|travel|explore|see|book|need|would|could|should|will|can|am|is|are)\b",
    re.IGNORECASE,
)

# Greeting words blocklist for title-case heuristic
_GREETING_BLOCKLIST = frozenset(
    {
        "hello",
        "hi",
        "hey",
        "thanks",
        "thank",
        "please",
        "yes",
        "no",
        "ok",
        "okay",
        "sure",
        "great",
        "perfect",
        "awesome",
        "cool",
        "nice",
        "good",
        "fine",
    }
)


def _normalize_suggestion_text(text: str) -> str:
    """Normalize text for suggestion matching: trim, collapse spaces, casefold."""
    return " ".join(text.split()).casefold()


def _try_suggestion_echo(
    text: str,
    state: "GraphState",
) -> Optional[Dict[str, Any]]:
    """
    Try to match user text against last_suggestions.

    Returns LQA-shaped delta dict if match found, None otherwise.
    First tries raw exact match, then normalized match.

    v5 Lifecycle: Only matches if question_id matches, preventing stale echo.
    """
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
                iso_date = _date_normalizer.normalize(sugg_text)
                if iso_date:
                    delta["start_date_delta"] = iso_date
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
    for pattern_name, pattern in _RELATIVE_DATE_PATTERNS.items():
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

    # Check season pattern
    season_match = _SEASON_PATTERN.match(text_stripped)
    if season_match:
        season = season_match.group(1).lower()
        if season in _SEASON_TO_DATE_RANGE:
            start_month, start_day, end_month, end_day = _SEASON_TO_DATE_RANGE[season]

            # Determine year: "next" prefix or season in past
            is_next = "next" in text_lower
            year = today.year

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
    if _TRAVELERS_MICRO_PATTERNS["solo"].match(text_stripped):
        _deterministic_parse_stats["travelers_hits"] += 1
        return {"adults_delta": 1, "lqa_reason": "deterministic:travelers_answer"}

    # Couple patterns
    if _TRAVELERS_MICRO_PATTERNS["couple"].match(text_stripped):
        _deterministic_parse_stats["travelers_hits"] += 1
        return {"adults_delta": 2, "lqa_reason": "deterministic:travelers_answer"}

    # Family of N
    family_match = _TRAVELERS_MICRO_PATTERNS["family"].match(text_stripped)
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
    group_match = _TRAVELERS_MICRO_PATTERNS["group"].match(text_stripped)
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
        origin_match = _ORIGIN_PREFIX_PATTERN.match(text_stripped)
        if origin_match:
            text_stripped = origin_match.group(2).strip()

    text_lower = text_stripped.lower()

    # Don't parse if it contains verbs (likely a sentence, not place list)
    if _SENTENCE_VERB_PATTERN.search(text_stripped):
        return None

    # Check greeting blocklist for title-case false positives
    if text_lower in _GREETING_BLOCKLIST:
        return None

    # Try multi-place split first if separator present
    if _PLACE_SEPARATORS.search(text_stripped):
        segments = _PLACE_SEPARATORS.split(text_stripped)
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
        if word_lower not in _GREETING_BLOCKLIST and word_lower not in _MONTH_NAMES:
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

    Top-level guard: Only runs if question_target is set OR last_suggestions non-empty.

    Returns LQA-shaped delta dict on hit, None on miss.
    On hit, also sets metadata for conditional question_target advancement.
    """
    question_target = canonicalize_question_target(
        state.question_target or state.metadata.get("last_question_field")
    )
    last_suggestions = state.metadata.get("last_suggestions", [])

    # Top-level guard: only run if we have context
    if not question_target and not last_suggestions:
        return None

    text_stripped = text.strip()
    if not text_stripped:
        return None

    # 1. Suggestion echo (highest priority - user clicked a suggestion)
    result = _try_suggestion_echo(text, state)
    if result:
        return result

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

    # 3. Travelers parser (if question_target is travelers)
    if question_target == "travelers":
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
    # Initialize counters/trackers if needed
    if "llm_calls_this_turn" not in state.metadata:
        state.metadata["llm_calls_this_turn"] = 0
    if "llm_nodes_called_this_turn" not in state.metadata:
        state.metadata["llm_nodes_called_this_turn"] = []
    if "llm_call_blocked_reason" not in state.metadata:
        state.metadata["llm_call_blocked_reason"] = {}
    if "llm_call_blocked_count" not in state.metadata:
        state.metadata["llm_call_blocked_count"] = {}

    # Check if we're in core collection mode
    readiness = compute_trip_readiness(state.trip_inputs)
    question_target = state.question_target or state.metadata.get("last_question_field")

    # If ready or no question_target, no cap
    if readiness.ready_to_generate or not question_target:
        # Still track but don't enforce cap
        state.metadata["llm_calls_this_turn"] += 1
        state.metadata["llm_nodes_called_this_turn"].append(node_name)
        return True

    current_calls = state.metadata["llm_calls_this_turn"]
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
        state.metadata["llm_call_blocked_reason"][node_name] = "budget_exhausted"
        # Track blocked count per node for observability
        blocked_counts = state.metadata["llm_call_blocked_count"]
        blocked_counts[node_name] = blocked_counts.get(node_name, 0) + 1
        return False

    # Increment before call (never decrement on error)
    state.metadata["llm_calls_this_turn"] += 1
    state.metadata["llm_nodes_called_this_turn"].append(node_name)
    _debug(
        "LLM call allowed",
        node=node_name,
        call_number=state.metadata["llm_calls_this_turn"],
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
            "destinations": "Where would you like to go?",
            "dates": "When would you like to travel?",
            "travelers": "How many people are traveling?",
            "origin": "Where will you be traveling from?",
            "budget": "What's your budget for this trip?",
        }
        question = fallback_questions.get(target, "What else can I help you with?")
        suggestions = []

    # Mutate state with fallback response
    state.last_summary = question
    state.suggested_responses = suggestions if suggestions else []
    state.question_target = target

    # Set provenance for polish skip
    set_response_provenance(state, "template")
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
# RESPONSE PROVENANCE TRACKING
# =============================================================================
# Single-source-of-truth for how a response was generated.
# Set in exactly one place per response path.


def set_response_provenance(state: "GraphState", provenance: str) -> None:
    """
    Set the response provenance for polish skip decisions.

    Valid values:
    - "template": Template-generated response
    - "deterministic": Deterministic code path (no LLM)
    - "codegen": Code-generated structured response
    - "llm": LLM-generated response

    Should be called exactly once per response, at the point of generation.
    """
    state.metadata["response_provenance"] = provenance


def get_response_provenance(state: "GraphState") -> Optional[str]:
    """Get the response provenance if set."""
    return state.metadata.get("response_provenance")


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
        state.metadata["response_provenance"] = provenance
        _debug(
            "Response source set",
            node=node_name,
            provenance=provenance,
        )


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

    if not updates:
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


# Bail patterns: Multi-intent or correction signals that need full extraction
_LQA_BAIL_PATTERNS = [
    re.compile(r"\b(also|and\s+book|plus|as\s+well)\b", re.IGNORECASE),  # Multi-intent
    re.compile(r"[,;].*[,;]", re.IGNORECASE),  # Multiple delimiters
    re.compile(r"\b(not|instead|change|actually|but)\b", re.IGNORECASE),  # Negation/correction
]

# Pattern to strip leading articles from destinations ("the Netherlands" -> "Netherlands")
_ARTICLE_PREFIX = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)


def _parse_destination_answer(text: str, state: "GraphState") -> Optional[Dict[str, Any]]:
    """Parse a destination answer. Returns parsed dict or None."""
    # First check if the raw text is a known place
    if is_known_place(text):
        # If so, normalize it for consistency
        normalized = normalize_place_synonym(text)
        return {"destinations_delta": [normalized]}
    # Also try the normalized version (in case synonym maps to different casing)
    normalized = normalize_place_synonym(text)
    if is_known_place(normalized):
        return {"destinations_delta": [normalized]}

    # Strip leading articles ("the Netherlands" -> "Netherlands")
    stripped = _ARTICLE_PREFIX.sub("", text).strip()
    if stripped != text:
        if is_known_place(stripped):
            normalized = normalize_place_synonym(stripped)
            return {"destinations_delta": [normalized]}
        normalized = normalize_place_synonym(stripped)
        if is_known_place(normalized):
            return {"destinations_delta": [normalized]}

    return None


def _parse_origin_answer(text: str, state: "GraphState") -> Optional[Dict[str, Any]]:
    """Parse an origin answer, handling 'from X' prefix. Returns parsed dict or None."""
    # Try with "from" prefix first
    origin_match = _ORIGIN_PREFIX_PATTERN.match(text)
    if origin_match:
        origin_text = origin_match.group(2).strip()
    else:
        origin_text = text

    # First check if the raw text is a known place
    if is_known_place(origin_text):
        # If so, normalize it for consistency
        normalized = normalize_place_synonym(origin_text)
        return {"origin_delta": normalized}
    # Also try the normalized version (in case synonym maps to different casing)
    normalized = normalize_place_synonym(origin_text)
    if is_known_place(normalized):
        return {"origin_delta": normalized}
    return None


# =============================================================================
# DATE-LIKE TOKEN DETECTION (for LQA skip heuristic)
# =============================================================================
# Patterns to detect if text is likely a date vs a destination/location.
# Used to skip LQA date parsing on non-date-like strings like "Swiss Alps".

# Month name patterns (for date detection)
_MONTH_NAMES = frozenset(
    {
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
        "december",
        "jan",
        "feb",
        "mar",
        "apr",
        "jun",
        "jul",
        "aug",
        "sep",
        "sept",
        "oct",
        "nov",
        "dec",
    }
)

# Relative date keywords
_RELATIVE_DATE_WORDS = frozenset(
    {
        "today",
        "tomorrow",
        "next",
        "this",
        "weekend",
        "week",
        "month",
        "year",
        "morning",
        "evening",
        "afternoon",
        "night",
    }
)

# Year clarification patterns (for dates_clarify responses)
_YEAR_CLARIFY_PATTERNS = [
    re.compile(
        r"this\s+(december|january|february|march|april|may|june|july|august|september|october|november)",
        re.IGNORECASE,
    ),
    re.compile(
        r"next\s+(december|january|february|march|april|may|june|july|august|september|october|november|year)",
        re.IGNORECASE,
    ),
    re.compile(r"(20\d{2})", re.IGNORECASE),  # Explicit year like "2025" or "2026"
    re.compile(r"this\s+year", re.IGNORECASE),
    re.compile(r"next\s+year", re.IGNORECASE),
]


def _is_date_like_text(text: str) -> bool:
    """
    Check if text looks like it could be a date answer.

    Returns True if the text contains date-like tokens (digits, month names,
    relative date words). Returns False for location-like text (capitalized
    proper nouns without date indicators).

    This is used to skip LQA date parsing on clearly non-date text like
    "Swiss Alps" when question_target is "dates".
    """
    text_lower = text.lower().strip()

    # Has digits? Likely a date (Dec 20, 2025, etc.)
    if re.search(r"\d", text):
        return True

    # Contains month name?
    words = set(re.findall(r"[a-z]+", text_lower))
    if words & _MONTH_NAMES:
        return True

    # Contains relative date words?
    if words & _RELATIVE_DATE_WORDS:
        return True

    # No date-like tokens found
    return False


def _is_place_like_text(text: str) -> bool:
    """
    Check if text looks like a place/destination name.

    Returns True for text that appears to be a location rather than a date.
    Used to skip LQA date parsing.
    """
    # Check if it's a known place
    if is_known_place(text):
        return True

    # Check for capitalized words (proper nouns suggesting places)
    # But exclude single common words
    words = text.split()
    if len(words) >= 1:
        capitalized_words = [w for w in words if w[0].isupper() and len(w) > 1]
        # Multiple capitalized words or a known place pattern
        if len(capitalized_words) >= 2:
            return True
        # Single capitalized word that's not a month
        if len(capitalized_words) == 1:
            word_lower = capitalized_words[0].lower()
            if word_lower not in _MONTH_NAMES and word_lower not in _RELATIVE_DATE_WORDS:
                return True

    return False


def _parse_date_answer(text: str, state: "GraphState") -> Optional[Dict[str, Any]]:
    """
    Parse a date answer. Returns parsed dict or None.

    Extended to handle year clarification responses like:
    - "This December", "Next December"
    - "This year", "Next year"
    - Explicit years like "2025", "2026"
    """
    text_stripped = text.strip()

    # First, check for year clarification patterns
    for pattern in _YEAR_CLARIFY_PATTERNS:
        if pattern.search(text_stripped):
            # Get reference date from state if available
            metadata = state.metadata or {}
            today_iso = metadata.get("today_iso")
            if today_iso:
                try:
                    reference_date = datetime.strptime(today_iso, "%Y-%m-%d").date()
                except ValueError:
                    reference_date = datetime.now(UTC).date()
            else:
                reference_date = datetime.now(UTC).date()

            text_lower = text_stripped.lower()

            # Handle "this year" / "next year"
            if "this year" in text_lower:
                # Use the pending date range with current year
                pending_dates = metadata.get("pending_date_range", {})
                if pending_dates:
                    year = reference_date.year
                    start = pending_dates.get("start_date", "").replace(
                        pending_dates.get("start_date", "")[:4], str(year)
                    )
                    end = pending_dates.get("end_date", "").replace(
                        pending_dates.get("end_date", "")[:4], str(year)
                    )
                    if start and end:
                        return {"start_date_hint": start, "end_date_hint": end}
                return None

            if "next year" in text_lower:
                pending_dates = metadata.get("pending_date_range", {})
                if pending_dates:
                    year = reference_date.year + 1
                    start = pending_dates.get("start_date", "")
                    end = pending_dates.get("end_date", "")
                    if start and end:
                        start = f"{year}-{start[5:]}"
                        end = f"{year}-{end[5:]}"
                        return {"start_date_hint": start, "end_date_hint": end}
                return None

            # Handle "this December" / "next December"
            this_match = re.search(r"this\s+(\w+)", text_lower)
            if this_match:
                month_name = this_match.group(1)
                if month_name in _MONTH_NAMES:
                    year = reference_date.year
                    pending_dates = metadata.get("pending_date_range", {})
                    if pending_dates:
                        start = pending_dates.get("start_date", "")
                        end = pending_dates.get("end_date", "")
                        if start and end:
                            start = f"{year}-{start[5:]}"
                            end = f"{year}-{end[5:]}"
                            return {"start_date_hint": start, "end_date_hint": end}

            next_match = re.search(r"next\s+(\w+)", text_lower)
            if next_match:
                month_name = next_match.group(1)
                if month_name in _MONTH_NAMES or month_name == "year":
                    year = reference_date.year + 1
                    pending_dates = metadata.get("pending_date_range", {})
                    if pending_dates:
                        start = pending_dates.get("start_date", "")
                        end = pending_dates.get("end_date", "")
                        if start and end:
                            start = f"{year}-{start[5:]}"
                            end = f"{year}-{end[5:]}"
                            return {"start_date_hint": start, "end_date_hint": end}

            # Handle explicit year like "2026"
            year_match = re.search(r"(20\d{2})", text_stripped)
            if year_match:
                year = int(year_match.group(1))
                pending_dates = metadata.get("pending_date_range", {})
                if pending_dates:
                    start = pending_dates.get("start_date", "")
                    end = pending_dates.get("end_date", "")
                    if start and end:
                        start = f"{year}-{start[5:]}"
                        end = f"{year}-{end[5:]}"
                        return {"start_date_hint": start, "end_date_hint": end}

    # Try parsing as a date range first (e.g., "first week of January", "December 20-27")
    range_start, range_end = _date_normalizer.parse_date_range(text_stripped)
    if range_start and range_end:
        return {"start_date_hint": range_start, "end_date_hint": range_end}

    # Standard single date parsing
    iso_date = _date_normalizer.normalize(text_stripped)
    if iso_date:
        return {"start_date_hint": iso_date}
    return None


def _parse_travelers_answer(text: str, state: "GraphState") -> Optional[Dict[str, Any]]:
    """Parse a travelers answer. Returns parsed dict or None."""
    # Check for adults + kids pattern first (e.g., "2 adults and 2 kids")
    kids_match = _TRAVELERS_WITH_KIDS_PATTERN.match(text)
    if kids_match:
        adults = int(kids_match.group(1))
        children = int(kids_match.group(2))
        return {"adults_delta": adults, "children_delta": children}

    travelers_match = _TRAVELERS_PATTERN.match(text)
    if travelers_match:
        # Extract number of adults
        if "just" in text.lower() or "solo" in text.lower() or text.lower() in ("me", "myself"):
            adults = 1
        elif "couple" in text.lower():
            adults = 2
        elif travelers_match.group(1):  # "2 adults", "3 people"
            adults = int(travelers_match.group(1))
        elif travelers_match.group(3):  # "family of 4"
            adults = int(travelers_match.group(3))
        elif travelers_match.group(4):  # "4 of us"
            adults = int(travelers_match.group(4))
        else:
            adults = 1  # Default
        return {"adults_delta": adults}
    return None


def _parse_budget_answer(text: str, state: "GraphState") -> Optional[Dict[str, Any]]:
    """Parse a budget answer. Returns parsed dict or None."""
    budget_match = _BUDGET_PATTERN.match(text)
    if budget_match:
        amount_str = budget_match.group(1)
        # Handle "k" suffix (e.g., "2k" -> 2000)
        if amount_str.lower().endswith("k"):
            amount = float(amount_str[:-1]) * 1000
        # Handle "thousand" word (e.g., "5 thousand" -> 5000)
        elif "thousand" in amount_str.lower():
            amount = float(amount_str.lower().replace("thousand", "").strip()) * 1000
        else:
            # Remove commas and convert
            amount = float(amount_str.replace(",", ""))
        return {"budget_delta": amount}
    return None


def _parse_duration_answer(text: str, state: "GraphState") -> Optional[Dict[str, Any]]:
    """Parse a duration answer. Returns parsed dict or None."""
    duration_match = _DURATION_PATTERN.match(text)
    if duration_match:
        # Parse the number (could be word or digit)
        num_str = duration_match.group(1).lower()
        if num_str in _WORD_TO_NUMBER:
            num = _WORD_TO_NUMBER[num_str]
        else:
            num = int(num_str)

        unit = duration_match.group(2).lower()
        # Convert to days
        if "week" in unit:
            days = num * 7
        else:
            days = num  # days or nights treated the same

        return {"duration_days": days}
    return None


# Mapping from question_target to parser function
_LQA_FIELD_PARSERS: Dict[str, Callable[[str, "GraphState"], Optional[Dict[str, Any]]]] = {
    "destinations": _parse_destination_answer,
    "origin": _parse_origin_answer,
    "dates": _parse_date_answer,
    "start_date": _parse_date_answer,
    "end_date": _parse_date_answer,
    "travelers": _parse_travelers_answer,
    "budget": _parse_budget_answer,
    "duration": _parse_duration_answer,
}


def lqa_prepass(state: "GraphState") -> "GraphState":
    """
    LQA (Last Question Answer) pre-pass node.

    Runs BEFORE extractor to deterministically parse simple answers to the
    last question asked. If successful, sets parsed_inputs and flags so
    extractor can be skipped entirely.

    Bail conditions (falls through to extractor):
    - pending_action is set (short-circuit should handle)
    - No question_target/last_question_field set
    - Input exceeds lqa_max_length
    - Multi-intent or negation patterns detected
    - Field validation fails

    Returns:
        Updated state with flags["lqa_prepass"] = True/False
    """
    _debug_node_entry("lqa_prepass", state)
    _lqa_stats["attempts"] += 1

    text = (state.user_text or "").strip()

    # -------------------------------------------------------------------------
    # BAIL 1: Pending action (defer to short-circuit handling in extractor)
    # -------------------------------------------------------------------------
    pending_action = state.metadata.get("pending_action")
    if pending_action:
        _lqa_stats["bails"] += 1
        _lqa_stats["bail_pending_action"] += 1
        state.flags["lqa_prepass"] = False
        state.flags["lqa_bail_reason"] = "pending_action"
        _debug("[LQA] BAIL: pending_action set", action=pending_action)
        _debug_node_exit("lqa_prepass", state)
        return state

    # -------------------------------------------------------------------------
    # BAIL 2: No question_target (can't know what field to parse)
    # -------------------------------------------------------------------------
    raw_question_target = state.question_target or state.metadata.get("last_question_field")
    if not raw_question_target:
        _lqa_stats["bails"] += 1
        _lqa_stats["bail_no_question_target"] += 1
        state.flags["lqa_prepass"] = False
        state.flags["lqa_bail_reason"] = "no_question_target"
        _debug("[LQA] BAIL: no question_target set")
        _debug_node_exit("lqa_prepass", state)
        return state

    # Canonicalize question_target before parsing
    question_target = canonicalize_question_target(raw_question_target)

    # -------------------------------------------------------------------------
    # NOT DATE-LIKE BAIL: When asking for dates but text looks like a place
    # -------------------------------------------------------------------------
    # Per test_lqa_skips_place_when_target_is_dates: when user gives a place
    # name (like "Swiss Alps") but we asked for dates, bail with "not_date_like"
    # and let the system re-ask for dates.
    if question_target == "dates":
        if not _is_date_like_text(text) and _is_place_like_text(text):
            _lqa_stats["bails"] += 1
            _date_stats["lqa_skip_not_date_like"] += 1
            state.flags["lqa_prepass"] = False
            state.flags["lqa_bail_reason"] = "not_date_like"
            _debug(
                "[LQA] SKIP: text is place-like, asked for dates",
                target=question_target,
                text=text[:30],
            )
            _debug_node_exit("lqa_prepass", state)
            return state

    # -------------------------------------------------------------------------
    # BAIL 3: Input too long
    # -------------------------------------------------------------------------
    if len(text) > settings.lqa_max_length:
        _lqa_stats["bails"] += 1
        _lqa_stats["bail_too_long"] += 1
        state.flags["lqa_prepass"] = False
        state.flags["lqa_bail_reason"] = "too_long"
        _debug(
            "[LQA] BAIL: input too long",
            length=len(text),
            max=settings.lqa_max_length,
        )
        _debug_node_exit("lqa_prepass", state)
        return state

    # -------------------------------------------------------------------------
    # BAIL 4: Multi-intent or negation patterns
    # -------------------------------------------------------------------------
    for i, pattern in enumerate(_LQA_BAIL_PATTERNS):
        if pattern.search(text):
            bail_types = ["multi_intent", "multi_intent", "negation"]
            bail_type = bail_types[i] if i < len(bail_types) else "multi_intent"
            _lqa_stats["bails"] += 1
            _lqa_stats[f"bail_{bail_type}"] += 1
            state.flags["lqa_prepass"] = False
            state.flags["lqa_bail_reason"] = bail_type
            _debug(
                f"[LQA] BAIL: {bail_type} pattern detected",
                pattern_idx=i,
                text=text[:30],
            )
            _debug_node_exit("lqa_prepass", state)
            return state

    # -------------------------------------------------------------------------
    # MVP OPTIMIZATION: DETERMINISTIC PIPELINE (runs before LQA parsers)
    # -------------------------------------------------------------------------
    # This is the highest-impact token saver. It handles:
    # - Suggestion echo: exact-match to last_suggestions
    # - Season/month dates: "next summer", "December"
    # - Travelers: "solo", "couple", "family of 4"
    # - Multi-place: "Paris and Rome"
    # - Single place (known): "Patagonia"
    #
    # On hit, returns LQA-shaped delta dict and skips extractor entirely.
    det_result = _run_deterministic_pipeline(text, state)
    if det_result:
        lqa_reason = det_result.get("lqa_reason", "deterministic:unknown")

        # Handle date ambiguity: don't set dates, trigger clarify mode
        if det_result.get("_date_clarify_mode"):
            state.flags["lqa_prepass"] = False
            state.flags["lqa_bail_reason"] = lqa_reason
            state.metadata["date_clarify_mode"] = True
            state.metadata["pending_date_text"] = det_result.get("_pending_date_text")
            set_response_provenance(state, "deterministic")
            _debug(
                "[LQA] DETERMINISTIC: date ambiguous, triggering clarify mode",
                pending_text=det_result.get("_pending_date_text"),
            )
            _debug_node_exit("lqa_prepass", state)
            return state

        # Build parsed_inputs from delta dict (keep delta format for compatibility)
        parsed = {}
        if "destinations_delta" in det_result:
            parsed["destinations_delta"] = det_result["destinations_delta"]
        if "origin_delta" in det_result:
            parsed["origin_delta"] = det_result["origin_delta"]
        if "start_date_delta" in det_result:
            parsed["start_date_hint"] = det_result["start_date_delta"]
        if "end_date_delta" in det_result:
            parsed["end_date_hint"] = det_result["end_date_delta"]
        if "adults_delta" in det_result:
            parsed["adults_delta"] = det_result["adults_delta"]
        if "children_delta" in det_result:
            parsed["children_delta"] = det_result["children_delta"]

        if parsed:
            _lqa_stats["hits"] += 1
            _lqa_stats["deterministic_pipeline_hits"] = (
                _lqa_stats.get("deterministic_pipeline_hits", 0) + 1
            )
            state.flags["lqa_prepass"] = True
            state.flags["lqa_field"] = lqa_reason.replace("deterministic:", "")
            state.parsed_inputs = parsed
            set_response_provenance(state, "deterministic")

            # Determine if we should advance question_target
            keep_target = det_result.get("_keep_question_target", False)
            if not keep_target:
                state.question_target = None

            # Set high confidence for deterministic parsing
            state.metadata["extraction_confidence"] = {
                "overall": 0.98,
                "level": "high",
                "method": lqa_reason,
                "grammar_matched": True,
                "is_english": True,
                "detected_language": None,
                "low_confidence_reasons": [],
                "typo_suggestions": {},
            }
            state.metadata["extraction_path"] = lqa_reason

            # Record multi-city signal if present
            if det_result.get("_multi_city_signal"):
                state.metadata["multi_city_signal"] = True

            _debug(
                "[LQA] DETERMINISTIC: pipeline hit",
                reason=lqa_reason,
                parsed=parsed,
                text=text[:30],
                tokens_saved="~500 (extractor_light avoided)",
            )
            _debug_node_exit("lqa_prepass", state)
            return state

    # -------------------------------------------------------------------------
    # BAIL 5: No parser for this question_target
    # -------------------------------------------------------------------------
    parser = _LQA_FIELD_PARSERS.get(question_target)
    if not parser:
        _lqa_stats["bails"] += 1
        _lqa_stats["bail_validation_fail"] += 1
        state.flags["lqa_prepass"] = False
        state.flags["lqa_bail_reason"] = "unhandled_field"
        _debug("[LQA] BAIL: no parser for question_target", target=question_target)
        _debug_node_exit("lqa_prepass", state)
        return state

    # -------------------------------------------------------------------------
    # ATTEMPT PARSING
    # -------------------------------------------------------------------------
    parsed = parser(text, state)
    if parsed is None:
        _lqa_stats["bails"] += 1
        _lqa_stats["bail_validation_fail"] += 1
        state.flags["lqa_prepass"] = False
        state.flags["lqa_bail_reason"] = "validation_fail"
        _debug(
            "[LQA] BAIL: validation failed",
            target=question_target,
            text=text[:30],
        )
        _debug_node_exit("lqa_prepass", state)
        return state

    # -------------------------------------------------------------------------
    # RESTRICT FIELD UPDATES DURING DATE CLARIFY MODE
    # -------------------------------------------------------------------------
    # When question_target is "dates", only allow updates to date-related fields.
    # This prevents mixed answers like "Next year in Zermatt" from polluting
    # destination/origin state while in date clarification mode.
    if question_target == "dates":
        allowed_keys = {
            "start_date_hint",
            "end_date_hint",
            "start_date",
            "end_date",
            "date_precision",
        }
        filtered_parsed = {k: v for k, v in parsed.items() if k in allowed_keys}
        if len(filtered_parsed) != len(parsed):
            _debug(
                "[LQA] Filtered non-date fields during dates clarify",
                original_keys=list(parsed.keys()),
                filtered_keys=list(filtered_parsed.keys()),
            )
            parsed = filtered_parsed

        # If nothing left after filtering, bail
        if not parsed:
            _lqa_stats["bails"] += 1
            state.flags["lqa_prepass"] = False
            state.flags["lqa_bail_reason"] = "no_date_fields_after_filter"
            _debug("[LQA] BAIL: no date fields after filter")
            _debug_node_exit("lqa_prepass", state)
            return state

    # -------------------------------------------------------------------------
    # SUCCESS: Set parsed_inputs and flags
    # -------------------------------------------------------------------------
    _lqa_stats["hits"] += 1
    state.flags["lqa_prepass"] = True
    state.flags["lqa_field"] = question_target
    state.parsed_inputs = parsed

    # Clear question_target after successfully answering it, so required_fields
    # will ask about the next missing field instead of repeating the same question
    state.question_target = None

    # Set high confidence since we matched deterministically
    state.metadata["extraction_confidence"] = {
        "overall": 0.95,
        "level": "high",
        "method": "lqa_prepass",
        "grammar_matched": True,
        "is_english": True,
        "detected_language": None,
        "low_confidence_reasons": [],
        "typo_suggestions": {},
    }

    # Record path trace for metrics
    state.metadata["extraction_path"] = f"lqa:{question_target}"

    _debug(
        "[LQA] HIT: parsed successfully",
        target=question_target,
        parsed=parsed,
        text=text[:30],
    )
    _debug_node_exit("lqa_prepass", state)
    return state


# =============================================================================
# FAST-PATH EXTRACTOR PATTERNS (Token-saving short-circuits)
# =============================================================================
# These patterns enable bypassing the LLM extractor when the user provides
# a simple, unambiguous answer to a specific question (question_target).
#
# REQUIREMENTS for fast-path triggering (ALL must be true):
# 1. question_target is set (system just asked for a specific field)
# 2. len(text) < 30 (short answer, likely direct response)
# 3. Matches strict regex for field type
# 4. No sentence-ending punctuation that suggests a sentence (!?.)

# Maximum length for fast-path consideration
_FAST_PATH_MAX_LENGTH = 30

# Pattern: Sentence-ending punctuation (reject these - likely sentences)
_SENTENCE_ENDING_PATTERN = re.compile(r"[!?]\s*$")

# Pattern: Origin prefix (e.g., "from London", "leaving from NYC")
_ORIGIN_PREFIX_PATTERN = re.compile(
    r"^(from|leaving\s+from|departing\s+from|flying\s+from|starting\s+from)\s+(.+)$",
    re.IGNORECASE,
)

# Pattern: Travelers (e.g., "2 adults", "just me", "3 people", "family of 4", "a couple")
_TRAVELERS_PATTERN = re.compile(
    r"^(?:just\s+me|only\s+me|me|myself|solo|"
    r"a?\s*couple|"
    r"(\d+)\s*(adult|person|people|guest|traveler|pax)s?|"
    r"(?:family\s+of|group\s+of)\s+(\d+)|"
    r"(\d+)\s*(?:of\s+us|traveling))$",
    re.IGNORECASE,
)

# Pattern: Inline travelers within sentences (for initial extraction)
# Matches: "I am traveling solo", "solo trip", "just me going", "two of us", "my partner and I"
_INLINE_TRAVELERS_PATTERN = re.compile(
    r"(?:^|[\s,])(?:"
    # Solo indicators
    r"(?:i'?m\s+)?(?:traveling\s+)?(?:solo|alone|by\s+myself)|"
    r"solo\s+(?:trip|travel|vacation)|"
    r"just\s+(?:me|myself)(?:\s+going|\s+traveling)?|"
    r"on\s+my\s+own|"
    # Couple indicators
    r"(?:my\s+)?(?:partner|spouse|husband|wife|boyfriend|girlfriend)\s+and\s+(?:i|me)|"
    r"(?:i|me)\s+and\s+my\s+(?:partner|spouse|husband|wife|boyfriend|girlfriend)|"
    r"(?:the\s+)?two\s+of\s+us|"
    r"just\s+(?:the\s+)?two\s+(?:of\s+us)?|"
    r"as\s+a\s+couple|"
    # Family with numbers
    r"(?:family\s+of|group\s+of|party\s+of)\s+(\d+)|"
    r"(\d+)\s+(?:of\s+us|people|adults?|travelers?)(?:\s+(?:are|will))?|"
    # Explicit counts
    r"(?:there\s+(?:are|will\s+be)\s+)?(\d+)\s+of\s+us" r")(?:[\s,.]|$)",
    re.IGNORECASE,
)

# Pattern: Family composition (e.g., "family of 4", "with 2 kids", "me and my 2 children")
# Returns total count and optional children count
_FAMILY_COMPOSITION_PATTERN = re.compile(
    r"(?:"
    # "family of N" / "family with N members"
    r"family\s+(?:of|with)\s+(\d+)(?:\s+(?:people|members))?|"
    # "N adults and N kids/children"
    r"(\d+)\s*adults?\s*(?:and|with|&|\+)\s*(\d+)\s*(?:kids?|children|child)|"
    # "me and my N kids" / "myself and N children"
    r"(?:me|myself|i)\s+(?:and\s+)?(?:my\s+)?(\d+)\s*(?:kids?|children|child)|"
    # "with N kids/children" / "have N kids with us" / "we have N kids"
    r"(?:with|have)\s+(\d+|two|three|four)\s*(?:kids?|children|child)(?:\s+with\s+us)?|"
    # "N kids with us"
    r"(\d+|two|three|four)\s*(?:kids?|children|child)\s+with\s+us|"
    # "traveling with kids/children" (implies children, count unknown) - GROUP 6
    r"((?:traveling|going)\s+with\s+(?:the\s+)?(?:kids?|children))|"
    # "for the kids" / "our kids" / "the kids" (implies children) - GROUP 7
    r"((?:for|with|and)\s+(?:the|our|my)\s+(?:kids?|children))|"
    # "family trip" / "family vacation" (implies children likely) - GROUP 8
    r"(family\s+(?:trip|vacation|holiday|getaway))" r")",
    re.IGNORECASE,
)

# Pattern: Inline budget mentions (e.g., "budget of $2000", "with a $3000 budget",
# "spending around 5k")
_INLINE_BUDGET_PATTERN = re.compile(
    (
        r"(?:"  # inline budget patterns
        r"budget\s+(?:of|is|around|about|roughly)?\s*(?:\$|€|£)?"
        r"(\d+(?:,\d{3})*(?:\.\d{2})?|\d+k)\s*(?:\$|€|£|dollars?|euros?|pounds?)?|"
        r"(?:with\s+(?:a\s+)?)?(?:\$|€|£)"
        r"(\d+(?:,\d{3})*(?:\.\d{2})?|\d+k)\s*(?:budget|max|maximum)|"
        # "around/about $X" in context of budget
        r"(?:around|about|roughly|approximately)\s*(?:\$|€|£)"
        r"(\d+(?:,\d{3})*(?:\.\d{2})?|\d+k)|"
        # "spending/spend $X" / "spend around $X"
        r"(?:spend(?:ing)?|invest(?:ing)?)\s*(?:around|about|roughly)?\s*(?:\$|€|£)?"
        r"(\d+(?:,\d{3})*(?:\.\d{2})?|\d+k)|"
        # "under $X" / "less than $X" / "keep it/the total/everything under $X" / "max $X"
        r"(?:under|less\s+than|no\s+more\s+than|max(?:imum)?|"
        r"keep\s+(?:it|everything|the\s+total|the\s+budget|things|costs?)?\s*under|"
        r"hoping\s+to\s+keep\s+(?:it|the\s+total|everything|things)?\s*under)"
        r"\s*(?:\$|€|£)?(\d+(?:,\d{3})*(?:\.\d{2})?|\d+k)|"
        # Simple "$X" or "$X for the trip/total" - standalone currency amounts
        r"(?:\$|€|£)(\d+(?:,\d{3})*)\s*(?:for\s+(?:the\s+)?"
        r"(?:trip|total|everything|whole|entire)|total)?|"
        # "X dollars/euros" without context
        r"(\d+(?:,\d{3})*)\s*(?:dollars?|euros?|pounds?)"
        r")"
    ),
    re.IGNORECASE,
)

# Pattern: Travelers with children (e.g., "2 adults and 2 kids")
_TRAVELERS_WITH_KIDS_PATTERN = re.compile(
    r"^(\d+)\s*adults?\s*(?:and|with|&|\+)\s*(\d+)\s*(?:kids?|children|child)$",
    re.IGNORECASE,
)

# Phase 5: Pattern for budget (e.g., "$2000", "2k", "5 thousand", "around 3000 euros")
_BUDGET_PATTERN = re.compile(
    (
        r"^(?:around|about|approximately|roughly|~)?\s*"  # Optional prefix
        r"(?:\$|€|£|USD|EUR|GBP|CAD|AUD)?\s*"  # Optional currency symbol/code before
        r"(\d+(?:,\d{3})*(?:\.\d{2})?|\d+k|\d+\s*thousand)"  # Amount
        r"\s*(?:\$|€|£|USD|EUR|GBP|CAD|AUD|dollars|euros|pounds)?"  # Optional currency after
        r"(?:\s*(?:budget|total|max|maximum))?$"  # Optional suffix
    ),
    re.IGNORECASE,
)

# Phase 5: Pattern for duration (e.g., "7 days", "one week", "10 nights", "2 weeks")
_DURATION_PATTERN = re.compile(
    r"^(?:(?:for\s+)?(\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
    r"\s*(day|days|night|nights|week|weeks))"
    r"(?:\s*(?:trip|vacation|holiday))?$",
    re.IGNORECASE,
)

# Word-to-number mapping for duration parsing
_WORD_TO_NUMBER = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


# NOTE: _debug_fast_path_decision and _try_fast_path_extraction have been removed.
# Their functionality is now handled by the lqa_prepass node which runs BEFORE
# extractor, providing better token savings by skipping extractor entirely.
# The shared field parsing logic is now in _LQA_FIELD_PARSERS and individual
# _parse_*_answer() functions above.


# =============================================================================
# PHASE 6: ZERO-LLM INITIAL MESSAGE EXTRACTION
# =============================================================================
# Handle simple initial messages like "I want to go to Paris" or
# "2 adults, Paris, next month" without LLM even when question_target is not set.
# This extends fast-path to work on first turn, saving ~1145 tokens.

# Pattern: "I want to go to X", "trip to X", "visit X", "travel to X"
_INITIAL_DESTINATION_PATTERN = re.compile(
    r"(?:i\s+want\s+to\s+(?:go\s+to|visit|travel\s+to)|"
    r"(?:trip|vacation|holiday)\s+to|"
    r"planning\s+(?:a\s+)?(?:trip|vacation|holiday)\s+to|"
    r"going\s+to|"
    r"let'?s\s+go\s+to)\s+(.+?)(?:\s+(?:from|next|in|for|with)\b|[.!?,]|$)",
    re.IGNORECASE,
)

# Pattern: "from X to Y" or "X to Y"
_ORIGIN_DESTINATION_PATTERN = re.compile(
    r"(?:from\s+)?(\w+(?:\s+\w+)?)\s+to\s+(\w+(?:\s+\w+)?)",
    re.IGNORECASE,
)

# Pattern: Multi-field simple input like "2 adults, Paris, next month"
# Handles comma-separated values that each match a field pattern
_MULTI_FIELD_PATTERN = re.compile(
    r"^(?:(\d+)\s*(?:adult|people|person|traveler)s?(?:\s*,\s*|\s+and\s+|\s+)?)?"
    r"(\w+(?:\s+\w+)?)?(?:\s*,\s*|\s+)?"
    r"(next\s+(?:week|month)|in\s+\w+|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*(?:\s+\d+)?)?",
    re.IGNORECASE,
)


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
    dest_match = _INITIAL_DESTINATION_PATTERN.search(text_clean)
    if dest_match:
        dest_text = dest_match.group(1).strip()
        normalized = normalize_place_synonym(dest_text)
        if is_known_place(normalized):
            parsed["destinations_delta"] = [normalized]
            fields_extracted.append("destinations")
            _debug(f"[INITIAL_EXTRACT] Pattern 1 matched: destinations={normalized}")

    # Try pattern 2: "from X to Y" or "X to Y"
    if not parsed.get("destinations_delta"):
        origin_dest_match = _ORIGIN_DESTINATION_PATTERN.search(text_clean)
        if origin_dest_match:
            origin_text = origin_dest_match.group(1).strip()
            dest_text = origin_dest_match.group(2).strip()

            origin_norm = normalize_place_synonym(origin_text)
            dest_norm = normalize_place_synonym(dest_text)

            if is_known_place(dest_norm):
                parsed["destinations_delta"] = [dest_norm]
                fields_extracted.append("destinations")
                _debug(f"[INITIAL_EXTRACT] Pattern 2 matched: destinations={dest_norm}")

            if is_known_place(origin_norm) and origin_norm != dest_norm:
                parsed["origin_delta"] = origin_norm
                fields_extracted.append("origin")
                _debug(f"[INITIAL_EXTRACT] Pattern 2 matched: origin={origin_norm}")

    # Try pattern 3: Multi-field comma-separated input
    multi_match = _MULTI_FIELD_PATTERN.match(text_clean)
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
        inline_match = _INLINE_TRAVELERS_PATTERN.search(text_lower)
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
    family_match = _FAMILY_COMPOSITION_PATTERN.search(text_lower)
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
    budget_match = _INLINE_BUDGET_PATTERN.search(text_lower)
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

# Infeasibility patterns that can be detected deterministically
_INFEASIBILITY_SIGNALS: dict[str, re.Pattern] = {
    # Dates in the past (explicit correction language)
    "dates_past": re.compile(
        r"\b(yesterday|last\s+week|last\s+month|already\s+passed|already\s+gone|"
        r"was\s+supposed\s+to|should\s+have\s+been|missed\s+the\s+date)\b",
        re.IGNORECASE,
    ),
    # Skiing in summer (seasonal impossibility)
    "skiing_summer": re.compile(
        r"\bski(ing)?\b.*\b(june|july|august|summer)\b|\b(june|july|august|summer)\b.*\bski(ing)?\b",
        re.IGNORECASE,
    ),
    # Beach in winter for northern destinations
    "beach_winter": re.compile(
        r"\bbeach\b.*\b(december|january|february|winter)\b.*\b(norway|sweden|finland|iceland|alaska|canada)\b|"
        r"\b(norway|sweden|finland|iceland|alaska|canada)\b.*\bbeach\b.*\b(december|january|february|winter)\b",
        re.IGNORECASE,
    ),
    # Beach in landlocked countries (geographic impossibility)
    "beach_landlocked": re.compile(
        r"\bbeach\b.*\b(switzerland|austria|czech|hungary|serbia|slovakia|luxembourg|liechtenstein|"
        r"andorra|vatican|san\s+marino|bolivia|paraguay|mongolia|nepal|bhutan|laos|kazakhstan|"
        r"uzbekistan|turkmenistan|kyrgyzstan|tajikistan|afghanistan|rwanda|burundi|uganda|zambia|"
        r"zimbabwe|botswana|malawi|lesotho|eswatini|ethiopia|chad|niger|mali|burkina\s+faso|"
        r"central\s+african|south\s+sudan)\b|"
        r"\b(switzerland|austria|czech|hungary|serbia|slovakia|luxembourg|liechtenstein|"
        r"andorra|bolivia|paraguay|mongolia|nepal|bhutan)\b.*\bbeach\b",
        re.IGNORECASE,
    ),
    # Impossible same-day intercontinental
    "same_day_impossible": re.compile(
        r"\bsame\s+day\b.*\b(tokyo|sydney|australia|japan|new\s+zealand)\b.*\b(london|paris|new\s+york|europe|america)\b|"
        r"\b(london|paris|new\s+york|europe|america)\b.*\bsame\s+day\b.*\b(tokyo|sydney|australia|japan|new\s+zealand)\b",
        re.IGNORECASE,
    ),
    # Explicit correction language from user
    "explicit_correction": re.compile(
        r"\b(that's\s+wrong|that's\s+incorrect|you\s+made\s+a\s+mistake|"
        r"fix\s+this|correct\s+this|change\s+this|that\s+won't\s+work|"
        r"not\s+possible|impossible|can't\s+do\s+that|won't\s+work)\b",
        re.IGNORECASE,
    ),
}


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
    if _GREETING_PATTERN.match(text_clean):
        _debug_short_circuit_decision(text, "greeting", last_field, "TRIGGERED")
        return {
            "type": "greeting",
            "response": _random_module.choice(_GREETING_RESPONSES),
            "action": None,
            "parsed": None,
        }

    pending = state.metadata.get("pending_action")

    # 2. Pending-action confirmations should be evaluated BEFORE acknowledgments
    # so ambiguous tokens like "sure" or "sounds good" act as a real confirm/deny.
    if pending and _YES_PATTERN.match(text_clean):
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

    if pending and _NO_PATTERN.match(text_clean):
        pending = state.metadata.get("pending_action")
        if pending:
            # Clear the pending action
            _debug_short_circuit_decision(
                text, "confirmation_no", last_field, "TRIGGERED", reason=f"pending={pending}"
            )
            return {
                "type": "confirmation_no",
                "response": "No problem. What would you like to do instead?",
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
    if _YES_PATTERN.match(text_clean):
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
    if _NO_PATTERN.match(text_clean):
        pending = state.metadata.get("pending_action")
        if pending:
            # Clear the pending action
            return {
                "type": "confirmation_no",
                "response": "No problem. What would you like to do instead?",
                "action": "clear_pending",
                "parsed": None,
            }
        return {
            "type": "confirmation_no",
            "response": None,
            "action": None,
            "parsed": None,
        }

    # 6-10. Off-topic, bare inputs - REMOVED: Now handled by LLM for better accuracy
    # Off-topic detection moved to router node with off_topic intent
    # Bare destination/date/travelers/origin detection removed - too brittle

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
    """
    Get today's date in ISO format (YYYY-MM-DD).

    Uses the provided timezone if valid, otherwise falls back to UTC.
    """
    tz = None
    if timezone_name:
        try:
            tz = ZoneInfo(timezone_name)
        except Exception:
            pass  # Invalid timezone, fall back to UTC

    if tz:
        return datetime.now(tz).strftime("%Y-%m-%d")
    return datetime.now(UTC).strftime("%Y-%m-%d")


# =============================================================================
# INPUT NORMALIZATION FUNCTIONS (ported from plan.py)
# =============================================================================

# Regex pattern for ANSI escape codes (terminal colors, formatting)
_ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*m")


def _normalize_str(value: Any) -> Optional[str]:
    """Convert any value to a trimmed string, returning None for empty values.

    Also strips ANSI escape codes that may be present from terminal formatting.
    """
    if value is None:
        return None
    value_str = str(value).strip()
    if not value_str or value_str.lower() == "null":
        return None
    # Strip ANSI escape codes
    value_str = _ANSI_ESCAPE_PATTERN.sub("", value_str)
    return value_str


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
# DATE PROVENANCE (Tracking source and explicit year for date values)
# =============================================================================
@dataclass
class DateProvenance:
    """
    Provenance information for a parsed date value.

    Used to track whether a year was explicit (from user input) or inferred,
    enabling the "explicit year wins" invariant at merge time.

    Attributes:
        value: The ISO date string (YYYY-MM-DD)
        source_turn: Turn number when this date was set (optional)
        explicit_year: True if the year was explicitly provided by user
        parsed_from: How the date was derived ("user_text", "normalized", "inferred")
    """

    value: str
    source_turn: Optional[int] = None
    explicit_year: bool = False
    parsed_from: str = "normalized"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "source_turn": self.source_turn,
            "explicit_year": self.explicit_year,
            "parsed_from": self.parsed_from,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DateProvenance":
        if not data:
            return None
        return cls(
            value=data.get("value", ""),
            source_turn=data.get("source_turn"),
            explicit_year=data.get("explicit_year", False),
            parsed_from=data.get("parsed_from", "normalized"),
        )


# =============================================================================
# DATE NORMALIZER (Consolidated date handling)
# =============================================================================
class DateNormalizer:
    """
    Centralized date normalization logic.

    Consolidates all date parsing, relative date conversion, and validation
    into a single class to eliminate duplication across nodes.

    Usage:
        normalizer = DateNormalizer()
        iso_date = normalizer.normalize("next week")
        iso_date, was_partial = normalizer.normalize_with_info("December 2025")
        end_date = normalizer.compute_end_from_duration("2025-01-01", 7)
        start, end = normalizer.parse_date_range("December 20-27")
    """

    # Pre-compiled patterns (class-level for efficiency)
    _ORDINAL_SUFFIX = re.compile(r"(\d+)(st|nd|rd|th)\b", re.IGNORECASE)
    _PARTIAL_DATE = re.compile(
        r"^(january|february|march|april|may|june|july|august|september|october|november|december"
        r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+(\d{4})$",
        re.IGNORECASE,
    )
    # Month + day without year (e.g., "December 15", "Dec 15")
    _MONTH_DAY_PATTERN = re.compile(
        r"^(january|february|march|april|may|june|july|august|september|october|november|december"
        r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+(\d{1,2})(?:st|nd|rd|th)?$",
        re.IGNORECASE,
    )
    _ISO_FORMAT = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    # Date range patterns: "December 20-27", "Dec 20-27", "20-27 December", etc.
    _DATE_RANGE_PATTERNS = [
        # "December 20-27" or "Dec 20-27" (optionally with year)
        re.compile(
            r"^(january|february|march|april|may|june|july|august|september|october|november|december"
            r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+"
            r"(\d{1,2})(?:st|nd|rd|th)?[-–—to\s]+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?$",
            re.IGNORECASE,
        ),
        # "20-27 December" or "20-27 Dec" (optionally with year)
        re.compile(
            r"^(\d{1,2})(?:st|nd|rd|th)?[-–—to\s]+(\d{1,2})(?:st|nd|rd|th)?\s+"
            r"(january|february|march|april|may|june|july|august|september|october|november|december"
            r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)(?:,?\s*(\d{4}))?$",
            re.IGNORECASE,
        ),
    ]

    # Week of month patterns: "first week of January", "last week of December", etc.
    _WEEK_OF_MONTH_PATTERN = re.compile(
        r"^(first|second|third|fourth|last|1st|2nd|3rd|4th)\s+week\s+(?:of\s+)?"
        r"(january|february|march|april|may|june|july|august|september|october|november|december"
        r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)(?:,?\s*(\d{4}))?$",
        re.IGNORECASE,
    )

    # Mapping from ordinal word to week number (1-indexed)
    _WEEK_ORDINALS = {
        "first": 1,
        "1st": 1,
        "second": 2,
        "2nd": 2,
        "third": 3,
        "3rd": 3,
        "fourth": 4,
        "4th": 4,
        "last": -1,  # Special: last week of month
    }

    # Relative date keywords
    _TODAY_WORDS = frozenset({"today", "tonight", "now"})

    # Pattern to detect explicit 4-digit year in input
    _EXPLICIT_YEAR_PATTERN = re.compile(r"\b(20\d{2}|19\d{2})\b")

    # Supported date formats (ordered by specificity - 4-digit year first)
    _DATE_FORMATS = (
        "%Y-%m-%d",  # 2025-12-28 (ISO)
        "%d-%m-%Y",  # 28-12-2025
        "%d/%m/%Y",  # 28/12/2025
        "%m/%d/%Y",  # 12/28/2025 (US format)
        "%m-%d-%Y",  # 12-28-2025 (US dash format)
        "%B %d, %Y",  # December 28, 2025
        "%b %d, %Y",  # Dec 28, 2025
        "%d %B %Y",  # 28 December 2025
        "%d %b %Y",  # 28 Dec 2025
        "%B %d %Y",  # December 28 2025 (no comma)
        "%b %d %Y",  # Dec 28 2025 (no comma)
        "%d %B, %Y",  # 28 December, 2025
        "%d %b, %Y",  # 28 Dec, 2025
        # 2-digit year formats (less common but still used)
        "%d-%m-%y",  # 28-12-25
        "%d/%m/%y",  # 28/12/25
        "%m/%d/%y",  # 12/28/25 (US format)
        "%m-%d-%y",  # 12-28-25 (US dash format)
    )

    def __init__(self, reference_date: Optional[date] = None):
        """
        Initialize with optional reference date for relative calculations.

        Args:
            reference_date: The "today" date for relative calculations.
                           Defaults to UTC today.
        """
        self._reference = reference_date or datetime.now(UTC).date()

    @property
    def today(self) -> date:
        """Get the reference date used for relative calculations."""
        return self._reference

    def relative_to_iso(self, text: Optional[str]) -> Optional[str]:
        """
        Convert relative date expressions to ISO format.

        Handles: today, tomorrow, next week, next month, weekend, this weekend
        """
        if not text:
            return None

        lowered = text.lower().strip()
        today = self._reference

        if lowered in self._TODAY_WORDS:
            return today.strftime("%Y-%m-%d")

        if lowered == "tomorrow":
            return (today + timedelta(days=1)).strftime("%Y-%m-%d")

        if "next week" in lowered:
            return (today + timedelta(days=7)).strftime("%Y-%m-%d")

        if "next month" in lowered:
            return (today + timedelta(days=30)).strftime("%Y-%m-%d")

        if "weekend" in lowered:
            days_until_saturday = (5 - today.weekday()) % 7
            if "next" in lowered and days_until_saturday <= 0:
                days_until_saturday += 7
            return (today + timedelta(days=days_until_saturday)).strftime("%Y-%m-%d")

        return None

    def normalize_with_info(self, value: Any) -> tuple[Optional[str], bool]:
        """
        Normalize various date formats to ISO format (YYYY-MM-DD).

        Returns:
            Tuple of (iso_date, was_partial) where was_partial indicates
            if the date was a partial date like "December 2025" that defaulted
            to the 1st of the month.
        """
        text = _normalize_str(value)
        if not text:
            return None, False

        # Try relative dates first
        relative = self.relative_to_iso(text)
        if relative:
            return relative, False

        # Strip ordinal suffixes before parsing (28th -> 28)
        text_cleaned = self._ORDINAL_SUFFIX.sub(r"\1", text)

        # Try various date formats
        for fmt in self._DATE_FORMATS:
            try:
                parsed = datetime.strptime(text_cleaned, fmt)
                return parsed.strftime("%Y-%m-%d"), False
            except ValueError:
                continue

        # Check for partial dates (month + year only)
        partial_match = self._PARTIAL_DATE.match(text_cleaned)
        if partial_match:
            month_str = partial_match.group(1)
            year_str = partial_match.group(2)
            for month_fmt in ("%B %d, %Y", "%b %d, %Y"):
                try:
                    parsed = datetime.strptime(f"{month_str} 1, {year_str}", month_fmt)
                    return parsed.strftime("%Y-%m-%d"), True
                except ValueError:
                    continue

        # Check for month + day without year (e.g., "December 15", "Dec 15")
        month_day_match = self._MONTH_DAY_PATTERN.match(text_cleaned)
        if month_day_match:
            month_str = month_day_match.group(1)
            day_str = month_day_match.group(2)
            # Infer year: use current year if date is future, next year if past
            for month_fmt in ("%B %d, %Y", "%b %d, %Y"):
                try:
                    # Try with current year first
                    current_year = self._reference.year
                    parsed = datetime.strptime(f"{month_str} {day_str}, {current_year}", month_fmt)
                    # If date is in the past, use next year
                    if parsed.date() < self._reference:
                        parsed = datetime.strptime(
                            f"{month_str} {day_str}, {current_year + 1}", month_fmt
                        )
                    return parsed.strftime("%Y-%m-%d"), False
                except ValueError:
                    continue

        # Check if already ISO format
        if self._ISO_FORMAT.match(text_cleaned):
            return text_cleaned, False

        return None, False

    def normalize(self, value: Any) -> Optional[str]:
        """Normalize various date formats to ISO format (YYYY-MM-DD)."""
        result, _ = self.normalize_with_info(value)
        return result

    def has_explicit_year(self, text: str) -> bool:
        """
        Check if the input text contains an explicit 4-digit year.

        This is used to determine whether year should be preserved during merges.
        """
        if not text:
            return False
        return bool(self._EXPLICIT_YEAR_PATTERN.search(text))

    def normalize_with_provenance(
        self,
        value: Any,
        source_turn: Optional[int] = None,
    ) -> Optional[DateProvenance]:
        """
        Normalize date and return full provenance information.

        This is the preferred method for date normalization when tracking
        explicit year is important for merge invariants.

        Args:
            value: Raw date string to normalize
            source_turn: Turn number where this date was provided

        Returns:
            DateProvenance with value, explicit_year flag, and source info,
            or None if parsing fails
        """
        text = _normalize_str(value)
        if not text:
            return None

        iso_date, was_partial = self.normalize_with_info(value)
        if not iso_date:
            return None

        # Check if original input had an explicit year
        explicit_year = self.has_explicit_year(text)

        # Determine parsed_from based on how the date was derived
        if was_partial:
            parsed_from = "partial_month"
        elif self.relative_to_iso(text):
            parsed_from = "relative"
        elif self._ISO_FORMAT.match(text.strip()):
            parsed_from = "iso_passthrough"
        else:
            parsed_from = "user_text"

        return DateProvenance(
            value=iso_date,
            source_turn=source_turn,
            explicit_year=explicit_year,
            parsed_from=parsed_from,
        )

    def parse_iso(self, text: Optional[str]) -> Optional[datetime]:
        """Parse an ISO date string to a datetime object."""
        if not text:
            return None
        try:
            return datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            return None

    def find_date_in_text(self, text: str, hint_month: Optional[str] = None) -> Optional[str]:
        """
        Try to find a full date (with day) in freeform user text.

        This is used as a fallback when the LLM extractor returns only month+year
        but the user's original text had a specific day.

        Args:
            text: The user's original input text
            hint_month: Optional month hint from LLM (e.g., "january") to help find the right date

        Returns:
            ISO date string if found, None otherwise
        """
        if not text:
            return None

        text_lower = text.lower()

        # Pattern to find dates like "January 15", "Jan 15", "15 January", "15th of January"
        # followed optionally by year.
        # IMPORTANT: Use negative lookahead (?!\d) to avoid matching "20" from "2025" as a day.
        month_day_patterns = [
            # "January 15, 2026" or "January 15 2026" or "January 15th, 2026"
            # The (?!\d) after (\d{1,2}) ensures we don't match partial year digits as day
            re.compile(
                r"(january|february|march|april|may|june|july|august|september|october|november|december"
                r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+"
                r"(\d{1,2})(?!\d)(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?",
                re.IGNORECASE,
            ),
            # "15 January 2026" or "15th of January 2026"
            re.compile(
                r"(\d{1,2})(?!\d)(?:st|nd|rd|th)?(?:\s+of)?\s+"
                r"(january|february|march|april|may|june|july|august|september|october|november|december"
                r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)(?:,?\s+(\d{4}))?",
                re.IGNORECASE,
            ),
        ]

        for pattern in month_day_patterns:
            matches = list(pattern.finditer(text_lower))
            for match in matches:
                groups = match.groups()

                # Determine month, day, and year from match
                if groups[0].isdigit():
                    # Pattern 2: day, month, year
                    day_str = groups[0]
                    month_str = groups[1]
                    year_str = groups[2] if len(groups) > 2 else None
                else:
                    # Pattern 1: month, day, year
                    month_str = groups[0]
                    day_str = groups[1]
                    year_str = groups[2] if len(groups) > 2 else None

                # If we have a hint_month, only match dates with that month
                if hint_month:
                    hint_month_lower = hint_month.lower()[:3]
                    if not month_str.lower().startswith(hint_month_lower):
                        continue

                # Parse month
                try:
                    month_dt = datetime.strptime(month_str[:3], "%b")
                    month_num = month_dt.month
                except ValueError:
                    continue

                # Parse day
                try:
                    day_num = int(day_str)
                    if day_num < 1 or day_num > 31:
                        continue
                except ValueError:
                    continue

                # Determine year
                if year_str:
                    year = int(year_str)
                else:
                    # Use current year, or next year if month is past
                    today = self._reference
                    year = today.year
                    if month_num < today.month or (
                        month_num == today.month and day_num < today.day
                    ):
                        year += 1

                # Build and validate the date
                try:
                    iso_date = f"{year:04d}-{month_num:02d}-{day_num:02d}"
                    datetime.strptime(iso_date, "%Y-%m-%d")  # Validate
                    return iso_date
                except ValueError:
                    continue

        return None

    def parse_date_range(self, value: Any) -> tuple[Optional[str], Optional[str]]:
        """
        Parse a date range expression into start and end dates.

        Handles formats like:
        - "December 20-27" → ("2025-12-20", "2025-12-27")
        - "Dec 20-27" → ("2025-12-20", "2025-12-27")
        - "December 20-27, 2025" → ("2025-12-20", "2025-12-27")
        - "20-27 December" → ("2025-12-20", "2025-12-27")

        If no year is specified, uses current year (or next year if month is past).

        Returns:
            Tuple of (start_date_iso, end_date_iso), or (None, None) if not a range.
        """
        text = _normalize_str(value)
        if not text:
            return None, None

        text_clean = text.strip()

        for pattern in self._DATE_RANGE_PATTERNS:
            match = pattern.match(text_clean)
            if match:
                groups = match.groups()

                # Pattern 1: "December 20-27" → (month, start_day, end_day, year?)
                # Pattern 2: "20-27 December" → (start_day, end_day, month, year?)
                if groups[0].isdigit():
                    # Pattern 2: start_day, end_day, month, year
                    start_day = int(groups[0])
                    end_day = int(groups[1])
                    month_str = groups[2]
                    year_str = groups[3] if len(groups) > 3 else None
                else:
                    # Pattern 1: month, start_day, end_day, year
                    month_str = groups[0]
                    start_day = int(groups[1])
                    end_day = int(groups[2])
                    year_str = groups[3] if len(groups) > 3 else None

                # Parse month name to number
                try:
                    month_dt = datetime.strptime(month_str[:3], "%b")
                    month_num = month_dt.month
                except ValueError:
                    continue

                # Determine year
                if year_str:
                    year = int(year_str)
                else:
                    # Use current year, or next year if month is in the past
                    today = self._reference
                    year = today.year
                    if month_num < today.month or (
                        month_num == today.month and end_day < today.day
                    ):
                        year += 1

                # Build ISO dates
                try:
                    start_iso = f"{year:04d}-{month_num:02d}-{start_day:02d}"
                    end_iso = f"{year:04d}-{month_num:02d}-{end_day:02d}"

                    # Validate dates are real
                    datetime.strptime(start_iso, "%Y-%m-%d")
                    datetime.strptime(end_iso, "%Y-%m-%d")

                    return start_iso, end_iso
                except ValueError:
                    # Invalid day for month
                    continue

        # Check for "first/second/third/fourth/last week of [month]" pattern
        week_match = self._WEEK_OF_MONTH_PATTERN.match(text_clean)
        if week_match:
            ordinal_str = week_match.group(1).lower()
            month_str = week_match.group(2)
            year_str = week_match.group(3) if len(week_match.groups()) > 2 else None

            # Get week number from ordinal
            week_num = self._WEEK_ORDINALS.get(ordinal_str)
            if week_num is None:
                return None, None

            # Parse month name to number
            try:
                month_dt = datetime.strptime(month_str[:3], "%b")
                month_num = month_dt.month
            except ValueError:
                return None, None

            # Determine year
            if year_str:
                year = int(year_str)
            else:
                # Use current year, or next year if month is in the past
                today = self._reference
                year = today.year
                if month_num < today.month:
                    year += 1

            # Calculate last day of month
            if month_num == 12:
                last_of_month = date(year + 1, 1, 1) - timedelta(days=1)
            else:
                last_of_month = date(year, month_num + 1, 1) - timedelta(days=1)

            if week_num == -1:  # "last week"
                # Last 7 days of the month
                end_day = last_of_month
                start_day = end_day - timedelta(days=6)
            else:
                # Calculate start of nth week (week 1 = days 1-7, week 2 = days 8-14, etc.)
                start_day_num = 1 + (week_num - 1) * 7
                end_day_num = min(start_day_num + 6, last_of_month.day)

                try:
                    start_day = date(year, month_num, start_day_num)
                    end_day = date(year, month_num, end_day_num)
                except ValueError:
                    # Invalid date (e.g., week 5 of a short month)
                    return None, None

            start_iso = start_day.strftime("%Y-%m-%d")
            end_iso = end_day.strftime("%Y-%m-%d")
            return start_iso, end_iso

        return None, None

    def parse_date_range_with_ambiguity(
        self, text: str
    ) -> Tuple[Optional[str], Optional[str], bool]:
        """
        Deterministic month-day range parser with straddle-today detection.

        This is the preferred method for parsing date ranges as it detects
        ambiguous year situations instead of silently guessing.

        Args:
            text: Input text like "December 20-27", "Dec 20-27", "20-27 December"

        Returns:
            Tuple of (start_iso, end_iso, is_ambiguous) where:
            - start_iso/end_iso: ISO date strings or None if parse failed
            - is_ambiguous: True if year is ambiguous (straddles today)
        """
        text = text.strip()
        if not text:
            return None, None, False

        for pattern in self._DATE_RANGE_PATTERNS:
            match = pattern.match(text)
            if not match:
                continue

            groups = match.groups()

            # Determine if pattern matched month first or day first
            if groups[0].isdigit():
                # Pattern 2: start_day, end_day, month, year
                start_day = int(groups[0])
                end_day = int(groups[1])
                month_str = groups[2]
                year_str = groups[3] if len(groups) > 3 else None
            else:
                # Pattern 1: month, start_day, end_day, year
                month_str = groups[0]
                start_day = int(groups[1])
                end_day = int(groups[2])
                year_str = groups[3] if len(groups) > 3 else None

            # Parse month name to number
            try:
                month_dt = datetime.strptime(month_str[:3], "%b")
                month_num = month_dt.month
            except ValueError:
                continue

            # If explicit year provided, no ambiguity
            if year_str:
                year = int(year_str)
                try:
                    start_iso = f"{year:04d}-{month_num:02d}-{start_day:02d}"
                    end_iso = f"{year:04d}-{month_num:02d}-{end_day:02d}"
                    datetime.strptime(start_iso, "%Y-%m-%d")
                    datetime.strptime(end_iso, "%Y-%m-%d")
                    return start_iso, end_iso, False
                except ValueError:
                    continue

            # Check for straddle-today ambiguity
            today = self._reference
            year = today.year

            try:
                # Build candidate dates in current year
                start_candidate = date(year, month_num, start_day)
                end_candidate = date(year, month_num, end_day)

                # Straddle-today detection:
                # 1. Today falls inside the range, OR
                # 2. Start is in past but end is in future (range crosses today)
                is_ambiguous = False

                if start_candidate <= today <= end_candidate:
                    # Today is inside the range
                    is_ambiguous = True
                elif start_candidate < today and end_candidate >= today:
                    # Range crosses today
                    is_ambiguous = True
                elif start_candidate < today and end_candidate < today:
                    # Entire range is in the past - assume next year, not ambiguous
                    year += 1

                start_iso = f"{year:04d}-{month_num:02d}-{start_day:02d}"
                end_iso = f"{year:04d}-{month_num:02d}-{end_day:02d}"

                return start_iso, end_iso, is_ambiguous

            except ValueError:
                # Invalid date for month
                continue

        return None, None, False

    def compute_end_from_duration(
        self, start_date: Optional[str], duration_days: int
    ) -> Optional[str]:
        """Compute end_date from start_date and duration in days."""
        if not start_date or duration_days <= 0:
            return None

        start_dt = self.parse_iso(start_date)
        if not start_dt:
            return None

        end_dt = start_dt + timedelta(days=duration_days)
        return end_dt.strftime("%Y-%m-%d")

    def is_valid_range(self, start_date: Optional[str], end_date: Optional[str]) -> bool:
        """Check if end_date >= start_date (allowing same-day trips)."""
        if not start_date or not end_date:
            return True  # Can't validate incomplete range

        start_dt = self.parse_iso(start_date)
        end_dt = self.parse_iso(end_date)
        if not start_dt or not end_dt:
            return True  # Can't validate unparseable dates

        return end_dt >= start_dt


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
# DATE ERROR CODES (Explicit error codes for date parsing issues)
# =============================================================================
# These error codes are used to drive template selection, loop mitigation,
# generation blocking, and observability.
class DateErrorCode:
    """Explicit error codes for date-related issues."""

    AMBIGUOUS_YEAR = "DATE_AMBIGUOUS_YEAR"  # Month-day range straddles today
    RANGE_INVALID = "DATE_RANGE_INVALID"  # start_date > end_date after all corrections
    PARSE_FAILED = "DATE_PARSE_FAILED"  # Could not parse date at all
    FORMAT_AMBIGUOUS = "DATE_FORMAT_AMBIGUOUS"  # DD/MM vs MM/DD ambiguity (future)


DATE_BLOCKING_ERROR_CODES = frozenset({DateErrorCode.AMBIGUOUS_YEAR, DateErrorCode.RANGE_INVALID})


# =============================================================================
# DATE OBSERVABILITY STATS
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

    state.metadata["question_target"] = canonical
    state.metadata["question_target_source"] = source
    state.question_target = canonical  # Sync state for this turn


def get_question_target(state: "GraphState") -> Optional[str]:
    """
    Read canonical question_target from metadata (SSoT).

    Returns:
        Canonical question_target value, or None if not set
    """
    return canonicalize_question_target(state.metadata.get("question_target"))


# =============================================================================
# NORMALIZATION ERROR
# =============================================================================
@dataclass
class NormalizationError:
    """
    Structured error from normalization with severity level.

    Attributes:
        field: The field name that had the error
        code: Machine-readable error code (e.g., DATE_AMBIGUOUS_YEAR)
        message: Human-readable error message
        severity: 'warning' for recoverable issues, 'error' for blocking issues
        original_value: The original value that caused the error
    """

    field: str
    message: str
    severity: Literal["warning", "error"]
    original_value: Any = None
    code: Optional[str] = None  # Machine-readable error code


# =============================================================================
# TRIP INPUT NORMALIZER (Unified normalization logic)
# =============================================================================
class TripInputNormalizer:
    """
    Unified normalization for all trip inputs.

    Consolidates all normalization logic (dates, destinations, currency, travelers,
    settings) into a single class. This is the ONLY place where normalization
    should occur in the graph.

    Usage:
        normalizer = TripInputNormalizer()
        updates, errors = normalizer.normalize_all(trip_inputs, deltas)
    """

    # Extended currency symbol map (from graph_plan_utils.py - more complete)
    CURRENCY_SYMBOL_MAP: Dict[str, str] = {
        "$": "USD",
        "€": "EUR",
        "£": "GBP",
        "¥": "JPY",
        "₹": "INR",
        "₩": "KRW",
        "₽": "RUB",
        "₺": "TRY",
        "R$": "BRL",
        "kr": "SEK",
        "CHF": "CHF",
        "A$": "AUD",
        "C$": "CAD",
        "NZ$": "NZD",
        "HK$": "HKD",
        "S$": "SGD",
    }

    # Extended ISO-4217 currency codes (from graph_plan_utils.py - 30 currencies)
    SUPPORTED_CURRENCIES: frozenset = frozenset(
        {
            "USD",
            "EUR",
            "GBP",
            "CAD",
            "AUD",
            "JPY",
            "CHF",
            "CNY",
            "INR",
            "MXN",
            "BRL",
            "KRW",
            "SGD",
            "HKD",
            "NOK",
            "SEK",
            "DKK",
            "NZD",
            "ZAR",
            "RUB",
            "TRY",
            "PLN",
            "THB",
            "MYR",
            "IDR",
            "PHP",
            "CZK",
            "ILS",
            "AED",
            "SAR",
        }
    )

    def __init__(self, date_normalizer: Optional[DateNormalizer] = None):
        """
        Initialize with optional DateNormalizer instance.

        Args:
            date_normalizer: DateNormalizer instance, uses global singleton if None.
        """
        self._date_normalizer = date_normalizer or _date_normalizer

    # -------------------------------------------------------------------------
    # Date Normalization (delegates to DateNormalizer)
    # -------------------------------------------------------------------------
    def normalize_date(self, value: Any) -> Optional[str]:
        """Normalize date to ISO format (YYYY-MM-DD)."""
        return self._date_normalizer.normalize(value)

    def normalize_date_with_info(self, value: Any) -> tuple[Optional[str], bool]:
        """Normalize date, returning (iso_date, was_partial)."""
        return self._date_normalizer.normalize_with_info(value)

    def validate_date_range(
        self,
        start_date: Optional[str],
        end_date: Optional[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[Optional[str], Optional[str], List[NormalizationError], bool]:
        """
        Validate and fix date range issues with hardened invariants.

        Date Parsing Ownership Hierarchy:
        ---------------------------------
        1. LQA pre-pass (deterministic, zero-LLM) - first attempt
        2. FULL extractor (LLM-based) - fallback, authoritative output
        3. This method (normalizer) - invariant enforcement ONLY, no guessing

        Hardened Invariants:
        -------------------
        - NEVER store reversed dates (start_date > end_date)
        - If swap still produces invalid range, CLEAR both dates
        - Set date_clarify_mode when ambiguity detected

        Handles:
        - Cross-year correction (Dec start → Jan/Feb end)
        - Atomic date swap if end < start (with re-validation)
        - Past date warnings
        - Straddle-today ambiguity detection

        Returns:
            Tuple of (corrected_start, corrected_end, errors, needs_clarify)
            where needs_clarify=True triggers date_clarify_mode
        """
        errors: List[NormalizationError] = []
        corrected_start = start_date
        corrected_end = end_date
        needs_clarify = False

        if not start_date or not end_date:
            return corrected_start, corrected_end, errors, needs_clarify

        start_dt = self._date_normalizer.parse_iso(start_date)
        end_dt = self._date_normalizer.parse_iso(end_date)

        if not start_dt or not end_dt:
            return corrected_start, corrected_end, errors, needs_clarify

        today = self._date_normalizer.today

        # =====================================================================
        # STRADDLE-TODAY AMBIGUITY DETECTION
        # =====================================================================
        # If both dates are in current year and range straddles today,
        # the year is ambiguous (user might mean this year or next)
        if start_dt.year == end_dt.year == today.year:
            start_d = start_dt.date()
            end_d = end_dt.date()
            # Straddle: start <= today <= end OR (start < today and end >= today)
            if (start_d <= today <= end_d) or (start_d < today and end_d >= today):
                _date_stats["date_ambiguous_year_count"] += 1
                errors.append(
                    NormalizationError(
                        field="dates",
                        code=DateErrorCode.AMBIGUOUS_YEAR,
                        message=(
                            f"Date range {start_date} to {end_date} straddles today - "
                            "year is ambiguous"
                        ),
                        severity="error",
                        original_value={"start_date": start_date, "end_date": end_date},
                    )
                )
                # Store pending dates for clarification resolution
                if metadata is not None:
                    metadata["pending_date_range"] = {
                        "start_date": start_date,
                        "end_date": end_date,
                    }
                needs_clarify = True
                # Return None dates - don't store ambiguous values
                return None, None, errors, needs_clarify

        # =====================================================================
        # CROSS-YEAR CORRECTION (Dec start → Jan/Feb end)
        # =====================================================================
        if start_dt.month == 12 and end_dt.month in (1, 2) and end_dt.year == start_dt.year:
            corrected_end_dt = end_dt.replace(year=start_dt.year + 1)
            corrected_end = corrected_end_dt.strftime("%Y-%m-%d")
            errors.append(
                NormalizationError(
                    field="end_date",
                    message=f"Corrected cross-year date: {end_date} → {corrected_end}",
                    severity="warning",
                    original_value=end_date,
                )
            )
            _debug(f"Corrected cross-year date range: {end_date} → {corrected_end}")
            end_dt = corrected_end_dt

        # =====================================================================
        # ATOMIC DATE SWAP WITH RE-VALIDATION
        # =====================================================================
        # If end < start after corrections, attempt atomic swap
        if end_dt < start_dt:
            # Perform atomic swap
            swapped_start = corrected_end
            swapped_end = corrected_start
            corrected_start = swapped_start
            corrected_end = swapped_end

            errors.append(
                NormalizationError(
                    field="dates",
                    message=f"Swapped dates: start={start_date}, end={end_date}",
                    severity="warning",
                    original_value={"start_date": start_date, "end_date": end_date},
                )
            )
            _debug(f"Auto-swapped dates: {start_date} ↔ {end_date}")

            # Re-validate after swap
            swapped_start_dt = self._date_normalizer.parse_iso(corrected_start)
            swapped_end_dt = self._date_normalizer.parse_iso(corrected_end)

            if swapped_start_dt and swapped_end_dt and swapped_end_dt < swapped_start_dt:
                # Swap didn't fix it - clear both and require clarification
                _date_stats["date_range_invalid_count"] += 1
                errors.append(
                    NormalizationError(
                        field="dates",
                        code=DateErrorCode.RANGE_INVALID,
                        message=(
                            "Date range invalid after swap: " f"{corrected_start} > {corrected_end}"
                        ),
                        severity="error",
                        original_value={"start_date": start_date, "end_date": end_date},
                    )
                )
                if metadata is not None:
                    metadata["pending_date_range"] = {
                        "start_date": start_date,
                        "end_date": end_date,
                    }
                needs_clarify = True
                return None, None, errors, needs_clarify

            # Update datetime objects after successful swap
            start_dt = swapped_start_dt
            end_dt = swapped_end_dt

        # =====================================================================
        # PAST DATE HANDLING
        # =====================================================================
        if start_dt and start_dt.date() < today:
            # Bump past start dates to next year
            bumped_start_dt = start_dt.replace(year=start_dt.year + 1)
            corrected_start = bumped_start_dt.strftime("%Y-%m-%d")
            errors.append(
                NormalizationError(
                    field="start_date",
                    message=f"Start date {start_date} is in the past, bumped to {corrected_start}",
                    severity="warning",
                    original_value=start_date,
                )
            )
            _debug(f"Bumped past start date: {start_date} → {corrected_start}")

            # Also bump end date if it was in the same year
            if end_dt and end_dt.year == start_dt.year:
                bumped_end_dt = end_dt.replace(year=end_dt.year + 1)
                corrected_end = bumped_end_dt.strftime("%Y-%m-%d")
                _debug(f"Bumped end date to match: {end_date} → {corrected_end}")

        # =====================================================================
        # FINAL INVARIANT CHECK
        # =====================================================================
        final_start_dt = self._date_normalizer.parse_iso(corrected_start)
        final_end_dt = self._date_normalizer.parse_iso(corrected_end)

        if final_start_dt and final_end_dt and final_end_dt < final_start_dt:
            # Still invalid after all corrections - this is a hard error
            _date_stats["date_range_invalid_count"] += 1
            errors.append(
                NormalizationError(
                    field="dates",
                    code=DateErrorCode.RANGE_INVALID,
                    message=f"Date range invariant violation: {corrected_start} > {corrected_end}",
                    severity="error",
                    original_value={"start_date": start_date, "end_date": end_date},
                )
            )
            if metadata is not None:
                metadata["pending_date_range"] = {
                    "start_date": start_date,
                    "end_date": end_date,
                }
            needs_clarify = True
            # NEVER store reversed dates
            return None, None, errors, needs_clarify

        return corrected_start, corrected_end, errors, needs_clarify

    # -------------------------------------------------------------------------
    # Currency Normalization
    # -------------------------------------------------------------------------
    def normalize_currency(self, value: Any, *, default: Optional[str] = None) -> Optional[str]:
        """
        Normalize currency to ISO-4217 code.

        Maps symbols ($, €, £, etc.) to codes and validates against ISO-4217.
        Uses extended set of 30 currencies.
        """
        if value is None:
            return default

        text = _normalize_str(value)
        if not text:
            return default

        # Check if it's a symbol
        if text in self.CURRENCY_SYMBOL_MAP:
            return self.CURRENCY_SYMBOL_MAP[text]

        # Uppercase and check against ISO codes
        code = text.upper()
        if code in self.SUPPORTED_CURRENCIES:
            return code

        # Check if symbol is part of value (e.g., "$100" -> extract $)
        for symbol, symbol_code in self.CURRENCY_SYMBOL_MAP.items():
            if text.startswith(symbol):
                return symbol_code

        return default

    # -------------------------------------------------------------------------
    # Traveler Normalization
    # -------------------------------------------------------------------------
    def clamp_travelers(self, value: Optional[int]) -> Optional[int]:
        """Constrain traveler count to valid range [0, 20]."""
        if value is None:
            return None
        return max(0, min(20, value))

    def normalize_adults(self, value: Any) -> Optional[int]:
        """Normalize adults count (min 1 when specified)."""
        int_val = _normalize_int(value)
        if int_val is None:
            return None
        return max(1, min(20, int_val))

    def normalize_children(self, value: Any) -> Optional[int]:
        """Normalize children count (min 0)."""
        int_val = _normalize_int(value)
        if int_val is None:
            return None
        return max(0, min(20, int_val))

    # -------------------------------------------------------------------------
    # Destination Normalization
    # -------------------------------------------------------------------------
    def normalize_destinations(
        self,
        destinations: List[str],
        new_destinations: Optional[List[str]] = None,
    ) -> tuple[List[str], List[NormalizationError]]:
        """
        Normalize and merge destinations.

        - Applies synonym mapping (NYC → New York City)
        - Filters phrase-like destinations containing excluded words
        - Deduplicates case-insensitively
        - Removes sublocations when parent exists

        Args:
            destinations: Existing destinations list
            new_destinations: New destinations to merge (optional)

        Returns:
            Tuple of (normalized_destinations, errors)
        """
        errors: List[NormalizationError] = []
        result = list(destinations)
        existing_lower = {d.lower() for d in result}

        if new_destinations:
            for d in new_destinations:
                d_norm = _normalize_str(d)
                if not d_norm:
                    continue

                # Apply synonym normalization
                d_norm = normalize_place_synonym(d_norm)
                d_lower = d_norm.lower()

                # Filter phrase-like destinations
                if any(word in d_lower for word in _DEST_EXCLUDE_WORDS):
                    errors.append(
                        NormalizationError(
                            field="destinations",
                            message=f"Filtered phrase-like destination: {d_norm}",
                            severity="warning",
                            original_value=d,
                        )
                    )
                    _debug(f"Filtering phrase-like destination: {d_norm}")
                    continue

                # Skip duplicates
                if d_lower not in existing_lower:
                    result.append(d_norm)
                    existing_lower.add(d_lower)

        # Deduplicate overlapping locations
        result = _deduplicate_destinations(result)

        return result, errors

    # -------------------------------------------------------------------------
    # Settings Normalization
    # -------------------------------------------------------------------------
    def merge_nested_settings(
        self,
        existing: Optional[Dict[str, Any]],
        delta: Dict[str, Any],
        list_fields: Optional[set] = None,
    ) -> Dict[str, Any]:
        """
        Merge nested settings dict with special handling for list fields.

        For list fields (like 'amenities'), extends rather than replaces.
        """
        list_fields = list_fields or {"amenities", "categories"}
        result = dict(existing) if existing else {}

        for key, value in delta.items():
            if key in list_fields and isinstance(value, list):
                # Extend list, avoiding duplicates
                existing_list = result.get(key, [])
                for item in value:
                    if item not in existing_list:
                        existing_list.append(item)
                result[key] = existing_list
            else:
                result[key] = value

        return result

    # -------------------------------------------------------------------------
    # Full Normalization Pass
    # -------------------------------------------------------------------------
    def normalize_all(
        self,
        trip_inputs: "TripInputs",
        deltas: Dict[str, Any],
        user_text: Optional[str] = None,
    ) -> tuple[Dict[str, Any], List[NormalizationError]]:
        """
        Single normalization pass for all trip inputs.

        This is the ONLY place where normalization should occur.
        Called from normalize_inputs node.

        Args:
            trip_inputs: Current TripInputs state
            deltas: Dict of field deltas to apply (from extractor)
            user_text: Original user text, used to recover dates when LLM strips the day

        Returns:
            Tuple of (updates_dict, errors_list)
        """
        _debug("TripInputNormalizer.normalize_all called - single normalization pass")

        updates: Dict[str, Any] = {}
        errors: List[NormalizationError] = []

        # --- Origin ---
        if "origin_delta" in deltas:
            origin_raw = _normalize_str(deltas["origin_delta"])
            if origin_raw:
                updates["origin"] = normalize_place_synonym(origin_raw)

        # --- Destinations ---
        if "destinations_delta" in deltas:
            dest_list = deltas["destinations_delta"]
            if isinstance(dest_list, str):
                dest_list = [dest_list]
            if isinstance(dest_list, list):
                normalized_dests, dest_errors = self.normalize_destinations(
                    trip_inputs.destinations, dest_list
                )
                if normalized_dests != trip_inputs.destinations:
                    updates["destinations"] = normalized_dests
                errors.extend(dest_errors)

        # --- Dates ---
        partial_date_notifications: List[str] = []
        # Track date provenance for explicit year protection
        date_provenance_updates: Dict[str, DateProvenance] = {}

        # Get current turn number for provenance tracking
        turn_number = deltas.get("_turn_number")

        # First, try to parse date ranges from start_date_hint (e.g., "December 20-27")
        # This handles cases where LLM sends the range as a single hint
        if "start_date_hint" in deltas and not trip_inputs.start_date:
            raw_hint = deltas["start_date_hint"]

            # Try parsing as a date range first
            range_start, range_end = self._date_normalizer.parse_date_range(raw_hint)
            if range_start and range_end:
                # Check for explicit year in the range hint
                explicit_year = self._date_normalizer.has_explicit_year(raw_hint)
                updates["start_date"] = range_start
                updates["end_date"] = range_end
                date_provenance_updates["start_date"] = DateProvenance(
                    value=range_start,
                    source_turn=turn_number,
                    explicit_year=explicit_year,
                    parsed_from="date_range",
                )
                date_provenance_updates["end_date"] = DateProvenance(
                    value=range_end,
                    source_turn=turn_number,
                    explicit_year=explicit_year,
                    parsed_from="date_range",
                )
                _debug(
                    "Parsed date range from start_date_hint",
                    raw=raw_hint,
                    start=range_start,
                    end=range_end,
                    explicit_year=explicit_year,
                )
            else:
                # Fall back to single date parsing with provenance tracking
                provenance = self._date_normalizer.normalize_with_provenance(raw_hint, turn_number)
                if provenance:
                    # If we got a partial_month result, try to recover full date from user_text
                    if provenance.parsed_from == "partial_month" and user_text:
                        # Extract month hint for targeted search
                        month_hint = raw_hint.split()[0] if raw_hint else None
                        full_date = self._date_normalizer.find_date_in_text(user_text, month_hint)
                        if full_date:
                            _debug(
                                "Recovered full date from user_text",
                                llm_hint=raw_hint,
                                recovered_date=full_date,
                                user_text=user_text[:50],
                            )
                            # Use the recovered date instead
                            explicit_year = self._date_normalizer.has_explicit_year(user_text)
                            provenance = DateProvenance(
                                value=full_date,
                                source_turn=turn_number,
                                explicit_year=explicit_year,
                                parsed_from="user_text_recovery",
                            )
                        else:
                            partial_date_notifications.append(
                                f"start_date set to first of month from '{raw_hint}'"
                            )
                    updates["start_date"] = provenance.value
                    date_provenance_updates["start_date"] = provenance

        if "end_date_hint" in deltas:
            raw_hint = deltas["end_date_hint"]
            provenance = self._date_normalizer.normalize_with_provenance(raw_hint, turn_number)
            if provenance:
                # If we got a partial_month result, try to recover full date from user_text
                if provenance.parsed_from == "partial_month" and user_text:
                    month_hint = raw_hint.split()[0] if raw_hint else None
                    # For end_date, we need to find a second date or a range end
                    full_date = self._date_normalizer.find_date_in_text(user_text, month_hint)
                    if full_date:
                        _debug(
                            "Recovered full end_date from user_text",
                            llm_hint=raw_hint,
                            recovered_date=full_date,
                        )
                        explicit_year = self._date_normalizer.has_explicit_year(user_text)
                        provenance = DateProvenance(
                            value=full_date,
                            source_turn=turn_number,
                            explicit_year=explicit_year,
                            parsed_from="user_text_recovery",
                        )
                    else:
                        partial_date_notifications.append(
                            f"end_date set to first of month from '{raw_hint}'"
                        )
                updates["end_date"] = provenance.value
                date_provenance_updates["end_date"] = provenance

        # Duration-based end_date computation
        if "duration_days_hint" in deltas and not trip_inputs.end_date:
            start = updates.get("start_date") or trip_inputs.start_date
            duration = _normalize_int(deltas["duration_days_hint"])
            if start and duration and duration > 0:
                end = self._date_normalizer.compute_end_from_duration(start, duration)
                if end:
                    updates["end_date"] = end
                    updates["duration_days"] = duration

        # Validate date range (cross-year, swap, past-date)
        start = updates.get("start_date") or trip_inputs.start_date
        end = updates.get("end_date") or trip_inputs.end_date
        if start and end:
            corrected_start, corrected_end, date_errors, needs_clarify = self.validate_date_range(
                start, end
            )
            if corrected_start != start:
                updates["start_date"] = corrected_start
            if corrected_end != end:
                updates["end_date"] = corrected_end
            errors.extend(date_errors)
            if needs_clarify:
                updates["_needs_date_clarify"] = True

        # Store partial date notifications in metadata
        if partial_date_notifications:
            updates["_partial_date_notifications"] = partial_date_notifications

        # --- Travelers ---
        if "adults_delta" in deltas:
            adults = self.normalize_adults(deltas["adults_delta"])
            if adults is not None:
                updates["adults"] = adults

        if "children_delta" in deltas:
            children = self.normalize_children(deltas["children_delta"])
            if children is not None:
                updates["children"] = children

        if "requires_assistance_delta" in deltas:
            updates["requires_assistance"] = deltas["requires_assistance_delta"]

        # --- Budget & Currency ---
        if "budget_delta" in deltas:
            budget = _normalize_budget(deltas["budget_delta"])
            if budget is not None:
                updates["budget"] = budget

        if "currency_delta" in deltas:
            currency = self.normalize_currency(deltas["currency_delta"])
            if currency:
                updates["currency"] = currency
        elif "budget_delta" in deltas and not trip_inputs.currency:
            # Default currency if budget set but no currency
            updates["currency"] = DEFAULT_CURRENCY

        # --- Multi-city Intent ---
        if "multi_city_intent_delta" in deltas:
            intent = _normalize_multi_city_intent(deltas["multi_city_intent_delta"])
            if intent:
                updates["multi_city_intent"] = intent

        # --- Settings (flight, hotel, transport, activity) ---
        if "flight_settings_delta" in deltas:
            delta = deltas["flight_settings_delta"]
            if isinstance(delta, dict):
                normalized = _normalize_booking_field("flight_settings", delta)
                if normalized:
                    merged = self.merge_nested_settings(trip_inputs.flight_settings, normalized)
                    updates["flight_settings"] = merged

        if "hotel_settings_delta" in deltas:
            delta = deltas["hotel_settings_delta"]
            if isinstance(delta, dict):
                normalized = _normalize_booking_field("hotel_settings", delta)
                if normalized:
                    merged = self.merge_nested_settings(
                        trip_inputs.hotel_settings, normalized, list_fields={"amenities"}
                    )
                    updates["hotel_settings"] = merged

        if "transport_settings_delta" in deltas:
            delta = deltas["transport_settings_delta"]
            if isinstance(delta, dict):
                normalized = _normalize_booking_field("transport_settings", delta)
                if normalized:
                    merged = self.merge_nested_settings(trip_inputs.transport_settings, normalized)
                    updates["transport_settings"] = merged

        if "activity_categories_delta" in deltas:
            delta = deltas["activity_categories_delta"]
            if isinstance(delta, list):
                existing = trip_inputs.activity_settings or {}
                existing_cats = list(existing.get("categories", []))
                # Normalize via _normalize_booking_field for consistency
                normalized = _normalize_booking_field("activity_settings", {"categories": delta})
                if normalized and "categories" in normalized:
                    for cat in normalized["categories"]:
                        if cat not in existing_cats:
                            existing_cats.append(cat)
                    # Deduplicate case-insensitively
                    existing_cats = _deduplicate_activities_case_insensitive(existing_cats)
                updates["activity_settings"] = {"categories": existing_cats}

        # --- Category Activation (booking types) ---
        if "category_activation" in deltas:
            activation = deltas["category_activation"]
            if isinstance(activation, dict):
                booking_types = dict(trip_inputs.booking_types or DEFAULT_BOOKING_TYPES)
                for cat, enabled in activation.items():
                    if cat in booking_types and isinstance(enabled, bool):
                        booking_types[cat] = enabled
                updates["booking_types"] = booking_types

        # --- Budget Per Night Derivation ---
        # Compute budget_per_night if we have budget_total and dates
        budget_total = updates.get("budget") or trip_inputs.budget
        start_date = updates.get("start_date") or trip_inputs.start_date
        end_date = updates.get("end_date") or trip_inputs.end_date

        if budget_total and start_date and end_date:
            # Only derive if not already explicitly set
            existing_budget_basis = (
                trip_inputs.strategy_settings.get("budget_basis")
                if trip_inputs.strategy_settings
                else None
            )
            if existing_budget_basis != "per_night":
                start_dt = self._date_normalizer.parse_iso(start_date)
                end_dt = self._date_normalizer.parse_iso(end_date)
                if start_dt and end_dt:
                    nights = max(1, (end_dt.date() - start_dt.date()).days)
                    budget_per_night = round(budget_total / nights, 2)

                    # Store in strategy_settings (extend existing or create new)
                    strategy_updates = dict(
                        updates.get("strategy_settings") or trip_inputs.strategy_settings or {}
                    )
                    strategy_updates["budget_per_night"] = budget_per_night
                    strategy_updates["budget_total"] = budget_total
                    strategy_updates["budget_nights"] = nights
                    if "budget_basis" not in strategy_updates:
                        strategy_updates["budget_basis"] = "total"
                    updates["strategy_settings"] = strategy_updates

                    _debug(
                        "Derived budget_per_night",
                        budget_total=budget_total,
                        nights=nights,
                        budget_per_night=budget_per_night,
                    )

        # --- Store Date Provenance for merge protection ---
        if date_provenance_updates:
            updates["_date_provenance"] = {
                k: v.to_dict() for k, v in date_provenance_updates.items()
            }

        return updates, errors


# Singleton instance for default usage
_trip_normalizer = TripInputNormalizer()


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


def _normalize_budget(value: Any) -> Optional[float]:
    """Normalize a budget value to a float, handling currency symbols."""
    if value is None:
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

    # Phrase-based inference
    separate_phrases = (
        "separate trip",
        "separate trips",
        "do them separately",
        "different trips",
        "compare destinations",
        "compare them",
    )
    multi_phrases = (
        "multi city",
        "multicity",
        "one trip",
        "single trip",
        "same trip",
        "together",
        "all together",
        "one itinerary",
        "visit both",
        "visit all",
        "see both",
        "do both",
    )

    # Additive phrases that imply combining destinations (AND logic)
    # These require checking the full phrase pattern, not just substring
    additive_patterns = (
        r"\btoo\b",  # "go to X too", "visit X too"
        r"\balso\b",  # "also visit X", "also go to X"
        r"\bas well\b",  # "visit X as well"
        r"\band\s+also\b",  # "and also X"
    )
    import re as _re_inner

    for pattern in additive_patterns:
        if _re_inner.search(pattern, normalized):
            return "multi_city"

    if "not separate" not in normalized:
        for phrase in separate_phrases:
            if phrase in normalized:
                return "separate"

    for phrase in multi_phrases:
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


def _auto_enable_booking_types(trip_inputs: TripInputs) -> None:
    """Auto-enable booking_types based on sub-settings."""
    booking_types = dict(trip_inputs.booking_types) if trip_inputs.booking_types else {}

    if _should_enable_booking_for_flights(trip_inputs.flight_settings):
        booking_types["flights"] = True
    if _should_enable_booking_for_hotels(trip_inputs.hotel_settings):
        booking_types["hotels"] = True
    if _should_enable_booking_for_activities(trip_inputs.activity_settings):
        booking_types["activities"] = True
    if _should_enable_booking_for_transport(trip_inputs.transport_settings):
        booking_types["ground_transport"] = True

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
    "budget": {"budget", "cheap", "affordable", "backpacker", "hostel", "low-cost"},
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
    }


# =============================================================================
# MISSING FIELDS & DEFAULT QUESTION (ported from plan.py)
# =============================================================================


# =============================================================================
# TRIP READINESS (Phase 6 Consolidation)
# =============================================================================
# Single canonical computation for missing fields, question target, and readiness.
# All nodes MUST use this instead of computing missing fields inline.


@dataclass
class TripReadiness:
    """
    Canonical trip readiness state - computed once, used everywhere.

    This consolidates _compute_missing_fields, _has_required_core_fields,
    and _get_missing_fields_summary into a single authoritative computation.
    """

    # Core required fields (destinations, origin, start_date)
    missing_core: List[str] = field(default_factory=list)
    # All required fields (core + end_date + adults + budget)
    missing_all: List[str] = field(default_factory=list)
    # Which field to ask about next (priority order)
    question_target: Optional[str] = None
    # Whether all core fields are present
    core_complete: bool = False
    # Whether ready to generate plan
    ready_to_generate: bool = False
    # Human-readable summary for prompt injection
    missing_summary: str = "none - all required fields collected"
    # Blocking errors that prevent routing to specialists/generation
    # (e.g., DATE_AMBIGUOUS_YEAR, DATE_RANGE_INVALID)
    blocking_errors: List[str] = field(default_factory=list)

    @property
    def has_destinations(self) -> bool:
        return "destinations" not in self.missing_core

    @property
    def has_origin(self) -> bool:
        return "origin" not in self.missing_core

    @property
    def has_dates(self) -> bool:
        return "start_date" not in self.missing_core

    @property
    def has_blocking_errors(self) -> bool:
        """Check if any blocking errors exist that prevent progression."""
        return len(self.blocking_errors) > 0


def compute_trip_readiness(
    trip_inputs: "TripInputs",
    prefer_date_first: bool = False,
    errors: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> TripReadiness:
    """
    Compute canonical trip readiness state.

    This is the ONLY function that should compute missing fields.
    All nodes must use this instead of inline checks.

    Args:
        trip_inputs: Current trip inputs (TripInputs object or dict)
        prefer_date_first: If True, prioritize start_date over destinations
            when determining question_target. Used for broad/open-ended queries.
        errors: Optional list of errors to check for blocking errors
        metadata: Optional metadata dict to check for date_clarify_mode

    Returns:
        TripReadiness with all computed fields including blocking_errors
    """
    # Handle both TripInputs object and dict
    if hasattr(trip_inputs, "destinations"):
        # TripInputs object
        ti = trip_inputs
        destinations = ti.destinations
        origin = ti.origin
        start_date = ti.start_date
        end_date = ti.end_date
        adults = ti.adults
        budget = ti.budget
    else:
        # Dict
        destinations = trip_inputs.get("destinations", [])
        origin = trip_inputs.get("origin")
        start_date = trip_inputs.get("start_date")
        end_date = trip_inputs.get("end_date")
        adults = trip_inputs.get("adults")
        budget = trip_inputs.get("budget")

    # Compute missing core fields
    missing_core = []
    if not destinations or (isinstance(destinations, list) and len(destinations) == 0):
        missing_core.append("destinations")
    if not origin:
        missing_core.append("origin")
    if not start_date:
        missing_core.append("start_date")

    # Compute all missing fields (core + optional but useful)
    missing_all = list(missing_core)
    if not end_date:
        missing_all.append("end_date")
    if adults is None:
        missing_all.append("travelers (adults)")
    if budget is None:
        missing_all.append("budget")

    # Compute blocking errors from errors list
    blocking_errors: List[str] = []
    if errors:
        for err in errors:
            if isinstance(err, NormalizationError) and err.code in DATE_BLOCKING_ERROR_CODES:
                blocking_errors.append(err.code)
            elif isinstance(err, dict):
                # Handle dict errors with "code" key
                code = err.get("code", "")
                if code in DATE_BLOCKING_ERROR_CODES:
                    blocking_errors.append(code)
            elif isinstance(err, str):
                for code in DATE_BLOCKING_ERROR_CODES:
                    if code in err:
                        blocking_errors.append(code)
                        break
    # Also check metadata for date_clarify_mode
    if metadata and metadata.get("date_clarify_mode"):
        if DateErrorCode.AMBIGUOUS_YEAR not in blocking_errors:
            blocking_errors.append(DateErrorCode.AMBIGUOUS_YEAR)

    # Determine question target (priority order)
    # Context-aware: if prefer_date_first and both destinations and dates are missing,
    # ask about dates first (helps with strategy recommendations)
    # OVERRIDE: If blocking date errors exist, always ask about dates first
    question_target = None
    if blocking_errors:
        question_target = "dates"
    elif missing_core:
        if prefer_date_first and "destinations" in missing_core and "start_date" in missing_core:
            # Prefer start_date over destinations for open-ended queries
            question_target = "dates"
        else:
            question_target = missing_core[0]
            # Normalize "start_date" to "dates" for user-facing questions
            if question_target == "start_date":
                question_target = "dates"
    elif missing_all:
        # All core complete, ask about optional fields
        first_optional = [
            f for f in missing_all if f not in ["destinations", "origin", "start_date"]
        ]
        if first_optional:
            field = first_optional[0]
            # Normalize field names for user-facing
            if field == "travelers (adults)":
                question_target = "travelers"
            else:
                question_target = field

    # Compute readiness
    core_complete = len(missing_core) == 0
    # ready_to_generate requires core complete AND no blocking errors
    ready_to_generate = core_complete and len(blocking_errors) == 0

    # Build summary string
    if missing_all:
        missing_summary = ", ".join(missing_all)
    else:
        missing_summary = "none - all required fields collected"

    return TripReadiness(
        missing_core=missing_core,
        missing_all=missing_all,
        question_target=question_target,
        core_complete=core_complete,
        ready_to_generate=ready_to_generate,
        missing_summary=missing_summary,
        blocking_errors=blocking_errors,
    )


def _has_required_core_fields(state: "GraphState") -> tuple[bool, List[str]]:
    """
    Check if required core fields (destinations, origin, start_date) are present.

    DEPRECATED: Use compute_trip_readiness() instead.

    Args:
        state: Current graph state

    Returns:
        Tuple of (has_all_fields: bool, missing_fields: List[str])
    """
    readiness = compute_trip_readiness(state.trip_inputs)
    return (readiness.core_complete, readiness.missing_core)


def _default_follow_up_with_field(
    missing_fields: List[str],
    user_intent: str = "detailed_planner",
    user_tone: str = "neutral",
    trip_inputs: Optional[dict] = None,
) -> tuple[Optional[str], Optional[str]]:
    """
    Get the default question and the field being asked about.
    Adapts phrasing based on user intent, tone, and existing trip context.
    Professional and natural—matches user energy without overdoing it.

    Returns a tuple of (question, field_name) for tracking which field
    was last asked, enabling context-aware clarification responses.
    """
    if not missing_fields:
        return None, None

    trip_inputs = trip_inputs or {}
    destinations = trip_inputs.get("destinations", [])

    # When we know the destination, can reference it
    dest_name = destinations[0] if destinations else None

    # Helper to build destination-aware messages
    def _dest_prefix(template_with: str, template_without: str) -> str:
        if dest_name:
            return template_with.replace("{dest}", dest_name)
        return template_without

    # Base prompts - professional and warm (only required fields)
    base_prompts = {
        "destinations": "Where are you looking to go?",
        "origin": "Where are you flying from?",
        "start_date": _dest_prefix(
            "When are you heading to {dest}?", "When are you looking to travel?"
        ),
    }

    # Quick booking - minimal, efficient
    quick_prompts = {
        "destinations": "Where to?",
        "origin": "Flying from?",
        "start_date": "When?",
    }

    # Adventurous - match energy but don't overdo
    adventurous_prompts = {
        "destinations": "Where is the adventure taking you?",
        "origin": "Where are you coming from?",
        "start_date": _dest_prefix("When are you heading to {dest}?", "When does the trip start?"),
        "end_date": "When do you need to be back?",
        "adults": "How many in your group?",
        "budget": "What is your budget?",
    }

    # Undecided - helpful guide
    undecided_prompts = {
        "destinations": (
            "Any destinations you have been thinking about? "
            "Or I can suggest some based on what you are in the mood for."
        ),
        "origin": _dest_prefix(
            "{dest} is a good choice. Where will you be traveling from?",
            "Where will you be traveling from?",
        ),
        "start_date": "Do you have any dates in mind?",
        "end_date": "Any idea when you would like to return?",
        "adults": "How many people are traveling?",
        "budget": "Do you have a rough budget in mind?",
    }

    # Short trip - acknowledge time constraints
    short_trip_prompts = {
        "destinations": "Where are you thinking for a quick trip?",
        "origin": _dest_prefix(
            "{dest} is great for a short trip. Where are you flying from?",
            "Where are you flying from?",
        ),
        "start_date": "When are you going?",
        "end_date": "When do you need to be back?",
        "adults": "How many travelers?",
        "budget": "Budget for this trip?",
    }

    # Select prompt set based on intent
    if user_intent == "quick_booking":
        prompts = quick_prompts
    elif user_intent == "adventurous":
        prompts = adventurous_prompts
    elif user_intent == "undecided":
        prompts = undecided_prompts
    elif user_intent == "short_trip":
        prompts = short_trip_prompts
    else:
        prompts = base_prompts

    # Find first missing required field
    for required_field in _REQUIRED_TRIP_INPUT_FIELDS:
        if required_field in missing_fields:
            question = prompts.get(required_field, base_prompts.get(required_field))
            if question:
                # Adjust for frustrated tone - be more direct, skip embellishments
                if user_tone == "frustrated":
                    # Use simpler, direct phrasing
                    question = quick_prompts.get(required_field, question)
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
) -> str:
    """Generate a natural language summary of recent conversation for suggestion context.

    Args:
        chat_history: List of {role, content} message dicts
        max_turns: Maximum number of turns to include (default 5)

    Returns:
        Natural language summary of recent conversation context
    """
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

    return " → ".join(summary_parts)


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
    booking_types: Dict[str, bool] = Field(default_factory=dict)
    flight_settings: Dict[str, Any] = Field(default_factory=dict)
    hotel_settings: Dict[str, Any] = Field(default_factory=dict)
    activity_settings: Dict[str, Any] = Field(default_factory=lambda: {"categories": []})
    transport_settings: Dict[str, Any] = Field(default_factory=dict)
    # Strategy-specific persisted preferences (per topic)
    strategy_settings: Dict[str, Any] = Field(default_factory=dict)

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
    {"destinations", "origin", "dates", "travelers", "budget", "activities", "general", None}
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
    errors: List[str] = Field(default_factory=list)
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

    return "\n".join(parts) if parts else "No trip details recorded yet."


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


def capture_pre_turn_snapshot(state: "GraphState") -> Dict[str, Any]:
    """Capture a snapshot of trip_inputs at the start of a turn.

    This snapshot is used to detect state regression and enable recovery.
    Should be called once at the beginning of each turn.
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

    # Generate recovery response
    known_info = _summarize_trip_inputs_for_recovery(error.pre_turn_snapshot)
    state.last_summary = (
        f"I may have lost track of some details. Here's what I have:\n\n"
        f"{known_info}\n\n"
        f"Is this correct, or would you like to update anything?"
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
                if isinstance(err, NormalizationError) and err.code in DATE_BLOCKING_ERROR_CODES:
                    has_blocking_date_errors = True
                    break
                if isinstance(err, str) and any(code in err for code in DATE_BLOCKING_ERROR_CODES):
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
        state.last_summary = (
            f"I want to make sure I have your trip details right. Here's what I have:\n\n"
            f"{known_info}\n\n"
            f"Does this look correct? Feel free to update or add anything."
        )
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


# =============================================================================
# STRATEGY EXPANSION DETECTION (Phase 1: Section-based expansion)
# =============================================================================
# Maps user phrases to specific expansion targets and output tiers.
# Section expansions use SECTION tier (768 tokens), full requests use FULL tier (2048).

# Patterns that trigger FULL tier (user explicitly wants everything)
_FULL_EXPANSION_TRIGGERS = frozenset(
    {
        "full itinerary",
        "full plan",
        "complete itinerary",
        "complete plan",
        "everything",
        "all the details",
        "the whole thing",
        "entire itinerary",
        "detailed plan",  # "detailed" implies comprehensive
    }
)

# Section-specific patterns -> (StrategyExpansionTarget, StrategyTier)
_SECTION_EXPANSION_PATTERNS: Dict[str, Tuple["StrategyExpansionTarget", "StrategyTier"]] = {
    # Day details
    "day 1": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    "day 2": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    "day 3": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    "day 4": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    "day 5": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    "first day": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    "second day": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    "third day": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    "expand day": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    "day-by-day": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    "daily breakdown": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    "daily schedule": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    # Routes and trails
    "routes": (StrategyExpansionTarget.ROUTES_TRAILS, StrategyTier.SECTION),
    "trails": (StrategyExpansionTarget.ROUTES_TRAILS, StrategyTier.SECTION),
    "trail": (StrategyExpansionTarget.ROUTES_TRAILS, StrategyTier.SECTION),
    "hikes": (StrategyExpansionTarget.ROUTES_TRAILS, StrategyTier.SECTION),
    "paths": (StrategyExpansionTarget.ROUTES_TRAILS, StrategyTier.SECTION),
    "route options": (StrategyExpansionTarget.ROUTES_TRAILS, StrategyTier.SECTION),
    "alternative routes": (StrategyExpansionTarget.ROUTES_TRAILS, StrategyTier.SECTION),
    # Logistics
    "logistics": (StrategyExpansionTarget.LOGISTICS, StrategyTier.SECTION),
    "transport": (StrategyExpansionTarget.LOGISTICS, StrategyTier.SECTION),
    "transfers": (StrategyExpansionTarget.LOGISTICS, StrategyTier.SECTION),
    "getting there": (StrategyExpansionTarget.LOGISTICS, StrategyTier.SECTION),
    "how to get": (StrategyExpansionTarget.LOGISTICS, StrategyTier.SECTION),
    "timing": (StrategyExpansionTarget.LOGISTICS, StrategyTier.SECTION),
    # Budget
    "budget": (StrategyExpansionTarget.BUDGET, StrategyTier.SECTION),
    "cost": (StrategyExpansionTarget.BUDGET, StrategyTier.SECTION),
    "costs": (StrategyExpansionTarget.BUDGET, StrategyTier.SECTION),
    "price": (StrategyExpansionTarget.BUDGET, StrategyTier.SECTION),
    "pricing": (StrategyExpansionTarget.BUDGET, StrategyTier.SECTION),
    "money": (StrategyExpansionTarget.BUDGET, StrategyTier.SECTION),
    "expenses": (StrategyExpansionTarget.BUDGET, StrategyTier.SECTION),
    "cost breakdown": (StrategyExpansionTarget.BUDGET, StrategyTier.SECTION),
    # Gear and packing
    "gear": (StrategyExpansionTarget.GEAR_PACKING, StrategyTier.SECTION),
    "equipment": (StrategyExpansionTarget.GEAR_PACKING, StrategyTier.SECTION),
    "packing": (StrategyExpansionTarget.GEAR_PACKING, StrategyTier.SECTION),
    "pack list": (StrategyExpansionTarget.GEAR_PACKING, StrategyTier.SECTION),
    "packing list": (StrategyExpansionTarget.GEAR_PACKING, StrategyTier.SECTION),
    "what to bring": (StrategyExpansionTarget.GEAR_PACKING, StrategyTier.SECTION),
    "what to pack": (StrategyExpansionTarget.GEAR_PACKING, StrategyTier.SECTION),
    "rental gear": (StrategyExpansionTarget.GEAR_PACKING, StrategyTier.SECTION),
    # Contingencies
    "contingencies": (StrategyExpansionTarget.CONTINGENCIES, StrategyTier.SECTION),
    "backup": (StrategyExpansionTarget.CONTINGENCIES, StrategyTier.SECTION),
    "backup plan": (StrategyExpansionTarget.CONTINGENCIES, StrategyTier.SECTION),
    "weather": (StrategyExpansionTarget.CONTINGENCIES, StrategyTier.SECTION),
    "rain plan": (StrategyExpansionTarget.CONTINGENCIES, StrategyTier.SECTION),
    "rest days": (StrategyExpansionTarget.CONTINGENCIES, StrategyTier.SECTION),
    "alternatives": (StrategyExpansionTarget.CONTINGENCIES, StrategyTier.SECTION),
    "if it rains": (StrategyExpansionTarget.CONTINGENCIES, StrategyTier.SECTION),
}

# Generic expansion phrases (default to ITINERARY_OUTLINE at SECTION tier)
_GENERIC_EXPANSION_TRIGGERS = frozenset(
    {
        "expand",
        "show details",
        "show more details",
        "tell me more",
        "more details",
        "elaborate",
        "go deeper",
        "give me more",
    }
)


@dataclass
class StrategyExpansionResult:
    """Result of parsing user text for strategy expansion intent."""

    is_expansion: bool
    target: Optional[StrategyExpansionTarget] = None
    tier: Optional[StrategyTier] = None
    matched_phrase: Optional[str] = None


def _is_strategy_expansion_request(
    text: str,
) -> StrategyExpansionResult:
    """
    Parse user text for strategy expansion intent.

    Returns structured result with:
    - is_expansion: Whether user is requesting expansion
    - target: Which section to expand (DAY_DETAILS, ROUTES, BUDGET, etc.)
    - tier: Output tier (SECTION=768 tokens, FULL=2048 tokens)

    Only triggers on explicit phrases to avoid false positives.
    Implicit confirmations like "yes" or "let's do it" do NOT trigger expansion.

    Args:
        text: User text (will be lowercased)

    Returns:
        StrategyExpansionResult with expansion details
    """
    text_lower = text.lower().strip()

    # Check for FULL tier triggers first (user wants everything)
    for trigger in _FULL_EXPANSION_TRIGGERS:
        if trigger in text_lower:
            return StrategyExpansionResult(
                is_expansion=True,
                target=StrategyExpansionTarget.FULL_EXPANSION,
                tier=StrategyTier.FULL,
                matched_phrase=trigger,
            )

    # Check for section-specific patterns
    for pattern, (target, tier) in _SECTION_EXPANSION_PATTERNS.items():
        if pattern in text_lower:
            return StrategyExpansionResult(
                is_expansion=True,
                target=target,
                tier=tier,
                matched_phrase=pattern,
            )

    # Check for generic expansion triggers (default to ITINERARY_OUTLINE)
    for trigger in _GENERIC_EXPANSION_TRIGGERS:
        if trigger in text_lower:
            return StrategyExpansionResult(
                is_expansion=True,
                target=StrategyExpansionTarget.ITINERARY_OUTLINE,
                tier=StrategyTier.SECTION,
                matched_phrase=trigger,
            )

    # No expansion detected
    return StrategyExpansionResult(is_expansion=False)


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

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
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

    # Gate verified = routing was done by KEYWORD_HEURISTIC or QUESTION_KEYWORD gate
    gate_verified = metadata.get("router_bypassed", False) and metadata.get("first_gate_fired") in (
        "KEYWORD_HEURISTIC",
        "QUESTION_KEYWORD",
        GatePrecedence.KEYWORD_HEURISTIC.name,
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
_STREAM_BASE_DELAY_MS = 15  # Starting delay per token (fast burst)
_STREAM_MAX_DELAY_MS = 35  # Maximum delay per token (deceleration cap)
_STREAM_ACCEL_FACTOR = 0.015  # How quickly delay increases per token
_STREAM_JITTER_MS = 8  # Random variance for organic feel


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


def _truncate_to_balanced_json(raw: str) -> Optional[str]:
    """
    Extract a valid JSON object from a potentially truncated or malformed string.

    LLMs sometimes return incomplete JSON or include extra text before/after the JSON.
    This function finds the first complete, balanced JSON object in the string.
    """
    start_idx = None
    brace_count = 0
    in_string = False
    escape = False
    last_valid_idx = -1

    for idx, ch in enumerate(raw):
        if start_idx is None:
            if ch == "{":
                start_idx = idx
                brace_count = 1
            continue

        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            brace_count += 1
        elif ch == "}":
            brace_count -= 1
            if brace_count == 0:
                last_valid_idx = idx
                break

    if start_idx is not None and last_valid_idx >= start_idx:
        return raw[start_idx : last_valid_idx + 1]
    return None


def jloads_safe(s: str) -> Dict[str, Any]:
    """
    Parse JSON with multiple fallback strategies for malformed input.

    Tries progressively more lenient parsing approaches:
    1. Standard json.loads() - works for well-formed JSON
    2. Non-strict mode - allows some escape sequence issues
    3. Truncation recovery - extracts balanced JSON from garbage
    4. Last resort: find { and } brackets

    Returns empty dict on failure (matches plan.py's _tolerant_json_loads behavior).
    """
    if not s:
        return {}

    # Try standard parsing first
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    # Try non-strict mode (allows some escape sequence issues)
    try:
        return json.loads(s, strict=False)
    except Exception:
        pass

    # Try extracting balanced JSON from garbage
    trimmed = _truncate_to_balanced_json(s)
    if trimmed:
        try:
            return json.loads(trimmed, strict=False)
        except json.JSONDecodeError:
            pass

    # Last resort: find { and } brackets
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(s[start : end + 1], strict=False)
        except json.JSONDecodeError:
            pass

    # Return empty dict on failure (matching plan.py's _tolerant_json_loads)
    _debug_error("JSON parse failed", raw=s[:100] if len(s) > 100 else s)
    return {}


def ti_short(ti: TripInputs) -> Dict[str, Any]:
    return ti.model_dump(exclude_none=True)


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
        Destinations + dates + activity context + strategy settings.
        """
        ti = state.trip_inputs
        view = {
            "destinations": ti.destinations or [],
            "start_date": ti.start_date,
            "end_date": ti.end_date,
            "adults": ti.adults,
            "children": ti.children,
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


def _record_structured_error(
    state: GraphState,
    code: str,
    node: str,
    message: str,
    severity: str = "error",
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
        severity: "error", "warning", or "info"
    """
    state.errors.append(
        {
            "code": code,
            "node": node,
            "severity": severity,
            "message": message,
        }
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
        severity="error",
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


# Strategy topic detection patterns - use word boundaries to avoid false positives
# e.g., "skippered" should not match "ski"
_STRATEGY_TOPIC_PATTERNS = {
    "hiking": re.compile(r"\b(?:hik(?:e|ing)|trek(?:king)?)\b", re.IGNORECASE),
    "diving": re.compile(r"\b(?:div(?:e|ing)|scuba|snorkel(?:ing)?)\b", re.IGNORECASE),
    "skiing": re.compile(r"\b(?:ski(?:ing)?|snowboard(?:ing)?)\b", re.IGNORECASE),
    "cycling": re.compile(r"\b(?:cycl(?:e|ing)|bik(?:e|ing)|bicycle)\b", re.IGNORECASE),
    "boating": re.compile(r"\b(?:boat(?:ing)?|sail(?:ing)?|yacht(?:ing)?)\b", re.IGNORECASE),
}


def _detect_strategy_topic_from_text(text: str) -> Optional[str]:
    """
    Detect strategy topic from user text using word boundary patterns.

    Returns the first matched topic or None.
    Uses regex word boundaries to avoid false positives like 'skippered' matching 'ski'.
    """
    if not text:
        return None

    for topic, pattern in _STRATEGY_TOPIC_PATTERNS.items():
        if pattern.search(text):
            return topic
    return None


# =============================================================================
# STRATEGY BOOTSTRAP BYPASS: Deterministic bypass of extractor LLM
# =============================================================================
# Constants for bypass safety guards
_BYPASS_MAX_TEXT_LENGTH = 150  # Skip bypass for long/dense prompts
_BYPASS_CONSTRAINT_PATTERNS = {
    "dates": re.compile(
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|"
        r"january|february|march|april|june|july|august|september|october|november|december|"
        r"next\s+(?:week|month|year)|this\s+(?:week|month|year)|"
        r"\d{1,2}[/-]\d{1,2}|\d{4})\b",
        re.IGNORECASE,
    ),
    "budget": re.compile(
        r"\$\d+|€\d+|£\d+|\d+\s*(?:dollars|euros|pounds|usd|eur|gbp)|budget\s+(?:is|of|\d)",
        re.IGNORECASE,
    ),
    "travelers": re.compile(
        r"\b(?:\d+\s*(?:adults?|people|persons?|travelers?|of\s+us)|"
        r"(?:just\s+)?me|solo|alone|couple|family)\b",
        re.IGNORECASE,
    ),
}

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
        hash_val = hash(session_id) % 100
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
    for constraint_type, pattern in _BYPASS_CONSTRAINT_PATTERNS.items():
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
    for t, pattern in _STRATEGY_TOPIC_PATTERNS.items():
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
        "constraint_tokens": {k: False for k in _BYPASS_CONSTRAINT_PATTERNS.keys()},
    }


# -----------------------
# Cheap extractor (code) - enhanced with patterns from plan.py
# -----------------------
async def extractor(state: GraphState) -> GraphState:
    """
    Extract structured data from user text using LLM.

    All trip input extraction (destinations, origin, dates, travelers, budget,
    activities, settings) is performed by the LLM for robust natural language
    understanding.

    SHORT-CIRCUITS (bypasses LLM entirely via short_circuit_responder):
    - Greetings: "hi", "hello", "hey" -> random greeting + destination question
    - Acknowledgments: "ok", "thanks", "got it" -> continue flow
    - Confirmations: "yes"/"no" with pending_action -> execute or clear action
    - Off-topic: weather, math, general knowledge -> redirect to travel
    """
    _debug_node_entry("extractor", state)

    text = state.user_text
    parsed: Dict[str, Any] = {}

    # Check for generate plan trigger
    if _is_generate_plan_trigger(text):
        state.flags["generate_requested"] = True
        state.flags["generate_plan"] = True
        _debug("Generate plan trigger detected")
        state.parsed_inputs = parsed
        _debug_node_exit("extractor", state)
        return state

    # =========================================================================
    # SHORT-CIRCUIT DETECTION
    # Keep lightweight short-circuits for greetings, acknowledgments, etc.
    # These save LLM tokens for trivial inputs.
    # =========================================================================
    short_circuit = _detect_short_circuit(text, state)
    if short_circuit:
        sc_type = short_circuit["type"]
        _debug(f"Short-circuit detected: {sc_type}", input=text[:30] if len(text) > 30 else text)

        state.flags["short_circuit"] = sc_type
        state.flags["short_circuit_response"] = short_circuit.get("response")
        state.flags["short_circuit_action"] = short_circuit.get("action")

        # If short-circuit extracted parsed data, merge it
        sc_parsed = short_circuit.get("parsed")
        if sc_parsed:
            parsed.update(sc_parsed)
            _debug("Short-circuit parsed data", parsed=sc_parsed)

        # For confirmations that trigger actions, handle them
        if short_circuit.get("action") == "generate_plan":
            state.flags["generate_requested"] = True
            state.flags["generate_plan"] = True
            _debug("Short-circuit triggered generate_plan")
        elif short_circuit.get("action") == "apply_typo_corrections":
            # Apply the stored typo corrections to trip_inputs
            typo_corrections = (sc_parsed or {}).get("typo_corrections", {})
            if typo_corrections:
                _apply_typo_corrections(state, typo_corrections)
            state.metadata.pop("pending_action", None)
            state.metadata.pop("pending_typo_corrections", None)
            _debug("Short-circuit applied typo corrections", corrections=typo_corrections)
        elif short_circuit.get("action") == "clear_pending":
            state.metadata.pop("pending_action", None)
            state.metadata.pop("pending_typo_corrections", None)
            _debug("Short-circuit cleared pending_action")

        state.parsed_inputs = parsed
        _debug_node_exit("extractor", state)
        return state

    # =========================================================================
    # STRATEGY BOOTSTRAP BYPASS: Skip extractor LLM for strategy pre-core
    # =========================================================================
    # When user enters a simple strategy prompt like "Plan a hiking trip",
    # we can deterministically detect the topic and bypass the extractor LLM,
    # routing directly to strategy_node stage0. This saves one LLM call.
    #
    # Safety gates to avoid bad routing:
    # 1. Feature flag enabled (settings.enable_strategy_bootstrap_bypass)
    # 2. No question_target (first turn or open-ended)
    # 3. Core fields are empty (destinations, dates not set)
    # 4. Strategy topic detected in text
    # 5. No place-like entities detected (avoid missing destination in "Hiking in Alps")
    # 6. Short text (< 150 chars) - dense prompts need full extraction
    # 7. No constraint tokens (dates, budget, travelers)
    # 8. No multi-intent (multiple specialists or topics)
    # =========================================================================
    bypass_result = _try_strategy_bootstrap_bypass(text, state)
    if bypass_result:
        # Bypass succeeded - set strategy_topic and route to STRATEGY_PRE_CORE_VALUE
        state.strategy_topic = bypass_result["topic"]
        state.flags["strategy_bootstrap_bypass"] = True
        state.flags["strategy_bootstrap_active"] = True  # BUG FIX: explicit boolean
        state.flags["fast_path"] = True
        state.flags["fast_path_field"] = "strategy_bootstrap"
        set_response_provenance(state, "deterministic")  # For polish skipping

        # Set minimal trip_shape fields deterministically
        if bypass_result.get("trip_style"):
            _write_trip_inputs(
                state, "extractor", trip_style=bypass_result["trip_style"]
            )  # Ignore fields_changed
        if bypass_result.get("activity_categories"):
            _write_trip_inputs(
                state, "extractor", activity_categories=bypass_result["activity_categories"]
            )  # Ignore fields_changed

        # Record bypass observability
        state.metadata["bypass_variant"] = bypass_result.get("variant", "bypass")
        state.metadata["bypass_observability"] = {
            "bypass_attempted": True,
            "bypass_taken": True,
            "bypass_reject_reasons": [],
            "place_detected_by": bypass_result.get("place_detected_by", "none"),
            "constraint_tokens": bypass_result.get("constraint_tokens", {}),
            "invariant_check_passed": True,
        }

        # Set question_target to dates for stage0
        state.metadata["question_target"] = "dates"

        _debug(
            "Strategy bootstrap bypass: skipping extractor LLM",
            topic=bypass_result["topic"],
            trip_style=bypass_result.get("trip_style"),
        )

        state.parsed_inputs = parsed
        _debug_node_exit("extractor", state)
        return state

    # =========================================================================
    # NOTE: Fast-path extraction is now handled by lqa_prepass node which runs
    # BEFORE extractor. If we reach here, either LQA wasn't applicable or it
    # bailed, so we proceed directly to initial message extraction or LLM.
    # =========================================================================

    # =========================================================================
    # PHASE 6: ZERO-LLM INITIAL MESSAGE EXTRACTION
    # Handle simple initial messages like "I want to go to Paris" or
    # "2 adults, Paris, next month" without LLM even when question_target is not set.
    # Saves ~1145 tokens on first turn for simple requests.
    # =========================================================================
    initial_result = _try_initial_message_extraction(text, state)
    if initial_result:
        init_fields = initial_result["fields"]
        init_parsed = initial_result["parsed"]
        _debug(
            f"Zero-LLM initial extraction success: {init_fields}",
            parsed=init_parsed,
            input=text[:50] if len(text) > 50 else text,
        )

        # Set fast-path flag for routing (reuse same routing path)
        state.flags["fast_path"] = True
        state.flags["fast_path_field"] = init_fields[0] if init_fields else "multi"

        # Merge parsed data
        parsed.update(init_parsed)

        # Set high confidence since we matched deterministically
        state.metadata["extraction_confidence"] = {
            "overall": 0.92,
            "level": "high",
            "method": "initial_extraction",
            "grammar_matched": True,
            "is_english": True,
            "detected_language": None,
            "low_confidence_reasons": [],
            "typo_suggestions": {},
        }

        # Record path trace for metrics
        state.metadata["extraction_path"] = f"initial:{','.join(init_fields)}"

        # Set strategy_topic from user text before returning (for topic-aware suggestions)
        if not state.strategy_topic and text:
            state.strategy_topic = _detect_strategy_topic_from_text(text)
            if state.strategy_topic:
                _debug(
                    "Strategy topic set from user text (initial extraction path)",
                    topic=state.strategy_topic,
                )

        state.parsed_inputs = parsed
        _debug_node_exit("extractor", state)
        return state

    # =========================================================================
    # LLM-BASED EXTRACTION (Light or Full mode)
    # Light mode: Core fields only (~128 tokens) - used for early/simple turns
    # Full mode: All fields (~400 tokens) - used for dense input or near-ready
    # =========================================================================

    # Determine extraction mode
    is_dense, dense_reason = _is_dense_input(text, state)
    extractor_mode = "full" if is_dense else "light"

    # Record path trace for metrics
    state.metadata["extraction_path"] = f"llm:{extractor_mode}"
    state.metadata["extractor_mode"] = extractor_mode
    state.metadata["extractor_mode_reason"] = dense_reason

    # =========================================================================
    # EXTRACTOR CACHE CHECK (60s TTL, turn-level dedup)
    # Key: (session_id, user_text, core_fields_hash, mode)
    # Saves ~500-1000 tokens when user sends identical message
    # =========================================================================
    session_id = state.session_id or "unknown"
    core_fields_hash = _get_core_fields_state(state.trip_inputs)

    cached_extraction = _get_extractor_cached(
        session_id, text, core_fields_hash, extractor_mode, state
    )
    if cached_extraction is not None:
        _debug(
            "📦 EXTRACTOR_CACHE_HIT: Using cached extraction",
            mode=extractor_mode,
            cache_key_prefix=f"{session_id[:8]}...",
            tokens_saved="~500-1000 (LLM call avoided)",
        )
        # Restore cached state
        state.parsed_inputs = cached_extraction.get("parsed", {})
        state.metadata["extraction_confidence"] = cached_extraction.get("confidence", {})
        state.metadata["extraction_path"] = f"cache:{extractor_mode}"
        _debug_node_exit("extractor", state)
        return state

    # Select config and prompt based on mode
    if extractor_mode == "light":
        llm_config = _get_node_llm_config("extractor_light")
        prompt_name = "extractor_light"
        _debug(
            "Extractor using LIGHT mode",
            reason=dense_reason,
            max_tokens=llm_config["max_tokens"],
        )
    else:
        llm_config = _get_node_llm_config("extractor")
        prompt_name = "extractor"
        _debug(
            "Extractor using FULL mode",
            reason=dense_reason,
            max_tokens=llm_config["max_tokens"],
        )

    today_iso = state.metadata.get("today_iso") or _today_iso()

    try:
        prompt = load_prompt(prompt_name)

        # Light mode uses simpler template (no trip_inputs context needed)
        if extractor_mode == "light":
            tpl = prompt.replace("{today}", today_iso).replace("{user_text}", text)
        else:
            tpl = (
                prompt.replace("{today}", today_iso)
                .replace("{trip_inputs}", json.dumps(ti_short(state.trip_inputs)))
                .replace("{user_text}", text)
            )

        tokens = _estimate_prompt_tokens(tpl, state.parsed_inputs)
        _record_node_tokens(
            state, f"extractor:{extractor_mode}", tokens, model=llm_config["model_hint"]
        )

        import time as _time

        _llm_start = _time.perf_counter()
        out = await call_llm_with_timeout(
            model=llm_config["model_hint"],
            prompt=tpl,
            timeout_seconds=settings.llm_timeout_extractor,
            max_tokens=llm_config["max_tokens"],
            temperature=llm_config["temperature"],
        )
        _record_llm_time(state, (_time.perf_counter() - _llm_start) * 1000)
        _increment_llm_calls(state)
        extracted = jloads_safe(out)

        # Map LLM output to parsed_inputs format
        if extracted.get("destinations_delta"):
            parsed["destinations_delta"] = extracted["destinations_delta"]
        if extracted.get("origin_delta"):
            parsed["origin_delta"] = extracted["origin_delta"]
        if extracted.get("start_date_hint"):
            parsed["start_date_hint"] = extracted["start_date_hint"]
        if extracted.get("end_date_hint"):
            parsed["end_date_hint"] = extracted["end_date_hint"]
        if extracted.get("duration_days"):
            parsed["duration_days"] = extracted["duration_days"]
        if extracted.get("adults_delta") is not None:
            parsed["adults_delta"] = extracted["adults_delta"]
        if extracted.get("children_delta") is not None:
            parsed["children_delta"] = extracted["children_delta"]
        if extracted.get("requires_assistance_delta") is not None:
            parsed["requires_assistance_delta"] = extracted["requires_assistance_delta"]
        if extracted.get("budget_delta"):
            parsed["budget_delta"] = extracted["budget_delta"]
        if extracted.get("multi_city_intent_delta"):
            parsed["multi_city_intent_delta"] = extracted["multi_city_intent_delta"]
        if extracted.get("category_activation"):
            parsed["category_activation"] = extracted["category_activation"]
        if extracted.get("flight_settings_delta"):
            parsed["flight_settings_delta"] = extracted["flight_settings_delta"]
        if extracted.get("hotel_settings_delta"):
            parsed["hotel_settings_delta"] = extracted["hotel_settings_delta"]
        if extracted.get("transport_settings_delta"):
            parsed["transport_settings_delta"] = extracted["transport_settings_delta"]
        if extracted.get("activity_categories_delta"):
            # Map to inferred_activity_categories for normalize_inputs
            parsed["inferred_activity_categories"] = extracted["activity_categories_delta"]
        if extracted.get("strategy_hint"):
            parsed["strategy_hint"] = extracted["strategy_hint"]

        # Store LLM-reported confidence in metadata
        confidence_score = extracted.get("confidence", 0.8)
        confidence_reasons = extracted.get("confidence_reasons") or []

        # Determine confidence level based on score
        if confidence_score >= 0.8:
            confidence_level = "high"
        elif confidence_score >= 0.5:
            confidence_level = "medium"
        else:
            confidence_level = "low"

        state.metadata["extraction_confidence"] = {
            "overall": confidence_score,
            "level": confidence_level,
            "method": "llm",
            "grammar_matched": False,  # Not applicable for LLM extraction
            "is_english": True,  # LLM handles multilingual
            "detected_language": None,
            "low_confidence_reasons": confidence_reasons,
            "typo_suggestions": {},
        }

        # Cache the extraction result for future identical requests (60s TTL)
        _set_extractor_cached(
            session_id,
            text,
            core_fields_hash,
            extractor_mode,
            {
                "parsed": parsed,
                "confidence": state.metadata["extraction_confidence"],
            },
        )

        _debug(
            "Extraction confidence calculated",
            overall=f"{confidence_score:.2f}",
            level=confidence_level,
            method="llm",
            grammar_matched=False,
            reasons=confidence_reasons[:3] if confidence_reasons else None,
        )

    except TimeoutError:
        _debug("Extractor LLM timeout, using empty parsed_inputs")
        state.metadata["extraction_confidence"] = {
            "overall": 0.0,
            "level": "low",
            "method": "llm_timeout",
            "grammar_matched": False,
            "is_english": True,
            "detected_language": None,
            "low_confidence_reasons": ["llm_timeout"],
            "typo_suggestions": {},
        }
    except Exception as e:
        _debug_error("Extractor LLM error", error=str(e))
        state.metadata["extraction_confidence"] = {
            "overall": 0.0,
            "level": "low",
            "method": "llm_error",
            "grammar_matched": False,
            "is_english": True,
            "detected_language": None,
            "low_confidence_reasons": ["llm_error"],
            "typo_suggestions": {},
        }

    state.parsed_inputs = parsed

    # =========================================================================
    # EARLY STRATEGY_TOPIC DETECTION
    # Set strategy_topic from activity_settings or user text keywords so
    # templates can use topic-aware suggestions on first turn.
    # =========================================================================
    if not state.strategy_topic:
        # First try to derive from activity_settings categories
        categories = getattr(state.trip_inputs.activity_settings, "categories", None) or []
        for cat in categories:
            detected = _detect_strategy_topic_from_text(cat)
            if detected:
                state.strategy_topic = detected
                _debug(
                    "Strategy topic set from activity_settings",
                    topic=detected,
                    category=cat,
                )
                break

        # If still not set, check user text for topic keywords (with word boundaries)
        if not state.strategy_topic and text:
            state.strategy_topic = _detect_strategy_topic_from_text(text)
            if state.strategy_topic:
                _debug(
                    "Strategy topic set from user text",
                    topic=state.strategy_topic,
                )

    _debug_node_exit("extractor", state)
    return state


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
    _debug_node_entry("normalize_inputs", state)

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
            _debug_node_exit("normalize_inputs", state)
            return state

    parsed = state.parsed_inputs or {}
    ti = state.trip_inputs  # Read-only reference for reading current values

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
        family_match = _FAMILY_COMPOSITION_PATTERN.search(text_lower)
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
        budget_match = _INLINE_BUDGET_PATTERN.search(user_text.lower())
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
    # USE TripInputNormalizer FOR UNIFIED NORMALIZATION
    # =========================================================================
    # This is the SINGLE normalization pass. All field normalization, validation,
    # and error collection happens here via TripInputNormalizer.

    # Pass turn number for provenance tracking
    parsed["_turn_number"] = state.turn_number
    updates, norm_errors = _trip_normalizer.normalize_all(ti, parsed, user_text=user_text)

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
                        notifications.append(
                            f"I'll assume {readable} for the start date—"
                            "let me know if you meant a different day."
                        )
            elif "end_date" in notif:
                end_iso = updates.get("end_date") or ti.end_date
                if end_iso:
                    dt = _parse_iso_date(end_iso)
                    if dt:
                        readable = dt.strftime("%B %d, %Y")
                        notifications.append(
                            f"I'll assume {readable} for the end date—"
                            "let me know if you meant a different day."
                        )
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
    # Requires TWO signals to avoid false positives:
    # 1. Additive marker (too/also/as well) in user text
    # 2. Destination count increased from prior state
    #
    # Single "too" without destination increase is ignored (user might say
    # "too hot" or "me too" casually).
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
                # Check user text for additive phrases
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

    # Apply all updates via the helper (this does ownership checking and deep copy)
    if updates:
        _write_trip_inputs(state, "normalize_inputs", **updates)  # Ignore fields_changed
        _debug(
            "normalize_inputs applied updates via _write_trip_inputs", fields=list(updates.keys())
        )

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

    _debug_node_exit("normalize_inputs", state)
    return state


# -----------------------
# Router (small LLM) - no retry, uses timeout
# -----------------------
async def router(state: GraphState) -> GraphState:
    """
    Router node to determine intent. Uses timeout but NO retry (router should be fast and reliable).
    Also refines user intent classification for conversational style adaptation.
    """
    _debug_node_entry("router", state)

    # Get per-node LLM configuration
    llm_config = _get_node_llm_config("router")

    # Check cache first - router decisions are stable for same inputs
    core_fields = _get_core_fields_state(state.trip_inputs)
    user_text_hash = _hash_user_text(state.user_text or "")
    cache_key = _compute_cache_key("router", core_fields, "", user_text_hash)
    cached = _get_cached_response(_follow_up_cache, cache_key, state)
    if cached is not None:
        _debug_cache_hit("router", cache_key[:16])
        state.intent = cached.get("intent") or "required_fields"
        state.strategy_topic = cached.get("strategy_topic")
        state.metadata["router_notes"] = cached.get("notes", "")
        state.metadata["router_confidence"] = cached.get("confidence", 1.0)
        state.metadata["router_path"] = "cache"
        if cached.get("user_intent"):
            state.metadata["user_intent"] = cached["user_intent"]
        _debug("Router cache hit", intent=state.intent, topic=state.strategy_topic)
        _debug_node_exit("router", state)
        return state

    try:
        prompt = load_prompt("router")
        # Include user intent hint from extractor for router to refine
        user_intent_hint = state.metadata.get("user_intent_hint", "")

        # Use minimal state view for router (saves ~75% tokens vs full trip_inputs)
        router_state_view = StateViewBuilder.for_router(state)

        tpl = (
            prompt.replace("{parsed_inputs}", json.dumps(state.parsed_inputs))
            .replace("{trip_inputs}", json.dumps(router_state_view))
            .replace("{user_intent_hint}", user_intent_hint or "none")
        )

        tokens = _estimate_prompt_tokens(tpl, state.parsed_inputs)
        _record_node_tokens(state, "router", tokens, model=llm_config["model_hint"])

        import time as _time

        _llm_start = _time.perf_counter()
        out = await call_llm_with_timeout(
            model=llm_config["model_hint"],
            prompt=tpl,
            timeout_seconds=settings.llm_timeout_router,
            max_tokens=llm_config["max_tokens"],
            temperature=llm_config["temperature"],
        )
        _record_llm_time(state, (_time.perf_counter() - _llm_start) * 1000)
        _increment_llm_calls(state)
        j = jloads_safe(out)
        state.intent = j.get("intent") or "required_fields"
        topic = j.get("topic") or state.parsed_inputs.get("strategy_hint")
        state.strategy_topic = topic if state.intent == "strategy" else None
        state.metadata["router_notes"] = j.get("notes", "")
        state.metadata["router_confidence"] = j.get("confidence", 1.0)

        # Cache the router result for future identical requests
        _set_cached_response(
            _follow_up_cache,
            cache_key,
            {
                "intent": state.intent,
                "strategy_topic": state.strategy_topic,
                "notes": state.metadata.get("router_notes", ""),
                "confidence": state.metadata.get("router_confidence", 1.0),
                "user_intent": j.get("user_intent"),
            },
        )

        # Handle off-topic intent with friendly deflection
        if state.intent == "off_topic":
            state.last_summary = _random_module.choice(_OFF_TOPIC_DEFLECTIONS)
            state.metadata["last_question_field"] = "destinations"
            _debug("Off-topic detected, deflecting to travel", response=state.last_summary[:50])
            _debug_node_exit("router", state)
            return state

        # Capture refined user intent from router (if provided)
        router_user_intent = j.get("user_intent")
        if router_user_intent and router_user_intent in USER_INTENT_ARCHETYPES:
            # Router refined the intent - update if different from extractor hint
            current_intent = state.metadata.get("user_intent")
            if router_user_intent != current_intent:
                _debug(
                    "Router refined user intent",
                    from_intent=current_intent,
                    to_intent=router_user_intent,
                )
                state.metadata["user_intent"] = router_user_intent
                state.metadata["intent_turn_count"] = 1
                state.metadata["intent_confidence"] = 1.0

        _debug(
            "Router result",
            intent=state.intent,
            confidence=state.metadata.get("router_confidence"),
            topic=state.strategy_topic,
            user_intent=state.metadata.get("user_intent"),
        )

        prev_intent = state.metadata.get("last_intent")
        no_progress_turns = state.metadata.get("no_progress_turns", 0)
        if state.intent == "required_fields" and prev_intent == "required_fields":
            no_progress_turns += 1
        else:
            no_progress_turns = 0
        state.metadata["no_progress_turns"] = no_progress_turns
        state.metadata["last_intent"] = state.intent

        _debug_node_exit("router", state)
        return state
    except Exception as exc:
        # Router failure is not critical - default to required_fields for conversational flow
        _debug_error("Router failed, defaulting to required_fields", error=str(exc))
        state.intent = "required_fields"
        state.metadata["router_notes"] = f"Router error: {exc}"
        _debug_node_exit("router", state)
        return state


# -----------------------
# Specialists (shared handler)
# -----------------------


def _select_required_fields_prompt(state: GraphState) -> str:
    """
    Select the appropriate prompt for required_fields based on state.

    Returns either:
    - required_fields_confirm: when typos/ambiguities need user confirmation
    - required_fields: for all other cases (collecting missing fields or confirming ready state)
    """
    # Check for typos or ambiguous entities needing confirmation
    extraction_conf = state.metadata.get("extraction_confidence", {})
    typo_suggestions = extraction_conf.get("typo_suggestions", [])

    if typo_suggestions:
        # Use confirmation prompt for typo/ambiguity resolution
        return load_prompt("required_fields_confirm")

    # Check if budget needs clarification (qualitative value was dropped)
    prompt = load_prompt("required_fields")
    if state.metadata.get("budget_needs_clarification"):
        # Clear the flag and inject budget question
        state.metadata["budget_needs_clarification"] = False
        state.question_target = "budget"
        prompt += (
            "\n\nIMPORTANT: The user provided a qualitative budget description."
            " Ask them for an approximate budget in dollars/their currency."
        )

    return prompt


async def _invoke_missing_fields_guard(state: GraphState, missing_fields: List[str]) -> bool:
    """
    Invoke the lightweight missing_fields_guard prompt to generate a question.

    This is called when a domain specialist is entered but core fields are missing.
    Uses a small model for minimal latency.

    Args:
        state: Current graph state (will be mutated with response)
        missing_fields: List of missing core field names

    Returns:
        True if guard was successful and state was updated, False on error
    """
    llm_config = _get_node_llm_config("missing_fields_guard")

    # Generate tone instruction using ToneAdapter (replaces _adapt_tone.txt include)
    user_intent = state.metadata.get("user_intent", "detailed_planner")
    user_tone = state.metadata.get("user_tone", "neutral")
    tone_instruction = ToneAdapter.get_instruction(user_intent, user_tone)

    prompt = load_prompt("missing_fields_guard")
    system_prompt = (
        prompt.replace("{missing_fields}", ", ".join(missing_fields))
        .replace("{trip_inputs}", json.dumps(ti_short(state.trip_inputs)))
        .replace("{tone_instruction}", tone_instruction)
    )

    tokens = _count_tokens(system_prompt)
    _record_node_tokens(state, "missing_fields_guard", tokens, model=llm_config["model_hint"])

    # LLM Budget Gate: Return fallback if budget exhausted
    if not can_call_llm(state, "missing_fields_guard"):
        # Determine best fallback target from missing_fields
        if "dates" in missing_fields or "start_date" in missing_fields:
            fallback_target = "dates"
        elif "destinations" in missing_fields:
            fallback_target = "destinations"
        elif "origin" in missing_fields:
            fallback_target = "origin"
        else:
            fallback_target = missing_fields[0] if missing_fields else "dates"
        _debug(
            f"⚠️ missing_fields_guard: LLM budget exhausted, using fallback for {fallback_target}",
            missing_fields=missing_fields,
        )
        llm_blocked_fallback(
            state, asked_target=fallback_target, source="missing_fields_guard:budget_blocked"
        )
        return True

    import time as _time

    # Check if we're in date_clarify_mode - if so, force dates question
    in_date_clarify_mode = state.metadata.get("date_clarify_mode", False)
    has_blocking_errors = bool(state.metadata.get("date_blocking_errors"))

    try:
        _llm_start = _time.perf_counter()
        out = await call_llm_with_timeout(
            model=llm_config["model_hint"],
            prompt=system_prompt,
            timeout_seconds=settings.llm_timeout_specialist,
            max_tokens=llm_config["max_tokens"],
            temperature=llm_config["temperature"],
            history=[],
            user_message="",
            top_p=llm_config["top_p"],
        )
        _record_llm_time(state, (_time.perf_counter() - _llm_start) * 1000)
        _increment_llm_calls(state)

        j = jloads_safe(out)

        state.last_summary = j.get("assistant_message", "Where would you like to go?")
        state.suggested_responses = j.get("suggested_responses", [])[:3]
        llm_question_target = j.get(
            "question_target", missing_fields[0] if missing_fields else None
        )

        # Enforce date_clarify_mode: refuse field switching when dates have blocking errors
        if in_date_clarify_mode or has_blocking_errors:
            if llm_question_target and llm_question_target not in (
                "dates",
                "start_date",
                "end_date",
            ):
                _debug(
                    "Missing fields guard: refusing field switch during date_clarify_mode",
                    llm_target=llm_question_target,
                    forced_target="dates",
                )
                set_question_target(state, "dates", source="missing_fields_guard:date_clarify")
            else:
                set_question_target(state, llm_question_target, source="missing_fields_guard:llm")
        else:
            set_question_target(state, llm_question_target, source="missing_fields_guard:llm")

        # Map question_target to last_question_field for short-circuit context
        target_to_field = {
            "destinations": "destinations",
            "origin": "origin",
            "dates": "start_date",
            "start_date": "start_date",
        }
        state.metadata["last_question_field"] = target_to_field.get(
            state.question_target, state.question_target
        )

        # Track that response was produced this turn (no-stale-summary invariant)
        state.metadata["last_response_turn"] = state.turn_number

        _debug(
            "Missing fields guard response",
            response_preview=state.last_summary[:50] if state.last_summary else "",
            suggestions=state.suggested_responses,
        )
        return True

    except Exception as e:
        _debug_error("Missing fields guard failed", error=str(e))
        # Record error for proper accounting (errors_count)
        state.errors.append(
            {
                "code": "GUARD_LLM_FAILED",
                "node": "missing_fields_guard",
                "severity": "warning",
                "message": str(e),
            }
        )
        # Fallback to a simple question (deterministic recovery)
        if "destinations" in missing_fields:
            state.last_summary = "Where are you looking to go?"
            state.suggested_responses = ["Bali, Indonesia", "Paris, France", "Tokyo, Japan"]
            set_question_target(state, "destinations", source="missing_fields_guard:fallback")
            store_suggestions_with_field(state, state.suggested_responses, "destinations")
        elif "origin" in missing_fields:
            state.last_summary = "Where will you be flying from?"
            state.suggested_responses = ["New York", "London", "Los Angeles"]
            set_question_target(state, "origin", source="missing_fields_guard:fallback")
            store_suggestions_with_field(state, state.suggested_responses, "origin")
        else:
            state.last_summary = "When are you looking to travel?"
            state.suggested_responses = ["Next month", "December 20-27", "First week of January"]
            set_question_target(state, "dates", source="missing_fields_guard:fallback")
            store_suggestions_with_field(state, state.suggested_responses, "dates")
        # Track that response was produced this turn (no-stale-summary invariant)
        state.metadata["last_response_turn"] = state.turn_number
        return True


# Vague affirmations that don't provide actionable information
# Used by no-op specialist gate to skip LLM when user just confirms without details
_VAGUE_AFFIRMATIONS = frozenset(
    {
        "ok",
        "okay",
        "sure",
        "yes",
        "yep",
        "yeah",
        "sounds good",
        "sounds great",
        "looks good",
        "looks great",
        "perfect",
        "great",
        "fine",
        "alright",
        "good",
        "nice",
        "cool",
        "maybe",
        "i guess",
        "i think so",
        "that works",
        "works for me",
    }
)


def _is_vague_affirmation(text: str) -> bool:
    """
    Check if user text is a vague affirmation without actionable content.

    Vague affirmations like "sounds good", "okay", "sure" don't provide new
    information for specialists to process. When there are no pending missing
    fields, we can skip the LLM call entirely.

    Args:
        text: User text (will be lowercased and stripped)

    Returns:
        True if text is a vague affirmation, False otherwise
    """
    normalized = text.lower().strip()
    # Check exact match
    if normalized in _VAGUE_AFFIRMATIONS:
        return True
    # Check if it's a very short confirmation (1-2 words, < 15 chars)
    words = normalized.split()
    if len(words) <= 2 and len(normalized) < 15:
        # Check if any word is an affirmation
        for word in words:
            if word in _VAGUE_AFFIRMATIONS:
                return True
    return False


async def _specialist(name: str, state: GraphState, retry_on_json_error: bool = True) -> GraphState:
    """
    Shared handler for specialist nodes with JSON retry logic.

    Args:
        name: Prompt name to load (also used to look up per-node LLM config).
        state: Current graph state.
        retry_on_json_error: If True, attempt one repair retry on JSON parse failure.
    """
    _debug_node_entry(f"specialist:{name}", state)

    # =========================================================================
    # HARD GATE: Block ALL domain specialists if core fields are missing
    # =========================================================================
    # This is a HARD GATE - no exceptions. Specialists should never run without
    # core fields (destinations, origin, start_date). This saves ~1000-2000 tokens
    # per specialist call that would otherwise be wasted.
    #
    # The gate applies to:
    # - flights, hotels, activities, transport: Domain specialists
    # - strategy: Strategy planning specialist
    #
    # Exempt:
    # - required_fields: Collects the core fields
    # - correction: Must run even without core fields to address infeasibilities
    #
    # Exception: PRE-CORE MODE
    # When specialist_pre_core_enabled, specialists can handle requests even with
    # missing core fields by acknowledging intent and asking for missing fields inline.
    _GUARDED_SPECIALISTS = {
        "flights",
        "hotels",
        "activities",
        "transport",
        "strategy",
    }
    if name in _GUARDED_SPECIALISTS:
        has_core, missing_core = _has_required_core_fields(state)
        if not has_core:
            # Check if we're in pre-core mode (routed here intentionally)
            pre_core_mode = state.metadata.get("pre_core_mode", False)

            if pre_core_mode and settings.specialist_pre_core_enabled:
                # =====================================================================
                # PRE-CORE MODE (MVP): Deterministic response - bypass LLM entirely
                # =====================================================================
                # Instead of invoking LLM, generate a template-based response that:
                # 1. Acknowledges the user's intent/topic
                # 2. Asks for the next missing core field deterministically
                # 3. Provides template suggestions
                _debug(
                    f"🔄 PRE-CORE MODE (DETERMINISTIC): {name} bypassing LLM",
                    specialist=name,
                    missing=missing_core,
                    tokens_saved="~1000-2000 (specialist LLM call avoided)",
                )
                state.metadata["specialist_pre_core_active"] = True
                state.metadata["specialist_pre_core_deterministic"] = True

                # Determine next missing field using priority order
                question_target = None
                for field in CORE_FIELD_PRIORITY:
                    # Normalize field names for comparison
                    check_field = field
                    if field == "start_date":
                        check_field = "start_date"
                    if check_field in missing_core or field in missing_core:
                        question_target = "dates" if field == "start_date" else field
                        break

                if not question_target and missing_core:
                    question_target = (
                        "destinations" if "destinations" in missing_core else missing_core[0]
                    )

                # Build acknowledgment based on specialist type and user text
                user_text_lower = (state.user_text or "").lower()
                topic_acknowledgments = {
                    "hotels": "hotels and accommodation",
                    "flights": "flights",
                    "activities": "activities and things to do",
                    "transport": "transportation",
                    "strategy": state.strategy_topic or "trip planning",
                }
                topic_name = topic_acknowledgments.get(name, name)

                # Get template question and suggestions
                template_response = _get_template_response(question_target, state.strategy_topic)
                if template_response:
                    question = template_response["question"]
                    suggestions = template_response["suggestions"][:3]
                else:
                    # Fallback question
                    question = (
                        "Where would you like to go?"
                        if question_target == "destinations"
                        else f"Could you tell me your {question_target}?"
                    )
                    suggestions = FALLBACK_SUGGESTIONS.copy()

                # Build warm acknowledgment + question
                state.last_summary = f"I'd love to help you find great {topic_name}! {question}"
                state.suggested_responses = suggestions
                set_question_target(state, question_target, source=f"specialist:{name}:pre_core")
                state.metadata["last_question_field"] = question_target
                state.metadata["from_template"] = True
                state.metadata["pre_core_deterministic_path"] = f"{name}:{question_target}"

                # Track question for loop guard
                track_question_asked(state, question_target, state.last_summary)

                _debug(
                    f"✅ PRE-CORE DETERMINISTIC: {name} → {question_target}",
                    question=state.last_summary[:80],
                    suggestions=suggestions,
                )
                _debug_node_exit(f"specialist:{name}", state)
                return state
            else:
                _debug(
                    f"🚫 SPECIALIST_GATE: {name} BLOCKED (core fields missing)",
                    specialist=name,
                    missing=missing_core,
                    tokens_saved=f"~1000-2000 ({name} LLM call avoided)",
                )
                state.metadata["specialist_gate_triggered"] = name
                state.metadata["specialist_gate_missing"] = missing_core

                # Use small prompt to generate a warm question with suggestions
                guard_result = await _invoke_missing_fields_guard(state, missing_core)
                if guard_result:
                    _debug_node_exit(f"specialist:{name}", state)
                    return state

    # =========================================================================
    # DEFAULT ADULTS LOGIC: When core complete but adults missing, default to 1
    # =========================================================================
    # This prevents repeated "How many travelers?" questions when user has
    # provided destination and dates but not explicitly mentioned party size.
    # We assume solo traveler and mark it in metadata for transparency.
    if settings.default_adults_enabled and name in _GUARDED_SPECIALISTS:
        ti = state.trip_inputs
        # Check if destination and dates are set but adults is not
        has_destination = bool(ti.destinations)
        has_dates = bool(ti.start_date)
        has_adults = ti.adults is not None and ti.adults > 0

        if has_destination and has_dates and not has_adults:
            _debug(
                "🧑 DEFAULT_ADULTS: Setting adults=1 (solo traveler assumed)",
                destinations=ti.destinations,
                start_date=ti.start_date,
            )
            state.trip_inputs.adults = 1
            state.metadata["adults_defaulted"] = True
            state.metadata["adults_default_reason"] = "core_complete_without_explicit_count"

    # =========================================================================
    # NO-OP SPECIALIST GATE: Skip LLM for vague affirmations
    # =========================================================================
    # When user says "sounds good", "okay", "sure" etc. without providing new
    # information, and there are no pending missing_fields, skip the LLM call.
    # This saves ~800-1500 tokens on confirmatory exchanges.
    _NOOP_GATE_SPECIALISTS = {"flights", "hotels", "activities", "transport"}
    if name in _NOOP_GATE_SPECIALISTS:
        user_text = state.user_text or ""
        missing_fields = compute_trip_readiness(
            state.trip_inputs.model_dump(exclude_none=True)
        ).missing_core

        if _is_vague_affirmation(user_text) and not missing_fields:
            _routing_stats["noop_gate_triggered"] += 1
            _debug(
                f"⏭️ NO-OP GATE: {name} skipped (vague affirmation, no missing fields)",
                specialist=name,
                user_text=user_text[:30],
                tokens_saved="~800-1500 (specialist LLM call avoided)",
            )
            state.metadata["noop_gate_triggered"] = name
            state.last_summary = (
                "Great! Is there anything else you'd like to add or should I proceed with the plan?"
            )
            state.suggested_responses = [
                "Proceed with plan",
                "Add more details",
                "Change something",
            ]
            _debug_node_exit(f"specialist:{name}", state)
            return state

    # Get per-node LLM configuration
    llm_config = _get_node_llm_config(name)

    # =========================================================================
    # REQUIRED_FIELDS: TEMPLATE-FIRST APPROACH
    # =========================================================================
    # Templates are the PRIMARY path for required_fields. LLM is fallback only.
    # This saves ~900-1500 tokens per turn on simple field collection.
    if name == "required_fields":
        # =====================================================================
        # DEFAULT ADULTS LOGIC (also applies in required_fields)
        # =====================================================================
        # When core fields are complete but adults is missing, and user has a
        # domain keyword in their message, default adults to 1 and route to
        # the appropriate specialist instead of asking about travelers.
        ti = state.trip_inputs
        has_destination = bool(ti.destinations)
        has_dates = bool(ti.start_date)
        has_adults = ti.adults is not None and ti.adults > 0
        core_complete = has_destination and bool(ti.origin) and has_dates

        if settings.default_adults_enabled and core_complete and not has_adults:
            # Check if user message contains a domain keyword
            user_text_lower = (state.user_text or "").lower()
            domain_keywords = {
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
                "hotels": {
                    "hotel",
                    "hotels",
                    "accommodation",
                    "stay",
                    "lodging",
                    "hostel",
                    "airbnb",
                },
                "flights": {"flight", "flights", "fly", "flying", "plane", "airline", "airport"},
                "transport": {
                    "transport",
                    "train",
                    "bus",
                    "taxi",
                    "uber",
                    "rental car",
                    "car rental",
                },
            }
            detected_domain = None
            for domain, keywords in domain_keywords.items():
                if any(kw in user_text_lower for kw in keywords):
                    detected_domain = domain
                    break

            if detected_domain:
                # Default adults to 1 and mark for specialist routing
                _debug(
                    "🧑 DEFAULT_ADULTS in required_fields: Setting adults=1",
                    detected_domain=detected_domain,
                    destinations=ti.destinations,
                    user_text_preview=user_text_lower[:50],
                )
                state.trip_inputs.adults = 1
                state.metadata["adults_defaulted"] = True
                state.metadata["adults_default_reason"] = "core_complete_with_domain_keyword"
                # Set intent so routing picks up the right specialist
                state.intent = detected_domain
                state.metadata["deferred_intent"] = detected_domain
                # Return early - let the routing mechanism handle it
                _debug_node_exit(f"specialist:{name}", state)
                return state

        # Determine question_target based on missing fields
        question_target = state.question_target or state.metadata.get("last_question_field")
        if not question_target:
            if not ti.destinations:
                question_target = "destinations"
            elif not ti.origin:
                question_target = "origin"
            elif not ti.start_date:
                question_target = "dates"
            elif not ti.adults:
                question_target = "travelers"

        # Check for conditions that REQUIRE LLM (template cannot handle):
        extraction_conf = state.metadata.get("extraction_confidence", {})
        requires_llm = False
        llm_reason = None
        conf_overall = extraction_conf.get("overall", 0.5)

        # 1. Typo suggestions need LLM to ask for confirmation - BUT only if low confidence
        # If typos detected but confidence is high, user likely knows what they meant
        if extraction_conf.get("typo_suggestions"):
            if conf_overall < 0.5:
                requires_llm = True
                llm_reason = "typo_suggestions_low_conf"
                _debug(
                    "🔄 LLM_FALLBACK: typo suggestions with low confidence",
                    typos=list(extraction_conf.get("typo_suggestions", {}).keys())[:2],
                    confidence=f"{conf_overall:.2f}",
                )
            else:
                # High confidence with typos - use template, user likely knows what they want
                _debug(
                    "📋 TEMPLATE_SAFE: typo suggestions but high confidence",
                    confidence=f"{conf_overall:.2f}",
                )

        # 2. Low confidence needs LLM for clarification - BUT only for complex cases
        # "Harmless low confidence" for simple core fields can use templates
        elif extraction_conf.get("level") == "low":
            # Simple core fields (destinations, origin, dates, travelers) are safe
            # to handle with templates even at low confidence
            harmless_fields = {"destinations", "origin", "dates", "travelers"}
            if question_target not in harmless_fields:
                requires_llm = True
                llm_reason = "low_confidence_complex_field"
            else:
                # Harmless low confidence - use template, track it
                _template_stats["low_conf_accepted"] += 1
                _debug(
                    "📋 HARMLESS_LOW_CONF: accepted without LLM",
                    field=question_target,
                    confidence_level="low",
                    tokens_saved="~900-1500 (required_fields LLM avoided)",
                )

        # 3. Multi-city ambiguity needs LLM
        elif state.trip_inputs.destinations and len(state.trip_inputs.destinations) > 1:
            multi_city_intent = state.trip_inputs.multi_city_intent
            if not multi_city_intent:
                requires_llm = True
                llm_reason = "multi_city_ambiguity"

        # 4. Ambiguity keywords in confidence reasons (excluding "vague" - too broad)
        low_confidence_reasons = extraction_conf.get("low_confidence_reasons") or []
        ambiguity_keywords = ["ambiguous", "unclear", "multiple", "conflict"]
        if any(
            any(kw in reason.lower() for kw in ambiguity_keywords)
            for reason in low_confidence_reasons
        ):
            requires_llm = True
            llm_reason = f"ambiguity_detected:{low_confidence_reasons[0][:30]}"

        if not requires_llm and question_target:
            # LOOP GUARD CHECK: Prevent repeated questions about the same field
            state, should_skip_question = check_and_apply_loop_guard(state, question_target)
            if should_skip_question:
                _debug(
                    "🛡️ LOOP GUARD: Skipping question due to repeated asks",
                    question_target=question_target,
                    questions_asked=state.questions_asked,
                )
                # Return with recovery summary instead of repeating the question
                _debug_node_exit(f"specialist:{name}", state)
                return state

            # LOOP GUARD: If "different_field" mitigation was applied, switch to another field
            skip_field = state.metadata.get("loop_guard_skip_field")
            if skip_field and skip_field == question_target:
                # Find a different required field to ask about
                readiness = compute_trip_readiness(state.trip_inputs)

                # Helper to normalize field names for comparison
                def _normalize_field_name(f: str) -> str:
                    if f == "start_date":
                        return "dates"
                    elif f == "travelers (adults)":
                        return "travelers"
                    elif f == "end_date":
                        return "dates"  # end_date is part of dates question
                    return f

                # Filter out the skip field (normalize for comparison)
                alternative_fields = [
                    f for f in readiness.missing_all if _normalize_field_name(f) != skip_field
                ]
                if alternative_fields:
                    # Use the first alternative and normalize it
                    alt_field = _normalize_field_name(alternative_fields[0])
                    question_target = alt_field
                    _debug(
                        "🛡️ LOOP GUARD: Switched to different field",
                        skipped=skip_field,
                        new_target=question_target,
                    )
                else:
                    # No alternative fields - emit recovery summary
                    trip_inputs_dict = (
                        state.trip_inputs.model_dump()
                        if hasattr(state.trip_inputs, "model_dump")
                        else dict(state.trip_inputs)
                    )
                    known_info = _summarize_trip_inputs_for_recovery(trip_inputs_dict)
                    state.last_summary = (
                        f"I have most of your trip details. Here's what I know:\n\n"
                        f"{known_info}\n\n"
                        f"Is there anything you'd like to add or change?"
                    )
                    state.suggested_responses = [
                        "Looks good!",
                        "Add more details",
                        "Change something",
                    ]
                    _debug(
                        "🛡️ LOOP GUARD: No alternative fields, emitting recovery summary",
                    )
                    _debug_node_exit(f"specialist:{name}", state)
                    return state

            # TEMPLATE PATH: Use template for simple field questions
            template_response = _get_template_response(question_target, state.strategy_topic)
            if template_response:
                _template_stats["template_hits"] += 1
                state.last_summary = template_response["question"]
                state.suggested_responses = template_response["suggestions"]
                set_question_target(state, question_target, source=f"specialist:{name}:template")

                # Store suggestions with field info for deterministic echo
                store_suggestions_with_field(
                    state, template_response["suggestions"], question_target
                )

                # Track this question for loop guard
                track_question_asked(state, question_target, template_response["question"])

                # Map question_target to last_question_field for fast-path context
                target_to_field = {
                    "destinations": "destinations",
                    "origin": "origin",
                    "dates": "dates",
                    "travelers": "travelers",
                    "budget": "budget",
                }
                state.metadata["last_question_field"] = target_to_field.get(
                    question_target, question_target
                )
                state.metadata["from_template"] = True  # Flag for response_polish to skip

                _debug(
                    "✅ TEMPLATE PATH: Required fields using template (LLM BYPASSED)",
                    question_target=question_target,
                    question=state.last_summary,
                    suggestions=state.suggested_responses,
                    tokens_saved="~900-1500 (required_fields LLM call avoided)",
                )
                state.metadata["required_fields_path"] = f"template:{question_target}"
                _debug_node_exit(f"specialist:{name}", state)
                return state
            else:
                _template_stats["template_misses"] += 1
                _debug(
                    "Template not found for target, falling through to LLM",
                    question_target=question_target,
                )
                llm_reason = f"no_template_for:{question_target}"

        if requires_llm:
            _debug(
                "⚠️ LLM PATH: Required fields requires LLM",
                reason=llm_reason,
                question_target=question_target,
            )

        # Cache check (only if we're going to LLM anyway)
        cache_key: Optional[str] = None
        core_fields = _get_core_fields_state(state.trip_inputs)
        user_intent = state.metadata.get("user_intent", "detailed_planner")
        cache_key = _compute_cache_key("required_fields", core_fields, user_intent, "")
        cached = _get_cached_response(_follow_up_cache, cache_key, state)
        if cached is not None:
            _debug_cache_hit("required_fields", cache_key[:16])
            state.last_summary = cached.get("assistant_message", "")
            state.question_target = cached.get("question_target")
            state.suggested_responses = cached.get("suggested_responses", [])
            summary_snippet = state.last_summary[:50] if state.last_summary else ""
            _debug(f"Required fields cache hit: {summary_snippet}")
            state.metadata["required_fields_path"] = "cache"
            _debug_node_exit(f"specialist:{name}", state)
            return state
    else:
        cache_key = None

    # Get today's date for prompt injection
    today_iso = state.metadata.get("today_iso") or _today_iso()

    # Get extraction confidence for confirmation prompts
    extraction_conf = state.metadata.get("extraction_confidence", {})
    confidence_level = extraction_conf.get("level", "unknown")
    typo_suggestions = extraction_conf.get("typo_suggestions", [])

    # Build extraction sources summary from parsed_inputs
    parsed = state.parsed_inputs or {}
    extraction_sources = {
        "destinations": parsed.get("destinations_source"),
        "origin": parsed.get("origin_source"),
        "budget": parsed.get("budget_source"),
        "travelers": parsed.get("travelers_source"),
        "dates": parsed.get("dates_source"),
        "duration": parsed.get("duration_source"),
    }
    # Filter out None values for cleaner output
    extraction_sources = {k: v for k, v in extraction_sources.items() if v}

    # Preserve the current trip_inputs snapshot for fallback normalization
    ti = state.trip_inputs

    # Use split prompts for required_fields to reduce token usage
    # Phase 6: Use load_specialist_prompt for domain specialists (conditional stripping)
    specialist_types = {"flights", "hotels", "transport", "activities"}
    if name == "required_fields":
        prompt = _select_required_fields_prompt(state)
    elif name in specialist_types:
        prompt = load_specialist_prompt(name, state)
    else:
        prompt = load_prompt(name)

    # =========================================================================
    # STATE VIEW: Use minimal state views to reduce token usage
    # =========================================================================
    # Instead of passing full trip_inputs (~50 fields), pass only what the node needs.
    if name == "required_fields":
        state_view = StateViewBuilder.for_required_fields(state)
        view_type = "required_fields"
    elif name in specialist_types:
        state_view = StateViewBuilder.for_specialist(state, name)
        view_type = name
    elif name == "strategy":
        state_view = StateViewBuilder.for_strategy(state)
        view_type = "strategy"
    elif name == "correction":
        # Correction needs core fields + all settings for conflict detection
        state_view = StateViewBuilder.for_correction(state)
        view_type = "correction"
    else:
        # Fallback to full state for unknown nodes - this should be avoided
        state_view = ti_short(state.trip_inputs)
        view_type = "full"
        _debug(
            f"StateView:FALLBACK:{name}",
            message="Using full state view - consider adding dedicated builder method",
        )

    # Phase 6: Validate state view size to catch regressions
    StateViewBuilder.validate_view(state_view, name)

    # Calculate token savings
    full_state_size = len(json.dumps(ti_short(state.trip_inputs)))
    view_size = len(json.dumps(state_view))
    tokens_saved_estimate = (full_state_size - view_size) // 4  # ~4 chars per token

    _debug(
        f"StateView applied: {view_type}",
        full_size=full_state_size,
        view_size=view_size,
        tokens_saved_estimate=tokens_saved_estimate,
    )

    # Generate tone instruction using ToneAdapter (replaces _adapt_tone.txt include)
    user_intent = state.metadata.get("user_intent", "detailed_planner")
    user_tone = state.metadata.get("user_tone", "neutral")
    tone_instruction = ToneAdapter.get_instruction(user_intent, user_tone)

    # Get available options context for grounded responses (tiles data)
    available_options = get_available_options_context(state, name)

    # =========================================================================
    # GROUNDEDNESS GUARDRAIL: Track when we suppress invented details
    # =========================================================================
    # Increment invented_detail_block_count ONLY when ALL conditions are true:
    # 1. Intent is grounding-required: hotels|flights|activities
    # 2. User asked for concrete options OR specialist in "recommendation mode"
    # 3. available_options_context is empty or invalid
    # 4. Specialist output policy explicitly suppresses naming/pricing
    groundedness_warning = ""
    tile_based_specialists = {"hotels", "flights", "activities"}

    if name in tile_based_specialists:
        options_empty = not available_options.strip()
        options_invalid = available_options.strip() and "error" in available_options.lower()

        # Check if user asked for options or specialist is in recommendation mode
        user_text_lower = (state.user_text or "").lower()
        user_asked_for_options = any(
            phrase in user_text_lower
            for phrase in [
                "recommend",
                "suggest",
                "options",
                "choices",
                "what about",
                "show me",
                "find me",
                "any good",
                "best",
                "where to stay",
                "which hotel",
                "which flight",
                "which activit",
            ]
        )
        pre_core_mode = state.metadata.get("pre_core_mode") if state.metadata else False

        # In pre_core_mode, the specialist focuses on collecting missing fields,
        # NOT on providing recommendations. So we should NOT trigger groundedness
        # warnings in pre_core_mode - the specialist will ask for destinations/dates first.
        recommendation_mode = user_asked_for_options and not pre_core_mode

        if (options_empty or options_invalid) and recommendation_mode:
            # Determine reason for blocking
            if options_empty:
                block_reason = "no_tiles"
            elif options_invalid:
                block_reason = "tiles_invalid"
            else:
                block_reason = "tiles_stale"

            groundedness_warning = (
                "\n\n⚠️ GROUNDEDNESS CONSTRAINT ⚠️\n"
                "No verified options are currently available for this category.\n"
                "DO NOT invent or fabricate specific names, prices, or details.\n"
                "Instead, acknowledge the request and explain that specific options "
                "are being searched for or will be available shortly.\n"
            )

            # Track with proper tags for observability
            _increment_state_counter("invented_detail_block_count")
            _debug(
                "[GROUNDEDNESS] Blocking potential invention due to missing tiles",
                intent=name,
                node=f"specialist:{name}",
                pre_core_mode=pre_core_mode,
                reason=block_reason,
                user_asked_for_options=user_asked_for_options,
            )

            # Store tags in metadata for downstream analysis
            if state.metadata is None:
                state.metadata = {}
            groundedness_blocks = state.metadata.get("groundedness_blocks", [])
            groundedness_blocks.append(
                {
                    "intent": name,
                    "node": f"specialist:{name}",
                    "pre_core_mode": pre_core_mode,
                    "reason": block_reason,
                    "turn": state.turn_number,
                }
            )
            state.metadata["groundedness_blocks"] = groundedness_blocks

    # Format questions_already_asked for loop prevention in required_fields specialist
    questions_already_asked = "None yet"
    if hasattr(state, "questions_asked") and state.questions_asked:
        asked_list = [f"{field} (asked {count}x)" for field, count in state.questions_asked.items()]
        questions_already_asked = ", ".join(asked_list) if asked_list else "None yet"

    system_prompt = (
        prompt.replace("{trip_inputs}", json.dumps(state_view))
        .replace("{parsed_inputs}", json.dumps(state.parsed_inputs))
        .replace("{today}", today_iso)
        .replace("{user_intent_hint}", user_intent)
        .replace("{user_tone}", user_tone)
        .replace("{tone_instruction}", tone_instruction)
        .replace("{extraction_confidence}", confidence_level)
        .replace("{typo_suggestions}", json.dumps(typo_suggestions) if typo_suggestions else "none")
        .replace(
            "{extraction_sources}", json.dumps(extraction_sources) if extraction_sources else "{}"
        )
        .replace("{missing_fields}", _get_missing_fields_summary(state))
        .replace("{conversation_summary}", _generate_conversation_summary(state.chat_history))
        .replace("{available_options}", available_options + groundedness_warning)
        .replace("{questions_already_asked}", questions_already_asked)
    )

    # Determine timeout based on model type
    timeout = settings.llm_timeout_specialist
    attempts = settings.llm_max_retries if retry_on_json_error else 1
    last_error = None

    tokens = _estimate_prompt_tokens(system_prompt, state.parsed_inputs)
    _record_node_tokens(state, f"specialist:{name}", tokens, model=llm_config["model_hint"])

    # LLM Budget Gate: Return fallback if budget exhausted
    if not can_call_llm(state, f"specialist:{name}"):
        _debug(
            f"⚠️ specialist:{name}: LLM budget exhausted, using fallback for {question_target}",
            question_target=question_target,
        )
        llm_blocked_fallback(
            state, asked_target=question_target, source=f"specialist:{name}:budget_blocked"
        )
        return state

    import time as _time

    for attempt in range(attempts):
        try:
            # Pass history as separate messages for better context
            _llm_start = _time.perf_counter()
            out = await call_llm_with_timeout(
                model=llm_config["model_hint"],
                prompt=system_prompt,
                timeout_seconds=timeout,
                max_tokens=llm_config["max_tokens"],
                temperature=llm_config["temperature"],
                history=state.chat_history,
                user_message=state.user_text,
                top_p=llm_config["top_p"],
            )
            _record_llm_time(state, (_time.perf_counter() - _llm_start) * 1000)
            _increment_llm_calls(state)
            j = jloads_safe(out)

            # Debug: log raw LLM response
            _debug(
                f"Specialist {name} LLM response",
                assistant_message=(
                    j.get("assistant_message", "<MISSING>")[:100]
                    if j.get("assistant_message")
                    else "<EMPTY>"
                ),
            )

            # Capture assistant_message early - even if field processing fails, we want this
            assistant_msg = j.get("assistant_message", "")
            if assistant_msg:
                state.last_summary = assistant_msg

            # Apply trip_inputs delta using centralized helper
            delta = j.get("trip_inputs", {}) or {}

            # Handle strategy_hint separately - it belongs in parsed_inputs, not trip_inputs
            # (LLM may return it in trip_inputs when confirming strategy intent)
            if "strategy_hint" in delta:
                strategy_hint = delta.pop("strategy_hint")
                if strategy_hint and isinstance(strategy_hint, str):
                    state.parsed_inputs["strategy_hint"] = strategy_hint
                    _debug(f"Captured strategy_hint from LLM: {strategy_hint}")

            # Domain specialists (flights, hotels, activities, transport) should not overwrite
            # core fields extracted by the extractor. Only required_fields and correction can
            # modify these fields (required_fields for collection, correction for fixing
            # infeasibility).
            _CORE_FIELDS = {
                "destinations",
                "origin",
                "start_date",
                "end_date",
                "adults",
                "children",
                "budget",
                "currency",
            }

            # Correction node can only modify core fields + specific correction-relevant fields
            # This prevents over-broad changes from correction requests
            _CORRECTION_ALLOWED_FIELDS = {
                "destinations",
                "origin",
                "start_date",
                "end_date",
                "adults",
                "children",
                "budget",
                "currency",
                # Allow removal of specific settings if user explicitly rejects
                "flight_settings",
                "hotel_settings",
                "transport_settings",
                "activity_settings",
            }

            # Fields that correction should NEVER modify (to prevent scope creep)
            _CORRECTION_SKIP_FIELDS = {
                "strategy_settings",  # Strategy is complex, shouldn't be corrected inline
                "booking_types",  # Auto-managed, not user-correctable
            }

            # required_fields can modify all fields; correction has restricted scope
            if name == "required_fields":
                skip_fields = None  # Allow all field modifications
            elif name == "correction":
                skip_fields = _CORRECTION_SKIP_FIELDS  # Block specific fields
                _debug(
                    "Correction node field permissions",
                    allowed="core + settings",
                    blocked=list(_CORRECTION_SKIP_FIELDS),
                )
            else:
                skip_fields = _CORE_FIELDS  # Domain specialists: block core fields
            _apply_llm_delta(state, f"specialist:{name}", delta, skip_fields=skip_fields)

            # Validate the updated trip_inputs
            TRIP_VALIDATOR.validate(state.trip_inputs.model_dump())
            state.last_summary = j.get("assistant_message", "")

            # Early safety snippet injection for international travel
            # This triggers as soon as we have destination+origin, not just at summarize
            if state.last_summary and state.trip_inputs.destinations:
                state.last_summary = _maybe_append_safety_snippet(state)

            # Parse question_target from LLM response for suggestion relevance
            raw_question_target = j.get("question_target")
            if raw_question_target and isinstance(raw_question_target, str):
                normalized_target = raw_question_target.lower().strip()
                if normalized_target in QUESTION_TARGET_VALUES:
                    set_question_target(
                        state, normalized_target, source=f"specialist:{name}:llm_response"
                    )
                    # Track this question for loop guard
                    track_question_asked(state, normalized_target, state.last_summary)
                elif normalized_target == "null" or normalized_target == "none":
                    set_question_target(state, None, source=f"specialist:{name}:llm_null")
                else:
                    _debug(f"Unknown question_target from LLM: {raw_question_target}")
                    set_question_target(state, None, source=f"specialist:{name}:llm_unknown")
            else:
                set_question_target(state, None, source=f"specialist:{name}:no_target")

            # Filter suggested responses with contextual fallback
            raw_suggestions = j.get("suggested_responses", []) or []
            _debug(f"Raw LLM suggested_responses: {raw_suggestions}")
            state.suggested_responses = _get_suggestions_with_fallback(
                raw_suggestions, state, state.question_target
            )
            _debug_suggestions(state.suggested_responses, source=f"specialist:{name}")

            # Only set ready_to_generate if explicitly triggered
            state.ready_to_generate = bool(j.get("ready_to_generate", False)) and state.flags.get(
                "generate_requested", False
            )

            # Only emit branches if generate was explicitly requested
            if state.flags.get("generate_requested", False):
                raw_branches = j.get("branches", []) or []
                fallback = ti.model_dump(exclude_none=True)
                normalized_branches: List[Dict[str, Any]] = []
                for b in raw_branches:
                    normalized = _normalize_branch_spec(b, fallback)
                    if normalized:
                        normalized_branches.append(normalized)
                state.branches = normalized_branches

            state.metadata["model_used"] = llm_config["model_hint"]
            state.metadata["token_estimate"] = _count_tokens(out)

            # Cache the response for required_fields node
            if name == "required_fields" and cache_key is not None:
                _set_cached_response(
                    _follow_up_cache,
                    cache_key,
                    {
                        "assistant_message": state.last_summary,
                        "question_target": state.question_target,
                        "suggested_responses": state.suggested_responses,
                    },
                )
                # Record path trace for required_fields
                state.metadata["required_fields_path"] = "llm"

            _debug(
                f"Specialist {name} completed",
                ready=state.ready_to_generate,
                branches=len(state.branches),
            )
            _debug_node_exit(f"specialist:{name}", state)
            return state

        except json.JSONDecodeError as e:
            last_error = e
            _debug_error(f"Specialist {name} JSON error on attempt {attempt + 1}", error=str(e))
            if attempt < attempts - 1:
                # Add repair hint to prompt for retry
                system_prompt += INVALID_JSON_HINT
                continue
            break
        except TimeoutError as e:
            last_error = e
            _debug_error(f"Specialist {name} timeout on attempt {attempt + 1}")
            break
        except Exception as e:
            last_error = e
            _debug_error(f"Specialist {name} error on attempt {attempt + 1}", error=str(e))
            break

    reason = f"{name} node produced invalid output after {attempts} attempt(s): {last_error}"
    _debug_error(f"Specialist {name} failed", reason=reason)
    return _record_llm_failure(state, reason)


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
# Strategy node (loads module by topic from registry)
# -----------------------
def _is_strategy_enabled(topic: str) -> bool:
    """Check if a strategy is enabled via feature flags."""
    flag_map = {
        "boating": settings.enable_strategy_boating,
        "hiking": settings.enable_strategy_hiking,
        "diving": settings.enable_strategy_diving,
        "skiing": settings.enable_strategy_skiing,
        "cycling": settings.enable_strategy_cycling,
    }
    return flag_map.get(topic, True)  # Default to enabled for unknown topics


# Question guidance for strategy_pre_core prompt based on question_target
# Uses canonical question_target values ("dates" not "start_date")
_STRATEGY_PRE_CORE_QUESTION_GUIDANCE = {
    "dates": (
        "Ask about timing/season. Examples:\n"
        '- "When are you thinking of going? Spring and fall are usually best."\n'
        '- "What month or season works for you?"'
    ),
    "origin": (
        "Ask about departure location. Examples:\n"
        '- "Where will you be traveling from?"\n'
        '- "What city will you be departing from?"'
    ),
    "destinations": (
        "Ask about preferred destination (only if other fields are set). Examples:\n"
        '- "Which of these regions appeals to you most?"\n'
        '- "Any of these destinations catching your eye?"'
    ),
}


async def _strategy_stage0(state: GraphState, topic: str) -> GraphState:
    """
    Stage 0: Pre-core value-first strategy response.

    Provides immediate value (destination archetypes + mini itinerary) with
    a single clarifying question, before core fields are complete.

    This is triggered by the STRATEGY_PRE_CORE_VALUE gate when:
    - Strategy topic detected (hiking, skiing, etc.)
    - Core fields missing
    - No destinations extracted
    - User didn't ask for "questions only"
    """
    ti = state.trip_inputs
    # Canonicalize question_target at node entry (use "dates" not "start_date")
    raw_target = state.question_target or "dates"
    question_target = canonicalize_question_target(raw_target)

    # Get question guidance (uses canonical keys)
    question_guidance = _STRATEGY_PRE_CORE_QUESTION_GUIDANCE.get(
        question_target, _STRATEGY_PRE_CORE_QUESTION_GUIDANCE["dates"]
    )

    # Compute missing core fields for context
    _, missing_core = _has_required_core_fields(state)

    # Generate tone instruction
    user_intent = state.metadata.get("user_intent", "detailed_planner")
    user_tone = state.metadata.get("user_tone", "neutral")
    tone_instruction = ToneAdapter.get_instruction(user_intent, user_tone)

    # Load the pre-core prompt with Jinja2 templating
    try:
        template = _JINJA_ENV.get_template("strategy_pre_core.txt")
        prompt = template.render(
            strategy_topic=topic,
            question_target=question_target,
            question_guidance=question_guidance,
            user_text=state.user_text or "",
            missing_core_fields=", ".join(missing_core) if missing_core else "none",
            tone_instruction=tone_instruction,
            trip_inputs=ti.model_dump_json(exclude_none=True),
        )
    except FileNotFoundError:
        # Fallback to required_fields if prompt not found
        _debug_error("strategy_pre_core.txt not found, falling back to required_fields")
        return await required_fields_node(state)

    # Use conservative token limit for stage 0
    llm_config = _get_node_llm_config("strategy_stage1")
    llm_config["max_output_tokens"] = 300  # Hard cap for value-first response

    timeout = settings.llm_timeout_specialist
    attempts = settings.llm_max_retries
    last_error = None

    # LLM Budget Gate: Return fallback if budget exhausted
    if not can_call_llm(state, "strategy_stage0"):
        _debug(
            f"⚠️ strategy_stage0: LLM budget exhausted, using fallback for {question_target}",
            question_target=question_target,
        )
        llm_blocked_fallback(
            state, asked_target=question_target, source="strategy_stage0:budget_blocked"
        )
        return state

    for attempt in range(attempts):
        try:
            out = await call_llm_with_timeout(
                model=llm_config["model_hint"],
                prompt=prompt,
                timeout_seconds=timeout,
                max_tokens=llm_config["max_output_tokens"],
                user_message=state.user_text or "",
            )

            j = jloads_safe(out)
            if not j:
                raise json.JSONDecodeError("No JSON block found", out, 0)

            # Extract response
            response = j.get("assistant_message", j.get("response", ""))

            # =================================================================
            # Stage 0 Output Validation (value-first guarantee)
            # =================================================================
            # 1. Must have at least 2 bullets/archetypes (value content)
            # 2. Must have exactly one question mark
            # 3. Must not exceed character limit

            # Count bullets/list items (value indicators)
            bullet_patterns = ["- ", "• ", "* ", "1.", "2.", "3."]
            bullet_count = sum(response.count(p) for p in bullet_patterns)
            if bullet_count < 2:
                _debug(f"⚠️ Stage 0 response lacks value content ({bullet_count} bullets)")
                # Don't fail - but log for observability
                _gate_stats["strategy_stage0_low_value"] = (
                    _gate_stats.get("strategy_stage0_low_value", 0) + 1
                )

            # Validate: exactly one question mark
            question_marks = response.count("?")
            if question_marks == 0:
                _debug("⚠️ Stage 0 response has no question, adding fallback")
                if question_target == "start_date":
                    response += "\n\nWhen are you thinking of going?"
                elif question_target == "origin":
                    response += "\n\nWhere will you be traveling from?"
                else:
                    response += "\n\nDo you have any destinations in mind?"
            elif question_marks > 1:
                _debug(f"⚠️ Stage 0 response has {question_marks} questions, trimming")
                # Keep only up to first question
                first_q_idx = response.find("?")
                response = response[: first_q_idx + 1]

            # Post-render length check (trim if too long)
            max_chars = 1200  # ~250 words
            if len(response) > max_chars:
                _debug(f"⚠️ Stage 0 response too long ({len(response)} chars), trimming")
                # Find a good break point before the question
                q_idx = response.rfind("?")
                if q_idx > 0:
                    # Keep the question, trim the middle
                    question_part = response[response.rfind("\n", 0, q_idx) : q_idx + 1]
                    available = max_chars - len(question_part) - 50
                    response = response[:available] + "\n\n..." + question_part

            state.last_summary = response
            set_question_target(
                state,
                j.get("question_target", question_target),
                source="strategy_stage0:llm_response",
            )
            state.suggested_responses = j.get("suggested_responses", [])[:3]

            # Generate default suggestions if none provided
            if not state.suggested_responses:
                if question_target == "start_date":
                    state.suggested_responses = [
                        "Next spring",
                        "This summer",
                        "I'm flexible on dates",
                    ]
                elif question_target == "origin":
                    state.suggested_responses = ["New York", "London", "Los Angeles"]
                else:
                    state.suggested_responses = ["Tell me more", "Show me options", "Not sure yet"]

            _debug_suggestions(state.suggested_responses, source="strategy_stage0")

            # Track loop guard for this question
            _track_strategy_pre_core_question(state, question_target)

            # Do NOT set destinations or other core fields
            # Only set metadata
            state.metadata["strategy_stage0_completed"] = True
            state.metadata["strategy_stage0_topic"] = topic
            state.metadata["model_used"] = llm_config["model_hint"]

            _debug(
                "✅ Stage 0 completed",
                topic=topic,
                question_target=question_target,
                response_length=len(response),
            )
            _debug_node_exit("strategy_node:stage0", state)
            return state

        except json.JSONDecodeError as e:
            last_error = e
            _debug_error(f"Stage 0 JSON error on attempt {attempt + 1}", error=str(e))
            if attempt < attempts - 1:
                continue
            break
        except TimeoutError as e:
            last_error = e
            _debug_error(f"Stage 0 timeout on attempt {attempt + 1}")
            break
        except Exception as e:
            last_error = e
            _debug_error(f"Stage 0 error on attempt {attempt + 1}", error=str(e))
            break

    # Fallback: on any error, use deterministic template (avoid extra LLM call)
    _debug(
        "⚠️ Stage 0 LLM failed, using deterministic template",
        error=str(last_error),
    )
    state.metadata["strategy_stage0_fallback"] = True
    state.metadata["strategy_stage0_error"] = str(last_error)
    state.metadata["strategy_stage0_deterministic"] = True

    # Deterministic fallback template with value + single question
    topic_templates = {
        "hiking": (
            "Great choice! Hiking adventures are incredibly rewarding.\n\n"
            "Here are some amazing destinations to consider:\n"
            "- **Swiss Alps** - Iconic trails like the Haute Route\n"
            "- **Patagonia, Chile** - Torres del Paine circuit\n"
            "- **New Zealand** - Milford Track and Routeburn\n"
            "- **Nepal** - Classic Annapurna or Everest base camp\n\n"
            "When are you thinking of going?"
        ),
        "skiing": (
            "Exciting! Let's plan an amazing ski trip.\n\n"
            "Top destinations to consider:\n"
            "- **French Alps** - Chamonix, Val d'Isère, Les 3 Vallées\n"
            "- **Swiss Alps** - Zermatt, Verbier, St. Moritz\n"
            "- **Japan** - Niseko, Hakuba for legendary powder\n"
            "- **Colorado** - Vail, Aspen, Breckenridge\n\n"
            "When are you thinking of hitting the slopes?"
        ),
        "diving": (
            "Fantastic! Diving opens up a whole underwater world.\n\n"
            "World-class dive destinations:\n"
            "- **Maldives** - Pristine reefs and manta rays\n"
            "- **Great Barrier Reef, Australia** - Bucket-list diving\n"
            "- **Red Sea, Egypt** - Wrecks and colorful reefs\n"
            "- **Indonesia** - Raja Ampat biodiversity hotspot\n\n"
            "When are you thinking of diving?"
        ),
        "cycling": (
            "Love it! Cycling trips offer amazing ways to explore.\n\n"
            "Epic cycling destinations:\n"
            "- **Netherlands** - Classic flat cycling with canals\n"
            "- **French countryside** - Loire Valley vineyards\n"
            "- **Italian Dolomites** - Stunning mountain passes\n"
            "- **Vietnam** - Ha Long Bay to Hoi An adventure\n\n"
            "When are you thinking of cycling?"
        ),
        "boating": (
            "Wonderful! Sailing adventures are unforgettable.\n\n"
            "Amazing sailing destinations:\n"
            "- **Greek Islands** - Island-hop through the Cyclades\n"
            "- **Croatia** - Dalmatian coast beauty\n"
            "- **Caribbean** - BVI, Grenadines, or Bahamas\n"
            "- **Thailand** - Phuket and the Andaman Sea\n\n"
            "When are you thinking of setting sail?"
        ),
    }

    fallback_response = topic_templates.get(
        topic,
        (
            "Sounds like an exciting trip idea!\n\n"
            "To help you plan the perfect adventure, I'll need a few details.\n\n"
            "When are you thinking of traveling?"
        ),
    )

    state.last_summary = fallback_response
    set_question_target(state, "dates", source="strategy_stage0_fallback")
    state.suggested_responses = _generate_date_suggestions()

    _debug_suggestions(state.suggested_responses, source="strategy_stage0_fallback")
    _debug_node_exit("strategy_node:stage0:fallback", state)
    return state


def _generate_date_suggestions() -> List[str]:
    """Generate relative date suggestions for stage0 fallback."""
    from datetime import date, timedelta

    today = date.today()

    # Calculate "next month" and "in 3 months"
    next_month = today + timedelta(days=30)
    three_months = today + timedelta(days=90)

    return [
        f"Around {next_month.strftime('%B')}",
        f"In {three_months.strftime('%B')}",
        "I'm flexible on dates",
    ]


def _track_strategy_pre_core_question(state: GraphState, question_target: str) -> None:
    """Track questions asked in stage 0 for loop guard."""
    key = "strategy_pre_core_questions"
    if key not in state.metadata:
        state.metadata[key] = []
    state.metadata[key].append(question_target)


def _should_escalate_from_stage0(state: GraphState) -> bool:
    """
    Check if we should escalate from stage 0 to required_fields.

    Returns True if user has ignored stage 0 questions twice.
    """
    questions = state.metadata.get("strategy_pre_core_questions", [])
    return len(questions) >= 2


async def strategy_node(state: GraphState) -> GraphState:
    _debug_node_entry("strategy_node", state)

    topic = state.strategy_topic or "boating"

    # Log selected specialist for observability (routing correctness tracking)
    specialist_name = f"strategy_{topic}"
    state.metadata["selected_specialist"] = specialist_name
    _debug(
        "Strategy topic selected",
        topic=topic,
        specialist=specialist_name,
        routing_path=state.metadata.get("router_path", "unknown"),
    )

    # =========================================================================
    # STAGE 0: PRE-CORE VALUE-FIRST MODE
    # =========================================================================
    # When routed via STRATEGY_PRE_CORE_VALUE gate, provide immediate value
    # (destination archetypes + mini itinerary) with a single clarifying question.
    # This bypasses the core fields guard since we're intentionally providing
    # inspiration before collecting details.
    is_stage0 = state.metadata.get("strategy_stage") == 0
    if is_stage0:
        _debug(
            "📋 STRATEGY STAGE 0: Pre-core value-first mode",
            topic=topic,
            question_target=state.question_target,
        )
        _strategy_stats["stage0_calls"] = _strategy_stats.get("stage0_calls", 0) + 1
        _gate_stats["strategy_pre_core_value_fired"] += 1
        return await _strategy_stage0(state, topic)

    # =========================================================================
    # NODE GUARD 1: Block strategy if core fields are missing
    # =========================================================================
    # Strategy nodes need destination context to provide relevant advice.
    # This guard catches cases where routing exemption allowed strategy through.
    has_core, missing_core = _has_required_core_fields(state)
    if not has_core:
        _debug(
            "⚠️ Node guard triggered: missing core fields for strategy",
            strategy=topic,
            missing=missing_core,
        )
        # Use small prompt to generate a warm question with suggestions
        guard_result = await _invoke_missing_fields_guard(state, missing_core)
        if guard_result:
            _debug_node_exit("strategy_node", state)
            return state

    # =========================================================================
    # NODE GUARD 2: Verify strategy topic relevance
    # =========================================================================
    # Only invoke strategy LLM if user text actually contains strategy-related terms.
    # This prevents wasted tokens when router incorrectly routes to strategy.
    user_text_lower = (state.user_text or "").lower()
    strategy_keywords = {
        "hiking": {"hike", "hiking", "trek", "trekking", "trail", "mountain", "climb"},
        "diving": {"dive", "diving", "scuba", "snorkel", "snorkeling", "underwater"},
        "skiing": {"ski", "skiing", "snowboard", "snowboarding", "slopes", "powder"},
        "cycling": {"bike", "biking", "bicycle", "cycling", "ride", "pedal"},
        "boating": {"boat", "boating", "sail", "sailing", "yacht", "kayak", "canoe"},
    }
    topic_keywords = strategy_keywords.get(topic, set())
    has_strategy_keyword = any(kw in user_text_lower for kw in topic_keywords)

    # Also check if strategy was explicitly routed via keyword heuristic
    was_keyword_routed = state.metadata.get("router_path", "").startswith("keyword_heuristic:")

    if not has_strategy_keyword and not was_keyword_routed:
        # Strategy was routed but user text doesn't mention the topic
        # This likely means router made an error - fallback to required_fields
        _debug(
            "⚠️ Strategy relevance gate: topic keywords not found in user text",
            topic=topic,
            user_text_preview=user_text_lower[:50],
            action="falling back to required_fields",
        )
        state.metadata["strategy_gate_fallback"] = True
        state.metadata["strategy_gate_reason"] = f"no_{topic}_keywords"
        # Instead of wasting strategy LLM, give a helpful response
        state.last_summary = (
            f"I'd be happy to help with {topic} planning! "
            f"Can you tell me more about what kind of {topic} experience you're looking for?"
        )
        state.suggested_responses = [
            f"Beginner-friendly {topic}",
            f"Advanced {topic} spots",
            "Equipment rental info",
        ]
        _debug_suggestions(state.suggested_responses, source="strategy_node:relevance_gate")
        _debug_node_exit("strategy_node", state)
        return state

    # Check feature flag - if disabled, fallback to activities-lite
    if not _is_strategy_enabled(topic):
        _debug(f"Strategy {topic} is disabled, falling back to activities")
        state.last_summary = (
            f"The {topic} planning module is currently unavailable. "
            "I can help with general activity planning instead."
        )
        state.active_category = "activities"
        return await _specialist("activities", state)

    prompt_name = STRATEGY_REGISTRY.get(topic)
    if not prompt_name:
        # Fallback: gentle notice; no state changes
        _debug(f"No prompt for strategy {topic}")
        state.last_summary = (
            f"I can draft a detailed {topic} plan soon. For now, which preferences matter most?"
        )
        state.suggested_responses = [
            "Beginner skill level",
            "Prefer skippered",
            "Max 4 hours daily",
        ]
        _debug_suggestions(state.suggested_responses, source="strategy_node:fallback")
        _debug_node_exit("strategy_node", state)
        return state

    # =========================================================================
    # THREE-TIER STRATEGY LOGIC (Phase 1: Token Optimization)
    # =========================================================================
    # Stage 1 (OUTLINE tier): Returns shortlist + skeleton (max_tokens 512)
    #   Sets pending_strategy_expansion = True, ends with expansion suggestions
    # Stage 2 (SECTION tier): Expands single section (max_tokens 768)
    #   User asks about specific topic: day details, routes, budget, gear, etc.
    # Stage 2 (FULL tier): Complete detailed itinerary (max_tokens 2048)
    #   Only when user explicitly requests "full itinerary", "everything", etc.
    #
    # Stage 2 triggers only on explicit phrases - NOT on implicit confirmations.
    expansion_result = _is_strategy_expansion_request(state.user_text or "")
    is_stage2 = state.pending_strategy_expansion and expansion_result.is_expansion

    if is_stage2:
        # Stage 2: User explicitly asked for expansion
        # Determine tier based on expansion target
        expansion_tier = expansion_result.tier or StrategyTier.SECTION
        expansion_target = expansion_result.target or StrategyExpansionTarget.ITINERARY_OUTLINE

        # Get max_tokens for this tier
        max_tokens = STRATEGY_TIER_MAX_TOKENS.get(expansion_tier, 768)

        # Use stage2 config but override max_tokens based on tier
        llm_config = _get_node_llm_config("strategy_stage2")
        llm_config["max_output_tokens"] = max_tokens

        stage_name = "stage2"
        _strategy_stats["stage2_calls"] += 1

        # Track tier-specific stats
        if expansion_tier == StrategyTier.FULL:
            _strategy_stats["tier_full"] += 1
        else:
            _strategy_stats["tier_section"] += 1

        # Track section-specific stats
        section_stat_map = {
            StrategyExpansionTarget.DAY_DETAILS: "section_day_details",
            StrategyExpansionTarget.ROUTES_TRAILS: "section_routes",
            StrategyExpansionTarget.LOGISTICS: "section_logistics",
            StrategyExpansionTarget.BUDGET: "section_budget",
            StrategyExpansionTarget.GEAR_PACKING: "section_gear",
            StrategyExpansionTarget.CONTINGENCIES: "section_contingencies",
        }
        if expansion_target in section_stat_map:
            _strategy_stats[section_stat_map[expansion_target]] += 1

        # Store tier/target in state for caching and session persistence
        state.strategy_expansion_tier = expansion_tier.value
        state.strategy_expansion_target = expansion_target.value

        _debug(
            "🔍 STRATEGY STAGE 2: Section expansion",
            topic=topic,
            tier=expansion_tier.value,
            target=expansion_target.value,
            max_tokens=max_tokens,
            matched_phrase=expansion_result.matched_phrase,
            stage="2",
        )
    else:
        # Stage 1: Initial strategy response (shortlist + skeleton)
        llm_config = _get_node_llm_config("strategy_stage1")
        stage_name = "stage1"
        expansion_tier = StrategyTier.OUTLINE
        expansion_target = None
        _strategy_stats["stage1_calls"] += 1
        _strategy_stats["tier_outline"] += 1
        _debug(
            "📋 STRATEGY STAGE 1: Generating shortlist + skeleton",
            topic=topic,
            pending_expansion=state.pending_strategy_expansion,
            stage="1",
        )

    # Use timeout and retry logic
    timeout = settings.llm_timeout_specialist
    attempts = settings.llm_max_retries
    last_error = None

    # Generate tone instruction using ToneAdapter (replaces _adapt_tone.txt include)
    user_intent = state.metadata.get("user_intent", "detailed_planner")
    user_tone = state.metadata.get("user_tone", "neutral")
    tone_instruction = ToneAdapter.get_instruction(user_intent, user_tone)

    prompt = load_prompt(prompt_name)

    # Phase 5: For Stage 1, strip verbose includes (_scope_specialist, _markdown_rules)
    # to reduce token count. Stage 1 only needs shortlist + skeleton, not full formatting.
    if not is_stage2:
        prompt = _strip_stage1_includes(prompt)
        # Add budget/season sanity checklist for Stage 1 to prevent correction triggers
        prompt = prompt + _STAGE1_SANITY_CHECKLIST
    elif expansion_target and expansion_target != StrategyExpansionTarget.FULL_EXPANSION:
        # Stage 2 section expansion: Add focus instruction to prompt
        section_focus = (
            "\n\nFOCUS: User requested expansion of **"
            f"{expansion_target.value.replace('_', ' ')}"
            "** section only. Provide detailed content for this section. "
            "Do not repeat the full itinerary.\n"
        )
        prompt = prompt + section_focus

    # Use minimal state view for strategy (saves ~75% tokens vs full trip_inputs)
    strategy_state_view = StateViewBuilder.for_strategy(state)

    system_prompt = (
        prompt.replace("{trip_inputs}", json.dumps(strategy_state_view))
        .replace("{parsed_inputs}", json.dumps(state.parsed_inputs))
        .replace("{topic}", topic)
        .replace("{missing_fields}", _get_missing_fields_summary(state))
        .replace("{conversation_summary}", _generate_conversation_summary(state.chat_history))
        .replace("{tone_instruction}", tone_instruction)
    )

    # =========================================================================
    # STRATEGY CACHE CHECK (5-min TTL, topic + section keyed)
    # Key: (session_id, topic, section_id, core_fields_hash, user_text_hash)
    # Saves ~2000-3000 tokens when user asks similar strategy questions
    # Section-level caching prevents re-rendering when user tweaks one detail
    # =========================================================================
    session_id = state.session_id or "unknown"
    core_fields_hash = _get_core_fields_state(state.trip_inputs)
    user_text_hash = _hash_user_text(state.user_text or "")
    # Use section_id for Stage 2 expansions, None for Stage 1
    section_id = expansion_target.value if (is_stage2 and expansion_target) else None

    cached_strategy = _get_strategy_cached(
        session_id, topic, core_fields_hash, user_text_hash, state, section_id
    )
    if cached_strategy is not None:
        _debug(
            "📦 STRATEGY_CACHE_HIT: Using cached strategy response",
            topic=topic,
            session=f"{session_id[:8]}...",
            tokens_saved="~2000-3000 (strategy LLM call avoided)",
        )
        # Restore cached state
        state.last_summary = cached_strategy.get("assistant_message", "")
        state.suggested_responses = cached_strategy.get("suggested_responses", [])
        state.question_target = cached_strategy.get("question_target")

        # Apply cached strategy_settings
        if cached_strategy.get("strategy_settings"):
            current_ss = (
                dict(state.trip_inputs.strategy_settings)
                if state.trip_inputs.strategy_settings
                else {}
            )
            current_ss[topic] = cached_strategy["strategy_settings"]
            _write_trip_inputs(
                state, f"strategy:{topic}:cache", strategy_settings=current_ss
            )  # Ignore fields_changed

        state.metadata["strategy_path"] = f"cache:{topic}"
        _debug_node_exit("strategy_node", state)
        return state

    tokens = _estimate_prompt_tokens(system_prompt, state.parsed_inputs)
    _record_node_tokens(state, f"strategy:{topic}", tokens, model=llm_config["model_hint"])

    # LLM Budget Gate: Return fallback if budget exhausted
    # Determine best fallback target from missing core fields
    fallback_target = None
    if not (state.trip_inputs.start_date and state.trip_inputs.end_date):
        fallback_target = "dates"
    elif not state.trip_inputs.destinations:
        fallback_target = "destinations"
    elif not state.trip_inputs.origin:
        fallback_target = "origin"

    if not can_call_llm(state, f"strategy:{topic}"):
        _debug(
            f"⚠️ strategy:{topic}: LLM budget exhausted, using fallback",
            fallback_target=fallback_target,
        )
        llm_blocked_fallback(
            state, asked_target=fallback_target, source=f"strategy:{topic}:budget_blocked"
        )
        return state

    import time as _time

    for attempt in range(attempts):
        try:
            # Pass history as separate messages for better context
            _llm_start = _time.perf_counter()
            out = await call_llm_with_timeout(
                model=llm_config["model_hint"],
                prompt=system_prompt,
                timeout_seconds=timeout,
                max_tokens=llm_config["max_tokens"],
                temperature=llm_config["temperature"],
                history=state.chat_history,
                user_message=state.user_text,
                top_p=llm_config["top_p"],
            )
            _record_llm_time(state, (_time.perf_counter() - _llm_start) * 1000)
            _increment_llm_calls(state)
            j = jloads_safe(out)

            # Handle strategy_settings specially (keyed by topic)
            strategy_data = j.get("strategy_settings", {})
            if strategy_data:
                current_ss = (
                    dict(state.trip_inputs.strategy_settings)
                    if state.trip_inputs.strategy_settings
                    else {}
                )
                current_ss[topic] = strategy_data
                _write_trip_inputs(
                    state, f"strategy:{topic}", strategy_settings=current_ss
                )  # Ignore fields_changed

            # Apply remaining trip_inputs delta using centralized helper
            # Strategy nodes should NOT overwrite core fields - only activity_settings
            delta = j.get("trip_inputs", {}) or {}
            _STRATEGY_SKIP_FIELDS = {
                "strategy_settings",  # Handled specially above
                "destinations",
                "origin",
                "start_date",
                "end_date",
                "adults",
                "children",
                "budget",
                "currency",
            }
            _apply_llm_delta(state, f"strategy:{topic}", delta, skip_fields=_STRATEGY_SKIP_FIELDS)

            # Validate the updated trip_inputs
            TRIP_VALIDATOR.validate(state.trip_inputs.model_dump())
            state.last_summary = j.get("assistant_message", "")

            # Parse question_target from LLM response for suggestion relevance
            raw_question_target = j.get("question_target")
            if raw_question_target and isinstance(raw_question_target, str):
                normalized_target = raw_question_target.lower().strip()
                if normalized_target in QUESTION_TARGET_VALUES:
                    set_question_target(
                        state, normalized_target, source="strategy_node:llm_response"
                    )
                elif normalized_target == "null" or normalized_target == "none":
                    set_question_target(state, None, source="strategy_node:llm_null")
                else:
                    set_question_target(state, None, source="strategy_node:llm_unknown")
            else:
                set_question_target(state, None, source="strategy_node:no_target")

            # Filter suggested responses with relevance scoring
            raw_suggestions = j.get("suggested_responses", []) or []
            _debug(f"Raw LLM suggested_responses: {raw_suggestions}")
            state.suggested_responses = _get_suggestions_with_fallback(
                raw_suggestions, state, state.question_target
            )
            _debug_suggestions(state.suggested_responses, source="strategy_node")

            # Only set ready_to_generate if explicitly triggered
            state.ready_to_generate = bool(j.get("ready_to_generate", False)) and state.flags.get(
                "generate_requested", False
            )

            # Only emit branches if generate was explicitly requested
            if state.flags.get("generate_requested", False):
                raw_branches = j.get("branches", []) or []
                fallback = state.trip_inputs.model_dump(exclude_none=True)
                normalized_branches: List[Dict[str, Any]] = []
                for b in raw_branches:
                    normalized = _normalize_branch_spec(b, fallback)
                    if normalized:
                        normalized_branches.append(normalized)
                state.branches = normalized_branches

            state.metadata["model_used"] = llm_config["model_hint"]
            state.metadata["token_estimate"] = _count_tokens(out)
            state.metadata["strategy_stage"] = stage_name

            # =========================================================================
            # TWO-STAGE EXPANSION STATE MANAGEMENT
            # =========================================================================
            if stage_name == "stage1":
                # Stage 1 complete: Set pending expansion flag
                state.pending_strategy_expansion = True
                # Add expansion prompt to suggestions
                if "Show more details" not in state.suggested_responses:
                    state.suggested_responses = ["Show more details"] + state.suggested_responses[
                        :2
                    ]
                _debug(
                    "📋 STRATEGY STAGE 1 COMPLETE: pending_strategy_expansion=True",
                    topic=topic,
                )
            elif stage_name == "stage2":
                # Stage 2 complete: Clear pending expansion flag
                state.pending_strategy_expansion = False
                _debug(
                    "🔍 STRATEGY STAGE 2 COMPLETE: Full itinerary delivered",
                    topic=topic,
                )

            # Cache the strategy result for future identical requests (5-min TTL)
            # Use section_id for section-level caching on Stage 2 expansions
            _set_strategy_cached(
                session_id,
                topic,
                core_fields_hash,
                user_text_hash,
                {
                    "assistant_message": state.last_summary,
                    "suggested_responses": state.suggested_responses,
                    "question_target": state.question_target,
                    "strategy_settings": j.get("strategy_settings", {}),
                    "expansion_tier": expansion_tier.value if expansion_tier else None,
                    "expansion_target": expansion_target.value if expansion_target else None,
                },
                section_id,
            )

            _debug_node_exit("strategy_node", state)
            return state

        except json.JSONDecodeError as e:
            last_error = e
            _debug_error(f"Strategy {topic} JSON error on attempt {attempt + 1}", error=str(e))
            if attempt < attempts - 1:
                system_prompt += INVALID_JSON_HINT
                continue
            break
        except Exception as e:
            last_error = e
            _debug_error(f"Strategy {topic} error on attempt {attempt + 1}", error=str(e))
            break

    reason = (
        f"strategy node for {topic} produced invalid output after {attempts} attempt(s): "
        f"{last_error}"
    )
    _debug_error(f"Strategy {topic} failed", reason=reason)
    return _record_llm_failure(state, reason)


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
    _debug_node_entry("validate_and_merge", state)

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
            if isinstance(err, NormalizationError) and err.code in DATE_BLOCKING_ERROR_CODES:
                has_blocking_date_errors = True
                break
            if isinstance(err, str) and any(code in err for code in DATE_BLOCKING_ERROR_CODES):
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
    _debug_node_exit("validate_and_merge", state)
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

    # MVP OPTIMIZATION: Use response_provenance as single-source-of-truth
    # This is the preferred method - decoupled from routing flags
    provenance = get_response_provenance(s)
    if provenance == "template":
        return True, "provenance:template"
    if provenance == "deterministic":
        return True, "provenance:deterministic"
    if provenance == "codegen":
        return True, "provenance:codegen"

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
# Apply simple deterministic rules to add warmth before falling back to LLM.
# This saves ~200-400 tokens per message that can be polished rule-based.

# Warm openers to prepend to dry messages
_WARM_OPENERS = [
    "Great choice! ",
    "Sounds wonderful! ",
    "Perfect! ",
    "Excellent! ",
    "Love it! ",
    "That's exciting! ",
]

# Warm closers to append to messages ending abruptly
_WARM_CLOSERS = [
    " Let me know if you'd like more details!",
    " Happy to help with more specifics!",
    " Just say the word if you need anything else!",
    " Feel free to ask if you have questions!",
]


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
            opener_idx = hash(msg) % len(_WARM_OPENERS)
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
            closer_idx = hash(msg) % len(_WARM_CLOSERS)
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
    Polish the assistant message for a more natural, travel-agent-like tone.
    Uses a lightweight LLM call with hard timeout cap.

    MVP Mode (enable_response_polish_mvp=False):
    When MVP mode is active, only deterministic polish is applied.
    LLM polish is skipped entirely to avoid timeout/reliability issues.
    """
    import time

    _debug_node_entry("response_polish", state)

    # Check if we should skip polishing
    should_skip, skip_reason = _should_skip_polish(state)
    if should_skip:
        state.metadata["polish_skipped_reason"] = skip_reason
        _polish_stats["polish_skipped"] += 1
        _debug(f"Response polish skipped: {skip_reason}")
        _debug_node_exit("response_polish", state)
        return state

    # =========================================================================
    # DETERMINISTIC POLISH (Always applied - MVP safe transforms only)
    # =========================================================================
    # Apply simple rule-based polish:
    # - Trim whitespace
    # - Normalize double newlines
    # - Ensure message ends with ? when question_target is set
    # - Warm openers/closers for short dry messages
    # NEVER changes question_target or suggested_responses
    deterministic_result = _try_deterministic_polish(state.last_summary, state)
    if deterministic_result is not None:
        state.last_summary = deterministic_result
        _polish_stats["deterministic_polish"] += 1
        _debug(
            "📝 DETERMINISTIC_POLISH: Applied",
            method=state.metadata.get("polish_method", "deterministic"),
            tokens_saved="~200-400",
        )
        # In MVP mode, stop here - no LLM polish
        if not settings.enable_response_polish_mvp:
            _debug("MVP mode: LLM polish disabled, using deterministic only")
            state.metadata["polish_mvp_mode"] = True
            _debug_node_exit("response_polish", state)
            return state

    # =========================================================================
    # MVP MODE CHECK: Skip LLM polish entirely in MVP mode
    # =========================================================================
    if not settings.enable_response_polish_mvp:
        _debug("MVP mode: LLM polish disabled")
        state.metadata["polish_mvp_mode"] = True
        state.metadata["polish_skipped_reason"] = "mvp_mode"
        _debug_node_exit("response_polish", state)
        return state

    # =========================================================================
    # LLM-BASED POLISH (fallback for complex messages - non-MVP only)
    # =========================================================================
    _polish_stats["llm_polish"] += 1
    # Get per-node LLM configuration
    llm_config = _get_node_llm_config("response_polish")

    # Build the polish prompt
    try:
        prompt = load_prompt("response_polish")
        trip_dests = state.trip_inputs.destinations
        destinations = ", ".join(trip_dests) if trip_dests else ""
        tpl = (
            prompt.replace("{assistant_message}", state.last_summary or "")
            .replace("{user_tone}", state.metadata.get("user_tone", "neutral"))
            .replace("{user_intent}", state.metadata.get("user_intent", "detailed_planner"))
            .replace("{destinations}", destinations or "not specified yet")
        )

        # LLM Budget Gate: Skip polish if budget exhausted (polish is optional enhancement)
        if not can_call_llm(state, "response_polish"):
            _debug("⚠️ response_polish: LLM budget exhausted, skipping polish")
            state.metadata["polish_skipped_reason"] = "llm_budget_exhausted"
            _debug_node_exit("response_polish", state)
            return state

        # Use hard timeout cap from settings (convert ms to seconds)
        timeout_seconds = settings.response_polish_timeout_ms / 1000.0

        start_time = time.perf_counter()

        out = await call_llm_with_timeout(
            model=llm_config["model_hint"],
            prompt=tpl,
            timeout_seconds=timeout_seconds,
            max_tokens=llm_config["max_tokens"],
            temperature=llm_config["temperature"],
        )
        _increment_llm_calls(state)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        _record_llm_time(state, elapsed_ms)
        state.metadata["polish_duration_ms"] = round(elapsed_ms, 2)
        state.metadata["polish_method"] = "llm"

        # Log warning if approaching timeout
        if elapsed_ms > settings.response_polish_warn_threshold_ms:
            _debug(
                f"Response polish took {elapsed_ms:.0f}ms (warn threshold: "
                f"{settings.response_polish_warn_threshold_ms}ms)"
            )

        # Parse and apply polished message
        j = jloads_safe(out)
        polished = j.get("polished_message", "").strip()

        if polished and len(polished) > 10:
            _debug(
                "Response polished",
                original_len=len(state.last_summary or ""),
                polished_len=len(polished),
            )
            state.last_summary = polished
        else:
            _debug("Polish returned empty/short response, keeping original")
            state.metadata["polish_skipped_reason"] = "empty_response"

    except TimeoutError:
        # Hard timeout - use original message
        state.metadata["polish_skipped_reason"] = "timeout"
        state.metadata["polish_duration_ms"] = settings.response_polish_timeout_ms
        _debug(f"Response polish timed out after {settings.response_polish_timeout_ms}ms")

    except Exception as exc:
        # Any other error - use original message, don't fail the request
        state.metadata["polish_skipped_reason"] = f"error: {str(exc)[:50]}"
        _debug_error("Response polish failed", error=str(exc))

    _debug_node_exit("response_polish", state)
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


def summarize(state: GraphState) -> GraphState:
    """Optional micro-summarizer node."""
    _debug_node_entry("summarize", state)
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

    # =========================================================================
    # SAFETY SNIPPET AUGMENTATION
    # =========================================================================
    # Append safety snippet for international travel if not already shown
    if state.last_summary:
        state.last_summary = _maybe_append_safety_snippet(state)

    _debug_node_exit("summarize", state)
    return state


# -----------------------
# Branch post-processing (new node)
# -----------------------
def branch_postprocess(state: GraphState) -> GraphState:
    """
    Post-process branches: split by destination if multi_city_intent != 'multi_city',
    normalize all branch specs, and generate unique IDs.
    """
    _debug_node_entry("branch_postprocess", state)

    if not state.branches:
        _debug("No branches to post-process")
        _debug_node_exit("branch_postprocess", state)
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
    _debug_node_exit("branch_postprocess", state)
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


# Tile cache for the current session (simple in-memory cache)
_tile_cache: Dict[str, Any] = {}


def ensure_tiles(
    state: "GraphState",
    intent: str,
    timeout_ms: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Ensure tiles are available for grounding, with caching.

    Args:
        state: Current graph state
        intent: The specialist intent
        timeout_ms: Optional timeout override (defaults to settings.tile_search_timeout_ms)

    Returns:
        Dict of tiles if available, None if not needed or failed
    """
    # Gate check
    if not needs_tiles(intent, state) or not should_run_tile_search(state, intent):
        return None

    # Build cache key
    ti = state.trip_inputs
    cache_key = f"{intent}:{','.join(ti.destinations or [])}:{ti.start_date}:{ti.origin}"

    # Check cache
    if cache_key in _tile_cache:
        _debug(f"Tile cache hit for {intent}", cache_key=cache_key[:50])
        state.metadata["tile_cache_hit"] = True
        return _tile_cache[cache_key]

    # Call tile service (would integrate with actual tile search here)
    # For now, mark that we need tiles but don't have them
    state.metadata["tile_cache_miss"] = True
    state.metadata["tiles_needed_for"] = intent

    return None


def clear_tile_cache() -> int:
    """Clear the tile cache. Returns count of cleared entries."""
    global _tile_cache
    count = len(_tile_cache)
    _tile_cache.clear()
    return count


# -----------------------
# Tile search node (integrated with tile_service)
# -----------------------
def tile_search(state: GraphState) -> GraphState:
    """
    Search for tiles based on branches and booking_types.
    Calls tile_service.search_tiles for each branch.

    MVP Hardening: Now includes strict gating on core field readiness.
    """
    _debug_node_entry("tile_search", state)

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
        _debug_node_exit("tile_search", state)
        return state

    # Check if any booking types are enabled
    booking_types = state.trip_inputs.booking_types or {}
    any_enabled = any(booking_types.values())

    if not any_enabled:
        _debug("No booking types enabled, skipping tile search")
        _debug_node_exit("tile_search", state)
        return state

    if not state.branches:
        _debug("No branches to search tiles for")
        _debug_node_exit("tile_search", state)
        return state

    ti = state.trip_inputs
    tiles_dict: Dict[str, Any] = {}

    # Determine which verticals to search based on booking_types
    verticals: List[str] = []
    if booking_types.get("hotels"):
        verticals.append("hotel")
    if booking_types.get("flights"):
        verticals.append("flight")
    if booking_types.get("activities"):
        verticals.append("activity")

    if not verticals:
        _debug("No verticals enabled despite booking types set")
        _debug_node_exit("tile_search", state)
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

        try:
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
                verticals=verticals,  # type: ignore
                max_results_per_vertical=5,
                budget=ti.budget,  # Pass budget for tile filtering
            )

            _debug(f"Searching tiles for branch {branch_id}", destination=primary_dest)
            tiles_response = search_tiles(tiles_request)

            # Store tiles and update branch tile IDs
            branch_tiles: Dict[str, List[str]] = {"stays": [], "flights": [], "activities": []}

            for tile in tiles_response.tiles:
                tiles_dict[tile.id] = tile.model_dump()
                if tile.type == "hotel":
                    branch_tiles["stays"].append(tile.id)
                elif tile.type == "flight":
                    branch_tiles["flights"].append(tile.id)
                elif tile.type == "activity":
                    branch_tiles["activities"].append(tile.id)

            # Update branch with tile IDs
            branch["tiles"] = branch_tiles

            _debug(
                f"Tiles found for branch {branch_id}",
                hotels=len(branch_tiles["stays"]),
                flights=len(branch_tiles["flights"]),
                activities=len(branch_tiles["activities"]),
            )

        except Exception as e:
            _debug_error(f"Tile search failed for branch {branch_id}", error=str(e))
            continue

    # Store tiles in metadata for later persistence
    state.metadata["tiles"] = tiles_dict
    state.metadata["tile_search_attempted"] = True
    state.metadata["tile_search_booking_types"] = verticals

    _debug(
        "Tile search completed",
        total_tiles=len(tiles_dict),
        enabled_verticals=verticals,
    )
    _debug_node_exit("tile_search", state)
    return state


# -----------------------
# Generate responder (handles GENERATE_PLAN_NOW trigger)
# -----------------------
def generate_responder(state: GraphState) -> GraphState:
    """
    Handle explicit plan generation requests.

    This node is reached when the user triggers plan generation
    (e.g., "GENERATE_PLAN_NOW" or confirmation of generate action).

    It creates default branches from trip_inputs and sets ready_to_generate=True.
    When the user explicitly requests generation, we proceed even with partial data.
    """
    _debug_node_entry("generate_responder", state)

    ti = state.trip_inputs

    # Minimum requirement: at least destinations must be set
    # When user explicitly requests generation, we're more lenient
    if not ti.destinations or len(ti.destinations) == 0:
        # Absolutely cannot generate without destinations
        state.last_summary = (
            "I need at least a destination to generate your plan. Where would you like to go?"
        )
        state.question_target = "destinations"
        state.ready_to_generate = False
        _debug("Generate blocked - no destinations")
        _debug_node_exit("generate_responder", state)
        return state

    # All core fields complete - create branches and set ready
    state.ready_to_generate = True
    state.last_summary = "Great! Generating your travel plan now..."

    # Create a default branch from trip_inputs
    fallback_inputs = ti.model_dump(exclude_none=True)
    default_branch = {
        "id": uuid4().hex[:8],
        "label": f"{ti.destinations[0]} Trip" if ti.destinations else "Your Trip",
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
    }

    normalized = _normalize_branch_spec(default_branch, fallback_inputs)
    if normalized:
        state.branches = [normalized]
    else:
        # Fallback to the raw branch if normalization fails
        state.branches = [default_branch]

    _debug(
        "Generate responder complete",
        ready=state.ready_to_generate,
        branches=len(state.branches),
    )
    _debug_node_exit("generate_responder", state)
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
    _debug_node_entry("short_circuit_responder", state)

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
                    state.last_summary = "Generating your travel plan..."
                else:
                    state.last_summary = follow_up
            else:
                state.last_summary = follow_up
        else:
            # No follow-up needed, we might be ready to generate
            state.last_summary = (
                "Looks like I have everything I need! Ready to generate your travel plan?"
            )
            state.metadata["pending_action"] = "generate_plan"
            state.metadata["last_question_field"] = None  # Clear - we're asking for confirmation
            state.question_target = None

    # Always regenerate contextual suggestions to match the current question
    # (Previous suggestions may be stale from a different question)
    # Note: We no longer use static fallback suggestions - LLM generates them
    question_target = state.metadata.get("last_question_field")
    state.question_target = question_target
    state.suggested_responses = []  # LLM will generate context-aware suggestions
    _debug_suggestions(state.suggested_responses, source="short_circuit_responder")

    # Set intent for logging purposes
    state.intent = f"short_circuit:{sc_type}"

    _debug_node_exit("short_circuit_responder", state)
    return state


# -----------------------
# Conditional routing after normalize_inputs
# -----------------------
def route_after_normalize(state: GraphState) -> str:
    """
    Route after normalize_inputs completes.

    Phase 6: Uses centralized GateEvaluator for all routing decisions.
    Gate evaluation is done once and results are applied to state.

    Routing priority (via GateEvaluator):
    1. SHORT_CIRCUIT → short_circuit_responder (no LLM)
    2. INFEASIBILITY_DETECTION → correction_node (no LLM)
    3. FAST_PATH → required_fields_node (no LLM)
    4. CORE_COLLECTION → required_fields_node (no LLM)
    5. HIGH_CONFIDENCE → required_fields_node (no LLM)
    6. QUESTION_KEYWORD → specialist nodes (no LLM) [Phase 6]
    7. KEYWORD_HEURISTIC → specialist nodes (no LLM)
    8. ROUTER_LLM → router (LLM fallback)
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
        "HIGH_CONFIDENCE": "high_confidence_fired",
        "QUESTION_KEYWORD": "question_keyword_fired",
        "KEYWORD_HEURISTIC": "keyword_heuristic_fired",
        "SCORING_ROUTER": "scoring_router_fired",
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
    elif gate_fired_name == "HIGH_CONFIDENCE":
        _routing_stats["high_conf_bypasses"] += 1
    elif gate_fired_name in ("KEYWORD_HEURISTIC", "QUESTION_KEYWORD", "SCORING_ROUTER"):
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
    _debug("RUN_TURN START", user_text=user_text[:100] if len(user_text) > 100 else user_text)
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
    # LLM BUDGET: Reset per-turn counters
    # =========================================================================
    # TODO: Rename llm_calls_this_turn -> llm_budget_used after tests pass
    metadata["llm_calls_this_turn"] = 0
    metadata["llm_call_blocked_reason"] = {}  # v5: dict for per-node tracking
    metadata["llm_nodes_called_this_turn"] = []  # v5: track which nodes called LLM
    metadata["deltas_applied_this_turn"] = []  # v5: track field changes this turn
    metadata["response_source_node"] = None  # v5: first node to produce response
    metadata["response_provenance"] = None  # v5: provenance of response
    # Note: llm_call_blocked_count is cumulative (not reset per turn)

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

    state = GraphState(
        user_text=user_text,
        trip_inputs=TripInputs(**session_state.get("trip_inputs", {})),
        metadata=metadata,
        flags=incoming_flags,
        last_summary=session_state.get("last_summary"),
        branches=deepcopy(session_state.get("branches", [])),
        suggested_responses=deepcopy(session_state.get("suggested_responses", [])),
        errors=deepcopy(session_state.get("errors", [])),
        chat_history=deepcopy(
            session_state.get("chat_history", [])
        ),  # Pass chat history for LLM context
        # Persist strategy expansion context across turns
        strategy_expansion_tier=session_state.get("strategy_expansion_tier"),
        strategy_expansion_target=session_state.get("strategy_expansion_target"),
        # Carry forward loop guard and turn tracking state
        loop_guard=deepcopy(session_state.get("loop_guard", {})),
        questions_asked=deepcopy(session_state.get("questions_asked", {})),
        turn_number=session_state.get("turn_number", 0),
    )

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
            fallback_msg = (
                f"I'm still working on your trip to {', '.join(destinations)}. "
                "What would you like to focus on next?"
            )
        else:
            fallback_msg = "I'd love to help plan your trip! Where would you like to go?"
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
        if readiness.missing_core:
            next_field = readiness.missing_core[0]
            result.question_target = canonicalize_question_target(next_field)
            result_meta["question_target"] = result.question_target
            if next_field == "destinations":
                result.last_summary = "Where would you like to go?"
                result.suggested_responses = ["Paris, France", "Tokyo, Japan", "Bali, Indonesia"]
            elif next_field == "origin":
                result.last_summary = "Where will you be traveling from?"
                result.suggested_responses = ["New York", "London", "Los Angeles"]
            elif next_field in ("start_date", "dates"):
                result.last_summary = "When are you planning to travel?"
                result.suggested_responses = ["Next month", "This summer", "I'm flexible"]
            else:
                result.last_summary = "What else would you like to tell me about your trip?"
                result.suggested_responses = ["Add details", "Generate plan", "Start over"]
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
            response_provenance=result_meta.get("response_provenance", "unknown"),
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
        _debug(
            "ROUTING_DECISION_FINAL",
            schema_version=routing_decision_final.schema_version,
            gate_destination=gate_result_snapshot.destination,
            executed_node=executed_node,
            redirect_reason=redirect_reason,
            response_provenance=routing_decision_final.response_provenance,
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

    # Assemble response
    resp = {
        "assistant_message": result.last_summary or "",
        "trip_inputs": result.trip_inputs.model_dump(exclude_none=True),
        "ready_to_generate": result.ready_to_generate,
        "branches": result.branches,
        "suggested_responses": result.suggested_responses,
        "errors": result.errors,
        "run_id": langsmith_run_id,  # LangSmith trace ID for E2E evaluation
        "session_state": {
            "trip_inputs": result.trip_inputs.model_dump(),
            "metadata": result_meta,
            "flags": result_flags,
            "last_summary": result.last_summary,
            "branches": result.branches,
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
            "strategy_expansion_tier": getattr(result, "strategy_expansion_tier", None),
            "strategy_expansion_target": getattr(result, "strategy_expansion_target", None),
            # State integrity tracking (Phase 1)
            "loop_guard": getattr(result, "loop_guard", {}),
            "questions_asked": getattr(result, "questions_asked", {}),
            "turn_number": getattr(result, "turn_number", 0),
            # State counters for observability
            "state_counters": _get_state_counters(),
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
    _debug(
        "RUN_TURN_STREAMING START", user_text=user_text[:100] if len(user_text) > 100 else user_text
    )
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

    state = GraphState(
        user_text=user_text,
        trip_inputs=TripInputs(**session_state.get("trip_inputs", {})),
        metadata=metadata,
        flags=incoming_flags,
        last_summary=session_state.get("last_summary"),
        branches=deepcopy(session_state.get("branches", [])),
        suggested_responses=deepcopy(session_state.get("suggested_responses", [])),
        errors=deepcopy(session_state.get("errors", [])),
        chat_history=deepcopy(session_state.get("chat_history", [])),
        # Persist question_target across turns for LQA to intercept direct answers
        question_target=session_state.get("question_target"),
        # Persist strategy_topic for topic-aware template suggestions
        strategy_topic=session_state.get("strategy_topic"),
        # Persist strategy expansion context across turns
        strategy_expansion_tier=session_state.get("strategy_expansion_tier"),
        strategy_expansion_target=session_state.get("strategy_expansion_target"),
        # Carry forward loop guard and turn tracking state
        loop_guard=deepcopy(session_state.get("loop_guard", {})),
        questions_asked=deepcopy(session_state.get("questions_asked", {})),
        turn_number=session_state.get("turn_number", 0),
    )

    # Phase 1: Capture pre-turn snapshot for state integrity checking
    _ = capture_pre_turn_snapshot(state)

    # Use a unique thread_id per turn
    turn_thread_id = f"{thread_id}_{uuid4().hex[:8]}"

    # Run the full graph (non-streaming) to get final state
    # Note: We run the full graph first, then stream the final message
    # This ensures all extractions complete before we start streaming
    result: GraphState | dict
    try:
        result = await app.ainvoke(state, config={"configurable": {"thread_id": turn_thread_id}})
    except StateRegressionError as e:
        # State integrity violation detected - recover using snapshot
        _debug_error(
            "StateRegressionError caught in run_turn_streaming",
            node=e.node_name,
            diff_summary=e.diff_summary,
        )
        state = handle_state_regression_error(state, e)
        result = state

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

    # Determine if this was a short-circuit or polish-skipped path
    polish_skipped = result_meta.get("polish_skipped_reason")
    is_short_circuit = bool(result_flags.get("short_circuit"))

    # Stream the message
    if final_message:
        if polish_skipped or is_short_circuit:
            # Simulated streaming for code-generated messages
            _debug(
                "Simulating streaming for code-generated response",
                reason=polish_skipped or "short_circuit",
            )
            async for token in simulate_streaming(final_message):
                yield {"type": "token", "data": token}
        else:
            # For LLM-polished responses, we already have the complete response
            # (since we ran the full graph). Stream it with simulated timing
            # to provide consistent UX.
            #
            # Note: True LLM streaming would require restructuring the graph
            # to run response_polish as a separate streaming call. For now,
            # we simulate to maintain UX consistency.
            _debug("Simulating streaming for polished response")
            async for token in simulate_streaming(final_message):
                yield {"type": "token", "data": token}

    # Build final response (same as run_turn)
    resp = {
        "assistant_message": final_message,
        "trip_inputs": result.trip_inputs.model_dump(exclude_none=True),
        "ready_to_generate": result.ready_to_generate,
        "branches": result.branches,
        "suggested_responses": result.suggested_responses,
        "errors": result.errors,
        "session_state": {
            "trip_inputs": result.trip_inputs.model_dump(),
            "metadata": result_meta,
            "flags": result_flags,
            "last_summary": result.last_summary,
            "branches": result.branches,
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
            "strategy_expansion_tier": getattr(result, "strategy_expansion_tier", None),
            "strategy_expansion_target": getattr(result, "strategy_expansion_target", None),
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
    # Convert booking_types dict to BookingTypes model
    booking_types_data = ti.booking_types or {}
    booking_types = BookingTypes(
        hotels=booking_types_data.get("hotels", False),
        flights=booking_types_data.get("flights", False),
        ground_transport=booking_types_data.get("ground_transport", False),
        activities=booking_types_data.get("activities", False),
    )

    # Convert flight_settings dict to FlightSettings model
    flight_settings_data = ti.flight_settings or {}
    flight_settings = FlightSettings(
        round_trip=flight_settings_data.get("round_trip", True),
        cabin_class=flight_settings_data.get("cabin_class", "economy"),
        direct_only=flight_settings_data.get("direct_only", False),
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
) -> List[DocumentBranch]:
    """Convert graph branches to DocumentBranch list for persistence."""
    doc_branches: List[DocumentBranch] = []

    for idx, spec in enumerate(branches):
        branch_destinations = spec.get("destinations", []) or []
        if not isinstance(branch_destinations, list):
            branch_destinations = [branch_destinations] if branch_destinations else []

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

        # 2. Record user message
        user_message_content = (
            "Generate my trip options" if _is_generate_plan_trigger(req.message) else req.message
        )
        await record_chat_message(
            db,
            session=db_session,
            trip_context=trip_ctx,
            role="user",
            content=user_message_content,
            metadata=None,
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

        session_state = {
            "trip_inputs": initial_trip_inputs,
            "branches": initial_branches,
            "metadata": {
                "today_iso": today_iso,
                "tiles": (
                    {t_id: t.model_dump() for t_id, t in (existing_doc_data.tiles or {}).items()}
                    if existing_doc_data
                    else {}
                ),
            },
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
        if result_branches:
            doc_branches = _branches_to_document(result_branches, trip_ctx.id)

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
