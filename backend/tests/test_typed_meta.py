"""Tests for typed metadata models and bridge functions."""

from app.planner.state.graph_state import TripSettings
from app.planner.state.typed_meta import (
    _PERSISTENT_FIELDS,
    _TURN_FIELDS,
    PersistentMeta,
    TurnMeta,
    get_persistent_meta,
    get_trip_settings,
    get_turn_meta,
    reset_turn_metadata,
    sync_persistent_meta,
    sync_turn_meta,
)
from app.schemas import (
    ActivitySettings,
    BookingTypes,
    FlightSettings,
    HotelSettings,
)

# =============================================================================
# Helpers
# =============================================================================


class FakeState:
    """Minimal stand-in for GraphState — only needs .metadata dict."""

    def __init__(self, metadata: dict | None = None):
        self.metadata = metadata if metadata is not None else {}


# =============================================================================
# TurnMeta model tests
# =============================================================================


class TestTurnMeta:
    def test_defaults_are_clean(self):
        """TurnMeta() should produce a clean slate with all defaults."""
        turn = TurnMeta()
        assert turn.short_circuit_response is False
        assert turn.architect_ran_this_turn is False
        assert turn.has_blocking_violations is False
        assert turn.constraints_validated == []
        assert turn.constraint_violations == []
        assert turn.violations_for_retry == []
        assert turn.llm_calls_this_turn == 0
        assert turn.visited_nodes == []
        assert turn.step_count == 0

    def test_field_count(self):
        """Ensure TurnMeta has the expected number of fields (catch accidental removals)."""
        assert len(TurnMeta.model_fields) >= 25  # Current count is ~28

    def test_no_overlap_with_persistent(self):
        """TurnMeta and PersistentMeta should have disjoint field sets."""
        overlap = _TURN_FIELDS & _PERSISTENT_FIELDS
        assert overlap == set(), f"Overlapping fields: {overlap}"


# =============================================================================
# PersistentMeta model tests
# =============================================================================


class TestPersistentMeta:
    def test_defaults_are_empty(self):
        """PersistentMeta() should produce empty containers."""
        meta = PersistentMeta()
        assert meta.strategy_sections == []
        assert meta.executed_strategy_topics == []
        assert meta.trip_inputs == {}
        assert meta.specialist_constraints == {}
        assert meta.local_expert_ran is False

    def test_field_count(self):
        assert len(PersistentMeta.model_fields) >= 8  # Current count is ~10


# =============================================================================
# Bridge function tests
# =============================================================================


class TestGetTurnMeta:
    def test_empty_metadata(self):
        """get_turn_meta on empty metadata returns defaults."""
        state = FakeState()
        turn = get_turn_meta(state)
        assert turn.has_blocking_violations is False
        assert turn.constraints_validated == []

    def test_reads_existing_values(self):
        """get_turn_meta picks up values already in metadata."""
        state = FakeState({"has_blocking_violations": True, "step_count": 5})
        turn = get_turn_meta(state)
        assert turn.has_blocking_violations is True
        assert turn.step_count == 5

    def test_ignores_unknown_keys(self):
        """get_turn_meta silently ignores keys not in TurnMeta."""
        state = FakeState({"unknown_key_xyz": 42, "has_blocking_violations": True})
        turn = get_turn_meta(state)
        assert turn.has_blocking_violations is True
        # unknown_key_xyz is not on the model
        assert not hasattr(turn, "unknown_key_xyz")


class TestSyncTurnMeta:
    def test_writes_to_metadata(self):
        """sync_turn_meta writes all TurnMeta fields to state.metadata."""
        state = FakeState()
        turn = TurnMeta(has_blocking_violations=True, step_count=3)
        sync_turn_meta(state, turn)
        assert state.metadata["has_blocking_violations"] is True
        assert state.metadata["step_count"] == 3
        assert state.metadata["short_circuit_response"] is False  # default written too

    def test_preserves_unknown_keys(self):
        """sync_turn_meta does not delete keys it doesn't own."""
        state = FakeState({"unknown_key_xyz": 42, "strategy_sections": [{"id": "s1"}]})
        turn = TurnMeta()
        sync_turn_meta(state, turn)
        assert state.metadata["unknown_key_xyz"] == 42
        assert state.metadata["strategy_sections"] == [{"id": "s1"}]


class TestResetTurnMetadata:
    def test_resets_stale_flags(self):
        """reset_turn_metadata clears stale per-turn values."""
        state = FakeState(
            {
                "architect_ran_this_turn": True,
                "has_blocking_violations": True,
                "step_count": 7,
                "constraint_violations": [{"code": "STALE"}],
                # Persistent key — should survive
                "strategy_sections": [{"id": "s1"}],
            }
        )
        reset_turn_metadata(state)
        assert state.metadata["architect_ran_this_turn"] is False
        assert state.metadata["has_blocking_violations"] is False
        assert state.metadata["step_count"] == 0
        assert state.metadata["constraint_violations"] == []
        # Persistent key preserved
        assert state.metadata["strategy_sections"] == [{"id": "s1"}]

    def test_replaces_three_adhoc_resets(self):
        """Verify the 3 keys that were previously ad-hoc reset in _restore_graph_state."""
        state = FakeState(
            {
                "architect_ran_this_turn": True,
                "origin_only_logistics": True,
                "short_circuit_response": True,
            }
        )
        reset_turn_metadata(state)
        assert state.metadata["architect_ran_this_turn"] is False
        assert state.metadata["origin_only_logistics"] is False
        assert state.metadata["short_circuit_response"] is False


class TestRoundTrip:
    def test_turn_meta_round_trip(self):
        """Write → read → write cycle preserves values."""
        state = FakeState()
        turn = TurnMeta(
            has_blocking_violations=True,
            constraints_validated=[{"id": "test", "status": "satisfied"}],
            step_count=5,
        )
        sync_turn_meta(state, turn)

        # Read back
        turn2 = get_turn_meta(state)
        assert turn2.has_blocking_violations is True
        assert turn2.constraints_validated == [{"id": "test", "status": "satisfied"}]
        assert turn2.step_count == 5

        # Modify and write again
        turn2.step_count = 10
        sync_turn_meta(state, turn2)
        assert state.metadata["step_count"] == 10

    def test_persistent_meta_round_trip(self):
        """Write → read → write cycle for persistent meta."""
        state = FakeState()
        meta = PersistentMeta(
            strategy_sections=[{"id": "s1", "specialist_type": "diving"}],
            executed_strategy_topics=["diving"],
            trip_inputs={"destination": "Bali"},
        )
        sync_persistent_meta(state, meta)

        meta2 = get_persistent_meta(state)
        assert meta2.strategy_sections == [{"id": "s1", "specialist_type": "diving"}]
        assert meta2.executed_strategy_topics == ["diving"]
        assert meta2.trip_inputs == {"destination": "Bali"}


# =============================================================================
# TripSettings model tests
# =============================================================================


class TestTripSettings:
    def test_defaults(self):
        """TripSettings() produces safe defaults matching DocumentTripInputs."""
        settings = TripSettings()
        assert settings.booking_types.hotels == "suggested"
        assert settings.booking_types.flights == "off"
        assert settings.booking_types.activities == "suggested"
        assert settings.flight_settings.round_trip is True
        assert settings.flight_settings.cabin_class == "economy"
        assert settings.flight_settings.direct_only is False
        assert settings.hotel_settings.min_stars == 0
        assert settings.hotel_settings.amenities == []
        assert settings.activity_settings.categories == []
        assert settings.activity_settings.skill_level is None
        assert settings.transport_settings.car is False
        assert settings.date_flex is False
        assert settings.trip_duration is None

    def test_from_dict(self):
        """TripSettings can be constructed from frontend-style dicts."""
        activity_payload = {"categories": ["diving", "hiking"], "skill_level": "advanced"}
        settings = TripSettings(
            booking_types=BookingTypes(**{"flights": "suggested", "hotels": "on"}),
            flight_settings=FlightSettings(**{"direct_only": True, "cabin_class": "business"}),
            hotel_settings=HotelSettings(**{"min_stars": 4}),
            activity_settings=ActivitySettings(**activity_payload),
        )
        assert settings.booking_types.flights == "suggested"
        assert settings.booking_types.hotels == "on"
        assert settings.flight_settings.direct_only is True
        assert settings.flight_settings.cabin_class == "business"
        assert settings.hotel_settings.min_stars == 4
        assert settings.activity_settings.categories == ["diving", "hiking"]
        assert settings.activity_settings.skill_level == "advanced"

    def test_round_trip_model_dump(self):
        """model_dump() -> TripSettings(**dump) preserves all values."""
        original = TripSettings(
            booking_types=BookingTypes(flights="on", hotels="off"),
            activity_settings=ActivitySettings(categories=["surfing"], skill_level="beginner"),
            date_flex=True,
            trip_duration=7,
        )
        dump = original.model_dump()
        restored = TripSettings(**dump)
        assert restored.booking_types.flights == "on"
        assert restored.booking_types.hotels == "off"
        assert restored.activity_settings.categories == ["surfing"]
        assert restored.activity_settings.skill_level == "beginner"
        assert restored.date_flex is True
        assert restored.trip_duration == 7

    def test_partial_dict_uses_defaults(self):
        """Missing keys in sub-dicts get Pydantic defaults."""
        settings = TripSettings(
            booking_types=BookingTypes(**{"flights": "on"}),
            hotel_settings=HotelSettings(**{}),
        )
        assert settings.booking_types.flights == "on"
        assert settings.booking_types.hotels == "suggested"  # default
        assert settings.hotel_settings.min_stars == 0  # default

    def test_booking_types_bool_coercion(self):
        """BookingTypes coerces legacy boolean values to tri-state strings."""
        bt = BookingTypes(**{"flights": True, "hotels": False})
        assert bt.flights == "on"
        assert bt.hotels == "off"


# =============================================================================
# get_trip_settings accessor tests
# =============================================================================


class TestGetTripSettings:
    def test_from_trip_settings_key(self):
        """get_trip_settings reads from metadata['trip_settings'] when present."""
        state = FakeState(
            {
                "trip_settings": {
                    "booking_types": {"flights": "on", "hotels": "suggested"},
                    "activity_settings": {"categories": ["diving"], "skill_level": "advanced"},
                }
            }
        )
        settings = get_trip_settings(state)
        assert isinstance(settings, TripSettings)
        assert settings.booking_types.flights == "on"
        assert settings.activity_settings.categories == ["diving"]
        assert settings.activity_settings.skill_level == "advanced"

    def test_fallback_to_trip_inputs(self):
        """get_trip_settings falls back to metadata['trip_inputs'] when trip_settings absent."""
        state = FakeState(
            {
                "trip_inputs": {
                    "booking_types": {"flights": "suggested"},
                    "activity_settings": {"categories": ["hiking"]},
                    "hotel_settings": {"min_stars": 3},
                    "date_flex": True,
                }
            }
        )
        settings = get_trip_settings(state)
        assert isinstance(settings, TripSettings)
        assert settings.booking_types.flights == "suggested"
        assert settings.activity_settings.categories == ["hiking"]
        assert settings.hotel_settings.min_stars == 3
        assert settings.date_flex is True

    def test_empty_metadata_returns_defaults(self):
        """get_trip_settings on empty metadata returns all defaults."""
        state = FakeState({})
        settings = get_trip_settings(state)
        assert settings.booking_types.flights == "off"
        assert settings.activity_settings.categories == []
        assert settings.hotel_settings.min_stars == 0

    def test_trip_settings_takes_priority(self):
        """When both trip_settings and trip_inputs exist, trip_settings wins."""
        state = FakeState(
            {
                "trip_settings": {
                    "booking_types": {"flights": "on"},
                },
                "trip_inputs": {
                    "booking_types": {"flights": "off"},
                },
            }
        )
        settings = get_trip_settings(state)
        assert settings.booking_types.flights == "on"

    def test_none_subdict_uses_defaults(self):
        """None values in trip_inputs sub-dicts produce defaults."""
        state = FakeState(
            {
                "trip_inputs": {
                    "booking_types": None,
                    "activity_settings": None,
                }
            }
        )
        settings = get_trip_settings(state)
        assert settings.booking_types.flights == "off"  # BookingTypes default
        assert settings.activity_settings.categories == []  # ActivitySettings default
