# backend/tests/test_local_expert.py
"""
Unit tests for local_expert.py -- the "Logistics Concierge" node.

Tests cover:
- No destination: early return, active_specialist cleared
- Cache HIT: existing section with matching destination skips rebuild
- Cache MISS: destination change triggers full pipeline
- Static knowledge path: constraints built via build_local_expert_section
- Empty knowledge fallback: generates "Explore {dest}" recommendation
- Error recovery: exception in _run_local_expert does not crash node
- Multi-specialist queue pop: pending_specialists drives activation
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from app.planner.nodes.expert_constraints import (
    LocalConstraint,
    LocalExpertOutput,
    LocalRecommendation,
)
from app.planner.state.graph_state import GraphState, TripPlan

# Import the MODULE object (not the function) so monkeypatch.setattr works
# correctly. The module and the public function share the name "local_expert",
# which makes string-path based patching ambiguous.
_le_mod = importlib.import_module("app.planner.nodes.local_expert")


# =============================================================================
# Helpers
# =============================================================================


def _make_state(
    *,
    destination: str | None = None,
    active_specialist: str | None = None,
    pending_specialists: List[str] | None = None,
    metadata: Dict[str, Any] | None = None,
) -> GraphState:
    """Build a minimal GraphState for local expert tests."""
    plan = TripPlan(destination=destination)
    state = GraphState(
        trip_plan=plan,
        active_specialist=active_specialist,
        pending_specialists=pending_specialists or [],
        metadata=metadata or {},
    )
    return state


def _patch_common(monkeypatch: pytest.MonkeyPatch) -> Dict[str, MagicMock]:
    """Patch all external dependencies of local_expert and return mocks dict.

    Uses the module object (_le_mod) for all setattr calls to avoid the
    name collision between the module and its public function.

    Patches:
    - _get_static_local_knowledge (returns empty by default)
    - build_local_expert_section (returns stub section)
    - upsert_section (no-op)
    - mark_topic_executed (no-op)
    - get_destination_gallery (returns [])
    - DEMO_MANIFEST (empty dict)
    """
    mocks: Dict[str, MagicMock] = {}

    # Static knowledge -- default empty
    mock_static = MagicMock(return_value=LocalExpertOutput())
    monkeypatch.setattr(_le_mod, "_get_static_local_knowledge", mock_static)
    mocks["static_knowledge"] = mock_static

    # Section builder
    mock_build = MagicMock(
        return_value={
            "id": "strategy_local_expert",
            "specialist_type": "local_expert",
            "title": "TestDest Trip Overview",
            "constraints_applied": [],
            "content_added": [],
        }
    )
    monkeypatch.setattr(_le_mod, "build_local_expert_section", mock_build)
    mocks["build_section"] = mock_build

    mock_upsert = MagicMock()
    monkeypatch.setattr(_le_mod, "upsert_section", mock_upsert)
    mocks["upsert_section"] = mock_upsert

    mock_mark = MagicMock()
    monkeypatch.setattr(_le_mod, "mark_topic_executed", mock_mark)
    mocks["mark_topic"] = mock_mark

    # Gallery -- empty list
    monkeypatch.setattr(_le_mod, "get_destination_gallery", lambda _: [])

    # DEMO_MANIFEST -- empty dict (no curated galleries)
    monkeypatch.setattr(_le_mod, "DEMO_MANIFEST", {})

    return mocks


# =============================================================================
# 1. No destination -> early return
# =============================================================================


class TestNoDestination:
    """When trip_plan.destination is None, local_expert returns early."""

    @pytest.mark.asyncio
    async def test_early_return_no_destination(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_common(monkeypatch)
        state = _make_state(destination=None, active_specialist="local_expert")

        result = await _le_mod.local_expert(state)

        assert result.active_specialist is None
        assert result.metadata.get("last_executed_specialist") == "local_expert"

    @pytest.mark.asyncio
    async def test_no_destination_does_not_call_build(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mocks = _patch_common(monkeypatch)
        state = _make_state(destination=None, active_specialist="local_expert")

        await _le_mod.local_expert(state)

        mocks["build_section"].assert_not_called()
        mocks["upsert_section"].assert_not_called()
        mocks["mark_topic"].assert_not_called()


# =============================================================================
# 2. Cache HIT -> existing section with matching destination
# =============================================================================


class TestCacheHit:
    """When strategy_sections contains a local_expert section whose title
    includes the current destination, the node returns early (no rebuild)."""

    @pytest.mark.asyncio
    async def test_cache_hit_skips_rebuild(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mocks = _patch_common(monkeypatch)
        state = _make_state(
            destination="Tokyo",
            active_specialist="local_expert",
            metadata={
                "strategy_sections": [
                    {
                        "specialist_type": "local_expert",
                        "title": "Tokyo Trip Overview",
                    }
                ]
            },
        )

        result = await _le_mod.local_expert(state)

        assert result.active_specialist is None
        assert result.metadata.get("last_executed_specialist") == "local_expert"
        # Should NOT call static knowledge or build
        mocks["static_knowledge"].assert_not_called()
        mocks["build_section"].assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_hit_with_substring_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Destination 'Bali' matches title 'Bali Trip Overview'."""
        mocks = _patch_common(monkeypatch)
        state = _make_state(
            destination="Bali",
            active_specialist="local_expert",
            metadata={
                "strategy_sections": [
                    {
                        "specialist_type": "local_expert",
                        "title": "Bali Trip Overview",
                    }
                ]
            },
        )

        await _le_mod.local_expert(state)

        mocks["static_knowledge"].assert_not_called()


# =============================================================================
# 3. Cache MISS -> destination changed
# =============================================================================


class TestCacheMiss:
    """When cached section title does not contain current destination,
    the node runs the full pipeline."""

    @pytest.mark.asyncio
    async def test_cache_miss_runs_pipeline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOCAL_EXPERT_USE_LLM", "false")
        mocks = _patch_common(monkeypatch)
        state = _make_state(
            destination="Paris",
            active_specialist="local_expert",
            metadata={
                "strategy_sections": [
                    {
                        "specialist_type": "local_expert",
                        "title": "Tokyo Trip Overview",
                    }
                ]
            },
        )

        result = await _le_mod.local_expert(state)

        # Full pipeline executed
        mocks["static_knowledge"].assert_called_once_with("Paris")
        mocks["build_section"].assert_called_once()
        mocks["upsert_section"].assert_called_once()
        mocks["mark_topic"].assert_called_once()
        assert result.active_specialist is None

    @pytest.mark.asyncio
    async def test_no_cached_section_runs_pipeline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When no cached section exists at all, runs full pipeline."""
        monkeypatch.setenv("LOCAL_EXPERT_USE_LLM", "false")
        mocks = _patch_common(monkeypatch)
        state = _make_state(
            destination="Rome",
            active_specialist="local_expert",
            metadata={},
        )

        await _le_mod.local_expert(state)

        mocks["static_knowledge"].assert_called_once_with("Rome")
        mocks["build_section"].assert_called_once()


# =============================================================================
# 4. Static knowledge path -> constraints built via build_local_expert_section
# =============================================================================


class TestStaticKnowledgePath:
    """When _get_static_local_knowledge returns constraints, verify section
    is built with those constraints via build_local_expert_section."""

    @pytest.mark.asyncio
    async def test_static_constraints_flow_to_section(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LOCAL_EXPERT_USE_LLM", "false")
        mocks = _patch_common(monkeypatch)

        static_output = LocalExpertOutput(
            constraints=[
                LocalConstraint(
                    type="cultural",
                    description="Cover shoulders in temples",
                    severity="warning",
                ),
                LocalConstraint(
                    type="safety",
                    description="Tap water not safe",
                    severity="warning",
                ),
            ],
            recommendations=[
                LocalRecommendation(
                    title="Visit Ubud",
                    description="Rice terraces and monkey forest",
                    category="attraction",
                    logic_hook="Morning visit beats crowds",
                ),
            ],
        )
        mocks["static_knowledge"].return_value = static_output

        state = _make_state(destination="Bali", active_specialist="local_expert")

        result = await _le_mod.local_expert(state)

        # build_local_expert_section called with constraint data
        mocks["build_section"].assert_called_once()
        call_kwargs = mocks["build_section"].call_args
        assert call_kwargs.kwargs["destination"] == "Bali"
        # Bullets come from constraint descriptions (up to 3)
        assert "Cover shoulders in temples" in call_kwargs.kwargs["bullets"]
        # must_dos come from recommendation titles (up to 5)
        assert "Visit Ubud" in call_kwargs.kwargs["must_dos"]
        # constraints_applied has the mapped constraint dicts
        assert len(call_kwargs.kwargs["constraints_applied"]) == 2
        assert call_kwargs.kwargs["constraints_applied"][0]["rule"] == "Cover shoulders in temples"
        # content_added has mapped recommendation dicts
        assert len(call_kwargs.kwargs["content_added"]) == 1
        assert call_kwargs.kwargs["content_added"][0]["title"] == "Visit Ubud"

        # State tracking
        assert result.metadata.get("local_expert_ran") is True
        assert result.metadata.get("last_executed_specialist") == "local_expert"
        assert result.active_specialist is None

    @pytest.mark.asyncio
    async def test_upsert_and_mark_called(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOCAL_EXPERT_USE_LLM", "false")
        mocks = _patch_common(monkeypatch)
        mocks["static_knowledge"].return_value = LocalExpertOutput(
            constraints=[
                LocalConstraint(
                    type="booking_window",
                    description="Book Eiffel Tower in advance",
                    severity="warning",
                )
            ],
        )

        state = _make_state(destination="Paris", active_specialist="local_expert")

        await _le_mod.local_expert(state)

        mocks["upsert_section"].assert_called_once()
        # Verify upsert mode is "appendable"
        call_args = mocks["upsert_section"].call_args
        assert call_args.kwargs.get("mode") == "appendable"

        mocks["mark_topic"].assert_called_once_with(state.metadata, "local_expert")


# =============================================================================
# 5. Empty knowledge fallback -> "Explore {dest}" recommendation
# =============================================================================


class TestEmptyKnowledgeFallback:
    """When _get_static_local_knowledge returns empty output (no constraints,
    no recommendations), node creates a fallback 'Explore {dest}' recommendation."""

    @pytest.mark.asyncio
    async def test_fallback_recommendation_created(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOCAL_EXPERT_USE_LLM", "false")
        mocks = _patch_common(monkeypatch)
        # Default mock already returns empty LocalExpertOutput

        state = _make_state(destination="Timbuktu", active_specialist="local_expert")

        await _le_mod.local_expert(state)

        mocks["build_section"].assert_called_once()
        call_kwargs = mocks["build_section"].call_args

        # must_dos should contain the fallback "Explore Timbuktu"
        assert "Explore Timbuktu" in call_kwargs.kwargs["must_dos"]

        # content_added should have the fallback recommendation
        content = call_kwargs.kwargs["content_added"]
        assert len(content) == 1
        assert content[0]["title"] == "Explore Timbuktu"
        assert content[0]["type"] == "general"

        # constraints_applied should be empty (no constraints)
        assert call_kwargs.kwargs["constraints_applied"] == []

    @pytest.mark.asyncio
    async def test_fallback_description_includes_destination(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LOCAL_EXPERT_USE_LLM", "false")
        mocks = _patch_common(monkeypatch)

        state = _make_state(destination="Reykjavik", active_specialist="local_expert")

        await _le_mod.local_expert(state)

        call_kwargs = mocks["build_section"].call_args
        content = call_kwargs.kwargs["content_added"]
        assert "Reykjavik" in content[0]["description"]


# =============================================================================
# 6. Error recovery -> exception does not crash node
# =============================================================================


class TestErrorRecovery:
    """When _run_local_expert raises an exception, local_expert catches it
    and returns state without crashing."""

    @pytest.mark.asyncio
    async def test_exception_returns_state_gracefully(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_common(monkeypatch)

        # Patch _run_local_expert to raise
        async def _exploding_run(*args, **kwargs):
            raise RuntimeError("LLM provider exploded")

        monkeypatch.setattr(_le_mod, "_run_local_expert", _exploding_run)

        state = _make_state(destination="Dubai", active_specialist="local_expert")

        result = await _le_mod.local_expert(state)

        # Node does NOT raise
        assert result is state
        assert result.active_specialist is None
        assert result.metadata.get("last_executed_specialist") == "local_expert"

    @pytest.mark.asyncio
    async def test_exception_preserves_existing_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_common(monkeypatch)

        async def _exploding_run(*args, **kwargs):
            raise ValueError("bad data")

        monkeypatch.setattr(_le_mod, "_run_local_expert", _exploding_run)

        state = _make_state(
            destination="London",
            active_specialist="local_expert",
            metadata={"existing_key": "preserve_me"},
        )

        result = await _le_mod.local_expert(state)

        assert result.metadata["existing_key"] == "preserve_me"
        assert result.active_specialist is None


# =============================================================================
# 7. Multi-specialist queue pop
# =============================================================================


class TestMultiSpecialistQueuePop:
    """When active_specialist is None and pending_specialists has
    ['local_expert'], the node pops it and sets active_specialist."""

    @pytest.mark.asyncio
    async def test_pops_local_expert_from_queue(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOCAL_EXPERT_USE_LLM", "false")
        _patch_common(monkeypatch)
        state = _make_state(
            destination="Rome",
            active_specialist=None,
            pending_specialists=["local_expert"],
        )

        result = await _le_mod.local_expert(state)

        # Queue should be empty after pop
        assert result.pending_specialists == []
        # active_specialist cleared after completion
        assert result.active_specialist is None
        assert result.metadata.get("last_executed_specialist") == "local_expert"

    @pytest.mark.asyncio
    async def test_pops_only_first_from_queue(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOCAL_EXPERT_USE_LLM", "false")
        _patch_common(monkeypatch)
        state = _make_state(
            destination="Amsterdam",
            active_specialist=None,
            pending_specialists=["local_expert", "diving"],
        )

        result = await _le_mod.local_expert(state)

        # Only local_expert popped; diving remains
        assert result.pending_specialists == ["diving"]
        assert result.active_specialist is None

    @pytest.mark.asyncio
    async def test_queue_pop_sets_ui_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOCAL_EXPERT_USE_LLM", "false")
        _patch_common(monkeypatch)
        state = _make_state(
            destination="Tokyo",
            active_specialist=None,
            pending_specialists=["local_expert"],
        )

        result = await _le_mod.local_expert(state)

        assert "SPECIALIST_ACTIVE" in result.ui_events

    @pytest.mark.asyncio
    async def test_no_pop_when_active_specialist_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If active_specialist is already set, do not pop from queue."""
        monkeypatch.setenv("LOCAL_EXPERT_USE_LLM", "false")
        _patch_common(monkeypatch)
        state = _make_state(
            destination="Berlin",
            active_specialist="local_expert",
            pending_specialists=["diving"],
        )

        result = await _le_mod.local_expert(state)

        # pending_specialists unchanged (no pop)
        assert result.pending_specialists == ["diving"]
