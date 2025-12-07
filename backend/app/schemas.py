from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

TileType = Literal["flight", "hotel", "activity"]
AvailabilityStatus = Literal["available", "low", "unknown", "not_available"]
UpdatedBy = Literal["user", "planner"]
ChatRole = Literal["user", "assistant"]


class Geo(BaseModel):
    lat: float
    lon: float


# =============================================================================
# Chat Messages
# =============================================================================


class ChatMessageResponse(BaseModel):
    """A single chat message for the frontend."""

    model_config = ConfigDict(from_attributes=True)

    id: str  # String ID for frontend compatibility
    role: ChatRole
    content: str
    created_at: str  # ISO timestamp


class ChatHistoryResponse(BaseModel):
    """Response containing chat history for a session."""

    messages: List[ChatMessageResponse]


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


class TileClickEvent(BaseModel):
    request_id: Optional[str] = None
    tile_id: str  # the tile identifier coming from the UI
    branch_id: Optional[str] = None  # now a string since branches are in JSON document


class PlanRequest(BaseModel):
    """Request to send a chat message to the planner.

    Note: Trip inputs are read from the PlanDocument (single source of truth).
    The frontend should NOT send trip_inputs directly - all state flows through
    the document.

    Note: session_id is no longer in the request body - it comes from the
    HttpOnly session cookie, injected by SessionMiddleware.
    """

    message: str  # The user's chat message
    timezone: Optional[str] = None  # IANA timezone (e.g., "Europe/Rome") for "today" calculation


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
    destinations: List[str] = Field(default_factory=list)
    origin: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    traveler_count: Optional[int] = None
    budget: Optional[int] = None
    is_primary: bool = False
    tiles: BranchTileIds = Field(default_factory=BranchTileIds)
    selections: BranchSelections = Field(default_factory=BranchSelections)


class DocumentTripInputsPatch(BaseModel):
    """Partial trip-input updates coming from the UI or planner merges."""

    destinations: Optional[List[str]] = None
    origin: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    traveler_count: Optional[int] = None
    budget: Optional[int] = None
    missing_fields: Optional[List[str]] = None
    multi_city_intent: Optional[Literal["multi_city", "separate"]] = None
    vibes: Optional[List[str]] = None
    booking_types: Optional["BookingTypes"] = None
    flight_settings: Optional["FlightSettings"] = None
    hotel_settings: Optional["HotelSettings"] = None
    activity_settings: Optional["ActivitySettings"] = None


class BookingTypes(BaseModel):
    """Which booking categories to search for."""

    hotels: bool = False
    flights: bool = False
    ground_transport: bool = False
    activities: bool = False


class FlightSettings(BaseModel):
    """Flight-specific search settings."""

    round_trip: bool = True
    cabin_class: Literal["economy", "premium_economy", "business", "first"] = "economy"
    direct_only: bool = False


class HotelSettings(BaseModel):
    """Hotel-specific search settings."""

    min_stars: int = Field(default=0, ge=0, le=5)  # 0 = no minimum
    amenities: List[str] = Field(default_factory=list)


class ActivitySettings(BaseModel):
    """Activity-specific search settings."""

    categories: List[str] = Field(default_factory=list)  # empty = all categories
    max_duration_hours: Optional[int] = None  # null = no limit


class TransportSettings(BaseModel):
    """Ground transport settings - which modes to include."""

    car: bool = False
    train: bool = False
    bus: bool = False


class DocumentTripInputs(BaseModel):
    """Trip parameters extracted/inferred from conversation."""

    destinations: List[str] = Field(default_factory=list)
    origin: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    traveler_count: Optional[int] = None
    budget: Optional[int] = None
    missing_fields: List[str] = Field(default_factory=list)
    # Multi-city intent: "multi_city" = one itinerary visiting all destinations
    # "separate" = generate separate branch options for each destination
    # null = not yet clarified (will be asked if 2+ destinations)
    multi_city_intent: Optional[Literal["multi_city", "separate"]] = None
    # Vibes: trip purposes/themes like "F1", "Backpacking", "Adventure", etc.
    # Open-ended list that LLM will validate/normalize to actual activities or purposes
    vibes: List[str] = Field(default_factory=list)
    # Booking preferences - what to search for and category-specific settings
    booking_types: BookingTypes = Field(default_factory=BookingTypes)
    flight_settings: FlightSettings = Field(default_factory=FlightSettings)
    hotel_settings: HotelSettings = Field(default_factory=HotelSettings)
    activity_settings: ActivitySettings = Field(default_factory=ActivitySettings)
    transport_settings: TransportSettings = Field(default_factory=TransportSettings)


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
    # Ready to generate flag - when all fields are complete but user hasn't clicked generate yet
    ready_to_generate: bool = False


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
    trip_inputs: Optional[DocumentTripInputsPatch | DocumentTripInputs] = None


# =============================================================================
# Trip Input Validation
# =============================================================================


class TripInputValidationRequest(BaseModel):
    """Request to validate a trip input (origin, destination, or vibe)."""

    field_type: Literal["origin", "destination", "vibe"]
    value: str


class TripInputValidationResponse(BaseModel):
    """Response from trip input validation."""

    corrected_values: List[str]  # List to support multi-destination splitting
    is_valid: bool
    reason: Optional[str] = None
