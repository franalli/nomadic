"""Short Circuit Gate - Precedence 30.

Handles inputs that can bypass LLM processing entirely:
- Greetings
- Acknowledgments
- Off-topic responses
- Infeasibility detection
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.planner.gates.base import Gate, GateContext
from app.planner.gates.precedence import GatePrecedence
from app.planner.gates.result import GateResult  # Still needed for type hints

if TYPE_CHECKING:
    pass


class ShortCircuitGate(Gate):
    """Gate for short-circuit responses.

    Triggers when:
    - flags.short_circuit is set (greeting, acknowledgment, off-topic)
    - Infeasibility signals detected in user text

    Precedence: 30
    """

    precedence = GatePrecedence.SHORT_CIRCUIT
    name = "SHORT_CIRCUIT"

    def evaluate(self, ctx: GateContext) -> Optional[GateResult]:
        """Check if input should be short-circuited."""
        # Check for short_circuit flag
        sc_type = ctx.flags.get("short_circuit")
        if sc_type:
            reason = f"short_circuit:{sc_type}"
            self.record(ctx, fired=True, reason=reason)
            return self.build_result(
                ctx,
                destination="short_circuit_responder",
                reason=reason,
                metadata_updates={"router_path": reason},
            )

        return None


class InfeasibilityGate(Gate):
    """Gate for infeasibility detection.

    Triggers when user text contains infeasibility signals
    (conflicts, impossibilities, logical errors).

    Uses same precedence as SHORT_CIRCUIT.
    """

    precedence = GatePrecedence.SHORT_CIRCUIT
    name = "INFEASIBILITY_DETECTION"

    def evaluate(self, ctx: GateContext) -> Optional[GateResult]:
        """Check for infeasibility signals."""
        # Late import to avoid circular dependency
        from app.plan_graph import _has_infeasibility_signals

        has_infeasibility, infeasibility_type = _has_infeasibility_signals(ctx.user_text, ctx.state)

        if has_infeasibility:
            reason = f"infeasibility:{infeasibility_type}"
            self.record(ctx, fired=True, reason=reason)
            return self.build_result(
                ctx,
                destination="correction_node",
                reason=reason,
                intent="correction_needed",
                metadata_updates={
                    "router_path": f"infeasibility_detection:{infeasibility_type}",
                    "router_bypassed": True,
                    "router_bypass_reason": reason,
                },
            )

        self.record(ctx, fired=False, reason="no_infeasibility")
        return None
