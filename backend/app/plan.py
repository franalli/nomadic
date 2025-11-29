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
    """

    def __init__(
        self,
        *,
        branches: List[dict],
        assistant_message: str,
        trip_inputs: Optional[dict] = None,
    ) -> None:
        self.branches = branches
        self.assistant_message = assistant_message
        self.trip_inputs = trip_inputs or {}


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
    "destination",
    "origin",
    "start_date",
    "end_date",
    "traveler_count",
    "budget",
)


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
    if ti.destination:
        inputs_parts.append(f"destination={ti.destination}")
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
            lines.append(f"  Destination: {branch.destination}")
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

    This function provides backward compatibility for sessions that existed before
    the PlanDocument was introduced as the single source of truth. It scans through
    assistant messages in chronological order and merges any trip_inputs stored
    in their metadata.

    The function is only used as a fallback when doc_trip_inputs is empty, allowing
    older sessions to continue working without data loss.

    Args:
        history_rows: List of ChatMessage objects from the database, ordered
                      chronologically (oldest first).

    Returns:
        Optional[dict]: Merged trip_inputs from all assistant messages, or None
                        if no trip_inputs were found in any message metadata.

    Note:
        - Only assistant messages are considered (user messages don't have trip_inputs)
        - Later messages overwrite earlier values (allow_overwrite=True)
        - This is a migration path and will eventually be deprecated
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


def _ordered_missing_fields_from_inputs(trip_inputs: dict) -> List[str]:
    """
    Get the list of missing trip input fields in canonical order.

    The order matches _TRIP_INPUT_FIELDS: destination, origin, start_date,
    end_date, traveler_count, budget. This ensures consistent prompting order.

    Args:
        trip_inputs: A dictionary of trip input values.

    Returns:
        List[str]: Field names that are None, in collection order.
    """
    return [field for field in _TRIP_INPUT_FIELDS if trip_inputs.get(field) is None]


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
            if field in ("start_date", "end_date"):
                normalizer = _normalize_date
            elif field == "traveler_count":
                normalizer = _normalize_int
            elif field == "budget":
                normalizer = _normalize_int
            else:
                normalizer = _normalize_str
            value = normalizer(source.get(field))
            current_value = merged[field]
            if value is not None:
                can_overwrite = allow_overwrite or (field in overwrite_set)
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
        if merged[field] is sentinel:
            merged[field] = None
        if merged[field] is None:
            final_missing.add(field)

    # Only add noted_missing fields if they are actually None
    # Don't let LLM's incorrect missing_fields override our actual values
    for field in noted_missing:
        if merged.get(field) is None:
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
        "destination": "Where are you headed?",
        "origin": "Which city or airport will you depart from?",
        "start_date": "When does this trip start? Please share the date in YYYY-MM-DD.",
        "end_date": "When will you return? Please share the date in YYYY-MM-DD.",
        "traveler_count": "How many travelers are going?",
        "budget": "What budget should we target? Please share a rough number (e.g. 1500).",
    }

    for field in _TRIP_INPUT_FIELDS:
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

    This is the core LLM integration function. It:
    1. Builds the system prompt with current trip state
    2. Constructs the message history for context
    3. Calls OpenAI with retry logic
    4. Parses and validates the LLM response
    5. Returns structured output (branches, trip_inputs, message)

    ## Why the complex state-aware prompting?

    The current implementation uses explicit state-based prompting (checking
    `all_fields_complete`, `is_last_field`, etc.) rather than a single unified
    prompt. This design choice was made for several reasons:

    1. **Token Efficiency**: Different phases need different response structures.
       When collecting inputs, we don't need branch JSON. When generating branches,
       we don't need field collection logic. Tailored prompts = smaller context.

    2. **Reliability**: LLMs are more reliable with explicit, constrained instructions.
       A single "be smart about what to do" prompt often produces inconsistent results.
       The explicit state machine approach ("you have X, you need Y, do Z") works better.

    3. **Validation Control**: Different phases need different validation. During
       collection, we validate one field at a time. For branch generation, we
       validate all fields together. Explicit phases enable explicit validation.

    4. **Debugging**: When something goes wrong, explicit states make it clear
       which phase failed. A unified prompt makes debugging much harder.

    A simpler unified approach would look like:
    ```
    "Here's the conversation and document state. Figure out what to do."
    ```

    This COULD work with a very capable model (GPT-4+), but in practice it leads to:
    - Inconsistent JSON structure (sometimes branches, sometimes not)
    - Missed field extractions (LLM forgets to update trip_inputs)
    - Confusion about when to generate branches vs. ask questions
    - Higher token usage due to verbose "decide what to do" instructions

    The explicit state machine trades prompt complexity for output reliability.

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
    if _DEBUG_LOG:
        print(f"[DEBUG] prior_trip_inputs_meta: {prior_trip_inputs_meta}")

    # Read trip inputs from document (source of truth)
    doc_trip_inputs: dict = {}
    if document_data and document_data.trip_inputs:
        ti = document_data.trip_inputs
        doc_trip_inputs = {
            "destination": ti.destination,
            "origin": ti.origin,
            "start_date": ti.start_date,
            "end_date": ti.end_date,
            "traveler_count": ti.traveler_count,
            "budget": ti.budget,
        }
    if _DEBUG_LOG:
        print(f"[DEBUG] doc_trip_inputs: {doc_trip_inputs}")

    # Merge: document first, then chat history (for migration/fallback)
    request_trip_inputs = _clean_trip_inputs(
        doc_trip_inputs,
        prior_trip_inputs_meta,
    )
    if _DEBUG_LOG:
        print(f"[DEBUG] request_trip_inputs after merge: {request_trip_inputs}")

    today = _today_iso()
    next_week = _next_week_iso()

    # Build current state summary for the LLM
    known_fields = []
    missing_fields = _ordered_missing_fields_from_inputs(request_trip_inputs)
    for field in _TRIP_INPUT_FIELDS:
        val = request_trip_inputs.get(field)
        if val is not None:
            known_fields.append(f"{field}={val}")

    all_fields_complete = len(missing_fields) == 0 and all(
        request_trip_inputs.get(field) is not None for field in _TRIP_INPUT_FIELDS
    )

    # Determine what the next field to collect is
    next_field_to_ask = missing_fields[0] if missing_fields else None

    # Build a clearer, more structured system prompt
    # If all fields are complete, emphasize branch generation
    state_lines = []
    if known_fields:
        state_lines.append(f"COLLECTED: {', '.join(known_fields)}")
    if missing_fields:
        state_lines.append(f"STILL NEED: {', '.join(missing_fields)}")
    state_summary = "\n".join(state_lines)

    expecting_context = ""
    if next_field_to_ask == "destination":
        expecting_context = """
YOU JUST ASKED: "Where are you headed?" (asking for destination)
The user's message is their DESTINATION. Extract it and set destination to that value."""
    elif next_field_to_ask == "origin":
        origin_val = request_trip_inputs.get("origin")
        if origin_val:
            expecting_context = f"""
YOU JUST ASKED about origin. Current origin from browser: {origin_val}
If user confirms or says nothing specific, keep origin={origin_val}."""
        else:
            expecting_context = """
YOU JUST ASKED: "Where are you leaving from?" (asking for origin)
The user's message is their ORIGIN city."""
    elif next_field_to_ask == "budget":
        expecting_context = """
YOU JUST ASKED: "What's your budget?" (asking for budget)
The user's message is their BUDGET amount. Extract the number."""
    elif next_field_to_ask in ("start_date", "end_date", "traveler_count"):
        expecting_context = f"""
YOU JUST ASKED about {next_field_to_ask}.
The user's message is their answer. Use defaults if they confirm."""

    # Check if this message will complete all fields (only 1 field left)
    is_last_field = len(missing_fields) == 1

    if all_fields_complete:
        complete_trip_inputs = {
            field: request_trip_inputs.get(field) for field in _TRIP_INPUT_FIELDS
        }
        complete_trip_inputs["missing_fields"] = []
        trip_inputs_json = json.dumps(complete_trip_inputs, ensure_ascii=True)
        system_prompt = f"""You are a travel planner. Today is {today}.

ALL TRIP FIELDS ARE COMPLETE:
{', '.join(known_fields)}

Generate 2-3 trip branches now. Do NOT ask questions.

Return JSON:
{{
  "assistant_message": "Great! Here are your trip options.",
  "trip_inputs": {trip_inputs_json},
  "branches": [
    {{
      "label": "Theme",
      "description": "...",
      "destination": "...",
      "origin": "...",
      "start_date": "...",
      "end_date": "...",
      "traveler_count": N,
      "budget": N
    }}
  ]
}}"""
    elif is_last_field:
        system_prompt = f"""You are a travel planner. Today is {today}.

{state_summary}
{expecting_context}

CRITICAL: Extract the value from the user's message. This completes all fields!

After extracting, GENERATE 2-3 TRIP BRANCHES immediately.

Return JSON:
{{
  "assistant_message": "Great! Here are your trip options for [destination].",
  "trip_inputs": {{
    "destination": "value",
    "origin": "value",
    "start_date": "YYYY-MM-DD",
    "end_date": "YYYY-MM-DD",
    "traveler_count": number,
    "budget": number,
    "missing_fields": []
  }},
  "branches": [
    {{
      "label": "Cultural Explorer",
      "description": "Museums, history, local culture",
      "destination": "...",
      "origin": "...",
      "start_date": "...",
      "end_date": "...",
      "traveler_count": N,
      "budget": N
    }},
    {{
      "label": "Food & Relaxation",
      "description": "Local cuisine, cafes, leisure",
      "destination": "...",
      "origin": "...",
      "start_date": "...",
      "end_date": "...",
      "traveler_count": N,
      "budget": N
    }}
  ]
}}"""
    else:
        system_prompt = f"""You are a travel planner collecting trip details. Today is {today}.

{state_summary}
{expecting_context}

CRITICAL: The user's message answers your previous question. Extract the value!

After extracting their answer, ask for the NEXT missing field.
Combine your acknowledgment and question in one message.

Field order to collect:
1. destination - "Where are you headed?"
2. origin - confirm detected location or ask
3. start_date - default {today}
4. end_date - default {next_week}
5. traveler_count - default 1
6. budget - "What's your budget?"

Return JSON only:
{{
  "assistant_message": "Acknowledgment + next question (e.g. 'Great choice! When do you travel?')",
  "trip_inputs": {{
    "destination": "extracted value or null",
    "origin": "value or null",
    "start_date": "YYYY-MM-DD or null",
    "end_date": "YYYY-MM-DD or null",
    "traveler_count": number or null,
    "budget": number or null,
    "missing_fields": ["remaining", "fields"]
  }},
  "branches": []
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
                print(f"[DEBUG] Raw LLM response: {raw_content[:500]}...")
            elif structured_payload:
                struct_str = json.dumps(structured_payload)[:500]
                print(f"[DEBUG] Structured LLM response: {struct_str}...")
            else:
                print(f"[DEBUG] No content extracted from LLM response. Choice: {choice}")

        default_assistant_message = "I'm having trouble processing that. Could you try again?"

        data = structured_payload or _tolerant_json_loads(raw_content or "")
        if _DEBUG_LOG:
            print(f"[DEBUG] Parsed data: {data}")
        if data is None:
            if _DEBUG_LOG:
                snippet = raw_content[:200] if raw_content else "empty"
                print(f"[DEBUG] Failed to parse JSON. Raw: {snippet}")
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
            request_trip_inputs,
            trip_inputs_payload,
            allow_overwrite=True,
        )
        trip_inputs, validation_messages = _validate_trip_inputs(trip_inputs, today_iso=today)
        parsed_missing_fields = trip_inputs.get("missing_fields") or []

        has_all_fields = len(parsed_missing_fields) == 0 and not validation_messages
        if _DEBUG_LOG:
            print(
                f"[DEBUG] all_fields_complete={all_fields_complete}, "
                f"has_all_fields={has_all_fields}, response_missing={parsed_missing_fields}, "
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
                branch_destination = _normalize_str(b.get("destination")) or canonical_inputs.get(
                    "destination"
                )
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

                if not branch_destination:
                    continue

                cleaned.append(
                    {
                        "label": str(b["label"]),
                        "description": str(b.get("description", "")),
                        "destination": branch_destination,
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

        if has_all_fields:
            trip_inputs["missing_fields"] = []
            if not assistant_message or re.search(
                r"\bwhere\b", assistant_message, flags=re.IGNORECASE
            ):
                assistant_message = "Generating trip options for you..."

        output = PlannerLLMOutput(
            branches=cleaned,
            assistant_message=assistant_message,
            trip_inputs=trip_inputs,
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


def plan_trip_flow(db: Session, req: PlanRequest) -> PlanDocumentResponse:
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
        req: PlanRequest containing session_id and user message.

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
    db_session = get_or_create_session(
        db,
        session_token=req.session_id,
        user_external_id=None,  # User ID comes from auth, not request
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
        trip_inputs_payload = trip_inputs_model.model_dump() if trip_inputs_model else None
        assistant_chat.content = planner_output.assistant_message
        assistant_meta: dict[str, Any] = {}
        if trip_inputs_payload:
            # Store trip_inputs in message metadata for migration compatibility
            assistant_meta["trip_inputs"] = trip_inputs_payload
        assistant_chat.meta = assistant_meta or None

        # 6. Get or create the PlanDocument
        plan_doc = get_or_create_document(db, session=db_session, updated_by="planner")

        # 7. Build document branches and tiles from LLM output
        branch_specs = planner_output.branches or []
        doc_branches: List[DocumentBranch] = []
        tiles_dict: dict[str, TileSchema] = {}
        primary_branch: Optional[DocumentBranch] = None

        for idx, spec in enumerate(branch_specs):
            # Generate a unique branch ID
            branch_id = f"branch_{trip_ctx.id}_{idx}"

            doc_branch = DocumentBranch(
                id=branch_id,
                label=str(spec.get("label", "")),
                description=str(spec.get("description", "")),
                destination=str(spec.get("destination", "")),
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

            tiles_request = TilesSearchRequest(
                user_id=None,  # User ID comes from auth, not request
                session_id=req.session_id,
                trip_context_id=trip_ctx.id,
                destination=primary_branch.destination,
                destination_hint=primary_branch.destination,
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
                destination=trip_inputs_model.destination,
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

        # Reconstruct the document data with chat fields
        doc_data_with_chat = PlanDocumentData(**doc_data_dict)

        response = PlanDocumentResponse(
            version=plan_doc.version,
            updated_by=plan_doc.updated_by,  # type: ignore[arg-type]
            document=doc_data_with_chat,
            updated_at=plan_doc.updated_at.isoformat(),
        )

        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def plan_trip(db: Session, req: PlanRequest) -> PlanDocumentResponse:
    """
    Public API entry point for trip planning.

    This is a simple wrapper around plan_trip_flow that serves as the
    stable public interface. Internal implementation details may change,
    but this function signature remains stable.

    Args:
        db: SQLAlchemy database session.
        req: PlanRequest containing session_id and user message.

    Returns:
        PlanDocumentResponse: Complete planning response with document state.

    See Also:
        plan_trip_flow: The actual implementation with full documentation.
    """
    return plan_trip_flow(db, req)
