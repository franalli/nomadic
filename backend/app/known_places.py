"""
Known places database for confidence scoring and validation.

This module provides:
- Large sets of known cities, countries, regions for validation
- Ambiguous entity detection (Jordan = country or name?)
- Fuzzy matching for typo correction
"""

import logging
from typing import Dict, FrozenSet, Optional, Tuple

logger = logging.getLogger(__name__)

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
# PLACE SYNONYM NORMALIZATION
# =============================================================================
# Maps common abbreviations and alternate names to their canonical forms.
# This eliminates the need for LLM to handle synonym normalization.

PLACE_SYNONYMS: Dict[str, str] = {
    # US city abbreviations
    "nyc": "New York City",
    "new york city": "New York City",
    "la": "Los Angeles",
    "l.a.": "Los Angeles",
    "sf": "San Francisco",
    "s.f.": "San Francisco",
    "dc": "Washington, D.C.",
    "d.c.": "Washington, D.C.",
    "washington dc": "Washington, D.C.",
    "washington d.c.": "Washington, D.C.",
    "philly": "Philadelphia",
    "vegas": "Las Vegas",
    "nola": "New Orleans",
    "chi-town": "Chicago",
    "atl": "Atlanta",
    "bos": "Boston",
    "dtx": "Dallas",
    "dfw": "Dallas",
    # Country abbreviations
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "the uk": "United Kingdom",
    "britain": "United Kingdom",
    "great britain": "United Kingdom",
    "england": "United Kingdom",  # Often used interchangeably
    "usa": "United States",
    "u.s.a.": "United States",
    "u.s.": "United States",
    "the states": "United States",
    "america": "United States",
    "uae": "United Arab Emirates",
    "u.a.e.": "United Arab Emirates",
    "the emirates": "United Arab Emirates",
    # International city abbreviations
    "cdmx": "Mexico City",
    "df": "Mexico City",  # Distrito Federal
    "hk": "Hong Kong",
    "sg": "Singapore",
    "bkk": "Bangkok",
    "kl": "Kuala Lumpur",
    # Common alternate names
    "the big apple": "New York City",
    "city of lights": "Paris",
    "the city of light": "Paris",
    "the eternal city": "Rome",
    "the windy city": "Chicago",
    "sin city": "Las Vegas",
    "motor city": "Detroit",
    "mile high city": "Denver",
    "the crescent city": "New Orleans",
    "the bay area": "San Francisco Bay Area",
    "bay area": "San Francisco Bay Area",
    "silicon valley": "San Francisco Bay Area",
    "socal": "Southern California",
    "norcal": "Northern California",
    # European variants
    "munich": "Munich",  # vs München
    "cologne": "Cologne",  # vs Köln
    "vienna": "Vienna",  # vs Wien
    "prague": "Prague",  # vs Praha
    "warsaw": "Warsaw",  # vs Warszawa
    "moscow": "Moscow",  # vs Москва
    "rome": "Rome",  # vs Roma
    "milan": "Milan",  # vs Milano
    "florence": "Florence",  # vs Firenze
    "venice": "Venice",  # vs Venezia
    "naples": "Naples",  # vs Napoli
    "lisbon": "Lisbon",  # vs Lisboa
    "athens": "Athens",  # vs Αθήνα
    "copenhagen": "Copenhagen",  # vs København
    # Asian variants
    "beijing": "Beijing",  # vs Peking
    "peking": "Beijing",
    "bombay": "Mumbai",
    "calcutta": "Kolkata",
    "madras": "Chennai",
    "rangoon": "Yangon",
    "saigon": "Ho Chi Minh City",
    "canton": "Guangzhou",
    # Middle East
    "mecca": "Mecca",  # vs Makkah
    "makkah": "Mecca",
    # Local language city names (Italian, German, etc.)
    "roma": "Rome",
    "milano": "Milan",
    "firenze": "Florence",
    "venezia": "Venice",
    "napoli": "Naples",
    "torino": "Turin",
    "genova": "Genoa",
    "wien": "Vienna",
    "munchen": "Munich",
    "münchen": "Munich",
    "koln": "Cologne",
    "köln": "Cologne",
    "lisboa": "Lisbon",
    "athinai": "Athens",
    "athina": "Athens",
    "αθήνα": "Athens",
    "moskva": "Moscow",
    "москва": "Moscow",
    "warszawa": "Warsaw",
    "praha": "Prague",
    "kobenhavn": "Copenhagen",
    "københavn": "Copenhagen",
}

# Lowercase lookup for case-insensitive matching
_PLACE_SYNONYMS_LOWER: Dict[str, str] = {k.lower(): v for k, v in PLACE_SYNONYMS.items()}


def normalize_place_synonym(place: str) -> str:
    """
    Normalize a place name using the synonym map.

    Returns the canonical form if a synonym is found, otherwise the original.
    """
    if not place:
        return place
    lowered = place.lower().strip()
    return _PLACE_SYNONYMS_LOWER.get(lowered, place)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def is_known_place(place: str) -> bool:
    """Check if a place name is in our known places database."""
    return place.lower() in _ALL_KNOWN_PLACES_LOWER


# =============================================================================
# FUZZY MATCHING FOR TYPO CORRECTION
# =============================================================================

# Minimum input length for fuzzy matching (avoid false positives on very short strings)
_FUZZY_MIN_LENGTH = 3

# Default similarity threshold (0-100). 80% catches typos while avoiding false positives
_FUZZY_DEFAULT_THRESHOLD = 80


def fuzzy_match_place(
    place: str, threshold: int = _FUZZY_DEFAULT_THRESHOLD
) -> Tuple[Optional[str], Optional[int]]:
    """
    Find the best fuzzy match for a place name from known places.

    Uses rapidfuzz for efficient fuzzy string matching to correct typos
    like "pariss" → "Paris" or "new yrok" → "New York".

    Args:
        place: The place name to match (possibly with typos)
        threshold: Minimum similarity score (0-100) to accept a match.
                   Default is 80, which catches most typos while avoiding
                   false positives (e.g., "Paris" vs "Parma").

    Returns:
        Tuple of (matched_place, similarity_score) if a match is found above threshold,
        otherwise (None, None).
    """
    if not place or len(place.strip()) < _FUZZY_MIN_LENGTH:
        return None, None

    place_lower = place.lower().strip()

    # First check synonym map (preferred - maps local names to English)
    if place_lower in _PLACE_SYNONYMS_LOWER:
        return _PLACE_SYNONYMS_LOWER[place_lower], 100

    # Then check exact match in known places
    if place_lower in _ALL_KNOWN_PLACES_LOWER:
        canonical = _CANONICAL_PLACES.get(place_lower, place)
        return canonical, 100

    try:
        from rapidfuzz import fuzz, process

        # Search against lowercase place names for case-insensitive matching
        # Using the lowercase set for matching, then map back to canonical form
        #
        # IMPORTANT: Get top 5 matches and prefer longer ones when scores are equal.
        # This prevents "torun poland" from matching "la" (from "po-la-nd") instead
        # of "poland" when both have the same score.
        results = process.extract(
            place_lower,
            list(_ALL_KNOWN_PLACES_LOWER),
            scorer=fuzz.WRatio,
            score_cutoff=threshold,
            limit=5,
        )

        if results:
            # Sort by score DESC, then by length DESC (prefer longer matches)
            # This ensures "poland" beats "la" when both have score 90
            sorted_results = sorted(
                results,
                key=lambda x: (-x[1], -len(x[0])),  # -score, -length
            )
            matched_lower, score, _ = sorted_results[0]
            # Map back to canonical form (proper casing)
            canonical = _CANONICAL_PLACES.get(matched_lower, matched_lower.title())
            logger.debug(f"[FUZZY_MATCH] '{place}' → '{canonical}' (score={score:.1f})")
            return canonical, int(score)

        return None, None

    except ImportError:
        logger.warning("rapidfuzz not installed, fuzzy matching disabled")
        return None, None


def normalize_place_with_fuzzy(place: str, fuzzy_threshold: int = _FUZZY_DEFAULT_THRESHOLD) -> str:
    """
    Normalize a place name using synonym map first, then fuzzy matching.

    This is the recommended function for place normalization as it:
    1. First tries exact synonym lookup (fast, deterministic)
    2. Falls back to fuzzy matching for typo correction
    3. Applies title case as final fallback

    Args:
        place: The place name to normalize
        fuzzy_threshold: Minimum similarity for fuzzy match (default 85)

    Returns:
        Normalized place name (canonical form, or title-cased original if no match)
    """
    if not place:
        return place

    place_stripped = place.strip()
    if not place_stripped:
        return place

    # Step 1: Try synonym map (exact match, case-insensitive)
    lowered = place_stripped.lower()
    if lowered in _PLACE_SYNONYMS_LOWER:
        result = _PLACE_SYNONYMS_LOWER[lowered]
        logger.debug(f"[PLACE_NORMALIZE] synonym: '{place}' → '{result}'")
        return result

    # Step 2: Try canonical lookup (exact match, case-insensitive)
    if lowered in _CANONICAL_PLACES:
        result = _CANONICAL_PLACES[lowered]
        logger.debug(f"[PLACE_NORMALIZE] canonical: '{place}' → '{result}'")
        return result

    # Step 3: Try fuzzy matching for typos
    fuzzy_result, score = fuzzy_match_place(place_stripped, fuzzy_threshold)
    if fuzzy_result:
        logger.debug(f"[PLACE_NORMALIZE] fuzzy: '{place}' → '{fuzzy_result}' (score={score})")
        return fuzzy_result

    # Step 4: Fallback - apply title case for proper capitalization
    result = place_stripped.title()
    if result != place:
        logger.debug(f"[PLACE_NORMALIZE] title_case: '{place}' → '{result}'")
    return result


# =============================================================================
# CITY/COUNTRY EXTRACTION
# =============================================================================
# Pre-compute lowercase country set for O(1) lookup
_KNOWN_COUNTRIES_LOWER: frozenset = frozenset(c.lower() for c in KNOWN_COUNTRIES)


def extract_city_from_location(text: str) -> str:
    """
    Extract city from "city country" patterns like "Torun Poland".

    When users say "based in Torun Poland" or "from New York USA", they mean
    the city, not the country. This function detects such patterns and extracts
    just the city part.

    Handles patterns like:
    - "Torun Poland" -> "Torun"
    - "New York USA" -> "New York"
    - "Paris France" -> "Paris"
    - "London UK" -> "London"
    - "San Francisco United States" -> "San Francisco"
    - "New York United States of America" -> "New York"
    - "Los Angeles" -> "Los Angeles" (no change, no country detected)

    Args:
        text: Location text that may contain "city country" pattern

    Returns:
        - Just the city if pattern detected and suffix is a known country
        - Original text if no country suffix detected
    """
    if not text or " " not in text:
        return text

    words = text.split()
    if len(words) < 2:
        return text

    # Find all possible country suffixes and pick the LONGEST match
    # This ensures "United States of America" is matched over "America"
    best_match = None
    best_city = None

    for i in range(1, len(words)):
        potential_country = " ".join(words[i:])
        potential_city = " ".join(words[:i])

        if potential_country.lower() in _KNOWN_COUNTRIES_LOWER:
            # Found a match - keep looking for longer ones
            if best_match is None or len(potential_country) > len(best_match):
                best_match = potential_country
                best_city = potential_city

    if best_city is not None:
        logger.debug(
            f"[CITY_EXTRACT] '{text}' → city='{best_city}' (stripped country='{best_match}')"
        )
        return best_city

    return text
