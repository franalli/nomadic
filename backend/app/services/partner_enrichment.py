"""
Unified partner enrichment: Viator + GYG in parallel, best match wins.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import settings
from app.utils.geo import haversine_km as _haversine_km

logger = logging.getLogger(__name__)
_PARTNER_GEO_MAX_DISTANCE_KM = 120.0
# Looser bound used when the source tile has no coords and we fall back to the
# destination centroid. The centroid is the city/region center while real
# activities radiate out (e.g. Bali day-trips to Nusa Penida / Menjangan ~100km),
# so a generous margin avoids false rejects while still decisively catching
# wrong-country/continent matches (Bali -> Cancun ~15000km).
_PARTNER_GEO_CENTROID_MAX_DISTANCE_KM = 400.0
_AFFILIATE_PARTNERS = {"viator", "gyg", "getyourguide", "get_your_guide"}


def _coords_from_tile(tile: dict[str, Any]) -> tuple[float, float] | None:
    """Extract (lat, lng) coordinates from a tile-like dict."""
    geo = tile.get("geo")
    if isinstance(geo, dict):
        lat = geo.get("lat")
        lng = geo.get("lng")
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            return float(lat), float(lng)

    coords = tile.get("coordinates")
    if isinstance(coords, dict):
        lat = coords.get("lat")
        lng = coords.get("lng")
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            return float(lat), float(lng)
    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
        lng, lat = coords[0], coords[1]
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            return float(lat), float(lng)

    return None


def _partner_match_is_geo_compatible(
    source_tile: dict[str, Any],
    partner_tile: dict[str, Any],
    centroid: tuple[float, float] | None = None,
) -> bool:
    """Reject partner matches that land implausibly far from the source tile.

    When the source tile has no coords -- LLM-generated specialist tiles never do
    -- fall back to the destination ``centroid`` so a partner product in the wrong
    country (e.g. a Bali dive matched to a Cancun/Antalya product) is still
    rejected instead of silently accepted.
    """
    source_coords = _coords_from_tile(source_tile)
    partner_coords = _coords_from_tile(partner_tile)

    reference = source_coords or centroid
    if not reference or not partner_coords:
        return True

    max_km = (
        _PARTNER_GEO_MAX_DISTANCE_KM if source_coords else _PARTNER_GEO_CENTROID_MAX_DISTANCE_KM
    )
    distance_km = _haversine_km(reference, partner_coords)
    if distance_km <= max_km:
        return True

    logger.info(
        "[PARTNER] Rejecting geo-mismatched match for '%s': ref=%s (%s) partner=%s "
        "distance=%.1fkm > %.0fkm",
        source_tile.get("title", ""),
        reference,
        "source" if source_coords else "centroid",
        partner_coords,
        distance_km,
        max_km,
    )
    return False


def _has_persisted_partner_match(tile: dict[str, Any]) -> bool:
    """Return True when a tile already carries persisted affiliate enrichment."""
    provider = str(tile.get("provider") or "").strip().lower()
    partner = str(tile.get("partner") or "").strip().lower()
    if provider in {"viator", "gyg"} or partner in _AFFILIATE_PARTNERS:
        return True

    meta = tile.get("meta")
    if isinstance(meta, dict) and (meta.get("viator_product_code") or meta.get("gyg_tour_id")):
        return True

    partner_product_id = str(tile.get("partner_product_id") or "").strip()
    if not partner_product_id:
        return False

    if tile.get("live_price") is not None or tile.get("is_estimate_only") is False:
        return True

    deeplink = str(tile.get("deeplink") or tile.get("deeplink_url") or "").lower()
    return _deeplink_is_affiliate(deeplink)


# Tier-1 specialist markers used to identify AI-suggested specialist activity blocks.
_TIER1_SPECIALIST_SOURCE_AGENTS = {"vertical_specialist"}


def _deeplink_is_affiliate(deeplink: str | None) -> bool:
    """Return True for a real affiliate booking deeplink.

    A bare Google-Maps ``maps/search``/``maps/place`` link is NOT a booking — it
    is the placeholder/display-floor fallback — so it must not count as affiliate.
    """
    dl = (deeplink or "").lower()
    if not dl:
        return False
    if "google.com/maps" in dl or "/maps/search" in dl or "/maps/place" in dl:
        return False
    return any(marker in dl for marker in ("viator", "getyourguide", "gyg"))


def has_affiliate_booking(
    tile: dict[str, Any] | None,
    extra_deeplink: str | None = None,
) -> bool:
    """Return True when a tile (and/or an extra block-level deeplink) is bookable.

    Bookable means a real Viator/GetYourGuide affiliate product — provider/partner
    fields, a persisted product code, or an affiliate deeplink. A bare Google-Maps
    ``maps/search`` link is NOT an affiliate booking.
    """
    if isinstance(tile, dict) and _has_persisted_partner_match(tile):
        return True
    if isinstance(tile, dict) and _deeplink_is_affiliate(
        str(tile.get("deeplink") or tile.get("deeplink_url") or "")
    ):
        return True
    return _deeplink_is_affiliate(extra_deeplink)


def is_tier1_specialist_activity(
    *,
    specialist_type: str | None,
    activity_domain: str | None,
    source_agent: str | None,
    provenance: str | None,
) -> bool:
    """Return True for AI-suggested Tier-1 specialist activity content.

    Scope (per product policy): only AI-suggested specialist activities qualify —
    a user-browse-added activity (even a specialist one) never does.
    """
    if provenance is not None and provenance != "ai_suggested":
        return False
    from app.planner.specialist_registry import TIER1_SPECIALIST_NAMES

    spec = (specialist_type or "").strip().lower()
    if spec and spec in {s.lower() for s in TIER1_SPECIALIST_NAMES}:
        return True
    if (activity_domain or "").strip().lower() == "tier1":
        return True
    if (source_agent or "").strip().lower() in _TIER1_SPECIALIST_SOURCE_AGENTS:
        return True
    return False


def is_unbookable_specialist_activity(
    *,
    specialist_type: str | None,
    activity_domain: str | None = None,
    source_agent: str | None = None,
    provenance: str | None = None,
    matched_tile: dict[str, Any] | None = None,
    deeplink: str | None = None,
) -> bool:
    """Shared drop predicate for the no-bookable-specialist policy.

    Returns True only when an activity is BOTH (a) AI-suggested Tier-1 specialist
    content AND (b) has no affiliate booking after enrichment. Callers must apply
    the conservative enrichment-evidence gate themselves — this predicate assumes
    affiliate status is already known for ``matched_tile``/``deeplink``.
    """
    if not is_tier1_specialist_activity(
        specialist_type=specialist_type,
        activity_domain=activity_domain,
        source_agent=source_agent,
        provenance=provenance,
    ):
        return False
    return not has_affiliate_booking(matched_tile, deeplink)


# Tile-level provenance/source markers that mean a user added the tile via Browse.
# A user-browse-added tile (even a specialist one) is OUT of the drop policy scope.
_BROWSE_ADDED_SOURCES = {"browse_add", "user_browse_added"}


def _tile_provenance(tile: dict[str, Any]) -> str:
    """Resolve an activity tile's provenance for the drop predicate.

    Mirrors ``ItineraryBuilder._is_user_browse_block`` at the TILE level: a tile
    whose ``meta.source``/``source`` marks it as user-browse-added is reported as
    ``"user_browse_added"`` (which the predicate excludes), otherwise
    ``"ai_suggested"``. This keeps user-pinned specialist tiles safe from the
    no-bookable-specialist prune.
    """
    meta = tile.get("meta") if isinstance(tile.get("meta"), dict) else {}
    for raw_source in (meta.get("source"), tile.get("source")):
        if isinstance(raw_source, str) and raw_source.strip().lower() in _BROWSE_ADDED_SOURCES:
            return "user_browse_added"
    return "ai_suggested"


def _tile_specialist_topic(tile: dict[str, Any]) -> str:
    """Topic stamp for an activity tile (``meta.specialist_type`` -> ``meta.category``).

    Mirrors ``middleware._tile_specialist_topic`` so a section's
    ``specialist_type`` and a tile's topic line up when deciding whether a
    specialist is fully unbookable.
    """
    meta = tile.get("meta") if isinstance(tile.get("meta"), dict) else {}
    topic = meta.get("specialist_type") or meta.get("category") or ""
    return str(topic).strip().lower()


def _tile_is_unbookable_specialist(tile: dict[str, Any]) -> bool:
    """Apply ``is_unbookable_specialist_activity`` to a raw activity tile dict."""
    meta = tile.get("meta") if isinstance(tile.get("meta"), dict) else {}
    return is_unbookable_specialist_activity(
        specialist_type=meta.get("specialist_type") or meta.get("category"),
        activity_domain=meta.get("activity_domain") or tile.get("activity_domain"),
        source_agent=tile.get("source_agent"),
        provenance=_tile_provenance(tile),
        matched_tile=tile,
        deeplink=str(tile.get("deeplink") or tile.get("deeplink_url") or "") or None,
    )


def _tile_is_bookable_specialist(tile: dict[str, Any]) -> bool:
    """True when a tile is an AI-suggested Tier-1 specialist activity that IS bookable.

    Used both for the affiliate-evidence gate and to keep a specialist's section
    alive when at least one of its activities still has an affiliate product.
    """
    meta = tile.get("meta") if isinstance(tile.get("meta"), dict) else {}
    if not is_tier1_specialist_activity(
        specialist_type=meta.get("specialist_type") or meta.get("category"),
        activity_domain=meta.get("activity_domain") or tile.get("activity_domain"),
        source_agent=tile.get("source_agent"),
        provenance=_tile_provenance(tile),
    ):
        return False
    return has_affiliate_booking(
        tile, str(tile.get("deeplink") or tile.get("deeplink_url") or "") or None
    )


def prune_unbookable_specialist_artifacts(
    activity_tiles: list[dict[str, Any]],
    strategy_sections: list[dict[str, Any]],
    day_cards: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str], set[str]]:
    """Drop browse-pool/map artifacts left by the unbookable-specialist policy.

    Shape-agnostic companion to the day-card block drop (graph
    ``_drop_unbookable_specialist_blocks`` / builder Phase 2.55): those drop the
    itinerary BLOCKS, this reconciles the TILE POOL (browse pool + map pins) and
    the ADVICE SECTIONS so a fully-unbookable specialist leaves no ghost section
    or orphaned map pin.

    GUARDED by the same global affiliate-evidence rule as the block drops: it only
    acts when at least one in-scope (AI-suggested Tier-1) specialist activity tile
    carries an affiliate booking. A partner-disabled deployment or a fresh build
    with placeholder deeplinks therefore prunes NOTHING.

    Rules:
      1. Remove every ``activity_tiles`` entry that ``is_unbookable_specialist_activity``
         (browse pool + map pins both derive from this pool). General/Google-Places
         activity tiles, user-browse-added tiles, hotels and flights are never touched.
      2. Remove a ``strategy_sections`` entry for a specialist ONLY when that
         specialist now has ZERO bookable activity tiles AND ZERO remaining
         day-card blocks. A mixed specialist (≥1 bookable tile/block) keeps its
         section and its bookable tile(s).

    Returns ``(kept_tiles, kept_sections, dropped_tile_ids, dropped_specialist_types)``.
    The original lists are never mutated; callers splice the kept lists into their
    own container shape and use the dropped sets for logging / replace signaling.
    """
    activity_tiles = activity_tiles or []
    strategy_sections = strategy_sections or []
    day_cards = day_cards or []

    # Evidence gate over the TILE pool (semantically identical to the block-drop
    # gate): at least one in-scope specialist tile must be bookable.
    if not any(_tile_is_bookable_specialist(t) for t in activity_tiles if isinstance(t, dict)):
        return list(activity_tiles), list(strategy_sections), set(), set()

    # (1) Prune unbookable specialist tiles; track per-topic bookable survivors AND
    # the topics whose tiles this run actually dropped.
    dropped_tile_ids: set[str] = set()
    topics_with_bookable_tile: set[str] = set()
    topics_with_dropped_tile: set[str] = set()
    kept_tiles: list[dict[str, Any]] = []
    for tile in activity_tiles:
        if not isinstance(tile, dict):
            kept_tiles.append(tile)
            continue
        if _tile_is_unbookable_specialist(tile):
            tid = tile.get("id")
            if tid is not None:
                dropped_tile_ids.add(str(tid))
            topic = _tile_specialist_topic(tile)
            if topic:
                topics_with_dropped_tile.add(topic)
            continue
        if _tile_is_bookable_specialist(tile):
            topic = _tile_specialist_topic(tile)
            if topic:
                topics_with_bookable_tile.add(topic)
        kept_tiles.append(tile)

    # (2) Determine which specialist topics still own a day-card block (any block
    # whose specialist_type matches, including a placed bookable one).
    topics_with_block: set[str] = set()
    for card in day_cards:
        if not isinstance(card, dict):
            continue
        for block in card.get("blocks", []) or []:
            if not isinstance(block, dict):
                continue
            topic = str(block.get("specialist_type") or "").strip().lower()
            if topic:
                topics_with_block.add(topic)

    # (3) Drop a section only when THIS run made the specialist fully unbookable:
    # we dropped at least one of its tiles AND it now has no bookable tile AND no
    # remaining day-card block. Gating on ``topics_with_dropped_tile`` keeps the
    # drop to specialists the policy actually emptied -- an infeasible specialist
    # section (zero tiles/blocks by design, _inject_specialist_tiles_into_state
    # skips infeasible) or any other zero-activity / Tier-2 section is preserved
    # even when another specialist fires the affiliate-evidence gate.
    dropped_specialist_types: set[str] = set()
    kept_sections: list[dict[str, Any]] = []
    for section in strategy_sections:
        if isinstance(section, dict):
            stype = str(section.get("specialist_type") or "").strip().lower()
            if (
                stype
                and stype not in ("general", "local_expert")
                and stype in topics_with_dropped_tile
                and stype not in topics_with_bookable_tile
                and stype not in topics_with_block
            ):
                dropped_specialist_types.add(stype)
                continue
        kept_sections.append(section)

    return kept_tiles, kept_sections, dropped_tile_ids, dropped_specialist_types


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

    # Resolve the destination centroid once (cached L1+L2) so partner matches can
    # be geo-validated even when the source tile carries no coords -- which is the
    # case for every LLM-generated specialist tile. Without this, a wrong-country
    # product (Bali dive -> Cancun) passes the geo guard and stamps a foreign
    # deeplink + pin. Best-effort: a geocode miss leaves centroid=None (no change).
    centroid: tuple[float, float] | None = None
    try:
        from app.tile_service.google_places_provider import _geocode_destination_async

        centroid = await _geocode_destination_async(destination)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("[PARTNER] centroid geocode failed for %s: %s", destination, exc)

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
        and t.get("type", "activity") == "activity"
        and "hotel" not in {str(tag).lower() for tag in t.get("tags", [])}
        and not _has_persisted_partner_match(t)
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
        if not _partner_match_is_geo_compatible(tile, result, centroid):
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
        if result_meta.get("category"):
            meta["category"] = result_meta["category"]
        tile["meta"] = meta

    if matched:
        logger.info("[PARTNER] Enriched %d/%d tiles for %s", matched, len(filtered), destination)
