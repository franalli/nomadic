"""Circuit breaker and rate limiter for external API resilience.

Extracted from amadeus_client.py. These are reusable patterns for any external
API client (Amadeus, Unsplash, etc.).
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)


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
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def record_success(self):
        """Record a successful request."""
        async with self._lock:
            self.failure_count = 0
            self.state = CircuitState.CLOSED

    async def record_failure(self):
        """Record a failed request."""
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
                logger.warning(f"Circuit breaker OPENED after {self.failure_count} failures")

    async def can_execute(self) -> bool:
        """Check if a request can be executed."""
        async with self._lock:
            if self.state == CircuitState.CLOSED:
                return True

            if self.state == CircuitState.OPEN:
                # Check if reset timeout has passed
                elapsed = time.time() - (self.last_failure_time or 0)
                if self.last_failure_time and elapsed > self.reset_timeout:
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
