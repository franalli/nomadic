from app.services.activity_browser import _placeholder_category_for_browse
from app.tile_service.google_places_provider import _placeholder_category_for_place_type


def test_google_places_placeholder_category_prefers_culture_for_landmarks() -> None:
    assert _placeholder_category_for_place_type("historical_landmark") == "culture"
    assert _placeholder_category_for_place_type("museum") == "culture"
    assert _placeholder_category_for_place_type("tourist_attraction") == "culture"
    assert _placeholder_category_for_place_type("point_of_interest") == "culture"


def test_google_places_placeholder_category_prefers_cooking_for_food_types() -> None:
    assert _placeholder_category_for_place_type("restaurant") == "cooking"
    assert _placeholder_category_for_place_type("cafe") == "cooking"


def test_browse_placeholder_category_uses_browse_category_signal() -> None:
    assert _placeholder_category_for_browse("cultural", "point_of_interest") == "culture"
    assert _placeholder_category_for_browse("food", "tourist_attraction") == "cooking"
    assert _placeholder_category_for_browse("tours", "tourist_attraction") == "culture"


def test_browse_placeholder_category_defaults_to_activity() -> None:
    assert _placeholder_category_for_browse("unknown", "unknown_type") == "activity"
