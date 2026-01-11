from typing import List, Optional

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

    # Budget constraints for filtering tiles
    budget: Optional[float] = None  # Total trip budget
    budget_per_category: Optional[float] = None  # Suggested allocation per category

    # User preference settings for filtering tiles
    flight_settings: Optional[FlightSettings] = None
    hotel_settings: Optional[HotelSettings] = None
    activity_settings: Optional[ActivitySettings] = None
