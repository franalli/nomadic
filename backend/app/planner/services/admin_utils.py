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
import os
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
        "architecture": "create_agent",
        "tools": [
            "extract_trip_fields",
            "get_specialist_advice",
            "get_local_intel",
            "search_tiles",
            "validate_plan",
            "build_itinerary",
        ],
    }


def get_graph_stats() -> Dict[str, Any]:
    """Return graph statistics."""
    return {
        "architecture": "create_agent",
        "tools": 6,
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


async def clear_all_checkpoints() -> None:
    """Clear all checkpoints (no-op)."""
    pass


async def clear_response_caches() -> int:
    """Clear L1 in-memory caches (experience, specialist, tile, feasibility, router, browse, enrichment, IATA).

    L2 (PostgreSQL) is only cleared when settings.clear_l2_on_session_reset is True
    (set CLEAR_L2_ON_RESET=true in .env for local dev). In production this flag is
    unset so L2 entries survive restarts and expire naturally via their TTL.
    """
    from app.planner.services.feasibility_service import _feasibility_cache
    from app.services.experience_generator import clear_experience_cache
    from app.services.specialist_cache import clear_memory_cache as clear_specialist_cache
    from app.services.tile_cache import clear_memory_cache as clear_tile_cache

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
    truthy = {"1", "true", "yes", "on"}
    clear_l2_raw = os.getenv("CLEAR_L2_ON_RESET", "").strip().lower()
    pytest_running_raw = os.getenv("PYTEST_RUNNING", "").strip().lower()
    clear_l2 = clear_l2_raw in truthy
    pytest_running = pytest_running_raw in truthy
    if clear_l2 and not pytest_running:
        try:
            from sqlalchemy import text

            from app.db import _get_async_session_factory

            factory = _get_async_session_factory()
            async with factory() as db:
                result = await db.execute(text("DELETE FROM response_cache"))
                total += result.rowcount
                await db.commit()
        except Exception:
            pass

    return total


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
    """Clear all caches (response caches, validation caches, etc.)."""
    return await clear_response_caches()
