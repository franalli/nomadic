"""Regression tests for the "sub-locality read as a new destination" bug.

A question naming a sub-locality of the current destination -- e.g.
"how would I get from the airport to Canggu?" on an existing Bali trip -- must
NOT be treated as a destination change. The router intermittently extracts the
named place as a brand-new ``destination``; ``_merge_trip_fields`` would then
treat that as a destination change and wipe the entire plan (strategy_sections /
tiles / day_cards / constraints), and the cleared day_cards re-arm the post-loop
auto-build -- so a pure question silently regenerated the whole trip and dropped
the active specialist.

``extract_trip_fields`` suppresses the extracted destination when the router
classified the turn as a question (``question_type`` set) on an already-set trip.
A genuine destination swap ("change to Tokyo") never carries a ``question_type``
(the taxonomy has no "change destination" topic), so it is unaffected.

The inner ``_classify_and_extract_with_llm`` is mocked so the tests are offline
and deterministic. The tool reads InjectedState directly, so we invoke the raw
``.coroutine`` (``.ainvoke`` strips injected args).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.planner.nodes.router_extraction import RouterOutput
from app.planner.tools.extract_trip_fields import extract_trip_fields

# A committed trip (destination + dates set) -- the precondition for the lock.
# Shared read-only fixture; no test mutates it.
COMMITTED_BALI_STATE = {
    "trip_plan": {
        "destination": "Bali",
        "start_date": "2026-06-08",
        "end_date": "2026-06-17",
    }
}


async def _run(mock_output: RouterOutput, state: dict) -> dict:
    with patch(
        "app.planner.nodes.router_extraction._classify_and_extract_with_llm",
        new=AsyncMock(return_value=(mock_output, {})),
    ):
        return await extract_trip_fields.coroutine(
            user_message="(ignored -- _classify_and_extract_with_llm is mocked)",
            state=state,
        )


async def test_transport_question_about_sublocality_does_not_change_destination() -> None:
    """THE BUG: 'how would I get from the airport to Canggu?' on a Bali trip.

    Router mis-reads Canggu (a town in Bali) as a destination but DOES set
    question_type=transport -> destination must be suppressed so the plan is not
    wiped.
    """
    mock_output = RouterOutput(
        intent="PLANNING",
        confidence=0.9,
        reasoning="transport question",
        destination="Canggu",
        question_type="transport",
        planning_intent="exploring",
    )
    result = await _run(mock_output, COMMITTED_BALI_STATE)
    assert result["destination"] is None
    assert "destination" not in result["fields_changed"]


async def test_accommodation_question_about_sublocality_suppressed() -> None:
    """A 'where should I stay in Seminyak?' style question is also a sub-locality
    mention (question_type=accommodation), not a destination change."""
    mock_output = RouterOutput(
        intent="PLANNING",
        confidence=0.9,
        reasoning="accommodation question",
        destination="Seminyak",
        question_type="accommodation",
        planning_intent="exploring",
    )
    result = await _run(mock_output, COMMITTED_BALI_STATE)
    assert result["destination"] is None
    assert "destination" not in result["fields_changed"]
    # A question is suppressed SILENTLY -- not flagged as a switch request.
    assert result["destination_switch_blocked"] is None


async def test_exploring_intent_without_question_type_also_suppressed() -> None:
    """GAP CLOSURE: the router sometimes mis-extracts the sub-locality as a
    destination WITHOUT setting question_type, but still tags the turn
    planning_intent='exploring' ('asking questions without committing'). The second
    independent signal must also suppress, so the backstop does not depend on a
    single LLM field landing."""
    mock_output = RouterOutput(
        intent="PLANNING",
        confidence=0.9,
        reasoning="asking about getting around",
        destination="Canggu",
        question_type=None,
        planning_intent="exploring",
    )
    result = await _run(mock_output, COMMITTED_BALI_STATE)
    assert result["destination"] is None
    assert "destination" not in result["fields_changed"]


async def test_genuine_switch_on_committed_trip_is_blocked_and_flags_reset() -> None:
    """A real swap ('change to Tokyo') on a committed trip is REJECTED: the
    destination is locked to the current itinerary, so it is not applied -- and the
    requested destination is recorded so the terminal model advises Reset."""
    mock_output = RouterOutput(
        intent="PLANNING",
        confidence=0.9,
        reasoning="destination change",
        destination="Tokyo",
        question_type=None,
        planning_intent="modifying",
    )
    result = await _run(mock_output, COMMITTED_BALI_STATE)
    # Switch NOT applied -- trip stays on the current destination.
    assert result["destination"] is None
    assert "destination" not in result["fields_changed"]
    # Requested destination recorded so build_turn_context can advise Reset.
    assert result["destination_switch_blocked"] == "Tokyo"


async def test_blocked_switch_rejects_bundled_fields() -> None:
    """A switch bundled with dates/budget ("change to Tokyo, July 10-15, $6000") must
    reject the WHOLE pivot -- not just the destination. Otherwise the locked trip's
    dates/budget get silently mutated (and the stray dates re-arm the auto-build)."""
    mock_output = RouterOutput(
        intent="PLANNING",
        confidence=0.9,
        reasoning="switch with bundled dates + budget",
        destination="Tokyo",
        start_date="2026-07-10",
        end_date="2026-07-15",
        budget=6000,
        activity_categories=["hiking"],
        planning_intent="modifying",
        question_type=None,
    )
    result = await _run(mock_output, COMMITTED_BALI_STATE)
    assert result["destination"] is None
    assert result["destination_switch_blocked"] == "Tokyo"
    # NONE of the bundled fields leak onto the locked trip.
    assert result["start_date"] is None
    assert result["end_date"] is None
    assert result["budget"] is None
    assert result["activity_categories"] == []
    assert result["fields_changed"] == []


async def test_question_about_other_place_does_not_change_current_dates() -> None:
    """A question naming another place ("weather in Tokyo July 10-15?") must not
    reset the current trip's dates, but is suppressed silently (not a switch)."""
    mock_output = RouterOutput(
        intent="PLANNING",
        confidence=0.9,
        reasoning="weather question naming dates",
        destination="Tokyo",
        start_date="2026-07-10",
        end_date="2026-07-15",
        question_type="weather",
        planning_intent="exploring",
    )
    result = await _run(mock_output, COMMITTED_BALI_STATE)
    assert result["destination"] is None
    assert result["start_date"] is None
    assert result["end_date"] is None
    assert "start_date" not in result["fields_changed"]
    assert "end_date" not in result["fields_changed"]
    # A question is not a switch -> no Reset advice.
    assert result["destination_switch_blocked"] is None


async def test_sublocality_question_keeps_legit_activity_add() -> None:
    """ "How do I get to Canggu, and add diving?" -- the diving add is a genuine
    current-trip refinement and must survive even though Canggu (the destination) is
    dropped."""
    mock_output = RouterOutput(
        intent="PLANNING",
        confidence=0.9,
        reasoning="sub-locality question + activity add",
        destination="Canggu",
        activity_categories=["diving"],
        question_type="transport",
        planning_intent="exploring",
    )
    result = await _run(mock_output, COMMITTED_BALI_STATE)
    assert result["destination"] is None
    assert "diving" in result["activity_categories"]
    assert "activity_categories" in result["fields_changed"]
    assert result["destination_switch_blocked"] is None


async def test_first_destination_set_unaffected() -> None:
    """No existing destination -> backstop never fires, first-time set works even
    when the router (oddly) also tagged a question_type."""
    mock_output = RouterOutput(
        intent="PLANNING",
        confidence=0.9,
        reasoning="first plan",
        destination="Lisbon",
        question_type="transport",
    )
    result = await _run(mock_output, {"trip_plan": {}})
    assert result["destination"] == "Lisbon"
    assert "destination" in result["fields_changed"]


async def test_same_destination_question_is_noop() -> None:
    """A question that re-names the SAME current destination is not a change and is
    left alone (no spurious suppression log, destination simply not flagged)."""
    mock_output = RouterOutput(
        intent="PLANNING",
        confidence=0.9,
        reasoning="weather question about current trip",
        destination="Bali",
        question_type="weather",
        planning_intent="exploring",
    )
    result = await _run(mock_output, COMMITTED_BALI_STATE)
    # destination unchanged vs current -> not flagged; value may stay "Bali".
    assert "destination" not in result["fields_changed"]
