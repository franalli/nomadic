"""
Specialist Base - Shared constants and utilities for specialist nodes.

Contains:
- Constants for specialist configuration
- Field validation helpers
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Set

if TYPE_CHECKING:
    pass

# Core fields that domain specialists should not modify
CORE_FIELDS: Set[str] = {
    "destinations",
    "origin",
    "start_date",
    "end_date",
    "adults",
    "children",
    "budget",
    "currency",
}

# Fields that correction node is allowed to modify
CORRECTION_ALLOWED_FIELDS: Set[str] = {
    "destinations",
    "origin",
    "start_date",
    "end_date",
    "adults",
    "children",
    "budget",
    "currency",
    "flight_settings",
    "hotel_settings",
    "transport_settings",
    "activity_settings",
}

# Fields that correction should NEVER modify
CORRECTION_SKIP_FIELDS: Set[str] = {
    "strategy_settings",
    "booking_types",
}

# Specialist types that use domain-specific prompts
SPECIALIST_TYPES: Set[str] = {"flights", "hotels", "transport", "activities"}

# Valid question target values
QUESTION_TARGET_FIELD_MAP = {
    "dates": lambda t: bool(t.start_date),
    "start_date": lambda t: bool(t.start_date),
    "end_date": lambda t: bool(t.end_date),
    "destinations": lambda t: bool(t.destinations),
    "origin": lambda t: bool(t.origin),
    "travelers": lambda t: t.adults is not None,
    "adults": lambda t: t.adults is not None,
    "budget": lambda t: t.budget is not None,
    "currency": lambda t: bool(t.currency),
}


def get_skip_fields_for_specialist(name: str) -> Set[str]:
    """
    Get the set of fields to skip when applying LLM delta for a specialist.

    required_fields: can modify all fields
    correction: has restricted scope
    domain specialists: block core fields
    """
    if name == "required_fields":
        return set()  # Allow all field modifications
    elif name == "correction":
        return CORRECTION_SKIP_FIELDS
    else:
        return CORE_FIELDS
