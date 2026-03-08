"""
Hard spend guardrails for paid external APIs.

Implements:
- Per-session daily USD cap
- Global daily USD cap
- Request-scoped session context via contextvars
- Pre-call budget reservation for LLM and Google Places calls
"""

from __future__ import annotations

import json
import logging
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from app.config import MODEL_PRICING_PER_1M, settings

logger = logging.getLogger(__name__)

_session_id_ctx: ContextVar[str | None] = ContextVar("spend_guard_session_id", default=None)

# NOTE: In-memory spend tracking is correct for single-worker deployment.
# For multi-worker, migrate to Redis or shared state.
#
# File-based persistence (via _SPEND_STATE_FILE) is implemented as a bridge so
# daily caps survive process restarts within a single-worker deployment.
# It does NOT solve multi-worker isolation.
#
# TODO: Before scaling to multi-instance, replace module-level dicts with
# Redis counters (INCRBY + daily-key TTL) so budget isolation is shared
# across workers.
#
# Planned Redis key schema:
#   spend:{session_id}:{YYYY-MM-DD}  — per-session daily spend (float cents)
#   spend:global:{YYYY-MM-DD}        — global daily spend (float cents)
#   spend:provider:{provider}:{YYYY-MM-DD} — per-provider daily spend
#
# Operations:
#   INCRBY / INCRBYFLOAT on the relevant key before each paid call.
#   SET TTL = 86400 (24h) on first write via SET NX + EXPIRE, so keys
#   auto-expire one day after creation and do not require manual cleanup.
#   Use a Lua script or MULTI/EXEC to atomically check cap + increment.
_spend_lock = Lock()
_spend_day_key = datetime.now(UTC).date().isoformat()
_session_spend_usd: dict[str, float] = {}
_global_spend_usd = 0.0
_provider_spend_usd: dict[str, float] = {"llm": 0.0, "places": 0.0, "partner": 0.0}

_SPEND_STATE_FILE = Path(tempfile.gettempdir()) / "nomadic_spend_guard_state.json"


def _persist_state() -> None:
    """Write global and provider spend to disk so caps survive restarts.

    Must be called while _spend_lock is held. File I/O errors are swallowed
    so they never block API calls.
    """
    try:
        data = {
            "day": _spend_day_key,
            "global_spend_usd": _global_spend_usd,
            "provider_spend_usd": dict(_provider_spend_usd),
        }
        _SPEND_STATE_FILE.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        logger.debug("spend_guard: failed to persist state to %s", _SPEND_STATE_FILE, exc_info=True)


def _load_state() -> None:
    """Restore global and provider spend from disk on startup.

    Only restores if the persisted day key matches today. Stale data from a
    previous day is silently ignored. File I/O errors are swallowed so startup
    is never blocked.
    """
    global _global_spend_usd

    try:
        if not _SPEND_STATE_FILE.exists():
            return
        raw = _SPEND_STATE_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return
        if data.get("day") != _spend_day_key:
            logger.info(
                "spend_guard: ignoring stale persisted state (file day=%s, today=%s)",
                data.get("day"),
                _spend_day_key,
            )
            return
        restored_global = float(data.get("global_spend_usd", 0.0))
        restored_providers = data.get("provider_spend_usd", {})
        if not isinstance(restored_providers, dict):
            restored_providers = {}

        _global_spend_usd = max(0.0, restored_global)
        for key in ("llm", "places", "partner"):
            _provider_spend_usd[key] = max(0.0, float(restored_providers.get(key, 0.0)))

        logger.info(
            "spend_guard: restored persisted state — global=$%.4f, providers=%s",
            _global_spend_usd,
            _provider_spend_usd,
        )
    except Exception:
        logger.debug(
            "spend_guard: failed to load persisted state from %s",
            _SPEND_STATE_FILE,
            exc_info=True,
        )


# Restore persisted spend counters on module load (before any requests).
_load_state()

if not settings.spend_guard_enabled:
    _level = logging.CRITICAL if not settings.is_dev else logging.WARNING
    logger.log(
        _level,
        "SPEND GUARD DISABLED — all LLM and Places API calls are uncapped. "
        "Set SPEND_GUARD_ENABLED=true in production.",
    )

# Intentional fail-fast: refuse to start with multiple workers since in-memory
# spend tracking would allow N× the configured cap (one counter per worker).
# This is a safety net, not a bug — remove only when Redis migration is complete.
if settings.spend_guard_enabled:
    _worker_count = settings.web_concurrency
    if _worker_count > 1:
        logger.critical(
            "SPEND GUARD: %d workers detected with in-memory spend tracking. "
            "Effective cap is %dx nominal. Set SPEND_GUARD_ENABLED=false "
            "or WEB_CONCURRENCY=1 or migrate to Redis.",
            _worker_count,
            _worker_count,
        )
        raise RuntimeError(
            f"Spend guard cannot safely run with {_worker_count} workers. "
            "Set WEB_CONCURRENCY=1 or disable spend guard."
        )

# Log startup info about file-backed persistence (only when guard is active)
if settings.spend_guard_enabled:
    logger.info(
        "Spend guard: in-memory with file-backed persistence (%s). "
        "Daily caps survive single-worker restarts. "
        "For multi-worker caps, migrate to Redis (see TODO above).",
        _SPEND_STATE_FILE,
    )


class SpendLimitExceeded(RuntimeError):
    """Raised when a pre-call spend reservation exceeds configured limits."""

    def __init__(
        self,
        *,
        provider: str,
        scope: str,
        limit_usd: float,
        current_usd: float,
        requested_usd: float,
        source: str,
    ) -> None:
        total_usd = current_usd + requested_usd
        message = (
            f"{provider.upper()} daily spend cap exceeded for {scope}: "
            f"limit=${limit_usd:.2f}, attempted=${total_usd:.4f}"
        )
        if source:
            message = f"{message} ({source})"
        super().__init__(message)
        self.provider = provider
        self.scope = scope
        self.limit_usd = limit_usd
        self.current_usd = current_usd
        self.requested_usd = requested_usd
        self.source = source


def _current_day_key() -> str:
    return datetime.now(UTC).date().isoformat()


def _rollover_if_needed() -> None:
    global _spend_day_key
    global _global_spend_usd

    day_key = _current_day_key()
    if day_key == _spend_day_key:
        return

    _spend_day_key = day_key
    _session_spend_usd.clear()
    _provider_spend_usd["llm"] = 0.0
    _provider_spend_usd["places"] = 0.0
    _provider_spend_usd["partner"] = 0.0
    _global_spend_usd = 0.0
    _persist_state()


@contextmanager
def spend_guard_scope(session_id: str | None):
    """Bind a session id to downstream paid-call reservations."""
    token = _session_id_ctx.set(session_id)
    try:
        yield
    finally:
        _session_id_ctx.reset(token)


def _check_provider_cap(provider: str, estimated_usd: float, source: str) -> None:
    """Provider-specific daily cap. Must be called inside _spend_lock."""
    cap: float = 0.0
    if provider == "places":
        cap = max(0.0, float(settings.spend_guard_places_daily_cap_usd))
    elif provider == "partner":
        cap = max(0.0, float(settings.spend_guard_partner_daily_cap_usd))
    else:
        return

    current = _provider_spend_usd.get(provider, 0.0)
    if cap > 0 and (current + estimated_usd) > cap:
        raise SpendLimitExceeded(
            provider=provider,
            scope="provider",
            limit_usd=cap,
            current_usd=current,
            requested_usd=estimated_usd,
            source=source,
        )


def _reserve_or_raise(
    *,
    provider: str,
    estimated_usd: float,
    session_id: str | None = None,
    source: str = "",
) -> None:
    global _global_spend_usd

    if not settings.spend_guard_enabled:
        return
    if estimated_usd <= 0:
        return

    sid = session_id if session_id is not None else _session_id_ctx.get()
    if not sid:
        logger.warning(
            "spend_guard: no session_id (source=%s), enforcing global cap only",
            source,
        )
        # Skip session cap, still enforce global daily cap
        global_cap = max(0.0, float(settings.spend_guard_global_daily_cap_usd))
        with _spend_lock:
            _rollover_if_needed()
            if global_cap > 0 and (_global_spend_usd + estimated_usd) > global_cap:
                raise SpendLimitExceeded(
                    provider=provider,
                    scope="global",
                    limit_usd=global_cap,
                    current_usd=_global_spend_usd,
                    requested_usd=estimated_usd,
                    source=source,
                )
            _check_provider_cap(provider, estimated_usd, source)
            _global_spend_usd += estimated_usd
            _provider_spend_usd[provider] = _provider_spend_usd.get(provider, 0.0) + estimated_usd
            _persist_state()
        return

    session_cap = max(0.0, float(settings.spend_guard_session_daily_cap_usd))
    global_cap = max(0.0, float(settings.spend_guard_global_daily_cap_usd))

    with _spend_lock:
        _rollover_if_needed()

        session_current = _session_spend_usd.get(sid, 0.0)
        global_current = _global_spend_usd

        if session_cap > 0 and (session_current + estimated_usd) > session_cap:
            raise SpendLimitExceeded(
                provider=provider,
                scope="session",
                limit_usd=session_cap,
                current_usd=session_current,
                requested_usd=estimated_usd,
                source=source,
            )

        if global_cap > 0 and (global_current + estimated_usd) > global_cap:
            raise SpendLimitExceeded(
                provider=provider,
                scope="global",
                limit_usd=global_cap,
                current_usd=global_current,
                requested_usd=estimated_usd,
                source=source,
            )

        _check_provider_cap(provider, estimated_usd, source)

        _session_spend_usd[sid] = session_current + estimated_usd
        _global_spend_usd = global_current + estimated_usd
        _provider_spend_usd[provider] = _provider_spend_usd.get(provider, 0.0) + estimated_usd
        _persist_state()


def _estimate_llm_call_usd(model: str, max_tokens: int | None = None) -> float:
    pricing = MODEL_PRICING_PER_1M.get(model)
    if not pricing:
        return max(0.0, float(settings.spend_guard_llm_unknown_model_estimated_call_usd))

    prompt_tokens = max(1, int(settings.spend_guard_llm_prompt_tokens_estimate))
    completion_floor = max(1, int(settings.spend_guard_llm_completion_tokens_estimate))
    completion_tokens = max(completion_floor, int(max_tokens or 0))

    prompt_cost = (prompt_tokens / 1_000_000.0) * pricing["prompt"]
    completion_cost = (completion_tokens / 1_000_000.0) * pricing["completion"]
    return max(prompt_cost + completion_cost, 0.0)


def reserve_llm_spend_or_raise(
    *,
    model: str,
    max_tokens: int | None = None,
    session_id: str | None = None,
    source: str = "llm",
) -> None:
    estimated = _estimate_llm_call_usd(model=model, max_tokens=max_tokens)
    _reserve_or_raise(
        provider="llm",
        estimated_usd=estimated,
        session_id=session_id,
        source=source,
    )


def reserve_places_spend_or_raise(
    *,
    session_id: str | None = None,
    source: str = "google_places",
) -> None:
    estimated = max(0.0, float(settings.spend_guard_places_estimated_call_usd))
    _reserve_or_raise(
        provider="places",
        estimated_usd=estimated,
        session_id=session_id,
        source=source,
    )


def reserve_partner_api_spend_or_raise(provider_label: str = "partner") -> None:
    """Reserve budget for a partner API call (Viator, GYG, etc.)."""
    if not settings.spend_guard_enabled:
        return
    _reserve_or_raise(
        provider="partner",
        estimated_usd=max(0.0, float(settings.spend_guard_partner_estimated_call_usd)),
        source=f"partner-{provider_label}",
    )


def clear_spend_guard_counters() -> None:
    """Reset in-memory spend counters (tests/admin maintenance)."""
    global _spend_day_key
    global _global_spend_usd

    with _spend_lock:
        _spend_day_key = _current_day_key()
        _session_spend_usd.clear()
        _provider_spend_usd["llm"] = 0.0
        _provider_spend_usd["places"] = 0.0
        _provider_spend_usd["partner"] = 0.0
        _global_spend_usd = 0.0
        _persist_state()


def get_spend_guard_snapshot() -> dict[str, object]:
    """Expose counters for observability/tests."""
    with _spend_lock:
        _rollover_if_needed()
        return {
            "day": _spend_day_key,
            "global_spend_usd": _global_spend_usd,
            "provider_spend_usd": dict(_provider_spend_usd),
            "session_count": len(_session_spend_usd),
        }
