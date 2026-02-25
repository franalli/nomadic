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
from typing import Any, Dict, List, Optional, Tuple

from app.planner.specialist_registry import canonicalize_rule, get_nofly_buffer_hours
from app.planner.specialist_registry import get as get_config
from app.planner.state import (
    GraphState,
    TripPlan,
    get_persistent_meta,
    get_trip_settings,
    get_turn_meta,
    sync_turn_meta,
)
from app.planner.state.graph_state import SpecialistConstraint

# =============================================================================
# Place Validation Helper
# =============================================================================


async def validate_place_exists(place: str) -> tuple[bool, str | None]:
    """
    Check if a place exists using the validation cache.

    Uses the existing LLM-backed validation with TTL caching.
    Returns (is_valid, reason) tuple.
    Fails open (returns True) if validation service unavailable.
    """
    import logging

    from app.validation import validate_input_async

    logger = logging.getLogger(__name__)

    try:
        result = await validate_input_async(place, "destination")
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


class GuardViolation:
    """A constraint violation detected by the guard."""

    def __init__(
        self,
        code: str,
        message: str,
        severity: str = "warning",
        category: str = "general",
        suggested_action: str | None = None,
        suggested_specialist: str | None = None,
        conflicting_specialists: list[str] | None = None,
    ):
        self.code = code
        self.message = message
        self.severity = severity  # "blocking", "warning", "info"
        self.category = category  # "budget", "temporal", "geographic", "specialist", "seasonal"
        self.suggested_action = suggested_action  # Human-readable action
        self.suggested_specialist = suggested_specialist  # Alternative specialist to switch to
        self.conflicting_specialists = conflicting_specialists or []

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
        if self.conflicting_specialists:
            result["conflicting_specialists"] = self.conflicting_specialists
        return result


# =============================================================================
# Constraint Rule Canonicalization
# =============================================================================

# Canonical constraint rule names — LLMs generate aliases


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
) -> List[GuardViolation]:
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
                GuardViolation(
                    code=f"BUDGET_{category.upper()}_EXCEEDED",
                    message=(
                        f"{category.title()} cost (${category_cost:.0f}) "
                        f"exceeds allocation (${allocation:.0f})"
                    ),
                    severity="warning",
                    category="budget",
                    suggested_action=f"Look for more affordable {category} options",
                )
            )

        total_cost += category_cost

    # Check total budget
    if total_cost > plan.budget:
        violations.append(
            GuardViolation(
                code="BUDGET_TOTAL_EXCEEDED",
                message=f"Total cost (${total_cost:.0f}) exceeds budget (${plan.budget:.0f})",
                severity="blocking",
                category="budget",
                suggested_action=(
                    f"Reduce total spend by ${total_cost - plan.budget:.0f} or increase budget"
                ),
            )
        )

    return violations


def check_temporal_constraints(
    plan: TripPlan,
    _tiles: Dict[str, List[Dict[str, Any]]],
) -> List[GuardViolation]:
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

            # Past date check (last-resort — extraction auto-bumps first)
            today = datetime.now().date()
            if start.date() < today:
                violations.append(
                    GuardViolation(
                        code="DATE_IN_PAST",
                        message=f"Trip starts on {plan.start_date} which is in the past",
                        severity="blocking",
                        category="temporal",
                        suggested_action="Update your start date to a future date",
                    )
                )

            if end < start:
                violations.append(
                    GuardViolation(
                        code="DATE_ORDER_INVALID",
                        message="End date is before start date",
                        severity="blocking",
                        category="temporal",
                    )
                )

            duration = (end - start).days
            if duration > 30:
                violations.append(
                    GuardViolation(
                        code="TRIP_TOO_LONG",
                        message=f"Trip duration ({duration} days) is unusually long",
                        severity="info",
                        category="temporal",
                    )
                )

            if duration < 1:
                violations.append(
                    GuardViolation(
                        code="TRIP_TOO_SHORT",
                        message="Trip duration is less than 1 day",
                        severity="warning",
                        category="temporal",
                    )
                )

        except ValueError:
            pass  # Invalid date format, let it pass

    return violations


def _check_departure_buffer_conflict(
    plan: TripPlan,
    tiles: Dict[str, List[Dict[str, Any]]],
    _topic: str,
    blocks: list,
    buffer_days: int,
) -> bool:
    """Check if specialist activities are scheduled too close to departure.

    Returns True if the last activity for this specialist falls within
    buffer_days of the departure date and flights are present.
    """
    if not plan.start_date or not plan.end_date:
        return False

    try:
        start = datetime.fromisoformat(plan.start_date)
        end = datetime.fromisoformat(plan.end_date)
        trip_days = (end - start).days + 1  # Inclusive
    except ValueError:
        return False

    if trip_days < 1:
        return False

    # No flights → no departure conflict
    if not tiles.get("flights"):
        return False

    last_day = max((b.day for b in blocks if b.day), default=0)
    if last_day == 0:
        return False

    # Conflict: activity within buffer_days of departure
    # trip_days = N means departure on day N. Need buffer_days clear before that.
    return last_day >= trip_days - buffer_days


def check_specialist_constraints(
    plan: TripPlan,
    tiles: Dict[str, List[Dict[str, Any]]],
) -> List[GuardViolation]:
    """Registry-driven specialist constraint checks.

    Two checks per specialist:
    1. Departure buffer — for specialists with has_nofly_buffer, check if
       activities are scheduled too close to departure flight.
    2. Cross-domain — for specialists with cross_domain_blocks, check if
       target specialist blocks are scheduled within the buffer window.
    """
    from app.planner.specialist_registry import (
        get as get_config,
    )
    from app.planner.specialist_registry import (
        get_nofly_buffer_hours,
    )

    violations: List[GuardViolation] = []

    # Group itinerary blocks by source specialist (activity blocks only —
    # buffer/arrival/departure blocks must not trigger constraint violations)
    blocks_by_specialist: Dict[str, list] = {}
    for block in plan.itinerary_blocks:
        if block.source_specialist and block.type == "activity":
            blocks_by_specialist.setdefault(block.source_specialist, []).append(block)

    for topic, blocks in blocks_by_specialist.items():
        config = get_config(topic)
        if not config:
            continue

        # 1. Departure buffer (generalized from _check_diving_flight_conflict)
        if config.has_nofly_buffer:
            buffer_hours = get_nofly_buffer_hours(topic) or 24
            buffer_days = buffer_hours // 24
            if _check_departure_buffer_conflict(plan, tiles, topic, blocks, buffer_days):
                violations.append(
                    GuardViolation(
                        code=f"{topic.upper()}_SURFACE_INTERVAL",
                        message=(
                            f"{topic.title()} scheduled too close to departure "
                            f"flight — need {buffer_hours}h buffer"
                        ),
                        severity="blocking",
                        category="specialist",
                        suggested_action=(
                            f"Move {topic} activities earlier or extend trip by 1 day"
                        ),
                    )
                )

        # 2. Cross-domain blocks
        for xd in config.cross_domain_blocks:
            last_source_day = max((b.day for b in blocks if b.day), default=0)
            if not last_source_day:
                continue

            # Capacity gate: skip violation if trip is long enough for builder
            # to handle sequencing (mirrors _check_cross_domain_from_sections)
            if plan.start_date and plan.end_date:
                try:
                    _s = datetime.fromisoformat(plan.start_date)
                    _e = datetime.fromisoformat(plan.end_date)
                    total_days = (_e - _s).days + 1
                    usable = total_days - 2  # arrival + departure
                    available_after_buffer = usable - (xd.buffer_hours // 24)
                    if available_after_buffer >= 2:
                        continue  # Trip long enough — builder handles sequencing
                except (ValueError, TypeError):
                    pass  # Fall through to emit violation

            for target_sid in xd.target_specialists:
                target_blocks = blocks_by_specialist.get(target_sid, [])
                for tb in target_blocks:
                    if tb.day and tb.day <= last_source_day:
                        violations.append(
                            GuardViolation(
                                code=xd.violation_code,
                                message=xd.reason,
                                severity=xd.severity,
                                category="specialist",
                                suggested_action=(
                                    f"Schedule {target_sid} activities at least "
                                    f"{xd.buffer_hours}h after last {topic} activity"
                                ),
                                conflicting_specialists=[target_sid],
                            )
                        )
                        break  # One violation per target specialist

    return violations


def _check_cross_domain_from_sections(
    strategy_sections: List[Dict[str, Any]],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> List[GuardViolation]:
    """Stateless cross-domain check using persisted strategy sections.

    Unlike check_specialist_constraints() which reads itinerary_blocks
    (may be empty on fast paths), this reads strategy_sections which
    persist across turns.

    Capacity-aware: only emits a violation when the trip is too short
    for even the minimum viable plan (1 dive + buffer + 1 altitude).
    When the trip is long enough, the builder handles trimming.
    """
    from app.debug_utils import log
    from app.planner.specialist_registry import get as get_config

    active_specialists = {
        s.get("specialist_type")
        for s in strategy_sections
        if s.get("specialist_type") not in ("local_expert", "general", None)
    }

    if len(active_specialists) < 2:
        return []

    violations: List[GuardViolation] = []
    for topic in active_specialists:
        config = get_config(topic)
        if not config:
            continue
        for xd in config.cross_domain_blocks:
            conflicting = active_specialists & set(xd.target_specialists)
            if not conflicting:
                continue

            # Capacity check: only flag if trip too short for minimum viable
            if start_date and end_date:
                try:
                    s = datetime.fromisoformat(start_date)
                    e = datetime.fromisoformat(end_date)
                    total_days = (e - s).days + 1
                    usable = total_days - 2
                    available_after_buffer = usable - (xd.buffer_hours // 24)
                    log(
                        "GUARD",
                        f"Cross-domain capacity: {topic}→{sorted(conflicting)} "
                        f"total_days={total_days} usable={usable} "
                        f"buffer_h={xd.buffer_hours} available={available_after_buffer}",
                    )
                    if available_after_buffer >= 2:
                        # Trip long enough — builder will trim, no violation
                        continue
                except (ValueError, TypeError) as e:
                    log("GUARD", f"⚠️ Cross-domain capacity parse error: {e}")
            else:
                log(
                    "GUARD",
                    f"⚠️ Cross-domain check: no dates, emitting {xd.violation_code}",
                )

            violations.append(
                GuardViolation(
                    code=xd.violation_code,
                    message=xd.reason,
                    severity=xd.severity,
                    category="specialist",
                    suggested_action=(
                        f"Schedule {', '.join(sorted(conflicting))} activities at least "
                        f"{xd.buffer_hours}h after last {topic} activity"
                    ),
                    conflicting_specialists=sorted(conflicting),
                )
            )
    return violations


def check_day_preference_capacity(
    start_date: Optional[str],
    end_date: Optional[str],
    day_prefs: Dict[str, int],
    strategy_sections: Optional[List[Dict[str, Any]]] = None,
    activity_categories: Optional[List[str]] = None,
) -> List[GuardViolation]:
    """Check that requested activity day counts fit within trip duration.

    Computes max no-fly buffer from strategy_sections (preferred) or
    activity_categories (fallback), then validates total_requested <= effective days.

    Returns at most one GuardViolation: DAY_PREFERENCE_EXCEEDS_CAPACITY.
    """
    if not day_prefs or not start_date or not end_date:
        return []

    try:
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
        total_days = (end - start).days + 1
        usable = max(0, total_days - 2)  # arrival + departure

        # Compute max buffer from active specialists
        max_buffer = 0
        if strategy_sections:
            for section in strategy_sections:
                topic = section.get("specialist_type") if isinstance(section, dict) else None
                if topic:
                    config = get_config(topic)
                    if config and config.has_nofly_buffer:
                        hours = get_nofly_buffer_hours(topic) or 24
                        max_buffer = max(max_buffer, hours // 24)

        # Fallback: check activity_categories if no buffer from strategy_sections
        if not max_buffer and activity_categories:
            for cat in activity_categories:
                cat_name = str(cat).strip().lower()
                if cat_name:
                    config = get_config(cat_name)
                    if config and config.has_nofly_buffer:
                        hours = get_nofly_buffer_hours(cat_name) or 24
                        max_buffer = max(max_buffer, hours // 24)

        effective = max(0, usable - max_buffer)
        total_requested = sum(day_prefs.values())

        if total_requested > effective:
            return [
                GuardViolation(
                    code="DAY_PREFERENCE_EXCEEDS_CAPACITY",
                    message=(
                        f"Requested {total_requested} activity days but only "
                        f"{effective} available ({max_buffer} buffer day(s) required)"
                    ),
                    severity="blocking",
                    category="capacity",
                    suggested_action=(
                        f"Extend trip by {total_requested - effective} day(s) "
                        f"or reduce activity days"
                    ),
                )
            ]
    except (ValueError, TypeError):
        pass

    return []


async def check_route_constraint(plan: TripPlan) -> List[GuardViolation]:
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
            GuardViolation(
                code="SAME_CITY_ERROR",
                message=f"Origin and destination cannot be the same ({plan.destination})",
                severity="blocking",
                category="route",
                suggested_action="Please choose a different destination",
            )
        )

    # 2. Unknown Place Check (uses LLM-backed validation)
    if plan.destination and len(plan.destination) > 1:
        is_valid, reason = await validate_place_exists(plan.destination)
        if not is_valid:
            violations.append(
                GuardViolation(
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

    async def check_all(
        self,
        state: GraphState,
    ) -> Tuple[List[GuardViolation], bool]:
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

        # Specialist constraints (registry-driven: departure buffer + cross-domain)
        violations.extend(check_specialist_constraints(state.trip_plan, state.tiles))

        # Route constraints (Logic Guards - user intent errors)
        violations.extend(await check_route_constraint(state.trip_plan))

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

    # Typed metadata access — turn (per-turn) + persistent (cross-turn)
    turn = get_turn_meta(state)
    persistent = get_persistent_meta(state)

    # STATE IN logging - critical for debugging state mutations between nodes
    logger.info(
        f"[GUARD] STATE IN: tiles={len(state.tiles)} "
        f"strategy={len(persistent.strategy_sections)} "
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
    turn.constraints_validated = []

    # =========================================================================
    # Merge Persisted Specialist Constraints
    # Specialists store their constraints in metadata on emit. On subsequent turns,
    # trip_plan.constraints may be cleared, but persisted constraints remain.
    # This ensures guard sees ALL constraints from ALL specialists that ever ran.
    # =========================================================================
    from app.debug_utils import log

    persisted = persistent.specialist_constraints
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
        f"executed_topics={persistent.executed_strategy_topics}",
    )
    log("GUARD", "Validation (pure Python, no LLM)...")

    # Run all checks (pure Python, no LLM)
    violations, has_blocking = await guard.check_all(state)

    # =========================================================================
    # Stateless Cross-Domain Check (Strategy-Section-Driven)
    # check_specialist_constraints() reads itinerary_blocks which may be empty
    # on fast paths (ACTIONABLE_TO_LOGISTICS). This fallback reads persisted
    # strategy_sections to detect specialist co-existence every turn.
    # =========================================================================
    existing_codes = {v.code for v in violations}
    section_violations = _check_cross_domain_from_sections(
        persistent.strategy_sections,
        start_date=state.trip_plan.start_date,
        end_date=state.trip_plan.end_date,
    )
    # Map violation codes to the constraint rules the builder enforces
    # TODO: derive from specialist registry when more cross-domain constraints exist
    _violation_to_constraint_rule = {
        "ALTITUDE_AFTER_DIVE": "no_altitude_after_dive",
    }
    for sv in section_violations:
        if sv.code not in existing_codes:
            # If the builder's constraint is already persisted from a previous turn,
            # the builder is enforcing it via clustering — suppress the violation.
            # BUT: only suppress if the builder SUCCESSFULLY enforced the constraint
            # last turn. If the builder failed (trip too short), re-surface the
            # violation so the synthesizer can generate resolution chips.
            constraint_rule = _violation_to_constraint_rule.get(sv.code)
            if constraint_rule and canonicalize_rule(constraint_rule) in existing_rules:
                builder_ok = state.metadata.get("last_builder_success", False)
                drop_ratio = state.metadata.get("last_builder_drop_ratio", 0.0)
                # Only suppress if builder succeeded AND didn't drop too many activities
                if builder_ok and drop_ratio < 0.5:
                    log("GUARD", f"⏭️ {sv.code} suppressed: builder enforces {constraint_rule}")
                    continue
                else:
                    reason = "builder failed" if not builder_ok else f"drop ratio {drop_ratio:.0%}"
                    log(
                        "GUARD",
                        f"🔄 {sv.code} re-surfaced: {reason} for {constraint_rule}",
                    )
            violations.append(sv)
            existing_codes.add(sv.code)
            if sv.severity == "blocking":
                has_blocking = True

    # =========================================================================
    # Registry-Driven Capacity Check (Flight-Independent)
    # Pure math: validates specialist activities are physically possible
    # given trip duration and buffer requirements.
    # Works even before flights are added (Turn 1-2 of demo arc)
    # =========================================================================
    from app.planner.specialist_registry import (
        get as get_config,
    )
    from app.planner.specialist_registry import (
        get_nofly_buffer_hours,
    )

    if state.trip_plan.start_date and state.trip_plan.end_date:
        try:
            start = datetime.fromisoformat(state.trip_plan.start_date)
            end = datetime.fromisoformat(state.trip_plan.end_date)
            total_days = (end - start).days + 1
            usable_days = max(0, total_days - 2)  # arrival + departure

            for section in persistent.strategy_sections:
                topic = section.get("specialist_type")
                config = get_config(topic) if topic else None
                if not config or not config.has_nofly_buffer:
                    continue

                violation_code = f"{topic.upper()}_SURFACE_INTERVAL"
                if any(v.code == violation_code for v in violations):
                    continue  # Already caught by departure buffer check

                buffer_hours = get_nofly_buffer_hours(topic) or 24
                buffer_days = buffer_hours // 24
                available = max(0, usable_days - buffer_days)

                activity_blocks = [
                    b for b in section.get("content_added", []) if b.get("type") == "activity"
                ]

                if len(activity_blocks) > available:
                    violations.append(
                        GuardViolation(
                            code=violation_code,
                            severity="blocking",
                            category="capacity",
                            message=(
                                f"Need {len(activity_blocks)} {topic} days but only "
                                f"{available} available ({buffer_hours}h buffer requires "
                                f"{buffer_days} rest day(s) before departure)"
                            ),
                        )
                    )
                    has_blocking = True
                    log(
                        "CONSTRAINT",
                        f"FAIL {violation_code} (blocking) - capacity: "
                        f"{len(activity_blocks)} > {available} available days",
                    )
        except Exception as e:
            log("GUARD", f"Capacity check error (non-fatal): {e}")

    # =========================================================================
    # Day Preference Capacity Check
    # Validates that requested activity day counts fit within trip duration
    # =========================================================================
    settings = get_trip_settings(state)
    day_prefs = settings.activity_settings.day_preferences
    if day_prefs:
        day_pref_violations = check_day_preference_capacity(
            start_date=state.trip_plan.start_date,
            end_date=state.trip_plan.end_date,
            day_prefs=day_prefs,
            strategy_sections=persistent.strategy_sections,
        )
        for v in day_pref_violations:
            violations.append(v)
            has_blocking = True
            log(
                "CONSTRAINT",
                f"FAIL {v.code} (blocking) - {v.message}",
            )

    # =========================================================================
    # Multi-Specialist Aggregate Capacity Check
    # Sums activity counts across ALL specialists. Individual checks pass
    # but combined they may exceed capacity. WARNING severity — builder
    # co-schedules up to 2 specialist activities/day (3-5h each).
    # =========================================================================
    if state.trip_plan.start_date and state.trip_plan.end_date:
        try:
            start = datetime.fromisoformat(state.trip_plan.start_date)
            end = datetime.fromisoformat(state.trip_plan.end_date)
            total_days = (end - start).days + 1
            usable_days = max(0, total_days - 2)

            total_activities = 0
            active_specialist_names: list[str] = []
            for section in persistent.strategy_sections:
                topic = section.get("specialist_type")
                if topic in ("general", "local_expert", None):
                    continue
                if section.get("feasibility_status") == "infeasible":
                    continue
                activity_blocks = [
                    b
                    for b in section.get("content_added", [])
                    if b.get("type") == "activity" and not b.get("is_buffer", False)
                ]
                if activity_blocks:
                    total_activities += len(activity_blocks)
                    active_specialist_names.append(topic)

            buffer_days_needed = 0
            for topic in active_specialist_names:
                src_config = get_config(topic)
                if not src_config:
                    continue
                for xd in src_config.cross_domain_blocks:
                    if set(active_specialist_names) & set(xd.target_specialists):
                        buffer_days_needed = max(buffer_days_needed, xd.buffer_hours // 24)

            effective_days = max(0, usable_days - buffer_days_needed)
            # Specialist activities are 3-5h each, max ~2 per day realistically
            max_capacity = effective_days * 2

            if len(active_specialist_names) >= 2 and total_activities > max_capacity:
                shortage = total_activities - max_capacity
                extend_by = (shortage + 1) // 2
                violations.append(
                    GuardViolation(
                        code="MULTI_SPECIALIST_CAPACITY_EXCEEDED",
                        message=(
                            f"{total_activities} activities across "
                            f"{', '.join(sorted(active_specialist_names))} "
                            f"exceed {effective_days}-day capacity"
                        ),
                        severity="warning",
                        category="capacity",
                        suggested_action=(
                            f"Extend trip by {extend_by} day(s) or reduce activities"
                        ),
                        conflicting_specialists=sorted(active_specialist_names),
                    )
                )
                log(
                    "CONSTRAINT",
                    f"WARN MULTI_SPECIALIST_CAPACITY_EXCEEDED - "
                    f"{total_activities} > {max_capacity} "
                    f"({effective_days} days x 2 specialist acts/day)",
                )
        except Exception as e:
            log("GUARD", f"Multi-specialist capacity check error (non-fatal): {e}")

    # =========================================================================
    # Cross-Domain Constraint Injection for Builder
    # ALWAYS inject when specialists co-exist, regardless of violation status.
    # The builder needs the constraint for sequencing (diving → buffer →
    # altitude) even when the trip is long enough that no violation is emitted.
    # =========================================================================
    for topic in persistent.executed_strategy_topics:
        src_config = get_config(topic)
        if not src_config:
            continue
        for xd in src_config.cross_domain_blocks:
            conflicting_topics = set(persistent.executed_strategy_topics) & set(
                xd.target_specialists
            )
            if not conflicting_topics:
                continue
            # Use canonical rule name that builder's _find_constraint() expects
            canonical_rule = "no_altitude_after_dive"
            constraint = SpecialistConstraint(
                constraint_id=canonical_rule,
                type="temporal",
                rule=canonical_rule,
                severity="blocking",
                applies_to_categories=["activities"],
                buffer_hours=xd.buffer_hours,
                reason=xd.reason,
            )
            rule_canon = canonicalize_rule(constraint.rule)
            if rule_canon not in existing_rules:
                state.trip_plan.constraints.append(constraint)
                existing_rules.add(rule_canon)
                # Persist for future turns
                if topic not in persisted:
                    persisted[topic] = []
                persisted[topic].append(constraint.model_dump())
                # Also inject into strategy section so expand-itinerary
                # builder can find it (builder reads constraints_applied,
                # not trip_plan.constraints).
                # StrategySection.constraints_applied is List[Dict[str, str]]
                # so we serialize to string-only dict format.
                section_constraint = {
                    "constraint_id": canonical_rule,
                    "type": "temporal",
                    "rule": canonical_rule,
                    "severity": "blocking",
                    "reason": xd.reason or "",
                }
                for section in persistent.strategy_sections:
                    if section.get("specialist_type") == topic:
                        section_rules = {
                            c.get("rule") for c in section.get("constraints_applied", [])
                        }
                        if canonical_rule not in section_rules:
                            section.setdefault("constraints_applied", []).append(section_constraint)
                        break
                log("GUARD", f"Injected cross-domain constraint: {constraint.rule}")

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
    # Validation Receipts — Registry-Driven
    # Green badges for constraints that PASSED. Surfaced in Trip DNA bar.
    # =========================================================================
    validated = []

    # --- System-level receipts ---
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

    # --- Specialist-level receipts (registry-driven) ---
    for topic in persistent.specialist_constraints:
        config = get_config(topic)
        if not config:
            continue
        # Only emit receipts for specialists with enforceable constraints
        if not (config.has_nofly_buffer or config.has_altitude_buffer):
            continue
        topic_upper = topic.upper()
        has_topic_violation = any(topic_upper in v.code for v in violations)
        if not has_topic_violation:
            validated.append(
                {
                    "constraint_id": f"{topic}_constraints_ok",
                    "rule": f"{topic}_constraints_satisfied",
                    "status": "satisfied",
                    "specialist": topic,
                    "label": config.display_name or topic.replace("_", " ").title(),
                }
            )

    turn.constraints_validated = validated
    for v in validated:
        log("CONSTRAINT", f"OK {v['constraint_id']} (satisfied) -- {v['label']}")

    # Update state
    state.constraints_violated = [v.message for v in violations]

    # Store detailed violations in metadata (typed)
    turn.constraint_violations = [v.to_dict() for v in violations]
    turn.has_blocking_violations = has_blocking

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
        previous_inputs = persistent.trip_inputs
        state.trip_plan.destination = previous_inputs.get("destination")  # Restore previous
        log(
            "GUARD",
            f"Rolled back to: dest={state.trip_plan.destination}",
        )

    # Prepare violation context for Architect retry (Auto-Fix Loop)
    if has_blocking:
        turn.violations_for_retry = [
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

    # Flush typed per-turn values back to state.metadata
    sync_turn_meta(state, turn)

    # STATE OUT logging - shows where state goes next and what changed
    logger.info(
        f"[GUARD] STATE OUT: tiles={len(state.tiles)} "
        f"strategy={len(persistent.strategy_sections)} "
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


# ── Arrangement validation (Stage 13A) ────────────────────────────────────────


def _apply_moves_to_cards(day_cards: list[dict], moves: list[dict]) -> list[dict]:
    """Clone day_cards and apply moves. Returns new list."""
    import copy

    cards = copy.deepcopy(day_cards)
    card_map = {dc["day_number"]: dc for dc in cards}

    for move in moves:
        block_id = move["block_id"]
        from_day = move["from_day"]
        to_day = move["to_day"]

        src = card_map.get(from_day)
        if not src:
            continue
        block = None
        for i, b in enumerate(src["blocks"]):
            if b.get("id") == block_id:
                block = src["blocks"].pop(i)
                break
        if not block:
            continue

        dst = card_map.get(to_day)
        if not dst:
            continue
        pos = min(move.get("to_position", len(dst["blocks"])), len(dst["blocks"]))
        dst["blocks"].insert(pos, block)

    return cards


def _arr_block_has_nofly(block: dict) -> bool:
    """Return True if this block's specialist has a no-fly buffer constraint."""
    cfg = get_config(block.get("specialist_type") or "")
    return bool(cfg and cfg.has_nofly_buffer)


def _arr_get_day(cards: list[dict], day_num: int) -> dict:
    return next((dc for dc in cards if dc["day_number"] == day_num), {"blocks": []})


def _arr_check_locked_blocks(day_cards: list[dict], moves: list[dict]) -> list[dict]:
    """Locked blocks (buffer, arrival, departure) cannot be moved."""
    violations = []
    block_map: dict[str, dict] = {}
    for dc in day_cards:
        for b in dc.get("blocks", []):
            if b.get("id"):
                block_map[b["id"]] = b

    locked_types = {"arrival", "departure", "check-in", "check-out"}
    for move in moves:
        block = block_map.get(move["block_id"])
        if not block:
            continue
        if block.get("is_buffer") or block.get("activity_type") in locked_types:
            violations.append(
                {
                    "block_id": move["block_id"],
                    "violation_code": "LOCKED_BLOCK",
                    "severity": "blocking",
                    "message": (
                        f"'{block.get('title') or block.get('activity_type', 'This block')}'"
                        " cannot be moved"
                    ),
                    "target_day": move["to_day"],
                }
            )
    return violations


def _arr_check_no_fly_buffer(rearranged: list[dict], trip_inputs: object) -> list[dict]:
    """Diving (or any no-fly specialist) blocks must not fall within buffer of departure."""
    violations = []
    end_date = getattr(trip_inputs, "end_date", None)
    if not end_date:
        return violations

    departure_day = max(dc["day_number"] for dc in rearranged)

    for dc in rearranged:
        for block in dc.get("blocks", []):
            if _arr_block_has_nofly(block):
                st = block.get("specialist_type", "")
                activity_name = block.get("title") or block.get("activity_type") or st
                buffer_hours = get_nofly_buffer_hours(st) or 24
                buffer_days = buffer_hours // 24
                if dc["day_number"] >= departure_day - buffer_days + 1:
                    violations.append(
                        {
                            "block_id": block.get("id", ""),
                            "violation_code": "NO_FLY_BUFFER",
                            "severity": "blocking",
                            "message": (
                                f"'{activity_name}' on Day {dc['day_number']} is too close to"
                                f" departure (Day {departure_day}) — needs {buffer_hours}h gap"
                            ),
                            "target_day": dc["day_number"],
                        }
                    )
    return violations


def _arr_check_cross_domain_adjacency(rearranged: list[dict]) -> list[dict]:
    """Check cross-domain adjacency violations using specialist registry."""
    violations = []
    day_specialist_map: dict[int, set[str]] = {}
    # Also track the actual block names per day for use in messages
    day_block_names: dict[int, dict[str, str]] = {}  # day_num → {specialist_type → activity name}
    for dc in rearranged:
        types = {b.get("specialist_type") for b in dc.get("blocks", []) if b.get("specialist_type")}
        day_specialist_map[dc["day_number"]] = types
        names: dict[str, str] = {}
        for b in dc.get("blocks", []):
            st = b.get("specialist_type")
            if st and st not in names:
                names[st] = b.get("title") or b.get("activity_type") or st
        day_block_names[dc["day_number"]] = names

    for day_num, types in day_specialist_map.items():
        prev_types = day_specialist_map.get(day_num - 1, set())
        for st in types:
            for prev_st in prev_types:
                cfg = get_config(prev_st)
                if not cfg:
                    continue
                if any(st in xd.target_specialists for xd in cfg.cross_domain_blocks):
                    target_blocks = [
                        b
                        for b in _arr_get_day(rearranged, day_num).get("blocks", [])
                        if b.get("specialist_type") == st
                    ]
                    prev_activity = day_block_names.get(day_num - 1, {}).get(prev_st, prev_st)
                    for b in target_blocks:
                        this_activity = b.get("title") or b.get("activity_type") or st
                        violations.append(
                            {
                                "block_id": b.get("id", ""),
                                "violation_code": "CROSS_DOMAIN_BUFFER_REQUIRED",
                                "severity": "blocking",
                                "message": (
                                    f"'{prev_activity}' on Day {day_num - 1} needs a buffer day "
                                    f"before {st.title()} on Day {day_num} — "
                                    f"move '{this_activity}' to Day {day_num + 1} or later"
                                ),
                                "target_day": day_num,
                            }
                        )
    return violations


def _arr_check_day_capacity(rearranged: list[dict], max_blocks: int = 3) -> list[dict]:
    """Target day can't exceed max activity blocks."""
    violations = []
    skip_types = {"arrival", "departure", "free_day", "check-in", "check-out"}
    for dc in rearranged:
        real_blocks = [
            b
            for b in dc.get("blocks", [])
            if not b.get("is_buffer") and b.get("activity_type") not in skip_types
        ]
        if len(real_blocks) > max_blocks:
            violations.append(
                {
                    "block_id": real_blocks[-1].get("id", ""),
                    "violation_code": "DAY_CAPACITY_EXCEEDED",
                    "severity": "warning",
                    "message": (
                        f"Day {dc['day_number']} has {len(real_blocks)} activities"
                        f" (max {max_blocks})"
                    ),
                    "target_day": dc["day_number"],
                }
            )
    return violations


def validate_block_arrangement(
    day_cards: list[dict],
    moves: list[dict],
    trip_inputs: object,
) -> list[dict]:
    """
    Validate proposed block moves against active constraints.
    Pure Python, no LLM, target <50ms.

    Only reports violations caused by the proposed moves — not pre-existing
    violations in the original itinerary. This prevents the guard from
    rejecting valid moves due to constraints already present before the drag.

    Returns list of BlockViolation dicts.
    """
    # Check locked blocks on original cards (before applying moves)
    violations = _arr_check_locked_blocks(day_cards, moves)

    # If any locked-block violations, stop here — moves are invalid
    if any(v["severity"] == "blocking" for v in violations):
        return violations

    # Track which block_ids are being moved, and which days they're moving TO/FROM
    moved_block_ids = {m["block_id"] for m in moves}
    destination_days = {m["to_day"] for m in moves}
    source_days = {m["from_day"] for m in moves}

    # Cross-domain adjacency checks are N vs N±1 (e.g. dive on Day 3 → buffer on Day 4,
    # hiking on Day 5 = violation). A move to Day 4 can create a violation on Day 5's block.
    # Expand to ±1 radius around all touched days so collateral violations are not silently dropped.
    affected_days: set[int] = set()
    for d in destination_days | source_days:
        affected_days.update({d - 1, d, d + 1})

    # Apply moves to get rearranged state
    rearranged = _apply_moves_to_cards(day_cards, moves)

    # Collect all violations on the rearranged state
    all_violations = []
    all_violations += _arr_check_no_fly_buffer(rearranged, trip_inputs)
    all_violations += _arr_check_cross_domain_adjacency(rearranged)
    all_violations += _arr_check_day_capacity(rearranged)

    # Filter: only keep violations that affect moved blocks or days adjacent to the move.
    # Using affected_days (±1 radius) rather than exact destination_days catches collateral
    # violations on neighboring blocks (e.g. hiking on Day 5 when dive lands on Day 4).
    violations += [
        v
        for v in all_violations
        if v.get("block_id") in moved_block_ids or v.get("target_day") in affected_days
    ]

    return violations
