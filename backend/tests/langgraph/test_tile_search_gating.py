"""
Unit tests for tile search gating in plan_graph.py.

MVP Hardening tests covering:
- should_run_tile_search prerequisites check
- needs_tiles intent and booking_types check
- Tile search blocked when core fields missing
- Cache behavior
"""

import pytest

from app.plan_graph import (
    GraphState,
    TripInputs,
    clear_tile_cache,
    needs_tiles,
    should_run_tile_search,
)


class TestShouldRunTileSearch:
    """Test should_run_tile_search prerequisite checks."""

    def test_returns_false_for_non_tile_intent(self):
        """Non-tile intents should not trigger tile search."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                start_date="2026-01-15",
                origin="London",
            ),
            metadata={},
            flags={},
        )

        assert should_run_tile_search(state, "transport") is False
        assert should_run_tile_search(state, "required_fields") is False
        assert should_run_tile_search(state, "general") is False

    def test_returns_true_for_tile_intents_with_prerequisites(self):
        """Tile intents with all prerequisites should return True."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                start_date="2026-01-15",
                origin="London",  # Required for flights
            ),
            metadata={},
            flags={},
        )

        assert should_run_tile_search(state, "hotels") is True
        assert should_run_tile_search(state, "activities") is True
        assert should_run_tile_search(state, "flights") is True

    def test_returns_false_when_destinations_missing(self):
        """Should return False when destinations are missing."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(
                start_date="2026-01-15",
                origin="London",
            ),
            metadata={},
            flags={},
        )

        assert should_run_tile_search(state, "hotels") is False
        assert should_run_tile_search(state, "activities") is False

    def test_returns_false_when_start_date_missing(self):
        """Should return False when start_date is missing."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
            ),
            metadata={},
            flags={},
        )

        assert should_run_tile_search(state, "hotels") is False
        assert should_run_tile_search(state, "activities") is False

    def test_flights_requires_origin(self):
        """Flights should require origin in addition to destinations and dates."""
        # Without origin
        state_no_origin = GraphState(
            user_text="test",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                start_date="2026-01-15",
            ),
            metadata={},
            flags={},
        )
        assert should_run_tile_search(state_no_origin, "flights") is False

        # With origin
        state_with_origin = GraphState(
            user_text="test",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                start_date="2026-01-15",
                origin="London",
            ),
            metadata={},
            flags={},
        )
        assert should_run_tile_search(state_with_origin, "flights") is True


class TestNeedsTiles:
    """Test needs_tiles intent and booking_types check."""

    def test_returns_false_for_non_tile_intent(self):
        """Non-tile intents should not need tiles."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(booking_types={"hotels": True}),
            metadata={},
            flags={},
        )

        assert needs_tiles("transport", state) is False
        assert needs_tiles("general", state) is False

    def test_returns_true_when_booking_type_enabled(self):
        """Should return True when booking_type for that domain is enabled."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(booking_types={"hotels": True}),
            metadata={},
            flags={},
        )

        assert needs_tiles("hotels", state) is True

    def test_returns_false_when_booking_type_disabled(self):
        """Should return False when booking_type disabled and no option signals."""
        state = GraphState(
            user_text="Just exploring",
            trip_inputs=TripInputs(booking_types={"hotels": False}),
            metadata={},
            flags={},
        )

        assert needs_tiles("hotels", state) is False

    def test_returns_true_with_option_signals_in_text(self):
        """Should return True when user text contains option signals."""
        state = GraphState(
            user_text="Show me hotel options",
            trip_inputs=TripInputs(booking_types={}),  # No booking types set
            metadata={},
            flags={},
        )

        assert needs_tiles("hotels", state) is True

    @pytest.mark.parametrize(
        "user_text",
        [
            "Show me options",
            "What are the prices?",
            "I want to book a hotel",
            "Check availability",
            "Find me something",
            "Compare hotels",
            "Recommend a place",
        ],
    )
    def test_option_signals_detected(self, user_text: str):
        """Various option signal phrases should trigger needs_tiles."""
        state = GraphState(
            user_text=user_text,
            trip_inputs=TripInputs(booking_types={}),
            metadata={},
            flags={},
        )

        assert needs_tiles("hotels", state) is True


class TestTileCache:
    """Test tile cache behavior."""

    def test_clear_tile_cache_returns_count(self):
        """clear_tile_cache should return count of cleared entries."""
        # Clear any existing cache first
        clear_tile_cache()

        # Clear empty cache should return 0
        count = clear_tile_cache()
        assert count == 0

    def test_clear_tile_cache_clears_entries(self):
        """clear_tile_cache should actually clear the cache."""
        # Clear and verify empty
        clear_tile_cache()
        count = clear_tile_cache()
        assert count == 0


class TestTileSearchBlockedWithoutCore:
    """Test that tile search is blocked when core fields are missing."""

    def test_all_intents_blocked_without_destinations(self):
        """All tile intents should be blocked without destinations."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(start_date="2026-01-15", origin="London"),
            metadata={},
            flags={},
        )

        for intent in ["hotels", "activities", "flights"]:
            assert should_run_tile_search(state, intent) is False

    def test_all_intents_blocked_without_dates(self):
        """All tile intents should be blocked without dates."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(destinations=["Paris"], origin="London"),
            metadata={},
            flags={},
        )

        for intent in ["hotels", "activities", "flights"]:
            assert should_run_tile_search(state, intent) is False
