import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.plan_graph import TripInputs, _normalize_multi_city_intent  # noqa: E402


@pytest.mark.parametrize(
    "text, expected",
    [
        ("one trip", "multi_city"),
        ("multi-city", "multi_city"),
        ("do it all together", "multi_city"),
        ("visit both", "multi_city"),
        ("compare destinations", "separate"),
        ("separate trips", "separate"),
        ("make them separate", None),
        (None, None),
        ("", None),
    ],
)
def test_normalize_multi_city_intent(text: str | None, expected: str | None) -> None:
    assert _normalize_multi_city_intent(text) == expected


class TestMultiCityIntentIntegration:
    """Integration tests for multi-city intent with TripInputs."""

    def test_multi_city_intent_default_is_none(self):
        """Default multi_city_intent should be None."""
        ti = TripInputs(destinations=["Rome", "Paris"])
        assert ti.multi_city_intent is None

    def test_multi_city_intent_set_to_multi_city(self):
        """multi_city_intent='multi_city' means visit all destinations in one trip (AND)."""
        ti = TripInputs(destinations=["Rome", "Paris", "Barcelona"], multi_city_intent="multi_city")
        assert ti.multi_city_intent == "multi_city"
        # User wants: Rome AND Paris AND Barcelona in one trip

    def test_multi_city_intent_set_to_separate(self):
        """multi_city_intent='separate' means compare destinations as separate trips (OR)."""
        ti = TripInputs(destinations=["Rome", "Paris"], multi_city_intent="separate")
        assert ti.multi_city_intent == "separate"
        # User wants: Rome OR Paris (compare options)

    @pytest.mark.parametrize(
        "user_phrase, expected_intent",
        [
            # Phrases that should trigger multi_city (AND logic)
            ("I want to visit Rome and Paris in one trip", "multi_city"),
            ("Plan a multi-city itinerary for Tokyo and Kyoto", "multi_city"),
            ("I want to do it all together", "multi_city"),
            ("Can I visit both cities?", "multi_city"),
            # Phrases that should trigger separate (OR logic)
            ("compare destinations", "separate"),
            ("compare them", "separate"),
            ("Show me separate trips to each city", "separate"),
            # Phrases that don't clearly indicate intent
            ("I want to go to Rome", None),
            ("Flying to Paris next week", None),
        ],
    )
    def test_intent_extraction_from_phrases(self, user_phrase: str, expected_intent: str | None):
        """Test that various user phrases correctly extract multi-city intent."""
        result = _normalize_multi_city_intent(user_phrase)
        assert result == expected_intent

    def test_intent_with_single_destination(self):
        """Intent can still be set with a single destination."""
        ti = TripInputs(destinations=["Rome"], multi_city_intent="multi_city")
        assert ti.multi_city_intent == "multi_city"
        assert len(ti.destinations) == 1

    def test_intent_changes_dont_affect_destinations(self):
        """Changing intent should not modify the destinations list."""
        ti = TripInputs(destinations=["Rome", "Paris"])
        original_destinations = ti.destinations.copy()

        ti.multi_city_intent = "multi_city"
        assert ti.destinations == original_destinations

        ti.multi_city_intent = "separate"
        assert ti.destinations == original_destinations
