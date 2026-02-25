"""
Middleware suite for the create_agent-based planner.

Contains four middleware classes that plug into the LangChain AgentMiddleware
protocol.  Applied in order:

1. ModelSelectionMiddleware  -- upgrades model for complex planning turns
2. DynamicPromptMiddleware   -- injects per-turn system prompt from state
3. TurnLifecycleMiddleware   -- resets turn_meta; merges tool results into state
4. SuggestionChipMiddleware  -- generates suggestion chips after final response

All middleware use the immutable ``override()`` pattern on requests and return
state updates via ``Command`` or ``ExtendedModelResponse`` where needed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, timedelta
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
from app.planner.prompts.planner import build_planner_system_prompt

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
    """Injects a per-turn system prompt built from current agent state.

    On every model call the middleware reads ``request.state`` to obtain
    the live ``trip_plan``, ``constraints``, and other context fields, then
    rebuilds the system prompt via ``build_planner_system_prompt`` and
    overrides the request's system message.  This ensures the LLM always
    sees the latest trip state instead of a stale initial prompt.
    """

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable,
    ) -> ModelResponse | AIMessage | ExtendedModelResponse:
        # Build the dynamic prompt from whatever state is available
        state_dict: dict[str, Any] = {}
        if request.state is not None:
            if hasattr(request.state, "get"):
                state_dict = dict(request.state)
            elif isinstance(request.state, dict):
                state_dict = request.state

        dynamic_prompt = build_planner_system_prompt(state_dict)

        # Override the system message on the request (immutable pattern)
        updated_request = request.override(
            system_message=SystemMessage(content=dynamic_prompt),
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


def _short_date(iso_date: str) -> str:
    """Format YYYY-MM-DD as 'Mon D'; pass through on parse failure."""
    try:
        from datetime import datetime

        return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%b %-d")
    except (TypeError, ValueError):
        return str(iso_date)


def _get_turn_steps(turn_meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a mutable list of turn step entries."""
    raw_steps = turn_meta.get("turn_steps", [])
    return list(raw_steps) if isinstance(raw_steps, list) else []


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
    raw_turn_meta = state.get("turn_meta", {})
    existing_steps = _get_turn_steps(raw_turn_meta) if isinstance(raw_turn_meta, dict) else []

    # Detect destination change -- if the user switches destination, all
    # strategy_sections, tiles, day_cards, and constraints from the old
    # destination are stale and must be cleared.
    _destination_changed = False
    if "destination" in changed:
        old_dest = trip_plan.get("destination", "")
        new_dest = result.get("destination", "")
        if old_dest and new_dest and old_dest.lower().strip() != new_dest.lower().strip():
            _destination_changed = True

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

    # Derive end_date from start_date + duration_days when end_date is missing
    if (
        trip_plan.get("start_date")
        and trip_plan.get("duration_days")
        and not trip_plan.get("end_date")
    ):
        try:
            from datetime import datetime, timedelta

            sd = datetime.strptime(trip_plan["start_date"], "%Y-%m-%d")
            ed = sd + timedelta(days=trip_plan["duration_days"] - 1)
            trip_plan["end_date"] = ed.strftime("%Y-%m-%d")
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

    # Settings fields must persist in nested settings objects.
    trip_settings = _normalize_trip_settings(dict(state.get("trip_settings", {})))
    flight_settings = trip_settings.get("flight_settings", {})
    flight_settings = dict(flight_settings) if isinstance(flight_settings, dict) else {}
    hotel_settings = trip_settings.get("hotel_settings", {})
    hotel_settings = dict(hotel_settings) if isinstance(hotel_settings, dict) else {}
    activity_settings = trip_settings.get("activity_settings", {})
    activity_settings = dict(activity_settings) if isinstance(activity_settings, dict) else {}

    # Merge activity day preferences (e.g., {"hiking": 4, "diving": 2})
    raw_day_prefs = result.get("activity_day_preferences")
    if raw_day_prefs and isinstance(raw_day_prefs, str):
        try:
            parsed_prefs = json.loads(raw_day_prefs)
            if isinstance(parsed_prefs, dict):
                existing_prefs = activity_settings.get("day_preferences", {})
                if not isinstance(existing_prefs, dict):
                    existing_prefs = {}
                existing_prefs.update({k.lower().strip(): int(v) for k, v in parsed_prefs.items()})
                activity_settings["day_preferences"] = existing_prefs
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

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

    # Auto-upgrade flights to "suggested" when origin is newly set
    origin_just_set = False
    if "origin" in changed and trip_plan.get("origin"):
        bt = trip_settings.get("booking_types", {})
        if not isinstance(bt, dict):
            bt = {}
        if bt.get("flights", "off") == "off":
            bt["flights"] = "suggested"
            trip_settings["booking_types"] = bt
            origin_just_set = True

    # Auto-upgrade activities to "suggested" when categories are explicitly set.
    if "activity_categories" in changed:
        categories = trip_plan.get("activity_categories", [])
        if isinstance(categories, list) and categories:
            bt = trip_settings.get("booking_types", {})
            if not isinstance(bt, dict):
                bt = {}
            if bt.get("activities", "off") == "off":
                bt["activities"] = "suggested"
                trip_settings["booking_types"] = bt

    # When activity categories changed via chat (without destination change),
    # clear stale day_cards and activity tiles so auto-build re-runs.
    if "activity_categories" in changed and not _destination_changed:
        _existing_tiles = dict(state.get("tiles", {}))
        _existing_tiles["activities"] = []
        _cat_clear_updates: dict[str, Any] = {
            "day_cards": [],
            "tiles": _existing_tiles,
        }
        logger.info(
            "[_merge_trip_fields] Categories changed to %s — cleared day_cards + activity tiles",
            trip_plan.get("activity_categories", []),
        )
        _verify_tiles = _cat_clear_updates.get("tiles", {})
        logger.info(
            "[GUARD:TILE_CLEAR:MW] activities_after=%d day_cards_after=%d",
            len(_verify_tiles.get("activities", [])),
            len(_cat_clear_updates.get("day_cards", [])),
        )
    else:
        _cat_clear_updates = {}

    updates: dict[str, Any] = {
        "trip_plan": trip_plan,
        "trip_settings": trip_settings,
        **_cat_clear_updates,
    }

    turn_meta_updates: dict[str, Any] = {"fields_changed": sorted(changed)}
    step_entries: list[dict[str, str]] = []

    summary_parts: list[str] = []
    if "destination" in changed and trip_plan.get("destination"):
        summary_parts.append(str(trip_plan.get("destination")))

    if "start_date" in changed or "end_date" in changed:
        start = trip_plan.get("start_date")
        end = trip_plan.get("end_date")
        if start and end:
            summary_parts.append(f"{_short_date(start)}-{_short_date(end)}")
        elif start:
            summary_parts.append(f"from {_short_date(start)}")

    if "adults" in changed or "children" in changed:
        adults = trip_plan.get("adults")
        children = trip_plan.get("children", 0)
        traveler_parts: list[str] = []
        if adults is not None:
            traveler_parts.append(f"{adults} adult{'s' if adults != 1 else ''}")
        if children:
            traveler_parts.append(f"{children} child{'ren' if children != 1 else ''}")
        if traveler_parts:
            summary_parts.append(", ".join(traveler_parts))

    if "budget" in changed:
        budget = trip_plan.get("budget")
        if isinstance(budget, (int, float)):
            summary_parts.append(f"${int(budget):,} budget")

    if "origin" in changed and trip_plan.get("origin"):
        summary_parts.append(f"from {trip_plan.get('origin')}")

    if "activity_categories" in changed:
        categories = trip_plan.get("activity_categories", [])
        if isinstance(categories, list) and categories:
            summary_parts.append(", ".join(str(cat) for cat in categories))

    if summary_parts:
        step_entries.append({"type": "trip_update", "summary": " · ".join(summary_parts)})

    settings_parts: list[str] = []
    if "hotel_min_stars" in changed:
        stars = hotel_settings.get("min_stars")
        if isinstance(stars, (int, float)) and stars > 0:
            settings_parts.append(f"{int(stars)}-star hotels")
        elif stars == 0:
            settings_parts.append("any hotel rating")
    if "flight_direct_only" in changed:
        settings_parts.append(
            "direct flights only" if flight_settings.get("direct_only") else "connections allowed"
        )
    if "flight_cabin_class" in changed:
        cabin = flight_settings.get("cabin_class")
        if cabin:
            settings_parts.append(f"{str(cabin).replace('_', ' ')} class")
    if "skill_level" in changed:
        level = activity_settings.get("skill_level")
        if level:
            settings_parts.append(f"{level} skill level")
    if settings_parts:
        step_entries.append({"type": "preference", "summary": " · ".join(settings_parts)})

    if _destination_changed and trip_plan.get("destination"):
        step_entries.append(
            {
                "type": "destination_change",
                "summary": f"Switched to {trip_plan.get('destination')}",
            }
        )

    if step_entries:
        turn_meta_updates["turn_steps"] = existing_steps + step_entries

    if origin_just_set:
        turn_meta_updates["origin_just_set"] = True

    # When destination changed, clear stale data from the previous destination.
    if _destination_changed:
        updates["strategy_sections"] = []
        updates["tiles"] = {}
        updates["day_cards"] = []
        updates["constraints"] = []
        logger.info(
            "[_merge_trip_fields] Destination changed -- cleared stale strategy_sections, "
            "tiles, day_cards, and constraints",
        )

    # Auto-run day preference capacity check after extraction.
    # This runs deterministically in middleware (no agent decision needed)
    # so constraint violations surface reliably in the SSE complete event.
    day_prefs = activity_settings.get("day_preferences", {})
    if (
        isinstance(day_prefs, dict)
        and day_prefs
        and trip_plan.get("start_date")
        and trip_plan.get("end_date")
    ):
        from app.planner.nodes.constraint_guard import check_day_preference_capacity

        day_pref_violations = check_day_preference_capacity(
            start_date=trip_plan["start_date"],
            end_date=trip_plan["end_date"],
            day_prefs=day_prefs,
            activity_categories=trip_plan.get("activity_categories", []),
        )
        if day_pref_violations:
            v = day_pref_violations[0]
            violation = v.to_dict()
            violation["field"] = "end_date"
            turn_meta_updates["validation_result"] = {
                "valid": False,
                "violations": [violation],
                "warnings": [],
                "blocking_count": 1,
            }
            logger.info(
                "[_merge_trip_fields] DAY_PREFERENCE_EXCEEDS_CAPACITY: %s",
                v.message,
            )

    if turn_meta_updates:
        updates["turn_meta"] = turn_meta_updates

    return updates


def _merge_tiles(state: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Merge search_tiles result into the tiles dict.

    Replaces entire category arrays (flights, hotels, activities) with
    fresh results from the provider.
    """
    tiles = dict(state.get("tiles", {}))

    for category in ("flights", "hotels", "activities"):
        new_tiles = result.get(category)
        if new_tiles is not None:
            tiles[category] = new_tiles

    updates: dict[str, Any] = {"tiles": tiles}
    turn_meta = dict(state.get("turn_meta", {}))
    steps = _get_turn_steps(turn_meta)
    counts: list[str] = []
    for category in ("flights", "hotels", "activities"):
        category_tiles = result.get(category, [])
        count = len(category_tiles) if isinstance(category_tiles, list) else 0
        if count > 0:
            counts.append(f"{count} {category}")
    if counts:
        steps.append({"type": "tiles", "summary": "Found " + " · ".join(counts)})
        turn_meta["turn_steps"] = steps
        updates["turn_meta"] = turn_meta

    return updates


def _merge_specialist(state: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Merge get_specialist_advice result into strategy_sections and constraints."""
    updates: dict[str, Any] = {}

    # Append strategy section
    section = result.get("strategy_section")
    if section:
        sections = list(state.get("strategy_sections", []))
        # Replace existing section for the same topic, or append
        topic = result.get("topic", "")
        replaced = False
        for i, existing in enumerate(sections):
            if isinstance(existing, dict) and existing.get("specialist_type") == topic:
                sections[i] = section
                replaced = True
                break
        if not replaced:
            sections.append(section)
        updates["strategy_sections"] = sections

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

    topic = str(result.get("topic", "") or "").strip()
    pretty_topic = topic.replace("_", " ").title() if topic else "Specialist"
    constraint_count = len(result.get("constraints", []) or [])
    specialist_summary = f"{pretty_topic} expert consulted"
    if constraint_count > 0:
        specialist_summary += (
            f" · {constraint_count} constraint{'s' if constraint_count != 1 else ''}"
        )
    turn_meta = dict(state.get("turn_meta", {}))
    steps = _get_turn_steps(turn_meta)
    steps.append({"type": "specialist", "summary": specialist_summary})
    turn_meta["turn_steps"] = steps
    updates["turn_meta"] = turn_meta

    return updates


def _merge_local_intel(state: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Merge get_local_intel result into strategy_sections and constraints."""
    updates: dict[str, Any] = {}

    section = result.get("section")
    if section:
        sections = list(state.get("strategy_sections", []))
        # Replace existing local_expert section, or append
        replaced = False
        for i, existing in enumerate(sections):
            if isinstance(existing, dict) and existing.get("specialist_type") == "local_expert":
                sections[i] = section
                replaced = True
                break
        if not replaced:
            sections.append(section)
        updates["strategy_sections"] = sections

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

    turn_meta = dict(state.get("turn_meta", {}))
    steps = _get_turn_steps(turn_meta)
    steps.append({"type": "local_intel", "summary": "Local knowledge loaded"})
    turn_meta["turn_steps"] = steps
    updates["turn_meta"] = turn_meta

    return updates


def _merge_validation(state: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Store validate_plan violations/warnings in turn_meta."""
    turn_meta = dict(state.get("turn_meta", {}))
    violations = result.get("violations", []) or []
    blocking_count = result.get("blocking_count", 0)
    turn_meta["validation_result"] = {
        "valid": result.get("valid", False),
        "violations": violations,
        "warnings": result.get("warnings", []),
        "blocking_count": blocking_count,
    }
    turn_meta["has_blocking_violations"] = bool(blocking_count > 0)
    turn_meta["constraint_violations"] = violations

    steps = _get_turn_steps(turn_meta)
    if blocking_count > 0 and violations:
        messages = [
            str(v.get("message", "")).strip()
            for v in violations[:2]
            if isinstance(v, dict) and str(v.get("message", "")).strip()
        ]
        steps.append(
            {
                "type": "validation",
                "summary": "Validation failed" + (f" · {' · '.join(messages)}" if messages else ""),
            }
        )
    elif result.get("valid"):
        steps.append({"type": "validation", "summary": "Validation passed"})
    turn_meta["turn_steps"] = steps

    return {"turn_meta": turn_meta}


def _merge_itinerary(state: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Update day_cards from build_itinerary result."""
    updates: dict[str, Any] = {}
    day_cards = result.get("day_cards", [])
    if day_cards:
        updates["day_cards"] = day_cards

    # Also stash builder metadata in turn_meta for chip generation
    turn_meta = dict(state.get("turn_meta", {}))
    turn_meta["builder_result"] = {
        "success": result.get("success", False),
        "activities_placed": result.get("activities_placed", 0),
        "activities_dropped": result.get("activities_dropped", 0),
        "conflicts": result.get("conflicts", []),
        "warnings": result.get("warnings", []),
    }
    steps = _get_turn_steps(turn_meta)
    day_count = len(day_cards or [])
    dropped = int(result.get("activities_dropped", 0) or 0)
    if result.get("success"):
        itinerary_summary = (
            f"Built {day_count}-day itinerary" if day_count > 0 else "Built itinerary"
        )
        if dropped > 0:
            itinerary_summary += f" · {dropped} activit{'y' if dropped == 1 else 'ies'} dropped"
        steps.append({"type": "itinerary", "summary": itinerary_summary})
    elif day_count > 0:
        steps.append({"type": "itinerary", "summary": f"Built partial {day_count}-day itinerary"})
    turn_meta["turn_steps"] = steps
    updates["turn_meta"] = turn_meta
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
        """Reset turn_meta at the start of each agent turn."""
        return {
            "turn_meta": {
                "turn_started_at": time.time(),
                "tool_call_count": 0,
                "tools_called": [],
            },
        }

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

        # Update turn_meta counters — return ONLY the delta for this tool
        # call.  The _merge_turn_meta reducer concatenates tools_called
        # lists and derives tool_call_count from len(combined).
        state_updates["turn_meta"] = {"tools_called": [tool_name]}

        # Parse and merge tool-specific result (skip error ToolMessages)
        merger = _TOOL_MERGERS.get(tool_name)
        if merger is not None and isinstance(result, ToolMessage):
            parsed = _extract_tool_result(result)
            if parsed is not None and "error" not in parsed:
                try:
                    tool_updates = merger(state_dict, parsed)
                    # Merge turn_meta from tool_updates if present
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
            "[TurnLifecycleMiddleware] Tool %s complete, state keys updated: %s",
            tool_name,
            list(state_updates.keys()),
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


# ===========================================================================
# 4. SuggestionChipMiddleware
# ===========================================================================


def _generate_chips_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate template-based suggestion chips from agent state.

    This is a lightweight chip generator for the agent path that does
    not depend on GraphState.  It produces 1-3 actionable chips based on
    what data is available in the current state.
    """
    trip_plan: dict[str, Any] = state.get("trip_plan", {})
    tiles: dict[str, Any] = state.get("tiles", {})
    turn_meta: dict[str, Any] = state.get("turn_meta", {})
    constraints: list = state.get("constraints", [])
    day_cards: list = state.get("day_cards", [])
    trip_settings: dict[str, Any] = state.get("trip_settings", {})

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
            chips.append(
                {
                    "message": "Show me what needs to change",
                    "action_type": "send_message",
                    "action_target": None,
                    "chip_type": "cta",
                    "category": "fix_violation",
                    "icon": "help-circle",
                }
            )
        return chips[:3]

    # Post-itinerary: suggest refinements
    builder_result = turn_meta.get("builder_result", {})
    if builder_result.get("success") and day_cards:
        chips.append(
            {
                "message": "Show my full itinerary",
                "action_type": "send_message",
                "action_target": None,
                "chip_type": "cta",
                "category": "itinerary",
                "icon": "calendar",
            }
        )
        if builder_result.get("activities_dropped", 0) > 0:
            chips.append(
                {
                    "message": "Add an extra day for dropped activities",
                    "action_type": "send_message",
                    "action_target": None,
                    "chip_type": "suggestion",
                    "category": "itinerary",
                    "icon": "plus-circle",
                }
            )
        if constraints:
            chips.append(
                {
                    "message": "Review safety constraints",
                    "action_type": "send_message",
                    "action_target": None,
                    "chip_type": "info",
                    "category": "constraints",
                    "icon": "shield",
                }
            )
        return chips[:3]

    # Has tiles but no itinerary yet: suggest building
    if tiles and (tiles.get("flights") or tiles.get("hotels") or tiles.get("activities")):
        if dest and start_date and end_date:
            chips.append(_chip("Build my itinerary", "cta", "progression", "calendar"))
        hotel_settings = trip_settings.get("hotel_settings", {})
        if not hotel_settings.get("min_stars"):
            chips.append(
                _chip(
                    "5-star hotels only",
                    "suggestion",
                    "preferences",
                    "star",
                    action_type="open_pill",
                    action_target="stays",
                )
            )
        flight_settings = trip_settings.get("flight_settings", {})
        if not flight_settings.get("direct_only"):
            chips.append(
                _chip(
                    "Direct flights only",
                    "suggestion",
                    "preferences",
                    "plane",
                    action_type="trigger_action",
                    action_target="set_direct_flights_only",
                )
            )
        if len(chips) < 3:
            chips.append(
                _chip(
                    "Browse activities",
                    "suggestion",
                    "preferences",
                    "compass",
                    action_type="open_pill",
                    action_target="activities",
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
        chips.append(_chip("I'm flexible on dates", "suggestion", "date_prompt", "calendar"))
        return chips[:3]

    # Has destination and dates but no activities
    if dest and start_date and not categories:
        chips.append(
            _chip(
                f"What activities in {dest}?",
                "question",
                "core_fields",
                "compass",
                action_type="open_pill",
                action_target="activities",
            )
        )
        chips.append(
            _chip(
                f"Local food and culture in {dest}",
                "suggestion",
                "specialist",
                "utensils",
            )
        )
        chips.append(_chip("Surprise me", "suggestion", "core_fields", "sparkles"))
        return chips[:3]

    # No destination
    if not dest:
        chips.append(_chip("Beach vacation", "suggestion", "destination_prompt", "sun"))
        chips.append(_chip("Mountain adventure", "suggestion", "destination_prompt", "mountain"))
        chips.append(_chip("City break in Europe", "suggestion", "destination_prompt", "building"))
        return chips[:3]

    # Specialist suggestions based on detected categories
    if dest and categories:
        for cat in categories[:2]:
            chips.append(
                _chip(
                    f"Tell me about {cat} in {dest}",
                    "suggestion",
                    "specialist",
                    "compass",
                )
            )

    # Local intel suggestion
    if dest and len(chips) < 3:
        chips.append(_chip(f"Local tips for {dest}", "suggestion", "local_intel", "info"))

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


class SuggestionChipMiddleware(AgentMiddleware):
    """Generates suggestion chips after the agent's final model response.

    When the model response contains no tool calls (i.e., it is a final
    text response to the user), this middleware generates contextual
    suggestion chips based on current state and stores them in
    ``persistent_meta.suggestion_chips``.

    Uses template-based chip generation derived from state fields -- no
    additional LLM call needed.
    """

    async def aafter_model(
        self,
        state: Any,
        runtime: Any,
    ) -> dict[str, Any] | None:
        """Generate chips after a model call if it was a final response.

        State timing assumption: ``state`` already contains the AIMessage from
        the model call that just completed (i.e. LangGraph appends the
        response to ``messages`` before invoking ``aafter_model``).  We rely
        on ``messages[-1]`` being the latest AIMessage to decide whether this
        was a final text response or a tool-calling step.
        """
        state_dict: dict[str, Any] = {}
        if state is not None:
            if isinstance(state, dict):
                state_dict = state
            elif hasattr(state, "get"):
                state_dict = dict(state)

        # Check if the last message is an AIMessage with no tool calls
        messages = state_dict.get("messages", [])
        if not messages:
            return None

        last_msg = messages[-1]
        if not isinstance(last_msg, AIMessage):
            return None

        # If model wants to call tools, skip chip generation
        if last_msg.tool_calls:
            return None

        # Generate chips from current state
        chips = _generate_chips_from_state(state_dict)

        if not chips:
            return None

        # Store in persistent_meta
        persistent_meta = dict(state_dict.get("persistent_meta", {}))
        persistent_meta["suggestion_chips"] = chips
        persistent_meta["suggestion_chip_texts"] = [c["message"] for c in chips]

        logger.debug(
            "[SuggestionChipMiddleware] Generated %d chips: %s",
            len(chips),
            [c["message"] for c in chips],
        )

        return {"persistent_meta": persistent_meta}
