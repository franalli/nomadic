"""
Aviasales / Travelpayouts flight search provider.

Searches real-time flight prices via the Travelpayouts Data API and returns
tile-compatible dicts ready for state.tiles["flights"].

API docs: https://support.travelpayouts.com/hc/en-us/articles/203956163

Graceful degradation: returns empty list on any failure.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# -- Constants ----------------------------------------------------------------
TRAVELPAYOUTS_BASE = "https://api.travelpayouts.com/aviasales/v3"
AVIASALES_TIMEOUT = 10.0  # seconds
_MAX_PROVIDER_RESULTS = 10
_MAX_TILE_RESULTS = 5
_FLEX_WINDOW_DAYS = 3  # ±3 days for date flex suggestions


@dataclass
class FlightSearchResult:
    """Flight tiles plus optional nearby-date pricing for flex suggestions."""

    tiles: list[dict[str, Any]] = dc_field(default_factory=list)
    nearby_prices: dict[str, float] = dc_field(default_factory=dict)
    requested_date_price: float | None = None
    cheapest_date: str | None = None
    cheapest_price: float | None = None


# -- Singleton httpx client ---------------------------------------------------
_aviasales_client: httpx.AsyncClient | None = None
_aviasales_client_lock = asyncio.Lock()


async def _get_client() -> httpx.AsyncClient:
    """Return a shared httpx client, creating lazily if needed."""
    global _aviasales_client
    if _aviasales_client is not None and not _aviasales_client.is_closed:
        return _aviasales_client
    async with _aviasales_client_lock:
        if _aviasales_client is None or _aviasales_client.is_closed:
            _aviasales_client = httpx.AsyncClient(timeout=AVIASALES_TIMEOUT)
        return _aviasales_client


async def close_aviasales_http_client() -> None:
    """Close the shared httpx client (call during app shutdown)."""
    global _aviasales_client
    if _aviasales_client and not _aviasales_client.is_closed:
        await _aviasales_client.aclose()
        _aviasales_client = None


# -- Deeplink builder ---------------------------------------------------------


def _build_deeplink(
    origin: str,
    destination: str,
    depart_date: str | datetime,
    return_date: str | datetime = "",
) -> str:
    """Build an Aviasales affiliate search deeplink.

    Format: https://www.aviasales.com/search/{ORIGIN}{DDMM}{DEST}{DDMM}1?marker={marker}
    One-way: https://www.aviasales.com/search/{ORIGIN}{DDMM}{DEST}1?marker={marker}
    """
    marker = settings.aviasales_marker

    def _to_ddmm(d: str | datetime) -> str:
        if isinstance(d, datetime):
            return d.strftime("%d%m")
        # Parse YYYY-MM-DD or ISO datetime string
        try:
            dt = datetime.strptime(d[:10], "%Y-%m-%d")
            return dt.strftime("%d%m")
        except (ValueError, TypeError):
            return ""

    dep_ddmm = _to_ddmm(depart_date)
    if not dep_ddmm:
        return f"https://www.aviasales.com/search/{origin}{destination}1"

    ret_ddmm = _to_ddmm(return_date) if return_date else ""

    if ret_ddmm:
        path = f"{origin}{dep_ddmm}{destination}{ret_ddmm}1"
    else:
        path = f"{origin}{dep_ddmm}{destination}1"

    url = f"https://www.aviasales.com/search/{path}"
    if marker:
        url += f"?marker={marker}"
    return url


# -- Main search function -----------------------------------------------------


async def search_aviasales_flights(
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str = "",
    currency: str = "usd",
) -> FlightSearchResult:
    """Search Aviasales for flights and return tiles plus optional flex data.

    Tries prices_for_dates first, falls back to grouped_prices calendar API.
    When grouped_prices is used, preserves nearby-date pricing for flex suggestions.
    """
    empty = FlightSearchResult()

    if not settings.aviasales_enabled or not settings.aviasales_api_token:
        return empty

    if not origin or not destination or not depart_date:
        logger.debug(
            "[Aviasales] Missing required params: origin=%s dest=%s date=%s",
            origin,
            destination,
            depart_date,
        )
        return empty

    token = settings.aviasales_api_token

    # 1. Try prices_for_dates (specific date search)
    results = await _search_prices_for_dates(
        origin, destination, depart_date, return_date, token, currency
    )

    # 2. Fallback to grouped_prices (calendar month search)
    nearby_prices: dict[str, float] = {}
    if not results:
        logger.debug("[Aviasales] No results from prices_for_dates, trying grouped_prices")
        results, nearby_prices = await _search_grouped_prices(
            origin, destination, depart_date, token, currency
        )

    if not results:
        logger.info(
            "[Aviasales] No flights found for %s -> %s on %s", origin, destination, depart_date
        )
        return empty

    unique_results = _dedupe_flight_results(results, origin, destination)

    # Convert API results to tile-compatible dicts
    tiles = []
    for flight in unique_results[:_MAX_TILE_RESULTS]:
        tile = _api_result_to_tile(
            flight,
            origin,
            destination,
            currency,
            requested_depart_date=depart_date,
            requested_return_date=return_date,
        )
        if tile:
            tiles.append(tile)

    logger.info("[Aviasales] Found %d flights for %s -> %s", len(tiles), origin, destination)

    # Compute flex summary from calendar data (±3 day window)
    requested_day = depart_date[:10]
    requested_price = nearby_prices.get(requested_day)
    cheapest_date: str | None = None
    cheapest_price: float | None = None
    if nearby_prices:
        try:
            req_dt = datetime.strptime(requested_day, "%Y-%m-%d")
            window: dict[str, float] = {}
            for delta in range(-_FLEX_WINDOW_DAYS, _FLEX_WINDOW_DAYS + 1):
                check = (req_dt + timedelta(days=delta)).strftime("%Y-%m-%d")
                if check in nearby_prices:
                    window[check] = nearby_prices[check]
            if window:
                cheapest_date = min(window, key=window.get)  # type: ignore[arg-type]  # dict.get is valid key func
                cheapest_price = window[cheapest_date]
        except ValueError:
            pass

    # nearby_prices contains the full month from grouped_prices;
    # cheapest_date/cheapest_price are pre-filtered to the ±3 day window.
    # The consumer (logistics_node) further trims nearby_prices to ±3 days for payload size.
    return FlightSearchResult(
        tiles=tiles,
        nearby_prices=nearby_prices,
        requested_date_price=requested_price,
        cheapest_date=cheapest_date,
        cheapest_price=cheapest_price,
    )


# -- API call helpers ----------------------------------------------------------


async def _search_prices_for_dates(
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str,
    token: str,
    currency: str,
) -> list[dict[str, Any]]:
    """Call prices_for_dates API for specific date flight prices."""
    params: dict[str, Any] = {
        "origin": origin,
        "destination": destination,
        "departure_at": depart_date[:10],  # YYYY-MM-DD
        "token": token,
        "sorting": "price",
        "direct": "false",
        "limit": _MAX_PROVIDER_RESULTS,
        "currency": currency,
    }
    if return_date:
        params["return_at"] = return_date[:10]

    try:
        client = await _get_client()
        resp = await client.get(
            f"{TRAVELPAYOUTS_BASE}/prices_for_dates",
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success"):
            logger.debug("[Aviasales] prices_for_dates returned success=false")
            return []

        return data.get("data", [])

    except httpx.TimeoutException:
        logger.warning("[Aviasales] prices_for_dates timed out for %s->%s", origin, destination)
        return []
    except httpx.HTTPStatusError as e:
        logger.warning(
            "[Aviasales] prices_for_dates HTTP %d for %s->%s",
            e.response.status_code,
            origin,
            destination,
        )
        return []
    except Exception as e:
        logger.warning("[Aviasales] prices_for_dates error: %s", e)
        return []


async def _search_grouped_prices(
    origin: str,
    destination: str,
    depart_date: str,
    token: str,
    currency: str,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    """Call grouped_prices API as fallback (month-level calendar search).

    Returns (results_list, date_price_map). The date_price_map preserves the
    raw date→price dict for flex suggestions before collapsing to a list.
    """
    # Extract YYYY-MM from the date
    month_str = depart_date[:7]  # YYYY-MM

    params: dict[str, Any] = {
        "origin": origin,
        "destination": destination,
        "departure_at": month_str,
        "token": token,
        "group_by": "departure_at",
        "currency": currency,
    }

    try:
        client = await _get_client()
        resp = await client.get(
            f"{TRAVELPAYOUTS_BASE}/grouped_prices",
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success"):
            logger.debug("[Aviasales] grouped_prices returned success=false")
            return [], {}

        # grouped_prices returns {data: {"2026-04-01": {...}, "2026-04-02": {...}}}
        raw = data.get("data", {})
        if isinstance(raw, dict):
            # Preserve date→price map for flex suggestions
            date_prices: dict[str, float] = {
                date_key: entry.get("price", 0)
                for date_key, entry in raw.items()
                if isinstance(entry, dict) and entry.get("price")
            }
            # Convert dict-of-dates to list, sorted by price
            results = list(raw.values())
            results.sort(key=lambda x: x.get("price", float("inf")))
            return results[:_MAX_PROVIDER_RESULTS], date_prices
        elif isinstance(raw, list):
            return raw[:_MAX_PROVIDER_RESULTS], {}
        return [], {}

    except httpx.TimeoutException:
        logger.warning("[Aviasales] grouped_prices timed out for %s->%s", origin, destination)
        return [], {}
    except httpx.HTTPStatusError as e:
        logger.warning(
            "[Aviasales] grouped_prices HTTP %d for %s->%s",
            e.response.status_code,
            origin,
            destination,
        )
        return [], {}
    except Exception as e:
        logger.warning("[Aviasales] grouped_prices error: %s", e)
        return [], {}


# -- Tile conversion -----------------------------------------------------------


def _api_result_to_tile(
    flight: dict[str, Any],
    origin: str,
    destination: str,
    currency: str,
    requested_depart_date: str = "",
    requested_return_date: str = "",
) -> dict[str, Any] | None:
    """Convert a Travelpayouts API flight result to a tile-compatible dict."""
    try:
        price = flight.get("price")
        if price is None:
            return None

        airline_code = flight.get("airline", "")
        departure_at = flight.get("departure_at", "")
        transfers = flight.get("transfers", 0)
        duration_to = flight.get("duration_to", 0)  # minutes
        return_at = flight.get("return_at", "")

        # Resolve carrier name from CARRIER_MAP or use airline code
        from app.data.demo_curation import CARRIER_MAP

        carrier_info = CARRIER_MAP.get(airline_code, {"name": airline_code, "logo": airline_code})
        carrier_name = carrier_info["name"]
        carrier_logo = carrier_info["logo"]

        is_direct = transfers == 0
        stops_label = "Direct" if is_direct else (f"{transfers} stop{'s' if transfers > 1 else ''}")

        # Format duration
        if duration_to and duration_to > 0:
            hours = duration_to // 60
            minutes = duration_to % 60
            duration_str = f"{hours}h {minutes}m" if minutes else f"{hours}h"
        else:
            duration_str = ""

        requested_depart_day = requested_depart_date[:10] if requested_depart_date else ""
        requested_return_day = requested_return_date[:10] if requested_return_date else ""
        provider_depart_day = departure_at[:10] if departure_at else ""
        provider_return_day = return_at[:10] if return_at else ""
        has_date_drift = (requested_depart_day and requested_depart_day != provider_depart_day) or (
            requested_return_day and requested_return_day != provider_return_day
        )

        # When grouped-price fallback drifts from the requested dates, avoid
        # presenting the provider's alternate-date itinerary details as exact.
        if has_date_drift:
            subtitle = "Price based on nearby dates"
        else:
            dep_time_display = ""
            if departure_at and "T" in departure_at:
                dep_time_display = departure_at.split("T")[1][:5]

            subtitle_parts = []
            if dep_time_display:
                subtitle_parts.append(f"Departs {dep_time_display}")
            if duration_str:
                subtitle_parts.append(duration_str)
            subtitle = " \u2022 ".join(subtitle_parts) if subtitle_parts else stops_label

        # Keep the outbound deeplink anchored to the plan's requested dates.
        deeplink = _build_deeplink(
            origin,
            destination,
            requested_depart_date or departure_at or "",
            requested_return_date or return_at or "",
        )

        flight_fingerprint = _flight_fingerprint(flight, origin, destination)
        tile_id = f"aviasales_{origin}_{destination}_{flight_fingerprint[:12]}"
        partner_product_id = f"aviasales_{flight_fingerprint}"

        logo_url = f"https://pics.avs.io/200/200/{carrier_logo}.png"

        return {
            "id": tile_id,
            "type": "flight",
            "partner": "aviasales",
            "title": f"{carrier_name} - {stops_label}",
            "subtitle": subtitle,
            "image_url": logo_url,
            "price_estimate": float(price),
            "currency": currency.upper(),
            "price_basis": "per_person",
            "is_estimate_only": has_date_drift,
            "deeplink": deeplink,
            "deeplink_url": deeplink,
            "tags": [carrier_name, stops_label.lower()],
            "availability_status": "available",
            "partner_product_id": partner_product_id,
            "meta": {
                "carrier_code": carrier_logo,
                "carrier_name": carrier_name,
                "departure_time": departure_at,
                "arrival_time": flight.get("arrival_at", ""),
                "duration": duration_str,
                "stops": transfers,
                "is_direct": is_direct,
            },
            "source": "aviasales",
            "source_agent": "logistics_node",
            "category": "flight",
        }

    except Exception as e:
        logger.warning("[Aviasales] Failed to convert flight result to tile: %s", e)
        return None


def _normalize_flight_field(value: Any) -> str:
    """Normalize provider values so identical itineraries hash identically."""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value).strip().lower()


def _flight_fingerprint(flight: dict[str, Any], origin: str, destination: str) -> str:
    """Build a stable logical identifier for an Aviasales itinerary."""
    fingerprint_fields = [
        origin,
        destination,
        flight.get("airline"),
        flight.get("flight_number"),
        flight.get("departure_at"),
        flight.get("arrival_at"),
        flight.get("return_at"),
        flight.get("transfers"),
        flight.get("return_transfers"),
        flight.get("duration_to"),
        flight.get("duration_back"),
        flight.get("origin_airport"),
        flight.get("destination_airport"),
    ]
    raw = "|".join(_normalize_flight_field(field) for field in fingerprint_fields)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _dedupe_flight_results(
    results: list[dict[str, Any]],
    origin: str,
    destination: str,
) -> list[dict[str, Any]]:
    """Collapse duplicate provider rows to one logical itinerary."""
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicates = 0

    for flight in results:
        fingerprint = _flight_fingerprint(flight, origin, destination)
        if fingerprint in seen:
            duplicates += 1
            continue
        seen.add(fingerprint)
        deduped.append(flight)

    if duplicates:
        logger.info("[Aviasales] Deduped %d duplicate flight result(s)", duplicates)

    return deduped
