"""Unit tests for LocalExpert enrichment endpoint status semantics."""

from __future__ import annotations

import json
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
    monkeypatch.setattr(main, "get_document", _document)
    monkeypatch.setattr(
        main,
        "get_document_data",
        lambda _doc: SimpleNamespace(strategy_sections=[section]),
    )


@pytest.mark.asyncio
async def test_local_expert_pending_returns_202(monkeypatch: pytest.MonkeyPatch) -> None:
    section = StrategySection(
        id="strategy_local_expert",
        specialist_type="local_expert",
        travel_intelligence={},
        local_expert_enrichment={"state": "pending", "updated_at": "2026-02-22T00:00:00Z"},
    )
    _patch_common(monkeypatch, section)

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
    section = StrategySection(
        id="strategy_local_expert",
        specialist_type="local_expert",
        travel_intelligence={},
        local_expert_enrichment={
            "state": "failed",
            "error_code": "timeout",
            "updated_at": "2026-02-22T00:00:00Z",
        },
    )
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
    section = StrategySection(
        id="strategy_local_expert",
        specialist_type="local_expert",
        travel_intelligence={"visa_entry": {"max_stay_days": 30}},
        local_expert_enrichment={"state": "ready", "updated_at": "2026-02-22T00:00:00Z"},
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
