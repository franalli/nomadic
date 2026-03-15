# backend/tests/test_itinerary_adapter.py
"""
Unit tests for itinerary_adapter.py — thin bridge from GraphState to ItineraryBuilder.

Tests cover:
- Precondition guards (missing start_date, end_date, empty sections)
- Correct ItineraryBuilderInput construction when all preconditions met
- user_pinned_tiles with preferred_day and priority
- Empty user_pinned_tiles handling
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

from app.planner.state.graph_state import GraphState, SpecialistConstraint, TripSettings
from app.services.itinerary_builder import (
    ItineraryBuilderInput,
    ItineraryResult,
    PreferenceOverrideInput,
)

# =============================================================================
# Helpers
# =============================================================================


def _make_state(
    *,
    destination: str = "Bali",
    start_date: Optional[str] = "2026-03-01",
    end_date: Optional[str] = "2026-03-07",
    sections: Optional[list] = None,
    pinned_tiles: Optional[Dict[str, Any]] = None,
    constraints: Optional[list] = None,
) -> GraphState:
    """Build a GraphState with sensible defaults for adapter tests."""
    state = GraphState()
    state.trip_plan.destination = destination
    state.trip_plan.start_date = start_date
    state.trip_plan.end_date = end_date

    if sections is not None:
        state.metadata["strategy_sections"] = sections
    else:
        state.metadata["strategy_sections"] = [{"id": "test", "specialist_type": "local_expert"}]

    if pinned_tiles is not None:
        state.metadata["user_pinned_tiles"] = pinned_tiles

    if constraints is not None:
        state.trip_plan.constraints = constraints

    # Ensure trip_settings exists so get_trip_settings works
    state.metadata["trip_settings"] = TripSettings().model_dump()

    return state


def _fake_result() -> ItineraryResult:
    """Return a minimal successful ItineraryResult."""
    return ItineraryResult(success=True, day_cards=[], conflicts=[], resolutions=[])


# =============================================================================
# Precondition guards
# =============================================================================


class TestPreconditionGuards:
    """build_itinerary_from_state returns None when preconditions are not met."""

    def test_returns_none_when_start_date_missing(self) -> None:
        state = _make_state(start_date=None)

        from app.planner.services.itinerary_adapter import build_itinerary_from_state

        result = build_itinerary_from_state(state)
        assert result is None

    def test_returns_none_when_end_date_missing(self) -> None:
        state = _make_state(end_date=None)

        from app.planner.services.itinerary_adapter import build_itinerary_from_state

        result = build_itinerary_from_state(state)
        assert result is None

    def test_returns_none_when_both_dates_missing(self) -> None:
        state = _make_state(start_date=None, end_date=None)

        from app.planner.services.itinerary_adapter import build_itinerary_from_state

        result = build_itinerary_from_state(state)
        assert result is None

    def test_returns_none_when_strategy_sections_empty(self) -> None:
        state = _make_state(sections=[])

        from app.planner.services.itinerary_adapter import build_itinerary_from_state

        result = build_itinerary_from_state(state)
        assert result is None

    def test_returns_none_when_strategy_sections_missing(self) -> None:
        state = _make_state()
        # Remove strategy_sections entirely
        state.metadata.pop("strategy_sections", None)

        from app.planner.services.itinerary_adapter import build_itinerary_from_state

        result = build_itinerary_from_state(state)
        assert result is None


# =============================================================================
# Successful builds
# =============================================================================


class TestSuccessfulBuild:
    """build_itinerary_from_state passes correct input to ItineraryBuilder."""

    @patch("app.planner.services.itinerary_adapter.ItineraryBuilder")
    @patch("app.planner.services.itinerary_adapter.flatten_tiles_to_id_map")
    def test_passes_correct_input_shape(
        self, mock_flatten: MagicMock, mock_builder_cls: MagicMock
    ) -> None:
        mock_flatten.return_value = {"tile_1": {"id": "tile_1", "type": "hotel"}}
        mock_instance = MagicMock()
        mock_instance.build.return_value = _fake_result()
        mock_builder_cls.return_value = mock_instance

        sections = [
            {"id": "strategy_local_expert", "specialist_type": "local_expert"},
            {"id": "specialist_diving", "specialist_type": "diving"},
        ]
        state = _make_state(destination="Bali", sections=sections)

        from app.planner.services.itinerary_adapter import build_itinerary_from_state

        result = build_itinerary_from_state(state)

        assert result is not None
        assert result.success is True
        mock_instance.build.assert_called_once()

        # Verify the ItineraryBuilderInput passed
        call_args = mock_instance.build.call_args
        builder_input = call_args[0][0]
        assert isinstance(builder_input, ItineraryBuilderInput)
        assert builder_input.start_date == "2026-03-01"
        assert builder_input.end_date == "2026-03-07"
        assert builder_input.destination == "Bali"
        assert builder_input.strategy_sections == sections
        assert builder_input.tiles == {"tile_1": {"id": "tile_1", "type": "hotel"}}

    @patch("app.planner.services.itinerary_adapter.ItineraryBuilder")
    @patch("app.planner.services.itinerary_adapter.flatten_tiles_to_id_map")
    def test_activities_off_passes_explicit_empty_category_list(
        self, mock_flatten: MagicMock, mock_builder_cls: MagicMock
    ) -> None:
        mock_flatten.return_value = {}
        mock_instance = MagicMock()
        mock_instance.build.return_value = _fake_result()
        mock_builder_cls.return_value = mock_instance

        state = _make_state()
        trip_settings = TripSettings()
        trip_settings.booking_types.activities = "off"
        trip_settings.activity_settings.categories = ["cultural"]
        state.metadata["trip_settings"] = trip_settings.model_dump()

        from app.planner.services.itinerary_adapter import build_itinerary_from_state

        build_itinerary_from_state(state)

        call_args = mock_instance.build.call_args
        builder_input = call_args[0][0]
        assert builder_input.activity_categories == []

    @patch("app.planner.services.itinerary_adapter.ItineraryBuilder")
    @patch("app.planner.services.itinerary_adapter.flatten_tiles_to_id_map")
    def test_empty_categories_pass_none_when_activities_not_off(
        self, mock_flatten: MagicMock, mock_builder_cls: MagicMock
    ) -> None:
        mock_flatten.return_value = {}
        mock_instance = MagicMock()
        mock_instance.build.return_value = _fake_result()
        mock_builder_cls.return_value = mock_instance

        state = _make_state()
        trip_settings = TripSettings()
        trip_settings.booking_types.activities = "suggested"
        trip_settings.activity_settings.categories = []
        state.metadata["trip_settings"] = trip_settings.model_dump()

        from app.planner.services.itinerary_adapter import build_itinerary_from_state

        build_itinerary_from_state(state)

        call_args = mock_instance.build.call_args
        builder_input = call_args[0][0]
        assert builder_input.activity_categories is None

    @patch("app.planner.services.itinerary_adapter.ItineraryBuilder")
    @patch("app.planner.services.itinerary_adapter.flatten_tiles_to_id_map")
    def test_no_preferences_when_no_pinned_tiles(
        self, mock_flatten: MagicMock, mock_builder_cls: MagicMock
    ) -> None:
        mock_flatten.return_value = {}
        mock_instance = MagicMock()
        mock_instance.build.return_value = _fake_result()
        mock_builder_cls.return_value = mock_instance

        state = _make_state()
        # No user_pinned_tiles in metadata

        from app.planner.services.itinerary_adapter import build_itinerary_from_state

        build_itinerary_from_state(state)

        call_args = mock_instance.build.call_args
        builder_input = call_args[0][0]
        assert builder_input.preferences is None

    @patch("app.planner.services.itinerary_adapter.ItineraryBuilder")
    @patch("app.planner.services.itinerary_adapter.flatten_tiles_to_id_map")
    def test_empty_pinned_tiles_gives_no_preferences(
        self, mock_flatten: MagicMock, mock_builder_cls: MagicMock
    ) -> None:
        mock_flatten.return_value = {}
        mock_instance = MagicMock()
        mock_instance.build.return_value = _fake_result()
        mock_builder_cls.return_value = mock_instance

        state = _make_state(pinned_tiles={})

        from app.planner.services.itinerary_adapter import build_itinerary_from_state

        build_itinerary_from_state(state)

        call_args = mock_instance.build.call_args
        builder_input = call_args[0][0]
        assert builder_input.preferences is None


# =============================================================================
# Pinned tiles → preferences
# =============================================================================


class TestPinnedTilesPreferences:
    """user_pinned_tiles metadata is converted to PreferenceOverrideInput."""

    @patch("app.planner.services.itinerary_adapter.ItineraryBuilder")
    @patch("app.planner.services.itinerary_adapter.flatten_tiles_to_id_map")
    def test_pinned_tiles_with_preferred_day_and_priority(
        self, mock_flatten: MagicMock, mock_builder_cls: MagicMock
    ) -> None:
        mock_flatten.return_value = {}
        mock_instance = MagicMock()
        mock_instance.build.return_value = _fake_result()
        mock_builder_cls.return_value = mock_instance

        pinned = {
            "tile_abc": {"preferred_day": 2, "priority": "high"},
            "tile_xyz": {"preferred_day": 5, "priority": "low"},
        }
        state = _make_state(pinned_tiles=pinned)

        from app.planner.services.itinerary_adapter import build_itinerary_from_state

        build_itinerary_from_state(state)

        call_args = mock_instance.build.call_args
        builder_input = call_args[0][0]
        prefs = builder_input.preferences
        assert prefs is not None
        assert isinstance(prefs, PreferenceOverrideInput)
        assert set(prefs.preferred_activity_ids) == {"tile_abc", "tile_xyz"}
        assert prefs.pinned_day_map == {"tile_abc": 2, "tile_xyz": 5}
        assert prefs.pinned_priority_map == {"tile_abc": "high", "tile_xyz": "low"}

    @patch("app.planner.services.itinerary_adapter.ItineraryBuilder")
    @patch("app.planner.services.itinerary_adapter.flatten_tiles_to_id_map")
    def test_pinned_tiles_without_preferred_day(
        self, mock_flatten: MagicMock, mock_builder_cls: MagicMock
    ) -> None:
        mock_flatten.return_value = {}
        mock_instance = MagicMock()
        mock_instance.build.return_value = _fake_result()
        mock_builder_cls.return_value = mock_instance

        pinned = {
            "tile_no_day": {"priority": "high"},
        }
        state = _make_state(pinned_tiles=pinned)

        from app.planner.services.itinerary_adapter import build_itinerary_from_state

        build_itinerary_from_state(state)

        call_args = mock_instance.build.call_args
        builder_input = call_args[0][0]
        prefs = builder_input.preferences
        assert prefs is not None
        assert prefs.preferred_activity_ids == ["tile_no_day"]
        # No preferred_day → not in day_map
        assert prefs.pinned_day_map == {}
        assert prefs.pinned_priority_map == {"tile_no_day": "high"}

    @patch("app.planner.services.itinerary_adapter.ItineraryBuilder")
    @patch("app.planner.services.itinerary_adapter.flatten_tiles_to_id_map")
    def test_pinned_tiles_default_priority_is_high(
        self, mock_flatten: MagicMock, mock_builder_cls: MagicMock
    ) -> None:
        mock_flatten.return_value = {}
        mock_instance = MagicMock()
        mock_instance.build.return_value = _fake_result()
        mock_builder_cls.return_value = mock_instance

        pinned = {
            "tile_no_prio": {},  # No priority key
        }
        state = _make_state(pinned_tiles=pinned)

        from app.planner.services.itinerary_adapter import build_itinerary_from_state

        build_itinerary_from_state(state)

        call_args = mock_instance.build.call_args
        builder_input = call_args[0][0]
        prefs = builder_input.preferences
        assert prefs is not None
        # Default priority is "high"
        assert prefs.pinned_priority_map == {"tile_no_prio": "high"}


class TestCanonicalConstraints:
    """TripPlan constraints are forwarded into the pure-Python builder."""

    @patch("app.planner.services.itinerary_adapter.ItineraryBuilder")
    @patch("app.planner.services.itinerary_adapter.flatten_tiles_to_id_map")
    def test_trip_plan_constraints_are_passed_to_builder(
        self, mock_flatten: MagicMock, mock_builder_cls: MagicMock
    ) -> None:
        mock_flatten.return_value = {}
        mock_instance = MagicMock()
        mock_instance.build.return_value = _fake_result()
        mock_builder_cls.return_value = mock_instance

        state = _make_state(
            constraints=[
                SpecialistConstraint(
                    constraint_id="no_altitude_after_dive",
                    type="temporal",
                    rule="no_altitude_after_dive",
                    severity="blocking",
                    reason="24h buffer before altitude",
                )
            ]
        )

        from app.planner.services.itinerary_adapter import build_itinerary_from_state

        build_itinerary_from_state(state)

        builder_input = mock_instance.build.call_args[0][0]
        assert len(builder_input.canonical_constraints) == 1
        assert builder_input.canonical_constraints[0]["rule"] == "no_altitude_after_dive"
        assert builder_input.canonical_constraints[0]["reason"] == "24h buffer before altitude"

    def test_trip_plan_constraints_are_honored_without_section_constraint(self) -> None:
        state = _make_state(
            start_date="2026-03-01",
            end_date="2026-03-08",
            sections=[
                {
                    "specialist_type": "diving",
                    "content_added": [
                        {"title": "USAT Liberty Wreck", "duration_hours": 3.0},
                        {"title": "Manta Point", "duration_hours": 3.0},
                    ],
                    "constraints_applied": [],
                },
                {
                    "specialist_type": "hiking",
                    "content_added": [
                        {"title": "Mount Batur Sunrise", "duration_hours": 4.0},
                        {"title": "Campuhan Ridge Walk", "duration_hours": 2.5},
                    ],
                    "constraints_applied": [],
                },
            ],
            constraints=[
                SpecialistConstraint(
                    constraint_id="no_altitude_after_dive",
                    type="temporal",
                    rule="no_altitude_after_dive",
                    severity="blocking",
                    reason="24h buffer before altitude",
                )
            ],
        )

        from app.planner.services.itinerary_adapter import build_itinerary_from_state

        result = build_itinerary_from_state(state)

        assert result is not None
        assert result.success is True

        diving_days: list[int] = []
        hiking_days: list[int] = []
        for day in result.day_cards:
            for block in day.blocks:
                if block.specialist_type == "diving" and not block.is_buffer:
                    diving_days.append(day.day_number)
                if block.specialist_type == "hiking" and not block.is_buffer:
                    hiking_days.append(day.day_number)

        assert diving_days
        assert hiking_days
        assert max(diving_days) < min(hiking_days)
