"""
Constraint Engine - Deterministic filtering for specialist constraints.

This engine applies specialist constraints (e.g., 24h no-fly rule for diving)
to booking options using DETERMINISTIC MATH - no LLM needed.

Key Design Principles:
- Instant (0ms latency vs 2-3s for LLM)
- 100% accurate (no hallucination risk)
- Use LLM only for "vibes" (e.g., "Good for couples"), never for safety math

Usage:
    engine = ConstraintEngine()
    safe_flights, blocked_flights = engine.filter_flights_by_diving_constraint(
        flights=flights,
        last_dive_time=datetime(2026, 2, 1, 16, 0),
    )
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel

from app.debug_utils import log

logger = logging.getLogger(__name__)


# =============================================================================
# Constraint Types
# =============================================================================


class ConstraintViolation(BaseModel):
    """A constraint violation with details."""

    constraint_type: str  # "diving_no_fly", "altitude_acclimatization"
    rule: str  # "min_24h_buffer_after_dive"
    message: str  # Human-readable explanation
    severity: Literal["blocking", "warning", "info"] = "blocking"
    parameters: Dict[str, Any] = {}  # e.g., {"hours_required": 24, "hours_actual": 18}


class FilteredResult(BaseModel):
    """Result of constraint filtering."""

    safe_items: List[Dict[str, Any]]
    blocked_items: List[Dict[str, Any]]
    blocked_summary: Optional[Dict[str, Any]] = None


# =============================================================================
# Constraint Engine
# =============================================================================


class ConstraintEngine:
    """
    Deterministic constraint filtering engine.

    Applies specialist constraints to booking options using pure Python math.
    No LLM calls - instant, accurate, and reliable.
    """

    # =========================================================================
    # Diving Constraints
    # =========================================================================

    # PADI/DAN recommended minimum surface interval before flying
    DIVING_NO_FLY_HOURS = 24  # 24 hours for multi-dive days
    DIVING_NO_FLY_SINGLE = 12  # 12 hours for single dive

    def filter_flights_by_diving_constraint(
        self,
        flights: List[Dict[str, Any]],
        last_dive_time: Optional[datetime],
        multi_dive_day: bool = True,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Filter flights based on diving no-fly constraint.

        PADI/DAN Guidelines:
        - Single dive: Wait 12 hours before flying
        - Multiple dives/multi-day diving: Wait 24 hours before flying

        Args:
            flights: List of flight tiles (dict with departure_time)
            last_dive_time: When the last dive ended
            multi_dive_day: Whether multiple dives were done (affects buffer)

        Returns:
            Tuple of (safe_flights, blocked_flights)
        """
        if not last_dive_time:
            # No diving constraint - all flights are safe
            log("CONSTRAINT", "No diving constraints apply - all flights safe", sleep=0.1)
            for flight in flights:
                self._add_logic_hook(flight, "No diving constraints apply", is_safe=True)
            return flights, []

        required_hours = self.DIVING_NO_FLY_HOURS if multi_dive_day else self.DIVING_NO_FLY_SINGLE
        min_safe_departure = last_dive_time + timedelta(hours=required_hours)

        log(
            "CONSTRAINT",
            f"Applying diving no-fly rule ({required_hours}h buffer)",
            data=(
                f"Last dive: {last_dive_time.strftime('%Y-%m-%d %H:%M')} → "
                f"Safe after: {min_safe_departure.strftime('%Y-%m-%d %H:%M')}"
            ),
            sleep=0.15,
        )

        safe_flights = []
        blocked_flights = []

        for flight in flights:
            is_safe, logic_hook = self._check_flight_safety(
                flight=flight,
                last_dive_time=last_dive_time,
                min_safe_departure=min_safe_departure,
                required_hours=required_hours,
            )

            self._add_logic_hook(flight, logic_hook, is_safe=is_safe)

            # Log each flight evaluation
            flight_label = flight.get("label") or flight.get("title") or "Flight"
            if is_safe:
                log("✓ SAFE", f"{flight_label}", data=logic_hook, sleep=0.08)
                safe_flights.append(flight)
            else:
                log("✗ BLOCKED", f"{flight_label}", data=logic_hook, sleep=0.08)
                blocked_flights.append(flight)

        # Log summary
        if blocked_flights:
            log(
                "CONSTRAINT",
                f"Result: {len(safe_flights)} safe, {len(blocked_flights)} blocked",
                data=(
                    f"Blocked flights depart before {min_safe_departure.strftime('%Y-%m-%d %H:%M')}"
                ),
                sleep=0.1,
            )
        else:
            log("CONSTRAINT", f"All {len(safe_flights)} flights cleared safety check", sleep=0.1)

        return safe_flights, blocked_flights

    def _check_flight_safety(
        self,
        flight: Dict[str, Any],
        last_dive_time: datetime,
        min_safe_departure: datetime,  # noqa: ARG002
        required_hours: int,
    ) -> Tuple[bool, str]:
        """
        Check if a single flight is safe after diving.

        DETERMINISTIC MATH - No LLM needed.

        Returns:
            Tuple of (is_safe, logic_hook_message)
        """
        _ = min_safe_departure

        # Get departure time from flight
        departure_time = self._get_departure_time(flight)
        if not departure_time:
            return True, "Unable to verify departure time"

        # Calculate actual surface interval
        delta = departure_time - last_dive_time
        hours = delta.total_seconds() / 3600

        if hours >= required_hours:
            return True, f"Clears {required_hours}h safety buffer ({int(hours)}h after dive)"
        else:
            return False, f"Only {int(hours)}h surface interval (need {required_hours}h)"

    def _get_departure_time(self, flight: Dict[str, Any]) -> Optional[datetime]:
        """Extract departure time from a flight tile."""
        # Try multiple possible field names
        for field_name in ["departure_time", "departureTime", "departure"]:
            value = flight.get(field_name)
            if value:
                if isinstance(value, datetime):
                    return value
                if isinstance(value, str):
                    try:
                        return datetime.fromisoformat(value.replace("Z", "+00:00"))
                    except ValueError:
                        pass

        # Check in meta
        meta = flight.get("meta", {})
        for field_name in ["departure_time", "departureTime"]:
            value = meta.get(field_name)
            if value:
                if isinstance(value, datetime):
                    return value
                if isinstance(value, str):
                    try:
                        return datetime.fromisoformat(value.replace("Z", "+00:00"))
                    except ValueError:
                        pass

        return None

    def _add_logic_hook(
        self,
        item: Dict[str, Any],
        message: str,
        is_safe: bool,
    ) -> None:
        """Add logic hook to item's meta field."""
        if "meta" not in item:
            item["meta"] = {}

        # Add emoji prefix based on safety
        prefix = "" if is_safe else ""
        item["meta"]["logic_hook"] = f"{prefix} {message}"
        item["meta"]["is_safe"] = is_safe

    # =========================================================================
    # Altitude Constraints (for hiking/skiing)
    # =========================================================================

    # Days needed for altitude acclimatization before intense activity
    ALTITUDE_ACCLIMATIZATION_DAYS = 2  # 48 hours

    def filter_activities_by_altitude(
        self,
        activities: List[Dict[str, Any]],
        arrival_time: Optional[datetime],
        destination_altitude: int = 0,  # meters
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Filter activities based on altitude acclimatization.

        High altitude (>2500m) activities should not be done immediately after arrival.

        Args:
            activities: List of activity tiles
            arrival_time: When user arrives at destination
            destination_altitude: Altitude in meters

        Returns:
            Tuple of (safe_activities, blocked_activities)
        """
        # Only apply constraint for high altitude destinations
        if destination_altitude < 2500:
            log("CONSTRAINT", "No altitude restrictions (below 2500m)", sleep=0.1)
            for activity in activities:
                self._add_logic_hook(activity, "No altitude restrictions", is_safe=True)
            return activities, []

        if not arrival_time:
            log("CONSTRAINT", "Altitude check skipped (no arrival time)", sleep=0.1)
            for activity in activities:
                self._add_logic_hook(activity, "Check altitude requirements", is_safe=True)
            return activities, []

        safe_after = arrival_time + timedelta(days=self.ALTITUDE_ACCLIMATIZATION_DAYS)
        log(
            "CONSTRAINT",
            f"Applying altitude acclimatization ({self.ALTITUDE_ACCLIMATIZATION_DAYS} days)",
            data=(
                f"Arrival: {arrival_time.strftime('%Y-%m-%d %H:%M')} → "
                f"Safe after: {safe_after.strftime('%Y-%m-%d %H:%M')}"
            ),
            sleep=0.15,
        )

        safe_activities = []
        blocked_activities = []

        for activity in activities:
            activity_time = self._get_activity_time(activity)
            skill_level = activity.get("meta", {}).get("skill_level", "beginner")

            # Only block intense activities in first 48h
            activity_label = activity.get("label") or activity.get("title") or "Activity"
            if skill_level in ["intermediate", "advanced"] and activity_time:
                if activity_time < safe_after:
                    hours_since_arrival = (activity_time - arrival_time).total_seconds() / 3600
                    self._add_logic_hook(
                        activity,
                        f"Schedule after acclimatization "
                        f"({int(hours_since_arrival)}h since arrival)",
                        is_safe=False,
                    )
                    log(
                        "✗ BLOCKED",
                        f"{activity_label}",
                        data=f"Only {int(hours_since_arrival)}h since arrival",
                        sleep=0.08,
                    )
                    blocked_activities.append(activity)
                    continue

            self._add_logic_hook(activity, "Safe for early days", is_safe=True)
            log("✓ SAFE", f"{activity_label}", data="Safe for early days", sleep=0.08)
            safe_activities.append(activity)

        # Log summary
        if blocked_activities:
            log(
                "CONSTRAINT",
                f"Result: {len(safe_activities)} safe, {len(blocked_activities)} need rescheduling",
                sleep=0.1,
            )
        else:
            log(
                "CONSTRAINT",
                f"All {len(safe_activities)} activities cleared altitude check",
                sleep=0.1,
            )

        return safe_activities, blocked_activities

    def _get_activity_time(self, activity: Dict[str, Any]) -> Optional[datetime]:
        """Extract scheduled time from an activity tile."""
        for field_name in ["scheduled_time", "activity_date", "date"]:
            value = activity.get(field_name) or activity.get("meta", {}).get(field_name)
            if value:
                if isinstance(value, datetime):
                    return value
                if isinstance(value, str):
                    try:
                        return datetime.fromisoformat(value.replace("Z", "+00:00"))
                    except ValueError:
                        pass
        return None

    # =========================================================================
    # Generic Constraint Application
    # =========================================================================

    def apply_constraints(
        self,
        tiles: List[Dict[str, Any]],
        constraints: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> FilteredResult:
        """
        Apply all relevant constraints to tiles.

        Args:
            tiles: List of tile dicts
            constraints: List of constraint dicts from specialist
            context: Trip context with timing info

        Returns:
            FilteredResult with safe and blocked items
        """
        safe_tiles = list(tiles)
        all_blocked = []

        for constraint in constraints:
            rule = constraint.get("rule", "")

            if rule == "min_24h_buffer_after_dive":
                # Get last dive time from context
                last_dive_time = context.get("last_dive_time")
                if last_dive_time and isinstance(last_dive_time, str):
                    last_dive_time = datetime.fromisoformat(last_dive_time)

                # Filter only flights
                flights = [t for t in safe_tiles if t.get("type") == "flight"]
                other_tiles = [t for t in safe_tiles if t.get("type") != "flight"]

                safe_flights, blocked_flights = self.filter_flights_by_diving_constraint(
                    flights=flights,
                    last_dive_time=last_dive_time,
                )

                safe_tiles = other_tiles + safe_flights
                all_blocked.extend(blocked_flights)

            elif rule == "altitude_acclimatization":
                arrival_time = context.get("arrival_time")
                if arrival_time and isinstance(arrival_time, str):
                    arrival_time = datetime.fromisoformat(arrival_time)

                altitude = context.get("destination_altitude", 0)

                # Filter only activities
                activities = [t for t in safe_tiles if t.get("type") == "activity"]
                other_tiles = [t for t in safe_tiles if t.get("type") != "activity"]

                safe_activities, blocked_activities = self.filter_activities_by_altitude(
                    activities=activities,
                    arrival_time=arrival_time,
                    destination_altitude=altitude,
                )

                safe_tiles = other_tiles + safe_activities
                all_blocked.extend(blocked_activities)

        # Build summary
        blocked_summary = None
        if all_blocked:
            blocked_summary = {
                "count": len(all_blocked),
                "reasons": list(
                    set(
                        b.get("meta", {}).get("logic_hook", "Constraint violation")
                        for b in all_blocked
                    )
                ),
            }

        return FilteredResult(
            safe_items=safe_tiles,
            blocked_items=all_blocked,
            blocked_summary=blocked_summary,
        )


# =============================================================================
# Helper Functions
# =============================================================================
