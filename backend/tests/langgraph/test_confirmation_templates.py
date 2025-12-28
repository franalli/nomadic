"""
Unit tests for P4.2 confirmation templates.

Tests:
- select_confirmation_template() function
- apply_confirmation_template() function
- Integration with specialist_main.py
"""

from app.plan_graph import GraphState, TripInputs
from app.planner.nodes.specialist.templates import (
    _get_extracted_value_for_field,
    apply_confirmation_template,
    select_confirmation_template,
)


def _make_test_state(
    trip_inputs: TripInputs | None = None,
    metadata: dict | None = None,
    user_text: str = "",
    **kwargs,
) -> GraphState:
    """Create a test GraphState with optional overrides."""
    state = GraphState(
        user_text=user_text,
        trip_inputs=trip_inputs or TripInputs(),
    )
    if metadata:
        state.metadata.update(metadata)
    for key, value in kwargs.items():
        setattr(state, key, value)
    return state


class TestSelectConfirmationTemplate:
    """Tests for select_confirmation_template function."""

    def test_returns_none_when_no_question_target(self):
        """Should return None when no question target is set."""
        state = _make_test_state()
        result = select_confirmation_template(state, None)
        assert result is None

    def test_multiple_destinations_without_multi_city_intent(self):
        """Should return multiple_destinations template when destinations > 1 without intent."""
        ti = TripInputs(destinations=["Paris", "Rome"], multi_city_intent=None)
        state = _make_test_state(trip_inputs=ti)

        result = select_confirmation_template(state, "destinations")

        assert result is not None
        assert result["template_type"] == "multiple_destinations"
        assert result["field"] == "destinations"
        assert "Paris" in result["destinations_list"]
        assert "Rome" in result["destinations_list"]
        assert result["first_dest"] == "Paris"

    def test_no_confirmation_for_single_destination(self):
        """Should return None for single destination."""
        ti = TripInputs(destinations=["Paris"])
        state = _make_test_state(trip_inputs=ti)

        result = select_confirmation_template(state, "destinations")

        assert result is None

    def test_no_confirmation_for_multi_city_intent_set(self):
        """Should return None when multi_city_intent is already set."""
        ti = TripInputs(destinations=["Paris", "Rome"], multi_city_intent="multi_city")
        state = _make_test_state(trip_inputs=ti)

        result = select_confirmation_template(state, "destinations")

        assert result is None

    def test_typo_detected_with_dict_suggestions(self):
        """Should return typo_detected template for typo suggestions dict."""
        metadata = {
            "extraction_confidence": {
                "typo_suggestions": {"Pris": "Paris"},
                "level": "low",
                "overall": 0.4,
            }
        }
        state = _make_test_state(metadata=metadata)

        result = select_confirmation_template(state, "destinations")

        assert result is not None
        assert result["template_type"] == "typo_detected"
        assert result["field"] == "destinations"
        assert result["user_input"] == "Pris"
        assert result["suggestion"] == "Paris"

    def test_typo_detected_with_list_suggestions(self):
        """Should return typo_detected template for typo suggestions list."""
        metadata = {
            "extraction_confidence": {
                "typo_suggestions": ["Paris"],
                "level": "low",
                "overall": 0.4,
            }
        }
        state = _make_test_state(metadata=metadata, user_text="Pris")

        result = select_confirmation_template(state, "destinations")

        assert result is not None
        assert result["template_type"] == "typo_detected"
        assert result["suggestion"] == "Paris"

    def test_low_confidence_with_extracted_value(self):
        """Should return low_confidence template for low confidence extractions."""
        ti = TripInputs(destinations=["Paris"])
        metadata = {
            "extraction_confidence": {
                "level": "low",
                "overall": 0.5,
            }
        }
        state = _make_test_state(trip_inputs=ti, metadata=metadata)

        result = select_confirmation_template(state, "destinations")

        assert result is not None
        assert result["template_type"] == "low_confidence"
        assert result["field"] == "destinations"
        assert result["extracted_value"] == "Paris"
        assert result["confidence"] == 0.5

    def test_no_low_confidence_for_high_confidence(self):
        """Should not return low_confidence template for high confidence."""
        ti = TripInputs(destinations=["Paris"])
        metadata = {
            "extraction_confidence": {
                "level": "high",
                "overall": 0.9,
            }
        }
        state = _make_test_state(trip_inputs=ti, metadata=metadata)

        result = select_confirmation_template(state, "destinations")

        assert result is None

    def test_no_low_confidence_for_very_low_confidence(self):
        """Should not return low_confidence template for very low confidence (<0.3)."""
        ti = TripInputs(destinations=["Paris"])
        metadata = {
            "extraction_confidence": {
                "level": "low",
                "overall": 0.2,
            }
        }
        state = _make_test_state(trip_inputs=ti, metadata=metadata)

        result = select_confirmation_template(state, "destinations")

        # Should not return low_confidence because overall < 0.3
        assert result is None


class TestGetExtractedValueForField:
    """Tests for _get_extracted_value_for_field helper."""

    def test_destinations_single(self):
        """Should return single destination."""
        ti = TripInputs(destinations=["Paris"])
        state = _make_test_state(trip_inputs=ti)

        result = _get_extracted_value_for_field(state, "destinations")

        assert result == "Paris"

    def test_destinations_multiple(self):
        """Should join multiple destinations."""
        ti = TripInputs(destinations=["Paris", "Rome", "Barcelona"])
        state = _make_test_state(trip_inputs=ti)

        result = _get_extracted_value_for_field(state, "destinations")

        assert result == "Paris, Rome, Barcelona"

    def test_origin(self):
        """Should return origin."""
        ti = TripInputs(origin="London")
        state = _make_test_state(trip_inputs=ti)

        result = _get_extracted_value_for_field(state, "origin")

        assert result == "London"

    def test_dates_with_start_and_end(self):
        """Should format date range."""
        ti = TripInputs(start_date="2025-01-15", end_date="2025-01-22")
        state = _make_test_state(trip_inputs=ti)

        result = _get_extracted_value_for_field(state, "dates")

        assert result == "2025-01-15 to 2025-01-22"

    def test_dates_with_start_only(self):
        """Should return start date only."""
        ti = TripInputs(start_date="2025-01-15")
        state = _make_test_state(trip_inputs=ti)

        result = _get_extracted_value_for_field(state, "dates")

        assert result == "2025-01-15"

    def test_travelers_adults_only(self):
        """Should format adults count."""
        ti = TripInputs(adults=2)
        state = _make_test_state(trip_inputs=ti)

        result = _get_extracted_value_for_field(state, "travelers")

        assert result == "2 adults"

    def test_travelers_single_adult(self):
        """Should format single adult."""
        ti = TripInputs(adults=1)
        state = _make_test_state(trip_inputs=ti)

        result = _get_extracted_value_for_field(state, "travelers")

        assert result == "1 adult"

    def test_travelers_with_children(self):
        """Should format adults and children."""
        ti = TripInputs(adults=2, children=2)
        state = _make_test_state(trip_inputs=ti)

        result = _get_extracted_value_for_field(state, "travelers")

        assert result == "2 adults and 2 children"

    def test_budget(self):
        """Should return budget (stored as float, returns as-is)."""
        ti = TripInputs(budget=5000.0)
        state = _make_test_state(trip_inputs=ti)

        result = _get_extracted_value_for_field(state, "budget")

        assert result == 5000.0

    def test_unknown_field(self):
        """Should return None for unknown field."""
        state = _make_test_state()

        result = _get_extracted_value_for_field(state, "unknown_field")

        assert result is None


class TestApplyConfirmationTemplate:
    """Tests for apply_confirmation_template function."""

    def test_apply_multiple_destinations_template(self):
        """Should apply multiple_destinations template to state."""
        ti = TripInputs(destinations=["Paris", "Rome"])
        state = _make_test_state(trip_inputs=ti)
        confirmation = {
            "template_type": "multiple_destinations",
            "field": "destinations",
            "destinations_list": "Paris, Rome",
            "first_dest": "Paris",
        }

        result = apply_confirmation_template(state, confirmation)

        assert result is True
        assert state.last_summary  # Should have a question
        assert "Paris" in state.last_summary or "Rome" in state.last_summary
        assert state.question_target == "destinations"
        assert state.metadata.get("confirmation_template_applied") == "multiple_destinations"
        assert state.metadata.get("from_template") is True

    def test_apply_typo_detected_template(self):
        """Should apply typo_detected template to state."""
        state = _make_test_state()
        confirmation = {
            "template_type": "typo_detected",
            "field": "destinations",
            "user_input": "Pris",
            "suggestion": "Paris",
        }

        result = apply_confirmation_template(state, confirmation)

        assert result is True
        assert state.last_summary
        # Should mention either the typo or suggestion
        assert "Pris" in state.last_summary or "Paris" in state.last_summary
        assert state.question_target == "destinations"

    def test_apply_low_confidence_template(self):
        """Should apply low_confidence template to state."""
        ti = TripInputs(destinations=["Paris"])
        state = _make_test_state(trip_inputs=ti)
        confirmation = {
            "template_type": "low_confidence",
            "field": "destinations",
            "extracted_value": "Paris",
            "confidence": 0.5,
        }

        result = apply_confirmation_template(state, confirmation)

        assert result is True
        assert state.last_summary
        assert "Paris" in state.last_summary
        assert state.question_target == "destinations"

    def test_returns_false_for_missing_template(self):
        """Should return False if template type doesn't exist."""
        state = _make_test_state()
        confirmation = {
            "template_type": "nonexistent_template_type",
            "field": "destinations",
        }

        result = apply_confirmation_template(state, confirmation)

        assert result is False

    def test_sets_suggested_responses(self):
        """Should set suggested responses from template."""
        ti = TripInputs(destinations=["Paris", "Rome"])
        state = _make_test_state(trip_inputs=ti)
        confirmation = {
            "template_type": "multiple_destinations",
            "field": "destinations",
            "destinations_list": "Paris, Rome",
            "first_dest": "Paris",
        }

        apply_confirmation_template(state, confirmation)

        assert state.suggested_responses
        assert len(state.suggested_responses) > 0

    def test_sets_response_provenance(self):
        """Should set response generation provenance."""
        ti = TripInputs(destinations=["Paris", "Rome"])
        state = _make_test_state(trip_inputs=ti)
        confirmation = {
            "template_type": "multiple_destinations",
            "field": "destinations",
            "destinations_list": "Paris, Rome",
            "first_dest": "Paris",
        }

        apply_confirmation_template(state, confirmation)

        assert state.metadata.get("response_generation_provenance") == "template"
        assert "confirm_template" in state.metadata.get("response_writer_node", "")


class TestConfirmationTemplateIntegration:
    """Integration tests for confirmation templates in the specialist flow."""

    def test_multiple_destinations_triggers_confirmation(self):
        """When multiple destinations without intent, should trigger confirmation."""
        ti = TripInputs(destinations=["Paris", "Rome"])
        metadata = {"extraction_confidence": {"level": "high", "overall": 0.9}}
        state = _make_test_state(trip_inputs=ti, metadata=metadata)

        confirmation = select_confirmation_template(state, "destinations")

        assert confirmation is not None
        assert confirmation["template_type"] == "multiple_destinations"

        # Apply and verify
        result = apply_confirmation_template(state, confirmation)
        assert result is True
        assert state.question_target == "destinations"

    def test_origin_typo_triggers_confirmation(self):
        """When origin has typo, should trigger confirmation."""
        ti = TripInputs(origin="Landon")  # Typo for London
        metadata = {
            "extraction_confidence": {
                "typo_suggestions": {"Landon": "London"},
                "level": "low",
                "overall": 0.4,
            }
        }
        state = _make_test_state(trip_inputs=ti, metadata=metadata)

        confirmation = select_confirmation_template(state, "origin")

        assert confirmation is not None
        assert confirmation["template_type"] == "typo_detected"
        assert confirmation["suggestion"] == "London"

    def test_no_confirmation_for_clear_high_confidence(self):
        """High confidence single destination should not trigger confirmation."""
        ti = TripInputs(destinations=["Paris"])
        metadata = {
            "extraction_confidence": {
                "level": "high",
                "overall": 0.95,
            }
        }
        state = _make_test_state(trip_inputs=ti, metadata=metadata)

        confirmation = select_confirmation_template(state, "destinations")

        # No confirmation needed for clear extraction
        assert confirmation is None
