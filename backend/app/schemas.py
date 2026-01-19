from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

TileType = Literal["flight", "hotel", "activity"]


# =============================================================================
# Error Record for structured error handling
# =============================================================================


class ErrorRecord(BaseModel):
    """
    Structured error record for consistent error handling across the graph.

    Used in GraphState.errors to replace string errors with machine-readable
    structured errors that support blocking error detection and routing decisions.
    """

    code: str  # Machine-readable error code (e.g., "DATE_AMBIGUOUS_YEAR", "LLM_FAILED")
    node: str  # Node name where error occurred
    severity: Literal["blocking", "warning", "info"] = "warning"
    message: str  # Human-readable error message


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


class DeleteLastMessageResponse(BaseModel):
    """Response from deleting the last user message and its assistant response."""

    deleted_count: int
    restored_trip_inputs: Optional[dict] = None
    messages: List[ChatMessageResponse]  # Remaining messages after deletion


TileProvider = Literal["expedia", "booking", "unknown"]


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
    currency: str = "USD"
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

    # Expedia Rapid API pricing fields for compliance
    total_inclusive: Optional[float] = None  # Total price including all taxes/fees
    tax_and_service_fee: Optional[float] = None  # Combined taxes and service fees
    property_fee: Optional[float] = None  # Property-collected fees
    is_refundable: Optional[bool] = None  # Whether booking is refundable
    cancel_policy_summary: Optional[str] = None  # Brief cancellation policy text
    provider: Optional[TileProvider] = "expedia"  # Default to Expedia for now


class TilesSearchRequest(BaseModel):
    branch_id: Optional[str] = None  # Now a string since branches are in JSON document
    session_id: Optional[str] = None
    trip_context_id: Optional[int] = None

    destination: Optional[str] = None
    destination_hint: Optional[str] = None
    origin: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    requires_assistance: Optional[bool] = None

    verticals: List[TileType] = Field(default_factory=lambda: ["hotel", "flight", "activity"])
    max_results_per_vertical: int = 5

    currency: str = "USD"
    response_mode: str = "estimate_first"

    # Budget constraints for filtering tiles
    budget: Optional[float] = None  # Total trip budget
    budget_per_category: Optional[float] = None  # Suggested allocation per category

    # User preference settings for filtering tiles
    # Accept both dict and model since TripInputs stores these as dicts
    flight_settings: Optional[Union["FlightSettings", Dict[str, Any]]] = None
    hotel_settings: Optional[Union["HotelSettings", Dict[str, Any]]] = None
    activity_settings: Optional[Union["ActivitySettings", Dict[str, Any]]] = None


class TilesSearchResponse(BaseModel):
    tiles_request_id: str
    tiles: List[Tile]
    summary: dict


class TileRefreshRequest(BaseModel):
    """Request to refresh tiles with current settings."""

    branch_id: str
    verticals: Optional[List[TileType]] = None  # None = refresh all verticals


class TileRefreshResponse(BaseModel):
    """Response from tile refresh."""

    tiles: List[Tile]
    refreshed_at: str
    verticals_refreshed: List[str]


class TileClickEvent(BaseModel):
    request_id: Optional[str] = None
    tile_id: str  # the tile identifier coming from the UI
    branch_id: Optional[str] = None  # now a string since branches are in JSON document


class SuggestionClickEvent(BaseModel):
    """Track when a user clicks a suggested response pill."""

    suggestion_text: str  # The text of the suggestion that was clicked
    suggestion_index: int  # Position in the list (0, 1, 2)
    request_id: Optional[str] = None


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
    ui_phase: Optional[Literal["bootstrap", "expanded"]] = None  # "chips-only" vs "full planner"
    suggestion_clicked: Optional[str] = None  # Text of clicked suggestion chip (enables LQA echo)


class GraphPlanRequest(BaseModel):
    """Request schema for graph-based planning entrypoint."""

    message: str
    trip_inputs: dict = Field(default_factory=dict)
    session_state: dict | None = None
    document_id: str | None = Field(
        default=None,
        description="Optional document ID for persistence and optimistic concurrency",
    )
    expected_version: int | None = Field(
        default=None,
        description="Expected document version for optimistic concurrency control",
    )
    thread_id: str | None = Field(
        default=None,
        description="Optional thread ID for conversation tracking",
    )
    reset: bool = Field(
        default=False,
        description=(
            "When true with empty session_state, "
            "generate new thread_id and optionally init from trip_inputs"
        ),
    )
    ui_phase: Optional[Literal["bootstrap", "expanded"]] = None  # "chips-only" vs "full planner"
    suggestion_clicked: Optional[str] = None  # Text of clicked suggestion chip (enables LQA echo)


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
    adults: Optional[int] = None
    children: Optional[int] = None
    requires_assistance: Optional[bool] = None
    budget: Optional[float] = None
    currency: str = "USD"
    is_primary: bool = False
    tiles: BranchTileIds = Field(default_factory=BranchTileIds)
    selections: BranchSelections = Field(default_factory=BranchSelections)
    # Dynamic images based on destination (from Unsplash)
    image_url: Optional[str] = None  # Primary branch card image
    hero_images: List[str] = Field(default_factory=list)  # Mood images for detail view
    # Strategy-enriched fields (populated by strategy nodes)
    vibe: Optional[str] = None  # Trip mood/theme e.g. "Coastal hikes + harbor nights"
    focus: Optional[str] = None  # Trip focus e.g. "Sea cliffs, seafood, slower mornings"
    highlights: List[str] = Field(default_factory=list)  # Key experiences (3-5 items)
    flow: List[str] = Field(default_factory=list)  # Day-by-day outline (3-5 items)
    notes: List[str] = Field(default_factory=list)  # Practical tips (3-4 items)


class DocumentTripInputsPatch(BaseModel):
    """Partial trip-input updates coming from the UI or planner merges."""

    destinations: Optional[List[str]] = None
    origin: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    requires_assistance: Optional[bool] = None
    budget: Optional[float] = None
    currency: Optional[str] = None
    missing_fields: Optional[List[str]] = None
    multi_city_intent: Optional[Literal["multi_city", "separate"]] = None
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
    skill_level: Optional[str] = None  # "beginner", "intermediate", "advanced"


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
    adults: Optional[int] = None
    children: Optional[int] = None
    requires_assistance: Optional[bool] = None
    budget: Optional[float] = None
    currency: str = "USD"
    missing_fields: List[str] = Field(default_factory=list)
    # Multi-city intent: "multi_city" = one itinerary visiting all destinations
    # "separate" = generate separate branch options for each destination
    # null = not yet clarified (will be asked if 2+ destinations)
    multi_city_intent: Optional[Literal["multi_city", "separate"]] = None
    # Booking preferences - what to search for and category-specific settings
    booking_types: BookingTypes = Field(default_factory=BookingTypes)
    flight_settings: FlightSettings = Field(default_factory=FlightSettings)
    hotel_settings: HotelSettings = Field(default_factory=HotelSettings)
    activity_settings: ActivitySettings = Field(default_factory=ActivitySettings)
    transport_settings: TransportSettings = Field(default_factory=TransportSettings)


# =============================================================================
# Plan State Envelope Types (for unified frontend state)
# =============================================================================

# Backend-authoritative plan state - frontend must NOT infer from other fields
PlanState = Literal["INCOMPLETE", "RESOLVING", "STABLE", "LOCKED"]

# UI phase - chips-only bootstrap vs full planner
UIPhase = Literal["bootstrap", "expanded"]

# Resolver steps - fixed order, exactly one active at a time
ResolverStep = Literal["processing_constraints", "matching_inventory", "updating_itinerary"]

# Readiness keys - fixed set for constraint completeness
ReadinessKey = Literal["origin", "destination", "start_date", "end_date", "travelers", "budget"]

# Booking status states per tab
BookingState = Literal["idle", "loading", "ready", "error"]


class ReadinessItem(BaseModel):
    """Single readiness constraint status."""

    key: ReadinessKey
    ok: bool


class ResolverState(BaseModel):
    """Resolver progress for RESOLVING state."""

    active_step: ResolverStep
    completed_steps: List[ResolverStep] = Field(default_factory=list)


class DestinationCard(BaseModel):
    """Destination content anchor for the plan."""

    title: str  # e.g. "Rome"
    subtitle: Optional[str] = None  # e.g. "Your adventure in Rome"
    image_url: Optional[str] = None  # Placeholder OK


class BookingStatusItem(BaseModel):
    """Status for a single booking category."""

    state: BookingState
    summary: str  # Short factual string, no tone, no emoji


class BookingStatus(BaseModel):
    """Per-tab booking status."""

    flights: Optional[BookingStatusItem] = None
    stays: Optional[BookingStatusItem] = None
    activities: Optional[BookingStatusItem] = None


# =============================================================================
# Change Tracking Types (for UI receipts)
# =============================================================================

# Canonical UI keys - locked set for type safety
CanonicalUIKey = Literal["origin", "destination", "dates", "travelers", "budget"]

# Conflict codes - locked enum, frontend renders deterministic copy
ConflictCode = Literal[
    "date_range_invalid",
    "date_past",
    "budget_exceeded",
    "traveler_mismatch",
    "destination_unreachable",
    "duration_mismatch",
]


class Conflict(BaseModel):
    """Structured conflict for UI rendering (no freeform text)."""

    scope: CanonicalUIKey  # Typed, not str
    related_constraints: List[CanonicalUIKey]  # Typed, not List[str]
    code: ConflictCode


class PlanDocumentData(BaseModel):
    """
    The JSON structure stored in plan_documents.document column.
    This is the source of truth for the planning session.
    """

    trip_context_id: Optional[int] = None
    trip_inputs: DocumentTripInputs = Field(default_factory=DocumentTripInputs)
    branches: List[DocumentBranch] = Field(default_factory=list)
    tiles: Dict[str, Tile] = Field(default_factory=dict)  # tile_id -> Tile
    # Chat fields (populated when returning from /v1/graph_plan, not persisted)
    assistant_message: Optional[str] = None
    assistant_message_id: Optional[str] = None
    # Ready to generate flag - when all fields are complete but user hasn't clicked generate yet
    ready_to_generate: bool = False
    # Suggested user responses for quick replies (1-3 contextual suggestions)
    suggested_responses: List[str] = Field(default_factory=list)
    # Change tracking for UI receipts
    applied_updates: List[CanonicalUIKey] = Field(default_factory=list)  # Typed keys only
    conflicts: List[Conflict] = Field(default_factory=list)
    undo_snapshot: Optional[Dict[str, Any]] = (
        None  # Previous trip_inputs for rollback (whitelisted fields)
    )
    update_provenance: Optional[Literal["lqa", "extractor", "user_edit"]] = None  # Debugging aid

    # ==========================================================================
    # Plan State Envelope - unified frontend state (populated at response time)
    # ==========================================================================
    # Backend-authoritative state - frontend must NOT infer from other fields
    plan_state: PlanState = "INCOMPLETE"
    # UI phase - chips-only bootstrap vs full planner
    ui_phase: UIPhase = "bootstrap"
    # Resolver progress (present ONLY when plan_state = "RESOLVING")
    resolver: Optional[ResolverState] = None
    # Constraint completeness for diagnostic panel
    readiness: List[ReadinessItem] = Field(default_factory=list)
    # Destination content anchor
    destination_card: Optional[DestinationCard] = None
    # Per-tab booking status (factual, no tone, no emoji)
    booking_status: Optional[BookingStatus] = None


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
    """Request to validate a trip input (origin or destination)."""

    field_type: Literal["origin", "destination"]
    value: str


class TripInputValidationResponse(BaseModel):
    """Response from trip input validation."""

    corrected_values: List[str]  # List to support multi-destination splitting
    is_valid: bool
    reason: Optional[str] = None


# =============================================================================
# Gate Trace Debug Endpoint (P2)
# =============================================================================


class GateTraceRequest(BaseModel):
    """P2: Request for gate trace debug endpoint.

    Used to debug gate evaluation without executing the full graph.
    Provides visibility into which gates fire and why for a given state.
    """

    user_text: str
    trip_inputs: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    turn_number: int = 0


# =============================================================================
# Graph Plan Types - LangGraph-based planning route
# =============================================================================


class GraphPlanErrorCode(str):
    """Stable error codes for /v1/graph_plan responses."""

    DATE_AMBIGUOUS = "DATE_AMBIGUOUS"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    MODULE_DISABLED = "MODULE_DISABLED"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_JSON_INVALID = "PROVIDER_JSON_INVALID"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    ROUTE_DISABLED = "ROUTE_DISABLED"
    INVALID_THREAD_ID = "INVALID_THREAD_ID"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_ERROR = "LLM_ERROR"


class GraphPlanTokens(BaseModel):
    """Token usage for observability."""

    prompt: int = 0
    completion: int = 0
    total: int = 0


class EntityConfidenceInfo(BaseModel):
    """Confidence information for a single extracted entity (e.g., destination)."""

    value: str
    confidence: float = Field(ge=0.0, le=1.0)
    needs_confirmation: bool = False
    fuzzy_suggestion: Optional[str] = None
    ambiguity_type: Optional[str] = None  # "name_person", "multiple_places", etc.


class ExtractionConfidenceInfo(BaseModel):
    """Overall extraction confidence for the current request."""

    overall: float = Field(ge=0.0, le=1.0, default=1.0)
    level: str = "high"  # "high", "medium", "low"
    destinations: List[EntityConfidenceInfo] = Field(default_factory=list)
    origin: Optional[EntityConfidenceInfo] = None
    detected_language: Optional[str] = None
    is_english: bool = True
    typo_suggestions: List[str] = Field(default_factory=list)


class GraphPlanObservability(BaseModel):
    """Minimal observability data for /v1/graph_plan responses."""

    tokens: GraphPlanTokens = Field(default_factory=GraphPlanTokens)
    model_used: Optional[str] = None
    router_intent: Optional[str] = None
    strategy_topic: Optional[str] = None
    today_iso: Optional[str] = None
    ready_to_generate_prev: bool = False
    ready_to_generate_now: bool = False
    extraction_confidence: Optional[ExtractionConfidenceInfo] = None

    # Short-circuit and routing metrics
    short_circuit_type: Optional[str] = None  # greeting, acknowledgment, confirmation_yes, etc.
    llm_calls_made: int = 0  # Count of LLM calls in this request
    cache_hits: int = 0  # Response cache hits
    confidence_routing: Optional[str] = None  # high_bypass, medium_llm, low_force_llm


class GraphPlanResponse(BaseModel):
    """Response from /v1/graph_plan endpoint."""

    # Core document fields
    document: PlanDocumentData
    session_state: Dict[str, Any]
    version: int
    updated_by: UpdatedBy
    updated_at: str
    changes_made: bool = False

    # Request tracking
    request_id: str

    # Observability (optional, all fields have defaults)
    observability: Optional[GraphPlanObservability] = None
