"""
Bug-driven tests for intent_router.py pure functions.

Tests:
- _detect_specialists_from_activity_settings
- _compute_constraint_hash
- _clear_stale_specialist_content
"""

from __future__ import annotations

import importlib

import pytest
from langchain_core.messages import HumanMessage

from app.planner.nodes.intent_router import (
    _block_destination_switch_if_needed,
    _build_plan_progression_suggestions,
    _build_question_suggestions,
    _clear_exploration_carryover,
    _clear_stale_specialist_content,
    _compute_constraint_hash,
    _destination_context_changed,
    _detect_destination_switch_request,
    _detect_specialists_from_activity_settings,
    _looks_like_destination_setup_turn,
    _reset_destination_bound_state_if_changed,
    _should_attempt_preplan_opportunistic_extraction,
)
from app.planner.nodes.router_extraction import IntentClassification, RouterOutput
from app.planner.state.graph_state import GraphState, TripPlan, TripSettings


def _make_state_with_categories(categories: list[str]) -> GraphState:
    """Build a GraphState with activity_settings.categories set."""
    state = GraphState()
    state.metadata["trip_settings"] = {
        "activity_settings": {"categories": categories},
    }
    return state


# =============================================================================
# 1. _detect_specialists_from_activity_settings
# =============================================================================


class TestDetectSpecialistsFromActivitySettings:
    """Tests for detecting specialist types from activity categories."""

    def test_detect_specialists_tier1_categories(self):
        """Tier 1 categories (diving, hiking) map to their specialist names."""
        state = _make_state_with_categories(["diving", "hiking"])
        result = _detect_specialists_from_activity_settings(state)

        assert "diving" in result, "Should detect diving specialist"
        assert "hiking" in result, "Should detect hiking specialist"

    def test_detect_specialists_tier2_categories(self):
        """Tier 2 categories (yoga, cooking) map to their category name as specialist."""
        state = _make_state_with_categories(["yoga", "cooking"])
        result = _detect_specialists_from_activity_settings(state)

        assert "yoga" in result, "Should detect yoga as Tier 2 specialist"
        assert "cooking" in result, "Should detect cooking as Tier 2 specialist"

    def test_empty_categories_returns_empty(self):
        """Empty categories produces no specialists."""
        state = _make_state_with_categories([])
        result = _detect_specialists_from_activity_settings(state)
        assert result == []

    def test_mixed_tier1_tier2(self):
        """Mixed Tier 1 + Tier 2 categories all detected."""
        state = _make_state_with_categories(["diving", "yoga"])
        result = _detect_specialists_from_activity_settings(state)

        assert "diving" in result
        assert "yoga" in result


# =============================================================================
# 2. _compute_constraint_hash
# =============================================================================


class TestComputeConstraintHash:
    """Tests for constraint hash computation (cache invalidation key)."""

    def test_constraint_hash_deterministic(self):
        """Same inputs produce the same hash."""
        plan = TripPlan(destination="Bali", start_date="2026-03-01")
        settings = TripSettings(
            activity_settings={"categories": ["diving", "hiking"], "skill_level": None},
        )

        hash1 = _compute_constraint_hash(plan, settings)
        hash2 = _compute_constraint_hash(plan, settings)
        assert hash1 == hash2

    def test_different_categories_different_hash(self):
        """Different categories produce different hashes."""
        plan = TripPlan(destination="Bali", start_date="2026-03-01")
        settings_a = TripSettings(
            activity_settings={"categories": ["diving"], "skill_level": None},
        )
        settings_b = TripSettings(
            activity_settings={"categories": ["hiking"], "skill_level": None},
        )

        hash_a = _compute_constraint_hash(plan, settings_a)
        hash_b = _compute_constraint_hash(plan, settings_b)
        assert hash_a != hash_b

    def test_constraint_hash_category_order_independent(self):
        """Category order does not affect the hash (sorted internally)."""
        plan = TripPlan(destination="Bali", start_date="2026-03-01")
        settings_ab = TripSettings(
            activity_settings={"categories": ["hiking", "diving"], "skill_level": None},
        )
        settings_ba = TripSettings(
            activity_settings={"categories": ["diving", "hiking"], "skill_level": None},
        )

        hash_ab = _compute_constraint_hash(plan, settings_ab)
        hash_ba = _compute_constraint_hash(plan, settings_ba)
        assert hash_ab == hash_ba

    def test_different_destination_different_hash(self):
        """Different destinations produce different hashes."""
        settings = TripSettings(
            activity_settings={"categories": ["diving"], "skill_level": None},
        )
        plan_a = TripPlan(destination="Bali", start_date="2026-03-01")
        plan_b = TripPlan(destination="Thailand", start_date="2026-03-01")

        assert _compute_constraint_hash(plan_a, settings) != _compute_constraint_hash(
            plan_b, settings
        )


# =============================================================================
# 3. _clear_stale_specialist_content
# =============================================================================


class TestClearStaleSpecialistContent:
    """Tests for clearing stale specialist data on constraint change."""

    def test_clear_stale_specialist_content(self):
        """After clearing, itinerary_blocks, constraints, and tiles are empty."""
        state = GraphState()
        # Populate with stale data
        from app.planner.state.graph_state import ItineraryBlock, SpecialistConstraint

        state.trip_plan.itinerary_blocks = [
            ItineraryBlock(
                day=1,
                title="Old dive",
                description="Stale",
                type="activity",
                source_specialist="diving",
            )
        ]
        state.trip_plan.constraints = [
            SpecialistConstraint(type="safety", rule="min_24h_buffer_after_dive")
        ]
        state.tiles = {
            "flights": [{"id": "f1"}],
            "activities": [{"id": "a1"}],
        }
        state.metadata["strategy_sections"] = [
            {"specialist_type": "diving", "content_added": [{"title": "Dive"}]}
        ]
        state.metadata["specialist_infeasible"] = True
        state.metadata["specialist_infeasible_reason"] = "Too far"
        state.metadata["specialist_alternative"] = "Try X"

        _clear_stale_specialist_content(state)

        assert state.trip_plan.itinerary_blocks == []
        assert state.trip_plan.constraints == []
        assert state.tiles == {}
        assert state.metadata.get("strategy_sections") == []
        assert "specialist_infeasible" not in state.metadata
        assert "specialist_infeasible_reason" not in state.metadata
        assert "specialist_alternative" not in state.metadata

    def test_clear_preserves_trip_plan_core_fields(self):
        """Clearing stale content preserves destination, dates, etc."""
        state = GraphState(
            trip_plan=TripPlan(
                destination="Bali",
                start_date="2026-03-01",
                end_date="2026-03-10",
                budget=5000.0,
            )
        )
        state.tiles = {"flights": [{"id": "old"}]}

        _clear_stale_specialist_content(state)

        assert state.trip_plan.destination == "Bali"
        assert state.trip_plan.start_date == "2026-03-01"
        assert state.trip_plan.end_date == "2026-03-10"
        assert state.trip_plan.budget == 5000.0


# =============================================================================
# 4. Exploration carryover + chip category alignment
# =============================================================================


class TestExplorationCarryoverAndChipCategories:
    def test_destination_context_change_detection(self):
        state = GraphState(trip_plan=TripPlan(destination="Bali"))

        assert _destination_context_changed(state, "Bali") is False

        state.metadata["last_destination_context"] = "Bali"
        assert _destination_context_changed(state, "Rome") is True

    def test_clear_exploration_carryover_removes_repetitive_metadata(self):
        state = GraphState()
        state.metadata.update(
            {
                "detected_month": "March",
                "generic_question_count": 4,
                "suggested_question_types": ["weather", "costs"],
                "last_suggested_replies": ["March 1-8", "What's weather like?"],
                "awaiting_dates": True,
                "keep_me": "unchanged",
            }
        )

        _clear_exploration_carryover(state)

        assert "detected_month" not in state.metadata
        assert "generic_question_count" not in state.metadata
        assert "suggested_question_types" not in state.metadata
        assert state.metadata["last_suggested_replies"] == ["March 1-8", "What's weather like?"]
        assert "awaiting_dates" not in state.metadata
        assert state.metadata["keep_me"] == "unchanged"

    def test_destination_switch_resets_destination_bound_state(self):
        state = GraphState(trip_plan=TripPlan(destination="Rome"))
        state.metadata.update(
            {
                "last_destination_context": "Bali",
                "tiles_destination": "Bali",
                "local_expert_ran": True,
                "executed_strategy_topics": ["local_expert", "diving"],
                "detected_month": "March",
                "generic_question_count": 3,
                "awaiting_dates": True,
            }
        )
        state.tiles = {"hotels": [{"id": "h1"}], "activities": [{"id": "a1"}]}
        state.metadata["strategy_sections"] = [{"specialist_type": "local_expert"}]

        changed = _reset_destination_bound_state_if_changed(state)

        assert changed is True
        assert state.tiles == {}
        assert state.metadata.get("strategy_sections") == []
        assert state.metadata.get("local_expert_ran") is False
        assert state.metadata.get("tiles_destination") is None
        assert state.metadata.get("executed_strategy_topics") == ["diving"]
        assert "generic_question_count" not in state.metadata
        assert "detected_month" not in state.metadata
        assert "awaiting_dates" not in state.metadata

    def test_destination_switch_is_blocked_and_requires_reset(self):
        state = GraphState(trip_plan=TripPlan(destination="Amsterdam"))

        blocked = _block_destination_switch_if_needed(state, "Rome")

        assert blocked is True
        assert state.trip_plan.destination == "Amsterdam"
        assert state.metadata.get("short_circuit_response") is True
        assert state.metadata.get("short_circuit_type") == "destination_locked"
        assert "click the **reset** button" in state.last_summary.lower()
        assert all(reply.lower() != "reset" for reply in state.suggested_replies)
        assert state.metadata.get("destination_switch_blocked") == {
            "from": "Amsterdam",
            "to": "Rome",
        }

    def test_destination_switch_block_not_triggered_for_same_destination(self):
        state = GraphState(trip_plan=TripPlan(destination="Amsterdam"))

        blocked = _block_destination_switch_if_needed(state, "amsterdam")

        assert blocked is False
        assert state.metadata.get("short_circuit_response") is not True

    def test_detect_destination_switch_request_from_short_phrase(self):
        assert _detect_destination_switch_request("change to rome") == "rome"
        assert _detect_destination_switch_request("switch destination to tokyo") == "tokyo"

    def test_detect_destination_switch_request_ignores_settings_changes(self):
        assert _detect_destination_switch_request("change to 5-star hotels") is None
        assert _detect_destination_switch_request("switch to direct flights only") is None

    def test_detect_destination_switch_request_returns_none_for_non_switch_text(self):
        assert _detect_destination_switch_request("what's the weather in rome?") is None

    def test_destination_setup_heuristic_detects_short_city_input(self):
        assert _looks_like_destination_setup_turn("rome") is True
        assert _looks_like_destination_setup_turn("go to amsterdam") is True

    def test_destination_setup_heuristic_ignores_questions_and_generic_phrases(self):
        assert _looks_like_destination_setup_turn("what is weather in rome?") is False
        assert _looks_like_destination_setup_turn("beach vacation") is False
        assert _looks_like_destination_setup_turn("interested in hiking") is False

    def test_preplan_opportunistic_extraction_prefers_core_field_turns(self):
        state = GraphState()

        assert _should_attempt_preplan_opportunistic_extraction(state, "rome") is True

        state.trip_plan.destination = "Amsterdam"
        assert (
            _should_attempt_preplan_opportunistic_extraction(
                state,
                "what should I do there",
            )
            is False
        )
        assert (
            _should_attempt_preplan_opportunistic_extraction(
                state,
                "next week works",
            )
            is True
        )

        state.metadata["router_extracted_fields"] = True
        assert _should_attempt_preplan_opportunistic_extraction(state, "tokyo") is False


@pytest.mark.asyncio
async def test_intent_router_reset_intent_is_locked_to_ui_button(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router_module = importlib.import_module("app.planner.nodes.intent_router")
    state = GraphState(trip_plan=TripPlan(destination="Amsterdam"))
    state.messages = [HumanMessage(content="start over")]

    monkeypatch.setattr(
        router_module,
        "_check_exact_match_greeting",
        lambda _text: IntentClassification(
            intent="RESET",
            confidence=1.0,
            reasoning="test reset lock",
            specialist_hints=[],
        ),
    )

    result = await router_module.intent_router(state)

    assert result.trip_plan.destination == "Amsterdam"
    assert result.metadata.get("short_circuit_response") is True
    assert result.metadata.get("short_circuit_type") == "reset_locked"
    lower_summary = result.last_summary.lower()
    assert "reset" in lower_summary and "button" in lower_summary


@pytest.mark.asyncio
async def test_relative_extend_not_double_applied_when_post_plan_extraction_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router_module = importlib.import_module("app.planner.nodes.intent_router")
    state = GraphState(
        trip_plan=TripPlan(
            destination="Rome",
            start_date="2026-02-27",
            end_date="2026-03-01",
        )
    )
    state.metadata["plan_view_state"] = "S3_ITINERARY_READY"
    state.messages = [HumanMessage(content="extend by 10 days")]

    async def _fake_extract(_user_text: str, _state: GraphState):
        # Simulates the bug: deterministic path already moved end_date to Mar 11,
        # but LLM extraction proposes another +10 days to Mar 21.
        return (
            RouterOutput(
                intent="PLANNING",
                confidence=0.99,
                reasoning="test double-extend guard",
                specialist_hints=[],
                end_date="2026-03-21",
            ),
            {},
        )

    monkeypatch.setattr(router_module, "_classify_and_extract_with_llm", _fake_extract)

    result = await router_module.intent_router(state)

    assert result.trip_plan.end_date == "2026-03-11"


def test_plan_progression_uses_plan_activity_explore_category():
    state = GraphState(
        trip_plan=TripPlan(
            destination="Bali",
            start_date="2026-03-01",
            end_date="2026-03-07",
        )
    )
    state.metadata["plan_view_state"] = "S2_STRATEGY_READY"
    state.metadata["trip_settings"] = TripSettings(
        activity_settings={"categories": []},
    ).model_dump()

    suggestions = _build_plan_progression_suggestions(state)
    categories = [s["category"] for s in suggestions]

    assert "plan_activity_explore" in categories
    assert "plan_activities" not in categories
    assert "plan_dates_refine" in categories


def test_plan_progression_available_with_dates_even_without_plan_view_state():
    state = GraphState(
        trip_plan=TripPlan(
            destination="Bali",
            start_date="2026-03-01",
            end_date="2026-03-07",
        )
    )
    state.tiles = {"hotels": [{"id": "h1"}], "flights": []}
    state.metadata["trip_settings"] = TripSettings(
        activity_settings={"categories": []},
    ).model_dump()

    suggestions = _build_plan_progression_suggestions(state)
    categories = [s["category"] for s in suggestions]

    assert "plan_flights_hint" in categories
    assert "plan_hotels_compare" in categories


def test_question_suggestions_suppressed_after_core_dates():
    state = GraphState(
        trip_plan=TripPlan(
            destination="Bali",
            start_date="2026-03-01",
            end_date="2026-03-07",
        )
    )

    assert _build_question_suggestions(state) == []
