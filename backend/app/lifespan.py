# backend/app/lifespan.py
"""Application lifespan hooks (startup + shutdown).

Extracted from main.py to keep the FastAPI app module focused on routes.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.planner import (
    CACHE_SCHEMA_VERSION,
    PLANNER_BUILD_ID,
    PROMPT_BUNDLE_HASH,
    prewarm_prompts,
    validate_template_coverage,
)
from app.validation import prewarm_cache

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    """Application lifespan hooks.

    Used instead of deprecated @app.on_event handlers.
    Pre-warms caches and compiles templates to eliminate cold-start latency.
    Validates template coverage at startup - fails fast on mismatch.
    """
    # Configure logging (suppress noisy loggers in non-full modes)
    from app.debug_utils import _debug, configure_logging

    configure_logging()

    # Log build info for cache debugging
    logger.info(
        "[Startup] Build info: prompt_bundle_hash=%s, planner_build_id=%s, cache_schema_version=%s",
        PROMPT_BUNDLE_HASH,
        PLANNER_BUILD_ID,
        CACHE_SCHEMA_VERSION,
    )
    _debug(
        f"[Startup] prompt_bundle_hash={PROMPT_BUNDLE_HASH}, "
        f"planner_build_id={PLANNER_BUILD_ID}, cache_schema_version={CACHE_SCHEMA_VERSION}"
    )

    # Prewarm validation cache
    validation_count = await prewarm_cache()
    _debug(f"[Validation] Pre-warmed cache with {validation_count} entries")

    # Prewarm prompts and templates (Jinja2 compilation)
    warmup_stats = prewarm_prompts()
    _debug(
        f"[Warmup] Pre-compiled {warmup_stats['prompts_warmed']} prompts, "
        f"{warmup_stats['templates_loaded']} templates in {warmup_stats['warmup_ms']}ms"
    )

    # Validate template coverage - FATAL on failure
    # This prevents deploy-time prompt/template drift that causes hard-to-debug runtime behavior
    template_validation = validate_template_coverage()
    if not template_validation["valid"]:
        error_msg = (
            f"[FATAL] Template coverage validation failed: "
            f"missing_fields={template_validation['missing_fields']}, "
            f"errors={template_validation['errors'][:3]}"
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    _debug(
        f"[Startup] Template coverage validation passed "
        f"(insufficient_suggestions={template_validation.get('insufficient_suggestions', {})})"
    )

    yield

    # ── Shutdown cleanup ──────────────────────────────────────────
    logger.info("[Shutdown] Cleaning up resources...")

    # 1. Cancel tracked background tasks
    from app.services.task_tracker import cancel_all as _cancel_bg_tasks

    cancelled = await _cancel_bg_tasks()
    if cancelled:
        logger.info("[Shutdown] Cancelled %d background tasks", cancelled)

    # 2a. Dispose async DB engine
    from app.db import _async_engine

    if _async_engine is not None:
        await _async_engine.dispose()
        logger.info("[Shutdown] Disposed async DB engine")

    # 2b. Dispose sync DB engine (used by Alembic/legacy)
    from app.db import engine as _sync_engine

    _sync_engine.dispose()
    logger.info("[Shutdown] Disposed sync DB engine")

    # 3. Close Amadeus HTTP client
    from app.tools.amadeus_client import AmadeusClient

    if AmadeusClient._instance is not None:
        await AmadeusClient._instance.close()
        logger.info("[Shutdown] Closed Amadeus HTTP client")

    # 4. Close Unsplash HTTP client
    from app.services.unsplash import close_http_client as close_unsplash_http_client

    await close_unsplash_http_client()
    logger.info("[Shutdown] Closed Unsplash HTTP client")

    # 5. Clear SSE connections dict
    from app.sse_state import _sse_connections, _sse_state_lock

    async with _sse_state_lock:
        _sse_connections.clear()

    logger.info("[Shutdown] Cleanup complete")
