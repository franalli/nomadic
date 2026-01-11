"""
Unit tests for _invoke_missing_fields_guard template path (P1 optimization).

Tests cover:
- Template path behavior (guard_use_templates=True)
- Question target selection priority
- date_clarify_mode enforcement
- blocking_errors enforcement
- Suggestion storage for LQA matching
- Metadata tracking
- Feature flag toggle behavior
"""

from unittest.mock import patch

import pytest

from app.config import settings
from app.plan_graph import GraphState, TripInputs
from app.planner.nodes.specialist_main import (
    _invoke_missing_fields_guard,
    _set_question_field_metadata,
)


class TestGuardTemplateConfig:
    """Test guard template configuration."""

    def test_guard_use_templates_enabled_by_default(self):
        """Verify guard_use_templates is True by default."""
        assert settings.guard_use_templates is True


class TestGuardTemplateQuestionTarget:
    """Test question target selection in template path."""

    @pytest.mark.asyncio
    async def test_asks_dates_when_dates_missing(self):
        """Should ask about dates when dates is in missing_fields."""
        state = GraphState(
            user_text="I want to book hotels",
            trip_inputs=TripInputs(destinations=["Paris"], origin="London"),
            metadata={},
            turn_number=1,
        )

        result = await _invoke_missing_fields_guard(state, ["dates", "adults"])

        assert result is True
        assert state.question_target == "dates"
        assert "travel" in state.last_summary.lower()  # "When are you looking to travel?"

    @pytest.mark.asyncio
    async def test_asks_destinations_when_destinations_missing(self):
        """Should ask about destinations when destinations is first missing field."""
        state = GraphState(
            user_text="I want flights",
            trip_inputs=TripInputs(origin="London", start_date="2025-06-15"),
            metadata={},
            turn_number=1,
        )

        result = await _invoke_missing_fields_guard(state, ["destinations"])

        assert result is True
        assert state.question_target == "destinations"
        assert "dreaming" in state.last_summary.lower() or "going" in state.last_summary.lower()

    @pytest.mark.asyncio
    async def test_asks_origin_when_origin_missing(self):
        """Should ask about origin when origin is first missing field."""
        state = GraphState(
            user_text="Hotels in Paris",
            trip_inputs=TripInputs(destinations=["Paris"], start_date="2025-06-15"),
            metadata={},
            turn_number=1,
        )

        result = await _invoke_missing_fields_guard(state, ["origin"])

        assert result is True
        assert state.question_target == "origin"
        assert "flying from" in state.last_summary.lower()

    @pytest.mark.asyncio
    async def test_priority_dates_over_destinations(self):
        """Dates should be asked before destinations (based on position in missing_fields)."""
        state = GraphState(
            user_text="I want to travel",
            trip_inputs=TripInputs(),
            metadata={},
            turn_number=1,
        )

        # When both dates and destinations missing, dates comes first in priority
        result = await _invoke_missing_fields_guard(state, ["dates", "destinations"])

        assert result is True
        assert state.question_target == "dates"


class TestGuardTemplateDateClarifyMode:
    """Test date_clarify_mode enforcement in template path."""

    @pytest.mark.asyncio
    async def test_forces_dates_in_date_clarify_mode(self):
        """Should force dates question when date_clarify_mode is active."""
        state = GraphState(
            user_text="I want hotels",
            trip_inputs=TripInputs(destinations=["Paris"]),
            metadata={"date_clarify_mode": True},
            turn_number=1,
        )

        # Even though destinations would normally come first, date_clarify_mode forces dates
        result = await _invoke_missing_fields_guard(state, ["destinations", "origin"])

        assert result is True
        assert state.question_target == "dates"

    @pytest.mark.asyncio
    async def test_forces_dates_with_blocking_errors(self):
        """Should force dates question when date_blocking_errors exist."""
        state = GraphState(
            user_text="I want hotels",
            trip_inputs=TripInputs(destinations=["Paris"]),
            metadata={"date_blocking_errors": [{"code": "PAST_DATE"}]},
            turn_number=1,
        )

        result = await _invoke_missing_fields_guard(state, ["destinations", "origin"])

        assert result is True
        assert state.question_target == "dates"


class TestGuardTemplateSuggestions:
    """Test suggestion generation in template path."""

    @pytest.mark.asyncio
    async def test_generates_destination_suggestions(self):
        """Should generate appropriate suggestions for destinations."""
        state = GraphState(
            user_text="I want to travel",
            trip_inputs=TripInputs(),
            metadata={},
            turn_number=1,
        )

        await _invoke_missing_fields_guard(state, ["destinations"])

        assert len(state.suggested_responses) == 3
        # Should be real destination suggestions
        assert any("Bali" in s or "Paris" in s or "Tokyo" in s for s in state.suggested_responses)

    @pytest.mark.asyncio
    async def test_generates_origin_suggestions(self):
        """Should generate appropriate suggestions for origin."""
        state = GraphState(
            user_text="Hotels",
            trip_inputs=TripInputs(destinations=["Paris"]),
            metadata={},
            turn_number=1,
        )

        await _invoke_missing_fields_guard(state, ["origin"])

        assert len(state.suggested_responses) == 3
        # Should be city suggestions
        assert any(
            "New York" in s or "London" in s or "Los Angeles" in s
            for s in state.suggested_responses
        )

    @pytest.mark.asyncio
    async def test_generates_date_suggestions(self):
        """Should generate appropriate suggestions for dates."""
        state = GraphState(
            user_text="Hotels",
            trip_inputs=TripInputs(destinations=["Paris"], origin="London"),
            metadata={},
            turn_number=1,
        )

        await _invoke_missing_fields_guard(state, ["dates"])

        assert len(state.suggested_responses) == 3
        # Should be date-like suggestions
        assert any(
            "month" in s.lower() or "december" in s.lower() or "january" in s.lower()
            for s in state.suggested_responses
        )


class TestGuardTemplateMetadata:
    """Test metadata tracking in template path."""

    @pytest.mark.asyncio
    async def test_sets_last_question_field(self):
        """Should set last_question_field metadata."""
        state = GraphState(
            user_text="Hotels",
            trip_inputs=TripInputs(),
            metadata={},
            turn_number=1,
        )

        await _invoke_missing_fields_guard(state, ["destinations"])

        assert state.metadata.get("last_question_field") == "destinations"

    @pytest.mark.asyncio
    async def test_maps_dates_to_start_date(self):
        """Should map 'dates' question_target to 'start_date' for last_question_field."""
        state = GraphState(
            user_text="Hotels",
            trip_inputs=TripInputs(destinations=["Paris"], origin="London"),
            metadata={},
            turn_number=1,
        )

        await _invoke_missing_fields_guard(state, ["dates"])

        # dates should map to start_date for LQA matching
        assert state.metadata.get("last_question_field") == "start_date"

    @pytest.mark.asyncio
    async def test_sets_last_response_turn(self):
        """Should set last_response_turn metadata."""
        state = GraphState(
            user_text="Hotels",
            trip_inputs=TripInputs(),
            metadata={},
            turn_number=5,
        )

        await _invoke_missing_fields_guard(state, ["destinations"])

        assert state.metadata.get("last_response_turn") == 5

    @pytest.mark.asyncio
    async def test_sets_guard_template_path_flag(self):
        """Should set guard_template_path metadata flag."""
        state = GraphState(
            user_text="Hotels",
            trip_inputs=TripInputs(),
            metadata={},
            turn_number=1,
        )

        await _invoke_missing_fields_guard(state, ["destinations"])

        assert state.metadata.get("guard_template_path") is True


class TestGuardTemplateAllFields:
    """Test all supported field types."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "field,expected_phrase",
        [
            ("destinations", "dreaming"),
            ("origin", "flying"),
            ("dates", "travel"),
            ("adults", "travelers"),
            ("budget", "budget"),
        ],
    )
    async def test_all_field_types_have_templates(self, field: str, expected_phrase: str):
        """Each supported field should have a template question."""
        state = GraphState(
            user_text="Help me plan",
            trip_inputs=TripInputs(),
            metadata={},
            turn_number=1,
        )

        result = await _invoke_missing_fields_guard(state, [field])

        assert result is True
        assert expected_phrase in state.last_summary.lower()


class TestGuardFeatureFlag:
    """Test feature flag toggle behavior."""

    @pytest.mark.asyncio
    async def test_template_path_when_flag_enabled(self):
        """Should use template path when guard_use_templates=True."""
        state = GraphState(
            user_text="Hotels",
            trip_inputs=TripInputs(),
            metadata={},
            turn_number=1,
        )

        with patch.object(settings, "guard_use_templates", True):
            result = await _invoke_missing_fields_guard(state, ["destinations"])

        assert result is True
        assert state.metadata.get("guard_template_path") is True

    @pytest.mark.asyncio
    async def test_llm_path_when_flag_disabled(self):
        """Should attempt LLM path when guard_use_templates=False."""
        state = GraphState(
            user_text="Hotels",
            trip_inputs=TripInputs(),
            metadata={},
            turn_number=1,
        )

        # Mock the LLM call to avoid actual API calls
        # can_call_llm is imported inside the function from app.plan_graph
        with patch.object(settings, "guard_use_templates", False):
            with patch("app.plan_graph.can_call_llm", return_value=False):
                # When LLM budget exhausted, should use llm_blocked_fallback
                result = await _invoke_missing_fields_guard(state, ["destinations"])

        assert result is True
        # Template path flag should NOT be set when using LLM path (even fallback)
        assert state.metadata.get("guard_template_path") is None


class TestGuardTemplateEdgeCases:
    """Test edge cases in template path."""

    @pytest.mark.asyncio
    async def test_handles_empty_missing_fields(self):
        """Should handle empty missing_fields gracefully."""
        state = GraphState(
            user_text="Hotels",
            trip_inputs=TripInputs(),
            metadata={},
            turn_number=1,
        )

        # Edge case: empty list (shouldn't happen in practice)
        result = await _invoke_missing_fields_guard(state, [])

        assert result is True
        # Should default to dates
        assert state.question_target == "dates"

    @pytest.mark.asyncio
    async def test_handles_unknown_field(self):
        """Should handle unknown field types with fallback."""
        state = GraphState(
            user_text="Hotels",
            trip_inputs=TripInputs(),
            metadata={},
            turn_number=1,
        )

        # Unknown field type
        result = await _invoke_missing_fields_guard(state, ["unknown_field"])

        assert result is True
        # Should still work with a generic question
        assert state.last_summary is not None
        assert len(state.last_summary) > 0

    @pytest.mark.asyncio
    async def test_handles_start_date_alias(self):
        """Should handle 'start_date' the same as 'dates'."""
        state = GraphState(
            user_text="Hotels",
            trip_inputs=TripInputs(destinations=["Paris"], origin="London"),
            metadata={},
            turn_number=1,
        )

        result = await _invoke_missing_fields_guard(state, ["start_date"])

        assert result is True
        assert state.question_target == "dates"


class TestSetQuestionFieldMetadata:
    """Test the _set_question_field_metadata helper function.

    This helper was extracted from duplicate code blocks in template and LLM paths
    to consolidate the target_to_field mapping logic.
    """

    def test_maps_destinations_to_destinations(self):
        """destinations should map to destinations."""
        state = GraphState(
            user_text="Test",
            trip_inputs=TripInputs(),
            metadata={},
            turn_number=1,
        )

        _set_question_field_metadata(state, "destinations")

        assert state.metadata["last_question_field"] == "destinations"

    def test_maps_origin_to_origin(self):
        """origin should map to origin."""
        state = GraphState(
            user_text="Test",
            trip_inputs=TripInputs(),
            metadata={},
            turn_number=1,
        )

        _set_question_field_metadata(state, "origin")

        assert state.metadata["last_question_field"] == "origin"

    def test_maps_dates_to_start_date(self):
        """dates should map to start_date for LQA matching."""
        state = GraphState(
            user_text="Test",
            trip_inputs=TripInputs(),
            metadata={},
            turn_number=1,
        )

        _set_question_field_metadata(state, "dates")

        assert state.metadata["last_question_field"] == "start_date"

    def test_maps_start_date_to_start_date(self):
        """start_date should map to start_date."""
        state = GraphState(
            user_text="Test",
            trip_inputs=TripInputs(),
            metadata={},
            turn_number=1,
        )

        _set_question_field_metadata(state, "start_date")

        assert state.metadata["last_question_field"] == "start_date"

    def test_unknown_field_passes_through(self):
        """Unknown fields should pass through unchanged."""
        state = GraphState(
            user_text="Test",
            trip_inputs=TripInputs(),
            metadata={},
            turn_number=1,
        )

        _set_question_field_metadata(state, "budget")

        assert state.metadata["last_question_field"] == "budget"

    def test_overwrites_existing_metadata(self):
        """Should overwrite any existing last_question_field value."""
        state = GraphState(
            user_text="Test",
            trip_inputs=TripInputs(),
            metadata={"last_question_field": "old_value"},
            turn_number=1,
        )

        _set_question_field_metadata(state, "origin")

        assert state.metadata["last_question_field"] == "origin"
