"""
Trip Input Validation Module
============================

This module provides lightweight LLM-based validation for trip inputs:
- Origin: Must be a real, valid location (single value only)
- Destinations: Must be real, valid locations (supports multi-destination splitting)

Uses the same LLM as the main planner but with minimal prompts (~10 max tokens)
for fast, cheap responses. Results are cached in a TTL memory cache to avoid
repeated LLM calls for common inputs.

Cache infrastructure lives in validation_cache.py.
"""

import asyncio
import logging
import random
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.config import settings
from app.planner.llm_factory import get_llm_by_model
from app.validation_cache import (
    _build_prompt,
    _check_rate_limit,
    cache_stats,  # noqa: F401 — re-exported for external callers
    clear_cache,  # noqa: F401 — re-exported for external callers
    lookup_cache,
    lookup_fallback,
    prewarm_cache,  # noqa: F401 — re-exported for external callers
    store_result,
)

logger = logging.getLogger(__name__)


class ValidationResponse(BaseModel):
    """Pydantic schema for LLM validation output — enforced via structured output."""

    v: list[str] = Field(default_factory=list, description="Corrected place name(s)")
    ok: bool = Field(description="Whether the input is a valid location")
    r: Optional[str] = Field(default=None, description="Reason if invalid")


def _get_model_name() -> str:
    """Get the model name for validation (Guard node)."""
    return settings.guard_model


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


async def _call_llm_validation_async(
    prompt: str,
    max_retries: int = 3,
) -> Optional[dict]:
    """
    Call the LLM for validation with structured output and async retry logic.

    Uses LangChain with_structured_output(ValidationResponse) to enforce
    Pydantic schema for both OpenAI and Gemini providers.

    Args:
        prompt: The validation prompt.
        max_retries: Number of retry attempts.

    Returns:
        Parsed JSON dict from LLM, or None if all retries failed.
    """
    from langchain_core.messages import HumanMessage

    model_name = _get_model_name()
    last_error: Optional[Exception] = None

    initial_delay = 0.5
    max_delay = 10.0

    for attempt in range(max_retries):
        try:
            llm = get_llm_by_model(
                model_name,
                temperature=0,
                max_tokens=settings.validation_max_tokens,
            )
            structured_llm = llm.with_structured_output(ValidationResponse)
            result = await structured_llm.ainvoke([HumanMessage(content=prompt)])
            return result.model_dump()

        except Exception as exc:
            last_error = exc
            status_code = getattr(exc, "status_code", None)
            if status_code == 429 or (isinstance(status_code, int) and status_code >= 500):
                wait_time = min(initial_delay * (2**attempt), max_delay) + random.uniform(0, 1)
                await asyncio.sleep(wait_time)
                continue
            raise

    if last_error:
        raise last_error
    return None


# =============================================================================
# PUBLIC VALIDATION FUNCTIONS
# =============================================================================


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
    rate_limit_reason = await _check_rate_limit(session_id)
    if rate_limit_reason:
        return ValidationResult(
            corrected_values=[],
            is_valid=False,
            reason=rate_limit_reason,
        )

    # Check cache
    cached = await lookup_cache(field_type, normalized_value)
    if cached is not None:
        return ValidationResult(**cached)

    # Build prompt
    prompt = await _build_prompt(field_type, normalized_value, _LOCATION_PROMPT)

    # Tier 11.1: Use async LLM call with non-blocking retries
    llm_response = await _call_llm_validation_async(prompt)

    if llm_response is None:
        fallback = await lookup_fallback(field_type, normalized_value)
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

    # Cache the result
    await store_result(field_type, normalized_value, result.to_dict(), is_valid, reason)

    return result
