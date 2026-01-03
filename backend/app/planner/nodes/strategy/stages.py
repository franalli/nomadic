"""
Strategy Stage 1/2 Coordinators - Token-optimized strategy responses.

Stage 1: Initial strategy response (shortlist + skeleton, max 512 tokens)
Stage 2: Section expansion (detailed content, 600-1536 tokens based on tier)

This module provides coordinator classes that encapsulate the LLM call patterns
for strategy stages, similar to Stage0Coordinator in stage0.py.

Tier 9: Extracted from strategy_main.py for improved modularity.
Pattern established; full extraction of guards deferred for future iteration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional

from app.planner.gates.checks import (
    STRATEGY_TIER_MAX_TOKENS,
    StrategyExpansionTarget,
    StrategyTier,
)
from app.planner.metadata_mutator import get_mutator

if TYPE_CHECKING:
    from app.plan_graph import GraphState


@dataclass
class StageConfig:
    """Configuration for a strategy stage LLM call."""

    stage_name: str
    tier: StrategyTier
    target: Optional[StrategyExpansionTarget]
    max_tokens: int
    is_expansion: bool


class StageConfigBuilder:
    """
    Builder for strategy stage configurations.

    Encapsulates the logic for determining which stage config to use
    based on expansion state and user request.
    """

    @staticmethod
    def for_stage1() -> StageConfig:
        """Build config for Stage 1 (outline tier)."""
        return StageConfig(
            stage_name="stage1",
            tier=StrategyTier.OUTLINE,
            target=None,
            max_tokens=STRATEGY_TIER_MAX_TOKENS.get(StrategyTier.OUTLINE, 512),
            is_expansion=False,
        )

    @staticmethod
    def for_stage2(
        tier: StrategyTier,
        target: Optional[StrategyExpansionTarget],
    ) -> StageConfig:
        """Build config for Stage 2 (section or full tier)."""
        max_tokens = STRATEGY_TIER_MAX_TOKENS.get(tier, 768)
        return StageConfig(
            stage_name="stage2",
            tier=tier,
            target=target,
            max_tokens=max_tokens,
            is_expansion=True,
        )


class StrategyStageTracker:
    """
    Tracks strategy stage progression and lifecycle state.

    Manages:
    - Stage 1 -> Stage 2 transitions
    - Expansion state (pending_strategy_expansion flag)
    - Skeleton caching for Stage 2 context reuse
    - Stage completion signatures for lifecycle suppression
    """

    @staticmethod
    def mark_stage1_complete(
        state: "GraphState",
        topic: str,
        response: str,
    ) -> None:
        """
        Mark Stage 1 as complete and set up for potential Stage 2.

        - Sets pending_strategy_expansion = True
        - Caches the skeleton for Stage 2 context reuse
        - Computes lifecycle signature to prevent re-firing
        """
        from app.planner.gates.suppression import SuppressionPredicates

        state.pending_strategy_expansion = True

        # Compute and store lifecycle signature
        stage1_sig = SuppressionPredicates.compute_stage1_signature(
            topic,
            state.trip_inputs.destinations or [],
            state.trip_inputs.origin,
        )
        # Cache skeleton for Stage 2 context reuse (saves ~1000-1500 tokens)
        get_mutator(state).set_stage1_skeleton(response, topic, stage1_sig)

    @staticmethod
    def mark_stage2_complete(state: "GraphState") -> None:
        """Mark Stage 2 as complete and clear expansion state."""
        state.pending_strategy_expansion = False

    @staticmethod
    def get_cached_skeleton(state: "GraphState") -> Optional[str]:
        """Get cached Stage 1 skeleton for Stage 2 context, if available."""
        return state.metadata.get("stage1_skeleton")

    @staticmethod
    def get_skeleton_topic(state: "GraphState") -> Optional[str]:
        """Get the topic associated with the cached skeleton."""
        return state.metadata.get("stage1_skeleton_topic")

    @staticmethod
    def build_stage2_context(
        state: "GraphState",
        topic: str,
        target: Optional[StrategyExpansionTarget],
    ) -> Optional[str]:
        """
        Build condensed context for Stage 2 using cached Stage 1 skeleton.

        Returns None if no skeleton is cached, indicating fallback to
        full conversation_summary should be used.
        """
        cached_skeleton = StrategyStageTracker.get_cached_skeleton(state)
        if not cached_skeleton:
            return None

        skeleton_topic = StrategyStageTracker.get_skeleton_topic(state) or topic
        expansion_desc = target.value.replace("_", " ") if target else "full itinerary"

        # Truncate skeleton to prevent excessive context
        truncated_skeleton = cached_skeleton[:1500]
        if len(cached_skeleton) > 1500:
            truncated_skeleton += "..."

        return (
            f"Previous {skeleton_topic} skeleton:\n"
            f"---\n{truncated_skeleton}\n---\n"
            f"User requested expansion of: {expansion_desc}"
        )


class StrategyStatsTracker:
    """
    Tracks strategy stage statistics for monitoring.

    Wraps the _strategy_stats dict from plan_graph.py for type safety.
    """

    @staticmethod
    def record_stage1_call(stats: Dict[str, int]) -> None:
        """Record a Stage 1 LLM call."""
        stats["stage1_calls"] = stats.get("stage1_calls", 0) + 1
        stats["tier_outline"] = stats.get("tier_outline", 0) + 1

    @staticmethod
    def record_stage2_call(
        stats: Dict[str, int],
        tier: StrategyTier,
        target: Optional[StrategyExpansionTarget],
    ) -> None:
        """Record a Stage 2 LLM call with tier and target tracking."""
        stats["stage2_calls"] = stats.get("stage2_calls", 0) + 1

        if tier == StrategyTier.FULL:
            stats["tier_full"] = stats.get("tier_full", 0) + 1
        else:
            stats["tier_section"] = stats.get("tier_section", 0) + 1

        # Track section-specific stats
        section_stat_map = {
            StrategyExpansionTarget.DAY_DETAILS: "section_day_details",
            StrategyExpansionTarget.ROUTES_TRAILS: "section_routes",
            StrategyExpansionTarget.LOGISTICS: "section_logistics",
            StrategyExpansionTarget.BUDGET: "section_budget",
            StrategyExpansionTarget.GEAR_PACKING: "section_gear",
            StrategyExpansionTarget.CONTINGENCIES: "section_contingencies",
        }
        if target and target in section_stat_map:
            stat_key = section_stat_map[target]
            stats[stat_key] = stats.get(stat_key, 0) + 1


# =============================================================================
# PROMPT BUILDERS
# =============================================================================


def build_destination_context(
    topic: str,
    destinations: List[str],
) -> str:
    """
    Build destination-specific context for Stage 1 when destinations are known.

    When strategy_dest_known is True, the LLM should provide destination-specific
    advice, NOT a shortlist of destinations.
    """
    if not destinations:
        return ""

    dest_list = ", ".join(destinations)
    return (
        f"\n\n==============================\n"
        f"DESTINATION ALREADY CHOSEN: {dest_list}\n"
        f"==============================\n"
        f"The user has ALREADY selected {dest_list} as their destination.\n"
        f"DO NOT ask which destination they prefer or suggest alternative destinations.\n"
        f"Instead, provide:\n"
        f"1. Specific {topic} recommendations for {dest_list}\n"
        f"2. Best trails/routes/spots in this region\n"
        f"3. Seasonal considerations for their travel dates\n"
        f"4. Practical tips specific to {dest_list}\n"
        f"5. Ask about preferences (difficulty, duration, etc.) if needed\n\n"
    )


def build_section_focus(target: StrategyExpansionTarget) -> str:
    """
    Build section focus instruction for Stage 2 section expansions.
    """
    if target == StrategyExpansionTarget.FULL_EXPANSION:
        return ""

    section_name = target.value.replace("_", " ")
    return (
        f"\n\nFOCUS: User requested expansion of **{section_name}** section only. "
        "Provide detailed content for this section. Do not repeat the full itinerary.\n"
    )
