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

        source_mode = "live" if (ctx.response_mode or "").startswith("live") else "cache"

        base_count = ctx.max_results_per_vertical
        for i in range(1, base_count + 1):
            price = 280 + 25 * i
            subtitle_prefix = "Flexible stay"
            trip_type_label = "trip"
            tiles.append(
                Tile(
                    id=f"tile_mock_hotel_{i}",
                    type="hotel",
                    partner=self.name,
                    partner_product_id=f"mock_prop_{i}",
                    title=f"Mock Hotel {i} in {dest}",
                    subtitle=f"{subtitle_prefix} · {trip_type_label}",
                    image_url="https://picsum.photos/400/250",
                    price_estimate=round(price, 2),
                    live_price=None if source_mode == "cache" else round(price * 1.05, 2),
                    currency=ctx.currency,
                    price_basis="per_trip",
                    is_estimate_only=source_mode == "cache",
                    deeplink_url="https://example.com/hotel/mock?aff_id=DEMO",
                    rating=4.0 + 0.1 * i,
                    review_count=100 * i,
                    location_label=f"Central {dest}",
                    geo=Geo(lat=38.72 + 0.01 * i, lon=-9.13),
                    tags=["central", "mock"],
                    availability_status="available" if source_mode == "live" else "unknown",
                    meta={
                        "refundable": True,
                        "destination": dest,
                    },
                    score=0.7 + 0.05 * i,
                    source=source_mode,
                )
            )

        return tiles
