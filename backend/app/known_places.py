"""
Known places database for confidence scoring and validation.

This module provides:
- Large sets of known cities, countries, regions for validation
- Ambiguous entity detection (Jordan = country or name?)
- Fuzzy matching for typo correction
- Language detection helpers
"""

from functools import lru_cache
from typing import Dict, FrozenSet, List, Optional, Tuple

# Try to import fuzzy matching library
try:
    from rapidfuzz import fuzz, process

    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False

# Try to import language detection
try:
    from langdetect import LangDetectException, detect_langs

    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False


# =============================================================================
# KNOWN PLACES DATABASE
# =============================================================================

# Major world cities (500+)
KNOWN_CITIES: FrozenSet[str] = frozenset(
    {
        # North America
        "New York",
        "NYC",
        "Los Angeles",
        "LA",
        "Chicago",
        "Houston",
        "Phoenix",
        "Philadelphia",
        "San Antonio",
        "San Diego",
        "Dallas",
        "San Jose",
        "Austin",
        "Jacksonville",
        "Fort Worth",
        "Columbus",
        "Charlotte",
        "San Francisco",
        "SF",
        "Indianapolis",
        "Seattle",
        "Denver",
        "Washington",
        "Washington DC",
        "DC",
        "Boston",
        "El Paso",
        "Nashville",
        "Detroit",
        "Oklahoma City",
        "Portland",
        "Las Vegas",
        "Vegas",
        "Memphis",
        "Louisville",
        "Baltimore",
        "Milwaukee",
        "Albuquerque",
        "Tucson",
        "Fresno",
        "Sacramento",
        "Mesa",
        "Kansas City",
        "Atlanta",
        "Miami",
        "Oakland",
        "Minneapolis",
        "Tulsa",
        "Cleveland",
        "Wichita",
        "Arlington",
        "New Orleans",
        "Bakersfield",
        "Tampa",
        "Honolulu",
        "Aurora",
        "Anaheim",
        "Santa Ana",
        "St. Louis",
        "Riverside",
        "Corpus Christi",
        "Lexington",
        "Pittsburgh",
        "Anchorage",
        "Stockton",
        "Cincinnati",
        "St. Paul",
        "Toledo",
        "Greensboro",
        "Newark",
        "Plano",
        "Henderson",
        "Lincoln",
        "Buffalo",
        "Jersey City",
        "Chula Vista",
        "Fort Wayne",
        "Orlando",
        "Salt Lake City",
        "SLC",
        # Canada
        "Toronto",
        "Montreal",
        "Vancouver",
        "Calgary",
        "Edmonton",
        "Ottawa",
        "Winnipeg",
        "Quebec City",
        "Hamilton",
        "Victoria",
        # Mexico
        "Mexico City",
        "Guadalajara",
        "Monterrey",
        "Cancun",
        "Tijuana",
        "Puebla",
        "Playa del Carmen",
        "Cabo San Lucas",
        "Puerto Vallarta",
        "Oaxaca",
        # Central/South America
        "Sao Paulo",
        "São Paulo",
        "Rio de Janeiro",
        "Rio",
        "Buenos Aires",
        "Lima",
        "Bogota",
        "Bogotá",
        "Santiago",
        "Caracas",
        "Quito",
        "La Paz",
        "Montevideo",
        "Asuncion",
        "Asunción",
        "Medellin",
        "Medellín",
        "Cartagena",
        "Cusco",
        "Havana",
        "San Juan",
        "Panama City",
        "Guatemala City",
        "Managua",
        "Tegucigalpa",
        "San Salvador",
        # Europe - UK/Ireland
        "London",
        "Manchester",
        "Birmingham",
        "Liverpool",
        "Leeds",
        "Glasgow",
        "Edinburgh",
        "Bristol",
        "Cardiff",
        "Belfast",
        "Dublin",
        "Cork",
        "Galway",
        # Europe - France
        "Paris",
        "Marseille",
        "Lyon",
        "Toulouse",
        "Nice",
        "Nantes",
        "Strasbourg",
        "Montpellier",
        "Bordeaux",
        "Lille",
        "Rennes",
        "Cannes",
        "Monaco",
        # Europe - Germany
        "Berlin",
        "Hamburg",
        "Munich",
        "München",
        "Cologne",
        "Köln",
        "Frankfurt",
        "Stuttgart",
        "Dusseldorf",
        "Düsseldorf",
        "Leipzig",
        "Dortmund",
        "Essen",
        "Bremen",
        "Dresden",
        "Hanover",
        "Nuremberg",
        "Nürnberg",
        # Europe - Italy
        "Rome",
        "Roma",
        "Milan",
        "Milano",
        "Naples",
        "Napoli",
        "Turin",
        "Torino",
        "Palermo",
        "Genoa",
        "Genova",
        "Bologna",
        "Florence",
        "Firenze",
        "Venice",
        "Venezia",
        "Verona",
        "Catania",
        "Bari",
        "Messina",
        "Padua",
        "Trieste",
        # Europe - Spain
        "Madrid",
        "Barcelona",
        "Valencia",
        "Seville",
        "Sevilla",
        "Zaragoza",
        "Malaga",
        "Málaga",
        "Murcia",
        "Palma",
        "Las Palmas",
        "Bilbao",
        "Alicante",
        "Cordoba",
        "Córdoba",
        "Granada",
        "San Sebastian",
        # Europe - Portugal
        "Lisbon",
        "Porto",
        "Braga",
        "Coimbra",
        "Funchal",
        "Faro",
        # Europe - Netherlands
        "Amsterdam",
        "Rotterdam",
        "The Hague",
        "Utrecht",
        "Eindhoven",
        "Tilburg",
        # Europe - Belgium
        "Brussels",
        "Antwerp",
        "Ghent",
        "Bruges",
        "Liege",
        "Leuven",
        # Europe - Switzerland
        "Zurich",
        "Zürich",
        "Geneva",
        "Genève",
        "Basel",
        "Bern",
        "Lausanne",
        "Lucerne",
        "Luzern",
        "Interlaken",
        "Zermatt",
        "St. Moritz",
        # Europe - Austria
        "Vienna",
        "Wien",
        "Salzburg",
        "Innsbruck",
        "Graz",
        "Linz",
        # Europe - Scandinavia
        "Copenhagen",
        "København",
        "Stockholm",
        "Oslo",
        "Helsinki",
        "Gothenburg",
        "Malmö",
        "Bergen",
        "Reykjavik",
        "Reykjavík",
        # Europe - Eastern
        "Prague",
        "Praha",
        "Budapest",
        "Warsaw",
        "Warszawa",
        "Krakow",
        "Kraków",
        "Bucharest",
        "București",
        "Sofia",
        "Belgrade",
        "Beograd",
        "Zagreb",
        "Ljubljana",
        "Bratislava",
        "Tallinn",
        "Riga",
        "Vilnius",
        "Kyiv",
        "Kiev",
        "Lviv",
        "Odessa",
        "Minsk",
        "Chisinau",
        # Europe - Greece/Turkey
        "Athens",
        "Athina",
        "Thessaloniki",
        "Santorini",
        "Mykonos",
        "Rhodes",
        "Crete",
        "Heraklion",
        "Corfu",
        "Istanbul",
        "Ankara",
        "Izmir",
        "Antalya",
        "Bodrum",
        "Cappadocia",
        # Middle East
        "Dubai",
        "Abu Dhabi",
        "Doha",
        "Riyadh",
        "Jeddah",
        "Kuwait City",
        "Manama",
        "Muscat",
        "Amman",
        "Beirut",
        "Tel Aviv",
        "Jerusalem",
        "Haifa",
        "Petra",
        "Dead Sea",
        # Africa
        "Cairo",
        "Alexandria",
        "Marrakech",
        "Marrakesh",
        "Casablanca",
        "Fes",
        "Tangier",
        "Cape Town",
        "Johannesburg",
        "Durban",
        "Pretoria",
        "Nairobi",
        "Mombasa",
        "Dar es Salaam",
        "Zanzibar",
        "Addis Ababa",
        "Lagos",
        "Accra",
        "Dakar",
        "Tunis",
        "Algiers",
        "Mauritius",
        # Asia - East
        "Tokyo",
        "Osaka",
        "Kyoto",
        "Yokohama",
        "Nagoya",
        "Sapporo",
        "Fukuoka",
        "Kobe",
        "Hiroshima",
        "Nara",
        "Okinawa",
        "Beijing",
        "Shanghai",
        "Guangzhou",
        "Shenzhen",
        "Chengdu",
        "Hangzhou",
        "Xian",
        "Xi'an",
        "Nanjing",
        "Wuhan",
        "Chongqing",
        "Suzhou",
        "Guilin",
        "Hong Kong",
        "Macau",
        "Macao",
        "Seoul",
        "Busan",
        "Incheon",
        "Jeju",
        "Taipei",
        "Kaohsiung",
        "Taichung",
        # Asia - Southeast
        "Singapore",
        "Kuala Lumpur",
        "KL",
        "Penang",
        "Langkawi",
        "Johor Bahru",
        "Bangkok",
        "Phuket",
        "Chiang Mai",
        "Pattaya",
        "Krabi",
        "Koh Samui",
        "Ho Chi Minh City",
        "Saigon",
        "Hanoi",
        "Da Nang",
        "Hoi An",
        "Nha Trang",
        "Jakarta",
        "Bali",
        "Ubud",
        "Yogyakarta",
        "Surabaya",
        "Lombok",
        "Manila",
        "Cebu",
        "Boracay",
        "Palawan",
        "El Nido",
        "Phnom Penh",
        "Siem Reap",
        "Vientiane",
        "Luang Prabang",
        "Yangon",
        # Asia - South
        "Mumbai",
        "Bombay",
        "Delhi",
        "New Delhi",
        "Bangalore",
        "Bengaluru",
        "Chennai",
        "Madras",
        "Kolkata",
        "Calcutta",
        "Hyderabad",
        "Ahmedabad",
        "Pune",
        "Jaipur",
        "Udaipur",
        "Goa",
        "Agra",
        "Varanasi",
        "Kerala",
        "Kathmandu",
        "Pokhara",
        "Colombo",
        "Kandy",
        "Dhaka",
        "Karachi",
        "Lahore",
        "Islamabad",
        # Asia - Central
        "Tashkent",
        "Samarkand",
        "Bukhara",
        "Almaty",
        "Astana",
        "Bishkek",
        "Dushanbe",
        "Ashgabat",
        "Baku",
        "Tbilisi",
        "Yerevan",
        # Oceania
        "Sydney",
        "Melbourne",
        "Brisbane",
        "Perth",
        "Adelaide",
        "Canberra",
        "Gold Coast",
        "Cairns",
        "Darwin",
        "Hobart",
        "Auckland",
        "Wellington",
        "Christchurch",
        "Queenstown",
        "Rotorua",
        "Fiji",
        "Suva",
        "Tahiti",
        "Bora Bora",
        "Moorea",
    }
)

# Countries and territories (200+)
KNOWN_COUNTRIES: FrozenSet[str] = frozenset(
    {
        # North America
        "USA",
        "United States",
        "United States of America",
        "America",
        "US",
        "Canada",
        "Mexico",
        # Central America & Caribbean
        "Guatemala",
        "Belize",
        "Honduras",
        "El Salvador",
        "Nicaragua",
        "Costa Rica",
        "Panama",
        "Cuba",
        "Jamaica",
        "Haiti",
        "Dominican Republic",
        "Puerto Rico",
        "Bahamas",
        "Barbados",
        "Trinidad and Tobago",
        "Aruba",
        "Curacao",
        "Curaçao",
        "St. Lucia",
        "Saint Lucia",
        "Antigua",
        "Antigua and Barbuda",
        "St. Kitts",
        "Grenada",
        "St. Vincent",
        "Virgin Islands",
        "BVI",
        "USVI",
        "Cayman Islands",
        "Turks and Caicos",
        # South America
        "Brazil",
        "Argentina",
        "Colombia",
        "Peru",
        "Venezuela",
        "Chile",
        "Ecuador",
        "Bolivia",
        "Paraguay",
        "Uruguay",
        "Guyana",
        "Suriname",
        "French Guiana",
        # Europe - Western
        "UK",
        "United Kingdom",
        "Great Britain",
        "Britain",
        "England",
        "Scotland",
        "Wales",
        "Northern Ireland",
        "Ireland",
        "France",
        "Germany",
        "Italy",
        "Spain",
        "Portugal",
        "Netherlands",
        "Holland",
        "Belgium",
        "Luxembourg",
        "Switzerland",
        "Austria",
        "Liechtenstein",
        "Monaco",
        "Andorra",
        "San Marino",
        "Vatican",
        "Vatican City",
        # Europe - Northern
        "Denmark",
        "Norway",
        "Sweden",
        "Finland",
        "Iceland",
        "Greenland",
        "Faroe Islands",
        # Europe - Eastern
        "Poland",
        "Czech Republic",
        "Czechia",
        "Slovakia",
        "Hungary",
        "Romania",
        "Bulgaria",
        "Serbia",
        "Croatia",
        "Slovenia",
        "Bosnia",
        "Bosnia and Herzegovina",
        "Montenegro",
        "North Macedonia",
        "Macedonia",
        "Albania",
        "Kosovo",
        "Moldova",
        "Ukraine",
        "Belarus",
        "Russia",
        "Estonia",
        "Latvia",
        "Lithuania",
        # Europe - Southern
        "Greece",
        "Turkey",
        "Cyprus",
        "Malta",
        # Middle East
        "Israel",
        "Palestine",
        "Jordan",
        "Lebanon",
        "Syria",
        "Iraq",
        "Iran",
        "Saudi Arabia",
        "UAE",
        "United Arab Emirates",
        "Qatar",
        "Bahrain",
        "Kuwait",
        "Oman",
        "Yemen",
        # Africa - North
        "Egypt",
        "Morocco",
        "Algeria",
        "Tunisia",
        "Libya",
        # Africa - West
        "Nigeria",
        "Ghana",
        "Senegal",
        "Ivory Coast",
        "Côte d'Ivoire",
        "Mali",
        "Burkina Faso",
        "Niger",
        "Benin",
        "Togo",
        "Gambia",
        "Guinea",
        "Sierra Leone",
        "Liberia",
        "Mauritania",
        "Cape Verde",
        # Africa - East
        "Kenya",
        "Tanzania",
        "Uganda",
        "Rwanda",
        "Burundi",
        "Ethiopia",
        "Eritrea",
        "Djibouti",
        "Somalia",
        "Sudan",
        "South Sudan",
        "Seychelles",
        "Mauritius",
        "Madagascar",
        "Comoros",
        "Mayotte",
        # Africa - Central
        "DRC",
        "Democratic Republic of Congo",
        "Congo",
        "Cameroon",
        "Central African Republic",
        "Chad",
        "Gabon",
        "Equatorial Guinea",
        "Sao Tome and Principe",
        # Africa - Southern
        "South Africa",
        "Namibia",
        "Botswana",
        "Zimbabwe",
        "Zambia",
        "Malawi",
        "Mozambique",
        "Angola",
        "Lesotho",
        "Eswatini",
        "Swaziland",
        # Asia - East
        "China",
        "Japan",
        "South Korea",
        "Korea",
        "North Korea",
        "Taiwan",
        "Mongolia",
        "Hong Kong",
        "Macau",
        "Macao",
        # Asia - Southeast
        "Thailand",
        "Vietnam",
        "Malaysia",
        "Singapore",
        "Indonesia",
        "Philippines",
        "Myanmar",
        "Burma",
        "Cambodia",
        "Laos",
        "Brunei",
        "East Timor",
        "Timor-Leste",
        # Asia - South
        "India",
        "Pakistan",
        "Bangladesh",
        "Sri Lanka",
        "Nepal",
        "Bhutan",
        "Maldives",
        "Afghanistan",
        # Asia - Central
        "Kazakhstan",
        "Uzbekistan",
        "Turkmenistan",
        "Kyrgyzstan",
        "Tajikistan",
        "Azerbaijan",
        "Georgia",
        "Armenia",
        # Oceania
        "Australia",
        "New Zealand",
        "Papua New Guinea",
        "Fiji",
        "Samoa",
        "Tonga",
        "Vanuatu",
        "Solomon Islands",
        "New Caledonia",
        "French Polynesia",
        "Guam",
        "Palau",
        "Micronesia",
        "Marshall Islands",
        "Kiribati",
        "Tuvalu",
        "Nauru",
        "Cook Islands",
    }
)

# Regions, landmarks, and non-standard destinations
KNOWN_REGIONS: FrozenSet[str] = frozenset(
    {
        # Famous regions
        "Patagonia",
        "Tuscany",
        "Provence",
        "Burgundy",
        "Champagne",
        "Alsace",
        "Normandy",
        "Brittany",
        "Loire Valley",
        "French Riviera",
        "Côte d'Azur",
        "Amalfi Coast",
        "Cinque Terre",
        "Dolomites",
        "Italian Riviera",
        "Costa Brava",
        "Costa del Sol",
        "Andalusia",
        "Andalucía",
        "Basque Country",
        "Galicia",
        "Catalonia",
        "Balearic Islands",
        "Canary Islands",
        "Algarve",
        "Douro Valley",
        "Madeira",
        "Azores",
        "Scottish Highlands",
        "Lake District",
        "Cotswolds",
        "Cornwall",
        "Black Forest",
        "Bavarian Alps",
        "Rhine Valley",
        "Romantic Road",
        "Swiss Alps",
        "Austrian Alps",
        "Tyrol",
        "Salzburgerland",
        "Dalmatian Coast",
        "Istria",
        "Transylvania",
        "Norwegian Fjords",
        "Lapland",
        "Finnish Lakeland",
        # Americas regions
        "Caribbean",
        "West Indies",
        "Central America",
        "South America",
        "Yucatan",
        "Yucatán",
        "Riviera Maya",
        "Baja California",
        "Copper Canyon",
        "Amazon",
        "Amazon Rainforest",
        "Galapagos",
        "Galápagos",
        "Machu Picchu",
        "Sacred Valley",
        "Inca Trail",
        "Atacama",
        "Atacama Desert",
        "Torres del Paine",
        "Iguazu",
        "Iguaçu",
        "Iguazu Falls",
        "Pantanal",
        "Fernando de Noronha",
        "Northeast Brazil",
        "Pacific Coast Highway",
        "Route 66",
        "Grand Canyon",
        "Yellowstone",
        "Yosemite",
        "Death Valley",
        "Joshua Tree",
        "Monument Valley",
        "Napa Valley",
        "Sonoma",
        "Big Sur",
        "Pacific Northwest",
        "New England",
        "Florida Keys",
        "Everglades",
        "Outer Banks",
        "Great Smoky Mountains",
        "Blue Ridge Parkway",
        "Appalachian Trail",
        "Rocky Mountains",
        "Rockies",
        "Alaska Inside Passage",
        "Denali",
        "Hawaii",
        "Hawaiian Islands",
        "Niagara Falls",
        "Canadian Rockies",
        "Banff",
        "Jasper",
        "Whistler",
        "Vancouver Island",
        "Bay of Fundy",
        "Prince Edward Island",
        "Maritimes",
        # Asia regions
        "Southeast Asia",
        "Indochina",
        "Mekong Delta",
        "Halong Bay",
        "Ha Long Bay",
        "Sapa",
        "Golden Triangle",
        "Northern Thailand",
        "Southern Thailand",
        "Thai Islands",
        "Borneo",
        "Raja Ampat",
        "Komodo",
        "Gili Islands",
        "Great Wall",
        "Silk Road",
        "Tibet",
        "Yunnan",
        "Zhangjiajie",
        "Hokkaido",
        "Mount Fuji",
        "Japanese Alps",
        "Okinawa Islands",
        "Korean DMZ",
        "Jeju Island",
        "Himalayas",
        "Kashmir",
        "Ladakh",
        "Rajasthan",
        "Kerala Backwaters",
        "Goa",
        "Andaman Islands",
        "Angkor",
        "Angkor Wat",
        "Temples of Angkor",
        # Middle East/Africa regions
        "Holy Land",
        "Petra",
        "Wadi Rum",
        "Dead Sea",
        "Red Sea",
        "Nile",
        "Nile Valley",
        "Valley of the Kings",
        "Sinai",
        "Sahara",
        "Sahara Desert",
        "Atlas Mountains",
        "High Atlas",
        "Serengeti",
        "Masai Mara",
        "Maasai Mara",
        "Kruger",
        "Kruger Park",
        "Okavango",
        "Okavango Delta",
        "Victoria Falls",
        "Garden Route",
        "Cape Winelands",
        "Wild Coast",
        "Skeleton Coast",
        "Namib Desert",
        "Mount Kilimanjaro",
        "Kilimanjaro",
        "Ngorongoro",
        "Ngorongoro Crater",
        # Oceania regions
        "Great Barrier Reef",
        "Whitsundays",
        "Gold Coast",
        "Sunshine Coast",
        "Outback",
        "Australian Outback",
        "Red Centre",
        "Uluru",
        "Ayers Rock",
        "Great Ocean Road",
        "Tasmania",
        "Blue Mountains",
        "Kimberley",
        "New Zealand South Island",
        "New Zealand North Island",
        "Milford Sound",
        "Fiordland",
        "Abel Tasman",
        "Bay of Islands",
        "Coromandel",
        "French Polynesia",
        "Society Islands",
        "Tuamotu",
        "Marquesas",
        # Europe - more regions
        "Alps",
        "Pyrenees",
        "Mediterranean",
        "Adriatic",
        "Aegean",
        "Baltic",
        "Scandinavian",
        "Nordic",
        "Balkans",
        "Eastern Europe",
        "Western Europe",
        # Islands and archipelagos
        "Maldives",
        "Seychelles",
        "Mauritius",
        "Reunion",
        "Réunion",
        "Zanzibar",
        "Lamu",
        "Cape Verde",
        "Canaries",
        "Balearics",
        "Mallorca",
        "Majorca",
        "Ibiza",
        "Menorca",
        "Formentera",
        "Greek Islands",
        "Cyclades",
        "Dodecanese",
        "Ionian Islands",
        "Sardinia",
        "Sicily",
        "Corsica",
        "Elba",
        "Channel Islands",
        "Jersey",
        "Guernsey",
        "Isle of Man",
        "Isle of Wight",
        "Faroe",
        "Faroe Islands",
        "Svalbard",
        "Lofoten",
        "Lofoten Islands",
        "Gotland",
        "Åland",
    }
)

# US States (for disambiguation)
US_STATES: FrozenSet[str] = frozenset(
    {
        "Alabama",
        "Alaska",
        "Arizona",
        "Arkansas",
        "California",
        "Colorado",
        "Connecticut",
        "Delaware",
        "Florida",
        "Georgia",
        "Hawaii",
        "Idaho",
        "Illinois",
        "Indiana",
        "Iowa",
        "Kansas",
        "Kentucky",
        "Louisiana",
        "Maine",
        "Maryland",
        "Massachusetts",
        "Michigan",
        "Minnesota",
        "Mississippi",
        "Missouri",
        "Montana",
        "Nebraska",
        "Nevada",
        "New Hampshire",
        "New Jersey",
        "New Mexico",
        "New York",
        "North Carolina",
        "North Dakota",
        "Ohio",
        "Oklahoma",
        "Oregon",
        "Pennsylvania",
        "Rhode Island",
        "South Carolina",
        "South Dakota",
        "Tennessee",
        "Texas",
        "Utah",
        "Vermont",
        "Virginia",
        "Washington",
        "West Virginia",
        "Wisconsin",
        "Wyoming",
        "District of Columbia",
        "DC",
    }
)

# All known places combined
ALL_KNOWN_PLACES: FrozenSet[str] = KNOWN_CITIES | KNOWN_COUNTRIES | KNOWN_REGIONS | US_STATES

# Lowercase version for case-insensitive lookups
_ALL_KNOWN_PLACES_LOWER: FrozenSet[str] = frozenset(p.lower() for p in ALL_KNOWN_PLACES)

# Mapping from lowercase to canonical form
_CANONICAL_PLACES: Dict[str, str] = {p.lower(): p for p in ALL_KNOWN_PLACES}


# =============================================================================
# AMBIGUOUS ENTITIES
# =============================================================================

# Entities that could be places OR something else (person names, brands, etc.)
AMBIGUOUS_ENTITIES: Dict[str, Dict[str, any]] = {
    # Country/Person name ambiguity
    "jordan": {
        "types": ["country", "person_name"],
        "canonical": "Jordan",
        "ambiguity_penalty": 0.25,
    },
    "chad": {"types": ["country", "person_name"], "canonical": "Chad", "ambiguity_penalty": 0.25},
    "india": {"types": ["country", "person_name"], "canonical": "India", "ambiguity_penalty": 0.15},
    "china": {"types": ["country", "person_name"], "canonical": "China", "ambiguity_penalty": 0.15},
    "kenya": {"types": ["country", "person_name"], "canonical": "Kenya", "ambiguity_penalty": 0.20},
    "israel": {
        "types": ["country", "person_name"],
        "canonical": "Israel",
        "ambiguity_penalty": 0.15,
    },
    # Country/US State ambiguity
    "georgia": {
        "types": ["country", "us_state"],
        "canonical": "Georgia",
        "ambiguity_penalty": 0.30,
    },
    "washington": {
        "types": ["city", "us_state", "person_name"],
        "canonical": "Washington",
        "ambiguity_penalty": 0.25,
    },
    "new york": {"types": ["city", "us_state"], "canonical": "New York", "ambiguity_penalty": 0.10},
    # City/Common word ambiguity
    "nice": {"types": ["city", "adjective"], "canonical": "Nice", "ambiguity_penalty": 0.35},
    "reading": {"types": ["city", "verb"], "canonical": "Reading", "ambiguity_penalty": 0.30},
    "mobile": {"types": ["city", "adjective"], "canonical": "Mobile", "ambiguity_penalty": 0.30},
    "bath": {"types": ["city", "noun"], "canonical": "Bath", "ambiguity_penalty": 0.25},
    "split": {"types": ["city", "verb"], "canonical": "Split", "ambiguity_penalty": 0.30},
    "essen": {"types": ["city", "verb_german"], "canonical": "Essen", "ambiguity_penalty": 0.20},
    "bergen": {"types": ["city", "verb_german"], "canonical": "Bergen", "ambiguity_penalty": 0.15},
    # City/Person name ambiguity
    "paris": {"types": ["city", "person_name"], "canonical": "Paris", "ambiguity_penalty": 0.10},
    "sydney": {"types": ["city", "person_name"], "canonical": "Sydney", "ambiguity_penalty": 0.15},
    "austin": {"types": ["city", "person_name"], "canonical": "Austin", "ambiguity_penalty": 0.20},
    "houston": {
        "types": ["city", "person_name"],
        "canonical": "Houston",
        "ambiguity_penalty": 0.15,
    },
    "orlando": {
        "types": ["city", "person_name"],
        "canonical": "Orlando",
        "ambiguity_penalty": 0.15,
    },
    "jackson": {
        "types": ["city", "person_name"],
        "canonical": "Jackson",
        "ambiguity_penalty": 0.25,
    },
    "madison": {
        "types": ["city", "person_name"],
        "canonical": "Madison",
        "ambiguity_penalty": 0.20,
    },
    "charlotte": {
        "types": ["city", "person_name"],
        "canonical": "Charlotte",
        "ambiguity_penalty": 0.20,
    },
    "florence": {
        "types": ["city", "person_name"],
        "canonical": "Florence",
        "ambiguity_penalty": 0.15,
    },
    "victoria": {
        "types": ["city", "person_name"],
        "canonical": "Victoria",
        "ambiguity_penalty": 0.20,
    },
    "regina": {"types": ["city", "person_name"], "canonical": "Regina", "ambiguity_penalty": 0.25},
    "adelaide": {
        "types": ["city", "person_name"],
        "canonical": "Adelaide",
        "ambiguity_penalty": 0.20,
    },
    "alexandria": {
        "types": ["city", "person_name"],
        "canonical": "Alexandria",
        "ambiguity_penalty": 0.15,
    },
    "savannah": {
        "types": ["city", "person_name"],
        "canonical": "Savannah",
        "ambiguity_penalty": 0.20,
    },
    "brooklyn": {
        "types": ["city", "person_name"],
        "canonical": "Brooklyn",
        "ambiguity_penalty": 0.15,
    },
    "dakota": {
        "types": ["region", "person_name"],
        "canonical": "Dakota",
        "ambiguity_penalty": 0.25,
    },
    "montana": {
        "types": ["us_state", "person_name"],
        "canonical": "Montana",
        "ambiguity_penalty": 0.20,
    },
    "virginia": {
        "types": ["us_state", "person_name"],
        "canonical": "Virginia",
        "ambiguity_penalty": 0.15,
    },
    "carolina": {
        "types": ["region", "person_name"],
        "canonical": "Carolina",
        "ambiguity_penalty": 0.20,
    },
    # Brand/Place ambiguity
    "amazon": {"types": ["region", "company"], "canonical": "Amazon", "ambiguity_penalty": 0.30},
    "delta": {"types": ["region", "airline"], "canonical": "Delta", "ambiguity_penalty": 0.35},
    "united": {"types": ["airline", "adjective"], "canonical": "United", "ambiguity_penalty": 0.40},
    "virgin": {"types": ["brand", "adjective"], "canonical": "Virgin", "ambiguity_penalty": 0.35},
    "american": {
        "types": ["airline", "adjective"],
        "canonical": "American",
        "ambiguity_penalty": 0.40,
    },
    "frontier": {"types": ["airline", "noun"], "canonical": "Frontier", "ambiguity_penalty": 0.35},
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def is_known_place(place: str) -> bool:
    """Check if a place name is in our known places database."""
    return place.lower() in _ALL_KNOWN_PLACES_LOWER


def get_canonical_place(place: str) -> Optional[str]:
    """Get the canonical form of a place name, or None if unknown."""
    return _CANONICAL_PLACES.get(place.lower())


def is_ambiguous_entity(entity: str) -> bool:
    """Check if an entity is known to be ambiguous."""
    return entity.lower() in AMBIGUOUS_ENTITIES


def get_ambiguity_info(entity: str) -> Optional[Dict]:
    """Get ambiguity information for an entity."""
    return AMBIGUOUS_ENTITIES.get(entity.lower())


def get_ambiguity_penalty(entity: str) -> float:
    """Get the confidence penalty for an ambiguous entity (0.0-1.0)."""
    info = AMBIGUOUS_ENTITIES.get(entity.lower())
    return info["ambiguity_penalty"] if info else 0.0


@lru_cache(maxsize=1024)
def fuzzy_match_place(query: str, threshold: int = 85) -> Optional[Tuple[str, int]]:
    """
    Find the best fuzzy match for a place name.

    Args:
        query: The place name to match
        threshold: Minimum similarity score (0-100) to consider a match

    Returns:
        Tuple of (matched_place, score) or None if no match above threshold
    """
    if not RAPIDFUZZ_AVAILABLE:
        return None

    query_lower = query.lower()

    # First check exact match
    if query_lower in _ALL_KNOWN_PLACES_LOWER:
        return (_CANONICAL_PLACES[query_lower], 100)

    # Fuzzy match against all known places
    result = process.extractOne(
        query, list(ALL_KNOWN_PLACES), scorer=fuzz.ratio, score_cutoff=threshold
    )

    if result:
        match, score, _ = result
        return (match, int(score))

    return None


def get_fuzzy_suggestions(query: str, limit: int = 3, threshold: int = 70) -> List[Tuple[str, int]]:
    """
    Get multiple fuzzy match suggestions for a place name.

    Args:
        query: The place name to match
        limit: Maximum number of suggestions
        threshold: Minimum similarity score

    Returns:
        List of (matched_place, score) tuples, sorted by score descending
    """
    if not RAPIDFUZZ_AVAILABLE:
        return []

    results = process.extract(
        query, list(ALL_KNOWN_PLACES), scorer=fuzz.ratio, limit=limit, score_cutoff=threshold
    )

    return [(match, int(score)) for match, score, _ in results]


def detect_language(text: str) -> Tuple[str, float]:
    """
    Detect the language of a text.

    Returns:
        Tuple of (language_code, confidence) e.g., ("en", 0.95)
        Returns ("en", 0.5) if detection fails or library unavailable
    """
    if not LANGDETECT_AVAILABLE:
        return ("en", 0.5)  # Assume English with low confidence

    try:
        # Get detailed language probabilities
        langs = detect_langs(text)
        if langs:
            top_lang = langs[0]
            return (top_lang.lang, top_lang.prob)
        return ("en", 0.5)
    except LangDetectException:
        return ("en", 0.5)


def is_likely_english(text: str, threshold: float = 0.7) -> Tuple[bool, str, float]:
    """
    Check if text is likely in English.

    Returns:
        Tuple of (is_english, detected_language, confidence)
    """
    lang, conf = detect_language(text)
    is_english = lang == "en" and conf >= threshold
    return (is_english, lang, conf)


# =============================================================================
# CONFIDENCE SCORING HELPERS
# =============================================================================


def calculate_place_confidence(
    place: str,
    extraction_method: str,  # "regex", "spacy", "llm"
    has_grammar_pattern: bool = False,
    context_text: str = "",
) -> float:
    """
    Calculate confidence score for a single extracted place.

    Args:
        place: The extracted place name
        extraction_method: How the place was extracted
        has_grammar_pattern: Whether a grammar pattern was matched (from/to, going to)
        context_text: The full user text for additional context

    Returns:
        Confidence score between 0.0 and 1.0
    """
    score = 0.5  # Base score

    # Extraction method bonus
    if extraction_method == "regex" and has_grammar_pattern:
        score += 0.30  # High confidence for grammar-bound regex
    elif extraction_method == "regex":
        score += 0.15  # Medium confidence for bare regex
    elif extraction_method == "spacy":
        score += 0.15  # Medium confidence for spaCy NER
    elif extraction_method == "llm":
        score += 0.25  # Higher confidence for LLM extraction

    # Known place bonus
    if is_known_place(place):
        score += 0.25
    else:
        # Try fuzzy match - this indicates a TYPO, not a match
        fuzzy = fuzzy_match_place(place, threshold=85)
        if fuzzy:
            matched, fuzzy_score = fuzzy
            # High fuzzy score but not exact = likely typo
            # Penalize proportionally to how different it is
            if matched.lower() != place.lower():
                # Typo detected - penalize and flag for confirmation
                score -= 0.15  # Typo penalty
            else:
                # Case difference only - small bonus
                score += 0.20
        elif fuzzy_match_place(place, threshold=70):
            score -= 0.25  # Moderate typo penalty
        else:
            score -= 0.15  # Unknown place penalty

    # Ambiguity penalty
    ambiguity = get_ambiguity_penalty(place)
    score -= ambiguity

    # Context bonuses (if context provided)
    if context_text:
        ctx_lower = context_text.lower()
        # Travel-related context increases confidence
        travel_words = ["trip", "travel", "visit", "fly", "going", "vacation", "holiday"]
        if any(word in ctx_lower for word in travel_words):
            score += 0.05

    # Clamp to [0.0, 1.0]
    return max(0.0, min(1.0, score))


def get_confidence_level(score: float) -> str:
    """
    Convert a confidence score to a human-readable level.

    Returns:
        "high" (≥0.80), "medium" (0.50-0.79), or "low" (<0.50)
    """
    if score >= 0.80:
        return "high"
    elif score >= 0.50:
        return "medium"
    else:
        return "low"


def needs_confirmation(score: float) -> bool:
    """Check if a confidence score requires user confirmation."""
    return score < 0.80
