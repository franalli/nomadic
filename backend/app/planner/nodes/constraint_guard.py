"""
ConstraintGuard Node - Pure Python deterministic validation.

NO LLM calls - this is pure logic.
Checks:
- Budget constraints (total cost < budget)
- Temporal constraints (arrival < check-in)
- Geographic feasibility (landlocked beaches)
- Specialist constraints (24h surface interval)

Key Principle: "The math must work."
"""

from datetime import datetime
from typing import Any, Dict, List, Tuple

from app.planner.state import GraphState, TripPlan

# =============================================================================
# Place Validation Helper
# =============================================================================


def validate_place_exists(place: str) -> tuple[bool, str | None]:
    """
    Check if a place exists using the validation cache.

    Uses the existing LLM-backed validation with TTL caching.
    Returns (is_valid, reason) tuple.
    Fails open (returns True) if validation service unavailable.
    """
    import logging

    from app.validation import validate_input

    logger = logging.getLogger(__name__)

    try:
        result = validate_input(place, "destination")
        logger.info(
            f"[GUARD] validate_place_exists('{place}'): "
            f"is_valid={result.is_valid}, reason={result.reason}"
        )
        return result.is_valid, result.reason
    except Exception as e:
        logger.warning(f"[GUARD] validate_place_exists('{place}'): EXCEPTION - {e}, failing open")
        return True, None  # Fail open - don't block if validation unavailable


# =============================================================================
# Constraint Violation Types
# =============================================================================


class ConstraintViolation:
    """A constraint violation detected by the guard."""

    def __init__(
        self,
        code: str,
        message: str,
        severity: str = "warning",
        category: str = "general",
        suggested_action: str | None = None,
        suggested_specialist: str | None = None,
    ):
        self.code = code
        self.message = message
        self.severity = severity  # "blocking", "warning", "info"
        self.category = category  # "budget", "temporal", "geographic", "specialist", "seasonal"
        self.suggested_action = suggested_action  # Human-readable action
        self.suggested_specialist = suggested_specialist  # Alternative specialist to switch to

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "category": self.category,
        }
        if self.suggested_action:
            result["suggested_action"] = self.suggested_action
        if self.suggested_specialist:
            result["suggested_specialist"] = self.suggested_specialist
        return result


# =============================================================================
# Budget Allocation
# =============================================================================

# Default budget allocation percentages
BUDGET_ALLOCATIONS = {
    "flights": 0.30,  # 30% for flights
    "hotels": 0.40,  # 40% for hotels
    "activities": 0.30,  # 30% for activities
}


def _get_budget_allocation(budget: float, category: str) -> float:
    """Get budget allocation for a category."""
    return budget * BUDGET_ALLOCATIONS.get(category, 0.25)


# =============================================================================
# Validation Functions
# =============================================================================


def check_budget_constraint(
    plan: TripPlan,
    tiles: Dict[str, List[Dict[str, Any]]],
) -> List[ConstraintViolation]:
    """
    Check if total tile costs exceed budget.

    Returns list of violations.
    """
    violations = []

    if not plan.budget:
        return violations  # No budget set, can't violate

    total_cost = 0.0

    for category, category_tiles in tiles.items():
        category_cost = 0.0
        allocation = _get_budget_allocation(plan.budget, category)

        for tile in category_tiles:
            price = tile.get("price_estimate") or tile.get("live_price") or 0
            category_cost += price

        # Check if category exceeds allocation
        if category_cost > allocation:
            violations.append(
                ConstraintViolation(
                    code=f"BUDGET_{category.upper()}_EXCEEDED",
                    message=(
                        f"{category.title()} cost (${category_cost:.0f}) "
                        f"exceeds allocation (${allocation:.0f})"
                    ),
                    severity="warning",
                    category="budget",
                )
            )

        total_cost += category_cost

    # Check total budget
    if total_cost > plan.budget:
        violations.append(
            ConstraintViolation(
                code="BUDGET_TOTAL_EXCEEDED",
                message=f"Total cost (${total_cost:.0f}) exceeds budget (${plan.budget:.0f})",
                severity="blocking",
                category="budget",
            )
        )

    return violations


def check_temporal_constraints(
    plan: TripPlan,
    tiles: Dict[str, List[Dict[str, Any]]],
) -> List[ConstraintViolation]:
    """
    Check temporal constraints:
    - Flight arrival < hotel check-in
    - Trip duration makes sense
    """
    violations = []

    # Check trip duration
    if plan.start_date and plan.end_date:
        try:
            start = datetime.fromisoformat(plan.start_date)
            end = datetime.fromisoformat(plan.end_date)

            if end < start:
                violations.append(
                    ConstraintViolation(
                        code="DATE_ORDER_INVALID",
                        message="End date is before start date",
                        severity="blocking",
                        category="temporal",
                    )
                )

            duration = (end - start).days
            if duration > 30:
                violations.append(
                    ConstraintViolation(
                        code="TRIP_TOO_LONG",
                        message=f"Trip duration ({duration} days) is unusually long",
                        severity="info",
                        category="temporal",
                    )
                )

            if duration < 1:
                violations.append(
                    ConstraintViolation(
                        code="TRIP_TOO_SHORT",
                        message="Trip duration is less than 1 day",
                        severity="warning",
                        category="temporal",
                    )
                )

        except ValueError:
            pass  # Invalid date format, let it pass

    return violations


def _check_diving_flight_conflict(
    plan: TripPlan,
    tiles: Dict[str, List[Dict[str, Any]]],
) -> bool:
    """
    Check if diving activities are scheduled too close to departure flight.

    Returns True if there's a conflict (diving on last day with flight scheduled).

    Logic:
    1. Calculate trip duration from start_date and end_date
    2. Find the last day with diving activities in itinerary_blocks
    3. Check if flights are present (user wants to fly home)
    4. Conflict = diving on last day (or day before with early flight)
    """
    # Need dates to calculate trip duration
    if not plan.start_date or not plan.end_date:
        return False

    try:
        start = datetime.fromisoformat(plan.start_date)
        end = datetime.fromisoformat(plan.end_date)
        trip_days = (end - start).days + 1  # Inclusive of both days
    except ValueError:
        return False

    if trip_days < 1:
        return False

    # Find last day with diving activity
    last_dive_day = None
    for block in plan.itinerary_blocks:
        is_diving = block.source_specialist == "diving" or (
            block.type == "activity" and "dive" in (block.title or "").lower()
        )
        if is_diving and block.day:
            if last_dive_day is None or block.day > last_dive_day:
                last_dive_day = block.day

    if last_dive_day is None:
        return False  # No diving activities found

    # Check if flights are enabled/present
    flight_tiles = tiles.get("flights", [])
    has_departure_flight = len(flight_tiles) > 0  # Any flight tile indicates flights enabled

    if not has_departure_flight:
        return False  # No flights, no conflict

    # Conflict: diving on last day or second-to-last day (needs 24h buffer)
    # trip_days is total days, so last day = trip_days, second-to-last = trip_days - 1
    # Conservative: flag if diving is on the last day (day N) since flight is on end_date
    if last_dive_day >= trip_days:
        return True  # Diving on departure day = definite conflict

    # Also flag if diving on day before last (second-to-last day)
    # because 24h buffer may not be met depending on flight time
    if last_dive_day == trip_days - 1:
        return True  # Diving day before departure = potential conflict

    return False


def check_specialist_constraints(
    plan: TripPlan,
    tiles: Dict[str, List[Dict[str, Any]]],
) -> List[ConstraintViolation]:
    """
    Check constraints injected by Vertical Specialist.

    For example:
    - 24h surface interval before flying (diving)
    - Altitude acclimatization (hiking)
    """
    violations = []

    for constraint in plan.constraints:
        if constraint.rule == "min_24h_buffer_after_dive":
            # Check for actual diving+flight conflict
            has_conflict = _check_diving_flight_conflict(plan, tiles)

            if has_conflict:
                # Actual conflict detected - blocking severity triggers auto-fix
                violations.append(
                    ConstraintViolation(
                        code="DIVING_SURFACE_INTERVAL",
                        message="Diving scheduled too close to departure flight - need 24h buffer",
                        severity="blocking",
                        category="specialist",
                        suggested_action="Move diving activities earlier or extend trip by 1 day",
                    )
                )
            else:
                # No conflict - just an informational note
                violations.append(
                    ConstraintViolation(
                        code="DIVING_SURFACE_INTERVAL",
                        message="24h no-fly buffer after diving is respected",
                        severity="info",
                        category="specialist",
                    )
                )

        elif constraint.rule == "altitude_acclimatization":
            violations.append(
                ConstraintViolation(
                    code="ALTITUDE_WARNING",
                    message="Plan for altitude acclimatization if going above 3000m",
                    severity="info",
                    category="specialist",
                )
            )

        elif constraint.rule == "advanced_cert_required_for_deep":
            # Check activities for deep dives
            activity_tiles = tiles.get("activities", [])
            for tile in activity_tiles:
                skill = tile.get("meta", {}).get("skill_level")
                if skill == "advanced":
                    violations.append(
                        ConstraintViolation(
                            code="CERTIFICATION_REQUIRED",
                            message=f"'{tile.get('title')}' may require advanced certification",
                            severity="warning",
                            category="specialist",
                        )
                    )

        elif constraint.rule == "no_altitude_after_dive":
            # Cross-domain constraint: diving → hiking
            # Detailed validation happens in ItineraryBuilder
            violations.append(
                ConstraintViolation(
                    code="ALTITUDE_AFTER_DIVE_WARNING",
                    message="High-altitude activities must be scheduled 24h+ after diving",
                    severity="info",
                    category="specialist",
                )
            )

    return violations


def check_seasonal_constraints(plan: TripPlan) -> List[ConstraintViolation]:
    """
    Check if trip_type is compatible with the season at destination.

    Examples:
    - Hiking in Swiss Alps in November → Trails closed due to snow
    - Skiing in Chamonix in July → No snow conditions

    Returns violations with suggested alternative specialists.
    """
    from app.planner.season import get_activity_season_conflict

    violations = []

    if not plan.trip_type or not plan.start_date or not plan.destination:
        return violations

    # Get season conflict
    conflict = get_activity_season_conflict(
        activity_type=plan.trip_type,
        date_str=plan.start_date,
        destination=plan.destination,
    )

    if conflict:
        violation_message, suggested_specialist = conflict
        # season variable intentionally not used - conflict message already contains context

        violations.append(
            ConstraintViolation(
                code="SEASONAL_ACTIVITY_CONFLICT",
                message=violation_message,
                severity="warning",  # Warning, not blocking - user can override
                category="seasonal",
                suggested_action=f"Try {suggested_specialist} instead?",
                suggested_specialist=suggested_specialist,
            )
        )

    return violations


def check_geographic_constraints(plan: TripPlan) -> List[ConstraintViolation]:
    """
    Check geographic feasibility.

    Validates:
    - Diving in landlocked countries (impossible)
    - Beach activities in landlocked countries (impossible)

    Note: Seasonal constraints (skiing in summer, beach in winter for Nordic countries)
    are complex because they require understanding the trip activities AND timing.
    For MVP, the LLM architect handles these through contextual reasoning.
    """
    violations = []

    # Landlocked countries (simplified list)
    landlocked = {
        "switzerland",
        "austria",
        "czech",
        "czechia",
        "hungary",
        "luxembourg",
        "liechtenstein",
        "andorra",
        "san marino",
        "mongolia",
        "nepal",
        "bhutan",
        "laos",
        "paraguay",
        "bolivia",
        "rwanda",
        "burundi",
        "uganda",
        "zambia",
        "zimbabwe",
        "botswana",
        "malawi",
        "lesotho",
        "eswatini",
        "ethiopia",
        "chad",
        "niger",
        "mali",
        "burkina faso",
        "central african republic",
        "south sudan",
    }

    destination = (plan.destination or "").lower()

    # Check diving in landlocked
    if plan.trip_type == "diving":
        for country in landlocked:
            if country in destination:
                violations.append(
                    ConstraintViolation(
                        code="GEOGRAPHIC_INFEASIBLE",
                        message=f"Diving not available in landlocked {plan.destination}",
                        severity="blocking",
                        category="geographic",
                    )
                )
                break

    # Check beach activities in landlocked (via itinerary blocks)
    beach_keywords = {"beach", "snorkeling", "coastal", "seaside"}
    for block in plan.itinerary_blocks:
        block_title = (block.title or "").lower()
        block_desc = (block.description or "").lower()
        has_beach = any(kw in block_title or kw in block_desc for kw in beach_keywords)

        if has_beach:
            for country in landlocked:
                if country in destination:
                    violations.append(
                        ConstraintViolation(
                            code="BEACH_IN_LANDLOCKED",
                            message=(
                                f"Beach activity '{block.title}' not possible "
                                f"in landlocked {plan.destination}"
                            ),
                            severity="blocking",
                            category="geographic",
                        )
                    )
                    break

    return violations


def check_route_constraint(plan: TripPlan) -> List[ConstraintViolation]:
    """
    Check route validity (Logic Guards).

    Validates:
    - Origin !== Destination (same city error)
    - Destination exists (LLM validation)

    These are USER INTENT errors that cannot be auto-fixed by the Architect.
    They must be rejected and corrected by the user.
    """
    violations = []

    origin = (plan.origin or "").lower().strip()
    destination = (plan.destination or "").lower().strip()

    # 1. Same City Check
    if origin and destination and origin == destination:
        violations.append(
            ConstraintViolation(
                code="SAME_CITY_ERROR",
                message=f"Origin and destination cannot be the same ({plan.destination})",
                severity="blocking",
                category="route",
                suggested_action="Please choose a different destination",
            )
        )

    # 2. Unknown Place Check (uses LLM-backed validation)
    if plan.destination and len(plan.destination) > 1:
        is_valid, reason = validate_place_exists(plan.destination)
        if not is_valid:
            violations.append(
                ConstraintViolation(
                    code="UNKNOWN_DESTINATION_ERROR",
                    message=reason or f"'{plan.destination}' is not a valid destination",
                    severity="blocking",
                    category="route",
                    suggested_action="Check spelling or be more specific",
                )
            )

    return violations


# =============================================================================
# ConstraintGuard Class
# =============================================================================


class ConstraintGuard:
    """
    Deterministic validation node.

    Runs all constraint checks and collects violations.
    """

    def check_all(
        self,
        state: GraphState,
    ) -> Tuple[List[ConstraintViolation], bool]:
        """
        Run all constraint checks.

        Returns:
            (violations, has_blocking) tuple
        """
        violations = []

        # Budget constraints
        violations.extend(check_budget_constraint(state.trip_plan, state.tiles))

        # Temporal constraints
        violations.extend(check_temporal_constraints(state.trip_plan, state.tiles))

        # Seasonal constraints (hiking in winter, skiing in summer)
        violations.extend(check_seasonal_constraints(state.trip_plan))

        # Specialist constraints
        violations.extend(check_specialist_constraints(state.trip_plan, state.tiles))

        # Geographic constraints
        violations.extend(check_geographic_constraints(state.trip_plan))

        # Route constraints (Logic Guards - user intent errors)
        violations.extend(check_route_constraint(state.trip_plan))

        # Check for blocking violations
        has_blocking = any(v.severity == "blocking" for v in violations)

        return violations, has_blocking


# =============================================================================
# Node Function (for graph registration)
# =============================================================================


async def constraint_guard(state: GraphState) -> GraphState:
    """
    ConstraintGuard node function for LangGraph.

    Pure Python validation - no LLM calls.
    """
    from app.debug_utils import _debug_node_end, _debug_node_start

    _debug_node_start(
        "guard",
        "🛡️",
        destination=state.trip_plan.destination,
        budget=state.trip_plan.budget,
        specialist_constraints=len(state.trip_plan.constraints),
    )

    guard = ConstraintGuard()

    from app.debug_utils import log

    log("GUARD", "Validation (pure Python, no LLM)...")

    # Run all checks (pure Python, no LLM)
    violations, has_blocking = guard.check_all(state)

    log("GUARD", f"Violations found: {len(violations)}")
    for v in violations:
        severity_icon = "⚠️" if v.severity == "warning" else "ℹ️" if v.severity == "info" else "❌"
        log("CONSTRAINT", f"{severity_icon} {v.code} ({v.severity})", data=v.message, sleep=0.2)

    if has_blocking:
        log("SOLVER", "Blocking violations detected - triggering auto-fix loop")
    elif violations:
        log("GUARD", "No blocking violations - proceeding to synthesis")
    else:
        log("GUARD", "All constraints satisfied")

    # Update state
    state.constraints_violated = [v.message for v in violations]

    # Store detailed violations in metadata
    state.metadata["constraint_violations"] = [v.to_dict() for v in violations]
    state.metadata["has_blocking_violations"] = has_blocking

    # ==========================================================================
    # ROUTE ERROR HANDLING (Logic Guards)
    # Handle route errors with targeted fixes rather than full rollback.
    # SAME_CITY_ERROR: Clear only the origin (the erroneous field)
    # UNKNOWN_DESTINATION_ERROR: Clear only the destination
    # ==========================================================================
    same_city_error = any(v.code == "SAME_CITY_ERROR" for v in violations)
    unknown_dest_error = any(v.code == "UNKNOWN_DESTINATION_ERROR" for v in violations)

    if same_city_error:
        # SAME_CITY_ERROR: The LLM incorrectly set origin == destination
        # Fix: Clear only the origin, preserve the destination
        log("GUARD", "🚫 SAME_CITY_ERROR: Clearing invalid origin (preserving destination)")
        state.trip_plan.origin = None
        log(
            "GUARD",
            f"Fixed: origin=None, dest={state.trip_plan.destination}",
        )
    elif unknown_dest_error:
        # UNKNOWN_DESTINATION_ERROR: Invalid destination entered
        # Fix: Clear the destination, preserve other fields
        log("GUARD", "🚫 UNKNOWN_DESTINATION_ERROR: Clearing invalid destination")
        previous_inputs = state.metadata.get("trip_inputs", {})
        state.trip_plan.destination = previous_inputs.get("destination")  # Restore previous
        log(
            "GUARD",
            f"Rolled back to: dest={state.trip_plan.destination}",
        )

    # Prepare violation context for Architect retry (Auto-Fix Loop)
    if has_blocking:
        state.metadata["violations_for_retry"] = [
            {"code": v.code, "message": v.message, "severity": v.severity}
            for v in violations
            if v.severity == "blocking"
        ]

    # Add UI event if violations found
    if violations:
        state.ui_events.append("CONSTRAINT_VIOLATED")

    _debug_node_end(
        "guard",
        "🛡️",
        violations_count=len(violations),
        has_blocking=has_blocking,
        violation_codes=[v.code for v in violations],
    )

    return state
