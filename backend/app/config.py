import os
import uuid
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
# Ensure .env values are loaded once for the entire app (FastAPI, DB, and helpers).
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env.docker", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.docker"),  # make sure .env and .env.docker match!
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # core
    env: str = os.getenv("ENV", "local")

    # backend
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000

    # database
    database_url: str = os.getenv("DATABASE_URL", "")

    # external APIs
    openai_api_key: str | None = None

    # Validation cache settings
    validation_cache_size: int = 1000
    validation_cache_ttl: int = 86400  # 24 hours
    validation_max_tokens: int = 50  # Enough for JSON response
    validation_negative_cache_enabled: bool = True
    validation_negative_cache_size: int = 500
    validation_negative_cache_ttl: int = 900  # Short TTL for invalid entries
    validation_split_cache_size: int = 500
    validation_prompt_cache_size: int = 500
    validation_fallback_cache_size: int = 500
    validation_rate_limit_enabled: bool = True
    validation_rate_limit_window: int = 300  # seconds
    validation_rate_limit_max_requests: int = 50

    # Cross-origin / Cookie configuration
    # Frontend origin for CORS (e.g., "https://app.nomadic.com")
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
    # Cookie domain for subdomain sharing (e.g., ".nomadic.com"), or None for same-origin
    cookie_domain: str | None = os.getenv("COOKIE_DOMAIN", None)


settings = Settings()


# =============================================================================
# OpenAI Client Singleton
# =============================================================================

_openai_client: Optional[OpenAI] = None


def get_openai_client() -> Optional[OpenAI]:
    """
    Get or create the singleton OpenAI client instance.

    Uses lazy initialization to avoid creating the client until needed.
    The API key is read from settings or environment variable.

    Returns:
        Optional[OpenAI]: The OpenAI client, or None if no API key is configured.
    """
    global _openai_client

    api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    if _openai_client is None:
        _openai_client = OpenAI(api_key=api_key)

    return _openai_client


def generate_session_token() -> str:
    """Generate a new cryptographically secure session token (UUID4)."""
    return str(uuid.uuid4())
