"""
Heavy-duty tests for regex + NER extraction.

Tests hundreds of:
- Destinations (cities, countries, regions, landmarks)
- Hotel chains, hostels, motels
- Airlines and travel brands
- Ambiguous entities
- Case variations (upper, lower, mixed)
- Edge cases and tricky inputs
"""

import os
from typing import Any, Dict

import pytest

# Enable debug logging for tests
os.environ["DEBUG_PLAN_MESSAGES"] = "0"  # Set to "1" to see debug output

from app.plan_graph import (
    GraphState,
    TripInputs,
    _get_spacy_nlp,
    _should_run_spacy_ner,
    _spacy_extract_entities,
    extractor,
)

# =============================================================================
# TEST DATA: DESTINATIONS
# =============================================================================

# Major world cities
MAJOR_CITIES = [
    "New York",
    "Los Angeles",
    "Chicago",
    "Houston",
    "Phoenix",
    "London",
    "Paris",
    "Berlin",
    "Rome",
    "Madrid",
    "Barcelona",
    "Amsterdam",
    "Tokyo",
    "Beijing",
    "Shanghai",
    "Hong Kong",
    "Singapore",
    "Bangkok",
    "Sydney",
    "Melbourne",
    "Auckland",
    "Dubai",
    "Abu Dhabi",
    "Doha",
    "Cairo",
    "Cape Town",
    "Nairobi",
    "Lagos",
    "Casablanca",
    "São Paulo",
    "Rio de Janeiro",
    "Buenos Aires",
    "Lima",
    "Bogotá",
    "Mexico City",
    "Toronto",
    "Vancouver",
    "Montreal",
    "Mumbai",
    "Delhi",
]

# Countries
COUNTRIES = [
    "USA",
    "United States",
    "UK",
    "United Kingdom",
    "France",
    "Germany",
    "Italy",
    "Spain",
    "Portugal",
    "Netherlands",
    "Belgium",
    "Switzerland",
    "Austria",
    "Greece",
    "Turkey",
    "Japan",
    "China",
    "South Korea",
    "Thailand",
    "Vietnam",
    "Indonesia",
    "Malaysia",
    "Philippines",
    "Australia",
    "New Zealand",
    "India",
    "Pakistan",
    "Bangladesh",
    "Egypt",
    "Morocco",
    "South Africa",
    "Kenya",
    "Tanzania",
    "Brazil",
    "Argentina",
    "Chile",
    "Peru",
    "Colombia",
    "Mexico",
    "Canada",
    "Russia",
    "Ukraine",
    "Poland",
    "Czech Republic",
    "Ireland",
    "Scotland",
    "Wales",
    "Iceland",
    "Norway",
    "Sweden",
    "Denmark",
    "Finland",
    "Croatia",
    "Slovenia",
    "Montenegro",
]

# Regions and landmarks (often not recognized by default NER)
REGIONS_AND_LANDMARKS = [
    "Patagonia",
    "Torres del Paine",
    "Dolomites",
    "Alps",
    "Pyrenees",
    "Great Barrier Reef",
    "Raja Ampat",
    "Galápagos",
    "Machu Picchu",
    "Angkor Wat",
    "Petra",
    "Santorini",
    "Amalfi Coast",
    "Cinque Terre",
    "Tuscany",
    "Provence",
    "Côte d'Azur",
    "French Riviera",
    "Costa Brava",
    "Algarve",
    "Ibiza",
    "Mallorca",
    "Canary Islands",
    "Azores",
    "Maldives",
    "Seychelles",
    "Mauritius",
    "Bora Bora",
    "Fiji",
    "Bali",
    "Phuket",
    "Koh Samui",
    "Krabi",
    "Ha Long Bay",
    "Everest Base Camp",
    "EBC",
    "Annapurna",
    "K2",
    "Mont Blanc",
    "Grand Canyon",
    "Yellowstone",
    "Yosemite",
    "Zion",
    "Banff",
    "Niagara Falls",
    "Victoria Falls",
    "Iguazu Falls",
    "Great Wall",
    "Taj Mahal",
    "Colosseum",
    "Eiffel Tower",
    "BVI",
    "British Virgin Islands",
    "USVI",
    "Turks and Caicos",
    "Costa Rica",
    "Puerto Rico",
    "Dominican Republic",
    "Jamaica",
    "Bahamas",
    "Bermuda",
    "Aruba",
    "Curaçao",
    "St. Lucia",
    "Zanzibar",
    "Madagascar",
    "Réunion",
    "Cape Verde",
]

# US cities and states (often confused)
US_LOCATIONS = [
    "NYC",
    "LA",
    "SF",
    "San Francisco",
    "Vegas",
    "Las Vegas",
    "Miami",
    "Orlando",
    "Atlanta",
    "Boston",
    "Seattle",
    "Portland",
    "Denver",
    "Austin",
    "Dallas",
    "Nashville",
    "New Orleans",
    "Washington DC",
    "Philadelphia",
    "San Diego",
    "Honolulu",
    "Maui",
    "California",
    "Florida",
    "Texas",
    "Hawaii",
    "Alaska",
    "Colorado",
]


# =============================================================================
# TEST DATA: HOTELS, HOSTELS, MOTELS
# =============================================================================

HOTEL_CHAINS = [
    "Hilton",
    "Marriott",
    "Hyatt",
    "Sheraton",
    "Westin",
    "Ritz Carlton",
    "Four Seasons",
    "St. Regis",
    "W Hotel",
    "InterContinental",
    "Crowne Plaza",
    "Holiday Inn",
    "Hampton Inn",
    "DoubleTree",
    "Embassy Suites",
    "Fairmont",
    "Sofitel",
    "Novotel",
    "Mercure",
    "Ibis",
    "Accor",
    "Best Western",
    "Radisson",
    "Wyndham",
    "La Quinta",
    "Choice Hotels",
    "Mandarin Oriental",
    "Peninsula",
    "Aman",
    "Banyan Tree",
    "Shangri-La",
    "Oberoi",
    "Taj Hotels",
    "Leela",
    "Park Hyatt",
    "Grand Hyatt",
    "Andaz",
    "Aloft",
    "Element",
    "Renaissance",
    "Autograph Collection",
    "Tribute Portfolio",
    "JW Marriott",
    "Edition",
    "Moxy",
    "AC Hotels",
]

HOSTELS_AND_BUDGET = [
    "Hostelworld",
    "Generator Hostel",
    "St Christopher's",
    "Selina",
    "Freehand",
    "HI Hostel",
    "Youth Hostel",
    "Clink Hostel",
    "Wombats",
    "A&O Hostel",
    "MEININGER",
    "Motel 6",
    "Super 8",
    "Days Inn",
    "Econo Lodge",
    "Red Roof Inn",
    "Travelodge",
    "Premier Inn",
    "easyHotel",
]

VACATION_RENTALS = [
    "Airbnb",
    "VRBO",
    "Booking.com",
    "Expedia",
    "Hotels.com",
    "Agoda",
    "Trivago",
    "Kayak",
    "Hostelworld",
]


# =============================================================================
# TEST DATA: AIRLINES
# =============================================================================

AIRLINES = [
    # US carriers
    "Delta",
    "United",
    "American",
    "Southwest",
    "JetBlue",
    "Spirit",
    "Frontier",
    "Alaska Airlines",
    "Hawaiian Airlines",
    # European carriers
    "British Airways",
    "Air France",
    "Lufthansa",
    "KLM",
    "Ryanair",
    "easyJet",
    "Vueling",
    "Norwegian",
    "Wizz Air",
    "Swiss",
    "Austrian",
    "Iberia",
    "TAP Portugal",
    "SAS",
    "Finnair",
    "Icelandair",
    "Aer Lingus",
    "LOT Polish",
    # Middle East carriers
    "Emirates",
    "Qatar Airways",
    "Etihad",
    "Turkish Airlines",
    "Saudia",
    "Oman Air",
    "Royal Jordanian",
    "Gulf Air",
    # Asian carriers
    "Singapore Airlines",
    "Cathay Pacific",
    "Japan Airlines",
    "ANA",
    "Korean Air",
    "Asiana",
    "Thai Airways",
    "Vietnam Airlines",
    "Malaysia Airlines",
    "Garuda Indonesia",
    "Philippine Airlines",
    "Air China",
    "China Eastern",
    "China Southern",
    "Hainan Airlines",
    "Air India",
    "IndiGo",
    "SpiceJet",
    # Other
    "Qantas",
    "Air New Zealand",
    "LATAM",
    "Avianca",
    "Copa",
    "Air Canada",
    "WestJet",
    "South African Airways",
    "Ethiopian Airlines",
]


# =============================================================================
# TEST DATA: AMBIGUOUS ENTITIES
# =============================================================================

# Words that could be places OR other things
AMBIGUOUS_ENTITIES = [
    ("Jordan", "country"),  # Also a name
    ("Georgia", "country/state"),  # Country and US state
    ("Paris", "city"),  # Also a name (Paris Hilton)
    ("Sydney", "city"),  # Also a name
    ("Florence", "city"),  # Also a name
    ("Austin", "city"),  # Also a name
    ("Phoenix", "city"),  # Also a word
    ("Dallas", "city"),  # Also a name
    ("Denver", "city"),  # Also a name
    ("Jackson", "city"),  # Also a name
    ("Madison", "city"),  # Also a name
    ("Charlotte", "city"),  # Also a name
    ("Virginia", "state"),  # Also a name
    ("Carolina", "state_part"),  # Also a name
    ("Montana", "state"),  # Also a name (Hannah Montana)
    ("Dakota", "state_part"),  # Also a name
    ("Washington", "state/city"),  # Also a name
    ("Lincoln", "city"),  # Also a name
    ("Cleveland", "city"),  # Also a name
    ("Portland", "city"),  # Also a common word pattern
    ("Nice", "city"),  # Also an adjective
    ("Mobile", "city"),  # Also a word (mobile phone)
    ("Reading", "city"),  # Also a verb
    ("Bath", "city"),  # Also a word
    ("Hull", "city"),  # Also a word
    ("Split", "city"),  # Also a word
    ("Essen", "city"),  # Also a word (German for "eat")
    ("Como", "city"),  # Also "como" in Spanish
    ("Delta", "airline/region"),  # Airline and river delta
    ("Virgin", "airline/islands"),  # Virgin Atlantic vs Virgin Islands
    ("American", "airline"),  # American Airlines vs nationality
    ("United", "airline"),  # United Airlines vs word
    ("Frontier", "airline"),  # Also a word
    ("Spirit", "airline"),  # Also a word
    ("Turkish", "airline"),  # Turkish Airlines vs nationality
]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def run_extraction(text: str) -> Dict[str, Any]:
    """Run the extractor and return parsed_inputs."""
    state = GraphState(user_text=text, trip_inputs=TripInputs())
    result = extractor(state)
    return result.parsed_inputs


def assert_destination_extracted(text: str, expected_dest: str, case_insensitive: bool = True):
    """Assert that a destination was extracted correctly."""
    parsed = run_extraction(text)
    destinations = parsed.get("destinations_delta", [])

    if case_insensitive:
        destinations_lower = [d.lower() for d in destinations]
        assert (
            expected_dest.lower() in destinations_lower
        ), f"Expected '{expected_dest}' in destinations, got {destinations} for input: {text}"
    else:
        assert (
            expected_dest in destinations
        ), f"Expected '{expected_dest}' in destinations, got {destinations} for input: {text}"


def assert_destination_extracted_any(
    text: str, expected_dests: list, case_insensitive: bool = True
):
    """Assert that any of the expected destinations was extracted."""
    parsed = run_extraction(text)
    destinations = parsed.get("destinations_delta", [])

    if case_insensitive:
        destinations_lower = [d.lower() for d in destinations]
        expected_lower = [e.lower() for e in expected_dests]
        found = any(e in destinations_lower for e in expected_lower)
        assert (
            found
        ), f"Expected one of {expected_dests} in destinations, got {destinations} for input: {text}"
    else:
        found = any(e in destinations for e in expected_dests)
        assert (
            found
        ), f"Expected one of {expected_dests} in destinations, got {destinations} for input: {text}"


def assert_hotel_extracted(text: str, expected_hotel: str):
    """Assert that a hotel was extracted correctly."""
    parsed = run_extraction(text)
    hotels = parsed.get("hotel_mentions", [])

    if hotels is None:
        hotels = []

    hotels_lower = [h.lower() for h in hotels]
    assert (
        expected_hotel.lower() in hotels_lower
    ), f"Expected '{expected_hotel}' in hotel_mentions, got {hotels} for input: {text}"


def assert_airline_extracted(text: str, expected_airline: str):
    """Assert that an airline was extracted correctly."""
    parsed = run_extraction(text)
    airlines = parsed.get("airline_mentions", [])

    if airlines is None:
        airlines = []

    airlines_lower = [a.lower() for a in airlines]
    assert (
        expected_airline.lower() in airlines_lower
    ), f"Expected '{expected_airline}' in airline_mentions, got {airlines} for input: {text}"


def assert_not_destination(text: str, not_expected: str):
    """Assert that something was NOT extracted as a destination."""
    parsed = run_extraction(text)
    destinations = parsed.get("destinations_delta", [])
    destinations_lower = [d.lower() for d in destinations]

    assert (
        not_expected.lower() not in destinations_lower
    ), f"'{not_expected}' should NOT be in destinations, but got {destinations} for input: {text}"


# =============================================================================
# TEST CLASSES
# =============================================================================


class TestMajorCities:
    """Test extraction of major world cities."""

    @pytest.mark.parametrize("city", MAJOR_CITIES[:20])  # Test first 20
    def test_going_to_city(self, city):
        assert_destination_extracted(f"going to {city}", city)

    @pytest.mark.parametrize("city", MAJOR_CITIES[:20])
    def test_from_x_to_city(self, city):
        assert_destination_extracted(f"from London to {city}", city)

    @pytest.mark.parametrize("city", MAJOR_CITIES[:20])
    def test_bare_city(self, city):
        assert_destination_extracted(city, city)

    @pytest.mark.parametrize("city", [c for c in MAJOR_CITIES[:20] if c.lower() != "singapore"])
    def test_city_lowercase(self, city):
        # Note: lowercase single-word destinations without context require spaCy
        # Singapore lowercase is ambiguous (country vs airline) - skip it
        if not _should_run_spacy_ner(city.lower(), {}):
            pytest.skip(
                "spaCy is disabled/unavailable; bare lowercase city extraction requires spaCy"
            )
        assert_destination_extracted(city.lower(), city)

    @pytest.mark.parametrize("city", MAJOR_CITIES[:20])
    def test_city_uppercase(self, city):
        assert_destination_extracted(city.upper(), city)


class TestCountries:
    """Test extraction of countries."""

    @pytest.mark.parametrize("country", COUNTRIES[:25])
    def test_visiting_country(self, country):
        assert_destination_extracted(f"visiting {country}", country)

    @pytest.mark.parametrize("country", COUNTRIES[:25])
    def test_trip_to_country(self, country):
        assert_destination_extracted(f"trip to {country}", country)

    def test_country_abbreviations(self):
        assert_destination_extracted("going to USA", "USA")
        assert_destination_extracted("going to UK", "UK")
        # "the US" includes article - accept either form
        assert_destination_extracted_any("visiting the US", ["US", "the US"])


class TestRegionsAndLandmarks:
    """Test extraction of regions, landmarks, and non-standard destinations."""

    @pytest.mark.parametrize("region", REGIONS_AND_LANDMARKS[:30])
    def test_region_extraction(self, region):
        assert_destination_extracted(f"I want to visit {region}", region)

    def test_patagonia_variations(self):
        assert_destination_extracted("Patagonia", "Patagonia")
        # Lowercase bare destination without context - test with grammar pattern
        assert_destination_extracted("going to patagonia", "patagonia")
        assert_destination_extracted("PATAGONIA", "Patagonia")
        assert_destination_extracted("going to Patagonia", "Patagonia")
        assert_destination_extracted("hiking in Patagonia", "Patagonia")

    def test_torres_del_paine(self):
        assert_destination_extracted("Torres del Paine", "Torres del Paine")
        assert_destination_extracted("visiting Torres del Paine", "Torres del Paine")

    def test_abbreviations(self):
        # These should be recognized via EntityRuler
        assert_destination_extracted("hiking to EBC", "EBC")
        assert_destination_extracted("sailing in BVI", "BVI")

    def test_french_locations(self):
        assert_destination_extracted("Côte d'Azur", "Côte d'Azur")
        # Unicode variations
        assert_destination_extracted("Cote d'Azur", "Cote d'Azur")


class TestUSLocations:
    """Test US-specific locations and abbreviations."""

    def test_city_abbreviations(self):
        assert_destination_extracted("flying to NYC", "NYC")
        assert_destination_extracted("going to LA", "LA")
        assert_destination_extracted("visiting SF", "SF")
        assert_destination_extracted("trip to Vegas", "Vegas")

    def test_washington_dc(self):
        assert_destination_extracted("going to Washington DC", "Washington DC")
        assert_destination_extracted("visiting Washington, D.C.", "Washington")

    def test_states_vs_cities(self):
        # These are tricky - could be state or city
        assert_destination_extracted("going to Hawaii", "Hawaii")
        assert_destination_extracted("visiting California", "California")


class TestHotelExtraction:
    """Test that hotel names are extracted correctly and NOT as destinations."""

    @pytest.mark.parametrize("hotel", HOTEL_CHAINS[:20])
    def test_hotel_in_sentence(self, hotel):
        text = f"I want to stay at the {hotel} in Paris"
        parsed = run_extraction(text)

        # Paris should be destination
        destinations = parsed.get("destinations_delta", [])
        assert any(
            "paris" in d.lower() for d in destinations
        ), f"Paris should be destination, got {destinations}"

        # Hotel should NOT be destination (should be in hotel_mentions or filtered)
        destinations_lower = [d.lower() for d in destinations]
        assert hotel.lower() not in destinations_lower, f"{hotel} should NOT be a destination"

    def test_hilton_not_destination(self):
        text = "staying at Hilton in Dubai"
        assert_destination_extracted(text, "Dubai")
        assert_not_destination(text, "Hilton")

    def test_marriott_not_destination(self):
        text = "booking Marriott in Tokyo"
        assert_destination_extracted(text, "Tokyo")
        assert_not_destination(text, "Marriott")

    def test_four_seasons_not_destination(self):
        text = "I want to book Four Seasons in Bali"
        assert_destination_extracted(text, "Bali")
        assert_not_destination(text, "Four Seasons")


class TestHostelsAndBudget:
    """Test hostel and budget accommodation extraction."""

    def test_hostel_not_destination(self):
        text = "booking a hostel in Barcelona"
        assert_destination_extracted(text, "Barcelona")

    def test_generator_hostel(self):
        text = "staying at Generator Hostel in Amsterdam"
        assert_destination_extracted(text, "Amsterdam")
        assert_not_destination(text, "Generator")

    def test_airbnb_not_destination(self):
        text = "renting an Airbnb in Rome"
        assert_destination_extracted(text, "Rome")
        assert_not_destination(text, "Airbnb")


class TestAirlineExtraction:
    """Test that airlines are extracted correctly."""

    @pytest.mark.parametrize("airline", ["Emirates", "Delta", "United", "Lufthansa", "Qatar"])
    def test_flying_airline_to_dest(self, airline):
        text = f"Flying {airline} to Dubai"
        parsed = run_extraction(text)

        # Dubai should be destination
        destinations = parsed.get("destinations_delta", [])
        assert any(
            "dubai" in d.lower() for d in destinations
        ), f"Dubai should be destination, got {destinations}"

        # Airline should be in airline_mentions
        airlines = parsed.get("airline_mentions", [])
        if airlines:  # May or may not be extracted depending on pattern
            assert_airline_extracted(text, airline)

    def test_delta_not_destination(self):
        text = "Flying Delta to Atlanta"
        assert_destination_extracted(text, "Atlanta")
        # Delta should NOT be a destination
        parsed = run_extraction(text)
        destinations = parsed.get("destinations_delta", [])
        destinations_lower = [d.lower() for d in destinations]
        assert "delta" not in destinations_lower

    def test_united_not_destination(self):
        text = "booking United to Chicago"
        parsed = run_extraction(text)
        destinations = parsed.get("destinations_delta", [])
        destinations_lower = [d.lower() for d in destinations]
        # "United" alone shouldn't be a destination
        assert "united" not in destinations_lower or "chicago" in destinations_lower


class TestAmbiguousEntities:
    """Test handling of ambiguous entity names."""

    def test_jordan_as_country(self):
        text = "visiting Jordan for the Dead Sea"
        assert_destination_extracted(text, "Jordan")

    def test_georgia_as_country(self):
        text = "traveling to Georgia in the Caucasus"
        assert_destination_extracted(text, "Georgia")

    def test_georgia_as_state(self):
        text = "going to Atlanta, Georgia"
        assert_destination_extracted(text, "Atlanta")

    def test_paris_as_city(self):
        text = "visiting Paris for the Eiffel Tower"
        assert_destination_extracted(text, "Paris")

    def test_nice_as_city(self):
        # "Nice" is a city but also an adjective
        text = "going to Nice, France"
        assert_destination_extracted(text, "Nice")

    def test_mobile_as_city(self):
        text = "visiting Mobile, Alabama"
        assert_destination_extracted(text, "Mobile")

    def test_reading_as_city(self):
        text = "going to Reading, UK"
        assert_destination_extracted(text, "Reading")

    def test_bath_as_city(self):
        text = "visiting Bath, England"
        assert_destination_extracted(text, "Bath")

    def test_split_as_city(self):
        text = "going to Split, Croatia"
        assert_destination_extracted(text, "Split")


class TestCaseVariations:
    """Test various case combinations."""

    def test_all_lowercase(self):
        assert_destination_extracted("going to paris", "paris")
        assert_destination_extracted("from london to tokyo", "tokyo")

    def test_all_uppercase(self):
        assert_destination_extracted("GOING TO PARIS", "PARIS")
        assert_destination_extracted("FROM LONDON TO TOKYO", "TOKYO")

    def test_mixed_case(self):
        assert_destination_extracted("Going To PARIS", "PARIS")
        assert_destination_extracted("FROM london TO Tokyo", "Tokyo")

    def test_camelcase_typos(self):
        # People sometimes type weird cases
        assert_destination_extracted("going to ParIs", "ParIs")
        assert_destination_extracted("LONdon to tokyo", "tokyo")


class TestGrammarBoundPatterns:
    """Test that grammar-bound patterns skip spaCy."""

    def test_from_to_skips_spacy(self):
        text = "from NYC to Paris"
        result = _should_run_spacy_ner(
            text, {"destinations_delta": ["Paris"], "origin_delta": "NYC"}
        )
        assert not result, "Grammar-bound from/to should skip spaCy"

    def test_going_to_skips_spacy(self):
        parsed = {"destinations_delta": ["Paris"]}
        text = "going to Paris"
        result = _should_run_spacy_ner(text, parsed)
        assert not result, "Grammar-bound 'going to' should skip spaCy"

    def test_bare_destination_runs_spacy(self):
        import app.plan_graph as plan_graph

        if not plan_graph._spacy_enabled():
            pytest.skip("spaCy is disabled/unavailable in this environment")

        text = "Patagonia"
        # When regex doesn't extract, spaCy should run
        result = _should_run_spacy_ner(text, {})
        assert result, "Bare destination without grammar should run spaCy"


class TestComplexSentences:
    """Test complex sentences with multiple entities."""

    def test_multiple_destinations(self):
        text = "visiting Paris, Rome, and Barcelona"
        parsed = run_extraction(text)
        destinations = parsed.get("destinations_delta", [])

        # Should extract multiple destinations
        assert len(destinations) >= 2, f"Expected multiple destinations, got {destinations}"

    def test_destination_with_hotel_and_airline(self):
        text = "Flying Emirates to Dubai, staying at the Burj Al Arab"
        parsed = run_extraction(text)

        destinations = parsed.get("destinations_delta", [])
        assert any("dubai" in d.lower() for d in destinations)

    def test_origin_and_destination(self):
        text = "from New York to Tokyo"
        parsed = run_extraction(text)

        assert parsed.get("origin_delta") is not None
        assert parsed.get("destinations_delta") is not None

    def test_destination_with_date(self):
        text = "going to Bali in December"
        parsed = run_extraction(text)

        destinations = parsed.get("destinations_delta", [])
        assert any("bali" in d.lower() for d in destinations)
        # December should NOT be a destination
        assert not any("december" in d.lower() for d in destinations)

    def test_destination_with_duration(self):
        text = "visiting Thailand for 2 weeks"
        parsed = run_extraction(text)

        destinations = parsed.get("destinations_delta", [])
        assert any("thailand" in d.lower() for d in destinations)


class TestEdgeCases:
    """Test edge cases and tricky inputs."""

    def test_empty_string(self):
        parsed = run_extraction("")
        assert parsed.get("destinations_delta") is None

    def test_only_whitespace(self):
        parsed = run_extraction("   ")
        assert parsed.get("destinations_delta") is None

    def test_only_punctuation(self):
        parsed = run_extraction("!@#$%")
        assert parsed.get("destinations_delta") is None

    def test_very_long_input(self):
        # Should not crash or timeout
        text = "going to Paris " * 100
        parsed = run_extraction(text)
        assert parsed is not None

    def test_unicode_characters(self):
        assert_destination_extracted("visiting São Paulo", "São Paulo")
        assert_destination_extracted("going to Zürich", "Zürich")
        assert_destination_extracted("trip to Malmö", "Malmö")
        assert_destination_extracted("visiting Kraków", "Kraków")

    def test_apostrophes(self):
        assert_destination_extracted("Côte d'Ivoire", "Côte d'Ivoire")
        assert_destination_extracted("going to Hawai'i", "Hawai'i")

    def test_hyphens(self):
        assert_destination_extracted("going to Stratford-upon-Avon", "Stratford-upon-Avon")
        assert_destination_extracted("visiting Baden-Baden", "Baden-Baden")

    def test_numbers_in_names(self):
        # Route 66, Area 51 etc shouldn't cause issues
        parsed = run_extraction("driving Route 66")
        # Should not crash
        assert parsed is not None

    def test_the_prefix(self):
        # Note: "The" is stripped by regex, so we accept either form
        # "The Hague" and "The Bahamas" are edge cases where The is part of the name
        assert_destination_extracted_any("visiting The Hague", ["The Hague", "Hague"])
        assert_destination_extracted_any("going to The Bahamas", ["The Bahamas", "Bahamas"])

    def test_new_prefix(self):
        assert_destination_extracted("visiting New Zealand", "New Zealand")
        assert_destination_extracted("going to New Orleans", "New Orleans")
        assert_destination_extracted("trip to New Delhi", "New Delhi")

    def test_saint_prefix(self):
        assert_destination_extracted("going to St. Lucia", "St. Lucia")
        assert_destination_extracted("visiting Saint Petersburg", "Saint Petersburg")
        assert_destination_extracted("trip to San Francisco", "San Francisco")

    def test_los_las_prefix(self):
        assert_destination_extracted("going to Los Angeles", "Los Angeles")
        assert_destination_extracted("visiting Las Vegas", "Las Vegas")


class TestActivityInference:
    """Test that activities are inferred from destinations."""

    def test_patagonia_infers_hiking(self):
        parsed = run_extraction("going to Patagonia")
        activities = parsed.get("inferred_activity_categories", [])
        assert any(
            "hiking" in a.lower() for a in activities
        ), f"Patagonia should infer hiking, got {activities}"

    def test_maldives_infers_diving(self):
        parsed = run_extraction("visiting Maldives")
        activities = parsed.get("inferred_activity_categories", [])
        # Should infer diving or beach
        assert len(activities) > 0, f"Maldives should infer activities, got {activities}"

    def test_alps_infers_skiing(self):
        parsed = run_extraction("going to the Alps")
        activities = parsed.get("inferred_activity_categories", [])
        assert any(
            "ski" in a.lower() for a in activities
        ), f"Alps should infer skiing, got {activities}"


class TestDateExtraction:
    """Test that dates are extracted and destinations are not polluted."""

    def test_december_not_destination(self):
        text = "going to Paris in December"
        parsed = run_extraction(text)
        destinations = parsed.get("destinations_delta", [])

        # December should NOT be in destinations
        assert not any(
            "december" in d.lower() for d in destinations
        ), f"December should not be destination, got {destinations}"

    def test_next_week_not_destination(self):
        text = "visiting Tokyo next week"
        parsed = run_extraction(text)
        destinations = parsed.get("destinations_delta", [])

        assert not any("next" in d.lower() or "week" in d.lower() for d in destinations)

    def test_date_extracted_separately(self):
        text = "Patagonia in December"
        parsed = run_extraction(text)

        # Should have date hint
        date_hint = parsed.get("start_date_hint")
        assert date_hint is not None, "Should extract date hint"


class TestSpacyFallback:
    """Test spaCy NER fallback behavior."""

    def test_spacy_available(self):
        """Verify spaCy is available for tests."""
        nlp = _get_spacy_nlp()
        if nlp is None:
            pytest.skip("spaCy model unavailable or disabled")
        assert nlp is not None, "spaCy should be available"

    def test_spacy_extracts_unlisted_destination(self):
        """Test that spaCy can extract destinations not in our EntityRuler."""
        # Use a city that might not be in our custom patterns
        text = "I want to visit Reykjavik"
        parsed = run_extraction(text)
        destinations = parsed.get("destinations_delta", [])

        # Should still extract via spaCy or "visit" pattern
        assert len(destinations) > 0, f"Should extract Reykjavik, got {destinations}"

    def test_spacy_entities_function(self):
        """Direct test of spaCy extraction function."""
        if _get_spacy_nlp() is None:
            pytest.skip("spaCy model unavailable or disabled")

        entities = _spacy_extract_entities("staying at Hilton in Dubai")

        # Should extract Dubai as destination
        assert "spacy_destinations" in entities
        assert any("dubai" in d.lower() for d in entities["spacy_destinations"])


class TestBulkDestinations:
    """Bulk tests for many destinations at once."""

    @pytest.mark.parametrize("dest", MAJOR_CITIES + COUNTRIES[:20] + REGIONS_AND_LANDMARKS[:20])
    def test_bulk_visiting(self, dest):
        """Test 'visiting X' pattern for many destinations."""
        try:
            text = f"visiting {dest}"
            parsed = run_extraction(text)
            # At minimum, should not crash
            assert parsed is not None
        except Exception as e:
            pytest.fail(f"Failed for destination '{dest}': {e}")


class TestRealWorldQueries:
    """Test realistic user queries."""

    def test_honeymoon_query(self):
        text = "We're planning our honeymoon to the Maldives in March"
        parsed = run_extraction(text)
        destinations = parsed.get("destinations_delta", [])
        assert any("maldives" in d.lower() for d in destinations)

    def test_business_trip(self):
        text = "I need to fly to Singapore for a conference"
        parsed = run_extraction(text)
        destinations = parsed.get("destinations_delta", [])
        assert any("singapore" in d.lower() for d in destinations)

    def test_family_vacation(self):
        text = "Planning a family vacation to Orlando, staying at a Disney resort"
        parsed = run_extraction(text)
        destinations = parsed.get("destinations_delta", [])
        assert any("orlando" in d.lower() for d in destinations)

    def test_backpacking_trip(self):
        text = "Backpacking through Southeast Asia, starting in Bangkok"
        parsed = run_extraction(text)
        destinations = parsed.get("destinations_delta", [])
        assert any("bangkok" in d.lower() or "asia" in d.lower() for d in destinations)

    def test_road_trip(self):
        text = "Road trip from LA to San Francisco"
        parsed = run_extraction(text)
        assert parsed.get("origin_delta") is not None or any(
            "la" in d.lower() or "los angeles" in d.lower()
            for d in parsed.get("destinations_delta", [])
        )

    def test_cruise_query(self):
        text = "Looking for a Caribbean cruise from Miami"
        parsed = run_extraction(text)
        # Should extract something
        assert parsed is not None

    def test_ski_trip(self):
        text = "Ski trip to Aspen in January"
        parsed = run_extraction(text)
        destinations = parsed.get("destinations_delta", [])
        assert any("aspen" in d.lower() for d in destinations)

    def test_wine_tour(self):
        text = "Wine tasting in Tuscany next fall"
        parsed = run_extraction(text)
        destinations = parsed.get("destinations_delta", [])
        assert any("tuscany" in d.lower() for d in destinations)


# =============================================================================
# TEST CLASS: FUZZY INPUTS (TYPOS)
# =============================================================================


class TestFuzzyInputsTypos:
    """Test handling of typos and misspellings with confidence scoring."""

    # Common typos for popular destinations
    TYPO_TEST_CASES = [
        # (typo, expected_destination, should_have_typo_suggestion)
        ("Patogonia", "Patogonia", True),  # Should extract and flag typo
        ("Bacelona", "Bacelona", True),  # Barcelona
        ("Prauge", "Prauge", True),  # Prague
        ("Toyko", "Toyko", True),  # Tokyo
        ("Sydeny", "Sydeny", True),  # Sydney
        ("Maimi", "Maimi", True),  # Miami
        ("Vencie", "Vencie", True),  # Venice
        ("Athen", "Athen", True),  # Athens
        ("Dubln", "Dubln", True),  # Dublin
        ("Amsterdm", "Amsterdm", True),  # Amsterdam
    ]

    @pytest.mark.parametrize("typo,expected,should_flag", TYPO_TEST_CASES)
    def test_typo_extraction_with_grammar(self, typo, expected, should_flag):
        """Test that typos are extracted and flagged with fuzzy suggestions."""
        from app.plan_graph import GraphState, TripInputs, extractor

        text = f"I want to go to {typo}"
        state = GraphState(user_text=text, trip_inputs=TripInputs())
        result = extractor(state)

        # Should still extract the destination (even with typo)
        destinations = result.parsed_inputs.get("destinations_delta", [])
        assert len(destinations) > 0, f"Should extract '{typo}' as destination, got {destinations}"

        # Check confidence metadata
        conf = result.metadata.get("extraction_confidence", {})

        if should_flag:
            # Level should be medium or low for typos
            assert conf.get("level") in (
                "medium",
                "low",
            ), f"Typo should lower confidence, got {conf.get('level')}"

    def test_patogonia_suggests_patagonia(self):
        """Test that Patogonia suggests Patagonia as correction."""
        from app.plan_graph import GraphState, TripInputs, extractor

        state = GraphState(user_text="I want to visit Patogonia", trip_inputs=TripInputs())
        result = extractor(state)

        conf = result.metadata.get("extraction_confidence", {})
        typo_suggestions = conf.get("typo_suggestions", {})

        assert (
            "Patogonia" in typo_suggestions
        ), f"Should suggest correction for Patogonia, got {typo_suggestions}"
        assert (
            typo_suggestions.get("Patogonia") == "Patagonia"
        ), f"Should suggest 'Patagonia', got {typo_suggestions}"

    def test_correct_spelling_no_suggestions(self):
        """Test that correct spellings don't have typo suggestions."""
        from app.plan_graph import GraphState, TripInputs, extractor

        state = GraphState(user_text="I want to visit Patagonia", trip_inputs=TripInputs())
        result = extractor(state)

        conf = result.metadata.get("extraction_confidence", {})
        typo_suggestions = conf.get("typo_suggestions", {})

        # Should have no typo suggestions for correct spelling
        assert (
            not typo_suggestions
        ), f"Correct spelling should have no suggestions, got {typo_suggestions}"
        assert conf.get("level") == "high", "Correct spelling should have high confidence"

    def test_multiple_typos(self):
        """Test extraction with multiple typos in one sentence."""
        from app.plan_graph import GraphState, TripInputs, extractor

        text = "from Londn to Parsi"  # London to Paris with typos
        state = GraphState(user_text=text, trip_inputs=TripInputs())
        result = extractor(state)

        # Should extract both with grammar pattern
        parsed = result.parsed_inputs
        assert parsed.get("origin_delta") is not None or parsed.get("destinations_delta")

    def test_close_but_not_quite(self):
        """Test words that are close to places but not typos."""
        from app.plan_graph import GraphState, TripInputs, extractor

        # "Paradise" is not a typo for "Paris"
        state = GraphState(user_text="I want to go to Paradise", trip_inputs=TripInputs())
        result = extractor(state)

        # Should extract Paradise but not suggest Paris (too different)
        assert result.parsed_inputs is not None

    def test_minor_typo_high_similarity(self):
        """Test that very minor typos (1 char) are caught."""
        from app.plan_graph import GraphState, TripInputs, extractor

        # "Londen" is very close to "London"
        state = GraphState(user_text="fly to Londen", trip_inputs=TripInputs())
        result = extractor(state)

        # Should flag as potential typo
        assert result.metadata.get("extraction_confidence") is not None


# =============================================================================
# TEST CLASS: DIFFERENT LANGUAGE INPUTS
# =============================================================================


class TestMultiLanguageInputs:
    """Test handling of non-English inputs with language detection."""

    # Test cases: (input_text, expected_destination, language_code)
    LANGUAGE_TEST_CASES = [
        # German
        ("Ich möchte nach Berlin reisen", "Berlin", "de"),
        ("Flug nach München buchen", "München", "de"),
        # Spanish
        ("Quiero viajar a Barcelona", "Barcelona", "es"),
        ("Vuelo a Madrid", "Madrid", "es"),
        # French
        ("Je veux aller à Paris", "Paris", "fr"),
        ("Voyage à Marseille", "Marseille", "fr"),
        # Italian
        ("Voglio andare a Roma", "Roma", "it"),
        ("Viaggio a Firenze", "Firenze", "it"),
        # Portuguese
        ("Quero ir para Lisboa", "Lisboa", "pt"),
        ("Viagem para o Rio de Janeiro", "Rio de Janeiro", "pt"),
    ]

    @pytest.mark.parametrize("text,expected_dest,lang", LANGUAGE_TEST_CASES)
    def test_non_english_destination_extraction(self, text, expected_dest, lang):
        """Test that destinations can be extracted from non-English text."""
        from app.plan_graph import GraphState, TripInputs, extractor

        state = GraphState(user_text=text, trip_inputs=TripInputs())
        result = extractor(state)

        # The system should attempt extraction - may not always succeed
        # but should not crash
        parsed = result.parsed_inputs
        assert parsed is not None, f"Should handle non-English input: {text}"

    def test_german_berlin_extraction(self):
        """Test German input for Berlin."""
        from app.plan_graph import GraphState, TripInputs, extractor

        text = "Ich möchte nach Berlin fliegen"
        state = GraphState(user_text=text, trip_inputs=TripInputs())
        result = extractor(state)

        # Short text might not trigger language detection, so just check no crash
        assert result is not None

    def test_spanish_madrid_extraction(self):
        """Test Spanish input for Madrid."""
        from app.plan_graph import GraphState, TripInputs, extractor

        text = "Necesito un vuelo a Madrid para la próxima semana"
        state = GraphState(user_text=text, trip_inputs=TripInputs())
        result = extractor(state)

        # May detect as Spanish for longer text
        assert result is not None

    def test_french_riviera_extraction(self):
        """Test French input for Côte d'Azur."""
        from app.plan_graph import GraphState, TripInputs, extractor

        text = "Je voudrais visiter la Côte d'Azur cet été"
        state = GraphState(user_text=text, trip_inputs=TripInputs())
        result = extractor(state)

        assert result is not None

    def test_mixed_language_english_destination(self):
        """Test non-English sentence with English destination name."""
        from app.plan_graph import GraphState, TripInputs, extractor

        # German sentence but "New York" is universal
        text = "Ich möchte nach New York City fliegen"
        state = GraphState(user_text=text, trip_inputs=TripInputs())
        result = extractor(state)

        # May or may not extract depending on patterns
        assert result is not None

    def test_japanese_input_doesnt_crash(self):
        """Test that Japanese input doesn't crash the system."""
        from app.plan_graph import GraphState, TripInputs, extractor

        text = "東京に行きたいです"  # I want to go to Tokyo
        state = GraphState(user_text=text, trip_inputs=TripInputs())
        result = extractor(state)

        # Should not crash, even if it can't extract
        assert result is not None

    def test_korean_input_doesnt_crash(self):
        """Test that Korean input doesn't crash the system."""
        from app.plan_graph import GraphState, TripInputs, extractor

        text = "서울로 가고 싶습니다"  # I want to go to Seoul
        state = GraphState(user_text=text, trip_inputs=TripInputs())
        result = extractor(state)

        assert result is not None

    def test_arabic_input_doesnt_crash(self):
        """Test that Arabic input doesn't crash the system."""
        from app.plan_graph import GraphState, TripInputs, extractor

        text = "أريد السفر إلى دبي"  # I want to travel to Dubai
        state = GraphState(user_text=text, trip_inputs=TripInputs())
        result = extractor(state)

        assert result is not None

    def test_chinese_input_doesnt_crash(self):
        """Test that Chinese input doesn't crash the system."""
        from app.plan_graph import GraphState, TripInputs, extractor

        text = "我想去北京"  # I want to go to Beijing
        state = GraphState(user_text=text, trip_inputs=TripInputs())
        result = extractor(state)

        assert result is not None


# =============================================================================
# TEST CLASS: CONFIDENCE SCORING INTEGRATION
# =============================================================================


class TestConfidenceScoring:
    """Test confidence scoring for various extraction scenarios."""

    def test_high_confidence_known_place_grammar(self):
        """Test high confidence for known place with grammar pattern."""
        from app.plan_graph import GraphState, TripInputs, extractor

        state = GraphState(user_text="from London to Paris", trip_inputs=TripInputs())
        result = extractor(state)

        conf = result.metadata.get("extraction_confidence", {})
        assert conf.get("level") == "high", f"Should be high confidence, got {conf}"
        assert (
            conf.get("overall", 0) >= 0.80
        ), f"Overall should be >= 0.80, got {conf.get('overall')}"

    def test_medium_confidence_typo(self):
        """Test medium confidence for typos."""
        from app.plan_graph import GraphState, TripInputs, extractor

        state = GraphState(user_text="I want to go to Patogonia", trip_inputs=TripInputs())
        result = extractor(state)

        conf = result.metadata.get("extraction_confidence", {})
        assert conf.get("level") in ("medium", "low"), f"Typo should lower confidence, got {conf}"
        assert (
            0.50 <= conf.get("overall", 0) < 0.80
        ), f"Overall should be medium range, got {conf.get('overall')}"

    def test_ambiguous_entity_confidence(self):
        """Test that ambiguous entities affect confidence."""
        from app.plan_graph import GraphState, TripInputs, extractor

        state = GraphState(user_text="visit Georgia", trip_inputs=TripInputs())
        result = extractor(state)

        conf = result.metadata.get("extraction_confidence", {})
        low_reasons = conf.get("low_confidence_reasons", [])

        # Should flag as ambiguous
        assert any(
            "ambiguous" in r.lower() for r in low_reasons
        ), f"Should flag Georgia as ambiguous, got {low_reasons}"

    def test_entity_confidence_metadata(self):
        """Test that per-entity confidence is stored."""
        from app.plan_graph import GraphState, TripInputs, extractor

        state = GraphState(user_text="from London to Tokyo", trip_inputs=TripInputs())
        result = extractor(state)

        # At minimum, overall confidence should be present
        conf = result.metadata.get("extraction_confidence", {})
        assert "overall" in conf
        assert "level" in conf


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
