"""Generate Requested Gate - Precedence 20.

Handles explicit plan generation requests (e.g., "GENERATE_PLAN_NOW").
Blocks if there are blocking date errors that need resolution first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.planner.gates.base import Gate, GateContext
from app.planner.gates.constants import DATE_BLOCKING_ERROR_CODES
from app.planner.gates.precedence import GatePrecedence
from app.planner.gates.result import GateResult

if TYPE_CHECKING:
    pass


class GenerateRequestedGate(Gate):
    """Gate for explicit generate requests.

    Triggers when:
    - flags.generate_requested is True

    Blocks if:
    - There are blocking date errors (DATE_AMBIGUOUS_YEAR, DATE_RANGE_INVALID)
    - date_clarify_mode is active

    Precedence: 20
    """

    precedence = GatePrecedence.GENERATE_REQUESTED
    name = "GENERATE_REQUESTED"

    def evaluate(self, ctx: GateContext) -> Optional[GateResult]:
        """Check if user requested plan generation."""
        # Late import to avoid circular dependency

        if not ctx.flags.get("generate_requested"):
            self.record(ctx, fired=False, reason="no_generate_flag")
            return None

        # Check for blocking date errors
        has_blocking_date_errors = self._has_blocking_date_errors(ctx)

        if has_blocking_date_errors:
            # Block generation and redirect to dates clarification
            self.record(
                ctx,
                fired=True,
                reason="blocked_by_date_errors",
                suppressed=True,
                suppression_reason="date_clarify_mode",
            )
            return GateResult(
                gate_fired=GatePrecedence.CORE_COLLECTION,
                destination="required_fields_node",
                reason="generate_blocked:date_errors",
                eval_time_ms=ctx.elapsed_ms(),
                skipped_gates=[],
                metadata_updates={
                    "router_path": "generate_blocked:date_errors",
                    "router_bypassed": True,
                    "date_clarify_mode": True,
                },
            )

        self.record(ctx, fired=True, reason="generate_requested")
        return self.build_result(
            ctx,
            destination="generate_responder",
            reason="generate_requested",
            metadata_updates={
                "router_path": "generate_requested",
                "router_bypassed": True,
            },
        )

    def _has_blocking_date_errors(self, ctx: GateContext) -> bool:
        """Check if there are blocking date errors."""
        from app.plan_graph import NormalizationError
        from app.schemas import ErrorRecord

        state = ctx.state

        if state.errors:
            for err in state.errors:
                if isinstance(err, ErrorRecord):
                    if err.severity == "blocking" or err.code in DATE_BLOCKING_ERROR_CODES:
                        return True
                elif isinstance(err, NormalizationError) and err.code in DATE_BLOCKING_ERROR_CODES:
                    return True
                elif isinstance(err, str) and any(
                    code in err for code in DATE_BLOCKING_ERROR_CODES
                ):
                    return True

        # Also check metadata for date_clarify_mode
        if ctx.metadata.get("date_clarify_mode"):
            return True

        return False
