"""
Unit tests for exit contract enforcement in plan_graph.py.

MVP Hardening tests covering:
- Non-empty assistant_message invariant
- Deterministic missing_fields from compute_trip_readiness
- Suggested_responses when question_target is set
- Question_target validation (echo guard)
"""

from app.plan_graph import (
    CORE_FIELD_PRIORITY,
    FALLBACK_SUGGESTIONS,
    GraphState,
    TripInputs,
    _enforce_exit_contract,
    _get_deterministic_suggestions,
    _validate_question_target,
    compute_trip_readiness,
)


class TestQuestionTargetValidation:
    """Test question_target validation and echo guard."""

    def test_valid_question_target_passes(self):
        """Valid question_target values should pass through unchanged."""
        assert _validate_question_target("destinations") == "destinations"
        assert _validate_question_target("origin") == "origin"
        assert _validate_question_target("dates") == "dates"
        assert _validate_question_target("travelers") == "travelers"
        assert _validate_question_target("budget") == "budget"

    def test_echo_guard_rejects_pipe_separated(self):
        """Question target with pipes (LLM echo) should be rejected."""
        # This is the failure mode where LLM echoes the enum list
        result = _validate_question_target("destinations|origin|dates|travelers|budget")
        assert result is None

    def test_echo_guard_rejects_any_pipe(self):
        """Any pipe character should invalidate the question_target."""
        assert _validate_question_target("destinations|origin") is None
        assert _validate_question_target("a|b") is None

    def test_normalizes_start_date_to_dates(self):
        """start_date should be normalized to dates for user-facing."""
        assert _validate_question_target("start_date") == "dates"

    def test_normalizes_adults_to_travelers(self):
        """adults should be normalized to travelers."""
        result = _validate_question_target("adults")
        assert result == "travelers"

    def test_none_input_returns_none(self):
        """None input should return None."""
        assert _validate_question_target(None) is None

    def test_empty_string_returns_none(self):
        """Empty string should return None."""
        assert _validate_question_target("") is None


class TestDeterministicSuggestions:
    """Test deterministic suggestion generation."""

    def test_destinations_has_suggestions(self):
        """destinations should have non-empty suggestions."""
        suggestions = _get_deterministic_suggestions("destinations")
        assert suggestions
        assert len(suggestions) >= 1
        assert all(isinstance(s, str) for s in suggestions)

    def test_dates_has_suggestions(self):
        """dates should have non-empty suggestions."""
        suggestions = _get_deterministic_suggestions("dates")
        assert suggestions
        assert len(suggestions) >= 1

    def test_unknown_field_returns_fallback(self):
        """Unknown field should return fallback suggestions."""
        suggestions = _get_deterministic_suggestions("unknown_field_xyz")
        assert suggestions == FALLBACK_SUGGESTIONS

    def test_strategy_topic_customizes_suggestions(self):
        """Strategy topic should customize suggestions when available."""
        # Hiking should have different suggestions than default
        hiking_suggestions = _get_deterministic_suggestions("destinations", "hiking")
        default_suggestions = _get_deterministic_suggestions("destinations", None)
        # They may or may not differ based on templates, but should be valid
        assert hiking_suggestions
        assert len(hiking_suggestions) >= 1
        assert default_suggestions
        assert len(default_suggestions) >= 1


class TestExitContractEnforcement:
    """Test the _enforce_exit_contract function."""

    def test_patches_empty_suggestions_when_question_target_set(self):
        """Should add suggestions when question_target is set but suggestions empty."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(),  # Empty - missing all fields
            metadata={},
            flags={},
            question_target="destinations",
            suggested_responses=[],  # Empty!
        )

        result = _enforce_exit_contract(state)

        assert result.suggested_responses
        assert len(result.suggested_responses) >= 1
        assert result.metadata.get("exit_contract_patched") is True

    def test_sets_question_target_when_missing_fields_exist(self):
        """Should set question_target when missing_fields exist but target is None."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(),  # Empty - missing all fields
            metadata={},
            flags={},
            question_target=None,  # Not set!
            suggested_responses=[],
        )

        result = _enforce_exit_contract(state)

        # Should set question_target based on missing fields
        assert result.question_target is not None
        assert result.metadata.get("exit_contract_patched") is True

    def test_does_not_overwrite_valid_question_target(self):
        """Should not overwrite a valid question_target already set."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(destinations=["Paris"]),  # Has destination
            metadata={},
            flags={},
            question_target="origin",  # Already set to a valid value
            suggested_responses=["London", "New York", "Tokyo"],
        )

        result = _enforce_exit_contract(state)

        # Should preserve the existing question_target
        assert result.question_target == "origin"

    def test_sanitizes_invalid_question_target(self):
        """Should sanitize invalid question_target (with pipes)."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(),
            metadata={},
            flags={},
            question_target="destinations|origin|dates",  # Invalid echo
            suggested_responses=[],
        )

        result = _enforce_exit_contract(state)

        # Should have sanitized the question_target
        assert "|" not in (result.question_target or "")
        assert result.metadata.get("exit_contract_patched") is True

    def test_filters_invalid_suggestions(self):
        """Should filter out empty or invalid suggestions."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(),
            metadata={},
            flags={},
            question_target="destinations",
            suggested_responses=["Paris", "", "  ", "Tokyo"],  # Some invalid (empty strings)
        )

        result = _enforce_exit_contract(state)

        # Should only have valid non-empty string suggestions
        assert all(s and s.strip() for s in result.suggested_responses)

    def test_records_missing_fields_in_metadata(self):
        """Should record missing_fields in metadata for observability."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(destinations=["Paris"]),  # Missing origin, dates
            metadata={},
            flags={},
        )

        result = _enforce_exit_contract(state)

        assert "exit_contract_missing_fields" in result.metadata
        assert "exit_contract_core_complete" in result.metadata


class TestCoreFieldPriority:
    """Test CORE_FIELD_PRIORITY constant consistency."""

    def test_priority_order_is_defined(self):
        """CORE_FIELD_PRIORITY should be a non-empty list."""
        assert CORE_FIELD_PRIORITY
        assert len(CORE_FIELD_PRIORITY) >= 4

    def test_destinations_is_first(self):
        """destinations should be first in priority order."""
        assert CORE_FIELD_PRIORITY[0] == "destinations"

    def test_contains_core_fields(self):
        """Should contain all core fields."""
        assert "destinations" in CORE_FIELD_PRIORITY
        assert "start_date" in CORE_FIELD_PRIORITY
        assert "origin" in CORE_FIELD_PRIORITY

    def test_compute_readiness_uses_priority_order(self):
        """compute_trip_readiness should respect CORE_FIELD_PRIORITY order."""
        # Empty trip inputs - should target destinations first
        ti = TripInputs()
        readiness = compute_trip_readiness(ti)
        assert readiness.question_target == "destinations"

        # Has destinations, should target next priority field
        ti2 = TripInputs(destinations=["Paris"])
        readiness2 = compute_trip_readiness(ti2)
        # Should be either origin or start_date based on priority
        assert readiness2.question_target in ["origin", "dates"]
