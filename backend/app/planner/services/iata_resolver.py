"""IATA airport code resolver with state + shared L1/L2 caching."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import _get_async_session_factory
from app.planner.hashing import make_cache_key
from app.planner.llm_factory import (
    get_llm_by_model,
    resolve_schema_refs,
    strip_unsupported_schema_keys,
)
from app.planner.state.graph_state import GraphState
from app.services.cache_core import MemoryCache, l2_upsert

logger = logging.getLogger(__name__)


class IataResponse(BaseModel):
    """LLM response for IATA code resolution."""

    origin: str = Field(default="", description="IATA code for origin city")
    destination: str = Field(default="", description="IATA code for destination city")


# Pre-resolved flat schema for Gemini-compatible structured output.
_IATA_FLAT_SCHEMA: dict = strip_unsupported_schema_keys(
    resolve_schema_refs(IataResponse.model_json_schema())
)

L1_TTL_SECONDS = 24 * 60 * 60  # 24h
L1_MAX_SIZE = 512
L2_TTL_HOURS = 24 * 30  # 30d

_shared_mem = MemoryCache(maxsize=L1_MAX_SIZE, ttl=L1_TTL_SECONDS)


def clear_iata_cache() -> int:
    """Clear shared L1 IATA cache (primarily for tests)."""
    return _shared_mem.clear()


def _normalize_city(city: str) -> str:
    return " ".join(city.lower().strip().split()) if city else ""


def _iata_city_cache_key(city: str, qualifier: str | None = None) -> str:
    normalized_city = _normalize_city(city) or "unknown"
    normalized_qualifier = _normalize_city(qualifier or "") or "unknown"
    return make_cache_key("iata", "v2", normalized_city, normalized_qualifier)


def _get_l1_city_code(city: str, qualifier: str | None = None) -> str | None:
    if not city:
        return None
    cache_key = _iata_city_cache_key(city, qualifier=qualifier)
    cached = _shared_mem.get(cache_key)
    if isinstance(cached, str) and cached.strip():
        _shared_mem.increment_stat("l1_hits")
        return cached.strip().upper()
    _shared_mem.increment_stat("l1_misses")
    return None


def _set_l1_city_code(city: str, code: str, qualifier: str | None = None) -> None:
    if not city or not code:
        return
    cache_key = _iata_city_cache_key(city, qualifier=qualifier)
    _shared_mem.set(cache_key, code.strip().upper())


async def _get_l2_city_code(
    db: AsyncSession, city: str, qualifier: str | None = None
) -> str | None:
    from app.db_models import ResponseCache

    cache_key = _iata_city_cache_key(city, qualifier=qualifier)

    try:
        result = await db.execute(
            select(ResponseCache)
            .where(ResponseCache.cache_key == cache_key)
            .where(ResponseCache.cache_type == "iata")
            .where(ResponseCache.expires_at > datetime.now(UTC))
        )
        row = result.scalar_one_or_none()
        if row is None:
            _shared_mem.increment_stat("l2_misses")
            return None

        payload = row.response_json or {}
        code = payload.get("code") if isinstance(payload, dict) else None
        if not isinstance(code, str) or not code.strip():
            _shared_mem.increment_stat("l2_misses")
            return None

        normalized_code = code.strip().upper()
        _shared_mem.increment_stat("l2_hits")
        _set_l1_city_code(city, normalized_code, qualifier=qualifier)

        stmt = (
            update(ResponseCache)
            .where(ResponseCache.cache_key == cache_key)
            .values(
                hit_count=ResponseCache.hit_count + 1,
                last_hit_at=datetime.now(UTC),
            )
        )
        await db.execute(stmt)
        await db.commit()
        return normalized_code
    except Exception as e:
        logger.warning(f"[IATA] L2 lookup failed for '{city}': {e}")
        return None


async def _set_l2_city_code(
    db: AsyncSession,
    city: str,
    code: str,
    qualifier: str | None = None,
) -> None:
    cache_key = _iata_city_cache_key(city, qualifier=qualifier)
    normalized_code = code.strip().upper()

    try:
        await l2_upsert(
            db,
            cache_key=cache_key,
            cache_type="iata",
            response_json={
                "city": city,
                "qualifier": qualifier,
                "code": normalized_code,
            },
            ttl=timedelta(hours=L2_TTL_HOURS),
        )
        _shared_mem.increment_stat("writes")
    except Exception as e:
        logger.warning(f"[IATA] L2 write failed for '{city}': {e}")
        await db.rollback()


def _extract_code(codes: dict, key: str) -> str:
    value = codes.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip().upper()
    return ""


async def resolve_iata_codes(origin: str, destination: str, state: GraphState) -> tuple[str, str]:
    """Resolve IATA codes. State → shared L1/L2 → LLM fallback.

    Returns (origin_code, dest_code). Either may be "" if unresolvable.
    """
    origin_code = (state.trip_plan.origin_iata or "").strip().upper()
    dest_code = (state.trip_plan.destination_iata or "").strip().upper()

    if origin_code and dest_code:
        return origin_code, dest_code

    # Shared L1 cache lookup by city (cross-session reuse)
    if origin and not origin_code:
        l1_origin = _get_l1_city_code(origin, qualifier=destination)
        if l1_origin:
            origin_code = l1_origin
            state.trip_plan.origin_iata = origin_code
    if destination and not dest_code:
        l1_dest = _get_l1_city_code(destination, qualifier=origin)
        if l1_dest:
            dest_code = l1_dest
            state.trip_plan.destination_iata = dest_code

    if origin_code and dest_code:
        return origin_code, dest_code

    # Shared L2 lookup for unresolved city codes
    needs_origin = bool(origin and not origin_code)
    needs_dest = bool(destination and not dest_code)
    if needs_origin or needs_dest:
        try:
            async_session_factory = _get_async_session_factory()
            async with async_session_factory() as db:
                if needs_origin:
                    l2_origin = await _get_l2_city_code(db, origin, qualifier=destination)
                    if l2_origin:
                        origin_code = l2_origin
                        state.trip_plan.origin_iata = origin_code
                if needs_dest:
                    l2_dest = await _get_l2_city_code(db, destination, qualifier=origin)
                    if l2_dest:
                        dest_code = l2_dest
                        state.trip_plan.destination_iata = dest_code
        except Exception as e:
            logger.warning(f"[IATA] Shared L2 cache unavailable: {e}")

    needs = []
    if origin and not origin_code:
        needs.append(f"origin: {origin}")
    if destination and not dest_code:
        needs.append(f"destination: {destination}")

    if not needs:
        return origin_code, dest_code

    l2_writes: list[tuple[str, str | None, str]] = []

    try:
        llm = get_llm_by_model(settings.iata_resolver_model, temperature=0, max_tokens=50)

        structured_llm = llm.with_structured_output(
            dict(_IATA_FLAT_SCHEMA), include_raw=True, method="function_calling"
        )

        prompt = (
            f"Return IATA airport codes for these cities. "
            f"Use the primary international airport for each city.\n"
            f"Cities: {', '.join(needs)}"
        )
        result = await structured_llm.ainvoke([{"role": "user", "content": prompt}])
        if isinstance(result, dict) and "parsed" in result:
            parsed = result["parsed"]
            if parsed is None:
                logger.warning("[IATA] Structured output returned None")
                return origin_code, dest_code
        elif hasattr(result, "model_fields"):
            parsed = result
        else:
            logger.warning(f"[IATA] Unexpected structured output type: {type(result).__name__}")
            return origin_code, dest_code

        codes = parsed if isinstance(parsed, dict) else parsed.model_dump()

        if origin and not origin_code:
            extracted_origin = _extract_code(codes, "origin")
            if extracted_origin:
                origin_code = extracted_origin
                state.trip_plan.origin_iata = origin_code
                _set_l1_city_code(origin, origin_code, qualifier=destination)
                l2_writes.append((origin, destination, origin_code))
        if destination and not dest_code:
            extracted_dest = _extract_code(codes, "destination")
            if extracted_dest:
                dest_code = extracted_dest
                state.trip_plan.destination_iata = dest_code
                _set_l1_city_code(destination, dest_code, qualifier=origin)
                l2_writes.append((destination, origin, dest_code))

        if l2_writes:
            try:
                async_session_factory = _get_async_session_factory()
                async with async_session_factory() as db:
                    for city, qualifier, code in l2_writes:
                        await _set_l2_city_code(db, city, code, qualifier=qualifier)
            except Exception as e:
                logger.warning(f"[IATA] Shared L2 write unavailable: {e}")

        logger.info(f"[IATA] Resolved: {origin}→{origin_code}, {destination}→{dest_code}")
    except Exception as e:
        logger.warning(f"[IATA] LLM resolution failed: {e}")

    return origin_code, dest_code
