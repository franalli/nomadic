import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.db import Base, get_async_db  # noqa: E402
from app.main import app  # noqa: E402
from tests.llm_stub import llm_json_for_prompt  # noqa: E402


@pytest.fixture(scope="module")
def _db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # Use a per-module temp DB to avoid leaking state into other tests.
    return tmp_path_factory.mktemp("graph_plan_conversation_flow") / "test.db"


class _EmptyTilesResponse:
    tiles: list = []


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
    return json.dumps(
        llm_json_for_prompt(prompt=prompt, user_message=user_message), ensure_ascii=False
    )


async def _patched_call_llm_force_router_unknown(
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
    if "Role: Intent router" in prompt or "Intent router" in prompt:
        return json.dumps(
            {
                "intent": "unknown",
                "topic": None,
                "user_intent": "detailed_planner",
                "confidence": 0.1,
                "notes": "unknown",
            }
        )
    return json.dumps(
        llm_json_for_prompt(prompt=prompt, user_message=user_message), ensure_ascii=False
    )


async def _patched_call_llm_force_router_correction(
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
    if "Role: Intent router" in prompt or "Intent router" in prompt:
        return json.dumps(
            {
                "intent": "correction_needed",
                "topic": None,
                "user_intent": "detailed_planner",
                "confidence": 0.9,
                "notes": "correction",
            }
        )
    return json.dumps(
        llm_json_for_prompt(prompt=prompt, user_message=user_message), ensure_ascii=False
    )


@pytest.fixture(autouse=True)
def _enable_route_and_disable_polish():
    original_route = settings.enable_graph_plan_route
    original_polish = settings.enable_response_polish
    settings.enable_graph_plan_route = True
    settings.enable_response_polish = False
    try:
        yield
    finally:
        settings.enable_graph_plan_route = original_route
        settings.enable_response_polish = original_polish


@pytest.fixture(scope="module", autouse=True)
def _setup_db_file(_db_path: Path):
    engine = create_engine(
        f"sqlite+pysqlite:///{_db_path.as_posix()}",
        future=True,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    yield


@pytest.fixture(scope="module")
def _async_session_maker(_db_path: Path):
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
    import asyncio

    asyncio.run(engine.dispose())


@pytest.fixture(autouse=True)
def _override_async_db(_async_session_maker):
    async def _override():
        async with _async_session_maker() as session:
            yield session

    app.dependency_overrides[get_async_db] = _override
    yield
    app.dependency_overrides.pop(get_async_db, None)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        # Cookie names are defined in app.middleware.session
        import uuid

        c.cookies.set("session_id", f"sess-{uuid.uuid4().hex}")
        c.cookies.set("csrf", f"csrf-{uuid.uuid4().hex}")
        yield c


def _post(client: TestClient, payload: dict, session_state: dict | None = None):
    body = dict(payload)
    if session_state is not None:
        body["session_state"] = session_state
    csrf = client.cookies.get("csrf")
    res = client.post(
        "/v1/graph_plan",
        json=body,
        headers={"X-CSRF-Token": csrf or "", "Content-Type": "application/json"},
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_graph_plan_casual_conversation_short_circuit(client):
    with (
        patch("app.plan_graph.call_llm_with_timeout", _patched_call_llm_with_timeout),
        patch("app.plan_graph.search_tiles", lambda *args, **kwargs: _EmptyTilesResponse()),
    ):
        out = _post(client, {"message": "hello"})

    assert out["document"]["assistant_message"]
    assert out["observability"]["router_intent"] in (
        None,
        "required_fields",
        "short_circuit:greeting",
    )
    assert out["document"]["trip_inputs"] == {} or "destinations" in out["document"]["trip_inputs"]


def test_graph_plan_one_way_flights_multi_turn(client):
    with (
        patch("app.plan_graph.call_llm_with_timeout", _patched_call_llm_with_timeout),
        patch("app.plan_graph.search_tiles", lambda *args, **kwargs: _EmptyTilesResponse()),
    ):
        turn1 = _post(
            client,
            {
                "message": "One-way flight from Rome to Dubai on 2026-01-10",
            },
        )
        assert turn1["observability"]["router_intent"] == "flights"
        assert turn1["document"]["trip_inputs"]["origin"] == "Rome"
        assert turn1["document"]["trip_inputs"]["destinations"] == ["Dubai"]
        assert turn1["document"]["trip_inputs"]["start_date"] == "2026-01-10"

        state = turn1["session_state"]

        turn2 = _post(client, {"message": "direct business class"}, session_state=state)
        assert turn2["observability"]["router_intent"] == "flights"

        ti2 = turn2["document"]["trip_inputs"]
        assert ti2["flight_settings"]["direct_only"] is True
        assert ti2["flight_settings"]["cabin_class"] == "business"

        state2 = turn2["session_state"]
        turn3 = _post(client, {"message": "GENERATE_PLAN_NOW"}, session_state=state2)
        assert turn3["document"]["ready_to_generate"] is True
        assert turn3["observability"]["monolith_used"] is True
        assert len(turn3["document"]["branches"]) >= 1

        for b in turn3["document"]["branches"]:
            tiles = b.get("tiles") or {}
            assert tiles.get("stays", []) == []
            assert tiles.get("flights", []) == []
            assert tiles.get("activities", []) == []


def test_graph_plan_full_trip_flight_hotel_activities(client):
    with (
        patch("app.plan_graph.call_llm_with_timeout", _patched_call_llm_with_timeout),
        patch("app.plan_graph.search_tiles", lambda *args, **kwargs: _EmptyTilesResponse()),
    ):
        t1 = _post(
            client,
            {
                "message": (
                    "Plan a trip from New York to Tokyo 2026-04-05 to 2026-04-12 for 2 adults. "
                    "I need flights and a hotel."
                )
            },
        )
        assert t1["document"]["trip_inputs"]["origin"] == "New York"
        assert t1["document"]["trip_inputs"]["destinations"] == ["Tokyo"]

        t2 = _post(
            client,
            {"message": "In Tokyo: 4-star hotel with breakfast and gym"},
            session_state=t1["session_state"],
        )
        assert t2["observability"]["router_intent"] == "hotels"
        ti2 = t2["document"]["trip_inputs"]
        assert ti2["hotel_settings"]["min_stars"] == 4
        assert set(ti2["hotel_settings"]["amenities"]) >= {"breakfast", "gym"}

        t3 = _post(
            client,
            {"message": "In Tokyo add food tours and temples"},
            session_state=t2["session_state"],
        )
        assert t3["observability"]["router_intent"] == "activities"


def test_graph_plan_transport_preferences_multi_turn(client):
    with (
        patch("app.plan_graph.call_llm_with_timeout", _patched_call_llm_with_timeout),
        patch("app.plan_graph.search_tiles", lambda *args, **kwargs: _EmptyTilesResponse()),
    ):
        t1 = _post(
            client,
            {
                "message": "Plan a trip from New York to Tokyo 2026-04-05 to 2026-04-12",
            },
        )

        t2 = _post(
            client,
            {"message": "In Tokyo we'll rent a car and take trains."},
            session_state=t1["session_state"],
        )
        assert t2["observability"]["router_intent"] == "transport"
        assert "transport" in (t2["document"]["assistant_message"] or "").lower()
        ti2 = t2["document"]["trip_inputs"]
        assert ti2["transport_settings"]["car"] is True
        assert ti2["transport_settings"]["train"] is True


def test_graph_plan_correction_needed_routes_to_correction_specialist(client):
    with (
        patch("app.plan_graph.call_llm_with_timeout", _patched_call_llm_force_router_correction),
        patch("app.plan_graph.search_tiles", lambda *args, **kwargs: _EmptyTilesResponse()),
    ):
        out = _post(
            client,
            {
                "message": "I want a beach vacation in Switzerland",
            },
        )

    assert out["observability"]["router_intent"] == "correction_needed"
    assert out["observability"]["monolith_used"] is False
    assert out["document"]["ready_to_generate"] is False
    assert (out["document"]["assistant_message"] or "").startswith("⚠️")
    assert len(out["document"].get("suggested_responses") or []) <= 3


def test_graph_plan_monolith_used_when_router_unknown(client):
    with (
        patch("app.plan_graph.call_llm_with_timeout", _patched_call_llm_force_router_unknown),
        patch("app.plan_graph.search_tiles", lambda *args, **kwargs: _EmptyTilesResponse()),
    ):
        out = _post(client, {"message": "do something weird"})

    assert out["observability"]["router_intent"] == "unknown"
    assert out["observability"]["monolith_used"] is True
    assert out["document"]["assistant_message"]


def test_graph_plan_multicity_intent_end_to_end(client):
    with (
        patch("app.plan_graph.call_llm_with_timeout", _patched_call_llm_with_timeout),
        patch("app.plan_graph.search_tiles", lambda *args, **kwargs: _EmptyTilesResponse()),
    ):
        t1 = _post(
            client,
            {
                "message": "Plan a trip from London to Paris and Rome 2026-05-10 to 2026-05-20",
            },
        )
        assert t1["document"]["trip_inputs"].get("destinations")

        t2 = _post(
            client,
            {"message": "Do it all together, one trip"},
            session_state=t1["session_state"],
        )

    assert t2["document"]["trip_inputs"].get("multi_city_intent") == "multi_city"
    assert t2["session_state"]["trip_inputs"].get("multi_city_intent") == "multi_city"


@pytest.mark.parametrize(
    "topic, message1, message2",
    [
        (
            "hiking",
            "I want an in-depth hiking trip from Milan to Chamonix on 2026-07-10",
            (
                "For my hiking trip from Milan to Chamonix on 2026-07-10: "
                "what gear and daily distance should we target?"
            ),
        ),
        (
            "boating",
            "Plan a boating trip from Split to Hvar on 2026-06-01",
            (
                "For my boating trip from Split to Hvar on 2026-06-01: "
                "skippered vs bareboat—what do you recommend?"
            ),
        ),
        (
            "cycling",
            "I want a cycling-focused trip from Amsterdam to Utrecht on 2026-05-15",
            (
                "For my cycling trip from Amsterdam to Utrecht on 2026-05-15: "
                "how long should each ride be, and what about safety?"
            ),
        ),
        (
            "diving",
            "I want a diving trip from Rome to Sharm El Sheikh on 2026-03-20",
            (
                "For my diving trip from Rome to Sharm El Sheikh on 2026-03-20: "
                "certification requirements and safety checklist?"
            ),
        ),
        (
            "skiing",
            "Plan a skiing trip from London to Geneva on 2026-02-05",
            (
                "For my skiing trip from London to Geneva on 2026-02-05: "
                "resort choice vs off-piste—what’s safest?"
            ),
        ),
    ],
)
def test_graph_plan_strategy_topics_in_depth(client, topic, message1, message2):
    with (
        patch("app.plan_graph.call_llm_with_timeout", _patched_call_llm_with_timeout),
        patch("app.plan_graph.search_tiles", lambda *args, **kwargs: _EmptyTilesResponse()),
    ):
        t1 = _post(client, {"message": message1})
        assert t1["observability"]["router_intent"] == "strategy"
        assert t1["observability"]["strategy_topic"] == topic
        assert t1["document"]["assistant_message"]

        t2 = _post(client, {"message": message2}, session_state=t1["session_state"])
        assert t2["observability"]["router_intent"] == "strategy"
        assert t2["observability"]["strategy_topic"] == topic
        assert t2["document"]["assistant_message"]
