"""
validate_plan tool -- wraps constraint_guard checks + GATE_THRESHOLDS bounds.

Runs input gate validation (date ranges, budget limits, traveler counts)
against ``GATE_THRESHOLDS`` and constraint validation (specialist constraints
like no-fly buffers, budget overruns). Optionally validates place existence
(LLM-backed, cached). The legacy ``GateRegistry`` class was removed from the
codebase; the bounds checks now live inline in ``_run_input_gates``.

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


def _run_input_gates(
    plan: Any,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Validate trip inputs against ``GATE_THRESHOLDS``.

    Replaces the removed ``GateRegistry``: there is no longer a gate-class
    registry in the codebase, only the ``GATE_THRESHOLDS`` constants, so the
    bounds checks live inline here. Returns ``(blockers, warnings)`` as dicts.
    """
    from datetime import date

    from app.planner.nodes.input_gate_config import GATE_THRESHOLDS

    blockers: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    def _block(code: str, message: str, field: str, action: str) -> None:
        blockers.append(
            {
                "code": code,
                "message": message,
                "severity": "blocking",
                "category": "input_gate",
                "suggested_action": action,
                "field": field,
            }
        )

    def _warn(code: str, message: str, field: str, action: str) -> None:
        warnings.append(
            {
                "code": code,
                "message": message,
                "severity": "warning",
                "category": "input_gate",
                "suggested_action": action,
                "field": field,
            }
        )

    # --- Date range ---
    start = _parse_iso_date(plan.start_date)
    end = _parse_iso_date(plan.end_date)
    if start and end:
        trip_days = (end - start).days + 1
        if trip_days < GATE_THRESHOLDS["min_trip_days"]:
            _block(
                "TRIP_TOO_SHORT",
                f"Trip must be at least {GATE_THRESHOLDS['min_trip_days']} day(s).",
                "end_date",
                "Extend the end date.",
            )
        elif trip_days > GATE_THRESHOLDS["max_trip_days"]:
            _block(
                "TRIP_TOO_LONG",
                f"Trip exceeds the {GATE_THRESHOLDS['max_trip_days']}-day maximum.",
                "end_date",
                "Shorten the trip or split it.",
            )
        elif trip_days > GATE_THRESHOLDS["warn_trip_days"]:
            _warn(
                "TRIP_LONG",
                f"Trips over {GATE_THRESHOLDS['warn_trip_days']} days may be hard to plan.",
                "end_date",
                "Consider shortening the trip.",
            )
        if end < start:
            _block(
                "END_BEFORE_START",
                "End date is before the start date.",
                "end_date",
                "Pick an end date after the start date.",
            )
    if start:
        days_ahead = (start - date.today()).days
        if days_ahead > GATE_THRESHOLDS["max_days_in_future"]:
            _block(
                "DATE_TOO_FAR",
                f"Start date is more than {GATE_THRESHOLDS['max_days_in_future']} days out.",
                "start_date",
                "Pick a nearer start date.",
            )

    # --- Travelers ---
    adults = plan.adults or 0
    children = plan.children or 0
    if adults > GATE_THRESHOLDS["max_adults"]:
        _block(
            "TOO_MANY_ADULTS",
            f"Maximum {GATE_THRESHOLDS['max_adults']} adults supported.",
            "adults",
            "Reduce the number of adults.",
        )
    if children > GATE_THRESHOLDS["max_children"]:
        _block(
            "TOO_MANY_CHILDREN",
            f"Maximum {GATE_THRESHOLDS['max_children']} children supported.",
            "children",
            "Reduce the number of children.",
        )
    if adults + children > GATE_THRESHOLDS["max_total_travelers"]:
        _block(
            "TOO_MANY_TRAVELERS",
            f"Maximum {GATE_THRESHOLDS['max_total_travelers']} total travelers supported.",
            "adults",
            "Reduce the party size.",
        )

    # --- Budget ---
    budget = plan.budget
    if budget is not None and budget > 0:
        if budget < GATE_THRESHOLDS["min_budget_usd"]:
            _block(
                "BUDGET_TOO_LOW",
                f"Budget below the ${GATE_THRESHOLDS['min_budget_usd']} minimum.",
                "budget",
                "Increase the budget.",
            )
        elif budget > GATE_THRESHOLDS["max_budget_usd"]:
            _block(
                "BUDGET_TOO_HIGH",
                f"Budget above the ${GATE_THRESHOLDS['max_budget_usd']} maximum.",
                "budget",
                "Lower the budget.",
            )
        elif budget > GATE_THRESHOLDS["warn_budget_high_usd"]:
            _warn(
                "BUDGET_HIGH",
                f"Budget over ${GATE_THRESHOLDS['warn_budget_high_usd']} is unusually high.",
                "budget",
                "Confirm the budget is intentional.",
            )

    return blockers, warnings


def _parse_iso_date(value: Any) -> Any:
    """Parse an ISO date string into a ``date``; return None on failure."""
    if not value:
        return None
    from datetime import date

    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


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
        gate_blockers, gate_warnings = _run_input_gates(plan)
        violations.extend(gate_blockers)
        warnings.extend(gate_warnings)
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

    # 5. Route validation (same-city + place existence -- LLM-backed, cached)
    try:
        route_violations = await check_route_constraint(plan)
        for v in route_violations:
            entry = v.to_dict()
            if v.severity == "blocking":
                violations.append(entry)
            else:
                warnings.append(entry)
    except Exception as exc:
        logger.warning("[validate_plan] Route validation failed: %s", exc)

    # 6. Build result
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
