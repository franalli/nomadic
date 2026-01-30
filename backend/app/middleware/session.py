"""
Session Middleware
==================

Provides secure session management via HttpOnly cookies.

Features:
- Issues opaque session_id cookie on first request
- HttpOnly, Secure, SameSite=None for cross-origin support
- CSRF protection via double-submit cookie pattern
- Session injection into request state for endpoint access

Cookie Configuration:
- session_id: HttpOnly, Secure, SameSite=None, Max-Age=14 days
- csrf: Non-HttpOnly (readable by JS), Secure, SameSite=None

CSRF Protection:
- Double-submit cookie pattern
- Requires X-CSRF-Token header to match csrf cookie on unsafe methods
- Unsafe methods: POST, PUT, PATCH, DELETE
"""

import secrets
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from app.config import generate_session_token, settings

# Cookie configuration
SESSION_COOKIE_NAME = "session_id"
CSRF_COOKIE_NAME = "csrf"
SESSION_MAX_AGE = 14 * 24 * 60 * 60  # 14 days in seconds


def _get_cookie_kwargs() -> dict:
    """Get cookie configuration based on environment."""
    is_production = settings.env not in ("local", "development", "test")

    base_kwargs = {
        "path": "/",
        "max_age": SESSION_MAX_AGE,
        "samesite": "none" if is_production else "lax",
    }

    # Secure is required when SameSite=None
    if is_production:
        base_kwargs["secure"] = True

    # Add domain if configured (for subdomain sharing)
    cookie_domain = getattr(settings, "cookie_domain", None)
    if cookie_domain:
        base_kwargs["domain"] = cookie_domain

    return base_kwargs


def _generate_csrf_token() -> str:
    """Generate a cryptographically secure CSRF token."""
    return secrets.token_urlsafe(32)


class SessionMiddleware(BaseHTTPMiddleware):
    """
    Middleware that manages session cookies.

    On each request:
    1. Reads session_id cookie (or generates new one)
    2. Reads csrf cookie (or generates new one)
    3. Injects session_id into request.state.session_id
    4. Sets cookies on response if newly generated
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        # Read existing cookies
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        csrf_token = request.cookies.get(CSRF_COOKIE_NAME)

        # Generate new values if missing
        new_session = session_id is None
        new_csrf = csrf_token is None

        if new_session:
            session_id = generate_session_token()
        if new_csrf:
            csrf_token = _generate_csrf_token()

        # Inject into request state for endpoint access
        request.state.session_id = session_id
        request.state.csrf_token = csrf_token

        # Process the request
        response = await call_next(request)

        # Set cookies if newly generated
        cookie_kwargs = _get_cookie_kwargs()

        if new_session:
            response.set_cookie(
                key=SESSION_COOKIE_NAME,
                value=session_id,
                httponly=True,
                **cookie_kwargs,
            )

        if new_csrf:
            # CSRF cookie must NOT be HttpOnly so JS can read it
            response.set_cookie(
                key=CSRF_COOKIE_NAME,
                value=csrf_token,
                httponly=False,
                **cookie_kwargs,
            )

        return response


def get_session_from_request(request: Request) -> str:
    """
    Get the session ID from the request state.

    Use this as a FastAPI dependency to access the session in endpoints.

    Example:
        @app.get("/api/document")
        def get_document(session_id: str = Depends(get_session_from_request)):
            ...
    """
    session_id = getattr(request.state, "session_id", None)
    if not session_id:
        raise ValueError("Session middleware not configured or session missing")
    return session_id


# =============================================================================
# CSRF Protection Middleware
# =============================================================================

# HTTP methods that modify state and require CSRF protection
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Paths that are exempt from CSRF protection (e.g., health checks, stateless validation)
CSRF_EXEMPT_PATHS = {
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/validate-trip-input",
    "/api/admin/clear-validation-cache",
    "/api/admin/clear-all-caches",
    "/api/admin/clear-all-checkpoints",
    "/api/admin/fresh-start",
}

# Header name for CSRF token
CSRF_HEADER_NAME = "X-CSRF-Token"


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    CSRF protection using double-submit cookie pattern.

    For unsafe methods (POST, PUT, PATCH, DELETE):
    1. Reads csrf cookie value
    2. Reads X-CSRF-Token header value
    3. Compares them using constant-time comparison
    4. Returns 403 if they don't match

    This works because:
    - The csrf cookie is set by SessionMiddleware (SameSite=None + Secure)
    - An attacker on a different origin cannot read our csrf cookie
    - So they cannot set the correct X-CSRF-Token header
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        # Skip CSRF check for safe methods
        if request.method not in UNSAFE_METHODS:
            return await call_next(request)

        # Skip CSRF check for exempt paths
        if request.url.path in CSRF_EXEMPT_PATHS:
            return await call_next(request)

        # Get CSRF token from cookie
        csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
        if not csrf_cookie:
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF cookie missing"},
            )

        # Get CSRF token from header
        csrf_header = request.headers.get(CSRF_HEADER_NAME)
        if not csrf_header:
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token header missing"},
            )

        # Compare using constant-time comparison to prevent timing attacks
        if not secrets.compare_digest(csrf_cookie, csrf_header):
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token mismatch"},
            )

        # CSRF check passed
        return await call_next(request)


def clear_session_cookies(response: Response) -> Response:
    """
    Clear session and CSRF cookies from a response.

    Use this when resetting/deleting a session to ensure cookies are removed.
    """
    cookie_kwargs = _get_cookie_kwargs()
    # Remove max_age to delete the cookie
    del cookie_kwargs["max_age"]

    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path=cookie_kwargs.get("path", "/"),
        domain=cookie_kwargs.get("domain"),
    )
    response.delete_cookie(
        key=CSRF_COOKIE_NAME,
        path=cookie_kwargs.get("path", "/"),
        domain=cookie_kwargs.get("domain"),
    )

    return response
