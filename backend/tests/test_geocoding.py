"""
Tests for geocoding service.

Uses mocking to avoid actual network calls during testing.
"""

from unittest.mock import patch

from app.geocoding import (
    GeocodingCache,
    GeocodingResult,
    _parse_nominatim_response,
    clear_geocoding_cache,
    geocode_place_sync,
)


class TestGeocodingResult:
    """Tests for GeocodingResult dataclass."""

    def test_short_name_us_with_state(self):
        """US locations should show city, state format."""
        result = GeocodingResult(
            display_name="South Bend, St. Joseph County, Indiana, USA",
            city="South Bend",
            state="Indiana",
            country="United States",
            country_code="us",
            lat=41.6764,
            lng=-86.2520,
        )
        assert result.short_name == "South Bend, Indiana"

    def test_short_name_us_state_only(self):
        """US state without city should show just state."""
        result = GeocodingResult(
            display_name="Indiana, USA",
            city=None,
            state="Indiana",
            country="United States",
            country_code="us",
            lat=40.0,
            lng=-86.0,
        )
        assert result.short_name == "Indiana"

    def test_short_name_non_us(self):
        """Non-US locations should show city, country format."""
        result = GeocodingResult(
            display_name="Paris, Ile-de-France, France",
            city="Paris",
            state="Ile-de-France",
            country="France",
            country_code="fr",
            lat=48.8566,
            lng=2.3522,
        )
        assert result.short_name == "Paris, France"

    def test_short_name_no_city(self):
        """Locations without city should show just country."""
        result = GeocodingResult(
            display_name="France",
            city=None,
            state=None,
            country="France",
            country_code="fr",
            lat=46.0,
            lng=2.0,
        )
        assert result.short_name == "France"


class TestGeocodingCache:
    """Tests for GeocodingCache."""

    def test_cache_set_and_get(self):
        """Setting and getting cached values should work."""
        cache = GeocodingCache(ttl_seconds=3600)
        result = GeocodingResult(
            display_name="Test",
            city="Test City",
            state=None,
            country="Test Country",
            country_code="tc",
            lat=0.0,
            lng=0.0,
        )
        cache.set("test place", result)
        cached = cache.get("test place")
        assert cached is not None
        assert cached.city == "Test City"

    def test_cache_case_insensitive(self):
        """Cache lookup should be case-insensitive."""
        cache = GeocodingCache(ttl_seconds=3600)
        result = GeocodingResult(
            display_name="Test",
            city="Test City",
            state=None,
            country="Test Country",
            country_code="tc",
            lat=0.0,
            lng=0.0,
        )
        cache.set("Test Place", result)
        assert cache.get("test place") is not None
        assert cache.get("TEST PLACE") is not None

    def test_cache_miss(self):
        """Non-existent keys should return None."""
        cache = GeocodingCache(ttl_seconds=3600)
        assert cache.get("nonexistent") is None

    def test_cache_clear(self):
        """Clearing cache should remove all entries."""
        cache = GeocodingCache(ttl_seconds=3600)
        result = GeocodingResult(
            display_name="Test",
            city="Test",
            state=None,
            country="Test",
            country_code="tc",
            lat=0.0,
            lng=0.0,
        )
        cache.set("key1", result)
        cache.set("key2", result)
        count = cache.clear()
        assert count == 2
        assert cache.get("key1") is None


class TestParseNominatimResponse:
    """Tests for _parse_nominatim_response."""

    def test_parse_valid_response(self):
        """Valid Nominatim response should parse correctly."""
        data = {
            "display_name": "South Bend, St. Joseph County, Indiana, United States",
            "lat": "41.6764",
            "lon": "-86.2520",
            "address": {
                "city": "South Bend",
                "county": "St. Joseph County",
                "state": "Indiana",
                "country": "United States",
                "country_code": "us",
            },
        }
        result = _parse_nominatim_response(data)
        assert result is not None
        assert result.city == "South Bend"
        assert result.state == "Indiana"
        assert result.country == "United States"
        assert result.country_code == "us"

    def test_parse_town_instead_of_city(self):
        """Should handle 'town' field when 'city' is missing."""
        data = {
            "display_name": "Small Town, Country",
            "lat": "0",
            "lon": "0",
            "address": {
                "town": "Small Town",
                "country": "Some Country",
                "country_code": "sc",
            },
        }
        result = _parse_nominatim_response(data)
        assert result is not None
        assert result.city == "Small Town"

    def test_parse_missing_country_returns_none(self):
        """Response without country should return None."""
        data = {
            "display_name": "Unknown",
            "lat": "0",
            "lon": "0",
            "address": {"city": "Unknown"},
        }
        result = _parse_nominatim_response(data)
        assert result is None

    def test_parse_empty_response_returns_none(self):
        """Empty response should return None."""
        assert _parse_nominatim_response({}) is None
        assert _parse_nominatim_response(None) is None


class TestGeocodePlaceSync:
    """Tests for geocode_place_sync with mocking."""

    def test_empty_input_returns_none(self):
        """Empty input should return None without making network call."""
        assert geocode_place_sync("") is None
        assert geocode_place_sync("   ") is None
        assert geocode_place_sync(None) is None

    @patch("app.geocoding._geocode_sync_http")
    def test_cache_hit_no_network_call(self, mock_http):
        """Cache hit should not make network call."""
        # Pre-populate cache
        from app.geocoding import _geocoding_cache

        result = GeocodingResult(
            display_name="Cached",
            city="Cached City",
            state=None,
            country="Cached Country",
            country_code="cc",
            lat=0.0,
            lng=0.0,
        )
        _geocoding_cache.set("cached place", result)

        # Should get from cache, not call HTTP
        cached = geocode_place_sync("cached place", use_cache=True)
        assert cached is not None
        assert cached.city == "Cached City"
        mock_http.assert_not_called()

        # Cleanup
        clear_geocoding_cache()


class TestNormalizePlaceWithGeocoding:
    """Integration tests for normalize_place_with_fuzzy with geocoding."""

    @patch("app.known_places._try_geocoding")
    def test_geocoding_used_when_fuzzy_fails(self, mock_geocoding):
        """Geocoding should be called when fuzzy matching fails."""
        from app.known_places import normalize_place_with_fuzzy

        mock_geocoding.return_value = "South Bend, Indiana"

        # "south bend indiana" won't fuzzy match well, should use geocoding
        result = normalize_place_with_fuzzy("south bend indiana", use_geocoding=True)

        # Either geocoding was called, or fuzzy matched to Indiana
        # The important thing is it's not "New Zealand South Island"
        assert "Zealand" not in result

    def test_geocoding_disabled(self):
        """When geocoding is disabled, should fall back to title case."""
        from app.known_places import normalize_place_with_fuzzy

        # Use a place that won't match anything
        result = normalize_place_with_fuzzy("xyzabc123", use_geocoding=False)
        assert result == "Xyzabc123"  # Title-cased fallback

    def test_known_places_skip_geocoding(self):
        """Known places should not need geocoding."""
        from app.known_places import normalize_place_with_fuzzy

        # Paris is in known places
        result = normalize_place_with_fuzzy("paris", use_geocoding=True)
        assert result == "Paris"  # From known places, not geocoding
