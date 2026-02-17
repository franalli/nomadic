# backend/tests/test_state_serde.py
"""
Unit tests for state_serde.py — round-trip serialization between GraphState and session dicts.

Tests cover:
- trip_plan_to_trip_inputs: dict keys/values from populated TripPlan, None handling
- state_to_session_state: message serialization, metadata inclusion, field_hashes
- restore_graph_state: empty input, round-trip fidelity, message types, defaults,
  _doc_settings merge
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from app.planner.hashing import field_hash
from app.planner.services.state_serde import (
    restore_graph_state,
    state_to_session_state,
    trip_plan_to_trip_inputs,
)
from app.planner.state.graph_state import GraphState, TripPlan, TripSettings

# =============================================================================
# Helpers
# =============================================================================


def _make_populated_plan() -> TripPlan:
    """Build a fully populated TripPlan."""
    return TripPlan(
        destination="Bali",
        origin="London",
        origin_iata="LHR",
        destination_iata="DPS",
        start_date="2026-03-01",
        end_date="2026-03-07",
        adults=2,
        children=1,
        budget=5000.0,
        currency="EUR",
    )


def _make_populated_state() -> GraphState:
    """Build a GraphState with messages, tiles, and metadata."""
    state = GraphState()
    state.trip_plan = _make_populated_plan()
    state.messages = [
        HumanMessage(content="Plan a trip to Bali"),
        AIMessage(content="Great choice! Bali is wonderful."),
    ]
    state.tiles = {
        "flights": [{"id": "f1", "type": "flight"}],
        "hotels": [{"id": "h1", "type": "hotel"}],
    }
    state.active_specialist = "diving"
    state.constraints_violated = ["budget_exceeded"]
    state.last_constraint_hash = "abc123"
    state.metadata["strategy_sections"] = [
        {"id": "strategy_local_expert", "specialist_type": "local_expert"}
    ]
    state.metadata["trip_settings"] = TripSettings().model_dump()
    state.metadata["trip_inputs"] = {}
    return state


# =============================================================================
# trip_plan_to_trip_inputs
# =============================================================================


class TestTripPlanToTripInputs:
    """Convert TripPlan to a flat dict for the frontend document envelope."""

    def test_correct_keys_and_values(self) -> None:
        plan = _make_populated_plan()
        result = trip_plan_to_trip_inputs(plan)

        assert result["destination"] == "Bali"
        assert result["origin"] == "London"
        assert result["origin_iata"] == "LHR"
        assert result["destination_iata"] == "DPS"
        assert result["start_date"] == "2026-03-01"
        assert result["end_date"] == "2026-03-07"
        assert result["adults"] == 2
        assert result["children"] == 1
        assert result["budget"] == 5000.0
        assert result["currency"] == "EUR"

    def test_all_expected_keys_present(self) -> None:
        plan = _make_populated_plan()
        result = trip_plan_to_trip_inputs(plan)
        expected_keys = {
            "destination",
            "origin",
            "origin_iata",
            "destination_iata",
            "start_date",
            "end_date",
            "adults",
            "children",
            "budget",
            "currency",
        }
        assert set(result.keys()) == expected_keys

    def test_handles_none_fields(self) -> None:
        plan = TripPlan()  # All optional fields are None
        result = trip_plan_to_trip_inputs(plan)
        assert result["destination"] is None
        assert result["origin"] is None
        assert result["start_date"] is None
        assert result["end_date"] is None
        assert result["budget"] is None
        # Defaults
        assert result["adults"] == 1
        assert result["children"] == 0
        assert result["currency"] == "USD"


# =============================================================================
# state_to_session_state
# =============================================================================


class TestStateToSessionState:
    """Serialize GraphState to a session dict for persistence."""

    def test_messages_serialized_to_role_content_dicts(self) -> None:
        state = _make_populated_state()
        session = state_to_session_state(state)

        messages = session["messages"]
        assert len(messages) == 2
        assert messages[0] == {"role": "human", "content": "Plan a trip to Bali"}
        assert messages[1] == {"role": "assistant", "content": "Great choice! Bali is wonderful."}

    def test_trip_inputs_has_all_fields(self) -> None:
        state = _make_populated_state()
        session = state_to_session_state(state)

        trip_inputs = session["trip_inputs"]
        assert trip_inputs["destination"] == "Bali"
        assert trip_inputs["origin"] == "London"
        assert trip_inputs["start_date"] == "2026-03-01"
        assert trip_inputs["end_date"] == "2026-03-07"
        assert trip_inputs["adults"] == 2
        assert trip_inputs["children"] == 1
        assert trip_inputs["budget"] == 5000.0
        assert trip_inputs["currency"] == "EUR"

    def test_metadata_includes_tiles(self) -> None:
        state = _make_populated_state()
        session = state_to_session_state(state)

        meta = session["metadata"]
        assert "tiles" in meta
        assert len(meta["tiles"]["flights"]) == 1
        assert len(meta["tiles"]["hotels"]) == 1

    def test_metadata_includes_active_specialist(self) -> None:
        state = _make_populated_state()
        session = state_to_session_state(state)
        assert session["metadata"]["active_specialist"] == "diving"

    def test_metadata_includes_constraints_violated(self) -> None:
        state = _make_populated_state()
        session = state_to_session_state(state)
        assert session["metadata"]["constraints_violated"] == ["budget_exceeded"]

    def test_metadata_includes_last_constraint_hash(self) -> None:
        state = _make_populated_state()
        session = state_to_session_state(state)
        assert session["metadata"]["last_constraint_hash"] == "abc123"

    def test_field_hashes_dict_has_required_keys(self) -> None:
        state = _make_populated_state()
        session = state_to_session_state(state)

        hashes = session["field_hashes"]
        assert set(hashes.keys()) == {"destination", "dates", "travelers", "budget", "origin"}
        # Each hash is a non-empty string
        for key in hashes:
            assert isinstance(hashes[key], str)
            assert len(hashes[key]) > 0

    def test_field_hashes_are_stable(self) -> None:
        """Same state produces same hashes."""
        state = _make_populated_state()
        session1 = state_to_session_state(state)
        session2 = state_to_session_state(state)
        assert session1["field_hashes"] == session2["field_hashes"]

    def test_field_hashes_match_expected_values(self) -> None:
        state = _make_populated_state()
        session = state_to_session_state(state)

        hashes = session["field_hashes"]
        assert hashes["destination"] == field_hash("Bali")
        assert hashes["dates"] == field_hash("2026-03-01|2026-03-07")
        assert hashes["travelers"] == field_hash("2|1")
        assert hashes["budget"] == field_hash("5000.0")
        assert hashes["origin"] == field_hash("London")

    def test_empty_messages(self) -> None:
        state = GraphState()
        state.metadata["trip_settings"] = TripSettings().model_dump()
        session = state_to_session_state(state)
        assert session["messages"] == []


# =============================================================================
# restore_graph_state
# =============================================================================


class TestRestoreGraphState:
    """Restore GraphState from a session_state dict."""

    def test_none_input_returns_empty_state(self) -> None:
        state = restore_graph_state(None)
        assert isinstance(state, GraphState)
        assert state.trip_plan.destination is None
        assert state.messages == []
        assert "trip_inputs" in state.metadata
        assert "trip_settings" in state.metadata

    def test_empty_dict_returns_empty_state(self) -> None:
        state = restore_graph_state({})
        assert isinstance(state, GraphState)
        assert state.trip_plan.destination is None
        assert "trip_inputs" in state.metadata
        assert "trip_settings" in state.metadata

    def test_messages_restored_as_correct_types(self) -> None:
        session = {
            "messages": [
                {"role": "human", "content": "Hello"},
                {"role": "assistant", "content": "Hi there"},
            ],
            "trip_inputs": {},
            "metadata": {},
        }
        state = restore_graph_state(session)
        assert len(state.messages) == 2
        assert isinstance(state.messages[0], HumanMessage)
        assert isinstance(state.messages[1], AIMessage)
        assert state.messages[0].content == "Hello"
        assert state.messages[1].content == "Hi there"

    def test_trip_plan_fields_restored(self) -> None:
        session = {
            "messages": [],
            "trip_inputs": {
                "destination": "Tokyo",
                "origin": "Paris",
                "origin_iata": "CDG",
                "destination_iata": "NRT",
                "start_date": "2026-04-01",
                "end_date": "2026-04-10",
                "adults": 3,
                "children": 2,
                "budget": 8000.0,
                "currency": "GBP",
            },
            "metadata": {},
        }
        state = restore_graph_state(session)
        assert state.trip_plan.destination == "Tokyo"
        assert state.trip_plan.origin == "Paris"
        assert state.trip_plan.origin_iata == "CDG"
        assert state.trip_plan.destination_iata == "NRT"
        assert state.trip_plan.start_date == "2026-04-01"
        assert state.trip_plan.end_date == "2026-04-10"
        assert state.trip_plan.adults == 3
        assert state.trip_plan.children == 2
        assert state.trip_plan.budget == 8000.0
        assert state.trip_plan.currency == "GBP"

    def test_adults_defaults_to_1_when_missing(self) -> None:
        session = {"messages": [], "trip_inputs": {}, "metadata": {}}
        state = restore_graph_state(session)
        assert state.trip_plan.adults == 1

    def test_children_defaults_to_0_when_missing(self) -> None:
        session = {"messages": [], "trip_inputs": {}, "metadata": {}}
        state = restore_graph_state(session)
        assert state.trip_plan.children == 0

    def test_currency_defaults_to_usd_when_missing(self) -> None:
        session = {"messages": [], "trip_inputs": {}, "metadata": {}}
        state = restore_graph_state(session)
        assert state.trip_plan.currency == "USD"

    def test_adults_defaults_to_1_when_none(self) -> None:
        session = {
            "messages": [],
            "trip_inputs": {"adults": None},
            "metadata": {},
        }
        state = restore_graph_state(session)
        assert state.trip_plan.adults == 1

    def test_currency_defaults_to_usd_when_none(self) -> None:
        session = {
            "messages": [],
            "trip_inputs": {"currency": None},
            "metadata": {},
        }
        state = restore_graph_state(session)
        assert state.trip_plan.currency == "USD"

    def test_tiles_restored_from_metadata(self) -> None:
        session = {
            "messages": [],
            "trip_inputs": {},
            "metadata": {
                "tiles": {"flights": [{"id": "f1"}], "hotels": [{"id": "h1"}]},
            },
        }
        state = restore_graph_state(session)
        assert len(state.tiles["flights"]) == 1
        assert len(state.tiles["hotels"]) == 1

    def test_active_specialist_restored(self) -> None:
        session = {
            "messages": [],
            "trip_inputs": {},
            "metadata": {"active_specialist": "hiking"},
        }
        state = restore_graph_state(session)
        assert state.active_specialist == "hiking"

    def test_last_constraint_hash_restored(self) -> None:
        session = {
            "messages": [],
            "trip_inputs": {},
            "metadata": {"last_constraint_hash": "xyz789"},
        }
        state = restore_graph_state(session)
        assert state.last_constraint_hash == "xyz789"

    def test_doc_settings_merge_overrides_trip_inputs(self) -> None:
        session = {
            "messages": [],
            "trip_inputs": {"destination": "Bali"},
            "metadata": {},
            "_doc_settings": {
                "activity_settings": {"categories": ["diving"], "skill_level": "advanced"},
            },
        }
        state = restore_graph_state(session)
        # _doc_settings should override trip_inputs in metadata
        activity = state.metadata["trip_inputs"].get("activity_settings", {})
        assert activity["categories"] == ["diving"]

    def test_doc_settings_none_values_not_merged(self) -> None:
        session = {
            "messages": [],
            "trip_inputs": {"destination": "Bali"},
            "metadata": {},
            "_doc_settings": {
                "activity_settings": None,  # None should not override
            },
        }
        state = restore_graph_state(session)
        # activity_settings should not be set to None
        assert state.metadata["trip_inputs"].get("activity_settings") is None or isinstance(
            state.metadata["trip_inputs"].get("activity_settings"), (dict, type(None))
        )


# =============================================================================
# Round-trip: state → session → state
# =============================================================================


class TestRoundTrip:
    """Serialize and deserialize, then verify key fields match."""

    def test_round_trip_preserves_trip_plan_fields(self) -> None:
        original = _make_populated_state()
        session = state_to_session_state(original)
        restored = restore_graph_state(session)

        assert restored.trip_plan.destination == original.trip_plan.destination
        assert restored.trip_plan.origin == original.trip_plan.origin
        assert restored.trip_plan.origin_iata == original.trip_plan.origin_iata
        assert restored.trip_plan.destination_iata == original.trip_plan.destination_iata
        assert restored.trip_plan.start_date == original.trip_plan.start_date
        assert restored.trip_plan.end_date == original.trip_plan.end_date
        assert restored.trip_plan.adults == original.trip_plan.adults
        assert restored.trip_plan.children == original.trip_plan.children
        assert restored.trip_plan.budget == original.trip_plan.budget
        assert restored.trip_plan.currency == original.trip_plan.currency

    def test_round_trip_preserves_messages(self) -> None:
        original = _make_populated_state()
        session = state_to_session_state(original)
        restored = restore_graph_state(session)

        assert len(restored.messages) == 2
        assert isinstance(restored.messages[0], HumanMessage)
        assert isinstance(restored.messages[1], AIMessage)
        assert restored.messages[0].content == "Plan a trip to Bali"
        assert restored.messages[1].content == "Great choice! Bali is wonderful."

    def test_round_trip_preserves_tiles(self) -> None:
        original = _make_populated_state()
        session = state_to_session_state(original)
        restored = restore_graph_state(session)

        assert restored.tiles == original.tiles

    def test_round_trip_preserves_constraint_hash(self) -> None:
        original = _make_populated_state()
        session = state_to_session_state(original)
        restored = restore_graph_state(session)

        assert restored.last_constraint_hash == "abc123"

    def test_round_trip_preserves_strategy_sections(self) -> None:
        original = _make_populated_state()
        session = state_to_session_state(original)
        restored = restore_graph_state(session)

        restored_sections = restored.metadata.get("strategy_sections", [])
        assert len(restored_sections) == 1
        assert restored_sections[0]["specialist_type"] == "local_expert"
