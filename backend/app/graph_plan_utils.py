"""
Utility functions for the /v1/graph_plan route.

This module provides:
- Session state sanitization and validation
- Trip input normalization (currency, destinations, dates)
- Output validation (suggested responses, message truncation)
- Today ISO computation with server timezone
- JSON parsing with recovery (PR-D extraction)
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ValidationError

from app.config import settings

# TypeVar for generic Pydantic model parsing
T = TypeVar("T", bound=BaseModel)

# =============================================================================
# Constants
# =============================================================================

# Server timezone for consistent date handling
logger = logging.getLogger(__name__)

try:
    SERVER_TZ = ZoneInfo("Europe/Amsterdam")
except ZoneInfoNotFoundError:
    logger.warning("Time zone Europe/Amsterdam not found; falling back to UTC")
    SERVER_TZ = ZoneInfo("UTC")

# ISO-4217 currency codes we accept
ISO_4217_CURRENCIES: Set[str] = {
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

# Currency symbol to ISO code mapping
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
    "kr": "SEK",  # Also used for NOK, DKK
    "CHF": "CHF",
    "A$": "AUD",
    "C$": "CAD",
    "NZ$": "NZD",
    "HK$": "HKD",
    "S$": "SGD",
}


# =============================================================================
# Today ISO Computation
# =============================================================================


def compute_today_iso() -> str:
    """
    Compute today's date in ISO format using server timezone.

    This should be called once at route ingress and passed to all nodes.

    Returns:
        str: Today's date in YYYY-MM-DD format (server TZ).
    """
    return datetime.now(SERVER_TZ).date().isoformat()


# =============================================================================
# Request ID Generation
# =============================================================================


def generate_request_id() -> str:
    """Generate a unique request ID for tracking."""
    return str(uuid.uuid4())


# =============================================================================
# Thread ID Validation
# =============================================================================


def is_valid_thread_id(thread_id: Any) -> bool:
    """
    Check if thread_id is a valid UUID.

    Args:
        thread_id: The thread ID to validate.

    Returns:
        bool: True if valid UUID, False otherwise.
    """
    if thread_id is None:
        return False

    if not isinstance(thread_id, str):
        return False

    try:
        uuid.UUID(thread_id)
        return True
    except ValueError:
        return False


def ensure_thread_id(thread_id: Any) -> str:
    """
    Validate thread_id is a valid UUID, or generate a new one.

    Args:
        thread_id: The thread ID to validate (may be None or invalid).

    Returns:
        str: A valid UUID string (existing if valid, new if not).
    """
    if is_valid_thread_id(thread_id):
        return thread_id
    return str(uuid.uuid4())


# Backwards compatibility alias
# =============================================================================
# Session State Sanitization
# =============================================================================


def sanitize_session_state(
    session_state: Optional[Dict[str, Any]],
    explicit_nulls: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """
    Sanitize session_state by keeping only allowed keys.

    Args:
        session_state: Raw session state from client.
        explicit_nulls: Set of field names explicitly set to null by UI.

    Returns:
        Dict with only allowed keys, validated thread_id.
    """
    if session_state is None:
        return {
            "thread_id": str(uuid.uuid4()),
            "trip_inputs": {},
            "metadata": {},
            "flags": {},
            "last_summary": None,
            "branches": [],
            "suggested_responses": [],
            "errors": [],
        }

    if not isinstance(session_state, dict):
        session_state = {}

    # Drop only known-dangerous prototype-pollution keys; keep other keys for forward-compat.
    dangerous_keys = {"__proto__", "constructor", "prototype"}
    sanitized: Dict[str, Any] = {
        key: value for key, value in session_state.items() if key not in dangerous_keys
    }

    # Ensure thread_id is valid (returns valid UUID or generates new one)
    sanitized["thread_id"] = ensure_thread_id(sanitized.get("thread_id"))

    # Ensure required keys exist with defaults
    sanitized.setdefault("trip_inputs", {})
    sanitized.setdefault("metadata", {})
    sanitized.setdefault("flags", {})
    sanitized.setdefault("branches", [])
    sanitized.setdefault("suggested_responses", [])
    sanitized.setdefault("errors", [])

    if not isinstance(sanitized.get("trip_inputs"), dict):
        sanitized["trip_inputs"] = {}
    if not isinstance(sanitized.get("metadata"), dict):
        sanitized["metadata"] = {}
    if not isinstance(sanitized.get("flags"), dict):
        sanitized["flags"] = {}

    # Store explicit nulls in metadata for merge logic
    if explicit_nulls:
        sanitized["metadata"]["explicit_nulls"] = list(explicit_nulls)

    return sanitized


# =============================================================================
# Currency Normalization
# =============================================================================


def normalize_currency(value: Any) -> Optional[str]:
    """
    Normalize currency to ISO-4217 code.

    Maps symbols ($, €, £) to codes and validates against ISO-4217 set.

    Args:
        value: Currency string (symbol or code).

    Returns:
        ISO-4217 code if valid, None otherwise.
    """
    if value is None:
        return None

    if not isinstance(value, str):
        return None

    value = value.strip()
    if not value:
        return None

    # Check if it's a symbol
    if value in CURRENCY_SYMBOL_MAP:
        return CURRENCY_SYMBOL_MAP[value]

    # Uppercase and check against ISO codes
    upper = value.upper()
    if upper in ISO_4217_CURRENCIES:
        return upper

    # Check if symbol is part of value (e.g., "$100" -> extract $)
    for symbol, code in CURRENCY_SYMBOL_MAP.items():
        if value.startswith(symbol):
            return code

    return None


# =============================================================================
# Destination Normalization
# =============================================================================


def normalize_destinations(destinations: Any, max_count: Optional[int] = None) -> List[str]:
    """
    Normalize destinations list with NFC, trim, and case-insensitive dedupe.

    Preserves original casing for display while deduplicating.
    Strips country suffixes in "Place, Country" format (e.g., "Banff, Canada" -> "Banff").

    Args:
        destinations: Raw destinations list.
        max_count: Maximum number of destinations (uses config default if None).

    Returns:
        Normalized, deduplicated list of destinations.
    """
    if max_count is None:
        max_count = settings.max_destinations

    if not isinstance(destinations, list):
        return []

    seen_lower: Set[str] = set()
    result: List[str] = []

    def _strip_country_suffix(text: str) -> str:
        """Strip country suffix in 'Place, Country' format."""
        if ", " not in text:
            return text

        # Split on last comma to handle cases like "New York City, USA"
        parts = text.rsplit(", ", 1)
        if len(parts) != 2:
            return text

        place, potential_country = parts

        # Common country names and codes to strip
        countries = {
            "usa",
            "us",
            "united states",
            "united states of america",
            "uk",
            "united kingdom",
            "england",
            "great britain",
            "canada",
            "australia",
            "france",
            "germany",
            "italy",
            "spain",
            "japan",
            "china",
            "india",
            "brazil",
            "mexico",
            "netherlands",
            "switzerland",
            "austria",
            "belgium",
            "portugal",
            "greece",
            "turkey",
            "thailand",
            "vietnam",
            "indonesia",
            "malaysia",
            "singapore",
            "philippines",
            "south korea",
            "korea",
            "taiwan",
            "new zealand",
            "ireland",
            "scotland",
            "wales",
            "norway",
            "sweden",
            "denmark",
            "finland",
            "iceland",
            "poland",
            "czech republic",
            "czechia",
            "hungary",
            "croatia",
            "slovenia",
            "romania",
            "bulgaria",
            "egypt",
            "morocco",
            "south africa",
            "kenya",
            "tanzania",
            "argentina",
            "chile",
            "peru",
            "colombia",
            "costa rica",
            "panama",
            "cuba",
            "jamaica",
            "bahamas",
            "dominican republic",
            "puerto rico",
            "uae",
            "united arab emirates",
            "dubai",
            "qatar",
            "saudi arabia",
            "israel",
            "jordan",
            "lebanon",
            "russia",
            "ukraine",
        }

        if potential_country.lower().strip() in countries:
            return place.strip()

        return text

    for dest in destinations:
        if not isinstance(dest, str):
            continue

        # Unicode NFC normalization + trim + collapse whitespace
        normalized = normalize_text(dest)
        if not normalized:
            continue

        # Strip country suffix (e.g., "Banff, Canada" -> "Banff")
        normalized = _strip_country_suffix(normalized)

        # Case-insensitive deduplication
        lower = normalized.lower()
        if lower in seen_lower:
            continue

        def _title_case_place(text: str) -> str:
            # Preserve short all-caps tokens (e.g., "EBC", "USA")
            if text.isupper() and len(text) <= 4:
                return text

            # Title-case words, preserving hyphens/apostrophes reasonably.
            words: List[str] = []
            for word in text.split():
                parts = []
                for part in word.split("-"):
                    if not part:
                        parts.append(part)
                        continue
                    first = part[0].upper()
                    rest = part[1:].lower() if len(part) > 1 else ""
                    parts.append(first + rest)
                words.append("-".join(parts))
            return " ".join(words)

        seen_lower.add(lower)
        result.append(_title_case_place(normalized))

        # Enforce max count
        if len(result) >= max_count:
            break

    return result


def normalize_text(text: str) -> str:
    """
    Normalize text with Unicode NFC, trim, and whitespace collapse.

    Args:
        text: Raw text string.

    Returns:
        Normalized string.
    """
    if not isinstance(text, str):
        return ""

    # Unicode NFC normalization
    text = unicodedata.normalize("NFC", text)

    # Trim and collapse repeated whitespace
    text = " ".join(text.split())

    return text


# =============================================================================
# Numeric Clamping
# =============================================================================


def clamp_adults(value: Any) -> Optional[int]:
    """Clamp adults to valid range (≥1)."""
    if value is None:
        return None
    try:
        v = int(value)
        return max(1, v) if v > 0 else None
    except (ValueError, TypeError):
        return None


def clamp_children(value: Any) -> Optional[int]:
    """Clamp children to valid range (≥0)."""
    if value is None:
        return None
    try:
        v = int(value)
        return max(0, v)
    except (ValueError, TypeError):
        return None


def clamp_budget(value: Any) -> Optional[int]:
    """Clamp budget to valid range (≥0)."""
    if value is None:
        return None
    try:
        v = int(float(value))  # Handle float input
        return max(0, v)
    except (ValueError, TypeError):
        return None


# =============================================================================
# Date Normalization
# =============================================================================


def normalize_date(date_value: Any) -> Optional[str]:
    """
    Normalize date to YYYY-MM-DD format.

    Handles various input formats:
    - Already correct: "2026-02-01" -> "2026-02-01"
    - ISO with time: "2026-02-01T00:00:00.000Z" -> "2026-02-01"
    - ISO with timezone: "2026-02-01T12:00:00+00:00" -> "2026-02-01"

    Returns:
        Date string in YYYY-MM-DD format, or None if invalid.
    """
    if date_value is None:
        return None
    if not isinstance(date_value, str):
        return None

    date_str = date_value.strip()
    if not date_str:
        return None

    # Handle ISO format with time (2026-02-01T00:00:00.000Z)
    if "T" in date_str:
        date_str = date_str.split("T")[0]

    # Validate the format is YYYY-MM-DD
    if len(date_str) == 10 and date_str[4] == "-" and date_str[7] == "-":
        try:
            # Validate it's a real date
            year, month, day = date_str.split("-")
            if 1 <= int(month) <= 12 and 1 <= int(day) <= 31:
                return date_str
        except (ValueError, IndexError):
            pass

    return None


# =============================================================================
# Trip Inputs Normalization
# =============================================================================


def normalize_trip_inputs(trip_inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize trip inputs with validation and clamping.

    Args:
        trip_inputs: Raw trip inputs dict.

    Returns:
        Normalized trip inputs dict.
    """
    if not isinstance(trip_inputs, dict):
        return {}

    result: Dict[str, Any] = {}

    # Destination (single destination only)
    if "destination" in trip_inputs:
        dest = trip_inputs["destination"]
        if dest is not None:
            result["destination"] = normalize_text(str(dest)) or None
        else:
            result["destination"] = None

    # Origin (text normalization)
    if "origin" in trip_inputs:
        origin = trip_inputs["origin"]
        if origin is not None:
            result["origin"] = normalize_text(str(origin)) or None
        else:
            result["origin"] = None

    # Dates (normalize to YYYY-MM-DD format)
    for date_field in ("start_date", "end_date"):
        if date_field in trip_inputs:
            result[date_field] = normalize_date(trip_inputs[date_field])

    # Numeric fields with clamping
    if "adults" in trip_inputs:
        result["adults"] = clamp_adults(trip_inputs["adults"])

    if "children" in trip_inputs:
        result["children"] = clamp_children(trip_inputs["children"])

    if "budget" in trip_inputs:
        result["budget"] = clamp_budget(trip_inputs["budget"])

    # Currency normalization
    if "currency" in trip_inputs:
        currency = normalize_currency(trip_inputs["currency"])
        if currency:
            result["currency"] = currency

    # Pass through other valid fields
    passthrough_fields = {
        "requires_assistance",
        "booking_types",
        "flight_settings",
        "hotel_settings",
        "activity_settings",
        "transport_settings",
        "strategy_settings",
        "missing_fields",
    }

    for field in passthrough_fields:
        if field in trip_inputs:
            result[field] = trip_inputs[field]

    return result


# =============================================================================
# Suggested Responses Validation
# =============================================================================


def validate_suggested_responses(responses: Any) -> List[str]:
    """
    Validate and filter suggested responses.

    Rules:
    - Max 3 items
    - 1-8 words each (single-word destinations like "Norway" are valid)
    - No question marks

    Args:
        responses: Raw suggested responses list.

    Returns:
        Filtered list of valid responses.
    """
    if not isinstance(responses, list):
        return []

    max_count = settings.max_suggested_responses
    result: List[str] = []

    for resp in responses:
        if not isinstance(resp, str):
            continue

        resp = resp.strip()
        if not resp:
            continue

        # No question marks
        if "?" in resp:
            continue

        # Word count check (1-8 words) - single-word destinations are valid
        words = resp.split()
        if len(words) < 1 or len(words) > 8:
            continue

        result.append(resp)

        if len(result) >= max_count:
            break

    return result


# =============================================================================
# Assistant Message Truncation
# =============================================================================


def truncate_assistant_message(message: Any) -> str:
    """
    Truncate assistant message to configured max length gracefully.

    This is the synchronous fallback. For better results, use the async
    condense_long_message() from plan_graph.py which uses LLM re-summarization.

    Args:
        message: Raw assistant message.

    Returns:
        Truncated message string.
    """
    if message is None:
        return ""

    if not isinstance(message, str):
        message = str(message)

    max_len = settings.assistant_msg_max_len

    if len(message) <= max_len:
        return message

    # Graceful truncation at natural boundary
    target = max_len - 3

    if target <= 0:
        return message[:max_len]

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


# =============================================================================
# Payload Size Validation
# =============================================================================

# Maximum payload size in bytes (200KB)
MAX_PAYLOAD_SIZE_BYTES = 200 * 1024


def check_payload_size(request: Any) -> Optional[str]:
    """
    Check if payload size is within limits.

    Args:
        request: FastAPI Request object.

    Returns:
        Error message if too large, None if OK.
    """
    # Try to get Content-Length from request headers
    content_length = None

    if hasattr(request, "headers"):
        content_length_str = request.headers.get("content-length")
        if content_length_str:
            try:
                content_length = int(content_length_str)
            except (ValueError, TypeError):
                pass

    if content_length is None:
        return None  # Allow if not specified (will be checked at parsing)

    if content_length > MAX_PAYLOAD_SIZE_BYTES:
        return (
            f"Payload too large: {content_length} bytes exceeds {MAX_PAYLOAD_SIZE_BYTES} byte limit"
        )

    return None


# =============================================================================
# PR-D: JSON PARSING UTILITIES (Extracted from plan_graph.py)
# =============================================================================
# These functions provide robust JSON parsing with multiple recovery strategies
# for handling malformed LLM output.


def truncate_to_balanced_json(raw: str) -> Optional[str]:
    """
    Extract a valid JSON object from a potentially truncated or malformed string.

    LLMs sometimes return incomplete JSON or include extra text before/after the JSON.
    This function finds the first complete, balanced JSON object in the string.

    Args:
        raw: Raw string potentially containing JSON

    Returns:
        Extracted balanced JSON string, or None if not found
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

    Args:
        s: JSON string to parse

    Returns:
        Parsed dict, or empty dict on failure
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
    trimmed = truncate_to_balanced_json(s)
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

    # Return empty dict on failure
    logger.warning("JSON parse failed: %s", s[:100] if len(s) > 100 else s)
    return {}


def parse_llm_output(
    raw: str,
    model: type[T],
    fallback: T | None = None,
) -> T:
    """
    Parse LLM output with Pydantic validation and optional fallback.

    Uses jloads_safe() for resilient JSON extraction, then validates
    against the provided Pydantic model.

    Args:
        raw: Raw LLM output string (potentially malformed JSON)
        model: Pydantic model class to validate against
        fallback: Optional fallback instance if validation fails.
                  If None and validation fails, raises ValidationError.

    Returns:
        Validated Pydantic model instance

    Raises:
        ValidationError: If validation fails and no fallback provided
    """
    data = jloads_safe(raw)
    try:
        return model.model_validate(data)
    except ValidationError:
        if fallback is not None:
            logger.warning(
                "Pydantic validation failed for %s, using fallback",
                model.__name__,
            )
            return fallback
        raise


def extract_message_from_malformed_json(raw: str) -> Optional[str]:
    """
    Try to extract assistant_message content from truncated/malformed JSON.

    This is a recovery mechanism when LLM output gets truncated or has JSON errors.
    It uses regex to find the assistant_message field value even if the JSON is incomplete.

    Args:
        raw: The raw LLM output string (potentially malformed JSON)

    Returns:
        The extracted message content, or None if extraction failed
    """
    if not raw:
        return None

    # Pattern 1: Match "assistant_message": "..." with proper quote handling
    # This handles cases where the message is complete but other parts are truncated
    pattern1 = re.compile(
        r'"assistant_message"\s*:\s*"((?:[^"\\]|\\.)*)(?:"|$)',
        re.DOTALL,
    )

    # Pattern 2: Match with single quotes (some LLMs use this)
    pattern2 = re.compile(
        r"['\"]assistant_message['\"]\s*:\s*['\"](.+?)(?:['\"]|$)",
        re.DOTALL,
    )

    for pattern in [pattern1, pattern2]:
        match = pattern.search(raw)
        if match:
            message = match.group(1)
            # Unescape JSON escape sequences
            try:
                # Try to parse as JSON string to handle escapes properly
                message = json.loads(f'"{message}"')
            except (json.JSONDecodeError, ValueError):
                # Fallback: manual unescape of common sequences
                message = (
                    message.replace('\\"', '"')
                    .replace("\\n", "\n")
                    .replace("\\t", "\t")
                    .replace("\\\\", "\\")
                )

            # Validate: message should be reasonably long and not truncated mid-word
            if len(message) > 50:
                # Check if message appears truncated (ends mid-sentence without punctuation)
                if message.rstrip()[-1:] not in ".!?:;)\"'":
                    # Try to find a natural break point
                    for punct in [".", "!", "?", "\n"]:
                        last_punct = message.rfind(punct)
                        if last_punct > len(message) // 2:  # At least half the content
                            message = message[: last_punct + 1]
                            break
                return message.strip()

    return None
