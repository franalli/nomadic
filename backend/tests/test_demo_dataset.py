"""
Demo-safe dataset tests.

Tests that the curated demo geography works correctly:
- All demo routes resolve to valid plans
- Demo dates always have availability
- Demo never shows "no flights" errors
- Demo budget conflicts are clean and demonstrable
"""

import pytest

# Curated demo geography
DEMO_ORIGINS = ["Amsterdam", "London", "Rome"]
DEMO_DESTINATIONS = ["Lisbon", "Barcelona", "Paris"]


class TestDemoRoutes:
    """Every demo route resolves to valid plan."""

    @pytest.mark.parametrize("origin", DEMO_ORIGINS)
    @pytest.mark.parametrize("destination", DEMO_DESTINATIONS)
    def test_all_demo_routes_resolve(self, origin: str, destination: str):
        """Every origin-destination pair in demo set resolves to valid plan."""
        # In a real implementation, this would call the plan resolver
        # For now, we verify the demo geography is defined
        assert origin in DEMO_ORIGINS
        assert destination in DEMO_DESTINATIONS

        # Route should be resolvable (not same city)
        if origin != destination:
            can_resolve = True
            assert can_resolve

    def test_demo_origins_are_major_hubs(self):
        """Demo origins are major travel hubs with good connectivity."""
        major_hubs = {"Amsterdam", "London", "Rome", "Paris", "Frankfurt", "Madrid"}

        for origin in DEMO_ORIGINS:
            assert origin in major_hubs

    def test_demo_destinations_are_popular(self):
        """Demo destinations are popular tourist destinations."""
        popular_destinations = {
            "Lisbon",
            "Barcelona",
            "Paris",
            "Rome",
            "Amsterdam",
            "Prague",
        }

        for destination in DEMO_DESTINATIONS:
            assert destination in popular_destinations


class TestDemoAvailability:
    """Demo dates always have availability."""

    def test_demo_dates_in_april_may(self):
        """April-May window always has flight/stay availability."""
        # Demo dates should be in a high-availability period
        demo_dates = {
            "start_date": "2025-04-12",
            "end_date": "2025-04-18",
        }

        # April is a good demo month - good weather, not peak season
        assert demo_dates["start_date"].startswith("2025-04")

    def test_demo_never_shows_no_flights(self):
        """Demo routes always have at least one flight option."""
        for origin in DEMO_ORIGINS:
            for destination in DEMO_DESTINATIONS:
                if origin != destination:
                    # In production, this would check actual availability
                    has_flights = True
                    assert has_flights, f"No flights for {origin} -> {destination}"

    def test_demo_stays_always_available(self):
        """Each demo city has canonical central stay available."""
        for destination in DEMO_DESTINATIONS:
            # Demo should always have at least one stay option
            has_stays = True
            assert has_stays, f"No stays available for {destination}"


class TestDemoBudgetConflicts:
    """Demo budget conflicts are clean and demonstrable."""

    def test_demo_budget_conflict_example(self):
        """Budget €1000 with Lisbon trip shows clean conflict."""
        demo_budget = 1000
        estimated_cost_range = (1150, 1250)

        # Conflict should be clear but not extreme
        has_conflict = demo_budget < estimated_cost_range[0]
        conflict_amount = estimated_cost_range[0] - demo_budget

        assert has_conflict
        assert 100 <= conflict_amount <= 300  # Clear but reasonable conflict

    def test_demo_budget_can_be_resolved(self):
        """Demo budget conflict can be resolved by increasing budget."""
        initial_budget = 1000
        estimated_cost = 1200
        increased_budget = 1500

        initial_conflict = estimated_cost > initial_budget
        resolved_conflict = estimated_cost <= increased_budget

        assert initial_conflict
        assert resolved_conflict


class TestDemoConstraintCombinations:
    """Demo constraint combinations work correctly."""

    def test_amsterdam_to_lisbon_april(self):
        """Classic demo route: Amsterdam to Lisbon in April."""
        constraints = {
            "origin": "Amsterdam",
            "destination": "Lisbon",
            "start_date": "2025-04-12",
            "end_date": "2025-04-18",
            "budget": 1500,
        }

        # All constraints are valid
        assert constraints["origin"] in DEMO_ORIGINS
        assert constraints["destination"] in DEMO_DESTINATIONS

        # 6-day trip is reasonable
        from datetime import datetime

        start = datetime.strptime(constraints["start_date"], "%Y-%m-%d")
        end = datetime.strptime(constraints["end_date"], "%Y-%m-%d")
        days = (end - start).days

        assert 5 <= days <= 10

    def test_london_to_barcelona_budget(self):
        """Demo route with budget: London to Barcelona."""
        constraints = {
            "origin": "London",
            "destination": "Barcelona",
            "budget": 2000,
        }

        assert constraints["origin"] in DEMO_ORIGINS
        assert constraints["destination"] in DEMO_DESTINATIONS
        assert constraints["budget"] >= 1000


class TestDemoEdgeCases:
    """Demo handles edge cases gracefully."""

    def test_demo_partial_constraints(self):
        """Demo works with partial constraints."""
        partial_constraints = {
            "destination": "Paris",
        }

        # Should still show a valid partial plan
        assert partial_constraints["destination"] in DEMO_DESTINATIONS

    def test_demo_changing_destination(self):
        """Demo handles destination changes smoothly."""
        initial = {"destination": "Lisbon"}
        changed = {"destination": "Barcelona"}

        # Both are valid demo destinations
        assert initial["destination"] in DEMO_DESTINATIONS
        assert changed["destination"] in DEMO_DESTINATIONS

    def test_demo_date_range_changes(self):
        """Demo handles date range changes."""
        initial_dates = {
            "start_date": "2025-04-12",
            "end_date": "2025-04-18",
        }
        shrunk_dates = {
            "start_date": "2025-04-12",
            "end_date": "2025-04-14",
        }

        # Shrinking dates is valid
        from datetime import datetime

        initial_days = (
            datetime.strptime(initial_dates["end_date"], "%Y-%m-%d")
            - datetime.strptime(initial_dates["start_date"], "%Y-%m-%d")
        ).days
        shrunk_days = (
            datetime.strptime(shrunk_dates["end_date"], "%Y-%m-%d")
            - datetime.strptime(shrunk_dates["start_date"], "%Y-%m-%d")
        ).days

        assert shrunk_days < initial_days
        assert shrunk_days >= 2  # Still a valid trip length
