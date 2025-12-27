"""LLM call utilities for planner nodes.

Provides shared patterns for timing, recording, and retry logic around LLM calls.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator, Optional

if TYPE_CHECKING:
    from app.plan_graph import GraphState


@asynccontextmanager
async def measure_llm_call(
    state: "GraphState",
    *,
    record_on_error: bool = False,
) -> AsyncIterator[None]:
    """Context manager for timing LLM calls.

    Measures elapsed time and records it via _record_llm_time on successful
    completion. Also increments the LLM call counter.

    Args:
        state: GraphState to record timing into
        record_on_error: If True, record timing even on exception (default False)

    Usage:
        async with measure_llm_call(state):
            out = await call_llm_with_timeout(...)

    The timing is only recorded if the LLM call completes without exception
    (unless record_on_error=True).
    """
    # Late import to avoid circular dependency
    from app.plan_graph import _increment_llm_calls, _record_llm_time

    start = time.perf_counter()
    exc_occurred = False
    try:
        yield
    except Exception:
        exc_occurred = True
        raise
    finally:
        if not exc_occurred or record_on_error:
            elapsed_ms = (time.perf_counter() - start) * 1000
            _record_llm_time(state, elapsed_ms)
            _increment_llm_calls(state)


class LLMCallTimer:
    """Manual timer for cases where context manager doesn't fit.

    Usage:
        timer = LLMCallTimer(state)
        timer.start()
        try:
            out = await call_llm_with_timeout(...)
            timer.record()  # Only call on success
        except Exception:
            pass  # Don't record on error
    """

    def __init__(self, state: "GraphState"):
        self.state = state
        self._start: Optional[float] = None

    def start(self) -> None:
        """Start the timer."""
        self._start = time.perf_counter()

    def record(self) -> float:
        """Record the elapsed time and increment call counter.

        Returns:
            Elapsed time in milliseconds
        """
        if self._start is None:
            raise RuntimeError("Timer was not started")

        # Late import to avoid circular dependency
        from app.plan_graph import _increment_llm_calls, _record_llm_time

        elapsed_ms = (time.perf_counter() - self._start) * 1000
        _record_llm_time(self.state, elapsed_ms)
        _increment_llm_calls(self.state)
        return elapsed_ms

    @property
    def elapsed_ms(self) -> float:
        """Get elapsed time without recording."""
        if self._start is None:
            return 0.0
        return (time.perf_counter() - self._start) * 1000
