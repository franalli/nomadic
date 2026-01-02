"""Strategy Topic Switch Gate - Precedence 70.

Handles mid-session strategy topic switches when user requests
a different topic (e.g., adding diving to a hiking trip).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

from app.debug_utils import _debug
from app.pattern_matching import (
    TOPIC_SWITCH_INTENT_VERBS,
    TOPIC_SWITCH_OVERRIDE_PHRASES,
)
from app.planner.gates.base import Gate, GateContext
from app.planner.gates.precedence import GatePrecedence
from app.planner.gates.result import GateResult
from app.planner.gates.suppression import SuppressionPredicates

if TYPE_CHECKING:
    from app.plan_graph import TripInputs
    from app.planner.gates.readiness import TripReadiness

# Strategy topic to node mapping
STRATEGY_TOPIC_TO_NODE: Dict[str, str] = {
    "hiking": "strategy_node",
    "diving": "strategy_node",
    "skiing": "strategy_node",
    "cycling": "strategy_node",
    "boating": "strategy_node",
}


class StrategyTopicSwitchGate(Gate):
    """Gate for mid-session strategy topic switches.

    Triggers when:
    1. Auto-fire pending topic (deferred from previous turn)
    2. Strategy keyword detected in user text
    3. User expresses intent via verb patterns ("wanna", "go", "plan", "try")
    4. Topic differs from last_strategy_topic OR explicitly re-requested
    5. Cooldown has passed OR override phrase used ("actually", "instead")

    Behavior:
    - If blocking_errors exist: store pending_strategy_topic, route to date clarify
    - If core complete + no blocking errors: route to strategy stage 1
    - If destinations missing: route to strategy stage 0

    Precedence: 70
    """

    precedence = GatePrecedence.STRATEGY_TOPIC_SWITCH
    name = "STRATEGY_TOPIC_SWITCH"

    def evaluate(self, ctx: GateContext) -> Optional[GateResult]:
        """Check if strategy topic switch should fire."""
        topic_switch_result = self._check_strategy_topic_switch(
            ctx.user_text_lower,
            ctx.ti,
            ctx.readiness,
            ctx.metadata,
            ctx.state.turn_number,
            ctx.detected_strategy_topic,  # Pass pre-computed topic
        )

        if not topic_switch_result:
            self.record(ctx, fired=False, reason="no_topic_switch")
            return None

        new_topic, switch_reason = topic_switch_result

        # Check for blocking errors - must handle dates first
        if ctx.readiness.has_blocking_errors:
            _debug(
                "STRATEGY_TOPIC_SWITCH: deferred due to blocking errors",
                new_topic=new_topic,
                blocking_errors=ctx.readiness.blocking_errors,
            )
            self.record(ctx, fired=True, reason=f"topic_switch_deferred:{new_topic}")
            return self.build_result(
                ctx,
                destination="required_fields_node",
                reason=f"topic_switch_deferred:{new_topic}:blocking_errors",
                intent="required_fields",
                question_target="dates",
                strategy_topic=new_topic,
                metadata_updates={
                    "router_path": f"topic_switch_deferred:{new_topic}",
                    "router_bypassed": True,
                    "pending_strategy_topic": new_topic,
                    "date_clarify_mode": True,
                    "topic_switch_reason": switch_reason,
                },
            )

        # Determine stage based on readiness
        has_destinations = bool(ctx.ti.destinations)
        if ctx.readiness.core_complete:
            strategy_stage = 1
        elif not ctx.ti.destinations:
            strategy_stage = 0
        else:
            strategy_stage = 1

        destination = STRATEGY_TOPIC_TO_NODE.get(new_topic, "strategy_node")
        self.record(ctx, fired=True, reason=f"topic_switch:{new_topic}")

        return self.build_result(
            ctx,
            destination=destination,
            reason=f"topic_switch:{new_topic}:{switch_reason}",
            intent="strategy",
            strategy_topic=new_topic,
            metadata_updates={
                "router_path": f"strategy_topic_switch:{new_topic}",
                "router_bypassed": True,
                "router_bypass_reason": f"topic_switch:{new_topic}",
                "strategy_stage": strategy_stage,
                "strategy_dest_known": has_destinations,
                "last_strategy_topic": new_topic,
                "last_strategy_topic_turn": ctx.state.turn_number,
                "topic_switch_cooldown_until_turn": ctx.state.turn_number + 1,
                "topic_switch_reason": switch_reason,
            },
        )

    def _check_strategy_topic_switch(
        self,
        text_lower: str,
        ti: "TripInputs",
        readiness: "TripReadiness",
        metadata: Dict[str, Any],
        turn_number: int,
        precomputed_topic: Optional[str] = None,
    ) -> Optional[tuple[str, str]]:
        """
        Check if user is requesting a mid-session strategy topic switch.

        Args:
            text_lower: Lowercased user text
            ti: TripInputs
            readiness: TripReadiness
            metadata: State metadata
            turn_number: Current turn number
            precomputed_topic: Pre-computed strategy topic from GateContext

        Returns:
            (new_topic, switch_reason) if topic switch should fire, None otherwise
        """
        # Check for auto-fire pending topic (from previous turn's deferred switch)
        auto_fire_topic = metadata.get("auto_fire_topic_switch")
        if auto_fire_topic:
            _debug(
                "STRATEGY_TOPIC_SWITCH: auto-firing pending topic",
                topic=auto_fire_topic,
            )
            return (auto_fire_topic, "auto_fire_pending")

        # BRIDGE SUPPRESSION: Don't fire when user just answered active question
        if SuppressionPredicates.bridge_suppression(metadata):
            return None

        # TURN 1 GUARD: Topic switch is for mid-session changes, not first turn
        last_strategy_topic = metadata.get("last_strategy_topic")
        if turn_number < 2 and not last_strategy_topic:
            _debug(
                "STRATEGY_TOPIC_SWITCH: skipped on turn 1 (use STRATEGY_PRE_CORE_VALUE)",
                turn_number=turn_number,
            )
            return None

        # Use pre-computed strategy topic from GateContext (avoids redundant detection)
        detected_topic = precomputed_topic
        if not detected_topic:
            return None

        # Check for intent verb patterns - user must be expressing desire
        has_intent_verb = any(verb in text_lower for verb in TOPIC_SWITCH_INTENT_VERBS)
        if not has_intent_verb:
            _debug(
                "STRATEGY_TOPIC_SWITCH: no intent verb detected",
                topic=detected_topic,
                text_preview=text_lower[:50],
            )
            return None

        # Get last strategy topic state
        last_topic = metadata.get("last_strategy_topic")
        cooldown_until = metadata.get("topic_switch_cooldown_until_turn", 0)

        # Check if this is the same topic as before (not a switch)
        if detected_topic == last_topic:
            # Check for explicit re-request patterns
            has_override = any(phrase in text_lower for phrase in TOPIC_SWITCH_OVERRIDE_PHRASES)
            if not has_override:
                _debug(
                    "STRATEGY_TOPIC_SWITCH: same topic, no override phrase",
                    topic=detected_topic,
                    last_topic=last_topic,
                )
                return None
            # User explicitly wants to revisit the same topic
            return (detected_topic, "explicit_revisit")

        # Different topic - check cooldown
        if turn_number <= cooldown_until:
            # Check for override phrases that bypass cooldown
            has_override = any(phrase in text_lower for phrase in TOPIC_SWITCH_OVERRIDE_PHRASES)
            if not has_override:
                _debug(
                    "STRATEGY_TOPIC_SWITCH: cooldown active, no override",
                    topic=detected_topic,
                    cooldown_until=cooldown_until,
                    turn_number=turn_number,
                )
                return None
            # Override phrase detected - allow switch
            return (detected_topic, "override_cooldown")

        # New topic, cooldown expired - allow switch
        return (detected_topic, "new_topic")
