"""
Coordinator protocol schemas -- typed contracts between classifier, coordinator,
specialists, and the execution planner.

These schemas define the data shapes that flow through the coordinator architecture:

  User message
       |
  ClassifierOutput  (extends RouterOutput with change classification)
       |
  ExecutionPlan     (ordered steps the coordinator will execute)
       |
  TripBrief  -----> SpecialistPlan   (per-specialist contract)
       |
  ReplanRequest     (iteration on existing plans)

All schemas are Pydantic v2 BaseModel with strict type hints.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# =============================================================================
# Change Classification
# =============================================================================


class ChangeType(str, Enum):
    """Classification of how a user message changes the trip plan.

    Used by the coordinator to decide which specialists need re-invocation
    and which cached results can be preserved.
    """

    INITIAL_PLAN = "initial_plan"
    """First planning message -- everything is fresh."""

    DAY_COUNT = "day_count"
    """User changed day counts for a specialist ('3 dive days not 4')."""

    SPATIAL = "spatial"
    """User changed spatial arrangement ('move hiking near the dives')."""

    SWAP_ACTIVITY = "swap_activity"
    """User wants to replace one activity with another."""

    ADD_ACTIVITY = "add_activity"
    """User wants to add a new activity to the plan."""

    REMOVE_ACTIVITY = "remove_activity"
    """User wants to remove an activity from the plan."""

    DATE_CHANGE = "date_change"
    """Dates changed -- specialists may need to adjust schedules."""

    DESTINATION_CHANGE = "destination_change"
    """Destination changed -- invalidates ALL specialist plans and logistics."""

    PREFERENCE = "preference"
    """General preference change ('more relaxed pace')."""

    LOGISTICS = "logistics"
    """Logistics preference changed ('direct flights only')."""

    SETTINGS = "settings"
    """Hotel/flight/other settings changed ('5-star hotels')."""

    QUESTION = "question"
    """User is asking a question, not changing the plan."""

    GREETING = "greeting"
    """Social/greeting input -- no plan change."""

    RESET = "reset"
    """Explicit reset -- clear everything and start over."""


# =============================================================================
# Lightweight Change Classification (small enough for Gemini function calling)
# =============================================================================


class ChangeClassification(BaseModel):
    """Lightweight change classification — small enough for Gemini function calling.

    The full ClassifierOutput (~40 fields, 14-value enum) triggers Gemini's
    "too much branching" rejection.  This 6-field schema is used in a second
    lightweight LLM call after the proven RouterOutput extraction, then merged
    into a full ClassifierOutput.
    """

    intent: Literal["GREETING", "RESET", "PLANNING", "QUESTION"] = Field(
        description="User intent classification."
    )
    change_type: ChangeType = Field(
        default=ChangeType.INITIAL_PLAN,
        description="How this message changes the trip plan.",
    )
    fields_changed: List[str] = Field(
        default_factory=list,
        description="Which plan fields this message modifies.",
    )
    affects: List[str] = Field(
        default_factory=list,
        description="Specialist topics that need re-dispatch.",
    )
    preserves: List[str] = Field(
        default_factory=list,
        description="Specialist topics whose plans should be kept.",
    )
    informs: List[str] = Field(
        default_factory=list,
        description="Specialist topics that should receive cross-context.",
    )


# =============================================================================
# Classifier Output (extends RouterOutput fields)
# =============================================================================


class ClassifierOutput(BaseModel):
    """Combined intent classification, field extraction, and change analysis.

    Extends the existing RouterOutput field set with change-classification
    fields that the coordinator uses to decide execution strategy.

    All fields from RouterOutput are preserved for backward compatibility
    during the bridge period between old and new architectures.
    """

    # -- Intent classification (from RouterOutput) --
    intent: Literal["GREETING", "RESET", "PLANNING", "QUESTION"]
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    reasoning: str = Field(description="Brief explanation of classification")

    # -- Specialist hints (from RouterOutput) --
    specialist_hints: List[str] = Field(
        default_factory=list,
        description="List of detected specialist activities (can be multiple)",
    )

    # -- Activity categories (from RouterOutput) --
    activity_categories: List[str] = Field(
        default_factory=list,
        description="Activity categories mentioned (open-ended Tier 2).",
    )

    # -- Activity day preferences (from RouterOutput) --
    activity_day_preferences: Optional[str] = Field(
        None,
        description=(
            "JSON string of day counts per activity when user explicitly states "
            'numbers. E.g., "3 days diving" -> \'{"diving": 3}\'. null if not '
            "specified."
        ),
    )

    # -- Per-day activity density --
    activities_per_day: Optional[int] = Field(
        None,
        description=(
            "Target number of activities per day if user specifies density. "
            "E.g., '2 activities a day' → 2. Only set when explicitly stated."
        ),
    )

    # -- Extracted trip fields (from RouterOutput) --
    destination: Optional[str] = Field(None, description="Destination city/country if mentioned")
    origin: Optional[str] = Field(None, description="Origin city if mentioned")
    origin_iata: Optional[str] = Field(
        None,
        description="IATA airport code for origin city (e.g. SFO, LHR, CDG).",
    )
    destination_iata: Optional[str] = Field(
        None,
        description="IATA airport code for destination (e.g. DPS, CDG, DXB).",
    )
    start_date: Optional[str] = Field(None, description="Start date in YYYY-MM-DD format")
    end_date: Optional[str] = Field(None, description="End date in YYYY-MM-DD format")
    duration_days: Optional[int] = Field(
        None,
        description="Trip duration if mentioned (e.g., 'for a week' = 7)",
    )
    adults: Optional[int] = Field(None, description="Number of adults if mentioned")
    children: Optional[int] = Field(None, description="Number of children if mentioned")
    budget: Optional[float] = Field(None, description="Budget amount in USD if mentioned")

    # -- Flags (from RouterOutput) --
    has_dates_in_message: bool = Field(
        default=False,
        description="True if user provided any date info in this message.",
    )
    has_activity_in_message: bool = Field(
        default=False,
        description="True if user mentioned specific activities.",
    )
    planning_ready: bool = Field(
        default=False,
        description="True if user explicitly wants to plan now.",
    )

    # -- Modification intents (from RouterOutput) --
    removal_targets: List[str] = Field(
        default_factory=list,
        description="Activities/categories user wants to REMOVE from plan.",
    )
    skill_level: Optional[str] = Field(
        None,
        description=("Skill/experience level: 'beginner', 'intermediate', 'advanced'."),
    )
    reset_budget: bool = Field(
        default=False,
        description="True if user wants to REMOVE/CLEAR budget constraint.",
    )
    multi_destination_detected: bool = Field(
        default=False,
        description="True if user mentioned multiple separate destinations.",
    )
    reset_hotel: bool = Field(
        default=False,
        description="True if user wants to CLEAR hotel preferences.",
    )

    # -- Settings extraction (from RouterOutput) --
    hotel_min_stars: Optional[int] = Field(
        None,
        description="Minimum hotel star rating (1-5) if mentioned.",
    )
    hotel_style: Optional[str] = Field(
        None,
        description=("Hotel style: 'luxury', 'boutique', 'budget', 'mid-range'."),
    )
    hotel_amenities: List[str] = Field(
        default_factory=list,
        description="Requested hotel amenities: pool, spa, gym, etc.",
    )
    hotel_location: Optional[str] = Field(
        None,
        description=("Hotel location preference: 'beachfront', 'city_center', 'airport'."),
    )
    flight_direct_only: Optional[bool] = Field(
        None,
        description="True if user wants direct/non-stop flights.",
    )
    flight_cabin_class: Optional[str] = Field(
        None,
        description=("Cabin class: 'economy', 'premium_economy', 'business', 'first'."),
    )

    # -- Planning intent (from RouterOutput) --
    planning_intent: Optional[str] = Field(
        None,
        description=("Planning readiness: 'ready', 'modifying', 'exploring', 'greeting'."),
    )
    question_type: Optional[str] = Field(
        None,
        description="Destination question topic if asking a question.",
    )
    date_auto_adjustments: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Date corrections applied by backend validation.",
    )

    # =========================================================================
    # NEW: Change classification fields (coordinator-specific)
    # =========================================================================

    change_type: ChangeType = Field(
        default=ChangeType.INITIAL_PLAN,
        description="How this message changes the trip plan.",
    )
    fields_changed: List[str] = Field(
        default_factory=list,
        description=(
            "Which plan fields this message modifies. "
            "E.g., ['destination', 'start_date'] or ['activity_categories']."
        ),
    )
    affects: List[str] = Field(
        default_factory=list,
        description=(
            "Specialist topics that need re-dispatch. "
            "E.g., ['diving'] for '3 dive days not 4'. "
            "Empty for settings-only changes."
        ),
    )
    preserves: List[str] = Field(
        default_factory=list,
        description=(
            "Specialist topics whose plans should be kept unchanged. "
            "E.g., ['hiking', 'cooking'] when only diving changes."
        ),
    )
    informs: List[str] = Field(
        default_factory=list,
        description=(
            "Specialist topics that should receive cross-context but NOT "
            "re-run. E.g., ['diving'] when hiking moves near dive zone."
        ),
    )


# =============================================================================
# Trip Brief -- what the coordinator sends to specialists
# =============================================================================


class TripBrief(BaseModel):
    """Structured packet sent to a specialist with everything they need to plan.

    The specialist never sees raw user text. It sees this brief.
    The coordinator assembles this from trip_inputs + other specialist plans.
    """

    # Core trip parameters
    destination: str
    start_date: str
    end_date: str
    num_days: int

    # Traveler context
    adults: int = 1
    children: int = 0
    skill_level: Optional[str] = None

    # Budget allocation for this specialist's domain
    budget_total: Optional[float] = None
    budget_allocation_pct: float = Field(
        default=0.25,
        description="Coordinator-decided budget share for this specialist.",
    )

    # Scheduling constraints from other specialists
    reserved_days: List[int] = Field(
        default_factory=list,
        description="Day numbers already claimed by other specialists.",
    )
    target_day_count: Optional[int] = Field(
        None,
        description="User-requested number of days for this activity.",
    )
    activities_per_day: int = Field(
        default=2,
        description="Global pace setting: activities per day (1=relaxed, 2=moderate, 3=packed).",
    )

    # Cross-specialist spatial context
    hotel_zone: Optional[str] = None
    other_specialist_zones: Dict[str, str] = Field(
        default_factory=dict,
        description=("topic -> zone mapping. E.g., {'diving': 'Amed, East Bali'}"),
    )

    # Trip intent
    trip_vibe: Optional[str] = None  # "adventure", "relaxation", etc.

    # All active categories for fair-share allocation across specialists
    categories: List[str] = Field(
        default_factory=list,
        description="All active trip categories for fair-share allocation.",
    )


# =============================================================================
# Specialist Output Protocol -- what specialists return
# =============================================================================


class SpecialistDayPlan(BaseModel):
    """Plan for a single day from a specialist."""

    day_number: int
    period: Literal["morning", "afternoon", "evening", "full_day"] = "morning"
    title: str
    description: str = ""
    location: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    duration_hours: float = 3.0
    difficulty: str = "beginner"
    # Topic-specific optional fields
    depth_meters: Optional[int] = None
    elevation_meters: Optional[int] = None
    certification_required: Optional[str] = None
    logic_hook: Optional[str] = None  # "Why this matters" tip


class SpecialistTransit(BaseModel):
    """Transit requirement between activities."""

    from_day: int
    to_day: int
    mode: Literal["walk", "drive", "boat", "internal_flight"] = "drive"
    estimated_minutes: int = 30
    note: Optional[str] = None


class SpecialistConstraintOutput(BaseModel):
    """Constraint from specialist (matches existing LLMConstraint shape)."""

    constraint_id: str
    constraint_type: str = "blocking"
    applies_to_categories: List[str] = Field(default_factory=list)
    buffer_hours: Optional[int] = None
    reason: str = ""
    label: Optional[str] = None
    icon: Optional[str] = None


class SpecialistPlan(BaseModel):
    """Complete output from a specialist dispatch.

    Replaces LLMSpecialistOutput with richer structure that supports
    coordinator merging and selective re-planning.
    """

    topic: str
    feasibility_status: Literal["feasible", "infeasible", "conditional"] = "feasible"
    feasibility_reason: Optional[str] = None

    day_plans: List[SpecialistDayPlan] = Field(default_factory=list)
    constraints: List[SpecialistConstraintOutput] = Field(default_factory=list)
    transit_requirements: List[SpecialistTransit] = Field(default_factory=list)

    # Budget tracking
    estimated_cost: Optional[float] = None

    # Specialist's editorial insight (fed to conversationalist)
    editorial: str = ""

    # Confidence in the plan quality (0-1)
    confidence: float = 0.8


# =============================================================================
# Replan Request
# =============================================================================


class ReplanRequest(BaseModel):
    """When the user modifies an existing plan, the coordinator sends
    the original plan + what changed, not a blank brief.
    """

    original_brief: TripBrief
    original_plan: SpecialistPlan
    change_trigger: str  # "User requested 3 dive days instead of 4"
    change_type: ChangeType
    updated_brief: TripBrief  # Brief with updated fields
    cross_specialist_context: Dict[str, Any] = Field(
        default_factory=dict,
        description=("Plans from other specialists for spatial/temporal awareness."),
    )
    preserve: List[str] = Field(
        default_factory=list,
        description=("What to keep from original plan. E.g., ['hotel_zone', 'day_1_activity']"),
    )


# =============================================================================
# Execution Plan -- coordinator's step-by-step execution strategy
# =============================================================================


class StepType(str, Enum):
    """Types of steps the coordinator can execute."""

    CLASSIFY = "classify"
    DISPATCH_SPECIALISTS = "dispatch_specialists"
    SEARCH_TILES = "search_tiles"
    BUILD_ITINERARY = "build_itinerary"
    GENERATE_RESPONSE = "generate_response"
    LOCAL_INTEL = "local_intel"
    SHORT_CIRCUIT = "short_circuit"  # greeting, reset, simple question


class ExecutionStep(BaseModel):
    """A single step in the coordinator's execution plan."""

    step_type: StepType
    params: Dict[str, Any] = Field(default_factory=dict)
    parallel_with: Optional[StepType] = None  # Run in parallel with this step


class ExecutionPlan(BaseModel):
    """The coordinator's deterministic plan for handling this turn.

    Pure Python produces this. No LLM involved.
    """

    steps: List[ExecutionStep] = Field(default_factory=list)
    reason: str = ""  # For debugging/logging
    estimated_llm_calls: int = 0
    estimated_wall_ms: int = 0
