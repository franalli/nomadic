"""
Gate Precedence Enum - P1 Module Extraction.

This module defines the ordering of routing gates in the GateEvaluator.
Gates are checked in priority order; first match wins.

Usage:
    from app.planner.gates import GatePrecedence

    if gate.value < GatePrecedence.CORE_COLLECTION.value:
        # Higher priority gate
        ...
"""

from enum import IntEnum


class GatePrecedence(IntEnum):
    """
    Explicit ordering of routing gates in GateEvaluator.evaluate().
    Gates are checked in priority order; first match wins.

    Gate Ordering (increments of 10 for future insertions):
    - STRATEGY_EXPANSION (10): User requesting expansion on existing strategy
    - GENERATE_REQUESTED (20): Explicit generate request detected
    - SHORT_CIRCUIT (30): High priority for greetings/confirmations
    - STRATEGY_POST_CORE (35): Stage 1 trigger when core complete after stage 0
    - READY_NO_FIELDS (40): Plan is ready, no fields to ask
    - FAST_PATH (50): Bootstrap optimization (turn 1 only when strategy_bootstrap_active)
    - SPECIALIST_PRE_CORE (60): Domain keywords before core complete
    - STRATEGY_TOPIC_SWITCH (70): Mid-session topic changes (e.g., adding "diving")
    - STRATEGY_PRE_CORE_VALUE (80): Strategy topic detected -> value-first response
    - CORE_COLLECTION (90): Collect missing core fields
    - QUESTION_KEYWORD (110): Question-word + domain keyword combo + heuristics
    - ROUTER_LLM (999): Fallback to LLM classification
    """

    STRATEGY_EXPANSION = 10  # User requesting expansion on existing strategy content
    GENERATE_REQUESTED = 20  # Explicit generate request (pattern match or pending_action)
    SHORT_CIRCUIT = 30  # Greeting, acknowledgment, off-topic
    STRATEGY_POST_CORE = 35  # Stage 1 trigger: core complete after stage 0
    READY_NO_FIELDS = 40  # Plan ready, missing_all empty, no blocking errors
    FAST_PATH = 50  # Direct field updates (bootstrap only when strategy_bootstrap_active)
    SPECIALIST_PRE_CORE = 60  # Specialist keyword when core fields missing (pre-core mode)
    STRATEGY_TOPIC_SWITCH = 70  # Mid-session strategy topic change (e.g., "diving")
    STRATEGY_PRE_CORE_VALUE = 80  # Strategy topic detected -> value-first response
    CORE_COLLECTION = 90  # Core fields missing -> required_fields
    QUESTION_KEYWORD = 110  # Question-word + domain keyword combo + keyword heuristic
    ROUTER_LLM = 999  # Default: invoke router LLM
