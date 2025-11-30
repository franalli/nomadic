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
- Chat history metadata provides fallback for migration from older sessions
- Trip inputs are collected in a specific order: destination → origin → dates → travelers → budget
- Branches are only generated once ALL required fields are collected
- Robust JSON parsing handles malformed LLM responses
"""

import json
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any, Iterable, List, Optional, cast

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from sqlalchemy.orm import Session

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
    BranchTileIds,
    DocumentBranch,
    DocumentTripInputs,
    PlanDocumentData,
    PlanDocumentResponse,
    PlanRequest,
    TilesSearchRequest,
    TripInputs,
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
                  start_date, end_date, traveler_count, budget.
        assistant_message: The conversational response to show the user.
        trip_inputs: Dict of collected/updated trip input fields.
        ready_to_generate: True when all fields are complete but branches haven't
                           been generated yet (waiting for user to click Generate).
    """

    def __init__(
        self,
        *,
        branches: List[dict],
        assistant_message: str,
        trip_inputs: Optional[dict] = None,
        ready_to_generate: bool = False,
    ) -> None:
        self.branches = branches
        self.assistant_message = assistant_message
        self.trip_inputs = trip_inputs or {}
        self.ready_to_generate = ready_to_generate


# =============================================================================
# CONFIGURATION CONSTANTS
# =============================================================================
# These environment-driven settings control LLM behavior and conversation limits.

_CHAT_HISTORY_LIMIT = int(os.getenv("PLAN_CHAT_HISTORY_LIMIT", "20"))  # Max messages to include
_MAX_TOKENS = int(os.getenv("OPENAI_PLAN_MAX_TOKENS", "800"))  # Token limit for LLM response
_PLAN_TEMPERATURE = float(os.getenv("OPENAI_PLAN_TEMPERATURE", "0.75"))  # Response creativity
_PLAN_TOP_P = float(os.getenv("OPENAI_PLAN_TOP_P", "0.95"))  # Nucleus sampling threshold
_PLAN_MAX_RETRIES = int(os.getenv("OPENAI_PLAN_MAX_RETRIES", "3"))  # Retry count for API errors
_PLAN_SEED = os.getenv("OPENAI_PLAN_SEED")  # Optional seed for reproducibility

_openai_client: Optional[OpenAI] = None  # Singleton OpenAI client instance
_DEBUG_LOG = bool(os.getenv("DEBUG_PLAN_MESSAGES"))  # Enable verbose debug logging

# The canonical order for collecting trip input fields.
# This order is used consistently for prompts, validation, and missing field detection.
_TRIP_INPUT_FIELDS = (
    "destinations",
    "origin",
    "start_date",
    "end_date",
    "traveler_count",
    "budget",
)

# Required fields - all must be filled before branches can be generated
_REQUIRED_TRIP_INPUT_FIELDS = _TRIP_INPUT_FIELDS  # All 6 fields are required


# =============================================================================
# DATE UTILITY FUNCTIONS
# =============================================================================


def _today_iso() -> str:
    """
    Get today's date in ISO format (YYYY-MM-DD).

    Uses UTC to ensure consistency across timezones.

    Returns:
        str: Today's date as "YYYY-MM-DD"
    """
    return datetime.utcnow().strftime("%Y-%m-%d")


def _next_week_iso() -> str:
    """
    Get the date one week from today in ISO format.

    Used as a default end_date suggestion when users don't specify dates.

    Returns:
        str: Date 7 days from now as "YYYY-MM-DD"
    """
    return (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d")


# =============================================================================
# OPENAI CLIENT MANAGEMENT
# =============================================================================


def _get_openai_client() -> Optional[OpenAI]:
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


def _serialize_document_for_llm(doc_data: Optional[PlanDocumentData]) -> Optional[str]:
    """
    Serialize the full PlanDocumentData into a human-readable format for the LLM.

    This function converts the structured document state into a text format that
    the LLM can easily understand. It includes:
    - Trip inputs (destination, dates, travelers, budget)
    - All branches with their descriptions and tile assignments
    - Available tiles with pricing information
    - User's current selections within each branch

    The output format uses clear section headers and indentation to help the LLM
    parse the context effectively.

    Args:
        doc_data: The current plan document data, or None if no document exists.

    Returns:
        Optional[str]: A formatted text representation of the document state,
                       or None if doc_data is None.

    Example output:
        === CURRENT TRIP PLAN STATE ===
        Trip Inputs: destination=Paris, start_date=2025-01-15
        Missing Fields: origin, end_date, traveler_count, budget

        === BRANCHES (2) ===
        Branch: Cultural Explorer (PRIMARY)
          Description: Museums, history, local culture
          ...
        === END TRIP PLAN STATE ===
    """
    if doc_data is None:
        return None

    lines: List[str] = ["=== CURRENT TRIP PLAN STATE ==="]

    # 1. Trip inputs
    ti = doc_data.trip_inputs
    inputs_parts = []
    if ti.destinations:
        inputs_parts.append(f"destinations={', '.join(ti.destinations)}")
    if ti.origin:
        inputs_parts.append(f"origin={ti.origin}")
    if ti.start_date:
        inputs_parts.append(f"start_date={ti.start_date}")
    if ti.end_date:
        inputs_parts.append(f"end_date={ti.end_date}")
    if ti.traveler_count is not None:
        inputs_parts.append(f"traveler_count={ti.traveler_count}")
    if ti.budget is not None:
        inputs_parts.append(f"budget={ti.budget}")
    if inputs_parts:
        lines.append(f"Trip Inputs: {', '.join(inputs_parts)}")
    if ti.missing_fields:
        lines.append(f"Missing Fields: {', '.join(ti.missing_fields)}")

    # 2. Branches with their selections and tile info
    if doc_data.branches:
        lines.append(f"\n=== BRANCHES ({len(doc_data.branches)}) ===")
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
            if branch.traveler_count is not None:
                lines.append(f"  Travelers: {branch.traveler_count}")
            if branch.budget is not None:
                lines.append(f"  Budget: {branch.budget}")

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

    # 3. Available tiles (abbreviated)
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

    lines.append("\n=== END TRIP PLAN STATE ===")
    return "\n".join(lines)


# =============================================================================
# CHAT HISTORY MIGRATION HELPERS
# =============================================================================


def _latest_trip_state_from_history(
    history_rows: List[models.ChatMessage],
) -> Optional[dict]:
    """
    Extract trip_inputs from chat message metadata as a migration fallback.

    DEPRECATED: This function exists only for backward compatibility with sessions
    created before PlanDocument became the single source of truth. It will be
    removed once all old sessions have migrated or expired.

    The function scans through assistant messages in chronological order and merges
    any trip_inputs stored in their metadata.

    Args:
        history_rows: List of ChatMessage objects from the database, ordered
                      chronologically (oldest first).

    Returns:
        Optional[dict]: Merged trip_inputs from all assistant messages, or None
                        if no trip_inputs were found in any message metadata.

    Note:
        - Only assistant messages are considered (user messages don't have trip_inputs)
        - Later messages overwrite earlier values (allow_overwrite=True)
        - Consider removing this once migration period is complete
    """

    merged_trip_inputs: Optional[dict] = None

    for entry in history_rows:
        if getattr(entry, "role", None) != "assistant":
            continue
        meta = getattr(entry, "meta", None)
        if not isinstance(meta, dict):
            continue

        ti = meta.get("trip_inputs")
        if isinstance(ti, dict):
            if merged_trip_inputs is None:
                merged_trip_inputs = _clean_trip_inputs(ti)
            else:
                merged_trip_inputs = _clean_trip_inputs(
                    merged_trip_inputs,
                    ti,
                    allow_overwrite=True,
                )

    return merged_trip_inputs


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
        Optional[str]: The trimmed string, or None if the value was None
                       or became empty after trimming.
    """
    if value is None:
        return None
    value_str = str(value).strip()
    return value_str or None


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


def _clamp_traveler_count(value: Optional[int]) -> Optional[int]:
    """
    Constrain traveler count to a valid range [1, 20].

    Args:
        value: The traveler count to clamp.

    Returns:
        Optional[int]: The clamped value (1-20), or None if input was None.
    """
    if value is None:
        return None
    return max(1, min(20, value))


def _ordered_missing_fields_from_inputs(
    trip_inputs: dict,
) -> List[str]:
    """
    Get the list of missing trip input fields in canonical order.

    The order matches _REQUIRED_TRIP_INPUT_FIELDS: destinations, origin, start_date,
    end_date, traveler_count, budget.

    Args:
        trip_inputs: A dictionary of trip input values.

    Returns:
        List[str]: Field names that are None/empty, in collection order.
    """
    missing = []
    for field in _REQUIRED_TRIP_INPUT_FIELDS:
        if field == "destinations":
            # For destinations, check if array is empty
            val = trip_inputs.get(field, [])
            if not val or (isinstance(val, list) and len(val) == 0):
                missing.append(field)
        elif trip_inputs.get(field) is None:
            missing.append(field)
    return missing


# =============================================================================
# TRIP INPUTS MERGING AND CLEANING
# =============================================================================


def _clean_trip_inputs(
    *sources: Any,
    fallback: Optional[dict] = None,
    allow_overwrite: bool = False,
    overwrite_fields: Optional[Iterable[str]] = None,
) -> dict:
    """
    Merge multiple trip_inputs sources into a single normalized dictionary.

    This function is central to the state management strategy. It handles:
    - Merging inputs from document, chat history, and LLM response
    - Normalizing values (dates, integers, strings)
    - Tracking which fields are still missing
    - Respecting overwrite semantics (first source wins unless allow_overwrite)

    The merging priority (first source wins by default):
    1. Earlier sources in *sources take precedence
    2. fallback is applied last
    3. With allow_overwrite=True, later sources can overwrite earlier values

    Args:
        *sources: Variable number of dict-like sources to merge.
        fallback: Optional final fallback dictionary.
        allow_overwrite: If True, later sources overwrite earlier values.
        overwrite_fields: Specific field names that can always be overwritten.

    Returns:
        dict: Merged trip_inputs with all fields normalized and a
              "missing_fields" key listing fields that are still None.

    Example:
        >>> _clean_trip_inputs(
        ...     {"destination": "Paris"},
        ...     {"destination": "London", "budget": 1500},
        ...     allow_overwrite=False
        ... )
        {"destination": "Paris", "budget": 1500, "missing_fields": [...]}
    """
    sentinel = object()
    merged: dict[str, Any] = {field: sentinel for field in _TRIP_INPUT_FIELDS}
    noted_missing: set[str] = set()
    overwrite_set = {str(f) for f in overwrite_fields} if overwrite_fields else set()

    def _ingest(source: Any) -> None:
        if not isinstance(source, dict):
            return

        raw_missing = source.get("missing_fields", [])
        if isinstance(raw_missing, list):
            for entry in raw_missing:
                entry_str = str(entry).strip()
                if entry_str:
                    noted_missing.add(entry_str)

        for field in _TRIP_INPUT_FIELDS:
            if field == "destinations":
                # Handle destinations as an array
                # With allow_overwrite=True, the LLM can replace destinations entirely
                # Check if destinations key is explicitly present in source (even if empty)
                destinations_key_present = "destinations" in source
                source_destinations = source.get("destinations", [])
                if not isinstance(source_destinations, list):
                    source_destinations = [source_destinations] if source_destinations else []
                source_destinations = [
                    _normalize_str(d) for d in source_destinations if d and _normalize_str(d)
                ]
                current_value = merged[field]
                can_overwrite = allow_overwrite or ("destinations" in overwrite_set)
                if source_destinations:
                    if can_overwrite:
                        # When allow_overwrite is True, replace destinations entirely
                        # This allows users to change/reduce their destination list via chat
                        merged[field] = source_destinations
                    elif current_value in (sentinel, None, []):
                        merged[field] = source_destinations
                    elif isinstance(current_value, list):
                        # Merge: add new destinations that aren't already present
                        existing_set = set(current_value)
                        for dest in source_destinations:
                            if dest not in existing_set:
                                current_value.append(dest)
                                existing_set.add(dest)
                        merged[field] = current_value
                    else:
                        merged[field] = source_destinations
                elif can_overwrite and destinations_key_present:
                    # Explicit empty list when allow_overwrite - delete all destinations
                    merged[field] = []
                elif current_value is sentinel:
                    merged[field] = []
            elif field in ("start_date", "end_date"):
                normalizer = _normalize_date
                value = normalizer(source.get(field))
                current_value = merged[field]
                can_overwrite = allow_overwrite or (field in overwrite_set)
                # Non-destination fields persist once set - only update with non-null values
                if value is not None:
                    if current_value in (sentinel, None) or can_overwrite:
                        merged[field] = value
                elif current_value is sentinel:
                    merged[field] = None
            elif field == "traveler_count":
                normalizer = _normalize_int
                value = normalizer(source.get(field))
                current_value = merged[field]
                can_overwrite = allow_overwrite or (field in overwrite_set)
                # Non-destination fields persist once set - only update with non-null values
                if value is not None:
                    if current_value in (sentinel, None) or can_overwrite:
                        merged[field] = value
                elif current_value is sentinel:
                    merged[field] = None
            elif field == "budget":
                normalizer = _normalize_int
                value = normalizer(source.get(field))
                current_value = merged[field]
                can_overwrite = allow_overwrite or (field in overwrite_set)
                # Non-destination fields persist once set - only update with non-null values
                if value is not None:
                    if current_value in (sentinel, None) or can_overwrite:
                        merged[field] = value
                elif current_value is sentinel:
                    merged[field] = None
            else:
                # Origin and other string fields - persist once set
                normalizer = _normalize_str
                value = normalizer(source.get(field))
                current_value = merged[field]
                can_overwrite = allow_overwrite or (field in overwrite_set)
                # Non-destination fields persist once set - only update with non-null values
                if value is not None:
                    if current_value in (sentinel, None) or can_overwrite:
                        merged[field] = value
                elif current_value is sentinel:
                    merged[field] = None

    for source in sources:
        _ingest(source)
    if fallback is not None:
        _ingest(fallback)

    final_missing: set[str] = set()
    for field in _TRIP_INPUT_FIELDS:
        if field == "destinations":
            if merged[field] is sentinel:
                merged[field] = []
            if not merged[field]:
                final_missing.add(field)
        else:
            if merged[field] is sentinel:
                merged[field] = None
            if merged[field] is None:
                final_missing.add(field)

    # Only add noted_missing fields if they are actually None/empty
    # Don't let LLM's incorrect missing_fields override our actual values
    for field in noted_missing:
        if field == "destinations":
            if not merged.get(field):
                final_missing.add(field)
        elif merged.get(field) is None:
            final_missing.add(field)

    ordered_missing = [field for field in _TRIP_INPUT_FIELDS if field in final_missing]

    merged["missing_fields"] = ordered_missing

    return merged


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

    traveler_count = trip_inputs.get("traveler_count")
    if traveler_count is not None:
        clamped_travelers = _clamp_traveler_count(traveler_count)
        if traveler_count < 1:
            validation_messages.append(
                f"Traveler count must be at least 1. I set it to {clamped_travelers}. Is that okay?"
            )
        if traveler_count != clamped_travelers:
            trip_inputs["traveler_count"] = clamped_travelers

    budget_value = trip_inputs.get("budget")
    if budget_value is not None and budget_value < 0:
        trip_inputs["budget"] = None
        validation_messages.append("Budget must be zero or higher. Please share an updated budget.")

    trip_inputs["missing_fields"] = _ordered_missing_fields_from_inputs(trip_inputs)
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
        "traveler_count": "How many travelers will be going?",
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
    history_rows: List[models.ChatMessage],
    history: List[ChatCompletionMessageParam],
    document_data: Optional[PlanDocumentData] = None,
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
        history_rows: Raw ChatMessage database objects (for metadata extraction).
        history: Processed message history in OpenAI format.
        document_data: Current PlanDocument state (source of truth).

    Returns:
        PlannerLLMOutput: Structured output containing branches, message, and trip_inputs.

    Raises:
        RuntimeError: If OpenAI client is not configured or call fails after retries.
    """
    # Get trip state from conversation history (fallback for older sessions)
    prior_trip_inputs_meta = _latest_trip_state_from_history(history_rows)

    # Read trip inputs from document (THE ONLY source of truth)
    doc_trip_inputs: dict = {}
    if document_data and document_data.trip_inputs:
        ti = document_data.trip_inputs
        doc_trip_inputs = {
            "destinations": ti.destinations,
            "origin": ti.origin,
            "start_date": ti.start_date,
            "end_date": ti.end_date,
            "traveler_count": ti.traveler_count,
            "budget": ti.budget,
        }

    # Document is the only source of truth for trip inputs.
    # Chat history metadata is only used as fallback for migration from older sessions.
    current_trip_inputs = _clean_trip_inputs(
        doc_trip_inputs,
        prior_trip_inputs_meta,
    )

    today = _today_iso()

    # Check if this is a generate plan trigger
    is_generate_trigger = _is_generate_plan_trigger(req.message)

    # Check if we already have branches
    has_existing_branches = bool(document_data and document_data.branches)

    # Check if all required fields are complete BEFORE calling LLM
    pre_check_missing = _ordered_missing_fields_from_inputs(current_trip_inputs)
    all_fields_already_complete = len(pre_check_missing) == 0

    if _DEBUG_LOG:
        print(
            f"[DEBUG] Pre-LLM check: all_fields_complete={all_fields_already_complete}, "
            f"has_branches={has_existing_branches}, is_generate={is_generate_trigger}"
        )

    # REMOVED: Early return when all fields complete
    # We ALWAYS call the LLM so users can modify their inputs at any time.
    # The only exception is the generate trigger which explicitly requests branch generation.

    # Build current state as JSON for the prompt (include ALL fields including destinations)
    current_state_json = json.dumps(current_trip_inputs, indent=2)

    # Single unified system prompt
    system_prompt = f"""You are a travel planner. Today is {today}.

STYLE: Warm, concise. If user mentions a destination, always start with a
relevant emoji (only if one exists) for example:
🏛️ Rome (or Athens), 🎭 Florence, 🗼 Paris, 🗽 NYC, 🏯 Tokyo,
🎰 Vegas, 🌴 Miami, 🏔️ Alps, 🏖️ Bali, 🕌 Dubai

CURRENT STATE:
{current_state_json}

TASK: Extract trip details from user message and update trip_inputs.
Required fields: destinations[], origin, start_date, end_date, traveler_count, budget

EXTRACTION RULES:
- Dates: Convert to YYYY-MM-DD. "today"={today}, "tomorrow"=+1 day, "in X days"=+X days
- If user gives duration ("for 5 days"), compute end_date from start_date
- Travelers: "solo"=1, "couple"=2, "family of 4"=4
- Budget: "$1000" or "1000 dollars" → 1000
- Locations: Auto-correct typos (Florene→Florence, Pairs→Paris, Also→Oslo)
- Destinations: CURRENT STATE is the source of truth. Only add NEW destinations
  from current message. Do NOT re-add destinations from chat history if not in CURRENT STATE.
- REMOVAL: "Remove X" or "Remove destination X" → IMMEDIATELY remove X from destinations list.
  Do NOT ask for confirmation. Just remove it and acknowledge briefly.
- IGNORE removal requests for origin, dates, travelers, or budget - these persist once set
- origin = where user travels FROM. destinations = where they travel TO

BEHAVIOR:
1. Extract values from message, update trip_inputs with ALL fields (existing + new)
2. Never confirm what you just extracted—ask for next missing field
3. All 6 fields complete → set ready_to_generate:true, branches:[]
4. User says "generate" → set ready_to_generate:false, create 1 branch per destination
5. Missing fields → set ready_to_generate:false, branches:[]

Return this JSON structure:
{{
  "assistant_message": "Your response to user",
  "trip_inputs": {{
    "destinations": [],
    "origin": null,
    "start_date": null,
    "end_date": null,
    "traveler_count": null,
    "budget": null,
    "missing_fields": []
  }},
  "ready_to_generate": false,
  "branches": []
}}

Branch format (when generating):
{{
  "label": "Name",
  "description": "Brief desc",
  "destinations": ["city"],
  "origin": "city",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "traveler_count": 1,
  "budget": 1000
}}"""

    client = _get_openai_client()
    if client is None:
        raise RuntimeError("OpenAI client is not configured")

    last_error: Exception | None = None

    history_messages: List[ChatCompletionMessageParam] = list(history)

    # Serialize document state for LLM context
    document_context = _serialize_document_for_llm(document_data)

    messages: List[ChatCompletionMessageParam] = [
        cast(ChatCompletionMessageParam, {"role": "system", "content": system_prompt})
    ]
    # Inject document state as a system-level context message if available
    if document_context:
        messages.append(
            cast(
                ChatCompletionMessageParam,
                {
                    "role": "system",
                    "content": f"[CONTEXT: Current trip plan state]\n{document_context}",
                },
            )
        )
    messages.extend(history_messages)
    messages.append(cast(ChatCompletionMessageParam, {"role": "user", "content": req.message}))

    if _DEBUG_LOG:
        print(f"[DEBUG] Sending {len(messages)} messages to OpenAI:")
        for i, msg in enumerate(messages):
            role = msg.get("role", "?")
            content_raw = msg.get("content", "")
            content = str(content_raw)[:100] if content_raw else ""
            print(f"  [{i}] {role}: {content}...")

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

        # Base parameters common to all models
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
        # GPT-5 models (including nano/mini)
        elif "gpt-5" in model_lower:
            params = {
                **base_params,
                "max_completion_tokens": _MAX_TOKENS,
            }
        # o1, o3, and other reasoning models (may not support response_format)
        elif model_lower.startswith("o1") or model_lower.startswith("o3"):
            params = {
                "model": model_name,
                "messages": messages,
                "max_completion_tokens": _MAX_TOKENS,
            }
            if seed_value is not None:
                params["seed"] = seed_value
        else:
            # Default fallback for other GPT models
            params = {
                **base_params,
                "max_tokens": _MAX_TOKENS,
            }

        if _DEBUG_LOG:
            keys_str = list(params.keys())
            print(f"[DEBUG] OpenAI request params: model={model_name}, keys={keys_str}")

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
                if _DEBUG_LOG:
                    print(f"[DEBUG] OpenAI planning call attempt {attempt + 1} failed: {exc}")
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
        if _DEBUG_LOG:
            print(f"[DEBUG] OpenAI planning call failed with '{model_name}': {exc}")

    if completion is not None:
        raw_content = ""
        structured_payload: Optional[dict] = None
        choice = None
        try:
            choice = completion.choices[0] if completion and completion.choices else None
            if choice is not None:
                structured_payload, raw_content = _extract_message_payload(choice)
                if _DEBUG_LOG:
                    has_struct = structured_payload is not None
                    print(f"[DEBUG] Extracted: structured={has_struct}, raw_len={len(raw_content)}")
        except Exception as parse_exc:
            if _DEBUG_LOG:
                print(f"[DEBUG] Failed to extract message payload: {parse_exc}")
            raw_content = ""

        if _DEBUG_LOG:
            if raw_content:
                print(
                    f"[DEBUG] Raw LLM response ({len(raw_content)} chars): "
                    f"{raw_content[:500]}..."
                )
            elif structured_payload:
                struct_str = json.dumps(structured_payload)[:500]
                print(f"[DEBUG] Structured LLM response: {struct_str}...")
            else:
                # Enhanced debugging: show full choice object
                print("[DEBUG] No content extracted from LLM response.")
                print(f"[DEBUG] Choice object: {choice}")
                if choice is not None:
                    message_obj = getattr(choice, "message", None)
                    if message_obj:
                        print(f"[DEBUG] Message object: {message_obj}")
                        content_val = getattr(message_obj, "content", None)
                        print(f"[DEBUG] Message content type: {type(content_val)}")
                        print(f"[DEBUG] Message content value: {content_val}")

        default_assistant_message = "I'm having trouble processing that. Could you try again?"

        data = structured_payload or _tolerant_json_loads(raw_content or "")
        if _DEBUG_LOG:
            print(f"[DEBUG] Parsed data: {data}")

        # Retry logic: if parsing failed and we have a client, try once more
        if data is None and client is not None:
            if _DEBUG_LOG:
                snippet = raw_content[:200] if raw_content else "empty"
                print(f"[DEBUG] Failed to parse JSON on first attempt. Raw: {snippet}")
                print("[DEBUG] Retrying LLM call...")

            try:
                # Retry the completion
                retry_completion = _invoke_with_retries()
                if retry_completion and retry_completion.choices:
                    retry_choice = retry_completion.choices[0]
                    retry_structured, retry_raw = _extract_message_payload(retry_choice)
                    if _DEBUG_LOG:
                        has_struct = retry_structured is not None
                        print(
                            f"[DEBUG] Retry extracted: structured={has_struct}, "
                            f"raw_len={len(retry_raw)}"
                        )
                        if retry_raw:
                            print(f"[DEBUG] Retry raw response: {retry_raw[:500]}...")
                    data = retry_structured or _tolerant_json_loads(retry_raw or "")
                    if _DEBUG_LOG:
                        print(f"[DEBUG] Retry parsed data: {data}")
            except Exception as retry_exc:
                if _DEBUG_LOG:
                    print(f"[DEBUG] Retry failed: {retry_exc}")

        if data is None:
            if _DEBUG_LOG:
                snippet = raw_content[:200] if raw_content else "empty"
                print(f"[DEBUG] Failed to parse JSON after retry. Raw: {snippet}")
            data = {
                "branches": [],
                "assistant_message": default_assistant_message,
                "trip_inputs": {},
            }
        if not isinstance(data, dict):
            data = {}

        branches_raw = data.get("branches", []) or []
        if _DEBUG_LOG:
            print(f"[DEBUG] Branches from LLM: {len(branches_raw)} branches")
        assistant_message = str(data.get("assistant_message") or "").strip()

        trip_inputs_payload = data.get("trip_inputs") or {}
        # Allow LLM to overwrite any field - users might correct any previous value
        trip_inputs = _clean_trip_inputs(
            current_trip_inputs,
            trip_inputs_payload,
            allow_overwrite=True,
        )

        # FALLBACK: If LLM failed to compute end_date from duration, do it ourselves
        if trip_inputs.get("start_date") and not trip_inputs.get("end_date"):
            duration_days = _extract_duration_days_from_message(req.message)
            if duration_days:
                computed_end = _compute_end_date_from_duration(
                    trip_inputs["start_date"], duration_days
                )
                if computed_end:
                    trip_inputs["end_date"] = computed_end
                    if _DEBUG_LOG:
                        print(
                            f"[DEBUG] Computed end_date from duration: "
                            f"{trip_inputs['start_date']} + {duration_days} days = {computed_end}"
                        )

        trip_inputs, validation_messages = _validate_trip_inputs(trip_inputs, today_iso=today)
        parsed_missing_fields = trip_inputs.get("missing_fields") or []

        has_all_fields = len(parsed_missing_fields) == 0 and not validation_messages
        if _DEBUG_LOG:
            print(
                f"[DEBUG] has_all_fields={has_all_fields}, "
                f"response_missing={parsed_missing_fields}, "
                f"validation={validation_messages}"
            )

        cleaned: List[dict] = []
        canonical_inputs = {field: trip_inputs.get(field) for field in _TRIP_INPUT_FIELDS}

        if has_all_fields and branches_raw:
            for b in branches_raw:
                if not isinstance(b, dict):
                    continue
                if "label" not in b:
                    continue
                # Handle destinations as array
                branch_destinations = b.get("destinations", [])
                if not isinstance(branch_destinations, list):
                    branch_destinations = [branch_destinations] if branch_destinations else []
                branch_destinations = [_normalize_str(d) for d in branch_destinations if d]
                if not branch_destinations:
                    branch_destinations = canonical_inputs.get("destinations", [])
                branch_origin = _normalize_str(b.get("origin")) or canonical_inputs.get("origin")
                branch_start = _normalize_date(b.get("start_date")) or canonical_inputs.get(
                    "start_date"
                )
                branch_end = _normalize_date(b.get("end_date")) or canonical_inputs.get("end_date")
                branch_travelers = _normalize_int(b.get("traveler_count"))
                if branch_travelers is None:
                    branch_travelers = _normalize_int(canonical_inputs.get("traveler_count"))
                if branch_travelers is not None:
                    branch_travelers = _clamp_traveler_count(branch_travelers)
                branch_budget = _normalize_int(b.get("budget"))
                if branch_budget is None:
                    branch_budget = _normalize_int(canonical_inputs.get("budget"))
                if branch_budget is not None and branch_budget < 0:
                    branch_budget = None

                if not branch_destinations:
                    continue

                cleaned.append(
                    {
                        "label": str(b["label"]),
                        "description": str(b.get("description", "")),
                        "destinations": branch_destinations,
                        "origin": branch_origin,
                        "start_date": branch_start,
                        "end_date": branch_end,
                        "traveler_count": branch_travelers,
                        "budget": branch_budget,
                    }
                )

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

        output = PlannerLLMOutput(
            branches=cleaned,
            assistant_message=assistant_message,
            trip_inputs=trip_inputs,
            ready_to_generate=final_ready_to_generate,
        )

        return output

    if last_error is not None:
        if _DEBUG_LOG:
            print(f"OpenAI planning call failed: {last_error}")
        raise RuntimeError(f"OpenAI planning call failed: {last_error}")
    raise RuntimeError("OpenAI planning call returned no completion")


# =============================================================================
# PUBLIC PLANNING API
# =============================================================================


def plan_trip_flow(db: Session, session_id: str, req: PlanRequest) -> PlanDocumentResponse:
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
    9. **Response Building**: Construct and return PlanDocumentResponse

    Error Handling:
    - Uses try/except with rollback to ensure database consistency
    - Any exception triggers a rollback before re-raising

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

    Raises:
        RuntimeError: If OpenAI is not configured or call fails.
        ValueError: If trip_context_id validation fails.
    """
    # 1. Setup session and context
    # Use lock_for_update=True to prevent deadlocks with concurrent session deletion
    db_session = get_or_create_session(
        db,
        session_token=session_id,
        user_external_id=None,  # User ID comes from auth, not request
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
    initial_destinations = existing_doc_data.trip_inputs.destinations if existing_doc_data else []

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

        # 2. Record user message
        record_chat_message(
            db,
            session=db_session,
            trip_context=trip_ctx,
            role="user",
            content=req.message,
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
            history_rows=history_rows,
            history=history_messages,
            document_data=existing_doc_data,
        )

        # 5. Process LLM output and update assistant message
        trip_inputs_model = (
            TripInputs(**planner_output.trip_inputs)
            if planner_output.trip_inputs is not None
            else None
        )
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
        current_destinations = current_doc_data.trip_inputs.destinations or []
        removed_destinations = {d for d in initial_destinations if d not in current_destinations}

        # Use LLM destinations, but filter out any the user removed during the LLM call
        # The LLM is instructed to use CURRENT STATE as source of truth, so its output
        # should already respect user removals made before the call. This filter catches
        # removals made during the LLM call (race condition protection).
        if trip_inputs_model:
            llm_destinations = trip_inputs_model.destinations or []
            # Filter out destinations the user removed during the LLM call
            final_destinations = [d for d in llm_destinations if d not in removed_destinations]

            trip_inputs_payload = trip_inputs_model.model_dump()
            trip_inputs_payload["destinations"] = final_destinations
            trip_inputs_payload["missing_fields"] = _ordered_missing_fields_from_inputs(
                trip_inputs_payload
            )
            trip_inputs_model = TripInputs(**trip_inputs_payload)
            # Store merged trip_inputs in message metadata for migration compatibility
            assistant_meta["trip_inputs"] = trip_inputs_payload

        assistant_chat.meta = assistant_meta or None

        # 7. Build document branches and tiles from LLM output
        branch_specs = planner_output.branches or []
        doc_branches: List[DocumentBranch] = []
        tiles_dict: dict[str, TileSchema] = {}
        primary_branch: Optional[DocumentBranch] = None

        for idx, spec in enumerate(branch_specs):
            # Generate a unique branch ID
            branch_id = f"branch_{trip_ctx.id}_{idx}"

            raw_destinations = spec.get("destinations", []) or []
            # Filter out destinations the user removed during the LLM call
            filtered_destinations = [d for d in raw_destinations if d not in removed_destinations]
            # For primary branch (idx==0), use trip_inputs destinations if available
            if idx == 0 and trip_inputs_model and trip_inputs_model.destinations:
                filtered_destinations = trip_inputs_model.destinations

            doc_branch = DocumentBranch(
                id=branch_id,
                label=str(spec.get("label", "")),
                description=str(spec.get("description", "")),
                destinations=filtered_destinations,
                origin=_normalize_str(spec.get("origin")),
                start_date=_normalize_str(spec.get("start_date")),
                end_date=_normalize_str(spec.get("end_date")),
                traveler_count=_normalize_int(spec.get("traveler_count")),
                budget=_normalize_int(spec.get("budget")),
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
                user_id=None,  # User ID comes from auth, not request
                session_id=session_id,
                trip_context_id=trip_ctx.id,
                destination=primary_dest,
                destination_hint=primary_dest,
                origin=trip_inputs_model.origin if trip_inputs_model else None,
                start_date=trip_inputs_model.start_date if trip_inputs_model else None,
                end_date=trip_inputs_model.end_date if trip_inputs_model else None,
                traveler_count=trip_inputs_model.traveler_count if trip_inputs_model else None,
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
        doc_trip_inputs = None
        if trip_inputs_model:
            doc_trip_inputs = DocumentTripInputs(
                destinations=trip_inputs_model.destinations or [],
                origin=trip_inputs_model.origin,
                start_date=trip_inputs_model.start_date,
                end_date=trip_inputs_model.end_date,
                traveler_count=trip_inputs_model.traveler_count,
                budget=trip_inputs_model.budget,
                missing_fields=trip_inputs_model.missing_fields,
            )

        # 10. Apply the planner update to the document
        # Always update trip_inputs (even during collection phase when no branches exist)
        apply_planner_update(
            db,
            doc=plan_doc,
            trip_context_id=trip_ctx.id,
            trip_inputs=doc_trip_inputs,
            branches=doc_branches or None,
            tiles=tiles_dict or None,
        )

        doc_data = get_document_data(plan_doc)

        # Add chat metadata to the response (not persisted to document)
        doc_data_dict = doc_data.model_dump()
        doc_data_dict["assistant_message"] = assistant_chat.content
        doc_data_dict["assistant_message_id"] = str(assistant_chat.id)
        # Pass through the ready_to_generate flag from planner output
        doc_data_dict["ready_to_generate"] = planner_output.ready_to_generate

        # Reconstruct the document data with chat fields
        doc_data_with_chat = PlanDocumentData(**doc_data_dict)

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


def plan_trip(db: Session, session_id: str, req: PlanRequest) -> PlanDocumentResponse:
    """
    Public API entry point for trip planning.

    This is a simple wrapper around plan_trip_flow that serves as the
    stable public interface. Internal implementation details may change,
    but this function signature remains stable.

    Args:
        db: SQLAlchemy database session.
        session_id: Session ID from cookie (injected by middleware).
        req: PlanRequest containing user message.

    Returns:
        PlanDocumentResponse: Complete planning response with document state.

    See Also:
        plan_trip_flow: The actual implementation with full documentation.
    """
    return plan_trip_flow(db, session_id, req)
