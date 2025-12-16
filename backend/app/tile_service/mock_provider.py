import re
from datetime import date, datetime
from typing import List, Optional

from app.schemas import Geo, Tile

from .models import SearchContext
from .provider_base import Provider


def _parse_budget(value) -> Optional[float]:
    """Parse a budget value that may be a string or number."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # Remove currency symbols and commas, extract number
        cleaned = re.sub(r"[^\d.]", "", value)
        if cleaned:
            try:
                return float(cleaned)
            except ValueError:
                return None
    return None


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
        total_travelers = (ctx.adults or 0) + (ctx.children or 0) or 2
        nights = self._estimate_nights(ctx)

        # Calculate budget per category if budget is specified
        budget_limit = _parse_budget(ctx.budget_per_category)
        if not budget_limit:
            parsed_budget = _parse_budget(ctx.budget)
            if parsed_budget:
                # Allocate ~40% of total budget to hotels
                budget_limit = parsed_budget * 0.4

        base_count = ctx.max_results_per_vertical
        for i in range(1, base_count + 1):
            nightly_rate = 120 + 18 * i
            price = round(
                nightly_rate * max(nights, 1) * (1 + 0.08 * max(total_travelers - 1, 0)), 2
            )

            # Skip tiles that exceed budget (if budget is set)
            if budget_limit and price > budget_limit:
                continue

            tiles.append(
                Tile(
                    id=f"tile_mock_hotel_{i}",
                    type="hotel",
                    partner=self.name,
                    partner_product_id=f"mock_prop_{i}",
                    title=f"Mock Hotel {i} in {dest}",
                    subtitle=self._subtitle(ctx, nights, total_travelers),
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
                    tags=(
                        ["central", "mock", "within-budget"]
                        if budget_limit
                        else ["central", "mock"]
                    ),
                    availability_status="available" if source_mode == "live" else "unknown",
                    meta={
                        "refundable": True,
                        "destination": dest,
                        "origin": ctx.origin,
                        "start_date": ctx.start_date,
                        "end_date": ctx.end_date,
                        "adults": ctx.adults,
                        "children": ctx.children,
                        "nights": nights,
                        "budget_limit": budget_limit,
                    },
                    score=0.7 + 0.05 * i,
                    source=source_mode,
                )
            )

        return tiles


class MockFlightProvider(Provider):
    name = "mock_flight"

    def search(self, ctx: SearchContext) -> List[Tile]:
        """Return simple mock flights for the given route."""
        dest = ctx.destination or "Somewhere"
        origin = ctx.origin or "Home"
        tiles: List[Tile] = []

        source_mode = "live" if (ctx.response_mode or "").startswith("live") else "cache"
        total_travelers = (ctx.adults or 0) + (ctx.children or 0) or 1
        max_results = max(1, min(ctx.max_results_per_vertical, 3))

        # Calculate budget per category if budget is specified
        budget_limit = _parse_budget(ctx.budget_per_category)
        if not budget_limit:
            parsed_budget = _parse_budget(ctx.budget)
            if parsed_budget:
                # Allocate ~30% of total budget to flights
                budget_limit = parsed_budget * 0.3

        options = [
            {
                "title": "Morning express",
                "depart": "08:10",
                "duration": "7h 50m",
                "price": 610.0,
                "stops": "Nonstop",
                "image_url": "https://images.unsplash.com/photo-1489515217757-5fd1be406fef?auto=format&fit=crop&w=1200&q=80",
            },
            {
                "title": "Evening sleeper",
                "depart": "19:20",
                "duration": "9h 10m",
                "price": 480.0,
                "stops": "1 stop via AMS",
                "image_url": "https://images.unsplash.com/photo-1485939420040-3e4a274307d0?auto=format&fit=crop&w=1200&q=80",
            },
            {
                "title": "Weekend saver",
                "depart": "22:05",
                "duration": "11h 05m",
                "price": 420.0,
                "stops": "1 stop via LHR",
                "image_url": "https://images.unsplash.com/photo-1474302770737-173ee21bab63?auto=format&fit=crop&w=1200&q=80",
            },
        ]

        for idx, option in enumerate(options[:max_results]):
            base_price = option["price"]
            price = round(base_price * total_travelers, 2)

            # Skip tiles that exceed budget (if budget is set)
            if budget_limit and price > budget_limit:
                continue

            tiles.append(
                Tile(
                    id=f"tile_mock_flight_{idx + 1}",
                    type="flight",
                    partner=self.name,
                    partner_product_id=f"mock_flight_{idx + 1}",
                    title=f"{option['title']} · {origin} → {dest}",
                    subtitle=(
                        f"{option['depart']} departure · {option['duration']} · "
                        f"{option['stops']}"
                    ),
                    image_url=option["image_url"],
                    price_estimate=price,
                    live_price=None if source_mode == "cache" else round(price * 1.03, 2),
                    currency=ctx.currency,
                    price_basis="per_trip",
                    is_estimate_only=source_mode == "cache",
                    deeplink_url="https://example.com/flights/search?aff_id=DEMO",
                    rating=4.3 + 0.05 * idx,
                    review_count=120 + 35 * idx,
                    location_label=f"{origin} → {dest}",
                    tags=["flight", option["stops"]] + (["within-budget"] if budget_limit else []),
                    availability_status="available",
                    meta={
                        "stops": option["stops"],
                        "fare_class": "Main cabin",
                        "destination": dest,
                        "origin": origin,
                        "adults": ctx.adults,
                        "children": ctx.children,
                        "budget_limit": budget_limit,
                    },
                    score=0.65 + 0.05 * idx,
                    source=source_mode,
                )
            )

        return tiles


class MockActivityProvider(Provider):
    name = "mock_activity"

    def search(self, ctx: SearchContext) -> List[Tile]:
        """Return simple mock activities for the given destination."""
        dest = ctx.destination or "your destination"
        tiles: List[Tile] = []

        source_mode = "live" if (ctx.response_mode or "").startswith("live") else "cache"
        total_travelers = (ctx.adults or 0) + (ctx.children or 0) or 2
        max_results = max(1, min(ctx.max_results_per_vertical, 3))

        # Calculate budget per category if budget is specified
        budget_limit = _parse_budget(ctx.budget_per_category)
        if not budget_limit:
            parsed_budget = _parse_budget(ctx.budget)
            if parsed_budget:
                # Allocate ~30% of total budget to activities
                budget_limit = parsed_budget * 0.3

        activities = [
            {
                "title": f"Sunrise ridge hike in {dest}",
                "subtitle": "Guide-led, breakfast at the summit",
                "price": 95.0,
                "image_url": "https://images.unsplash.com/photo-1452626038306-9aae5e071dd3?auto=format&fit=crop&w=1200&q=80",
                "duration": "3h",
                "tag": "outdoors",
                "availability": "available",
            },
            {
                "title": f"Night market food crawl, {dest} center",
                "subtitle": "Street bites, rooftop nightcap, hidden alleys",
                "price": 68.0,
                "image_url": "https://images.unsplash.com/photo-1440404653325-ab127d49abb4?auto=format&fit=crop&w=1200&q=80",
                "duration": "2.5h",
                "tag": "food",
                "availability": "available",
            },
            {
                "title": f"Golden-hour harbor sail near {dest}",
                "subtitle": "Small group, bubbly on board, sunset views",
                "price": 125.0,
                "image_url": "https://images.unsplash.com/photo-1500375592092-40eb2168fd21?auto=format&fit=crop&w=1200&q=80",
                "duration": "2h",
                "tag": "water",
                "availability": "low",
            },
        ]

        for idx, activity in enumerate(activities[:max_results]):
            per_person = round(activity["price"], 2)
            total = round(per_person * total_travelers, 2)

            # Skip tiles that exceed budget (if budget is set)
            if budget_limit and total > budget_limit:
                continue

            tiles.append(
                Tile(
                    id=f"tile_mock_activity_{idx + 1}",
                    type="activity",
                    partner=self.name,
                    partner_product_id=f"mock_activity_{idx + 1}",
                    title=activity["title"],
                    subtitle=f"{activity['subtitle']} · {activity['duration']}",
                    image_url=activity["image_url"],
                    price_estimate=total,
                    live_price=None if source_mode == "cache" else round(total * 1.02, 2),
                    currency=ctx.currency,
                    price_basis="per_trip",
                    is_estimate_only=source_mode == "cache",
                    deeplink_url="https://example.com/activities/book?aff_id=DEMO",
                    rating=4.5 + 0.06 * idx,
                    review_count=220 + 55 * idx,
                    location_label=dest,
                    tags=["activity", activity["tag"]]
                    + (["within-budget"] if budget_limit else []),
                    availability_status=activity["availability"],
                    meta={
                        "duration": activity["duration"],
                        "destination": dest,
                        "adults": ctx.adults,
                        "children": ctx.children,
                        "budget_limit": budget_limit,
                    },
                    score=0.6 + 0.05 * idx,
                    source=source_mode,
                )
            )

        return tiles
