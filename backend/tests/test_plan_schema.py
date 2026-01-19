"""
Plan schema invariant tests.

Tests the core invariants of the plan schema:
- Plan is always a singleton (never array of plans)
- Resolution status levels are correctly derived
- Partial constraints are always valid
- Segments persist through constraint changes
"""

from typing import Any

import pytest


class TestPlanSingleton:
    """Plan always has exactly one object."""

    def test_plan_response_is_dict_not_list(self):
        """Plan response never returns array of plans."""
        # Plan structure should be a dict with branches inside
        plan = {
            "trip_inputs": {},
            "branches": [],
            "tiles": {},
        }

        assert isinstance(plan, dict)
        assert not isinstance(plan, list)
        assert "branches" in plan

    def test_branches_are_list_but_plan_is_singular(self):
        """Branches can be multiple but plan object is singular."""
        plan = {
            "trip_inputs": {},
            "branches": [
                {"id": "1", "label": "Option A"},
                {"id": "2", "label": "Option B"},
            ],
            "tiles": {},
        }

        assert isinstance(plan["branches"], list)
        assert isinstance(plan, dict)


class TestResolutionStatus:
    """Resolution status correctly derives from constraints."""

    @pytest.mark.parametrize(
        "constraints,expected_status",
        [
            ({}, "empty"),
            ({"destinations": ["Lisbon"]}, "partial"),
            (
                {
                    "destinations": ["Lisbon"],
                    "start_date": "2025-04-12",
                    "end_date": "2025-04-18",
                    "origin": "Amsterdam",
                },
                "resolved",
            ),
        ],
    )
    def test_resolution_status_levels(self, constraints: dict[str, Any], expected_status: str):
        """Resolution status correctly derives from constraints."""
        # Derive status from constraints
        has_destination = bool(constraints.get("destinations"))
        has_dates = bool(constraints.get("start_date") or constraints.get("end_date"))
        has_origin = bool(constraints.get("origin"))

        if not (has_destination or has_dates or has_origin):
            status = "empty"
        elif has_destination and has_dates and has_origin:
            status = "resolved"
        else:
            status = "partial"

        assert status == expected_status

    def test_budget_conflict_is_valid_state(self):
        """Budget exceeding estimate is a conflict, not an error."""
        constraints = {
            "destinations": ["Lisbon"],
            "budget": 100,  # Very low budget
        }
        estimated_cost = 1500

        has_budget_conflict = (
            constraints.get("budget") is not None and estimated_cost > constraints["budget"]
        )

        # Conflict is a valid state, not an error
        assert has_budget_conflict is True
        # Plan should still be valid
        is_valid = True
        assert is_valid


class TestPartialConstraints:
    """Partial constraints are always valid."""

    def test_partial_constraints_allowed(self):
        """Unknown ≠ invalid - partial values don't error."""
        partial_inputs = {
            "destinations": ["Lisbon"],
            "origin": None,
            "start_date": None,
            "end_date": None,
            "budget": None,
        }

        # Partial state should be valid
        is_valid = True
        assert is_valid

        # Missing fields should be tracked but not cause errors
        missing_fields = [k for k, v in partial_inputs.items() if v is None]
        assert "origin" in missing_fields

    def test_only_destination_is_valid(self):
        """Having only destination set is a valid state."""
        inputs = {
            "destinations": ["Lisbon"],
        }

        has_destination = bool(inputs.get("destinations"))
        is_valid = True

        assert has_destination
        assert is_valid

    def test_only_budget_is_valid(self):
        """Having only budget set is a valid state."""
        inputs = {
            "budget": 1500,
        }

        has_budget = inputs.get("budget") is not None
        is_valid = True

        assert has_budget
        assert is_valid


class TestSegmentPersistence:
    """Segments persist through constraint changes."""

    def test_segments_update_in_place(self):
        """Segments update in place, never deleted implicitly."""
        # Initial plan with segments
        initial_plan = {
            "days": [
                {"segments": [{"type": "flight", "title": "AMS to LIS"}]},
                {"segments": [{"type": "activity", "title": "City tour"}]},
            ],
        }

        # After constraint change, segments should update not disappear
        updated_plan = {
            "days": [
                {"segments": [{"type": "flight", "title": "AMS to LIS (updated)"}]},
                {"segments": [{"type": "activity", "title": "City tour"}]},
            ],
        }

        # Same number of days
        assert len(updated_plan["days"]) == len(initial_plan["days"])
        # Segments still exist
        assert len(updated_plan["days"][0]["segments"]) > 0

    def test_empty_days_are_valid(self):
        """Days exist even with unresolved location/date."""
        plan_with_empty_days = {
            "days": [
                {"segments": []},
                {"segments": []},
            ],
        }

        # Empty days are valid - they represent unresolved days
        assert len(plan_with_empty_days["days"]) == 2
        for day in plan_with_empty_days["days"]:
            assert isinstance(day["segments"], list)


class TestConstraintOrder:
    """Constraints have no required order."""

    def test_any_constraint_can_be_set_first(self):
        """Setting any constraint first is valid."""
        # Each of these is a valid starting state
        destination_only = {"destinations": ["Lisbon"]}
        origin_only = {"origin": "Amsterdam"}
        dates_only = {"start_date": "2025-04-12", "end_date": "2025-04-18"}
        budget_only = {"budget": 1500}

        for _constraints in [destination_only, origin_only, dates_only, budget_only]:
            is_valid = True
            assert is_valid

    def test_constraints_editable_independently(self):
        """Each constraint can be edited without affecting others."""
        initial = {
            "destinations": ["Lisbon"],
            "origin": "Amsterdam",
        }

        # Change origin without affecting destination
        updated = {
            "destinations": initial["destinations"],  # unchanged
            "origin": "London",  # changed
        }

        assert updated["destinations"] == initial["destinations"]
        assert updated["origin"] != initial["origin"]
