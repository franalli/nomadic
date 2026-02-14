"""Tests for settings extraction/apply behavior in intent_router."""

from app.planner.nodes.intent_router import _apply_settings_to_state
from app.planner.state import GraphState


def test_apply_settings_sets_flights_toggle_as_tri_state_string():
    state = GraphState()
    state.trip_plan.destination = "Bali"
    state.metadata["trip_inputs"] = {}

    detected_settings = {
        "flight_settings": {
            "direct_only": True,
        }
    }

    _apply_settings_to_state(state, detected_settings, clog=None)

    extracted = state.metadata.get("extracted_settings", {})
    assert extracted.get("flights_toggle") == "on"
    assert extracted.get("flight_direct_only") is True
