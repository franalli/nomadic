import uuid
from typing import List
from .schemas import TilesSearchRequest, TilesSearchResponse, Tile, Geo


def _mock_hotel_tile(dest: str, idx: int) -> Tile:
    return Tile(
        id=f"tile_hotel_{idx}",
        type="hotel",
        partner="mock_booking",
        partner_product_id=f"mock_prop_{idx}",
        title=f"Mock Hotel {idx} in {dest}",
        subtitle="3 nights · central area",
        image_url="https://picsum.photos/400/250",
        price_estimate=280 + 25 * idx,
        live_price=None,
        currency="EUR",
        price_basis="per_trip",
        is_estimate_only=True,
        deeplink_url="https://example.com/hotel/mock?aff_id=DEMO",
        rating=4.0 + 0.1 * idx,
        review_count=100 * idx,
        location_label=f"Central {dest}",
        geo=Geo(lat=38.72 + 0.01 * idx, lon=-9.13),
        tags=["central", "mock"],
        availability_status="unknown",
        meta={"refundable": True},
        score=0.7 + 0.05 * idx,
        source="cache",
    )


def search_tiles(req: TilesSearchRequest) -> TilesSearchResponse:
    request_id = uuid.uuid4().hex
    dest = req.destination or "Somewhere"

    tiles: List[Tile] = []
    if "hotel" in req.verticals:
        for i in range(1, req.max_results_per_vertical + 1):
            tiles.append(_mock_hotel_tile(dest, i))

    summary = {
        "verticals_returned": sorted({t.type for t in tiles}),
        "min_price_estimate": min(
            (t.price_estimate for t in tiles if t.price_estimate is not None),
            default=None,
        ),
        "max_price_estimate": max(
            (t.price_estimate for t in tiles if t.price_estimate is not None),
            default=None,
        ),
    }

    return TilesSearchResponse(request_id=request_id, tiles=tiles, summary=summary)
