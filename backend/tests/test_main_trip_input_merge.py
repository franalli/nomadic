"""Unit tests for main.py trip_inputs merge sanitization."""

from app.main import _sanitize_trip_inputs_for_category_merge


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
