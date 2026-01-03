"""
Specialist Parallelization Utilities - Tier 9

This module provides infrastructure for running multiple specialist nodes
in parallel when they're independent (e.g., flights AND hotels).

Usage:
    from app.planner.nodes.specialist.parallel import (
        ParallelSpecialistExecutor,
        can_parallelize_specialists,
    )

    if can_parallelize_specialists(state, specialists):
        results = await ParallelSpecialistExecutor.execute(state, specialists)
        merged_state = ParallelSpecialistExecutor.merge_states(state, results)

NOTE: This feature is disabled by default (settings.specialist_parallelization_enabled).
Enable with caution after thorough testing of state merge behavior.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from app.config import settings
from app.debug_utils import _debug, _debug_error

if TYPE_CHECKING:
    from app.plan_graph import GraphState


@dataclass
class SpecialistResult:
    """Result from a parallel specialist execution."""

    specialist_name: str
    success: bool
    state_delta: Dict[str, Any]  # Changes to merge into base state
    error: Optional[str] = None
    execution_time_ms: float = 0.0


def can_parallelize_specialists(
    state: "GraphState",
    specialists: List[str],
) -> bool:
    """
    Check if the given specialists can be run in parallel.

    Parallelization is allowed when:
    1. Feature flag is enabled
    2. More than one specialist is requested
    3. Specialists are independent (don't share state mutations)
    4. State is in a safe condition for parallel execution

    Args:
        state: Current graph state
        specialists: List of specialist names to potentially parallelize

    Returns:
        True if parallelization is allowed, False otherwise
    """
    # Check feature flag
    if not getattr(settings, "specialist_parallelization_enabled", False):
        return False

    # Need at least 2 specialists to parallelize
    if len(specialists) < 2:
        return False

    # Define mutually exclusive specialists that can't run in parallel
    # These share state mutations that would conflict
    EXCLUSIVE_GROUPS = [
        {"required_fields", "correction"},  # Both mutate trip_inputs
        {"strategy", "activities"},  # Both mutate activity_settings
    ]

    specialist_set = set(specialists)
    for group in EXCLUSIVE_GROUPS:
        if len(specialist_set & group) > 1:
            _debug(
                "PARALLEL_SPECIALISTS_BLOCKED",
                specialists=specialists,
                reason=f"conflicting group: {group}",
            )
            return False

    # Check for active locks or pending operations
    if state.metadata.get("parallel_lock"):
        return False

    return True


class ParallelSpecialistExecutor:
    """
    Executor for running multiple specialists in parallel.

    Handles:
    - Concurrent execution with asyncio.gather
    - Error isolation (one failure doesn't affect others)
    - State delta collection for merging
    - Execution time tracking
    """

    @staticmethod
    async def execute(
        base_state: "GraphState",
        specialists: List[str],
        specialist_fn: Callable,
    ) -> List[SpecialistResult]:
        """
        Execute multiple specialists in parallel.

        Args:
            base_state: Base state to fork for each specialist
            specialists: List of specialist names to execute
            specialist_fn: The specialist function to call (usually _specialist)

        Returns:
            List of SpecialistResult with state deltas
        """
        import time

        # Create shallow copies of state for each specialist
        # Each specialist operates on its own copy to avoid race conditions
        forked_states = [ParallelSpecialistExecutor._fork_state(base_state) for _ in specialists]

        async def run_specialist(
            name: str,
            forked: "GraphState",
        ) -> SpecialistResult:
            """Run a single specialist and capture its state changes."""
            start = time.perf_counter()
            try:
                # Execute the specialist
                result_state = await specialist_fn(name, forked)

                # Extract state delta (changes from base state)
                delta = ParallelSpecialistExecutor._extract_delta(base_state, result_state)

                return SpecialistResult(
                    specialist_name=name,
                    success=True,
                    state_delta=delta,
                    execution_time_ms=(time.perf_counter() - start) * 1000,
                )
            except Exception as e:
                _debug_error(
                    f"PARALLEL_SPECIALIST_ERROR: {name}",
                    error=str(e),
                )
                return SpecialistResult(
                    specialist_name=name,
                    success=False,
                    state_delta={},
                    error=str(e),
                    execution_time_ms=(time.perf_counter() - start) * 1000,
                )

        # Run all specialists concurrently
        tasks = [
            run_specialist(name, forked)
            for name, forked in zip(specialists, forked_states, strict=True)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=False)

        _debug(
            "PARALLEL_SPECIALISTS_COMPLETE",
            specialists=specialists,
            success_count=sum(1 for r in results if r.success),
            total_time_ms=sum(r.execution_time_ms for r in results),
        )

        return results

    @staticmethod
    def _fork_state(state: "GraphState") -> "GraphState":
        """
        Create a shallow fork of the state for isolated execution.

        Note: This creates a new state object but shares mutable nested objects.
        For full isolation, a deep copy would be needed, but that's expensive.
        The current approach works because specialists write to different keys.
        """
        # Late import to avoid circular dependency
        from app.plan_graph import GraphState

        # Create new state with same values
        forked = GraphState(
            trip_inputs=state.trip_inputs.model_copy(deep=True),
            chat_history=list(state.chat_history),
            user_text=state.user_text,
            last_summary=state.last_summary,
            suggested_responses=list(state.suggested_responses),
            ready_to_generate=state.ready_to_generate,
            session_id=state.session_id,
            metadata=dict(state.metadata),
            flags=dict(state.flags),
        )

        return forked

    @staticmethod
    def _extract_delta(
        base: "GraphState",
        result: "GraphState",
    ) -> Dict[str, Any]:
        """
        Extract the state changes (delta) between base and result states.

        Only includes fields that changed, to support safe merging.
        """
        delta = {}

        # Check key fields for changes
        if result.last_summary != base.last_summary:
            delta["last_summary"] = result.last_summary

        if result.suggested_responses != base.suggested_responses:
            delta["suggested_responses"] = result.suggested_responses

        if result.question_target != base.question_target:
            delta["question_target"] = result.question_target

        if result.ready_to_generate != base.ready_to_generate:
            delta["ready_to_generate"] = result.ready_to_generate

        # Check trip_inputs changes
        if result.trip_inputs != base.trip_inputs:
            delta["trip_inputs"] = result.trip_inputs

        # Metadata changes (selective merge)
        metadata_delta = {}
        for key, value in result.metadata.items():
            if key not in base.metadata or base.metadata[key] != value:
                metadata_delta[key] = value
        if metadata_delta:
            delta["metadata_delta"] = metadata_delta

        return delta

    @staticmethod
    def merge_states(
        base_state: "GraphState",
        results: List[SpecialistResult],
    ) -> "GraphState":
        """
        Merge results from parallel specialists into the base state.

        Merge strategy:
        - last_summary: Concatenate with separator
        - suggested_responses: Combine unique suggestions
        - trip_inputs: Merge non-conflicting fields
        - metadata: Update with all deltas

        Args:
            base_state: Original state before parallel execution
            results: List of specialist results with state deltas

        Returns:
            Merged state incorporating all specialist outputs
        """
        # Start with base state
        merged = base_state

        summaries = []
        all_suggestions = []

        for result in results:
            if not result.success:
                continue

            delta = result.state_delta

            # Collect summaries for concatenation
            if "last_summary" in delta:
                summaries.append(delta["last_summary"])

            # Collect suggestions for deduplication
            if "suggested_responses" in delta:
                all_suggestions.extend(delta["suggested_responses"])

            # Apply metadata updates
            if "metadata_delta" in delta:
                merged.metadata.update(delta["metadata_delta"])

            # Apply trip_inputs (last specialist wins for conflicts)
            if "trip_inputs" in delta:
                merged.trip_inputs = delta["trip_inputs"]

        # Merge summaries
        if summaries:
            merged.last_summary = "\n\n---\n\n".join(summaries)

        # Merge suggestions (deduplicate, keep order)
        if all_suggestions:
            seen = set()
            unique_suggestions = []
            for s in all_suggestions:
                if s not in seen:
                    seen.add(s)
                    unique_suggestions.append(s)
            merged.suggested_responses = unique_suggestions[:5]  # Limit to 5

        return merged
