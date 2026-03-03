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
