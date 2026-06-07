"""LLM-generated, conversation+state-aware suggestion chips.

The deterministic ``chip_generator._generate_chips_from_state`` keys only on
``trip_plan`` fields and is blind to the conversation, so a Q&A turn like
"is bali a fun place?" (no destination set) yields "Pick a destination" even
though the whole conversation is about Bali.

This module produces chips from BOTH the conversation and the trip state via a
small structured-output LLM call (mirroring the router_extraction pattern). It is
exception-safe: it runs in the streaming hot path and must NEVER crash the turn.
``generate_suggestion_chips`` returns ``None`` whenever the LLM yields nothing
valid / raises / times out, so the caller falls back to the deterministic
generator.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Literal, Optional

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from app.config import settings
from app.planner.llm_factory import (
    gemini_safe_schema,
    get_llm_by_model,
    resolve_schema_refs,
    strip_unsupported_schema_keys,
)

logger = logging.getLogger(__name__)

# ── Frontend action vocabulary mirror ────────────────────────────────────────
# keep in sync with SuggestionChipItem.tsx (OPEN_PILL_TARGETS / TRIGGER_ACTION_TARGETS)
_OPEN_PILL_TARGETS = {
    "dates",
    "origin",
    "destination",
    "travelers",
    "budget",
    "flights",
    "stays",
    "activities",
}
_TRIGGER_ACTION_TARGETS = {"set_direct_flights_only", "confirm_reset"}

_MAX_CHIPS = 3
_MAX_TURNS = 5


class LLMSuggestionChip(BaseModel):
    """One LLM-proposed suggestion chip. Mirrors ``schemas.SuggestionChip``."""

    message: str = Field(description="Short actionable display text for the chip")
    action_type: Literal["send_message", "open_pill", "trigger_action"] = "send_message"
    action_target: Optional[str] = None
    chip_type: Literal["cta", "follow_up", "setting"] = "follow_up"
    category: str = ""
    icon: Optional[str] = None


class LLMSuggestionChips(BaseModel):
    """Wrapper schema for structured output."""

    chips: list[LLMSuggestionChip] = Field(default_factory=list)


_SUGGESTIONS_SCHEMA: dict = gemini_safe_schema(
    strip_unsupported_schema_keys(resolve_schema_refs(LLMSuggestionChips.model_json_schema()))
)

_SYSTEM_PROMPT = """You generate 2-3 SHORT, actionable suggestion chips for a travel-planning \
assistant. Each chip is a tappable next-step the traveler can take.

Rules:
- Reflect the ACTUAL conversation subject. If the conversation is about a place \
(e.g. Bali) but no destination is set yet, a good chip is "Plan a trip to Bali" — \
NEVER suggest "Pick a destination" when the destination is set OR clearly intended \
from the conversation.
- NEVER re-suggest a step that is already satisfied (don't say "pick a destination" \
if a destination is set; don't say "set dates" if dates are set).
- Prefer action_type="open_pill" ONLY for a genuinely-missing CORE field, with \
action_target in: {open_pill_targets}.
- Prefer action_type="send_message" for conversational next steps — the chip text \
becomes the user's next message, so write it as something the user would say.
- Use action_type="trigger_action" only with action_target in: {trigger_targets}.
- Keep messages under ~6 words. Produce at most 3 chips.
- chip_type is one of: cta, follow_up, setting. icon is an optional Lucide icon name.

Trip state:
{state_summary}

Recent conversation (most recent last):
{conversation}
"""


def _chunk_text(content: Any) -> str:
    """Normalize message content (Gemini-3 list-of-parts OR plain str) to text.

    Local copy of ``agent_runner._chunk_text`` — importing from agent_runner
    would create an import cycle (agent_runner imports this module).
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: list[str] = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text" and isinstance(part.get("text"), str):
                    out.append(part["text"])
            elif isinstance(part, str):
                out.append(part)
        return "".join(out)
    return ""


def _msg_kind(msg: Any) -> Optional[str]:
    """Return 'human' / 'ai' / None for a message object or dict."""
    name = type(msg).__name__
    if name == "HumanMessage":
        return "human"
    if name == "AIMessage" or name == "AIMessageChunk":
        return "ai"
    if isinstance(msg, dict):
        t = msg.get("type") or msg.get("role")
        if t in ("human", "user"):
            return "human"
        if t in ("ai", "assistant"):
            return "ai"
    return None


def _msg_content(msg: Any) -> str:
    content = getattr(msg, "content", None)
    if content is None and isinstance(msg, dict):
        content = msg.get("content")
    return _chunk_text(content).strip()


def _extract_recent_turns(recent_messages: list) -> list[str]:
    """Extract the last ~5 HUMAN/ASSISTANT text turns, stripping tool-call noise.

    The messages list contains tool calls + tool results (AIMessages with empty
    text + tool_calls, and ToolMessages). We keep only human + assistant TEXT,
    mirroring extract_trip_fields' "authoritative HumanMessage" content handling.
    """
    turns: list[str] = []
    for msg in recent_messages or []:
        kind = _msg_kind(msg)
        if kind not in ("human", "ai"):
            continue  # drops ToolMessage / system / unknown
        text = _msg_content(msg)
        if not text:
            continue  # drops tool-call-only AIMessages (empty text)
        label = "HUMAN" if kind == "human" else "ASSISTANT"
        turns.append(f"{label}: {text}")
    return turns[-_MAX_TURNS:]


def _build_state_summary(final_state: dict, recent_turns: list[str]) -> dict[str, Any]:
    """Compact state summary for the prompt (conversation-subject aware)."""
    trip_plan: dict[str, Any] = final_state.get("trip_plan", {}) or {}
    tiles: dict[str, Any] = final_state.get("tiles", {}) or {}
    persistent_meta: dict[str, Any] = final_state.get("persistent_meta", {}) or {}
    turn_meta: dict[str, Any] = final_state.get("turn_meta", {}) or {}

    destination = trip_plan.get("destination") or ""

    validation = turn_meta.get("validation_result", {}) or {}
    blocking = [
        {"code": v.get("code"), "message": v.get("message")}
        for v in (validation.get("violations", []) or [])
        if isinstance(v, dict) and v.get("severity") == "blocking"
    ][:3]

    return {
        "destination": destination,
        "destination_set": bool(destination),
        "start_date": trip_plan.get("start_date") or "",
        "end_date": trip_plan.get("end_date") or "",
        "activity_categories": trip_plan.get("activity_categories", []) or [],
        "plan_view_state": persistent_meta.get("plan_view_state") or "",
        "has_tiles": bool(tiles.get("flights") or tiles.get("hotels") or tiles.get("activities")),
        "has_day_cards": bool(final_state.get("day_cards")),
        "has_strategy_sections": bool(final_state.get("strategy_sections")),
        "blocking_constraint_violations": blocking,
    }


def _coerce_chip(chip: LLMSuggestionChip) -> Optional[dict[str, Any]]:
    """Validate one chip against the frontend vocabulary.

    Invalid open_pill / trigger_action targets are coerced to send_message
    (matching the frontend's own degradation). Returns the chip dict, or None
    if it cannot be salvaged (empty message).
    """
    message = (chip.message or "").strip()
    if not message:
        return None

    action_type = chip.action_type
    action_target = chip.action_target

    if action_type == "open_pill" and (action_target not in _OPEN_PILL_TARGETS):
        action_type = "send_message"
        action_target = None
    elif action_type == "trigger_action" and (action_target not in _TRIGGER_ACTION_TARGETS):
        action_type = "send_message"
        action_target = None

    return {
        "message": message,
        "action_type": action_type,
        "action_target": action_target,
        "chip_type": chip.chip_type,
        "category": chip.category or "",
        "icon": chip.icon,
    }


async def generate_suggestion_chips(
    final_state: dict, recent_messages: list
) -> list[dict[str, Any]] | None:
    """LLM-generate conversation+state-aware suggestion chips.

    Returns a list of validated chip dicts (capped at 3), or ``None`` when the
    LLM yields nothing valid / raises / times out. The entire function is
    exception-safe — it runs in the streaming hot path and must never crash the
    turn.
    """
    try:
        recent_turns = _extract_recent_turns(recent_messages)
        state_summary = _build_state_summary(final_state, recent_turns)

        prompt = _SYSTEM_PROMPT.format(
            open_pill_targets=sorted(_OPEN_PILL_TARGETS),
            trigger_targets=sorted(_TRIGGER_ACTION_TARGETS),
            state_summary=json.dumps(state_summary, indent=2, default=str),
            conversation="\n".join(recent_turns) if recent_turns else "(no conversation yet)",
        )

        # Construct INSIDE try — get_llm_by_model reserves spend and can raise.
        # NOTE: do NOT pass timeout=settings.suggestions_timeout_s as the LLM-client
        # timeout — Gemini-3 rejects deadlines < 10s ("Manually set deadline 4s is
        # too short"). The hot-path bound is enforced by the wait_for() around the
        # concurrent task in agent_runner; the SDK default applies here.
        llm = get_llm_by_model(
            settings.suggestions_model,
            temperature=0,
            max_tokens=300,
            max_retries=1,
        )
        structured_llm = llm.with_structured_output(
            dict(_SUGGESTIONS_SCHEMA),
            include_raw=True,
            method="function_calling",
        )

        result = None
        for _attempt in range(2):
            try:
                result = await structured_llm.ainvoke([HumanMessage(content=prompt)])
                break
            except Exception:
                if _attempt == 0:
                    await asyncio.sleep(0.5)
                    continue
                raise

        parsed_payload = result["parsed"] if isinstance(result, dict) else result
        if parsed_payload is None:
            raise ValueError("Structured output returned None for generate_suggestion_chips")

        if isinstance(parsed_payload, LLMSuggestionChips):
            parsed = parsed_payload
        elif isinstance(parsed_payload, dict):
            parsed = LLMSuggestionChips.model_validate(parsed_payload)
        elif hasattr(parsed_payload, "model_dump"):
            parsed = LLMSuggestionChips.model_validate(parsed_payload.model_dump())
        else:
            raise ValueError(
                f"Unexpected payload type for suggestion chips: {type(parsed_payload).__name__}"
            )

        chips: list[dict[str, Any]] = []
        for raw_chip in parsed.chips:
            coerced = _coerce_chip(raw_chip)
            if coerced is not None:
                chips.append(coerced)
            if len(chips) >= _MAX_CHIPS:
                break

        if not chips:
            return None
        return chips[:_MAX_CHIPS]
    except Exception as exc:  # pragma: no cover - defensive hot-path guard
        logger.warning("[generate_suggestion_chips] suggestion generation failed: %s", exc)
        return None
