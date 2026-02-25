"""
Streaming core -- translates create_agent events into the SSE contract.

This module provides ``run_turn_streaming()``, the primary streaming entry
point for the planner agent.  It consumes ``astream_events(version="v2")``
from the compiled agent and yields event dicts that ``streaming.generate_sse()``
consumes:

- ``{"type": "token",       "data": str}``
- ``{"type": "node_status", "data": {...}}``
- ``{"type": "partial",     "data": {...}}``
- ``{"type": "complete",    "data": {...}}``
- ``{"type": "error",       "message": str}``

Integration requirements for ``streaming.py``:
- Error events use flat format ``{"type": "error", "message": "..."}`` (no ``data``
  wrapper), matching the contract that ``generate_sse()`` consumes.
- The ``complete`` event ``data.document`` dict must include ``plan_view_state``
  with proper S3 sub-states derived from builder metadata in ``turn_meta``.
- ``suggested_response_meta`` carries chip progression metadata (list of dicts),
  distinct from ``suggestion_chips`` which holds the full chip objects.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, Dict, Optional

from langchain_core.messages import AIMessage, HumanMessage

from app.debug_utils import _safe_print, get_debug_mode
from app.planner.services.agent_runner import _get_agent
from app.planner.services.state_serde import (
    restore_agent_state,
    serialize_agent_state,
)

logger = logging.getLogger(__name__)

# Agent graph name -- must match the ``name`` kwarg in ``create_planner_agent()``.
_AGENT_GRAPH_NAME = "nomadic_planner"

# ---------------------------------------------------------------------------
# Tool status configuration
# ---------------------------------------------------------------------------
# Maps tool names to human-readable status metadata emitted as ``node_status``
# events.  The frontend progress indicator renders these as step indicators.

_TOOL_STATUS_MAP: Dict[str, Dict[str, Any]] = {
    "extract_trip_fields": {
        "label": "Reading your message...",
        "icon": "brain",
        "duration": 300,
    },
    "get_specialist_advice": {
        "label": "Consulting expert...",
        "icon": "star",
        "duration": 3000,
    },
    "get_local_intel": {
        "label": "Loading local knowledge...",
        "icon": "building",
        "duration": 50,
    },
    "search_tiles": {
        "label": "Searching flights & hotels...",
        "icon": "search",
        "duration": 2000,
    },
    "validate_plan": {
        "label": "Checking your plan...",
        "icon": "shield",
        "duration": 100,
    },
    "build_itinerary": {
        "label": "Building itinerary...",
        "icon": "calendar",
        "duration": 200,
    },
}

# Tools whose results should be emitted as ``partial`` events so the
# frontend can update the UI incrementally before the final response.
_TOOL_PARTIAL_KIND: Dict[str, str] = {
    "extract_trip_fields": "trip_inputs",
    "search_tiles": "tiles",
    "get_specialist_advice": "strategy_sections",
    "get_local_intel": "strategy_sections",
}


# ---------------------------------------------------------------------------
# Tool result extraction helpers
# ---------------------------------------------------------------------------


def _parse_tool_result(content: Any) -> Optional[Dict[str, Any]]:
    """Parse a tool message content string into a dict, or return None."""
    if isinstance(content, dict):
        return content
    if not content or not isinstance(content, str):
        return None
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _extract_partial_payload(
    tool_name: str,
    result_dict: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Build a partial event payload from a tool result, or return None.

    Only tools listed in ``_TOOL_PARTIAL_KIND`` produce partial events.
    The ``kind`` field tells the frontend which UI region to update:

    - ``trip_inputs``        -> setup bar / trip DNA
    - ``tiles``              -> tile carousel
    - ``strategy_sections``  -> strategy cards
    """
    kind = _TOOL_PARTIAL_KIND.get(tool_name)
    if kind is None:
        return None

    if kind == "trip_inputs":
        # Emit the trip_plan dict directly -- TurnLifecycleMiddleware has
        # already merged extracted fields into state by the time the
        # ToolMessage is emitted, but the raw result carries the delta.
        payload = {}
        for field in (
            "destination",
            "origin",
            "start_date",
            "end_date",
            "adults",
            "children",
            "budget",
            "currency",
            "origin_iata",
            "destination_iata",
        ):
            val = result_dict.get(field)
            if val is not None:
                payload[field] = val
        return {"kind": kind, "payload": payload} if payload else None

    if kind == "tiles":
        # Emit ID-keyed tiles to match document.tiles shape on the frontend.
        tiles: Dict[str, Any] = {}
        for category in ("flights", "hotels", "activities"):
            cat_tiles = result_dict.get(category)
            if not isinstance(cat_tiles, list):
                continue
            for tile in cat_tiles:
                if not isinstance(tile, dict):
                    continue
                tile_id = tile.get("id")
                if tile_id:
                    tiles[tile_id] = tile
        return {"kind": kind, "payload": tiles} if tiles else None

    if kind == "strategy_sections":
        # Specialist advice returns ``strategy_section`` (singular);
        # local intel returns ``section``.
        section = result_dict.get("strategy_section") or result_dict.get("section")
        if section:
            return {"kind": kind, "payload": [section]}
        return None

    return None


# ---------------------------------------------------------------------------
# S3 sub-state computation
# ---------------------------------------------------------------------------


def _compute_s3_view_state(turn_meta: Dict[str, Any], day_cards: list) -> str:
    """Derive the correct S3 sub-state from builder metadata in turn_meta.

    The build_itinerary tool merger in TurnLifecycleMiddleware stores
    builder result info in ``turn_meta``.  Use it to determine:

    - ``S3_ITINERARY_READY``   -- success=True, conflicts=0
    - ``S3_EDITING``           -- success=True, conflicts>0
    - ``S3_PARTIAL_CONFLICT``  -- success=False with partial cards
    - ``S3_BLOCKED``           -- success=False, no cards
    """
    builder_result = turn_meta.get("builder_result", {})
    builder_success = builder_result.get("success", True)
    # _merge_itinerary stores conflicts as a list; derive count from its length.
    conflicts = builder_result.get("conflicts", [])
    conflict_count = len(conflicts) if isinstance(conflicts, list) else 0

    if builder_success:
        if conflict_count > 0:
            return "S3_EDITING"
        return "S3_ITINERARY_READY"
    else:
        if day_cards:
            return "S3_PARTIAL_CONFLICT"
        return "S3_BLOCKED"


# ---------------------------------------------------------------------------
# Result envelope builder
# ---------------------------------------------------------------------------


def _build_complete_envelope(
    state: Dict[str, Any],
    assistant_message: str,
    session_id: str = "",
) -> Dict[str, Any]:
    """Build the ``complete`` event data dict matching streaming.py expectations."""
    # Serialization is deferred until after potential auto-build (see below)

    trip_plan: Dict[str, Any] = state.get("trip_plan", {})
    trip_settings: Dict[str, Any] = state.get("trip_settings", {})
    tiles: Dict[str, Any] = state.get("tiles", {})
    strategy_sections: list = state.get("strategy_sections", [])
    day_cards: list = state.get("day_cards", [])
    persistent_meta: Dict[str, Any] = state.get("persistent_meta", {})
    turn_meta: Dict[str, Any] = state.get("turn_meta", {})

    # Suggestion chips from SuggestionChipMiddleware
    suggestion_chips = persistent_meta.get("suggestion_chips", [])
    suggested_replies = [c.get("message", "") for c in suggestion_chips if isinstance(c, dict)]

    # Build trip_inputs from trip_plan + trip_settings
    trip_inputs: Dict[str, Any] = {}
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
        val = trip_plan.get(field)
        if val is not None:
            trip_inputs[field] = val

    # Merge settings sub-dicts into trip_inputs for frontend
    for settings_field in (
        "booking_types",
        "flight_settings",
        "hotel_settings",
        "activity_settings",
        "transport_settings",
    ):
        val = trip_settings.get(settings_field)
        if val:
            trip_inputs[settings_field] = val

    # Determine ready_to_generate
    ready_to_generate = bool(
        trip_plan.get("destination") and trip_plan.get("start_date") and trip_plan.get("end_date")
    )

    # Auto-build: if the agent didn't call build_itinerary but all conditions
    # are met, run the builder now. This ensures S3 auto-expansion when the
    # agent stops after specialist advice + tiles without chaining to build.
    validation_result = turn_meta.get("validation_result", {})
    has_blocking_validation = validation_result.get("blocking_count", 0) > 0
    has_core = bool(
        trip_plan.get("destination") and trip_plan.get("start_date") and trip_plan.get("end_date")
    )
    tools_called = turn_meta.get("tools_called", [])

    # Don't auto-build empty itineraries when user explicitly requested activities
    _act_settings = state.get("trip_settings", {}).get("activity_settings", {})
    _requested_cats = _act_settings.get("categories", []) if isinstance(_act_settings, dict) else []
    _has_activity_tiles = bool(tiles.get("activities"))

    # === FULL DIAGNOSTIC — LAYER 6: AUTO-BUILD DECISION ===
    try:
        if get_debug_mode() in ("compact", "full"):
            _will_auto_build = bool(
                has_core
                and not day_cards
                and not has_blocking_validation
                and (tiles.get("hotels") or tiles.get("activities"))
                and "build_itinerary" not in tools_called
                and (not _requested_cats or _has_activity_tiles)
            )
            _safe_print(
                f"\n[DIAG:AUTO_BUILD] === Envelope Build Decision ===\n"
                f"  has_core: {has_core} (dest={trip_plan.get('destination')}, start={trip_plan.get('start_date')}, end={trip_plan.get('end_date')})\n"
                f"  day_cards_from_agent: {len(day_cards)}\n"
                f"  has_blocking_validation: {has_blocking_validation}\n"
                f"  tiles: hotels={len(tiles.get('hotels') or [])}, activities={len(tiles.get('activities') or [])}\n"
                f"  tools_called: {tools_called}\n"
                f"  requested_cats: {_requested_cats}\n"
                f"  has_activity_tiles: {_has_activity_tiles}\n"
                f"  will_auto_build: {_will_auto_build}"
            )
    except Exception:
        pass
    # === END DIAGNOSTIC ===

    if (
        has_core
        and not day_cards
        and not has_blocking_validation
        and (tiles.get("hotels") or tiles.get("activities"))
        and "build_itinerary" not in tools_called
        and (not _requested_cats or _has_activity_tiles)
    ):
        try:
            from app.services.itinerary_builder import ItineraryBuilder, ItineraryBuilderInput
            from app.utils.tile_utils import flatten_tiles_to_id_map

            tiles_by_category = tiles
            constraints = state.get("constraints", [])
            tile_id_map = flatten_tiles_to_id_map(tiles_by_category)
            # Prefer real strategy_sections from state (specialist data with
            # constraints, metadata, durations).  Fall back to minimal
            # tile-derived sections only when state has none.
            if strategy_sections:
                auto_sections = strategy_sections
            else:
                from app.planner.tools.build_itinerary import _build_strategy_sections

                auto_sections = _build_strategy_sections(tiles_by_category, constraints)
            _auto_act_settings = state.get("trip_settings", {}).get("activity_settings", {})
            _auto_cats = (
                _auto_act_settings.get("categories", [])
                if isinstance(_auto_act_settings, dict)
                else []
            )
            builder_input = ItineraryBuilderInput(
                start_date=trip_plan["start_date"],
                end_date=trip_plan["end_date"],
                strategy_sections=auto_sections,
                tiles=tile_id_map,
                destination=trip_plan["destination"],
                origin=trip_plan.get("origin"),
                activity_categories=_auto_cats or None,
            )
            builder = ItineraryBuilder()
            result = builder.build(builder_input)
            if result.day_cards:
                day_cards = [card.model_dump() for card in result.day_cards]
                state["day_cards"] = day_cards
                turn_meta["builder_result"] = {
                    "success": result.success,
                    "activities_placed": result.total_activities_placed,
                    "activities_dropped": max(
                        0, result.total_activities_input - result.total_activities_placed
                    ),
                    "conflicts": [c.model_dump() for c in result.conflicts],
                    "warnings": result.warnings,
                }
                turn_steps = turn_meta.get("turn_steps", [])
                if isinstance(turn_steps, list):
                    dropped = max(0, result.total_activities_input - result.total_activities_placed)
                    summary = f"Built {len(day_cards)}-day itinerary"
                    if dropped > 0:
                        summary += f" · {dropped} activit{'y' if dropped == 1 else 'ies'} dropped"
                    turn_steps.append({"type": "itinerary", "summary": summary})
                    turn_meta["turn_steps"] = turn_steps
                _safe_print(
                    f"[auto-build] Built {len(day_cards)} day cards for {trip_plan['destination']}"
                )
        except Exception as exc:
            logger.warning("[auto-build] Failed: %s", exc)

    # Auto-generate travel advice skeleton (Phase A) when no strategy
    # sections exist.  This is instant (no LLM) and produces the Trip
    # Overview card.  Phase B background enrichment is stashed for
    # post-commit firing in streaming.py.
    if has_core and not strategy_sections and day_cards:
        try:
            import time as _time

            from app.config import settings as _settings
            from app.data.demo_curation import DEMO_MANIFEST
            from app.placeholders import get_destination_gallery
            from app.planner.nodes.expert_constraints import _get_constraints_as_list
            from app.planner.nodes.local_expert import (
                _MAX_PENDING_ENRICHMENTS,
                _pending_enrichments,
                _pending_enrichments_thread_lock,
                build_enrichment_closure,
            )
            from app.planner.services.section_builder import build_local_expert_section

            _dest = trip_plan["destination"]
            _dest_key = _dest.lower().strip()

            constraint_list = _get_constraints_as_list(_dest)
            constraints_applied = [
                {
                    "rule": c["desc"],
                    "type": c["type"],
                    "severity": c["severity"],
                    "reason": c["desc"],
                }
                for c in constraint_list
            ]
            warning_constraints = [c for c in constraint_list if c["severity"] == "warning"]
            if warning_constraints:
                joined = " & ".join(list({c["type"] for c in warning_constraints})[:2])
                one_liner = f"{_dest}: review {joined} requirements before your trip"
            else:
                one_liner = f"Your adventure in {_dest}"

            gallery = DEMO_MANIFEST.get(_dest_key, {}).get("destination_gallery", [])
            if not gallery:
                gallery = get_destination_gallery(_dest)

            section = build_local_expert_section(
                destination=_dest,
                one_liner=one_liner,
                bullets=[c["desc"] for c in constraint_list[:3]],
                must_dos=[],
                logistics_notes=[],
                constraints_applied=constraints_applied,
                content_added=[],
                gallery_images=gallery,
                travel_intelligence={},
                principles=[c["desc"] for c in warning_constraints[:4]],
            )
            from datetime import UTC, datetime

            section["local_expert_enrichment"] = {
                "state": "pending" if _settings.local_expert_use_llm else "ready",
                "error_code": None if _settings.local_expert_use_llm else "disabled",
                "updated_at": datetime.now(UTC).isoformat(),
            }
            strategy_sections = [section]
            state["strategy_sections"] = strategy_sections

            # Stash Phase B enrichment for background firing
            if _settings.local_expert_use_llm:
                enrich_fn = build_enrichment_closure(
                    destination=_dest,
                    start_date=trip_plan.get("start_date"),
                    end_date=trip_plan.get("end_date"),
                    adults=trip_plan.get("adults", 1),
                    children=trip_plan.get("children", 0),
                    session_id=session_id,
                )
                if enrich_fn is not None:
                    enrich_key = session_id if session_id else f"auto_{_dest_key}"
                    # Use threading lock for synchronous dict access (not in async context).
                    # The asyncio _pending_lock protects async callers; this thread lock
                    # prevents concurrent thread races in sync code paths.
                    with _pending_enrichments_thread_lock:
                        if len(_pending_enrichments) >= _MAX_PENDING_ENRICHMENTS:
                            oldest = next(iter(_pending_enrichments))
                            _pending_enrichments.pop(oldest)
                        _pending_enrichments[enrich_key] = (enrich_fn, _time.monotonic())
                    logger.debug("[auto-build] Phase B enrichment stashed for %s", _dest)

            _safe_print(f"[auto-build] Travel advice skeleton created for {_dest}")
        except Exception as exc:
            logger.warning("[auto-build] Travel advice skeleton failed: %s", exc)

    # Compute plan_view_state BEFORE serialization so it persists in
    # persistent_meta for the next turn's STATE_INIT diagnostic.
    if not has_core:
        plan_view_state = "S0_BOOTSTRAP"
    elif day_cards:
        plan_view_state = _compute_s3_view_state(turn_meta, day_cards)
    elif strategy_sections:
        plan_view_state = "S2_STRATEGY_READY"
    elif tiles.get("hotels") or tiles.get("activities"):
        # Tier 2 categories (food, culture, etc.) don't produce strategy
        # sections but DO load tiles.  Treat tiles-loaded as sufficient
        # to progress past bootstrap — auto-build above will have
        # synthesized sections from tiles and built day_cards already.
        plan_view_state = "S2_STRATEGY_READY"
    else:
        # Core fields set but no content yet — stay in bootstrap so the
        # frontend doesn't open an empty plan panel.
        plan_view_state = "S0_BOOTSTRAP"

    # Write to persistent_meta so it survives serialization
    _pm = dict(state.get("persistent_meta", {}))
    _pm["plan_view_state"] = plan_view_state
    state["persistent_meta"] = _pm

    # Serialize state (after potential auto-build and plan_view_state above)
    serialized = serialize_agent_state(state)

    # Executed topics from strategy sections
    executed_topics = list(
        {
            s.get("specialist_type")
            for s in strategy_sections
            if isinstance(s, dict) and s.get("specialist_type")
        }
    )

    # Validation result from turn_meta
    validation_result = turn_meta.get("validation_result", {})
    raw_constraint_violations = validation_result.get("violations", [])
    constraint_violations = (
        raw_constraint_violations if isinstance(raw_constraint_violations, list) else []
    )
    raw_fields_changed = turn_meta.get("fields_changed", [])
    fields_changed = raw_fields_changed if isinstance(raw_fields_changed, list) else []
    raw_turn_steps = turn_meta.get("turn_steps", [])
    turn_steps = raw_turn_steps if isinstance(raw_turn_steps, list) else []
    ack_updates = [
        {
            "field": str(step.get("type", "update")),
            "to": str(step.get("summary", "")).strip(),
        }
        for step in turn_steps
        if isinstance(step, dict) and str(step.get("summary", "")).strip()
    ]

    # Ack status from constraint blocks and applied field changes
    has_blocking = turn_meta.get("has_blocking_violations", False)
    raw_blocking_violations = turn_meta.get("constraint_violations", [])
    blocking_violations = (
        raw_blocking_violations if isinstance(raw_blocking_violations, list) else []
    )
    if has_blocking and blocking_violations:
        constraint_violations = blocking_violations
    route_violation = next(
        (v for v in constraint_violations if isinstance(v, dict) and v.get("category") == "route"),
        None,
    )
    if route_violation:
        ack_status = "rejected"
        ack_updates = [{"field": "route", "to": route_violation.get("code", "INVALID_ROUTE")}]
    elif ack_updates:
        ack_status = "applied"
    else:
        ack_status = "no_change"

    # constraints_validated mirrors v1: list of constraint check names that ran
    constraints_validated = ["validate_plan"] if validation_result.get("valid") is not None else []

    # Flatten tiles from category format to ID-based map
    flattened_tiles: Dict[str, Any] = {}
    for _category, tile_list in tiles.items():
        if not isinstance(tile_list, list):
            continue
        for tile in tile_list:
            if isinstance(tile, dict):
                tile_id = tile.get("id")
                if tile_id:
                    flattened_tiles[tile_id] = tile

    # Derive origin_just_set and tiles_replaced from turn_meta
    origin_just_set = bool(turn_meta.get("origin_just_set", False))
    tiles_replaced = bool(turn_meta.get("tiles_replaced", False))

    # Browseable activities from turn_meta (Tier 1 suppressed tiles)
    browseable_activities = turn_meta.get("browseable_activities", [])

    document: Dict[str, Any] = {
        "trip_context_id": None,
        "trip_inputs": trip_inputs,
        "branches": [],
        "tiles": flattened_tiles,
        "assistant_message": assistant_message,
        "ready_to_generate": ready_to_generate,
        "suggested_responses": suggested_replies,
        "suggested_response_meta": persistent_meta.get("suggestion_chip_meta", []),
        "suggestion_chips": suggestion_chips,
        "plan_view_state": plan_view_state,
        "strategy_sections": strategy_sections,
        "pending_strategy_topics": [],
        "executed_strategy_topics": executed_topics,
        "origin_just_set": origin_just_set,
        "tiles_replaced": tiles_replaced,
        "constraints_validated": constraints_validated,
        "constraint_violations": constraint_violations,
        "browseable_activities": browseable_activities,
        "itinerary_day_cards": day_cards if day_cards else None,
        "ack_status": ack_status,
        "ack_updates": ack_updates,
        "applied_updates": fields_changed,
        "_debug": {},
    }

    return {
        "session_state": serialized,
        "assistant_message": assistant_message,
        "suggestion_chips": suggestion_chips,
        "suggested_responses": suggested_replies,
        "trip_inputs": trip_inputs,
        "branches": [],
        "ready_to_generate": ready_to_generate,
        "changes_made": True,
        "document": document,
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_ALLOWED_DOC_SETTINGS_KEYS: frozenset[str] = frozenset(
    {
        "booking_types",
        "flight_settings",
        "hotel_settings",
        "activity_settings",
        "transport_settings",
    }
)


async def run_turn_streaming(
    user_message: str,
    session_state: Optional[Dict[str, Any]] = None,
    doc_settings: Optional[Dict[str, Any]] = None,
    session_id: str = "",
) -> AsyncGenerator[Dict[str, Any], None]:
    """Streaming entry point for the planner agent.

    Yields SSE-compatible events consumed by ``streaming.generate_sse()``:

    - ``{"type": "token",       "data": str}``           -- streaming text chunks
    - ``{"type": "node_status", "data": {...}}``         -- tool execution status
    - ``{"type": "partial",     "data": {...}}``         -- incremental data
    - ``{"type": "complete",    "data": {...}}``         -- final result envelope
    - ``{"type": "error",       "message": str}``        -- errors (flat format)

    Parameters
    ----------
    user_message : str
        The user's chat message.
    session_state : dict | None
        Previously serialized session state, or None for a fresh conversation.
    doc_settings : dict | None
        User-owned settings from the document (activity_settings, booking_types,
        etc.).  Merged into ``trip_settings`` before the agent sees state.
    session_id : str
        Session identifier for logging and config threading.
    """
    wall_start = time.monotonic()

    # ------------------------------------------------------------------
    # 1. Restore agent state from session
    # ------------------------------------------------------------------
    state = restore_agent_state(session_state)

    # Verify turn_meta is clean on restore (B3 regression guard)
    _restored_tm = state.get("turn_meta", {})
    _restored_tools = _restored_tm.get("tools_called", [])
    if _restored_tools:
        logger.warning(
            "[GUARD:TURN_META] Stale tools_called on restore: %s — "
            "state_serde may be serializing turn_meta again",
            _restored_tools,
        )

    # Merge doc_settings into trip_settings — detect category changes.
    if doc_settings:
        trip_settings = dict(state.get("trip_settings", {}))
        _old_as = trip_settings.get("activity_settings", {})
        _old_cats = set(_old_as.get("categories", []) if isinstance(_old_as, dict) else [])
        for field, value in doc_settings.items():
            if value is not None and field in _ALLOWED_DOC_SETTINGS_KEYS:
                trip_settings[field] = value
        state["trip_settings"] = trip_settings

        # When activity categories changed via PATCH, clear stale day_cards
        # and activity tiles so auto-build re-runs with fresh data.
        _new_as = trip_settings.get("activity_settings", {})
        _new_cats = set(_new_as.get("categories", []) if isinstance(_new_as, dict) else [])
        if _old_cats != _new_cats and (_old_cats or _new_cats):
            state["day_cards"] = []
            _tiles = state.get("tiles", {})
            if isinstance(_tiles, dict):
                _tiles["activities"] = []
                state["tiles"] = _tiles
            logger.info(
                "[run_turn_streaming] Categories changed %s -> %s — "
                "cleared day_cards + activity tiles",
                sorted(_old_cats),
                sorted(_new_cats),
            )
            _verify_tiles = state.get("tiles", {})
            logger.info(
                "[GUARD:TILE_CLEAR:PG] activities_after=%d day_cards_after=%d",
                len(_verify_tiles.get("activities", [])),
                len(state.get("day_cards", [])),
            )

    # Append the user message
    state["messages"].append(HumanMessage(content=user_message))

    # === FULL DIAGNOSTIC BLOCK — LAYER 1: STATE INIT ===
    try:
        if get_debug_mode() in ("compact", "full"):
            _diag_tp = state.get("trip_plan", {})
            _diag_ts = state.get("trip_settings", {})
            _diag_tiles = state.get("tiles", {})
            _diag_sections = state.get("strategy_sections", [])
            _diag_msgs = state.get("messages", [])
            _safe_print(
                f"\n[DIAG:STATE_INIT] === Agent State at Turn Start ===\n"
                f"  user_message: {user_message[:80]!r}\n"
                f"  trip_plan: dest={_diag_tp.get('destination')}, dates={_diag_tp.get('start_date')}\u2192{_diag_tp.get('end_date')}, origin={_diag_tp.get('origin')}\n"
                f"  trip_settings.activity_settings: {_diag_ts.get('activity_settings')}\n"
                f"  trip_settings.booking_types: {_diag_ts.get('booking_types')}\n"
                f"  tiles: hotels={len(_diag_tiles.get('hotels', []))}, activities={len(_diag_tiles.get('activities', []))}, flights={len(_diag_tiles.get('flights', []))}\n"
                f"  strategy_sections: {len(_diag_sections)} (types={[s.get('specialist_type') for s in _diag_sections if isinstance(s, dict)]})\n"
                f"  day_cards: {len(state.get('day_cards', []))}\n"
                f"  messages: {len(_diag_msgs)} (last_human={str(_diag_msgs[-1].content[:60]) if _diag_msgs else 'NONE'!r})\n"
                f"  constraints: {len(state.get('constraints', []))}\n"
                f"  persistent_meta.plan_view_state: {state.get('persistent_meta', {}).get('plan_view_state', '?')}"
            )
    except Exception:
        pass
    # === END DIAGNOSTIC ===

    _safe_print(
        f"[run_turn_streaming] session={session_id or '(none)'}, messages={len(state['messages'])}, user={user_message[:80]!r}"
    )

    # ------------------------------------------------------------------
    # 2. Get the agent and prepare config
    # ------------------------------------------------------------------
    agent = _get_agent()

    config: Dict[str, Any] = {
        "configurable": {"thread_id": session_id} if session_id else {},
    }

    # ------------------------------------------------------------------
    # 3. Stream events with timeout
    # ------------------------------------------------------------------
    STREAM_TIMEOUT_SECONDS = 60

    active_tool: Optional[str] = None
    assistant_chunks: list[str] = []
    final_state: Optional[Dict[str, Any]] = None

    # Per-invocation token buffering.
    #
    # Text tokens arrive BEFORE tool_call_chunks in the same invocation,
    # so we can't immediately yield them — they might be intermediate
    # reasoning before a tool call.  Buffer per invocation:
    # - If tool_call_chunks appear → discard the buffer (intermediate text)
    # - If next on_chat_model_start fires → flush buffer (confirmed final)
    # - After loop ends → flush remaining buffer (last invocation)
    _invocation_buffer: list[str] = []
    _current_invocation_has_tools = False
    _model_invocation_count = 0

    try:
        async with asyncio.timeout(STREAM_TIMEOUT_SECONDS):
            async for event in agent.astream_events(
                state,
                config=config,
                version="v2",
            ):
                event_type = event.get("event")

                # ---------------------------------------------------------
                # Tool start -> emit node_status "started"
                # ---------------------------------------------------------
                if event_type == "on_tool_start":
                    tool_name = event.get("name", "")
                    active_tool = tool_name

                    status_meta = _TOOL_STATUS_MAP.get(tool_name, {})
                    yield {
                        "type": "node_status",
                        "data": {
                            "node": tool_name,
                            "status": "started",
                            "label": status_meta.get("label", tool_name),
                            "icon_key": status_meta.get("icon", "cog"),
                            "estimated_duration_ms": status_meta.get("duration", 1000),
                        },
                    }

                # ---------------------------------------------------------
                # Tool end -> emit partial + node_status "completed"
                # ---------------------------------------------------------
                elif event_type == "on_tool_end":
                    tool_name = event.get("name", active_tool or "")
                    output = event.get("data", {}).get("output")

                    # Parse tool result and emit partial if applicable
                    if output is not None:
                        # output may be a ToolMessage or raw content
                        content = output.content if hasattr(output, "content") else output
                        result_dict = _parse_tool_result(content)
                        if result_dict is not None:
                            partial = _extract_partial_payload(tool_name, result_dict)
                            if partial is not None:
                                yield {
                                    "type": "partial",
                                    "data": partial,
                                }

                    # === FULL DIAGNOSTIC — LAYER 5: TOOL RESULT ===
                    try:
                        if get_debug_mode() in ("compact", "full"):
                            _output_summary = str(content)[:300] if output is not None else "NONE"
                            _safe_print(
                                f"\n[DIAG:TOOL_RESULT] === {tool_name} returned ===\n"
                                f"  output_type: {type(output).__name__ if output is not None else 'None'}\n"
                                f"  output_preview: {_output_summary}"
                            )
                    except Exception:
                        pass
                    # === END DIAGNOSTIC ===

                    yield {
                        "type": "node_status",
                        "data": {
                            "node": tool_name,
                            "status": "completed",
                        },
                    }
                    active_tool = None

                # ---------------------------------------------------------
                # LLM streaming -> buffer tokens per invocation
                # ---------------------------------------------------------
                elif event_type == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk is None:
                        continue

                    # Detect tool-call data in this chunk.
                    has_tool_calls = (
                        hasattr(chunk, "tool_call_chunks") and chunk.tool_call_chunks
                    ) or (hasattr(chunk, "tool_calls") and chunk.tool_calls)

                    if has_tool_calls:
                        _current_invocation_has_tools = True
                        _invocation_buffer.clear()  # discard — intermediate reasoning

                        # === FULL DIAGNOSTIC — LAYER 4: TOOL CALL ===
                        try:
                            if get_debug_mode() in ("compact", "full"):
                                _tc_chunks = getattr(chunk, "tool_call_chunks", []) or getattr(
                                    chunk, "tool_calls", []
                                )
                                for _tc in _tc_chunks:
                                    _tc_name = (
                                        _tc.get("name")
                                        if isinstance(_tc, dict)
                                        else getattr(_tc, "name", "?")
                                    )
                                    _tc_args = (
                                        _tc.get("args")
                                        if isinstance(_tc, dict)
                                        else getattr(_tc, "args", "")
                                    )
                                    if _tc_name:
                                        _safe_print(
                                            f"[DIAG:TOOL_CALL] invocation=#{_model_invocation_count} tool={_tc_name} args={str(_tc_args)[:200]}"
                                        )
                        except Exception:
                            pass
                        # === END DIAGNOSTIC ===
                        continue

                    if _current_invocation_has_tools:
                        continue

                    content = getattr(chunk, "content", None)
                    if content:
                        _invocation_buffer.append(content)

                # ---------------------------------------------------------
                # Chat model start -> flush previous invocation buffer
                # ---------------------------------------------------------
                elif event_type == "on_chat_model_start":
                    # Previous invocation ended.  If it had no tools,
                    # its buffered tokens are a confirmed text response.
                    if _invocation_buffer and not _current_invocation_has_tools:
                        for buffered in _invocation_buffer:
                            assistant_chunks.append(buffered)
                            yield {"type": "token", "data": buffered}
                    _invocation_buffer.clear()
                    _current_invocation_has_tools = False
                    _model_invocation_count += 1
                    logger.debug(
                        "[STREAM] on_chat_model_start invocation=#%d chunks_so_far=%d",
                        _model_invocation_count,
                        len(assistant_chunks),
                    )

                    # === FULL DIAGNOSTIC — LAYER 3: LLM INVOCATION ===
                    try:
                        if get_debug_mode() in ("compact", "full"):
                            _inv_data = event.get("data", {})
                            # LangGraph v2 uses data.input (list or dict w/ messages)
                            _inv_input = _inv_data.get("input", {})
                            if isinstance(_inv_input, dict):
                                _last_msgs = _inv_input.get("messages", [])
                            elif isinstance(_inv_input, list):
                                _last_msgs = _inv_input
                            else:
                                # Legacy fallback: data.messages is batched [[msg, ...]]
                                _inv_batched = _inv_data.get("messages", [[]])
                                _last_msgs = _inv_batched[0] if _inv_batched else []
                            _msg_summary = []
                            for _m in _last_msgs[-3:]:
                                _mtype = type(_m).__name__
                                _mcontent = str(getattr(_m, "content", ""))[:120]
                                _mtools = getattr(_m, "tool_calls", [])
                                _msg_summary.append(
                                    f"    {_mtype}: {_mcontent}"
                                    + (
                                        f" [tools={[t['name'] for t in _mtools]}]"
                                        if _mtools
                                        else ""
                                    )
                                )
                            _safe_print(
                                f"\n[DIAG:LLM_INVOKE] === Invocation #{_model_invocation_count} ===\n"
                                f"  model: {event.get('name', '?')}\n"
                                f"  total_messages: {len(_last_msgs)}\n"
                                f"  last 3 messages:\n" + "\n".join(_msg_summary)
                            )
                    except Exception:
                        pass
                    # === END DIAGNOSTIC ===

                # ---------------------------------------------------------
                # Chain end -> capture final agent state
                # ---------------------------------------------------------
                elif event_type == "on_chain_end":
                    # Only capture the top-level agent graph output, not
                    # intermediate chain_end events from tools or sub-chains.
                    ev_name = event.get("name", "")
                    output = event.get("data", {}).get("output")
                    logger.debug(
                        "[STREAM] on_chain_end name=%r has_output=%s has_messages=%s",
                        ev_name[:40] if ev_name else "",
                        output is not None,
                        "messages" in output if isinstance(output, dict) else False,
                    )
                    if (
                        ev_name == _AGENT_GRAPH_NAME
                        and isinstance(output, dict)
                        and "messages" in output
                    ):
                        final_state = output

        # ------------------------------------------------------------------
        # 4. Flush remaining invocation buffer and build complete event
        # ------------------------------------------------------------------
        # Final invocation's buffer — if it had no tools, flush to output.
        if _invocation_buffer and not _current_invocation_has_tools:
            for buffered in _invocation_buffer:
                assistant_chunks.append(buffered)
                yield {"type": "token", "data": buffered}
            _invocation_buffer.clear()

        assistant_message = "".join(assistant_chunks)

        # Merge final state with input state so fields not touched by the
        # agent this turn (e.g. tiles, strategy_sections from a prior turn)
        # are preserved.  final_state may only contain delta keys when the
        # agent responds without calling any tools.
        result_state = {**state, **(final_state or {})}

        # Authoritative assistant message extraction from final_state.
        #
        # on_chat_model_stream events do NOT fire through middleware-wrapped
        # model calls (DynamicPromptMiddleware.awrap_model_call masks them),
        # so assistant_chunks is typically empty.  Extract the response from
        # final_state.messages which is always populated after the agent
        # completes.  Search only the current turn (after last HumanMessage)
        # to avoid replaying stale greetings from prior turns.
        if not assistant_message and final_state:
            fs_messages = final_state.get("messages", [])
            # Find current turn boundary
            turn_start = 0
            for i in range(len(fs_messages) - 1, -1, -1):
                if isinstance(fs_messages[i], HumanMessage):
                    turn_start = i
                    break
            # Walk backward — last AIMessage with content IS the response.
            # Accept messages WITH tool_calls: some models produce content
            # alongside tool invocations and the content is the response text.
            for msg in reversed(fs_messages[turn_start:]):
                if isinstance(msg, AIMessage) and msg.content:
                    assistant_message = msg.content
                    break

        if assistant_message and not assistant_chunks:
            _safe_print(
                f"[STREAM_FALLBACK] Extracted {len(assistant_message)} chars from final_state (invocations={_model_invocation_count})"
            )
            yield {"type": "token", "data": assistant_message}
        elif not assistant_message:
            # GENERATE_PLAN_NOW triggers tool-only turns (validate + build)
            # with no conversational text. The itinerary IS the response.
            tools_called = result_state.get("turn_meta", {}).get("tools_called", [])
            if "build_itinerary" in tools_called:
                assistant_message = "Your itinerary has been updated!"
                yield {"type": "token", "data": assistant_message}
            else:
                logger.warning(
                    "[STREAM_FALLBACK] No assistant text found (invocations=%d, "
                    "final_state=%s, result_messages=%d)",
                    _model_invocation_count,
                    "captured" if final_state else "NONE",
                    len(result_state.get("messages", [])),
                )

        envelope = _build_complete_envelope(result_state, assistant_message, session_id=session_id)

        # Auto-build runs inside _build_complete_envelope. If it produced
        # day_cards but the agent never emitted text, send a canned response.
        if not assistant_message and result_state.get("turn_meta", {}).get("builder_result"):
            assistant_message = "Your itinerary has been built!"
            yield {"type": "token", "data": assistant_message}
            envelope["assistant_message"] = assistant_message
            if "document" in envelope and isinstance(envelope["document"], dict):
                envelope["document"]["assistant_message"] = assistant_message

        wall_ms = int((time.monotonic() - wall_start) * 1000)
        _safe_print(
            f"[run_turn_streaming] session={session_id or '(none)'}, wall={wall_ms}ms, tokens={len(assistant_chunks)}, tools={result_state.get('turn_meta', {}).get('tools_called', [])}"
        )

        # === FULL DIAGNOSTIC — LAYER 7: FINAL ENVELOPE ===
        try:
            if get_debug_mode() in ("compact", "full"):
                _e_tiles = envelope.get("document", {}).get("tiles", {})
                _e_dc = envelope.get("document", {}).get("itinerary_day_cards") or []
                _safe_print(
                    f"\n[DIAG:ENVELOPE] === Final SSE Envelope ===\n"
                    f"  plan_view_state: {envelope.get('document', {}).get('plan_view_state')}\n"
                    f"  assistant_message: {(assistant_message or '')[:80]!r}\n"
                    f"  tiles: {len(_e_tiles) if isinstance(_e_tiles, dict) else 0} (activity_ids={[k for k in (_e_tiles if isinstance(_e_tiles, dict) else {}) if 'activity' in k.lower()][:5]})\n"
                    f"  day_cards: {len(_e_dc) if isinstance(_e_dc, list) else 0}\n"
                    f"  activity_settings_in_trip_inputs: {envelope.get('document', {}).get('trip_inputs', {}).get('activity_settings')}\n"
                    f"  strategy_sections: {len(envelope.get('document', {}).get('strategy_sections', []))}\n"
                    f"  ack_updates: {envelope.get('document', {}).get('ack_updates', [])}"
                )
        except Exception:
            pass
        # === END DIAGNOSTIC ===
        yield {"type": "complete", "data": envelope}

    except TimeoutError:
        logger.error(
            "[run_turn_streaming] Stream timed out after %ds (session=%s)",
            STREAM_TIMEOUT_SECONDS,
            session_id,
        )
        yield {"type": "error", "message": "Request timed out. Please try again."}

    except Exception as exc:
        logger.error(
            "[run_turn_streaming] Stream failed (session=%s): %s",
            session_id,
            exc,
            exc_info=True,
        )
        yield {"type": "error", "message": str(exc)}
