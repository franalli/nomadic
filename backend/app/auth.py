from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db_models import Session as SessionModel
from app.db_models import SharedTrip, User

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


async def exchange_google_code(code: str, redirect_uri: str) -> dict[str, Any]:
    """Exchange an OAuth code for user profile data."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        token_res = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        token_res.raise_for_status()
        token_payload = token_res.json()
        access_token = token_payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("Google token response missing access token")

        userinfo_res = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        userinfo_res.raise_for_status()
        profile = userinfo_res.json()
        if not isinstance(profile.get("sub"), str) or not isinstance(profile.get("email"), str):
            raise ValueError("Google profile missing required fields")
        return profile


async def get_or_create_user(db: AsyncSession, google_profile: dict[str, Any]) -> User:
    """Find an existing user by google_id or create one."""
    google_id = str(google_profile["sub"])
    result = await db.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()
    now = datetime.now(UTC)

    if user:
        user.last_login_at = now
        user.name = google_profile.get("name") or user.name
        user.avatar_url = google_profile.get("picture") or user.avatar_url
        user.email = str(google_profile.get("email") or user.email)
        await db.flush()
        return user

    user = User(
        google_id=google_id,
        email=str(google_profile["email"]),
        name=google_profile.get("name"),
        avatar_url=google_profile.get("picture"),
        last_login_at=now,
    )
    db.add(user)
    try:
        await db.flush()
        return user
    except IntegrityError:
        # Concurrent first-login race: another request inserted this google_id first.
        await db.rollback()
        result = await db.execute(select(User).where(User.google_id == google_id))
        existing = result.scalar_one_or_none()
        if existing is None:
            raise

        existing.last_login_at = now
        existing.name = google_profile.get("name") or existing.name
        existing.avatar_url = google_profile.get("picture") or existing.avatar_url
        existing.email = str(google_profile.get("email") or existing.email)
        await db.flush()
        return existing


async def link_session_to_user(db: AsyncSession, session: SessionModel, user: User) -> None:
    """Link current session to a user and migrate anonymous shared links."""
    session.user_id = user.id
    await db.execute(
        update(SharedTrip)
        .where(SharedTrip.session_id == session.id)
        .where(SharedTrip.user_id.is_(None))
        .values(user_id=user.id, expires_at=None)
    )
    await db.flush()
