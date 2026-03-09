"""
Unified partner enrichment: Viator + GYG in parallel, best match wins.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


async def match_activity_to_best_partner(
    activity_title: str,
    destination: str,
    currency: str = "USD",
    category: str | None = None,
) -> dict | None:
    """Search Viator + GYG in parallel, return best match."""
    tasks: list[Any] = []

    if settings.viator_enabled and settings.viator_api_key:
        from app.services.viator_provider import match_activity_to_viator

        tasks.append(
            match_activity_to_viator(activity_title, destination, currency, category=category)
        )

    if settings.get_your_guide_enabled and settings.get_your_guide_api_key:
        from app.services.gyg_provider import match_activity_to_gyg

        tasks.append(
            match_activity_to_gyg(activity_title, destination, currency, category=category)
        )

    if not tasks:
        return None

    results = await asyncio.gather(*tasks, return_exceptions=True)
    matches = [r for r in results if isinstance(r, dict)]

    if not matches:
        return None

    # Higher rating wins, lower price breaks tie, Viator wins final tie
    matches.sort(
        key=lambda t: (
            -(t.get("rating") or 0),
            t.get("price_estimate") or float("inf"),
            0 if t.get("partner") == "viator" else 1,
        )
    )
    winner = matches[0]
    logger.info(
        "[PARTNER] Best match for '%s': partner=%s rating=%s price=%s",
        activity_title,
        winner.get("partner"),
        winner.get("rating"),
        winner.get("price_estimate"),
    )
    return winner


async def enrich_tiles_with_partners(
    experience_tiles: list[dict],
    destination: str,
    currency: str = "USD",
) -> None:
    """Enrich experience tiles with best partner match. Mutates in-place.

    Replaces the old _enrich_tiles_with_viator with parallel Viator+GYG search.
    """
    has_viator = settings.viator_enabled and settings.viator_api_key
    has_gyg = settings.get_your_guide_enabled and settings.get_your_guide_api_key
    if not has_viator and not has_gyg:
        return
    if not experience_tiles:
        return

    sem = asyncio.Semaphore(5)

    async def _throttled_match(title: str, category: str | None = None) -> dict | None:
        async with sem:
            return await match_activity_to_best_partner(
                title, destination, currency, category=category
            )

    filtered = [
        (i, t)
        for i, t in enumerate(experience_tiles)
        if t.get("title")
        and t.get("provider") not in ("viator", "gyg")
        and not (t.get("meta") or {}).get("viator_product_code")
        and not (t.get("meta") or {}).get("gyg_tour_id")
    ]
    tasks = [
        _throttled_match(
            t.get("title", ""),
            category=(t.get("meta") or {}).get("specialist_type")
            or (t.get("meta") or {}).get("category"),
        )
        for _, t in filtered
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    matched = 0
    for (_, tile), result in zip(filtered, results, strict=False):
        if isinstance(result, Exception) or result is None:
            continue
        matched += 1
        # Merge partner data onto existing tile
        if result.get("price_estimate") is not None:
            tile["price_estimate"] = result["price_estimate"]
            tile["live_price"] = result.get("live_price")
            tile["is_estimate_only"] = False
            tile["currency"] = result.get("currency", currency)
            tile["price_basis"] = result.get("price_basis", "per_person")
        if result.get("image_url"):
            tile["image_url"] = result["image_url"]
        if result.get("rating") is not None:
            tile["rating"] = result["rating"]
        if result.get("review_count") is not None:
            tile["review_count"] = result["review_count"]
        if result.get("deeplink") or result.get("deeplink_url"):
            dl = result.get("deeplink") or result["deeplink_url"]
            tile["deeplink"] = dl
            tile["deeplink_url"] = dl
        tile["partner"] = result.get("partner", "")
        tile["partner_product_id"] = result.get("partner_product_id", "")
        tile["provider"] = result.get("provider", "")
        if result.get("geo"):
            tile["geo"] = result["geo"]
        meta = tile.get("meta", {})
        result_meta = result.get("meta", {})
        if result_meta.get("viator_product_code"):
            meta["viator_product_code"] = result_meta["viator_product_code"]
        if result_meta.get("gyg_tour_id"):
            meta["gyg_tour_id"] = result_meta["gyg_tour_id"]
        if result_meta.get("duration_hours"):
            meta["duration_hours"] = result_meta["duration_hours"]
        tile["meta"] = meta

    if matched:
        logger.info("[PARTNER] Enriched %d/%d tiles for %s", matched, len(filtered), destination)
