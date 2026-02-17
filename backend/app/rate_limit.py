# backend/app/rate_limit.py
"""Shared rate limiter instance (slowapi).

Extracted so that both main.py and sub-routers (analytics_routes.py) can
apply @limiter.limit() decorators without circular imports.
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings


def _rate_key(request: Request) -> str:
    """Session cookie -> IP fallback for rate limit keying.

    OPTIONS preflights share a single bucket so CORS preflight requests
    never exhaust a real user's rate limit.
    """
    if request.method == "OPTIONS":
        return "__preflight__"
    return request.cookies.get("session_id") or get_remote_address(request)


limiter = Limiter(key_func=_rate_key, enabled=settings.rate_limit_enabled)
