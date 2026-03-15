from app.config import settings
from app.tile_service.google_places_provider import GooglePlacesHotelProvider
from app.tile_service.models import SearchContext


def test_google_places_hotel_tiles_do_not_fabricate_stars_from_min_stars() -> None:
    provider = GooglePlacesHotelProvider()
    ctx = SearchContext(
        destination="Barcelona",
        start_date="2026-06-01",
        end_date="2026-06-05",
        adults=2,
        children=0,
        hotel_settings={"min_stars": 5},
    )
    places = [
        {
            "id": "ChIJ123",
            "displayName": {"text": "Grand Stay Barcelona"},
            "formattedAddress": "Placa Example 1, Barcelona",
            "googleMapsUri": "https://maps.google.com/?q=place_id:ChIJ123",
            "location": {"latitude": 41.387, "longitude": 2.17},
        }
    ]

    tiles = provider._build_tiles(ctx, places)

    assert len(tiles) == 1
    tile = tiles[0]
    assert tile.rating is None
    assert "stars" not in (tile.meta or {})
    assert (tile.meta or {}).get("place_id") == "ChIJ123"


def test_google_places_hotel_tiles_use_plain_booking_deeplink_by_default(
    monkeypatch,
) -> None:
    provider = GooglePlacesHotelProvider()
    ctx = SearchContext(
        destination="Bali",
        start_date="2026-04-01",
        end_date="2026-04-07",
        adults=2,
        children=1,
    )
    places = [
        {
            "id": "ChIJ456",
            "displayName": {"text": "Grand Stay Bali"},
            "formattedAddress": "Jl. Example 1, Bali",
            "googleMapsUri": "https://maps.google.com/?q=place_id:ChIJ456",
            "location": {"latitude": -8.65, "longitude": 115.22},
        }
    ]

    monkeypatch.setattr(settings, "booking_affiliate_aid", "")

    tiles = provider._build_tiles(ctx, places)

    assert len(tiles) == 1
    tile = tiles[0]
    assert tile.deeplink.startswith("https://www.booking.com/searchresults.html?")
    assert "ss=Grand+Stay+Bali+Bali" in tile.deeplink
    assert "checkin=2026-04-01" in tile.deeplink
    assert "checkout=2026-04-07" in tile.deeplink
    assert "group_adults=2" in tile.deeplink
    assert "group_children=1" in tile.deeplink
    assert "aid=" not in tile.deeplink
    assert (tile.meta or {}).get(
        "maps_deeplink"
    ) == "https://www.google.com/travel/hotels/entity/ChIJ456"
    assert (tile.meta or {}).get("booking_deeplink") == tile.deeplink


def test_google_places_hotel_tiles_append_aid_when_configured(
    monkeypatch,
) -> None:
    provider = GooglePlacesHotelProvider()
    ctx = SearchContext(
        destination="Bali",
        start_date="2026-04-01",
        end_date="2026-04-07",
        adults=2,
    )
    places = [
        {
            "id": "ChIJ789",
            "displayName": {"text": "Lagoon Stay Bali"},
            "formattedAddress": "Jl. Example 2, Bali",
            "googleMapsUri": "https://maps.google.com/?q=place_id:ChIJ789",
            "location": {"latitude": -8.66, "longitude": 115.23},
        }
    ]

    monkeypatch.setattr(settings, "booking_affiliate_aid", "12345")

    tiles = provider._build_tiles(ctx, places)

    assert len(tiles) == 1
    tile = tiles[0]
    assert tile.deeplink.startswith("https://www.booking.com/searchresults.html?")
    assert "aid=12345" in tile.deeplink
    assert (tile.meta or {}).get("booking_deeplink") == tile.deeplink


def test_google_places_hotel_tiles_fall_back_to_google_travel_when_booking_url_unavailable(
    monkeypatch,
) -> None:
    import app.tile_service.google_places_provider as gp_module

    provider = GooglePlacesHotelProvider()
    ctx = SearchContext(
        destination="Bali",
        start_date="2026-04-01",
        end_date="2026-04-07",
        adults=2,
    )
    places = [
        {
            "id": "ChIJ789",
            "displayName": {"text": "Lagoon Stay Bali"},
            "formattedAddress": "Jl. Example 2, Bali",
            "googleMapsUri": "https://maps.google.com/?q=place_id:ChIJ789",
            "location": {"latitude": -8.66, "longitude": 115.23},
        }
    ]

    monkeypatch.setattr(gp_module, "_build_booking_search_url", lambda *_args, **_kwargs: "")

    tiles = provider._build_tiles(ctx, places)

    assert len(tiles) == 1
    tile = tiles[0]
    assert tile.deeplink == "https://www.google.com/travel/hotels/entity/ChIJ789"
    assert (tile.meta or {}).get("maps_deeplink") == tile.deeplink
    assert (tile.meta or {}).get("booking_deeplink") is None
