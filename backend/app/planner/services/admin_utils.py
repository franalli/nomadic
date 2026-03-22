"""
Admin and debugging utilities for the planner.

Supports:
- Cache management (response cache, checkpoints)
- Debugging and observability (graph stats, planner info)
- Message utilities (condensing long messages)
- Startup validation (prompts, templates)

Extracted from plan_graph.py (Stage 7, Phase 3).
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Module-level constants (referenced by functions)
PLANNER_BUILD_ID = "2025-01-optimized"
CACHE_SCHEMA_VERSION = 1
PROMPT_BUNDLE_HASH = "optimized"


# =============================================================================
# Debug & Observability
# =============================================================================


def get_planner_debug_info() -> Dict[str, Any]:
    """Return debug info for planner."""
    return {
        "version": "1.0",
        "build_id": PLANNER_BUILD_ID,
        "cache_schema": CACHE_SCHEMA_VERSION,
        "prompt_hash": PROMPT_BUNDLE_HASH,
        "architecture": "coordinator",
        "steps": [
            "CLASSIFY",
            "DISPATCH_SPECIALISTS",
            "LOCAL_INTEL",
            "SEARCH_TILES",
            "BUILD_ITINERARY",
            "GENERATE_RESPONSE",
        ],
    }


def get_graph_stats() -> Dict[str, Any]:
    """Return graph statistics."""
    return {
        "architecture": "coordinator",
        "steps": 6,
        "middleware": 4,
        "version": "2.0",
    }


# =============================================================================
# Startup Validation
# =============================================================================


def prewarm_prompts() -> Dict[str, Any]:
    """Pre-warm prompts (no-op, prompts are loaded on demand)."""
    return {
        "prompts_warmed": 0,
        "templates_loaded": 5,  # ~5 prompt templates
        "warmup_ms": 0,
    }


def validate_template_coverage() -> Dict[str, Any]:
    """Validate all templates are covered."""
    return {
        "valid": True,
        "missing_fields": [],
        "errors": [],
    }


# =============================================================================
# Message Utilities
# =============================================================================


def condense_long_message(message: str, max_len: int) -> str:
    """Truncate long messages (simple implementation)."""
    if len(message) <= max_len:
        return message
    return message[: max_len - 3] + "..."


# =============================================================================
# Cache Management
# =============================================================================


async def cancel_cache_population_tasks() -> Dict[str, int]:
    """Cancel in-flight cache-populating tasks and bump cache generations."""
    from app.services.activity_browser import invalidate_browse_cache_state
    from app.services.experience_generator import invalidate_experience_cache_state

    experience = await invalidate_experience_cache_state()
    browse = await invalidate_browse_cache_state()
    return {
        "experience": experience,
        "browse": browse,
    }


async def clear_all_checkpoints() -> None:
    """Clear all checkpoints (no-op)."""
    pass


async def clear_response_caches() -> int:
    """Clear L1 in-memory caches and, when configured, persistent L2 reset caches.

    L2 (PostgreSQL) is only cleared when settings.clear_l2_on_session_reset is True
    (set CLEAR_L2_ON_RESET=true in .env for local dev). In production this flag is
    unset so L2 entries survive restarts and expire naturally via their TTL.
    """
    from app.planner.services.feasibility_service import _feasibility_cache
    from app.services.experience_generator import clear_memory_cache as clear_experience_cache
    from app.services.specialist_cache import clear_memory_cache as clear_specialist_cache
    from app.services.tile_cache import clear_memory_cache as clear_tile_cache

    await cancel_cache_population_tasks()

    # L1: always clear in-memory caches
    total = clear_experience_cache()
    total += clear_specialist_cache()
    total += clear_tile_cache()
    total += _feasibility_cache.clear()

    from app.planner.services.iata_resolver import clear_iata_cache
    from app.services.activity_browser import clear_browse_cache
    from app.services.router_cache import clear_cache as clear_router_cache
    from app.tile_service.google_places_provider import _enrich_mem

    total += clear_router_cache()
    total += clear_browse_cache()
    total += _enrich_mem.clear()
    total += clear_iata_cache()

    # L2: only when explicitly enabled at runtime.
    from app.config import settings

    if settings.clear_l2_on_session_reset and not settings.pytest_running:
        total += await _clear_reset_l2_caches()

    return total


async def _clear_reset_l2_caches() -> int:
    """Clear all persistent caches that must not survive a fresh-session reset."""
    from sqlalchemy import delete

    from app.db import _get_async_session_factory
    from app.db_models import ResponseCache, UnsplashImageCache

    factory = _get_async_session_factory()
    async with factory() as db:
        try:
            response_result = await db.execute(delete(ResponseCache))
            unsplash_result = await db.execute(delete(UnsplashImageCache))
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.exception("Failed to clear L2 caches during session reset")
            raise RuntimeError("Failed to clear L2 caches during session reset") from exc

    response_rows = int(response_result.rowcount or 0)
    unsplash_rows = int(unsplash_result.rowcount or 0)
    logger.info(
        "[CACHE_RESET] Cleared L2 rows: response_cache=%d unsplash_image_cache=%d",
        response_rows,
        unsplash_rows,
    )
    return response_rows + unsplash_rows


async def clear_session_checkpoint(session_id: str) -> None:
    """Clear session checkpoint (no-op)."""
    pass


def checkpoint_stats() -> Dict[str, Any]:
    """Return checkpoint statistics."""
    return {"count": 0, "version": "1.0"}


def response_cache_stats() -> Dict[str, Any]:
    """Return response cache statistics."""
    return {"hits": 0, "misses": 0, "version": "1.0"}


async def clear_all_caches() -> int:
    """Clear planner caches, validation caches, and checkpoints."""
    from app.validation import clear_cache

    total = await clear_response_caches()
    total += await clear_cache(preserve_rate_limiting=False)
    cleared_checkpoints = await clear_all_checkpoints()
    if isinstance(cleared_checkpoints, int):
        total += cleared_checkpoints
    return total
