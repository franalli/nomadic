"""
Hard spend guardrails for paid external APIs.

Implements:
- Per-session daily USD cap
- Global daily USD cap
- Provider-specific daily USD cap
- Request-scoped session context via contextvars
- Pre-call budget reservation for LLM and Google Places calls

Counters are stored in the shared runtime_state table so they work across workers.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import db as db_module
from app.config import MODEL_PRICING_PER_1M, settings
from app.db_models import RuntimeState

logger = logging.getLogger(__name__)

_session_id_ctx: ContextVar[str | None] = ContextVar("spend_guard_session_id", default=None)

_SPEND_COUNTER_STATE_TYPE = "spend_counter"
_GLOBAL_SCOPE = "global"
_SESSION_SCOPE = "session"
_PROVIDER_SCOPE = "provider"
_MICRO_USD = 1_000_000
_KNOWN_PROVIDER_KEYS = ("llm", "places")


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


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _current_day_key() -> str:
    return datetime.now(UTC).date().isoformat()


def _usd_to_micro_usd(amount_usd: float) -> int:
    return max(0, int(round(float(amount_usd) * _MICRO_USD)))


def _micro_usd_to_usd(amount_micro_usd: int) -> float:
    return max(0, int(amount_micro_usd)) / _MICRO_USD


def _counter_state_key(
    *,
    scope: str,
    day_key: str,
    session_id: str | None = None,
    provider: str | None = None,
) -> str:
    if scope == _GLOBAL_SCOPE:
        return f"spend:global:{day_key}"
    if scope == _SESSION_SCOPE:
        if not session_id:
            raise ValueError("session_id is required for session spend keys")
        return f"spend:session:{session_id}:{day_key}"
    if scope == _PROVIDER_SCOPE:
        if not provider:
            raise ValueError("provider is required for provider spend keys")
        return f"spend:provider:{provider}:{day_key}"
    raise ValueError(f"Unsupported spend scope: {scope}")


def _provider_cap_micro_usd(provider: str) -> int:
    if provider == "places":
        return _usd_to_micro_usd(float(settings.spend_guard_places_daily_cap_usd))
    return 0


def _counter_expires_at(day_key: str) -> datetime:
    day = date.fromisoformat(day_key)
    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=UTC)


def _purge_stale_spend_rows(db: Session, *, day_key: str) -> None:
    now = _utcnow()
    db.execute(
        delete(RuntimeState).where(
            RuntimeState.state_type == _SPEND_COUNTER_STATE_TYPE,
            or_(
                and_(
                    RuntimeState.expires_at.is_not(None),
                    RuntimeState.expires_at <= now,
                ),
                and_(
                    RuntimeState.expires_at.is_(None),
                    RuntimeState.day_key.is_not(None),
                    RuntimeState.day_key < day_key,
                ),
            ),
        )
    )


def _ensure_counter_row(
    db: Session,
    *,
    state_key: str,
    scope: str,
    day_key: str,
    session_id: str | None = None,
    provider: str | None = None,
) -> None:
    if (
        db.execute(
            select(RuntimeState.state_key).where(RuntimeState.state_key == state_key)
        ).scalar_one_or_none()
        is not None
    ):
        return

    while True:
        try:
            with db.begin_nested():
                db.add(
                    RuntimeState(
                        state_key=state_key,
                        state_type=_SPEND_COUNTER_STATE_TYPE,
                        scope=scope,
                        session_id=session_id,
                        provider=provider,
                        day_key=day_key,
                        expires_at=_counter_expires_at(day_key),
                    )
                )
                db.flush()
            return
        except IntegrityError:
            if (
                db.execute(
                    select(RuntimeState.state_key).where(RuntimeState.state_key == state_key)
                ).scalar_one_or_none()
                is not None
            ):
                return


def _increment_counter_or_current(
    db: Session,
    *,
    state_key: str,
    scope: str,
    day_key: str,
    amount_micro_usd: int,
    limit_micro_usd: int = 0,
    session_id: str | None = None,
    provider: str | None = None,
) -> int | None:
    for _ in range(3):
        _ensure_counter_row(
            db,
            state_key=state_key,
            scope=scope,
            day_key=day_key,
            session_id=session_id,
            provider=provider,
        )

        stmt = update(RuntimeState).where(RuntimeState.state_key == state_key)
        if limit_micro_usd > 0:
            stmt = stmt.where(RuntimeState.value_micro_usd + amount_micro_usd <= limit_micro_usd)

        result = db.execute(
            stmt.values(
                value_micro_usd=RuntimeState.value_micro_usd + amount_micro_usd,
                updated_at=_utcnow(),
            )
        )
        if result.rowcount == 1:
            return None

        current_micro_usd = db.execute(
            select(RuntimeState.value_micro_usd).where(RuntimeState.state_key == state_key)
        ).scalar_one_or_none()
        if current_micro_usd is None:
            continue

        current_micro_usd = int(current_micro_usd or 0)
        if limit_micro_usd > 0 and current_micro_usd + amount_micro_usd > limit_micro_usd:
            return current_micro_usd

    raise RuntimeError(f"Unable to update spend counter row {state_key}")


def _raise_spend_limit(
    *,
    provider: str,
    scope: str,
    limit_micro_usd: int,
    current_micro_usd: int,
    requested_micro_usd: int,
    source: str,
) -> None:
    raise SpendLimitExceeded(
        provider=provider,
        scope=scope,
        limit_usd=_micro_usd_to_usd(limit_micro_usd),
        current_usd=_micro_usd_to_usd(current_micro_usd),
        requested_usd=_micro_usd_to_usd(requested_micro_usd),
        source=source,
    )


@contextmanager
def spend_guard_scope(session_id: str | None):
    """Bind a session id to downstream paid-call reservations."""
    token = _session_id_ctx.set(session_id)
    try:
        yield
    finally:
        _session_id_ctx.reset(token)


def _reserve_or_raise(
    *,
    provider: str,
    estimated_usd: float,
    session_id: str | None = None,
    source: str = "",
) -> None:
    if not settings.spend_guard_enabled:
        return

    requested_micro_usd = _usd_to_micro_usd(estimated_usd)
    if requested_micro_usd <= 0:
        return

    sid = session_id if session_id is not None else _session_id_ctx.get()
    day_key = _current_day_key()
    session_cap_micro_usd = _usd_to_micro_usd(float(settings.spend_guard_session_daily_cap_usd))
    global_cap_micro_usd = _usd_to_micro_usd(float(settings.spend_guard_global_daily_cap_usd))
    provider_cap_micro_usd = _provider_cap_micro_usd(provider)

    if not sid:
        logger.warning(
            "spend_guard: no session_id (source=%s), enforcing global cap only",
            source,
        )

    with db_module.SessionLocal() as db:
        with db.begin():
            _purge_stale_spend_rows(db, day_key=day_key)

            if sid:
                session_key = _counter_state_key(
                    scope=_SESSION_SCOPE,
                    day_key=day_key,
                    session_id=sid,
                )
                session_current = _increment_counter_or_current(
                    db,
                    state_key=session_key,
                    scope=_SESSION_SCOPE,
                    day_key=day_key,
                    session_id=sid,
                    amount_micro_usd=requested_micro_usd,
                    limit_micro_usd=session_cap_micro_usd,
                )
                if session_current is not None:
                    _raise_spend_limit(
                        provider=provider,
                        scope=_SESSION_SCOPE,
                        limit_micro_usd=session_cap_micro_usd,
                        current_micro_usd=session_current,
                        requested_micro_usd=requested_micro_usd,
                        source=source,
                    )

            global_key = _counter_state_key(scope=_GLOBAL_SCOPE, day_key=day_key)
            global_current = _increment_counter_or_current(
                db,
                state_key=global_key,
                scope=_GLOBAL_SCOPE,
                day_key=day_key,
                amount_micro_usd=requested_micro_usd,
                limit_micro_usd=global_cap_micro_usd,
            )
            if global_current is not None:
                _raise_spend_limit(
                    provider=provider,
                    scope=_GLOBAL_SCOPE,
                    limit_micro_usd=global_cap_micro_usd,
                    current_micro_usd=global_current,
                    requested_micro_usd=requested_micro_usd,
                    source=source,
                )

            provider_key = _counter_state_key(
                scope=_PROVIDER_SCOPE,
                day_key=day_key,
                provider=provider,
            )
            provider_current = _increment_counter_or_current(
                db,
                state_key=provider_key,
                scope=_PROVIDER_SCOPE,
                day_key=day_key,
                provider=provider,
                amount_micro_usd=requested_micro_usd,
                limit_micro_usd=provider_cap_micro_usd,
            )
            if provider_current is not None:
                _raise_spend_limit(
                    provider=provider,
                    scope=_PROVIDER_SCOPE,
                    limit_micro_usd=provider_cap_micro_usd,
                    current_micro_usd=provider_current,
                    requested_micro_usd=requested_micro_usd,
                    source=source,
                )


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


def clear_spend_guard_counters() -> None:
    """Reset shared spend counters (tests/admin maintenance)."""
    with db_module.SessionLocal() as db, db.begin():
        db.execute(delete(RuntimeState).where(RuntimeState.state_type == _SPEND_COUNTER_STATE_TYPE))


def get_spend_guard_snapshot() -> dict[str, object]:
    """Expose counters for observability/tests."""
    day_key = _current_day_key()
    provider_spend_usd = {provider: 0.0 for provider in _KNOWN_PROVIDER_KEYS}
    global_spend_usd = 0.0
    session_ids: set[str] = set()

    with db_module.SessionLocal() as db, db.begin():
        _purge_stale_spend_rows(db, day_key=day_key)
        rows = db.execute(
            select(
                RuntimeState.scope,
                RuntimeState.provider,
                RuntimeState.session_id,
                RuntimeState.value_micro_usd,
            ).where(
                RuntimeState.state_type == _SPEND_COUNTER_STATE_TYPE,
                RuntimeState.day_key == day_key,
            )
        ).all()

    for scope, provider, session_id, value_micro_usd in rows:
        amount_usd = _micro_usd_to_usd(int(value_micro_usd or 0))
        if scope == _GLOBAL_SCOPE:
            global_spend_usd = amount_usd
        elif scope == _PROVIDER_SCOPE and provider:
            provider_spend_usd[provider] = amount_usd
        elif scope == _SESSION_SCOPE and session_id:
            session_ids.add(session_id)

    return {
        "day": day_key,
        "global_spend_usd": global_spend_usd,
        "provider_spend_usd": provider_spend_usd,
        "session_count": len(session_ids),
    }


def flush_spend_state() -> None:
    """DB-backed counters are already durable; kept for lifespan compatibility."""


if not settings.spend_guard_enabled:
    _level = logging.CRITICAL if not settings.is_dev else logging.WARNING
    logger.log(
        _level,
        "SPEND GUARD DISABLED — all LLM and Places API calls are uncapped. "
        "Set SPEND_GUARD_ENABLED=true in production.",
    )
else:
    logger.info(
        "Spend guard: using DB-backed runtime_state counters (workers=%d)",
        settings.web_concurrency,
    )
