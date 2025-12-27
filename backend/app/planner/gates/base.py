"""Gate Base Classes - Foundation for Gate Extraction.

This module provides the base classes for the gate evaluation system.
Gates are extracted from GateEvaluator.evaluate() into separate classes
that implement a common interface.

Usage:
    from app.planner.gates.base import Gate, GateContext

    class ShortCircuitGate(Gate):
        precedence = GatePrecedence.SHORT_CIRCUIT

        def evaluate(self, ctx: GateContext) -> Optional[GateResult]:
            # Gate logic here
            if is_greeting(ctx.user_text_lower):
                return GateResult(...)
            return None  # Gate didn't fire
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

if TYPE_CHECKING:
    from app.plan_graph import GraphState, TripInputs
    from app.planner.gates.precedence import GatePrecedence
    from app.planner.gates.readiness import TripReadiness
    from app.planner.gates.result import GateResult


@dataclass
class GateContext:
    """Context object passed to gate evaluate() methods.

    Holds all commonly-used state values extracted once at the start of
    gate evaluation. This avoids repeated attribute access and ensures
    consistency across gate checks.

    Attributes:
        state: The full GraphState (for rare cases needing full access)
        user_text: Original user input text
        user_text_lower: Lowercased user text for pattern matching
        ti: TripInputs object with trip configuration
        flags: State flags dict
        metadata: State metadata dict
        extraction_conf: Extraction confidence dict from metadata
        readiness: Computed TripReadiness for field status
        start_time: perf_counter timestamp when evaluation started
        gate_trace: List to record gate evaluation history
    """

    state: "GraphState"
    user_text: str
    user_text_lower: str
    ti: "TripInputs"
    flags: Dict[str, Any]
    metadata: Dict[str, Any]
    extraction_conf: Dict[str, Any]
    readiness: "TripReadiness"
    start_time: float
    gate_trace: List[Dict[str, Any]] = field(default_factory=list)

    # Callbacks from evaluator (injected to avoid circular imports)
    record_gate: Optional[Callable[..., None]] = None

    @classmethod
    def from_state(
        cls,
        state: "GraphState",
        readiness: "TripReadiness",
        start_time: Optional[float] = None,
    ) -> "GateContext":
        """Create a GateContext from a GraphState.

        Args:
            state: The GraphState to extract values from
            readiness: Pre-computed TripReadiness
            start_time: Optional start time (defaults to now)

        Returns:
            Populated GateContext
        """
        user_text = state.user_text or ""
        return cls(
            state=state,
            user_text=user_text,
            user_text_lower=user_text.lower(),
            ti=state.trip_inputs,
            flags=state.flags,
            metadata=state.metadata,
            extraction_conf=state.metadata.get("extraction_confidence", {}),
            readiness=readiness,
            start_time=start_time if start_time is not None else time.perf_counter(),
        )

    def elapsed_ms(self) -> float:
        """Get elapsed time since evaluation started in milliseconds."""
        return (time.perf_counter() - self.start_time) * 1000


class Gate(ABC):
    """Abstract base class for routing gates.

    Each gate implements a single routing decision. Gates are evaluated
    in precedence order; the first gate to return a non-None GateResult
    wins and determines the routing.

    Subclasses must define:
        - precedence: GatePrecedence enum value for ordering
        - name: Human-readable gate name for debugging

    And implement:
        - evaluate(): Returns GateResult if gate fires, None otherwise
    """

    # Subclasses must set these
    precedence: "GatePrecedence"
    name: str

    @abstractmethod
    def evaluate(self, ctx: GateContext) -> Optional["GateResult"]:
        """Evaluate this gate against the current context.

        Args:
            ctx: GateContext with all relevant state

        Returns:
            GateResult if this gate fires (determines routing)
            None if this gate doesn't apply (continue to next gate)
        """
        pass

    def record(
        self,
        ctx: GateContext,
        fired: bool,
        reason: str,
        suppressed: bool = False,
        suppression_reason: Optional[str] = None,
    ) -> None:
        """Record this gate's evaluation in the trace.

        Args:
            ctx: The evaluation context
            fired: Whether the gate fired
            reason: Human-readable explanation
            suppressed: Whether the gate was suppressed
            suppression_reason: Why it was suppressed (if applicable)
        """
        ctx.gate_trace.append(
            {
                "gate": self.name,
                "fired": fired,
                "reason": reason,
                "suppressed": suppressed,
                "suppression_reason": suppression_reason,
                "elapsed_ms": ctx.elapsed_ms(),
            }
        )

    def build_result(
        self,
        ctx: GateContext,
        destination: str,
        reason: str,
        intent: Optional[str] = None,
        question_target: Optional[str] = None,
        strategy_topic: Optional[str] = None,
        metadata_updates: Optional[Dict[str, Any]] = None,
    ) -> "GateResult":
        """Build a GateResult with common fields populated.

        Factory method that reduces boilerplate in gate implementations.
        Always sets gate_fired, eval_time_ms, and skipped_gates.

        Args:
            ctx: The evaluation context
            destination: Node to route to
            reason: Human-readable explanation
            intent: Optional intent override
            question_target: Optional field to ask about (e.g., "destinations")
            strategy_topic: Optional strategy topic (e.g., "hiking")
            metadata_updates: Optional metadata to merge into state

        Returns:
            Populated GateResult ready to return from evaluate()
        """
        from app.planner.gates.result import GateResult

        return GateResult(
            gate_fired=self.precedence,
            destination=destination,
            reason=reason,
            eval_time_ms=ctx.elapsed_ms(),
            skipped_gates=[],
            intent=intent,
            question_target=question_target,
            strategy_topic=strategy_topic,
            metadata_updates=metadata_updates or {},
        )
