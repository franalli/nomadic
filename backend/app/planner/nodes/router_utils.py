"""
Router Utilities — Shared constants and functions used by both
intent_router.py and router_category_sync.py.

Extracted to eliminate duplication of:
- EXACT_MATCH_GREETINGS (frozenset)
- ORIGIN_PATTERNS (list of regex strings)
- get_new_specialists_from_text()
- _extract_destination_context()
- _check_exact_match_greeting()
- _detect_origin_from_message()
"""

import logging
import re
from typing import TYPE_CHECKING, List, Optional

from app.planner.nodes.router_extraction import (
    IntentClassification,
    _normalize_city_name,
)
from app.planner.specialist_registry import ALL_SPECIALIST_KEYWORDS

if TYPE_CHECKING:
    from app.planner.state import GraphState

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

EXACT_MATCH_GREETINGS = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "yo",
        "sup",
        "hi!",
        "hello!",
        "hey!",
        "good morning",
        "good afternoon",
        "good evening",
        "morning",
        "afternoon",
        "evening",
        "thanks",
        "thank you",
        "thanks!",
        "thank you!",
        "bye",
        "goodbye",
        "bye!",
        "goodbye!",
        "cheers",
        "ciao",
        "hola",
    }
)

ORIGIN_PATTERNS = [
    r"^(?:i(?:'m|'m| am)\s+)?(?:leaving|departing|flying|coming|traveling)?\s*from\s+(\S.+)$",
    r"^(?:departure|depart(?:ing)?|leav(?:e|ing))\s+from\s+(\S.+)$",
    r"^from\s+(\S.+)$",  # Most common: "from rome"
]


# ============================================================================
# Specialist Detection
# ============================================================================


def get_new_specialists_from_text(text: str, existing_specialists: List[str]) -> List[str]:
    """
    Get list of NEW specialists mentioned in text that aren't already in the plan.

    Args:
        text: User message
        existing_specialists: List of specialist types already in the plan

    Returns:
        List of new specialist types to add
    """
    text_lower = text.lower()
    new_specialists = []

    for specialist_type, keywords in ALL_SPECIALIST_KEYWORDS.items():
        if specialist_type in existing_specialists:
            continue  # Already have this specialist

        if any(kw in text_lower for kw in keywords):
            new_specialists.append(specialist_type)

    return new_specialists


# ============================================================================
# Destination Context Extraction
# ============================================================================


def _extract_destination_context(state: "GraphState") -> Optional[str]:
    """Extract destination from conversation context or trip plan.

    Priority:
    1. Conversation context (last_destination_context)
    2. trip_plan.destination

    NOTE: Direct destination detection from text is handled by the LLM extraction
    path (_classify_and_extract_with_llm), not here. This function only provides
    fallback context for the router.
    """
    # Fallback to conversation context
    if state.metadata.get("last_destination_context"):
        return state.metadata["last_destination_context"]

    if state.trip_plan and state.trip_plan.destination:
        return state.trip_plan.destination

    return None


# ============================================================================
# Greeting Detection
# ============================================================================


def _check_exact_match_greeting(text: str) -> Optional[IntentClassification]:
    """
    Check if input matches known greeting patterns exactly.

    Returns IntentClassification if matched, None otherwise.
    Saves an LLM call for trivial inputs (~300ms, ~150 tokens).
    """
    normalized = text.strip().lower()

    if normalized in EXACT_MATCH_GREETINGS:
        logger.debug(f"Exact match greeting detected: '{text}'")
        return IntentClassification(
            intent="GREETING",
            confidence=1.0,
            reasoning="Exact match greeting - no LLM needed",
            specialist_hints=[],
        )

    return None


# ============================================================================
# Origin Detection
# ============================================================================


def _detect_origin_from_message(user_text: str) -> Optional[str]:
    """
    Detect if user message is specifying an origin/departure city.
    Returns normalized city name if detected, None otherwise.

    Must run BEFORE exploration mode check to prevent "from rome" being
    interpreted as exploring Rome when user means "departing from Rome".

    Examples:
        "from rome" → "Rome"
        "flying from london" → "London"
        "leaving from NYC" → "New York"
        "tell me about rome" → None (not an origin pattern)
    """
    text = user_text.strip()

    # Quick reject: if message doesn't contain "from", skip
    if "from" not in text.lower():
        return None

    for pattern in ORIGIN_PATTERNS:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            city = match.group(1).strip().rstrip(".!?,")
            # Truncate at destination indicators: "rome to bali" → "rome"
            city = re.split(r"\s+to\s+", city, maxsplit=1, flags=re.IGNORECASE)[0].strip()
            # Truncate at date-like tokens: "rome feb 11" → "rome"
            city = re.split(
                r"\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|\d{1,2}[/-])\b",
                city,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip()
            # Normalize: "rome italy" → "Rome", remove country suffixes
            city = _normalize_city_name(city)
            if city:
                # Title case the city name for display
                return city.title()

    return None
