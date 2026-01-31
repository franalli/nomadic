"""
Deterministic placeholder images for travel content.
Uses curated Unsplash photo IDs (images.unsplash.com) instead of
the deprecated source.unsplash.com service.
"""

from typing import List, Optional

# Curated Unsplash photo IDs by category (high-quality travel imagery)
PLACEHOLDER_IMAGES = {
    "destination": [
        "photo-1488646953014-85cb44e25828",  # Travel landscape
        "photo-1501785888041-af3ef285b470",  # Mountain vista
        "photo-1476514525535-07fb3b4ae5f1",  # Tropical beach
        "photo-1469474968028-56623f02e42e",  # Road trip
        "photo-1507525428034-b723cf961d3e",  # Beach paradise
        "photo-1530789253388-582c481c54b0",  # Travel adventure
    ],
    "culture": [
        "photo-1493976040374-85c8e12f0c0e",  # Temple
        "photo-1518998053901-5348d3961a04",  # Market
        "photo-1552832230-c0197dd311b5",  # Architecture
        "photo-1504598318550-17eba1008a68",  # Local food
    ],
    "adventure": [
        "photo-1527631746610-bca00a040d60",  # Hiking
        "photo-1501555088652-021faa106b9b",  # Outdoor adventure
        "photo-1551632811-561732d1e306",  # Climbing
        "photo-1506905925346-21bda4d32df4",  # Mountain peak
    ],
    "diving": [
        "photo-1544551763-46a013bb70d5",  # Underwater coral
        "photo-1559827260-dc66d52bef19",  # Scuba diver
        "photo-1546026423-cc4642628d2b",  # Tropical fish
        "photo-1582967788606-a171c1080cb0",  # Ocean reef
    ],
    "hiking": [
        "photo-1551632811-561732d1e306",  # Mountain trail
        "photo-1506905925346-21bda4d32df4",  # Summit view
        "photo-1464822759023-fed622ff2c3b",  # Mountain landscape
        "photo-1527631746610-bca00a040d60",  # Trekking
    ],
    "skiing": [
        "photo-1551524559-8af4e6624178",  # Ski slopes
        "photo-1605540436563-5bca919ae766",  # Snowy mountain
        "photo-1517483000871-1dbf64a6e1c6",  # Ski resort
        "photo-1516939884455-1445c8652f83",  # Winter sports
    ],
    "hotel": [
        "photo-1566073771259-6a8506099945",  # Resort pool
        "photo-1551882547-ff40c63fe5fa",  # Hotel room
        "photo-1564501049412-61c2a3083791",  # Luxury hotel
        "photo-1520250497591-112f2f40a3f4",  # Beach resort
    ],
    "activity": [
        "photo-1527631746610-bca00a040d60",  # Adventure
        "photo-1501555088652-021faa106b9b",  # Outdoor
        "photo-1551632811-561732d1e306",  # Active
        "photo-1506905925346-21bda4d32df4",  # Scenic
    ],
}


def _hash_string(s: str) -> int:
    """Simple string hash for deterministic selection."""
    h = 0
    for char in s:
        h = ((h << 5) - h) + ord(char)
        h = h & 0xFFFFFFFF  # Keep it 32-bit
    return h


def get_placeholder_image(
    category: str = "destination",
    seed: Optional[str] = None,
    width: int = 800,
    height: int = 600,
) -> str:
    """
    Get a deterministic placeholder image URL.

    Args:
        category: Image category (destination, culture, adventure, diving, etc.)
        seed: Optional seed for deterministic selection
        width: Image width
        height: Image height

    Returns:
        Unsplash CDN URL for the image
    """
    images = PLACEHOLDER_IMAGES.get(category, PLACEHOLDER_IMAGES["destination"])

    if seed:
        index = _hash_string(seed) % len(images)
    else:
        index = 0

    photo_id = images[index]
    return f"https://images.unsplash.com/{photo_id}?w={width}&h={height}&fit=crop&auto=format"


def get_destination_gallery(destination: str) -> List[dict]:
    """
    Get a set of 3 gallery images for a destination.

    Args:
        destination: Destination name for seeding

    Returns:
        List of gallery items with label and image_url
    """
    # Note: destination is used for seeding image URLs below
    return [
        {
            "label": "Destination",
            "image_url": get_placeholder_image("destination", f"{destination}-dest", 800, 600),
        },
        {
            "label": "Culture",
            "image_url": get_placeholder_image("culture", f"{destination}-culture", 800, 600),
        },
        {
            "label": "Adventure",
            "image_url": get_placeholder_image("adventure", f"{destination}-adventure", 800, 600),
        },
    ]


def get_hero_image(category: str, seed: Optional[str] = None) -> str:
    """
    Get a hero image for a specialist or activity.

    Args:
        category: Specialist type (diving, hiking, skiing, etc.)
        seed: Optional seed for deterministic selection

    Returns:
        Unsplash CDN URL for the hero image
    """
    return get_placeholder_image(category, seed, 800, 400)


def get_activity_image(topic: str, destination: str, title: str) -> str:
    """
    Get a placeholder image for an activity without curated content.

    Uses deterministic selection based on the activity details to ensure
    consistent images across sessions.

    Args:
        topic: Specialist type (diving, hiking, skiing, etc.)
        destination: Destination name
        title: Activity title

    Returns:
        Unsplash CDN URL for the activity image
    """
    # Use topic category if available, otherwise fall back to activity
    category = topic if topic in PLACEHOLDER_IMAGES else "activity"
    seed = f"{destination}-{topic}-{title}"
    return get_placeholder_image(category, seed, 800, 600)
