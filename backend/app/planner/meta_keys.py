# backend/app/planner/meta_keys.py
"""
Metadata key constants for planner state.

Centralizes all frequently used metadata keys to prevent string-literal drift
and typos. All keys used in state.metadata should be defined here.

PR2: Metadata helpers + centralized turn init
"""

from typing import Tuple

# =============================================================================
# PER-TURN KEYS (reset at start of each turn via init_turn_metadata)
# =============================================================================

# LLM budget tracking
LLM_CALLS_THIS_TURN = "llm_calls_this_turn"
LLM_CALL_SITES = "llm_nodes_called_this_turn"
LLM_CALL_BLOCKED_REASON = "llm_call_blocked_reason"

# Node execution journal
NODE_RUN_JOURNAL = "node_run_journal"
VISITED_NODES = "visited_nodes"
STEP_COUNT = "step_count"

# Response writer guard (single response per turn)
RESPONSE_CLAIMED_BY = "response_claimed_by"

# Planner version/build info snapshot
PLANNER_SNAPSHOT = "planner_snapshot"

# Cache event tracking
CACHE_EVENTS = "cache_events_this_turn"
CACHE_SUMMARY_THIS_TURN = "cache_summary_this_turn"

# Duplication detection
DUPLICATION_CLASS = "duplication_class"

# Turn canary for state mutation validation
TURN_CANARY = "turn_canary"
MUTATION_COUNTER = "mutation_counter"

# Tripwire detection
TRIPWIRE_TRIGGERED = "tripwire_triggered"

# Field change tracking
DELTAS_APPLIED_THIS_TURN = "deltas_applied_this_turn"

# Response provenance
RESPONSE_SOURCE_NODE = "response_source_node"
RESPONSE_GENERATION_PROVENANCE = "response_generation_provenance"

# =============================================================================
# CROSS-TURN KEYS (persist across turns)
# =============================================================================

# Cumulative LLM budget tracking
LLM_CALL_BLOCKED_COUNT = "llm_call_blocked_count"

# Today's date (set once per session)
TODAY_ISO = "today_iso"

# Trace envelope (PR-T1: correlation IDs, persists across turns)
TRACE_ENVELOPE = "trace_envelope"

# =============================================================================
# ALL KEYS TUPLE (for uniqueness validation)
# =============================================================================

ALL_META_KEYS: Tuple[str, ...] = (
    # Per-turn keys
    LLM_CALLS_THIS_TURN,
    LLM_CALL_SITES,
    LLM_CALL_BLOCKED_REASON,
    NODE_RUN_JOURNAL,
    VISITED_NODES,
    STEP_COUNT,
    RESPONSE_CLAIMED_BY,
    PLANNER_SNAPSHOT,
    CACHE_EVENTS,
    CACHE_SUMMARY_THIS_TURN,
    DUPLICATION_CLASS,
    TURN_CANARY,
    MUTATION_COUNTER,
    TRIPWIRE_TRIGGERED,
    DELTAS_APPLIED_THIS_TURN,
    RESPONSE_SOURCE_NODE,
    RESPONSE_GENERATION_PROVENANCE,
    # Cross-turn keys
    LLM_CALL_BLOCKED_COUNT,
    TODAY_ISO,
    TRACE_ENVELOPE,
)

# Per-turn keys that should be reset/initialized at the start of each turn
PER_TURN_KEYS: Tuple[str, ...] = (
    LLM_CALLS_THIS_TURN,
    LLM_CALL_SITES,
    LLM_CALL_BLOCKED_REASON,
    NODE_RUN_JOURNAL,
    VISITED_NODES,
    STEP_COUNT,
    RESPONSE_CLAIMED_BY,
    PLANNER_SNAPSHOT,
    CACHE_EVENTS,
    DUPLICATION_CLASS,
    TURN_CANARY,
    MUTATION_COUNTER,
    TRIPWIRE_TRIGGERED,
    DELTAS_APPLIED_THIS_TURN,
    RESPONSE_SOURCE_NODE,
    RESPONSE_GENERATION_PROVENANCE,
)
