"""Strategy Pre-Core Value Gates - Precedence 80 and 85.

Routes to strategy_node for value-first responses when:
- Strategy topic detected (hiking, skiing, diving, etc.)
- Core fields not complete
- Provides helpful content before asking for missing info
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
    """Gate for strategy value-first response (no destinations).

    Triggers when:
    - Strategy topic detected (hiking, skiing, etc.)
    - Core fields missing
    - NO destinations extracted
    - Not a "questions only" request

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

        # Must NOT have destinations (handled by STRATEGY_PRE_CORE_VALUE_WITH_DEST)
        if ctx.ti.destinations:
            self.record(ctx, fired=False, reason="has_destinations")
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

        self.record(ctx, fired=True, reason=f"strategy_pre_core:{detected_topic}")

        return self.build_result(
            ctx,
            destination="strategy_node",
            reason=f"strategy_pre_core_value:{detected_topic}",
            intent="strategy",
            question_target=question_target,
            strategy_topic=detected_topic,
            metadata_updates={
                "router_path": f"strategy_pre_core_value:{detected_topic}",
                "router_bypassed": True,
                "router_bypass_reason": f"strategy:{detected_topic}",
                "strategy_stage": 0,
                "pre_core_mode": True,
            },
        )


class StrategyPreCoreValueWithDestGate(Gate):
    """Gate for strategy value-first response (with destinations).

    Triggers when:
    - Strategy topic detected (hiking, skiing, etc.)
    - Core fields missing BUT destinations known
    - Not a "questions only" request

    Precedence: 85
    """

    precedence = GatePrecedence.STRATEGY_PRE_CORE_VALUE_WITH_DEST
    name = "STRATEGY_PRE_CORE_VALUE_WITH_DEST"

    def evaluate(self, ctx: GateContext) -> Optional[GateResult]:
        """Check if strategy pre-core with destinations should fire."""
        # Must have missing core fields
        if ctx.readiness.core_complete:
            self.record(ctx, fired=False, reason="core_complete")
            return None

        # MUST have destinations
        if not ctx.ti.destinations:
            self.record(ctx, fired=False, reason="no_destinations")
            return None

        # Check for date clarify mode
        if ctx.metadata.get("date_clarify_mode"):
            _debug("strategy_pre_core_value_with_dest skipped: date_clarify_mode")
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
                self.record(ctx, fired=False, reason=f"questions_only:{phrase}")
                return None

        # Detect strategy topic
        detected_topic = detect_strategy_topic(ctx.user_text_lower, ctx.ti.activity_settings)
        if not detected_topic:
            self.record(ctx, fired=False, reason="no_strategy_topic")
            return None

        _debug(
            "strategy_pre_core_value_with_dest triggered",
            topic=detected_topic,
            destinations=ctx.ti.destinations,
            missing_core=ctx.readiness.missing_core,
        )

        self.record(ctx, fired=True, reason=f"strategy_with_dest:{detected_topic}")

        return self.build_result(
            ctx,
            destination="strategy_node",
            reason=f"strategy_pre_core_value_with_dest:{detected_topic}",
            intent="strategy",
            strategy_topic=detected_topic,
            metadata_updates={
                "router_path": f"strategy_pre_core_value_with_dest:{detected_topic}",
                "router_bypassed": True,
                "router_bypass_reason": f"strategy_with_dest:{detected_topic}",
                "strategy_stage": 0,
                "pre_core_mode": True,
            },
        )
