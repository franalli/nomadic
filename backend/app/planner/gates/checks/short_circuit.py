"""
Short-Circuit Gate Checks - P4 Module Extraction.

Contains logic for detecting inputs that can bypass LLM processing.
Used by GateEvaluator and specialists to skip unnecessary LLM calls.

Usage:
    from app.planner.gates.checks.short_circuit import is_vague_affirmation

    if is_vague_affirmation(user_text):
        # Skip LLM, use template response
"""

from __future__ import annotations

# Vague affirmations that don't provide actionable information
# Used by no-op specialist gate to skip LLM when user just confirms without details
VAGUE_AFFIRMATIONS = frozenset(
    {
        "ok",
        "okay",
        "sure",
        "yes",
        "yep",
        "yeah",
        "sounds good",
        "sounds great",
        "looks good",
        "looks great",
        "perfect",
        "great",
        "fine",
        "alright",
        "good",
        "nice",
        "cool",
        "maybe",
        "i guess",
        "i think so",
        "that works",
        "works for me",
    }
)


def is_vague_affirmation(text: str) -> bool:
    """
    Check if user text is a vague affirmation without actionable content.

    Vague affirmations like "sounds good", "okay", "sure" don't provide new
    information for specialists to process. When there are no pending missing
    fields, we can skip the LLM call entirely.

    Args:
        text: User text (will be lowercased and stripped)

    Returns:
        True if text is a vague affirmation, False otherwise
    """
    normalized = text.lower().strip()
    # Check exact match
    if normalized in VAGUE_AFFIRMATIONS:
        return True
    # Check if it's a very short confirmation (1-2 words, < 15 chars)
    words = normalized.split()
    if len(words) <= 2 and len(normalized) < 15:
        # Check if any word is an affirmation
        for word in words:
            if word in VAGUE_AFFIRMATIONS:
                return True
    return False


__all__ = [
    "VAGUE_AFFIRMATIONS",
    "is_vague_affirmation",
]
