"""Type definitions for the gates package.

This module provides TypedDict definitions for structured type hints
on dictionaries used throughout the gate evaluation system.

Usage:
    from app.planner.gates.types import GraphMetadata, ExtractionConfidence
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class ExtractionConfidence(TypedDict, total=False):
    """Confidence scores from the extractor node."""

    overall: float
    per_field: Dict[str, float]
    source: str  # "deterministic" | "llm" | "lqa"


class DateProvenance(TypedDict, total=False):
    """Provenance information for date fields."""

    start_date: str  # "explicit" | "inferred" | "relative"
    end_date: str
    source_node: str


class PendingDateRange(TypedDict, total=False):
    """Pending date range for clarification mode."""

    start: Optional[str]
    end: Optional[str]
    start_hint: Optional[str]
    end_hint: Optional[str]


class TurnJournalEntry(TypedDict, total=False):
    """Single entry in the turn journal."""

    turn_id: str
    action: str
    field: Optional[str]
    value: Any
    timestamp: float


class GateResultMetadata(TypedDict, total=False):
    """Gate evaluation result stored in metadata."""

    destination: str
    gate_fired: str
    reason: str
    eval_time_ms: float
    skipped_gates: List[str]


class CacheDiscards(TypedDict, total=False):
    """Cache discard counts by reason."""

    ttl_expired: int
    schema_mismatch: int
    invalidated: int


class LLMBudgetInfo(TypedDict, total=False):
    """LLM budget tracking information."""

    calls_this_turn: int
    nodes_called: List[str]
    node_tokens: Dict[str, int]
    blocked_reasons: Dict[str, str]


class ReadinessSnapshot(TypedDict, total=False):
    """Snapshot of trip readiness at a point in time."""

    core_complete: bool
    ready_to_generate: bool
    missing_core: List[str]
    blocking_errors: List[str]


class GraphMetadata(TypedDict, total=False):
    """Complete metadata dictionary for GraphState.

    This TypedDict documents all known metadata keys used across
    the planner system. Using this type enables IDE autocomplete
    and static type checking for metadata access.

    Note: This is total=False because metadata is incrementally built
    during graph execution - not all keys are present at all times.
    """

    # ==========================================================================
    # Session & Turn Identification
    # ==========================================================================
    thread_id: str  # Unique session identifier
    session_id: str  # Alternative session identifier
    today_iso: str  # Current date in ISO format for testing
    turn_reference_date: str  # Reference date for relative date parsing
    journal_turn_id: str  # Current turn identifier in journal

    # ==========================================================================
    # Question Target & Routing
    # ==========================================================================
    question_target: Optional[str]  # Current field being asked (destinations|origin|dates|etc)
    question_target_source: str  # Where the question_target was set from
    active_question_target: Optional[str]  # Currently active question target
    active_question_id: int  # ID of the currently active question
    answered_question_target_this_turn: Optional[str]  # Question target answered this turn
    answered_question_id_this_turn: Optional[int]  # Question ID answered this turn
    last_question_field: Optional[str]  # Last field that was asked about
    last_answered_question_id: Optional[int]  # Last question ID that was answered
    question_id_counter: int  # Counter for generating unique question IDs

    # ==========================================================================
    # Routing & Gate Results
    # ==========================================================================
    router_path: str  # Path taken through router
    router_bypassed: bool  # Whether router was bypassed
    first_gate_fired: str  # First gate that fired
    gate_trace: List[str]  # Trace of all gates checked
    gate_result: GateResultMetadata  # Full gate result object
    _gate_result_destination: str  # Gate destination (internal)
    _gate_result_gate_fired: str  # Gate that fired (internal)
    _gate_result_reason: str  # Gate reason (internal)
    _gate_result_eval_time_ms: float  # Gate eval time (internal)
    _gate_result_skipped_gates: List[str]  # Skipped gates (internal)
    force_route_next_turn: Optional[str]  # Force routing to specific node

    # ==========================================================================
    # Extraction & Parsing
    # ==========================================================================
    extraction_confidence: ExtractionConfidence  # Confidence scores
    extraction_path: str  # Path through extraction (deterministic|llm|lqa)
    extractor_mode: str  # Mode used for extraction (clarification|normal)
    parse_provenance: str  # Provenance of parsed data
    parse_provenance_source_node: str  # Node that set parse provenance
    parse_provenance_finalized: bool  # Whether provenance is finalized
    parsed_inputs: Dict[str, Any]  # Raw parsed inputs from extractor
    user_intent: str  # Detected user intent
    user_intent_hint: str  # Hint for user intent
    user_tone: str  # Detected user tone (neutral|frustrated|etc)
    last_intent: str  # Last detected intent

    # ==========================================================================
    # Strategy System
    # ==========================================================================
    strategy_stage: int  # Current strategy stage (0|1|2)
    strategy_topic: Optional[str]  # Current strategy topic (hiking|diving|etc)
    last_strategy_topic: Optional[str]  # Last strategy topic used
    pending_strategy_expansion: bool  # Whether awaiting expansion request
    stage0_completed_sig: Optional[str]  # Signature for stage 0 completion tracking
    auto_fire_topic_switch: Optional[str]  # Auto-fire topic switch
    topic_switch_cooldown_until_turn: int  # Turn until topic switch allowed
    strategy_cache_hit: bool  # Whether strategy cache was hit

    # ==========================================================================
    # Response Generation
    # ==========================================================================
    response_writer_node: str  # Node that wrote the response
    response_source_node: str  # Node that generated the response
    response_generation_provenance: (
        str  # How response was generated (llm|template|cached|deterministic)
    )
    response_text_hash: str  # Hash of response text for change detection
    from_template: bool  # Whether response was from template
    template_used: str  # Name of template used
    polish_method: str  # Method used for polishing
    polish_skipped_reason: str  # Reason polish was skipped
    polish_mvp_mode: bool  # Whether MVP polish mode is active

    # ==========================================================================
    # Suggestions & UI
    # ==========================================================================
    last_suggestions: List[str]  # Last set of suggestions shown
    last_suggestions_question_id: int  # Question ID for last suggestions
    last_suggestions_target: str  # Target field for last suggestions
    suggestion_target_override: str  # Override for suggestion target
    suggestion_contract_violation: Dict[str, Any]  # Details of suggestion contract violation

    # ==========================================================================
    # Date Handling
    # ==========================================================================
    date_clarify_mode: bool  # Whether in date clarification mode
    date_provenance: DateProvenance  # Provenance info for dates
    pending_date_range: PendingDateRange  # Pending date range for clarification
    raw_date_hints: Dict[str, str]  # Raw date hints before parsing
    rejected_date_answer: str  # Date answer that was rejected
    partial_date_notifications: List[str]  # Notifications about partial dates
    schema_version: str  # Schema version for date handling

    # ==========================================================================
    # Trip Inputs & State Tracking
    # ==========================================================================
    trip_inputs_provenance: Dict[str, str]  # Provenance for each trip input field
    deltas_applied_this_turn: List[Dict[str, Any]]  # Deltas applied this turn
    turn_journal: List[TurnJournalEntry]  # Journal of all turn actions
    turn_updates: List[Dict[str, Any]]  # Updates applied this turn
    pre_turn_snapshot: Dict[str, Any]  # Snapshot before turn started
    trip_shape_inferred: str  # Inferred trip shape
    multi_city_confidence: float  # Confidence in multi-city detection
    budget_answered: bool  # Whether budget has been answered
    budget_tier: str  # Budget tier (budget|mid-range|luxury)
    clarification_target_field: str  # Field being clarified

    # ==========================================================================
    # Error Handling & Recovery
    # ==========================================================================
    error_events: List[Dict[str, Any]]  # Error events this turn
    error_flags: Dict[str, bool]  # Error flags (STATE_REGRESSION, etc)
    failed_inputs: List[Dict[str, Any]]  # Failed input attempts
    failed_input_message: str  # Message about failed input
    blocking_errors: List[str]  # Errors blocking progression
    typo_suggestions: Dict[str, List[str]]  # Typo suggestions per field
    pending_typo_corrections: Dict[str, str]  # Pending typo corrections
    validator_failures: int  # Count of validation failures
    pending_recovery_validation: Dict[str, Any]  # Pending recovery validation
    current_node: str  # Current node being executed

    # ==========================================================================
    # Caching
    # ==========================================================================
    required_fields_cache_hit: bool  # Whether required_fields cache was hit
    router_cache_hit: bool  # Whether router cache was hit
    extractor_cache_hit: bool  # Whether extractor cache was hit
    cache_discards: CacheDiscards  # Cache discard counts

    # ==========================================================================
    # LLM Budget & Telemetry
    # ==========================================================================
    llm_calls_this_turn: int  # Number of LLM calls this turn
    llm_nodes_called_this_turn: List[str]  # Nodes that called LLM
    node_tokens: Dict[str, int]  # Token usage per node
    llm_call_blocked_count: Dict[str, int]  # Blocked LLM calls per reason
    llm_call_blocked_reason: Dict[str, str]  # Reasons for blocked calls

    # ==========================================================================
    # LQA Prepass
    # ==========================================================================
    lqa_reason: str  # Reason for LQA result (hit|miss|skip)

    # ==========================================================================
    # Loop Guards
    # ==========================================================================
    loop_guard_skip_field: str  # Field to skip in loop guard
    loop_guard_excluded_intents: List[str]  # Intents excluded from loop guard
    loop_guard_recovery_emitted: bool  # Whether recovery was emitted
    no_progress_turns: int  # Count of turns with no progress
    missing_fields_unchanged_turns: int  # Turns with unchanged missing fields

    # ==========================================================================
    # Readiness Tracking
    # ==========================================================================
    readiness_pre: ReadinessSnapshot  # Readiness before processing
    explicit_specialist_intent: Optional[str]  # Explicit specialist intent
    pre_core_mode: bool  # Whether in pre-core mode

    # ==========================================================================
    # Pending Actions
    # ==========================================================================
    pending_action: Optional[str]  # Pending action to perform


# =============================================================================
# Type Aliases for Common Patterns
# =============================================================================

# Metadata that can be accessed from state
StateMetadata = GraphMetadata

# Subset of metadata used in gate evaluation
GateEvaluatorMetadata = GraphMetadata

# Subset used in routing decisions
RoutingMetadata = GraphMetadata
