"""Unit tests for app.request_dedup backed by runtime_state leases."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import request_dedup as dedup_module
from app.db import Base
from app.db_models import RuntimeState
from app.request_dedup import (
    acquire_expand_slot,
    check_idempotency,
    release_expand_slot,
    release_idempotency,
)


@pytest.fixture(autouse=True)
def runtime_state_db(tmp_path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "request_dedup.sqlite"
    engine = create_engine(
        f"sqlite+pysqlite:///{db_path}",
        future=True,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    testing_session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        future=True,
    )
    Base.metadata.create_all(bind=engine, tables=[RuntimeState.__table__])
    monkeypatch.setattr(dedup_module.db_module, "SessionLocal", testing_session_local)
    dedup_module._active_lease_handles.set(None)

    yield testing_session_local

    dedup_module._active_lease_handles.set(None)
    Base.metadata.drop_all(bind=engine, tables=[RuntimeState.__table__])
    engine.dispose()


def _runtime_rows(testing_session_local: sessionmaker) -> list[RuntimeState]:
    with testing_session_local() as db:
        return list(db.execute(select(RuntimeState)).scalars())


@pytest.mark.asyncio
async def test_check_idempotency_new_key(runtime_state_db: sessionmaker):
    assert await check_idempotency("key-abc-123") is False

    rows = _runtime_rows(runtime_state_db)
    assert len(rows) == 1
    assert rows[0].state_key == dedup_module._hashed_idempotency_state_key("key-abc-123")
    assert rows[0].scope == "request_idempotency"


@pytest.mark.asyncio
async def test_check_idempotency_duplicate(runtime_state_db: sessionmaker):
    first = await check_idempotency("key-dup")
    second = await check_idempotency("key-dup")

    assert first is False
    assert second is True
    assert len(_runtime_rows(runtime_state_db)) == 1


@pytest.mark.asyncio
async def test_check_idempotency_none_or_empty_key(runtime_state_db: sessionmaker):
    assert await check_idempotency(None) is False
    assert await check_idempotency("") is False
    assert _runtime_rows(runtime_state_db) == []


@pytest.mark.asyncio
async def test_check_idempotency_same_key_different_sessions(runtime_state_db: sessionmaker):
    assert await check_idempotency("key-shared", session_id="session-a") is False
    assert await check_idempotency("key-shared", session_id="session-b") is False
    assert await check_idempotency("key-shared", session_id="session-a") is True
    assert await check_idempotency("key-shared", session_id="session-b") is True

    state_keys = {row.state_key for row in _runtime_rows(runtime_state_db)}
    assert state_keys == {
        dedup_module._hashed_idempotency_state_key("session-a:key-shared"),
        dedup_module._hashed_idempotency_state_key("session-b:key-shared"),
    }


@pytest.mark.asyncio
async def test_release_idempotency_is_session_scoped(runtime_state_db: sessionmaker):
    assert await check_idempotency("key-release", session_id="session-a") is False
    assert await check_idempotency("key-release", session_id="session-b") is False

    await release_idempotency("key-release", session_id="session-a")

    assert await check_idempotency("key-release", session_id="session-a") is False
    assert await check_idempotency("key-release", session_id="session-b") is True

    state_keys = {row.state_key for row in _runtime_rows(runtime_state_db)}
    assert state_keys == {
        dedup_module._hashed_idempotency_state_key("session-a:key-release"),
        dedup_module._hashed_idempotency_state_key("session-b:key-release"),
    }


@pytest.mark.asyncio
async def test_check_idempotency_hashes_max_length_keys(runtime_state_db: sessionmaker):
    session_id = "123e4567-e89b-12d3-a456-426614174000"
    long_key = "k" * 200

    assert await check_idempotency(long_key, session_id=session_id) is False
    assert await check_idempotency(long_key, session_id=session_id) is True

    rows = _runtime_rows(runtime_state_db)
    assert len(rows) == 1
    assert rows[0].state_key.startswith("lease:request_idempotency:sha256:")
    assert len(rows[0].state_key) < 255
    assert long_key not in rows[0].state_key


@pytest.mark.asyncio
async def test_check_idempotency_purges_expired_leases_globally(runtime_state_db: sessionmaker):
    stale_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    active_expires_at = datetime.now(UTC) + timedelta(seconds=30)
    with runtime_state_db() as db, db.begin():
        db.add(
            RuntimeState(
                state_key="lease:request_idempotency:stale-entry",
                state_type="lease",
                scope="request_idempotency",
                session_id="stale-session",
                expires_at=stale_expires_at,
                value_micro_usd=0,
            )
        )
        db.add(
            RuntimeState(
                state_key="lease:expand_mutex:active-session",
                state_type="lease",
                scope="expand_mutex",
                session_id="active-session",
                expires_at=active_expires_at,
                value_micro_usd=0,
            )
        )

    assert await check_idempotency("fresh-key") is False

    state_keys = {row.state_key for row in _runtime_rows(runtime_state_db)}
    assert "lease:request_idempotency:stale-entry" not in state_keys
    assert "lease:expand_mutex:active-session" in state_keys


@pytest.mark.asyncio
async def test_release_lease_does_not_delete_reacquired_incarnation(runtime_state_db: sessionmaker):
    state_key = "lease:expand_mutex:aba-session"

    first_handle = await asyncio.to_thread(
        dedup_module._acquire_lease,
        state_key=state_key,
        scope="expand_mutex",
        ttl_seconds=120,
        session_id="aba-session",
    )
    assert first_handle is not None

    with runtime_state_db() as db, db.begin():
        row = db.get(RuntimeState, state_key)
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    second_handle = await asyncio.to_thread(
        dedup_module._acquire_lease,
        state_key=state_key,
        scope="expand_mutex",
        ttl_seconds=120,
        session_id="aba-session",
    )
    assert second_handle is not None
    assert second_handle.lease_token != first_handle.lease_token

    await asyncio.to_thread(dedup_module._release_lease, first_handle)

    rows = _runtime_rows(runtime_state_db)
    assert len(rows) == 1
    assert rows[0].state_key == state_key
    assert rows[0].value_micro_usd == second_handle.lease_token


@pytest.mark.asyncio
async def test_acquire_expand_slot_persists_runtime_lease(runtime_state_db: sessionmaker):
    first = await acquire_expand_slot("session-1")
    second = await acquire_expand_slot("session-1")

    assert first is True
    assert second is False

    rows = _runtime_rows(runtime_state_db)
    assert len(rows) == 1
    assert rows[0].state_key == "lease:expand_mutex:session-1"
    assert rows[0].scope == "expand_mutex"


@pytest.mark.asyncio
async def test_release_then_reacquire_expand_slot(runtime_state_db: sessionmaker):
    assert await acquire_expand_slot("session-1") is True
    await release_expand_slot("session-1")
    assert await acquire_expand_slot("session-1") is True

    rows = _runtime_rows(runtime_state_db)
    assert len(rows) == 1
    assert rows[0].state_key == "lease:expand_mutex:session-1"


@pytest.mark.asyncio
async def test_acquire_expand_slot_independent_sessions(runtime_state_db: sessionmaker):
    assert await acquire_expand_slot("session-a") is True
    assert await acquire_expand_slot("session-b") is True
    assert await acquire_expand_slot("session-a") is False
    assert await acquire_expand_slot("session-b") is False

    state_keys = {row.state_key for row in _runtime_rows(runtime_state_db)}
    assert state_keys == {
        "lease:expand_mutex:session-a",
        "lease:expand_mutex:session-b",
    }


@pytest.mark.asyncio
async def test_concurrent_expand_acquire_is_single_winner(runtime_state_db: sessionmaker):
    n = 20
    results = await asyncio.gather(*(acquire_expand_slot("race-session") for _ in range(n)))

    assert results.count(True) == 1
    assert results.count(False) == n - 1
    assert len(_runtime_rows(runtime_state_db)) == 1
