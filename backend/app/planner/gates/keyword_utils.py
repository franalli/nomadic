"""Keyword matching utilities for gate evaluation.

Provides consistent keyword matching behavior across all gates.
Uses word boundary matching for single-word keywords and
substring matching for multi-word phrases.

Optimized with pre-compiled regex patterns for common keyword sets.
"""

from __future__ import annotations

import re
from typing import Dict, FrozenSet, Iterable, Optional, Pattern, Tuple, Union

# =============================================================================
# PRE-COMPILED PATTERN CACHE
# =============================================================================
# Cache for compiled regex patterns, keyed by frozenset id
# This avoids recompiling regex on every call
_COMPILED_PATTERNS: Dict[int, Tuple[Pattern[str], FrozenSet[str]]] = {}


def _get_or_compile_pattern(
    keywords: FrozenSet[str],
) -> Tuple[Optional[Pattern[str]], FrozenSet[str]]:
    """Get or compile a regex pattern for single-word keywords.

    Returns:
        (compiled_pattern, multi_word_keywords) where:
        - compiled_pattern: Regex for single-word matching (None if no single words)
        - multi_word_keywords: Set of multi-word phrases to check with 'in'
    """
    cache_key = id(keywords)

    if cache_key in _COMPILED_PATTERNS:
        return _COMPILED_PATTERNS[cache_key]

    single_words = []
    multi_words = []

    for kw in keywords:
        if " " in kw:
            multi_words.append(kw)
        else:
            single_words.append(kw)

    # Compile single-word pattern with alternation
    pattern = None
    if single_words:
        # Build pattern: \b(word1|word2|word3)\b
        escaped = [re.escape(w) for w in single_words]
        pattern = re.compile(r"\b(?:" + "|".join(escaped) + r")\b")

    result = (pattern, frozenset(multi_words))

    # Only cache for frozenset (stable identity)
    if isinstance(keywords, frozenset):
        _COMPILED_PATTERNS[cache_key] = result

    return result


def keyword_match(text: str, keywords: Union[FrozenSet[str], Iterable[str]]) -> bool:
    """Check if any keyword appears in text.

    Uses word boundary matching for single-word keywords to avoid false positives
    (e.g., "car" shouldn't match "scary"). Multi-word phrases use substring matching.

    Optimized: Pre-compiles and caches regex patterns for frozenset keywords.

    Args:
        text: Text to search in (should be lowercase for case-insensitive matching)
        keywords: Collection of keywords to search for

    Returns:
        True if any keyword is found, False otherwise

    Examples:
        >>> keyword_match("i want to book a flight", {"flight", "hotel"})
        True
        >>> keyword_match("what hotels are available", {"hotel", "hotels"})
        True
        >>> keyword_match("scary movie", {"car"})  # Word boundary prevents match
        False
        >>> keyword_match("ground transport options", {"ground transport"})
        True
    """
    # Fast path for frozenset (uses pre-compiled patterns)
    if isinstance(keywords, frozenset):
        pattern, multi_words = _get_or_compile_pattern(keywords)

        # Check single-word pattern
        if pattern and pattern.search(text):
            return True

        # Check multi-word phrases
        for phrase in multi_words:
            if phrase in text:
                return True

        return False

    # Fallback for non-frozenset (original behavior)
    for kw in keywords:
        if " " in kw:
            if kw in text:
                return True
        else:
            if re.search(rf"\b{re.escape(kw)}\b", text):
                return True
    return False


def find_matching_keyword(text: str, keywords: Union[FrozenSet[str], Iterable[str]]) -> str | None:
    """Find the first matching keyword in text.

    Uses the same matching logic as keyword_match().

    Args:
        text: Text to search in (should be lowercase for case-insensitive matching)
        keywords: Collection of keywords to search for

    Returns:
        The first matching keyword, or None if no match
    """
    # Fast path for frozenset
    if isinstance(keywords, frozenset):
        pattern, multi_words = _get_or_compile_pattern(keywords)

        # Check single-word pattern and find which keyword matched
        if pattern:
            match = pattern.search(text)
            if match:
                return match.group(0)

        # Check multi-word phrases
        for phrase in multi_words:
            if phrase in text:
                return phrase

        return None

    # Fallback for non-frozenset
    for kw in keywords:
        if " " in kw:
            if kw in text:
                return kw
        else:
            if re.search(rf"\b{re.escape(kw)}\b", text):
                return kw
    return None
