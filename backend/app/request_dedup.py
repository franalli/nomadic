"""Request deduplication via DB-backed runtime leases."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from app import db as db_module
from app.db_models import RuntimeState

_LEASE_STATE_TYPE = "lease"
_IDEMPOTENCY_SCOPE = "request_idempotency"
_EXPAND_SCOPE = "expand_mutex"
_IDEMPOTENCY_TTL_SECONDS = 30
_EXPAND_TTL_SECONDS = 120
_active_lease_handles: ContextVar[dict[str, "LeaseHandle"] | None] = ContextVar(
    "request_dedup_active_leases", default=None
)


@dataclass(frozen=True)
class LeaseHandle:
    state_key: str
    lease_token: int


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _scoped_idempotency_key(key: str | None, session_id: str | None = None) -> str | None:
    """Scope idempotency keys to a session when one is available."""
    if not key:
        return None
    if not session_id:
        return key
    return f"{session_id}:{key}"


def _lease_state_key(scope: str, key: str) -> str:
    return f"lease:{scope}:{key}"


def _hashed_idempotency_state_key(scoped_key: str) -> str:
    digest = hashlib.sha256(scoped_key.encode("utf-8")).hexdigest()
    return _lease_state_key(_IDEMPOTENCY_SCOPE, f"sha256:{digest}")


def _purge_expired_leases(*, now: datetime) -> None:
    with db_module.SessionLocal() as db, db.begin():
        db.execute(
            delete(RuntimeState).where(
                RuntimeState.state_type == _LEASE_STATE_TYPE,
                RuntimeState.expires_at.is_not(None),
                RuntimeState.expires_at <= now,
            )
        )


def _remember_lease(handle: LeaseHandle) -> None:
    active = dict(_active_lease_handles.get() or {})
    active[handle.state_key] = handle
    _active_lease_handles.set(active)


def _take_lease(state_key: str) -> LeaseHandle | None:
    active = dict(_active_lease_handles.get() or {})
    handle = active.pop(state_key, None)
    _active_lease_handles.set(active or None)
    return handle


def _acquire_lease(
    *,
    state_key: str,
    scope: str,
    ttl_seconds: int,
    session_id: str | None = None,
) -> LeaseHandle | None:
    for _ in range(2):
        now = _utcnow()
        expires_at = now + timedelta(seconds=ttl_seconds)
        lease_token = max(1, secrets.randbits(63))
        _purge_expired_leases(now=now)
        with db_module.SessionLocal() as db:
            try:
                with db.begin():
                    db.add(
                        RuntimeState(
                            state_key=state_key,
                            state_type=_LEASE_STATE_TYPE,
                            scope=scope,
                            session_id=session_id,
                            provider=None,
                            day_key=None,
                            expires_at=expires_at,
                            value_micro_usd=lease_token,
                        )
                    )
                return LeaseHandle(state_key=state_key, lease_token=lease_token)
            except IntegrityError:
                db.rollback()
                existing = db.get(RuntimeState, state_key)
                if existing is None:
                    continue

                existing_expires_at = _coerce_utc(existing.expires_at)
                if existing_expires_at is None or existing_expires_at > _utcnow():
                    return None

                with db.begin():
                    db.delete(existing)

    return None


def _release_lease(handle: LeaseHandle) -> None:
    with db_module.SessionLocal() as db, db.begin():
        db.execute(
            delete(RuntimeState).where(
                RuntimeState.state_key == handle.state_key,
                RuntimeState.state_type == _LEASE_STATE_TYPE,
                RuntimeState.value_micro_usd == handle.lease_token,
            )
        )


async def check_idempotency(key: str | None, *, session_id: str | None = None) -> bool:
    """Check if idempotency key was recently used. Returns True if duplicate."""
    scoped_key = _scoped_idempotency_key(key, session_id=session_id)
    if not scoped_key:
        return False

    handle = await asyncio.to_thread(
        _acquire_lease,
        state_key=_hashed_idempotency_state_key(scoped_key),
        scope=_IDEMPOTENCY_SCOPE,
        ttl_seconds=_IDEMPOTENCY_TTL_SECONDS,
        session_id=session_id,
    )
    if handle is None:
        return True
    _remember_lease(handle)
    return False


async def release_idempotency(key: str | None, *, session_id: str | None = None) -> None:
    """Release an idempotency key so it can be retried after failure."""
    scoped_key = _scoped_idempotency_key(key, session_id=session_id)
    if not scoped_key:
        return

    state_key = _hashed_idempotency_state_key(scoped_key)
    handle = _take_lease(state_key)
    if handle is None:
        return
    await asyncio.to_thread(_release_lease, handle)


async def acquire_expand_slot(session_id: str) -> bool:
    """Try to acquire the expand-itinerary slot for this session."""
    handle = await asyncio.to_thread(
        _acquire_lease,
        state_key=_lease_state_key(_EXPAND_SCOPE, session_id),
        scope=_EXPAND_SCOPE,
        ttl_seconds=_EXPAND_TTL_SECONDS,
        session_id=session_id,
    )
    if handle is None:
        return False
    _remember_lease(handle)
    return True


async def release_expand_slot(session_id: str) -> None:
    """Release the expand-itinerary slot for this session."""
    state_key = _lease_state_key(_EXPAND_SCOPE, session_id)
    handle = _take_lease(state_key)
    if handle is None:
        return
    await asyncio.to_thread(_release_lease, handle)
