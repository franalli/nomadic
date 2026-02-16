"""Unit tests for main.py trip_inputs/session-state merge sanitization."""

from app.main import (
    _merge_user_owned_trip_setting,
    _prepare_graph_plan_session_state,
    _sanitize_trip_inputs_for_category_merge,
)
from app.schemas import GraphPlanRequest


def test_generate_turn_preserves_document_categories_by_dropping_request_snapshot():
    incoming = {
        "activity_settings": {
            "categories": ["diving", "nightlife"],
            "day_preferences": {"diving": 3},
        },
        "hotel_settings": {"min_stars": 5},
    }

    sanitized = _sanitize_trip_inputs_for_category_merge(incoming, "GENERATE_PLAN_NOW")

    assert "categories" not in sanitized["activity_settings"]
    assert sanitized["activity_settings"]["day_preferences"] == {"diving": 3}
    assert sanitized["hotel_settings"]["min_stars"] == 5


def test_question_turn_drops_request_category_snapshot():
    incoming = {
        "activity_settings": {
            "categories": ["diving", "surfing", "nightlife"],
        }
    }

    sanitized = _sanitize_trip_inputs_for_category_merge(incoming, "Do I need a visa for Bali?")

    assert sanitized["activity_settings"] == {}


def test_explicit_category_intent_keeps_request_categories():
    incoming = {
        "activity_settings": {
            "categories": ["diving", "nightlife"],
        }
    }

    sanitized = _sanitize_trip_inputs_for_category_merge(incoming, "add nightlife and yoga")

    assert sanitized["activity_settings"]["categories"] == ["diving", "nightlife"]


def test_merge_user_owned_trip_setting_preserves_categories_when_incoming_omits_them():
    merged = _merge_user_owned_trip_setting(
        {"categories": ["diving", "surfing"], "day_preferences": {"diving": 3}},
        {"day_preferences": {"diving": 2, "surfing": 1}},
        preserve_categories_if_missing=True,
    )
    assert merged["categories"] == ["diving", "surfing"]
    assert merged["day_preferences"] == {"diving": 2, "surfing": 1}


def test_merge_user_owned_trip_setting_allows_explicit_category_overwrite():
    merged = _merge_user_owned_trip_setting(
        {"categories": ["diving", "surfing"]},
        {"categories": []},
        preserve_categories_if_missing=True,
    )
    assert merged["categories"] == []


def test_generate_turn_session_merge_keeps_existing_categories():
    req = GraphPlanRequest(
        message="GENERATE_PLAN_NOW",
        trip_inputs={
            "activity_settings": {
                "categories": ["diving", "nightlife", "surfing", "yoga"],
                "day_preferences": {"diving": 3, "surfing": 2},
            }
        },
        session_state={
            "trip_inputs": {
                "destination": "Bali",
                "activity_settings": {
                    "categories": ["diving", "nightlife", "surfing", "yoga"],
                },
            },
            "metadata": {},
        },
    )

    prepared = _prepare_graph_plan_session_state(req, today_iso="2026-02-16")
    activity_settings = prepared["trip_inputs"]["activity_settings"]

    assert activity_settings["categories"] == ["diving", "nightlife", "surfing", "yoga"]
    assert activity_settings["day_preferences"] == {"diving": 3, "surfing": 2}


def test_graph_plan_session_prep_parity_for_equivalent_requests():
    payload = {
        "message": "Plan Bali diving and nightlife",
        "trip_inputs": {
            "destination": "Bali",
            "start_date": "2026-06-10",
            "end_date": "2026-06-17",
            "activity_settings": {"categories": ["diving", "nightlife"]},
        },
        "session_state": {
            "thread_id": "123e4567-e89b-12d3-a456-426614174000",
            "trip_inputs": {"origin": "SFO"},
            "metadata": {"foo": "bar"},
        },
        "ui_phase": "expanded",
        "suggestion_clicked": "Build itinerary",
    }
    today_iso = "2026-02-16"

    sync_prepared = _prepare_graph_plan_session_state(
        GraphPlanRequest.model_validate(payload),
        today_iso=today_iso,
    )
    stream_prepared = _prepare_graph_plan_session_state(
        GraphPlanRequest.model_validate(payload),
        today_iso=today_iso,
    )

    assert sync_prepared == stream_prepared
    assert sync_prepared["today_iso"] == today_iso
    assert sync_prepared["thread_id"] == "123e4567-e89b-12d3-a456-426614174000"
    assert sync_prepared["metadata"]["foo"] == "bar"
    assert sync_prepared["metadata"]["ui_phase"] == "expanded"
    assert sync_prepared["metadata"]["suggestion_clicked"] == "Build itinerary"


def test_graph_plan_session_prep_merges_trip_inputs_non_null_only():
    req = GraphPlanRequest(
        message="Update destination only",
        trip_inputs={
            "destination": "Lisbon",
            "origin": None,
            "end_date": "2026-09-20",
        },
        session_state={
            "thread_id": "123e4567-e89b-12d3-a456-426614174001",
            "trip_inputs": {
                "destination": "Bali",
                "origin": "SFO",
                "start_date": "2026-09-10",
            },
        },
    )

    prepared = _prepare_graph_plan_session_state(req, today_iso="2026-02-16")

    assert prepared["trip_inputs"]["destination"] == "Lisbon"
    # Explicit null from request must not clobber existing non-null value.
    assert prepared["trip_inputs"]["origin"] == "SFO"
    assert prepared["trip_inputs"]["start_date"] == "2026-09-10"
    assert prepared["trip_inputs"]["end_date"] == "2026-09-20"
    assert prepared["thread_id"] == "123e4567-e89b-12d3-a456-426614174001"


def test_graph_plan_session_prep_reset_initializes_new_thread_and_trip_inputs():
    req = GraphPlanRequest(
        message="Start over in Tokyo",
        reset=True,
        session_state={},
        thread_id="client-thread-id",
        trip_inputs={"destination": "Tokyo"},
    )

    prepared = _prepare_graph_plan_session_state(req, today_iso="2026-02-16")

    assert prepared["thread_id"]
    assert prepared["thread_id"] != "client-thread-id"
    assert prepared["trip_inputs"]["destination"] == "Tokyo"
    assert prepared["today_iso"] == "2026-02-16"
