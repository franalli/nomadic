import json
import os
import re
from datetime import datetime
from typing import Any, Generator, List, Optional, cast

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from sqlalchemy.orm import Session

from app import db_models as models
from app.config import settings
from app.crud_trip import (
    create_branches_for_context,
    create_trip_context,
    fetch_chat_history,
    get_latest_trip_context_for_session,
    get_or_create_session,
    record_chat_message,
    snapshot_tiles_for_branch,
)
from app.schemas import (
    PlanBranch,
    PlanRequest,
    PlanResponse,
    TilesSearchRequest,
    TilesSearchResponse,
    TripInputs,
)
from app.tile_service import search_tiles


class PlannerLLMOutput:
    def __init__(
        self,
        *,
        branches: List[dict],
        assistant_message: str,
        follow_up_question: Optional[str] = None,
        trip_inputs: Optional[dict] = None,
    ) -> None:
        self.branches = branches
        self.assistant_message = assistant_message
        self.follow_up_question = follow_up_question
        self.trip_inputs = trip_inputs or {}


_CHAT_HISTORY_LIMIT = int(os.getenv("PLAN_CHAT_HISTORY_LIMIT", "20"))  # messages
_STREAM_MIN_FLUSH_CHARS = int(os.getenv("PLAN_STREAM_MIN_CHARS", "5"))  # chars
_MAX_TOKENS = int(os.getenv("OPENAI_PLAN_MAX_TOKENS", "800"))  # enough for JSON response

_openai_client: Optional[OpenAI] = None

_TRIP_INPUT_FIELDS = (
    "destination",
    "origin",
    "start_date",
    "end_date",
    "traveler_count",
    "budget",
)

# Frontend default values - ignore these unless user explicitly changed them
# Note: origin can be auto-detected from browser geolocation, so we don't have
# a fixed default for it - we only ignore it if it matches the hardcoded fallback
_FRONTEND_DEFAULTS = {
    "origin": "Oslo",  # Only the fallback, not geo-detected values
    "traveler_count": 1,
}


def _today_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _next_week_iso() -> str:
    from datetime import timedelta

    return (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d")


def _extract_user_edited_inputs(frontend_inputs: dict) -> dict:
    """
    Filter frontend inputs to include user-edited values AND geo-detected origin.

    We keep ALL values the frontend sends, EXCEPT for these exact defaults which
    indicate the user hasn't touched them:
    - origin="Amsterdam" (the hardcoded fallback - geo-detected values like "Oslo" are kept)

    We DO keep dates and traveler_count even if they match defaults, because:
    1. The user sees these values in the UI
    2. We want to use them as starting points (just confirm, don't ask fresh)
    """
    if not frontend_inputs:
        return {}

    result = {}

    for field, value in frontend_inputs.items():
        if field == "missing_fields":
            continue
        if value is None:
            continue

        # Only filter out the hardcoded fallback origin "Amsterdam"
        # Keep everything else including default dates and traveler_count
        if field == "origin" and value == _FRONTEND_DEFAULTS.get("origin"):
            continue

        result[field] = value

    return result


class _AssistantMessageParser:
    """Incrementally pull the assistant_message string out of a streaming JSON body."""

    def __init__(self) -> None:
        self._key = '"assistant_message"'
        self._key_idx = 0
        self._waiting_colon = False
        self._waiting_quote = False
        self._capturing = False
        self._escape = False
        self._unicode_buffer: List[str] | None = None
        self._complete = False
        self._parts: List[str] = []

    @property
    def text(self) -> str:
        return "".join(self._parts)

    @property
    def complete(self) -> bool:
        return self._complete

    def _reset_search(self) -> None:
        self._key_idx = 0
        self._waiting_colon = False
        self._waiting_quote = False
        self._capturing = False
        self._escape = False
        self._unicode_buffer = None

    def _decode_escape(self, char: str) -> Optional[str]:
        if char == "u":
            self._unicode_buffer = []
            return None

        mapping = {
            '"': '"',
            "\\": "\\",
            "/": "/",
            "b": "\b",
            "f": "\f",
            "n": "\n",
            "r": "\r",
            "t": "\t",
        }
        return mapping.get(char, char)

    def feed(self, chunk: str) -> str:
        new_chars: List[str] = []
        for char in chunk:
            if self._complete:
                continue

            if not self._capturing:
                if self._key_idx < len(self._key):
                    if char == self._key[self._key_idx]:
                        self._key_idx += 1
                        if self._key_idx == len(self._key):
                            self._waiting_colon = True
                    else:
                        self._key_idx = 1 if char == self._key[0] else 0
                    continue

                if self._waiting_colon:
                    if char == ":":
                        self._waiting_colon = False
                        self._waiting_quote = True
                    elif char in " \t\r\n":
                        continue
                    else:
                        self._reset_search()
                    continue

                if self._waiting_quote:
                    if char in " \t\r\n":
                        continue
                    if char == '"':
                        self._capturing = True
                    else:
                        self._reset_search()
                    continue

                continue

            if self._unicode_buffer is not None:
                if char.lower() in "0123456789abcdef":
                    self._unicode_buffer.append(char)
                    if len(self._unicode_buffer) == 4:
                        try:
                            decoded = chr(int("".join(self._unicode_buffer), 16))
                        except ValueError:
                            decoded = ""
                        self._parts.append(decoded)
                        new_chars.append(decoded)
                        self._unicode_buffer = None
                    continue
                self._unicode_buffer = None
                self._escape = False
                continue

            if self._escape:
                decoded = self._decode_escape(char)
                self._escape = False
                if decoded is None:
                    continue
                self._parts.append(decoded)
                new_chars.append(decoded)
                continue

            if char == "\\":
                self._escape = True
                continue

            if char == '"':
                self._capturing = False
                self._complete = True
                continue

            self._parts.append(char)
            new_chars.append(char)

        return "".join(new_chars)


def _get_openai_client() -> Optional[OpenAI]:
    global _openai_client

    api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    if _openai_client is None:
        _openai_client = OpenAI(api_key=api_key)

    return _openai_client


def _latest_trip_state_from_history(
    history_rows: List[models.ChatMessage],
) -> tuple[Optional[dict], Optional[str]]:
    """
    Pull the most recent trip_inputs and follow_up_question from assistant metadata
    so the LLM can stay grounded in prior confirmations.
    """

    merged_trip_inputs: Optional[dict] = None
    last_follow_up_question: Optional[str] = None

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

        fu = meta.get("follow_up_question")
        if isinstance(fu, str) and fu.strip():
            last_follow_up_question = fu.strip()

    return merged_trip_inputs, last_follow_up_question


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
            text_value = getattr(entry, "text", None)
            if text_value:
                parts.append(str(text_value))
            elif isinstance(entry, str):
                parts.append(entry)
        return "".join(parts)

    text_value = getattr(delta_content, "text", None)
    if text_value:
        return str(text_value)

    return str(delta_content)


def _normalize_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    value_str = str(value).strip()
    return value_str or None


def _normalize_date(value: Any) -> Optional[str]:
    text = _normalize_str(value)
    if not text:
        return None

    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue

    iso_match = re.match(r"^\d{4}-\d{2}-\d{2}$", text)
    return text if iso_match else None


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


def _clean_trip_inputs(
    *sources: Any,
    fallback: Optional[dict] = None,
    allow_overwrite: bool = False,
) -> dict:
    sentinel = object()
    merged: dict[str, Any] = {field: sentinel for field in _TRIP_INPUT_FIELDS}
    noted_missing: set[str] = set()

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
            else:
                normalizer = _normalize_str
            value = normalizer(source.get(field))
            current_value = merged[field]
            if value is not None:
                if current_value in (sentinel, None) or allow_overwrite:
                    merged[field] = value
            elif current_value is sentinel:
                merged[field] = None

    for source in sources:
        _ingest(source)
    if fallback is not None:
        _ingest(fallback)

    if merged.get("traveler_count") not in (sentinel, None):
        merged["traveler_count"] = _clamp_traveler_count(merged.get("traveler_count"))

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
    for field in sorted(final_missing):
        if field not in ordered_missing:
            ordered_missing.append(field)

    merged["missing_fields"] = ordered_missing
    return merged


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
        # For assistant messages, append follow_up_question from meta if present
        if entry.role == "assistant":
            meta = getattr(entry, "meta", None)
            if isinstance(meta, dict):
                follow_up = meta.get("follow_up_question")
                if follow_up and isinstance(follow_up, str):
                    content = f"{content}\n\n{follow_up}" if content else follow_up
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
    message_id: str,
) -> Generator[dict, None, PlannerLLMOutput]:
    # Get trip state from conversation history
    prior_trip_inputs_meta, last_follow_up = _latest_trip_state_from_history(history_rows)
    print(f"[DEBUG] prior_trip_inputs_meta: {prior_trip_inputs_meta}")
    print(f"[DEBUG] last_follow_up: {last_follow_up}")

    # Frontend sends defaults (Amsterdam, today, next week, 1 traveler).
    # Only use frontend values if they differ from defaults (user edited them).
    frontend_inputs = req.trip_inputs.dict() if req.trip_inputs is not None else {}
    user_edited_inputs = _extract_user_edited_inputs(frontend_inputs)
    print(f"[DEBUG] frontend_inputs: {frontend_inputs}")
    print(f"[DEBUG] user_edited_inputs: {user_edited_inputs}")

    # Merge: conversation history first, then user-edited frontend values on top
    request_trip_inputs = _clean_trip_inputs(
        prior_trip_inputs_meta,
        user_edited_inputs,
        allow_overwrite=True,
    )
    print(f"[DEBUG] request_trip_inputs after merge: {request_trip_inputs}")

    today = _today_iso()
    next_week = _next_week_iso()

    # Build current state summary for the LLM
    known_fields = []
    missing_fields = []
    for field in _TRIP_INPUT_FIELDS:
        val = request_trip_inputs.get(field)
        if val is not None:
            known_fields.append(f"{field}={val}")
        else:
            missing_fields.append(field)

    all_fields_complete = len(missing_fields) == 0

    # Determine what the next field to collect is
    next_field_to_ask = missing_fields[0] if missing_fields else None

    # Build a clearer, more structured system prompt
    # If all fields are complete, emphasize branch generation
    if all_fields_complete:
        system_prompt = f"""You are a travel planner. Today is {today}.

ALL TRIP FIELDS ARE COMPLETE:
{', '.join(known_fields)}

Generate 2-3 trip branches now. Do NOT ask questions.

Return JSON:
{{
  "assistant_message": "Great! Here are your trip options.",
  "follow_up_question": null,
  "trip_inputs": {{
    "destination": "{request_trip_inputs.get('destination')}",
    "origin": "{request_trip_inputs.get('origin')}",
    "start_date": "{request_trip_inputs.get('start_date')}",
    "end_date": "{request_trip_inputs.get('end_date')}",
    "traveler_count": {request_trip_inputs.get('traveler_count')},
    "budget": {request_trip_inputs.get('budget')},
    "missing_fields": []
  }},
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
    else:
        # Build context about what was asked and what we're expecting
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

        # If there's conversation history, add context about what was last asked
        if last_follow_up:
            expecting_context = f"""
YOUR LAST QUESTION WAS: "{last_follow_up}"
The user's message "{req.message}" is the ANSWER to that question.
Extract the relevant value from their response."""

        state_lines = []
        if known_fields:
            state_lines.append(f"COLLECTED: {', '.join(known_fields)}")
        if missing_fields:
            state_lines.append(f"STILL NEED: {', '.join(missing_fields)}")
        state_summary = "\n".join(state_lines)

        # Check if this message will complete all fields (only 1 field left)
        is_last_field = len(missing_fields) == 1

        if is_last_field:
            # This is the last field - after extracting, generate branches!
            system_prompt = f"""You are a travel planner. Today is {today}.

{state_summary}
{expecting_context}

CRITICAL: Extract the value from the user's message. This completes all fields!

After extracting, GENERATE 2-3 TRIP BRANCHES immediately.

Return JSON:
{{
  "assistant_message": "Great! Here are your trip options for [destination].",
  "follow_up_question": null,
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

After extracting their answer, ask for the NEXT missing field in this order:
1. destination - "Where are you headed?"
2. origin - confirm detected location or ask
3. start_date - default {today}
4. end_date - default {next_week}
5. traveler_count - default 1
6. budget - "What's your budget?"

Return JSON only:
{{
  "assistant_message": "Acknowledgment of what they said (e.g. 'Rome, great choice!')",
  "follow_up_question": "Next question or null if all complete",
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

    # If this is the first message (no history), add a synthetic opening assistant message
    # This matches the static greeting shown in the frontend
    if not history_messages:
        initial_greeting = (
            "Tell me about your trip: where you're headed, where you're leaving from, "
            "dates, vibes, and how many travelers are going. Where are you headed?"
        )
        history_messages.append(
            cast(ChatCompletionMessageParam, {"role": "assistant", "content": initial_greeting})
        )

    messages: List[ChatCompletionMessageParam] = [
        cast(ChatCompletionMessageParam, {"role": "system", "content": system_prompt})
    ]
    messages.extend(history_messages)
    messages.append(cast(ChatCompletionMessageParam, {"role": "user", "content": req.message}))

    # Debug: log message structure (can be removed in production)
    if os.getenv("DEBUG_PLAN_MESSAGES"):
        print(f"[DEBUG] Sending {len(messages)} messages to OpenAI:")
        for i, msg in enumerate(messages):
            role = msg.get("role", "?")
            content_raw = msg.get("content", "")
            content = str(content_raw)[:100] if content_raw else ""
            print(f"  [{i}] {role}: {content}...")

    model_name = _plan_model_name()
    stream = None
    try:
        if "gpt-4o" in model_name:
            stream = client.chat.completions.create(
                model=model_name,
                messages=messages,
                max_tokens=_MAX_TOKENS,
                response_format={"type": "json_object"},
                stream=True,
            )
        elif "gpt-5" in model_name:
            stream = client.chat.completions.create(
                model=model_name,
                messages=messages,
                max_completion_tokens=_MAX_TOKENS,
                response_format={"type": "json_object"},
                stream=True,
            )
        else:
            raise RuntimeError(f"Unsupported planning model: {model_name}")
    except Exception as exc:
        last_error = exc
        print(f"OpenAI planning call failed with '{model_name}': {exc}")

    if stream is not None:
        assistant_parser = _AssistantMessageParser()
        assistant_stream_buffer = ""
        has_streamed_any = False
        raw_response_parts: List[str] = []

        try:
            for chunk in stream:
                delta_content = getattr(chunk.choices[0].delta, "content", None)
                delta_text = _coerce_delta_content(delta_content)
                if not delta_text:
                    continue

                raw_response_parts.append(delta_text)
                new_assistant_text = assistant_parser.feed(delta_text)
                if new_assistant_text:
                    assistant_stream_buffer += new_assistant_text
                    while len(assistant_stream_buffer) >= _STREAM_MIN_FLUSH_CHARS:
                        buffered_delta = assistant_stream_buffer[:_STREAM_MIN_FLUSH_CHARS]
                        assistant_stream_buffer = assistant_stream_buffer[_STREAM_MIN_FLUSH_CHARS:]
                        yield {
                            "event": "assistant_message",
                            "message_id": message_id,
                            "delta": buffered_delta,
                            "is_final": False,
                            "follow_up_question": None,
                        }
                        has_streamed_any = True
        except Exception as exc:
            last_error = exc
            print(f"OpenAI planning stream failed with '{model_name}': {exc}")
        else:
            raw_response = "".join(raw_response_parts)
            print(f"[DEBUG] Raw LLM response: {raw_response[:500]}...")
            data = None
            try:
                data = json.loads(raw_response or '{"branches": []}')
            except json.JSONDecodeError as exc:
                print(f"OpenAI planning response parsing failed for '{model_name}': {exc}")
                # Try to repair common JSON issues
                repaired = raw_response or ""
                # Remove trailing incomplete content after last complete structure
                # Find the last valid closing brace
                brace_count = 0
                last_valid_idx = -1
                for i, ch in enumerate(repaired):
                    if ch == "{":
                        brace_count += 1
                    elif ch == "}":
                        brace_count -= 1
                        if brace_count == 0:
                            last_valid_idx = i
                if last_valid_idx > 0:
                    repaired = repaired[: last_valid_idx + 1]
                try:
                    data = json.loads(repaired)
                    print("[DEBUG] JSON repair succeeded")
                except json.JSONDecodeError:
                    # Last resort: extract just assistant_message if possible
                    print("[DEBUG] JSON repair failed, using fallback response")
                    data = {
                        "branches": [],
                        "assistant_message": assistant_parser.text.strip()
                        or "I'm having trouble processing that. Could you try again?",
                        "follow_up_question": None,
                        "trip_inputs": {},
                    }

            if data is not None:
                branches_raw = data.get("branches", []) or []
                print(f"[DEBUG] Branches from LLM: {len(branches_raw)} branches")
                assistant_message = str(data.get("assistant_message") or "").strip()
                follow_up_question = str(data.get("follow_up_question") or "").strip() or None

                trip_inputs_payload = data.get("trip_inputs") or {}
                trip_inputs = _clean_trip_inputs(
                    request_trip_inputs,
                    trip_inputs_payload,
                    allow_overwrite=True,
                )
                response_missing_fields = trip_inputs.get("missing_fields") or []

                # Use pre-calculated all_fields_complete if we determined it before LLM call
                # This prevents LLM's incorrect missing_fields from blocking branch generation
                has_all_fields = all_fields_complete or len(response_missing_fields) == 0
                print(
                    f"[DEBUG] all_fields_complete={all_fields_complete}, "
                    f"has_all_fields={has_all_fields}, response_missing={response_missing_fields}"
                )

                cleaned: List[dict] = []

                # Process branches if we have all fields OR if LLM returned branches anyway
                if has_all_fields or branches_raw:
                    for b in branches_raw:
                        if not isinstance(b, dict):
                            continue
                        if not all(k in b for k in ("label", "destination")):
                            continue
                        cleaned.append(
                            {
                                "label": str(b["label"]),
                                "description": str(b.get("description", "")),
                                "destination": str(b["destination"]),
                                "origin": _normalize_str(b.get("origin")),
                                "start_date": _normalize_str(b.get("start_date")),
                                "end_date": _normalize_str(b.get("end_date")),
                                "traveler_count": _normalize_int(b.get("traveler_count")),
                                "budget": _normalize_str(b.get("budget")),
                            }
                        )

                # If all fields complete, don't ask follow-up questions
                if has_all_fields:
                    follow_up_question = None
                    if not assistant_message or "where" in assistant_message.lower():
                        assistant_message = "Generating trip options for you..."
                    trip_inputs["missing_fields"] = []
                elif not follow_up_question:
                    follow_up_question = _default_follow_up_question(response_missing_fields)

                if not assistant_message:
                    assistant_message = assistant_parser.text.strip()
                if not assistant_message and follow_up_question:
                    assistant_message = follow_up_question

                output = PlannerLLMOutput(
                    branches=cleaned,
                    assistant_message=assistant_message,
                    follow_up_question=follow_up_question,
                    trip_inputs=trip_inputs,
                )

                final_delta = assistant_stream_buffer
                if not final_delta and not has_streamed_any:
                    final_delta = assistant_message

                yield {
                    "event": "assistant_message",
                    "message_id": message_id,
                    "delta": final_delta,
                    "is_final": True,
                    "follow_up_question": follow_up_question,
                }

                return output

    if last_error is not None:
        print(f"OpenAI planning call failed: {last_error}")
        raise RuntimeError(f"OpenAI planning call failed: {last_error}")

    # Fallback: if we reach here without returning, raise an error
    raise RuntimeError("OpenAI planning call did not produce a valid response")


def plan_trip_flow(db: Session, req: PlanRequest) -> Generator[dict, None, PlanResponse]:
    if not req.session_id:
        raise ValueError("session_id is required for planning")

    # 1. Setup session and context
    db_session = get_or_create_session(
        db,
        session_token=req.session_id,
        user_external_id=req.user_id,
    )

    history_rows = fetch_chat_history(db, session=db_session, limit=_CHAT_HISTORY_LIMIT)
    history_messages = _history_to_messages(history_rows)

    parent_ctx = _resolve_parent_trip_context(
        db,
        session=db_session,
        requested_parent_id=req.trip_context_id,
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

        # 4. Call LLM and stream response
        openai_stream = _call_openai_for_plan(
            req,
            history_rows=history_rows,
            history=history_messages,
            message_id=str(assistant_chat.id),
        )

        while True:
            try:
                stream_event = next(openai_stream)
            except StopIteration as stop:
                planner_output = stop.value
                break
            yield stream_event

        # 5. Process LLM output and update DB
        trip_inputs_model = (
            TripInputs(**planner_output.trip_inputs)
            if planner_output.trip_inputs is not None
            else None
        )
        trip_inputs_payload = trip_inputs_model.dict() if trip_inputs_model else None
        assistant_chat.content = planner_output.assistant_message
        assistant_meta: dict[str, Any] = {}
        if planner_output.follow_up_question:
            assistant_meta["follow_up_question"] = planner_output.follow_up_question
        if trip_inputs_payload:
            assistant_meta["trip_inputs"] = trip_inputs_payload
        assistant_chat.meta = assistant_meta or None

        plan_branches: List[PlanBranch] = []
        branch_specs = planner_output.branches or []
        db_branches: List[models.Branch] = []
        primary_db_branch: Optional[models.Branch] = None

        if branch_specs:
            db_branches = create_branches_for_context(
                db,
                trip_context=trip_ctx,
                branch_specs=branch_specs,
                primary_index=0,
            )

            for idx, db_branch in enumerate(db_branches):
                source_spec = branch_specs[idx] if idx < len(branch_specs) else {}
                spec_dict = source_spec if isinstance(source_spec, dict) else {}
                plan_branches.append(
                    PlanBranch(
                        id=str(db_branch.id),
                        label=db_branch.label,
                        description=db_branch.description or "",
                        destination=db_branch.destination,
                        origin=_normalize_str(spec_dict.get("origin")),
                        start_date=_normalize_str(spec_dict.get("start_date")),
                        end_date=_normalize_str(spec_dict.get("end_date")),
                        traveler_count=_normalize_int(spec_dict.get("traveler_count")),
                        budget=_normalize_str(spec_dict.get("budget")),
                    )
                )

            primary_db_branch = db_branches[0] if db_branches else None

        yield {
            "event": "plan_update",
            "trip_context_id": trip_ctx.id,
            "branches": [branch.dict() for branch in plan_branches],
            "primary_branch_id": str(primary_db_branch.id) if primary_db_branch else None,
            "assistant_message_id": str(assistant_chat.id),
            "trip_inputs": trip_inputs_payload,
        }

        tiles_response: TilesSearchResponse | None = None

        if primary_db_branch:
            # 6. Search for tiles (hotels, activities, etc.) for the primary branch
            tiles_request = TilesSearchRequest(
                user_id=req.user_id,
                branch_id=primary_db_branch.id,
                session_id=req.session_id,
                trip_context_id=trip_ctx.id,
                destination=primary_db_branch.destination,
                destination_hint=primary_db_branch.destination,
                origin=trip_inputs_model.origin if trip_inputs_model else None,
                start_date=trip_inputs_model.start_date if trip_inputs_model else None,
                end_date=trip_inputs_model.end_date if trip_inputs_model else None,
                traveler_count=trip_inputs_model.traveler_count if trip_inputs_model else None,
            )

            tiles_response = search_tiles(tiles_request)

            if tiles_response.tiles:
                snapshot_tiles_for_branch(
                    db,
                    branch=primary_db_branch,
                    tiles=tiles_response.tiles,
                    replace_existing=True,
                )

            yield {
                "event": "tiles_update",
                "tiles": [tile.dict() for tile in tiles_response.tiles],
                "tiles_request_id": tiles_response.tiles_request_id,
                "summary": tiles_response.summary,
            }

        # 7. Final response
        response = PlanResponse(
            trip_context_id=trip_ctx.id,
            branches=plan_branches,
            tiles=tiles_response.tiles if tiles_response else [],
            primary_branch_id=str(primary_db_branch.id) if primary_db_branch else None,
            tiles_request_id=tiles_response.tiles_request_id if tiles_response else None,
            tiles_summary=tiles_response.summary if tiles_response else None,
            assistant_message=planner_output.assistant_message,
            assistant_message_id=str(assistant_chat.id),
            follow_up_question=planner_output.follow_up_question,
            trip_inputs=trip_inputs_model,
        )

        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def plan_trip(db: Session, req: PlanRequest) -> PlanResponse:
    flow = plan_trip_flow(db, req)
    while True:
        try:
            next(flow)
        except StopIteration as stop:
            return stop.value


def plan_trip_event_stream(db: Session, req: PlanRequest):
    flow = plan_trip_flow(db, req)

    def iterator():
        while True:
            try:
                event = next(flow)
            except StopIteration as stop:
                final_response = stop.value
                payload = {
                    "event": "complete",
                    "response": final_response.dict(),
                }
                yield (json.dumps(payload) + "\n").encode("utf-8")
                break

            yield (json.dumps(event) + "\n").encode("utf-8")

    return iterator()
