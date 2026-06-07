"""Tests for the "remove all activities" intent.

Covers all four implementation parts:
  A. Router/plumbing: remove_all_activities flows RouterOutput -> TripFieldsResult
     -> fields_changed -> turn_meta.
  B. Post-loop enforcement: _apply_remove_all_activities empties activities while
     preserving hotels/flights/buffers/free-days; signals a replace.
  C. (Prompt directive is exercised indirectly via build_turn_context.)
  D. Un-stick: a later activity request re-enables booking_types.activities.

Plus composition order and the no-op guardrail.
"""

from __future__ import annotations

from typing import Any, Dict

from app.planner.middleware import _merge_specialist, _merge_trip_fields
from app.planner.prompts.planner import build_turn_context
from app.planner.services.agent_runner import (
    _apply_remove_all_activities,
    _reenable_activities_if_requested,
)
from app.planner.tools.extract_trip_fields import (
    TripFieldsResult,
    _detect_changed_fields,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _activity_block(bid: str, atype: str = "diving") -> Dict[str, Any]:
    return {
        "id": bid,
        "period": "morning",
        "activity_type": atype,
        "summary": f"{atype} excursion",
        "is_buffer": False,
        "specialist_type": atype,
        "booking_category": "activity",
    }


def _arrival_block() -> Dict[str, Any]:
    return {
        "id": "arrival_1",
        "period": "morning",
        "activity_type": "arrival",
        "summary": "Arrive in Bali",
        "is_buffer": True,
        "buffer_type": "arrival",
    }


def _hotel_block() -> Dict[str, Any]:
    return {
        "id": "hotel_1",
        "period": "evening",
        "activity_type": "check_in",
        "summary": "Check in to hotel",
        "is_buffer": False,
        "booking_category": "hotel",
        "hotel_name": "Beach Resort",
    }


def _flight_block() -> Dict[str, Any]:
    return {
        "id": "flight_1",
        "period": "morning",
        "activity_type": "departure",
        "summary": "Flight home",
        "is_buffer": True,
        "buffer_type": "departure",
        "booking_category": "flight",
    }


def _base_state_with_activities(remove_all: bool = True) -> Dict[str, Any]:
    return {
        "trip_plan": {
            "destination": "Bali",
            "start_date": "2026-07-01",
            "end_date": "2026-07-05",
            "activity_categories": ["diving", "cultural"],
            "specialist_hints": ["diving"],
        },
        "trip_settings": {
            "booking_types": {"hotels": "suggested", "flights": "suggested"},
            "activity_settings": {"categories": ["diving", "cultural"]},
        },
        "tiles": {
            "hotels": [{"id": "h1", "type": "hotel", "title": "Beach Resort"}],
            "flights": [{"id": "f1", "type": "flight", "title": "Flight"}],
            "activities": [
                {"id": "a1", "type": "activity", "title": "Dive Site"},
                {"id": "a2", "type": "activity", "title": "Temple Tour"},
            ],
        },
        "strategy_sections": [
            {"specialist_type": "diving", "subtitle": "Bali", "title": "Diving"},
            {"specialist_type": "local_expert", "subtitle": "Bali", "title": "Local Intel"},
        ],
        "specialist_plans": {"diving": {"foo": "bar"}},
        "day_cards": [
            {
                "day_number": 1,
                "label": "Arrival Day",
                "blocks": [_arrival_block(), _hotel_block(), _activity_block("b1", "diving")],
            },
            {
                "day_number": 2,
                "label": "Diving Day",
                "blocks": [
                    _activity_block("b2", "diving"),
                    _activity_block("b3", "cultural"),
                ],
            },
            {
                "day_number": 3,
                "label": "Departure Day",
                "blocks": [_flight_block()],
            },
        ],
        "persistent_meta": {"browseable_activities": [{"id": "ba1", "title": "Snorkel"}]},
        "turn_meta": {"remove_all_activities": remove_all},
    }


# ---------------------------------------------------------------------------
# PART A -- Router / plumbing
# ---------------------------------------------------------------------------


def test_plumbing_remove_all_registers_as_change() -> None:
    """remove_all_activities=True must appear in fields_changed."""
    result = TripFieldsResult(remove_all_activities=True)
    changed = _detect_changed_fields(
        result,
        current_destination="Bali",
        current_origin="",
        current_start_date="2026-07-01",
        current_end_date="2026-07-05",
        current_adults=1,
        current_children=0,
        current_budget=0,
        current_categories="diving,cultural",
    )
    assert "remove_all_activities" in changed


def test_plumbing_specific_removal_does_not_set_global_flag() -> None:
    """A specific-topic removal must NOT set remove_all_activities."""
    result = TripFieldsResult(removal_targets=["hiking"], remove_all_activities=False)
    changed = _detect_changed_fields(
        result,
        current_destination="Bali",
        current_origin="",
        current_start_date="",
        current_end_date="",
        current_adults=1,
        current_children=0,
        current_budget=0,
        current_categories="hiking,diving",
    )
    assert "removal_targets" in changed
    assert "remove_all_activities" not in changed


def test_plumbing_flag_flows_to_turn_meta() -> None:
    """_merge_trip_fields surfaces remove_all_activities in the turn_meta delta."""
    state = {"trip_plan": {"destination": "Bali"}, "trip_settings": {}}
    result = TripFieldsResult(
        remove_all_activities=True, fields_changed=["remove_all_activities"]
    ).model_dump()
    updates = _merge_trip_fields(state, result)
    assert updates["turn_meta"]["remove_all_activities"] is True


# ---------------------------------------------------------------------------
# PART B -- Post-loop enforcement
# ---------------------------------------------------------------------------


def test_remove_all_clears_activities_keeps_logistics() -> None:
    state = _base_state_with_activities(remove_all=True)
    _apply_remove_all_activities(state)

    # tiles.activities emptied
    assert state["tiles"]["activities"] == []
    # hotels/flights tiles untouched
    assert len(state["tiles"]["hotels"]) == 1
    assert len(state["tiles"]["flights"]) == 1

    # Tier-1 specialist section dropped; local_expert kept
    types = {s["specialist_type"] for s in state["strategy_sections"]}
    assert "diving" not in types
    assert "local_expert" in types

    # specialist_plans cleared
    assert "diving" not in state["specialist_plans"]

    # booking_types.activities off + categories empty
    assert state["trip_settings"]["booking_types"]["activities"] == "off"
    assert state["trip_settings"]["activity_settings"]["categories"] == []
    assert state["trip_plan"]["activity_categories"] == []
    assert state["trip_plan"]["specialist_hints"] == []

    # replace signals set
    assert state["turn_meta"]["tiles_replaced"] is True
    assert state["turn_meta"]["removal_pruned"] is True
    assert state["turn_meta"]["browseable_activities"] == []
    assert state["persistent_meta"]["browseable_activities"] == []


def test_remove_all_drops_activity_blocks_keeps_buffers_hotel_flight() -> None:
    state = _base_state_with_activities(remove_all=True)
    _apply_remove_all_activities(state)

    all_blocks = [b for c in state["day_cards"] for b in c["blocks"]]
    # No real activity block survives
    real_activities = [
        b
        for b in all_blocks
        if not b.get("is_buffer")
        and b.get("activity_type") not in ("free_day", "check_in")
        and b.get("booking_category") not in ("hotel", "flight")
    ]
    assert real_activities == []

    # Arrival buffer, hotel check-in, and flight blocks all survive
    block_ids = {b["id"] for b in all_blocks}
    assert "arrival_1" in block_ids
    assert "hotel_1" in block_ids
    assert "flight_1" in block_ids


def test_remove_all_empties_day_becomes_free_day() -> None:
    state = _base_state_with_activities(remove_all=True)
    _apply_remove_all_activities(state)

    # Day 2 had only activities -> becomes a free day
    day2 = next(c for c in state["day_cards"] if c["day_number"] == 2)
    assert day2["label"] == "Free Day"
    assert any(b.get("activity_type") == "free_day" for b in day2["blocks"])

    # Day 1 (arrival + hotel) keeps its boundary label, not relabeled to Free Day
    day1 = next(c for c in state["day_cards"] if c["day_number"] == 1)
    assert day1["label"] == "Arrival Day"


def test_remove_all_noop_when_flag_false() -> None:
    """Guardrail: nothing cleared when remove_all_activities is False."""
    state = _base_state_with_activities(remove_all=False)
    before_activities = list(state["tiles"]["activities"])
    before_sections = list(state["strategy_sections"])
    _apply_remove_all_activities(state)

    assert state["tiles"]["activities"] == before_activities
    assert state["strategy_sections"] == before_sections
    assert "activities" not in state["trip_settings"]["booking_types"]
    assert "tiles_replaced" not in state["turn_meta"]


# ---------------------------------------------------------------------------
# Composition order -- clear wins over _merge_tiles preservation
# ---------------------------------------------------------------------------


def test_composition_clear_wins_over_preserved_specialist_tile() -> None:
    """A specialist tile that _merge_tiles would preserve is gone after the clear."""
    state = _base_state_with_activities(remove_all=True)
    # Simulate _merge_tiles having preserved a specialist tile forward.
    state["tiles"]["activities"] = [
        {
            "id": "preserved_dive",
            "type": "activity",
            "title": "Preserved Dive",
            "source_agent": "vertical_specialist",
            "meta": {"specialist_type": "diving"},
        }
    ]
    _apply_remove_all_activities(state)
    assert state["tiles"]["activities"] == []


# ---------------------------------------------------------------------------
# PART D -- Un-stick
# ---------------------------------------------------------------------------


def test_unstick_via_merge_trip_fields_reenables_activities() -> None:
    """After remove-all, a category add flips booking_types.activities back on."""
    state = {
        "trip_plan": {"destination": "Bali", "activity_categories": []},
        "trip_settings": {"booking_types": {"activities": "off"}},
    }
    result = TripFieldsResult(
        activity_categories=["diving"], fields_changed=["activity_categories"]
    ).model_dump()
    updates = _merge_trip_fields(state, result)
    assert updates["trip_settings"]["booking_types"]["activities"] == "suggested"


def test_unstick_post_loop_reenables_when_specialist_section_present() -> None:
    """A live specialist section while off (no extract) re-enables activities."""
    state = {
        "trip_plan": {"destination": "Bali", "activity_categories": ["diving"]},
        "trip_settings": {"booking_types": {"activities": "off"}},
        "strategy_sections": [{"specialist_type": "diving"}],
        "turn_meta": {},
    }
    _reenable_activities_if_requested(state)
    assert state["trip_settings"]["booking_types"]["activities"] == "suggested"


def test_unstick_does_not_fire_on_remove_all_turn() -> None:
    """Un-stick must yield to a remove-all turn."""
    state = {
        "trip_plan": {"destination": "Bali", "activity_categories": ["diving"]},
        "trip_settings": {"booking_types": {"activities": "off"}},
        "strategy_sections": [{"specialist_type": "diving"}],
        "turn_meta": {"remove_all_activities": True},
    }
    _reenable_activities_if_requested(state)
    assert state["trip_settings"]["booking_types"]["activities"] == "off"


def test_remove_all_then_unstick_sequence() -> None:
    """End-to-end: remove-all clears, then a later add re-enables."""
    state = _base_state_with_activities(remove_all=True)
    _apply_remove_all_activities(state)
    assert state["trip_settings"]["booking_types"]["activities"] == "off"

    # Later turn: traveler asks for diving again.
    result = TripFieldsResult(
        activity_categories=["diving"], fields_changed=["activity_categories"]
    ).model_dump()
    updates = _merge_trip_fields(state, result)
    assert updates["trip_settings"]["booking_types"]["activities"] == "suggested"


def test_unstick_merge_specialist_does_not_clobber_settings() -> None:
    """_merge_specialist returns only delta keys (no full trip_settings copy)."""
    state = {
        "trip_plan": {"destination": "Bali"},
        "trip_settings": {"booking_types": {"activities": "off"}},
    }
    result = {
        "strategy_section": {"specialist_type": "diving"},
        "topic": "diving",
        "constraints": [],
    }
    updates = _merge_specialist(state, result)
    # _merge_specialist intentionally does NOT touch trip_settings (avoids the
    # parallel-round shallow-merge clobber); un-stick for the no-extract case is
    # handled post-loop by _reenable_activities_if_requested.
    assert "trip_settings" not in updates


# ---------------------------------------------------------------------------
# PART C -- prompt directive
# ---------------------------------------------------------------------------


def test_turn_context_injects_remove_all_directive() -> None:
    state = {
        "trip_plan": {"destination": "Bali"},
        "turn_meta": {"remove_all_activities": True},
    }
    ctx = build_turn_context(state)
    assert "remove ALL activities" in ctx
    assert "Do NOT call get_specialist_advice" in ctx


def test_turn_context_no_directive_without_flag() -> None:
    state = {"trip_plan": {"destination": "Bali"}, "turn_meta": {}}
    ctx = build_turn_context(state)
    assert "remove ALL activities" not in ctx
