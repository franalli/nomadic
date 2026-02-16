import asyncio
import importlib
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.planner.nodes.logistics_node import (
    _resolve_tier2_experience_tiles,
    _tier2_generation_key,
)
from app.planner.state import GraphState, TripPlan

logistics_node_module = importlib.import_module("app.planner.nodes.logistics_node")
unsplash_module = importlib.import_module("app.services.unsplash")


@pytest.mark.asyncio
async def test_tier2_reuses_cached_tiles_without_regeneration():
    destination = "Bali"
    month = "2026-02"
    categories = {"yoga", "nightlife"}
    tiles_per_category = 4
    generation_key = _tier2_generation_key(destination, month, categories, tiles_per_category)
    cached_tiles = [
        {"id": "exp_bali_nightlife_1", "meta": {"category": "nightlife"}},
        {"id": "exp_bali_yoga_2", "meta": {"category": "yoga"}},
    ]

    state = SimpleNamespace(
        metadata={
            "tier2_generation_key": generation_key,
            "generated_tier2_categories": {
                destination: {
                    "nightlife": [cached_tiles[0]],
                    "yoga": [cached_tiles[1]],
                }
            },
        }
    )

    consume_prefetch = AsyncMock(return_value=None)
    generate_fn = AsyncMock(return_value=[{"id": "should_not_be_used"}])

    tiles = await _resolve_tier2_experience_tiles(
        state=state,
        destination=destination,
        month=month,
        categories=categories,
        tiles_per_category=tiles_per_category,
        budget=None,
        tier1_specialists=["diving", "surfing"],
        fallback_tiles=[],
        consume_prefetch=consume_prefetch,
        generate_fn=generate_fn,
        allow_prefetch_wait=True,
    )

    assert tiles == cached_tiles
    assert consume_prefetch.await_count == 0
    assert generate_fn.await_count == 0
    assert state.metadata.get("tier2_generation_source") == "reuse"
    assert state.metadata.get("tier2_generation_reason") == "matching_generation_key"


@pytest.mark.asyncio
async def test_tier2_timeout_falls_back_quickly(monkeypatch: pytest.MonkeyPatch):
    destination = "Bali"
    month = "2026-02"
    categories = {"yoga"}
    fallback_tiles = [{"id": "fallback_tile", "tags": ["yoga"]}]
    state = SimpleNamespace(metadata={})

    async def _slow_generate(**_kwargs):
        await asyncio.sleep(0.05)
        return [{"id": "late_tile"}]

    consume_prefetch = AsyncMock(return_value=None)
    scheduled = []

    def _capture_background(coro):
        scheduled.append(coro)
        coro.close()
        return SimpleNamespace()

    monkeypatch.setattr(settings, "tier2_generation_wait_budget_ms", 1)
    start = time.monotonic()
    tiles = await _resolve_tier2_experience_tiles(
        state=state,
        destination=destination,
        month=month,
        categories=categories,
        tiles_per_category=2,
        budget=None,
        tier1_specialists=None,
        fallback_tiles=fallback_tiles,
        consume_prefetch=consume_prefetch,
        generate_fn=_slow_generate,
        create_task_fn=_capture_background,
        allow_prefetch_wait=True,
    )
    elapsed_ms = int((time.monotonic() - start) * 1000)

    assert tiles == fallback_tiles
    assert elapsed_ms < 40
    assert state.metadata.get("tier2_generation_source") == "fallback_timeout"
    assert state.metadata.get("tier2_generation_reason") == "timeout"
    assert state.metadata.get("tier2_generation_elapsed_ms", 9999) <= 35
    assert len(scheduled) == 1


@pytest.mark.asyncio
async def test_tier2_timeout_schedules_background_prewarm(monkeypatch: pytest.MonkeyPatch):
    destination = "Bali"
    month = "2026-02"
    categories = {"yoga"}
    fallback_tiles = [{"id": "fallback_tile", "tags": ["yoga"]}]
    state = SimpleNamespace(metadata={})
    calls = []

    async def _generate(**kwargs):
        calls.append(kwargs.get("state"))
        if kwargs.get("state") is None:
            return [{"id": "bg_tile"}]
        await asyncio.sleep(0.05)
        return [{"id": "late_tile"}]

    consume_prefetch = AsyncMock(return_value=None)
    background_tasks = []

    def _spawn_background(coro):
        task = asyncio.create_task(coro)
        background_tasks.append(task)
        return task

    monkeypatch.setattr(settings, "tier2_generation_wait_budget_ms", 1)
    tiles = await _resolve_tier2_experience_tiles(
        state=state,
        destination=destination,
        month=month,
        categories=categories,
        tiles_per_category=2,
        budget=None,
        tier1_specialists=None,
        fallback_tiles=fallback_tiles,
        consume_prefetch=consume_prefetch,
        generate_fn=_generate,
        create_task_fn=_spawn_background,
        allow_prefetch_wait=True,
    )

    assert tiles == fallback_tiles
    assert state.metadata.get("tier2_generation_source") == "fallback_timeout"
    assert state.metadata.get("tier2_generation_reason") == "timeout"
    assert len(background_tasks) == 1
    await asyncio.gather(*background_tasks)
    assert any(call is None for call in calls)


@pytest.mark.asyncio
async def test_tier2_new_content_flag_false_for_reuse_without_activity_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = GraphState(
        trip_plan=TripPlan(destination="Bali", start_date="2026-02-15", end_date="2026-02-25")
    )
    state.tiles = {"hotels": [], "activities": [{"id": "exp_same"}], "flights": []}
    state.metadata.update(
        {
            "trip_inputs": {"activity_settings": {"categories": ["diving", "nightlife"]}},
            "executed_strategy_topics": ["diving"],
            "strategy_sections": [
                {"specialist_type": "diving", "content_added": [{"title": "Dive"}]}
            ],
        }
    )

    async def _fake_fetch_hotels(*_args, **_kwargs):
        return [{"id": "hotel_1"}]

    async def _fake_fetch_activities(*_args, **_kwargs):
        return [{"id": "generic_activity"}]

    async def _fake_resolve_tier2(**kwargs):
        kwargs["state"].metadata["tier2_generation_source"] = "reuse"
        return [
            {
                "id": "exp_same",
                "source_agent": "experience_generator",
                "meta": {"category": "nightlife"},
            }
        ]

    async def _fake_prefetch(*_args, **_kwargs):
        return None

    monkeypatch.setattr(logistics_node_module, "_fetch_hotels", _fake_fetch_hotels)
    monkeypatch.setattr(logistics_node_module, "_fetch_activities", _fake_fetch_activities)
    monkeypatch.setattr(
        logistics_node_module, "_resolve_tier2_experience_tiles", _fake_resolve_tier2
    )
    monkeypatch.setattr(unsplash_module, "prefetch_destination_images", _fake_prefetch)

    await logistics_node_module._search_hotels_and_activities(state, state.trip_plan)

    assert state.metadata.get("tier2_generation_source") == "reuse"
    assert state.metadata.get("tier2_new_content_generated") is False


@pytest.mark.asyncio
async def test_tier2_new_content_flag_true_when_activity_set_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = GraphState(
        trip_plan=TripPlan(destination="Bali", start_date="2026-02-15", end_date="2026-02-25")
    )
    state.tiles = {"hotels": [], "activities": [{"id": "exp_old"}], "flights": []}
    state.metadata.update(
        {
            "trip_inputs": {"activity_settings": {"categories": ["diving", "nightlife"]}},
            "executed_strategy_topics": ["diving"],
            "strategy_sections": [
                {"specialist_type": "diving", "content_added": [{"title": "Dive"}]}
            ],
        }
    )

    async def _fake_fetch_hotels(*_args, **_kwargs):
        return [{"id": "hotel_1"}]

    async def _fake_fetch_activities(*_args, **_kwargs):
        return [{"id": "generic_activity"}]

    async def _fake_resolve_tier2(**kwargs):
        kwargs["state"].metadata["tier2_generation_source"] = "llm"
        return [
            {
                "id": "exp_new",
                "source_agent": "experience_generator",
                "meta": {"category": "nightlife"},
            }
        ]

    async def _fake_prefetch(*_args, **_kwargs):
        return None

    monkeypatch.setattr(logistics_node_module, "_fetch_hotels", _fake_fetch_hotels)
    monkeypatch.setattr(logistics_node_module, "_fetch_activities", _fake_fetch_activities)
    monkeypatch.setattr(
        logistics_node_module, "_resolve_tier2_experience_tiles", _fake_resolve_tier2
    )
    monkeypatch.setattr(unsplash_module, "prefetch_destination_images", _fake_prefetch)

    await logistics_node_module._search_hotels_and_activities(state, state.trip_plan)

    assert state.metadata.get("tier2_generation_source") == "llm"
    assert state.metadata.get("tier2_new_content_generated") is True


@pytest.mark.asyncio
async def test_logistics_sets_no_origin_flight_skip_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = GraphState(
        trip_plan=TripPlan(destination="Bali", start_date="2026-02-15", end_date="2026-02-25")
    )
    state.tiles = {"hotels": [], "activities": [], "flights": []}
    state.metadata["trip_inputs"] = {"booking_types": {"flights": "on"}}

    async def _fake_search_hotels_and_activities(state_arg, _plan_arg):
        state_arg.tiles["hotels"] = [{"id": "hotel_1"}]
        state_arg.tiles["activities"] = [{"id": "act_1"}]

    monkeypatch.setattr(
        logistics_node_module,
        "_search_hotels_and_activities",
        _fake_search_hotels_and_activities,
    )

    await logistics_node_module.logistics_node(state)

    assert state.metadata.get("flight_search_possible") is False
    assert state.metadata.get("flight_search_status") == "skipped_no_origin"
    assert state.metadata.get("flight_skip_reason") == "no_origin_for_flights"
    assert state.metadata.get("booking_summary", {}).get("flights_found") == 0
    assert state.tiles.get("flights") == []


def _offer_with_segments(offer_id: str, segments: list[dict], price: str = "500.0") -> dict:
    return {
        "id": offer_id,
        "itineraries": [{"segments": segments}],
        "price": {"total": price},
    }


@pytest.mark.asyncio
async def test_logistics_direct_only_filters_non_direct_offers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = GraphState(
        trip_plan=TripPlan(
            destination="Testville",
            origin="Rome",
            start_date="2026-02-15",
            end_date="2026-02-25",
        )
    )
    state.tiles = {"hotels": [], "activities": [], "flights": []}
    state.metadata["trip_inputs"] = {
        "booking_types": {"flights": "on"},
        "flight_settings": {"direct_only": True},
    }

    async def _fake_search_hotels_and_activities(state_arg, _plan_arg):
        state_arg.tiles["hotels"] = [{"id": "hotel_1"}]
        state_arg.tiles["activities"] = [{"id": "act_1"}]

    async def _fake_resolve_iata_codes(_origin: str, _destination: str, _state):
        return "FCO", "DPS"

    direct_segments = [
        {
            "carrierCode": "SQ",
            "departure": {"at": "2026-02-25T10:00:00"},
            "duration": "PT16H",
        }
    ]
    one_stop_segments = [
        {
            "carrierCode": "SQ",
            "departure": {"at": "2026-02-25T12:00:00"},
            "duration": "PT11H",
        },
        {
            "carrierCode": "SQ",
            "departure": {"at": "2026-02-25T18:00:00"},
            "duration": "PT6H",
        },
    ]

    monkeypatch.setattr(
        logistics_node_module,
        "_search_hotels_and_activities",
        _fake_search_hotels_and_activities,
    )
    monkeypatch.setattr(logistics_node_module, "resolve_iata_codes", _fake_resolve_iata_codes)
    monkeypatch.setattr(
        logistics_node_module,
        "_get_mock_flights",
        lambda _date: [
            _offer_with_segments("flight_direct", direct_segments),
            _offer_with_segments("flight_one_stop", one_stop_segments),
        ],
    )

    await logistics_node_module.logistics_node(state)

    flights = state.tiles.get("flights", [])
    assert len(flights) == 1
    assert flights[0]["id"] == "flight_direct"
    assert flights[0]["meta"]["stops"] == 0
    assert flights[0]["meta"]["is_direct"] is True


@pytest.mark.asyncio
async def test_logistics_records_stop_metadata_when_direct_only_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = GraphState(
        trip_plan=TripPlan(
            destination="Testville",
            origin="Rome",
            start_date="2026-02-15",
            end_date="2026-02-25",
        )
    )
    state.tiles = {"hotels": [], "activities": [], "flights": []}
    state.metadata["trip_inputs"] = {
        "booking_types": {"flights": "on"},
        "flight_settings": {"direct_only": False},
    }

    async def _fake_search_hotels_and_activities(state_arg, _plan_arg):
        state_arg.tiles["hotels"] = [{"id": "hotel_1"}]
        state_arg.tiles["activities"] = [{"id": "act_1"}]

    async def _fake_resolve_iata_codes(_origin: str, _destination: str, _state):
        return "FCO", "DPS"

    direct_segments = [
        {
            "carrierCode": "SQ",
            "departure": {"at": "2026-02-25T10:00:00"},
            "duration": "PT16H",
        }
    ]
    one_stop_segments = [
        {
            "carrierCode": "SQ",
            "departure": {"at": "2026-02-25T12:00:00"},
            "duration": "PT11H",
        },
        {
            "carrierCode": "SQ",
            "departure": {"at": "2026-02-25T18:00:00"},
            "duration": "PT6H",
        },
    ]

    monkeypatch.setattr(
        logistics_node_module,
        "_search_hotels_and_activities",
        _fake_search_hotels_and_activities,
    )
    monkeypatch.setattr(logistics_node_module, "resolve_iata_codes", _fake_resolve_iata_codes)
    monkeypatch.setattr(
        logistics_node_module,
        "_get_mock_flights",
        lambda _date: [
            _offer_with_segments("flight_direct", direct_segments),
            _offer_with_segments("flight_one_stop", one_stop_segments),
        ],
    )

    await logistics_node_module.logistics_node(state)

    flights = {tile["id"]: tile for tile in state.tiles.get("flights", [])}
    assert set(flights.keys()) == {"flight_direct", "flight_one_stop"}
    assert flights["flight_direct"]["meta"]["stops"] == 0
    assert flights["flight_direct"]["meta"]["is_direct"] is True
    assert flights["flight_one_stop"]["meta"]["stops"] == 1
    assert flights["flight_one_stop"]["meta"]["is_direct"] is False


@pytest.mark.asyncio
async def test_logistics_logs_l1_state_invalidation_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = GraphState(
        trip_plan=TripPlan(
            destination="Bali",
            start_date="2026-02-15",
            end_date="2026-02-25",
        )
    )
    state.tiles = {"hotels": [{"id": "h"}], "activities": [{"id": "a"}], "flights": [{"id": "f"}]}
    state.metadata.update(
        {
            "_logistics_hotel_hash": "old_hotel_hash",
            "_logistics_activity_hash": "old_activity_hash",
            "_logistics_flight_hash": "old_flight_hash",
            "trip_inputs": {"booking_types": {"flights": "off"}},
        }
    )
    log_messages: list[str] = []

    async def _fake_search_hotels_and_activities(state_arg, _plan_arg):
        state_arg.tiles["hotels"] = [{"id": "hotel_1"}]
        state_arg.tiles["activities"] = [{"id": "act_1"}]

    def _capture_log(_scope: str, message: str, data: str | None = None):
        if data:
            log_messages.append(f"{message} | {data}")
        else:
            log_messages.append(message)

    monkeypatch.setattr(
        logistics_node_module,
        "_search_hotels_and_activities",
        _fake_search_hotels_and_activities,
    )
    monkeypatch.setattr(logistics_node_module, "log", _capture_log)

    await logistics_node_module.logistics_node(state)

    assert any("State invalidation (L1)" in msg for msg in log_messages)
