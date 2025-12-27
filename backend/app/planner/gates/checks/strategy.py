"""
Strategy Gate Checks - P4 Module Extraction.

Contains strategy expansion detection logic and related types.
Used by GateEvaluator to detect when users request strategy expansion.

Usage:
    from app.planner.gates.checks.strategy import (
        is_strategy_expansion_request,
        StrategyExpansionResult,
        StrategyExpansionTarget,
        StrategyTier,
    )

    result = is_strategy_expansion_request("tell me more about day 1")
    if result.is_expansion:
        # Route to strategy expansion
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple


class StrategyExpansionTarget(str, Enum):
    """Expansion targets for strategy Stage 2 section-based expansion."""

    ITINERARY_OUTLINE = "itinerary_outline"  # High-level day-by-day skeleton
    DAY_DETAILS = "day_details"  # Detailed breakdown for specific day(s)
    ROUTES_TRAILS = "routes_trails"  # Specific routes, trails, or paths
    LOGISTICS = "logistics"  # Transport, transfers, timing
    BUDGET = "budget"  # Cost breakdown, money-saving tips
    GEAR_PACKING = "gear_packing"  # Equipment, packing list
    CONTINGENCIES = "contingencies"  # Weather backup, rest days, alternatives
    FULL_EXPANSION = "full_expansion"  # Complete detailed itinerary (legacy Stage 2)


class StrategyTier(str, Enum):
    """Output tier for strategy responses, controlling max_tokens."""

    OUTLINE = "outline"  # 512 tokens - Stage 1 shortlist + skeleton
    SECTION = "section"  # 768 tokens - Single section expansion
    FULL = "full"  # 2048 tokens - Complete expansion (user must explicitly request)


# Map tiers to max_tokens
STRATEGY_TIER_MAX_TOKENS: Dict[StrategyTier, int] = {
    StrategyTier.OUTLINE: 512,
    StrategyTier.SECTION: 768,
    StrategyTier.FULL: 2048,
}


# Patterns that trigger FULL tier (user explicitly wants everything)
FULL_EXPANSION_TRIGGERS = frozenset(
    {
        "full itinerary",
        "full plan",
        "complete itinerary",
        "complete plan",
        "everything",
        "all the details",
        "the whole thing",
        "entire itinerary",
        "detailed plan",  # "detailed" implies comprehensive
    }
)


# Section-specific patterns -> (StrategyExpansionTarget, StrategyTier)
SECTION_EXPANSION_PATTERNS: Dict[str, Tuple[StrategyExpansionTarget, StrategyTier]] = {
    # Day details
    "day 1": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    "day 2": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    "day 3": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    "day 4": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    "day 5": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    "first day": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    "second day": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    "third day": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    "expand day": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    "day-by-day": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    "daily breakdown": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    "daily schedule": (StrategyExpansionTarget.DAY_DETAILS, StrategyTier.SECTION),
    # Routes and trails
    "routes": (StrategyExpansionTarget.ROUTES_TRAILS, StrategyTier.SECTION),
    "trails": (StrategyExpansionTarget.ROUTES_TRAILS, StrategyTier.SECTION),
    "trail": (StrategyExpansionTarget.ROUTES_TRAILS, StrategyTier.SECTION),
    "hikes": (StrategyExpansionTarget.ROUTES_TRAILS, StrategyTier.SECTION),
    "paths": (StrategyExpansionTarget.ROUTES_TRAILS, StrategyTier.SECTION),
    "route options": (StrategyExpansionTarget.ROUTES_TRAILS, StrategyTier.SECTION),
    "alternative routes": (StrategyExpansionTarget.ROUTES_TRAILS, StrategyTier.SECTION),
    # Logistics
    "logistics": (StrategyExpansionTarget.LOGISTICS, StrategyTier.SECTION),
    "transport": (StrategyExpansionTarget.LOGISTICS, StrategyTier.SECTION),
    "transfers": (StrategyExpansionTarget.LOGISTICS, StrategyTier.SECTION),
    "getting there": (StrategyExpansionTarget.LOGISTICS, StrategyTier.SECTION),
    "how to get": (StrategyExpansionTarget.LOGISTICS, StrategyTier.SECTION),
    "timing": (StrategyExpansionTarget.LOGISTICS, StrategyTier.SECTION),
    # Budget
    "budget": (StrategyExpansionTarget.BUDGET, StrategyTier.SECTION),
    "cost": (StrategyExpansionTarget.BUDGET, StrategyTier.SECTION),
    "costs": (StrategyExpansionTarget.BUDGET, StrategyTier.SECTION),
    "price": (StrategyExpansionTarget.BUDGET, StrategyTier.SECTION),
    "pricing": (StrategyExpansionTarget.BUDGET, StrategyTier.SECTION),
    "money": (StrategyExpansionTarget.BUDGET, StrategyTier.SECTION),
    "expenses": (StrategyExpansionTarget.BUDGET, StrategyTier.SECTION),
    "cost breakdown": (StrategyExpansionTarget.BUDGET, StrategyTier.SECTION),
    # Gear and packing
    "gear": (StrategyExpansionTarget.GEAR_PACKING, StrategyTier.SECTION),
    "equipment": (StrategyExpansionTarget.GEAR_PACKING, StrategyTier.SECTION),
    "packing": (StrategyExpansionTarget.GEAR_PACKING, StrategyTier.SECTION),
    "pack list": (StrategyExpansionTarget.GEAR_PACKING, StrategyTier.SECTION),
    "packing list": (StrategyExpansionTarget.GEAR_PACKING, StrategyTier.SECTION),
    "what to bring": (StrategyExpansionTarget.GEAR_PACKING, StrategyTier.SECTION),
    "what to pack": (StrategyExpansionTarget.GEAR_PACKING, StrategyTier.SECTION),
    "rental gear": (StrategyExpansionTarget.GEAR_PACKING, StrategyTier.SECTION),
    # Contingencies
    "contingencies": (StrategyExpansionTarget.CONTINGENCIES, StrategyTier.SECTION),
    "backup": (StrategyExpansionTarget.CONTINGENCIES, StrategyTier.SECTION),
    "backup plan": (StrategyExpansionTarget.CONTINGENCIES, StrategyTier.SECTION),
    "weather": (StrategyExpansionTarget.CONTINGENCIES, StrategyTier.SECTION),
    "rain plan": (StrategyExpansionTarget.CONTINGENCIES, StrategyTier.SECTION),
    "rest days": (StrategyExpansionTarget.CONTINGENCIES, StrategyTier.SECTION),
    "alternatives": (StrategyExpansionTarget.CONTINGENCIES, StrategyTier.SECTION),
    "if it rains": (StrategyExpansionTarget.CONTINGENCIES, StrategyTier.SECTION),
}


# Generic expansion phrases (default to ITINERARY_OUTLINE at SECTION tier)
GENERIC_EXPANSION_TRIGGERS = frozenset(
    {
        "expand",
        "show details",
        "show more details",
        "tell me more",
        "more details",
        "elaborate",
        "go deeper",
        "give me more",
    }
)


@dataclass
class StrategyExpansionResult:
    """Result of parsing user text for strategy expansion intent."""

    is_expansion: bool
    target: Optional[StrategyExpansionTarget] = None
    tier: Optional[StrategyTier] = None
    matched_phrase: Optional[str] = None


def is_strategy_expansion_request(text: str) -> StrategyExpansionResult:
    """
    Parse user text for strategy expansion intent.

    Returns structured result with:
    - is_expansion: Whether user is requesting expansion
    - target: Which section to expand (DAY_DETAILS, ROUTES, BUDGET, etc.)
    - tier: Output tier (SECTION=768 tokens, FULL=2048 tokens)

    Only triggers on explicit phrases to avoid false positives.
    Implicit confirmations like "yes" or "let's do it" do NOT trigger expansion.

    Args:
        text: User text (will be lowercased)

    Returns:
        StrategyExpansionResult with expansion details
    """
    text_lower = text.lower().strip()

    # Check for FULL tier triggers first (user wants everything)
    for trigger in FULL_EXPANSION_TRIGGERS:
        if trigger in text_lower:
            return StrategyExpansionResult(
                is_expansion=True,
                target=StrategyExpansionTarget.FULL_EXPANSION,
                tier=StrategyTier.FULL,
                matched_phrase=trigger,
            )

    # Check for section-specific patterns
    for pattern, (target, tier) in SECTION_EXPANSION_PATTERNS.items():
        if pattern in text_lower:
            return StrategyExpansionResult(
                is_expansion=True,
                target=target,
                tier=tier,
                matched_phrase=pattern,
            )

    # Check for generic expansion triggers (default to ITINERARY_OUTLINE)
    for trigger in GENERIC_EXPANSION_TRIGGERS:
        if trigger in text_lower:
            return StrategyExpansionResult(
                is_expansion=True,
                target=StrategyExpansionTarget.ITINERARY_OUTLINE,
                tier=StrategyTier.SECTION,
                matched_phrase=trigger,
            )

    # No expansion detected
    return StrategyExpansionResult(is_expansion=False)


__all__ = [
    "StrategyExpansionTarget",
    "StrategyTier",
    "STRATEGY_TIER_MAX_TOKENS",
    "StrategyExpansionResult",
    "is_strategy_expansion_request",
    # Pattern constants (for testing/debugging)
    "FULL_EXPANSION_TRIGGERS",
    "SECTION_EXPANSION_PATTERNS",
    "GENERIC_EXPANSION_TRIGGERS",
]
