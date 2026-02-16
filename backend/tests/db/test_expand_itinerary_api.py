"""State gating tests for expand-itinerary/remove-specialist view-state semantics."""

from app.main import _resolve_itinerary_document_view_state, _resolve_stage3_view_state


def test_success_without_conflicts_is_ready() -> None:
    assert _resolve_stage3_view_state(True, []) == "S3_ITINERARY_READY"


def test_success_with_conflicts_is_editing() -> None:
    conflicts = [{"type": "temporal_capacity", "message": "Too many hours"}]
    assert _resolve_stage3_view_state(True, conflicts) == "S3_EDITING"


def test_failed_build_with_conflicts_is_partial_conflict() -> None:
    conflicts = [{"type": "constraint_clash", "message": "No-fly buffer conflict"}]
    assert _resolve_stage3_view_state(False, conflicts) == "S3_PARTIAL_CONFLICT"


def test_document_view_state_matches_itinerary_shape_and_conflicts() -> None:
    day_cards = [{"day_number": 1, "label": "Day 1", "blocks": []}]

    ready_state = _resolve_itinerary_document_view_state("S2_STRATEGY_READY", day_cards, [])
    editing_state = _resolve_itinerary_document_view_state(
        "S2_STRATEGY_READY",
        day_cards,
        [{"code": "TEMPORAL_CAPACITY", "category": "itinerary"}],
    )

    assert ready_state == "S3_ITINERARY_READY"
    assert editing_state == "S3_EDITING"


def test_document_view_state_preserves_partial_conflict_when_emitted() -> None:
    day_cards = [{"day_number": 1, "label": "Day 1", "blocks": []}]

    preserved = _resolve_itinerary_document_view_state(
        "S3_PARTIAL_CONFLICT",
        day_cards,
        [{"code": "TEMPORAL_CAPACITY", "category": "itinerary"}],
    )

    assert preserved == "S3_PARTIAL_CONFLICT"
