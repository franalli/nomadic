"""
Centralized regex/keyword pattern registries for the planner.

Imported by router_extraction.py and planner tools.
Keep pattern order intact — TRAVELER_PATTERNS is order-sensitive (most specific first).
"""

# Budget patterns - extract numeric budget values
BUDGET_PATTERNS = [
    r"(?:budget|bugdet|spend|spending)\s*(?:is|of|around|about|to|at)?\s*\$?([\d,]+(?:\.\d{2})?)\s*(?:k|K|thousand)?",
    r"\$?([\d,]+(?:\.\d{2})?)\s*(?:k|K|thousand)?\s*(?:budget|bugdet)",
    # Pattern: "have/got $X to spend" or "have/got $X for the trip"
    r"(?:have|got)\s*\$?([\d,]+(?:\.\d{2})?)\s*(?:k|K|thousand)?"
    r"\s*(?:to spend|for (?:the |this )?trip)?",
    r"(?:up to|max(?:imum)?|around|about)\s*\$?([\d,]+(?:\.\d{2})?)\s*(?:k|K|thousand)?",
]

# Traveler patterns - extract number of adults/children
# IMPORTANT: Order matters! Most specific patterns first.
TRAVELER_PATTERNS = [
    # Combined adults AND children - MUST BE FIRST to capture "4 adults 2 kids"
    r"(\d+)\s*(?:adult|person)s?\s*(?:and|,|&)\s*(\d+)\s*(?:child|kid|children|minor)s?",
    # Children only (e.g., "2 children", "3 kids")
    r"(\d+)\s*(?:child|kid|children|minor)s?",
    # Group/party size (e.g., "party of 4")
    r"(?:party of|group of|traveling with)\s*(\d+)",
    # Adults only - AFTER combined pattern (e.g., "2 adults", "4 people")
    r"(\d+)\s*(?:adult|person|people|traveler)s?(?:\s+of us)?",
    # Qualitative patterns - LAST (e.g., "family of 4", "couple", "solo")
    r"(?:family of|couple|solo|alone)",
]

# Keywords that indicate EXPLICIT settings/toggle intent.
# Must be specific enough to avoid false positives on activity descriptions
# like "yoga class", "cooking activity", "business district".
SETTINGS_KEYWORDS = [
    # Explicit toggle phrases
    "turn off",
    "turn on",
    "no need",
    "don't need",
    "skip flights",
    "skip hotels",
    "no flights",
    "no hotels",
    "include flights",
    "include hotels",
    # Flight preferences (require "flight" context)
    "direct flight",
    "nonstop flight",
    "no layover",
    "layovers",
    "first class",
    "business class",
    "economy class",
    "one way",
    "round trip",
    # Hotel preferences (require "hotel"/"star" context)
    "star hotel",
    "star resort",
    "luxury hotel",
    "luxury resort",
    "budget hotel",
    "budget stay",
    "mid-range hotel",
]
