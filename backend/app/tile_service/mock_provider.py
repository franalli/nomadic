import hashlib
import re
from datetime import date, datetime
from typing import List, Optional

from app.schemas import Geo, Tile
from app.services.unsplash import get_image_url_sync

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


def _dest_hash(dest: str) -> str:
    """Generate a 6-char hash from destination for tile ID namespacing."""
    return hashlib.md5(dest.lower().strip().encode()).hexdigest()[:6]


class MockHotelProvider(Provider):
    name = "mock_hotel"

    # Mock amenities per hotel tier (higher index = more amenities)
    MOCK_AMENITIES = {
        1: ["wifi", "breakfast"],
        2: ["wifi", "breakfast", "parking"],
        3: ["wifi", "breakfast", "parking", "pool"],
        4: ["wifi", "breakfast", "parking", "pool", "gym"],
        5: ["wifi", "breakfast", "parking", "pool", "gym", "spa"],
    }

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

    def _get_hotel_rating(self, index: int) -> float:
        """Map hotel index to star rating (1-5 scale)."""
        # Hotels 1-2 are 3-star, 3-4 are 4-star, 5 is 5-star
        if index <= 2:
            return 3.0 + 0.2 * index
        elif index <= 4:
            return 4.0 + 0.1 * (index - 2)
        else:
            return 4.5 + 0.1 * (index - 4)

    def _get_hotel_stars(self, index: int) -> int:
        """Map hotel index to star category (integer 1-5)."""
        if index <= 2:
            return 3
        elif index <= 4:
            return 4
        else:
            return 5

    def _has_required_amenities(self, hotel_amenities: List[str], required: List[str]) -> bool:
        """Check if hotel has all required amenities."""
        if not required:
            return True
        hotel_set = set(a.lower() for a in hotel_amenities)
        required_set = set(a.lower() for a in required)
        return required_set.issubset(hotel_set)

    def search(self, ctx: SearchContext) -> List[Tile]:
        """Return simple mock hotels for the given destination."""
        dest = ctx.destination or "Somewhere"
        dest_id = _dest_hash(dest)
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

        # Extract hotel settings for filtering
        # Handle both dict and HotelSettings model
        min_stars = 0
        required_amenities: List[str] = []
        if ctx.hotel_settings:
            if isinstance(ctx.hotel_settings, dict):
                min_stars = ctx.hotel_settings.get("min_stars") or 0
                required_amenities = ctx.hotel_settings.get("amenities") or []
            else:
                min_stars = ctx.hotel_settings.min_stars or 0
                required_amenities = ctx.hotel_settings.amenities or []

        base_count = ctx.max_results_per_vertical
        for i in range(1, base_count + 1):
            hotel_stars = self._get_hotel_stars(i)
            hotel_amenities = self.MOCK_AMENITIES.get(i, ["wifi"])

            # Filter by minimum stars
            if min_stars > 0 and hotel_stars < min_stars:
                continue

            # Filter by required amenities
            if not self._has_required_amenities(hotel_amenities, required_amenities):
                continue

            nightly_rate = 120 + 18 * i
            price = round(
                nightly_rate * max(nights, 1) * (1 + 0.08 * max(total_travelers - 1, 0)), 2
            )

            # Skip tiles that exceed budget (if budget is set)
            if budget_limit and price > budget_limit:
                continue

            # Expedia compliance: calculate taxes and fees
            tax_and_service = round(price * 0.12, 2)  # ~12% taxes/service fees
            property_fee = round(nights * 15, 2)  # ~$15/night property fee
            total_inclusive = round(price + tax_and_service + property_fee, 2)
            is_refundable = i <= 3  # First 3 hotels are refundable

            tiles.append(
                Tile(
                    id=f"tile_mock_hotel_{dest_id}_{i}",
                    type="hotel",
                    partner=self.name,
                    partner_product_id=f"mock_prop_{i}",
                    title=f"Mock Hotel {i} in {dest}",
                    subtitle=self._subtitle(ctx, nights, total_travelers),
                    image_url=get_image_url_sync(dest, variant=i % 6, width=400, height=250),
                    price_estimate=round(price, 2),
                    live_price=None if source_mode == "cache" else round(price * 1.05, 2),
                    currency=ctx.currency,
                    price_basis="per_trip",
                    is_estimate_only=source_mode == "cache",
                    deeplink_url="https://example.com/hotel/mock?aff_id=DEMO",
                    rating=self._get_hotel_rating(i),
                    review_count=100 * i,
                    location_label=f"Central {dest}",
                    geo=Geo(lat=38.72 + 0.01 * i, lon=-9.13),
                    tags=(
                        ["central", "mock", f"{hotel_stars}-star", "within-budget"]
                        if budget_limit
                        else ["central", "mock", f"{hotel_stars}-star"]
                    ),
                    availability_status="available" if source_mode == "live" else "unknown",
                    meta={
                        "refundable": is_refundable,
                        "destination": dest,
                        "origin": ctx.origin,
                        "start_date": ctx.start_date,
                        "end_date": ctx.end_date,
                        "adults": ctx.adults,
                        "children": ctx.children,
                        "nights": nights,
                        "budget_limit": budget_limit,
                        "stars": hotel_stars,
                        "amenities": hotel_amenities,
                    },
                    score=0.7 + 0.05 * i,
                    source=source_mode,
                    # Expedia Rapid API compliance fields
                    total_inclusive=total_inclusive,
                    tax_and_service_fee=tax_and_service,
                    property_fee=property_fee,
                    is_refundable=is_refundable,
                    cancel_policy_summary=(
                        "Free cancellation until 24h before check-in"
                        if is_refundable
                        else "Non-refundable rate"
                    ),
                    provider="expedia",
                )
            )

        return tiles


class MockFlightProvider(Provider):
    name = "mock_flight"

    # Price multipliers for cabin classes
    CABIN_MULTIPLIERS = {
        "economy": 1.0,
        "premium_economy": 1.5,
        "business": 3.0,
        "first": 5.0,
    }

    def search(self, ctx: SearchContext) -> List[Tile]:
        """Return simple mock flights for the given route."""
        dest = ctx.destination or "Somewhere"
        dest_id = _dest_hash(dest)
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

        # Extract flight settings for filtering
        # Handle both dict and FlightSettings model
        cabin_class = "economy"
        direct_only = False
        round_trip = True
        if ctx.flight_settings:
            if isinstance(ctx.flight_settings, dict):
                cabin_class = ctx.flight_settings.get("cabin_class") or "economy"
                direct_only = ctx.flight_settings.get("direct_only") or False
                round_trip = ctx.flight_settings.get("round_trip", True)
            else:
                cabin_class = ctx.flight_settings.cabin_class or "economy"
                direct_only = ctx.flight_settings.direct_only or False
                round_trip = (
                    ctx.flight_settings.round_trip
                    if ctx.flight_settings.round_trip is not None
                    else True
                )

        cabin_multiplier = self.CABIN_MULTIPLIERS.get(cabin_class, 1.0)

        options = [
            {
                "title": "Morning express",
                "depart": "08:10",
                "duration": "7h 50m",
                "base_price": 610.0,
                "stops": "Nonstop",
                "is_direct": True,
                "image_url": "https://images.unsplash.com/photo-1489515217757-5fd1be406fef?auto=format&fit=crop&w=1200&q=80",
            },
            {
                "title": "Evening sleeper",
                "depart": "19:20",
                "duration": "9h 10m",
                "base_price": 480.0,
                "stops": "1 stop via AMS",
                "is_direct": False,
                "image_url": "https://images.unsplash.com/photo-1485939420040-3e4a274307d0?auto=format&fit=crop&w=1200&q=80",
            },
            {
                "title": "Weekend saver",
                "depart": "22:05",
                "duration": "11h 05m",
                "base_price": 420.0,
                "stops": "1 stop via LHR",
                "is_direct": False,
                "image_url": "https://images.unsplash.com/photo-1474302770737-173ee21bab63?auto=format&fit=crop&w=1200&q=80",
            },
        ]

        for idx, option in enumerate(options[:max_results]):
            # Filter by direct_only preference
            if direct_only and not option["is_direct"]:
                continue

            # Calculate price based on cabin class and round trip
            base_price = option["base_price"] * cabin_multiplier
            if round_trip:
                base_price *= 2  # Round trip doubles the price
            price = round(base_price * total_travelers, 2)

            # Skip tiles that exceed budget (if budget is set)
            if budget_limit and price > budget_limit:
                continue

            # Format cabin class for display
            cabin_display = cabin_class.replace("_", " ").title()
            trip_type = "Round trip" if round_trip else "One way"

            # Expedia compliance: calculate taxes and fees for flights
            tax_and_service = round(price * 0.15, 2)  # ~15% taxes/service fees
            total_inclusive = round(price + tax_and_service, 2)
            # Flights are typically non-refundable except premium cabins
            is_refundable = cabin_class in ["business", "first"]

            tiles.append(
                Tile(
                    id=f"tile_mock_flight_{dest_id}_{idx + 1}",
                    type="flight",
                    partner=self.name,
                    partner_product_id=f"mock_flight_{idx + 1}",
                    title=f"{option['title']} · {origin} → {dest}",
                    subtitle=(
                        f"{option['depart']} departure · {option['duration']} · "
                        f"{option['stops']} · {cabin_display}"
                    ),
                    image_url=get_image_url_sync(dest, variant=(idx + 3) % 6),
                    price_estimate=price,
                    live_price=None if source_mode == "cache" else round(price * 1.03, 2),
                    currency=ctx.currency,
                    price_basis="per_trip",
                    is_estimate_only=source_mode == "cache",
                    deeplink_url="https://example.com/flights/search?aff_id=DEMO",
                    rating=4.3 + 0.05 * idx,
                    review_count=120 + 35 * idx,
                    location_label=f"{origin} → {dest}",
                    tags=["flight", option["stops"], cabin_class]
                    + (["within-budget"] if budget_limit else []),
                    availability_status="available",
                    meta={
                        "stops": option["stops"],
                        "is_direct": option["is_direct"],
                        "fare_class": cabin_display,
                        "cabin_class": cabin_class,
                        "trip_type": trip_type,
                        "round_trip": round_trip,
                        "destination": dest,
                        "origin": origin,
                        "adults": ctx.adults,
                        "children": ctx.children,
                        "budget_limit": budget_limit,
                    },
                    score=0.65 + 0.05 * idx,
                    source=source_mode,
                    # Expedia Rapid API compliance fields
                    total_inclusive=total_inclusive,
                    tax_and_service_fee=tax_and_service,
                    property_fee=None,  # No property fee for flights
                    is_refundable=is_refundable,
                    cancel_policy_summary=(
                        "Flexible - changes permitted with fee"
                        if is_refundable
                        else "Non-refundable fare"
                    ),
                    provider="expedia",
                )
            )

        return tiles


class MockActivityProvider(Provider):
    name = "mock_activity"

    # Template catalog — titles use {dest} placeholder, resolved at search time.
    # Each entry uses `tags` (list[str]) for affinity sorting.
    _ACTIVITY_CATALOG = [
        {
            "title": "Sunrise ridge hike in {dest}",
            "subtitle": "Guide-led, breakfast at the summit",
            "price": 95.0,
            "duration": "3h",
            "category": "hiking",
            "tags": ["outdoors"],
            "skill_level": "intermediate",
            "availability": "available",
        },
        {
            "title": "Night market food crawl, {dest} center",
            "subtitle": "Street bites, rooftop nightcap, hidden alleys",
            "price": 68.0,
            "duration": "2.5h",
            "category": "food",
            "tags": ["food", "culture"],
            "skill_level": "beginner",
            "availability": "available",
        },
        {
            "title": "Golden-hour harbor sail near {dest}",
            "subtitle": "Small group, bubbly on board, sunset views",
            "price": 125.0,
            "duration": "2h",
            "category": "boating",
            "tags": ["water"],
            "skill_level": "beginner",
            "availability": "low",
        },
        {
            "title": "Scuba diving adventure in {dest}",
            "subtitle": "Discover underwater wonders with certified instructors",
            "price": 180.0,
            "duration": "4h",
            "category": "diving",
            "tags": ["water", "outdoors"],
            "skill_level": "intermediate",
            "availability": "available",
        },
        {
            "title": "Mountain biking trails near {dest}",
            "subtitle": "Technical trails through scenic landscapes",
            "price": 110.0,
            "duration": "3h",
            "category": "cycling",
            "tags": ["outdoors"],
            "skill_level": "advanced",
            "availability": "available",
        },
        # --- Extended catalog for long-trip backfill ---
        {
            "title": "Guided snorkeling reef tour at {dest}",
            "subtitle": "Shallow reefs, gear included, small group",
            "price": 85.0,
            "duration": "2.5h",
            "category": "snorkeling",
            "tags": ["water", "outdoors"],
            "skill_level": "beginner",
            "availability": "available",
        },
        {
            "title": "Sea kayaking coastal adventure near {dest}",
            "subtitle": "Paddle past sea caves and hidden coves",
            "price": 90.0,
            "duration": "3h",
            "category": "kayaking",
            "tags": ["water", "outdoors"],
            "skill_level": "intermediate",
            "availability": "available",
        },
        {
            "title": "Stand-up paddleboard session in {dest}",
            "subtitle": "Calm-water SUP with board rental included",
            "price": 55.0,
            "duration": "1.5h",
            "category": "paddleboarding",
            "tags": ["water", "outdoors"],
            "skill_level": "beginner",
            "availability": "available",
        },
        {
            "title": "Sunset catamaran cruise near {dest}",
            "subtitle": "Open bar, snacks, live music on the water",
            "price": 140.0,
            "duration": "2.5h",
            "category": "boating",
            "tags": ["water"],
            "skill_level": "beginner",
            "availability": "available",
        },
        {
            "title": "Zipline canopy tour through {dest} forest",
            "subtitle": "Seven lines over the treetops, harness provided",
            "price": 105.0,
            "duration": "2h",
            "category": "zipline",
            "tags": ["outdoors", "adventure"],
            "skill_level": "beginner",
            "availability": "available",
        },
        {
            "title": "Horseback riding along {dest} trails",
            "subtitle": "Guided ride through countryside scenery",
            "price": 115.0,
            "duration": "2h",
            "category": "horseback_riding",
            "tags": ["outdoors", "adventure"],
            "skill_level": "beginner",
            "availability": "available",
        },
        {
            "title": "Cultural walking tour of historic {dest}",
            "subtitle": "Local guide, landmarks, and hidden stories",
            "price": 45.0,
            "duration": "2.5h",
            "category": "cultural",
            "tags": ["culture"],
            "skill_level": "beginner",
            "availability": "available",
        },
        {
            "title": "Sunset yoga session on {dest} beach",
            "subtitle": "All levels, mat provided, oceanside setting",
            "price": 35.0,
            "duration": "1h",
            "category": "yoga",
            "tags": ["wellness", "outdoors"],
            "skill_level": "beginner",
            "availability": "available",
        },
        {
            "title": "Local cooking class in {dest}",
            "subtitle": "Market tour, hands-on cooking, group meal",
            "price": 75.0,
            "duration": "3h",
            "category": "cooking",
            "tags": ["culture", "food"],
            "skill_level": "beginner",
            "availability": "available",
        },
        {
            "title": "Photography tour of {dest} landmarks",
            "subtitle": "Pro tips, golden-hour spots, small group",
            "price": 65.0,
            "duration": "2h",
            "category": "photography",
            "tags": ["culture", "outdoors"],
            "skill_level": "beginner",
            "availability": "available",
        },
        {
            "title": "Guided wildlife nature walk near {dest}",
            "subtitle": "Birdwatching, flora ID, binoculars provided",
            "price": 50.0,
            "duration": "2.5h",
            "category": "wildlife",
            "tags": ["outdoors", "culture"],
            "skill_level": "beginner",
            "availability": "available",
        },
        {
            "title": "Evening cocktail-making workshop in {dest}",
            "subtitle": "Local spirits, three drinks, take-home recipes",
            "price": 60.0,
            "duration": "1.5h",
            "category": "nightlife",
            "tags": ["food", "culture"],
            "skill_level": "beginner",
            "availability": "available",
        },
        {
            "title": "Morning meditation & temple visit in {dest}",
            "subtitle": "Guided mindfulness, incense ceremony, sunrise",
            "price": 40.0,
            "duration": "2h",
            "category": "wellness",
            "tags": ["wellness", "culture"],
            "skill_level": "beginner",
            "availability": "available",
        },
        {
            "title": "Vintage market & artisan craft walk, {dest}",
            "subtitle": "Local makers, street art, souvenirs",
            "price": 30.0,
            "duration": "2h",
            "category": "shopping",
            "tags": ["culture"],
            "skill_level": "beginner",
            "availability": "available",
        },
        {
            "title": "Waterfall swimming excursion near {dest}",
            "subtitle": "Jungle trail, natural pools, packed lunch",
            "price": 70.0,
            "duration": "4h",
            "category": "swimming",
            "tags": ["water", "outdoors"],
            "skill_level": "beginner",
            "availability": "available",
        },
    ]

    def search(
        self,
        ctx: SearchContext,
        *,
        affinity_tags: list[str] | None = None,
    ) -> List[Tile]:
        """Return mock activities for the given destination.

        Args:
            ctx: Search context with destination, filters, etc.
            affinity_tags: Optional tag list for affinity-based sorting.
                Activities matching more tags rank higher.
        """
        dest = ctx.destination or "your destination"
        dest_id = _dest_hash(dest)
        tiles: List[Tile] = []

        source_mode = "live" if (ctx.response_mode or "").startswith("live") else "cache"
        total_travelers = (ctx.adults or 0) + (ctx.children or 0) or 2
        max_results = max(1, ctx.max_results_per_vertical)

        # Calculate budget per category if budget is specified
        budget_limit = _parse_budget(ctx.budget_per_category)
        if not budget_limit:
            parsed_budget = _parse_budget(ctx.budget)
            if parsed_budget:
                # Allocate ~30% of total budget to activities
                budget_limit = parsed_budget * 0.3

        # Extract activity settings for filtering
        # Handle both dict and ActivitySettings model
        requested_categories: List[str] = []
        skill_level: Optional[str] = None
        if ctx.activity_settings:
            if isinstance(ctx.activity_settings, dict):
                requested_categories = [
                    c.lower() for c in (ctx.activity_settings.get("categories") or [])
                ]
                skill_level = ctx.activity_settings.get("skill_level")
            else:
                requested_categories = [c.lower() for c in (ctx.activity_settings.categories or [])]
                skill_level = ctx.activity_settings.skill_level

        filtered_activities = []
        for activity in self._ACTIVITY_CATALOG:
            # Filter by category if categories are specified
            if requested_categories:
                activity_category = activity.get("category", "").lower()
                if activity_category not in requested_categories:
                    continue

            # Filter by skill level if specified
            if skill_level:
                activity_skill = activity.get("skill_level", "beginner")
                # Skill level matching: beginner can do beginner,
                # intermediate can do beginner+intermediate, etc.
                skill_order = ["beginner", "intermediate", "advanced"]
                if skill_level in skill_order and activity_skill in skill_order:
                    user_level_idx = skill_order.index(skill_level)
                    activity_level_idx = skill_order.index(activity_skill)
                    # User can only do activities at or below their skill level
                    if activity_level_idx > user_level_idx:
                        continue

            filtered_activities.append(activity)

        # Affinity sort: activities matching more affinity tags rank higher
        if affinity_tags:
            tag_set = set(affinity_tags)
            filtered_activities.sort(
                key=lambda a: -len(tag_set & set(a.get("tags", []))),
            )

        for idx, activity in enumerate(filtered_activities[:max_results]):
            per_person = round(activity["price"], 2)
            total = round(per_person * total_travelers, 2)

            # Skip tiles that exceed budget (if budget is set)
            if budget_limit and total > budget_limit:
                continue

            # Expedia compliance: calculate taxes and fees for activities
            tax_and_service = round(total * 0.08, 2)  # ~8% taxes/service fees
            total_inclusive = round(total + tax_and_service, 2)
            # Most activities are refundable with 24h notice
            is_refundable = True

            # Resolve {dest} template in title (replace, not format, to avoid
            # KeyError if destination contains literal braces)
            title = activity["title"].replace("{dest}", dest)
            subtitle = activity["subtitle"]
            activity_tags = activity.get("tags", [])

            tiles.append(
                Tile(
                    id=f"tile_mock_activity_{dest_id}_{idx + 1}",
                    type="activity",
                    partner=self.name,
                    partner_product_id=f"mock_activity_{idx + 1}",
                    title=title,
                    subtitle=f"{subtitle} · {activity['duration']}",
                    image_url=get_image_url_sync(dest, variant=(idx + 4) % 6),
                    price_estimate=total,
                    live_price=None if source_mode == "cache" else round(total * 1.02, 2),
                    currency=ctx.currency,
                    price_basis="per_trip",
                    is_estimate_only=source_mode == "cache",
                    deeplink_url="https://example.com/activities/book?aff_id=DEMO",
                    rating=4.5 + 0.06 * idx,
                    review_count=220 + 55 * idx,
                    location_label=dest,
                    tags=["activity", activity["category"]]
                    + list(activity_tags)
                    + (["within-budget"] if budget_limit else []),
                    availability_status=activity["availability"],
                    meta={
                        "duration": activity["duration"],
                        "category": activity["category"],
                        "skill_level": activity["skill_level"],
                        "destination": dest,
                        "adults": ctx.adults,
                        "children": ctx.children,
                        "budget_limit": budget_limit,
                    },
                    score=0.6 + 0.05 * idx,
                    source=source_mode,
                    # Expedia Rapid API compliance fields
                    total_inclusive=total_inclusive,
                    tax_and_service_fee=tax_and_service,
                    property_fee=None,  # No property fee for activities
                    is_refundable=is_refundable,
                    cancel_policy_summary="Free cancellation up to 24h before start time",
                    provider="expedia",
                )
            )

        return tiles
