"""Core Collection Gate - Precedence 90.

Routes to required_fields when core fields are missing.
This is the primary path for collecting destination, origin, dates, etc.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.planner.gates.base import Gate, GateContext
from app.planner.gates.precedence import GatePrecedence
from app.planner.gates.result import GateResult

if TYPE_CHECKING:
    pass


class CoreCollectionGate(Gate):
    """Gate for core field collection.

    Triggers when:
    - Core fields are missing (destinations, origin, dates, travelers)
    - No higher-priority gate has fired

    Precedence: 90
    """

    precedence = GatePrecedence.CORE_COLLECTION
    name = "CORE_COLLECTION"

    def evaluate(self, ctx: GateContext) -> Optional[GateResult]:
        """Check if core fields need to be collected."""
        readiness = ctx.readiness

        # If core is complete, don't fire
        if readiness.core_complete:
            self.record(ctx, fired=False, reason="core_complete")
            return None

        # Get the first missing field to ask about
        missing_fields = readiness.missing_core
        if not missing_fields:
            self.record(ctx, fired=False, reason="no_missing_fields")
            return None

        # Determine question target (first missing field in priority order)
        question_target = missing_fields[0]

        self.record(ctx, fired=True, reason=f"missing_core:{question_target}")
        return self.build_result(
            ctx,
            destination="required_fields_node",
            reason=f"core_collection:{question_target}",
            question_target=question_target,
            metadata_updates={
                "router_path": f"core_collection:{question_target}",
                "router_bypassed": True,
                "missing_core_fields": missing_fields,
            },
        )
