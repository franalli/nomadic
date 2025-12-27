"""
Strategy Base - Shared constants and utilities for strategy nodes.

Contains:
- Feature flag checks
- Question guidance for pre-core prompts
- Topic switch detection
- Date suggestion generation
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Dict, List, Optional, Set

if TYPE_CHECKING:
    from app.plan_graph import GraphState

# Question guidance for strategy_pre_core prompt based on question_target
STRATEGY_PRE_CORE_QUESTION_GUIDANCE: Dict[str, str] = {
    "dates": (
        "Ask about timing/season. Examples:\n"
        '- "When are you thinking of going? Spring and fall are usually best."\n'
        '- "What month or season works for you?"'
    ),
    "origin": (
        "Ask about departure location. Examples:\n"
        '- "Where will you be traveling from?"\n'
        '- "What city will you be departing from?"'
    ),
    "destinations": (
        "Ask about preferred destination (only if other fields are set). Examples:\n"
        '- "Which of these regions appeals to you most?"\n'
        '- "Any of these destinations catching your eye?"'
    ),
    "travelers": (
        "Ask about who is traveling. Examples:\n"
        '- "Who will be joining you on this trip?"\n'
        '- "How many people are in your group?"'
    ),
}

# Strategy topic keywords for relevance checking
STRATEGY_KEYWORDS: Dict[str, Set[str]] = {
    "hiking": {"hike", "hiking", "trek", "trekking", "trail", "mountain", "climb"},
    "diving": {"dive", "diving", "scuba", "snorkel", "snorkeling", "underwater"},
    "skiing": {"ski", "skiing", "snowboard", "snowboarding", "slopes", "powder"},
    "cycling": {"bike", "biking", "bicycle", "cycling", "ride", "pedal"},
    "boating": {"boat", "boating", "sail", "sailing", "yacht", "kayak", "canoe"},
}

# Keywords that indicate user wants a different category (not strategy)
TOPIC_SWITCH_KEYWORDS: Dict[str, str] = {
    "car": "ground_transport",
    "rental": "ground_transport",
    "rent a car": "ground_transport",
    "car rental": "ground_transport",
    "drive": "ground_transport",
    "driving": "ground_transport",
    "train": "ground_transport",
    "bus": "ground_transport",
    "transport": "ground_transport",
    "hotel": "hotels",
    "hotels": "hotels",
    "accommodation": "hotels",
    "stay": "hotels",
    "where to stay": "hotels",
    "lodging": "hotels",
    "flight": "flights",
    "flights": "flights",
    "fly": "flights",
    "flying": "flights",
    "airline": "flights",
}


def _is_strategy_enabled(topic: str) -> bool:
    """Check if a strategy is enabled via feature flags."""
    from app.config import settings

    flag_map = {
        "boating": settings.enable_strategy_boating,
        "hiking": settings.enable_strategy_hiking,
        "diving": settings.enable_strategy_diving,
        "skiing": settings.enable_strategy_skiing,
        "cycling": settings.enable_strategy_cycling,
    }
    return flag_map.get(topic, True)  # Default to enabled for unknown topics


# Alias for cleaner public API
is_strategy_enabled = _is_strategy_enabled


def generate_date_suggestions() -> List[str]:
    """Generate relative date suggestions for stage0 fallback."""
    today = date.today()

    # Calculate "next month" and "in 3 months"
    next_month = today + timedelta(days=30)
    three_months = today + timedelta(days=90)

    return [
        f"Around {next_month.strftime('%B')}",
        f"In {three_months.strftime('%B')}",
        "I'm flexible on dates",
    ]


def track_strategy_pre_core_question(state: "GraphState", question_target: str) -> None:
    """Track questions asked in stage 0 for loop guard."""
    key = "strategy_pre_core_questions"
    if key not in state.metadata:
        state.metadata[key] = []
    state.metadata[key].append(question_target)


def should_escalate_from_stage0(state: "GraphState") -> bool:
    """
    Check if we should escalate from stage 0 to required_fields.

    Returns True if user has ignored stage 0 questions twice.
    """
    questions = state.metadata.get("strategy_pre_core_questions", [])
    return len(questions) >= 2


def has_strategy_keyword(user_text: str, topic: str) -> bool:
    """Check if user text contains keywords for the given strategy topic."""
    user_text_lower = user_text.lower()
    topic_keywords = STRATEGY_KEYWORDS.get(topic, set())
    return any(kw in user_text_lower for kw in topic_keywords)


def detect_topic_switch(user_text: str) -> Optional[str]:
    """
    Detect if user wants to switch to a different category.

    Returns the detected category or None.
    """
    user_text_lower = user_text.lower()
    for keyword, category in TOPIC_SWITCH_KEYWORDS.items():
        if keyword in user_text_lower:
            return category
    return None


def detect_strategy_switch(user_text: str, current_topic: str) -> Optional[str]:
    """
    Detect if user wants to switch to a different strategy topic.

    Returns the new topic or None.
    """
    user_text_lower = user_text.lower()
    for other_topic, other_keywords in STRATEGY_KEYWORDS.items():
        if other_topic != current_topic:
            if any(kw in user_text_lower for kw in other_keywords):
                return other_topic
    return None


def get_question_guidance(question_target: str) -> str:
    """Get question guidance for a given target."""
    return STRATEGY_PRE_CORE_QUESTION_GUIDANCE.get(
        question_target,
        STRATEGY_PRE_CORE_QUESTION_GUIDANCE["dates"],
    )


# Aliases for backward compatibility with underscore-prefixed names
_track_strategy_pre_core_question = track_strategy_pre_core_question
_should_escalate_from_stage0 = should_escalate_from_stage0
_generate_date_suggestions = generate_date_suggestions
