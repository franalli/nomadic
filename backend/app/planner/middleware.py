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

    updates: dict[str, Any] = {"trip_plan": trip_plan, "trip_settings": trip_settings}

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

    return {"tiles": tiles}


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

    return updates


def _merge_validation(state: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Store validate_plan violations/warnings in turn_meta."""
    turn_meta = dict(state.get("turn_meta", {}))
    turn_meta["validation_result"] = {
        "valid": result.get("valid", False),
        "violations": result.get("violations", []),
        "warnings": result.get("warnings", []),
        "blocking_count": result.get("blocking_count", 0),
    }
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

        # Update turn_meta counters
        turn_meta = dict(state_dict.get("turn_meta", {}))
        turn_meta["tool_call_count"] = turn_meta.get("tool_call_count", 0) + 1
        tools_called = list(turn_meta.get("tools_called", []))
        tools_called.append(tool_name)
        turn_meta["tools_called"] = tools_called
        state_updates["turn_meta"] = turn_meta

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
            "[TurnLifecycleMiddleware] Tool %s complete (call #%d), state keys updated: %s",
            tool_name,
            turn_meta["tool_call_count"],
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
            chips.append(
                {
                    "message": "Build my itinerary",
                    "action_type": "send_message",
                    "action_target": None,
                    "chip_type": "cta",
                    "category": "progression",
                    "icon": "calendar",
                }
            )
        if tiles.get("hotels"):
            chips.append(
                {
                    "message": "Show me hotel options",
                    "action_type": "send_message",
                    "action_target": None,
                    "chip_type": "suggestion",
                    "category": "tiles",
                    "icon": "building",
                }
            )
        if tiles.get("flights"):
            chips.append(
                {
                    "message": "Compare flight options",
                    "action_type": "send_message",
                    "action_target": None,
                    "chip_type": "suggestion",
                    "category": "tiles",
                    "icon": "plane",
                }
            )
        return chips[:3]

    # Has destination but missing dates or other core fields
    if dest and not start_date:
        chips.append(
            {
                "message": f"When are you planning to visit {dest}?",
                "action_type": "send_message",
                "action_target": None,
                "chip_type": "question",
                "category": "core_fields",
                "icon": "calendar",
            }
        )
    elif dest and start_date and not categories:
        chips.append(
            {
                "message": f"What activities interest you in {dest}?",
                "action_type": "send_message",
                "action_target": None,
                "chip_type": "question",
                "category": "core_fields",
                "icon": "compass",
            }
        )
    elif not dest:
        chips.append(
            {
                "message": "Where would you like to go?",
                "action_type": "send_message",
                "action_target": None,
                "chip_type": "question",
                "category": "core_fields",
                "icon": "map-pin",
            }
        )

    # Specialist suggestions based on detected categories
    if dest and categories:
        for cat in categories[:2]:
            chips.append(
                {
                    "message": f"Tell me about {cat} in {dest}",
                    "action_type": "send_message",
                    "action_target": None,
                    "chip_type": "suggestion",
                    "category": "specialist",
                    "icon": "compass",
                }
            )

    # Local intel suggestion
    if dest and len(chips) < 3:
        chips.append(
            {
                "message": f"What should I know about {dest}?",
                "action_type": "send_message",
                "action_target": None,
                "chip_type": "suggestion",
                "category": "local_intel",
                "icon": "info",
            }
        )

    return chips[:3]


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
