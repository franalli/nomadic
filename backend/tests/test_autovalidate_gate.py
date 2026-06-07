"""Unit tests for the deterministic validate_plan backstop gate.

``_should_autovalidate`` guarantees a feasibility check runs on every substantive
turn even when the model omits validate_plan (Gemini Flash often does), while
staying inert on pure Q&A turns and de-duping when the model already validated.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from app.planner.services.agent_runner import (
    _merge_patch_changed_fields,
    _should_autobuild,
    _should_autovalidate,
)
from app.planner.tools.validate_plan import validate_plan

_CORE = {"destination": "Bali", "start_date": "2026-09-01", "end_date": "2026-09-08"}


def _state(*, trip_plan=None, tools=None, fields=None):
    return {
        "trip_plan": trip_plan if trip_plan is not None else dict(_CORE),
        "turn_meta": {
            "tools_called": list(tools or []),
            "fields_changed": list(fields or []),
        },
    }


def test_validates_after_deterministic_autobuild() -> None:
    # built_this_turn=True with core fields set -> validate.
    assert _should_autovalidate(_state(), built_this_turn=True) is True


def test_validates_after_search_tiles() -> None:
    assert _should_autovalidate(_state(tools=["search_tiles"]), built_this_turn=False) is True


def test_validates_after_specialist_advice() -> None:
    assert (
        _should_autovalidate(_state(tools=["get_specialist_advice"]), built_this_turn=False) is True
    )


def test_validates_when_core_field_changed() -> None:
    assert _should_autovalidate(_state(fields=["budget"]), built_this_turn=False) is True


def test_deduped_when_model_already_validated() -> None:
    # Model called validate_plan itself -> backstop must not double-run.
    state = _state(tools=["search_tiles", "validate_plan"])
    assert _should_autovalidate(state, built_this_turn=True) is False


def test_skipped_without_core_fields() -> None:
    # No dates yet -> nothing meaningful to validate.
    state = _state(trip_plan={"destination": "Bali"}, tools=["search_tiles"])
    assert _should_autovalidate(state, built_this_turn=False) is False


def test_skipped_on_pure_qa_turn() -> None:
    # Core fields set, but this turn only did a lookup / answered a question:
    # no fetch, no field change, nothing built -> do not re-validate.
    state = _state(tools=["get_local_intel"], fields=[])
    assert _should_autovalidate(state, built_this_turn=False) is False


def test_handles_missing_turn_meta() -> None:
    assert _should_autovalidate({"trip_plan": dict(_CORE)}, built_this_turn=True) is True
    assert _should_autovalidate({}, built_this_turn=True) is False


# --- skip_route_check: the backstop runs deterministic checks only -------------


async def test_backstop_skips_llm_route_check(monkeypatch) -> None:
    """skip_route_check=True must NOT invoke the LLM-backed place/route check, yet
    still return deterministic blockers (here: end date before start date)."""
    import importlib

    # The package re-exports a `constraint_guard` function, shadowing the
    # submodule name -- fetch the real module object explicitly to patch it.
    cg = importlib.import_module("app.planner.nodes.constraint_guard")

    called = {"route": False}

    async def _boom(*_a, **_k):
        called["route"] = True
        raise AssertionError("route check must be skipped in backstop mode")

    monkeypatch.setattr(cg, "check_route_constraint", _boom)
    result = await validate_plan.coroutine(
        destination="Paris",
        origin="New York",
        start_date="2026-09-10",
        end_date="2026-09-01",  # end before start -> deterministic blocker
        budget=5000,
        skip_route_check=True,
    )
    assert result["valid"] is False
    assert "END_BEFORE_START" in {v.get("code") for v in result["violations"]}
    assert called["route"] is False  # LLM route check never ran


async def test_model_invoked_runs_route_check(monkeypatch) -> None:
    """Default (model-invoked) path still runs the full LLM route/place check."""
    import importlib

    cg = importlib.import_module("app.planner.nodes.constraint_guard")
    route = AsyncMock(return_value=[])
    monkeypatch.setattr(cg, "check_route_constraint", route)
    await validate_plan.coroutine(
        destination="Paris",
        origin="New York",
        start_date="2026-09-01",
        end_date="2026-09-05",
        budget=5000,
        skip_route_check=False,
    )
    route.assert_awaited_once()


# --- _patch_changed_fields -> fields_changed merge (PATCH-driven date change) ---


def _patch_state():
    """Final state for a PATCH-driven GENERATE_PLAN_NOW turn: dates set via the
    Dates sheet (not chat text), strategy ready, nothing built, and the agent
    extracted no field diff (empty tools_called / fields_changed)."""
    return {
        "trip_plan": dict(_CORE),
        "strategy_sections": [{"specialist_type": "diving"}],
        "day_cards": [],
        "tiles": {},
        "turn_meta": {"tools_called": [], "fields_changed": []},
    }


def test_merge_patch_fields_enables_both_gates() -> None:
    # PATCH-only date change: gates must be inert BEFORE the merge ...
    state = _patch_state()
    assert _should_autobuild(state) is False
    assert _should_autovalidate(state, built_this_turn=False) is False

    # ... and fire AFTER folding _patch_changed_fields into fields_changed.
    _merge_patch_changed_fields(state, ["start_date", "end_date"])
    assert set(state["turn_meta"]["fields_changed"]) == {"start_date", "end_date"}
    assert _should_autobuild(state) is True
    assert _should_autovalidate(state, built_this_turn=False) is True


def test_merge_patch_fields_dedups_with_existing() -> None:
    state = _patch_state()
    state["turn_meta"]["fields_changed"] = ["start_date", "budget"]
    _merge_patch_changed_fields(state, ["start_date", "end_date"])
    assert state["turn_meta"]["fields_changed"] == ["budget", "end_date", "start_date"]


def test_merge_patch_fields_creates_turn_meta_when_absent() -> None:
    state = {"trip_plan": dict(_CORE)}
    _merge_patch_changed_fields(state, ["start_date"])
    assert state["turn_meta"]["fields_changed"] == ["start_date"]


def test_merge_patch_fields_noop_on_empty_or_bad_input() -> None:
    state = _patch_state()
    _merge_patch_changed_fields(state, None)
    _merge_patch_changed_fields(state, [])
    assert state["turn_meta"]["fields_changed"] == []
    # Gates stay inert when there is nothing to merge.
    assert _should_autobuild(state) is False
