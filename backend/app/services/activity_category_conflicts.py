"""Shared category conflict rules for partner activity matching."""

from __future__ import annotations

CATEGORY_CONFLICTS: dict[str, set[str]] = {
    # Sport-adjacent conflicts (original)
    "diving": {"snorkel", "snorkeling", "snorkelling"},
    "snorkeling": {"scuba", "scuba diving", "deep dive"},
    "hiking": {"walking tour", "city walk", "food tour"},
    "cycling": {"motorbike", "scooter", "atv"},
    "surfing": {"bodyboard", "paddleboard", "kayak"},
    "sailing": {"cruise", "ferry"},
    # Food/cooking vs outdoor sports
    "food": {"cycling", "hiking", "diving", "surfing", "climbing", "sailing", "bike", "trek"},
    "cooking": {"cycling", "hiking", "diving", "surfing", "climbing", "sailing", "bike", "trek"},
    # Yoga/spa vs active/tour categories
    "yoga": {"cycling", "biking", "sightseeing", "city tour", "bus tour", "boat tour", "bike"},
    "spa": {"cycling", "biking", "sightseeing", "city tour", "bus tour", "boat tour", "bike"},
    # Nightlife vs outdoor sports
    "nightlife": {"hiking", "diving", "surfing", "climbing", "sailing", "cycling", "trek", "bike"},
    # Shopping vs outdoor sports
    "shopping": {"hiking", "diving", "surfing", "climbing", "sailing", "cycling", "trek", "bike"},
}


def has_category_conflict(specialist_category: str | None, product_title: str) -> bool:
    """Return True when a partner title clearly conflicts with the requested category."""
    if not specialist_category:
        return False
    conflicts = CATEGORY_CONFLICTS.get(specialist_category.lower(), set())
    product_lower = product_title.lower()
    return any(conflict in product_lower for conflict in conflicts)
