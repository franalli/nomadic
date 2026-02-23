"""Tests for settings extraction/apply behavior in intent_router."""

import pytest

from app.planner.nodes.intent_router import (
    _apply_modifications_to_state,
    _apply_origin_to_state,
    _apply_settings_to_state,
    _detect_settings_from_message,
    _sanitize_settings_from_message,
)
from app.planner.nodes.router_extraction import (
    RouterOutput,
    _populate_trip_plan_from_router_output,
    _validate_extraction,
)
from app.planner.state import GraphState


def test_apply_settings_sets_flights_toggle_as_tri_state_string():
    state = GraphState()
    state.trip_plan.destination = "Bali"
    state.metadata["trip_inputs"] = {}

    detected_settings = {
        "flight_settings": {
            "direct_only": True,
        }
    }

    _apply_settings_to_state(state, detected_settings, None)

    extracted = state.metadata.get("extracted_settings", {})
    assert extracted.get("flights_toggle") == "on"
    assert extracted.get("flight_direct_only") is True
    assert state.metadata.get("explicit_flights_toggle") == "on"
    assert state.metadata.get("trip_inputs", {}).get("booking_types", {}).get("flights") == "on"
    assert state.metadata.get("tier2_prefetch_intent") == "settings"


def test_detect_settings_supports_budget_typo_without_hotel_false_positive():
    state = GraphState()
    state.trip_plan.destination = "Bali"

    detected = _detect_settings_from_message("3 adults 2 kids, bugdet 2000", state)

    assert detected is not None
    assert detected.get("budget") == 2000
    assert "hotel_settings" not in detected


def test_budget_only_update_preserves_existing_hotel_star_preference():
    state = GraphState()
    state.trip_plan.destination = "Bali"
    state.metadata["trip_inputs"] = {"hotel_settings": {"min_stars": 5}}

    detected = _detect_settings_from_message("Increase budget to $2,800", state)
    assert detected == {"budget": 2800}

    _apply_settings_to_state(state, detected, None)

    hotel_settings = state.metadata.get("trip_inputs", {}).get("hotel_settings", {})
    assert hotel_settings.get("min_stars") == 5
    assert state.trip_plan.budget == 2800


def test_sanitize_settings_drops_spurious_hotel_settings_for_budget_only_message():
    detected = {
        "budget": 2800,
        "hotel_settings": {"min_stars": 0},
    }

    sanitized = _sanitize_settings_from_message(detected, "Increase budget to $2,800")

    assert sanitized == {"budget": 2800}


def test_sanitize_settings_keeps_hotel_settings_when_message_mentions_hotels():
    detected = {
        "budget": 2800,
        "hotel_settings": {"min_stars": 5},
    }

    sanitized = _sanitize_settings_from_message(
        detected,
        "Increase budget to $2,800 and keep 5-star hotels",
    )

    assert sanitized == detected


@pytest.mark.asyncio
async def test_apply_origin_preserves_explicit_flights_on():
    state = GraphState()
    state.metadata["trip_inputs"] = {"booking_types": {"flights": "off"}}
    state.metadata["explicit_flights_toggle"] = "on"

    await _apply_origin_to_state(state, "Rome", None)

    assert state.metadata["trip_inputs"]["booking_types"]["flights"] == "on"
    assert state.metadata["extracted_settings"]["flights_toggle"] == "on"


@pytest.mark.asyncio
async def test_apply_origin_preserves_explicit_flights_off():
    state = GraphState()
    state.metadata["trip_inputs"] = {"booking_types": {"flights": "on"}}
    state.metadata["explicit_flights_toggle"] = "off"

    await _apply_origin_to_state(state, "Rome", None)

    assert state.metadata["trip_inputs"]["booking_types"]["flights"] == "off"
    assert "flights_toggle" not in state.metadata.get("extracted_settings", {})


@pytest.mark.asyncio
async def test_apply_origin_upgrades_default_off_to_suggested_when_not_explicit():
    state = GraphState()
    state.metadata["trip_inputs"] = {"booking_types": {"flights": "off"}}

    await _apply_origin_to_state(state, "Rome", None)

    assert state.metadata["trip_inputs"]["booking_types"]["flights"] == "suggested"
    assert state.metadata["extracted_settings"]["flights_toggle"] == "suggested"


def test_populate_trip_plan_skips_category_writes_without_category_intent():
    state = GraphState()
    state.metadata["trip_inputs"] = {"activity_settings": {"categories": ["diving", "surfing"]}}

    router_output = RouterOutput(
        intent="PLANNING",
        confidence=0.9,
        reasoning="settings-only",
        activity_categories=["nightlife"],
        specialist_hints=[],
    )

    _populate_trip_plan_from_router_output(
        state,
        router_output,
        fallback_destination="Bali",
        user_text="5-star hotels only",
        category_baseline={"diving", "surfing"},
        category_merge_mode="replace",
        allow_category_updates=False,
    )

    categories = (
        state.metadata.get("trip_inputs", {}).get("activity_settings", {}).get("categories", [])
    )
    assert categories == ["diving", "surfing"]


def test_apply_modifications_remove_last_category_disables_activities():
    state = GraphState()
    state.trip_plan.destination = "Rome"
    state.metadata["trip_inputs"] = {
        "activity_settings": {"categories": ["cultural"]},
        "booking_types": {"activities": "suggested"},
    }

    result = _apply_modifications_to_state(
        state,
        {"remove_categories": {"cultural"}},
        "remove all cultural",
        None,
    )

    assert result is state
    assert state.metadata["trip_inputs"]["activity_settings"]["categories"] == []
    assert state.metadata["trip_inputs"]["booking_types"]["activities"] == "off"


def test_apply_modifications_add_category_reenables_activities():
    state = GraphState()
    state.metadata["trip_inputs"] = {
        "activity_settings": {"categories": []},
        "booking_types": {"activities": "off"},
    }

    result = _apply_modifications_to_state(
        state,
        {"add_categories": {"yoga"}},
        "add yoga",
        None,
    )

    assert result is state
    assert state.metadata["trip_inputs"]["activity_settings"]["categories"] == ["yoga"]
    assert state.metadata["trip_inputs"]["booking_types"]["activities"] == "suggested"


def test_validate_extraction_bumps_end_year_when_start_auto_bumps():
    extracted = {
        "start_date": "2026-02-15",
        "end_date": "2026-02-25",
    }

    validated = _validate_extraction(extracted, "2026-02-16")

    assert validated["start_date"] == "2027-02-15"
    assert validated["end_date"] == "2027-02-25"
    assert validated["date_auto_adjustments"] == [
        {
            "field": "start_date",
            "from": "2026-02-15",
            "to": "2027-02-15",
            "reason": "past_date_auto_bumped",
        },
        {
            "field": "end_date",
            "from": "2026-02-25",
            "to": "2027-02-25",
            "reason": "preserve_range_after_start_bump",
        },
    ]
