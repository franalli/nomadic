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
from app.schemas import PlanBranch, PlanRequest, PlanResponse, TilesSearchRequest, TripInputs
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


_CHAT_HISTORY_LIMIT = int(os.getenv("PLAN_CHAT_HISTORY_LIMIT", "12"))
_STREAM_CHUNK_SIZE = int(os.getenv("PLAN_STREAM_CHUNK_SIZE", "220"))
_STREAM_MIN_FLUSH_CHARS = int(os.getenv("PLAN_STREAM_MIN_CHARS", "10"))

_openai_client: Optional[OpenAI] = None

_TRIP_INPUT_FIELDS = ("destination", "origin", "start_date", "end_date", "traveler_count")


def _today_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


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


def _mock_branch_specs(req: PlanRequest) -> List[dict]:
    """Return deterministic mock branches so the flow works without OpenAI."""

    base_destinations = [
        ("Barcelona food & nightlife", "Barcelona, Spain"),
        ("Lisbon city break", "Lisbon, Portugal"),
        ("Valencia beach & paella", "Valencia, Spain"),
    ]

    branches: List[dict] = []
    for idx, (label, destination) in enumerate(base_destinations, start=1):
        branches.append(
            {
                "label": label,
                "description": f"Idea #{idx} inspired by: {req.message[:80]}",
                "destination": destination,
            }
        )

    return branches


def _summarise_branches(branches: List[dict]) -> str:
    if not branches:
        return "I couldn't pull concrete directions yet, but here are some starter ideas."

    lines = ["Here are a few directions to consider:"]
    for idx, branch in enumerate(branches, start=1):
        description = branch.get("description") or ""
        destination = branch.get("destination") or "Unknown destination"
        label = branch.get("label") or destination
        summary = f"{idx}. {label} ({destination})"
        if description:
            summary = f"{summary} — {description}"
        lines.append(summary)

    return "\n".join(lines)


def _mock_plan_output(req: PlanRequest) -> PlannerLLMOutput:
    branches = _mock_branch_specs(req)
    request_trip_inputs = req.trip_inputs.dict() if req.trip_inputs is not None else {}
    trip_inputs = _clean_trip_inputs(request_trip_inputs)
    assistant_message = (
        "Pulling from what you shared, I sketched a few sample trips you can react to."
        " Let me know what to double-click on or what to change."
    )
    follow_up_question = _default_follow_up_question(trip_inputs.get("missing_fields") or [])
    summary = _summarise_branches(branches)
    combined_message = f"{assistant_message}\n\n{summary}"

    return PlannerLLMOutput(
        branches=branches,
        assistant_message=combined_message,
        follow_up_question=follow_up_question,
        trip_inputs=trip_inputs,
    )


def _build_user_prompt(req: PlanRequest) -> str:
    """Compact summary of the latest user message for the LLM."""
    base = f"User message: {req.message}"
    if req.trip_inputs is None:
        return base

    inputs = _clean_trip_inputs(req.trip_inputs.dict())
    details: list[str] = []
    details.append(f"destination: {inputs.get('destination') or 'unknown'}")
    details.append(f"origin: {inputs.get('origin') or 'unknown'}")
    details.append(f"start_date: {inputs.get('start_date') or 'unknown'}")
    details.append(f"end_date: {inputs.get('end_date') or 'unknown'}")
    traveler_value = inputs.get("traveler_count")
    details.append(f"traveler_count: {traveler_value if traveler_value is not None else 'unknown'}")
    missing = inputs.get("missing_fields") or []
    if missing:
        details.append(f"missing_fields: {', '.join(missing)}")

    return f"{base}\nProvided trip details: {', '.join(details)}"


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


def _chunk_message_for_streaming(message: str) -> List[str]:
    if not message:
        return []

    paragraphs = [segment.strip() for segment in message.split("\n\n") if segment.strip()]
    if not paragraphs:
        paragraphs = [message.strip()]

    chunks: List[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= _STREAM_CHUNK_SIZE:
            chunks.append(paragraph)
            continue

        sentences = re.split(r"(?<=[.!?])\s+", paragraph)
        buffer = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            candidate = sentence if not buffer else f"{buffer} {sentence}"
            if len(candidate) <= _STREAM_CHUNK_SIZE:
                buffer = candidate
            else:
                if buffer:
                    chunks.append(buffer)
                buffer = sentence
        if buffer:
            chunks.append(buffer)

    return chunks or [message.strip()]


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


def _clean_trip_inputs(*sources: Any, fallback: Optional[dict] = None) -> dict:
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
                if current_value in (sentinel, None):
                    merged[field] = value
            elif current_value is sentinel:
                merged[field] = None

    for source in sources:
        _ingest(source)
    if fallback is not None:
        _ingest(fallback)

    if merged.get("start_date") is sentinel or merged.get("start_date") is None:
        merged["start_date"] = _today_iso()

    if merged.get("end_date") is sentinel or merged.get("end_date") is None:
        merged["end_date"] = _today_iso()

    if merged.get("traveler_count") is sentinel or merged.get("traveler_count") is None:
        merged["traveler_count"] = 1
    else:
        merged["traveler_count"] = _clamp_traveler_count(merged.get("traveler_count"))

    final_missing: set[str] = set()
    for field in _TRIP_INPUT_FIELDS:
        if merged[field] is sentinel:
            merged[field] = None
        if merged[field] is None:
            final_missing.add(field)

    for field in noted_missing:
        if field in _TRIP_INPUT_FIELDS:
            if merged.get(field) is None:
                final_missing.add(field)
        else:
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
    }

    for field in _TRIP_INPUT_FIELDS:
        if field in missing_fields:
            return prompt_by_field.get(field)
    return None


def _emit_assistant_events(
    message: str, message_id: str, follow_up_question: Optional[str]
) -> Generator[dict, None, None]:
    chunks = _chunk_message_for_streaming(message) or [message]
    for idx, chunk in enumerate(chunks):
        yield {
            "event": "assistant_message",
            "message_id": message_id,
            "delta": chunk,
            "is_final": idx == len(chunks) - 1,
            "follow_up_question": follow_up_question if idx == len(chunks) - 1 else None,
        }


def _history_to_messages(history: List[models.ChatMessage]) -> List[ChatCompletionMessageParam]:
    messages: List[ChatCompletionMessageParam] = []
    for entry in history:
        messages.append(
            cast(ChatCompletionMessageParam, {"role": entry.role, "content": entry.content})
        )
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
    history: List[ChatCompletionMessageParam],
    message_id: str,
) -> Generator[dict, None, PlannerLLMOutput]:
    # if os.getenv("PLAN_FORCE_MOCK", "0") == "1":
    #     output = _mock_plan_output(req)
    #     yield from _emit_assistant_events(
    #         output.assistant_message,
    #         message_id,
    #         output.follow_up_question,
    #     )
    #     return output

    request_trip_inputs = req.trip_inputs.dict() if req.trip_inputs is not None else {}

    system_prompt = (
        "You are a live travel planner speaking like a sharp, friendly travel agent.\n"
        "Always acknowledge prior context, note how the latest user message changes the plan, "
        "and keep the chat concise.\n"
        "Continuously capture these core fields from the conversation: destination city/region, "
        "origin city/airport, start_date, end_date, and traveler_count. "
        "Infer from history when possible. If anything is missing or fuzzy, ask one targeted "
        "follow-up at a time until all fields are set. "
        "Prompt for destination first if it is missing. Dates must be ISO formatted as YYYY-MM-DD "
        "and traveler_count is an integer.\n\n"
        "Respond strictly with JSON:\n"
        "{\n"
        '  "assistant_message": "brief conversational reply that reacts to the user",\n'
        '  "follow_up_question": "one crisp question for the next missing field, or null",\n'
        '  "trip_inputs": {\n'
        '    "destination": "city/region, or null",\n'
        '    "origin": "city or airport code, or null",\n'
        '    "start_date": "YYYY-MM-DD or null",\n'
        '    "end_date": "YYYY-MM-DD or null",\n'
        '    "traveler_count": 2,\n'
        '    "missing_fields": ["destination", "origin", "start_date"]\n'
        "  },\n"
        '  "branches": [\n'
        '    {"label": "...", "description": "...", "destination": "...", "origin": "...", '
        '"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", "traveler_count": 2}\n'
        "  ]\n"
        "}\n"
        "Rules: up to 3 branches only; always include trip_inputs with missing_fields listing any "
        "unknowns (destination first); carry known trip_inputs into every branch so tiles can "
        "align with origin and dates (use null when unknown); "
        "if all fields are present, set follow_up_question to null; never include markdown or "
        "commentary outside the JSON."
    )

    user_prompt = _build_user_prompt(req)

    client = _get_openai_client()
    if client is None:
        output = _mock_plan_output(req)
        yield from _emit_assistant_events(
            output.assistant_message,
            message_id,
            output.follow_up_question,
        )
        return output

    last_error: Exception | None = None

    history_messages: List[ChatCompletionMessageParam] = list(history)
    messages: List[ChatCompletionMessageParam] = [
        cast(ChatCompletionMessageParam, {"role": "system", "content": system_prompt})
    ]
    messages.extend(history_messages)
    messages.append(cast(ChatCompletionMessageParam, {"role": "user", "content": user_prompt}))

    model_name = _plan_model_name()
    try:
        stream = client.chat.completions.create(
            model=model_name,
            messages=messages,
            response_format={"type": "json_object"},
            stream=True,
        )
    except Exception as exc:  # pragma: no cover - depends on OpenAI availability
        last_error = exc
        print(f"OpenAI planning call failed with '{model_name}': {exc}")
    else:
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
        except Exception as exc:  # pragma: no cover - depends on OpenAI availability
            last_error = exc
            print(f"OpenAI planning stream failed with '{model_name}': {exc}")
        else:
            raw_response = "".join(raw_response_parts)
            try:
                data = json.loads(raw_response or '{"branches": []}')
            except Exception as exc:  # pragma: no cover - depends on OpenAI availability
                last_error = exc
                print(f"OpenAI planning response parsing failed for '{model_name}': {exc}")
            else:
                branches_raw = data.get("branches", []) or []
                assistant_message = str(data.get("assistant_message") or "").strip()
                follow_up_question = str(data.get("follow_up_question") or "").strip() or None

                cleaned: List[dict] = []
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
                        }
                    )

                fallback_trip_inputs = {}
                if cleaned:
                    first_branch = cleaned[0]
                    fallback_trip_inputs = {
                        "destination": first_branch.get("destination"),
                        "origin": first_branch.get("origin"),
                        "start_date": first_branch.get("start_date"),
                        "end_date": first_branch.get("end_date"),
                        "traveler_count": first_branch.get("traveler_count"),
                    }
                trip_inputs = _clean_trip_inputs(
                    request_trip_inputs,
                    data.get("trip_inputs") or {},
                    fallback=fallback_trip_inputs,
                )
                if not follow_up_question:
                    follow_up_question = _default_follow_up_question(
                        trip_inputs.get("missing_fields") or []
                    )

                if not cleaned:
                    print(
                        f"OpenAI planning call with '{model_name}' "
                        "returned no usable branches; falling back"
                    )
                    cleaned = _mock_branch_specs(req)

                if not assistant_message:
                    assistant_message = assistant_parser.text.strip()
                if not assistant_message and cleaned:
                    assistant_message = _summarise_branches(cleaned)

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
        print(f"OpenAI planning call failed, using mock branches: {last_error}")

    output = _mock_plan_output(req)
    yield from _emit_assistant_events(
        output.assistant_message, message_id, output.follow_up_question
    )
    return output


def plan_trip_flow(db: Session, req: PlanRequest) -> Generator[dict, None, PlanResponse]:
    if not req.session_id:
        raise ValueError("session_id is required for planning")

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

        record_chat_message(
            db,
            session=db_session,
            trip_context=trip_ctx,
            role="user",
            content=req.message,
            metadata=None,
        )

        assistant_chat = record_chat_message(
            db,
            session=db_session,
            trip_context=trip_ctx,
            role="assistant",
            content="",
            metadata=None,
        )

        openai_stream = _call_openai_for_plan(
            req,
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

        branch_specs = planner_output.branches
        db_branches = create_branches_for_context(
            db,
            trip_context=trip_ctx,
            branch_specs=branch_specs,
            primary_index=0,
        )

        if not db_branches:
            raise ValueError("No branches generated for trip context")

        plan_branches: List[PlanBranch] = []
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
                )
            )

        primary_db_branch = db_branches[0]
        yield {
            "event": "plan_update",
            "trip_context_id": trip_ctx.id,
            "branches": [branch.dict() for branch in plan_branches],
            "primary_branch_id": str(primary_db_branch.id),
            "assistant_message_id": str(assistant_chat.id),
            "trip_inputs": trip_inputs_payload,
        }

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

        response = PlanResponse(
            trip_context_id=trip_ctx.id,
            branches=plan_branches,
            tiles=tiles_response.tiles,
            primary_branch_id=str(primary_db_branch.id),
            tiles_request_id=tiles_response.tiles_request_id,
            tiles_summary=tiles_response.summary,
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
