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

from typing import Any, Dict
from unittest.mock import patch

import pytest

from app.planner.coordinator import (
    _canonicalize_applied_updates,
    _compute_coordinator_s3_state,
    _compute_dispatch_list,
    _compute_preserve_list,
    _inject_specialist_tiles_into_state,
    _norm_topic,
    _normalize_specialist_plan_keys,
    _run_local_intel,
    _short_circuit_message,
    _specialist_content_to_tiles,
    _tile_refresh_types,
    build_brief,
    build_trip_state_summary,
    plan_turn,
)
from app.planner.schemas.coordinator_schemas import (
    ChangeType,
    ClassifierOutput,
    ExecutionPlan,
    StepType,
)

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

    def test_question_steps(self) -> None:
        classifier = _make_classifier(intent="QUESTION", change_type=ChangeType.QUESTION)
        plan = plan_turn(classifier, _make_state())

        step_types = [s.step_type for s in plan.steps]
        assert StepType.SHORT_CIRCUIT in step_types
        assert StepType.GENERATE_RESPONSE in step_types
        assert plan.estimated_llm_calls == 1

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
        result = _tile_refresh_types(classifier)
        assert set(result) == {"flights", "hotels", "activities"}

    def test_logistics_refreshes_flights(self) -> None:
        classifier = _make_classifier(change_type=ChangeType.LOGISTICS)
        result = _tile_refresh_types(classifier)
        assert result == ["flights"]

    def test_date_change_refreshes_flights_hotels_activities(self) -> None:
        classifier = _make_classifier(change_type=ChangeType.DATE_CHANGE)
        result = _tile_refresh_types(classifier)
        assert set(result) == {"flights", "hotels", "activities"}

    def test_add_activity_refreshes_activities(self) -> None:
        classifier = _make_classifier(change_type=ChangeType.ADD_ACTIVITY)
        result = _tile_refresh_types(classifier)
        assert result == ["activities"]


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
        """Missing coordinates result in empty geo dict."""
        section = {"content_added": [{"title": "Reef Dive"}]}
        tiles = _specialist_content_to_tiles("diving", section, "Bali")
        assert tiles[0]["geo"] == {}

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
