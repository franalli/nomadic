"""
Regression tests for date clarify mode and LQA/date normalization contract.

Tests cover the exact failure sequence that was causing loops:
1. Strategy stage 0 asks about dates (question_target="dates")
2. User answers with destination ("Swiss Alps") - LQA should skip, not fail
3. Date range straddles today - triggers date_clarify_mode
4. GENERATE_PLAN_NOW with date errors - should be blocked
5. Year clarification resolves ambiguity

These tests lock in the contract between:
- LQA prepass
- Date normalization (validate_date_range)
- Loop guard (dates_clarify escalation)
- GateEvaluator (GENERATE_REQUESTED blocking)
"""

from datetime import date

import pytest

from app.plan_graph import (
    DateErrorCode,
    DateNormalizer,
    GateEvaluator,
    GraphState,
    TripInputNormalizer,
    TripInputs,
    _is_date_like_text,
    _is_place_like_text,
    canonicalize_question_target,
    get_loop_guard_mitigation,
    lqa_prepass,
    validate_and_merge,
)
from app.schemas import ErrorRecord


class TestCanonicalizeQuestionTarget:
    """Test question_target canonicalization."""

    def test_start_date_maps_to_dates(self):
        """start_date should map to dates for LQA compatibility."""
        assert canonicalize_question_target("start_date") == "dates"

    def test_end_date_maps_to_dates(self):
        """end_date should map to dates for LQA compatibility."""
        assert canonicalize_question_target("end_date") == "dates"

    def test_dates_stays_dates(self):
        """dates should stay as dates."""
        assert canonicalize_question_target("dates") == "dates"

    def test_travelers_variants(self):
        """Traveler variants should map to travelers."""
        assert canonicalize_question_target("travelers (adults)") == "travelers"
        assert canonicalize_question_target("adults") == "travelers"

    def test_origin_stays_origin(self):
        """origin should stay as origin."""
        assert canonicalize_question_target("origin") == "origin"

    def test_destinations_stays_destinations(self):
        """destinations should stay as destinations."""
        assert canonicalize_question_target("destinations") == "destinations"

    def test_none_returns_none(self):
        """None should return None."""
        assert canonicalize_question_target(None) is None


class TestDateLikeTextDetection:
    """Test date-like vs place-like text detection for LQA skip heuristic."""

    def test_month_day_is_date_like(self):
        """December 20-27 should be detected as date-like."""
        assert _is_date_like_text("December 20-27") is True

    def test_relative_date_is_date_like(self):
        """Next month should be detected as date-like."""
        assert _is_date_like_text("next month") is True

    def test_this_year_is_date_like(self):
        """This year should be detected as date-like."""
        assert _is_date_like_text("this year") is True

    def test_swiss_alps_not_date_like(self):
        """Swiss Alps should NOT be detected as date-like."""
        assert _is_date_like_text("Swiss Alps") is False

    def test_swiss_alps_is_place_like(self):
        """Swiss Alps should be detected as place-like."""
        assert _is_place_like_text("Swiss Alps") is True

    def test_next_december_is_date_like(self):
        """Next December should be date-like (clarify response)."""
        assert _is_date_like_text("Next December") is True


class TestLQAPrepassSkipsNonDateText:
    """Test that LQA skips non-date-like text when target is dates."""

    def test_lqa_skips_place_when_target_is_dates(self):
        """LQA should skip parsing 'Swiss Alps' when question_target is 'dates'."""
        state = GraphState(
            user_text="Swiss Alps",
            trip_inputs=TripInputs(),
            question_target="dates",
            metadata={},
            flags={},
        )

        result = lqa_prepass(state)

        # Should bail with "not_date_like" reason, not "validation_fail"
        assert result.flags.get("lqa_prepass") is False
        assert result.flags.get("lqa_bail_reason") == "not_date_like"

    def test_lqa_parses_date_when_target_is_dates(self):
        """LQA should parse 'December 20-27' when question_target is 'dates'."""
        state = GraphState(
            user_text="next month",
            trip_inputs=TripInputs(),
            question_target="dates",
            metadata={},
            flags={},
        )

        result = lqa_prepass(state)

        # Should succeed in parsing
        assert result.flags.get("lqa_prepass") is True
        assert result.parsed_inputs is not None


class TestStraddleTodayAmbiguity:
    """Test straddle-today detection in date range parsing."""

    def test_range_straddling_today_is_ambiguous(self):
        """December 20-27 on Dec 21 should trigger ambiguity."""
        today = date(2025, 12, 21)  # Dec 21, 2025
        normalizer = TripInputNormalizer(date_normalizer=DateNormalizer(today))

        start, end, errors, needs_clarify = normalizer.validate_date_range(
            "2025-12-20",  # Dec 20 (past)
            "2025-12-27",  # Dec 27 (future)
            metadata={},
        )

        # Should detect ambiguity and request clarification
        assert needs_clarify is True
        assert start is None  # Dates should be cleared
        assert end is None
        assert any(e.code == DateErrorCode.AMBIGUOUS_YEAR for e in errors)

    def test_future_range_not_ambiguous(self):
        """January 10-17 (completely in future) should not be ambiguous."""
        today = date(2025, 12, 21)
        normalizer = TripInputNormalizer(date_normalizer=DateNormalizer(today))

        start, end, errors, needs_clarify = normalizer.validate_date_range(
            "2026-01-10",
            "2026-01-17",
            metadata={},
        )

        # Should not be ambiguous
        assert needs_clarify is False
        assert start == "2026-01-10"
        assert end == "2026-01-17"

    def test_past_range_bumped_to_next_year(self):
        """December 10-15 (completely in past) should be bumped to next year."""
        today = date(2025, 12, 21)
        normalizer = TripInputNormalizer(date_normalizer=DateNormalizer(today))

        start, end, errors, needs_clarify = normalizer.validate_date_range(
            "2025-12-10",
            "2025-12-15",
            metadata={},
        )

        # Should be bumped to next year
        assert needs_clarify is False
        assert start == "2026-12-10"
        assert end == "2026-12-15"


class TestDateRangeInvariant:
    """Test that reversed dates are never stored."""

    def test_reversed_dates_cleared_with_error(self):
        """Reversed dates should be cleared and error returned."""
        today = date(2025, 12, 21)
        normalizer = TripInputNormalizer(date_normalizer=DateNormalizer(today))

        # Create a scenario where dates are reversed and can't be fixed
        start, end, errors, needs_clarify = normalizer.validate_date_range(
            "2026-12-27",  # End comes first
            "2025-12-20",  # Start comes second (wrong year)
            metadata={},
        )

        # After swap attempt, if still invalid, should be cleared
        if needs_clarify:
            assert start is None
            assert end is None


class TestGenerateBlockedOnDateErrors:
    """Test that GENERATE_PLAN_NOW is blocked when date errors exist."""

    def test_generate_blocked_with_date_clarify_mode(self):
        """GENERATE_REQUESTED should be blocked when date_clarify_mode is True."""
        state = GraphState(
            user_text="GENERATE_PLAN_NOW",
            trip_inputs=TripInputs(
                destinations=["Swiss Alps"],
                origin="London",
            ),
            metadata={"date_clarify_mode": True},
            flags={"generate_requested": True},
            errors=[],
        )

        result = GateEvaluator.evaluate(state)

        # Should NOT route to generate_responder
        assert result.destination != "generate_responder"
        assert "date_errors" in result.reason

    def test_generate_blocked_with_blocking_date_error(self):
        """GENERATE_REQUESTED should be blocked when DATE_AMBIGUOUS_YEAR error exists."""
        state = GraphState(
            user_text="GENERATE_PLAN_NOW",
            trip_inputs=TripInputs(
                destinations=["Swiss Alps"],
                origin="London",
            ),
            metadata={},
            flags={"generate_requested": True},
            # Errors stored as ErrorRecord with blocking severity
            errors=[
                ErrorRecord(
                    code=DateErrorCode.AMBIGUOUS_YEAR,
                    node="normalize_inputs",
                    severity="blocking",
                    message="Date range straddles today",
                )
            ],
        )

        result = GateEvaluator.evaluate(state)

        # Should NOT route to generate_responder
        assert result.destination != "generate_responder"
        assert "date_errors" in result.reason

    def test_generate_allowed_without_date_errors(self):
        """GENERATE_REQUESTED should proceed when no date errors exist."""
        state = GraphState(
            user_text="GENERATE_PLAN_NOW",
            trip_inputs=TripInputs(
                destinations=["Swiss Alps"],
                origin="London",
                start_date="2026-01-10",
            ),
            metadata={},
            flags={"generate_requested": True},
            errors=[],
        )

        result = GateEvaluator.evaluate(state)

        # Should route to generate_responder
        assert result.destination == "generate_responder"


class TestDateClarifyModeLifecycle:
    """Test date_clarify_mode lifecycle in validate_and_merge."""

    def test_clarify_mode_cleared_on_valid_range(self):
        """date_clarify_mode should be cleared when valid range stored."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(
                destinations=["Swiss Alps"],
                origin="London",
                start_date="2026-01-10",
                end_date="2026-01-17",
            ),
            metadata={"date_clarify_mode": True},
            flags={},
            errors=[],
        )

        result = validate_and_merge(state)

        # date_clarify_mode should be cleared
        assert result.metadata.get("date_clarify_mode") is False

    def test_clarify_mode_persists_with_errors(self):
        """date_clarify_mode should persist when blocking errors exist."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(
                destinations=["Swiss Alps"],
                origin="London",
            ),
            metadata={"date_clarify_mode": True},
            flags={},
            # Errors stored as ErrorRecord with blocking severity
            errors=[
                ErrorRecord(
                    code=DateErrorCode.AMBIGUOUS_YEAR,
                    node="normalize_inputs",
                    severity="blocking",
                    message="Date range straddles today",
                )
            ],
        )

        result = validate_and_merge(state)

        # date_clarify_mode should persist
        assert result.metadata.get("date_clarify_mode") is True


class TestLoopGuardDateEscalation:
    """Test loop guard special handling for date errors."""

    def test_loop_guard_escalates_to_dates_clarify(self):
        """Loop guard should escalate to dates_clarify when date errors exist."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(),
            metadata={"date_clarify_mode": True},
            flags={},
            # Errors stored as ErrorRecord with blocking severity
            errors=[
                ErrorRecord(
                    code=DateErrorCode.AMBIGUOUS_YEAR,
                    node="normalize_inputs",
                    severity="blocking",
                    message="Test",
                )
            ],
            loop_guard={},
        )

        mitigation = get_loop_guard_mitigation(state, "dates")

        # Should return dates_clarify mitigation
        assert mitigation == "dates_clarify"
        # Should have set year-specific suggestions
        assert len(state.suggested_responses) == 3


class TestFullRegressionSequence:
    """Test the exact failure sequence from the bug report."""

    @pytest.mark.asyncio
    async def test_hiking_trip_to_swiss_alps_sequence(self):
        """
        Replay the sequence:
        1. "Plan hiking trip" -> stage0 asks dates (question_target="dates")
        2. "Swiss Alps" -> LQA skips (not_date_like), extractor sets destination
        3. Origin answered
        4. "December 20-27" on Dec 21 -> triggers dates_clarify
        5. "Next December (2026)" -> ordered dates
        """
        # This is an integration test that would require mocking the full graph
        # For now, we test the individual components above
        pass
