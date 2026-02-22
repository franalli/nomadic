"""Session middleware safety checks."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

import app.middleware.session as session_middleware


def _build_app(*, with_csrf: bool = False) -> FastAPI:
    app = FastAPI()
    app.add_middleware(session_middleware.SessionMiddleware)
    if with_csrf:
        app.add_middleware(session_middleware.CSRFMiddleware)

    @app.get("/ok")
    async def ok() -> dict[str, bool]:
        return {"ok": True}

    if with_csrf:

        @app.delete("/api/session", status_code=204)
        async def reset_session() -> Response:
            return session_middleware.clear_session_cookies(Response(status_code=204))

    return app


def test_session_creation_throttle_enforced() -> None:
    session_middleware._session_creation_counter.clear()
    app = _build_app()

    statuses: list[int] = []
    max_sessions = session_middleware._MAX_SESSIONS_PER_IP_PER_HOUR

    for _ in range(max_sessions + 1):
        # New client each iteration => no session cookie reuse.
        with TestClient(app) as client:
            statuses.append(client.get("/ok").status_code)

    assert statuses.count(200) == max_sessions
    assert statuses[-1] == 429


def test_session_throttle_under_concurrency() -> None:
    session_middleware._session_creation_counter.clear()
    app = _build_app()

    # Lower threshold for deterministic test runtime.
    original_max = session_middleware._MAX_SESSIONS_PER_IP_PER_HOUR
    session_middleware._MAX_SESSIONS_PER_IP_PER_HOUR = 4

    try:

        def _request_once() -> int:
            with TestClient(app) as client:
                return client.get("/ok").status_code

        with ThreadPoolExecutor(max_workers=8) as executor:
            statuses = list(executor.map(lambda _: _request_once(), range(8)))

        assert all(code in {200, 429} for code in statuses)
        assert statuses.count(200) <= session_middleware._MAX_SESSIONS_PER_IP_PER_HOUR
    finally:
        session_middleware._MAX_SESSIONS_PER_IP_PER_HOUR = original_max


def test_delete_session_then_fresh_init_sets_csrf_cookie() -> None:
    session_middleware._session_creation_counter.clear()
    app = _build_app(with_csrf=True)
    original_cookie_domain = session_middleware.settings.cookie_domain
    session_middleware.settings.cookie_domain = None

    try:
        with TestClient(app) as client:
            response = client.get("/ok")
            assert response.status_code == 200
            csrf = client.cookies.get(session_middleware.CSRF_COOKIE_NAME)
            assert csrf

            response = client.delete("/api/session", headers={"X-CSRF-Token": csrf})
            assert response.status_code == 204

            client.cookies.clear()
            response = client.get("/ok")
            assert response.status_code == 200
            assert client.cookies.get(session_middleware.CSRF_COOKIE_NAME)
    finally:
        session_middleware.settings.cookie_domain = original_cookie_domain
