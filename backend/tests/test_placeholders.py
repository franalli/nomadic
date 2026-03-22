"""Tests for app.placeholders — deterministic placeholder image generation."""

from app.placeholders import (
    PLACEHOLDER_IMAGES,
    get_activity_image,
    get_destination_gallery,
    get_placeholder_image,
)


class TestGetPlaceholderImage:
    def test_returns_unsplash_url(self) -> None:
        url = get_placeholder_image("destination", seed="paris")
        assert url.startswith("https://images.unsplash.com/")
        assert "w=800" in url
        assert "h=600" in url

    def test_deterministic_with_same_seed(self) -> None:
        url1 = get_placeholder_image("diving", seed="bali-reef")
        url2 = get_placeholder_image("diving", seed="bali-reef")
        assert url1 == url2

    def test_different_seeds_can_differ(self) -> None:
        url1 = get_placeholder_image("hiking", seed="alps-trail")
        url2 = get_placeholder_image("hiking", seed="andes-summit")
        # Different seeds may select different images (not guaranteed but likely)
        # Just verify both are valid URLs
        assert url1.startswith("https://images.unsplash.com/")
        assert url2.startswith("https://images.unsplash.com/")

    def test_unknown_category_falls_back_to_destination(self) -> None:
        url = get_placeholder_image("nonexistent_category", seed="test")
        dest_url = get_placeholder_image("destination", seed="test")
        assert url == dest_url

    def test_custom_dimensions(self) -> None:
        url = get_placeholder_image("hotel", seed="test", width=400, height=300)
        assert "w=400" in url
        assert "h=300" in url

    def test_no_seed_returns_first_image(self) -> None:
        url = get_placeholder_image("diving")
        photo_id = PLACEHOLDER_IMAGES["diving"][0]
        assert photo_id in url

    def test_all_categories_have_images(self) -> None:
        for category in PLACEHOLDER_IMAGES:
            assert len(PLACEHOLDER_IMAGES[category]) > 0


class TestGetDestinationGallery:
    def test_returns_three_items(self) -> None:
        gallery = get_destination_gallery("Tokyo")
        assert len(gallery) == 3

    def test_gallery_items_have_required_fields(self) -> None:
        gallery = get_destination_gallery("Paris")
        for item in gallery:
            assert "label" in item
            assert "image_url" in item
            assert item["image_url"].startswith("https://images.unsplash.com/")

    def test_gallery_labels_are_expected(self) -> None:
        gallery = get_destination_gallery("London")
        labels = [item["label"] for item in gallery]
        assert labels == ["Destination", "Culture", "Adventure"]

    def test_deterministic_for_same_destination(self) -> None:
        g1 = get_destination_gallery("Bali")
        g2 = get_destination_gallery("Bali")
        assert g1 == g2


class TestGetActivityImage:
    def test_uses_topic_category_when_available(self) -> None:
        url = get_activity_image("diving", "Bali", "Coral Reef Tour")
        assert url.startswith("https://images.unsplash.com/")

    def test_falls_back_to_activity_for_unknown_topic(self) -> None:
        url = get_activity_image("unknown_topic", "Tokyo", "City Walk")
        # Should use "activity" category fallback
        assert url.startswith("https://images.unsplash.com/")

    def test_deterministic_for_same_inputs(self) -> None:
        url1 = get_activity_image("hiking", "Alps", "Summit Trek")
        url2 = get_activity_image("hiking", "Alps", "Summit Trek")
        assert url1 == url2
