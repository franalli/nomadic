import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # core
    env: str = "dev"

    # backend
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000

    # database
    database_url: str = os.getenv("DATABASE_URL", "")

    # external APIs
    openai_api_key: str | None = None


settings = Settings()
