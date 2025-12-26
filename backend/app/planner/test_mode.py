# backend/app/planner/test_mode.py
"""
Test-mode detection for planner invariants.

PR4: Hard fail in tests - converts logged anomalies into test failures.

When PYTEST_RUNNING=1 is set (by conftest.py), invariant violations
that would normally just log+skip in production will raise AssertionError
for immediate test failure.
"""

from __future__ import annotations

import os
from typing import Optional


def is_test_mode() -> bool:
    """
    Check if running under pytest.

    Returns True if PYTEST_RUNNING env var is set to a truthy value.
    This is set by conftest.py before any test imports.
    """
    return os.environ.get("PYTEST_RUNNING", "").lower() in ("1", "true", "yes")


def assert_invariant(
    condition: bool,
    message: str,
    *,
    log_fn: Optional[callable] = None,
) -> None:
    """
    Assert an invariant that should hold.

    In test mode, raises AssertionError immediately.
    In production, logs the violation and continues.

    Args:
        condition: The invariant condition (should be True)
        message: Error message if condition is False
        log_fn: Optional logging function for production mode
    """
    if condition:
        return

    if is_test_mode():
        raise AssertionError(f"Invariant violation: {message}")

    # Production mode - log and continue
    if log_fn is not None:
        log_fn(f"INVARIANT WARNING: {message}")


def raise_if_test_mode(message: str) -> None:
    """
    Raise AssertionError if in test mode.

    Use this at points where production code logs+skips but tests
    should fail immediately.

    Args:
        message: Error message for the assertion
    """
    if is_test_mode():
        raise AssertionError(message)
