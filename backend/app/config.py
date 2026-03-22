import os
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
# Ensure .env values are loaded once for the entire app (FastAPI, DB, and helpers).
load_dotenv(BACKEND_DIR / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # core — accepts "dev"/"local"/"development" (→ dev) or "prod"/"production" (→ prod)
    env: str = "dev"

    @property
    def is_dev(self) -> bool:
        """True for any development-like ENV value (case-insensitive)."""
        return self.env.lower() in ("dev", "local", "development", "test")

    @property
    def is_prod(self) -> bool:
        """True for any production-like ENV value (case-insensitive)."""
        return self.env.lower() in ("prod", "production")

    # =============================================================================
    # LangGraph Planning Route Configuration
    # =============================================================================
    # Feature flags
    enable_graph_plan_route: bool = True  # Enable /v1/graph_plan route
    # Route configuration
    graph_plan_route_timeout_ms: int = 300000  # Overall route timeout in milliseconds (5 min)

    # Output limits
    assistant_msg_max_len: int = 2000  # Max chars for assistant message
    max_suggested_responses: int = 3  # Max suggested responses

    # =============================================================================
    # Node Model Assignments (env-driven, matches .env)
    # =============================================================================
    # extract_trip_fields tool, router_extraction, specialist feasibility
    router_model: str = "gemini-2.5-flash"
    # local_expert LLM — uses Gemini-safe function calling with a flattened schema
    local_expert_model: str = "gemini-2.5-flash"
    local_expert_use_llm: bool = True  # Set LOCAL_EXPERT_USE_LLM=false to disable LLM (tests/debug)
    # vertical_specialist domain reasoning — KEEP gpt-4o (quality risk on Gemini Flash)
    specialist_model: str = "gpt-4o"
    specialist_fallback_model: str | None = None

    @field_validator("specialist_fallback_model", mode="before")
    @classmethod
    def _empty_fallback_to_none(cls, v: Any) -> Any:
        if isinstance(v, str) and not v.strip():
            return None
        return v

    # constraint_guard place validation
    guard_model: str = "gemini-2.5-flash"
    # synthesizer planning responses
    synthesizer_planning_model: str = "gemini-2.5-flash"
    # Tier 2 activity generation (experience_generator.py)
    experience_model: str = "gemini-2.5-flash"
    # airport code extraction (iata_resolver.py)
    iata_resolver_model: str = "gemini-2.5-flash"

    # Debug flags
    debug_plan_messages: bool = False  # Enable verbose debug logging for planning
    aggressive_cache_clear: bool = False  # Clear ALL caches on Fresh Start (dev mode)
    debug_mode: str = Field(
        default="off", alias="DEBUG"
    )  # DEBUG env var: "off" | "compact" | "full"
    pytest_running: bool = Field(default=False, alias="PYTEST_RUNNING")  # Set by conftest.py
    cost_threshold_warning: float = 0.10  # LLM cost warning threshold (USD)
    cost_threshold_critical: float = 1.00  # LLM cost critical threshold (USD)

    # Infrastructure
    web_concurrency: int = 1

    # backend — 0.0.0.0 required for container environments (Render, Docker)
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    app_name: str = "Nomadic Backend"  # Application name for OpenAPI docs

    # database
    database_url: str = ""

    # LLM provider API keys (consumed by LangChain from env; centralised here for defaults)
    openai_api_key: str = ""
    google_api_key: str = ""

    # external APIs
    unsplash_access_key: str | None = None
    unsplash_request_timeout_seconds: float = 2.5
    unsplash_max_retries: int = 1
    unsplash_prefetch_timeout_seconds: float = 1.5
    unsplash_prefetch_max_retries: int = 0
    unsplash_prefetch_failure_cooldown_seconds: float = 20.0
    unsplash_prefetch_dest_cooldown_seconds: float = 30.0
    unsplash_prefetch_streak_threshold: int = 2

    # GetYourGuide Partner API
    get_your_guide_api_key: str = ""
    get_your_guide_enabled: bool = False
    get_your_guide_cache_ttl_hours: int = 24
    get_your_guide_api_url: str = "https://api.getyourguide.com/1"

    # Viator Affiliate API (Basic Access)
    viator_api_key: str = ""
    viator_enabled: bool = False
    viator_cache_ttl_hours: int = 1
    viator_api_url: str = "https://api.viator.com/partner"

    # Aviasales / Travelpayouts Flights API
    aviasales_api_token: str = ""
    aviasales_marker: str = ""
    aviasales_enabled: bool = False
    aviasales_cache_ttl_hours: int = 1

    # Booking.com hotel deeplink aid parameter (optional, future)
    booking_affiliate_aid: str = ""

    # =============================================================================
    # Cache Configuration
    # =============================================================================
    # L2 TTL overrides (env-driven, tune without deploys)
    # Google Places data changes slowly — 72h avoids redundant API calls
    google_places_cache_ttl_hours: int = 72
    # Deterministic LLM output — same inputs always produce same output
    specialist_cache_ttl_hours: int = 168
    # Nondeterministic LLM — shorter TTL lets model improvements flow through
    experience_cache_ttl_hours: int = 72
    # Google Places enrichment of LLM-generated activities (Tier1/Tier2)
    google_places_enrichment_cache_ttl_hours: int = 720  # 30 days — venue data is stable
    # IATA resolver L2 cache TTL
    iata_cache_ttl_hours: int = 720  # 30 days
    geocode_cache_ttl_hours: int = 24
    # Max activities to enrich per call (caps Google Places API spend)
    google_places_enrichment_cap: int = 3
    # Enrichment concurrency and retry tuning
    google_places_enrichment_max_parallel: int = 4
    google_places_enrichment_retry_attempts: int = 2
    google_places_enrichment_retry_base_ms: int = 250
    # Wipe L2 (PostgreSQL) on session reset — for local dev/testing only
    # Set CLEAR_L2_ON_RESET=true in .env; leave unset in production
    clear_l2_on_session_reset: bool = Field(default=False, validation_alias="CLEAR_L2_ON_RESET")

    # =============================================================================
    # Trip Planning Configuration
    # =============================================================================
    # Budget split controls used across allocator and builder filters
    budget_allocation_flights: float = 0.30
    budget_allocation_hotels: float = 0.40
    budget_allocation_activities: float = 0.30
    tier2_prefetch_wait_budget_ms: int = 350
    tier2_generation_wait_budget_ms: int = 5500

    # =============================================================================
    # Security: Rate Limiting & Admin Access
    # =============================================================================
    rate_limit_enabled: bool = True
    admin_api_key: str = ""
    media_proxy_signing_key: str = ""
    max_sessions_per_ip_hour: int = 10  # Session creation throttle per IP
    spend_guard_enabled: bool = True
    # Hard daily cost caps (USD) for paid external APIs.
    # Code defaults are conservative; .env overrides for dev (3) and prod (3).
    spend_guard_session_daily_cap_usd: float = 1.0
    spend_guard_global_daily_cap_usd: float = 5.0
    # Estimated per-LLM-call token envelope used for pre-call budgeting.
    spend_guard_llm_prompt_tokens_estimate: int = 1200
    spend_guard_llm_completion_tokens_estimate: int = 700
    spend_guard_llm_unknown_model_estimated_call_usd: float = 0.02
    # Google Places Text Search billable-call estimate (USD) — Pro tier Text Search $5/1k + Photo $7/1k blended.
    spend_guard_places_estimated_call_usd: float = 0.007
    # Provider-specific daily cap for Google Places API spend (USD).
    spend_guard_places_daily_cap_usd: float = 2.00

    # Validation prewarm destinations (comma-separated, e.g. "Paris,Tokyo")
    validation_prewarm_destinations: str = ""

    # Validation cache settings
    validation_cache_size: int = 5000  # Increased for progressive learning of unknown places
    validation_cache_ttl: int = 604800  # 7 days - keeps verified places longer
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
    frontend_origin: str = "http://localhost:3000"
    # Cookie domain for subdomain sharing (e.g., ".nomadic.com"), or None for same-origin
    cookie_domain: str | None = None
    # Google OAuth (Phase 2 user accounts)
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""

    # =============================================================================
    # LangSmith Tracing Configuration
    # =============================================================================
    langsmith_api_key: str | None = None
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_project: str = "default"
    langsmith_tracing_enabled: bool = Field(default=False, validation_alias="LANGSMITH_TRACING")
    # Fraction of sessions to trace (0.0 = none, 1.0 = all).
    # Recommended: 1.0 during Gemini migration validation, 0.15 in steady-state prod.
    langsmith_dev_sample_rate: float = 1.0
    langsmith_prod_sample_rate: float = 0.15

    @property
    def langsmith_sample_rate(self) -> float:
        """Return the env-appropriate LangSmith sample rate."""
        return self.langsmith_prod_sample_rate if self.is_prod else self.langsmith_dev_sample_rate

    # =============================================================================
    # Demo curation configuration
    # =============================================================================
    use_demo_curation: bool = False

    # =============================================================================
    # Google Places API Configuration
    # =============================================================================
    google_maps_api_key: str | None = None
    google_maps_api_secret: str | None = None

    # Feature flag: enable Google Places for hotels and activities
    use_google_places_provider: bool = False
    google_places_photos_enabled: bool = True
    google_places_enrichment_enabled: bool = True
    google_places_photo_signed_ttl_max: int = 60 * 60  # 1 hour
    google_places_circuit_breaker_enabled: bool = True
    google_places_circuit_breaker_failure_threshold: int = 2
    google_places_circuit_breaker_open_seconds: int = 30


settings = Settings()


def get_media_signing_secret() -> str:
    """Canonical fallback chain for media proxy URL signing.

    Used by both the signer (google_places_provider) and verifier (main.py)
    to ensure the same secret is resolved in all environments.
    """
    return (
        settings.media_proxy_signing_key
        or settings.admin_api_key
        or settings.google_maps_api_secret
        or settings.google_maps_api_key
        or ""
    ).strip()


# =============================================================================
# Shared Model Pricing Table (per 1M tokens, USD)
# =============================================================================
# Single source of truth consumed by spend_guard.py and debug_utils.py.
MODEL_PRICING_PER_1M: dict[str, dict[str, float]] = {
    "gpt-4o": {"prompt": 2.50, "completion": 10.00},
    "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
    "gemini-2.5-flash": {"prompt": 0.15, "completion": 0.60},
    "gemini-2.5-pro": {"prompt": 1.25, "completion": 5.00},
    "gemini-3-flash-preview": {"prompt": 0.50, "completion": 3.00},
}


# =============================================================================
# LangSmith Environment Setup
# =============================================================================
def configure_langsmith_tracing(
    enabled: bool = True,
    project: str | None = None,
) -> str | None:
    """
    Configure LangSmith tracing environment variables.

    This should be called before any LangGraph operations to enable tracing.
    LangGraph automatically picks up these environment variables.

    Args:
        enabled: Whether to enable tracing
        project: Optional project name override (defaults to settings.langsmith_project)

    Returns:
        The resolved project name (with env suffix), or None if tracing is not configured.
    """
    api_key = settings.langsmith_api_key
    if not api_key:
        return None

    # Fully disable if tracing flag is off OR sample rate is 0
    effective_enabled = (
        enabled and settings.langsmith_tracing_enabled and settings.langsmith_sample_rate > 0
    )

    # Derive project name with env suffix: "nomadic" → "nomadic-dev" / "nomadic-prod"
    base_project = project or settings.langsmith_project
    suffix = "-prod" if settings.is_prod else "-dev"
    if not base_project.endswith(suffix):
        resolved_project = f"{base_project}{suffix}"
    else:
        resolved_project = base_project

    os.environ["LANGCHAIN_API_KEY"] = api_key
    os.environ["LANGCHAIN_ENDPOINT"] = settings.langsmith_endpoint
    os.environ["LANGCHAIN_TRACING_V2"] = "true" if effective_enabled else "false"
    os.environ["LANGSMITH_TRACING"] = "true" if effective_enabled else "false"
    # Set both — newer SDK reads LANGSMITH_PROJECT, older reads LANGCHAIN_PROJECT
    os.environ["LANGCHAIN_PROJECT"] = resolved_project
    os.environ["LANGSMITH_PROJECT"] = resolved_project
    return resolved_project


def generate_session_token() -> str:
    """Generate a new cryptographically secure session token (UUID4)."""
    return str(uuid.uuid4())
