"""
State serialization and deserialization utilities.

Handles conversion between:
- GraphState ↔ session_state dict (for persistence)
- TripPlan → trip_inputs dict (for frontend document envelope)
- Field hashing for selective regeneration

Extracted from plan_graph.py (Stage 7, Phase 1).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, Optional

from langchain_core.messages import AIMessage, HumanMessage

from app.planner.state import GraphState, TripPlan, TripSettings
from app.schemas import (
    ActivitySettings,
    BookingTypes,
    FlightSettings,
    HotelSettings,
    TransportSettings,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Public API
# =============================================================================


def trip_plan_to_trip_inputs(plan: TripPlan) -> Dict[str, Any]:
    """Convert TripPlan to trip_inputs dict for frontend document envelope."""
    return {
        "destination": plan.destination,
        "origin": plan.origin,
        "origin_iata": plan.origin_iata,
        "destination_iata": plan.destination_iata,
        "start_date": plan.start_date,
        "end_date": plan.end_date,
        "adults": plan.adults,
        "children": plan.children,
        "budget": plan.budget,
        "currency": plan.currency,
        # NOTE: Settings fields (booking_types, flight_settings, etc.) intentionally
        # OMITTED — they live on the document (set via PATCH from frontend sheets).
    }


def state_to_session_state(state: GraphState) -> Dict[str, Any]:
    """Convert GraphState to session_state dict for persistence."""
    # Keep tiles in CATEGORY format for state restoration
    # Stored as: {"hotels": [tile1, tile2], "flights": [tile3]}
    # We preserve this format so state can be restored correctly on next request

    return {
        "messages": [
            {"role": "human" if m.type == "human" else "assistant", "content": m.content}
            for m in state.messages
        ],
        "trip_inputs": trip_plan_to_trip_inputs(state.trip_plan),
        "metadata": {
            **state.metadata,
            "tiles": state.tiles,  # Keep in category format for state restoration
            "active_specialist": state.active_specialist,
            "constraints_violated": state.constraints_violated,
            # Persist for constraint change detection
            "last_constraint_hash": state.last_constraint_hash,
        },
        # NEW: Field hashes for selective regeneration strategy
        "field_hashes": _compute_field_hashes(state.trip_plan),
    }


def restore_graph_state(session_state: Optional[Dict[str, Any]]) -> GraphState:
    """Restore GraphState from session_state dict."""
    from app.debug_utils import _debug_log

    if not session_state:
        _debug_log("restore_graph_state: No session_state provided, returning empty state")
        state = GraphState()
        # Ensure typed settings exist even on first turn
        state.metadata["trip_inputs"] = {}
        state.metadata["trip_settings"] = TripSettings().model_dump()
        return state

    state = GraphState()

    # NOTE: Per-turn flag resets moved to reset_turn_metadata() at turn boundary.
    # Called from run_turn_streaming() and run_turn_internal() after restore_graph_state().

    # Convert messages
    for msg in session_state.get("messages", []):
        if isinstance(msg, dict):
            if msg.get("role") == "human":
                state.messages.append(HumanMessage(content=msg.get("content", "")))
            else:
                state.messages.append(AIMessage(content=msg.get("content", "")))
        else:
            state.messages.append(msg)

    # Convert trip_inputs to TripPlan
    trip_inputs = session_state.get("trip_inputs", {})
    if trip_inputs:
        state.trip_plan.destination = trip_inputs.get("destination")
        state.trip_plan.origin = trip_inputs.get("origin")
        state.trip_plan.origin_iata = trip_inputs.get("origin_iata")
        state.trip_plan.destination_iata = trip_inputs.get("destination_iata")
        state.trip_plan.start_date = trip_inputs.get("start_date")
        state.trip_plan.end_date = trip_inputs.get("end_date")
        state.trip_plan.adults = trip_inputs.get("adults", 1) or 1
        state.trip_plan.children = trip_inputs.get("children", 0) or 0
        state.trip_plan.budget = trip_inputs.get("budget")
        state.trip_plan.currency = trip_inputs.get("currency", "USD") or "USD"

    # Restore metadata
    metadata = session_state.get("metadata", {})
    state.metadata = {k: v for k, v in metadata.items() if k not in ("tiles", "active_specialist")}

    # Also store trip_inputs in metadata for consistent access (router, specialist detection)
    state.metadata["trip_inputs"] = trip_inputs

    # ── Merge document's user-owned settings (SSoT) ──
    # Session may carry stale defaults from a prior graph run (e.g.,
    # activity_settings.categories=[] even though the user selected
    # ['diving'] via the pill UI).  The document is the SSoT for these
    # fields — main.py reads the latest doc and passes them here.
    doc_settings = session_state.get("_doc_settings", {})
    for field, value in doc_settings.items():
        if value is not None:
            state.metadata["trip_inputs"][field] = value

    # ── Shadow-write: build typed TripSettings from merged trip_inputs ──
    _merged = {**trip_inputs}
    for field, value in doc_settings.items():
        if value is not None:
            _merged[field] = value
    state.metadata["trip_settings"] = TripSettings(
        booking_types=BookingTypes(**(_merged.get("booking_types") or {})),
        flight_settings=FlightSettings(**(_merged.get("flight_settings") or {})),
        hotel_settings=HotelSettings(**(_merged.get("hotel_settings") or {})),
        activity_settings=ActivitySettings(**(_merged.get("activity_settings") or {})),
        transport_settings=TransportSettings(**(_merged.get("transport_settings") or {})),
        date_flex=_merged.get("date_flex", False),
        trip_duration=_merged.get("trip_duration"),
        date_window_start=_merged.get("date_window_start"),
        date_window_end=_merged.get("date_window_end"),
    ).model_dump()

    # HARD TRACE: Log the exact activity_settings reaching the graph
    final_activity = state.metadata["trip_inputs"].get("activity_settings", {})
    final_cats = final_activity.get("categories", []) if isinstance(final_activity, dict) else []
    logger.info(
        f"[RESTORE] activity_settings.categories={final_cats}, "
        f"_doc_settings_keys={list(doc_settings.keys())}, "
        f"doc_activity={doc_settings.get('activity_settings', 'NOT_SET')}"
    )

    state.tiles = metadata.get("tiles", {})
    state.active_specialist = metadata.get("active_specialist")
    state.last_constraint_hash = metadata.get(
        "last_constraint_hash"
    )  # Restore for constraint change detection

    # DEBUG: Log what strategy_sections we're restoring
    incoming_sections = metadata.get("strategy_sections", [])
    restored_sections = state.metadata.get("strategy_sections", [])
    _debug_log(
        f"restore_graph_state: Incoming strategy_sections={len(incoming_sections)}, "
        f"Restored={len(restored_sections)}, "
        f"types={[s.get('specialist_type') for s in incoming_sections]}"
    )

    return state


# =============================================================================
# Private Helpers
# =============================================================================


def _field_hash(value: str) -> str:
    """Stable hash for selective regeneration change detection."""
    return hashlib.sha256((value or "").encode()).hexdigest()[:12]


def _compute_field_hashes(trip_plan: TripPlan) -> Dict[str, str]:
    """
    Compute field hashes for selective regeneration strategy.

    These hashes allow the expand-itinerary endpoint to detect which
    fields changed and compute the minimum regeneration strategy.

    @see docs/plan_graph_analysis.md - Selective Regeneration
    """
    return {
        "destination": _field_hash(trip_plan.destination or ""),
        "dates": _field_hash(f"{trip_plan.start_date or ''}|{trip_plan.end_date or ''}"),
        "travelers": _field_hash(f"{trip_plan.adults or 1}|{trip_plan.children or 0}"),
        "budget": _field_hash(str(trip_plan.budget or "")),
        "origin": _field_hash(trip_plan.origin or ""),
    }
