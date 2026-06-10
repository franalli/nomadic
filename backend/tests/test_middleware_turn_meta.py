"""
Unit tests for the create_agent middleware turn_meta contract.

Covers the bug-prone reducer/delta interaction (no live LLM):
  - tools_called concatenation produces the right list + derived count
  - turn_steps / partial_failures accumulate across parallel tool calls
  - extract merge produces fields_changed / origin_just_set field-producers
  - tiles / validation mergers produce their envelope field-producers
"""

from __future__ import annotations

from app.planner.middleware import (
    TurnLifecycleMiddleware,
    _merge_tiles,
    _merge_trip_fields,
    _merge_validation,
)
from app.planner.state.agent_state import _merge_dicts, _merge_turn_meta


class TestTurnMetaReducer:
    def test_tools_called_concatenates_no_duplication(self):
        # Each producer returns a single-element delta; the reducer concatenates.
        a = _merge_turn_meta({"tools_called": []}, {"tools_called": ["extract_trip_fields"]})
        b = _merge_turn_meta(a, {"tools_called": ["search_tiles"]})
        assert b["tools_called"] == ["extract_trip_fields", "search_tiles"]
        assert b["tool_call_count"] == 2

    def test_parallel_deltas_accumulate_not_clobber(self):
        # Two parallel tool deltas merged into the same prior state.
        base = {
            "tools_called": ["extract_trip_fields"],
            "turn_steps": [{"node": "extract_trip_fields"}],
        }
        left = _merge_turn_meta(
            base, {"tools_called": ["search_tiles"], "turn_steps": [{"node": "search_tiles"}]}
        )
        both = _merge_turn_meta(
            left,
            {"tools_called": ["get_local_intel"], "turn_steps": [{"node": "get_local_intel"}]},
        )
        assert both["tools_called"] == ["extract_trip_fields", "search_tiles", "get_local_intel"]
        assert [s["node"] for s in both["turn_steps"]] == [
            "extract_trip_fields",
            "search_tiles",
            "get_local_intel",
        ]
        assert both["tool_call_count"] == 3

    def test_partial_failures_concatenate(self):
        merged = _merge_turn_meta(
            {"partial_failures": [{"tool": "search_tiles", "error": "timeout"}]},
            {"partial_failures": [{"tool": "build_itinerary", "error": "boom"}]},
        )
        assert len(merged["partial_failures"]) == 2

    def test_model_turns_right_wins_increment(self):
        # abefore_model returns the incremented value; reducer right-wins.
        s = _merge_turn_meta({"model_turns": 0}, {"model_turns": 1})
        s = _merge_turn_meta(s, {"model_turns": 2})
        assert s["model_turns"] == 2

    def test_scalar_keys_right_win(self):
        merged = _merge_turn_meta(
            {"validation_result": {"valid": True}},
            {"validation_result": {"valid": False}},
        )
        assert merged["validation_result"] == {"valid": False}


class TestExtractFieldProducers:
    def test_fields_changed_and_origin_just_set(self):
        state = {"trip_plan": {"destination": "Bali"}, "trip_settings": {}}
        result = {
            "fields_changed": ["origin", "start_date"],
            "origin": "London",
            "start_date": "2026-07-01",
        }
        updates = _merge_trip_fields(state, result)
        tm = updates["turn_meta"]
        assert tm["fields_changed"] == ["origin", "start_date"]
        assert tm["origin_just_set"] is True
        # Delta must NOT carry tools_called (would re-concatenate via reducer).
        assert "tools_called" not in tm

    def test_origin_not_just_set_when_already_present(self):
        state = {"trip_plan": {"destination": "Bali", "origin": "Paris"}, "trip_settings": {}}
        result = {"fields_changed": ["origin"], "origin": "London"}
        updates = _merge_trip_fields(state, result)
        assert updates["turn_meta"]["origin_just_set"] is False


class TestTilesAndValidationProducers:
    def test_tiles_replaced_tracked(self):
        state = {"tiles": {}}
        result = {
            "hotels": [{"id": "h1"}],
            "activities": [{"id": "a1"}],
            "browseable_activities": [{"id": "b1"}],
        }
        updates = _merge_tiles(state, result)
        assert set(updates["turn_meta"]["tiles_replaced"]) == {"hotels", "activities"}
        assert updates["turn_meta"]["browseable_activities"] == [{"id": "b1"}]

    def test_validation_producers(self):
        state = {"turn_meta": {"tools_called": ["validate_plan"]}}
        result = {"valid": False, "violations": [{"code": "BUDGET_TOO_LOW"}], "blocking_count": 1}
        updates = _merge_validation(state, result)
        tm = updates["turn_meta"]
        assert tm["has_blocking_violations"] is True
        assert tm["constraint_violations"] == [{"code": "BUDGET_TOO_LOW"}]
        # Delta only -- must not copy the prior tools_called.
        assert "tools_called" not in tm


class TestResetIntent:
    """Two-step RESET confirm flow.

    First RESET turn arms persistent_meta.reset_pending + turn_meta.reset_pending
    and skips ALL trip-field merges. TurnLifecycleMiddleware.abefore_agent then
    carries the marker into the NEXT turn's fresh turn_meta as
    reset_pending_carryover and clears the persistent marker in the same update,
    so the marker lives EXACTLY one turn. A RESET turn WITH the carryover flags
    turn_meta.coordinator_reset (consumed by _build_envelope / the SSE persist
    wipe); any non-RESET turn abandons the confirmation automatically (the
    marker is already cleared, nothing re-arms).
    """

    def test_reset_intent_arms_marker_and_skips_merge(self):
        state = {
            "trip_plan": {"destination": "Bali", "start_date": "2026-07-01"},
            "trip_settings": {},
            "persistent_meta": {},
            "turn_meta": {},
        }
        result = {
            "intent": "RESET",
            "destination": "Tokyo",
            "fields_changed": ["destination"],
        }
        updates = _merge_trip_fields(state, result)
        assert updates["persistent_meta"] == {"reset_pending": True}
        assert updates["turn_meta"] == {"reset_pending": True}
        # A reset request must not mutate the plan -- co-extracted fields skipped.
        assert "trip_plan" not in updates
        assert "trip_settings" not in updates

    def test_carryover_reset_flags_coordinator_reset(self):
        state = {
            "trip_plan": {"destination": "Bali"},
            "trip_settings": {},
            "persistent_meta": {"reset_pending": False},  # cleared by abefore_agent
            "turn_meta": {"reset_pending_carryover": True},
        }
        updates = _merge_trip_fields(state, {"intent": "RESET"})
        assert updates["turn_meta"] == {"coordinator_reset": True}
        assert "trip_plan" not in updates
        # abefore_agent owns the marker clear; the merger must not re-touch it.
        assert "persistent_meta" not in updates

    def test_persistent_marker_alone_does_not_confirm(self):
        # A same-turn double extract (or any stale marker that abefore_agent has
        # not carried over) must RE-ARM, never self-confirm: only the one-turn
        # carryover flag authorizes the wipe.
        state = {
            "trip_plan": {"destination": "Bali"},
            "trip_settings": {},
            "persistent_meta": {"reset_pending": True},
            "turn_meta": {},
        }
        updates = _merge_trip_fields(state, {"intent": "RESET"})
        assert updates["turn_meta"] == {"reset_pending": True}
        assert updates["persistent_meta"] == {"reset_pending": True}

    def test_carryover_non_reset_abandons_and_still_merges(self):
        state = {
            "trip_plan": {"destination": "Bali"},
            "trip_settings": {},
            "persistent_meta": {"reset_pending": False},  # cleared by abefore_agent
            "turn_meta": {"reset_pending_carryover": True},
        }
        result = {"intent": "PLANNING", "fields_changed": ["budget"], "budget": 2000.0}
        updates = _merge_trip_fields(state, result)
        # Nothing re-arms and nothing wipes -- the pending confirm is abandoned.
        assert "persistent_meta" not in updates
        assert not updates["turn_meta"].get("reset_pending")
        assert not updates["turn_meta"].get("coordinator_reset")
        assert updates["trip_plan"]["budget"] == 2000.0

    def test_planning_without_marker_leaves_persistent_meta_untouched(self):
        state = {"trip_plan": {}, "trip_settings": {}, "persistent_meta": {}, "turn_meta": {}}
        updates = _merge_trip_fields(state, {"intent": "PLANNING", "fields_changed": []})
        assert "persistent_meta" not in updates


class TestResetMarkerLifecycle:
    """abefore_agent owns the reset marker: carried over + cleared in ONE turn.

    Covers the strand cases: extract_trip_fields erroring on the confirm turn,
    or a turn where the model never calls extract_trip_fields at all -- in both
    cases the marker is consumed at turn start, so a much later unrelated
    "reset" can never wipe without a fresh confirmation.
    """

    async def test_abefore_agent_carries_over_and_clears_marker(self):
        state = {"persistent_meta": {"reset_pending": True, "plan_view_state": "S2_STRATEGY"}}
        updates = await TurnLifecycleMiddleware().abefore_agent(state, None)
        assert updates["turn_meta"]["reset_pending_carryover"] is True
        assert updates["persistent_meta"] == {"reset_pending": False}
        # The right-wins _merge_dicts reducer must actually deliver the clear
        # without dropping sibling persistent_meta keys.
        merged = _merge_dicts(state["persistent_meta"], updates["persistent_meta"])
        assert merged["reset_pending"] is False
        assert merged["plan_view_state"] == "S2_STRATEGY"

    async def test_abefore_agent_without_marker_is_inert(self):
        updates = await TurnLifecycleMiddleware().abefore_agent(
            {"persistent_meta": {"plan_view_state": "S3_ITINERARY"}}, None
        )
        assert "persistent_meta" not in updates
        assert "reset_pending_carryover" not in updates["turn_meta"]
        # Standard turn_meta reset still happens.
        assert updates["turn_meta"]["tools_called"] == []

    async def test_marker_cleared_even_when_extract_never_runs(self):
        # Turn N: marker armed. Turn N+1: abefore_agent consumes it; NO merger
        # runs (model never called extract_trip_fields). Turn N+2 must see no
        # marker and no carryover.
        state = {"persistent_meta": {"reset_pending": True}}
        updates = await TurnLifecycleMiddleware().abefore_agent(state, None)
        state["persistent_meta"] = _merge_dicts(
            state["persistent_meta"], updates["persistent_meta"]
        )
        # Turn N+2
        updates2 = await TurnLifecycleMiddleware().abefore_agent(state, None)
        assert "persistent_meta" not in updates2
        assert "reset_pending_carryover" not in updates2["turn_meta"]

    async def test_arm_then_serde_round_trip_then_carryover(self):
        from app.planner.services.state_serde import (
            restore_agent_state,
            serialize_agent_state,
        )

        # Turn N: extract arms the marker.
        state = {
            "trip_plan": {"destination": "Bali"},
            "trip_settings": {},
            "persistent_meta": {},
            "turn_meta": {},
        }
        arm = _merge_trip_fields(state, {"intent": "RESET"})
        state["persistent_meta"] = _merge_dicts(state["persistent_meta"], arm["persistent_meta"])

        # Persist + restore across the turn boundary (the marker must survive).
        serialized = serialize_agent_state({"messages": [], **state})
        restored = restore_agent_state(serialized)
        assert restored["persistent_meta"].get("reset_pending") is True

        # Turn N+1: abefore_agent produces the carryover and clears the marker.
        updates = await TurnLifecycleMiddleware().abefore_agent(restored, None)
        assert updates["turn_meta"]["reset_pending_carryover"] is True
        restored["persistent_meta"] = _merge_dicts(
            restored["persistent_meta"], updates["persistent_meta"]
        )

        # The cleared marker round-trips as falsy: no carryover on turn N+2.
        serialized2 = serialize_agent_state({"messages": [], **restored})
        restored2 = restore_agent_state(serialized2)
        assert not restored2["persistent_meta"].get("reset_pending")
        updates2 = await TurnLifecycleMiddleware().abefore_agent(restored2, None)
        assert "persistent_meta" not in updates2
        assert "reset_pending_carryover" not in updates2["turn_meta"]
