"""
Lightweight turn-execution helper for the create_agent planner.

Wraps agent invocation with state serialization/deserialization so callers
only deal with plain dicts (suitable for DB persistence).  Used by tests
and will later be called from the streaming layer.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict, Optional

from langchain_core.messages import AIMessageChunk, HumanMessage, ToolMessage

from app.planner.agent import create_planner_agent

logger = logging.getLogger(__name__)

# Module-level cached agent (created once, reused across calls)
_cached_agent = None

# Max HumanMessages per session before the turn cap fires (runaway-session guard).
SESSION_MAX_TURNS = 40

# Hard ceiling (seconds) on the synchronous post-build enrichment pass. Enrichment makes
# external Places/partner calls; on timeout we proceed with whatever enriched in-place so a
# slow provider can never stall the turn's `complete` envelope.
ENRICHMENT_TIMEOUT_S = 6.0


# ---------------------------------------------------------------------------
# SSE translation constants
# ---------------------------------------------------------------------------

# Tool name -> frontend node_status `node` string. Identity for all six tools
# (these names match the strings the frontend keys progress UI on); the final
# model turn maps to "response".
_TOOL_TO_NODE: Dict[str, str] = {
    "extract_trip_fields": "extract_trip_fields",
    "get_specialist_advice": "get_specialist_advice",
    "search_tiles": "search_tiles",
    "get_local_intel": "get_local_intel",
    "validate_plan": "validate_plan",
    "build_itinerary": "build_itinerary",
}

# Per-node label / icon / estimated duration for the progress UI.
_NODE_META: Dict[str, tuple[str, str, int]] = {
    "extract_trip_fields": ("Reading your trip details", "search", 800),
    "get_specialist_advice": ("Planning specialist activities", "compass", 4000),
    "search_tiles": ("Finding flights, stays & activities", "search", 3000),
    "get_local_intel": ("Gathering local intel", "map-pin", 2500),
    "validate_plan": ("Checking feasibility", "shield-check", 800),
    "build_itinerary": ("Building your itinerary", "calendar", 3000),
    "response": ("Writing your plan", "message-square", 800),
}


def _should_autobuild(state: Dict[str, Any]) -> bool:
    """Whether to deterministically build the itinerary after the agent loop.

    Gemini Flash reliably returns empty after ~4 tool rounds in one turn, so it
    cannot dependably chain extract -> parallel-fetch -> build -> reply itself.
    The driver builds on its behalf once the plan is ready: destination + dates
    + fetched options are present, nothing is built yet, and this turn actually
    progressed the plan (a fetch ran, or core fields changed) -- so a pure
    question on an already-set-up trip does not trigger a build.
    """
    tp = state.get("trip_plan", {})
    if state.get("day_cards"):
        return False  # already built (rebuilds are the agent's job via the prompt)
    if not (tp.get("destination") and tp.get("start_date") and tp.get("end_date")):
        return False
    tiles = state.get("tiles") or {}
    has_options = bool(state.get("strategy_sections")) or any(
        tiles.get(k) for k in ("hotels", "activities", "flights")
    )
    if not has_options:
        return False
    tm = state.get("turn_meta", {})
    tools = set(tm.get("tools_called") or [])
    fields = set(tm.get("fields_changed") or [])
    return bool(tools & {"search_tiles", "get_specialist_advice"}) or bool(
        fields & {"destination", "start_date", "end_date", "duration_days"}
    )


def _prune_stale_sections(state: Dict[str, Any]) -> None:
    """Drop stale specialist sections AND, on explicit removal turns, the matching
    activity tiles / day_cards / specialist_plans for the active trip.

    The strategy_sections reducer is additive (dedup-by-type, right-wins, NO remove
    branch) and an empty/shortened-list delta from a merger is therefore INERT -- so
    removals must be applied here by DIRECT mutation on final_state. Two cases:
      (a) PREVIOUS destination -- a section whose destination stamp ("subtitle", set by
          build_specialist_section) != the current destination (e.g. Bali content left
          over after Bali -> Cozumel).
      (b) EXPLICIT removal/swap -- a section whose specialist_type the user asked to drop
          this turn (turn_meta.removal_targets, e.g. "switch from diving to hiking" ->
          remove diving). removal_targets is a per-turn signal (turn_meta is reset each
          turn), so unlike trip_plan.specialist_hints it is NOT clobbered by parallel
          multi-specialist rounds.

    On an EXPLICIT removal turn (removal_targets non-empty) we ALSO prune the activity
    tiles + specialist_plans for the removed topics and WHOLESALE clear day_cards --
    otherwise the section disappears but the tiles + day_cards survive and the frontend
    re-displays the removed specialist. This mirrors the doc_settings category-change
    cleanup in coordinator.py (which also does `day_cards = []` rather than surgically
    editing blocks), but is SCOPED to removal_targets (that block nukes ALL activities by
    design). We clear day_cards wholesale rather than surgically dropping the removed
    specialist's blocks: the builder co-locates arrival/departure buffers onto the
    first/last cards, so block-level pruning silently deleted whole arrival/departure days
    (and their inbound-flight booked_tiles) and left gapped day numbers. Tiles are pruned
    FIRST, so the frontend re-expands from the surviving tiles + dates, regrouping only the
    surviving specialists and reconstructing the buffers -- nothing is lost and day numbers
    stay contiguous.

    We deliberately do NOT prune sections by trip_plan.specialist_hints: it's a shallow
    sub-key of trip_plan, clobbered when two get_specialist_advice calls run in one parallel
    round -- pruning by it wrongly dropped the OTHER specialist's fresh section (the
    multi-specialist "add hiking to my diving trip" bug).
    """
    sections = state.get("strategy_sections") or []
    current_dest = (
        (state.get("trip_plan", {}).get("destination") or "").strip().lower().split(",")[0].strip()
    )
    removal_targets = {
        str(t).strip().lower()
        for t in (state.get("turn_meta", {}).get("removal_targets") or [])
        if str(t).strip()
    }
    if not sections and not removal_targets:
        return

    # (1) Section prune -- runs whenever there are sections to evaluate.
    if sections and (current_dest or removal_targets):
        kept = []
        for s in sections:
            if isinstance(s, dict):
                stype = str(s.get("specialist_type", "")).strip().lower()
                if stype and stype in removal_targets:
                    continue  # explicitly removed / swapped out this turn
                sec_dest = (s.get("subtitle") or "").strip().lower().split(",")[0].strip()
                if current_dest and sec_dest and sec_dest != current_dest:
                    continue  # stale destination -- drop (prev-destination content)
            kept.append(s)
        if len(kept) != len(sections):
            state["strategy_sections"] = kept

    # (2) Full removal cleanup -- prune activity tiles, day_cards, and specialist_plans for
    # the removed topics. Runs even when the section list was empty (a no-op section prune
    # must NOT short-circuit the tile/day_card cleanup).
    if not removal_targets:
        return

    pruned = False

    tiles = state.get("tiles")
    if isinstance(tiles, dict):
        activity_tiles = tiles.get("activities")
        if isinstance(activity_tiles, list):
            kept_tiles = []
            for tile in activity_tiles:
                meta = tile.get("meta", {}) if isinstance(tile, dict) else {}
                stype = str(meta.get("specialist_type", "")).strip().lower()
                cat = str(meta.get("category", "")).strip().lower()
                if (stype and stype in removal_targets) or (cat and cat in removal_targets):
                    pruned = True
                    continue
                kept_tiles.append(tile)
            if len(kept_tiles) != len(activity_tiles):
                tiles["activities"] = kept_tiles
                state["tiles"] = tiles

    specialist_plans = state.get("specialist_plans")
    if isinstance(specialist_plans, dict):
        for key in list(specialist_plans.keys()):
            if str(key).strip().lower() in removal_targets:
                specialist_plans.pop(key, None)
                pruned = True

    if pruned:
        # WHOLESALE clear of day_cards (mirrors coordinator.py's doc_settings
        # category-change path, which does `state["day_cards"] = []` rather than
        # surgically editing blocks). Surgical block-pruning silently dropped whole
        # cards: the builder co-locates arrival/departure buffers onto the first/last
        # cards and a removed specialist's activity can share those cards, so dropping
        # the activity then dropping the now-buffer-only card deleted the arrival/
        # departure day and its inbound-flight booked_tile/logistics_details, and left
        # gapped day numbers. Tiles are pruned ABOVE before this clear, so the frontend
        # re-expands from the surviving tiles + dates -- regrouping only the surviving
        # specialists and reconstructing the arrival/departure buffers -- with no data
        # loss and contiguous day numbers. This unifies with the all-removed case
        # (which also ends at day_cards=[]).
        state["day_cards"] = []
        turn_meta = state.get("turn_meta")
        if not isinstance(turn_meta, dict):
            turn_meta = {}
        turn_meta["tiles_replaced"] = True
        turn_meta["removal_pruned"] = True
        state["turn_meta"] = turn_meta


def _trim_conversation_history(messages: list, keep_turns: int = 12) -> list:
    """Keep only conversational turns; drop prior tool-call noise.

    Gemini returns empty AIMessages on later turns when the history carries the
    accumulated tool_call AIMessages + ToolMessages from earlier turns. Because
    NomadicAgentState already holds the trip data (trip_plan/tiles/sections/
    day_cards) and the current state is re-shown each turn via CURRENT CONTEXT,
    the message history only needs the human/assistant text turns. We therefore
    drop every ToolMessage and every AIMessage that carries tool_calls, keeping
    HumanMessages and final assistant text replies. Dropping both halves of each
    call/response pair keeps the history valid (no orphaned function_call).
    """
    kept: list = []
    for msg in messages or []:
        kind = type(msg).__name__
        if kind == "ToolMessage":
            continue
        if kind in ("AIMessage", "AIMessageChunk"):
            if getattr(msg, "tool_calls", None):
                continue  # intermediate tool-calling turn -- drop
            if not (isinstance(getattr(msg, "content", None), str) and msg.content.strip()):
                continue  # empty assistant message -- drop
        kept.append(msg)
    return kept[-keep_turns:]


def _node_status_event(node: str, status: str) -> Dict[str, Any]:
    """Build a node_status SSE event matching the coordinator's shape."""
    label, icon, duration = _NODE_META.get(node, (node, "circle", 500))
    return {
        "type": "node_status",
        "data": {
            "node": node,
            "status": status,
            "label": label,
            "icon_key": icon,
            "estimated_duration_ms": duration,
        },
    }


def _classify_error(exc: Exception) -> str:
    """Classify an exception into the envelope's response_error_type buckets."""
    text = f"{type(exc).__name__} {exc}".lower()
    if "rate" in text or "quota" in text or "429" in text:
        return "rate_limit"
    if "timeout" in text or isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "timeout"
    return "generation_error"


def _feasibility_warning_from_toolmsg(msg: ToolMessage) -> Optional[Dict[str, Any]]:
    """Surface a feasibility_warning when get_specialist_advice flags infeasible."""
    if getattr(msg, "name", None) != "get_specialist_advice":
        return None
    content = msg.content
    if not content or not isinstance(content, str):
        return None
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    if str(parsed.get("feasibility_status", "")).lower() != "infeasible":
        return None
    return {
        "type": "feasibility_warning",
        "data": {
            "topic": parsed.get("topic", ""),
            "status": "infeasible",
            "reason": parsed.get("feasibility_reason", ""),
            "alternative": parsed.get("alternative", ""),
        },
    }


def _get_agent():
    """Lazily create and cache the planner agent."""
    global _cached_agent  # noqa: PLW0603
    if _cached_agent is None:
        _cached_agent = create_planner_agent()
    return _cached_agent


async def run_agent_turn_streaming(
    user_message: str,
    state: Dict[str, Any],
    session_id: str,
    doc_settings: Optional[Dict[str, Any]] = None,
    cancel_event: Optional[asyncio.Event] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Drive the create_agent planner and yield the legacy SSE event contract.

    Drop-in replacement for ``coordinator.execute_turn``: yields the same
    ``{"type": ..., "data": ...}`` dicts (node_status / partial / token /
    feasibility_warning / complete / error) so ``streaming.generate_sse`` stays
    unchanged downstream.

    A single ``agent.astream`` multiplexes four modes:
      - ``updates``  -> node_status started (AIMessage.tool_calls) + completed (ToolMessage)
      - ``custom``   -> partial (tools push {kind, payload} via get_stream_writer)
      - ``messages`` -> token, on the terminal (no-tool-call) model turn only
      - ``values``   -> retained as the final NomadicAgentState for the envelope
    """
    # Import here to avoid importing the coordinator at module load (and to keep
    # the dependency one-directional during the coexistence window).
    from app.planner.coordinator import _build_envelope, _merge_doc_settings

    agent = _get_agent()

    if doc_settings:
        try:
            _merge_doc_settings(state, doc_settings)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[run_agent_turn_streaming] doc_settings merge failed: %s", exc)

    # Guard empty/blank turns: a HumanMessage with empty content is stripped by
    # the Gemini client, leaving no contents -> "contents are required" error.
    # Return a minimal envelope asking for detail instead of invoking the model.
    if not (user_message or "").strip():
        envelope = _build_envelope(
            state,
            user_message,
            session_id,
            "Could you tell me a bit more about your trip -- where and when you'd like to go?",
        )
        yield {"type": "complete", "data": envelope}
        return

    # Session turn cap: prevent runaway sessions (mirrors the cap the removed
    # coordinator DAG enforced). Count prior HumanMessages; at the limit, return
    # a cap notice instead of invoking the model.
    _human_turns = sum(1 for m in state.get("messages", []) if type(m).__name__ == "HumanMessage")
    if _human_turns >= SESSION_MAX_TURNS:
        envelope = _build_envelope(
            state,
            user_message,
            session_id,
            "We've covered a lot in this session. Start a new trip to keep planning.",
        )
        yield {"type": "complete", "data": envelope}
        return

    # Translate the machine "Build" signal into an explicit instruction the
    # orchestrator reliably acts on -- Flash does not treat the raw token as a
    # build trigger, so a literal "GENERATE_PLAN_NOW" otherwise just gets a
    # conversational reply with no build_itinerary call.
    effective_message = user_message
    if user_message.strip().upper().startswith("GENERATE_PLAN_NOW"):
        effective_message = (
            "Build my complete day-by-day itinerary now using the stays and activities we have "
            "already gathered. If flights, hotels, or activities are not loaded yet, fetch them "
            "first with search_tiles, then call build_itinerary."
        )

    # Trim prior-turn tool noise before this turn (Gemini empties out otherwise).
    state["messages"] = _trim_conversation_history(state.get("messages", [])) + [
        HumanMessage(content=effective_message)
    ]

    config: Dict[str, Any] = {}
    if session_id:
        config["configurable"] = {"thread_id": session_id}

    # Holder so the degraded/except path can see the latest state snapshot even
    # if the stream raises mid-flight.
    holder: Dict[str, Any] = {"last_values": None}

    async def _drive():
        """Drive one agent.astream pass: yield SSE events, then a final
        ('__result__', {assistant, any_tool}) sentinel. Updates holder."""
        parts: list[str] = []
        response_started = False
        any_tool = False
        async for mode, payload in agent.astream(
            state, config=config, stream_mode=["values", "updates", "messages", "custom"]
        ):
            if cancel_event is not None and cancel_event.is_set():
                break
            if mode == "values":
                if isinstance(payload, dict):
                    holder["last_values"] = payload
            elif mode == "updates":
                for node_update in (payload or {}).values():
                    if not isinstance(node_update, dict):
                        continue
                    for msg in node_update.get("messages", []) or []:
                        tool_calls = getattr(msg, "tool_calls", None)
                        if tool_calls:
                            for tc in tool_calls:
                                node = _TOOL_TO_NODE.get(tc.get("name"))
                                if node:
                                    any_tool = True
                                    yield _node_status_event(node, "started")
                        elif isinstance(msg, ToolMessage):
                            node = _TOOL_TO_NODE.get(getattr(msg, "name", None))
                            if node:
                                yield _node_status_event(node, "completed")
                            warning = _feasibility_warning_from_toolmsg(msg)
                            if warning:
                                yield warning
            elif mode == "custom":
                if isinstance(payload, dict) and payload.get("kind"):
                    yield {"type": "partial", "data": payload}
            elif mode == "messages":
                chunk, _meta = payload if isinstance(payload, tuple) else (payload, {})
                content = getattr(chunk, "content", None)
                tool_chunks = getattr(chunk, "tool_call_chunks", None)
                if (
                    isinstance(chunk, AIMessageChunk)
                    and isinstance(content, str)
                    and content
                    and not tool_chunks
                ):
                    if not response_started and any_tool:
                        response_started = True
                        yield _node_status_event("response", "started")
                    parts.append(content)
                    yield {"type": "token", "data": content}
        if response_started:
            yield _node_status_event("response", "completed")
        yield ("__result__", {"assistant": "".join(parts), "any_tool": any_tool})

    try:
        result: Dict[str, Any] = {"assistant": "", "any_tool": False}
        async for item in _drive():
            if isinstance(item, tuple) and len(item) == 2 and item[0] == "__result__":
                result = item[1]
            else:
                yield item

        # Retry once if a substantive turn produced NO tools and NO reply --
        # Gemini Flash intermittently returns an empty first response. A
        # failed-empty attempt emits zero SSE events, so the retry cannot
        # duplicate anything the client already saw.
        if (
            not result["any_tool"]
            and not result["assistant"].strip()
            and len((user_message or "").strip()) > 4
            and not (cancel_event is not None and cancel_event.is_set())
        ):
            logger.warning("[run_agent_turn_streaming] empty turn -- retrying once")
            async for item in _drive():
                if isinstance(item, tuple) and len(item) == 2 and item[0] == "__result__":
                    result = item[1]
                else:
                    yield item

        last_values = holder["last_values"]
        assistant_message = result["assistant"].strip() or (
            "I'm working on your trip plan. Let me know if you'd like to adjust anything."
        )
        final_state = last_values if isinstance(last_values, dict) else state

        # Whether the itinerary was (re)built THIS turn. Only then does it need
        # re-enrichment -- a pure-question turn on an existing trip reuses already-enriched
        # day_cards, so we must NOT re-run the (paid) enrichment pass on it. Seeded from a
        # direct LLM build_itinerary call; set below when the deterministic auto-build fires.
        built_this_turn = "build_itinerary" in (
            final_state.get("turn_meta", {}).get("tools_called") or []
        )

        # Deterministic auto-build: the LLM can't reliably chain a 4th tool round
        # (Gemini empties out), so build here once the plan is ready.
        if _should_autobuild(final_state):
            yield _node_status_event("build_itinerary", "started")
            try:
                from app.planner.middleware import _merge_itinerary
                from app.planner.tools.build_itinerary import build_itinerary as _build_tool

                build_result = await _build_tool.coroutine(state=final_state)
                if isinstance(build_result, dict) and build_result.get("day_cards"):
                    build_updates = _merge_itinerary(final_state, build_result)
                    final_state["day_cards"] = build_updates.get("day_cards")
                    merged_meta = dict(final_state.get("turn_meta", {}))
                    merged_meta.update(build_updates.get("turn_meta", {}))
                    final_state["turn_meta"] = merged_meta
                    built_this_turn = True
            except Exception as build_exc:
                logger.warning("[run_agent_turn_streaming] auto-build failed: %s", build_exc)
            yield _node_status_event("build_itinerary", "completed")

        # Post-build enrichment (synchronous, before the envelope). The old DAG ran this as a
        # deferred task; the agent path lost the caller. It partner-enriches (Viator/GYG) the
        # PLACED day-card blocks and propagates partner geo -> block.coordinates ({lat,lng}),
        # which is what the map plots; Google Places stays a fallback-only step for blocks with
        # no partner data (cost-minimized per product intent). Runs ONLY on turns that rebuilt
        # the itinerary (built_this_turn) so a pure-question turn never re-pays enrichment.
        # Cancel-aware + timeout-bounded: returns as soon as enrichment finishes, and on a
        # client disconnect or the hard ceiling we cancel the in-flight task (no wasted partner
        # API spend) -- partial enrichment survives because the pipeline mutates in place.
        if built_this_turn and final_state.get("day_cards"):
            try:
                from app.planner.coordinator import _run_itinerary_enrichment_pipeline

                enrich_task = asyncio.ensure_future(
                    _run_itinerary_enrichment_pipeline(
                        trip_plan=final_state.get("trip_plan", {}),
                        activity_tiles=(final_state.get("tiles") or {}).get("activities", []),
                        day_cards=final_state.get("day_cards", []),
                        session_id=session_id,
                    )
                )
                waiters: set = {enrich_task}
                cancel_task = None
                if cancel_event is not None:
                    cancel_task = asyncio.ensure_future(cancel_event.wait())
                    waiters.add(cancel_task)
                _done, _pending = await asyncio.wait(
                    waiters, timeout=ENRICHMENT_TIMEOUT_S, return_when=asyncio.FIRST_COMPLETED
                )
                # Stop whatever lost the race (cancel_event waiter, or enrichment on timeout/
                # disconnect) and await the cancellation so it can't mutate state concurrently
                # with envelope construction below.
                for _t in _pending:
                    _t.cancel()
                if _pending:
                    await asyncio.gather(*_pending, return_exceptions=True)
                # Consume the result only on clean completion; partial in-place enrichment is
                # already reflected in final_state["day_cards"] either way.
                if enrich_task in _done and not enrich_task.cancelled():
                    enrich_result = enrich_task.result()  # re-raises a pipeline error
                    if isinstance(enrich_result, dict):
                        final_state.setdefault("tiles", {})["activities"] = enrich_result.get(
                            "activities", (final_state.get("tiles") or {}).get("activities", [])
                        )
                        final_state["day_cards"] = enrich_result.get(
                            "day_cards", final_state["day_cards"]
                        )
            except Exception as enrich_exc:  # incl. asyncio.TimeoutError
                logger.warning(
                    "[run_agent_turn_streaming] post-build enrichment skipped: %s", enrich_exc
                )

        _prune_stale_sections(final_state)
        envelope = _build_envelope(final_state, user_message, session_id, assistant_message)
        yield {"type": "complete", "data": envelope}

    except Exception as exc:
        logger.error("[run_agent_turn_streaming] turn failed: %s", exc, exc_info=True)
        # Degraded path: if tools already ran, still emit a (degraded) envelope
        # so the frontend keeps the work instead of nuking the turn.
        degraded_state = holder.get("last_values")
        if isinstance(degraded_state, dict):
            turn_meta = dict(degraded_state.get("turn_meta", {}))
            turn_meta["response_degraded"] = True
            turn_meta["response_error_type"] = _classify_error(exc)
            degraded_state["turn_meta"] = turn_meta
            try:
                envelope = _build_envelope(
                    degraded_state,
                    user_message,
                    session_id,
                    "I hit a snag finishing that -- here's what I have so far.",
                )
                yield {"type": "complete", "data": envelope}
                return
            except Exception as build_exc:  # pragma: no cover - defensive
                logger.error("[run_agent_turn_streaming] degraded envelope failed: %s", build_exc)
        yield {"type": "error", "message": str(exc)}
