"""Fast Path Gate - Precedence 50.

Handles direct field updates during bootstrap mode.
Only fires when strategy_bootstrap_active is True.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.debug_utils import _debug
from app.planner.gates.base import Gate, GateContext
from app.planner.gates.precedence import GatePrecedence
from app.planner.gates.result import GateResult

if TYPE_CHECKING:
    pass


class FastPathGate(Gate):
    """Gate for fast path bootstrap optimization.

    Triggers when:
    - flags.fast_path is set
    - For strategy_bootstrap: only when strategy_bootstrap_active is True

    Precedence: 50
    """

    precedence = GatePrecedence.FAST_PATH
    name = "FAST_PATH"

    def evaluate(self, ctx: GateContext) -> Optional[GateResult]:
        """Check if fast path should be used."""
        if not ctx.flags.get("fast_path"):
            self.record(ctx, fired=False, reason="no_fast_path_flag")
            return None

        fp_field = ctx.flags.get("fast_path_field", "unknown")

        # Strategy bootstrap fast path only fires when bootstrap is active (turn 1)
        if fp_field == "strategy_bootstrap":
            if not ctx.flags.get("strategy_bootstrap_active", False):
                _debug(
                    "FAST_PATH skipped: strategy_bootstrap expired",
                    fp_field=fp_field,
                    strategy_bootstrap_active=False,
                )
                self.record(
                    ctx,
                    fired=False,
                    reason="strategy_bootstrap_expired",
                    suppressed=True,
                    suppression_reason="strategy_bootstrap_inactive",
                )
                return None

        self.record(ctx, fired=True, reason=f"fast_path:{fp_field}")
        return self.build_result(
            ctx,
            destination="required_fields_node",
            reason=f"fast_path:{fp_field}",
            intent="required_fields",
            metadata_updates={
                "router_path": f"fast_path:{fp_field}",
            },
        )
