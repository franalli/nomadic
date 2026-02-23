"""
Tests for vertical_specialist.py — Pydantic models, helper functions, and node entry.

Covers:
1. LLMActivity / LLMConstraint / LLMSpecialistOutput schema validation
2. _migrate_legacy_constraints helper
3. convert_llm_output_to_specialist_output mapping
4. Feasibility cache key stability (make_cache_key)
5. vertical_specialist node entry: queue pop, no-destination guard, cache hit, error recovery
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.planner.hashing import make_cache_key
from app.planner.nodes.vertical_specialist import (
    LLMActivity,
    LLMConstraint,
    LLMSpecialistOutput,
    VerticalSpecialist,
    _migrate_legacy_constraints,
    convert_llm_output_to_specialist_output,
    generate_specialist_output_llm,
    vertical_specialist,
)
from app.planner.state import (
    ConstraintSeverity,
    GraphState,
    SpecialistConstraint,
    SpecialistStateOutput,
    TripPlan,
)

# Module path constants (keeps @patch lines under 100 chars)
_VS = "app.planner.nodes.vertical_specialist"
_MERGE = f"{_VS}._merge_specialist_into_state"
_SESSION = "app.db._get_async_session_factory"
_SPECIALIST_CACHE_GET = "app.services.specialist_cache.get_cached_specialist_output"

# =============================================================================
# Helpers
# =============================================================================


def _minimal_state(**overrides: Any) -> GraphState:
    """Build a minimal GraphState with sensible defaults for testing."""
    defaults: Dict[str, Any] = {
        "messages": [],
        "trip_plan": TripPlan(
            destination="Bali",
            start_date="2026-03-01",
            end_date="2026-03-07",
        ),
        "metadata": {},
    }
    defaults.update(overrides)
    return GraphState(**defaults)


# =============================================================================
# 1. LLMActivity model
# =============================================================================


class TestLLMActivity:
    """Validate LLMActivity Pydantic schema."""

    def test_valid_construction_all_fields(self):
        activity = LLMActivity(
            title="USAT Liberty Wreck",
            description="Famous WWII shipwreck dive",
            location="Tulamben",
            duration_hours=2.5,
            difficulty="intermediate",
            depth_meters=30,
            certification_required="Advanced Open Water",
            lat=-8.275,
            lng=115.592,
            logic_hook="Best visibility before noon",
        )
        assert activity.title == "USAT Liberty Wreck"
        assert activity.depth_meters == 30
        assert activity.lat == -8.275
        assert activity.lng == 115.592

    def test_defaults(self):
        activity = LLMActivity(title="Morning Dive")
        assert activity.description == ""
        assert activity.duration_hours == 3.0
        assert activity.difficulty == "beginner"
        assert activity.location is None
        assert activity.depth_meters is None
        assert activity.elevation_meters is None
        assert activity.certification_required is None
        assert activity.lat is None
        assert activity.lng is None
        assert activity.logic_hook is None

    def test_hiking_fields(self):
        activity = LLMActivity(
            title="Mount Agung Summit",
            elevation_meters=3031,
            distance_km=12.5,
        )
        assert activity.elevation_meters == 3031
        assert activity.distance_km == 12.5

    def test_skiing_fields(self):
        activity = LLMActivity(
            title="Valluga Off-Piste",
            vertical_meters=1500,
        )
        assert activity.vertical_meters == 1500


# =============================================================================
# 2. LLMConstraint model
# =============================================================================


class TestLLMConstraint:
    """Validate LLMConstraint Pydantic schema."""

    def test_valid_construction(self):
        c = LLMConstraint(
            constraint_id="no_fly_24h",
            constraint_type="blocking",
            applies_to_categories=["flights"],
            buffer_hours=24,
            reason="Decompression sickness risk",
            label="24h no-fly buffer",
            icon="X",
        )
        assert c.constraint_id == "no_fly_24h"
        assert c.buffer_hours == 24

    def test_required_field_constraint_id(self):
        """constraint_id is required (no default)."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LLMConstraint()  # type: ignore[call-arg]

    def test_defaults(self):
        c = LLMConstraint(constraint_id="test_rule")
        assert c.constraint_type == "blocking"
        assert c.applies_to_categories == []
        assert c.buffer_hours is None
        assert c.reason == ""
        assert c.label is None
        assert c.icon is None


# =============================================================================
# 3. LLMSpecialistOutput model
# =============================================================================


class TestLLMSpecialistOutput:
    """Validate LLMSpecialistOutput Pydantic schema."""

    def test_valid_full_output(self):
        output = LLMSpecialistOutput(
            feasibility_status="feasible",
            feasibility_reason=None,
            activities=[
                LLMActivity(title="Dive 1"),
                LLMActivity(title="Dive 2"),
            ],
            constraints=[
                LLMConstraint(
                    constraint_id="no_fly_24h",
                    buffer_hours=24,
                    reason="Safety",
                ),
            ],
        )
        assert output.feasibility_status == "feasible"
        assert len(output.activities) == 2
        assert len(output.constraints) == 1

    def test_defaults(self):
        output = LLMSpecialistOutput()
        assert output.feasibility_status == "feasible"
        assert output.feasibility_reason is None
        assert output.activities == []
        assert output.constraints == []

    def test_infeasible_output(self):
        output = LLMSpecialistOutput(
            feasibility_status="infeasible",
            feasibility_reason="Landlocked city — no coastline for diving",
        )
        assert output.feasibility_status == "infeasible"
        assert "Landlocked" in output.feasibility_reason

    def test_serialization_roundtrip(self):
        output = LLMSpecialistOutput(
            feasibility_status="feasible",
            activities=[LLMActivity(title="Trail Run", distance_km=8.0)],
            constraints=[LLMConstraint(constraint_id="early_start")],
        )
        data = output.model_dump()
        restored = LLMSpecialistOutput.model_validate(data)
        assert restored.activities[0].title == "Trail Run"
        assert restored.constraints[0].constraint_id == "early_start"


# =============================================================================
# 4. Feasibility cache key stability
# =============================================================================


class TestFeasibilityCacheKey:
    """Verify make_cache_key produces stable, distinct keys."""

    def test_same_inputs_same_key(self):
        k1 = make_cache_key("feasibility", "v2", "diving", "Bali")
        k2 = make_cache_key("feasibility", "v2", "diving", "Bali")
        assert k1 == k2

    def test_different_topic_different_key(self):
        k_diving = make_cache_key("feasibility", "v2", "diving", "Bali")
        k_hiking = make_cache_key("feasibility", "v2", "hiking", "Bali")
        assert k_diving != k_hiking

    def test_different_destination_different_key(self):
        k_bali = make_cache_key("feasibility", "v2", "diving", "Bali")
        k_paris = make_cache_key("feasibility", "v2", "diving", "Paris")
        assert k_bali != k_paris


# =============================================================================
# 5. _migrate_legacy_constraints helper
# =============================================================================


class TestMigrateLegacyConstraints:
    """Verify backward compat migration for constraint_id."""

    def test_adds_id_from_rule_when_missing(self):
        c = SpecialistConstraint(
            constraint_id="",
            type="safety",
            rule="min_24h_buffer_after_dive",
            severity=ConstraintSeverity.BLOCKING,
        )
        result = _migrate_legacy_constraints([c])
        assert result[0].constraint_id == "min_24h_buffer_after_dive"

    def test_preserves_existing_id(self):
        c = SpecialistConstraint(
            constraint_id="custom_id",
            type="safety",
            rule="some_rule",
            severity=ConstraintSeverity.STRONG,
        )
        result = _migrate_legacy_constraints([c])
        assert result[0].constraint_id == "custom_id"

    def test_empty_list(self):
        result = _migrate_legacy_constraints([])
        assert result == []


# =============================================================================
# 6. convert_llm_output_to_specialist_output
# =============================================================================


class TestConvertLLMOutput:
    """Test LLMSpecialistOutput -> SpecialistStateOutput mapping."""

    @patch("app.services.unsplash.get_image_url_sync", return_value="/img/test.jpg")
    def test_activities_become_itinerary_blocks(self, _mock_img):
        llm_out = LLMSpecialistOutput(
            feasibility_status="feasible",
            activities=[
                LLMActivity(
                    title="Dive A",
                    description="Desc A",
                    location="Tulamben",
                    duration_hours=2.0,
                    difficulty="intermediate",
                    lat=-8.27,
                    lng=115.59,
                ),
                LLMActivity(title="Dive B"),
            ],
        )
        result = convert_llm_output_to_specialist_output(llm_out, "diving", "Bali")

        assert isinstance(result, SpecialistStateOutput)
        assert result.feasibility_status == "feasible"
        assert len(result.content_blocks) == 2

        block = result.content_blocks[0]
        assert block.title == "Dive A"
        assert block.day == 2  # starts day 2 (day 1 is arrival)
        assert block.type == "activity"
        assert block.source_specialist == "diving"
        assert block.skill_level == "intermediate"
        assert block.coordinates == [115.59, -8.27]  # [lng, lat] Mapbox convention
        assert block.image_url == "/img/test.jpg"

    @patch("app.services.unsplash.get_image_url_sync", return_value=None)
    def test_constraints_become_specialist_constraints(self, _mock_img):
        llm_out = LLMSpecialistOutput(
            feasibility_status="feasible",
            constraints=[
                LLMConstraint(
                    constraint_id="no_fly_24h",
                    constraint_type="blocking",
                    applies_to_categories=["flights"],
                    buffer_hours=24,
                    reason="Decompression sickness risk",
                    label="No-fly 24h",
                ),
            ],
        )
        result = convert_llm_output_to_specialist_output(llm_out, "diving", "Bali")

        assert len(result.constraints) == 1
        c = result.constraints[0]
        assert c.constraint_id == "no_fly_24h"
        assert c.severity == ConstraintSeverity.BLOCKING
        assert c.buffer_hours == 24
        assert c.applies_to_categories == ["flights"]

    @patch("app.services.unsplash.get_image_url_sync", return_value=None)
    def test_severity_mapping(self, _mock_img):
        """Verify string severity values map to ConstraintSeverity enums."""
        llm_out = LLMSpecialistOutput(
            constraints=[
                LLMConstraint(constraint_id="c1", constraint_type="blocking"),
                LLMConstraint(constraint_id="c2", constraint_type="strong"),
                LLMConstraint(constraint_id="c3", constraint_type="soft"),
                LLMConstraint(constraint_id="c4", constraint_type="unknown_type"),
            ],
        )
        result = convert_llm_output_to_specialist_output(llm_out, "diving", "Bali")

        assert result.constraints[0].severity == ConstraintSeverity.BLOCKING
        assert result.constraints[1].severity == ConstraintSeverity.STRONG
        assert result.constraints[2].severity == ConstraintSeverity.SOFT
        assert result.constraints[3].severity == ConstraintSeverity.STRONG  # fallback

    @patch("app.services.unsplash.get_image_url_sync", return_value=None)
    def test_no_coordinates_when_lat_lng_missing(self, _mock_img):
        llm_out = LLMSpecialistOutput(
            activities=[LLMActivity(title="No Coords")],
        )
        result = convert_llm_output_to_specialist_output(llm_out, "diving", "Bali")
        assert result.content_blocks[0].coordinates is None


# =============================================================================
# 7. VerticalSpecialist._calculate_activity_days
# =============================================================================


class TestCalculateActivityDays:
    """Test trip duration -> available activity day calculation."""

    def test_7_day_trip_diving(self):
        """7-day trip with diving: 7 - 2 (arrival/departure) - 1 (no-fly) = 4."""
        state = _minimal_state()
        specialist = VerticalSpecialist("diving")
        result = specialist._calculate_activity_days(state)
        assert result == 4

    def test_7_day_trip_hiking(self):
        """7-day hiking trip: 7 - 2 (arrival/departure) - 1 (altitude buffer) = 4."""
        state = _minimal_state()
        specialist = VerticalSpecialist("hiking")
        result = specialist._calculate_activity_days(state)
        assert result == 4

    def test_no_dates_returns_default(self):
        state = _minimal_state(trip_plan=TripPlan(destination="Bali"))
        specialist = VerticalSpecialist("diving")
        result = specialist._calculate_activity_days(state)
        assert result == 3  # default when no dates

    def test_very_short_trip_returns_zero(self):
        """2-day trip: 2 - 2 = 0 (no activity days)."""
        state = _minimal_state(
            trip_plan=TripPlan(
                destination="Bali",
                start_date="2026-03-01",
                end_date="2026-03-02",
            )
        )
        specialist = VerticalSpecialist("hiking")
        result = specialist._calculate_activity_days(state)
        assert result == 0

    def test_result_is_cached(self):
        """Second call returns cached value without recalculation."""
        state = _minimal_state()
        specialist = VerticalSpecialist("diving")
        first = specialist._calculate_activity_days(state)
        # Mutate plan dates to prove caching
        state.trip_plan.start_date = "2026-01-01"
        state.trip_plan.end_date = "2026-01-30"
        second = specialist._calculate_activity_days(state)
        assert first == second  # still cached


# =============================================================================
# 8. vertical_specialist node entry — async tests
# =============================================================================


def _mock_compact_logger():
    """Return a mock CompactLogger that accepts any calls."""
    clog = MagicMock()
    clog.node_start = MagicMock()
    clog.node_end = MagicMock()
    clog.event = MagicMock()
    return clog


def _build_section(
    specialist_type: str,
    destination: str,
    start_date: str,
    end_date: str,
    *,
    feasibility_status: str = "feasible",
    content_added: List[Dict[str, Any]] | None = None,
    day_pref: int | None = None,
) -> Dict[str, Any]:
    """Build a minimal strategy_section dict for cache-hit tests."""
    return {
        "specialist_type": specialist_type,
        "subtitle": destination,
        "_cache_dates": f"{start_date}:{end_date}",
        "_cache_day_pref": day_pref,
        "feasibility_status": feasibility_status,
        "content_added": content_added or [{"title": "Cached Dive"}],
    }


@pytest.mark.asyncio
class TestVerticalSpecialistNodeEntry:
    """Test the vertical_specialist() graph node function."""

    @patch(_MERGE, new_callable=AsyncMock)
    @patch(_SESSION)
    async def test_queue_pop_sets_active_specialist(self, mock_session_factory, mock_merge):
        """When active_specialist is None and pending_specialists has items, pop the first."""
        mock_session_factory.return_value = MagicMock(
            __aenter__=AsyncMock(return_value=MagicMock()),
            __aexit__=AsyncMock(return_value=False),
        )
        # Make the context manager on the factory's return value work
        mock_db = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory.return_value = MagicMock(return_value=mock_session_ctx)

        state = _minimal_state(
            active_specialist=None,
            pending_specialists=["diving", "hiking"],
        )

        # Mock the parallel LLM generation to avoid real LLM calls
        with (
            patch(
                "app.planner.nodes.vertical_specialist.generate_all_specialists_parallel",
                new_callable=AsyncMock,
                return_value={
                    "diving": LLMSpecialistOutput(feasibility_status="feasible"),
                    "hiking": LLMSpecialistOutput(feasibility_status="feasible"),
                },
            ),
            patch(
                "app.planner.nodes.vertical_specialist.get_trip_settings",
                return_value=MagicMock(
                    activity_settings=MagicMock(skill_level=None),
                ),
            ),
        ):
            result = await vertical_specialist(state)

        # After node, active_specialist should be cleared
        assert result.active_specialist is None
        # _merge_specialist_into_state called for each topic
        assert mock_merge.call_count >= 1

    @patch(_MERGE, new_callable=AsyncMock)
    @patch(_SESSION)
    async def test_no_specialist_returns_state_unchanged(self, mock_session_factory, mock_merge):
        """When active_specialist is None and pending is empty, skip."""
        state = _minimal_state(
            active_specialist=None,
            pending_specialists=[],
        )
        result = await vertical_specialist(state)
        assert result is state
        mock_merge.assert_not_called()

    @patch(_MERGE, new_callable=AsyncMock)
    @patch(_SESSION)
    async def test_no_destination_still_runs_merge(self, mock_session_factory, mock_merge):
        """Node runs merge even without destination (specialist handles the guard)."""
        mock_db = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory.return_value = MagicMock(return_value=mock_session_ctx)

        state = _minimal_state(
            trip_plan=TripPlan(destination=None),
            active_specialist="diving",
            pending_specialists=[],
        )

        with (
            patch(
                "app.planner.nodes.vertical_specialist.generate_specialist_output_llm",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(_SPECIALIST_CACHE_GET, new_callable=AsyncMock, return_value=None),
            patch(
                "app.planner.nodes.vertical_specialist.get_trip_settings",
                return_value=MagicMock(
                    activity_settings=MagicMock(skill_level=None),
                ),
            ),
        ):
            result = await vertical_specialist(state)

        # Should have called merge (specialist handles no-destination internally)
        assert mock_merge.call_count == 1
        # active_specialist cleared at end
        assert result.active_specialist is None

    @patch(_MERGE, new_callable=AsyncMock)
    @patch(_SESSION)
    async def test_active_specialist_cleared_after_processing(
        self, mock_session_factory, mock_merge
    ):
        """active_specialist is set to None after all specialists processed."""
        mock_db = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory.return_value = MagicMock(return_value=mock_session_ctx)

        state = _minimal_state(
            active_specialist="diving",
            pending_specialists=[],
        )

        with (
            patch(
                "app.planner.nodes.vertical_specialist.generate_specialist_output_llm",
                new_callable=AsyncMock,
                return_value=LLMSpecialistOutput(feasibility_status="feasible"),
            ),
            patch(_SPECIALIST_CACHE_GET, new_callable=AsyncMock, return_value=None),
            patch(
                "app.planner.nodes.vertical_specialist.get_trip_settings",
                return_value=MagicMock(
                    activity_settings=MagicMock(skill_level=None),
                ),
            ),
        ):
            result = await vertical_specialist(state)

        assert result.active_specialist is None


# =============================================================================
# 9. _merge_specialist_into_state — selective regen cache hit
# =============================================================================


@pytest.mark.asyncio
class TestMergeSpecialistCacheHit:
    """Test selective regeneration cache hit in _merge_specialist_into_state."""

    async def test_cache_hit_skips_llm(self):
        """When strategy_sections has a matching section, skip LLM call."""
        from app.planner.nodes.vertical_specialist import _merge_specialist_into_state

        state = _minimal_state(
            active_specialist="diving",
            metadata={
                "strategy_sections": [
                    _build_section(
                        "diving",
                        "Bali",
                        "2026-03-01",
                        "2026-03-07",
                    ),
                ],
                "trip_inputs": {"activity_settings": {"day_preferences": {}}},
            },
        )

        clog = _mock_compact_logger()
        node_start_time = 0.0

        # Patch generate_output to verify it is NOT called
        with patch.object(
            VerticalSpecialist,
            "generate_output",
            new_callable=AsyncMock,
        ) as mock_generate:
            await _merge_specialist_into_state(state, "diving", node_start_time, clog)
            mock_generate.assert_not_called()

        # Topic should be recorded as last executed
        assert state.metadata.get("last_executed_specialist") == "diving"

    async def test_cache_miss_when_destination_differs(self):
        """When cached section destination differs, should NOT cache-hit."""
        from app.planner.nodes.vertical_specialist import _merge_specialist_into_state

        state = _minimal_state(
            active_specialist="diving",
            metadata={
                "strategy_sections": [
                    _build_section(
                        "diving",
                        "Maldives",  # different destination
                        "2026-03-01",
                        "2026-03-07",
                    ),
                ],
                "trip_inputs": {"activity_settings": {"day_preferences": {}}},
                "parallel_llm_results": {
                    "diving": LLMSpecialistOutput(
                        feasibility_status="feasible",
                        activities=[LLMActivity(title="Reef Dive")],
                    ).model_dump(),
                },
            },
        )

        clog = _mock_compact_logger()

        # Patch Unsplash calls to avoid real HTTP
        with (
            patch(
                "app.services.unsplash.get_image_url_sync",
                return_value=None,
            ),
            patch(
                "app.services.unsplash.prefetch_destination_images",
                new_callable=AsyncMock,
            ),
        ):
            await _merge_specialist_into_state(state, "diving", 0.0, clog)

        # Should have processed the specialist (not cache hit)
        assert state.metadata.get("last_executed_specialist") == "diving"
        # Should have content blocks from the LLM output
        assert len(state.trip_plan.itinerary_blocks) > 0

    async def test_infeasible_cached_at_same_destination_skips(self):
        """Infeasible result cached at same destination is reused without LLM."""
        from app.planner.nodes.vertical_specialist import _merge_specialist_into_state

        state = _minimal_state(
            active_specialist="diving",
            metadata={
                "strategy_sections": [
                    {
                        "specialist_type": "diving",
                        "subtitle": "Bali",
                        "_cache_dates": "2026-01-01:2026-01-07",  # different dates
                        "_cache_day_pref": None,
                        "feasibility_status": "infeasible",
                        "feasibility_reason": "No diving possible",
                        "alternative_suggestion": "Try Maldives",
                        "content_added": [],
                    },
                ],
                "trip_inputs": {"activity_settings": {"day_preferences": {}}},
            },
        )

        clog = _mock_compact_logger()

        with patch.object(
            VerticalSpecialist,
            "generate_output",
            new_callable=AsyncMock,
        ) as mock_generate:
            await _merge_specialist_into_state(state, "diving", 0.0, clog)
            mock_generate.assert_not_called()

        assert state.metadata.get("specialist_infeasible") is True
        assert "SPECIALIST_INFEASIBLE" in state.ui_events


# =============================================================================
# 10. VerticalSpecialist.generate_output — trip too short
# =============================================================================


@pytest.mark.asyncio
class TestGenerateOutputEdgeCases:
    """Test VerticalSpecialist.generate_output for edge cases."""

    async def test_trip_too_short_returns_infeasible(self):
        """2-day trip should return infeasible (no activity days)."""
        state = _minimal_state(
            trip_plan=TripPlan(
                destination="Bali",
                start_date="2026-03-01",
                end_date="2026-03-02",
            ),
        )
        specialist = VerticalSpecialist("diving")
        result = await specialist.generate_output(state)
        assert result.feasibility_status == "infeasible"
        assert "too short" in (result.feasibility_reason or "").lower()
        assert result.content_blocks == []
        assert result.constraints == []

    async def test_generate_bookends(self):
        """Bookends add arrival on day 1 and departure on last day."""
        state = _minimal_state()
        specialist = VerticalSpecialist("diving")
        bookends = specialist.generate_bookends(state)

        assert len(bookends) == 2
        assert bookends[0].day == 1
        assert bookends[0].buffer_type == "arrival"
        assert bookends[0].is_buffer is True
        assert bookends[1].day == 7  # 7-day trip
        assert bookends[1].buffer_type == "departure"

    async def test_generate_enhancements_uses_registry(self):
        """Enhancements come from the specialist registry."""
        state = _minimal_state()
        specialist = VerticalSpecialist("diving")
        enhancements = specialist.generate_enhancements(state)
        # Should return a list (may be empty if registry has no enhancements)
        assert isinstance(enhancements, list)


# =============================================================================
# 11. generate_specialist_output_llm — model fallback behavior
# =============================================================================


@pytest.mark.asyncio
async def test_generate_specialist_output_llm_retries_with_fallback_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Primary model failure retries with SPECIALIST_FALLBACK_MODEL and succeeds."""
    trip_plan = TripPlan(
        destination="Bali",
        start_date="2026-03-01",
        end_date="2026-03-07",
    )

    primary_structured = MagicMock()
    primary_structured.ainvoke = AsyncMock(side_effect=RuntimeError("primary timeout"))
    fallback_structured = MagicMock()
    fallback_structured.ainvoke = AsyncMock(
        return_value={
            "parsed": {
                "feasibility_status": "feasible",
                "activities": [{"title": "Reef Dive"}],
                "constraints": [],
            }
        }
    )

    primary_llm = MagicMock()
    primary_llm.with_structured_output.return_value = primary_structured
    fallback_llm = MagicMock()
    fallback_llm.with_structured_output.return_value = fallback_structured

    mock_get_llm = MagicMock(side_effect=[primary_llm, fallback_llm])
    mock_debug_log = MagicMock()

    monkeypatch.setattr(settings, "specialist_model", "gpt-4o")
    monkeypatch.setattr(settings, "specialist_fallback_model", "gemini-2.5-flash")

    with (
        patch(f"{_VS}.load_prompt", return_value="System prompt"),
        patch(f"{_VS}.get_llm_by_model", mock_get_llm),
        patch("app.debug_utils._debug_log", mock_debug_log),
    ):
        output = await generate_specialist_output_llm(
            topic="diving",
            destination="Bali",
            trip_plan=trip_plan,
            db=None,
            skip_cache_lookup=True,
        )

    assert output is not None
    assert output.feasibility_status == "feasible"
    assert len(output.activities) == 1
    assert mock_get_llm.call_count == 2
    assert mock_get_llm.call_args_list[0].args[0] == "gpt-4o"
    assert mock_get_llm.call_args_list[1].args[0] == "gemini-2.5-flash"

    logs = " | ".join(str(call.args[0]) for call in mock_debug_log.call_args_list if call.args)
    assert "Primary model 'gpt-4o' failed" in logs
    assert "Retrying with fallback model 'gemini-2.5-flash'" in logs
    assert "Success (fallback=gemini-2.5-flash)" in logs


@pytest.mark.asyncio
async def test_generate_specialist_output_llm_logs_when_primary_and_fallback_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both model failures are logged and function returns None."""
    trip_plan = TripPlan(
        destination="Bali",
        start_date="2026-03-01",
        end_date="2026-03-07",
    )

    primary_structured = MagicMock()
    primary_structured.ainvoke = AsyncMock(side_effect=RuntimeError("primary timeout"))
    fallback_structured = MagicMock()
    fallback_structured.ainvoke = AsyncMock(side_effect=RuntimeError("fallback timeout"))

    primary_llm = MagicMock()
    primary_llm.with_structured_output.return_value = primary_structured
    fallback_llm = MagicMock()
    fallback_llm.with_structured_output.return_value = fallback_structured

    mock_get_llm = MagicMock(side_effect=[primary_llm, fallback_llm])
    mock_debug_log = MagicMock()

    monkeypatch.setattr(settings, "specialist_model", "gpt-4o")
    monkeypatch.setattr(settings, "specialist_fallback_model", "gemini-2.5-flash")

    with (
        patch(f"{_VS}.load_prompt", return_value="System prompt"),
        patch(f"{_VS}.get_llm_by_model", mock_get_llm),
        patch("app.debug_utils._debug_log", mock_debug_log),
    ):
        output = await generate_specialist_output_llm(
            topic="diving",
            destination="Bali",
            trip_plan=trip_plan,
            db=None,
            skip_cache_lookup=True,
        )

    assert output is None
    assert mock_get_llm.call_count == 2

    logs = " | ".join(str(call.args[0]) for call in mock_debug_log.call_args_list if call.args)
    assert "Primary model 'gpt-4o' failed" in logs
    assert "Retrying with fallback model 'gemini-2.5-flash'" in logs
    assert "Fallback model 'gemini-2.5-flash' failed" in logs
    assert "FAILED for diving" in logs
