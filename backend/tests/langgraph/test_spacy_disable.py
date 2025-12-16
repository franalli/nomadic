"""
Tests for spaCy disable functionality.

DEPRECATED: spaCy extraction has been replaced by LLM-based extraction.
The extractor no longer calls spaCy functions. These tests are skipped.
"""

import pytest

# Skip entire module - spaCy extraction is no longer used
pytestmark = pytest.mark.skip(
    reason="spaCy extraction has been removed - extraction is now LLM-based"
)


def test_should_run_spacy_ner_respects_disable_spacy_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Test skipped - spaCy no longer used
    pass


def test_should_run_spacy_ner_is_false_on_windows_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Test skipped - spaCy no longer used
    pass


def test_extractor_skips_spacy_paths_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    # Test skipped - spaCy no longer used
    pass
