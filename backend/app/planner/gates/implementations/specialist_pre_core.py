"""Specialist Pre-Core Gate - Precedence 60.

Routes to domain specialists (flights, hotels, activities) when user
mentions them before core fields are complete.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, FrozenSet, Optional

from app.debug_utils import _debug
from app.planner.gates.base import Gate, GateContext
from app.planner.gates.precedence import GatePrecedence
from app.planner.gates.result import GateResult
from app.planner.gates.topic_detection import detect_strategy_topic_from_text

if TYPE_CHECKING:
    pass


# Specialist keywords that trigger pre-core routing
SPECIALIST_PRE_CORE_KEYWORDS: Dict[str, FrozenSet[str]] = {
    "flights": frozenset({"flight", "flights", "fly", "flying", "airline", "airfare"}),
    "hotels": frozenset({"hotel", "hotels", "stay", "accommodation", "lodging", "hostel"}),
    "transport": frozenset({"car rental", "rent a car", "taxi", "uber", "train", "bus"}),
    "activities": frozenset({"activities", "things to do", "attractions", "tours", "excursions"}),
}


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
                "pre_core_mode": True,
            },
        )

    def _check_specialist_keywords(self, ctx: GateContext) -> Optional[tuple[str, str]]:
        """Check for specialist keywords in user text."""
        text_lower = ctx.user_text_lower
        readiness = ctx.readiness

        for intent_name, keywords in SPECIALIST_PRE_CORE_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
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

                destination_map = {
                    "flights": "flights_node",
                    "hotels": "hotels_node",
                    "transport": "transport_node",
                    "activities": "activities_node",
                }
                _debug(
                    "specialist_pre_core triggered",
                    intent=intent_name,
                    missing_core=readiness.missing_core,
                )
                return (intent_name, destination_map[intent_name])

        return None
