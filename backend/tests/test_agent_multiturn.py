"""
Tests for agent state serialization and coordinator dispatch integration.

The serialization tests are pure unit tests (no API keys needed).
"""

from __future__ import annotations

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.planner.services.state_serde import (
    restore_agent_state,
    serialize_agent_state,
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
            "specialist_plans": {
                "diving": {
                    "topic": "diving",
                    "feasibility_status": "feasible",
                    "day_plans": [{"day_number": 2, "title": "USAT Liberty"}],
                    "constraints": [{"constraint_id": "no_fly_24h"}],
                    "editorial": "March is perfect for Tulamben",
                    "confidence": 0.85,
                },
            },
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
        assert result["specialist_plans"] == state["specialist_plans"]
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
        assert result["specialist_plans"] == {}
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

    def test_specialist_plans_roundtrip(self):
        """specialist_plans round-trips through serialize -> restore."""
        diving_plan = {
            "topic": "diving",
            "feasibility_status": "feasible",
            "day_plans": [
                {"day_number": 2, "title": "USAT Liberty", "location": "Tulamben"},
                {"day_number": 3, "title": "Manta Point", "location": "Nusa Penida"},
            ],
            "constraints": [
                {"constraint_id": "no_fly_24h", "reason": "24h no-fly buffer after diving"},
            ],
            "transit_requirements": [],
            "estimated_cost": None,
            "editorial": "March is perfect for Tulamben visibility",
            "confidence": 0.85,
        }
        hiking_plan = {
            "topic": "hiking",
            "feasibility_status": "feasible",
            "day_plans": [
                {"day_number": 5, "title": "Mount Batur Sunrise", "location": "Kintamani"},
            ],
            "constraints": [],
            "transit_requirements": [],
            "estimated_cost": None,
            "editorial": "Dry season is ideal for Batur",
            "confidence": 0.9,
        }
        original = {
            "messages": [HumanMessage(content="Plan diving and hiking in Bali")],
            "trip_plan": {"destination": "Bali"},
            "specialist_plans": {"diving": diving_plan, "hiking": hiking_plan},
        }

        serialized = serialize_agent_state(original)
        assert serialized["specialist_plans"] == original["specialist_plans"]

        restored = restore_agent_state(serialized)
        assert restored["specialist_plans"]["diving"]["topic"] == "diving"
        assert (
            restored["specialist_plans"]["diving"]["editorial"]
            == "March is perfect for Tulamben visibility"
        )
        assert len(restored["specialist_plans"]["diving"]["day_plans"]) == 2
        assert restored["specialist_plans"]["hiking"]["topic"] == "hiking"
        assert restored["specialist_plans"]["hiking"]["confidence"] == 0.9

        # Re-serialize should be identical
        re_serialized = serialize_agent_state(restored)
        assert re_serialized["specialist_plans"] == serialized["specialist_plans"]

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
        # Legacy sessions have no specialist_plans — should default to {}
        assert restored["specialist_plans"] == {}

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
# Selective re-dispatch (serde → coordinator dispatch list integration)
# ===========================================================================


def test_selective_redispatch_preserves_unaffected_plans() -> None:
    """Verify that specialist_plans survives round-trip and _compute_preserve_list
    returns topics not in the dispatch list."""
    from app.planner.coordinator import _compute_dispatch_list, _compute_preserve_list
    from app.planner.schemas.coordinator_schemas import ChangeType, ClassifierOutput

    # Simulate a session with two specialist plans
    original_state = {
        "messages": [HumanMessage(content="Plan diving and hiking in Bali")],
        "trip_plan": {"destination": "Bali", "start_date": "2026-03-01", "end_date": "2026-03-08"},
        "trip_settings": {"activity_settings": {"categories": ["diving", "hiking"]}},
        "specialist_plans": {
            "diving": {
                "topic": "diving",
                "feasibility_status": "feasible",
                "day_plans": [{"day_number": 2}],
            },
            "hiking": {
                "topic": "hiking",
                "feasibility_status": "feasible",
                "day_plans": [{"day_number": 5}],
            },
        },
    }

    # Round-trip through serde
    serialized = serialize_agent_state(original_state)
    restored = restore_agent_state(serialized)

    # Classifier says only diving is affected
    classifier = ClassifierOutput(
        intent="PLANNING",
        reasoning="User wants to change dive sites",
        change_type=ChangeType.SWAP_ACTIVITY,
        affects=["diving"],
        preserves=["hiking"],
    )

    dispatch = _compute_dispatch_list(classifier, restored)
    preserve = _compute_preserve_list(classifier, restored)

    assert dispatch == ["diving"]
    assert preserve == ["hiking"]
    # Hiking plan survives untouched
    assert restored["specialist_plans"]["hiking"]["day_plans"] == [{"day_number": 5}]
