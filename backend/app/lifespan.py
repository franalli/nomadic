# backend/app/lifespan.py
"""Application lifespan hooks (startup + shutdown).

Extracted from main.py to keep the FastAPI app module focused on routes.
"""

import asyncio
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

    # Configure LangSmith tracing (sets LANGCHAIN_* env vars with project suffix)
    from app.config import configure_langsmith_tracing

    resolved_project = configure_langsmith_tracing()
    _debug(f"[Startup] LangSmith project resolved to: {resolved_project or 'N/A'}")

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

    # Log spend guard state (counters restored from disk if same day)
    from app.config import settings
    from app.services.spend_guard import get_spend_guard_snapshot

    sg = get_spend_guard_snapshot()
    logger.info(
        "[Startup] SpendGuard counters restored to $%.2f "
        "(enabled=%s, session_cap=$%.2f, global_cap=$%.2f)",
        sg["global_spend_usd"],
        settings.spend_guard_enabled,
        settings.spend_guard_session_daily_cap_usd,
        settings.spend_guard_global_daily_cap_usd,
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

    # 1b. Cancel in-flight experience generation tasks
    from app.services.experience_generator import cancel_inflight as _cancel_inflight

    cancelled_inflight = await _cancel_inflight()
    if cancelled_inflight:
        logger.info(
            "[Shutdown] Cancelled %d inflight experience generation tasks", cancelled_inflight
        )

    # 1c. Cancel inflight feasibility checks
    from app.planner.services.feasibility_service import cancel_feasibility_inflight

    cancelled_feasibility = await cancel_feasibility_inflight()
    if cancelled_feasibility:
        logger.info("[Shutdown] Cancelled %d inflight feasibility checks", cancelled_feasibility)

    # 1d. Cancel inflight browse tasks before disposing DB-backed cache layers
    from app.services.activity_browser import cancel_browse_inflight

    cancelled_browse = await cancel_browse_inflight()
    if cancelled_browse:
        logger.info("[Shutdown] Cancelled %d inflight browse tasks", cancelled_browse)

    # 2a. Dispose async DB engine
    from app.db import _async_engine

    if _async_engine is not None:
        await _async_engine.dispose()
        logger.info("[Shutdown] Disposed async DB engine")

    # 2b. Dispose sync DB engine (used by Alembic/legacy)
    from app.db import engine as _sync_engine

    _sync_engine.dispose()
    logger.info("[Shutdown] Disposed sync DB engine")

    # 3. Cancel unsplash in-flight fetch tasks (before closing HTTP client)
    from app.services.unsplash import (
        _inflight_fetches,
        _inflight_fetches_lock,
        _prefetch_destination_inflight,
    )

    async with _inflight_fetches_lock:
        _unsplash_tasks = list(_inflight_fetches.values()) + list(
            _prefetch_destination_inflight.values()
        )
        _inflight_fetches.clear()
        _prefetch_destination_inflight.clear()
    for _t in _unsplash_tasks:
        _t.cancel()
    if _unsplash_tasks:
        await asyncio.gather(*_unsplash_tasks, return_exceptions=True)
        logger.info("[Shutdown] Cancelled %d unsplash inflight tasks", len(_unsplash_tasks))

    # 5. Close Unsplash HTTP client
    from app.services.unsplash import close_http_client as close_unsplash_http_client

    await close_unsplash_http_client()
    logger.info("[Shutdown] Closed Unsplash HTTP client")

    # 5a2. Flush spend guard state to disk before shutdown
    from app.services.spend_guard import flush_spend_state

    flush_spend_state()
    logger.info("[Shutdown] Flushed spend guard state to disk")

    # 5a3. Drain Google Places enrichment inflight + geocode caches
    from app.tile_service.google_places_provider import clear_geocode_caches

    clear_geocode_caches()
    logger.info("[Shutdown] Cleared Google Places geocode caches and enrichment inflight")

    # 5b. Close Google Places HTTP client
    from app.tile_service.google_places_provider import close_places_http_client

    await close_places_http_client()
    logger.info("[Shutdown] Closed Google Places HTTP client")

    # 5b2. Close Viator HTTP client
    from app.services.viator_provider import close_viator_http_client

    await close_viator_http_client()
    logger.info("[Shutdown] Closed Viator HTTP client")

    # 5b3. Close GYG HTTP client
    from app.services.gyg_provider import close_gyg_http_client

    await close_gyg_http_client()
    logger.info("[Shutdown] Closed GYG HTTP client")

    # 5c. Close Google Places sync HTTP client
    from app.tile_service.google_places_provider import close_sync_client

    close_sync_client()
    logger.info("[Shutdown] Closed Google Places sync HTTP client")

    # 5d. Close photo proxy HTTP client
    from app.main import _photo_proxy_client

    if _photo_proxy_client is not None and not _photo_proxy_client.is_closed:
        await _photo_proxy_client.aclose()
        logger.info("[Shutdown] Closed photo proxy HTTP client")

    # 6. Clear pending enrichments dict
    from app.planner.nodes.local_expert import _pending_enrichments, _pending_lock

    async with _pending_lock:
        _n_enrichments = len(_pending_enrichments)
        _pending_enrichments.clear()
    if _n_enrichments:
        logger.info("[Shutdown] Cleared %d pending enrichments", _n_enrichments)

    # 7. Clear SSE connections dict
    from app.sse_state import _sse_connections, _sse_state_lock

    async with _sse_state_lock:
        _sse_connections.clear()

    logger.info("[Shutdown] Cleanup complete")
