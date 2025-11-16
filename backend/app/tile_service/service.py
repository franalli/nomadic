import uuid
from typing import List

from app.schemas import (
    Tile,
    TilesSearchRequest,
    TilesSearchResponse,
)

from .mock_provider import MockHotelProvider
from .models import SearchContext
from .provider_base import Provider


def _build_search_context(req: TilesSearchRequest) -> SearchContext:
    """
    Map the public API request into an internal SearchContext.
    This is where you normalize / pre-process API input.
    """
    return SearchContext(
        origin=req.origin,
        destination=req.destination,
        trip_type=req.trip_type,
        start_date=req.start_date,
        end_date=req.end_date,
        budget_bucket=req.budget_bucket,
        group_size=req.group_size,
        vibes=req.vibes or [],
        verticals=req.verticals or [],
        max_results_per_vertical=req.max_results_per_vertical,
        currency=req.currency,
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

    # Example: only attach hotel provider if hotels requested
    if "hotel" in ctx.verticals or not ctx.verticals:
        providers.append(MockHotelProvider())

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
            # For now just log/print; later replace with proper logging
            # and maybe partial failure handling.
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
    }

    return TilesSearchResponse(request_id=request_id, tiles=all_tiles, summary=summary)
