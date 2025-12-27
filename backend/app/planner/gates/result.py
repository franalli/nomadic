"""
Gate Result Dataclass - P1 Module Extraction.

This module defines the GateResult dataclass returned by GateEvaluator.evaluate().
The result contains the gate decision and metadata for routing and observability.

Usage:
    from app.planner.gates import GateResult, GatePrecedence

    result = GateResult(
        gate_fired=GatePrecedence.SHORT_CIRCUIT,
        destination="short_circuit_responder",
        reason="greeting:hello",
    )
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.planner.gates.precedence import GatePrecedence


@dataclass
class GateResult:
    """Result of gate evaluation - computed once per routing decision.

    Stored immutably in state.metadata["gate_result"] for observability.

    Attributes:
        gate_fired: Which gate matched and produced this result
        destination: Node name to route to
        reason: Human-readable explanation of the routing decision
        skipped_gates: Gates evaluated but not fired (for debugging)
        eval_time_ms: Time taken to evaluate all gates
        intent: Detected intent (e.g., "strategy", "specialist", "required_fields")
        strategy_topic: Strategy topic if applicable (e.g., "hiking", "diving")
        question_target: Field to ask about (e.g., "destinations", "dates")
        metadata_updates: Additional metadata to merge into state
        lqa_reason: LQA pre-pass reason if applicable
        llm_budget_used: Number of LLM calls at gate evaluation time
        date_clarify_mode: Whether date clarification is active
    """

    gate_fired: GatePrecedence
    destination: str  # Node to route to
    reason: str  # Human-readable explanation
    skipped_gates: List[str] = field(default_factory=list)  # Gates evaluated but not fired
    eval_time_ms: float = 0.0  # Time taken to evaluate all gates
    # For mutating state in the router function
    intent: Optional[str] = None
    strategy_topic: Optional[str] = None
    question_target: Optional[str] = None
    metadata_updates: Dict[str, Any] = field(default_factory=dict)
    # v5 Routing Observability fields
    lqa_reason: Optional[str] = None  # e.g., "lqa:hit", "deterministic:place_answer"
    llm_budget_used: int = 0  # Value of llm_calls_this_turn at gate evaluation time
    date_clarify_mode: bool = False  # Whether date clarification is active
