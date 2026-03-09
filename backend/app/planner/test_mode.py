# backend/app/planner/test_mode.py
"""Test-mode detection helpers for planner invariants."""

from __future__ import annotations

import os


def is_test_mode() -> bool:
    """
    Check if running under pytest.

    Returns True if PYTEST_RUNNING env var is set to a truthy value.
    This is set by conftest.py before any test imports.

    Reads os.environ directly (not settings singleton) so that
    monkeypatch.setenv / delenv changes are visible at runtime.
    """
    val = os.environ.get("PYTEST_RUNNING", "").strip().lower()
    return val in ("1", "true", "yes")
