from __future__ import annotations

import secrets
import string
from datetime import datetime
from typing import Any, Dict

from app.placeholders import get_activity_image
from app.schemas import PlanDocumentData

_ALPHABET = string.ascii_lowercase + string.digits
_SLUG_LENGTH = 8


def generate_slug() -> str:
    """Generate a short URL-safe slug (collision checked by caller)."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(_SLUG_LENGTH))


def _is_signed_media_proxy_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if "/api/media/google-places-photo" in value:
        return True
    return "/api/media/" in value


_TILE_TYPE_TO_CATEGORY = {"stay": "hotel", "accommodation": "hotel"}


def _public_fallback(image_url: Any, label: str, destination: str) -> str | None:
    """Replace signed media proxy URLs with public Unsplash placeholders."""
    if not _is_signed_media_proxy_url(image_url):
        return image_url
    if not destination:
        return None
    category = _TILE_TYPE_TO_CATEGORY.get(label, label)
    return get_activity_image(category, destination, category)


def build_share_snapshot(doc_data: PlanDocumentData) -> dict:
    """Build an immutable share snapshot from PlanDocumentData."""
    full = doc_data.model_dump()
    snapshot: Dict[str, Any] = {
        "trip_inputs": full.get("trip_inputs"),
        "tiles": full.get("tiles", {}),
        "strategy_sections": full.get("strategy_sections", []),
        "day_cards": full.get("day_cards", []),
        "plan_view_state": full.get("plan_view_state"),
        "executed_strategy_topics": full.get("executed_strategy_topics", []),
        "constraint_violations": full.get("constraint_violations", []),
        "preferred_tile_ids": full.get("preferred_tile_ids", []),
    }

    trip_inputs = snapshot.get("trip_inputs") or {}
    destination = trip_inputs.get("destination", "") if isinstance(trip_inputs, dict) else ""

    for tile in snapshot.get("tiles", {}).values():
        if not isinstance(tile, dict):
            continue
        tile["image_url"] = _public_fallback(
            tile.get("image_url"), tile.get("type", "activity"), destination
        )

    for day_card in snapshot.get("day_cards", []):
        if not isinstance(day_card, dict):
            continue
        for block in day_card.get("blocks", []):
            if not isinstance(block, dict):
                continue
            block["image_url"] = _public_fallback(
                block.get("image_url"), block.get("activity_type", "activity"), destination
            )
            booked_tile = block.get("booked_tile")
            if isinstance(booked_tile, dict):
                booked_tile["image_url"] = _public_fallback(
                    booked_tile.get("image_url"),
                    booked_tile.get("type", "activity"),
                    destination,
                )

    return snapshot


def derive_share_metadata(doc_data: PlanDocumentData) -> dict:
    """Extract denormalized metadata for a shared trip row."""
    trip_inputs = doc_data.trip_inputs
    destination = trip_inputs.destination if trip_inputs else None
    start_date = trip_inputs.start_date if trip_inputs else None
    end_date = trip_inputs.end_date if trip_inputs else None
    day_count = len(doc_data.day_cards) if doc_data.day_cards else None

    parts: list[str] = []
    if destination:
        parts.append(destination)

    categories: list[str] = []
    if trip_inputs and trip_inputs.activity_settings:
        categories = trip_inputs.activity_settings.categories or []
    if categories:
        parts.append(" + ".join(c.title() for c in categories[:3]))

    if start_date and end_date:
        try:
            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date)
            parts.append(f"{start_dt.strftime('%b %d')}-{end_dt.strftime('%d')}")
        except ValueError:
            pass

    title = " · ".join(parts) if parts else "Shared Trip"
    return {
        "title": title[:200],
        "destination": destination,
        "day_count": day_count,
    }
