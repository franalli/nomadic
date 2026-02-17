"""
Tests for the Amadeus API client in app.tools.amadeus_client.

Covers:
- CircuitBreaker state machine (pure logic, no mocks needed)
- RateLimiter basic behavior (async)
- FlightOffer parsing (_parse_flight_offer)
- HotelOffer parsing (_parse_hotel)
- AmadeusClient configuration and is_configured()
- AmadeusClient search methods with mocked HTTP
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.amadeus_client import (
    AmadeusClient,
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
    FlightOffer,
    HotelOffer,
    RateLimiter,
)

# =============================================================================
# CircuitBreaker Tests (pure logic)
# =============================================================================


class TestCircuitBreakerInit:
    """Tests for CircuitBreaker initial state."""

    def test_starts_closed(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED

    def test_starts_with_zero_failures(self):
        cb = CircuitBreaker()
        assert cb.failure_count == 0

    def test_can_execute_when_closed(self):
        cb = CircuitBreaker()
        assert cb.can_execute() is True

    def test_custom_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.failure_threshold == 3

    def test_custom_reset_timeout(self):
        cb = CircuitBreaker(reset_timeout=120)
        assert cb.reset_timeout == 120


class TestCircuitBreakerSuccessPath:
    """Tests for success recording behavior."""

    def test_success_stays_closed(self):
        cb = CircuitBreaker()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker()
        cb.failure_count = 3
        cb.record_success()
        assert cb.failure_count == 0

    def test_success_after_half_open_closes(self):
        cb = CircuitBreaker()
        cb.state = CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0


class TestCircuitBreakerFailurePath:
    """Tests for failure recording and OPEN transition."""

    def test_single_failure_increments_count(self):
        cb = CircuitBreaker(failure_threshold=5)
        cb.record_failure()
        assert cb.failure_count == 1
        assert cb.state == CircuitState.CLOSED

    def test_below_threshold_stays_closed(self):
        cb = CircuitBreaker(failure_threshold=5)
        for _ in range(4):
            cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_at_threshold_opens(self):
        cb = CircuitBreaker(failure_threshold=5)
        for _ in range(5):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_open_rejects_requests(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.can_execute() is False

    def test_failure_records_timestamp(self):
        cb = CircuitBreaker()
        before = time.time()
        cb.record_failure()
        after = time.time()
        assert cb.last_failure_time is not None
        assert before <= cb.last_failure_time <= after


class TestCircuitBreakerHalfOpen:
    """Tests for OPEN -> HALF_OPEN transition after reset_timeout."""

    def test_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=0)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        # With reset_timeout=0, immediately eligible for half-open
        time.sleep(0.01)
        assert cb.can_execute() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_allows_one_request(self):
        cb = CircuitBreaker()
        cb.state = CircuitState.HALF_OPEN
        assert cb.can_execute() is True

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.state = CircuitState.HALF_OPEN
        cb.failure_count = 0
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_stays_open_before_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=9999)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.can_execute() is False


# =============================================================================
# RateLimiter Tests
# =============================================================================


class TestRateLimiter:
    """Tests for the sliding-window rate limiter."""

    @pytest.mark.asyncio
    async def test_under_limit_acquires_immediately(self):
        rl = RateLimiter(max_requests=10, window_seconds=60)
        await rl.acquire()
        assert len(rl._request_times) == 1

    @pytest.mark.asyncio
    async def test_records_request_time(self):
        rl = RateLimiter(max_requests=10, window_seconds=60)
        before = time.time()
        await rl.acquire()
        after = time.time()
        assert len(rl._request_times) == 1
        assert before <= rl._request_times[0] <= after

    @pytest.mark.asyncio
    async def test_multiple_acquires_tracked(self):
        rl = RateLimiter(max_requests=100, window_seconds=60)
        for _ in range(5):
            await rl.acquire()
        assert len(rl._request_times) == 5


# =============================================================================
# FlightOffer Parsing Tests
# =============================================================================


def _make_client() -> AmadeusClient:
    """Create a client instance with fake credentials for parsing tests."""
    with patch.dict(
        os.environ,
        {"AMADEUS_API_KEY": "test", "AMADEUS_API_SECRET": "secret"},  # pragma: allowlist secret
    ):
        return AmadeusClient()


SAMPLE_FLIGHT_OFFER = {
    "id": "1",
    "itineraries": [
        {
            "duration": "PT7H30M",
            "segments": [
                {
                    "carrierCode": "EK",
                    "number": "203",
                    "departure": {"iataCode": "JFK", "at": "2026-03-01T10:00:00"},
                    "arrival": {"iataCode": "DXB", "at": "2026-03-01T17:30:00"},
                    "duration": "PT7H30M",
                    "cabin": "ECONOMY",
                }
            ],
        }
    ],
    "price": {"total": "850.00", "currency": "USD"},
    "travelerPricings": [
        {"fareDetailsBySegment": [{"includedCheckedBags": {"weight": 23, "weightUnit": "KG"}}]}
    ],
}

SAMPLE_DICTIONARIES = {"carriers": {"EK": "Emirates"}}


class TestParseFlightOffer:
    """Tests for _parse_flight_offer with sample Amadeus data."""

    def test_parses_basic_fields(self):
        client = _make_client()
        offer = client._parse_flight_offer(SAMPLE_FLIGHT_OFFER, SAMPLE_DICTIONARIES)
        assert isinstance(offer, FlightOffer)
        assert offer.id == "1"
        assert offer.carrier_code == "EK"
        assert offer.carrier_name == "Emirates"
        assert offer.price == 850.0
        assert offer.currency == "USD"

    def test_parses_segments(self):
        client = _make_client()
        offer = client._parse_flight_offer(SAMPLE_FLIGHT_OFFER, SAMPLE_DICTIONARIES)
        assert len(offer.segments) == 1
        seg = offer.segments[0]
        assert seg.departure_airport == "JFK"
        assert seg.arrival_airport == "DXB"
        assert seg.carrier_code == "EK"
        assert seg.flight_number == "203"

    def test_parses_departure_arrival_times(self):
        client = _make_client()
        offer = client._parse_flight_offer(SAMPLE_FLIGHT_OFFER, SAMPLE_DICTIONARIES)
        assert offer.departure_time == datetime(2026, 3, 1, 10, 0, 0)
        assert offer.arrival_time == datetime(2026, 3, 1, 17, 30, 0)

    def test_calculates_stops(self):
        client = _make_client()
        offer = client._parse_flight_offer(SAMPLE_FLIGHT_OFFER, SAMPLE_DICTIONARIES)
        assert offer.stops == 0  # 1 segment = 0 stops

    def test_multi_segment_stops(self):
        client = _make_client()
        multi_seg = {
            **SAMPLE_FLIGHT_OFFER,
            "itineraries": [
                {
                    "duration": "PT14H",
                    "segments": [
                        {
                            "carrierCode": "EK",
                            "number": "203",
                            "departure": {"iataCode": "JFK", "at": "2026-03-01T10:00:00"},
                            "arrival": {"iataCode": "DXB", "at": "2026-03-01T17:30:00"},
                            "duration": "PT7H30M",
                        },
                        {
                            "carrierCode": "EK",
                            "number": "404",
                            "departure": {"iataCode": "DXB", "at": "2026-03-01T19:00:00"},
                            "arrival": {"iataCode": "DPS", "at": "2026-03-02T06:00:00"},
                            "duration": "PT6H",
                        },
                    ],
                }
            ],
        }
        offer = client._parse_flight_offer(multi_seg, SAMPLE_DICTIONARIES)
        assert offer.stops == 1

    def test_baggage_included_detected(self):
        client = _make_client()
        offer = client._parse_flight_offer(SAMPLE_FLIGHT_OFFER, SAMPLE_DICTIONARIES)
        assert offer.baggage_included is True

    def test_baggage_not_included_when_missing(self):
        client = _make_client()
        no_bags = {**SAMPLE_FLIGHT_OFFER, "travelerPricings": [{"fareDetailsBySegment": [{}]}]}
        offer = client._parse_flight_offer(no_bags, SAMPLE_DICTIONARIES)
        assert offer.baggage_included is False

    def test_carrier_logo_url(self):
        client = _make_client()
        offer = client._parse_flight_offer(SAMPLE_FLIGHT_OFFER, SAMPLE_DICTIONARIES)
        assert offer.carrier_logo == "https://pics.avs.io/200/200/EK.png"

    def test_empty_itineraries_handled(self):
        client = _make_client()
        empty = {"id": "99", "itineraries": [], "price": {}, "travelerPricings": [{}]}
        offer = client._parse_flight_offer(empty, {})
        assert offer.id == "99"
        assert offer.stops == 0
        assert offer.segments == []

    def test_missing_price_defaults_to_zero(self):
        client = _make_client()
        no_price = {**SAMPLE_FLIGHT_OFFER, "price": {}}
        offer = client._parse_flight_offer(no_price, SAMPLE_DICTIONARIES)
        assert offer.price == 0.0
        assert offer.currency == "USD"


# =============================================================================
# HotelOffer Parsing Tests
# =============================================================================

SAMPLE_HOTEL = {
    "hotelId": "HTDXB001",
    "name": "Grand Hyatt Dubai",
    "chainCode": "HY",
    "rating": 5,
    "geoCode": {"latitude": 25.2, "longitude": 55.3},
    "address": {
        "lines": ["123 Sheikh Zayed Road"],
        "cityName": "Dubai",
        "countryCode": "AE",
    },
}


class TestParseHotel:
    """Tests for _parse_hotel with sample Amadeus data."""

    def test_parses_basic_fields(self):
        client = _make_client()
        hotel = client._parse_hotel(SAMPLE_HOTEL, "DXB")
        assert isinstance(hotel, HotelOffer)
        assert hotel.hotel_id == "HTDXB001"
        assert hotel.name == "Grand Hyatt Dubai"
        assert hotel.chain_code == "HY"
        assert hotel.rating == 5
        assert hotel.city_code == "DXB"

    def test_parses_geo_code(self):
        client = _make_client()
        hotel = client._parse_hotel(SAMPLE_HOTEL, "DXB")
        assert hotel.latitude == 25.2
        assert hotel.longitude == 55.3

    def test_parses_address(self):
        client = _make_client()
        hotel = client._parse_hotel(SAMPLE_HOTEL, "DXB")
        assert "123 Sheikh Zayed Road" in hotel.address
        assert "Dubai" in hotel.address
        assert "AE" in hotel.address

    def test_missing_geo_code(self):
        client = _make_client()
        no_geo = {**SAMPLE_HOTEL, "geoCode": {}}
        hotel = client._parse_hotel(no_geo, "DXB")
        assert hotel.latitude is None
        assert hotel.longitude is None

    def test_missing_address(self):
        client = _make_client()
        no_addr = {**SAMPLE_HOTEL, "address": {}}
        hotel = client._parse_hotel(no_addr, "DXB")
        # Should not raise, address is empty/None-ish
        assert hotel.address is not None  # joins empty list

    def test_minimal_hotel(self):
        client = _make_client()
        minimal = {"hotelId": "H1", "name": "Test"}
        hotel = client._parse_hotel(minimal, "NYC")
        assert hotel.hotel_id == "H1"
        assert hotel.name == "Test"
        assert hotel.city_code == "NYC"
        assert hotel.rating is None
        assert hotel.chain_code is None


# =============================================================================
# AmadeusClient Configuration Tests
# =============================================================================


class TestAmadeusClientConfig:
    """Tests for AmadeusClient initialization and is_configured()."""

    def test_is_configured_with_creds(self):
        with patch.dict(
            os.environ,
            {"AMADEUS_API_KEY": "key", "AMADEUS_API_SECRET": "secret"},  # pragma: allowlist secret
        ):
            client = AmadeusClient()
            assert client.is_configured() is True

    def test_not_configured_without_key(self):
        with patch.dict(
            os.environ,
            {"AMADEUS_API_SECRET": "secret"},  # pragma: allowlist secret
            clear=True,
        ):
            client = AmadeusClient()
            assert client.is_configured() is False

    def test_not_configured_without_secret(self):  # pragma: allowlist secret
        env = {"AMADEUS_API_KEY": "key"}  # pragma: allowlist secret
        with patch.dict(os.environ, env, clear=True):
            client = AmadeusClient()
            assert client.is_configured() is False

    def test_not_configured_with_empty_creds(self):
        with patch.dict(os.environ, {"AMADEUS_API_KEY": "", "AMADEUS_API_SECRET": ""}, clear=True):
            client = AmadeusClient()
            assert client.is_configured() is False

    def test_circuit_breaker_attached(self):
        with patch.dict(os.environ, {"AMADEUS_API_KEY": "k", "AMADEUS_API_SECRET": "s"}):
            client = AmadeusClient()
            assert isinstance(client.circuit_breaker, CircuitBreaker)

    def test_rate_limiter_attached(self):
        with patch.dict(os.environ, {"AMADEUS_API_KEY": "k", "AMADEUS_API_SECRET": "s"}):
            client = AmadeusClient()
            assert isinstance(client.rate_limiter, RateLimiter)

    def test_custom_base_url(self):
        with patch.dict(
            os.environ,
            {
                "AMADEUS_API_KEY": "k",
                "AMADEUS_API_SECRET": "s",
                "AMADEUS_BASE_URL": "https://custom.api.example.com",
            },
        ):
            client = AmadeusClient()
            assert client.base_url == "https://custom.api.example.com"


# =============================================================================
# AmadeusClient Search with Mocked HTTP
# =============================================================================


class TestSearchFlightsMocked:
    """Tests for search_flights with mocked HTTP transport."""

    @pytest.fixture
    def client(self):
        with patch.dict(
            os.environ,
            {"AMADEUS_API_KEY": "test", "AMADEUS_API_SECRET": "test"},  # pragma: allowlist secret
        ):
            c = AmadeusClient()
            # Pre-set a valid token to skip OAuth
            c._access_token = "fake-token"
            c._token_expires_at = datetime(2099, 1, 1)
            return c

    @pytest.mark.asyncio
    async def test_search_flights_returns_parsed_offers(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [SAMPLE_FLIGHT_OFFER],
            "dictionaries": SAMPLE_DICTIONARIES,
        }

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_response)
        mock_http.is_closed = False
        client._http = mock_http

        results = await client.search_flights("JFK", "DXB", "2026-03-01")
        assert len(results) == 1
        assert isinstance(results[0], FlightOffer)
        assert results[0].carrier_code == "EK"

    @pytest.mark.asyncio
    async def test_search_flights_api_error_returns_empty(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = '{"errors": [{"detail": "Server Error"}]}'
        mock_response.json.return_value = {"errors": [{"detail": "Server Error"}]}

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_response)
        mock_http.is_closed = False
        client._http = mock_http

        results = await client.search_flights("JFK", "DXB", "2026-03-01")
        assert results == []

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_repeated_failures(self, client):
        """After failure_threshold errors, circuit opens and rejects."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = '{"errors": []}'
        mock_response.json.return_value = {"errors": []}

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_response)
        mock_http.is_closed = False
        client._http = mock_http

        # Exhaust the circuit breaker (default threshold is 5)
        for _ in range(client.circuit_breaker.failure_threshold):
            await client.search_flights("JFK", "DXB", "2026-03-01")

        assert client.circuit_breaker.state == CircuitState.OPEN

        # Next _make_request should raise CircuitBreakerOpenError
        # But search_flights catches AmadeusAPIError, not CircuitBreakerOpenError
        # so we test via _make_request directly
        with pytest.raises(CircuitBreakerOpenError):
            await client._make_request("GET", "/v2/shopping/flight-offers")
