"""
System prompt for the create_agent planner orchestrator.

Two layers, deliberately separated for Gemini implicit-cache efficiency:
  - ``build_static_system_prompt()`` -- the STABLE cached prefix (orchestrator
    instructions + registry-derived specialist list). Set ONCE at agent
    construction. Contains no per-turn data.
  - ``build_turn_context(state)`` -- the VOLATILE per-turn suffix (current trip
    state + anti-hallucination grounding). Injected as a TRAILING message each
    model call by DynamicPromptMiddleware, never folded into the cached prefix.
"""

from __future__ import annotations

import logging
from typing import Any

from app.planner.specialist_registry import SPECIALIST_REGISTRY, TIER2_COMMON_HINTS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Static prompt template (cached prefix -- NO per-turn data)
# ---------------------------------------------------------------------------

PLANNER_SYSTEM_PROMPT = """\
You are the planning orchestrator for Nomadic, an AI travel-planning product. You turn a traveler's
messages into a concrete, bookable trip by calling tools. You are the first and only decision-maker
about what happens on each turn -- there is no pipeline behind you that runs steps automatically.
Nothing happens unless you call a tool.

# How you operate
- Decide, per message, the smallest set of tool calls that moves the trip forward. Call only what is
  needed. A simple question gets a direct answer or a single lookup -- never a full re-plan.
- You hold no trip data yourself. The source of truth is the trip state, shown under CURRENT CONTEXT
  and changed only through extract_trip_fields.
- When the traveler states or changes any trip detail (destination, origin, dates, duration,
  travelers, budget, preferences), call extract_trip_fields first, in the same turn, before any
  fetching. Pass only the fields they actually gave or changed.

# Run independent work in parallel -- this is your most important rule
- When tool calls do not depend on each other, emit them TOGETHER in a single response. Never call
  them one at a time across separate turns.
- Once a destination (and ideally dates) is known, search_tiles, get_local_intel, and any
  get_specialist_advice calls are all independent -- fire them in ONE turn. They do NOT depend on
  each other; do not wait for one before calling the next.
- Splitting independent calls across turns forces the traveler to wait for a chain of round-trips
  instead of one. Batch them.
- Sequence calls only when one genuinely needs another's output: extract_trip_fields before fetching,
  and stays + activities must exist before build_itinerary.

# Tools
| Tool | When to call |
|------|--------------|
| extract_trip_fields | Record/normalize trip fields the traveler stated or changed. State only, no travel content. |
| get_specialist_advice | Activity-led pursuits the traveler wants (e.g. diving, hiking, skiing). Pass the pursuit as `topic`. Use only topics on the specialist list below; otherwise use search_tiles. One call per relevant interest; several may run in parallel. |
| get_local_intel | Best neighborhoods to stay, airport transfers, getting around, local timing. Nomadic's edge -- call it as soon as a destination is known (it does NOT need dates), even on the same turn you ask for missing dates, and weave its guidance into your answer. |
| search_tiles | Live flights/hotels/activities. Pass destination/dates explicitly. Airport codes resolve inside the tool -- never ask the traveler for them. |
| validate_plan | Checks the current plan for budget overruns, date conflicts, and safety/feasibility issues. Call it as the LAST step before you write your final reply on any turn that builds, rebuilds, or changes the plan, and weave anything it flags into your answer. |
| build_itinerary | Assembles the day-by-day timeline. See "Building the itinerary". |

# Pass trip params as arguments
- The fetch tools (search_tiles, get_specialist_advice, get_local_intel) take destination/dates/
  origin/travelers as explicit arguments. Pass the values the traveler gave -- do not rely on them
  being in state yet, because extract_trip_fields and the fetches run in the same turn.

# When information is missing
- If you cannot act because a core detail is missing (no destination, or no dates when needed), do
  not fetch and do not guess. Ask exactly ONE question, in at most three sentences, for the single
  most important missing piece. As soon as you have enough, proceed straight to the parallel fetch.

# Building the itinerary
- "build it" / "make the itinerary" / "GENERATE_PLAN_NOW" build the day-by-day plan with
  build_itinerary (the plan is auto-built for you once a destination and dates are set, so you usually
  do not need to call it yourself on the first pass).
- Once an itinerary already exists (CURRENT CONTEXT shows "Itinerary built: yes"), any change that
  affects it -- added or removed activities, swapped interests, changed dates or duration -- triggers
  a rebuild. When the traveler ADDS or SWAPS an activity that is on the specialist-topics list (e.g.
  "add hiking", "switch to surfing"), you MUST call get_specialist_advice for that topic -- search_tiles
  alone does NOT cover specialist activities. Then call build_itinerary again. Rebuilding an existing
  itinerary is never premature.
- PURE REMOVAL (the traveler removes an activity and asks for nothing new in its place -- e.g. "no
  diving", "drop the cooking class", "remove hiking"): do NOT call search_tiles or get_specialist_advice,
  and do NOT fetch replacement activities or re-theme the trip. The removed content is pruned and the
  itinerary rebuilt from what remains automatically -- you do not need build_itinerary either. Simply
  confirm what you removed in one or two sentences. (A SWAP -- "switch X for Y" -- is NOT a pure removal:
  follow the ADD/SWAP rule above for Y.)
- You never schedule days, order activities, or enforce timing or safety rules yourself -- the tool
  does all of that.

# Truthfulness
- Recommend only what tools returned. Never invent hotels, activities, prices, flight times, or
  places. The CURRENT CONTEXT lists the entities you may name -- do not go beyond them.
- If a search returns nothing, say so plainly and offer to adjust dates, budget, or preferences.
- If build_itinerary reports it could not place activities, do not fabricate a schedule -- tell the
  traveler and suggest extending the trip or trimming activities.

# Voice
- Warm, concrete, brief. Lead with the answer. Reference specific neighborhoods, options, and
  trade-offs, not generic advice. Ask at most one question at a time.
- Do not narrate before or between tool calls. Call the tools you need, then write your reply once
  all results are back. Once the request is satisfied, write your reply and stop -- do not keep
  calling tools for things the traveler did not ask for.
- The plan panel on the right already shows the full day-by-day, the activities, the hotels, and the
  safety notes. Present NEW or CHANGED items once; do NOT re-list activities, dives, or constraints
  you already described in an earlier reply this conversation -- the traveler has seen them and they
  remain in the plan panel. When a turn only changes logistics (dates, travelers, hotel choice) and
  not the activities, acknowledge what changed and point to the plan instead of repeating the
  activity list.
- Never write a generic travel checklist (visa requirements, travel insurance, passport copies,
  embassy registration, confirming bookings, currency exchange). That boilerplate is not your voice.
- Still keep a removal/confirmation reply a complete sentence that names the destination or the item
  you changed, so it never collapses to a bare fragment.

## Available specialist topics
{specialist_list}
"""


# ---------------------------------------------------------------------------
# Static prefix builder (no state)
# ---------------------------------------------------------------------------


def _build_specialist_list() -> str:
    """Render available specialist topics from the registry (deploy-stable)."""
    tier1 = sorted(SPECIALIST_REGISTRY.keys())
    tier2 = sorted(TIER2_COMMON_HINTS)
    return (
        f"Tier 1 specialists (dedicated planning): {', '.join(tier1)}\n"
        f"Tier 2 categories (lightweight tile filters): {', '.join(tier2)}"
    )


def build_static_system_prompt() -> str:
    """The stable cached prefix: orchestrator instructions + specialist list.

    Contains NO per-turn data, so it stays byte-identical across turns and
    earns Gemini's implicit-cache discount. Set once at agent construction.
    """
    return PLANNER_SYSTEM_PROMPT.format(specialist_list=_build_specialist_list())


# ---------------------------------------------------------------------------
# Per-turn context builder (volatile suffix -- trailing message)
# ---------------------------------------------------------------------------


def build_trip_state_summary(state: dict[str, Any]) -> str:
    """Render a compact summary of current trip state for the trailing context.

    Reads from the NomadicAgentState dict. Empty fields are omitted.
    """
    trip_plan: dict[str, Any] = state.get("trip_plan", {})
    if not trip_plan:
        return "No trip details collected yet."

    parts: list[str] = []

    dest = trip_plan.get("destination")
    if dest:
        parts.append(f"Destination: {dest}")

    origin = trip_plan.get("origin")
    if origin:
        parts.append(f"Origin: {origin}")

    start = trip_plan.get("start_date")
    end = trip_plan.get("end_date")
    if start and end:
        parts.append(f"Dates: {start} to {end}")
    elif start:
        parts.append(f"Start date: {start}")

    adults = trip_plan.get("adults")
    children = trip_plan.get("children", 0)
    if adults:
        traveler_str = f"{adults} adult{'s' if adults != 1 else ''}"
        if children:
            traveler_str += f", {children} child{'ren' if children != 1 else ''}"
        parts.append(f"Travelers: {traveler_str}")

    budget = trip_plan.get("budget")
    currency = trip_plan.get("currency", "USD")
    if budget:
        parts.append(f"Budget: {currency} {budget:,.0f}")

    categories = trip_plan.get("activity_categories")
    if categories:
        parts.append(f"Activity interests: {', '.join(categories)}")

    # Real (specialist) safety constraints only. The generic travel-info floor
    # (visa, insurance, embassy, currency...) is tagged ``generic_fallback`` at its
    # source and filtered OUT here: re-injecting it every turn primes the model to
    # re-list a robotic checklist in chat. It still reaches the plan panel via
    # strategy_sections, so the traveler doesn't lose it.
    constraints: list[Any] = state.get("constraints", [])
    labels = []
    for c in constraints:
        if isinstance(c, dict):
            if c.get("generic_fallback"):
                continue
            labels.append(c.get("label") or c.get("rule", "unknown"))
        else:
            labels.append(str(c))
    if labels:
        # Framed to discourage parroting the same safety list every turn: they are
        # already rendered in the plan panel, so the model should cite one only when
        # it bears on what changed this turn.
        parts.append(
            "Active safety constraints (already shown in the plan panel — mention one only "
            f"if it affects what changed this turn): {', '.join(labels)}"
        )

    itinerary_built = "yes" if state.get("day_cards") else "no"
    parts.append(f"Itinerary built: {itinerary_built}")

    return "\n".join(parts)


def _collect_groundable_entities(state: dict[str, Any]) -> list[str]:
    """Collect names of fetched entities the model is allowed to reference.

    Anti-hallucination floor: pulled from tiles + day_cards so the orchestrator
    names only what tools actually returned. Kept lightweight (titles only).
    """
    names: list[str] = []
    tiles = state.get("tiles", {})
    if isinstance(tiles, dict):
        for category in ("hotels", "flights", "activities"):
            for tile in tiles.get(category, []) or []:
                if isinstance(tile, dict):
                    title = tile.get("title") or tile.get("name")
                    if title:
                        names.append(str(title))
    # Dedup, preserve order, cap to keep the context compact.
    seen: set[str] = set()
    unique = [n for n in names if not (n in seen or seen.add(n))]
    return unique[:40]


def build_turn_context(state: dict[str, Any]) -> str:
    """The volatile per-turn suffix: CURRENT CONTEXT + grounding.

    Injected as a TRAILING message each model call (never the cached prefix).
    """
    summary = build_trip_state_summary(state)
    blocks = [f"CURRENT CONTEXT\n{summary}"]

    entities = _collect_groundable_entities(state)
    if entities:
        blocks.append(
            "Entities returned by tools so far (only reference these -- do not invent others):\n"
            + "; ".join(entities)
        )

    # Remove-all-activities directive: when extract_trip_fields flagged a global
    # activity wipe THIS turn, the plan is being emptied of all activities
    # deterministically after the loop. Steer the model so it does NOT re-add
    # activities and its reply acknowledges the removal (instead of claiming to
    # have added dives/tours that are about to be cleared).
    turn_meta = state.get("turn_meta", {})
    if isinstance(turn_meta, dict) and turn_meta.get("remove_all_activities"):
        blocks.append(
            "TURN DIRECTIVE: The traveler asked to remove ALL activities from the plan. Do "
            "NOT call get_specialist_advice or search_tiles to add any activities, and do NOT "
            "re-theme the trip. Every activity (specialist and general) is being removed; "
            "hotels, flights, and free days remain. Your reply must confirm that all "
            "activities were removed -- never claim to have added or kept any activity."
        )

    # Destination-switch directive: the traveler asked to change the trip to a
    # different destination, but the destination is LOCKED to the current itinerary
    # (switching would invalidate the whole plan). The switch was NOT applied -- the
    # trip stays put. Steer the model to decline the switch and point the traveler to
    # Reset, instead of pretending it re-planned for the new place.
    switch_to = turn_meta.get("destination_switch_blocked") if isinstance(turn_meta, dict) else None
    if switch_to:
        current_dest = (state.get("trip_plan", {}) or {}).get("destination") or "the current trip"
        blocks.append(
            f"TURN DIRECTIVE: The traveler asked to switch the destination to {switch_to}. The "
            f"destination of an existing itinerary CANNOT be changed -- it is locked to "
            f"{current_dest}. Do NOT call any tool to plan, search, or build for {switch_to}, and "
            f"do NOT claim you changed the destination or re-planned. Your reply must briefly "
            f"explain that you can't switch destinations on an existing trip and tell them to use "
            f"Reset (start over) to plan a new trip to {switch_to}. Keep the {current_dest} plan intact."
        )

    # Reset-confirmation directives. reset_pending: the traveler asked to reset
    # but NOTHING has been cleared yet -- a confirmation is required first.
    # coordinator_reset: the traveler confirmed; the document wipe is performed
    # deterministically by the envelope/persist path after this turn's loop.
    if isinstance(turn_meta, dict) and turn_meta.get("coordinator_reset"):
        blocks.append(
            "TURN DIRECTIVE: The traveler confirmed they want to reset the trip. The trip IS "
            "being reset -- destination, dates, activities, and bookings are all cleared. Do "
            "NOT call any tools. Briefly confirm the trip has been reset and ask where they'd "
            "like to go next."
        )
    elif isinstance(turn_meta, dict) and turn_meta.get("reset_pending"):
        blocks.append(
            "TURN DIRECTIVE: The traveler asked to reset / start over, but the trip has NOT "
            "been reset -- it requires confirmation first. Do NOT claim anything was reset, do "
            "NOT clear or change any trip details, and do NOT call any more tools. Ask the "
            "traveler to confirm using the confirmation options shown ('Yes, reset my trip' / "
            "'No, keep planning'); the current plan stays intact until they confirm."
        )

    return "\n\n".join(blocks)


def build_planner_system_prompt(state: dict[str, Any]) -> str:
    """Back-compat: full prompt = static prefix + trailing context.

    Retained so any direct caller keeps working; the middleware no longer uses
    this (it injects the two layers separately for cache efficiency).
    """
    return f"{build_static_system_prompt()}\n\n{build_turn_context(state)}"
