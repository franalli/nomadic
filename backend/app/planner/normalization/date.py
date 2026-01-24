"""
Date Normalization - Tier 3 Full Extraction.

This module provides centralized date normalization logic including:
- Relative date parsing ("next week", "tomorrow")
- ISO date normalization
- Date range parsing
- Cross-year correction
- Date provenance tracking

Usage:
    from app.planner.normalization.date import (
        DateNormalizer,
        DateProvenance,
        normalize_str,
    )

    normalizer = DateNormalizer()
    iso_date = normalizer.normalize("next week")
    start, end = normalizer.parse_date_range("December 20-27")
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from app.pattern_matching import (
    ANSI_ESCAPE_PATTERN,
    DATE_RANGE_EUROPEAN_PATTERNS,
    DATE_RANGE_FLEXIBLE_PATTERNS,
    DATE_RANGE_WITH_YEAR_PATTERNS,
    EXPLICIT_YEAR_PATTERN,
    ISO_DATE_PATTERN,
    MONTH_DAY_EXTRACTION_PATTERNS,
    MONTH_DAY_PATTERN,
    ORDINAL_SUFFIX_PATTERN,
    PARTIAL_DATE_PATTERN,
    TODAY_WORDS,
    WEEK_OF_MONTH_PATTERN,
    WEEK_ORDINALS,
)


# =============================================================================
# STRING NORMALIZATION HELPER
# =============================================================================
def normalize_str(value: Any) -> Optional[str]:
    """Convert any value to a trimmed string, returning None for empty values.

    Also strips ANSI escape codes that may be present from terminal formatting.
    """
    if value is None:
        return None
    value_str = str(value).strip()
    if not value_str or value_str.lower() == "null":
        return None
    # Strip ANSI escape codes
    value_str = ANSI_ESCAPE_PATTERN.sub("", value_str)
    return value_str


# Backward-compatible alias
_normalize_str = normalize_str


# =============================================================================
# DATE PROVENANCE (Tracking source and explicit year for date values)
# =============================================================================
@dataclass
class DateProvenance:
    """
    Provenance information for a parsed date value.

    Used to track whether a year was explicit (from user input) or inferred,
    enabling the "explicit year wins" invariant at merge time.

    Attributes:
        value: The ISO date string (YYYY-MM-DD)
        source_turn: Turn number when this date was set (optional)
        explicit_year: True if the year was explicitly provided by user
        parsed_from: How the date was derived ("user_text", "normalized", "inferred")
    """

    value: str
    source_turn: Optional[int] = None
    explicit_year: bool = False
    parsed_from: str = "normalized"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "source_turn": self.source_turn,
            "explicit_year": self.explicit_year,
            "parsed_from": self.parsed_from,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Optional["DateProvenance"]:
        if not data:
            return None
        return cls(
            value=data.get("value", ""),
            source_turn=data.get("source_turn"),
            explicit_year=data.get("explicit_year", False),
            parsed_from=data.get("parsed_from", "normalized"),
        )


# =============================================================================
# DATE NORMALIZER (Consolidated date handling)
# =============================================================================
class DateNormalizer:
    """
    Centralized date normalization logic.

    Consolidates all date parsing, relative date conversion, and validation
    into a single class to eliminate duplication across nodes.

    Usage:
        normalizer = DateNormalizer()
        iso_date = normalizer.normalize("next week")
        iso_date, was_partial = normalizer.normalize_with_info("December 2025")
        end_date = normalizer.compute_end_from_duration("2025-01-01", 7)
        start, end = normalizer.parse_date_range("December 20-27")
    """

    # Supported date formats (ordered by specificity - 4-digit year first)
    _DATE_FORMATS = (
        "%Y-%m-%d",  # 2025-12-28 (ISO)
        "%d-%m-%Y",  # 28-12-2025
        "%d/%m/%Y",  # 28/12/2025
        "%m/%d/%Y",  # 12/28/2025 (US format)
        "%m-%d-%Y",  # 12-28-2025 (US dash format)
        "%B %d, %Y",  # December 28, 2025
        "%b %d, %Y",  # Dec 28, 2025
        "%d %B %Y",  # 28 December 2025
        "%d %b %Y",  # 28 Dec 2025
        "%B %d %Y",  # December 28 2025 (no comma)
        "%b %d %Y",  # Dec 28 2025 (no comma)
        "%d %B, %Y",  # 28 December, 2025
        "%d %b, %Y",  # 28 Dec, 2025
        # 2-digit year formats (less common but still used)
        "%d-%m-%y",  # 28-12-25
        "%d/%m/%y",  # 28/12/25
        "%m/%d/%y",  # 12/28/25 (US format)
        "%m-%d-%y",  # 12-28-25 (US dash format)
    )

    def __init__(self, reference_date: Optional[date] = None):
        """
        Initialize with optional reference date for relative calculations.

        Args:
            reference_date: The "today" date for relative calculations.
                           Defaults to UTC today.
        """
        self._reference = reference_date or datetime.now(UTC).date()

    @property
    def today(self) -> date:
        """Get the reference date used for relative calculations."""
        return self._reference

    def relative_to_iso(self, text: Optional[str]) -> Optional[str]:
        """
        Convert relative date expressions to ISO format.

        Handles: today, tomorrow, next week, next month, weekend, this weekend
        """
        if not text:
            return None

        lowered = text.lower().strip()
        today = self._reference

        if lowered in TODAY_WORDS:
            return today.strftime("%Y-%m-%d")

        if lowered in ("tomorrow", "tmrw"):
            return (today + timedelta(days=1)).strftime("%Y-%m-%d")

        if "next week" in lowered:
            return (today + timedelta(days=7)).strftime("%Y-%m-%d")

        if "next month" in lowered:
            return (today + timedelta(days=30)).strftime("%Y-%m-%d")

        if "weekend" in lowered:
            days_until_saturday = (5 - today.weekday()) % 7
            if "next" in lowered and days_until_saturday <= 0:
                days_until_saturday += 7
            return (today + timedelta(days=days_until_saturday)).strftime("%Y-%m-%d")

        # Handle "next monday", "next tuesday", etc.
        weekday_names = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6,
        }
        next_weekday_match = re.match(
            r"^(?:next|this)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)$",
            lowered,
        )
        if next_weekday_match:
            target_day = weekday_names[next_weekday_match.group(1)]
            days_ahead = (target_day - today.weekday()) % 7
            # "next X" means at least 1 day ahead; if today is that day, go to next week
            if days_ahead == 0 and "next" in lowered:
                days_ahead = 7
            return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

        return None

    def normalize_with_info(self, value: Any) -> Tuple[Optional[str], bool]:
        """
        Normalize various date formats to ISO format (YYYY-MM-DD).

        Returns:
            Tuple of (iso_date, was_partial) where was_partial indicates
            if the date was a partial date like "December 2025" that defaulted
            to the 1st of the month.
        """
        text = normalize_str(value)
        if not text:
            return None, False

        # Try relative dates first
        relative = self.relative_to_iso(text)
        if relative:
            return relative, False

        # Strip ordinal suffixes before parsing (28th -> 28)
        text_cleaned = ORDINAL_SUFFIX_PATTERN.sub(r"\1", text)

        # Try various date formats
        for fmt in self._DATE_FORMATS:
            try:
                parsed = datetime.strptime(text_cleaned, fmt)
                return parsed.strftime("%Y-%m-%d"), False
            except ValueError:
                continue

        # Check for partial dates (month + year only)
        partial_match = PARTIAL_DATE_PATTERN.match(text_cleaned)
        if partial_match:
            month_str = partial_match.group(1)
            year_str = partial_match.group(2)
            for month_fmt in ("%B %d, %Y", "%b %d, %Y"):
                try:
                    parsed = datetime.strptime(f"{month_str} 1, {year_str}", month_fmt)
                    return parsed.strftime("%Y-%m-%d"), True
                except ValueError:
                    continue

        # Check for month + day without year (e.g., "December 15", "Dec 15")
        month_day_match = MONTH_DAY_PATTERN.match(text_cleaned)
        if month_day_match:
            month_str = month_day_match.group(1)
            day_str = month_day_match.group(2)
            # Infer year: use current year if date is future, next year if past
            for month_fmt in ("%B %d, %Y", "%b %d, %Y"):
                try:
                    # Try with current year first
                    current_year = self._reference.year
                    parsed = datetime.strptime(f"{month_str} {day_str}, {current_year}", month_fmt)
                    # If date is in the past, use next year
                    if parsed.date() < self._reference:
                        parsed = datetime.strptime(
                            f"{month_str} {day_str}, {current_year + 1}", month_fmt
                        )
                    return parsed.strftime("%Y-%m-%d"), False
                except ValueError:
                    continue

        # Check if already ISO format
        if ISO_DATE_PATTERN.match(text_cleaned):
            return text_cleaned, False

        return None, False

    def normalize(self, value: Any) -> Optional[str]:
        """Normalize various date formats to ISO format (YYYY-MM-DD)."""
        result, _ = self.normalize_with_info(value)
        return result

    def has_explicit_year(self, text: str) -> bool:
        """
        Check if the input text contains an explicit 4-digit year.

        This is used to determine whether year should be preserved during merges.
        """
        if not text:
            return False
        return bool(EXPLICIT_YEAR_PATTERN.search(text))

    def normalize_with_provenance(
        self,
        value: Any,
        source_turn: Optional[int] = None,
    ) -> Optional[DateProvenance]:
        """
        Normalize date and return full provenance information.

        This is the preferred method for date normalization when tracking
        explicit year is important for merge invariants.

        Args:
            value: Raw date string to normalize
            source_turn: Turn number where this date was provided

        Returns:
            DateProvenance with value, explicit_year flag, and source info,
            or None if parsing fails
        """
        text = normalize_str(value)
        if not text:
            return None

        iso_date, was_partial = self.normalize_with_info(value)
        if not iso_date:
            return None

        # Check if original input had an explicit year
        explicit_year = self.has_explicit_year(text)

        # Determine parsed_from based on how the date was derived
        if was_partial:
            parsed_from = "partial_month"
        elif self.relative_to_iso(text):
            parsed_from = "relative"
        elif ISO_DATE_PATTERN.match(text.strip()):
            parsed_from = "iso_passthrough"
        else:
            parsed_from = "user_text"

        return DateProvenance(
            value=iso_date,
            source_turn=source_turn,
            explicit_year=explicit_year,
            parsed_from=parsed_from,
        )

    def parse_iso(self, text: Optional[str]) -> Optional[datetime]:
        """Parse an ISO date string to a datetime object."""
        if not text:
            return None
        try:
            return datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            return None

    def find_date_in_text(self, text: str, hint_month: Optional[str] = None) -> Optional[str]:
        """
        Try to find a full date (with day) in freeform user text.

        This is used as a fallback when the LLM extractor returns only month+year
        but the user's original text had a specific day.

        Args:
            text: The user's original input text
            hint_month: Optional month hint from LLM (e.g., "january") to help find the right date

        Returns:
            ISO date string if found, None otherwise
        """
        if not text:
            return None

        text_lower = text.lower()

        for pattern in MONTH_DAY_EXTRACTION_PATTERNS:
            matches = list(pattern.finditer(text_lower))
            for match in matches:
                groups = match.groups()

                # Determine month, day, and year from match
                if groups[0].isdigit():
                    # Pattern 2: day, month, year
                    day_str = groups[0]
                    month_str = groups[1]
                    year_str = groups[2] if len(groups) > 2 else None
                else:
                    # Pattern 1: month, day, year
                    month_str = groups[0]
                    day_str = groups[1]
                    year_str = groups[2] if len(groups) > 2 else None

                # If we have a hint_month, only match dates with that month
                if hint_month:
                    hint_month_lower = hint_month.lower()[:3]
                    if not month_str.lower().startswith(hint_month_lower):
                        continue

                # Parse month
                try:
                    month_dt = datetime.strptime(month_str[:3], "%b")
                    month_num = month_dt.month
                except ValueError:
                    continue

                # Parse day
                try:
                    day_num = int(day_str)
                    if day_num < 1 or day_num > 31:
                        continue
                except ValueError:
                    continue

                # Determine year
                if year_str:
                    year = int(year_str)
                else:
                    # Use current year, or next year if month is past
                    today = self._reference
                    year = today.year
                    if month_num < today.month or (
                        month_num == today.month and day_num < today.day
                    ):
                        year += 1

                # Build and validate the date
                try:
                    iso_date = f"{year:04d}-{month_num:02d}-{day_num:02d}"
                    datetime.strptime(iso_date, "%Y-%m-%d")  # Validate
                    return iso_date
                except ValueError:
                    continue

        return None

    def parse_date_range(self, value: Any) -> Tuple[Optional[str], Optional[str]]:
        """
        Parse a date range expression into start and end dates.

        Handles formats like:
        - "December 20-27" → ("2025-12-20", "2025-12-27")
        - "Dec 20-27" → ("2025-12-20", "2025-12-27")
        - "December 20-27, 2025" → ("2025-12-20", "2025-12-27")
        - "20-27 December" → ("2025-12-20", "2025-12-27")
        - "6-15th feb" → ("2025-02-06", "2025-02-15") (mixed ordinals)
        - "6-15.02" → ("2025-02-06", "2025-02-15") (European decimal)
        - "dates are 6-15 feb, budget..." → extracts from context

        If no year is specified, uses current year (or next year if month is past).

        Returns:
            Tuple of (start_date_iso, end_date_iso), or (None, None) if not a range.
        """
        text = normalize_str(value)
        if not text:
            return None, None

        text_clean = text.strip()

        # Step 1: Pre-normalize ALL ordinal suffixes (handles "6-15th feb" -> "6-15 feb")
        text_normalized = ORDINAL_SUFFIX_PATTERN.sub(r"\1", text_clean)

        # Step 2: Try European decimal patterns first (6-15.02, 6.02-15.02)
        european_result = self._try_european_date_patterns(text_normalized)
        if european_result[0] is not None:
            return european_result

        # Step 3: Try flexible patterns that search within text (for dates in sentences)
        flexible_result = self._try_flexible_date_patterns(text_normalized)
        if flexible_result[0] is not None:
            return flexible_result

        # Step 4: Try anchored patterns (original behavior)
        for pattern in DATE_RANGE_WITH_YEAR_PATTERNS:
            match = pattern.match(text_clean)
            if match:
                groups = match.groups()

                # Pattern 1: "December 20-27" → (month, start_day, end_day, year?)
                # Pattern 2: "20-27 December" → (start_day, end_day, month, year?)
                if groups[0].isdigit():
                    # Pattern 2: start_day, end_day, month, year
                    start_day = int(groups[0])
                    end_day = int(groups[1])
                    month_str = groups[2]
                    year_str = groups[3] if len(groups) > 3 else None
                else:
                    # Pattern 1: month, start_day, end_day, year
                    month_str = groups[0]
                    start_day = int(groups[1])
                    end_day = int(groups[2])
                    year_str = groups[3] if len(groups) > 3 else None

                # Parse month name to number
                try:
                    month_dt = datetime.strptime(month_str[:3], "%b")
                    month_num = month_dt.month
                except ValueError:
                    continue

                # Determine year
                if year_str:
                    year = int(year_str)
                else:
                    # Use current year, or next year if month is in the past
                    today = self._reference
                    year = today.year
                    if month_num < today.month or (
                        month_num == today.month and end_day < today.day
                    ):
                        year += 1

                # Build ISO dates
                try:
                    start_iso = f"{year:04d}-{month_num:02d}-{start_day:02d}"
                    end_iso = f"{year:04d}-{month_num:02d}-{end_day:02d}"

                    # Validate dates are real
                    datetime.strptime(start_iso, "%Y-%m-%d")
                    datetime.strptime(end_iso, "%Y-%m-%d")

                    return start_iso, end_iso
                except ValueError:
                    # Invalid day for month
                    continue

        # Check for "first/second/third/fourth/last week of [month]" pattern
        week_match = WEEK_OF_MONTH_PATTERN.match(text_clean)
        if week_match:
            ordinal_str = week_match.group(1).lower()
            month_str = week_match.group(2)
            year_str = week_match.group(3) if len(week_match.groups()) > 2 else None

            # Get week number from ordinal
            week_num = WEEK_ORDINALS.get(ordinal_str)
            if week_num is None:
                return None, None

            # Parse month name to number
            try:
                month_dt = datetime.strptime(month_str[:3], "%b")
                month_num = month_dt.month
            except ValueError:
                return None, None

            # Determine year
            if year_str:
                year = int(year_str)
            else:
                # Use current year, or next year if month is in the past
                today = self._reference
                year = today.year
                if month_num < today.month:
                    year += 1

            # Calculate last day of month
            if month_num == 12:
                last_of_month = date(year + 1, 1, 1) - timedelta(days=1)
            else:
                last_of_month = date(year, month_num + 1, 1) - timedelta(days=1)

            if week_num == -1:  # "last week"
                # Last 7 days of the month
                end_day = last_of_month
                start_day_date = end_day - timedelta(days=6)
            else:
                # Calculate start of nth week (week 1 = days 1-7, week 2 = days 8-14, etc.)
                start_day_num = 1 + (week_num - 1) * 7
                end_day_num = min(start_day_num + 6, last_of_month.day)

                try:
                    start_day_date = date(year, month_num, start_day_num)
                    end_day = date(year, month_num, end_day_num)
                except ValueError:
                    # Invalid date (e.g., week 5 of a short month)
                    return None, None

            start_iso = start_day_date.strftime("%Y-%m-%d")
            end_iso = end_day.strftime("%Y-%m-%d")
            return start_iso, end_iso

        return None, None

    def _try_european_date_patterns(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Try to parse European date formats like 6-15.02 or 6.02-15.02.

        Handles:
        - "6.02-15.02" → Feb 6 to Feb 15 (DD.MM-DD.MM) [pattern 0]
        - "6-15.02" → Feb 6-15 (DD-DD.MM) [pattern 1]
        - "15.02" → Feb 15 (single date, returns same for start and end) [pattern 2]

        Returns:
            Tuple of (start_date_iso, end_date_iso), or (None, None) if no match.
        """
        for i, pattern in enumerate(DATE_RANGE_EUROPEAN_PATTERNS):
            match = pattern.search(text)
            if not match:
                continue

            groups = match.groups()

            try:
                if i == 0:  # DD.MM-DD.MM format: "6.02-15.02" (most specific)
                    start_day = int(groups[0])
                    start_month = int(groups[1])
                    end_day = int(groups[2])
                    end_month = int(groups[3])
                    year_str = groups[4] if len(groups) > 4 and groups[4] else None

                    # For cross-month ranges, build two separate dates
                    if start_month != end_month:
                        year = self._infer_year(start_month, start_day, year_str)
                        start_iso = f"{year:04d}-{start_month:02d}-{start_day:02d}"
                        end_iso = f"{year:04d}-{end_month:02d}-{end_day:02d}"
                        datetime.strptime(start_iso, "%Y-%m-%d")
                        datetime.strptime(end_iso, "%Y-%m-%d")
                        return start_iso, end_iso

                    month_num = start_month
                elif i == 1:  # DD-DD.MM format: "6-15.02"
                    start_day = int(groups[0])
                    end_day = int(groups[1])
                    month_num = int(groups[2])
                    year_str = groups[3] if len(groups) > 3 and groups[3] else None
                else:  # DD.MM format: "15.02" (single date)
                    start_day = int(groups[0])
                    end_day = start_day
                    month_num = int(groups[1])
                    year_str = groups[2] if len(groups) > 2 and groups[2] else None

                # Validate month
                if month_num < 1 or month_num > 12:
                    continue

                # Determine year
                year = self._infer_year(month_num, end_day, year_str)

                # Build ISO dates
                start_iso = f"{year:04d}-{month_num:02d}-{start_day:02d}"
                end_iso = f"{year:04d}-{month_num:02d}-{end_day:02d}"

                # Validate dates are real
                datetime.strptime(start_iso, "%Y-%m-%d")
                datetime.strptime(end_iso, "%Y-%m-%d")

                return start_iso, end_iso

            except (ValueError, TypeError):
                continue

        return None, None

    def _try_flexible_date_patterns(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Try to find date ranges within surrounding text using search() patterns.

        Handles dates embedded in sentences like:
        - "dates are 6-15 feb, budget around 2000" → Feb 6-15
        - "going from dec 20-27" → Dec 20-27

        Returns:
            Tuple of (start_date_iso, end_date_iso), or (None, None) if no match.
        """
        for pattern in DATE_RANGE_FLEXIBLE_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue

            groups = match.groups()

            try:
                # Determine if pattern matched month first or day first
                if groups[0].isdigit():
                    # Pattern 2: start_day, end_day, month, year
                    start_day = int(groups[0])
                    end_day = int(groups[1])
                    month_str = groups[2]
                    year_str = groups[3] if len(groups) > 3 and groups[3] else None
                else:
                    # Pattern 1: month, start_day, end_day, year
                    month_str = groups[0]
                    start_day = int(groups[1])
                    end_day = int(groups[2])
                    year_str = groups[3] if len(groups) > 3 and groups[3] else None

                # Parse month name to number
                month_dt = datetime.strptime(month_str[:3], "%b")
                month_num = month_dt.month

                # Determine year
                year = self._infer_year(month_num, end_day, year_str)

                # Build ISO dates
                start_iso = f"{year:04d}-{month_num:02d}-{start_day:02d}"
                end_iso = f"{year:04d}-{month_num:02d}-{end_day:02d}"

                # Validate dates are real
                datetime.strptime(start_iso, "%Y-%m-%d")
                datetime.strptime(end_iso, "%Y-%m-%d")

                return start_iso, end_iso

            except (ValueError, TypeError):
                continue

        return None, None

    def _infer_year(self, month_num: int, day: int, year_str: Optional[str]) -> int:
        """
        Infer year for a date, using current year or next year if past.

        Args:
            month_num: Month number (1-12)
            day: Day of month
            year_str: Optional explicit year string

        Returns:
            4-digit year
        """
        if year_str:
            year = int(year_str)
            # Handle 2-digit years
            if year < 100:
                year += 2000
            return year

        # Use current year, or next year if date is in the past
        today = self._reference
        year = today.year
        if month_num < today.month or (month_num == today.month and day < today.day):
            year += 1
        return year

    def parse_date_range_with_ambiguity(
        self, text: str
    ) -> Tuple[Optional[str], Optional[str], bool]:
        """
        Deterministic month-day range parser with straddle-today detection.

        This is the preferred method for parsing date ranges as it detects
        ambiguous year situations instead of silently guessing.

        Args:
            text: Input text like "December 20-27", "Dec 20-27", "20-27 December"

        Returns:
            Tuple of (start_iso, end_iso, is_ambiguous) where:
            - start_iso/end_iso: ISO date strings or None if parse failed
            - is_ambiguous: True if year is ambiguous (straddles today)
        """
        text = text.strip()
        if not text:
            return None, None, False

        for pattern in DATE_RANGE_WITH_YEAR_PATTERNS:
            match = pattern.match(text)
            if not match:
                continue

            groups = match.groups()

            # Determine if pattern matched month first or day first
            if groups[0].isdigit():
                # Pattern 2: start_day, end_day, month, year
                start_day = int(groups[0])
                end_day = int(groups[1])
                month_str = groups[2]
                year_str = groups[3] if len(groups) > 3 else None
            else:
                # Pattern 1: month, start_day, end_day, year
                month_str = groups[0]
                start_day = int(groups[1])
                end_day = int(groups[2])
                year_str = groups[3] if len(groups) > 3 else None

            # Parse month name to number
            try:
                month_dt = datetime.strptime(month_str[:3], "%b")
                month_num = month_dt.month
            except ValueError:
                continue

            # If explicit year provided, no ambiguity
            if year_str:
                year = int(year_str)
                try:
                    start_iso = f"{year:04d}-{month_num:02d}-{start_day:02d}"
                    end_iso = f"{year:04d}-{month_num:02d}-{end_day:02d}"
                    datetime.strptime(start_iso, "%Y-%m-%d")
                    datetime.strptime(end_iso, "%Y-%m-%d")
                    return start_iso, end_iso, False
                except ValueError:
                    continue

            # Check for straddle-today ambiguity
            today = self._reference
            year = today.year

            try:
                # Build candidate dates in current year
                start_candidate = date(year, month_num, start_day)
                end_candidate = date(year, month_num, end_day)

                # Straddle-today detection:
                # 1. Today falls inside the range, OR
                # 2. Start is in past but end is in future (range crosses today)
                is_ambiguous = False

                if start_candidate <= today <= end_candidate:
                    # Today is inside the range
                    is_ambiguous = True
                elif start_candidate < today and end_candidate >= today:
                    # Range crosses today
                    is_ambiguous = True
                elif start_candidate < today and end_candidate < today:
                    # Entire range is in the past - assume next year, not ambiguous
                    year += 1

                start_iso = f"{year:04d}-{month_num:02d}-{start_day:02d}"
                end_iso = f"{year:04d}-{month_num:02d}-{end_day:02d}"

                return start_iso, end_iso, is_ambiguous

            except ValueError:
                # Invalid date for month
                continue

        return None, None, False

    def compute_end_from_duration(
        self, start_date: Optional[str], duration_days: int
    ) -> Optional[str]:
        """Compute end_date from start_date and duration in days."""
        if not start_date or duration_days <= 0:
            return None

        start_dt = self.parse_iso(start_date)
        if not start_dt:
            return None

        end_dt = start_dt + timedelta(days=duration_days)
        return end_dt.strftime("%Y-%m-%d")

    def is_valid_range(self, start_date: Optional[str], end_date: Optional[str]) -> bool:
        """Check if end_date >= start_date (allowing same-day trips)."""
        if not start_date or not end_date:
            return True  # Can't validate incomplete range

        start_dt = self.parse_iso(start_date)
        end_dt = self.parse_iso(end_date)
        if not start_dt or not end_dt:
            return True  # Can't validate unparseable dates

        return end_dt >= start_dt
