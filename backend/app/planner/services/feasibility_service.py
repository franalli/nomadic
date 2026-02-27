"""Feasibility checking service for specialist activities.

LLM-backed geographic feasibility checks with caching.
Determines if an activity (diving, skiing, etc.) is possible at a destination.

Extracted from vertical_specialist.py to reduce node file size.
"""

import asyncio
from typing import Tuple

from pydantic import BaseModel

from app.config import settings
from app.planner.hashing import make_cache_key
from app.planner.llm_factory import resolve_schema_refs, strip_unsupported_schema_keys
from app.planner.specialist_registry import get as get_specialist_config
from app.services.cache_core import MemoryCache


class FeasibilityCheck(BaseModel):
    """LLM response for feasibility check."""

    possible: bool
    reason: str


# Pre-resolved flat schema for Gemini-compatible structured output.
_FEASIBILITY_FLAT_SCHEMA: dict = strip_unsupported_schema_keys(
    resolve_schema_refs(FeasibilityCheck.model_json_schema())
)


async def _check_feasibility_llm(topic: str, destination: str) -> FeasibilityCheck:
    """
    LLM determines if activity is geographically possible.

    Uses structured output for reliable parsing (no manual JSON stripping).
    Falls open on error (assumes possible) to avoid false negatives.
    """
    from app.debug_utils import _debug_log

    try:
        from app.planner.llm_factory import get_llm_by_model

        llm = get_llm_by_model(
            settings.router_model,  # Quick feasibility check
            temperature=0,
            max_tokens=100,
        )

        structured_llm = llm.with_structured_output(
            dict(_FEASIBILITY_FLAT_SCHEMA), include_raw=True, method="function_calling"
        )

        prompt = f"""Is {topic} activity possible in {destination}?

Rules:
- Diving requires coastline, large lakes, or dedicated dive facilities
- Skiing requires mountains with reliable snow or indoor ski facilities
- Hiking requires terrain suitable for walking trails
- Surfing requires ocean waves

Be strict. Landlocked cities cannot have diving. Alpine towns without coast cannot have diving."""

        result = await structured_llm.ainvoke(prompt)
        if isinstance(result, dict) and "parsed" in result:
            parsed = result["parsed"]
            if parsed is None:
                raise ValueError(f"Structured output returned None for {topic} in {destination}")
        elif hasattr(result, "model_fields"):
            parsed = result
        else:
            raise ValueError(f"Unexpected structured output type: {type(result).__name__}")

        # Rehydrate dict → Pydantic (Gemini returns dict when using dict schema)
        if isinstance(parsed, dict):
            parsed = FeasibilityCheck.model_validate(parsed)

        _debug_log(
            f"[FEASIBILITY_LLM] {topic} in {destination}: "
            f"possible={parsed.possible}, reason={parsed.reason}"
        )
        return parsed

    except Exception as e:
        _debug_log(f"[FEASIBILITY_LLM] Error checking {topic} in {destination}: {e}")
        # Fail open - assume possible if LLM fails
        return FeasibilityCheck(possible=True, reason="Unknown, proceeding")


# Thread-safe feasibility cache (24h TTL, 256 entries max)
_feasibility_cache: MemoryCache = MemoryCache(maxsize=256, ttl=86400)
_feasibility_inflight: dict[str, asyncio.Future] = {}


def cancel_feasibility_inflight() -> int:
    """Cancel all inflight feasibility futures. Returns count cancelled."""
    count = 0
    for _key, fut in list(_feasibility_inflight.items()):
        if not fut.done():
            fut.cancel()
            count += 1
    _feasibility_inflight.clear()
    return count


async def get_feasibility_llm(topic: str, destination: str) -> Tuple[bool, str]:
    """
    Cached LLM feasibility check with singleflight deduplication.

    Cache key: f"feasibility:v2:{topic}:{destination}"
    Returns: (possible, reason)
    """
    cache_key = make_cache_key("feasibility", "v2", topic, destination)

    cached = _feasibility_cache.get(cache_key)
    if cached is not None:
        return cached

    if cache_key in _feasibility_inflight:
        return await _feasibility_inflight[cache_key]

    # Skip dedup under pressure to avoid unbounded memory growth
    if len(_feasibility_inflight) > 200:
        result = await _check_feasibility_llm(topic, destination)
        pair = (result.possible, result.reason)
        _feasibility_cache.set(cache_key, pair)
        return pair

    # No await between here and registering the future — asyncio's cooperative
    # scheduling makes this check-and-set atomic. If you add an await here,
    # two coroutines can both pass the check above and fire duplicate LLM calls.
    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()
    _feasibility_inflight[cache_key] = future
    try:
        result = await _check_feasibility_llm(topic, destination)
        cached_result = (result.possible, result.reason)
        _feasibility_cache.set(cache_key, cached_result)
        future.set_result(cached_result)
        return cached_result
    except Exception as e:
        future.set_exception(e)
        raise
    finally:
        _feasibility_inflight.pop(cache_key, None)


async def check_feasibility(
    topic: str,
    destination: str,
) -> tuple:
    """
    LLM-only feasibility check, gated by registry has_geographic_constraint flag.

    Returns:
        (status, reason, alternative_suggestion) tuple where:
        - status: "feasible" | "caveat" | "infeasible"
        - reason: Human-readable explanation (or None)
        - alternative_suggestion: Suggested alternative (or None)
    """
    from app.debug_utils import _debug_log

    if not (destination or "").strip():
        return ("feasible", None, None)

    config = get_specialist_config(topic)
    if not config or not config.has_geographic_constraint:
        return ("feasible", None, None)

    # All feasibility decisions delegated to LLM
    _debug_log(f"[FEASIBILITY] LLM check for {topic} in {destination}")
    possible, reason = await get_feasibility_llm(topic, destination)

    if not possible:
        return (
            "infeasible",
            f"{topic.title()} is not available in {destination}. {reason}",
            reason,  # LLM provides alternatives in reason text
        )

    if "limited" in reason.lower():
        return ("caveat", reason, None)

    return ("feasible", None, None)
