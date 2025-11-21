from datetime import date, datetime
from typing import List, Optional

from app.schemas import Geo, Tile

from .models import SearchContext
from .provider_base import Provider


class MockHotelProvider(Provider):
    name = "mock_hotel"

    @staticmethod
    def _parse_date(value: Optional[str]) -> Optional[date]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value).date()
        except Exception:
            return None

    def _estimate_nights(self, ctx: SearchContext) -> int:
        start = self._parse_date(ctx.start_date)
        end = self._parse_date(ctx.end_date)
        if start and end and end > start:
            return max((end - start).days, 1)
        return 4

    def _subtitle(self, ctx: SearchContext, nights: int, travelers: int) -> str:
        start = self._parse_date(ctx.start_date)
        end = self._parse_date(ctx.end_date)
        if start and end and end > start:
            date_part = f"{start.strftime('%b %d')}–{end.strftime('%b %d')}"
        elif start:
            date_part = f"{start.strftime('%b %d')} (flexible)"
        else:
            date_part = "Flexible stay"
        traveler_part = f"{travelers} traveler{'s' if travelers != 1 else ''}"
        return f"{date_part} · {nights} nights · {traveler_part}"

    def search(self, ctx: SearchContext) -> List[Tile]:
        """Return simple mock hotels for the given destination."""
        dest = ctx.destination or "Somewhere"
        tiles: List[Tile] = []

        source_mode = "live" if (ctx.response_mode or "").startswith("live") else "cache"
        travelers = ctx.traveler_count or 2
        nights = self._estimate_nights(ctx)

        base_count = ctx.max_results_per_vertical
        for i in range(1, base_count + 1):
            nightly_rate = 120 + 18 * i
            price = round(nightly_rate * max(nights, 1) * (1 + 0.08 * max(travelers - 1, 0)), 2)
            tiles.append(
                Tile(
                    id=f"tile_mock_hotel_{i}",
                    type="hotel",
                    partner=self.name,
                    partner_product_id=f"mock_prop_{i}",
                    title=f"Mock Hotel {i} in {dest}",
                    subtitle=self._subtitle(ctx, nights, travelers),
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
                        "origin": ctx.origin,
                        "start_date": ctx.start_date,
                        "end_date": ctx.end_date,
                        "traveler_count": travelers,
                        "nights": nights,
                    },
                    score=0.7 + 0.05 * i,
                    source=source_mode,
                )
            )

        return tiles
