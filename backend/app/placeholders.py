"""
Deterministic placeholder images for travel content.
Uses curated Unsplash photo IDs (images.unsplash.com) instead of
the deprecated source.unsplash.com service.
"""

from typing import List, Optional

# Curated Unsplash photo IDs by category (high-quality travel imagery)
# Updated 2026-02 with fresh, topic-specific images
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
    # ==========================================================================
    # DIVING - Underwater, scuba, coral reefs, marine life
    # ==========================================================================
    "diving": [
        "photo-1544551763-46a013bb70d5",  # Colorful coral reef with tropical fish
        "photo-1559827260-dc66d52bef19",  # Scuba diver exploring underwater
        "photo-1544551763-77ef2d0cfc6c",  # Freediver in deep blue water
        "photo-1546026423-cc4642628d2b",  # Tropical fish school on reef
        "photo-1560275619-4662e36fa65c",  # Manta ray gliding in ocean
        "photo-1582967788606-a171c1080cb0",  # Ocean coral reef scene
        "photo-1583212292454-1fe6229603b7",  # Sea turtle swimming
        "photo-1589308078059-be1415eab4c3",  # Underwater diving scene
    ],
    # ==========================================================================
    # HIKING - Mountain trails, trekking, summit views, backpacking
    # ==========================================================================
    "hiking": [
        "photo-1551632811-561732d1e306",  # Hikers on mountain trail
        "photo-1506905925346-21bda4d32df4",  # Summit panoramic view
        "photo-1464822759023-fed622ff2c3b",  # Dramatic mountain landscape
        "photo-1527631746610-bca00a040d60",  # Backpacker on mountain trail
        "photo-1454496522488-7a8e488e8606",  # Mountain peak sunrise view
        "photo-1486870591958-9b9d0d1dda99",  # Alpine hiking trail
        "photo-1501555088652-021faa106b9b",  # Outdoor adventure hiking
        "photo-1519681393784-d120267933ba",  # Mountain landscape at dawn
    ],
    # ==========================================================================
    # SKIING - Powder snow, alpine slopes, ski resorts, winter sports
    # ==========================================================================
    "skiing": [
        "photo-1551524559-8af4e6624178",  # Skier carving through powder
        "photo-1605540436563-5bca919ae766",  # Snowy alpine mountain
        "photo-1517483000871-1dbf64a6e1c6",  # Ski resort chairlift
        "photo-1516939884455-1445c8652f83",  # Winter skiing action
        "photo-1483728642387-6c3bdd6c93e5",  # Snow-capped Mont Blanc peaks
        "photo-1520681279154-51b3fb4ea0f7",  # Alpine chalet in snow
        "photo-1548777123-e216912df7d8",  # Cozy fireplace après-ski
        "photo-1486184885347-1464b5f10296",  # Skier on powder snow slope
    ],
    "hotel": [
        "photo-1566073771259-6a8506099945",  # Resort pool
        "photo-1551882547-ff40c63fe5fa",  # Hotel room
        "photo-1564501049412-61c2a3083791",  # Luxury hotel
        "photo-1520250497591-112f2f40a3f4",  # Beach resort
    ],
    # ==========================================================================
    # YOGA - Retreats, meditation, wellness, mindfulness
    # ==========================================================================
    "yoga": [
        "photo-1545205597-3d9d02c29597",  # Yoga pose on beach at sunset
        "photo-1506126613408-eca07ce68773",  # Meditation in nature
        "photo-1588286840104-8957b019727f",  # Yoga class studio
        "photo-1599901860904-17e6ed7083a0",  # Yoga retreat tropical setting
        "photo-1544367567-0f2fcb009e0b",  # Woman doing yoga outdoors
        "photo-1552196563-55cd4e45efb3",  # Yoga mat and candles
    ],
    # ==========================================================================
    # NIGHTLIFE - Bars, rooftops, cocktails, clubs, evening dining
    # ==========================================================================
    "nightlife": [
        "photo-1566417713940-fe7c737a9ef2",  # Rooftop bar city view
        "photo-1514933651103-005eec06c04b",  # Bar cocktails neon
        "photo-1470337458703-46ad1756a187",  # Night city lights
        "photo-1516450360452-9312f5e86fc7",  # Party crowd dancing
        "photo-1572116469696-31de0f17cc34",  # Neon street nightlife
        "photo-1578474846511-04ba529f0b88",  # Cocktail bar ambience
    ],
    # ==========================================================================
    # COOKING - Classes, local food, markets, culinary experiences
    # ==========================================================================
    "cooking": [
        "photo-1556910103-1c02745aae4d",  # Cooking class ingredients
        "photo-1507048331197-7d4ac70811cf",  # Chef preparing food
        "photo-1466637574441-749b8f19452f",  # Fresh market produce
        "photo-1528712306091-ed0763094c98",  # Street food vendor
        "photo-1414235077428-338989a2e8c0",  # Plated gourmet food
        "photo-1551218808-94e220e084d2",  # Cooking with wok
    ],
    # ==========================================================================
    # WELLNESS - Spa, massage, hot springs, relaxation
    # ==========================================================================
    "wellness": [
        "photo-1540555700478-4be289fbec6d",  # Spa treatment room
        "photo-1544161515-4ab6ce6db874",  # Massage therapy
        "photo-1600334089648-b0d9d3028eb2",  # Hot spring natural pool
        "photo-1507652313519-d4e9174996dd",  # Zen stones water
        "photo-1515377905703-c4788e51af15",  # Tropical spa setting
        "photo-1519823551278-64ac92734fb1",  # Relaxation poolside
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
