"""
Gates Package - P3 Module Extraction.

This package contains the gate evaluation system for routing decisions.

Exports:
    Gate: Abstract base class for gate implementations
    GateContext: Context object passed to gate evaluate() methods
    GatePrecedence: IntEnum defining gate priority ordering
    GateResult: Dataclass containing gate evaluation results
    DateErrorCode: Class with date error code constants
    DATE_BLOCKING_ERROR_CODES: Set of error codes that block progression
    CORE_FIELD_PRIORITY: Priority order for collecting trip fields
    CANONICAL_FIELD_ORDER: Stable ordering for observability
    GateEvaluator: Centralized gate evaluator class

Usage:
    from app.planner.gates import Gate, GateContext
    from app.planner.gates import GatePrecedence, GateResult
    from app.planner.gates import DateErrorCode, DATE_BLOCKING_ERROR_CODES
    from app.planner.gates import CORE_FIELD_PRIORITY
    from app.planner.gates import GateEvaluator
"""

from app.planner.gates.base import Gate, GateContext
from app.planner.gates.constants import (
    CANONICAL_FIELD_ORDER,
    CORE_FIELD_PRIORITY,
    DATE_BLOCKING_ERROR_CODES,
    DateErrorCode,
)
from app.planner.gates.evaluator_v2 import GateEvaluator
from app.planner.gates.intent_detection import (
    check_intent_only_input,
    check_question_keyword_combo,
)
from app.planner.gates.keyword_utils import keyword_match
from app.planner.gates.precedence import GatePrecedence
from app.planner.gates.readiness import TripReadiness, compute_trip_readiness
from app.planner.gates.result import GateResult
from app.planner.gates.suppression import SuppressionPredicates
from app.planner.gates.topic_detection import (
    ALL_STRATEGY_KEYWORDS,
    STRATEGY_TOPIC_PATTERNS,
    detect_strategy_topic,
    detect_strategy_topic_from_settings,
    detect_strategy_topic_from_text,
    detect_strategy_topic_from_text_precise,
    has_strategy_topic,
    text_contains_strategy_keyword,
)
from app.planner.gates.types import (
    ExtractionConfidence,
    GraphMetadata,
    ReadinessSnapshot,
)

__all__ = [
    # P2: Base classes
    "Gate",
    "GateContext",
    "GatePrecedence",
    "GateResult",
    # P3: Constants
    "DateErrorCode",
    "DATE_BLOCKING_ERROR_CODES",
    "CORE_FIELD_PRIORITY",
    "CANONICAL_FIELD_ORDER",
    # P4: Readiness
    "TripReadiness",
    "compute_trip_readiness",
    # P5: GateEvaluator
    "GateEvaluator",
    # P6: Types
    "GraphMetadata",
    "ExtractionConfidence",
    "ReadinessSnapshot",
    # P7: Suppression
    "SuppressionPredicates",
    # Topic detection utilities
    "detect_strategy_topic",
    "detect_strategy_topic_from_text",
    "detect_strategy_topic_from_text_precise",
    "detect_strategy_topic_from_settings",
    "has_strategy_topic",
    "text_contains_strategy_keyword",
    "ALL_STRATEGY_KEYWORDS",
    "STRATEGY_TOPIC_PATTERNS",
    # Keyword matching utility
    "keyword_match",
    # Intent detection utilities
    "check_intent_only_input",
    "check_question_keyword_combo",
]
