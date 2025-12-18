import os
import uuid
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAI
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

    # =============================================================================
    # LangGraph Planning Route Configuration
    # =============================================================================
    # Feature flags
    enable_graph_plan_route: bool = False  # Enable /v1/graph_plan route

    # Route configuration
    graph_plan_route_timeout_ms: int = 15000  # Overall route timeout in milliseconds

    # Output limits
    assistant_msg_max_len: int = 2000  # Max chars for assistant message
    max_destinations: int = 20  # Max destinations per trip
    max_suggested_responses: int = 3  # Max suggested responses

    # Strategy feature flags (default enabled)
    enable_strategy_boating: bool = True
    enable_strategy_hiking: bool = True
    enable_strategy_diving: bool = True
    enable_strategy_skiing: bool = True
    enable_strategy_cycling: bool = True

    # Response polish node configuration
    enable_response_polish: bool = True  # Enable response polishing for natural tone
    response_polish_timeout_ms: int = 200  # Hard timeout cap for polish node (ms)
    response_polish_warn_threshold_ms: int = 150  # Log warning if polish exceeds this (ms)

    # LLM timeouts (in seconds)
    llm_timeout_extractor: float = 6.0  # Extractor should be fast
    llm_timeout_router: float = 8.0
    llm_timeout_specialist: float = 12.0

    # LLM configuration (parity with plan.py)
    plan_chat_history_limit: int = 20  # Max messages to include in context
    openai_plan_max_tokens: int = 800  # Token limit for LLM response
    openai_plan_temperature: float = 0.5  # Response creativity (lower = more consistent)
    openai_plan_top_p: float = 0.95  # Nucleus sampling threshold
    llm_max_retries: int = 3  # Retry count for API errors
    openai_plan_seed: int | None = None  # Optional seed for reproducibility

    # Debug flags
    debug_plan_messages: bool = False  # Enable verbose debug logging for planning

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

    # =============================================================================
    # LangSmith Tracing Configuration
    # =============================================================================
    langsmith_api_key: str | None = os.getenv("LANGSMITH_API_KEY")
    langsmith_endpoint: str = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    langsmith_project: str = os.getenv("LANGSMITH_PROJECT", "default")
    langsmith_tracing_enabled: bool = os.getenv("LANGSMITH_TRACING", "false").lower() == "true"


settings = Settings()


# =============================================================================
# LangSmith Environment Setup
# =============================================================================
def configure_langsmith_tracing(
    enabled: bool = True,
    project: str | None = None,
) -> None:
    """
    Configure LangSmith tracing environment variables.

    This should be called before any LangGraph operations to enable tracing.
    LangGraph automatically picks up these environment variables.

    Args:
        enabled: Whether to enable tracing
        project: Optional project name override (defaults to settings.langsmith_project)
    """
    api_key = settings.langsmith_api_key
    if not api_key:
        return

    os.environ["LANGCHAIN_API_KEY"] = api_key
    os.environ["LANGCHAIN_ENDPOINT"] = settings.langsmith_endpoint
    os.environ["LANGCHAIN_TRACING_V2"] = "true" if enabled else "false"
    os.environ["LANGCHAIN_PROJECT"] = project or settings.langsmith_project


# =============================================================================
# OpenAI Client Singleton (Sync - for legacy code and migrations)
# =============================================================================

_openai_client: Optional[OpenAI] = None


def get_openai_client() -> Optional[OpenAI]:
    """
    Get or create the singleton OpenAI client instance (synchronous).

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


# =============================================================================
# Async OpenAI Client Singleton
# =============================================================================

_async_openai_client: Optional[AsyncOpenAI] = None


def get_async_openai_client() -> Optional[AsyncOpenAI]:
    """
    Get or create the singleton AsyncOpenAI client instance.

    Uses lazy initialization to avoid creating the client until needed.
    The API key is read from settings or environment variable.

    Returns:
        Optional[AsyncOpenAI]: The async OpenAI client, or None if no API key is configured.
    """
    global _async_openai_client

    api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    if _async_openai_client is None:
        _async_openai_client = AsyncOpenAI(api_key=api_key)

    return _async_openai_client


def generate_session_token() -> str:
    """Generate a new cryptographically secure session token (UUID4)."""
    return str(uuid.uuid4())
