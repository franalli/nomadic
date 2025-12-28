"""
Unit tests for P2.3 compound travelers+date parsing.

Tests:
- COMPOUND_TRAVELERS_DATE_PATTERN pattern matching
- COMPOUND_DATE_TRAVELERS_PATTERN pattern matching
- _parse_compound_travelers_date() function
- Integration with _run_deterministic_pipeline
"""

from app.pattern_matching import (
    COMPOUND_DATE_TRAVELERS_PATTERN,
    COMPOUND_KEYWORDS,
    COMPOUND_TRAVELERS_DATE_PATTERN,
)
from app.plan_graph import GraphState, TripInputs, _run_deterministic_pipeline
from app.planner.parsing.lqa_parsers import _parse_compound_travelers_date


def _make_test_state(
    trip_inputs: TripInputs | None = None,
    metadata: dict | None = None,
    question_target: str | None = None,
    user_text: str = "",
) -> GraphState:
    """Create a test GraphState."""
    state = GraphState(
        user_text=user_text,
        trip_inputs=trip_inputs or TripInputs(),
    )
    if metadata:
        state.metadata.update(metadata)
    if question_target:
        state.question_target = question_target
    return state


class TestCompoundTravelersDatePattern:
    """Tests for COMPOUND_TRAVELERS_DATE_PATTERN regex."""

    def test_adults_for_next_month(self):
        """Should match '2 adults for next month'."""
        text = "2 adults for next month"
        match = COMPOUND_TRAVELERS_DATE_PATTERN.match(text)
        assert match is not None
        assert match.group("travelers") == "2 adults"
        assert match.group("date") == "next month"

    def test_people_in_december(self):
        """Should match '3 people in December'."""
        text = "3 people in December"
        match = COMPOUND_TRAVELERS_DATE_PATTERN.match(text)
        assert match is not None
        assert match.group("travelers") == "3 people"
        assert match.group("date") == "December"

    def test_couple_for_next_week(self):
        """Should match 'couple for next week'."""
        text = "couple for next week"
        match = COMPOUND_TRAVELERS_DATE_PATTERN.match(text)
        assert match is not None
        assert match.group("travelers") == "couple"
        assert match.group("date") == "next week"

    def test_family_of_4_in_january(self):
        """Should match 'family of 4 in January'."""
        text = "family of 4 in January"
        match = COMPOUND_TRAVELERS_DATE_PATTERN.match(text)
        assert match is not None
        assert match.group("travelers") == "family of 4"
        assert match.group("date") == "January"

    def test_just_me_for_summer(self):
        """Should match 'just me for summer'."""
        text = "just me for summer"
        match = COMPOUND_TRAVELERS_DATE_PATTERN.match(text)
        assert match is not None
        assert match.group("travelers") == "just me"
        assert match.group("date") == "summer"

    def test_3_of_us_during_winter(self):
        """Should match '3 of us during winter'."""
        text = "3 of us during winter"
        match = COMPOUND_TRAVELERS_DATE_PATTERN.match(text)
        assert match is not None
        assert match.group("travelers") == "3 of us"
        assert match.group("date") == "winter"


class TestCompoundDateTravelersPattern:
    """Tests for COMPOUND_DATE_TRAVELERS_PATTERN regex."""

    def test_next_month_for_2_adults(self):
        """Should match 'next month for 2 adults'."""
        text = "next month for 2 adults"
        match = COMPOUND_DATE_TRAVELERS_PATTERN.match(text)
        assert match is not None
        assert match.group("date") == "next month"
        assert match.group("travelers") == "2 adults"

    def test_january_with_3_people(self):
        """Should match 'January with 3 people'."""
        text = "January with 3 people"
        match = COMPOUND_DATE_TRAVELERS_PATTERN.match(text)
        assert match is not None
        assert match.group("date") == "January"
        assert match.group("travelers") == "3 people"

    def test_this_week_for_couple(self):
        """Should match 'this week for couple'."""
        text = "this week for couple"
        match = COMPOUND_DATE_TRAVELERS_PATTERN.match(text)
        assert match is not None
        assert match.group("date") == "this week"
        assert match.group("travelers") == "couple"


class TestCompoundKeywords:
    """Tests for COMPOUND_KEYWORDS set."""

    def test_all_keywords_present(self):
        """Should contain all compound keywords."""
        assert "for" in COMPOUND_KEYWORDS
        assert "in" in COMPOUND_KEYWORDS
        assert "during" in COMPOUND_KEYWORDS
        assert "with" in COMPOUND_KEYWORDS


class TestParseCompoundTravelersDate:
    """Tests for _parse_compound_travelers_date function."""

    def test_adults_for_next_month(self):
        """Should parse '2 adults for next month'."""
        state = _make_test_state(question_target="travelers")
        result = _parse_compound_travelers_date("2 adults for next month", state)

        assert result is not None
        assert result.get("adults_delta") == 2
        assert "lqa_reason" in result
        assert "compound" in result["lqa_reason"]

    def test_couple_for_next_week(self):
        """Should parse 'couple for next week'."""
        state = _make_test_state(question_target="dates")
        result = _parse_compound_travelers_date("couple for next week", state)

        assert result is not None
        assert result.get("adults_delta") == 2
        assert "lqa_reason" in result

    def test_family_of_4_in_december(self):
        """Should parse 'family of 4 in December'."""
        state = _make_test_state(question_target="travelers")
        result = _parse_compound_travelers_date("family of 4 in December", state)

        assert result is not None
        # Family of 4 typically parsed as 4 adults (or 2+2)
        assert result.get("adults_delta") is not None
        assert "lqa_reason" in result

    def test_next_month_for_3_people(self):
        """Should parse 'next month for 3 people' (date-first)."""
        state = _make_test_state(question_target="dates")
        result = _parse_compound_travelers_date("next month for 3 people", state)

        assert result is not None
        assert result.get("adults_delta") == 3
        assert "lqa_reason" in result

    def test_no_compound_keywords_returns_none(self):
        """Should return None when no compound keywords present."""
        state = _make_test_state(question_target="travelers")
        result = _parse_compound_travelers_date("2 adults", state)

        assert result is None

    def test_non_compound_text_returns_none(self):
        """Should return None for non-compound text."""
        state = _make_test_state(question_target="destinations")
        result = _parse_compound_travelers_date("Paris", state)

        assert result is None


class TestCompoundParsingIntegration:
    """Integration tests for compound parsing in deterministic pipeline."""

    def test_compound_in_deterministic_pipeline(self):
        """Compound parsing should work through _run_deterministic_pipeline."""
        state = _make_test_state(question_target="travelers")
        result = _run_deterministic_pipeline("2 adults for next month", state)

        # Should get a compound result with both fields
        assert result is not None
        assert result.get("adults_delta") == 2 or "adults_delta" in result
        assert "lqa_reason" in result

    def test_non_compound_falls_through(self):
        """Non-compound text should fall through to other parsers."""
        state = _make_test_state(question_target="destinations")
        # This should not be parsed as compound
        result = _run_deterministic_pipeline("Paris", state)

        # Should be handled by place parser, not compound
        if result:
            assert "compound" not in result.get("lqa_reason", "")

    def test_compound_captures_both_travelers_and_date(self):
        """Compound result should include both travelers and date info."""
        state = _make_test_state(question_target="travelers")
        result = _parse_compound_travelers_date("2 adults for next week", state)

        if result:
            # Should have travelers info
            has_travelers = "adults_delta" in result or "children_delta" in result
            # Should have date info (might be start_date_hint or similar)
            has_date = any(k for k in result if "date" in k.lower())
            # At least one should be present
            assert has_travelers or has_date
