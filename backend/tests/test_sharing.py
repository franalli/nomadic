"""
Tests for app.services.sharing module.

Covers:
- generate_slug() — length, character set, uniqueness
- _is_signed_media_proxy_url() — URL detection logic
- _public_fallback() — signed URL replacement with Unsplash placeholders
- build_share_snapshot() — snapshot construction and image URL sanitization
- derive_share_metadata() — metadata extraction and title formatting
"""

from __future__ import annotations

from unittest.mock import patch

from app.schemas import (
    ActivitySettings,
    DayBlock,
    DayCard,
    DocumentTripInputs,
    PlanDocumentData,
    Tile,
)
from app.services.sharing import (
    _is_signed_media_proxy_url,
    _public_fallback,
    build_share_snapshot,
    derive_share_metadata,
    generate_slug,
)


class TestGenerateSlug:
    """Tests for generate_slug() URL-safe slug generation."""

    def test_returns_string(self):
        slug = generate_slug()
        assert isinstance(slug, str)

    def test_length_is_8(self):
        slug = generate_slug()
        assert len(slug) == 8

    def test_only_lowercase_and_digits(self):
        for _ in range(20):
            slug = generate_slug()
            assert slug.isalnum()
            assert slug == slug.lower()

    def test_different_slugs_on_repeated_calls(self):
        slugs = {generate_slug() for _ in range(50)}
        # With 36^8 possible slugs, 50 calls should produce at least 45 unique
        assert len(slugs) >= 45


class TestIsSignedMediaProxyUrl:
    """Tests for _is_signed_media_proxy_url() detection."""

    def test_google_places_photo_url(self):
        url = "https://example.com/api/media/google-places-photo?ref=abc&sig=xyz"
        assert _is_signed_media_proxy_url(url) is True

    def test_generic_media_proxy_url(self):
        url = "https://example.com/api/media/something"
        assert _is_signed_media_proxy_url(url) is True

    def test_normal_https_url(self):
        url = "https://images.unsplash.com/photo-abc"
        assert _is_signed_media_proxy_url(url) is False

    def test_none_input(self):
        assert _is_signed_media_proxy_url(None) is False

    def test_int_input(self):
        assert _is_signed_media_proxy_url(42) is False

    def test_empty_string(self):
        assert _is_signed_media_proxy_url("") is False


class TestPublicFallback:
    """Tests for _public_fallback() signed-URL replacement."""

    def test_non_signed_url_returned_unchanged(self):
        url = "https://images.unsplash.com/photo-abc"
        assert _public_fallback(url, "activity", "Paris") == url

    def test_signed_url_replaced_with_placeholder(self):
        url = "https://example.com/api/media/google-places-photo?ref=abc"
        with patch(
            "app.services.sharing.get_activity_image", return_value="https://placeholder.jpg"
        ) as mock:
            result = _public_fallback(url, "activity", "Paris")
            assert result == "https://placeholder.jpg"
            mock.assert_called_once_with("activity", "Paris", "activity")

    def test_stay_label_maps_to_hotel_category(self):
        url = "https://example.com/api/media/google-places-photo?ref=abc"
        with patch(
            "app.services.sharing.get_activity_image", return_value="https://hotel.jpg"
        ) as mock:
            _public_fallback(url, "stay", "Rome")
            mock.assert_called_once_with("hotel", "Rome", "hotel")

    def test_accommodation_label_maps_to_hotel_category(self):
        url = "https://example.com/api/media/google-places-photo?ref=abc"
        with patch(
            "app.services.sharing.get_activity_image", return_value="https://hotel.jpg"
        ) as mock:
            _public_fallback(url, "accommodation", "Rome")
            mock.assert_called_once_with("hotel", "Rome", "hotel")

    def test_signed_url_with_empty_destination_returns_none(self):
        url = "https://example.com/api/media/google-places-photo?ref=abc"
        assert _public_fallback(url, "activity", "") is None

    def test_none_image_url_returned_as_is(self):
        # None is not a signed URL, so it passes through
        assert _public_fallback(None, "activity", "Paris") is None


class TestBuildShareSnapshot:
    """Tests for build_share_snapshot() snapshot construction."""

    def test_returns_dict(self):
        doc = PlanDocumentData()
        result = build_share_snapshot(doc)
        assert isinstance(result, dict)

    def test_snapshot_contains_expected_keys(self):
        doc = PlanDocumentData()
        result = build_share_snapshot(doc)
        expected_keys = {
            "trip_inputs",
            "tiles",
            "strategy_sections",
            "day_cards",
            "plan_view_state",
            "executed_strategy_topics",
            "constraint_violations",
            "preferred_tile_ids",
        }
        assert expected_keys == set(result.keys())

    def test_tiles_with_public_urls_unchanged(self):
        tile = Tile(
            id="t1",
            title="Dive",
            type="activity",
            deeplink="https://example.com",
            image_url="https://images.unsplash.com/photo-abc",
        )
        doc = PlanDocumentData(tiles={"t1": tile})
        result = build_share_snapshot(doc)
        assert result["tiles"]["t1"]["image_url"] == "https://images.unsplash.com/photo-abc"

    def test_tiles_with_signed_urls_replaced(self):
        tile = Tile(
            id="t1",
            title="Dive",
            type="activity",
            deeplink="https://example.com",
            image_url="https://example.com/api/media/google-places-photo?ref=abc",
        )
        doc = PlanDocumentData(
            trip_inputs=DocumentTripInputs(destination="Bali"),
            tiles={"t1": tile},
        )
        with patch(
            "app.services.sharing.get_activity_image", return_value="https://placeholder.jpg"
        ):
            result = build_share_snapshot(doc)
        assert result["tiles"]["t1"]["image_url"] == "https://placeholder.jpg"

    def test_day_card_block_images_replaced(self):
        block = DayBlock(
            period="morning",
            activity_type="activity",
            summary="Temple visit",
            image_url="https://example.com/api/media/google-places-photo?ref=abc",
        )
        card = DayCard(day_number=1, label="Day 1", blocks=[block])
        doc = PlanDocumentData(
            trip_inputs=DocumentTripInputs(destination="Tokyo"),
            day_cards=[card],
        )
        with patch(
            "app.services.sharing.get_activity_image", return_value="https://placeholder.jpg"
        ):
            result = build_share_snapshot(doc)
        assert result["day_cards"][0]["blocks"][0]["image_url"] == "https://placeholder.jpg"

    def test_booked_tile_images_replaced(self):
        block = DayBlock(
            period="morning",
            activity_type="stay",
            summary="Hotel checkin",
            image_url="https://normal.jpg",
            booked_tile={
                "type": "stay",
                "image_url": "https://example.com/api/media/google-places-photo?ref=abc",
            },
        )
        card = DayCard(day_number=1, label="Day 1", blocks=[block])
        doc = PlanDocumentData(
            trip_inputs=DocumentTripInputs(destination="Tokyo"),
            day_cards=[card],
        )
        with patch(
            "app.services.sharing.get_activity_image", return_value="https://placeholder.jpg"
        ):
            result = build_share_snapshot(doc)
        booked = result["day_cards"][0]["blocks"][0]["booked_tile"]
        assert booked["image_url"] == "https://placeholder.jpg"

    def test_empty_tiles_dict_handled(self):
        doc = PlanDocumentData(tiles={})
        result = build_share_snapshot(doc)
        assert result["tiles"] == {}

    def test_empty_day_cards_handled(self):
        doc = PlanDocumentData(day_cards=[])
        result = build_share_snapshot(doc)
        assert result["day_cards"] == []


class TestDeriveShareMetadata:
    """Tests for derive_share_metadata() metadata extraction."""

    def test_empty_doc_returns_shared_trip_title(self):
        doc = PlanDocumentData()
        meta = derive_share_metadata(doc)
        assert meta["title"] == "Shared Trip"
        assert meta["destination"] is None
        assert meta["day_count"] is None

    def test_destination_only(self):
        doc = PlanDocumentData(
            trip_inputs=DocumentTripInputs(destination="Paris"),
        )
        meta = derive_share_metadata(doc)
        assert meta["title"] == "Paris"
        assert meta["destination"] == "Paris"

    def test_destination_with_categories(self):
        doc = PlanDocumentData(
            trip_inputs=DocumentTripInputs(
                destination="Bali",
                activity_settings=ActivitySettings(categories=["diving", "surfing"]),
            ),
        )
        meta = derive_share_metadata(doc)
        assert "Bali" in meta["title"]
        assert "Diving + Surfing" in meta["title"]

    def test_categories_capped_at_three(self):
        doc = PlanDocumentData(
            trip_inputs=DocumentTripInputs(
                destination="Thailand",
                activity_settings=ActivitySettings(
                    categories=["diving", "surfing", "hiking", "cycling"]
                ),
            ),
        )
        meta = derive_share_metadata(doc)
        # Only first 3 categories included
        assert "Cycling" not in meta["title"]
        assert "Diving + Surfing + Hiking" in meta["title"]

    def test_with_dates(self):
        doc = PlanDocumentData(
            trip_inputs=DocumentTripInputs(
                destination="Rome",
                start_date="2025-06-15",
                end_date="2025-06-22",
            ),
        )
        meta = derive_share_metadata(doc)
        assert "Jun 15-22" in meta["title"]

    def test_invalid_dates_ignored(self):
        doc = PlanDocumentData(
            trip_inputs=DocumentTripInputs(
                destination="Rome",
                start_date="not-a-date",
                end_date="also-not",
            ),
        )
        meta = derive_share_metadata(doc)
        assert meta["title"] == "Rome"

    def test_day_count_from_day_cards(self):
        cards = [DayCard(day_number=i, label=f"Day {i}") for i in range(1, 4)]
        doc = PlanDocumentData(day_cards=cards)
        meta = derive_share_metadata(doc)
        assert meta["day_count"] == 3

    def test_title_truncated_at_200_chars(self):
        long_dest = "A" * 300
        doc = PlanDocumentData(
            trip_inputs=DocumentTripInputs(destination=long_dest),
        )
        meta = derive_share_metadata(doc)
        assert len(meta["title"]) <= 200

    def test_full_metadata_structure(self):
        cards = [DayCard(day_number=i, label=f"Day {i}") for i in range(1, 3)]
        doc = PlanDocumentData(
            trip_inputs=DocumentTripInputs(
                destination="Bali",
                start_date="2025-07-01",
                end_date="2025-07-08",
                activity_settings=ActivitySettings(categories=["diving"]),
            ),
            day_cards=cards,
        )
        meta = derive_share_metadata(doc)
        assert "Bali" in meta["title"]
        assert "Diving" in meta["title"]
        assert "Jul 01-08" in meta["title"]
        assert meta["destination"] == "Bali"
        assert meta["day_count"] == 2
