"""Unit tests for destination normalization and case-insensitive deduplication.

Tests cover:
1. Case-insensitive deduplication (rome, Rome -> Rome)
2. Title-casing (new york -> New York)
3. End-to-end flow simulation where user types lowercase and LLM returns title-case
4. And/Or logic wiring for multi-city intent
"""

# ruff: noqa: E402

import os
import sys
from pathlib import Path

# Suppress debug output before importing plan_graph
os.environ["PLAN_GRAPH_DEBUG"] = "0"

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from app.graph_plan_utils import normalize_destinations
from app.plan_graph import TripInputs, _normalize_str


class TestNormalizeDestinations:
    """Tests for the normalize_destinations function."""

    def test_case_insensitive_deduplication_same_case(self):
        """Exact duplicates should be removed."""
        result = normalize_destinations(["Rome", "Rome", "Paris"])
        assert result == ["Rome", "Paris"]

    def test_case_insensitive_deduplication_different_case(self):
        """Case-insensitive duplicates should be removed (rome, Rome -> Rome)."""
        result = normalize_destinations(["rome", "Rome"])
        assert result == ["Rome"]

    def test_case_insensitive_deduplication_lowercase_first(self):
        """First occurrence wins but gets title-cased."""
        result = normalize_destinations(["rome", "ROME", "Rome"])
        assert result == ["Rome"]

    def test_case_insensitive_deduplication_mixed(self):
        """Multiple destinations with case variations."""
        result = normalize_destinations(["paris", "rome", "PARIS", "Rome"])
        assert result == ["Paris", "Rome"]

    def test_title_casing_single_word(self):
        """Single word destinations should be title-cased."""
        result = normalize_destinations(["rome", "paris", "tokyo"])
        assert result == ["Rome", "Paris", "Tokyo"]

    def test_title_casing_multi_word(self):
        """Multi-word destinations should have each word title-cased."""
        result = normalize_destinations(["new york", "los angeles", "san francisco"])
        assert result == ["New York", "Los Angeles", "San Francisco"]

    def test_title_casing_all_caps(self):
        """All-caps destinations should be converted to title-case."""
        result = normalize_destinations(["PARIS", "NEW YORK"])
        assert result == ["Paris", "New York"]

    def test_short_all_caps_preserved(self):
        """Short all-caps tokens (<=4 chars) like country codes should be preserved."""
        result = normalize_destinations(["USA", "NYC"])
        assert result == ["USA", "NYC"]

    def test_hyphenated_destinations(self):
        """Hyphenated destinations should be handled correctly."""
        result = normalize_destinations(["hong-kong", "new-york-city"])
        # Each part of the hyphen should be title-cased
        assert result == ["Hong-Kong", "New-York-City"]

    def test_empty_list(self):
        """Empty list should return empty list."""
        result = normalize_destinations([])
        assert result == []

    def test_list_with_empty_strings(self):
        """Empty strings should be filtered out."""
        result = normalize_destinations(["", "Rome", "", "Paris"])
        assert result == ["Rome", "Paris"]

    def test_list_with_whitespace_only(self):
        """Whitespace-only strings should be filtered out."""
        result = normalize_destinations(["   ", "Rome", "\t", "Paris"])
        assert result == ["Rome", "Paris"]

    def test_non_string_values_filtered(self):
        """Non-string values should be filtered out."""
        result = normalize_destinations(["Rome", None, 123, "Paris", [], {}])
        assert result == ["Rome", "Paris"]

    def test_max_count_limit(self):
        """Results should be limited by max_count parameter."""
        destinations = ["Rome", "Paris", "Tokyo", "London", "Madrid"]
        result = normalize_destinations(destinations, max_count=3)
        assert len(result) == 3
        assert result == ["Rome", "Paris", "Tokyo"]

    def test_whitespace_normalization(self):
        """Extra whitespace should be collapsed."""
        result = normalize_destinations(["  Rome  ", "  New   York  "])
        assert result == ["Rome", "New York"]


class TestCountrySuffixStripping:
    """Tests for stripping country suffixes from destinations."""

    def test_strip_country_suffix_basic(self):
        """Basic 'Place, Country' format should strip country."""
        result = normalize_destinations(["Banff, Canada"])
        assert result == ["Banff"]

    def test_strip_country_suffix_usa(self):
        """USA and variations should be stripped."""
        result = normalize_destinations(
            [
                "New York, USA",
                "Los Angeles, US",
                "Chicago, United States",
            ]
        )
        assert result == ["New York", "Los Angeles", "Chicago"]

    def test_strip_country_suffix_uk(self):
        """UK and variations should be stripped."""
        result = normalize_destinations(
            [
                "London, UK",
                "Manchester, United Kingdom",
                "Edinburgh, Scotland",
            ]
        )
        assert result == ["London", "Manchester", "Edinburgh"]

    def test_strip_country_suffix_various_countries(self):
        """Various country names should be stripped."""
        result = normalize_destinations(
            [
                "Paris, France",
                "Tokyo, Japan",
                "Sydney, Australia",
                "Rome, Italy",
                "Barcelona, Spain",
            ]
        )
        assert result == ["Paris", "Tokyo", "Sydney", "Rome", "Barcelona"]

    def test_strip_country_suffix_preserves_non_country(self):
        """Non-country suffixes should be preserved."""
        result = normalize_destinations(
            [
                "San Francisco, California",  # State, not country - should preserve
                "New York, New York",  # City, State - should preserve
            ]
        )
        # These should NOT be stripped since California and New York are not countries
        assert result == ["San Francisco, California", "New York, New York"]

    def test_strip_country_suffix_no_comma(self):
        """Destinations without comma should be unchanged."""
        result = normalize_destinations(["Rome", "Paris", "Tokyo"])
        assert result == ["Rome", "Paris", "Tokyo"]

    def test_strip_country_suffix_deduplication(self):
        """Country stripping should deduplicate (Banff, Canada + Banff -> single Banff)."""
        result = normalize_destinations(["Banff, Canada", "Banff"])
        assert result == ["Banff"]

    def test_strip_country_suffix_case_insensitive(self):
        """Country matching should be case-insensitive."""
        result = normalize_destinations(
            [
                "Rome, ITALY",
                "Paris, france",
                "Tokyo, JAPAN",
            ]
        )
        assert result == ["Rome", "Paris", "Tokyo"]

    def test_strip_country_suffix_with_multi_word_place(self):
        """Multi-word places with country suffix should work."""
        result = normalize_destinations(
            [
                "New York City, USA",
                "Los Angeles, United States",
                "Hong Kong, China",
            ]
        )
        assert result == ["New York City", "Los Angeles", "Hong Kong"]


class TestDestinationDeduplicationInTripInputs:
    """End-to-end deduping between lowercase and title-case inputs."""

    def test_simulate_user_then_llm_duplicate(self):
        """Simulate: user types 'rome', LLM returns 'Rome' - should not duplicate."""
        # Step 1: User types "rome" - goes through extractor
        ti = TripInputs(destinations=["rome"])

        # Step 2: LLM returns "Rome" - this simulates what happens in _specialist
        llm_destinations = ["Rome"]
        existing_lower = {d.lower() for d in ti.destinations}
        for d in llm_destinations:
            d_norm = _normalize_str(d)
            if d_norm and d_norm.lower() not in existing_lower:
                ti.destinations.append(d_norm)
                existing_lower.add(d_norm.lower())

        # Should have only one destination
        assert len(ti.destinations) == 1
        # Note: at this point it's still "rome" because we only block duplicates
        # The normalization to "Rome" happens in normalize_destinations
        assert ti.destinations == ["rome"]

        # Step 3: normalize_destinations is called in apply_planner_update
        ti.destinations = normalize_destinations(ti.destinations)
        assert ti.destinations == ["Rome"]

    def test_simulate_multiple_destinations_mixed_case(self):
        """Simulate conversation adding destinations with various cases."""
        ti = TripInputs(destinations=[])

        # User says "I want to go to paris"
        user_destinations = ["paris"]
        existing_lower = {d.lower() for d in ti.destinations}
        for d in user_destinations:
            d_norm = _normalize_str(d)
            if d_norm and d_norm.lower() not in existing_lower:
                ti.destinations.append(d_norm)
                existing_lower.add(d_norm.lower())

        # LLM responds with "Paris" and also adds "Rome"
        llm_destinations = ["Paris", "Rome"]
        existing_lower = {d.lower() for d in ti.destinations}
        for d in llm_destinations:
            d_norm = _normalize_str(d)
            if d_norm and d_norm.lower() not in existing_lower:
                ti.destinations.append(d_norm)
                existing_lower.add(d_norm.lower())

        # Should have paris and Rome (paris blocked because of case-insensitive check)
        assert len(ti.destinations) == 2
        assert "paris" in ti.destinations
        assert "Rome" in ti.destinations

        # After normalization
        ti.destinations = normalize_destinations(ti.destinations)
        assert ti.destinations == ["Paris", "Rome"]


class TestAndOrLogicWiring:
    """Tests for multi_city_intent and/or logic."""

    def test_multi_city_intent_values(self):
        """multi_city_intent should accept 'multi_city' or 'separate'."""
        ti = TripInputs(destinations=["Rome", "Paris"])

        # Default is None
        assert ti.multi_city_intent is None

        # Set to multi_city (visit together as one trip - "and")
        ti.multi_city_intent = "multi_city"
        assert ti.multi_city_intent == "multi_city"

        # Set to separate (compare as separate trips - "or")
        ti.multi_city_intent = "separate"
        assert ti.multi_city_intent == "separate"

    def test_multi_city_intent_with_destinations(self):
        """multi_city_intent should work independently of number of destinations."""
        # Single destination - intent doesn't matter functionally but should be settable
        ti_single = TripInputs(destinations=["Rome"], multi_city_intent="multi_city")
        assert ti_single.multi_city_intent == "multi_city"

        # Multiple destinations with multi_city
        ti_multi = TripInputs(
            destinations=["Rome", "Paris", "Barcelona"], multi_city_intent="multi_city"
        )
        assert ti_multi.multi_city_intent == "multi_city"
        assert len(ti_multi.destinations) == 3

    def test_normalized_destinations_preserves_order(self):
        """Normalization should preserve the order of destinations."""
        destinations = ["tokyo", "paris", "rome"]
        result = normalize_destinations(destinations)
        assert result == ["Tokyo", "Paris", "Rome"]
