"""Unit tests for app.sse_state module.

Tests the SSE connection tracking data structures, constants, and
simulated acquire/release logic under the async lock.
"""

from __future__ import annotations

import asyncio

import pytest

from app.sse_state import (
    MAX_SSE_PER_IP,
    MAX_SSE_PER_SESSION,
    _sse_connections,
    _sse_state_lock,
)


@pytest.fixture(autouse=True)
def _clear_sse_connections():
    """Clear the shared _sse_connections dict before and after each test."""
    _sse_connections.clear()
    yield
    _sse_connections.clear()


# ---- 1. Constants are correct ------------------------------------------------


def test_max_sse_per_session_value():
    assert MAX_SSE_PER_SESSION == 2


def test_max_sse_per_ip_value():
    assert MAX_SSE_PER_IP == 5


# ---- 2. Slot acquire ---------------------------------------------------------


@pytest.mark.asyncio
async def test_slot_acquire():
    """Acquiring a slot increments the connection count to 1."""
    async with _sse_state_lock:
        _sse_connections["session1"] += 1

    assert _sse_connections["session1"] == 1


# ---- 3. Slot release ---------------------------------------------------------


@pytest.mark.asyncio
async def test_slot_release():
    """Acquiring then releasing a slot returns the count to 0."""
    # Acquire
    async with _sse_state_lock:
        _sse_connections["session1"] += 1

    assert _sse_connections["session1"] == 1

    # Release
    async with _sse_state_lock:
        _sse_connections["session1"] -= 1

    assert _sse_connections["session1"] == 0


# ---- 4. Session limit --------------------------------------------------------


@pytest.mark.asyncio
async def test_session_limit():
    """Filling MAX_SSE_PER_SESSION slots reaches the expected count."""
    for _ in range(MAX_SSE_PER_SESSION):
        async with _sse_state_lock:
            _sse_connections["session1"] += 1

    assert _sse_connections["session1"] == MAX_SSE_PER_SESSION
    assert _sse_connections["session1"] == 2


# ---- 5. IP limit -------------------------------------------------------------


@pytest.mark.asyncio
async def test_ip_limit():
    """Filling MAX_SSE_PER_IP slots for an IP key reaches the expected count."""
    ip_key = "ip:192.168.1.1"
    for _ in range(MAX_SSE_PER_IP):
        async with _sse_state_lock:
            _sse_connections[ip_key] += 1

    assert _sse_connections[ip_key] == MAX_SSE_PER_IP
    assert _sse_connections[ip_key] == 5


# ---- 6. Concurrent contention ------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_contention():
    """Multiple coroutines modifying the dict under the lock produce a correct final count."""
    num_tasks = 20

    async def acquire_slot():
        async with _sse_state_lock:
            _sse_connections["contested"] += 1

    await asyncio.gather(*(acquire_slot() for _ in range(num_tasks)))

    assert _sse_connections["contested"] == num_tasks


@pytest.mark.asyncio
async def test_concurrent_acquire_and_release():
    """Concurrent acquires followed by concurrent releases yields zero."""
    num_tasks = 15

    async def acquire_slot():
        async with _sse_state_lock:
            _sse_connections["contested2"] += 1

    async def release_slot():
        async with _sse_state_lock:
            _sse_connections["contested2"] -= 1

    # All acquires first
    await asyncio.gather(*(acquire_slot() for _ in range(num_tasks)))
    assert _sse_connections["contested2"] == num_tasks

    # All releases
    await asyncio.gather(*(release_slot() for _ in range(num_tasks)))
    assert _sse_connections["contested2"] == 0


# ---- 7. Multiple sessions isolated -------------------------------------------


@pytest.mark.asyncio
async def test_multiple_sessions_isolated():
    """Incrementing separate session keys does not cause cross-contamination."""
    async with _sse_state_lock:
        _sse_connections["session1"] += 1
        _sse_connections["session1"] += 1

    async with _sse_state_lock:
        _sse_connections["session2"] += 1

    assert _sse_connections["session1"] == 2
    assert _sse_connections["session2"] == 1
    # Ensure no phantom keys
    assert set(_sse_connections.keys()) == {"session1", "session2"}
