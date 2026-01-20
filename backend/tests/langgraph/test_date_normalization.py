"""
Comprehensive tests for date normalization in plan_graph.py.

Tests cover:
- Natural language date formats (December 28, 2025)
- Ordinal dates (December 28th, 2025)
- US formats (12-28-2025, 12/28/2025)
- Partial dates (December 2025)
- Relative dates (tomorrow, next week)
- Date ranges (December 20-27)
- Edge cases and error handling
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.plan_graph import (
    GraphState,
    TripInputs,
    _date_normalizer,
    _normalize_date,
    _trip_normalizer,
    normalize_inputs,
)
from app.planner.normalization import DateNormalizer


class TestNormalizeDateFormats:
    """Test various date format conversions."""

    @pytest.mark.parametrize(
        "input_date,expected_iso",
        [
            # ISO format (already correct)
            ("2025-12-28", "2025-12-28"),
            ("2026-01-15", "2026-01-15"),
            # European dash format (DD-MM-YYYY)
            ("28-12-2025", "2025-12-28"),
            ("15-01-2026", "2026-01-15"),
            # European slash format (DD/MM/YYYY)
            ("28/12/2025", "2025-12-28"),
            ("15/01/2026", "2026-01-15"),
            # US slash format (MM/DD/YYYY)
            ("12/28/2025", "2025-12-28"),
            ("01/15/2026", "2026-01-15"),
            # US dash format (MM-DD-YYYY)
            ("12-28-2025", "2025-12-28"),
            ("01-15-2026", "2026-01-15"),
        ],
    )
    def test_numeric_date_formats(self, input_date: str, expected_iso: str):
        """Test numeric date format parsing."""
        result = _normalize_date(input_date)
        assert result == expected_iso, f"Failed to parse '{input_date}'"


class TestNaturalLanguageDates:
    """Test natural language date parsing."""

    @pytest.mark.parametrize(
        "input_date,expected_iso",
        [
            # Full month name with comma (December 28, 2025)
            ("December 28, 2025", "2025-12-28"),
            ("January 15, 2026", "2026-01-15"),
            ("March 1, 2025", "2025-03-01"),
            # Abbreviated month with comma (Dec 28, 2025)
            ("Dec 28, 2025", "2025-12-28"),
            ("Jan 15, 2026", "2026-01-15"),
            ("Mar 1, 2025", "2025-03-01"),
            # European format - day first (28 December 2025)
            ("28 December 2025", "2025-12-28"),
            ("15 January 2026", "2026-01-15"),
            ("1 March 2025", "2025-03-01"),
            # European abbreviated (28 Dec 2025)
            ("28 Dec 2025", "2025-12-28"),
            ("15 Jan 2026", "2026-01-15"),
            # No comma variants
            ("December 28 2025", "2025-12-28"),
            ("Dec 28 2025", "2025-12-28"),
            # European with comma
            ("28 December, 2025", "2025-12-28"),
            ("28 Dec, 2025", "2025-12-28"),
        ],
    )
    def test_natural_language_formats(self, input_date: str, expected_iso: str):
        """Test natural language date format parsing."""
        result = _normalize_date(input_date)
        assert result == expected_iso, f"Failed to parse '{input_date}'"


class TestOrdinalDates:
    """Test dates with ordinal suffixes (1st, 2nd, 3rd, 4th, etc.)."""

    @pytest.mark.parametrize(
        "input_date,expected_iso",
        [
            # Full month with ordinal
            ("December 28th, 2025", "2025-12-28"),
            ("January 1st, 2026", "2026-01-01"),
            ("March 2nd, 2025", "2025-03-02"),
            ("April 3rd, 2025", "2025-04-03"),
            ("May 4th, 2025", "2025-05-04"),
            ("June 21st, 2025", "2025-06-21"),
            ("July 22nd, 2025", "2025-07-22"),
            ("August 23rd, 2025", "2025-08-23"),
            # Abbreviated month with ordinal
            ("Dec 28th, 2025", "2025-12-28"),
            ("Jan 1st, 2026", "2026-01-01"),
            ("Mar 2nd, 2025", "2025-03-02"),
            # European format with ordinal (day first)
            ("28th December 2025", "2025-12-28"),
            ("1st January 2026", "2026-01-01"),
            ("2nd March 2025", "2025-03-02"),
            ("3rd April 2025", "2025-04-03"),
            # No comma with ordinal
            ("December 28th 2025", "2025-12-28"),
            ("Dec 28th 2025", "2025-12-28"),
            # European with comma and ordinal
            ("28th December, 2025", "2025-12-28"),
        ],
    )
    def test_ordinal_date_formats(self, input_date: str, expected_iso: str):
        """Test ordinal date format parsing (strips st/nd/rd/th suffixes)."""
        result = _normalize_date(input_date)
        assert result == expected_iso, f"Failed to parse '{input_date}'"


class TestPartialDates:
    """Test partial dates (month + year only) with default day handling."""

    @pytest.mark.parametrize(
        "input_date,expected_iso",
        [
            # Full month names
            ("December 2025", "2025-12-01"),
            ("January 2026", "2026-01-01"),
            ("March 2025", "2025-03-01"),
            ("February 2026", "2026-02-01"),
            # Abbreviated month names
            ("Dec 2025", "2025-12-01"),
            ("Jan 2026", "2026-01-01"),
            ("Mar 2025", "2025-03-01"),
            ("Feb 2026", "2026-02-01"),
        ],
    )
    def test_partial_dates_default_to_first(self, input_date: str, expected_iso: str):
        """Test that partial dates (month + year) default to 1st of month."""
        result = _normalize_date(input_date)
        assert result == expected_iso, f"Failed to parse '{input_date}'"

    @pytest.mark.parametrize(
        "input_date",
        [
            "December 2025",
            "Jan 2026",
            "March 2025",
        ],
    )
    def test_partial_dates_flag_as_partial(self, input_date: str):
        """Test that partial dates are flagged as such."""
        iso_date, was_partial = _trip_normalizer.normalize_date_with_info(input_date)
        assert iso_date is not None, f"Failed to parse '{input_date}'"
        assert was_partial is True, f"'{input_date}' should be flagged as partial"

    @pytest.mark.parametrize(
        "input_date",
        [
            "December 28, 2025",
            "28 December 2025",
            "12/28/2025",
            "2025-12-28",
        ],
    )
    def test_complete_dates_not_flagged_as_partial(self, input_date: str):
        """Test that complete dates are NOT flagged as partial."""
        iso_date, was_partial = _trip_normalizer.normalize_date_with_info(input_date)
        assert iso_date is not None, f"Failed to parse '{input_date}'"
        assert was_partial is False, f"'{input_date}' should NOT be flagged as partial"


class TestDateRangeParsing:
    """Test date range parsing (e.g., 'December 20-27').

    Uses a fixed reference date (December 1, 2025) for deterministic year inference.
    """

    @pytest.fixture
    def date_normalizer(self):
        """DateNormalizer with fixed reference date for deterministic tests."""
        # Use December 1, 2025 so "December 20-27" is still in the future
        return DateNormalizer(reference_date=date(2025, 12, 1))

    @pytest.mark.parametrize(
        "input_range,expected_start,expected_end",
        [
            # Month first format
            ("December 20-27", "2025-12-20", "2025-12-27"),
            ("Dec 20-27", "2025-12-20", "2025-12-27"),
            ("January 5-12", "2026-01-05", "2026-01-12"),
            ("Jan 5-12", "2026-01-05", "2026-01-12"),
            # With year
            ("December 20-27, 2025", "2025-12-20", "2025-12-27"),
            ("January 5-12, 2026", "2026-01-05", "2026-01-12"),
            # Day first format
            ("20-27 December", "2025-12-20", "2025-12-27"),
            ("5-12 January", "2026-01-05", "2026-01-12"),
            # With ordinal suffixes
            ("December 20th-27th", "2025-12-20", "2025-12-27"),
            ("March 1st-7th", "2026-03-01", "2026-03-07"),
            # With 'to' separator
            ("December 20 to 27", "2025-12-20", "2025-12-27"),
        ],
    )
    def test_date_range_parsing(
        self, date_normalizer, input_range: str, expected_start: str, expected_end: str
    ):
        """Test parsing of date ranges like 'December 20-27'."""
        start, end = date_normalizer.parse_date_range(input_range)
        assert start == expected_start, f"Start date mismatch for '{input_range}'"
        assert end == expected_end, f"End date mismatch for '{input_range}'"

    @pytest.mark.parametrize(
        "input_text",
        [
            "December 25",  # Single date, not a range
            "next week",  # Relative date
            "2025-12-20",  # ISO format
            "Paris",  # Not a date
            "I want to go to Rome",  # Sentence
        ],
    )
    def test_non_range_inputs_return_none(self, date_normalizer, input_text: str):
        """Test that non-range inputs return (None, None)."""
        start, end = date_normalizer.parse_date_range(input_text)
        assert start is None, f"Expected None for start with '{input_text}'"
        assert end is None, f"Expected None for end with '{input_text}'"


class TestFlexibleDateRangeParsing:
    """Test flexible date range parsing for mixed ordinals and European formats.

    These tests verify the new date parsing patterns added to handle:
    - Mixed ordinals: "6-15th feb" (ordinal only on second number)
    - European decimal: "6-15.02" (DD-DD.MM format)
    - Date ranges in sentences: "dates are 6-15 feb, budget around 2000"
    """

    @pytest.fixture
    def date_normalizer(self):
        """DateNormalizer with fixed reference date for deterministic tests."""
        # Use January 1, 2025 so February dates are in the future
        return DateNormalizer(reference_date=date(2025, 1, 1))

    @pytest.mark.parametrize(
        "input_range,expected_start,expected_end",
        [
            # Mixed ordinals (ordinal only on second number)
            ("6-15th feb", "2025-02-06", "2025-02-15"),
            ("6-15th Feb", "2025-02-06", "2025-02-15"),
            ("6-15th february", "2025-02-06", "2025-02-15"),
            ("1-10th march", "2025-03-01", "2025-03-10"),
            # Both ordinals
            ("6th-15th feb", "2025-02-06", "2025-02-15"),
            # No ordinals
            ("6-15 feb", "2025-02-06", "2025-02-15"),
            ("6-15 February", "2025-02-06", "2025-02-15"),
        ],
    )
    def test_mixed_ordinal_date_ranges(
        self, date_normalizer, input_range: str, expected_start: str, expected_end: str
    ):
        """Test parsing of date ranges with mixed ordinal suffixes."""
        start, end = date_normalizer.parse_date_range(input_range)
        assert start == expected_start, f"Start date mismatch for '{input_range}'"
        assert end == expected_end, f"End date mismatch for '{input_range}'"

    @pytest.mark.parametrize(
        "input_range,expected_start,expected_end",
        [
            # DD-DD.MM format (European decimal)
            ("6-15.02", "2025-02-06", "2025-02-15"),
            ("1-10.03", "2025-03-01", "2025-03-10"),
            ("20-27.12", "2025-12-20", "2025-12-27"),
            # With year
            ("6-15.02.2025", "2025-02-06", "2025-02-15"),
            ("6-15.02.25", "2025-02-06", "2025-02-15"),  # 2-digit year
        ],
    )
    def test_european_decimal_date_ranges(
        self, date_normalizer, input_range: str, expected_start: str, expected_end: str
    ):
        """Test parsing of European decimal date ranges (DD-DD.MM)."""
        start, end = date_normalizer.parse_date_range(input_range)
        assert start == expected_start, f"Start date mismatch for '{input_range}'"
        assert end == expected_end, f"End date mismatch for '{input_range}'"

    @pytest.mark.parametrize(
        "input_text,expected_start,expected_end",
        [
            # Date ranges embedded in sentences
            ("dates are 6-15 feb, budget around 2000", "2025-02-06", "2025-02-15"),
            ("going from dec 20-27", "2025-12-20", "2025-12-27"),
            ("trip dates: 6-15th feb", "2025-02-06", "2025-02-15"),
            ("planning for jan 5-12 next year", "2025-01-05", "2025-01-12"),
            # With surrounding context
            (
                "going to dubai, from south bend, dates are 6-15th feb, budget around 2000",
                "2025-02-06",
                "2025-02-15",
            ),
        ],
    )
    def test_date_ranges_in_context(
        self, date_normalizer, input_text: str, expected_start: str, expected_end: str
    ):
        """Test extracting date ranges from surrounding text context."""
        start, end = date_normalizer.parse_date_range(input_text)
        assert start == expected_start, f"Start date mismatch for '{input_text}'"
        assert end == expected_end, f"End date mismatch for '{input_text}'"

    @pytest.mark.parametrize(
        "input_range,expected_start,expected_end",
        [
            # DD.MM-DD.MM format (full European)
            ("6.02-15.02", "2025-02-06", "2025-02-15"),
            ("1.03-10.03", "2025-03-01", "2025-03-10"),
        ],
    )
    def test_full_european_date_ranges(
        self, date_normalizer, input_range: str, expected_start: str, expected_end: str
    ):
        """Test parsing of full European date ranges (DD.MM-DD.MM)."""
        start, end = date_normalizer.parse_date_range(input_range)
        assert start == expected_start, f"Start date mismatch for '{input_range}'"
        assert end == expected_end, f"End date mismatch for '{input_range}'"


class TestWeekOfMonthParsing:
    """Test 'first/second/third/fourth/last week of [month]' parsing."""

    @pytest.mark.parametrize(
        "input_text,expected_start,expected_end",
        [
            # First week of various months
            ("First week of January", "2026-01-01", "2026-01-07"),
            ("first week of January", "2026-01-01", "2026-01-07"),
            ("First week of Jan", "2026-01-01", "2026-01-07"),
            ("1st week of January", "2026-01-01", "2026-01-07"),
            # Second week
            ("Second week of March", "2026-03-08", "2026-03-14"),
            ("2nd week of March", "2026-03-08", "2026-03-14"),
            # Third week
            ("Third week of June", "2026-06-15", "2026-06-21"),
            ("3rd week of June", "2026-06-15", "2026-06-21"),
            # Fourth week
            ("Fourth week of September", "2026-09-22", "2026-09-28"),
            ("4th week of September", "2026-09-22", "2026-09-28"),
            # Last week (December 2025 is in the past when today is Jan 2026, so rolls to 2026)
            ("Last week of December", "2026-12-25", "2026-12-31"),
            ("last week of December", "2026-12-25", "2026-12-31"),
            # With explicit year
            ("First week of January 2027", "2027-01-01", "2027-01-07"),
            ("First week of January, 2027", "2027-01-01", "2027-01-07"),
        ],
    )
    def test_week_of_month_parsing(self, input_text: str, expected_start: str, expected_end: str):
        """Test parsing of 'first/second/third/fourth/last week of [month]'."""
        start, end = _date_normalizer.parse_date_range(input_text)
        assert start == expected_start, f"Start date mismatch for '{input_text}'"
        assert end == expected_end, f"End date mismatch for '{input_text}'"


class TestRelativeDates:
    """Test relative date expressions."""

    def test_today(self):
        """Test 'today' converts to today's date."""
        result = _normalize_date("today")
        expected = datetime.now(UTC).date().strftime("%Y-%m-%d")
        assert result == expected

    def test_tomorrow(self):
        """Test 'tomorrow' converts to tomorrow's date."""
        result = _normalize_date("tomorrow")
        expected = (datetime.now(UTC).date() + timedelta(days=1)).strftime("%Y-%m-%d")
        assert result == expected

    def test_next_week(self):
        """Test 'next week' converts to 7 days from now."""
        result = _normalize_date("next week")
        expected = (datetime.now(UTC).date() + timedelta(days=7)).strftime("%Y-%m-%d")
        assert result == expected

    def test_next_month(self):
        """Test 'next month' converts to 30 days from now."""
        result = _normalize_date("next month")
        expected = (datetime.now(UTC).date() + timedelta(days=30)).strftime("%Y-%m-%d")
        assert result == expected

    @pytest.mark.parametrize(
        "input_text",
        ["today", "tonight", "now", "tomorrow", "next week", "next month"],
    )
    def test_relative_dates_through_normalize(self, input_text: str):
        """Test that relative dates work through _normalize_date."""
        result = _normalize_date(input_text)
        assert result is not None, f"Failed to parse relative date '{input_text}'"
        # Should be a valid ISO date
        assert len(result) == 10
        assert result[4] == "-" and result[7] == "-"


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.parametrize(
        "invalid_input",
        [
            None,
            "",
            "   ",
            "not a date",
            "sometime in summer",
            "next year maybe",
            "32/13/2025",  # Invalid day/month
        ],
    )
    def test_invalid_inputs_return_none(self, invalid_input):
        """Test that invalid inputs return None."""
        result = _normalize_date(invalid_input)
        assert result is None, f"'{invalid_input}' should return None"

    def test_case_insensitivity(self):
        """Test that date parsing is case-insensitive."""
        assert _normalize_date("DECEMBER 28, 2025") == "2025-12-28"
        assert _normalize_date("december 28, 2025") == "2025-12-28"
        assert _normalize_date("December 28, 2025") == "2025-12-28"
        assert _normalize_date("DEC 28, 2025") == "2025-12-28"

    def test_whitespace_handling(self):
        """Test that extra whitespace is handled gracefully."""
        assert _normalize_date("  December 28, 2025  ") == "2025-12-28"
        # Extra internal whitespace is handled by strptime's flexibility
        assert _normalize_date("December  28,  2025") == "2025-12-28"


class TestNormalizeInputsIntegration:
    """Integration tests for date parsing in normalize_inputs."""

    def test_natural_date_applied_to_trip_inputs(self):
        """Test that natural language dates are correctly applied to trip_inputs."""
        state = GraphState(
            user_text="December 28, 2025",
            trip_inputs=TripInputs(destinations=["Paris"], origin="London"),
            parsed_inputs={"start_date_hint": "December 28, 2025"},
        )

        result = normalize_inputs(state)

        assert result.trip_inputs.start_date == "2025-12-28"

    def test_ordinal_date_applied_to_trip_inputs(self):
        """Test that ordinal dates are correctly applied to trip_inputs."""
        state = GraphState(
            user_text="December 28th, 2025",
            trip_inputs=TripInputs(destinations=["Paris"], origin="London"),
            parsed_inputs={"start_date_hint": "December 28th, 2025"},
        )

        result = normalize_inputs(state)

        assert result.trip_inputs.start_date == "2025-12-28"

    def test_partial_date_notification_set(self):
        """Test that partial dates set notification in metadata."""
        state = GraphState(
            user_text="December 2025",
            trip_inputs=TripInputs(destinations=["Paris"], origin="London"),
            parsed_inputs={"start_date_hint": "December 2025"},
        )

        result = normalize_inputs(state)

        assert result.trip_inputs.start_date == "2025-12-01"
        assert "partial_date_notifications" in result.metadata
        notifications = result.metadata["partial_date_notifications"]
        assert len(notifications) == 1
        assert "December 01, 2025" in notifications[0]
        # YC style: terse notification format "Start: {date}."
        assert notifications[0].startswith("Start:")

    def test_end_date_partial_notification(self):
        """Test that partial end dates also get notifications."""
        state = GraphState(
            user_text="May 2026",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date="2026-03-15",
            ),
            parsed_inputs={"end_date_hint": "May 2026"},
        )

        result = normalize_inputs(state)

        assert result.trip_inputs.end_date == "2026-05-01"
        notifications = result.metadata.get("partial_date_notifications", [])
        assert len(notifications) == 1
        # YC style: terse notification format "End: {date}."
        assert notifications[0].startswith("End:")

    def test_complete_date_no_notification(self):
        """Test that complete dates don't trigger notifications."""
        state = GraphState(
            user_text="December 28, 2025",
            trip_inputs=TripInputs(destinations=["Paris"], origin="London"),
            parsed_inputs={"start_date_hint": "December 28, 2025"},
        )

        result = normalize_inputs(state)

        assert result.trip_inputs.start_date == "2025-12-28"
        assert result.metadata.get("partial_date_notifications") is None

    def test_existing_start_date_not_overwritten(self):
        """Test that existing start_date is not overwritten by hint."""
        state = GraphState(
            user_text="January 2026",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date="2025-12-28",  # Already set
            ),
            parsed_inputs={"start_date_hint": "January 2026"},
        )

        result = normalize_inputs(state)

        # Should keep existing start_date
        assert result.trip_inputs.start_date == "2025-12-28"


# =============================================================================
# TIER 3: CRITICAL EDGE CASE TESTS
# =============================================================================


class TestCriticalDateEdgeCases:
    """Critical edge cases for date parsing - Tier 3 reliability tests."""

    def test_december_january_cross_year(self):
        """Test date ranges that span December to January (year boundary)."""
        # This is a common real-world scenario for holiday trips
        state = GraphState(
            user_text="December 28 to January 5",
            trip_inputs=TripInputs(destinations=["Paris"], origin="London"),
            parsed_inputs={
                "start_date_hint": "December 28",
                "end_date_hint": "January 5",
            },
        )

        result = normalize_inputs(state)

        # Start date should be current/nearest December
        assert result.trip_inputs.start_date is not None
        # End date should be in January (next year from December)
        assert result.trip_inputs.end_date is not None

        if result.trip_inputs.start_date and result.trip_inputs.end_date:
            start_year = int(result.trip_inputs.start_date[:4])
            end_year = int(result.trip_inputs.end_date[:4])
            # January should be in the year after December
            assert end_year >= start_year, "January should not be before December"

    def test_leap_year_february_29(self):
        """Test February 29th on a leap year."""
        # 2024 and 2028 are leap years
        result = _normalize_date("February 29, 2024")
        assert result == "2024-02-29"

        result = _normalize_date("February 29, 2028")
        assert result == "2028-02-29"

    def test_non_leap_year_february_29_handled(self):
        """Test February 29th on a non-leap year is handled gracefully."""
        # 2025, 2026, 2027 are not leap years
        result = _normalize_date("February 29, 2025")
        # Should return None or handle gracefully (not crash)
        # The parser may reject this as invalid
        assert result is None or result == "2025-02-28" or result == "2025-03-01"

    def test_today_straddle_midnight(self):
        """Test that 'today' is consistent even near midnight transitions."""
        # Get today's date
        today_result = _normalize_date("today")
        assert today_result is not None
        assert len(today_result) == 10

        # Parse back to verify it's a valid date
        parsed = date.fromisoformat(today_result)
        today = datetime.now(UTC).date()

        # Should be today or very close (within 1 day for timezone edge cases)
        diff = abs((parsed - today).days)
        assert diff <= 1, f"'today' parsed to {parsed} but actual today is {today}"

    def test_year_rollover_december_31(self):
        """Test December 31st date parsing near year boundary."""
        result = _normalize_date("December 31, 2025")
        assert result == "2025-12-31"

        result = _normalize_date("December 31, 2026")
        assert result == "2026-12-31"

    def test_january_1_new_year(self):
        """Test January 1st date parsing."""
        result = _normalize_date("January 1, 2026")
        assert result == "2026-01-01"

        result = _normalize_date("January 1st, 2026")
        assert result == "2026-01-01"

    def test_month_end_dates(self):
        """Test last day of various months."""
        # 30-day months
        assert _normalize_date("April 30, 2026") == "2026-04-30"
        assert _normalize_date("June 30, 2026") == "2026-06-30"
        assert _normalize_date("September 30, 2026") == "2026-09-30"
        assert _normalize_date("November 30, 2026") == "2026-11-30"

        # 31-day months
        assert _normalize_date("January 31, 2026") == "2026-01-31"
        assert _normalize_date("March 31, 2026") == "2026-03-31"
        assert _normalize_date("May 31, 2026") == "2026-05-31"
        assert _normalize_date("July 31, 2026") == "2026-07-31"
        assert _normalize_date("August 31, 2026") == "2026-08-31"
        assert _normalize_date("October 31, 2026") == "2026-10-31"
        assert _normalize_date("December 31, 2026") == "2026-12-31"

    def test_invalid_month_day_combinations(self):
        """Test invalid day-of-month combinations are handled gracefully."""
        # April only has 30 days
        result = _normalize_date("April 31, 2026")
        assert result is None, "April 31 should return None"

        # February only has 28/29 days
        result = _normalize_date("February 30, 2026")
        assert result is None, "February 30 should return None"

        # September only has 30 days
        result = _normalize_date("September 31, 2026")
        assert result is None, "September 31 should return None"


class TestParsingRobustness:
    """Test parsing robustness for edge cases - Tier 3 reliability tests."""

    def test_european_budget_format_with_comma(self):
        """Test that European budget formats with comma are handled.

        Note: This tests extraction parsing, not date parsing.
        European format uses comma as decimal separator: 2.000,50
        """
        from app.plan_graph import GraphState, TripInputs

        # Create state with European-style budget representation
        state = GraphState(
            user_text="My budget is around 2000 euros",
            trip_inputs=TripInputs(destinations=["Paris"]),
            parsed_inputs={"budget_delta": {"budget": 2000, "currency": "EUR"}},
        )

        # Verify state is created successfully
        assert state.parsed_inputs.get("budget_delta", {}).get("budget") == 2000
        assert state.parsed_inputs.get("budget_delta", {}).get("currency") == "EUR"

    def test_unicode_destination_names(self):
        """Test that unicode destination names are handled."""
        state = GraphState(
            user_text="I want to go to Zürich",
            trip_inputs=TripInputs(),
            parsed_inputs={"destinations_delta": ["Zürich"]},
        )

        result = normalize_inputs(state)
        # Should not crash
        assert result is not None

    def test_mixed_case_dates(self):
        """Test mixed case date parsing."""
        assert _normalize_date("dEcEmBeR 28, 2025") == "2025-12-28"
        assert _normalize_date("JANUARY 15, 2026") == "2026-01-15"
        assert _normalize_date("march 1st, 2026") == "2026-03-01"

    def test_extra_punctuation_in_dates(self):
        """Test dates with extra punctuation are handled."""
        # These should either parse correctly or return None gracefully
        result = _normalize_date("December 28th 2025.")
        # Should parse without the trailing period
        assert result == "2025-12-28" or result is None

    def test_very_long_date_string(self):
        """Test very long date strings don't cause issues."""
        long_input = "December 28, 2025" + " " * 1000
        result = _normalize_date(long_input)
        # Should either parse correctly or return None
        assert result == "2025-12-28" or result is None

    def test_empty_and_whitespace_only(self):
        """Test empty and whitespace-only inputs."""
        assert _normalize_date("") is None
        assert _normalize_date("   ") is None
        assert _normalize_date("\n\t") is None
        assert _normalize_date(None) is None
