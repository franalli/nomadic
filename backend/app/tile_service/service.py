import uuid
from typing import List

from app.config import settings
from app.debug_utils import _debug
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
        # Pass user preference settings for filtering
        flight_settings=req.flight_settings,
        hotel_settings=req.hotel_settings,
        activity_settings=req.activity_settings,
    )


def _get_providers(ctx: SearchContext) -> List[Provider]:
    """
    Decide which providers to call based on the context.

    Provider routing strategy (consistent with logistics_node):
    1. Google Places enabled → GooglePlacesProvider (real names + photos, overrides Amadeus)
    2. Amadeus enabled → AmadeusProvider for hotels (real names, placeholder images)
    3. Fallback → MockProviders

    @see docs/ux_unified_architecture.md Section XIII - Tile Provider Architecture
    """
    providers: List[Provider] = []

    # 1. GOOGLE PLACES FIRST - Real hotel and activity names with photos (overrides Amadeus)
    if settings.use_google_places_provider:
        _debug(f"[PROVIDER] Using GooglePlaces for hotels/activities: {ctx.destination}")
        from .google_places_provider import GooglePlacesActivityProvider, GooglePlacesHotelProvider

        if "hotel" in ctx.verticals or not ctx.verticals:
            providers.append(GooglePlacesHotelProvider())
        if "flight" in ctx.verticals or not ctx.verticals:
            providers.append(MockFlightProvider())
        if "activity" in ctx.verticals or not ctx.verticals:
            providers.append(GooglePlacesActivityProvider())
        return providers

    # 2. AMADEUS SECOND - Real hotel names with placeholder images
    if settings.use_amadeus_provider:
        _debug(f"[PROVIDER] Using Amadeus for hotels: {ctx.destination}")

        if "hotel" in ctx.verticals or not ctx.verticals:
            from .amadeus_provider import AmadeusHotelProvider

            providers.append(AmadeusHotelProvider())

        # Flights and activities use Mock (Amadeus flights disabled for consistency)
        if "flight" in ctx.verticals or not ctx.verticals:
            providers.append(MockFlightProvider())
        if "activity" in ctx.verticals or not ctx.verticals:
            providers.append(MockActivityProvider())

        return providers

    # 3. MOCK FALLBACK - Development/offline mode
    _debug(f"[PROVIDER] Using MockProviders for: {ctx.destination}")

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
            _debug(f"Provider {provider.name} failed: {exc}")
            continue

        all_tiles.extend(tiles)

    # If Google Places was used but returned no hotels/activities, fall back to mock
    if settings.use_google_places_provider:
        hotel_tiles = [t for t in all_tiles if t.type == "hotel"]
        activity_tiles = [t for t in all_tiles if t.type == "activity"]
        if not hotel_tiles and ("hotel" in ctx.verticals or not ctx.verticals):
            _debug("[PROVIDER] GooglePlaces returned 0 hotels — falling back to mock")
            all_tiles.extend(MockHotelProvider().search(ctx))
        if not activity_tiles and ("activity" in ctx.verticals or not ctx.verticals):
            _debug("[PROVIDER] GooglePlaces returned 0 activities — falling back to mock")
            all_tiles.extend(MockActivityProvider().search(ctx))

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
