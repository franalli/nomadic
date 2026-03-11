from __future__ import annotations

import json

import pytest
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.main import MAX_BODY_BYTES, limit_body_size


def _make_request(*chunks: bytes, method: str = "POST") -> Request:
    messages = [
        {
            "type": "http.request",
            "body": chunk,
            "more_body": idx < (len(chunks) - 1),
        }
        for idx, chunk in enumerate(chunks)
    ]

    async def receive():
        if messages:
            return messages.pop(0)
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": "/api/test",
        "raw_path": b"/api/test",
        "query_string": b"",
        "headers": [(b"transfer-encoding", b"chunked")],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }
    return Request(scope, receive)


@pytest.mark.asyncio
async def test_limit_body_size_allows_small_chunked_payload_and_preserves_body():
    request = _make_request(b'{"mes', b'sage":"ok"}')

    async def call_next(req: Request):
        body = await req.body()
        return JSONResponse({"size": len(body), "body": body.decode("utf-8")})

    response = await limit_body_size(request, call_next)

    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload == {"size": 16, "body": '{"message":"ok"}'}


@pytest.mark.asyncio
async def test_limit_body_size_rejects_oversized_chunked_payload_before_call_next():
    request = _make_request(b"a" * (MAX_BODY_BYTES - 10), b"b" * 32)
    called = False

    async def call_next(_req: Request):
        nonlocal called
        called = True
        return JSONResponse({"ok": True})

    response = await limit_body_size(request, call_next)

    assert response.status_code == 413
    assert not called
