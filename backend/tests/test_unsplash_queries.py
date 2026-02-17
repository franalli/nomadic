# backend/tests/test_unsplash_queries.py
"""
Pure function tests for unsplash_queries.py — query generation, no side effects.
"""

import pytest

from app.services.unsplash_queries import (
    ACTIVITY_QUERIES,
    DESTINATION_QUERIES,
    get_query_for_destination,
)


class TestGetQueryForDestination:
    """Query generation determines image search quality."""

    # ── Destination-only queries ─────────────────────────────────────────

    def test_known_destination(self) -> None:
        result = get_query_for_destination("Bali")
        assert result == DESTINATION_QUERIES["bali"]

    def test_case_insensitive(self) -> None:
        assert get_query_for_destination("PARIS") == get_query_for_destination("paris")

    def test_unknown_destination_fallback(self) -> None:
        result = get_query_for_destination("Atlantis")
        assert result == "Atlantis travel landmark"

    def test_whitespace_stripped(self) -> None:
        result = get_query_for_destination("  bali  ")
        assert result == DESTINATION_QUERIES["bali"]

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

    def test_skiing_includes_destination(self) -> None:
        result = get_query_for_destination("Chamonix", activities=["skiing"])
        assert "Chamonix" in result
        assert "skiing" in result

    def test_first_activity_used(self) -> None:
        """When multiple activities provided, only the first is used."""
        result = get_query_for_destination("Bali", activities=["diving", "hiking"])
        assert result == ACTIVITY_QUERIES["diving"]

    def test_unknown_activity_falls_back_to_destination(self) -> None:
        result = get_query_for_destination("Bali", activities=["bungee_jumping"])
        assert result == DESTINATION_QUERIES["bali"]

    def test_empty_activities_list(self) -> None:
        result = get_query_for_destination("Bali", activities=[])
        assert result == DESTINATION_QUERIES["bali"]

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
    """Verify the lookup dictionaries are well-formed."""

    def test_destination_queries_are_strings(self) -> None:
        for key, value in DESTINATION_QUERIES.items():
            assert isinstance(key, str), f"Key {key!r} is not a string"
            assert isinstance(value, str), f"Value for {key!r} is not a string"
            assert len(value) > 0, f"Empty query for {key!r}"

    def test_activity_queries_are_strings(self) -> None:
        for key, value in ACTIVITY_QUERIES.items():
            assert isinstance(key, str), f"Key {key!r} is not a string"
            assert isinstance(value, str), f"Value for {key!r} is not a string"
            assert len(value) > 0, f"Empty query for {key!r}"

    def test_destination_keys_lowercase(self) -> None:
        for key in DESTINATION_QUERIES:
            assert key == key.lower(), f"Key {key!r} is not lowercase"

    def test_activity_keys_lowercase(self) -> None:
        for key in ACTIVITY_QUERIES:
            assert key == key.lower(), f"Key {key!r} is not lowercase"
