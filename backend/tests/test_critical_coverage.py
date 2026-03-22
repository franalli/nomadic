"""
Tier 1 + Tier 2 unit tests for critical untested functions.

Covers functions that directly cause empty tiles, hollow blocks,
stale data, and broken progressive rendering when they regress.

Tier 1 (ship-blocking):
  - merge_trip_inputs: CRDT-style trip input merging
  - _ensure_block_display_floor: minimum viable block display data
  - _flatten_tiles_payload: tiles dict normalization for SSE
  - _is_pure_tail_extension: extension detection for specialist preservation
  - _carry_forward_partner_enrichment: affiliate data survival across tile refresh

Tier 2 (pre-progressive-rendering):
  - _tile_enrichment_partial_event: enrichment partial SSE event
  - _day_cards_partial_payload: progressive day_cards partial shape
  - state serde round-trip: field survival through serialize/deserialize
  - _has_partner_enrichment + _copy_partner_enrichment_fields: partner helpers
  - _day_cards_partial_event: SSE event shape

Run with: pytest tests/test_critical_coverage.py -v
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

from app.crud_document import merge_trip_inputs
from app.planner.coordinator import (
    _carry_forward_partner_enrichment,
    _copy_partner_enrichment_fields,
    _day_cards_partial_event,
    _day_cards_partial_payload,
    _flatten_tiles_payload,
    _has_partner_enrichment,
    _is_pure_tail_extension,
    _tile_enrichment_partial_event,
)
from app.planner.services.state_serde import (
    restore_agent_state,
    serialize_agent_state,
)
from app.schemas import ActivitySettings, DocumentTripInputs
from app.services.itinerary_builder import (
    DayBlockOutput,
    _ensure_block_display_floor,
)

# =============================================================================
# Tier 1: merge_trip_inputs
# =============================================================================


class TestMergeTripInputs:
    """Tests for crud_document.merge_trip_inputs -- CRDT merge logic."""

    def test_incoming_none_returns_existing(self):
        existing = DocumentTripInputs(destination="Bali")
        result = merge_trip_inputs(existing, None)
        assert result.destination == "Bali"

    def test_incoming_empty_dict_returns_existing(self):
        existing = DocumentTripInputs(destination="Bali", start_date="2030-03-01")
        result = merge_trip_inputs(existing, {})
        assert result.destination == "Bali"
        assert result.start_date == "2030-03-01"

    def test_scalar_field_overwrite(self):
        existing = DocumentTripInputs(destination="Bali", origin="NYC")
        result = merge_trip_inputs(existing, {"destination": "Rome"})
        assert result.destination == "Rome"
        assert result.origin == "NYC"

    def test_none_incoming_value_does_not_clear_existing(self):
        existing = DocumentTripInputs(destination="Bali", origin="NYC")
        result = merge_trip_inputs(existing, {"origin": None})
        assert result.origin == "NYC"

    def test_explicit_null_clears_field(self):
        existing = DocumentTripInputs(destination="Bali", origin="NYC")
        result = merge_trip_inputs(existing, {}, explicit_nulls={"origin"})
        assert result.origin is None

    def test_explicit_null_destination(self):
        existing = DocumentTripInputs(destination="Bali")
        result = merge_trip_inputs(existing, {}, explicit_nulls={"destination"})
        assert result.destination is None
        assert "destination" in result.missing_fields

    def test_explicit_null_currency_resets_to_usd(self):
        existing = DocumentTripInputs(currency="EUR")
        result = merge_trip_inputs(existing, {}, explicit_nulls={"currency"})
        assert result.currency == "USD"

    def test_activity_settings_replaced_as_whole(self):
        existing = DocumentTripInputs(activity_settings=ActivitySettings(categories=["diving"]))
        result = merge_trip_inputs(
            existing, {"activity_settings": {"categories": ["hiking", "surfing"]}}
        )
        assert result.activity_settings.categories == ["hiking", "surfing"]

    def test_pydantic_defaults_not_merged_when_absent(self):
        existing = DocumentTripInputs(
            destination="Bali",
            start_date="2030-03-01",
            end_date="2030-03-07",
            adults=2,
        )
        result = merge_trip_inputs(existing, {"destination": "Rome"})
        assert result.start_date == "2030-03-01"
        assert result.end_date == "2030-03-07"
        assert result.adults == 2

    def test_missing_fields_recomputed(self):
        result = merge_trip_inputs(DocumentTripInputs(), {"destination": "Bali"})
        assert "destination" not in result.missing_fields
        assert "start_date" in result.missing_fields

    def test_missing_fields_empty_when_all_required_present(self):
        result = merge_trip_inputs(
            DocumentTripInputs(),
            {"destination": "Bali", "start_date": "2030-03-01"},
        )
        assert result.missing_fields == []

    def test_deep_copy_does_not_mutate_existing(self):
        existing = DocumentTripInputs(destination="Bali")
        _ = merge_trip_inputs(existing, {"destination": "Rome"})
        assert existing.destination == "Bali"

    def test_date_flex_explicit_null_resets_to_false(self):
        existing = DocumentTripInputs(date_flex=True)
        result = merge_trip_inputs(existing, {}, explicit_nulls={"date_flex"})
        assert result.date_flex is False

    def test_booking_types_explicit_null_resets_to_default(self):
        from app.schemas import BookingTypes

        existing = DocumentTripInputs(booking_types=BookingTypes(flights="on"))
        result = merge_trip_inputs(existing, {}, explicit_nulls={"booking_types"})
        assert result.booking_types is not None
        # Default flights is "off", so after reset it should not be "on"
        assert result.booking_types.flights != "on"


# =============================================================================
# Tier 1: _ensure_block_display_floor
# =============================================================================


class TestEnsureBlockDisplayFloor:
    """Tests for itinerary_builder._ensure_block_display_floor."""

    def _block(self, **kw) -> DayBlockOutput:
        defaults: dict[str, Any] = {
            "id": "test_1",
            "period": "morning",
            "activity_type": "diving",
            "summary": "Snorkel Tour",
        }
        defaults.update(kw)
        return DayBlockOutput(**defaults)

    def test_buffer_block_returned_unchanged(self):
        block = self._block(is_buffer=True, deeplink=None, image_url=None)
        result = _ensure_block_display_floor(block, "Bali")
        assert result.deeplink is None
        assert result.image_url is None

    def test_deeplink_from_google_place_id(self):
        block = self._block(deeplink=None, google_place_id="ChIJ_abc123")
        result = _ensure_block_display_floor(block, "Bali")
        assert result.deeplink is not None
        assert "place_id:ChIJ_abc123" in result.deeplink

    def test_deeplink_from_summary_when_no_place_id(self):
        block = self._block(deeplink=None, google_place_id=None, summary="Manta Point")
        result = _ensure_block_display_floor(block, "Bali")
        assert result.deeplink is not None
        assert "maps/search" in result.deeplink
        assert "Manta" in result.deeplink

    def test_deeplink_from_coordinates_last_resort(self):
        block = self._block(
            deeplink=None,
            google_place_id=None,
            summary="",
            coordinates={"lat": -8.5, "lng": 115.2},
        )
        result = _ensure_block_display_floor(block, "Bali")
        assert result.deeplink is not None
        assert "-8.5" in result.deeplink

    def test_existing_deeplink_not_overwritten(self):
        block = self._block(deeplink="https://viator.com/tours/123")
        result = _ensure_block_display_floor(block, "Bali")
        assert result.deeplink == "https://viator.com/tours/123"

    @patch("app.placeholders.get_activity_image", return_value="https://placeholder.com/img.jpg")
    def test_image_url_filled_with_placeholder(self, mock_img):
        block = self._block(image_url=None, specialist_type="diving")
        result = _ensure_block_display_floor(block, "Bali")
        assert result.image_url == "https://placeholder.com/img.jpg"
        mock_img.assert_called_once()

    def test_existing_image_url_not_overwritten(self):
        block = self._block(image_url="https://real.com/photo.jpg")
        result = _ensure_block_display_floor(block, "Bali")
        assert result.image_url == "https://real.com/photo.jpg"


# =============================================================================
# Tier 1: _flatten_tiles_payload
# =============================================================================


class TestFlattenTilesPayload:
    def test_category_keyed_dict(self):
        tiles = {
            "activities": [
                {"id": "act1", "title": "Dive", "type": "activity"},
                {"id": "act2", "title": "Hike", "type": "activity"},
            ],
            "hotels": [{"id": "htl1", "title": "Beach Hotel", "type": "hotel"}],
        }
        result = _flatten_tiles_payload(tiles)
        assert len(result) == 3
        assert "act1" in result and "act2" in result and "htl1" in result

    def test_empty_dict(self):
        assert _flatten_tiles_payload({}) == {}

    def test_non_dict_returns_empty(self):
        assert _flatten_tiles_payload([]) == {}  # type: ignore[arg-type]

    def test_skips_non_list_values(self):
        tiles = {"activities": [{"id": "a1", "title": "X"}], "meta": "string"}
        assert len(_flatten_tiles_payload(tiles)) == 1

    def test_tiles_without_id_skipped(self):
        assert len(_flatten_tiles_payload({"a": [{"title": "No ID"}]})) == 0

    def test_deeplink_url_normalized_to_deeplink(self):
        tiles = {"a": [{"id": "a1", "deeplink_url": "https://viator.com/123"}]}
        result = _flatten_tiles_payload(tiles)
        assert result["a1"].get("deeplink") == "https://viator.com/123"

    def test_coordinates_normalized_to_geo(self):
        tiles = {"a": [{"id": "a1", "coordinates": [115.2, -8.5]}]}
        geo = _flatten_tiles_payload(tiles)["a1"].get("geo")
        assert geo == {"lat": -8.5, "lng": 115.2}


# =============================================================================
# Tier 1: _is_pure_tail_extension
# =============================================================================


class TestIsPureTailExtension:
    def _p(self, dest, start, end):
        return {"destination": dest, "start_date": start, "end_date": end}

    def test_same_start_later_end(self):
        assert (
            _is_pure_tail_extension(
                self._p("Bali", "2030-03-01", "2030-03-07"),
                self._p("Bali", "2030-03-01", "2030-03-14"),
            )
            is True
        )

    def test_different_start(self):
        assert (
            _is_pure_tail_extension(
                self._p("Bali", "2030-03-01", "2030-03-07"),
                self._p("Bali", "2030-03-03", "2030-03-14"),
            )
            is False
        )

    def test_same_dates(self):
        assert (
            _is_pure_tail_extension(
                self._p("Bali", "2030-03-01", "2030-03-07"),
                self._p("Bali", "2030-03-01", "2030-03-07"),
            )
            is False
        )

    def test_shorter_end(self):
        assert (
            _is_pure_tail_extension(
                self._p("Bali", "2030-03-01", "2030-03-14"),
                self._p("Bali", "2030-03-01", "2030-03-07"),
            )
            is False
        )

    def test_different_destination(self):
        assert (
            _is_pure_tail_extension(
                self._p("Bali", "2030-03-01", "2030-03-07"),
                self._p("Rome", "2030-03-01", "2030-03-14"),
            )
            is False
        )

    def test_missing_dates(self):
        assert (
            _is_pure_tail_extension(
                self._p("Bali", "2030-03-01", "2030-03-07"),
                {"destination": "Bali"},
            )
            is False
        )

    def test_case_insensitive(self):
        assert (
            _is_pure_tail_extension(
                self._p("bali", "2030-03-01", "2030-03-07"),
                self._p("Bali", "2030-03-01", "2030-03-14"),
            )
            is True
        )

    def test_empty_destination(self):
        assert (
            _is_pure_tail_extension(
                self._p("", "2030-03-01", "2030-03-07"),
                self._p("", "2030-03-01", "2030-03-14"),
            )
            is False
        )


# =============================================================================
# Tier 1: _carry_forward_partner_enrichment
# =============================================================================


class TestCarryForwardPartnerEnrichment:
    def _enriched(self, tid="t1", **kw):
        base = {
            "id": tid,
            "title": "Manta Point Dive",
            "type": "activity",
            "provider": "viator",
            "partner": "viator",
            "live_price": 85.0,
            "deeplink_url": "https://viator.com/tours/123",
            "meta": {"viator_product_code": "12345P1", "category": "diving"},
        }
        base.update(kw)
        return base

    def _plain(self, tid="t1", **kw):
        base = {
            "id": tid,
            "title": "Manta Point Dive",
            "type": "activity",
            "provider": "google_places",
            "meta": {"category": "diving"},
        }
        base.update(kw)
        return base

    def test_carried_forward_by_id(self):
        result = _carry_forward_partner_enrichment([self._plain()], [self._enriched()])
        assert result[0]["provider"] == "viator"
        assert result[0]["live_price"] == 85.0
        assert result[0]["meta"]["viator_product_code"] == "12345P1"

    def test_already_enriched_not_overwritten(self):
        result = _carry_forward_partner_enrichment(
            [self._enriched(live_price=99.0)], [self._enriched(live_price=85.0)]
        )
        assert result[0]["live_price"] == 99.0

    def test_no_existing_enrichment(self):
        result = _carry_forward_partner_enrichment([self._plain()], [self._plain()])
        assert result[0]["provider"] == "google_places"

    def test_non_list_existing(self):
        assert len(_carry_forward_partner_enrichment([self._plain()], None)) == 1

    def test_non_list_refreshed(self):
        assert _carry_forward_partner_enrichment(None, [self._enriched()]) == []

    def test_match_by_title(self):
        result = _carry_forward_partner_enrichment(
            [self._plain("new_id")], [self._enriched("old_id")]
        )
        assert result[0].get("provider") == "viator"

    def test_no_match_different_titles(self):
        result = _carry_forward_partner_enrichment(
            [self._plain("t2", title="Volcano Hike", meta={"category": "hiking"})],
            [self._enriched("t1", title="Coral Garden")],
        )
        assert result[0]["provider"] == "google_places"


# =============================================================================
# Tier 2: _tile_enrichment_partial_event
# =============================================================================


class TestTileEnrichmentPartialEvent:
    def _s(self, **kw):
        return {"tiles": {}, "strategy_sections": [], **kw}

    def test_none_when_nothing_changed(self):
        assert (
            _tile_enrichment_partial_event(
                self._s(), [], {}, day_cards_changed=False, tiles_changed=False
            )
            is None
        )

    def test_partial_when_day_cards_changed(self):
        r = _tile_enrichment_partial_event(
            self._s(), [], {}, day_cards_changed=True, tiles_changed=False
        )
        assert r["type"] == "partial"
        assert r["data"]["kind"] == "tile_enrichment"
        assert r["data"]["payload"]["day_cards_changed"] is True

    def test_partial_when_tiles_changed(self):
        r = _tile_enrichment_partial_event(
            self._s(), [], {}, day_cards_changed=False, tiles_changed=True
        )
        assert r["data"]["payload"]["tiles_changed"] is True

    def test_tiles_replaced_flag(self):
        r = _tile_enrichment_partial_event(
            self._s(turn_meta={"tiles_replaced": True}),
            [],
            {},
            day_cards_changed=True,
            tiles_changed=False,
        )
        assert r["data"].get("tiles_replaced") is True

    def test_no_tiles_replaced_by_default(self):
        r = _tile_enrichment_partial_event(
            self._s(), [], {}, day_cards_changed=True, tiles_changed=False
        )
        assert "tiles_replaced" not in r["data"]


# =============================================================================
# Tier 2: _day_cards_partial_payload + _day_cards_partial_event
# =============================================================================


class TestDayCardsPartials:
    def test_payload_has_required_keys(self):
        state = {
            "tiles": {"activities": [{"id": "a1", "title": "X"}]},
            "strategy_sections": [{"specialist_type": "diving"}],
        }
        r = _day_cards_partial_payload(state, [{"day": 1}])
        assert "day_cards" in r and "tiles" in r and "strategy_sections" in r

    def test_payload_uses_explicit_tiles(self):
        state = {"tiles": {}, "strategy_sections": []}
        r = _day_cards_partial_payload(state, [], tiles_payload={"x": {"id": "x"}})
        assert r["tiles"] == {"x": {"id": "x"}}

    def test_payload_flattens_when_no_explicit(self):
        state = {"tiles": {"a": [{"id": "a1", "title": "X"}]}, "strategy_sections": []}
        assert "a1" in _day_cards_partial_payload(state, [])["tiles"]

    def test_event_structure(self):
        state = {"tiles": {}, "strategy_sections": []}
        r = _day_cards_partial_event(state, [{"day": 1}])
        assert r["type"] == "partial"
        assert r["data"]["kind"] == "day_cards"
        assert "payload" in r["data"]


# =============================================================================
# Tier 2: State serde round-trip
# =============================================================================


class TestStateSerdeRoundTrip:
    def _golden_state(self) -> Dict[str, Any]:
        from langchain_core.messages import AIMessage, HumanMessage

        return {
            "messages": [HumanMessage(content="Diving in Bali"), AIMessage(content="Great!")],
            "trip_plan": {
                "destination": "Bali",
                "origin": "New York",
                "start_date": "2030-03-01",
                "end_date": "2030-03-07",
                "adults": 2,
                "children": 1,
                "budget": 5000,
                "currency": "USD",
            },
            "trip_settings": {
                "activity_settings": {
                    "categories": ["diving", "cultural"],
                    "activities_per_day": 2,
                },
                "booking_types": {"flights": "suggested", "hotels": "suggested"},
            },
            "tiles": {
                "activities": [
                    {
                        "id": "act1",
                        "type": "activity",
                        "title": "Manta Point Dive",
                        "provider": "viator",
                        "partner": "viator",
                        "source": "live",
                        "source_agent": "vertical_specialist",
                        "price_estimate": 85.0,
                        "live_price": 85.0,
                        "currency": "USD",
                        "is_estimate_only": False,
                        "image_url": "https://example.com/manta.jpg",
                        "geo": {"lat": -8.5, "lng": 115.2},
                        "deeplink": "https://viator.com/tours/123",
                        "rating": 4.8,
                        "review_count": 342,
                        "meta": {"viator_product_code": "12345P1", "category": "diving"},
                    }
                ],
                "hotels": [
                    {
                        "id": "htl1",
                        "type": "hotel",
                        "title": "Beach Resort",
                        "price_estimate": 120.0,
                        "deeplink": "https://booking.com/hotel/123",
                        "image_url": "https://example.com/hotel.jpg",
                        "geo": {"lat": -8.6, "lng": 115.3},
                    }
                ],
            },
            "strategy_sections": [
                {
                    "specialist_type": "diving",
                    "feasibility_status": "feasible",
                    "content_added": [{"title": "Manta Point", "duration_hours": 3}],
                    "constraints_applied": ["no_fly_24h"],
                }
            ],
            "day_cards": [
                {
                    "day_number": 1,
                    "label": "Arrival Day",
                    "blocks": [
                        {
                            "id": "blk1",
                            "booking_category": "activity",
                            "summary": "Manta Point Dive",
                            "booked_tile": {
                                "id": "act1",
                                "title": "Manta Point Dive",
                                "provider": "viator",
                                "partner": "viator",
                                "source": "live",
                                "source_agent": "vertical_specialist",
                                "live_price": 85.0,
                                "price_estimate": 85.0,
                                "deeplink": "https://viator.com/tours/123",
                                "is_estimate_only": False,
                            },
                        }
                    ],
                }
            ],
            "constraints": [{"rule": "no_fly_24h", "specialist": "diving"}],
            "specialist_plans": {"diving": {"day_plans": [{"day": 2}]}},
            "persistent_meta": {"itinerary_overview": {"duration_label": "7 days"}},
        }

    def test_trip_plan(self):
        r = restore_agent_state(serialize_agent_state(self._golden_state()))
        assert r["trip_plan"]["destination"] == "Bali"
        assert r["trip_plan"]["adults"] == 2
        assert r["trip_plan"]["budget"] == 5000

    def test_trip_settings(self):
        r = restore_agent_state(serialize_agent_state(self._golden_state()))
        cats = r["trip_settings"]["activity_settings"]["categories"]
        assert "diving" in cats

    def test_activity_tile_fields(self):
        r = restore_agent_state(serialize_agent_state(self._golden_state()))
        t = r["tiles"]["activities"][0]
        assert t["id"] == "act1"
        assert t["provider"] == "viator"
        assert t["live_price"] == 85.0
        assert t["is_estimate_only"] is False
        assert t.get("image_url") == "https://example.com/manta.jpg"
        assert t.get("geo") == {"lat": -8.5, "lng": 115.2}
        assert t.get("deeplink") == "https://viator.com/tours/123"

    def test_viator_meta(self):
        r = restore_agent_state(serialize_agent_state(self._golden_state()))
        assert r["tiles"]["activities"][0]["meta"]["viator_product_code"] == "12345P1"

    def test_strategy_sections(self):
        r = restore_agent_state(serialize_agent_state(self._golden_state()))
        s = r["strategy_sections"][0]
        assert s["specialist_type"] == "diving"
        # content_added is intentionally stripped during serialization (state_serde line 674)
        assert "content_added" not in s
        assert s["feasibility_status"] == "feasible"

    def test_day_card_structure(self):
        r = restore_agent_state(serialize_agent_state(self._golden_state()))
        assert r["day_cards"][0]["label"] == "Arrival Day"

    def test_booked_tile_core_fields(self):
        r = restore_agent_state(serialize_agent_state(self._golden_state()))
        bt = r["day_cards"][0]["blocks"][0]["booked_tile"]
        assert bt["id"] == "act1"
        assert bt["provider"] == "viator"
        assert bt["live_price"] == 85.0
        assert bt["deeplink"] == "https://viator.com/tours/123"

    def test_constraints(self):
        r = restore_agent_state(serialize_agent_state(self._golden_state()))
        assert len(r["constraints"]) >= 1

    def test_specialist_plans(self):
        r = restore_agent_state(serialize_agent_state(self._golden_state()))
        assert "diving" in r["specialist_plans"]

    def test_messages(self):
        from langchain_core.messages import HumanMessage

        r = restore_agent_state(serialize_agent_state(self._golden_state()))
        assert len(r["messages"]) == 2
        assert isinstance(r["messages"][0], HumanMessage)
        assert r["messages"][0].content == "Diving in Bali"

    def test_persistent_meta(self):
        r = restore_agent_state(serialize_agent_state(self._golden_state()))
        assert "itinerary_overview" in r["persistent_meta"]

    def test_empty_state(self):
        r = restore_agent_state(serialize_agent_state({}))
        assert isinstance(r.get("messages", []), list)


# =============================================================================
# Tier 2: _has_partner_enrichment + _copy_partner_enrichment_fields
# =============================================================================


class TestPartnerEnrichmentHelpers:
    def test_viator_provider(self):
        assert _has_partner_enrichment({"provider": "viator"}) is True

    def test_gyg_partner(self):
        assert _has_partner_enrichment({"partner": "gyg"}) is True

    def test_viator_meta(self):
        assert _has_partner_enrichment({"meta": {"viator_product_code": "X"}}) is True

    def test_google_places_not_enriched(self):
        assert _has_partner_enrichment({"provider": "google_places"}) is False

    def test_non_dict(self):
        assert _has_partner_enrichment(None) is False  # type: ignore[arg-type]

    def test_copy_fields(self):
        src = {
            "provider": "viator",
            "live_price": 85.0,
            "deeplink_url": "https://viator.com/123",
            "meta": {"viator_product_code": "12345P1"},
        }
        tgt: Dict[str, Any] = {"id": "t1", "provider": "google_places", "meta": {}}
        _copy_partner_enrichment_fields(src, tgt)
        assert tgt["provider"] == "viator"
        assert tgt["live_price"] == 85.0
        assert tgt["meta"]["viator_product_code"] == "12345P1"

    def test_copy_skips_enriched_target(self):
        src = {"provider": "viator", "live_price": 50.0, "meta": {}}
        tgt: Dict[str, Any] = {"provider": "viator", "live_price": 99.0, "meta": {}}
        _copy_partner_enrichment_fields(src, tgt)
        assert tgt["live_price"] == 99.0

    def test_copy_fills_missing_geo(self):
        src = {"provider": "viator", "geo": {"lat": -8.5, "lng": 115.2}, "meta": {}}
        tgt: Dict[str, Any] = {"provider": "google_places", "meta": {}}
        _copy_partner_enrichment_fields(src, tgt)
        assert tgt["geo"] == {"lat": -8.5, "lng": 115.2}

    def test_copy_keeps_existing_geo(self):
        src = {"provider": "viator", "geo": {"lat": 0, "lng": 0}, "meta": {}}
        tgt: Dict[str, Any] = {
            "provider": "google_places",
            "geo": {"lat": -8.5, "lng": 115.2},
            "meta": {},
        }
        _copy_partner_enrichment_fields(src, tgt)
        assert tgt["geo"] == {"lat": -8.5, "lng": 115.2}
