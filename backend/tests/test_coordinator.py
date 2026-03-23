"""
Unit tests for coordinator.py — deterministic turn planner and helpers.

Tests the pure-Python planning/dispatch logic. ALL LLM calls and external
deps are mocked. Covers:
- plan_turn(): 4 intent paths (greeting, reset, question, planning/destination)
- _build_envelope(): PlanViewState transitions
- _compute_dispatch_list() / _compute_preserve_list(): affects/preserves logic
- _compute_coordinator_s3_state(): builder result → S3 sub-state
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest

from app.planner.coordinator import (
    _PENDING_ITINERARY_ENRICHMENT_TASK_KEY,
    _apply_activity_tile_enrichment_to_day_cards,
    _build_itinerary,
    _builder_conflicts_to_constraint_violations,
    _canonicalize_applied_updates,
    _collect_canonical_builder_constraints,
    _compute_coordinator_s3_state,
    _compute_dispatch_list,
    _compute_preserve_list,
    _date_change_continuity_details,
    _inject_specialist_tiles_into_state,
    _merge_activity_tiles,
    _norm_topic,
    _normalize_specialist_plan_keys,
    _post_build_enrich_placed_activities,
    _preserved_specialist_tiles_for_turn,
    _refresh_preserved_specialist_section_metadata,
    _rehydrate_trimmed_booked_tiles,
    _resolve_activity_category_filters,
    _run_local_intel,
    _short_circuit_message,
    _specialist_content_to_tiles,
    _tile_refresh_types,
    build_brief,
    build_trip_state_summary,
    execute_turn,
    plan_turn,
)
from app.planner.schemas.coordinator_schemas import (
    ChangeType,
    ClassifierOutput,
    ExecutionPlan,
    ExecutionStep,
    StepType,
)
from app.planner.state.graph_state import ConstraintSeverity, GraphState, TripPlan

# =============================================================================
# Helpers
# =============================================================================


def _make_classifier(**overrides: Any) -> ClassifierOutput:
    """Build a ClassifierOutput with sensible defaults, overriding as needed."""
    defaults: Dict[str, Any] = {
        "intent": "PLANNING",
        "confidence": 0.9,
        "reasoning": "test",
        "change_type": ChangeType.INITIAL_PLAN,
    }
    defaults.update(overrides)
    return ClassifierOutput(**defaults)


def _make_state(**overrides: Any) -> Dict[str, Any]:
    """Build a minimal agent state dict."""
    state: Dict[str, Any] = {
        "trip_plan": {},
        "trip_settings": {},
        "tiles": {},
        "strategy_sections": [],
        "day_cards": [],
        "constraints": [],
        "specialist_plans": {},
        "persistent_meta": {},
        "turn_meta": {},
    }
    state.update(overrides)
    return state


async def _collect_step_events(step_result: Any) -> list[Dict[str, Any]]:
    """Collect step events from either a static return value or async stream."""
    if hasattr(step_result, "__aiter__") and hasattr(step_result, "__anext__"):
        return [event async for event in step_result]
    if step_result is None:
        return []
    if isinstance(step_result, dict):
        return [step_result]
    if isinstance(step_result, list):
        return [event for event in step_result if isinstance(event, dict)]
    return []


# =============================================================================
# plan_turn — intent routing
# =============================================================================


class TestPlanTurnGreeting:
    """Greeting intent short-circuits with no LLM calls."""

    def test_greeting_returns_short_circuit(self) -> None:
        classifier = _make_classifier(intent="GREETING")
        state = _make_state()
        plan = plan_turn(classifier, state)

        assert isinstance(plan, ExecutionPlan)
        assert len(plan.steps) == 1
        assert plan.steps[0].step_type == StepType.SHORT_CIRCUIT
        assert plan.steps[0].params.get("reason") == "greeting"
        assert plan.estimated_llm_calls == 0

    def test_greeting_reason_text(self) -> None:
        classifier = _make_classifier(intent="GREETING")
        plan = plan_turn(classifier, _make_state())
        assert "Greeting" in plan.reason


class TestPlanTurnReset:
    """Reset intent short-circuits and clears state."""

    def test_reset_returns_short_circuit(self) -> None:
        classifier = _make_classifier(intent="RESET", change_type=ChangeType.RESET)
        plan = plan_turn(classifier, _make_state())

        assert len(plan.steps) == 1
        assert plan.steps[0].step_type == StepType.SHORT_CIRCUIT
        assert plan.steps[0].params.get("reason") == "reset"
        assert plan.estimated_llm_calls == 0


class TestPlanTurnQuestion:
    """Question intent generates a response without plan changes."""

    def test_question_no_destination_skips_local_intel(self) -> None:
        # No destination, no question_type → just GENERATE_RESPONSE, no SHORT_CIRCUIT dead code
        classifier = _make_classifier(intent="QUESTION", change_type=ChangeType.QUESTION)
        plan = plan_turn(classifier, _make_state())

        step_types = [s.step_type for s in plan.steps]
        assert step_types == [StepType.GENERATE_RESPONSE]
        assert StepType.SHORT_CIRCUIT not in step_types
        assert plan.estimated_llm_calls == 1

    def test_question_with_question_type_triggers_local_intel(self) -> None:
        # question_type set + destination in trip_plan → LOCAL_INTEL + GENERATE_RESPONSE
        classifier = _make_classifier(
            intent="QUESTION",
            change_type=ChangeType.QUESTION,
            question_type="safety",
        )
        state = _make_state(trip_plan={"destination": "Bali"})
        plan = plan_turn(classifier, state)

        step_types = [s.step_type for s in plan.steps]
        assert StepType.LOCAL_INTEL in step_types
        assert StepType.GENERATE_RESPONSE in step_types
        assert plan.steps[-1].step_type == StepType.GENERATE_RESPONSE

    def test_question_with_specialist_hints_triggers_local_intel(self) -> None:
        # specialist_hints present + destination → LOCAL_INTEL + GENERATE_RESPONSE
        classifier = _make_classifier(
            intent="QUESTION",
            change_type=ChangeType.QUESTION,
            specialist_hints=["diving"],
        )
        state = _make_state(trip_plan={"destination": "Bali"})
        plan = plan_turn(classifier, state)

        step_types = [s.step_type for s in plan.steps]
        assert StepType.LOCAL_INTEL in step_types
        assert StepType.GENERATE_RESPONSE in step_types

    def test_question_reuses_cached_local_intel(self) -> None:
        # Local expert section already present for destination → skip LOCAL_INTEL
        classifier = _make_classifier(
            intent="QUESTION",
            change_type=ChangeType.QUESTION,
            question_type="activities",
        )
        state = _make_state(
            trip_plan={"destination": "Bali"},
            strategy_sections=[
                {
                    "specialist_type": "local_expert",
                    "title": "Local Expert — Bali",
                    "one_liner": "your adventure in Bali",
                }
            ],
        )
        plan = plan_turn(classifier, state)

        step_types = [s.step_type for s in plan.steps]
        assert StepType.LOCAL_INTEL not in step_types
        assert StepType.GENERATE_RESPONSE in step_types

    def test_question_destination_change_refetches_local_intel(self) -> None:
        # Existing local_expert section is for Rwanda; classifier.destination is Tokyo →
        # _has_local_intel_for_destination returns False for Tokyo → LOCAL_INTEL fires
        classifier = _make_classifier(
            intent="QUESTION",
            change_type=ChangeType.QUESTION,
            destination="Tokyo",
            question_type="activities",
        )
        state = _make_state(
            trip_plan={"destination": "Rwanda"},
            strategy_sections=[
                {
                    "specialist_type": "local_expert",
                    "title": "Local Expert — Rwanda",
                    "one_liner": "gorilla trekking in Rwanda",
                }
            ],
        )
        plan = plan_turn(classifier, state)

        step_types = [s.step_type for s in plan.steps]
        assert StepType.LOCAL_INTEL in step_types

    def test_question_specialist_hints_without_destination_skips_local_intel(self) -> None:
        # specialist_hints present but no destination → AND gate short-circuits, skip LOCAL_INTEL
        classifier = _make_classifier(
            intent="QUESTION",
            change_type=ChangeType.QUESTION,
            specialist_hints=["diving"],
        )
        plan = plan_turn(classifier, _make_state())
        step_types = [s.step_type for s in plan.steps]
        assert StepType.LOCAL_INTEL not in step_types
        assert StepType.GENERATE_RESPONSE in step_types

    def test_question_no_specialist_dispatch(self) -> None:
        classifier = _make_classifier(intent="QUESTION", change_type=ChangeType.QUESTION)
        plan = plan_turn(classifier, _make_state())
        step_types = [s.step_type for s in plan.steps]
        assert StepType.DISPATCH_SPECIALISTS not in step_types


class TestPlanTurnPlanning:
    """PLANNING intent with destination triggers specialist dispatch + tiles + response."""

    def test_initial_plan_with_destination_and_dates(self) -> None:
        classifier = _make_classifier(
            intent="PLANNING",
            change_type=ChangeType.INITIAL_PLAN,
            destination="Bali",
            start_date="2026-03-01",
            end_date="2026-03-07",
            specialist_hints=["diving"],
            activity_categories=["diving"],
        )
        state = _make_state()
        plan = plan_turn(classifier, state)

        step_types = [s.step_type for s in plan.steps]
        assert StepType.DISPATCH_SPECIALISTS in step_types
        assert StepType.SEARCH_TILES in step_types
        assert StepType.BUILD_ITINERARY in step_types
        assert StepType.GENERATE_RESPONSE in step_types
        # Response is always last
        assert step_types[-1] == StepType.GENERATE_RESPONSE

    def test_initial_plan_emits_single_tile_step_with_all_types(self) -> None:
        """SEARCH_TILES is a single step — logistics_node handles internal parallelism."""
        classifier = _make_classifier(
            intent="PLANNING",
            change_type=ChangeType.INITIAL_PLAN,
            destination="Bali",
            start_date="2026-03-01",
            end_date="2026-03-07",
            specialist_hints=["diving"],
            activity_categories=["diving"],
        )
        state = _make_state()
        plan = plan_turn(classifier, state)

        tile_steps = [s for s in plan.steps if s.step_type == StepType.SEARCH_TILES]
        assert len(tile_steps) == 1, "Expected single SEARCH_TILES step"
        assert set(tile_steps[0].params["tile_types"]) == {"flights", "hotels", "activities"}
        # Tile step runs parallel with specialists
        assert tile_steps[0].parallel_with == StepType.DISPATCH_SPECIALISTS

    def test_destination_only_no_dates_skips_tiles_and_builder(self) -> None:
        """Without dates, tiles and itinerary builder should not run."""
        classifier = _make_classifier(
            intent="PLANNING",
            change_type=ChangeType.INITIAL_PLAN,
            destination="Paris",
            specialist_hints=["hiking"],
            activity_categories=["hiking"],
        )
        state = _make_state()
        plan = plan_turn(classifier, state)

        step_types = [s.step_type for s in plan.steps]
        assert StepType.SEARCH_TILES not in step_types
        assert StepType.BUILD_ITINERARY not in step_types
        # Still generates response
        assert StepType.GENERATE_RESPONSE in step_types

    def test_planning_without_specialist_skips_dispatch(self) -> None:
        """If no Tier 1 activities, no specialist dispatch."""
        classifier = _make_classifier(
            intent="PLANNING",
            change_type=ChangeType.INITIAL_PLAN,
            destination="Tokyo",
            start_date="2026-04-01",
            end_date="2026-04-07",
        )
        state = _make_state()
        plan = plan_turn(classifier, state)

        step_types = [s.step_type for s in plan.steps]
        assert StepType.DISPATCH_SPECIALISTS not in step_types

    def test_local_intel_included_for_initial_plan(self) -> None:
        classifier = _make_classifier(
            intent="PLANNING",
            change_type=ChangeType.INITIAL_PLAN,
            destination="Bali",
            start_date="2026-03-01",
            end_date="2026-03-07",
        )
        state = _make_state()
        plan = plan_turn(classifier, state)

        step_types = [s.step_type for s in plan.steps]
        assert StepType.LOCAL_INTEL in step_types

    def test_initial_plan_with_existing_itinerary_and_no_field_changes_is_response_only(
        self,
    ) -> None:
        classifier = _make_classifier(
            intent="PLANNING",
            change_type=ChangeType.INITIAL_PLAN,
            destination="Bali",
            start_date="2026-03-01",
            end_date="2026-03-07",
            reasoning="Repeat build request with no new trip inputs",
        )
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            },
            day_cards=[{"day_number": 1, "label": "Arrival"}],
            turn_meta={"fields_changed": []},
        )

        plan = plan_turn(classifier, state)

        assert [step.step_type for step in plan.steps] == [StepType.GENERATE_RESPONSE]


# =============================================================================
# _compute_dispatch_list / _compute_preserve_list
# =============================================================================


class TestComputeDispatchList:
    """Tests for specialist dispatch list computation."""

    def test_initial_plan_dispatches_all_tier1(self) -> None:
        classifier = _make_classifier(
            change_type=ChangeType.INITIAL_PLAN,
            activity_categories=["diving", "hiking"],
        )
        state = _make_state(
            trip_settings={"activity_settings": {"categories": ["diving", "hiking"]}}
        )
        result = _compute_dispatch_list(classifier, state)
        assert "diving" in result
        assert "hiking" in result

    def test_destination_change_dispatches_all(self) -> None:
        classifier = _make_classifier(
            change_type=ChangeType.DESTINATION_CHANGE,
            activity_categories=["surfing"],
        )
        state = _make_state(trip_settings={"activity_settings": {"categories": ["surfing"]}})
        result = _compute_dispatch_list(classifier, state)
        assert "surfing" in result

    def test_targeted_change_only_affected(self) -> None:
        """DAY_COUNT with affects=['diving'] dispatches only diving."""
        classifier = _make_classifier(
            change_type=ChangeType.DAY_COUNT,
            affects=["diving"],
        )
        state = _make_state(
            trip_settings={"activity_settings": {"categories": ["diving", "hiking"]}}
        )
        result = _compute_dispatch_list(classifier, state)
        assert "diving" in result
        assert "hiking" not in result

    def test_date_change_dispatches_existing_specialists(self) -> None:
        classifier = _make_classifier(change_type=ChangeType.DATE_CHANGE)
        state = _make_state(
            specialist_plans={
                "diving": {"day_plans": []},
                "hiking": {"day_plans": []},
            }
        )
        result = _compute_dispatch_list(classifier, state)
        assert "diving" in result
        assert "hiking" in result

    def test_date_change_same_month_same_duration_skips_specialist_rerun(self) -> None:
        classifier = _make_classifier(change_type=ChangeType.DATE_CHANGE)
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-03",
                "end_date": "2026-03-09",
            },
            trip_settings={
                "activity_settings": {"categories": ["diving"], "activities_per_day": 2}
            },
            specialist_plans={"diving": {"day_plans": [{"day_number": 2, "location": "Tulamben"}]}},
            _pre_change_briefs={
                "trip_plan": {
                    "destination": "Bali",
                    "start_date": "2026-03-01",
                    "end_date": "2026-03-07",
                },
                "trip_settings": {
                    "activity_settings": {"categories": ["diving"], "activities_per_day": 2}
                },
            },
        )

        assert _compute_dispatch_list(classifier, state) == []
        assert _compute_preserve_list(classifier, state) == ["diving"]

    def test_date_change_tail_extension_same_month_skips_specialist_rerun(self) -> None:
        classifier = _make_classifier(change_type=ChangeType.DATE_CHANGE)
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-17",
            },
            trip_settings={
                "activity_settings": {"categories": ["diving"], "activities_per_day": 2}
            },
            specialist_plans={"diving": {"day_plans": [{"day_number": 2, "location": "Tulamben"}]}},
            strategy_sections=[
                {
                    "specialist_type": "diving",
                    "content_added": [{"title": "Tulamben wreck dive"}],
                }
            ],
            _pre_change_briefs={
                "trip_plan": {
                    "destination": "Bali",
                    "start_date": "2026-03-01",
                    "end_date": "2026-03-07",
                },
                "trip_settings": {
                    "activity_settings": {"categories": ["diving"], "activities_per_day": 2}
                },
            },
        )

        assert _compute_dispatch_list(classifier, state) == []
        assert _compute_preserve_list(classifier, state) == ["diving"]

    def test_date_change_tail_extension_skips_rerun_even_with_classifier_affects(self) -> None:
        classifier = _make_classifier(change_type=ChangeType.DATE_CHANGE, affects=["diving"])
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-17",
            },
            trip_settings={
                "activity_settings": {"categories": ["diving"], "activities_per_day": 2}
            },
            specialist_plans={"diving": {"day_plans": [{"day_number": 2, "location": "Tulamben"}]}},
            strategy_sections=[
                {
                    "specialist_type": "diving",
                    "content_added": [{"title": "Tulamben wreck dive"}],
                }
            ],
            _pre_change_briefs={
                "trip_plan": {
                    "destination": "Bali",
                    "start_date": "2026-03-01",
                    "end_date": "2026-03-07",
                },
                "trip_settings": {
                    "activity_settings": {"categories": ["diving"], "activities_per_day": 2}
                },
            },
        )

        assert _compute_dispatch_list(classifier, state) == []
        assert _compute_preserve_list(classifier, state) == ["diving"]

    def test_date_change_continuity_details_marks_safe_tail_extension(self) -> None:
        classifier = _make_classifier(change_type=ChangeType.DATE_CHANGE)
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-17",
            },
            trip_settings={
                "activity_settings": {
                    "categories": ["diving", "hiking"],
                    "day_preferences": {"diving": 2},
                    "activities_per_day": 2,
                    "skill_level": "Advanced",
                }
            },
            specialist_plans={
                "diving": {"day_plans": [{"day_number": 2, "location": "Tulamben"}]},
                "hiking": {"day_plans": [{"day_number": 5, "location": "Batur"}]},
            },
            strategy_sections=[
                {
                    "specialist_type": "diving",
                    "content_added": [{"title": "Tulamben wreck dive"}],
                },
                {
                    "specialist_type": "hiking",
                    "content_added": [{"title": "Mount Batur sunrise trek"}],
                },
            ],
            _pre_change_briefs={
                "trip_plan": {
                    "destination": "Bali",
                    "start_date": "2026-03-01",
                    "end_date": "2026-03-07",
                },
                "trip_settings": {
                    "activity_settings": {
                        "categories": ["hiking", "diving"],
                        "day_preferences": {"diving": 2},
                        "activities_per_day": 2,
                        "skill_level": "advanced",
                    }
                },
            },
        )
        plan = ExecutionPlan(
            steps=[],
            reason="PLANNING (date_change): refresh tiles, generate response",
            estimated_llm_calls=1,
            estimated_wall_ms=1200,
        )

        details = _date_change_continuity_details(classifier, state, plan)

        assert details == {
            "safe_tail_extension": True,
            "same_month_bucket": True,
            "same_activity_settings": True,
            "dispatch": [],
            "preserve": ["diving", "hiking"],
        }

    def test_date_change_shifted_window_same_month_still_reruns_specialist(self) -> None:
        classifier = _make_classifier(change_type=ChangeType.DATE_CHANGE)
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-03",
                "end_date": "2026-03-19",
            },
            trip_settings={
                "activity_settings": {"categories": ["diving"], "activities_per_day": 2}
            },
            specialist_plans={"diving": {"day_plans": [{"day_number": 2, "location": "Tulamben"}]}},
            strategy_sections=[
                {
                    "specialist_type": "diving",
                    "content_added": [{"title": "Tulamben wreck dive"}],
                }
            ],
            _pre_change_briefs={
                "trip_plan": {
                    "destination": "Bali",
                    "start_date": "2026-03-01",
                    "end_date": "2026-03-07",
                },
                "trip_settings": {
                    "activity_settings": {"categories": ["diving"], "activities_per_day": 2}
                },
            },
        )

        assert _compute_dispatch_list(classifier, state) == ["diving"]

    def test_removal_excludes_removed_topics(self) -> None:
        classifier = _make_classifier(
            change_type=ChangeType.REMOVE_ACTIVITY,
            removal_targets=["diving"],
            activity_categories=["diving", "hiking"],
        )
        state = _make_state(
            trip_settings={"activity_settings": {"categories": ["diving", "hiking"]}}
        )
        result = _compute_dispatch_list(classifier, state)
        assert "diving" not in result

    def test_question_returns_empty_dispatch(self) -> None:
        classifier = _make_classifier(
            change_type=ChangeType.QUESTION,
        )
        state = _make_state()
        result = _compute_dispatch_list(classifier, state)
        assert result == []


class TestComputePreserveList:
    """Tests for specialist preserve list computation."""

    def test_explicit_preserves(self) -> None:
        classifier = _make_classifier(
            change_type=ChangeType.DAY_COUNT,
            affects=["diving"],
            preserves=["hiking"],
        )
        state = _make_state(
            specialist_plans={
                "diving": {"day_plans": []},
                "hiking": {"day_plans": []},
            }
        )
        result = _compute_preserve_list(classifier, state)
        assert "hiking" in result
        assert "diving" not in result

    def test_implicit_preserves_non_dispatched(self) -> None:
        """When no explicit preserves, keep plans NOT in dispatch list."""
        classifier = _make_classifier(
            change_type=ChangeType.DAY_COUNT,
            affects=["diving"],
        )
        state = _make_state(
            specialist_plans={
                "diving": {"day_plans": []},
                "hiking": {"day_plans": []},
            },
            trip_settings={"activity_settings": {"categories": ["diving", "hiking"]}},
        )
        result = _compute_preserve_list(classifier, state)
        assert "hiking" in result


# =============================================================================
# _compute_coordinator_s3_state
# =============================================================================


class TestComputeS3State:
    """Tests for S3 sub-state computation from builder results."""

    def test_builder_success_with_day_cards(self) -> None:
        turn_meta = {"builder_result": {"success": True, "conflicts": []}}
        result = _compute_coordinator_s3_state(turn_meta, [{"day": 1}])
        assert result == "S3_ITINERARY_READY"

    def test_builder_success_with_conflicts(self) -> None:
        turn_meta = {
            "builder_result": {
                "success": True,
                "conflicts": [{"type": "overlap"}],
            }
        }
        result = _compute_coordinator_s3_state(turn_meta, [{"day": 1}])
        assert result == "S3_EDITING"

    def test_builder_success_no_day_cards(self) -> None:
        turn_meta = {"builder_result": {"success": True, "conflicts": []}}
        result = _compute_coordinator_s3_state(turn_meta, [])
        assert result == "S3_BLOCKED"

    def test_builder_failure_with_day_cards(self) -> None:
        turn_meta = {"builder_result": {"success": False, "conflicts": []}}
        result = _compute_coordinator_s3_state(turn_meta, [{"day": 1}])
        assert result == "S3_PARTIAL_CONFLICT"

    def test_builder_failure_no_day_cards(self) -> None:
        turn_meta = {"builder_result": {"success": False, "conflicts": []}}
        result = _compute_coordinator_s3_state(turn_meta, [])
        assert result == "S3_BLOCKED"

    def test_infeasible_zero_activity_result_stays_ready_with_warning(self) -> None:
        turn_meta = {
            "builder_result": {
                "success": True,
                "conflicts": [],
                "activities_placed": 0,
                "warnings": [],
                "infeasible_requested_categories": ["skiing"],
            }
        }
        result = _compute_coordinator_s3_state(turn_meta, [{"day": 1}])
        assert result == "S3_ITINERARY_READY"
        assert any(
            "infeasible" in warning.lower() for warning in turn_meta["builder_result"]["warnings"]
        )


class TestResolveActivityCategoryFilters:
    def test_filters_infeasible_tier1_categories_from_builder(self) -> None:
        state = _make_state(
            trip_settings={
                "activity_settings": {"categories": ["skiing", "food"]},
            },
            turn_meta={
                "feasibility_prechecks": {
                    "skiing": ("infeasible", "No snow", "Try hiking"),
                }
            },
        )

        requested, effective, infeasible, activities_off = _resolve_activity_category_filters(state)

        assert requested == ["skiing", "food"]
        assert effective == ["food"]
        assert infeasible == ["skiing"]
        assert activities_off is False

    def test_all_infeasible_tier1_categories_stay_explicitly_empty(self) -> None:
        state = _make_state(
            trip_settings={
                "activity_settings": {"categories": ["skiing"]},
            },
            turn_meta={
                "feasibility_prechecks": {
                    "skiing": ("infeasible", "No snow", "Try hiking"),
                }
            },
        )

        requested, effective, infeasible, activities_off = _resolve_activity_category_filters(state)

        assert requested == ["skiing"]
        assert effective == []
        assert infeasible == ["skiing"]
        assert activities_off is False


class TestBuilderConflictMapping:
    def test_maps_builder_conflicts_to_constraint_violations(self) -> None:
        mapped = _builder_conflicts_to_constraint_violations(
            [{"type": "temporal_capacity", "message": "Too many blocks", "severity": "warning"}],
            [{"description": "Reduce activities"}],
        )

        assert mapped == [
            {
                "code": "TEMPORAL_CAPACITY",
                "message": "Too many blocks",
                "severity": "warning",
                "category": "itinerary",
                "rule": "temporal_capacity",
                "suggested_action": "Reduce activities",
            }
        ]

    def test_maps_enum_builder_conflict_severity_to_canonical_string(self) -> None:
        mapped = _builder_conflicts_to_constraint_violations(
            [
                {
                    "type": "constraint_clash",
                    "message": "Unsafe overlap",
                    "severity": ConstraintSeverity.BLOCKING,
                }
            ]
        )

        assert mapped[0]["severity"] == "blocking"


# =============================================================================
# _build_envelope — PlanViewState transitions
# =============================================================================


class TestBuildEnvelopeViewState:
    """Test PlanViewState assignment in _build_envelope."""

    @patch("app.planner.services.state_serde.serialize_agent_state", return_value="{}")
    def test_no_destination_returns_s0(self, _mock_serialize: Any) -> None:
        state = _make_state()
        from app.planner.coordinator import _build_envelope

        result = _build_envelope(state, "hello", "sess-1", "Hi there!")
        assert result["document"]["plan_view_state"] == "S0_BOOTSTRAP"

    @patch("app.planner.services.state_serde.serialize_agent_state", return_value="{}")
    def test_strategy_sections_returns_s2(self, _mock_serialize: Any) -> None:
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            },
            strategy_sections=[{"specialist_type": "diving", "content_blocks": []}],
        )
        from app.planner.coordinator import _build_envelope

        result = _build_envelope(state, "plan my trip", "sess-1", "Here is your plan")
        assert result["document"]["plan_view_state"] == "S2_STRATEGY_READY"

    @patch("app.planner.services.state_serde.serialize_agent_state", return_value="{}")
    def test_day_cards_returns_s3_itinerary_ready(self, _mock_serialize: Any) -> None:
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            },
            day_cards=[{"day": 1, "activities": []}],
            turn_meta={
                "builder_result": {"success": True, "conflicts": []},
            },
        )
        from app.planner.coordinator import _build_envelope

        result = _build_envelope(state, "build itinerary", "sess-1", "Done!")
        assert result["document"]["plan_view_state"] == "S3_ITINERARY_READY"

    @patch("app.planner.services.state_serde.serialize_agent_state", return_value="{}")
    def test_builder_conflicts_are_exposed_as_constraint_violations(
        self,
        _mock_serialize: Any,
    ) -> None:
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            },
            day_cards=[{"day": 1, "activities": []}],
            turn_meta={
                "builder_result": {
                    "success": True,
                    "activities_placed": 2,
                    "conflicts": [
                        {
                            "type": "temporal_capacity",
                            "message": "Too many activities",
                            "severity": "warning",
                        }
                    ],
                    "resolutions": [{"description": "Reduce activities"}],
                },
            },
        )
        from app.planner.coordinator import _build_envelope

        result = _build_envelope(state, "build itinerary", "sess-1", "Done!")

        assert result["document"]["plan_view_state"] == "S3_EDITING"
        assert result["document"]["constraint_violations"] == [
            {
                "code": "TEMPORAL_CAPACITY",
                "message": "Too many activities",
                "severity": "warning",
                "category": "itinerary",
                "rule": "temporal_capacity",
                "suggested_action": "Reduce activities",
            }
        ]

    @patch("app.planner.services.state_serde.serialize_agent_state", return_value="{}")
    def test_tiles_only_returns_s2(self, _mock_serialize: Any) -> None:
        state = _make_state(
            trip_plan={
                "destination": "Paris",
                "start_date": "2026-04-01",
                "end_date": "2026-04-05",
            },
            tiles={
                "hotels": [{"id": "h1", "name": "Hotel A"}],
            },
        )
        from app.planner.coordinator import _build_envelope

        result = _build_envelope(state, "find hotels", "sess-1", "Found hotels")
        assert result["document"]["plan_view_state"] == "S2_STRATEGY_READY"

    @patch("app.planner.services.state_serde.serialize_agent_state", return_value="{}")
    def test_flight_tiles_do_not_reenable_explicitly_disabled_flights(
        self,
        _mock_serialize: Any,
    ) -> None:
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "origin": "Rome",
                "start_date": "2026-04-01",
                "end_date": "2026-04-17",
            },
            trip_settings={
                "booking_types": {
                    "flights": "off",
                    "hotels": "suggested",
                    "activities": "suggested",
                }
            },
            tiles={"flights": [{"id": "flight_1"}]},
            persistent_meta={"user_disabled_booking_types": ["flights"]},
        )
        from app.planner.coordinator import _build_envelope

        result = _build_envelope(state, "extend trip", "sess-1", "Updated trip")

        assert result["document"]["trip_inputs"]["booking_types"]["flights"] == "off"
        assert state["trip_settings"]["booking_types"]["flights"] == "off"


# =============================================================================
# Small helpers
# =============================================================================


class TestNormTopic:
    def test_normalizes_case_and_whitespace(self) -> None:
        assert _norm_topic("  Diving ") == "diving"

    def test_empty_string(self) -> None:
        assert _norm_topic("") == ""

    def test_none_safe(self) -> None:
        assert _norm_topic(None) == ""  # type: ignore[arg-type]


class TestShortCircuitMessage:
    def test_reset_message(self) -> None:
        msg = _short_circuit_message("RESET")
        assert "reset" in msg.lower()

    def test_greeting_message(self) -> None:
        msg = _short_circuit_message("GREETING")
        assert "destination" in msg.lower() or "Hi" in msg

    def test_unknown_returns_empty(self) -> None:
        assert _short_circuit_message("UNKNOWN") == ""


class TestCanonicalizeAppliedUpdates:
    def test_maps_date_fields(self) -> None:
        result = _canonicalize_applied_updates(["start_date", "end_date"])
        assert result == ["dates"]

    def test_deduplicates(self) -> None:
        result = _canonicalize_applied_updates(["start_date", "end_date", "trip_duration"])
        assert result.count("dates") == 1

    def test_multiple_categories(self) -> None:
        result = _canonicalize_applied_updates(["destination", "budget", "adults"])
        assert "destination" in result
        assert "budget" in result
        assert "travelers" in result


class _DummyAsyncLock:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


class TestLocalIntel:
    @pytest.mark.asyncio
    async def test_none_travelers_are_normalized_for_enrichment(self, monkeypatch: Any) -> None:
        captured: Dict[str, Any] = {}

        def _fake_build_enrichment_closure(
            *,
            destination: str,
            start_date: str | None,
            end_date: str | None,
            adults: int,
            children: int,
            session_id: str = "",
            budget: float | None = None,
            vibe: str | None = None,
            origin: str | None = None,
            activity_categories: list[str] | None = None,
        ) -> object:
            captured.update(
                {
                    "destination": destination,
                    "start_date": start_date,
                    "end_date": end_date,
                    "adults": adults,
                    "children": children,
                    "session_id": session_id,
                }
            )

            async def _noop() -> None:
                return None

            return _noop

        import importlib

        from app.config import settings as app_settings

        local_expert_module = importlib.import_module("app.planner.nodes.local_expert")

        monkeypatch.setattr(app_settings, "local_expert_use_llm", True)
        monkeypatch.setattr(
            local_expert_module,
            "build_enrichment_closure",
            _fake_build_enrichment_closure,
        )
        monkeypatch.setattr(local_expert_module, "_pending_lock", _DummyAsyncLock())
        monkeypatch.setattr(local_expert_module, "_pending_enrichments", {})
        monkeypatch.setattr(local_expert_module, "_MAX_PENDING_ENRICHMENTS", 3)

        state = _make_state(
            trip_plan={
                "destination": "Rome",
                "start_date": "2026-04-01",
                "end_date": "2026-04-07",
                "adults": None,
                "children": None,
            }
        )

        section = await _run_local_intel(state, session_id="session-123")
        assert section is not None
        assert captured["adults"] == 1
        assert captured["children"] == 0


class TestLogisticsFlightRefresh:
    @pytest.mark.asyncio
    async def test_logistics_does_not_auto_upgrade_when_flights_not_requested(
        self, monkeypatch: Any
    ) -> None:
        import importlib

        logistics_module = importlib.import_module("app.planner.nodes.logistics_node")

        state = GraphState(
            trip_plan=TripPlan(
                destination="Bali",
                origin="Amsterdam",
                start_date="2026-04-01",
                end_date="2026-04-07",
            )
        )
        state.tiles = {"hotels": [], "activities": [], "flights": [{"id": "stale_flight"}]}
        state.metadata.update(
            {
                "trip_settings": {
                    "booking_types": {"flights": "off", "hotels": "suggested", "activities": "on"},
                    "flight_settings": {"direct_only": False, "round_trip": True},
                    "hotel_settings": {"min_stars": 0, "amenities": []},
                    "activity_settings": {"categories": ["diving"]},
                },
                "trip_inputs": {"booking_types": {"flights": "off"}},
                "allow_flight_auto_upgrade": False,
                "requested_tile_types": ["activities"],
            }
        )
        resolve_calls: list[tuple[str, str]] = []

        async def _fake_search_hotels_and_activities(
            state_arg: GraphState, _plan_arg: TripPlan
        ) -> None:
            state_arg.tiles["hotels"] = [{"id": "hotel_1"}]
            state_arg.tiles["activities"] = [{"id": "act_1"}]

        async def _fake_resolve_iata_codes(origin: str, destination: str, _state: GraphState):
            resolve_calls.append((origin, destination))
            if origin:
                raise AssertionError(
                    "Flight refresh should not resolve origin when flights are excluded"
                )
            return "", "DPS"

        monkeypatch.setattr(
            logistics_module,
            "_search_hotels_and_activities",
            _fake_search_hotels_and_activities,
        )
        monkeypatch.setattr(logistics_module, "resolve_iata_codes", _fake_resolve_iata_codes)

        result = await logistics_module.logistics_node(state)

        assert result.metadata.get("flight_search_possible") is False
        assert result.metadata.get("flight_search_status") == "skipped_disabled"
        assert result.metadata.get("flight_skip_reason") == "flights_disabled_in_settings"
        assert result.tiles["flights"] == []
        assert resolve_calls == [("", "Bali")]

    @pytest.mark.asyncio
    async def test_logistics_starts_aviasales_fetch_before_hotel_activity_search_finishes(
        self, monkeypatch: Any
    ) -> None:
        import importlib

        from app.config import settings as app_settings

        logistics_module = importlib.import_module("app.planner.nodes.logistics_node")

        state = GraphState(
            trip_plan=TripPlan(
                destination="Bali",
                origin="Amsterdam",
                start_date="2026-04-01",
                end_date="2026-04-07",
                currency="USD",
            )
        )
        state.tiles = {"hotels": [], "activities": [], "flights": []}
        state.metadata.update(
            {
                "trip_settings": {
                    "booking_types": {
                        "flights": "suggested",
                        "hotels": "suggested",
                        "activities": "on",
                    },
                    "flight_settings": {"direct_only": False, "round_trip": True},
                    "hotel_settings": {"min_stars": 0, "amenities": []},
                    "activity_settings": {"categories": ["diving"]},
                },
                "allow_flight_auto_upgrade": False,
            }
        )

        order: list[str] = []
        flight_started = asyncio.Event()
        release_flights = asyncio.Event()

        async def _fake_search_hotels_and_activities(
            state_arg: GraphState, _plan_arg: TripPlan
        ) -> None:
            order.append("hotels_start")
            await asyncio.wait_for(flight_started.wait(), timeout=0.1)
            order.append("flight_started_before_hotels_end")
            state_arg.tiles["hotels"] = [{"id": "hotel_1"}]
            state_arg.tiles["activities"] = [{"id": "act_1"}]
            release_flights.set()
            order.append("hotels_end")

        async def _fake_resolve_iata_codes(origin: str, destination: str, _state: GraphState):
            return "AMS", "DPS"

        async def _fake_search_aviasales_flights(**kwargs: Any):
            from app.services.aviasales_provider import FlightSearchResult

            order.append("flight_start")
            flight_started.set()
            await asyncio.wait_for(release_flights.wait(), timeout=0.1)
            order.append("flight_end")
            return FlightSearchResult()

        monkeypatch.setattr(app_settings, "aviasales_enabled", True)
        monkeypatch.setattr(
            logistics_module,
            "_search_hotels_and_activities",
            _fake_search_hotels_and_activities,
        )
        monkeypatch.setattr(logistics_module, "resolve_iata_codes", _fake_resolve_iata_codes)
        monkeypatch.setattr(
            logistics_module,
            "search_aviasales_flights",
            _fake_search_aviasales_flights,
        )
        monkeypatch.setattr(logistics_module, "_get_mock_flights", lambda *_args, **_kwargs: [])

        await logistics_module.logistics_node(state)

        assert order.index("flight_start") < order.index("hotels_end")
        assert "flight_started_before_hotels_end" in order


class TestBookingTypeOverrides:
    def test_merge_doc_settings_marks_explicit_flight_disable(self) -> None:
        from app.planner.coordinator import _merge_doc_settings

        state = _make_state(
            trip_settings={"booking_types": {"flights": "suggested", "hotels": "suggested"}}
        )

        _merge_doc_settings(state, {"booking_types": {"flights": "off", "hotels": "suggested"}})

        assert state["persistent_meta"]["user_disabled_booking_types"] == ["flights"]

    def test_merge_doc_settings_marks_explicit_flight_disable_from_unset(self) -> None:
        from app.planner.coordinator import _merge_doc_settings

        state = _make_state(trip_settings={"booking_types": {"hotels": "suggested"}})

        _merge_doc_settings(state, {"booking_types": {"flights": "off", "hotels": "suggested"}})

        assert state["persistent_meta"]["user_disabled_booking_types"] == ["flights"]

    def test_apply_classifier_keeps_explicitly_disabled_flights_off_when_origin_added(self) -> None:
        from app.planner.coordinator import _apply_classifier_to_state, _merge_doc_settings

        state = _make_state(
            trip_plan={"destination": "Bali", "start_date": "2026-04-01", "end_date": "2026-04-07"},
            trip_settings={"booking_types": {"hotels": "suggested"}},
        )
        _merge_doc_settings(state, {"booking_types": {"flights": "off", "hotels": "suggested"}})

        classifier = _make_classifier(
            change_type=ChangeType.LOGISTICS,
            origin="Rome",
            start_date="2026-04-01",
            end_date="2026-04-07",
        )
        _apply_classifier_to_state(state, classifier)

        assert state["trip_settings"]["booking_types"]["flights"] == "off"
        assert state["persistent_meta"]["user_disabled_booking_types"] == ["flights"]

    def test_merge_doc_settings_clears_explicit_flight_disable_when_reenabled(self) -> None:
        from app.planner.coordinator import _merge_doc_settings

        state = _make_state(
            trip_settings={"booking_types": {"flights": "off", "hotels": "suggested"}},
            persistent_meta={"user_disabled_booking_types": ["flights"]},
        )

        _merge_doc_settings(
            state,
            {"booking_types": {"flights": "suggested", "hotels": "suggested"}},
        )

        assert "user_disabled_booking_types" not in state["persistent_meta"]


class TestSearchTilesFlightAutoUpgrade:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("classifier_overrides", "state_overrides"),
        [
            (
                {"change_type": ChangeType.DAY_COUNT, "affects": ["diving"]},
                {
                    "trip_settings": {
                        "booking_types": {
                            "flights": "off",
                            "hotels": "suggested",
                            "activities": "suggested",
                        },
                        "activity_settings": {"categories": ["diving"]},
                    },
                    "strategy_sections": [
                        {
                            "specialist_type": "diving",
                            "constraints_applied": [],
                            "content_added": [],
                        }
                    ],
                },
            ),
            (
                {"change_type": ChangeType.DATE_CHANGE},
                {
                    "trip_settings": {
                        "booking_types": {
                            "flights": "off",
                            "hotels": "suggested",
                            "activities": "suggested",
                        }
                    }
                },
            ),
            (
                {
                    "change_type": ChangeType.PREFERENCE,
                    "activity_day_preferences": '{"diving": 3}',
                },
                {
                    "trip_settings": {
                        "booking_types": {
                            "flights": "off",
                            "hotels": "suggested",
                            "activities": "suggested",
                        },
                        "activity_settings": {"categories": ["diving"]},
                    },
                    "strategy_sections": [
                        {
                            "specialist_type": "diving",
                            "constraints_applied": [],
                            "content_added": [],
                        }
                    ],
                },
            ),
        ],
    )
    async def test_explicitly_disabled_flights_stay_off_during_internal_refreshes(
        self,
        monkeypatch: Any,
        classifier_overrides: Dict[str, Any],
        state_overrides: Dict[str, Any],
    ) -> None:
        import importlib

        from app.planner.coordinator import _search_tiles, _tile_refresh_types

        logistics_module = importlib.import_module("app.planner.nodes.logistics_node")
        classifier = _make_classifier(**classifier_overrides)
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "origin": "Rome",
                "start_date": "2026-04-01",
                "end_date": "2026-04-07",
            },
            persistent_meta={"user_disabled_booking_types": ["flights"]},
            **state_overrides,
        )

        async def _fake_logistics_node(graph_state: GraphState) -> GraphState:
            assert graph_state.metadata["allow_flight_auto_upgrade"] is False
            assert graph_state.metadata["trip_settings"]["booking_types"]["flights"] == "suggested"
            graph_state.tiles["flights"] = [{"id": "fresh_flight"}]
            trip_settings = graph_state.metadata.setdefault("trip_settings", {})
            booking_types = trip_settings.setdefault("booking_types", {})
            booking_types["flights"] = "suggested"
            return graph_state

        monkeypatch.setattr(logistics_module, "logistics_node", _fake_logistics_node)

        tiles = await _search_tiles(state, classifier, _tile_refresh_types(classifier, state))

        assert tiles.get("flights") in (None, [])
        assert state["trip_settings"]["booking_types"]["flights"] == "off"

    @patch("app.planner.services.state_serde.serialize_agent_state", return_value="{}")
    def test_build_envelope_hides_disabled_flight_tiles(self, _mock_serialize: Any) -> None:
        from app.planner.coordinator import _build_envelope

        state = _make_state(
            trip_plan={"destination": "Bali", "start_date": "2026-04-01", "end_date": "2026-04-07"},
            trip_settings={"booking_types": {"flights": "off", "hotels": "suggested"}},
            tiles={
                "flights": [{"id": "flight_1", "title": "Hidden Flight"}],
                "hotels": [{"id": "hotel_1", "title": "Visible Hotel"}],
            },
        )

        envelope = _build_envelope(state, "extend 10 days", "sess-1", "Updated trip")

        assert "flight_1" not in envelope["document"]["tiles"]
        assert "hotel_1" in envelope["document"]["tiles"]

    @pytest.mark.asyncio
    async def test_initial_plan_can_still_auto_enable_flights(self, monkeypatch: Any) -> None:
        import importlib

        from app.planner.coordinator import _search_tiles, _tile_refresh_types

        logistics_module = importlib.import_module("app.planner.nodes.logistics_node")
        classifier = _make_classifier(
            change_type=ChangeType.INITIAL_PLAN,
            destination="Bali",
            start_date="2026-04-01",
            end_date="2026-04-07",
        )
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "origin": "Rome",
                "start_date": "2026-04-01",
                "end_date": "2026-04-07",
            },
            trip_settings={"booking_types": {"flights": "off", "hotels": "suggested"}},
        )

        async def _fake_logistics_node(graph_state: GraphState) -> GraphState:
            assert graph_state.metadata["allow_flight_auto_upgrade"] is True
            graph_state.tiles["flights"] = [{"id": "fresh_flight"}]
            trip_settings = graph_state.metadata.setdefault("trip_settings", {})
            booking_types = trip_settings.setdefault("booking_types", {})
            booking_types["flights"] = "suggested"
            return graph_state

        monkeypatch.setattr(logistics_module, "logistics_node", _fake_logistics_node)

        await _search_tiles(state, classifier, _tile_refresh_types(classifier, state))

        assert state["trip_settings"]["booking_types"]["flights"] == "suggested"

    @pytest.mark.asyncio
    async def test_initial_plan_without_origin_keeps_internal_flight_refresh_off_in_state(
        self, monkeypatch: Any
    ) -> None:
        import importlib

        from app.planner.coordinator import _search_tiles, _tile_refresh_types

        logistics_module = importlib.import_module("app.planner.nodes.logistics_node")
        classifier = _make_classifier(
            change_type=ChangeType.INITIAL_PLAN,
            destination="Bali",
            start_date="2026-04-01",
            end_date="2026-04-07",
        )
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-04-01",
                "end_date": "2026-04-07",
            },
            trip_settings={"booking_types": {"flights": "off", "hotels": "suggested"}},
        )

        async def _fake_logistics_node(graph_state: GraphState) -> GraphState:
            assert graph_state.metadata["allow_flight_auto_upgrade"] is False
            assert graph_state.metadata["trip_settings"]["booking_types"]["flights"] == "suggested"
            trip_settings = graph_state.metadata.setdefault("trip_settings", {})
            booking_types = trip_settings.setdefault("booking_types", {})
            booking_types["flights"] = "suggested"
            return graph_state

        monkeypatch.setattr(logistics_module, "logistics_node", _fake_logistics_node)

        await _search_tiles(state, classifier, _tile_refresh_types(classifier, state))

        assert state["trip_settings"]["booking_types"]["flights"] == "off"

    @pytest.mark.asyncio
    async def test_date_change_carries_forward_preserved_specialist_tiles(
        self, monkeypatch: Any
    ) -> None:
        import importlib

        from app.planner.coordinator import _search_tiles, _tile_refresh_types

        logistics_module = importlib.import_module("app.planner.nodes.logistics_node")
        classifier = _make_classifier(change_type=ChangeType.DATE_CHANGE)
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "origin": "Rome",
                "start_date": "2026-03-01",
                "end_date": "2026-03-17",
            },
            trip_settings={"activity_settings": {"categories": ["diving", "hiking"]}},
            specialist_plans={
                "diving": {"day_plans": [{"day_number": 2, "location": "Tulamben"}]},
                "hiking": {"day_plans": []},
            },
            strategy_sections=[
                {"specialist_type": "diving", "content_added": [{"title": "Dive"}]},
                {"specialist_type": "hiking", "content_added": []},
            ],
            tiles={
                "activities": [
                    {
                        "id": "spec_bali_diving_keep",
                        "title": "Dive",
                        "type": "activity",
                        "source_agent": "vertical_specialist",
                        "provider": "viator",
                        "meta": {"specialist_type": "diving"},
                    },
                    {
                        "id": "spec_bali_hiking_drop",
                        "title": "Hike",
                        "type": "activity",
                        "source_agent": "vertical_specialist",
                        "provider": "viator",
                        "meta": {"specialist_type": "hiking"},
                    },
                ]
            },
            _pre_change_briefs={
                "trip_plan": {
                    "destination": "Bali",
                    "start_date": "2026-03-01",
                    "end_date": "2026-03-07",
                },
                "trip_settings": {"activity_settings": {"categories": ["diving", "hiking"]}},
            },
        )

        async def _fake_logistics_node(graph_state: GraphState) -> GraphState:
            graph_state.tiles["activities"] = [
                {"id": "browse_1", "title": "Market", "type": "activity"}
            ]
            return graph_state

        monkeypatch.setattr(logistics_module, "logistics_node", _fake_logistics_node)

        tiles = await _search_tiles(state, classifier, _tile_refresh_types(classifier, state))

        ids = {tile["id"] for tile in tiles["activities"]}
        assert ids == {"browse_1", "spec_bali_diving_keep"}
        preserved_tile = next(
            tile for tile in tiles["activities"] if tile["id"] == "spec_bali_diving_keep"
        )
        assert preserved_tile["provider"] == "viator"

    @pytest.mark.asyncio
    async def test_search_tiles_rehydrates_partner_fields_for_matching_places(
        self, monkeypatch: Any
    ) -> None:
        import importlib

        from app.planner.coordinator import _search_tiles, _tile_refresh_types

        logistics_module = importlib.import_module("app.planner.nodes.logistics_node")
        classifier = _make_classifier(change_type=ChangeType.DATE_CHANGE)
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "origin": "Rome",
                "start_date": "2026-04-01",
                "end_date": "2026-04-07",
            },
            tiles={
                "activities": [
                    {
                        "id": "browse_gp_spa",
                        "title": "Ubud Traditional Spa",
                        "type": "activity",
                        "google_place_id": "gp_spa_1",
                        "place_id": "gp_spa_1",
                        "provider": "viator",
                        "partner": "viator",
                        "partner_product_id": "115849P4",
                        "price_estimate": 27.35,
                        "live_price": 27.35,
                        "currency": "USD",
                        "price_basis": "per_person",
                        "is_estimate_only": False,
                        "rating": 5.0,
                        "review_count": 18,
                        "image_url": "https://cdn.example/spa.jpg",
                        "deeplink": "https://www.viator.com/tours/spa",
                        "deeplink_url": "https://www.viator.com/tours/spa",
                        "meta": {
                            "category": "spa",
                            "viator_product_code": "115849P4",
                        },
                    }
                ]
            },
        )

        async def _fake_logistics_node(graph_state: GraphState) -> GraphState:
            graph_state.tiles["activities"] = [
                {
                    "id": "browse_gp_spa",
                    "title": "Ubud Traditional Spa",
                    "type": "activity",
                    "google_place_id": "gp_spa_1",
                    "place_id": "gp_spa_1",
                    "provider": "google_places",
                    "price_estimate": 35.0,
                    "meta": {"category": "spa"},
                }
            ]
            graph_state.tiles["flights"] = []
            graph_state.tiles["hotels"] = []
            return graph_state

        monkeypatch.setattr(logistics_module, "logistics_node", _fake_logistics_node)

        tiles = await _search_tiles(state, classifier, _tile_refresh_types(classifier, state))

        tile = tiles["activities"][0]
        assert tile["provider"] == "viator"
        assert tile["partner"] == "viator"
        assert tile["partner_product_id"] == "115849P4"
        assert tile["price_estimate"] == 27.35
        assert tile["deeplink"] == "https://www.viator.com/tours/spa"
        assert tile["meta"]["viator_product_code"] == "115849P4"

    @pytest.mark.asyncio
    async def test_search_tiles_skips_ambiguous_title_only_partner_rehydration(
        self, monkeypatch: Any
    ) -> None:
        import importlib

        from app.planner.coordinator import _search_tiles, _tile_refresh_types

        logistics_module = importlib.import_module("app.planner.nodes.logistics_node")
        classifier = _make_classifier(change_type=ChangeType.DATE_CHANGE)
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "origin": "Rome",
                "start_date": "2026-04-01",
                "end_date": "2026-04-07",
            },
            tiles={
                "activities": [
                    {
                        "id": "prior_viator",
                        "title": "Shared Market Tour",
                        "type": "activity",
                        "provider": "viator",
                        "partner": "viator",
                        "partner_product_id": "V1",
                        "meta": {"viator_product_code": "V1"},
                    },
                    {
                        "id": "prior_gyg",
                        "title": "Shared Market Tour",
                        "type": "activity",
                        "provider": "gyg",
                        "partner": "gyg",
                        "partner_product_id": "G1",
                        "meta": {"gyg_tour_id": "G1"},
                    },
                ]
            },
        )

        async def _fake_logistics_node(graph_state: GraphState) -> GraphState:
            graph_state.tiles["activities"] = [
                {
                    "id": "fresh_market_tile",
                    "title": "Shared Market Tour",
                    "type": "activity",
                    "provider": "google_places",
                    "meta": {},
                }
            ]
            graph_state.tiles["flights"] = []
            graph_state.tiles["hotels"] = []
            return graph_state

        monkeypatch.setattr(logistics_module, "logistics_node", _fake_logistics_node)

        tiles = await _search_tiles(state, classifier, _tile_refresh_types(classifier, state))

        tile = tiles["activities"][0]
        assert tile["provider"] == "google_places"
        assert tile.get("partner_product_id") is None
        assert tile.get("partner") is None
        assert tile.get("meta") == {}

    @pytest.mark.asyncio
    async def test_search_tiles_skips_same_place_partner_rehydration_on_category_mismatch(
        self, monkeypatch: Any
    ) -> None:
        import importlib

        from app.planner.coordinator import _search_tiles, _tile_refresh_types

        logistics_module = importlib.import_module("app.planner.nodes.logistics_node")
        classifier = _make_classifier(change_type=ChangeType.DATE_CHANGE)
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "origin": "Rome",
                "start_date": "2026-04-01",
                "end_date": "2026-04-07",
            },
            tiles={
                "activities": [
                    {
                        "id": "browse_gp_place",
                        "title": "Shared Place",
                        "type": "activity",
                        "google_place_id": "gp_shared_1",
                        "place_id": "gp_shared_1",
                        "provider": "viator",
                        "partner": "viator",
                        "partner_product_id": "SPA1",
                        "meta": {
                            "category": "spa",
                            "viator_product_code": "SPA1",
                        },
                        "browse_category": "spa",
                    }
                ]
            },
        )

        async def _fake_logistics_node(graph_state: GraphState) -> GraphState:
            graph_state.tiles["activities"] = [
                {
                    "id": "browse_gp_place",
                    "title": "Shared Place",
                    "type": "activity",
                    "google_place_id": "gp_shared_1",
                    "place_id": "gp_shared_1",
                    "provider": "google_places",
                    "category": "cultural",
                    "browse_category": "cultural",
                    "meta": {"category": "cultural"},
                }
            ]
            graph_state.tiles["flights"] = []
            graph_state.tiles["hotels"] = []
            return graph_state

        monkeypatch.setattr(logistics_module, "logistics_node", _fake_logistics_node)

        tiles = await _search_tiles(state, classifier, _tile_refresh_types(classifier, state))

        tile = tiles["activities"][0]
        assert tile["provider"] == "google_places"
        assert tile["category"] == "cultural"
        assert tile["browse_category"] == "cultural"
        assert tile.get("partner_product_id") is None
        assert tile.get("partner") is None
        assert tile["meta"] == {"category": "cultural"}


class TestExecuteTurn:
    @pytest.mark.asyncio
    async def test_dispatch_specialists_step_streams_each_completed_specialist_in_requested_order(
        self, monkeypatch: Any
    ) -> None:
        import app.planner.coordinator as coordinator_module

        classifier = _make_classifier(
            intent="PLANNING",
            change_type=ChangeType.INITIAL_PLAN,
            destination="Bali",
            start_date="2026-04-01",
            end_date="2026-04-07",
        )
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-04-01",
                "end_date": "2026-04-07",
            },
            trip_settings={"activity_settings": {"categories": ["diving", "hiking"]}},
        )

        async def _fake_dispatch_specialists_parallel(*_args: Any, **_kwargs: Any):
            yield (
                "hiking",
                {
                    "activities": [],
                    "constraints": [],
                    "editorial": "Volcano ridge plan",
                    "feasibility_status": "feasible",
                },
            )
            await asyncio.sleep(0.02)
            yield (
                "diving",
                {
                    "activities": [],
                    "constraints": [],
                    "editorial": "Warm-water dive plan",
                    "feasibility_status": "feasible",
                },
            )

        monkeypatch.setattr(
            coordinator_module,
            "_dispatch_specialists_parallel",
            _fake_dispatch_specialists_parallel,
        )
        monkeypatch.setattr(
            coordinator_module,
            "_llm_output_to_plan_dict",
            lambda topic, *_args, **_kwargs: {
                "topic": topic,
                "day_plans": [],
                "constraints": [],
                "feasibility_status": "feasible",
            },
        )
        monkeypatch.setattr(
            coordinator_module,
            "_plan_to_strategy_section",
            lambda topic, *_args, **_kwargs: {
                "id": f"section_{topic}",
                "specialist_type": topic,
                "title": f"{topic.title()} Bali",
                "one_liner": f"{topic.title()} highlights",
                "hero_image": f"https://images.test/{topic}.jpg",
                "feasibility_status": "feasible",
                "content_added": [{"title": f"{topic.title()} highlight"}],
            },
        )
        monkeypatch.setattr(
            coordinator_module,
            "_refresh_preserved_specialist_section_metadata",
            lambda *_args, **_kwargs: None,
        )

        step_result = await coordinator_module._execute_step(
            ExecutionStep(
                step_type=StepType.DISPATCH_SPECIALISTS,
                params={"topics": ["diving", "hiking"]},
            ),
            state,
            classifier,
            "build my itinerary",
            session_id="session-123",
        )

        assert hasattr(step_result, "__aiter__")

        first_event = await asyncio.wait_for(anext(step_result), timeout=0.01)
        assert first_event["data"]["kind"] == "specialist_preview"
        first_preview = first_event["data"]["payload"]
        assert first_preview["destination"] == "Bali"
        assert first_preview["topics"] == ["diving", "hiking"]
        assert first_preview["activities"] == [
            {
                "title": "Hiking highlight",
                "day": None,
                "specialist_type": "hiking",
                "duration_hours": 3,
                "description": None,
                "image_url": None,
                "coordinates": None,
            }
        ]
        assert [section["specialist_type"] for section in first_preview["sections"]] == ["hiking"]

        second_event = await asyncio.wait_for(anext(step_result), timeout=0.01)
        assert second_event["data"]["kind"] == "strategy_sections"
        assert [section["specialist_type"] for section in second_event["data"]["payload"]] == [
            "hiking"
        ]

        third_event = await asyncio.wait_for(anext(step_result), timeout=0.05)
        assert third_event["data"]["kind"] == "specialist_preview"
        assert [
            activity["specialist_type"] for activity in third_event["data"]["payload"]["activities"]
        ] == [
            "diving",
            "hiking",
        ]
        assert [
            section["specialist_type"] for section in third_event["data"]["payload"]["sections"]
        ] == [
            "diving",
            "hiking",
        ]

        fourth_event = await asyncio.wait_for(anext(step_result), timeout=0.01)
        assert fourth_event["data"]["kind"] == "strategy_sections"
        assert [section["specialist_type"] for section in fourth_event["data"]["payload"]] == [
            "diving",
            "hiking",
        ]

        with pytest.raises(StopAsyncIteration):
            await anext(step_result)

        assert list(state["specialist_plans"]) == ["diving", "hiking"]
        assert [section["specialist_type"] for section in state["strategy_sections"]] == [
            "diving",
            "hiking",
        ]

    @pytest.mark.asyncio
    async def test_dispatch_specialists_step_emits_empty_preview_when_all_dispatched_specialists_fail(
        self, monkeypatch: Any
    ) -> None:
        import app.planner.coordinator as coordinator_module

        classifier = _make_classifier(
            intent="PLANNING",
            change_type=ChangeType.INITIAL_PLAN,
            destination="Bali",
            start_date="2026-04-01",
            end_date="2026-04-07",
        )
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-04-01",
                "end_date": "2026-04-07",
            },
            trip_settings={"activity_settings": {"categories": ["diving", "hiking"]}},
        )

        async def _fake_dispatch_specialists_parallel(*_args: Any, **_kwargs: Any):
            yield "diving", None
            yield "hiking", None

        monkeypatch.setattr(
            coordinator_module,
            "_dispatch_specialists_parallel",
            _fake_dispatch_specialists_parallel,
        )
        monkeypatch.setattr(
            coordinator_module,
            "_refresh_preserved_specialist_section_metadata",
            lambda *_args, **_kwargs: None,
        )

        step_result = await coordinator_module._execute_step(
            ExecutionStep(
                step_type=StepType.DISPATCH_SPECIALISTS,
                params={"topics": ["diving", "hiking"]},
            ),
            state,
            classifier,
            "build my itinerary",
            session_id="session-123",
        )
        events = await _collect_step_events(step_result)

        assert [event["data"]["kind"] for event in events] == [
            "specialist_preview",
            "strategy_sections",
        ]
        preview_payload = events[0]["data"]["payload"]
        assert preview_payload["topics"] == ["diving", "hiking"]
        assert preview_payload["sections"] == []
        assert events[1]["data"]["payload"] == []
        assert state["specialist_plans"] == {}
        assert state["strategy_sections"] == []

    @pytest.mark.asyncio
    async def test_execute_turn_streams_parallel_step_partials_and_completed_statuses_as_each_step_finishes(
        self, monkeypatch: Any
    ) -> None:
        import app.planner.coordinator as coordinator_module
        import app.planner.nodes.router_extraction as router_module
        import app.planner.services.feasibility_service as feasibility_module
        import app.services.unsplash as unsplash_module

        classifier = _make_classifier(
            intent="PLANNING",
            change_type=ChangeType.INITIAL_PLAN,
            destination="Bali",
        )
        plan = ExecutionPlan(
            reason="parallel partial streaming",
            steps=[
                ExecutionStep(
                    step_type=StepType.DISPATCH_SPECIALISTS,
                    params={"topics": ["diving"]},
                ),
                ExecutionStep(
                    step_type=StepType.SEARCH_TILES,
                    params={"tile_types": ["activities"]},
                    parallel_with=StepType.DISPATCH_SPECIALISTS,
                ),
                ExecutionStep(step_type=StepType.GENERATE_RESPONSE, params={}),
            ],
            estimated_llm_calls=1,
        )
        state = _make_state(
            trip_plan={"destination": "Bali"},
            trip_settings={},
            messages=[],
        )

        async def _fake_execute_step(
            step: ExecutionStep,
            _state_arg: Dict[str, Any],
            _classifier: ClassifierOutput,
            _user_message: str,
            session_id: str = "",
        ) -> Any:
            assert session_id == "session-123"
            if step.step_type == StepType.DISPATCH_SPECIALISTS:

                async def _stream_specialist_events():
                    await asyncio.sleep(0)
                    yield {
                        "type": "partial",
                        "data": {
                            "kind": "specialist_preview",
                            "payload": {
                                "destination": "Bali",
                                "topics": ["diving"],
                                "activities": [
                                    {
                                        "title": "Dive highlight",
                                        "day": 1,
                                        "specialist_type": "diving",
                                        "duration_hours": 3,
                                        "description": None,
                                        "image_url": None,
                                        "coordinates": None,
                                    }
                                ],
                                "sections": [{"specialist_type": "diving"}],
                            },
                        },
                    }
                    await asyncio.sleep(0)
                    yield {
                        "type": "partial",
                        "data": {
                            "kind": "strategy_sections",
                            "payload": [{"specialist_type": "diving", "content_added": []}],
                        },
                    }

                return _stream_specialist_events()
            if step.step_type == StepType.SEARCH_TILES:
                await asyncio.sleep(0.01)
                return {
                    "type": "partial",
                    "data": {
                        "kind": "tiles",
                        "payload": {
                            "tile_1": {
                                "id": "tile_1",
                                "type": "activity",
                                "title": "Dive",
                            }
                        },
                    },
                }
            return None

        async def _fake_generate_response_streaming(*args: Any, **kwargs: Any):
            yield "done"

        def _fake_build_envelope(
            state_arg: Dict[str, Any],
            user_message: str,
            session_id: str,
            assistant_message: str,
        ) -> Dict[str, Any]:
            return {
                "document": {
                    "day_cards": list(state_arg.get("day_cards", [])),
                    "trip_inputs": dict(state_arg.get("trip_plan", {})),
                },
                "assistant_message": assistant_message,
                "session_state": {"trip_plan": dict(state_arg.get("trip_plan", {}))},
            }

        monkeypatch.setattr(router_module, "classify_change", AsyncMock(return_value=classifier))
        monkeypatch.setattr(coordinator_module, "plan_turn", lambda *_args, **_kwargs: plan)
        monkeypatch.setattr(coordinator_module, "_execute_step", _fake_execute_step)
        monkeypatch.setattr(
            coordinator_module,
            "_generate_response_streaming",
            _fake_generate_response_streaming,
        )
        monkeypatch.setattr(coordinator_module, "_refresh_enrichment_states", AsyncMock())
        monkeypatch.setattr(coordinator_module, "_build_envelope", _fake_build_envelope)
        monkeypatch.setattr(
            feasibility_module,
            "batch_feasibility_precheck",
            AsyncMock(return_value={}),
        )
        monkeypatch.setattr(
            unsplash_module,
            "prefetch_destination_images",
            AsyncMock(return_value=None),
        )

        events = [
            event
            async for event in execute_turn(
                "build my itinerary",
                state,
                session_id="session-123",
            )
        ]

        partial_kinds = [event["data"]["kind"] for event in events if event["type"] == "partial"]
        preview_index = partial_kinds.index("specialist_preview")
        strategy_index = partial_kinds.index("strategy_sections")
        tiles_index = partial_kinds.index("tiles")
        assert preview_index < tiles_index
        assert strategy_index < tiles_index

        completed_nodes = [
            event["data"]["node"]
            for event in events
            if event["type"] == "node_status" and event["data"]["status"] == "completed"
        ]
        specialist_completed_index = completed_nodes.index("get_specialist_advice")
        tiles_completed_index = completed_nodes.index("search_tiles")
        assert specialist_completed_index < tiles_completed_index

    @pytest.mark.asyncio
    async def test_execute_turn_streams_sequential_async_generator_step_before_completed_status(
        self, monkeypatch: Any
    ) -> None:
        import app.planner.coordinator as coordinator_module
        import app.planner.nodes.router_extraction as router_module
        import app.planner.services.feasibility_service as feasibility_module
        import app.services.unsplash as unsplash_module

        classifier = _make_classifier(
            intent="PLANNING",
            change_type=ChangeType.INITIAL_PLAN,
            destination="Bali",
        )
        plan = ExecutionPlan(
            reason="sequential streamed step",
            steps=[
                ExecutionStep(
                    step_type=StepType.DISPATCH_SPECIALISTS,
                    params={"topics": ["diving"]},
                ),
                ExecutionStep(step_type=StepType.GENERATE_RESPONSE, params={}),
            ],
            estimated_llm_calls=1,
        )
        state = _make_state(
            trip_plan={"destination": "Bali"},
            trip_settings={},
            messages=[],
        )

        async def _fake_execute_step(
            step: ExecutionStep,
            _state_arg: Dict[str, Any],
            _classifier: ClassifierOutput,
            _user_message: str,
            session_id: str = "",
        ) -> Any:
            assert session_id == "session-123"
            if step.step_type != StepType.DISPATCH_SPECIALISTS:
                return None

            async def _stream_specialist_events():
                await asyncio.sleep(0)
                yield {
                    "type": "partial",
                    "data": {
                        "kind": "specialist_preview",
                        "payload": {
                            "destination": "Bali",
                            "topics": ["diving"],
                            "activities": [
                                {
                                    "title": "Dive highlight",
                                    "day": 1,
                                    "specialist_type": "diving",
                                    "duration_hours": 3,
                                    "description": None,
                                    "image_url": None,
                                    "coordinates": None,
                                }
                            ],
                            "sections": [{"specialist_type": "diving"}],
                        },
                    },
                }
                await asyncio.sleep(0)
                yield {
                    "type": "partial",
                    "data": {
                        "kind": "strategy_sections",
                        "payload": [{"specialist_type": "diving", "content_added": []}],
                    },
                }

            return _stream_specialist_events()

        async def _fake_generate_response_streaming(*args: Any, **kwargs: Any):
            yield "done"

        def _fake_build_envelope(
            state_arg: Dict[str, Any],
            user_message: str,
            session_id: str,
            assistant_message: str,
        ) -> Dict[str, Any]:
            return {
                "document": {
                    "day_cards": list(state_arg.get("day_cards", [])),
                    "trip_inputs": dict(state_arg.get("trip_plan", {})),
                },
                "assistant_message": assistant_message,
                "session_state": {"trip_plan": dict(state_arg.get("trip_plan", {}))},
            }

        monkeypatch.setattr(router_module, "classify_change", AsyncMock(return_value=classifier))
        monkeypatch.setattr(coordinator_module, "plan_turn", lambda *_args, **_kwargs: plan)
        monkeypatch.setattr(coordinator_module, "_execute_step", _fake_execute_step)
        monkeypatch.setattr(
            coordinator_module,
            "_generate_response_streaming",
            _fake_generate_response_streaming,
        )
        monkeypatch.setattr(coordinator_module, "_refresh_enrichment_states", AsyncMock())
        monkeypatch.setattr(coordinator_module, "_build_envelope", _fake_build_envelope)
        monkeypatch.setattr(
            feasibility_module,
            "batch_feasibility_precheck",
            AsyncMock(return_value={}),
        )
        monkeypatch.setattr(
            unsplash_module,
            "prefetch_destination_images",
            AsyncMock(return_value=None),
        )

        events = [
            event
            async for event in execute_turn(
                "build my itinerary",
                state,
                session_id="session-123",
            )
        ]

        partial_kinds = [event["data"]["kind"] for event in events if event["type"] == "partial"]
        assert partial_kinds == ["trip_inputs", "specialist_preview", "strategy_sections"]

        specialist_started_index = next(
            idx
            for idx, event in enumerate(events)
            if event["type"] == "node_status"
            and event["data"]["node"] == "get_specialist_advice"
            and event["data"]["status"] == "started"
        )
        preview_index = next(
            idx
            for idx, event in enumerate(events)
            if event["type"] == "partial" and event["data"]["kind"] == "specialist_preview"
        )
        strategy_index = next(
            idx
            for idx, event in enumerate(events)
            if event["type"] == "partial" and event["data"]["kind"] == "strategy_sections"
        )
        specialist_completed_index = next(
            idx
            for idx, event in enumerate(events)
            if event["type"] == "node_status"
            and event["data"]["node"] == "get_specialist_advice"
            and event["data"]["status"] == "completed"
        )
        response_started_index = next(
            idx
            for idx, event in enumerate(events)
            if event["type"] == "node_status"
            and event["data"]["node"] == "response"
            and event["data"]["status"] == "started"
        )
        assert (
            specialist_started_index
            < preview_index
            < strategy_index
            < specialist_completed_index
            < response_started_index
        )
        assert events[-1]["type"] == "complete"

    @pytest.mark.asyncio
    async def test_execute_turn_early_close_cancels_parallel_async_generator_tasks(
        self, monkeypatch: Any
    ) -> None:
        import importlib

        import app.db as db_module
        import app.planner.coordinator as coordinator_module
        import app.planner.nodes.router_extraction as router_module
        import app.planner.services.feasibility_service as feasibility_module
        import app.services.unsplash as unsplash_module

        classifier = _make_classifier(
            intent="PLANNING",
            change_type=ChangeType.INITIAL_PLAN,
            destination="Bali",
            start_date="2026-04-01",
            end_date="2026-04-07",
        )
        plan = ExecutionPlan(
            reason="parallel cleanup",
            steps=[
                ExecutionStep(
                    step_type=StepType.DISPATCH_SPECIALISTS,
                    params={"topics": ["diving", "hiking"]},
                ),
                ExecutionStep(
                    step_type=StepType.SEARCH_TILES,
                    params={"tile_types": ["activities"]},
                    parallel_with=StepType.DISPATCH_SPECIALISTS,
                ),
                ExecutionStep(step_type=StepType.GENERATE_RESPONSE, params={}),
            ],
            estimated_llm_calls=1,
        )
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-04-01",
                "end_date": "2026-04-07",
            },
            trip_settings={"activity_settings": {"categories": ["diving", "hiking"]}},
            messages=[],
        )
        hiking_started = asyncio.Event()
        hiking_release = asyncio.Event()
        hiking_cancelled = asyncio.Event()
        search_started = asyncio.Event()
        search_release = asyncio.Event()
        search_cancelled = asyncio.Event()
        unsplash_started = asyncio.Event()
        unsplash_release = asyncio.Event()
        unsplash_cancelled = asyncio.Event()
        turn_stream = None

        class _FakeSpecialistOutput:
            def __init__(self, payload: Dict[str, Any]) -> None:
                self._payload = payload

            def model_dump(self) -> Dict[str, Any]:
                return dict(self._payload)

        class _DummyAsyncSession:
            async def __aenter__(self) -> object:
                return object()

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
                return None

        async def _fake_dispatch_specialist_with_brief(*, topic: str, **_kwargs: Any) -> Any:
            if topic == "diving":
                await asyncio.sleep(0)
                return _FakeSpecialistOutput(
                    {
                        "activities": [],
                        "constraints": [],
                        "editorial": "Warm-water dive plan",
                        "feasibility_status": "feasible",
                    }
                )

            hiking_started.set()
            try:
                await hiking_release.wait()
            except asyncio.CancelledError:
                hiking_cancelled.set()
                raise

            return _FakeSpecialistOutput(
                {
                    "activities": [],
                    "constraints": [],
                    "editorial": "Volcano ridge plan",
                    "feasibility_status": "feasible",
                }
            )

        async def _fake_search_tiles(*_args: Any, **_kwargs: Any) -> Dict[str, Any]:
            search_started.set()
            try:
                await search_release.wait()
            except asyncio.CancelledError:
                search_cancelled.set()
                raise

            return {"activities": []}

        async def _fake_generate_response_streaming(*args: Any, **kwargs: Any):
            yield "done"

        async def _fake_prefetch_destination_images(_destination: str) -> None:
            unsplash_started.set()
            try:
                await unsplash_release.wait()
            except asyncio.CancelledError:
                unsplash_cancelled.set()
                raise

        vertical_specialist_module = importlib.import_module(
            "app.planner.nodes.vertical_specialist"
        )

        monkeypatch.setattr(router_module, "classify_change", AsyncMock(return_value=classifier))
        monkeypatch.setattr(coordinator_module, "plan_turn", lambda *_args, **_kwargs: plan)
        monkeypatch.setattr(db_module, "_get_async_session_factory", lambda: _DummyAsyncSession)
        monkeypatch.setattr(
            vertical_specialist_module,
            "dispatch_specialist_with_brief",
            _fake_dispatch_specialist_with_brief,
        )
        monkeypatch.setattr(coordinator_module, "_search_tiles", _fake_search_tiles)
        monkeypatch.setattr(
            coordinator_module,
            "_llm_output_to_plan_dict",
            lambda topic, *_args, **_kwargs: {
                "topic": topic,
                "day_plans": [],
                "constraints": [],
                "feasibility_status": "feasible",
            },
        )
        monkeypatch.setattr(
            coordinator_module,
            "_plan_to_strategy_section",
            lambda topic, *_args, **_kwargs: {
                "id": f"section_{topic}",
                "specialist_type": topic,
                "title": f"{topic.title()} Bali",
                "one_liner": f"{topic.title()} highlights",
                "hero_image": f"https://images.test/{topic}.jpg",
                "feasibility_status": "feasible",
                "content_added": [{"title": f"{topic.title()} highlight"}],
            },
        )
        monkeypatch.setattr(
            coordinator_module,
            "_refresh_preserved_specialist_section_metadata",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            coordinator_module,
            "_generate_response_streaming",
            _fake_generate_response_streaming,
        )
        monkeypatch.setattr(coordinator_module, "_refresh_enrichment_states", AsyncMock())
        monkeypatch.setattr(
            feasibility_module,
            "batch_feasibility_precheck",
            AsyncMock(return_value={}),
        )
        monkeypatch.setattr(
            unsplash_module,
            "prefetch_destination_images",
            _fake_prefetch_destination_images,
        )

        try:
            turn_stream = execute_turn(
                "build my itinerary",
                state,
                session_id="session-123",
            )

            preview_event = None
            while True:
                event = await asyncio.wait_for(anext(turn_stream), timeout=0.1)
                if event["type"] == "partial" and event["data"]["kind"] == "specialist_preview":
                    preview_event = event
                    break

            await asyncio.wait_for(hiking_started.wait(), timeout=0.1)
            await asyncio.wait_for(search_started.wait(), timeout=0.1)
            await asyncio.wait_for(unsplash_started.wait(), timeout=0.1)

            await turn_stream.aclose()

            await asyncio.wait_for(hiking_cancelled.wait(), timeout=0.1)
            await asyncio.wait_for(search_cancelled.wait(), timeout=0.1)
            await asyncio.wait_for(unsplash_cancelled.wait(), timeout=0.1)
        finally:
            hiking_release.set()
            search_release.set()
            unsplash_release.set()
            if turn_stream is not None:
                await turn_stream.aclose()
            await asyncio.sleep(0)

        assert preview_event is not None
        assert preview_event["data"]["payload"]["topics"] == ["diving", "hiking"]
        assert [
            section["specialist_type"] for section in preview_event["data"]["payload"]["sections"]
        ] == ["diving"]

    @pytest.mark.asyncio
    async def test_execute_turn_records_parallel_failures_without_blocking_successful_partials(
        self, monkeypatch: Any
    ) -> None:
        import app.planner.coordinator as coordinator_module
        import app.planner.nodes.router_extraction as router_module
        import app.planner.services.feasibility_service as feasibility_module
        import app.services.unsplash as unsplash_module

        classifier = _make_classifier(
            intent="PLANNING",
            change_type=ChangeType.INITIAL_PLAN,
            destination="Bali",
        )
        plan = ExecutionPlan(
            reason="parallel partial failure",
            steps=[
                ExecutionStep(
                    step_type=StepType.DISPATCH_SPECIALISTS,
                    params={"topics": ["diving"]},
                ),
                ExecutionStep(
                    step_type=StepType.SEARCH_TILES,
                    params={"tile_types": ["activities"]},
                    parallel_with=StepType.DISPATCH_SPECIALISTS,
                ),
                ExecutionStep(step_type=StepType.GENERATE_RESPONSE, params={}),
            ],
            estimated_llm_calls=1,
        )
        state = _make_state(
            trip_plan={"destination": "Bali"},
            trip_settings={},
            messages=[],
        )

        async def _fake_execute_step(
            step: ExecutionStep,
            _state_arg: Dict[str, Any],
            _classifier: ClassifierOutput,
            _user_message: str,
            session_id: str = "",
        ) -> Any:
            assert session_id == "session-123"
            if step.step_type == StepType.DISPATCH_SPECIALISTS:
                await asyncio.sleep(0)
                return [
                    {
                        "type": "partial",
                        "data": {
                            "kind": "specialist_preview",
                            "payload": {
                                "destination": "Bali",
                                "topics": ["diving"],
                                "activities": [
                                    {
                                        "title": "Dive highlight",
                                        "day": 1,
                                        "specialist_type": "diving",
                                        "duration_hours": 3,
                                        "description": None,
                                        "image_url": None,
                                        "coordinates": None,
                                    }
                                ],
                                "sections": [{"specialist_type": "diving"}],
                            },
                        },
                    },
                    {
                        "type": "partial",
                        "data": {
                            "kind": "strategy_sections",
                            "payload": [{"specialist_type": "diving", "content_added": []}],
                        },
                    },
                ]
            if step.step_type == StepType.SEARCH_TILES:
                await asyncio.sleep(0.01)
                raise RuntimeError("tile provider timeout")
            return None

        async def _fake_generate_response_streaming(*args: Any, **kwargs: Any):
            yield "done"

        def _fake_build_envelope(
            state_arg: Dict[str, Any],
            user_message: str,
            session_id: str,
            assistant_message: str,
        ) -> Dict[str, Any]:
            return {
                "document": {
                    "day_cards": list(state_arg.get("day_cards", [])),
                    "trip_inputs": dict(state_arg.get("trip_plan", {})),
                },
                "assistant_message": assistant_message,
                "session_state": {"trip_plan": dict(state_arg.get("trip_plan", {}))},
            }

        monkeypatch.setattr(router_module, "classify_change", AsyncMock(return_value=classifier))
        monkeypatch.setattr(coordinator_module, "plan_turn", lambda *_args, **_kwargs: plan)
        monkeypatch.setattr(coordinator_module, "_execute_step", _fake_execute_step)
        monkeypatch.setattr(
            coordinator_module,
            "_generate_response_streaming",
            _fake_generate_response_streaming,
        )
        monkeypatch.setattr(coordinator_module, "_refresh_enrichment_states", AsyncMock())
        monkeypatch.setattr(coordinator_module, "_build_envelope", _fake_build_envelope)
        monkeypatch.setattr(
            feasibility_module,
            "batch_feasibility_precheck",
            AsyncMock(return_value={}),
        )
        monkeypatch.setattr(
            unsplash_module,
            "prefetch_destination_images",
            AsyncMock(return_value=None),
        )

        events = [
            event
            async for event in execute_turn(
                "build my itinerary",
                state,
                session_id="session-123",
            )
        ]

        partial_kinds = [event["data"]["kind"] for event in events if event["type"] == "partial"]
        assert partial_kinds == ["trip_inputs", "specialist_preview", "strategy_sections"]
        assert state["turn_meta"]["partial_failures"] == ["search_tiles"]

        completed_nodes = [
            event["data"]["node"]
            for event in events
            if event["type"] == "node_status" and event["data"]["status"] == "completed"
        ]
        specialist_completed_index = completed_nodes.index("get_specialist_advice")
        tiles_completed_index = completed_nodes.index("search_tiles")
        assert specialist_completed_index < tiles_completed_index
        assert events[-1]["type"] == "complete"

    @pytest.mark.asyncio
    async def test_build_itinerary_step_emits_day_cards_partial_before_tile_partial(
        self, monkeypatch: Any
    ) -> None:
        import app.planner.coordinator as coordinator_module

        classifier = _make_classifier()
        state = _make_state(
            tiles={"activities": [{"id": "existing_activity", "type": "activity"}]},
            turn_meta={"tiles_replaced": True},
        )
        day_cards = [{"day_number": 1, "label": "Arrival", "blocks": []}]

        async def _fake_build_itinerary(
            state_arg: Dict[str, Any],
            session_id: str = "",
        ) -> list[Dict[str, Any]]:
            assert session_id == "session-123"
            state_arg["day_cards"] = list(day_cards)
            state_arg["turn_meta"] = {
                "tiles_replaced": True,
                "builder_result": {
                    "success": True,
                    "activities_placed": 1,
                    "activities_dropped": 0,
                    "conflicts": [],
                    "resolutions": [],
                    "warnings": ["Low supply for day 1"],
                    "overview": {"duration_label": "1 day"},
                    "assumptions": {"pace": "balanced"},
                },
            }
            state_arg["tiles"] = {
                "activities": [
                    {"id": "existing_activity", "type": "activity"},
                    {"id": "new_specialist_tile", "type": "activity"},
                ]
            }
            return list(day_cards)

        monkeypatch.setattr(coordinator_module, "_build_itinerary", _fake_build_itinerary)

        events = await coordinator_module._execute_step(
            ExecutionStep(step_type=StepType.BUILD_ITINERARY, params={}),
            state,
            classifier,
            "build it",
            session_id="session-123",
        )

        assert isinstance(events, list)
        assert events[0]["data"]["kind"] == "day_cards"
        assert events[0]["data"]["payload"] == {
            "day_cards": day_cards,
            "tiles": {
                "existing_activity": {
                    "id": "existing_activity",
                    "type": "activity",
                    "category": "activity",
                },
                "new_specialist_tile": {
                    "id": "new_specialist_tile",
                    "type": "activity",
                    "category": "activity",
                },
            },
            "strategy_sections": [],
            "plan_view_state": "S3_ITINERARY_READY",
            "itinerary_overview": {"duration_label": "1 day"},
            "itinerary_assumptions": {"pace": "balanced"},
            "warnings": ["Low supply for day 1"],
        }
        assert events[1]["data"]["kind"] == "tiles"
        assert events[1]["data"]["tiles_replaced"] is True

    @pytest.mark.asyncio
    async def test_build_itinerary_step_emits_empty_day_cards_partial_when_builder_clears_them(
        self, monkeypatch: Any
    ) -> None:
        import app.planner.coordinator as coordinator_module

        classifier = _make_classifier()
        state = _make_state(
            day_cards=[{"day_number": 1, "label": "Stale itinerary", "blocks": []}],
            tiles={"activities": [{"id": "existing_activity", "type": "activity"}]},
        )

        async def _fake_build_itinerary(
            state_arg: Dict[str, Any],
            session_id: str = "",
        ) -> list[Dict[str, Any]]:
            assert session_id == "session-123"
            state_arg["day_cards"] = []
            return []

        monkeypatch.setattr(coordinator_module, "_build_itinerary", _fake_build_itinerary)

        events = await coordinator_module._execute_step(
            ExecutionStep(step_type=StepType.BUILD_ITINERARY, params={}),
            state,
            classifier,
            "build it",
            session_id="session-123",
        )

        assert events == {
            "type": "partial",
            "data": {
                "kind": "day_cards",
                "payload": {
                    "day_cards": [],
                    "tiles": {
                        "existing_activity": {
                            "id": "existing_activity",
                            "type": "activity",
                            "category": "activity",
                        }
                    },
                    "strategy_sections": [],
                    "plan_view_state": "S3_BLOCKED",
                },
            },
        }

    @pytest.mark.asyncio
    async def test_execute_turn_finalizes_deferred_itinerary_enrichment_after_response(
        self, monkeypatch: Any
    ) -> None:
        import app.planner.coordinator as coordinator_module
        import app.planner.nodes.router_extraction as router_module
        import app.planner.services.feasibility_service as feasibility_module
        import app.services.unsplash as unsplash_module

        classifier = _make_classifier(
            intent="PLANNING",
            change_type=ChangeType.INITIAL_PLAN,
            destination="Bali",
            start_date="2026-04-01",
            end_date="2026-04-07",
        )
        plan = ExecutionPlan(
            reason="test build path",
            steps=[
                ExecutionStep(step_type=StepType.BUILD_ITINERARY, params={}),
                ExecutionStep(step_type=StepType.GENERATE_RESPONSE, params={}),
            ],
            estimated_llm_calls=1,
        )
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-04-01",
                "end_date": "2026-04-07",
            },
            trip_settings={"activity_settings": {"categories": ["diving"]}},
            messages=[],
        )
        order: list[str] = []

        async def _fake_execute_step(
            step: ExecutionStep,
            state_arg: Dict[str, Any],
            _classifier: ClassifierOutput,
            _user_message: str,
            session_id: str = "",
        ) -> Any:
            if step.step_type != StepType.BUILD_ITINERARY:
                return None

            state_arg["day_cards"] = [{"day_number": 1, "blocks": [{"summary": "Dive"}]}]
            state_arg["tiles"] = {"activities": [{"id": "tile_1", "title": "Dive"}]}

            async def _pending() -> Dict[str, Any]:
                order.append("enrichment_started")
                await asyncio.sleep(0)
                order.append("enrichment_finished")
                return {
                    "activities": [{"id": "tile_1", "title": "Dive", "provider": "viator"}],
                    "day_cards": [
                        {
                            "day_number": 1,
                            "blocks": [{"summary": "Dive", "deeplink": "https://viator.test"}],
                        }
                    ],
                }

            state_arg["_pending_itinerary_enrichment_task"] = asyncio.create_task(_pending())
            return {
                "type": "partial",
                "data": {
                    "kind": "day_cards",
                    "payload": {
                        "day_cards": state_arg["day_cards"],
                        "tiles": {"tile_1": {"id": "tile_1", "title": "Dive"}},
                        "strategy_sections": [],
                        "plan_view_state": "S3_ITINERARY_READY",
                    },
                },
            }

        async def _fake_generate_response_streaming(*args: Any, **kwargs: Any):
            order.append("response_started")
            await asyncio.sleep(0)
            order.append("response_finished")
            yield "done"

        def _fake_build_envelope(
            state_arg: Dict[str, Any],
            user_message: str,
            session_id: str,
            assistant_message: str,
        ) -> Dict[str, Any]:
            order.append("envelope")
            # Envelope is now built BEFORE enrichment completes, so day_cards
            # should NOT yet contain the enriched deeplink field.
            assert "deeplink" not in state_arg["day_cards"][0]["blocks"][0]
            return {
                "document": {"day_cards": list(state_arg.get("day_cards", []))},
                "assistant_message": assistant_message,
                "session_state": {"trip_plan": dict(state_arg.get("trip_plan", {}))},
            }

        monkeypatch.setattr(router_module, "classify_change", AsyncMock(return_value=classifier))
        monkeypatch.setattr(coordinator_module, "plan_turn", lambda *_args, **_kwargs: plan)
        monkeypatch.setattr(coordinator_module, "_execute_step", _fake_execute_step)
        monkeypatch.setattr(
            coordinator_module,
            "_generate_response_streaming",
            _fake_generate_response_streaming,
        )
        monkeypatch.setattr(coordinator_module, "_refresh_enrichment_states", AsyncMock())
        monkeypatch.setattr(coordinator_module, "_build_envelope", _fake_build_envelope)
        monkeypatch.setattr(
            feasibility_module,
            "batch_feasibility_precheck",
            AsyncMock(return_value={}),
        )
        monkeypatch.setattr(
            unsplash_module,
            "prefetch_destination_images",
            AsyncMock(return_value=None),
        )

        events = [
            event
            async for event in execute_turn(
                "build my itinerary",
                state,
                session_id="session-123",
            )
        ]

        # Enrichment task starts during BUILD_ITINERARY (before response streaming)
        assert order.index("enrichment_started") < order.index("response_finished")
        # Envelope is now emitted BEFORE enrichment finishes (non-blocking)
        assert order.index("envelope") < order.index("enrichment_finished")

        complete_index = next(
            idx for idx, event in enumerate(events) if event["type"] == "complete"
        )
        # Enrichment follow-up partials are emitted AFTER the complete event
        partial_events_after_complete = [
            event
            for event in events[complete_index + 1 :]
            if event["type"] == "partial" and event["data"]["kind"] != "trip_inputs"
        ]
        assert [event["data"]["kind"] for event in partial_events_after_complete] == [
            "tile_enrichment",
            "day_cards",
            "tiles",
        ]
        tile_enrichment_event = partial_events_after_complete[0]
        assert (
            tile_enrichment_event["data"]["payload"]["day_cards"][0]["blocks"][0]["deeplink"]
            == "https://viator.test"
        )
        assert tile_enrichment_event["data"]["payload"]["tiles"]["tile_1"]["provider"] == "viator"
        assert tile_enrichment_event["data"]["payload"]["day_cards_changed"] is True
        assert tile_enrichment_event["data"]["payload"]["tiles_changed"] is True
        assert tile_enrichment_event["data"]["payload"]["plan_view_state"] == "S3_ITINERARY_READY"

        enriched_day_cards_event = partial_events_after_complete[1]
        assert (
            enriched_day_cards_event["data"]["payload"]["day_cards"][0]["blocks"][0]["deeplink"]
            == "https://viator.test"
        )
        assert partial_events_after_complete[2]["data"]["payload"]["tile_1"]["provider"] == "viator"

    @pytest.mark.asyncio
    async def test_noop_initial_plan_preserves_existing_itinerary(self, monkeypatch: Any) -> None:
        classifier = _make_classifier(
            intent="PLANNING",
            change_type=ChangeType.INITIAL_PLAN,
            reasoning="Repeat build request with no new trip inputs",
            destination="Bali",
            start_date="2026-04-01",
            end_date="2026-04-07",
        )
        day_cards = [{"day_number": 1, "label": "Arrival Day", "blocks": []}]
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-04-01",
                "end_date": "2026-04-07",
            },
            trip_settings={"activity_settings": {"categories": ["diving"]}},
            tiles={"activities": [{"id": "viator_1", "type": "activity", "provider": "viator"}]},
            strategy_sections=[{"specialist_type": "diving", "content_added": [{"title": "Dive"}]}],
            day_cards=list(day_cards),
            messages=[],
        )

        async def _fake_generate_response_streaming(*args: Any, **kwargs: Any):
            yield "Reused itinerary."

        def _fake_build_envelope(
            state: Dict[str, Any],
            user_message: str,
            session_id: str,
            assistant_message: str,
        ) -> Dict[str, Any]:
            return {
                "document": {"day_cards": list(state.get("day_cards", []))},
                "session_state": {
                    "trip_plan": dict(state.get("trip_plan", {})),
                    "trip_settings": dict(state.get("trip_settings", {})),
                },
                "assistant_message": assistant_message,
            }

        import app.planner.coordinator as coordinator_module
        import app.planner.nodes.router_extraction as router_module
        import app.planner.services.feasibility_service as feasibility_module
        import app.services.unsplash as unsplash_module

        feasibility_precheck = AsyncMock(
            return_value={"diving": ("infeasible", "No reefs", "Try sailing")}
        )
        monkeypatch.setattr(router_module, "classify_change", AsyncMock(return_value=classifier))
        monkeypatch.setattr(
            coordinator_module,
            "_generate_response_streaming",
            _fake_generate_response_streaming,
        )
        monkeypatch.setattr(coordinator_module, "_refresh_enrichment_states", AsyncMock())
        monkeypatch.setattr(coordinator_module, "_build_envelope", _fake_build_envelope)
        monkeypatch.setattr(
            feasibility_module,
            "batch_feasibility_precheck",
            feasibility_precheck,
        )
        monkeypatch.setattr(
            unsplash_module,
            "prefetch_destination_images",
            AsyncMock(return_value=None),
        )

        events = [
            event
            async for event in execute_turn(
                "build my itinerary",
                state,
                session_id="session-123",
            )
        ]

        node_names = [
            event["data"]["node"] for event in events if event.get("type") == "node_status"
        ]
        assert "get_specialist_advice" not in node_names
        assert "search_tiles" not in node_names
        assert "build_itinerary" not in node_names
        assert not any(event.get("type") == "feasibility_warning" for event in events)
        feasibility_precheck.assert_not_awaited()
        assert state["day_cards"] == day_cards
        assert events[-1]["type"] == "complete"
        assert events[-1]["data"]["document"]["day_cards"] == day_cards

    @pytest.mark.asyncio
    async def test_cancel_event_stops_before_response_and_complete(self, monkeypatch: Any) -> None:
        import app.planner.coordinator as coordinator_module
        import app.planner.nodes.router_extraction as router_module
        import app.planner.services.feasibility_service as feasibility_module
        import app.services.unsplash as unsplash_module

        classifier = _make_classifier(
            intent="PLANNING",
            change_type=ChangeType.INITIAL_PLAN,
            destination="Bali",
        )
        plan = ExecutionPlan(
            reason="cancel after step execution",
            steps=[
                ExecutionStep(step_type=StepType.BUILD_ITINERARY, params={}),
                ExecutionStep(step_type=StepType.GENERATE_RESPONSE, params={}),
            ],
            estimated_llm_calls=1,
        )
        state = _make_state(
            trip_plan={"destination": "Bali"},
            trip_settings={},
            messages=[],
        )
        cancel_event = asyncio.Event()
        enrichment_started = asyncio.Event()
        enrichment_cancelled = asyncio.Event()

        async def _fake_execute_step(
            step: ExecutionStep,
            state_arg: Dict[str, Any],
            _classifier: ClassifierOutput,
            _user_message: str,
            session_id: str = "",
        ) -> Any:
            assert session_id == "session-123"
            assert step.step_type == StepType.BUILD_ITINERARY
            state_arg["day_cards"] = [{"day_number": 1, "label": "Arrival", "blocks": []}]

            async def _pending_enrichment() -> None:
                enrichment_started.set()
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    enrichment_cancelled.set()
                    raise

            state_arg[_PENDING_ITINERARY_ENRICHMENT_TASK_KEY] = asyncio.create_task(
                _pending_enrichment()
            )
            cancel_event.set()
            return {
                "type": "partial",
                "data": {
                    "kind": "day_cards",
                    "payload": {
                        "day_cards": state_arg["day_cards"],
                        "tiles": {},
                        "strategy_sections": [],
                        "plan_view_state": "S3_ITINERARY_READY",
                    },
                },
            }

        generate_response_streaming = AsyncMock()
        refresh_enrichment_states = AsyncMock()
        build_envelope = AsyncMock()

        monkeypatch.setattr(router_module, "classify_change", AsyncMock(return_value=classifier))
        monkeypatch.setattr(coordinator_module, "plan_turn", lambda *_args, **_kwargs: plan)
        monkeypatch.setattr(coordinator_module, "_execute_step", _fake_execute_step)
        monkeypatch.setattr(
            coordinator_module,
            "_generate_response_streaming",
            generate_response_streaming,
        )
        monkeypatch.setattr(
            coordinator_module,
            "_refresh_enrichment_states",
            refresh_enrichment_states,
        )
        monkeypatch.setattr(coordinator_module, "_build_envelope", build_envelope)
        monkeypatch.setattr(
            feasibility_module,
            "batch_feasibility_precheck",
            AsyncMock(return_value={}),
        )
        monkeypatch.setattr(
            unsplash_module,
            "prefetch_destination_images",
            AsyncMock(return_value=None),
        )

        events = [
            event
            async for event in execute_turn(
                "build my itinerary",
                state,
                session_id="session-123",
                cancel_event=cancel_event,
            )
        ]

        await asyncio.wait_for(enrichment_started.wait(), timeout=0.1)
        await asyncio.wait_for(enrichment_cancelled.wait(), timeout=0.1)

        partial_events = [event for event in events if event["type"] == "partial"]
        assert [event["data"]["kind"] for event in partial_events] == ["trip_inputs", "day_cards"]
        assert not any(event["type"] == "complete" for event in events)
        assert not any(
            event["type"] == "node_status" and event["data"]["node"] == "response"
            for event in events
        )
        assert _PENDING_ITINERARY_ENRICHMENT_TASK_KEY not in state
        generate_response_streaming.assert_not_called()
        refresh_enrichment_states.assert_not_awaited()
        build_envelope.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_turn_aclose_cancels_pending_itinerary_enrichment(
        self, monkeypatch: Any
    ) -> None:
        import app.planner.coordinator as coordinator_module
        import app.planner.nodes.router_extraction as router_module
        import app.planner.services.feasibility_service as feasibility_module
        import app.services.unsplash as unsplash_module

        classifier = _make_classifier(
            intent="PLANNING",
            change_type=ChangeType.INITIAL_PLAN,
            destination="Bali",
        )
        plan = ExecutionPlan(
            reason="cancel generator after builder partial",
            steps=[
                ExecutionStep(step_type=StepType.BUILD_ITINERARY, params={}),
                ExecutionStep(step_type=StepType.GENERATE_RESPONSE, params={}),
            ],
            estimated_llm_calls=1,
        )
        state = _make_state(
            trip_plan={"destination": "Bali"},
            trip_settings={},
            messages=[],
        )
        enrichment_started = asyncio.Event()
        enrichment_cancelled = asyncio.Event()

        async def _fake_execute_step(
            step: ExecutionStep,
            state_arg: Dict[str, Any],
            _classifier: ClassifierOutput,
            _user_message: str,
            session_id: str = "",
        ) -> Any:
            assert session_id == "session-123"
            assert step.step_type == StepType.BUILD_ITINERARY
            state_arg["day_cards"] = [{"day_number": 1, "label": "Arrival", "blocks": []}]

            async def _pending_enrichment() -> None:
                enrichment_started.set()
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    enrichment_cancelled.set()
                    raise

            state_arg[_PENDING_ITINERARY_ENRICHMENT_TASK_KEY] = asyncio.create_task(
                _pending_enrichment()
            )
            return {
                "type": "partial",
                "data": {
                    "kind": "day_cards",
                    "payload": {
                        "day_cards": state_arg["day_cards"],
                        "tiles": {},
                        "strategy_sections": [],
                        "plan_view_state": "S3_ITINERARY_READY",
                    },
                },
            }

        generate_response_streaming = AsyncMock()

        monkeypatch.setattr(router_module, "classify_change", AsyncMock(return_value=classifier))
        monkeypatch.setattr(coordinator_module, "plan_turn", lambda *_args, **_kwargs: plan)
        monkeypatch.setattr(coordinator_module, "_execute_step", _fake_execute_step)
        monkeypatch.setattr(
            coordinator_module,
            "_generate_response_streaming",
            generate_response_streaming,
        )
        monkeypatch.setattr(coordinator_module, "_refresh_enrichment_states", AsyncMock())
        monkeypatch.setattr(coordinator_module, "_build_envelope", AsyncMock())
        monkeypatch.setattr(
            feasibility_module,
            "batch_feasibility_precheck",
            AsyncMock(return_value={}),
        )
        monkeypatch.setattr(
            unsplash_module,
            "prefetch_destination_images",
            AsyncMock(return_value=None),
        )

        turn = execute_turn(
            "build my itinerary",
            state,
            session_id="session-123",
        )

        seen_day_cards = False
        try:
            while True:
                event = await turn.__anext__()
                if event["type"] == "partial" and event["data"]["kind"] == "day_cards":
                    seen_day_cards = True
                    break
        finally:
            await turn.aclose()

        await asyncio.wait_for(enrichment_started.wait(), timeout=0.1)
        await asyncio.wait_for(enrichment_cancelled.wait(), timeout=0.1)

        assert seen_day_cards is True
        assert _PENDING_ITINERARY_ENRICHMENT_TASK_KEY not in state
        generate_response_streaming.assert_not_called()


class TestDeferredActivityTileRehydration:
    def test_matches_enriched_tile_via_booked_tile_title_when_summary_drifts(self) -> None:
        day_cards = [
            {
                "day_number": 1,
                "blocks": [
                    {
                        "summary": "Village walk",
                        "booked_tile": {"title": "Secret Garden Village"},
                    }
                ],
            }
        ]
        activity_tiles = [
            {
                "id": "browse_village_walk",
                "title": "Village walk",
                "provider": "google_places",
                "deeplink": "https://maps.test/village-walk",
                "image_url": "https://images.test/village-walk.jpg",
            },
            {
                "id": "browse_secret_garden",
                "title": "Secret Garden Village (Session 2)",
                "provider": "viator",
                "deeplink": "https://viator.test/secret-garden",
                "image_url": "https://images.test/secret-garden.jpg",
            },
        ]

        _apply_activity_tile_enrichment_to_day_cards(activity_tiles, day_cards)

        block = day_cards[0]["blocks"][0]
        assert block["id"] == "browse_secret_garden"
        assert block["deeplink"] == "https://viator.test/secret-garden"
        assert block["image_url"] == "https://images.test/secret-garden.jpg"

    def test_matches_enriched_tile_via_partner_product_id_when_block_id_is_missing(self) -> None:
        day_cards = [
            {
                "day_number": 1,
                "blocks": [
                    {
                        "summary": "Sunrise trek",
                        "booked_tile": {
                            "partner_product_id": "gyg-123",
                            "title": "Mount Batur Sunrise Trek",
                        },
                    }
                ],
            }
        ]
        activity_tiles = [
            {
                "id": "tile_mount_batur",
                "partner_product_id": "gyg-123",
                "title": "Mount Batur Sunrise Trek",
                "provider": "gyg",
                "deeplink": "https://gyg.test/mount-batur",
                "image_url": "https://images.test/mount-batur.jpg",
            }
        ]

        _apply_activity_tile_enrichment_to_day_cards(activity_tiles, day_cards)

        block = day_cards[0]["blocks"][0]
        assert block["id"] == "tile_mount_batur"
        assert block["deeplink"] == "https://gyg.test/mount-batur"
        assert block["image_url"] == "https://images.test/mount-batur.jpg"

    def test_skips_relaxed_title_fallback_when_multiple_tiles_share_same_base_title(self) -> None:
        day_cards = [
            {
                "day_number": 1,
                "blocks": [
                    {
                        "summary": "Secret Garden Village",
                    }
                ],
            }
        ]
        activity_tiles = [
            {
                "id": "secret_garden_morning",
                "title": "Secret Garden Village (Morning)",
                "provider": "viator",
                "deeplink": "https://viator.test/secret-garden-morning",
            },
            {
                "id": "secret_garden_evening",
                "title": "Secret Garden Village (Evening)",
                "provider": "viator",
                "deeplink": "https://viator.test/secret-garden-evening",
            },
        ]

        _apply_activity_tile_enrichment_to_day_cards(activity_tiles, day_cards)

        block = day_cards[0]["blocks"][0]
        assert block.get("id") is None
        assert block.get("deeplink") is None

    @pytest.mark.asyncio
    async def test_build_itinerary_real_path_starts_deferred_enrichment(
        self, monkeypatch: Any
    ) -> None:
        import app.planner.coordinator as coordinator_module

        class _FakeOverview:
            def model_dump(self) -> dict[str, Any]:
                return {"duration_label": "1 day"}

        class _FakeDayCard:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._payload = payload

            def model_dump(self) -> dict[str, Any]:
                return dict(self._payload)

        class _FakeBuilderResult:
            success = True
            total_activities_placed = 1
            total_activities_input = 1
            conflicts: list[Any] = []
            resolutions: list[Any] = []
            warnings: list[str] = []
            overview = _FakeOverview()
            assumptions = None
            day_cards = [_FakeDayCard({"day_number": 1, "label": "Arrival", "blocks": []})]

        class _FakeBuilder:
            def build(self, _input: Any) -> _FakeBuilderResult:
                return _FakeBuilderResult()

        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-04-01",
                "end_date": "2026-04-01",
            },
            trip_settings={"activity_settings": {"categories": ["diving"]}},
            tiles={
                "activities": [{"id": "act_1", "title": "Dive", "type": "activity"}],
                "hotels": [{"id": "hotel_1", "title": "Stay", "type": "hotel"}],
            },
        )
        started: list[tuple[str, list[dict[str, Any]]]] = []

        monkeypatch.setattr(
            coordinator_module,
            "_inject_specialist_tiles_into_state",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(coordinator_module, "_prepare_activity_tiles_for_build", AsyncMock())
        monkeypatch.setattr(
            "app.services.itinerary_builder.ItineraryBuilder",
            lambda: _FakeBuilder(),
        )
        monkeypatch.setattr(
            coordinator_module,
            "_start_pending_itinerary_enrichment",
            lambda state_arg, session_id="": started.append(
                (session_id, list(state_arg.get("day_cards", [])))
            ),
        )

        day_cards = await _build_itinerary(state, session_id="session-123")

        assert day_cards == [{"day_number": 1, "label": "Arrival", "blocks": []}]
        assert started == [
            (
                "session-123",
                [{"day_number": 1, "label": "Arrival", "blocks": []}],
            )
        ]

    @pytest.mark.asyncio
    async def test_build_itinerary_real_path_starts_deferred_enrichment_without_day_cards(
        self, monkeypatch: Any
    ) -> None:
        import app.planner.coordinator as coordinator_module

        class _FakeBuilderResult:
            success = True
            total_activities_placed = 0
            total_activities_input = 1
            conflicts: list[Any] = []
            resolutions: list[Any] = []
            warnings: list[str] = []
            overview = None
            assumptions = None
            day_cards: list[Any] = []

        class _FakeBuilder:
            def build(self, _input: Any) -> _FakeBuilderResult:
                return _FakeBuilderResult()

        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-04-01",
                "end_date": "2026-04-01",
            },
            trip_settings={"activity_settings": {"categories": ["diving"]}},
            tiles={
                "activities": [{"id": "act_1", "title": "Dive", "type": "activity"}],
                "hotels": [{"id": "hotel_1", "title": "Stay", "type": "hotel"}],
            },
        )
        started: list[tuple[str, list[dict[str, Any]]]] = []

        monkeypatch.setattr(
            coordinator_module,
            "_inject_specialist_tiles_into_state",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(coordinator_module, "_prepare_activity_tiles_for_build", AsyncMock())
        monkeypatch.setattr(
            "app.services.itinerary_builder.ItineraryBuilder",
            lambda: _FakeBuilder(),
        )
        monkeypatch.setattr(
            coordinator_module,
            "_start_pending_itinerary_enrichment",
            lambda state_arg, session_id="": started.append(
                (session_id, list(state_arg.get("day_cards", [])))
            ),
        )

        day_cards = await _build_itinerary(state, session_id="session-123")

        assert day_cards == []
        assert state["day_cards"] == []
        assert started == [("session-123", [])]

    @pytest.mark.asyncio
    async def test_execute_turn_cancels_pending_itinerary_enrichment_on_error(
        self, monkeypatch: Any
    ) -> None:
        import app.planner.coordinator as coordinator_module
        import app.planner.nodes.router_extraction as router_module
        import app.planner.services.feasibility_service as feasibility_module
        import app.services.unsplash as unsplash_module

        classifier = _make_classifier(
            intent="PLANNING",
            change_type=ChangeType.INITIAL_PLAN,
            destination="Bali",
            start_date="2026-04-01",
            end_date="2026-04-07",
        )
        plan = ExecutionPlan(
            reason="test error cleanup",
            steps=[ExecutionStep(step_type=StepType.GENERATE_RESPONSE, params={})],
            estimated_llm_calls=1,
        )
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-04-01",
                "end_date": "2026-04-07",
            },
            messages=[],
        )
        cancel_calls: list[Dict[str, Any]] = []
        unsplash_started = asyncio.Event()
        unsplash_release = asyncio.Event()
        unsplash_cancelled = asyncio.Event()

        async def _broken_generate(*_args: Any, **_kwargs: Any):
            await asyncio.sleep(0)
            raise RuntimeError("boom")
            yield "unreachable"

        async def _fake_prefetch_destination_images(_destination: str) -> None:
            unsplash_started.set()
            try:
                await unsplash_release.wait()
            except asyncio.CancelledError:
                unsplash_cancelled.set()
                raise

        monkeypatch.setattr(router_module, "classify_change", AsyncMock(return_value=classifier))
        monkeypatch.setattr(coordinator_module, "plan_turn", lambda *_args, **_kwargs: plan)
        monkeypatch.setattr(coordinator_module, "_generate_response_streaming", _broken_generate)

        async def _fake_cleanup_pending_itinerary_enrichment(state_arg: Dict[str, Any]) -> None:
            cancel_calls.append(dict(state_arg))

        monkeypatch.setattr(
            coordinator_module,
            "_cleanup_pending_itinerary_enrichment",
            _fake_cleanup_pending_itinerary_enrichment,
        )
        monkeypatch.setattr(
            feasibility_module,
            "batch_feasibility_precheck",
            AsyncMock(return_value={}),
        )
        monkeypatch.setattr(
            unsplash_module,
            "prefetch_destination_images",
            _fake_prefetch_destination_images,
        )

        try:
            events = [
                event
                async for event in execute_turn(
                    "build my itinerary",
                    state,
                    session_id="session-123",
                )
            ]
            await asyncio.wait_for(unsplash_started.wait(), timeout=0.1)
            await asyncio.wait_for(unsplash_cancelled.wait(), timeout=0.1)
        finally:
            unsplash_release.set()

        # Response generation failure is now non-fatal (Item P: LLM failure recovery).
        # The coordinator catches it, sets response_degraded, and emits a complete envelope.
        assert events[-1]["type"] == "complete"
        assert events[-1]["data"].get("response_degraded") is True
        assert len(cancel_calls) >= 1


class TestPostBuildPlacedActivityEnrichment:
    @pytest.mark.asyncio
    async def test_reuses_booked_tile_google_places_fields_without_provider_call(
        self, monkeypatch: Any
    ) -> None:
        import app.tile_service.google_places_provider as gp_module
        from app.config import settings as app_settings

        state = _make_state(
            trip_plan={"destination": "Bali"},
            tiles={"activities": []},
            session_id="session-123",
        )
        day_cards = [
            {
                "day_number": 1,
                "blocks": [
                    {
                        "summary": "Village walk",
                        "booked_tile": {
                            "title": "Secret Garden Village",
                            "google_place_id": "gp_secret",
                            "coordinates": {"lat": -8.5, "lng": 115.2},
                            "deeplink": "https://maps.test/secret-garden",
                            "image_url": "https://images.test/secret-garden.jpg",
                            "price_level": 2,
                        },
                    }
                ],
            }
        ]

        monkeypatch.setattr(app_settings, "use_google_places_provider", True)
        monkeypatch.setattr(app_settings, "google_places_enrichment_enabled", True)
        enrich_mock = AsyncMock(side_effect=AssertionError("provider should not be called"))
        monkeypatch.setattr(gp_module, "enrich_activities_with_places", enrich_mock)

        await _post_build_enrich_placed_activities(state, day_cards)

        block = day_cards[0]["blocks"][0]
        assert block["google_place_id"] == "gp_secret"
        assert block["coordinates"] == {"lat": -8.5, "lng": 115.2}
        assert block["deeplink"] == "https://maps.test/secret-garden"
        assert block["image_url"] == "https://images.test/secret-garden.jpg"
        assert block["price_level"] == 2
        enrich_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_prefers_booked_tile_title_for_cached_gp_reuse_when_summary_drifts(
        self, monkeypatch: Any
    ) -> None:
        import app.tile_service.google_places_provider as gp_module
        from app.config import settings as app_settings

        state = _make_state(
            trip_plan={"destination": "Bali"},
            tiles={
                "activities": [
                    {
                        "id": "browse_secret_garden",
                        "title": "Secret Garden Village",
                        "google_place_id": "gp_secret",
                        "coordinates": {"lat": -8.51, "lng": 115.21},
                        "deeplink": "https://maps.test/secret-garden",
                        "photo_name": "places/secret-garden/photo-1",
                        "price_level": 3,
                    }
                ]
            },
            session_id="session-123",
        )
        day_cards = [
            {
                "day_number": 1,
                "blocks": [
                    {
                        "summary": "Village walk",
                        "booked_tile": {"title": "Secret Garden Village"},
                    }
                ],
            }
        ]

        monkeypatch.setattr(app_settings, "use_google_places_provider", True)
        monkeypatch.setattr(app_settings, "google_places_enrichment_enabled", True)
        enrich_mock = AsyncMock(side_effect=AssertionError("provider should not be called"))
        monkeypatch.setattr(gp_module, "enrich_activities_with_places", enrich_mock)
        monkeypatch.setattr(
            gp_module,
            "build_signed_photo_url",
            lambda session_id, photo_name: f"signed://{session_id}/{photo_name}",
        )

        await _post_build_enrich_placed_activities(state, day_cards)

        block = day_cards[0]["blocks"][0]
        assert block["google_place_id"] == "gp_secret"
        assert block["coordinates"] == {"lat": -8.51, "lng": 115.21}
        assert block["deeplink"] == "https://maps.test/secret-garden"
        assert block["image_url"] == "signed://session-123/places/secret-garden/photo-1"
        assert block["price_level"] == 3
        enrich_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_ambiguous_cached_gp_title_reuse_and_queries_places(
        self, monkeypatch: Any
    ) -> None:
        import app.tile_service.google_places_provider as gp_module
        from app.config import settings as app_settings

        state = _make_state(
            trip_plan={"destination": "Bali", "adults": 2, "children": 0},
            tiles={
                "activities": [
                    {
                        "id": "secret_garden_a",
                        "title": "Secret Garden Village",
                        "google_place_id": "gp_a",
                        "coordinates": {"lat": -8.50, "lng": 115.20},
                    },
                    {
                        "id": "secret_garden_b",
                        "title": "Secret Garden Village",
                        "google_place_id": "gp_b",
                        "coordinates": {"lat": -8.60, "lng": 115.30},
                    },
                ]
            },
            session_id="session-123",
        )
        day_cards = [
            {
                "day_number": 1,
                "blocks": [{"summary": "Secret Garden Village"}],
            }
        ]

        monkeypatch.setattr(app_settings, "use_google_places_provider", True)
        monkeypatch.setattr(app_settings, "google_places_enrichment_enabled", True)
        enrich_mock = AsyncMock(
            return_value=[
                {
                    "id": "post_enrich_0_0",
                    "google_place_id": "gp_resolved",
                    "coordinates": {"lat": -8.55, "lng": 115.25},
                    "deeplink": "https://maps.test/resolved",
                    "meta": {"photo_name": "places/resolved/photo-1"},
                    "price_level": 1,
                }
            ]
        )
        monkeypatch.setattr(gp_module, "enrich_activities_with_places", enrich_mock)
        monkeypatch.setattr(
            gp_module,
            "build_signed_photo_url",
            lambda session_id, photo_name: f"signed://{session_id}/{photo_name}",
        )

        await _post_build_enrich_placed_activities(state, day_cards)

        block = day_cards[0]["blocks"][0]
        assert block["google_place_id"] == "gp_resolved"
        assert block["coordinates"] == {"lat": -8.55, "lng": 115.25}
        assert block["deeplink"] == "https://maps.test/resolved"
        assert block["image_url"] == "signed://session-123/places/resolved/photo-1"
        assert block["price_level"] == 1
        enrich_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_preserves_dict_coordinates_on_proxy_when_booked_tile_lacks_place_id(
        self, monkeypatch: Any
    ) -> None:
        import app.tile_service.google_places_provider as gp_module
        from app.config import settings as app_settings

        state = _make_state(
            trip_plan={"destination": "Bali", "adults": 1, "children": 0},
            tiles={"activities": []},
            session_id="session-123",
        )
        day_cards = [
            {
                "day_number": 1,
                "blocks": [
                    {
                        "summary": "Cliff walk",
                        "booked_tile": {
                            "title": "Uluwatu Cliff Walk",
                            "coordinates": {"lat": -8.829, "lng": 115.084},
                        },
                    }
                ],
            }
        ]
        captured_proxies: list[dict[str, Any]] = []

        async def _fake_enrich(
            proxies: list[dict[str, Any]],
            *_args: Any,
            **_kwargs: Any,
        ) -> list[dict[str, Any]]:
            captured_proxies.extend(proxies)
            return []

        monkeypatch.setattr(app_settings, "use_google_places_provider", True)
        monkeypatch.setattr(app_settings, "google_places_enrichment_enabled", True)
        monkeypatch.setattr(gp_module, "enrich_activities_with_places", _fake_enrich)

        await _post_build_enrich_placed_activities(state, day_cards)

        assert captured_proxies == [
            {
                "id": "post_enrich_0_0",
                "title": "Uluwatu Cliff Walk",
                "coordinates": [115.084, -8.829],
                "photo_name": None,
                "image_url": None,
                "meta": {},
            }
        ]


class TestNormalizeSpecialistPlanKeys:
    def test_lowercases_keys(self) -> None:
        state: Dict[str, Any] = {
            "specialist_plans": {"Diving": {"day_plans": []}, "HIKING": {"day_plans": []}}
        }
        _normalize_specialist_plan_keys(state)
        assert set(state["specialist_plans"].keys()) == {"diving", "hiking"}

    def test_no_plans_is_noop(self) -> None:
        state: Dict[str, Any] = {}
        _normalize_specialist_plan_keys(state)
        assert "specialist_plans" not in state


class TestBuildTripStateSummary:
    def test_basic_summary(self) -> None:
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
                "adults": 2,
                "budget": 5000,
            },
            trip_settings={"activity_settings": {"categories": ["diving"]}},
        )
        summary = build_trip_state_summary(state)
        assert summary["destination"] == "Bali"
        assert summary["adults"] == 2
        assert summary["budget"] == 5000
        assert "diving" in summary["categories"]

    def test_empty_state(self) -> None:
        summary = build_trip_state_summary(_make_state())
        assert summary["destination"] is None
        assert summary["categories"] == []
        assert summary["has_itinerary"] is False


class TestBuildBrief:
    def test_none_travelers_default_to_safe_values(self) -> None:
        """Explicit None travelers should default to 1 adult and 0 children."""
        classifier = _make_classifier(
            destination="Bali",
            start_date="2026-03-01",
            end_date="2026-03-07",
        )
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
                "adults": None,
                "children": None,
            },
            trip_settings={"activity_settings": {"categories": ["diving"]}},
        )

        brief = build_brief("diving", state, classifier, other_plans={})
        assert brief.adults == 1
        assert brief.children == 0


class TestTileRefreshTypes:
    def test_initial_plan_refreshes_all(self) -> None:
        classifier = _make_classifier(change_type=ChangeType.INITIAL_PLAN)
        result = _tile_refresh_types(classifier, _make_state())
        assert set(result) == {"flights", "hotels", "activities"}

    def test_logistics_refreshes_flights(self) -> None:
        classifier = _make_classifier(change_type=ChangeType.LOGISTICS)
        result = _tile_refresh_types(classifier, _make_state())
        assert result == ["flights"]

    def test_date_change_refreshes_flights_hotels_activities(self) -> None:
        classifier = _make_classifier(change_type=ChangeType.DATE_CHANGE)
        result = _tile_refresh_types(classifier, _make_state())
        assert set(result) == {"flights", "hotels", "activities"}

    def test_add_tier1_activity_refreshes_flights_and_activities(self) -> None:
        classifier = _make_classifier(
            change_type=ChangeType.ADD_ACTIVITY,
            specialist_hints=["diving"],
            activity_categories=["diving"],
        )
        result = _tile_refresh_types(classifier, _make_state())
        assert result == ["activities", "flights"]

    def test_existing_diving_plan_keeps_refreshing_flights_for_tier2_additions(self) -> None:
        classifier = _make_classifier(
            change_type=ChangeType.ADD_ACTIVITY,
            activity_categories=["spa"],
        )
        state = _make_state(
            trip_settings={"activity_settings": {"categories": ["diving", "spa"]}},
            strategy_sections=[
                {"specialist_type": "diving", "constraints_applied": [], "content_added": []}
            ],
        )
        result = _tile_refresh_types(classifier, state)
        assert result == ["activities", "flights"]

    def test_preference_day_count_refreshes_flights_and_activities(self) -> None:
        classifier = _make_classifier(
            change_type=ChangeType.PREFERENCE,
            activity_day_preferences='{"diving": 3}',
        )
        state = _make_state(
            trip_settings={"activity_settings": {"categories": ["diving"]}},
            strategy_sections=[
                {"specialist_type": "diving", "constraints_applied": [], "content_added": []}
            ],
        )
        result = _tile_refresh_types(classifier, state)
        assert result == ["activities", "flights"]

    def test_day_count_refreshes_flights_hotels_and_activities(self) -> None:
        classifier = _make_classifier(change_type=ChangeType.DAY_COUNT, affects=["diving"])
        result = _tile_refresh_types(classifier, _make_state())
        assert result == ["activities", "flights", "hotels"]


class TestDateChangeContinuityReuse:
    def test_refresh_preserved_specialist_section_metadata_updates_cache_fields(self) -> None:
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-17",
            },
            trip_settings={
                "activity_settings": {
                    "categories": ["diving"],
                    "day_preferences": {"diving": 4},
                    "skill_level": "advanced",
                }
            },
            strategy_sections=[
                {
                    "specialist_type": "diving",
                    "_cache_dates": "2026-03-01:2026-03-07",
                    "_cache_day_pref": None,
                    "_cache_skill_level": None,
                    "content_added": [{"title": "Dive"}],
                }
            ],
        )

        _refresh_preserved_specialist_section_metadata(state, ["diving"])

        section = state["strategy_sections"][0]
        assert section["subtitle"] == "Bali"
        assert section["_cache_dates"] == "2026-03-01:2026-03-17"
        assert section["_cache_day_pref"] == 4
        assert section["_cache_skill_level"] == "advanced"

    def test_preserved_specialist_tiles_for_turn_filters_to_preserved_topics(self) -> None:
        classifier = _make_classifier(change_type=ChangeType.DATE_CHANGE)
        state = _make_state(
            trip_plan={
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-17",
            },
            trip_settings={"activity_settings": {"categories": ["diving", "hiking"]}},
            specialist_plans={
                "diving": {"day_plans": [{"day_number": 2, "location": "Tulamben"}]},
                "hiking": {"day_plans": []},
            },
            strategy_sections=[
                {"specialist_type": "diving", "content_added": [{"title": "Dive"}]},
                {"specialist_type": "hiking", "content_added": []},
            ],
            _pre_change_briefs={
                "trip_plan": {
                    "destination": "Bali",
                    "start_date": "2026-03-01",
                    "end_date": "2026-03-07",
                },
                "trip_settings": {"activity_settings": {"categories": ["diving", "hiking"]}},
            },
        )
        existing_tiles = [
            {
                "id": "spec_bali_diving_keep",
                "title": "Dive",
                "type": "activity",
                "source_agent": "vertical_specialist",
                "provider": "viator",
                "meta": {"specialist_type": "diving"},
            },
            {
                "id": "spec_bali_hiking_drop",
                "title": "Hike",
                "type": "activity",
                "source_agent": "vertical_specialist",
                "provider": "viator",
                "meta": {"specialist_type": "hiking"},
            },
        ]

        preserved = _preserved_specialist_tiles_for_turn(state, classifier, existing_tiles)
        merged = _merge_activity_tiles(
            [{"id": "browse_1", "title": "Market", "type": "activity"}],
            preserved,
        )

        ids = {tile["id"] for tile in merged}
        assert ids == {"browse_1", "spec_bali_diving_keep"}
        kept_tile = next(tile for tile in merged if tile["id"] == "spec_bali_diving_keep")
        assert kept_tile["provider"] == "viator"


class TestCanonicalBuilderConstraints:
    def test_collects_cross_domain_constraint_from_active_sections(self) -> None:
        state = _make_state(
            strategy_sections=[
                {"specialist_type": "diving", "constraints_applied": [], "content_added": []},
                {"specialist_type": "hiking", "constraints_applied": [], "content_added": []},
            ],
            trip_settings={"activity_settings": {"categories": ["diving", "hiking"]}},
        )

        result = _collect_canonical_builder_constraints(state)

        assert any(c.get("rule") == "no_altitude_after_dive" for c in result)


# =============================================================================
# _specialist_content_to_tiles — tile conversion shape
# =============================================================================


class TestSpecialistContentToTiles:
    """Tests for converting specialist content_added items to tile dicts."""

    def test_basic_tile_shape(self) -> None:
        """Converted tile has all required fields matching experience tile shape."""
        section = {
            "content_added": [
                {
                    "title": "USAT Liberty Wreck",
                    "description": "Famous WWII shipwreck dive",
                    "duration_hours": 3.0,
                    "day": 2,
                    "coordinates": [115.59, -8.28],
                    "intensity": "moderate",
                }
            ],
        }
        tiles = _specialist_content_to_tiles("diving", section, "Bali")

        assert len(tiles) == 1
        tile = tiles[0]
        assert tile["id"].startswith("spec_bali_diving_")
        assert tile["type"] == "activity"
        assert tile["source_agent"] == "vertical_specialist"
        assert tile["title"] == "USAT Liberty Wreck"
        assert tile["tags"] == ["activity", "diving", "specialist"]
        assert tile["meta"]["specialist_type"] == "diving"
        assert tile["meta"]["preferred_day"] == 2
        assert tile["meta"]["duration_hours"] == 3.0
        assert tile["geo"] == {"lng": 115.59, "lat": -8.28}

    def test_deterministic_ids(self) -> None:
        """Same topic + title always produces the same tile ID."""
        section = {"content_added": [{"title": "Manta Point"}]}
        tiles_a = _specialist_content_to_tiles("diving", section, "Bali")
        tiles_b = _specialist_content_to_tiles("diving", section, "Bali")
        assert tiles_a[0]["id"] == tiles_b[0]["id"]

    def test_different_titles_different_ids(self) -> None:
        """Different titles produce different tile IDs."""
        section = {
            "content_added": [
                {"title": "Manta Point"},
                {"title": "USAT Liberty Wreck"},
            ]
        }
        tiles = _specialist_content_to_tiles("diving", section, "Bali")
        assert len(tiles) == 2
        assert tiles[0]["id"] != tiles[1]["id"]

    def test_skips_buffer_items(self) -> None:
        """Buffer items (is_buffer=True) are not converted to tiles."""
        section = {
            "content_added": [
                {"title": "Dive Day", "is_buffer": False},
                {"title": "Safety Buffer", "is_buffer": True},
            ]
        }
        tiles = _specialist_content_to_tiles("diving", section, "Bali")
        assert len(tiles) == 1
        assert tiles[0]["title"] == "Dive Day"

    def test_skips_empty_titles(self) -> None:
        """Items with no title are skipped."""
        section = {"content_added": [{"title": ""}, {"title": "Real Activity"}]}
        tiles = _specialist_content_to_tiles("diving", section, "Bali")
        assert len(tiles) == 1

    def test_empty_content_returns_empty(self) -> None:
        """No content_added returns empty list."""
        tiles = _specialist_content_to_tiles("diving", {"content_added": []}, "Bali")
        assert tiles == []

    def test_no_coordinates_empty_geo(self) -> None:
        """Missing coordinates serialize as absent geo coordinates."""
        section = {"content_added": [{"title": "Reef Dive"}]}
        tiles = _specialist_content_to_tiles("diving", section, "Bali")
        assert tiles[0]["geo"] is None

    def test_destination_slug_normalization(self) -> None:
        """Destination with spaces/commas gets slugified in tile ID."""
        section = {"content_added": [{"title": "Trail Run"}]}
        tiles = _specialist_content_to_tiles("hiking", section, "Rome, Italy")
        assert tiles[0]["id"].startswith("spec_rome_italy_hiking_")


# =============================================================================
# _inject_specialist_tiles_into_state — injection + dedup + stale cleanup
# =============================================================================


class TestInjectSpecialistTiles:
    """Tests for specialist tile injection into state."""

    def test_injects_tiles_into_empty_activities(self) -> None:
        """Specialist tiles appear in state['tiles']['activities']."""
        state = _make_state(
            trip_plan={"destination": "Bali"},
            strategy_sections=[
                {
                    "specialist_type": "diving",
                    "content_added": [
                        {"title": "USAT Liberty Wreck"},
                        {"title": "Manta Point"},
                    ],
                }
            ],
            tiles={},
        )
        _inject_specialist_tiles_into_state(state)

        activities = state["tiles"]["activities"]
        assert len(activities) == 2
        assert all(t["source_agent"] == "vertical_specialist" for t in activities)

    def test_writes_tile_id_back_to_content_added(self) -> None:
        """Each content_added item gets tile_id written back."""
        content = [{"title": "Reef Dive"}, {"title": "Wall Dive"}]
        state = _make_state(
            trip_plan={"destination": "Bali"},
            strategy_sections=[{"specialist_type": "diving", "content_added": content}],
            tiles={},
        )
        _inject_specialist_tiles_into_state(state)

        for item in content:
            assert "tile_id" in item
            assert item["tile_id"].startswith("spec_bali_diving_")

    def test_deduplicates_existing_tiles(self) -> None:
        """Tiles already in state are not duplicated."""
        content = [{"title": "Reef Dive"}]
        state = _make_state(
            trip_plan={"destination": "Bali"},
            strategy_sections=[{"specialist_type": "diving", "content_added": content}],
            tiles={},
        )
        # First injection
        _inject_specialist_tiles_into_state(state)
        assert len(state["tiles"]["activities"]) == 1
        tile_id = state["tiles"]["activities"][0]["id"]

        # Second injection (simulates replan)
        _inject_specialist_tiles_into_state(state)
        assert len(state["tiles"]["activities"]) == 1
        assert state["tiles"]["activities"][0]["id"] == tile_id

    def test_removes_stale_specialist_tiles(self) -> None:
        """Tiles from previous specialist runs are removed if no longer in sections."""
        # Start with an old specialist tile
        old_tile = {
            "id": "spec_bali_surfing_old12345",
            "type": "activity",
            "source_agent": "vertical_specialist",
            "title": "Old Surf Spot",
        }
        state = _make_state(
            trip_plan={"destination": "Bali"},
            strategy_sections=[
                {
                    "specialist_type": "diving",
                    "content_added": [{"title": "Reef Dive"}],
                }
            ],
            tiles={"activities": [old_tile]},
        )
        _inject_specialist_tiles_into_state(state)

        activities = state["tiles"]["activities"]
        ids = [t.get("id") for t in activities]
        assert "spec_bali_surfing_old12345" not in ids
        assert len(activities) == 1  # Only the new diving tile

    def test_preserves_non_specialist_tiles(self) -> None:
        """Experience generator tiles are not affected by injection."""
        exp_tile = {
            "id": "exp_bali_yoga_0",
            "type": "activity",
            "source_agent": "experience_generator",
            "title": "Morning Yoga",
        }
        state = _make_state(
            trip_plan={"destination": "Bali"},
            strategy_sections=[
                {
                    "specialist_type": "diving",
                    "content_added": [{"title": "Reef Dive"}],
                }
            ],
            tiles={"activities": [exp_tile]},
        )
        _inject_specialist_tiles_into_state(state)

        activities = state["tiles"]["activities"]
        assert any(t["id"] == "exp_bali_yoga_0" for t in activities)
        assert len(activities) == 2  # exp + specialist

    def test_skips_infeasible_sections(self) -> None:
        """Infeasible sections don't produce tiles."""
        state = _make_state(
            trip_plan={"destination": "Bali"},
            strategy_sections=[
                {
                    "specialist_type": "skiing",
                    "feasibility_status": "infeasible",
                    "content_added": [{"title": "Alpine Run"}],
                }
            ],
            tiles={},
        )
        _inject_specialist_tiles_into_state(state)

        activities = state["tiles"].get("activities", [])
        assert len(activities) == 0

    def test_skips_general_and_local_expert(self) -> None:
        """General and local_expert sections are not converted."""
        state = _make_state(
            trip_plan={"destination": "Bali"},
            strategy_sections=[
                {"specialist_type": "general", "content_added": [{"title": "Overview"}]},
                {"specialist_type": "local_expert", "content_added": [{"title": "Tips"}]},
            ],
            tiles={},
        )
        _inject_specialist_tiles_into_state(state)

        activities = state["tiles"].get("activities", [])
        assert len(activities) == 0

    def test_no_destination_is_noop(self) -> None:
        """No destination = no injection."""
        state = _make_state(
            trip_plan={},
            strategy_sections=[{"specialist_type": "diving", "content_added": [{"title": "Dive"}]}],
            tiles={},
        )
        _inject_specialist_tiles_into_state(state)
        assert state["tiles"].get("activities") is None or state["tiles"].get("activities") == []


# =============================================================================
# _rehydrate_trimmed_booked_tiles
# =============================================================================


class TestRehydrateTrimmedBookedTiles:
    """_rehydrate_trimmed_booked_tiles backfills display fields onto booked_tile
    dicts that were trimmed by session serialization."""

    def _make_activity_tile(self, tile_id: str, **extra: Any) -> Dict[str, Any]:
        """Build a minimal activity tile dict."""
        base: Dict[str, Any] = {"id": tile_id, "title": f"Tile {tile_id}"}
        base.update(extra)
        return base

    def _make_day_card(self, booked_tile: Dict[str, Any]) -> Dict[str, Any]:
        """Wrap a booked_tile in a day_card → block structure."""
        return {"day": 1, "blocks": [{"type": "activity", "booked_tile": booked_tile}]}

    # ------------------------------------------------------------------
    # Case 1: missing fields get backfilled from matching tile
    # ------------------------------------------------------------------

    def test_backfills_image_url_and_geo(self) -> None:
        """booked_tile missing image_url + geo gets both fields from the tile."""
        tile_id = "abc-123"
        booked = {"id": tile_id, "title": "Snorkel tour"}
        tile = self._make_activity_tile(
            tile_id,
            image_url="https://example.com/img.jpg",
            geo={"lat": 1.23, "lng": 4.56},
        )
        state = _make_state(
            day_cards=[self._make_day_card(booked)],
            tiles={"activities": [tile]},
        )

        _rehydrate_trimmed_booked_tiles(state)

        assert booked["image_url"] == "https://example.com/img.jpg"
        assert booked["geo"] == {"lat": 1.23, "lng": 4.56}

    def test_backfills_only_missing_field(self) -> None:
        """Only the absent field is filled; the present one is untouched."""
        tile_id = "xyz-777"
        booked = {
            "id": tile_id,
            "title": "Cooking class",
            "image_url": "https://already.com/img.jpg",
        }
        tile = self._make_activity_tile(
            tile_id,
            image_url="https://tile.com/other.jpg",
            geo={"lat": 9.0, "lng": 10.0},
        )
        state = _make_state(
            day_cards=[self._make_day_card(booked)],
            tiles={"activities": [tile]},
        )

        _rehydrate_trimmed_booked_tiles(state)

        # image_url already present — must NOT be overwritten
        assert booked["image_url"] == "https://already.com/img.jpg"
        # geo was absent — must be filled
        assert booked["geo"] == {"lat": 9.0, "lng": 10.0}

    # ------------------------------------------------------------------
    # Case 2: existing values on booked_tile are never overwritten
    # ------------------------------------------------------------------

    def test_existing_values_not_overwritten(self) -> None:
        """If booked_tile already has both image_url and geo, neither is touched."""
        tile_id = "keep-me"
        booked = {
            "id": tile_id,
            "image_url": "https://original.com/photo.jpg",
            "geo": {"lat": 0.1, "lng": 0.2},
        }
        tile = self._make_activity_tile(
            tile_id,
            image_url="https://tile.com/different.jpg",
            geo={"lat": 99.0, "lng": 99.0},
        )
        state = _make_state(
            day_cards=[self._make_day_card(booked)],
            tiles={"activities": [tile]},
        )

        _rehydrate_trimmed_booked_tiles(state)

        assert booked["image_url"] == "https://original.com/photo.jpg"
        assert booked["geo"] == {"lat": 0.1, "lng": 0.2}

    # ------------------------------------------------------------------
    # Case 3: no-op when tiles are empty or missing "activities" key
    # ------------------------------------------------------------------

    def test_noop_when_tiles_is_empty_dict(self) -> None:
        """Empty tiles dict — function returns without error, day_cards unchanged."""
        tile_id = "t1"
        booked = {"id": tile_id}
        state = _make_state(
            day_cards=[self._make_day_card(booked)],
            tiles={},
        )

        _rehydrate_trimmed_booked_tiles(state)  # must not raise

        assert "image_url" not in booked
        assert "geo" not in booked

    def test_noop_when_tiles_missing_activities_key(self) -> None:
        """tiles dict without 'activities' key — no error, no mutation."""
        tile_id = "t2"
        booked = {"id": tile_id}
        state = _make_state(
            day_cards=[self._make_day_card(booked)],
            tiles={"flights": [], "hotels": []},
        )

        _rehydrate_trimmed_booked_tiles(state)

        assert "image_url" not in booked
        assert "geo" not in booked

    def test_noop_when_activities_list_is_empty(self) -> None:
        """tiles['activities'] is an empty list — no error, no mutation."""
        tile_id = "t3"
        booked = {"id": tile_id}
        state = _make_state(
            day_cards=[self._make_day_card(booked)],
            tiles={"activities": []},
        )

        _rehydrate_trimmed_booked_tiles(state)

        assert "image_url" not in booked

    # ------------------------------------------------------------------
    # Case 4: no-op when day_cards are empty
    # ------------------------------------------------------------------

    def test_noop_when_day_cards_is_empty_list(self) -> None:
        """Empty day_cards — function returns immediately without error."""
        tile = self._make_activity_tile("t4", image_url="https://example.com/img.jpg")
        state = _make_state(
            day_cards=[],
            tiles={"activities": [tile]},
        )

        _rehydrate_trimmed_booked_tiles(state)  # must not raise

    def test_noop_when_day_cards_key_absent(self) -> None:
        """State without day_cards key — no error."""
        tile = self._make_activity_tile("t5", image_url="https://example.com/img.jpg")
        state: Dict[str, Any] = {"tiles": {"activities": [tile]}}

        _rehydrate_trimmed_booked_tiles(state)  # must not raise

    # ------------------------------------------------------------------
    # Case 5: no match on unknown tile ID — nothing patched, no error
    # ------------------------------------------------------------------

    def test_no_match_on_unknown_id(self) -> None:
        """booked_tile has an ID that doesn't exist in tiles — no error, no mutation."""
        booked = {"id": "missing-id", "title": "Mystery activity"}
        tile = self._make_activity_tile(
            "real-id-999",
            image_url="https://example.com/img.jpg",
            geo={"lat": 5.0, "lng": 6.0},
        )
        state = _make_state(
            day_cards=[self._make_day_card(booked)],
            tiles={"activities": [tile]},
        )

        _rehydrate_trimmed_booked_tiles(state)

        assert "image_url" not in booked
        assert "geo" not in booked

    def test_no_match_when_booked_tile_has_no_id(self) -> None:
        """booked_tile without an 'id' field — no error, no mutation."""
        booked = {"title": "No ID tile"}
        tile = self._make_activity_tile(
            "some-id",
            image_url="https://example.com/img.jpg",
        )
        state = _make_state(
            day_cards=[self._make_day_card(booked)],
            tiles={"activities": [tile]},
        )

        _rehydrate_trimmed_booked_tiles(state)

        assert "image_url" not in booked

    # ------------------------------------------------------------------
    # Multi-card / multi-block coverage
    # ------------------------------------------------------------------

    def test_multiple_cards_multiple_blocks(self) -> None:
        """Rehydration walks all cards and all blocks within each card."""
        booked_a = {"id": "id-a"}
        booked_b = {"id": "id-b"}
        card1 = {"day": 1, "blocks": [{"type": "activity", "booked_tile": booked_a}]}
        card2 = {"day": 2, "blocks": [{"type": "activity", "booked_tile": booked_b}]}

        tiles = [
            self._make_activity_tile("id-a", image_url="https://a.com/img.jpg"),
            self._make_activity_tile("id-b", image_url="https://b.com/img.jpg"),
        ]
        state = _make_state(
            day_cards=[card1, card2],
            tiles={"activities": tiles},
        )

        _rehydrate_trimmed_booked_tiles(state)

        assert booked_a["image_url"] == "https://a.com/img.jpg"
        assert booked_b["image_url"] == "https://b.com/img.jpg"

    def test_block_without_booked_tile_is_skipped(self) -> None:
        """Blocks lacking a booked_tile key do not cause errors."""
        card = {"day": 1, "blocks": [{"type": "free_time"}]}
        tile = self._make_activity_tile("t6", image_url="https://example.com/img.jpg")
        state = _make_state(
            day_cards=[card],
            tiles={"activities": [tile]},
        )

        _rehydrate_trimmed_booked_tiles(state)  # must not raise
