"""Unit tests for the CircuitBreaker class."""

import threading
from unittest.mock import patch

from app.services.circuit_breaker import CircuitBreaker


class TestCircuitBreakerBasics:
    """Core state transitions for the circuit breaker."""

    def test_initially_closed(self):
        cb = CircuitBreaker("test", failure_threshold=5, open_seconds=120)
        assert cb.is_open() is False

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=5, open_seconds=120)
        for _ in range(4):
            cb.record_failure()
        assert cb.is_open() is False

    def test_opens_at_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=5, open_seconds=120)
        for _ in range(5):
            cb.record_failure()
        assert cb.is_open() is True

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker("test", failure_threshold=5, open_seconds=120)
        for _ in range(4):
            cb.record_failure()
        cb.record_success()
        # After reset, another 4 failures should not trip the breaker
        for _ in range(4):
            cb.record_failure()
        assert cb.is_open() is False


class TestCircuitBreakerHalfOpen:
    """Half-open behaviour after the open duration expires."""

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker("test", failure_threshold=3, open_seconds=60)

        # Trip the breaker at t=100
        with patch("app.services.circuit_breaker.time.monotonic", return_value=100.0):
            for _ in range(3):
                cb.record_failure()
            assert cb.is_open() is True

        # Still open at t=150 (before 100+60)
        with patch("app.services.circuit_breaker.time.monotonic", return_value=150.0):
            assert cb.is_open() is True

        # Half-open reset at t=161 (past 100+60)
        with patch("app.services.circuit_breaker.time.monotonic", return_value=161.0):
            assert cb.is_open() is False

    def test_success_after_half_open_keeps_closed(self):
        cb = CircuitBreaker("test", failure_threshold=3, open_seconds=60)

        # Trip at t=100
        with patch("app.services.circuit_breaker.time.monotonic", return_value=100.0):
            for _ in range(3):
                cb.record_failure()

        # Half-open reset at t=200
        with patch("app.services.circuit_breaker.time.monotonic", return_value=200.0):
            assert cb.is_open() is False
            cb.record_success()

        # Should stay closed; a few new failures don't re-open
        with patch("app.services.circuit_breaker.time.monotonic", return_value=201.0):
            cb.record_failure()
            assert cb.is_open() is False


class TestCircuitBreakerThreadSafety:
    """Concurrent access must not corrupt internal counters."""

    def test_concurrent_failures(self):
        cb = CircuitBreaker("test", failure_threshold=50, open_seconds=120)
        barrier = threading.Barrier(10)

        def hammer():
            barrier.wait()
            for _ in range(10):
                cb.record_failure()

        threads = [threading.Thread(target=hammer) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 10 threads x 10 failures = 100 total, well above threshold of 50
        assert cb.is_open() is True
