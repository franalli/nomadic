"""
Season Detection Utility for Constraint Engine.

Determines season based on date and destination hemisphere.
Used by ConstraintGuard to detect seasonal activity conflicts.
"""

from datetime import datetime
from typing import Literal, Optional, Tuple

Season = Literal["winter", "spring", "summer", "fall"]

# Destinations and their hemispheres
# Northern hemisphere: winter = Dec-Feb, summer = Jun-Aug
# Southern hemisphere: winter = Jun-Aug, summer = Dec-Feb
NORTHERN_HEMISPHERE_DESTINATIONS = {
    # Europe - Alps
    "chamonix",
    "zermatt",
    "st. moritz",
    "innsbruck",
    "verbier",
    "courchevel",
    "val d'isere",
    "megeve",
    "cortina",
    # Europe - General
    "switzerland",
    "austria",
    "france",
    "italy",
    "germany",
    "alps",
    "dolomites",
    "pyrenees",
    # North America
    "aspen",
    "vail",
    "whistler",
    "jackson hole",
    "park city",
    "colorado",
    "utah",
    "wyoming",
    "montana",
    "canada",
    # Asia
    "japan",
    "niseko",
    "hakuba",
    "nepal",
    "tibet",
    "ladakh",
    "himalayas",
    "everest",
}

SOUTHERN_HEMISPHERE_DESTINATIONS = {
    # South America
    "patagonia",
    "argentina",
    "chile",
    "torres del paine",
    "bariloche",
    "portillo",
    "peru",
    "cusco",
    # Oceania
    "new zealand",
    "queenstown",
    "wanaka",
    # Africa
    "kilimanjaro",
    "south africa",
    "cape town",
}


def get_hemisphere(destination: str) -> Literal["northern", "southern", "tropical"]:
    """
    Determine hemisphere of destination.

    Returns 'tropical' for destinations near equator (no seasonal variation).
    """
    dest_lower = destination.lower()

    # Check known destinations
    for northern_dest in NORTHERN_HEMISPHERE_DESTINATIONS:
        if northern_dest in dest_lower or dest_lower in northern_dest:
            return "northern"

    for southern_dest in SOUTHERN_HEMISPHERE_DESTINATIONS:
        if southern_dest in dest_lower or dest_lower in southern_dest:
            return "southern"

    # Tropical/equatorial destinations (diving spots, beach destinations)
    tropical_keywords = [
        "bali",
        "maldives",
        "thailand",
        "philippines",
        "indonesia",
        "caribbean",
        "mexico",
        "hawaii",
        "fiji",
        "seychelles",
    ]
    for tropical in tropical_keywords:
        if tropical in dest_lower:
            return "tropical"

    # Default to northern hemisphere for unknown destinations
    return "northern"


def get_season(date_str: str, destination: str) -> Season:
    """
    Get season for a destination on a given date.

    Args:
        date_str: Date in YYYY-MM-DD format
        destination: Destination name

    Returns:
        Season: 'winter', 'spring', 'summer', or 'fall'
    """
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        # Default to winter for invalid dates
        return "winter"

    month = date.month
    hemisphere = get_hemisphere(destination)

    if hemisphere == "tropical":
        # Tropical destinations: use dry/wet season logic
        # For simplicity, map to nearest temperate equivalent
        if month in [11, 12, 1, 2, 3]:
            return "winter"  # Dry season (good for diving)
        else:
            return "summer"  # Wet/monsoon season

    # Northern hemisphere seasons
    if hemisphere == "northern":
        if month in [12, 1, 2]:
            return "winter"
        elif month in [3, 4, 5]:
            return "spring"
        elif month in [6, 7, 8]:
            return "summer"
        else:  # 9, 10, 11
            return "fall"
    else:
        # Southern hemisphere - inverted
        if month in [12, 1, 2]:
            return "summer"
        elif month in [3, 4, 5]:
            return "fall"
        elif month in [6, 7, 8]:
            return "winter"
        else:  # 9, 10, 11
            return "spring"


def is_ski_season(date_str: str, destination: str) -> bool:
    """Check if date falls within ski season for destination."""
    season = get_season(date_str, destination)
    return season == "winter"


def is_hiking_season(date_str: str, destination: str) -> bool:
    """
    Check if date falls within hiking season for destination.

    Most alpine hiking is best in summer/fall (June-October in northern hemisphere).
    """
    season = get_season(date_str, destination)
    # Hiking is generally good in summer and fall, marginal in spring
    return season in ["summer", "fall", "spring"]


def get_activity_season_conflict(
    activity_type: str, date_str: str, destination: str
) -> Optional[Tuple[str, str]]:
    """
    Check if activity conflicts with season.

    Returns:
        Tuple of (violation_message, suggested_alternative) or None if no conflict
    """
    if not date_str or not destination:
        return None

    season = get_season(date_str, destination)
    hemisphere = get_hemisphere(destination)

    if activity_type == "hiking":
        # Skip snow warning for tropical destinations - they don't have snow
        # Tropical "winter" is actually dry season, often the BEST time for hiking
        if season == "winter" and hemisphere != "tropical":
            return (
                f"Hiking trails in {destination} are typically closed or dangerous "
                f"in winter due to snow",
                "skiing",
            )

    elif activity_type == "skiing":
        if season == "summer":
            return (f"No snow conditions in {destination} during summer months", "hiking")
        elif season == "fall" and get_hemisphere(destination) == "northern":
            # Late fall might have early snow
            try:
                date = datetime.strptime(date_str, "%Y-%m-%d")
                if date.month == 11 and date.day < 15:
                    return (f"Ski season in {destination} typically starts mid-November", "hiking")
            except ValueError:
                pass

    return None


def get_recommended_specialist(
    season: Season, current_specialist: Optional[str], destination: str
) -> Optional[str]:
    """
    Suggest specialist switch based on season.

    Args:
        season: Current season at destination
        current_specialist: Currently active specialist (e.g., 'hiking')
        destination: Destination name

    Returns:
        Recommended specialist to switch to, or None if current is fine
    """
    if not current_specialist:
        return None

    # Check for conflicts
    if current_specialist == "hiking" and season == "winter":
        # Is this a ski destination?
        dest_lower = destination.lower()
        ski_keywords = ["alps", "chamonix", "zermatt", "aspen", "whistler", "niseko"]
        if any(kw in dest_lower for kw in ski_keywords):
            return "skiing"

    elif current_specialist == "skiing" and season == "summer":
        return "hiking"

    return None
