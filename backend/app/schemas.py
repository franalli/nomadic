from typing import List, Literal, Optional

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
    branch_id: Optional[int] = None
    session_id: Optional[str] = None
    trip_context_id: Optional[int] = None

    origin: Optional[str] = None
    destination: Optional[str] = None
    destination_hint: Optional[str] = None
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
    tiles_request_id: str
    request_id: Optional[str] = None
    tiles: List[Tile]
    summary: dict


class TileClickEvent(BaseModel):
    request_id: Optional[str] = None
    tile_id: str  # the tile identifier coming from the UI
    user_id: Optional[str] = None  # optional, for later
    branch_id: Optional[int] = None  # can be None if not using branches yet
    session_id: Optional[str] = None  # your frontend-generated session id


class PlanRequest(BaseModel):
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    message: str

    origin: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    budget_bucket: Optional[str] = None
    group_size: Optional[int] = None
    vibes: List[str] = Field(default_factory=list)


class PlanBranch(BaseModel):
    id: str
    label: str
    description: str
    destination: str


class PlanResponse(BaseModel):
    trip_context_id: Optional[int] = None
    branches: List[PlanBranch]
    tiles: List[Tile]  # tiles for the primary branch
    primary_branch_id: Optional[str] = None
    tiles_request_id: Optional[str] = None
    tiles_summary: Optional[dict] = None


class SessionTripContext(BaseModel):
    id: int
    origin: Optional[str] = None
    destination_hint: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    budget_bucket: Optional[str] = None
    group_size: Optional[int] = None
    vibes: List[str] = Field(default_factory=list)
    raw_prompt: Optional[str] = None


class SessionStateResponse(BaseModel):
    session_id: str
    session_exists: bool = False
    trip_context: Optional[SessionTripContext] = None
    branches: List[PlanBranch] = Field(default_factory=list)
    primary_branch_id: Optional[str] = None
    tiles: List[Tile] = Field(default_factory=list)
    tiles_request_id: Optional[str] = None
