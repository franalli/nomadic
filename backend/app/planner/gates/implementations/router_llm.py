"""Router LLM Gate - Precedence 999.

Default fallback gate that routes to the LLM router.
This fires when no other gate has matched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.planner.gates.base import Gate, GateContext
from app.planner.gates.precedence import GatePrecedence
from app.planner.gates.result import GateResult

if TYPE_CHECKING:
    pass


class RouterLLMGate(Gate):
    """Default gate that routes to LLM router.

    Always fires as the final fallback when no other gate matches.

    Precedence: 999 (lowest priority)
    """

    precedence = GatePrecedence.ROUTER_LLM
    name = "ROUTER_LLM"

    def evaluate(self, ctx: GateContext) -> Optional[GateResult]:
        """Route to LLM router as fallback."""
        self.record(ctx, fired=True, reason="default_fallback")
        return self.build_result(
            ctx,
            destination="router",
            reason="router_llm_fallback",
            metadata_updates={
                "router_path": "router_llm",
            },
        )
