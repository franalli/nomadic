from __future__ import annotations

import importlib
import time
from dataclasses import dataclass

import pytest
from langchain_core.messages import HumanMessage

from app.debug_utils import RequestMetrics
from app.planner.nodes.synthesizer import (
    PILL_ACTION_MAP,
    _build_destination_setup_message,
    _build_synthesis_context,
    _get_model_id,
    _ground_flight_response,
    _render_prompt_for_response_type,
    _should_force_destination_setup_message,
    _should_use_llm_synthesis,
    generate_suggestions,
)
from app.planner.state import GraphState, TripPlan

synthesizer_module = importlib.import_module("app.planner.nodes.synthesizer")


def _new_state(*, metadata: dict | None = None, last_human: str = "hello") -> GraphState:
    state = GraphState(
        trip_plan=TripPlan(destination="Bali", start_date="2025-03-01", end_date="2025-03-08")
    )
    state.messages = [HumanMessage(content=last_human)]
    if metadata:
        state.metadata.update(metadata)
    return state


def test_prompt_specialist_update_isolation() -> None:
    prompt = _render_prompt_for_response_type("specialist_update")

    assert "POST-PLAN UPDATE (YOUR ONLY INSTRUCTION)" in prompt
    assert "FIRST PLAN RESPONSE" not in prompt


def test_prompt_planning_isolation() -> None:
    prompt = _render_prompt_for_response_type("planning")

    assert "FIRST PLAN RESPONSE" in prompt
    assert "POST-PLAN UPDATE (YOUR ONLY INSTRUCTION)" not in prompt


def test_shared_rules_present_only_for_planning_and_specialist_update() -> None:
    planning_prompt = _render_prompt_for_response_type("planning")
    specialist_prompt = _render_prompt_for_response_type("specialist_update")
    greeting_prompt = _render_prompt_for_response_type("greeting")
    exploration_prompt = _render_prompt_for_response_type("exploration")

    assert "SHARED RULES" in planning_prompt
    assert "SHARED RULES" in specialist_prompt
    assert "SHARED RULES" not in greeting_prompt
    assert "SHARED RULES" not in exploration_prompt


class _ModelNameStub:
    model_name = "gpt-4o-mini"


class _ModelStub:
    model = "gemini-1.5-pro"


class _UnknownModelStub:
    pass


@pytest.mark.parametrize(
    ("llm", "expected"),
    [
        (_ModelNameStub(), "gpt-4o-mini"),
        (_ModelStub(), "gemini-1.5-pro"),
        (_UnknownModelStub(), "unknown"),
    ],
)
def test_get_model_id_fallback_matrix(llm: object, expected: str) -> None:
    assert _get_model_id(llm) == expected


@pytest.mark.parametrize(
    ("metadata", "last_human", "expected_change_type"),
    [
        ({"settings_just_updated": True}, "GENERATE_PLAN_NOW", "STEPPER_RERUN"),
        ({"settings_just_updated": True}, "set hotels to 5 star", "SETTINGS_CHANGE"),
        ({"added_categories": ["hiking"]}, "add hiking", "NEW_CATEGORY"),
        ({"turn_applied_fields": ["end_date"]}, "extend trip", "DATE_CHANGE"),
        ({}, "just update", "PLAN_UPDATE"),
    ],
)
def test_change_type_mapping_in_synthesis_context(
    metadata: dict,
    last_human: str,
    expected_change_type: str,
) -> None:
    state = _new_state(metadata=metadata, last_human=last_human)
    context = _build_synthesis_context(state, response_type="specialist_update")

    assert f"- change_type: {expected_change_type}" in context


def test_specialist_breakdown_from_metadata_dict_sections() -> None:
    state = _new_state(
        metadata={
            "strategy_sections": [
                {"specialist_type": "diving", "content_added": [{"id": 1}, {"id": 2}, {"id": 3}]},
                {"specialist_type": "local_expert", "content_added": [{"id": 9}]},
            ]
        }
    )

    context = _build_synthesis_context(state, response_type="specialist_update")

    assert "## What Changed This Turn" in context
    assert "- Specialist activities placed: diving: 3" in context
    assert "local_expert" not in context
    assert "Mention what changed, not inventory" in context


@dataclass
class _SectionObj:
    specialist_type: str
    content_added: list[dict]


def test_specialist_breakdown_from_metadata_object_sections() -> None:
    state = _new_state(
        metadata={
            "strategy_sections": [
                _SectionObj(specialist_type="hiking", content_added=[{"id": 1}, {"id": 2}]),
            ]
        }
    )

    context = _build_synthesis_context(state, response_type="specialist_update")

    assert "## What Changed This Turn" in context
    assert "- Specialist activities placed: hiking: 2" in context
    assert "Mention what changed, not inventory" in context


def test_plan_flight_pref_maps_to_direct_flights_trigger_action() -> None:
    action_type, action_target = PILL_ACTION_MAP["plan_flight_pref"]
    assert action_type == "trigger_action"
    assert action_target == "set_direct_flights_only"


def test_plan_flight_direct_legacy_alias_maps_to_direct_flights_trigger_action() -> None:
    action_type, action_target = PILL_ACTION_MAP["plan_flight_direct"]
    assert action_type == "trigger_action"
    assert action_target == "set_direct_flights_only"


def test_plan_hotels_compare_maps_to_stays_sheet() -> None:
    action_type, action_target = PILL_ACTION_MAP["plan_hotels_compare"]
    assert action_type == "open_pill"
    assert action_target == "stays"


def test_plan_dates_refine_maps_to_dates_sheet() -> None:
    action_type, action_target = PILL_ACTION_MAP["plan_dates_refine"]
    assert action_type == "open_pill"
    assert action_target == "dates"


def test_date_chip_categories_do_not_force_open_pill_actions() -> None:
    assert "date_prompt" not in PILL_ACTION_MAP
    assert "date_contextual" not in PILL_ACTION_MAP


def test_generate_suggestions_date_prompt_chips_use_send_message_actions() -> None:
    state = GraphState(trip_plan=TripPlan(destination="Rome"))

    generate_suggestions(state)
    structured = state.metadata.get("suggestion_chips", [])
    date_chips = [
        chip for chip in structured if chip.get("category") in {"date_prompt", "date_contextual"}
    ]

    assert date_chips
    assert all(chip.get("action_type") == "send_message" for chip in date_chips)
    assert all(chip.get("action_target") is None for chip in date_chips)


@pytest.mark.parametrize(
    ("short_circuit_type", "expected"),
    [
        ("exploration", True),
        ("soft_transition", True),
        ("question_answer", True),
        ("gate_blocked", True),
        ("destination_locked", False),
        ("reset_locked", False),
        ("greeting", False),
        ("reset", False),
    ],
)
def test_should_use_llm_synthesis_by_short_circuit_type(
    short_circuit_type: str,
    expected: bool,
) -> None:
    state = _new_state(
        metadata={
            "short_circuit_response": True,
            "short_circuit_type": short_circuit_type,
        }
    )

    assert _should_use_llm_synthesis(state) is expected


def test_should_force_destination_setup_message_when_destination_set_without_dates() -> None:
    state = GraphState(trip_plan=TripPlan(destination="Rome"))
    state.metadata["turn_applied_fields"] = ["destination"]

    assert _should_force_destination_setup_message(state) is True


def test_should_not_force_destination_setup_message_when_dates_exist() -> None:
    state = GraphState(
        trip_plan=TripPlan(destination="Rome", start_date="2026-03-01", end_date="2026-03-07")
    )
    state.metadata["turn_applied_fields"] = ["destination"]

    assert _should_force_destination_setup_message(state) is False


def test_build_destination_setup_message_mentions_dates_activities_and_origin_hint() -> None:
    state = GraphState(trip_plan=TripPlan(destination="Rome"))
    message = _build_destination_setup_message(state)

    lowered = message.lower()
    assert "dates" in lowered
    assert "activit" in lowered
    assert "origin is not required" in lowered


def test_generate_suggestions_preserves_discover_slot_with_priority_zero_group() -> None:
    state = GraphState(trip_plan=TripPlan(destination="Bali"))
    state.metadata["detected_month"] = "March"

    suggested_replies = generate_suggestions(state)
    categories = [m.get("category") for m in state.metadata.get("suggestion_chip_meta", [])]
    p0_categories = {"destination_choice", "date_prompt", "date_contextual"}

    assert len(suggested_replies) == 3
    assert sum(1 for c in categories if c in p0_categories) <= 2
    assert any(
        isinstance(c, str) and (c.startswith("question_") or c.startswith("plan_"))
        for c in categories
    )


def test_generate_suggestions_rotates_question_categories_across_calls() -> None:
    state = GraphState(trip_plan=TripPlan(destination="Bali"))

    generate_suggestions(state)
    first_meta = list(state.metadata.get("suggestion_chip_meta", []))
    first_questions = {
        m.get("category")
        for m in first_meta
        if isinstance(m, dict) and str(m.get("category", "")).startswith("question_")
    }

    generate_suggestions(state)
    second_meta = list(state.metadata.get("suggestion_chip_meta", []))
    second_questions = {
        m.get("category")
        for m in second_meta
        if isinstance(m, dict) and str(m.get("category", "")).startswith("question_")
    }

    assert first_questions
    assert second_questions
    assert first_questions.isdisjoint(second_questions)


def test_generate_suggestions_skips_just_asked_question_type() -> None:
    state = GraphState(trip_plan=TripPlan(destination="Bali"))
    state.messages = [HumanMessage(content="What's the weather like in Bali?")]

    generate_suggestions(state)
    categories = [m.get("category") for m in state.metadata.get("suggestion_chip_meta", [])]

    assert "question_weather" not in categories


def test_generate_suggestions_post_plan_prefers_refinement_actions() -> None:
    state = GraphState(
        trip_plan=TripPlan(destination="Rome", start_date="2026-02-27", end_date="2026-03-01")
    )
    state.metadata["plan_view_state"] = "S3_ITINERARY_READY"
    state.tiles = {"hotels": [{"id": "h1"}], "flights": [], "activities": []}

    generate_suggestions(state)
    categories = [m.get("category") for m in state.metadata.get("suggestion_chip_meta", [])]

    assert categories
    assert all(
        not (isinstance(category, str) and category.startswith("question_"))
        for category in categories
    )


def test_generate_suggestions_keeps_departure_city_chip_until_origin_set() -> None:
    state = GraphState(
        trip_plan=TripPlan(destination="Rome", start_date="2026-02-27", end_date="2026-03-01")
    )
    state.metadata["plan_view_state"] = "S3_ITINERARY_READY"
    state.metadata["last_suggested_replies"] = ["Set my departure city"]
    state.metadata["trip_settings"] = {
        "booking_types": {
            "hotels": "suggested",
            "flights": "suggested",
            "activities": "suggested",
            "ground_transport": "off",
        },
        "activity_settings": {"categories": []},
    }
    state.tiles = {"hotels": [{"id": "h1"}], "activities": [{"id": "a1"}], "flights": []}

    suggestions = generate_suggestions(state)
    categories = [m.get("category") for m in state.metadata.get("suggestion_chip_meta", [])]

    assert "Set my departure city" in suggestions
    assert "plan_flights_hint" in categories


def test_generate_suggestions_resets_carryover_when_destination_changes() -> None:
    state = GraphState(trip_plan=TripPlan(destination="Rome"))
    state.metadata.update(
        {
            "last_destination_context": "bali",
            "suggested_question_types": ["legacy_marker", "weather", "safety"],
            "generic_question_count": 4,
            "detected_month": "March",
            "last_suggested_replies": ["legacy reply marker"],
            "awaiting_dates": True,
        }
    )

    generate_suggestions(state)
    categories = [m.get("category") for m in state.metadata.get("suggestion_chip_meta", [])]
    suggested_qtypes = state.metadata.get("suggested_question_types", [])
    suggested_replies = state.metadata.get("last_suggested_replies", [])

    assert "question_weather" in categories
    assert state.metadata.get("last_destination_context") == "Rome"
    assert "awaiting_dates" not in state.metadata
    assert "generic_question_count" not in state.metadata
    assert "detected_month" not in state.metadata
    assert isinstance(suggested_qtypes, list)
    assert "legacy_marker" not in suggested_qtypes
    assert isinstance(suggested_replies, list)
    assert all("legacy reply marker" not in text for text in suggested_replies)


def test_synthesis_context_includes_no_origin_flight_guardrail() -> None:
    state = _new_state(
        metadata={
            "trip_inputs": {"booking_types": {"flights": "on"}},
            "flight_search_status": "skipped_no_origin",
            "flight_skip_reason": "no_origin_for_flights",
        }
    )
    context = _build_synthesis_context(state, response_type="specialist_update")

    assert "- status: skipped_no_origin" in context
    assert "- skip_reason: no_origin_for_flights" in context
    assert "Do NOT claim flights were found" in context


def test_ground_flight_response_removes_hallucinated_counts_and_prompts_origin() -> None:
    state = _new_state(
        metadata={
            "trip_inputs": {"booking_types": {"flights": "on"}},
            "flight_search_status": "skipped_no_origin",
            "flight_skip_reason": "no_origin_for_flights",
        }
    )
    state.tiles = {"flights": []}

    grounded = _ground_flight_response(
        "Now showing direct flights. Found **2 flights**.",
        state,
    )

    assert "Found **2 flights**" not in grounded
    assert "Now showing direct flights." not in grounded
    assert "departure city" in grounded


def test_ground_flight_response_corrects_hotel_activity_count_claims() -> None:
    state = _new_state()
    state.tiles = {
        "hotels": [{"id": "h1"}],
        "activities": [{"id": "a1"}, {"id": "a2"}, {"id": "a3"}],
        "flights": [],
    }

    grounded = _ground_flight_response(
        "Updated your plan. Found **1 hotel** and **8 activities**.",
        state,
    )

    assert "8 activities" not in grounded
    assert "Found **1 hotel** and **3 activities**." in grounded


def test_ground_flight_response_drops_count_recap_for_question_turns() -> None:
    state = _new_state(last_human="What's the weather like in Bali?")
    state.tiles = {
        "hotels": [{"id": "h1"}],
        "activities": [{"id": "a1"}, {"id": "a2"}, {"id": "a3"}],
        "flights": [],
    }
    state.metadata["tile_inventory_changed_this_turn"] = True

    grounded = _ground_flight_response(
        "March is warm with occasional rain. Found **1 hotel** and **3 activities**.",
        state,
    )

    assert grounded == "March is warm with occasional rain."


def test_ground_flight_response_ignores_date_adjustments_in_metadata() -> None:
    """Date adjustment note appending was removed; metadata is ignored."""
    state = _new_state(
        metadata={
            "date_auto_adjustments": [
                {
                    "field": "start_date",
                    "from": "2026-02-15",
                    "to": "2027-02-15",
                    "reason": "past_date_auto_bumped",
                },
                {
                    "field": "end_date",
                    "from": "2026-02-25",
                    "to": "2027-02-25",
                    "reason": "preserve_range_after_start_bump",
                },
            ]
        }
    )
    state.tiles = {"hotels": [{"id": "h1"}], "activities": [], "flights": []}

    grounded = _ground_flight_response("Plan updated.", state)

    assert "2026-02-15 -> 2027-02-15" not in grounded
    assert "Adjusted past dates" not in grounded


def test_ground_flight_response_skips_date_adjustment_note_when_new_dates_present() -> None:
    state = _new_state(
        metadata={
            "date_auto_adjustments": [
                {
                    "field": "start_date",
                    "from": "2026-02-15",
                    "to": "2027-02-15",
                    "reason": "past_date_auto_bumped",
                },
                {
                    "field": "end_date",
                    "from": "2026-02-25",
                    "to": "2027-02-25",
                    "reason": "preserve_range_after_start_bump",
                },
            ]
        }
    )
    state.tiles = {"hotels": [], "activities": [], "flights": []}

    grounded = _ground_flight_response(
        "Trip locked for **2027-02-15** to **2027-02-25**.",
        state,
    )

    assert "Adjusted past dates to future dates" not in grounded
    assert "2026-02-15 -> 2027-02-15" not in grounded


def test_ground_flight_response_skips_date_adjustment_note_for_human_date_range() -> None:
    state = _new_state(
        metadata={
            "date_auto_adjustments": [
                {
                    "field": "start_date",
                    "from": "2026-02-15",
                    "to": "2027-02-15",
                    "reason": "past_date_auto_bumped",
                },
                {
                    "field": "end_date",
                    "from": "2026-02-25",
                    "to": "2027-02-25",
                    "reason": "preserve_range_after_start_bump",
                },
            ]
        }
    )
    state.tiles = {"hotels": [{"id": "h1"}], "activities": [{"id": "a1"}], "flights": []}

    grounded = _ground_flight_response(
        (
            "Your Bali itinerary is all set for February 15-25, 2027. "
            "Found **1 hotel** and **1 activity**."
        ),
        state,
    )

    assert "Adjusted past dates to future dates" not in grounded
    assert "2026-02-15 -> 2027-02-15" not in grounded


def test_ground_flight_response_strips_disallowed_activity_claim_fragment() -> None:
    state = _new_state(
        metadata={
            "trip_inputs": {
                "activity_settings": {
                    "categories": ["diving", "surfing", "nightlife", "yoga"],
                }
            }
        }
    )
    state.tiles = {
        "activities": [
            {"id": "a1", "title": "Sunset Yoga at Canggu", "meta": {"category": "yoga"}},
            {"id": "a2", "title": "Seminyak Nightlife Crawl", "meta": {"category": "nightlife"}},
        ]
    }

    grounded = _ground_flight_response(
        (
            "Extended by **5 days** to **Mar 2**, adding **West Bali National Park** "
            "to the hiking days."
        ),
        state,
    )

    assert "Extended by **5 days** to **Mar 2**" in grounded
    assert "West Bali National Park" not in grounded
    assert "hiking" not in grounded.lower()


def test_ground_flight_response_corrects_activity_category_count_claims() -> None:
    state = _new_state(
        metadata={
            "trip_inputs": {
                "activity_settings": {
                    "categories": ["diving", "surfing", "nightlife", "yoga"],
                }
            }
        }
    )
    state.tiles = {
        "activities": [
            {"id": "a1", "title": "Sunset Yoga at Canggu", "meta": {"category": "yoga"}},
            {"id": "a2", "title": "Beachfront Yoga Flow", "meta": {"category": "yoga"}},
            {"id": "a3", "title": "Seminyak Nightlife Crawl", "meta": {"category": "nightlife"}},
            {"id": "a4", "title": "Canggu Live Music Night", "meta": {"category": "nightlife"}},
            {"id": "a5", "title": "Kuta Rooftop Bar Hop", "meta": {"category": "nightlife"}},
            {"id": "a6", "title": "Uluwatu Late-Night Set", "meta": {"category": "nightlife"}},
            {"id": "a7", "title": "Morning Yoga at Ubud", "meta": {"category": "yoga"}},
            {"id": "a8", "title": "Sunset Yoga by the Cliffs", "meta": {"category": "yoga"}},
        ]
    }

    grounded = _ground_flight_response(
        "Added **8 nightlife spots** and **8 yoga sessions**.",
        state,
    )

    assert grounded == "Added **4 nightlife spots** and **4 yoga sessions**."


def test_ground_flight_response_strips_unknown_added_entity_claim() -> None:
    state = _new_state(
        metadata={
            "trip_inputs": {
                "activity_settings": {
                    "categories": ["diving", "surfing"],
                }
            }
        }
    )
    state.tiles = {
        "activities": [
            {"id": "a1", "title": "USAT Liberty Wreck Dive", "meta": {"category": "diving"}},
            {"id": "a2", "title": "Manta Point Dive", "meta": {"category": "diving"}},
        ]
    }

    grounded = _ground_flight_response(
        "Extended by **5 days** to **Mar 2**, adding **West Bali National Park**.",
        state,
    )

    assert "Extended by **5 days** to **Mar 2**" in grounded
    assert "West Bali National Park" not in grounded


@pytest.mark.asyncio
async def test_synthesizer_overrides_destination_setup_message_when_dates_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = GraphState(trip_plan=TripPlan(destination="Rome"))
    state.messages = [HumanMessage(content="rome")]
    state.metadata["turn_applied_fields"] = ["destination"]

    async def _fake_enrich_with_images(_state: GraphState) -> None:
        return None

    async def _fake_synthesize_with_llm(_state: GraphState, _response_type: str):
        return ("Rome is an excellent choice.", {"model": "gemini-2.5-flash"})

    monkeypatch.setattr(synthesizer_module, "enrich_with_images", _fake_enrich_with_images)
    monkeypatch.setattr(synthesizer_module, "synthesize_with_llm", _fake_synthesize_with_llm)
    monkeypatch.setattr(synthesizer_module, "generate_suggestions", lambda _state: [])

    await synthesizer_module.synthesizer(state)

    lowered = state.last_summary.lower()
    assert "set your dates" in lowered
    assert "activit" in lowered
    assert "origin is not required" in lowered


@pytest.mark.asyncio
async def test_synthesizer_settings_only_uses_terse_ack_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _new_state(
        metadata={
            "settings_just_updated": True,
            "actionable_acknowledgment": "Applied your preference.",
            "constraint_violations": [],
            "added_categories": [],
            "tier2_tiles_generated": False,
            "tier2_new_content_generated": False,
        },
        last_human="direct flights",
    )
    calls = {"llm": 0}

    async def _fake_enrich_with_images(_state: GraphState) -> None:
        return None

    async def _fake_synthesize_with_llm(_state: GraphState, _response_type: str):
        calls["llm"] += 1
        return ("should not be used", None)

    monkeypatch.setattr(synthesizer_module, "enrich_with_images", _fake_enrich_with_images)
    monkeypatch.setattr(synthesizer_module, "synthesize_with_llm", _fake_synthesize_with_llm)
    monkeypatch.setattr(synthesizer_module, "generate_suggestions", lambda _state: [])

    await synthesizer_module.synthesizer(state)

    assert calls["llm"] == 0
    assert state.last_summary == "Applied your preference."
    assert state.metadata.get("synthesizer_output", {}).get("used_llm") is False


@pytest.mark.asyncio
async def test_synthesizer_settings_with_date_change_routes_to_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Date changes bypass terse ack even when settings_just_updated is true."""
    state = _new_state(
        metadata={
            "settings_just_updated": True,
            "actionable_acknowledgment": "Updated dates.",
            "constraint_violations": [],
            "added_categories": [],
            "tier2_new_content_generated": False,
            "turn_applied_fields": ["end_date"],
        },
        last_human="extend by 5 days",
    )
    calls = {"llm": 0}

    async def _fake_enrich_with_images(_state: GraphState) -> None:
        return None

    async def _fake_synthesize_with_llm(_state: GraphState, _response_type: str):
        calls["llm"] += 1
        return ("Extended by **5 days** to **Mar 13**.", None)

    monkeypatch.setattr(synthesizer_module, "enrich_with_images", _fake_enrich_with_images)
    monkeypatch.setattr(synthesizer_module, "synthesize_with_llm", _fake_synthesize_with_llm)
    monkeypatch.setattr(synthesizer_module, "generate_suggestions", lambda _state: [])

    await synthesizer_module.synthesizer(state)

    assert calls["llm"] == 1
    assert state.metadata.get("synthesizer_output", {}).get("used_llm") is True


@pytest.mark.asyncio
async def test_synthesizer_settings_turn_avoids_count_only_reply_when_inventory_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _new_state(
        metadata={
            "settings_just_updated": True,
            "actionable_acknowledgment": "Direct flights enabled.",
            "constraint_violations": [],
            "added_categories": [],
            "tier2_new_content_generated": False,
            # Force LLM path so post-grounding quality gate runs
            "turn_applied_fields": ["end_date"],
            "last_tile_counts": {"hotels": 1, "flights": 0, "activities": 6},
        },
        last_human="direct flights only",
    )
    state.tiles = {
        "hotels": [{"id": "h1"}],
        "flights": [],
        "activities": [
            {"id": "a1"},
            {"id": "a2"},
            {"id": "a3"},
            {"id": "a4"},
            {"id": "a5"},
            {"id": "a6"},
        ],
    }

    async def _fake_enrich_with_images(_state: GraphState) -> None:
        return None

    async def _fake_synthesize_with_llm(_state: GraphState, _response_type: str):
        return ("Found **6 activities**.", {"model": "gemini-2.5-flash"})

    monkeypatch.setattr(synthesizer_module, "enrich_with_images", _fake_enrich_with_images)
    monkeypatch.setattr(synthesizer_module, "synthesize_with_llm", _fake_synthesize_with_llm)
    monkeypatch.setattr(synthesizer_module, "generate_suggestions", lambda _state: [])

    await synthesizer_module.synthesizer(state)

    assert state.last_summary == "Direct flights enabled."


@pytest.mark.asyncio
async def test_synthesizer_settings_turn_avoids_count_only_reply_even_when_inventory_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _new_state(
        metadata={
            "settings_just_updated": True,
            "actionable_acknowledgment": "Direct flights enabled.",
            "constraint_violations": [],
            "added_categories": [],
            "tier2_new_content_generated": False,
            "turn_applied_fields": ["end_date"],
            "last_tile_counts": {"hotels": 0, "flights": 0, "activities": 0},
        },
        last_human="direct flights only",
    )
    state.tiles = {
        "hotels": [{"id": "h1"}],
        "flights": [],
        "activities": [{"id": "a1"}],
    }

    async def _fake_enrich_with_images(_state: GraphState) -> None:
        return None

    async def _fake_synthesize_with_llm(_state: GraphState, _response_type: str):
        return ("Found **1 hotel** and **1 activity**.", {"model": "gemini-2.5-flash"})

    monkeypatch.setattr(synthesizer_module, "enrich_with_images", _fake_enrich_with_images)
    monkeypatch.setattr(synthesizer_module, "synthesize_with_llm", _fake_synthesize_with_llm)
    monkeypatch.setattr(synthesizer_module, "generate_suggestions", lambda _state: [])

    await synthesizer_module.synthesizer(state)

    assert state.last_summary == "Direct flights enabled."


@pytest.mark.asyncio
async def test_synthesizer_ignores_legacy_tier2_generated_flag_when_no_new_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _new_state(
        metadata={
            "settings_just_updated": True,
            "actionable_acknowledgment": "Applied your preference.",
            "constraint_violations": [],
            "added_categories": [],
            "tier2_tiles_generated": True,  # legacy flag can still be present
            "tier2_new_content_generated": False,
        },
        last_human="direct flights",
    )
    calls = {"llm": 0}

    async def _fake_enrich_with_images(_state: GraphState) -> None:
        return None

    async def _fake_synthesize_with_llm(_state: GraphState, _response_type: str):
        calls["llm"] += 1
        return ("should not be used", None)

    monkeypatch.setattr(synthesizer_module, "enrich_with_images", _fake_enrich_with_images)
    monkeypatch.setattr(synthesizer_module, "synthesize_with_llm", _fake_synthesize_with_llm)
    monkeypatch.setattr(synthesizer_module, "generate_suggestions", lambda _state: [])

    await synthesizer_module.synthesizer(state)

    assert calls["llm"] == 0
    assert state.metadata.get("synthesizer_output", {}).get("used_llm") is False


@pytest.mark.asyncio
async def test_synthesizer_tracks_llm_tokens_in_compact_logger_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _new_state(
        metadata={
            "settings_just_updated": True,
            "constraint_violations": [],
            "added_categories": ["nightlife"],
            "tier2_tiles_generated": True,
            "tier2_new_content_generated": True,
            "_metrics": RequestMetrics(start_time=time.time()),
        },
        last_human="add nightlife",
    )
    calls = {"llm": 0}

    async def _fake_enrich_with_images(_state: GraphState) -> None:
        return None

    async def _fake_synthesize_with_llm(_state: GraphState, _response_type: str):
        calls["llm"] += 1
        return (
            "LLM response",
            {
                "model": "gemini-2.5-flash",
                "prompt_tokens": 123,
                "completion_tokens": 45,
                "total_tokens": 168,
            },
        )

    monkeypatch.setattr(synthesizer_module, "enrich_with_images", _fake_enrich_with_images)
    monkeypatch.setattr(synthesizer_module, "synthesize_with_llm", _fake_synthesize_with_llm)
    monkeypatch.setattr(synthesizer_module, "generate_suggestions", lambda _state: [])

    await synthesizer_module.synthesizer(state)

    assert calls["llm"] == 1
    assert state.metadata.get("synthesizer_output", {}).get("used_llm") is True
    node_tokens = state.metadata["_metrics"].node_tokens.get("SYNTHESIZER")
    assert node_tokens is not None
    assert node_tokens.prompt == 123
    assert node_tokens.completion == 45


@pytest.mark.asyncio
async def test_synthesizer_specialist_update_strips_day_recap_fragment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _new_state(
        metadata={
            "settings_just_updated": True,
            "constraint_violations": [],
            "added_categories": [],
            "tier2_tiles_generated": True,
            "tier2_new_content_generated": True,
            "_planning_response_given": True,
        },
        last_human="extend by 5 days",
    )
    state.trip_plan.start_date = "2027-02-15"
    state.trip_plan.end_date = "2027-03-02"
    state.tiles = {
        "hotels": [{"id": "h1"}],
        "activities": [{"id": "a1"}, {"id": "a2"}],
        "flights": [],
    }

    async def _fake_enrich_with_images(_state: GraphState) -> None:
        return None

    async def _fake_synthesize_with_llm(_state: GraphState, _response_type: str):
        return (
            (
                "Your trip now extends to **March 2**, allowing more time to enjoy "
                "**3 days of diving** and **2 days of surfing**. "
                "Found **1 hotel** and **2 activities**."
            ),
            {"model": "gemini-2.5-flash", "prompt_tokens": 10, "completion_tokens": 10},
        )

    monkeypatch.setattr(synthesizer_module, "enrich_with_images", _fake_enrich_with_images)
    monkeypatch.setattr(synthesizer_module, "synthesize_with_llm", _fake_synthesize_with_llm)
    monkeypatch.setattr(synthesizer_module, "generate_suggestions", lambda _state: [])

    await synthesizer_module.synthesizer(state)

    assert "3 days of diving" not in state.last_summary
    assert "2 days of surfing" not in state.last_summary
    assert "extends to **March 2**" in state.last_summary
