"""
Tests for agent state serialization and multi-turn conversations.

The serialization tests are pure unit tests (no API keys needed).
The multi-turn tests require OPENAI_API_KEY or GOOGLE_API_KEY and
are skipped when keys are unavailable.
"""

from __future__ import annotations

import importlib
import os
from types import SimpleNamespace

import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.planner.middleware import _merge_trip_fields
from app.planner.plan_graph import _extract_partial_payload
from app.planner.services.state_serde import (
    restore_agent_state,
    serialize_agent_state,
)
from app.planner.tools.get_local_intel import get_local_intel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Integration tests are marked with ``llm`` so they can be explicitly
# selected with ``pytest -m llm``.  They are skipped by default unless the
# RUN_LLM_TESTS env var is set.
_skip_no_llm = pytest.mark.skipif(
    not os.environ.get("RUN_LLM_TESTS"),
    reason="Set RUN_LLM_TESTS=1 to run agent integration tests",
)


# ===========================================================================
# Unit tests -- serialization roundtrip (no API keys needed)
# ===========================================================================


class TestSerializeAgentState:
    """Test serialize_agent_state produces JSON-safe output."""

    def test_empty_state(self):
        state = {"messages": []}
        result = serialize_agent_state(state)
        assert result["messages"] == []
        assert result.get("trip_plan") is None  # not in state, not in result

    def test_basic_messages(self):
        state = {
            "messages": [
                SystemMessage(content="You are helpful"),
                HumanMessage(content="Hello"),
                AIMessage(content="Hi there!"),
            ],
            "trip_plan": {"destination": "Bali"},
        }
        result = serialize_agent_state(state)
        assert len(result["messages"]) == 3
        # All messages should be dicts with "type" and "data"
        for m in result["messages"]:
            assert isinstance(m, dict)
            assert "type" in m
            assert "data" in m
        assert result["trip_plan"] == {"destination": "Bali"}

    def test_tool_messages_preserved(self):
        """AIMessage with tool_calls and ToolMessage with tool_call_id survive roundtrip."""
        state = {
            "messages": [
                HumanMessage(content="Plan my trip"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "extract_trip_fields",
                            "args": {"msg": "Bali"},
                            "id": "tc_1",
                            "type": "tool_call",
                        }
                    ],
                ),
                ToolMessage(content='{"destination": "Bali"}', tool_call_id="tc_1"),
                AIMessage(content="Got it, Bali!"),
            ],
        }
        serialized = serialize_agent_state(state)
        assert len(serialized["messages"]) == 4

        # Roundtrip
        restored = restore_agent_state(serialized)
        msgs = restored["messages"]
        assert len(msgs) == 4
        assert isinstance(msgs[0], HumanMessage)
        assert isinstance(msgs[1], AIMessage)
        assert msgs[1].tool_calls[0]["name"] == "extract_trip_fields"
        assert isinstance(msgs[2], ToolMessage)
        assert msgs[2].tool_call_id == "tc_1"
        assert isinstance(msgs[3], AIMessage)
        assert msgs[3].content == "Got it, Bali!"

    def test_message_trimming(self):
        """Messages are trimmed to max_messages, keeping first 2 + last N."""
        messages = [SystemMessage(content="System"), HumanMessage(content="First")]
        # Add 30 more messages
        for i in range(30):
            if i % 2 == 0:
                messages.append(HumanMessage(content=f"Human {i}"))
            else:
                messages.append(AIMessage(content=f"AI {i}"))

        state = {"messages": messages}
        result = serialize_agent_state(state, max_messages=10)
        assert len(result["messages"]) == 10

        # First 2 should be the system + first human
        restored = restore_agent_state(result)
        assert isinstance(restored["messages"][0], SystemMessage)
        assert restored["messages"][0].content == "System"
        assert isinstance(restored["messages"][1], HumanMessage)
        assert restored["messages"][1].content == "First"

    def test_no_trimming_when_under_limit(self):
        state = {
            "messages": [
                HumanMessage(content="A"),
                AIMessage(content="B"),
            ],
        }
        result = serialize_agent_state(state, max_messages=20)
        assert len(result["messages"]) == 2

    def test_non_message_fields_passthrough(self):
        state = {
            "messages": [],
            "trip_plan": {"destination": "Tokyo", "start_date": "2026-04-01"},
            "trip_settings": {"skill_level": "intermediate"},
            "tiles": {"flights": [{"id": "f1"}], "hotels": []},
            "strategy_sections": [{"specialist_type": "diving"}],
            "day_cards": [{"day": 1}],
            "constraints": [{"constraint_id": "no_fly_24h", "rule": "min 24h buffer"}],
            "turn_meta": {"tool_call_count": 2},
            "persistent_meta": {"plan_view_state": "S1_STRATEGY"},
        }
        result = serialize_agent_state(state)
        assert result["trip_plan"] == state["trip_plan"]
        assert result["trip_settings"] == state["trip_settings"]
        assert result["tiles"] == state["tiles"]
        assert result["strategy_sections"] == state["strategy_sections"]
        assert result["day_cards"] == state["day_cards"]
        assert result["constraints"] == state["constraints"]
        # turn_meta is per-turn state — intentionally NOT serialized
        assert "turn_meta" not in result
        assert result["persistent_meta"] == state["persistent_meta"]


class TestRestoreAgentState:
    """Test restore_agent_state with various inputs."""

    def test_none_returns_defaults(self):
        result = restore_agent_state(None)
        assert result["messages"] == []
        assert result["trip_plan"] == {}
        assert result["trip_settings"] == {}
        assert result["tiles"] == {}
        assert result["strategy_sections"] == []
        assert result["day_cards"] == []
        assert result["constraints"] == []
        assert result["turn_meta"] == {}
        assert result["persistent_meta"] == {}

    def test_empty_dict_returns_defaults(self):
        result = restore_agent_state({})
        assert result["messages"] == []
        assert result["trip_plan"] == {}

    def test_legacy_message_format(self):
        """Legacy format from existing graph path (role/content dicts) is handled."""
        session = {
            "messages": [
                {"role": "human", "content": "Hello"},
                {"role": "assistant", "content": "Hi!"},
            ],
        }
        result = restore_agent_state(session)
        assert len(result["messages"]) == 2
        assert isinstance(result["messages"][0], HumanMessage)
        assert result["messages"][0].content == "Hello"
        assert isinstance(result["messages"][1], AIMessage)
        assert result["messages"][1].content == "Hi!"

    def test_full_roundtrip(self):
        """Full serialize -> restore -> serialize produces identical output."""
        original = {
            "messages": [
                SystemMessage(content="System prompt"),
                HumanMessage(content="I want to visit Bali March 1-8 for diving"),
                AIMessage(content="Great choice!"),
            ],
            "trip_plan": {
                "destination": "Bali",
                "start_date": "2026-03-01",
                "end_date": "2026-03-08",
            },
            "constraints": [{"constraint_id": "no_fly_24h", "rule": "24h no-fly buffer"}],
            "strategy_sections": [{"specialist_type": "diving", "content": "advice"}],
        }

        # Serialize
        serialized = serialize_agent_state(original)

        # Restore
        restored = restore_agent_state(serialized)

        # Check trip_plan preserved
        assert restored["trip_plan"] == original["trip_plan"]
        assert restored["constraints"] == original["constraints"]
        assert restored["strategy_sections"] == original["strategy_sections"]

        # Check messages restored with correct types
        assert len(restored["messages"]) == 3
        assert isinstance(restored["messages"][0], SystemMessage)
        assert isinstance(restored["messages"][1], HumanMessage)
        assert isinstance(restored["messages"][2], AIMessage)
        assert restored["messages"][2].content == "Great choice!"

        # Re-serialize should produce the same serialized form
        re_serialized = serialize_agent_state(restored)
        assert re_serialized["trip_plan"] == serialized["trip_plan"]
        assert len(re_serialized["messages"]) == len(serialized["messages"])

    def test_legacy_trip_inputs_and_metadata_tiles_are_migrated(self):
        session = {
            "messages": [
                {"role": "human", "content": "Plan Bali"},
            ],
            "trip_inputs": {
                "destination": "Bali",
                "origin": "SFO",
                "start_date": "2026-03-01",
                "end_date": "2026-03-08",
                "adults": 2,
                "children": 0,
                "budget": 5000,
            },
            "metadata": {
                "tiles": {"flights": [{"id": "f1"}], "hotels": [{"id": "h1"}]},
                "strategy_sections": [{"id": "sec_local", "specialist_type": "local_expert"}],
            },
        }

        restored = restore_agent_state(session)

        assert restored["trip_plan"]["destination"] == "Bali"
        assert restored["trip_plan"]["origin"] == "SFO"
        assert restored["trip_plan"]["start_date"] == "2026-03-01"
        assert restored["trip_plan"]["end_date"] == "2026-03-08"
        assert restored["trip_plan"]["budget"] == 5000
        assert restored["tiles"]["flights"][0]["id"] == "f1"
        assert restored["strategy_sections"][0]["specialist_type"] == "local_expert"

    def test_legacy_flat_trip_settings_are_normalized(self):
        session = {
            "messages": [],
            "trip_settings": {
                "skill_level": "advanced",
                "hotel_min_stars": 5,
                "flight_direct_only": True,
                "flight_cabin_class": "business",
            },
        }

        restored = restore_agent_state(session)
        trip_settings = restored["trip_settings"]

        assert trip_settings["activity_settings"]["skill_level"] == "advanced"
        assert trip_settings["hotel_settings"]["min_stars"] == 5
        assert trip_settings["flight_settings"]["direct_only"] is True
        assert trip_settings["flight_settings"]["cabin_class"] == "business"
        assert "skill_level" not in trip_settings
        assert "hotel_min_stars" not in trip_settings


# ===========================================================================
# Unit tests -- create_agent regression guards
# ===========================================================================


def test_merge_trip_fields_applies_removal_and_reset_flags() -> None:
    state = {
        "trip_plan": {
            "budget": 6000,
            "activity_categories": ["hiking", "yoga"],
            "specialist_hints": ["diving", "hiking"],
        },
        "trip_settings": {
            "hotel_settings": {"min_stars": 5, "amenities": ["pool"]},
        },
    }
    result = {
        "fields_changed": ["removal_targets", "reset_budget", "reset_hotel"],
        "removal_targets": ["hiking"],
        "reset_budget": True,
        "reset_hotel": True,
    }

    updates = _merge_trip_fields(state, result)

    assert updates["trip_plan"]["budget"] is None
    assert updates["trip_plan"]["activity_categories"] == ["yoga"]
    assert updates["trip_plan"]["specialist_hints"] == ["diving"]
    assert updates["trip_settings"]["hotel_settings"]["min_stars"] == 0
    assert updates["trip_settings"]["hotel_settings"]["amenities"] == []


def test_merge_trip_fields_persists_preferences_in_nested_settings() -> None:
    state = {"trip_plan": {}, "trip_settings": {}}
    result = {
        "fields_changed": [
            "skill_level",
            "hotel_min_stars",
            "hotel_amenities",
            "flight_direct_only",
            "flight_cabin_class",
            "activity_categories",
        ],
        "skill_level": "beginner",
        "hotel_min_stars": 4,
        "hotel_amenities": ["pool", "spa"],
        "flight_direct_only": True,
        "flight_cabin_class": "business",
        "activity_categories": ["yoga", "nightlife"],
    }

    updates = _merge_trip_fields(state, result)
    trip_settings = updates["trip_settings"]

    assert trip_settings["activity_settings"]["skill_level"] == "beginner"
    assert trip_settings["activity_settings"]["categories"] == ["nightlife", "yoga"]
    assert trip_settings["hotel_settings"]["min_stars"] == 4
    assert trip_settings["hotel_settings"]["amenities"] == ["pool", "spa"]
    assert trip_settings["flight_settings"]["direct_only"] is True
    assert trip_settings["flight_settings"]["cabin_class"] == "business"

    # Regression guard: flat keys are ignored by complete envelope builders.
    assert "skill_level" not in trip_settings
    assert "hotel_min_stars" not in trip_settings
    assert "flight_direct_only" not in trip_settings


def test_tiles_partial_payload_is_id_keyed_map() -> None:
    tool_result = {
        "flights": [{"id": "f_1", "type": "flight"}],
        "hotels": [{"id": "h_1", "type": "hotel"}],
        "activities": [{"id": "a_1", "type": "activity"}],
    }

    partial = _extract_partial_payload("search_tiles", tool_result)

    assert partial is not None
    assert partial["kind"] == "tiles"
    assert set(partial["payload"].keys()) == {"f_1", "h_1", "a_1"}


@pytest.mark.asyncio
async def test_get_local_intel_uses_runtime_thread_id_for_enrichment_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    local_expert_module = importlib.import_module("app.planner.nodes.local_expert")
    captured_session_id: dict[str, str] = {}

    async def _dummy_enrich() -> None:
        return None

    def _fake_build_enrichment_closure(*, session_id: str, **_: object):
        captured_session_id["value"] = session_id
        return _dummy_enrich

    monkeypatch.setattr(settings, "local_expert_use_llm", True, raising=False)
    monkeypatch.setattr(
        local_expert_module,
        "build_enrichment_closure",
        _fake_build_enrichment_closure,
    )

    async with local_expert_module._pending_lock:
        local_expert_module._pending_enrichments.clear()

    runtime = SimpleNamespace(config={"configurable": {"thread_id": "sess_123"}})
    await get_local_intel.coroutine(
        destination="Bali",
        start_date="2026-03-01",
        end_date="2026-03-08",
        travelers="2 adults",
        session_id="",
        runtime=runtime,
    )

    async with local_expert_module._pending_lock:
        pending_keys = list(local_expert_module._pending_enrichments.keys())
        local_expert_module._pending_enrichments.clear()

    assert captured_session_id["value"] == "sess_123"
    assert pending_keys == ["sess_123"]


# ===========================================================================
# Integration tests -- multi-turn (requires API key)
# ===========================================================================


@_skip_no_llm
@pytest.mark.asyncio
async def test_greeting():
    """Agent handles a greeting with no tools."""
    from app.planner.services.agent_runner import run_agent_turn

    result = await run_agent_turn("Hi!")
    assert result is not None
    assert "messages" in result
    # Should have at least the user message + agent response
    assert len(result["messages"]) >= 2


@_skip_no_llm
@pytest.mark.asyncio
async def test_multi_turn():
    """Agent handles greeting -> destination -> dates across turns."""
    from app.planner.services.agent_runner import run_agent_turn

    # Turn 1: Greeting
    state = await run_agent_turn("Hi, I want to plan a trip!")
    assert state is not None
    assert "messages" in state

    # Turn 2: Destination
    state = await run_agent_turn(
        "I want to go to Bali for diving",
        session_state=state,
    )
    trip = state.get("trip_plan", {})
    # The agent should have extracted the destination via extract_trip_fields tool
    assert trip.get("destination") is not None or len(state["messages"]) > 2

    # Turn 3: Dates
    state = await run_agent_turn(
        "March 1 to March 8, 2026",
        session_state=state,
    )
    trip = state.get("trip_plan", {})
    # At minimum, conversation should have progressed
    assert len(state["messages"]) >= 4


@_skip_no_llm
@pytest.mark.asyncio
async def test_serialization_roundtrip_with_agent():
    """State from a live agent call serializes and deserializes correctly."""
    from app.planner.services.agent_runner import run_agent_turn

    state = await run_agent_turn("I want to visit Bali March 1-8 for diving")

    # Serialize (already serialized by run_agent_turn)
    serialized = state

    # Deserialize
    restored = restore_agent_state(serialized)
    assert isinstance(restored["messages"], list)
    assert restored.get("trip_plan") == state.get("trip_plan", {})

    # Re-serialize should be stable
    re_serialized = serialize_agent_state(restored)
    assert re_serialized.get("trip_plan") == serialized.get("trip_plan")
