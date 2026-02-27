"""
Unit tests for chip_generator.py — suggestion chip generation.

Tests template-based chip generation for different trip states:
- No destination (S0)
- Destination but no dates
- Destination + dates, no categories
- Post-itinerary (day_cards present)
- Blocking validation violations
- Tiles present but no itinerary
"""

from __future__ import annotations

from typing import Any, Dict

from app.planner.chip_generator import _chip, _generate_chips_from_state

# =============================================================================
# Helpers
# =============================================================================


def _make_state(**overrides: Any) -> Dict[str, Any]:
    """Build a minimal state dict for chip generation."""
    state: Dict[str, Any] = {
        "trip_plan": {},
        "trip_settings": {},
        "tiles": {},
        "turn_meta": {},
        "day_cards": [],
    }
    state.update(overrides)
    return state


# =============================================================================
# _chip helper
# =============================================================================


class TestChipHelper:
    def test_basic_chip_shape(self) -> None:
        chip = _chip("Test message", "cta", "core_fields", "map-pin")
        assert chip["message"] == "Test message"
        assert chip["chip_type"] == "cta"
        assert chip["category"] == "core_fields"
        assert chip["icon"] == "map-pin"
        assert chip["action_type"] == "send_message"
        assert chip["action_target"] is None

    def test_chip_with_action_target(self) -> None:
        chip = _chip(
            "Set dates",
            "cta",
            "date_prompt",
            "calendar",
            action_type="open_pill",
            action_target="dates",
        )
        assert chip["action_type"] == "open_pill"
        assert chip["action_target"] == "dates"


# =============================================================================
# No destination — S0 bootstrap
# =============================================================================


class TestNoDestination:
    def test_returns_destination_chip(self) -> None:
        state = _make_state()
        chips = _generate_chips_from_state(state)
        assert len(chips) <= 3
        messages = [c["message"] for c in chips]
        assert any("destination" in m.lower() for m in messages)

    def test_returns_max_3_chips(self) -> None:
        state = _make_state()
        chips = _generate_chips_from_state(state)
        assert len(chips) <= 3

    def test_includes_date_and_traveler_chips(self) -> None:
        state = _make_state()
        chips = _generate_chips_from_state(state)
        categories = {c["category"] for c in chips}
        assert "core_fields" in categories or "date_prompt" in categories


# =============================================================================
# Has destination, no dates
# =============================================================================


class TestDestinationNoDates:
    def test_suggests_date_options(self) -> None:
        state = _make_state(trip_plan={"destination": "Bali"})
        chips = _generate_chips_from_state(state)
        assert len(chips) <= 3
        categories = {c["category"] for c in chips}
        assert "date_prompt" in categories

    def test_includes_set_dates_pill(self) -> None:
        state = _make_state(trip_plan={"destination": "Paris"})
        chips = _generate_chips_from_state(state)
        pill_chips = [c for c in chips if c.get("action_type") == "open_pill"]
        assert any(c["action_target"] == "dates" for c in pill_chips)


# =============================================================================
# Has destination + dates, no activities
# =============================================================================


class TestDestinationAndDatesNoActivities:
    def test_suggests_activities(self) -> None:
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            }
        )
        chips = _generate_chips_from_state(state)
        messages = [c["message"].lower() for c in chips]
        assert any("activit" in m for m in messages)

    def test_suggests_departure_city(self) -> None:
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            }
        )
        chips = _generate_chips_from_state(state)
        messages = [c["message"].lower() for c in chips]
        assert any("departure" in m for m in messages)


# =============================================================================
# Post-itinerary (day_cards present)
# =============================================================================


class TestPostItinerary:
    def test_refinement_chips(self) -> None:
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            },
            trip_settings={"activity_settings": {"categories": ["diving"]}},
            day_cards=[{"day": 1, "activities": []}],
        )
        chips = _generate_chips_from_state(state)
        assert len(chips) <= 3
        assert len(chips) > 0

    def test_browse_activities_chip_present(self) -> None:
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            },
            trip_settings={"activity_settings": {"categories": ["diving"]}},
            day_cards=[{"day": 1}],
        )
        chips = _generate_chips_from_state(state)
        messages = [c["message"].lower() for c in chips]
        assert any("browse" in m or "activit" in m for m in messages)

    def test_no_origin_suggests_departure(self) -> None:
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            },
            trip_settings={"activity_settings": {"categories": ["diving"]}},
            day_cards=[{"day": 1}],
        )
        chips = _generate_chips_from_state(state)
        messages = [c["message"].lower() for c in chips]
        assert any("departure" in m for m in messages)

    def test_with_origin_suggests_hotel(self) -> None:
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
                "origin": "San Francisco",
            },
            trip_settings={"activity_settings": {"categories": ["diving"]}},
            day_cards=[{"day": 1}],
        )
        chips = _generate_chips_from_state(state)
        messages = [c["message"].lower() for c in chips]
        assert any("hotel" in m for m in messages)


# =============================================================================
# Blocking violations
# =============================================================================


class TestBlockingViolations:
    def test_violation_chips_take_priority(self) -> None:
        state = _make_state(
            trip_plan={"destination": "Bali"},
            turn_meta={
                "validation_result": {
                    "blocking_count": 1,
                    "violations": [
                        {
                            "code": "DATE_MISSING",
                            "suggested_action": "Please add travel dates",
                        }
                    ],
                }
            },
        )
        chips = _generate_chips_from_state(state)
        assert len(chips) >= 1
        messages = [c["message"] for c in chips]
        assert "Please add travel dates" in messages

    def test_date_violation_suggests_date_pill(self) -> None:
        state = _make_state(
            trip_plan={"destination": "Bali"},
            turn_meta={
                "validation_result": {
                    "blocking_count": 1,
                    "violations": [
                        {
                            "code": "DATE_EXCEEDS_CAPACITY",
                            "suggested_action": "Reduce trip duration",
                        }
                    ],
                }
            },
        )
        chips = _generate_chips_from_state(state)
        pill_chips = [c for c in chips if c.get("action_type") == "open_pill"]
        assert any(c["action_target"] == "dates" for c in pill_chips)

    def test_budget_violation_suggests_budget_pill(self) -> None:
        state = _make_state(
            trip_plan={"destination": "Bali"},
            turn_meta={
                "validation_result": {
                    "blocking_count": 1,
                    "violations": [
                        {
                            "code": "BUDGET_TOO_LOW",
                            "suggested_action": "Increase budget",
                        }
                    ],
                }
            },
        )
        chips = _generate_chips_from_state(state)
        pill_chips = [c for c in chips if c.get("action_type") == "open_pill"]
        assert any(c["action_target"] == "budget" for c in pill_chips)


# =============================================================================
# Tiles present, no itinerary
# =============================================================================


class TestTilesPresent:
    def test_with_dest_dates_categories_suggests_build(self) -> None:
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
                "activity_categories": ["diving"],
            },
            tiles={
                "hotels": [{"id": "h1"}],
                "activities": [{"id": "a1"}],
            },
        )
        chips = _generate_chips_from_state(state)
        messages = [c["message"].lower() for c in chips]
        assert any("build" in m or "itinerary" in m or "browse" in m for m in messages)

    def test_with_dest_dates_no_categories_suggests_activities(self) -> None:
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            },
            tiles={
                "hotels": [{"id": "h1"}],
            },
        )
        chips = _generate_chips_from_state(state)
        messages = [c["message"].lower() for c in chips]
        assert any("activit" in m for m in messages)
