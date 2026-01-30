from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

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

    # Agent provenance - which specialist agent produced this tile
    source_agent: Optional[str] = None  # "diving", "hiking", etc. - set at creation

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


# =============================================================================
# Expand Itinerary (Stage 3 Generation)
# =============================================================================


class ExpandItineraryRequest(BaseModel):
    """Request to expand strategy into full itinerary (Stage 2 -> Stage 3)."""

    idempotency_key: str = Field(
        description="Client-generated UUID to prevent duplicate generation"
    )
    # Optional document context - if provided, used to restore session state
    trip_inputs: Optional[Dict[str, Any]] = Field(
        default=None, description="Trip inputs from frontend document"
    )
    strategy_sections: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Strategy sections from frontend document"
    )
    tiles: Optional[Dict[str, Any]] = Field(
        default=None, description="Tiles from frontend document"
    )


class ExpandItineraryStreamEvent(BaseModel):
    """NDJSON streaming event for expand-itinerary endpoint."""

    type: Literal["progress", "envelope", "done", "error"]
    # Progress events
    stage: Optional[Literal["structure", "strategy", "itinerary"]] = None
    message: Optional[str] = None
    pct: Optional[int] = None
    # Envelope events - partial document update
    plan_envelope: Optional[Dict[str, Any]] = None
    # Done events
    plan_view_state: Optional[str] = None


class TileClickEvent(BaseModel):
    request_id: Optional[str] = None
    tile_id: str  # the tile identifier coming from the UI
    branch_id: Optional[str] = None  # now a string since branches are in JSON document


class SuggestionClickEvent(BaseModel):
    """Track when a user clicks a suggested response pill."""

    suggestion_text: str  # The text of the suggestion that was clicked
    suggestion_index: int  # Position in the list (0, 1, 2)
    request_id: Optional[str] = None


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
    destination: Optional[str] = None
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

    destination: Optional[str] = None
    origin: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    requires_assistance: Optional[bool] = None
    budget: Optional[float] = None
    currency: Optional[str] = None
    missing_fields: Optional[List[str]] = None
    booking_types: Optional["BookingTypes"] = None
    flight_settings: Optional["FlightSettings"] = None
    hotel_settings: Optional["HotelSettings"] = None
    activity_settings: Optional["ActivitySettings"] = None


# Tri-state booking type: off (user disabled), suggested (default/auto), on (user enabled)
BookingTypeState = Literal["off", "suggested", "on"]


class BookingTypes(BaseModel):
    """Which booking categories to search for.

    Uses tri-state model:
    - 'off': User explicitly disabled, never show or search
    - 'suggested': Default state, show provisional items
    - 'on': User explicitly enabled, may require confirmation gates
    """

    hotels: BookingTypeState = "suggested"
    flights: BookingTypeState = "off"  # Upgrades to 'suggested' when origin is set
    ground_transport: BookingTypeState = "off"
    activities: BookingTypeState = "suggested"

    @field_validator("*", mode="before")
    @classmethod
    def coerce_bool(cls, v):
        """Coerce legacy boolean values to tri-state strings."""
        if isinstance(v, bool):
            return "on" if v else "off"
        return v


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

    destination: Optional[str] = None
    origin: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    requires_assistance: Optional[bool] = None
    budget: Optional[float] = None
    currency: str = "USD"
    missing_fields: List[str] = Field(default_factory=list)
    # Booking preferences - what to search for and category-specific settings
    booking_types: BookingTypes = Field(default_factory=BookingTypes)
    flight_settings: FlightSettings = Field(default_factory=FlightSettings)
    hotel_settings: HotelSettings = Field(default_factory=HotelSettings)
    activity_settings: ActivitySettings = Field(default_factory=ActivitySettings)
    transport_settings: TransportSettings = Field(default_factory=TransportSettings)
    # Flexible dates support - exposed for CTA gating in frontend
    date_flex: bool = False  # User explicitly chose "flexible dates"
    trip_duration: Optional[int] = None  # Trip length in days (e.g., 7)
    date_window_start: Optional[str] = None  # Earliest possible start date
    date_window_end: Optional[str] = None  # Latest possible start date


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

# =============================================================================
# Plan View State Machine Types (Stage-Aware Right-Side View)
# =============================================================================

# State machine states for right-side plan view
PlanViewState = Literal[
    "S0_BOOTSTRAP",  # No plan yet (or reset). Placeholders only.
    "S1_FRAMING",  # Stage 1 output available (shortlist/skeleton)
    "S2_STRATEGY_READY",  # All relevant Stage 2 strategy nodes complete
    "S2_BLOCKED",  # Stage 2 incomplete due to missing critical fields
    "S3_ITINERARY_READY",  # Itinerary generated (day cards)
    "S3_EDITING",  # User editing itinerary assumptions/constraints
    "S3_BLOCKED",  # Stage 3 requested but blocked (missing locks)
]


class StrategySection(BaseModel):
    """A strategy section for Stage 2 view - one card per executed strategy topic."""

    id: str
    title: str = "Strategy"
    subtitle: Optional[str] = None  # e.g., "Dubai Trip"
    specialist_type: Optional[str] = None  # e.g., "hiking", "diving", "general"

    # Collapsed state
    one_liner: Optional[str] = None  # max 60 chars
    principles: List[str] = Field(default_factory=list)  # max 4 items, 50 chars each

    # Expanded state
    must_dos: List[str] = Field(default_factory=list)  # max 5 items, 110 chars each
    optional_upgrades: List[str] = Field(default_factory=list)  # max 3 items
    logistics_notes: List[str] = Field(default_factory=list)  # max 4 items
    tradeoffs_summary: Optional[str] = None  # max 300 chars

    # Provenance (debug only, not shown in UI)
    strategy_node_id: Optional[str] = None
    strategy_version: Optional[str] = None

    # Booking artifacts - counts of tiles produced by this agent (NO status field - computed by UI)
    booking_artifacts: Optional[Dict[str, int]] = None  # {"activities_count": 3, "hotels_count": 2}

    # Impact areas - which parts of the plan this agent affects
    impact_areas: List[str] = Field(default_factory=list)  # ["Schedule", "Location", "Gear"]

    # Technical log data for "System Log" display
    constraints_applied: List[Dict[str, str]] = Field(default_factory=list)
    # Each dict: {"rule": "min_24h_buffer_after_dive", "type": "safety", "reason": "..."}

    content_added: List[Dict[str, Any]] = Field(default_factory=list)
    # Each dict: {"title": "USAT Liberty Wreck", "day": 2, "type": "activity"}

    # Destination gallery - "Vibe Trio" images for Local Expert card (hero destinations only)
    destination_gallery: List[Dict[str, str]] = Field(default_factory=list)
    # Each dict: {"url": "https://...", "alt": "Dubai Marina"}

    # For General Agent: trip parameters summary (inventory counts read from tiles, not here)
    trip_summary: Optional[Dict[str, Any]] = None
    # {"destination": "Dubai", "dates": "Jan 26-Feb 2", "travelers": "1 adult"}

    # Legacy field for backward compatibility
    bullets: List[str] = Field(default_factory=list)


class OpenDecision(BaseModel):
    """An open decision that needs user input (shown in Stage 2)."""

    id: str
    statement: str  # Statement form, not question (e.g., "Trip duration not confirmed")
    related_field: Optional[str] = None  # Which trip input field this relates to
    is_blocking: bool = False  # If true, blocks Stage 3


class DayBlock(BaseModel):
    """A single activity block within a day (Stage 3)."""

    period: Literal["morning", "afternoon", "evening"]
    activity_type: str  # e.g., "moderate hike", "city stroll"
    intensity: Optional[Literal["light", "moderate", "challenging"]] = None
    summary: str  # ≤15 words, no times/prices


class DayCard(BaseModel):
    """A single day in the itinerary (Stage 3)."""

    day_number: int
    label: str  # e.g., "Arrival + light activity", "Main hike day"
    blocks: List[DayBlock] = Field(default_factory=list)  # Max 3 blocks


class ItineraryOverview(BaseModel):
    """Overview stats for Stage 3 itinerary."""

    duration_label: str  # e.g., "3 days"
    base_structure: str  # e.g., "Single base + day excursions"
    activity_density: str  # e.g., "1 major activity/day"


class ItineraryAssumptions(BaseModel):
    """Assumptions and flexible elements for Stage 3."""

    assumptions: List[str] = Field(default_factory=list)  # Max 4 items
    flexible_elements: List[str] = Field(default_factory=list)  # Max 3 items


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


class AckUpdate(BaseModel):
    """Detailed update info for collapsible message UI."""

    field: str  # Canonical UI key (e.g., "destination", "origin", "dates")
    to: str  # New value (human-readable)
    from_value: Optional[str] = None  # Previous value if overwritten


# Ack status for constraint updates
AckStatus = Literal["applied", "partial", "no_change", "needs_clarification", "failed", "rejected"]


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
    # Detailed ack payload for collapsible messages UI
    ack_status: AckStatus = "applied"
    ack_updates: List[AckUpdate] = Field(default_factory=list)  # Field + value changes

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

    # ==========================================================================
    # Plan View State Machine (Stage-Aware Right-Side View)
    # ==========================================================================
    # State machine state - determines what content to show in right panel
    plan_view_state: PlanViewState = "S0_BOOTSTRAP"

    # Stage 2 content (populated when plan_view_state in S2_*)
    strategy_sections: List[StrategySection] = Field(default_factory=list)
    executed_strategy_topics: List[str] = Field(
        default_factory=list
    )  # Topics that ran: ["hiking", "diving"]
    pending_strategy_topics: List[str] = Field(
        default_factory=list
    )  # Topics still to run: ["skiing"]
    open_decisions: List[OpenDecision] = Field(default_factory=list)

    # Stage 3 content (populated when plan_view_state in S3_*)
    itinerary_overview: Optional[ItineraryOverview] = None
    day_cards: List[DayCard] = Field(default_factory=list)
    itinerary_assumptions: Optional[ItineraryAssumptions] = None

    # State flags
    needs_refresh: bool = False  # Marks S3 content as stale after constraint change
    can_expand_to_itinerary: bool = False  # True when Stage3EntryGuard passes


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
