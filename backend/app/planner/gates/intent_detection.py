"""Intent-only input detection utilities.

Provides logic for detecting pure intent inputs (topic keywords without
extractable entities like dates, numbers, or locations).

This is used to fast-path inputs like "adventure hiking" directly to
required_fields without invoking the extractor LLM.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional, Tuple

from app.pattern_matching import DOMAIN_KEYWORDS, INTENT_ONLY_KEYWORDS, QUESTION_WORDS
from app.planner.gates.constants import SPECIALIST_NODE_MAP

if TYPE_CHECKING:
    from app.plan_graph import TripInputs


# Pattern to detect extractable entities that would require LLM extraction
# Matches: digits, currency symbols, month names, relative time words
ENTITY_DETECTION_PATTERN = re.compile(
    r"\d|"  # Any digit (dates, numbers, budget amounts)
    r"[$\u20ac\u00a3]|"  # Currency symbols ($, Euro, British Pound)
    # Month names
    r"\b(january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\b|"
    r"\b(next|this|last)\s+(week|month|year)\b"  # Relative time expressions
)


def check_intent_only_input(text_lower: str, ti: "TripInputs") -> Optional[str]:
    """Check if input is intent-only (topic keywords without extractable entities).

    Intent-only inputs are pure topic expressions like "adventure hiking" or
    "beach vacation" that don't contain dates, numbers, or other extractable
    entities. These can skip the extractor LLM and route directly to
    required_fields.

    Args:
        text_lower: User text in lowercase
        ti: Current TripInputs state

    Returns:
        Detected topic (e.g., "hiking", "beach") or None if not intent-only

    Examples:
        >>> check_intent_only_input("adventure hiking", TripInputs())
        'hiking'  # or 'adventure', depending on keyword order
        >>> check_intent_only_input("beach vacation", TripInputs())
        'beach'  # or 'relaxation'
        >>> check_intent_only_input("hiking in march", TripInputs())
        None  # Has month name (extractable entity)
        >>> check_intent_only_input("adventure", TripInputs(destinations=["Paris"]))
        None  # Has existing trip data
    """
    # If we already have any concrete data, not intent-only
    if ti.destinations or ti.origin or ti.start_date or ti.budget or ti.adults:
        return None

    # Check for intent keywords
    words = text_lower.split()
    detected_topics = []
    for word in words:
        clean_word = word.strip(".,!?;:")
        if clean_word in INTENT_ONLY_KEYWORDS:
            detected_topics.append(INTENT_ONLY_KEYWORDS[clean_word])

    if not detected_topics:
        return None

    # Check for extractable entities that would require LLM
    if ENTITY_DETECTION_PATTERN.search(text_lower):
        return None

    # Prefer strategy topics over general ones
    strategy_topics = {"hiking", "skiing", "diving", "cycling", "boating"}
    for topic in detected_topics:
        if topic in strategy_topics:
            return topic

    # Return first detected topic
    return detected_topics[0] if detected_topics else None


def check_question_keyword_combo(text_lower: str) -> Optional[Tuple[str, str]]:
    """Check for question-word + domain keyword combinations.

    Detects patterns like "what hotels are available" or "which flights".
    Used for explicit intent detection in routing.

    Args:
        text_lower: User text in lowercase

    Returns:
        (intent_name, destination_node) if match, None otherwise

    Examples:
        >>> check_question_keyword_combo("what hotels are available")
        ('hotels', 'hotels_node')
        >>> check_question_keyword_combo("which flights to paris")
        ('flights', 'flights_node')
        >>> check_question_keyword_combo("I want to book a hotel")
        None  # No question word at start
    """
    words = text_lower.split()
    if not words:
        return None

    # Check if starts with question word
    first_word = words[0].rstrip("?.,")
    if first_word not in QUESTION_WORDS:
        return None

    # Check for domain keywords
    for intent_name, keywords in DOMAIN_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return (intent_name, SPECIALIST_NODE_MAP[intent_name])

    return None
