"""Unit tests for suggestion_generator.py — LLM-generated suggestion chips.

The LLM is mocked throughout — these tests never hit the network. They cover:
- Valid LLM output -> chips returned, capped at 3.
- Invalid open_pill / trigger_action targets -> coerced to send_message.
- LLM raises / times out / returns empty -> function returns None.
- _build_envelope LLM-vs-fallback-vs-reset precedence.
- Vocab mirror constants equal the documented frontend sets.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.planner.services import suggestion_generator as sg
from app.planner.services.suggestion_generator import (
    _OPEN_PILL_TARGETS,
    _TRIGGER_ACTION_TARGETS,
    LLMSuggestionChip,
    LLMSuggestionChips,
    _coerce_chip,
    _extract_recent_turns,
    generate_suggestion_chips,
)

# =============================================================================
# Helpers
# =============================================================================


def _fake_msg(kind: str, content: Any) -> Dict[str, Any]:
    """A LangChain-message-like dict (type + content) the extractor understands."""
    return {"type": kind, "content": content}


def _patch_structured_llm(parsed: Any) -> Any:
    """Return a patch context manager for get_llm_by_model whose structured LLM
    ainvoke yields ``{"parsed": parsed, "raw": ...}``."""
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value={"parsed": parsed, "raw": MagicMock()})
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=structured)
    return patch.object(sg, "get_llm_by_model", return_value=llm)


def _chip_model(**overrides: Any) -> LLMSuggestionChip:
    base: Dict[str, Any] = {
        "message": "Plan a trip to Bali",
        "action_type": "send_message",
        "action_target": None,
        "chip_type": "cta",
        "category": "discovery",
        "icon": "map-pin",
    }
    base.update(overrides)
    return LLMSuggestionChip(**base)


# =============================================================================
# Vocab mirror constants (test #5)
# =============================================================================


class TestVocabMirror:
    def test_open_pill_targets_match_frontend(self) -> None:
        assert _OPEN_PILL_TARGETS == {
            "dates",
            "origin",
            "destination",
            "travelers",
            "budget",
            "flights",
            "stays",
            "activities",
        }

    def test_trigger_action_targets_match_frontend(self) -> None:
        assert _TRIGGER_ACTION_TARGETS == {"set_direct_flights_only", "confirm_reset"}


# =============================================================================
# _extract_recent_turns — tool-noise stripping
# =============================================================================


class TestExtractRecentTurns:
    def test_keeps_only_human_and_assistant_text(self) -> None:
        messages = [
            _fake_msg("human", "is bali a fun place?"),
            # tool-call-only AI message (empty text) -> dropped
            _fake_msg("ai", ""),
            # tool result -> dropped (not human/ai)
            {"type": "tool", "content": '{"result": "..."}'},
            _fake_msg("ai", "Bali is fantastic for beaches and diving."),
        ]
        turns = _extract_recent_turns(messages)
        assert turns == [
            "HUMAN: is bali a fun place?",
            "ASSISTANT: Bali is fantastic for beaches and diving.",
        ]

    def test_caps_to_last_five_turns(self) -> None:
        messages = [_fake_msg("human", f"msg {i}") for i in range(10)]
        turns = _extract_recent_turns(messages)
        assert len(turns) == 5
        assert turns[0] == "HUMAN: msg 5"
        assert turns[-1] == "HUMAN: msg 9"

    def test_handles_gemini_list_content_parts(self) -> None:
        messages = [
            _fake_msg("ai", [{"type": "text", "text": "Part A "}, {"type": "text", "text": "B"}]),
        ]
        turns = _extract_recent_turns(messages)
        assert turns == ["ASSISTANT: Part A B"]

    def test_empty_input_returns_empty(self) -> None:
        assert _extract_recent_turns([]) == []
        assert _extract_recent_turns(None) == []  # type: ignore[arg-type]


# =============================================================================
# _coerce_chip — vocabulary validation
# =============================================================================


class TestCoerceChip:
    def test_valid_open_pill_kept(self) -> None:
        chip = _coerce_chip(_chip_model(action_type="open_pill", action_target="dates"))
        assert chip is not None
        assert chip["action_type"] == "open_pill"
        assert chip["action_target"] == "dates"

    def test_invalid_open_pill_coerced_to_send_message(self) -> None:
        chip = _coerce_chip(_chip_model(action_type="open_pill", action_target="not_a_real_pill"))
        assert chip is not None
        assert chip["action_type"] == "send_message"
        assert chip["action_target"] is None

    def test_invalid_trigger_action_coerced(self) -> None:
        chip = _coerce_chip(_chip_model(action_type="trigger_action", action_target="bogus"))
        assert chip is not None
        assert chip["action_type"] == "send_message"
        assert chip["action_target"] is None

    def test_valid_trigger_action_kept(self) -> None:
        chip = _coerce_chip(
            _chip_model(action_type="trigger_action", action_target="confirm_reset")
        )
        assert chip is not None
        assert chip["action_type"] == "trigger_action"
        assert chip["action_target"] == "confirm_reset"

    def test_empty_message_dropped(self) -> None:
        assert _coerce_chip(_chip_model(message="   ")) is None


# =============================================================================
# generate_suggestion_chips — end to end (mocked LLM)
# =============================================================================


class TestGenerateSuggestionChips:
    def test_valid_output_capped_at_three(self) -> None:
        # test #1 + cap: 4 valid chips -> only 3 returned
        parsed = LLMSuggestionChips(
            chips=[
                _chip_model(message="Plan a trip to Bali"),
                _chip_model(message="See Bali highlights"),
                _chip_model(message="Set dates", action_type="open_pill", action_target="dates"),
                _chip_model(message="Set budget", action_type="open_pill", action_target="budget"),
            ]
        )
        state = {"trip_plan": {}}
        msgs = [_fake_msg("human", "is bali a fun place?")]
        with _patch_structured_llm(parsed):
            chips = asyncio.run(generate_suggestion_chips(state, msgs))
        assert chips is not None
        assert len(chips) == 3
        assert chips[0]["message"] == "Plan a trip to Bali"

    def test_invalid_target_dropped_or_coerced_valid_kept(self) -> None:
        # test #2: one chip with bad open_pill target -> coerced; valid kept
        parsed = LLMSuggestionChips(
            chips=[
                _chip_model(
                    message="Open mystery", action_type="open_pill", action_target="mystery"
                ),
                _chip_model(message="Set dates", action_type="open_pill", action_target="dates"),
            ]
        )
        with _patch_structured_llm(parsed):
            chips = asyncio.run(generate_suggestion_chips({"trip_plan": {}}, []))
        assert chips is not None
        assert len(chips) == 2
        # invalid target coerced to send_message
        assert chips[0]["action_type"] == "send_message"
        assert chips[0]["action_target"] is None
        # valid target preserved
        assert chips[1]["action_type"] == "open_pill"
        assert chips[1]["action_target"] == "dates"

    def test_dict_parsed_payload_accepted(self) -> None:
        parsed = {"chips": [{"message": "Plan Bali", "action_type": "send_message"}]}
        with _patch_structured_llm(parsed):
            chips = asyncio.run(generate_suggestion_chips({"trip_plan": {}}, []))
        assert chips is not None
        assert chips[0]["message"] == "Plan Bali"

    def test_llm_raises_returns_none(self) -> None:
        # test #3a: LLM raises on every attempt -> None
        structured = MagicMock()
        structured.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
        llm = MagicMock()
        llm.with_structured_output = MagicMock(return_value=structured)
        with patch.object(sg, "get_llm_by_model", return_value=llm):
            with patch.object(sg.asyncio, "sleep", new=AsyncMock()):
                chips = asyncio.run(generate_suggestion_chips({"trip_plan": {}}, []))
        assert chips is None

    def test_construction_raises_returns_none(self) -> None:
        # test #3b: get_llm_by_model raises (e.g. spend guard) -> None
        with patch.object(sg, "get_llm_by_model", side_effect=RuntimeError("spend cap")):
            chips = asyncio.run(generate_suggestion_chips({"trip_plan": {}}, []))
        assert chips is None

    def test_empty_chips_returns_none(self) -> None:
        # test #3c: LLM returns empty -> None
        parsed = LLMSuggestionChips(chips=[])
        with _patch_structured_llm(parsed):
            chips = asyncio.run(generate_suggestion_chips({"trip_plan": {}}, []))
        assert chips is None

    def test_all_invalid_message_returns_none(self) -> None:
        # every chip has an empty message -> nothing salvageable -> None
        parsed = LLMSuggestionChips(chips=[_chip_model(message="")])
        with _patch_structured_llm(parsed):
            chips = asyncio.run(generate_suggestion_chips({"trip_plan": {}}, []))
        assert chips is None

    def test_none_parsed_returns_none(self) -> None:
        with _patch_structured_llm(None):
            chips = asyncio.run(generate_suggestion_chips({"trip_plan": {}}, []))
        assert chips is None


# =============================================================================
# _build_envelope precedence (test #4)
# =============================================================================


def _make_envelope_state(**overrides: Any) -> Dict[str, Any]:
    state: Dict[str, Any] = {
        "trip_plan": {},
        "trip_settings": {},
        "tiles": {},
        "turn_meta": {},
        "day_cards": [],
    }
    state.update(overrides)
    return state


class TestBuildEnvelopePrecedence:
    @patch("app.planner.services.state_serde.serialize_agent_state", return_value="{}")
    def test_llm_chips_used_when_set_and_valid(self, _mock_serialize: Any) -> None:
        from app.planner.coordinator import _build_envelope

        llm_chips = [
            {
                "message": "Plan a trip to Bali",
                "action_type": "send_message",
                "action_target": None,
                "chip_type": "cta",
                "category": "discovery",
                "icon": "map-pin",
            }
        ]
        # No destination set: deterministic generator would say "Pick a destination".
        state = _make_envelope_state(_llm_suggestion_chips=llm_chips)
        result = _build_envelope(state, "is bali a fun place?", "sess-1", "Bali is great!")
        chips = result["suggestion_chips"]
        assert chips == llm_chips
        assert result["suggested_responses"] == ["Plan a trip to Bali"]
        # deterministic "Pick a destination" must NOT appear
        assert all(c["message"] != "Pick a destination" for c in chips)

    @patch("app.planner.services.state_serde.serialize_agent_state", return_value="{}")
    def test_falls_back_to_deterministic_when_unset(self, _mock_serialize: Any) -> None:
        from app.planner.coordinator import _build_envelope

        state = _make_envelope_state()  # no _llm_suggestion_chips
        result = _build_envelope(state, "hi", "sess-1", "Hello!")
        chips = result["suggestion_chips"]
        # deterministic no-destination branch surfaces "Pick a destination"
        assert any(c["message"] == "Pick a destination" for c in chips)

    @patch("app.planner.services.state_serde.serialize_agent_state", return_value="{}")
    def test_falls_back_when_llm_chips_empty_list(self, _mock_serialize: Any) -> None:
        from app.planner.coordinator import _build_envelope

        state = _make_envelope_state(_llm_suggestion_chips=[])
        result = _build_envelope(state, "hi", "sess-1", "Hello!")
        chips = result["suggestion_chips"]
        assert any(c["message"] == "Pick a destination" for c in chips)

    @patch("app.planner.services.state_serde.serialize_agent_state", return_value="{}")
    def test_falls_back_when_llm_chips_malformed(self, _mock_serialize: Any) -> None:
        from app.planner.coordinator import _build_envelope

        # missing "message" -> treated as invalid -> deterministic fallback
        state = _make_envelope_state(_llm_suggestion_chips=[{"action_type": "send_message"}])
        result = _build_envelope(state, "hi", "sess-1", "Hello!")
        chips = result["suggestion_chips"]
        assert any(c["message"] == "Pick a destination" for c in chips)

    @patch("app.planner.services.state_serde.serialize_agent_state", return_value="{}")
    def test_reset_pending_overrides_llm_chips(self, _mock_serialize: Any) -> None:
        from app.planner.coordinator import _build_envelope

        llm_chips = [
            {
                "message": "Plan a trip to Bali",
                "action_type": "send_message",
                "action_target": None,
                "chip_type": "cta",
                "category": "discovery",
                "icon": "map-pin",
            }
        ]
        state = _make_envelope_state(_llm_suggestion_chips=llm_chips, _reset_pending=True)
        result = _build_envelope(state, "reset", "sess-1", "Sure?")
        messages = [c["message"] for c in result["suggestion_chips"]]
        assert messages == ["Yes, reset my trip", "No, keep planning"]


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
