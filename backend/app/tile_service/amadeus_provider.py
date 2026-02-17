"""
Amadeus Providers - Flight and Hotel providers using Amadeus API.

These providers implement the Provider interface and use the AmadeusClient
to fetch real inventory data.

Usage:
    provider = AmadeusFlightProvider()
    tiles = provider.search(context)
"""

import asyncio
import logging
import uuid
from typing import List, Optional

from app.placeholders import get_placeholder_image
from app.schemas import Tile
from app.tools.amadeus_client import (
    AmadeusClient,
    FlightOffer,
    HotelOffer,
    city_to_airport_code,
)

from .models import SearchContext
from .provider_base import Provider

logger = logging.getLogger(__name__)


def _normalize_city_for_amadeus(city: str) -> str:
    """
    Remove country/region suffixes that break Amadeus city code lookup.
    Safety net for when router normalization doesn't fully work.
    """
    if not city:
        return city

    city = city.strip()

    # Remove common country suffixes (case-insensitive)
    suffixes = [
        ", France",
        ", FR",
        ", Italy",
        ", IT",
        ", Spain",
        ", ES",
        ", USA",
        ", US",
        ", United States",
        ", UK",
        ", United Kingdom",
        ", Germany",
        ", DE",
        ", Japan",
        ", JP",
        ", Thailand",
        ", TH",
        ", Indonesia",
        ", ID",
        ", UAE",
        ", United Arab Emirates",
        ", Australia",
        ", AU",
        ", Canada",
        ", CA",
        ", Mexico",
        ", MX",
    ]

    for suffix in suffixes:
        if city.lower().endswith(suffix.lower()):
            city = city[: -len(suffix)].strip()
            break

    return city


class AmadeusFlightProvider(Provider):
    """
    Flight provider using Amadeus Flight Offers Search API.

    Returns real-time flight offers with pricing.
    """

    name = "amadeus_flight"

    def __init__(self):
        """Initialize the provider."""
        self._client: Optional[AmadeusClient] = None

    def _get_client(self) -> AmadeusClient:
        """Get or create the Amadeus client."""
        if self._client is None:
            self._client = AmadeusClient()
        return self._client

    def search(self, ctx: SearchContext) -> List[Tile]:
        """
        Search for flights using Amadeus API.

        Note: This is a sync wrapper around the async API.
        Handles the case where we're called from within an existing event loop
        (e.g., LangGraph streaming) by running in a separate thread.
        """
        import concurrent.futures

        try:
            # Check if we're already in an event loop
            try:
                asyncio.get_running_loop()  # Check if loop exists
                # We're in an event loop - run in a thread pool
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(self._run_async_in_new_loop, ctx)
                    return future.result(timeout=30)
            except RuntimeError:
                # No running event loop - create one
                return asyncio.run(self._search_async(ctx))
        except Exception as e:
            logger.warning(f"Amadeus flight search failed: {e}")
            return []

    def _run_async_in_new_loop(self, ctx: SearchContext) -> List[Tile]:
        """Run the async search in a new event loop (for thread execution)."""
        return asyncio.run(self._search_async(ctx))

    async def search_async(self, ctx: SearchContext) -> List[Tile]:
        """Async search — use from async contexts to avoid event-loop blocking."""
        try:
            return await self._search_async(ctx)
        except Exception as e:
            logger.warning(f"Amadeus flight search failed: {e}")
            return []

    async def _search_async(self, ctx: SearchContext) -> List[Tile]:
        """Async implementation of flight search."""
        client = self._get_client()

        if not client.is_configured():
            logger.warning("Amadeus API not configured, skipping flight search")
            return []

        # Prefer pre-resolved IATA codes from planner graph (LLM-backed),
        # fall back to hardcoded city→airport lookup.
        origin_code = ctx.origin_iata or self._resolve_airport_code(ctx.origin)
        dest_code = ctx.destination_iata or self._resolve_airport_code(ctx.destination)

        if not origin_code or not dest_code:
            logger.warning(f"Could not resolve airport codes: {ctx.origin} -> {ctx.destination}")
            return []

        # Get flight settings
        flight_settings = ctx.flight_settings or {}
        cabin_class = flight_settings.get("cabin_class", "economy").upper()
        direct_only = flight_settings.get("direct_only", False)
        round_trip = flight_settings.get("round_trip", True)

        # Search flights
        offers = await client.search_flights(
            origin=origin_code,
            destination=dest_code,
            departure_date=ctx.start_date,
            return_date=ctx.end_date if round_trip else None,
            adults=ctx.adults or 1,
            cabin_class=cabin_class,
            direct_only=direct_only,
            max_results=ctx.max_results_per_vertical or 5,
        )

        # Convert to tiles
        tiles = [self._offer_to_tile(offer, ctx) for offer in offers]

        # Apply budget filter if set (flights get ~30% of total budget)
        if ctx.budget:
            flight_limit = ctx.budget * 0.30
            tiles = [t for t in tiles if not t.price_estimate or t.price_estimate <= flight_limit]

        return tiles

    def _resolve_airport_code(self, location: Optional[str]) -> Optional[str]:
        """Resolve a location to an airport code."""
        if not location:
            return None

        # Normalize location name (strip country suffixes)
        normalized = _normalize_city_for_amadeus(location)

        if normalized != location:
            logger.info(f"[AMADEUS] Normalized location: '{location}' → '{normalized}'")

        # Check if already an airport code (3 letters)
        if len(normalized) == 3 and normalized.isalpha():
            return normalized.upper()

        # Try city-to-airport mapping
        return city_to_airport_code(normalized)

    def _offer_to_tile(self, offer: FlightOffer, _ctx: SearchContext) -> Tile:
        """Convert a FlightOffer to a Tile."""
        # Build title
        stops_text = (
            "Direct" if offer.stops == 0 else f"{offer.stops} stop{'s' if offer.stops > 1 else ''}"
        )
        title = f"{offer.carrier_name or offer.carrier_code} - {stops_text}"

        # Build subtitle with times
        dep_time = offer.departure_time.strftime("%H:%M")
        arr_time = offer.arrival_time.strftime("%H:%M")
        subtitle = f"{dep_time} - {arr_time} ({offer.duration})"

        # Parse duration for tags
        tags = [offer.cabin_class.lower(), stops_text.lower()]
        if offer.baggage_included:
            tags.append("baggage included")

        return Tile(
            id=f"amadeus_flight_{offer.id}_{uuid.uuid4().hex[:6]}",
            type="flight",
            partner="amadeus",
            partner_product_id=offer.id,
            title=title,
            subtitle=subtitle,
            image_url=offer.carrier_logo,
            price_estimate=offer.price,
            live_price=offer.price,
            currency=offer.currency,
            price_basis="per_person",
            is_estimate_only=False,
            deeplink_url="#",  # Amadeus doesn't provide direct booking links in test env
            tags=tags,
            availability_status="available",
            meta={
                "carrier_code": offer.carrier_code,
                "carrier_name": offer.carrier_name,
                "carrier_logo": offer.carrier_logo,
                "departure_time": offer.departure_time.isoformat(),
                "arrival_time": offer.arrival_time.isoformat(),
                "duration": offer.duration,
                "stops": offer.stops,
                "cabin_class": offer.cabin_class,
                "baggage_included": offer.baggage_included,
                "segments": [
                    {
                        "carrier": seg.carrier_code,
                        "flight_number": seg.flight_number,
                        "departure": seg.departure_airport,
                        "arrival": seg.arrival_airport,
                        "departure_time": seg.departure_time.isoformat(),
                        "arrival_time": seg.arrival_time.isoformat(),
                    }
                    for seg in offer.segments
                ],
                "amadeus": True,
            },
            source="live",
            source_agent="amadeus_flight_provider",
        )


class AmadeusHotelProvider(Provider):
    """
    Hotel provider using Amadeus Hotel Search API.

    Note: This returns hotel listings, not real-time pricing.
    For pricing, a separate Hotel Offers API call would be needed.
    """

    name = "amadeus_hotel"

    def __init__(self):
        """Initialize the provider."""
        self._client: Optional[AmadeusClient] = None

    def _get_client(self) -> AmadeusClient:
        """Get or create the Amadeus client."""
        if self._client is None:
            self._client = AmadeusClient()
        return self._client

    def search(self, ctx: SearchContext) -> List[Tile]:
        """
        Search for hotels using Amadeus API.

        Note: This is a sync wrapper around the async API.
        Handles the case where we're called from within an existing event loop.
        """
        import concurrent.futures

        try:
            # Check if we're already in an event loop
            try:
                asyncio.get_running_loop()  # Check if loop exists
                # We're in an event loop - run in a thread pool
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(self._run_async_in_new_loop, ctx)
                    return future.result(timeout=30)
            except RuntimeError:
                # No running event loop - create one
                return asyncio.run(self._search_async(ctx))
        except Exception as e:
            logger.warning(f"Amadeus hotel search failed: {e}")
            return []

    def _run_async_in_new_loop(self, ctx: SearchContext) -> List[Tile]:
        """Run the async search in a new event loop (for thread execution)."""
        return asyncio.run(self._search_async(ctx))

    async def search_async(self, ctx: SearchContext) -> List[Tile]:
        """Async search — use from async contexts to avoid event-loop blocking."""
        try:
            return await self._search_async(ctx)
        except Exception as e:
            logger.warning(f"Amadeus hotel search failed: {e}")
            return []

    async def _search_async(self, ctx: SearchContext) -> List[Tile]:
        """Async implementation of hotel search."""
        client = self._get_client()

        if not client.is_configured():
            logger.warning("Amadeus API not configured, skipping hotel search")
            return []

        # Prefer pre-resolved IATA code from planner graph, fall back to lookup
        city_code = ctx.destination_iata or self._resolve_city_code(ctx.destination)
        if not city_code:
            logger.warning(f"Could not resolve city code for: {ctx.destination}")
            return []

        # Get hotel settings
        hotel_settings = ctx.hotel_settings or {}
        ratings = None
        min_stars = hotel_settings.get("min_stars")
        if min_stars and min_stars > 0:
            ratings = list(range(min_stars, 6))  # e.g., [4, 5] for min_stars=4

        # Search hotels
        hotels = await client.search_hotels_by_city(
            city_code=city_code,
            ratings=ratings,
            max_results=ctx.max_results_per_vertical or 5,
        )

        # Convert to tiles
        tiles = [self._hotel_to_tile(hotel, ctx) for hotel in hotels]

        # Apply budget filter if set (hotels get ~40% of total budget)
        if ctx.budget:
            hotel_limit = ctx.budget * 0.40
            tiles = [t for t in tiles if not t.price_estimate or t.price_estimate <= hotel_limit]

        return tiles

    def _resolve_city_code(self, destination: Optional[str]) -> Optional[str]:
        """Resolve a destination to a city IATA code."""
        if not destination:
            return None

        # Normalize city name (strip country suffixes like ", France")
        normalized = _normalize_city_for_amadeus(destination)

        if normalized != destination:
            logger.info(f"[AMADEUS] Normalized destination: '{destination}' → '{normalized}'")

        # Check if already a code (3 letters)
        if len(normalized) == 3 and normalized.isalpha():
            return normalized.upper()

        # Use airport code as city code (often the same)
        return city_to_airport_code(normalized)

    def _hotel_to_tile(self, hotel: HotelOffer, _ctx: SearchContext) -> Tile:
        """Convert a HotelOffer to a Tile."""
        # Build rating text
        rating_text = f"{hotel.rating}★" if hotel.rating else ""

        # Amadeus Hotel List API doesn't return photos - use deterministic placeholder
        # Seed with hotel_id for consistency (same hotel always gets same image)
        image_url = hotel.photo_url or get_placeholder_image(
            category="hotel",
            seed=hotel.hotel_id,
        )

        return Tile(
            id=f"amadeus_hotel_{hotel.id}_{uuid.uuid4().hex[:6]}",
            type="hotel",
            partner="amadeus",
            partner_product_id=hotel.hotel_id,
            title=hotel.name,
            subtitle=hotel.address or hotel.city_code,
            image_url=image_url,
            price_estimate=hotel.price_per_night,
            currency=hotel.currency,
            price_basis="per_night",
            is_estimate_only=True,  # Hotel list API doesn't include prices
            deeplink_url="#",
            rating=float(hotel.rating) if hotel.rating else None,
            location_label=hotel.address,
            geo={"lat": hotel.latitude, "lon": hotel.longitude} if hotel.latitude else None,
            tags=[rating_text] if rating_text else [],
            availability_status="unknown",  # Need separate API call for availability
            meta={
                "hotel_id": hotel.hotel_id,
                "chain_code": hotel.chain_code,
                "star_rating": hotel.rating,
                "amenities": hotel.amenities,
                "amadeus": True,
            },
            source="live",
            source_agent="amadeus_hotel_provider",
        )
