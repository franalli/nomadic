"""
Tests for LLM-based feasibility checking.

These tests verify that the geographic feasibility layer correctly identifies
impossible activities (e.g., diving in landlocked Chamonix).
"""

from app.planner.nodes.vertical_specialist import check_feasibility


class TestHardcodedFeasibility:
    """Test hardcoded feasibility checks (fast path)."""

    def test_diving_in_switzerland_infeasible(self):
        """Diving should be infeasible in Switzerland (landlocked)."""
        status, reason, alternative = check_feasibility("diving", "Switzerland")
        assert status == "infeasible"
        assert "not available" in reason.lower()
        assert alternative is not None

    def test_diving_in_bali_feasible(self):
        """Diving should be feasible in Bali (coastal)."""
        status, reason, alternative = check_feasibility("diving", "Bali")
        assert status == "feasible"
        assert reason is None

    def test_skiing_in_bali_infeasible(self):
        """Skiing should be infeasible in Bali (tropical)."""
        status, reason, alternative = check_feasibility("skiing", "Bali")
        assert status == "infeasible"
        assert "not available" in reason.lower()

    def test_skiing_in_chamonix_feasible(self):
        """Skiing should be feasible in Chamonix (Alps)."""
        # Note: Chamonix might not be in hardcoded list but LLM should say feasible
        status, reason, alternative = check_feasibility("skiing", "Chamonix")
        # Could be "feasible" (from LLM) or might not be in hardcoded list
        assert status in ["feasible", "caveat"]


class TestCheckFeasibilityIntegration:
    """Test the full check_feasibility flow with LLM fallback."""

    def test_hiking_always_feasible(self):
        """Hiking should be feasible almost everywhere (no LLM check)."""
        status, reason, alternative = check_feasibility("hiking", "Chamonix")
        assert status == "feasible"

        status, reason, alternative = check_feasibility("hiking", "Tokyo")
        assert status == "feasible"
