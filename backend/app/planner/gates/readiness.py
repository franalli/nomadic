"""
Trip Readiness - P4 Module Extraction.

Defines the TripReadiness dataclass and compute_trip_readiness() function
for canonical trip state computation. This consolidates missing fields
computation across all routing decisions.

Usage:
    from app.planner.gates import TripReadiness, compute_trip_readiness

    readiness = compute_trip_readiness(trip_inputs, prefer_date_first=True)
    if readiness.core_complete:
        # Proceed with specialist routing
    else:
        # Ask about readiness.question_target
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from app.planner.gates.constants import (
    CORE_FIELD_PRIORITY,
    DATE_BLOCKING_ERROR_CODES,
    DateErrorCode,
)

if TYPE_CHECKING:
    pass


@dataclass
class TripReadiness:
    """
    Canonical trip readiness state - computed once, used everywhere.

    This consolidates _compute_missing_fields, _has_required_core_fields,
    and _get_missing_fields_summary into a single authoritative computation.

    Created by compute_trip_readiness().
    """

    # Core required fields (destinations, origin, start_date)
    missing_core: List[str] = field(default_factory=list)
    # All required fields (core + end_date + adults + budget)
    missing_all: List[str] = field(default_factory=list)
    # Which field to ask about next (priority order)
    question_target: Optional[str] = None
    # Whether all core fields are present
    core_complete: bool = False
    # Whether ready to generate plan
    ready_to_generate: bool = False
    # Human-readable summary for prompt injection
    missing_summary: str = "none - all required fields collected"
    # Blocking errors that prevent routing to specialists/generation
    # (e.g., DATE_AMBIGUOUS_YEAR, DATE_RANGE_INVALID)
    blocking_errors: List[str] = field(default_factory=list)

    @property
    def has_destinations(self) -> bool:
        """Check if destinations are set."""
        return "destinations" not in self.missing_core

    @property
    def has_origin(self) -> bool:
        """Check if origin is set."""
        return "origin" not in self.missing_core

    @property
    def has_dates(self) -> bool:
        """Check if start_date is set."""
        return "start_date" not in self.missing_core

    @property
    def has_blocking_errors(self) -> bool:
        """Check if any blocking errors exist that prevent progression."""
        return len(self.blocking_errors) > 0


def compute_trip_readiness(
    trip_inputs: Any,
    prefer_date_first: bool = False,
    errors: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> TripReadiness:
    """
    Compute canonical trip readiness state.

    This is the ONLY function that should compute missing fields.
    All nodes must use this instead of inline checks.

    Args:
        trip_inputs: Current trip inputs (TripInputs object or dict)
        prefer_date_first: If True, prioritize start_date over destinations
            when determining question_target. Used for broad/open-ended queries.
        errors: Optional list of errors to check for blocking errors.
            Supports: ErrorRecord (new), NormalizationError, dict (legacy), str (legacy)
        metadata: Optional metadata dict to check for date_clarify_mode

    Returns:
        TripReadiness with all computed fields including blocking_errors
    """
    # Handle both TripInputs object and dict
    if hasattr(trip_inputs, "destinations"):
        # TripInputs object
        ti = trip_inputs
        destinations = ti.destinations
        origin = ti.origin
        start_date = ti.start_date
        end_date = ti.end_date
        adults = ti.adults
        budget = ti.budget
    else:
        # Dict
        destinations = trip_inputs.get("destinations", [])
        origin = trip_inputs.get("origin")
        start_date = trip_inputs.get("start_date")
        end_date = trip_inputs.get("end_date")
        adults = trip_inputs.get("adults")
        budget = trip_inputs.get("budget")

    # Extract flexible dates fields
    if hasattr(trip_inputs, "date_flex"):
        date_flex = trip_inputs.date_flex
        trip_duration = trip_inputs.trip_duration
    else:
        date_flex = trip_inputs.get("date_flex", False)
        trip_duration = trip_inputs.get("trip_duration")

    # Compute missing core fields using CORE_FIELD_PRIORITY as single source of truth
    # This ensures priority order is consistent: destinations -> start_date -> end_date
    # -> origin -> adults -> budget
    field_values = {
        "destinations": destinations if isinstance(destinations, list) and destinations else None,
        "start_date": start_date,
        "end_date": end_date,
        "origin": origin,
        "adults": adults,
        "budget": budget,
    }
    missing_candidates = {f for f, v in field_values.items() if not v}
    # Filter to only core fields (first 4 in CORE_FIELD_PRIORITY: destinations,
    # start_date, end_date, origin)
    core_fields = {"destinations", "start_date", "origin"}  # end_date handled separately below
    missing_core = [f for f in CORE_FIELD_PRIORITY if f in missing_candidates and f in core_fields]

    # If date_flex is True, dates are "answered" - remove start_date from missing_core
    if date_flex and "start_date" in missing_core:
        missing_core.remove("start_date")

    # Compute all missing fields (core + optional but useful)
    missing_all = list(missing_core)
    if not end_date:
        missing_all.append("end_date")
    if adults is None:
        missing_all.append("travelers (adults)")
    # Budget is optional - don't add to missing if user explicitly said "no budget"/"flexible"
    budget_answered = metadata.get("budget_answered", False) if metadata else False
    if budget is None and not budget_answered:
        missing_all.append("budget")
    # If date_flex is set but trip_duration is missing, add duration to missing_all
    if date_flex and not trip_duration:
        missing_all.append("duration")

    # Compute blocking errors from errors list
    # Supports: ErrorRecord (new), NormalizationError, dict (legacy), str (legacy)
    blocking_errors: List[str] = []
    if errors:
        for err in errors:
            # Check for ErrorRecord (Pydantic model with severity and code)
            if hasattr(err, "severity") and hasattr(err, "code"):
                if err.severity == "blocking" or err.code in DATE_BLOCKING_ERROR_CODES:
                    blocking_errors.append(err.code)
            # Check for NormalizationError (dataclass with code attribute)
            elif hasattr(err, "code") and err.code in DATE_BLOCKING_ERROR_CODES:
                blocking_errors.append(err.code)
            elif isinstance(err, dict):
                # Handle dict errors with "code" key (legacy)
                code = err.get("code", "")
                if code in DATE_BLOCKING_ERROR_CODES:
                    blocking_errors.append(code)
            elif isinstance(err, str):
                for code in DATE_BLOCKING_ERROR_CODES:
                    if code in err:
                        blocking_errors.append(code)
                        break
    # Also check metadata for date_clarify_mode
    if metadata and metadata.get("date_clarify_mode"):
        if DateErrorCode.AMBIGUOUS_YEAR not in blocking_errors:
            blocking_errors.append(DateErrorCode.AMBIGUOUS_YEAR)

    # Determine question target (priority order)
    # Context-aware: if prefer_date_first and both destinations and dates are missing,
    # ask about dates first (helps with strategy recommendations)
    # OVERRIDE: If blocking date errors exist, always ask about dates first
    question_target = None
    if blocking_errors:
        question_target = "dates"
    elif date_flex and not trip_duration:
        # Flexible dates set but no duration - ask for duration immediately
        question_target = "duration"
    elif missing_core:
        if prefer_date_first and "destinations" in missing_core and "start_date" in missing_core:
            # Prefer start_date over destinations for open-ended queries
            question_target = "dates"
        else:
            question_target = missing_core[0]
            # Normalize "start_date" to "dates" for user-facing questions
            if question_target == "start_date":
                question_target = "dates"
    elif missing_all:
        # All core complete, ask about optional fields
        first_optional = [
            f for f in missing_all if f not in ["destinations", "origin", "start_date"]
        ]
        if first_optional:
            field = first_optional[0]
            # Normalize field names for user-facing
            if field == "travelers (adults)":
                question_target = "travelers"
            else:
                question_target = field

    # Compute readiness
    core_complete = len(missing_core) == 0
    # ready_to_generate requires core complete AND no blocking errors
    ready_to_generate = core_complete and len(blocking_errors) == 0

    # Build summary string
    if missing_all:
        missing_summary = ", ".join(missing_all)
    else:
        missing_summary = "none - all required fields collected"

    return TripReadiness(
        missing_core=missing_core,
        missing_all=missing_all,
        question_target=question_target,
        core_complete=core_complete,
        ready_to_generate=ready_to_generate,
        missing_summary=missing_summary,
        blocking_errors=blocking_errors,
    )


def is_dates_structurable(trip_inputs: Any) -> bool:
    """
    Check if date info exists (partial OK for receipts).
    Returns True if start_date OR end_date is set.

    Used by: Receipt system to show "dates" pill even with partial info.
    """
    if hasattr(trip_inputs, "start_date"):
        return bool(trip_inputs.start_date or trip_inputs.end_date)
    return bool(trip_inputs.get("start_date") or trip_inputs.get("end_date"))


def is_dates_placeable(trip_inputs: Any) -> bool:
    """
    Check if dates can anchor a plan (both start AND end).
    Returns True if start_date AND end_date are set.

    Used by: Readiness checks, plan generation guards.
    """
    if hasattr(trip_inputs, "start_date"):
        return bool(trip_inputs.start_date and trip_inputs.end_date)
    return bool(trip_inputs.get("start_date") and trip_inputs.get("end_date"))


__all__ = ["TripReadiness", "compute_trip_readiness", "is_dates_structurable", "is_dates_placeable"]
