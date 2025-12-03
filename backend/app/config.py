import os
from pathlib import Path

from dotenv import load_dotenv
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

    # Cross-origin / Cookie configuration
    # Frontend origin for CORS (e.g., "https://app.nomadic.com")
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
    # Cookie domain for subdomain sharing (e.g., ".nomadic.com"), or None for same-origin
    cookie_domain: str | None = os.getenv("COOKIE_DOMAIN", None)


settings = Settings()
