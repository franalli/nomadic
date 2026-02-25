"""
validate_plan tool -- wraps constraint_guard + input_gates validation.

Runs input gate validation (date ranges, budget limits, same-city check)
and constraint validation (specialist constraints like no-fly buffers,
budget overruns). Optionally validates place existence (LLM-backed, cached).

When running inside a ``create_agent`` graph the ``InjectedState``
annotation auto-populates trip fields and tiles/constraints from agent
state so the LLM does not need to serialize large JSON payloads.

State mutation happens in TurnLifecycleMiddleware, not here.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from typing_extensions import Annotated

from app.planner.tools._parsing import parse_constraints_json, parse_tiles_json

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_trip_plan(
    destination: str,
    origin: str,
    start_date: str,
    end_date: str,
    adults: int,
    children: int,
    budget: float,
) -> Any:
    """Build a minimal TripPlan for gate and guard evaluation."""
    from app.planner.state.graph_state import TripPlan

    return TripPlan(
        destination=destination or None,
        origin=origin or None,
        start_date=start_date or None,
        end_date=end_date or None,
        adults=adults if adults else 1,
        children=children if children else 0,
        budget=budget if budget else None,
    )


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


@tool
async def validate_plan(
    destination: str = "",
    origin: str = "",
    start_date: str = "",
    end_date: str = "",
    adults: int = 1,
    children: int = 0,
    budget: float = 0,
    activity_categories: str = "",
    constraints_json: str = "[]",
    tiles_json: str = "{}",
    # InjectedState -- auto-populated when running inside create_agent;
    # invisible to the LLM's tool-calling schema.  Provides trip_plan,
    # tiles, and constraints from agent state so the LLM does not need
    # to pass large JSON payloads.
    state: Annotated[Optional[dict], InjectedState] = None,
) -> dict:
    """Check a trip plan for constraint violations (budget overruns, date
    conflicts, safety buffers). Call after making plan changes or adding tiles."""
    from app.planner.nodes.constraint_guard import (
        GuardViolation,
        check_budget_constraint,
        check_route_constraint,
        check_specialist_constraints,
        check_temporal_constraints,
    )
    from app.planner.nodes.input_gates import GateRegistry
    from app.planner.state.graph_state import SpecialistConstraint

    # When InjectedState is available, fill in defaults from agent state
    if state is not None:
        trip_plan: dict[str, Any] = state.get("trip_plan", {})
        destination = destination or trip_plan.get("destination", "")
        origin = origin or trip_plan.get("origin", "")
        start_date = start_date or trip_plan.get("start_date", "")
        end_date = end_date or trip_plan.get("end_date", "")
        adults = adults if adults != 1 else trip_plan.get("adults", 1)
        children = children if children != 0 else trip_plan.get("children", 0)
        budget = budget if budget != 0 else (trip_plan.get("budget", 0) or 0)

        # Pull tiles and constraints from state when not passed explicitly
        if tiles_json == "{}" and state.get("tiles"):
            try:
                tiles_json = json.dumps(state["tiles"])
            except (TypeError, ValueError):
                pass
        if constraints_json == "[]" and state.get("constraints"):
            try:
                constraints_json = json.dumps(state["constraints"])
            except (TypeError, ValueError):
                pass

    violations: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    # 1. Build TripPlan for validation
    plan = _build_trip_plan(
        destination=destination,
        origin=origin,
        start_date=start_date,
        end_date=end_date,
        adults=adults,
        children=children,
        budget=budget,
    )

    # 2. Run input gate validation (date ranges, budget limits, travelers)
    try:
        registry = GateRegistry()
        blockers, gate_warnings = registry.run_all(plan)

        for result in blockers:
            violations.append(
                {
                    "code": result.code,
                    "message": result.message,
                    "severity": "blocking",
                    "category": "input_gate",
                    "suggested_action": result.suggested_action,
                    "field": result.field,
                }
            )

        for result in gate_warnings:
            warnings.append(
                {
                    "code": result.code,
                    "message": result.message,
                    "severity": "warning",
                    "category": "input_gate",
                    "suggested_action": result.suggested_action,
                    "field": result.field,
                }
            )
    except Exception as exc:
        logger.warning("[validate_plan] Input gate validation failed: %s", exc)

    # 3. Parse tiles and constraints for guard checks
    tiles = parse_tiles_json(tiles_json)
    constraint_dicts = parse_constraints_json(constraints_json)

    # Hydrate specialist constraints onto the plan for guard evaluation
    for cd in constraint_dicts:
        try:
            constraint = SpecialistConstraint.model_validate(cd)
            plan.constraints.append(constraint)
        except Exception as exc:
            logger.warning("[validate_plan] Skipping invalid constraint: %s", exc)

    # 4. Run constraint guard checks (pure Python, no LLM)
    try:
        # Budget constraints
        guard_violations: List[GuardViolation] = []
        guard_violations.extend(check_budget_constraint(plan, tiles))

        # Temporal constraints
        guard_violations.extend(check_temporal_constraints(plan, tiles))

        # Specialist constraints (departure buffer + cross-domain).
        # NOTE: check_specialist_constraints validates against plan.constraints
        # only, not itinerary_blocks (which are empty at this pre-build stage).
        # Full itinerary-aware constraint checking happens in the builder itself.
        guard_violations.extend(check_specialist_constraints(plan, tiles))

        for v in guard_violations:
            entry = v.to_dict()
            if v.severity == "blocking":
                violations.append(entry)
            elif v.severity == "warning":
                warnings.append(entry)
            else:
                # "info" severity goes to warnings
                warnings.append(entry)
    except Exception as exc:
        logger.warning("[validate_plan] Constraint guard failed: %s", exc)

    # 5. Route validation (same-city + place existence)
    # Skip the LLM-backed place existence check when search_tiles already
    # returned results — Google Places confirming hotels/activities for a
    # destination is proof it exists.  Saves ~1s per turn.
    has_real_tiles = False
    if tiles:
        for cat in ("hotels", "activities"):
            cat_tiles = tiles.get(cat, [])
            if isinstance(cat_tiles, list) and len(cat_tiles) > 0:
                has_real_tiles = True
                break
    try:
        if has_real_tiles:
            # Only run same-city check (pure logic, no LLM)
            route_violations = []
            origin_str = (plan.origin or "").lower().strip()
            dest_str = (plan.destination or "").lower().strip()
            if origin_str and dest_str and origin_str == dest_str:
                route_violations.append(
                    GuardViolation(
                        code="SAME_CITY_ERROR",
                        message=f"Origin and destination cannot be the same ({plan.destination})",
                        severity="blocking",
                        category="route",
                        suggested_action="Please choose a different destination",
                    )
                )
            logger.debug(
                "[validate_plan] Skipped place existence check (tiles loaded for %s)",
                plan.destination,
            )
        else:
            route_violations = await check_route_constraint(plan)
        for v in route_violations:
            entry = v.to_dict()
            if v.severity == "blocking":
                violations.append(entry)
            else:
                warnings.append(entry)
    except Exception as exc:
        logger.warning("[validate_plan] Route validation failed: %s", exc)

    # 6. Day preference capacity check
    if state is not None:
        trip_settings_val: dict[str, Any] = state.get("trip_settings", {})
        activity_settings_val: dict[str, Any] = trip_settings_val.get("activity_settings", {})
        day_prefs: dict[str, int] = activity_settings_val.get("day_preferences", {})

        if day_prefs:
            from app.planner.nodes.constraint_guard import check_day_preference_capacity

            # Prefer strategy_sections; fall back to activity_categories
            strategy_secs: list = state.get("strategy_sections", [])
            cats_fallback: list[str] | None = None
            if not strategy_secs:
                # Build fallback from LLM parameter or trip_plan
                if activity_categories:
                    cats_fallback = [
                        c.strip().lower() for c in activity_categories.split(",") if c.strip()
                    ]
                if not cats_fallback:
                    tp: dict[str, Any] = state.get("trip_plan", {})
                    cats_fallback = tp.get("activity_categories", [])

            day_pref_violations = check_day_preference_capacity(
                start_date=start_date,
                end_date=end_date,
                day_prefs=day_prefs,
                strategy_sections=strategy_secs if strategy_secs else None,
                activity_categories=cats_fallback,
            )
            for v in day_pref_violations:
                entry = v.to_dict()
                entry["field"] = "end_date"
                violations.append(entry)

    # 7. Build result
    all_issues = violations + warnings
    blocking_count = sum(1 for v in all_issues if v.get("severity") == "blocking")
    is_valid = blocking_count == 0

    logger.debug(
        "[validate_plan] dest=%s valid=%s violations=%d warnings=%d blocking=%d",
        destination,
        is_valid,
        len(violations),
        len(warnings),
        blocking_count,
    )

    return {
        "valid": is_valid,
        "violations": violations,
        "warnings": warnings,
        "blocking_count": blocking_count,
    }
