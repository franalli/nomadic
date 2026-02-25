"""Unit tests for logistics_node.py pure/helper functions with zero coverage."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.planner.nodes.logistics_node import (
    _cached_tier2_tiles_for_categories,
    _calculate_diving_safety,
    _compute_tiles_per_category,
    _curated_to_flight_tiles,
    _fallback_tier2_tiles,
    _get_mock_flights,
    _has_nofly_constraints,
    _tier2_generation_key,
    _tile_matches_categories,
    _tile_to_dict,
)
from app.planner.state.graph_state import GraphState, SpecialistConstraint, TripPlan

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**overrides) -> GraphState:
    """Build a minimal GraphState with sensible defaults, overridable via kwargs."""
    defaults = {
        "trip_plan": TripPlan(
            destination="Bali",
            start_date="2026-03-01",
            end_date="2026-03-07",
            adults=2,
            children=0,
        ),
        "metadata": {},
        "tiles": {},
        "messages": [],
        "pending_specialists": [],
        "active_specialist": None,
        "active_agent_id": None,
        "ui_events": [],
    }
    defaults.update(overrides)
    return GraphState(**defaults)


def _make_tile_obj(**overrides):
    """Build a mock tile object (SimpleNamespace) with all expected attributes."""
    attrs = {
        "id": "tile_001",
        "type": "hotel",
        "partner": "booking.com",
        "partner_product_id": "bk_12345",
        "title": "Oceanview Resort",
        "subtitle": "Beachfront luxury",
        "image_url": "https://example.com/img.jpg",
        "price_estimate": 250.0,
        "currency": "USD",
        "price_basis": "per_night",
        "is_estimate_only": False,
        "deeplink_url": "https://booking.com/hotel/12345",
        "rating": 4.5,
        "location_label": "Seminyak, Bali",
        "tags": ["beach", "luxury"],
        "availability_status": "available",
        "meta": {"stars": 5},
        "source": "curated",
        "source_agent": "logistics_node",
    }
    attrs.update(overrides)
    return SimpleNamespace(**attrs)


# ===========================================================================
# 1. _tile_to_dict
# ===========================================================================


class TestTileToDict:
    def test_all_fields_mapped_correctly(self):
        tile = _make_tile_obj()
        result = _tile_to_dict(tile)

        assert result["id"] == "tile_001"
        assert result["type"] == "hotel"
        assert result["partner"] == "booking.com"
        assert result["partner_product_id"] == "bk_12345"
        assert result["title"] == "Oceanview Resort"
        assert result["subtitle"] == "Beachfront luxury"
        assert result["image_url"] == "https://example.com/img.jpg"
        assert result["price_estimate"] == 250.0
        assert result["currency"] == "USD"
        assert result["price_basis"] == "per_night"
        assert result["is_estimate_only"] is False
        assert result["deeplink_url"] == "https://booking.com/hotel/12345"
        assert result["rating"] == 4.5
        assert result["location_label"] == "Seminyak, Bali"
        assert result["tags"] == ["beach", "luxury"]
        assert result["availability_status"] == "available"
        assert result["meta"] == {"stars": 5}
        assert result["source"] == "curated"
        assert result["source_agent"] == "logistics_node"

    def test_source_agent_fallback_when_none(self):
        tile = _make_tile_obj(source_agent=None)
        result = _tile_to_dict(tile)
        assert result["source_agent"] == "logistics_node"

    def test_source_agent_preserved_when_set(self):
        tile = _make_tile_obj(source_agent="experience_generator")
        result = _tile_to_dict(tile)
        assert result["source_agent"] == "experience_generator"

    def test_works_with_mock_magic_mock(self):
        tile = MagicMock()
        tile.id = "mm_001"
        tile.type = "activity"
        tile.partner = "viator"
        tile.partner_product_id = "v_99"
        tile.title = "Snorkeling Trip"
        tile.subtitle = "Half day"
        tile.image_url = None
        tile.price_estimate = 80
        tile.currency = "EUR"
        tile.price_basis = "per_person"
        tile.is_estimate_only = True
        tile.deeplink_url = None
        tile.rating = 3.9
        tile.location_label = "Nusa Penida"
        tile.tags = ["water"]
        tile.availability_status = "limited"
        tile.meta = {}
        tile.source = "mock"
        tile.source_agent = None

        result = _tile_to_dict(tile)
        assert result["id"] == "mm_001"
        assert result["source_agent"] == "logistics_node"


# ===========================================================================
# 2. _calculate_diving_safety
# ===========================================================================


class TestCalculateDivingSafety:
    def test_safe_with_large_buffer(self):
        # Flight at 2026-03-08T16:00 -> last dive 2026-03-07T14:00 -> 26h buffer
        status, is_safe = _calculate_diving_safety("2026-03-08T16:00:00")
        assert is_safe is True
        assert "26h" in status
        assert "Safe" in status

    def test_risky_10h_buffer(self):
        # Flight at midnight -> last dive yesterday at 14:00 -> 10h buffer
        # buffer = flight_hour + 10 = 0 + 10 = 10
        status, is_safe = _calculate_diving_safety("2026-03-07T00:00:00")
        assert is_safe is False
        assert "10h" in status
        assert "Risky" in status

    def test_exactly_24h_is_safe(self):
        # Need buffer = exactly 24h. Last dive = flight - 1 day at 14:00.
        # buffer_hours = (flight - (flight-1day).replace(14:00)).total_seconds() / 3600
        # If flight at 14:00 next day: buffer = 24h exactly.
        status, is_safe = _calculate_diving_safety("2026-03-07T14:00:00")
        assert is_safe is True
        assert "24h" in status
        assert "Safe" in status

    def test_iso_datetime_with_timezone_z(self):
        # Z suffix should be handled via .replace("Z", "+00:00")
        # Flight at 18:00 UTC -> last dive at 14:00 (yesterday) -> 28h -> safe
        status, is_safe = _calculate_diving_safety("2026-03-08T18:00:00Z")
        assert is_safe is True
        assert "28h" in status

    def test_iso_datetime_with_offset(self):
        # Same calculation with explicit +00:00 offset
        status, is_safe = _calculate_diving_safety("2026-03-08T18:00:00+00:00")
        assert is_safe is True
        assert "28h" in status

    def test_early_morning_flight_risky(self):
        # Flight at 08:00 -> last dive yesterday 14:00 -> 18h buffer -> risky
        status, is_safe = _calculate_diving_safety("2026-03-07T08:00:00")
        assert is_safe is False
        assert "18h" in status

    def test_late_evening_flight_safe(self):
        # Flight at 21:30 -> last dive yesterday 14:00 -> 31.5h buffer -> safe
        status, is_safe = _calculate_diving_safety("2026-03-07T21:30:00")
        assert is_safe is True
        assert "31h" in status


# ===========================================================================
# 3. _has_nofly_constraints (registry-driven no-fly buffer detection)
# ===========================================================================


class TestHasNoflyConstraints:
    def test_active_specialist_is_diving(self):
        state = _make_state(active_specialist="diving")
        assert _has_nofly_constraints(state) is True

    def test_strategy_section_with_diving_specialist_type(self):
        state = _make_state(
            metadata={
                "strategy_sections": [{"specialist_type": "diving", "constraints_applied": []}]
            }
        )
        assert _has_nofly_constraints(state) is True

    def test_constraint_with_24h_in_rule(self):
        state = _make_state(
            metadata={
                "strategy_sections": [
                    {
                        "specialist_type": "general",
                        "constraints_applied": [
                            {"rule": "Allow 24h buffer before flying after diving"}
                        ],
                    }
                ]
            }
        )
        assert _has_nofly_constraints(state) is True

    def test_constraint_with_no_fly_in_rule(self):
        state = _make_state(
            metadata={
                "strategy_sections": [
                    {
                        "specialist_type": "general",
                        "constraints_applied": [{"rule": "no_fly interval required after scuba"}],
                    }
                ]
            }
        )
        assert _has_nofly_constraints(state) is True

    def test_trip_plan_constraint_with_24h(self):
        tp = TripPlan(
            destination="Bali",
            start_date="2026-03-01",
            end_date="2026-03-07",
            constraints=[
                SpecialistConstraint(
                    type="temporal",
                    rule="24h surface interval before flight",
                    severity="blocking",
                )
            ],
        )
        state = _make_state(trip_plan=tp)
        assert _has_nofly_constraints(state) is True

    def test_trip_plan_constraint_with_no_fly(self):
        tp = TripPlan(
            destination="Bali",
            start_date="2026-03-01",
            end_date="2026-03-07",
            constraints=[
                SpecialistConstraint(
                    type="safety",
                    rule="no_fly_buffer_after_diving",
                    severity="blocking",
                )
            ],
        )
        state = _make_state(trip_plan=tp)
        assert _has_nofly_constraints(state) is True

    def test_no_nofly_indicators(self):
        state = _make_state(
            active_specialist="hiking",
            metadata={
                "strategy_sections": [
                    {
                        "specialist_type": "hiking",
                        "constraints_applied": [{"rule": "altitude acclimatization required"}],
                    }
                ]
            },
        )
        assert _has_nofly_constraints(state) is False

    def test_no_metadata_at_all(self):
        state = _make_state()
        assert _has_nofly_constraints(state) is False


# ===========================================================================
# 4. _tile_matches_categories
# ===========================================================================


class TestTileMatchesCategories:
    def test_matching_tag(self):
        tile = {"tags": ["yoga", "wellness"], "title": "Sunrise Yoga", "subtitle": ""}
        assert _tile_matches_categories(tile, {"yoga"}) is True

    def test_matching_keyword_in_title_fallback(self):
        tile = {"tags": ["relaxation"], "title": "Beach Cooking Class", "subtitle": ""}
        assert _tile_matches_categories(tile, {"cooking"}) is True

    def test_matching_keyword_in_subtitle(self):
        tile = {
            "tags": ["relaxation"],
            "title": "Local Experience",
            "subtitle": "Traditional cooking lesson",
        }
        assert _tile_matches_categories(tile, {"cooking"}) is True

    def test_no_match(self):
        tile = {
            "tags": ["adventure", "outdoors"],
            "title": "Mountain Trek",
            "subtitle": "Full day hike",
        }
        assert _tile_matches_categories(tile, {"cooking"}) is False

    def test_case_insensitive_tags(self):
        tile = {"tags": ["YOGA", "Wellness"], "title": "Morning session", "subtitle": ""}
        assert _tile_matches_categories(tile, {"yoga"}) is True

    def test_case_insensitive_category(self):
        tile = {"tags": ["yoga"], "title": "Morning session", "subtitle": ""}
        assert _tile_matches_categories(tile, {"YOGA"}) is True

    def test_empty_tags_fallback_to_title(self):
        tile = {"tags": [], "title": "Nightlife Tour", "subtitle": ""}
        assert _tile_matches_categories(tile, {"nightlife"}) is True

    def test_no_tags_key(self):
        tile = {"title": "Nightlife Tour", "subtitle": ""}
        assert _tile_matches_categories(tile, {"nightlife"}) is True

    def test_multiple_categories_any_match(self):
        tile = {"tags": ["surfing"], "title": "Wave Rider", "subtitle": ""}
        assert _tile_matches_categories(tile, {"yoga", "surfing", "cooking"}) is True


# ===========================================================================
# 5. _compute_tiles_per_category
# ===========================================================================


class TestComputeTilesPerCategory:
    def test_no_dates_returns_2(self):
        state = _make_state(trip_plan=TripPlan(destination="Bali"))
        assert _compute_tiles_per_category(state, {"yoga"}) == 2

    def test_no_start_date_returns_2(self):
        state = _make_state(trip_plan=TripPlan(destination="Bali", end_date="2026-03-07"))
        assert _compute_tiles_per_category(state, {"yoga"}) == 2

    def test_empty_tier2_cats_returns_2(self):
        state = _make_state()
        assert _compute_tiles_per_category(state, set()) == 2

    def test_7_day_trip_no_specialist_days_3_categories(self):
        # trip_days = 7, specialist_days = 0, free_days = max(0, 7-0-2) = 5
        # total_placeable = 5 + 0 = 5, tiles_per_cat = min(max(2, 5//3), 4) = min(max(2,1),4) = 2
        state = _make_state()
        result = _compute_tiles_per_category(state, {"yoga", "cooking", "nightlife"})
        assert result == 2

    def test_7_day_trip_no_specialist_days_1_category(self):
        # trip_days = 7, specialist_days = 0, free_days = 5
        # total_placeable = 5, tiles_per_cat = min(max(2, 5//1), 4) = min(5,4) = 4
        state = _make_state()
        result = _compute_tiles_per_category(state, {"yoga"})
        assert result == 4

    def test_long_trip_capped_at_4(self):
        # 21-day trip, no specialists, 1 category
        # trip_days = 21, free = 19, placeable = 19, tiles = min(max(2,19),4) = 4
        tp = TripPlan(
            destination="Bali",
            start_date="2026-03-01",
            end_date="2026-03-21",
        )
        state = _make_state(trip_plan=tp)
        result = _compute_tiles_per_category(state, {"yoga"})
        assert result == 4

    def test_very_short_trip_minimum_2(self):
        # 2-day trip, 0 specialist
        # trip_days = 2, free = max(0, 2-0-2) = 0, placeable = 0
        # tiles_per_cat = min(max(2, 0//1), 4) = 2
        tp = TripPlan(
            destination="Bali",
            start_date="2026-03-01",
            end_date="2026-03-02",
        )
        state = _make_state(trip_plan=tp)
        result = _compute_tiles_per_category(state, {"yoga"})
        assert result == 2

    def test_with_specialist_days(self):
        # 10-day trip, 3 specialist days (from strategy_sections), 2 categories
        # trip_days = 10, specialist_days = 3, free = max(0,10-3-2) = 5
        # total_placeable = 5+3 = 8, tiles_per_cat = min(max(2,8//2),4) = min(4,4) = 4
        tp = TripPlan(
            destination="Bali",
            start_date="2026-03-01",
            end_date="2026-03-10",
        )
        state = _make_state(
            trip_plan=tp,
            metadata={
                "strategy_sections": [
                    {
                        "specialist_type": "diving",
                        "content_added": [{}, {}, {}],
                    }
                ]
            },
        )
        result = _compute_tiles_per_category(state, {"yoga", "nightlife"})
        assert result == 4

    def test_local_expert_sections_not_counted_as_specialist_days(self):
        # local_expert and general sections are excluded from specialist_days
        tp = TripPlan(
            destination="Bali",
            start_date="2026-03-01",
            end_date="2026-03-07",
        )
        state = _make_state(
            trip_plan=tp,
            metadata={
                "strategy_sections": [
                    {
                        "specialist_type": "local_expert",
                        "content_added": [{}, {}, {}, {}, {}],
                    }
                ]
            },
        )
        # specialist_days = 0 (local_expert excluded)
        # trip_days=7, free=5, placeable=5, tiles=min(max(2,5//1),4)=4
        result = _compute_tiles_per_category(state, {"yoga"})
        assert result == 4

    def test_invalid_date_format_returns_2(self):
        tp = TripPlan(
            destination="Bali",
            start_date="not-a-date",
            end_date="also-not-a-date",
        )
        state = _make_state(trip_plan=tp)
        assert _compute_tiles_per_category(state, {"yoga"}) == 2


# ===========================================================================
# 6. _tier2_generation_key
# ===========================================================================


class TestTier2GenerationKey:
    def test_normalizes_destination_lowercase(self):
        key = _tier2_generation_key("BALI", "march", {"yoga"}, 3)
        assert "bali" in key
        assert "BALI" not in key

    def test_normalizes_month_lowercase(self):
        key = _tier2_generation_key("bali", "MARCH", {"yoga"}, 3)
        assert "march" in key
        assert "MARCH" not in key

    def test_sorts_categories(self):
        key1 = _tier2_generation_key("bali", "march", {"yoga", "cooking", "nightlife"}, 3)
        key2 = _tier2_generation_key("bali", "march", {"nightlife", "yoga", "cooking"}, 3)
        assert key1 == key2

    def test_includes_tiles_per_category(self):
        key = _tier2_generation_key("bali", "march", {"yoga"}, 4)
        assert "n4" in key

    def test_different_tiles_per_category_different_key(self):
        key1 = _tier2_generation_key("bali", "march", {"yoga"}, 2)
        key2 = _tier2_generation_key("bali", "march", {"yoga"}, 4)
        assert key1 != key2

    def test_handles_none_destination(self):
        key = _tier2_generation_key(None, "march", {"yoga"}, 2)
        assert key.startswith("tier2::")

    def test_handles_none_month(self):
        key = _tier2_generation_key("bali", None, {"yoga"}, 2)
        assert "tier2:bali::" in key

    def test_handles_empty_categories(self):
        key = _tier2_generation_key("bali", "march", set(), 2)
        assert key == "tier2:bali:march::n2"

    def test_strips_whitespace(self):
        key = _tier2_generation_key("  Bali  ", "  March  ", {"  yoga  "}, 3)
        assert "bali" in key
        assert "march" in key
        assert "yoga" in key

    def test_format_structure(self):
        key = _tier2_generation_key("bali", "march", {"yoga", "cooking"}, 3)
        assert key == "tier2:bali:march:cooking|yoga:n3"


# ===========================================================================
# 7. _curated_to_flight_tiles
# ===========================================================================


class TestCuratedToFlightTiles:
    def test_converts_single_flight(self):
        curated = [
            {
                "id": "ek_001",
                "carrier_code": "EK",
                "carrier_name": "Emirates",
                "departure_time": "10:30",
                "duration": "PT6H",
                "price": 450,
            }
        ]
        result = _curated_to_flight_tiles(curated, "2026-03-15")

        assert len(result) == 1
        flight = result[0]
        assert flight["id"] == "ek_001"
        assert flight["price"]["total"] == "450"
        segments = flight["itineraries"][0]["segments"]
        assert len(segments) == 1
        assert segments[0]["carrierCode"] == "EK"
        assert segments[0]["departure"]["at"] == "2026-03-15T10:30:00"
        assert segments[0]["duration"] == "PT6H"

    def test_converts_multiple_flights(self):
        curated = [
            {"carrier_code": "EK", "departure_time": "08:00", "duration": "PT5H", "price": 300},
            {"carrier_code": "BA", "departure_time": "18:00", "duration": "PT7H", "price": 550},
        ]
        result = _curated_to_flight_tiles(curated, "2026-04-01")
        assert len(result) == 2
        assert result[0]["itineraries"][0]["segments"][0]["carrierCode"] == "EK"
        assert result[1]["itineraries"][0]["segments"][0]["carrierCode"] == "BA"

    def test_uses_date_str_as_base(self):
        curated = [
            {"carrier_code": "SQ", "departure_time": "14:00", "duration": "PT8H", "price": 600}
        ]
        result = _curated_to_flight_tiles(curated, "2026-12-25")
        departure_at = result[0]["itineraries"][0]["segments"][0]["departure"]["at"]
        assert departure_at.startswith("2026-12-25T")

    def test_defaults_for_missing_fields(self):
        curated = [{}]
        result = _curated_to_flight_tiles(curated, "2026-03-15")
        flight = result[0]
        # Should use defaults without raising
        assert flight["price"]["total"] == "0"
        segments = flight["itineraries"][0]["segments"]
        assert segments[0]["carrierCode"] == "EK"  # default
        assert segments[0]["departure"]["at"] == "2026-03-15T12:00:00"  # default
        assert segments[0]["duration"] == "PT6H"  # default

    def test_truncates_long_date_str(self):
        curated = [
            {"carrier_code": "QF", "departure_time": "09:00", "duration": "PT4H", "price": 200}
        ]
        # date_str with full ISO timestamp - should take first 10 chars
        result = _curated_to_flight_tiles(curated, "2026-03-15T14:30:00+00:00")
        departure_at = result[0]["itineraries"][0]["segments"][0]["departure"]["at"]
        assert departure_at.startswith("2026-03-15T")

    def test_empty_date_str_uses_fallback(self):
        curated = [
            {"carrier_code": "QF", "departure_time": "09:00", "duration": "PT4H", "price": 200}
        ]
        result = _curated_to_flight_tiles(curated, "")
        departure_at = result[0]["itineraries"][0]["segments"][0]["departure"]["at"]
        assert departure_at.startswith("2026-03-20T")  # fallback date


# ===========================================================================
# 8. _get_mock_flights
# ===========================================================================


class TestGetMockFlights:
    def test_returns_three_flights(self):
        flights = _get_mock_flights("2026-03-20")
        assert len(flights) == 3

    def test_first_flight_is_demo_unsafe(self):
        flights = _get_mock_flights("2026-03-20")
        assert flights[0]["id"] == "demo_unsafe"
        dep = flights[0]["itineraries"][0]["segments"][0]["departure"]["at"]
        assert "T08:00:00" in dep

    def test_second_and_third_are_safe_options(self):
        flights = _get_mock_flights("2026-03-20")
        assert flights[1]["id"] == "demo_safe_1"
        assert flights[2]["id"] == "demo_safe_2"
        dep1 = flights[1]["itineraries"][0]["segments"][0]["departure"]["at"]
        dep2 = flights[2]["itineraries"][0]["segments"][0]["departure"]["at"]
        assert "T18:00:00" in dep1
        assert "T21:30:00" in dep2

    def test_uses_provided_date_str(self):
        flights = _get_mock_flights("2027-06-15")
        for flight in flights:
            dep = flight["itineraries"][0]["segments"][0]["departure"]["at"]
            assert dep.startswith("2027-06-15T")

    def test_each_flight_has_price(self):
        flights = _get_mock_flights("2026-03-20")
        for flight in flights:
            assert "total" in flight["price"]
            assert float(flight["price"]["total"]) > 0

    def test_carrier_codes(self):
        flights = _get_mock_flights("2026-03-20")
        codes = [f["itineraries"][0]["segments"][0]["carrierCode"] for f in flights]
        # First two are "XX" (maps to Emirates), third is "BA"
        assert codes[0] == "XX"
        assert codes[1] == "XX"
        assert codes[2] == "BA"


# ===========================================================================
# 9. Hash functions: _hotel_logistics_hash, _activity_logistics_hash,
#    _flight_logistics_hash
# ===========================================================================


class TestLogisticsHashFunctions:
    """Test determinism, isolation, and sensitivity of logistics cache hashes."""

    def _base_state(self) -> GraphState:
        return _make_state(
            trip_plan=TripPlan(
                destination="Bali",
                origin="London",
                start_date="2026-03-01",
                end_date="2026-03-07",
                adults=2,
                children=0,
                budget=3000.0,
            ),
            metadata={
                "trip_settings": {
                    "booking_types": {
                        "hotels": "suggested",
                        "flights": "on",
                        "ground_transport": "off",
                        "activities": "suggested",
                    },
                    "flight_settings": {
                        "round_trip": True,
                        "cabin_class": "economy",
                        "direct_only": False,
                    },
                    "hotel_settings": {"min_stars": 3, "amenities": ["pool"]},
                    "activity_settings": {
                        "categories": ["diving"],
                        "skill_level": "beginner",
                        "day_preferences": {},
                    },
                    "transport_settings": {"car": False, "train": False, "bus": False},
                    "date_flex": False,
                    "trip_duration": None,
                    "date_window_start": None,
                    "date_window_end": None,
                },
            },
        )

    def test_same_inputs_same_hash(self):
        from app.planner.nodes.logistics_node import (
            _activity_logistics_hash,
            _flight_logistics_hash,
            _hotel_logistics_hash,
        )

        s1 = self._base_state()
        s2 = self._base_state()
        assert _hotel_logistics_hash(s1) == _hotel_logistics_hash(s2)
        assert _activity_logistics_hash(s1) == _activity_logistics_hash(s2)
        assert _flight_logistics_hash(s1) == _flight_logistics_hash(s2)

    def test_different_destination_different_hash(self):
        from app.planner.nodes.logistics_node import (
            _activity_logistics_hash,
            _flight_logistics_hash,
            _hotel_logistics_hash,
        )

        s1 = self._base_state()
        s2 = self._base_state()
        s2.trip_plan.destination = "Tokyo"
        assert _hotel_logistics_hash(s1) != _hotel_logistics_hash(s2)
        assert _activity_logistics_hash(s1) != _activity_logistics_hash(s2)
        assert _flight_logistics_hash(s1) != _flight_logistics_hash(s2)

    def test_different_dates_different_hash(self):
        from app.planner.nodes.logistics_node import (
            _activity_logistics_hash,
            _flight_logistics_hash,
            _hotel_logistics_hash,
        )

        s1 = self._base_state()
        s2 = self._base_state()
        s2.trip_plan.start_date = "2026-06-01"
        s2.trip_plan.end_date = "2026-06-07"
        assert _hotel_logistics_hash(s1) != _hotel_logistics_hash(s2)
        assert _activity_logistics_hash(s1) != _activity_logistics_hash(s2)
        assert _flight_logistics_hash(s1) != _flight_logistics_hash(s2)

    def test_hotel_hash_ignores_activity_settings(self):
        from app.planner.nodes.logistics_node import _hotel_logistics_hash

        s1 = self._base_state()
        s2 = self._base_state()
        # Change activity categories - hotel hash should stay the same
        s2.metadata["trip_settings"]["activity_settings"]["categories"] = [
            "hiking",
            "surfing",
        ]
        assert _hotel_logistics_hash(s1) == _hotel_logistics_hash(s2)

    def test_activity_hash_ignores_hotel_settings(self):
        from app.planner.nodes.logistics_node import _activity_logistics_hash

        s1 = self._base_state()
        s2 = self._base_state()
        # Change hotel min_stars - activity hash should stay the same
        s2.metadata["trip_settings"]["hotel_settings"]["min_stars"] = 5
        assert _activity_logistics_hash(s1) == _activity_logistics_hash(s2)

    def test_flight_hash_sensitive_to_origin(self):
        from app.planner.nodes.logistics_node import _flight_logistics_hash

        s1 = self._base_state()
        s2 = self._base_state()
        s2.trip_plan.origin = "Paris"
        assert _flight_logistics_hash(s1) != _flight_logistics_hash(s2)


# ===========================================================================
# 10. _cached_tier2_tiles_for_categories
# ===========================================================================


class TestCachedTier2TilesForCategories:
    def test_all_categories_cached_returns_combined(self):
        yoga_tiles = [{"id": "yoga_1"}, {"id": "yoga_2"}]
        cooking_tiles = [{"id": "cooking_1"}]
        state = _make_state(
            metadata={
                "generated_tier2_categories": {
                    "Bali": {
                        "yoga": yoga_tiles,
                        "cooking": cooking_tiles,
                    }
                }
            }
        )
        result = _cached_tier2_tiles_for_categories(state, "Bali", {"yoga", "cooking"})
        assert len(result) == 3
        ids = {t["id"] for t in result}
        assert ids == {"yoga_1", "yoga_2", "cooking_1"}

    def test_missing_category_returns_empty(self):
        state = _make_state(
            metadata={
                "generated_tier2_categories": {
                    "Bali": {
                        "yoga": [{"id": "yoga_1"}],
                        # "cooking" is missing
                    }
                }
            }
        )
        result = _cached_tier2_tiles_for_categories(state, "Bali", {"yoga", "cooking"})
        assert result == []

    def test_no_metadata_returns_empty(self):
        state = _make_state()
        result = _cached_tier2_tiles_for_categories(state, "Bali", {"yoga"})
        assert result == []

    def test_wrong_destination_returns_empty(self):
        state = _make_state(
            metadata={"generated_tier2_categories": {"Bali": {"yoga": [{"id": "yoga_1"}]}}}
        )
        result = _cached_tier2_tiles_for_categories(state, "Tokyo", {"yoga"})
        assert result == []

    def test_empty_category_tiles_returns_empty(self):
        state = _make_state(
            metadata={
                "generated_tier2_categories": {
                    "Bali": {"yoga": []}  # empty tile list
                }
            }
        )
        result = _cached_tier2_tiles_for_categories(state, "Bali", {"yoga"})
        assert result == []

    def test_none_generated_tier2_categories(self):
        state = _make_state(metadata={"generated_tier2_categories": None})
        result = _cached_tier2_tiles_for_categories(state, "Bali", {"yoga"})
        assert result == []


# ===========================================================================
# 11. _fallback_tier2_tiles
# ===========================================================================


class TestFallbackTier2Tiles:
    def test_tiles_matching_categories_returns_subset(self):
        tiles = [
            {"tags": ["yoga"], "title": "Yoga Retreat", "subtitle": ""},
            {"tags": ["cooking"], "title": "Cooking Class", "subtitle": ""},
            {"tags": ["nightlife"], "title": "Bar Crawl", "subtitle": ""},
        ]
        result = _fallback_tier2_tiles(tiles, {"yoga", "cooking"})
        assert len(result) == 2
        titles = {t["title"] for t in result}
        assert titles == {"Yoga Retreat", "Cooking Class"}

    def test_no_matching_tiles_returns_all(self):
        tiles = [
            {"tags": ["nature"], "title": "Forest Walk", "subtitle": ""},
            {"tags": ["adventure"], "title": "Zipline", "subtitle": ""},
        ]
        result = _fallback_tier2_tiles(tiles, {"yoga"})
        assert result == tiles

    def test_empty_existing_tiles(self):
        result = _fallback_tier2_tiles([], {"yoga"})
        assert result == []

    def test_partial_match_returns_matching_only(self):
        tiles = [
            {"tags": ["yoga"], "title": "Yoga Session", "subtitle": ""},
            {"tags": ["nature"], "title": "Hiking Trail", "subtitle": ""},
        ]
        result = _fallback_tier2_tiles(tiles, {"yoga"})
        assert len(result) == 1
        assert result[0]["title"] == "Yoga Session"

    def test_title_keyword_fallback_match(self):
        # _tile_matches_categories also checks title keywords
        tiles = [
            {"tags": [], "title": "Nightlife Experience", "subtitle": ""},
            {"tags": ["nature"], "title": "Forest Walk", "subtitle": ""},
        ]
        result = _fallback_tier2_tiles(tiles, {"nightlife"})
        assert len(result) == 1
        assert result[0]["title"] == "Nightlife Experience"
