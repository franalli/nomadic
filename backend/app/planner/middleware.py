"""
Middleware suite for the create_agent-based planner.

Contains three middleware classes that plug into the LangChain AgentMiddleware
protocol.  Applied in order:

1. ModelSelectionMiddleware  -- upgrades model for complex planning turns
2. DynamicPromptMiddleware   -- injects per-turn system prompt from state
3. TurnLifecycleMiddleware   -- resets turn_meta; merges tool results into state

All middleware use the immutable ``override()`` pattern on requests and return
state updates via ``Command`` or ``ExtendedModelResponse`` where needed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ExtendedModelResponse,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.types import Command

from app.config import settings
from app.planner.agent_constants import AGENT_MAX_TOKENS, AGENT_TEMPERATURE
from app.planner.llm_factory import get_llm_by_model
from app.planner.prompts.planner import build_turn_context

logger = logging.getLogger(__name__)

# Threshold: upgrade model when this many tool calls in a single turn
_TOOL_CALL_UPGRADE_THRESHOLD = 3


# ===========================================================================
# 1. ModelSelectionMiddleware
# ===========================================================================


class ModelSelectionMiddleware(AgentMiddleware):
    """Dynamically upgrades the LLM for complex planning turns.

    Default behaviour: pass through the model configured via ``create_agent``.
    Upgrades to ``settings.synthesizer_planning_model`` (default:
    gemini-2.5-flash) when:

    - First full planning response (``plan_view_state == "S0_BOOTSTRAP"`` AND
      more than 4 messages in history), OR
    - High tool-call density in the current turn (3+ tool calls).

    The upgrade is constructed via ``get_llm_by_model()`` to preserve LLM
    factory compliance.  A per-instance cache avoids re-constructing the model
    on every call within the same turn.
    """

    def __init__(self) -> None:
        self._upgraded_model: BaseChatModel | None = None

    def _should_upgrade(self, state: dict[str, Any], messages: list) -> bool:
        """Decide whether to use the stronger planning model."""
        persistent_meta: dict[str, Any] = (
            state.get("persistent_meta", {}) if isinstance(state, dict) else {}
        )
        turn_meta: dict[str, Any] = state.get("turn_meta", {}) if isinstance(state, dict) else {}

        plan_view_state = persistent_meta.get("plan_view_state", "")
        is_bootstrap = plan_view_state == "S0_BOOTSTRAP"

        # Condition 1: first planning response with enough context
        if is_bootstrap and len(messages) > 4:
            return True

        # Condition 2: many tool calls in this turn
        tool_call_count = turn_meta.get("tool_call_count", 0)
        if tool_call_count >= _TOOL_CALL_UPGRADE_THRESHOLD:
            return True

        return False

    def _get_upgraded_model(self) -> BaseChatModel:
        """Lazily construct and cache the upgraded model."""
        if self._upgraded_model is None:
            self._upgraded_model = get_llm_by_model(
                settings.synthesizer_planning_model,
                temperature=AGENT_TEMPERATURE,
                max_tokens=AGENT_MAX_TOKENS,
            )
        return self._upgraded_model

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable,
    ) -> ModelResponse | AIMessage | ExtendedModelResponse:
        state_dict: dict[str, Any] = {}
        if request.state is not None:
            if isinstance(request.state, dict):
                state_dict = request.state
            elif hasattr(request.state, "get"):
                state_dict = dict(request.state)

        if self._should_upgrade(state_dict, request.messages):
            upgraded = self._get_upgraded_model()
            logger.debug(
                "[ModelSelectionMiddleware] Upgrading to %s (messages=%d, tool_calls=%d)",
                settings.synthesizer_planning_model,
                len(request.messages),
                state_dict.get("turn_meta", {}).get("tool_call_count", 0),
            )
            updated_request = request.override(model=upgraded)
            return await handler(updated_request)

        return await handler(request)


# ===========================================================================
# 2. DynamicPromptMiddleware
# ===========================================================================


class DynamicPromptMiddleware(AgentMiddleware):
    """Injects the per-turn CURRENT CONTEXT as a TRAILING message.

    The stable orchestrator instructions live in the agent's ``system_message``
    (set once at construction -- a cache-eligible prefix). This middleware does
    NOT rewrite that prefix. Instead, on every model call it reads
    ``request.state`` for the live trip state + grounding and appends a single
    trailing context message, so volatile data never pollutes the cached prefix
    (preserving Gemini's implicit-cache discount across loop rounds).
    """

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable,
    ) -> ModelResponse | AIMessage | ExtendedModelResponse:
        state_dict: dict[str, Any] = {}
        if request.state is not None:
            if hasattr(request.state, "get"):
                state_dict = dict(request.state)
            elif isinstance(request.state, dict):
                state_dict = request.state

        context = build_turn_context(state_dict)
        context_msg = SystemMessage(content=context)

        # Append as a trailing message; leave system_message (the cached prefix)
        # untouched.
        updated_request = request.override(
            messages=[*request.messages, context_msg],
        )

        return await handler(updated_request)


# ===========================================================================
# 3. TurnLifecycleMiddleware
# ===========================================================================


def _extract_tool_result(tool_message: ToolMessage) -> dict[str, Any] | None:
    """Parse the JSON content of a ToolMessage into a dict.

    Returns None if content is not parseable JSON.
    """
    content = tool_message.content
    if not content or not isinstance(content, str):
        return None
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
        return None
    except (json.JSONDecodeError, TypeError):
        return None


def _summarize_local_intel_for_model(parsed: dict[str, Any] | None) -> str:
    """Concise, MODEL-FACING summary of a get_local_intel result.

    The tool returns a verbose Phase-A skeleton whose only chat-relevant content is
    the generic travel-info floor (visa / insurance / passport copies / embassy /
    currency) -- the real neighborhood/transfer detail is enriched ASYNCHRONOUSLY
    (Phase B) into the plan panel and never reaches the model in-turn. Handing the
    raw skeleton to the model made it re-list that robotic checklist in chat. The
    full result is already merged into state for the plan panel by the caller, so we
    replace only what the MODEL reads with a short note that names no boilerplate.
    Any genuine (non-``generic_fallback``) constraint is preserved so it is not lost.
    """
    parsed = parsed or {}
    payload: dict[str, Any] = {
        "destination": parsed.get("destination") or "",
        "status": "local intel ready",
        "note": (
            "Local tips, neighborhoods, transfers and timing are saved to the plan panel for "
            "the traveler. Do not reproduce a travel-tips checklist in your chat reply."
        ),
    }
    real_constraints = [
        label
        for c in (parsed.get("constraints") or [])
        if isinstance(c, dict)
        and not c.get("generic_fallback")
        and (label := (c.get("label") or c.get("rule")))
    ]
    if real_constraints:
        payload["safety_constraints"] = real_constraints
    return json.dumps(payload)


def _normalize_trip_settings(raw_settings: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy flat trip_settings keys into nested settings dicts."""
    trip_settings = dict(raw_settings)

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


def _merge_trip_fields(state: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Merge extract_trip_fields result into the trip_plan dict.

    Only non-None fields from the extraction result are applied.
    Returns the updated trip_plan dict (does not mutate in place).

    When the destination changes, clears stale strategy_sections, tiles,
    and day_cards that belonged to the previous destination.
    """
    trip_plan = dict(state.get("trip_plan", {}))

    # Only apply fields that the extraction pipeline flagged as changed.
    # This prevents Pydantic default values (e.g. hotel_amenities=[]) from
    # overwriting existing state when the user didn't mention them.
    changed = set(result.get("fields_changed", []))

    # Detect destination change -- if the user switches destination, all
    # strategy_sections, tiles, day_cards, and constraints from the old
    # destination are stale and must be cleared.
    _destination_changed = False
    if "destination" in changed:
        old_dest = trip_plan.get("destination", "")
        new_dest = result.get("destination", "")
        if old_dest and new_dest and old_dest.lower().strip() != new_dest.lower().strip():
            _destination_changed = True

    # Origin transitioning empty -> set triggers flight auto-upgrade downstream.
    old_origin = (trip_plan.get("origin") or "").strip()
    _origin_just_set = (
        "origin" in changed and not old_origin and bool((result.get("origin") or "").strip())
    )

    # Direct field mappings from TripFieldsResult to trip_plan
    field_map = [
        "destination",
        "origin",
        "origin_iata",
        "destination_iata",
        "start_date",
        "end_date",
        "duration_days",
        "adults",
        "children",
        "budget",
    ]
    for field in field_map:
        if field in changed:
            value = result.get(field)
            if value is not None:
                trip_plan[field] = value

    # Mirror duration_days -> trip_duration (the envelope/trip_inputs field) so a
    # date-less duration ("weekend getaway" -> 3 days) surfaces in trip_duration.
    if "duration_days" in changed and result.get("duration_days") is not None:
        trip_plan["trip_duration"] = result.get("duration_days")

    # Derive end_date from start_date + duration when the traveler gave a
    # duration but no explicit end ("a week starting March 15"). The router
    # extracts start + duration_days but not the end; compute it so date-window
    # consumers (logistics, builder, curl checks) have a concrete end.
    _start = trip_plan.get("start_date")
    _dur = trip_plan.get("duration_days")
    _end_derived = False
    if _start and _dur and not trip_plan.get("end_date"):
        try:
            from datetime import datetime, timedelta

            _start_dt = datetime.strptime(str(_start), "%Y-%m-%d")
            trip_plan["end_date"] = (_start_dt + timedelta(days=int(_dur))).strftime("%Y-%m-%d")
            _end_derived = True
        except (ValueError, TypeError):
            pass

    # Reconcile trip_duration from an EXPLICIT date range so a stale duration from
    # an earlier turn ("10 days") can't outlive a later explicit range ("Jul 1-7")
    # and feed a wrong flight return-date (logistics uses trip_duration-1) or a
    # wrong "N days" trip summary. Guards:
    #  - skip when end_date was just DERIVED from duration this turn (else the
    #    inclusive recompute would fight the duration the traveler actually gave);
    #  - skip flexible / date-window trips, where start/end can encode a search
    #    WINDOW wider than the nominal trip length.
    _ts_in = state.get("trip_settings", {}) or {}
    _is_flex = bool(_ts_in.get("date_flex")) or bool(_ts_in.get("date_window_start"))
    _end_final = trip_plan.get("end_date")
    if _start and _end_final and not _end_derived and not _is_flex:
        try:
            from datetime import datetime

            _s = datetime.strptime(str(_start)[:10], "%Y-%m-%d")
            _e = datetime.strptime(str(_end_final)[:10], "%Y-%m-%d")
            if _e >= _s:
                trip_plan["trip_duration"] = (_e - _s).days + 1
        except (ValueError, TypeError):
            pass

    # Category removals are case-insensitive.
    removal_targets = {
        str(v).strip().lower() for v in (result.get("removal_targets", []) or []) if str(v).strip()
    }

    # Merge activity categories (additive + explicit removals)
    if "activity_categories" in changed or "removal_targets" in changed:
        existing_categories = {
            str(v).strip().lower()
            for v in (trip_plan.get("activity_categories", []) or [])
            if str(v).strip()
        }
        if "activity_categories" in changed:
            for cat in result.get("activity_categories", []) or []:
                normalized = str(cat).strip().lower()
                if normalized:
                    existing_categories.add(normalized)
        if removal_targets:
            existing_categories = {cat for cat in existing_categories if cat not in removal_targets}
        trip_plan["activity_categories"] = sorted(existing_categories)

    # Specialist hints
    if "specialist_hints" in changed or "removal_targets" in changed:
        existing_hints = {
            str(v).strip().lower()
            for v in (trip_plan.get("specialist_hints", []) or [])
            if str(v).strip()
        }
        if "specialist_hints" in changed:
            for hint in result.get("specialist_hints", []) or []:
                normalized = str(hint).strip().lower()
                if normalized:
                    existing_hints.add(normalized)
        if removal_targets:
            existing_hints = {hint for hint in existing_hints if hint not in removal_targets}
        trip_plan["specialist_hints"] = sorted(existing_hints)

        # Specialist topics ARE activity categories from the traveler's point of
        # view (and the frontend treats them as such). Fold the hints into
        # activity_categories so "diving"/"hiking" appear there too, honoring
        # removals.
        merged_categories = {
            str(v).strip().lower()
            for v in (trip_plan.get("activity_categories", []) or [])
            if str(v).strip()
        }
        merged_categories |= existing_hints
        if removal_targets:
            merged_categories = {c for c in merged_categories if c not in removal_targets}
        trip_plan["activity_categories"] = sorted(merged_categories)

    # Settings fields must persist in nested settings objects.
    trip_settings = _normalize_trip_settings(dict(state.get("trip_settings", {})))
    flight_settings = trip_settings.get("flight_settings", {})
    flight_settings = dict(flight_settings) if isinstance(flight_settings, dict) else {}
    hotel_settings = trip_settings.get("hotel_settings", {})
    hotel_settings = dict(hotel_settings) if isinstance(hotel_settings, dict) else {}
    activity_settings = trip_settings.get("activity_settings", {})
    activity_settings = dict(activity_settings) if isinstance(activity_settings, dict) else {}

    # Keep activity categories mirrored in trip_settings for trip_inputs envelopes.
    if "activity_categories" in trip_plan:
        activity_settings["categories"] = list(trip_plan.get("activity_categories", []))

    if "skill_level" in changed:
        value = result.get("skill_level")
        if value is not None:
            activity_settings["skill_level"] = value
    if "hotel_min_stars" in changed:
        value = result.get("hotel_min_stars")
        if value is not None:
            hotel_settings["min_stars"] = value
    if "hotel_style" in changed:
        value = result.get("hotel_style")
        if value is not None:
            hotel_settings["style"] = value
    if "hotel_amenities" in changed:
        value = result.get("hotel_amenities")
        if value is not None:
            hotel_settings["amenities"] = value
    if "hotel_location" in changed:
        value = result.get("hotel_location")
        if value is not None:
            hotel_settings["location"] = value
    if "flight_direct_only" in changed:
        value = result.get("flight_direct_only")
        if value is not None:
            flight_settings["direct_only"] = bool(value)
    if "flight_cabin_class" in changed:
        value = result.get("flight_cabin_class")
        if value is not None:
            flight_settings["cabin_class"] = value

    # Explicit reset intents must clear stale constraints.
    if "reset_budget" in changed and result.get("reset_budget"):
        trip_plan["budget"] = None
    if "reset_hotel" in changed and result.get("reset_hotel"):
        hotel_settings["min_stars"] = 0
        hotel_settings["amenities"] = []
        hotel_settings.pop("style", None)
        hotel_settings.pop("location", None)

    if flight_settings:
        trip_settings["flight_settings"] = flight_settings
    if hotel_settings:
        trip_settings["hotel_settings"] = hotel_settings
    if activity_settings:
        trip_settings["activity_settings"] = activity_settings

    # Setting an origin makes flights relevant -- enable the flights booking
    # type (parity with the coordinator's origin -> flight auto-upgrade) so the
    # envelope surfaces flights instead of leaving them "off".
    if _origin_just_set:
        booking_types = dict(trip_settings.get("booking_types") or {})
        if booking_types.get("flights") in (None, "", "off"):
            booking_types["flights"] = "suggested"
        trip_settings["booking_types"] = booking_types

    # Un-stick activities: a prior "remove all activities" turn set
    # booking_types.activities="off" (and that is sticky). When the traveler now
    # asks for ANY activity again -- a new category/specialist hint -- re-enable
    # activities so the next fetch/backfill runs and the envelope stops hiding
    # them. Gated on the activity interest set being non-empty AND this turn
    # actually adding interest (a remove-all turn never reaches here: it carries
    # no activity_categories/specialist_hints, so those keys aren't in `changed`).
    if ("activity_categories" in changed or "specialist_hints" in changed) and (
        trip_plan.get("activity_categories") or trip_plan.get("specialist_hints")
    ):
        booking_types = dict(trip_settings.get("booking_types") or {})
        if booking_types.get("activities") == "off":
            booking_types["activities"] = "suggested"
            trip_settings["booking_types"] = booking_types
            logger.info(
                "[_merge_trip_fields] Re-enabled activities (was off) -- traveler "
                "requested activity interest again"
            )

    updates: dict[str, Any] = {"trip_plan": trip_plan, "trip_settings": trip_settings}

    # Field producers consumed by the envelope builder (applied_updates / ack
    # status / flight auto-upgrade). turn_meta carries ONLY this delta -- the
    # reducer is right-wins for these keys; never copy the full turn_meta here.
    updates["turn_meta"] = {
        "fields_changed": sorted(changed),
        "origin_just_set": _origin_just_set,
        # Explicit removals/swaps this turn. The strategy_sections reducer is additive (no remove
        # branch), so the filtered-list delta below is inert -- _prune_stale_sections consumes this
        # post-graph and drops the section by direct mutation on final_state.
        "removal_targets": sorted(removal_targets),
        # Global "remove ALL activities" intent. The in-loop model may re-plan
        # (re-run a specialist), so this clear is ENFORCED post-loop in
        # agent_runner._apply_remove_all_activities (turn_meta scalar keys are
        # right-wins, so this flag survives to final_state). Also read by
        # DynamicPromptMiddleware to shape the terminal reply.
        "remove_all_activities": bool(result.get("remove_all_activities")),
    }

    # When destination changed, clear stale data from the previous destination.
    if _destination_changed:
        updates["strategy_sections"] = []
        updates["tiles"] = {}
        updates["day_cards"] = []
        updates["constraints"] = []
        # Interests from the old destination ("diving in Bali") do not carry to
        # the new one -- keep only what THIS turn re-specified.
        fresh_cats = {
            str(c).strip().lower()
            for c in (result.get("activity_categories") or [])
            if str(c).strip()
        }
        fresh_hints = {
            str(h).strip().lower() for h in (result.get("specialist_hints") or []) if str(h).strip()
        }
        trip_plan["specialist_hints"] = sorted(fresh_hints)
        trip_plan["activity_categories"] = sorted(fresh_cats | fresh_hints)
        # Mirror the cleared categories into trip_settings.activity_settings so
        # the envelope's activity_settings.categories also drops stale interests
        # (it was mirrored from the OLD categories earlier in this function).
        ts_activity = dict(trip_settings.get("activity_settings") or {})
        ts_activity["categories"] = sorted(fresh_cats | fresh_hints)
        trip_settings["activity_settings"] = ts_activity
        logger.info(
            "[_merge_trip_fields] Destination changed -- cleared stale strategy_sections, "
            "tiles, day_cards, constraints, and prior-destination interests",
        )
    elif removal_targets:
        # Activity swap/removal (e.g. "switch from diving to hiking"): drop the
        # strategy section(s) for the removed topic so the old section does not
        # linger. The orchestrator re-dispatches + rebuilds per the prompt.
        existing_sections = updates.get("strategy_sections", state.get("strategy_sections", []))
        filtered = [
            s
            for s in (existing_sections or [])
            if not (
                isinstance(s, dict)
                and str(s.get("specialist_type", "")).strip().lower() in removal_targets
            )
        ]
        if len(filtered) != len(existing_sections or []):
            updates["strategy_sections"] = filtered

    return updates


def _active_specialist_topics(state: dict[str, Any]) -> set[str]:
    """Topics (lowercased) with a live section in ``state["strategy_sections"]``.

    Used to scope specialist-tile preservation: only a topic that still owns a
    strategy section is "active", so a removed specialist's tiles are not carried
    forward (tile-state tracks section-state).
    """
    sections = state.get("strategy_sections") or []
    topics: set[str] = set()
    for section in sections:
        if not isinstance(section, dict):
            continue
        topic = str(section.get("specialist_type", "")).strip().lower()
        if topic:
            topics.add(topic)
    return topics


def _tile_specialist_topic(tile: dict[str, Any]) -> str:
    """Topic stamp for an activity tile (``meta.specialist_type`` -> ``meta.category``)."""
    meta = tile.get("meta")
    if not isinstance(meta, dict):
        return ""
    topic = meta.get("specialist_type") or meta.get("category") or ""
    return str(topic).strip().lower()


def _preserve_active_specialist_tiles(
    state: dict[str, Any],
    old_activities: list[Any],
    new_tiles: list[Any],
) -> list[Any]:
    """Union-forward dropped specialist tiles whose topic is still active.

    Appends any existing ``source_agent == "vertical_specialist"`` tile to
    ``new_tiles`` when (a) its id is absent from the fresh results (right-wins by
    id) AND (b) its topic still has a live strategy section. Returns the
    (possibly extended) ``new_tiles`` list; never resurrects a removed topic's
    tiles.
    """
    active_topics = _active_specialist_topics(state)
    if not active_topics:
        return new_tiles

    fresh_ids = {t.get("id") for t in new_tiles if isinstance(t, dict) and t.get("id") is not None}
    preserved = 0
    for tile in old_activities:
        if not isinstance(tile, dict):
            continue
        if tile.get("source_agent") != "vertical_specialist":
            continue
        tile_id = tile.get("id")
        if tile_id is None or tile_id in fresh_ids:
            continue
        if _tile_specialist_topic(tile) not in active_topics:
            continue
        new_tiles.append(tile)
        preserved += 1

    if preserved:
        logger.info(
            "[_merge_tiles] Preserved %d specialist activity tile(s) dropped by search_tiles",
            preserved,
        )
    return new_tiles


def _merge_tiles(state: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Merge search_tiles result into the tiles dict.

    Replaces entire category arrays (flights, hotels, activities) with
    fresh results from the provider.
    """
    tiles = dict(state.get("tiles", {}))

    replaced: list[str] = []
    for category in ("flights", "hotels", "activities"):
        new_tiles = result.get(category)
        if new_tiles is not None:
            # Carry partner (Viator/GYG) enrichment + geo forward from the tiles we're about
            # to replace onto the freshly-fetched ones (matched by id/place_id/title). This
            # keeps affiliate deeplinks/prices and map coordinates stable across re-fetches and
            # avoids re-calling the partner APIs every turn (cost). Activities only -- flights/
            # hotels aren't partner-enriched. Best-effort: never block the merge on it.
            if category == "activities":
                old_activities = state.get("tiles", {}).get("activities") or []
                if old_activities and isinstance(new_tiles, list):
                    try:
                        from app.planner.coordinator import _carry_forward_partner_enrichment

                        _carry_forward_partner_enrichment(new_tiles, old_activities)
                    except Exception as exc:  # pragma: no cover - defensive
                        logger.warning("[_merge_tiles] partner carry-forward failed: %s", exc)

                    # Union-forward specialist activity tiles (source_agent ==
                    # "vertical_specialist") that the fresh search results drop.
                    # These tiles are the ONLY carrier of Viator image+deeplink for
                    # Tier-1 activities (injected in-place by
                    # _inject_specialist_tiles_into_state); search_tiles emits none,
                    # so a wholesale replace would silently strip them and the
                    # subsequent expand-itinerary rebuild loses the partner stamp.
                    #
                    # Scope preservation to topics still present in
                    # strategy_sections so a REMOVED specialist (whose section is
                    # gone) is NOT resurrected -- keeping tile-state consistent with
                    # section-state. Right-wins by id: only carry a specialist tile
                    # forward when its id is absent from the fresh results.
                    new_tiles = _preserve_active_specialist_tiles(state, old_activities, new_tiles)
            tiles[category] = new_tiles
            replaced.append(category)

    # turn_meta delta consumed by the envelope builder (tiles_replaced drives
    # scoped-replace UX; browseable_activities feeds the browse pool).
    turn_meta: dict[str, Any] = {"tiles_replaced": replaced}
    if "browseable_activities" in result:
        turn_meta["browseable_activities"] = result.get("browseable_activities") or []
    if "hotel_filter_cascaded" in result:
        turn_meta["hotel_filter_cascaded"] = bool(result.get("hotel_filter_cascaded"))

    return {"tiles": tiles, "turn_meta": turn_meta}


def _merge_specialist(state: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Merge get_specialist_advice result into strategy_sections and constraints."""
    updates: dict[str, Any] = {}

    # Append strategy section
    section = result.get("strategy_section")
    topic = result.get("topic", "")
    if section:
        # Return ONLY this section as a single-element delta and let the
        # _merge_strategy_sections reducer (dedup-by-specialist_type, right wins)
        # merge it into the channel. Reconstructing the full list from
        # start-of-round state would clobber a SIBLING tool's fresh section
        # (e.g. local_expert) with the stale start-of-round copy when both run in
        # the same parallel round -- the same minimal-delta rule the trip_plan
        # merge below already follows.
        updates["strategy_sections"] = [section]

        # Calling get_specialist_advice for a topic IS the signal that the topic
        # is an active interest -- record it in specialist_hints / categories so
        # (a) the section survives _prune_stale_sections (which reconciles vs
        # hints) even when the LLM skipped extract_trip_fields, and (b) the
        # envelope's categories include it. Union with existing values.
        topic_norm = str(topic).strip().lower()
        if topic_norm:
            cur_tp = state.get("trip_plan", {})
            hints = {str(h).strip().lower() for h in (cur_tp.get("specialist_hints") or [])}
            cats = {str(c).strip().lower() for c in (cur_tp.get("activity_categories") or [])}
            hints.add(topic_norm)
            cats.add(topic_norm)
            # CRITICAL: return ONLY the two keys we change -- NOT a full trip_plan
            # copy. The trip_plan reducer (_merge_dicts) is a shallow merge, so a
            # full copy carries the start-of-round destination=None and would
            # clobber the extract tool's destination when both tools run in the
            # same parallel round.
            updates["trip_plan"] = {
                "specialist_hints": sorted(hints),
                "activity_categories": sorted(cats),
            }

    # Merge constraints (dedup by constraint_id)
    new_constraints = result.get("constraints", [])
    if new_constraints:
        existing_constraints = list(state.get("constraints", []))
        existing_ids = {c.get("constraint_id") for c in existing_constraints if isinstance(c, dict)}
        for c in new_constraints:
            cid = c.get("constraint_id") if isinstance(c, dict) else None
            if cid and cid not in existing_ids:
                existing_constraints.append(c)
                existing_ids.add(cid)
        updates["constraints"] = existing_constraints

    return updates


def _merge_local_intel(state: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Merge get_local_intel result into strategy_sections and constraints."""
    updates: dict[str, Any] = {}

    section = result.get("section")
    if section:
        # Single-element delta only -- the _merge_strategy_sections reducer
        # dedups by specialist_type (local_expert) and merges. Returning the full
        # reconstructed list would clobber a sibling tool's fresh specialist
        # section with the stale start-of-round copy in a parallel round.
        updates["strategy_sections"] = [section]

    # Dedup by constraint_id (same key as _merge_specialist).
    # Local-intel constraints may lack constraint_id; synthesise one from
    # the rule text so the dedup logic is consistent across both mergers.
    new_constraints = result.get("constraints", [])
    if new_constraints:
        existing_constraints = list(state.get("constraints", []))
        existing_ids = {
            c.get("constraint_id")
            for c in existing_constraints
            if isinstance(c, dict) and c.get("constraint_id")
        }
        for c in new_constraints:
            if not isinstance(c, dict):
                continue
            cid = c.get("constraint_id")
            if not cid:
                # Derive a stable id from the rule text
                rule = c.get("rule", "")
                cid = "local_" + rule.lower().replace(" ", "_")[:60] if rule else None
                if cid:
                    c["constraint_id"] = cid
            if cid and cid not in existing_ids:
                existing_constraints.append(c)
                existing_ids.add(cid)
        updates["constraints"] = existing_constraints

    return updates


def _merge_validation(state: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Store validate_plan violations/warnings in turn_meta (delta only)."""
    violations = result.get("violations", [])
    blocking_count = result.get("blocking_count", 0)
    # Delta only -- never copy the full turn_meta (would re-concatenate
    # tools_called through the reducer).
    turn_meta = {
        "validation_result": {
            "valid": result.get("valid", False),
            "violations": violations,
            "warnings": result.get("warnings", []),
            "blocking_count": blocking_count,
        },
        "constraint_violations": violations,
        "has_blocking_violations": bool(blocking_count),
    }
    return {"turn_meta": turn_meta}


def _merge_itinerary(state: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Update day_cards from build_itinerary result."""
    updates: dict[str, Any] = {}
    day_cards = result.get("day_cards", [])
    if day_cards:
        updates["day_cards"] = day_cards

    # Stash builder metadata in turn_meta (delta only -- never copy the full
    # turn_meta, which would re-concatenate tools_called via the reducer).
    updates["turn_meta"] = {
        "builder_result": {
            "success": result.get("success", False),
            "activities_placed": result.get("activities_placed", 0),
            "activities_dropped": result.get("activities_dropped", 0),
            "conflicts": result.get("conflicts", []),
            "warnings": result.get("warnings", []),
        }
    }
    return updates


# Dispatch table: tool name -> merge function
_TOOL_MERGERS: dict[str, Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]] = {
    "extract_trip_fields": _merge_trip_fields,
    "search_tiles": _merge_tiles,
    "get_specialist_advice": _merge_specialist,
    "get_local_intel": _merge_local_intel,
    "validate_plan": _merge_validation,
    "build_itinerary": _merge_itinerary,
}


class TurnLifecycleMiddleware(AgentMiddleware):
    """State synchronisation middleware for the planner agent.

    Responsibilities:

    - **Before agent**: resets ``turn_meta`` to a clean slate for the new turn.
    - **After tool call**: parses each tool's return dict and merges relevant
      fields into ``NomadicAgentState`` (trip_plan, tiles, strategy_sections,
      constraints, day_cards, turn_meta).

    Tool result merging is driven by a dispatch table keyed on
    ``tool_call.name``.  Unknown tool names are silently ignored (the raw
    ToolMessage still reaches the LLM via the message history).
    """

    async def abefore_agent(
        self,
        state: Any,
        runtime: Any,
    ) -> dict[str, Any] | None:
        """Reset turn_meta at the start of each agent turn.

        Safe to overwrite wholesale here: turn_meta is NOT persisted across
        turns (serialize_agent_state drops it), so each invocation starts from
        an empty/default turn_meta that this reset replaces.
        """
        return {
            "turn_meta": {
                "turn_started_at": time.time(),
                "tool_call_count": 0,
                "tools_called": [],
                "turn_steps": [],
                "partial_failures": [],
                "model_turns": 0,
            },
        }

    async def abefore_model(
        self,
        state: Any,
        runtime: Any,
    ) -> dict[str, Any] | None:
        """Count model invocations (round-count, distinct from tool_call_count).

        With parallel tool calls, one model turn can emit N tools, so
        ``tool_call_count`` over-counts rounds. ``model_turns`` measures the
        actual number of model invocations -- the metric that proves "one
        fetch round". Model calls are sequential in the loop, so read-and-
        increment is safe (no parallel collision).
        """
        state_dict: dict[str, Any] = {}
        if isinstance(state, dict):
            state_dict = state
        elif hasattr(state, "get"):
            state_dict = dict(state)
        prev = state_dict.get("turn_meta", {}).get("model_turns", 0) or 0
        return {"turn_meta": {"model_turns": prev + 1}}

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable,
    ) -> ToolMessage | Command:
        """Execute the tool, then merge its result into agent state.

        Wraps the handler call in a try/except so that tool timeouts and
        unexpected errors produce a graceful ToolMessage instead of crashing
        the entire agent loop.
        """
        tool_name = request.tool_call["name"]

        # Execute the tool -- catch timeouts and unexpected errors so the
        # agent receives an error ToolMessage and can decide what to do
        # (e.g. retry, skip, or inform the user) instead of crashing.
        try:
            result = await handler(request)
        except (TimeoutError, asyncio.TimeoutError) as exc:
            logger.warning(
                "[TurnLifecycleMiddleware] Tool %s timed out: %s",
                tool_name,
                exc,
            )
            result = ToolMessage(
                content=json.dumps(
                    {
                        "error": f"Tool '{tool_name}' timed out. Try again or skip this step.",
                        "tool_name": tool_name,
                    }
                ),
                tool_call_id=request.tool_call.get("id", ""),
            )
        except Exception as exc:
            logger.error(
                "[TurnLifecycleMiddleware] Tool %s raised unexpected error: %s",
                tool_name,
                exc,
                exc_info=True,
            )
            result = ToolMessage(
                content=json.dumps(
                    {
                        "error": f"Tool '{tool_name}' failed: {type(exc).__name__}",
                        "tool_name": tool_name,
                    }
                ),
                tool_call_id=request.tool_call.get("id", ""),
            )

        # Increment tool call counter in state
        state_dict: dict[str, Any] = {}
        if request.state is not None:
            if isinstance(request.state, dict):
                state_dict = request.state
            elif hasattr(request.state, "get"):
                state_dict = dict(request.state)

        # Build state update from tool result
        state_updates: dict[str, Any] = {}

        # Detect a failed tool (error ToolMessage from the except branches or a
        # tool that returned an {"error": ...} payload).
        parsed = _extract_tool_result(result) if isinstance(result, ToolMessage) else None
        tool_errored = bool(parsed and "error" in parsed)

        # turn_meta DELTA only. tools_called / turn_steps / partial_failures are
        # concatenated by the _merge_turn_meta reducer, so return single-element
        # deltas -- returning the full accumulated list would re-concatenate.
        turn_meta_delta: dict[str, Any] = {
            "tools_called": [tool_name],
            "turn_steps": [{"node": tool_name, "status": "error" if tool_errored else "completed"}],
        }
        if tool_errored:
            turn_meta_delta["partial_failures"] = [
                {"tool": tool_name, "error": (parsed or {}).get("error", "unknown")}
            ]
        state_updates["turn_meta"] = turn_meta_delta

        # Parse and merge tool-specific result (skip error ToolMessages)
        merger = _TOOL_MERGERS.get(tool_name)
        if merger is not None and not tool_errored and parsed is not None:
            try:
                tool_updates = merger(state_dict, parsed)
                # Fold the merger's turn_meta delta into ours (right-wins for
                # scalar/dict keys; the reducer concatenates the list keys).
                if "turn_meta" in tool_updates:
                    merged_turn_meta = dict(state_updates["turn_meta"])
                    merged_turn_meta.update(tool_updates.pop("turn_meta"))
                    state_updates["turn_meta"] = merged_turn_meta
                state_updates.update(tool_updates)
            except Exception as exc:
                logger.warning(
                    "[TurnLifecycleMiddleware] Merge failed for %s: %s",
                    tool_name,
                    exc,
                )

        logger.debug(
            "[TurnLifecycleMiddleware] Tool %s complete (errored=%s), state keys updated: %s",
            tool_name,
            tool_errored,
            list(state_updates.keys()),
        )

        # get_local_intel's full skeleton is already merged into state for the plan panel
        # above. Shrink the MODEL-FACING ToolMessage to a concise summary so the model
        # acknowledges local intel without re-listing the generic travel-info checklist it
        # otherwise parrots into chat every time the tool runs. Scoped to this one tool; all
        # other tool results reach the model verbatim. (The merge above mutates `parsed` in
        # place -- adds constraint_id -- but the summary reads only generic_fallback/label/rule,
        # which it never touches, so ordering is safe.)
        if (
            tool_name == "get_local_intel"
            and not tool_errored
            and parsed is not None
            and isinstance(result, ToolMessage)
        ):
            result = ToolMessage(
                content=_summarize_local_intel_for_model(parsed),
                tool_call_id=result.tool_call_id,
                name=result.name,
            )

        # If the handler already returned a Command (e.g. with goto routing),
        # merge our state_updates into its existing update dict and preserve
        # goto so we don't lose downstream routing decisions.
        if isinstance(result, Command):
            existing_update = result.update or {}
            merged = {**existing_update, **state_updates}
            return Command(update=merged, goto=result.goto)

        # Standard path: wrap the ToolMessage in a Command with state updates
        return Command(
            update={
                "messages": [result] if isinstance(result, ToolMessage) else [],
                **state_updates,
            }
        )
