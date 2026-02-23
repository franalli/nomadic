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
from unittest.mock import AsyncMock, MagicMock

import pytest

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
    - settings.local_expert_use_llm = False (no real LLM calls in unit tests)
    - _get_constraints_as_list (returns [] by default — no static constraints)
    - _get_constraint_context (returns empty string by default)
    - build_local_expert_section (returns stub section)
    - upsert_section (no-op)
    - mark_topic_executed (no-op)
    - get_destination_gallery (returns [])
    - DEMO_MANIFEST (empty dict)
    """
    mocks: Dict[str, MagicMock] = {}

    # Disable LLM for all unit tests — no real API calls
    monkeypatch.setattr(_le_mod.settings, "local_expert_use_llm", False)

    # Static constraints list (Phase A) -- default empty
    mock_constraints_list = MagicMock(return_value=[])
    monkeypatch.setattr(_le_mod, "_get_constraints_as_list", mock_constraints_list)
    mocks["constraints_list"] = mock_constraints_list

    # Constraint context (Phase B prompt injection) -- default empty
    mock_constraint_ctx = MagicMock(return_value="")
    monkeypatch.setattr(_le_mod, "_get_constraint_context", mock_constraint_ctx)
    mocks["constraint_context"] = mock_constraint_ctx

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
                        "constraints_applied": [
                            {
                                "rule": f"Constraint {i}",
                                "type": "booking_window",
                                "severity": "warning",
                            }
                            for i in range(6)
                        ],
                        "content_added": [
                            {
                                "title": f"Tip {i}",
                                "description": f"Recommendation {i}",
                                "type": "logistics",
                            }
                            for i in range(6)
                        ],
                    }
                ]
            },
        )

        result = await _le_mod.local_expert(state)

        assert result.active_specialist is None
        assert result.metadata.get("last_executed_specialist") == "local_expert"
        # Should NOT call constraint context or build
        mocks["constraint_context"].assert_not_called()
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
                        "constraints_applied": [
                            {
                                "rule": f"Constraint {i}",
                                "type": "booking_window",
                                "severity": "warning",
                            }
                            for i in range(6)
                        ],
                        "content_added": [
                            {
                                "title": f"Tip {i}",
                                "description": f"Recommendation {i}",
                                "type": "logistics",
                            }
                            for i in range(6)
                        ],
                    }
                ]
            },
        )

        await _le_mod.local_expert(state)

        mocks["constraint_context"].assert_not_called()


# =============================================================================
# 3. Cache MISS -> destination changed
# =============================================================================


class TestCacheMiss:
    """When cached section title does not contain current destination,
    the node runs the full pipeline (Phase A skeleton)."""

    @pytest.mark.asyncio
    async def test_cache_miss_runs_pipeline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cache miss triggers Phase A skeleton build.

        Phase A uses _get_constraints_as_list (not _get_constraint_context).
        _get_constraint_context is only called in Phase B (LLM disabled here).
        """
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

        # Phase A: static constraint list called with destination
        mocks["constraints_list"].assert_called_once_with("Paris")
        # Section built and upserted
        mocks["build_section"].assert_called_once()
        mocks["upsert_section"].assert_called_once()
        mocks["mark_topic"].assert_called_once()
        assert result.active_specialist is None

    @pytest.mark.asyncio
    async def test_no_cached_section_runs_pipeline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When no cached section exists at all, Phase A runs full skeleton pipeline."""
        mocks = _patch_common(monkeypatch)
        state = _make_state(
            destination="Rome",
            active_specialist="local_expert",
            metadata={},
        )

        await _le_mod.local_expert(state)

        # Phase A: static constraint list called with destination
        mocks["constraints_list"].assert_called_once_with("Rome")
        mocks["build_section"].assert_called_once()


# =============================================================================
# 3b. Destination-scoped cache reuse (L1/L2) even with sparse session section
# =============================================================================


class TestDestinationCacheReuse:
    """If session state is sparse, reuse destination-scoped L1/L2 cache before recompute."""

    @pytest.mark.asyncio
    async def test_sparse_session_uses_destination_cache(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mocks = _patch_common(monkeypatch)
        monkeypatch.setattr(_le_mod.settings, "local_expert_use_llm", True)

        state = _make_state(
            destination="Rome",
            active_specialist="local_expert",
            metadata={
                "strategy_sections": [
                    {
                        "specialist_type": "local_expert",
                        "title": "Rome Trip Overview",
                        "constraints_applied": [{"rule": "Sparse", "type": "booking_window"}],
                        "content_added": [],
                    }
                ]
            },
        )

        sentinel_response = object()
        mock_cached_output = AsyncMock(return_value=sentinel_response)
        monkeypatch.setattr(_le_mod, "_get_cached_local_expert_output", mock_cached_output)
        monkeypatch.setattr(
            _le_mod, "_enrich_legacy_lists", MagicMock(return_value=sentinel_response)
        )
        monkeypatch.setattr(_le_mod, "_has_rich_local_expert_output", MagicMock(return_value=True))
        monkeypatch.setattr(
            _le_mod,
            "_build_section_from_cached_output",
            MagicMock(
                return_value={
                    "id": "strategy_local_expert",
                    "specialist_type": "local_expert",
                    "title": "Rome Trip Overview",
                    "constraints_applied": [{"rule": "Cached", "type": "visa"}],
                    "content_added": [{"title": "Cached tip"}],
                }
            ),
        )
        mock_run = MagicMock()
        monkeypatch.setattr(_le_mod, "_run_local_expert", mock_run)

        result = await _le_mod.local_expert(state)

        assert result.active_specialist is None
        mock_cached_output.assert_called_once()
        mocks["upsert_section"].assert_called_once()
        mocks["mark_topic"].assert_called_once()
        mock_run.assert_not_called()


# =============================================================================
# 4. LLM-disabled path -> fallback generates "Explore {dest}" section
# =============================================================================


class TestLlmDisabledFallback:
    """When LLM is disabled, Phase A skeleton is built instantly from static data.

    In the skeleton-first architecture:
    - Phase A always runs (builds skeleton with static constraints, empty must_dos/content_added)
    - Phase B (LLM enrichment) is skipped when local_expert_use_llm=False
    - travel_intelligence starts as {} and is populated asynchronously by Phase B
    """

    @pytest.mark.asyncio
    async def test_fallback_section_built_with_llm_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mocks = _patch_common(monkeypatch)

        state = _make_state(destination="Bali", active_specialist="local_expert")

        result = await _le_mod.local_expert(state)

        # Phase A skeleton built
        mocks["build_section"].assert_called_once()
        call_kwargs = mocks["build_section"].call_args
        assert call_kwargs.kwargs["destination"] == "Bali"
        # Skeleton has empty must_dos and content_added (Phase B populates them)
        assert call_kwargs.kwargs["must_dos"] == []
        assert call_kwargs.kwargs["content_added"] == []
        # travel_intelligence is empty dict in skeleton
        assert call_kwargs.kwargs["travel_intelligence"] == {}
        # LLM-disabled mode should mark enrichment as terminal ready (no pending spinner)
        upserted_section = mocks["upsert_section"].call_args.args[1]
        assert upserted_section["local_expert_enrichment"]["state"] == "ready"
        assert upserted_section["local_expert_enrichment"]["error_code"] == "disabled"

        # State tracking
        assert result.metadata.get("local_expert_ran") is True
        assert result.metadata.get("last_executed_specialist") == "local_expert"
        assert result.active_specialist is None

    @pytest.mark.asyncio
    async def test_upsert_and_mark_called(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mocks = _patch_common(monkeypatch)

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
    """Phase A skeleton for destinations with no static constraint data.

    In the skeleton-first architecture, Phase A always produces an instant section
    with empty must_dos/content_added/travel_intelligence. Phase B (LLM) enriches
    asynchronously. There is no synchronous "Explore {dest}" fallback anymore.
    """

    @pytest.mark.asyncio
    async def test_fallback_recommendation_created(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Phase A builds skeleton with empty content for unknown destination.

        No static constraints → constraints_applied=[], must_dos=[], content_added=[].
        Phase B (disabled in tests) would add enriched content later.
        """
        mocks = _patch_common(monkeypatch)

        state = _make_state(destination="Timbuktu", active_specialist="local_expert")

        await _le_mod.local_expert(state)

        mocks["build_section"].assert_called_once()
        call_kwargs = mocks["build_section"].call_args

        # Skeleton: empty lists (Phase B populates async)
        assert call_kwargs.kwargs["must_dos"] == []
        assert call_kwargs.kwargs["content_added"] == []
        assert call_kwargs.kwargs["constraints_applied"] == []
        # one_liner uses destination name
        assert "Timbuktu" in call_kwargs.kwargs["one_liner"]

    @pytest.mark.asyncio
    async def test_fallback_description_includes_destination(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Phase A one_liner always includes the destination name."""
        mocks = _patch_common(monkeypatch)

        state = _make_state(destination="Reykjavik", active_specialist="local_expert")

        await _le_mod.local_expert(state)

        call_kwargs = mocks["build_section"].call_args
        # one_liner format: "Your adventure in {destination}"
        assert "Reykjavik" in call_kwargs.kwargs["one_liner"]


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
        _patch_common(monkeypatch)
        state = _make_state(
            destination="Berlin",
            active_specialist="local_expert",
            pending_specialists=["diving"],
        )

        result = await _le_mod.local_expert(state)

        # pending_specialists unchanged (no pop)
        assert result.pending_specialists == ["diving"]
