"""
Tests for shared trip and user account endpoints.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import app.db_models as models  # noqa: E402
import app.main as main_module  # noqa: E402
from app.db import Base, get_async_db, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.rate_limit import mark_trusted_session_id  # noqa: E402

TEST_DB_PATH = BACKEND_DIR / "test_share_and_auth_pytest.db"
TEST_DATABASE_URL = f"sqlite+pysqlite:///{TEST_DB_PATH.as_posix()}"
engine = create_engine(
    TEST_DATABASE_URL,
    future=True,
    connect_args={"check_same_thread": False, "timeout": 30},
)
async_engine = create_async_engine(
    f"sqlite+aiosqlite:///{TEST_DB_PATH.as_posix()}",
    future=True,
    echo=False,
)
TestingAsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)
TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
)

TEST_CSRF_TOKEN = "test-csrf-token-share-auth"


async def override_get_async_db():
    async with TestingAsyncSessionLocal() as db:
        yield db


def override_get_db():
    with TestingSessionLocal() as db:
        yield db


client = TestClient(app)


def setup_module(_: object):
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def teardown_module(_: object):
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    import asyncio

    asyncio.run(async_engine.dispose())
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


@pytest.fixture(autouse=True)
def override_dependencies():
    original_async = app.dependency_overrides.get(get_async_db)
    original_sync = app.dependency_overrides.get(get_db)

    app.dependency_overrides[get_async_db] = override_get_async_db
    app.dependency_overrides[get_db] = override_get_db
    yield

    if original_async is None:
        app.dependency_overrides.pop(get_async_db, None)
    else:
        app.dependency_overrides[get_async_db] = original_async

    if original_sync is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = original_sync


def set_client_cookies(
    *,
    session_token: str,
    csrf_token: str = TEST_CSRF_TOKEN,
    oauth_state: str | None = None,
) -> None:
    mark_trusted_session_id(session_token)
    client.cookies.set("session_id", session_token)
    client.cookies.set("csrf", csrf_token)
    if oauth_state is not None:
        client.cookies.set("oauth_state", oauth_state)


def current_csrf_headers() -> dict[str, str]:
    csrf_token = client.cookies.get("csrf")
    assert csrf_token
    return {"X-CSRF-Token": csrf_token}


def _document_payload(destination: str) -> dict:
    return {
        "trip_inputs": {
            "destination": destination,
            "start_date": "2026-04-01",
            "end_date": "2026-04-07",
            "activity_settings": {"categories": ["diving"]},
        },
        "tiles": {},
        "day_cards": [
            {
                "day_number": 1,
                "label": "Arrival",
                "blocks": [
                    {
                        "id": f"{destination.lower()}-arrival",
                        "period": "morning",
                        "activity_type": "arrival",
                        "summary": f"Arrive in {destination}",
                    }
                ],
            }
        ],
        "plan_view_state": "S3_ITINERARY_READY",
    }


def seed_session_with_document(
    *,
    session_token: str,
    with_itinerary: bool = True,
    destination: str = "Bali",
) -> models.Session:
    with TestingSessionLocal() as db:
        now = datetime.now(UTC)
        session = models.Session(
            session_token=session_token,
            last_activity_at=now,
            expires_at=now + timedelta(days=90),
        )
        db.add(session)
        db.flush()

        day_cards = []
        if with_itinerary:
            day_cards = [
                {
                    "day_number": 1,
                    "label": "Arrival",
                    "blocks": [
                        {
                            "id": "block-1",
                            "period": "morning",
                            "activity_type": "arrival",
                            "summary": "Arrive and settle in",
                            "image_url": "/api/media/google-places-photo?name=test",
                        }
                    ],
                }
            ]

        doc = models.PlanDocument(
            session_id=session.id,
            version=1,
            updated_by="planner",
            document={
                "trip_inputs": {
                    "destination": destination,
                    "start_date": "2026-04-01",
                    "end_date": "2026-04-07",
                    "activity_settings": {"categories": ["diving"]},
                },
                "tiles": {
                    "tile-1": {
                        "id": "tile-1",
                        "type": "activity",
                        "title": "Shore dive",
                        "deeplink": "https://example.com/activity",
                        "image_url": "/api/media/google-places-photo?name=tile",
                    }
                },
                "day_cards": day_cards,
                "plan_view_state": "S3_ITINERARY_READY",
            },
        )
        db.add(doc)
        db.commit()
        db.refresh(session)
        return session


def test_create_shared_trip_requires_itinerary():
    session = seed_session_with_document(session_token="share-no-itinerary", with_itinerary=False)
    set_client_cookies(session_token=session.session_token)

    response = client.post("/api/share", headers={"X-CSRF-Token": TEST_CSRF_TOKEN})

    assert response.status_code == 400
    assert "Build your itinerary" in response.json()["detail"]


def test_create_and_get_shared_trip_snapshot():
    session = seed_session_with_document(session_token="share-success", with_itinerary=True)
    set_client_cookies(session_token=session.session_token)

    create_response = client.post("/api/share", headers={"X-CSRF-Token": TEST_CSRF_TOKEN})
    assert create_response.status_code == 200
    payload = create_response.json()
    assert payload["slug"]
    assert payload["url"].endswith(f"/trip/{payload['slug']}")

    get_response = client.get(f"/api/shared/{payload['slug']}")
    assert get_response.status_code == 200
    shared = get_response.json()
    assert shared["slug"] == payload["slug"]
    assert shared["snapshot"]["tiles"]["tile-1"]["image_url"] is None
    assert shared["snapshot"]["day_cards"][0]["blocks"][0]["image_url"] is None


def test_create_shared_trip_retries_on_slug_conflict(monkeypatch):
    session = seed_session_with_document(session_token="share-slug-retry", with_itinerary=True)
    set_client_cookies(session_token=session.session_token)

    with TestingSessionLocal() as db:
        db.add(
            models.SharedTrip(
                slug="dupslug1",
                session_id=session.id,
                snapshot={"day_cards": []},
                title="Existing",
            )
        )
        db.commit()

    generated = iter(["dupslug1", "freshslug"])

    def _fake_generate_slug() -> str:
        return next(generated)

    monkeypatch.setattr("app.services.sharing.generate_slug", _fake_generate_slug)

    create_response = client.post("/api/share", headers={"X-CSRF-Token": TEST_CSRF_TOKEN})
    assert create_response.status_code == 200
    assert create_response.json()["slug"] == "freshslug"


def test_shared_trip_expired_returns_410():
    with TestingSessionLocal() as db:
        session = models.Session(
            session_token="share-expired",
            last_activity_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=90),
        )
        db.add(session)
        db.flush()
        shared = models.SharedTrip(
            slug="expired01",
            session_id=session.id,
            snapshot={"day_cards": []},
            title="Expired",
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        db.add(shared)
        db.commit()

    response = client.get("/api/shared/expired01")
    assert response.status_code == 410


def test_fork_shared_trip_copies_snapshot_to_viewer_session():
    owner = seed_session_with_document(session_token="share-fork-owner", with_itinerary=True)
    set_client_cookies(session_token=owner.session_token)
    create_response = client.post("/api/share", headers={"X-CSRF-Token": TEST_CSRF_TOKEN})
    assert create_response.status_code == 200
    slug = create_response.json()["slug"]

    viewer_token = "share-fork-viewer"
    set_client_cookies(session_token=viewer_token)
    fork_response = client.post(
        f"/api/share/fork/{slug}",
        headers={"X-CSRF-Token": TEST_CSRF_TOKEN},
    )
    assert fork_response.status_code == 200
    set_cookie_header = fork_response.headers.get("set-cookie", "")
    assert "session_id=" in set_cookie_header
    cookie = SimpleCookie()
    cookie.load(set_cookie_header)
    fork_session_token = cookie["session_id"].value
    fork_csrf_token = cookie["csrf"].value
    assert fork_session_token
    assert fork_session_token != viewer_token
    assert fork_csrf_token
    assert fork_csrf_token != TEST_CSRF_TOKEN
    fork_payload = fork_response.json()
    assert fork_payload["ok"] is True
    assert fork_payload["destination"] == "Bali"
    assert fork_payload["day_count"] == 1

    with TestingSessionLocal() as db:
        viewer_session = (
            db.query(models.Session)
            .filter(models.Session.session_token == fork_session_token)
            .one()
        )
        viewer_doc = (
            db.query(models.PlanDocument)
            .filter(models.PlanDocument.session_id == viewer_session.id)
            .one()
        )
        viewer_payload = viewer_doc.document or {}
        assert viewer_payload.get("trip_inputs", {}).get("destination") == "Bali"
        assert len(viewer_payload.get("day_cards", [])) == 1
        assert viewer_payload.get("tiles", {}).get("tile-1", {}).get("id") == "tile-1"

        owner_doc = (
            db.query(models.PlanDocument).filter(models.PlanDocument.session_id == owner.id).one()
        )
        owner_payload = owner_doc.document or {}
        assert owner_payload.get("trip_inputs", {}).get("destination") == "Bali"
        assert len(owner_payload.get("day_cards", [])) == 1


def test_fork_shared_trip_expired_returns_410():
    with TestingSessionLocal() as db:
        owner_session = models.Session(
            session_token="share-fork-expired-owner",
            last_activity_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=90),
        )
        db.add(owner_session)
        db.flush()
        db.add(
            models.SharedTrip(
                slug="forkexp01",
                session_id=owner_session.id,
                snapshot={"day_cards": []},
                title="Expired Fork",
                expires_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        db.commit()

    set_client_cookies(session_token="share-fork-expired-viewer")
    response = client.post(
        "/api/share/fork/forkexp01",
        headers={"X-CSRF-Token": TEST_CSRF_TOKEN},
    )
    assert response.status_code == 410


def test_shared_trip_get_without_cookies_does_not_issue_session_cookie():
    session = seed_session_with_document(session_token="share-public-read", with_itinerary=True)
    set_client_cookies(session_token=session.session_token)
    create_response = client.post("/api/share", headers={"X-CSRF-Token": TEST_CSRF_TOKEN})
    assert create_response.status_code == 200
    slug = create_response.json()["slug"]

    client.cookies.clear()
    response = client.get(f"/api/shared/{slug}")
    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "")
    assert "session_id=" not in set_cookie


def test_reset_session_preserves_shared_trip_snapshot():
    session = seed_session_with_document(session_token="share-reset-survives", with_itinerary=True)
    set_client_cookies(session_token=session.session_token)
    create_response = client.post("/api/share", headers={"X-CSRF-Token": TEST_CSRF_TOKEN})
    assert create_response.status_code == 200
    slug = create_response.json()["slug"]

    reset_response = client.delete("/api/session", headers={"X-CSRF-Token": TEST_CSRF_TOKEN})
    assert reset_response.status_code == 204

    with TestingSessionLocal() as db:
        shared = db.query(models.SharedTrip).filter(models.SharedTrip.slug == slug).one()
        assert shared.session_id is None

    client.cookies.clear()
    public_response = client.get(f"/api/shared/{slug}")
    assert public_response.status_code == 200


def test_google_callback_links_user_and_trip_listing(monkeypatch):
    session = seed_session_with_document(session_token="auth-link", with_itinerary=True)

    monkeypatch.setattr(main_module.settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(main_module.settings, "google_oauth_client_secret", "client-secret")

    async def _fake_exchange_google_code(code: str, redirect_uri: str):
        assert code == "test-code"
        assert redirect_uri.endswith("/auth/callback")
        return {
            "sub": "google-user-123",
            "email": "user@example.com",
            "name": "Test User",
            "picture": "https://example.com/avatar.png",
        }

    monkeypatch.setattr("app.auth.exchange_google_code", _fake_exchange_google_code)

    set_client_cookies(session_token=session.session_token, oauth_state="state-123")
    callback_response = client.post(
        "/api/auth/google/callback",
        headers={"X-CSRF-Token": TEST_CSRF_TOKEN},
        json={"code": "test-code", "state": "state-123"},
    )
    assert callback_response.status_code == 200
    assert callback_response.json()["user"]["email"] == "user@example.com"
    set_cookie_header = callback_response.headers.get("set-cookie", "")
    assert "session_id=" in set_cookie_header
    cookie = SimpleCookie()
    cookie.load(set_cookie_header)
    rotated_session_token = cookie["session_id"].value
    rotated_csrf_token = cookie["csrf"].value
    client.cookies.set("session_id", rotated_session_token)
    assert rotated_session_token
    assert rotated_session_token != session.session_token
    assert rotated_csrf_token
    assert rotated_csrf_token != TEST_CSRF_TOKEN
    with TestingSessionLocal() as db:
        old_session = (
            db.query(models.Session)
            .filter(models.Session.session_token == session.session_token)
            .one_or_none()
        )
        assert old_session is None
        new_session = (
            db.query(models.Session)
            .filter(models.Session.session_token == rotated_session_token)
            .one_or_none()
        )
        assert new_session is not None
        assert new_session.user_id is not None

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["user"]["name"] == "Test User"

    trips_response = client.get("/api/trips")
    assert trips_response.status_code == 200
    trips = trips_response.json()["trips"]
    assert len(trips) == 1
    assert isinstance(trips[0]["trip_id"], int)
    assert trips[0]["destination"] == "Bali"

    logout_response = client.post("/api/auth/logout", headers=current_csrf_headers())
    assert logout_response.status_code == 200
    assert logout_response.json()["ok"] is True

    me_after_logout = client.get("/api/auth/me")
    assert me_after_logout.status_code == 200
    assert me_after_logout.json()["user"] is None


def test_cross_account_login_does_not_leak_previous_user_trips(monkeypatch):
    session = seed_session_with_document(
        session_token="auth-cross-account",
        with_itinerary=True,
        destination="Bali",
    )

    monkeypatch.setattr(main_module.settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(main_module.settings, "google_oauth_client_secret", "client-secret")

    async def _fake_exchange_google_code(code: str, _redirect_uri: str):
        if code == "code-user-a":
            return {
                "sub": "google-user-a",
                "email": "a@example.com",
                "name": "User A",
                "picture": "https://example.com/a.png",
            }
        return {
            "sub": "google-user-b",
            "email": "b@example.com",
            "name": "User B",
            "picture": "https://example.com/b.png",
        }

    monkeypatch.setattr("app.auth.exchange_google_code", _fake_exchange_google_code)

    set_client_cookies(session_token=session.session_token, oauth_state="state-a")
    callback_a = client.post(
        "/api/auth/google/callback",
        headers={"X-CSRF-Token": TEST_CSRF_TOKEN},
        json={"code": "code-user-a", "state": "state-a"},
    )
    assert callback_a.status_code == 200
    cookie_a = SimpleCookie()
    cookie_a.load(callback_a.headers.get("set-cookie", ""))
    token_user_a = cookie_a["session_id"].value
    client.cookies.set("session_id", token_user_a)

    trips_a = client.get("/api/trips")
    assert trips_a.status_code == 200
    assert trips_a.json()["trips"][0]["destination"] == "Bali"

    logout_response = client.post("/api/auth/logout", headers=current_csrf_headers())
    assert logout_response.status_code == 200
    set_cookie = logout_response.headers.get("set-cookie", "")
    assert "session_id=" in set_cookie
    assert "Max-Age=0" in set_cookie

    # Simulate stale-cookie replay on shared browser; server must not leak User A data.
    client.cookies.set("session_id", token_user_a)
    client.cookies.set("csrf", TEST_CSRF_TOKEN)
    client.cookies.set("oauth_state", "state-b")
    callback_b = client.post(
        "/api/auth/google/callback",
        headers={"X-CSRF-Token": TEST_CSRF_TOKEN},
        json={"code": "code-user-b", "state": "state-b"},
    )
    assert callback_b.status_code == 200
    cookie_b = SimpleCookie()
    cookie_b.load(callback_b.headers.get("set-cookie", ""))
    token_user_b = cookie_b["session_id"].value
    client.cookies.set("session_id", token_user_b)

    trips_b = client.get("/api/trips")
    assert trips_b.status_code == 200
    assert trips_b.json()["trips"] == []

    with TestingSessionLocal() as db:
        user_a = db.query(models.User).filter(models.User.google_id == "google-user-a").one()
        user_b = db.query(models.User).filter(models.User.google_id == "google-user-b").one()
        assert user_a.id != user_b.id
        user_a_sessions = db.query(models.Session).filter(models.Session.user_id == user_a.id).all()
        user_b_sessions = db.query(models.Session).filter(models.Session.user_id == user_b.id).all()
        assert len(user_a_sessions) == 1
        assert len(user_b_sessions) == 1


def test_google_callback_rejects_invalid_state(monkeypatch):
    session = seed_session_with_document(session_token="auth-invalid-state", with_itinerary=True)
    monkeypatch.setattr(main_module.settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(main_module.settings, "google_oauth_client_secret", "client-secret")
    set_client_cookies(session_token=session.session_token, oauth_state="expected-state")

    response = client.post(
        "/api/auth/google/callback",
        headers={"X-CSRF-Token": TEST_CSRF_TOKEN},
        json={"code": "unused", "state": "wrong-state"},
    )
    assert response.status_code == 403
    assert "Invalid OAuth state" in response.json()["detail"]


def test_google_callback_exchange_errors_map_to_401_and_502(monkeypatch):
    session = seed_session_with_document(session_token="auth-exchange-errors", with_itinerary=True)
    monkeypatch.setattr(main_module.settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(main_module.settings, "google_oauth_client_secret", "client-secret")
    set_client_cookies(session_token=session.session_token, oauth_state="state-err")

    async def _http_status_error(_code: str, _redirect_uri: str):
        request = httpx.Request("POST", "https://oauth2.googleapis.com/token")
        response = httpx.Response(status_code=400, request=request)
        raise httpx.HTTPStatusError("bad request", request=request, response=response)

    monkeypatch.setattr("app.auth.exchange_google_code", _http_status_error)
    auth_failed = client.post(
        "/api/auth/google/callback",
        headers={"X-CSRF-Token": TEST_CSRF_TOKEN},
        json={"code": "bad-code", "state": "state-err"},
    )
    assert auth_failed.status_code == 401

    async def _http_error(_code: str, _redirect_uri: str):
        raise httpx.HTTPError("network down")

    monkeypatch.setattr("app.auth.exchange_google_code", _http_error)
    unavailable = client.post(
        "/api/auth/google/callback",
        headers={"X-CSRF-Token": TEST_CSRF_TOKEN},
        json={"code": "bad-code", "state": "state-err"},
    )
    assert unavailable.status_code == 502


def test_google_auth_url_response_contract(monkeypatch):
    monkeypatch.setattr(main_module.settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(main_module.settings, "google_oauth_client_secret", "client-secret")

    response = client.get("/api/auth/google/url")
    assert response.status_code == 200

    payload = response.json()
    assert "url" in payload
    assert isinstance(payload["url"], str)
    assert payload["url"].startswith("https://accounts.google.com/o/oauth2/")
    assert "session_id" not in payload
    assert "session_token" not in payload

    parsed = urlparse(payload["url"])
    params = parse_qs(parsed.query)
    assert "state" in params
    assert "client_id" in params
    assert "redirect_uri" in params


def test_google_auth_url_sets_oauth_state_cookie_flags(monkeypatch):
    monkeypatch.setattr(main_module.settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(main_module.settings, "google_oauth_client_secret", "client-secret")

    response = client.get("/api/auth/google/url")
    assert response.status_code == 200
    set_cookie_header = response.headers.get("set-cookie", "")
    assert "oauth_state=" in set_cookie_header
    assert "HttpOnly" in set_cookie_header
    assert "Max-Age=600" in set_cookie_header
    assert "SameSite=lax" in set_cookie_header


def test_auth_google_url_rate_limit_not_bypassable_with_rotating_cookies(monkeypatch):
    monkeypatch.setattr(main_module.settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(main_module.settings, "google_oauth_client_secret", "client-secret")

    for i in range(20):
        client.cookies.clear()
        client.cookies.set("session_id", f"forged-session-{i}")
        response = client.get("/api/auth/google/url")
        if response.status_code == 429:
            return
    pytest.fail("Expected 429 on /api/auth/google/url despite rotating forged session cookies")


def test_shared_trip_rate_limit_not_bypassable_with_rotating_cookies(monkeypatch):
    monkeypatch.setattr(main_module.settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(main_module.settings, "google_oauth_client_secret", "client-secret")

    session = seed_session_with_document(session_token="shared-rate-limit", with_itinerary=True)
    set_client_cookies(session_token=session.session_token)
    create_response = client.post("/api/share", headers={"X-CSRF-Token": TEST_CSRF_TOKEN})
    assert create_response.status_code == 200
    slug = create_response.json()["slug"]

    for i in range(40):
        client.cookies.clear()
        client.cookies.set("session_id", f"rotating-cookie-{i}")
        response = client.get(f"/api/shared/{slug}")
        if response.status_code == 429:
            return
        assert response.status_code == 200
    pytest.fail("Expected 429 on /api/shared/{slug} despite rotating forged session cookies")


def test_google_callback_requires_csrf_header(monkeypatch):
    session = seed_session_with_document(
        session_token="callback-csrf-required", with_itinerary=True
    )
    monkeypatch.setattr(main_module.settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(main_module.settings, "google_oauth_client_secret", "client-secret")

    set_client_cookies(session_token=session.session_token, oauth_state="state-123")
    response = client.post(
        "/api/auth/google/callback",
        json={"code": "unused", "state": "state-123"},
    )
    assert response.status_code == 403


def test_share_requires_csrf_header():
    session = seed_session_with_document(session_token="share-csrf-required", with_itinerary=True)
    set_client_cookies(session_token=session.session_token)

    response = client.post("/api/share")
    assert response.status_code == 403


def test_logout_requires_csrf_header():
    session = seed_session_with_document(session_token="logout-csrf-required", with_itinerary=True)
    set_client_cookies(session_token=session.session_token)

    response = client.post("/api/auth/logout")
    assert response.status_code == 403


def test_trips_requires_login():
    session = seed_session_with_document(session_token="trips-anon", with_itinerary=True)
    set_client_cookies(session_token=session.session_token)
    response = client.get("/api/trips")
    assert response.status_code == 401


def test_resume_trip_requires_login():
    client.cookies.clear()
    client.cookies.set("csrf", TEST_CSRF_TOKEN)
    response = client.post(
        "/api/trips/999/resume",
        headers={"X-CSRF-Token": TEST_CSRF_TOKEN},
    )
    assert response.status_code == 401


def test_resume_trip_requires_csrf_header():
    with TestingSessionLocal() as db:
        user = models.User(
            google_id="resume-csrf-user",
            email="resume-csrf@example.com",
            name="Resume Csrf User",
        )
        db.add(user)
        db.flush()

        now = datetime.now(UTC)
        session = models.Session(
            session_token="resume-csrf-session",
            user_id=user.id,
            last_activity_at=now,
            expires_at=now + timedelta(days=90),
        )
        db.add(session)
        db.flush()
        db.add(
            models.PlanDocument(
                session_id=session.id,
                version=1,
                updated_by="planner",
                document=_document_payload("Madrid"),
            )
        )
        db.commit()

    set_client_cookies(session_token="resume-csrf-session")
    response = client.post("/api/trips/1/resume")
    assert response.status_code == 403


def test_resume_trip_switches_active_session_to_selected_trip():
    with TestingSessionLocal() as db:
        user = models.User(
            google_id="resume-user",
            email="resume@example.com",
            name="Resume User",
        )
        db.add(user)
        db.flush()

        now = datetime.now(UTC)
        session_a = models.Session(
            session_token="resume-session-a",
            user_id=user.id,
            last_activity_at=now,
            expires_at=now + timedelta(days=90),
        )
        session_b = models.Session(
            session_token="resume-session-b",
            user_id=user.id,
            last_activity_at=now,
            expires_at=now + timedelta(days=90),
        )
        db.add_all([session_a, session_b])
        db.flush()

        doc_a = models.PlanDocument(
            session_id=session_a.id,
            version=1,
            updated_by="planner",
            document=_document_payload("Bali"),
        )
        doc_b = models.PlanDocument(
            session_id=session_b.id,
            version=1,
            updated_by="planner",
            document=_document_payload("Tokyo"),
        )
        db.add_all([doc_a, doc_b])
        db.commit()
        trip_id_to_resume = doc_b.id

    set_client_cookies(session_token="resume-session-a")
    response = client.post(
        f"/api/trips/{trip_id_to_resume}/resume",
        headers={"X-CSRF-Token": TEST_CSRF_TOKEN},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "trip_id": trip_id_to_resume}

    set_cookie_header = response.headers.get("set-cookie", "")
    assert "session_id=" in set_cookie_header
    cookie = SimpleCookie()
    cookie.load(set_cookie_header)
    rotated_token = cookie["session_id"].value
    rotated_csrf_token = cookie["csrf"].value
    assert rotated_token
    assert rotated_token not in {"resume-session-a", "resume-session-b"}
    assert rotated_csrf_token
    assert rotated_csrf_token != TEST_CSRF_TOKEN
    client.cookies.set("session_id", rotated_token)

    doc_response = client.get("/api/document")
    assert doc_response.status_code == 200
    document = doc_response.json().get("document") or {}
    trip_inputs = document.get("trip_inputs") or {}
    assert trip_inputs.get("destination") == "Tokyo"


def test_resume_trip_rejects_non_owned_trip():
    with TestingSessionLocal() as db:
        user_a = models.User(
            google_id="resume-user-a",
            email="resume-a@example.com",
            name="Resume User A",
        )
        user_b = models.User(
            google_id="resume-user-b",
            email="resume-b@example.com",
            name="Resume User B",
        )
        db.add_all([user_a, user_b])
        db.flush()

        now = datetime.now(UTC)
        user_a_session = models.Session(
            session_token="resume-owned-a",
            user_id=user_a.id,
            last_activity_at=now,
            expires_at=now + timedelta(days=90),
        )
        user_b_session = models.Session(
            session_token="resume-owned-b",
            user_id=user_b.id,
            last_activity_at=now,
            expires_at=now + timedelta(days=90),
        )
        db.add_all([user_a_session, user_b_session])
        db.flush()

        user_a_doc = models.PlanDocument(
            session_id=user_a_session.id,
            version=1,
            updated_by="planner",
            document=_document_payload("Lisbon"),
        )
        user_b_doc = models.PlanDocument(
            session_id=user_b_session.id,
            version=1,
            updated_by="planner",
            document=_document_payload("Seoul"),
        )
        db.add_all([user_a_doc, user_b_doc])
        db.commit()
        other_trip_id = user_b_doc.id

    set_client_cookies(session_token="resume-owned-a")
    response = client.post(
        f"/api/trips/{other_trip_id}/resume",
        headers={"X-CSRF-Token": TEST_CSRF_TOKEN},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Trip not found"


def test_resume_trip_old_cookie_becomes_invalid_after_rotation():
    with TestingSessionLocal() as db:
        user = models.User(
            google_id="resume-rotate-user",
            email="resume-rotate@example.com",
            name="Resume Rotate User",
        )
        db.add(user)
        db.flush()

        now = datetime.now(UTC)
        session_a = models.Session(
            session_token="resume-rotate-a",
            user_id=user.id,
            last_activity_at=now,
            expires_at=now + timedelta(days=90),
        )
        session_b = models.Session(
            session_token="resume-rotate-b",
            user_id=user.id,
            last_activity_at=now,
            expires_at=now + timedelta(days=90),
        )
        db.add_all([session_a, session_b])
        db.flush()
        db.add(
            models.PlanDocument(
                session_id=session_a.id,
                version=1,
                updated_by="planner",
                document=_document_payload("Prague"),
            )
        )
        doc_b = models.PlanDocument(
            session_id=session_b.id,
            version=1,
            updated_by="planner",
            document=_document_payload("Osaka"),
        )
        db.add(doc_b)
        db.commit()
        target_trip_id = doc_b.id

    old_token = "resume-rotate-a"
    set_client_cookies(session_token=old_token)
    first_resume = client.post(
        f"/api/trips/{target_trip_id}/resume",
        headers={"X-CSRF-Token": TEST_CSRF_TOKEN},
    )
    assert first_resume.status_code == 200
    first_cookie_header = first_resume.headers.get("set-cookie", "")
    first_cookie = SimpleCookie()
    first_cookie.load(first_cookie_header)
    first_rotated_token = first_cookie["session_id"].value
    first_rotated_csrf = first_cookie["csrf"].value
    assert first_rotated_token
    assert first_rotated_csrf
    assert first_rotated_csrf != TEST_CSRF_TOKEN

    # Simulate second rapid click from original session cookie.
    client.cookies.set("session_id", old_token)
    client.cookies.set("csrf", TEST_CSRF_TOKEN)
    second_resume = client.post(
        f"/api/trips/{target_trip_id}/resume",
        headers={"X-CSRF-Token": TEST_CSRF_TOKEN},
    )
    assert second_resume.status_code == 200
    second_cookie_header = second_resume.headers.get("set-cookie", "")
    second_cookie = SimpleCookie()
    second_cookie.load(second_cookie_header)
    second_rotated_token = second_cookie["session_id"].value
    assert second_rotated_token
    assert first_rotated_token != second_rotated_token

    # First rotated token is now stale and should no longer authenticate.
    client.cookies.set("session_id", first_rotated_token)
    stale_read = client.get("/api/trips")
    assert stale_read.status_code == 401


def test_admin_clear_all_caches_clears_validation_cache(monkeypatch):
    async def _seed_validation_state() -> None:
        from app.validation import clear_cache
        from app.validation_cache import _check_rate_limit, store_result

        await clear_cache(preserve_rate_limiting=False)
        await store_result(
            "destination",
            "bali",
            {
                "corrected_values": ["Bali"],
                "is_valid": True,
                "reason": None,
            },
            True,
            None,
        )
        await _check_rate_limit("admin-clear-validation")

    monkeypatch.setattr(main_module.settings, "admin_api_key", "admin-key")
    asyncio.run(_seed_validation_state())
    set_client_cookies(session_token="admin-clear-validation")

    response = client.post(
        "/api/admin/clear-all-caches",
        headers={**current_csrf_headers(), "X-Admin-Key": "admin-key"},
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["before"]["validation"]["positive"] >= 1
    assert payload["before"]["validation"]["rate_counters"] >= 1
    assert payload["after"]["validation"]["positive"] == 0
    assert payload["after"]["validation"]["negative"] == 0
    assert payload["after"]["validation"]["split"] == 0
    assert payload["after"]["validation"]["prompt"] == 0
    assert payload["after"]["validation"]["fallback"] == 0
    assert payload["after"]["validation"]["rate_counters"] == 0
