"""Strategy Pre-Core Value Gate - Precedence 80.

Routes to strategy_node for duration-aware strategy responses when:
- Strategy topic detected (hiking, skiing, diving, etc.)
- ALL core fields are complete (origin, destination, dates, travelers)

Constraint-first: Strategy only fires when ALL core fields are present.
This prevents premature itinerary generation before we have enough info.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.debug_utils import _debug
from app.pattern_matching import QUESTIONS_ONLY_PHRASES
from app.planner.gates.base import Gate, GateContext
from app.planner.gates.precedence import GatePrecedence
from app.planner.gates.result import GateResult

if TYPE_CHECKING:
    pass


class StrategyPreCoreValueGate(Gate):
    """Gate for duration-aware strategy response.

    Triggers when:
    - Strategy topic detected (hiking, skiing, etc.)
    - User explicitly requests itinerary, OR all core fields complete
      (origin, destinations, dates, AND travelers)
    - Not a "questions only" request

    Strategy only fires with explicit user request OR complete information.
    This prevents premature itinerary generation while core fields are missing.

    Precedence: 80
    """

    precedence = GatePrecedence.STRATEGY_PRE_CORE_VALUE
    name = "STRATEGY_PRE_CORE_VALUE"

    def evaluate(self, ctx: GateContext) -> Optional[GateResult]:
        """Check if strategy pre-core value should fire."""
        # Pre-check strategy topic to store in metadata even if gate doesn't fire
        # This enables context-aware messaging in required_fields (Tier 6 UX)
        detected_topic = ctx.detected_strategy_topic
        if detected_topic:
            ctx.metadata["pending_strategy_topic"] = detected_topic
            ctx.metadata["strategy_topic_detected_at"] = "strategy_pre_core"

        # Check for "questions only" phrases first
        for phrase in QUESTIONS_ONLY_PHRASES:
            if phrase in ctx.user_text_lower:
                _debug(
                    "strategy_pre_core_value bypassed: questions_only phrase",
                    phrase=phrase,
                )
                self.record(ctx, fired=False, reason=f"questions_only:{phrase}")
                return None

        # Use pre-computed strategy topic from GateContext (avoids redundant detection)
        if not detected_topic:
            self.record(ctx, fired=False, reason="no_strategy_topic")
            return None

        # Check if all required fields are complete (origin, destination, dates, travelers)
        # Constraint-first: Strategy ONLY fires when ALL core fields are present
        has_destinations = bool(ctx.ti.destinations)
        has_origin = bool(ctx.ti.origin)
        has_dates = bool(ctx.ti.start_date)
        has_travelers = ctx.ti.adults is not None and ctx.ti.adults > 0
        all_core_complete = has_destinations and has_origin and has_dates and has_travelers

        # Strategy requires ALL core fields - no bypass for explicit requests
        if not all_core_complete:
            missing = []
            if not has_destinations:
                missing.append("destinations")
            if not has_origin:
                missing.append("origin")
            if not has_dates:
                missing.append("dates")
            if not has_travelers:
                missing.append("travelers")
            self.record(
                ctx,
                fired=False,
                reason=f"missing_fields:{','.join(missing)}",
            )
            return None

        # Check for date clarify mode
        if ctx.metadata.get("date_clarify_mode"):
            _debug("strategy_pre_core_value skipped: date_clarify_mode")
            self.record(
                ctx,
                fired=False,
                reason="date_clarify_mode",
                suppressed=True,
                suppression_reason="date_clarify_mode_active",
            )
            return None

        # Determine question target for any remaining fields
        missing_core = ctx.readiness.missing_core
        if "dates" in missing_core or "start_date" in missing_core:
            question_target = "dates"
        elif "origin" in missing_core:
            question_target = "origin"
        elif missing_core:
            question_target = missing_core[0]
        else:
            question_target = None  # All fields complete

        # Build result
        record_reason = f"strategy:{detected_topic}:all_fields_complete"

        _debug(
            "strategy_pre_core_value triggered",
            topic=detected_topic,
            has_destinations=has_destinations,
            has_origin=has_origin,
            has_dates=has_dates,
            has_travelers=has_travelers,
        )

        self.record(ctx, fired=True, reason=record_reason)

        return self.build_result(
            ctx,
            destination="strategy_node",
            reason=f"strategy_pre_core_value:{detected_topic}:all_fields_complete",
            intent="strategy",
            question_target=question_target,
            strategy_topic=detected_topic,
            metadata_updates={
                "router_path": f"strategy_pre_core_value:{detected_topic}:all_fields_complete",
                "router_bypassed": True,
                "router_bypass_reason": f"strategy:{detected_topic}:all_fields_complete",
                "strategy_stage": 0,
                "strategy_dest_known": has_destinations,
            },
        )
