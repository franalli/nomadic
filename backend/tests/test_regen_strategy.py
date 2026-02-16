"""Selective regeneration strategy tests."""

from app.services.regen_strategy import (
    RegenStrategy,
    compute_field_hashes,
    compute_strategy,
    detect_changed_fields,
)

BASE_TRIP_INPUTS = {
    "destination": "Bali",
    "start_date": "2026-03-01",
    "end_date": "2026-03-07",
    "adults": 2,
    "children": 0,
    "origin": "Rome",
    "activity_settings": {"categories": ["diving"], "skill_level": "intermediate"},
}


def test_preference_only_change_maps_to_builder() -> None:
    previous_hashes = compute_field_hashes(
        BASE_TRIP_INPUTS,
        {"preferred_tile_ids": ["tile_a", "tile_b"]},
    )
    current_hashes = compute_field_hashes(
        BASE_TRIP_INPUTS,
        {"preferred_tile_ids": ["tile_a", "tile_b", "tile_c"]},
    )

    changed = detect_changed_fields(previous_hashes, current_hashes)
    strategy = compute_strategy(changed)

    assert changed == {"preferences"}
    assert strategy == RegenStrategy.BUILDER


def test_preference_order_does_not_count_as_change() -> None:
    previous_hashes = compute_field_hashes(
        BASE_TRIP_INPUTS,
        {"preferred_tile_ids": ["tile_b", "tile_a"]},
    )
    current_hashes = compute_field_hashes(
        BASE_TRIP_INPUTS,
        {"preferred_tile_ids": ["tile_a", "tile_b"]},
    )

    changed = detect_changed_fields(previous_hashes, current_hashes)

    assert "preferences" not in changed


def test_destination_plus_preferences_still_forces_full() -> None:
    previous_hashes = compute_field_hashes(
        BASE_TRIP_INPUTS,
        {"preferred_tile_ids": ["tile_a"]},
    )
    next_inputs = dict(BASE_TRIP_INPUTS)
    next_inputs["destination"] = "Dubai"
    current_hashes = compute_field_hashes(
        next_inputs,
        {"preferred_tile_ids": ["tile_b"]},
    )

    changed = detect_changed_fields(previous_hashes, current_hashes)
    strategy = compute_strategy(changed)

    assert "destination" in changed
    assert "preferences" in changed
    assert strategy == RegenStrategy.FULL
