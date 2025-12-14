import pytest

from app.plan_graph import GraphState, TripInputs, _detect_short_circuit


@pytest.mark.parametrize("text", ["sure", "yep", "sounds good"])
def test_pending_action_confirmation_yes_variants_trigger_generate_plan(text: str) -> None:
    state = GraphState(
        user_text="",
        trip_inputs=TripInputs(),
        metadata={"pending_action": "generate_plan"},
    )

    result = _detect_short_circuit(text, state)
    assert result is not None
    assert result["type"] == "confirmation_yes"
    assert result["action"] == "generate_plan"


@pytest.mark.parametrize("text", ["nope"])
def test_pending_action_confirmation_no_clears_pending_action(text: str) -> None:
    state = GraphState(
        user_text="",
        trip_inputs=TripInputs(),
        metadata={"pending_action": "generate_plan"},
    )

    result = _detect_short_circuit(text, state)
    assert result is not None
    assert result["type"] == "confirmation_no"
    assert result["action"] == "clear_pending"
