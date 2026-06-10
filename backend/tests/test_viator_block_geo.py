"""Viator per-product geo pre-pass: placed Viator blocks get DISTINCT centers.

Decision (A): resolve each placed Viator product's FIRST itinerary POI ref via
GET /products/{code} -> POST /locations/bulk -> {lat,lng}. This gives every
placed Viator product a distinct pin instead of stacking them all on the
shared destination centroid.

Covers:
1. Two placed Viator blocks (distinct product codes) end up with DISTINCT
   coordinates that are the Viator-resolved centers (not the centroid).
2. Batching: N products -> exactly ONE POST /locations/bulk call.
3. Caching: a repeat build re-resolves nothing (no new product/bulk HTTP calls).
4. A block whose product yields no resolved center is left coord-less (no
   invented coords) and is not negatively cached (stays retryable).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import app.services.viator_provider as vp
from app.planner.coordinator import _resolve_viator_block_geo

_DESTINATION = "Bali, Indonesia"

# Destination centroid every coord-less Viator block would otherwise stack on.
_CENTROID = {"lat": -8.3405, "lng": 115.0920}  # Bali-ish

# Distinct real per-product centers, keyed by location ref.
_REF_CENTERS: dict[str, dict[str, float]] = {
    "loc_tulamben": {"lat": -8.2742, "lng": 115.5926},
    "loc_amed": {"lat": -8.3411, "lng": 115.6486},
    "loc_nusa_penida": {"lat": -8.7196, "lng": 115.4760},
}

# Product code -> first itinerary POI ref. "VPNOREF" deliberately has no POI ref.
_PRODUCT_REF: dict[str, str] = {
    "VP1": "loc_tulamben",
    "VP2": "loc_amed",
    "VP3": "loc_nusa_penida",
}


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.status_code = 200
        self._payload = payload

    def raise_for_status(self) -> None:  # noqa: D401
        return None

    def json(self) -> dict:
        return self._payload


class _RoutingViatorClient:
    """httpx.AsyncClient double routing by URL path: /products/{code} returns a
    product-detail body whose first itinerary POI carries a ref; /locations/bulk
    returns a center per known ref."""

    is_closed = False

    def __init__(self) -> None:
        self.product_calls: list[str] = []
        self.bulk_calls: list[list[str]] = []

    async def get(self, url, headers=None, timeout=None, **kwargs):  # noqa: ANN001
        code = url.rsplit("/", 1)[-1]
        self.product_calls.append(code)
        ref = _PRODUCT_REF.get(code)
        items = []
        if ref:
            items = [{"pointOfInterestLocation": {"location": {"ref": ref}}}]
        return _FakeResponse({"productCode": code, "itinerary": {"itineraryItems": items}})

    async def post(self, url, headers=None, json=None, timeout=None, **kwargs):  # noqa: ANN001
        refs = (json or {}).get("locations", [])
        self.bulk_calls.append(list(refs))
        locations = [
            {"reference": ref, "center": {"latitude": c["lat"], "longitude": c["lng"]}}
            for ref in refs
            if (c := _REF_CENTERS.get(ref))
        ]
        return _FakeResponse({"locations": locations})


def _viator_block(block_id: str, product_code: str) -> dict:
    """A placed Viator block: bookable + centroid-stacked geo, no real per-POI coord."""
    return {
        "id": block_id,
        "type": "activity",
        "summary": f"Activity {block_id}",
        "partner": "viator",
        "partner_product_id": product_code,
        "provider": "viator",
        "deeplink": "https://www.viator.com/tours/x",
        "coordinates": dict(_CENTROID),
    }


def _day_cards(blocks: list[dict]) -> list[dict]:
    return [{"title": "Day 1", "blocks": blocks}]


@pytest.fixture(autouse=True)
def _reset_viator(monkeypatch: pytest.MonkeyPatch):
    vp._viator_cb._failures = 0
    vp._viator_cb._open_until = 0.0
    vp._product_geo_cache._cache.clear()
    monkeypatch.setattr(vp.settings, "viator_enabled", True)
    monkeypatch.setattr(vp.settings, "viator_api_key", "fake-key")
    yield
    vp._product_geo_cache._cache.clear()


def _patches(client: _RoutingViatorClient):
    """Patch the shared client + L2 helpers (no DB in tests) + centroid geocode."""
    import app.tile_service.google_places_provider as gp

    async def _noop_l2_get(code: str):
        return None

    async def _noop_l2_set(code: str, geo: dict):
        return None

    async def _fake_geocode(dest: str):
        return (_CENTROID["lat"], _CENTROID["lng"])

    return (
        patch.object(vp, "_get_viator_client", new=AsyncMock(return_value=client)),
        patch.object(vp, "_product_geo_l2_get", new=AsyncMock(side_effect=_noop_l2_get)),
        patch.object(vp, "_product_geo_l2_set", new=AsyncMock(side_effect=_noop_l2_set)),
        patch.object(gp, "_geocode_destination_async", new=AsyncMock(side_effect=_fake_geocode)),
    )


@pytest.mark.asyncio
async def test_placed_viator_blocks_get_distinct_centers():
    client = _RoutingViatorClient()
    blocks = [_viator_block("b1", "VP1"), _viator_block("b2", "VP2")]
    day_cards = _day_cards(blocks)

    p = _patches(client)
    with p[0], p[1], p[2], p[3]:
        await _resolve_viator_block_geo(day_cards, _DESTINATION)

    c1 = day_cards[0]["blocks"][0]["coordinates"]
    c2 = day_cards[0]["blocks"][1]["coordinates"]

    # Distinct, non-centroid, Viator-resolved coords.
    assert (c1["lat"], c1["lng"]) != (c2["lat"], c2["lng"])
    assert (c1["lat"], c1["lng"]) != (_CENTROID["lat"], _CENTROID["lng"])
    assert (c2["lat"], c2["lng"]) != (_CENTROID["lat"], _CENTROID["lng"])
    assert c1 == _REF_CENTERS["loc_tulamben"]
    assert c2 == _REF_CENTERS["loc_amed"]

    # Batching: N products fetched, but exactly ONE bulk resolve call.
    assert sorted(client.product_calls) == ["VP1", "VP2"]
    assert len(client.bulk_calls) == 1
    assert sorted(client.bulk_calls[0]) == ["loc_amed", "loc_tulamben"]


@pytest.mark.asyncio
async def test_repeat_build_uses_cache_no_new_http():
    client = _RoutingViatorClient()
    p = _patches(client)

    dc1 = _day_cards([_viator_block("b1", "VP1"), _viator_block("b2", "VP2")])
    with p[0], p[1], p[2], p[3]:
        await _resolve_viator_block_geo(dc1, _DESTINATION)
    assert len(client.product_calls) == 2
    assert len(client.bulk_calls) == 1

    # Second build, same product codes -> L1 cache hit, no new HTTP.
    dc2 = _day_cards([_viator_block("b1", "VP1"), _viator_block("b2", "VP2")])
    with p[0], p[1], p[2], p[3]:
        await _resolve_viator_block_geo(dc2, _DESTINATION)
    assert len(client.product_calls) == 2  # unchanged
    assert len(client.bulk_calls) == 1  # unchanged

    coords = [b["coordinates"] for b in dc2[0]["blocks"]]
    assert coords[0] == _REF_CENTERS["loc_tulamben"]
    assert coords[1] == _REF_CENTERS["loc_amed"]


@pytest.mark.asyncio
async def test_unresolved_block_left_coordless_not_negatively_cached():
    client = _RoutingViatorClient()
    # VPNOREF yields a product detail with no POI ref -> no center resolved.
    blocks = [_viator_block("b1", "VP1"), _viator_block("b2", "VPNOREF")]
    day_cards = _day_cards(blocks)

    p = _patches(client)
    with p[0], p[1], p[2], p[3]:
        await _resolve_viator_block_geo(day_cards, _DESTINATION)

    # VP1 resolved to a distinct center.
    assert day_cards[0]["blocks"][0]["coordinates"] == _REF_CENTERS["loc_tulamben"]
    # VPNOREF left on its existing fallback (the centroid) -- no invented coords.
    assert day_cards[0]["blocks"][1]["coordinates"] == _CENTROID
    # Not negatively cached: VPNOREF is absent from L1 (a later retry can resolve it).
    assert vp._product_geo_cache.get("VPNOREF") is None


@pytest.mark.asyncio
async def test_non_viator_block_skipped():
    """A GYG (non-Viator) block must NOT be sent to the Viator API."""
    client = _RoutingViatorClient()
    gyg_block = {
        "id": "g1",
        "type": "activity",
        "summary": "GYG activity",
        "partner": "gyg",
        "partner_product_id": "GYG999",
        "provider": "gyg",
        "coordinates": dict(_CENTROID),
    }
    day_cards = _day_cards([gyg_block])

    p = _patches(client)
    with p[0], p[1], p[2], p[3]:
        await _resolve_viator_block_geo(day_cards, _DESTINATION)

    assert client.product_calls == []
    assert client.bulk_calls == []
    assert day_cards[0]["blocks"][0]["coordinates"] == _CENTROID


def _production_shape_block(block_id: str, product_code: str) -> dict:
    """Mirror _apply_activity_tile_enrichment_to_day_cards output exactly.

    Production blocks do NOT carry partner/provider/partner_product_id at the
    top level -- the Viator code lives only inside ``booked_tile``. This is the
    only block shape that actually reaches the geo pre-pass in production, so it
    must exercise the ``booked_tile`` branch of _viator_product_code_from_block.
    """
    return {
        "id": block_id,
        "type": "activity",
        "summary": f"Activity {block_id}",
        # Only a viator deeplink at the top level (no partner/provider/product id).
        "deeplink": "https://www.viator.com/tours/x",
        "coordinates": dict(_CENTROID),
        "booked_tile": {
            "id": f"viator_{product_code}",
            "partner": "viator",
            "provider": "viator",
            "partner_product_id": product_code,
            "meta": {"viator_product_code": product_code},
        },
    }


@pytest.mark.asyncio
async def test_pipeline_booked_tile_blocks_get_distinct_centers_no_gp():
    """End-to-end through _run_itinerary_enrichment_pipeline with production-shape
    blocks (Viator code only in booked_tile): blocks get distinct Viator centers
    and Google Places never fires for them (the geo pre-pass resolved real coords
    so the GP gate skips them)."""
    from app.planner.coordinator import _run_itinerary_enrichment_pipeline

    client = _RoutingViatorClient()
    blocks = [
        _production_shape_block("b1", "VP1"),
        _production_shape_block("b2", "VP2"),
    ]
    day_cards = _day_cards(blocks)

    gp_calls: list[str] = []

    async def _gp_should_not_run(*args, **kwargs):  # noqa: ANN002, ANN003
        gp_calls.append("called")
        return None

    p = _patches(client)
    with (
        p[0],
        p[1],
        p[2],
        p[3],
        # GP must NOT fire for Viator-resolved blocks; assert via this spy.
        patch(
            "app.planner.coordinator._post_build_enrich_placed_activities",
            new=AsyncMock(side_effect=_gp_should_not_run),
        ),
    ):
        result = await _run_itinerary_enrichment_pipeline(
            trip_plan={"destination": _DESTINATION, "adults": 2},
            activity_tiles=[],  # thin pool: partner-enrich branch skipped, geo pre-pass still runs
            day_cards=day_cards,
            session_id="sess-1",
        )

    out = result["day_cards"][0]["blocks"]
    c1, c2 = out[0]["coordinates"], out[1]["coordinates"]

    # booked_tile branch resolved distinct, non-centroid Viator centers.
    assert c1 == _REF_CENTERS["loc_tulamben"]
    assert c2 == _REF_CENTERS["loc_amed"]
    assert (c1["lat"], c1["lng"]) != (c2["lat"], c2["lng"])
    # Batching held: one bulk call for both products.
    assert len(client.bulk_calls) == 1
    # GP did not fire: every placed block already had a real per-POI coord.
    assert gp_calls == []
