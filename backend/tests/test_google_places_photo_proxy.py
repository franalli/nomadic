from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx
from fastapi.testclient import TestClient

import app.main as main_module
from app.db import get_async_db
from app.main import app

PHOTO_NAME = "places/ChIJx/photos/AbCd_123"


async def _override_get_async_db():
    yield SimpleNamespace()


class _FakePlacesPhotoClient:
    is_closed = False

    def __init__(self, *args, **kwargs):
        _ = (args, kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        _ = (exc_type, exc, tb)
        return False

    async def aclose(self):
        self.is_closed = True

    async def get(self, *args, **kwargs):
        _ = (args, kwargs)
        return httpx.Response(
            status_code=200,
            content=b"jpeg-bytes",
            headers={
                "content-type": "image/jpeg",
                "content-length": str(len(b"jpeg-bytes")),
            },
        )


def test_signed_photo_url_round_trip(monkeypatch) -> None:
    app.dependency_overrides[get_async_db] = _override_get_async_db
    original_cookie_domain = main_module.settings.cookie_domain
    main_module.settings.cookie_domain = None
    monkeypatch.setattr(main_module.settings, "google_maps_api_key", "fake-key", raising=False)
    monkeypatch.setattr(
        main_module.settings, "media_proxy_signing_key", "test-signing-key", raising=False
    )
    monkeypatch.setattr(main_module, "get_session_by_token", AsyncMock(return_value=object()))
    monkeypatch.setattr(main_module.httpx, "AsyncClient", _FakePlacesPhotoClient)

    try:
        with TestClient(app) as client:
            signed = client.get(
                "/api/media/google-places-photo-url",
                params={
                    "name": PHOTO_NAME,
                    "max_width": 320,
                    "max_height": 240,
                    "ttl_seconds": 300,
                },
            )
            assert signed.status_code == 200
            signed_url = signed.json()["url"]
            assert "/api/media/google-places-photo?" in signed_url

            image = client.get(signed_url)
            assert image.status_code == 200
            assert image.headers["content-type"].startswith("image/")
            assert image.content == b"jpeg-bytes"
    finally:
        main_module.settings.cookie_domain = original_cookie_domain
        app.dependency_overrides.pop(get_async_db, None)


def test_signed_photo_url_rejects_tampered_signature(monkeypatch) -> None:
    app.dependency_overrides[get_async_db] = _override_get_async_db
    original_cookie_domain = main_module.settings.cookie_domain
    main_module.settings.cookie_domain = None
    monkeypatch.setattr(main_module.settings, "google_maps_api_key", "fake-key", raising=False)
    monkeypatch.setattr(
        main_module.settings, "media_proxy_signing_key", "test-signing-key", raising=False
    )
    monkeypatch.setattr(main_module, "get_session_by_token", AsyncMock(return_value=object()))
    monkeypatch.setattr(main_module.httpx, "AsyncClient", _FakePlacesPhotoClient)

    try:
        with TestClient(app) as client:
            signed = client.get("/api/media/google-places-photo-url", params={"name": PHOTO_NAME})
            assert signed.status_code == 200
            signed_url = signed.json()["url"]
            parsed = urlsplit(signed_url)
            query = parse_qs(parsed.query)
            query["sig"] = ["deadbeef"]
            tampered = urlunsplit(
                (
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    urlencode(query, doseq=True),
                    parsed.fragment,
                )
            )

            response = client.get(tampered)
            assert response.status_code == 403
    finally:
        main_module.settings.cookie_domain = original_cookie_domain
        app.dependency_overrides.pop(get_async_db, None)


def test_signed_photo_url_requires_persisted_session(monkeypatch) -> None:
    app.dependency_overrides[get_async_db] = _override_get_async_db
    original_cookie_domain = main_module.settings.cookie_domain
    main_module.settings.cookie_domain = None
    monkeypatch.setattr(main_module.settings, "google_maps_api_key", "fake-key", raising=False)
    monkeypatch.setattr(
        main_module.settings, "media_proxy_signing_key", "test-signing-key", raising=False
    )
    monkeypatch.setattr(main_module, "get_session_by_token", AsyncMock(return_value=None))

    try:
        with TestClient(app) as client:
            response = client.get("/api/media/google-places-photo-url", params={"name": PHOTO_NAME})
            assert response.status_code == 401
    finally:
        main_module.settings.cookie_domain = original_cookie_domain
        app.dependency_overrides.pop(get_async_db, None)
