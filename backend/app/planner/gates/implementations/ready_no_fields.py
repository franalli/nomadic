"""Ready No Fields Gate - Precedence 40.

Handles the case when the plan is ready and no fields need to be collected.
Routes to summarize when all core fields are complete, or to specialist nodes
if explicit specialist keywords are detected.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.pattern_matching import SPECIALIST_KEYWORDS
from app.planner.gates.base import Gate, GateContext
from app.planner.gates.constants import SPECIALIST_NODE_MAP
from app.planner.gates.keyword_utils import keyword_match
from app.planner.gates.precedence import GatePrecedence
from app.planner.gates.result import GateResult
from app.planner.gates.topic_detection import detect_strategy_topic_from_text

# Additional keywords that trigger strategy when core is complete
# "adventure" maps to hiking as the most common adventure activity
ADVENTURE_KEYWORDS = frozenset({"adventure", "activities", "things to do", "what can i do"})

if TYPE_CHECKING:
    pass


class ReadyNoFieldsGate(Gate):
    """Gate for ready state with no missing fields.

    Triggers when:
    - readiness.core_complete is True
    - No blocking errors exist
    - No pending date clarification

    Routes to specialist nodes if explicit specialist keywords detected,
    otherwise routes to summarize.

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

        user_text_lower = ctx.user_text_lower

        # Check if user text contains an explicit strategy keyword (hiking, diving, etc.)
        # This is checked FIRST because strategy keywords in user text take precedence
        strategy_keyword_in_text = detect_strategy_topic_from_text(user_text_lower)

        # SPECIALIST_REQUEST: Check for explicit specialist keywords when ready
        # BUT only if no explicit strategy keyword is present in the current user text.
        # This ensures "hiking and outdoor activities" routes to strategy, while
        # "Add flights" (no strategy keyword) routes to flights specialist.
        if not strategy_keyword_in_text:
            for specialist, keywords in SPECIALIST_KEYWORDS.items():
                if keyword_match(user_text_lower, keywords):
                    destination = SPECIALIST_NODE_MAP.get(specialist, "hotels_node")
                    self.record(ctx, fired=True, reason=f"specialist_request:{specialist}")
                    return self.build_result(
                        ctx,
                        destination=destination,
                        reason=f"specialist_request:{specialist}",
                        intent=specialist,
                        metadata_updates={
                            "router_path": f"specialist_request:{specialist}",
                            "router_bypassed": True,
                            "explicit_specialist_request": specialist,
                        },
                    )

        # STRATEGY_REQUEST: Use pre-computed strategy topic from GateContext
        # This fires when user text has a strategy keyword, OR when activity_settings
        # has a strategy topic (from previous turns)
        strategy_topic = ctx.detected_strategy_topic

        # Also check for generic "adventure" keywords that map to hiking
        if not strategy_topic:
            if any(kw in user_text_lower for kw in ADVENTURE_KEYWORDS):
                strategy_topic = "hiking"  # Default adventure topic

        if strategy_topic:
            self.record(ctx, fired=True, reason=f"strategy_request:{strategy_topic}")
            return self.build_result(
                ctx,
                destination="strategy_node",
                reason=f"strategy_ready:{strategy_topic}",
                intent="strategy",
                strategy_topic=strategy_topic,
                metadata_updates={
                    "router_path": f"strategy_ready:{strategy_topic}",
                    "router_bypassed": True,
                    "strategy_stage": 0,
                    "strategy_dest_known": bool(ctx.ti.destinations),
                    "post_ready_strategy": True,  # Flag to indicate strategy after ready
                },
            )

        # SETTINGS_CHANGE: Route to specialist when user answered a preference question
        # This triggers when user says "open to layovers" and flight_settings changes
        settings_changed = ctx.metadata.get("settings_changed_this_turn", {})
        if settings_changed:
            # Map settings field to specialist
            settings_to_specialist = {
                "flight_settings": ("flights", "flights_node"),
                "hotel_settings": ("hotels", "hotels_node"),
                "activity_settings": ("activities", "activities_node"),
                "transport_settings": ("transport", "transport_node"),
            }
            # Pick the first changed setting (usually only one changes per turn)
            for field, (specialist, destination) in settings_to_specialist.items():
                if field in settings_changed:
                    self.record(ctx, fired=True, reason=f"settings_changed:{field}")
                    return self.build_result(
                        ctx,
                        destination=destination,
                        reason=f"settings_changed:{specialist}",
                        intent=specialist,
                        metadata_updates={
                            "router_path": f"settings_changed:{specialist}",
                            "router_bypassed": True,
                            "settings_changed_specialist": specialist,
                        },
                    )

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
