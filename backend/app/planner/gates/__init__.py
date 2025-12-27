"""
Gates Package - P3 Module Extraction.

This package contains the gate evaluation system for routing decisions.

Exports:
    GatePrecedence: IntEnum defining gate priority ordering
    GateResult: Dataclass containing gate evaluation results
    DateErrorCode: Class with date error code constants
    DATE_BLOCKING_ERROR_CODES: Set of error codes that block progression
    CORE_FIELD_PRIORITY: Priority order for collecting trip fields
    CANONICAL_FIELD_ORDER: Stable ordering for observability

Usage:
    from app.planner.gates import GatePrecedence, GateResult
    from app.planner.gates import DateErrorCode, DATE_BLOCKING_ERROR_CODES
    from app.planner.gates import CORE_FIELD_PRIORITY

Future (P3+):
    from app.planner.gates import GateEvaluator
"""

from app.planner.gates.constants import (
    CANONICAL_FIELD_ORDER,
    CORE_FIELD_PRIORITY,
    DATE_BLOCKING_ERROR_CODES,
    DateErrorCode,
)
from app.planner.gates.precedence import GatePrecedence
from app.planner.gates.readiness import TripReadiness
from app.planner.gates.result import GateResult

__all__ = [
    "GatePrecedence",
    "GateResult",
    # P3: Constants
    "DateErrorCode",
    "DATE_BLOCKING_ERROR_CODES",
    "CORE_FIELD_PRIORITY",
    "CANONICAL_FIELD_ORDER",
    # P3: Readiness
    "TripReadiness",
]
