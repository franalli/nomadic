"""
Shared JSON parsing helpers for planner tools.

Extracted from validate_plan.py and build_itinerary.py to avoid duplication.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def parse_tiles_json(tiles_json: str) -> Dict[str, List[Dict[str, Any]]]:
    """Parse tiles JSON string into category-grouped dict.

    Expected format: {"flights": [...], "hotels": [...], "activities": [...]}
    Falls back to empty dict on parse error.
    """
    if not tiles_json or tiles_json == "{}":
        return {}
    try:
        parsed = json.loads(tiles_json)
        if isinstance(parsed, dict):
            return parsed
        return {}
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse tiles_json")
        return {}


def parse_constraints_json(constraints_json: str) -> List[Dict[str, Any]]:
    """Parse constraints JSON string into list of constraint dicts.

    Falls back to empty list on parse error.
    """
    if not constraints_json or constraints_json == "[]":
        return []
    try:
        parsed = json.loads(constraints_json)
        if isinstance(parsed, list):
            return parsed
        return []
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse constraints_json")
        return []
