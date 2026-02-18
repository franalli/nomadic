"""Tests for backend/app/planner/test_mode.py.

Covers:
- is_test_mode: truthy/falsy PYTEST_RUNNING env var values
"""

from __future__ import annotations

import pytest

from app.planner.test_mode import is_test_mode


class TestIsTestMode:
    """Test is_test_mode() env var detection."""

    def test_pytest_running_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYTEST_RUNNING", "1")
        assert is_test_mode() is True

    def test_pytest_running_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYTEST_RUNNING", "true")
        assert is_test_mode() is True

    def test_pytest_running_yes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYTEST_RUNNING", "yes")
        assert is_test_mode() is True

    def test_pytest_running_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYTEST_RUNNING", "false")
        assert is_test_mode() is False

    def test_pytest_running_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYTEST_RUNNING", "")
        assert is_test_mode() is False

    def test_pytest_running_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PYTEST_RUNNING", raising=False)
        assert is_test_mode() is False

    def test_case_insensitive_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYTEST_RUNNING", "TRUE")
        assert is_test_mode() is True

    def test_case_insensitive_yes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYTEST_RUNNING", "YES")
        assert is_test_mode() is True

    def test_zero_is_falsy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYTEST_RUNNING", "0")
        assert is_test_mode() is False

    def test_no_is_falsy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYTEST_RUNNING", "no")
        assert is_test_mode() is False
