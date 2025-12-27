"""Strategy Expansion Gate - Precedence 10.

Handles user requests to expand on existing strategy content.
Highest priority gate - fires when user says "show more details", "expand", etc.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.planner.gates.base import Gate, GateContext
from app.planner.gates.checks import is_strategy_expansion_request
from app.planner.gates.precedence import GatePrecedence
from app.planner.gates.result import GateResult

if TYPE_CHECKING:
    pass


class StrategyExpansionGate(Gate):
    """Gate for strategy expansion requests.

    Triggers when:
    1. pending_strategy_expansion is True (stage 1 was completed)
    2. User text matches expansion triggers ("show more details", "expand", etc.)

    Precedence: 10 (highest priority)
    """

    precedence = GatePrecedence.STRATEGY_EXPANSION
    name = "STRATEGY_EXPANSION"

    def evaluate(self, ctx: GateContext) -> Optional[GateResult]:
        """Check if user is requesting strategy expansion."""
        state = ctx.state

        if not state.pending_strategy_expansion:
            self.record(ctx, fired=False, reason="no_pending_expansion")
            return None

        expansion_result = is_strategy_expansion_request(ctx.user_text)
        if not expansion_result.is_expansion:
            self.record(ctx, fired=False, reason="no_expansion_request")
            return None

        # Get the last strategy topic for routing
        last_topic = ctx.metadata.get("last_strategy_topic", "hiking")
        self.record(ctx, fired=True, reason=f"expansion_request:{last_topic}")

        return self.build_result(
            ctx,
            destination="strategy_node",
            reason=f"strategy_expansion:{last_topic}:{expansion_result.matched_phrase}",
            intent="strategy",
            strategy_topic=last_topic,
            metadata_updates={
                "router_path": f"strategy_expansion:{last_topic}",
                "router_bypassed": True,
                "strategy_stage": 2,
                "expansion_target": (
                    expansion_result.target.value if expansion_result.target else None
                ),
                "expansion_tier": (expansion_result.tier.value if expansion_result.tier else None),
                "user_request_type": "expand",
            },
        )
