"""
Trip Input Validation Module
============================

This module provides lightweight LLM-based validation for trip inputs:
- Origin: Must be a real, valid location (single value only)
- Destinations: Must be real, valid locations (supports multi-destination splitting)
- Vibes: Loosely normalized trip themes/moods

Uses the same LLM as the main planner but with minimal prompts (~10 max tokens)
for fast, cheap responses. Results are cached in a TTL memory cache to avoid
repeated LLM calls for common inputs.
"""

import json
import os
import time
from typing import Any, Literal, Optional

from cachetools import TTLCache
from openai import OpenAI

from app.config import settings

# =============================================================================
# CACHE INITIALIZATION
# =============================================================================

# TTL cache: per-worker, entries expire after validation_cache_ttl seconds
_validation_cache: TTLCache = TTLCache(
    maxsize=settings.validation_cache_size,
    ttl=settings.validation_cache_ttl,
)

# OpenAI client singleton (reused from plan.py pattern)
_openai_client: Optional[OpenAI] = None


def _get_openai_client() -> Optional[OpenAI]:
    """Get or create the singleton OpenAI client instance."""
    global _openai_client

    api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    if _openai_client is None:
        _openai_client = OpenAI(api_key=api_key)

    return _openai_client


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

_VIBE_PROMPT = """Validate "{value}" as trip interest(s)/activity/purpose/feature. Return JSON only.
Single vibe: {{"v":["the normalized value"],"e":"relevant emoji","ok":true}}
Multiple vibes: {{"v":["vibe1","vibe2"],"e":["emoji1","emoji2"],"ok":true}}
Invalid: {{"v":[],"ok":false,"r":"reason"}}
If input contains multiple vibes (e.g. "beach and hiking", "food, culture"), split them.
Accept any real activity: backpacking, sports, events, cuisine, culture, music, shows, nature.
Normalize abbreviations: f1->Formula 1, foodie->food.
Always include "e" with relevant emoji(s) (e.g. 🏖️ for beach, 🎒 for backpacking, 🏎️ for Formula 1).
Reject: offensive content, fictional/impossible activities, random nonsense words."""


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
    client = _get_openai_client()
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
    field_type: Literal["origin", "destination", "vibe"],
) -> ValidationResult:
    """
    Validate a trip input value.

    Checks cache first, then calls LLM if not cached. Only caches valid results.

    Args:
        value: The raw input value to validate.
        field_type: Type of input ("origin", "destination", or "vibe").

    Returns:
        ValidationResult with corrected values, validity flag, and optional reason.

    Raises:
        RuntimeError: If LLM call fails after all retries.
    """
    # Normalize input
    normalized_value = value.strip()
    if not normalized_value:
        return ValidationResult(
            corrected_values=[],
            is_valid=False,
            reason="Empty input",
        )

    # Check cache
    cache_key = _cache_key(field_type, normalized_value)
    cached = _validation_cache.get(cache_key)
    if cached is not None:
        return ValidationResult(**cached)

    # Build prompt based on field type
    if field_type in ("origin", "destination"):
        prompt = _LOCATION_PROMPT.format(
            field_type=field_type,
            value=normalized_value,
        )
    else:  # vibe
        prompt = _VIBE_PROMPT.format(
            value=normalized_value,
        )

    # Call LLM
    llm_response = _call_llm_validation(prompt)

    if llm_response is None:
        raise RuntimeError(f"Validation failed for {field_type}: {normalized_value}")

    # Parse response
    corrected_values = llm_response.get("v", [])
    if not isinstance(corrected_values, list):
        corrected_values = [corrected_values] if corrected_values else []
    corrected_values = [str(v).strip() for v in corrected_values if v]

    is_valid = llm_response.get("ok", False)
    reason = llm_response.get("r") or llm_response.get("reason")

    # For vibes, prepend emoji to each value
    if field_type == "vibe" and corrected_values and is_valid:
        emojis_raw = llm_response.get("e", "✨")
        # Handle emoji as list or single string
        if isinstance(emojis_raw, list):
            emojis = [
                str(e).strip()[:2] if len(str(e).strip()) >= 2 else str(e).strip()[:1]
                for e in emojis_raw
            ]
            # Pad with default if fewer emojis than vibes
            while len(emojis) < len(corrected_values):
                emojis.append("✨")
        else:
            # Single emoji for all vibes
            emoji = str(emojis_raw).strip() if emojis_raw else "✨"
            emoji = emoji[:2] if len(emoji) >= 2 else emoji[:1]
            if not emoji:
                emoji = "✨"
            emojis = [emoji] * len(corrected_values)
        # Prepend emoji to each corrected value
        corrected_values = [f"{emojis[i]} {v}" for i, v in enumerate(corrected_values)]

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
        _validation_cache[cache_key] = result.to_dict()

    return result


# =============================================================================
# CACHE MANAGEMENT
# =============================================================================


def prewarm_cache() -> int:
    """
    Pre-populate the cache with common destinations and vibes.

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

    # Common vibes with emojis (~20 popular themes)
    common_vibes = [
        ("beach", "🏖️"),
        ("adventure", "🎒"),
        ("romantic", "💕"),
        ("relaxation", "😌"),
        ("culture", "🏛️"),
        ("food", "🍽️"),
        ("nightlife", "🌃"),
        ("nature", "🌿"),
        ("history", "📜"),
        ("luxury", "💎"),
        ("budget", "💰"),
        ("family", "👨‍👩‍👧‍👦"),
        ("solo", "🚶"),
        ("honeymoon", "💒"),
        ("wellness", "🧘"),
        ("spa", "💆"),
        ("hiking", "🥾"),
        ("diving", "🤿"),
        ("skiing", "⛷️"),
        ("shopping", "🛍️"),
    ]

    count = 0

    # Pre-populate destinations (valid for both origin and destination)
    for dest in common_destinations:
        for field_type in ("origin", "destination"):
            cache_key = _cache_key(field_type, dest)
            if cache_key not in _validation_cache:
                _validation_cache[cache_key] = {
                    "corrected_values": [dest],
                    "is_valid": True,
                    "reason": None,
                }
                count += 1

    # Pre-populate vibes with emojis
    for vibe, emoji in common_vibes:
        cache_key = _cache_key("vibe", vibe)
        if cache_key not in _validation_cache:
            _validation_cache[cache_key] = {
                "corrected_values": [f"{emoji} {vibe}"],
                "is_valid": True,
                "reason": None,
            }
            count += 1

    return count


def clear_cache() -> int:
    """
    Clear the validation cache.

    Returns the number of entries that were cleared.
    """
    count = len(_validation_cache)
    _validation_cache.clear()
    return count


def get_cache_stats() -> dict[str, Any]:
    """Get cache statistics for debugging."""
    return {
        "size": len(_validation_cache),
        "maxsize": _validation_cache.maxsize,
        "ttl": _validation_cache.ttl,
    }
