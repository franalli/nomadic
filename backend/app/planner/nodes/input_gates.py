"""
Input Gate Validation -- extensible pre-routing validation.

Gates validate extracted trip fields BEFORE routing.
Blocking gates short-circuit to synthesizer.
Warnings continue with notes appended to synthesis context.

Design: Subclass InputGate, implement evaluate(), add to _DEFAULT_GATES.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Literal, Optional, Tuple

from app.planner.nodes.input_gate_config import GATE_THRESHOLDS
from app.planner.state import TripPlan

logger = logging.getLogger(__name__)


@dataclass
class GateResult:
    gate_name: str
    severity: Literal["blocking", "warning"]
    code: str
    message: str
    suggested_action: Optional[str] = None
    field: Optional[str] = None


class InputGate(ABC):
    @abstractmethod
    def evaluate(self, trip_plan: TripPlan, thresholds: Dict[str, Any]) -> Optional[GateResult]: ...


class DateGate(InputGate):
    def evaluate(self, trip_plan, thresholds):
        s, e = trip_plan.start_date, trip_plan.end_date
        if not s or not e:
            return None

        today = date.today()
        try:
            start = date.fromisoformat(s) if isinstance(s, str) else s
            end = date.fromisoformat(e) if isinstance(e, str) else e
        except (ValueError, TypeError):
            return GateResult(
                "DateGate",
                "blocking",
                "invalid_date_format",
                "Couldn't parse those dates -- try a format like 'Feb 15-25'.",
                field="start_date",
            )

        if end < start:
            return GateResult(
                "DateGate",
                "blocking",
                "end_before_start",
                "The end date is before the start date.",
                suggested_action="Swap them or pick new dates.",
                field="end_date",
            )
        if start < today:
            return GateResult(
                "DateGate",
                "blocking",
                "date_in_past",
                f"Start date {s} is in the past.",
                suggested_action="Pick a future date.",
                field="start_date",
            )
        days_out = (start - today).days
        if days_out > thresholds["max_days_in_future"]:
            months = thresholds["max_days_in_future"] // 30
            return GateResult(
                "DateGate",
                "blocking",
                "too_far_future",
                f"That's over {months} months out -- we can't reliably plan that far ahead.",
                suggested_action=f"Try dates within the next {months} months.",
                field="start_date",
            )
        return None


class DurationGate(InputGate):
    def evaluate(self, trip_plan, thresholds):
        s, e = trip_plan.start_date, trip_plan.end_date
        if not s or not e:
            return None
        try:
            start = date.fromisoformat(s) if isinstance(s, str) else s
            end = date.fromisoformat(e) if isinstance(e, str) else e
        except (ValueError, TypeError):
            return None

        days = (end - start).days + 1
        if days < thresholds.get("min_trip_days", 1):
            return GateResult(
                "DurationGate",
                "blocking",
                "trip_too_short",
                "A trip needs to be at least 1 day.",
                field="end_date",
            )
        if days > thresholds["max_trip_days"]:
            return GateResult(
                "DurationGate",
                "blocking",
                "trip_too_long",
                f"A {days}-day trip exceeds our {thresholds['max_trip_days']}-day limit.",
                suggested_action=f"Try {thresholds['max_trip_days']} days or less.",
                field="end_date",
            )
        if days > thresholds["warn_trip_days"]:
            return GateResult(
                "DurationGate",
                "warning",
                "trip_long",
                f"A {days}-day trip is quite long -- some logistics may be less precise.",
                field="end_date",
            )
        return None


class TravelerGate(InputGate):
    def evaluate(self, trip_plan, thresholds):
        adults = trip_plan.adults or 0
        children = trip_plan.children or 0
        total = adults + children
        if total == 0:
            return None

        if adults == 0 and children > 0:
            return GateResult(
                "TravelerGate",
                "blocking",
                "children_without_adult",
                "At least one adult traveler is needed.",
                field="adults",
            )
        if total > thresholds["max_total_travelers"]:
            return GateResult(
                "TravelerGate",
                "blocking",
                "too_many_travelers",
                f"We support up to {thresholds['max_total_travelers']} travelers "
                f"-- you've got {total}.",
                suggested_action="For large groups, consider splitting into separate trips.",
                field="adults",
            )
        return None


class BudgetGate(InputGate):
    def evaluate(self, trip_plan, thresholds):
        budget = trip_plan.budget
        if budget is None:
            return None
        if budget < thresholds["min_budget_usd"]:
            return GateResult(
                "BudgetGate",
                "blocking",
                "budget_too_low",
                f"A ${budget} budget is too low for trip planning.",
                suggested_action="Most trips start around $50/day minimum.",
                field="budget",
            )
        if budget > thresholds["max_budget_usd"]:
            return GateResult(
                "BudgetGate",
                "blocking",
                "budget_extreme",
                f"A ${budget:,} budget is outside our planning range.",
                field="budget",
            )
        if budget > thresholds["warn_budget_high_usd"]:
            return GateResult(
                "BudgetGate",
                "warning",
                "budget_high",
                f"With a ${budget:,} budget, we'll focus on premium options.",
                field="budget",
            )
        return None


class DestinationGate(InputGate):
    """
    Detects multi-destination input.
    PRIMARY: LLM-set _multi_dest_from_llm flag (avoids false positives).
    FALLBACK: Only splits on comma when 3+ parts detected.
    Never splits on "and".
    """

    def evaluate(self, trip_plan, thresholds):
        dest = trip_plan.destination
        if not dest:
            return None

        multi_flag = getattr(trip_plan, "_multi_dest_from_llm", False)
        deferred = getattr(trip_plan, "_deferred_destinations", [])

        if multi_flag and deferred:
            return GateResult(
                gate_name="DestinationGate",
                severity="warning",
                code="multi_destination_detected",
                message=(
                    f"Starting with {dest} -- we can plan "
                    f"{', '.join(deferred)} after this itinerary is set."
                ),
                field="destination",
            )

        parts = [p.strip() for p in dest.split(",") if p.strip()]
        if len(parts) >= 3:
            trip_plan.destination = parts[0]
            rest = parts[1:]
            return GateResult(
                gate_name="DestinationGate",
                severity="warning",
                code="multi_destination_detected",
                message=(
                    f"Starting with {parts[0]} -- we can plan "
                    f"{', '.join(rest)} after this itinerary is set."
                ),
                field="destination",
            )

        return None


_DEFAULT_GATES: List[InputGate] = [
    DateGate(),
    DurationGate(),
    TravelerGate(),
    BudgetGate(),
    DestinationGate(),
]


class GateRegistry:
    """Runs all registered gates. Fail-open: gate exceptions logged and skipped."""

    def __init__(self, gates: Optional[List[InputGate]] = None):
        self._gates = gates or list(_DEFAULT_GATES)
        self._thresholds = dict(GATE_THRESHOLDS)

    def register(self, gate: InputGate) -> None:
        self._gates.append(gate)

    def run_all(self, trip_plan: TripPlan) -> Tuple[List[GateResult], List[GateResult]]:
        """Returns (blocking_results, warning_results)."""
        blockers: List[GateResult] = []
        warnings: List[GateResult] = []

        for gate in self._gates:
            try:
                result = gate.evaluate(trip_plan, self._thresholds)
                if result is None:
                    continue
                if result.severity == "blocking":
                    blockers.append(result)
                else:
                    warnings.append(result)
            except Exception as e:
                logger.warning(f"[INPUT_GATE] {gate.__class__.__name__} raised: {e}")

        return blockers, warnings
