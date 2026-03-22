"""Tests for app.utils.geo — geographic utility functions."""

from app.utils.geo import haversine_km


class TestHaversineKm:
    def test_zero_distance(self) -> None:
        """Same point should return 0."""
        assert haversine_km((0.0, 0.0), (0.0, 0.0)) == 0.0

    def test_known_distance_london_paris(self) -> None:
        """London (51.5074, -0.1278) to Paris (48.8566, 2.3522) is ~343 km."""
        dist = haversine_km((51.5074, -0.1278), (48.8566, 2.3522))
        assert 340.0 < dist < 350.0

    def test_known_distance_new_york_los_angeles(self) -> None:
        """New York (40.7128, -74.0060) to LA (34.0522, -118.2437) is ~3944 km."""
        dist = haversine_km((40.7128, -74.0060), (34.0522, -118.2437))
        assert 3930.0 < dist < 3960.0

    def test_antipodal_points(self) -> None:
        """Opposite sides of Earth should be ~20015 km (half circumference)."""
        dist = haversine_km((0.0, 0.0), (0.0, 180.0))
        assert 20010.0 < dist < 20020.0

    def test_symmetry(self) -> None:
        """Distance A->B should equal B->A."""
        a = (35.6762, 139.6503)  # Tokyo
        b = (-33.8688, 151.2093)  # Sydney
        assert abs(haversine_km(a, b) - haversine_km(b, a)) < 0.001

    def test_short_distance(self) -> None:
        """Two nearby points should give a small distance."""
        # ~1 km apart
        a = (48.8566, 2.3522)
        b = (48.8656, 2.3522)
        dist = haversine_km(a, b)
        assert 0.5 < dist < 1.5

    def test_returns_float(self) -> None:
        result = haversine_km((0.0, 0.0), (1.0, 1.0))
        assert isinstance(result, float)
