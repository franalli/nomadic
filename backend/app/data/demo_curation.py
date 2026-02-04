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
    # Bali carriers
    "GA": {"name": "Garuda Indonesia", "logo": "GA"},
    "SQ": {"name": "Singapore Airlines", "logo": "SQ"},
    "QZ": {"name": "AirAsia Indonesia", "logo": "QZ"},
    "JT": {"name": "Lion Air", "logo": "JT"},
    # Patagonia carriers
    "AR": {"name": "Aerolineas Argentinas", "logo": "AR"},
    "LA": {"name": "LATAM Airlines", "logo": "LA"},
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
                    # Freediver descending into deep blue water
                    "image": "https://images.unsplash.com/photo-1682687220742-aba13b6e50ba?w=800&q=80",
                    "skill_level": "intermediate",
                    "duration_hours": 3,
                    "price_estimate": 350,
                    "currency": "USD",
                    "location": "Nad Al Sheba",
                    "coordinates": [55.3075, 25.1177],  # [lng, lat] Mapbox format
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
                    # Vibrant coral reef with tropical fish
                    "image": "https://images.unsplash.com/photo-1544551763-46a013bb70d5?w=800&q=80",
                    "skill_level": "beginner",
                    "duration_hours": 4,
                    "price_estimate": 180,
                    "currency": "USD",
                    "location": "Jumeirah Beach",
                    "coordinates": [55.1850, 25.2048],  # [lng, lat] Mapbox format
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
                    # Scuba diver exploring underwater wreck
                    "image": "https://images.unsplash.com/photo-1559827260-dc66d52bef19?w=800&q=80",
                    "skill_level": "advanced",
                    "duration_hours": 5,
                    "price_estimate": 280,
                    "currency": "USD",
                    "location": "Off Umm Al Quwain",
                    "coordinates": [55.6000, 25.5700],  # [lng, lat] Mapbox format - off UAE coast
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
                "coordinates": [55.1174, 25.1304],  # [lng, lat] Palm Jumeirah
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
                "coordinates": [55.1850, 25.2048],  # [lng, lat] Jumeirah Beach
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
                "coordinates": [55.2744, 25.1972],  # [lng, lat] Downtown Dubai
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
                "coordinates": [12.4797, 41.9092],  # [lng, lat] Via del Babuino, Rome
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
                "coordinates": [12.4963, 41.8947],  # [lng, lat] Monti district, Rome
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
                "coordinates": [12.5016, 41.9010],  # [lng, lat] Termini, Rome
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
                    # Skier carving through pristine powder with mountain backdrop
                    "image": "https://images.unsplash.com/photo-1565992441121-4367c2967103?w=800&q=80",
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
                    # Dramatic alpine skiing with fresh powder spray
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
                    # Stunning Mont Blanc panoramic mountain view
                    "image": "https://images.unsplash.com/photo-1483728642387-6c3bdd6c93e5?w=800&q=80",
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
                "coordinates": [6.8694, 45.9237],  # [lng, lat] Chamonix town center
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
                "coordinates": [6.8694, 45.9237],  # [lng, lat] Chamonix town center
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
    # =========================================================================
    # BALI - Hero Destination (Diving + Hiking Focus)
    # =========================================================================
    "bali": {
        # Hero: Iconic Bali temple on water at sunset
        "hero_image": "https://images.unsplash.com/photo-1537996194471-e657df975ab4?w=1920&q=80",
        "hero_image_alt": "Tanah Lot temple at sunset, Bali",
        "tagline": "Island of the Gods",
        # Destination Gallery - "Vibe Trio" for Local Expert card
        "destination_gallery": [
            {
                "url": "https://images.unsplash.com/photo-1555400038-63f5ba517a47?w=400&q=80",
                "alt": "Bali rice terraces with palm trees",
            },
            {
                "url": "https://images.unsplash.com/photo-1573790387438-4da905039392?w=400&q=80",
                "alt": "Traditional Balinese temple gate",
            },
            {
                "url": "https://images.unsplash.com/photo-1518548419970-58e3b4079ab2?w=400&q=80",
                "alt": "Bali beach sunset",
            },
        ],
        # Specialist Activities - Domain-specific content
        "specialist_content": {
            "diving": [
                {
                    "id": "curated_bali_dive_001",
                    "title": "USAT Liberty Wreck",
                    "description": (
                        "World-famous WWII shipwreck just 30m offshore in Tulamben. "
                        "Suitable for all certification levels with depths from 5-30m. "
                        "Shore entry makes this the perfect first dive of your trip."
                    ),
                    "type": "activity",
                    "logic_hook": "Shore entry - no boat needed, ideal for jet lag day",
                    # Shipwreck underwater with coral growth
                    "image": "https://images.unsplash.com/photo-1559827260-dc66d52bef19?w=800&q=80",
                    "skill_level": "beginner",
                    "duration_hours": 4,
                    "price_estimate": 95,
                    "currency": "USD",
                    "location": "Tulamben",
                    "coordinates": [115.5931, -8.2762],  # [lng, lat] Mapbox format
                    "highlights": [
                        "120m WWII wreck",
                        "Shore entry - no boat",
                        "5-30m depth range",
                        "Abundant coral growth",
                        "Resident school of bumphead parrotfish",
                    ],
                },
                {
                    "id": "curated_bali_dive_002",
                    "title": "Manta Point Nusa Penida",
                    "description": (
                        "Encounter majestic manta rays at this famous cleaning station. "
                        "Best visibility March-June. Moderate currents require good buoyancy."
                    ),
                    "type": "activity",
                    "logic_hook": "Book morning slot - calmer currents before noon",
                    # Manta ray gliding in blue ocean
                    "image": "https://images.unsplash.com/photo-1560275619-4662e36fa65c?w=800&q=80",
                    "skill_level": "intermediate",
                    "duration_hours": 6,
                    "price_estimate": 145,
                    "currency": "USD",
                    "location": "Nusa Penida",
                    "coordinates": [115.5271, -8.7935],  # [lng, lat] Mapbox format
                    "highlights": [
                        "Manta ray cleaning station",
                        "5-18m depth",
                        "45 min boat ride from Sanur",
                        "Best March-June",
                        "Possible bamboo shark sightings",
                    ],
                },
                {
                    "id": "curated_bali_dive_003",
                    "title": "Crystal Bay",
                    "description": (
                        "Hunt for the elusive Mola Mola (sunfish) at this world-renowned site. "
                        "Peak season July-October. Strong thermoclines possible."
                    ),
                    "type": "activity",
                    "logic_hook": "Mola season Jul-Oct - cold thermoclines (18C), bring 5mm suit",
                    # Freediver in crystal clear deep blue water
                    "image": "https://images.unsplash.com/photo-1544551763-77ef2d0cfc6c?w=800&q=80",
                    "skill_level": "advanced",
                    "duration_hours": 6,
                    "price_estimate": 165,
                    "currency": "USD",
                    "location": "Nusa Penida",
                    "coordinates": [115.4486, -8.7179],  # [lng, lat] Mapbox format
                    "highlights": [
                        "Mola Mola (sunfish) sightings",
                        "Strong currents - advanced skills needed",
                        "Cold thermoclines 18-22C",
                        "Peak season July-October",
                        "Stunning hard coral garden",
                    ],
                },
                {
                    "id": "curated_bali_dive_004",
                    "title": "Blue Lagoon Padangbai",
                    "description": (
                        "Gentle macro diving paradise with seahorses, nudibranchs, and frogfish. "
                        "Protected bay perfect for beginners and underwater photographers."
                    ),
                    "type": "activity",
                    "logic_hook": "Macro paradise - bring your camera",
                    # Vibrant coral reef teeming with colorful fish
                    "image": "https://images.unsplash.com/photo-1546026423-cc4642628d2b?w=800&q=80",
                    "skill_level": "beginner",
                    "duration_hours": 4,
                    "price_estimate": 85,
                    "currency": "USD",
                    "location": "Padangbai",
                    "coordinates": [115.5088, -8.5331],  # [lng, lat] Mapbox format
                    "highlights": [
                        "Protected bay - calm conditions",
                        "Macro paradise: nudis, seahorses, frogfish",
                        "Max depth 15m",
                        "Great for photography",
                        "Morning dives for best visibility",
                    ],
                },
            ],
            "hiking": [
                {
                    "id": "curated_bali_hike_001",
                    "title": "Mount Batur Sunrise Trek",
                    "description": (
                        "Iconic sunrise hike up Bali's active volcano. 2-hour ascent rewards "
                        "with panoramic views over Lake Batur and Mount Agung at dawn."
                    ),
                    "type": "activity",
                    "logic_hook": "2 AM pickup - summit for 6 AM sunrise, breakfast included",
                    # Dramatic volcano summit at sunrise with hikers
                    "image": "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?w=800&q=80",
                    "skill_level": "intermediate",
                    "duration_hours": 7,
                    "price_estimate": 55,
                    "currency": "USD",
                    "location": "Kintamani",
                    "coordinates": [115.3756, -8.2417],  # [lng, lat] Mapbox format
                    "highlights": [
                        "Active volcano (1717m)",
                        "Sunrise breakfast at summit",
                        "Guide required by local regulations",
                        "700m elevation gain",
                        "Views of Mt Agung & Lake Batur",
                    ],
                },
                {
                    "id": "curated_bali_hike_002",
                    "title": "Campuhan Ridge Walk",
                    "description": (
                        "Scenic ridge walk between two valleys in Ubud. Easy morning stroll "
                        "through swaying grass fields with valley views. Perfect sunrise activity."
                    ),
                    "type": "activity",
                    "logic_hook": "Start at 6 AM - avoid midday heat, magical morning light",
                    # Scenic hill path with grass fields and valley views
                    "image": "https://images.unsplash.com/photo-1501555088652-021faa106b9b?w=800&q=80",
                    "skill_level": "beginner",
                    "duration_hours": 2,
                    "price_estimate": 0,
                    "currency": "USD",
                    "location": "Ubud",
                    "coordinates": [115.2580, -8.4952],  # [lng, lat] Mapbox format
                    "highlights": [
                        "Free - no entrance fee",
                        "2km easy walk",
                        "Best at sunrise",
                        "Instagram-famous views",
                        "Starts near Ibah Luxury Villas",
                    ],
                },
                {
                    "id": "curated_bali_hike_003",
                    "title": "Tegallalang Rice Terrace Walk",
                    "description": (
                        "Explore Bali's most photogenic rice terraces carved "
                        "into the hillside. Walk through the traditional subak "
                        "irrigation system dating back centuries."
                    ),
                    "type": "activity",
                    "logic_hook": "Arrive by 8 AM to beat tour buses, wear sturdy shoes",
                    # Lush green Bali rice terraces with palm trees
                    "image": "https://images.unsplash.com/photo-1604999333679-b86d54738315?w=800&q=80",
                    "skill_level": "beginner",
                    "duration_hours": 3,
                    "price_estimate": 15,
                    "currency": "USD",
                    "location": "Tegallalang",
                    "coordinates": [115.2791, -8.4343],  # [lng, lat] Mapbox format
                    "highlights": [
                        "UNESCO-recognized subak system",
                        "Multiple photo spots",
                        "Coffee plantation nearby",
                        "20 min from Ubud",
                        "Swing experiences available",
                    ],
                },
                {
                    "id": "curated_bali_hike_004",
                    "title": "Sekumpul Waterfall Trek",
                    "description": (
                        "Bali's most majestic waterfall hidden in the northern highlands. "
                        "Steep descent through jungle rewards with a twin 80m cascade."
                    ),
                    "type": "activity",
                    "logic_hook": "Full day trip - 2.5h from Ubud, arrive before 10 AM",
                    # Majestic tropical waterfall in lush jungle setting
                    "image": "https://images.unsplash.com/photo-1494472155656-f34e81b17ddc?w=800&q=80",
                    "skill_level": "intermediate",
                    "duration_hours": 5,
                    "price_estimate": 25,
                    "currency": "USD",
                    "location": "Singaraja",
                    "coordinates": [115.1847, -8.1768],  # [lng, lat] Mapbox format
                    "highlights": [
                        "Twin 80m waterfalls",
                        "Steep jungle descent (30-45 min)",
                        "Swimming allowed at base",
                        "Local guide recommended",
                        "Bali's most beautiful waterfall",
                    ],
                },
            ],
            "general": [
                {
                    "id": "curated_bali_gen_001",
                    "title": "Tanah Lot Temple Sunset",
                    "description": (
                        "Visit Bali's most iconic sea temple perched on a rocky outcrop. "
                        "Time your visit for sunset when the temple silhouettes against "
                        "the golden sky."
                    ),
                    "type": "activity",
                    "logic_hook": "Arrive 4:30 PM for sunset - temple closes at dark",
                    "image": "https://images.unsplash.com/photo-1537996194471-e657df975ab4?w=800&q=80",
                    "duration_hours": 3,
                    "price_estimate": 10,
                    "currency": "USD",
                    "location": "Tanah Lot",
                    "coordinates": [115.0867, -8.6213],  # [lng, lat] Mapbox format
                    "highlights": [
                        "Iconic sea temple",
                        "Best at sunset",
                        "Sea snakes in rock caves",
                        "Traditional market nearby",
                    ],
                },
                {
                    "id": "curated_bali_gen_002",
                    "title": "Ubud Monkey Forest & Art Walk",
                    "description": (
                        "Explore the sacred monkey sanctuary followed by a stroll through "
                        "Ubud's art galleries and craft workshops. Perfect rest day activity."
                    ),
                    "type": "activity",
                    "logic_hook": "Morning visit - monkeys less aggressive, cooler temps",
                    "image": "https://images.unsplash.com/photo-1578469550956-0e16b69c6a3d?w=800&q=80",
                    "duration_hours": 4,
                    "price_estimate": 20,
                    "currency": "USD",
                    "location": "Ubud",
                    "coordinates": [115.2588, -8.5185],  # [lng, lat] Mapbox format
                    "highlights": [
                        "700+ Balinese long-tailed macaques",
                        "Ancient temple ruins",
                        "Ubud art galleries",
                        "Traditional craft workshops",
                    ],
                },
                {
                    "id": "curated_bali_gen_003",
                    "title": "Seminyak Beach Club Day",
                    "description": (
                        "Relax at a premium beach club with infinity pool, day beds, "
                        "and sunset cocktails. Perfect no-fly day activity after diving."
                    ),
                    "type": "activity",
                    "logic_hook": "Perfect for 24h no-fly buffer day - no altitude stress",
                    "image": "https://images.unsplash.com/photo-1540541338287-41700207dee6?w=800&q=80",
                    "duration_hours": 6,
                    "price_estimate": 75,
                    "currency": "USD",
                    "location": "Seminyak",
                    "coordinates": [115.1614, -8.6900],  # [lng, lat] Mapbox format
                    "highlights": [
                        "Infinity pool",
                        "Day bed included",
                        "Sunset cocktails",
                        "Great food menu",
                        "Perfect dive recovery day",
                    ],
                },
            ],
        },
        # Curated Hotels - Range from luxury to budget
        "curated_hotels": [
            {
                "id": "curated_bali_hotel_001",
                "name": "COMO Uma Ubud",
                "description": (
                    "Luxury hillside retreat overlooking the Tjampuhan Valley. "
                    "Award-winning COMO Shambhala spa and farm-to-table dining."
                ),
                "price_estimate": 450,
                "currency": "USD",
                "rating": 5,
                "image": "https://images.unsplash.com/photo-1582719508461-905c673771fd?w=800&q=80",
                "logic_hook": "Central Ubud - 30 min to Campuhan Ridge, 2h to Tulamben",
                "amenities": ["pool", "spa", "yoga", "restaurant", "valley_view"],
                "location": "Ubud",
                "coordinates": [115.2614, -8.5039],  # [lng, lat] Ubud
                "distance_to_dive_sites": "2h to Tulamben (USAT Liberty)",
            },
            {
                "id": "curated_bali_hotel_002",
                "name": "Alila Manggis",
                "description": (
                    "Beachfront boutique resort in East Bali. Perfect base for "
                    "Tulamben diving and Mount Batur hiking with stunning Lombok views."
                ),
                "price_estimate": 180,
                "currency": "USD",
                "rating": 4,
                "image": "https://images.unsplash.com/photo-1571896349842-33c89424de2d?w=800&q=80",
                "logic_hook": "East Bali base - 45 min to Tulamben, 1h to Mt Batur",
                "amenities": ["pool", "beach", "dive_center_nearby", "spa", "restaurant"],
                "location": "Candidasa",
                "coordinates": [115.5633, -8.5097],  # [lng, lat] Candidasa
                "distance_to_dive_sites": "45 min to Tulamben",
            },
            {
                "id": "curated_bali_hotel_003",
                "name": "Puri Bagus Lovina",
                "description": (
                    "Affordable beachfront resort in North Bali with private beach. "
                    "Close to Sekumpul Waterfall and dolphin watching tours."
                ),
                "price_estimate": 85,
                "currency": "USD",
                "rating": 3,
                "image": "https://images.unsplash.com/photo-1590490360182-c33d57733427?w=800&q=80",
                "logic_hook": "Budget pick - 40 min to Sekumpul, sunrise dolphin tours",
                "amenities": ["pool", "beach", "restaurant", "spa"],
                "location": "Lovina",
                "coordinates": [115.0269, -8.1553],  # [lng, lat] Lovina
                "distance_to_dive_sites": "1h to Tulamben",
            },
        ],
        # Curated Flights - To Ngurah Rai (DPS)
        "curated_flights": [
            {
                "id": "curated_bali_flight_001",
                "carrier_code": "GA",
                "carrier_name": "Garuda Indonesia",
                "departure_time": "08:30",
                "duration": "PT4H15M",
                "price": 380,
                "currency": "USD",
                "logic_hook": None,  # Calculated by logistics node
            },
            {
                "id": "curated_bali_flight_002",
                "carrier_code": "SQ",
                "carrier_name": "Singapore Airlines",
                "departure_time": "14:00",
                "duration": "PT5H30M",
                "price": 520,
                "currency": "USD",
                "logic_hook": None,  # Via Singapore
            },
            {
                "id": "curated_bali_flight_003",
                "carrier_code": "QR",
                "carrier_name": "Qatar Airways",
                "departure_time": "19:30",
                "duration": "PT14H00M",
                "price": 680,
                "currency": "USD",
                "logic_hook": None,  # Via Doha - premium option
            },
            {
                "id": "curated_bali_flight_004",
                "carrier_code": "QZ",
                "carrier_name": "AirAsia Indonesia",
                "departure_time": "22:15",
                "duration": "PT4H45M",
                "price": 195,
                "currency": "USD",
                "logic_hook": None,  # Budget option - late departure safe for diving
            },
        ],
        # Local logistics tips
        "logistics": {
            "best_diving_months": ["April", "May", "June", "September", "October", "November"],
            "best_hiking_months": ["April", "May", "June", "July", "August", "September"],
            "mola_season": ["July", "August", "September", "October"],
            "water_temp_range": "26-30C (18-22C at Crystal Bay thermoclines)",
            "visibility_range": "15-40m",
            "timezone": "WITA (UTC+8)",
            "currency": "IDR",
            "tipping": "10% service charge usually included, small tips appreciated",
            "dive_constraints": {
                "24h_no_fly": True,
                "altitude_after_diving": "Avoid Mt Batur (1717m) within 24h of diving",
            },
            "hiking_constraints": {
                "mt_batur_altitude": "1717m - no acclimatization needed for healthy adults",
                "guide_required": "Mt Batur requires licensed guide (local regulation)",
            },
            "airport": "Ngurah Rai International (DPS)",
            "transfer_times": {
                "airport_to_ubud": "1h 30min",
                "airport_to_seminyak": "30min",
                "ubud_to_tulamben": "2h",
                "ubud_to_kintamani": "1h",
            },
        },
    },
    # =========================================================================
    # PATAGONIA - Hero Destination (Hiking Focus)
    # =========================================================================
    "patagonia": {
        # Hero: Torres del Paine peaks
        "hero_image": "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?w=1920&q=80",
        "hero_image_alt": "Torres del Paine granite peaks at sunrise",
        "tagline": "The End of the World",
        # Destination Gallery - "Vibe Trio" for Local Expert card
        "destination_gallery": [
            {
                "url": "https://images.unsplash.com/photo-1519681393784-d120267933ba?w=400&q=80",
                "alt": "Fitz Roy mountain at dawn",
            },
            {
                "url": "https://images.unsplash.com/photo-1503614472-8c93d56e92ce?w=400&q=80",
                "alt": "Perito Moreno Glacier",
            },
            {
                "url": "https://images.unsplash.com/photo-1551632811-561732d1e306?w=400&q=80",
                "alt": "Guanacos in Patagonian steppe",
            },
        ],
        # Specialist Activities - Hiking focus
        "specialist_content": {
            "hiking": [
                {
                    "id": "curated_pata_hike_001",
                    "title": "Torres del Paine W Trek",
                    "description": (
                        "The iconic W Trek covers 80km through Patagonia's most dramatic scenery. "
                        "Visit the three Torres, French Valley, and Grey Glacier over 4-5 days."
                    ),
                    "type": "activity",
                    "logic_hook": "Book refugios 4-6 months ahead - sells out fast",
                    # Dramatic Torres del Paine granite peaks at sunrise
                    "image": "https://images.unsplash.com/photo-1531366936337-7c912a4589a7?w=800&q=80",
                    "skill_level": "advanced",
                    "duration_hours": 96,  # 4 days
                    "price_estimate": 450,
                    "currency": "USD",
                    "location": "Torres del Paine National Park",
                    "coordinates": [-72.9667, -50.9423],  # [lng, lat] Mapbox format
                    "highlights": [
                        "80km over 4-5 days",
                        "Refugio or camping",
                        "Base of the Torres viewpoint",
                        "French Valley panoramas",
                        "Grey Glacier crossing",
                    ],
                },
                {
                    "id": "curated_pata_hike_002",
                    "title": "Laguna de los Tres (Fitz Roy)",
                    "description": (
                        "Classic day hike to the iconic viewpoint of Mount Fitz Roy. "
                        "10-hour round trip with 1000m elevation gain. Sunrise recommended."
                    ),
                    "type": "activity",
                    "logic_hook": "Start at 4 AM for sunrise at the lagoon - worth it",
                    # Iconic Fitz Roy peak reflected in alpine lagoon
                    "image": "https://images.unsplash.com/photo-1508739773434-c26b3d09e071?w=800&q=80",
                    "skill_level": "intermediate",
                    "duration_hours": 10,
                    "price_estimate": 0,
                    "currency": "USD",
                    "location": "El Chalten",
                    "coordinates": [-72.8867, -49.3314],  # [lng, lat] Mapbox format
                    "highlights": [
                        "Free - no entrance fee",
                        "25km round trip",
                        "1000m elevation gain",
                        "Iconic Fitz Roy view",
                        "Best at sunrise",
                    ],
                },
                {
                    "id": "curated_pata_hike_003",
                    "title": "Perito Moreno Glacier Trek",
                    "description": (
                        "Walk on one of the world's last advancing glaciers. "
                        "Includes crampons, ice trekking, and whiskey with glacier ice."
                    ),
                    "type": "activity",
                    "logic_hook": "Big Ice (4h on glacier) vs Mini Trekking (1h) - book ahead",
                    # Massive blue glacier ice formations with trekkers
                    "image": "https://images.unsplash.com/photo-1484910292437-025e5d13ce87?w=800&q=80",
                    "skill_level": "intermediate",
                    "duration_hours": 8,
                    "price_estimate": 180,
                    "currency": "USD",
                    "location": "Los Glaciares National Park",
                    "coordinates": [-73.0486, -50.4967],  # [lng, lat] Mapbox format
                    "highlights": [
                        "Walk ON the glacier",
                        "Crampons provided",
                        "Whiskey with glacier ice",
                        "One of few advancing glaciers",
                        "Spectacular ice formations",
                    ],
                },
                {
                    "id": "curated_pata_hike_004",
                    "title": "Cerro Torre Viewpoint",
                    "description": (
                        "Half-day hike to Laguna Torre with views of the impossible needle "
                        "of Cerro Torre. Easier than Fitz Roy, equally dramatic."
                    ),
                    "type": "activity",
                    "logic_hook": "Afternoon hike OK - less crowded than Fitz Roy trail",
                    # Dramatic mountain needle reflected in glacial lagoon
                    "image": "https://images.unsplash.com/photo-1527631746610-bca00a040d60?w=800&q=80",
                    "skill_level": "beginner",
                    "duration_hours": 6,
                    "price_estimate": 0,
                    "currency": "USD",
                    "location": "El Chalten",
                    "coordinates": [-72.9500, -49.3200],  # [lng, lat] Mapbox format
                    "highlights": [
                        "Free - no entrance fee",
                        "18km round trip",
                        "400m elevation gain",
                        "Cerro Torre needle views",
                        "Laguna Torre reflection",
                    ],
                },
            ],
            "general": [
                {
                    "id": "curated_pata_gen_001",
                    "title": "Perito Moreno Walkways",
                    "description": (
                        "Extensive boardwalk system facing the glacier with multiple viewpoints. "
                        "Watch and hear ice calving into Lago Argentino."
                    ),
                    "type": "activity",
                    "logic_hook": "Afternoon best for calving - ice warms and breaks more",
                    "image": "https://images.unsplash.com/photo-1503614472-8c93d56e92ce?w=800&q=80",
                    "duration_hours": 4,
                    "price_estimate": 35,
                    "currency": "USD",
                    "location": "Los Glaciares National Park",
                    "coordinates": [-73.0486, -50.4967],  # [lng, lat] Mapbox format
                    "highlights": [
                        "Multiple viewpoint levels",
                        "Watch ice calving live",
                        "Thunderous crack sounds",
                        "Cafe and facilities on site",
                    ],
                },
                {
                    "id": "curated_pata_gen_002",
                    "title": "Estancia Day Visit",
                    "description": (
                        "Experience traditional Patagonian ranch life. Includes horseback riding, "
                        "sheep shearing demo, and asado (BBQ) lunch."
                    ),
                    "type": "activity",
                    "logic_hook": "Book for rest day between big hikes - perfect recovery",
                    "image": "https://images.unsplash.com/photo-1548199973-03cce0bbc87b?w=800&q=80",
                    "duration_hours": 6,
                    "price_estimate": 120,
                    "currency": "USD",
                    "location": "El Calafate",
                    "coordinates": [-72.2761, -50.3378],  # [lng, lat] Mapbox format
                    "highlights": [
                        "Traditional asado lunch",
                        "Horseback riding included",
                        "Sheep shearing demo",
                        "Gaucho culture experience",
                    ],
                },
                {
                    "id": "curated_pata_gen_003",
                    "title": "Lago Argentino Boat Tour",
                    "description": (
                        "Cruise among icebergs to the Upsala and Spegazzini glaciers. "
                        "Full day on the water with lunch included."
                    ),
                    "type": "activity",
                    "logic_hook": "All-weather activity - boat runs rain or shine",
                    "image": "https://images.unsplash.com/photo-1501785888041-af3ef285b470?w=800&q=80",
                    "duration_hours": 8,
                    "price_estimate": 150,
                    "currency": "USD",
                    "location": "El Calafate",
                    "coordinates": [-72.8000, -50.3300],  # [lng, lat] Mapbox format
                    "highlights": [
                        "Multiple glaciers",
                        "Floating icebergs",
                        "Lunch included",
                        "Weather-proof activity",
                    ],
                },
            ],
        },
        # Curated Hotels - Range from luxury to budget
        "curated_hotels": [
            {
                "id": "curated_pata_hotel_001",
                "name": "Explora Patagonia",
                "description": (
                    "All-inclusive luxury lodge in Torres del Paine with guided expeditions. "
                    "Floor-to-ceiling windows frame the Paine massif."
                ),
                "price_estimate": 1200,
                "currency": "USD",
                "rating": 5,
                "image": "https://images.unsplash.com/photo-1566073771259-6a8506099945?w=800&q=80",
                "logic_hook": "All-inclusive with expert guides - worth the splurge",
                "amenities": ["spa", "restaurant", "guided_hikes", "horseback", "bar"],
                "location": "Torres del Paine",
                "coordinates": [-72.9667, -50.9423],  # [lng, lat]
                "distance_to_trailheads": "On-site access to park trails",
            },
            {
                "id": "curated_pata_hotel_002",
                "name": "Hosteria Helsingfors",
                "description": (
                    "Historic estancia on Lago Viedma with Fitz Roy views. "
                    "Authentic Patagonian hospitality with modern comforts."
                ),
                "price_estimate": 280,
                "currency": "USD",
                "rating": 4,
                "image": "https://images.unsplash.com/photo-1520250497591-112f2f40a3f4?w=800&q=80",
                "logic_hook": "Between El Chalten and El Calafate - strategic location",
                "amenities": ["restaurant", "bar", "lake_view", "horseback"],
                "location": "Lago Viedma",
                "coordinates": [-72.6000, -49.6000],  # [lng, lat]
                "distance_to_trailheads": "1h to El Chalten trailheads",
            },
            {
                "id": "curated_pata_hotel_003",
                "name": "America del Sur Hostel",
                "description": (
                    "Popular backpacker hostel in El Calafate with private rooms available. "
                    "Great common areas and kitchen. Walking distance to town center."
                ),
                "price_estimate": 45,
                "currency": "USD",
                "rating": 3,
                "image": "https://images.unsplash.com/photo-1590490360182-c33d57733427?w=800&q=80",
                "logic_hook": "Budget pick - best hostel in El Calafate, book private room",
                "amenities": ["kitchen", "common_room", "wifi", "luggage_storage"],
                "location": "El Calafate",
                "coordinates": [-72.2761, -50.3378],  # [lng, lat]
                "distance_to_trailheads": "1.5h to Perito Moreno",
            },
        ],
        # Curated Flights - To El Calafate (FTE)
        "curated_flights": [
            {
                "id": "curated_pata_flight_001",
                "carrier_code": "AR",
                "carrier_name": "Aerolineas Argentinas",
                "departure_time": "06:30",
                "duration": "PT3H15M",
                "price": 320,
                "currency": "USD",
                "logic_hook": "Direct from Buenos Aires (AEP) - morning arrival",
            },
            {
                "id": "curated_pata_flight_002",
                "carrier_code": "AR",
                "carrier_name": "Aerolineas Argentinas",
                "departure_time": "14:00",
                "duration": "PT3H15M",
                "price": 350,
                "currency": "USD",
                "logic_hook": "Afternoon flight - arrive for sunset at El Calafate",
            },
            {
                "id": "curated_pata_flight_003",
                "carrier_code": "LA",
                "carrier_name": "LATAM Airlines",
                "departure_time": "09:45",
                "duration": "PT3H30M",
                "price": 380,
                "currency": "USD",
                "logic_hook": "Via Santiago option available",
            },
        ],
        # Local logistics tips
        "logistics": {
            "best_hiking_months": [
                "October",
                "November",
                "December",
                "January",
                "February",
                "March",
            ],
            "weather_warning": "Patagonian weather is extreme and unpredictable - pack layers",
            "wind_season": "September-March brings strong winds (up to 120km/h)",
            "timezone": "ART (UTC-3)",
            "currency": "ARS (US dollars widely accepted)",
            "tipping": "10% at restaurants, round up for guides",
            "hiking_constraints": {
                "max_altitude": "1200m - no acclimatization needed",
                "wind_factor": "High winds can close trails - check daily",
                "permit_required": "W Trek requires advance refugio/camping booking",
            },
            "airport": "El Calafate International (FTE)",
            "transfer_times": {
                "airport_to_el_calafate": "20min",
                "el_calafate_to_perito_moreno": "1h 30min",
                "el_calafate_to_el_chalten": "3h",
                "el_calafate_to_torres_del_paine": "5h (cross border to Chile)",
            },
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
