"""
System prompt builder for the create_agent planner.

Constructs a dynamic system prompt by injecting:
  - Available specialist list (from specialist_registry)
  - Current trip state summary (from agent state)
"""

from __future__ import annotations

import logging
from typing import Any

from app.debug_utils import _safe_print, get_debug_mode
from app.planner.specialist_registry import SPECIALIST_REGISTRY, TIER2_COMMON_HINTS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Static prompt template
# ---------------------------------------------------------------------------

PLANNER_SYSTEM_PROMPT = """\
You are Nomadic, a trip-planning assistant with the voice of an expedition leader \
-- knowledgeable, warm, and concise (2-3 sentences per reply unless detail is needed).

## Available Specialists
{specialist_list}

## Available Tools

| Tool                     | When to call                                              |
|--------------------------|-----------------------------------------------------------|
| extract_trip_fields      | User provides or changes trip details (destination, dates, budget, activities). |
| get_specialist_advice    | Trip has an activity category that matches a specialist (diving, hiking, ...).  |
| search_tiles             | Core fields ready (destination + dates) and user wants flights/hotels/activities.|
| get_local_intel          | User EXPLICITLY asks about local tips, food, culture, transport, or safety.    |
| validate_plan            | After extraction when day preferences or constraints exist, OR before building.|
| build_itinerary          | After validate_plan passes with no blocking violations.                        |

## Tool Calling Rules
1. **Always call extract_trip_fields first** when the user mentions trip details.
2. Call get_specialist_advice **before** search_tiles when specialist categories are detected.
3. Call validate_plan **before** build_itinerary.
4. Never call build_itinerary without a successful validate_plan in the same turn.
5. If extract_trip_fields returns missing core fields (destination or dates), \
ask the user for those fields -- do not call search_tiles or build_itinerary.
6. When the user sends GENERATE_PLAN_NOW or "Build my plan":\n\
   a. If activity tiles are missing (see ⚠️ warning), call search_tiles ONCE.\n\
   b. After search_tiles returns (or if tiles already loaded), respond with a brief \
confirmation like "Your itinerary has been built!" — do NOT call validate_plan, \
build_itinerary, or get_local_intel. The system builds automatically.\n\
   c. Keep your response under 2 sentences.
7. **Do NOT call get_local_intel** during standard trip planning -- it runs automatically \
when the itinerary is built. Only call it when the user EXPLICITLY asks about local \
information (e.g., "What should I know about Bali?", "Tell me about Rome").
8. When extract_trip_fields returns activity_day_preferences (e.g., "4 days hiking"), \
**always call validate_plan** immediately to check capacity constraints. If validate_plan \
returns blocking violations, inform the user and suggest fixes -- do NOT call build_itinerary.
9. **Always call search_tiles** in the same turn after any specialist/local-intel tool \
when core fields (destination + dates) are ready and tiles have not been loaded yet. \
Never stop a turn with strategy advice but zero tiles -- the user needs bookable options.
10. **Stale tile detection**: If the Trip State shows "Activity tiles STALE", \
the loaded tiles do NOT match the user's current activity preferences. \
You MUST call search_tiles with the user's requested categories before \
calling validate_plan or build_itinerary -- even if tiles are already loaded. \
Stale tiles produce an itinerary that ignores the user's preferences.
11. When the user sends "GENERATE_PLAN_NOW" AND Trip State shows stale or missing tiles, \
rule #6a applies — call search_tiles ONCE with the requested categories, then confirm.

## Auto-Chain Workflow
When the user provides a **complete trip request** (destination + dates + activities in \
one message), run the full pipeline in a single turn. \
This does NOT apply to GENERATE_PLAN_NOW — see rule #6 instead.
1. extract_trip_fields
2. get_specialist_advice (for each detected Tier 1 specialist category)
3. search_tiles (hotels + activities)
4. validate_plan
5. build_itinerary (only if validate_plan returns no blocking violations)

Do NOT stop after specialist advice -- continue through the full pipeline. \
Travel advice is generated automatically during itinerary building -- do NOT call \
get_local_intel unless the user explicitly asks.

## Multi-Turn Chaining
When core fields (destination + dates) are already set from prior turns AND the user \
adds activity preferences, asks about things to do, or requests local info:
1. extract_trip_fields (if the user mentioned new trip details)
2. get_specialist_advice or get_local_intel (as appropriate for the topic)
3. search_tiles (always -- so the user gets real hotel and activity options)
Do NOT stop after advice or local intel. Always follow through to search_tiles \
so the itinerary builder has tiles to work with.

## Trip State
{trip_state_summary}

## Response Style
- Be specific and actionable. Suggest next steps.
- When specialist constraints exist (e.g., 24h no-fly buffer for diving), \
mention them naturally -- don't lecture.
- Use the traveler's destination and dates in your response when available.
- If the user's request is ambiguous, ask a single clarifying question.
"""


# ---------------------------------------------------------------------------
# Dynamic builders
# ---------------------------------------------------------------------------


def _build_specialist_list() -> str:
    """Render a bullet list of available specialists from the registry."""
    lines: list[str] = []

    # Tier 1: full specialists with safety/domain constraints
    for topic, cfg in sorted(SPECIALIST_REGISTRY.items()):
        constraint_count = len(cfg.hardcoded_constraints)
        constraint_note = (
            f" ({constraint_count} safety constraint{'s' if constraint_count != 1 else ''})"
            if constraint_count
            else ""
        )
        lines.append(f"- **{cfg.display_name}** ({topic}, Tier {cfg.tier}){constraint_note}")

    # Tier 2: lightweight categories (no dedicated specialist pipeline)
    tier2_sorted = sorted(TIER2_COMMON_HINTS)
    lines.append(f"- Tier 2 categories (lightweight): {', '.join(tier2_sorted)}")

    return "\n".join(lines)


def build_trip_state_summary(state: dict[str, Any]) -> str:
    """Render a human-readable summary of current trip state for prompt injection.

    Reads from the agent state dict (NomadicAgentState shape).  Missing or
    empty fields are omitted to keep the prompt compact.
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

    trip_type = trip_plan.get("trip_type")
    if trip_type:
        parts.append(f"Trip type: {trip_type}")

    # Data inventory -- tells the LLM what has/hasn't been loaded
    tiles: dict[str, Any] = state.get("tiles", {})
    tile_counts: list[str] = []
    for cat in ("flights", "hotels", "activities"):
        cat_tiles = tiles.get(cat, [])
        if isinstance(cat_tiles, list) and cat_tiles:
            tile_counts.append(f"{len(cat_tiles)} {cat}")
    if tile_counts:
        parts.append(f"Tiles loaded: {', '.join(tile_counts)}")
    elif dest and start and end:
        parts.append("Tiles loaded: NONE (search_tiles not yet called)")

    # Activity category mismatch detection — alerts agent when loaded tiles
    # don't match the user's current category preferences.
    trip_settings: dict[str, Any] = state.get("trip_settings", {})
    activity_settings: dict[str, Any] = trip_settings.get("activity_settings", {})
    requested_cats: list[str] = activity_settings.get("categories", [])

    # Activity tile status — 3 cases:
    # A) Categories requested, no tiles → MUST search (pill change just cleared them)
    # B) Categories requested, tiles exist but wrong type → STALE
    # C) Categories requested, tiles match → informational
    if requested_cats and not tiles.get("activities"):
        # Case A: cleared or never searched
        parts.append(
            f"⚠️ No activity tiles loaded — user requested: "
            f"{', '.join(requested_cats)} — MUST call search_tiles "
            f"with activity_categories={','.join(requested_cats)} before building"
        )
    elif requested_cats and tiles.get("activities"):
        # Case B/C: check category match
        loaded_cats: set[str] = set()
        for tile in tiles.get("activities", []):
            if isinstance(tile, dict):
                meta = tile.get("meta") or {}
                # source_categories carries the user semantic categories
                # that produced this tile (fixes Google primaryType mismatch)
                for sc in meta.get("source_categories", []):
                    if sc:
                        loaded_cats.add(sc.lower())
                cat = meta.get("category", "")
                if cat:
                    loaded_cats.add(cat.lower())
                specialist = meta.get("specialist_type", "")
                if specialist:
                    loaded_cats.add(specialist.lower())

        requested_set = {c.lower() for c in requested_cats}
        # W4 fix: use issubset instead of intersection — detect partial staleness
        if not loaded_cats or not requested_set.issubset(loaded_cats):
            missing = sorted(requested_set - loaded_cats)
            parts.append(
                f"⚠️ Activity tiles STALE: loaded categories={sorted(loaded_cats)}, "
                f"user requested={sorted(requested_set)}, missing={missing} "
                f"— MUST call search_tiles to refresh"
            )
        elif requested_cats:
            parts.append(f"Requested activity categories: {', '.join(requested_cats)}")
    elif requested_cats:
        parts.append(f"Requested activity categories: {', '.join(requested_cats)}")

    # Regression guard: always log category state for tracing
    if requested_cats and get_debug_mode() in ("compact", "full"):
        _loaded_act = tiles.get("activities", [])
        _loaded_count = len(_loaded_act) if isinstance(_loaded_act, list) else 0
        _safe_print(
            f"[GUARD:PROMPT_CATS] requested={requested_cats} "
            f"loaded_activity_tiles={_loaded_count} "
            f"prompt_contains_warning={'⚠️' in parts[-1] if parts else False}"
        )

    strategy_sections: list[Any] = state.get("strategy_sections", [])
    if strategy_sections:
        topics = [s.get("specialist_type", "?") for s in strategy_sections if isinstance(s, dict)]
        parts.append(f"Strategy sections: {', '.join(topics)}")

    # Constraints summary
    constraints: list[Any] = state.get("constraints", [])
    if constraints:
        labels = []
        for c in constraints:
            if isinstance(c, dict):
                labels.append(c.get("label") or c.get("rule", "unknown"))
            else:
                labels.append(str(c))
        parts.append(f"Active constraints: {', '.join(labels)}")

    if not parts:
        return "No trip details collected yet."

    return "\n".join(parts)


def build_planner_system_prompt(state: dict[str, Any]) -> str:
    """Build the full system prompt with dynamic specialist list and trip state."""
    specialist_list = _build_specialist_list()
    trip_summary = build_trip_state_summary(state)

    result = PLANNER_SYSTEM_PROMPT.format(
        specialist_list=specialist_list,
        trip_state_summary=trip_summary,
    )
    # === FULL DIAGNOSTIC — LAYER 2: SYSTEM PROMPT ===
    try:
        if get_debug_mode() in ("compact", "full"):
            _safe_print(
                f"\n[DIAG:SYSTEM_PROMPT] === Prompt Injected to LLM ===\n"
                f"  trip_state_summary:\n{trip_summary}\n"
                f"  prompt_length: {len(result)} chars"
            )
    except Exception:
        pass
    # === END DIAGNOSTIC ===
    return result
