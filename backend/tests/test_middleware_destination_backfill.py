"""Regression tests for trip_plan.destination backfill from tool-call args.

The bug (confirmed against a live session, session_id=4174): a conversational
turn like "is bali fun?" -> "what are the best beaches?" never triggers
``extract_trip_fields`` (no explicit planning intent), so the router never writes
``trip_plan.destination``. But those turns DO call destination-scoped tools
(``get_local_intel`` / ``search_tiles`` / ``get_specialist_advice``) with the
model-supplied ``destination="Bali"``, and the system builds a full 11-day Bali
itinerary. The resolved "Bali" lives only in the ephemeral tool args, so the
persisted ``trip_inputs.destination`` stays ``None``. The frontend's
``hasPlanPrerequisites`` gate (destination + dates) then forces ``planViewState``
to ``null`` and the itinerary never renders -- "itinerary does not load".

The fix backfills ``trip_plan.destination`` from a destination-scoped tool's
``args`` in ``TurnLifecycleMiddleware.awrap_tool_call`` -- but ONLY when the SSoT
destination is still empty (never override an explicit router set), and folded
into any ``trip_plan`` delta the tool's own merger already produced (so we don't
clobber sibling keys like specialist_hints in the same round).
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.planner.middleware import TurnLifecycleMiddleware


def _request(tool_name: str, args: dict[str, Any], state: dict[str, Any]):
    """Build a minimal ToolCallRequest-like object.

    awrap_tool_call only reads ``request.tool_call`` (name/args/id) and
    ``request.state``; runtime is unused, so a lightweight stand-in is enough and
    avoids constructing a real ToolRuntime.
    """

    class _Req:
        tool_call = {"name": tool_name, "args": args, "id": "call_test_1"}

    req = _Req()
    req.state = state
    return req


def _handler_for(result_payload: dict[str, Any]):
    async def handler(request):
        return ToolMessage(
            content=json.dumps(result_payload),
            tool_call_id=request.tool_call["id"],
            name=request.tool_call["name"],
        )

    return handler


async def _run(tool_name, args, state, result_payload):
    mw = TurnLifecycleMiddleware()
    req = _request(tool_name, args, state)
    out = await mw.awrap_tool_call(req, _handler_for(result_payload))
    assert isinstance(out, Command)
    return out.update


async def test_backfills_destination_from_local_intel_args_when_empty() -> None:
    """THE BUG: get_local_intel("Bali") on a conversational turn, trip_plan has no
    destination -> backfill "Bali" so the SSoT (and frontend gate) sees it."""
    update = await _run(
        "get_local_intel",
        {"destination": "Bali"},
        {"trip_plan": {}},
        {"summary": "Bali local intel", "constraints": []},
    )
    assert update["trip_plan"]["destination"] == "Bali"


async def test_backfills_destination_from_search_tiles_args() -> None:
    """search_tiles is also destination-scoped: it commits the trip to a place."""
    update = await _run(
        "search_tiles",
        {"destination": "Lisbon"},
        {"trip_plan": {}, "tiles": {}},
        {"hotels": [], "activities": [], "summary": "ok"},
    )
    assert update["trip_plan"]["destination"] == "Lisbon"


async def test_does_not_override_existing_destination() -> None:
    """GUARD: an explicit router-set destination must win -- the tool arg never
    overwrites it (e.g. a stale arg or a comparison query)."""
    update = await _run(
        "search_tiles",
        {"destination": "Bali"},
        {"trip_plan": {"destination": "Rome"}, "tiles": {}},
        {"hotels": [], "activities": [], "summary": "ok"},
    )
    # No destination write occurred (merger emits no trip_plan; backfill skipped).
    assert update.get("trip_plan", {}).get("destination") != "Bali"


async def test_folds_into_specialist_trip_plan_delta_without_clobber() -> None:
    """NO CLOBBER: get_specialist_advice's merger returns a trip_plan delta
    (specialist_hints / activity_categories). The destination backfill must be
    folded INTO that same delta -- preserving the sibling keys, not replacing
    them with a destination-only dict."""
    update = await _run(
        "get_specialist_advice",
        {"destination": "Bali", "topic": "diving"},
        {"trip_plan": {}},
        {
            "strategy_section": {"specialist_type": "diving", "feasibility_status": "feasible"},
            "topic": "diving",
            "constraints": [],
        },
    )
    tp = update["trip_plan"]
    assert tp["destination"] == "Bali"
    # Sibling keys produced by _merge_specialist survive.
    assert "diving" in tp["specialist_hints"]
    assert "diving" in tp["activity_categories"]


async def test_non_destination_scoped_tool_does_not_backfill() -> None:
    """validate_plan is not destination-scoped: even a destination-looking arg
    must not commit the trip to a destination."""
    update = await _run(
        "validate_plan",
        {"destination": "Bali"},
        {"trip_plan": {}},
        {"valid": True, "violations": [], "blocking_count": 0},
    )
    assert update.get("trip_plan", {}).get("destination") != "Bali"


async def test_blank_destination_arg_is_ignored() -> None:
    """A whitespace/empty destination arg must not write an empty destination."""
    update = await _run(
        "search_tiles",
        {"destination": "   "},
        {"trip_plan": {}, "tiles": {}},
        {"hotels": [], "activities": [], "summary": "ok"},
    )
    assert "destination" not in update.get("trip_plan", {})
