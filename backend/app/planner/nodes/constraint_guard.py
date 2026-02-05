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
from app.planner.state.schemas import SpecialistConstraint

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
# Constraint Rule Canonicalization
# =============================================================================

# Canonical constraint rule names — LLMs generate aliases
# NOTE: itinerary_builder.py has similar CONSTRAINT_ALIASES dict.
# Post-demo: extract to shared backend/app/planner/constraint_defs.py
# For now, keep in sync manually or risk mismatch bugs.
CONSTRAINT_ALIASES = {
    "min_24h_buffer_after_dive": [
        "no_fly_24h",
        "24h_no_fly",
        "diving_no_fly_buffer",
        "no_fly_after_dive",
        "24h_buffer_after_dive",
    ],
    "morning_start_recommended": ["early_start", "morning_activity", "am_start"],
    "guide_required": ["requires_guide", "guided_activity", "professional_guide"],
}


def canonicalize_rule(rule: str) -> str:
    """Normalize to canonical constraint name."""
    if not rule:
        return rule
    normalized = rule.lower().replace("-", "_").replace(" ", "_")
    for canonical, aliases in CONSTRAINT_ALIASES.items():
        if normalized == canonical or any(normalized == a.lower() for a in aliases):
            return canonical
    return normalized


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
            # No else branch - satisfied constraints don't add violations

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
    import logging

    from app.debug_utils import _debug_node_end, _debug_node_start

    logger = logging.getLogger(__name__)

    # STATE IN logging - critical for debugging state mutations between nodes
    logger.info(
        f"[GUARD] STATE IN: tiles={len(state.tiles)} "
        f"strategy={len(state.metadata.get('strategy_sections', []))} "
        f"retry={state.guard_retry_count}"
    )

    _debug_node_start(
        "guard",
        "🛡️",
        destination=state.trip_plan.destination,
        budget=state.trip_plan.budget,
        specialist_constraints=len(state.trip_plan.constraints),
    )

    # RESET: Clear previous validation receipts before re-evaluation
    # Prevents stale green badges if guard runs multiple times (auto-fix loop)
    state.metadata["constraints_validated"] = []

    # =========================================================================
    # Merge Persisted Specialist Constraints
    # Specialists store their constraints in metadata on emit. On subsequent turns,
    # trip_plan.constraints may be cleared, but persisted constraints remain.
    # This ensures guard sees ALL constraints from ALL specialists that ever ran.
    # =========================================================================
    from app.debug_utils import log

    persisted = state.metadata.get("specialist_constraints", {})
    existing_rules = {canonicalize_rule(c.rule) for c in state.trip_plan.constraints}
    merged_count = 0
    for topic, constraint_dicts in persisted.items():
        for cd in constraint_dicts:
            rule = cd.get("rule", "")
            if canonicalize_rule(rule) not in existing_rules:
                try:
                    # Use model_validate for proper Pydantic reconstruction from stored dict
                    constraint = SpecialistConstraint.model_validate(cd)
                    state.trip_plan.constraints.append(constraint)
                    existing_rules.add(canonicalize_rule(rule))
                    merged_count += 1
                except Exception as e:
                    log("GUARD", f"⚠️ Failed to merge constraint from {topic}: {e}")

    if merged_count > 0:
        log("GUARD", f"Merged {merged_count} persisted constraints from metadata")
    log(
        "GUARD",
        f"After merge: trip_plan.constraints={[c.rule for c in state.trip_plan.constraints]}",
    )

    guard = ConstraintGuard()

    # DEBUG: Log constraint sources for validation receipt logic
    log(
        "GUARD",
        f"Constraint sources: trip_plan={[c.rule for c in state.trip_plan.constraints]}, "
        f"executed_topics={state.metadata.get('executed_strategy_topics', [])}",
    )
    log("GUARD", "Validation (pure Python, no LLM)...")

    # Run all checks (pure Python, no LLM)
    violations, has_blocking = guard.check_all(state)

    # =========================================================================
    # Flight-Independent Diving Capacity Check
    # Pure math: validates diving is physically possible given trip duration
    # Works even before flights are added (Turn 1-2 of demo arc)
    # =========================================================================
    has_diving_constraint_for_capacity = any(
        canonicalize_rule(c.rule) == "min_24h_buffer_after_dive"
        for c in state.trip_plan.constraints
    )
    if (
        has_diving_constraint_for_capacity
        and state.trip_plan.start_date
        and state.trip_plan.end_date
        and not any(v.code == "DIVING_SURFACE_INTERVAL" for v in violations)
    ):
        try:
            from datetime import datetime

            start = datetime.fromisoformat(state.trip_plan.start_date)
            end = datetime.fromisoformat(state.trip_plan.end_date)
            total_days = (end - start).days + 1
            usable_days = total_days - 2  # arrival + departure
            diving_available = max(0, usable_days - 1)  # 24h no-fly buffer

            # Count diving content blocks from strategy sections
            strategy_sections = state.metadata.get("strategy_sections", [])
            diving_blocks = [
                b
                for s in strategy_sections
                if s.get("specialist_type") == "diving"
                for b in s.get("content_added", [])
                if b.get("type") == "activity"
            ]

            if len(diving_blocks) > diving_available:
                violations.append(
                    ConstraintViolation(
                        code="DIVING_SURFACE_INTERVAL",
                        severity="blocking",
                        category="capacity",
                        message=(
                            f"Need {len(diving_blocks)} dive days but only {diving_available} "
                            f"available (24h no-fly buffer requires 1 rest day before departure)"
                        ),
                    )
                )
                has_blocking = True
                log(
                    "CONSTRAINT",
                    f"❌ DIVING_SURFACE_INTERVAL (blocking) - capacity check: "
                    f"{len(diving_blocks)} dives > {diving_available} available days",
                )
        except Exception as e:
            log("GUARD", f"Capacity check error (non-fatal): {e}")

    log("GUARD", f"Violations found: {len(violations)}")
    for v in violations:
        severity_icon = "⚠️" if v.severity == "warning" else "ℹ️" if v.severity == "info" else "❌"
        log("CONSTRAINT", f"{severity_icon} {v.code} ({v.severity})", data=v.message, sleep=0.2)

    if has_blocking:
        log("SOLVER", "Blocking violations detected - routing to synthesizer (state preserved)")
    elif violations:
        log("GUARD", "No blocking violations - proceeding to synthesis")
    else:
        log("GUARD", "All constraints satisfied")

    # =========================================================================
    # Emit Validation Receipts for Constraints that PASSED
    # These surface as green badges in the Trip DNA bar
    #
    # NOTE: Specialist constraints are now merged from metadata at top of guard,
    # so trip_plan.constraints contains ALL constraints from ALL specialists.
    # No more executed_topics fallback needed.
    # =========================================================================
    validated = []

    # Diving no-fly buffer - check trip_plan.constraints (includes merged persisted)
    has_diving_constraint = any(
        canonicalize_rule(c.rule) == "min_24h_buffer_after_dive"
        for c in state.trip_plan.constraints
    )
    has_diving_violation = any(v.code == "DIVING_SURFACE_INTERVAL" for v in violations)

    if has_diving_constraint and not has_diving_violation:
        validated.append(
            {
                "constraint_id": "diving_no_fly",
                "rule": "min_24h_buffer_after_dive",  # Always canonical
                "status": "satisfied",
                "specialist": "diving",
                "label": "24h No-Fly Buffer",
            }
        )

    # Temporal validity - if no DATE_ORDER_INVALID or TRIP_TOO_* violations
    has_temporal_violation = any(v.code.startswith(("DATE_ORDER", "TRIP_TOO")) for v in violations)
    if state.trip_plan.start_date and not has_temporal_violation:
        validated.append(
            {
                "constraint_id": "temporal_valid",
                "rule": "valid_date_range",
                "status": "satisfied",
                "specialist": "system",
                "label": "Valid Date Range",
            }
        )

    # Budget - if no BUDGET_* violations
    has_budget_violation = any(v.code.startswith("BUDGET_") for v in violations)
    if state.trip_plan.budget and not has_budget_violation:
        validated.append(
            {
                "constraint_id": "budget_ok",
                "rule": "budget_within_limits",
                "status": "satisfied",
                "specialist": "system",
                "label": "Budget Within Limits",
            }
        )

    # Store in metadata
    state.metadata["constraints_validated"] = validated

    # Log validated constraints (terminal visibility for demo)
    for v in validated:
        log("CONSTRAINT", f"✅ {v['constraint_id']} (satisfied) └─ {v['label']}")

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

    # Determine routing decision for logging
    unfixable_categories = {"route", "specialist"}
    is_unfixable = any(
        v.code in ("SAME_CITY_ERROR", "UNKNOWN_DESTINATION_ERROR")
        or v.category in unfixable_categories
        for v in violations
    )
    route_destination = "synth" if is_unfixable or not has_blocking else "architect"

    # STATE OUT logging - shows where state goes next and what changed
    logger.info(
        f"[GUARD] STATE OUT: tiles={len(state.tiles)} "
        f"strategy={len(state.metadata.get('strategy_sections', []))} "
        f"route={route_destination}"
    )

    _debug_node_end(
        "guard",
        "🛡️",
        violations_count=len(violations),
        has_blocking=has_blocking,
        violation_codes=[v.code for v in violations],
    )

    return state
