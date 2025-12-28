"""Specialist Pre-Core Gate - Precedence 60.

Routes to domain specialists (flights, hotels, activities) when user
mentions them before core fields are complete.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.debug_utils import _debug
from app.pattern_matching import SPECIALIST_KEYWORDS
from app.planner.gates.base import Gate, GateContext
from app.planner.gates.constants import SPECIALIST_NODE_MAP
from app.planner.gates.keyword_utils import keyword_match
from app.planner.gates.precedence import GatePrecedence
from app.planner.gates.result import GateResult
from app.planner.gates.topic_detection import detect_strategy_topic_from_text

if TYPE_CHECKING:
    pass


class SpecialistPreCoreGate(Gate):
    """Gate for specialist routing before core fields are complete.

    Triggers when:
    - User mentions specialist domains (flights, hotels, etc.)
    - Core fields may not be complete
    - Strategy topic not detected (yields to strategy gate if topic present)

    Precedence: 60
    """

    precedence = GatePrecedence.SPECIALIST_PRE_CORE
    name = "SPECIALIST_PRE_CORE"

    def evaluate(self, ctx: GateContext) -> Optional[GateResult]:
        """Check if user is asking about a specialist domain."""
        result = self._check_specialist_keywords(ctx)
        if result is None:
            self.record(ctx, fired=False, reason="no_specialist_keyword")
            return None

        intent_name, destination = result
        self.record(ctx, fired=True, reason=f"specialist:{intent_name}")

        return self.build_result(
            ctx,
            destination=destination,
            reason=f"specialist_pre_core:{intent_name}",
            intent=intent_name,
            metadata_updates={
                "router_path": f"specialist_pre_core:{intent_name}",
                "router_bypassed": True,
                "router_bypass_reason": f"specialist_pre_core:{intent_name}",
                "pre_core_mode": True,
                "missing_core_fields": ctx.readiness.missing_core,
            },
        )

    def _check_specialist_keywords(self, ctx: GateContext) -> Optional[tuple[str, str]]:
        """Check for specialist keywords in user text."""
        text_lower = ctx.user_text_lower
        readiness = ctx.readiness

        for intent_name, keywords in SPECIALIST_KEYWORDS.items():
            if keyword_match(text_lower, keywords):
                # Yield to strategy gate for "activities" when strategy topic detected
                if intent_name == "activities":
                    strategy_topic = detect_strategy_topic_from_text(text_lower)
                    if strategy_topic:
                        _debug(
                            "specialist_pre_core yielding to strategy_pre_core",
                            intent=intent_name,
                            strategy_topic=strategy_topic,
                        )
                        return None

                _debug(
                    "specialist_pre_core triggered",
                    intent=intent_name,
                    missing_core=readiness.missing_core,
                )
                return (intent_name, SPECIALIST_NODE_MAP[intent_name])

        return None
