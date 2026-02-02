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

import asyncio
import json
import logging
import os
import random
import time
from threading import RLock
from typing import Any, Literal, Optional

from cachetools import TTLCache

from app.config import get_async_openai_client, get_openai_client, settings

logger = logging.getLogger(__name__)

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

# Thread-safety lock for all validation caches
# Required because FastAPI may run requests in thread pool executors
_validation_cache_lock = RLock()


def clear_validation_caches() -> int:
    """
    Clear all validation caches.

    This function should be called at the start of each test to ensure
    complete isolation. It clears:
    - _validation_cache: Validated location results
    - _negative_cache: Invalid location results
    - _split_cache: Destination split results
    - _prompt_cache: Formatted prompts
    - _fallback_cache: Fallback responses
    - _rate_counter_cache: Rate limit counters

    Returns the total number of cache entries cleared.
    """
    with _validation_cache_lock:
        total_cleared = (
            len(_validation_cache)
            + len(_negative_cache)
            + len(_split_cache)
            + len(_prompt_cache)
            + len(_fallback_cache)
            + len(_rate_counter_cache)
        )

        _validation_cache.clear()
        _negative_cache.clear()
        _split_cache.clear()
        _prompt_cache.clear()
        _fallback_cache.clear()
        _rate_counter_cache.clear()

    return total_cleared


def _get_model_name() -> str:
    """Get the OpenAI model name for validation (uses settings with fallback)."""
    # Use settings.openai_plan_model which has a default of gpt-4o-mini
    # Also check env vars as override
    model_name = (
        os.getenv("OPENAI_PLAN_MODEL", "").strip()
        or settings.openai_plan_model
        or "gpt-4o-mini"  # Ultimate fallback
    )
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
    with _validation_cache_lock:
        cached_prompt = _prompt_cache.get(cache_key)
        if cached_prompt is not None:
            return cached_prompt

    prompt = _LOCATION_PROMPT.format(
        field_type=field_type,
        value=normalized_value,
    )
    with _validation_cache_lock:
        _prompt_cache[cache_key] = prompt
    return prompt


def _check_rate_limit(session_id: Optional[str]) -> Optional[str]:
    """Increment per-session validation counter; return reason if exceeded."""
    if not settings.validation_rate_limit_enabled or not session_id:
        return None

    with _validation_cache_lock:
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

RULES:
1. VALID: Real cities, regions, or countries on Earth (Paris, Bali, Japan)
2. VALID: Correct misspellings (Sydny->Sydney, Barselonaa->Barcelona)
3. VALID: Expand abbreviations (NYC->New York City, SF->San Francisco)
4. INVALID: Celestial bodies (Moon, Mars, Sun) - reason: "Not a destination on Earth"
5. INVALID: Fictional places (Atlantis, Mordor, Hogwarts) - reason: "Fictional location"
6. INVALID: Too vague (The Beach, Asia, The World) - reason: "Too vague, specify a city or region"
7. INVALID: Nonsense (asdf, 12345) - reason: "Not a recognized location"

Be STRICT: Only return ok:true for real, specific, reachable destinations on Earth."""


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

    initial_delay = 0.5
    max_delay = 10.0

    for attempt in range(max_retries):
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
            # Retry on rate limit or server errors with exponential backoff + jitter
            if status_code == 429 or (isinstance(status_code, int) and status_code >= 500):
                wait_time = min(initial_delay * (2**attempt), max_delay) + random.uniform(0, 1)
                time.sleep(wait_time)
                continue
            raise

    if last_error:
        raise last_error
    return None


# Tier 11.1: Async version with non-blocking sleep for better concurrency
async def _call_llm_validation_async(
    prompt: str,
    max_retries: int = 3,
) -> Optional[dict]:
    """
    Call the LLM for validation with async retry logic.

    Uses asyncio.sleep instead of time.sleep for non-blocking retries.

    Args:
        prompt: The validation prompt.
        max_retries: Number of retry attempts.

    Returns:
        Parsed JSON dict from LLM, or None if all retries failed.
    """
    client = get_async_openai_client()
    if client is None:
        return None

    model_name = _get_model_name()
    last_error: Optional[Exception] = None

    initial_delay = 0.5
    max_delay = 10.0

    for attempt in range(max_retries):
        try:
            response = await client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=settings.validation_max_tokens,
                temperature=0,
                response_format={"type": "json_object"},
            )

            if response and response.choices:
                content = response.choices[0].message.content
                if content:
                    return json.loads(content)

        except Exception as exc:
            last_error = exc
            status_code = getattr(exc, "status_code", None)
            # Tier 11.1: Non-blocking retry with exponential backoff + jitter
            if status_code == 429 or (isinstance(status_code, int) and status_code >= 500):
                wait_time = min(initial_delay * (2**attempt), max_delay) + random.uniform(0, 1)
                await asyncio.sleep(wait_time)  # Non-blocking!
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

    # Check cache (thread-safe)
    cache_key = _cache_key(field_type, normalized_value)
    with _validation_cache_lock:
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
            # Tier 11.5: Log fallback usage for observability
            logger.warning(
                "VALIDATION_LLM_FALLBACK: Using cached fallback for %s=%r "
                "(LLM call failed, cache TTL<%ds)",
                field_type,
                normalized_value,
                settings.validation_cache_ttl,
            )
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
    with _validation_cache_lock:
        if is_valid:
            result_dict = result.to_dict()
            _validation_cache[cache_key] = result_dict
            _fallback_cache[cache_key] = result_dict

            if field_type == "destination" and len(result.corrected_values) > 1:
                _split_cache[split_key] = result_dict
        elif settings.validation_negative_cache_enabled:
            _negative_cache[cache_key] = reason or "Invalid input"

    return result


# Tier 11.1: Async version for better concurrency
async def validate_input_async(
    value: str,
    field_type: Literal["origin", "destination"],
    *,
    session_id: Optional[str] = None,
) -> ValidationResult:
    """
    Async version of validate_input with non-blocking LLM retries.

    Uses asyncio.sleep instead of time.sleep during rate limit retries,
    allowing other requests to be processed while waiting.

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

    # Lightweight per-session rate limiting
    rate_limit_reason = _check_rate_limit(session_id)
    if rate_limit_reason:
        return ValidationResult(
            corrected_values=[],
            is_valid=False,
            reason=rate_limit_reason,
        )

    # Check cache (thread-safe - caches are in-memory)
    cache_key = _cache_key(field_type, normalized_value)
    with _validation_cache_lock:
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

        # Destination splitting cache
        split_key = normalized_value.lower()
        if field_type == "destination":
            split_cached = _split_cache.get(split_key)
            if split_cached is not None:
                return ValidationResult(**split_cached)

    # Build prompt
    prompt = _build_prompt(field_type, normalized_value)

    # Tier 11.1: Use async LLM call with non-blocking retries
    llm_response = await _call_llm_validation_async(prompt)

    if llm_response is None:
        fallback = _fallback_cache.get(cache_key)
        if fallback is not None:
            logger.warning(
                "VALIDATION_LLM_FALLBACK: Using cached fallback for %s=%r "
                "(LLM call failed, cache TTL<%ds)",
                field_type,
                normalized_value,
                settings.validation_cache_ttl,
            )
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
        corrected_values = corrected_values[:1]
        reason = "Please enter a single origin location"

    result = ValidationResult(
        corrected_values=corrected_values,
        is_valid=is_valid,
        reason=reason,
    )

    # Cache only valid results (thread-safe)
    with _validation_cache_lock:
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
    with _validation_cache_lock:
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
    with _validation_cache_lock:
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
    with _validation_cache_lock:
        return {
            "positive": len(_validation_cache),
            "negative": len(_negative_cache),
            "split": len(_split_cache),
            "prompt": len(_prompt_cache),
            "fallback": len(_fallback_cache),
            "rate_counters": len(_rate_counter_cache),
        }
