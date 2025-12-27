"""
Gate Checks Package - P4 Module Extraction.

This package contains individual gate check functions extracted from
GateEvaluator. Each check function tests a specific routing condition.

Structure:
    checks/
    ├── __init__.py          # This file - package exports
    ├── strategy.py          # Strategy expansion detection
    └── short_circuit.py     # Vague affirmation detection

Usage:
    from app.planner.gates.checks import (
        is_strategy_expansion_request,
        StrategyExpansionResult,
        is_vague_affirmation,
    )
"""

from app.planner.gates.checks.short_circuit import (
    VAGUE_AFFIRMATIONS,
    is_vague_affirmation,
)
from app.planner.gates.checks.strategy import (
    FULL_EXPANSION_TRIGGERS,
    GENERIC_EXPANSION_TRIGGERS,
    SECTION_EXPANSION_PATTERNS,
    STRATEGY_TIER_MAX_TOKENS,
    StrategyExpansionResult,
    StrategyExpansionTarget,
    StrategyTier,
    is_strategy_expansion_request,
)

__all__ = [
    # Strategy expansion
    "StrategyExpansionTarget",
    "StrategyTier",
    "STRATEGY_TIER_MAX_TOKENS",
    "StrategyExpansionResult",
    "is_strategy_expansion_request",
    "FULL_EXPANSION_TRIGGERS",
    "SECTION_EXPANSION_PATTERNS",
    "GENERIC_EXPANSION_TRIGGERS",
    # Short-circuit detection
    "VAGUE_AFFIRMATIONS",
    "is_vague_affirmation",
]
