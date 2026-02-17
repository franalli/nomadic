"""Shared fire-and-forget background task tracker.

All modules that spawn asyncio.Tasks register them here so the lifespan
shutdown hook can cancel them in one place.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task] = set()


def track(task: asyncio.Task) -> None:
    """Register a background task for lifecycle tracking."""
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def cancel_all() -> int:
    """Cancel all tracked tasks and await completion. Returns count cancelled."""
    tasks = set(_background_tasks)  # snapshot
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    count = len(tasks)
    _background_tasks.clear()
    return count
