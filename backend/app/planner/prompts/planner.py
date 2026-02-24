"""
System prompt builder for the create_agent planner.

Constructs a dynamic system prompt by injecting:
  - Available specialist list (from specialist_registry)
  - Current trip state summary (from agent state)
"""

from __future__ import annotations

import logging
from typing import Any

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
| get_local_intel          | User asks about a destination (food, culture, transport, safety tips).          |
| validate_plan            | Before presenting a final itinerary -- checks constraints and completeness.     |
| build_itinerary          | After validation passes -- assembles day-by-day cards from tiles + specialist.  |
| build_itinerary          | User sends "GENERATE_PLAN_NOW" or "Build my plan" (requires tiles loaded).     |

## Tool Calling Rules
1. **Always call extract_trip_fields first** when the user mentions trip details.
2. Call get_specialist_advice **before** search_tiles when specialist categories are detected.
3. Call validate_plan **before** build_itinerary.
4. Never call build_itinerary without a successful validate_plan in the same turn.
5. If extract_trip_fields returns missing core fields (destination or dates), \
ask the user for those fields -- do not call search_tiles or build_itinerary.
6. When the user sends "GENERATE_PLAN_NOW" or "Build my plan", skip extract_trip_fields \
and proceed directly to validate_plan -> build_itinerary (tiles must already be loaded). \
If tiles are not yet loaded, call search_tiles first.

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

    return PLANNER_SYSTEM_PROMPT.format(
        specialist_list=specialist_list,
        trip_state_summary=trip_summary,
    )
