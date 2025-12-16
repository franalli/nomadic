"""
Trip Input Validation Module
============================

This module provides lightweight LLM-based validation for trip inputs:
- Origin: Must be a real, valid location (single value only)
- Destinations: Must be real, valid locations (supports multi-destination splitting)

Uses the same LLM as the main planner but with minimal prompts (~10 max tokens)
for fast, cheap responses. Results are cached in a TTL memory cache to avoid
repeated LLM calls for common inputs.
"""

import json
import os
import time
from math import atan2, cos, radians, sin, sqrt
from typing import Any, Literal, Optional

from cachetools import TTLCache

from app.config import get_openai_client, settings

# =============================================================================
# CACHE INITIALIZATION
# =============================================================================

# TTL cache: per-worker, entries expire after validation_cache_ttl seconds
_validation_cache: TTLCache = TTLCache(
    maxsize=settings.validation_cache_size,
    ttl=settings.validation_cache_ttl,
)
_negative_cache: TTLCache = TTLCache(
    maxsize=settings.validation_negative_cache_size,
    ttl=settings.validation_negative_cache_ttl,
)
# Split cache stores destination splits so repeat requests skip LLM parsing.
_split_cache: TTLCache = TTLCache(
    maxsize=settings.validation_split_cache_size,
    ttl=settings.validation_cache_ttl,
)
# Prompt cache avoids repeatedly formatting identical prompts.
_prompt_cache: TTLCache = TTLCache(
    maxsize=settings.validation_prompt_cache_size,
    ttl=settings.validation_cache_ttl,
)
# Fallback cache returns the last known good answer if the live call fails.
_fallback_cache: TTLCache = TTLCache(
    maxsize=settings.validation_fallback_cache_size,
    ttl=settings.validation_cache_ttl,
)
# Per-session counters provide a lightweight request budget.
_rate_counter_cache: TTLCache = TTLCache(
    maxsize=10_000,
    ttl=settings.validation_rate_limit_window,
)


def _get_model_name() -> str:
    """Get the OpenAI model name (same as planner)."""
    model_name = os.getenv("OPENAI_PLAN_MODEL", "").strip()
    if not model_name:
        raise RuntimeError("OPENAI_PLAN_MODEL is required for validation")
    return model_name


# =============================================================================
# VALIDATION RESULT TYPE
# =============================================================================


class ValidationResult:
    """
    Result of validating a trip input.

    Attributes:
        corrected_values: List of corrected/normalized values. For origin, always
                          a single item. For destinations, may be multiple if the
                          input was split (e.g., "Paris and Rome" -> ["Paris", "Rome"]).
        is_valid: True if the input is valid (possibly after correction).
        reason: Human-readable explanation if invalid or corrected.
    """

    def __init__(
        self,
        *,
        corrected_values: list[str],
        is_valid: bool,
        reason: Optional[str] = None,
    ) -> None:
        self.corrected_values = corrected_values
        self.is_valid = is_valid
        self.reason = reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "corrected_values": self.corrected_values,
            "is_valid": self.is_valid,
            "reason": self.reason,
        }


# =============================================================================
# CACHE KEY GENERATION
# =============================================================================


def _cache_key(field_type: str, value: str) -> str:
    """Generate a cache key from field type and normalized value."""
    normalized = value.strip().lower()
    return f"{field_type}:{normalized}"


def _build_prompt(field_type: str, normalized_value: str) -> str:
    """Render or reuse the minimal validation prompt."""
    cache_key = _cache_key(field_type, normalized_value)
    cached_prompt = _prompt_cache.get(cache_key)
    if cached_prompt is not None:
        return cached_prompt

    prompt = _LOCATION_PROMPT.format(
        field_type=field_type,
        value=normalized_value,
    )
    _prompt_cache[cache_key] = prompt
    return prompt


def _check_rate_limit(session_id: Optional[str]) -> Optional[str]:
    """Increment per-session validation counter; return reason if exceeded."""
    if not settings.validation_rate_limit_enabled or not session_id:
        return None

    count = _rate_counter_cache.get(session_id, 0) + 1
    _rate_counter_cache[session_id] = count

    if count > settings.validation_rate_limit_max_requests:
        return "Too many validation attempts. Please try again later."
    return None


# =============================================================================
# LLM VALIDATION CALLS
# =============================================================================

# Minimal prompts for validation
_LOCATION_PROMPT = """Validate "{value}" as a travel {field_type}. Return JSON only.
Valid place: {{"v":["Corrected Name"],"ok":true}}
Multiple places: {{"v":["Place1","Place2"],"ok":true}}
Invalid: {{"v":[],"ok":false,"r":"reason"}}
Correct misspellings to real places (Sydny->Sydney, vinna -> Vienna, Barselonaa->Barcelona).
Expand abbreviations (NYC->New York City, SF->San Francisco, LA->Los Angeles).
Reject fictional or non-existent places."""


def _call_llm_validation(
    prompt: str,
    *,
    max_retries: int = 3,
) -> Optional[dict]:
    """
    Call LLM with a minimal validation prompt.

    Uses fixed-delay retries (not exponential) for simplicity.

    Args:
        prompt: The validation prompt.
        max_retries: Number of retry attempts.

    Returns:
        Parsed JSON dict from LLM, or None if all retries failed.
    """
    client = get_openai_client()
    if client is None:
        return None

    model_name = _get_model_name()
    last_error: Optional[Exception] = None

    for _attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=settings.validation_max_tokens,
                temperature=0,  # Deterministic for validation
                response_format={"type": "json_object"},
            )

            if response and response.choices:
                content = response.choices[0].message.content
                if content:
                    return json.loads(content)

        except Exception as exc:
            last_error = exc
            status_code = getattr(exc, "status_code", None)
            # Retry on rate limit or server errors
            if status_code == 429 or (isinstance(status_code, int) and status_code >= 500):
                time.sleep(0.5)  # Fixed delay
                continue
            raise

    if last_error:
        raise last_error
    return None


# =============================================================================
# PUBLIC VALIDATION FUNCTIONS
# =============================================================================


def validate_input(
    value: str,
    field_type: Literal["origin", "destination"],
    *,
    session_id: Optional[str] = None,
) -> ValidationResult:
    """
    Validate a trip input value.

    Checks cache first (positive, negative, split), enforces a lightweight
    per-session rate limit, then calls LLM if not cached. Only caches valid
    results long-term; invalid responses land in a short-TTL negative cache.

    Args:
        value: The raw input value to validate.
        field_type: Type of input ("origin" or "destination").
        session_id: Optional session token for rate limiting.

    Returns:
        ValidationResult with corrected values, validity flag, and optional reason.

    Raises:
        RuntimeError: If LLM call fails after all retries.
    """
    # Normalize input (cache keys remain case-insensitive)
    normalized_value = value.strip()
    if not normalized_value:
        return ValidationResult(
            corrected_values=[],
            is_valid=False,
            reason="Empty input",
        )

    # Lightweight per-session rate limiting (short TTL window)
    rate_limit_reason = _check_rate_limit(session_id)
    if rate_limit_reason:
        return ValidationResult(
            corrected_values=[],
            is_valid=False,
            reason=rate_limit_reason,
        )

    # Check cache
    cache_key = _cache_key(field_type, normalized_value)
    cached = _validation_cache.get(cache_key)
    if cached is not None:
        return ValidationResult(**cached)

    if settings.validation_negative_cache_enabled:
        negative_reason = _negative_cache.get(cache_key)
        if negative_reason is not None:
            return ValidationResult(
                corrected_values=[],
                is_valid=False,
                reason=negative_reason,
            )

    # Destination splitting cache (case-insensitive key)
    split_key = normalized_value.lower()
    if field_type == "destination":
        split_cached = _split_cache.get(split_key)
        if split_cached is not None:
            return ValidationResult(**split_cached)

    # Build prompt based on field type
    prompt = _build_prompt(field_type, normalized_value)

    # Call LLM
    llm_response = _call_llm_validation(prompt)

    if llm_response is None:
        fallback = _fallback_cache.get(cache_key)
        if fallback is not None:
            return ValidationResult(**fallback)
        raise RuntimeError(f"Validation failed for {field_type}: {normalized_value}")

    # Parse response
    corrected_values = llm_response.get("v", [])
    if not isinstance(corrected_values, list):
        corrected_values = [corrected_values] if corrected_values else []
    corrected_values = [str(v).strip() for v in corrected_values if v]

    is_valid = llm_response.get("ok", False)
    reason = llm_response.get("r") or llm_response.get("reason")

    # For origin, enforce single value
    if field_type == "origin" and len(corrected_values) > 1:
        # Take the first one, user needs to pick a single origin
        corrected_values = corrected_values[:1]
        reason = "Please enter a single origin location"

    result = ValidationResult(
        corrected_values=corrected_values,
        is_valid=is_valid,
        reason=reason,
    )

    # Cache only valid results (typos should be re-validated)
    if is_valid:
        result_dict = result.to_dict()
        _validation_cache[cache_key] = result_dict
        _fallback_cache[cache_key] = result_dict

        if field_type == "destination" and len(result.corrected_values) > 1:
            _split_cache[split_key] = result_dict
    elif settings.validation_negative_cache_enabled:
        _negative_cache[cache_key] = reason or "Invalid input"

    return result


# =============================================================================
# CACHE MANAGEMENT
# =============================================================================


def prewarm_cache() -> int:
    """
    Pre-populate the cache with common destinations.

    Called on server startup. Returns the number of entries added.
    """
    # Common destinations (top ~50 cities)
    common_destinations = [
        "Paris",
        "London",
        "New York City",
        "Tokyo",
        "Rome",
        "Barcelona",
        "Amsterdam",
        "Dubai",
        "Singapore",
        "Hong Kong",
        "Los Angeles",
        "San Francisco",
        "Miami",
        "Las Vegas",
        "Chicago",
        "Sydney",
        "Melbourne",
        "Bangkok",
        "Bali",
        "Phuket",
        "Berlin",
        "Munich",
        "Vienna",
        "Prague",
        "Budapest",
        "Lisbon",
        "Madrid",
        "Milan",
        "Venice",
        "Florence",
        "Athens",
        "Istanbul",
        "Cairo",
        "Marrakech",
        "Cape Town",
        "Rio de Janeiro",
        "Buenos Aires",
        "Mexico City",
        "Cancun",
        "Toronto",
        "Vancouver",
        "Montreal",
        "Reykjavik",
        "Dublin",
        "Edinburgh",
        "Copenhagen",
        "Stockholm",
        "Oslo",
        "Helsinki",
        "Zurich",
    ]

    count = 0

    # Pre-populate destinations (valid for both origin and destination)
    for dest in common_destinations:
        for field_type in ("origin", "destination"):
            cache_key = _cache_key(field_type, dest)
            if cache_key not in _validation_cache:
                entry = {
                    "corrected_values": [dest],
                    "is_valid": True,
                    "reason": None,
                }
                _validation_cache[cache_key] = entry
                _fallback_cache[cache_key] = entry
                count += 1

    return count


def clear_cache(preserve_rate_limiting: bool = True) -> int:
    """
    Clear all validation caches.

    Args:
        preserve_rate_limiting: If True (default), preserves the rate counter cache
                                to prevent abuse. Set to False only for full system reset.

    Returns the number of entries that were cleared across caches.
    """
    count = (
        len(_validation_cache)
        + len(_negative_cache)
        + len(_split_cache)
        + len(_prompt_cache)
        + len(_fallback_cache)
    )
    _validation_cache.clear()
    _negative_cache.clear()
    _split_cache.clear()
    _prompt_cache.clear()
    _fallback_cache.clear()

    if not preserve_rate_limiting:
        count += len(_rate_counter_cache)
        _rate_counter_cache.clear()

    return count


def cache_stats() -> dict[str, int]:
    """Return a snapshot of validation cache sizes."""
    return {
        "positive": len(_validation_cache),
        "negative": len(_negative_cache),
        "split": len(_split_cache),
        "prompt": len(_prompt_cache),
        "fallback": len(_fallback_cache),
        "rate_counters": len(_rate_counter_cache),
    }


# =============================================================================
# TRAVEL FEASIBILITY VALIDATION
# =============================================================================

# Approximate coordinates for major destinations (for distance calculations)
# This is a simplified version - real implementation would use a geocoding service
_LOCATION_COORDS: dict[str, tuple[float, float]] = {
    # Major cities with approximate lat/lon
    "tokyo": (35.6762, 139.6503),
    "new york": (40.7128, -74.0060),
    "nyc": (40.7128, -74.0060),
    "sydney": (-33.8688, 151.2093),
    "london": (51.5074, -0.1278),
    "paris": (48.8566, 2.3522),
    "dubai": (25.2048, 55.2708),
    "singapore": (1.3521, 103.8198),
    "hong kong": (22.3193, 114.1694),
    "los angeles": (34.0522, -118.2437),
    "san francisco": (37.7749, -122.4194),
    "chicago": (41.8781, -87.6298),
    "toronto": (43.6532, -79.3832),
    "rome": (41.9028, 12.4964),
    "berlin": (52.5200, 13.4050),
    "amsterdam": (52.3676, 4.9041),
    "bangkok": (13.7563, 100.5018),
    "seoul": (37.5665, 126.9780),
    "beijing": (39.9042, 116.4074),
    "mumbai": (19.0760, 72.8777),
    "delhi": (28.7041, 77.1025),
    "cairo": (30.0444, 31.2357),
    "cape town": (-33.9249, 18.4241),
    "rio de janeiro": (-22.9068, -43.1729),
    "buenos aires": (-34.6037, -58.3816),
    "mexico city": (19.4326, -99.1332),
    "moscow": (55.7558, 37.6173),
    "istanbul": (41.0082, 28.9784),
}


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points on Earth in kilometers."""
    R = 6371  # Earth's radius in kilometers

    lat1_rad, lat2_rad = radians(lat1), radians(lat2)
    delta_lat = radians(lat2 - lat1)
    delta_lon = radians(lon2 - lon1)

    a = sin(delta_lat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return R * c


def _estimate_travel_hours(distance_km: float) -> float:
    """Estimate minimum travel hours based on distance (flight + logistics)."""
    if distance_km < 500:
        # Short haul: ~1-2 hours flight + airport time
        return 3
    elif distance_km < 2000:
        # Medium haul: ~3-5 hours flight + airport time
        return 6
    elif distance_km < 6000:
        # Long haul: ~7-12 hours flight + airport time
        return 14
    else:
        # Ultra long haul: may need connection
        return 20


def validate_itinerary_feasibility(
    destinations: list[str],
    days_available: int,
) -> dict[str, Any]:
    """
    Validate if a multi-destination itinerary is feasible within the given days.

    Returns:
        {
            "is_feasible": bool,
            "warning": Optional[str],
            "travel_time_hours": float,
            "min_days_needed": int,
            "details": list[dict]
        }
    """
    if not destinations or len(destinations) < 2:
        return {
            "is_feasible": True,
            "warning": None,
            "travel_time_hours": 0,
            "min_days_needed": 1,
            "details": [],
        }

    total_travel_hours = 0
    details = []

    for i in range(len(destinations) - 1):
        origin = destinations[i].lower().strip()
        dest = destinations[i + 1].lower().strip()

        # Get coordinates
        origin_coords = _LOCATION_COORDS.get(origin)
        dest_coords = _LOCATION_COORDS.get(dest)

        if not origin_coords or not dest_coords:
            # Unknown location - can't calculate, assume feasible
            details.append(
                {
                    "from": destinations[i],
                    "to": destinations[i + 1],
                    "distance_km": None,
                    "travel_hours": None,
                    "note": "Unknown location, cannot estimate travel time",
                }
            )
            continue

        distance = _haversine_distance(
            origin_coords[0], origin_coords[1], dest_coords[0], dest_coords[1]
        )
        travel_hours = _estimate_travel_hours(distance)
        total_travel_hours += travel_hours

        details.append(
            {
                "from": destinations[i],
                "to": destinations[i + 1],
                "distance_km": round(distance),
                "travel_hours": travel_hours,
            }
        )

    # Minimum days needed: travel days + at least 1 day per destination
    travel_days = total_travel_hours / 10  # Assume 10 usable hours per day
    min_days_needed = max(len(destinations), int(travel_days) + len(destinations))

    is_feasible = days_available >= min_days_needed * 0.8  # Allow some flexibility

    warning = None
    if not is_feasible:
        warning = (
            f"This itinerary covers {len(destinations)} destinations requiring approximately "
            f"{round(total_travel_hours)} hours of travel. With {days_available} days available, "
            f"this may be rushed. Consider reducing destinations or extending your trip."
        )
    elif days_available < min_days_needed:
        warning = (
            f"Tight schedule: {days_available} days for {len(destinations)} destinations. "
            f"You'll have limited time at each stop."
        )

    return {
        "is_feasible": is_feasible,
        "warning": warning,
        "travel_time_hours": round(total_travel_hours, 1),
        "min_days_needed": min_days_needed,
        "details": details,
    }
