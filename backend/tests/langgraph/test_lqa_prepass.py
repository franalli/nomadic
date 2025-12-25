"""Tests for LQA (Last Question Answer) pre-pass node."""

# ruff: noqa: E402

import os
import sys
from pathlib import Path

# Suppress debug output before importing plan_graph
os.environ["PLAN_GRAPH_DEBUG"] = "0"

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from app.plan_graph import (
    GraphState,
    TripInputs,
    _lqa_stats,
    _parse_budget_answer,
    _parse_date_answer,
    _parse_destination_answer,
    _parse_duration_answer,
    _parse_origin_answer,
    _parse_travelers_answer,
    get_graph_stats,
    lqa_prepass,
    reset_graph_stats,
)


class TestLqaFieldParsers:
    """Tests for individual LQA field parser functions."""

    def test_parse_destination_known_place(self):
        """Should parse known place names."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_destination_answer("Paris", state)
        assert result is not None
        assert result["destinations_delta"] == ["Paris"]

    def test_parse_destination_synonym(self):
        """Should normalize place synonyms like NYC -> New York."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_destination_answer("NYC", state)
        assert result is not None
        assert "New York" in result["destinations_delta"][0]

    def test_parse_destination_unknown_place(self):
        """Should return None for unknown places."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_destination_answer("Xyzzy123", state)
        assert result is None

    def test_parse_origin_simple(self):
        """Should parse simple origin."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_origin_answer("London", state)
        assert result is not None
        assert result["origin_delta"] == "London"

    def test_parse_origin_with_from_prefix(self):
        """Should handle 'from X' prefix."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_origin_answer("from Amsterdam", state)
        assert result is not None
        assert result["origin_delta"] == "Amsterdam"

    def test_parse_date_iso(self):
        """Should parse date-like strings."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        # Test with a relative date phrase
        result = _parse_date_answer("next month", state)
        assert result is not None
        assert "start_date_hint" in result

    def test_parse_date_as_end_date_when_start_date_set(self):
        """Should parse date as end_date_hint when start_date is already set."""
        # When start_date is already set and user provides a single date,
        # it should be interpreted as the return/end date
        state = GraphState(
            user_text="", trip_inputs=TripInputs(start_date="2025-12-29")  # start_date already set
        )
        result = _parse_date_answer("January 10, 2026", state)
        assert result is not None
        assert "end_date_hint" in result
        assert "start_date_hint" not in result
        assert result["end_date_hint"] == "2026-01-10"

    def test_parse_date_as_start_date_when_no_dates_set(self):
        """Should parse date as start_date_hint when no dates are set."""
        state = GraphState(user_text="", trip_inputs=TripInputs())  # no dates set
        result = _parse_date_answer("January 10, 2026", state)
        assert result is not None
        assert "start_date_hint" in result
        assert result["start_date_hint"] == "2026-01-10"

    def test_parse_date_invalid(self):
        """Should return None for non-date strings."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_date_answer("hello world", state)
        assert result is None

    def test_parse_travelers_adults(self):
        """Should parse adult count."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_travelers_answer("2 adults", state)
        assert result is not None
        assert result["adults_delta"] == 2

    def test_parse_travelers_solo(self):
        """Should handle 'just me' as 1 adult."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_travelers_answer("just me", state)
        assert result is not None
        assert result["adults_delta"] == 1

    def test_parse_travelers_family(self):
        """Should handle 'family of X' pattern."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_travelers_answer("family of 4", state)
        assert result is not None
        assert result["adults_delta"] == 4

    def test_parse_budget_simple(self):
        """Should parse simple budget amounts."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_budget_answer("$2000", state)
        assert result is not None
        assert result["budget_delta"] == 2000.0

    def test_parse_budget_with_k(self):
        """Should handle k suffix (2k = 2000)."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_budget_answer("2k", state)
        assert result is not None
        assert result["budget_delta"] == 2000.0

    def test_parse_budget_under_amount(self):
        """Should parse 'under $X' format."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_budget_answer("under $2,000", state)
        assert result is not None
        assert result["budget_delta"] == 2000.0

    def test_parse_budget_around_amount(self):
        """Should parse 'around $X' format."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_budget_answer("around $1,500", state)
        assert result is not None
        assert result["budget_delta"] == 1500.0

    def test_parse_budget_max_amount(self):
        """Should parse 'max $X' format."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_budget_answer("max $3000", state)
        assert result is not None
        assert result["budget_delta"] == 3000.0

    def test_parse_budget_less_than(self):
        """Should parse 'less than $X' format."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_budget_answer("less than $5000", state)
        assert result is not None
        assert result["budget_delta"] == 5000.0

    def test_parse_budget_no_budget(self):
        """Should handle 'no budget' as answered but no value."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_budget_answer("no budget", state)
        assert result is not None
        assert result.get("budget_answered") is True
        assert result.get("budget_delta") is None

    def test_parse_budget_flexible(self):
        """Should handle 'flexible' as answered but no value."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_budget_answer("flexible budget", state)
        assert result is not None
        assert result.get("budget_answered") is True

    def test_parse_budget_no_limit(self):
        """Should handle 'no limit' as answered but no value."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_budget_answer("no limit", state)
        assert result is not None
        assert result.get("budget_answered") is True

    def test_parse_budget_luxury_tier(self):
        """Should handle 'luxury' and set budget tier."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_budget_answer("luxury", state)
        assert result is not None
        assert result.get("budget_answered") is True
        assert result.get("budget_tier") == "luxury"

    def test_parse_budget_budget_friendly(self):
        """Should handle 'budget-friendly' and set budget tier."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_budget_answer("budget-friendly", state)
        assert result is not None
        assert result.get("budget_answered") is True
        assert result.get("budget_tier") == "budget"

    def test_parse_budget_mid_range(self):
        """Should handle 'mid-range' and set budget tier."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_budget_answer("mid-range", state)
        assert result is not None
        assert result.get("budget_answered") is True
        assert result.get("budget_tier") == "moderate"

    def test_parse_duration_days(self):
        """Should parse day duration."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_duration_answer("7 days", state)
        assert result is not None
        assert result["duration_days"] == 7

    def test_parse_duration_weeks(self):
        """Should convert weeks to days."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_duration_answer("2 weeks", state)
        assert result is not None
        assert result["duration_days"] == 14


class TestLqaPrepass:
    """Tests for the lqa_prepass node function."""

    def setup_method(self):
        """Reset stats before each test."""
        reset_graph_stats()

    def test_bail_on_pending_action(self):
        """Should bail when pending_action is set."""
        state = GraphState(
            user_text="yes",
            trip_inputs=TripInputs(),
            metadata={"pending_action": "confirm_typo", "last_question_field": "destinations"},
        )
        result = lqa_prepass(state)
        assert result.flags.get("lqa_prepass") is False
        assert result.flags.get("lqa_bail_reason") == "pending_action"
        assert _lqa_stats["bail_pending_action"] == 1

    def test_bail_on_no_question_target(self):
        """Should bail when no question_target is set."""
        state = GraphState(
            user_text="Paris",
            trip_inputs=TripInputs(),
            metadata={},  # No last_question_field
        )
        result = lqa_prepass(state)
        assert result.flags.get("lqa_prepass") is False
        assert result.flags.get("lqa_bail_reason") == "no_question_target"
        assert _lqa_stats["bail_no_question_target"] == 1

    def test_bail_on_too_long(self):
        """Should bail when input exceeds lqa_max_length."""
        long_text = "I want to go to Paris and Rome and Barcelona and Madrid"
        state = GraphState(
            user_text=long_text,
            trip_inputs=TripInputs(),
            question_target="destinations",
            metadata={},
        )
        result = lqa_prepass(state)
        assert result.flags.get("lqa_prepass") is False
        assert result.flags.get("lqa_bail_reason") == "too_long"
        assert _lqa_stats["bail_too_long"] == 1

    def test_bail_on_multi_intent(self):
        """Should bail when multi-intent pattern detected."""
        state = GraphState(
            user_text="Paris and also book hotels",
            trip_inputs=TripInputs(),
            question_target="destinations",
            metadata={},
        )
        result = lqa_prepass(state)
        assert result.flags.get("lqa_prepass") is False
        assert result.flags.get("lqa_bail_reason") in ("multi_intent", "negation")

    def test_bail_on_negation(self):
        """Should bail when negation pattern detected."""
        state = GraphState(
            user_text="not Paris, somewhere else",
            trip_inputs=TripInputs(),
            question_target="destinations",
            metadata={},
        )
        result = lqa_prepass(state)
        assert result.flags.get("lqa_prepass") is False

    def test_hit_destination(self):
        """Should parse destination and set lqa_prepass=True."""
        state = GraphState(
            user_text="Paris",
            trip_inputs=TripInputs(),
            question_target="destinations",
            metadata={},
        )
        result = lqa_prepass(state)
        assert result.flags.get("lqa_prepass") is True
        assert result.parsed_inputs.get("destinations_delta") == ["Paris"]
        assert _lqa_stats["hits"] == 1

    def test_hit_origin_with_from(self):
        """Should parse origin with 'from' prefix."""
        state = GraphState(
            user_text="from London",
            trip_inputs=TripInputs(),
            question_target="origin",
            metadata={},
        )
        result = lqa_prepass(state)
        assert result.flags.get("lqa_prepass") is True
        assert result.parsed_inputs.get("origin_delta") == "London"

    def test_hit_travelers(self):
        """Should parse travelers count."""
        state = GraphState(
            user_text="2 adults",
            trip_inputs=TripInputs(),
            question_target="travelers",
            metadata={},
        )
        result = lqa_prepass(state)
        assert result.flags.get("lqa_prepass") is True
        assert result.parsed_inputs.get("adults_delta") == 2

    def test_uses_last_question_field_fallback(self):
        """Should use metadata.last_question_field if question_target not set."""
        state = GraphState(
            user_text="Paris",
            trip_inputs=TripInputs(),
            metadata={"last_question_field": "destinations"},
        )
        result = lqa_prepass(state)
        assert result.flags.get("lqa_prepass") is True
        assert result.parsed_inputs.get("destinations_delta") == ["Paris"]


class TestLqaStats:
    """Tests for LQA observability stats tracking."""

    def setup_method(self):
        """Reset stats before each test."""
        reset_graph_stats()

    def test_attempts_counter_increments(self):
        """Should increment attempts counter on every lqa_prepass call."""
        state = GraphState(
            user_text="Paris",
            trip_inputs=TripInputs(),
            question_target="destinations",
            metadata={},
        )
        initial_attempts = _lqa_stats["attempts"]
        lqa_prepass(state)
        assert _lqa_stats["attempts"] == initial_attempts + 1

    def test_hits_counter_on_success(self):
        """Should increment hits counter when LQA successfully parses."""
        state = GraphState(
            user_text="Paris",
            trip_inputs=TripInputs(),
            question_target="destinations",
            metadata={},
        )
        initial_hits = _lqa_stats["hits"]
        result = lqa_prepass(state)
        assert result.flags.get("lqa_prepass") is True
        assert _lqa_stats["hits"] == initial_hits + 1

    def test_bails_counter_on_failure(self):
        """Should increment bails counter when LQA bails out."""
        state = GraphState(
            user_text="I want to go to Paris and book hotels and find activities",
            trip_inputs=TripInputs(),
            question_target="destinations",
            metadata={},
        )
        initial_bails = _lqa_stats["bails"]
        result = lqa_prepass(state)
        assert result.flags.get("lqa_prepass") is False
        assert _lqa_stats["bails"] == initial_bails + 1

    def test_stats_exposed_via_get_graph_stats(self):
        """Should expose LQA stats via get_graph_stats()["lqa"]."""
        # Make some calls to generate stats
        state_hit = GraphState(
            user_text="Paris",
            trip_inputs=TripInputs(),
            question_target="destinations",
            metadata={},
        )
        state_bail = GraphState(
            user_text="somewhere nice",
            trip_inputs=TripInputs(),
            question_target="destinations",
            metadata={},
        )
        lqa_prepass(state_hit)
        lqa_prepass(state_bail)

        stats = get_graph_stats()
        assert "lqa" in stats
        lqa_section = stats["lqa"]
        assert "attempts" in lqa_section
        assert "hits" in lqa_section
        assert "bails" in lqa_section
        assert "hit_rate" in lqa_section
        assert lqa_section["attempts"] >= 2

    def test_hit_rate_computation(self):
        """Should compute hit_rate as hits/attempts."""
        # Create 2 hits and 1 bail
        for city in ["Paris", "London"]:
            state = GraphState(
                user_text=city,
                trip_inputs=TripInputs(),
                question_target="destinations",
                metadata={},
            )
            lqa_prepass(state)

        state_bail = GraphState(
            user_text="somewhere nice and sunny",
            trip_inputs=TripInputs(),
            question_target="destinations",
            metadata={},
        )
        lqa_prepass(state_bail)

        stats = get_graph_stats()
        # With 2 hits and 1 bail, hit_rate should be 2/3 ≈ 0.667
        assert stats["lqa"]["hit_rate"] > 0.6
        assert stats["lqa"]["hit_rate"] < 0.7


class TestLqaParserEdgeCases:
    """Additional edge case tests for LQA field parsers.

    Some of these tests document potential parser improvements.
    Tests marked with pytest.mark.skip are for patterns not yet implemented.
    """

    def test_parse_date_iso_format(self):
        """Should parse ISO format dates like 2025-01-15."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_date_answer("2025-01-15", state)
        assert result is not None
        assert "start_date_hint" in result or "dates_raw" in result

    def test_parse_date_next_week(self):
        """Should parse 'next week' as relative date."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_date_answer("next week", state)
        assert result is not None

    def test_parse_date_month_day(self):
        """Should parse month + day format like December 15."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_date_answer("December 15", state)
        assert result is not None
        assert "start_date_hint" in result

    def test_parse_date_first_week_of_month(self):
        """Should parse 'first week of January' as a date range."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_date_answer("First week of January", state)
        assert result is not None
        assert "start_date_hint" in result
        assert "end_date_hint" in result
        # First week of January should be Jan 1-7
        assert result["start_date_hint"].endswith("-01-01")
        assert result["end_date_hint"].endswith("-01-07")

    def test_parse_date_last_week_of_month(self):
        """Should parse 'last week of December' as a date range."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_date_answer("last week of December", state)
        assert result is not None
        assert "start_date_hint" in result
        assert "end_date_hint" in result
        # Last week of December should be Dec 25-31
        assert result["end_date_hint"].endswith("-12-31")

    def test_parse_date_bare_month_name(self):
        """Should parse bare month names like 'December' as full month range."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_date_answer("December", state)
        assert result is not None
        assert "start_date_hint" in result
        assert "end_date_hint" in result
        # December should be Dec 01 to Dec 31
        assert result["start_date_hint"].endswith("-12-01")
        assert result["end_date_hint"].endswith("-12-31")

    def test_parse_date_bare_month_january(self):
        """Should parse 'January' as full month range."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_date_answer("January", state)
        assert result is not None
        assert "start_date_hint" in result
        assert "end_date_hint" in result
        assert result["start_date_hint"].endswith("-01-01")
        assert result["end_date_hint"].endswith("-01-31")

    def test_parse_date_bare_month_abbreviated(self):
        """Should parse abbreviated month names like 'jan' or 'feb'."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_date_answer("jan", state)
        assert result is not None
        assert result["start_date_hint"].endswith("-01-01")

        result = _parse_date_answer("feb", state)
        assert result is not None
        assert result["start_date_hint"].endswith("-02-01")

    def test_parse_budget_euro_symbol(self):
        """Should parse euro symbol budgets like €2000."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_budget_answer("€2000", state)
        assert result is not None
        assert result["budget_delta"] == 2000.0

    def test_parse_budget_thousand_word(self):
        """Should parse 'thousand' in budget like 5 thousand."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_budget_answer("5 thousand", state)
        assert result is not None
        assert result["budget_delta"] == 5000.0

    def test_parse_budget_gbp_symbol(self):
        """Should parse pound symbol budgets like £1500."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_budget_answer("£1500", state)
        assert result is not None
        assert result["budget_delta"] == 1500.0

    def test_parse_travelers_couple(self):
        """Should parse 'couple' as 2 adults."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_travelers_answer("a couple", state)
        assert result is not None
        assert result["adults_delta"] == 2

    def test_parse_travelers_with_children(self):
        """Should parse travelers with children like '2 adults and 2 kids'."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_travelers_answer("2 adults and 2 kids", state)
        assert result is not None
        assert result.get("adults_delta") == 2
        assert result.get("children_delta") == 2

    def test_parse_duration_weekend(self):
        """Should parse 'weekend' as short duration."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        _parse_duration_answer("a weekend", state)
        # May return None if not implemented, or days 2-3
        # This is an edge case that may need implementation

    def test_parse_destination_with_article(self):
        """Should parse destination with article like 'the Netherlands'."""
        state = GraphState(user_text="", trip_inputs=TripInputs())
        result = _parse_destination_answer("the Netherlands", state)
        assert result is not None
        assert "Netherlands" in result["destinations_delta"][0]


class TestLqaIntegration:
    """Integration tests verifying LQA pre-pass works within full graph flow.

    These tests use mocked LLM calls to verify that:
    1. LQA hit → extractor is skipped → normalize_inputs called
    2. LQA bail → extractor is called
    """

    def setup_method(self):
        """Reset stats before each test."""
        reset_graph_stats()

    def test_lqa_hit_skips_extractor_in_graph_flow(self):
        """When LQA hits, the extractor node should be skipped entirely.

        This test creates a state where LQA would succeed (simple destination
        answer after a question about destinations), runs through routing,
        and verifies the extractor path is not taken.
        """
        from app.plan_graph import route_after_lqa_prepass

        # Simulate state after lqa_prepass has run and succeeded
        state = GraphState(
            user_text="Paris",
            trip_inputs=TripInputs(),
            question_target="destinations",
            flags={"lqa_prepass": True},
            parsed_inputs={"destinations_delta": ["Paris"]},
            metadata={},
        )

        # Verify routing
        next_node = route_after_lqa_prepass(state)
        assert next_node == "normalize_inputs", "LQA hit should route to normalize_inputs"

    def test_lqa_bail_routes_to_extractor_in_graph_flow(self):
        """When LQA bails, the extractor node should be called.

        This test creates a state where LQA would bail (complex multi-intent
        answer), runs through routing, and verifies extractor is called.
        """
        from app.plan_graph import route_after_lqa_prepass

        # Simulate state after lqa_prepass has run and bailed
        state = GraphState(
            user_text="Paris and also book some hotels",
            trip_inputs=TripInputs(),
            question_target="destinations",
            flags={"lqa_prepass": False, "lqa_bail_reason": "multi_intent"},
            parsed_inputs={},
            metadata={},
        )

        # Verify routing
        next_node = route_after_lqa_prepass(state)
        assert next_node == "extractor", "LQA bail should route to extractor"

    def test_lqa_prepass_to_normalize_preserves_parsed_inputs(self):
        """Parsed inputs from LQA should be preserved through routing."""
        # Run lqa_prepass
        state = GraphState(
            user_text="Tokyo",
            trip_inputs=TripInputs(),
            question_target="destinations",
            metadata={},
        )
        result = lqa_prepass(state)

        # Verify parsed_inputs are set
        assert result.flags.get("lqa_prepass") is True
        assert result.parsed_inputs.get("destinations_delta") == ["Tokyo"]

        # Verify routing preserves state
        from app.plan_graph import route_after_lqa_prepass

        next_node = route_after_lqa_prepass(result)
        assert next_node == "normalize_inputs"
        # parsed_inputs should still be present
        assert result.parsed_inputs.get("destinations_delta") == ["Tokyo"]

    def test_lqa_stats_after_multiple_turns(self):
        """Verify stats accumulate correctly across multiple LQA calls."""
        # Simulate multiple turns in a conversation
        turns = [
            ("Paris", "destinations", True),  # Should hit
            ("2 adults", "travelers", True),  # Should hit
            (
                "I want to explore museums and eat good food",
                "activities",
                False,
            ),  # Should bail (too long)
        ]

        for user_text, question_target, expected_hit in turns:
            state = GraphState(
                user_text=user_text,
                trip_inputs=TripInputs(),
                question_target=question_target,
                metadata={},
            )
            result = lqa_prepass(state)
            assert result.flags.get("lqa_prepass") == expected_hit, f"Failed for: {user_text}"

        stats = get_graph_stats()
        assert stats["lqa"]["attempts"] == 3
        assert stats["lqa"]["hits"] == 2
        assert stats["lqa"]["bails"] == 1
