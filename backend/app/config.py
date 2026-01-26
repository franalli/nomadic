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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
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
    enable_graph_plan_route: bool = True  # Enable /v1/graph_plan route

    # Route configuration
    graph_plan_route_timeout_ms: int = 300000  # Overall route timeout in milliseconds (5 min)

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
    enable_response_polish: bool = True  # Enable deterministic response polishing

    # LQA (Last Question Answer) pre-pass configuration
    lqa_max_length: int = 150  # Max input length for LQA pre-pass (chars)

    # Short-circuit configuration
    short_circuit_max_length: int = 200  # Max input length for short-circuit patterns (chars)

    # LLM timeouts (in seconds)
    llm_timeout_extractor: float = 120.0  # No timeout limit
    llm_timeout_router: float = 120.0  # No timeout limit
    llm_timeout_specialist: float = 120.0  # No timeout limit

    # P0: Streaming timeouts (in milliseconds)
    # Strategy responses can be large (~900 tokens), increased from 15s to 30s
    streaming_timeout_strategy_ms: int = 30000  # 30s for strategy responses
    streaming_timeout_default_ms: int = 20000  # 20s for other responses
    streaming_warn_threshold_ms: int = 10000  # Log warning if streaming exceeds 10s

    # Node progress bar estimated durations (in milliseconds)
    # These are used by the frontend to show progress bars during LLM node execution
    node_progress_required_fields_ms: int = 3000  # Understanding trip fields
    node_progress_flights_ms: int = 5000  # Finding flights
    node_progress_hotels_ms: int = 5000  # Searching hotels
    node_progress_transport_ms: int = 4000  # Planning transport
    node_progress_activities_ms: int = 5000  # Discovering activities
    node_progress_general_ms: int = 4000  # Processing general request
    node_progress_correction_ms: int = 3000  # Adjusting plan
    node_progress_response_polish_ms: int = 2000  # Polishing response

    # LLM configuration (parity with plan.py)
    plan_chat_history_limit: int = 20  # Max messages to include in context
    openai_plan_max_tokens: int = 800  # Token limit for LLM response
    openai_plan_temperature: float = 0.5  # Response creativity (lower = more consistent)
    llm_max_retries: int = 3  # Retry count for API errors
    openai_plan_seed: int | None = None  # Optional seed for reproducibility
    openai_plan_model: str = "gpt-4o-mini"  # Model for planning
    openai_small_model: str = "gpt-4o-mini"  # Small model for simple tasks
    openai_medium_model: str = "gpt-4o-mini"  # Medium model for moderate tasks
    llm_specialist_model: str = "gpt-4o-mini"  # Model for strategy specialist calls

    # =============================================================================
    # V2 Model Tiering (for latency optimization)
    # =============================================================================
    router_model: str = os.getenv("ROUTER_MODEL", "gpt-4o-mini")  # Fast intent classification
    extraction_model: str = os.getenv("EXTRACTION_MODEL", "gpt-4o-mini")  # Field extraction
    architect_model: str = os.getenv("ARCHITECT_MODEL", "gpt-4o")  # Planning decisions
    synthesizer_model: str = os.getenv("SYNTHESIZER_MODEL", "gpt-4o")  # Response generation

    # Debug flags
    debug_plan_messages: bool = False  # Enable verbose debug logging for planning
    aggressive_cache_clear: bool = False  # Clear ALL caches on Fresh Start (dev mode)
    precise_token_count: bool = False  # Use tiktoken for precise token counting

    # backend
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    app_name: str = "Nomadic Backend"  # Application name for OpenAPI docs

    # database
    database_url: str = os.getenv("DATABASE_URL", "")

    # external APIs
    openai_api_key: str | None = None
    unsplash_access_key: str | None = os.getenv("UNSPLASH_ACCESS_KEY")

    # =============================================================================
    # Cache Configuration
    # =============================================================================
    response_cache_ttl_seconds: int = 3600  # TTL for cached LLM responses (1 hour)
    response_cache_maxsize: int = 200  # Max entries in response cache
    checkpoint_ttl_hours: int = 24  # Hours before idle checkpoints are purged

    # =============================================================================
    # Strategy Output Limits (PR-C: Strategy Output Size Limits)
    # =============================================================================
    strategy_max_output_chars: int = 4000  # Hard cap on strategy response chars
    strategy_expansion_max_output_chars: int = 8000  # Hard cap on expansion response chars

    # =============================================================================
    # Trip Planning Configuration
    # =============================================================================
    default_trip_currency: str = "USD"  # Default currency for trip budgets
    auto_correct_typo_threshold: int = 100  # Levenshtein distance for typo correction
    confidence_threshold_skip_router: float = 0.92  # Confidence to skip LLM router

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
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
    # Cookie domain for subdomain sharing (e.g., ".nomadic.com"), or None for same-origin
    cookie_domain: str | None = os.getenv("COOKIE_DOMAIN", None)

    # =============================================================================
    # E2E Test Configuration
    # =============================================================================
    e2e_test_model: str = "gpt-4o-mini"  # Model for E2E tests
    router_call_rate_target: float = 0.30  # Target % of turns using LLM router
    template_hit_rate_target: float = 0.85  # Target % of turns hitting templates

    # =============================================================================
    # State Integrity Configuration
    # =============================================================================
    # Enable invariant checking (compute/log state violations)
    state_invariants_enabled: bool = True
    # Restore from snapshot on state regression (false = reconcile prompt only)
    state_snapshot_restore_enabled: bool = True

    # =============================================================================
    # Loop Guard Configuration
    # =============================================================================
    loop_guard_enabled: bool = True  # Enable loop guard mitigation actions
    loop_guard_shadow_mode: bool = False  # Enforce loop prevention
    loop_guard_shadow_audit: bool = False  # Log "would-trigger" events for parameter tuning
    loop_guard_threshold: int = (
        1  # Same field asked N times in window triggers loop (lowered to 1 for faster detection)
    )
    loop_guard_window_turns: int = 3  # Turns to check for repeated questions
    loop_guard_extended_window_turns: int = 6  # Extended window (gated by no-progress)
    loop_guard_no_progress_turns: int = 2  # Turns with no progress before triggering
    loop_guard_forced_route_cooldown_turns: int = 2  # Cooldown between forced routes
    loop_guard_max_triggers_per_convo: int = 3  # Max triggers per conversation
    loop_guard_require_no_progress_for_extended: bool = True  # Require no-progress for window=6

    # =============================================================================
    # Specialist Pre-Core Mode Configuration
    # =============================================================================
    # When enabled, specialist nodes (hotels, flights, activities) can be routed to
    # even before core fields are fully collected, if the user's intent is clear.
    # The specialist will acknowledge intent and ask for minimal missing fields inline.
    specialist_pre_core_enabled: bool = True

    # =============================================================================
    # Specialist Parallelization Configuration (Tier 10.1)
    # =============================================================================
    # When enabled, independent specialist nodes (flights, hotels, transport) can
    # run concurrently for 100-200ms latency reduction. Mutually exclusive specialists
    # (required_fields/correction, strategy/activities) still run sequentially.
    specialist_parallelization_enabled: bool = True

    # When True, use deterministic templates instead of LLM for missing_fields_guard.
    # Saves ~200-250 tokens per guard call with minimal UX impact.
    # Set to False to use LLM for more varied phrasing (original behavior).
    guard_use_templates: bool = True

    # =============================================================================
    # Default Adults Configuration
    # =============================================================================
    # When enabled, after core fields (destination, dates) are collected but adults
    # is still missing, default to adults=1 with metadata marker instead of asking.
    default_adults_enabled: bool = True

    # =============================================================================
    # Turn Journal Configuration
    # =============================================================================
    turn_journal_max_turns: int = 20  # Max turns in ring buffer

    # =============================================================================
    # Extractor Cache Configuration
    # =============================================================================
    extractor_cache_ttl_seconds: int = (
        300  # TTL for extractor cache entries (5 min for multi-turn reuse)
    )
    extractor_cache_maxsize: int = 100  # Max entries in extractor cache

    # =============================================================================
    # Strategy Cache Configuration
    # =============================================================================
    strategy_cache_ttl_seconds: int = 300  # TTL for strategy cache (5 min)
    strategy_cache_maxsize: int = (
        100  # Max entries in strategy cache (increased to reduce evictions)
    )

    # =============================================================================
    # First-Turn Optimization: Strategy Bootstrap Bypass
    # =============================================================================
    # Enable deterministic bypass of extractor for strategy pre-core prompts
    enable_strategy_bootstrap_bypass: bool = True
    # A/B test sample rate (0.0-1.0): fraction of sessions using bypass
    strategy_bootstrap_bypass_sample_rate: float = 1.0
    # Disable automatic cache clearing in production (allow only on deploy/admin)
    disable_autoclear_caches_in_prod: bool = True

    # =============================================================================
    # Telemetry Configuration (PR-T1..T3)
    # =============================================================================
    # Sampling rates for structured trace events
    trace_sample_rate: float = 1.0  # Probability of enabling trace (0.0 to 1.0)
    trace_verbose_sample_rate: float = 0.0  # Probability of verbose trace (0.0 to 1.0)
    # Redaction mode: "hash_only" (default) or "verbose" (logs raw text)
    trace_redaction_mode: str = "hash_only"
    # Console output for trace events (like debug_plan_messages)
    trace_console_output: bool = True

    # =============================================================================
    # LangSmith Tracing Configuration
    # =============================================================================
    langsmith_api_key: str | None = os.getenv("LANGSMITH_API_KEY")
    langsmith_endpoint: str = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    langsmith_project: str = os.getenv("LANGSMITH_PROJECT", "default")
    langsmith_tracing_enabled: bool = os.getenv("LANGSMITH_TRACING", "false").lower() == "true"

    # =============================================================================
    # Amadeus API Configuration
    # =============================================================================
    amadeus_api_key: str | None = os.getenv("AMADEUS_API_KEY")
    amadeus_api_secret: str | None = os.getenv("AMADEUS_API_SECRET")
    amadeus_base_url: str = os.getenv("AMADEUS_BASE_URL", "https://test.api.amadeus.com")

    # Feature flags for Amadeus integration
    use_amadeus_provider: bool = os.getenv("USE_AMADEUS_PROVIDER", "false").lower() == "true"
    use_demo_curation: bool = os.getenv("USE_DEMO_CURATION", "true").lower() == "true"

    # Rate limiting and circuit breaker
    amadeus_requests_per_minute: int = int(os.getenv("AMADEUS_REQUESTS_PER_MINUTE", "30"))
    amadeus_circuit_breaker_threshold: int = int(
        os.getenv("AMADEUS_CIRCUIT_BREAKER_THRESHOLD", "5")
    )
    amadeus_circuit_breaker_timeout: int = int(os.getenv("AMADEUS_CIRCUIT_BREAKER_TIMEOUT", "60"))


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
