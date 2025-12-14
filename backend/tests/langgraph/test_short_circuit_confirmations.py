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


@pytest.mark.parametrize("text", ["yes", "yep", "sure", "sounds good"])
def test_pending_action_typo_confirmation_yes_applies_corrections(text: str) -> None:
    """Test that 'yes' to a pending typo confirmation triggers apply_typo_corrections."""
    typo_corrections = {"Patogonia": "Patagonia"}
    state = GraphState(
        user_text="",
        trip_inputs=TripInputs(),
        metadata={
            "pending_action": "confirm_typo",
            "pending_typo_corrections": typo_corrections,
        },
    )

    result = _detect_short_circuit(text, state)
    assert result is not None
    assert result["type"] == "confirm_typo"
    assert result["action"] == "apply_typo_corrections"
    assert result["parsed"]["typo_corrections"] == typo_corrections


@pytest.mark.parametrize("text", ["no", "nope", "nah"])
def test_pending_action_typo_confirmation_no_clears_pending(text: str) -> None:
    """Test that 'no' to a pending typo confirmation clears pending action."""
    typo_corrections = {"Patogonia": "Patagonia"}
    state = GraphState(
        user_text="",
        trip_inputs=TripInputs(),
        metadata={
            "pending_action": "confirm_typo",
            "pending_typo_corrections": typo_corrections,
        },
    )

    result = _detect_short_circuit(text, state)
    assert result is not None
    assert result["type"] == "confirmation_no"
    assert result["action"] == "clear_pending"
