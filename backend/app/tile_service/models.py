from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas import TileType  # reuse your existing Tile model


class SearchContext(BaseModel):
    """
    Internal representation of a tile search.
    You can extend this later with more fields (e.g. date flexibility,
    normalized budget, etc.) without changing the public API.
    """

    origin: Optional[str] = None
    destination: Optional[str] = None
    trip_type: Optional[str] = "round_trip"
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    budget_bucket: Optional[str] = None
    group_size: Optional[int] = 2
    vibes: List[str] = Field(default_factory=list)

    verticals: List[TileType] = Field(default_factory=list)
    max_results_per_vertical: int = 5

    currency: str = "EUR"
