"""Root conftest.py for all backend tests.

Provides automatic cache isolation for complete test independence.
This ensures that no cached LLM responses, validation results, or
other state can leak between tests.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def clear_all_plan_graph_caches():
    """
    Clear ALL plan_graph caches before and after each test.

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
    from app.plan_graph import clear_all_caches

    # Clear before test
    clear_all_caches()

    yield

    # Clear after test
    clear_all_caches()
