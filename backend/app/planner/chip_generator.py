"""Suggestion chip generator — extracted from middleware.py.

Provides template-based suggestion chip generation that does not depend
on GraphState, only on a plain ``dict[str, Any]`` agent state.

Public API
----------
- _generate_chips_from_state(state)
- _chip(message, chip_type, category, icon, ...)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def _generate_chips_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate template-based suggestion chips from agent state.

    This is a lightweight chip generator for the agent path that does
    not depend on GraphState.  It produces 1-3 actionable chips based on
    what data is available in the current state.
    """
    trip_plan: dict[str, Any] = state.get("trip_plan", {})
    tiles: dict[str, Any] = state.get("tiles", {})
    turn_meta: dict[str, Any] = state.get("turn_meta", {})
    day_cards: list = state.get("day_cards", [])

    chips: list[dict[str, Any]] = []
    dest = trip_plan.get("destination", "")
    start_date = trip_plan.get("start_date", "")
    end_date = trip_plan.get("end_date", "")
    categories = trip_plan.get("activity_categories", [])

    # Post-validation: if blocking violations exist, suggest fixes
    validation = turn_meta.get("validation_result", {})
    if validation.get("blocking_count", 0) > 0:
        violations = validation.get("violations", [])
        for v in violations[:2]:
            action = v.get("suggested_action")
            if action:
                chips.append(
                    {
                        "message": action,
                        "action_type": "send_message",
                        "action_target": None,
                        "chip_type": "cta",
                        "category": "fix_violation",
                        "icon": "alert-triangle",
                    }
                )
        if len(chips) < 3:
            violation_type = violations[0].get("code", "") if violations else ""
            if "DATE" in violation_type or "DURATION" in violation_type:
                chips.append(
                    _chip(
                        "Adjust dates",
                        "cta",
                        "fix_violation",
                        "calendar",
                        action_type="open_pill",
                        action_target="dates",
                    )
                )
            elif "BUDGET" in violation_type or "SPEND" in violation_type:
                chips.append(
                    _chip(
                        "Adjust budget",
                        "cta",
                        "fix_violation",
                        "banknote",
                        action_type="open_pill",
                        action_target="budget",
                    )
                )
            else:
                chips.append(
                    _chip(
                        "Change activities",
                        "cta",
                        "fix_violation",
                        "compass",
                        action_type="open_pill",
                        action_target="activities",
                    )
                )
        return chips[:3]

    # Post-itinerary: refinement chips (covers both build turn AND subsequent S3 turns)
    if day_cards and dest and start_date:
        origin = trip_plan.get("origin", "")

        chips = []
        chips.append(
            _chip(
                "Browse activities",
                "follow_up",
                "browse",
                "search",
                action_type="open_pill",
                action_target="activities",
            )
        )
        if not origin:
            chips.append(
                _chip(
                    "Add departure city",
                    "follow_up",
                    "core_fields",
                    "plane",
                    action_type="open_pill",
                    action_target="origin",
                )
            )
        else:
            chips.append(
                _chip(
                    "Change hotel",
                    "follow_up",
                    "stays",
                    "building",
                    action_type="open_pill",
                    action_target="stays",
                )
            )
        budget = trip_plan.get("budget")
        if not budget:
            chips.append(
                _chip(
                    "Set budget",
                    "follow_up",
                    "core_fields",
                    "banknote",
                    action_type="open_pill",
                    action_target="budget",
                )
            )
        return chips[:3]

    # Has tiles but no itinerary yet: suggest building
    if tiles and (tiles.get("flights") or tiles.get("hotels") or tiles.get("activities")):
        origin = trip_plan.get("origin", "")
        if dest and start_date and end_date and not categories:
            chips.append(
                _chip(
                    "Choose activities",
                    "cta",
                    "core_fields",
                    "compass",
                    action_type="open_pill",
                    action_target="activities",
                )
            )
            if not origin:
                chips.append(
                    _chip(
                        "Add departure city",
                        "cta",
                        "core_fields",
                        "plane",
                        action_type="open_pill",
                        action_target="origin",
                    )
                )
            else:
                chips.append(
                    _chip(
                        "Set budget",
                        "follow_up",
                        "core_fields",
                        "banknote",
                        action_type="open_pill",
                        action_target="budget",
                    )
                )
            chips.append(
                _chip(
                    "Set travelers",
                    "follow_up",
                    "core_fields",
                    "users",
                    action_type="open_pill",
                    action_target="travelers",
                )
            )
            return chips[:3]

        if dest and start_date and end_date:
            chips.append(_chip("Build my itinerary", "cta", "progression", "calendar"))
        chips.append(
            _chip(
                "Browse activities",
                "follow_up",
                "browse",
                "search",
                action_type="open_pill",
                action_target="activities",
            )
        )
        if len(chips) < 3 and categories:
            chips.append(
                _chip(
                    f"Refine {categories[0].lower()} plan",
                    "cta",
                    "specialist",
                    "compass",
                )
            )
        elif len(chips) < 3:
            chips.append(
                _chip(
                    "Get local tips",
                    "follow_up",
                    "local_intel",
                    "map-pin",
                )
            )
        return chips[:3]

    # Has destination but missing dates
    if dest and not start_date:
        today = date.today()
        # Next weekend
        days_to_sat = (5 - today.weekday()) % 7 or 7
        sat = today + timedelta(days=days_to_sat)
        wk1_start = sat
        wk1_end = sat + timedelta(days=6)
        # Next month, first full week
        first_of_next = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        wk2_start = first_of_next
        wk2_end = first_of_next + timedelta(days=6)
        # Mid next month

        def _fmt(d: date) -> str:
            return d.strftime("%b %-d")

        chips.append(
            _chip(
                f"{_fmt(wk1_start)} - {_fmt(wk1_end)}",
                "cta",
                "date_prompt",
                "calendar",
            )
        )
        chips.append(
            _chip(
                f"{_fmt(wk2_start)} - {_fmt(wk2_end)}",
                "cta",
                "date_prompt",
                "calendar",
            )
        )
        chips.append(
            _chip(
                "Set dates",
                "cta",
                "date_prompt",
                "calendar",
                action_type="open_pill",
                action_target="dates",
            )
        )
        return chips[:3]

    # Has destination and dates but no activities
    if dest and start_date and not categories:
        origin = trip_plan.get("origin", "")
        chips.append(
            _chip(
                "Choose activities",
                "cta",
                "core_fields",
                "compass",
                action_type="open_pill",
                action_target="activities",
            )
        )
        if not origin:
            chips.append(
                _chip(
                    "Add departure city",
                    "cta",
                    "core_fields",
                    "plane",
                    action_type="open_pill",
                    action_target="origin",
                )
            )
        else:
            chips.append(
                _chip(
                    "Set budget",
                    "follow_up",
                    "core_fields",
                    "banknote",
                    action_type="open_pill",
                    action_target="budget",
                )
            )
        chips.append(
            _chip(
                "Set travelers",
                "follow_up",
                "core_fields",
                "users",
                action_type="open_pill",
                action_target="travelers",
            )
        )
        return chips[:3]

    # No destination — open core field pills
    if not dest:
        chips.append(
            _chip(
                "Pick a destination",
                "cta",
                "core_fields",
                "map-pin",
                action_type="open_pill",
                action_target="destination",
            )
        )
        chips.append(
            _chip(
                "Choose dates first",
                "follow_up",
                "date_prompt",
                "calendar",
                action_type="open_pill",
                action_target="dates",
            )
        )
        chips.append(
            _chip(
                "Set travelers",
                "follow_up",
                "core_fields",
                "users",
                action_type="open_pill",
                action_target="travelers",
            )
        )
        return chips[:3]

    # Specialist suggestions based on detected categories
    if dest and categories:
        for cat in categories[:2]:
            chips.append(
                _chip(
                    f"Refine {cat} plan",
                    "cta",
                    "specialist",
                    "compass",
                )
            )

    # Local intel suggestion
    if dest and len(chips) < 3:
        chips.append(_chip("Get local tips", "cta", "local_intel", "map-pin"))

    # ── INVARIANT: every chip must be actionable ──────────────────────
    chips = [
        c
        for c in chips
        if c.get("action_type") in ("open_pill", "trigger_action")
        or (c.get("action_type") == "send_message" and c.get("chip_type") in ("cta", "follow_up"))
    ]

    if len(chips) < 3 and dest and categories:
        existing = {c.get("message") for c in chips}
        backfill = f"Refine {categories[0].lower()} plan"
        if backfill not in existing:
            chips.append(_chip(backfill, "cta", "specialist", "compass"))

    return chips[:3]


def _chip(
    message: str,
    chip_type: str,
    category: str,
    icon: str,
    action_type: str = "send_message",
    action_target: str | None = None,
) -> dict[str, Any]:
    """Helper to build a suggestion chip payload."""
    return {
        "message": message,
        "action_type": action_type,
        "action_target": action_target,
        "chip_type": chip_type,
        "category": category,
        "icon": icon,
    }
