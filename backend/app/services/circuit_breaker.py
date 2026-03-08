"""Shared circuit breaker for external API providers."""

from __future__ import annotations

import logging
import time
from threading import Lock

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Simple circuit breaker with failure threshold and open duration.

    Thread-safe via threading.Lock (sub-microsecond critical sections).
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        open_seconds: int = 120,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.open_seconds = open_seconds
        self._lock = Lock()
        self._failures = 0
        self._open_until = 0.0

    def is_open(self) -> bool:
        with self._lock:
            if self._open_until and time.monotonic() < self._open_until:
                return True
            if self._open_until and time.monotonic() >= self._open_until:
                # Half-open: reset and allow a probe
                self._failures = 0
                self._open_until = 0.0
            return False

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._open_until = time.monotonic() + self.open_seconds
                logger.warning(
                    "%s circuit breaker OPEN after %d failures (for %ds)",
                    self.name,
                    self._failures,
                    self.open_seconds,
                )

    def record_success(self) -> None:
        with self._lock:
            if self._failures > 0:
                self._failures = 0
                self._open_until = 0.0
