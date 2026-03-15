"""Unit tests for LocalExpert enrichment endpoint status semantics."""

from __future__ import annotations

import json
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from starlette.responses import JSONResponse

import app.main as main
from app.schemas import SpecialistEnrichmentResponse, StrategySection


def _patch_common(monkeypatch: pytest.MonkeyPatch, section: StrategySection) -> None:
    monkeypatch.setattr(main, "get_session_from_request", lambda _req: "session-token")

    async def _session(*_args, **_kwargs):
        return SimpleNamespace(id=1)

    async def _document(*_args, **_kwargs):
        return object()

    monkeypatch.setattr(main, "get_session_by_token", _session)
    monkeypatch.setattr(main, "get_document_by_session_id", _document)
    monkeypatch.setattr(
        main,
        "get_document_data",
        lambda _doc: SimpleNamespace(strategy_sections=[section]),
    )


def _make_local_expert_section(
    *,
    state: str,
    travel_intelligence: dict | None = None,
    error_code: str | None = None,
) -> StrategySection:
    enrichment: dict[str, object] = {"state": state, "updated_at": "2026-02-22T00:00:00Z"}
    if error_code is not None:
        enrichment["error_code"] = error_code
    return StrategySection(
        id="strategy_local_expert",
        specialist_type="local_expert",
        travel_intelligence=travel_intelligence or {},
        local_expert_enrichment=enrichment,
    )


def _patch_section_sequence(
    monkeypatch: pytest.MonkeyPatch,
    sections: list[StrategySection],
) -> None:
    monkeypatch.setattr(main, "get_session_from_request", lambda _req: "session-token")

    async def _session(*_args, **_kwargs):
        return SimpleNamespace(id=1)

    async def _document(*_args, **_kwargs):
        return object()

    iterator: Iterator[StrategySection] = iter(sections)
    current = sections[-1]

    def _get_document_data(_doc: object) -> SimpleNamespace:
        nonlocal current
        try:
            current = next(iterator)
        except StopIteration:
            pass
        return SimpleNamespace(strategy_sections=[current])

    monkeypatch.setattr(main, "get_session_by_token", _session)
    monkeypatch.setattr(main, "get_document_by_session_id", _document)
    monkeypatch.setattr(main, "get_document_data", _get_document_data)


@pytest.mark.asyncio
async def test_local_expert_pending_returns_202(monkeypatch: pytest.MonkeyPatch) -> None:
    section = _make_local_expert_section(state="pending")
    _patch_common(monkeypatch, section)
    monkeypatch.setattr(main, "SPECIALIST_ENRICHMENT_LONG_POLL_TIMEOUT_SECONDS", 0.0)

    response = await main.get_specialist_enrichment.__wrapped__(
        request=SimpleNamespace(),
        section_id=section.id,
        db=None,
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 202
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["status"] == "pending"
    assert payload["section_id"] == section.id
    assert payload["retry_after_ms"] == 1500


@pytest.mark.asyncio
async def test_local_expert_failed_returns_error_code(monkeypatch: pytest.MonkeyPatch) -> None:
    section = _make_local_expert_section(state="failed", error_code="timeout")
    _patch_common(monkeypatch, section)

    response = await main.get_specialist_enrichment.__wrapped__(
        request=SimpleNamespace(),
        section_id=section.id,
        db=None,
    )

    assert isinstance(response, SpecialistEnrichmentResponse)
    assert response.status == "failed"
    assert response.error_code == "timeout"
    assert response.data is None


@pytest.mark.asyncio
async def test_local_expert_ready_returns_section(monkeypatch: pytest.MonkeyPatch) -> None:
    section = _make_local_expert_section(
        state="ready",
        travel_intelligence={"visa_entry": {"max_stay_days": 30}},
    )
    _patch_common(monkeypatch, section)

    response = await main.get_specialist_enrichment.__wrapped__(
        request=SimpleNamespace(),
        section_id=section.id,
        db=None,
    )

    assert isinstance(response, SpecialistEnrichmentResponse)
    assert response.status == "ready"
    assert response.data is not None
    assert response.data.get("id") == section.id


@pytest.mark.asyncio
async def test_local_expert_long_poll_returns_ready_when_phase_b_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = _make_local_expert_section(state="pending")
    ready = _make_local_expert_section(
        state="ready",
        travel_intelligence={"safety": {"headline": "Use registered guides"}},
    )
    _patch_section_sequence(monkeypatch, [pending, ready])
    monkeypatch.setattr(main, "SPECIALIST_ENRICHMENT_LONG_POLL_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(main, "SPECIALIST_ENRICHMENT_LONG_POLL_INTERVAL_SECONDS", 0.0)

    sleep_calls: list[float] = []

    async def _sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(main.asyncio, "sleep", _sleep)

    response = await main.get_specialist_enrichment.__wrapped__(
        request=SimpleNamespace(),
        section_id=pending.id,
        db=None,
    )

    assert isinstance(response, SpecialistEnrichmentResponse)
    assert response.status == "ready"
    assert response.data is not None
    assert response.data["travel_intelligence"]["safety"]["headline"] == "Use registered guides"
    assert sleep_calls == [0.0]


@pytest.mark.asyncio
async def test_local_expert_long_poll_times_out_to_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    section = _make_local_expert_section(state="pending")
    _patch_common(monkeypatch, section)
    monkeypatch.setattr(main, "SPECIALIST_ENRICHMENT_LONG_POLL_TIMEOUT_SECONDS", 0.0)

    async def _sleep(_delay: float) -> None:
        raise AssertionError("sleep should not run once the long-poll deadline is exhausted")

    monkeypatch.setattr(main.asyncio, "sleep", _sleep)

    response = await main.get_specialist_enrichment.__wrapped__(
        request=SimpleNamespace(),
        section_id=section.id,
        db=None,
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 202
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["status"] == "pending"
    assert payload["section_id"] == section.id


@pytest.mark.asyncio
async def test_local_expert_long_poll_does_not_touch_expired_session_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeSession:
        def __init__(self) -> None:
            self.expired = False

        @property
        def id(self) -> int:
            if self.expired:
                raise AssertionError("session.id accessed after expire_all")
            return 1

    class _FakeDb:
        def __init__(self, session: _FakeSession) -> None:
            self._session = session
            self.rollback_calls = 0

        def expire_all(self) -> None:
            self._session.expired = True

        async def rollback(self) -> None:
            self.rollback_calls += 1

    pending = _make_local_expert_section(state="pending")
    ready = _make_local_expert_section(
        state="ready",
        travel_intelligence={"safety": {"headline": "Use registered guides"}},
    )
    sections: Iterator[StrategySection] = iter([pending, ready])
    current = ready
    session = _FakeSession()
    db = _FakeDb(session)

    monkeypatch.setattr(main, "get_session_from_request", lambda _req: "session-token")

    async def _session(*_args, **_kwargs):
        return session

    async def _document(*_args, **_kwargs):
        return object()

    monkeypatch.setattr(main, "get_session_by_token", _session)
    monkeypatch.setattr(main, "get_document_by_session_id", _document)

    def _get_document_data(_doc: object) -> SimpleNamespace:
        nonlocal current
        try:
            current = next(sections)
        except StopIteration:
            pass
        return SimpleNamespace(strategy_sections=[current])

    monkeypatch.setattr(
        main,
        "get_document_data",
        _get_document_data,
    )
    monkeypatch.setattr(main, "SPECIALIST_ENRICHMENT_LONG_POLL_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(main, "SPECIALIST_ENRICHMENT_LONG_POLL_INTERVAL_SECONDS", 0.0)

    sleep_calls: list[float] = []

    async def _sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(main.asyncio, "sleep", _sleep)

    response = await main.get_specialist_enrichment.__wrapped__(
        request=SimpleNamespace(),
        section_id=pending.id,
        db=db,
    )

    assert isinstance(response, SpecialistEnrichmentResponse)
    assert response.status == "ready"
    assert response.data is not None
    assert response.data["travel_intelligence"]["safety"]["headline"] == "Use registered guides"
    assert sleep_calls == [0.0]
    assert db.rollback_calls == 1
