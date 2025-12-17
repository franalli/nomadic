# plan_graph.py — Minimalist LangGraph with strategy modules
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random as _random_module
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from cachetools import TTLCache
from jinja2 import Environment, FileSystemLoader
from jsonschema import Draft7Validator
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app import db_models as models
from app.config import settings
from app.crud_document import (
    apply_planner_update,
    get_document,
    get_document_data,
    get_or_create_document,
)
from app.crud_trip import (
    create_trip_context,
    fetch_chat_history,
    get_latest_trip_context_for_session,
    get_or_create_session,
    record_chat_message,
)
from app.known_places import (
    KNOWN_COUNTRIES,
    normalize_place_synonym,
)
from app.schemas import (
    ActivitySettings,
    BookingTypes,
    BranchTileIds,
    DocumentBranch,
    DocumentTripInputs,
    FlightSettings,
    HotelSettings,
    PlanDocumentData,
    PlanDocumentResponse,
    PlanRequest,
    TilesSearchRequest,
    TransportSettings,
)
from app.schemas import (
    Tile as TileSchema,
)
from app.tile_service import search_tiles

# LangSmith tracing support - optional import
try:
    from langchain_core.tracers import LangChainTracer

    LANGCHAIN_TRACER_AVAILABLE = True
except ImportError:
    LANGCHAIN_TRACER_AVAILABLE = False

# Try to import tiktoken for token counting, fallback to char-based estimation
try:
    import tiktoken

    _TIKTOKEN_AVAILABLE = True
except ImportError:
    tiktoken = None  # type: ignore
    _TIKTOKEN_AVAILABLE = False


def _env_truthy(name: str) -> bool:
    value = os.getenv(name)
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


_KNOWN_COUNTRIES_LOWER = frozenset(c.lower() for c in KNOWN_COUNTRIES)

# =============================================================================
# DEBUG LOGGING
# =============================================================================
_DEBUG_LOG = settings.debug_plan_messages or bool(os.getenv("DEBUG_PLAN_MESSAGES"))

# Retry count for API errors (matching plan.py)
_PLAN_MAX_RETRIES = int(os.getenv("OPENAI_PLAN_MAX_RETRIES", "3"))


def _debug(message: str, **kwargs: Any) -> None:
    """Print debug message if DEBUG_PLAN_MESSAGES is enabled."""
    if _DEBUG_LOG:
        extras = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
        print(f"[PLAN_GRAPH DEBUG] {message} {extras}".strip())


def _debug_error(message: str, **kwargs: Any) -> None:
    """Print ERROR message - always visible and prominent."""
    if _DEBUG_LOG:
        extras = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
        print(f"[PLAN_GRAPH ERROR] ❌ {message} {extras}".strip())


def _debug_suggestions(suggestions: List[str], source: str = "") -> None:
    """Print user prompt suggestions for debug visibility."""
    if _DEBUG_LOG:
        src_tag = f" ({source})" if source else ""
        if suggestions:
            suggestions_str = " | ".join(suggestions)
            print(f"[PLAN_GRAPH DEBUG] 💡 Prompt suggestions{src_tag}: [{suggestions_str}]")
        else:
            print(f"[PLAN_GRAPH DEBUG] 💡 Prompt suggestions{src_tag}: (none)")


# Emoji mapping for each node/specialist for high-visibility debug logging
_NODE_EMOJIS: dict[str, str] = {
    # Core nodes
    "extractor": "🔍",
    "normalize_inputs": "📐",
    "router": "🧭",
    "validate_and_merge": "✅",
    "response_polish": "✨",
    "summarize": "📝",
    "branch_postprocess": "🌿",
    "tile_search": "🗺️",
    "short_circuit_responder": "⚡",
    # Short-circuit detection & fast-path routing
    "short_circuit": "🔌",
    "fast_path": "🏎️",
    # Specialists
    "specialist:required_fields": "📋",
    "specialist:hotels": "🏨",
    "specialist:flights": "✈️",
    "specialist:activities": "🎭",
    "specialist:transport": "🚗",
    "specialist:correction": "🔧",
    # Strategy
    "strategy_node": "🎯",
    "boating": "⛵",
    "hiking": "🥾",
    "skiing": "⛷️",
    "diving": "🤿",
    "cycling": "🚴",
}

# Cache hit emoji for debug logging
_CACHE_EMOJI = "💾"

# Token usage emoji for high-visibility token logging
_TOKEN_EMOJI = "🪙"


def _debug_cache_hit(cache_name: str, key: str = "", value_preview: str = "") -> None:
    """Log cache hit for debugging with optional value preview."""
    if _DEBUG_LOG:
        key_info = f" key={key[:50]}" if key else ""
        # Show first 80 chars of cached value if provided
        val_info = ""
        if value_preview:
            preview = value_preview.replace("\n", " ")[:80]
            val_info = f" => '{preview}...'"
        print(
            f"[PLAN_GRAPH DEBUG] {_CACHE_EMOJI}{_CACHE_EMOJI}{_CACHE_EMOJI} "
            f"CACHE HIT: {cache_name}{key_info}{val_info}"
        )


def _debug_node_entry(node_name: str, state: "GraphState") -> None:
    """Log entry into a graph node."""
    if _DEBUG_LOG:
        ti = state.trip_inputs
        # Get emoji for node, or default rocket
        emoji = _NODE_EMOJIS.get(node_name, "🚀")
        extras = " ".join(
            f"{k}={v}"
            for k, v in {
                "user_text": (
                    state.user_text[:50] + "..." if len(state.user_text) > 50 else state.user_text
                ),
                "destinations": ti.destinations,
                "origin": ti.origin,
                "intent": state.intent,
            }.items()
        )
        print(
            f"[PLAN_GRAPH DEBUG] {emoji}{emoji}{emoji} "
            f"ENTERING {node_name} {emoji}{emoji}{emoji} {extras}"
        )


def _debug_node_exit(node_name: str, state: "GraphState") -> None:
    """Log exit from a graph node."""
    if _DEBUG_LOG:
        _debug(
            f"<<< EXITING {node_name}",
            ready=state.ready_to_generate,
            errors=len(state.errors),
            branches=len(state.branches),
        )


# =============================================================================
# OBSERVABILITY HELPERS
# =============================================================================


def _increment_llm_calls(state: "GraphState") -> None:
    """Increment the LLM call counter in state metadata for observability."""
    meta = state.metadata or {}
    meta["llm_calls_made"] = meta.get("llm_calls_made", 0) + 1
    state.metadata = meta


def _record_llm_time(state: "GraphState", duration_ms: float) -> None:
    """Record LLM call duration in state metadata for observability."""
    meta = state.metadata or {}
    meta["llm_time_ms"] = meta.get("llm_time_ms", 0.0) + duration_ms
    state.metadata = meta


def _increment_cache_hits(state: "GraphState") -> None:
    """Increment the cache hit counter in state metadata for observability."""
    meta = state.metadata or {}
    meta["cache_hits"] = meta.get("cache_hits", 0) + 1
    state.metadata = meta


def _resolve_model_name(model_hint: str) -> str:
    """Resolve model hint (small/medium/large) to actual model name (gpt-4o-mini, etc.)."""
    # Import _MODEL_MAP lazily to avoid circular reference (it's defined later in file)
    model_map = {
        "small": os.getenv("OPENAI_SMALL_MODEL", "gpt-4o-mini"),
        "medium": os.getenv("OPENAI_MEDIUM_MODEL", "gpt-4o-mini"),
        "large": os.getenv("OPENAI_PLAN_MODEL", "gpt-4o"),
    }
    return model_map.get(model_hint, model_hint)


def _record_node_tokens(state: "GraphState", node_name: str, tokens: int, model: str = "") -> None:
    """Record token usage and model for a specific node in state metadata."""
    meta = state.metadata or {}
    node_tokens = meta.get("node_tokens", {})
    node_tokens[node_name] = node_tokens.get(node_name, 0) + tokens
    meta["node_tokens"] = node_tokens
    meta["total_tokens"] = meta.get("total_tokens", 0) + tokens
    # Track which model each node used (resolve hint to actual model name)
    if model:
        node_models = meta.get("node_models", {})
        node_models[node_name] = _resolve_model_name(model)
        meta["node_models"] = node_models
    state.metadata = meta


def _debug_token_summary(state: "GraphState") -> None:
    """Print a summary of token usage across all nodes at the end of the trace."""
    if not _DEBUG_LOG:
        return
    meta = state.metadata or {}
    node_tokens = meta.get("node_tokens", {})
    total_tokens = meta.get("total_tokens", 0)

    if not node_tokens:
        return

    print("\n" + "=" * 70)
    print(f"[PLAN_GRAPH DEBUG] {_TOKEN_EMOJI} TOKEN USAGE SUMMARY {_TOKEN_EMOJI}")
    print("=" * 70)

    # Sort by token count descending
    node_models = meta.get("node_models", {})
    sorted_nodes = sorted(node_tokens.items(), key=lambda x: x[1], reverse=True)
    for node_name, tokens in sorted_nodes:
        emoji = _NODE_EMOJIS.get(node_name, "🚀")
        model = node_models.get(node_name, "")
        bar_len = min(int(tokens / 100), 40)  # Scale bar (100 tokens = 1 char, max 40)
        bar = "█" * bar_len
        model_suffix = f"  ({model})" if model else ""
        # Use fixed-width formatting: tokens right-aligned, "tokens" left-aligned in 8 chars
        print(f"  {emoji} {node_name:<30} {tokens:>8,} {'tokens':<8} {bar}{model_suffix}")

    print("-" * 70)
    print(f"  {_TOKEN_EMOJI} {'TOTAL':<30} {total_tokens:>8,} {'tokens':<8}")
    print("=" * 70 + "\n")


def _set_confidence_routing(state: "GraphState", routing: str) -> None:
    """Set the confidence routing type in state metadata for observability."""
    meta = state.metadata or {}
    meta["confidence_routing"] = routing
    state.metadata = meta


# =============================================================================
# LLM RESPONSE CACHING (TTLCache)
# =============================================================================
# Cache LLM responses for common patterns to reduce API calls and latency.
# Uses in-memory TTLCache - suitable for single-instance deployments.

# Cache configuration via environment variables
_RESPONSE_CACHE_TTL = int(os.getenv("RESPONSE_CACHE_TTL_SECONDS", "3600"))  # 1 hour default
_RESPONSE_CACHE_MAXSIZE = int(os.getenv("RESPONSE_CACHE_MAXSIZE", "200"))

# Response caches by type
_follow_up_cache: TTLCache = TTLCache(maxsize=_RESPONSE_CACHE_MAXSIZE, ttl=_RESPONSE_CACHE_TTL)
_ready_state_cache: TTLCache = TTLCache(maxsize=100, ttl=_RESPONSE_CACHE_TTL)


def _compute_cache_key(
    prompt_name: str,
    core_fields_state: str,
    user_intent: str = "",
    extra: str = "",
) -> str:
    """
    Compute a cache key for LLM response caching.

    Args:
        prompt_name: Name of the prompt being used
        core_fields_state: Serialized state of core trip fields (dest, origin, date)
        user_intent: User intent archetype (quick_booking, detailed_planner, etc.)
        extra: Any additional context to include in key

    Returns:
        MD5 hash string suitable for cache key
    """
    key_parts = f"{prompt_name}|{core_fields_state}|{user_intent}|{extra}"
    return hashlib.md5(key_parts.encode()).hexdigest()


def _get_core_fields_state(trip_inputs: "TripInputs") -> str:
    """Get a serialized representation of core trip fields for cache key."""
    return json.dumps(
        {
            "destinations": sorted(trip_inputs.destinations or []),
            "origin": trip_inputs.origin,
            "start_date": trip_inputs.start_date,
            "has_end_date": trip_inputs.end_date is not None,
        },
        sort_keys=True,
    )


def _get_cached_response(cache: TTLCache, key: str) -> Optional[Dict[str, Any]]:
    """Try to get a cached response."""
    result = cache.get(key)
    if result is not None:
        _debug_cache_hit("response_cache", key[:16])
    return result


def _set_cached_response(cache: TTLCache, key: str, response: Dict[str, Any]) -> None:
    """Cache an LLM response."""
    cache[key] = response


def clear_response_caches() -> int:
    """
    Clear all LLM response caches.

    Returns the number of entries that were cleared.
    """
    count = len(_follow_up_cache) + len(_ready_state_cache)
    _follow_up_cache.clear()
    _ready_state_cache.clear()
    _debug(f"Cleared response caches: {count} entries")
    return count


def clear_all_caches() -> int:
    """
    Clear ALL caches including response caches, validation caches, and checkpointer.

    This function should be called at the start of each test to ensure
    complete isolation between tests. It clears:
    - LLM response caches (_follow_up_cache, _ready_state_cache)
    - Validation caches (place, flight, hotel, activity caches)
    - MemorySaver checkpointer storage
    - LRU caches (fuzzy_match_place, _load_prompt_cached)
    - Date normalizer singleton (reset reference date)
    - Prompt tracking set (_PROMPTS_LOADED)

    Returns the total number of cache entries cleared.
    """
    global _date_normalizer
    total_cleared = 0
    cleared_caches = []  # Track which caches were cleared for debug logging

    # Clear response caches
    response_count = clear_response_caches()
    total_cleared += response_count
    if response_count > 0:
        cleared_caches.append(f"response_caches: {response_count}")

    # Clear validation caches
    try:
        from app.validation import clear_validation_caches

        validation_count = clear_validation_caches()
        total_cleared += validation_count
        if validation_count > 0:
            cleared_caches.append(f"validation_caches: {validation_count}")
    except ImportError:
        pass  # Validation module may not be available

    # Clear checkpointer storage
    try:
        if hasattr(app, "checkpointer") and app.checkpointer is not None:
            checkpointer = app.checkpointer
            if hasattr(checkpointer, "storage"):
                storage = getattr(checkpointer, "storage", None)
                if storage is not None and isinstance(storage, dict):
                    checkpoint_count = len(storage)
                    storage.clear()
                    total_cleared += checkpoint_count
                    if checkpoint_count > 0:
                        cleared_caches.append(f"checkpointer: {checkpoint_count}")
                    _debug(f"Cleared {checkpoint_count} checkpointer entries")
    except Exception as e:
        _debug_error(f"Failed to clear checkpointer: {e}")

    # Clear prompt LRU cache (32 entries max)
    try:
        cache_info = _load_prompt_cached.cache_info()
        if cache_info.currsize > 0:
            cleared_caches.append(f"prompt_cache: {cache_info.currsize}")
            total_cleared += cache_info.currsize
        _load_prompt_cached.cache_clear()
    except AttributeError:
        pass

    # Clear prompt tracking set
    if _PROMPTS_LOADED:
        cleared_caches.append(f"prompts_loaded_set: {len(_PROMPTS_LOADED)}")
        _PROMPTS_LOADED.clear()

    # Reset date normalizer singleton with fresh reference date
    _date_normalizer = DateNormalizer()
    cleared_caches.append("date_normalizer: reset")

    _debug(f"Cleared all caches: {total_cleared} total entries", caches_cleared=cleared_caches)
    return total_cleared


def response_cache_stats() -> dict[str, int]:
    """Return a snapshot of response cache sizes."""
    return {
        "follow_up": len(_follow_up_cache),
        "ready_state": len(_ready_state_cache),
    }


# =============================================================================
# TYPO CORRECTION HELPERS
# =============================================================================


def _apply_typo_corrections(state: "GraphState", corrections: Dict[str, str]) -> None:
    """
    Apply typo corrections to trip_inputs using the _write_trip_inputs helper.

    Args:
        state: Current graph state to modify
        corrections: Dict mapping original text -> corrected text
    """
    updates: Dict[str, Any] = {}

    # Apply to destinations
    ti = state.trip_inputs
    if ti.destinations:
        corrected_dests = [corrections.get(dest, dest) for dest in ti.destinations]
        if corrected_dests != ti.destinations:
            updates["destinations"] = corrected_dests

    # Apply to origin
    if ti.origin and ti.origin in corrections:
        updates["origin"] = corrections[ti.origin]

    if updates:
        _write_trip_inputs(state, "extractor", **updates)
        _debug(
            "Applied typo corrections via _write_trip_inputs",
            corrections=corrections,
            updates=updates,
        )
    else:
        _debug("No typo corrections applied (no matching fields)")


# =============================================================================
# TOKEN ESTIMATION (ported from plan.py)
# =============================================================================

# Precise token counting via tiktoken can be surprisingly expensive in tight loops.
# Default to a cheap char-based estimate unless explicitly enabled.
_PRECISE_TOKEN_COUNT = os.getenv("NOMADIC_PRECISE_TOKEN_COUNT", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# Cached tiktoken encoder singleton for performance
_TIKTOKEN_ENCODER: Optional[Any] = None
_TIKTOKEN_ENCODER_INITIALIZED = False


def _get_tiktoken_encoder() -> Optional[Any]:
    """Get or create the cached tiktoken encoder (singleton pattern)."""
    global _TIKTOKEN_ENCODER, _TIKTOKEN_ENCODER_INITIALIZED
    if not _TIKTOKEN_ENCODER_INITIALIZED:
        _TIKTOKEN_ENCODER_INITIALIZED = True
        if _TIKTOKEN_AVAILABLE:
            try:
                _TIKTOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")  # type: ignore[union-attr]
                _debug("Tiktoken encoder initialized (cl100k_base)")
            except Exception as e:
                _debug_error("Failed to initialize tiktoken encoder", error=str(e))
    return _TIKTOKEN_ENCODER


def _count_tokens(text: str) -> int:
    """Estimate token count for a text block using cached tiktoken encoder."""
    safe_text = text or ""

    # Default: fast estimate (~4 chars/token). Enable precise mode via env var.
    if not _PRECISE_TOKEN_COUNT or not _TIKTOKEN_AVAILABLE:
        return len(safe_text) // 4

    encoder = _get_tiktoken_encoder()
    if encoder is None:
        return len(safe_text) // 4

    try:
        return len(encoder.encode(safe_text))
    except Exception:
        # Fallback to character-based estimation
        return len(safe_text) // 4


def _estimate_prompt_tokens(prompt: str, parsed_inputs: Dict[str, Any]) -> int:
    """Estimate total tokens for a prompt including injected data."""
    token_count = _count_tokens(prompt)
    token_count += _count_tokens(json.dumps(parsed_inputs))
    return token_count


# =============================================================================
# CONSTANTS (ported from plan.py)
# =============================================================================
DEFAULT_CURRENCY = os.getenv("DEFAULT_TRIP_CURRENCY", "USD")
SUPPORTED_CURRENCIES = {"USD", "EUR", "GBP", "CAD", "AUD", "JPY"}
DEFAULT_BOOKING_TYPES = {
    "hotels": False,
    "flights": False,
    "ground_transport": False,
    "activities": False,
}
DEFAULT_FLIGHT_SETTINGS = {"round_trip": True, "cabin_class": "economy", "direct_only": False}
DEFAULT_HOTEL_SETTINGS = {"min_stars": 0, "amenities": []}
DEFAULT_ACTIVITY_SETTINGS = {"categories": []}
DEFAULT_TRANSPORT_SETTINGS = {"car": False, "train": False, "bus": False}

# =============================================================================
# DESTINATION EXCLUDE WORDS
# =============================================================================
# Words that indicate a phrase-like destination that should be filtered out.
# These are intent/action words, not actual places.
_DEST_EXCLUDE_WORDS = frozenset(
    {
        "trip",
        "vacation",
        "holiday",
        "getaway",
        "tour",
        "recommend",
        "suggest",
        "help",
        "planning",
        "visit",
        "travel",
        "go to",
        "book",
        "find",
    }
)

# =============================================================================
# ACTIVITY EMOJI MAPPING
# =============================================================================
# Maps activity keywords (lowercase) to their emoji prefixes.
# Used to normalize activities so they all have consistent emoji prefixes.
# The mapping includes synonyms that resolve to canonical activities.
# Based on the emoji mapping in prompts/activities.txt

_ACTIVITY_EMOJI_MAP: Dict[str, str] = {
    # Beach/coastal
    "beach": "🏖️",
    "coastal": "🏖️",
    "seaside": "🏖️",
    # Romantic
    "romantic": "💕",
    "couples": "💕",
    "honeymoon": "💕",
    # Adventure/extreme
    "adventure": "🧗",
    "extreme": "🧗",
    "adrenaline": "🧗",
    "climbing": "🧗",
    "rock climbing": "🧗",
    "bungee": "🧗",
    "skydiving": "🧗",
    "paragliding": "🧗",
    "zip-line": "🧗",
    "zipline": "🧗",
    # Family
    "family": "👨‍👩‍👧",
    "kids": "👨‍👩‍👧",
    "children": "👨‍👩‍👧",
    # Food/culinary
    "food": "🍝",
    "culinary": "🍝",
    "gastronomy": "🍝",
    "food tour": "🍝",
    "cooking class": "🍝",
    "street food": "🍝",
    # Wine/tasting
    "wine": "🍷",
    "vineyard": "🍷",
    "tasting": "🍷",
    "wine tasting": "🍷",
    "brewery": "🍷",
    "distillery": "🍷",
    # Culture/museums
    "culture": "🏛️",
    "museums": "🏛️",
    "galleries": "🏛️",
    "art": "🏛️",
    "exhibitions": "🏛️",
    "sightseeing": "🏛️",
    # History
    "history": "📜",
    "heritage": "📜",
    "ancient": "📜",
    "archaeology": "📜",
    # Theater/shows
    "theater": "🎭",
    "theatre": "🎭",
    "shows": "🎭",
    "opera": "🎭",
    "ballet": "🎭",
    "broadway": "🎭",
    "cabaret": "🎭",
    "comedy": "🎭",
    # Spa/wellness
    "spa": "💆",
    "wellness": "💆",
    "yoga": "💆",
    "meditation": "💆",
    "retreat": "💆",
    "spa day": "💆",
    "massage": "💆",
    # Relaxation
    "relaxation": "😌",
    "chill": "😌",
    "unwind": "😌",
    # Hiking/trekking
    "hiking": "🥾",
    "trekking": "🥾",
    "trails": "🥾",
    "hike": "🥾",
    "trek": "🥾",
    # Dirt riding/motorbike
    "dirt riding": "🏍️",
    "motorbike": "🏍️",
    "atv": "🏍️",
    "quad": "🏍️",
    "off-road": "🏍️",
    "motocross": "🏍️",
    "motogp": "🏍️",
    # Racing/F1
    "f1": "🏎️",
    "racing": "🏎️",
    "motorsport": "🏎️",
    "go-kart": "🏎️",
    "formula 1": "🏎️",
    "grand prix": "🏎️",
    "nascar": "🏎️",
    # Diving/snorkeling
    "diving": "🤿",
    "snorkeling": "🤿",
    "scuba": "🤿",
    # Skiing/winter
    "skiing": "⛷️",
    "snowboarding": "⛷️",
    "winter sports": "⛷️",
    "snow activities": "🎿",
    # Nightlife
    "nightlife": "🎉",
    "clubs": "🎉",
    "bars": "🎉",
    "entertainment": "🎉",
    "party": "🎉",
    "clubbing": "🎉",
    "night out": "🎉",
    # Running
    "running": "🏃",
    "jogging": "🏃",
    "marathon": "🏃",
    "triathlon": "🏃",
    "trail running": "🏃",
    # Backpacking
    "backpacking": "🎒",
    "budget travel": "🎒",
    # Music
    "music": "🎵",
    "concerts": "🎵",
    "festivals": "🎵",
    "live music": "🎵",
    "dj": "🎵",
    "rave": "🎵",
    # Movies/film
    "movies": "🎬",
    "film festival": "🎬",
    "premiere": "🎬",
    "cinema": "🎬",
    "celebrity events": "🎬",
    # Circus/carnival
    "circus": "🎪",
    "carnival": "🎪",
    "parade": "🎪",
    "celebration": "🎪",
    "fair": "🎪",
    # Shopping
    "shopping": "🛍️",
    "markets": "🛍️",
    "boutiques": "🛍️",
    # Cycling
    "cycling": "🚴",
    "biking": "🚴",
    "mountain biking": "🚴",
    "bmx": "🚴",
    # Surfing/water sports
    "surfing": "🏄",
    "water sports": "🏄",
    "jet ski": "🏄",
    "wakeboard": "🏄",
    # Kayaking/paddling
    "kayaking": "🛶",
    "canoeing": "🛶",
    "paddleboarding": "🛶",
    "rafting": "🛶",
    # Sailing/boating
    "sailing": "⛵",
    "boating": "⛵",
    "yacht": "⛵",
    "cruise": "⛵",
    # Fishing
    "fishing": "🎣",
    "deep sea fishing": "🎣",
    # Safari/wildlife
    "safari": "🦁",
    "wildlife": "🦁",
    "animal watching": "🦁",
    "zoo": "🦁",
    "whale watching": "🦁",
    "wildlife tours": "🦁",
    # Nature
    "nature": "🌲",
    "national parks": "🌲",
    "aurora": "🌲",
    "northern lights": "🌲",
    "outdoor": "🌲",
    "outdoor activities": "🌲",
    # Golf
    "golf": "⛳",
    # Tennis
    "tennis": "🎾",
    # Sports events
    "basketball": "🏀",
    "football": "🏀",
    "soccer": "🏀",
    "sports events": "🏀",
    # Academic
    "academic": "🎓",
    "conference": "🎓",
    "seminar": "🎓",
    "workshop": "🎓",
    "lecture": "🎓",
    "university": "🎓",
    "research": "🎓",
    "study abroad": "🎓",
    # Competition
    "competition": "🏆",
    "hackathon": "🏆",
    "tournament": "🏆",
    "championship": "🏆",
    "esports": "🏆",
    "olympics": "🏆",
    "world cup": "🏆",
    # Tours (generic)
    "tours": "🎫",
    "guided tours": "🎫",
    "excursions": "🎫",
    "day trips": "🎫",
    # Experiences
    "experiences": "🌟",
    "local experiences": "🌟",
}

# Default emoji for activities that don't match any known category
_DEFAULT_ACTIVITY_EMOJI = "✨"


def _normalize_activity_with_emoji(activity: str) -> str:
    """
    Normalize an activity string to ensure it has the correct emoji prefix.

    - If the activity already starts with an emoji, validate it's correct for the activity type
    - If the emoji is wrong, strip it and apply the correct one
    - Otherwise, look up the activity in the emoji map and add the appropriate emoji
    - If no match found, use the sparkle emoji as default

    Args:
        activity: The activity string (may or may not have emoji prefix)

    Returns:
        The activity string with correct emoji prefix
    """
    import re

    activity = activity.strip()
    if not activity:
        return activity

    # Check if the activity already starts with an emoji
    # Emojis are typically in certain Unicode ranges
    first_char = activity[0]
    # Check if first character is in emoji ranges (simplified check)
    if ord(first_char) > 0x1F00:
        # Has emoji prefix - extract the text part to validate
        # Find where the emoji ends (usually followed by space or the text)
        text_part = activity[1:].lstrip()
        if not text_part:
            return activity

        # Look up what the correct emoji should be for this activity
        text_lower = text_part.lower()
        correct_emoji = None

        # Direct match in emoji map
        if text_lower in _ACTIVITY_EMOJI_MAP:
            correct_emoji = _ACTIVITY_EMOJI_MAP[text_lower]
        else:
            # Try partial matching - check if any keyword is contained in the activity
            for keyword, emoji in _ACTIVITY_EMOJI_MAP.items():
                if re.search(rf"\b{re.escape(keyword)}\b", text_lower):
                    correct_emoji = emoji
                    break

        # If we found a correct emoji and it differs from current, fix it
        if correct_emoji and first_char != correct_emoji:
            return f"{correct_emoji} {text_part}"

        # Emoji is correct or no match found, return as-is
        return activity

    # No emoji prefix - add appropriate one
    activity_lower = activity.lower()

    # Direct match in emoji map
    if activity_lower in _ACTIVITY_EMOJI_MAP:
        emoji = _ACTIVITY_EMOJI_MAP[activity_lower]
        return f"{emoji} {activity}"

    # Try matching with common suffixes removed
    for suffix in [" activities", " tours", " experiences"]:
        if activity_lower.endswith(suffix):
            base = activity_lower[: -len(suffix)]
            if base in _ACTIVITY_EMOJI_MAP:
                emoji = _ACTIVITY_EMOJI_MAP[base]
                return f"{emoji} {activity}"

    # Try partial matching - check if any keyword is contained in the activity
    for keyword, emoji in _ACTIVITY_EMOJI_MAP.items():
        # Only match if keyword is a complete word in the activity
        if keyword in activity_lower:
            # Check word boundaries
            import re

            if re.search(rf"\b{re.escape(keyword)}\b", activity_lower):
                return f"{emoji} {activity}"

    # No match found, use default sparkle emoji
    return f"{_DEFAULT_ACTIVITY_EMOJI} {activity}"


def _deduplicate_activities_case_insensitive(categories: List[str]) -> List[str]:
    """
    Deduplicate activity categories case-insensitively.

    When comparing, strips the emoji prefix to compare only the activity text.
    Keeps the first occurrence of each unique activity.

    Args:
        categories: List of activity strings (with emoji prefixes)

    Returns:
        Deduplicated list preserving order and first occurrences
    """
    seen_lower: set = set()
    deduped: List[str] = []

    for cat in categories:
        # Extract the text part after emoji for comparison
        # Emojis are typically followed by a space
        text = cat.strip()
        # Find where the actual text starts (after emoji and space)
        text_start = 0
        for i, char in enumerate(text):
            if ord(char) < 0x1F00 and char != " ":
                text_start = i
                break
            elif char == " " and i > 0:
                text_start = i + 1
                break

        # Get the text portion for comparison
        text_portion = text[text_start:].strip().lower()

        if text_portion and text_portion not in seen_lower:
            seen_lower.add(text_portion)
            deduped.append(cat)

    return deduped


# Required fields for ready_to_generate (only core 3 - matches plan.py)
_REQUIRED_TRIP_INPUT_FIELDS = (
    "destinations",
    "origin",
    "start_date",
)

# Auto-correct typo threshold: fuzzy match score at or above which typos are
# auto-corrected without LLM confirmation. Default 100 means disabled (always confirm).
# Set to 98 to auto-correct very obvious typos like "Londen" -> "London".
AUTO_CORRECT_TYPO_THRESHOLD = int(os.getenv("AUTO_CORRECT_TYPO_THRESHOLD", "100"))

# Confidence threshold for skipping router entirely (high-confidence extraction)
# When confidence >= this AND all core fields present AND no typos -> skip to validate_and_merge
CONFIDENCE_THRESHOLD_SKIP_ROUTER = float(os.getenv("CONFIDENCE_THRESHOLD_SKIP_ROUTER", "0.92"))

# =============================================================================
# STATE OWNERSHIP MAPPING
# =============================================================================
# Defines which node is the "owner" of each state field. Only the owner should
# write to that field; other nodes should read only. Violations are logged as
# warnings in development.
#
# Fields with "specialists" owner can be written by whichever specialist node runs.
# Fields with "any" owner have shared write access (e.g., metadata for observability).
STATE_OWNERSHIP: Dict[str, str] = {
    # Core extraction - written by extractor, consumed by all
    "parsed_inputs": "extractor",
    # Trip inputs - normalize_inputs seeds values from regex extraction;
    # specialists refine them via _apply_llm_delta. Both can write.
    # Users can update ANY trip input at ANY point in the conversation
    # (e.g., "actually flying from Paris", "change to 3 adults").
    "trip_inputs.destinations": "normalize_inputs|specialists",
    "trip_inputs.origin": "normalize_inputs|specialists",
    "trip_inputs.start_date": "normalize_inputs|specialists",
    "trip_inputs.end_date": "normalize_inputs|specialists",
    "trip_inputs.adults": "normalize_inputs|specialists",
    "trip_inputs.children": "normalize_inputs|specialists",
    "trip_inputs.budget": "normalize_inputs|specialists",
    "trip_inputs.currency": "normalize_inputs|specialists",
    "trip_inputs.requires_assistance": "normalize_inputs|specialists",
    "trip_inputs.duration_days": "normalize_inputs|specialists",
    "trip_inputs.multi_city_intent": "normalize_inputs|specialists",
    # Settings fields - normalize_inputs seeds from regex, specialists refine.
    # Users often mention preferences early (e.g., "hiking trip" before activities_node runs).
    "trip_inputs.booking_types": "normalize_inputs|specialists",
    "trip_inputs.flight_settings": "normalize_inputs|specialists",
    "trip_inputs.hotel_settings": "normalize_inputs|specialists",
    "trip_inputs.transport_settings": "normalize_inputs|specialists",
    "trip_inputs.activity_settings": "normalize_inputs|specialists",
    # Control flow
    "ready_to_generate": "validate_and_merge",
    "intent": "router",
    "strategy_topic": "router",
    "active_category": "router",
    # Output fields
    "branches": "branch_postprocess",
    "suggested_responses": "specialists",  # Whichever specialist runs
    "last_summary": "summarize",
    "question_target": "specialists",
    # Shared/observability (any node can write)
    "errors": "any",
    "metadata": "any",
    "flags": "any",
    "chat_history": "any",
}


def _check_state_ownership(node_name: str, field_path: str) -> bool:
    """
    Check if a node is allowed to write to a field based on STATE_OWNERSHIP.

    Returns True if allowed, False if violation (logs a visible warning).
    Writes are still applied even on violation (warn-only mode).

    Supports pipe-separated owners (e.g., "normalize_inputs|specialists") where
    any listed owner is allowed to write.
    """
    owner = STATE_OWNERSHIP.get(field_path)

    if owner is None:
        # Field not in ownership map - allow by default
        return True

    if owner == "any":
        # Shared fields - any node can write
        return True

    # Handle pipe-separated owners (e.g., "normalize_inputs|specialists")
    owners = owner.split("|")

    for o in owners:
        if o == "specialists" and (
            node_name.endswith("_node")
            or node_name.startswith("specialist:")
            or node_name.startswith("strategy:")
        ):
            # Specialist and strategy nodes can write to specialist-owned fields
            return True

        if o == node_name:
            # Exact match - allowed
            return True

    # Violation - log highly visible warning
    _debug(
        "⚠️⚠️⚠️ STATE OWNERSHIP VIOLATION ⚠️⚠️⚠️",
        node=node_name,
        field=field_path,
        expected_owner=owner,
        action="write allowed (warn-only mode)",
    )
    if _DEBUG_LOG:
        print(f"\n{'='*60}")
        print("⚠️ STATE OWNERSHIP VIOLATION")
        print(f"  Node: {node_name}")
        print(f"  Field: {field_path}")
        print(f"  Expected owner: {owner}")
        print("  Action: write allowed (warn-only mode)")
        print(f"{'='*60}\n")
    return False


def _write_trip_inputs(
    state: "GraphState",
    node_name: str,
    **updates: Any,
) -> "GraphState":
    """
    Safely update trip_inputs with ownership checking.

    Uses model_copy(deep=True) to ensure immutability.
    Logs warnings for ownership violations but does not block writes.

    Args:
        state: Current graph state
        node_name: Name of the calling node (for ownership checking)
        **updates: Field updates to apply to trip_inputs

    Returns:
        Updated state (for chaining)

    Example:
        state = _write_trip_inputs(state, "normalize_inputs", destinations=["Paris"])
    """
    ti = state.trip_inputs.model_copy(deep=True)

    for field, value in updates.items():
        field_path = f"trip_inputs.{field}"
        _check_state_ownership(node_name, field_path)

        # Handle nested dict updates (e.g., booking_types, flight_settings)
        if hasattr(ti, field):
            current = getattr(ti, field)
            if isinstance(current, dict) and isinstance(value, dict):
                # Merge dict updates
                merged = {**current, **value}
                setattr(ti, field, merged)
            else:
                setattr(ti, field, value)

    state.trip_inputs = ti
    return state


def _apply_llm_delta(
    state: "GraphState",
    node_name: str,
    delta: Dict[str, Any],
    skip_fields: Optional[set] = None,
) -> None:
    """
    Apply an LLM-generated trip_inputs delta with RAW merge only.

    This function does MINIMAL processing - just merges values without normalization.
    All normalization happens in normalize_inputs via TripInputNormalizer.

    NOTE: Specialists do NOT re-extract basic trip fields.
    See prompts/_scope_specialist.txt for prompt-level enforcement.
    All normalization happens in normalize_inputs via TripInputNormalizer.

    Args:
        state: Current graph state
        node_name: Name of the calling node (for ownership checking and logging)
        delta: Dict of field updates from LLM response
        skip_fields: Optional set of field names to skip (e.g., {"strategy_settings"})
    """
    if not delta:
        return

    skip_fields = skip_fields or set()
    ti = state.trip_inputs  # Read-only for getting current values
    updates: Dict[str, Any] = {}

    # Get valid field names from TripInputs model
    valid_fields = set(type(ti).model_fields.keys())

    for k, v in delta.items():
        # Map 'travelers' to 'adults' (LLM sometimes uses wrong field name)
        if k == "travelers" and isinstance(v, (int, str)):
            if "children" in delta or "adults" in delta:
                k = "adults"
                _debug(f"Mapped LLM 'travelers' to 'adults': {v}", node=node_name)
            else:
                _debug(
                    f"Skipping ambiguous 'travelers' field: {v} (no adults/children breakdown)",
                    node=node_name,
                )
                continue

        # Skip unknown fields to avoid crashes
        if k not in valid_fields:
            _debug(f"Skipping unknown field from LLM: {k}", node=node_name)
            continue

        # Skip explicitly excluded fields (with warning for observability)
        if k in skip_fields:
            _debug(
                f"⚠️ BLOCKED: field '{k}' from {node_name} (value: {repr(v)[:50]})",
                node=node_name,
                blocked_field=k,
            )
            continue

        # =====================================================================
        # RAW MERGE ONLY - No normalization here!
        # Normalization happens in normalize_inputs via TripInputNormalizer
        # =====================================================================

        if k == "destinations":
            # Coerce string to list (LLM sometimes returns single destination as string)
            if isinstance(v, str):
                v = [v]
                _debug(f"Coerced string destination to list: {v}", node=node_name)
            if not isinstance(v, list):
                _debug(f"Skipping invalid destinations type: {type(v).__name__}", node=node_name)
                continue
            # Simple merge - just add new destinations, skip exact duplicates
            existing_lower = {d.lower() for d in ti.destinations}
            new_destinations = list(ti.destinations)
            for d in v:
                if isinstance(d, str) and d.strip():
                    d_lower = d.strip().lower()
                    if d_lower not in existing_lower:
                        new_destinations.append(d.strip())
                        existing_lower.add(d_lower)
            if new_destinations != ti.destinations:
                updates["destinations"] = new_destinations

        elif k in (
            "flight_settings",
            "hotel_settings",
            "activity_settings",
            "transport_settings",
            "booking_types",
        ):
            # Simple dict merge
            if isinstance(v, dict):
                existing = dict(getattr(ti, k, {}) or {})
                existing.update(v)
                updates[k] = existing

        elif k in ("start_date", "end_date", "origin", "currency", "multi_city_intent"):
            # Pass through string fields as-is
            if v is not None:
                updates[k] = v

        elif k in ("adults", "children"):
            # Basic int coercion only
            if isinstance(v, int):
                updates[k] = v
            elif isinstance(v, str):
                try:
                    updates[k] = int(v)
                except ValueError:
                    pass

        elif k == "budget":
            # Accept int/float directly, try to parse strings
            if isinstance(v, (int, float)):
                updates[k] = float(v)
            elif isinstance(v, str):
                # Detect template literal bugs
                if v.startswith("{") and v.endswith("}"):
                    _debug(
                        f"Dropping template literal budget: {v} (system bug)",
                        node=node_name,
                        level="warn",
                    )
                    continue
                # Try simple numeric extraction
                cleaned = re.sub(r"[^\d.]", "", v)
                if cleaned:
                    try:
                        updates[k] = float(cleaned)
                    except ValueError:
                        pass

        elif k == "requires_assistance":
            if isinstance(v, bool):
                updates[k] = v

        elif _should_skip_field_update(k, v, getattr(ti, k, None)):
            continue

        else:
            updates[k] = v

    # Apply all updates via the helper
    if updates:
        _write_trip_inputs(state, node_name, **updates)
        _debug("Applied LLM delta (raw merge)", node=node_name, fields=list(updates.keys()))

    # NOTE: _auto_enable_booking_types is now called ONLY in validate_and_merge
    # to avoid duplicate calls across the graph


# =============================================================================
# USER INTENT ARCHETYPES (for conversational style adaptation)
# =============================================================================
# Priority order: lower number = higher priority (speed preferences win)
# Patterns are pre-compiled for efficiency
USER_INTENT_ARCHETYPES = {
    "quick_booking": {
        "priority": 1,
        "patterns": [
            re.compile(
                r"\b(just\s+flights?|book\s+now|asap|fastest|quick\s+book|just\s+need)\b", re.I
            ),
            re.compile(r"\b(hurry|urgent|immediately|right\s+away)\b", re.I),
        ],
        "description": "Streamlined, minimal questions, skip optional fields",
    },
    "short_trip": {
        "priority": 2,
        "patterns": [
            re.compile(
                r"\b(weekend|quick\s+trip|2-3\s+days|getaway|short\s+trip|day\s+trip)\b", re.I
            ),
            re.compile(r"\b(mini\s+vacation|long\s+weekend|brief\s+visit)\b", re.I),
        ],
        "description": "Focus on essentials, suggest compact itineraries",
    },
    "adventurous": {
        "priority": 3,
        "patterns": [
            re.compile(
                r"\b(explore|off\s+the?\s+beaten\s+path|unique|adventure|hidden\s+gems?)\b", re.I
            ),
            re.compile(r"\b(authentic|local\s+experience|undiscovered|unusual)\b", re.I),
        ],
        "description": "Proactive tips, suggest hidden gems, enthusiastic tone",
    },
    "undecided": {
        "priority": 4,
        "patterns": [
            re.compile(
                r"\b(not\s+sure|help\s+me|suggestions?|ideas?|recommend|where\s+should)\b", re.I
            ),
            re.compile(r"\b(can\'t\s+decide|options?|what\s+do\s+you\s+think)\b", re.I),
        ],
        "description": "Curated options, gentle guidance, offer comparisons",
    },
    "detailed_planner": {
        "priority": 5,
        "patterns": [],  # Default fallback - no specific patterns
        "description": "Thorough questions, structured approach, all categories",
    },
}

# User tone detection patterns (for response adaptation)
# Patterns are pre-compiled for efficiency
USER_TONE_PATTERNS = {
    "enthusiastic": {
        "patterns": [
            re.compile(r"!{2,}", re.I),  # Multiple exclamation marks
            re.compile(r"\b(can\'t\s+wait|so\s+excited|amazing|awesome|love\s+it|perfect)\b", re.I),
            re.compile(r"\b(yay|woohoo|fantastic|incredible|thrilled)\b", re.I),
        ],
    },
    "frustrated": {
        "patterns": [
            re.compile(r"\b(ugh|again\??|still|already\s+told|not\s+working)\b", re.I),
            re.compile(r"\b(confused|frustrat|annoying|wrong|doesn\'t\s+work)\b", re.I),
        ],
        # Also detect very short replies as potential frustration
        "max_length": 15,  # Very short replies may indicate frustration
    },
    "neutral": {
        "patterns": [],  # Default
    },
}

# Intent persistence decay schedule (confidence by turn count)
INTENT_DECAY_SCHEDULE = {
    1: 1.0,  # Turn 1-2: 100% confidence
    2: 1.0,
    3: 0.75,  # Turn 3: 75% confidence
    4: 0.50,  # Turn 4: 50% confidence
    # Turn 5+: 0% - re-detect from scratch
}


def _detect_user_intent_hint(text: str) -> Optional[str]:
    """
    Detect user intent archetype from text using pre-compiled regex patterns.
    Returns the highest-priority matching intent, or None if no match.
    """
    text_lower = text.lower()
    matches = []

    for intent_name, config in USER_INTENT_ARCHETYPES.items():
        if not config["patterns"]:  # Skip default (detailed_planner)
            continue
        for pattern in config["patterns"]:
            if pattern.search(text_lower):
                matches.append((config["priority"], intent_name))
                break  # One match per intent is enough

    if not matches:
        return None

    # Return highest priority (lowest number)
    matches.sort(key=lambda x: x[0])
    return matches[0][1]


def _detect_user_tone(text: str) -> str:
    """
    Detect user tone from text using pre-compiled regex patterns.
    Returns: 'enthusiastic', 'frustrated', or 'neutral'.
    """
    text_lower = text.lower()

    # Check enthusiastic patterns
    for pattern in USER_TONE_PATTERNS["enthusiastic"]["patterns"]:
        if pattern.search(text_lower):
            return "enthusiastic"

    # Check frustrated patterns
    for pattern in USER_TONE_PATTERNS["frustrated"]["patterns"]:
        if pattern.search(text_lower):
            return "frustrated"

    # Check for very short replies (potential frustration)
    max_len = USER_TONE_PATTERNS["frustrated"].get("max_length", 15)
    if len(text.strip()) <= max_len and len(text.split()) <= 3:
        # Short reply - could be frustration, but mark as neutral unless other signals
        pass

    return "neutral"


def _compute_intent_confidence(turn_count: int) -> float:
    """Compute intent confidence based on turn count since detection."""
    if turn_count >= 5:
        return 0.0
    return INTENT_DECAY_SCHEDULE.get(turn_count, 0.0)


def _should_override_persisted_intent(
    new_hint: Optional[str],
    persisted_intent: Optional[str],
    confidence: float,
) -> bool:
    """
    Determine if new intent hint should override persisted intent.
    Strong new signals override regardless of confidence.
    """
    if not new_hint:
        return False
    if not persisted_intent:
        return True
    if confidence <= 0.5:
        return True  # Low confidence - accept new signal
    # High priority intent overrides lower priority
    new_priority = USER_INTENT_ARCHETYPES.get(new_hint, {}).get("priority", 99)
    old_priority = USER_INTENT_ARCHETYPES.get(persisted_intent, {}).get("priority", 99)
    return new_priority < old_priority


# =============================================================================
# PER-NODE LLM CONFIGURATION
# =============================================================================
# Each node can have its own LLM parameters optimized for its task.
# - Router: Fast, deterministic classification → low temp, small output
# - Specialists: Focused extraction → low temp, moderate output
# - Strategy: Deeper topic analysis → slightly higher temp
_NODE_LLM_CONFIG: Dict[str, Dict[str, Any]] = {
    "extractor": {
        "model_hint": "small",
        "temperature": 0.1,  # Very deterministic for extraction
        "max_tokens": 512,  # Structured JSON output
        "top_p": None,
    },
    "router": {
        "model_hint": "small",
        "temperature": 0.1,  # Very deterministic for classification
        "max_tokens": 256,  # Only needs short JSON response
        "top_p": None,
    },
    "required_fields": {
        "model_hint": "small",
        "temperature": 0.2,  # Deterministic extraction
        "max_tokens": 512,  # Reduced from 1024 - typical output ~200-400 tokens
        "top_p": None,
    },
    "flights": {
        "model_hint": "small",
        "temperature": 0.2,
        "max_tokens": 512,  # Reduced from 1024 - typical output ~150-300 tokens
        "top_p": None,
    },
    "hotels": {
        "model_hint": "small",
        "temperature": 0.2,
        "max_tokens": 512,  # Reduced from 1024 - typical output ~150-300 tokens
        "top_p": None,
    },
    "transport": {
        "model_hint": "small",
        "temperature": 0.2,
        "max_tokens": 512,  # Reduced from 1024 - typical output ~150-300 tokens
        "top_p": None,
    },
    "activities": {
        "model_hint": "small",
        "temperature": 0.2,
        "max_tokens": 512,  # Reduced from 1024 - typical output ~150-300 tokens
        "top_p": None,
    },
    "correction": {
        "model_hint": "small",
        "temperature": 0.2,
        "max_tokens": 512,  # Reduced from 1024 - typical output ~200-350 tokens
        "top_p": None,
    },
    "strategy": {
        "model_hint": "medium",
        "temperature": 0.3,  # Slightly creative for topic advice
        "max_tokens": 2048,  # Deep planning needs more space
        "top_p": None,
    },
    "response_polish": {
        "model_hint": "small",
        "temperature": 0.4,  # Slightly creative for natural tone
        "max_tokens": 512,  # Must accommodate full polished messages from specialists
        "top_p": None,
    },
}


def _get_node_llm_config(node_name: str) -> Dict[str, Any]:
    """Get LLM configuration for a specific node, with fallback to defaults."""
    config = _NODE_LLM_CONFIG.get(node_name, {})
    return {
        "model_hint": config.get("model_hint", "medium"),
        "temperature": config.get("temperature", settings.openai_plan_temperature),
        "max_tokens": config.get("max_tokens", settings.openai_plan_max_tokens),
        "top_p": config.get("top_p"),
    }


# Generate plan trigger message
_GENERATE_PLAN_TRIGGER = "GENERATE_PLAN_NOW"


def _is_generate_plan_trigger(message: str) -> bool:
    """Check if the message is the special generate plan trigger."""
    return message.strip().upper() == _GENERATE_PLAN_TRIGGER


# =============================================================================
# SHORT-CIRCUIT PATTERNS FOR LIGHTWEIGHT FLOW
# =============================================================================
# These patterns detect simple inputs that can bypass the LLM router/specialist
# pipeline, saving ~800 tokens per message.

# Pattern: Greetings (hi, hello, hey, good morning, etc.)
_GREETING_PATTERN = re.compile(
    r"^(h(i|ey|ello|iya|owdy)|yo|sup|good\s+(morning|afternoon|evening|day)|"
    r"what'?s\s+up|greetings?)[\s\.\!\?]*$",
    re.IGNORECASE,
)

# Pattern: Simple confirmations (yes, yeah, yep, yup)
_YES_PATTERN = re.compile(
    r"^(yes|yeah|yep|yup|yea|ya|sure|ok(ay)?|alright|all\s+right|"
    r"sounds?\s+good|absolutely|definitely|of\s+course|please|do\s+it|go\s+ahead|"
    r"let'?s\s+do\s+(it|this|that)|ok(ay)?\s+go\s+ahead)[\s\.\!\?]*$",
    re.IGNORECASE,
)

# Pattern: Simple negations (no, nope, nah, not really)
_NO_PATTERN = re.compile(
    r"^(no|nope|nah|not\s+really|no\s+thanks?|never\s*mind|cancel|"
    r"don'?t|stop|wait|hold\s+on)[\s\.\!\?]*$",
    re.IGNORECASE,
)

# Friendly greeting responses (randomized for variety)
_GREETING_RESPONSES = [
    "Hi! 👋 Where are you looking to travel?",
    "Hello! What destination is calling your name?",
    "Hey! Ready to plan a trip. Where to?",
    "Hi there! Where would you like to go?",
]

# Off-topic deflection responses (used when router detects non-travel queries)
_OFF_TOPIC_DEFLECTIONS = [
    "I'm here to help with travel planning! Where would you like to go?",
    "That's outside my expertise—but I'd love to help plan your next trip! 🌍",
    "I specialize in travel! Got a destination in mind?",
    "I'm your travel assistant! Tell me where you'd like to explore.",
    "That's not quite my area, but I'm great at planning adventures! Where to?",
]


def _debug_short_circuit_decision(
    input_text: str,
    detected_type: Optional[str],
    last_field: Optional[str],
    decision: str,
    reason: Optional[str] = None,
    parsed_data: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Log structured observability data for short-circuit decisions.

    Format: [SHORT_CIRCUIT] input="..." type=... last_field=... decision=... reason=...

    Args:
        input_text: The raw user input (truncated for logging).
        detected_type: The short-circuit type detected (or None if bypassed).
        last_field: The last_question_field from previous turn.
        decision: TRIGGERED, BYPASSED, or PATTERN_MISS.
        reason: Optional explanation for the decision.
        parsed_data: Optional parsed data extracted from the input.
    """
    truncated = input_text[:30] + "..." if len(input_text) > 30 else input_text
    parts = [
        f'[SHORT_CIRCUIT] input="{truncated}"',
        f"type={detected_type or 'none'}",
        f"last_field={last_field or 'none'}",
        f"decision={decision}",
    ]
    if reason:
        parts.append(f"reason={reason}")
    if parsed_data:
        parts.append(f"parsed={parsed_data}")
    _debug(" ".join(parts))


def _detect_short_circuit(text: str, state: "GraphState") -> Optional[Dict[str, Any]]:
    """
    Detect if user input can be short-circuited without LLM calls.

    Returns a dict with:
        - type: str - the short-circuit type (greeting, acknowledgment, etc.)
        - response: Optional[str] - a template response, or None to use default follow-up
        - action: Optional[str] - an action to execute (for confirmations)
        - parsed: Optional[Dict] - extracted data to merge (for bare field inputs)

    Returns None if the input should go through the normal LLM pipeline.
    """
    text_clean = text.strip()
    last_field = state.metadata.get("last_question_field")

    # Skip short-circuit if there's substantial content (>50 chars usually has travel info)
    if len(text_clean) > 50:
        _debug_short_circuit_decision(text, None, last_field, "BYPASSED", reason="input_too_long")
        return None

    # 1. Greetings
    if _GREETING_PATTERN.match(text_clean):
        _debug_short_circuit_decision(text, "greeting", last_field, "TRIGGERED")
        return {
            "type": "greeting",
            "response": _random_module.choice(_GREETING_RESPONSES),
            "action": None,
            "parsed": None,
        }

    pending = state.metadata.get("pending_action")

    # 2. Pending-action confirmations should be evaluated BEFORE acknowledgments
    # so ambiguous tokens like "sure" or "sounds good" act as a real confirm/deny.
    if pending and _YES_PATTERN.match(text_clean):
        pending = state.metadata.get("pending_action")
        if pending == "generate_plan":
            # Execute the pending action
            _debug_short_circuit_decision(
                text, "confirmation_yes", last_field, "TRIGGERED", reason=f"pending={pending}"
            )
            return {
                "type": "confirmation_yes",
                "response": None,
                "action": "generate_plan",
                "parsed": None,
            }
        if pending == "confirm_typo":
            # Apply the typo corrections stored in metadata
            typo_corrections = state.metadata.get("pending_typo_corrections", {})
            _debug_short_circuit_decision(
                text,
                "confirm_typo",
                last_field,
                "TRIGGERED",
                reason=f"pending={pending}",
                parsed_data=typo_corrections,
            )
            return {
                "type": "confirm_typo",
                "response": None,
                "action": "apply_typo_corrections",
                "parsed": {"typo_corrections": typo_corrections},
            }
        # Generic yes without pending action - just acknowledge and continue
        _debug_short_circuit_decision(text, "confirmation_yes", last_field, "TRIGGERED")
        return {
            "type": "confirmation_yes",
            "response": None,
            "action": None,
            "parsed": None,
        }

    if pending and _NO_PATTERN.match(text_clean):
        pending = state.metadata.get("pending_action")
        if pending:
            # Clear the pending action
            _debug_short_circuit_decision(
                text, "confirmation_no", last_field, "TRIGGERED", reason=f"pending={pending}"
            )
            return {
                "type": "confirmation_no",
                "response": "No problem. What would you like to do instead?",
                "action": "clear_pending",
                "parsed": None,
            }
        _debug_short_circuit_decision(text, "confirmation_no", last_field, "TRIGGERED")
        return {
            "type": "confirmation_no",
            "response": None,
            "action": None,
            "parsed": None,
        }

    # 3. Acknowledgments - REMOVED: Now handled by LLM extractor for better context awareness

    # 4. Simple confirmations (yes, yeah)
    if _YES_PATTERN.match(text_clean):
        pending = state.metadata.get("pending_action")
        if pending == "generate_plan":
            # Execute the pending action
            _debug_short_circuit_decision(
                text, "confirmation_yes", last_field, "TRIGGERED", reason=f"pending={pending}"
            )
            return {
                "type": "confirmation_yes",
                "response": None,
                "action": "generate_plan",
                "parsed": None,
            }
        # Generic yes without pending action - just acknowledge and continue
        return {
            "type": "confirmation_yes",
            "response": None,
            "action": None,
            "parsed": None,
        }

    # 5. Simple negations (no, nope)
    if _NO_PATTERN.match(text_clean):
        pending = state.metadata.get("pending_action")
        if pending:
            # Clear the pending action
            return {
                "type": "confirmation_no",
                "response": "No problem. What would you like to do instead?",
                "action": "clear_pending",
                "parsed": None,
            }
        return {
            "type": "confirmation_no",
            "response": None,
            "action": None,
            "parsed": None,
        }

    # 6-10. Off-topic, bare inputs - REMOVED: Now handled by LLM for better accuracy
    # Off-topic detection moved to router node with off_topic intent
    # Bare destination/date/travelers/origin detection removed - too brittle

    # No short-circuit detected - let LLM handle it
    _debug_short_circuit_decision(
        text, None, last_field, "PATTERN_MISS", reason="no_pattern_matched"
    )
    return None


# =============================================================================
# DOCUMENT SERIALIZATION FOR LLM CONTEXT (ported from plan.py)
# =============================================================================


def _serialize_branches_for_llm(
    branches: List[Dict[str, Any]], tiles: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    Serialize branches and tiles for LLM context.

    This function converts the branches and tiles into a text format that
    the LLM can understand when refining existing plans.

    Args:
        branches: List of branch dictionaries.
        tiles: Optional dict of tile_id -> tile info.

    Returns:
        Optional[str]: A formatted text representation of branches/tiles,
                       or None if no branches exist.
    """
    if not branches:
        return None

    lines: List[str] = []

    # Branches with their info
    lines.append(f"=== EXISTING BRANCHES ({len(branches)}) ===")
    for idx, branch in enumerate(branches):
        primary_marker = " (PRIMARY)" if idx == 0 else ""
        lines.append(f"\nBranch: {branch.get('label', 'Unnamed')}{primary_marker}")
        lines.append(f"  ID: {branch.get('id', 'unknown')}")
        if branch.get("description"):
            lines.append(f"  Description: {branch['description']}")
        if branch.get("destinations"):
            dests = branch["destinations"]
            if isinstance(dests, list):
                lines.append(f"  Destinations: {', '.join(dests)}")
            else:
                lines.append(f"  Destinations: {dests}")
        if branch.get("origin"):
            lines.append(f"  Origin: {branch['origin']}")
        if branch.get("start_date"):
            lines.append(f"  Dates: {branch['start_date']} to {branch.get('end_date', 'TBD')}")
        traveler_parts = []
        if branch.get("adults"):
            traveler_parts.append(f"{branch['adults']} adult(s)")
        if branch.get("children"):
            traveler_parts.append(f"{branch['children']} child(ren)")
        if traveler_parts:
            lines.append(f"  Travelers: {', '.join(traveler_parts)}")
        if branch.get("requires_assistance"):
            lines.append("  Requires assistance: Yes")
        if branch.get("budget") is not None:
            currency = branch.get("currency", "USD")
            lines.append(f"  Budget: {branch['budget']} {currency}")

    # Available tiles (abbreviated) if provided
    if tiles:
        lines.append(f"\n=== AVAILABLE TILES ({len(tiles)}) ===")
        by_type: Dict[str, List[str]] = {"flight": [], "hotel": [], "activity": []}
        for _tile_id, tile in tiles.items():
            if isinstance(tile, dict):
                tile_type = tile.get("type", "activity")
                title = tile.get("title", "Unknown")
                price_info = ""
                if tile.get("live_price") is not None:
                    price_info = f" ({tile['live_price']} {tile.get('currency', '')})"
                elif tile.get("price_estimate") is not None:
                    price_info = f" (~{tile['price_estimate']} {tile.get('currency', '')})"
                by_type.setdefault(tile_type, []).append(f"{title}{price_info}")
        for tile_type, tile_list in by_type.items():
            if tile_list:
                lines.append(f"{tile_type.upper()}S: {', '.join(tile_list[:5])}")
                if len(tile_list) > 5:
                    lines.append(f"  ... and {len(tile_list) - 5} more")

    return "\n".join(lines)


# =============================================================================
# DATE UTILITY FUNCTIONS (ported from plan.py)
# =============================================================================


def _today_iso(timezone_name: Optional[str] = None) -> str:
    """
    Get today's date in ISO format (YYYY-MM-DD).

    Uses the provided timezone if valid, otherwise falls back to UTC.
    """
    tz = None
    if timezone_name:
        try:
            tz = ZoneInfo(timezone_name)
        except Exception:
            pass  # Invalid timezone, fall back to UTC

    if tz:
        return datetime.now(tz).strftime("%Y-%m-%d")
    return datetime.now(UTC).strftime("%Y-%m-%d")


# =============================================================================
# INPUT NORMALIZATION FUNCTIONS (ported from plan.py)
# =============================================================================


def _normalize_str(value: Any) -> Optional[str]:
    """Convert any value to a trimmed string, returning None for empty values."""
    if value is None:
        return None
    value_str = str(value).strip()
    if not value_str or value_str.lower() == "null":
        return None
    return value_str


def _deduplicate_destinations(destinations: List[str]) -> List[str]:
    """
    Deduplicate destinations by removing sublocations when parent location exists.

    Examples:
    - ["Paris", "Marais district"] → ["Paris"] (Marais is in Paris)
    - ["Tokyo", "Shibuya"] → ["Tokyo"] (Shibuya is in Tokyo)
    - ["Italy", "Rome", "Florence"] → ["Italy"] or keep all if multi-city

    Also removes exact duplicates case-insensitively.
    """
    if not destinations or len(destinations) <= 1:
        return destinations

    # Known city-district relationships
    known_sublocations = {
        "marais": "paris",
        "marais district": "paris",
        "le marais": "paris",
        "montmartre": "paris",
        "latin quarter": "paris",
        "shibuya": "tokyo",
        "shinjuku": "tokyo",
        "ginza": "tokyo",
        "manhattan": "new york",
        "brooklyn": "new york",
        "soho": "london",
        "westminster": "london",
        "trastevere": "rome",
        "vatican": "rome",
        "kreuzberg": "berlin",
        "mitte": "berlin",
    }

    result = []
    seen_lower = set()
    parent_cities = set()

    # First pass: identify parent cities
    for dest in destinations:
        dest_lower = dest.lower().strip()
        # Check if this is a known parent city
        for _subloc, parent in known_sublocations.items():
            if parent == dest_lower:
                parent_cities.add(parent)

    # Second pass: filter out sublocations if parent exists
    for dest in destinations:
        dest_lower = dest.lower().strip()

        # Skip exact duplicates
        if dest_lower in seen_lower:
            continue

        # Skip sublocations if parent city is present
        if dest_lower in known_sublocations:
            parent = known_sublocations[dest_lower]
            if parent in parent_cities or any(parent in d.lower() for d in destinations):
                continue

        seen_lower.add(dest_lower)
        result.append(dest)

    return result if result else destinations  # Never return empty list


# =============================================================================
# DATE NORMALIZER (Consolidated date handling)
# =============================================================================
class DateNormalizer:
    """
    Centralized date normalization logic.

    Consolidates all date parsing, relative date conversion, and validation
    into a single class to eliminate duplication across nodes.

    Usage:
        normalizer = DateNormalizer()
        iso_date = normalizer.normalize("next week")
        iso_date, was_partial = normalizer.normalize_with_info("December 2025")
        end_date = normalizer.compute_end_from_duration("2025-01-01", 7)
    """

    # Pre-compiled patterns (class-level for efficiency)
    _ORDINAL_SUFFIX = re.compile(r"(\d+)(st|nd|rd|th)\b", re.IGNORECASE)
    _PARTIAL_DATE = re.compile(
        r"^(january|february|march|april|may|june|july|august|september|october|november|december"
        r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+(\d{4})$",
        re.IGNORECASE,
    )
    _ISO_FORMAT = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    # Relative date keywords
    _TODAY_WORDS = frozenset({"today", "tonight", "now"})

    # Supported date formats
    _DATE_FORMATS = (
        "%Y-%m-%d",  # 2025-12-28
        "%d-%m-%Y",  # 28-12-2025
        "%d/%m/%Y",  # 28/12/2025
        "%m/%d/%Y",  # 12/28/2025 (US format)
        "%m-%d-%Y",  # 12-28-2025 (US dash format)
        "%B %d, %Y",  # December 28, 2025
        "%b %d, %Y",  # Dec 28, 2025
        "%d %B %Y",  # 28 December 2025
        "%d %b %Y",  # 28 Dec 2025
        "%B %d %Y",  # December 28 2025 (no comma)
        "%b %d %Y",  # Dec 28 2025 (no comma)
        "%d %B, %Y",  # 28 December, 2025
        "%d %b, %Y",  # 28 Dec, 2025
    )

    def __init__(self, reference_date: Optional[date] = None):
        """
        Initialize with optional reference date for relative calculations.

        Args:
            reference_date: The "today" date for relative calculations.
                           Defaults to UTC today.
        """
        self._reference = reference_date or datetime.now(UTC).date()

    @property
    def today(self) -> date:
        """Get the reference date used for relative calculations."""
        return self._reference

    def relative_to_iso(self, text: Optional[str]) -> Optional[str]:
        """
        Convert relative date expressions to ISO format.

        Handles: today, tomorrow, next week, next month, weekend, this weekend
        """
        if not text:
            return None

        lowered = text.lower().strip()
        today = self._reference

        if lowered in self._TODAY_WORDS:
            return today.strftime("%Y-%m-%d")

        if lowered == "tomorrow":
            return (today + timedelta(days=1)).strftime("%Y-%m-%d")

        if "next week" in lowered:
            return (today + timedelta(days=7)).strftime("%Y-%m-%d")

        if "next month" in lowered:
            return (today + timedelta(days=30)).strftime("%Y-%m-%d")

        if "weekend" in lowered:
            days_until_saturday = (5 - today.weekday()) % 7
            if "next" in lowered and days_until_saturday <= 0:
                days_until_saturday += 7
            return (today + timedelta(days=days_until_saturday)).strftime("%Y-%m-%d")

        return None

    def normalize_with_info(self, value: Any) -> tuple[Optional[str], bool]:
        """
        Normalize various date formats to ISO format (YYYY-MM-DD).

        Returns:
            Tuple of (iso_date, was_partial) where was_partial indicates
            if the date was a partial date like "December 2025" that defaulted
            to the 1st of the month.
        """
        text = _normalize_str(value)
        if not text:
            return None, False

        # Try relative dates first
        relative = self.relative_to_iso(text)
        if relative:
            return relative, False

        # Strip ordinal suffixes before parsing (28th -> 28)
        text_cleaned = self._ORDINAL_SUFFIX.sub(r"\1", text)

        # Try various date formats
        for fmt in self._DATE_FORMATS:
            try:
                parsed = datetime.strptime(text_cleaned, fmt)
                return parsed.strftime("%Y-%m-%d"), False
            except ValueError:
                continue

        # Check for partial dates (month + year only)
        partial_match = self._PARTIAL_DATE.match(text_cleaned)
        if partial_match:
            month_str = partial_match.group(1)
            year_str = partial_match.group(2)
            for month_fmt in ("%B %d, %Y", "%b %d, %Y"):
                try:
                    parsed = datetime.strptime(f"{month_str} 1, {year_str}", month_fmt)
                    return parsed.strftime("%Y-%m-%d"), True
                except ValueError:
                    continue

        # Check if already ISO format
        if self._ISO_FORMAT.match(text_cleaned):
            return text_cleaned, False

        return None, False

    def normalize(self, value: Any) -> Optional[str]:
        """Normalize various date formats to ISO format (YYYY-MM-DD)."""
        result, _ = self.normalize_with_info(value)
        return result

    def parse_iso(self, text: Optional[str]) -> Optional[datetime]:
        """Parse an ISO date string to a datetime object."""
        if not text:
            return None
        try:
            return datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            return None

    def compute_end_from_duration(
        self, start_date: Optional[str], duration_days: int
    ) -> Optional[str]:
        """Compute end_date from start_date and duration in days."""
        if not start_date or duration_days <= 0:
            return None

        start_dt = self.parse_iso(start_date)
        if not start_dt:
            return None

        end_dt = start_dt + timedelta(days=duration_days)
        return end_dt.strftime("%Y-%m-%d")

    def is_valid_range(self, start_date: Optional[str], end_date: Optional[str]) -> bool:
        """Check if end_date >= start_date (allowing same-day trips)."""
        if not start_date or not end_date:
            return True  # Can't validate incomplete range

        start_dt = self.parse_iso(start_date)
        end_dt = self.parse_iso(end_date)
        if not start_dt or not end_dt:
            return True  # Can't validate unparseable dates

        return end_dt >= start_dt


# Singleton instance for default usage
_date_normalizer = DateNormalizer()


# =============================================================================
# NORMALIZATION ERROR
# =============================================================================
@dataclass
class NormalizationError:
    """
    Structured error from normalization with severity level.

    Attributes:
        field: The field name that had the error
        message: Human-readable error message
        severity: 'warning' for recoverable issues, 'error' for blocking issues
        original_value: The original value that caused the error
    """

    field: str
    message: str
    severity: Literal["warning", "error"]
    original_value: Any = None


# =============================================================================
# TRIP INPUT NORMALIZER (Unified normalization logic)
# =============================================================================
class TripInputNormalizer:
    """
    Unified normalization for all trip inputs.

    Consolidates all normalization logic (dates, destinations, currency, travelers,
    settings) into a single class. This is the ONLY place where normalization
    should occur in the graph.

    Usage:
        normalizer = TripInputNormalizer()
        updates, errors = normalizer.normalize_all(trip_inputs, deltas)
    """

    # Extended currency symbol map (from graph_plan_utils.py - more complete)
    CURRENCY_SYMBOL_MAP: Dict[str, str] = {
        "$": "USD",
        "€": "EUR",
        "£": "GBP",
        "¥": "JPY",
        "₹": "INR",
        "₩": "KRW",
        "₽": "RUB",
        "₺": "TRY",
        "R$": "BRL",
        "kr": "SEK",
        "CHF": "CHF",
        "A$": "AUD",
        "C$": "CAD",
        "NZ$": "NZD",
        "HK$": "HKD",
        "S$": "SGD",
    }

    # Extended ISO-4217 currency codes (from graph_plan_utils.py - 30 currencies)
    SUPPORTED_CURRENCIES: frozenset = frozenset(
        {
            "USD",
            "EUR",
            "GBP",
            "CAD",
            "AUD",
            "JPY",
            "CHF",
            "CNY",
            "INR",
            "MXN",
            "BRL",
            "KRW",
            "SGD",
            "HKD",
            "NOK",
            "SEK",
            "DKK",
            "NZD",
            "ZAR",
            "RUB",
            "TRY",
            "PLN",
            "THB",
            "MYR",
            "IDR",
            "PHP",
            "CZK",
            "ILS",
            "AED",
            "SAR",
        }
    )

    def __init__(self, date_normalizer: Optional[DateNormalizer] = None):
        """
        Initialize with optional DateNormalizer instance.

        Args:
            date_normalizer: DateNormalizer instance, uses global singleton if None.
        """
        self._date_normalizer = date_normalizer or _date_normalizer

    # -------------------------------------------------------------------------
    # Date Normalization (delegates to DateNormalizer)
    # -------------------------------------------------------------------------
    def normalize_date(self, value: Any) -> Optional[str]:
        """Normalize date to ISO format (YYYY-MM-DD)."""
        return self._date_normalizer.normalize(value)

    def normalize_date_with_info(self, value: Any) -> tuple[Optional[str], bool]:
        """Normalize date, returning (iso_date, was_partial)."""
        return self._date_normalizer.normalize_with_info(value)

    def validate_date_range(
        self,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> tuple[Optional[str], Optional[str], List[NormalizationError]]:
        """
        Validate and fix date range issues.

        Handles:
        - Cross-year correction (Dec start → Jan/Feb end)
        - Date auto-swap if end < start
        - Past date warnings

        Returns:
            Tuple of (corrected_start, corrected_end, errors)
        """
        errors: List[NormalizationError] = []
        corrected_start = start_date
        corrected_end = end_date

        if not start_date or not end_date:
            return corrected_start, corrected_end, errors

        start_dt = self._date_normalizer.parse_iso(start_date)
        end_dt = self._date_normalizer.parse_iso(end_date)

        if not start_dt or not end_dt:
            return corrected_start, corrected_end, errors

        # Cross-year correction: Dec start → Jan/Feb end likely means next year
        if start_dt.month == 12 and end_dt.month in (1, 2) and end_dt.year == start_dt.year:
            corrected_end_dt = end_dt.replace(year=start_dt.year + 1)
            corrected_end = corrected_end_dt.strftime("%Y-%m-%d")
            errors.append(
                NormalizationError(
                    field="end_date",
                    message=f"Corrected cross-year date: {end_date} → {corrected_end}",
                    severity="warning",
                    original_value=end_date,
                )
            )
            _debug(f"Corrected cross-year date range: {end_date} → {corrected_end}")
            end_dt = corrected_end_dt

        # Date auto-swap if end < start (after cross-year correction)
        if end_dt < start_dt:
            corrected_start, corrected_end = end_date, start_date
            if corrected_end != end_date:  # Was already corrected
                corrected_start = start_date
                corrected_end = end_dt.strftime("%Y-%m-%d")
            errors.append(
                NormalizationError(
                    field="dates",
                    message=f"Swapped dates: start={start_date}, end={end_date}",
                    severity="warning",
                    original_value={"start_date": start_date, "end_date": end_date},
                )
            )
            _debug(f"Auto-swapped dates: {start_date} ↔ {end_date}")

        # Past date warnings
        today = self._date_normalizer.today
        if start_dt.date() < today:
            errors.append(
                NormalizationError(
                    field="start_date",
                    message=f"Start date {start_date} is in the past",
                    severity="warning",
                    original_value=start_date,
                )
            )

        return corrected_start, corrected_end, errors

    # -------------------------------------------------------------------------
    # Currency Normalization
    # -------------------------------------------------------------------------
    def normalize_currency(self, value: Any, *, default: Optional[str] = None) -> Optional[str]:
        """
        Normalize currency to ISO-4217 code.

        Maps symbols ($, €, £, etc.) to codes and validates against ISO-4217.
        Uses extended set of 30 currencies.
        """
        if value is None:
            return default

        text = _normalize_str(value)
        if not text:
            return default

        # Check if it's a symbol
        if text in self.CURRENCY_SYMBOL_MAP:
            return self.CURRENCY_SYMBOL_MAP[text]

        # Uppercase and check against ISO codes
        code = text.upper()
        if code in self.SUPPORTED_CURRENCIES:
            return code

        # Check if symbol is part of value (e.g., "$100" -> extract $)
        for symbol, symbol_code in self.CURRENCY_SYMBOL_MAP.items():
            if text.startswith(symbol):
                return symbol_code

        return default

    # -------------------------------------------------------------------------
    # Traveler Normalization
    # -------------------------------------------------------------------------
    def clamp_travelers(self, value: Optional[int]) -> Optional[int]:
        """Constrain traveler count to valid range [0, 20]."""
        if value is None:
            return None
        return max(0, min(20, value))

    def normalize_adults(self, value: Any) -> Optional[int]:
        """Normalize adults count (min 1 when specified)."""
        int_val = _normalize_int(value)
        if int_val is None:
            return None
        return max(1, min(20, int_val))

    def normalize_children(self, value: Any) -> Optional[int]:
        """Normalize children count (min 0)."""
        int_val = _normalize_int(value)
        if int_val is None:
            return None
        return max(0, min(20, int_val))

    # -------------------------------------------------------------------------
    # Destination Normalization
    # -------------------------------------------------------------------------
    def normalize_destinations(
        self,
        destinations: List[str],
        new_destinations: Optional[List[str]] = None,
    ) -> tuple[List[str], List[NormalizationError]]:
        """
        Normalize and merge destinations.

        - Applies synonym mapping (NYC → New York City)
        - Filters phrase-like destinations containing excluded words
        - Deduplicates case-insensitively
        - Removes sublocations when parent exists

        Args:
            destinations: Existing destinations list
            new_destinations: New destinations to merge (optional)

        Returns:
            Tuple of (normalized_destinations, errors)
        """
        errors: List[NormalizationError] = []
        result = list(destinations)
        existing_lower = {d.lower() for d in result}

        if new_destinations:
            for d in new_destinations:
                d_norm = _normalize_str(d)
                if not d_norm:
                    continue

                # Apply synonym normalization
                d_norm = normalize_place_synonym(d_norm)
                d_lower = d_norm.lower()

                # Filter phrase-like destinations
                if any(word in d_lower for word in _DEST_EXCLUDE_WORDS):
                    errors.append(
                        NormalizationError(
                            field="destinations",
                            message=f"Filtered phrase-like destination: {d_norm}",
                            severity="warning",
                            original_value=d,
                        )
                    )
                    _debug(f"Filtering phrase-like destination: {d_norm}")
                    continue

                # Skip duplicates
                if d_lower not in existing_lower:
                    result.append(d_norm)
                    existing_lower.add(d_lower)

        # Deduplicate overlapping locations
        result = _deduplicate_destinations(result)

        return result, errors

    # -------------------------------------------------------------------------
    # Settings Normalization
    # -------------------------------------------------------------------------
    def merge_nested_settings(
        self,
        existing: Optional[Dict[str, Any]],
        delta: Dict[str, Any],
        list_fields: Optional[set] = None,
    ) -> Dict[str, Any]:
        """
        Merge nested settings dict with special handling for list fields.

        For list fields (like 'amenities'), extends rather than replaces.
        """
        list_fields = list_fields or {"amenities", "categories"}
        result = dict(existing) if existing else {}

        for key, value in delta.items():
            if key in list_fields and isinstance(value, list):
                # Extend list, avoiding duplicates
                existing_list = result.get(key, [])
                for item in value:
                    if item not in existing_list:
                        existing_list.append(item)
                result[key] = existing_list
            else:
                result[key] = value

        return result

    # -------------------------------------------------------------------------
    # Full Normalization Pass
    # -------------------------------------------------------------------------
    def normalize_all(
        self,
        trip_inputs: "TripInputs",
        deltas: Dict[str, Any],
    ) -> tuple[Dict[str, Any], List[NormalizationError]]:
        """
        Single normalization pass for all trip inputs.

        This is the ONLY place where normalization should occur.
        Called from normalize_inputs node.

        Args:
            trip_inputs: Current TripInputs state
            deltas: Dict of field deltas to apply (from extractor)

        Returns:
            Tuple of (updates_dict, errors_list)
        """
        _debug("TripInputNormalizer.normalize_all called - single normalization pass")

        updates: Dict[str, Any] = {}
        errors: List[NormalizationError] = []

        # --- Origin ---
        if "origin_delta" in deltas:
            origin_raw = _normalize_str(deltas["origin_delta"])
            if origin_raw:
                updates["origin"] = normalize_place_synonym(origin_raw)

        # --- Destinations ---
        if "destinations_delta" in deltas:
            dest_list = deltas["destinations_delta"]
            if isinstance(dest_list, str):
                dest_list = [dest_list]
            if isinstance(dest_list, list):
                normalized_dests, dest_errors = self.normalize_destinations(
                    trip_inputs.destinations, dest_list
                )
                if normalized_dests != trip_inputs.destinations:
                    updates["destinations"] = normalized_dests
                errors.extend(dest_errors)

        # --- Dates ---
        partial_date_notifications: List[str] = []

        if "start_date_hint" in deltas and not trip_inputs.start_date:
            raw_hint = deltas["start_date_hint"]
            iso_date, was_partial = self.normalize_date_with_info(raw_hint)
            if iso_date:
                updates["start_date"] = iso_date
                if was_partial:
                    partial_date_notifications.append(
                        f"start_date set to first of month from '{raw_hint}'"
                    )

        if "end_date_hint" in deltas:
            raw_hint = deltas["end_date_hint"]
            iso_date, was_partial = self.normalize_date_with_info(raw_hint)
            if iso_date:
                updates["end_date"] = iso_date
                if was_partial:
                    partial_date_notifications.append(
                        f"end_date set to first of month from '{raw_hint}'"
                    )

        # Duration-based end_date computation
        if "duration_days_hint" in deltas and not trip_inputs.end_date:
            start = updates.get("start_date") or trip_inputs.start_date
            duration = _normalize_int(deltas["duration_days_hint"])
            if start and duration and duration > 0:
                end = self._date_normalizer.compute_end_from_duration(start, duration)
                if end:
                    updates["end_date"] = end
                    updates["duration_days"] = duration

        # Validate date range (cross-year, swap, past-date)
        start = updates.get("start_date") or trip_inputs.start_date
        end = updates.get("end_date") or trip_inputs.end_date
        if start and end:
            corrected_start, corrected_end, date_errors = self.validate_date_range(start, end)
            if corrected_start != start:
                updates["start_date"] = corrected_start
            if corrected_end != end:
                updates["end_date"] = corrected_end
            errors.extend(date_errors)

        # Store partial date notifications in metadata
        if partial_date_notifications:
            updates["_partial_date_notifications"] = partial_date_notifications

        # --- Travelers ---
        if "adults_delta" in deltas:
            adults = self.normalize_adults(deltas["adults_delta"])
            if adults is not None:
                updates["adults"] = adults

        if "children_delta" in deltas:
            children = self.normalize_children(deltas["children_delta"])
            if children is not None:
                updates["children"] = children

        if "requires_assistance_delta" in deltas:
            updates["requires_assistance"] = deltas["requires_assistance_delta"]

        # --- Budget & Currency ---
        if "budget_delta" in deltas:
            budget = _normalize_budget(deltas["budget_delta"])
            if budget is not None:
                updates["budget"] = budget

        if "currency_delta" in deltas:
            currency = self.normalize_currency(deltas["currency_delta"])
            if currency:
                updates["currency"] = currency
        elif "budget_delta" in deltas and not trip_inputs.currency:
            # Default currency if budget set but no currency
            updates["currency"] = DEFAULT_CURRENCY

        # --- Multi-city Intent ---
        if "multi_city_intent_delta" in deltas:
            intent = _normalize_multi_city_intent(deltas["multi_city_intent_delta"])
            if intent:
                updates["multi_city_intent"] = intent

        # --- Settings (flight, hotel, transport, activity) ---
        if "flight_settings_delta" in deltas:
            delta = deltas["flight_settings_delta"]
            if isinstance(delta, dict):
                normalized = _normalize_booking_field("flight_settings", delta)
                if normalized:
                    merged = self.merge_nested_settings(trip_inputs.flight_settings, normalized)
                    updates["flight_settings"] = merged

        if "hotel_settings_delta" in deltas:
            delta = deltas["hotel_settings_delta"]
            if isinstance(delta, dict):
                normalized = _normalize_booking_field("hotel_settings", delta)
                if normalized:
                    merged = self.merge_nested_settings(
                        trip_inputs.hotel_settings, normalized, list_fields={"amenities"}
                    )
                    updates["hotel_settings"] = merged

        if "transport_settings_delta" in deltas:
            delta = deltas["transport_settings_delta"]
            if isinstance(delta, dict):
                normalized = _normalize_booking_field("transport_settings", delta)
                if normalized:
                    merged = self.merge_nested_settings(trip_inputs.transport_settings, normalized)
                    updates["transport_settings"] = merged

        if "activity_categories_delta" in deltas:
            delta = deltas["activity_categories_delta"]
            if isinstance(delta, list):
                existing = trip_inputs.activity_settings or {}
                existing_cats = existing.get("categories", [])
                # Normalize activities with emojis and deduplicate
                for cat in delta:
                    normalized_cat = _normalize_activity_with_emoji(cat)
                    if normalized_cat and normalized_cat not in existing_cats:
                        existing_cats.append(normalized_cat)
                existing_cats = _deduplicate_activities_case_insensitive(existing_cats)
                updates["activity_settings"] = {"categories": existing_cats}

        # --- Category Activation (booking types) ---
        if "category_activation" in deltas:
            activation = deltas["category_activation"]
            if isinstance(activation, dict):
                booking_types = dict(trip_inputs.booking_types or DEFAULT_BOOKING_TYPES)
                for cat, enabled in activation.items():
                    if cat in booking_types and isinstance(enabled, bool):
                        booking_types[cat] = enabled
                updates["booking_types"] = booking_types

        return updates, errors


# Singleton instance for default usage
_trip_normalizer = TripInputNormalizer()


def _normalize_date(value: Any) -> Optional[str]:
    """Normalize various date formats to ISO format (YYYY-MM-DD)."""
    return _date_normalizer.normalize(value)


def _parse_iso_date(text: Optional[str]) -> Optional[datetime]:
    """Parse an ISO date string to a datetime object."""
    return _date_normalizer.parse_iso(text)


def _normalize_int(value: Any) -> Optional[int]:
    """Convert any value to an integer."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(str(value).strip())
        except Exception:
            return None


def _normalize_budget(value: Any) -> Optional[float]:
    """Normalize a budget value to a float, handling currency symbols."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # Remove currency symbols and commas, extract number
        cleaned = re.sub(r"[^\d.]", "", value)
        if cleaned:
            try:
                return float(cleaned)
            except ValueError:
                return None
    return None


def _normalize_currency(value: Any, *, default: Optional[str] = None) -> Optional[str]:
    """Normalize a currency value to a supported 3-letter code."""
    if value is None:
        return default

    symbol_map = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}

    text = _normalize_str(value)
    if not text:
        return default

    if text in symbol_map:
        text = symbol_map[text]

    code = text.upper()
    if code in SUPPORTED_CURRENCIES:
        return code

    return default


def _normalize_multi_city_intent(value: Any) -> Optional[str]:
    """
    Normalize multi-city intent from canonical values or natural language phrases.
    """
    if value is None:
        return None

    if isinstance(value, bool):
        return "multi_city" if value else "separate"

    text = _normalize_str(value)
    if not text:
        return None

    normalized = re.sub(r"\s+", " ", text.lower().replace("_", " ").replace("-", " ")).strip()

    # Quick exact matches
    if normalized in {
        "multi city",
        "multicity",
        "multi city trip",
        "multi city itinerary",
        "multi city intent",
    }:
        return "multi_city"
    if normalized in {
        "separate",
        "separate trip",
        "separate trips",
        "separate itinerary",
        "separate itineraries",
    }:
        return "separate"

    # Phrase-based inference
    separate_phrases = (
        "separate trip",
        "separate trips",
        "do them separately",
        "different trips",
        "compare destinations",
        "compare them",
    )
    multi_phrases = (
        "multi city",
        "multicity",
        "one trip",
        "single trip",
        "same trip",
        "together",
        "all together",
        "one itinerary",
        "visit both",
        "visit all",
        "see both",
        "do both",
    )

    if "not separate" not in normalized:
        for phrase in separate_phrases:
            if phrase in normalized:
                return "separate"

    for phrase in multi_phrases:
        if phrase in normalized:
            return "multi_city"

    return None


def _clamp_traveler_value(value: Optional[int]) -> Optional[int]:
    """Constrain a traveler count to valid range [0, 20]."""
    if value is None:
        return None
    return max(0, min(20, value))


def _should_skip_field_update(field: str, value: Any, current_value: Any) -> bool:
    """
    Check if a field update should be skipped to avoid false change detection.

    Returns True if the new value is effectively "no change" compared to the default None.
    This prevents the frontend from showing change animations for fields that weren't
    actually modified by the user.
    """
    # Skip None values
    if value is None:
        return True

    # Skip empty strings for string fields that default to None
    if field in ("origin", "start_date", "end_date", "multi_city_intent") and value == "":
        return True

    # Skip False for boolean fields that default to None
    if field == "requires_assistance" and value is False and current_value is None:
        return True

    # Skip 0 for numeric fields that default to None (only if current is None)
    if field in ("adults", "children", "budget") and value == 0 and current_value is None:
        return True

    return False


# =============================================================================
# BOOKING AUTO-ENABLE LOGIC (ported from plan.py)
# =============================================================================


def _ensure_booking_types(trip_inputs: dict) -> dict:
    """Guarantee booking_types exists with all keys."""
    existing = trip_inputs.get("booking_types")
    if not isinstance(existing, dict):
        existing = dict(DEFAULT_BOOKING_TYPES)
    else:
        existing = {**DEFAULT_BOOKING_TYPES, **existing}
    trip_inputs["booking_types"] = existing
    return existing


def _should_enable_booking_for_flights(flight_settings: dict | None) -> bool:
    if not flight_settings or not isinstance(flight_settings, dict):
        return False
    return (
        (
            "cabin_class" in flight_settings
            and flight_settings.get("cabin_class") != DEFAULT_FLIGHT_SETTINGS["cabin_class"]
        )
        or ("direct_only" in flight_settings and flight_settings.get("direct_only") is True)
        or (
            "round_trip" in flight_settings
            and flight_settings.get("round_trip") != DEFAULT_FLIGHT_SETTINGS["round_trip"]
        )
    )


def _should_enable_booking_for_hotels(hotel_settings: dict | None) -> bool:
    if not hotel_settings or not isinstance(hotel_settings, dict):
        return False
    min_stars = hotel_settings.get("min_stars", 0)
    if min_stars and min_stars > 0:
        return True
    amenities = hotel_settings.get("amenities") or []
    return isinstance(amenities, list) and len(amenities) > 0


def _should_enable_booking_for_activities(activity_settings: dict | None) -> bool:
    if not activity_settings or not isinstance(activity_settings, dict):
        return False
    categories = activity_settings.get("categories") or []
    return isinstance(categories, list) and len(categories) > 0


def _should_enable_booking_for_transport(transport_settings: dict | None) -> bool:
    if not transport_settings or not isinstance(transport_settings, dict):
        return False
    return any(transport_settings.get(key) is True for key in ("car", "train", "bus"))


def _auto_enable_booking_types(trip_inputs: TripInputs) -> None:
    """Auto-enable booking_types based on sub-settings."""
    booking_types = dict(trip_inputs.booking_types) if trip_inputs.booking_types else {}

    if _should_enable_booking_for_flights(trip_inputs.flight_settings):
        booking_types["flights"] = True
    if _should_enable_booking_for_hotels(trip_inputs.hotel_settings):
        booking_types["hotels"] = True
    if _should_enable_booking_for_activities(trip_inputs.activity_settings):
        booking_types["activities"] = True
    if _should_enable_booking_for_transport(trip_inputs.transport_settings):
        booking_types["ground_transport"] = True

    trip_inputs.booking_types = booking_types


# =============================================================================
# BOOKING FIELD NORMALIZATION (ported from plan.py)
# =============================================================================


def _normalize_booking_field(field: str, raw_value: dict) -> Optional[dict]:
    """Normalize a booking preference field from LLM output."""
    if not isinstance(raw_value, dict):
        return None

    if field == "booking_types":
        result = {}
        for key in ("hotels", "flights", "ground_transport", "activities"):
            if key in raw_value and isinstance(raw_value[key], bool):
                result[key] = raw_value[key]
        return result if result else None

    if field == "flight_settings":
        result = {}
        if "round_trip" in raw_value and isinstance(raw_value["round_trip"], bool):
            result["round_trip"] = raw_value["round_trip"]
        if "cabin_class" in raw_value:
            cabin = str(raw_value["cabin_class"]).lower().replace(" ", "_")
            if cabin in ("economy", "premium_economy", "business", "first"):
                result["cabin_class"] = cabin
        if "direct_only" in raw_value and isinstance(raw_value["direct_only"], bool):
            result["direct_only"] = raw_value["direct_only"]
        return result if result else None

    if field == "hotel_settings":
        result = {}
        if "min_stars" in raw_value:
            stars = _normalize_int(raw_value["min_stars"])
            if stars is not None:
                result["min_stars"] = max(0, min(5, stars))
        if "amenities" in raw_value:
            amenities = raw_value["amenities"]
            if isinstance(amenities, list):
                normalized_amenities = []
                for a in amenities:
                    a_str = _normalize_str(a)
                    if a_str:
                        normalized_amenities.append(a_str.lower())
                result["amenities"] = normalized_amenities
        return result if result else None

    if field == "activity_settings":
        result = {}
        if "categories" in raw_value:
            categories = raw_value["categories"]
            if isinstance(categories, list):
                normalized_categories = []
                for cat in categories:
                    cat_str = _normalize_str(cat)
                    if cat_str:
                        # Ensure activity has emoji prefix
                        cat_with_emoji = _normalize_activity_with_emoji(cat_str)
                        normalized_categories.append(cat_with_emoji)
                if normalized_categories:
                    # Deduplicate case-insensitively (compares text portion only)
                    deduped = _deduplicate_activities_case_insensitive(normalized_categories)
                    result["categories"] = deduped
        return result if result else None

    if field == "transport_settings":
        result = {}
        for key in ("car", "train", "bus"):
            if key in raw_value and isinstance(raw_value[key], bool):
                result[key] = raw_value[key]
        return result if result else None

    return None


# =============================================================================
# BRANCH NORMALIZATION (ported from plan.py)
# =============================================================================


def _normalize_branch_spec(spec: dict, fallback_inputs: dict) -> Optional[dict]:
    """Normalize a branch specification from LLM output."""
    if not isinstance(spec, dict) or "label" not in spec:
        return None

    # Handle destinations as array
    branch_destinations = spec.get("destinations", [])
    if not isinstance(branch_destinations, list):
        branch_destinations = [branch_destinations] if branch_destinations else []
    branch_destinations = [_normalize_str(d) for d in branch_destinations if d]
    if not branch_destinations:
        branch_destinations = fallback_inputs.get("destinations", [])
    if not branch_destinations:
        return None

    # Normalize other fields with fallbacks
    branch_origin = _normalize_str(spec.get("origin")) or fallback_inputs.get("origin")
    branch_start = _normalize_date(spec.get("start_date")) or fallback_inputs.get("start_date")
    branch_end = _normalize_date(spec.get("end_date")) or fallback_inputs.get("end_date")

    branch_adults = _normalize_int(spec.get("adults"))
    if branch_adults is None:
        branch_adults = _normalize_int(fallback_inputs.get("adults"))
    if branch_adults is not None:
        branch_adults = _clamp_traveler_value(branch_adults)

    branch_children = _normalize_int(spec.get("children"))
    if branch_children is None:
        branch_children = _normalize_int(fallback_inputs.get("children"))
    if branch_children is not None:
        branch_children = _clamp_traveler_value(branch_children)

    branch_requires_assistance = spec.get("requires_assistance")
    if branch_requires_assistance is None:
        branch_requires_assistance = fallback_inputs.get("requires_assistance")
    if branch_requires_assistance is not None and not isinstance(branch_requires_assistance, bool):
        branch_requires_assistance = None

    branch_budget = _normalize_budget(spec.get("budget"))
    if branch_budget is None:
        branch_budget = _normalize_budget(fallback_inputs.get("budget"))
    if branch_budget is not None and isinstance(branch_budget, (int, float)) and branch_budget < 0:
        branch_budget = None

    branch_currency = _normalize_currency(
        spec.get("currency"), default=_normalize_currency(fallback_inputs.get("currency"))
    )
    if branch_currency is None:
        branch_currency = DEFAULT_CURRENCY

    return {
        "id": spec.get("id") or uuid4().hex[:8],
        "label": str(spec["label"]),
        "description": str(spec.get("description", "")),
        "destinations": branch_destinations,
        "origin": branch_origin,
        "start_date": branch_start,
        "end_date": branch_end,
        "adults": branch_adults,
        "children": branch_children,
        "requires_assistance": branch_requires_assistance,
        "budget": branch_budget,
        "currency": branch_currency,
    }


# =============================================================================
# MISSING FIELDS & DEFAULT QUESTION (ported from plan.py)
# =============================================================================


def _compute_missing_fields(trip_inputs: dict) -> List[str]:
    """Compute the list of missing REQUIRED trip input fields."""
    missing = []
    for field in _REQUIRED_TRIP_INPUT_FIELDS:
        if field == "destinations":
            val = trip_inputs.get(field, [])
            if not val or (isinstance(val, list) and len(val) == 0):
                missing.append(field)
        elif trip_inputs.get(field) is None:
            missing.append(field)
    return missing


def _infer_question_target_from_missing(state: "GraphState") -> Optional[str]:
    """Infer question_target from missing required fields.

    When an LLM doesn't provide a question_target, we infer it from the
    first missing required field. This enables contextual suggestion
    generation even when the LLM response doesn't include question_target.

    Args:
        state: Current graph state

    Returns:
        The first missing required field as question_target, or None if all
        required fields are present.
    """
    ti = state.trip_inputs
    missing = _compute_missing_fields(ti.model_dump(exclude_none=True))
    if missing:
        # Return the first missing field as the question_target
        return missing[0]
    return None


def _default_follow_up_question(
    missing_fields: List[str],
    user_intent: str = "detailed_planner",
    user_tone: str = "neutral",
    trip_inputs: Optional[dict] = None,
) -> Optional[str]:
    """
    Get the default question to ask for the next missing field.
    Adapts phrasing based on user intent, tone, and existing trip context.
    Professional and natural—matches user energy without overdoing it.
    """
    if not missing_fields:
        return None

    trip_inputs = trip_inputs or {}
    destinations = trip_inputs.get("destinations", [])

    # When we know the destination, can reference it
    dest_name = destinations[0] if destinations else None

    # Helper to build destination-aware messages
    def _dest_prefix(template_with: str, template_without: str) -> str:
        if dest_name:
            return template_with.replace("{dest}", dest_name)
        return template_without

    # Base prompts - professional and warm (only required fields)
    base_prompts = {
        "destinations": "Where are you looking to go?",
        "origin": "Where are you flying from?",
        "start_date": _dest_prefix(
            "When are you heading to {dest}?", "When are you looking to travel?"
        ),
    }

    # Quick booking - minimal, efficient
    quick_prompts = {
        "destinations": "Where to?",
        "origin": "Flying from?",
        "start_date": "When?",
    }

    # Adventurous - match energy but don't overdo
    adventurous_prompts = {
        "destinations": "Where is the adventure taking you?",
        "origin": "Where are you coming from?",
        "start_date": _dest_prefix("When are you heading to {dest}?", "When does the trip start?"),
        "end_date": "When do you need to be back?",
        "adults": "How many in your group?",
        "budget": "What is your budget?",
    }

    # Undecided - helpful guide
    undecided_prompts = {
        "destinations": (
            "Any destinations you have been thinking about? "
            "Or I can suggest some based on what you are in the mood for."
        ),
        "origin": _dest_prefix(
            "{dest} is a good choice. Where will you be traveling from?",
            "Where will you be traveling from?",
        ),
        "start_date": "Do you have any dates in mind?",
        "end_date": "Any idea when you would like to return?",
        "adults": "How many people are traveling?",
        "budget": "Do you have a rough budget in mind?",
    }

    # Short trip - acknowledge time constraints
    short_trip_prompts = {
        "destinations": "Where are you thinking for a quick trip?",
        "origin": _dest_prefix(
            "{dest} is great for a short trip. Where are you flying from?",
            "Where are you flying from?",
        ),
        "start_date": "When are you going?",
        "end_date": "When do you need to be back?",
        "adults": "How many travelers?",
        "budget": "Budget for this trip?",
    }

    # Select prompt set based on intent
    if user_intent == "quick_booking":
        prompts = quick_prompts
    elif user_intent == "adventurous":
        prompts = adventurous_prompts
    elif user_intent == "undecided":
        prompts = undecided_prompts
    elif user_intent == "short_trip":
        prompts = short_trip_prompts
    else:
        prompts = base_prompts

    # Find first missing required field
    for field in _REQUIRED_TRIP_INPUT_FIELDS:
        if field in missing_fields:
            question = prompts.get(field, base_prompts.get(field))
            if question:
                # Adjust for frustrated tone - be more direct, skip embellishments
                if user_tone == "frustrated":
                    # Use simpler, direct phrasing
                    question = quick_prompts.get(field, question)
                return question
    return None


def _default_follow_up_with_field(
    missing_fields: List[str],
    user_intent: str = "detailed_planner",
    user_tone: str = "neutral",
    trip_inputs: Optional[dict] = None,
) -> tuple[Optional[str], Optional[str]]:
    """
    Get the default question and the field being asked about.

    Returns a tuple of (question, field_name) for tracking which field
    was last asked, enabling context-aware clarification responses.
    """
    if not missing_fields:
        return None, None

    trip_inputs = trip_inputs or {}
    destinations = trip_inputs.get("destinations", [])
    dest_name = destinations[0] if destinations else None

    def _dest_prefix(template_with: str, template_without: str) -> str:
        if dest_name:
            return template_with.replace("{dest}", dest_name)
        return template_without

    # Base prompts (only required fields)
    base_prompts = {
        "destinations": "Where are you looking to go?",
        "origin": "Where are you flying from?",
        "start_date": _dest_prefix(
            "When are you heading to {dest}?", "When are you looking to travel?"
        ),
    }

    quick_prompts = {
        "destinations": "Where to?",
        "origin": "Flying from?",
        "start_date": "When?",
    }

    if user_intent == "quick_booking":
        prompts = quick_prompts
    else:
        prompts = base_prompts

    for field in _REQUIRED_TRIP_INPUT_FIELDS:
        if field in missing_fields:
            question = prompts.get(field, base_prompts.get(field))
            if question:
                if user_tone == "frustrated":
                    question = quick_prompts.get(field, question)
                return question, field
    return None, None


# =============================================================================
# SUGGESTED RESPONSES FILTERING (ported from plan.py)
# =============================================================================

# Patterns that indicate assistant-style phrasing (not user voice)
_ASSISTANT_PHRASES = frozenset(
    [
        "i can help",
        "let me",
        "i'll help",
        "would you like",
        "shall i",
        "i suggest",
        "i recommend",
        "we can",
        "we could",
        "here are",
        "here's",
        "feel free",
        "don't hesitate",
        "so i can",
        "assist you",
        "help you",
    ]
)

# Patterns indicating vague/placeholder content
_VAGUE_PATTERNS = frozenset(
    [
        "...",
        "[",
        "]",
        "enter",
        "select",
        "choose",
        "type",
        "input",
        "specify",
        "provide",
    ]
)

# Instruction-style verbs that indicate prompts, not user responses
_INSTRUCTION_STARTS = frozenset(
    [
        "add",
        "include",
        "specify",
        "provide",
        "enter",
        "select",
        "choose",
        "consider",
        "try",
        "explore",
        "look for",
        "looking for",
        "search for",
        "find",
        "get",
        "set",
        "update",
        "change",
    ]
)


def _is_low_quality_suggestion(text: str) -> bool:
    """Check if suggestion is too vague, assistant-style, or instruction-like."""
    lower = text.lower().strip()

    # Reject assistant-style phrases
    for phrase in _ASSISTANT_PHRASES:
        if phrase in lower:
            return True

    # Reject vague/placeholder patterns
    for pattern in _VAGUE_PATTERNS:
        if pattern in lower:
            return True

    # Reject instruction-style starts (these are prompts, not user responses)
    for instruction in _INSTRUCTION_STARTS:
        if lower.startswith(instruction + " ") or lower.startswith(instruction + " a "):
            return True

    # Reject request patterns (user asking the assistant to do something)
    request_patterns = [
        "please ",
        "can you ",
        "could you ",
        "would you ",
        "will you ",
        "i need you to",
        "i want you to",
        "i'd like you to",
    ]
    for pattern in request_patterns:
        if lower.startswith(pattern):
            return True

    # Reject if too short (less than 2 words) UNLESS it looks like a place name
    # Single-word destinations like "Nepal", "Bali", "Peru" are valid
    words = text.split()
    if len(words) < 2:
        # Reject single letters but allow 2-3 char uppercase abbreviations (LA, NYC, UK)
        if len(text) == 1:
            return True
        # Allow all-uppercase abbreviations (LA, UK, NYC, USA) - valid place codes
        if text.isupper() and len(text) <= 4:
            pass  # Allow these
        elif len(text) <= 2:
            # Reject 2-char lowercase or mixed case (not abbreviations)
            return True
        # Reject pure numbers (like "2", "10", "2024")
        if text.isdigit():
            return True
        # Reject common command words that might be capitalized
        command_words = {"go", "try", "set", "get", "add", "run", "use", "see", "ask", "let"}
        if lower in command_words:
            return True
        # Allow single words that start with uppercase (proper nouns = places)
        # or are at least 4 characters (likely a place name or valid term)
        if not (text[0].isupper() or len(text) >= 4):
            return True

    # Reject if too many words (more than 8)
    if len(words) > 8:
        return True

    # Reject generic fillers
    generic_fillers = {"yes", "no", "ok", "okay", "sure", "thanks", "thank you"}
    if lower in generic_fillers:
        return True

    # Reject suggestions that are too generic/vague (no concrete nouns)
    # Use word boundary matching to avoid false positives like "Adventure activities"
    vague_phrases = [
        "a specific",
        "the best",
        "some options",
        "more details",
        "more information",
        "something",
        "anything",
        "anywhere",  # too vague without specifics
        "somewhere",  # too vague without specifics
        "preferences",
        "by the beach",  # vague location
        "near the",
        "around the",
    ]
    for vague in vague_phrases:
        if vague in lower:
            return True

    # Reject if ONLY the word "activities" or "destination" (too generic alone)
    # But allow "Adventure activities", "Beach activities", etc.
    if lower == "activities" or lower == "destination":
        return True

    return False


def _filter_suggested_responses(responses: List[Any]) -> List[str]:
    """Filter suggested responses: remove questions, low-quality, limit to 3, handle dict format."""
    result = []
    seen_lower = set()  # Deduplicate case-insensitively

    for r in responses:
        # Handle dict format
        if isinstance(r, dict):
            text = r.get("text") or r.get("response") or r.get("value") or ""
        else:
            text = str(r) if r else ""

        text = text.strip()
        if not text:
            continue

        # Reject questions
        if "?" in text:
            continue

        # Reject low-quality suggestions
        if _is_low_quality_suggestion(text):
            continue

        # Deduplicate case-insensitively
        lower = text.lower()
        if lower in seen_lower:
            continue
        seen_lower.add(lower)

        # Limit length (truncate if needed, but prefer rejection for quality)
        if len(text) > 50:
            text = text[:47] + "..."

        result.append(text)

        if len(result) >= 3:
            break

    return result


# Universal cities for dynamic origin suggestions
_UNIVERSAL_ORIGIN_CITIES = [
    "London",
    "New York",
    "Paris",
    "Tokyo",
    "Dubai",
    "Sydney",
    "Los Angeles",
    "Singapore",
    "Hong Kong",
    "Berlin",
]

# Intent-aware destination suggestions
_ADVENTURE_DESTINATIONS = [
    "Swiss Alps",
    "Patagonia",
    "Nepal",
    "New Zealand",
    "Costa Rica",
    "Iceland",
    "Norway",
    "Peru",
]
_BEACH_DESTINATIONS = [
    "Bali",
    "Maldives",
    "Cancun",
    "Phuket",
    "Hawaii",
    "Fiji",
    "Seychelles",
    "Caribbean",
]
_CITY_DESTINATIONS = [
    "Rome",
    "Tokyo",
    "Barcelona",
    "Paris",
    "New York",
    "London",
    "Singapore",
    "Dubai",
]
_FOOD_DESTINATIONS = [
    "Paris",
    "Tokyo",
    "Bangkok",
    "Barcelona",
    "Mexico City",
    "Bologna",
    "Singapore",
    "Lima",
]
_SKIING_DESTINATIONS = [
    "Chamonix",
    "Aspen",
    "Zermatt",
    "Niseko",
    "Whistler",
    "St. Moritz",
    "Verbier",
    "Courchevel",
]

# Strategy topic to destination list mapping for fallback suggestions
_STRATEGY_DESTINATION_MAP = {
    "hiking": _ADVENTURE_DESTINATIONS,
    "cycling": _ADVENTURE_DESTINATIONS,
    "diving": _BEACH_DESTINATIONS,
    "boating": _BEACH_DESTINATIONS,
    "skiing": _SKIING_DESTINATIONS,
}

# Minimum relevance score threshold - suggestions below this are suppressed
_SUGGESTION_RELEVANCE_THRESHOLD = 0.5
# Minimum number of suggestions to show - if fewer pass threshold, show none
_MIN_SUGGESTIONS_TO_SHOW = 2


def _score_suggestion_relevance(
    suggestion: str,
    question_target: Optional[str],
    user_intent: Optional[str] = None,
) -> float:
    """
    Score how relevant a suggestion is to the question_target.

    Returns a score from 0.0 to 1.0:
    - 1.0: High confidence match
    - 0.7-0.9: Good match
    - 0.4-0.6: Weak match
    - 0.0-0.3: Mismatch

    Args:
        suggestion: The suggestion text to score
        question_target: What field the assistant is asking about
        user_intent: User intent (adventurous, quick_booking, etc.)
    """
    if not suggestion or not question_target:
        # If no question_target, we can't score relevance - accept suggestion
        return 0.8

    lower = suggestion.lower().strip()

    # Pattern matching for each question_target type
    if question_target == "origin":
        # Origin suggestions should start with "From" or be a city name
        if lower.startswith("from "):
            return 1.0
        # Check if it looks like a city (capitalized, no travel verbs)
        if not any(word in lower for word in ["to ", "visit", "go to", "explore"]):
            # Could be a city name without "From" - medium confidence
            return 0.6
        return 0.2  # Likely a destination, not origin

    elif question_target == "destinations":
        # Destination suggestions should NOT start with "From"
        if lower.startswith("from "):
            return 0.1  # This is an origin, not destination
        # Check for place-like patterns (proper nouns, location words)
        destination_indicators = [
            "beach",
            "island",
            "mountain",
            "city",
            "country",
            "alps",
            "coast",
            "bay",
            "valley",
            "lake",
        ]
        if any(ind in lower for ind in destination_indicators):
            return 1.0
        # If it contains comma (like "Paris, France"), likely a destination
        if "," in suggestion:
            return 0.95
        # Check if it matches adventure destinations for intent
        if user_intent == "adventurous":
            adventure_keywords = ["trek", "hike", "climb", "adventure", "explore"]
            if any(kw in lower for kw in adventure_keywords):
                return 0.9
        # Generic place name - accept with medium confidence
        if not any(word in lower for word in ["from ", "next ", "in ", " weeks", " month"]):
            return 0.8
        return 0.3

    elif question_target in ("dates", "start_date", "end_date"):
        # Date suggestions should contain time-related words
        date_indicators = [
            "month",
            "week",
            "december",
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "today",
            "tomorrow",
            "next",
            "in ",
            "spring",
            "summer",
            "fall",
            "winter",
            "christmas",
            "holiday",
            "-",  # For date ranges like "Dec 15-22"
        ]
        if any(ind in lower for ind in date_indicators):
            return 1.0
        # Check for numeric patterns (dates)
        if any(char.isdigit() for char in suggestion):
            return 0.9
        return 0.2  # Doesn't look like a date

    elif question_target in ("travelers", "adults"):
        # Traveler suggestions should mention numbers or group types
        traveler_indicators = [
            "solo",
            "just me",
            "couple",
            "family",
            "adult",
            "child",
            "kid",
            "person",
            "people",
            "1 ",
            "2 ",
            "3 ",
            "4 ",
            "5 ",
            "6 ",
            "me and",
            "with my",
            "group of",
        ]
        if any(ind in lower for ind in traveler_indicators):
            return 1.0
        # Check for numeric patterns
        if any(char.isdigit() for char in suggestion):
            return 0.8
        return 0.2  # Doesn't look like traveler info

    elif question_target == "budget":
        # Budget suggestions should mention money or cost levels
        budget_indicators = [
            "$",
            "€",
            "£",
            "budget",
            "luxury",
            "mid-range",
            "cheap",
            "affordable",
            "expensive",
            "per day",
            "per night",
            "total",
        ]
        if any(ind in lower for ind in budget_indicators):
            return 1.0
        # Check for numeric patterns (budget amounts)
        if any(char.isdigit() for char in suggestion):
            return 0.7
        return 0.2

    elif question_target == "activities":
        # Activity suggestions should mention activity types
        activity_indicators = [
            "sightseeing",
            "hiking",
            "diving",
            "snorkeling",
            "beach",
            "museum",
            "tour",
            "food",
            "wine",
            "spa",
            "adventure",
            "shopping",
            "nightlife",
            "culture",
            "art",
            "history",
            "sports",
            "yoga",
            "safari",
            "cruise",
        ]
        if any(ind in lower for ind in activity_indicators):
            return 1.0
        return 0.5  # Could be an activity

    elif question_target == "general":
        # General questions - accept most suggestions
        return 0.7

    # Unknown question_target - accept with low confidence
    return 0.5


def _generate_contextual_suggestions(
    state: "GraphState",
    question_target: Optional[str] = None,
) -> List[str]:
    """Generate high-quality contextual suggestions based on question_target.

    Args:
        state: Current graph state
        question_target: What field the assistant is asking about

    Returns 2-3 actionable suggestions in user voice.
    """
    import random

    ti = state.trip_inputs

    # If we have a question_target, generate suggestions for that field
    if question_target:
        if question_target == "origin":
            origins = random.sample(_UNIVERSAL_ORIGIN_CITIES, 3)
            return [f"From {city}" for city in origins]

        elif question_target == "destinations":
            # First check strategy_topic for topic-aware fallback
            if state.strategy_topic and state.strategy_topic in _STRATEGY_DESTINATION_MAP:
                dest_list = _STRATEGY_DESTINATION_MAP[state.strategy_topic]
                return random.sample(dest_list, min(3, len(dest_list)))

            # Check user intent for context-aware suggestions
            user_intent = state.metadata.get("user_intent", "")
            last_user_msg = ""
            for msg in reversed(state.chat_history):
                if msg.get("role") == "user":
                    last_user_msg = msg.get("content", "").lower()
                    break

            # Adventure/hiking
            if user_intent == "adventurous" or any(
                word in last_user_msg
                for word in ["hike", "hiking", "mountain", "adventure", "trek"]
            ):
                return random.sample(_ADVENTURE_DESTINATIONS, min(3, len(_ADVENTURE_DESTINATIONS)))
            # Beach-related
            elif any(
                word in last_user_msg
                for word in ["beach", "ocean", "sea", "tropical", "island", "relax"]
            ):
                return random.sample(_BEACH_DESTINATIONS, min(3, len(_BEACH_DESTINATIONS)))
            # City/culture
            elif any(
                word in last_user_msg for word in ["city", "culture", "museum", "history", "art"]
            ):
                return random.sample(_CITY_DESTINATIONS, min(3, len(_CITY_DESTINATIONS)))
            # Food/culinary
            elif any(
                word in last_user_msg for word in ["food", "culinary", "wine", "gastronomy", "eat"]
            ):
                return random.sample(_FOOD_DESTINATIONS, min(3, len(_FOOD_DESTINATIONS)))
            # Skiing/winter
            elif any(word in last_user_msg for word in ["ski", "snow", "winter", "slopes"]):
                return random.sample(_SKIING_DESTINATIONS, min(3, len(_SKIING_DESTINATIONS)))
            # Generic popular destinations
            else:
                return random.sample(_CITY_DESTINATIONS, min(3, len(_CITY_DESTINATIONS)))

        elif question_target in ("start_date", "end_date", "dates"):
            # Generate specific bookable dates
            from datetime import datetime, timedelta

            today = datetime.now()
            two_weeks = today + timedelta(days=14)
            one_month = today + timedelta(days=30)
            two_months = today + timedelta(days=60)
            return [
                two_weeks.strftime("%B %d, %Y"),
                one_month.strftime("%B %d, %Y"),
                two_months.strftime("%B %d, %Y"),
            ]

        elif question_target in ("adults", "travelers"):
            return ["Just me", "2 adults", "Family of 4"]

        elif question_target == "budget":
            return ["Around $2000", "Mid-range budget", "Luxury trip"]

        elif question_target == "activities":
            return ["Sightseeing and culture", "Beach and relaxation", "Adventure activities"]

        elif question_target == "general":
            # Generic helpful suggestions based on what's missing
            if not ti.destinations:
                return random.sample(_CITY_DESTINATIONS, min(3, len(_CITY_DESTINATIONS)))
            elif not ti.origin:
                origins = random.sample(_UNIVERSAL_ORIGIN_CITIES, 3)
                return [f"From {city}" for city in origins]
            elif not ti.start_date:
                from datetime import datetime, timedelta

                today = datetime.now()
                two_weeks = today + timedelta(days=14)
                one_month = today + timedelta(days=30)
                return [
                    two_weeks.strftime("%B %d, %Y"),
                    one_month.strftime("%B %d, %Y"),
                ]
            else:
                return ["Looks good, generate my plan", "Add more details", "Change dates"]

    # Fallback: No question_target - use legacy priority-based logic
    # but return empty to avoid mismatched suggestions
    return []


def _get_suggestions_with_fallback(
    raw_suggestions: List[Any],
    state: "GraphState",
    question_target: Optional[str] = None,
) -> List[str]:
    """Filter LLM suggestions by relevance to question_target.

    Args:
        raw_suggestions: Raw suggestions from LLM
        state: Current graph state
        question_target: What field the assistant is asking about

    Returns:
        List of relevant suggestions (may be empty if none are relevant)
    """
    filtered = _filter_suggested_responses(raw_suggestions)

    if not filtered:
        # No LLM suggestions - try contextual generation
        if question_target:
            contextual = _generate_contextual_suggestions(state, question_target)
            return contextual[:3]
        # No question_target - return empty rather than bad suggestions
        return []

    # Score each suggestion for relevance
    user_intent = state.metadata.get("user_intent_hint")
    scored_suggestions = []
    for suggestion in filtered:
        score = _score_suggestion_relevance(suggestion, question_target, user_intent)
        scored_suggestions.append((suggestion, score))
        if _DEBUG_LOG:
            _debug(f"Suggestion score: '{suggestion}' -> {score:.2f} (target={question_target})")

    # Filter by threshold
    passing = [s for s, score in scored_suggestions if score >= _SUGGESTION_RELEVANCE_THRESHOLD]

    # If not enough pass, suppress entirely (better no suggestions than bad ones)
    if len(passing) < _MIN_SUGGESTIONS_TO_SHOW:
        _debug(
            f"Suppressing suggestions: only {len(passing)} passed threshold "
            f"(need {_MIN_SUGGESTIONS_TO_SHOW})"
        )
        # Try contextual fallback
        if question_target:
            contextual = _generate_contextual_suggestions(state, question_target)
            if len(contextual) >= _MIN_SUGGESTIONS_TO_SHOW:
                return contextual[:3]
        return []

    return passing[:3]


# -----------------------
# Confidence Scoring Types
# -----------------------
class EntityConfidence(BaseModel):
    """Confidence information for a single extracted entity."""

    value: str  # The extracted value (e.g., "Paris")
    confidence: float = Field(ge=0.0, le=1.0)  # 0.0 to 1.0
    extraction_method: str = "unknown"  # "regex", "spacy", "llm", "hybrid"
    needs_confirmation: bool = False  # Whether to ask user to confirm
    fuzzy_suggestion: Optional[str] = None  # Suggested correction if typo detected
    ambiguity_type: Optional[str] = None  # e.g., "country/person_name"


class ExtractionConfidence(BaseModel):
    """Overall confidence scoring for extracted data."""

    overall: float = Field(default=0.5, ge=0.0, le=1.0)
    level: str = "medium"  # "high", "medium", "low"

    # Per-field confidence
    destinations: List[EntityConfidence] = Field(default_factory=list)
    origin: Optional[EntityConfidence] = None
    dates: Optional[float] = None

    # Metadata
    extraction_method: str = "unknown"  # Primary method used
    detected_language: Optional[str] = None
    language_confidence: Optional[float] = None
    is_english: bool = True

    # Reasons for low confidence
    low_confidence_reasons: List[str] = Field(default_factory=list)

    # Fuzzy match suggestions for typos
    typo_suggestions: Dict[str, str] = Field(default_factory=dict)  # original -> suggested


# Confidence thresholds
CONFIDENCE_THRESHOLD_HIGH = 0.80  # Skip to router, no confirmation needed
CONFIDENCE_THRESHOLD_MEDIUM = 0.50  # Proceed but may need confirmation
# Below 0.50 = Low confidence, force LLM extraction


# -----------------------
# Models & schema
# -----------------------
class TripInputs(BaseModel):
    destinations: List[str] = []
    origin: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    requires_assistance: Optional[bool] = None
    budget: Optional[float] = None
    currency: Optional[str] = None
    multi_city_intent: Optional[Literal["multi_city", "separate"]] = None
    booking_types: Dict[str, bool] = Field(default_factory=dict)
    flight_settings: Dict[str, Any] = Field(default_factory=dict)
    hotel_settings: Dict[str, Any] = Field(default_factory=dict)
    activity_settings: Dict[str, Any] = Field(default_factory=lambda: {"categories": []})
    transport_settings: Dict[str, Any] = Field(default_factory=dict)
    # Strategy-specific persisted preferences (per topic)
    strategy_settings: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("budget", mode="before")
    @classmethod
    def parse_budget_string(cls, v):
        """Parse budget from string with currency symbol if needed."""
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            # Remove currency symbols and commas, extract number
            import re

            cleaned = re.sub(r"[^\d.]", "", v)
            if cleaned:
                try:
                    return float(cleaned)
                except ValueError:
                    return None
        return None


# Valid values for question_target field
QUESTION_TARGET_VALUES = frozenset(
    {"destinations", "origin", "dates", "travelers", "budget", "activities", "general", None}
)


class GraphState(BaseModel):
    user_text: str
    trip_inputs: TripInputs = Field(default_factory=TripInputs)
    parsed_inputs: Dict[str, Any] = Field(default_factory=dict)
    ready_to_generate: bool = False
    branches: List[Dict[str, Any]] = Field(default_factory=list)
    suggested_responses: List[str] = Field(default_factory=list)
    intent: Optional[str] = (
        None  # required_fields|flights|hotels|transport|activities|correction_needed|strategy
    )
    strategy_topic: Optional[str] = None  # boating|hiking|diving|...
    active_category: Optional[str] = None
    last_summary: Optional[str] = None
    errors: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    flags: Dict[str, Any] = Field(default_factory=dict)
    # Chat history for LLM context (list of {role, content} dicts) - matches plan.py
    chat_history: List[Dict[str, str]] = Field(default_factory=list)
    # What field the assistant's question is asking about (for suggestion relevance)
    question_target: Optional[str] = (
        None  # destinations|origin|dates|travelers|budget|activities|general
    )


TRIP_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "destinations": {"type": "array", "items": {"type": "string"}},
        "origin": {"type": ["string", "null"]},
        "start_date": {"type": ["string", "null"]},
        "end_date": {"type": ["string", "null"]},
        "adults": {"type": ["integer", "null"], "minimum": 1},
        "children": {"type": ["integer", "null"], "minimum": 0},
        "requires_assistance": {"type": ["boolean", "null"]},
        "budget": {"type": ["number", "null"]},
        "currency": {"type": ["string", "null"]},
    },
    "additionalProperties": True,
}
TRIP_VALIDATOR = Draft7Validator(TRIP_JSON_SCHEMA)

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PROMPTS_DIR = Path(__file__).parent / "prompts"
INVALID_JSON_HINT = (
    "\n\nIMPORTANT: Your previous response was not valid JSON. "
    "Please respond with ONLY valid JSON."
)

# -----------------------
# Strategy registry (plug-in)
# -----------------------
STRATEGY_REGISTRY: Dict[str, str] = {}  # topic -> prompt filename (without .txt)


def register_strategy(topic: str, prompt_name: str):
    STRATEGY_REGISTRY[topic] = prompt_name


# Example registrations (create corresponding prompts/*.txt files)
register_strategy("boating", "strategy_boating")
register_strategy("hiking", "strategy_hiking")
register_strategy("diving", "strategy_diving")
register_strategy("skiing", "strategy_skiing")
register_strategy("cycling", "strategy_cycling")


# -----------------------
# Prompt & LLM helpers
# -----------------------

# Jinja2 environment for prompt templating with {% include %} support
_JINJA_ENV = Environment(
    loader=FileSystemLoader(PROMPTS_DIR),
    autoescape=False,  # Prompts are plain text, not HTML
    keep_trailing_newline=True,
)


@lru_cache(maxsize=32)
def _load_prompt_cached(name: str) -> str:
    """Internal cached prompt loader using Jinja2 for {% include %} support."""
    template = _JINJA_ENV.get_template(f"{name}.txt")
    return template.render()


# Track which prompts have been loaded (for cache hit logging)
_PROMPTS_LOADED: set[str] = set()


def load_prompt(name: str) -> str:
    """Load prompt template from file with LRU caching and debug logging.

    Supports Jinja2 {% include %} directives for shared blocks.
    Example: {% include "_never_invent.txt" %}
    """
    result = _load_prompt_cached(name)
    if name in _PROMPTS_LOADED:
        _debug_cache_hit("load_prompt", name, value_preview=result)
    else:
        _PROMPTS_LOADED.add(name)
    return result


def clear_prompt_cache() -> None:
    """Clear the prompt cache. Useful for development/hot-reloading."""
    _load_prompt_cached.cache_clear()
    _PROMPTS_LOADED.clear()
    _JINJA_ENV.cache.clear() if hasattr(_JINJA_ENV, "cache") and _JINJA_ENV.cache else None


# Model size to actual model name mapping
_MODEL_MAP = {
    "small": os.getenv("OPENAI_SMALL_MODEL", "gpt-4o-mini"),
    "medium": os.getenv("OPENAI_MEDIUM_MODEL", "gpt-4o-mini"),
    "large": os.getenv("OPENAI_PLAN_MODEL", "gpt-4o"),
}


async def call_llm(
    model: str,
    prompt: str,
    max_tokens: int = 512,
    temperature: float = 0.2,
    history: Optional[List[Dict[str, str]]] = None,
    user_message: Optional[str] = None,
    top_p: Optional[float] = None,
    max_retries: int = _PLAN_MAX_RETRIES,
) -> str:
    """
    Call the LLM provider using AsyncOpenAI. Returns a string (JSON text).

    Uses proper message structure with system prompt + history + user message,
    matching plan.py's approach for better context handling.
    Includes exponential backoff retry for 429/5xx errors (matching plan.py).

    Args:
        model: Model size identifier ("small", "medium", "large").
        prompt: The system prompt to send.
        max_tokens: Maximum tokens in response.
        temperature: Sampling temperature.
        history: Optional list of {role, content} dicts for conversation history.
        user_message: Optional current user message (appended after history).
        top_p: Optional nucleus sampling threshold (used for GPT-4 models).
        max_retries: Maximum retry attempts for transient errors.

    Returns:
        str: LLM response text.
    """
    from app.config import get_async_openai_client

    client = get_async_openai_client()
    if client is None:
        raise RuntimeError("OpenAI client is not configured")

    model_name = _MODEL_MAP.get(model, model)

    # Build messages array - same structure as plan.py
    messages: List[Dict[str, str]] = [{"role": "system", "content": prompt}]

    # Add history as separate messages (not in prompt text)
    if history:
        for msg in history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

    # Add current user message
    if user_message:
        messages.append({"role": "user", "content": user_message})

    # Build params matching plan.py's model-specific logic
    params: Dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }

    # Optional seed for reproducibility
    seed_env = os.getenv("OPENAI_PLAN_SEED")
    if seed_env:
        try:
            params["seed"] = int(seed_env)
        except ValueError:
            pass

    # GPT-4 models: use max_tokens, temperature, top_p
    # Other models: use max_completion_tokens
    if "gpt-4" in model_name.lower():
        params["max_tokens"] = max_tokens
        params["temperature"] = temperature
        if top_p is not None:
            params["top_p"] = top_p
    else:
        params["max_completion_tokens"] = max_tokens

    # Retry logic with exponential backoff for 429/5xx errors (matching plan.py)
    backoff = 0.5
    last_error: Optional[Exception] = None

    for attempt in range(max(1, max_retries)):
        try:
            response = await client.chat.completions.create(**params)
            content = response.choices[0].message.content or ""
            return content
        except Exception as exc:
            last_error = exc
            status_code = getattr(exc, "status_code", None) or getattr(exc, "status", None)
            # Retry on rate limit (429) or server errors (5xx)
            if attempt < max_retries - 1 and (
                status_code == 429 or (isinstance(status_code, int) and status_code >= 500)
            ):
                _debug_error(
                    f"LLM call failed (attempt {attempt + 1}), retrying...", error=str(exc)
                )
                await asyncio.sleep(backoff)
                backoff *= 2
                continue
            raise

    raise last_error or RuntimeError("LLM call failed after retries")


async def call_llm_with_timeout(
    model: str,
    prompt: str,
    timeout_seconds: float,
    max_tokens: int = 512,
    temperature: float = 0.2,
    history: Optional[List[Dict[str, str]]] = None,
    user_message: Optional[str] = None,
    top_p: Optional[float] = None,
    max_retries: int = _PLAN_MAX_RETRIES,
) -> str:
    """
    Call LLM with a timeout using asyncio.wait_for. Raises TimeoutError if the call takes too long.

    Args:
        model: Model identifier.
        prompt: The system prompt to send.
        timeout_seconds: Maximum time to wait for response.
        max_tokens: Maximum tokens in response.
        temperature: Sampling temperature.
        history: Optional list of {role, content} dicts for conversation history.
        user_message: Optional current user message (appended after history).
        top_p: Optional nucleus sampling threshold.
        max_retries: Maximum retry attempts for transient errors.

    Returns:
        str: LLM response text.

    Raises:
        TimeoutError: If the call exceeds timeout_seconds.
        Exception: Any exception from the underlying LLM call.
    """
    try:
        return await asyncio.wait_for(
            call_llm(
                model, prompt, max_tokens, temperature, history, user_message, top_p, max_retries
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        raise TimeoutError(f"LLM call timed out after {timeout_seconds}s") from None


# =============================================================================
# STREAMING LLM SUPPORT
# =============================================================================
# Simulated streaming parameters (hybrid timing for natural LLM-like flow)
# Fast start, gradual deceleration mimics real LLM token generation patterns
_STREAM_BASE_DELAY_MS = 8  # Starting delay (fast burst)
_STREAM_MAX_DELAY_MS = 18  # Maximum delay (deceleration cap)
_STREAM_ACCEL_FACTOR = 0.015  # How quickly delay increases per character
_STREAM_JITTER_MS = 4  # Random variance for organic feel


async def call_llm_streaming(
    model: str,
    prompt: str,
    max_tokens: int = 512,
    temperature: float = 0.2,
    history: Optional[List[Dict[str, str]]] = None,
    user_message: Optional[str] = None,
    top_p: Optional[float] = None,
):
    """
    Call the LLM with streaming enabled. Yields tokens as they arrive.

    This is used for response_polish and other text-only outputs where
    we want to stream tokens directly to the frontend via SSE.

    Args:
        model: Model size identifier ("small", "medium", "large").
        prompt: The system prompt to send.
        max_tokens: Maximum tokens in response.
        temperature: Sampling temperature.
        history: Optional list of {role, content} dicts for conversation history.
        user_message: Optional current user message (appended after history).
        top_p: Optional nucleus sampling threshold.

    Yields:
        str: Token chunks as they arrive from the LLM.
    """

    from app.config import get_async_openai_client

    client = get_async_openai_client()
    if client is None:
        raise RuntimeError("OpenAI client is not configured")

    model_name = _MODEL_MAP.get(model, model)

    # Build messages array - same structure as call_llm
    messages: List[Dict[str, str]] = [{"role": "system", "content": prompt}]

    if history:
        for msg in history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

    if user_message:
        messages.append({"role": "user", "content": user_message})

    # Build params - note: no response_format for streaming plain text
    params: Dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "stream": True,
    }

    # Optional seed for reproducibility
    seed_env = os.getenv("OPENAI_PLAN_SEED")
    if seed_env:
        try:
            params["seed"] = int(seed_env)
        except ValueError:
            pass

    # GPT-4 models: use max_tokens, temperature, top_p
    if "gpt-4" in model_name.lower():
        params["max_tokens"] = max_tokens
        params["temperature"] = temperature
        if top_p is not None:
            params["top_p"] = top_p
    else:
        params["max_completion_tokens"] = max_tokens

    async for chunk in await client.chat.completions.create(**params):
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


async def simulate_streaming(text: str):
    """
    Simulate streaming for code-generated messages with hybrid timing.

    Uses a fast-start, gradual-deceleration pattern that mimics real LLM
    token generation. Includes slight random jitter for organic feel.

    Timing pattern:
    - First ~50 chars: ~8-12ms/char (fast burst, ~80-125 chars/sec)
    - Mid section: gradual slowdown to ~15-18ms/char
    - Random jitter ±4ms prevents robotic feel

    Args:
        text: The complete text to simulate streaming for.

    Yields:
        str: Single characters with natural variable delay.
    """
    import random

    total_chars = len(text)
    for i, char in enumerate(text):
        # Progress through text (0.0 to 1.0)
        progress = i / max(total_chars, 1)

        # Base delay increases with progress (fast start, slower end)
        base_delay = _STREAM_BASE_DELAY_MS + (
            (_STREAM_MAX_DELAY_MS - _STREAM_BASE_DELAY_MS) * progress * _STREAM_ACCEL_FACTOR * 100
        )
        base_delay = min(base_delay, _STREAM_MAX_DELAY_MS)

        # Add jitter for organic feel
        jitter = random.uniform(-_STREAM_JITTER_MS, _STREAM_JITTER_MS)
        delay_ms = max(4, base_delay + jitter)  # Floor at 4ms

        yield char
        await asyncio.sleep(delay_ms / 1000.0)


def _truncate_to_balanced_json(raw: str) -> Optional[str]:
    """
    Extract a valid JSON object from a potentially truncated or malformed string.

    LLMs sometimes return incomplete JSON or include extra text before/after the JSON.
    This function finds the first complete, balanced JSON object in the string.
    """
    start_idx = None
    brace_count = 0
    in_string = False
    escape = False
    last_valid_idx = -1

    for idx, ch in enumerate(raw):
        if start_idx is None:
            if ch == "{":
                start_idx = idx
                brace_count = 1
            continue

        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            brace_count += 1
        elif ch == "}":
            brace_count -= 1
            if brace_count == 0:
                last_valid_idx = idx
                break

    if start_idx is not None and last_valid_idx >= start_idx:
        return raw[start_idx : last_valid_idx + 1]
    return None


def jloads_safe(s: str) -> Dict[str, Any]:
    """
    Parse JSON with multiple fallback strategies for malformed input.

    Tries progressively more lenient parsing approaches:
    1. Standard json.loads() - works for well-formed JSON
    2. Non-strict mode - allows some escape sequence issues
    3. Truncation recovery - extracts balanced JSON from garbage
    4. Last resort: find { and } brackets

    Returns empty dict on failure (matches plan.py's _tolerant_json_loads behavior).
    """
    if not s:
        return {}

    # Try standard parsing first
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    # Try non-strict mode (allows some escape sequence issues)
    try:
        return json.loads(s, strict=False)
    except Exception:
        pass

    # Try extracting balanced JSON from garbage
    trimmed = _truncate_to_balanced_json(s)
    if trimmed:
        try:
            return json.loads(trimmed, strict=False)
        except json.JSONDecodeError:
            pass

    # Last resort: find { and } brackets
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(s[start : end + 1], strict=False)
        except json.JSONDecodeError:
            pass

    # Return empty dict on failure (matching plan.py's _tolerant_json_loads)
    _debug_error("JSON parse failed", raw=s[:100] if len(s) > 100 else s)
    return {}


def ti_short(ti: TripInputs) -> Dict[str, Any]:
    return ti.model_dump(exclude_none=True)


def _record_llm_failure(state: GraphState, reason: str) -> GraphState:
    """Record an LLM failure and provide a conversational fallback message."""
    failures = state.metadata.get("validator_failures", 0) + 1
    state.metadata["validator_failures"] = failures
    state.errors.append(reason)

    # Always provide a user-facing message - be conversational
    # Use the default follow-up question based on missing fields, adapted to user intent/tone
    trip_inputs_dict = state.trip_inputs.model_dump(exclude_none=True)
    missing = _compute_missing_fields(trip_inputs_dict)
    user_intent = state.metadata.get("user_intent", "detailed_planner")
    user_tone = state.metadata.get("user_tone", "neutral")
    fallback_msg = _default_follow_up_question(missing, user_intent, user_tone, trip_inputs_dict)
    if fallback_msg:
        state.last_summary = fallback_msg
    else:
        state.last_summary = "Where are you looking to travel?"

    state.ready_to_generate = False
    return state


# -----------------------
# Cheap extractor (code) - enhanced with patterns from plan.py
# -----------------------
async def extractor(state: GraphState) -> GraphState:
    """
    Extract structured data from user text using LLM.

    All trip input extraction (destinations, origin, dates, travelers, budget,
    activities, settings) is performed by the LLM for robust natural language
    understanding.

    SHORT-CIRCUITS (bypasses LLM entirely via short_circuit_responder):
    - Greetings: "hi", "hello", "hey" -> random greeting + destination question
    - Acknowledgments: "ok", "thanks", "got it" -> continue flow
    - Confirmations: "yes"/"no" with pending_action -> execute or clear action
    - Off-topic: weather, math, general knowledge -> redirect to travel
    """
    _debug_node_entry("extractor", state)

    text = state.user_text
    parsed: Dict[str, Any] = {}

    # Check for generate plan trigger
    if _is_generate_plan_trigger(text):
        state.flags["generate_requested"] = True
        state.flags["generate_plan"] = True
        _debug("Generate plan trigger detected")
        state.parsed_inputs = parsed
        _debug_node_exit("extractor", state)
        return state

    # =========================================================================
    # SHORT-CIRCUIT DETECTION
    # Keep lightweight short-circuits for greetings, acknowledgments, etc.
    # These save LLM tokens for trivial inputs.
    # =========================================================================
    short_circuit = _detect_short_circuit(text, state)
    if short_circuit:
        sc_type = short_circuit["type"]
        _debug(f"Short-circuit detected: {sc_type}", input=text[:30] if len(text) > 30 else text)

        state.flags["short_circuit"] = sc_type
        state.flags["short_circuit_response"] = short_circuit.get("response")
        state.flags["short_circuit_action"] = short_circuit.get("action")

        # If short-circuit extracted parsed data, merge it
        sc_parsed = short_circuit.get("parsed")
        if sc_parsed:
            parsed.update(sc_parsed)
            _debug("Short-circuit parsed data", parsed=sc_parsed)

        # For confirmations that trigger actions, handle them
        if short_circuit.get("action") == "generate_plan":
            state.flags["generate_requested"] = True
            state.flags["generate_plan"] = True
            _debug("Short-circuit triggered generate_plan")
        elif short_circuit.get("action") == "apply_typo_corrections":
            # Apply the stored typo corrections to trip_inputs
            typo_corrections = (sc_parsed or {}).get("typo_corrections", {})
            if typo_corrections:
                _apply_typo_corrections(state, typo_corrections)
            state.metadata.pop("pending_action", None)
            state.metadata.pop("pending_typo_corrections", None)
            _debug("Short-circuit applied typo corrections", corrections=typo_corrections)
        elif short_circuit.get("action") == "clear_pending":
            state.metadata.pop("pending_action", None)
            state.metadata.pop("pending_typo_corrections", None)
            _debug("Short-circuit cleared pending_action")

        state.parsed_inputs = parsed
        _debug_node_exit("extractor", state)
        return state

    # =========================================================================
    # LLM-BASED EXTRACTION
    # All trip input extraction is performed by the LLM for robust NLU.
    # =========================================================================
    llm_config = _get_node_llm_config("extractor")
    today_iso = state.metadata.get("today_iso") or _today_iso()

    try:
        prompt = load_prompt("extractor")
        tpl = (
            prompt.replace("{today}", today_iso)
            .replace("{trip_inputs}", json.dumps(ti_short(state.trip_inputs)))
            .replace("{user_text}", text)
        )

        tokens = _estimate_prompt_tokens(tpl, state.parsed_inputs)
        _record_node_tokens(state, "extractor", tokens, model=llm_config["model_hint"])

        import time as _time

        _llm_start = _time.perf_counter()
        out = await call_llm_with_timeout(
            model=llm_config["model_hint"],
            prompt=tpl,
            timeout_seconds=settings.llm_timeout_extractor,
            max_tokens=llm_config["max_tokens"],
            temperature=llm_config["temperature"],
        )
        _record_llm_time(state, (_time.perf_counter() - _llm_start) * 1000)
        _increment_llm_calls(state)
        extracted = jloads_safe(out)

        # Map LLM output to parsed_inputs format
        if extracted.get("destinations_delta"):
            parsed["destinations_delta"] = extracted["destinations_delta"]
        if extracted.get("origin_delta"):
            parsed["origin_delta"] = extracted["origin_delta"]
        if extracted.get("start_date_hint"):
            parsed["start_date_hint"] = extracted["start_date_hint"]
        if extracted.get("end_date_hint"):
            parsed["end_date_hint"] = extracted["end_date_hint"]
        if extracted.get("duration_days"):
            parsed["duration_days"] = extracted["duration_days"]
        if extracted.get("adults_delta") is not None:
            parsed["adults_delta"] = extracted["adults_delta"]
        if extracted.get("children_delta") is not None:
            parsed["children_delta"] = extracted["children_delta"]
        if extracted.get("requires_assistance_delta") is not None:
            parsed["requires_assistance_delta"] = extracted["requires_assistance_delta"]
        if extracted.get("budget_delta"):
            parsed["budget_delta"] = extracted["budget_delta"]
        if extracted.get("multi_city_intent_delta"):
            parsed["multi_city_intent_delta"] = extracted["multi_city_intent_delta"]
        if extracted.get("category_activation"):
            parsed["category_activation"] = extracted["category_activation"]
        if extracted.get("flight_settings_delta"):
            parsed["flight_settings_delta"] = extracted["flight_settings_delta"]
        if extracted.get("hotel_settings_delta"):
            parsed["hotel_settings_delta"] = extracted["hotel_settings_delta"]
        if extracted.get("transport_settings_delta"):
            parsed["transport_settings_delta"] = extracted["transport_settings_delta"]
        if extracted.get("activity_categories_delta"):
            # Map to inferred_activity_categories for normalize_inputs
            parsed["inferred_activity_categories"] = extracted["activity_categories_delta"]
        if extracted.get("strategy_hint"):
            parsed["strategy_hint"] = extracted["strategy_hint"]

        # Store LLM-reported confidence in metadata
        confidence_score = extracted.get("confidence", 0.8)
        confidence_reasons = extracted.get("confidence_reasons", [])

        # Determine confidence level based on score
        if confidence_score >= 0.8:
            confidence_level = "high"
        elif confidence_score >= 0.5:
            confidence_level = "medium"
        else:
            confidence_level = "low"

        state.metadata["extraction_confidence"] = {
            "overall": confidence_score,
            "level": confidence_level,
            "method": "llm",
            "grammar_matched": False,  # Not applicable for LLM extraction
            "is_english": True,  # LLM handles multilingual
            "detected_language": None,
            "low_confidence_reasons": confidence_reasons,
            "typo_suggestions": {},
        }

        _debug(
            "Extraction confidence calculated",
            overall=f"{confidence_score:.2f}",
            level=confidence_level,
            method="llm",
            grammar_matched=False,
            reasons=confidence_reasons[:3] if confidence_reasons else None,
        )

    except TimeoutError:
        _debug("Extractor LLM timeout, using empty parsed_inputs")
        state.metadata["extraction_confidence"] = {
            "overall": 0.0,
            "level": "low",
            "method": "llm_timeout",
            "grammar_matched": False,
            "is_english": True,
            "detected_language": None,
            "low_confidence_reasons": ["llm_timeout"],
            "typo_suggestions": {},
        }
    except Exception as e:
        _debug_error("Extractor LLM error", error=str(e))
        state.metadata["extraction_confidence"] = {
            "overall": 0.0,
            "level": "low",
            "method": "llm_error",
            "grammar_matched": False,
            "is_english": True,
            "detected_language": None,
            "low_confidence_reasons": ["llm_error"],
            "typo_suggestions": {},
        }

    state.parsed_inputs = parsed
    _debug_node_exit("extractor", state)
    return state


# -----------------------
# Normalize inputs node (new)
# -----------------------
def normalize_inputs(state: GraphState) -> GraphState:
    """
    Apply normalization to extracted inputs and merge into trip_inputs.

    This node runs after extractor and before router. It is the SINGLE location
    where all normalization occurs in the graph. Uses TripInputNormalizer for
    unified normalization logic.

    NOTE: All normalization happens here. Specialists and validate_and_merge
    should NOT duplicate normalization logic.
    """
    _debug_node_entry("normalize_inputs", state)

    # Early exit for short-circuits with no parsed data (greetings, acknowledgments, off-topic)
    # These don't need any normalization work
    sc_type = state.flags.get("short_circuit")
    if sc_type and sc_type in (
        "greeting",
        "acknowledgment",
        "off_topic",
        "confirmation_yes",
        "confirmation_no",
    ):
        if not state.parsed_inputs:
            _debug(f"Skipping normalize_inputs for short-circuit: {sc_type}")
            _debug_node_exit("normalize_inputs", state)
            return state

    parsed = state.parsed_inputs or {}
    ti = state.trip_inputs  # Read-only reference for reading current values

    # =========================================================================
    # USE TripInputNormalizer FOR UNIFIED NORMALIZATION
    # =========================================================================
    # This is the SINGLE normalization pass. All field normalization, validation,
    # and error collection happens here via TripInputNormalizer.
    updates, norm_errors = _trip_normalizer.normalize_all(ti, parsed)

    # Handle partial date notifications (stored in updates by normalizer)
    partial_date_notifications = updates.pop("_partial_date_notifications", None)
    if partial_date_notifications:
        # Build human-readable notification messages
        notifications = []
        for notif in partial_date_notifications:
            if "start_date" in notif:
                start_iso = updates.get("start_date") or ti.start_date
                if start_iso:
                    dt = _parse_iso_date(start_iso)
                    if dt:
                        readable = dt.strftime("%B %d, %Y")
                        notifications.append(
                            f"I'll assume {readable} for the start date—"
                            "let me know if you meant a different day."
                        )
            elif "end_date" in notif:
                end_iso = updates.get("end_date") or ti.end_date
                if end_iso:
                    dt = _parse_iso_date(end_iso)
                    if dt:
                        readable = dt.strftime("%B %d, %Y")
                        notifications.append(
                            f"I'll assume {readable} for the end date—"
                            "let me know if you meant a different day."
                        )
        if notifications:
            state.metadata["partial_date_notifications"] = notifications
            _debug("Partial date defaults applied", notifications=notifications)

    # Store raw date hints for specialist nodes
    if "start_date_hint" in parsed:
        if "raw_date_hints" not in state.metadata:
            state.metadata["raw_date_hints"] = {}
        state.metadata["raw_date_hints"]["start_date"] = parsed["start_date_hint"]
    if "end_date_hint" in parsed:
        if "raw_date_hints" not in state.metadata:
            state.metadata["raw_date_hints"] = {}
        state.metadata["raw_date_hints"]["end_date"] = parsed["end_date_hint"]

    # Apply inferred activities from destination (multi-faceted extraction)
    # These are activities implied by the destination, e.g., "Patagonia" → hiking
    if "inferred_activity_categories" in parsed:
        inferred = parsed["inferred_activity_categories"]
        existing_settings = dict(ti.activity_settings) if ti.activity_settings else {}
        existing_cats = list(existing_settings.get("categories", []))

        for cat in inferred:
            # Normalize activity with emoji prefix
            normalized_cat = _normalize_activity_with_emoji(cat)
            if normalized_cat not in existing_cats:
                existing_cats.append(normalized_cat)

        # Deduplicate case-insensitively after merge
        existing_cats = _deduplicate_activities_case_insensitive(existing_cats)
        existing_settings["categories"] = existing_cats
        updates["activity_settings"] = existing_settings

        # Also enable activities booking type
        existing_booking = dict(updates.get("booking_types") or ti.booking_types or {})
        existing_booking["activities"] = True
        updates["booking_types"] = existing_booking

        _debug(
            "Applied inferred activities from destination",
            categories=existing_cats,
        )

    # Apply all updates via the helper (this does ownership checking and deep copy)
    if updates:
        _write_trip_inputs(state, "normalize_inputs", **updates)
        _debug(
            "normalize_inputs applied updates via _write_trip_inputs", fields=list(updates.keys())
        )

    # Add normalization errors to state errors
    if norm_errors:
        for err in norm_errors:
            state.errors.append(
                {
                    "field": err.field,
                    "message": err.message,
                    "severity": err.severity,
                }
            )
        _debug(f"Normalization produced {len(norm_errors)} errors/warnings")

    _debug_node_exit("normalize_inputs", state)
    return state


# -----------------------
# Router (small LLM) - no retry, uses timeout
# -----------------------
async def router(state: GraphState) -> GraphState:
    """
    Router node to determine intent. Uses timeout but NO retry (router should be fast and reliable).
    Also refines user intent classification for conversational style adaptation.
    """
    _debug_node_entry("router", state)

    # Get per-node LLM configuration
    llm_config = _get_node_llm_config("router")

    try:
        prompt = load_prompt("router")
        # Include user intent hint from extractor for router to refine
        user_intent_hint = state.metadata.get("user_intent_hint", "")
        tpl = (
            prompt.replace("{parsed_inputs}", json.dumps(state.parsed_inputs))
            .replace("{trip_inputs}", json.dumps(ti_short(state.trip_inputs)))
            .replace("{user_intent_hint}", user_intent_hint or "none")
        )

        tokens = _estimate_prompt_tokens(tpl, state.parsed_inputs)
        _record_node_tokens(state, "router", tokens, model=llm_config["model_hint"])

        import time as _time

        _llm_start = _time.perf_counter()
        out = await call_llm_with_timeout(
            model=llm_config["model_hint"],
            prompt=tpl,
            timeout_seconds=settings.llm_timeout_router,
            max_tokens=llm_config["max_tokens"],
            temperature=llm_config["temperature"],
        )
        _record_llm_time(state, (_time.perf_counter() - _llm_start) * 1000)
        _increment_llm_calls(state)
        j = jloads_safe(out)
        state.intent = j.get("intent") or "required_fields"
        topic = j.get("topic") or state.parsed_inputs.get("strategy_hint")
        state.strategy_topic = topic if state.intent == "strategy" else None
        state.metadata["router_notes"] = j.get("notes", "")
        state.metadata["router_confidence"] = j.get("confidence", 1.0)

        # Handle off-topic intent with friendly deflection
        if state.intent == "off_topic":
            state.last_summary = _random_module.choice(_OFF_TOPIC_DEFLECTIONS)
            state.metadata["last_question_field"] = "destinations"
            _debug("Off-topic detected, deflecting to travel", response=state.last_summary[:50])
            _debug_node_exit("router", state)
            return state

        # Capture refined user intent from router (if provided)
        router_user_intent = j.get("user_intent")
        if router_user_intent and router_user_intent in USER_INTENT_ARCHETYPES:
            # Router refined the intent - update if different from extractor hint
            current_intent = state.metadata.get("user_intent")
            if router_user_intent != current_intent:
                _debug(
                    "Router refined user intent",
                    from_intent=current_intent,
                    to_intent=router_user_intent,
                )
                state.metadata["user_intent"] = router_user_intent
                state.metadata["intent_turn_count"] = 1
                state.metadata["intent_confidence"] = 1.0

        _debug(
            "Router result",
            intent=state.intent,
            confidence=state.metadata.get("router_confidence"),
            topic=state.strategy_topic,
            user_intent=state.metadata.get("user_intent"),
        )

        prev_intent = state.metadata.get("last_intent")
        no_progress_turns = state.metadata.get("no_progress_turns", 0)
        if state.intent == "required_fields" and prev_intent == "required_fields":
            no_progress_turns += 1
        else:
            no_progress_turns = 0
        state.metadata["no_progress_turns"] = no_progress_turns
        state.metadata["last_intent"] = state.intent

        _debug_node_exit("router", state)
        return state
    except Exception as exc:
        # Router failure is not critical - default to required_fields for conversational flow
        _debug_error("Router failed, defaulting to required_fields", error=str(exc))
        state.intent = "required_fields"
        state.metadata["router_notes"] = f"Router error: {exc}"
        _debug_node_exit("router", state)
        return state


# -----------------------
# Specialists (shared handler)
# -----------------------


def _select_required_fields_prompt(state: GraphState) -> str:
    """
    Select the appropriate prompt for required_fields based on state.

    Returns either:
    - required_fields_confirm: when typos/ambiguities need user confirmation
    - required_fields: for all other cases (collecting missing fields or confirming ready state)
    """
    # Check for typos or ambiguous entities needing confirmation
    extraction_conf = state.metadata.get("extraction_confidence", {})
    typo_suggestions = extraction_conf.get("typo_suggestions", [])

    if typo_suggestions:
        # Use confirmation prompt for typo/ambiguity resolution
        return load_prompt("required_fields_confirm")

    # Check if budget needs clarification (qualitative value was dropped)
    prompt = load_prompt("required_fields")
    if state.metadata.get("budget_needs_clarification"):
        # Clear the flag and inject budget question
        state.metadata["budget_needs_clarification"] = False
        state.question_target = "budget"
        prompt += (
            "\n\nIMPORTANT: The user provided a qualitative budget description."
            " Ask them for an approximate budget in dollars/their currency."
        )

    return prompt


async def _specialist(name: str, state: GraphState, retry_on_json_error: bool = True) -> GraphState:
    """
    Shared handler for specialist nodes with JSON retry logic.

    Args:
        name: Prompt name to load (also used to look up per-node LLM config).
        state: Current graph state.
        retry_on_json_error: If True, attempt one repair retry on JSON parse failure.
    """
    _debug_node_entry(f"specialist:{name}", state)

    # Get per-node LLM configuration
    llm_config = _get_node_llm_config(name)

    # Get today's date for prompt injection
    today_iso = state.metadata.get("today_iso") or _today_iso()

    # Get extraction confidence for confirmation prompts
    extraction_conf = state.metadata.get("extraction_confidence", {})
    confidence_level = extraction_conf.get("level", "unknown")
    typo_suggestions = extraction_conf.get("typo_suggestions", [])

    # Build extraction sources summary from parsed_inputs
    parsed = state.parsed_inputs or {}
    extraction_sources = {
        "destinations": parsed.get("destinations_source"),
        "origin": parsed.get("origin_source"),
        "budget": parsed.get("budget_source"),
        "travelers": parsed.get("travelers_source"),
        "dates": parsed.get("dates_source"),
        "duration": parsed.get("duration_source"),
    }
    # Filter out None values for cleaner output
    extraction_sources = {k: v for k, v in extraction_sources.items() if v}

    # Preserve the current trip_inputs snapshot for fallback normalization
    ti = state.trip_inputs

    # Use split prompts for required_fields to reduce token usage
    if name == "required_fields":
        prompt = _select_required_fields_prompt(state)
    else:
        prompt = load_prompt(name)

    system_prompt = (
        prompt.replace("{trip_inputs}", json.dumps(ti_short(state.trip_inputs)))
        .replace("{parsed_inputs}", json.dumps(state.parsed_inputs))
        .replace("{today}", today_iso)
        .replace("{user_intent_hint}", state.metadata.get("user_intent", "detailed_planner"))
        .replace("{user_tone}", state.metadata.get("user_tone", "neutral"))
        .replace("{extraction_confidence}", confidence_level)
        .replace("{typo_suggestions}", json.dumps(typo_suggestions) if typo_suggestions else "none")
        .replace(
            "{extraction_sources}", json.dumps(extraction_sources) if extraction_sources else "{}"
        )
    )

    # Determine timeout based on model type
    timeout = settings.llm_timeout_specialist
    attempts = settings.llm_max_retries if retry_on_json_error else 1
    last_error = None

    tokens = _estimate_prompt_tokens(system_prompt, state.parsed_inputs)
    _record_node_tokens(state, f"specialist:{name}", tokens, model=llm_config["model_hint"])

    import time as _time

    for attempt in range(attempts):
        try:
            # Pass history as separate messages for better context
            _llm_start = _time.perf_counter()
            out = await call_llm_with_timeout(
                model=llm_config["model_hint"],
                prompt=system_prompt,
                timeout_seconds=timeout,
                max_tokens=llm_config["max_tokens"],
                temperature=llm_config["temperature"],
                history=state.chat_history,
                user_message=state.user_text,
                top_p=llm_config["top_p"],
            )
            _record_llm_time(state, (_time.perf_counter() - _llm_start) * 1000)
            _increment_llm_calls(state)
            j = jloads_safe(out)

            # Debug: log raw LLM response
            _debug(
                f"Specialist {name} LLM response",
                assistant_message=(
                    j.get("assistant_message", "<MISSING>")[:100]
                    if j.get("assistant_message")
                    else "<EMPTY>"
                ),
            )

            # Capture assistant_message early - even if field processing fails, we want this
            assistant_msg = j.get("assistant_message", "")
            if assistant_msg:
                state.last_summary = assistant_msg

            # Apply trip_inputs delta using centralized helper
            delta = j.get("trip_inputs", {}) or {}

            # Handle strategy_hint separately - it belongs in parsed_inputs, not trip_inputs
            # (LLM may return it in trip_inputs when confirming strategy intent)
            if "strategy_hint" in delta:
                strategy_hint = delta.pop("strategy_hint")
                if strategy_hint and isinstance(strategy_hint, str):
                    state.parsed_inputs["strategy_hint"] = strategy_hint
                    _debug(f"Captured strategy_hint from LLM: {strategy_hint}")

            # Domain specialists (flights, hotels, activities, transport) should not overwrite
            # core fields extracted by the extractor. Only required_fields and correction can
            # modify these fields (required_fields for collection, correction for fixing
            # infeasibility).
            _CORE_FIELDS = {
                "destinations",
                "origin",
                "start_date",
                "end_date",
                "adults",
                "children",
                "budget",
                "currency",
            }
            # required_fields and correction can modify core fields; domain specialists cannot
            if name in ("required_fields", "correction"):
                skip_fields = None  # Allow all field modifications
            else:
                skip_fields = _CORE_FIELDS  # Block core field modifications
            _apply_llm_delta(state, f"specialist:{name}", delta, skip_fields=skip_fields)

            # Validate the updated trip_inputs
            TRIP_VALIDATOR.validate(state.trip_inputs.model_dump())
            state.last_summary = j.get("assistant_message", "")

            # Parse question_target from LLM response for suggestion relevance
            raw_question_target = j.get("question_target")
            if raw_question_target and isinstance(raw_question_target, str):
                normalized_target = raw_question_target.lower().strip()
                if normalized_target in QUESTION_TARGET_VALUES:
                    state.question_target = normalized_target
                elif normalized_target == "null" or normalized_target == "none":
                    state.question_target = None
                else:
                    _debug(f"Unknown question_target from LLM: {raw_question_target}")
                    state.question_target = None
            else:
                state.question_target = None

            # Fallback: infer question_target from missing fields if LLM didn't provide one
            if state.question_target is None:
                inferred_target = _infer_question_target_from_missing(state)
                if inferred_target:
                    state.question_target = inferred_target
                    _debug(
                        "Inferred question_target from missing fields",
                        target=inferred_target,
                    )

            # Filter suggested responses with contextual fallback
            raw_suggestions = j.get("suggested_responses", []) or []
            state.suggested_responses = _get_suggestions_with_fallback(
                raw_suggestions, state, state.question_target
            )
            _debug_suggestions(state.suggested_responses, source=f"specialist:{name}")

            # Only set ready_to_generate if explicitly triggered
            state.ready_to_generate = bool(j.get("ready_to_generate", False)) and state.flags.get(
                "generate_requested", False
            )

            # Only emit branches if generate was explicitly requested
            if state.flags.get("generate_requested", False):
                raw_branches = j.get("branches", []) or []
                fallback = ti.model_dump(exclude_none=True)
                normalized_branches: List[Dict[str, Any]] = []
                for b in raw_branches:
                    normalized = _normalize_branch_spec(b, fallback)
                    if normalized:
                        normalized_branches.append(normalized)
                state.branches = normalized_branches

            state.metadata["model_used"] = llm_config["model_hint"]
            state.metadata["token_estimate"] = _count_tokens(out)

            _debug(
                f"Specialist {name} completed",
                ready=state.ready_to_generate,
                branches=len(state.branches),
            )
            _debug_node_exit(f"specialist:{name}", state)
            return state

        except json.JSONDecodeError as e:
            last_error = e
            _debug_error(f"Specialist {name} JSON error on attempt {attempt + 1}", error=str(e))
            if attempt < attempts - 1:
                # Add repair hint to prompt for retry
                system_prompt += INVALID_JSON_HINT
                continue
            break
        except TimeoutError as e:
            last_error = e
            _debug_error(f"Specialist {name} timeout on attempt {attempt + 1}")
            break
        except Exception as e:
            last_error = e
            _debug_error(f"Specialist {name} error on attempt {attempt + 1}", error=str(e))
            break

    reason = f"{name} node produced invalid output after {attempts} attempt(s): {last_error}"
    _debug_error(f"Specialist {name} failed", reason=reason)
    return _record_llm_failure(state, reason)


async def required_fields_node(state: GraphState) -> GraphState:
    return await _specialist("required_fields", state)


async def flights_node(state: GraphState) -> GraphState:
    state.active_category = "flights"
    return await _specialist("flights", state)


async def hotels_node(state: GraphState) -> GraphState:
    state.active_category = "hotels"
    return await _specialist("hotels", state)


async def transport_node(state: GraphState) -> GraphState:
    state.active_category = "transport"
    return await _specialist("transport", state)


async def activities_node(state: GraphState) -> GraphState:
    state.active_category = "activities"
    return await _specialist("activities", state)


async def correction_node(state: GraphState) -> GraphState:
    return await _specialist("correction", state)


# -----------------------
# Strategy node (loads module by topic from registry)
# -----------------------
def _is_strategy_enabled(topic: str) -> bool:
    """Check if a strategy is enabled via feature flags."""
    flag_map = {
        "boating": settings.enable_strategy_boating,
        "hiking": settings.enable_strategy_hiking,
        "diving": settings.enable_strategy_diving,
        "skiing": settings.enable_strategy_skiing,
        "cycling": settings.enable_strategy_cycling,
    }
    return flag_map.get(topic, True)  # Default to enabled for unknown topics


async def strategy_node(state: GraphState) -> GraphState:
    _debug_node_entry("strategy_node", state)

    topic = state.strategy_topic or "boating"
    _debug("Strategy topic", topic=topic)

    # Check feature flag - if disabled, fallback to activities-lite
    if not _is_strategy_enabled(topic):
        _debug(f"Strategy {topic} is disabled, falling back to activities")
        state.last_summary = (
            f"The {topic} planning module is currently unavailable. "
            "I can help with general activity planning instead."
        )
        state.active_category = "activities"
        return await _specialist("activities", state)

    prompt_name = STRATEGY_REGISTRY.get(topic)
    if not prompt_name:
        # Fallback: gentle notice; no state changes
        _debug(f"No prompt for strategy {topic}")
        state.last_summary = (
            f"I can draft a detailed {topic} plan soon. For now, which preferences matter most?"
        )
        state.suggested_responses = [
            "Beginner skill level",
            "Prefer skippered",
            "Max 4 hours daily",
        ]
        _debug_suggestions(state.suggested_responses, source="strategy_node:fallback")
        _debug_node_exit("strategy_node", state)
        return state

    # Get per-node LLM configuration for strategy
    llm_config = _get_node_llm_config("strategy")

    # Use timeout and retry logic
    timeout = settings.llm_timeout_specialist
    attempts = settings.llm_max_retries
    last_error = None

    prompt = load_prompt(prompt_name)
    system_prompt = (
        prompt.replace("{trip_inputs}", json.dumps(ti_short(state.trip_inputs)))
        .replace("{parsed_inputs}", json.dumps(state.parsed_inputs))
        .replace("{topic}", topic)
    )

    tokens = _estimate_prompt_tokens(system_prompt, state.parsed_inputs)
    _record_node_tokens(state, f"strategy:{topic}", tokens, model=llm_config["model_hint"])

    import time as _time

    for attempt in range(attempts):
        try:
            # Pass history as separate messages for better context
            _llm_start = _time.perf_counter()
            out = await call_llm_with_timeout(
                model=llm_config["model_hint"],
                prompt=system_prompt,
                timeout_seconds=timeout,
                max_tokens=llm_config["max_tokens"],
                temperature=llm_config["temperature"],
                history=state.chat_history,
                user_message=state.user_text,
                top_p=llm_config["top_p"],
            )
            _record_llm_time(state, (_time.perf_counter() - _llm_start) * 1000)
            _increment_llm_calls(state)
            j = jloads_safe(out)

            # Handle strategy_settings specially (keyed by topic)
            strategy_data = j.get("strategy_settings", {})
            if strategy_data:
                current_ss = (
                    dict(state.trip_inputs.strategy_settings)
                    if state.trip_inputs.strategy_settings
                    else {}
                )
                current_ss[topic] = strategy_data
                _write_trip_inputs(state, f"strategy:{topic}", strategy_settings=current_ss)

            # Apply remaining trip_inputs delta using centralized helper
            # Strategy nodes should NOT overwrite core fields - only activity_settings
            delta = j.get("trip_inputs", {}) or {}
            _STRATEGY_SKIP_FIELDS = {
                "strategy_settings",  # Handled specially above
                "destinations",
                "origin",
                "start_date",
                "end_date",
                "adults",
                "children",
                "budget",
                "currency",
            }
            _apply_llm_delta(state, f"strategy:{topic}", delta, skip_fields=_STRATEGY_SKIP_FIELDS)

            # Validate the updated trip_inputs
            TRIP_VALIDATOR.validate(state.trip_inputs.model_dump())
            state.last_summary = j.get("assistant_message", "")

            # Parse question_target from LLM response for suggestion relevance
            raw_question_target = j.get("question_target")
            if raw_question_target and isinstance(raw_question_target, str):
                normalized_target = raw_question_target.lower().strip()
                if normalized_target in QUESTION_TARGET_VALUES:
                    state.question_target = normalized_target
                elif normalized_target == "null" or normalized_target == "none":
                    state.question_target = None
                else:
                    state.question_target = None
            else:
                state.question_target = None

            # Fallback: infer question_target from missing fields if LLM didn't provide one
            if state.question_target is None:
                inferred_target = _infer_question_target_from_missing(state)
                if inferred_target:
                    state.question_target = inferred_target
                    _debug(
                        "Inferred question_target from missing fields",
                        target=inferred_target,
                    )

            # Filter suggested responses with relevance scoring
            raw_suggestions = j.get("suggested_responses", []) or []
            state.suggested_responses = _get_suggestions_with_fallback(
                raw_suggestions, state, state.question_target
            )
            _debug_suggestions(state.suggested_responses, source="strategy_node")

            # Only set ready_to_generate if explicitly triggered
            state.ready_to_generate = bool(j.get("ready_to_generate", False)) and state.flags.get(
                "generate_requested", False
            )

            # Only emit branches if generate was explicitly requested
            if state.flags.get("generate_requested", False):
                raw_branches = j.get("branches", []) or []
                fallback = state.trip_inputs.model_dump(exclude_none=True)
                normalized_branches: List[Dict[str, Any]] = []
                for b in raw_branches:
                    normalized = _normalize_branch_spec(b, fallback)
                    if normalized:
                        normalized_branches.append(normalized)
                state.branches = normalized_branches

            state.metadata["model_used"] = llm_config["model_hint"]
            state.metadata["token_estimate"] = _count_tokens(out)

            _debug_node_exit("strategy_node", state)
            return state

        except json.JSONDecodeError as e:
            last_error = e
            _debug_error(f"Strategy {topic} JSON error on attempt {attempt + 1}", error=str(e))
            if attempt < attempts - 1:
                system_prompt += INVALID_JSON_HINT
                continue
            break
        except Exception as e:
            last_error = e
            _debug_error(f"Strategy {topic} error on attempt {attempt + 1}", error=str(e))
            break

    reason = (
        f"strategy node for {topic} produced invalid output after {attempts} attempt(s): "
        f"{last_error}"
    )
    _debug_error(f"Strategy {topic} failed", reason=reason)
    return _record_llm_failure(state, reason)


# -----------------------
# Validation & summarization (enhanced with plan.py logic)
# -----------------------
def validate_and_merge(state: GraphState) -> GraphState:
    """
    Compute ready_to_generate state and enable booking types.

    NOTE: All normalization (dates, travelers, currency, destinations) now
    happens in normalize_inputs via TripInputNormalizer. This node only:
    1. Computes ready_to_generate based on required fields
    2. Calls _auto_enable_booking_types (single call location)
    3. Generates any final validation messages
    """
    _debug_node_entry("validate_and_merge", state)

    ti = state.trip_inputs  # Read-only reference

    # =========================================================================
    # AUTO-ENABLE BOOKING TYPES (single call location)
    # =========================================================================
    # This is the ONLY place where _auto_enable_booking_types is called.
    # It was previously called in _apply_llm_delta and normalize_inputs too.
    _auto_enable_booking_types(ti)

    # =========================================================================
    # COMPUTE READY STATE
    # =========================================================================
    # Only require: destinations, origin, start_date (matches plan.py)
    missing = _compute_missing_fields(ti.model_dump(exclude_none=True))

    # ready_to_generate: all required fields complete
    state.ready_to_generate = bool(
        not state.errors and not missing and ti.destinations and ti.origin and ti.start_date
    )

    _debug(
        "Validation complete",
        missing=missing,
        ready=state.ready_to_generate,
        errors_count=len(state.errors),
    )
    _debug_node_exit("validate_and_merge", state)
    return state


# -----------------------
# Response polish node (for natural conversational tone)
# -----------------------
# Minimum length threshold for polishing (chars)
_POLISH_MIN_LENGTH = 200

# Patterns that indicate content would benefit from polish formatting
_POLISH_LIST_PATTERNS = (
    "\n- ",  # Markdown bullet list
    "\n* ",  # Alternative bullet
    "\n1. ",  # Numbered list
    "\n2. ",  # Numbered list continuation
    "option",  # Multiple options being presented
    "could ",  # Suggesting alternatives
    "either ",  # Presenting choices
)


def _should_skip_polish(s: GraphState) -> tuple[bool, str]:
    """
    Determine if response polishing should be skipped.
    Returns (should_skip, reason).

    Polish is applied ONLY for:
    - Responses containing lists (bullet points, numbered items)
    - Longer responses (>200 chars) that would benefit from formatting

    This keeps polish targeted at content that needs structure,
    while avoiding latency for simple responses.
    """
    # Check feature flag
    if not settings.enable_response_polish:
        return True, "feature_disabled"

    # Short-circuited responses are already template-based and don't need polish
    if s.flags.get("short_circuit"):
        return True, "short_circuit"

    # Cached responses are already polished from previous use
    if s.flags.get("skip_polish"):
        return True, "cache_hit"

    # No message to polish
    if not s.last_summary:
        return True, "no_message"

    # Quick booking intent - prioritize speed over polish
    if s.metadata.get("user_intent") == "quick_booking":
        return True, "quick_booking"

    # Frustrated user - avoid perceived delays
    if s.metadata.get("user_tone") == "frustrated":
        return True, "frustrated_user"

    msg = s.last_summary

    # Check if message contains list-like content that would benefit from polish
    has_list_content = any(pattern in msg.lower() for pattern in _POLISH_LIST_PATTERNS)

    # Check if message is long enough to benefit from formatting
    is_long_enough = len(msg) >= _POLISH_MIN_LENGTH

    # Only polish if the content would benefit from it
    if not has_list_content and not is_long_enough:
        return True, "short_simple_response"

    # Message already seems warm AND well-formatted (has emoji, formatting, reasonable length)
    has_emoji = any(c in msg for c in "✈️🏨🎉🌴☀️😊👍🎊🗺️📍✨🌟💫🎯")
    has_exclamation = "!" in msg
    has_bold = "**" in msg  # Already has markdown bold formatting
    if has_emoji and has_exclamation and has_bold and len(msg) > 50:
        return True, "already_formatted"

    return False, ""


async def response_polish(state: GraphState) -> GraphState:
    """
    Polish the assistant message for a more natural, travel-agent-like tone.
    Uses a lightweight LLM call with hard timeout cap.
    """
    import time

    _debug_node_entry("response_polish", state)

    # Check if we should skip polishing
    should_skip, skip_reason = _should_skip_polish(state)
    if should_skip:
        state.metadata["polish_skipped_reason"] = skip_reason
        _debug(f"Response polish skipped: {skip_reason}")
        _debug_node_exit("response_polish", state)
        return state

    # Get per-node LLM configuration
    llm_config = _get_node_llm_config("response_polish")

    # Build the polish prompt
    try:
        prompt = load_prompt("response_polish")
        trip_dests = state.trip_inputs.destinations
        destinations = ", ".join(trip_dests) if trip_dests else ""
        tpl = (
            prompt.replace("{assistant_message}", state.last_summary or "")
            .replace("{user_tone}", state.metadata.get("user_tone", "neutral"))
            .replace("{user_intent}", state.metadata.get("user_intent", "detailed_planner"))
            .replace("{destinations}", destinations or "not specified yet")
        )

        # Use hard timeout cap from settings (convert ms to seconds)
        timeout_seconds = settings.response_polish_timeout_ms / 1000.0

        start_time = time.perf_counter()

        out = await call_llm_with_timeout(
            model=llm_config["model_hint"],
            prompt=tpl,
            timeout_seconds=timeout_seconds,
            max_tokens=llm_config["max_tokens"],
            temperature=llm_config["temperature"],
        )
        _increment_llm_calls(state)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        _record_llm_time(state, elapsed_ms)
        state.metadata["polish_duration_ms"] = round(elapsed_ms, 2)

        # Log warning if approaching timeout
        if elapsed_ms > settings.response_polish_warn_threshold_ms:
            _debug(
                f"Response polish took {elapsed_ms:.0f}ms (warn threshold: "
                f"{settings.response_polish_warn_threshold_ms}ms)"
            )

        # Parse and apply polished message
        j = jloads_safe(out)
        polished = j.get("polished_message", "").strip()

        if polished and len(polished) > 10:
            _debug(
                "Response polished",
                original_len=len(state.last_summary or ""),
                polished_len=len(polished),
            )
            state.last_summary = polished
        else:
            _debug("Polish returned empty/short response, keeping original")
            state.metadata["polish_skipped_reason"] = "empty_response"

    except TimeoutError:
        # Hard timeout - use original message
        state.metadata["polish_skipped_reason"] = "timeout"
        state.metadata["polish_duration_ms"] = settings.response_polish_timeout_ms
        _debug(f"Response polish timed out after {settings.response_polish_timeout_ms}ms")

    except Exception as exc:
        # Any other error - use original message, don't fail the request
        state.metadata["polish_skipped_reason"] = f"error: {str(exc)[:50]}"
        _debug_error("Response polish failed", error=str(exc))

    _debug_node_exit("response_polish", state)
    return state


# -----------------------
# Message condensation (for long responses)
# -----------------------
# Timeout for condensation LLM call (ms)
_CONDENSE_TIMEOUT_MS = 500


async def condense_long_message(
    message: str,
    max_length: int,
    timeout_ms: int = _CONDENSE_TIMEOUT_MS,
) -> str:
    """
    Condense a message that exceeds max_length using LLM re-summarization.

    Instead of abruptly truncating with ellipsis, this function asks the LLM
    to produce a shorter version that naturally concludes and preserves
    all essential information.

    Args:
        message: The original message to condense.
        max_length: Target maximum character length.
        timeout_ms: Timeout for the LLM call in milliseconds.

    Returns:
        Condensed message, or gracefully truncated fallback if LLM fails.
    """
    if not message or len(message) <= max_length:
        return message

    try:
        prompt = load_prompt("condense")
        # Target ~90% of max length to leave buffer
        target_length = int(max_length * 0.9)
        tpl = prompt.replace("{message}", message).replace("{target_length}", str(target_length))

        timeout_seconds = timeout_ms / 1000.0

        out = await call_llm_with_timeout(
            model="small",
            prompt=tpl,
            timeout_seconds=timeout_seconds,
            max_tokens=512,
            temperature=0.3,
        )

        j = jloads_safe(out)
        condensed = j.get("condensed_message", "").strip()

        if condensed and len(condensed) > 50:
            _debug(
                "Message condensed successfully",
                original_len=len(message),
                condensed_len=len(condensed),
            )
            # If still too long, do a graceful fallback truncation
            if len(condensed) > max_length:
                return _graceful_truncate(condensed, max_length)
            return condensed
        else:
            _debug("Condense returned empty/short response, using fallback")

    except TimeoutError:
        _debug(f"Condense timed out after {timeout_ms}ms, using fallback")
    except Exception as exc:
        _debug_error("Condense failed", error=str(exc))

    # Fallback: graceful truncation at sentence/word boundary
    return _graceful_truncate(message, max_length)


def _graceful_truncate(message: str, max_length: int) -> str:
    """
    Truncate message gracefully at a natural boundary (sentence or word).

    Unlike simple truncation with "...", this finds the last complete
    sentence or word that fits, preserving readability.
    """
    if len(message) <= max_length:
        return message

    # Leave room for ellipsis
    target = max_length - 3

    if target <= 0:
        return message[:max_length]

    truncated = message[:target]

    # Try to find last sentence ending (. ! ?)
    last_sentence = -1
    for punct in ".!?":
        idx = truncated.rfind(punct)
        if idx > last_sentence:
            last_sentence = idx

    # If we found a sentence ending in the last ~30% of text, use it
    if last_sentence > target * 0.7:
        return message[: last_sentence + 1]

    # Otherwise find last word boundary
    last_space = truncated.rfind(" ")
    if last_space > target * 0.5:
        return message[:last_space] + "..."

    # Final fallback
    return truncated + "..."


def summarize(state: GraphState) -> GraphState:
    """Optional micro-summarizer node."""
    _debug_node_entry("summarize", state)
    # If no assistant message, generate a default follow-up question
    if not state.last_summary:
        trip_inputs_dict = state.trip_inputs.model_dump(exclude_none=True)
        missing = _compute_missing_fields(trip_inputs_dict)
        _debug(
            "Summarize fallback triggered",
            missing=missing,
            last_summary_was=repr(state.last_summary),
        )
        user_intent = state.metadata.get("user_intent", "detailed_planner")
        user_tone = state.metadata.get("user_tone", "neutral")
        # Use the version that returns both question and field for tracking
        default_question, asked_field = _default_follow_up_with_field(
            missing, user_intent, user_tone, trip_inputs_dict
        )
        if default_question:
            state.last_summary = default_question
            if asked_field:
                state.metadata["last_question_field"] = asked_field
                _debug(
                    "Summarize set default question", question=default_question, field=asked_field
                )
            else:
                _debug("Summarize set default question", question=default_question)
        else:
            _debug("Summarize: no default question available")
    else:
        _debug(
            "Summarize: last_summary already set",
            preview=state.last_summary[:80] if state.last_summary else "",
        )
    _debug_node_exit("summarize", state)
    return state


# -----------------------
# Branch post-processing (new node)
# -----------------------
def branch_postprocess(state: GraphState) -> GraphState:
    """
    Post-process branches: split by destination if multi_city_intent != 'multi_city',
    normalize all branch specs, and generate unique IDs.
    """
    _debug_node_entry("branch_postprocess", state)

    if not state.branches:
        _debug("No branches to post-process")
        _debug_node_exit("branch_postprocess", state)
        return state

    ti = state.trip_inputs
    fallback_inputs = ti.model_dump(exclude_none=True)

    # If multi_city_intent is not "multi_city" and we have multiple destinations,
    # split branches by destination
    if ti.multi_city_intent != "multi_city" and len(ti.destinations) > 1:
        _debug("Splitting branches by destination", destinations=ti.destinations)
        new_branches: List[Dict[str, Any]] = []
        for branch in state.branches:
            branch_dests = branch.get("destinations", [])
            if len(branch_dests) > 1:
                # Split this branch into one per destination
                for dest in branch_dests:
                    split_branch = dict(branch)
                    split_branch["id"] = uuid4().hex[:8]
                    split_branch["destinations"] = [dest]
                    split_branch["label"] = f"{dest} Trip"
                    normalized = _normalize_branch_spec(split_branch, fallback_inputs)
                    if normalized:
                        new_branches.append(normalized)
            else:
                normalized = _normalize_branch_spec(branch, fallback_inputs)
                if normalized:
                    new_branches.append(normalized)
        state.branches = new_branches
    else:
        # Just normalize all branches - filter out None values explicitly
        normalized_branches: List[Dict[str, Any]] = []
        for b in state.branches:
            normalized = _normalize_branch_spec(b, fallback_inputs)
            if normalized:
                normalized_branches.append(normalized)
        state.branches = normalized_branches

    # Ensure all branches have unique IDs
    seen_ids: set[str] = set()
    for branch in state.branches:
        if not branch.get("id") or branch["id"] in seen_ids:
            branch["id"] = uuid4().hex[:8]
        seen_ids.add(branch["id"])

    _debug("Branch post-processing complete", branches=len(state.branches))
    _debug_node_exit("branch_postprocess", state)
    return state


# -----------------------
# Tile search node (integrated with tile_service)
# -----------------------
def tile_search(state: GraphState) -> GraphState:
    """
    Search for tiles based on branches and booking_types.
    Calls tile_service.search_tiles for each branch.
    """
    _debug_node_entry("tile_search", state)

    # Check if any booking types are enabled
    booking_types = state.trip_inputs.booking_types or {}
    any_enabled = any(booking_types.values())

    if not any_enabled:
        _debug("No booking types enabled, skipping tile search")
        _debug_node_exit("tile_search", state)
        return state

    if not state.branches:
        _debug("No branches to search tiles for")
        _debug_node_exit("tile_search", state)
        return state

    ti = state.trip_inputs
    tiles_dict: Dict[str, Any] = {}

    # Determine which verticals to search based on booking_types
    verticals: List[str] = []
    if booking_types.get("hotels"):
        verticals.append("hotel")
    if booking_types.get("flights"):
        verticals.append("flight")
    if booking_types.get("activities"):
        verticals.append("activity")

    if not verticals:
        _debug("No verticals enabled despite booking types set")
        _debug_node_exit("tile_search", state)
        return state

    # Search tiles for the primary branch only (idx == 0), matching plan.py behavior
    for idx, branch in enumerate(state.branches):
        if idx != 0:
            # plan.py only searches tiles for the primary branch
            continue

        branch_id = branch.get("id", f"branch_{idx}")
        branch_destinations = branch.get("destinations", [])
        primary_dest = branch_destinations[0] if branch_destinations else None

        if not primary_dest:
            _debug(f"Branch {branch_id} has no destination, skipping tile search")
            continue

        try:
            tiles_request = TilesSearchRequest(
                branch_id=branch_id,
                destination=primary_dest,
                destination_hint=primary_dest,
                origin=branch.get("origin") or ti.origin,
                start_date=branch.get("start_date") or ti.start_date,
                end_date=branch.get("end_date") or ti.end_date,
                adults=branch.get("adults") or ti.adults,
                children=branch.get("children") or ti.children,
                requires_assistance=branch.get("requires_assistance") or ti.requires_assistance,
                currency=branch.get("currency") or ti.currency or DEFAULT_CURRENCY,
                verticals=verticals,  # type: ignore
                max_results_per_vertical=5,
                budget=ti.budget,  # Pass budget for tile filtering
            )

            _debug(f"Searching tiles for branch {branch_id}", destination=primary_dest)
            tiles_response = search_tiles(tiles_request)

            # Store tiles and update branch tile IDs
            branch_tiles: Dict[str, List[str]] = {"stays": [], "flights": [], "activities": []}

            for tile in tiles_response.tiles:
                tiles_dict[tile.id] = tile.model_dump()
                if tile.type == "hotel":
                    branch_tiles["stays"].append(tile.id)
                elif tile.type == "flight":
                    branch_tiles["flights"].append(tile.id)
                elif tile.type == "activity":
                    branch_tiles["activities"].append(tile.id)

            # Update branch with tile IDs
            branch["tiles"] = branch_tiles

            _debug(
                f"Tiles found for branch {branch_id}",
                hotels=len(branch_tiles["stays"]),
                flights=len(branch_tiles["flights"]),
                activities=len(branch_tiles["activities"]),
            )

        except Exception as e:
            _debug_error(f"Tile search failed for branch {branch_id}", error=str(e))
            continue

    # Store tiles in metadata for later persistence
    state.metadata["tiles"] = tiles_dict
    state.metadata["tile_search_attempted"] = True
    state.metadata["tile_search_booking_types"] = verticals

    _debug(
        "Tile search completed",
        total_tiles=len(tiles_dict),
        enabled_verticals=verticals,
    )
    _debug_node_exit("tile_search", state)
    return state


# -----------------------
# Short-circuit responder (lightweight node for simple inputs)
# -----------------------
def short_circuit_responder(state: GraphState) -> GraphState:
    """
    Handle short-circuited inputs without LLM calls.

    This node is reached when the extractor detects a simple input pattern
    (greeting or yes/no confirmation) that can be handled with template-based
    responses instead of going through the full LLM pipeline.

    Only handles: greeting, confirmation_yes, confirmation_no
    All other input types (including acknowledgments, bare inputs) go through LLM.
    """
    _debug_node_entry("short_circuit_responder", state)

    sc_type = state.flags.get("short_circuit", "unknown")
    sc_response = state.flags.get("short_circuit_response")
    sc_action = state.flags.get("short_circuit_action")

    _debug(f"Short-circuit responder handling: {sc_type}", action=sc_action)

    # Get trip context for generating follow-up questions
    trip_inputs_dict = state.trip_inputs.model_dump(exclude_none=True)
    missing = _compute_missing_fields(trip_inputs_dict)
    user_intent = state.metadata.get("user_intent", "detailed_planner")
    user_tone = state.metadata.get("user_tone", "neutral")

    # Handle based on short-circuit type
    if sc_response:
        # Use the pre-defined template response (greetings)
        state.last_summary = sc_response
        if sc_type == "greeting":
            state.metadata["last_question_field"] = "destinations"
        _debug("Using template response", response=sc_response[:50])
    else:
        # Generate a contextual follow-up question with field tracking
        follow_up, asked_field = _default_follow_up_with_field(
            missing, user_intent, user_tone, trip_inputs_dict
        )
        if asked_field:
            state.metadata["last_question_field"] = asked_field
            _debug(f"Tracking question field: {asked_field}")

        if follow_up:
            if sc_type in ("confirmation_yes", "confirmation_no"):
                if sc_action == "generate_plan":
                    # Plan generation was triggered - this will be handled by the graph
                    state.last_summary = "Generating your travel plan..."
                else:
                    state.last_summary = follow_up
            else:
                state.last_summary = follow_up
        else:
            # No follow-up needed, we might be ready to generate
            state.last_summary = (
                "Looks like I have everything I need! Ready to generate your travel plan?"
            )
            state.metadata["pending_action"] = "generate_plan"
            state.metadata["last_question_field"] = None  # Clear - we're asking for confirmation
            state.question_target = None

    # Always regenerate contextual suggestions to match the current question
    # (Previous suggestions may be stale from a different question)
    question_target = state.metadata.get("last_question_field")
    state.question_target = question_target
    state.suggested_responses = _generate_contextual_suggestions(state, question_target)
    _debug_suggestions(state.suggested_responses, source="short_circuit_responder")

    # Set intent for logging purposes
    state.intent = f"short_circuit:{sc_type}"

    _debug_node_exit("short_circuit_responder", state)
    return state


# -----------------------
# Conditional routing after normalize_inputs
# -----------------------
def route_after_normalize(state: GraphState) -> str:
    """
    Route after normalize_inputs completes.

    Routing priority:
    1. Short-circuit detected → short_circuit_responder (no LLM)
    2. High confidence extraction + core fields present + no new content → skip router
       and go directly to required_fields_node for confirmation (saves router LLM call)
    3. Default → router (LLM determines intent)

    Note: The bypass is conservative - it only triggers when the user input appears
    to be a simple confirmation/acknowledgment with no new intent-bearing content.
    """
    # 1. Short-circuit takes priority
    if state.flags.get("short_circuit"):
        sc_type = state.flags.get("short_circuit")
        _debug("Routing to short_circuit_responder", type=sc_type)
        _set_confidence_routing(state, f"short_circuit:{sc_type}")
        return "short_circuit_responder"

    # 2. High-confidence router bypass (CONSERVATIVE)
    # Only bypass when:
    # - Very high extraction confidence
    # - Core fields already complete
    # - No typos detected
    # - User input is short (likely just confirmation, not new request)
    # - No strategy/activity keywords that would require routing
    extraction_conf = state.metadata.get("extraction_confidence", {})
    conf_level = extraction_conf.get("level", "medium")
    conf_overall = extraction_conf.get("overall", 0.5)

    ti = state.trip_inputs
    core_fields_complete = ti.destinations and ti.origin and ti.start_date
    no_typos = not extraction_conf.get("typo_suggestions", {})

    # Only bypass for very short inputs (confirmations) that don't contain new intent
    user_text = state.user_text or ""
    is_short_input = len(user_text.strip()) <= 30

    # Check for strategy/intent keywords that would require routing
    # These keywords indicate the user wants a specific specialist, not just confirmation
    intent_keywords = (
        # Strategy topics
        "cycling",
        "hiking",
        "diving",
        "skiing",
        "boating",
        # Specialist categories
        "flight",
        "flights",
        "hotel",
        "hotels",
        "boutique",
        "accommodation",
        "stay",
        "where to stay",
        "transport",
        "train",
        "car rental",
        "activity",
        "activities",
        "things to do",
        # Question words
        "how",
        "what",
        "when",
        "where",
        "should",
        "recommend",
        "suggest",
        "find",
        "book",
    )
    has_intent_keywords = any(kw in user_text.lower() for kw in intent_keywords)

    if (
        conf_overall >= CONFIDENCE_THRESHOLD_SKIP_ROUTER
        and core_fields_complete
        and no_typos
        and conf_level == "high"
        and is_short_input
        and not has_intent_keywords
    ):
        _debug(
            "High-confidence router bypass",
            confidence=f"{conf_overall:.2f}",
            destinations=ti.destinations,
            origin=ti.origin,
            start_date=ti.start_date,
            user_text_len=len(user_text.strip()),
        )
        _set_confidence_routing(state, "high_confidence_bypass")
        # Set intent directly to skip router LLM call
        state.intent = "required_fields"
        return "required_fields_node"

    # 3. Default: use router to determine intent
    _set_confidence_routing(state, f"router:{conf_level}")
    return "router"


# -----------------------
# Conditional routing after required_fields (for deferred intent handling)
# -----------------------
def route_after_required_fields(state: GraphState) -> str:
    """
    Route after required_fields completes.

    If there's a deferred_intent (original intent that was postponed until core fields
    were extracted), route to that specialist. Otherwise, go to validate_and_merge.

    This enables multi-faceted extraction: "direct flight from Rome to Patagonia next week"
    first extracts destinations/origin/dates via required_fields, then routes to flights
    specialist for flight-specific preferences.
    """
    deferred_intent = state.metadata.get("deferred_intent")

    if deferred_intent:
        # Core fields should now be extracted - check if we should proceed with deferred intent
        ti = state.trip_inputs
        core_fields_complete = ti.destinations and ti.origin and ti.start_date

        if core_fields_complete:
            # Append the required_fields response to chat history to avoid repetition
            if state.last_summary:
                state.chat_history.append(
                    {
                        "role": "assistant",
                        "content": state.last_summary,
                    }
                )

            # Clear deferred intent to prevent loops
            state.metadata.pop("deferred_intent", None)
            deferred_topic = state.metadata.pop("deferred_strategy_topic", None)

            _debug(
                "Routing to deferred intent after core fields extracted",
                deferred_intent=deferred_intent,
                deferred_topic=deferred_topic,
            )

            # Restore strategy topic if it was a strategy intent
            if deferred_intent == "strategy" and deferred_topic:
                state.strategy_topic = deferred_topic
                return "strategy_node"

            # Map intent to node
            intent_to_node = {
                "flights": "flights_node",
                "hotels": "hotels_node",
                "transport": "transport_node",
                "activities": "activities_node",
                "correction_needed": "correction_node",
            }
            return intent_to_node.get(deferred_intent, "validate_and_merge")
        else:
            # Core fields still incomplete - clear deferred and continue to validate
            _debug(
                "Core fields still incomplete, clearing deferred intent",
                destinations=bool(ti.destinations),
                origin=bool(ti.origin),
                start_date=bool(ti.start_date),
            )
            state.metadata.pop("deferred_intent", None)
            state.metadata.pop("deferred_strategy_topic", None)

    return "validate_and_merge"


# -----------------------
# Conditional routing after branch_postprocess
# -----------------------
def route_after_branch_postprocess(state: GraphState) -> str:
    """Route to tile_search if any booking types are enabled, otherwise to summarize."""
    booking_types = state.trip_inputs.booking_types or {}
    any_enabled = any(booking_types.values())

    if any_enabled and state.branches:
        _debug(
            "Routing to tile_search",
            enabled_booking_types=[k for k, v in booking_types.items() if v],
        )
        return "tile_search"
    else:
        _debug("Skipping tile_search, routing to summarize")
        return "summarize"


# -----------------------
# Graph assembly (updated with new nodes)
# -----------------------
_graph = StateGraph(GraphState)
_graph.add_node("extractor", extractor)
_graph.add_node("normalize_inputs", normalize_inputs)
_graph.add_node("short_circuit_responder", short_circuit_responder)
_graph.add_node("router", router)
_graph.add_node("required_fields_node", required_fields_node)
_graph.add_node("flights_node", flights_node)
_graph.add_node("hotels_node", hotels_node)
_graph.add_node("transport_node", transport_node)
_graph.add_node("activities_node", activities_node)
_graph.add_node("strategy_node", strategy_node)
_graph.add_node("correction_node", correction_node)
_graph.add_node("validate_and_merge", validate_and_merge)
_graph.add_node("branch_postprocess", branch_postprocess)
_graph.add_node("tile_search", tile_search)
_graph.add_node("summarize", summarize)
_graph.add_node("response_polish", response_polish)


# Routing function after extractor - fast-path for pure short-circuits
def route_after_extractor(state: GraphState) -> str:
    """
    Route immediately after extractor for maximum responsiveness.

    Pure short-circuits (greeting, acknowledgment, off-topic, yes/no without parsed data)
    bypass normalize_inputs entirely.

    Short-circuits with parsed data (bare_destination, bare_date, etc.) go through
    normalize_inputs to apply the extracted data.
    """
    sc_type = state.flags.get("short_circuit")
    if sc_type:
        # Pure short-circuits with no data to normalize - go directly to responder
        if sc_type in ("greeting", "acknowledgment", "off_topic"):
            _debug(f"Fast-path: bypassing normalize_inputs for {sc_type}")
            return "short_circuit_responder"
        # Yes/no confirmations without pending action that would change state
        if sc_type in ("confirmation_yes", "confirmation_no") and not state.parsed_inputs:
            _debug(f"Fast-path: bypassing normalize_inputs for {sc_type}")
            return "short_circuit_responder"
    # All other cases go through normalize_inputs
    return "normalize_inputs"


# Flow: START → extractor → (conditional) normalize_inputs or short_circuit_responder
_graph.add_edge(START, "extractor")

# Conditional edge after extractor: fast-path for pure short-circuits
_graph.add_conditional_edges(
    "extractor",
    route_after_extractor,
    {
        "normalize_inputs": "normalize_inputs",
        "short_circuit_responder": "short_circuit_responder",
    },
)

# Conditional edge: normalize_inputs → router OR short_circuit_responder OR required_fields_node
_graph.add_conditional_edges(
    "normalize_inputs",
    route_after_normalize,
    {
        "router": "router",
        "short_circuit_responder": "short_circuit_responder",
        "required_fields_node": "required_fields_node",
    },
)

# short_circuit_responder → summarize (bypass validate_and_merge, branch_postprocess)
_graph.add_edge("short_circuit_responder", "summarize")


def route_after_router(state: GraphState) -> str:
    # =========================================================================
    # OFF-TOPIC HANDLING
    # =========================================================================
    # Off-topic queries have already been handled in the router node with a
    # friendly deflection response. Skip to summarize to output the response.
    if state.intent == "off_topic":
        _debug("Routing off_topic to summarize")
        return "summarize"

    # =========================================================================
    # CONFIDENCE-BASED ROUTING
    # =========================================================================
    # Force required_fields for low confidence extractions
    # This allows the LLM to validate/correct entities like typos or non-English
    extraction_conf = state.metadata.get("extraction_confidence", {})
    confidence_level = extraction_conf.get("level", "medium")
    confidence_score = extraction_conf.get("overall", 0.5)

    # Low confidence forces LLM extraction only when we didn't extract any meaningful updates.
    # Many preference-only turns (e.g., "direct business class", "rent a car") won't extract new
    # places and would otherwise be mis-routed to required_fields.
    meaningful_turn_update = any(
        k in (state.parsed_inputs or {})
        for k in (
            "budget_delta",
            "adults_delta",
            "children_delta",
            "requires_assistance_delta",
            "multi_city_intent_delta",
            "flight_settings_delta",
            "hotel_settings_delta",
            "transport_settings_delta",
            "category_activation",
            "strategy_hint",
        )
    )

    if (
        confidence_level == "low"
        and not meaningful_turn_update
        and state.intent not in ("correction_needed", "required_fields")
    ):
        low_reasons = extraction_conf.get("low_confidence_reasons", [])
        state.metadata["force_required_fields_reason"] = "low_extraction_confidence"
        state.metadata["deferred_intent"] = state.intent
        if state.strategy_topic:
            state.metadata["deferred_strategy_topic"] = state.strategy_topic
        _debug(
            "Forcing required_fields due to low extraction confidence",
            confidence=f"{confidence_score:.2f}",
            level=confidence_level,
            reasons=low_reasons[:3],
        )
        return "required_fields_node"

    # Non-English detected with high confidence → force LLM extraction
    if not extraction_conf.get("is_english", True):
        lang = extraction_conf.get("detected_language", "unknown")
        lang_conf = extraction_conf.get("language_confidence", 0)
        if lang_conf > 0.8 and state.intent not in ("correction_needed", "required_fields"):
            state.metadata["force_required_fields_reason"] = f"non_english:{lang}"
            state.metadata["deferred_intent"] = state.intent
            _debug(
                "Forcing required_fields due to non-English input",
                detected_language=lang,
                language_confidence=f"{lang_conf:.2f}",
            )
            return "required_fields_node"

    # Typo suggestions present → force LLM extraction to confirm/correct
    typo_suggestions = extraction_conf.get("typo_suggestions", {})
    if typo_suggestions and state.intent not in ("correction_needed", "required_fields"):
        state.metadata["force_required_fields_reason"] = "typo_detected"
        state.metadata["typo_suggestions"] = typo_suggestions
        state.metadata["deferred_intent"] = state.intent
        # Set up pending action for short-circuit typo confirmation on next turn
        state.metadata["pending_action"] = "confirm_typo"
        state.metadata["pending_typo_corrections"] = typo_suggestions
        _debug(
            "Forcing required_fields due to potential typos",
            typo_suggestions=typo_suggestions,
        )
        return "required_fields_node"

    # Strategy intents (skiing, hiking, diving, etc.) can proceed immediately
    # once detected - they provide activity-specific guidance even without
    # destination/origin/dates being set.
    if state.intent == "strategy":
        return "strategy_node"

    # CRITICAL: Force required_fields when core fields are missing
    # This ensures destination extraction happens even when router detects
    # activity/flight/strategy keywords. The required_fields specialist has the best
    # extraction logic for bare place names, typos, etc.
    ti = state.trip_inputs
    core_fields_missing = not ti.destinations or not ti.origin or not ti.start_date

    if core_fields_missing and state.intent not in ("correction_needed", "required_fields"):
        # Store the original intent to route to after required_fields completes
        original_intent = state.intent
        original_topic = state.strategy_topic

        # Only defer if there's a meaningful intent to come back to
        if original_intent and original_intent != "required_fields":
            state.metadata["deferred_intent"] = original_intent
            if original_topic:
                state.metadata["deferred_strategy_topic"] = original_topic
            _debug(
                "Deferring intent until core fields extracted",
                deferred_intent=original_intent,
                deferred_topic=original_topic,
                destinations=bool(ti.destinations),
                origin=bool(ti.origin),
                start_date=bool(ti.start_date),
            )
        else:
            _debug(
                "Forcing required_fields route due to missing core fields",
                destinations=bool(ti.destinations),
                origin=bool(ti.origin),
                start_date=bool(ti.start_date),
            )
        return "required_fields_node"

    intent = state.intent or "required_fields"
    return {
        "required_fields": "required_fields_node",
        "flights": "flights_node",
        "hotels": "hotels_node",
        "transport": "transport_node",
        "activities": "activities_node",
        "correction_needed": "correction_node",
    }.get(intent, "required_fields_node")


_graph.add_conditional_edges(
    "router",
    route_after_router,
    {
        "strategy_node": "strategy_node",
        "required_fields_node": "required_fields_node",
        "flights_node": "flights_node",
        "hotels_node": "hotels_node",
        "transport_node": "transport_node",
        "activities_node": "activities_node",
        "correction_node": "correction_node",
        "summarize": "summarize",
    },
)

# required_fields_node has special conditional routing for deferred intents
_graph.add_conditional_edges(
    "required_fields_node",
    route_after_required_fields,
    {
        "validate_and_merge": "validate_and_merge",
        "flights_node": "flights_node",
        "hotels_node": "hotels_node",
        "transport_node": "transport_node",
        "activities_node": "activities_node",
        "strategy_node": "strategy_node",
        "correction_node": "correction_node",
    },
)

# Other workers go directly to validate_and_merge
for n in [
    "flights_node",
    "hotels_node",
    "transport_node",
    "activities_node",
    "strategy_node",
    "correction_node",
]:
    _graph.add_edge(n, "validate_and_merge")

# validate_and_merge → branch_postprocess
_graph.add_edge("validate_and_merge", "branch_postprocess")

# branch_postprocess → conditional routing to tile_search or summarize
_graph.add_conditional_edges(
    "branch_postprocess",
    route_after_branch_postprocess,
    {
        "tile_search": "tile_search",
        "summarize": "summarize",
    },
)

# tile_search → summarize → response_polish → END
_graph.add_edge("tile_search", "summarize")
_graph.add_edge("summarize", "response_polish")
_graph.add_edge("response_polish", END)

app = _graph.compile(checkpointer=MemorySaver())


def clear_session_checkpoint(session_id: str) -> None:
    """
    Clear the LangGraph checkpoint for a session.

    Called when a session is reset to ensure the graph state doesn't persist.
    The MemorySaver stores checkpoints by thread_id, which is 'session_{session_id}'.
    """
    thread_id = f"session_{session_id}"
    try:
        # MemorySaver stores checkpoints in a dict keyed by thread_id
        # Access the internal storage to clear it
        if hasattr(app, "checkpointer") and app.checkpointer is not None:
            checkpointer = app.checkpointer
            if hasattr(checkpointer, "storage"):
                storage = getattr(checkpointer, "storage", None)
                if storage is not None and thread_id in storage:
                    del storage[thread_id]
                    _debug(f"Cleared LangGraph checkpoint for thread_id={thread_id}")
    except Exception as e:
        _debug_error(f"Failed to clear checkpoint for {thread_id}: {e}")


# Environment variable for checkpoint TTL (hours), defaults to 24 hours
_CHECKPOINT_TTL_HOURS = int(os.getenv("CHECKPOINT_TTL_HOURS", "24"))


def prune_stale_checkpoints() -> int:
    """
    Remove LangGraph checkpoints that have been idle for longer than CHECKPOINT_TTL_HOURS.

    This helps prevent memory overflow from accumulated thread checkpoints.
    The MemorySaver stores checkpoints in-memory, so this is important for
    long-running instances.

    Returns the number of checkpoints that were pruned.
    """
    pruned_count = 0
    try:
        if not hasattr(app, "checkpointer") or app.checkpointer is None:
            return 0

        checkpointer = app.checkpointer
        if not hasattr(checkpointer, "storage"):
            return 0

        storage = getattr(checkpointer, "storage", None)
        if storage is None or not isinstance(storage, dict):
            return 0

        now = datetime.now(UTC)
        ttl_delta = timedelta(hours=_CHECKPOINT_TTL_HOURS)
        threads_to_remove = []

        # Iterate over storage to find stale checkpoints
        for thread_id, checkpoint_data in storage.items():
            # MemorySaver stores checkpoints with metadata including timestamps
            # Try to extract the last access/update time
            try:
                # Check if checkpoint has timestamp metadata
                if isinstance(checkpoint_data, dict):
                    # Look for common timestamp fields
                    ts = checkpoint_data.get("ts") or checkpoint_data.get("timestamp")
                    if ts:
                        if isinstance(ts, str):
                            last_access = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        elif isinstance(ts, (int, float)):
                            last_access = datetime.fromtimestamp(ts, tz=UTC)
                        else:
                            last_access = now  # Can't parse, skip

                        if now - last_access > ttl_delta:
                            threads_to_remove.append(thread_id)
                    else:
                        # No timestamp, mark for removal if we're in strict mode
                        # For now, skip entries without timestamps
                        pass
            except Exception:
                # If we can't parse the checkpoint, skip it
                continue

        # Remove stale checkpoints
        for thread_id in threads_to_remove:
            try:
                del storage[thread_id]
                pruned_count += 1
                _debug(f"Pruned stale checkpoint: {thread_id}")
            except KeyError:
                pass

        if pruned_count > 0:
            _debug(f"Pruned {pruned_count} stale checkpoints (TTL: {_CHECKPOINT_TTL_HOURS}h)")

    except Exception as e:
        _debug_error(f"Failed to prune stale checkpoints: {e}")

    return pruned_count


def clear_all_checkpoints() -> int:
    """
    Clear ALL LangGraph checkpoints regardless of age.

    Use with caution - this will clear all in-progress session states.
    Returns the number of checkpoints that were cleared.
    """
    cleared_count = 0
    try:
        if not hasattr(app, "checkpointer") or app.checkpointer is None:
            return 0

        checkpointer = app.checkpointer
        if not hasattr(checkpointer, "storage"):
            return 0

        storage = getattr(checkpointer, "storage", None)
        if storage is not None and isinstance(storage, dict):
            cleared_count = len(storage)
            storage.clear()
            _debug(f"Cleared all {cleared_count} LangGraph checkpoints")

    except Exception as e:
        _debug_error(f"Failed to clear all checkpoints: {e}")

    return cleared_count


def checkpoint_stats() -> dict[str, int]:
    """Return a snapshot of checkpoint storage size."""
    try:
        if hasattr(app, "checkpointer") and app.checkpointer is not None:
            checkpointer = app.checkpointer
            if hasattr(checkpointer, "storage"):
                storage = getattr(checkpointer, "storage", None)
                if storage is not None and isinstance(storage, dict):
                    return {"checkpoint_count": len(storage)}
    except Exception:
        pass
    return {"checkpoint_count": 0}


# -----------------------
# Public entrypoint
# -----------------------


def _required_done(ti: TripInputs) -> bool:
    # Match READY STATE rule (destinations, origin, start_date)
    return bool(ti.destinations and ti.origin and ti.start_date)


def _progress_signal(before: TripInputs, after: TripInputs) -> bool:
    # Register progress if any required field newly completed or any field changed
    if _required_done(before) != _required_done(after):
        return True
    # Shallow diff on a few high-signal keys
    keys = [
        "destinations",
        "origin",
        "start_date",
        "end_date",
        "budget",
        "currency",
        "activity_settings",
        "strategy_settings",
        "booking_types",
        "flight_settings",
        "hotel_settings",
        "transport_settings",
    ]
    b = before.model_dump(exclude_none=True)
    a = after.model_dump(exclude_none=True)
    return any(b.get(k) != a.get(k) for k in keys)


async def run_turn(
    user_text: str, session_state: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Public entrypoint for running a single turn of the planning graph (async).

    Args:
        user_text: The user's message.
        session_state: Optional session state from previous turns.

    Returns:
        Dict with assistant_message, trip_inputs, ready_to_generate, branches, etc.
    """
    _debug("=" * 60)
    _debug("RUN_TURN START", user_text=user_text[:100] if len(user_text) > 100 else user_text)
    _debug("=" * 60)

    session_state = session_state or {}
    thread_id = session_state.get("thread_id") or str(uuid4())

    # Previous state snapshot for progress heuristics
    prev_ti = TripInputs(**session_state.get("trip_inputs", {}))

    # Build metadata with today_iso from session_state (defaults to current date)
    metadata = deepcopy(session_state.get("metadata", {}))
    if "today_iso" in session_state:
        metadata["today_iso"] = session_state["today_iso"]
    elif "today_iso" not in metadata:
        metadata["today_iso"] = date.today().isoformat()

    # Reset turn-specific metadata counters that shouldn't persist across turns
    # These should start fresh each turn for consistent routing behavior
    metadata.pop("validator_failures", None)
    metadata.pop("no_progress_turns", None)
    metadata.pop("last_intent", None)
    # Clear turn-scoped context fields - nodes will re-set them as needed
    # last_question_field is set by nodes that ask questions, cleared here so stale
    # context from previous turns doesn't influence short-circuit detection
    metadata.pop("last_question_field", None)
    # Clear pending actions to prevent stale actions from triggering on unrelated inputs
    metadata.pop("pending_action", None)
    metadata.pop("pending_typo_corrections", None)
    # Clear deferred intent/strategy to prevent stale deferrals
    metadata.pop("deferred_intent", None)
    metadata.pop("deferred_strategy_topic", None)

    # Build input state
    # Reset turn-specific flags to prevent stale state from persisting
    incoming_flags = deepcopy(session_state.get("flags", {}))
    incoming_flags.pop("generate_plan", None)
    incoming_flags.pop("generate_requested", None)
    # Clear short-circuit flags so each turn re-detects from scratch
    incoming_flags.pop("short_circuit", None)
    incoming_flags.pop("short_circuit_response", None)
    incoming_flags.pop("short_circuit_action", None)

    state = GraphState(
        user_text=user_text,
        trip_inputs=TripInputs(**session_state.get("trip_inputs", {})),
        metadata=metadata,
        flags=incoming_flags,
        last_summary=session_state.get("last_summary"),
        branches=deepcopy(session_state.get("branches", [])),
        suggested_responses=deepcopy(session_state.get("suggested_responses", [])),
        errors=deepcopy(session_state.get("errors", [])),
        chat_history=deepcopy(
            session_state.get("chat_history", [])
        ),  # Pass chat history for LLM context
    )

    # Use a unique thread_id per turn to prevent LangGraph from restoring stale checkpoint state
    # We manage state ourselves via session_state, so we don't need checkpoint persistence
    turn_thread_id = f"{thread_id}_{uuid4().hex[:8]}"

    # Build config with optional LangSmith tracing
    # When LANGSMITH_TRACING=true in .env, we use a LangChainTracer callback
    # to capture the actual LangSmith run UUID for trace enrichment
    tracing_enabled = settings.langsmith_tracing_enabled and settings.langsmith_api_key
    tracer = None
    config: Dict[str, Any] = {"configurable": {"thread_id": turn_thread_id}}

    if tracing_enabled and LANGCHAIN_TRACER_AVAILABLE:
        # Ensure LangChain env vars are set for the tracer to work
        if settings.langsmith_api_key:
            os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
            os.environ["LANGCHAIN_TRACING_V2"] = "true"
            os.environ["LANGCHAIN_ENDPOINT"] = settings.langsmith_endpoint
            os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project

        # Extract test metadata for trace tagging
        scenario_id = metadata.get("scenario_id", "")
        is_test_run = metadata.get("test_run", False)

        # Create tracer with tags for searchability
        # Note: LangChainTracer doesn't accept metadata param - we encode info in tags
        tracer = LangChainTracer(
            project_name=settings.langsmith_project,
            tags=[
                "nomadic",
                f"thread:{thread_id}",
                *(["e2e-test"] if is_test_run else []),
                *([f"scenario:{scenario_id}"] if scenario_id else []),
            ],
        )
        config["callbacks"] = [tracer]
        config["run_name"] = f"run_turn_{thread_id[:8]}"

    # Execute the graph
    result: GraphState | dict = await app.ainvoke(state, config=config)

    # Capture the actual LangSmith run ID from the tracer (if available)
    # This is the real UUID that can be used to fetch trace details
    langsmith_run_id: Optional[str] = turn_thread_id  # Fallback to correlator
    if tracer is not None and hasattr(tracer, "latest_run") and tracer.latest_run:
        langsmith_run_id = str(tracer.latest_run.id)
    elif tracer is not None and hasattr(tracer, "run_map") and tracer.run_map:
        # Alternative: get the root run from run_map
        root_runs = [r for r in tracer.run_map.values() if r.parent_run_id is None]
        if root_runs:
            langsmith_run_id = str(root_runs[0].id)

    # Normalize to GraphState in case the graph returns a plain dict (e.g., from checkpoints)
    if isinstance(result, dict):
        result = GraphState.model_validate(result)

    # Update simple “no progress” metric used by conversation quality tracking
    try:
        made_progress = _progress_signal(prev_ti, result.trip_inputs)
        meta = result.metadata or {}
        if made_progress:
            meta["no_progress_turns"] = 0
        else:
            meta["no_progress_turns"] = int(meta.get("no_progress_turns", 0)) + 1
        result.metadata = meta
    except Exception:
        # Do not let metrics break the turn
        pass

    # Extract observability metrics from result state
    result_meta = result.metadata or {}
    result_flags = result.flags or {}

    # Print token usage summary at end of trace
    _debug_token_summary(result)

    # Log final suggestions being returned
    _debug_suggestions(result.suggested_responses, source="FINAL RESPONSE")

    # Assemble response
    resp = {
        "assistant_message": result.last_summary or "",
        "trip_inputs": result.trip_inputs.model_dump(exclude_none=True),
        "ready_to_generate": result.ready_to_generate,
        "branches": result.branches,
        "suggested_responses": result.suggested_responses,
        "errors": result.errors,
        "run_id": langsmith_run_id,  # LangSmith trace ID for E2E evaluation
        "session_state": {
            "trip_inputs": result.trip_inputs.model_dump(),
            "metadata": result_meta,
            "flags": result_flags,
            "last_summary": result.last_summary,
            "branches": result.branches,
            "suggested_responses": result.suggested_responses,
            "errors": result.errors,
            "thread_id": thread_id,
            # Observability metrics for analytics
            "router_intent": getattr(result, "intent", None),
            "strategy_topic": getattr(result, "strategy_topic", None),
            "short_circuit_type": result_flags.get("short_circuit"),
            "llm_calls_made": result_meta.get("llm_calls_made", 0),
            "cache_hits": result_meta.get("cache_hits", 0),
            "confidence_routing": result_meta.get("confidence_routing"),
            # Token and timing metrics for diagnostics
            "total_tokens": result_meta.get("total_tokens", 0),
            "node_tokens": result_meta.get("node_tokens", {}),
            "llm_time_ms": result_meta.get("llm_time_ms", 0.0),
        },
    }
    return resp


# =============================================================================
# STREAMING RUN_TURN (SSE support)
# =============================================================================


async def run_turn_streaming(user_text: str, session_state: Optional[Dict[str, Any]] = None):
    """
    Streaming version of run_turn that yields SSE events.

    Runs the graph normally until response_polish, then streams the final
    assistant message. For code-only paths (short-circuit), simulates streaming.

    Yields SSE events in the format:
        {"type": "token", "data": "..."} - streaming token
        {"type": "complete", "data": {...}} - final state with all extractions

    Args:
        user_text: The user's message.
        session_state: Optional session state from previous turns.

    Yields:
        Dict with SSE event data.
    """

    _debug("=" * 60)
    _debug(
        "RUN_TURN_STREAMING START", user_text=user_text[:100] if len(user_text) > 100 else user_text
    )
    _debug("=" * 60)

    session_state = session_state or {}
    thread_id = session_state.get("thread_id") or str(uuid4())

    # Previous state snapshot for progress heuristics
    prev_ti = TripInputs(**session_state.get("trip_inputs", {}))

    # Build metadata with today_iso from session_state (defaults to current date)
    metadata = deepcopy(session_state.get("metadata", {}))
    if "today_iso" in session_state:
        metadata["today_iso"] = session_state["today_iso"]
    elif "today_iso" not in metadata:
        metadata["today_iso"] = date.today().isoformat()

    # Reset turn-specific metadata counters
    metadata.pop("validator_failures", None)
    metadata.pop("no_progress_turns", None)
    metadata.pop("last_intent", None)
    # Clear turn-scoped context fields - nodes will re-set them as needed
    # last_question_field is set by nodes that ask questions, cleared here so stale
    # context from previous turns doesn't influence short-circuit detection
    metadata.pop("last_question_field", None)
    # Clear pending actions to prevent stale actions from triggering on unrelated inputs
    metadata.pop("pending_action", None)
    metadata.pop("pending_typo_corrections", None)
    # Clear deferred intent/strategy to prevent stale deferrals
    metadata.pop("deferred_intent", None)
    metadata.pop("deferred_strategy_topic", None)

    # Build input state
    # Reset turn-specific flags to prevent stale state from persisting
    incoming_flags = deepcopy(session_state.get("flags", {}))
    incoming_flags.pop("generate_plan", None)
    incoming_flags.pop("generate_requested", None)
    # Clear short-circuit flags so each turn re-detects from scratch
    incoming_flags.pop("short_circuit", None)
    incoming_flags.pop("short_circuit_response", None)
    incoming_flags.pop("short_circuit_action", None)

    state = GraphState(
        user_text=user_text,
        trip_inputs=TripInputs(**session_state.get("trip_inputs", {})),
        metadata=metadata,
        flags=incoming_flags,
        last_summary=session_state.get("last_summary"),
        branches=deepcopy(session_state.get("branches", [])),
        suggested_responses=deepcopy(session_state.get("suggested_responses", [])),
        errors=deepcopy(session_state.get("errors", [])),
        chat_history=deepcopy(session_state.get("chat_history", [])),
    )

    # Use a unique thread_id per turn
    turn_thread_id = f"{thread_id}_{uuid4().hex[:8]}"

    # Run the full graph (non-streaming) to get final state
    # Note: We run the full graph first, then stream the final message
    # This ensures all extractions complete before we start streaming
    result: GraphState | dict = await app.ainvoke(
        state, config={"configurable": {"thread_id": turn_thread_id}}
    )

    # Normalize to GraphState
    if isinstance(result, dict):
        result = GraphState.model_validate(result)

    # Update progress metrics
    try:
        made_progress = _progress_signal(prev_ti, result.trip_inputs)
        meta = result.metadata or {}
        if made_progress:
            meta["no_progress_turns"] = 0
        else:
            meta["no_progress_turns"] = int(meta.get("no_progress_turns", 0)) + 1
        result.metadata = meta
    except Exception:
        pass

    result_meta = result.metadata or {}
    result_flags = result.flags or {}

    # Print token usage summary
    _debug_token_summary(result)
    _debug_suggestions(result.suggested_responses, source="FINAL RESPONSE (STREAMING)")

    # Get the final assistant message to stream
    final_message = result.last_summary or ""

    # Determine if this was a short-circuit or polish-skipped path
    polish_skipped = result_meta.get("polish_skipped_reason")
    is_short_circuit = bool(result_flags.get("short_circuit"))

    # Stream the message
    if final_message:
        if polish_skipped or is_short_circuit:
            # Simulated streaming for code-generated messages
            _debug(
                "Simulating streaming for code-generated response",
                reason=polish_skipped or "short_circuit",
            )
            async for char in simulate_streaming(final_message):
                yield {"type": "token", "data": char}
        else:
            # For LLM-polished responses, we already have the complete response
            # (since we ran the full graph). Stream it with simulated timing
            # to provide consistent UX.
            #
            # Note: True LLM streaming would require restructuring the graph
            # to run response_polish as a separate streaming call. For now,
            # we simulate to maintain UX consistency.
            _debug("Simulating streaming for polished response")
            async for char in simulate_streaming(final_message):
                yield {"type": "token", "data": char}

    # Build final response (same as run_turn)
    resp = {
        "assistant_message": final_message,
        "trip_inputs": result.trip_inputs.model_dump(exclude_none=True),
        "ready_to_generate": result.ready_to_generate,
        "branches": result.branches,
        "suggested_responses": result.suggested_responses,
        "errors": result.errors,
        "session_state": {
            "trip_inputs": result.trip_inputs.model_dump(),
            "metadata": result_meta,
            "flags": result_flags,
            "last_summary": result.last_summary,
            "branches": result.branches,
            "suggested_responses": result.suggested_responses,
            "errors": result.errors,
            "thread_id": thread_id,
            "router_intent": getattr(result, "intent", None),
            "strategy_topic": getattr(result, "strategy_topic", None),
            "short_circuit_type": result_flags.get("short_circuit"),
            "llm_calls_made": result_meta.get("llm_calls_made", 0),
            "cache_hits": result_meta.get("cache_hits", 0),
            "confidence_routing": result_meta.get("confidence_routing"),
        },
    }

    # Yield complete event with full state
    yield {"type": "complete", "data": resp}


# =============================================================================
# DATABASE-INTEGRATED ENTRYPOINT (matches plan.py's plan_trip)
# =============================================================================


def _history_to_messages(history: List[models.ChatMessage]) -> List[Dict[str, str]]:
    """
    Convert database ChatMessage objects to message format for state.

    Filters out empty messages (e.g., unfilled assistant placeholders).
    """
    messages: List[Dict[str, str]] = []
    for entry in history:
        content = entry.content or ""
        if not content.strip():
            continue
        messages.append({"role": entry.role, "content": content})
    return messages


async def _resolve_parent_trip_context(
    db: AsyncSession,
    *,
    session: models.Session,
    requested_parent_id: Optional[int],
) -> Optional[models.TripContext]:
    """
    Resolve the parent TripContext for the current planning request (async).
    """
    if requested_parent_id is not None:
        parent_ctx = await db.get(models.TripContext, requested_parent_id)
        if not parent_ctx:
            raise ValueError("trip_context_id not found")
        if parent_ctx.session_id != session.id:
            raise ValueError("trip_context_id does not belong to this session")
        return parent_ctx

    return await get_latest_trip_context_for_session(db, session=session)


def _trip_inputs_to_document(ti: TripInputs) -> DocumentTripInputs:
    """Convert graph TripInputs to DocumentTripInputs for persistence.

    Includes all fields including booking preferences to match plan.py behavior.
    """
    # Convert booking_types dict to BookingTypes model
    booking_types_data = ti.booking_types or {}
    booking_types = BookingTypes(
        hotels=booking_types_data.get("hotels", False),
        flights=booking_types_data.get("flights", False),
        ground_transport=booking_types_data.get("ground_transport", False),
        activities=booking_types_data.get("activities", False),
    )

    # Convert flight_settings dict to FlightSettings model
    flight_settings_data = ti.flight_settings or {}
    flight_settings = FlightSettings(
        round_trip=flight_settings_data.get("round_trip", True),
        cabin_class=flight_settings_data.get("cabin_class", "economy"),
        direct_only=flight_settings_data.get("direct_only", False),
    )

    # Convert hotel_settings dict to HotelSettings model
    hotel_settings_data = ti.hotel_settings or {}
    hotel_settings = HotelSettings(
        min_stars=hotel_settings_data.get("min_stars", 0),
        amenities=hotel_settings_data.get("amenities", []),
    )

    # Convert activity_settings dict to ActivitySettings model
    activity_settings_data = ti.activity_settings or {}
    activity_settings = ActivitySettings(
        categories=activity_settings_data.get("categories", []),
    )

    # Convert transport_settings dict to TransportSettings model
    transport_settings_data = ti.transport_settings or {}
    transport_settings = TransportSettings(
        car=transport_settings_data.get("car", False),
        train=transport_settings_data.get("train", False),
        bus=transport_settings_data.get("bus", False),
    )

    return DocumentTripInputs(
        destinations=ti.destinations or [],
        origin=ti.origin,
        start_date=ti.start_date,
        end_date=ti.end_date,
        adults=ti.adults,
        children=ti.children,
        requires_assistance=ti.requires_assistance,
        budget=int(ti.budget) if ti.budget else None,
        currency=ti.currency or DEFAULT_CURRENCY,
        multi_city_intent=ti.multi_city_intent,
        missing_fields=_compute_missing_fields(ti.model_dump(exclude_none=True)),
        # Booking preferences - match plan.py behavior
        booking_types=booking_types,
        flight_settings=flight_settings,
        hotel_settings=hotel_settings,
        activity_settings=activity_settings,
        transport_settings=transport_settings,
    )


def _branches_to_document(
    branches: List[Dict[str, Any]],
    trip_context_id: int,
) -> List[DocumentBranch]:
    """Convert graph branches to DocumentBranch list for persistence."""
    doc_branches: List[DocumentBranch] = []

    for idx, spec in enumerate(branches):
        branch_destinations = spec.get("destinations", []) or []
        if not isinstance(branch_destinations, list):
            branch_destinations = [branch_destinations] if branch_destinations else []

        doc_branch = DocumentBranch(
            id=spec.get("id") or f"branch_{trip_context_id}_{idx}",
            label=str(spec.get("label", "")),
            description=str(spec.get("description", "")),
            destinations=branch_destinations,
            origin=_normalize_str(spec.get("origin")),
            start_date=_normalize_date(spec.get("start_date")),
            end_date=_normalize_date(spec.get("end_date")),
            adults=_normalize_int(spec.get("adults")),
            children=_normalize_int(spec.get("children")),
            requires_assistance=spec.get("requires_assistance"),
            budget=_normalize_budget(spec.get("budget")),
            currency=(
                _normalize_currency(spec.get("currency"), default=DEFAULT_CURRENCY)
                or DEFAULT_CURRENCY
            ),
            is_primary=(idx == 0),
            tiles=BranchTileIds(
                stays=spec.get("tiles", {}).get("stays", []),
                flights=spec.get("tiles", {}).get("flights", []),
                activities=spec.get("tiles", {}).get("activities", []),
            ),
        )
        doc_branches.append(doc_branch)

    return doc_branches


async def plan_trip_graph(
    db: AsyncSession, session_id: str, req: PlanRequest
) -> PlanDocumentResponse:
    """
    Main planning flow using the LangGraph-based planner (async).

    This is the database-integrated entry point that:
    1. Gets/creates session and document
    2. Fetches chat history
    3. Runs the LangGraph planning flow
    4. Persists results to the database

    Args:
        db: SQLAlchemy async database session.
        session_id: Session ID from cookie.
        req: PlanRequest containing user message.

    Returns:
        PlanDocumentResponse: The complete response including document state.
    """
    _debug("=" * 60)
    _debug("PLAN_TRIP_GRAPH START", session_id=session_id, user_message=req.message[:50])
    _debug("=" * 60)

    # 1. Setup session and context
    db_session = await get_or_create_session(db, session_token=session_id, lock_for_update=True)

    # Fetch chat history
    history_rows = await fetch_chat_history(
        db, session=db_session, limit=settings.plan_chat_history_limit
    )
    history_messages = _history_to_messages(history_rows)

    # Get existing document and parent context
    existing_doc = await get_document(db, session=db_session)
    existing_doc_data: Optional[PlanDocumentData] = None
    parent_trip_context_id: Optional[int] = None

    if existing_doc:
        existing_doc_data = get_document_data(existing_doc)
        parent_trip_context_id = existing_doc_data.trip_context_id

    parent_ctx = await _resolve_parent_trip_context(
        db,
        session=db_session,
        requested_parent_id=parent_trip_context_id,
    )

    try:
        # Create trip context for this turn
        trip_ctx = await create_trip_context(
            db,
            session=db_session,
            parent_trip_context=parent_ctx,
            req_message=req.message,
        )

        # 2. Record user message
        user_message_content = (
            "Generate my trip options" if _is_generate_plan_trigger(req.message) else req.message
        )
        await record_chat_message(
            db,
            session=db_session,
            trip_context=trip_ctx,
            role="user",
            content=user_message_content,
            metadata=None,
        )

        # 3. Prepare placeholder for assistant message
        assistant_chat = await record_chat_message(
            db,
            session=db_session,
            trip_context=trip_ctx,
            role="assistant",
            content="",
            metadata=None,
        )

        # 4. Build initial state from existing document
        initial_trip_inputs: Dict[str, Any] = {}
        initial_branches: List[Dict[str, Any]] = []

        if existing_doc_data and existing_doc_data.trip_inputs:
            ti = existing_doc_data.trip_inputs
            initial_trip_inputs = {
                "destinations": ti.destinations or [],
                "origin": ti.origin,
                "start_date": ti.start_date,
                "end_date": ti.end_date,
                "adults": ti.adults,
                "children": ti.children,
                "requires_assistance": ti.requires_assistance,
                "budget": ti.budget,
                "currency": ti.currency,
                "multi_city_intent": ti.multi_city_intent,
                "booking_types": ti.booking_types.model_dump() if ti.booking_types else {},
                "flight_settings": ti.flight_settings.model_dump() if ti.flight_settings else {},
                "hotel_settings": ti.hotel_settings.model_dump() if ti.hotel_settings else {},
                "activity_settings": (
                    ti.activity_settings.model_dump() if ti.activity_settings else {}
                ),
                "transport_settings": (
                    ti.transport_settings.model_dump() if ti.transport_settings else {}
                ),
            }
            # Load existing branches
            if existing_doc_data.branches:
                initial_branches = [b.model_dump() for b in existing_doc_data.branches]

        # 5. Run the graph
        today_iso = _today_iso(req.timezone)

        session_state = {
            "trip_inputs": initial_trip_inputs,
            "branches": initial_branches,
            "metadata": {
                "today_iso": today_iso,
                "tiles": (
                    {t_id: t.model_dump() for t_id, t in (existing_doc_data.tiles or {}).items()}
                    if existing_doc_data
                    else {}
                ),
            },
            "flags": {},
            "last_summary": None,
            "suggested_responses": [],
            "errors": [],
            "thread_id": f"session_{session_id}",
            "chat_history": history_messages,  # Pass chat history for LLM context
        }

        result = await run_turn(req.message, session_state)

        # 6. Update assistant message
        assistant_chat.content = result.get("assistant_message", "")

        # 7. Get or create the PlanDocument
        plan_doc = await get_or_create_document(db, session=db_session, updated_by="planner")

        try:
            await db.refresh(plan_doc)
        except Exception:
            pass

        # 8. Build document structures from result
        trip_inputs_model = _trip_inputs_to_document(TripInputs(**result.get("trip_inputs", {})))

        doc_branches: List[DocumentBranch] = []
        tiles_dict: Dict[str, TileSchema] = {}

        result_branches = result.get("branches", [])
        if result_branches:
            doc_branches = _branches_to_document(result_branches, trip_ctx.id)

            # Get tiles from metadata
            tiles_from_search = result.get("session_state", {}).get("metadata", {}).get("tiles", {})
            for tile_id, tile_data in tiles_from_search.items():
                if isinstance(tile_data, dict):
                    tiles_dict[tile_id] = TileSchema(**tile_data)

        # 9. Apply the planner update to the document
        # Only provide branches if the graph actually generated new ones.
        # If branches=None, apply_planner_update keeps existing branches and still
        # cascades trip_inputs changes into the primary branch.
        branches_to_apply = doc_branches if doc_branches else None

        plan_doc = await apply_planner_update(
            db,
            doc=plan_doc,
            trip_context_id=trip_ctx.id,
            trip_inputs=trip_inputs_model,
            branches=branches_to_apply,
            tiles=tiles_dict or None,
        )

        doc_data = get_document_data(plan_doc)

        # 10. Build response
        doc_data_dict = doc_data.model_dump()
        doc_data_dict["assistant_message"] = assistant_chat.content
        doc_data_dict["assistant_message_id"] = str(assistant_chat.id)
        doc_data_dict["ready_to_generate"] = result.get("ready_to_generate", False)
        doc_data_dict["suggested_responses"] = result.get("suggested_responses", [])

        if _DEBUG_LOG:
            print("[DEBUG] === AFTER MERGE ===")
            print(json.dumps(doc_data_dict, indent=2, default=str))
            print("=" * 80)

        doc_data_with_chat = PlanDocumentData(**doc_data_dict)

        response = PlanDocumentResponse(
            version=plan_doc.version,
            updated_by=plan_doc.updated_by,
            document=doc_data_with_chat,
            updated_at=plan_doc.updated_at.isoformat(),
            changes_made=True,
        )

        await db.commit()
        _debug("PLAN_TRIP_GRAPH COMPLETE", version=plan_doc.version)
        return response

    except Exception:
        await db.rollback()
        raise
