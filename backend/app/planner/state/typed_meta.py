"""
Typed metadata models for GraphState.metadata — shadow-mode migration.

Provides Pydantic models for the ~65 keys in state.metadata, split into:
- TurnMeta: per-turn flags, reset at turn boundary via reset_turn_metadata()
- PersistentMeta: cross-turn state, persisted via session_state

Bridge functions (get_*/sync_*) snapshot from / write back to the raw dict,
so state.metadata remains the SSoT during the migration period.
Unmigrated code keeps using state.metadata[key] directly — no breakage.

Usage (migrated node):
    turn = get_turn_meta(state)
    turn.has_blocking_violations = True
    sync_turn_meta(state, turn)

Turn boundary (plan_graph.py):
    state = _restore_graph_state(session_state)
    reset_turn_metadata(state)   # writes TurnMeta() defaults → state.metadata
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.planner.state.graph_state import TripSettings

# =============================================================================
# TurnMeta — reset via TurnMeta() at each turn boundary
# =============================================================================


class TurnMeta(BaseModel):
    """Per-turn flags. All fields have safe defaults so ``TurnMeta()`` is a clean slate."""

    # --- Routing / short-circuit ---
    short_circuit_response: bool = False
    short_circuit_type: Optional[str] = None
    exploration_mode: bool = False

    # --- Node execution flags ---
    architect_ran_this_turn: bool = False
    origin_only_logistics: bool = False
    is_generate_trigger: bool = False
    logistics_attempted: bool = False

    # --- Constraint guard outputs ---
    constraints_validated: List[Dict[str, Any]] = Field(default_factory=list)
    constraint_violations: List[Dict[str, Any]] = Field(default_factory=list)
    has_blocking_violations: bool = False
    violations_for_retry: List[Dict[str, Any]] = Field(default_factory=list)

    # --- Observability (from meta_keys.py PER_TURN_KEYS) ---
    llm_calls_this_turn: int = 0
    llm_nodes_called_this_turn: List[str] = Field(default_factory=list)
    llm_call_blocked_reason: Optional[str] = None
    node_run_journal: List[Dict[str, Any]] = Field(default_factory=list)
    visited_nodes: List[str] = Field(default_factory=list)
    step_count: int = 0
    response_claimed_by: Optional[str] = None
    planner_snapshot: Dict[str, Any] = Field(default_factory=dict)
    cache_events_this_turn: List[Dict[str, Any]] = Field(default_factory=list)
    cache_summary_this_turn: Dict[str, Any] = Field(default_factory=dict)
    duplication_class: Optional[str] = None
    turn_canary: Optional[str] = None
    mutation_counter: int = 0
    tripwire_triggered: bool = False
    deltas_applied_this_turn: List[Dict[str, Any]] = Field(default_factory=list)
    response_source_node: Optional[str] = None
    response_generation_provenance: Optional[str] = None

    # --- Specialist execution (per-turn) ---
    specialist_message: Optional[str] = None


# =============================================================================
# PersistentMeta — survives across turns via session_state
# =============================================================================


class PersistentMeta(BaseModel):
    """Cross-turn state persisted in session_state."""

    # --- Strategy sections ---
    strategy_sections: List[Dict[str, Any]] = Field(default_factory=list)
    executed_strategy_topics: List[str] = Field(default_factory=list)

    # --- Trip inputs (document SSoT mirror) ---
    trip_inputs: Dict[str, Any] = Field(default_factory=dict)  # DEPRECATED: use trip_settings
    trip_settings: Dict[str, Any] = Field(default_factory=dict)  # TripSettings.model_dump()

    # --- Specialist tracking ---
    specialist_constraints: Dict[str, Any] = Field(default_factory=dict)
    local_expert_ran: bool = False
    last_executed_specialist: Optional[str] = None

    # --- Cumulative observability ---
    llm_call_blocked_count: int = 0
    today_iso: Optional[str] = None
    trace_envelope: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Field-name sets (for bridge functions)
# =============================================================================

_TURN_FIELDS: frozenset[str] = frozenset(TurnMeta.model_fields.keys())
_PERSISTENT_FIELDS: frozenset[str] = frozenset(PersistentMeta.model_fields.keys())


# =============================================================================
# Bridge functions — read from / write to state.metadata
# =============================================================================


def get_turn_meta(state: Any) -> TurnMeta:
    """Snapshot per-turn fields from ``state.metadata`` into a typed model.

    Unknown keys in the dict are silently ignored — they stay in metadata
    and are preserved by ``sync_turn_meta``.
    """
    data = {k: state.metadata[k] for k in _TURN_FIELDS if k in state.metadata}
    return TurnMeta(**data)


def sync_turn_meta(state: Any, turn: TurnMeta) -> None:
    """Write typed per-turn values back to ``state.metadata``.

    Only writes keys defined on TurnMeta. Unknown keys already in the dict
    are preserved (not deleted).
    """
    for key, value in turn.model_dump().items():
        state.metadata[key] = value


def reset_turn_metadata(state: Any) -> None:
    """Canonical turn boundary reset — writes ``TurnMeta()`` defaults to metadata.

    Call immediately after ``_restore_graph_state()`` in both entry points.
    Replaces the ad-hoc resets that were in ``_restore_graph_state``.
    """
    sync_turn_meta(state, TurnMeta())


def get_persistent_meta(state: Any) -> PersistentMeta:
    """Snapshot cross-turn fields from ``state.metadata`` into a typed model."""
    data = {k: state.metadata[k] for k in _PERSISTENT_FIELDS if k in state.metadata}
    return PersistentMeta(**data)


def sync_persistent_meta(state: Any, meta: PersistentMeta) -> None:
    """Write typed persistent values back to ``state.metadata``."""
    for key, value in meta.model_dump().items():
        state.metadata[key] = value


# =============================================================================
# TripSettings accessor — typed access to user-owned settings
# =============================================================================


def get_trip_settings(state: Any) -> TripSettings:
    """Read typed trip settings from state, fallback to legacy trip_inputs.

    During shadow-mode migration, ``state.metadata["trip_settings"]`` is the
    canonical source.  If absent (old sessions), falls back to extracting
    settings from the legacy ``metadata["trip_inputs"]`` dict.
    """
    from app.planner.state.graph_state import TripSettings
    from app.schemas import (
        ActivitySettings,
        BookingTypes,
        FlightSettings,
        HotelSettings,
        TransportSettings,
    )

    raw = state.metadata.get("trip_settings")
    if raw:
        return TripSettings(**raw)

    # Fallback: extract from legacy trip_inputs dict
    ti = state.metadata.get("trip_inputs", {})
    return TripSettings(
        booking_types=BookingTypes(**(ti.get("booking_types") or {})),
        flight_settings=FlightSettings(**(ti.get("flight_settings") or {})),
        hotel_settings=HotelSettings(**(ti.get("hotel_settings") or {})),
        activity_settings=ActivitySettings(**(ti.get("activity_settings") or {})),
        transport_settings=TransportSettings(**(ti.get("transport_settings") or {})),
        date_flex=ti.get("date_flex", False),
        trip_duration=ti.get("trip_duration"),
        date_window_start=ti.get("date_window_start"),
        date_window_end=ti.get("date_window_end"),
    )
