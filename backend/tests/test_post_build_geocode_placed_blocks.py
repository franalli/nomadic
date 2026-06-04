"""
Path B regression tests: geocode placed activity blocks by title so every
placed POI carries a distinct, real coordinate -> distinct map markers.

Covers the three bug sites fixed in coordinator._post_build_enrich_placed_activities
and the _run_itinerary_enrichment_pipeline skip gate:

1. A placed specialist/Viator block with NO real coords (None or destination
   centroid) gets geocoded by title -> real geo (not None, not the centroid).
2. Two distinct titles resolve to two distinct coordinates (no centroid stacking).
3. Geocode results are cached: the Places search fires once per distinct title
   across repeat builds.
4. The skip gate no longer treats partner deeplink/image with centroid-only geo
   as "already enriched".
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import app.tile_service.google_places_provider as provider
from app.planner.coordinator import (
    _is_centroid_coords,
    _post_build_enrich_placed_activities,
    _run_itinerary_enrichment_pipeline,
)

# Destination centroid every coord-less Viator/specialist tile would be stamped with.
_CENTROID = (-8.3405, 115.0920)  # Bali-ish (lat, lng)

# Distinct, real per-POI coords keyed by the GP search title fragment.
_POI_COORDS: dict[str, tuple[float, float]] = {
    "usat liberty shipwreck": (-8.2742, 115.5926),  # Tulamben (lat, lng)
    "jemeluk bay coral garden": (-8.3411, 115.6486),  # Amed
    "crystal bay shallow reef": (-8.7196, 115.4760),  # Nusa Penida
    "manta point cleaning station": (-8.7969, 115.5390),  # Nusa Penida SW
    "gili biaha cave reef": (-8.3950, 115.6620),  # Candidasa
}


def _match_poi(text_query: str) -> tuple[float, float] | None:
    q = text_query.lower()
    for frag, coords in _POI_COORDS.items():
        if frag in q:
            return coords
    return None


@pytest.fixture(autouse=True)
def _clear_state():
    provider._enrich_mem.clear()
    provider._enrich_inflight.clear()
    provider.clear_geocode_caches()
    provider._places_http_client = None
    provider.clear_google_places_circuit_breaker()
    yield
    provider._enrich_mem.clear()
    provider._enrich_inflight.clear()
    provider.clear_geocode_caches()
    provider._places_http_client = None


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.status_code = 200
        self._payload = payload
        self.text = ""
        self.headers: dict[str, str] = {}

    def json(self) -> dict:
        return self._payload


class _CountingPlacesClient:
    """httpx.AsyncClient double that records one call per distinct text query and
    returns a distinct GP place for known POI titles."""

    is_closed = False

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def post(self, url, headers=None, json=None, **kwargs):  # noqa: ANN001
        text_query = (json or {}).get("textQuery", "")
        self.queries.append(text_query)
        coords = _match_poi(text_query)
        if coords is None:
            return _FakeResponse({"places": []})
        lat, lng = coords
        # GP displayName must token-overlap the query so the relevance gate passes.
        display = text_query
        return _FakeResponse(
            {
                "places": [
                    {
                        "id": f"gp_{abs(hash(text_query)) % 100000}",
                        "displayName": {"text": display},
                        "location": {"latitude": lat, "longitude": lng},
                        "googleMapsUri": "https://maps.google/x",
                    }
                ]
            }
        )


def _make_block(block_id: str, summary: str, coordinates) -> dict:
    """A placed specialist/Viator block: partner deeplink + image but only
    centroid-level (or no) geo."""
    return {
        "id": block_id,
        "type": "activity",
        "summary": summary,
        "deeplink": "https://www.viator.com/tours/x",
        "image_url": "https://cache.viator.com/x.jpg",
        "coordinates": coordinates,
    }


def _day_cards(blocks: list[dict]) -> list[dict]:
    return [{"title": "Day 1", "blocks": blocks}]


def _patches(client: _CountingPlacesClient, l2_store: dict):
    async def _fake_get_cache(cache_key: str):
        return l2_store.get(cache_key)

    async def _fake_set_cache(cache_key: str, payload: dict):
        l2_store[cache_key] = payload

    async def _fake_geocode(dest: str):
        return _CENTROID

    return (
        patch.object(provider.settings, "use_google_places_provider", True),
        patch.object(provider.settings, "google_places_enrichment_enabled", True),
        patch.object(provider.settings, "google_maps_api_key", "fake-key"),
        patch.object(
            provider, "_geocode_destination_async", new=AsyncMock(side_effect=_fake_geocode)
        ),
        patch.object(provider, "_get_places_http_client", new=AsyncMock(return_value=client)),
        patch.object(
            provider, "_get_cached_enrichment", new=AsyncMock(side_effect=_fake_get_cache)
        ),
        patch.object(
            provider, "_set_cached_enrichment", new=AsyncMock(side_effect=_fake_set_cache)
        ),
        patch.object(provider, "reserve_places_spend_or_raise", return_value=None),
        patch.object(provider, "_enrich_retry_attempts", return_value=1),
    )


def test_is_centroid_coords_detects_centroid_and_real_poi():
    # Missing coords -> centroid (needs geocode)
    assert _is_centroid_coords(None, _CENTROID) is True
    # Exact centroid -> centroid
    assert _is_centroid_coords({"lat": _CENTROID[0], "lng": _CENTROID[1]}, _CENTROID) is True
    # Real distinct POI (Tulamben, ~70km away) -> NOT centroid
    tulamben = _POI_COORDS["usat liberty shipwreck"]
    assert _is_centroid_coords({"lat": tulamben[0], "lng": tulamben[1]}, _CENTROID) is False
    # [lng, lat] list form of centroid -> centroid
    assert _is_centroid_coords([_CENTROID[1], _CENTROID[0]], _CENTROID) is True
    # No centroid known -> only coord-less counts as centroid
    assert _is_centroid_coords(None, None) is True
    assert _is_centroid_coords({"lat": 1.0, "lng": 2.0}, None) is False


@pytest.mark.asyncio
async def test_placed_specialist_blocks_get_distinct_real_coords():
    client = _CountingPlacesClient()
    l2_store: dict = {}

    blocks = [
        _make_block("b1", "USAT Liberty Shipwreck Shore Dive", None),
        # Centroid-stacked Viator block (same dest center as the other)
        _make_block(
            "b2",
            "Jemeluk Bay Coral Garden Boat Dive",
            {"lat": _CENTROID[0], "lng": _CENTROID[1]},
        ),
    ]
    state = {
        "trip_plan": {"destination": "Bali, Indonesia", "adults": 2},
        "tiles": {"activities": []},
        "session_id": "sess-1",
    }
    day_cards = _day_cards(blocks)

    p = _patches(client, l2_store)
    with p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7], p[8]:
        await _post_build_enrich_placed_activities(state, day_cards)

    out = day_cards[0]["blocks"]
    c1 = out[0]["coordinates"]
    c2 = out[1]["coordinates"]

    # Both placed blocks now carry a real (non-None) coordinate.
    assert c1 is not None and c2 is not None
    # Neither is the destination centroid.
    assert not _is_centroid_coords(c1, _CENTROID)
    assert not _is_centroid_coords(c2, _CENTROID)
    # Two distinct titles -> two distinct coordinates (no centroid stacking).
    assert (c1["lat"], c1["lng"]) != (c2["lat"], c2["lng"])
    # They match the real POI coords we geocoded by title.
    assert (round(c1["lat"], 4), round(c1["lng"], 4)) == (
        round(_POI_COORDS["usat liberty shipwreck"][0], 4),
        round(_POI_COORDS["usat liberty shipwreck"][1], 4),
    )


@pytest.mark.asyncio
async def test_geocode_results_cached_across_repeat_builds():
    client = _CountingPlacesClient()
    l2_store: dict = {}

    def _fresh_blocks() -> list[dict]:
        return [
            _make_block("b1", "USAT Liberty Shipwreck Shore Dive", None),
            _make_block("b2", "Jemeluk Bay Coral Garden Boat Dive", None),
            _make_block("b3", "Crystal Bay Shallow Reef Exploration", None),
        ]

    state = {
        "trip_plan": {"destination": "Bali, Indonesia", "adults": 2},
        "tiles": {"activities": []},
        "session_id": "sess-1",
    }

    p = _patches(client, l2_store)

    # First build: one Places search per distinct title (3 calls).
    dc1 = _day_cards(_fresh_blocks())
    with p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7], p[8]:
        await _post_build_enrich_placed_activities(state, dc1)
    assert len(client.queries) == 3

    # Second build (same titles): cache hit, no new Places searches.
    dc2 = _day_cards(_fresh_blocks())
    with p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7], p[8]:
        await _post_build_enrich_placed_activities(state, dc2)
    assert len(client.queries) == 3  # unchanged -> cached

    # Distinct coords still applied from cache on the rebuild.
    coords = [b["coordinates"] for b in dc2[0]["blocks"]]
    seen = {(c["lat"], c["lng"]) for c in coords}
    assert len(seen) == 3


@pytest.mark.asyncio
async def test_all_placed_blocks_geocoded_beyond_default_cap():
    """The placed-block pass lifts the default enrichment_cap (3) so EVERY placed
    POI gets a distinct coordinate, even for >3-activity plans. Leave the default
    cap in place to prove the per-call enrich_cap override is what does the work."""
    client = _CountingPlacesClient()
    l2_store: dict = {}

    blocks = [
        _make_block("b1", "USAT Liberty Shipwreck Shore Dive", None),
        _make_block("b2", "Jemeluk Bay Coral Garden Boat Dive", None),
        _make_block("b3", "Crystal Bay Shallow Reef Exploration", None),
        _make_block("b4", "Manta Point Cleaning Station Dive", None),
        _make_block("b5", "Gili Biaha Cave Reef Dive", None),
    ]
    state = {
        "trip_plan": {"destination": "Bali, Indonesia", "adults": 2},
        "tiles": {"activities": []},
        "session_id": "sess-1",
    }
    day_cards = _day_cards(blocks)

    p = _patches(client, l2_store)
    # NOTE: default settings.google_places_enrichment_cap (=3) is intentionally NOT
    # patched. If the pass respected it, only 3 blocks would geocode and this fails.
    assert provider.settings.google_places_enrichment_cap == 3
    with p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7], p[8]:
        await _post_build_enrich_placed_activities(state, day_cards)

    out = day_cards[0]["blocks"]
    # All 5 placed blocks geocoded -> 5 Places searches (one per distinct title).
    assert len(client.queries) == 5
    coords = [b["coordinates"] for b in out]
    assert all(c is not None for c in coords)
    assert all(not _is_centroid_coords(c, _CENTROID) for c in coords)
    # 5 distinct POIs -> 5 distinct coordinates (no centroid stacking / cap-drop).
    seen = {(c["lat"], c["lng"]) for c in coords}
    assert len(seen) == 5


@pytest.mark.asyncio
async def test_ungeocodable_blocks_left_coordless_no_centroid_stamp():
    """Un-geocodable generic multi-stop marketing tours (no single POI) must be
    left coord-less — NOT stamped with the destination centroid (which would
    collapse them onto one point and re-stack the map). Geocodable blocks in the
    same plan must still get their real distinct per-POI coords."""
    client = _CountingPlacesClient()
    l2_store: dict = {}

    blocks = [
        # Geocodable: a real POI dive -> distinct real coords.
        _make_block("b1", "USAT Liberty Shipwreck Shore Dive", None),
        # Un-geocodable generic marketing tours: titles match no POI fragment, so
        # _match_poi returns None and the Places search yields no place. These are
        # exactly the live-verification offenders that used to all collapse onto
        # the destination centroid via the last-resort fallback.
        _make_block("b2", "Bali BEST Things to Do Private Full-day Tour", None),
        _make_block("b3", "Bali Shore Excursions: Private Car Rental", None),
    ]
    state = {
        "trip_plan": {"destination": "Bali, Indonesia", "adults": 2},
        "tiles": {"activities": []},
        "session_id": "sess-1",
    }
    day_cards = _day_cards(blocks)

    p = _patches(client, l2_store)
    with p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7], p[8]:
        await _post_build_enrich_placed_activities(state, day_cards)

    out = day_cards[0]["blocks"]
    c1, c2, c3 = (b["coordinates"] for b in out)

    # Geocodable block: real distinct per-POI coords (NOT centroid, NOT None).
    assert c1 is not None
    assert not _is_centroid_coords(c1, _CENTROID)
    assert (round(c1["lat"], 4), round(c1["lng"], 4)) == (
        round(_POI_COORDS["usat liberty shipwreck"][0], 4),
        round(_POI_COORDS["usat liberty shipwreck"][1], 4),
    )

    # Un-geocodable blocks: left coord-less. No centroid stamp -> no map pin ->
    # nothing to re-stack. (Previously the last-resort fallback stamped both with
    # the destination centroid, collapsing them onto one point.)
    assert c2 is None
    assert c3 is None


@pytest.mark.asyncio
async def test_skip_gate_does_not_skip_centroid_only_blocks():
    """The pipeline gate must NOT skip GP enrichment when placed blocks have
    partner deeplink/image but only centroid-level geo."""
    client = _CountingPlacesClient()
    l2_store: dict = {}

    blocks = [
        _make_block(
            "b1",
            "USAT Liberty Shipwreck Shore Dive",
            {"lat": _CENTROID[0], "lng": _CENTROID[1]},
        ),
    ]
    day_cards = _day_cards(blocks)
    trip_plan = {"destination": "Bali, Indonesia", "adults": 2}

    p = _patches(client, l2_store)
    # No partner providers configured -> only the GP centroid-geocode path runs.
    with (
        p[0],
        p[1],
        p[2],
        p[3],
        p[4],
        p[5],
        p[6],
        p[7],
        p[8],
        patch.object(provider.settings, "viator_enabled", False),
        patch.object(provider.settings, "get_your_guide_enabled", False),
    ):
        result = await _run_itinerary_enrichment_pipeline(
            trip_plan=trip_plan,
            activity_tiles=[],
            day_cards=day_cards,
            session_id="sess-1",
        )

    # The gate fired the geocode pass (it did not skip), and the block now has
    # the real POI coordinate instead of the centroid.
    assert client.queries, "expected a Places search (gate must not skip centroid-only blocks)"
    c = result["day_cards"][0]["blocks"][0]["coordinates"]
    assert not _is_centroid_coords(c, _CENTROID)
