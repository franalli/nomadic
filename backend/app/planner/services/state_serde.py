"""
State serialization and deserialization utilities.

Handles conversion between:
- GraphState ↔ session_state dict (for persistence)
- TripPlan → trip_inputs dict (for frontend document envelope)
- Field hashing for selective regeneration

Extracted from plan_graph.py (Stage 7, Phase 1).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    messages_from_dict,
    messages_to_dict,
)

from app.planner.state import GraphState, TripPlan, TripSettings
from app.schemas import (
    ActivitySettings,
    BookingTypes,
    FlightSettings,
    HotelSettings,
    TransportSettings,
)
from app.services.regen_strategy import compute_field_hashes

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
        "field_hashes": compute_field_hashes(_trip_plan_to_inputs_dict(state.trip_plan)),
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
# Agent State Serialization (create_agent path)
# =============================================================================

# Maximum messages to persist.  Keeps last N messages (default 20 = 10 turns)
# while always preserving the first 2 messages (system + first human) for
# context grounding.
_DEFAULT_MAX_MESSAGES = 20


def _agent_state_defaults() -> Dict[str, Any]:
    """Return fresh default values for NomadicAgentState.

    Must be a function (not a module-level dict) to avoid mutable default
    aliasing -- callers that mutate the returned dict won't corrupt a
    shared object.
    """
    return {
        "trip_plan": {},
        "trip_settings": {},
        "tiles": {},
        "strategy_sections": [],
        "day_cards": [],
        "constraints": [],
        "turn_meta": {},
        "persistent_meta": {},
    }


def _trim_messages(
    messages: list[BaseMessage],
    max_messages: int = _DEFAULT_MAX_MESSAGES,
) -> list[BaseMessage]:
    """Keep first 2 messages (system + first human) and last N to prevent token bloat.

    If total messages <= max_messages, returns the full list unchanged.
    Otherwise, returns [first_2] + [last (max_messages - 2)].
    """
    if len(messages) <= max_messages:
        return list(messages)

    # Always keep the first 2 for context grounding
    head_count = min(2, len(messages))
    head = messages[:head_count]
    tail_count = max_messages - head_count
    tail = messages[-tail_count:] if tail_count > 0 else []
    return head + tail


def serialize_agent_state(
    state: Dict[str, Any],
    max_messages: int = _DEFAULT_MAX_MESSAGES,
) -> Dict[str, Any]:
    """Serialize NomadicAgentState dict -> session_state dict for DB persistence.

    Keeps last N message pairs (configurable) to prevent token bloat.
    Uses LangChain's ``messages_to_dict`` for full-fidelity message
    serialization (handles AIMessage.tool_calls, ToolMessage.tool_call_id,
    SystemMessage, etc.).

    All non-message fields (trip_plan, tiles, constraints, ...) are passed
    through as-is since they are already plain dicts/lists inside
    NomadicAgentState.
    """
    raw_messages: list = state.get("messages", [])

    # Convert everything to BaseMessage first so trimming and
    # serialization treat all messages uniformly and preserve order.
    message_objects: list[BaseMessage] = []
    for m in raw_messages:
        if isinstance(m, BaseMessage):
            message_objects.append(m)
        elif isinstance(m, dict):
            # Passthrough dict -- coerce to HumanMessage so it survives
            # trim + messages_to_dict uniformly (preserves original order).
            message_objects.append(HumanMessage(content=str(m.get("content", ""))))

    trimmed = _trim_messages(message_objects, max_messages)
    serialized_messages = messages_to_dict(trimmed)

    result: Dict[str, Any] = {"messages": serialized_messages}

    # Copy all non-message fields from state
    for key in (
        "trip_plan",
        "trip_settings",
        "tiles",
        "strategy_sections",
        "day_cards",
        "constraints",
        "turn_meta",
        "persistent_meta",
    ):
        if key in state:
            result[key] = state[key]

    return result


def restore_agent_state(session_state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Deserialize session_state dict -> NomadicAgentState dict.

    Returns a fresh state with default values if ``session_state`` is None.
    Uses LangChain's ``messages_from_dict`` for full-fidelity message
    deserialization.
    """
    if not session_state:
        logger.debug("restore_agent_state: no session_state, returning defaults")
        return {**_agent_state_defaults(), "messages": []}

    # Restore messages -- single-pass to preserve interleaved order
    raw_messages = session_state.get("messages", [])
    restored_messages: list[BaseMessage] = []

    for m in raw_messages:
        if isinstance(m, BaseMessage):
            restored_messages.append(m)
        elif isinstance(m, dict) and "type" in m and "data" in m:
            # Single LangChain-format dict -- deserialize immediately
            # to preserve order relative to legacy dicts / BaseMessages.
            restored_messages.extend(messages_from_dict([m]))
        elif isinstance(m, dict):
            # Legacy format from existing graph path: {"role": ..., "content": ...}
            role = m.get("role", "assistant")
            content = m.get("content", "")
            if role == "human":
                restored_messages.append(HumanMessage(content=content))
            else:
                restored_messages.append(AIMessage(content=content))

    result: Dict[str, Any] = {"messages": restored_messages}

    # Restore all non-message fields with fresh defaults
    defaults = _agent_state_defaults()
    for key, default in defaults.items():
        if key == "messages":
            continue
        result[key] = session_state.get(key, default)

    _migrate_legacy_agent_fields(session_state, result)
    result["trip_settings"] = _normalize_agent_trip_settings(result.get("trip_settings", {}))

    return result


# =============================================================================
# Private Helpers
# =============================================================================


def _trip_plan_to_inputs_dict(trip_plan: TripPlan) -> Dict[str, Any]:
    """Convert TripPlan fields to the dict format expected by compute_field_hashes."""
    return {
        "destination": trip_plan.destination or "",
        "start_date": str(trip_plan.start_date) if trip_plan.start_date else "",
        "end_date": str(trip_plan.end_date) if trip_plan.end_date else "",
        "adults": trip_plan.adults,
        "children": trip_plan.children,
        "budget": trip_plan.budget,
        "origin": trip_plan.origin or "",
    }


def _normalize_agent_trip_settings(raw_settings: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize legacy flat trip_settings keys into nested settings dicts."""
    trip_settings = dict(raw_settings) if isinstance(raw_settings, dict) else {}

    flight_settings = trip_settings.get("flight_settings", {})
    flight_settings = dict(flight_settings) if isinstance(flight_settings, dict) else {}

    hotel_settings = trip_settings.get("hotel_settings", {})
    hotel_settings = dict(hotel_settings) if isinstance(hotel_settings, dict) else {}

    activity_settings = trip_settings.get("activity_settings", {})
    activity_settings = dict(activity_settings) if isinstance(activity_settings, dict) else {}

    if "flight_direct_only" in trip_settings and "direct_only" not in flight_settings:
        val = trip_settings.get("flight_direct_only")
        if val is not None:
            flight_settings["direct_only"] = bool(val)
    if "flight_cabin_class" in trip_settings and "cabin_class" not in flight_settings:
        val = trip_settings.get("flight_cabin_class")
        if val is not None:
            flight_settings["cabin_class"] = val

    if "hotel_min_stars" in trip_settings and "min_stars" not in hotel_settings:
        val = trip_settings.get("hotel_min_stars")
        if val is not None:
            hotel_settings["min_stars"] = val
    if "hotel_amenities" in trip_settings and "amenities" not in hotel_settings:
        val = trip_settings.get("hotel_amenities")
        if val is not None:
            hotel_settings["amenities"] = val
    if "hotel_style" in trip_settings and "style" not in hotel_settings:
        val = trip_settings.get("hotel_style")
        if val is not None:
            hotel_settings["style"] = val
    if "hotel_location" in trip_settings and "location" not in hotel_settings:
        val = trip_settings.get("hotel_location")
        if val is not None:
            hotel_settings["location"] = val

    if "skill_level" in trip_settings and "skill_level" not in activity_settings:
        val = trip_settings.get("skill_level")
        if val is not None:
            activity_settings["skill_level"] = val
    if "activity_categories" in trip_settings and "categories" not in activity_settings:
        val = trip_settings.get("activity_categories")
        if val is not None:
            activity_settings["categories"] = val

    if flight_settings:
        trip_settings["flight_settings"] = flight_settings
    if hotel_settings:
        trip_settings["hotel_settings"] = hotel_settings
    if activity_settings:
        trip_settings["activity_settings"] = activity_settings

    for legacy_field in (
        "skill_level",
        "hotel_min_stars",
        "hotel_style",
        "hotel_amenities",
        "hotel_location",
        "flight_direct_only",
        "flight_cabin_class",
        "activity_categories",
    ):
        trip_settings.pop(legacy_field, None)

    return trip_settings


def _migrate_legacy_agent_fields(session_state: Dict[str, Any], result: Dict[str, Any]) -> None:
    """Backfill create_agent state from legacy persisted graph fields."""
    legacy_trip_inputs = session_state.get("trip_inputs", {})
    if isinstance(legacy_trip_inputs, dict):
        if not result.get("trip_plan"):
            trip_plan: Dict[str, Any] = {}
            for field in (
                "destination",
                "origin",
                "origin_iata",
                "destination_iata",
                "start_date",
                "end_date",
                "adults",
                "children",
                "budget",
                "currency",
            ):
                val = legacy_trip_inputs.get(field)
                if val is not None:
                    trip_plan[field] = val
            categories = (
                legacy_trip_inputs.get("activity_settings", {}).get("categories", [])
                if isinstance(legacy_trip_inputs.get("activity_settings"), dict)
                else []
            )
            if categories:
                trip_plan["activity_categories"] = categories
            if trip_plan:
                result["trip_plan"] = trip_plan

        if not result.get("trip_settings"):
            trip_settings: Dict[str, Any] = {}
            for settings_field in (
                "booking_types",
                "flight_settings",
                "hotel_settings",
                "activity_settings",
                "transport_settings",
                "date_flex",
                "trip_duration",
                "date_window_start",
                "date_window_end",
            ):
                val = legacy_trip_inputs.get(settings_field)
                if val is not None:
                    trip_settings[settings_field] = val
            if trip_settings:
                result["trip_settings"] = trip_settings

    legacy_meta = session_state.get("metadata", {})
    if not isinstance(legacy_meta, dict):
        return

    if not result.get("tiles") and isinstance(legacy_meta.get("tiles"), dict):
        result["tiles"] = legacy_meta.get("tiles", {})
    if not result.get("strategy_sections") and isinstance(
        legacy_meta.get("strategy_sections"), list
    ):
        result["strategy_sections"] = legacy_meta.get("strategy_sections", [])
    if not result.get("day_cards") and isinstance(legacy_meta.get("day_cards"), list):
        result["day_cards"] = legacy_meta.get("day_cards", [])
    if not result.get("constraints") and isinstance(legacy_meta.get("constraints"), list):
        result["constraints"] = legacy_meta.get("constraints", [])

    if not result.get("trip_settings") and isinstance(legacy_meta.get("trip_settings"), dict):
        result["trip_settings"] = legacy_meta.get("trip_settings", {})

    persistent_meta = result.get("persistent_meta", {})
    persistent_meta = dict(persistent_meta) if isinstance(persistent_meta, dict) else {}
    for key in ("plan_view_state", "suggestion_chips", "suggestion_chip_meta", "session_id"):
        if key not in persistent_meta and key in legacy_meta:
            persistent_meta[key] = legacy_meta[key]
    result["persistent_meta"] = persistent_meta
