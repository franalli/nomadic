from app.main import _canonical_poi_type_for_block
from app.services.itinerary_builder import ItineraryBuilder


def test_cultural_attraction_stays_cultural() -> None:
    assert _canonical_poi_type_for_block("cultural_attraction") == "cultural"
    assert ItineraryBuilder._canonical_map_type("cultural_attraction") == "cultural"


def test_bare_attraction_maps_to_tours() -> None:
    assert _canonical_poi_type_for_block("attraction") == "tours"
    assert ItineraryBuilder._canonical_map_type("attraction") == "tours"


def test_tourist_attraction_maps_to_tours() -> None:
    assert _canonical_poi_type_for_block("tourist_attraction") == "tours"
    assert ItineraryBuilder._canonical_map_type("tourist_attraction") == "tours"


def test_exact_religious_sites_map_to_temples() -> None:
    for raw in ("church", "mosque", "synagogue", "place_of_worship"):
        assert _canonical_poi_type_for_block(raw) == "temples"
        assert ItineraryBuilder._canonical_map_type(raw) == "temples"


def test_compound_religious_sites_map_to_temples() -> None:
    for raw in ("historic_church", "grand_mosque", "old_synagogue"):
        assert _canonical_poi_type_for_block(raw) == "temples"
        assert ItineraryBuilder._canonical_map_type(raw) == "temples"
