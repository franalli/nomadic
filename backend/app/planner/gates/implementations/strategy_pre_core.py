"""Strategy Pre-Core Value Gate - Precedence 80.

Routes to strategy_node for value-first responses when:
- Strategy topic detected (hiking, skiing, diving, etc.)
- Core fields not complete
- Provides helpful content before asking for missing info

Note: Previously split into two gates (80 and 85) based on destinations presence.
Now consolidated into a single gate that handles both cases.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.debug_utils import _debug
from app.pattern_matching import QUESTIONS_ONLY_PHRASES
from app.planner.gates.base import Gate, GateContext
from app.planner.gates.precedence import GatePrecedence
from app.planner.gates.result import GateResult
from app.planner.gates.topic_detection import detect_strategy_topic

if TYPE_CHECKING:
    pass


class StrategyPreCoreValueGate(Gate):
    """Gate for strategy value-first response.

    Triggers when:
    - Strategy topic detected (hiking, skiing, etc.)
    - Core fields missing
    - Not a "questions only" request

    Handles both cases:
    - Without destinations: asks for dates/origin
    - With destinations: asks for remaining fields (typically dates)

    Precedence: 80
    """

    precedence = GatePrecedence.STRATEGY_PRE_CORE_VALUE
    name = "STRATEGY_PRE_CORE_VALUE"

    def evaluate(self, ctx: GateContext) -> Optional[GateResult]:
        """Check if strategy pre-core value should fire."""
        # Must have missing core fields
        if ctx.readiness.core_complete:
            self.record(ctx, fired=False, reason="core_complete")
            return None

        has_destinations = bool(ctx.ti.destinations)

        # Check for date clarify mode (only relevant when destinations exist)
        if has_destinations and ctx.metadata.get("date_clarify_mode"):
            _debug("strategy_pre_core_value skipped: date_clarify_mode")
            self.record(
                ctx,
                fired=False,
                reason="date_clarify_mode",
                suppressed=True,
                suppression_reason="date_clarify_mode_active",
            )
            return None

        # Check for "questions only" phrases
        for phrase in QUESTIONS_ONLY_PHRASES:
            if phrase in ctx.user_text_lower:
                _debug(
                    "strategy_pre_core_value bypassed: questions_only phrase",
                    phrase=phrase,
                )
                self.record(ctx, fired=False, reason=f"questions_only:{phrase}")
                return None

        # Detect strategy topic
        detected_topic = detect_strategy_topic(ctx.user_text_lower, ctx.ti.activity_settings)
        if not detected_topic:
            self.record(ctx, fired=False, reason="no_strategy_topic")
            return None

        # Determine question target (dates preferred for strategy)
        missing_core = ctx.readiness.missing_core
        if "dates" in missing_core or "start_date" in missing_core:
            question_target = "dates"
        elif "origin" in missing_core:
            question_target = "origin"
        else:
            question_target = missing_core[0] if missing_core else "dates"

        # Build result - include destination context in reason if applicable
        reason_suffix = "_with_dest" if has_destinations else ""
        record_reason = (
            f"strategy_with_dest:{detected_topic}"
            if has_destinations
            else f"strategy_pre_core:{detected_topic}"
        )

        _debug(
            "strategy_pre_core_value triggered",
            topic=detected_topic,
            has_destinations=has_destinations,
            destinations=ctx.ti.destinations,
            missing_core=missing_core,
            question_target=question_target,
        )

        self.record(ctx, fired=True, reason=record_reason)

        return self.build_result(
            ctx,
            destination="strategy_node",
            reason=f"strategy_pre_core_value{reason_suffix}:{detected_topic}",
            intent="strategy",
            question_target=question_target,
            strategy_topic=detected_topic,
            metadata_updates={
                "router_path": f"strategy_pre_core_value{reason_suffix}:{detected_topic}",
                "router_bypassed": True,
                "router_bypass_reason": f"strategy{reason_suffix}:{detected_topic}",
                "strategy_stage": 0,
                "pre_core_mode": True,
                "strategy_dest_known": has_destinations,
            },
        )
