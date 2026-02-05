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

Timezone Handling:
- Infrastructure added for timezone-aware constraint calculations
- Currently assumes local destination time (sufficient for MVP)
- Enable full timezone support by calling normalize_to_destination_tz()
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from app.debug_utils import _debug, _debug_itinerary
from app.planner.state import ConstraintSeverity

logger = logging.getLogger(__name__)

# =============================================================================
# Timezone Handling Infrastructure
# =============================================================================

# Common destination timezone offsets (UTC offset in hours)
# Note: For production, consider using pytz or zoneinfo for DST handling
DESTINATION_TIMEZONES: Dict[str, float] = {
    # Asia-Pacific
    "bali": 8.0,  # WITA (UTC+8)
    "indonesia": 8.0,
    "thailand": 7.0,
    "bangkok": 7.0,
    "phuket": 7.0,
    "vietnam": 7.0,
    "singapore": 8.0,
    "japan": 9.0,
    "tokyo": 9.0,
    "niseko": 9.0,
    "australia": 10.0,  # AEST
    "sydney": 10.0,
    "melbourne": 10.0,
    "maldives": 5.0,
    "dubai": 4.0,
    "uae": 4.0,
    # Europe
    "london": 0.0,  # GMT (no DST adjustment)
    "paris": 1.0,
    "france": 1.0,
    "chamonix": 1.0,
    "switzerland": 1.0,
    "zermatt": 1.0,
    "austria": 1.0,
    "spain": 1.0,
    "italy": 1.0,
    "greece": 2.0,
    # Americas
    "new york": -5.0,
    "usa": -5.0,  # EST default
    "california": -8.0,
    "los angeles": -8.0,
    "colorado": -7.0,
    "aspen": -7.0,
    "hawaii": -10.0,
    "mexico": -6.0,
    "cancun": -5.0,
    "costa rica": -6.0,
    "brazil": -3.0,
    "argentina": -3.0,
    "patagonia": -3.0,
    "chile": -4.0,
    # Africa/Middle East
    "egypt": 2.0,
    "red sea": 2.0,
    "south africa": 2.0,
    "kenya": 3.0,
    "morocco": 1.0,
    # South Asia
    "nepal": 5.75,  # UTC+5:45
    "india": 5.5,
    "sri lanka": 5.5,
}


def get_destination_utc_offset(destination: str) -> float:
    """
    Get UTC offset for a destination.

    Args:
        destination: Destination name (case-insensitive)

    Returns:
        UTC offset in hours. Defaults to 0.0 (UTC) if unknown.
    """
    if not destination:
        return 0.0

    dest_lower = destination.lower().strip()

    # Direct match
    if dest_lower in DESTINATION_TIMEZONES:
        return DESTINATION_TIMEZONES[dest_lower]

    # Partial match
    for key, offset in DESTINATION_TIMEZONES.items():
        if key in dest_lower or dest_lower in key:
            return offset

    # Default to UTC
    logger.debug(f"[Timezone] Unknown destination '{destination}', using UTC")
    return 0.0


def normalize_to_destination_tz(
    dt: datetime,
    destination: str,
    source_offset: float = 0.0,
) -> datetime:
    """
    Convert datetime to destination local time.

    Args:
        dt: Datetime to convert (assumed naive or with source_offset)
        destination: Destination name for timezone lookup
        source_offset: UTC offset of source timezone (default: 0.0 = UTC)

    Returns:
        Datetime adjusted to destination local time (naive datetime).

    Note:
        For MVP, this function is available but not actively used.
        Current implementation assumes all times are in destination local time.
        Enable for cross-timezone flight calculations if needed.
    """
    dest_offset = get_destination_utc_offset(destination)

    # Calculate total adjustment
    adjustment_hours = dest_offset - source_offset

    # Apply adjustment
    return dt + timedelta(hours=adjustment_hours)


def calculate_hours_between(
    time1: datetime,
    time2: datetime,
    destination: str = "",
    use_timezone: bool = False,
) -> float:
    """
    Calculate hours between two times, optionally with timezone awareness.

    Args:
        time1: Earlier datetime
        time2: Later datetime
        destination: Destination for timezone lookup (used if use_timezone=True)
        use_timezone: Whether to apply timezone normalization

    Returns:
        Hours between the two times (positive if time2 > time1).

    Note:
        When use_timezone=False (default), assumes both times are in local time.
        This is the current MVP behavior.
    """
    if use_timezone and destination:
        # Normalize both to destination time
        time1 = normalize_to_destination_tz(time1, destination)
        time2 = normalize_to_destination_tz(time2, destination)

    delta = time2 - time1
    return delta.total_seconds() / 3600


# =============================================================================
# Constraint Rule Normalization
# =============================================================================
# LLM may output constraint rules with various naming conventions.
# Builder normalizes to canonical rules for consistent detection.

CONSTRAINT_ALIASES: Dict[str, List[str]] = {
    # Cross-domain: diving + altitude conflict
    "no_altitude_after_dive": [
        "no_altitude_24h",
        "altitude_buffer",
        "no_altitude_after_diving",
        "altitude_restriction_after_dive",
    ],
    # Diving: no-fly buffer
    "min_24h_buffer_after_dive": [
        "no_fly_24h",
        "flight_buffer_24h",
        "no_fly_after_diving",
        "24h_no_fly_after_diving",
        "no_fly_buffer",
    ],
    # Surface interval
    "surface_interval": [
        "min_18h_surface_interval",
        "dive_surface_interval",
    ],
}


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
    aliases = CONSTRAINT_ALIASES.get(canonical_rule, [])
    all_names = [canonical_rule] + aliases

    for c in constraints:
        rule_lower = c.rule.lower().replace("-", "_").replace(" ", "_")
        for name in all_names:
            if rule_lower == name.lower() or name.lower() in rule_lower:
                return c
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

    # Rich content
    image_url: Optional[str] = None
    duration: Optional[str] = None
    coordinates: Optional[Dict[str, float]] = None  # {lat, lng}

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


class DayCardOutput(BaseModel):
    """Output day card - matches frontend DayCard interface."""

    day_number: int
    label: str
    blocks: List[DayBlockOutput] = Field(default_factory=list)


class ItineraryOverviewOutput(BaseModel):
    """Overview stats for itinerary."""

    duration_label: str
    base_structure: str
    activity_density: str


class Conflict(BaseModel):
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


class ItineraryResult(BaseModel):
    """Result from itinerary builder."""

    success: bool
    day_cards: List[DayCardOutput] = Field(default_factory=list)
    overview: Optional[ItineraryOverviewOutput] = None
    conflicts: List[Conflict] = Field(default_factory=list)
    resolutions: List[Resolution] = Field(default_factory=list)
    error: Optional[str] = None
    dropped_preferred_count: int = 0  # Activities that couldn't fit in available days
    warnings: List[str] = Field(
        default_factory=list
    )  # User-facing warnings (e.g., "Reduced diving from 4 to 1")


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


@dataclass
class PreferenceOverrideInput:
    """User heart preferences for tile weighting."""

    preferred_hotel_ids: List[str] = field(default_factory=list)
    preferred_activity_ids: List[str] = field(default_factory=list)
    preferred_flight_ids: List[str] = field(default_factory=list)

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
            activities, constraints = self._extract_specialist_content(input_data.strategy_sections)

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
                _debug(
                    f"[ItineraryBuilder] ⚠️ Conflict detected: {len(early_conflicts)} conflicts, "
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
                    error="CONSTRAINT_CONFLICT",
                )

            # Phase 3: Place temporal anchors (arrival/departure)
            days = self._place_anchors(days, input_data.tiles, input_data.origin)

            # Phase 4: Inject safety buffers
            days = self._inject_safety_buffers(days, merged_constraints)

            # Phase 5: Distribute activities across days (interleaved)
            days = self._distribute_activities(days, activities)

            # Phase 5.5: Handle empty days (add FreeDay placeholders)
            days = self._handle_empty_days(days, input_data.tiles)

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

            # Phase 7: Detect post-placement conflicts (overflow)
            conflicts = self._detect_temporal_conflicts(days)
            if conflicts:
                resolutions = self._generate_resolutions(conflicts, len(days))
                # For now, still return success but include warnings
                # In future, could block if severity is BLOCKING

            # Compute overview
            overview = self._compute_overview(days)

            _debug_itinerary(
                f"✅ Success: generated {len(days)} day cards with "
                f"{sum(len(d.blocks) for d in days)} total blocks"
            )
            return ItineraryResult(
                success=True,
                day_cards=days,
                overview=overview,
                conflicts=conflicts,
                resolutions=[],
                dropped_preferred_count=dropped_preferred_count,
                warnings=self._warnings,
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

            # Default labels
            if day_num == 1:
                label = "Arrival Day"
            elif day_num == duration:
                label = "Departure Day"
            else:
                label = f"Day {day_num}"

            days.append(
                DayCardOutput(
                    day_number=day_num,
                    label=label,
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

    def _merge_constraints(self, constraints: List[Dict[str, Any]]) -> List[MergedConstraint]:
        """Merge constraints from all specialists with priority."""
        merged = []

        for c in constraints:
            rule = c.get("rule", "")
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
    # Phase 2b: Early Conflict Detection + Partial Schedule
    # =========================================================================

    def _detect_early_conflicts(
        self,
        days: List[DayCardOutput],
        activities_by_specialist: Dict[str, List[ActivityBlock]],
        constraints: List[MergedConstraint],
        tiles: Dict[str, Any],
        origin: Optional[str],
    ) -> Tuple[List[Conflict], List[DayCardOutput]]:
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
            buffer_days = 1
            _debug(f"[ItineraryBuilder] No-fly constraint found: rule={nofly_constraint.rule}")

        # Cross-domain check: diving + high-altitude activity conflict
        diving_present = "diving" in activities_by_specialist
        altitude_activities = ["hiking", "trekking", "mountaineering", "skiing"]
        altitude_specialists_present = [
            spec for spec in altitude_activities if spec in activities_by_specialist
        ]

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

            # Layer 2 defense: Only apply altitude buffer for HIGH-ALTITUDE destinations
            # Low-altitude destinations (Bali, Caribbean, etc.) don't need this buffer
            if altitude_constraint:
                HIGH_ALTITUDE_DESTINATIONS = {
                    "nepal",
                    "everest",
                    "annapurna",
                    "ladakh",
                    "leh",
                    "cusco",
                    "peru",
                    "machu picchu",
                    "bolivia",
                    "la paz",
                    "kilimanjaro",
                    "tanzania",
                    "mt kenya",
                    "switzerland",
                    "chamonix",
                    "mont blanc",
                    "zermatt",
                    "patagonia",
                    "aconcagua",
                    "colorado",
                    "tibet",
                }
                dest_lower = (self.destination or "").lower()
                is_high_altitude = any(kw in dest_lower for kw in HIGH_ALTITUDE_DESTINATIONS)

                if not is_high_altitude:
                    _debug(
                        f"[ItineraryBuilder] Skipping altitude buffer - "
                        f"low-altitude destination: {self.destination}"
                    )
                    altitude_constraint = None  # Disable for this trip

            if altitude_constraint:
                # Need additional buffer day between diving and high-altitude activities
                diving_days = len(activities_by_specialist.get("diving", []))
                altitude_days = sum(
                    len(activities_by_specialist.get(spec, [])) for spec in altitude_activities
                )
                altitude_buffer = 1  # 24h buffer between diving and altitude

                # Account for arrival/departure days
                usable_days = total_days - 2

                # Calculate required days for diving + buffer + altitude activities
                required_for_combo = diving_days + altitude_buffer + altitude_days
                if required_for_combo > usable_days:
                    cross_domain_conflict = True
                    conflicts.append(
                        Conflict(
                            type="constraint_clash",
                            severity=ConstraintSeverity.BLOCKING,
                            specialists=["diving"] + altitude_specialists_present,
                            message=(
                                f"Cannot fit diving ({diving_days} days) + 24h buffer + "
                                f"altitude activities ({altitude_days} days) "
                                f"in {usable_days} activity days. "
                                f"Need {required_for_combo} days."
                            ),
                        )
                    )

        # Account for arrival/departure days
        usable_days = total_days - 2  # First and last day are partial

        # FIX: No-fly buffer only affects DIVING placement, not total capacity
        # Day 7 can still have hiking even though diving is blocked
        diving_activities = activities_by_specialist.get("diving", [])
        diving_slots = usable_days - buffer_days if nofly_constraint else usable_days

        # Auto-truncate diving activities to fit available slots (no conflict)
        if len(diving_activities) > diving_slots:
            original_count = len(diving_activities)
            activities_by_specialist["diving"] = diving_activities[:diving_slots]
            logger.info(
                f"[ITINERARY] ⚠️ Auto-reduced diving: {original_count} → {diving_slots} "
                f"(no-fly buffer requires finishing by day {total_days - 1})"
            )
            # Track warning for user display
            if diving_slots == 0:
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
        max_capacity = usable_days * MAX_BLOCKS_PER_DAY
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
        altitude_activities = ["hiking", "trekking", "mountaineering", "skiing"]

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
                    activity_type="unschedulable",
                    summary=activity.title,
                    specialist_type=specialist,
                    is_buffer=False,
                    intensity=activity.intensity,
                    image_url=activity.image_url,
                    unschedulable=True,
                    unschedulable_reason=reason,
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
        self, days: List[DayCardOutput], constraints: List[MergedConstraint]
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
                # Acclimatization on day 3 for high-altitude trips
                if len(days) >= 4:
                    accl_day_idx = 2  # Day 3 (0-indexed)
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
                        specialist_type="hiking",
                        intensity="light",
                    )
                    days[accl_day_idx].blocks.insert(0, buffer_block)

        return days

    # =========================================================================
    # Phase 5: Activity Distribution
    # =========================================================================

    def _distribute_activities(
        self,
        days: List[DayCardOutput],
        activities_by_specialist: Dict[str, List[ActivityBlock]],
    ) -> List[DayCardOutput]:
        """
        Distribute activities from multiple specialists across days.

        Strategy:
        1. Calculate available slots per day (respecting buffers)
        2. Weight and sort activities by user preference (preferred first)
        3. Alternate between specialists for variety
        4. Respect max activities per day (2-3)
        """
        if not activities_by_specialist:
            return days

        # Get available days (exclude buffer days that block all activities)
        available_day_indices = []
        for i, day in enumerate(days):
            # Skip arrival day for major activities
            if i == 0:
                continue
            # Skip departure day for major activities
            if i == len(days) - 1:
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

        # Even distribution: spread activities across all available days
        # Strategy: cycle through days, placing 1 activity per day per round
        # This ensures Days 6-7 get activities before Days 2-3 get their 2nd
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
            day_idx = available_day_indices[day_ptr % len(available_day_indices)]
            current_day = days[day_idx]
            current_specialist = specialists[specialist_ptr % len(specialists)]

            # Check if day is truly full (at max capacity)
            non_buffer_blocks = [b for b in current_day.blocks if not b.is_buffer]
            if len(non_buffer_blocks) >= MAX_BLOCKS_PER_DAY:
                day_ptr += 1
                if day_ptr >= len(available_day_indices):
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

                # Create block with preference attribution
                block = DayBlockOutput(
                    id=f"act_{current_specialist}_{day_idx}_{len(current_day.blocks)}",
                    period=periods[period_ptr % len(periods)],
                    activity_type=activity.title.lower().replace(" ", "_"),
                    intensity=activity.intensity,
                    summary=activity.title,
                    specialist_type=current_specialist,
                    image_url=activity.image_url,
                    duration=f"{activity.duration_hours}h" if activity.duration_hours else None,
                    constraints=activity.constraints,
                    # Preference attribution for frontend badge
                    preference_status=preference_status,
                )

                if activity.coordinates:
                    block.coordinates = {
                        "lat": activity.coordinates[1],
                        "lng": activity.coordinates[0],
                    }

                current_day.blocks.append(block)
                specialist_count_per_day[day_idx][current_specialist] += 1
                period_ptr += 1

                # EVEN DISTRIBUTION: Always advance to next day after placing
                # This spreads activities across all days before filling any day
                day_ptr += 1

            # Rotate specialist for variety
            specialist_ptr += 1

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
    ) -> List[DayCardOutput]:
        """
        Phase 5.5: Add FreeDay placeholders for days without activities.

        For each day (excluding arrival/departure) that has no activity blocks,
        insert a free_day block so the timeline never appears empty.
        """
        # Count available activity tiles for reference in the placeholder
        activity_count = sum(
            1
            for tile in tiles.values()
            if isinstance(tile, dict) and tile.get("type") == "activity"
        )

        for i, day in enumerate(days):
            # Skip arrival day (first) and departure day (last)
            if i == 0 or i == len(days) - 1:
                continue

            # Check if day has any non-buffer, non-logistics activity blocks
            has_activity = any(
                not b.is_buffer
                and b.activity_type not in ("check-in", "check-out", "arrival", "departure")
                for b in day.blocks
            )

            if not has_activity:
                # Create FreeDay placeholder block
                free_day_block = DayBlockOutput(
                    id=f"free_day_{day.day_number}",
                    period="morning",
                    activity_type="free_day",
                    summary="Free Day - explore at your own pace",
                    is_buffer=False,
                    specialist_type=None,
                    intensity="light",
                    constraints=[f"{activity_count} activities available to add"],
                )

                # Insert after any buffer blocks
                buffer_count = sum(1 for b in day.blocks if b.is_buffer)
                day.blocks.insert(buffer_count, free_day_block)

                # Update day label if generic
                if day.label.startswith("Day "):
                    day.label = "Free Day"

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

        # Collect preferred tile activities (ordered by position in preferred_activity_ids)
        preferred_activities = []
        for tile_id in preferences.preferred_activity_ids:
            tile = tiles.get(tile_id)
            if tile and isinstance(tile, dict) and tile.get("type") == "activity":
                preferred_activities.append({**tile, "id": tile_id})

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
            # Arrival day: morning+afternoon locked (travel), evening FREE
            if idx == 0:
                day_slots[idx] = {"morning", "afternoon"}
                continue

            # Departure day: morning FREE, afternoon+evening locked (travel)
            if idx == len(days) - 1:
                day_slots[idx] = {"afternoon", "evening"}
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

        # Safety net: Track specialist count per day to prevent activity cramming
        # Max 1 activity per specialist per day (e.g., 1 dive + 1 hike per day is OK)
        from collections import defaultdict

        specialist_count_per_day: dict = defaultdict(lambda: defaultdict(int))

        for tile in preferred_activities:
            # Find day with LEAST occupied slots (most capacity), then by day index
            available_days = [d for d in day_slots if len(day_slots[d]) < MAX_SLOTS_PER_DAY]
            if not available_days:
                _debug_itinerary(f"📅 Dropping '{tile.get('title')}' (all days full)")
                dropped_count += 1
                continue

            best_day = min(available_days, key=lambda d: (len(day_slots[d]), d))

            # Check specialist-per-day cap (max 1 activity per specialist per day)
            source_specialist = tile.get("source_specialist") or tile.get("meta", {}).get(
                "specialist_type"
            )
            if source_specialist and specialist_count_per_day[best_day][source_specialist] >= 1:
                _debug_itinerary(
                    f"📅 Dropping '{tile.get('title')}' "
                    f"(already have {source_specialist} on day {best_day + 1})"
                )
                dropped_count += 1
                continue
            if source_specialist:
                specialist_count_per_day[best_day][source_specialist] += 1

            day = days[best_day]

            # Pick first free period
            period = next(p for p in PERIODS if p not in day_slots[best_day])
            day_slots[best_day].add(period)

            # Remove FreeDay placeholder if this is the first real activity on this day
            has_free_day_placeholder = any(b.activity_type == "free_day" for b in day.blocks)
            if has_free_day_placeholder:
                day.blocks = [b for b in day.blocks if b.activity_type != "free_day"]

            # Create activity block from preferred tile with correct period
            activity_block = DayBlockOutput(
                id=f"pref_{tile['id']}_{best_day}_{period}",
                period=period,
                activity_type=tile.get("title", "Activity").lower().replace(" ", "_"),
                intensity=tile.get("intensity"),
                summary=tile.get("title", "Activity"),
                image_url=tile.get("image_url"),
                duration=tile.get("duration"),
                coordinates=tile.get("coordinates"),
                preference_status="user_preferred",
                booking_category="activity",
                booked_tile=tile,
            )

            # Insert after any buffer blocks, respecting period order
            buffer_count = sum(1 for b in day.blocks if b.is_buffer)
            # Find insertion index based on period order
            period_order = {"morning": 0, "afternoon": 1, "evening": 2}
            insert_idx = buffer_count
            for i, b in enumerate(day.blocks[buffer_count:], start=buffer_count):
                block_period = getattr(b, "period", None) or "morning"
                if period_order.get(block_period, 0) > period_order.get(period, 0):
                    insert_idx = i
                    break
                insert_idx = i + 1
            day.blocks.insert(insert_idx, activity_block)

            # Update day label back from "Free Day" to activity-based label
            if day.label == "Free Day":
                day.label = f"Day {day.day_number}"

            _debug_itinerary(f"📅 Placed '{tile.get('title')}' on day {best_day + 1} ({period})")

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

        if hotel_tile and len(days) > 1:
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
        departure_day = len(days)
        _debug_itinerary(
            f"🏷️ Phase 6.5: Applying constraint tags to {len(days)} days, "
            f"departure_day={departure_day}"
        )

        for day_idx, day_card in enumerate(days):
            for block in day_card.blocks:
                constraints = []

                # Diving activity constraints
                activity_type = (block.activity_type or "").lower()
                specialist = (block.specialist_type or "").lower()
                is_diving = "div" in activity_type or specialist == "diving"
                _debug(
                    f"[ItineraryBuilder] 🏷️ Day {day_idx+1} block: "
                    f"activity_type='{activity_type}', specialist='{specialist}', "
                    f"is_diving={is_diving}, is_buffer={block.is_buffer}"
                )

                if is_diving and not block.is_buffer:
                    # Check if this is the last dive before departure
                    is_last_dive = not any(
                        any(
                            (
                                "div" in (b.activity_type or "").lower()
                                or (b.specialist_type or "").lower() == "diving"
                            )
                            and not b.is_buffer
                            for b in dc.blocks
                        )
                        for dc in days[day_idx + 1 :]
                    )

                    # Last dive within 2 days of departure gets no-fly buffer warning
                    if is_last_dive and day_idx >= departure_day - 2:
                        constraints.append(
                            {
                                "id": "no_fly_buffer",
                                "severity": "warning",
                                "icon": "⚠️",
                                "title": "24h No-Fly Buffer",
                                "description": (
                                    f"Day {departure_day} departure requires "
                                    "finishing diving by 2pm today"
                                ),
                            }
                        )

                    # All dives get surface interval info
                    if not constraints:  # Don't duplicate if already has no-fly warning
                        constraints.append(
                            {
                                "id": "surface_interval",
                                "severity": "info",
                                "icon": "ℹ️",
                                "title": "Dive Safety",
                                "description": "Scheduled with appropriate surface intervals",
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
                                    "Check avalanche bulletin - " "guide + safety gear required"
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

    # =========================================================================
    # Phase 7: Temporal Conflict Detection
    # =========================================================================

    def _detect_temporal_conflicts(self, days: List[DayCardOutput]) -> List[Conflict]:
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
                    Conflict(
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
        self, conflicts: List[Conflict], current_days: int
    ) -> List[Resolution]:
        """Generate resolution options for conflicts."""
        resolutions = []

        # Check if extending trip would help
        has_insufficient_days = any(c.type == "insufficient_days" for c in conflicts)
        if has_insufficient_days:
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
        usable_days = max(1, total_days - 2)
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
