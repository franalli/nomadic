"""
Trip Readiness - P3 Module Extraction.

Defines the TripReadiness dataclass used for canonical trip state computation.
This consolidates missing fields computation across all routing decisions.

The compute_trip_readiness() function remains in plan_graph.py for now
due to dependencies on GraphState and error types. It will be migrated
in a future phase.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TripReadiness:
    """
    Canonical trip readiness state - computed once, used everywhere.

    This consolidates _compute_missing_fields, _has_required_core_fields,
    and _get_missing_fields_summary into a single authoritative computation.

    Created by compute_trip_readiness() in plan_graph.py.
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


__all__ = ["TripReadiness"]
