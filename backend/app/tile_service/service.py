import os
import uuid
from typing import List

from app.schemas import (
    Tile,
    TilesSearchRequest,
    TilesSearchResponse,
)

from .mock_provider import (
    MockActivityProvider,
    MockFlightProvider,
    MockHotelProvider,
)
from .models import SearchContext
from .provider_base import Provider

_DEBUG_LOG = bool(os.getenv("DEBUG_PLAN_MESSAGES"))


def _build_search_context(req: TilesSearchRequest) -> SearchContext:
    """
    Map the public API request into an internal SearchContext.
    This is where you normalize / pre-process API input.
    """
    return SearchContext(
        destination=req.destination or req.destination_hint,
        origin=req.origin,
        start_date=req.start_date,
        end_date=req.end_date,
        adults=req.adults,
        children=req.children,
        requires_assistance=req.requires_assistance,
        verticals=req.verticals or [],
        max_results_per_vertical=req.max_results_per_vertical,
        currency=req.currency,
        response_mode=req.response_mode,
        budget=req.budget,
        budget_per_category=req.budget_per_category,
    )


def _get_providers(ctx: SearchContext) -> List[Provider]:
    """
    Decide which providers to call based on the context.
    For now, always return the mock provider.
    Later, you can:
    - Route based on verticals (e.g. hotel vs flight)
    - Route based on region or partner preferences
    - Read from config / env
    """
    providers: List[Provider] = []

    # Example: only attach providers if their vertical was requested
    if "hotel" in ctx.verticals or not ctx.verticals:
        providers.append(MockHotelProvider())
    if "flight" in ctx.verticals or not ctx.verticals:
        providers.append(MockFlightProvider())
    if "activity" in ctx.verticals or not ctx.verticals:
        providers.append(MockActivityProvider())

    return providers


def search_tiles(req: TilesSearchRequest) -> TilesSearchResponse:
    """
    Public entry point used by FastAPI.
    - Builds internal SearchContext
    - Routes to provider(s)
    - Merges results
    - Computes a summary
    """
    ctx = _build_search_context(req)
    providers = _get_providers(ctx)

    all_tiles: List[Tile] = []

    for provider in providers:
        try:
            tiles = provider.search(ctx)
        except Exception as exc:
            if _DEBUG_LOG:
                print(f"Provider {provider.name} failed: {exc}")
            continue

        all_tiles.extend(tiles)

    request_id = uuid.uuid4().hex

    summary = {
        "verticals_returned": sorted({t.type for t in all_tiles}),
        "min_price_estimate": min(
            (t.price_estimate for t in all_tiles if t.price_estimate is not None),
            default=None,
        ),
        "max_price_estimate": max(
            (t.price_estimate for t in all_tiles if t.price_estimate is not None),
            default=None,
        ),
        "response_mode": ctx.response_mode,
        "origin": ctx.origin,
        "start_date": ctx.start_date,
        "end_date": ctx.end_date,
        "adults": ctx.adults,
        "children": ctx.children,
        "requires_assistance": ctx.requires_assistance,
        "currency": ctx.currency,
    }

    return TilesSearchResponse(
        tiles_request_id=request_id,
        tiles=all_tiles,
        summary=summary,
    )
