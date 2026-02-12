"""
Tests for registry-gated feasibility checking.

These tests verify that the geographic feasibility layer correctly gates
on has_geographic_constraint from the specialist registry.
"""

from app.planner.nodes.vertical_specialist import check_feasibility
from app.planner.specialist_registry import get as get_specialist_config


class TestRegistryGatedFeasibility:
    """Test that feasibility respects registry has_geographic_constraint flag."""

    def test_diving_has_geographic_constraint(self):
        """Diving config should have geographic constraint enabled."""
        config = get_specialist_config("diving")
        assert config is not None
        assert config.has_geographic_constraint is True

    def test_skiing_has_geographic_constraint(self):
        """Skiing config should have geographic constraint enabled."""
        config = get_specialist_config("skiing")
        assert config is not None
        assert config.has_geographic_constraint is True

    def test_hiking_no_geographic_constraint(self):
        """Hiking should not have geographic constraint — feasible everywhere."""
        config = get_specialist_config("hiking")
        assert config is not None
        assert config.has_geographic_constraint is False

    def test_cycling_no_geographic_constraint(self):
        """Cycling should not have geographic constraint — feasible everywhere."""
        config = get_specialist_config("cycling")
        assert config is not None
        assert config.has_geographic_constraint is False

    def test_surfing_no_geographic_constraint(self):
        """Surfing should not have geographic constraint."""
        config = get_specialist_config("surfing")
        assert config is not None
        assert config.has_geographic_constraint is False


class TestCheckFeasibilityAutoFeasible:
    """Test that specialists without geographic constraint are auto-feasible."""

    async def test_hiking_always_feasible(self):
        """Hiking should be feasible everywhere (no LLM check)."""
        status, reason, alternative = await check_feasibility("hiking", "Chamonix")
        assert status == "feasible"
        assert reason is None

        status, reason, alternative = await check_feasibility("hiking", "Tokyo")
        assert status == "feasible"
        assert reason is None

    async def test_cycling_always_feasible(self):
        """Cycling should be feasible everywhere (no LLM check)."""
        status, reason, alternative = await check_feasibility("cycling", "Antarctica")
        assert status == "feasible"
        assert reason is None

    async def test_empty_destination_always_feasible(self):
        """Empty destination should be auto-feasible for any specialist."""
        status, reason, alternative = await check_feasibility("diving", "")
        assert status == "feasible"
        assert reason is None

    async def test_unknown_specialist_always_feasible(self):
        """Unknown specialist should be auto-feasible (no config)."""
        status, reason, alternative = await check_feasibility("unknown_sport", "Paris")
        assert status == "feasible"
        assert reason is None
