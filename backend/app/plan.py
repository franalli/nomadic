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


_CHAT_HISTORY_LIMIT = int(os.getenv("PLAN_CHAT_HISTORY_LIMIT", "20"))  # messages
_MAX_TOKENS = int(os.getenv("OPENAI_PLAN_MAX_TOKENS", "800"))  # enough for JSON response
_PLAN_TEMPERATURE = float(os.getenv("OPENAI_PLAN_TEMPERATURE", "0.75"))
_PLAN_TOP_P = float(os.getenv("OPENAI_PLAN_TOP_P", "0.95"))
_PLAN_MAX_RETRIES = int(os.getenv("OPENAI_PLAN_MAX_RETRIES", "3"))
_PLAN_SEED = os.getenv("OPENAI_PLAN_SEED")

_openai_client: Optional[OpenAI] = None
_DEBUG_LOG = bool(os.getenv("DEBUG_PLAN_MESSAGES"))

_TRIP_INPUT_FIELDS = (
    "destination",
    "origin",
    "start_date",
    "end_date",
    "traveler_count",
    "budget",
)


def _today_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _next_week_iso() -> str:
    return (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d")


def _get_openai_client() -> Optional[OpenAI]:
    global _openai_client

    api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    if _openai_client is None:
        _openai_client = OpenAI(api_key=api_key)

    return _openai_client


def _serialize_document_for_llm(doc_data: Optional[PlanDocumentData]) -> Optional[str]:
    """
    Serialize the full PlanDocumentData into a readable format for the LLM.
    This includes all branches, tiles, and selections so the LLM has complete context.
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


def _latest_trip_state_from_history(
    history_rows: List[models.ChatMessage],
) -> Optional[dict]:
    """
    Pull the most recent trip_inputs from assistant metadata
    for fallback/migration from older sessions.
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


def _plan_model_name() -> str:
    """Return the configured OpenAI model name, requiring an explicit env setting."""

    model_name = os.getenv("OPENAI_PLAN_MODEL", "").strip()
    if not model_name:
        raise RuntimeError("OPENAI_PLAN_MODEL is required for planning")
    return model_name


def _coerce_delta_content(delta_content: Any) -> str:
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
    """Return either structured JSON payload or fallback raw text from a choice."""

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
    Trim a raw JSON-like string to the last balanced closing brace while being
    aware of quoted strings and escape characters.
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


def _normalize_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    value_str = str(value).strip()
    return value_str or None


def _relative_date_to_iso(text: Optional[str]) -> Optional[str]:
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
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None


def _normalize_int(value: Any) -> Optional[int]:
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
    if value is None:
        return None
    return max(1, min(20, value))


def _ordered_missing_fields_from_inputs(trip_inputs: dict) -> List[str]:
    return [field for field in _TRIP_INPUT_FIELDS if trip_inputs.get(field) is None]


def _clean_trip_inputs(
    *sources: Any,
    fallback: Optional[dict] = None,
    allow_overwrite: bool = False,
    overwrite_fields: Optional[Iterable[str]] = None,
) -> dict:
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
    Ensure dates and numeric fields are sane. Returns the cleaned inputs and any
    validation messages that require user confirmation before generating branches.
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


def _history_to_messages(history: List[models.ChatMessage]) -> List[ChatCompletionMessageParam]:
    messages: List[ChatCompletionMessageParam] = []
    for entry in history:
        content = entry.content or ""
        # Skip empty messages (e.g., unfilled assistant placeholders)
        if not content.strip():
            continue
        messages.append(cast(ChatCompletionMessageParam, {"role": entry.role, "content": content}))
    return messages


def _resolve_parent_trip_context(
    db: Session,
    *,
    session: models.Session,
    requested_parent_id: Optional[int],
) -> Optional[models.TripContext]:
    parent_ctx: Optional[models.TripContext] = None

    if requested_parent_id is not None:
        parent_ctx = db.get(models.TripContext, requested_parent_id)
        if not parent_ctx:
            raise ValueError("trip_context_id not found")
        if parent_ctx.session_id != session.id:
            raise ValueError("trip_context_id does not belong to this session")
        return parent_ctx

    return get_latest_trip_context_for_session(db, session=session)


def _call_openai_for_plan(
    req: PlanRequest,
    *,
    history_rows: List[models.ChatMessage],
    history: List[ChatCompletionMessageParam],
    document_data: Optional[PlanDocumentData] = None,
) -> PlannerLLMOutput:
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

        if "gpt-4" in model_name.lower():
            params: dict[str, Any] = {
                "model": model_name,
                "messages": messages,
                "max_tokens": _MAX_TOKENS,
                "temperature": _PLAN_TEMPERATURE,
                "top_p": _PLAN_TOP_P,
                "response_format": {"type": "json_object"},
                "seed": seed_value,
            }
        elif "gpt-5" in model_name.lower():
            params: dict[str, Any] = {
                "model": model_name,
                "messages": messages,
                "max_completion_tokens": _MAX_TOKENS,
                "response_format": {"type": "json_object"},
                "seed": seed_value,
            }
        else:
            raise RuntimeError(f"Unsupported model for planning: {model_name}")

        result = client.chat.completions.create(**params)
        return result

    def _invoke_with_retries():
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
        try:
            choice = completion.choices[0] if completion and completion.choices else None
            if choice is not None:
                structured_payload, raw_content = _extract_message_payload(choice)
        except Exception:
            raw_content = ""

        if _DEBUG_LOG and raw_content:
            print(f"[DEBUG] Raw LLM response: {raw_content[:500]}...")
        elif _DEBUG_LOG and structured_payload:
            print(f"[DEBUG] Structured LLM response: {json.dumps(structured_payload)[:500]}...")

        default_assistant_message = "I'm having trouble processing that. Could you try again?"

        data = structured_payload or _tolerant_json_loads(raw_content or "")
        if data is None:
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


def plan_trip_flow(db: Session, req: PlanRequest) -> PlanDocumentResponse:
    """
    Main planning flow that returns a PlanDocumentResponse.
    All state is stored in the centralized PlanDocument.
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
    return plan_trip_flow(db, req)
