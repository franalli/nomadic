import pytest
from starlette.requests import Request

from app.rate_limit import (
    _clear_trusted_session_ids_for_tests,
    _rate_key,
    mark_trusted_session_id,
)


def _build_request(path: str, cookie_header: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if cookie_header:
        headers.append((b"cookie", cookie_header.encode("utf-8")))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 54321),
        "server": ("testserver", 80),
        "root_path": "",
    }
    return Request(scope)


@pytest.fixture(autouse=True)
def _clear_trusted_cache() -> None:
    _clear_trusted_session_ids_for_tests()


def test_public_shared_path_rate_key_is_ip_only():
    req_a = _build_request("/api/shared/slug-1", "session_id=forged-a")
    req_b = _build_request("/api/shared/slug-1", "session_id=forged-b")
    assert _rate_key(req_a) == _rate_key(req_b)


def test_public_auth_path_rate_key_is_ip_only():
    req_a = _build_request("/api/auth/google/url", "session_id=forged-a")
    req_b = _build_request("/api/auth/google/url", "session_id=forged-b")
    assert _rate_key(req_a) == _rate_key(req_b)


def test_non_public_path_untrusted_cookie_falls_back_to_ip():
    req_a = _build_request("/api/graph_plan/stream", "session_id=forged-a")
    req_b = _build_request("/api/graph_plan/stream", "session_id=forged-b")
    assert _rate_key(req_a) == _rate_key(req_b)


def test_non_public_path_trusted_cookie_uses_session_bucket():
    trusted = "trusted-session-id"
    mark_trusted_session_id(trusted)
    req = _build_request("/api/trips", f"session_id={trusted}")
    assert _rate_key(req) == trusted
