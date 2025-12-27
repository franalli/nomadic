"""
Gate Checks Package - P3 Module Extraction.

This package will contain individual gate check functions extracted from
GateEvaluator. Each check function tests a specific routing condition.

Planned structure (P3+):
    checks/
    ├── __init__.py          # This file - package exports
    ├── strategy.py          # Strategy-related gate checks
    ├── short_circuit.py     # Short-circuit detection (greetings, etc.)
    ├── intent.py            # Intent detection (question + keyword combos)
    └── specialist.py        # Specialist routing checks

Current exports: None (structure only in P3)

Future usage:
    from app.planner.gates.checks import (
        check_strategy_expansion,
        check_short_circuit,
        check_intent_only,
    )
"""

__all__: list[str] = []
