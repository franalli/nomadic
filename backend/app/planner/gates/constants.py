"""
Gate Constants - P3 Module Extraction.

Defines constants used across gate evaluation, including:
- Field priority ordering for question targeting
- Date error codes and blocking error sets
- Canonical field ordering for observability
"""

from typing import List

# =============================================================================
# CORE FIELD PRIORITY
# =============================================================================
# Priority order for collecting trip fields.
# Used by TripReadiness to determine question_target.
# Order: destinations → start_date → end_date → origin → adults → budget
CORE_FIELD_PRIORITY: List[str] = [
    "destinations",
    "start_date",
    "end_date",
    "origin",
    "adults",
    "budget",
]


# =============================================================================
# CANONICAL FIELD ORDER (v5 Routing Observability)
# =============================================================================
# Stable ordering for deltas_applied in RoutingDecisionFinal.
# Used to ensure deterministic field ordering across Python versions.
CANONICAL_FIELD_ORDER: List[str] = [
    "destinations",
    "origin",
    "start_date",
    "end_date",
    "adults",
    "children",
    "budget",
    "activity_settings",
    "flight_settings",
    "hotel_settings",
    "transport_settings",
    "booking_types",
    "strategy_settings",
]


# =============================================================================
# DATE ERROR CODES
# =============================================================================
class DateErrorCode:
    """Explicit error codes for date-related issues."""

    AMBIGUOUS_YEAR = "DATE_AMBIGUOUS_YEAR"  # Month-day range straddles today
    RANGE_INVALID = "DATE_RANGE_INVALID"  # start_date > end_date after all corrections
    PARSE_FAILED = "DATE_PARSE_FAILED"  # Could not parse date at all
    FORMAT_AMBIGUOUS = "DATE_FORMAT_AMBIGUOUS"  # DD/MM vs MM/DD ambiguity (future)


# Error codes that block progression (require user clarification)
DATE_BLOCKING_ERROR_CODES = frozenset(
    {
        DateErrorCode.AMBIGUOUS_YEAR,
        DateErrorCode.RANGE_INVALID,
    }
)


__all__ = [
    "CORE_FIELD_PRIORITY",
    "CANONICAL_FIELD_ORDER",
    "DateErrorCode",
    "DATE_BLOCKING_ERROR_CODES",
]
