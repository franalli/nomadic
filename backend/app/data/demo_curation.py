"""
Demo Curation - Golden Path Content for Hero Destinations.

This module provides curated, high-quality content for demo destinations.
The strategy:
- Hero Destinations (Dubai, Rome, Chamonix): Use curated content for flawless demo
- All Other Cities: Fall back to live Amadeus API

Exports:
- CARRIER_MAP: Sanitize Amadeus test codes (XX, YY) to real airlines (Emirates, FlyDubai)
- DEMO_MANIFEST: Curated content for hero destinations
- get_curated_content(): Helper to fetch curated content by destination

Usage:
    from app.data.demo_curation import CARRIER_MAP, DEMO_MANIFEST, get_curated_content

    if destination.lower() in DEMO_MANIFEST:
        content = get_curated_content(destination, specialist_type="diving")
"""

from typing import Any, Dict, List, Optional

# =============================================================================
# CARRIER MAP - Sanitize Amadeus Test Codes to Real Airlines
# =============================================================================
# Maps generic/test carrier codes to Real Airlines for the demo
CARRIER_MAP: Dict[str, Dict[str, str]] = {
    # Major Airlines
    "SV": {"name": "Saudia", "logo": "SV"},
    "BA": {"name": "British Airways", "logo": "BA"},
    "EK": {"name": "Emirates", "logo": "EK"},
    "QR": {"name": "Qatar Airways", "logo": "QR"},
    "AZ": {"name": "ITA Airways", "logo": "AZ"},
    "LH": {"name": "Lufthansa", "logo": "LH"},
    "AF": {"name": "Air France", "logo": "AF"},
    "EY": {"name": "Etihad Airways", "logo": "EY"},
    "LX": {"name": "Swiss International", "logo": "LX"},
    "EZY": {"name": "easyJet", "logo": "U2"},  # easyJet uses U2 for logos
    "U2": {"name": "easyJet", "logo": "U2"},
    "FZ": {"name": "FlyDubai", "logo": "FZ"},
    # Force Amadeus Test Codes to real airlines
    "XX": {"name": "Emirates", "logo": "EK"},
    "YY": {"name": "FlyDubai", "logo": "FZ"},
    "6X": {"name": "Rex Airlines", "logo": "ZL"},
    "1X": {"name": "Qatar Airways", "logo": "QR"},
    "2X": {"name": "Etihad", "logo": "EY"},
}

# =============================================================================
# DEMO MANIFEST - Curated Content for Hero Destinations
# =============================================================================

DEMO_MANIFEST: Dict[str, Dict[str, Any]] = {
    # =========================================================================
    # DUBAI - Primary Demo Destination (Diving Focus)
    # =========================================================================
    "dubai": {
        # City Header - The "Vibe Shot" (Dubai skyline at golden hour)
        "hero_image": "https://images.unsplash.com/photo-1512453979798-5ea266f8880c?w=1920&q=80",
        "hero_image_alt": "Dubai skyline at sunset with Burj Khalifa",
        "tagline": "Where desert meets ocean",
        # Destination Gallery - "Vibe Trio" for Local Expert card
        "destination_gallery": [
            {
                "url": "https://images.unsplash.com/photo-1518684079-3c830dcef090?w=400&q=80",
                "alt": "Dubai Marina at Night",
            },
            {
                "url": "https://images.unsplash.com/photo-1580674684081-7617fbf3d745?w=400&q=80",
                "alt": "Old Dubai Souk",
            },
            {
                "url": "https://images.unsplash.com/photo-1547234935-80c7145ec969?w=400&q=80",
                "alt": "Desert Safari Sunset",
            },
        ],
        # Specialist Activities - Domain-specific content
        "specialist_content": {
            "diving": [
                {
                    "id": "curated_dubai_dive_001",
                    "title": "Deep Dive Dubai",
                    "description": (
                        "World's deepest pool at 60m with an underwater sunken city theme. "
                        "Perfect for confined water training and unique photo opportunities."
                    ),
                    "type": "activity",
                    "logic_hook": "Indoor facility - Summer safe & AC controlled",
                    # Freediver underwater - deep blue
                    "image": "https://images.unsplash.com/photo-1544551763-77ef2d0cfc6c?w=800&q=80",
                    "skill_level": "intermediate",
                    "duration_hours": 3,
                    "price_estimate": 350,
                    "currency": "USD",
                    "location": "Nad Al Sheba",
                    "booking_url": "https://deepdivedubai.com",
                    "highlights": [
                        "World's deepest pool (60m)",
                        "Sunken city theme",
                        "Year-round availability",
                        "PADI certified instructors",
                    ],
                },
                {
                    "id": "curated_dubai_dive_002",
                    "title": "Jumeirah Scuba Diving",  # Matches DIVING_KNOWLEDGE title
                    "description": (
                        "Shore diving at Jumeirah Beach with artificial reefs and marine life. "
                        "Shore entry makes this ideal for the day before your flight."
                    ),
                    "type": "activity",
                    "logic_hook": "No boat needed - shore entry",  # Matches DIVING_KNOWLEDGE
                    # Tropical fish reef
                    "image": "https://images.unsplash.com/photo-1544551763-46a013bb70d5?w=800&q=80",
                    "skill_level": "beginner",
                    "duration_hours": 4,
                    "price_estimate": 180,
                    "currency": "USD",
                    "location": "Jumeirah Beach",
                    "highlights": [
                        "Shore entry - no boat needed",
                        "Max depth 12m",
                        "Abundant marine life",
                        "Morning dives for best visibility",
                    ],
                },
                {
                    "id": "curated_dubai_dive_003",
                    "title": "MV Dara Wreck Dive",
                    "description": (
                        "Advanced wreck dive to the MV Dara, a passenger ship that sank "
                        "in 1961. Rich in history and marine life."
                    ),
                    "type": "activity",
                    "logic_hook": "Advanced cert required - 20m depth",
                    # Underwater wreck scene
                    "image": "https://images.unsplash.com/photo-1559827260-dc66d52bef19?w=800&q=80",
                    "skill_level": "advanced",
                    "duration_hours": 5,
                    "price_estimate": 280,
                    "currency": "USD",
                    "location": "Off Umm Al Quwain",
                    "highlights": [
                        "Historic wreck from 1961",
                        "20m depth",
                        "Advanced Open Water required",
                        "Rich coral growth",
                    ],
                },
            ],
            "general": [
                {
                    "id": "curated_dubai_gen_001",
                    "title": "Desert Safari with BBQ Dinner",
                    "description": (
                        "Experience sunset dune bashing, camel rides, and a traditional "
                        "BBQ dinner under the stars. Perfect activity for your no-fly rest day."
                    ),
                    "type": "activity",
                    "logic_hook": "Perfect for no-fly day - surface interval activity",
                    # Dubai desert dunes sunset
                    "image": "https://images.unsplash.com/photo-1547234935-80c7145ec969?w=800&q=80",
                    "duration_hours": 6,
                    "price_estimate": 85,
                    "currency": "USD",
                    "highlights": [
                        "Sunset dune bashing",
                        "Camel riding",
                        "Traditional BBQ dinner",
                        "Belly dancing show",
                    ],
                },
                {
                    "id": "curated_dubai_gen_002",
                    "title": "Burj Khalifa At The Top",
                    "description": (
                        "Visit the observation deck of the world's tallest building. "
                        "Book the sunset slot for spectacular views."
                    ),
                    "type": "activity",
                    "logic_hook": "Book sunset slot (5-7 PM) for best photos",
                    # Burj Khalifa
                    "image": "https://images.unsplash.com/photo-1582672060674-bc2bd808a8b5?w=800&q=80",
                    "duration_hours": 2,
                    "price_estimate": 45,
                    "currency": "USD",
                    "highlights": [
                        "World's tallest building",
                        "148th floor observation deck",
                        "360-degree views",
                    ],
                },
                {
                    "id": "curated_dubai_gen_003",
                    "title": "Dubai Marina Yacht Cruise",
                    "description": (
                        "Private yacht cruise through Dubai Marina with skyline views. "
                        "Includes refreshments and swimming stop."
                    ),
                    "type": "activity",
                    "logic_hook": "Morning slot avoids afternoon heat",
                    # Yacht/marina
                    "image": "https://images.unsplash.com/photo-1569263979104-865ab7cd8d13?w=800&q=80",
                    "duration_hours": 3,
                    "price_estimate": 150,
                    "currency": "USD",
                    "highlights": [
                        "Private yacht",
                        "Skyline views",
                        "Swimming stop",
                        "Refreshments included",
                    ],
                },
            ],
        },
        # Curated Hotels - 4K images, accurate logic hooks
        "curated_hotels": [
            {
                "id": "curated_dubai_hotel_001",
                "name": "Atlantis The Royal",
                "description": (
                    "Ultra-luxury beachfront resort with stunning architecture and "
                    "world-class amenities. The new crown jewel of Palm Jumeirah."
                ),
                "price_estimate": 850,
                "currency": "USD",
                "rating": 5,
                # Luxury infinity pool Dubai
                "image": "https://images.unsplash.com/photo-1582719508461-905c673771fd?w=800&q=80",
                "logic_hook": "15 min from Deep Dive Dubai",
                "amenities": ["pool", "spa", "beach", "fitness", "restaurant"],
                "location": "Palm Jumeirah",
                "distance_to_dive_sites": "15 min drive",
            },
            {
                "id": "curated_dubai_hotel_002",
                "name": "Jumeirah Beach Hotel",
                "description": (
                    "Iconic wave-shaped hotel with direct beach access. "
                    "Home to the Pavilion Dive Centre for convenient shore dives."
                ),
                "price_estimate": 420,
                "currency": "USD",
                "rating": 5,
                # Beach resort pool
                "image": "https://images.unsplash.com/photo-1571896349842-33c89424de2d?w=800&q=80",
                "logic_hook": "On-site dive center - walk to shore dives",
                "amenities": ["pool", "beach", "dive_center", "spa", "kids_club"],
                "location": "Jumeirah Beach",
                "distance_to_dive_sites": "On-site",
            },
            {
                "id": "curated_dubai_hotel_003",
                "name": "Rove Downtown",
                "description": (
                    "Modern budget-friendly hotel in the heart of Downtown Dubai. "
                    "Great value with rooftop pool and Burj Khalifa views."
                ),
                "price_estimate": 120,
                "currency": "USD",
                "rating": 4,
                # Modern hotel room
                "image": "https://images.unsplash.com/photo-1590490360182-c33d57733427?w=800&q=80",
                "logic_hook": "Budget-friendly, 25 min to dive sites",
                "amenities": ["pool", "gym", "restaurant"],
                "location": "Downtown Dubai",
                "distance_to_dive_sites": "25 min drive",
            },
        ],
        # Curated Flights - Demo-ready with Emirates branding
        # Note: Logistics node will apply 24h safety logic to these
        "curated_flights": [
            {
                "id": "curated_dubai_flight_001",
                "carrier_code": "EK",
                "carrier_name": "Emirates",
                "departure_time": "08:00",
                "duration": "PT6H30M",
                "price": 420,
                "currency": "USD",
                "logic_hook": None,  # Will be calculated by logistics node (unsafe - early)
            },
            {
                "id": "curated_dubai_flight_002",
                "carrier_code": "EK",
                "carrier_name": "Emirates",
                "departure_time": "14:30",
                "duration": "PT6H30M",
                "price": 480,
                "currency": "USD",
                "logic_hook": None,  # Will be calculated (borderline)
            },
            {
                "id": "curated_dubai_flight_003",
                "carrier_code": "EK",
                "carrier_name": "Emirates",
                "departure_time": "21:00",
                "duration": "PT6H30M",
                "price": 550,
                "currency": "USD",
                "logic_hook": None,  # Will be calculated (safe - late evening)
            },
        ],
        # Local logistics tips
        "logistics": {
            "best_diving_months": ["October", "November", "March", "April", "May"],
            "water_temp_range": "24-30°C",
            "visibility_range": "5-15m",
            "timezone": "GST (UTC+4)",
            "currency": "AED",
            "tipping": "10-15% at restaurants",
        },
    },
    # =========================================================================
    # ROME - Secondary Demo Destination (Cultural Focus)
    # =========================================================================
    "rome": {
        # Hero: Colosseum at golden hour
        "hero_image": "https://images.unsplash.com/photo-1552832230-c0197dd311b5?w=1920&q=80",
        "hero_image_alt": "Colosseum at golden hour",
        "tagline": "Eternal city, timeless experiences",
        # Destination Gallery - "Vibe Trio" for Local Expert card
        "destination_gallery": [
            {
                "url": "https://images.unsplash.com/photo-1525874684015-58379d421a52?w=400&q=80",
                "alt": "St. Peter's Basilica Dome",
            },
            {
                "url": "https://images.unsplash.com/photo-1515542622106-78bda8ba0e5b?w=400&q=80",
                "alt": "Roman Street with Ivy",
            },
            {
                "url": "https://images.unsplash.com/photo-1529260830199-42c24126f198?w=400&q=80",
                "alt": "Sunset over the Tiber",
            },
        ],
        "specialist_content": {
            "general": [
                {
                    "id": "curated_rome_gen_001",
                    "title": "Skip-the-Line Colosseum & Forum",
                    "description": (
                        "Expert-guided tour of the Colosseum, Roman Forum, and "
                        "Palatine Hill. Skip all queues with priority access."
                    ),
                    "type": "activity",
                    "logic_hook": "Book 8 AM slot to avoid crowds",
                    # Colosseum interior arches
                    "image": "https://images.unsplash.com/photo-1555992828-ca4dbe41d294?w=800&q=80",
                    "duration_hours": 3,
                    "price_estimate": 65,
                    "currency": "EUR",
                },
                {
                    "id": "curated_rome_gen_002",
                    "title": "Vatican Museums & Sistine Chapel",
                    "description": (
                        "Early morning access to the Vatican Museums before the crowds. "
                        "Includes Sistine Chapel and St. Peter's Basilica."
                    ),
                    "type": "activity",
                    "logic_hook": "Early entry (7:30 AM) - 80% fewer crowds",
                    # Vatican museum ceiling/gallery
                    "image": "https://images.unsplash.com/photo-1531572753322-ad063cecc140?w=800&q=80",
                    "duration_hours": 4,
                    "price_estimate": 85,
                    "currency": "EUR",
                },
                {
                    "id": "curated_rome_gen_003",
                    "title": "Trastevere Food Tour",
                    "description": (
                        "Evening food tour through Rome's most charming neighborhood. "
                        "Sample pasta, supplì, gelato, and local wines."
                    ),
                    "type": "activity",
                    "logic_hook": "Evening tour (6 PM) - cooler weather",
                    # Fresh pasta making
                    "image": "https://images.unsplash.com/photo-1473093295043-cdd812d0e601?w=800&q=80",
                    "duration_hours": 3,
                    "price_estimate": 75,
                    "currency": "EUR",
                },
            ],
        },
        "curated_hotels": [
            {
                "id": "curated_rome_hotel_001",
                "name": "Hotel de Russie",
                "description": (
                    "Legendary 5-star hotel with secret garden, steps from "
                    "Piazza del Popolo. Celebrity favorite."
                ),
                "price_estimate": 650,
                "currency": "EUR",
                "rating": 5,
                # Luxury hotel courtyard garden
                "image": "https://images.unsplash.com/photo-1618773928121-c32242e63f39?w=800&q=80",
                "logic_hook": "5 min walk to Spanish Steps",
                "amenities": ["spa", "garden", "restaurant", "fitness"],
                "location": "Via del Babuino",
            },
            {
                "id": "curated_rome_hotel_002",
                "name": "Chapter Roma",
                "description": (
                    "Boutique hotel in a former monastery. " "Rooftop bar with Colosseum views."
                ),
                "price_estimate": 280,
                "currency": "EUR",
                "rating": 4,
                # Rooftop terrace Rome
                "image": "https://images.unsplash.com/photo-1566665797739-1674de7a421a?w=800&q=80",
                "logic_hook": "Rooftop Colosseum views - book sunset drinks",
                "amenities": ["rooftop_bar", "restaurant", "spa"],
                "location": "Monti",
            },
            {
                "id": "curated_rome_hotel_003",
                "name": "The Beehive",
                "description": (
                    "Eco-friendly boutique hotel with vegetarian cafe. "
                    "Great value in the Termini area."
                ),
                "price_estimate": 95,
                "currency": "EUR",
                "rating": 3,
                # Cozy boutique hotel room
                "image": "https://images.unsplash.com/photo-1584132967334-10e028bd69f7?w=800&q=80",
                "logic_hook": "Budget pick - 10 min walk to Colosseum",
                "amenities": ["cafe", "garden"],
                "location": "Termini",
            },
        ],
        # Curated Flights - Demo-ready with ITA Airways branding
        "curated_flights": [
            {
                "id": "curated_rome_flight_001",
                "carrier_code": "AZ",
                "carrier_name": "ITA Airways",
                "departure_time": "07:45",
                "duration": "PT2H15M",
                "price": 145,
                "currency": "EUR",
                "logic_hook": "Direct flight - Fiumicino (FCO)",
            },
            {
                "id": "curated_rome_flight_002",
                "carrier_code": "AZ",
                "carrier_name": "ITA Airways",
                "departure_time": "12:30",
                "duration": "PT2H15M",
                "price": 165,
                "currency": "EUR",
                "logic_hook": "Direct flight - Fiumicino (FCO)",
            },
            {
                "id": "curated_rome_flight_003",
                "carrier_code": "AZ",
                "carrier_name": "ITA Airways",
                "departure_time": "18:00",
                "duration": "PT2H15M",
                "price": 185,
                "currency": "EUR",
                "logic_hook": "Direct flight - Fiumicino (FCO)",
            },
        ],
    },
    # =========================================================================
    # CHAMONIX - Alps Skiing Destination
    # =========================================================================
    "chamonix": {
        # Hero: Mont Blanc snowy peaks
        "hero_image": "https://images.unsplash.com/photo-1483728642387-6c3bdd6c93e5?w=1920&q=80",
        "hero_image_alt": "Mont Blanc and Chamonix valley",
        "tagline": "The birthplace of alpinism",
        # Destination Gallery - "Vibe Trio" for Local Expert card
        "destination_gallery": [
            {
                "url": "https://images.unsplash.com/photo-1520681279154-51b3fb4ea0f7?w=400&q=80",
                "alt": "Chamonix Mountain Chalet",
            },
            {
                "url": "https://images.unsplash.com/photo-1548777123-e216912df7d8?w=400&q=80",
                "alt": "Cozy Alpine Fireplace",
            },
            {
                "url": "https://images.unsplash.com/photo-1477346611705-65d1883cee1e?w=400&q=80",
                "alt": "Misty Alpine Forest",
            },
        ],
        "specialist_content": {
            "skiing": [
                {
                    "id": "curated_cham_ski_001",
                    "title": "Vallée Blanche Off-Piste",
                    "description": (
                        "Legendary 20km descent from Aiguille du Midi. "
                        "Requires guide and advanced skills."
                    ),
                    "type": "activity",
                    "logic_hook": "Book early AM - best snow conditions",
                    # Skier in powder snow
                    "image": "https://images.unsplash.com/photo-1551524559-8af4e6624178?w=800&q=80",
                    "skill_level": "advanced",
                    "duration_hours": 6,
                    "price_estimate": 350,
                    "currency": "EUR",
                },
                {
                    "id": "curated_cham_ski_002",
                    "title": "Grands Montets Day Pass",
                    "description": (
                        "Access to Chamonix's most challenging terrain. "
                        "2000m of vertical with legendary off-piste."
                    ),
                    "type": "activity",
                    "logic_hook": "Check avalanche conditions - off-piste paradise",
                    # Skier carving turns
                    "image": "https://images.unsplash.com/photo-1605540436563-5bca919ae766?w=800&q=80",
                    "skill_level": "intermediate",
                    "duration_hours": 8,
                    "price_estimate": 72,
                    "currency": "EUR",
                },
            ],
            "general": [
                {
                    "id": "curated_cham_gen_001",
                    "title": "Aiguille du Midi Cable Car",
                    "description": (
                        "Ascend to 3,842m for panoramic Mont Blanc views. "
                        "Step into the Void glass box for the brave."
                    ),
                    "type": "activity",
                    "logic_hook": "Book first cable car (8 AM) for clearest views",
                    # Mountain panorama view
                    "image": "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?w=800&q=80",
                    "duration_hours": 3,
                    "price_estimate": 65,
                    "currency": "EUR",
                },
            ],
        },
        "curated_hotels": [
            {
                "id": "curated_cham_hotel_001",
                "name": "Hameau Albert 1er",
                "description": (
                    "5-star Relais & Châteaux with Michelin-starred restaurant. "
                    "Ski-in/ski-out access."
                ),
                "price_estimate": 580,
                "currency": "EUR",
                "rating": 5,
                # Luxury alpine chalet
                "image": "https://images.unsplash.com/photo-1601918774946-25832a4be0d6?w=800&q=80",
                "logic_hook": "Michelin dining + ski-in/ski-out",
                "amenities": ["spa", "restaurant", "pool", "ski_room"],
                "location": "Town center",
            },
            {
                "id": "curated_cham_hotel_002",
                "name": "Le Refuge des Aiglons",
                "description": (
                    "Charming 4-star with indoor pool and spa. "
                    "Great location near Aiguille du Midi lift."
                ),
                "price_estimate": 220,
                "currency": "EUR",
                "rating": 4,
                # Cozy mountain hotel
                "image": "https://images.unsplash.com/photo-1520250497591-112f2f40a3f4?w=800&q=80",
                "logic_hook": "3 min walk to Aiguille du Midi lift",
                "amenities": ["pool", "spa", "restaurant", "ski_room"],
                "location": "Town center",
            },
        ],
        # Curated Flights - To Geneva (GVA), nearest airport to Chamonix
        "curated_flights": [
            {
                "id": "curated_cham_flight_001",
                "carrier_code": "LX",
                "carrier_name": "Swiss International",
                "departure_time": "06:30",
                "duration": "PT1H45M",
                "price": 195,
                "currency": "EUR",
                "logic_hook": "Direct to Geneva (GVA) - 1h15 transfer to Chamonix",
            },
            {
                "id": "curated_cham_flight_002",
                "carrier_code": "AF",
                "carrier_name": "Air France",
                "departure_time": "10:15",
                "duration": "PT2H00M",
                "price": 165,
                "currency": "EUR",
                "logic_hook": "Direct to Geneva (GVA)",
            },
            {
                "id": "curated_cham_flight_003",
                "carrier_code": "EZY",
                "carrier_name": "easyJet",
                "departure_time": "14:45",
                "duration": "PT1H50M",
                "price": 85,
                "currency": "EUR",
                "logic_hook": "Budget option - Direct to Geneva",
            },
            {
                "id": "curated_cham_flight_004",
                "carrier_code": "BA",
                "carrier_name": "British Airways",
                "departure_time": "18:20",
                "duration": "PT1H55M",
                "price": 215,
                "currency": "EUR",
                "logic_hook": "Evening flight - Direct to Geneva",
            },
        ],
        "logistics": {
            "best_skiing_months": ["December", "January", "February", "March"],
            "nearest_airport": "Geneva (GVA) - 1h15 transfer",
            "altitude": "1035m (town), 3842m (Aiguille du Midi)",
        },
    },
}


# =============================================================================
# Helper Functions
# =============================================================================


def get_curated_content(
    destination: str,
    specialist_type: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get curated content for a destination.

    Args:
        destination: City name (case-insensitive)
        specialist_type: Optional specialist filter ("diving", "skiing", "general")

    Returns:
        Dict with curated content or None if not a hero destination
    """
    dest_key = destination.lower().strip()

    if dest_key not in DEMO_MANIFEST:
        return None

    manifest = DEMO_MANIFEST[dest_key]

    # If specialist_type specified, filter activities
    if specialist_type:
        activities = manifest.get("specialist_content", {}).get(specialist_type, [])
        # Also include general activities
        general = manifest.get("specialist_content", {}).get("general", [])
        all_activities = activities + general
    else:
        # Return all activities
        all_activities = []
        for activities in manifest.get("specialist_content", {}).values():
            all_activities.extend(activities)

    return {
        "hero_image": manifest.get("hero_image"),
        "hero_image_alt": manifest.get("hero_image_alt"),
        "tagline": manifest.get("tagline"),
        "activities": all_activities,
        "hotels": manifest.get("curated_hotels", []),
        "use_live_flights": manifest.get("curated_flights") is None,
        "logistics": manifest.get("logistics", {}),
    }


def is_hero_destination(destination: str) -> bool:
    """Check if a destination has curated content."""
    return destination.lower().strip() in DEMO_MANIFEST


def get_hero_destinations() -> List[str]:
    """Get list of all hero destinations with curated content."""
    return list(DEMO_MANIFEST.keys())
