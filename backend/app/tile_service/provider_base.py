from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from app.schemas import Tile

from .models import SearchContext


class Provider(ABC):
    """
    Base class for tile providers (Booking.com, Expedia, etc.).
    Each provider implements `search` and returns normalized Tiles.
    """

    name: str

    @abstractmethod
    def search(self, ctx: SearchContext) -> List[Tile]:
        """
        Perform a search for tiles based on the given context.
        Implementations should:
        - Call their underlying API / data source
        - Map results into Tile objects
        - Not worry about global ranking/merging
        """
        ...
