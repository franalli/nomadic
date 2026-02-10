"""
TileService Tool - Fetches travel inventory (flights, hotels, activities).

This tool is called by the Trip Architect to get real/mock travel options.
It wraps the existing tile_service infrastructure and adds:
- City validation before API calls
- Image fallback via Unsplash
- Constraint filtering from Specialist nodes

Key Principle: "Flights/Hotels are NOT Agents - they are data fetchers."
"""

from typing import Any, Dict, List, Literal, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.schemas import (
    ActivitySettings,
    FlightSettings,
    HotelSettings,
    Tile,
    TilesSearchRequest,
    TileType,
)
from app.tile_service.service import search_tiles
from app.validation import validate_input_async


class TileSearchInput(BaseModel):
    """Input schema for the fetch_travel_tiles tool."""

    category: Literal["flights", "hotels", "activities"] = Field(
        description="The type of travel inventory to fetch"
    )
    location: str = Field(description="The destination city/location (e.g., 'Bali', 'Paris')")
    start_date: str = Field(description="Trip start date in ISO format (e.g., '2024-03-15')")
    end_date: Optional[str] = Field(
        default=None, description="Trip end date in ISO format (e.g., '2024-03-20')"
    )
    origin: Optional[str] = Field(
        default=None, description="Origin city for flights (required for flight searches)"
    )
    adults: int = Field(default=1, description="Number of adult travelers")
    children: int = Field(default=0, description="Number of child travelers")
    budget: Optional[float] = Field(default=None, description="Maximum budget for this category")
    constraints: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Additional constraints from Specialist (e.g., {'min_24h_buffer_after_dive': True})"
        ),
    )
    # Category-specific settings
    flight_settings: Optional[Dict[str, Any]] = Field(
        default=None, description="Flight preferences: cabin_class, direct_only, round_trip"
    )
    hotel_settings: Optional[Dict[str, Any]] = Field(
        default=None, description="Hotel preferences: min_stars, amenities"
    )
    activity_settings: Optional[Dict[str, Any]] = Field(
        default=None, description="Activity preferences: categories, skill_level"
    )


class TileSearchOutput(BaseModel):
    """Output schema for the fetch_travel_tiles tool."""

    success: bool
    tiles: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None
    location_validated: Optional[str] = None
    tile_count: int = 0
    summary: Optional[Dict[str, Any]] = None
    # Constraint engine results - blocked tiles for UI display
    blocked_tiles: List[Dict[str, Any]] = Field(default_factory=list)
    blocked_summary: Optional[Dict[str, Any]] = None


def _map_category_to_vertical(category: str) -> TileType:
    """Map tool category to internal TileType."""
    mapping = {
        "flights": "flight",
        "hotels": "hotel",
        "activities": "activity",
    }
    return mapping.get(category, category)


async def _validate_location(
    location: str, field_type: str = "destination"
) -> tuple[bool, str, Optional[str]]:
    """
    Validate location using existing validation.py logic.

    Returns:
        (is_valid, validated_name, error_message)
    """
    try:
        result = await validate_input_async(location, field_type)
        if result.is_valid and result.corrected_values:
            # Use first corrected value
            return True, result.corrected_values[0], None
        else:
            reason = result.reason or f"Unknown location: {location}"
            return False, location, reason
    except Exception:
        # Fallback: accept location as-is if validation fails
        return True, location, None


def _apply_specialist_constraints(
    tiles: List[Tile],
    constraints: Optional[Dict[str, Any]],
    category: str,
) -> tuple[List[Tile], List[Tile], Optional[Dict[str, Any]]]:
    """
    Apply constraints from Vertical Specialist to filter tiles.

    Uses the ConstraintEngine for DETERMINISTIC filtering (no LLM).

    Example constraints:
    - {"min_24h_buffer_after_dive": True, "last_dive_time": "..."} -> Filter flights
    - {"advanced_cert_required": True} -> Filter activities needing certification

    Returns:
        Tuple of (safe_tiles, blocked_tiles, blocked_summary)
    """
    if not constraints:
        return tiles, [], None

    from datetime import datetime

    from app.tools.constraint_engine import ConstraintEngine

    engine = ConstraintEngine()
    safe_tiles = list(tiles)
    blocked_tiles: List[Tile] = []
    blocked_summary = None

    # Diving constraint: 24h no-fly rule
    if constraints.get("min_24h_buffer_after_dive") and category == "flights":
        last_dive_time = constraints.get("last_dive_time")
        if last_dive_time:
            # Parse datetime if string
            if isinstance(last_dive_time, str):
                try:
                    last_dive_time = datetime.fromisoformat(last_dive_time.replace("Z", "+00:00"))
                except ValueError:
                    last_dive_time = None

            if last_dive_time:
                # Convert tiles to dicts for constraint engine
                tile_dicts = [t.model_dump() for t in safe_tiles]

                safe_dicts, blocked_dicts = engine.filter_flights_by_diving_constraint(
                    flights=tile_dicts,
                    last_dive_time=last_dive_time,
                    multi_dive_day=constraints.get("multi_dive_day", True),
                )

                # Convert back to Tile objects
                safe_tiles = [Tile(**d) for d in safe_dicts]
                blocked_tiles = [Tile(**d) for d in blocked_dicts]

                if blocked_tiles:
                    suffix = "s" if len(blocked_tiles) != 1 else ""
                    blocked_summary = {
                        "count": len(blocked_tiles),
                        "reason": "Departure within 24h of last dive",
                        "constraint": "min_24h_buffer_after_dive",
                        "icon": "",
                        "message": f"{len(blocked_tiles)} flight option{suffix} removed",
                    }

    # Advanced certification constraint for activities
    if constraints.get("advanced_cert_required") and category == "activities":
        filtered = []
        for tile in safe_tiles:
            skill_level = tile.meta.get("skill_level") if tile.meta else None
            if skill_level and skill_level != "advanced":
                blocked_tiles.append(tile)
                continue
            filtered.append(tile)
        safe_tiles = filtered

        if blocked_tiles and not blocked_summary:
            blocked_summary = {
                "count": len(blocked_tiles),
                "reason": "Requires advanced certification",
                "constraint": "advanced_cert_required",
            }

    return safe_tiles, blocked_tiles, blocked_summary


@tool("fetch_travel_tiles", args_schema=TileSearchInput)
async def fetch_travel_tiles(
    category: str,
    location: str,
    start_date: str,
    end_date: Optional[str] = None,
    origin: Optional[str] = None,
    adults: int = 1,
    children: int = 0,
    budget: Optional[float] = None,
    constraints: Optional[Dict[str, Any]] = None,
    flight_settings: Optional[Dict[str, Any]] = None,
    hotel_settings: Optional[Dict[str, Any]] = None,
    activity_settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Fetch travel options (flights, hotels, activities) from providers.

    Use this tool when:
    - Building a trip plan and need real inventory options
    - User asks for specific prices or availability
    - Comparing options across providers

    DO NOT use this tool:
    - Before you have destination AND dates
    - For general trip inspiration (use your knowledge instead)

    Args:
        category: Type of inventory ("flights", "hotels", "activities")
        location: Destination city (will be validated)
        start_date: Trip start date (ISO format)
        end_date: Trip end date (optional, ISO format)
        origin: Origin city (required for flights)
        adults: Number of adults (default: 1)
        children: Number of children (default: 0)
        budget: Maximum budget for this category
        constraints: Specialist-injected constraints (e.g., diving surface interval)
        flight_settings: Flight preferences (cabin_class, direct_only, round_trip)
        hotel_settings: Hotel preferences (min_stars, amenities)
        activity_settings: Activity preferences (categories, skill_level)

    Returns:
        Dict with: success, tiles, error, location_validated, tile_count, summary
    """
    # 1. Validate destination
    is_valid, validated_location, error = await _validate_location(location, "destination")
    if not is_valid:
        return TileSearchOutput(
            success=False,
            error=f"Invalid destination: {error}",
            location_validated=None,
        ).model_dump()

    # 2. Validate origin for flights
    validated_origin = origin
    if category == "flights":
        if not origin:
            return TileSearchOutput(
                success=False,
                error="Origin is required for flight searches",
                location_validated=validated_location,
            ).model_dump()
        is_valid_origin, validated_origin, origin_error = await _validate_location(origin, "origin")
        if not is_valid_origin:
            return TileSearchOutput(
                success=False,
                error=f"Invalid origin: {origin_error}",
                location_validated=validated_location,
            ).model_dump()

    # 3. Build search request
    vertical = _map_category_to_vertical(category)
    request = TilesSearchRequest(
        destination=validated_location,
        origin=validated_origin,
        start_date=start_date,
        end_date=end_date,
        adults=adults,
        children=children,
        verticals=[vertical],
        budget=budget,
        currency="USD",
        response_mode="estimate_first",
        flight_settings=FlightSettings(**flight_settings) if flight_settings else None,
        hotel_settings=HotelSettings(**hotel_settings) if hotel_settings else None,
        activity_settings=ActivitySettings(**activity_settings) if activity_settings else None,
    )

    # 4. Call existing tile service
    try:
        response = search_tiles(request)
    except Exception as e:
        return TileSearchOutput(
            success=False,
            error=f"Tile search failed: {str(e)}",
            location_validated=validated_location,
        ).model_dump()

    # 5. Apply specialist constraints (DETERMINISTIC - no LLM)
    safe_tiles, blocked_tiles, blocked_summary = _apply_specialist_constraints(
        response.tiles,
        constraints,
        category,
    )

    # 6. Convert tiles to dicts for JSON serialization
    tiles_data = [tile.model_dump() for tile in safe_tiles]
    blocked_data = [tile.model_dump() for tile in blocked_tiles]

    return TileSearchOutput(
        success=True,
        tiles=tiles_data,
        location_validated=validated_location,
        tile_count=len(tiles_data),
        summary=response.summary,
        blocked_tiles=blocked_data,
        blocked_summary=blocked_summary,
    ).model_dump()
