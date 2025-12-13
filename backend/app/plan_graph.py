# plan_graph.py — Minimalist LangGraph with strategy modules + monolith fallback
from __future__ import annotations

import asyncio
import json
import os
import re
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from jsonschema import Draft7Validator
from jsonschema import validate as jsonschema_validate
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
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

# Try to import tiktoken for token counting, fallback to char-based estimation
try:
    import tiktoken

    _TIKTOKEN_AVAILABLE = True
except ImportError:
    tiktoken = None  # type: ignore
    _TIKTOKEN_AVAILABLE = False

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


def _debug_node_entry(node_name: str, state: "GraphState") -> None:
    """Log entry into a graph node."""
    if _DEBUG_LOG:
        ti = state.trip_inputs
        _debug(
            f">>> ENTERING {node_name}",
            user_text=(
                state.user_text[:50] + "..." if len(state.user_text) > 50 else state.user_text
            ),
            destinations=ti.destinations,
            origin=ti.origin,
            intent=state.intent,
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
# TOKEN ESTIMATION (ported from plan.py)
# =============================================================================


def _count_tokens(text: str) -> int:
    """Estimate token count for a text block using tiktoken, with safe fallbacks."""
    safe_text = text or ""
    if not _TIKTOKEN_AVAILABLE:
        # Fallback: ~4 chars per token
        return len(safe_text) // 4

    try:
        return len(tiktoken.encode(safe_text))  # type: ignore[union-attr]
    except Exception:
        try:
            encoding = tiktoken.get_encoding("cl100k_base")  # type: ignore[union-attr]
            return len(encoding.encode(safe_text))
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

# Required fields for ready_to_generate (only core 3 - matches plan.py)
_REQUIRED_TRIP_INPUT_FIELDS = (
    "destinations",
    "origin",
    "start_date",
)

# =============================================================================
# USER INTENT ARCHETYPES (for conversational style adaptation)
# =============================================================================
# Priority order: lower number = higher priority (speed preferences win)
USER_INTENT_ARCHETYPES = {
    "quick_booking": {
        "priority": 1,
        "patterns": [
            r"\b(just\s+flights?|book\s+now|asap|fastest|quick\s+book|just\s+need)\b",
            r"\b(hurry|urgent|immediately|right\s+away)\b",
        ],
        "description": "Streamlined, minimal questions, skip optional fields",
    },
    "short_trip": {
        "priority": 2,
        "patterns": [
            r"\b(weekend|quick\s+trip|2-3\s+days|getaway|short\s+trip|day\s+trip)\b",
            r"\b(mini\s+vacation|long\s+weekend|brief\s+visit)\b",
        ],
        "description": "Focus on essentials, suggest compact itineraries",
    },
    "adventurous": {
        "priority": 3,
        "patterns": [
            r"\b(explore|off\s+the?\s+beaten\s+path|unique|adventure|hidden\s+gems?)\b",
            r"\b(authentic|local\s+experience|undiscovered|unusual)\b",
        ],
        "description": "Proactive tips, suggest hidden gems, enthusiastic tone",
    },
    "undecided": {
        "priority": 4,
        "patterns": [
            r"\b(not\s+sure|help\s+me|suggestions?|ideas?|recommend|where\s+should)\b",
            r"\b(can\'t\s+decide|options?|what\s+do\s+you\s+think)\b",
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
USER_TONE_PATTERNS = {
    "enthusiastic": {
        "patterns": [
            r"!{2,}",  # Multiple exclamation marks
            r"\b(can\'t\s+wait|so\s+excited|amazing|awesome|love\s+it|perfect)\b",
            r"\b(yay|woohoo|fantastic|incredible|thrilled)\b",
        ],
    },
    "frustrated": {
        "patterns": [
            r"\b(ugh|again\??|still|already\s+told|not\s+working)\b",
            r"\b(confused|frustrat|annoying|wrong|doesn\'t\s+work)\b",
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
    Detect user intent archetype from text using regex patterns.
    Returns the highest-priority matching intent, or None if no match.
    """
    text_lower = text.lower()
    matches = []

    for intent_name, config in USER_INTENT_ARCHETYPES.items():
        if not config["patterns"]:  # Skip default (detailed_planner)
            continue
        for pattern in config["patterns"]:
            if re.search(pattern, text_lower, re.I):
                matches.append((config["priority"], intent_name))
                break  # One match per intent is enough

    if not matches:
        return None

    # Return highest priority (lowest number)
    matches.sort(key=lambda x: x[0])
    return matches[0][1]


def _detect_user_tone(text: str) -> str:
    """
    Detect user tone from text using regex patterns.
    Returns: 'enthusiastic', 'frustrated', or 'neutral'.
    """
    text_lower = text.lower()

    # Check enthusiastic patterns
    for pattern in USER_TONE_PATTERNS["enthusiastic"]["patterns"]:
        if re.search(pattern, text_lower, re.I):
            return "enthusiastic"

    # Check frustrated patterns
    for pattern in USER_TONE_PATTERNS["frustrated"]["patterns"]:
        if re.search(pattern, text_lower, re.I):
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
# - Monolith: Complex reasoning fallback → higher temp, large output, top_p
_NODE_LLM_CONFIG: Dict[str, Dict[str, Any]] = {
    "router": {
        "model_hint": "small",
        "temperature": 0.1,  # Very deterministic for classification
        "max_tokens": 256,  # Only needs short JSON response
        "top_p": None,
    },
    "required_fields": {
        "model_hint": "small",
        "temperature": 0.2,  # Deterministic extraction
        "max_tokens": 1024,
        "top_p": None,
    },
    "flights": {
        "model_hint": "small",
        "temperature": 0.2,
        "max_tokens": 1024,
        "top_p": None,
    },
    "hotels": {
        "model_hint": "small",
        "temperature": 0.2,
        "max_tokens": 1024,
        "top_p": None,
    },
    "transport": {
        "model_hint": "small",
        "temperature": 0.2,
        "max_tokens": 1024,
        "top_p": None,
    },
    "activities": {
        "model_hint": "small",
        "temperature": 0.2,
        "max_tokens": 1024,
        "top_p": None,
    },
    "correction": {
        "model_hint": "small",
        "temperature": 0.2,
        "max_tokens": 1024,
        "top_p": None,
    },
    "strategy": {
        "model_hint": "medium",
        "temperature": 0.3,  # Slightly creative for topic advice
        "max_tokens": 2048,
        "top_p": None,
    },
    "monolith": {
        "model_hint": "large",
        "temperature": 0.5,  # More creative for complex responses
        "max_tokens": 4096,  # Large output for full planning
        "top_p": 0.95,  # Nucleus sampling for diversity
    },
    "response_polish": {
        "model_hint": "small",
        "temperature": 0.4,  # Slightly creative for natural tone
        "max_tokens": 100,  # Keep polished response concise
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
    return datetime.utcnow().strftime("%Y-%m-%d")


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


def _relative_date_to_iso(text: Optional[str]) -> Optional[str]:
    """
    Convert relative date expressions to ISO format dates.

    Handles: "today", "tomorrow", "next week", "next month", "weekend"
    """
    if not text:
        return None

    lowered = text.lower().strip()
    today = datetime.utcnow().date()

    if lowered in {"today", "tonight", "now"}:
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


def _extract_duration_days_from_message(message: str) -> Optional[int]:
    """Extract trip duration in days from patterns like 'for 5 days' or '5 day trip'."""
    if not message:
        return None

    lowered = message.lower()
    patterns = [
        r"coming\s+back\s+in\s+(\d+)\s*days?",
        r"returning?\s+in\s+(\d+)\s*days?",
        r"for\s+(\d+)\s*days?",
        r"(\d+)\s*days?\s+trip",
        r"(\d+)\s*day\s+trip",
    ]

    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            try:
                return int(match.group(1))
            except (ValueError, IndexError):
                continue
    return None


def _compute_end_date_from_duration(start_date: Optional[str], duration_days: int) -> Optional[str]:
    """Compute end_date from start_date and duration."""
    if not start_date or duration_days <= 0:
        return None

    start_dt = _parse_iso_date(start_date)
    if not start_dt:
        return None

    end_dt = start_dt + timedelta(days=duration_days)
    return end_dt.strftime("%Y-%m-%d")


def _normalize_date(value: Any) -> Optional[str]:
    """Normalize various date formats to ISO format (YYYY-MM-DD)."""
    text = _normalize_str(value)
    if not text:
        return None

    relative = _relative_date_to_iso(text)
    if relative:
        return relative

    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue

    iso_match = re.match(r"^\d{4}-\d{2}-\d{2}$", text)
    return text if iso_match else None


def _parse_iso_date(text: Optional[str]) -> Optional[datetime]:
    """Parse an ISO date string to a datetime object."""
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None


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
                        normalized_categories.append(cat_str)
                if normalized_categories:
                    # Dedupe while preserving order
                    seen = set()
                    deduped = []
                    for c in normalized_categories:
                        c_lower = c.lower()
                        if c_lower not in seen:
                            seen.add(c_lower)
                            deduped.append(c)
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

    branch_budget = _normalize_int(spec.get("budget"))
    if branch_budget is None:
        branch_budget = _normalize_int(fallback_inputs.get("budget"))
    if branch_budget is not None and branch_budget < 0:
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


def _default_follow_up_question(
    missing_fields: List[str],
    user_intent: str = "detailed_planner",
    user_tone: str = "neutral",
) -> Optional[str]:
    """
    Get the default question to ask for the next missing field.
    Adapts phrasing based on user intent and tone.
    """
    if not missing_fields:
        return None

    # Base prompts for each field
    base_prompts = {
        "destinations": "Where would you like to go?",
        "origin": "Where will you be traveling from?",
        "start_date": "When does your trip start?",
        "end_date": "When does your trip end?",
        "adults": "How many adults will be going?",
        "budget": "What's your budget for this trip?",
    }

    # Intent-specific phrasing variants
    quick_prompts = {
        "destinations": "Where to?",
        "origin": "Flying from?",
        "start_date": "Departure date?",
        "end_date": "Return date?",
        "adults": "How many travelers?",
        "budget": "Budget range?",
    }

    adventurous_prompts = {
        "destinations": "Where's the adventure taking you? 🌴",
        "origin": "Where are you setting off from?",
        "start_date": "When does the adventure begin?",
        "end_date": "When do you need to be back?",
        "adults": "How many adventurers in your crew?",
        "budget": "What's your budget for this adventure?",
    }

    undecided_prompts = {
        "destinations": "Any destinations you've been dreaming about?",
        "origin": "Where will you be starting your journey from?",
        "start_date": "Do you have any dates in mind?",
        "end_date": "Any idea when you'd like to return?",
        "adults": "How many people are traveling?",
        "budget": "Do you have a rough budget in mind?",
    }

    # Select prompt set based on intent
    if user_intent == "quick_booking":
        prompts = quick_prompts
    elif user_intent == "adventurous":
        prompts = adventurous_prompts
    elif user_intent == "undecided":
        prompts = undecided_prompts
    else:
        prompts = base_prompts

    # Find first missing required field
    for field in _REQUIRED_TRIP_INPUT_FIELDS:
        if field in missing_fields:
            question = prompts.get(field, base_prompts.get(field))
            if question:
                # Adjust for frustrated tone - be more direct, skip embellishments
                if user_tone == "frustrated":
                    # Strip emojis and use simpler phrasing
                    question = quick_prompts.get(field, question)
                return question
    return None


# =============================================================================
# SUGGESTED RESPONSES FILTERING (ported from plan.py)
# =============================================================================


def _filter_suggested_responses(responses: List[Any]) -> List[str]:
    """Filter suggested responses: remove questions, limit to 3, handle dict format."""
    result = []
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

        # Limit length
        if len(text) > 50:
            text = text[:47] + "..."

        result.append(text)

        if len(result) >= 3:
            break

    return result


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
def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")


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
    missing = _compute_missing_fields(state.trip_inputs.model_dump(exclude_none=True))
    user_intent = state.metadata.get("user_intent", "detailed_planner")
    user_tone = state.metadata.get("user_tone", "neutral")
    fallback_msg = _default_follow_up_question(missing, user_intent, user_tone)
    if fallback_msg:
        state.last_summary = fallback_msg
    else:
        state.last_summary = (
            "I'd love to help plan your trip! What destination are you thinking about?"
        )

    state.ready_to_generate = False
    return state


# -----------------------
# Cheap extractor (code) - enhanced with patterns from plan.py
# -----------------------
def extractor(state: GraphState) -> GraphState:
    """
    Extract structured data from user text using regex patterns.
    Enhanced to match plan.py extraction rules.
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

    # budget + currency (multiple patterns)
    # Pattern 1: Symbol before amount ($1000, €500)
    m = re.search(r"(?P<cur>[$€£¥])\s*(?P<amt>\d[\d,\.]*)", text)
    if m:
        cur = m.group("cur")
        amt = float(m.group("amt").replace(",", ""))
        parsed["budget_delta"] = {
            "budget": amt,
            "currency": {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}.get(cur, "USD"),
        }
    # Pattern 2: Amount with currency code (1000 USD, 500 EUR)
    if "budget_delta" not in parsed:
        m = re.search(r"(?P<amt>\d[\d,\.]*)\s*(?P<cur>USD|EUR|GBP|CAD|AUD|JPY)", text, re.I)
        if m:
            amt = float(m.group("amt").replace(",", ""))
            parsed["budget_delta"] = {
                "budget": amt,
                "currency": m.group("cur").upper(),
            }

    # origin/destinations - multiple patterns
    # Pattern 1: "from X to Y"
    m = re.search(r"from\s+(?P<o>[A-Za-z\s\-]+?)\s+to\s+(?P<d>[A-Za-z\s,\-and]+)", text, re.I)
    if m:
        parsed["origin_delta"] = m.group("o").strip()
        parsed["destinations_delta"] = [
            x.strip() for x in re.split(r",|\band\b", m.group("d")) if x.strip()
        ]
    # Pattern 2: "to Y from X"
    if "origin_delta" not in parsed:
        m = re.search(r"to\s+(?P<d>[A-Za-z\s,\-and]+?)\s+from\s+(?P<o>[A-Za-z\s\-]+)", text, re.I)
        if m:
            parsed["origin_delta"] = m.group("o").strip()
            parsed["destinations_delta"] = [
                x.strip() for x in re.split(r",|\band\b", m.group("d")) if x.strip()
            ]

    # Pattern 3: "[destination] leaving today/tomorrow/next week"
    # Extract destination before date phrase
    if "destinations_delta" not in parsed:
        m = re.search(
            r"^(?P<dest>[A-Za-z\s\-]+?)\s+(?:leaving|departing|starting|on|in)\s+(?:today|tomorrow|next\s+week|this\s+weekend|\d)",
            text,
            re.I,
        )
        if m:
            dest = m.group("dest").strip()
            # Make sure it's a reasonable destination name (not too long, not generic words)
            if dest and len(dest) < 50 and dest.lower() not in ("i", "we", "the", "a", "an", "my"):
                parsed["destinations_delta"] = [dest]

    # Pattern 4: "going to X" / "want to go to X" / "visit X"
    if "destinations_delta" not in parsed:
        m = re.search(
            r"(?:going|go|want(?:ing)?\s+to\s+go|visit(?:ing)?|travel(?:ing)?)\s+(?:to\s+)?(?P<dest>[A-Za-z\s,\-and]+?)(?:\s+(?:today|tomorrow|next|on|in|for|\.|$))",
            text,
            re.I,
        )
        if m:
            dest = m.group("dest").strip()
            if dest and len(dest) < 50:
                parsed["destinations_delta"] = [
                    x.strip() for x in re.split(r",|\band\b", dest) if x.strip()
                ]

    # Traveler patterns (from plan.py EXTRACTION RULES)
    # solo / just me
    if re.search(r"\b(solo|just me|traveling alone|by myself)\b", text, re.I):
        parsed["adults_delta"] = 1
        parsed["children_delta"] = 0
    # couple / me and partner
    elif re.search(
        r"\b(couple|me and (my )?(partner|wife|husband|girlfriend|boyfriend))\b", text, re.I
    ):
        parsed["adults_delta"] = 2
        parsed["children_delta"] = 0
    # family of N
    elif m := re.search(r"\bfamily of (\d+)\b", text, re.I):
        family_size = int(m.group(1))
        parsed["adults_delta"] = min(2, family_size)
        parsed["children_delta"] = max(0, family_size - 2)
    # N adults, M kids
    elif m := re.search(r"(\d+)\s*adults?\s*(?:,|and)?\s*(\d+)\s*(?:kids?|children)", text, re.I):
        parsed["adults_delta"] = int(m.group(1))
        parsed["children_delta"] = int(m.group(2))
    # Just N adults
    elif m := re.search(r"(\d+)\s*adults?", text, re.I):
        parsed["adults_delta"] = int(m.group(1))

    # Accessibility
    if re.search(
        r"\b(wheelchair|accessibility|disabled|mobility|requires? assistance)\b", text, re.I
    ):
        parsed["requires_assistance_delta"] = True

    # Date patterns - relative dates
    if re.search(r"\b(today|tonight|now)\b", text, re.I):
        parsed["start_date_hint"] = "today"
    elif re.search(r"\btomorrow\b", text, re.I):
        parsed["start_date_hint"] = "tomorrow"
    elif re.search(r"\bnext week\b", text, re.I):
        parsed["start_date_hint"] = "next week"
    elif re.search(r"\bweekend\b", text, re.I):
        parsed["start_date_hint"] = "weekend"

    # Duration extraction
    duration = _extract_duration_days_from_message(text)
    if duration:
        parsed["duration_days"] = duration

    # Multi-city intent detection
    multi_intent = _normalize_multi_city_intent(text)
    if multi_intent:
        parsed["multi_city_intent_delta"] = multi_intent

    # Category activation
    cats = []
    if re.search(r"flight|cabin|nonstop|direct|one[-\s]?way|round[-\s]?trip|airline", text, re.I):
        cats.append("flights")
    if re.search(r"hotel|amenit|star|room|accommodation|stay|lodge|resort", text, re.I):
        cats.append("hotels")
    if re.search(r"\btrain|car rental|rent a? car|bus|drive|driving\b", text, re.I):
        cats.append("transport")
    if re.search(
        r"activity|tour|museum|beach|hike|dive|nightlife|restaurant|show|ticket", text, re.I
    ):
        cats.append("activities")
    if cats:
        parsed["category_activation"] = cats

    # Flight settings extraction
    if "flights" in cats or re.search(r"flight|cabin|nonstop|direct|one[-\s]?way", text, re.I):
        flight_settings: Dict[str, Any] = {}
        if re.search(r"\b(nonstop|non-stop|direct)\b", text, re.I):
            flight_settings["direct_only"] = True
        if re.search(r"\b(one[-\s]?way)\b", text, re.I):
            flight_settings["round_trip"] = False
        if re.search(r"\b(round[-\s]?trip)\b", text, re.I):
            flight_settings["round_trip"] = True
        if re.search(r"\b(business)\b", text, re.I):
            flight_settings["cabin_class"] = "business"
        elif re.search(r"\b(first\s*class)\b", text, re.I):
            flight_settings["cabin_class"] = "first"
        elif re.search(r"\b(premium\s*economy)\b", text, re.I):
            flight_settings["cabin_class"] = "premium_economy"
        if flight_settings:
            parsed["flight_settings_delta"] = flight_settings

    # Hotel settings extraction
    if "hotels" in cats or re.search(r"hotel|star|amenit", text, re.I):
        hotel_settings: Dict[str, Any] = {}
        if m := re.search(r"(\d)\s*[-\s]?star", text, re.I):
            hotel_settings["min_stars"] = int(m.group(1))
        amenities = []
        if re.search(r"\bpool\b", text, re.I):
            amenities.append("pool")
        if re.search(r"\bgym\b", text, re.I):
            amenities.append("gym")
        if re.search(r"\bspa\b", text, re.I):
            amenities.append("spa")
        if re.search(r"\bwifi\b", text, re.I):
            amenities.append("wifi")
        if re.search(r"\bbreakfast\b", text, re.I):
            amenities.append("breakfast")
        if amenities:
            hotel_settings["amenities"] = amenities
        if hotel_settings:
            parsed["hotel_settings_delta"] = hotel_settings

    # Transport settings extraction
    if "transport" in cats or re.search(r"train|car|bus|drive", text, re.I):
        transport_settings: Dict[str, Any] = {}
        if re.search(r"\b(car|rent a car|car rental|drive|driving)\b", text, re.I):
            transport_settings["car"] = True
        if re.search(r"\btrain\b", text, re.I):
            transport_settings["train"] = True
        if re.search(r"\bbus\b", text, re.I):
            transport_settings["bus"] = True
        if transport_settings:
            parsed["transport_settings_delta"] = transport_settings

    # Strategy detection heuristic (router will finalize)
    if re.search(r"boat|boating|sail|yacht|kayak|canoe|marina", text, re.I):
        parsed["strategy_hint"] = "boating"
    elif re.search(r"hike|trek|trail|alpine|mountain|hiking", text, re.I):
        parsed["strategy_hint"] = "hiking"
    elif re.search(r"dive|diving|scuba|snorkel", text, re.I):
        parsed["strategy_hint"] = "diving"
    elif re.search(r"ski|skiing|snowboard|slopes|powder", text, re.I):
        parsed["strategy_hint"] = "skiing"
    elif re.search(r"cycle|cycling|bike|biking|bicycle", text, re.I):
        parsed["strategy_hint"] = "cycling"

    # =========================================================================
    # USER INTENT & TONE DETECTION (for conversational style adaptation)
    # =========================================================================
    # Detect user intent archetype (fast regex-based hint for router to refine)
    intent_hint = _detect_user_intent_hint(text)
    if intent_hint:
        state.metadata["user_intent_hint"] = intent_hint
        _debug(f"Detected user intent hint: {intent_hint}")

    # Detect user tone for response adaptation
    user_tone = _detect_user_tone(text)
    state.metadata["user_tone"] = user_tone
    if user_tone != "neutral":
        _debug(f"Detected user tone: {user_tone}")

    # Handle intent persistence with decay
    persisted_intent = state.metadata.get("user_intent")
    intent_turn_count = state.metadata.get("intent_turn_count", 0) + 1
    state.metadata["intent_turn_count"] = intent_turn_count

    if persisted_intent:
        confidence = _compute_intent_confidence(intent_turn_count)
        state.metadata["intent_confidence"] = confidence

        if _should_override_persisted_intent(intent_hint, persisted_intent, confidence):
            state.metadata["user_intent"] = intent_hint
            state.metadata["intent_turn_count"] = 1  # Reset turn count
            state.metadata["intent_confidence"] = 1.0
            _debug(f"Intent override: {persisted_intent} -> {intent_hint}")
        elif confidence <= 0:
            # Decay expired, use hint or default to detailed_planner
            state.metadata["user_intent"] = intent_hint or "detailed_planner"
            state.metadata["intent_turn_count"] = 1
            state.metadata["intent_confidence"] = 1.0 if intent_hint else 0.5
            _debug(f"Intent decayed, reset to: {state.metadata['user_intent']}")
    elif intent_hint:
        # First detection
        state.metadata["user_intent"] = intent_hint
        state.metadata["intent_turn_count"] = 1
        state.metadata["intent_confidence"] = 1.0
    else:
        # No hint and no persisted - default to detailed_planner
        if "user_intent" not in state.metadata:
            state.metadata["user_intent"] = "detailed_planner"
            state.metadata["intent_confidence"] = 0.5

    state.parsed_inputs = parsed
    _debug_node_exit("extractor", state)
    return state


# -----------------------
# Normalize inputs node (new)
# -----------------------
def normalize_inputs(state: GraphState) -> GraphState:
    """
    Apply normalization to extracted inputs and merge into trip_inputs.
    This node runs after extractor and before router.
    """
    _debug_node_entry("normalize_inputs", state)

    parsed = state.parsed_inputs
    ti = state.trip_inputs.model_copy(deep=True)
    # today_iso is available via state.metadata if needed

    # Apply budget delta
    if "budget_delta" in parsed:
        bd = parsed["budget_delta"]
        ti.budget = bd.get("budget")
        ti.currency = bd.get("currency", DEFAULT_CURRENCY)

    # Apply origin delta
    if "origin_delta" in parsed:
        ti.origin = _normalize_str(parsed["origin_delta"])

    # Apply destinations delta
    if "destinations_delta" in parsed:
        for d in parsed["destinations_delta"]:
            d_norm = _normalize_str(d)
            if d_norm and d_norm not in ti.destinations:
                ti.destinations.append(d_norm)

    # Apply traveler deltas
    if "adults_delta" in parsed:
        ti.adults = _clamp_traveler_value(_normalize_int(parsed["adults_delta"]))
    if "children_delta" in parsed:
        ti.children = _clamp_traveler_value(_normalize_int(parsed["children_delta"]))
    if "requires_assistance_delta" in parsed:
        ti.requires_assistance = parsed["requires_assistance_delta"]

    # Apply date hints
    if "start_date_hint" in parsed and not ti.start_date:
        ti.start_date = _relative_date_to_iso(parsed["start_date_hint"])
    if "end_date_hint" in parsed and not ti.end_date:
        ti.end_date = _relative_date_to_iso(parsed["end_date_hint"])

    # Apply duration to compute end_date if we have start_date but not end_date
    if "duration_days" in parsed and ti.start_date and not ti.end_date:
        ti.end_date = _compute_end_date_from_duration(ti.start_date, parsed["duration_days"])

    # Apply multi-city intent
    if "multi_city_intent_delta" in parsed:
        ti.multi_city_intent = parsed["multi_city_intent_delta"]

    # Apply flight settings delta
    if "flight_settings_delta" in parsed:
        existing = dict(ti.flight_settings) if ti.flight_settings else {}
        existing.update(parsed["flight_settings_delta"])
        ti.flight_settings = existing

    # Apply hotel settings delta
    if "hotel_settings_delta" in parsed:
        existing = dict(ti.hotel_settings) if ti.hotel_settings else {}
        delta = parsed["hotel_settings_delta"]
        if "amenities" in delta:
            existing_amenities = existing.get("amenities", [])
            for a in delta["amenities"]:
                if a not in existing_amenities:
                    existing_amenities.append(a)
            delta["amenities"] = existing_amenities
        existing.update(delta)
        ti.hotel_settings = existing

    # Apply transport settings delta
    if "transport_settings_delta" in parsed:
        existing = dict(ti.transport_settings) if ti.transport_settings else {}
        existing.update(parsed["transport_settings_delta"])
        ti.transport_settings = existing

    # Auto-enable booking types based on settings
    _auto_enable_booking_types(ti)

    # Normalize currency
    if ti.currency:
        ti.currency = _normalize_currency(ti.currency, default=DEFAULT_CURRENCY)
    elif ti.budget is not None:
        ti.currency = DEFAULT_CURRENCY

    state.trip_inputs = ti
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

        _debug("Router prompt tokens", tokens=_estimate_prompt_tokens(tpl, state.parsed_inputs))

        out = await call_llm_with_timeout(
            model=llm_config["model_hint"],
            prompt=tpl,
            timeout_seconds=settings.llm_timeout_router,
            max_tokens=llm_config["max_tokens"],
            temperature=llm_config["temperature"],
        )
        j = jloads_safe(out)
        state.intent = j.get("intent") or "required_fields"
        topic = j.get("topic") or state.parsed_inputs.get("strategy_hint")
        state.strategy_topic = topic if state.intent == "strategy" else None
        state.metadata["router_notes"] = j.get("notes", "")
        state.metadata["router_confidence"] = j.get("confidence", 1.0)

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

    prompt = load_prompt(name)
    system_prompt = (
        prompt.replace("{trip_inputs}", json.dumps(ti_short(state.trip_inputs)))
        .replace("{parsed_inputs}", json.dumps(state.parsed_inputs))
        .replace("{today}", today_iso)
        .replace("{user_intent_hint}", state.metadata.get("user_intent", "detailed_planner"))
        .replace("{user_tone}", state.metadata.get("user_tone", "neutral"))
    )

    # Determine timeout based on model type
    timeout = settings.llm_timeout_specialist
    attempts = settings.llm_max_retries if retry_on_json_error else 1
    last_error = None

    _debug(
        f"Specialist {name} prompt tokens",
        tokens=_estimate_prompt_tokens(system_prompt, state.parsed_inputs),
    )

    for attempt in range(attempts):
        try:
            # Pass history as separate messages for better context
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

            ti = state.trip_inputs.model_copy(deep=True)
            delta = j.get("trip_inputs", {}) or {}

            # Get valid field names from TripInputs model
            valid_fields = set(ti.model_fields.keys())

            # Apply deltas with normalization
            for k, v in delta.items():
                # Skip unknown fields to avoid crashes
                if k not in valid_fields:
                    _debug(f"Skipping unknown field from LLM: {k}")
                    continue

                if k == "destinations" and isinstance(v, list):
                    for d in v:
                        d_norm = _normalize_str(d)
                        if d_norm and d_norm not in ti.destinations:
                            ti.destinations.append(d_norm)
                elif k in (
                    "flight_settings",
                    "hotel_settings",
                    "activity_settings",
                    "transport_settings",
                    "booking_types",
                ):
                    # Normalize booking fields
                    normalized = _normalize_booking_field(k, v) if isinstance(v, dict) else None
                    if normalized:
                        existing = getattr(ti, k, {}) or {}
                        existing.update(normalized)
                        setattr(ti, k, existing)
                elif k == "start_date" or k == "end_date":
                    normalized_date = _normalize_date(v)
                    if normalized_date is not None:
                        setattr(ti, k, normalized_date)
                elif k == "currency":
                    setattr(ti, k, _normalize_currency(v, default=DEFAULT_CURRENCY))
                elif k == "adults" or k == "children":
                    normalized_int = _clamp_traveler_value(_normalize_int(v))
                    if not _should_skip_field_update(k, normalized_int, getattr(ti, k)):
                        setattr(ti, k, normalized_int)
                elif k == "multi_city_intent":
                    normalized_intent = _normalize_multi_city_intent(v)
                    if normalized_intent is not None:
                        setattr(ti, k, normalized_intent)
                elif _should_skip_field_update(k, v, getattr(ti, k, None)):
                    continue
                else:
                    setattr(ti, k, v)

            # Auto-enable booking types
            _auto_enable_booking_types(ti)

            jsonschema_validate(ti.model_dump(), TRIP_JSON_SCHEMA)
            state.trip_inputs = ti
            state.last_summary = j.get("assistant_message", "")

            # Filter suggested responses (no questions, max 3)
            raw_suggestions = j.get("suggested_responses", []) or []
            state.suggested_responses = _filter_suggested_responses(raw_suggestions)

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

    _debug(
        f"Strategy {topic} prompt tokens",
        tokens=_estimate_prompt_tokens(system_prompt, state.parsed_inputs),
    )

    for attempt in range(attempts):
        try:
            # Pass history as separate messages for better context
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
            j = jloads_safe(out)

            ti = state.trip_inputs.model_copy(deep=True)
            ss = dict(ti.strategy_settings)
            ss[topic] = j.get("strategy_settings", ss.get(topic, {}))
            ti.strategy_settings = ss

            for k, v in (j.get("trip_inputs", {}) or {}).items():
                if k in {"strategy_settings"}:
                    continue
                if k == "destinations" and isinstance(v, list):
                    for d in v:
                        d_norm = _normalize_str(d)
                        if d_norm and d_norm not in ti.destinations:
                            ti.destinations.append(d_norm)
                elif k in (
                    "flight_settings",
                    "hotel_settings",
                    "activity_settings",
                    "transport_settings",
                    "booking_types",
                ):
                    normalized = _normalize_booking_field(k, v) if isinstance(v, dict) else None
                    if normalized:
                        existing = getattr(ti, k, {}) or {}
                        existing.update(normalized)
                        setattr(ti, k, existing)
                elif k == "start_date" or k == "end_date":
                    normalized_date = _normalize_date(v)
                    if normalized_date is not None:
                        setattr(ti, k, normalized_date)
                elif k == "currency":
                    setattr(ti, k, _normalize_currency(v, default=DEFAULT_CURRENCY))
                elif k == "adults" or k == "children":
                    normalized_int = _clamp_traveler_value(_normalize_int(v))
                    if not _should_skip_field_update(k, normalized_int, getattr(ti, k)):
                        setattr(ti, k, normalized_int)
                elif _should_skip_field_update(k, v, getattr(ti, k, None)):
                    continue
                else:
                    setattr(ti, k, v)

            # Auto-enable booking types
            _auto_enable_booking_types(ti)

            jsonschema_validate(ti.model_dump(), TRIP_JSON_SCHEMA)
            state.trip_inputs = ti
            state.last_summary = j.get("assistant_message", "")

            # Filter suggested responses
            raw_suggestions = j.get("suggested_responses", []) or []
            state.suggested_responses = _filter_suggested_responses(raw_suggestions)

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
# Monolith fallback (full prompt)
# -----------------------
async def monolith_node(state: GraphState) -> GraphState:
    """
    Monolith fallback node with timeout and JSON retry logic.

    Used when router confidence is low or specialists fail repeatedly.
    """
    # ⚠️ PROMINENT DEBUG WARNING FOR MONOLITH FALLBACK ⚠️
    _debug("⚠️⚠️⚠️ MONOLITH FALLBACK ACTIVATED ⚠️⚠️⚠️")
    if _DEBUG_LOG:
        print("\n" + "=" * 60)
        print("⚠️⚠️⚠️ MONOLITH FALLBACK ACTIVATED ⚠️⚠️⚠️")
        print("=" * 60)
        print("  Reason indicators:")
        print(f"    - intent: {state.intent}")
        print(f"    - router_confidence: {state.metadata.get('router_confidence', 'N/A')}")
        print(f"    - no_progress_turns: {state.metadata.get('no_progress_turns', 0)}")
        print(f"    - validator_failures: {state.metadata.get('validator_failures', 0)}")
        print(f"    - force_monolith flag: {state.flags.get('force_monolith', False)}")
        print(f"    - generate_plan flag: {state.flags.get('generate_plan', False)}")
        print("=" * 60 + "\n")

    _debug_node_entry("monolith_node", state)

    # Get per-node LLM configuration for monolith
    llm_config = _get_node_llm_config("monolith")

    prompt = load_prompt("monolith")
    # Use today_iso from metadata (injected by route) or fall back to current date
    today_iso = state.metadata.get("today_iso") or _today_iso()

    # Serialize existing branches for LLM context (if any)
    branch_context = _serialize_branches_for_llm(state.branches, state.metadata.get("tiles"))
    existing_branches_block = ""
    if branch_context:
        existing_branches_block = f"\n[EXISTING BRANCHES AND TILES]\n{branch_context}\n"

    # Build system prompt (without chat history - that goes in separate messages)
    system_prompt = (
        prompt.replace("{trip_inputs}", json.dumps(ti_short(state.trip_inputs)))
        .replace("{parsed_inputs}", json.dumps(state.parsed_inputs))
        .replace("{conversation_summary}", state.last_summary or "")
        .replace("{errors}", json.dumps(state.errors))
        .replace("{today}", today_iso)
        .replace(
            "{current_state_json}", json.dumps(ti_short(state.trip_inputs))
        )  # reuse compact state
        .replace("{existing_branches}", existing_branches_block)
    )

    timeout = settings.llm_timeout_monolith
    attempts = settings.llm_max_retries
    last_error = None

    _debug(
        "Monolith prompt tokens", tokens=_estimate_prompt_tokens(system_prompt, state.parsed_inputs)
    )

    for attempt in range(attempts):
        try:
            # Pass history as separate messages (matching plan.py behavior)
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
            j = jloads_safe(out)

            ti = state.trip_inputs.model_copy(deep=True)
            for k, v in (j.get("trip_inputs", {}) or {}).items():
                if k == "destinations" and isinstance(v, list):
                    for d in v:
                        d_norm = _normalize_str(d)
                        if d_norm and d_norm not in ti.destinations:
                            ti.destinations.append(d_norm)
                elif k in (
                    "flight_settings",
                    "hotel_settings",
                    "activity_settings",
                    "transport_settings",
                    "booking_types",
                ):
                    normalized = _normalize_booking_field(k, v) if isinstance(v, dict) else None
                    if normalized:
                        existing = getattr(ti, k, {}) or {}
                        existing.update(normalized)
                        setattr(ti, k, existing)
                elif k == "start_date" or k == "end_date":
                    normalized_date = _normalize_date(v)
                    if normalized_date is not None:
                        setattr(ti, k, normalized_date)
                elif k == "currency":
                    setattr(ti, k, _normalize_currency(v, default=DEFAULT_CURRENCY))
                elif k == "adults" or k == "children":
                    normalized_int = _clamp_traveler_value(_normalize_int(v))
                    if not _should_skip_field_update(k, normalized_int, getattr(ti, k)):
                        setattr(ti, k, normalized_int)
                elif k == "multi_city_intent":
                    normalized_intent = _normalize_multi_city_intent(v)
                    if normalized_intent is not None:
                        setattr(ti, k, normalized_intent)
                elif _should_skip_field_update(k, v, getattr(ti, k, None)):
                    continue
                else:
                    setattr(ti, k, v)

            # Auto-enable booking types
            _auto_enable_booking_types(ti)

            jsonschema_validate(ti.model_dump(), TRIP_JSON_SCHEMA)
            state.trip_inputs = ti
            state.last_summary = j.get("assistant_message", "")

            # Filter suggested responses
            raw_suggestions = j.get("suggested_responses", []) or []
            state.suggested_responses = _filter_suggested_responses(raw_suggestions)

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
            state.metadata["monolith_used"] = True
            state.metadata["token_estimate"] = _count_tokens(out)

            _debug("Monolith completed successfully")
            _debug_node_exit("monolith_node", state)
            return state

        except json.JSONDecodeError as e:
            last_error = e
            _debug_error(f"Monolith JSON error on attempt {attempt + 1}", error=str(e))
            if attempt < attempts - 1:
                system_prompt += INVALID_JSON_HINT
                continue
            break
        except Exception as e:
            last_error = e
            _debug_error(f"Monolith error on attempt {attempt + 1}", error=str(e))
            break

    reason = f"monolith node failed after {attempts} attempt(s): {last_error}"
    _debug_error("Monolith FAILED", reason=reason)
    return _record_llm_failure(state, reason)


# -----------------------
# Validation & summarization (enhanced with plan.py logic)
# -----------------------
def validate_and_merge(state: GraphState) -> GraphState:
    """
    Validate trip inputs and generate user-facing messages for issues.
    Ported from plan.py _validate_trip_inputs.
    """
    _debug_node_entry("validate_and_merge", state)

    ti = state.trip_inputs
    validation_messages: List[str] = []
    today_iso = state.metadata.get("today_iso") or _today_iso()
    today_dt = _parse_iso_date(today_iso)

    # Validate and normalize dates
    start_dt = _parse_iso_date(ti.start_date)
    end_dt = _parse_iso_date(ti.end_date)

    # Check for ISO format
    if ti.start_date and not ISO.match(ti.start_date):
        state.errors.append("Invalid start_date format")
    if ti.end_date and not ISO.match(ti.end_date):
        state.errors.append("Invalid end_date format")

    # Auto-swap dates if end_date < start_date
    if start_dt and end_dt and end_dt < start_dt:
        earliest = min(start_dt, end_dt)
        latest = max(start_dt, end_dt)
        ti.start_date = earliest.strftime("%Y-%m-%d")
        ti.end_date = latest.strftime("%Y-%m-%d")
        validation_messages.append(
            "I reordered your dates so the trip starts before it ends. Does that look right?"
        )
        start_dt = earliest
        end_dt = latest
        _debug("Dates auto-swapped", start=ti.start_date, end=ti.end_date)

    # Past date warnings
    if start_dt and today_dt and start_dt < today_dt:
        validation_messages.append("The start date is in the past. Want to update it?")
    if end_dt and today_dt and end_dt < today_dt:
        validation_messages.append("The end date is in the past. Want to update it?")

    # Validate and clamp traveler counts
    if ti.adults is not None:
        clamped_adults = _clamp_traveler_value(ti.adults)
        if ti.adults < 0:
            validation_messages.append(
                f"Adults count cannot be negative. I set it to {clamped_adults}."
            )
        if ti.adults != clamped_adults:
            ti.adults = clamped_adults

    if ti.children is not None:
        clamped_children = _clamp_traveler_value(ti.children)
        if ti.children < 0:
            validation_messages.append(
                f"Children count cannot be negative. I set it to {clamped_children}."
            )
        if ti.children != clamped_children:
            ti.children = clamped_children

    # Ensure requires_assistance is boolean
    if ti.requires_assistance is not None and not isinstance(ti.requires_assistance, bool):
        ti.requires_assistance = None

    # Validate budget
    if ti.budget is not None and ti.budget < 0:
        ti.budget = None
        validation_messages.append("Budget must be zero or higher. Please share an updated budget.")

    # Normalize currency
    if ti.currency:
        normalized_currency = _normalize_currency(ti.currency)
        if normalized_currency is None:
            normalized_currency = DEFAULT_CURRENCY
            validation_messages.append(f"I set the currency to {normalized_currency}.")
        ti.currency = normalized_currency
    elif ti.budget is not None:
        ti.currency = DEFAULT_CURRENCY

    # Auto-enable booking types based on settings
    _auto_enable_booking_types(ti)

    state.trip_inputs = ti

    # Append validation messages to assistant message if any
    if validation_messages and state.last_summary:
        state.last_summary = state.last_summary + " " + " ".join(validation_messages)
    elif validation_messages:
        state.last_summary = " ".join(validation_messages)

    # Compute missing fields and ready_to_generate
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
        validation_msgs=len(validation_messages),
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

        elapsed_ms = (time.perf_counter() - start_time) * 1000
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
        missing = _compute_missing_fields(state.trip_inputs.model_dump(exclude_none=True))
        _debug(
            "Summarize fallback triggered",
            missing=missing,
            last_summary_was=repr(state.last_summary),
        )
        user_intent = state.metadata.get("user_intent", "detailed_planner")
        user_tone = state.metadata.get("user_tone", "neutral")
        default_question = _default_follow_up_question(missing, user_intent, user_tone)
        if default_question:
            state.last_summary = default_question
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
# Monolith routing policy
# -----------------------
def should_use_monolith(state: GraphState) -> bool:
    """
    Determine if we should use the monolith fallback.

    The monolith is a comprehensive single-prompt approach that's more expensive
    but handles complex/ambiguous requests. We use it sparingly to keep the bot
    conversational and cost-effective.

    Triggers (only in extreme cases):
    - User explicitly requests plan generation (generate_plan flag)
    - Router explicitly returns "unknown" intent (can't classify at all)
    - Multiple consecutive LLM failures (>= 3) indicating systemic issues
    """
    # User explicitly triggered plan generation
    if state.flags.get("generate_plan", False):
        _debug("Monolith triggered: user requested plan generation")
        return True

    # Router couldn't classify the intent at all
    if state.intent == "unknown":
        _debug("Monolith triggered: router returned unknown intent")
        return True

    # Multiple consecutive failures indicate something is broken
    validator_failures = state.metadata.get("validator_failures", 0)
    if validator_failures >= 5:
        _debug(
            "Monolith triggered: multiple failures",
            validator_failures=validator_failures,
        )
        return True

    return False


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
_graph.add_node("router", router)
_graph.add_node("required_fields_node", required_fields_node)
_graph.add_node("flights_node", flights_node)
_graph.add_node("hotels_node", hotels_node)
_graph.add_node("transport_node", transport_node)
_graph.add_node("activities_node", activities_node)
_graph.add_node("strategy_node", strategy_node)
_graph.add_node("correction_node", correction_node)
_graph.add_node("monolith_node", monolith_node)
_graph.add_node("validate_and_merge", validate_and_merge)
_graph.add_node("branch_postprocess", branch_postprocess)
_graph.add_node("tile_search", tile_search)
_graph.add_node("summarize", summarize)
_graph.add_node("response_polish", response_polish)

# Flow: START → extractor → normalize_inputs → router
_graph.add_edge(START, "extractor")
_graph.add_edge("extractor", "normalize_inputs")
_graph.add_edge("normalize_inputs", "router")


def route_after_router(state: GraphState) -> str:
    if should_use_monolith(state):
        return "monolith_node"
    if state.intent == "strategy":
        return "strategy_node"
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
        "monolith_node": "monolith_node",
        "strategy_node": "strategy_node",
        "required_fields_node": "required_fields_node",
        "flights_node": "flights_node",
        "hotels_node": "hotels_node",
        "transport_node": "transport_node",
        "activities_node": "activities_node",
        "correction_node": "correction_node",
    },
)

# From any worker → validate_and_merge → branch_postprocess →
# (conditional) tile_search/summarize → END
for n in [
    "required_fields_node",
    "flights_node",
    "hotels_node",
    "transport_node",
    "activities_node",
    "strategy_node",
    "correction_node",
    "monolith_node",
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
    # These are used for monolith fallback heuristics and should start fresh each turn
    metadata.pop("validator_failures", None)
    metadata.pop("no_progress_turns", None)
    metadata.pop("last_intent", None)

    # Build input state
    # Reset turn-specific flags to prevent monolith fallback from persisting
    incoming_flags = deepcopy(session_state.get("flags", {}))
    incoming_flags.pop("force_monolith", None)
    incoming_flags.pop("generate_plan", None)
    incoming_flags.pop("generate_requested", None)

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
    result: GraphState | dict = await app.ainvoke(
        state, config={"configurable": {"thread_id": turn_thread_id}}
    )

    # Normalize to GraphState in case the graph returns a plain dict (e.g., from checkpoints)
    if isinstance(result, dict):
        result = GraphState.model_validate(result)

    # Update simple “no progress” metric used by should_use_monolith()
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

    # Assemble response
    resp = {
        "assistant_message": result.last_summary or "",
        "trip_inputs": result.trip_inputs.model_dump(exclude_none=True),
        "ready_to_generate": result.ready_to_generate,
        "branches": result.branches,
        "suggested_responses": result.suggested_responses,
        "errors": result.errors,
        "session_state": {
            "trip_inputs": result.trip_inputs.model_dump(),
            "metadata": result.metadata,
            "flags": result.flags,
            "last_summary": result.last_summary,
            "branches": result.branches,
            "suggested_responses": result.suggested_responses,
            "errors": result.errors,
            "thread_id": thread_id,
            # Optional: expose for debugging/analytics if your nodes set them
            "router_intent": getattr(result, "intent", None),
            "strategy_topic": getattr(result, "strategy_topic", None),
        },
    }
    return resp


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
            budget=_normalize_int(spec.get("budget")),
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

        current_doc_data = get_document_data(plan_doc)

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
        final_branches = doc_branches if doc_branches else current_doc_data.branches
        branches_to_apply = final_branches if final_branches else None

        await apply_planner_update(
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
