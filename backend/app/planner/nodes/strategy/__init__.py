"""
Strategy Subpackage - Modular strategy node components.

This package contains extracted components from the monolithic strategy_main.py:
- base.py: Constants, feature flags, topic detection helpers
- stage0.py: Pre-core value-first strategy response (Stage0Coordinator)

The main strategy_node function is in nodes/strategy_main.py and re-exported here
for backward compatibility. Stage 1 and Stage 2 logic remains inline in strategy_main.py.
"""

# Re-export the main strategy functions for backward compatibility
from app.planner.nodes.strategy.base import (
    STRATEGY_KEYWORDS,
    STRATEGY_PRE_CORE_QUESTION_GUIDANCE,
    TOPIC_SWITCH_KEYWORDS,
    _generate_date_suggestions,
    _is_strategy_enabled,
    _should_escalate_from_stage0,
    _track_strategy_pre_core_question,
    detect_field_modification_request,
    detect_strategy_switch,
    detect_topic_switch,
    generate_date_suggestions,
    get_question_guidance,
    has_strategy_keyword,
    is_strategy_enabled,
    should_escalate_from_stage0,
    track_strategy_pre_core_question,
)
from app.planner.nodes.strategy.stage0 import (
    STAGE0_FALLBACK_TEMPLATES,
    Stage0Coordinator,
    get_dest_known_fallback,
    strategy_stage0,
)
from app.planner.nodes.strategy_main import (
    _strategy_stage0,
    strategy_node,
)

__all__ = [
    # Main functions (re-exported from strategy_main.py)
    "_strategy_stage0",
    "strategy_node",
    # Base constants
    "STRATEGY_KEYWORDS",
    "STRATEGY_PRE_CORE_QUESTION_GUIDANCE",
    "TOPIC_SWITCH_KEYWORDS",
    "STAGE0_FALLBACK_TEMPLATES",
    # Base functions (with underscore aliases for backward compatibility)
    "_is_strategy_enabled",
    "_should_escalate_from_stage0",
    "_track_strategy_pre_core_question",
    "_generate_date_suggestions",
    "is_strategy_enabled",
    "generate_date_suggestions",
    "track_strategy_pre_core_question",
    "should_escalate_from_stage0",
    "has_strategy_keyword",
    "detect_topic_switch",
    "detect_strategy_switch",
    "detect_field_modification_request",
    "get_question_guidance",
    # Stage 0 coordinator
    "Stage0Coordinator",
    "strategy_stage0",
    "get_dest_known_fallback",
]
