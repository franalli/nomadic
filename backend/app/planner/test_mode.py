# backend/app/planner/test_mode.py
"""Test-mode detection helpers for planner invariants."""

from __future__ import annotations

from app.config import settings


def is_test_mode() -> bool:
    """
    Check if running under pytest.

    Returns True if PYTEST_RUNNING env var is set to a truthy value.
    This is set by conftest.py before any test imports.
    """
    return settings.pytest_running
