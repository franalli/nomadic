"""
Amadeus API Client - OAuth2 token management and flight/hotel search.

This client wraps the Amadeus API with:
- Automatic OAuth2 token refresh (tokens expire after 30 min)
- Circuit breaker pattern (5 failures → open for 60s)
- Rate limiting (30 req/min for test environment)
- Proper error handling and logging

Usage:
    client = AmadeusClient()
    flights = await client.search_flights("JFK", "DXB", "2026-02-01", adults=2)
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================


def _get_config():
    """Get Amadeus configuration from environment."""
    return {
        "api_key": os.getenv("AMADEUS_API_KEY"),
        "api_secret": os.getenv("AMADEUS_API_SECRET"),
        "base_url": os.getenv("AMADEUS_BASE_URL", "https://test.api.amadeus.com"),
        "requests_per_minute": int(os.getenv("AMADEUS_REQUESTS_PER_MINUTE", "30")),
        "circuit_breaker_threshold": int(os.getenv("AMADEUS_CIRCUIT_BREAKER_THRESHOLD", "5")),
        "circuit_breaker_timeout": int(os.getenv("AMADEUS_CIRCUIT_BREAKER_TIMEOUT", "60")),
    }


# =============================================================================
# Data Models
# =============================================================================


class FlightSegment(BaseModel):
    """A single flight segment (leg) within an itinerary."""

    carrier_code: str  # e.g., "EK"
    flight_number: str  # e.g., "203"
    departure_airport: str  # IATA code
    departure_time: datetime
    arrival_airport: str
    arrival_time: datetime
    duration: str  # ISO 8601 duration, e.g., "PT7H30M"
    cabin_class: Optional[str] = None


class FlightOffer(BaseModel):
    """A flight offer from Amadeus Flight Offers Search API."""

    id: str
    carrier_code: str  # Primary carrier
    carrier_name: Optional[str] = None
    carrier_logo: Optional[str] = None  # CDN URL
    departure_time: datetime
    arrival_time: datetime
    duration: str  # Total duration
    price: float
    currency: str
    segments: List[FlightSegment]
    stops: int = 0
    cabin_class: str = "economy"
    baggage_included: bool = False
    is_refundable: bool = False

    # Raw Amadeus data for debugging
    raw_data: Optional[Dict[str, Any]] = None


class HotelOffer(BaseModel):
    """A hotel offer from Amadeus Hotel Search API."""

    id: str
    hotel_id: str
    name: str
    chain_code: Optional[str] = None
    rating: Optional[int] = None  # Star rating 1-5
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None
    city_code: str
    amenities: List[str] = field(default_factory=list)
    photo_url: Optional[str] = None
    price_per_night: Optional[float] = None
    currency: str = "USD"

    # Raw Amadeus data for debugging
    raw_data: Optional[Dict[str, Any]] = None


# =============================================================================
# Circuit Breaker
# =============================================================================


class CircuitState(str, Enum):
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreaker:
    """
    Circuit breaker to protect against cascading failures.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Service is failing, reject requests immediately
    - HALF_OPEN: Testing if service recovered, allow one request

    After `failure_threshold` consecutive failures, circuit opens.
    After `reset_timeout` seconds, circuit moves to half-open.
    If half-open request succeeds, circuit closes.
    If half-open request fails, circuit opens again.
    """

    failure_threshold: int = 5
    reset_timeout: int = 60

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: Optional[float] = None

    def record_success(self):
        """Record a successful request."""
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def record_failure(self):
        """Record a failed request."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(f"Circuit breaker OPENED after {self.failure_count} failures")

    def can_execute(self) -> bool:
        """Check if a request can be executed."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Check if reset timeout has passed
            if self.last_failure_time and time.time() - self.last_failure_time > self.reset_timeout:
                self.state = CircuitState.HALF_OPEN
                logger.info("Circuit breaker moving to HALF_OPEN")
                return True
            return False

        # HALF_OPEN - allow one request
        return True


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and rejecting requests."""

    pass


# =============================================================================
# Rate Limiter
# =============================================================================


@dataclass
class RateLimiter:
    """
    Simple rate limiter using sliding window.

    Limits requests to `max_requests` per minute.
    """

    max_requests: int = 30
    window_seconds: int = 60

    _request_times: List[float] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def acquire(self):
        """Wait until a request can be made."""
        async with self._lock:
            now = time.time()
            # Remove old requests outside the window
            cutoff = now - self.window_seconds
            self._request_times = [t for t in self._request_times if t > cutoff]

            if len(self._request_times) >= self.max_requests:
                # Wait until oldest request expires
                wait_time = self._request_times[0] + self.window_seconds - now
                if wait_time > 0:
                    logger.debug(f"Rate limit reached, waiting {wait_time:.2f}s")
                    await asyncio.sleep(wait_time)

            self._request_times.append(time.time())


# =============================================================================
# Amadeus Client
# =============================================================================


class AmadeusClient:
    """
    Async client for Amadeus API with OAuth2 token management.

    Features:
    - Automatic token refresh (5 min before expiry)
    - Circuit breaker for fault tolerance
    - Rate limiting to respect API limits
    - Proper error handling
    """

    _instance: Optional["AmadeusClient"] = None
    _lock: asyncio.Lock = asyncio.Lock()

    def __init__(self):
        """Initialize the Amadeus client."""
        config = _get_config()
        self.api_key = config["api_key"]
        self.api_secret = config["api_secret"]
        self.base_url = config["base_url"]

        # Token management
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self._token_lock = asyncio.Lock()

        # Circuit breaker
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=config["circuit_breaker_threshold"],
            reset_timeout=config["circuit_breaker_timeout"],
        )

        # Rate limiter
        self.rate_limiter = RateLimiter(max_requests=config["requests_per_minute"])

    @classmethod
    async def get_instance(cls) -> "AmadeusClient":
        """Get or create singleton instance."""
        async with cls._lock:
            if cls._instance is None:
                cls._instance = AmadeusClient()
            return cls._instance

    def is_configured(self) -> bool:
        """Check if API credentials are configured."""
        return bool(self.api_key and self.api_secret)

    async def _get_access_token(self) -> str:
        """
        Get a valid access token, refreshing if needed.

        Amadeus tokens expire after 30 minutes.
        We refresh 5 minutes before expiry to avoid race conditions.
        """
        async with self._token_lock:
            # Check if current token is valid
            if self._access_token and self._token_expires_at:
                # Refresh 5 minutes before expiry
                if datetime.now() < self._token_expires_at - timedelta(minutes=5):
                    return self._access_token

            # Request new token
            logger.info("Requesting new Amadeus access token")

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/v1/security/oauth2/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.api_key,
                        "client_secret": self.api_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )

                if response.status_code != 200:
                    error_text = response.text
                    logger.error(
                        f"Failed to get Amadeus token: {response.status_code} - {error_text}"
                    )
                    raise AmadeusAPIError(
                        code="AUTH_FAILED",
                        message=f"Failed to authenticate with Amadeus: {response.status_code}",
                    )

                data = response.json()
                self._access_token = data["access_token"]
                expires_in = data.get("expires_in", 1799)  # Default 30 min
                self._token_expires_at = datetime.now() + timedelta(seconds=expires_in)

                logger.info(f"Got Amadeus token, expires in {expires_in}s")
                return self._access_token

    async def _make_request(
        self,
        method: Literal["GET", "POST"],
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Make an authenticated request to Amadeus API.

        Handles:
        - Circuit breaker
        - Rate limiting
        - Token refresh
        - Error handling
        """
        if not self.is_configured():
            raise AmadeusAPIError(
                code="NOT_CONFIGURED",
                message="Amadeus API credentials not configured",
            )

        # Check circuit breaker
        if not self.circuit_breaker.can_execute():
            raise CircuitBreakerOpenError(
                "Amadeus API circuit breaker is open. Service may be unavailable."
            )

        # Rate limiting
        await self.rate_limiter.acquire()

        # Get token
        token = await self._get_access_token()

        # Make request
        url = f"{self.base_url}{endpoint}"
        headers = {"Authorization": f"Bearer {token}"}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if method == "GET":
                    response = await client.get(url, params=params, headers=headers)
                else:
                    response = await client.post(url, json=json_data, headers=headers)

                # Handle errors
                if response.status_code >= 400:
                    self.circuit_breaker.record_failure()
                    error_data = response.json() if response.text else {}
                    errors = error_data.get("errors", [])
                    error_msg = (
                        errors[0].get("detail", str(response.status_code))
                        if errors
                        else str(response.status_code)
                    )

                    raise AmadeusAPIError(
                        code=f"HTTP_{response.status_code}",
                        message=f"Amadeus API error: {error_msg}",
                        details=error_data,
                    )

                self.circuit_breaker.record_success()
                return response.json()

        except httpx.TimeoutException as e:
            self.circuit_breaker.record_failure()
            raise AmadeusAPIError(
                code="TIMEOUT",
                message="Amadeus API request timed out",
            ) from e
        except httpx.RequestError as e:
            self.circuit_breaker.record_failure()
            raise AmadeusAPIError(
                code="REQUEST_ERROR",
                message=f"Amadeus API request failed: {str(e)}",
            ) from e

    # =========================================================================
    # Flight Search
    # =========================================================================

    async def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        adults: int = 1,
        return_date: Optional[str] = None,
        cabin_class: str = "ECONOMY",
        direct_only: bool = False,
        max_results: int = 10,
    ) -> List[FlightOffer]:
        """
        Search for flight offers.

        Args:
            origin: Origin airport IATA code (e.g., "JFK")
            destination: Destination airport IATA code (e.g., "DXB")
            departure_date: Departure date in YYYY-MM-DD format
            adults: Number of adult passengers
            return_date: Optional return date for round-trip
            cabin_class: Cabin class (ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST)
            direct_only: Only return non-stop flights
            max_results: Maximum number of results

        Returns:
            List of FlightOffer objects
        """
        logger.info(f"Searching flights: {origin} -> {destination} on {departure_date}")

        params = {
            "originLocationCode": origin.upper(),
            "destinationLocationCode": destination.upper(),
            "departureDate": departure_date,
            "adults": adults,
            "travelClass": cabin_class.upper(),
            "max": max_results,
            "currencyCode": "USD",
        }

        if return_date:
            params["returnDate"] = return_date

        if direct_only:
            params["nonStop"] = "true"

        try:
            data = await self._make_request(
                "GET",
                "/v2/shopping/flight-offers",
                params=params,
            )

            offers = data.get("data", [])
            dictionaries = data.get("dictionaries", {})

            return [self._parse_flight_offer(offer, dictionaries) for offer in offers]

        except AmadeusAPIError as e:
            logger.warning(f"Flight search failed: {e.message}")
            return []

    def _parse_flight_offer(
        self,
        offer: Dict[str, Any],
        dictionaries: Dict[str, Any],
    ) -> FlightOffer:
        """Parse a raw Amadeus flight offer into our model."""
        itineraries = offer.get("itineraries", [])
        first_itinerary = itineraries[0] if itineraries else {}
        segments = first_itinerary.get("segments", [])
        first_segment = segments[0] if segments else {}

        # Get carrier info
        carrier_code = first_segment.get("carrierCode", "")
        carriers = dictionaries.get("carriers", {})
        carrier_name = carriers.get(carrier_code, carrier_code)

        # Parse segments
        parsed_segments = []
        for seg in segments:
            parsed_segments.append(
                FlightSegment(
                    carrier_code=seg.get("carrierCode", ""),
                    flight_number=seg.get("number", ""),
                    departure_airport=seg.get("departure", {}).get("iataCode", ""),
                    departure_time=datetime.fromisoformat(
                        seg.get("departure", {}).get("at", "2000-01-01T00:00:00")
                    ),
                    arrival_airport=seg.get("arrival", {}).get("iataCode", ""),
                    arrival_time=datetime.fromisoformat(
                        seg.get("arrival", {}).get("at", "2000-01-01T00:00:00")
                    ),
                    duration=seg.get("duration", ""),
                    cabin_class=seg.get("cabin"),
                )
            )

        # Calculate stops
        stops = len(segments) - 1 if segments else 0

        # Get price
        price_data = offer.get("price", {})
        price = float(price_data.get("total", 0))
        currency = price_data.get("currency", "USD")

        # Build carrier logo URL (avs.io CDN)
        carrier_logo = f"https://pics.avs.io/200/200/{carrier_code}.png" if carrier_code else None

        return FlightOffer(
            id=offer.get("id", ""),
            carrier_code=carrier_code,
            carrier_name=carrier_name,
            carrier_logo=carrier_logo,
            departure_time=parsed_segments[0].departure_time if parsed_segments else datetime.now(),
            arrival_time=parsed_segments[-1].arrival_time if parsed_segments else datetime.now(),
            duration=first_itinerary.get("duration", ""),
            price=price,
            currency=currency,
            segments=parsed_segments,
            stops=stops,
            cabin_class=first_segment.get("cabin", "ECONOMY"),
            baggage_included=bool(
                offer.get("travelerPricings", [{}])[0]
                .get("fareDetailsBySegment", [{}])[0]
                .get("includedCheckedBags")
            ),
            raw_data=offer,
        )

    # =========================================================================
    # Hotel Search
    # =========================================================================

    async def search_hotels_by_city(
        self,
        city_code: str,
        radius: int = 20,
        radius_unit: str = "KM",
        ratings: Optional[List[int]] = None,
        amenities: Optional[List[str]] = None,
        max_results: int = 10,
    ) -> List[HotelOffer]:
        """
        Search for hotels in a city.

        This uses the Hotel List API to get hotels, not prices.
        For pricing, you'd need to call Hotel Offers API separately.

        Args:
            city_code: City IATA code (e.g., "DXB" for Dubai)
            radius: Search radius from city center
            radius_unit: KM or MILE
            ratings: Filter by star ratings (e.g., [4, 5])
            amenities: Filter by amenities
            max_results: Maximum results

        Returns:
            List of HotelOffer objects
        """
        logger.info(f"Searching hotels in city: {city_code}")

        params = {
            "cityCode": city_code.upper(),
            "radius": radius,
            "radiusUnit": radius_unit,
        }

        if ratings:
            params["ratings"] = ",".join(str(r) for r in ratings)

        if amenities:
            params["amenities"] = ",".join(amenities)

        try:
            data = await self._make_request(
                "GET",
                "/v1/reference-data/locations/hotels/by-city",
                params=params,
            )

            hotels = data.get("data", [])[:max_results]

            return [self._parse_hotel(hotel, city_code) for hotel in hotels]

        except AmadeusAPIError as e:
            logger.warning(f"Hotel search failed: {e.message}")
            return []

    def _parse_hotel(self, hotel: Dict[str, Any], city_code: str) -> HotelOffer:
        """Parse a raw Amadeus hotel into our model."""
        geo = hotel.get("geoCode", {})
        address = hotel.get("address", {})

        return HotelOffer(
            id=hotel.get("hotelId", ""),
            hotel_id=hotel.get("hotelId", ""),
            name=hotel.get("name", "Hotel"),
            chain_code=hotel.get("chainCode"),
            rating=hotel.get("rating"),
            latitude=geo.get("latitude"),
            longitude=geo.get("longitude"),
            address=", ".join(
                filter(
                    None,
                    [
                        address.get("lines", [""])[0] if address.get("lines") else None,
                        address.get("cityName"),
                        address.get("countryCode"),
                    ],
                )
            ),
            city_code=city_code,
            raw_data=hotel,
        )


# =============================================================================
# Errors
# =============================================================================


class AmadeusAPIError(Exception):
    """Amadeus API error with structured information."""

    def __init__(
        self,
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


# =============================================================================
# Utility Functions
# =============================================================================


# City to IATA airport code mapping for common destinations
CITY_TO_AIRPORT: Dict[str, str] = {
    "dubai": "DXB",
    "rome": "FCO",
    "paris": "CDG",
    "london": "LHR",
    "new york": "JFK",
    "los angeles": "LAX",
    "tokyo": "NRT",
    "singapore": "SIN",
    "hong kong": "HKG",
    "sydney": "SYD",
    "bali": "DPS",
    "maldives": "MLE",
    "chamonix": "GVA",  # Nearest major airport
    "geneva": "GVA",
    "milan": "MXP",
}


def city_to_airport_code(city: str) -> Optional[str]:
    """
    Convert a city name to its primary airport IATA code.

    Args:
        city: City name (case-insensitive)

    Returns:
        IATA airport code or None if not found
    """
    return CITY_TO_AIRPORT.get(city.lower().strip())
