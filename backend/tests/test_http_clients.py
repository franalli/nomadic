"""Tests for app.http_clients — shared HTTP client lifecycle."""

import pytest

from app.http_clients import get_photo_proxy_client


@pytest.mark.asyncio
async def test_get_photo_proxy_client_creates_client() -> None:
    """First call should create a new AsyncClient."""
    import app.http_clients as mod

    # Reset module state
    original = mod.photo_proxy_client
    mod.photo_proxy_client = None
    try:
        client = await get_photo_proxy_client()
        assert client is not None
        assert not client.is_closed
        # Second call should return same instance
        client2 = await get_photo_proxy_client()
        assert client is client2
    finally:
        # Cleanup
        if mod.photo_proxy_client and not mod.photo_proxy_client.is_closed:
            await mod.photo_proxy_client.aclose()
        mod.photo_proxy_client = original


@pytest.mark.asyncio
async def test_get_photo_proxy_client_recreates_if_closed() -> None:
    """If the client is closed, a new one should be created."""
    import app.http_clients as mod

    original = mod.photo_proxy_client
    mod.photo_proxy_client = None
    try:
        client1 = await get_photo_proxy_client()
        await client1.aclose()

        client2 = await get_photo_proxy_client()
        assert client2 is not client1
        assert not client2.is_closed
    finally:
        if mod.photo_proxy_client and not mod.photo_proxy_client.is_closed:
            await mod.photo_proxy_client.aclose()
        mod.photo_proxy_client = original


@pytest.mark.asyncio
async def test_get_photo_proxy_client_has_timeout() -> None:
    """Client should have a timeout configured."""
    import app.http_clients as mod

    original = mod.photo_proxy_client
    mod.photo_proxy_client = None
    try:
        client = await get_photo_proxy_client()
        assert client.timeout.connect is not None or client.timeout.read is not None
    finally:
        if mod.photo_proxy_client and not mod.photo_proxy_client.is_closed:
            await mod.photo_proxy_client.aclose()
        mod.photo_proxy_client = original
