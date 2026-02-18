"""Unit tests for app.services.task_tracker."""

import asyncio

import pytest

from app.services.task_tracker import _background_tasks, cancel_all, track


@pytest.fixture(autouse=True)
def _clear_task_set():
    """Ensure a clean task set before and after every test."""
    _background_tasks.clear()
    yield
    _background_tasks.clear()


@pytest.mark.asyncio
async def test_track_registers_task():
    """track() adds the task to the internal set."""

    async def noop():
        await asyncio.sleep(10)

    task = asyncio.create_task(noop())
    track(task)

    assert task in _background_tasks

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_done_callback_discards_completed_task():
    """A task that finishes normally is auto-removed from the set."""

    async def instant():
        return 42

    task = asyncio.create_task(instant())
    track(task)

    await task  # let it complete

    # After completion the done-callback should have removed it
    assert task not in _background_tasks


@pytest.mark.asyncio
async def test_cancel_all_cancels_tracked_tasks():
    """cancel_all() cancels every tracked task and returns the count."""

    async def hang():
        await asyncio.sleep(3600)

    t1 = asyncio.create_task(hang())
    t2 = asyncio.create_task(hang())
    track(t1)
    track(t2)

    count = await cancel_all()

    assert count == 2
    assert t1.cancelled()
    assert t2.cancelled()
    assert len(_background_tasks) == 0


@pytest.mark.asyncio
async def test_cancel_all_empty_set():
    """cancel_all() with no tracked tasks returns 0."""
    count = await cancel_all()
    assert count == 0


@pytest.mark.asyncio
async def test_cancel_all_clears_set():
    """After cancel_all() the internal set is empty."""

    async def hang():
        await asyncio.sleep(3600)

    t1 = asyncio.create_task(hang())
    t2 = asyncio.create_task(hang())
    t3 = asyncio.create_task(hang())
    track(t1)
    track(t2)
    track(t3)

    assert len(_background_tasks) == 3

    await cancel_all()

    assert len(_background_tasks) == 0
