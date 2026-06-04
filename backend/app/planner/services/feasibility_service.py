"""Feasibility checking service for specialist activities.

LLM-backed geographic feasibility checks with caching.
Determines if an activity (diving, skiing, etc.) is possible at a destination.

Extracted from vertical_specialist.py to reduce node file size.
"""

import asyncio
from typing import Tuple

from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from app.config import settings
from app.planner.hashing import make_cache_key
from app.planner.llm_factory import (
    gemini_safe_schema,
    resolve_schema_refs,
    strip_unsupported_schema_keys,
)
from app.planner.specialist_registry import SPECIALIST_REGISTRY
from app.planner.specialist_registry import get as get_specialist_config
from app.services.cache_core import MemoryCache


class FeasibilityCheck(BaseModel):
    """LLM response for feasibility check."""

    possible: bool
    reason: str


# Pre-resolved flat schema for Gemini-compatible structured output.
_FEASIBILITY_FLAT_SCHEMA: dict = gemini_safe_schema(
    strip_unsupported_schema_keys(resolve_schema_refs(FeasibilityCheck.model_json_schema()))
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

        all_rules = [
            f"- {cfg.geographic_rule}"
            for cfg in SPECIALIST_REGISTRY.values()
            if cfg.geographic_rule
        ]
        rules_block = "\n".join(all_rules) if all_rules else "Use geographic common sense."

        prompt = f"""Is {topic} activity possible in {destination}?

Rules:
{rules_block}

Be strict."""

        result = await structured_llm.ainvoke([HumanMessage(content=prompt)])
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
_feasibility_inflight_lock: asyncio.Lock = asyncio.Lock()


async def cancel_feasibility_inflight() -> int:
    """Cancel all inflight feasibility futures. Returns count cancelled."""
    async with _feasibility_inflight_lock:
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

    # L2: database cache (survives process restarts)
    try:
        from app.db import _get_async_session_factory
        from app.services.specialist_cache import get_cached_specialist_output

        async_session_factory = _get_async_session_factory()
        async with async_session_factory() as cache_db:
            l2_payload = await get_cached_specialist_output(
                cache_db,
                topic=f"feasibility:{topic}",
                destination=destination,
                start_date=None,
                end_date=None,
                skill_level=None,
                day_pref=None,
            )
        if l2_payload and isinstance(l2_payload, dict):
            pair = (l2_payload.get("possible", True), l2_payload.get("reason", ""))
            _feasibility_cache.set(cache_key, pair)
            return pair
    except Exception:
        pass  # L2 miss or error — fall through to LLM

    owner = False
    future: asyncio.Future | None = None

    async with _feasibility_inflight_lock:
        if cache_key in _feasibility_inflight:
            future = _feasibility_inflight[cache_key]
        elif len(_feasibility_inflight) > 200:
            # Skip dedup under pressure to avoid unbounded memory growth
            future = None
        else:
            loop = asyncio.get_running_loop()
            future = loop.create_future()
            _feasibility_inflight[cache_key] = future
            owner = True

    # Pressure bypass: no dedup, call LLM directly
    if future is None:
        result = await _check_feasibility_llm(topic, destination)
        pair = (result.possible, result.reason)
        _feasibility_cache.set(cache_key, pair)
        return pair

    # Non-owner: just await the shared future
    if not owner:
        return await future

    # Owner: perform the LLM call and resolve the shared future
    try:
        result = await _check_feasibility_llm(topic, destination)
        cached_result = (result.possible, result.reason)
        _feasibility_cache.set(cache_key, cached_result)
        # L2 write (best-effort)
        try:
            from app.db import _get_async_session_factory
            from app.services.specialist_cache import set_cached_specialist_output

            _sf = _get_async_session_factory()
            async with _sf() as _db:
                await set_cached_specialist_output(
                    _db,
                    topic=f"feasibility:{topic}",
                    destination=destination,
                    start_date=None,
                    end_date=None,
                    output={"possible": result.possible, "reason": result.reason},
                    skill_level=None,
                    day_pref=None,
                )
        except Exception:
            pass
        future.set_result(cached_result)
        return cached_result
    except Exception as e:
        future.set_exception(e)
        raise
    finally:
        async with _feasibility_inflight_lock:
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
