# backend/app/planner/telemetry.py
"""
Telemetry spine for comprehensive live traces.

PR-T1: Correlation + Trace Envelope
PR-T2: Structured Event Stream + Latency Breakdown
PR-T3: Redaction + Sampling + Anomaly Bundles

Provides:
- TraceEnvelope: Correlation IDs for joining request → planner → nodes → LLM → cache
- emit_event(): Structured JSON logging with console visibility
- Redaction utilities for PII protection
- Sampling logic with forced-verbose on anomaly
- Anomaly bundle emission for post-mortem debugging
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

# Import stable_hash from hashing module (no circular import)
from app.planner.hashing import stable_hash

if TYPE_CHECKING:
    from fastapi import Request

# =============================================================================
# LOGGING SETUP
# =============================================================================

# Create a dedicated logger for trace events
_trace_logger = logging.getLogger("planner.trace")
_trace_logger.setLevel(logging.DEBUG)

# Ensure at least one handler exists (StreamHandler for console)
if not _trace_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setLevel(logging.DEBUG)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _trace_logger.addHandler(_handler)


# =============================================================================
# W3C TRACEPARENT PARSING
# =============================================================================

# W3C Trace Context format: 00-<trace_id>-<span_id>-<flags>
_TRACEPARENT_PATTERN = re.compile(r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")


def parse_traceparent(header: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse W3C traceparent header.

    Format: {version}-{trace_id}-{parent_id}-{flags}
    Example: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01

    Returns:
        Tuple of (trace_id, span_id) or (None, None) if invalid/missing
    """
    if not header:
        return None, None

    match = _TRACEPARENT_PATTERN.match(header.lower().strip())
    if not match:
        return None, None

    version, trace_id, span_id, flags = match.groups()

    # Version 00 is the only supported version
    if version != "00":
        return None, None

    # All-zero trace_id or span_id is invalid
    if trace_id == "0" * 32 or span_id == "0" * 16:
        return None, None

    return trace_id, span_id


# =============================================================================
# TRACE ENVELOPE
# =============================================================================


@dataclass
class TraceEnvelope:
    """
    Correlation envelope for joining all events in a request lifecycle.

    Created once per request, injected into state.metadata["trace_envelope"],
    and propagated through all planner operations.
    """

    # Core correlation IDs
    trace_id: str  # Unique per request (from traceparent or generated)
    request_id: str  # From X-Request-ID header or generated
    thread_id: str  # Conversation thread ID
    session_id: str  # User session ID
    turn_id: str  # Per-turn unique ID (from turn canary)

    # Build metadata (for version correlation)
    planner_build_id: str = ""
    prompt_bundle_hash: str = ""
    cache_schema_version: str = ""

    # Sampling decisions (computed once per request)
    trace_enabled: bool = True
    trace_verbose: bool = False
    redaction_mode: str = "hash_only"  # "hash_only" | "verbose"

    # Process info (for multi-worker debugging)
    pid: int = field(default_factory=os.getpid)

    # W3C traceparent span_id (if received)
    parent_span_id: Optional[str] = None

    # Request-level event GUID for deduplication
    event_guid: str = field(default_factory=lambda: uuid.uuid4().hex[:16])

    def to_dict(self) -> Dict[str, Any]:
        """Convert envelope to dictionary for storage in metadata."""
        return {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "thread_id": self.thread_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "planner_build_id": self.planner_build_id,
            "prompt_bundle_hash": self.prompt_bundle_hash,
            "cache_schema_version": self.cache_schema_version,
            "trace_enabled": self.trace_enabled,
            "trace_verbose": self.trace_verbose,
            "redaction_mode": self.redaction_mode,
            "pid": self.pid,
            "parent_span_id": self.parent_span_id,
            "event_guid": self.event_guid,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TraceEnvelope":
        """Reconstruct envelope from dictionary."""
        return cls(
            trace_id=data.get("trace_id", ""),
            request_id=data.get("request_id", ""),
            thread_id=data.get("thread_id", ""),
            session_id=data.get("session_id", ""),
            turn_id=data.get("turn_id", ""),
            planner_build_id=data.get("planner_build_id", ""),
            prompt_bundle_hash=data.get("prompt_bundle_hash", ""),
            cache_schema_version=data.get("cache_schema_version", ""),
            trace_enabled=data.get("trace_enabled", True),
            trace_verbose=data.get("trace_verbose", False),
            redaction_mode=data.get("redaction_mode", "hash_only"),
            pid=data.get("pid", os.getpid()),
            parent_span_id=data.get("parent_span_id"),
            event_guid=data.get("event_guid", uuid.uuid4().hex[:16]),
        )


def compute_sampling(
    trace_sample_rate: float = 0.05,
    trace_verbose_sample_rate: float = 0.001,
) -> Tuple[bool, bool]:
    """
    Compute sampling decisions for a request.

    Sampling is computed once per request to ensure all events
    for a request are either all traced or all skipped.

    Args:
        trace_sample_rate: Probability of enabling trace (0.0 to 1.0)
        trace_verbose_sample_rate: Probability of verbose trace (0.0 to 1.0)

    Returns:
        Tuple of (trace_enabled, trace_verbose)
    """
    trace_enabled = random.random() < trace_sample_rate
    trace_verbose = trace_enabled and random.random() < trace_verbose_sample_rate
    return trace_enabled, trace_verbose


def create_envelope(
    request: Optional["Request"],
    thread_id: str,
    session_id: str,
    turn_id: str = "",
    planner_build_id: str = "",
    prompt_bundle_hash: str = "",
    cache_schema_version: str = "",
    trace_sample_rate: float = 1.0,  # Default to 100% for dev; config overrides
    trace_verbose_sample_rate: float = 0.0,
    redaction_mode: str = "hash_only",
    force_trace: bool = False,
    force_verbose: bool = False,
) -> TraceEnvelope:
    """
    Create a TraceEnvelope for a new request.

    Header precedence for trace_id:
    1. W3C traceparent header → extract trace_id
    2. X-Request-ID header → use as request_id, generate trace_id
    3. Generate both

    Args:
        request: FastAPI Request object (may be None for tests)
        thread_id: Conversation thread ID
        session_id: User session ID
        turn_id: Per-turn unique ID
        planner_build_id: Planner build version
        prompt_bundle_hash: Hash of prompt bundle
        cache_schema_version: Cache schema version
        trace_sample_rate: Sampling rate for trace
        trace_verbose_sample_rate: Sampling rate for verbose trace
        redaction_mode: "hash_only" or "verbose"
        force_trace: Force trace_enabled=True (for anomalies)
        force_verbose: Force trace_verbose=True (for anomalies)

    Returns:
        TraceEnvelope with all correlation IDs populated
    """
    trace_id: Optional[str] = None
    parent_span_id: Optional[str] = None
    request_id: Optional[str] = None

    # Extract headers if request is available
    if request is not None:
        # Try W3C traceparent first
        traceparent = request.headers.get("traceparent")
        if traceparent:
            trace_id, parent_span_id = parse_traceparent(traceparent)

        # Try X-Request-ID
        if not request_id:
            request_id = request.headers.get("x-request-id")

    # Generate missing IDs
    if not trace_id:
        trace_id = uuid.uuid4().hex

    if not request_id:
        request_id = str(uuid.uuid4())

    if not turn_id:
        turn_id = uuid.uuid4().hex[:16]

    # Compute sampling
    trace_enabled, trace_verbose = compute_sampling(trace_sample_rate, trace_verbose_sample_rate)

    # Apply force flags
    if force_trace:
        trace_enabled = True
    if force_verbose:
        trace_verbose = True

    return TraceEnvelope(
        trace_id=trace_id,
        request_id=request_id,
        thread_id=thread_id,
        session_id=session_id,
        turn_id=turn_id,
        planner_build_id=planner_build_id,
        prompt_bundle_hash=prompt_bundle_hash,
        cache_schema_version=cache_schema_version,
        trace_enabled=trace_enabled,
        trace_verbose=trace_verbose,
        redaction_mode=redaction_mode,
        parent_span_id=parent_span_id,
    )


# =============================================================================
# REDACTION UTILITIES (PR-T3)
# =============================================================================


def redact_text(text: str) -> Dict[str, Any]:
    """
    Redact user text for safe logging.

    Returns hash and length only by default.
    Raw text only logged when redaction_mode="verbose" AND trace_verbose=True.

    Args:
        text: Raw user text

    Returns:
        Dict with {"hash": str, "length": int}
    """
    return {
        "hash": stable_hash(text, length=16),
        "length": len(text),
    }


def redact_prompt(
    prompt: str,
    tokens: int = 0,
    truncated: bool = False,
) -> Dict[str, Any]:
    """
    Redact LLM prompt/response for safe logging.

    Args:
        prompt: Raw prompt or response text
        tokens: Token count
        truncated: Whether content was truncated

    Returns:
        Dict with {"hash": str, "tokens": int, "truncated": bool}
    """
    return {
        "hash": stable_hash(prompt, length=16),
        "tokens": tokens,
        "truncated": truncated,
    }


# =============================================================================
# EVENT EMISSION (PR-T1 + PR-T2)
# =============================================================================

# Prefix constants for console visibility (matching _debug style)
_TRACE_PREFIX = "[TRACE]"
_TRACE_VERBOSE_PREFIX = "[TRACE:VERBOSE]"
_TRACE_ANOMALY_PREFIX = "[TRACE:ANOMALY]"


def emit_event(
    name: str,
    payload: Dict[str, Any],
    envelope: Optional[TraceEnvelope],
    *,
    verbose_only: bool = False,
    console_output: bool = True,
) -> None:
    """
    Emit a structured trace event.

    Events are printed to console (like _debug) AND logged via Python logging
    for aggregation systems.

    Args:
        name: Event name (e.g., "planner_request_start", "node_end")
        payload: Event-specific data
        envelope: TraceEnvelope with correlation IDs
        verbose_only: Only emit if trace_verbose=True
        console_output: Print to console (default True)
    """
    if envelope is None:
        return

    if not envelope.trace_enabled:
        return

    if verbose_only and not envelope.trace_verbose:
        return

    # Build event structure
    event = {
        "event": name,
        "ts_ms": int(time.time() * 1000),
        "trace_id": envelope.trace_id,
        "request_id": envelope.request_id,
        "thread_id": envelope.thread_id,
        "turn_id": envelope.turn_id,
        **payload,
    }

    # Serialize to JSON
    try:
        json_line = json.dumps(event, default=str, ensure_ascii=True)
    except Exception:
        # Fallback for non-serializable payloads
        json_line = json.dumps(
            {"event": name, "error": "serialization_failed", "trace_id": envelope.trace_id}
        )

    # Console output for visibility (like _debug) - only in full mode
    if console_output:
        from app.debug_utils import get_debug_mode

        if get_debug_mode() in ("full", "compact"):
            from app.debug_utils import _safe_print

            prefix = _TRACE_VERBOSE_PREFIX if verbose_only else _TRACE_PREFIX
            _safe_print(f"{prefix} {name} {json_line}")

    # Also emit via logger for log aggregation
    _trace_logger.info(json_line)


def emit_anomaly_event(
    name: str,
    payload: Dict[str, Any],
    envelope: Optional[TraceEnvelope],
) -> None:
    """
    Emit an anomaly trace event (always visible).

    Anomaly events bypass sampling and are always emitted.

    Args:
        name: Event name (e.g., "planner_anomaly_bundle")
        payload: Event-specific data
        envelope: TraceEnvelope with correlation IDs
    """
    if envelope is None:
        # Create minimal envelope for anomaly logging
        event = {
            "event": name,
            "ts_ms": int(time.time() * 1000),
            **payload,
        }
    else:
        event = {
            "event": name,
            "ts_ms": int(time.time() * 1000),
            "trace_id": envelope.trace_id,
            "request_id": envelope.request_id,
            "thread_id": envelope.thread_id,
            "turn_id": envelope.turn_id,
            **payload,
        }

    try:
        json_line = json.dumps(event, default=str, ensure_ascii=True)
    except Exception:
        json_line = json.dumps({"event": name, "error": "serialization_failed"})

    # Print anomaly events (compact and full modes)
    from app.debug_utils import _safe_print, get_debug_mode

    if get_debug_mode() != "off":
        _safe_print(f"{_TRACE_ANOMALY_PREFIX} {name} {json_line}")
    _trace_logger.warning(json_line)


# =============================================================================
# ANOMALY BUNDLE (PR-T3)
# =============================================================================

# Maximum entries to include in anomaly bundle
ANOMALY_BUNDLE_MAX_NODE_RUNS = 50
ANOMALY_BUNDLE_MAX_CACHE_EVENTS = 50


def emit_anomaly_bundle(
    envelope: Optional[TraceEnvelope],
    anomaly_type: str,
    metadata: Dict[str, Any],  # noqa: ARG001
    *,
    planner_snapshot: Optional[Dict[str, Any]] = None,
    cache_summary: Optional[Dict[str, Any]] = None,
    cache_events: Optional[List[Dict[str, Any]]] = None,
    node_run_journal: Optional[List[Dict[str, Any]]] = None,
    llm_call_sites: Optional[List[str]] = None,
    llm_call_blocked_reason: Optional[Dict[str, str]] = None,
    duplication_class: Optional[str] = None,
    response_claimed_by: Optional[str] = None,
    tripwire_triggered: bool = False,
) -> None:
    """
    Emit a comprehensive anomaly bundle for post-mortem debugging.

    Contains all relevant state for debugging without reproduction.
    Automatically truncates large collections.

    Args:
        envelope: TraceEnvelope with correlation IDs
        anomaly_type: Type of anomaly (e.g., "tripwire_triggered", "exception")
        metadata: Additional metadata from state
        planner_snapshot: Planner version info
        cache_summary: Summarized cache stats
        cache_events: Raw cache events (truncated to last N)
        node_run_journal: Node execution journal (truncated to last N)
        llm_call_sites: LLM call sites this turn
        llm_call_blocked_reason: Blocked LLM calls with reasons
        duplication_class: Duplication detection marker
        response_claimed_by: Single response writer
        tripwire_triggered: Whether tripwire fired
    """
    _ = metadata
    # Truncate large collections
    cache_events_tail = (cache_events or [])[-ANOMALY_BUNDLE_MAX_CACHE_EVENTS:]
    node_runs_tail = (node_run_journal or [])[-ANOMALY_BUNDLE_MAX_NODE_RUNS:]

    bundle_truncated = (
        len(cache_events or []) > ANOMALY_BUNDLE_MAX_CACHE_EVENTS
        or len(node_run_journal or []) > ANOMALY_BUNDLE_MAX_NODE_RUNS
    )

    payload = {
        "anomaly_type": anomaly_type,
        "planner_snapshot": planner_snapshot or {},
        "cache_summary": cache_summary or {},
        "cache_events_tail": cache_events_tail,
        "node_run_journal_tail": node_runs_tail,
        "llm_call_sites": llm_call_sites or [],
        "llm_call_blocked_reason": llm_call_blocked_reason or {},
        "duplication_class": duplication_class,
        "response_claimed_by": response_claimed_by,
        "tripwire_triggered": tripwire_triggered,
        "bundle_truncated": bundle_truncated,
        "bundle_caps": {
            "node_runs": ANOMALY_BUNDLE_MAX_NODE_RUNS,
            "cache_events": ANOMALY_BUNDLE_MAX_CACHE_EVENTS,
        },
    }

    emit_anomaly_event("planner_anomaly_bundle", payload, envelope)


# =============================================================================
# FORCE VERBOSE ON ANOMALY
# =============================================================================


def force_verbose_on_anomaly(envelope: TraceEnvelope, metadata: Dict[str, Any]) -> None:
    """
    Force trace_verbose=True when anomaly conditions are detected.

    Called when:
    - tripwire_triggered is set
    - duplication_class is set
    - exception is caught

    Args:
        envelope: TraceEnvelope to modify
        metadata: State metadata to check for anomaly flags
    """
    from app.planner.meta_keys import DUPLICATION_CLASS, TRIPWIRE_TRIGGERED

    should_force = (
        metadata.get(TRIPWIRE_TRIGGERED, False) or metadata.get(DUPLICATION_CLASS) is not None
    )

    if should_force:
        envelope.trace_enabled = True
        envelope.trace_verbose = True


# =============================================================================
# TIMING UTILITIES (PR-T2)
# =============================================================================


def now_ns() -> int:
    """Get current time in nanoseconds (monotonic clock)."""
    return time.perf_counter_ns()


def ns_to_ms(ns: int) -> float:
    """Convert nanoseconds to milliseconds."""
    return ns / 1_000_000


def compute_duration_ms(start_ns: int, end_ns: Optional[int] = None) -> float:
    """
    Compute duration in milliseconds.

    Args:
        start_ns: Start time in nanoseconds
        end_ns: End time in nanoseconds (defaults to now)

    Returns:
        Duration in milliseconds
    """
    if end_ns is None:
        end_ns = now_ns()
    return ns_to_ms(end_ns - start_ns)


# =============================================================================
# LATENCY BREAKDOWN (PR-T2)
# =============================================================================


@dataclass
class LatencyBreakdown:
    """Latency breakdown for a request."""

    total_ms: float = 0.0
    gate_eval_ms: float = 0.0
    node_ms_total: float = 0.0
    llm_ms_total: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "total_ms": round(self.total_ms, 2),
            "gate_eval_ms": round(self.gate_eval_ms, 2),
            "node_ms_total": round(self.node_ms_total, 2),
            "llm_ms_total": round(self.llm_ms_total, 2),
        }


def compute_latency_breakdown(
    start_ns: int,
    gate_eval_ms: float = 0.0,
    node_durations_ms: Optional[List[float]] = None,
    llm_durations_ms: Optional[List[float]] = None,
) -> LatencyBreakdown:
    """
    Compute latency breakdown for a request.

    Args:
        start_ns: Request start time in nanoseconds
        gate_eval_ms: Gate evaluation time
        node_durations_ms: List of node execution durations
        llm_durations_ms: List of LLM call durations

    Returns:
        LatencyBreakdown with computed totals
    """
    total_ms = compute_duration_ms(start_ns)
    node_ms_total = sum(node_durations_ms or [])
    llm_ms_total = sum(llm_durations_ms or [])

    return LatencyBreakdown(
        total_ms=total_ms,
        gate_eval_ms=gate_eval_ms,
        node_ms_total=node_ms_total,
        llm_ms_total=llm_ms_total,
    )


# =============================================================================
# BOUNDARY EVENT HELPERS (PR-T1)
# =============================================================================


def emit_request_start(
    envelope: TraceEnvelope,
    user_text: str,
    *,
    user_text_redacted: bool = True,
) -> int:
    """
    Emit planner_request_start event.

    Args:
        envelope: TraceEnvelope
        user_text: Raw user text (will be redacted by default)
        user_text_redacted: Whether to redact user text

    Returns:
        Start time in nanoseconds for latency calculation
    """
    start_ns = now_ns()

    payload: Dict[str, Any] = {
        "pid": envelope.pid,
        "planner_build_id": envelope.planner_build_id,
        "prompt_bundle_hash": envelope.prompt_bundle_hash,
    }

    if user_text_redacted or envelope.redaction_mode == "hash_only":
        payload["user_text"] = redact_text(user_text)
    else:
        payload["user_text"] = user_text

    emit_event("planner_request_start", payload, envelope)

    return start_ns


def emit_request_end(
    envelope: TraceEnvelope,
    start_ns: int,
    *,
    selected_gate: Optional[str] = None,
    selected_node: Optional[str] = None,
    response_claimed_by: Optional[str] = None,
    llm_calls_this_turn: int = 0,
    cache_summary: Optional[Dict[str, Any]] = None,
    gate_eval_ms: float = 0.0,
    node_durations_ms: Optional[List[float]] = None,
    llm_durations_ms: Optional[List[float]] = None,
    error: Optional[str] = None,
) -> None:
    """
    Emit planner_request_end event with latency breakdown.

    Args:
        envelope: TraceEnvelope
        start_ns: Request start time from emit_request_start
        selected_gate: Gate that fired
        selected_node: Node that was routed to
        response_claimed_by: Node that wrote the response
        llm_calls_this_turn: LLM call count
        cache_summary: Cache stats summary
        gate_eval_ms: Gate evaluation time
        node_durations_ms: Node execution durations
        llm_durations_ms: LLM call durations
        error: Error message if request failed
    """
    breakdown = compute_latency_breakdown(
        start_ns=start_ns,
        gate_eval_ms=gate_eval_ms,
        node_durations_ms=node_durations_ms,
        llm_durations_ms=llm_durations_ms,
    )

    payload: Dict[str, Any] = {
        "selected_gate": selected_gate,
        "selected_node": selected_node,
        "response_claimed_by": response_claimed_by,
        "llm_calls_this_turn": llm_calls_this_turn,
        "cache_summary": cache_summary or {},
        **breakdown.to_dict(),
    }

    if error:
        payload["error"] = error

    emit_event("planner_request_end", payload, envelope)


# =============================================================================
# NODE/GATE/LLM EVENT HELPERS (PR-T2)
# =============================================================================


def emit_gate_eval_end(
    envelope: TraceEnvelope,
    gate_fired: str,
    destination: str,
    reason: str,
    duration_ms: float,
    skipped_gates: Optional[List[str]] = None,
) -> None:
    """Emit gate_eval_end event."""
    emit_event(
        "gate_eval_end",
        {
            "gate_fired": gate_fired,
            "destination": destination,
            "reason": reason,
            "duration_ms": round(duration_ms, 2),
            "skipped_gates": skipped_gates or [],
        },
        envelope,
    )


def emit_node_start(
    envelope: TraceEnvelope,
    node: str,
    event_guid: str,
    inputs_hash: Optional[str] = None,
) -> None:
    """Emit node_start event."""
    emit_event(
        "node_start",
        {
            "node": node,
            "event_guid": event_guid,
            "inputs_hash": inputs_hash or "",
        },
        envelope,
    )


def emit_node_end(
    envelope: TraceEnvelope,
    node: str,
    event_guid: str,
    duration_ms: float,
    wrote_response: bool = False,
    error: Optional[str] = None,
) -> None:
    """Emit node_end event."""
    emit_event(
        "node_end",
        {
            "node": node,
            "event_guid": event_guid,
            "duration_ms": round(duration_ms, 2),
            "wrote_response": wrote_response,
            "error": error,
        },
        envelope,
    )


def emit_llm_call_end(
    envelope: TraceEnvelope,
    node: str,
    callsite: str,
    model: str,
    duration_ms: float,
    tokens_in: int = 0,
    tokens_out: int = 0,
    truncated: bool = False,
) -> None:
    """Emit llm_call_end event."""
    emit_event(
        "llm_call_end",
        {
            "node": node,
            "callsite": callsite,
            "model": model,
            "duration_ms": round(duration_ms, 2),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "truncated": truncated,
        },
        envelope,
    )


def emit_cache_event(
    envelope: TraceEnvelope,
    node: str,
    action: str,
    reason: Optional[str] = None,
) -> None:
    """Emit cache_event (verbose only)."""
    emit_event(
        "cache_event",
        {
            "node": node,
            "action": action,
            "reason": reason or "",
        },
        envelope,
        verbose_only=True,
    )
