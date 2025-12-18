import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.db_models as models  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Base  # noqa: E402
from app.plan_graph import plan_trip_graph  # noqa: E402
from app.schemas import PlanRequest  # noqa: E402
from tests.llm_stub import llm_json_for_prompt  # noqa: E402


@pytest.fixture(scope="function")
def _db_path(tmp_path: Path) -> Path:
    # Use a per-test temp DB for complete isolation.
    return tmp_path / "test.db"


class _EmptyTilesResponse:
    tiles: list = []


def _run(coro):
    return asyncio.run(coro)


async def _no_lock_get_or_create_session(
    db: AsyncSession, session_token: str, lock_for_update: bool = False
):
    from app.crud_trip import get_or_create_session as real

    # SQLite doesn't support SELECT ... FOR UPDATE; skip lock in tests.
    return await real(db, session_token=session_token, lock_for_update=False)


async def _patched_call_llm_with_timeout(
    *,
    model: str,
    prompt: str,
    timeout_seconds: float,
    max_tokens: int = 512,
    temperature: float = 0.2,
    history=None,
    user_message: str | None = None,
    top_p=None,
    max_retries: int = 1,
) -> str:
    payload = llm_json_for_prompt(prompt=prompt, user_message=user_message)
    return json_dumps(payload)


def json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


@pytest.fixture(autouse=True)
def _disable_response_polish():
    original = settings.enable_response_polish
    settings.enable_response_polish = False
    try:
        yield
    finally:
        settings.enable_response_polish = original


@pytest.fixture(scope="function", autouse=True)
def _setup_db(_db_path: Path):
    engine = create_engine(
        f"sqlite+pysqlite:///{_db_path.as_posix()}",
        future=True,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    yield


@pytest.fixture()
def async_session_maker(_db_path: Path):
    async_url = f"sqlite+aiosqlite:///{_db_path.as_posix()}"
    engine = create_async_engine(async_url, future=True, echo=False)
    maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    yield maker
    _run(engine.dispose())


def test_plan_trip_graph_casual_conversation_persists_db(async_session_maker):
    async def _test():
        session_token = "sess-casual"

        async with async_session_maker() as db:
            with (
                patch("app.plan_graph.get_or_create_session", _no_lock_get_or_create_session),
                patch("app.plan_graph.call_llm_with_timeout", _patched_call_llm_with_timeout),
            ):
                resp = await plan_trip_graph(
                    db, session_token, PlanRequest(message="hi", timezone="UTC")
                )

            assert resp.document.assistant_message
            assert (
                "?" in resp.document.assistant_message
                or "destination" in resp.document.assistant_message.lower()
            )

            # DB assertions: session + a trip context + user+assistant messages
            sess = (
                await db.execute(
                    select(models.Session).where(models.Session.session_token == session_token)
                )
            ).scalar_one()
            assert sess.id

            ctxs = (
                (
                    await db.execute(
                        select(models.TripContext).where(models.TripContext.session_id == sess.id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(ctxs) == 1

            msgs = (
                (
                    await db.execute(
                        select(models.ChatMessage)
                        .where(models.ChatMessage.trip_context_id == ctxs[0].id)
                        .order_by(models.ChatMessage.id)
                    )
                )
                .scalars()
                .all()
            )
            assert [m.role for m in msgs] == ["user", "assistant"]
            assert msgs[0].content.strip().lower() == "hi"
            assert msgs[1].content

            docs = (
                (
                    await db.execute(
                        select(models.PlanDocument)
                        .where(models.PlanDocument.session_id == sess.id)
                        .order_by(models.PlanDocument.id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(docs) == 1
            assert docs[0].version >= 1

    _run(_test())


def test_plan_trip_graph_one_way_flights_then_generate_branches(async_session_maker):
    async def _test():
        session_token = "sess-flight"

        with (
            patch("app.plan_graph.get_or_create_session", _no_lock_get_or_create_session),
            patch("app.plan_graph.call_llm_with_timeout", _patched_call_llm_with_timeout),
            patch("app.plan_graph.search_tiles", lambda *args, **kwargs: _EmptyTilesResponse()),
        ):
            async with async_session_maker() as db:
                r1 = await plan_trip_graph(
                    db,
                    session_token,
                    PlanRequest(
                        message="I need a one-way flight from Rome to Dubai, date flexible",
                        timezone="UTC",
                    ),
                )

                ti1 = r1.document.trip_inputs
                assert "Dubai" in (ti1.destinations or [])
                assert ti1.flight_settings and ti1.flight_settings.round_trip is False

                r2 = await plan_trip_graph(
                    db,
                    session_token,
                    PlanRequest(message="Direct, business class", timezone="UTC"),
                )

                ti2 = r2.document.trip_inputs
                assert ti2.flight_settings and ti2.flight_settings.direct_only is True
                assert ti2.flight_settings and ti2.flight_settings.cabin_class == "business"

                r3 = await plan_trip_graph(
                    db,
                    session_token,
                    PlanRequest(message="GENERATE_PLAN_NOW", timezone="UTC"),
                )

                assert r3.document.ready_to_generate is True
                assert r3.document.branches and len(r3.document.branches) >= 1

                # Keep tiles out (no tile_search persisted)
                for b in r3.document.branches:
                    assert b.tiles.stays == []
                    assert b.tiles.flights == []
                    assert b.tiles.activities == []

    _run(_test())


def test_plan_trip_graph_full_trip_flight_hotel_activities(async_session_maker):
    async def _test():
        session_token = "sess-full"

        with (
            patch("app.plan_graph.get_or_create_session", _no_lock_get_or_create_session),
            patch("app.plan_graph.call_llm_with_timeout", _patched_call_llm_with_timeout),
            patch("app.plan_graph.search_tiles", lambda *args, **kwargs: _EmptyTilesResponse()),
        ):
            async with async_session_maker() as db:
                r1 = await plan_trip_graph(
                    db,
                    session_token,
                    PlanRequest(
                        message=(
                            "Plan a trip from New York to Tokyo 2026-04-05 to 2026-04-12 "
                            "for 2 adults. "
                            "I need flights and a hotel."
                        ),
                        timezone="UTC",
                    ),
                )
                assert (
                    "tokyo" in (r1.document.assistant_message or "").lower()
                    or r1.document.assistant_message
                )

                r2 = await plan_trip_graph(
                    db,
                    session_token,
                    PlanRequest(
                        message="In Tokyo: 4-star hotel with breakfast and gym", timezone="UTC"
                    ),
                )

                ti2 = r2.document.trip_inputs
                assert ti2.hotel_settings and ti2.hotel_settings.min_stars == 4
                assert set(ti2.hotel_settings.amenities) >= {"breakfast", "gym"}

                r3 = await plan_trip_graph(
                    db,
                    session_token,
                    PlanRequest(
                        message="In Tokyo add food tours and temples, relaxed pace", timezone="UTC"
                    ),
                )

                ti3 = r3.document.trip_inputs
                assert ti3.activity_settings is not None

                r4 = await plan_trip_graph(
                    db,
                    session_token,
                    PlanRequest(message="GENERATE_PLAN_NOW", timezone="UTC"),
                )

                assert r4.document.ready_to_generate is True
                assert r4.document.branches and len(r4.document.branches) >= 1

                for b in r4.document.branches:
                    assert b.tiles.stays == []
                    assert b.tiles.flights == []
                    assert b.tiles.activities == []

    _run(_test())
