# backend/app/services/unsplash_queries.py
"""
Unsplash query synthesis for destination hero images.

Activity-specific queries stay curated because they are bounded product
categories. Destination queries are generated generically to avoid embedding
curated world-data maps in backend code.
"""

# =============================================================================
# ACTIVITY-SPECIFIC QUERIES - Override destination queries for specialists
# =============================================================================
# When an activity is specified, use these queries instead of appending
# the activity to destination queries (which produces poor results like
# "bali rice terraces temple diving")
# Update _QUERIES_VERSION when changing query synthesis behavior.
_QUERIES_VERSION = "2026-03-13"

ACTIVITY_QUERIES: dict[str, str] = {
    "diving": "scuba diving underwater coral reef tropical fish",
    "hiking": "mountain hiking trail backpacker summit view",
    "skiing": "skiing powder snow alpine mountain slopes",
    "surfing": "surfing ocean wave beach",
    "climbing": "rock climbing mountaineer cliff",
    "snorkeling": "snorkeling tropical reef underwater",
    "kayaking": "kayaking ocean river paddle",
    "cycling": "cycling mountain bike trail",
    # Tier 2 experience categories
    "yoga": "yoga retreat meditation wellness",
    "cooking": "cooking class local food market",
    "nightlife": "nightlife bar rooftop cocktail",
    "sailing": "sailing yacht ocean sunset",
    "food": "food tour street food local cuisine",
    "wine": "wine tasting vineyard cellar",
    "photography": "photography tour scenic viewpoint",
    "wellness": "spa wellness retreat relaxation",
    "culture": "cultural tour temple museum heritage",
    "music": "live music concert venue",
    "wildlife_safari": "african safari wildlife savanna elephant lion",
}

_UNDERWATER_ACTIVITY_QUERIES = {"diving", "snorkeling"}
_GENERIC_DESTINATION_SUFFIX = "travel destination landscape cityscape"


def _canonicalize_destination(destination: str) -> str:
    """Normalize whitespace/casing without injecting destination-specific data."""
    normalized = " ".join((destination or "").replace("/", " ").split()).strip(" ,")
    if not normalized:
        return ""

    words: list[str] = []
    for word in normalized.split(" "):
        if word.isupper() and len(word) <= 4:
            words.append(word)
            continue
        words.append(word[:1].upper() + word[1:].lower())
    return " ".join(words)


def _generic_destination_query(destination: str) -> str:
    """Build a generic destination query without curated world-data lookups."""
    canonical = _canonicalize_destination(destination)
    if not canonical:
        return _GENERIC_DESTINATION_SUFFIX
    return f"{canonical} {_GENERIC_DESTINATION_SUFFIX}"


def get_query_for_destination(destination: str, activities: list[str] | None = None) -> str:
    """
    Get a deterministic search query for a destination, optionally using activity-specific queries.

    Args:
        destination: The destination name (case-insensitive)
        activities: Optional list of activity categories (e.g., ["diving", "hiking"])

    Returns:
        For specialist activities (diving, hiking, skiing, etc.):
            Uses ACTIVITY_QUERIES for topic-relevant images (e.g., underwater scenes for diving)
        For general queries:
            Uses generic destination query synthesis with no curated world-data map
    """
    destination_query = _generic_destination_query(destination)

    # If an activity is specified, use activity-specific query for better results.
    # Underwater activities use pure activity queries; land activities keep the
    # destination in the query for place-specific imagery.
    if activities and len(activities) > 0:
        activity = activities[0].lower().strip()
        if activity in ACTIVITY_QUERIES:
            if activity not in _UNDERWATER_ACTIVITY_QUERIES:
                return f"{destination_query} {activity} {ACTIVITY_QUERIES[activity]}"
            return ACTIVITY_QUERIES[activity]
        return f"{destination_query} {activity} travel experience"

    return destination_query
