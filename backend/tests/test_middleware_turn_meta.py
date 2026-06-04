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
    _merge_tiles,
    _merge_trip_fields,
    _merge_validation,
)
from app.planner.state.agent_state import _merge_turn_meta


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
