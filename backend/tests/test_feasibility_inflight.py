"""Tests for feasibility inflight deduplication with asyncio.Lock.

Verifies:
- Singleflight: concurrent calls with same key produce only 1 LLM invocation
- Cleanup: future is removed from inflight dict after exception
- Cancel: cancel_feasibility_inflight() clears all entries under lock
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.planner.services.feasibility_service import (
    FeasibilityCheck,
    _feasibility_cache,
    _feasibility_inflight,
    _feasibility_inflight_lock,
    cancel_feasibility_inflight,
    get_feasibility_llm,
)


@pytest.fixture(autouse=True)
def _clear_inflight():
    """Reset inflight dict and L1 cache before/after each test."""
    _feasibility_inflight.clear()
    _feasibility_cache.clear()
    yield
    _feasibility_inflight.clear()
    _feasibility_cache.clear()


class TestSingleflightDedup:
    """Two concurrent calls with same cache key should invoke LLM only once."""

    @pytest.mark.asyncio
    async def test_concurrent_same_key_single_llm_call(self):
        # Use an event to guarantee both coroutines overlap: the LLM mock
        # blocks until the event is set, ensuring the second caller arrives
        # while the first is still in-flight.
        llm_entered = asyncio.Event()

        async def _slow_llm(*args, **kwargs):
            llm_entered.set()
            await asyncio.sleep(0.01)
            return FeasibilityCheck(possible=True, reason="Great reef nearby")

        llm_mock = AsyncMock(side_effect=_slow_llm)

        with (
            patch(
                "app.planner.services.feasibility_service._check_feasibility_llm",
                llm_mock,
            ),
            # Bypass L2 DB cache so we reach the inflight path
            patch(
                "app.db._get_async_session_factory",
                side_effect=Exception("no db"),
            ),
        ):
            results = await asyncio.gather(
                get_feasibility_llm("diving", "Maldives"),
                get_feasibility_llm("diving", "Maldives"),
            )

        # Both callers get the same result
        assert results[0] == (True, "Great reef nearby")
        assert results[1] == (True, "Great reef nearby")

        # LLM was invoked exactly once (singleflight dedup)
        assert llm_mock.call_count == 1

    @pytest.mark.asyncio
    async def test_different_keys_get_separate_calls(self):
        llm_mock = AsyncMock(
            side_effect=[
                FeasibilityCheck(possible=True, reason="Good diving"),
                FeasibilityCheck(possible=False, reason="No slopes"),
            ],
        )

        with (
            patch(
                "app.planner.services.feasibility_service._check_feasibility_llm",
                llm_mock,
            ),
            patch(
                "app.db._get_async_session_factory",
                side_effect=Exception("no db"),
            ),
        ):
            results = await asyncio.gather(
                get_feasibility_llm("diving", "Maldives"),
                get_feasibility_llm("skiing", "Maldives"),
            )

        assert results[0] == (True, "Good diving")
        assert results[1] == (False, "No slopes")
        assert llm_mock.call_count == 2


class TestCleanupAfterException:
    """Future is removed from inflight dict even when LLM call raises."""

    @pytest.mark.asyncio
    async def test_inflight_cleared_on_exception(self):
        llm_mock = AsyncMock(side_effect=RuntimeError("LLM exploded"))

        with (
            patch(
                "app.planner.services.feasibility_service._check_feasibility_llm",
                llm_mock,
            ),
            patch(
                "app.db._get_async_session_factory",
                side_effect=Exception("no db"),
            ),
        ):
            # _check_feasibility_llm itself catches exceptions and fails open,
            # but if it propagates, the finally block should still clean up.
            # Since the mock raises before the internal try/except in
            # _check_feasibility_llm (we're patching the whole function),
            # the exception propagates through get_feasibility_llm.
            with pytest.raises(RuntimeError, match="LLM exploded"):
                await get_feasibility_llm("diving", "Bali")

        # Inflight entry must be cleaned up
        async with _feasibility_inflight_lock:
            assert len(_feasibility_inflight) == 0


class TestCancelInflight:
    """cancel_feasibility_inflight() cancels futures and clears dict under lock."""

    @pytest.mark.asyncio
    async def test_cancel_clears_all_entries(self):
        loop = asyncio.get_running_loop()

        # Manually insert some inflight futures
        async with _feasibility_inflight_lock:
            for i in range(5):
                fut = loop.create_future()
                _feasibility_inflight[f"key_{i}"] = fut

        cancelled = await cancel_feasibility_inflight()

        assert cancelled == 5
        async with _feasibility_inflight_lock:
            assert len(_feasibility_inflight) == 0

    @pytest.mark.asyncio
    async def test_cancel_skips_already_done_futures(self):
        loop = asyncio.get_running_loop()

        async with _feasibility_inflight_lock:
            # One pending future
            pending = loop.create_future()
            _feasibility_inflight["pending"] = pending

            # One already-resolved future
            done = loop.create_future()
            done.set_result((True, "done"))
            _feasibility_inflight["done"] = done

        cancelled = await cancel_feasibility_inflight()

        # Only the pending one counts as cancelled
        assert cancelled == 1
        async with _feasibility_inflight_lock:
            assert len(_feasibility_inflight) == 0
