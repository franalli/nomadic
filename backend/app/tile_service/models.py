from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas import TileType  # reuse your existing Tile model


class SearchContext(BaseModel):
    """
    Internal representation of a tile search.
    You can extend this later with more fields (e.g. date flexibility,
    normalized budget, etc.) without changing the public API.
    """

    destination: Optional[str] = None

    verticals: List[TileType] = Field(default_factory=list)
    max_results_per_vertical: int = 5

    currency: str = "EUR"
    response_mode: Optional[str] = None
