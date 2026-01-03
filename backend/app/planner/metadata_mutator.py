"""
Metadata Mutator - Tier D Atomic Metadata Mutations.

This module provides type-safe, centralized metadata mutations with
optional transaction support. All metadata writes should go through
this class for:
1. Type safety via typed method signatures
2. Centralized validation
3. Atomic transaction support (for multi-field updates)
4. Observability (logging/tracing of mutations)

Usage:
    from app.planner.metadata_mutator import MetadataMutator

    mutator = MetadataMutator(state)
    mutator.set_question_target("destinations", source="extractor")

    # Or with transactions:
    with mutator.transaction() as tx:
        tx.set_response_provenance(node="specialist:flights", kind="llm")
        tx.track_llm_call("specialist_node")
    # All mutations applied atomically on __exit__

NOTE: This is a Tier D improvement (16-24 hours effort).
The full migration of 300+ callsites will be done incrementally.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterator,
    List,
    Literal,
    Optional,
    Set,
    TypedDict,
    Union,
)

if TYPE_CHECKING:
    from app.plan_graph import GraphState


# -----------------------------------------------------------------------------
# Type definitions for metadata values
# -----------------------------------------------------------------------------


class ExtractionConfidence(TypedDict, total=False):
    """Type for extraction_confidence metadata."""

    level: Literal["high", "medium", "low"]
    overall: float
    reason: str
    fields: Dict[str, float]


class GateResultSnapshot(TypedDict, total=False):
    """Type for gate_result metadata snapshot."""

    destination: str
    gate_fired: Optional[str]
    reason: str
    eval_time_ms: float
    skipped_gates: List[str]
    metadata_updates: Dict[str, Any]


class DateProvenance(TypedDict, total=False):
    """Type for date_provenance metadata."""

    start_date: str
    end_date: str
    source: str


# -----------------------------------------------------------------------------
# Constants - Metadata key names
# -----------------------------------------------------------------------------

# LLM budget tracking
LLM_CALLS_THIS_TURN = "llm_calls_this_turn"
LLM_CALL_SITES = "llm_nodes_called_this_turn"
LLM_CALL_BLOCKED_REASON = "llm_call_blocked_reason"
LLM_CALL_BLOCKED_COUNT = "llm_call_blocked_count"

# Turn tracking
TURN_CANARY = "turn_canary"
STEP_COUNT = "step_count"


# -----------------------------------------------------------------------------
# Transaction support
# -----------------------------------------------------------------------------


@dataclass
class MetadataTransaction:
    """
    Collects mutations to be applied atomically.

    Used internally by MetadataMutator.transaction() context manager.
    """

    _pending: Dict[str, Any] = field(default_factory=dict)
    _appends: Dict[str, List[Any]] = field(default_factory=dict)
    _increments: Dict[str, int] = field(default_factory=dict)

    def set(self, key: str, value: Any) -> None:
        """Queue a simple set operation."""
        self._pending[key] = value

    def append(self, key: str, value: Any) -> None:
        """Queue an append to a list."""
        if key not in self._appends:
            self._appends[key] = []
        self._appends[key].append(value)

    def increment(self, key: str, amount: int = 1) -> None:
        """Queue an increment operation."""
        self._increments[key] = self._increments.get(key, 0) + amount

    def apply(self, state: "GraphState") -> None:
        """Apply all queued mutations atomically."""
        # Apply simple sets
        for key, value in self._pending.items():
            state.metadata[key] = value

        # Apply appends
        for key, values in self._appends.items():
            if key not in state.metadata:
                state.metadata[key] = []
            for v in values:
                state.metadata[key].append(v)

        # Apply increments
        for key, amount in self._increments.items():
            current = state.metadata.get(key, 0)
            state.metadata[key] = current + amount


# -----------------------------------------------------------------------------
# Main MetadataMutator class
# -----------------------------------------------------------------------------


class MetadataMutator:
    """
    Type-safe, centralized metadata mutation handler.

    All metadata writes should go through this class for type safety
    and centralized validation. Methods are organized by domain.
    """

    __slots__ = ("_state", "_lock", "_in_transaction", "_tx")

    def __init__(self, state: "GraphState") -> None:
        """
        Initialize mutator with state reference.

        Args:
            state: The GraphState to mutate
        """
        self._state = state
        self._lock = threading.Lock()
        self._in_transaction = False
        self._tx: Optional[MetadataTransaction] = None

    @contextmanager
    def transaction(self) -> Iterator["MetadataMutator"]:
        """
        Context manager for atomic multi-field mutations.

        Usage:
            with mutator.transaction() as tx:
                tx.set_response_provenance(node="specialist", kind="llm")
                tx.track_llm_call("specialist")
            # All mutations applied on exit

        Yields:
            Self, with mutations queued until context exit
        """
        with self._lock:
            self._in_transaction = True
            self._tx = MetadataTransaction()
            try:
                yield self
            finally:
                if self._tx:
                    self._tx.apply(self._state)
                self._tx = None
                self._in_transaction = False

    def _set(self, key: str, value: Any) -> None:
        """Internal: Set metadata, respecting transaction mode."""
        if self._in_transaction and self._tx:
            self._tx.set(key, value)
        else:
            self._state.metadata[key] = value

    def _append(self, key: str, value: Any) -> None:
        """Internal: Append to list, respecting transaction mode."""
        if self._in_transaction and self._tx:
            self._tx.append(key, value)
        else:
            if key not in self._state.metadata:
                self._state.metadata[key] = []
            self._state.metadata[key].append(value)

    def _increment(self, key: str, amount: int = 1) -> None:
        """Internal: Increment counter, respecting transaction mode."""
        if self._in_transaction and self._tx:
            self._tx.increment(key, amount)
        else:
            current = self._state.metadata.get(key, 0)
            self._state.metadata[key] = current + amount

    def _get(self, key: str, default: Any = None) -> Any:
        """Internal: Get metadata value."""
        return self._state.metadata.get(key, default)

    # -------------------------------------------------------------------------
    # Question Management
    # -------------------------------------------------------------------------

    def set_question_target(
        self,
        target: Optional[str],
        source: str = "unknown",
    ) -> None:
        """
        Set the current question target field.

        Args:
            target: Canonical field name (destinations, dates, etc.) or None
            source: Source that set this (extractor, specialist, etc.)
        """
        self._set("question_target", target)
        self._set("question_target_source", source)

        if target:
            # Track active question ID
            active_qid = self._get("active_question_id", 0) + 1
            self._set("active_question_id", active_qid)
            self._set("active_question_target", target)

    def set_last_question_field(self, field: Optional[str]) -> None:
        """Set last_question_field metadata."""
        self._set("last_question_field", field)

    def increment_question_id(self) -> int:
        """Increment and return new question ID."""
        counter = self._get("question_id_counter", 0) + 1
        self._set("question_id_counter", counter)
        return counter

    def set_suggestions(
        self,
        suggestions: List[str],
        question_id: int,
        target: str,
    ) -> None:
        """
        Store suggestion metadata for a question.

        Args:
            suggestions: List of suggestion strings
            question_id: The question ID these suggestions are for
            target: The field these suggestions target
        """
        self._set("last_suggestions", [{"text": s, "field": target} for s in suggestions])
        self._set("last_suggestions_question_id", question_id)
        self._set("last_suggestions_target", target)

    # -------------------------------------------------------------------------
    # Response Tracking
    # -------------------------------------------------------------------------

    def set_response_provenance(
        self,
        node: str,
        kind: Literal["llm", "template", "deterministic", "cached", "llm_fallback"],
    ) -> None:
        """
        Set response generation provenance.

        Args:
            node: The node that generated the response (e.g., "specialist:flights")
            kind: The generation method (llm, template, deterministic, cached)
        """
        self._set("response_writer_node", node)
        self._set("response_generation_provenance", kind)

    def set_response_source_node(self, node: str) -> None:
        """Set the source node that generated current response."""
        self._set("response_source_node", node)

    def set_response_hash(self, hash_value: str) -> None:
        """Set response text hash for deduplication."""
        self._set("response_text_hash", hash_value)

    def set_last_response_turn(self, turn: int) -> None:
        """Record the turn number of last response."""
        self._set("last_response_turn", turn)

    # -------------------------------------------------------------------------
    # LLM Budget Tracking
    # -------------------------------------------------------------------------

    def init_llm_budget(self) -> None:
        """Initialize LLM budget counters for a new turn."""
        self._set(LLM_CALLS_THIS_TURN, 0)
        self._set(LLM_CALL_SITES, [])
        self._set(LLM_CALL_BLOCKED_REASON, {})
        self._set(LLM_CALL_BLOCKED_COUNT, {})

    def track_llm_call(self, node_name: str) -> None:
        """
        Record an LLM call from a node.

        Args:
            node_name: Name of the node making the call
        """
        self._increment(LLM_CALLS_THIS_TURN)
        self._append(LLM_CALL_SITES, node_name)

    def block_llm_call(self, node_name: str, reason: str = "budget_exhausted") -> None:
        """
        Record a blocked LLM call.

        Args:
            node_name: Name of the node that was blocked
            reason: Why the call was blocked
        """
        blocked_reasons = self._get(LLM_CALL_BLOCKED_REASON, {})
        blocked_reasons[node_name] = reason
        self._set(LLM_CALL_BLOCKED_REASON, blocked_reasons)

        blocked_counts = self._get(LLM_CALL_BLOCKED_COUNT, {})
        blocked_counts[node_name] = blocked_counts.get(node_name, 0) + 1
        self._set(LLM_CALL_BLOCKED_COUNT, blocked_counts)

    def set_model_used(self, model: str, token_estimate: int = 0) -> None:
        """Record the model used for LLM call."""
        self._set("model_used", model)
        if token_estimate:
            self._set("token_estimate", token_estimate)

    # -------------------------------------------------------------------------
    # Extraction State
    # -------------------------------------------------------------------------

    def set_extraction_confidence(self, confidence: ExtractionConfidence) -> None:
        """Set extraction confidence metadata."""
        self._set("extraction_confidence", confidence)

    def set_extraction_path(self, path: str) -> None:
        """Set the extraction path (e.g., 'llm:standard', 'lqa:dates')."""
        self._set("extraction_path", path)

    def set_extractor_mode(self, mode: str, reason: str = "") -> None:
        """Set extractor mode and reason."""
        self._set("extractor_mode", mode)
        if reason:
            self._set("extractor_mode_reason", reason)

    def set_parse_provenance(self, provenance: str, source_node: str) -> None:
        """Set parse provenance metadata."""
        self._set("parse_provenance", provenance)
        self._set("parse_provenance_source_node", source_node)

    def finalize_parse_provenance(self) -> None:
        """Mark parse provenance as finalized (no more updates)."""
        self._set("parse_provenance_finalized", True)

    # -------------------------------------------------------------------------
    # Routing/Gate State
    # -------------------------------------------------------------------------

    def set_router_result(
        self,
        path: str,
        notes: str = "",
        confidence: float = 1.0,
    ) -> None:
        """Set router result metadata."""
        self._set("router_path", path)
        self._set("router_notes", notes)
        self._set("router_confidence", confidence)

    def set_gate_result(self, result: GateResultSnapshot) -> None:
        """
        Store gate evaluation result for observability.

        Args:
            result: Gate result snapshot dict
        """
        from copy import deepcopy

        self._set("gate_result", deepcopy(result))

        # Store individual fields for quick access
        self._set("_gate_result_destination", result.get("destination"))
        self._set("_gate_result_gate_fired", result.get("gate_fired"))
        self._set("_gate_result_reason", result.get("reason", ""))
        self._set("_gate_result_eval_time_ms", result.get("eval_time_ms", 0.0))
        self._set("_gate_result_skipped_gates", result.get("skipped_gates", []))

        # Apply any metadata updates from the gate
        for key, value in result.get("metadata_updates", {}).items():
            self._set(key, value)

    def set_gate_metrics(
        self,
        first_fired: Optional[str],
        eval_time_ms: float,
        skipped: List[str],
    ) -> None:
        """Set gate evaluation metrics."""
        if first_fired:
            self._set("first_gate_fired", first_fired)
        self._set("gate_eval_time_ms", eval_time_ms)
        self._set("skipped_gates", skipped)

    def set_specialist_gate_triggered(
        self,
        name: str,
        missing_fields: Optional[List[str]] = None,
    ) -> None:
        """Record that a specialist gate was triggered."""
        self._set("specialist_gate_triggered", name)
        if missing_fields:
            self._set("specialist_gate_missing", missing_fields)

    # -------------------------------------------------------------------------
    # Strategy State
    # -------------------------------------------------------------------------

    def set_strategy_stage(
        self,
        stage: Union[int, str],
        topic: Optional[str] = None,
    ) -> None:
        """Set current strategy stage."""
        self._set("strategy_stage", stage)
        if topic:
            self._set("last_strategy_topic", topic)

    def set_strategy_path(self, path: str) -> None:
        """Set strategy execution path."""
        self._set("strategy_path", path)

    def mark_strategy_truncated(self, cap: int) -> None:
        """Mark that strategy response was truncated."""
        self._set("strategy_truncated", True)
        self._set("strategy_truncate_cap", cap)

    def set_stage0_complete(
        self,
        topic: str,
        model: str,
        question_target: str,
        signature: str,
    ) -> None:
        """Mark stage0 as complete with metadata."""
        self._set("strategy_stage0_completed", True)
        self._set("strategy_stage0_topic", topic)
        self._set("model_used", model)
        self._set("last_strategy_topic", topic)
        self._set("stage0_completed_sig", signature)
        self._set("last_stage0_question_target", question_target)

    def set_stage0_fallback(self, error: str) -> None:
        """Mark stage0 as using fallback due to error."""
        self._set("strategy_stage0_fallback", True)
        self._set("strategy_stage0_error", error)
        self._set("strategy_stage0_deterministic", True)

    def set_stage1_skeleton(self, skeleton: str, topic: str, signature: str) -> None:
        """Store stage1 skeleton for stage2 continuation."""
        self._set("stage1_completed_sig", signature)
        self._set("stage1_skeleton", skeleton)
        self._set("stage1_skeleton_topic", topic)

    def set_strategy_gate_fallback(self, reason: str) -> None:
        """Mark strategy as falling back with reason."""
        self._set("strategy_gate_fallback", True)
        self._set("strategy_gate_reason", reason)

    # -------------------------------------------------------------------------
    # Date Handling
    # -------------------------------------------------------------------------

    def set_date_clarify_mode(
        self,
        enabled: bool,
        pending_text: Optional[str] = None,
        suggestions: Optional[List[str]] = None,
        season_name: Optional[str] = None,
    ) -> None:
        """
        Set date clarification mode state.

        Args:
            enabled: Whether date clarify mode is active
            pending_text: The pending date text to clarify
            suggestions: Date clarification suggestions
            season_name: Season name if applicable
        """
        self._set("date_clarify_mode", enabled)
        if pending_text is not None:
            self._set("pending_date_text", pending_text)
        if suggestions is not None:
            self._set("date_clarify_suggestions", suggestions)
        if season_name is not None:
            self._set("date_clarify_season_name", season_name)

    def increment_date_clarify_attempts(self) -> int:
        """Increment and return date clarify attempt count."""
        attempts = self._get("_date_clarify_attempts", 0) + 1
        self._set("_date_clarify_attempts", attempts)
        return attempts

    def set_date_loop_guard(self, fallback_text: str) -> None:
        """Trigger date loop guard with fallback."""
        self._set("date_loop_guard_fallback", fallback_text)
        self._set("date_loop_guard_triggered", True)

    def set_date_provenance(self, provenance: DateProvenance) -> None:
        """Set date extraction provenance."""
        self._set("date_provenance", provenance)

    def set_raw_date_hints(
        self,
        start_hint: Optional[str] = None,
        end_hint: Optional[str] = None,
    ) -> None:
        """Store raw date hints for debugging."""
        hints = self._get("raw_date_hints", {})
        if start_hint:
            hints["start_date"] = start_hint
        if end_hint:
            hints["end_date"] = end_hint
        self._set("raw_date_hints", hints)

    def set_end_date_bypassed(self, bypassed: bool = True) -> None:
        """Mark that end_date requirement was bypassed."""
        self._set("end_date_bypassed", bypassed)

    # -------------------------------------------------------------------------
    # Turn/Journal Tracking
    # -------------------------------------------------------------------------

    def init_turn(self, turn_id: str) -> None:
        """Initialize metadata for a new turn."""
        self._set("journal_turn_id", turn_id)
        self._set("turn_journal", [])
        self._set("turn_updates", [])
        self._set("error_events", [])

    def record_turn_update(self, update: Dict[str, Any]) -> None:
        """Record a turn update event."""
        updates = self._get("turn_updates", [])
        updates.append(update)
        self._set("turn_updates", updates)

    def set_pre_turn_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """Store pre-turn state snapshot."""
        self._set("pre_turn_snapshot", snapshot)

    def append_journal_entry(self, entry: Dict[str, Any]) -> None:
        """Append entry to turn journal."""
        self._append("turn_journal", entry)

    def set_user_intent(self, intent: str, tone: str = "neutral") -> None:
        """Set user intent and tone metadata."""
        self._set("user_intent", intent)
        self._set("user_tone", tone)

    def set_intent_confidence(self, turn_count: int = 1, confidence: float = 1.0) -> None:
        """Set intent tracking metadata after router refinement."""
        self._set("intent_turn_count", turn_count)
        self._set("intent_confidence", confidence)

    def track_no_progress(self, last_intent: str) -> int:
        """Track turn without progress. Returns new count."""
        count = self._get("no_progress_turns", 0) + 1
        self._set("no_progress_turns", count)
        self._set("last_intent", last_intent)
        return count

    def reset_progress_tracking(self, current_intent: str) -> None:
        """Reset progress tracking when intent changes."""
        self._set("no_progress_turns", 0)
        self._set("last_intent", current_intent)

    # -------------------------------------------------------------------------
    # Error Tracking
    # -------------------------------------------------------------------------

    def append_error_event(self, event: Dict[str, Any]) -> None:
        """Append an error event to the error log."""
        if "error_events" not in self._state.metadata:
            self._set("error_events", [])
        self._append("error_events", event)

    def set_error_flag(self, flag: str, value: bool = True) -> None:
        """Set an error flag."""
        flags = self._get("error_flags", {})
        flags[flag] = value
        self._set("error_flags", flags)

    def increment_validator_failures(self) -> int:
        """Increment and return validator failure count."""
        failures = self._get("validator_failures", 0) + 1
        self._set("validator_failures", failures)
        return failures

    # -------------------------------------------------------------------------
    # Trip Input State
    # -------------------------------------------------------------------------

    def set_trip_inputs_provenance(self, provenance: Dict[str, Any]) -> None:
        """Set trip inputs provenance metadata."""
        self._set("trip_inputs_provenance", provenance)

    def append_delta_applied(self, delta: Dict[str, Any]) -> None:
        """Append a delta that was applied this turn."""
        self._append("deltas_applied_this_turn", delta)

    def set_budget_answered(self, tier: Optional[str] = None) -> None:
        """Mark budget as answered."""
        self._set("budget_answered", True)
        if tier:
            self._set("budget_tier", tier)

    def set_multi_city_confidence(self, confidence: float) -> None:
        """Set multi-city detection confidence."""
        self._set("multi_city_confidence", confidence)

    def set_multi_city_signal(self, detected: bool = True) -> None:
        """Mark multi-city signal as detected."""
        self._set("multi_city_signal", detected)

    def set_adults_defaulted(self, reason: str) -> None:
        """Mark that adults count was defaulted."""
        self._set("adults_defaulted", True)
        self._set("adults_default_reason", reason)

    # -------------------------------------------------------------------------
    # Pending Actions
    # -------------------------------------------------------------------------

    def set_pending_action(
        self,
        action: Optional[str],
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Set a pending action to be handled.

        Args:
            action: Action type (generate_plan, confirm_typo, etc.) or None to clear
            data: Optional associated data
        """
        self._set("pending_action", action)
        if data:
            for key, value in data.items():
                self._set(f"pending_{key}", value)

    def set_deferred_intent(
        self,
        intent: str,
        topic: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Set a deferred intent for later processing."""
        self._set("deferred_intent", intent)
        if topic:
            self._set("deferred_strategy_topic", topic)
        if reason:
            self._set("force_required_fields_reason", reason)

    # -------------------------------------------------------------------------
    # Loop Guard / Recovery
    # -------------------------------------------------------------------------

    def set_loop_guard_skip(
        self,
        field: str,
        excluded_intents: Optional[List[str]] = None,
    ) -> None:
        """Set loop guard skip configuration."""
        self._set("loop_guard_skip_field", field)
        if excluded_intents:
            self._set("loop_guard_excluded_intents", excluded_intents)

    def set_loop_guard_recovery_emitted(self) -> None:
        """Mark that loop guard recovery was emitted."""
        self._set("loop_guard_recovery_emitted", True)

    def set_force_route_next_turn(
        self,
        destination: str,
        validation_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Force routing to a destination next turn."""
        self._set("force_route_next_turn", destination)
        if validation_data:
            self._set("pending_recovery_validation", validation_data)

    # -------------------------------------------------------------------------
    # Polish State
    # -------------------------------------------------------------------------

    def set_polish_result(
        self,
        method: Literal["deterministic:opener", "deterministic:closer", "llm", "mvp_mode"],
        duration_ms: Optional[float] = None,
        skipped_reason: Optional[str] = None,
    ) -> None:
        """Set response polish metadata."""
        self._set("polish_method", method)
        if duration_ms is not None:
            self._set("polish_duration_ms", round(duration_ms, 2))
        if skipped_reason:
            self._set("polish_skipped_reason", skipped_reason)
        if method == "mvp_mode":
            self._set("polish_mvp_mode", True)

    # -------------------------------------------------------------------------
    # Tile Search
    # -------------------------------------------------------------------------

    def set_tiles(
        self,
        tiles: Dict[str, Any],
        booking_types: List[str],
    ) -> None:
        """Set tile search results."""
        self._set("tiles", tiles)
        self._set("tile_search_attempted", True)
        self._set("tile_search_booking_types", booking_types)

    def set_tile_cache_hit(self) -> None:
        """Mark tile cache hit."""
        self._set("tile_cache_hit", True)

    def set_tile_cache_miss(self, intent: str) -> None:
        """Mark tile cache miss with intent."""
        self._set("tile_cache_miss", True)
        self._set("tiles_needed_for", intent)

    def set_tile_search_blocked(self, reason: str) -> None:
        """Mark tile search as blocked with reason."""
        self._set("tile_search_blocked", reason)

    # -------------------------------------------------------------------------
    # Cache Hit Tracking
    # -------------------------------------------------------------------------

    def set_cache_hit(
        self,
        cache_type: Literal["response", "extractor", "gate", "required_fields", "router"],
    ) -> None:
        """Mark a cache hit for the specified cache type."""
        self._set(f"{cache_type}_cache_hit", True)

    # -------------------------------------------------------------------------
    # Exit Contract
    # -------------------------------------------------------------------------

    def set_exit_contract(
        self,
        missing_fields: List[str],
        core_complete: bool,
        patched: bool = False,
    ) -> None:
        """Set exit contract metadata."""
        self._set("exit_contract_missing_fields", missing_fields)
        self._set("exit_contract_core_complete", core_complete)
        if patched:
            self._set("exit_contract_patched", True)

    # -------------------------------------------------------------------------
    # Specialist State
    # -------------------------------------------------------------------------

    def set_selected_specialist(self, name: str) -> None:
        """Set the selected specialist name."""
        self._set("selected_specialist", name)

    def set_specialist_pre_core(self, deterministic: bool = True) -> None:
        """Mark specialist as in pre-core mode."""
        self._set("specialist_pre_core_active", True)
        self._set("specialist_pre_core_deterministic", deterministic)

    def set_pre_core_deterministic_path(self, path: str) -> None:
        """Set pre-core deterministic template path."""
        self._set("pre_core_deterministic_path", path)

    def set_groundedness_blocks(self, blocks: List[str]) -> None:
        """Set groundedness validation blocks."""
        self._set("groundedness_blocks", blocks)

    # -------------------------------------------------------------------------
    # Failed Inputs
    # -------------------------------------------------------------------------

    def append_failed_input(
        self,
        failure: Dict[str, Any],
        message: Optional[str] = None,
    ) -> None:
        """Append a failed input with optional message."""
        existing = self._get("failed_inputs", [])
        existing.append(failure)
        self._set("failed_inputs", existing)

        if message and not self._get("failed_input_message"):
            self._set("failed_input_message", message)

    def set_failed_input_message(self, message: str) -> None:
        """Set the failed input user message."""
        self._set("failed_input_message", message)

    # -------------------------------------------------------------------------
    # Negation/Alternative Extraction
    # -------------------------------------------------------------------------

    def set_negation_extraction(
        self,
        negation_type: str,
        alternative: Optional[str] = None,
        confidence: Optional[ExtractionConfidence] = None,
    ) -> None:
        """Set negation/alternative extraction metadata."""
        self._set("negation_alternative_extracted", True)
        self._set("negation_type", negation_type)
        if alternative:
            self._set("negation_alternative_raw", alternative)
        if confidence:
            self._set("extraction_confidence", confidence)

    # -------------------------------------------------------------------------
    # Template Tracking
    # -------------------------------------------------------------------------

    def set_template_used(
        self,
        template_type: str,
        field: Optional[str] = None,
    ) -> None:
        """Mark that a template was used for response."""
        self._set("from_template", True)
        self._set("template_used", template_type)
        if field:
            self._set("last_question_field", field)

    def set_confirmation_template(self, template_type: str, field: str) -> None:
        """Mark confirmation template as applied."""
        self._set("confirmation_template_applied", template_type)
        self._set("last_question_field", field)
        self._set("from_template", True)

    # -------------------------------------------------------------------------
    # Misc/Other
    # -------------------------------------------------------------------------

    def set_plan_ready(self, ready: bool = True) -> None:
        """Mark that plan just became ready."""
        self._set("plan_just_became_ready", ready)

    def set_safety_snippet_shown(self, destinations: Set[str]) -> None:
        """Track which destinations had safety snippets shown."""
        self._set("safety_snippet_shown_for", list(destinations))

    def set_bypass_result(self, variant: str, observability: Dict[str, Any]) -> None:
        """Set bypass extraction result metadata."""
        self._set("bypass_variant", variant)
        self._set("bypass_observability", observability)

    def set_user_request_type(self, request_type: str) -> None:
        """Set user request type classification."""
        self._set("user_request_type", request_type)

    def set_low_confidence_fallback(
        self,
        original_intent: str,
        original_topic: Optional[str] = None,
    ) -> None:
        """Mark low confidence fallback with original values."""
        self._set("router_low_confidence_fallback", True)
        self._set("router_original_intent", original_intent)
        if original_topic:
            self._set("router_original_topic", original_topic)

    def set_typo_suggestions(
        self,
        suggestions: Dict[str, str],
        original_intent: str,
    ) -> None:
        """Set typo correction suggestions."""
        self._set("typo_suggestions", suggestions)
        self._set("deferred_intent", original_intent)
        self._set("force_required_fields_reason", "typo_detected")
        self._set("pending_action", "confirm_typo")
        self._set("pending_typo_corrections", suggestions)


# -----------------------------------------------------------------------------
# Convenience function
# -----------------------------------------------------------------------------


def get_mutator(state: "GraphState") -> MetadataMutator:
    """
    Get a MetadataMutator for the given state.

    This is a convenience function for quick access.

    Args:
        state: The GraphState to mutate

    Returns:
        MetadataMutator instance
    """
    return MetadataMutator(state)
