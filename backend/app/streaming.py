"""
Streaming generators extracted from main.py.

- generate_sse(): SSE async generator for /api/graph_plan/stream
- generate_ndjson(): NDJSON async generator for /api/expand-itinerary
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List

from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request

from app.config import settings
from app.crud_document import (
    apply_planner_update,
    get_document,
    get_document_data,
    get_or_create_document,
)
from app.crud_trip import (
    get_latest_trip_context_for_session,
    get_or_create_session,
    get_session_by_token,
    record_chat_message,
)
from app.db import _get_async_session_factory
from app.debug_utils import _debug, log_llm_output, log_user_input
from app.graph_plan_utils import (
    normalize_trip_inputs,
    truncate_assistant_message,
    validate_suggested_responses,
)
from app.planner.services.admin_utils import condense_long_message
from app.schemas import (
    AckUpdate,
    BookingStatus,
    BookingStatusItem,
    DayCard,
    DestinationCard,
    ExpandItineraryRequest,
    ExpandItineraryStreamEvent,
    GraphPlanRequest,
    PlanDocumentData,
    PlanViewState,
    ReadinessItem,
    StrategySection,
    Tile,
)
from app.services.regen_strategy import (
    RegenStrategy,
    compute_field_hashes,
    compute_strategy,
    detect_changed_fields,
    get_strategy_description,
)
from app.services.spend_guard import spend_guard_scope
from app.services.task_tracker import track as _track_bg_task
from app.services.unsplash import get_image_url_sync

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers (moved from main.py — only used by generators)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class TripReadiness:
    """Simple trip readiness checker."""

    has_origin: bool
    has_destination: bool
    has_dates: bool
    core_complete: bool


def compute_trip_readiness(trip_inputs: Dict[str, Any], errors: List[Any] = None) -> TripReadiness:
    """Compute trip readiness from trip inputs."""
    _ = errors  # compatibility: callers pass validation errors, readiness currently ignores them
    destination = trip_inputs.get("destination")
    return TripReadiness(
        has_origin=bool(trip_inputs.get("origin")),
        has_destination=bool(destination),
        has_dates=bool(trip_inputs.get("start_date")),
        core_complete=bool(destination and trip_inputs.get("start_date")),
    )


def _normalized_preference_ids(values: List[str] | None) -> List[str]:
    """Return deduplicated/sorted preference ids for stable hashing."""
    if not values:
        return []
    return sorted({v for v in values if v})


def _flatten_request_preferences(preferences: Any) -> Dict[str, Any]:
    """Convert API request preference shape to a stable hashable snapshot."""
    if not preferences:
        return {"preferred_tile_ids": []}

    combined_ids: List[str] = []
    combined_ids.extend(preferences.preferred_hotel_ids or [])
    combined_ids.extend(preferences.preferred_activity_ids or [])
    combined_ids.extend(preferences.preferred_flight_ids or [])
    return {"preferred_tile_ids": _normalized_preference_ids(combined_ids)}


def _get_trip_input_display_value(ui_key: str, trip_inputs: dict) -> str | None:
    """
    Get human-readable display value for a UI key from trip_inputs.

    Maps canonical UI keys to their corresponding trip_inputs values
    and formats them for display in collapsible message summaries.
    """
    # Map UI key to trip_inputs field(s)
    if ui_key == "destination":
        return trip_inputs.get("destination")
    elif ui_key == "origin":
        return trip_inputs.get("origin")
    elif ui_key == "dates":
        start = trip_inputs.get("start_date")
        end = trip_inputs.get("end_date")
        if start and end:
            return f"{start} – {end}"
        elif start:
            return start
        return None
    elif ui_key == "budget":
        budget = trip_inputs.get("budget")
        currency = trip_inputs.get("currency", "USD")
        return f"{currency} {budget}" if budget else None
    elif ui_key == "travelers":
        adults = trip_inputs.get("adults")
        children = trip_inputs.get("children", 0)
        if adults:
            parts = [f"{adults} adult{'s' if adults != 1 else ''}"]
            if children:
                parts.append(f"{children} child{'ren' if children != 1 else ''}")
            return ", ".join(parts)
        return None
    elif ui_key == "flights":
        if trip_inputs.get("booking_types", {}).get("flights"):
            flight_settings = trip_inputs.get("flight_settings", {})
            parts = []
            if flight_settings.get("direct_only"):
                parts.append("Direct")
            cabin = flight_settings.get("cabin_class", "economy")
            if cabin != "economy":
                parts.append(cabin.title())
            return " · ".join(parts) if parts else "Enabled"
        return None
    elif ui_key == "hotels":
        if trip_inputs.get("booking_types", {}).get("hotels"):
            hotel_settings = trip_inputs.get("hotel_settings", {})
            stars = hotel_settings.get("min_stars", 0)
            return f"{stars}+ stars" if stars else "Enabled"
        return None
    # =========================================================================
    # Settings keys (dotted notation from NL command extraction)
    # =========================================================================
    elif ui_key == "booking_types.flights":
        toggle = trip_inputs.get("booking_types", {}).get("flights")
        return {"off": "Disabled", "suggested": "Auto", "on": "Enabled"}.get(toggle)
    elif ui_key == "booking_types.hotels":
        toggle = trip_inputs.get("booking_types", {}).get("hotels")
        return {"off": "Disabled", "suggested": "Auto", "on": "Enabled"}.get(toggle)
    elif ui_key == "booking_types.activities":
        toggle = trip_inputs.get("booking_types", {}).get("activities")
        return {"off": "Disabled", "suggested": "Auto", "on": "Enabled"}.get(toggle)
    elif ui_key == "booking_types.ground_transport":
        toggle = trip_inputs.get("booking_types", {}).get("ground_transport")
        return {"off": "Disabled", "suggested": "Auto", "on": "Enabled"}.get(toggle)
    elif ui_key == "flight_settings.direct_only":
        direct = trip_inputs.get("flight_settings", {}).get("direct_only")
        return "Direct flights only" if direct else "Connections OK"
    elif ui_key == "flight_settings.cabin_class":
        cabin = trip_inputs.get("flight_settings", {}).get("cabin_class")
        return cabin.replace("_", " ").title() if cabin else None
    elif ui_key == "flight_settings.round_trip":
        round_trip = trip_inputs.get("flight_settings", {}).get("round_trip")
        return "Round trip" if round_trip else "One way"
    elif ui_key == "hotel_settings.min_stars":
        stars = trip_inputs.get("hotel_settings", {}).get("min_stars")
        if stars is not None:
            return f"{stars}+ stars" if stars > 0 else "Any rating"
        return None
    elif ui_key == "activity_settings.skill_level":
        level = trip_inputs.get("activity_settings", {}).get("skill_level")
        return level.title() if level else None
    return None


def _conflicts_to_constraint_violations(
    conflicts: List[Any], resolutions: List[Any] | None = None
) -> List[Dict[str, Any]]:
    """Map itinerary conflicts to frontend Trip DNA-style violation objects."""
    mapped: List[Dict[str, Any]] = []
    suggested_action = None
    if resolutions:
        first_resolution = resolutions[0]
        suggested_action = (
            first_resolution.description if hasattr(first_resolution, "description") else None
        )

    for conflict in conflicts:
        severity = (
            conflict.severity.value
            if hasattr(conflict, "severity") and hasattr(conflict.severity, "value")
            else str(getattr(conflict, "severity", "warning")).lower()
        )
        mapped.append(
            {
                "code": str(getattr(conflict, "type", "itinerary_conflict")).upper(),
                "message": getattr(conflict, "message", "Itinerary conflict detected"),
                "severity": severity,
                "category": "itinerary",
                "rule": getattr(conflict, "type", "itinerary_conflict"),
                "suggested_action": suggested_action,
            }
        )
    return mapped


# ─────────────────────────────────────────────────────────────────────────────
# SSE Generator
# ─────────────────────────────────────────────────────────────────────────────


async def generate_sse(
    *,
    session_id: str,
    req: GraphPlanRequest,
    session_state: Dict[str, Any],
    request_id: str,
    today_iso: str,
    session_key: str,
    ip_key: str,
    request: Request,
    release_sse_slot: Callable[[str, str], Awaitable[None]],
    sanitize_trip_inputs_for_category_merge: Callable[[Dict[str, Any], str], Dict[str, Any]],
    merge_user_owned_trip_settings: Callable[..., None],
    resolve_itinerary_document_view_state: Callable[..., str],
) -> AsyncIterator[str]:
    """Generator that yields SSE events from the streaming graph execution.

    Extracted from graph_plan_stream_endpoint.  All previously-captured closure
    variables are now explicit keyword-only parameters.
    """
    session_factory = _get_async_session_factory()
    async with session_factory() as db:
        try:
            db_session = await get_or_create_session(db, session_id)

            # Get or create document
            document = None
            document_data = None
            document_version = None
            try:
                document = await get_or_create_document(db, session=db_session)
                document_data = get_document_data(document)
                document_version = document.version

                # Record user message with trip_inputs snapshot for undo functionality
                user_message_content = req.message
                trip_inputs_snapshot = None
                if document_data and document_data.trip_inputs:
                    ti = document_data.trip_inputs
                    trip_inputs_snapshot = {
                        "destination": ti.destination,
                        "origin": ti.origin,
                        "start_date": ti.start_date,
                        "end_date": ti.end_date,
                        "adults": ti.adults,
                        "children": ti.children,
                        "requires_assistance": ti.requires_assistance,
                        "budget": ti.budget,
                        "currency": ti.currency,
                        "booking_types": ti.booking_types.model_dump() if ti.booking_types else {},
                        "flight_settings": (
                            ti.flight_settings.model_dump() if ti.flight_settings else {}
                        ),
                        "hotel_settings": (
                            ti.hotel_settings.model_dump() if ti.hotel_settings else {}
                        ),
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
                    trip_context=None,
                    role="user",
                    content=user_message_content,
                    metadata=None,
                    trip_inputs_snapshot=trip_inputs_snapshot,
                )

                # Hydrate session state from document
                if document_data:
                    if document_data.branches:
                        session_state["branches"] = [b.model_dump() for b in document_data.branches]
                    # CRITICAL FIX: Always use document trip_inputs as BASELINE,
                    # then merge request on top. This ensures fields set via settings
                    # panel (origin, flight_settings, etc.) are preserved when the
                    # chat request only has partial trip_inputs.
                    # @see docs/plan_graph_analysis.md - Origin sync for flight fetching
                    if document_data.trip_inputs:
                        doc_inputs = document_data.trip_inputs.model_dump()
                        session_inputs = session_state.get("trip_inputs", {})
                        # User-owned settings fields — document is SSoT (set via PATCH
                        # from frontend sheets). Session may carry stale values from
                        # previous graph runs; document always wins for these.
                        _USER_OWNED_SETTINGS = {
                            "activity_settings",
                            "hotel_settings",
                            "flight_settings",
                            "transport_settings",
                            "booking_types",
                        }
                        # Document as baseline, session overrides for graph-owned fields only
                        merged = {**doc_inputs}
                        for k, v in session_inputs.items():
                            if v is not None and k not in _USER_OWNED_SETTINGS:
                                merged[k] = v
                        session_state["trip_inputs"] = normalize_trip_inputs(merged)

                        # req.trip_inputs is the freshest source for user-owned
                        # settings (Zustand snapshot at send time).  The document
                        # may be stale if ensureSettingsFlushed PATCH hasn't
                        # committed yet, or if get_or_create_document created a
                        # default doc with empty categories.
                        if req.trip_inputs:
                            req_ti = sanitize_trip_inputs_for_category_merge(
                                dict(req.trip_inputs),
                                req.message,
                            )
                            current = session_state["trip_inputs"]
                            merge_user_owned_trip_settings(
                                current,
                                req_ti,
                                user_owned_fields=_USER_OWNED_SETTINGS,
                            )
                            session_state["trip_inputs"] = normalize_trip_inputs(current)

                        # HARD TRACE: Log doc's activity categories at merge time
                        _doc_cats = doc_inputs.get("activity_settings", {}).get("categories", [])
                        _final_cats = (
                            session_state["trip_inputs"]
                            .get("activity_settings", {})
                            .get("categories", [])
                        )
                        logger.info(
                            f"[{request_id}] trip_inputs merge: "
                            f"doc.categories={_doc_cats}, "
                            f"final.categories={_final_cats}, "
                            f"doc.origin={doc_inputs.get('origin')}"
                        )
                    # Inject user-pinned tiles into metadata so graph state preserves them
                    if document_data.user_pinned_tiles:
                        if "metadata" not in session_state:
                            session_state["metadata"] = {}
                        session_state["metadata"]["user_pinned_tiles"] = (
                            document_data.user_pinned_tiles
                        )
            except Exception as e:
                logger.warning(f"[{request_id}] Failed to load document for session: {e}")

            # ── Pass document's user-owned settings to graph state ──
            # _restore_graph_state merges these into state.metadata["trip_inputs"],
            # ensuring the graph sees pill selections / settings panel values
            # even when the session carries stale trip_inputs from a prior turn.
            if document:
                try:
                    await db.refresh(document)
                    fresh_data = get_document_data(document)
                    if fresh_data.trip_inputs:
                        ti = fresh_data.trip_inputs
                        session_state["_doc_settings"] = {
                            "activity_settings": ti.activity_settings.model_dump()
                            if ti.activity_settings
                            else {},
                            "hotel_settings": ti.hotel_settings.model_dump()
                            if ti.hotel_settings
                            else {},
                            "flight_settings": ti.flight_settings.model_dump()
                            if ti.flight_settings
                            else {},
                            "transport_settings": ti.transport_settings.model_dump()
                            if ti.transport_settings
                            else {},
                            "booking_types": (
                                ti.booking_types.model_dump() if ti.booking_types else {}
                            ),
                        }
                        # Override _doc_settings with req.trip_inputs (most
                        # current source — Zustand snapshot at send time).
                        # Prevents stale/empty doc values from clobbering
                        # correct pill selections in state_serde.restore_graph_state.
                        if req.trip_inputs:
                            req_ti = sanitize_trip_inputs_for_category_merge(
                                dict(req.trip_inputs),
                                req.message,
                            )
                            merge_user_owned_trip_settings(
                                session_state["_doc_settings"],
                                req_ti,
                                user_owned_fields={
                                    "activity_settings",
                                    "hotel_settings",
                                    "flight_settings",
                                    "transport_settings",
                                    "booking_types",
                                },
                            )

                        # HARD TRACE: Log what we're injecting
                        _cats = (
                            session_state["_doc_settings"]
                            .get("activity_settings", {})
                            .get("categories", [])
                        )
                        logger.info(
                            f"[{request_id}] _doc_settings injected: "
                            f"activity_settings.categories={_cats}"
                        )
                    # ── Sync last_builder_success from document state ──
                    if fresh_data.plan_view_state == "S3_ITINERARY_READY":
                        session_state.setdefault("metadata", {})["last_builder_success"] = True
                except Exception as e:
                    logger.error(f"[{request_id}] _doc_settings injection FAILED: {e}")

            # --- Log user input for DEBUG=full mode ---
            log_user_input(req.message, request_id)

            # Inject session_id into metadata so Phase B (local_expert background
            # LLM enrichment) can write travel_intelligence back to the DB document.
            if session_state.get("metadata") is None:
                session_state["metadata"] = {}
            session_state["metadata"]["session_id"] = session_id
            if document_version is not None:
                session_state["metadata"]["document_version"] = int(document_version)

            # Stream tokens from run_turn_streaming with per-event timeout
            # Use route timeout for total stream duration protection
            route_timeout_seconds = settings.graph_plan_route_timeout_ms / 1000.0
            final_result = None
            token_count = 0
            stream_start = asyncio.get_event_loop().time()

            from app.planner.plan_graph import run_turn_streaming

            doc_settings = session_state.pop("_doc_settings", None)
            event_source = run_turn_streaming(
                user_message=req.message,
                session_state=session_state,
                doc_settings=doc_settings,
                session_id=session_id,
            )

            with spend_guard_scope(session_id):
                async for event in event_source:
                    # Check for client disconnect
                    if await request.is_disconnected():
                        logger.info(f"[{request_id}] Client disconnected, cancelling stream")
                        break

                    # Check if we've exceeded total stream timeout
                    elapsed = asyncio.get_event_loop().time() - stream_start
                    if elapsed > route_timeout_seconds:
                        logger.error(
                            f"[{request_id}] Stream timeout after {elapsed:.1f}s "
                            f"(limit: {route_timeout_seconds}s)"
                        )
                        timeout_payload = json.dumps(
                            {"type": "error", "message": f"Stream timed out after {elapsed:.1f}s"}
                        )
                        yield f"event: error\ndata: {timeout_payload}\n\n"
                        return

                    if event["type"] == "token":
                        token_count += 1
                        if token_count <= 5 or token_count % 50 == 0:
                            logger.debug(f"[{request_id}] Streaming token #{token_count}")
                        yield f"event: token\ndata: {json.dumps(event)}\n\n"
                    elif event["type"] == "node_status":
                        # Forward strategy node status for frontend progress tracking
                        node = event["data"].get("node")
                        status = event["data"].get("status")
                        logger.debug(f"[{request_id}] Node status: {node} - {status}")
                        yield f"event: node_status\ndata: {json.dumps(event)}\n\n"
                    elif event["type"] == "partial":
                        # Forward partial data events (v2 emits these from tool results)
                        yield f"event: partial\ndata: {json.dumps(event)}\n\n"
                    elif event["type"] == "complete":
                        logger.debug(f"[{request_id}] Stream complete after {token_count} tokens")
                        final_result = event["data"]
                    elif event["type"] == "error":
                        # Forward graph errors to frontend with actual message
                        error_msg = event.get("message", "Unknown graph error")
                        logger.error(f"[{request_id}] Graph error: {error_msg}")
                        error_payload = json.dumps({"type": "error", "message": error_msg})
                        yield f"event: error\ndata: {error_payload}\n\n"
                        return

            if final_result is None:
                error_payload = json.dumps({"type": "error", "message": "No result from graph"})
                yield f"event: error\ndata: {error_payload}\n\n"
                return

            # --- Process and persist final result ---
            assistant_message = final_result.get("assistant_message", "")
            if len(assistant_message) > settings.assistant_msg_max_len:
                try:
                    assistant_message = condense_long_message(
                        assistant_message,
                        settings.assistant_msg_max_len,
                    )
                except Exception as e:
                    logger.warning(f"[{request_id}] Condense failed: {e}")
                    assistant_message = truncate_assistant_message(assistant_message)

            suggested_responses = validate_suggested_responses(
                final_result.get("suggested_responses", [])
            )

            # --- Log LLM output for DEBUG=full mode ---
            log_llm_output(assistant_message, request_id)

            updated_session_state = final_result.get("session_state", session_state)
            branches = final_result.get("branches", [])
            trip_inputs = final_result.get(
                "trip_inputs", updated_session_state.get("trip_inputs", {})
            )
            ready_to_generate_now = final_result.get("ready_to_generate", False)
            changes_made = trip_inputs != session_state.get("trip_inputs", {})

            # Persist document
            new_document_version = document_version
            updated_at = datetime.now().isoformat()
            if document:
                try:
                    from app.schemas import DocumentBranch, DocumentTripInputs
                    from app.schemas import Tile as TileSchema

                    branch_objs = []
                    for b in branches:
                        if isinstance(b, dict):
                            branch_objs.append(DocumentBranch.model_validate(b))
                        else:
                            branch_objs.append(b)

                    trip_inputs_obj = None
                    if trip_inputs:
                        if isinstance(trip_inputs, dict):
                            trip_inputs_obj = DocumentTripInputs.model_validate(trip_inputs)
                        else:
                            trip_inputs_obj = trip_inputs

                    trip_context = await get_latest_trip_context_for_session(db, session=db_session)
                    trip_context_id = trip_context.id if trip_context else 0

                    # Extract viewModel fields from graph result for persistence
                    graph_doc = final_result.get("document", {})

                    # Extract tiles from graph document (NOT session_state.metadata!)
                    # Tiles are returned in final_result.document.tiles by _format_result
                    tiles_from_graph = graph_doc.get("tiles", {})
                    tiles_dict = {}
                    if tiles_from_graph:
                        for tile_id, tile_data in tiles_from_graph.items():
                            if isinstance(tile_data, dict):
                                tiles_dict[tile_id] = TileSchema.model_validate(tile_data)
                            elif isinstance(tile_data, TileSchema):
                                tiles_dict[tile_id] = tile_data
                    logger.info(f"[TILES] Persisting {len(tiles_dict)} tiles to DB")
                    graph_strategy_sections = graph_doc.get("strategy_sections", [])
                    strategy_section_objs = None
                    if graph_strategy_sections:
                        strategy_section_objs = [
                            StrategySection(**s) if isinstance(s, dict) else s
                            for s in graph_strategy_sections
                        ]

                    # Extract NL-extracted settings for deep-merge persistence
                    nl_extracted = updated_session_state.get("metadata", {}).get(
                        "extracted_settings"
                    )

                    # Convert graph-built day_cards for persistence
                    graph_day_cards_raw = graph_doc.get("itinerary_day_cards")
                    day_card_objs = None
                    persist_view_state = resolve_itinerary_document_view_state(
                        graph_doc.get("plan_view_state"),
                        graph_day_cards_raw,
                        graph_doc.get("constraint_violations", []),
                    )
                    if graph_day_cards_raw:
                        day_card_objs = [
                            DayCard(**dc) if isinstance(dc, dict) else dc
                            for dc in graph_day_cards_raw
                        ]
                    elif (
                        graph_doc.get("strategy_sections")
                        and document_data
                        and document_data.day_cards
                    ):
                        # Strategy changed but no new itinerary built — check for specialist coverage mismatch.
                        # If the strategy_sections no longer match the day_cards (specialist added or removed),
                        # clear stale cards by passing day_card_objs=[] (explicit empty vs None which is no-op).
                        _graph_strat_topics: set[str] = set()
                        for _s in graph_doc.get("strategy_sections", []):
                            _st = (
                                _s.get("specialist_type")
                                if isinstance(_s, dict)
                                else _s.specialist_type
                            )
                            if _st and _st not in ("local_expert", "general"):
                                _graph_strat_topics.add(_st)
                        _existing_dc_topics: set[str] = set()
                        for _dc in document_data.day_cards:
                            for _b in _dc.blocks:
                                if _b.specialist_type:
                                    _existing_dc_topics.add(_b.specialist_type)
                        # Only compare Tier 1 types (those present in strategy).
                        # Browse-inserted blocks (e.g. "cultural", "food") are not Tier 1
                        # and must not trigger stale detection.
                        _existing_dc_tier1 = _existing_dc_topics & _graph_strat_topics
                        if _existing_dc_tier1 != _graph_strat_topics:
                            _debug(
                                f"[streaming] Stale day_cards in DB: strategy={_graph_strat_topics}, "
                                f"day_cards={_existing_dc_topics} — clearing for DB persistence"
                            )
                            day_card_objs = []  # Explicit empty list clears DB; None would be a no-op

                    updated_doc = await apply_planner_update(
                        db,
                        doc=document,
                        trip_context_id=trip_context_id,
                        trip_inputs=trip_inputs_obj,
                        branches=branch_objs if branch_objs else None,
                        tiles=tiles_dict if tiles_dict else None,
                        # ViewModel fields for session restoration
                        plan_view_state=persist_view_state,
                        strategy_sections=strategy_section_objs,
                        executed_strategy_topics=graph_doc.get("executed_strategy_topics"),
                        pending_strategy_topics=graph_doc.get("pending_strategy_topics"),
                        day_cards=day_card_objs,
                        can_expand_to_itinerary=graph_doc.get("can_expand_to_itinerary"),
                        extracted_settings=nl_extracted,
                    )
                    if updated_doc:
                        new_document_version = updated_doc.version
                        document_data = get_document_data(updated_doc)

                    # Record assistant message
                    await record_chat_message(
                        db,
                        session=db_session,
                        trip_context=None,
                        role="assistant",
                        content=assistant_message,
                        metadata=None,
                    )

                    await db.commit()

                    # Phase B: fire local_expert LLM enrichment AFTER db.commit() so it
                    # can't be stomped by apply_planner_update, and runs outside the
                    # graph's asyncio.timeout() context so it isn't cancelled.
                    import time as _time

                    from app.planner.nodes.local_expert import (
                        _ENRICHMENT_TTL_SECONDS,
                        _pending_enrichments,
                        _pending_lock,
                        _persist_travel_intelligence,
                    )

                    async with _pending_lock:
                        _entry = _pending_enrichments.pop(session_id, None)
                    if _entry is not None:
                        _enrich_fn, _created_at = _entry
                        if _time.monotonic() - _created_at < _ENRICHMENT_TTL_SECONDS:
                            # Wrap in tracing_context(enabled=False) so this post-graph
                            # background LLM call doesn't create an orphan LangSmith trace.
                            from langsmith.run_helpers import tracing_context

                            async def _enrich_no_trace(fn=_enrich_fn):
                                with tracing_context(enabled=False):
                                    with spend_guard_scope(session_id):
                                        await fn()

                            _enrich_task = asyncio.create_task(_enrich_no_trace())
                            _track_bg_task(_enrich_task)
                            logger.debug("[SSE] Phase B: enrichment task fired")
                        else:
                            logger.warning(
                                "[SSE] Phase B: stale enrichment for %s",
                                session_id,
                            )
                            try:
                                await _persist_travel_intelligence(
                                    session_id,
                                    None,
                                    enrichment_state="failed",
                                    error_code="stale",
                                )
                            except Exception as _persist_err:
                                logger.warning(
                                    "[SSE] Phase B: failed to mark stale enrichment for %s: %s",
                                    session_id,
                                    _persist_err,
                                )
                except (SQLAlchemyError, ValueError) as e:
                    logger.error(f"[{request_id}] Failed to persist document: {e}")
                    await db.rollback()
                    # Clean up pending Phase B enrichment so the dict doesn't leak.
                    # Don't fire enrichment — the Phase A skeleton was not committed.
                    from app.planner.nodes.local_expert import (
                        _pending_enrichments as _pe_cleanup,
                    )
                    from app.planner.nodes.local_expert import (
                        _pending_lock as _pe_lock,
                    )

                    async with _pe_lock:
                        _pe_cleanup.pop(session_id, None)

            # Build response document
            response_document = document_data if document_data else PlanDocumentData()
            response_document.assistant_message = assistant_message
            response_document.suggested_responses = suggested_responses
            response_document.ready_to_generate = ready_to_generate_now

            # --- Set change tracking fields for UI receipts ---
            session_metadata = updated_session_state.get("metadata", {})
            response_document.applied_updates = session_metadata.get("turn_applied_fields", [])
            response_document.update_provenance = session_metadata.get("update_provenance")
            if response_document.applied_updates:
                response_document.undo_snapshot = session_metadata.get("prev_trip_inputs_snapshot")

            # --- Build detailed ack_updates for collapsible messages UI ---
            ack_updates = []
            for ui_key in response_document.applied_updates:
                value = _get_trip_input_display_value(ui_key, trip_inputs)
                if value:
                    ack_updates.append(AckUpdate(field=ui_key, to=value))
            response_document.ack_updates = ack_updates

            # --- Check for blocking route violations (Logic Guards) ---
            # Route errors (SAME_CITY_ERROR, UNKNOWN_DESTINATION_ERROR) trigger "rejected" status
            constraint_violations = session_metadata.get("constraint_violations", [])
            route_violation = next(
                (
                    v
                    for v in constraint_violations
                    if v.get("category") == "route" and v.get("severity") == "blocking"
                ),
                None,
            )

            # Set ack_status based on violations or applied updates
            if route_violation:
                # Logic Guard rejection - use amber UI pattern (DS Section 20)
                response_document.ack_status = "rejected"
                response_document.ack_updates = [
                    AckUpdate(field="route", to=route_violation.get("code", "INVALID_ROUTE"))
                ]
            elif ack_updates:
                response_document.ack_status = "applied"
            elif response_document.applied_updates:
                response_document.ack_status = "partial"
            else:
                response_document.ack_status = "no_change"

            # --- Compute Plan State Envelope fields ---
            # Get ui_phase from request (defaults to "bootstrap")
            response_document.ui_phase = req.ui_phase or "bootstrap"

            # Compute readiness from trip_inputs
            readiness = compute_trip_readiness(trip_inputs, errors=final_result.get("errors", []))

            # Build readiness array for frontend
            response_document.readiness = [
                ReadinessItem(key="origin", ok=readiness.has_origin),
                ReadinessItem(key="destination", ok=readiness.has_destination),
                ReadinessItem(key="start_date", ok=readiness.has_dates),
                ReadinessItem(key="end_date", ok=bool(trip_inputs.get("end_date"))),
                ReadinessItem(key="travelers", ok=trip_inputs.get("adults") is not None),
                ReadinessItem(key="budget", ok=trip_inputs.get("budget") is not None),
            ]

            # Compute plan_state from readiness
            if not readiness.core_complete:
                response_document.plan_state = "INCOMPLETE"
            else:
                response_document.plan_state = "STABLE"

            # Build destination_card if destination exists
            dest_name = trip_inputs.get("destination")
            if dest_name:
                # Non-blocking: check memory cache (populated by fire-and-forget prefetch),
                # fall back to deterministic Unsplash placeholder. Images are decorative.
                dest_image_url = get_image_url_sync(dest_name, variant=0, width=1600, height=900)
                response_document.destination_card = DestinationCard(
                    title=dest_name,
                    subtitle=f"Your adventure in {dest_name}" if dest_name else None,
                    image_url=dest_image_url,
                )

            # resolver is None at completion (was used during streaming)
            response_document.resolver = None

            # Build booking_status from tiles
            if response_document.tiles:
                flights_count = sum(
                    1 for t in response_document.tiles.values() if t.type == "flight"
                )
                hotels_count = sum(1 for t in response_document.tiles.values() if t.type == "hotel")
                activities_count = sum(
                    1 for t in response_document.tiles.values() if t.type == "activity"
                )
                response_document.booking_status = BookingStatus(
                    flights=BookingStatusItem(
                        state="ready" if flights_count > 0 else "idle",
                        summary=(
                            f"Flights · {flights_count} options"
                            if flights_count
                            else "Flights · not started"
                        ),
                    ),
                    stays=BookingStatusItem(
                        state="ready" if hotels_count > 0 else "idle",
                        summary=(
                            f"Stays · {hotels_count} options"
                            if hotels_count
                            else "Stays · not started"
                        ),
                    ),
                    activities=BookingStatusItem(
                        state="ready" if activities_count > 0 else "idle",
                        summary=(
                            f"Activities · {activities_count} options"
                            if activities_count
                            else "Activities · not started"
                        ),
                    ),
                )

            # --- Graph Output Processing ---
            # Graph generates strategy_sections, plan_view_state, and executed_topics
            graph_document = final_result.get("document", {})
            graph_strategy_sections = graph_document.get("strategy_sections", [])

            # Compute plan_view_state based on actual state (tiles/destination/dates)
            response_document.plan_view_state = graph_document.get(
                "plan_view_state", "S0_BOOTSTRAP"
            )

            # Apply strategy sections if present
            if graph_strategy_sections:
                response_document.strategy_sections = [
                    StrategySection(**section) if isinstance(section, dict) else section
                    for section in graph_strategy_sections
                ]
                response_document.executed_strategy_topics = graph_document.get(
                    "executed_strategy_topics", []
                )
                response_document.pending_strategy_topics = graph_document.get(
                    "pending_strategy_topics", []
                )
                response_document.needs_refresh = False
                response_document.can_expand_to_itinerary = True

            # Apply graph tiles if present - ALWAYS replace DB tiles with fresh graph tiles
            # FIX: Changed from `if graph_tiles and not response_document.tiles` to `if graph_tiles`
            # This ensures destination changes get fresh tiles instead of keeping old DB tiles
            graph_tiles = graph_document.get("tiles", {})
            if graph_tiles:
                response_document.tiles = {
                    tile_id: (
                        Tile.model_validate(tile_data) if isinstance(tile_data, dict) else tile_data
                    )
                    for tile_id, tile_data in graph_tiles.items()
                }

            # Copy origin_just_set flag for frontend flight fetch trigger
            response_document.origin_just_set = graph_document.get("origin_just_set", False)
            # Copy tiles_replaced flag — frontend should REPLACE tiles, not merge additively
            response_document.tiles_replaced = graph_document.get("tiles_replaced", False)
            # Copy browseable_activities (Tier 1 suppressed tiles stashed by logistics_node)
            browseable = graph_document.get("browseable_activities")
            if browseable:
                response_document.browseable_activities = browseable

            # Copy itinerary day cards if builder ran during graph execution
            graph_day_cards = graph_document.get("itinerary_day_cards")
            if graph_day_cards:
                response_document.day_cards = [
                    DayCard.model_validate(dc) if isinstance(dc, dict) else dc
                    for dc in graph_day_cards
                ]
                response_document.plan_view_state = resolve_itinerary_document_view_state(
                    response_document.plan_view_state,
                    graph_day_cards,
                    graph_document.get("constraint_violations", []),
                )
            elif graph_strategy_sections and response_document.day_cards:
                # Strategy changed but no new itinerary built — check specialist coverage mismatch.
                # Covers both additive (cycling added) and subtractive (cycling removed) changes.
                # Clearing stale cards forces the frontend expand gate to fire expand-itinerary.
                _resp_strat_topics = {
                    s.specialist_type
                    for s in response_document.strategy_sections
                    if s.specialist_type and s.specialist_type not in ("local_expert", "general")
                }
                _resp_dc_topics: set[str] = set()
                for _dc in response_document.day_cards:
                    for _b in _dc.blocks:
                        if _b.specialist_type:
                            _resp_dc_topics.add(_b.specialist_type)
                # Only compare Tier 1 types (those present in strategy).
                # Browse-inserted blocks (e.g. "cultural", "food") are not Tier 1
                # and must not trigger stale detection.
                _resp_dc_tier1 = _resp_dc_topics & _resp_strat_topics
                if _resp_dc_tier1 != _resp_strat_topics:
                    _debug(
                        f"[streaming] Stale day_cards in SSE response: strategy={_resp_strat_topics}, "
                        f"day_cards={_resp_dc_topics} — clearing to trigger expand-itinerary"
                    )
                    response_document.day_cards = []
                    # Downgrade view state so frontend expand gate recognizes strategy-only state
                    response_document.plan_view_state = "S2_STRATEGY_READY"

            # Copy suggestions from graph document (unfiltered by validator)
            # The validator strips question marks but synthesizer chips are curated
            graph_suggestions = graph_document.get("suggested_responses")
            if graph_suggestions and not response_document.suggested_responses:
                response_document.suggested_responses = graph_suggestions

            # Copy suggestion chip metadata (progression hints etc)
            graph_chip_meta = graph_document.get("suggested_response_meta")
            if graph_chip_meta:
                response_document.suggested_response_meta = graph_chip_meta

            # Copy constraint validation state
            graph_constraints = graph_document.get("constraints_validated")
            if graph_constraints:
                response_document.constraints_validated = graph_constraints
            graph_violations = graph_document.get("constraint_violations")
            if graph_violations:
                response_document.constraint_violations = graph_violations

            _debug(
                f"[MAIN.PY] Graph output: plan_view_state={response_document.plan_view_state}, "
                f"strategy_sections={len(response_document.strategy_sections or [])}, "
                f"tiles={len(response_document.tiles or {})}, "
                f"day_cards={len(response_document.day_cards or [])}"
            )

            # Build full response matching GraphPlanResponse
            full_response = {
                "document": (
                    response_document.model_dump()
                    if hasattr(response_document, "model_dump")
                    else response_document
                ),
                "session_state": updated_session_state,
                "version": new_document_version or 1,
                "updated_by": "planner",
                "updated_at": updated_at,
                "changes_made": changes_made,
                "request_id": request_id,
                "observability": {
                    "tokens": {"prompt": 0, "completion": 0, "total": 0},
                    "today_iso": today_iso,
                    "ready_to_generate_now": ready_to_generate_now,
                },
            }

            # DEBUG: Verify strategy_sections in full_response before sending
            doc_in_response = full_response.get("document", {})
            strategy_sections = doc_in_response.get("strategy_sections", [])
            first_id = strategy_sections[0].get("id") if strategy_sections else "none"
            _debug(
                f"[MAIN.PY] SSE complete payload: "
                f"strategy_sections_count={len(strategy_sections)}, "
                f"plan_view_state={doc_in_response.get('plan_view_state')}, "
                f"first_section_id={first_id}"
            )

            complete_payload = json.dumps(
                {"type": "complete", "data": full_response},
                default=str,
            )
            yield f"event: complete\ndata: {complete_payload}\n\n"

        except (asyncio.CancelledError, GeneratorExit):
            logger.debug("[SSE] Client disconnected, cleaning up")
        except TimeoutError:
            logger.error(f"[{request_id}] run_turn_streaming timed out")
            timeout_payload = json.dumps({"type": "error", "message": "Request timed out"})
            yield f"event: error\ndata: {timeout_payload}\n\n"
        except Exception as e:
            logger.error(f"[{request_id}] run_turn_streaming failed: {e}")
            error_payload = json.dumps({"type": "error", "message": str(e)})
            yield f"event: error\ndata: {error_payload}\n\n"
        finally:
            await release_sse_slot(session_key, ip_key)


# ─────────────────────────────────────────────────────────────────────────────
# NDJSON Generator
# ─────────────────────────────────────────────────────────────────────────────


async def generate_ndjson(
    *,
    session_id: str,
    req: ExpandItineraryRequest,
    resolve_stage3_view_state: Callable[..., PlanViewState],
) -> AsyncIterator[str]:
    """Generator that yields NDJSON events for itinerary generation.

    Extracted from expand_itinerary_endpoint.  All previously-captured closure
    variables are now explicit keyword-only parameters.
    """
    # Create fresh database session for this generator
    # (Cannot use FastAPI's injected session - it's closed by the time we run)
    session_factory = _get_async_session_factory()
    async with session_factory() as db:
        try:
            session = await get_session_by_token(db, session_id)
            if not session:
                event = ExpandItineraryStreamEvent(type="error", message="Session not found")
                yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                return

            doc = await get_document(db, session=session)
            if not doc:
                event = ExpandItineraryStreamEvent(type="error", message="No plan document found")
                yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                return

            doc_data = get_document_data(doc)
            _debug("✅ [expand-itinerary] Session & doc found")

            # Emit progress: starting
            event = ExpandItineraryStreamEvent(
                type="progress",
                stage="itinerary",
                message="Generating itinerary...",
                pct=10,
            )
            yield json.dumps(event.model_dump(exclude_none=True)) + "\n"

            # Use frontend-provided context if available, else fall back to database
            # This ensures we have the latest strategy_sections from the client
            trip_inputs_data = (
                req.trip_inputs
                if req.trip_inputs
                else (doc_data.trip_inputs.model_dump() if doc_data.trip_inputs else {})
            )
            strategy_sections_data = (
                req.strategy_sections
                if req.strategy_sections
                else (
                    [s.model_dump() for s in doc_data.strategy_sections]
                    if doc_data.strategy_sections
                    else []
                )
            )

            # Guard: Require at least one strategy section
            # (no specialists = nothing to schedule)
            if not strategy_sections_data:
                _debug("❌ [expand-itinerary] EARLY RETURN: No strategy sections")
                event = ExpandItineraryStreamEvent(
                    type="error",
                    message=json.dumps(
                        {
                            "error": "NO_STRATEGY",
                            "message": "Ask about activities before generating itinerary",
                        }
                    ),
                )
                yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                return

            # =================================================================
            # SELECTIVE REGENERATION: Detect strategy based on changed fields
            # =================================================================
            # Compute previous field hashes from document's stored trip_inputs
            # (field_hashes are computed from trip_inputs, not stored separately)
            prev_trip_inputs = doc_data.trip_inputs.model_dump() if doc_data.trip_inputs else {}
            previous_preferences = {
                "preferred_tile_ids": _normalized_preference_ids(doc_data.preferred_tile_ids or [])
            }
            previous_hashes = compute_field_hashes(prev_trip_inputs, previous_preferences)

            # Compute current field hashes from request trip_inputs
            current_preferences = _flatten_request_preferences(req.preferences)
            current_hashes = compute_field_hashes(trip_inputs_data, current_preferences)

            # Detect which fields changed
            changed_fields = detect_changed_fields(previous_hashes, current_hashes)

            # Compute the regeneration strategy
            regen_strategy = compute_strategy(changed_fields)

            # Force full rebuild if frontend signals structural change (new specialist)
            if req.force_full_rebuild:
                _debug("⚡ [expand-itinerary] force_full_rebuild=True - bypassing selective regen")
                regen_strategy = RegenStrategy.FULL

            _debug(
                f"🔄 [expand-itinerary] Selective Regen: "
                f"strategy={regen_strategy.value}, changed={changed_fields}"
            )

            # For BUILDER strategy, we're already doing the right thing (ItineraryBuilder only)
            # For LOGISTICS/SPECIALISTS/FULL, the frontend would need to trigger graph execution
            # Currently this endpoint only handles BUILDER - log warning for other strategies
            if regen_strategy != RegenStrategy.BUILDER:
                _debug(
                    f"⚠️ [expand-itinerary] {get_strategy_description(regen_strategy)} "
                    f"- fields changed: {changed_fields}. "
                    f"Note: This endpoint only rebuilds itinerary; "
                    f"tiles/specialists use cached values from last graph run."
                )

            # Tile source selection — gated on force_full_rebuild.
            # force_full_rebuild=True  → auto-expand after chat. Frontend tiles
            #   may be stale (mergeEnvelope adds but never removes). Session
            #   tiles are authoritative (written by apply_planner_update before SSE).
            # force_full_rebuild=False → preference regen / manual rebuild.
            #   Frontend tiles are authoritative (include hearted tiles, filters).
            if req.force_full_rebuild:
                tiles_data = (
                    {
                        tid: t.model_dump() if hasattr(t, "model_dump") else t
                        for tid, t in doc_data.tiles.items()
                    }
                    if doc_data.tiles
                    else {}
                )
                _debug(
                    f"📊 [expand-itinerary] Using DB tiles ({len(tiles_data)}) "
                    f"[force_full_rebuild=True, frontend sent "
                    f"{len(req.tiles) if req.tiles else 0}]"
                )
            else:
                if req.tiles and len(req.tiles) > 0:
                    tiles_data = req.tiles
                    _debug(f"📊 [expand-itinerary] Using frontend tiles ({len(tiles_data)})")
                else:
                    tiles_data = (
                        {
                            tid: t.model_dump() if hasattr(t, "model_dump") else t
                            for tid, t in doc_data.tiles.items()
                        }
                        if doc_data.tiles
                        else {}
                    )
                    _debug(
                        f"📊 [expand-itinerary] Using DB tiles ({len(tiles_data)}) "
                        f"— no frontend tiles provided"
                    )

            tiles_count = len(tiles_data)
            _debug(
                f"📊 [expand-itinerary] Input data: "
                f"strategy_sections={len(strategy_sections_data)}, "
                f"destination={trip_inputs_data.get('destination')}, tiles={tiles_count}"
            )
            # Log content_added counts for each section
            for i, section in enumerate(strategy_sections_data):
                content_count = len(section.get("content_added", []))
                spec_type = section.get("specialist_type")
                _debug(
                    f"📦 [expand-itinerary] Section {i}: {spec_type} content_added={content_count}"
                )
            # Log first section keys for debugging schema issues
            if strategy_sections_data:
                first_section_keys = list(strategy_sections_data[0].keys())
                _debug(f"📊 [expand-itinerary] First section keys: {first_section_keys}")

            # NOTE: session_state used to be built here for planner graph
            # but is no longer needed as we build itinerary directly.
            # See CRITICAL comment below for context that was preserved.

            # Emit progress: processing
            event = ExpandItineraryStreamEvent(
                type="progress",
                stage="itinerary",
                message="Building day cards...",
                pct=30,
            )
            yield json.dumps(event.model_dump(exclude_none=True)) + "\n"

            # Build itinerary using pure Python service (NOT LLM)
            # This is faster and more predictable than run_turn()
            from app.services.itinerary_builder import (
                ItineraryBuilder,
                ItineraryBuilderInput,
                PreferenceOverrideInput,
            )

            # Convert API preferences to builder input format
            preferences_input = None
            if req.preferences:
                hotel_ids = req.preferences.preferred_hotel_ids or []
                activity_ids = req.preferences.preferred_activity_ids or []
                flight_ids = req.preferences.preferred_flight_ids or []
                _debug(
                    f"🎯 [expand-itinerary] Preferences received: "
                    f"hotels={len(hotel_ids)}, activities={len(activity_ids)}, "
                    f"flights={len(flight_ids)}"
                )
                _debug(f"🎯 [expand-itinerary] Hotel IDs: {hotel_ids}")
                _debug(f"🎯 [expand-itinerary] Activity IDs: {activity_ids}")
                _debug(f"🎯 [expand-itinerary] Flight IDs: {flight_ids}")
                preferences_input = PreferenceOverrideInput(
                    preferred_hotel_ids=hotel_ids,
                    preferred_activity_ids=activity_ids,
                    preferred_flight_ids=flight_ids,
                )
            else:
                _debug("🎯 [expand-itinerary] No preferences in request")

            # Validate dates - require both start and end for multi-day trips
            start_date = trip_inputs_data.get("start_date")
            end_date = trip_inputs_data.get("end_date")

            # Guard: Require both dates (S0_BOOTSTRAP has neither)
            if not start_date or not end_date:
                _debug(
                    f"❌ [expand-itinerary] EARLY RETURN: Missing dates "
                    f"(start={start_date}, end={end_date})"
                )
                event = ExpandItineraryStreamEvent(
                    type="error",
                    message=json.dumps(
                        {
                            "error": "MISSING_DATES",
                            "message": "Set travel dates to generate itinerary",
                        }
                    ),
                )
                yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                return

            # Guard: Minimum 2-day trip (generates hotel booking, enables constraints)
            if start_date and end_date:
                from datetime import datetime as dt

                try:
                    start_dt = dt.fromisoformat(start_date.split("T")[0])
                    end_dt = dt.fromisoformat(end_date.split("T")[0])
                    trip_days = (end_dt - start_dt).days + 1
                    if trip_days < 2:
                        _debug(
                            f"❌ [expand-itinerary] EARLY RETURN: Trip too short: {trip_days} days"
                        )
                        event = ExpandItineraryStreamEvent(
                            type="error",
                            message=json.dumps(
                                {
                                    "error": "TRIP_TOO_SHORT",
                                    "message": "Trip must be at least 2 days",
                                    "current_days": trip_days,
                                    "minimum_days": 2,
                                }
                            ),
                        )
                        yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                        return
                except (ValueError, AttributeError) as e:
                    logger.warning(f"❌ [expand-itinerary] Date parsing error: {e}")

            _debug(
                f"🔥 [expand-itinerary] BUILDER CALLED: "
                f"start={start_date}, end={end_date}, "
                f"sections={len(strategy_sections_data)}, tiles={tiles_count}"
            )

            builder = ItineraryBuilder()
            booking_types = trip_inputs_data.get("booking_types", {})
            activities_off = booking_types.get("activities") == "off"
            raw_categories = trip_inputs_data.get("activity_settings", {}).get("categories")
            # When activities are explicitly disabled, pass empty list so the builder
            # treats it as "user cleared all categories" (set() → skip all tiles).
            # When activities are enabled but categories is empty/None, pass None
            # so the builder applies no category filter (place all activities).
            if activities_off:
                activity_categories: list[str] | None = []
            elif raw_categories:
                activity_categories = raw_categories
            else:
                activity_categories = None
            day_preferences = trip_inputs_data.get("activity_settings", {}).get("day_preferences")
            builder_input = ItineraryBuilderInput(
                start_date=start_date,
                end_date=end_date,
                strategy_sections=strategy_sections_data,
                tiles=tiles_data,
                destination=trip_inputs_data.get("destination"),
                origin=trip_inputs_data.get("origin"),
                preferences=preferences_input,
                activity_categories=activity_categories,
                activity_day_preferences=day_preferences,
                user_pinned_tiles=doc_data.user_pinned_tiles if doc_data else None,
            )

            try:
                itinerary_result = builder.build(builder_input)
                _debug(
                    f"✅ [expand-itinerary] Builder result: "
                    f"success={itinerary_result.success}, "
                    f"day_cards={len(itinerary_result.day_cards)}, "
                    f"conflicts={len(itinerary_result.conflicts)}"
                )
                for _c in itinerary_result.conflicts:
                    _debug(
                        f"  ⚠️ Conflict: type={_c.type}, "
                        f"severity={_c.severity}, day={_c.day}, "
                        f"msg={_c.message}"
                    )
            except Exception as e:
                logger.exception(f"Itinerary builder failed: {e}")
                event = ExpandItineraryStreamEvent(
                    type="error", message=f"Itinerary generation failed: {str(e)}"
                )
                yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                return

            # Handle failed builds with conflicts - return partial schedule + conflict error
            if not itinerary_result.success:
                if itinerary_result.conflicts:
                    failure_view_state = resolve_stage3_view_state(
                        itinerary_result.success, itinerary_result.conflicts
                    )
                    logger.info(
                        "[expand-itinerary-state] builder_success=%s conflict_count=%s "
                        "emitted_plan_view_state=%s changed_fields=%s",
                        itinerary_result.success,
                        len(itinerary_result.conflicts or []),
                        failure_view_state,
                        sorted(changed_fields),
                    )
                    # NEW: Include partial day_cards in conflict response
                    # Partial schedule shows what CAN be scheduled + unschedulable markers
                    partial_day_cards = (
                        [dc.model_dump() for dc in itinerary_result.day_cards]
                        if itinerary_result.day_cards
                        else []
                    )
                    _debug(
                        f"⚠️ [expand-itinerary] Conflict with partial schedule: "
                        f"conflicts={len(itinerary_result.conflicts)}, "
                        f"partial_day_cards={len(partial_day_cards)}"
                    )

                    # Emit partial schedule envelope FIRST (so frontend can render it)
                    if partial_day_cards:
                        partial_envelope = {
                            "day_cards": partial_day_cards,
                            "plan_view_state": failure_view_state,
                        }
                        partial_event = ExpandItineraryStreamEvent(
                            type="envelope",
                            plan_envelope=partial_envelope,
                        )
                        yield json.dumps(partial_event.model_dump(exclude_none=True)) + "\n"

                    # Emit conflict response for frontend to handle
                    conflict_data = {
                        "error": "CONSTRAINT_CONFLICT",
                        "conflicts": [c.model_dump() for c in itinerary_result.conflicts],
                        "resolutions": [r.model_dump() for r in itinerary_result.resolutions],
                        "day_cards": partial_day_cards,  # Include in conflict data too
                    }
                    event = ExpandItineraryStreamEvent(
                        type="error",
                        message=json.dumps(conflict_data),
                    )
                    yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                    return
                else:
                    event = ExpandItineraryStreamEvent(
                        type="error",
                        message=itinerary_result.error or "Itinerary generation failed",
                    )
                    yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
                    return

            # Emit progress: finalizing
            event = ExpandItineraryStreamEvent(
                type="progress",
                stage="itinerary",
                message="Finalizing itinerary...",
                pct=80,
            )
            yield json.dumps(event.model_dump(exclude_none=True)) + "\n"

            # Build metadata from itinerary result.
            # strategy_stage=3 remains required for Stage 3 rendering semantics.
            metadata = {
                "strategy_stage": 3,  # Force stage 3 for proper state computation
                "day_cards": [dc.model_dump() for dc in itinerary_result.day_cards],
                "itinerary_overview": (
                    itinerary_result.overview.model_dump() if itinerary_result.overview else None
                ),
                "strategy_sections": strategy_sections_data,
            }
            trip_inputs = trip_inputs_data

            # Build envelope update
            plan_envelope = {}

            # Add itinerary fields if present
            if "day_cards" in metadata:
                plan_envelope["day_cards"] = metadata["day_cards"]
            if "itinerary_overview" in metadata:
                plan_envelope["itinerary_overview"] = metadata["itinerary_overview"]
            if "itinerary_assumptions" in metadata:
                plan_envelope["itinerary_assumptions"] = metadata["itinerary_assumptions"]

            new_plan_view_state: PlanViewState = resolve_stage3_view_state(
                itinerary_result.success, itinerary_result.conflicts
            )
            logger.info(
                "[expand-itinerary-state] builder_success=%s conflict_count=%s "
                "emitted_plan_view_state=%s changed_fields=%s",
                itinerary_result.success,
                len(itinerary_result.conflicts or []),
                new_plan_view_state,
                sorted(changed_fields),
            )
            plan_envelope["plan_view_state"] = new_plan_view_state
            if itinerary_result.conflicts:
                plan_envelope["constraint_violations"] = _conflicts_to_constraint_violations(
                    itinerary_result.conflicts, itinerary_result.resolutions
                )

            # Emit envelope update
            _debug(
                f"📤 [expand-itinerary] Emitting envelope: "
                f"day_cards={len(plan_envelope.get('day_cards', []))}, "
                f"plan_view_state={new_plan_view_state}"
            )
            event = ExpandItineraryStreamEvent(
                type="envelope",
                plan_envelope=plan_envelope,
            )
            yield json.dumps(event.model_dump(exclude_none=True)) + "\n"

            # Always persist plan_view_state; only include day_cards when present
            try:
                from app.schemas import DocumentTripInputs

                # Convert trip_inputs to DocumentTripInputs
                trip_inputs_obj = None
                if trip_inputs:
                    trip_inputs_obj = DocumentTripInputs.model_validate(trip_inputs)

                # Get trip context
                trip_context = await get_latest_trip_context_for_session(db, session=session)
                trip_context_id = trip_context.id if trip_context else 0

                # Convert day_cards to DayCard objects for persistence (only when present)
                day_card_objs = None
                if plan_envelope.get("day_cards"):
                    from app.schemas import DayCard as DayCardSchema

                    day_card_objs = [
                        DayCardSchema(**dc) if isinstance(dc, dict) else dc
                        for dc in plan_envelope["day_cards"]
                    ]

                await apply_planner_update(
                    db,
                    doc=doc,
                    trip_context_id=trip_context_id,
                    trip_inputs=trip_inputs_obj,
                    # ViewModel fields for session restoration — always persist state
                    plan_view_state=new_plan_view_state,
                    day_cards=day_card_objs,
                    can_expand_to_itinerary=day_card_objs is not None,
                )
                await db.commit()
            except (SQLAlchemyError, ValueError) as e:
                logger.warning(f"Failed to persist itinerary: {e}")
                await db.rollback()

            # Emit done with version for frontend sync (prevents 409 on next PATCH)
            event = ExpandItineraryStreamEvent(
                type="done",
                plan_view_state=new_plan_view_state,
                version=doc.version if doc else None,
                dropped_preferred_count=itinerary_result.dropped_preferred_count or None,
                warnings=itinerary_result.warnings if itinerary_result.warnings else None,
            )
            yield json.dumps(event.model_dump(exclude_none=True)) + "\n"

        except (asyncio.CancelledError, GeneratorExit):
            logger.debug("[NDJSON] Client disconnected, cleaning up")
        except Exception as e:
            logger.exception(f"Error in expand-itinerary: {e}")
            event = ExpandItineraryStreamEvent(
                type="error", message=str(e) or "Failed to generate itinerary"
            )
            yield json.dumps(event.model_dump(exclude_none=True)) + "\n"
        finally:
            logger.debug("[NDJSON] Generator exiting for session=%s", session_id)
