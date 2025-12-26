"""
Tests for debug/admin endpoints (PR-A: Debug/Config Snapshot).

These tests verify:
1. /v1/admin/planner returns stable schema with required keys
2. planner_snapshot values match actual constants
3. planner_snapshot is emitted per turn in run_turn()
"""

import pytest
from fastapi.testclient import TestClient

# =============================================================================
# /v1/admin/planner Endpoint Tests
# =============================================================================


class TestAdminPlannerEndpoint:
    """Tests for /v1/admin/planner endpoint."""

    @pytest.fixture
    def client(self):
        """Create a FastAPI test client."""
        from app.main import app

        with TestClient(app) as c:
            yield c

    def test_debug_planner_endpoint_schema(self, client):
        """Endpoint returns 200 with required keys."""
        response = client.get("/v1/admin/planner")

        assert response.status_code == 200
        data = response.json()

        # Required top-level keys (stable schema)
        required_keys = {
            "admin_endpoint_version",
            "prompt_bundle_hash",
            "planner_build_id",
            "cache_schema_version",
            "enabled_strategy_topics",
            "enabled_strategy_topics_source",
            "enable_all_strategy_topics",
            "llm_budget_max_calls_non_ready",
            "cache_ttl_map_seconds",
            "cache_ttl_map_source",
            "gate_precedence_version",
            "node_logic_version",
            "strategy_output_caps",
        }
        assert required_keys.issubset(data.keys()), f"Missing keys: {required_keys - data.keys()}"

    def test_debug_planner_values_match_constants(self, client):
        """Values match expected constants and config."""
        from app.config import settings
        from app.plan_graph import (
            CACHE_SCHEMA_VERSION,
            GATE_PRECEDENCE_VERSION,
            NODE_LOGIC_VERSION,
            PLANNER_BUILD_ID,
            PROMPT_BUNDLE_HASH,
        )

        response = client.get("/v1/admin/planner")
        data = response.json()

        # Verify constants match
        assert data["prompt_bundle_hash"] == PROMPT_BUNDLE_HASH
        assert data["planner_build_id"] == PLANNER_BUILD_ID
        assert data["cache_schema_version"] == CACHE_SCHEMA_VERSION
        assert data["gate_precedence_version"] == GATE_PRECEDENCE_VERSION
        assert data["node_logic_version"] == NODE_LOGIC_VERSION

        # Verify schema evolution marker
        assert data["admin_endpoint_version"] == "planner_v1"

        # Verify LLM budget invariant
        assert data["llm_budget_max_calls_non_ready"] == 1

        # Verify enabled_strategy_topics reflects defaults
        assert data["enabled_strategy_topics_source"] in ("defaults", "env_override")
        assert isinstance(data["enabled_strategy_topics"], list)

        # Verify cache TTL map
        assert "response" in data["cache_ttl_map_seconds"]
        assert "extractor" in data["cache_ttl_map_seconds"]
        assert "strategy" in data["cache_ttl_map_seconds"]
        assert data["cache_ttl_map_seconds"]["response"] == settings.response_cache_ttl_seconds

        # Verify strategy output caps
        assert "max_chars" in data["strategy_output_caps"]
        assert "expansion_max_chars" in data["strategy_output_caps"]
        assert data["strategy_output_caps"]["max_chars"] == settings.strategy_max_output_chars

    def test_debug_planner_enabled_topics_default(self, client):
        """Default enabled topics match feature flags."""
        from app.config import settings

        response = client.get("/v1/admin/planner")
        data = response.json()

        expected_topics = []
        if settings.enable_strategy_boating:
            expected_topics.append("boating")
        if settings.enable_strategy_cycling:
            expected_topics.append("cycling")
        if settings.enable_strategy_diving:
            expected_topics.append("diving")
        if settings.enable_strategy_hiking:
            expected_topics.append("hiking")
        if settings.enable_strategy_skiing:
            expected_topics.append("skiing")

        # Should be sorted alphabetically
        assert data["enabled_strategy_topics"] == sorted(expected_topics)


# =============================================================================
# planner_snapshot in run_turn() Tests
# =============================================================================


class TestPlannerSnapshot:
    """Tests for planner_snapshot in per-turn metadata."""

    @pytest.fixture
    def state_after_turn(self):
        """Run a simple turn and return the result."""
        import asyncio

        from app.plan_graph import run_turn

        # Simple greeting turn
        result = asyncio.run(run_turn("Hello", session_state=None))
        return result

    def test_planner_snapshot_exists_in_metadata(self, state_after_turn):
        """planner_snapshot should exist in session_state.metadata."""
        session_state = state_after_turn.get("session_state", {})
        metadata = session_state.get("metadata", {})

        assert "planner_snapshot" in metadata, "planner_snapshot missing from metadata"

    def test_planner_snapshot_has_required_keys(self, state_after_turn):
        """planner_snapshot should have all required keys."""
        session_state = state_after_turn.get("session_state", {})
        metadata = session_state.get("metadata", {})
        snapshot = metadata.get("planner_snapshot", {})

        required_keys = {
            "prompt_bundle_hash",
            "planner_build_id",
            "cache_schema_version",
            "enabled_strategy_topics",
            "llm_budget_max_calls_non_ready",
            "gate_precedence_version",
        }
        assert required_keys.issubset(
            snapshot.keys()
        ), f"Missing keys: {required_keys - snapshot.keys()}"

    def test_planner_snapshot_values_match_constants(self, state_after_turn):
        """Snapshot values should match actual constants."""
        from app.plan_graph import (
            CACHE_SCHEMA_VERSION,
            GATE_PRECEDENCE_VERSION,
            PLANNER_BUILD_ID,
            PROMPT_BUNDLE_HASH,
        )

        session_state = state_after_turn.get("session_state", {})
        metadata = session_state.get("metadata", {})
        snapshot = metadata.get("planner_snapshot", {})

        assert snapshot["prompt_bundle_hash"] == PROMPT_BUNDLE_HASH
        assert snapshot["planner_build_id"] == PLANNER_BUILD_ID
        assert snapshot["cache_schema_version"] == CACHE_SCHEMA_VERSION
        assert snapshot["gate_precedence_version"] == GATE_PRECEDENCE_VERSION
        assert snapshot["llm_budget_max_calls_non_ready"] == 1


class TestPlannerSnapshotTierA:
    """Tier A integration tests for planner_snapshot consistency."""

    @pytest.fixture
    def multi_turn_session(self):
        """Run multiple turns and return all results."""
        import asyncio

        from app.plan_graph import run_turn

        async def run_turns():
            results = []
            session_state = None

            messages = [
                "I want to go to Paris",
                "from New York",
                "next month for a week",
            ]

            for msg in messages:
                result = await run_turn(msg, session_state=session_state)
                results.append(result)
                session_state = result.get("session_state")

            return results

        return asyncio.run(run_turns())

    def test_planner_snapshot_consistent_across_turns(self, multi_turn_session):
        """planner_snapshot should be consistent across all turns in a session."""
        snapshots = []
        for result in multi_turn_session:
            session_state = result.get("session_state", {})
            metadata = session_state.get("metadata", {})
            snapshot = metadata.get("planner_snapshot")
            assert snapshot is not None, "planner_snapshot missing from turn"
            snapshots.append(snapshot)

        # All snapshots should have the same values (no mutation during session)
        first_snapshot = snapshots[0]
        for i, snapshot in enumerate(snapshots[1:], start=2):
            assert (
                snapshot["prompt_bundle_hash"] == first_snapshot["prompt_bundle_hash"]
            ), f"prompt_bundle_hash changed in turn {i}"
            assert (
                snapshot["planner_build_id"] == first_snapshot["planner_build_id"]
            ), f"planner_build_id changed in turn {i}"
            assert (
                snapshot["cache_schema_version"] == first_snapshot["cache_schema_version"]
            ), f"cache_schema_version changed in turn {i}"
