"""
Routing Keywords Module for Intent Classification.

This module contains keyword mappings and phrase sets used for deterministic
router bypass decisions. Centralizing these here improves maintainability
and allows for easier testing and updates.

Sections:
    1. KEYWORD_TO_INTENT - Maps keywords to (intent_name, strategy_topic)
    2. AMBIGUOUS_KEYWORDS - Keywords that should not trigger bypass
    3. NEGATION_PATTERNS - Phrases indicating negation
    4. POSITIVE_INTENT_PATTERNS - Phrases indicating positive intent
"""

from typing import Dict, FrozenSet, Optional, Tuple

# =============================================================================
# 1. KEYWORD TO INTENT MAPPING
# =============================================================================
# Maps keywords to (intent_name, strategy_topic)
# strategy_topic is only set for strategy-related keywords

KEYWORD_TO_INTENT: Dict[str, Tuple[str, Optional[str]]] = {
    # Hotel keywords
    "hotel": ("hotels", None),
    "hotels": ("hotels", None),
    "accommodation": ("hotels", None),
    "accommodations": ("hotels", None),
    "stay": ("hotels", None),
    "lodging": ("hotels", None),
    "hostel": ("hotels", None),
    "airbnb": ("hotels", None),
    "booking": ("hotels", None),
    # Hotel preference keywords (route to hotels for settings updates)
    "star": ("hotels", None),
    "breakfast": ("hotels", None),
    "amenities": ("hotels", None),
    "gym": ("hotels", None),
    "pool": ("hotels", None),
    "spa": ("hotels", None),
    # Flight keywords
    "flight": ("flights", None),
    "flights": ("flights", None),
    "fly": ("flights", None),
    "flying": ("flights", None),
    "plane": ("flights", None),
    "airplane": ("flights", None),
    "airline": ("flights", None),
    "airport": ("flights", None),
    # Flight preference keywords (route to flights for settings updates)
    "direct": ("flights", None),
    "nonstop": ("flights", None),
    "business class": ("flights", None),
    "first class": ("flights", None),
    "economy class": ("flights", None),
    "cabin class": ("flights", None),
    "layover": ("flights", None),
    "one-way": ("flights", None),
    "round-trip": ("flights", None),
    # Transport keywords
    "transport": ("transport", None),
    "transportation": ("transport", None),
    "train": ("transport", None),
    "bus": ("transport", None),
    "taxi": ("transport", None),
    "uber": ("transport", None),
    "rental car": ("transport", None),
    "car rental": ("transport", None),
    "ferry": ("transport", None),
    # Activity keywords
    "activity": ("activities", None),
    "activities": ("activities", None),
    "things to do": ("activities", None),
    "attractions": ("activities", None),
    "sightseeing": ("activities", None),
    "tour": ("activities", None),
    "tours": ("activities", None),
    "museum": ("activities", None),
    "restaurant": ("activities", None),
    "restaurants": ("activities", None),
    # Strategy keywords (with topics)
    "hiking": ("strategy", "hiking"),
    "hike": ("strategy", "hiking"),
    "trek": ("strategy", "hiking"),
    "trekking": ("strategy", "hiking"),
    "trail": ("strategy", "hiking"),
    "mountain": ("strategy", "hiking"),
    "diving": ("strategy", "diving"),
    "scuba": ("strategy", "diving"),
    "snorkeling": ("strategy", "diving"),
    "underwater": ("strategy", "diving"),
    "skiing": ("strategy", "skiing"),
    "ski": ("strategy", "skiing"),
    "snowboard": ("strategy", "skiing"),
    "snowboarding": ("strategy", "skiing"),
    "slopes": ("strategy", "skiing"),
    "cycling": ("strategy", "cycling"),
    "bike": ("strategy", "cycling"),
    "biking": ("strategy", "cycling"),
    "bicycle": ("strategy", "cycling"),
    "boating": ("strategy", "boating"),
    "boat": ("strategy", "boating"),
    "sailing": ("strategy", "boating"),
    "yacht": ("strategy", "boating"),
    "kayak": ("strategy", "boating"),
    "kayaking": ("strategy", "boating"),
}


# =============================================================================
# 2. AMBIGUOUS KEYWORDS
# =============================================================================
# Keywords that are ambiguous and should NOT trigger keyword bypass
# (user might mean something else, defer to router LLM)

AMBIGUOUS_KEYWORDS: FrozenSet[str] = frozenset(
    {
        "book",  # Could be hotel booking or "read a book"
        "trip",  # General planning, not specific
        "travel",  # General planning
        "vacation",  # General planning
        "help",  # General assistance
        "plan",  # General planning
        "itinerary",  # General planning
    }
)


# =============================================================================
# 3. NEGATION PATTERNS
# =============================================================================
# Negation patterns that should cause keyword bypass to defer to router LLM
# Example: "I don't want a hotel" should NOT route to hotels specialist

NEGATION_PATTERNS: FrozenSet[str] = frozenset(
    {
        "don't",
        "dont",
        "do not",
        "no ",
        "not ",
        "skip",
        "without",
        "avoid",
        "don't need",
        "dont need",
        "don't want",
        "dont want",
        "not interested",
        "cancel",
    }
)


# =============================================================================
# 4. POSITIVE INTENT PATTERNS
# =============================================================================
# Positive intent patterns that strengthen keyword bypass confidence
# When positive intent + domain keyword detected, bypass router with high confidence
# Example: "I want to find a hotel" → positive intent + hotel = strong bypass

POSITIVE_INTENT_PATTERNS: FrozenSet[str] = frozenset(
    {
        "i want",
        "i need",
        "i'd like",
        "i would like",
        "looking for",
        "find me",
        "find a",
        "search for",
        "show me",
        "get me",
        "can you find",
        "can you show",
        "help me find",
        "recommend",
        "suggest",
        # Phase 5 additions for higher bypass rate
        "compare",
        "options for",
        "recommend me",
        "itinerary for",
        "road trip",
        "multi-city",
        "multi city",
        "plan a",
        "planning a",
        "book a",
        "arrange",
    }
)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def has_positive_intent(text: str) -> Optional[str]:
    """
    Check if text contains a positive intent pattern.

    Args:
        text: Lowercase user text

    Returns:
        The matched pattern if found, None otherwise
    """
    text_lower = text.lower()
    for pattern in POSITIVE_INTENT_PATTERNS:
        if pattern in text_lower:
            return pattern
    return None


def is_keyword_negated(text: str, keyword: str, window: int = 20) -> bool:
    """
    Check if a keyword is negated in the text.

    Looks for negation patterns within `window` characters before the keyword.
    Examples:
        "I don't want a hotel" + "hotel" → True (negated)
        "I want a hotel" + "hotel" → False (not negated)
        "no flights please" + "flight" → True (negated)

    Args:
        text: Full text to search
        keyword: The keyword to check negation for
        window: Number of characters before keyword to check

    Returns:
        True if keyword appears to be negated
    """
    text_lower = text.lower()
    keyword_lower = keyword.lower()

    # Find all occurrences of the keyword
    start = 0
    while True:
        idx = text_lower.find(keyword_lower, start)
        if idx == -1:
            break

        # Check the window before this occurrence
        window_start = max(0, idx - window)
        prefix = text_lower[window_start:idx]

        # Check for negation patterns in the window
        for neg_pattern in NEGATION_PATTERNS:
            if neg_pattern in prefix:
                return True

        start = idx + 1

    return False


def has_ambiguous_keyword(text: str) -> bool:
    """
    Check if text contains an ambiguous keyword that should defer to router LLM.

    Args:
        text: User text to check

    Returns:
        True if text contains an ambiguous keyword
    """
    text_lower = text.lower()
    for keyword in AMBIGUOUS_KEYWORDS:
        if keyword in text_lower:
            return True
    return False
