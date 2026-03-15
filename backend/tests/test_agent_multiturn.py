"""
Tests for agent state serialization and coordinator dispatch integration.

The serialization tests are pure unit tests (no API keys needed).
"""

from __future__ import annotations

import json

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
from tests.analyze_flow_logs import FlowReport, check_day_fill_rate

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
        assert result["day_cards"] == [{"day_number": None, "date": None, "label": None}]
        assert result["constraints"] == state["constraints"]
        assert result["specialist_plans"] == {
            "diving": {
                "topic": "diving",
                "feasibility_status": "feasible",
                "day_plans": [{"day_number": 2}],
                "constraints": [{"constraint_id": "no_fly_24h"}],
            }
        }
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

    def test_partner_enriched_tile_fields_survive_roundtrip(self):
        """Viator/GYG enrichment fields must survive session_state reuse on the next turn."""
        original = {
            "messages": [],
            "tiles": {
                "activities": [
                    {
                        "id": "spec_bali_diving_1",
                        "type": "activity",
                        "title": "USAT Liberty Shipwreck Shore Dive",
                        "provider": "viator",
                        "partner": "viator",
                        "partner_product_id": "98765P2",
                        "source": "live",
                        "source_agent": "vertical_specialist",
                        "price_estimate": 74.0,
                        "live_price": 74.0,
                        "currency": "USD",
                        "price_basis": "per_person",
                        "is_estimate_only": False,
                        "deeplink": "https://www.viator.com/tours/test/98765P2",
                        "image_url": "https://example.com/usat.jpg",
                        "meta": {
                            "duration_hours": 4.0,
                            "viator_product_code": "98765P2",
                        },
                    }
                ]
            },
            "day_cards": [
                {
                    "day_number": 1,
                    "label": "Day 1",
                    "blocks": [
                        {
                            "id": "block_1",
                            "period": "morning",
                            "activity_type": "experience",
                            "specialist_type": "diving",
                            "is_buffer": False,
                            "booked_tile": {
                                "id": "spec_bali_diving_1",
                                "type": "activity",
                                "title": "USAT Liberty Shipwreck Shore Dive",
                                "provider": "viator",
                                "partner": "viator",
                                "partner_product_id": "98765P2",
                                "source": "live",
                                "source_agent": "vertical_specialist",
                                "price_estimate": 74.0,
                                "live_price": 74.0,
                                "currency": "USD",
                                "price_basis": "per_person",
                                "is_estimate_only": False,
                                "deeplink": "https://www.viator.com/tours/test/98765P2",
                                "image_url": "https://example.com/usat.jpg",
                            },
                        }
                    ],
                }
            ],
        }

        restored = restore_agent_state(serialize_agent_state(original))

        tile = restored["tiles"]["activities"][0]
        assert tile["provider"] == "viator"
        assert tile["partner"] == "viator"
        assert tile["source"] == "live"
        assert tile["source_agent"] == "vertical_specialist"
        assert tile["live_price"] == 74.0
        assert tile["is_estimate_only"] is False
        assert tile["meta"]["viator_product_code"] == "98765P2"

        booked_tile = restored["day_cards"][0]["blocks"][0]["booked_tile"]
        assert booked_tile["provider"] == "viator"
        assert booked_tile["partner"] == "viator"
        assert booked_tile["source"] == "live"
        assert booked_tile["source_agent"] == "vertical_specialist"
        assert booked_tile["live_price"] == 74.0
        assert booked_tile["is_estimate_only"] is False

    def test_browseable_activities_contract_fields_survive_roundtrip(self):
        """Persistent browse tiles must keep the core frontend contract fields."""
        original = {
            "messages": [],
            "persistent_meta": {
                "browseable_activities": [
                    {
                        "id": "browse_viator_1",
                        "type": "activity",
                        "partner": "viator",
                        "provider": "viator",
                        "partner_product_id": "98765P2",
                        "source": "live",
                        "source_agent": "logistics_node",
                        "title": "USAT Liberty Shipwreck Shore Dive",
                        "category": "diving",
                        "price_estimate": 74.0,
                        "live_price": 74.0,
                        "currency": "USD",
                        "price_basis": "per_person",
                        "rating": 4.8,
                        "review_count": 120,
                        "image_url": "https://example.com/usat.jpg",
                        "geo": {"lat": -8.28, "lng": 115.59},
                        "deeplink": "https://www.viator.com/tours/test/98765P2",
                        "browse_category": "activities",
                        "is_estimate_only": False,
                        "discard_me": "trimmed",
                    }
                ]
            },
        }

        restored = restore_agent_state(serialize_agent_state(original))
        browse_tile = restored["persistent_meta"]["browseable_activities"][0]

        assert browse_tile["type"] == "activity"
        assert browse_tile["partner_product_id"] == "98765P2"
        assert browse_tile["currency"] == "USD"
        assert browse_tile["price_basis"] == "per_person"
        assert browse_tile["rating"] == 4.8
        assert browse_tile["review_count"] == 120
        assert browse_tile["partner"] == "viator"
        assert browse_tile["provider"] == "viator"
        assert browse_tile["source"] == "live"
        assert browse_tile["source_agent"] == "logistics_node"
        assert browse_tile["is_estimate_only"] is False
        assert "discard_me" not in browse_tile

    def test_large_itinerary_is_trimmed_under_session_state_limit(self):
        """Oversized long-trip state should be trimmed below the request validator limit."""

        def build_tile(idx: int, *, tile_type: str = "activity") -> dict:
            return {
                "id": f"{tile_type}_{idx}",
                "type": tile_type,
                "title": f"Rome item {idx}",
                "partner": "viator" if tile_type == "activity" else "google_places_hotel",
                "provider": "viator" if tile_type == "activity" else "google_places",
                "partner_product_id": f"P-{idx}",
                "source": "live",
                "source_agent": "logistics_node",
                "category": "cultural",
                "price_estimate": 49.0 + idx,
                "live_price": 49.0 + idx,
                "currency": "USD",
                "price_basis": "per_person",
                "is_estimate_only": False,
                "deeplink": f"https://example.com/items/{idx}",
                "image_url": f"https://images.example.com/{idx}.jpg",
                "geo": {"lat": 41.9 + idx / 1000, "lng": 12.4 + idx / 1000},
                "rating": 4.7,
                "review_count": 100 + idx,
                "tags": ["activity", "rome"],
                "availability_status": "unknown",
                "meta": {
                    "duration_hours": 2.5,
                    "viator_product_code": f"V-{idx}",
                    "category": "cultural",
                },
            }

        activity_tiles = [build_tile(idx) for idx in range(40)]
        hotel_tiles = [build_tile(idx, tile_type="hotel") for idx in range(12)]
        day_cards = []
        for day_number in range(1, 29):
            blocks = [
                {
                    "id": f"block_{day_number}_am",
                    "period": "morning",
                    "activity_type": "experience",
                    "specialist_type": None,
                    "is_buffer": False,
                    "buffer_type": None,
                    "summary": f"Morning plan {day_number}",
                    "booked_tile": activity_tiles[(day_number - 1) % len(activity_tiles)],
                },
                {
                    "id": f"block_{day_number}_pm",
                    "period": "afternoon",
                    "activity_type": "experience",
                    "specialist_type": None,
                    "is_buffer": False,
                    "buffer_type": None,
                    "summary": f"Afternoon plan {day_number}",
                    "booked_tile": activity_tiles[day_number % len(activity_tiles)],
                },
                {
                    "id": f"block_{day_number}_eve",
                    "period": "evening",
                    "activity_type": "experience",
                    "specialist_type": None,
                    "is_buffer": False,
                    "buffer_type": None,
                    "summary": f"Evening plan {day_number}",
                    "booked_tile": activity_tiles[(day_number + 1) % len(activity_tiles)],
                },
            ]
            day_cards.append(
                {
                    "day_number": day_number,
                    "date": f"2030-03-{day_number:02d}",
                    "label": f"Day {day_number}",
                    "blocks": blocks,
                }
            )

        original = {
            "messages": [
                HumanMessage(content="Plan Rome"),
                AIMessage(content="Here is a plan"),
                HumanMessage(content="Extend it"),
                AIMessage(content="Extended"),
            ],
            "trip_plan": {
                "destination": "Rome",
                "start_date": "2030-03-01",
                "end_date": "2030-03-18",
            },
            "tiles": {"activities": activity_tiles, "hotels": hotel_tiles},
            "strategy_sections": [
                {
                    "id": "strategy_local_expert",
                    "specialist_type": "local_expert",
                    "title": "Rome Trip Overview",
                    "destination_gallery": [
                        {"label": f"gallery-{idx}", "image_url": f"https://gallery/{idx}.jpg"}
                        for idx in range(6)
                    ],
                    "vibe_trio": [
                        {"label": f"vibe-{idx}", "image_url": f"https://vibes/{idx}.jpg"}
                        for idx in range(3)
                    ],
                    "local_expert_enrichment": {"state": "pending"},
                }
            ],
            "day_cards": day_cards,
            "persistent_meta": {
                "plan_view_state": "S3_ITINERARY_READY",
                "browseable_activities": [build_tile(idx) for idx in range(30)],
            },
        }

        serialized = serialize_agent_state(original)
        raw_size = len(json.dumps(serialized, default=str))
        restored = restore_agent_state(serialized)
        from app.planner.coordinator import _build_envelope

        assert raw_size < 51200
        assert len(serialized["persistent_meta"]["browseable_activities"]) == 30
        assert len(restored["persistent_meta"]["browseable_activities"]) == 30
        assert "destination_gallery" not in serialized["strategy_sections"][0]
        assert serialized["day_cards"] == []
        assert len(serialized["tiles"]["activities"]) == len(activity_tiles)
        assert len(restored["tiles"]["activities"]) == len(activity_tiles)
        restored_tile = restored["tiles"]["activities"][0]
        assert restored_tile["image_url"].startswith("https://images.example.com/")
        assert restored_tile["geo"]["lat"] >= 41.9
        assert restored_tile["rating"] == 4.7
        restored["trip_plan"]["country_code"] = "IT"
        envelope = _build_envelope(restored, "What else should we do?", "test-session")
        assert len(envelope["document"]["browseable_activities"]) == 30

    def test_massive_tile_catalog_round_trips_via_compressed_session_state(self):
        """Huge tile catalogs should stay under 64KB without capping restored tiles."""

        def build_tile(idx: int, *, tile_type: str = "activity") -> dict:
            return {
                "id": f"{tile_type}_{idx}",
                "type": tile_type,
                "title": f"Rome item {idx}",
                "partner": "viator" if tile_type == "activity" else "google_places_hotel",
                "provider": "viator" if tile_type == "activity" else "google_places",
                "partner_product_id": f"P-{idx}",
                "source": "live",
                "source_agent": "logistics_node",
                "category": "cultural",
                "price_estimate": 49.0 + idx,
                "live_price": 49.0 + idx,
                "currency": "USD",
                "price_basis": "per_person",
                "is_estimate_only": False,
                "deeplink": f"https://example.com/items/{idx}",
                "image_url": f"https://images.example.com/{idx}.jpg",
                "geo": {"lat": 41.9 + idx / 1000, "lng": 12.4 + idx / 1000},
                "rating": 4.7,
                "review_count": 100 + idx,
                "tags": ["activity", "rome"],
                "availability_status": "unknown",
                "meta": {
                    "duration_hours": 2.5,
                    "viator_product_code": f"V-{idx}",
                    "category": "cultural",
                },
            }

        state = {
            "messages": [
                HumanMessage(content="Plan Rome"),
                AIMessage(content="Here is a plan"),
            ],
            "trip_plan": {
                "destination": "Rome",
                "start_date": "2030-03-01",
                "end_date": "2030-03-18",
            },
            "tiles": {
                "activities": [build_tile(idx) for idx in range(160)],
                "hotels": [build_tile(idx, tile_type="hotel") for idx in range(40)],
            },
            "strategy_sections": [{"id": "strategy_local_expert", "title": "Rome Trip Overview"}],
            "day_cards": [],
            "persistent_meta": {"plan_view_state": "S3_ITINERARY_READY"},
        }

        serialized = serialize_agent_state(state)
        restored = restore_agent_state(serialized)

        assert len(json.dumps(serialized, default=str)) < 65536
        assert serialized["tiles"] == {}
        assert isinstance(serialized["_compressed_tiles"], str)
        assert len(restored["tiles"]["activities"]) == 160
        restored_tile = restored["tiles"]["activities"][0]
        assert restored_tile["image_url"].startswith("https://images.example.com/")
        assert restored_tile["partner_product_id"] == "P-0"
        assert restored_tile["source_agent"] == "logistics_node"
        assert restored_tile["rating"] == 4.7

    def test_retained_day_cards_keep_booked_tile_restore_contract(self):
        """If day_cards survive budget trimming, booked tiles must keep restore-safe fields."""

        def build_tile(idx: int) -> dict:
            return {
                "id": f"activity_{idx}",
                "type": "activity",
                "title": f"Rome item {idx}",
                "partner": "viator",
                "provider": "viator",
                "partner_product_id": f"P-{idx}",
                "source": "live",
                "source_agent": "logistics_node",
                "category": "cultural",
                "price_estimate": 49.0 + idx,
                "live_price": 49.0 + idx,
                "currency": "USD",
                "price_basis": "per_person",
                "is_estimate_only": False,
                "deeplink": f"https://example.com/items/{idx}",
                "image_url": f"https://images.example.com/{idx}.jpg",
                "geo": {"lat": 41.9 + idx / 1000, "lng": 12.4 + idx / 1000},
                "rating": 4.7,
                "review_count": 100 + idx,
                "tags": ["activity", "rome"],
                "availability_status": "unknown",
                "meta": {
                    "duration_hours": 2.5,
                    "viator_product_code": f"V-{idx}",
                    "category": "cultural",
                },
            }

        long_blob = "x" * 1500
        activity_tiles = [build_tile(idx) for idx in range(25)]
        day_cards = []
        for day_number in range(1, 25):
            day_cards.append(
                {
                    "day_number": day_number,
                    "date": f"2030-03-{day_number:02d}",
                    "label": f"Day {day_number}",
                    "narrative": long_blob,
                    "blocks": [
                        {
                            "id": f"block_{day_number}_am",
                            "period": "morning",
                            "activity_type": "experience",
                            "specialist_type": None,
                            "is_buffer": False,
                            "buffer_type": None,
                            "summary": long_blob,
                            "notes": long_blob,
                            "booked_tile": activity_tiles[day_number % len(activity_tiles)],
                        },
                        {
                            "id": f"block_{day_number}_pm",
                            "period": "afternoon",
                            "activity_type": "experience",
                            "specialist_type": None,
                            "is_buffer": False,
                            "buffer_type": None,
                            "summary": long_blob,
                            "notes": long_blob,
                            "booked_tile": activity_tiles[(day_number + 1) % len(activity_tiles)],
                        },
                    ],
                }
            )

        serialized = serialize_agent_state(
            {
                "messages": [
                    HumanMessage(content="Plan Rome"),
                    AIMessage(content="Here is a plan"),
                ],
                "trip_plan": {
                    "destination": "Rome",
                    "start_date": "2030-03-01",
                    "end_date": "2030-03-24",
                },
                "tiles": {"activities": activity_tiles},
                "strategy_sections": [
                    {"id": "strategy_local_expert", "title": "Rome Trip Overview"}
                ],
                "day_cards": day_cards,
                "persistent_meta": {
                    "plan_view_state": "S3_ITINERARY_READY",
                    "browseable_activities": [build_tile(idx) for idx in range(5)],
                },
            }
        )

        assert len(json.dumps(serialized, default=str)) < 65536
        assert len(serialized["day_cards"]) == 24
        first_block = serialized["day_cards"][0]["blocks"][0]
        assert "summary" not in first_block
        booked_tile = first_block["booked_tile"]
        for key in (
            "partner",
            "partner_product_id",
            "source",
            "source_agent",
            "provider",
            "live_price",
            "price_basis",
            "is_estimate_only",
            "rating",
            "review_count",
        ):
            assert key in booked_tile

    def test_high_entropy_tile_catalog_uses_compacted_compressed_snapshot(self):
        """High-entropy tiles should trim below the soft budget and still restore."""

        def uniq(idx: int, prefix: str) -> str:
            return f"{prefix}-{idx:06d}-" + "".join(
                chr(33 + ((idx * 19 + shift) % 90)) for shift in range(400)
            )

        def build_tile(idx: int, *, tile_type: str = "activity") -> dict:
            return {
                "id": f"{tile_type}_{idx}",
                "type": tile_type,
                "title": uniq(idx, "title"),
                "partner": "viator" if tile_type == "activity" else "google_places_hotel",
                "provider": "viator" if tile_type == "activity" else "google_places",
                "partner_product_id": uniq(idx, "product"),
                "source": uniq(idx, "source"),
                "source_agent": uniq(idx, "agent"),
                "category": uniq(idx, "category"),
                "price_estimate": 49.0 + idx,
                "live_price": 49.0 + idx,
                "currency": "USD",
                "price_basis": uniq(idx, "basis"),
                "is_estimate_only": False,
                "deeplink": f"https://example.com/items/{idx}/" + uniq(idx, "deep"),
                "image_url": f"https://images.example.com/{idx}/" + uniq(idx, "img"),
                "geo": {"lat": 41.9 + idx / 1000, "lng": 12.4 + idx / 1000},
                "rating": 4.7,
                "review_count": 100 + idx,
                "tags": [uniq(idx, "tag1"), uniq(idx, "tag2"), uniq(idx, "tag3")],
                "availability_status": uniq(idx, "avail"),
                "meta": {
                    "duration_hours": 2.5,
                    "viator_product_code": uniq(idx, "vp"),
                    "category": uniq(idx, "meta-category"),
                    "is_backfill": False,
                    "notes": uniq(idx, "notes"),
                    "more": uniq(idx, "more"),
                },
            }

        serialized = serialize_agent_state(
            {
                "messages": [
                    HumanMessage(content="Plan Rome"),
                    AIMessage(content="Here is a plan"),
                ],
                "trip_plan": {"destination": "Rome"},
                "tiles": {
                    "activities": [build_tile(idx) for idx in range(400)],
                    "hotels": [build_tile(idx, tile_type="hotel") for idx in range(100)],
                },
                "strategy_sections": [
                    {"id": "strategy_local_expert", "title": "Rome Trip Overview"}
                ],
                "day_cards": [],
                "persistent_meta": {"plan_view_state": "S3_ITINERARY_READY"},
            }
        )
        restored = restore_agent_state(serialized)

        assert len(json.dumps(serialized, default=str)) < 51200
        assert isinstance(serialized["_compressed_tiles"], str)
        assert serialized["tiles"] == {}
        assert len(restored["tiles"]["activities"]) == 400
        restored_tile = restored["tiles"]["activities"][0]
        assert restored_tile["partner_product_id"].startswith("product-")
        assert "image_url" not in restored_tile
        assert "geo" not in restored_tile
        assert "tags" not in restored_tile
        assert "availability_status" not in restored_tile

    def test_soft_budget_compresses_tiles_below_threshold_and_restores(self):
        """Soft-budget states should serialize below 51.2KB and round-trip their tiles."""

        def build_tile(idx: int, *, tile_type: str = "activity") -> dict:
            return {
                "id": f"{tile_type}_{idx}",
                "type": tile_type,
                "title": f"Rome item {idx}",
                "partner": "viator" if tile_type == "activity" else "google_places_hotel",
                "provider": "viator" if tile_type == "activity" else "google_places",
                "partner_product_id": f"P-{idx}",
                "source": "live",
                "source_agent": "logistics_node",
                "category": "cultural",
                "price_estimate": 49.0 + idx,
                "live_price": 49.0 + idx,
                "currency": "USD",
                "price_basis": "per_person",
                "is_estimate_only": False,
                "deeplink": f"https://example.com/items/{idx}",
                "image_url": f"https://images.example.com/{idx}.jpg",
                "geo": {"lat": 41.9 + idx / 1000, "lng": 12.4 + idx / 1000},
                "rating": 4.7,
                "review_count": 100 + idx,
                "tags": ["activity", "rome"],
                "availability_status": "unknown",
                "meta": {
                    "duration_hours": 2.5,
                    "viator_product_code": f"V-{idx}",
                    "category": "cultural",
                },
            }

        state = {
            "messages": [
                HumanMessage(content="Plan Rome"),
                AIMessage(content="Here is a plan"),
            ],
            "trip_plan": {
                "destination": "Rome",
                "start_date": "2030-03-01",
                "end_date": "2030-03-18",
            },
            "tiles": {
                "activities": [build_tile(idx) for idx in range(160)],
                "hotels": [build_tile(idx, tile_type="hotel") for idx in range(40)],
            },
            "strategy_sections": [{"id": "strategy_local_expert", "title": "Rome Trip Overview"}],
            "day_cards": [],
            "persistent_meta": {"plan_view_state": "S3_ITINERARY_READY"},
        }

        serialized = serialize_agent_state(state)
        restored = restore_agent_state(serialized)

        assert len(json.dumps(serialized, default=str)) < 51200
        assert serialized["tiles"] == {}
        assert isinstance(serialized["_compressed_tiles"], str)
        assert len(restored["tiles"]["activities"]) == 160
        assert len(restored["tiles"]["hotels"]) == 40
        restored_tile = restored["tiles"]["activities"][0]
        assert restored_tile["partner"] == "viator"
        assert restored_tile["partner_product_id"] == "P-0"
        assert restored_tile["source_agent"] == "logistics_node"
        assert restored_tile["price_basis"] == "per_person"
        assert restored_tile["live_price"] == 49.0
        assert restored_tile["rating"] == 4.7

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
        assert serialized["specialist_plans"] == {
            "diving": {
                "topic": "diving",
                "feasibility_status": "feasible",
                "day_plans": [
                    {"day_number": 2, "location": "Tulamben"},
                    {"day_number": 3, "location": "Nusa Penida"},
                ],
                "constraints": [
                    {"constraint_id": "no_fly_24h", "reason": "24h no-fly buffer after diving"},
                ],
            },
            "hiking": {
                "topic": "hiking",
                "feasibility_status": "feasible",
                "day_plans": [{"day_number": 5, "location": "Kintamani"}],
                "constraints": [],
            },
        }

        restored = restore_agent_state(serialized)
        assert restored["specialist_plans"]["diving"]["topic"] == "diving"
        assert len(restored["specialist_plans"]["diving"]["day_plans"]) == 2
        assert restored["specialist_plans"]["hiking"]["topic"] == "hiking"
        assert "editorial" not in restored["specialist_plans"]["diving"]
        assert "confidence" not in restored["specialist_plans"]["hiking"]

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


def test_flow_23_infeasible_only_analysis_skips_day_fill_rate_failure() -> None:
    """Flow 23 should bypass day-fill-rate errors even with empty interior days."""

    sse_data = "data: " + json.dumps(
        {
            "type": "complete",
            "data": {
                "document": {
                    "day_cards": [
                        {
                            "day_number": 1,
                            "blocks": [{"booking_category": "arrival", "activity_type": "arrival"}],
                        },
                        {
                            "day_number": 2,
                            "blocks": [{"booking_category": "meal", "activity_type": "meal"}],
                        },
                        {
                            "day_number": 3,
                            "blocks": [{"booking_category": "meal", "activity_type": "meal"}],
                        },
                        {
                            "day_number": 4,
                            "blocks": [
                                {"booking_category": "departure", "activity_type": "departure"}
                            ],
                        },
                    ]
                },
                "session_state": {},
            },
        }
    )

    control = FlowReport(14, "control")
    check_day_fill_rate(sse_data, 14, control)
    assert control.errors
    assert "Day fill rate 0%" in control.errors[0]

    report = FlowReport(23, "Infeasible Activity - Skiing in Bali")
    check_day_fill_rate(sse_data, 23, report)

    assert report.errors == []
    assert "day_fill_rate" not in report.metrics
