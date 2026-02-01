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
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from app.debug_utils import _debug

logger = logging.getLogger(__name__)

# =============================================================================
# Constraint Severity Enum
# =============================================================================


class ConstraintSeverity(str, Enum):
    """Constraint priority levels for conflict resolution."""

    BLOCKING = "blocking"  # Safety/Legal - always wins
    STRONG = "strong"  # Optimization - negotiates
    SOFT = "soft"  # Preference - defers


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

    def is_hotel_preferred(self, tile_id: str) -> bool:
        """Check if a hotel tile is user-preferred."""
        return tile_id in self.preferred_hotel_ids

    def is_activity_preferred(self, tile_id: str) -> bool:
        """Check if an activity tile is user-preferred."""
        return tile_id in self.preferred_activity_ids


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
            early_conflicts = self._detect_early_conflicts(days, activities, merged_constraints)
            if early_conflicts:
                resolutions = self._generate_resolutions(early_conflicts, len(days))
                return ItineraryResult(
                    success=False,
                    conflicts=early_conflicts,
                    resolutions=resolutions,
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

            # Phase 6: Match tiles to blocks (with preference weighting)
            days = self._match_tiles(days, input_data.tiles, input_data.preferences)

            # Phase 7: Detect post-placement conflicts (overflow)
            conflicts = self._detect_temporal_conflicts(days)
            if conflicts:
                resolutions = self._generate_resolutions(conflicts, len(days))
                # For now, still return success but include warnings
                # In future, could block if severity is BLOCKING

            # Compute overview
            overview = self._compute_overview(days)

            _debug(
                f"[ItineraryBuilder] ✅ Success: generated {len(days)} day cards with "
                f"{sum(len(d.blocks) for d in days)} total blocks"
            )
            return ItineraryResult(
                success=True,
                day_cards=days,
                overview=overview,
                conflicts=conflicts,
                resolutions=[],
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
    # Phase 2b: Early Conflict Detection
    # =========================================================================

    def _detect_early_conflicts(
        self,
        days: List[DayCardOutput],
        activities_by_specialist: Dict[str, List[ActivityBlock]],
        constraints: List[MergedConstraint],
    ) -> List[Conflict]:
        """Detect conflicts before placement that are irreconcilable."""
        conflicts = []
        total_days = len(days)

        # Calculate required days for each specialist
        total_activity_days = 0
        buffer_days = 0

        for _specialist, activities in activities_by_specialist.items():
            total_activity_days += len(activities)

        # Check for diving no-fly buffer
        for c in constraints:
            if c.rule == "min_24h_buffer_after_dive":
                buffer_days = 1
                break

        # Account for arrival/departure days
        usable_days = total_days - 2  # First and last day are partial

        # Check if we have enough days
        required_days = total_activity_days + buffer_days
        if required_days > usable_days:
            specialists = list(activities_by_specialist.keys())
            conflicts.append(
                Conflict(
                    type="insufficient_days",
                    severity=ConstraintSeverity.BLOCKING,
                    specialists=specialists,
                    message=(
                        f"{total_days}-day trip insufficient for {total_activity_days} "
                        f"activities + {buffer_days} buffer day(s)"
                    ),
                )
            )

        return conflicts

    # =========================================================================
    # Phase 3: Anchor Placement
    # =========================================================================

    def _place_anchors(
        self,
        days: List[DayCardOutput],
        tiles: Dict[str, Any],
        origin: Optional[str],
    ) -> List[DayCardOutput]:
        """Place arrival/departure blocks based on flight tiles."""
        if not days:
            return days

        # Find flight tiles
        inbound_flight = None
        outbound_flight = None

        for _tile_id, tile in tiles.items():
            if not isinstance(tile, dict):
                continue
            if tile.get("type") != "flight":
                continue

            # Heuristic: inbound if in title or going TO destination
            title = tile.get("title", "").lower()
            if "inbound" in title or "arrival" in title:
                inbound_flight = tile
            elif "outbound" in title or "departure" in title:
                outbound_flight = tile
            elif origin and origin.lower() in title:
                inbound_flight = tile
            else:
                # Default: first flight is inbound, second is outbound
                if not inbound_flight:
                    inbound_flight = tile
                elif not outbound_flight:
                    outbound_flight = tile

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
                # No-fly buffer = day before departure
                buffer_day_idx = len(days) - 2
                if buffer_day_idx >= 1:  # Must be after arrival day
                    days[buffer_day_idx].label = "No-Fly Day"

                    # Remove any diving activities from this day
                    days[buffer_day_idx].blocks = [
                        b for b in days[buffer_day_idx].blocks if b.specialist_type != "diving"
                    ]

                    # Add safety block
                    buffer_block = DayBlockOutput(
                        id=f"buffer_nofly_{buffer_day_idx}",
                        period="morning",
                        activity_type="rest",
                        summary="Surface interval - no diving (light activities OK)",
                        is_buffer=True,
                        buffer_type="no_fly",
                        buffer_reason="PADI Standard: 24h surface interval before flying",
                        specialist_type="diving",
                        intensity="light",
                    )
                    days[buffer_day_idx].blocks.insert(0, buffer_block)

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
        2. Alternate between specialists for variety
        3. Respect max activities per day (2-3)
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

        # Flatten and copy activities
        specialists = list(activities_by_specialist.keys())
        remaining = {s: list(acts) for s, acts in activities_by_specialist.items()}

        # Round-robin distribution
        day_ptr = 0
        specialist_ptr = 0
        periods = ["morning", "afternoon", "evening"]
        period_ptr = 0

        max_iterations = 100  # Safety limit
        iteration = 0

        while any(remaining.values()) and iteration < max_iterations:
            iteration += 1

            # Get current day and specialist
            day_idx = available_day_indices[day_ptr % len(available_day_indices)]
            current_day = days[day_idx]
            current_specialist = specialists[specialist_ptr % len(specialists)]

            # Check if day has capacity
            non_buffer_blocks = [b for b in current_day.blocks if not b.is_buffer]
            if len(non_buffer_blocks) >= MAX_BLOCKS_PER_DAY - 1:  # Leave room
                day_ptr += 1
                if day_ptr >= len(available_day_indices):
                    day_ptr = 0
                    # If we've cycled through all days, break
                    if not any(remaining.values()):
                        break
                continue

            # Get next activity from current specialist
            activities = remaining.get(current_specialist, [])
            if activities:
                activity = activities.pop(0)

                # Create block
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
                )

                if activity.coordinates:
                    block.coordinates = {
                        "lat": activity.coordinates[1],
                        "lng": activity.coordinates[0],
                    }

                current_day.blocks.append(block)
                period_ptr += 1

            # Rotate specialist for variety
            specialist_ptr += 1

            # Move to next day if we've placed something
            if len(non_buffer_blocks) + 1 >= MAX_BLOCKS_PER_DAY - 1:
                day_ptr += 1

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
            )
            # Insert before departure block
            departure_idx = next(
                (i for i, b in enumerate(days[-1].blocks) if b.buffer_type == "departure"),
                len(days[-1].blocks),
            )
            days[-1].blocks.insert(departure_idx, checkout_block)

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
