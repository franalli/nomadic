"""
Unit tests for P4.1 negation alternative extraction.

Tests:
- NEGATION_ALTERNATIVE_PATTERN pattern matching
- SIMPLE_NEGATION_PATTERN pattern matching
- _extract_negation_alternative() function
- Integration with lqa_prepass
"""

from app.pattern_matching import NEGATION_ALTERNATIVE_PATTERN, SIMPLE_NEGATION_PATTERN
from app.plan_graph import GraphState, TripInputs
from app.planner.parsing.lqa_parsers import _extract_negation_alternative


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


class TestNegationAlternativePattern:
    """Tests for NEGATION_ALTERNATIVE_PATTERN regex."""

    def test_not_maybe_pattern(self):
        """Should match 'not X, maybe Y' pattern."""
        text = "not Paris, maybe Barcelona"
        match = NEGATION_ALTERNATIVE_PATTERN.search(text)
        assert match is not None
        # First non-None group should be the alternative
        alternative = next((g for g in match.groups() if g), None)
        assert alternative == "Barcelona"

    def test_not_try_pattern(self):
        """Should match 'not X, try Y' pattern."""
        text = "not Rome, try Venice"
        match = NEGATION_ALTERNATIVE_PATTERN.search(text)
        assert match is not None
        alternative = next((g for g in match.groups() if g), None)
        assert alternative == "Venice"

    def test_instead_of_pattern(self):
        """Should match 'instead of X, Y' pattern."""
        text = "instead of London, try Manchester"
        match = NEGATION_ALTERNATIVE_PATTERN.search(text)
        assert match is not None
        alternative = next((g for g in match.groups() if g), None)
        assert alternative == "Manchester"

    def test_change_to_pattern(self):
        """Should match 'change to X' pattern."""
        text = "change to Tokyo"
        match = NEGATION_ALTERNATIVE_PATTERN.search(text)
        assert match is not None
        alternative = next((g for g in match.groups() if g), None)
        assert alternative == "Tokyo"

    def test_switch_to_pattern(self):
        """Should match 'switch to X' pattern."""
        text = "switch to Berlin"
        match = NEGATION_ALTERNATIVE_PATTERN.search(text)
        assert match is not None
        alternative = next((g for g in match.groups() if g), None)
        assert alternative == "Berlin"

    def test_actually_pattern(self):
        """Should match 'actually X' pattern."""
        text = "actually Sydney"
        match = NEGATION_ALTERNATIVE_PATTERN.search(text)
        assert match is not None
        alternative = next((g for g in match.groups() if g), None)
        assert alternative == "Sydney"

    def test_x_instead_pattern(self):
        """Should match 'X instead' pattern."""
        text = "Amsterdam instead"
        match = NEGATION_ALTERNATIVE_PATTERN.search(text)
        assert match is not None
        alternative = next((g for g in match.groups() if g), None)
        assert alternative == "Amsterdam"

    def test_not_but_pattern(self):
        """Should match 'not X but Y' pattern."""
        text = "not Dubai but Abu Dhabi"
        match = NEGATION_ALTERNATIVE_PATTERN.search(text)
        assert match is not None


class TestSimpleNegationPattern:
    """Tests for SIMPLE_NEGATION_PATTERN regex."""

    def test_no_match(self):
        """Should match 'no'."""
        text = "no"
        match = SIMPLE_NEGATION_PATTERN.match(text)
        assert match is not None

    def test_no_thanks_match(self):
        """Should match 'no thanks'."""
        text = "no thanks"
        match = SIMPLE_NEGATION_PATTERN.match(text)
        assert match is not None

    def test_not_that_match(self):
        """Should match 'not that'."""
        text = "not that"
        match = SIMPLE_NEGATION_PATTERN.match(text)
        assert match is not None

    def test_nevermind_match(self):
        """Should match 'never mind'."""
        text = "never mind"
        match = SIMPLE_NEGATION_PATTERN.match(text)
        assert match is not None

    def test_dont_want_match(self):
        """Should match \"don't want\"."""
        text = "don't want"
        match = SIMPLE_NEGATION_PATTERN.match(text)
        assert match is not None

    def test_complex_text_no_match(self):
        """Should not match complex text with alternatives."""
        text = "not Paris, maybe Barcelona"
        match = SIMPLE_NEGATION_PATTERN.match(text)
        assert match is None


class TestExtractNegationAlternative:
    """Tests for _extract_negation_alternative function."""

    def test_not_maybe_extraction(self):
        """Should extract alternative from 'not X, maybe Y'."""
        state = _make_test_state(question_target="destinations")
        result = _extract_negation_alternative("not Paris, maybe Barcelona", state)

        assert result is not None
        assert result["alternative"] == "Barcelona"
        assert result["negation_type"] == "not_maybe"

    def test_instead_of_extraction(self):
        """Should extract alternative from 'instead of X, Y'."""
        state = _make_test_state(question_target="destinations")
        result = _extract_negation_alternative("instead of Rome, try Venice", state)

        assert result is not None
        assert result["alternative"] == "Venice"
        assert result["negation_type"] == "instead_of"

    def test_actually_extraction(self):
        """Should extract alternative from 'actually X'."""
        state = _make_test_state(question_target="destinations")
        result = _extract_negation_alternative("actually Tokyo", state)

        assert result is not None
        assert result["alternative"] == "Tokyo"
        assert result["negation_type"] == "actually"

    def test_change_to_extraction(self):
        """Should extract alternative from 'change to X'."""
        state = _make_test_state(question_target="origin")
        result = _extract_negation_alternative("change to London", state)

        assert result is not None
        assert result["alternative"] == "London"
        assert result["negation_type"] == "change_to"

    def test_x_instead_extraction(self):
        """Should extract alternative from 'X instead'."""
        state = _make_test_state(question_target="destinations")
        result = _extract_negation_alternative("Barcelona instead", state)

        assert result is not None
        assert result["alternative"] == "Barcelona"
        assert result["negation_type"] == "x_instead"

    def test_simple_rejection(self):
        """Should detect simple rejection without alternative."""
        state = _make_test_state(question_target="destinations")
        result = _extract_negation_alternative("no thanks", state)

        assert result is not None
        assert result["alternative"] is None
        assert result["negation_type"] == "simple_rejection"

    def test_no_negation(self):
        """Should return None for non-negation text."""
        state = _make_test_state(question_target="destinations")
        result = _extract_negation_alternative("Paris", state)

        assert result is None

    def test_trailing_punctuation_removed(self):
        """Should remove trailing punctuation from alternative."""
        state = _make_test_state(question_target="destinations")
        result = _extract_negation_alternative("actually Tokyo!", state)

        assert result is not None
        assert result["alternative"] == "Tokyo"


class TestNegationAlternativeIntegration:
    """Integration tests for negation alternative in LQA flow."""

    def test_negation_with_known_place_alternative(self):
        """Negation with known place should be parsable."""
        state = _make_test_state(question_target="destinations")
        result = _extract_negation_alternative("not Paris, maybe Barcelona", state)

        assert result is not None
        assert result["alternative"] == "Barcelona"
        # Barcelona is a known place, so parser should work

    def test_negation_with_unknown_alternative(self):
        """Negation with unknown text should still extract alternative."""
        state = _make_test_state(question_target="destinations")
        result = _extract_negation_alternative("not Paris, maybe somewhere warm", state)

        assert result is not None
        assert result["alternative"] == "somewhere warm"
        # This should be marked for extractor since not a known place

    def test_nottingham_not_matched(self):
        """'Nottingham' should not trigger negation (contains 'not')."""
        state = _make_test_state(question_target="destinations")
        result = _extract_negation_alternative("Nottingham", state)

        # Should not match negation pattern - just a place name
        assert result is None
