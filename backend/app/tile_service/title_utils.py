"""Shared title matching helpers for tile enrichment and backfill.

Used by both ``google_places_provider`` and ``logistics_node`` to avoid
duplicate definitions.
"""

# Domain qualifiers stripped from specialist tile titles before GP matching.
_QUALIFIERS = frozenset(
    {
        "dive",
        "diving",
        "hike",
        "hiking",
        "trek",
        "trekking",
        "climb",
        "climbing",
        "surf",
        "surfing",
        "cycle",
        "cycling",
        "sail",
        "sailing",
        "ski",
        "skiing",
        "safari",
        "snorkel",
        "snorkeling",
        "kayak",
        "kayaking",
        "raft",
        "rafting",
        "session",
        "class",
        "lesson",
        "workshop",
        "experience",
        "tour",
        "adventure",
        "excursion",
        "morning",
        "evening",
        "sunrise",
        "sunset",
        "guided",
        "private",
        "group",
    }
)


def simplify_specialist_title(title: str) -> str:
    """Strip domain qualifiers for better GP matching.

    Specialist tiles often have names like "USAT Liberty Shipwreck Dive"
    that are too domain-specific for Google Places text search. Removing
    sport qualifiers yields "USAT Liberty Shipwreck" which matches better.
    """
    words = title.split()
    simplified = [w for w in words if w.lower() not in _QUALIFIERS]
    return " ".join(simplified) if simplified else title


def token_overlap_ratio(a: str, b: str) -> float:
    """Fraction of tokens in ``a`` that appear in ``b``."""
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    if not tokens_a:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a)
