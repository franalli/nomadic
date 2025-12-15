"""
Trip Planning Module
====================

This module orchestrates the AI-powered trip planning conversation flow. It handles:
- Multi-turn conversation with the LLM to collect trip details (destination, dates, etc.)
- State management via PlanDocument (the single source of truth)
- Branch generation (different trip options/themes) once all inputs are collected
- Tile search integration (flights, hotels, activities)

Architecture Overview:
---------------------
1. User sends a message via PlanRequest
2. System retrieves session, chat history, and existing document state
3. LLM is called with conversation context + document state
4. LLM response is parsed, validated, and merged with existing state
5. PlanDocument is updated with new trip_inputs, branches, and tiles
6. Response is returned to the frontend

Key Design Decisions:
--------------------
- PlanDocument is the single source of truth for trip state
- LLM receives document JSON directly and returns updated trip_inputs
- merge_trip_inputs in crud_document handles merging with most-recent-wins logic
- Branches are only generated once ALL required fields are collected
- Robust JSON parsing handles malformed LLM responses
"""

import json
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, cast
from zoneinfo import ZoneInfo

import tiktoken
from openai.types.chat import ChatCompletionMessageParam
from sqlalchemy.orm import Session

from app import db_models as models
from app.config import get_openai_client
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
    BranchTileIds,
    DocumentBranch,
    DocumentTripInputs,
    PlanDocumentData,
    PlanDocumentResponse,
    PlanRequest,
    TilesSearchRequest,
)
from app.schemas import (
    Tile as TileSchema,
)
from app.tile_service import search_tiles


class PlannerLLMOutput:
    """
    Container for the structured output from the LLM planning call.

    This class holds the parsed response from OpenAI, separating the different
    components that the planner needs to process.

    Attributes:
        branches: List of branch specifications (trip options/themes). Each branch
                  is a dict with keys: label, description, destination, origin,
                  start_date, end_date, adults, children, requires_assistance,
                  budget, currency.
        assistant_message: The conversational response to show the user.
        trip_inputs: Dict of collected/updated trip input fields.
        ready_to_generate: True when all fields are complete but branches haven't
                           been generated yet (waiting for user to click Generate).
        suggested_responses: List of 1-3 suggested user responses for quick replies.
        token_estimate: Estimated total tokens used so far for debugging purposes.
    """

    def __init__(
        self,
        *,
        branches: List[dict],
        assistant_message: str,
        trip_inputs: Optional[dict] = None,
        ready_to_generate: bool = False,
        suggested_responses: Optional[List[str]] = None,
        token_estimate: Optional[int] = None,
    ) -> None:
        self.branches = branches
        self.assistant_message = assistant_message
        self.trip_inputs = trip_inputs or {}
        self.ready_to_generate = ready_to_generate
        self.suggested_responses = suggested_responses or []
        self.token_estimate = token_estimate


# =============================================================================
# CONFIGURATION CONSTANTS
# =============================================================================
# These environment-driven settings control LLM behavior and conversation limits.

_CHAT_HISTORY_LIMIT = int(os.getenv("PLAN_CHAT_HISTORY_LIMIT", "20"))  # Max messages to include
_MAX_TOKENS = int(os.getenv("OPENAI_PLAN_MAX_TOKENS", "800"))  # Token limit for LLM response
_PLAN_TEMPERATURE = float(
    os.getenv("OPENAI_PLAN_TEMPERATURE", "0.5")
)  # Response creativity (lower = more consistent)
_PLAN_TOP_P = float(os.getenv("OPENAI_PLAN_TOP_P", "0.95"))  # Nucleus sampling threshold
_PLAN_MAX_RETRIES = int(os.getenv("OPENAI_PLAN_MAX_RETRIES", "3"))  # Retry count for API errors
_PLAN_SEED = os.getenv("OPENAI_PLAN_SEED")  # Optional seed for reproducibility

_DEBUG_LOG = bool(os.getenv("DEBUG_PLAN_MESSAGES"))  # Enable verbose debug logging

# The canonical order for collecting trip input fields.
# This order is used consistently for prompts, validation, and missing field detection.
_TRIP_INPUT_FIELDS = (
    "destinations",
    "origin",
    "start_date",
    "end_date",
    "adults",
    "children",
    "requires_assistance",
    "budget",
    "currency",
    "multi_city_intent",
)

# Booking preference fields - these are nested objects extracted from conversation
_BOOKING_PREFERENCE_FIELDS = (
    "booking_types",
    "flight_settings",
    "hotel_settings",
    "activity_settings",
    "transport_settings",
)

# Required fields - only core 3 must be filled before branches can be generated
# adults/children, end_date and budget are optional - defaults will be applied during generation
_REQUIRED_TRIP_INPUT_FIELDS = (
    "destinations",
    "origin",
    "start_date",
)

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
# ACTIVITY EMOJI MAPPING
# =============================================================================
# Maps activity keywords (lowercase) to their emoji prefixes.
# Used to normalize activities so they all have consistent emoji prefixes.

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
    Normalize an activity string to ensure it has an emoji prefix.

    - If the activity already starts with an emoji, return it as-is
    - Otherwise, look up the activity in the emoji map and add the appropriate emoji
    - If no match found, use the sparkle emoji as default
    """
    activity = activity.strip()
    if not activity:
        return activity

    # Check if the activity already starts with an emoji
    first_char = activity[0]
    if ord(first_char) > 0x1F00:
        return activity

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
        if keyword in activity_lower:
            if re.search(rf"\b{re.escape(keyword)}\b", activity_lower):
                return f"{emoji} {activity}"

    # No match found, use default sparkle emoji
    return f"{_DEFAULT_ACTIVITY_EMOJI} {activity}"


def _deduplicate_activities_case_insensitive(categories: List[str]) -> List[str]:
    """
    Deduplicate activity categories case-insensitively.
    When comparing, strips the emoji prefix to compare only the activity text.
    Keeps the first occurrence of each unique activity.
    """
    seen_lower: set = set()
    deduped: List[str] = []

    for cat in categories:
        text = cat.strip()
        text_start = 0
        for i, char in enumerate(text):
            if ord(char) < 0x1F00 and char != " ":
                text_start = i
                break
            elif char == " " and i > 0:
                text_start = i + 1
                break

        text_portion = text[text_start:].strip().lower()

        if text_portion and text_portion not in seen_lower:
            seen_lower.add(text_portion)
            deduped.append(cat)

    return deduped


# =============================================================================
# TOKEN ESTIMATION
# =============================================================================


def _count_tokens(text: str) -> int:
    """Estimate token count for a text block using tiktoken, with safe fallbacks."""
    safe_text = text or ""
    try:
        return len(tiktoken.encode(safe_text))
    except Exception:
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(safe_text))
        except Exception:
            # Fallback to character length if tiktoken fails entirely
            return len(safe_text)


def _estimate_total_tokens(
    *,
    system_messages: List[str],
    history: List[ChatCompletionMessageParam],
    user_message: str,
    llm_output: str,
) -> int:
    """
    Approximate total tokens consumed so far by summing system, history, user, and LLM output.
    """
    token_counter = 0

    for content in system_messages:
        if content:
            token_counter += _count_tokens(str(content))

    for msg in history:
        content = ""
        if isinstance(msg, dict):
            content = str(msg.get("content", ""))
        else:
            content = str(getattr(msg, "content", ""))
        token_counter += _count_tokens(content)

    token_counter += _count_tokens(user_message)
    token_counter += _count_tokens(llm_output)

    return token_counter


# =============================================================================
# DATE UTILITY FUNCTIONS
# =============================================================================


def _today_iso(timezone_name: Optional[str] = None) -> str:
    """
    Get today's date in ISO format (YYYY-MM-DD).

    Uses the provided timezone if valid, otherwise falls back to UTC.
    This ensures users see "today" and "tomorrow" relative to their
    local time, not server time.

    Args:
        timezone_name: Optional IANA timezone name (e.g., "Europe/Rome").
                       If None or invalid, falls back to UTC.

    Returns:
        str: Today's date as "YYYY-MM-DD" in the specified timezone.
    """
    tz = None
    if timezone_name:
        try:
            tz = ZoneInfo(timezone_name)
        except (KeyError, ValueError):
            # Invalid timezone - fall back to UTC
            pass

    if tz:
        return datetime.now(tz).strftime("%Y-%m-%d")
    return datetime.utcnow().strftime("%Y-%m-%d")


# =============================================================================
# OPENAI CLIENT MANAGEMENT
# =============================================================================


def _serialize_document_for_llm(doc_data: Optional[PlanDocumentData]) -> Optional[str]:
    """
    Serialize branches and tiles from PlanDocumentData for LLM context.

    This function converts the branches and tiles into a text format that
    the LLM can understand. It does NOT include trip_inputs since those
    are already provided in the CURRENT STATE block of the system prompt.

    Args:
        doc_data: The current plan document data, or None if no document exists.

    Returns:
        Optional[str]: A formatted text representation of branches/tiles,
                       or None if doc_data is None or has no branches.
    """
    if doc_data is None:
        return None

    # Only include context if there are branches to show
    if not doc_data.branches:
        return None

    lines: List[str] = []

    # Branches with their selections and tile info
    lines.append(f"=== BRANCHES ({len(doc_data.branches)}) ===")
    for branch in doc_data.branches:
        primary_marker = " (PRIMARY)" if branch.is_primary else ""
        lines.append(f"\nBranch: {branch.label}{primary_marker}")
        lines.append(f"  ID: {branch.id}")
        lines.append(f"  Description: {branch.description}")
        if branch.destinations:
            lines.append(f"  Destinations: {', '.join(branch.destinations)}")
        if branch.origin:
            lines.append(f"  Origin: {branch.origin}")
        if branch.start_date:
            lines.append(f"  Dates: {branch.start_date} to {branch.end_date}")
        if branch.adults is not None or branch.children is not None:
            traveler_parts = []
            if branch.adults:
                traveler_parts.append(f"{branch.adults} adult(s)")
            if branch.children:
                traveler_parts.append(f"{branch.children} child(ren)")
            lines.append(f"  Travelers: {', '.join(traveler_parts)}")
            if branch.requires_assistance:
                lines.append("  Requires assistance: Yes")
        if branch.budget is not None:
            currency = branch.currency or getattr(doc_data.trip_inputs, "currency", None)
            currency_part = f" {currency}" if currency else ""
            lines.append(f"  Budget: {branch.budget}{currency_part}")

        # Tiles assigned to this branch
        tiles = branch.tiles
        tile_counts = []
        if tiles.stays:
            tile_counts.append(f"{len(tiles.stays)} stays")
        if tiles.flights:
            tile_counts.append(f"{len(tiles.flights)} flights")
        if tiles.activities:
            tile_counts.append(f"{len(tiles.activities)} activities")
        if tile_counts:
            lines.append(f"  Available Tiles: {', '.join(tile_counts)}")

        # User selections
        sel = branch.selections
        selected_parts = []
        if sel.stay:
            stay_tile = doc_data.tiles.get(sel.stay)
            stay_info = f"{stay_tile.title}" if stay_tile else sel.stay
            selected_parts.append(f"Stay: {stay_info}")
        if sel.flight:
            flight_tile = doc_data.tiles.get(sel.flight)
            flight_info = f"{flight_tile.title}" if flight_tile else sel.flight
            selected_parts.append(f"Flight: {flight_info}")
        if sel.activities:
            activity_names = []
            for act_id in sel.activities:
                act_tile = doc_data.tiles.get(act_id)
                activity_names.append(act_tile.title if act_tile else act_id)
            selected_parts.append(f"Activities: {', '.join(activity_names)}")
        if selected_parts:
            lines.append(f"  USER SELECTIONS: {'; '.join(selected_parts)}")

    # Available tiles (abbreviated)
    if doc_data.tiles:
        lines.append(f"\n=== AVAILABLE TILES ({len(doc_data.tiles)}) ===")
        by_type: dict[str, List[str]] = {"flight": [], "hotel": [], "activity": []}
        for _tile_id, tile in doc_data.tiles.items():
            price_info = ""
            if tile.live_price is not None:
                price_info = f" ({tile.live_price} {tile.currency})"
            elif tile.price_estimate is not None:
                price_info = f" (~{tile.price_estimate} {tile.currency})"
            by_type.setdefault(tile.type, []).append(f"{tile.title}{price_info}")
        for tile_type, tile_list in by_type.items():
            if tile_list:
                lines.append(f"{tile_type.upper()}S: {', '.join(tile_list[:5])}")
                if len(tile_list) > 5:
                    lines.append(f"  ... and {len(tile_list) - 5} more")

    return "\n".join(lines)


# =============================================================================
# MODEL CONFIGURATION
# =============================================================================


def _plan_model_name() -> str:
    """
    Get the OpenAI model name from environment configuration.

    The model name MUST be explicitly set via the OPENAI_PLAN_MODEL environment
    variable. This is intentional to prevent accidental use of expensive models
    and to ensure conscious model selection.

    Returns:
        str: The model name (e.g., "gpt-4-turbo", "gpt-4o")

    Raises:
        RuntimeError: If OPENAI_PLAN_MODEL is not set or is empty.

    Example:
        OPENAI_PLAN_MODEL=gpt-4-turbo-preview
    """

    model_name = os.getenv("OPENAI_PLAN_MODEL", "").strip()
    if not model_name:
        raise RuntimeError("OPENAI_PLAN_MODEL is required for planning")
    return model_name


# =============================================================================
# LLM RESPONSE PARSING UTILITIES
# =============================================================================


def _coerce_delta_content(delta_content: Any) -> str:
    """
    Convert various OpenAI response content formats to a plain string.

    OpenAI's API can return content in multiple formats depending on the model,
    streaming mode, and response_format settings. This function handles all known
    variations and normalizes them to a simple string.

    Supported formats:
    - str: Returned as-is
    - list: Recursively processed and concatenated
    - dict: Extracts text/json/value/content fields
    - Objects with .text attribute: Extracts the text value

    Args:
        delta_content: The content from an OpenAI response choice, which could
                       be a string, list, dict, or custom object.

    Returns:
        str: The extracted text content, or str(delta_content) as fallback.
    """
    if delta_content is None:
        return ""

    if isinstance(delta_content, str):
        return delta_content

    if isinstance(delta_content, list):
        parts: List[str] = []
        for entry in delta_content:
            parts.append(_coerce_delta_content(entry))
        return "".join(parts)

    if isinstance(delta_content, dict):
        text_candidate = delta_content.get("text")
        if isinstance(text_candidate, list):
            return "".join(_coerce_delta_content(chunk) for chunk in text_candidate)
        if isinstance(text_candidate, str):
            return text_candidate
        json_candidate = delta_content.get("json")
        if isinstance(json_candidate, dict):
            return json.dumps(json_candidate, ensure_ascii=True)
        value_candidate = delta_content.get("value")
        if isinstance(value_candidate, str):
            return value_candidate
        content_candidate = delta_content.get("content")
        if content_candidate is not None:
            return _coerce_delta_content(content_candidate)

    text_value = getattr(delta_content, "text", None)
    if text_value:
        return str(text_value)

    return str(delta_content)


def _extract_message_payload(choice: Any) -> tuple[Optional[dict], str]:
    """
    Extract structured or raw content from an OpenAI completion choice.

    When using response_format={"type": "json_object"}, OpenAI may return the
    parsed JSON directly in .parsed, or as a string in .content that needs
    parsing. This function tries all known extraction methods.

    Priority order:
    1. choice.message.parsed (structured output, already a dict)
    2. choice.message.content (raw JSON string to be parsed later)
    3. choice.delta.content (streaming format)

    Args:
        choice: A completion choice from OpenAI's response.

    Returns:
        tuple[Optional[dict], str]: A tuple of (structured_payload, raw_content).
            - If structured JSON was found, returns (dict, "")
            - If only raw content was found, returns (None, raw_string)
            - If nothing found, returns (None, "")
    """

    message_obj: Any = getattr(choice, "message", None)
    if message_obj is None and isinstance(choice, dict):
        message_obj = choice.get("message") or choice.get("delta")

    if message_obj is None:
        return None, ""

    parsed_candidate = getattr(message_obj, "parsed", None)
    if isinstance(message_obj, dict) and parsed_candidate is None:
        parsed_candidate = message_obj.get("parsed")
    if isinstance(parsed_candidate, dict):
        return parsed_candidate, ""
    if isinstance(parsed_candidate, list):
        merged: dict[str, Any] = {}
        for entry in parsed_candidate:
            if isinstance(entry, dict):
                merged.update(entry)
        if merged:
            return merged, ""
    if isinstance(parsed_candidate, str):
        return None, parsed_candidate

    content_obj: Any = getattr(message_obj, "content", None)
    if content_obj is None and isinstance(message_obj, dict):
        content_obj = message_obj.get("content")

    if isinstance(content_obj, list):
        for entry in content_obj:
            if isinstance(entry, dict):
                json_payload = entry.get("json")
                if isinstance(json_payload, dict):
                    return json_payload, ""

    raw_content = _coerce_delta_content(content_obj)
    return None, raw_content


def _truncate_to_balanced_json(raw: str) -> Optional[str]:
    """
    Extract a valid JSON object from a potentially truncated or malformed string.

    LLMs sometimes return incomplete JSON (e.g., if they hit token limits) or
    include extra text before/after the JSON. This function finds the first
    complete, balanced JSON object in the string.

    The algorithm:
    1. Finds the first '{' character to start
    2. Tracks brace depth, accounting for strings and escapes
    3. Returns the substring from first '{' to its matching '}'

    Args:
        raw: A string that may contain a JSON object somewhere within it.

    Returns:
        Optional[str]: The extracted balanced JSON string, or None if no valid
                       balanced JSON object could be found.

    Example:
        >>> _truncate_to_balanced_json('Some text {"key": "value"} more text')
        '{"key": "value"}'
        >>> _truncate_to_balanced_json('{"incomplete": "json')
        None
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


def _tolerant_json_loads(raw: str) -> Optional[dict]:
    """
    Parse JSON with multiple fallback strategies for malformed input.

    LLMs don't always produce perfectly valid JSON. This function tries
    progressively more lenient parsing approaches:

    1. Standard json.loads() - works for well-formed JSON
    2. Non-strict mode - allows some escape sequence issues
    3. Truncation recovery - extracts balanced JSON from garbage

    Args:
        raw: A string that should contain JSON, possibly malformed.

    Returns:
        Optional[dict]: The parsed dictionary, or None if parsing failed
                        with all strategies.
    """
    if not raw:
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    try:
        return json.loads(raw, strict=False)
    except Exception:
        pass

    trimmed = _truncate_to_balanced_json(raw)
    if trimmed:
        try:
            return json.loads(trimmed, strict=False)
        except json.JSONDecodeError:
            return None
    return None


# =============================================================================
# INPUT NORMALIZATION AND VALIDATION
# =============================================================================


def _normalize_str(value: Any) -> Optional[str]:
    """
    Convert any value to a trimmed string, returning None for empty values.

    Args:
        value: Any value to convert.

    Returns:
        Optional[str]: The trimmed string, or None if the value was None,
                       became empty after trimming, or equals "null".
    """
    if value is None:
        return None
    value_str = str(value).strip()
    if not value_str or value_str.lower() == "null":
        return None
    return value_str


def _relative_date_to_iso(text: Optional[str]) -> Optional[str]:
    """
    Convert relative date expressions to ISO format dates.

    Handles natural language date expressions that users might type:
    - "today", "tonight", "now" → today's date
    - "tomorrow" → tomorrow's date
    - "next week" → 7 days from now
    - "next month" → 30 days from now
    - "weekend", "next weekend" → upcoming Saturday

    Args:
        text: A relative date expression.

    Returns:
        Optional[str]: The corresponding ISO date (YYYY-MM-DD), or None
                       if the text wasn't recognized as a relative date.

    Example:
        >>> _relative_date_to_iso("next week")  # If today is 2025-01-15
        "2025-01-22"
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
        # Map to upcoming Saturday; if already Sat/Sun with "next", skip to following weekend
        days_until_saturday = (5 - today.weekday()) % 7
        if "next" in lowered and days_until_saturday <= 0:
            days_until_saturday += 7
        return (today + timedelta(days=days_until_saturday)).strftime("%Y-%m-%d")

    return None


def _extract_duration_days_from_message(message: str) -> Optional[int]:
    """
    Extract trip duration in days from user message.

    Looks for patterns like:
    - "coming back in 5 days"
    - "returning in 5 days"
    - "for 5 days"
    - "5 day trip"

    Args:
        message: The user's message text.

    Returns:
        Optional[int]: Number of days if a duration pattern was found, else None.
    """
    if not message:
        return None

    lowered = message.lower()

    # Patterns that indicate duration
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
    """
    Compute end_date from start_date and duration.

    Args:
        start_date: Start date in ISO format (YYYY-MM-DD).
        duration_days: Number of days for the trip.

    Returns:
        Optional[str]: End date in ISO format, or None if computation failed.
    """
    if not start_date or duration_days <= 0:
        return None

    start_dt = _parse_iso_date(start_date)
    if not start_dt:
        return None

    end_dt = start_dt + timedelta(days=duration_days)
    return end_dt.strftime("%Y-%m-%d")


def _normalize_date(value: Any) -> Optional[str]:
    """
    Normalize various date formats to ISO format (YYYY-MM-DD).

    Handles:
    - Relative dates ("tomorrow", "next week", etc.)
    - ISO format: 2025-01-15
    - European format: 15-01-2025 or 15/01/2025

    Args:
        value: A date value (string, or any value that can be str()'d).

    Returns:
        Optional[str]: The normalized ISO date, or None if parsing failed.
    """
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
    """
    Parse an ISO date string to a datetime object.

    Args:
        text: An ISO format date string (YYYY-MM-DD).

    Returns:
        Optional[datetime]: The parsed datetime, or None if parsing failed.
    """
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None


def _normalize_int(value: Any) -> Optional[int]:
    """
    Convert any value to an integer.

    Tries direct int() conversion first, then string parsing.

    Args:
        value: Any value to convert.

    Returns:
        Optional[int]: The integer value, or None if conversion failed.
    """
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
    """
    Normalize a currency value to a supported 3-letter code.

    Maps common symbols and uppercases valid codes. Returns the provided
    default when the value cannot be normalized.
    """
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

    Accepts the explicit enum values ("multi_city"/"separate"), booleans, and
    common phrases like "one trip together" or "separate trips". Returns the
    canonical string or None if no intent can be determined.
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

    # Phrase-based inference (include UI language like "visit both"/"compare destinations")
    separate_phrases = (
        "separate trip",
        "separate trips",
        "separate itineraries",
        "do them separately",
        "each separately",
        "each on their own",
        "different trips",
        "individual trips",
        "their own trip",
        "own trip",
        "own trips",
        "not together",
        "separately",
        "compare destinations",
        "compare the destinations",
        "compare options",
        "compare them",
        "compare cities",
    )
    multi_phrases = (
        "multi city",
        "multicity",
        "multi city trip",
        "one trip",
        "single trip",
        "same trip",
        "together",
        "all together",
        "one itinerary",
        "single itinerary",
        "same itinerary",
        "combined trip",
        "one go",
        "one journey",
        "visit both",
        "visit them both",
        "visit all",
        "see both",
        "do both",
    )

    # Check for explicit separation intent first (unless negated)
    if "not separate" not in normalized:
        for phrase in separate_phrases:
            if phrase in normalized:
                return "separate"

    for phrase in multi_phrases:
        if phrase in normalized:
            return "multi_city"

    return None


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
    if hotel_settings.get("min_stars", 0) and hotel_settings.get("min_stars") > 0:
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


def _clamp_traveler_value(value: Optional[int]) -> Optional[int]:
    """
    Constrain a traveler count (adults or children) to a valid range [0, 20].

    Args:
        value: The traveler count to clamp.

    Returns:
        Optional[int]: The clamped value (0-20), or None if input was None.
    """
    if value is None:
        return None
    return max(0, min(20, value))


def _normalize_booking_field(field: str, raw_value: dict) -> Optional[dict]:
    """
    Normalize a booking preference field from LLM output.

    Validates and normalizes the structure of booking preference objects,
    ensuring types and values are correct.

    Args:
        field: The field name (booking_types, flight_settings, etc.)
        raw_value: The raw dict from LLM response.

    Returns:
        Optional[dict]: Normalized dict with valid fields only, or None if invalid.
    """
    if not isinstance(raw_value, dict):
        return None

    if field == "booking_types":
        # BookingTypes: hotels, flights, ground_transport, activities (all bool)
        result = {}
        for key in ("hotels", "flights", "ground_transport", "activities"):
            if key in raw_value and isinstance(raw_value[key], bool):
                result[key] = raw_value[key]
        return result if result else None

    if field == "flight_settings":
        # FlightSettings: round_trip (bool), cabin_class (str), direct_only (bool)
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
        # HotelSettings: min_stars (int 0-5), amenities (list of str)
        result = {}
        if "min_stars" in raw_value:
            stars = _normalize_int(raw_value["min_stars"])
            if stars is not None:
                result["min_stars"] = max(0, min(5, stars))
        if "amenities" in raw_value:
            amenities = raw_value["amenities"]
            if isinstance(amenities, list):
                result["amenities"] = [
                    _normalize_str(a).lower() for a in amenities if a and _normalize_str(a)
                ]
        return result if result else None

    if field == "activity_settings":
        # ActivitySettings: categories (list of str)
        # Activities can be user-added custom entries or emoji-prefixed themes
        result = {}
        if "categories" in raw_value:
            categories = raw_value["categories"]
            if isinstance(categories, list):
                normalized_categories = []
                for cat in categories:
                    cat_str = _normalize_str(cat)
                    if not cat_str:
                        continue
                    # Normalize activity with emoji prefix
                    cat_with_emoji = _normalize_activity_with_emoji(cat_str)
                    normalized_categories.append(cat_with_emoji)
                if normalized_categories:
                    # Deduplicate case-insensitively (compares text portion only)
                    deduped = _deduplicate_activities_case_insensitive(normalized_categories)
                    result["categories"] = deduped
        return result if result else None

    if field == "transport_settings":
        # TransportSettings: car, train, bus (all bool)
        result = {}
        for key in ("car", "train", "bus"):
            if key in raw_value and isinstance(raw_value[key], bool):
                result[key] = raw_value[key]
        return result if result else None

    return None


def _normalize_branch_spec(spec: dict, fallback_inputs: dict) -> Optional[dict]:
    """
    Normalize a branch specification from LLM output.

    Applies consistent normalization to all branch fields and fills in
    missing values from fallback_inputs (the canonical trip inputs).

    Args:
        spec: Raw branch dict from LLM with label, description, destinations, etc.
        fallback_inputs: Canonical trip inputs to use for missing values.

    Returns:
        Optional[dict]: Normalized branch dict, or None if branch is invalid
                        (missing required fields like destinations).
    """
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


def _compute_missing_fields(trip_inputs: dict) -> List[str]:
    """
    Compute the list of missing REQUIRED trip input fields in canonical order.

    Only checks the 4 required fields: destinations, origin, start_date, end_date.
    Optional fields (adults, children, requires_assistance, budget) are not included.

    Args:
        trip_inputs: A dictionary of trip input values.

    Returns:
        List[str]: Field names that are None/empty, in collection order.
    """
    missing = []
    for field in _REQUIRED_TRIP_INPUT_FIELDS:
        if field == "destinations":
            val = trip_inputs.get(field, [])
            if not val or (isinstance(val, list) and len(val) == 0):
                missing.append(field)
        elif trip_inputs.get(field) is None:
            missing.append(field)
    return missing


def _validate_trip_inputs(trip_inputs: dict, *, today_iso: str) -> tuple[dict, List[str]]:
    """
    Validate trip inputs and generate user-facing messages for issues.

    Performs semantic validation that goes beyond type normalization:
    - Ensures end_date is after start_date (auto-corrects if needed)
    - Warns about past dates
    - Clamps traveler count to valid range (1-20)
    - Rejects negative budgets

    This function modifies trip_inputs in place and returns validation messages
    that should be shown to the user. If validation_messages is non-empty,
    branch generation should be deferred until the user confirms.

    Args:
        trip_inputs: The trip inputs dictionary (modified in place).
        today_iso: Today's date in ISO format for past-date detection.

    Returns:
        tuple[dict, List[str]]: The modified trip_inputs and a list of
            validation messages to show the user.

    Example:
        >>> inputs = {"start_date": "2025-01-20", "end_date": "2025-01-15"}
        >>> _validate_trip_inputs(inputs, today_iso="2025-01-10")
        ({"start_date": "2025-01-15", "end_date": "2025-01-20", ...},
         ["I reordered your dates so the trip starts before it ends..."])
    """
    validation_messages: List[str] = []
    today_dt = _parse_iso_date(today_iso)

    start_dt = _parse_iso_date(trip_inputs.get("start_date"))
    end_dt = _parse_iso_date(trip_inputs.get("end_date"))

    if start_dt and end_dt and end_dt < start_dt:
        earliest = min(start_dt, end_dt)
        latest = max(start_dt, end_dt)
        trip_inputs["start_date"] = earliest.strftime("%Y-%m-%d")
        trip_inputs["end_date"] = latest.strftime("%Y-%m-%d")
        validation_messages.append(
            "I reordered your dates so the trip starts before it ends. Does that look right?"
        )
        start_dt = earliest
        end_dt = latest

    if start_dt and today_dt and start_dt < today_dt:
        validation_messages.append("The start date is in the past. Want to update it?")
    if end_dt and today_dt and end_dt < today_dt:
        validation_messages.append("The end date is in the past. Want to update it?")

    # Validate adults and children counts
    adults = _normalize_int(trip_inputs.get("adults"))
    if adults is not None:
        trip_inputs["adults"] = adults  # Ensure it's stored as int
        clamped_adults = _clamp_traveler_value(adults)
        if adults < 0:
            validation_messages.append(
                f"Adults count cannot be negative. I set it to {clamped_adults}."
            )
        if adults != clamped_adults:
            trip_inputs["adults"] = clamped_adults

    children = _normalize_int(trip_inputs.get("children"))
    if children is not None:
        trip_inputs["children"] = children  # Ensure it's stored as int
        clamped_children = _clamp_traveler_value(children)
        if children < 0:
            validation_messages.append(
                f"Children count cannot be negative. I set it to {clamped_children}."
            )
        if children != clamped_children:
            trip_inputs["children"] = clamped_children

    # Ensure requires_assistance is a boolean if present
    requires_assistance = trip_inputs.get("requires_assistance")
    if requires_assistance is not None and not isinstance(requires_assistance, bool):
        trip_inputs["requires_assistance"] = None

    budget_value = _normalize_int(trip_inputs.get("budget"))
    if budget_value is not None:
        trip_inputs["budget"] = budget_value  # Ensure it's stored as int
        if budget_value < 0:
            trip_inputs["budget"] = None
            validation_messages.append(
                "Budget must be zero or higher. Please share an updated budget."
            )

    raw_currency = trip_inputs.get("currency")
    normalized_currency = _normalize_currency(raw_currency)
    if normalized_currency is None:
        normalized_currency = DEFAULT_CURRENCY
        if raw_currency not in (None, "", DEFAULT_CURRENCY):
            validation_messages.append(f"I set the currency to {normalized_currency}.")
    trip_inputs["currency"] = normalized_currency

    trip_inputs["missing_fields"] = _compute_missing_fields(trip_inputs)
    return trip_inputs, validation_messages


def _default_follow_up_question(missing_fields: List[str]) -> Optional[str]:
    """
    Get the default question to ask for the next missing field.

    Used as a fallback when the LLM doesn't provide an assistant_message.
    Returns a pre-defined question based on the first missing field in
    the canonical collection order.

    Args:
        missing_fields: List of field names that still need to be collected.

    Returns:
        Optional[str]: A question to ask the user, or None if no fields are missing.
    """
    if not missing_fields:
        return None

    prompt_by_field = {
        "destinations": "Where would you like to go?",
        "origin": "Where will you be traveling from?",
        "start_date": "When does your trip start?",
        "end_date": "When does your trip end?",
        "adults": "How many adults will be going?",
        "budget": "What's your budget for this trip?",
    }

    for field in _REQUIRED_TRIP_INPUT_FIELDS:
        if field in missing_fields:
            return prompt_by_field.get(field)
    return None


# =============================================================================
# CHAT HISTORY CONVERSION
# =============================================================================


def _history_to_messages(history: List[models.ChatMessage]) -> List[ChatCompletionMessageParam]:
    """
    Convert database ChatMessage objects to OpenAI message format.

    Filters out empty messages (e.g., unfilled assistant placeholders that
    haven't been updated yet).

    Args:
        history: List of ChatMessage database objects.

    Returns:
        List[ChatCompletionMessageParam]: Messages in OpenAI API format.
    """
    messages: List[ChatCompletionMessageParam] = []
    for entry in history:
        content = entry.content or ""
        # Skip empty messages (e.g., unfilled assistant placeholders)
        if not content.strip():
            continue
        messages.append(cast(ChatCompletionMessageParam, {"role": entry.role, "content": content}))
    return messages


# =============================================================================
# TRIP CONTEXT RESOLUTION
# =============================================================================


def _resolve_parent_trip_context(
    db: Session,
    *,
    session: models.Session,
    requested_parent_id: Optional[int],
) -> Optional[models.TripContext]:
    """
    Resolve the parent TripContext for the current planning request.

    TripContext forms a chain of conversation snapshots. This function either:
    1. Uses a specific parent context (if requested_parent_id is provided)
    2. Falls back to the most recent context for this session

    The parent context provides continuity between planning turns.

    Args:
        db: Database session.
        session: The user's session model.
        requested_parent_id: Optional specific context ID to use as parent.

    Returns:
        Optional[models.TripContext]: The parent context, or None for first message.

    Raises:
        ValueError: If requested_parent_id doesn't exist or belongs to another session.
    """
    parent_ctx: Optional[models.TripContext] = None

    if requested_parent_id is not None:
        parent_ctx = db.get(models.TripContext, requested_parent_id)
        if not parent_ctx:
            raise ValueError("trip_context_id not found")
        if parent_ctx.session_id != session.id:
            raise ValueError("trip_context_id does not belong to this session")
        return parent_ctx

    return get_latest_trip_context_for_session(db, session=session)


# =============================================================================
# GENERATE PLAN TRIGGER DETECTION
# =============================================================================

# Special message that the frontend sends when user clicks "Generate Plan"
_GENERATE_PLAN_TRIGGER = "GENERATE_PLAN_NOW"


def _is_generate_plan_trigger(message: str) -> bool:
    """Check if the user's message is the 'Generate Plan' button trigger."""
    return message.strip() == _GENERATE_PLAN_TRIGGER


# =============================================================================
# MAIN LLM PLANNING FUNCTION
# =============================================================================


def _call_openai_for_plan(
    req: PlanRequest,
    *,
    history: List[ChatCompletionMessageParam],
    document_data: Optional[PlanDocumentData] = None,
    timezone: Optional[str] = None,
) -> PlannerLLMOutput:
    """
    Call OpenAI to process a user message and generate planning output.

    Uses a single unified prompt that:
    - Receives full document state and chat history
    - Extracts all trip fields from user messages
    - Generates branches when all required fields are complete
    - Updates trip_inputs on every response

    Args:
        req: The plan request containing the user's message.
        history: Processed message history in OpenAI format.
        document_data: Current PlanDocument state (source of truth).
        timezone: Optional IANA timezone name for calculating "today".

    Returns:
        PlannerLLMOutput: Structured output containing branches, message, and trip_inputs.

    Raises:
        RuntimeError: If OpenAI client is not configured or call fails after retries.
    """
    # Document is the single source of truth for trip inputs
    current_trip_inputs: dict = {}
    if document_data and document_data.trip_inputs:
        ti = document_data.trip_inputs
        current_trip_inputs = {
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
            # Booking preferences
            "booking_types": (
                ti.booking_types.model_dump() if ti.booking_types else dict(DEFAULT_BOOKING_TYPES)
            ),
            "flight_settings": ti.flight_settings.model_dump() if ti.flight_settings else None,
            "hotel_settings": ti.hotel_settings.model_dump() if ti.hotel_settings else None,
            "activity_settings": (
                ti.activity_settings.model_dump() if ti.activity_settings else None
            ),
            "transport_settings": (
                ti.transport_settings.model_dump() if ti.transport_settings else None
            ),
        }
    else:
        # Initialize empty state
        current_trip_inputs = {
            "destinations": [],
            "origin": None,
            "start_date": None,
            "end_date": None,
            "adults": None,
            "children": None,
            "requires_assistance": None,
            "budget": None,
            "currency": DEFAULT_CURRENCY,
            "multi_city_intent": None,
            # Booking preferences - initialize as None (will use schema defaults)
            "booking_types": dict(DEFAULT_BOOKING_TYPES),
            "flight_settings": None,
            "hotel_settings": None,
            "activity_settings": None,
            "transport_settings": None,
        }

    today = _today_iso(timezone)

    # Check if this is a generate plan trigger
    is_generate_trigger = _is_generate_plan_trigger(req.message)

    # Check if we already have branches
    has_existing_branches = bool(document_data and document_data.branches)

    # Check if all required fields are complete BEFORE calling LLM
    pre_check_missing = _compute_missing_fields(current_trip_inputs)

    # DEBUG (1/3): Before LLM - current state + missing fields + message history
    if _DEBUG_LOG:
        print("[DEBUG] === BEFORE LLM ===")
        print(f"[DEBUG] Current trip_inputs: {json.dumps(current_trip_inputs, indent=2)}")
        print(f"[DEBUG] Missing fields: {pre_check_missing}")
        print(f"[DEBUG] Has branches: {has_existing_branches}, Is generate: {is_generate_trigger}")
        print("[DEBUG] === MESSAGE HISTORY ===")
        for msg in history:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            # Truncate long messages for readability
            display_content = content[:300] + "..." if len(content) > 300 else content
            print(f"[DEBUG] [{role.upper()}]: {display_content}")
        # Show the current user message being sent
        print(f"[DEBUG] [USER (current)]: {req.message}")
        print("=" * 80)

    # REMOVED: Early return when all fields complete
    # We ALWAYS call the LLM so users can modify their inputs at any time.
    # The only exception is the generate trigger which explicitly requests branch generation.

    # Build current state as JSON for the prompt (include ALL fields including destinations)
    current_state_json = json.dumps(current_trip_inputs, indent=2)

    # Single unified system prompt - optimized for token efficiency and conversational UX
    system_prompt = f"""You are a friendly, knowledgeable travel agent. Today is {today}.
Respond with valid JSON only. Be warm but concise.
Start assistant_message with a context-appropriate emoji:
    🏛️ history/culture, 🏖️ beach, 🗼 landmarks,
    ✈️ flights, 🏨 hotels, 📅 dates, 👨‍👩‍👧 travelers,
    💰 budget, 🎉 ready state. Default ✨ only if nothing fits.

STATE: {current_state_json}

==============================
DOCUMENT EDITING
==============================
- STATE is the JSON CRUD document—update ANY trip_inputs field or sub-field when the user asks.
- Use JSON keys even if the user references UI labels; map them with FIELD MAP.

==============================
JSON STRICTNESS
==============================
- Never include fields with null unless explicitly set by the user; otherwise omit.
- Dates must be ISO 8601 YYYY-MM-DD.
- If input dates are ambiguous or non-ISO, ask for confirmation before writing.
- Do not invent prices, availability, or live inventory. Use ranges only when discussing costs.

==============================
REALITY & FEASIBILITY CHECK (APPLY BEFORE WRITING STATE)
==============================
- Validate user intent against:
  1) Geography (landlocked vs beach, distance, borders)
  2) Seasonality (skiing vs summer, monsoon, extreme heat/cold)
  3) Transit feasibility (same-day intercontinental trips, excessive daily travel)
- If infeasible or contradictory:
  - Pause extraction for affected fields
  - Explain the issue briefly
  - Propose 1–2 realistic alternatives (prefer nearby or similar experiences)
  - Ask ONE corrective or confirmatory question
- Use this correction template:
  "Notice: {{issue}}. Because {{reason}}. Options: {{A}}, {{B}}. Which should I apply?"
- Prefer correction over silent acceptance.

==============================
FIELD MAP (UI → JSON KEYS)
==============================
- "From"→origin
- "Where to"→destinations[]
- "Dates"→start_date / end_date
- "How to visit"→multi_city_intent ("multi_city"=visit together, "separate"=compare)
- "Travelers"→adults, children, requires_assistance
- "Budget"→budget, currency
- "Flights"→booking_types.flights + flight_settings.round_trip / direct_only / cabin_class
- "Transport"→booking_types.ground_transport + transport_settings.car / train / bus
- "Hotels"→booking_types.hotels + hotel_settings.min_stars / amenities[]
- "Activities"→booking_types.activities + activity_settings.categories[]

==============================
SYNONYM NORMALIZATION
==============================
- nonstop → flight_settings.direct_only=true
- one way / one-way → flight_settings.round_trip=false
- premium economy / economy+ → flight_settings.cabin_class="premium_economy"
- snorkeling / scuba → 🤿 diving
- clubbing / night out → 🎭 nightlife
- trail running → 🏃 running

==============================
PERSONA
==============================
- Enthusiastic about travel, patient with questions
- Greetings → respond warmly, ask where they'd like to go
- Thanks/appreciation → "Happy to help! [next step]"
- Off-topic → gently redirect: "I'd love to help plan your trip! Where to?"
- Confusion → clarify: "Just to make sure I understand..."
- Celebrate exciting destinations briefly: "Barcelona—great choice!"

==============================
EXTRACTION RULES
==============================
- Set trip_inputs for ANY location mentioned.

| Pattern | Fields |
|--------|--------|
| "from X to Y" | origin=X, destinations=[Y] |
| "to Y from X" | origin=X, destinations=[Y] |
| "X and Y" (no from) | destinations=[X,Y] |
| solo / just me | adults=1 |
| couple / me and partner | adults=2 |
| family of N | adults=2, children=N-2 |
| N adults, M kids | adults=N, children=M |
| wheelchair / accessibility | requires_assistance=true |
| $N / €N / £N | budget=N, currency=USD/EUR/GBP |
| "leaving today, not sure when back" | start_date={today}, end_date=null |

==============================
DURATION CONSTRAINT
==============================
- If user says "for N days" without a start or end date:
  - Do NOT compute dates
  - Store trip_constraints.duration_days = N
  - Ask whether to anchor by start date or end date
- Resolve duration_days automatically once one date is provided
- Omit trip_constraints from output if empty

==============================
DESTINATION REFINEMENT
==============================
- If user specifies a city/region inside an existing country destination, REPLACE the country.
- Preserve order of mention.
- More specific locations supersede broader ones.

==============================
DATE HANDLING & SANITY
==============================
- Dates must be YYYY-MM-DD
- If end_date < start_date:
  - Ask whether to swap or confirm cross-year intent
- Accept valid cross-year ranges (e.g. Dec 28–Jan 3)
- If dates overlap major holidays, briefly note crowds or price surges

==============================
MULTI-DESTINATION LOGIC
==============================
- Default: separate trips
- multi_city_intent="multi_city" when user says:
  "one trip", "multi-city", "together", "visit both/all"
- multi_city_intent="separate" when user says:
  "compare destinations", "separate trips"
- Never ask about this unless correcting or confirming

==============================
ACTIVITIES
==============================
- Always preserve existing categories
- Append new activities, never replace
- Split compound activities into separate entries
- ALWAYS prefix with an emoji (use ✨ if none fits)
- Deduplicate case-insensitively

Common mappings:
🏖️ beach, 💕 romantic, 🧗 adventure, 👨‍👩‍👧 family,
🍝 food, 🍷 wine, 🏛️ culture, 📜 history,
💆 spa, 😌 relaxation, 🥾 hiking,
🏎️ f1, 🤿 diving, ⛷️ skiing,
🎭 nightlife, 🏃 running, 🎒 backpacking

==============================
BOOKING PREFERENCES
==============================
Extract only when mentioned.

- booking_types:
  "need hotels"→hotels:true
  "need flights"→flights:true
  "book activities"→activities:true
  "I'll drive"→flights:false, ground_transport:true

- flight_settings:
  "business class"→cabin_class:"business"
  "direct only"→direct_only:true
  "one-way"→round_trip:false

- hotel_settings:
  "5-star"→min_stars:5
  "need pool"→amenities:["pool"]

- transport_settings:
  "rent car"→car:true
  "take the train"→train:true
  "bus it"→bus:true

==============================
CATEGORY LOCKING
==============================
- When a booking category is activated, prioritize completing it before switching topics
  unless REQUIRED fields are missing.

CATEGORY COMPLETION THRESHOLDS:
- Flights complete when: round_trip, cabin_class, direct_only known
- Hotels complete when: min_stars OR at least one amenity known
- Transport complete when: one of car/train/bus chosen
- Ask at most ONE follow-up per turn within a category

==============================
BUDGET CONSISTENCY CHECK
==============================
- If estimated budget per person per day < 80 EUR AND
  (hotel_settings.min_stars ≥ 5 OR flight_settings.cabin_class in ["business","first"]):
  - Surface a single-sentence affordability warning
  - Ask which to adjust (budget, hotel stars, or cabin)
- Do not auto-change values

==============================
UPDATES & ACKNOWLEDGEMENTS
==============================
- Acknowledge only when a value actually changes
- "Add X"→append destinations
- "Remove X"→remove destinations
- "Actually N adults"→update adults
- "Make it $X"→update budget
- Booking edits flip the corresponding booking_types toggle on

==============================
CONVERSATION FLOW
==============================
1. Extract what the user provides
2. Briefly acknowledge updates
3. Determine NEXT BEST ACTION using tie-breaker:
   1) Missing REQUIRED fields
   2) Active category core fields
   3) Contradictions / feasibility issues
   4) High-variance decisions (dates, budget)
   5) Optional preferences
4. Ask at most ONE question per turn
5. Use natural phrasing, not checklists

==============================
MICRO-SUMMARIES
==============================
- When a REQUIRED field is completed or a category finishes core fields,
  append a one-line factual summary (≤ 8 words)
  Example: "Locked in: round trip, business, nonstop"

==============================
CONFLICT RESOLUTION
==============================
- New info overrides old after confirmation
- Numeric sanity checks (adults ≥1, children ≥0)
- If traveler mix changes and activities include "romantic", ask whether to keep it

==============================
READY STATE
==============================
- REQUIRED fields: destinations, origin, start_date
- When all complete → ready_to_generate=true
- If no booking prefs set yet, ask ONE guiding question before suggesting Generate
- When ready: keep message short and excited

==============================
BRANCHING (ONLY ON GENERATE TRIGGER)
==============================
- multi_city → single branch with all destinations
- separate/null → one branch per destination
- If no budget, estimate ~$200/day/person mid-range and note assumption

==============================
OUTPUT (JSON ONLY)
==============================
{{
  "assistant_message": "...",
  "trip_inputs": {{}},  // include only trip input fields you set or update this turn
  "ready_to_generate": false,
  "branches": [],
  "suggested_responses": []
}}

==============================
SUGGESTED_RESPONSES RULES
==============================
- 0–3 statements the USER might say next
- NEVER questions, NEVER question marks
- 2–6 words each
- Deduplicate case-insensitively
- No punctuation except commas
- Priority:
  1) Answer your last question
  2) Complete REQUIRED fields
  3) Move planning forward
- If unsure, return []

==============================
SELF-CHECK BEFORE RESPONDING
==============================
- JSON valid
- No null fields unless explicit
- ≤ 1 question asked
- Feasibility corrections applied when needed

==============================
OMISSIONS
==============================
- Omit unchanged fields
- Backend computes missing_fields—do not include it

==============================
BRANCH FORMAT
==============================
{{
  label,
  description,
  destinations[],
  origin,
  start_date,
  end_date,
  adults,
  children,
  requires_assistance,
  budget,
  currency
}}
"""

    client = get_openai_client()
    if client is None:
        raise RuntimeError("OpenAI client is not configured")

    last_error: Exception | None = None

    history_messages: List[ChatCompletionMessageParam] = list(history)

    # Serialize branches/tiles for LLM context (trip_inputs already in CURRENT STATE)
    document_context = _serialize_document_for_llm(document_data)

    messages: List[ChatCompletionMessageParam] = [
        cast(ChatCompletionMessageParam, {"role": "system", "content": system_prompt})
    ]
    # Inject branches/tiles context if available (for generating/refining branches)
    if document_context:
        messages.append(
            cast(
                ChatCompletionMessageParam,
                {
                    "role": "system",
                    "content": f"[EXISTING BRANCHES AND TILES]\n{document_context}",
                },
            )
        )
    messages.extend(history_messages)
    messages.append(cast(ChatCompletionMessageParam, {"role": "user", "content": req.message}))

    model_name = _plan_model_name()
    seed_value: Optional[int] = None
    if _PLAN_SEED is not None:
        try:
            seed_value = int(_PLAN_SEED)
        except ValueError:
            seed_value = None

    def _create_completion_request():
        """Build and execute the OpenAI completion request with model-specific params."""
        model_lower = model_name.lower()

        # Base parameters common to all models - enforce JSON output
        base_params: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }

        if seed_value is not None:
            base_params["seed"] = seed_value

        # GPT-4 models: use max_tokens, temperature, top_p
        if "gpt-4" in model_lower:
            params = {
                **base_params,
                "max_tokens": _MAX_TOKENS,
                "temperature": _PLAN_TEMPERATURE,
                "top_p": _PLAN_TOP_P,
            }
        else:
            # All other models: use max_completion_tokens
            params = {
                **base_params,
                "max_completion_tokens": _MAX_TOKENS,
            }

        result = client.chat.completions.create(**params)
        return result

    def _invoke_with_retries():
        """Execute the completion request with exponential backoff retry logic."""
        nonlocal last_error
        retry_limit = max(1, _PLAN_MAX_RETRIES)
        backoff = 0.5
        for attempt in range(retry_limit):
            try:
                result = _create_completion_request()
                if result is None:
                    raise RuntimeError("OpenAI completion request returned None")
                last_error = None
                return result
            except Exception as exc:
                last_error = exc
                status_code = getattr(exc, "status_code", None) or getattr(exc, "status", None)
                if attempt < _PLAN_MAX_RETRIES - 1 and (
                    status_code == 429 or (isinstance(status_code, int) and status_code >= 500)
                ):
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise
        raise RuntimeError("OpenAI planning call exhausted retries")

    completion = None
    try:
        completion = _invoke_with_retries()
    except Exception as exc:
        last_error = exc

    if completion is not None:
        raw_content = ""
        structured_payload: Optional[dict] = None
        choice = None
        try:
            choice = completion.choices[0] if completion and completion.choices else None
            if choice is not None:
                structured_payload, raw_content = _extract_message_payload(choice)
        except Exception:
            raw_content = ""

        default_assistant_message = "I'm having trouble processing that. Could you try again?"

        data = structured_payload or _tolerant_json_loads(raw_content or "")

        # DEBUG (2/3): After LLM - raw response + parsed data
        if _DEBUG_LOG:
            print("[DEBUG] === AFTER LLM ===")
            if raw_content:
                print(f"[DEBUG] Raw response: {raw_content[:500]}...")
            elif structured_payload:
                print(f"[DEBUG] Structured response: {json.dumps(structured_payload)[:500]}...")
            print(f"[DEBUG] Parsed data: {data}")
            print("=" * 80)

        if data is None:
            # LLM returned plain text instead of JSON - use the raw text as the message
            # This is a fallback to at least show the user something meaningful
            fallback_message = raw_content.strip() if raw_content else default_assistant_message
            # Truncate if too long
            if len(fallback_message) > 500:
                fallback_message = fallback_message[:497] + "..."
            data = {
                "branches": [],
                "assistant_message": fallback_message,
                "trip_inputs": {},
            }
        if not isinstance(data, dict):
            data = {}

        # Handle edge case: LLM returned a single branch object at root level
        # instead of the expected structure with branches array
        if "label" in data and "branches" not in data:
            single_branch = {
                "label": data.get("label"),
                "description": data.get("description", ""),
                "destinations": data.get("destinations", []),
                "origin": data.get("origin"),
                "start_date": data.get("start_date"),
                "end_date": data.get("end_date"),
                "adults": data.get("adults"),
                "children": data.get("children"),
                "requires_assistance": data.get("requires_assistance"),
                "budget": data.get("budget"),
                "currency": data.get("currency"),
            }
            data = {
                "branches": [single_branch],
                "assistant_message": data.get("assistant_message", "Here's your trip plan!"),
                "trip_inputs": data.get("trip_inputs", {}),
            }

        branches_raw = data.get("branches", []) or []

        # CRITICAL SAFEGUARD: Only accept branches from LLM if:
        # 1. This is an explicit generate trigger (user clicked "Generate Plan"), OR
        # 2. Branches already exist (user is refining their plan)
        # This prevents the LLM from auto-generating branches when all fields are complete
        if branches_raw and not is_generate_trigger and not has_existing_branches:
            branches_raw = []

        assistant_message = str(data.get("assistant_message") or "").strip()

        # Parse suggested responses (0-3 quick reply options)
        # These must be user statements, never questions
        suggested_responses_raw = data.get("suggested_responses") or []
        if not isinstance(suggested_responses_raw, list):
            suggested_responses_raw = []
        suggested_responses = []
        for s in suggested_responses_raw[:3]:
            if isinstance(s, dict):
                # Handle if LLM returns objects instead of strings
                text = s.get("content") or s.get("text") or ""
            else:
                text = str(s) if s else ""
            text = text.strip()
            # Reject questions - suggestions must be user statements, not assistant questions
            if text and "?" not in text:
                suggested_responses.append(text)

        trip_inputs_payload = data.get("trip_inputs") or {}

        # Normalize LLM response fields and merge with current state
        # The LLM can overwrite any field - users can correct values via chat
        normalized_llm_response: dict = {}
        for field in _TRIP_INPUT_FIELDS:
            if field not in trip_inputs_payload:
                continue
            raw_value = trip_inputs_payload.get(field)
            if field == "destinations":
                dest_list = (
                    raw_value if isinstance(raw_value, list) else ([raw_value] if raw_value else [])
                )
                normalized_llm_response["destinations"] = [
                    _normalize_str(d) for d in dest_list if d and _normalize_str(d)
                ]
            elif field in ("start_date", "end_date"):
                normalized_llm_response[field] = _normalize_date(raw_value)
            elif field in ("adults", "children", "budget"):
                normalized_llm_response[field] = _normalize_int(raw_value)
            elif field == "currency":
                normalized_llm_response[field] = _normalize_currency(raw_value)
            elif field == "requires_assistance":
                if isinstance(raw_value, bool):
                    normalized_llm_response[field] = raw_value
                elif isinstance(raw_value, str):
                    normalized_llm_response[field] = raw_value.lower() in ("true", "yes", "1")
            elif field == "multi_city_intent":
                normalized_value = _normalize_multi_city_intent(raw_value)
                if normalized_value:
                    normalized_llm_response[field] = normalized_value
            else:
                normalized_llm_response[field] = _normalize_str(raw_value)

        # Normalize booking preference fields (nested objects)
        for field in _BOOKING_PREFERENCE_FIELDS:
            if field not in trip_inputs_payload:
                continue
            raw_value = trip_inputs_payload.get(field)
            if not isinstance(raw_value, dict):
                continue
            normalized_llm_response[field] = _normalize_booking_field(field, raw_value)

        # Merge LLM response with current state (LLM can overwrite)
        trip_inputs = dict(current_trip_inputs)
        for field, value in normalized_llm_response.items():
            if field == "destinations":
                # For arrays, only update if LLM provided non-empty list
                if value:
                    trip_inputs[field] = value
            elif field in _BOOKING_PREFERENCE_FIELDS:
                # For booking preferences, merge nested dicts to support partial updates
                if value:
                    existing = trip_inputs.get(field)
                    if isinstance(existing, dict):
                        # Special handling for activity_settings:
                        # append categories instead of replacing
                        if field == "activity_settings" and "categories" in value:
                            existing_cats = existing.get("categories", [])
                            new_cats = value.get("categories", [])
                            # Merge lists, deduping case-insensitively while preserving order
                            merged_cats = list(existing_cats)
                            seen_lower = {c.lower() for c in existing_cats}
                            for cat in new_cats:
                                if cat.lower() not in seen_lower:
                                    merged_cats.append(cat)
                                    seen_lower.add(cat.lower())
                            trip_inputs[field] = {**existing, **value, "categories": merged_cats}
                        else:
                            # Merge: new values override existing
                            trip_inputs[field] = {**existing, **value}
                    else:
                        trip_inputs[field] = value
            else:
                # For scalars, update if LLM provided non-None value
                if value is not None:
                    trip_inputs[field] = value

        # Ensure booking_types exists and flip the relevant toggles on when sub-settings are present
        booking_types = _ensure_booking_types(trip_inputs)
        if _should_enable_booking_for_flights(trip_inputs.get("flight_settings")):
            booking_types["flights"] = True
        if _should_enable_booking_for_hotels(trip_inputs.get("hotel_settings")):
            booking_types["hotels"] = True
        if _should_enable_booking_for_transport(trip_inputs.get("transport_settings")):
            booking_types["ground_transport"] = True
        if _should_enable_booking_for_activities(trip_inputs.get("activity_settings")):
            booking_types["activities"] = True

        # Fallback: infer "How to visit" intent directly from the latest user message
        # if the LLM didn't return a value. This helps capture chats like
        # "let's do it all in one trip" or "make them separate trips".
        if not trip_inputs.get("multi_city_intent"):
            destinations = trip_inputs.get("destinations") or []
            if len(destinations) >= 2:
                inferred_intent = _normalize_multi_city_intent(req.message)
                if inferred_intent:
                    trip_inputs["multi_city_intent"] = inferred_intent

        # FALLBACK: If LLM failed to compute end_date from duration, do it ourselves
        if trip_inputs.get("start_date") and not trip_inputs.get("end_date"):
            duration_days = _extract_duration_days_from_message(req.message)
            if duration_days:
                computed_end = _compute_end_date_from_duration(
                    trip_inputs["start_date"], duration_days
                )
                if computed_end:
                    trip_inputs["end_date"] = computed_end

        trip_inputs, validation_messages = _validate_trip_inputs(trip_inputs, today_iso=today)
        parsed_missing_fields = trip_inputs.get("missing_fields") or []

        has_all_fields = len(parsed_missing_fields) == 0 and not validation_messages

        cleaned: List[dict] = []
        canonical_inputs = {field: trip_inputs.get(field) for field in _TRIP_INPUT_FIELDS}

        if has_all_fields and branches_raw:
            for b in branches_raw:
                normalized = _normalize_branch_spec(b, canonical_inputs)
                if normalized:
                    cleaned.append(normalized)

            # Post-processing: Split branches with multiple destinations when NOT multi_city
            # Default behavior (null/missing/"separate"): each destination gets its own branch
            multi_city_intent = canonical_inputs.get("multi_city_intent")
            if multi_city_intent != "multi_city" and cleaned:
                split_branches: List[dict] = []
                for branch in cleaned:
                    branch_dests = branch.get("destinations", [])
                    if len(branch_dests) > 1:
                        # Split this branch into multiple branches, one per destination
                        original_label = branch.get("label", "")
                        for dest in branch_dests:
                            # Preserve label style: "Paris Adventure" -> "Rome Adventure"
                            # If original has destination in it, replace; otherwise prefix
                            split_label = f"{dest} Trip"
                            for orig_dest in branch_dests:
                                if orig_dest.lower() in original_label.lower():
                                    split_label = original_label.replace(orig_dest, dest)
                                    break
                            split_branches.append(
                                {
                                    "label": split_label,
                                    "description": branch.get("description", ""),
                                    "destinations": [dest],
                                    "origin": branch.get("origin"),
                                    "start_date": branch.get("start_date"),
                                    "end_date": branch.get("end_date"),
                                    "adults": branch.get("adults"),
                                    "children": branch.get("children"),
                                    "requires_assistance": branch.get("requires_assistance"),
                                    "budget": branch.get("budget"),
                                    "currency": branch.get("currency"),
                                }
                            )
                    else:
                        split_branches.append(branch)
                cleaned = split_branches

        # Handle validation messages by appending to assistant message
        if validation_messages:
            validation_text = " ".join(validation_messages)
            if assistant_message:
                assistant_message = f"{assistant_message} {validation_text}"
            else:
                assistant_message = validation_text
        elif not has_all_fields and not assistant_message:
            # Generate a default question if LLM didn't provide one
            default_question = _default_follow_up_question(parsed_missing_fields)
            assistant_message = default_question or default_assistant_message

        if not assistant_message:
            assistant_message = default_assistant_message

        # Get ready_to_generate from LLM response, or determine it ourselves
        llm_ready_to_generate = data.get("ready_to_generate", False)

        # If LLM says ready but we have branches, that's inconsistent - prioritize branches
        if cleaned:
            llm_ready_to_generate = False

        # If all fields complete, no branches from LLM, and not a generate trigger,
        # then we're in the "ready to generate" state
        should_be_ready = (
            has_all_fields and not cleaned and not has_existing_branches and not is_generate_trigger
        )

        final_ready_to_generate = llm_ready_to_generate or should_be_ready

        if has_all_fields:
            trip_inputs["missing_fields"] = []

        token_estimate = None
        try:
            llm_output_text = (raw_content or "").strip()
            if not llm_output_text:
                llm_output_text = json.dumps(data, ensure_ascii=True, default=str) if data else ""
            if not llm_output_text:
                llm_output_text = assistant_message

            system_token_sources = [system_prompt]
            if document_context:
                system_token_sources.append(document_context)

            token_estimate = _estimate_total_tokens(
                system_messages=system_token_sources,
                history=history_messages,
                user_message=req.message,
                llm_output=llm_output_text,
            )
        except Exception:
            token_estimate = None

        output = PlannerLLMOutput(
            branches=cleaned,
            assistant_message=assistant_message,
            trip_inputs=trip_inputs,
            ready_to_generate=final_ready_to_generate,
            suggested_responses=suggested_responses,
            token_estimate=token_estimate,
        )

        return output

    if last_error is not None:
        raise RuntimeError(f"OpenAI planning call failed: {last_error}")
    raise RuntimeError("OpenAI planning call returned no completion")


# =============================================================================
# PUBLIC PLANNING API
# =============================================================================


def plan_trip(db: Session, session_id: str, req: PlanRequest) -> PlanDocumentResponse:
    """
    Main planning flow that orchestrates the entire trip planning conversation.

    This is the primary entry point for processing a user's planning message.
    It coordinates all the components: session management, chat history,
    LLM interaction, document updates, and tile search.

    The flow:
    1. **Session Setup**: Get or create a session for the user
    2. **History Retrieval**: Fetch recent chat history for LLM context
    3. **Document Loading**: Load existing PlanDocument (if any) for state
    4. **Context Creation**: Create a new TripContext for this conversation turn
    5. **Message Recording**: Store user message in chat history
    6. **LLM Processing**: Call OpenAI to process the message
    7. **Document Update**: Update PlanDocument with new state
    8. **Tile Search**: Search for tiles if branches were generated

    Args:
        db: SQLAlchemy database session.
        session_id: Session ID from cookie (injected by middleware).
        req: PlanRequest containing user message.

    Returns:
        PlanDocumentResponse: The complete response including:
            - version: Document version for optimistic locking
            - updated_by: Who made the last update ("planner", "user", etc.)
            - document: Full PlanDocumentData with trip_inputs, branches, tiles
            - updated_at: ISO timestamp of the update
    """
    # 1. Setup session and context
    # Use lock_for_update=True to prevent deadlocks with concurrent session deletion
    db_session = get_or_create_session(
        db,
        session_token=session_id,
        lock_for_update=True,
    )

    history_rows = fetch_chat_history(db, session=db_session, limit=_CHAT_HISTORY_LIMIT)
    history_messages = _history_to_messages(history_rows)

    # Get parent trip context from document (if exists)
    existing_doc = get_document(db, session=db_session)
    existing_doc_data: Optional[PlanDocumentData] = None
    parent_trip_context_id: Optional[int] = None
    if existing_doc:
        existing_doc_data = get_document_data(existing_doc)
        parent_trip_context_id = existing_doc_data.trip_context_id

    parent_ctx = _resolve_parent_trip_context(
        db,
        session=db_session,
        requested_parent_id=parent_trip_context_id,
    )

    try:
        trip_ctx = create_trip_context(
            db,
            session=db_session,
            parent_trip_context=parent_ctx,
            req_message=req.message,
        )

        # 2. Record user message (transform trigger to friendly text for display)
        user_message_content = (
            "Generate my trip options" if _is_generate_plan_trigger(req.message) else req.message
        )
        record_chat_message(
            db,
            session=db_session,
            trip_context=trip_ctx,
            role="user",
            content=user_message_content,
            metadata=None,
        )

        # 3. Prepare placeholder for assistant message
        # We create this early so it has the correct ordering in chat history
        assistant_chat = record_chat_message(
            db,
            session=db_session,
            trip_context=trip_ctx,
            role="assistant",
            content="",
            metadata=None,
        )

        # 4. Call LLM once (no streaming)
        planner_output = _call_openai_for_plan(
            req,
            history=history_messages,
            document_data=existing_doc_data,
            timezone=req.timezone,
        )

        # 5. Process LLM output and update assistant message
        # Filter out None booking preference fields - they have default_factory in schema
        if planner_output.trip_inputs is not None:
            filtered_inputs = {
                k: v
                for k, v in planner_output.trip_inputs.items()
                if v is not None or k not in _BOOKING_PREFERENCE_FIELDS
            }
            trip_inputs_model = DocumentTripInputs(**filtered_inputs)
        else:
            trip_inputs_model = None
        assistant_chat.content = planner_output.assistant_message
        assistant_meta: dict[str, Any] = {}

        # 6. Get or create the PlanDocument
        plan_doc = get_or_create_document(db, session=db_session, updated_by="planner")

        # Refresh the document to pick up any user-initiated patches that happened
        # while the LLM call was in progress (e.g., removing a destination)
        try:
            db.refresh(plan_doc)
        except Exception:
            # If refresh fails (e.g., brand new document), proceed with current state
            pass

        current_doc_data = get_document_data(plan_doc)

        assistant_chat.meta = assistant_meta or None

        # 7. Build document branches and tiles from LLM output
        branch_specs = planner_output.branches or []
        doc_branches: List[DocumentBranch] = []
        tiles_dict: dict[str, TileSchema] = {}
        primary_branch: Optional[DocumentBranch] = None

        for idx, spec in enumerate(branch_specs):
            # Generate a unique branch ID
            branch_id = f"branch_{trip_ctx.id}_{idx}"

            branch_destinations = spec.get("destinations", []) or []
            if not isinstance(branch_destinations, list):
                branch_destinations = [branch_destinations] if branch_destinations else []

            doc_branch = DocumentBranch(
                id=branch_id,
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
                currency=_normalize_currency(spec.get("currency"), default=DEFAULT_CURRENCY),
                is_primary=(idx == 0),
                tiles=BranchTileIds(),
            )
            doc_branches.append(doc_branch)

            if idx == 0:
                primary_branch = doc_branch

        # 8. Search for tiles for the primary branch
        if primary_branch:
            # Update assistant message to indicate we're creating suggestions
            assistant_chat.content = "Creating trip suggestions for you..."

            # Use first destination for tile search
            primary_dest = primary_branch.destinations[0] if primary_branch.destinations else None

            tiles_request = TilesSearchRequest(
                session_id=session_id,
                trip_context_id=trip_ctx.id,
                destination=primary_dest,
                destination_hint=primary_dest,
                origin=trip_inputs_model.origin if trip_inputs_model else None,
                start_date=trip_inputs_model.start_date if trip_inputs_model else None,
                end_date=trip_inputs_model.end_date if trip_inputs_model else None,
                adults=trip_inputs_model.adults if trip_inputs_model else None,
                children=trip_inputs_model.children if trip_inputs_model else None,
                currency=trip_inputs_model.currency if trip_inputs_model else DEFAULT_CURRENCY,
            )

            tiles_response = search_tiles(tiles_request)

            # Add tiles to the primary branch and to the tiles dict
            for tile in tiles_response.tiles:
                tiles_dict[tile.id] = tile
                if tile.type == "hotel":
                    primary_branch.tiles.stays.append(tile.id)
                elif tile.type == "flight":
                    primary_branch.tiles.flights.append(tile.id)
                elif tile.type == "activity":
                    primary_branch.tiles.activities.append(tile.id)

        # 9. Build trip inputs for document
        # LLM output already includes multi_city_intent – just propagate what it sent
        # Include ALL fields including booking preferences so LLM can update them
        doc_trip_inputs = None
        if trip_inputs_model:
            doc_trip_inputs = DocumentTripInputs(
                destinations=trip_inputs_model.destinations or [],
                origin=trip_inputs_model.origin,
                start_date=trip_inputs_model.start_date,
                end_date=trip_inputs_model.end_date,
                adults=trip_inputs_model.adults,
                children=trip_inputs_model.children,
                requires_assistance=trip_inputs_model.requires_assistance,
                budget=trip_inputs_model.budget,
                currency=trip_inputs_model.currency,
                missing_fields=trip_inputs_model.missing_fields,
                multi_city_intent=trip_inputs_model.multi_city_intent,
                # Booking preferences - propagate LLM updates
                booking_types=trip_inputs_model.booking_types,
                flight_settings=trip_inputs_model.flight_settings,
                hotel_settings=trip_inputs_model.hotel_settings,
                activity_settings=trip_inputs_model.activity_settings,
                transport_settings=trip_inputs_model.transport_settings,
            )

        # 10. Apply the planner update to the document
        # Always update trip_inputs (even during collection phase when no branches exist)
        #
        # If the LLM generated new branches, use them.
        # Otherwise, keep existing branches from the document.
        final_branches = doc_branches if doc_branches else current_doc_data.branches
        # Only pass branches to apply_planner_update if there are any to update
        branches_to_apply = final_branches if final_branches else None

        apply_planner_update(
            db,
            doc=plan_doc,
            trip_context_id=trip_ctx.id,
            trip_inputs=doc_trip_inputs,
            branches=branches_to_apply,
            tiles=tiles_dict or None,
        )

        doc_data = get_document_data(plan_doc)

        # Add chat metadata to the response (not persisted to document)
        doc_data_dict = doc_data.model_dump()
        doc_data_dict["assistant_message"] = assistant_chat.content
        doc_data_dict["assistant_message_id"] = str(assistant_chat.id)
        # Pass through the ready_to_generate flag from planner output
        doc_data_dict["ready_to_generate"] = planner_output.ready_to_generate
        # Pass through suggested responses for quick reply buttons
        doc_data_dict["suggested_responses"] = planner_output.suggested_responses

        # DEBUG (3/3): After merge - final document state
        if _DEBUG_LOG:
            print("[DEBUG] === AFTER MERGE ===")
            print(json.dumps(doc_data_dict, indent=2, default=str))
            print("=" * 80)

        # Reconstruct the document data with chat fields
        doc_data_with_chat = PlanDocumentData(**doc_data_dict)

        if _DEBUG_LOG and planner_output.token_estimate is not None:
            print(
                f"[DEBUG] Estimated total LLM tokens used for this turn: "
                f"{planner_output.token_estimate}"
            )

        response = PlanDocumentResponse(
            version=plan_doc.version,
            updated_by=plan_doc.updated_by,
            document=doc_data_with_chat,
            updated_at=plan_doc.updated_at.isoformat(),
            changes_made=True,
        )

        db.commit()
        return response
    except Exception:
        db.rollback()
        raise
