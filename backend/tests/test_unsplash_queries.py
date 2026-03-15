# backend/tests/test_unsplash_queries.py
"""
Pure function tests for unsplash_queries.py — query generation, no side effects.
"""

import pytest

import app.services.unsplash_queries as unsplash_queries
from app.services.unsplash_queries import ACTIVITY_QUERIES, get_query_for_destination


class TestGetQueryForDestination:
    """Query generation determines image search quality."""

    # ── Destination-only queries ─────────────────────────────────────────

    def test_destination_query_is_generic(self) -> None:
        result = get_query_for_destination("Bali")
        assert result == "Bali travel destination landscape cityscape"

    def test_case_insensitive(self) -> None:
        assert get_query_for_destination("PARIS") == get_query_for_destination("paris")

    def test_whitespace_stripped(self) -> None:
        result = get_query_for_destination("  bali  ")
        assert result == "Bali travel destination landscape cityscape"

    def test_blank_destination_uses_generic_fallback(self) -> None:
        result = get_query_for_destination("   ")
        assert result == "travel destination landscape cityscape"

    def test_destination_lookup_table_removed(self) -> None:
        assert not hasattr(unsplash_queries, "DESTINATION_QUERIES")

    # ── Activity-specific queries ────────────────────────────────────────

    def test_underwater_activity_pure_query(self) -> None:
        """Underwater activities use pure activity query (coral looks the same everywhere)."""
        result = get_query_for_destination("Bali", activities=["diving"])
        assert result == ACTIVITY_QUERIES["diving"]
        assert "bali" not in result.lower()

    def test_land_activity_includes_destination(self) -> None:
        """Land-based activities combine destination + activity for location-specific imagery."""
        result = get_query_for_destination("Bali", activities=["hiking"])
        assert "Bali" in result
        assert "hiking" in result
        assert "travel destination landscape cityscape" in result

    def test_skiing_includes_destination(self) -> None:
        result = get_query_for_destination("Chamonix", activities=["skiing"])
        assert "Chamonix" in result
        assert "skiing" in result

    def test_first_activity_used(self) -> None:
        """When multiple activities provided, only the first is used."""
        result = get_query_for_destination("Bali", activities=["diving", "hiking"])
        assert result == ACTIVITY_QUERIES["diving"]

    def test_unknown_activity_generates_query(self) -> None:
        """Novel Tier 2 categories get a generated query instead of falling back to destination."""
        result = get_query_for_destination("Bali", activities=["bungee_jumping"])
        assert "Bali" in result
        assert "bungee_jumping" in result
        assert result.endswith("travel experience")

    def test_empty_activities_list(self) -> None:
        result = get_query_for_destination("Bali", activities=[])
        assert result == "Bali travel destination landscape cityscape"

    # ── Determinism ──────────────────────────────────────────────────────

    def test_deterministic(self) -> None:
        """Same inputs always produce same outputs (no randomization)."""
        r1 = get_query_for_destination("Tokyo", activities=["food"])
        r2 = get_query_for_destination("Tokyo", activities=["food"])
        assert r1 == r2

    # ── Coverage of activity categories ──────────────────────────────────

    @pytest.mark.parametrize(
        "activity",
        [
            "diving",
            "snorkeling",
            "kayaking",
            "hiking",
            "skiing",
            "climbing",
            "cycling",
            "surfing",
            "yoga",
            "cooking",
            "nightlife",
            "sailing",
            "food",
            "wine",
            "photography",
            "wellness",
            "culture",
            "music",
        ],
    )
    def test_all_activity_queries_exist(self, activity: str) -> None:
        assert activity in ACTIVITY_QUERIES


class TestQueryDataIntegrity:
    """Verify the remaining bounded query dictionaries are well-formed."""

    def test_activity_queries_are_strings(self) -> None:
        for key, value in ACTIVITY_QUERIES.items():
            assert isinstance(key, str), f"Key {key!r} is not a string"
            assert isinstance(value, str), f"Value for {key!r} is not a string"
            assert len(value) > 0, f"Empty query for {key!r}"

    def test_activity_keys_lowercase(self) -> None:
        for key in ACTIVITY_QUERIES:
            assert key == key.lower(), f"Key {key!r} is not lowercase"
