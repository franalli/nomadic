"""Unit tests for routing functions in plan_graph.py.

Pure state-based tests: construct GraphState with the right fields, assert the
return string. No mocks, no DB, no LLM.
"""

from app.plan_graph import (
    _should_run_guard,
    route_after_architect,
    route_after_guard,
    route_after_logistics,
    route_after_router,
    route_after_specialist,
)
from app.planner.state import GraphState


def _state(
    destination: str = "",
    origin: str = "",
    start_date: str = "",
    intent: str | None = None,
    active_specialist: str | None = None,
    pending_specialists: list[str] | None = None,
    tiles: dict | None = None,
    guard_retry_count: int = 0,
    **meta_overrides,
) -> GraphState:
    """Build minimal GraphState for routing tests."""
    s = GraphState()
    if destination:
        s.trip_plan.destination = destination
    if origin:
        s.trip_plan.origin = origin
    if start_date:
        s.trip_plan.start_date = start_date
    if intent is not None:
        s.intent = intent
    if active_specialist is not None:
        s.active_specialist = active_specialist
    if pending_specialists is not None:
        s.pending_specialists = pending_specialists
    if tiles is not None:
        s.tiles = tiles
    s.guard_retry_count = guard_retry_count
    for k, v in meta_overrides.items():
        s.metadata[k] = v
    return s


# =============================================================================
# route_after_router
# =============================================================================


class TestRouteAfterRouter:
    def test_origin_only_logistics(self):
        s = _state(origin="London", origin_only_logistics=True)
        assert route_after_router(s) == "logistics"

    def test_short_circuit_response(self):
        s = _state(short_circuit_response=True)
        assert route_after_router(s) == "synthesizer"

    def test_specialist_queued_no_destination(self):
        s = _state(active_specialist="diving")
        assert route_after_router(s) == "architect"

    def test_specialist_queued_with_destination(self):
        s = _state(destination="Bali", active_specialist="diving")
        assert route_after_router(s) == "specialist"

    def test_local_expert_with_destination(self):
        s = _state(destination="Bali", active_specialist="local_expert")
        assert route_after_router(s) == "local_expert"

    def test_default_to_architect(self):
        s = _state()
        assert route_after_router(s) == "architect"


# =============================================================================
# route_after_specialist
# =============================================================================


class TestRouteAfterSpecialist:
    def test_pending_specialist_next(self):
        s = _state(pending_specialists=["hiking"])
        assert route_after_specialist(s) == "specialist"

    def test_pending_local_expert_next(self):
        s = _state(pending_specialists=["local_expert"])
        assert route_after_specialist(s) == "local_expert"

    def test_speculative_to_synthesizer(self):
        s = _state(intent="speculative")
        assert route_after_specialist(s) == "synthesizer"

    def test_booking_intent_with_destination_to_logistics(self):
        s = _state(destination="Bali", intent="booking")
        assert route_after_specialist(s) == "logistics"

    def test_dates_and_destination_to_logistics(self):
        s = _state(destination="Bali", start_date="2026-03-15")
        assert route_after_specialist(s) == "logistics"

    def test_architect_already_ran_to_guard(self):
        s = _state(destination="Bali", architect_ran_this_turn=True)
        assert route_after_specialist(s) == "guard"

    def test_default_to_architect(self):
        s = _state()
        assert route_after_specialist(s) == "architect"


# =============================================================================
# route_after_architect
# =============================================================================


class TestRouteAfterArchitect:
    def test_deferred_specialist_dispatch(self):
        s = _state(destination="Bali", active_specialist="diving")
        assert route_after_architect(s) == "specialist"

    def test_deferred_local_expert_dispatch(self):
        s = _state(destination="Bali", active_specialist="local_expert")
        assert route_after_architect(s) == "local_expert"

    def test_local_expert_fallback(self):
        """General intent + destination + local_expert hasn't run → local_expert."""
        s = _state(destination="Bali", intent="general")
        assert route_after_architect(s) == "local_expert"

    def test_local_expert_already_ran_skips(self):
        """If local_expert already ran, don't route there again."""
        s = _state(destination="Bali", intent="general", local_expert_ran=True)
        assert route_after_architect(s) != "local_expert"

    def test_dates_no_tiles_to_logistics(self):
        s = _state(destination="Bali", start_date="2026-03-15", local_expert_ran=True)
        assert route_after_architect(s) == "logistics"

    def test_logistics_already_attempted_skips(self):
        """If logistics already ran this turn, don't loop back."""
        s = _state(
            destination="Bali",
            start_date="2026-03-15",
            local_expert_ran=True,
            logistics_attempted=True,
        )
        assert route_after_architect(s) != "logistics"

    def test_fallthrough_with_destination_to_guard(self):
        s = _state(
            destination="Bali",
            local_expert_ran=True,
            logistics_attempted=True,
        )
        assert route_after_architect(s) == "guard"


# =============================================================================
# route_after_logistics
# =============================================================================


class TestRouteAfterLogistics:
    def test_architect_already_ran_to_guard(self):
        s = _state(destination="Bali", architect_ran_this_turn=True)
        assert route_after_logistics(s) == "guard"

    def test_default_to_architect(self):
        s = _state()
        assert route_after_logistics(s) == "architect"


# =============================================================================
# route_after_guard
# =============================================================================


class TestRouteAfterGuard:
    def test_unfixable_route_violation_to_synthesizer(self):
        s = _state(
            has_blocking_violations=True,
            constraint_violations=[{"category": "route", "message": "same city"}],
        )
        assert route_after_guard(s) == "synthesizer"

    def test_unfixable_specialist_violation_to_synthesizer(self):
        s = _state(
            has_blocking_violations=True,
            constraint_violations=[{"category": "specialist", "message": "buffer"}],
        )
        assert route_after_guard(s) == "synthesizer"

    def test_fixable_blocking_to_synthesizer(self):
        s = _state(
            has_blocking_violations=True,
            constraint_violations=[{"category": "budget", "message": "over budget"}],
            guard_retry_count=0,
        )
        assert route_after_guard(s) == "synthesizer"

    def test_fixable_blocking_exhausted_retries(self):
        s = _state(
            has_blocking_violations=True,
            constraint_violations=[{"category": "budget", "message": "over budget"}],
            guard_retry_count=1,
        )
        assert route_after_guard(s) == "synthesizer"

    def test_no_blocking_to_synthesizer(self):
        s = _state()
        assert route_after_guard(s) == "synthesizer"


# =============================================================================
# _should_run_guard
# =============================================================================


class TestShouldRunGuard:
    def test_destination_set_runs_guard(self):
        s = _state(destination="Bali")
        assert _should_run_guard(s) == "guard"

    def test_tiles_present_runs_guard(self):
        s = _state(tiles={"flights": [{"price": 500}]})
        assert _should_run_guard(s) == "guard"

    def test_nothing_to_synthesizer(self):
        s = _state()
        assert _should_run_guard(s) == "synthesizer"
