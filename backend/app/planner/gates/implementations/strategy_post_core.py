"""Strategy Post-Core Gate - Precedence 35.

Triggers Stage 1 of strategy flow when core fields become complete
after Stage 0 has run. This ensures the full strategy response is
generated before routing to summarize.

Gate fires when:
    - Core fields are complete (readiness.core_complete == True)
    - Stage 0 has run (last_strategy_topic is set in metadata)
    - Stage 1 hasn't completed yet (pending_strategy_expansion == False)
    - Lifecycle check passes (stage1_completed_sig differs from current)
    - No blocking errors or date clarify mode
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.debug_utils import _debug
from app.planner.gates.base import Gate, GateContext
from app.planner.gates.precedence import GatePrecedence
from app.planner.gates.result import GateResult
from app.planner.gates.suppression import SuppressionPredicates

if TYPE_CHECKING:
    pass


class StrategyPostCoreGate(Gate):
    """Gate for triggering Stage 1 after core becomes complete.

    This gate fills the gap between Stage 0 (pre-core value-first mode)
    and Stage 2 (expansion). After Stage 0 runs and the user provides
    the remaining core fields, this gate ensures Stage 1 fires to
    generate the full strategy outline before routing to summarize.

    Precedence: 35 (between SHORT_CIRCUIT at 30 and READY_NO_FIELDS at 40)
    """

    precedence = GatePrecedence.STRATEGY_POST_CORE
    name = "STRATEGY_POST_CORE"

    def evaluate(self, ctx: GateContext) -> Optional[GateResult]:
        """Check if Stage 1 should fire after core completion."""
        state = ctx.state
        metadata = ctx.metadata
        readiness = ctx.readiness
        ti = ctx.ti

        # Guard 1: Core must be complete
        if not readiness.core_complete:
            self.record(ctx, fired=False, reason="core_not_complete")
            return None

        # Guard 2: Stage 0 must have run (last_strategy_topic is set)
        last_topic = metadata.get("last_strategy_topic")
        if not last_topic:
            self.record(ctx, fired=False, reason="no_last_strategy_topic")
            return None

        # Guard 3: Stage 1 must not have completed yet
        # pending_strategy_expansion is set to True when Stage 1 completes
        if state.pending_strategy_expansion:
            self.record(ctx, fired=False, reason="stage1_already_completed")
            return None

        # Guard 4: Lifecycle suppression - check if Stage 1 already ran
        # for this topic+destinations+origin combination
        destinations = ti.destinations or []
        origin = ti.origin
        current_sig = SuppressionPredicates.compute_stage1_signature(
            last_topic, destinations, origin
        )
        completed_sig = metadata.get("stage1_completed_sig")
        if completed_sig == current_sig:
            self.record(
                ctx,
                fired=False,
                reason=f"lifecycle_suppression:{current_sig[:12]}",
            )
            return None

        # Guard 5: Check for blocking errors (dates must be valid)
        if readiness.has_blocking_errors:
            self.record(
                ctx,
                fired=False,
                reason="blocking_errors",
                suppressed=True,
                suppression_reason="date_blocking_errors",
            )
            return None

        # Guard 6: Not in date clarify mode
        if metadata.get("date_clarify_mode"):
            self.record(
                ctx,
                fired=False,
                reason="date_clarify_mode",
                suppressed=True,
                suppression_reason="date_clarify_mode_active",
            )
            return None

        # All guards passed - fire Stage 1
        _debug(
            "STRATEGY_POST_CORE gate triggered",
            topic=last_topic,
            destinations=destinations,
            current_sig=current_sig,
        )
        self.record(ctx, fired=True, reason=f"stage1_trigger:{last_topic}")

        return self.build_result(
            ctx,
            destination="strategy_node",
            reason=f"strategy_post_core:{last_topic}",
            intent="strategy",
            strategy_topic=last_topic,
            metadata_updates={
                "router_path": f"strategy_post_core:{last_topic}",
                "router_bypassed": True,
                "router_bypass_reason": f"stage1_trigger:{last_topic}",
                "strategy_stage": 1,
                "post_core_mode": True,
                "strategy_dest_known": bool(destinations),
            },
        )
