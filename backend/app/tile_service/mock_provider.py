from typing import List

from app.schemas import Geo, Tile

from .models import SearchContext
from .provider_base import Provider


class MockHotelProvider(Provider):
    name = "mock_hotel"

    def search(self, ctx: SearchContext) -> List[Tile]:
        """Return simple mock hotels for the given destination."""
        dest = ctx.destination or "Somewhere"
        tiles: List[Tile] = []

        # Only respond if hotels are requested
        if "hotel" not in ctx.verticals:
            return tiles

        count = ctx.max_results_per_vertical
        for i in range(1, count + 1):
            tiles.append(
                Tile(
                    id=f"tile_mock_hotel_{i}",
                    type="hotel",
                    partner=self.name,
                    partner_product_id=f"mock_prop_{i}",
                    title=f"Mock Hotel {i} in {dest}",
                    subtitle="3 nights · central area",
                    image_url="https://picsum.photos/400/250",
                    price_estimate=280 + 25 * i,
                    live_price=None,
                    currency=ctx.currency,
                    price_basis="per_trip",
                    is_estimate_only=True,
                    deeplink_url="https://example.com/hotel/mock?aff_id=DEMO",
                    rating=4.0 + 0.1 * i,
                    review_count=100 * i,
                    location_label=f"Central {dest}",
                    geo=Geo(lat=38.72 + 0.01 * i, lon=-9.13),
                    tags=["central", "mock"],
                    availability_status="unknown",
                    meta={"refundable": True},
                    score=0.7 + 0.05 * i,
                    source="cache",
                )
            )

        return tiles
