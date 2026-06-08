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
from typing import Any, AsyncGenerator, AsyncIterator, Dict, Optional

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


def _merge_patch_changed_fields(state: Dict[str, Any], patch_fields: Any) -> None:
    """Fold PATCH-driven field changes into ``turn_meta.fields_changed``.

    Dates/destination set via the Dates sheet are PATCHed onto the document and
    a silent GENERATE_PLAN_NOW turn is fired. Because those fields were not
    extracted from chat text, ``extract_trip_fields`` produces no diff and
    ``turn_meta.fields_changed`` stays empty -- so the autobuild/autovalidate
    gates (which key off ``fields_changed``) never fire. ``streaming.py`` records
    the diff as ``_patch_changed_fields`` on the INITIAL state dict; that key is
    NOT a declared ``NomadicAgentState`` channel, so it never reaches the graph's
    ``values`` output. This merges it (dedup) into ``fields_changed`` on the final
    state so a PATCH-only date change satisfies both deterministic gates.

    Mutates ``state`` in place; creates ``turn_meta``/``fields_changed`` if absent.
    """
    if not patch_fields or not isinstance(patch_fields, (list, tuple, set)):
        return
    turn_meta = state.get("turn_meta")
    if not isinstance(turn_meta, dict):
        turn_meta = {}
        state["turn_meta"] = turn_meta
    existing = turn_meta.get("fields_changed") or []
    turn_meta["fields_changed"] = sorted(set(existing) | set(patch_fields))


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


def _should_autovalidate(state: Dict[str, Any], built_this_turn: bool) -> bool:
    """Whether to deterministically validate the plan after the agent loop.

    Validation must not be left to the model's discretion: Gemini Flash often
    omits validate_plan, so without a backstop an infeasible plan (budget overrun,
    bad dates, non-existent place) can reach the envelope unchecked. Run it once
    this turn produced or changed a substantive plan and the model did not already
    validate -- the result is merged into turn_meta so _build_envelope surfaces the
    same constraint/feasibility state a model-invoked validate_plan would. Skipped
    on pure Q&A turns and de-duped when the model already called validate_plan.

    NOTE: this runs AFTER the assistant text has streamed, so it gates the
    envelope/feasibility surface, not the streamed prose -- the prompt nudges the
    model to call validate_plan itself (so its words reflect issues) and this is the
    guarantee for when it doesn't. Mirrors the deterministic auto-build.
    """
    tm = state.get("turn_meta", {})
    if "validate_plan" in (tm.get("tools_called") or []):
        return False  # model already validated this turn
    tp = state.get("trip_plan", {})
    if not (tp.get("destination") and tp.get("start_date") and tp.get("end_date")):
        return False
    tools = set(tm.get("tools_called") or [])
    fields = set(tm.get("fields_changed") or [])
    return (
        built_this_turn
        or bool(tools & {"search_tiles", "get_specialist_advice"})
        or bool(fields & {"destination", "start_date", "end_date", "duration_days", "budget"})
    )


def _drop_unbookable_specialist_blocks(state: Dict[str, Any]) -> None:
    """Graph-path twin of the builder's Phase 2.55 drop.

    On the graph build path, specialist tiles are injected with placeholder
    Google-Maps deeplinks and only receive their real Viator/GYG match POST-build
    in ``_run_itinerary_enrichment_pipeline``. So the authoritative point to drop
    a non-bookable AI-suggested Tier-1 specialist block is HERE, after enrichment
    has stamped affiliate data onto ``booked_tile``/``deeplink`` of placed blocks.

    Conservative: only fires when at least one Tier-1 specialist block now carries
    an affiliate booking (positive evidence enrichment ran on this set), so a
    partner-disabled deployment or a zero-affiliate-match destination never nukes
    all specialist content. No backfill is attempted here (a subsequent
    category-change expand re-places with Phase 5.6 backfill); dropped blocks are
    logged so the removal is never silent. Mutates ``state`` in place.
    """
    from app.config import settings
    from app.services.partner_enrichment import (
        has_affiliate_booking,
        is_tier1_specialist_activity,
        is_unbookable_specialist_activity,
    )

    has_viator = settings.viator_enabled and settings.viator_api_key
    has_gyg = settings.get_your_guide_enabled and settings.get_your_guide_api_key
    if not (has_viator or has_gyg):
        return

    day_cards = state.get("day_cards") or []
    if not isinstance(day_cards, list):
        return

    def _block_booked_tile(block: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        bt = block.get("booked_tile")
        return bt if isinstance(bt, dict) else None

    def _is_droppable_block(block: Dict[str, Any]) -> bool:
        if not isinstance(block, dict) or block.get("is_buffer"):
            return False
        if (block.get("activity_type") or "").lower() in (
            "arrival",
            "departure",
            "check_in",
            "check-in",
            "check_out",
            "check-out",
            "free_day",
        ):
            return False
        return is_tier1_specialist_activity(
            specialist_type=block.get("specialist_type"),
            activity_domain=block.get("activity_domain"),
            source_agent=(block.get("booked_tile") or {}).get("source_agent")
            if isinstance(block.get("booked_tile"), dict)
            else None,
            provenance=block.get("activity_provenance"),
        )

    # Evidence gate: at least one Tier-1 specialist block must now be bookable.
    has_evidence = False
    for card in day_cards:
        if not isinstance(card, dict):
            continue
        for block in card.get("blocks", []) or []:
            if not _is_droppable_block(block):
                continue
            if has_affiliate_booking(_block_booked_tile(block), block.get("deeplink")):
                has_evidence = True
                break
        if has_evidence:
            break

    if not has_evidence:
        return

    _NON_ACTIVITY_TYPES = (
        "free_day",
        "check-in",
        "check_in",
        "check-out",
        "check_out",
        "arrival",
        "departure",
    )

    dropped: list[str] = []
    for card in day_cards:
        if not isinstance(card, dict):
            continue
        blocks = card.get("blocks", [])
        if not isinstance(blocks, list):
            continue
        card_dropped = False
        kept_blocks: list[Dict[str, Any]] = []
        for block in blocks:
            if _is_droppable_block(block) and is_unbookable_specialist_activity(
                specialist_type=block.get("specialist_type"),
                activity_domain=block.get("activity_domain"),
                source_agent=(block.get("booked_tile") or {}).get("source_agent")
                if isinstance(block.get("booked_tile"), dict)
                else None,
                provenance=block.get("activity_provenance"),
                matched_tile=_block_booked_tile(block),
                deeplink=block.get("deeplink"),
            ):
                dropped.append(str(block.get("summary") or block.get("activity_type") or "?"))
                card_dropped = True
                continue
            kept_blocks.append(block)
        card["blocks"] = kept_blocks

        # No backfill on the graph path (the next category-change expand re-places
        # with Phase 5.6 backfill), but never leave a day that the drop emptied of
        # real activities as a broken blank card -- mirror Phase 5.5's free_day
        # placeholder so it renders as an explorable "Free Day".
        if not card_dropped:
            continue
        has_real_activity = any(
            isinstance(b, dict)
            and not b.get("is_buffer")
            and (b.get("activity_type") or "").lower() not in _NON_ACTIVITY_TYPES
            for b in kept_blocks
        )
        if not has_real_activity:
            buffer_count = sum(1 for b in kept_blocks if isinstance(b, dict) and b.get("is_buffer"))
            kept_blocks.insert(
                buffer_count,
                {
                    "id": f"free_day_{card.get('day_number', 0)}",
                    "period": "morning",
                    "activity_type": "free_day",
                    "summary": "Free Day - explore at your own pace",
                    "is_buffer": False,
                    "specialist_type": None,
                    "intensity": "light",
                },
            )
            card["blocks"] = kept_blocks
            if card.get("label") not in ("Arrival Day", "Departure Day"):
                card["label"] = "Free Day"

    if dropped:
        logger.info(
            "[run_agent_turn_streaming] dropped %d unbookable specialist block(s) "
            "(no affiliate product): %s",
            len(dropped),
            dropped,
        )

    # Reconcile the tile pool (browse pool + map pins) and Advice sections with the
    # day-card drop above: remove fully-unbookable specialist tiles + ghost sections.
    # Same affiliate-evidence gate (applied inside the helper) so a partner-disabled
    # / zero-match turn prunes nothing. Runs AFTER the block drop so day_cards already
    # reflect surviving blocks (a specialist with a surviving bookable block keeps its
    # section even with no bookable tile).
    from app.services.partner_enrichment import prune_unbookable_specialist_artifacts

    tiles = state.get("tiles")
    if not isinstance(tiles, dict):
        return
    activity_tiles = tiles.get("activities")
    if not isinstance(activity_tiles, list):
        return
    sections = state.get("strategy_sections")
    sections = sections if isinstance(sections, list) else []

    kept_tiles, kept_sections, dropped_tile_ids, dropped_topics = (
        prune_unbookable_specialist_artifacts(activity_tiles, sections, day_cards)
    )
    if not dropped_tile_ids and not dropped_topics:
        return

    tiles["activities"] = kept_tiles
    state["tiles"] = tiles
    if isinstance(state.get("strategy_sections"), list):
        state["strategy_sections"] = kept_sections

    # The flattened envelope activity pool is additive on the frontend; signal a
    # replace so the dropped tiles/pins actually disappear (mirrors
    # _prune_stale_sections' tiles_replaced contract for the removal-inert class).
    if dropped_tile_ids:
        turn_meta = state.get("turn_meta")
        if not isinstance(turn_meta, dict):
            turn_meta = {}
        turn_meta["tiles_replaced"] = True
        state["turn_meta"] = turn_meta

    logger.info(
        "[run_agent_turn_streaming] pruned %d unbookable specialist tile(s) and "
        "%d ghost section(s): tile_ids=%s topics=%s",
        len(dropped_tile_ids),
        len(dropped_topics),
        sorted(dropped_tile_ids),
        sorted(dropped_topics),
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
    # Track whether we dropped a section for an EXPLICIT removal target (not merely a
    # stale-destination drop): that alone must trigger the cleanup below, because the
    # frontend's additive section re-push is gated on tiles_replaced (RC2) -- if a
    # removed section is dropped here but tiles_replaced is never set, the frontend
    # resurrects it (and its map POIs).
    removal_section_dropped = False
    if sections and (current_dest or removal_targets):
        kept = []
        for s in sections:
            if isinstance(s, dict):
                stype = str(s.get("specialist_type", "")).strip().lower()
                if stype and stype in removal_targets:
                    removal_section_dropped = True
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

    # Seed `pruned` with the section-drop signal: when the agent re-fetched this turn it
    # may have already REPLACED the removed topic's activity tiles (so the tile/plan loops
    # below find nothing to prune), yet the section drop above is a real removal that the
    # frontend must honor. Without this, `pruned` stays False, tiles_replaced/removal_pruned
    # are never set, day_cards keep the agent-built content, and the frontend resurrects the
    # dropped section + POIs -- the "'No diving' doesn't remove the day cards / map POIs" bug.
    pruned = removal_section_dropped

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


# Block types that are NOT real activities -- buffers, boundary days, and the
# free-day placeholder. Mirrors the builder's _NON_ACTIVITY_TYPES so the
# remove-all clear keeps the same structural blocks the builder protects.
_REMOVE_ALL_KEEP_TYPES = frozenset(
    {
        "free_day",
        "check-in",
        "check_in",
        "check-out",
        "check_out",
        "arrival",
        "departure",
        "rest",
        "rest_day",
        "buffer",
        "decompression_buffer",
        "acclimatization",
        "no_fly",
    }
)


def _apply_remove_all_activities(state: Dict[str, Any]) -> None:
    """Deterministically empty the plan of ALL activities when the traveler asks.

    THE GUARANTEE for the "remove all activities" intent. The in-loop model can
    autonomously re-plan within the same turn (e.g. re-run get_specialist_advice
    "to focus on diving") and re-inject activity tiles + day-blocks, so an
    early/in-loop clear loses a race. This runs LAST in the post-loop block --
    AFTER _merge_tiles preservation (in-loop), AFTER _drop_unbookable_specialist_
    blocks / prune_unbookable_specialist_artifacts and _prune_stale_sections
    (post-loop) -- so nothing re-seeds what it clears.

    Gated strictly on turn_meta.remove_all_activities (sourced from
    extract_trip_fields this turn). Fires only when True -- no speculative clear.

    When set, it:
      1. Drops every real-activity day-block, keeping buffers, arrival/departure/
         check-in/check-out/no-fly/rest/acclimatization, hotel + flight blocks,
         and free_day placeholders. Days emptied of activities become free days
         (reusing _drop_unbookable_specialist_blocks' free_day placeholder).
      2. Empties state["tiles"]["activities"].
      3. Drops Tier-1 specialist strategy_sections (keeps local_expert / non-
         activity destination sections).
      4. Sets booking_types.activities="off" and activity_settings.categories=[]
         so subsequent turns don't re-fetch/backfill and the envelope reflects it.

    Sets turn_meta.tiles_replaced + removal_pruned (mirrors _prune_stale_sections)
    so the frontend's additive pools are REPLACED, not resurrected. Mutates in
    place; logs everything cleared (never silent).
    """
    from app.planner.specialist_registry import TIER1_SPECIALIST_NAMES

    turn_meta = state.get("turn_meta")
    if not isinstance(turn_meta, dict) or not turn_meta.get("remove_all_activities"):
        return

    dropped_blocks = 0
    freed_days = 0

    # (1) Drop real-activity blocks; keep buffers/boundaries/hotel/flight; re-add
    # a free_day placeholder to any day the drop emptied of real activities.
    day_cards = state.get("day_cards")
    if isinstance(day_cards, list):
        for card in day_cards:
            if not isinstance(card, dict):
                continue
            blocks = card.get("blocks")
            if not isinstance(blocks, list):
                continue

            def _is_keep_block(block: Dict[str, Any]) -> bool:
                if not isinstance(block, dict):
                    return True  # never drop something we can't classify
                if block.get("is_buffer"):
                    return True
                atype = (block.get("activity_type") or "").lower()
                if atype in _REMOVE_ALL_KEEP_TYPES:
                    return True
                # Hotel/flight blocks are logistics, not activities -- always keep.
                if (block.get("booking_category") or "").lower() in ("hotel", "flight"):
                    return True
                return False

            kept_blocks = [b for b in blocks if _is_keep_block(b)]
            dropped_blocks += len(blocks) - len(kept_blocks)

            has_real_activity = any(
                isinstance(b, dict)
                and not b.get("is_buffer")
                and (b.get("activity_type") or "").lower() not in _REMOVE_ALL_KEEP_TYPES
                and (b.get("booking_category") or "").lower() not in ("hotel", "flight")
                for b in kept_blocks
            )
            if not has_real_activity:
                already_free = any(
                    isinstance(b, dict) and (b.get("activity_type") or "").lower() == "free_day"
                    for b in kept_blocks
                )
                if not already_free:
                    buffer_count = sum(
                        1 for b in kept_blocks if isinstance(b, dict) and b.get("is_buffer")
                    )
                    kept_blocks.insert(
                        buffer_count,
                        {
                            "id": f"free_day_{card.get('day_number', 0)}",
                            "period": "morning",
                            "activity_type": "free_day",
                            "summary": "Free Day - explore at your own pace",
                            "is_buffer": False,
                            "specialist_type": None,
                            "intensity": "light",
                        },
                    )
                    freed_days += 1
                if card.get("label") not in ("Arrival Day", "Departure Day"):
                    card["label"] = "Free Day"
            card["blocks"] = kept_blocks

    # (2) Empty the activity tile pool.
    tiles = state.get("tiles")
    activities_cleared = 0
    if isinstance(tiles, dict):
        activities_cleared = len(tiles.get("activities") or [])
        tiles["activities"] = []
        state["tiles"] = tiles

    # (3) Drop Tier-1 specialist sections; keep local_expert / non-activity ones.
    sections = state.get("strategy_sections")
    sections_dropped: list[str] = []
    if isinstance(sections, list):
        kept_sections = []
        for s in sections:
            stype = str(s.get("specialist_type", "")).strip().lower() if isinstance(s, dict) else ""
            if stype in TIER1_SPECIALIST_NAMES:
                sections_dropped.append(stype)
                continue
            kept_sections.append(s)
        if len(kept_sections) != len(sections):
            state["strategy_sections"] = kept_sections

    # Drop specialist_plans for the cleared topics so a later rebuild can't re-seed.
    specialist_plans = state.get("specialist_plans")
    if isinstance(specialist_plans, dict):
        for key in list(specialist_plans.keys()):
            if str(key).strip().lower() in TIER1_SPECIALIST_NAMES:
                specialist_plans.pop(key, None)

    # (4) Settings: activities off + categories cleared (mirrored in trip_plan and
    # trip_settings.activity_settings so neither the next fetch nor the envelope
    # re-surfaces activities).
    trip_settings = state.get("trip_settings")
    if not isinstance(trip_settings, dict):
        trip_settings = {}
    trip_settings = dict(trip_settings)
    booking_types = dict(trip_settings.get("booking_types") or {})
    booking_types["activities"] = "off"
    trip_settings["booking_types"] = booking_types
    activity_settings = dict(trip_settings.get("activity_settings") or {})
    activity_settings["categories"] = []
    trip_settings["activity_settings"] = activity_settings
    state["trip_settings"] = trip_settings

    trip_plan = state.get("trip_plan")
    if isinstance(trip_plan, dict):
        trip_plan["activity_categories"] = []
        trip_plan["specialist_hints"] = []

    # Signal a REPLACE (not additive) for the tile/browse pools + section list so
    # the frontend drops POIs instead of resurrecting them; removal_pruned makes
    # the envelope emit itinerary_day_cards=[] when day_cards is empty.
    turn_meta["tiles_replaced"] = True
    turn_meta["removal_pruned"] = True
    turn_meta["browseable_activities"] = []
    state["turn_meta"] = turn_meta

    # Clear any persisted browse pool so the envelope can't rehydrate it.
    persistent_meta = state.get("persistent_meta")
    if isinstance(persistent_meta, dict) and persistent_meta.get("browseable_activities"):
        persistent_meta = dict(persistent_meta)
        persistent_meta["browseable_activities"] = []
        state["persistent_meta"] = persistent_meta

    logger.info(
        "[run_agent_turn_streaming] remove_all_activities: dropped %d activity block(s), "
        "freed %d day(s), cleared %d activity tile(s), dropped sections=%s, "
        "set booking_types.activities=off + categories=[]",
        dropped_blocks,
        freed_days,
        activities_cleared,
        sorted(set(sections_dropped)),
    )


def _reenable_activities_if_requested(state: Dict[str, Any]) -> None:
    """Un-stick: re-enable activities when this turn requested activity interest.

    booking_types.activities="off" (set by a prior remove-all turn) is sticky.
    The primary re-enable lives in _merge_trip_fields (when activity_categories /
    specialist_hints change). This is the deterministic backstop for turns where
    the model called get_specialist_advice WITHOUT extract_trip_fields: a live
    specialist section (or non-empty interests) while activities are "off" means
    the traveler asked for activities again, so flip it back on.

    NEVER fires on a remove-all turn: _apply_remove_all_activities runs FIRST and
    leaves no sections/categories, so there is nothing to re-enable.
    """
    if (state.get("turn_meta", {}) or {}).get("remove_all_activities"):
        return  # remove-all wins this turn

    trip_settings = state.get("trip_settings")
    if not isinstance(trip_settings, dict):
        return
    booking_types = trip_settings.get("booking_types")
    if not isinstance(booking_types, dict) or booking_types.get("activities") != "off":
        return

    trip_plan = state.get("trip_plan", {}) or {}
    has_interest = bool(trip_plan.get("activity_categories") or trip_plan.get("specialist_hints"))
    from app.planner.specialist_registry import TIER1_SPECIALIST_NAMES

    has_specialist_section = any(
        isinstance(s, dict)
        and str(s.get("specialist_type", "")).strip().lower() in TIER1_SPECIALIST_NAMES
        for s in (state.get("strategy_sections") or [])
    )
    if not (has_interest or has_specialist_section):
        return

    trip_settings = dict(trip_settings)
    booking_types = dict(booking_types)
    booking_types["activities"] = "suggested"
    trip_settings["booking_types"] = booking_types
    state["trip_settings"] = trip_settings
    logger.info(
        "[run_agent_turn_streaming] re-enabled activities (was off) -- "
        "traveler requested activity interest again"
    )


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


def _chunk_text(content: Any) -> str:
    """Extract streamable text from an AIMessageChunk's ``content``.

    Gemini 3 returns content as a LIST of typed parts
    (``[{"type": "text", "text": "..."}, ...]``) rather than a plain string,
    while Gemini 2.5 / OpenAI return a ``str``. A bare ``isinstance(content, str)``
    check therefore dropped every Gemini-3 token, which is why the loop's real
    terminal response never reached the client and a static boilerplate shipped
    each turn. Normalize both shapes to plain text so token streaming is
    provider-agnostic.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: list[str] = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text" and isinstance(part.get("text"), str):
                    out.append(part["text"])
            elif isinstance(part, str):
                out.append(part)
        return "".join(out)
    return ""


async def _stream_terminal_response(state: Dict[str, Any], user_message: str) -> AsyncIterator[str]:
    """Stream a One-Voice terminal reply when the tool loop produced no prose.

    The create_agent loop is meant to end on a terminal (no-tool) model turn that
    streams the assistant response. Gemini Flash intermittently empties out after
    tool rounds -- and the deterministic auto-build can consume the final round --
    leaving no prose, which previously surfaced a static "I'm working on your trip
    plan" boilerplate on EVERY tool-running turn. This makes one focused, tool-free
    model call over the now-final state so the traveler gets a real, turn-specific
    reply. Yields token strings; the caller emits them as {"type": "token"} SSE
    events (same contract as the loop's terminal turn). Best-effort: any failure
    leaves the caller to fall back to the boilerplate.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.config import settings
    from app.planner.llm_factory import get_llm_by_model
    from app.planner.prompts.planner import build_trip_state_summary

    summary = build_trip_state_summary(state)
    turn_meta = state.get("turn_meta", {}) or {}
    changed = turn_meta.get("fields_changed", []) or []
    changed_note = f"Fields updated this turn: {', '.join(changed)}." if changed else ""

    system = (
        "You are Nomadic's travel-planning assistant speaking directly to the "
        "traveler. Their trip plan was just updated. In 1-3 warm sentences, confirm "
        "what you just changed and what's ready now. You MAY reference the destination, "
        "the dates, and the activity categories the traveler asked for -- but do NOT "
        "invent or name specific attractions, venues, hotels, or places that aren't "
        "already in their plan (this avoids surfacing ungrounded names). Do NOT dump "
        "raw lists, do NOT call tools, and never use the generic phrase 'I'm working "
        "on your trip plan'."
    )
    # On a remove-all-activities turn the plan was just emptied of every activity;
    # steer the fallback reply to confirm the removal (never claim to have added any).
    if turn_meta.get("remove_all_activities"):
        system += (
            " The traveler asked to remove ALL activities, and every activity has been "
            "cleared -- hotels, flights, and free days remain. Confirm that all "
            "activities were removed; do NOT claim to have added or kept any activity."
        )
    llm = get_llm_by_model(settings.synthesizer_planning_model, streaming=True)
    messages = [
        SystemMessage(content=system),
        SystemMessage(content=f"Current trip state:\n{summary}\n{changed_note}".strip()),
        HumanMessage(content=user_message or "Continue planning my trip."),
    ]
    async for chunk in llm.astream(messages):
        text = _chunk_text(getattr(chunk, "content", None))
        if text:
            yield text


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
                tool_chunks = getattr(chunk, "tool_call_chunks", None)
                # Gemini 3 streams content as a list of typed parts, not a str --
                # normalize so terminal-response tokens aren't silently dropped.
                text = _chunk_text(getattr(chunk, "content", None))
                if isinstance(chunk, AIMessageChunk) and text and not tool_chunks:
                    if not response_started and any_tool:
                        response_started = True
                        yield _node_status_event("response", "started")
                    parts.append(text)
                    yield {"type": "token", "data": text}
        if response_started:
            yield _node_status_event("response", "completed")
        yield ("__result__", {"assistant": "".join(parts), "any_tool": any_tool})

    sugg_task: Optional[asyncio.Task] = None
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
        # May be empty when the tool loop produced no terminal prose; a real
        # One-Voice reply is generated below (after auto-build/validation) so it
        # reflects the FINAL plan, with the boilerplate only as a last resort.
        assistant_message = result["assistant"].strip()
        final_state = last_values if isinstance(last_values, dict) else state

        # Prompt-cache visibility: sum input vs prefix-cached tokens across THIS
        # turn's model calls. Rehydrated history carries no usage_metadata, so only
        # live calls count. cache_read is langchain's normalized field (Gemini
        # cached_content_token_count / OpenAI cached_tokens both land here), so this
        # one line reports real system+tools+history prefix reuse per turn.
        _in_tok = _cached_tok = _calls = 0
        for _m in final_state.get("messages", []) or []:
            _um = getattr(_m, "usage_metadata", None)
            if not _um:
                continue
            _calls += 1
            _in_tok += int(_um.get("input_tokens") or 0)
            _det = _um.get("input_token_details") or {}
            _cached_tok += int(
                (
                    _det.get("cache_read")
                    if isinstance(_det, dict)
                    else getattr(_det, "cache_read", 0)
                )
                or 0
            )
        if _in_tok:
            logger.info(
                "[cache] turn: %d model call(s), %d/%d input tokens cached (%.0f%%)",
                _calls,
                _cached_tok,
                _in_tok,
                100.0 * _cached_tok / _in_tok,
            )

        # Whether the itinerary was (re)built THIS turn. Only then does it need
        # re-enrichment -- a pure-question turn on an existing trip reuses already-enriched
        # day_cards, so we must NOT re-run the (paid) enrichment pass on it. Seeded from a
        # direct LLM build_itinerary call; set below when the deterministic auto-build fires.
        built_this_turn = "build_itinerary" in (
            final_state.get("turn_meta", {}).get("tools_called") or []
        )

        # PATCH-driven field changes (e.g. dates set via the Dates sheet, then a
        # silent GENERATE_PLAN_NOW) aren't extracted from chat text, so they leave
        # turn_meta.fields_changed empty and the gates below never fire. streaming.py
        # records the diff as _patch_changed_fields on the INITIAL state dict; it is
        # NOT a declared NomadicAgentState channel, so it never reaches last_values/
        # final_state -- read it from the initial `state` (with final_state as a
        # defensive fallback) and fold it into fields_changed so the autobuild AND
        # autovalidate gates both see the change.
        _patch_fields = state.get("_patch_changed_fields") or final_state.get(
            "_patch_changed_fields"
        )
        _merge_patch_changed_fields(final_state, _patch_fields)

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

            # Drop AI-suggested Tier-1 specialist blocks left without an affiliate
            # product after enrichment (authoritative post-enrichment point on the
            # graph path; placeholder deeplinks have now been resolved to real
            # Viator/GYG matches or remain unbookable). Guarded internally by the
            # affiliate-evidence gate so partner-disabled / zero-match turns are inert.
            try:
                _drop_unbookable_specialist_blocks(final_state)
            except Exception as drop_exc:  # pragma: no cover - defensive
                logger.warning(
                    "[run_agent_turn_streaming] unbookable-specialist drop skipped: %s",
                    drop_exc,
                )

        _prune_stale_sections(final_state)

        # Un-stick activities before the remove-all clear: if the traveler asked
        # for activity interest this turn (specialist section / categories) while
        # activities were stuck "off" from a prior remove-all, flip them back on.
        # Runs first so a real remove-all turn (handled next) still wins.
        _reenable_activities_if_requested(final_state)

        # THE GUARANTEE for "remove all activities": runs LAST in the post-loop
        # block -- after _merge_tiles preservation (in-loop), after
        # _drop_unbookable_specialist_blocks / _prune_stale_sections -- so nothing
        # re-seeds what it clears. Flag-gated internally (turn_meta.remove_all_
        # activities); inert otherwise.
        _apply_remove_all_activities(final_state)

        # Deterministic validation gate: enforce validate_plan before finalizing.
        # The model is prompted to call it itself (so its prose reflects issues),
        # but Flash often skips it -- this backstop guarantees a real feasibility
        # check on every substantive turn and merges the result into turn_meta so
        # _build_envelope surfaces violations the same way a model call would.
        if _should_autovalidate(final_state, built_this_turn):
            yield _node_status_event("validate_plan", "started")
            try:
                from app.planner.middleware import _merge_validation
                from app.planner.tools.validate_plan import validate_plan as _validate_tool

                # Backstop runs deterministic checks only (budget/dates/constraints);
                # the LLM place/route check stays with the model-invoked path.
                validation = await _validate_tool.coroutine(
                    state=final_state, skip_route_check=True
                )
                if isinstance(validation, dict):
                    val_updates = _merge_validation(final_state, validation)
                    merged_meta = dict(final_state.get("turn_meta", {}))
                    merged_meta.update(val_updates.get("turn_meta", {}))
                    final_state["turn_meta"] = merged_meta
                    for v in validation.get("violations", []) or []:
                        if isinstance(v, dict) and v.get("severity") == "blocking":
                            yield {
                                "type": "feasibility_warning",
                                "data": {
                                    "topic": v.get("field") or "plan",
                                    "status": "infeasible",
                                    "reason": v.get("message", ""),
                                    "alternative": v.get("suggested_action", ""),
                                },
                            }
            except Exception as val_exc:
                logger.warning("[run_agent_turn_streaming] auto-validate failed: %s", val_exc)
            yield _node_status_event("validate_plan", "completed")

        # LLM suggestion chips: generated CONCURRENTLY with the terminal reply.
        # Kicked off here (unconditionally — Q&A/conversational turns produce prose
        # in-loop and skip the terminal-response block below, but still need chips)
        # over the FINAL post-mutation state, then awaited just before
        # _build_envelope under a short timeout so it never gates the complete event.
        try:
            from app.planner.services.suggestion_generator import generate_suggestion_chips

            sugg_task = asyncio.create_task(
                generate_suggestion_chips(final_state, list(final_state.get("messages", []) or []))
            )
        except Exception as sugg_exc:  # pragma: no cover - defensive
            logger.warning(
                "[run_agent_turn_streaming] suggestion-chip task launch failed: %s", sugg_exc
            )
            sugg_task = None

        # One Voice: if the tool loop ran tools but produced no terminal prose,
        # stream a real, plan-specific reply now (over the FINAL state) instead of
        # shipping the static boilerplate that otherwise repeats every turn. Tokens
        # use the same {"type": "token"} contract as the loop's terminal turn.
        if (
            not assistant_message
            and result["any_tool"]
            and not (cancel_event is not None and cancel_event.is_set())
        ):
            yield _node_status_event("response", "started")
            gen_parts: list[str] = []
            try:
                async for tok in _stream_terminal_response(final_state, user_message):
                    gen_parts.append(tok)
                    yield {"type": "token", "data": tok}
                assistant_message = "".join(gen_parts).strip()
            except Exception as resp_exc:
                logger.warning(
                    "[run_agent_turn_streaming] terminal response generation failed: %s",
                    resp_exc,
                )
            # Always pair "started" with "completed", even on the error path
            # (matches the auto-build / auto-validate node_status convention).
            yield _node_status_event("response", "completed")

        if not assistant_message:
            assistant_message = (
                "I'm working on your trip plan. Let me know if you'd like to adjust anything."
            )

        # Harvest the concurrent suggestion-chip task under a short timeout. Never
        # gates the complete event beyond suggestions_timeout_s; on timeout/None/
        # exception leave _llm_suggestion_chips unset so _build_envelope falls back
        # to the deterministic generator.
        if sugg_task is not None:
            from app.config import settings as _settings

            try:
                sugg_chips = await asyncio.wait_for(
                    sugg_task, timeout=_settings.suggestions_timeout_s
                )
                if isinstance(sugg_chips, list) and sugg_chips:
                    final_state["_llm_suggestion_chips"] = sugg_chips
            except (asyncio.TimeoutError, asyncio.CancelledError):
                sugg_task.cancel()
            except Exception as sugg_exc:  # pragma: no cover - defensive
                logger.warning(
                    "[run_agent_turn_streaming] suggestion-chip harvest failed: %s", sugg_exc
                )

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
    finally:
        # Ensure the concurrent suggestion-chip task is never orphaned — covers the
        # GeneratorExit (client disconnect mid-yield) and normal-exit paths that the
        # `except Exception` above cannot catch. No-op once already harvested/done.
        if sugg_task is not None and not sugg_task.done():
            sugg_task.cancel()
            await asyncio.gather(sugg_task, return_exceptions=True)
