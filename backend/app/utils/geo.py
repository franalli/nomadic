"""Shared geographic utilities."""

import math


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Return the great-circle distance in km between two (lat, lng) points."""
    lat1, lng1 = a
    lat2, lng2 = b
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    )
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(h)))
