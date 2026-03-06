# backend/app/rate_limit.py
"""Shared rate limiter instance (slowapi).

Extracted so that both main.py and sub-routers (analytics_routes.py) can
apply @limiter.limit() decorators without circular imports.
"""

from threading import RLock

from cachetools import TTLCache
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

_IP_ONLY_RATE_PATHS = {
    "/api/shared/",
    "/api/auth/",
}

# Session tokens previously resolved against the DB are marked trusted for
# limiter keying so raw client-provided cookie values cannot mint new buckets.
_TRUSTED_SESSION_KEYS: TTLCache = TTLCache(maxsize=50_000, ttl=12 * 60 * 60)
_TRUSTED_SESSION_KEYS_LOCK = RLock()


def mark_trusted_session_id(session_id: str | None) -> None:
    if not session_id:
        return
    with _TRUSTED_SESSION_KEYS_LOCK:
        _TRUSTED_SESSION_KEYS[session_id] = True


def forget_trusted_session_id(session_id: str | None) -> None:
    if not session_id:
        return
    with _TRUSTED_SESSION_KEYS_LOCK:
        _TRUSTED_SESSION_KEYS.pop(session_id, None)


def _is_trusted_session_id(session_id: str | None) -> bool:
    if not session_id:
        return False
    with _TRUSTED_SESSION_KEYS_LOCK:
        return bool(_TRUSTED_SESSION_KEYS.get(session_id))


def _clear_trusted_session_ids_for_tests() -> None:
    with _TRUSTED_SESSION_KEYS_LOCK:
        _TRUSTED_SESSION_KEYS.clear()


def _rate_key(request: Request) -> str:
    """Route-aware rate limit keying.

    Public routes are keyed by IP-only to avoid cookie-rotation bypass.
    Other routes are keyed by session only when the cookie token was previously
    validated against the DB; otherwise fall back to IP.
    """
    path = request.url.path
    if any(path.startswith(prefix) for prefix in _IP_ONLY_RATE_PATHS):
        return get_remote_address(request)

    trusted_session_id = request.cookies.get("session_id")
    if _is_trusted_session_id(trusted_session_id):
        return trusted_session_id

    # Allows explicit validated session injection for any non-cookie auth flow.
    validated_session_id = getattr(request.state, "validated_session_id", None)
    if _is_trusted_session_id(validated_session_id):
        return validated_session_id

    return get_remote_address(request)


limiter = Limiter(key_func=_rate_key, enabled=settings.rate_limit_enabled)
