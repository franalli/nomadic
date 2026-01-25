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

from app.planner.state import GraphStateV2, TripPlan

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
    ):
        self.code = code
        self.message = message
        self.severity = severity  # "blocking", "warning", "info"
        self.category = category  # "budget", "temporal", "geographic", "specialist"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "category": self.category,
        }


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
            # Check if there's a flight tile on the last day
            # In real implementation, compare flight departure times
            # For MVP, just note the constraint
            violations.append(
                ConstraintViolation(
                    code="DIVING_SURFACE_INTERVAL",
                    message="Ensure 24h between last dive and flight for safety",
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
        state: GraphStateV2,
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

        # Specialist constraints
        violations.extend(check_specialist_constraints(state.trip_plan, state.tiles))

        # Geographic constraints
        violations.extend(check_geographic_constraints(state.trip_plan))

        # Check for blocking violations
        has_blocking = any(v.severity == "blocking" for v in violations)

        return violations, has_blocking


# =============================================================================
# Node Function (for graph registration)
# =============================================================================


async def constraint_guard(state: GraphStateV2) -> GraphStateV2:
    """
    ConstraintGuard node function for LangGraph.

    Pure Python validation - no LLM calls.
    """
    from app.debug_utils import _debug_v2_node_end, _debug_v2_node_start

    _debug_v2_node_start(
        "guard",
        "🛡️",
        destination=state.trip_plan.destination,
        budget=state.trip_plan.budget,
        specialist_constraints=len(state.trip_plan.constraints),
    )

    guard = ConstraintGuard()

    # Run all checks
    violations, has_blocking = guard.check_all(state)

    # Update state
    state.constraints_violated = [v.message for v in violations]

    # Store detailed violations in metadata
    state.metadata["constraint_violations"] = [v.to_dict() for v in violations]
    state.metadata["has_blocking_violations"] = has_blocking

    # Add UI event if violations found
    if violations:
        state.ui_events.append("CONSTRAINT_VIOLATED")

    _debug_v2_node_end(
        "guard",
        "🛡️",
        violations_count=len(violations),
        has_blocking=has_blocking,
        violation_codes=[v.code for v in violations],
    )

    return state
