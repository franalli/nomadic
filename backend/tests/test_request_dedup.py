"""Unit tests for app.request_dedup — idempotency and expand-itinerary mutex."""

import asyncio

import pytest

from app.request_dedup import (
    _expand_in_flight,
    _idempotency_cache,
    acquire_expand_slot,
    check_idempotency,
    release_expand_slot,
)


@pytest.fixture(autouse=True)
def _clear_dedup_caches():
    """Ensure clean caches before and after every test."""
    _idempotency_cache.clear()
    _expand_in_flight.clear()
    yield
    _idempotency_cache.clear()
    _expand_in_flight.clear()


# ---------------------------------------------------------------------------
# check_idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_idempotency_new_key():
    """A previously unseen key is not a duplicate — returns False."""
    result = await check_idempotency("key-abc-123")
    assert result is False


@pytest.mark.asyncio
async def test_check_idempotency_duplicate():
    """The same key seen twice returns True on the second call."""
    first = await check_idempotency("key-dup")
    second = await check_idempotency("key-dup")
    assert first is False
    assert second is True


@pytest.mark.asyncio
async def test_check_idempotency_none_key():
    """None key is never treated as a duplicate — always returns False."""
    assert await check_idempotency(None) is False
    assert await check_idempotency(None) is False


@pytest.mark.asyncio
async def test_check_idempotency_empty_string_key():
    """Empty string key is falsy — always returns False, same as None."""
    assert await check_idempotency("") is False
    assert await check_idempotency("") is False


@pytest.mark.asyncio
async def test_check_idempotency_distinct_keys():
    """Different keys are tracked independently."""
    assert await check_idempotency("key-a") is False
    assert await check_idempotency("key-b") is False
    # Both should now be duplicates
    assert await check_idempotency("key-a") is True
    assert await check_idempotency("key-b") is True


# ---------------------------------------------------------------------------
# acquire_expand_slot / release_expand_slot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acquire_expand_slot_first_time():
    """First acquisition for a session succeeds — returns True."""
    result = await acquire_expand_slot("session-1")
    assert result is True


@pytest.mark.asyncio
async def test_acquire_expand_slot_duplicate_rejected():
    """Second acquisition for the same session is rejected — returns False."""
    first = await acquire_expand_slot("session-1")
    second = await acquire_expand_slot("session-1")
    assert first is True
    assert second is False


@pytest.mark.asyncio
async def test_release_then_reacquire():
    """After releasing a slot, the same session can re-acquire it."""
    assert await acquire_expand_slot("session-1") is True
    await release_expand_slot("session-1")
    assert await acquire_expand_slot("session-1") is True


@pytest.mark.asyncio
async def test_release_nonexistent_slot():
    """Releasing a slot that was never acquired does not raise."""
    await release_expand_slot("never-acquired")  # Should not raise


@pytest.mark.asyncio
async def test_acquire_expand_slot_independent_sessions():
    """Different sessions can hold slots concurrently."""
    assert await acquire_expand_slot("session-a") is True
    assert await acquire_expand_slot("session-b") is True
    # Both are still held — re-acquire should fail for each
    assert await acquire_expand_slot("session-a") is False
    assert await acquire_expand_slot("session-b") is False


@pytest.mark.asyncio
async def test_concurrent_acquire():
    """Only one of N concurrent acquire calls for the same session succeeds."""
    n = 20
    results = await asyncio.gather(*(acquire_expand_slot("race-session") for _ in range(n)))
    assert results.count(True) == 1
    assert results.count(False) == n - 1
