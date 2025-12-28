"""
Node Utilities Module - P2 Late Import Extraction.

This module provides simple utility functions that can be safely imported
at module level by node files without causing circular import issues.

The key insight is that these utilities either:
1. Have no dependencies on plan_graph.py internals
2. Use TYPE_CHECKING pattern for type hints without runtime imports

Functions that depend on complex plan_graph.py internals (journaling,
caching, LLM calls) remain as late imports in node functions.

Usage:
    from app.planner.node_utils import ti_short, today_iso
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Dict, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

if TYPE_CHECKING:
    from app.plan_graph import TripInputs


def ti_short(ti: "TripInputs") -> Dict[str, Any]:
    """Convert TripInputs to a compact dict excluding None values.

    This is a simple wrapper around model_dump() that's commonly used
    in node functions for logging and LLM prompt building.

    Args:
        ti: TripInputs object to convert

    Returns:
        Dict with non-None fields from TripInputs

    Example:
        >>> ti = TripInputs(destinations=["Paris"], origin="London")
        >>> ti_short(ti)
        {'destinations': ['Paris'], 'origin': 'London'}
    """
    return ti.model_dump(exclude_none=True)


def today_iso(timezone_name: Optional[str] = None) -> str:
    """Get today's date in ISO format (YYYY-MM-DD).

    Uses the provided timezone if valid, otherwise falls back to UTC.
    This is commonly used for date comparison and LLM prompts.

    Args:
        timezone_name: Optional timezone name (e.g., "America/New_York")

    Returns:
        Today's date as ISO string (YYYY-MM-DD)

    Example:
        >>> today_iso()
        '2025-01-15'
        >>> today_iso("America/New_York")
        '2025-01-14'  # If it's still yesterday in NY
    """
    tz = None
    if timezone_name:
        try:
            tz = ZoneInfo(timezone_name)
        except Exception:
            pass  # Invalid timezone, fall back to UTC

    if tz:
        return datetime.now(tz).strftime("%Y-%m-%d")
    return datetime.now(UTC).strftime("%Y-%m-%d")


__all__ = [
    "ti_short",
    "today_iso",
]
