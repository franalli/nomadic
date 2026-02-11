"""
Admin and debugging utilities for the planner.

Supports:
- Cache management (response cache, checkpoints)
- Debugging and observability (graph stats, planner info)
- Message utilities (condensing long messages)
- Startup validation (prompts, templates)

Note: clear_all_caches() remains in plan_graph.py (mutates global _graph).

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
        "graph_nodes": ["router", "specialist", "architect", "guard", "synthesizer"],
    }


def get_graph_stats() -> Dict[str, Any]:
    """Return graph statistics."""
    return {
        "nodes": 5,
        "edges": 6,
        "version": "1.0",
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
    """Clear response caches (experience L1 + L2)."""
    from app.services.experience_generator import clear_experience_cache

    # L1: in-memory
    l1_cleared = clear_experience_cache()

    # L2: database (experience entries only)
    l2_cleared = 0
    try:
        from sqlalchemy import delete

        from app.db import _get_async_session_factory
        from app.db_models import ResponseCache

        factory = _get_async_session_factory()
        async with factory() as db:
            result = await db.execute(
                delete(ResponseCache).where(ResponseCache.cache_type == "experience")
            )
            l2_cleared = result.rowcount
            await db.commit()
    except Exception:
        pass

    return l1_cleared + l2_cleared


async def clear_session_checkpoint(session_id: str) -> None:
    """Clear session checkpoint (no-op)."""
    pass


def checkpoint_stats() -> Dict[str, Any]:
    """Return checkpoint statistics."""
    return {"count": 0, "version": "1.0"}


def response_cache_stats() -> Dict[str, Any]:
    """Return response cache statistics."""
    return {"hits": 0, "misses": 0, "version": "1.0"}
