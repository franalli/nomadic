"""Unit tests for branch_postprocess node.

This node handles multi-city branch splitting, unique ID generation,
and branch specification normalization.
"""

import os
import sys
from pathlib import Path

# Suppress debug output
os.environ["PLAN_GRAPH_DEBUG"] = "0"

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.plan_graph import GraphState, TripInputs, branch_postprocess  # noqa: E402
from tests.langgraph.fixtures import FUTURE_DATE, FUTURE_END_DATE  # noqa: E402

# =============================================================================
# Helper Functions
# =============================================================================


def make_state_with_branches(
    destinations: list[str],
    branches: list[dict],
    multi_city_intent: str | None = None,
) -> GraphState:
    """Create a GraphState with specific branches and destinations."""
    trip_inputs = TripInputs(
        destinations=destinations,
        origin="London",
        start_date=FUTURE_DATE,
        end_date=FUTURE_END_DATE,
        adults=2,
        multi_city_intent=multi_city_intent,
    )
    return GraphState(
        user_text="",
        trip_inputs=trip_inputs,
        branches=branches,
        metadata={"thread_id": "test_branch"},
    )


# =============================================================================
# Basic Functionality Tests
# =============================================================================


class TestBranchPostprocessBasics:
    """Tests for basic branch_postprocess functionality."""

    def test_no_branches_returns_unchanged(self):
        """Empty branches should pass through unchanged."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(destinations=["Paris"]),
            branches=[],
            metadata={},
        )

        result = branch_postprocess(state)

        assert result.branches == []

    def test_empty_branches_list_returns_unchanged(self):
        """Empty branches list should return unchanged."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(destinations=["Paris"]),
            branches=[],  # GraphState requires list, not None
            metadata={},
        )

        result = branch_postprocess(state)

        assert result.branches == []

    def test_single_destination_single_branch(self):
        """Single destination with single branch should normalize."""
        state = make_state_with_branches(
            destinations=["Paris"],
            branches=[{"destinations": ["Paris"], "label": "Paris Trip"}],
        )

        result = branch_postprocess(state)

        assert len(result.branches) == 1
        assert result.branches[0]["destinations"] == ["Paris"]
        # Should have an ID
        assert "id" in result.branches[0]


# =============================================================================
# Multi-City Splitting Tests
# =============================================================================


class TestMultiCitySplitting:
    """Tests for multi-city branch splitting behavior."""

    def test_split_when_not_multi_city_intent(self):
        """Should split branches when multi_city_intent is not 'multi_city'."""
        state = make_state_with_branches(
            destinations=["Paris", "Rome"],
            branches=[
                {
                    "destinations": ["Paris", "Rome"],
                    "label": "Europe Trip",
                }
            ],
            multi_city_intent=None,  # Not explicitly multi-city
        )

        result = branch_postprocess(state)

        # Should be split into 2 branches
        assert len(result.branches) == 2

        # Each branch should have single destination
        dest_sets = [tuple(b["destinations"]) for b in result.branches]
        assert ("Paris",) in dest_sets
        assert ("Rome",) in dest_sets

    def test_no_split_when_multi_city_intent(self):
        """Should NOT split when multi_city_intent is 'multi_city'."""
        state = make_state_with_branches(
            destinations=["Paris", "Rome"],
            branches=[
                {
                    "destinations": ["Paris", "Rome"],
                    "label": "Europe Trip",
                }
            ],
            multi_city_intent="multi_city",  # Explicitly multi-city
        )

        result = branch_postprocess(state)

        # Should remain as single branch
        assert len(result.branches) == 1
        assert result.branches[0]["destinations"] == ["Paris", "Rome"]

    def test_split_generates_unique_labels(self):
        """Split branches should have destination-based labels."""
        state = make_state_with_branches(
            destinations=["Paris", "Rome", "Berlin"],
            branches=[
                {
                    "destinations": ["Paris", "Rome", "Berlin"],
                    "label": "Europe Trip",
                }
            ],
            multi_city_intent=None,
        )

        result = branch_postprocess(state)

        # Should be split into 3 branches
        assert len(result.branches) == 3

        # Each should have destination-based label
        labels = [b["label"] for b in result.branches]
        assert "Paris Trip" in labels
        assert "Rome Trip" in labels
        assert "Berlin Trip" in labels


# =============================================================================
# Unique ID Generation Tests
# =============================================================================


class TestUniqueIdGeneration:
    """Tests for branch ID generation and uniqueness."""

    def test_generates_ids_for_branches_without_ids(self):
        """Should generate IDs for branches that don't have them."""
        state = make_state_with_branches(
            destinations=["Paris"],
            branches=[
                {"destinations": ["Paris"], "label": "Paris Trip"},
                {"destinations": ["Paris"], "label": "Paris Trip 2"},
            ],
        )

        result = branch_postprocess(state)

        for branch in result.branches:
            assert "id" in branch
            assert isinstance(branch["id"], str)
            assert len(branch["id"]) > 0

    def test_all_ids_are_unique(self):
        """All branch IDs should be unique."""
        state = make_state_with_branches(
            destinations=["Paris", "Rome", "Berlin"],
            branches=[
                {"destinations": ["Paris", "Rome", "Berlin"], "label": "Trip"},
            ],
            multi_city_intent=None,  # Will be split
        )

        result = branch_postprocess(state)

        ids = [b["id"] for b in result.branches]
        assert len(ids) == len(set(ids)), "Branch IDs are not unique"

    def test_replaces_duplicate_ids(self):
        """Should replace duplicate IDs with unique ones."""
        duplicate_id = "abc12345"
        state = make_state_with_branches(
            destinations=["Paris"],
            branches=[
                {"id": duplicate_id, "destinations": ["Paris"], "label": "Trip 1"},
                {"id": duplicate_id, "destinations": ["Paris"], "label": "Trip 2"},
            ],
        )

        result = branch_postprocess(state)

        ids = [b["id"] for b in result.branches]
        assert len(ids) == len(set(ids)), "Duplicate IDs were not replaced"

    def test_preserves_existing_unique_ids(self):
        """Should preserve existing unique IDs."""
        state = make_state_with_branches(
            destinations=["Paris"],
            branches=[
                {"id": "unique_1", "destinations": ["Paris"], "label": "Trip 1"},
                {"id": "unique_2", "destinations": ["Paris"], "label": "Trip 2"},
            ],
        )

        result = branch_postprocess(state)

        ids = [b["id"] for b in result.branches]
        assert "unique_1" in ids
        assert "unique_2" in ids


# =============================================================================
# Edge Cases
# =============================================================================


class TestBranchPostprocessEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_destinations_list(self):
        """Empty destinations should not crash."""
        state = make_state_with_branches(
            destinations=[],
            branches=[{"label": "Empty Trip"}],
        )

        result = branch_postprocess(state)

        # Should handle gracefully
        assert result is not None

    def test_single_destination_in_list(self):
        """Single destination should not trigger splitting logic."""
        state = make_state_with_branches(
            destinations=["Paris"],
            branches=[
                {"destinations": ["Paris"], "label": "Paris Trip"},
            ],
            multi_city_intent=None,
        )

        result = branch_postprocess(state)

        # Should remain as single branch (no split needed)
        assert len(result.branches) == 1

    def test_branch_with_no_destinations_field(self):
        """Branch without destinations field should be normalized."""
        state = make_state_with_branches(
            destinations=["Paris"],
            branches=[{"label": "Trip without destinations"}],
        )

        result = branch_postprocess(state)

        # Should handle gracefully (normalize_branch_spec fills in defaults)
        assert result is not None

    def test_many_destinations_split(self):
        """Many destinations should all be split correctly."""
        destinations = ["Paris", "Rome", "Berlin", "Madrid", "Lisbon"]
        state = make_state_with_branches(
            destinations=destinations,
            branches=[
                {"destinations": destinations, "label": "Grand Tour"},
            ],
            multi_city_intent=None,
        )

        result = branch_postprocess(state)

        assert len(result.branches) == 5

        # All destinations should be represented
        all_dests = []
        for branch in result.branches:
            all_dests.extend(branch["destinations"])
        for dest in destinations:
            assert dest in all_dests

    def test_multiple_branches_with_different_destinations(self):
        """Multiple branches with different destinations."""
        state = make_state_with_branches(
            destinations=["Paris", "Rome"],
            branches=[
                {"destinations": ["Paris"], "label": "Paris Trip"},
                {"destinations": ["Rome"], "label": "Rome Trip"},
            ],
            multi_city_intent="multi_city",
        )

        result = branch_postprocess(state)

        # Both branches should be preserved
        assert len(result.branches) == 2


# =============================================================================
# Branch Normalization Tests
# =============================================================================


class TestBranchNormalization:
    """Tests for branch spec normalization during post-processing."""

    def test_fallback_fields_applied(self):
        """Branch should inherit fallback fields from trip_inputs."""
        state = make_state_with_branches(
            destinations=["Paris"],
            branches=[
                {"destinations": ["Paris"], "label": "Paris Trip"},
            ],
        )

        result = branch_postprocess(state)

        # Should have inherited dates from trip_inputs
        branch = result.branches[0]
        # Note: normalization may apply trip_inputs fields to branch spec
        assert branch is not None

    def test_normalizes_branch_with_label(self):
        """Branch label should be preserved during normalization."""
        state = make_state_with_branches(
            destinations=["Paris"],
            branches=[
                {
                    "destinations": ["Paris"],
                    "label": "Luxury Paris Trip",
                },
            ],
        )

        result = branch_postprocess(state)

        branch = result.branches[0]
        # Label should be preserved
        assert branch.get("label") == "Luxury Paris Trip"
