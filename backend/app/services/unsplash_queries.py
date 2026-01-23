# backend/app/services/unsplash_queries.py
"""
Deterministic query mapping for Unsplash image searches.

Maps destination names to curated search queries that return high-quality,
representative images. Fallback to generic "{destination} travel landmark"
for unknown destinations.
"""

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
    "lisbon": "lisbon tram alfama",
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
    Get a deterministic search query for a destination, optionally enhanced with activities.

    Args:
        destination: The destination name (case-insensitive)
        activities: Optional list of activity categories (e.g., ["Hiking", "Photography"])

    Returns:
        A curated search query for known destinations (with activity if provided),
        or "{destination} travel landmark {activity}" for unknown ones.
    """
    normalized = destination.lower().strip()
    base_query = DESTINATION_QUERIES.get(normalized, f"{destination} travel landmark")

    # Enhance query with primary activity if provided
    if activities and len(activities) > 0:
        activity = activities[0].lower()
        return f"{base_query} {activity}"

    return base_query
