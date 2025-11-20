from datetime import date
from typing import List

from app.schemas import Geo, Tile

from .models import SearchContext
from .provider_base import Provider


class MockHotelProvider(Provider):
    name = "mock_hotel"

    def _nights(self, ctx: SearchContext) -> int | None:
        if not ctx.start_date or not ctx.end_date:
            return None
        try:
            start = date.fromisoformat(ctx.start_date)
            end = date.fromisoformat(ctx.end_date)
        except ValueError:
            return None

        delta = (end - start).days
        return delta if delta > 0 else None

    def search(self, ctx: SearchContext) -> List[Tile]:
        """Return simple mock hotels for the given destination."""
        dest = ctx.destination or "Somewhere"
        tiles: List[Tile] = []

        nights = self._nights(ctx)
        # Lightly adjust pricing based on budget and party size to make inputs matter.
        budget_multiplier = {
            "budget": 0.85,
            "mid": 1.0,
            "premium": 1.25,
            "luxury": 1.5,
        }.get((ctx.budget_bucket or "").lower(), 1.0)
        group_multiplier = max((ctx.group_size or 2) / 2, 0.5)
        subtitle_prefix = f"{nights} nights" if nights else "Flexible stay"
        trip_type_label = ctx.trip_type.replace("_", " ") if ctx.trip_type else "trip"
        source_mode = "live" if (ctx.response_mode or "").startswith("live") else "cache"

        base_count = ctx.max_results_per_vertical
        for i in range(1, base_count + 1):
            price = (280 + 25 * i) * budget_multiplier * group_multiplier
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
                    tags=["central", "mock", *ctx.vibes],
                    availability_status="available" if source_mode == "live" else "unknown",
                    meta={
                        "refundable": True,
                        "group_size": ctx.group_size,
                        "vibes": ctx.vibes,
                    },
                    score=0.7 + 0.05 * i,
                    source=source_mode,
                )
            )

        return tiles
