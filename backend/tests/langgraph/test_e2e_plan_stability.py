"""Hermetic E2E tests - demo stability invariants.

These tests:
- Use FakeLLM (no network calls) via conftest.py hermetic_e2e_mode fixture
- Assert on state/metadata fields, NOT assistant_message text
- Run on every PR touching plan flow

Run with: pytest -m "e2e and not llm_smoke" -v

Key invariant: These tests NEVER make network calls.
"""

from __future__ import annotations

import pytest

from tests.langgraph.e2e_helpers import (
    dump_failure,
    get_metadata,
    get_tiles,
    run_multi_turn,
)
from tests.langgraph.fixtures import FUTURE_DATE


@pytest.mark.e2e
class TestPlanStability:
    """PR acceptance criteria - plan shell invariants.

    These tests guard against demo-critical regressions:
    - Stage never drops below 2 once plan exists
    - Adding topics preserves existing content
    - Tiles have proper attribution
    - No mode flip back to Setup
    """

    # =========================================================================
    # TEST 1: First plan reaches stage >= 2
    # =========================================================================
    @pytest.mark.asyncio
    async def test_first_plan_reaches_stage_2(self):
        """Complete trip inputs + generate → strategy_stage >= 2."""
        result, turns = await run_multi_turn(
            [
                "I want to plan a trip to Japan",
                f"From {FUTURE_DATE} for 10 days",
                "Just me, solo trip",
                "GENERATE_PLAN_NOW",  # Trigger plan generation
            ]
        )

        failures = []
        stage = turns[-1]["strategy_stage"]
        if stage is None or stage < 2:
            failures.append(f"strategy_stage={stage}, expected >= 2")

        if failures:
            path = dump_failure("test_first_plan_reaches_stage_2", turns, failures, result)
            pytest.fail(f"Invariant violated. Artifact: {path}")

    # =========================================================================
    # TEST 2: Add topic keeps stage (Dubai → diving regression guard)
    # =========================================================================
    @pytest.mark.asyncio
    async def test_add_topic_keeps_stage_and_triggers_reorchestrate(self):
        """Add topic → stage stays >= 2, reorchestrate=True, force_strategy_topics stable.

        This is the PR1 "Dubai → diving" regression guard.
        """
        result, turns = await run_multi_turn(
            [
                "Plan a beach trip to Dubai",
                f"From {FUTURE_DATE} for 2 weeks",
                "2 adults",
                "GENERATE_PLAN_NOW",  # Trigger plan generation to reach stage 2
            ]
        )

        # Verify we reached stage >= 2
        stage_before = turns[-1]["strategy_stage"]
        if stage_before is None or stage_before < 2:
            pytest.skip("Did not reach stage 2 before adding topic")

        executed_before = turns[-1]["executed_strategy_topics"] or []

        # Add diving topic (triggers reorchestration)
        from app.plan_graph import run_turn

        session_state = result.get("session_state")
        add_result = await run_turn("I also want to add diving", session_state)

        add_metadata = get_metadata(add_result)
        turn_data = {
            "user": "I also want to add diving",
            "strategy_stage": add_metadata.get("strategy_stage"),
            "reorchestrate_strategies": add_metadata.get("reorchestrate_strategies"),
            "force_strategy_topics": add_metadata.get("force_strategy_topics"),
            "executed_strategy_topics": add_metadata.get("executed_strategy_topics"),
        }
        turns.append(turn_data)

        failures = []

        # Stage must stay >= 2 (no regression to Setup)
        stage_after = turn_data["strategy_stage"]
        if stage_after is None or stage_after < 2:
            failures.append(f"Stage dropped from {stage_before} to {stage_after}")

        # Reorchestrate should be True when adding new topic
        reorch = turn_data["reorchestrate_strategies"]
        if reorch is not True:
            # Note: reorchestrate may be cleared after orchestration completes
            # So we also accept if executed_strategy_topics was updated
            executed_after = turn_data["executed_strategy_topics"] or []
            if "diving" not in executed_after:
                failures.append(
                    f"reorchestrate_strategies={reorch} and diving not in executed={executed_after}"
                )

        # force_strategy_topics should include prior + new in stable order
        force_topics = turn_data["force_strategy_topics"] or []
        if force_topics:  # Only check if set (may be cleared after orchestration)
            for prior in executed_before:
                if prior not in force_topics:
                    failures.append(f"Prior topic '{prior}' missing from force_strategy_topics")
            if "diving" not in force_topics:
                failures.append(f"'diving' not in force_strategy_topics={force_topics}")

        if failures:
            path = dump_failure("test_add_topic_keeps_stage", turns, failures, add_result)
            pytest.fail(f"Stage/reorchestrate invariant violated. Artifact: {path}")

    # =========================================================================
    # TEST 3: Executed topics contain new topic after regen
    # =========================================================================
    @pytest.mark.asyncio
    async def test_executed_topics_includes_new_after_regen(self):
        """After regen completes, executed_strategy_topics contains the new topic."""
        result, turns = await run_multi_turn(
            [
                "Plan a hiking trip to Switzerland",
                f"From {FUTURE_DATE} for 1 week",
                "Solo traveler",
                "GENERATE_PLAN_NOW",  # Trigger plan generation to reach stage 2
                "Add skiing to my trip",  # Trigger regen
            ]
        )

        failures = []
        executed = turns[-1]["executed_strategy_topics"] or []

        # Should contain skiing after regen
        if "skiing" not in executed:
            failures.append(f"'skiing' not in executed_strategy_topics={executed}")

        # Should also contain hiking (not wiped)
        if "hiking" not in executed:
            failures.append(f"'hiking' wiped from executed_strategy_topics={executed}")

        if failures:
            path = dump_failure("test_executed_topics_includes_new", turns, failures, result)
            pytest.fail(f"Executed topics invariant violated. Artifact: {path}")

    # =========================================================================
    # TEST 4: Executed topics ordering is stable (deterministic merge)
    # =========================================================================
    @pytest.mark.asyncio
    async def test_executed_topics_stable_ordering(self):
        """Repeated identical conversations → same executed_strategy_topics order."""
        inputs = [
            "I want a hiking and diving trip to Bali",
            f"From {FUTURE_DATE} for 2 weeks",
            "2 adults",
            "GENERATE_PLAN_NOW",  # Trigger plan generation
        ]

        result1, turns1 = await run_multi_turn(inputs)
        executed1 = turns1[-1]["executed_strategy_topics"] or []

        result2, turns2 = await run_multi_turn(inputs)
        executed2 = turns2[-1]["executed_strategy_topics"] or []

        failures = []
        if executed1 != executed2:
            failures.append(f"Ordering unstable: run1={executed1}, run2={executed2}")

        if failures:
            path = dump_failure(
                "test_executed_topics_stable_ordering", turns1 + turns2, failures, result2
            )
            pytest.fail(f"Ordering stability violated. Artifact: {path}")

    # =========================================================================
    # TEST 5: New tiles have source_agent (for specialist-produced tiles)
    # =========================================================================
    @pytest.mark.asyncio
    async def test_specialist_tiles_have_source_agent(self):
        """Specialist tiles (activity/stay) have source_agent attribution."""
        result, turns = await run_multi_turn(
            [
                "Plan a diving trip to the Maldives",
                f"From {FUTURE_DATE} for 1 week",
                "2 divers",
                "GENERATE_PLAN_NOW",  # Trigger plan generation
            ]
        )

        failures = []
        tiles = get_tiles(result)

        # Only enforce source_agent for specialist-produced tiles
        specialist_categories = {"activity", "stay", "experience"}
        for tile in tiles:
            category = tile.get("category", "").lower() if tile.get("category") else ""
            if category in specialist_categories:
                if not tile.get("source_agent"):
                    failures.append(f"Specialist tile missing source_agent: {tile}")

        if failures:
            path = dump_failure("test_specialist_tiles_have_source_agent", turns, failures, result)
            pytest.fail(f"Source agent missing. Artifact: {path}")

    # =========================================================================
    # TEST 6: No tile duplication after regen (by id/hash, not title)
    # =========================================================================
    @pytest.mark.asyncio
    async def test_no_tile_duplication_after_regen(self):
        """Regen doesn't duplicate tiles - unique by id or content_hash."""
        result, turns = await run_multi_turn(
            [
                "Beach vacation in Phuket",
                f"From {FUTURE_DATE} for 5 days",
                "Solo",
                "GENERATE_PLAN_NOW",  # Trigger plan generation
            ]
        )

        # Add topic to trigger regen
        from app.plan_graph import run_turn

        session_state = result.get("session_state")
        add_result = await run_turn("Add some hiking activities", session_state)

        failures = []
        tiles = get_tiles(add_result)

        # Check for duplicates by id (preferred) or content_hash
        seen_ids = set()
        seen_hashes = set()
        for tile in tiles:
            tile_id = tile.get("id")
            tile_hash = tile.get("content_hash")

            if tile_id:
                if tile_id in seen_ids:
                    failures.append(f"Duplicate tile id: {tile_id}")
                seen_ids.add(tile_id)

            if tile_hash:
                if tile_hash in seen_hashes:
                    failures.append(f"Duplicate content_hash: {tile_hash}")
                seen_hashes.add(tile_hash)

        if failures:
            path = dump_failure("test_no_tile_duplication", turns, failures, add_result)
            pytest.fail(f"Tile duplication detected. Artifact: {path}")

    # =========================================================================
    # TEST 7: Plan mode persists with missing inputs (no flip to Setup)
    # =========================================================================
    @pytest.mark.asyncio
    async def test_plan_mode_persists_with_missing_inputs(self):
        """Once in Plan (stage >= 2), destination change → stays in Plan, not Setup."""
        # First: establish a plan (reach stage >= 2)
        result, turns = await run_multi_turn(
            [
                "Plan a trip to Tokyo",
                f"From {FUTURE_DATE} for 1 week",
                "2 adults",
                "GENERATE_PLAN_NOW",  # Trigger plan generation to reach stage 2
            ]
        )

        stage = turns[-1]["strategy_stage"]
        if stage is None or stage < 2:
            pytest.skip("Did not reach stage 2")

        # Now change destination (tests that we stay in Plan mode)
        from app.plan_graph import run_turn

        session_state = result.get("session_state")
        change_result = await run_turn("Actually, change destination to Kyoto", session_state)

        failures = []
        change_metadata = get_metadata(change_result)

        # Stage should remain >= 2 (no flip to Setup/stage 0-1)
        new_stage = change_metadata.get("strategy_stage")
        if new_stage is not None and new_stage < 2:
            failures.append(f"Stage dropped to {new_stage} - flipped back to Setup?")

        if failures:
            path = dump_failure("test_plan_mode_persists", turns, failures, change_result)
            pytest.fail(f"Mode flip detected. Artifact: {path}")
