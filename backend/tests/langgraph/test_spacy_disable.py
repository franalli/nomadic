import pytest

import app.plan_graph as plan_graph


def test_should_run_spacy_ner_respects_disable_spacy_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(plan_graph, "_SPACY_AVAILABLE", True)
    monkeypatch.setenv("DISABLE_SPACY", "1")
    monkeypatch.delenv("ENABLE_SPACY_ON_WINDOWS", raising=False)

    assert plan_graph._should_run_spacy_ner("travel in December", {}) is False


def test_should_run_spacy_ner_is_false_on_windows_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(plan_graph, "_SPACY_AVAILABLE", True)
    monkeypatch.delenv("DISABLE_SPACY", raising=False)
    monkeypatch.delenv("ENABLE_SPACY_ON_WINDOWS", raising=False)
    monkeypatch.setattr(plan_graph.sys, "platform", "win32")

    assert plan_graph._should_run_spacy_ner("travel in December", {}) is False


def test_extractor_skips_spacy_paths_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    text = "I'd like to travel in December with direct flights, business class please."

    def spacy_extract_should_not_run(*args, **kwargs):
        raise AssertionError("spaCy extraction should be skipped when disabled")

    monkeypatch.setattr(plan_graph, "_SPACY_AVAILABLE", True)
    monkeypatch.setenv("DISABLE_SPACY", "1")
    monkeypatch.delenv("ENABLE_SPACY_ON_WINDOWS", raising=False)
    monkeypatch.setattr(plan_graph, "_spacy_extract_entities", spacy_extract_should_not_run)

    state = plan_graph.GraphState(user_text=text, trip_inputs=plan_graph.TripInputs())
    plan_graph.extractor(state)
