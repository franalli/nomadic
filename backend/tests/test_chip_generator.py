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
    def test_discovery_chips_without_dates(self) -> None:
        """Dest but no dates, no strategy → discovery preference chips (not date chips)."""
        state = _make_state(trip_plan={"destination": "Bali"})
        chips = _generate_chips_from_state(state)
        assert len(chips) == 4
        categories = {c["category"] for c in chips}
        assert "preference" in categories

    def test_date_chips_when_strategy_exists(self) -> None:
        """Dest, no dates, but strategy present → falls through to date chips."""
        state = _make_state(
            trip_plan={"destination": "Paris"},
            strategy_sections=[{"specialist_type": "local_expert"}],
        )
        chips = _generate_chips_from_state(state)
        categories = {c["category"] for c in chips}
        assert "date_prompt" in categories
        pill_chips = [c for c in chips if c.get("action_type") == "open_pill"]
        assert any(c["action_target"] == "dates" for c in pill_chips)


# =============================================================================
# Has destination + dates, no activities
# =============================================================================


class TestDestinationAndDatesNoActivities:
    def test_discovery_preference_chips(self) -> None:
        """When dest+dates are set but no categories/strategy, show discovery chips."""
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            }
        )
        chips = _generate_chips_from_state(state)
        assert len(chips) == 4
        categories = {c["category"] for c in chips}
        assert "preference" in categories

    def test_discovery_chips_skipped_when_strategy_exists(self) -> None:
        """With strategy_sections present, fall through to activity/departure chips."""
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            },
            strategy_sections=[{"specialist_type": "local_expert"}],
        )
        chips = _generate_chips_from_state(state)
        messages = [c["message"].lower() for c in chips]
        assert any("activit" in m or "departure" in m for m in messages)


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
        assert len(chips) <= 4
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

    def test_browse_activities_chip_present_without_categories(self) -> None:
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            },
            trip_settings={"activity_settings": {"categories": []}},
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

    def test_with_dest_dates_no_categories_shows_discovery(self) -> None:
        """Tiles present but no categories/strategy -> discovery preference chips."""
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
        categories = {c["category"] for c in chips}
        assert "preference" in categories


# =============================================================================
# Departure city personalization
# =============================================================================


class TestDepartureCityPersonalization:
    """Verify destination name appears in departure city chip across all paths."""

    def test_post_itinerary_personalizes_departure(self) -> None:
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
        dep_chips = [c for c in chips if "departure" in c["message"].lower()]
        assert dep_chips, "Expected a departure city chip"
        assert "Bali" in dep_chips[0]["message"]

    def test_has_tiles_no_itinerary_personalizes_departure(self) -> None:
        """With strategy_sections, tiles path personalizes departure chip."""
        state = _make_state(
            trip_plan={
                "destination": "Tokyo",
                "start_date": "2026-04-01",
                "end_date": "2026-04-07",
            },
            tiles={"hotels": [{"id": "h1"}]},
            strategy_sections=[{"specialist_type": "local_expert"}],
        )
        chips = _generate_chips_from_state(state)
        dep_chips = [c for c in chips if "departure" in c["message"].lower()]
        assert dep_chips, "Expected a departure city chip"
        assert "Tokyo" in dep_chips[0]["message"]

    def test_dest_dates_no_activities_shows_discovery(self) -> None:
        """Without strategy, dest+dates+no categories -> discovery chips."""
        state = _make_state(
            trip_plan={
                "destination": "Paris",
                "start_date": "2026-05-01",
                "end_date": "2026-05-07",
            },
        )
        chips = _generate_chips_from_state(state)
        categories = {c["category"] for c in chips}
        assert "preference" in categories


# =============================================================================
# Must-dos injection from local expert
# =============================================================================


class TestMustDosInjection:
    """Verify local expert must_dos inject as contextual chips post-itinerary.

    The must_dos gate fires when ``len(chips) < 3``. With origin+budget set,
    only 2 standard chips are generated (Browse + Change hotel), leaving room.
    """

    _BASE_PLAN = {
        "destination": "Bali",
        "start_date": "2026-03-01",
        "end_date": "2026-03-07",
        "origin": "San Francisco",
        "budget": 5000,
    }

    def _local_expert_section(self, must_dos: list) -> dict:
        return {
            "id": "strategy_local_expert",
            "specialist_type": "local_expert",
            "title": "Bali Trip Overview",
            "must_dos": must_dos,
        }

    def test_must_do_string_appears_in_chips(self) -> None:
        state = _make_state(
            trip_plan=self._BASE_PLAN,
            trip_settings={"activity_settings": {"categories": ["diving"]}},
            day_cards=[{"day": 1}],
            strategy_sections=[self._local_expert_section(["Visit Uluwatu Temple"])],
        )
        chips = _generate_chips_from_state(state)
        messages = [c["message"] for c in chips]
        assert "Visit Uluwatu Temple" in messages

    def test_up_to_two_must_dos_injected(self) -> None:
        state = _make_state(
            trip_plan=self._BASE_PLAN,
            trip_settings={"activity_settings": {"categories": ["diving"]}},
            day_cards=[{"day": 1}],
            strategy_sections=[
                self._local_expert_section(["Visit Uluwatu Temple", "Try Nasi Goreng"])
            ],
        )
        chips = _generate_chips_from_state(state)
        messages = [c["message"] for c in chips]
        assert "Visit Uluwatu Temple" in messages
        assert "Try Nasi Goreng" in messages

    def test_must_do_over_60_chars_skipped(self) -> None:
        long_text = "A" * 61
        state = _make_state(
            trip_plan=self._BASE_PLAN,
            trip_settings={"activity_settings": {"categories": ["diving"]}},
            day_cards=[{"day": 1}],
            strategy_sections=[self._local_expert_section([long_text, "Short one"])],
        )
        chips = _generate_chips_from_state(state)
        messages = [c["message"] for c in chips]
        assert long_text not in messages
        assert "Short one" in messages

    def test_must_dos_only_from_local_expert_section(self) -> None:
        state = _make_state(
            trip_plan=self._BASE_PLAN,
            trip_settings={"activity_settings": {"categories": ["diving"]}},
            day_cards=[{"day": 1}],
            strategy_sections=[
                {"specialist_type": "diving", "must_dos": ["USAT Liberty Wreck"]},
            ],
        )
        chips = _generate_chips_from_state(state)
        messages = [c["message"] for c in chips]
        assert "USAT Liberty Wreck" not in messages

    def test_post_itinerary_cap_at_four(self) -> None:
        state = _make_state(
            trip_plan={**self._BASE_PLAN, "origin": None, "budget": None},
            trip_settings={"activity_settings": {"categories": ["diving"]}},
            day_cards=[{"day": 1}],
            strategy_sections=[self._local_expert_section(["Must do 1", "Must do 2"])],
        )
        chips = _generate_chips_from_state(state)
        # 3 standard chips (browse + departure + budget) + must_dos capped at 4
        assert len(chips) <= 4

    def test_must_dos_category_is_destination(self) -> None:
        state = _make_state(
            trip_plan=self._BASE_PLAN,
            trip_settings={"activity_settings": {"categories": ["diving"]}},
            day_cards=[{"day": 1}],
            strategy_sections=[self._local_expert_section(["Visit Tanah Lot"])],
        )
        chips = _generate_chips_from_state(state)
        dest_chips = [c for c in chips if c["category"] == "destination"]
        assert len(dest_chips) >= 1

    def test_must_dos_blocked_when_three_standard_chips(self) -> None:
        """When origin and budget are missing, 3 standard chips fill slots."""
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            },
            trip_settings={"activity_settings": {"categories": ["diving"]}},
            day_cards=[{"day": 1}],
            strategy_sections=[self._local_expert_section(["Should not appear"])],
        )
        chips = _generate_chips_from_state(state)
        messages = [c["message"] for c in chips]
        assert "Should not appear" not in messages
