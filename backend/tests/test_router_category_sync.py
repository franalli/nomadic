from types import SimpleNamespace

from app.planner.nodes.logistics_node import _tier2_generation_key
from app.planner.nodes.router_category_sync import (
    _collect_modifications_from_extraction,
    _detect_actionable_input,
    _estimate_prefetch_tiles_per_category,
    _tier2_prefetch_key,
    detect_category_merge_mode,
    has_explicit_category_intent,
)
from app.planner.state import GraphState, TripPlan


def _build_state(start_date: str | None, end_date: str | None, specialist_items: int):
    strategy_sections = [
        {"specialist_type": "local_expert", "content_added": [{"title": "Tip"}]},
        {
            "specialist_type": "diving",
            "content_added": [{"title": f"Dive {i}"} for i in range(specialist_items)],
        },
    ]
    return SimpleNamespace(
        trip_plan=SimpleNamespace(start_date=start_date, end_date=end_date),
        metadata={"strategy_sections": strategy_sections},
    )


def test_detect_category_merge_mode_replace_only():
    assert detect_category_merge_mode("diving and surfing only") == "replace"


def test_detect_category_merge_mode_default_add():
    assert detect_category_merge_mode("add yoga and nightlife") == "add"


def test_detect_category_merge_mode_non_category_only_is_add():
    assert detect_category_merge_mode("5-star hotels only") == "add"


def test_detect_category_merge_mode_replace_for_synonym_with_router_output():
    router_output = {"activity_categories": ["nightlife"], "specialist_hints": []}
    assert detect_category_merge_mode("party only", router_output) == "replace"


def test_has_explicit_category_intent_false_for_hotel_only():
    assert has_explicit_category_intent("5-star hotels only") is False


def test_has_explicit_category_intent_true_for_removal_targets():
    router_output = {
        "activity_categories": [],
        "specialist_hints": [],
        "removal_targets": ["cultural"],
    }
    assert has_explicit_category_intent("remove all cultural", router_output) is True


def test_collect_modifications_skips_categories_when_intent_is_false():
    state = SimpleNamespace(
        metadata={"trip_inputs": {"activity_settings": {"categories": ["diving"]}}}
    )
    router_output = {
        "activity_categories": ["nightlife"],
        "specialist_hints": [],
        "removal_targets": [],
        "skill_level": None,
        "reset_budget": False,
        "reset_hotel": False,
    }
    changes = _collect_modifications_from_extraction(
        router_output,
        state,
        pre_populate_categories={"diving"},
        allow_category_modifications=False,
    )
    assert changes is None


def test_collect_modifications_includes_removals_when_intent_is_true():
    state = SimpleNamespace(
        metadata={"trip_inputs": {"activity_settings": {"categories": ["cultural"]}}}
    )
    router_output = {
        "activity_categories": [],
        "specialist_hints": [],
        "removal_targets": ["cultural"],
        "skill_level": None,
        "reset_budget": False,
        "reset_hotel": False,
    }
    has_intent = has_explicit_category_intent("remove all cultural", router_output)
    changes = _collect_modifications_from_extraction(
        router_output,
        state,
        pre_populate_categories={"cultural"},
        allow_category_modifications=has_intent,
    )
    assert changes == {"remove_categories": {"cultural"}}


def test_estimate_prefetch_tiles_per_category_scales_with_trip():
    state = _build_state("2026-02-15", "2026-03-07", specialist_items=5)
    tiles_per_category = _estimate_prefetch_tiles_per_category(state, {"yoga", "nightlife"})
    assert tiles_per_category == 4


def test_estimate_prefetch_tiles_per_category_defaults_without_dates():
    state = _build_state(None, None, specialist_items=0)
    tiles_per_category = _estimate_prefetch_tiles_per_category(state, {"yoga"})
    assert tiles_per_category == 2


def test_tier2_prefetch_key_matches_logistics_generation_key():
    categories = {"nightlife", "yoga"}
    router_key = _tier2_prefetch_key("Bali", "2026-02", categories, 4)
    logistics_key = _tier2_generation_key("Bali", "2026-02", categories, 4)
    assert router_key == logistics_key


def test_tier2_prefetch_key_is_stable_for_category_order():
    key_a = _tier2_prefetch_key("Bali", "2026-02", {"yoga", "nightlife"}, 4)
    key_b = _tier2_prefetch_key("Bali", "2026-02", {"nightlife", "yoga"}, 4)
    assert key_a == key_b


def test_detect_actionable_input_date_only_does_not_fuzzy_add_category():
    state = GraphState(trip_plan=TripPlan(destination="Bali"))
    changes = _detect_actionable_input("I'm thinking March 10 to March 17", state)
    assert not changes or "add_categories" not in changes
