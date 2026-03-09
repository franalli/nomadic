# backend/app/services/unsplash_queries.py
"""
Curated Unsplash Queries — Optimization Layer
==============================================

These mappings produce higher-quality hero images for known destinations.
Unknown destinations fall through to: ``f"{destination} travel landmark"``

This is a CURATED OPTIMIZATION — the system works without any entries.
Add entries only when the generic fallback produces poor image results.

Activity-specific queries override destination queries when specialist
activities are specified (e.g., diving, hiking, skiing) to ensure
topic-relevant images.
"""

# =============================================================================
# ACTIVITY-SPECIFIC QUERIES - Override destination queries for specialists
# =============================================================================
# When an activity is specified, use these queries instead of appending
# the activity to destination queries (which produces poor results like
# "bali rice terraces temple diving")
# Curated Unsplash search optimization — graceful fallback for unknown destinations.
# Update _QUERIES_VERSION when adding/modifying query entries.
_QUERIES_VERSION = "2026-03-09"

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

# Curated mapping for common destinations
# Keys are lowercase for case-insensitive lookup
DESTINATION_QUERIES: dict[str, str] = {
    # Europe
    "paris": "paris eiffel tower iconic landmark",
    "london": "london big ben tower bridge iconic",
    "rome": "rome colosseum iconic landmark",
    "barcelona": "barcelona sagrada familia gaudi",
    "amsterdam": "amsterdam canals houses",
    "berlin": "berlin brandenburg gate",
    "prague": "prague charles bridge old town",
    "vienna": "vienna schonbrunn palace",
    "budapest": "budapest parliament danube",
    "lisbon": "lisbon portugal cityscape",
    "madrid": "madrid plaza mayor",
    "milan": "milan duomo cathedral",
    "venice": "venice grand canal gondola",
    "florence": "florence duomo ponte vecchio",
    "athens": "athens acropolis parthenon",
    "dublin": "dublin temple bar",
    "edinburgh": "edinburgh castle old town",
    "copenhagen": "copenhagen nyhavn colorful",
    "stockholm": "stockholm gamla stan",
    "oslo": "oslo fjord opera house",
    "helsinki": "helsinki cathedral harbor",
    "zurich": "zurich lake alps",
    "geneva": "geneva jet d'eau lake",
    "munich": "munich marienplatz",
    "brussels": "brussels grand place",
    "reykjavik": "iceland northern lights landscape",
    "santorini": "santorini white blue domes",
    "mykonos": "mykonos windmills beach",
    "dubrovnik": "dubrovnik old town walls",
    "split": "split diocletian palace",
    "krakow": "krakow old town square",
    "warsaw": "warsaw old town",
    # Asia
    "tokyo": "tokyo skyline neon cityscape iconic",
    "kyoto": "kyoto temple bamboo",
    "osaka": "osaka castle dotonbori",
    "seoul": "seoul gyeongbokgung palace",
    "bangkok": "bangkok grand palace temple",
    "singapore": "singapore marina bay skyline iconic",
    "hong kong": "hong kong victoria harbor skyline",
    "shanghai": "shanghai bund skyline",
    "beijing": "beijing forbidden city",
    "taipei": "taipei 101 skyline",
    "hanoi": "hanoi old quarter",
    "ho chi minh city": "ho chi minh city saigon",
    "kuala lumpur": "kuala lumpur petronas towers",
    "bali": "bali rice terraces temple",
    "phuket": "phuket beach tropical",
    "manila": "manila skyline",
    "jakarta": "jakarta skyline",
    "delhi": "delhi india gate",
    "mumbai": "mumbai gateway india",
    "jaipur": "jaipur hawa mahal pink city",
    "agra": "taj mahal agra",
    "kathmandu": "kathmandu nepal temples",
    "colombo": "colombo sri lanka",
    # Middle East
    "dubai": "dubai burj khalifa skyline iconic",
    "abu dhabi": "abu dhabi sheikh zayed mosque",
    "doha": "doha qatar skyline",
    "istanbul": "istanbul hagia sophia bosphorus",
    "tel aviv": "tel aviv beach skyline",
    "jerusalem": "jerusalem old city walls",
    "amman": "amman jordan citadel",
    "petra": "petra jordan treasury",
    # Africa
    "cairo": "cairo pyramids giza sphinx",
    "marrakech": "marrakech medina morocco",
    "cape town": "cape town table mountain",
    "johannesburg": "johannesburg skyline",
    "nairobi": "nairobi kenya safari",
    "zanzibar": "zanzibar beach stone town",
    "casablanca": "casablanca morocco hassan mosque",
    "tunis": "tunis medina",
    # Americas
    "new york": "new york manhattan skyline iconic",
    "los angeles": "los angeles hollywood beach",
    "san francisco": "san francisco golden gate bridge",
    "las vegas": "las vegas strip night",
    "miami": "miami beach art deco",
    "chicago": "chicago skyline river",
    "boston": "boston historic",
    "washington dc": "washington dc capitol monument",
    "seattle": "seattle space needle",
    "toronto": "toronto cn tower skyline",
    "vancouver": "vancouver mountains harbor",
    "montreal": "montreal old town",
    "mexico city": "mexico city zocalo palacio",
    "cancun": "cancun beach caribbean",
    "havana": "havana cuba classic cars",
    "rio de janeiro": "rio de janeiro christ redeemer copacabana",
    "buenos aires": "buenos aires la boca tango",
    "lima": "lima peru miraflores",
    "bogota": "bogota colombia",
    "cartagena": "cartagena colombia colonial",
    "santiago": "santiago chile andes",
    "cusco": "cusco peru machu picchu",
    "machu picchu": "machu picchu peru inca",
    # Oceania
    "sydney": "sydney opera house harbor iconic",
    "melbourne": "melbourne australia",
    "auckland": "auckland new zealand",
    "queenstown": "queenstown new zealand mountains",
    "fiji": "fiji beach tropical island",
    # Caribbean
    "jamaica": "jamaica beach caribbean",
    "bahamas": "bahamas beach turquoise",
    "barbados": "barbados beach",
    "puerto rico": "puerto rico san juan old",
    "aruba": "aruba beach caribbean",
    # Adventure destinations
    "maldives": "maldives overwater bungalow",
    "seychelles": "seychelles beach granite",
    "mauritius": "mauritius beach tropical",
    "bora bora": "bora bora overwater lagoon",
    "tahiti": "tahiti french polynesia",
    "patagonia": "patagonia torres del paine",
    "iceland": "iceland northern lights waterfall",
    "norway": "norway fjords",
    "swiss alps": "swiss alps mountains village",
    "costa rica": "costa rica rainforest beach",
}


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
            Uses DESTINATION_QUERIES for location-specific images
    """
    # If an activity is specified, use activity-specific query for better results
    # Underwater activities (diving) use pure activity queries - coral reefs look similar everywhere
    # Land activities (hiking, skiing) combine destination + activity for location-specific views
    if activities and len(activities) > 0:
        activity = activities[0].lower().strip()
        if activity in ACTIVITY_QUERIES:
            # Land-based activities: combine destination for location-specific imagery
            # e.g., "bali hiking mountain trail" instead of generic "mountain hiking trail"
            _UNDERWATER = {"diving", "snorkeling"}
            if activity not in _UNDERWATER:
                return f"{destination} {activity} {ACTIVITY_QUERIES[activity]}"
            # Underwater activities: use pure activity query (coral looks the same everywhere)
            return ACTIVITY_QUERIES[activity]
        # Novel Tier 2 category — generate a reasonable query
        return f"{destination} {activity} travel experience"

    # Fallback to destination-based query
    normalized = destination.lower().strip()
    return DESTINATION_QUERIES.get(normalized, f"{destination} travel landmark")
