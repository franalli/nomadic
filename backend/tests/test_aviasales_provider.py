"""Tests for the Aviasales flight provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import app.services.aviasales_provider as avp
from app.services.aviasales_provider import _api_result_to_tile, search_aviasales_flights


@pytest.fixture(autouse=True)
def _reset_aviasales_state() -> None:
    """Reset module-level client state between tests."""
    avp._aviasales_client = None
    yield
    avp._aviasales_client = None


@pytest.mark.asyncio
async def test_grouped_prices_deeplink_uses_requested_plan_dates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fallback grouped-price results should still book against the plan dates."""
    monkeypatch.setattr(avp.settings, "aviasales_enabled", True)
    monkeypatch.setattr(avp.settings, "aviasales_api_token", "test-token")
    monkeypatch.setattr(avp.settings, "aviasales_marker", "")

    grouped_result = [
        {
            "price": 199,
            "airline": "AZ",
            "flight_number": "611",
            "departure_at": "2026-04-05T07:30:00+00:00",
            "return_at": "2026-04-12T20:45:00+00:00",
            "transfers": 0,
            "duration_to": 155,
        }
    ]

    with (
        patch(
            "app.services.aviasales_provider._search_prices_for_dates",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.aviasales_provider._search_grouped_prices",
            new=AsyncMock(return_value=grouped_result),
        ),
    ):
        tiles = await search_aviasales_flights(
            origin="AMS",
            destination="FCO",
            depart_date="2026-04-07",
            return_date="2026-04-14",
            currency="usd",
        )

    assert len(tiles) == 1
    assert tiles[0]["deeplink"] == "https://www.aviasales.com/search/AMS0704FCO14041"
    assert tiles[0]["deeplink_url"] == "https://www.aviasales.com/search/AMS0704FCO14041"
    assert tiles[0]["is_estimate_only"] is True
    assert tiles[0]["subtitle"] == "Price based on nearby dates"
    assert tiles[0]["meta"]["departure_time"] == "2026-04-05T07:30:00+00:00"


@pytest.mark.asyncio
async def test_exact_date_results_keep_precise_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exact-date Aviasales results should remain non-estimate tiles."""
    monkeypatch.setattr(avp.settings, "aviasales_enabled", True)
    monkeypatch.setattr(avp.settings, "aviasales_api_token", "test-token")
    monkeypatch.setattr(avp.settings, "aviasales_marker", "")

    exact_result = [
        {
            "price": 249,
            "airline": "AZ",
            "flight_number": "611",
            "departure_at": "2026-04-07T07:30:00+00:00",
            "return_at": "2026-04-14T20:45:00+00:00",
            "transfers": 0,
            "duration_to": 155,
        }
    ]

    with patch(
        "app.services.aviasales_provider._search_prices_for_dates",
        new=AsyncMock(return_value=exact_result),
    ):
        tiles = await search_aviasales_flights(
            origin="AMS",
            destination="FCO",
            depart_date="2026-04-07",
            return_date="2026-04-14",
            currency="usd",
        )

    assert len(tiles) == 1
    assert tiles[0]["deeplink"] == "https://www.aviasales.com/search/AMS0704FCO14041"
    assert tiles[0]["is_estimate_only"] is False
    assert tiles[0]["subtitle"] == "Departs 07:30 \u2022 2h 35m"


@pytest.mark.asyncio
async def test_duplicate_provider_results_are_deduped_to_unique_tiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Duplicate Aviasales rows should collapse to one logical flight tile."""
    monkeypatch.setattr(avp.settings, "aviasales_enabled", True)
    monkeypatch.setattr(avp.settings, "aviasales_api_token", "test-token")
    monkeypatch.setattr(avp.settings, "aviasales_marker", "")

    duplicate = {
        "price": 249,
        "airline": "AZ",
        "flight_number": "611",
        "departure_at": "2026-04-07T07:30:00+00:00",
        "return_at": "2026-04-14T20:45:00+00:00",
        "transfers": 0,
        "duration_to": 155,
    }
    unique = {
        "price": 289,
        "airline": "KL",
        "flight_number": "1601",
        "departure_at": "2026-04-07T10:30:00+00:00",
        "return_at": "2026-04-14T18:45:00+00:00",
        "transfers": 1,
        "duration_to": 205,
    }

    with patch(
        "app.services.aviasales_provider._search_prices_for_dates",
        new=AsyncMock(return_value=[duplicate, duplicate.copy(), unique]),
    ):
        tiles = await search_aviasales_flights(
            origin="AMS",
            destination="FCO",
            depart_date="2026-04-07",
            return_date="2026-04-14",
            currency="usd",
        )

    assert len(tiles) == 2
    assert len({tile["id"] for tile in tiles}) == 2
    assert len({tile["partner_product_id"] for tile in tiles}) == 2


def test_tile_identity_is_stable_for_same_logical_flight() -> None:
    """Stable IDs must not depend on provider list index or duplicate count."""
    flight = {
        "price": 249,
        "airline": "AZ",
        "flight_number": "611",
        "departure_at": "2026-04-07T07:30:00+00:00",
        "return_at": "2026-04-14T20:45:00+00:00",
        "transfers": 0,
        "duration_to": 155,
    }

    first = _api_result_to_tile(
        flight,
        origin="AMS",
        destination="FCO",
        currency="usd",
        requested_depart_date="2026-04-07",
        requested_return_date="2026-04-14",
    )
    second = _api_result_to_tile(
        dict(flight),
        origin="AMS",
        destination="FCO",
        currency="usd",
        requested_depart_date="2026-04-07",
        requested_return_date="2026-04-14",
    )

    assert first is not None
    assert second is not None
    assert first["id"] == second["id"]
    assert first["partner_product_id"] == second["partner_product_id"]
