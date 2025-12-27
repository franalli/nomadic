"""Ready No Fields Gate - Precedence 40.

Handles the case when the plan is ready and no fields need to be collected.
Routes to summarize when all core fields are complete.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.planner.gates.base import Gate, GateContext
from app.planner.gates.precedence import GatePrecedence
from app.planner.gates.result import GateResult

if TYPE_CHECKING:
    pass


class ReadyNoFieldsGate(Gate):
    """Gate for ready state with no missing fields.

    Triggers when:
    - readiness.core_complete is True
    - No blocking errors exist
    - No pending date clarification

    Precedence: 40
    """

    precedence = GatePrecedence.READY_NO_FIELDS
    name = "READY_NO_FIELDS"

    def evaluate(self, ctx: GateContext) -> Optional[GateResult]:
        """Check if plan is ready with no missing fields."""
        readiness = ctx.readiness

        # Must have all core fields complete
        if not readiness.core_complete:
            self.record(ctx, fired=False, reason="core_fields_missing")
            return None

        # Check for blocking errors
        has_blocking_errors = bool(ctx.metadata.get("date_blocking_errors"))
        if has_blocking_errors:
            self.record(
                ctx,
                fired=False,
                reason="blocking_errors_present",
                suppressed=True,
                suppression_reason="date_blocking_errors",
            )
            return None

        # Check for date clarify mode
        if ctx.metadata.get("date_clarify_mode"):
            self.record(
                ctx,
                fired=False,
                reason="date_clarify_mode",
                suppressed=True,
                suppression_reason="date_clarify_mode_active",
            )
            return None

        self.record(ctx, fired=True, reason="plan_ready_to_generate")
        return self.build_result(
            ctx,
            destination="summarize",
            reason="ready_no_fields",
            metadata_updates={
                "router_path": "ready_no_fields",
                "router_bypassed": True,
            },
        )
