"""Root conftest.py for all backend tests.

Provides automatic cache isolation for complete test independence.
This ensures that no cached LLM responses, validation results, or
other state can leak between tests.

PR4: Sets PYTEST_RUNNING env var for test-mode detection.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# =============================================================================
# Load .env for LLM smoke tests (before any other imports)
# =============================================================================
try:
    from dotenv import load_dotenv

    env_path = Path(__file__).parents[1] / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # dotenv not installed, skip

# =============================================================================
# PR4: Test-mode detection - set env var before any imports
# =============================================================================
os.environ["PYTEST_RUNNING"] = "1"


def pytest_collection_modifyitems(session, config, items):
    """Reorder tests: DB first, then langgraph."""
    db_tests = []
    langgraph_tests = []

    for item in items:
        path_str = str(item.fspath)
        if "langgraph" in path_str:
            langgraph_tests.append(item)
        else:
            db_tests.append(item)

    items[:] = db_tests + langgraph_tests


@pytest.fixture(autouse=True)
def clear_all_plan_graph_caches():
    """
    Clear ALL planner caches before and after each test.

    This fixture runs automatically for every test and ensures:
    - LLM response caches are cleared
    - Validation caches are cleared
    - MemorySaver checkpointer storage is cleared
    - Prompt caches (LRU + Jinja2) are cleared
    - Date normalizer singleton is reset

    This prevents state leakage between tests that could cause:
    - Cached responses from one test affecting another
    - Destination confusion/hallucinations
    - Stale validation results
    """
    import asyncio

    from app.planner import clear_all_caches

    async def _clear():
        await clear_all_caches()

    # Clear before test (clear_all_caches is async)
    asyncio.run(_clear())

    yield

    # Clear after test
    asyncio.run(_clear())
