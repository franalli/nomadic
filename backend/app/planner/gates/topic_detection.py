"""Strategy topic detection utilities.

Provides consolidated logic for detecting strategy topics (hiking, diving, skiing,
cycling, boating) from user text and activity settings.

Extracted from evaluator.py to eliminate duplicate topic detection loops.

Provides two detection modes:
- Substring matching (detect_strategy_topic_from_text): Fast, may have false positives
- Regex word boundaries (detect_strategy_topic_from_text_precise): Precise, no false positives
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Dict, FrozenSet, Optional, Pattern, Set

from app.pattern_matching import STRATEGY_INTENT_KEYWORDS, STRATEGY_TOPICS

# Pre-compiled regex patterns for precise topic detection (word boundaries)
# Avoids false positives like "skippered" matching "ski" or "skilled" matching "ski"
STRATEGY_TOPIC_PATTERNS: Dict[str, Pattern[str]] = {}


def _init_topic_patterns() -> None:
    """Initialize regex patterns with word boundaries for precise matching."""
    global STRATEGY_TOPIC_PATTERNS
    for topic, keywords in STRATEGY_INTENT_KEYWORDS.items():
        # Build alternation pattern: \b(hike|hiking|trek|...)\b
        pattern_str = r"\b(" + "|".join(re.escape(kw) for kw in keywords) + r")\b"
        STRATEGY_TOPIC_PATTERNS[topic] = re.compile(pattern_str, re.IGNORECASE)


# Initialize patterns at module load time
_init_topic_patterns()

if TYPE_CHECKING:
    pass


def detect_strategy_topic_from_text(text: str) -> Optional[str]:
    """Detect strategy topic from user text keywords (substring matching).

    Checks text against STRATEGY_INTENT_KEYWORDS for each topic.
    Uses simple substring matching which is fast but may have false positives
    (e.g., "skippered" matches "ski").

    For precise matching with word boundaries, use detect_strategy_topic_from_text_precise().

    Args:
        text: User input text

    Returns:
        Topic name (hiking, diving, etc.) or None if no match
    """
    text_lower = text.lower()
    for topic, keywords in STRATEGY_INTENT_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return topic
    return None


def detect_strategy_topic_from_text_precise(text: str) -> Optional[str]:
    """Detect strategy topic from user text using regex word boundaries.

    Uses pre-compiled regex patterns with word boundaries to avoid false positives.
    For example, "skippered" will NOT match "ski" because "ski" is not at a word boundary.

    This is more precise than detect_strategy_topic_from_text() but slightly slower.
    Use this when precision matters (e.g., strategy bootstrap bypass).

    Args:
        text: User input text

    Returns:
        Topic name (hiking, diving, skiing, cycling, boating) or None if no match

    Examples:
        >>> detect_strategy_topic_from_text_precise("I want to go skiing")
        'skiing'
        >>> detect_strategy_topic_from_text_precise("I need a skippered yacht")  # No false positive
        None
        >>> detect_strategy_topic_from_text_precise("bareboat charter please")  # No false positive
        None
    """
    for topic, pattern in STRATEGY_TOPIC_PATTERNS.items():
        if pattern.search(text):
            return topic
    return None


def detect_strategy_topic_from_settings(
    activity_settings: Dict[str, Any],
) -> Optional[str]:
    """Detect strategy topic from activity settings categories.

    Checks if any category in activity_settings matches a known strategy topic.

    Args:
        activity_settings: Dict with "categories" list

    Returns:
        Topic name or None if no match
    """
    categories = activity_settings.get("categories", [])
    for cat in categories:
        cat_lower = cat.lower()
        if cat_lower in STRATEGY_TOPICS:
            return cat_lower
    return None


def detect_strategy_topic(
    text: str,
    activity_settings: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Detect strategy topic from text or activity settings.

    Tries text first, then falls back to activity_settings if no match.

    Args:
        text: User input text
        activity_settings: Optional dict with "categories" list

    Returns:
        Topic name (hiking, diving, skiing, cycling, boating) or None
    """
    # First try text keywords
    topic = detect_strategy_topic_from_text(text)
    if topic:
        return topic

    # Fall back to activity settings
    if activity_settings:
        return detect_strategy_topic_from_settings(activity_settings)

    return None


def has_strategy_topic(text: str) -> bool:
    """Check if text contains any strategy topic keywords.

    Args:
        text: User input text

    Returns:
        True if any strategy keyword found
    """
    return detect_strategy_topic_from_text(text) is not None


def get_all_strategy_keywords() -> FrozenSet[str]:
    """Get all strategy keywords as a frozen set.

    Useful for exclusion checks (e.g., "not any(kw in text for kw in keywords)").

    Returns:
        FrozenSet of all strategy keywords across all topics
    """
    all_keywords: Set[str] = set()
    for keywords in STRATEGY_INTENT_KEYWORDS.values():
        all_keywords.update(keywords)
    return frozenset(all_keywords)


# Pre-computed for efficiency in hot paths
ALL_STRATEGY_KEYWORDS: FrozenSet[str] = get_all_strategy_keywords()


def text_contains_strategy_keyword(text: str) -> bool:
    """Check if text contains any strategy keyword (fast path).

    Uses pre-computed ALL_STRATEGY_KEYWORDS for efficiency.

    Args:
        text: User input text

    Returns:
        True if any strategy keyword found
    """
    text_lower = text.lower()
    return any(kw in text_lower for kw in ALL_STRATEGY_KEYWORDS)
