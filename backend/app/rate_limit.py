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

    OPTIONS preflights are exempt via exempt_options_from_rate_limit
    middleware in main.py (sets _rate_limiting_complete before the
    route handler runs).
    """
    return request.cookies.get("session_id") or get_remote_address(request)


limiter = Limiter(key_func=_rate_key, enabled=settings.rate_limit_enabled)
