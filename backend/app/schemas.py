from typing import List, Optional, Literal
from pydantic import BaseModel, Field

TileType = Literal["flight", "hotel", "activity"]
AvailabilityStatus = Literal["available", "low", "unknown", "not_available"]


class Geo(BaseModel):
    lat: float
    lon: float


class Tile(BaseModel):
    id: str
    type: TileType
    partner: str
    partner_product_id: str

    title: str
    subtitle: Optional[str] = None
    image_url: Optional[str] = None

    price_estimate: Optional[float] = None
    live_price: Optional[float] = None
    currency: str = "EUR"
    price_basis: str = "per_trip"
    is_estimate_only: bool = True

    deeplink_url: str

    rating: Optional[float] = None
    review_count: Optional[int] = None

    location_label: Optional[str] = None
    geo: Optional[Geo] = None

    tags: List[str] = Field(default_factory=list)
    availability_status: AvailabilityStatus = "unknown"

    meta: dict = Field(default_factory=dict)
    score: Optional[float] = None
    source: Optional[str] = None  # "cache" | "live"


class TilesSearchRequest(BaseModel):
    user_id: Optional[str] = None
    branch_id: Optional[str] = None

    origin: Optional[str] = None
    destination: Optional[str] = None
    trip_type: Optional[str] = "round_trip"
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    budget_bucket: Optional[str] = None
    group_size: Optional[int] = 2
    vibes: List[str] = Field(default_factory=list)

    verticals: List[TileType] = Field(default_factory=lambda: ["hotel"])
    max_results_per_vertical: int = 5

    currency: str = "EUR"
    response_mode: str = "estimate_first"


class TilesSearchResponse(BaseModel):
    request_id: str
    tiles: List[Tile]
    summary: dict
