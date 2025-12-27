"""
Tests for trip style inference.

This module tests:
1. "no budget" does NOT trigger trip_style='budget'
2. "flexible budget" does NOT trigger trip_style='budget'
3. "backpacker trip" triggers trip_style='budget' (valid inference)
4. "cheap hostel" triggers trip_style='budget' (valid inference)
5. Other trip style keywords work correctly
"""


class TestTripStyleBudgetKeyword:
    """Test that 'budget' keyword is excluded from trip_style inference."""

    def test_no_budget_does_not_trigger_budget_style(self) -> None:
        """Test that 'no budget' does NOT set trip_style='budget'."""
        from app.plan_graph import _infer_trip_shape

        result = _infer_trip_shape("no budget")
        assert (
            result.get("trip_style") != "budget"
        ), "'no budget' should NOT trigger trip_style='budget'"

    def test_no_specific_budget_does_not_trigger_budget_style(self) -> None:
        """Test that 'no specific budget' does NOT set trip_style='budget'."""
        from app.plan_graph import _infer_trip_shape

        result = _infer_trip_shape("no specific budget")
        assert (
            result.get("trip_style") != "budget"
        ), "'no specific budget' should NOT trigger trip_style='budget'"

    def test_flexible_budget_does_not_trigger_budget_style(self) -> None:
        """Test that 'flexible budget' does NOT set trip_style='budget'."""
        from app.plan_graph import _infer_trip_shape

        result = _infer_trip_shape("flexible budget")
        assert (
            result.get("trip_style") != "budget"
        ), "'flexible budget' should NOT trigger trip_style='budget'"

    def test_open_budget_does_not_trigger_budget_style(self) -> None:
        """Test that 'open budget' does NOT set trip_style='budget'."""
        from app.plan_graph import _infer_trip_shape

        result = _infer_trip_shape("open budget")
        assert (
            result.get("trip_style") != "budget"
        ), "'open budget' should NOT trigger trip_style='budget'"


class TestTripStyleBudgetValidInference:
    """Test that unambiguous budget-travel keywords DO trigger trip_style='budget'."""

    def test_backpacker_triggers_budget_style(self) -> None:
        """Test that 'backpacker' sets trip_style='budget'."""
        from app.plan_graph import _infer_trip_shape

        result = _infer_trip_shape("backpacker trip")
        assert (
            result.get("trip_style") == "budget"
        ), "'backpacker' should trigger trip_style='budget'"

    def test_cheap_triggers_budget_style(self) -> None:
        """Test that 'cheap' sets trip_style='budget'."""
        from app.plan_graph import _infer_trip_shape

        result = _infer_trip_shape("cheap vacation")
        assert result.get("trip_style") == "budget", "'cheap' should trigger trip_style='budget'"

    def test_hostel_triggers_budget_style(self) -> None:
        """Test that 'hostel' sets trip_style='budget'."""
        from app.plan_graph import _infer_trip_shape

        result = _infer_trip_shape("hostel stay")
        assert result.get("trip_style") == "budget", "'hostel' should trigger trip_style='budget'"

    def test_affordable_triggers_budget_style(self) -> None:
        """Test that 'affordable' sets trip_style='budget'."""
        from app.plan_graph import _infer_trip_shape

        result = _infer_trip_shape("affordable trip")
        assert (
            result.get("trip_style") == "budget"
        ), "'affordable' should trigger trip_style='budget'"

    def test_low_cost_triggers_budget_style(self) -> None:
        """Test that 'low-cost' sets trip_style='budget'."""
        from app.plan_graph import _infer_trip_shape

        result = _infer_trip_shape("low-cost travel")
        assert result.get("trip_style") == "budget", "'low-cost' should trigger trip_style='budget'"


class TestTripStyleOtherStyles:
    """Test that other trip style keywords work correctly."""

    def test_hiking_triggers_adventure_style(self) -> None:
        """Test that 'hiking' sets trip_style='adventure_outdoors'."""
        from app.plan_graph import _infer_trip_shape

        result = _infer_trip_shape("hiking trip")
        assert result.get("trip_style") == "adventure_outdoors"

    def test_beach_triggers_relaxation_style(self) -> None:
        """Test that 'beach' sets trip_style='beach_relaxation'."""
        from app.plan_graph import _infer_trip_shape

        result = _infer_trip_shape("beach vacation")
        assert result.get("trip_style") == "beach_relaxation"

    def test_museum_triggers_cultural_style(self) -> None:
        """Test that 'museum' sets trip_style='cultural_historical'."""
        from app.plan_graph import _infer_trip_shape

        result = _infer_trip_shape("museum tour")
        assert result.get("trip_style") == "cultural_historical"

    def test_honeymoon_triggers_romantic_style(self) -> None:
        """Test that 'honeymoon' sets trip_style='romantic'."""
        from app.plan_graph import _infer_trip_shape

        result = _infer_trip_shape("honeymoon trip")
        assert result.get("trip_style") == "romantic"

    def test_family_triggers_family_style(self) -> None:
        """Test that 'family' sets trip_style='family'."""
        from app.plan_graph import _infer_trip_shape

        result = _infer_trip_shape("family vacation")
        assert result.get("trip_style") == "family"

    def test_luxury_triggers_luxury_style(self) -> None:
        """Test that 'luxury' sets trip_style='luxury'."""
        from app.plan_graph import _infer_trip_shape

        # Use "luxury hotel" instead of "luxury resort" as "resort" may trigger beach_relaxation
        result = _infer_trip_shape("luxury hotel in Paris")
        assert result.get("trip_style") == "luxury"


class TestTripStyleKeywordsSet:
    """Test the _TRIP_STYLE_KEYWORDS configuration."""

    def test_budget_keyword_not_in_budget_style(self) -> None:
        """Test that 'budget' is NOT in the budget style keywords."""
        from app.plan_graph import _TRIP_STYLE_KEYWORDS

        budget_keywords = _TRIP_STYLE_KEYWORDS.get("budget", set())
        assert "budget" not in budget_keywords, "'budget' should NOT be in budget style keywords"

    def test_unambiguous_budget_keywords_present(self) -> None:
        """Test that unambiguous budget keywords are in budget style."""
        from app.plan_graph import _TRIP_STYLE_KEYWORDS

        budget_keywords = _TRIP_STYLE_KEYWORDS.get("budget", set())
        expected_keywords = {"cheap", "affordable", "backpacker", "hostel", "low-cost"}
        assert expected_keywords.issubset(
            budget_keywords
        ), f"Expected {expected_keywords} to be in budget keywords"
