"""
Shared tile-flattening utilities.

Centralises the category-grouped-tiles -> ID-based-map conversion that is
needed by both the response envelope (for frontend) and the itinerary
adapter (for the builder).

Extracted to avoid circular imports between plan_graph and services.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def flatten_tiles_to_id_map(
    tiles_by_category: Optional[Dict[str, List]] = None,
) -> Dict[str, Any]:
    """Flatten category-grouped tiles to an ID-keyed dict.

    Args:
        tiles_by_category: ``{"flights": [tile, ...], "hotels": [...]}``

    Returns:
        ``{"tile_id_1": tile_dict, ...}``
    """
    if not tiles_by_category:
        return {}

    flat: Dict[str, Any] = {}
    for category, tile_list in tiles_by_category.items():
        if not isinstance(tile_list, list):
            logger.warning(
                "flatten_tiles_to_id_map: %s is not a list: %s", category, type(tile_list)
            )
            continue
        for tile in tile_list:
            if isinstance(tile, dict):
                tile_id = tile.get("id")
                if tile_id:
                    flat[tile_id] = tile
                else:
                    logger.debug(
                        "flatten_tiles_to_id_map: Tile without ID in %s: keys=%s",
                        category,
                        list(tile.keys())[:5],
                    )
    return flat
