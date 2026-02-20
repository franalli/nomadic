from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from app.schemas import (
    ActivitySettings,
    FlightSettings,
    HotelSettings,
    TileType,
)


class SearchContext(BaseModel):
    """
    Internal representation of a tile search.
    You can extend this later with more fields (e.g. date flexibility,
    normalized budget, etc.) without changing the public API.
    """

    destination: Optional[str] = None
    origin: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    requires_assistance: Optional[bool] = None

    verticals: List[TileType] = Field(default_factory=list)
    max_results_per_vertical: int = 5

    currency: str = "USD"
    response_mode: Optional[str] = None

    # Pre-resolved IATA codes (from iata_resolver in planner graph).
    # Used by Amadeus providers; falls back to hardcoded lookup if absent.
    origin_iata: Optional[str] = None
    destination_iata: Optional[str] = None

    # Destination geo coordinates for locationBias (populated by logistics_node geocoder)
    destination_lat: Optional[float] = None
    destination_lng: Optional[float] = None

    # Budget constraints for filtering tiles
    budget: Optional[float] = None  # Total trip budget
    budget_per_category: Optional[float] = None  # Suggested allocation per category

    # User preference settings for filtering tiles
    # Accept both dict and model since TripInputs stores these as dicts
    flight_settings: Optional[Union[FlightSettings, Dict[str, Any]]] = None
    hotel_settings: Optional[Union[HotelSettings, Dict[str, Any]]] = None
    activity_settings: Optional[Union[ActivitySettings, Dict[str, Any]]] = None
