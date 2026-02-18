"""Feasibility checking service for specialist activities.

LLM-backed geographic feasibility checks with caching.
Determines if an activity (diving, skiing, etc.) is possible at a destination.

Extracted from vertical_specialist.py to reduce node file size.
"""

import asyncio
import json
from typing import Tuple

from pydantic import BaseModel

from app.config import settings
from app.planner.hashing import make_cache_key
from app.planner.specialist_registry import get as get_specialist_config
from app.services.cache_core import MemoryCache


class FeasibilityCheck(BaseModel):
    """LLM response for feasibility check."""

    possible: bool
    reason: str


async def _check_feasibility_llm(topic: str, destination: str) -> FeasibilityCheck:
    """
    LLM determines if activity is geographically possible.

    Uses GPT-4o-mini for fast, cheap checks (~$0.0001, ~200ms).
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

        prompt = f"""Is {topic} activity possible in {destination}?

Rules:
- Diving requires coastline, large lakes, or dedicated dive facilities
- Skiing requires mountains with reliable snow or indoor ski facilities
- Hiking requires terrain suitable for walking trails
- Surfing requires ocean waves

Be strict. Landlocked cities cannot have diving. Alpine towns without coast cannot have diving.

Respond JSON only: {{"possible": true/false, "reason": "brief"}}"""

        response = await llm.ainvoke(prompt)
        content = response.content.strip()

        # Parse JSON response
        # Handle potential markdown code blocks
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        result = FeasibilityCheck(**json.loads(content))
        _debug_log(
            f"[FEASIBILITY_LLM] {topic} in {destination}: "
            f"possible={result.possible}, reason={result.reason}"
        )
        return result

    except Exception as e:
        _debug_log(f"[FEASIBILITY_LLM] Error checking {topic} in {destination}: {e}")
        # Fail open - assume possible if LLM fails
        return FeasibilityCheck(possible=True, reason="Unknown, proceeding")


# Thread-safe feasibility cache (24h TTL, 256 entries max)
_feasibility_cache: MemoryCache = MemoryCache(maxsize=256, ttl=86400)
_feasibility_inflight: dict[str, asyncio.Future] = {}


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
