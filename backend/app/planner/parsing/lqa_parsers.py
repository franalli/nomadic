"""
LQA Field Parsers - Low-Query Automation for field-specific answers.

This module contains deterministic parsers for each LQA field type:
- Destination parsing
- Origin parsing
- Date parsing (with year clarification, relative durations, month ranges)
- Travelers parsing (with kids support)
- Budget parsing (amounts and flexible tiers)
- Duration parsing

Extracted from plan_graph.py as part of the Tier 4 module extraction initiative.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Protocol

from app.known_places import is_known_place, normalize_place_synonym
from app.pattern_matching import (
    ARTICLE_PREFIX_PATTERN,
    BUDGET_PATTERN,
    COMPOUND_DATE_TRAVELERS_PATTERN,
    COMPOUND_KEYWORDS,
    COMPOUND_TRAVELERS_DATE_PATTERN,
    DURATION_PATTERN,
    INLINE_BUDGET_PATTERN,
    NEGATION_ALTERNATIVE_PATTERN,
    NO_BUDGET_PHRASES,
    ORIGIN_PREFIX_PATTERN,
    RELATIVE_DATE_WORDS_ALL,
    SIMPLE_NEGATION_PATTERN,
    TRAVELERS_PATTERN,
    TRAVELERS_WITH_KIDS_PATTERN,
    WORD_TO_NUMBER,
    YEAR_CLARIFY_PATTERNS,
    is_text_date_compatible,
)

if TYPE_CHECKING:
    from app.plan_graph import GraphState


# =============================================================================
# PROTOCOL DEFINITIONS (for dependency injection)
# =============================================================================


class DateNormalizerProtocol(Protocol):
    """Protocol for date normalizer to avoid circular imports."""

    def normalize(self, text: str) -> Optional[str]:
        """Normalize a date string to ISO format."""
        ...

    def parse_date_range(self, text: str) -> tuple[Optional[str], Optional[str]]:
        """Parse a date range from text."""
        ...


# =============================================================================
# CONSTANTS
# =============================================================================

# Local alias for backward compatibility
_ARTICLE_PREFIX = ARTICLE_PREFIX_PATTERN

# Month name patterns (for date detection)
_MONTH_NAMES = frozenset(
    {
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "jan",
        "feb",
        "mar",
        "apr",
        "jun",
        "jul",
        "aug",
        "sep",
        "sept",
        "oct",
        "nov",
        "dec",
    }
)

# Relative date keywords - alias from pattern_matching
_RELATIVE_DATE_WORDS = RELATIVE_DATE_WORDS_ALL

# Activity modifier words (V16) - exclude from place-like detection
# These indicate activity preferences, not place names
_ACTIVITY_MODIFIER_WORDS = frozenset(
    {
        "beginner",
        "intermediate",
        "advanced",
        "expert",
        "easy",
        "moderate",
        "difficult",
        "challenging",
        "friendly",
        "casual",
        "professional",
        "family",
        "kid",
        "child",
        "senior",
        "budget",
        "luxury",
        "short",
        "long",
        "day",
        "multi",
    }
)

# Strategy keywords for activity preference detection
_STRATEGY_KEYWORDS = frozenset(
    {
        "hiking",
        "trekking",
        "diving",
        "snorkeling",
        "skiing",
        "snowboarding",
        "cycling",
        "biking",
        "boating",
        "sailing",
    }
)


# =============================================================================
# DATE DETECTION HELPERS
# =============================================================================


def _is_date_like_text(text: str) -> bool:
    """
    Check if text looks like it could be a date answer.

    Returns True if the text contains date-like tokens (digits, month names,
    relative date words). Returns False for location-like text (capitalized
    proper nouns without date indicators).

    This is used to skip LQA date parsing on clearly non-date text like
    "Swiss Alps" when question_target is "dates".

    CONSOLIDATION NOTE: This now delegates to is_text_date_compatible() from
    pattern_matching.py which is the single source of truth for date detection.
    """
    # Delegate to consolidated date compatibility check
    return is_text_date_compatible(text)


def _is_place_like_text(text: str) -> bool:
    """
    Check if text looks like a place/destination name.

    Returns True for text that appears to be a location rather than a date.
    Used to skip LQA date parsing.

    V16: Excludes activity modifiers (beginner, advanced, easy, etc.) from
    place detection to avoid false positives on suggestions like
    "Beginner-friendly hiking".
    """
    # Check if it's a known place
    if is_known_place(text):
        return True

    # V16: Check if text is an activity preference (modifier + strategy keyword)
    # These should not be treated as place names
    if _is_activity_preference_text(text):
        return False

    # Check for capitalized words (proper nouns suggesting places)
    # But exclude single common words
    words = text.split()
    if len(words) >= 1:
        # V16: Filter out activity modifier words before counting
        capitalized_words = []
        for w in words:
            if len(w) > 1 and w[0].isupper():
                w_lower = w.lower()
                # Exclude activity modifiers
                if w_lower in _ACTIVITY_MODIFIER_WORDS:
                    continue
                # Exclude words ending in "-friendly" (e.g., "Beginner-friendly")
                if (
                    "-friendly" in w.lower()
                    or "-" in w
                    and any(part.lower() in _ACTIVITY_MODIFIER_WORDS for part in w.split("-"))
                ):
                    continue
                # Exclude strategy keywords
                if w_lower in _STRATEGY_KEYWORDS:
                    continue
                capitalized_words.append(w)

        # Multiple capitalized words or a known place pattern
        if len(capitalized_words) >= 2:
            return True
        # Single capitalized word that's not a month
        if len(capitalized_words) == 1:
            word_lower = capitalized_words[0].lower()
            if word_lower not in _MONTH_NAMES and word_lower not in _RELATIVE_DATE_WORDS:
                return True

    return False


def _is_activity_preference_text(text: str) -> bool:
    """
    Check if text is an activity preference (V16).

    Returns True if text contains both:
    - An activity modifier word (beginner, advanced, easy, etc.)
    - A strategy keyword (hiking, diving, skiing, etc.)

    Examples:
    - "Beginner-friendly hiking" -> True
    - "Advanced skiing" -> True
    - "Easy trails" -> False (no strategy keyword)
    - "Swiss Alps" -> False (no modifier)
    """
    text_lower = text.lower()
    words = set(re.split(r"[-\s]+", text_lower))

    has_modifier = bool(words & _ACTIVITY_MODIFIER_WORDS)
    has_strategy = bool(words & _STRATEGY_KEYWORDS)

    return has_modifier and has_strategy


# =============================================================================
# FIELD PARSERS
# =============================================================================


def _parse_destination_answer(text: str, state: "GraphState") -> Optional[Dict[str, Any]]:
    """Parse a destination answer. Returns parsed dict or None."""
    # First check if the raw text is a known place
    if is_known_place(text):
        # If so, normalize it for consistency
        normalized = normalize_place_synonym(text)
        return {"destinations_delta": [normalized]}
    # Also try the normalized version (in case synonym maps to different casing)
    normalized = normalize_place_synonym(text)
    if is_known_place(normalized):
        return {"destinations_delta": [normalized]}

    # V36: Handle "City, Country" format (e.g., "Paris, France")
    # Try extracting the city part before the comma
    if "," in text:
        city_part = text.split(",")[0].strip()
        if is_known_place(city_part):
            normalized = normalize_place_synonym(city_part)
            return {"destinations_delta": [normalized]}
        normalized = normalize_place_synonym(city_part)
        if is_known_place(normalized):
            return {"destinations_delta": [normalized]}

    # Strip leading articles ("the Netherlands" -> "Netherlands")
    stripped = _ARTICLE_PREFIX.sub("", text).strip()
    if stripped != text:
        if is_known_place(stripped):
            normalized = normalize_place_synonym(stripped)
            return {"destinations_delta": [normalized]}
        normalized = normalize_place_synonym(stripped)
        if is_known_place(normalized):
            return {"destinations_delta": [normalized]}

    return None


def _parse_origin_answer(text: str, state: "GraphState") -> Optional[Dict[str, Any]]:
    """Parse an origin answer, handling 'from X' prefix. Returns parsed dict or None."""
    # Try with "from" prefix first
    origin_match = ORIGIN_PREFIX_PATTERN.match(text)
    if origin_match:
        origin_text = origin_match.group(2).strip()
    else:
        origin_text = text

    # First check if the raw text is a known place
    if is_known_place(origin_text):
        # If so, normalize it for consistency
        normalized = normalize_place_synonym(origin_text)
        return {"origin_delta": normalized}
    # Also try the normalized version (in case synonym maps to different casing)
    normalized = normalize_place_synonym(origin_text)
    if is_known_place(normalized):
        return {"origin_delta": normalized}
    return None


def _parse_date_answer(
    text: str,
    state: "GraphState",
    date_normalizer: Optional[DateNormalizerProtocol] = None,
) -> Optional[Dict[str, Any]]:
    """
    Parse a date answer. Returns parsed dict or None.

    Extended to handle:
    - Year clarification responses like "This December", "Next December"
    - "This year", "Next year"
    - Explicit years like "2025", "2026"
    - V37: Relative durations when question_target is "end_date" and start_date is known
      (e.g., "a week", "10 days", "2 weeks")

    Args:
        text: User input text
        state: Current graph state
        date_normalizer: Optional DateNormalizer instance (defaults to plan_graph._date_normalizer)
    """
    # Get date_normalizer if not provided (lazy import to avoid circular deps)
    if date_normalizer is None:
        from app.plan_graph import _date_normalizer

        date_normalizer = _date_normalizer

    text_stripped = text.strip()

    # -------------------------------------------------------------------------
    # V37: Handle relative durations when asked for end_date with start_date set
    # -------------------------------------------------------------------------
    # If we're asking for end_date and user responds with a duration ("a week"),
    # compute end_date from start_date + duration.
    question_target = state.question_target or state.metadata.get("question_target")
    ti = state.trip_inputs
    if question_target == "end_date" and ti.start_date and not ti.end_date:
        text_lower = text_stripped.lower()
        # Match patterns like "a week", "one week", "10 days", "2 weeks", "3-4 days"
        duration_patterns = [
            (r"^a\s+week$", 7),
            (r"^one\s+week$", 7),
            (r"^(\d+)\s*weeks?$", lambda m: int(m.group(1)) * 7),
            (r"^(\d+)\s*days?$", lambda m: int(m.group(1))),
            (r"^(\.d+)\s*nights?$", lambda m: int(m.group(1))),
            (r"^(\d+)[-–](\d+)\s*days?$", lambda m: int(m.group(2))),  # Use upper bound
            (r"^about\s+(\d+)\s*days?$", lambda m: int(m.group(1))),
            (r"^around\s+(\d+)\s*days?$", lambda m: int(m.group(1))),
            (
                r"^(two|three|four|five|six|seven|eight|nine|ten)\s+weeks?$",
                lambda m: WORD_TO_NUMBER.get(m.group(1), 1) * 7,
            ),
            (
                r"^(two|three|four|five|six|seven|eight|nine|ten)\s+days?$",
                lambda m: WORD_TO_NUMBER.get(m.group(1), 1),
            ),
        ]
        for pattern, days_or_func in duration_patterns:
            match = re.match(pattern, text_lower)
            if match:
                if callable(days_or_func):
                    duration_days = days_or_func(match)
                else:
                    duration_days = days_or_func
                # Compute end_date from start_date + duration
                try:
                    start_dt = datetime.strptime(ti.start_date, "%Y-%m-%d").date()
                    end_dt = start_dt + timedelta(days=duration_days)
                    return {"end_date_hint": end_dt.strftime("%Y-%m-%d")}
                except (ValueError, TypeError):
                    pass  # Fall through to other parsers

    # First, check for year clarification patterns
    for pattern in YEAR_CLARIFY_PATTERNS:
        if pattern.search(text_stripped):
            # Get reference date from state if available
            metadata = state.metadata or {}
            today_iso = metadata.get("today_iso")
            if today_iso:
                try:
                    reference_date = datetime.strptime(today_iso, "%Y-%m-%d").date()
                except ValueError:
                    reference_date = datetime.now(UTC).date()
            else:
                reference_date = datetime.now(UTC).date()

            text_lower = text_stripped.lower()

            # Handle "this year" / "next year"
            if "this year" in text_lower:
                # Use the pending date range with current year
                pending_dates = metadata.get("pending_date_range", {})
                if pending_dates:
                    year = reference_date.year
                    start = pending_dates.get("start_date", "").replace(
                        pending_dates.get("start_date", "")[:4], str(year)
                    )
                    end = pending_dates.get("end_date", "").replace(
                        pending_dates.get("end_date", "")[:4], str(year)
                    )
                    if start and end:
                        return {"start_date_hint": start, "end_date_hint": end}
                return None

            if "next year" in text_lower:
                pending_dates = metadata.get("pending_date_range", {})
                if pending_dates:
                    year = reference_date.year + 1
                    start = pending_dates.get("start_date", "")
                    end = pending_dates.get("end_date", "")
                    if start and end:
                        start = f"{year}-{start[5:]}"
                        end = f"{year}-{end[5:]}"
                        return {"start_date_hint": start, "end_date_hint": end}
                return None

            # Handle "this December" / "next December"
            this_match = re.search(r"this\s+(\w+)", text_lower)
            if this_match:
                month_name = this_match.group(1)
                if month_name in _MONTH_NAMES:
                    year = reference_date.year
                    pending_dates = metadata.get("pending_date_range", {})
                    if pending_dates:
                        start = pending_dates.get("start_date", "")
                        end = pending_dates.get("end_date", "")
                        if start and end:
                            start = f"{year}-{start[5:]}"
                            end = f"{year}-{end[5:]}"
                            return {"start_date_hint": start, "end_date_hint": end}

            next_match = re.search(r"next\s+(\w+)", text_lower)
            if next_match:
                month_name = next_match.group(1)
                if month_name in _MONTH_NAMES or month_name == "year":
                    year = reference_date.year + 1
                    pending_dates = metadata.get("pending_date_range", {})
                    if pending_dates:
                        start = pending_dates.get("start_date", "")
                        end = pending_dates.get("end_date", "")
                        if start and end:
                            start = f"{year}-{start[5:]}"
                            end = f"{year}-{end[5:]}"
                            return {"start_date_hint": start, "end_date_hint": end}

            # Handle explicit year like "2026"
            year_match = re.search(r"(20\d{2})", text_stripped)
            if year_match:
                year = int(year_match.group(1))
                pending_dates = metadata.get("pending_date_range", {})
                if pending_dates:
                    start = pending_dates.get("start_date", "")
                    end = pending_dates.get("end_date", "")
                    if start and end:
                        start = f"{year}-{start[5:]}"
                        end = f"{year}-{end[5:]}"
                        return {"start_date_hint": start, "end_date_hint": end}

    # Try parsing as a date range first (e.g., "first week of January", "December 20-27")
    range_start, range_end = date_normalizer.parse_date_range(text_stripped)
    if range_start and range_end:
        return {"start_date_hint": range_start, "end_date_hint": range_end}

    # Handle month-to-month ranges (e.g., "September-November", "June to October")
    # Pattern: Month1 (to|through|-|--|---) Month2
    month_to_month_match = re.match(
        r"^(january|february|march|april|may|june|july|august|september|october|november|december"
        r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
        r"\s*(?:to|through|-|–|—)\s*"
        r"(january|february|march|april|may|june|july|august|september|october|november|december"
        r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)$",
        text_stripped,
        re.IGNORECASE,
    )
    if month_to_month_match:
        start_month_str = month_to_month_match.group(1).lower()
        end_month_str = month_to_month_match.group(2).lower()

        # Get reference date
        metadata = state.metadata or {}
        today_iso = metadata.get("today_iso")
        if today_iso:
            try:
                reference_date = datetime.strptime(today_iso, "%Y-%m-%d").date()
            except ValueError:
                reference_date = datetime.now(UTC).date()
        else:
            reference_date = datetime.now(UTC).date()

        # Parse month names to numbers
        try:
            start_month_num = datetime.strptime(start_month_str[:3], "%b").month
            end_month_num = datetime.strptime(end_month_str[:3], "%b").month
        except ValueError:
            pass  # Fall through to other parsers
        else:
            year = reference_date.year

            # If start month is in the past this year, use next year
            if start_month_num < reference_date.month:
                year += 1
            elif start_month_num == reference_date.month and reference_date.day > 15:
                # Already mid-month, assume next year
                year += 1

            # Calculate end year - handle cross-year ranges (e.g., "November-February")
            end_year = year
            if end_month_num < start_month_num:
                # Cross-year range (e.g., November to February)
                end_year = year + 1

            # Build date range: 1st of start month to last day of end month
            start_date = f"{year:04d}-{start_month_num:02d}-01"

            # Get last day of end month
            if end_month_num == 12:
                next_month_first = datetime(end_year + 1, 1, 1)
            else:
                next_month_first = datetime(end_year, end_month_num + 1, 1)
            last_day = (next_month_first - timedelta(days=1)).day
            end_date = f"{end_year:04d}-{end_month_num:02d}-{last_day:02d}"

            return {"start_date_hint": start_date, "end_date_hint": end_date}

    # Standard single date parsing
    iso_date = date_normalizer.normalize(text_stripped)
    if iso_date:
        # If start_date is already set but end_date is not, treat this as end_date
        ti = state.trip_inputs
        if ti.start_date and not ti.end_date:
            return {"end_date_hint": iso_date}
        return {"start_date_hint": iso_date}

    # Handle bare month names (e.g., "December", "January")
    # This is a valid answer - user is saying they want to travel in that month
    text_lower = text_stripped.lower()
    if text_lower in _MONTH_NAMES:
        # Get reference date from state if available
        metadata = state.metadata or {}
        today_iso = metadata.get("today_iso")
        if today_iso:
            try:
                reference_date = datetime.strptime(today_iso, "%Y-%m-%d").date()
            except ValueError:
                reference_date = datetime.now(UTC).date()
        else:
            reference_date = datetime.now(UTC).date()

        # Get month number by parsing the month name
        try:
            month_dt = datetime.strptime(text_lower[:3], "%b")
            month_num = month_dt.month
        except ValueError:
            return None

        # Determine year: current year if month is upcoming, next year if past
        year = reference_date.year
        if month_num < reference_date.month or (
            month_num == reference_date.month and reference_date.day > 15
        ):
            year += 1

        # Return a date range covering the whole month
        # First day of the month
        start_date = f"{year:04d}-{month_num:02d}-01"
        # Last day of the month
        if month_num == 12:
            next_month_first = datetime(year + 1, 1, 1)
        else:
            next_month_first = datetime(year, month_num + 1, 1)
        last_day = (next_month_first - timedelta(days=1)).day
        end_date = f"{year:04d}-{month_num:02d}-{last_day:02d}"

        return {"start_date_hint": start_date, "end_date_hint": end_date}

    return None


def _parse_travelers_answer(text: str, state: "GraphState") -> Optional[Dict[str, Any]]:
    """Parse a travelers answer. Returns parsed dict or None."""
    # Check for adults + kids pattern first (e.g., "2 adults and 2 kids")
    kids_match = TRAVELERS_WITH_KIDS_PATTERN.match(text)
    if kids_match:
        adults = int(kids_match.group(1))
        children = int(kids_match.group(2))
        return {"adults_delta": adults, "children_delta": children}

    travelers_match = TRAVELERS_PATTERN.match(text)
    if travelers_match:
        # Extract number of adults
        if "just" in text.lower() or "solo" in text.lower() or text.lower() in ("me", "myself"):
            adults = 1
        elif "couple" in text.lower():
            adults = 2
        elif travelers_match.group(1):  # "2 adults", "3 people"
            adults = int(travelers_match.group(1))
        elif travelers_match.group(3):  # "family of 4"
            adults = int(travelers_match.group(3))
        elif travelers_match.group(4):  # "4 of us"
            adults = int(travelers_match.group(4))
        else:
            adults = 1  # Default
        return {"adults_delta": adults}
    return None


def _parse_budget_answer(text: str, state: "GraphState") -> Optional[Dict[str, Any]]:
    """
    Parse a budget answer. Returns parsed dict or None.

    Handles:
    - Numeric amounts: "$2000", "2k", "5 thousand", "€3000", "£1500"
    - Qualitative prefixes: "under $2000", "around $1500", "about 3k", "max $5000"
    - No-budget phrases: "no budget", "flexible", "budget-friendly", "no limit"
    - Quality tiers: "luxury", "mid-range", "cheap", "budget-friendly"
    """
    text_lower = text.strip().lower()

    # Check for "no budget" / "flexible" phrases first
    # These are valid answers that mean "user has responded, skip budget requirement"
    for phrase in NO_BUDGET_PHRASES:
        if phrase in text_lower or text_lower == phrase:
            # Map quality tiers to approximate budget hints for better recommendations
            budget_hint = None
            if any(
                w in text_lower for w in ("luxury", "high-end", "high end", "premium", "splurge")
            ):
                budget_hint = "luxury"
            elif any(
                w in text_lower for w in ("cheap", "cheapest", "budget-friendly", "budget friendly")
            ):
                budget_hint = "budget"
            elif any(w in text_lower for w in ("mid-range", "midrange", "moderate", "average")):
                budget_hint = "moderate"

            result: Dict[str, Any] = {
                "budget_answered": True,  # Signal that user responded
                "lqa_reason": "deterministic:budget_flexible",
            }
            if budget_hint:
                result["budget_tier"] = budget_hint
            return result

    # Try the main budget pattern
    budget_match = BUDGET_PATTERN.match(text)
    if budget_match:
        amount_str = budget_match.group(1)
        # Handle "k" suffix (e.g., "2k" -> 2000)
        if amount_str.lower().endswith("k"):
            amount = float(amount_str[:-1]) * 1000
        # Handle "thousand" word (e.g., "5 thousand" -> 5000)
        elif "thousand" in amount_str.lower():
            amount = float(amount_str.lower().replace("thousand", "").strip()) * 1000
        else:
            # Remove commas and convert
            amount = float(amount_str.replace(",", ""))
        return {"budget_delta": amount, "lqa_reason": "deterministic:budget_amount"}

    # Fallback: Try to extract any number with currency symbol using inline pattern
    # This catches edge cases like "I have $2000 to spend" that don't match the strict pattern
    inline_match = INLINE_BUDGET_PATTERN.search(text)
    if inline_match:
        # Find the first non-None group (different capture groups for different patterns)
        for group_idx in range(1, 8):
            try:
                amount_str = inline_match.group(group_idx)
                if amount_str:
                    # Handle "k" suffix
                    if amount_str.lower().endswith("k"):
                        amount = float(amount_str[:-1]) * 1000
                    else:
                        amount = float(amount_str.replace(",", ""))
                    return {"budget_delta": amount, "lqa_reason": "deterministic:budget_inline"}
            except (IndexError, ValueError, TypeError):
                continue

    return None


def _parse_duration_answer(text: str, state: "GraphState") -> Optional[Dict[str, Any]]:
    """Parse a duration answer. Returns parsed dict or None."""
    duration_match = DURATION_PATTERN.match(text)
    if duration_match:
        # Parse the number (could be word or digit)
        num_str = duration_match.group(1).lower()
        if num_str in WORD_TO_NUMBER:
            num = WORD_TO_NUMBER[num_str]
        else:
            num = int(num_str)

        unit = duration_match.group(2).lower()
        # Convert to days
        if "week" in unit:
            days = num * 7
        else:
            days = num  # days or nights treated the same

        return {"duration_days": days}
    return None


# =============================================================================
# P4.1: NEGATION ALTERNATIVE EXTRACTION
# =============================================================================


def _extract_negation_alternative(
    text: str,
    state: "GraphState",
) -> Optional[Dict[str, Any]]:
    """
    Extract alternative value from negation patterns (P4.1 Optimization).

    Handles patterns like:
    - "not Paris, maybe Barcelona" -> "Barcelona"
    - "instead of Rome, try Venice" -> "Venice"
    - "actually Tokyo" -> "Tokyo"
    - "change to London" -> "London"
    - "Barcelona instead" -> "Barcelona"

    Returns:
        Dict with:
        - alternative: str - The extracted alternative text
        - negation_type: str - Type of negation pattern matched
        Or None if no alternative found
    """
    text_stripped = text.strip()

    # First check for simple negation without alternative
    if SIMPLE_NEGATION_PATTERN.match(text_stripped):
        # User is rejecting without providing alternative
        return {
            "alternative": None,
            "negation_type": "simple_rejection",
        }

    # Check for negation with alternative
    match = NEGATION_ALTERNATIVE_PATTERN.search(text_stripped)
    if match:
        # Find the first non-None capture group (alternative text)
        alternative = None
        for group in match.groups():
            if group:
                alternative = group.strip()
                break

        if alternative:
            # Clean up the alternative text
            # Remove trailing punctuation
            alternative = alternative.rstrip(".,!?")

            # Determine negation type based on pattern matched
            # Note: Order matters - check more specific patterns first
            text_lower = text_stripped.lower()
            if "instead of" in text_lower:
                negation_type = "instead_of"
            elif text_lower.endswith("instead"):
                negation_type = "x_instead"
            elif "maybe" in text_lower or "try" in text_lower:
                negation_type = "not_maybe"
            elif "but" in text_lower:
                negation_type = "not_but"
            elif "change" in text_lower or "switch" in text_lower:
                negation_type = "change_to"
            elif "actually" in text_lower:
                negation_type = "actually"
            else:
                negation_type = "generic"

            return {
                "alternative": alternative,
                "negation_type": negation_type,
            }

    return None


# =============================================================================
# P2.3: COMPOUND TRAVELERS+DATE PARSING
# =============================================================================


def _parse_compound_travelers_date(
    text: str,
    state: "GraphState",
    date_normalizer: Optional[DateNormalizerProtocol] = None,
) -> Optional[Dict[str, Any]]:
    """
    Parse compound travelers+date expressions (P2.3 Optimization).

    Handles patterns like:
    - "2 adults for next month" -> adults=2 + date
    - "family of 4 in December" -> adults=2, children=2 + date
    - "couple for next week" -> adults=2 + date
    - "just me in January" -> adults=1 + date
    - "next month for 3 people" -> adults=3 + date

    Returns:
        Dict with combined fields (adults_delta, children_delta, start_date_hint, etc.)
        or None if no compound pattern matched
    """
    text_stripped = text.strip()
    text_lower = text_stripped.lower()

    # Quick bail: no compound keywords
    if not any(kw in text_lower for kw in COMPOUND_KEYWORDS):
        return None

    # Get date_normalizer if not provided
    if date_normalizer is None:
        from app.plan_graph import _date_normalizer

        date_normalizer = date_normalizer or _date_normalizer

    result: Dict[str, Any] = {}

    # Try travelers-first pattern: "2 adults for next month"
    match = COMPOUND_TRAVELERS_DATE_PATTERN.match(text_stripped)
    if match:
        travelers_text = match.group("travelers")
        date_text = match.group("date")

        # Parse travelers
        travelers_parsed = _parse_travelers_answer(travelers_text, state)
        if travelers_parsed:
            result.update(travelers_parsed)

        # Parse date
        date_parsed = _parse_date_answer(date_text, state, date_normalizer)
        if date_parsed:
            result.update(date_parsed)

        if result:
            result["lqa_reason"] = "deterministic:compound_travelers_date"
            return result

    # Try date-first pattern: "next month for 2 adults"
    match = COMPOUND_DATE_TRAVELERS_PATTERN.match(text_stripped)
    if match:
        date_text = match.group("date")
        travelers_text = match.group("travelers")

        # Parse date
        date_parsed = _parse_date_answer(date_text, state, date_normalizer)
        if date_parsed:
            result.update(date_parsed)

        # Parse travelers
        travelers_parsed = _parse_travelers_answer(travelers_text, state)
        if travelers_parsed:
            result.update(travelers_parsed)

        if result:
            result["lqa_reason"] = "deterministic:compound_date_travelers"
            return result

    return None


# =============================================================================
# PARSER REGISTRY
# =============================================================================

# Type alias for parser function signature
LQAParserFunc = Callable[[str, "GraphState"], Optional[Dict[str, Any]]]

# Mapping from question_target to parser function
LQA_FIELD_PARSERS: Dict[str, LQAParserFunc] = {
    "destinations": _parse_destination_answer,
    "origin": _parse_origin_answer,
    "dates": lambda text, state: _parse_date_answer(text, state),
    "start_date": lambda text, state: _parse_date_answer(text, state),
    "end_date": lambda text, state: _parse_date_answer(text, state),
    "travelers": _parse_travelers_answer,
    "budget": _parse_budget_answer,
    "duration": _parse_duration_answer,
}

# Backward-compatible alias
_LQA_FIELD_PARSERS = LQA_FIELD_PARSERS


# =============================================================================
# EXPORTED NAMES
# =============================================================================

__all__ = [
    # Constants
    "_ARTICLE_PREFIX",
    "_MONTH_NAMES",
    "_RELATIVE_DATE_WORDS",
    "_ACTIVITY_MODIFIER_WORDS",
    "_STRATEGY_KEYWORDS",
    # Detection helpers
    "_is_date_like_text",
    "_is_place_like_text",
    "_is_activity_preference_text",
    # Parsers
    "_parse_destination_answer",
    "_parse_origin_answer",
    "_parse_date_answer",
    "_parse_travelers_answer",
    "_parse_budget_answer",
    "_parse_duration_answer",
    # P4.1: Negation extraction
    "_extract_negation_alternative",
    # P2.3: Compound parsing
    "_parse_compound_travelers_date",
    # Registry
    "LQA_FIELD_PARSERS",
    "_LQA_FIELD_PARSERS",
    "LQAParserFunc",
]
