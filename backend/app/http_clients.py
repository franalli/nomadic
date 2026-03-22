"""Shared HTTP clients extracted to avoid circular imports (main ↔ lifespan)."""

import asyncio

import httpx

# Shared httpx client for photo proxy (connection pooling across requests)
photo_proxy_client: httpx.AsyncClient | None = None
_photo_proxy_lock = asyncio.Lock()


async def get_photo_proxy_client() -> httpx.AsyncClient:
    global photo_proxy_client
    if photo_proxy_client is not None and not photo_proxy_client.is_closed:
        return photo_proxy_client
    async with _photo_proxy_lock:
        if photo_proxy_client is None or photo_proxy_client.is_closed:
            photo_proxy_client = httpx.AsyncClient(timeout=10.0, follow_redirects=True)
    return photo_proxy_client
