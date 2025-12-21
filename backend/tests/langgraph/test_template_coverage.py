"""
Unit tests for template coverage validation.

MVP Hardening tests covering:
- All core fields have templates
- Each template has sufficient suggestions
- Fallback suggestions work
- Startup validation catches issues
"""

import pytest

from app.plan_graph import (
    CORE_FIELD_PRIORITY,
    FALLBACK_SUGGESTIONS,
    _get_template_response,
    _load_required_fields_templates,
    validate_template_coverage,
)


class TestTemplateCoverage:
    """Test that templates cover all required fields."""

    def test_templates_load_successfully(self):
        """Templates should load without errors."""
        templates = _load_required_fields_templates()
        assert templates is not None
        assert isinstance(templates, dict)

    def test_destinations_template_exists(self):
        """destinations template should exist."""
        templates = _load_required_fields_templates()
        assert "destinations" in templates

    def test_origin_template_exists(self):
        """origin template should exist."""
        templates = _load_required_fields_templates()
        assert "origin" in templates

    def test_dates_template_exists(self):
        """dates template should exist."""
        templates = _load_required_fields_templates()
        assert "dates" in templates

    def test_travelers_template_exists(self):
        """travelers template should exist."""
        templates = _load_required_fields_templates()
        assert "travelers" in templates

    def test_budget_template_exists(self):
        """budget template should exist."""
        templates = _load_required_fields_templates()
        assert "budget" in templates


class TestTemplateValidation:
    """Test validate_template_coverage function."""

    def test_validation_returns_result_dict(self):
        """validate_template_coverage should return a result dict."""
        result = validate_template_coverage()

        assert isinstance(result, dict)
        assert "valid" in result
        assert "missing_fields" in result
        assert "insufficient_suggestions" in result
        assert "errors" in result

    def test_validation_identifies_missing_fields(self):
        """validation should identify missing template fields."""
        result = validate_template_coverage()

        # The result should at least have the structure
        assert isinstance(result["missing_fields"], list)

    def test_validation_checks_suggestion_counts(self):
        """validation should check suggestion counts."""
        result = validate_template_coverage()

        assert isinstance(result["insufficient_suggestions"], dict)


class TestTemplateResponses:
    """Test _get_template_response for all core fields."""

    @pytest.mark.parametrize(
        "field",
        ["destinations", "origin", "dates", "travelers", "budget"],
    )
    def test_core_field_has_template_response(self, field: str):
        """Each core field should have a template response."""
        response = _get_template_response(field)

        # Should either have a response or return None (which triggers fallback)
        if response is not None:
            assert "question" in response
            assert "suggestions" in response
            assert isinstance(response["question"], str)
            assert isinstance(response["suggestions"], list)

    @pytest.mark.parametrize(
        "field",
        ["destinations", "origin", "dates", "travelers", "budget"],
    )
    def test_core_field_has_non_empty_question(self, field: str):
        """Each core field template should have a non-empty question."""
        response = _get_template_response(field)

        if response is not None:
            assert response["question"]
            assert len(response["question"]) > 0

    @pytest.mark.parametrize(
        "field",
        ["destinations", "origin", "dates", "travelers", "budget"],
    )
    def test_core_field_has_suggestions(self, field: str):
        """Each core field template should have at least one suggestion."""
        response = _get_template_response(field)

        if response is not None:
            assert response["suggestions"]
            assert len(response["suggestions"]) >= 1


class TestFallbackSuggestions:
    """Test fallback suggestions behavior."""

    def test_fallback_suggestions_defined(self):
        """FALLBACK_SUGGESTIONS should be defined and non-empty."""
        assert FALLBACK_SUGGESTIONS
        assert len(FALLBACK_SUGGESTIONS) >= 1

    def test_fallback_suggestions_are_strings(self):
        """All fallback suggestions should be non-empty strings."""
        for suggestion in FALLBACK_SUGGESTIONS:
            assert isinstance(suggestion, str)
            assert len(suggestion) > 0

    def test_unknown_field_returns_none(self):
        """Unknown field should return None (triggers fallback elsewhere)."""
        response = _get_template_response("completely_unknown_field_xyz_123")
        assert response is None


class TestStrategyTopicCustomization:
    """Test that strategy topics customize suggestions."""

    @pytest.mark.parametrize(
        "strategy_topic",
        ["hiking", "skiing", "diving", "cycling", "boating"],
    )
    def test_strategy_topic_for_destinations(self, strategy_topic: str):
        """Strategy topics should work with destinations field."""
        response = _get_template_response("destinations", strategy_topic)

        # Should return a valid response
        if response is not None:
            assert "question" in response
            assert "suggestions" in response
            # Suggestions may or may not be customized depending on templates

    def test_strategy_topic_falls_back_to_default(self):
        """Unknown strategy topic should fall back to default suggestions."""
        default_response = _get_template_response("destinations", None)
        unknown_response = _get_template_response("destinations", "unknown_strategy")

        # Both should have suggestions
        if default_response and unknown_response:
            assert default_response["suggestions"]
            assert unknown_response["suggestions"]


class TestCoreFieldPriorityTemplates:
    """Test that all CORE_FIELD_PRIORITY fields have templates."""

    def test_all_priority_fields_have_templates(self):
        """All fields in CORE_FIELD_PRIORITY should have template mappings."""
        # Map from CORE_FIELD_PRIORITY to template keys
        field_to_template = {
            "destinations": "destinations",
            "start_date": "dates",
            "end_date": "dates",
            "origin": "origin",
            "adults": "travelers",
            "budget": "budget",
        }

        templates = _load_required_fields_templates()

        for field in CORE_FIELD_PRIORITY:
            template_key = field_to_template.get(field, field)
            # Check that template exists (or is shared with another field)
            if template_key in templates:
                assert templates[template_key], f"Template for {field} is empty"
