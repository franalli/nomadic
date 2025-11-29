from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field

TileType = Literal["flight", "hotel", "activity"]
AvailabilityStatus = Literal["available", "low", "unknown", "not_available"]
UpdatedBy = Literal["user", "planner"]


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
    branch_id: Optional[str] = None  # Now a string since branches are in JSON document
    session_id: Optional[str] = None
    trip_context_id: Optional[int] = None

    destination: Optional[str] = None
    destination_hint: Optional[str] = None
    origin: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    traveler_count: Optional[int] = None

    verticals: List[TileType] = Field(default_factory=lambda: ["hotel", "flight", "activity"])
    max_results_per_vertical: int = 5

    currency: str = "EUR"
    response_mode: str = "estimate_first"


class TilesSearchResponse(BaseModel):
    tiles_request_id: str
    tiles: List[Tile]
    summary: dict

    @computed_field
    @property
    def request_id(self) -> str:
        return self.tiles_request_id


class TileClickEvent(BaseModel):
    request_id: Optional[str] = None
    tile_id: str  # the tile identifier coming from the UI
    branch_id: Optional[str] = None  # now a string since branches are in JSON document
    user_id: Optional[str] = None
    session_id: Optional[str] = None


class TripInputs(BaseModel):
    """Trip parameters stored in chat message metadata."""

    destination: Optional[str] = None
    destinations: List[str] = Field(default_factory=list)
    origin: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    traveler_count: Optional[int] = None
    budget: Optional[int] = None
    missing_fields: List[str] = Field(default_factory=list)


class PlanRequest(BaseModel):
    """Request to send a chat message to the planner.

    All trip state (inputs, branches, tiles, selections) is read from
    the centralized PlanDocument. The frontend should PATCH /v1/document
    to update trip inputs before sending chat messages.
    """

    session_id: str  # Required - identifies the planning session
    message: str  # The user's chat message


# ─────────────────────────────────────────────────────────────────────────────
# Plan Document: Centralized JSON state for branches & tiles
# ─────────────────────────────────────────────────────────────────────────────


class BranchTileIds(BaseModel):
    """Tile IDs grouped by vertical for a branch."""

    stays: List[str] = Field(default_factory=list)
    flights: List[str] = Field(default_factory=list)
    activities: List[str] = Field(default_factory=list)


class BranchSelections(BaseModel):
    """User's selected tile IDs for booking within a branch."""

    stay: Optional[str] = None
    flight: Optional[str] = None
    activities: List[str] = Field(default_factory=list)


class DocumentBranch(BaseModel):
    """A branch within the plan document."""

    id: str
    label: str
    description: str
    destination: str
    destinations: List[str] = Field(default_factory=list)
    origin: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    traveler_count: Optional[int] = None
    budget: Optional[int] = None
    is_primary: bool = False
    tiles: BranchTileIds = Field(default_factory=BranchTileIds)
    selections: BranchSelections = Field(default_factory=BranchSelections)


class DocumentTripInputs(BaseModel):
    """Trip parameters extracted/inferred from conversation."""

    destination: Optional[str] = None
    destinations: List[str] = Field(default_factory=list)
    origin: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    traveler_count: Optional[int] = None
    budget: Optional[int] = None
    missing_fields: List[str] = Field(default_factory=list)


class PlanDocumentData(BaseModel):
    """
    The JSON structure stored in plan_documents.document column.
    This is the source of truth for the planning session.
    """

    trip_context_id: Optional[int] = None
    trip_inputs: DocumentTripInputs = Field(default_factory=DocumentTripInputs)
    branches: List[DocumentBranch] = Field(default_factory=list)
    tiles: Dict[str, Tile] = Field(default_factory=dict)  # tile_id -> Tile
    # Chat fields (populated when returning from /v1/plan, not persisted)
    assistant_message: Optional[str] = None
    assistant_message_id: Optional[str] = None


class PlanDocument(BaseModel):
    """Full plan document including metadata."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    version: int
    updated_by: UpdatedBy
    document: PlanDocumentData
    created_at: str
    updated_at: str


class PlanDocumentResponse(BaseModel):
    """Response when fetching the plan document."""

    version: int
    updated_by: UpdatedBy
    document: PlanDocumentData
    updated_at: str
    changes_made: bool = False  # Whether this request modified the document


class PlanDocumentPatch(BaseModel):
    """
    Partial update to the plan document from the user.
    Uses CRDT-style merge: additions win, deletions require explicit flags.
    """

    version: int  # Client's current version for optimistic locking hint
    # Branches to add or update (merged by id)
    branches: Optional[List[DocumentBranch]] = None
    # Branch IDs to remove
    remove_branch_ids: Optional[List[str]] = None
    # Tiles to add or update (merged by id)
    tiles: Optional[Dict[str, Tile]] = None
    # Tile IDs to remove
    remove_tile_ids: Optional[List[str]] = None
    # Selection updates per branch
    selections: Optional[Dict[str, BranchSelections]] = None
    # Trip inputs to merge
    trip_inputs: Optional[DocumentTripInputs] = None
