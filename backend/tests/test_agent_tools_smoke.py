"""
Smoke tests for create_agent planner tools.

Verifies the two representative tools are ``ainvoke``-testable and return
plain dicts:

- ``extract_trip_fields`` -- LLM-backed; the inner ``_classify_and_extract_with_llm``
  is mocked so the test is deterministic and offline.
- ``build_itinerary`` -- pure Python scheduling; invoked with stub tiles.

``@tool``-decorated functions are invoked via ``.ainvoke({...})`` with a dict of
args (the InjectedState param is omitted -- it is auto-populated only inside a
running create_agent graph).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.planner.tools.build_itinerary import build_itinerary
from app.planner.tools.extract_trip_fields import extract_trip_fields


async def test_extract_trip_fields_returns_dict() -> None:
    """extract_trip_fields returns a serializable dict (LLM mocked)."""
    from app.planner.nodes.router_extraction import RouterOutput

    mock_output = RouterOutput(
        intent="PLANNING",
        confidence=0.9,
        reasoning="smoke test",
        destination="Tokyo",
        start_date="2026-09-01",
        end_date="2026-09-07",
    )

    with patch(
        "app.planner.nodes.router_extraction._classify_and_extract_with_llm",
        new=AsyncMock(return_value=(mock_output, {})),
    ):
        result = await extract_trip_fields.ainvoke(
            {"user_message": "Plan a trip to Tokyo Sep 1-7 2026"}
        )

    assert isinstance(result, dict)
    assert result["intent"] == "PLANNING"
    assert result["destination"] == "Tokyo"
    # fields_changed must be populated against the (empty) current state.
    assert isinstance(result["fields_changed"], list)
    assert "destination" in result["fields_changed"]


async def test_build_itinerary_returns_dict() -> None:
    """build_itinerary returns a serializable dict from stub tiles (pure Python)."""
    tiles_json = (
        '{"activities": [{"id": "a1", "title": "City Walk", '
        '"subtitle": "Explore downtown", "meta": {"duration_hours": 3.0}}]}'
    )

    result = await build_itinerary.ainvoke(
        {
            "destination": "Tokyo",
            "start_date": "2026-09-01",
            "end_date": "2026-09-03",
            "tiles_json": tiles_json,
        }
    )

    assert isinstance(result, dict)
    assert "success" in result
    assert "day_cards" in result
    assert "conflicts" in result
    assert "activities_placed" in result
    assert isinstance(result["day_cards"], list)


async def test_build_itinerary_missing_fields_returns_error_dict() -> None:
    """build_itinerary returns a structured error dict when required fields are absent."""
    result = await build_itinerary.ainvoke({"destination": "Tokyo"})

    assert isinstance(result, dict)
    assert result["success"] is False
    assert result["error"]
