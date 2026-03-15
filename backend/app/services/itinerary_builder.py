"""
Itinerary Builder Service - Multi-Specialist Orchestration

Pure Python service that transforms specialist outputs into chronological,
constraint-validated timeline. Supports multi-specialist trips with conflict resolution.

NOT a LangGraph node - preserves 7-node architecture invariant.

Algorithm Phases:
1. Temporal Scaffolding - Create DayCard[] from dates
2. Anchor Placement - Arrival/departure from flight tiles
3. Multi-Specialist Constraint Merge - Priority resolution
4. Buffer Injection - Safety blocks by severity
5. Activity Distribution - Round-robin interleaving
6. Tile Matching - Hotels span all days

"""

import logging
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Literal, Optional, Tuple
from urllib.parse import quote

from pydantic import BaseModel, Field

from app.debug_utils import _debug, _debug_itinerary
from app.planner.specialist_registry import (
    ALL_CONSTRAINT_ALIASES,
    get_cross_domain_buffer_days,
    get_cross_domain_target_specialists,
    get_nofly_buffer_days,
)
from app.planner.specialist_registry import TIER1_SPECIALIST_NAMES as _TIER1_SPECIALIST_NAMES
from app.planner.state import ConstraintSeverity

logger = logging.getLogger(__name__)

# =============================================================================
# Constraint Rule Normalization
# =============================================================================
# LLM may output constraint rules with various naming conventions.
# Builder normalizes to canonical rules for consistent detection.


def _find_constraint(
    constraints: List["MergedConstraint"],
    canonical_rule: str,
) -> Optional["MergedConstraint"]:
    """
    Find constraint by canonical rule name or any of its aliases.

    This provides fuzzy matching for LLM-generated constraint rules,
    ensuring detection survives prompt/model variations.

    Args:
        constraints: List of merged constraints
        canonical_rule: The canonical rule name to search for

    Returns:
        Matching constraint or None
    """
    aliases = ALL_CONSTRAINT_ALIASES.get(canonical_rule, [])
    all_names = [canonical_rule] + aliases

    for c in constraints:
        rule_lower = c.rule.lower().replace("-", "_").replace(" ", "_")
        for name in all_names:
            if rule_lower == name.lower() or name.lower() in rule_lower:
                return c
    return None


def _constraint_rule_key(value: Any) -> str:
    """Normalize constraint rule names for alias matching and dedupe."""
    if not isinstance(value, str):
        return ""
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _raw_constraint_matches(constraint: Dict[str, Any], canonical_rule: str) -> bool:
    """Return True when a raw constraint dict matches a canonical rule or alias."""
    rule_key = _constraint_rule_key(constraint.get("rule") or constraint.get("constraint_id"))
    if not rule_key:
        return False

    aliases = [
        _constraint_rule_key(alias) for alias in ALL_CONSTRAINT_ALIASES.get(canonical_rule, [])
    ]
    all_names = [_constraint_rule_key(canonical_rule), *aliases]
    return any(rule_key == name or name in rule_key for name in all_names if name)


def _merge_constraint_inputs(
    section_constraints: List[Dict[str, Any]],
    canonical_constraints: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Append canonical trip constraints that are missing from specialist sections."""
    merged = list(section_constraints)

    for canonical in canonical_constraints:
        if not isinstance(canonical, dict):
            continue
        canonical_rule = _constraint_rule_key(
            canonical.get("rule") or canonical.get("constraint_id")
        )
        if not canonical_rule:
            continue
        if any(_raw_constraint_matches(existing, canonical_rule) for existing in merged):
            continue
        merged.append(canonical)

    return merged


def _normalize_title_key(title: Optional[str]) -> str:
    """Normalize activity titles for duplicate detection across tile IDs."""
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def _price_estimate_to_level(price_estimate: Any) -> Optional[int]:
    """Convert price estimate to Google Places price_level int (0-4).

    Accepts float/int dollar amount or string markers ("$", "$$", etc.).
    """
    if price_estimate is None:
        return None
    if isinstance(price_estimate, str):
        return {"Free": 0, "$": 1, "$$": 2, "$$$": 3, "$$$$": 4}.get(price_estimate)
    try:
        p = float(price_estimate)
    except (TypeError, ValueError):
        return None
    if p == 0:
        return 0
    if p < 30:
        return 1
    if p < 75:
        return 2
    if p < 150:
        return 3
    return 4


def normalize_poi_type_key(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace(" ", "_")
    return normalized or None


def canonical_poi_type(raw: Any) -> Optional[str]:
    key = normalize_poi_type_key(raw)
    if not key:
        return None
    if key in POI_TYPE_ALIASES:
        return POI_TYPE_ALIASES[key]
    if key in _CANONICAL_POI_TYPES:
        return key
    if any(token in key for token in ("culture", "cultural", "heritage")):
        return "cultural"
    if any(token in key for token in ("temple", "church", "worship", "mosque", "synagogue")):
        return "temples"
    if any(
        token in key
        for token in ("museum", "landmark", "historic", "monument", "plaza", "fountain")
    ):
        return "cultural"
    if any(token in key for token in ("restaurant", "cafe", "bar", "bakery", "food", "meal")):
        return "food"
    if any(token in key for token in ("park", "garden", "nature", "zoo", "camp")):
        return "nature"
    if any(token in key for token in ("shop", "store", "market", "mall")):
        return "shopping"
    if any(token in key for token in ("spa", "wellness", "gym", "beauty")):
        return "spa"
    if any(token in key for token in ("tour", "point_of_interest", "visitor", "travel_agency")):
        return "tours"
    return None


# =============================================================================
# Input/Output Types
# =============================================================================


class DayBlockOutput(BaseModel):
    """Output block for itinerary - matches frontend DayBlock interface."""

    id: Optional[str] = None
    period: Literal["morning", "afternoon", "evening"]
    activity_type: str
    intensity: Optional[Literal["light", "moderate", "challenging"]] = None
    summary: str

    # Buffer/Safety fields
    is_buffer: bool = False
    buffer_type: Optional[
        Literal["no_fly", "rest_day", "acclimatization", "arrival", "departure"]
    ] = None
    buffer_reason: Optional[str] = None

    # Specialist metadata
    specialist_type: Optional[str] = None
    constraints: List[str] = Field(default_factory=list)
    activity_domain: Optional[Literal["tier1", "tier2"]] = None
    activity_provenance: Optional[Literal["ai_suggested", "user_browse_added"]] = None
    map_type: Optional[str] = None  # Canonical map pin category (e.g., "food", "cycling")

    # Rich content
    image_url: Optional[str] = None
    duration: Optional[str] = None
    rating: Optional[float] = None  # Google Places star rating
    review_count: Optional[int] = None  # Google Places review count
    price_level: Optional[int] = None  # Google Places price level (0-4)
    price_estimate: Optional[float] = None  # USD estimate from tile
    coordinates: Optional[Dict[str, float]] = None  # {lat, lng}
    google_place_id: Optional[str] = None  # Google Places ID
    deeplink: Optional[str] = None  # Google Maps URL

    # Logistics layer
    scheduled_time: Optional[str] = None
    logistics_details: Optional[str] = None
    hotel_name: Optional[str] = None

    # Booking integration
    booked_tile: Optional[Dict[str, Any]] = None
    requires_booking: bool = False
    booking_category: Optional[Literal["hotel", "flight", "activity"]] = None

    # Preference attribution (shows why this tile was selected)
    preference_status: Optional[Literal["user_preferred", "ai_selected", "ai_override"]] = None
    preference_override_reason: Optional[str] = None
    alternative_tile_id: Optional[str] = None

    # Inline constraint display (shows active constraints on this block)
    active_constraints: List[Dict[str, Any]] = Field(default_factory=list)

    # Unschedulable marker (for partial timeline when conflicts occur)
    unschedulable: bool = False
    unschedulable_reason: Optional[str] = None
    unschedulable_days_needed: Optional[int] = None


def _ensure_block_display_floor(
    block: DayBlockOutput,
    destination: str,
) -> DayBlockOutput:
    """Guarantee minimum viable display data for every activity block.

    Runs AFTER all enrichment. Fills gaps with computed fallbacks
    so frontend cards never show empty deeplinks next to fully-enriched
    browse tiles.
    """
    if block.is_buffer:
        return block

    logger.info(
        "[DISPLAY_FLOOR] block='%s' deeplink=%s image=%s",
        (block.summary or "")[:40],
        (block.deeplink or "NONE")[:60],
        (block.image_url or "NONE")[:60],
    )

    # Deeplink: prefer place_id (exact), then named search (finds listing),
    # then raw coords (generic pin — last resort when no title).
    if not block.deeplink:
        if block.google_place_id:
            block.deeplink = (
                f"https://www.google.com/maps/place/?q=place_id:{block.google_place_id}"
            )
        elif block.summary:
            # Named search finds the actual venue listing (with photos, reviews)
            # rather than dropping a generic pin at coordinates.
            block.deeplink = (
                f"https://www.google.com/maps/search/{quote(f'{block.summary} {destination}')}"
            )
        elif block.coordinates and block.coordinates.get("lat") and block.coordinates.get("lng"):
            lat, lng = block.coordinates["lat"], block.coordinates["lng"]
            block.deeplink = f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"

    # Image: deterministic Unsplash placeholder keyed on specialist type
    if not block.image_url:
        from app.placeholders import get_activity_image

        block.image_url = get_activity_image(
            block.specialist_type or block.activity_type or "activity",
            destination,
            block.summary,
        )

    return block


class DayCardOutput(BaseModel):
    """Output day card - matches frontend DayCard interface."""

    day_number: int
    date: Optional[str] = None  # ISO date string, e.g. "2025-02-12"
    label: str
    subtitle: Optional[str] = None  # Explanatory context for special days
    blocks: List[DayBlockOutput] = Field(default_factory=list)


class ItineraryOverviewOutput(BaseModel):
    """Overview stats for itinerary."""

    duration_label: str
    base_structure: str
    activity_density: str


class BuilderConflict(BaseModel):
    """Detected conflict that needs resolution."""

    type: Literal["temporal_capacity", "constraint_clash", "insufficient_days"]
    severity: ConstraintSeverity
    day: Optional[int] = None
    specialists: List[str] = Field(default_factory=list)
    message: str
    overflow_hours: Optional[float] = None


class Resolution(BaseModel):
    """Resolution option for a conflict."""

    action: Literal["extend_trip", "reduce_activities", "reorder", "shift_activities"]
    description: str
    new_duration: Optional[int] = None
    keep_specialist: Optional[str] = None
    feasibility: Literal["recommended", "possible", "not_recommended"]


class ItineraryAssumptionsOutput(BaseModel):
    """Itinerary planning assumptions."""

    assumptions: List[str] = Field(default_factory=list)
    flexible_elements: List[str] = Field(default_factory=list)


class ItineraryResult(BaseModel):
    """Result from itinerary builder."""

    success: bool
    day_cards: List[DayCardOutput] = Field(default_factory=list)
    overview: Optional[ItineraryOverviewOutput] = None
    assumptions: Optional[ItineraryAssumptionsOutput] = None
    conflicts: List[BuilderConflict] = Field(default_factory=list)
    resolutions: List[Resolution] = Field(default_factory=list)
    error: Optional[str] = None
    dropped_preferred_count: int = 0  # Activities that couldn't fit in available days
    warnings: List[str] = Field(
        default_factory=list
    )  # User-facing warnings (e.g., "Reduced diving from 4 to 1")
    total_activities_input: int = 0  # Activities fed into distribution
    total_activities_placed: int = 0  # Activities actually placed on timeline


@dataclass
class MergedConstraint:
    """Constraint merged from multiple specialists."""

    source: str  # specialist type
    rule: str
    severity: ConstraintSeverity
    blocks_day: bool
    day: Optional[int] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    reason: Optional[str] = None


@dataclass
class ActivityBlock:
    """Internal activity representation during scheduling."""

    title: str
    description: str
    specialist_type: str
    day: Optional[int] = None  # Assigned day (1-indexed)
    period: Optional[str] = None  # morning/afternoon/evening
    duration_hours: float = 3.0
    intensity: Optional[str] = None
    image_url: Optional[str] = None
    coordinates: Optional[List[float]] = None  # [lng, lat]
    is_buffer: bool = False
    buffer_type: Optional[str] = None
    buffer_reason: Optional[str] = None
    tile_id: Optional[str] = None
    constraints: List[str] = field(default_factory=list)
    # Places metadata (from enrich_activities_with_places)
    rating: Optional[float] = None
    user_ratings_count: Optional[int] = None
    price_level: Optional[int] = None
    google_place_id: Optional[str] = None
    deeplink: Optional[str] = None


@dataclass
class PreferenceOverrideInput:
    """User heart preferences for tile weighting."""

    preferred_hotel_ids: List[str] = field(default_factory=list)
    preferred_activity_ids: List[str] = field(default_factory=list)
    preferred_flight_ids: List[str] = field(default_factory=list)
    pinned_day_map: Dict[str, int] = field(default_factory=dict)  # tile_id → day_number (1-indexed)
    pinned_priority_map: Dict[str, str] = field(default_factory=dict)  # tile_id → "high" | "low"

    def is_hotel_preferred(self, tile_id: str) -> bool:
        """Check if a hotel tile is user-preferred."""
        return tile_id in self.preferred_hotel_ids

    def is_activity_preferred(self, tile_id: str) -> bool:
        """Check if an activity tile is user-preferred."""
        return tile_id in self.preferred_activity_ids

    def is_flight_preferred(self, tile_id: str) -> bool:
        """Check if a flight tile is user-preferred."""
        return tile_id in self.preferred_flight_ids


@dataclass
class ItineraryBuilderInput:
    """Input to the itinerary builder."""

    start_date: str  # ISO date string
    end_date: str  # ISO date string
    strategy_sections: List[Dict[str, Any]]
    tiles: Dict[str, Any]  # Tile ID -> Tile dict
    destination: Optional[str] = None
    origin: Optional[str] = None
    preferences: Optional[PreferenceOverrideInput] = None  # User heart preferences
    activity_categories: Optional[List[str]] = None  # User-selected categories from pills
    activity_day_preferences: Optional[Dict[str, int]] = None  # {"diving": 3, "hiking": 2}
    activities_per_day: Optional[int] = None  # Target activities per day (e.g., 2 for "2 a day")
    adults: int = 1
    children: int = 0
    # Browse tiles explicitly added by user (source="browse_add") — survive graph re-runs
    user_pinned_tiles: Optional[Dict[str, Any]] = None  # tile_id → {tile, preferred_day, source}
    canonical_constraints: List[Dict[str, Any]] = field(default_factory=list)
    budget: Optional[float] = None
    currency: str = "USD"


# =============================================================================
# Constants
# =============================================================================

# Rules that block entire days
BLOCKING_RULES = {
    "min_24h_buffer_after_dive",
    "no_altitude_after_dive",  # Cross-domain: diving → hiking
    "altitude_acclimatization",
    "equipment_drying",
    "post_surgery_recovery",
}

# Day capacity in hours (24 - 8 sleep - 3 meals/transit - 2 reserve)
DAY_CAPACITY_HOURS = 11.0

# Maximum blocks per day
MAX_BLOCKS_PER_DAY = 3

# Constraint severity mapping
CONSTRAINT_SEVERITY_MAP = {
    # Blocking (Safety/Legal)
    "min_24h_buffer_after_dive": ConstraintSeverity.BLOCKING,
    "no_altitude_after_dive": ConstraintSeverity.BLOCKING,  # Cross-domain: diving → hiking
    "decompression_stop": ConstraintSeverity.BLOCKING,
    "altitude_limit": ConstraintSeverity.BLOCKING,
    "visa_requirement": ConstraintSeverity.BLOCKING,
    "permit_required": ConstraintSeverity.BLOCKING,
    "certification_required": ConstraintSeverity.BLOCKING,
    # Strong (Optimization)
    "altitude_acclimatization": ConstraintSeverity.STRONG,
    "best_weather_window": ConstraintSeverity.STRONG,
    "crowd_avoidance": ConstraintSeverity.STRONG,
    "equipment_rental": ConstraintSeverity.STRONG,
    "opening_hours": ConstraintSeverity.STRONG,
    # Soft (Preference)
    "scenic_route": ConstraintSeverity.SOFT,
    "photo_opportunity": ConstraintSeverity.SOFT,
    "early_start_preferred": ConstraintSeverity.SOFT,
    "minimize_walking": ConstraintSeverity.SOFT,
}

# Default duration for experience tiles when meta.duration_hours is missing
DEFAULT_EXPERIENCE_HOURS = 1.5

# Max same-category experience tiles per day (prevents 3x yoga on one day)
MAX_SAME_CATEGORY_PER_DAY = 2

# Time-of-day slot order for complementarity scoring
_TIME_SLOT_ORDER = {"morning": 0, "afternoon": 1, "evening": 2}

# Canonical map-pin taxonomy shared with frontend pin config.
_CANONICAL_POI_TYPES: set[str] = set(_TIER1_SPECIALIST_NAMES) | {
    "yoga",
    "wellness",
    "spa",
    "nightlife",
    "cooking",
    "culture",
    "cultural",
    "temples",
    "food",
    "beach",
    "shopping",
    "sightseeing",
    "photography",
    "relaxation",
    "nature",
    "tours",
    "adventure",
    "family",
    "activity",
}

# Raw provider categories/types -> canonical map-pin category.
# Canonical source — also imported by main.py for insert-activity-block endpoint.
POI_TYPE_ALIASES: dict[str, str] = {
    # Browse / Tier-2 canonical categories
    "culture": "cultural",
    "cultural": "cultural",
    "food": "food",
    "nature": "nature",
    "shopping": "shopping",
    "spa": "spa",
    "tours": "tours",
    "attraction": "tours",
    "cultural_attraction": "cultural",
    # Places primaryType families
    "tourist_attraction": "tours",
    "travel_agency": "tours",
    "point_of_interest": "tours",
    "museum": "cultural",
    "art_gallery": "cultural",
    "historical_landmark": "cultural",
    "cultural_landmark": "cultural",
    "monument": "cultural",
    "plaza": "cultural",
    "ruins": "cultural",
    "fountain": "cultural",
    "hindu_temple": "temples",
    "temple": "temples",
    "church": "temples",
    "place_of_worship": "temples",
    "synagogue": "temples",
    "mosque": "temples",
    "restaurant": "food",
    "cafe": "food",
    "bar": "food",
    "bakery": "food",
    "meal_takeaway": "food",
    "meal_delivery": "food",
    "park": "nature",
    "natural_feature": "nature",
    "national_park": "nature",
    "campground": "nature",
    "zoo": "nature",
    "botanical_garden": "nature",
    "shopping_mall": "shopping",
    "market": "shopping",
    "store": "shopping",
    "clothing_store": "shopping",
    "department_store": "shopping",
    "beauty_salon": "spa",
    "gym": "spa",
}


def _parse_duration_hours(duration_str: Optional[str], default: float = 3.0) -> float:
    """Parse '4h' → 4.0, '1.5h' → 1.5. Falls back to default."""
    if not duration_str:
        return default
    try:
        return float(duration_str.replace("h", "").strip())
    except (ValueError, AttributeError):
        return default


# =============================================================================
# Itinerary Builder
# =============================================================================


class ItineraryBuilder:
    """
    Pure Python itinerary scheduling service.

    Transforms specialist outputs into chronological, constraint-validated timeline.
    Supports multi-specialist trips with conflict detection and resolution.
    """

    def __init__(self):
        """Initialize builder with empty preferences."""
        self.preferences: Optional[PreferenceOverrideInput] = None
        # Defaults let unit tests call internal phases directly without build().
        self.destination: str = ""
        self._warnings: List[str] = []
        self._nofly_buffer_days: int = 0
        self._day_preferences: Dict[str, int] = {}
        self._activities_per_day: int = 2
        self._budget: Optional[float] = None
        self._currency: str = "USD"  # TODO: use for currency-aware price formatting
        self._num_days: int = 0
        self._children: int = 0
        # None = no category filter, set() = user explicitly cleared categories.
        self._active_categories: Optional[set[str]] = None

    def _normalize_activity_id(self, activity: ActivityBlock) -> str:
        """Generate consistent ID for matching across frontend/backend."""
        # Try tile_id first (most reliable)
        if activity.tile_id:
            return activity.tile_id

        # Fallback: normalize title/summary
        title = activity.title or activity.source or ""
        return title.lower().replace(" ", "_").replace("'", "").replace("-", "_")

    def build(self, input_data: ItineraryBuilderInput) -> ItineraryResult:
        """
        Main entry point - builds full itinerary.

        Returns:
            ItineraryResult with day_cards, or conflicts if irreconcilable
        """
        _debug(
            f"[ItineraryBuilder] 🏗️ Starting build: "
            f"start={input_data.start_date}, end={input_data.end_date}, "
            f"dest={input_data.destination}, "
            f"sections={len(input_data.strategy_sections)}, "
            f"tiles={len(input_data.tiles)}"
        )

        # Store preferences for use across phases
        self.preferences = input_data.preferences
        # Store destination for altitude constraint checks in _detect_early_conflicts
        self.destination = input_data.destination
        # Track warnings for user display (e.g., "Reduced diving from 4 to 1")
        self._warnings: List[str] = []
        self._nofly_buffer_days: int = 0
        self._day_preferences = input_data.activity_day_preferences or {}
        self._children: int = input_data.children
        base_apd = input_data.activities_per_day or 2
        if self._children > 0:
            base_apd = min(base_apd, 2)
        self._activities_per_day: int = max(1, min(base_apd, 5))
        self._budget = input_data.budget
        self._currency = input_data.currency
        self._num_days = 0  # set after date parsing
        # Active categories for Phase 5.25 preferred-tile category filter.
        # None means "no filter" (user didn't specify categories).
        # set() means "user explicitly cleared all categories — skip all".
        self._active_categories: Optional[set[str]] = (
            {c.lower() for c in input_data.activity_categories}
            if input_data.activity_categories is not None
            else None
        )

        try:
            # Parse dates
            start = self._parse_date(input_data.start_date)
            end = self._parse_date(input_data.end_date)
            duration = (end - start).days + 1 if start and end else "N/A"
            _debug(
                f"[ItineraryBuilder] Parsed dates: start={start}, end={end}, "
                f"duration={duration} days"
            )

            if not start or not end:
                _debug(
                    f"[ItineraryBuilder] ⚠️ Invalid dates - start_date={input_data.start_date}, "
                    f"end_date={input_data.end_date}"
                )
                return ItineraryResult(
                    success=False,
                    error="Invalid dates - cannot generate itinerary",
                )

            if end < start:
                return ItineraryResult(
                    success=False,
                    error="End date must be after start date",
                )

            # Validate minimum trip duration (2+ days required)
            trip_duration = (end - start).days + 1
            self._num_days = trip_duration
            if trip_duration < 2:
                logger.warning(
                    f"[ItineraryBuilder] Trip too short: {trip_duration} day(s). "
                    f"Minimum 2 days required."
                )
                return ItineraryResult(
                    success=False,
                    error="TRIP_TOO_SHORT",
                )

            # Phase 1: Create day skeleton
            days = self._create_day_skeleton(start, end)

            # Phase 2: Extract activities and constraints from all specialists
            activities, section_constraints = self._extract_specialist_content(
                input_data.strategy_sections
            )
            constraints = _merge_constraint_inputs(
                section_constraints,
                input_data.canonical_constraints,
            )

            # Phase 2.5: Enrich specialist activities with Google Places tile data
            activities = self._enrich_activities_from_tiles(activities, input_data.tiles)

            # Phase 2a: Merge constraints with priority
            merged_constraints = self._merge_constraints(constraints)

            # Phase 2b: Check for irreconcilable conflicts early
            # Returns both conflicts AND partial schedule showing what CAN be scheduled
            early_conflicts, partial_days = self._detect_early_conflicts(
                days,
                activities,
                merged_constraints,
                input_data.tiles,
                input_data.origin,
            )
            if early_conflicts:
                resolutions = self._generate_resolutions(early_conflicts, len(days))
                partial_days = self._annotate_activity_axes(partial_days)
                _debug(
                    f"[ItineraryBuilder] ⚠️ BuilderConflict detected: "
                    f"{len(early_conflicts)} conflicts, "
                    f"returning partial schedule with {len(partial_days)} day cards"
                )
                # Detailed conflict trace for debugging
                for i, conflict in enumerate(early_conflicts):
                    sev = (
                        conflict.severity.value
                        if hasattr(conflict.severity, "value")
                        else conflict.severity
                    )
                    _debug(
                        f"[ItineraryBuilder] CONFLICT[{i}]: type={conflict.type} "
                        f"severity={sev} specialists={conflict.specialists}"
                    )
                    _debug(f"[ItineraryBuilder] CONFLICT[{i}] message: {conflict.message}")
                # Trace partial day_cards structure
                for day in partial_days:
                    scheduled = [
                        b.summary for b in day.blocks if not getattr(b, "unschedulable", False)
                    ]
                    unschedulable = [
                        f"{b.summary} ({b.unschedulable_reason})"
                        for b in day.blocks
                        if getattr(b, "unschedulable", False)
                    ]
                    if scheduled or unschedulable:
                        _debug(
                            f"[ItineraryBuilder] Day {day.day_number}: "
                            f"scheduled={scheduled} unschedulable={unschedulable}"
                        )
                return ItineraryResult(
                    success=False,
                    conflicts=early_conflicts,
                    resolutions=resolutions,
                    day_cards=partial_days,  # Return partial schedule
                    overview=self._compute_overview(partial_days),
                    error="CONSTRAINT_CONFLICT",
                )

            # Phase 3: Place temporal anchors (arrival/departure)
            days = self._place_anchors(days, input_data.tiles, input_data.origin)

            # Phase 4: Inject safety buffers
            days = self._inject_safety_buffers(days, merged_constraints, activities)

            # Phase 5: Distribute activities across days (interleaved)
            total_activities_input = sum(len(acts) for acts in activities.values())
            # Compute Tier 2 categories: user selections minus scheduled specialists
            scheduled_types = set(activities.keys())
            tier2_cats = [
                c
                for c in (input_data.activity_categories or [])
                if c not in scheduled_types
                and c not in _TIER1_SPECIALIST_NAMES
                and c not in ("general", "local_expert")
            ]
            has_tier2 = bool(tier2_cats)
            days = self._distribute_activities(
                days, activities, merged_constraints, tier2_reserve=has_tier2
            )

            # Phase 5.5: Handle empty days (add FreeDay placeholders)
            days = self._handle_empty_days(days, input_data.tiles, tier2_cats)

            # Phase 5.55: Restore browse tiles explicitly pinned by the user (survive re-runs)
            days = self._restore_pinned_browse_tiles(days, input_data)

            # Phase 5.6: Place LLM-generated experience tiles on free days
            days = self._place_experience_tiles(days, input_data.tiles)

            # Phase 5.25: Populate free days with user-preferred activities
            preferred_acts = self.preferences.preferred_activity_ids if self.preferences else "None"
            _debug_itinerary(
                f"🔍 Phase 5.25 inputs: "
                f"preferences={self.preferences}, "
                f"preferred_activities={preferred_acts}, "
                f"tiles_count={len(input_data.tiles) if input_data.tiles else 0}"
            )
            days, dropped_preferred_count = self._populate_free_days_with_preferences(
                days, input_data.tiles, self.preferences
            )

            # Phase 6: Match tiles to blocks (with preference weighting)
            days = self._match_tiles(days, input_data.tiles, input_data.preferences)

            # Phase 6.5: Tag blocks with inline constraints for frontend display
            days = self._apply_constraints_to_blocks(days)

            # Phase 6.75: FINAL sort - ensure chronological order after ALL phases
            # Critical: Phases 5.5, 5.25, and 6 add blocks AFTER _distribute_activities sort
            days = self._sort_blocks_chronologically(days)
            days = self._annotate_activity_axes(days)

            # Phase 6.8: Final "Free Day" relabel cleanup.
            # Phases 5.6 and 5.25 place activities onto free days and sometimes
            # rename the label inline, but not all code paths trigger the rename.
            # This pass catches any day still labeled "Free Day" that actually
            # has non-buffer, non-placeholder activity blocks.
            _NON_ACTIVITY_TYPES = frozenset(
                {
                    "free_day",
                    "check-in",
                    "check-out",
                    "check_in",
                    "check_out",
                    "arrival",
                    "departure",
                    "rest_day",
                    "buffer",
                    "decompression_buffer",
                }
            )
            for day in days:
                if day.label != "Free Day":
                    continue
                real_activities = [
                    b
                    for b in day.blocks
                    if not b.is_buffer and b.activity_type not in _NON_ACTIVITY_TYPES
                ]
                if real_activities:
                    # Derive label from the dominant specialist category, or
                    # fall back to "Day N".
                    specialist_types = [
                        b.specialist_type
                        for b in real_activities
                        if b.specialist_type
                        and b.specialist_type not in ("general", "local_expert")
                    ]
                    if specialist_types:
                        # Use the most common specialist type
                        dominant = max(set(specialist_types), key=specialist_types.count)
                        day.label = f"{dominant.replace('_', ' ').title()} Day"
                    else:
                        # Restore arrival/departure labels for boundary days
                        if day.day_number == 1 and any(
                            b.activity_type in ("arrival", "departure") for b in day.blocks
                        ):
                            day.label = "Arrival Day"
                        elif day.day_number == len(days) and any(
                            b.activity_type in ("arrival", "departure") for b in day.blocks
                        ):
                            day.label = "Departure Day"
                        else:
                            day.label = f"Day {day.day_number}"
                    # Also remove the free_day placeholder block if it's still present
                    day.blocks = [b for b in day.blocks if b.activity_type != "free_day"]
                    _debug_itinerary(
                        f"🏷️ Phase 6.8: Relabeled Day {day.day_number} "
                        f"from 'Free Day' to '{day.label}'"
                    )

            # Final dedup: remove same-title activity duplicates within each day.
            # Prefers user_preferred blocks over auto-placed ones.
            for day in days:
                seen_titles: dict[str, int] = {}
                to_remove: list[int] = []
                for i, block in enumerate(day.blocks):
                    if block.is_buffer or block.activity_type in (
                        "free_day",
                        "check-in",
                        "check-out",
                        "check_in",
                        "check_out",
                        "arrival",
                        "departure",
                    ):
                        continue
                    key = _normalize_title_key(block.summary)
                    if not key:
                        continue
                    if key in seen_titles:
                        prev_idx = seen_titles[key]
                        prev_block = day.blocks[prev_idx]
                        # Keep the user-preferred version, drop the other
                        if (
                            getattr(block, "preference_status", None) == "user_preferred"
                            and getattr(prev_block, "preference_status", None) != "user_preferred"
                        ):
                            to_remove.append(prev_idx)
                            seen_titles[key] = i
                        else:
                            to_remove.append(i)
                    else:
                        seen_titles[key] = i
                if to_remove:
                    removed_titles = [day.blocks[i].summary for i in to_remove]
                    day.blocks = [b for i, b in enumerate(day.blocks) if i not in set(to_remove)]
                    _debug_itinerary(
                        f"🧹 Final dedup Day {day.day_number}: removed {len(removed_titles)} "
                        f"duplicates: {removed_titles}"
                    )

            # Display floor: guarantee deeplink + image on every activity block
            # Runs AFTER all block-producing phases so no path is missed.
            for day in days:
                for block in day.blocks:
                    _ensure_block_display_floor(block, self.destination)

            # Phase 7: Detect post-placement conflicts (overflow)
            conflicts = self._detect_temporal_conflicts(days)
            if conflicts:
                resolutions = self._generate_resolutions(conflicts, len(days))
                # For now, still return success but include warnings
                # In future, could block if severity is BLOCKING

            # Compute overview
            overview = self._compute_overview(days)
            assumptions = self._compute_assumptions(days, merged_constraints)

            _debug_itinerary(
                f"✅ Success: generated {len(days)} day cards with "
                f"{sum(len(d.blocks) for d in days)} total blocks"
            )
            # Count placed specialist activities (exclude buffers, logistics, free days)
            _LOGISTICS_TYPES = {
                "arrival",
                "departure",
                "check_in",
                "check_out",
                "check-in",
                "check-out",
                "free_day",
                "rest_day",
                "buffer",
                "decompression_buffer",
            }
            total_activities_placed = sum(
                1
                for d in days
                for b in d.blocks
                if not b.is_buffer and b.activity_type not in _LOGISTICS_TYPES
            )
            return ItineraryResult(
                success=True,
                day_cards=days,
                overview=overview,
                assumptions=assumptions,
                conflicts=conflicts,
                resolutions=[],
                dropped_preferred_count=dropped_preferred_count,
                warnings=self._warnings,
                total_activities_input=total_activities_input,
                total_activities_placed=total_activities_placed,
            )

        except Exception as e:
            logger.exception(f"[ItineraryBuilder] Exception during build: {e}")
            return ItineraryResult(
                success=False,
                error=f"Itinerary generation failed: {str(e)}",
            )

    # =========================================================================
    # Phase 1: Day Skeleton
    # =========================================================================

    def _create_day_skeleton(self, start: date, end: date) -> List[DayCardOutput]:
        """Create empty day cards for trip duration."""
        duration = (end - start).days + 1
        days = []

        for i in range(duration):
            day_num = i + 1
            day_date = start + timedelta(days=i)

            # Default labels
            if day_num == 1:
                label = "Arrival Day"
                subtitle = "Travel day — settle in"
            elif day_num == duration:
                label = "Departure Day"
                subtitle = "Safe travels home"
            else:
                label = f"Day {day_num}"
                subtitle = None

            days.append(
                DayCardOutput(
                    day_number=day_num,
                    date=day_date.isoformat(),
                    label=label,
                    subtitle=subtitle,
                    blocks=[],
                )
            )

        return days

    # =========================================================================
    # Phase 2: Extract Specialist Content
    # =========================================================================

    def _extract_specialist_content(
        self, strategy_sections: List[Dict[str, Any]]
    ) -> Tuple[Dict[str, List[ActivityBlock]], List[Dict[str, Any]]]:
        """
        Extract activities and constraints from all specialists.

        Returns:
            Tuple of (activities_by_specialist, all_constraints)
        """
        activities_by_specialist: Dict[str, List[ActivityBlock]] = {}
        all_constraints: List[Dict[str, Any]] = []

        for section in strategy_sections:
            specialist_type = section.get("specialist_type", "general")

            # Skip INFEASIBLE specialists - don't add skiing blocks to Bali itinerary
            # Infeasible sections still have content_added (for UI display) but shouldn't
            # contribute to the actual itinerary timeline
            if section.get("feasibility_status") == "infeasible":
                _debug_itinerary(f"⏭️ Phase 2: Skipping {specialist_type} (infeasible)")
                continue

            # Skip general/local_expert for activity extraction
            # (they provide context, not bookable activities)
            if specialist_type in ("general", "local_expert"):
                # Still collect constraints
                constraints = section.get("constraints_applied", [])
                for c in constraints:
                    c["source"] = specialist_type
                all_constraints.extend(constraints)
                continue

            # Extract content_added as activities
            content_added = section.get("content_added", [])
            _debug_itinerary(
                f"📦 Phase 2: {specialist_type} has {len(content_added)} content_added items"
            )
            activities = []

            for content in content_added:
                # Skip buffer blocks - handled separately
                if content.get("is_buffer", False):
                    continue

                activity = ActivityBlock(
                    title=content.get("title", "Activity"),
                    description=content.get("description", ""),
                    specialist_type=specialist_type,
                    day=content.get("day"),
                    duration_hours=content.get("duration_hours", 3.0),
                    intensity=content.get("intensity"),
                    image_url=content.get("image_url"),
                    coordinates=content.get("coordinates"),
                    tile_id=content.get("tile_id"),
                    rating=content.get("rating"),
                    user_ratings_count=content.get("user_ratings_count"),
                    price_level=(
                        content.get("price_level")
                        if content.get("price_level") is not None
                        else _price_estimate_to_level(content.get("price_estimate"))
                    ),
                    google_place_id=content.get("google_place_id"),
                    deeplink=content.get("deeplink"),
                )
                activities.append(activity)

            if activities:
                activities_by_specialist[specialist_type] = activities

            # Collect constraints
            constraints = section.get("constraints_applied", [])
            for c in constraints:
                c["source"] = specialist_type
            all_constraints.extend(constraints)

        # Log extraction results
        total_activities = sum(len(acts) for acts in activities_by_specialist.values())
        _debug(
            f"[ItineraryBuilder] Extracted: activities={total_activities} from "
            f"{list(activities_by_specialist.keys())}, constraints={len(all_constraints)}"
        )

        return activities_by_specialist, all_constraints

    def _enrich_activities_from_tiles(
        self,
        activities_by_specialist: Dict[str, List[ActivityBlock]],
        tiles: Dict[str, Any],
    ) -> Dict[str, List[ActivityBlock]]:
        """Phase 2.5: Cross-reference specialist content_added activities with
        search_tiles results to inherit Google Places data (rating, coordinates,
        photo, price, deeplink).

        Matching strategy: normalized title exact match.  Both sources describe
        the same well-known venues (e.g. "Roman Forum") so this is sufficient.

        Also stores ``_matched_tile`` on enriched activities so Phase 5 block
        construction can set ``booked_tile`` for frontend photo resolution.
        """
        # Build lookup from activity tiles: normalized_title → tile dict
        activity_tiles = [
            t for t in tiles.values() if isinstance(t, dict) and t.get("type") == "activity"
        ]
        if not activity_tiles:
            return activities_by_specialist

        # ID-based lookup (Priority 1: direct match for specialist tiles)
        tile_by_id: Dict[str, Dict[str, Any]] = {t["id"]: t for t in activity_tiles if t.get("id")}

        # Title-based lookup (Priority 2: fallback for experience tiles)
        tile_by_title: Dict[str, Dict[str, Any]] = {}
        for tile in activity_tiles:
            key = _normalize_title_key(tile.get("title"))
            if key and key not in tile_by_title:
                tile_by_title[key] = tile

        enriched_count = 0
        for _specialist, activities in activities_by_specialist.items():
            for activity in activities:
                tile = None
                # Priority 1: direct ID match (specialist tiles with tile_id)
                if activity.tile_id:
                    tile = tile_by_id.get(activity.tile_id)
                # Priority 2: title-based match
                if tile is None:
                    key = _normalize_title_key(activity.title)
                    tile = tile_by_title.get(key)
                if tile is None:
                    continue

                # Store matched tile for Phase 5 booked_tile assignment
                activity._matched_tile = tile  # type: ignore[attr-defined]

                # Skip field-by-field enrichment if already linked (specialist tiles
                # are created from the same content_added — copying is a no-op).
                if activity.tile_id and activity.tile_id == tile.get("id"):
                    if activity.image_url is None and tile.get("image_url"):
                        activity.image_url = tile["image_url"]
                    if activity.rating is None and tile.get("rating") is not None:
                        activity.rating = tile["rating"]
                    if activity.user_ratings_count is None and tile.get("review_count") is not None:
                        activity.user_ratings_count = tile["review_count"]
                    # Viator override: affiliate deeplinks/images/ratings always win
                    if tile.get("provider") == "viator":
                        vt_dl = tile.get("deeplink") or tile.get("deeplink_url")
                        if vt_dl:
                            activity.deeplink = vt_dl
                        vt_img = tile.get("image_url")
                        if vt_img:
                            activity.image_url = vt_img
                        if tile.get("rating") is not None:
                            activity.rating = tile["rating"]
                        if tile.get("review_count") is not None:
                            activity.user_ratings_count = tile["review_count"]
                    enriched_count += 1
                    continue

                meta = tile.get("meta") or {}
                geo = tile.get("geo") or {}

                if activity.rating is None and tile.get("rating") is not None:
                    activity.rating = tile["rating"]

                if activity.user_ratings_count is None:
                    activity.user_ratings_count = tile.get("review_count") or tile.get(
                        "user_ratings_count"
                    )

                if activity.price_level is None:
                    pl = meta.get("price_level") or tile.get("price_level")
                    if pl is not None:
                        activity.price_level = pl
                    elif tile.get("price_estimate") is not None:
                        activity.price_level = _price_estimate_to_level(tile["price_estimate"])

                if activity.coordinates is None:
                    if (
                        isinstance(geo, dict)
                        and geo.get("lat") is not None
                        and geo.get("lng") is not None
                    ):
                        activity.coordinates = [geo["lng"], geo["lat"]]

                if activity.google_place_id is None:
                    activity.google_place_id = meta.get("place_id") or tile.get("google_place_id")

                tile_deeplink = tile.get("deeplink") or tile.get("deeplink_url")
                if tile_deeplink and (
                    activity.deeplink is None or tile.get("provider") == "viator"
                ):
                    activity.deeplink = tile_deeplink

                tile_image = tile.get("image_url")
                if tile_image and (activity.image_url is None or tile.get("provider") == "viator"):
                    activity.image_url = tile_image

                if activity.tile_id is None:
                    activity.tile_id = tile.get("id")

                enriched_count += 1

        if enriched_count > 0:
            total = sum(len(a) for a in activities_by_specialist.values())
            _debug_itinerary(
                f"🔗 Phase 2.5: Enriched {enriched_count}/{total} activities from tiles"
            )

        return activities_by_specialist

    def _merge_constraints(self, constraints: List[Dict[str, Any]]) -> List[MergedConstraint]:
        """Merge constraints from all specialists with priority."""
        merged = []

        for c in constraints:
            rule = c.get("rule", "")
            raw_severity = c.get("severity")
            if isinstance(raw_severity, ConstraintSeverity):
                severity = raw_severity
            elif isinstance(raw_severity, str):
                try:
                    severity = ConstraintSeverity(raw_severity.lower())
                except ValueError:
                    severity = CONSTRAINT_SEVERITY_MAP.get(rule, ConstraintSeverity.STRONG)
            else:
                severity = CONSTRAINT_SEVERITY_MAP.get(rule, ConstraintSeverity.STRONG)

            merged.append(
                MergedConstraint(
                    source=c.get("source", "unknown"),
                    rule=rule,
                    severity=severity,
                    blocks_day=rule in BLOCKING_RULES,
                    parameters=c.get("parameters", {}),
                    reason=c.get("reason"),
                )
            )

        # Sort by severity (BLOCKING first, then STRONG, then SOFT)
        severity_order = {
            ConstraintSeverity.BLOCKING: 0,
            ConstraintSeverity.STRONG: 1,
            ConstraintSeverity.SOFT: 2,
        }
        merged.sort(key=lambda c: severity_order[c.severity])

        return merged

    # =========================================================================
    # Phase 2b: Early BuilderConflict Detection + Partial Schedule
    # =========================================================================

    def _detect_early_conflicts(
        self,
        days: List[DayCardOutput],
        activities_by_specialist: Dict[str, List[ActivityBlock]],
        constraints: List[MergedConstraint],
        tiles: Dict[str, Any],
        origin: Optional[str],
    ) -> Tuple[List[BuilderConflict], List[DayCardOutput]]:
        """
        Detect conflicts before placement that are irreconcilable.

        NEW: Returns partial schedule showing what CAN be scheduled,
        with unschedulable activities marked.

        Returns:
            Tuple of (conflicts, partial_days) where partial_days is
            a schedule with schedulable activities placed and
            unschedulable activities marked with unschedulable=True.
        """
        conflicts = []
        partial_days: List[DayCardOutput] = []
        total_days = len(days)

        # Trace incoming constraints for debugging
        _debug(f"[ItineraryBuilder] _detect_early_conflicts: {len(constraints)} merged constraints")
        for c in constraints:
            _debug(f"[ItineraryBuilder] Constraint: rule={c.rule} severity={c.severity}")

        # Calculate required days for each specialist
        total_activity_days = 0
        buffer_days = 0

        for _specialist, activities in activities_by_specialist.items():
            total_activity_days += len(activities)

        # Check for diving no-fly buffer (with alias support)
        nofly_constraint = _find_constraint(constraints, "min_24h_buffer_after_dive")
        if nofly_constraint:
            buffer_days = get_nofly_buffer_days("diving")
            self._nofly_buffer_days = buffer_days
            _debug(f"[ItineraryBuilder] No-fly constraint found: rule={nofly_constraint.rule}")

        # Cross-domain check: diving + high-altitude activity conflict
        diving_present = "diving" in activities_by_specialist
        # Altitude specialists derived from diving's cross-domain blocks in specialist_registry
        altitude_activities = get_cross_domain_target_specialists("diving")
        altitude_specialists_present = [
            spec for spec in altitude_activities if spec in activities_by_specialist
        ]

        days_shortfall = 0
        cross_domain_conflict = False
        if diving_present and altitude_specialists_present:
            # Check for no_altitude_after_dive constraint (with alias support)
            _debug(
                f"[ItineraryBuilder] Cross-domain check: diving={diving_present} "
                f"altitude_specialists={altitude_specialists_present}"
            )
            altitude_constraint = _find_constraint(constraints, "no_altitude_after_dive")
            alt_msg = (
                f"FOUND (rule={altitude_constraint.rule})" if altitude_constraint else "NOT FOUND"
            )
            _debug(f"[ItineraryBuilder] no_altitude_after_dive constraint: {alt_msg}")

            if altitude_constraint:
                # Need additional buffer day between diving and high-altitude activities
                diving_days = len(activities_by_specialist.get("diving", []))
                altitude_days = sum(
                    len(activities_by_specialist.get(spec, [])) for spec in altitude_activities
                )
                # Buffer days derived from diving's cross-domain constraint in registry
                altitude_buffer = get_cross_domain_buffer_days("diving")

                # Arrival + departure are partially usable (0.4 day each)
                usable_days = max(0, total_days - 2) + 0.8

                # Calculate required days for diving + buffer + altitude activities
                required_for_combo = diving_days + altitude_buffer + altitude_days
                if required_for_combo > usable_days:
                    # Can we fit by trimming? Available slots after buffer:
                    available_after_buffer = usable_days - altitude_buffer

                    if available_after_buffer < 2:
                        # Can't fit even 1 dive + 1 hike — REAL conflict
                        cross_domain_conflict = True
                        days_shortfall = required_for_combo - usable_days
                        conflicts.append(
                            BuilderConflict(
                                type="constraint_clash",
                                severity=ConstraintSeverity.BLOCKING,
                                specialists=["diving"] + altitude_specialists_present,
                                message=(
                                    f"Cannot fit diving + 24h buffer + altitude activities "
                                    f"in {usable_days} activity days. "
                                    f"Need at least 4 days total."
                                ),
                            )
                        )
                    else:
                        # Trim activities to fit — split evenly, diving gets remainder
                        dive_slots = int((available_after_buffer + 1) // 2)
                        altitude_slots = int(available_after_buffer - dive_slots)

                        if diving_days > dive_slots:
                            logger.info(
                                f"[ITINERARY] Cross-domain trim: "
                                f"diving {diving_days} -> {dive_slots}"
                            )
                            activities_by_specialist["diving"] = activities_by_specialist["diving"][
                                :dive_slots
                            ]

                        for spec in altitude_specialists_present:
                            acts = activities_by_specialist.get(spec, [])
                            if len(acts) > altitude_slots:
                                logger.info(
                                    f"[ITINERARY] Cross-domain trim: "
                                    f"{spec} {len(acts)} -> {altitude_slots}"
                                )
                                activities_by_specialist[spec] = acts[:altitude_slots]

                        self._warnings.append(
                            f"Adjusted to {dive_slots} dive(s) + "
                            f"{altitude_slots} hike(s) to fit your trip "
                            f"with the 24h safety buffer."
                        )

        # Arrival + departure are partially usable (0.4 day each)
        usable_days = max(0, total_days - 2) + 0.8

        # FIX: No-fly buffer only affects DIVING placement, not total capacity
        # Day 7 can still have hiking even though diving is blocked
        diving_activities = activities_by_specialist.get("diving", [])
        diving_slots = int(usable_days - buffer_days) if nofly_constraint else int(usable_days)

        # Auto-truncate diving activities to fit available slots (no conflict)
        if len(diving_activities) > diving_slots:
            original_count = len(diving_activities)
            activities_by_specialist["diving"] = diving_activities[:diving_slots]
            logger.info(
                f"[ITINERARY] ⚠️ Auto-reduced diving: {original_count} → {diving_slots} "
                f"(no-fly buffer requires finishing by day {total_days - 1})"
            )
            # Track warning for user display
            if diving_slots <= 0:
                self._warnings.append(
                    f"Diving isn't possible on a {total_days}-day trip "
                    f"due to the 24h no-fly buffer. Consider extending to 4+ days."
                )
            else:
                self._warnings.append(
                    f"Adjusted to {diving_slots} dive{'s' if diving_slots > 1 else ''} to fit your "
                    f"{total_days}-day trip (24h no-fly buffer maintained)."
                )

        # Auto-truncate if total activities exceed capacity
        # Recalculate total after diving truncation
        total_activity_days = sum(len(acts) for acts in activities_by_specialist.values())
        max_capacity = int(usable_days * min(MAX_BLOCKS_PER_DAY, self._activities_per_day))
        if total_activity_days > max_capacity:
            excess = total_activity_days - max_capacity
            logger.info(
                f"[ITINERARY] ⚠️ Auto-reducing activities: {total_activity_days} → {max_capacity} "
                f"(trimming {excess} activities to fit {usable_days} days)"
            )
            # Trim proportionally from each specialist (skip diving - already handled)
            for specialist, acts in activities_by_specialist.items():
                if specialist == "diving" or len(acts) == 0:
                    continue
                # Calculate how many to keep (proportional to capacity)
                keep_ratio = max_capacity / total_activity_days
                keep_count = max(1, int(len(acts) * keep_ratio))
                if keep_count < len(acts):
                    activities_by_specialist[specialist] = acts[:keep_count]

        # Build partial schedule if conflicts detected
        if conflicts:
            partial_days = self._build_partial_schedule(
                days=days,
                activities_by_specialist=activities_by_specialist,
                constraints=constraints,
                tiles=tiles,
                origin=origin,
                cross_domain_conflict=cross_domain_conflict,
                diving_present=diving_present,
                days_shortfall=days_shortfall,
            )

        return conflicts, partial_days

    def _build_partial_schedule(
        self,
        days: List[DayCardOutput],
        activities_by_specialist: Dict[str, List[ActivityBlock]],
        constraints: List[MergedConstraint],
        tiles: Dict[str, Any],
        origin: Optional[str],
        cross_domain_conflict: bool,
        diving_present: bool,
        days_shortfall: int = 0,
    ) -> List[DayCardOutput]:
        """
        Build partial timeline with schedulable activities + unschedulable markers.

        Strategy:
        - If cross-domain conflict (diving + altitude), schedule diving first
        - Mark altitude activities as unschedulable with reason
        - Always include arrival/departure anchors
        """
        import copy

        # Make a copy of days to avoid mutating original
        partial_days = copy.deepcopy(days)

        # Place anchors (arrival/departure)
        partial_days = self._place_anchors(partial_days, tiles, origin)

        # Inject safety buffers
        partial_days = self._inject_safety_buffers(partial_days, constraints)

        # Determine primary specialist (priority: diving > hiking > skiing > other)
        primary_specialist = None
        # Altitude specialists derived from diving's cross-domain blocks in specialist_registry
        altitude_activities = get_cross_domain_target_specialists("diving")

        if cross_domain_conflict and diving_present:
            # Diving takes priority in cross-domain conflicts
            primary_specialist = "diving"
        elif activities_by_specialist:
            # Pick first specialist with activities
            primary_specialist = next(iter(activities_by_specialist.keys()))

        # Schedule primary specialist activities
        if primary_specialist and primary_specialist in activities_by_specialist:
            primary_activities = {primary_specialist: activities_by_specialist[primary_specialist]}
            partial_days = self._distribute_activities(partial_days, primary_activities)

        # Mark other specialists as unschedulable
        for specialist, activities in activities_by_specialist.items():
            if specialist == primary_specialist:
                continue

            # Determine reason based on conflict type
            if cross_domain_conflict and specialist in altitude_activities:
                reason = f"Requires 24h buffer after diving - extend trip to include {specialist}"
            else:
                reason = f"Insufficient days to schedule {specialist} activities"

            # Add unschedulable blocks to the partial schedule
            for activity in activities:
                unschedulable_block = DayBlockOutput(
                    id=f"unschedulable_{specialist}_{activity.title[:15].replace(' ', '_')}",
                    period="afternoon",
                    activity_type=specialist,
                    summary=activity.title,
                    specialist_type=specialist,
                    is_buffer=False,
                    intensity=activity.intensity,
                    image_url=activity.image_url,
                    rating=activity.rating,
                    review_count=activity.user_ratings_count,
                    price_level=activity.price_level,
                    google_place_id=activity.google_place_id,
                    deeplink=activity.deeplink,
                    unschedulable=True,
                    unschedulable_reason=reason,
                    unschedulable_days_needed=(
                        math.ceil(days_shortfall) if days_shortfall > 0 else len(activities)
                    ),
                )
                # Add to second-to-last day (before departure)
                if len(partial_days) >= 2:
                    partial_days[-2].blocks.append(unschedulable_block)

        return partial_days

    # =========================================================================
    # Phase 3: Anchor Placement
    # =========================================================================

    def _place_anchors(
        self,
        days: List[DayCardOutput],
        tiles: Dict[str, Any],
        origin: Optional[str],
    ) -> List[DayCardOutput]:
        """Place arrival/departure blocks based on flight tiles.

        Prioritizes user-preferred flights over heuristic selection.
        """
        if not days:
            return days

        # Collect all flight tiles with preference info
        flight_tiles = []
        for tile_id, tile in tiles.items():
            if not isinstance(tile, dict):
                continue
            if tile.get("type") != "flight":
                continue
            is_preferred = bool(self.preferences and self.preferences.is_flight_preferred(tile_id))
            flight_tiles.append(
                {
                    "tile_id": tile_id,
                    "tile": tile,
                    "is_preferred": is_preferred,
                }
            )

        # Sort by preference (preferred first)
        flight_tiles.sort(key=lambda x: -x["is_preferred"])

        # Find inbound/outbound from preferred flights first, then fallback to heuristics
        inbound_flight = None
        outbound_flight = None

        # Separate preferred and non-preferred flights
        preferred_flights = [ft["tile"] for ft in flight_tiles if ft["is_preferred"]]
        non_preferred_flights = [ft["tile"] for ft in flight_tiles if not ft["is_preferred"]]

        # If user has preferred flights, use them (round-trip assumption: same tile for both legs)
        if preferred_flights:
            # Use first preferred flight for inbound
            inbound_flight = preferred_flights[0]
            # Use second preferred flight for outbound if available,
            # otherwise same flight (round-trip)
            outbound_flight = (
                preferred_flights[1] if len(preferred_flights) > 1 else preferred_flights[0]
            )
        else:
            # No preferred flights - use heuristics
            for tile in non_preferred_flights:
                title = tile.get("title", "").lower()

                if "inbound" in title or "arrival" in title:
                    if not inbound_flight:
                        inbound_flight = tile
                elif "outbound" in title or "departure" in title:
                    if not outbound_flight:
                        outbound_flight = tile
                elif origin and origin.lower() in title:
                    if not inbound_flight:
                        inbound_flight = tile
                else:
                    # Default: first flight is inbound, second is outbound
                    if not inbound_flight:
                        inbound_flight = tile
                    elif not outbound_flight:
                        outbound_flight = tile

            # If only one flight found, use it for both (round-trip)
            if inbound_flight and not outbound_flight:
                outbound_flight = inbound_flight
            elif outbound_flight and not inbound_flight:
                inbound_flight = outbound_flight

        # Day 1: Arrival
        if len(days) > 0:
            arrival_block = DayBlockOutput(
                id="arrival_001",
                period="morning",
                activity_type="arrival",
                summary="Arrive at destination",
                is_buffer=True,
                buffer_type="arrival",
                requires_booking=True,
                booking_category="flight",
            )

            if inbound_flight:
                arrival_block.scheduled_time = inbound_flight.get("meta", {}).get(
                    "arrival_time", ""
                )
                arrival_block.logistics_details = inbound_flight.get("subtitle", "")
                arrival_block.booked_tile = inbound_flight

            days[0].blocks.insert(0, arrival_block)

        # Last day: Departure
        if len(days) > 0:
            departure_block = DayBlockOutput(
                id="departure_001",
                period="evening",
                activity_type="departure",
                summary="Depart for home",
                is_buffer=True,
                buffer_type="departure",
                requires_booking=True,
                booking_category="flight",
            )

            if outbound_flight:
                departure_block.scheduled_time = outbound_flight.get("meta", {}).get(
                    "departure_time", ""
                )
                departure_block.logistics_details = outbound_flight.get("subtitle", "")
                departure_block.booked_tile = outbound_flight

            days[-1].blocks.append(departure_block)

        return days

    # =========================================================================
    # Phase 4: Safety Buffer Injection
    # =========================================================================

    def _inject_safety_buffers(
        self,
        days: List[DayCardOutput],
        constraints: List[MergedConstraint],
        activities_by_specialist: Optional[Dict[str, Any]] = None,
    ) -> List[DayCardOutput]:
        """Inject safety buffers based on constraints (sorted by priority)."""
        for constraint in constraints:
            if constraint.rule == "min_24h_buffer_after_dive":
                # No-fly buffer is now shown as INLINE CONSTRAINT on the last dive activity
                # (see _apply_constraints_to_blocks) instead of a standalone "No-Fly Day" card.
                # This keeps the timeline cleaner while still communicating the safety rule.
                _debug("[ItineraryBuilder] Diving no-fly constraint tracked (inline display)")
                pass  # Constraint visibility handled by inline badges

            elif constraint.rule == "altitude_acclimatization":
                # Acclimatization before the first altitude-activity day.
                # Find the first day with hiking/climbing/skiing blocks,
                # then place the buffer on the day before it (or fallback to first free day).
                altitude_specialists = {"hiking", "trekking", "climbing", "skiing"}
                diving_specialists = {"diving", "scuba", "freediving"}

                # Only insert acclimatization when the specialist LLM explicitly flags
                # it as required (i.e., the destination actually reaches altitude thresholds).
                # The constraint fires from the hardcoded registry for ALL hiking/climbing,
                # but Mount Batur (1717m) and similar sub-3000m destinations don't qualify.
                #
                # Signal: the specialist LLM sets requires_acclimatization=True in parameters.
                # The hardcoded registry reason ("Max 500m elevation gain per day above 3000m")
                # is a generic rule description, NOT a destination-specific elevation signal —
                # do NOT use reason text as a trigger.
                params = constraint.parameters or {}
                if not params.get("requires_acclimatization", False):
                    _debug(
                        "[ItineraryBuilder] Skipping altitude_acclimatization: "
                        "requires_acclimatization not set in constraint parameters"
                    )
                    continue

                # Skip acclimatization entirely on cross-domain trips that include diving:
                # the cross-domain rest day already provides the required buffer,
                # and inserting a second buffer creates conflicting content on dive days.
                # NOTE 1: check activities_by_specialist (Phase 3 input), not days[].blocks,
                # because Phase 4 (this method) runs before Phase 5 places specialist blocks.
                # NOTE 2: also check constraint sources — if diving has no content_added
                # (e.g., tiles-only mode), it won't appear in activities_by_specialist
                # but its constraints will still be in merged_constraints.
                active_specialists = (
                    set(activities_by_specialist.keys()) if activities_by_specialist else set()
                )
                constraint_sources = {c.source for c in constraints}
                has_diving = bool((active_specialists | constraint_sources) & diving_specialists)
                if has_diving:
                    _debug(
                        "[ItineraryBuilder] Skipping altitude_acclimatization: "
                        "cross-domain trip with diving"
                    )
                    continue

                # Derive the specialist_type from the triggering altitude activities
                # so the buffer block reflects the actual domain (hiking, skiing, etc.)
                triggering_specialist = next(
                    (s for s in altitude_specialists if s in active_specialists),
                    "hiking",  # safe fallback — this branch only runs for altitude-only trips
                )

                accl_day_idx = None
                for i in range(1, len(days) - 1):  # skip arrival/departure
                    has_altitude = any(
                        (getattr(b, "specialist_type", "") or "").lower() in altitude_specialists
                        for b in days[i].blocks
                        if not getattr(b, "is_buffer", False)
                    )
                    if has_altitude:
                        # Place acclimatization on the day before, minimum day 1.
                        # If i == 1 (altitude is on first interior day), candidate == i and the
                        # while-loop never executes — falls through to fallback below.
                        candidate = max(1, i - 1)
                        # Slide forward to avoid days that already have specialist blocks
                        while candidate < i:
                            day_specialist_types = {
                                (getattr(b, "specialist_type", "") or "").lower()
                                for b in days[candidate].blocks
                                if not getattr(b, "is_buffer", False)
                                and (getattr(b, "specialist_type", "") or "") != ""
                            }
                            if not day_specialist_types:
                                break  # Day is free — safe to use
                            candidate += 1
                        if candidate < i:
                            accl_day_idx = candidate
                        break

                if accl_day_idx is None and len(days) >= 4:
                    # Fallback: find first interior day with no specialist blocks.
                    # Guard requires >= 4 days: on a 3-day trip the only interior day
                    # already holds the altitude block — placing acclimatization there
                    # would be incorrect, so we suppress it.
                    for j in range(1, len(days) - 1):
                        day_specialist_types = {
                            (getattr(b, "specialist_type", "") or "").lower()
                            for b in days[j].blocks
                            if not getattr(b, "is_buffer", False)
                            and (getattr(b, "specialist_type", "") or "") != ""
                        }
                        if not day_specialist_types:
                            accl_day_idx = j
                            break

                if accl_day_idx is not None:
                    days[accl_day_idx].label = "Acclimatization Day"

                    # Remove strenuous activities
                    days[accl_day_idx].blocks = [
                        b for b in days[accl_day_idx].blocks if b.intensity != "challenging"
                    ]

                    buffer_block = DayBlockOutput(
                        id=f"buffer_accl_{accl_day_idx}",
                        period="morning",
                        activity_type="rest",
                        summary="Altitude adjustment - light activities only",
                        is_buffer=True,
                        buffer_type="acclimatization",
                        buffer_reason="Max 500m elevation gain per day above 3000m",
                        specialist_type=triggering_specialist,
                        intensity="light",
                    )
                    days[accl_day_idx].blocks.insert(0, buffer_block)
                    days[accl_day_idx].subtitle = buffer_block.buffer_reason

        return days

    # =========================================================================
    # Phase 5: Activity Distribution
    # =========================================================================

    def _distribute_activities(
        self,
        days: List[DayCardOutput],
        activities_by_specialist: Dict[str, List[ActivityBlock]],
        constraints: Optional[List["MergedConstraint"]] = None,
        tier2_reserve: bool = False,
    ) -> List[DayCardOutput]:
        """
        Distribute activities from multiple specialists across days.

        Strategy:
        1. Calculate available slots per day (respecting buffers)
        2. Weight and sort activities by user preference (preferred first)
        3. If cross-domain constraints exist (dive+altitude), cluster activities
        4. Otherwise alternate between specialists for variety
        5. Respect max activities per day (2-3)
        """
        if not activities_by_specialist:
            return days

        # Get available days (exclude buffer days that block all activities)
        available_day_indices = []

        for i, day in enumerate(days):
            # Skip only 1-day trips where arrival AND departure are the same day
            if i == 0 and i == len(days) - 1:
                continue
            # Skip days with blocking buffers
            has_blocking_buffer = any(b.is_buffer and b.buffer_type == "no_fly" for b in day.blocks)
            if not has_blocking_buffer:
                available_day_indices.append(i)

        if not available_day_indices:
            return days

        # Weight activities by preference before distribution
        # Preferred activities get placed first (higher priority)
        for specialist, activities in activities_by_specialist.items():
            for activity in activities:
                activity_id = self._normalize_activity_id(activity)
                is_preferred = bool(
                    self.preferences and self.preferences.is_activity_preferred(activity_id)
                )
                # Store preference state on activity for later use
                activity.is_user_preferred = is_preferred  # type: ignore
                if is_preferred:
                    _debug(f"[ItineraryBuilder] ❤️ Activity '{activity.title}' is user-preferred")

            # Sort activities: preferred first, then by original order
            activities_by_specialist[specialist] = sorted(
                activities,
                key=lambda a: (0 if getattr(a, "is_user_preferred", False) else 1),
            )

        # Flatten and copy activities
        specialists = list(activities_by_specialist.keys())
        remaining = {s: list(acts) for s, acts in activities_by_specialist.items()}

        # ─────────────────────────────────────────────────────────
        # Day preference capping: trim activity lists to user's requested counts
        # e.g., day_preferences={"diving": 3} → keep at most 3 diving activities
        # ─────────────────────────────────────────────────────────
        if self._day_preferences:
            for spec, max_days in self._day_preferences.items():
                if spec in remaining and len(remaining[spec]) > max_days:
                    trimmed = remaining[spec][:max_days]
                    _debug(
                        f"[ItineraryBuilder] Day preference: capped {spec} "
                        f"from {len(remaining[spec])} to {max_days} activities"
                    )
                    remaining[spec] = trimmed

        # ─────────────────────────────────────────────────────────
        # Cross-domain clustering: diving before altitude with buffer
        # ─────────────────────────────────────────────────────────
        altitude_constraint = _find_constraint(constraints or [], "no_altitude_after_dive")
        diving_specialists = {"diving"}
        altitude_specialist_names = {
            "hiking",
            "trekking",
            "mountaineering",
            "skiing",
            "climbing",
        }

        has_diving = any(s in diving_specialists for s in remaining if remaining[s])
        has_altitude = any(s in altitude_specialist_names for s in remaining if remaining[s])

        if altitude_constraint and has_diving and has_altitude:
            _debug("[ItineraryBuilder] 🏔️ Cross-domain clustering: diving → buffer → altitude")
            periods = ["morning", "afternoon", "evening"]
            period_ptr = 0
            slot_ptr = 0  # index into available_day_indices

            # Phase A: Place all diving activities on earliest days
            for spec in list(diving_specialists):
                for activity in remaining.get(spec, []):
                    if slot_ptr >= len(available_day_indices):
                        break
                    day_idx = available_day_indices[slot_ptr]
                    day = days[day_idx]

                    is_user_preferred = getattr(activity, "is_user_preferred", False)
                    preference_status = "user_preferred" if is_user_preferred else None
                    matched_tile = getattr(activity, "_matched_tile", None)
                    block = DayBlockOutput(
                        id=activity.tile_id or f"act_{spec}_{day_idx}_{len(day.blocks)}",
                        period=periods[period_ptr % len(periods)],
                        activity_type=spec,
                        intensity=activity.intensity,
                        summary=activity.title,
                        specialist_type=spec,
                        image_url=activity.image_url,
                        duration=f"{activity.duration_hours}h" if activity.duration_hours else None,
                        constraints=activity.constraints,
                        preference_status=preference_status,
                        rating=activity.rating,
                        review_count=activity.user_ratings_count,
                        price_level=activity.price_level,
                        price_estimate=(matched_tile or {}).get("price_estimate"),
                        google_place_id=activity.google_place_id,
                        deeplink=activity.deeplink,
                        booked_tile=matched_tile,
                        requires_booking=bool(matched_tile),
                        booking_category="activity" if matched_tile else None,
                    )
                    if activity.coordinates:
                        block.coordinates = {
                            "lat": activity.coordinates[1],
                            "lng": activity.coordinates[0],
                        }
                    day.blocks.append(block)
                    period_ptr += 1
                    slot_ptr += 1
                    _debug(
                        f"[ItineraryBuilder] 🤿 Clustered dive "
                        f"'{activity.title}' on Day {day_idx + 1}"
                    )
                remaining.pop(spec, None)

            # Phase B: Skip one day as decompression buffer
            if slot_ptr < len(available_day_indices):
                buffer_day_idx = available_day_indices[slot_ptr]
                buffer_day = days[buffer_day_idx]
                # Only insert rest buffer if the day is empty (Phase 4 may have already placed one)
                has_rest = any(
                    b.is_buffer and b.buffer_type == "rest_day" for b in buffer_day.blocks
                )
                if not has_rest:
                    buffer_day.label = "Rest Day — Decompression before altitude"
                    rest_block = DayBlockOutput(
                        id=f"buffer_cross_domain_{buffer_day_idx}",
                        period="morning",
                        activity_type="rest",
                        summary="Rest day — decompression safety before altitude activities",
                        is_buffer=True,
                        buffer_type="rest_day",
                        buffer_reason="No high-altitude activities within 24h of diving",
                        intensity="light",
                        specialist_type="diving",
                    )
                    buffer_day.blocks.append(rest_block)
                    buffer_day.subtitle = rest_block.buffer_reason
                    _debug(
                        f"[ItineraryBuilder] 🛑 Buffer day on Day "
                        f"{buffer_day_idx + 1} (cross-domain)"
                    )
                slot_ptr += 1

            # Phase C: Place all altitude activities after buffer
            for spec in list(altitude_specialist_names):
                for activity in remaining.get(spec, []):
                    if slot_ptr >= len(available_day_indices):
                        break
                    day_idx = available_day_indices[slot_ptr]
                    day = days[day_idx]

                    is_user_preferred = getattr(activity, "is_user_preferred", False)
                    preference_status = "user_preferred" if is_user_preferred else None
                    matched_tile = getattr(activity, "_matched_tile", None)
                    block = DayBlockOutput(
                        id=activity.tile_id or f"act_{spec}_{day_idx}_{len(day.blocks)}",
                        period=periods[period_ptr % len(periods)],
                        activity_type=spec,
                        intensity=activity.intensity,
                        summary=activity.title,
                        specialist_type=spec,
                        image_url=activity.image_url,
                        duration=f"{activity.duration_hours}h" if activity.duration_hours else None,
                        constraints=activity.constraints,
                        preference_status=preference_status,
                        rating=activity.rating,
                        review_count=activity.user_ratings_count,
                        price_level=activity.price_level,
                        price_estimate=(matched_tile or {}).get("price_estimate"),
                        google_place_id=activity.google_place_id,
                        deeplink=activity.deeplink,
                        booked_tile=matched_tile,
                        requires_booking=bool(matched_tile),
                        booking_category="activity" if matched_tile else None,
                    )
                    if activity.coordinates:
                        block.coordinates = {
                            "lat": activity.coordinates[1],
                            "lng": activity.coordinates[0],
                        }
                    day.blocks.append(block)
                    period_ptr += 1
                    slot_ptr += 1
                    _debug(
                        f"[ItineraryBuilder] 🏔️ Clustered altitude "
                        f"'{activity.title}' on Day {day_idx + 1}"
                    )
                remaining.pop(spec, None)

            # Phase D: Co-schedule remaining specialists onto existing days
            # using capacity-based placement, NOT slot_ptr allocation.
            # Buffer days allow non-altitude specialists (buffer separates
            # dive→altitude, not dive→surf).
            # When Tier 2 categories exist, reserve 1 block + 2h per day
            # so Phase 5.6 (_place_experience_tiles) has room for yoga/nightlife.
            _BUFFER_ACTIVITY_TYPES = {"rest_day", "buffer", "decompression_buffer"}
            _T2_RESERVE_HOURS = 2.0 if tier2_reserve else 0.0
            _T2_RESERVE_BLOCKS = 1 if tier2_reserve else 0
            if tier2_reserve:
                _debug(
                    "[ItineraryBuilder] Phase D: reserving "
                    f"{_T2_RESERVE_HOURS}h + {_T2_RESERVE_BLOCKS} block/day for Tier 2"
                )
            phase_d_placed = 0
            phase_d_unplaced: list[tuple[str, object]] = []

            for spec in list(remaining.keys()):
                for activity in remaining.get(spec, []):
                    activity_hours = activity.duration_hours or 3.0
                    best_day_idx: int | None = None
                    best_score: float = -1.0

                    for candidate_idx in available_day_indices:
                        candidate_day = days[candidate_idx]

                        # Buffer days block altitude specialists only
                        is_buffer_day = (
                            any(
                                b.activity_type in _BUFFER_ACTIVITY_TYPES
                                for b in candidate_day.blocks
                            )
                            or "buffer" in (candidate_day.label or "").lower()
                        )
                        if is_buffer_day and spec in altitude_specialist_names:
                            continue

                        rem_hours, rem_blocks = self._day_remaining_capacity(candidate_day)
                        # Reserve capacity for Tier 2 experience tiles
                        eff_hours = rem_hours - _T2_RESERVE_HOURS
                        eff_blocks = rem_blocks - _T2_RESERVE_BLOCKS
                        if eff_hours < activity_hours or eff_blocks < 1:
                            continue

                        # Max 1 activity per specialist per day
                        spec_count = sum(
                            1
                            for b in candidate_day.blocks
                            if b.specialist_type == spec
                            and b.activity_type not in _BUFFER_ACTIVITY_TYPES
                        )
                        if spec_count >= 1:
                            continue

                        # Score: prefer emptier days, break ties by time slot fit
                        headroom = rem_hours / DAY_CAPACITY_HOURS
                        complement = self._time_slot_score(
                            candidate_day,
                            periods[period_ptr % len(periods)],
                        )
                        score = headroom * 0.6 + complement * 0.4

                        if score > best_score:
                            best_score = score
                            best_day_idx = candidate_idx

                    if best_day_idx is not None:
                        day = days[best_day_idx]
                        is_user_preferred = getattr(activity, "is_user_preferred", False)
                        matched_tile = getattr(activity, "_matched_tile", None)
                        # Dedup period against existing blocks on this day
                        _existing_periods = {b.period for b in day.blocks if b.period}
                        _candidate_period = periods[period_ptr % len(periods)]
                        if _candidate_period in _existing_periods:
                            _candidate_period = next(
                                (p for p in periods if p not in _existing_periods),
                                _candidate_period,
                            )
                        block = DayBlockOutput(
                            id=activity.tile_id or f"act_{spec}_{best_day_idx}_{len(day.blocks)}",
                            period=_candidate_period,
                            activity_type=spec,
                            intensity=activity.intensity,
                            summary=activity.title,
                            specialist_type=spec,
                            image_url=activity.image_url,
                            duration=(f"{activity_hours}h"),
                            constraints=activity.constraints,
                            preference_status=("user_preferred" if is_user_preferred else None),
                            rating=activity.rating,
                            review_count=activity.user_ratings_count,
                            price_level=activity.price_level,
                            price_estimate=(matched_tile or {}).get("price_estimate"),
                            google_place_id=activity.google_place_id,
                            deeplink=activity.deeplink,
                            booked_tile=matched_tile,
                            requires_booking=bool(matched_tile),
                            booking_category="activity" if matched_tile else None,
                        )
                        if activity.coordinates:
                            block.coordinates = {
                                "lat": activity.coordinates[1],
                                "lng": activity.coordinates[0],
                            }
                        day.blocks.append(block)
                        period_ptr += 1
                        phase_d_placed += 1
                        _debug(
                            f"[ItineraryBuilder] Phase D co-scheduled "
                            f"'{activity.title}' ({spec}) on Day {best_day_idx + 1}"
                        )
                    else:
                        phase_d_unplaced.append((spec, activity))
                remaining.pop(spec, None)

            # Re-populate remaining for round-robin fallback
            if phase_d_unplaced:
                _debug(
                    f"[ItineraryBuilder] Phase D: {len(phase_d_unplaced)} "
                    f"activities deferred to round-robin"
                )
                for spec, activity in phase_d_unplaced:
                    remaining.setdefault(spec, []).append(activity)

            _debug(
                f"[ItineraryBuilder] Cross-domain clustering complete: "
                f"placed={phase_d_placed}, deferred={len(phase_d_unplaced)}"
            )

        # Even distribution: spread activities across all available days
        # Strategy: cycle through days, placing 1 activity per day per round
        # This ensures Days 6-7 get activities before Days 2-3 get their 2nd

        # Reserve minimum free days so Phase 5.6 backfill has room.
        # Without this, a 7-day hiking trip fills all 7 days with hikes
        # and backfill (restaurants, temples, spa) has nowhere to go.
        min_free_days = 2 if len(days) >= 5 else (1 if len(days) >= 3 else 0)
        if min_free_days > 0 and len(available_day_indices) > min_free_days:
            round_robin_day_indices = available_day_indices[:-min_free_days]
            _debug(
                f"[ItineraryBuilder] Reserved {min_free_days} free days for backfill "
                f"(specialist days: {len(round_robin_day_indices)}/{len(available_day_indices)})"
            )
        else:
            round_robin_day_indices = available_day_indices

        day_ptr = 0
        specialist_ptr = 0
        periods = ["morning", "afternoon", "evening"]
        period_ptr = 0

        # Safety net: Track specialist count per day to prevent activity cramming
        # Max 1 activity per specialist per day (e.g., 1 dive + 1 hike per day is OK)
        from collections import defaultdict

        specialist_count_per_day: dict = defaultdict(lambda: defaultdict(int))

        max_iterations = 100  # Safety limit
        iteration = 0

        while any(remaining.values()) and iteration < max_iterations:
            iteration += 1

            # Get current day and specialist
            day_idx = round_robin_day_indices[day_ptr % len(round_robin_day_indices)]
            current_day = days[day_idx]
            current_specialist = specialists[specialist_ptr % len(specialists)]

            # No-fly buffer: prevent diving placement too close to departure
            if current_specialist == "diving" and self._nofly_buffer_days > 0:
                departure_idx = len(days) - 1
                latest_dive_idx = departure_idx - 1 - self._nofly_buffer_days
                if day_idx > latest_dive_idx:
                    # Wrap to earlier day — retry same dive, don't skip it
                    day_ptr = (day_ptr + 1) % len(round_robin_day_indices)
                    dive_wrap_attempts = getattr(self, "_dive_wrap_attempts", 0) + 1
                    self._dive_wrap_attempts = dive_wrap_attempts
                    if dive_wrap_attempts >= len(round_robin_day_indices):
                        # All valid days exhausted for diving — skip this activity
                        specialist_ptr += 1
                        self._dive_wrap_attempts = 0
                    continue

            # Check if day is truly full (respect user's activities-per-day preference)
            non_buffer_blocks = [b for b in current_day.blocks if not b.is_buffer]
            max_for_day = min(MAX_BLOCKS_PER_DAY, self._activities_per_day)
            if len(non_buffer_blocks) >= max_for_day:
                day_ptr += 1
                if day_ptr >= len(round_robin_day_indices):
                    day_ptr = 0
                    # If we've cycled through all days and all are full, break
                    if not any(remaining.values()):
                        break
                continue

            # Safety net: Max 1 activity per specialist per day
            # Skip if this specialist already has an activity on this day
            if specialist_count_per_day[day_idx][current_specialist] >= 1:
                # Move to next day for this specialist
                day_ptr += 1
                continue

            # Get next activity from current specialist
            activities = remaining.get(current_specialist, [])
            if activities:
                activity = activities.pop(0)

                # Determine preference status for attribution badge
                is_user_preferred = getattr(activity, "is_user_preferred", False)
                preference_status = "user_preferred" if is_user_preferred else None
                matched_tile = getattr(activity, "_matched_tile", None)

                # Create block with preference attribution
                block = DayBlockOutput(
                    id=activity.tile_id
                    or f"act_{current_specialist}_{day_idx}_{len(current_day.blocks)}",
                    period=periods[period_ptr % len(periods)],
                    activity_type=current_specialist,
                    intensity=activity.intensity,
                    summary=activity.title,
                    specialist_type=current_specialist,
                    image_url=activity.image_url,
                    duration=f"{activity.duration_hours}h" if activity.duration_hours else None,
                    constraints=activity.constraints,
                    # Preference attribution for frontend badge
                    preference_status=preference_status,
                    rating=activity.rating,
                    review_count=activity.user_ratings_count,
                    price_level=activity.price_level,
                    price_estimate=(matched_tile or {}).get("price_estimate"),
                    google_place_id=activity.google_place_id,
                    deeplink=activity.deeplink,
                    booked_tile=matched_tile,
                    requires_booking=bool(matched_tile),
                    booking_category="activity" if matched_tile else None,
                )

                if activity.coordinates:
                    block.coordinates = {
                        "lat": activity.coordinates[1],
                        "lng": activity.coordinates[0],
                    }

                current_day.blocks.append(block)
                specialist_count_per_day[day_idx][current_specialist] += 1
                period_ptr += 1
                self._dive_wrap_attempts = 0  # Reset on successful placement

                # EVEN DISTRIBUTION: Always advance to next day after placing
                # This spreads activities across all days before filling any day
                day_ptr += 1

            # Rotate specialist for variety
            specialist_ptr += 1

        # Overflow: place remaining specialist activities onto reserved days.
        # This prevents silent activity loss when the reduced round-robin set
        # can't fit all specialist content (e.g., 5-day trip with 5 hikes but
        # only 3 round-robin days).  Reserved days still get backfill via
        # Phase 5.6 if capacity remains.
        leftover = sum(len(v) for v in remaining.values())
        if leftover and min_free_days > 0:
            reserved_indices = available_day_indices[-min_free_days:]
            overflow_placed = 0
            for spec in list(remaining.keys()):
                acts = remaining.get(spec, [])
                while acts:
                    placed = False
                    for res_idx in reserved_indices:
                        res_day = days[res_idx]
                        non_buffer = [b for b in res_day.blocks if not b.is_buffer]
                        if len(non_buffer) >= min(MAX_BLOCKS_PER_DAY, self._activities_per_day):
                            continue
                        spec_on_day = sum(
                            1
                            for b in res_day.blocks
                            if b.specialist_type == spec and not b.is_buffer
                        )
                        if spec_on_day >= 1:
                            continue
                        activity = acts.pop(0)
                        is_user_preferred = getattr(activity, "is_user_preferred", False)
                        matched_tile = getattr(activity, "_matched_tile", None)
                        existing_periods = {b.period for b in res_day.blocks if b.period}
                        chosen_period = next(
                            (p for p in periods if p not in existing_periods), "afternoon"
                        )
                        block = DayBlockOutput(
                            id=activity.tile_id or f"act_{spec}_{res_idx}_{len(res_day.blocks)}",
                            period=chosen_period,
                            activity_type=spec,
                            intensity=activity.intensity,
                            summary=activity.title,
                            specialist_type=spec,
                            image_url=activity.image_url,
                            duration=f"{activity.duration_hours}h"
                            if activity.duration_hours
                            else None,
                            constraints=activity.constraints,
                            preference_status="user_preferred" if is_user_preferred else None,
                            rating=activity.rating,
                            review_count=activity.user_ratings_count,
                            price_level=activity.price_level,
                            price_estimate=(matched_tile or {}).get("price_estimate"),
                            google_place_id=activity.google_place_id,
                            deeplink=activity.deeplink,
                            booked_tile=matched_tile,
                            requires_booking=bool(matched_tile),
                            booking_category="activity" if matched_tile else None,
                        )
                        if activity.coordinates:
                            block.coordinates = {
                                "lat": activity.coordinates[1],
                                "lng": activity.coordinates[0],
                            }
                        res_day.blocks.append(block)
                        overflow_placed += 1
                        placed = True
                        _debug(
                            f"[ItineraryBuilder] Overflow: placed '{activity.title}' "
                            f"({spec}) on reserved Day {res_idx + 1}"
                        )
                        break
                    if not placed:
                        break
                if not acts:
                    remaining.pop(spec, None)
            if overflow_placed:
                _debug(
                    f"[ItineraryBuilder] Overflow: placed {overflow_placed} activities "
                    f"on reserved days"
                )

        leftover_final = sum(len(v) for v in remaining.values())
        if leftover_final:
            _debug(
                f"[ItineraryBuilder] Round-robin: {leftover_final} activities unplaced "
                f"(iteration={iteration}, days={len(round_robin_day_indices)})"
            )

        # =================================================================
        # GAP 6 FIX: Sort blocks within each day by time-of-day
        # Ensures MORNING appears before AFTERNOON before EVENING
        # Also handles buffer types (arrival, departure, no_fly, etc.)
        # =================================================================
        TIME_SLOT_ORDER = {"morning": 0, "afternoon": 1, "evening": 2, "night": 3}

        # Buffer types that pin to specific positions
        BUFFER_SORT_PRIORITY = {
            "arrival": (0, 0),  # First thing, before morning
            "check_in": (0, 1),  # Right after arrival
            "check-in": (0, 1),  # Alternative spelling
            "acclimatization": (1, 0),  # Activity-level, morning slot
            "surface_interval": (1, 1),  # Activity-level, between dives
            "no_fly_buffer": (1, 3),  # Activity-level, evening (end of day)
            "no_fly": (1, 3),  # Alternative spelling
            "departure": (2, 0),  # Last thing
            "check_out": (2, 0),  # Same as departure
            "check-out": (2, 0),  # Alternative spelling
        }

        for day in days:
            day.blocks.sort(
                key=lambda b: (
                    # Layer 1: Logistics bracket (0=arrival, 1=activities, 2=departure)
                    BUFFER_SORT_PRIORITY.get(getattr(b, "buffer_type", None), (1, 1))[0],
                    # Layer 2: Buffer sub-priority OR time slot
                    (
                        BUFFER_SORT_PRIORITY.get(getattr(b, "buffer_type", None), (1, 1))[1]
                        if getattr(b, "buffer_type", None) in BUFFER_SORT_PRIORITY
                        else TIME_SLOT_ORDER.get(
                            (getattr(b, "period", None) or "afternoon").lower(), 1
                        )
                    ),
                )
            )

        return days

    # =========================================================================
    # Phase 5.5: Handle Empty Days
    # =========================================================================

    def _handle_empty_days(
        self,
        days: List[DayCardOutput],
        tiles: Dict[str, Any],
        tier2_categories: Optional[List[str]] = None,
    ) -> List[DayCardOutput]:
        """
        Phase 5.5: Add FreeDay placeholders for days without activities.

        For each day (excluding arrival/departure) that has no activity blocks,
        insert a free_day block so the timeline never appears empty.
        When Tier 2 categories are selected, labels free days with those categories.
        """
        # Count available activity tiles for reference in the placeholder
        activity_count = sum(
            1
            for tile in tiles.values()
            if isinstance(tile, dict) and tile.get("type") == "activity"
        )
        tier2_label = " & ".join(c.title() for c in (tier2_categories or [])) or None

        for _i, day in enumerate(days):
            # Arrival/departure days are partially usable — don't skip them.
            # _day_remaining_capacity returns reduced capacity (4h, 1 slot) for anchor days.

            # Check if day has any real activity blocks (not buffers, logistics, or placeholders)
            has_activity = any(
                not b.is_buffer
                and b.activity_type
                not in ("check-in", "check-out", "arrival", "departure", "free_day")
                for b in day.blocks
            )

            if not has_activity:
                summary = (
                    f"{tier2_label} Day - explore at your own pace"
                    if tier2_label
                    else "Free Day - explore at your own pace"
                )
                day_label = "Free Day"

                # Create FreeDay placeholder block
                free_day_block = DayBlockOutput(
                    id=f"free_day_{day.day_number}",
                    period="morning",
                    activity_type="free_day",
                    summary=summary,
                    is_buffer=False,
                    specialist_type=None,
                    intensity="light",
                    constraints=[f"{activity_count} activities available to add"],
                )

                # Insert after any buffer blocks
                buffer_count = sum(1 for b in day.blocks if b.is_buffer)
                day.blocks.insert(buffer_count, free_day_block)

                # Preserve arrival/departure anchor labels — Phase 5.5 should not overwrite them.
                if day.label not in ("Arrival Day", "Departure Day"):
                    day.label = day_label

        return days

    # =========================================================================
    # Phase 5.55: Restore Browse-Pinned Tiles
    # =========================================================================

    def _restore_pinned_browse_tiles(
        self,
        days: List[DayCardOutput],
        input_data: "ItineraryBuilderInput",
    ) -> List[DayCardOutput]:
        """
        Phase 5.55: Re-insert browse tiles explicitly added by the user (source='browse_add').

        These tiles are NOT in input_data.tiles (they come from Google Places, not the
        LangGraph tile pool), so Phase 5.25 cannot find them by preferred_activity_id.
        This phase restores them directly from user_pinned_tiles before Phase 5.6 fills
        the remaining free slots with Tier 2 experience tiles.

        Only 'browse_add' tiles are restored. 'auto_fill' tiles regenerate fresh each run.
        """
        if not input_data.user_pinned_tiles:
            return days

        # If user explicitly cleared all activity categories, skip all placement.
        if self._active_categories is not None and len(self._active_categories) == 0:
            _debug_itinerary("📌 Phase 5.55 skipped: all activity categories cleared by user")
            return days

        day_count = len(days)
        restored = 0

        for tile_id, pin_data in input_data.user_pinned_tiles.items():
            if pin_data.get("source") != "browse_add":
                continue

            preferred_day = pin_data.get("preferred_day")
            if not preferred_day or preferred_day < 1 or preferred_day > day_count:
                continue

            tile = pin_data.get("tile")
            if not tile:
                continue

            # D3: Skip tiles whose category is no longer active.
            # (Empty-set case already handled by early return above.)
            if self._active_categories is not None and len(self._active_categories) > 0:
                tile_cat = (
                    (tile.get("meta") or {}).get("specialist_type")
                    or (tile.get("meta") or {}).get("category")
                    or tile.get("browse_category")
                    or ""
                ).lower()
                tile_cat = POI_TYPE_ALIASES.get(tile_cat, tile_cat)
                tile_tags = {t.lower() for t in tile.get("tags") or []}
                category_match = (
                    not tile_cat
                    or tile_cat in self._active_categories
                    or bool(tile_tags & self._active_categories)
                )
                if not category_match:
                    _debug_itinerary(
                        f"📌 Phase 5.55: Skipping pinned '{tile.get('title')}' "
                        f"— category '{tile_cat}' not in active categories"
                    )
                    continue

            day = days[preferred_day - 1]

            # Skip anchor days (arrival/departure) — they have no capacity
            rem_hours, rem_slots = self._day_remaining_capacity(day)
            if rem_slots <= 0:
                _debug_itinerary(
                    f"📌 Phase 5.55: Skipping pinned '{tile.get('title')}' "
                    f"on Day {preferred_day} — no capacity"
                )
                continue

            # Deduplicate by tile_id
            existing_ids = {b.id for b in day.blocks if b.id}
            if tile_id in existing_ids:
                _debug_itinerary(
                    f"📌 Phase 5.55: Skipping '{tile.get('title')}' "
                    f"— already on Day {preferred_day}"
                )
                continue

            # Deduplicate by title (cross-source: a specialist or experience block
            # may already cover the same venue under a different tile ID)
            title_key = _normalize_title_key(tile.get("title"))
            existing_title_keys = {_normalize_title_key(b.summary) for b in day.blocks if b.summary}
            if title_key and title_key in existing_title_keys:
                _debug_itinerary(
                    f"📌 Phase 5.55: Skipping pinned '{tile.get('title')}' "
                    f"— title already on Day {preferred_day}"
                )
                continue

            # Build the block using the shared converter
            block = self._experience_tile_to_block(tile, preferred_day, 0)
            block.id = tile_id  # Preserve original tile_id for dedup in later phases
            block.preference_status = "user_preferred"  # type: ignore[attr-defined]

            # Remove any free_day placeholder before inserting
            day.blocks = [b for b in day.blocks if b.activity_type != "free_day"]
            day.blocks.append(block)
            restored += 1
            _debug_itinerary(
                f"📌 Phase 5.55: Restored browse tile '{tile.get('title')}' on Day {preferred_day}"
            )

        _debug_itinerary(f"✅ Phase 5.55: Restored {restored} pinned browse tiles")
        return days

    # =========================================================================
    # Co-Scheduling Helpers (used by Phase 5.6 and Phase 5.25)
    # =========================================================================

    def _day_remaining_capacity(self, day: DayCardOutput) -> tuple[float, int]:
        """
        Remaining (hours, block_slots) for a day.
        Returns (4.0, 1) for arrival/departure anchor days.
        """
        if not day.blocks:
            return (DAY_CAPACITY_HOURS, min(MAX_BLOCKS_PER_DAY, self._activities_per_day))

        # Skip logistics anchor days
        anchor_types = (
            "arrival",
            "departure",
            "check_in",
            "check_out",
            "check-in",
            "check-out",
        )
        buffer_types = ("arrival", "departure")
        if any(
            (b.activity_type in anchor_types) or ((b.buffer_type or "") in buffer_types)
            for b in day.blocks
        ):
            # Arrival/departure days get reduced capacity (1 activity, ~4h)
            return (4.0, 1)

        activity_hours = 0.0
        total_blocks = 0
        activity_count = 0
        for b in day.blocks:
            if b.activity_type == "free_day":
                continue
            # Count ALL blocks (including buffers) toward the per-day cap
            # to match the frontend content policy guard
            total_blocks += 1
            if not b.is_buffer:
                activity_hours += _parse_duration_hours(b.duration, 3.0)
                activity_count += 1

        remaining_hours = max(0.0, DAY_CAPACITY_HOURS - activity_hours)
        remaining_blocks = max(0, MAX_BLOCKS_PER_DAY - total_blocks)

        # Enforce activities_per_day as a hard ceiling across all placement phases
        apd_remaining = max(0, self._activities_per_day - activity_count)
        remaining_blocks = min(remaining_blocks, apd_remaining)

        return (remaining_hours, remaining_blocks)

    def _time_slot_score(self, day: DayCardOutput, tile_time_of_day: str) -> float:
        """
        Score 0.0-1.0 for how well a tile's time_of_day complements existing blocks.

        1.0 = no overlap (evening tile on morning-only day)
        0.5 = adjacent slot (afternoon tile on morning day)
        0.1 = same slot (morning tile on morning day)
        """
        tile_slot = _TIME_SLOT_ORDER.get(tile_time_of_day, 1)
        occupied = set()
        for b in day.blocks:
            p = (b.period or "").lower()
            if p in _TIME_SLOT_ORDER:
                occupied.add(_TIME_SLOT_ORDER[p])
        if not occupied:
            return 1.0
        if tile_slot in occupied:
            return 0.1
        min_dist = min(abs(tile_slot - s) for s in occupied)
        return 1.0 if min_dist >= 2 else 0.5

    def _experience_tile_to_block(
        self, tile: dict, day_number: int, count: int = 0
    ) -> DayBlockOutput:
        """Convert an experience_generator tile dict into a DayBlockOutput."""
        meta = tile.get("meta") or {}
        time_of_day = meta.get("time_of_day", "afternoon")
        category = meta.get("category", "experience")
        period_map = {"morning": "morning", "afternoon": "afternoon", "evening": "evening"}
        geo = tile.get("geo") or {}
        coords = None
        if isinstance(geo, dict) and geo.get("lat") is not None and geo.get("lng") is not None:
            coords = {"lat": geo["lat"], "lng": geo["lng"]}
        elif tile.get("coordinates"):
            c = tile["coordinates"]
            if isinstance(c, dict):
                coords = c
            elif isinstance(c, list) and len(c) == 2:
                coords = {"lat": c[1], "lng": c[0]}  # [lng, lat] → {lat, lng}
        if coords is None:
            meta_geo = meta.get("geo")
            if (
                isinstance(meta_geo, dict)
                and meta_geo.get("lat") is not None
                and meta_geo.get("lng") is not None
            ):
                coords = {"lat": meta_geo["lat"], "lng": meta_geo["lng"]}
        source_agent = (tile.get("source_agent") or "").strip().lower()
        explicit_price_level = tile.get("price_level")
        if isinstance(explicit_price_level, int) and 0 <= explicit_price_level <= 4:
            block_price_level = explicit_price_level
        elif source_agent == "experience_generator":
            # LLM-generated Tier 2 tiles have only USD estimates; derive display tier.
            block_price_level = _price_estimate_to_level(tile.get("price_estimate"))
        else:
            # Logistics/Places backfill should not invent "$$" when upstream price is unknown.
            block_price_level = None
        return DayBlockOutput(
            id=tile.get("id", f"exp_block_{day_number}_{count}"),
            period=period_map.get(time_of_day, "afternoon"),
            activity_type=category if category else "experience",
            summary=tile.get("title", "Experience Activity"),
            # Only tag Tier 1 specialist activities (diving, hiking, etc.).
            # Tier 2 / generic experience tiles don't get a specialist badge.
            specialist_type=category if category in _TIER1_SPECIALIST_NAMES else None,
            intensity="light",
            duration=f"{meta.get('duration_hours', 2)}h",
            image_url=tile.get("image_url"),
            booked_tile=tile,
            requires_booking=True,
            booking_category="activity",
            rating=tile.get("rating"),
            review_count=tile.get("review_count"),
            price_level=block_price_level,
            price_estimate=tile.get("price_estimate"),
            google_place_id=tile.get("google_place_id") or tile.get("place_id"),
            deeplink=tile.get("deeplink") or tile.get("deeplink_url") or tile.get("maps_uri"),
            coordinates=coords,
        )

    @staticmethod
    def _category_count_on_day(day: DayCardOutput, category: str) -> int:
        """Count experience blocks of a given category already on a day."""
        return sum(
            1
            for b in day.blocks
            if getattr(b, "specialist_type", None) == category
            and getattr(b, "booking_category", None) == "activity"
        )

    # =========================================================================
    # Phase 5.6: Place Experience Tiles on Free Days
    # =========================================================================

    def _place_experience_tiles(
        self,
        days: List[DayCardOutput],
        tiles: Dict[str, Any],
    ) -> List[DayCardOutput]:
        """
        Phase 5.6: Place experience tiles (Tier 2 activities from experience_generator).

        Two-pass strategy:
          Pass 1: Fill free days (days with free_day placeholder)
          Pass 2: Co-schedule remaining tiles onto specialist days with spare capacity

        Args:
            days: Day cards from previous phases
            tiles: Flat {tile_id: tile_dict} map from input_data.tiles

        Returns:
            Updated day cards with experience tiles placed.
        """
        if not tiles:
            _debug_itinerary("⏭️ Phase 5.6 skipped: no tiles")
            return days

        # If user explicitly cleared all activity categories, skip all placement.
        if self._active_categories is not None and len(self._active_categories) == 0:
            _debug_itinerary("⏭️ Phase 5.6 skipped: all activity categories cleared by user")
            return days

        # Filter for experience generator tiles, excluding those claimed by Phase 5.25
        preferred_ids = set(self.preferences.preferred_activity_ids) if self.preferences else set()

        # Primary: experience generator tiles (Tier 2: yoga, cooking, nightlife)
        experience_tiles = [
            t
            for _, t in tiles.items()
            if isinstance(t, dict)
            and t.get("source_agent") == "experience_generator"
            and t.get("id") not in preferred_ids
        ]

        # Fallback: any non-experience activity tiles (logistics backfill)
        # We're already past the experience_generator check, so any activity tile here
        # is from logistics_node (may lack source_agent if loaded from stale tile cache)
        if not experience_tiles:
            logistics_tiles = [
                t
                for _, t in tiles.items()
                if isinstance(t, dict)
                and t.get("type") == "activity"
                and t.get("source_agent") != "vertical_specialist"
                and t.get("id") not in preferred_ids
            ]

            if logistics_tiles:
                _debug_itinerary(
                    f"📅 Phase 5.6: No experience tiles, using {len(logistics_tiles)} "
                    f"logistics backfill tiles"
                )
                experience_tiles = logistics_tiles
            else:
                _debug_itinerary("⏭️ Phase 5.6 skipped: no placeable tiles")
                return days

        _debug_itinerary(f"📅 Phase 5.6: Found {len(experience_tiles)} experience tiles")

        # Per-tile category filter: when user has active categories, only place matching tiles.
        # (Empty-set case already handled by early return above.)
        if self._active_categories is not None and len(self._active_categories) > 0:
            pre_count = len(experience_tiles)
            filtered: list[dict] = []
            for t in experience_tiles:
                is_backfill_tile = bool((t.get("meta") or {}).get("is_backfill"))
                tile_cat = (
                    (t.get("meta") or {}).get("specialist_type")
                    or (t.get("meta") or {}).get("category")
                    or t.get("specialist_type")
                    or ""
                ).lower()
                tile_cat = POI_TYPE_ALIASES.get(tile_cat, tile_cat)
                tile_tags = {tag.lower() for tag in t.get("tags") or []}
                tile_source_cats = {
                    c.lower() for c in (t.get("meta") or {}).get("source_categories", [])
                }
                category_match = (
                    not tile_cat
                    or tile_cat in self._active_categories
                    or bool(tile_tags & self._active_categories)
                    or bool(tile_source_cats & self._active_categories)
                )
                if category_match or is_backfill_tile:
                    filtered.append(t)
                    if is_backfill_tile and not category_match:
                        _debug_itinerary(
                            f"📅 Phase 5.6: Preserving backfill '{t.get('title')}' "
                            "despite active category filter"
                        )
                else:
                    _debug_itinerary(
                        f"📅 Phase 5.6: Skipping '{t.get('title')}' "
                        f"— category '{tile_cat}' not in active categories"
                    )
            experience_tiles = filtered
            if not experience_tiles:
                _debug_itinerary(
                    f"⏭️ Phase 5.6 skipped: all {pre_count} tiles filtered by active categories"
                )
                return days

        # Sort by time_of_day: morning first, then afternoon, then evening
        experience_tiles.sort(
            key=lambda t: _TIME_SLOT_ORDER.get(
                (t.get("meta") or {}).get("time_of_day", "afternoon"), 1
            )
        )

        # Cross-source dedup is GLOBAL across all days: experience tiles should not
        # re-create venues already placed by specialist dispatch. Per-day scoping
        # would allow the same venue to appear twice in the itinerary.
        existing_titles: set[str] = set()
        for day in days:
            for block in day.blocks:
                title = getattr(block, "summary", None)
                if title:
                    existing_titles.add(_normalize_title_key(title))

        pre_dedup_count = len(experience_tiles)
        experience_tiles = [
            t
            for t in experience_tiles
            if _normalize_title_key(t.get("title")) not in existing_titles
        ]
        cross_removed = pre_dedup_count - len(experience_tiles)
        if cross_removed > 0:
            _debug_itinerary(
                f"📅 Phase 5.6: {len(experience_tiles)} tiles after cross-source dedup "
                f"(removed {cross_removed} duplicates vs existing blocks)"
            )

        # Deduplicate by normalised title — the experience generator can
        # produce tiles with different IDs but identical titles.
        seen_titles: set[str] = set()
        deduped: list[dict] = []
        for t in experience_tiles:
            title_key = _normalize_title_key(t.get("title"))
            if title_key and title_key in seen_titles:
                continue
            if title_key:
                seen_titles.add(title_key)
            deduped.append(t)
        unplaced = deduped

        _PERIOD_ORDER = ["morning", "afternoon", "evening"]

        # ─────────────────────────────────────────────────────────
        # Pass 0: Place pinned tiles (from fill-day) on target day
        # ─────────────────────────────────────────────────────────
        pinned = [t for t in unplaced if (t.get("meta") or {}).get("pinned_day") is not None]
        unpinned = [t for t in unplaced if (t.get("meta") or {}).get("pinned_day") is None]

        placed_pinned = 0
        for tile in pinned:
            target_day = tile["meta"]["pinned_day"]
            day_match = next((d for d in days if d.day_number == target_day), None)
            if day_match:
                rem_hours, rem_blocks = self._day_remaining_capacity(day_match)
                tile_hours = (tile.get("meta") or {}).get(
                    "duration_hours", DEFAULT_EXPERIENCE_HOURS
                )
                if rem_hours >= tile_hours and rem_blocks >= 1:
                    exp_count = sum(
                        1
                        for b in day_match.blocks
                        if getattr(b, "booking_category", None) == "activity"
                    )
                    block = self._experience_tile_to_block(tile, day_match.day_number, exp_count)
                    pinned_used = {b.period for b in day_match.blocks if b.period}
                    if block.period in pinned_used:
                        block.period = next(
                            (p for p in _PERIOD_ORDER if p not in pinned_used), block.period
                        )
                    day_match.blocks.append(block)
                    # Remove free_day placeholder so Pass 1 doesn't double-fill
                    day_match.blocks = [
                        b for b in day_match.blocks if b.activity_type != "free_day"
                    ]
                    if day_match.label == "Free Day":
                        day_match.label = f"Day {day_match.day_number}"
                    placed_pinned += 1
                    _debug_itinerary(
                        f"📌 Phase 5.6 Pass 0: Pinned '{tile.get('title')}' on Day {target_day}"
                    )
                    continue
            # Target day missing or full — fall through to unpinned pool
            unpinned.append(tile)

        if placed_pinned:
            _debug_itinerary(f"📌 Phase 5.6 Pass 0: Placed {placed_pinned} pinned tiles")

        unplaced = unpinned

        # ─────────────────────────────────────────────────────────
        # Pass 1: Free Day Placement (preserves existing behavior)
        # ─────────────────────────────────────────────────────────
        free_day_indices = []
        for i, day in enumerate(days):
            if any(b.activity_type == "free_day" for b in day.blocks):
                free_day_indices.append(i)

        placed_on_free = 0
        target_per_day = self._activities_per_day
        for day_idx in free_day_indices:
            if not unplaced:
                break
            day = days[day_idx]
            day.blocks = [b for b in day.blocks if b.activity_type != "free_day"]

            # Respect reduced capacity on arrival/departure days
            rem_hours, rem_slots = self._day_remaining_capacity(day)
            day_target = min(target_per_day, rem_slots)
            day_hour_budget = min(DAY_CAPACITY_HOURS, rem_hours)

            used_periods: set[str] = {b.period for b in day.blocks if b.period}
            placed_today = 0
            used_hours = 0.0
            while unplaced and placed_today < day_target:
                tile = unplaced[0]
                t_hours = (tile.get("meta") or {}).get("duration_hours", DEFAULT_EXPERIENCE_HOURS)
                if used_hours + t_hours > day_hour_budget:
                    break
                t_cat = (tile.get("meta") or {}).get("category", "experience")
                if (
                    placed_today > 0
                    and self._category_count_on_day(day, t_cat) >= MAX_SAME_CATEGORY_PER_DAY
                ):
                    break
                block = self._experience_tile_to_block(
                    unplaced.pop(0), day.day_number, placed_today
                )
                if block.period in used_periods:
                    block.period = next(
                        (p for p in _PERIOD_ORDER if p not in used_periods), block.period
                    )
                used_periods.add(block.period)
                day.blocks.append(block)
                used_hours += t_hours
                placed_today += 1
                placed_on_free += 1

        # Update day labels for free days that got experience tiles
        for day_idx in free_day_indices:
            day = days[day_idx]
            placed_categories = []
            for b in day.blocks:
                if b.specialist_type and b.specialist_type != "experience":
                    cat_title = b.specialist_type.replace("_", " ").title()
                    if cat_title not in placed_categories:
                        placed_categories.append(cat_title)
            if placed_categories:
                day.label = " & ".join(placed_categories) + " Day"

        if placed_on_free:
            _debug_itinerary(
                f"📅 Phase 5.6 Pass 1: Placed {placed_on_free} tiles on "
                f"{len(free_day_indices)} free days"
            )

        if not unplaced:
            _debug_itinerary(f"✅ Phase 5.6: All {placed_on_free} tiles placed on free days")
            return days

        # ─────────────────────────────────────────────────────────
        # Pass 2: Co-Schedule on Specialist Days
        # ─────────────────────────────────────────────────────────
        _debug_itinerary(
            f"📅 Phase 5.6 Pass 2: {len(unplaced)} tiles remaining, "
            f"scanning specialist days for capacity"
        )

        # Build candidate list with capacity — skip days where Tier 1
        # specialist blocks have saturated the activities_per_day cap.
        # Days with specialist blocks AND remaining capacity still accept
        # backfill (e.g., 1 hike + 1 temple visit on a 2-apd day).
        candidates: list[list] = []  # [[day_idx, remaining_hours, remaining_blocks]]
        for i, day in enumerate(days):
            specialist_count = sum(
                1
                for b in day.blocks
                if not b.is_buffer
                and getattr(b, "specialist_type", None) in _TIER1_SPECIALIST_NAMES
            )
            if specialist_count >= self._activities_per_day:
                continue
            remaining_hours, remaining_blocks = self._day_remaining_capacity(day)
            if remaining_hours >= 1.0 and remaining_blocks >= 1:
                candidates.append([i, remaining_hours, remaining_blocks])

        if not candidates:
            _debug_itinerary(
                f"📅 Phase 5.6 Pass 2: No days have capacity for backfill. "
                f"Dropping {len(unplaced)} tiles."
            )
            return days

        placed_on_specialist = 0
        still_unplaced = []

        for tile in unplaced:
            meta = tile.get("meta") or {}
            tile_hours = meta.get("duration_hours", DEFAULT_EXPERIENCE_HOURS)
            tile_tod = meta.get("time_of_day", "afternoon")
            tile_cat = meta.get("category", "experience")

            best_cand_idx = None
            best_score = -1.0

            for cand_idx, (day_idx, rem_hours, rem_blocks) in enumerate(candidates):
                if tile_hours > rem_hours or rem_blocks < 1:
                    continue

                # Skip if day already at category cap for this tile's
                # category.
                if (
                    self._category_count_on_day(days[day_idx], tile_cat)
                    >= MAX_SAME_CATEGORY_PER_DAY
                ):
                    continue

                complement = self._time_slot_score(days[day_idx], tile_tod)
                headroom = rem_hours / DAY_CAPACITY_HOURS
                score = complement * 0.7 + headroom * 0.3

                # Soft budget-density penalty: avoid stacking expensive tiles
                if self._budget and self._num_days:
                    daily_budget = self._budget / self._num_days
                    if daily_budget < 200:
                        tile_pl = tile.get("price_level") or 0
                        day_expensive = any(
                            (b.price_level or 0) >= 3
                            for b in days[day_idx].blocks
                            if not b.is_buffer
                        )
                        if tile_pl >= 3 and day_expensive:
                            score *= 0.8

                if score > best_score:
                    best_score = score
                    best_cand_idx = cand_idx

            if best_cand_idx is None:
                _debug_itinerary(
                    f"📅 Phase 5.6 Pass 2: Cannot fit "
                    f"'{tile.get('title')}' ({tile_hours}h) — dropped"
                )
                still_unplaced.append(tile)
                continue

            day_idx = candidates[best_cand_idx][0]
            day = days[day_idx]
            exp_count = sum(1 for b in day.blocks if b.activity_type == "activity")
            block = self._experience_tile_to_block(tile, day.day_number, exp_count)
            existing_periods = {b.period for b in day.blocks if b.period}
            if block.period in existing_periods:
                block.period = next(
                    (p for p in _PERIOD_ORDER if p not in existing_periods), block.period
                )
            day.blocks.append(block)
            placed_on_specialist += 1

            # Update candidate capacity
            candidates[best_cand_idx][1] -= tile_hours
            candidates[best_cand_idx][2] -= 1

            _debug_itinerary(
                f"📅 Phase 5.6 Pass 2: Placed '{tile.get('title')}' "
                f"on Day {day_idx + 1} (score={best_score:.2f})"
            )

        dropped = len(still_unplaced)
        _debug_itinerary(
            f"✅ Phase 5.6 complete: {placed_on_free} on free days, "
            f"{placed_on_specialist} co-scheduled, {dropped} dropped"
        )

        return days

    # =========================================================================
    # Phase 5.25: Populate Free Days with Preferred Activities
    # =========================================================================

    def _populate_free_days_with_preferences(
        self,
        days: List[DayCardOutput],
        tiles: Dict[str, Any],
        preferences: Optional[PreferenceOverrideInput],
    ) -> tuple[List[DayCardOutput], int]:
        """
        Phase 5.25: Place user-preferred activities into available day slots.

        Uses UNIFIED SLOT MODEL instead of free-days-only approach:
        - Every day has 3 periods: morning, afternoon, evening
        - Arrival day: morning+afternoon locked (travel), evening FREE
        - Departure day: morning FREE, afternoon+evening locked (travel)
        - Regular days: periods occupied by specialist blocks are locked
        - Buffer blocks (no-fly, etc.) don't lock periods - they mean
          "don't fly", not "don't do anything"

        Round-robin placement spreads activities across days, filling least-loaded first.
        Returns (days, dropped_count) tuple.
        """
        if not preferences or not preferences.preferred_activity_ids:
            _debug_itinerary("⏭️ Phase 5.25 skipped: no preferred activities")
            return days, 0

        # Skip tiles already placed by Phase 5.6 Pass 0 (pinned_day placement)
        already_placed: set[str] = set()
        scheduled_title_keys: set[str] = set()
        _NON_ACTIVITY = {"free_day", "check-in", "check-out", "arrival", "departure"}
        for day in days:
            for block in day.blocks:
                if not block.is_buffer and block.activity_type not in _NON_ACTIVITY:
                    title_key = _normalize_title_key(block.summary)
                    if title_key:
                        scheduled_title_keys.add(title_key)
                if block.id and block.booking_category == "activity":
                    already_placed.add(block.id)

        # Collect preferred tile activities (ordered by position in preferred_activity_ids)
        preferred_activities = []
        seen_preferred_titles: set[str] = set()
        for tile_id in preferences.preferred_activity_ids:
            if tile_id in already_placed:
                continue
            tile = tiles.get(tile_id)
            if tile and isinstance(tile, dict) and tile.get("type") == "activity":
                # D3: Skip tiles whose category is no longer active (user removed category).
                # Only filter when active_categories is explicitly set (not None).
                # None = no category filter (categories not specified).
                # set() = user cleared all categories — skip all preferred tiles.
                if self._active_categories is not None:
                    tile_cat = (
                        (tile.get("meta") or {}).get("specialist_type")
                        or (tile.get("meta") or {}).get("category")
                        or tile.get("specialist_type")
                        or ""
                    ).lower()
                    tile_cat = POI_TYPE_ALIASES.get(tile_cat, tile_cat)
                    # Match against tags too if no explicit category field
                    tile_tags = {t.lower() for t in tile.get("tags") or []}
                    # Empty tile_cat = unidentifiable source (e.g. browse/Places tile) →
                    # preserve only when user has active categories (safety fallback).
                    # When _active_categories is empty set, reject all tiles.
                    category_match = (
                        (not tile_cat and len(self._active_categories) > 0)
                        or tile_cat in self._active_categories
                        or bool(tile_tags & self._active_categories)
                    )
                    if not category_match:
                        _debug_itinerary(
                            f"📅 Phase 5.25: Skipping preferred tile '{tile.get('title')}' "
                            f"— category '{tile_cat}' not in active categories"
                        )
                        continue
                title_key = _normalize_title_key(tile.get("title"))
                if title_key and title_key in scheduled_title_keys:
                    _debug_itinerary(
                        f"📅 Phase 5.25: Skipping duplicate preferred title '{tile.get('title')}' "
                        "(already scheduled)"
                    )
                    continue
                if title_key and title_key in seen_preferred_titles:
                    _debug_itinerary(
                        f"📅 Phase 5.25: Skipping duplicate preferred title '{tile.get('title')}' "
                        "(duplicate tile)"
                    )
                    continue
                if title_key:
                    seen_preferred_titles.add(title_key)
                preferred_activities.append({**tile, "id": tile_id, "_title_key": title_key})

        if not preferred_activities:
            _debug_itinerary("📅 Phase 5.25: No valid activity tiles found in preferences")
            return days, 0

        _debug_itinerary(f"📅 Phase 5.25: Found {len(preferred_activities)} preferred activities")

        # =====================================================================
        # UNIFIED SLOT MODEL: Build slot map for ALL days
        # =====================================================================
        MAX_SLOTS_PER_DAY = 3
        PERIODS = ["morning", "afternoon", "evening"]

        # Track which periods are occupied per day (using sets)
        day_slots: dict[int, set[str]] = {}

        for idx, day in enumerate(days):
            # Arrival day: lock morning (flight/transfer), afternoon+evening free
            if idx == 0:
                day_slots[idx] = {"morning"}
                continue

            # Departure day: lock evening (flight/transfer), morning+afternoon free
            if idx == len(days) - 1:
                day_slots[idx] = {"evening"}
                continue

            # Regular days: check which periods are occupied by existing blocks
            used: set[str] = set()
            for block in day.blocks:
                # Buffer blocks don't lock periods - "don't fly" != "don't do anything"
                if block.is_buffer:
                    continue
                # Skip logistics/placeholder blocks
                if block.activity_type in (
                    "check-in",
                    "check-out",
                    "arrival",
                    "departure",
                    "free_day",
                ):
                    continue
                # Specialist/activity blocks occupy their declared period (default: morning)
                period = block.period or "morning"
                used.add(period)
            day_slots[idx] = used

        # Defensive: ensure we never reference days beyond trip length
        valid_day_indices = set(range(len(days)))
        day_slots = {d: slots for d, slots in day_slots.items() if d in valid_day_indices}

        # Log slot availability
        slot_summary = {d: MAX_SLOTS_PER_DAY - len(slots) for d, slots in day_slots.items()}
        total_capacity = sum(slot_summary.values())
        _debug_itinerary(
            f"📋 Slot availability: {slot_summary}, total_capacity={total_capacity}, "
            f"activities_to_place={len(preferred_activities)}"
        )

        if total_capacity == 0:
            _debug_itinerary("📅 Phase 5.25: No slots available for preferred activities")
            return days, len(preferred_activities)

        # =====================================================================
        # ROUND-ROBIN PLACEMENT: Spread activities across days
        # =====================================================================
        dropped_count = 0
        deferred: list[dict] = []  # Tiles that couldn't fit in Pass 1

        # Safety net: Track specialist count per day to prevent activity cramming
        # Max 1 activity per specialist per day (e.g., 1 dive + 1 hike per day is OK)
        from collections import defaultdict

        specialist_count_per_day: dict = defaultdict(lambda: defaultdict(int))

        pinned_day_map = preferences.pinned_day_map if preferences else {}
        priority_map = preferences.pinned_priority_map if preferences else {}

        # Split by priority: high (Browse→Add) gets fallback, low (auto-fill) is day-or-drop
        high_priority = [
            t for t in preferred_activities if priority_map.get(t.get("id"), "high") == "high"
        ]
        low_priority = [t for t in preferred_activities if priority_map.get(t.get("id")) == "low"]

        def _place_on_day(tile: dict, day_idx: int) -> bool:
            """Place tile on a specific day. Returns True if placed."""
            title_key = tile.get("_title_key") or _normalize_title_key(tile.get("title"))
            if title_key and title_key in scheduled_title_keys:
                return False
            if day_idx not in day_slots or len(day_slots[day_idx]) >= MAX_SLOTS_PER_DAY:
                return False
            # Enforce activities_per_day cap (matches _day_remaining_capacity)
            _, rem_blocks = self._day_remaining_capacity(days[day_idx])
            if rem_blocks < 1:
                return False
            day = days[day_idx]
            period = next((p for p in PERIODS if p not in day_slots[day_idx]), None)
            if not period:
                return False
            day_slots[day_idx].add(period)

            # Remove FreeDay placeholder
            if any(b.activity_type == "free_day" for b in day.blocks):
                day.blocks = [b for b in day.blocks if b.activity_type != "free_day"]

            # Resolve coordinates: DayBlock uses {lat, lng}, browse tiles carry geo {lat, lng}
            _coords = tile.get("coordinates")
            if isinstance(_coords, list) and len(_coords) >= 2:
                _coords = {"lng": _coords[0], "lat": _coords[1]}
            if not _coords:
                _geo = tile.get("geo")
                if isinstance(_geo, dict) and "lat" in _geo and "lng" in _geo:
                    _coords = {"lat": _geo["lat"], "lng": _geo["lng"]}

            activity_block = DayBlockOutput(
                id=f"pref_{tile['id']}_{day_idx}_{period}",
                period=period,
                activity_type=(
                    tile.get("specialist_type")
                    or tile.get("category")
                    or (tile.get("meta") or {}).get("category")
                    or "activity"
                ),
                intensity=tile.get("intensity"),
                summary=tile.get("title", "Activity"),
                image_url=tile.get("image_url"),
                duration=tile.get("duration"),
                rating=tile.get("rating"),
                review_count=tile.get("review_count"),
                price_level=tile.get("price_level"),
                price_estimate=tile.get("price_estimate"),
                coordinates=_coords,
                specialist_type=tile.get("specialist_type") or tile.get("category") or None,
                preference_status="user_preferred",
                booking_category="activity",
                booked_tile=tile,
                google_place_id=tile.get("google_place_id")
                or tile.get("place_id")
                or (tile.get("meta") or {}).get("place_id"),
                deeplink=tile.get("deeplink") or tile.get("deeplink_url") or tile.get("maps_uri"),
            )

            # Insert respecting period order
            buffer_count = sum(1 for b in day.blocks if b.is_buffer)
            period_order = {"morning": 0, "afternoon": 1, "evening": 2}
            insert_idx = buffer_count
            for i, b in enumerate(day.blocks[buffer_count:], start=buffer_count):
                block_period = getattr(b, "period", None) or "morning"
                if period_order.get(block_period, 0) > period_order.get(period, 0):
                    insert_idx = i
                    break
                insert_idx = i + 1
            day.blocks.insert(insert_idx, activity_block)

            if day.label == "Free Day":
                day.label = f"Day {day.day_number}"
            if title_key:
                scheduled_title_keys.add(title_key)

            _debug_itinerary(f"📅 Placed '{tile.get('title')}' on day {day_idx + 1} ({period})")
            return True

        # ── High-priority (Browse→Add): honor preferred_day, fallback to best-fit ──
        for tile in high_priority:
            pinned_day_num = pinned_day_map.get(tile.get("id"))
            pinned_idx = (pinned_day_num - 1) if pinned_day_num is not None else None

            available_days = [d for d in day_slots if len(day_slots[d]) < MAX_SLOTS_PER_DAY]
            if not available_days:
                deferred.append(tile)
                continue

            # Try pinned day first, then best-fit
            if pinned_idx is not None and pinned_idx in available_days:
                best_day = pinned_idx
            else:
                best_day = min(available_days, key=lambda d: (len(day_slots[d]), d))

            source_specialist = tile.get("source_specialist") or tile.get("meta", {}).get(
                "specialist_type"
            )
            if source_specialist and specialist_count_per_day[best_day][source_specialist] >= 1:
                deferred.append(tile)
                continue
            if source_specialist:
                specialist_count_per_day[best_day][source_specialist] += 1

            if not _place_on_day(tile, best_day):
                deferred.append(tile)

        # ── Low-priority (auto-fill): preferred day only if still free, else drop ──
        for tile in low_priority:
            pinned_day_num = pinned_day_map.get(tile.get("id"))
            if pinned_day_num is None:
                dropped_count += 1
                continue
            pinned_idx = pinned_day_num - 1
            if pinned_idx < 0 or pinned_idx >= len(days):
                dropped_count += 1
                continue

            # Only place on free days (no specialist blocks)
            day = days[pinned_idx]
            _NON_ACTIVITY = {"free_day", "check-in", "check-out", "arrival", "departure"}
            has_specialist = any(
                not b.is_buffer and b.activity_type not in _NON_ACTIVITY for b in day.blocks
            )
            if has_specialist:
                _debug_itinerary(
                    f"📅 Phase 5.25: Dropping low-priority '{tile.get('title')}' "
                    f"(day {pinned_idx + 1} taken by specialist)"
                )
                dropped_count += 1
                continue

            if not _place_on_day(tile, pinned_idx):
                dropped_count += 1

        # =====================================================================
        # PASS 2: Co-schedule deferred tiles using capacity-based fallback
        # =====================================================================
        if deferred:
            _debug_itinerary(
                f"📅 Phase 5.25 Pass 2: {len(deferred)} deferred tiles, "
                f"scanning days for hour-based capacity"
            )
            for tile in deferred:
                title_key = tile.get("_title_key") or _normalize_title_key(tile.get("title"))
                if title_key and title_key in scheduled_title_keys:
                    _debug_itinerary(
                        f"📅 Phase 5.25 Pass 2: Skipping duplicate '{tile.get('title')}' "
                        "(already scheduled)"
                    )
                    continue
                meta = tile.get("meta") or {}
                tile_hours = _parse_duration_hours(
                    tile.get("duration"), meta.get("duration_hours", DEFAULT_EXPERIENCE_HOURS)
                )
                tile_tod = meta.get("time_of_day", "afternoon")

                best_idx = None
                best_score = -1.0

                for i, day in enumerate(days):
                    remaining_hours, remaining_blocks = self._day_remaining_capacity(day)
                    if tile_hours > remaining_hours or remaining_blocks < 1:
                        continue
                    score = self._time_slot_score(day, tile_tod)
                    # Soft budget-density penalty
                    if self._budget and self._num_days:
                        daily_budget = self._budget / self._num_days
                        if daily_budget < 200:
                            tile_pl = tile.get("price_level") or 0
                            day_expensive = any(
                                (b.price_level or 0) >= 3 for b in day.blocks if not b.is_buffer
                            )
                            if tile_pl >= 3 and day_expensive:
                                score *= 0.8
                    if score > best_score:
                        best_score = score
                        best_idx = i

                if best_idx is not None:
                    day = days[best_idx]
                    tod = meta.get("time_of_day", "afternoon")
                    period_map = {
                        "morning": "morning",
                        "afternoon": "afternoon",
                        "evening": "evening",
                    }
                    period = period_map.get(tod, "afternoon")

                    activity_block = DayBlockOutput(
                        id=f"pref_{tile['id']}_{best_idx}_{period}",
                        period=period,
                        activity_type=(
                            tile.get("specialist_type")
                            or tile.get("category")
                            or (tile.get("meta") or {}).get("category")
                            or "activity"
                        ),
                        intensity=tile.get("intensity"),
                        summary=tile.get("title", "Activity"),
                        image_url=tile.get("image_url"),
                        duration=tile.get("duration"),
                        rating=tile.get("rating"),
                        review_count=tile.get("review_count"),
                        price_level=tile.get("price_level"),
                        price_estimate=tile.get("price_estimate"),
                        coordinates=(
                            (
                                {"lng": tile["coordinates"][0], "lat": tile["coordinates"][1]}
                                if isinstance(tile.get("coordinates"), list)
                                and len(tile["coordinates"]) >= 2
                                else tile.get("coordinates")
                            )
                            or (
                                {"lat": tile["geo"]["lat"], "lng": tile["geo"]["lng"]}
                                if isinstance(tile.get("geo"), dict)
                                and "lat" in tile.get("geo", {})
                                and "lng" in tile.get("geo", {})
                                else None
                            )
                        ),
                        specialist_type=tile.get("specialist_type") or tile.get("category") or None,
                        preference_status="user_preferred",
                        booking_category="activity",
                        booked_tile=tile,
                        google_place_id=tile.get("google_place_id")
                        or tile.get("place_id")
                        or (tile.get("meta") or {}).get("place_id"),
                        deeplink=tile.get("deeplink")
                        or tile.get("deeplink_url")
                        or tile.get("maps_uri"),
                    )
                    day.blocks.append(activity_block)
                    if title_key:
                        scheduled_title_keys.add(title_key)
                    _debug_itinerary(
                        f"📅 Phase 5.25 Pass 2: Co-scheduled '{tile.get('title')}' "
                        f"on Day {best_idx + 1} (score={best_score:.2f})"
                    )
                else:
                    dropped_count += 1
                    _debug_itinerary(
                        f"📅 Phase 5.25 Pass 2: Cannot fit '{tile.get('title')}' — dropped"
                    )

        return days, dropped_count

    # =========================================================================
    # Phase 6: Tile Matching
    # =========================================================================

    def _match_tiles(
        self,
        days: List[DayCardOutput],
        tiles: Dict[str, Any],
        preferences: Optional[PreferenceOverrideInput] = None,
    ) -> List[DayCardOutput]:
        """Match tiles to blocks (hotels span all days).

        Applies 1.5x preference boost to user-hearted tiles.
        """
        # Log Phase 6 entry with preference state
        preferred_hotels = preferences.preferred_hotel_ids if preferences else []
        _debug_itinerary(f"🏨 Phase 6 (Tile Matching): preferred_hotel_ids={preferred_hotels}")

        # Find hotel tiles, sorted by preference (preferred first)
        hotel_tiles = []
        for tile_id, tile in tiles.items():
            if isinstance(tile, dict) and tile.get("type") == "hotel":
                # Apply 1.5x score boost if preferred
                # Use bool() to ensure is_preferred is never None (needed for sort)
                is_preferred = bool(preferences and preferences.is_hotel_preferred(tile_id))
                base_score = tile.get("score", 0) or 0
                adjusted_score = base_score * 1.5 if is_preferred else base_score
                hotel_tiles.append(
                    {
                        "tile": tile,
                        "tile_id": tile_id,
                        "is_preferred": is_preferred,
                        "adjusted_score": adjusted_score,
                    }
                )

        # Sort by: preferred first, then by adjusted score
        hotel_tiles.sort(key=lambda x: (-x["is_preferred"], -x["adjusted_score"]))

        # Select best hotel (preferred tiles win)
        selected_hotel = hotel_tiles[0] if hotel_tiles else None
        hotel_tile = selected_hotel["tile"] if selected_hotel else None
        is_user_preferred = selected_hotel["is_preferred"] if selected_hotel else False

        # Log hotel selection result
        if selected_hotel:
            hotel_name = hotel_tile.get("title", "Unknown")[:30] if hotel_tile else "None"
            _debug_itinerary(
                f"🏨 Phase 6: Selected hotel '{hotel_name}' "
                f"(preferred={is_user_preferred}, score={selected_hotel['adjusted_score']:.2f})"
            )
        else:
            _debug_itinerary("🏨 Phase 6: No hotel tiles found")

        # Determine preference status
        preference_status = None
        if selected_hotel:
            preference_status = "user_preferred" if is_user_preferred else "ai_selected"

        # Find alternative if AI selected over user preference
        alternative_tile_id = None
        if len(hotel_tiles) > 1 and not is_user_preferred:
            # Check if there was a user-preferred option we didn't select
            user_preferred = next((h for h in hotel_tiles[1:] if h["is_preferred"]), None)
            if user_preferred:
                alternative_tile_id = user_preferred["tile_id"]
                preference_status = "ai_override"
                _debug_itinerary(
                    f"🏨 Phase 6: AI override - user preferred hotel not selected "
                    f"(alternative={alternative_tile_id[:20]})"
                )

        # Only add check-in/check-out blocks if user explicitly preferred a hotel
        # Tiles are suggestions in PLANNING mode - auto-selecting contradicts UX spec
        if hotel_tile and len(days) > 1 and not is_user_preferred:
            _debug_itinerary(
                f"🏨 Phase 6: Skipping hotel block - no user preference "
                f"({len(hotel_tiles)} hotels available as suggestions)"
            )

        if hotel_tile and len(days) > 1 and is_user_preferred:
            # Add check-in to Day 1 (after arrival)
            checkin_block = DayBlockOutput(
                id="checkin_001",
                period="afternoon",
                activity_type="check-in",
                summary=f"Check in: {hotel_tile.get('title', 'Hotel')}",
                hotel_name=hotel_tile.get("title"),
                logistics_details=hotel_tile.get("location_label"),
                booked_tile=hotel_tile,
                booking_category="hotel",
                # Preference attribution
                preference_status=preference_status,
                alternative_tile_id=alternative_tile_id,
            )
            days[0].blocks.append(checkin_block)

            # Add check-out to last day (before departure)
            checkout_block = DayBlockOutput(
                id="checkout_001",
                period="morning",
                activity_type="check-out",
                summary=f"Check out: {hotel_tile.get('title', 'Hotel')}",
                hotel_name=hotel_tile.get("title"),
                booked_tile=hotel_tile,
            )
            # Insert before departure block
            departure_idx = next(
                (i for i, b in enumerate(days[-1].blocks) if b.buffer_type == "departure"),
                len(days[-1].blocks),
            )
            days[-1].blocks.insert(departure_idx, checkout_block)

        return days

    # =========================================================================
    # Phase 6.5: Inline Constraint Tagging
    # =========================================================================

    def _apply_constraints_to_blocks(self, days: List[DayCardOutput]) -> List[DayCardOutput]:
        """
        Tag timeline blocks with relevant constraints for inline display.

        Adds active_constraints metadata to blocks so frontend can show
        constraint badges directly in the timeline.
        """
        from app.planner.specialist_registry import get as _get_config

        departure_day = len(days)
        _debug_itinerary(
            f"🏷️ Phase 6.5: Applying constraint tags to {len(days)} days, "
            f"departure_day={departure_day}"
        )

        for day_idx, day_card in enumerate(days):
            for block in day_card.blocks:
                constraints = []

                # Registry-driven no-fly buffer constraint tags
                activity_type = (block.activity_type or "").lower()
                specialist = (block.specialist_type or "").lower()

                _spec_config = _get_config(specialist) if specialist else None
                _has_nofly = _spec_config.has_nofly_buffer if _spec_config else False
                _has_altitude = _spec_config.has_altitude_buffer if _spec_config else False

                if _has_nofly and not block.is_buffer:
                    # Check if this is the last activity for this specialist before departure
                    is_last_for_specialist = not any(
                        any(
                            (b.specialist_type or "").lower() == specialist and not b.is_buffer
                            for b in dc.blocks
                        )
                        for dc in days[day_idx + 1 :]
                    )

                    # Last activity within 2 days of departure gets buffer warning
                    buffer_label = _spec_config.display_name or specialist.title()
                    if is_last_for_specialist and day_idx >= departure_day - 2:
                        constraints.append(
                            {
                                "id": "no_fly_buffer",
                                "severity": "warning",
                                "icon": "⚠️",
                                "title": "24h No-Fly Buffer",
                                "description": (
                                    f"Day {departure_day} departure requires "
                                    f"finishing {specialist} by 2pm today"
                                ),
                            }
                        )

                    # All activities for nofly specialists get safety info
                    if not constraints:
                        constraints.append(
                            {
                                "id": "surface_interval",
                                "severity": "info",
                                "icon": "ℹ️",
                                "title": f"{buffer_label}",
                                "description": "Scheduled with appropriate safety intervals",
                            }
                        )

                elif _has_altitude and not block.is_buffer:
                    buffer_label = _spec_config.display_name or specialist.title()
                    constraints.append(
                        {
                            "id": "altitude_buffer",
                            "severity": "info",
                            "icon": "🏔️",
                            "title": f"{buffer_label}",
                            "description": "Altitude acclimatization schedule applied",
                        }
                    )

                # Hiking activity constraints
                is_hiking = (
                    "hik" in activity_type or "trek" in activity_type or specialist == "hiking"
                )

                if is_hiking and not block.is_buffer:
                    # Intensity-based physical preparation
                    if block.intensity == "challenging":
                        constraints.append(
                            {
                                "id": "fitness_required",
                                "severity": "info",
                                "icon": "💪",
                                "title": "High Fitness Required",
                                "description": "Intermediate+ fitness level recommended",
                            }
                        )

                    # Weather window reminder for morning activities
                    if block.period == "morning":
                        constraints.append(
                            {
                                "id": "early_start_recommended",
                                "severity": "info",
                                "icon": "🌅",
                                "title": "Early Start",
                                "description": "Morning departure avoids afternoon weather changes",
                            }
                        )

                # Skiing activity constraints
                is_skiing = (
                    "ski" in activity_type or "snow" in activity_type or specialist == "skiing"
                )

                if is_skiing and not block.is_buffer:
                    summary_lower = (block.summary or "").lower()

                    # Off-piste/backcountry detection
                    if any(
                        term in summary_lower for term in ["off-piste", "backcountry", "freeride"]
                    ):
                        constraints.append(
                            {
                                "id": "avalanche_awareness",
                                "severity": "warning",
                                "icon": "🏔️",
                                "title": "Avalanche Terrain",
                                "description": (
                                    "Check avalanche bulletin - guide + safety gear required"
                                ),
                            }
                        )

                    # Skill level matching
                    if block.intensity == "challenging":
                        constraints.append(
                            {
                                "id": "advanced_terrain",
                                "severity": "info",
                                "icon": "⛷️",
                                "title": "Advanced Terrain",
                                "description": "Black diamond runs - advanced skills required",
                            }
                        )

                # Surfing activity constraints
                is_surfing = "surf" in activity_type or specialist == "surfing"

                if is_surfing and not block.is_buffer:
                    constraints.append(
                        {
                            "id": "tide_timing",
                            "severity": "info",
                            "icon": "🌊",
                            "title": "Check Conditions",
                            "description": "Verify swell/tide forecast before session",
                        }
                    )

                # Hotel check-in constraints with specialist context
                if block.activity_type == "check-in" and block.booked_tile:
                    # Collect specialist types from the trip
                    specialist_types = set()
                    for day_card in days:
                        for b in day_card.blocks:
                            if b.specialist_type and b.specialist_type not in (
                                "general",
                                "local_expert",
                            ):
                                specialist_types.add(b.specialist_type)

                    if specialist_types:
                        specialist_list = ", ".join(sorted(specialist_types))
                        constraints.append(
                            {
                                "id": "proximity_optimized",
                                "severity": "success",
                                "icon": "✓",
                                "title": "Location Optimized",
                                "description": f"Proximity to {specialist_list} activities",
                            }
                        )
                    else:
                        constraints.append(
                            {
                                "id": "proximity_optimized",
                                "severity": "success",
                                "icon": "✓",
                                "title": "Location Optimized",
                                "description": "Selected based on proximity to activities",
                            }
                        )

                # Attach constraints to block
                if constraints:
                    block.active_constraints = constraints
                    constraint_ids = [c["id"] for c in constraints]
                    _debug(
                        f"[ItineraryBuilder] 🏷️ ✅ Added {len(constraints)} constraints "
                        f"to block '{block.summary}': {constraint_ids}"
                    )

        return days

    # =========================================================================
    # Phase 6.75: FINAL Chronological Sorting
    # =========================================================================

    def _sort_blocks_chronologically(self, days: List[DayCardOutput]) -> List[DayCardOutput]:
        """
        FINAL sort: Ensure all blocks within each day are in chronological order.

        This runs AFTER all phases have added blocks (5.5, 5.25, 6) to ensure
        the final output is correctly ordered regardless of insertion order.

        Sort key:
        1. Logistics bracket: arrival(0) → activities(1) → departure(2)
        2. Time slot OR buffer sub-priority: morning < afternoon < evening < night
        """
        TIME_SLOT_ORDER = {"morning": 0, "afternoon": 1, "evening": 2, "night": 3}

        # Buffer types that pin to specific positions
        BUFFER_SORT_PRIORITY = {
            "arrival": (0, 0),  # First thing, before morning
            "check_in": (0, 1),  # Right after arrival
            "check-in": (0, 1),  # Alternative spelling
            "acclimatization": (1, 0),  # Activity-level, morning slot
            "surface_interval": (1, 1),  # Activity-level, between dives
            "no_fly_buffer": (1, 3),  # Activity-level, evening (end of day)
            "no_fly": (1, 3),  # Alternative spelling
            "departure": (2, 0),  # Last thing
            "check_out": (2, 0),  # Same as departure
            "check-out": (2, 0),  # Alternative spelling
        }

        for day in days:
            day.blocks.sort(
                key=lambda b: (
                    # Layer 1: Logistics bracket (0=arrival, 1=activities, 2=departure)
                    BUFFER_SORT_PRIORITY.get(getattr(b, "buffer_type", None), (1, 1))[0],
                    # Layer 2: Buffer sub-priority OR time slot
                    (
                        BUFFER_SORT_PRIORITY.get(getattr(b, "buffer_type", None), (1, 1))[1]
                        if getattr(b, "buffer_type", None) in BUFFER_SORT_PRIORITY
                        else TIME_SLOT_ORDER.get(
                            (getattr(b, "period", None) or "afternoon").lower(), 1
                        )
                    ),
                )
            )

        _debug(f"[ItineraryBuilder] 🔄 Final sort applied to {len(days)} days")
        return days

    @staticmethod
    def _is_user_browse_block(block: DayBlockOutput) -> bool:
        if block.activity_provenance == "user_browse_added":
            return True
        tile = block.booked_tile if isinstance(block.booked_tile, dict) else {}
        meta = tile.get("meta") if isinstance(tile.get("meta"), dict) else {}
        for raw_source in (meta.get("source"), tile.get("source")):
            if isinstance(raw_source, str) and raw_source.strip().lower() in (
                "browse_add",
                "user_browse_added",
            ):
                return True
        return False

    @staticmethod
    def _normalize_map_type_key(value: Any) -> Optional[str]:
        return normalize_poi_type_key(value)

    @classmethod
    def _canonical_map_type(cls, raw: Any) -> Optional[str]:
        return canonical_poi_type(raw)

    @classmethod
    def _map_type_from_booked_tile(cls, tile: dict[str, Any]) -> Optional[str]:
        meta = tile.get("meta") if isinstance(tile.get("meta"), dict) else {}

        for candidate in (
            meta.get("map_type"),
            tile.get("map_type"),
            tile.get("browse_category"),
            tile.get("category"),
            meta.get("category"),
        ):
            canonical = cls._canonical_map_type(candidate)
            if canonical:
                return canonical

        tags = tile.get("tags")
        if isinstance(tags, list):
            for tag in tags:
                canonical = cls._canonical_map_type(tag)
                if canonical:
                    return canonical

        return None

    @classmethod
    def _resolve_block_map_type(cls, block: DayBlockOutput) -> Optional[str]:
        canonical_direct = cls._canonical_map_type(block.map_type)
        if canonical_direct:
            return canonical_direct

        canonical_specialist = cls._canonical_map_type(block.specialist_type)
        if canonical_specialist:
            return canonical_specialist

        tile = block.booked_tile if isinstance(block.booked_tile, dict) else {}
        from_tile = cls._map_type_from_booked_tile(tile)
        if from_tile:
            return from_tile

        # Last resort: only accept activity_type if it already matches taxonomy.
        return cls._canonical_map_type(block.activity_type)

    def _annotate_activity_axes(self, days: List[DayCardOutput]) -> List[DayCardOutput]:
        non_activity_types = {
            "arrival",
            "departure",
            "check-in",
            "check-out",
            "check_in",
            "check_out",
            "free_day",
            "rest_day",
            "buffer",
            "decompression_buffer",
        }

        for day in days:
            for block in day.blocks:
                if block.is_buffer:
                    block.activity_domain = None
                    block.activity_provenance = None
                    block.map_type = None
                    continue

                block_type = (block.activity_type or "").strip().lower()
                if block_type in non_activity_types:
                    block.activity_domain = None
                    block.activity_provenance = None
                    block.map_type = None
                    continue

                if block.activity_domain is None:
                    specialist = (block.specialist_type or "").strip().lower()
                    block.activity_domain = (
                        "tier1" if specialist in _TIER1_SPECIALIST_NAMES else "tier2"
                    )

                if block.activity_provenance is None:
                    block.activity_provenance = (
                        "user_browse_added" if self._is_user_browse_block(block) else "ai_suggested"
                    )

                block.map_type = self._resolve_block_map_type(block)

        return days

    # =========================================================================
    # Phase 7: Temporal BuilderConflict Detection
    # =========================================================================

    def _detect_temporal_conflicts(self, days: List[DayCardOutput]) -> List[BuilderConflict]:
        """Detect temporal capacity conflicts after placement."""
        conflicts = []

        for day in days:
            # Estimate total hours
            total_hours = 0.0
            specialists = set()

            for block in day.blocks:
                if block.is_buffer:
                    continue

                # Parse duration
                duration = 3.0  # Default
                if block.duration:
                    try:
                        duration = float(block.duration.replace("h", ""))
                    except (ValueError, AttributeError):
                        pass

                total_hours += duration
                if block.specialist_type:
                    specialists.add(block.specialist_type)

            if total_hours > DAY_CAPACITY_HOURS:
                conflicts.append(
                    BuilderConflict(
                        type="temporal_capacity",
                        severity=ConstraintSeverity.STRONG,
                        day=day.day_number,
                        specialists=list(specialists),
                        message=(
                            f"Day {day.day_number} has {total_hours:.1f}h of activities "
                            f"(max {DAY_CAPACITY_HOURS}h)"
                        ),
                        overflow_hours=total_hours - DAY_CAPACITY_HOURS,
                    )
                )

        return conflicts

    # =========================================================================
    # Resolution Generation
    # =========================================================================

    def _generate_resolutions(
        self, conflicts: List[BuilderConflict], current_days: int
    ) -> List[Resolution]:
        """Generate resolution options for conflicts."""
        resolutions = []

        # Check if extending trip would help (insufficient days OR constraint clash)
        needs_more_days = any(
            c.type in ("insufficient_days", "constraint_clash") for c in conflicts
        )
        if needs_more_days:
            resolutions.append(
                Resolution(
                    action="extend_trip",
                    description=f"Extend trip to {current_days + 2} days",
                    new_duration=current_days + 2,
                    feasibility="recommended",
                )
            )

        # Collect specialists involved in conflicts
        all_specialists = set()
        for c in conflicts:
            all_specialists.update(c.specialists)

        # Offer to focus on one specialist
        for specialist in all_specialists:
            resolutions.append(
                Resolution(
                    action="reduce_activities",
                    description=f"Focus on {specialist} only",
                    keep_specialist=specialist,
                    feasibility="possible",
                )
            )

        return resolutions

    # =========================================================================
    # Overview Computation
    # =========================================================================

    def _compute_overview(self, days: List[DayCardOutput]) -> ItineraryOverviewOutput:
        """Compute overview stats from day cards."""
        total_days = len(days)

        # Count activity blocks
        activity_count = 0
        specialists = set()

        for day in days:
            for block in day.blocks:
                if not block.is_buffer and block.specialist_type:
                    activity_count += 1
                    specialists.add(block.specialist_type)

        # Determine structure
        if len(specialists) > 1:
            base_structure = "Multi-activity adventure"
        else:
            base_structure = "Single base + day excursions"

        # Density
        usable_days = max(0, total_days - 2) + 0.8
        density = activity_count / usable_days if usable_days > 0 else 0

        if density <= 1:
            activity_density = "1 major activity/day"
        elif density <= 2:
            activity_density = "1-2 activities/day"
        else:
            activity_density = "Action-packed schedule"

        return ItineraryOverviewOutput(
            duration_label=f"{total_days} days",
            base_structure=base_structure,
            activity_density=activity_density,
        )

    # =========================================================================
    # Assumptions Computation
    # =========================================================================

    def _compute_assumptions(
        self,
        days: List[DayCardOutput],
        merged_constraints: List[MergedConstraint],
    ) -> ItineraryAssumptionsOutput:
        """Derive planning assumptions from builder state for frontend display."""
        assumptions: List[str] = []
        flexible_elements: List[str] = []

        total_days = len(days)
        usable_days = max(0, total_days - 2) + 0.8

        # Activities-per-day assumption
        activity_count = sum(
            1
            for d in days
            for b in d.blocks
            if not b.is_buffer
            and b.activity_type not in ("arrival", "departure", "check-in", "check-out", "free_day")
        )
        if usable_days > 0:
            avg = round(activity_count / usable_days, 1)
            assumptions.append(f"{avg} activities per day on average")

        # Constraints applied
        blocking = [c for c in merged_constraints if c.severity == ConstraintSeverity.BLOCKING]
        if blocking:
            assumptions.append(
                f"{len(blocking)} safety constraint{'s' if len(blocking) != 1 else ''} applied"
            )

        # Hotel check-in assumption
        has_checkin = any(
            b.activity_type in ("check-in", "check_in") for d in days for b in d.blocks
        )
        if has_checkin:
            assumptions.append("Hotel check-in at 3 PM")

        # Free days as flexible elements
        free_days = [d for d in days if any(b.activity_type == "free_day" for b in d.blocks)]
        if free_days:
            flexible_elements.append(
                f"{len(free_days)} free day{'s' if len(free_days) != 1 else ''} available to fill"
            )

        # Unbooked tiles as flexible elements
        unbooked = sum(
            1
            for d in days
            for b in d.blocks
            if not b.is_buffer
            and not b.booked_tile
            and b.activity_type not in ("arrival", "departure", "check-in", "check-out", "free_day")
        )
        if unbooked:
            flexible_elements.append(f"{unbooked} activities with alternatives available")

        return ItineraryAssumptionsOutput(
            assumptions=assumptions[:4],  # Max 4 per schema
            flexible_elements=flexible_elements[:3],  # Max 3 per schema
        )

    # =========================================================================
    # Helpers
    # =========================================================================

    def _parse_date(self, date_str: Optional[str]) -> Optional[date]:
        """Parse ISO date string to date object."""
        if not date_str:
            return None

        try:
            # Handle ISO format (YYYY-MM-DD)
            return datetime.fromisoformat(date_str.split("T")[0]).date()
        except (ValueError, AttributeError):
            return None


# =============================================================================
# Post-Arrangement Constraint Recomputation (Stage 14)
# =============================================================================


# Only this tag is position-dependent; all others are intrinsic to the block
_POSITION_DEPENDENT_TAGS = frozenset({"no_fly_buffer"})


def _recompute_nofly_tags(day_cards: list[dict]) -> list[dict]:
    """Strip and reapply no_fly_buffer tags based on new block positions.

    Only `no_fly_buffer` is position-dependent — it applies to the last
    nofly-specialist block within 2 days of departure. `surface_interval`
    is intrinsic (property of the activity type) and is never stripped.
    """
    from app.planner.specialist_registry import get as get_config

    departure_day = max((dc["day_number"] for dc in day_cards), default=0)
    if not departure_day:
        return day_cards

    # Build map: specialist -> max day_number for nofly-specialist blocks
    last_day_for_specialist: dict[str, int] = {}
    for dc in day_cards:
        for block in dc.get("blocks", []):
            if block.get("is_buffer"):
                continue
            specialist = (block.get("specialist_type") or "").lower()
            cfg = get_config(specialist) if specialist else None
            if cfg and cfg.has_nofly_buffer:
                prev = last_day_for_specialist.get(specialist, 0)
                if dc["day_number"] > prev:
                    last_day_for_specialist[specialist] = dc["day_number"]

    # Recompute tags on each nofly-specialist block
    for dc in day_cards:
        for block in dc.get("blocks", []):
            if block.get("is_buffer"):
                continue
            specialist = (block.get("specialist_type") or "").lower()
            cfg = get_config(specialist) if specialist else None
            if not (cfg and cfg.has_nofly_buffer):
                continue

            # Strip only position-dependent tags
            existing = block.get("active_constraints", [])
            kept = [c for c in existing if c.get("id") not in _POSITION_DEPENDENT_TAGS]

            # Reapply no_fly_buffer if this is the last block for its specialist
            # and it's within 2 days of departure
            is_last = dc["day_number"] == last_day_for_specialist.get(specialist, 0)
            day_idx = dc["day_number"] - 1  # 0-indexed for comparison
            if is_last and day_idx >= departure_day - 2:
                kept.append(
                    {
                        "id": "no_fly_buffer",
                        "severity": "warning",
                        "icon": "\u26a0\ufe0f",
                        "title": "24h No-Fly Buffer",
                        "description": (
                            f"Day {departure_day} departure requires "
                            f"finishing {specialist} by 2pm today"
                        ),
                    }
                )

            # Ensure nofly-specialist blocks always have surface_interval.
            # The builder makes no_fly_buffer and surface_interval mutually
            # exclusive — if we stripped no_fly_buffer and the block never had
            # surface_interval, add it back as the intrinsic fallback.
            # Guard: skip if no_fly_buffer was just (re)applied — maintain
            # mutual exclusivity matching the builder's Phase 6.5 behavior.
            has_nofly = any(c.get("id") == "no_fly_buffer" for c in kept)
            if not has_nofly and not any(c.get("id") == "surface_interval" for c in kept):
                buffer_label = cfg.display_name or specialist.title()
                kept.append(
                    {
                        "id": "surface_interval",
                        "severity": "info",
                        "icon": "\u2139\ufe0f",
                        "title": f"{buffer_label}",
                        "description": ("Scheduled with appropriate safety intervals"),
                    }
                )

            block["active_constraints"] = kept

    return day_cards


def _get_cross_domain_specialists() -> tuple[set[str], set[str]]:
    """Derive source and target specialist sets from registry cross_domain_blocks.

    Returns (source_specialists, target_specialists) where source has
    cross_domain_blocks targeting the targets.
    """
    from app.planner.specialist_registry import SPECIALIST_REGISTRY

    sources: set[str] = set()
    targets: set[str] = set()
    for topic, cfg in SPECIALIST_REGISTRY.items():
        for xd in cfg.cross_domain_blocks:
            sources.add(topic)
            targets.update(xd.target_specialists)
    return sources, targets


def _detect_stale_buffers(day_cards: list[dict]) -> tuple[list[dict], list[dict]]:
    """Detect orphaned or missing cross-domain buffers after rearrangement.

    Mutates orphaned buffer blocks (updates summary, clears constraints).
    Returns (updated_day_cards, violations).
    """
    source_specialists, target_specialists = _get_cross_domain_specialists()
    violations: list[dict] = []

    # Map day_number -> specialist types (non-buffer activity blocks)
    day_specialists: dict[int, set[str]] = {}
    # Map day_number -> list of buffer block references
    day_buffers: dict[int, list[dict]] = {}

    for dc in day_cards:
        specs: set[str] = set()
        buffers: list[dict] = []
        for block in dc.get("blocks", []):
            if block.get("is_buffer"):
                buffers.append(block)
            else:
                st = (block.get("specialist_type") or "").lower()
                if st:
                    specs.add(st)
        day_specialists[dc["day_number"]] = specs
        day_buffers[dc["day_number"]] = buffers

    sorted_days = sorted(day_specialists.keys())

    def _mark_orphaned(buf: dict, day_num: int, reason: str) -> None:
        """Mutate an orphaned buffer block and emit a violation."""
        buf["summary"] = "Rest Day \u2014 buffer no longer required at this position"
        buf["constraints"] = []
        violations.append(
            {
                "block_id": buf.get("id", ""),
                "violation_code": "ORPHANED_BUFFER",
                "severity": "warning",
                "message": reason,
                "target_day": day_num,
            }
        )

    # Check 1: Orphaned rest_day buffers
    for day_num, buffers in day_buffers.items():
        for buf in buffers:
            if buf.get("buffer_type") != "rest_day":
                continue
            has_source_before = any(
                day_specialists.get(d, set()) & source_specialists
                for d in sorted_days
                if d < day_num
            )
            has_target_after = any(
                day_specialists.get(d, set()) & target_specialists
                for d in sorted_days
                if d > day_num
            )
            if not (has_source_before and has_target_after):
                _mark_orphaned(
                    buf,
                    day_num,
                    f"Rest day buffer on Day {day_num} may no longer be "
                    f"needed \u2014 the activity phases have moved",
                )

    # Check 2: Missing cross-domain buffer
    source_days = [d for d in sorted_days if day_specialists.get(d, set()) & source_specialists]
    target_days = [d for d in sorted_days if day_specialists.get(d, set()) & target_specialists]

    if source_days and target_days:
        last_source = max(source_days)
        first_target_after = next((d for d in target_days if d > last_source), None)
        if first_target_after is not None and first_target_after - last_source <= 2:
            # Check for rest_day buffer between them
            has_buffer = any(
                any(b.get("buffer_type") == "rest_day" for b in day_buffers.get(d, []))
                for d in range(last_source + 1, first_target_after)
            )
            if not has_buffer:
                # Find the first target block on that day for block_id
                target_dc = next(
                    (dc for dc in day_cards if dc["day_number"] == first_target_after),
                    None,
                )
                target_block_id = ""
                if target_dc:
                    for b in target_dc.get("blocks", []):
                        st = (b.get("specialist_type") or "").lower()
                        if st in target_specialists:
                            target_block_id = b.get("id", "")
                            break
                source_name = next(
                    (
                        s.title()
                        for s in day_specialists.get(last_source, set()) & source_specialists
                    ),
                    "Activity",
                )
                target_name = next(
                    (
                        s.title()
                        for s in day_specialists.get(first_target_after, set()) & target_specialists
                    ),
                    "altitude activity",
                )
                violations.append(
                    {
                        "block_id": target_block_id,
                        "violation_code": "MISSING_CROSS_DOMAIN_BUFFER",
                        "severity": "warning",
                        "message": (
                            f"{source_name} on Day {last_source} followed "
                            f"by {target_name} on Day {first_target_after} "
                            f"without a rest day buffer"
                        ),
                        "target_day": first_target_after,
                    }
                )

    # Check 3: Orphaned acclimatization buffers
    for day_num, buffers in day_buffers.items():
        for buf in buffers:
            if buf.get("buffer_type") != "acclimatization":
                continue
            has_altitude_soon = any(
                day_specialists.get(d, set()) & target_specialists
                for d in range(day_num + 1, day_num + 3)
                if d in day_specialists
            )
            if not has_altitude_soon:
                _mark_orphaned(
                    buf,
                    day_num,
                    f"Acclimatization day on Day {day_num} is no longer "
                    f"before any altitude activities",
                )

    # Check 4: Source specialist co-located with its own buffer block.
    # A rest_day buffer hosting a source-specialist activity is compromised —
    # the buffer cannot provide cross-domain separation when the trigger is on the same day.
    for dc in day_cards:
        day_num = dc["day_number"]
        buffers_on_day = day_buffers.get(day_num, [])
        if not buffers_on_day:
            continue
        specs_on_day = day_specialists.get(day_num, set())
        conflicting = specs_on_day & source_specialists
        if not conflicting:
            continue
        for buf in buffers_on_day:
            if buf.get("buffer_type") != "rest_day":
                continue
            source_name = next(iter(conflicting)).title()
            buf["summary"] = (
                f"Rest Day \u2014 {source_name} activity present, "
                f"buffer may not provide adequate recovery"
            )
            buf["constraints"] = []
            violations.append(
                {
                    "block_id": buf.get("id", ""),
                    "violation_code": "BUFFER_COMPROMISED",
                    "severity": "warning",
                    "message": (
                        f"{source_name} activity on Day {day_num} compromises "
                        f"the cross-domain buffer \u2014 consider moving it to another day"
                    ),
                    "target_day": day_num,
                }
            )

    return day_cards, violations


def recompute_constraints_after_arrangement(
    day_cards: list[dict],
    trip_inputs: object,
) -> tuple[list[dict], list[dict]]:
    """Recompute position-dependent constraint tags and detect stale buffers
    after a block arrangement. Pure Python, no LLM, <50ms.

    Called from apply_arrangement endpoint between _apply_moves_to_cards
    and save_document_data.

    Args:
        day_cards: Rearranged day_cards (list of dicts from _apply_moves_to_cards)
        trip_inputs: DocumentTripInputs (used for future extensions; currently
                     departure_day is derived from day_cards)

    Returns:
        (updated_day_cards, new_violations) where:
        - updated_day_cards has recomputed active_constraints on relevant blocks
        - new_violations is a list of BlockViolation-compatible dicts
    """
    # Pass 1: Recompute position-dependent constraint tags
    day_cards = _recompute_nofly_tags(day_cards)

    # Pass 2: Detect stale/missing buffer blocks
    day_cards, buffer_violations = _detect_stale_buffers(day_cards)

    return day_cards, buffer_violations
