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

from datetime import UTC, datetime, timedelta

import pytest

from app.plan_graph import (
    GraphState,
    TripInputs,
    _date_normalizer,
    _normalize_date,
    _trip_normalizer,
    normalize_inputs,
)


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
    """Test date range parsing (e.g., 'December 20-27')."""

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
    def test_date_range_parsing(self, input_range: str, expected_start: str, expected_end: str):
        """Test parsing of date ranges like 'December 20-27'."""
        start, end = _date_normalizer.parse_date_range(input_range)
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
    def test_non_range_inputs_return_none(self, input_text: str):
        """Test that non-range inputs return (None, None)."""
        start, end = _date_normalizer.parse_date_range(input_text)
        assert start is None, f"Expected None for start with '{input_text}'"
        assert end is None, f"Expected None for end with '{input_text}'"


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
            # Last week
            ("Last week of December", "2025-12-25", "2025-12-31"),
            ("last week of December", "2025-12-25", "2025-12-31"),
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
        assert "different day" in notifications[0]

    def test_end_date_partial_notification(self):
        """Test that partial end dates also get notifications."""
        state = GraphState(
            user_text="March 2026",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date="2025-12-28",
            ),
            parsed_inputs={"end_date_hint": "March 2026"},
        )

        result = normalize_inputs(state)

        assert result.trip_inputs.end_date == "2026-03-01"
        notifications = result.metadata.get("partial_date_notifications", [])
        assert len(notifications) == 1
        assert "end date" in notifications[0]

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
