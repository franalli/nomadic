# backend/tests/test_constraint_engine.py
"""
Unit tests for constraint_engine.py — deterministic constraint filtering.

Tests cover:
- filter_flights_by_diving_constraint: no-fly buffers (24h multi, 12h single), edge cases
- filter_activities_by_altitude: acclimatization at high altitude, skill level filtering
- apply_constraints: sequential rule application, unknown rules, mixed tile types
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.tools.constraint_engine import ConstraintEngine, FilteredResult

# =============================================================================
# Helpers
# =============================================================================


def _make_flight(
    label: str,
    departure_time: datetime | str | None = None,
    *,
    use_meta: bool = False,
) -> dict:
    """Build a minimal flight tile dict."""
    flight: dict = {"type": "flight", "label": label}
    if departure_time is not None:
        if use_meta:
            flight["meta"] = {"departure_time": departure_time}
        else:
            flight["departure_time"] = departure_time
    return flight


def _make_activity(
    label: str,
    scheduled_time: datetime | str | None = None,
    skill_level: str = "beginner",
) -> dict:
    """Build a minimal activity tile dict."""
    activity: dict = {
        "type": "activity",
        "label": label,
        "meta": {"skill_level": skill_level},
    }
    if scheduled_time is not None:
        activity["scheduled_time"] = scheduled_time
    return activity


# =============================================================================
# filter_flights_by_diving_constraint
# =============================================================================


class TestFilterFlightsByDivingConstraint:
    """Diving no-fly rule: 24h for multi-dive, 12h for single dive."""

    def setup_method(self) -> None:
        self.engine = ConstraintEngine()
        self.dive_time = datetime(2026, 3, 1, 16, 0)  # 4 PM

    def test_no_dive_time_all_flights_safe(self) -> None:
        flights = [_make_flight("EK203", datetime(2026, 3, 2, 10, 0))]
        safe, blocked = self.engine.filter_flights_by_diving_constraint(
            flights=flights, last_dive_time=None
        )
        assert len(safe) == 1
        assert len(blocked) == 0

    def test_flight_25h_after_dive_is_safe(self) -> None:
        """25h > 24h buffer → safe."""
        departure = self.dive_time + timedelta(hours=25)
        flights = [_make_flight("EK203", departure)]
        safe, blocked = self.engine.filter_flights_by_diving_constraint(
            flights=flights, last_dive_time=self.dive_time
        )
        assert len(safe) == 1
        assert len(blocked) == 0

    def test_flight_20h_after_dive_is_blocked(self) -> None:
        """20h < 24h buffer → blocked."""
        departure = self.dive_time + timedelta(hours=20)
        flights = [_make_flight("QF1", departure)]
        safe, blocked = self.engine.filter_flights_by_diving_constraint(
            flights=flights, last_dive_time=self.dive_time
        )
        assert len(safe) == 0
        assert len(blocked) == 1

    def test_single_dive_mode_uses_12h_buffer(self) -> None:
        """Single dive: 12h buffer. 13h after → safe."""
        departure = self.dive_time + timedelta(hours=13)
        flights = [_make_flight("BA456", departure)]
        safe, blocked = self.engine.filter_flights_by_diving_constraint(
            flights=flights, last_dive_time=self.dive_time, multi_dive_day=False
        )
        assert len(safe) == 1
        assert len(blocked) == 0

    def test_single_dive_mode_blocks_under_12h(self) -> None:
        """Single dive: 10h < 12h → blocked."""
        departure = self.dive_time + timedelta(hours=10)
        flights = [_make_flight("SQ321", departure)]
        safe, blocked = self.engine.filter_flights_by_diving_constraint(
            flights=flights, last_dive_time=self.dive_time, multi_dive_day=False
        )
        assert len(safe) == 0
        assert len(blocked) == 1

    def test_flight_exactly_at_24h_boundary_is_safe(self) -> None:
        """Exactly 24h after dive → safe (>= check)."""
        departure = self.dive_time + timedelta(hours=24)
        flights = [_make_flight("EK101", departure)]
        safe, blocked = self.engine.filter_flights_by_diving_constraint(
            flights=flights, last_dive_time=self.dive_time
        )
        assert len(safe) == 1
        assert len(blocked) == 0

    def test_flight_with_no_departure_time_treated_as_safe(self) -> None:
        """No departure time → can't verify → safe."""
        flights = [_make_flight("UNKNOWN")]  # No departure_time
        safe, blocked = self.engine.filter_flights_by_diving_constraint(
            flights=flights, last_dive_time=self.dive_time
        )
        assert len(safe) == 1
        assert len(blocked) == 0

    def test_mix_of_safe_and_blocked(self) -> None:
        safe_departure = self.dive_time + timedelta(hours=30)
        blocked_departure = self.dive_time + timedelta(hours=18)
        flights = [
            _make_flight("SAFE_FLIGHT", safe_departure),
            _make_flight("BLOCKED_FLIGHT", blocked_departure),
        ]
        safe, blocked = self.engine.filter_flights_by_diving_constraint(
            flights=flights, last_dive_time=self.dive_time
        )
        assert len(safe) == 1
        assert len(blocked) == 1
        assert safe[0]["label"] == "SAFE_FLIGHT"
        assert blocked[0]["label"] == "BLOCKED_FLIGHT"

    def test_departure_time_as_iso_string(self) -> None:
        """departure_time as ISO string should be parsed."""
        departure_str = (self.dive_time + timedelta(hours=25)).isoformat()
        flights = [_make_flight("STR_FLIGHT", departure_str)]
        safe, blocked = self.engine.filter_flights_by_diving_constraint(
            flights=flights, last_dive_time=self.dive_time
        )
        assert len(safe) == 1
        assert len(blocked) == 0

    def test_departure_time_in_meta_dict(self) -> None:
        """departure_time in meta sub-dict should be found."""
        departure = self.dive_time + timedelta(hours=25)
        flights = [_make_flight("META_FLIGHT", departure, use_meta=True)]
        safe, blocked = self.engine.filter_flights_by_diving_constraint(
            flights=flights, last_dive_time=self.dive_time
        )
        assert len(safe) == 1
        assert len(blocked) == 0

    def test_logic_hook_added_to_safe_flight(self) -> None:
        departure = self.dive_time + timedelta(hours=30)
        flights = [_make_flight("EK999", departure)]
        safe, _ = self.engine.filter_flights_by_diving_constraint(
            flights=flights, last_dive_time=self.dive_time
        )
        assert safe[0]["meta"]["is_safe"] is True
        assert "logic_hook" in safe[0]["meta"]

    def test_logic_hook_added_to_blocked_flight(self) -> None:
        departure = self.dive_time + timedelta(hours=10)
        flights = [_make_flight("EK000", departure)]
        _, blocked = self.engine.filter_flights_by_diving_constraint(
            flights=flights, last_dive_time=self.dive_time
        )
        assert blocked[0]["meta"]["is_safe"] is False
        assert "logic_hook" in blocked[0]["meta"]

    def test_empty_flights_list(self) -> None:
        safe, blocked = self.engine.filter_flights_by_diving_constraint(
            flights=[], last_dive_time=self.dive_time
        )
        assert safe == []
        assert blocked == []


# =============================================================================
# filter_activities_by_altitude
# =============================================================================


class TestFilterActivitiesByAltitude:
    """Altitude acclimatization: 48h buffer before intense activities above 2500m."""

    def setup_method(self) -> None:
        self.engine = ConstraintEngine()
        self.arrival = datetime(2026, 3, 1, 10, 0)

    def test_low_altitude_all_safe(self) -> None:
        """Below 2500m → no restrictions."""
        activities = [_make_activity("City Walk", datetime(2026, 3, 1, 14, 0), "intermediate")]
        safe, blocked = self.engine.filter_activities_by_altitude(
            activities=activities,
            arrival_time=self.arrival,
            destination_altitude=1000,
        )
        assert len(safe) == 1
        assert len(blocked) == 0

    def test_no_arrival_time_all_safe(self) -> None:
        """No arrival_time → can't verify → all safe."""
        activities = [_make_activity("Summit Trek", datetime(2026, 3, 1, 14, 0), "advanced")]
        safe, blocked = self.engine.filter_activities_by_altitude(
            activities=activities,
            arrival_time=None,
            destination_altitude=3000,
        )
        assert len(safe) == 1
        assert len(blocked) == 0

    def test_intermediate_within_48h_at_3000m_blocked(self) -> None:
        """Intermediate activity 6h after arrival at 3000m → blocked."""
        activity_time = self.arrival + timedelta(hours=6)
        activities = [_make_activity("Ridge Hike", activity_time, "intermediate")]
        safe, blocked = self.engine.filter_activities_by_altitude(
            activities=activities,
            arrival_time=self.arrival,
            destination_altitude=3000,
        )
        assert len(safe) == 0
        assert len(blocked) == 1

    def test_advanced_within_48h_at_3000m_blocked(self) -> None:
        """Advanced activity within 48h → blocked."""
        activity_time = self.arrival + timedelta(hours=24)
        activities = [_make_activity("Summit Push", activity_time, "advanced")]
        safe, blocked = self.engine.filter_activities_by_altitude(
            activities=activities,
            arrival_time=self.arrival,
            destination_altitude=3000,
        )
        assert len(safe) == 0
        assert len(blocked) == 1

    def test_beginner_within_48h_is_safe(self) -> None:
        """Beginner activity within 48h → safe (only intermediate/advanced blocked)."""
        activity_time = self.arrival + timedelta(hours=6)
        activities = [_make_activity("Easy Walk", activity_time, "beginner")]
        safe, blocked = self.engine.filter_activities_by_altitude(
            activities=activities,
            arrival_time=self.arrival,
            destination_altitude=3000,
        )
        assert len(safe) == 1
        assert len(blocked) == 0

    def test_intermediate_after_48h_is_safe(self) -> None:
        """Intermediate activity 50h after arrival → safe."""
        activity_time = self.arrival + timedelta(hours=50)
        activities = [_make_activity("Mountain Trek", activity_time, "intermediate")]
        safe, blocked = self.engine.filter_activities_by_altitude(
            activities=activities,
            arrival_time=self.arrival,
            destination_altitude=3000,
        )
        assert len(safe) == 1
        assert len(blocked) == 0

    def test_no_activity_time_is_safe(self) -> None:
        """Activity with no scheduled_time → safe (can't verify)."""
        activities = [_make_activity("Flexible Trek", None, "advanced")]
        safe, blocked = self.engine.filter_activities_by_altitude(
            activities=activities,
            arrival_time=self.arrival,
            destination_altitude=3000,
        )
        assert len(safe) == 1
        assert len(blocked) == 0

    def test_exactly_at_2500m_threshold_applies_constraint(self) -> None:
        """Altitude exactly at 2500m → constraint does NOT apply (< 2500 check)."""
        activity_time = self.arrival + timedelta(hours=6)
        activities = [_make_activity("Border Hike", activity_time, "intermediate")]
        safe, blocked = self.engine.filter_activities_by_altitude(
            activities=activities,
            arrival_time=self.arrival,
            destination_altitude=2500,
        )
        # 2500 is NOT < 2500 so constraint applies
        assert len(blocked) == 1

    def test_mix_of_safe_and_blocked(self) -> None:
        early_time = self.arrival + timedelta(hours=6)
        late_time = self.arrival + timedelta(hours=50)
        activities = [
            _make_activity("Early Trek", early_time, "advanced"),
            _make_activity("Late Trek", late_time, "advanced"),
            _make_activity("Easy Stroll", early_time, "beginner"),
        ]
        safe, blocked = self.engine.filter_activities_by_altitude(
            activities=activities,
            arrival_time=self.arrival,
            destination_altitude=3500,
        )
        assert len(safe) == 2  # Late Trek + Easy Stroll
        assert len(blocked) == 1  # Early Trek
        assert blocked[0]["label"] == "Early Trek"

    def test_logic_hook_on_blocked_activity(self) -> None:
        activity_time = self.arrival + timedelta(hours=6)
        activities = [_make_activity("Hard Hike", activity_time, "advanced")]
        _, blocked = self.engine.filter_activities_by_altitude(
            activities=activities,
            arrival_time=self.arrival,
            destination_altitude=3000,
        )
        assert blocked[0]["meta"]["is_safe"] is False

    def test_empty_activities_list(self) -> None:
        safe, blocked = self.engine.filter_activities_by_altitude(
            activities=[], arrival_time=self.arrival, destination_altitude=4000
        )
        assert safe == []
        assert blocked == []


# =============================================================================
# apply_constraints
# =============================================================================


class TestApplyConstraints:
    """Generic constraint application across mixed tile types."""

    def setup_method(self) -> None:
        self.engine = ConstraintEngine()

    def test_diving_constraint_filters_only_flights(self) -> None:
        dive_time = datetime(2026, 3, 1, 16, 0)
        blocked_departure = dive_time + timedelta(hours=10)
        tiles = [
            {"type": "flight", "label": "EK203", "departure_time": blocked_departure},
            {"type": "hotel", "label": "Beach Hotel"},
            {"type": "activity", "label": "Snorkeling"},
        ]
        constraints = [{"rule": "min_24h_buffer_after_dive"}]
        context = {"last_dive_time": dive_time}

        result = self.engine.apply_constraints(tiles, constraints, context)

        assert isinstance(result, FilteredResult)
        # Flight should be blocked, hotel and activity untouched
        assert len(result.blocked_items) == 1
        assert result.blocked_items[0]["label"] == "EK203"
        safe_labels = {t["label"] for t in result.safe_items}
        assert "Beach Hotel" in safe_labels
        assert "Snorkeling" in safe_labels

    def test_altitude_constraint_filters_only_activities(self) -> None:
        arrival = datetime(2026, 3, 1, 10, 0)
        early_time = arrival + timedelta(hours=6)
        tiles = [
            {"type": "flight", "label": "Outbound"},
            {
                "type": "activity",
                "label": "Summit Trek",
                "scheduled_time": early_time,
                "meta": {"skill_level": "advanced"},
            },
            {"type": "hotel", "label": "Mountain Lodge"},
        ]
        constraints = [{"rule": "altitude_acclimatization"}]
        context = {"arrival_time": arrival, "destination_altitude": 3500}

        result = self.engine.apply_constraints(tiles, constraints, context)

        assert len(result.blocked_items) == 1
        assert result.blocked_items[0]["label"] == "Summit Trek"
        safe_labels = {t["label"] for t in result.safe_items}
        assert "Outbound" in safe_labels
        assert "Mountain Lodge" in safe_labels

    def test_unknown_constraint_rule_no_filtering(self) -> None:
        tiles = [
            {"type": "flight", "label": "EK203"},
            {"type": "activity", "label": "Yoga"},
        ]
        constraints = [{"rule": "unknown_future_rule"}]
        context = {}

        result = self.engine.apply_constraints(tiles, constraints, context)

        assert len(result.safe_items) == 2
        assert len(result.blocked_items) == 0
        assert result.blocked_summary is None

    def test_multiple_constraints_applied_sequentially(self) -> None:
        dive_time = datetime(2026, 3, 1, 16, 0)
        arrival = datetime(2026, 3, 1, 10, 0)
        blocked_departure = dive_time + timedelta(hours=10)
        early_activity = arrival + timedelta(hours=6)

        tiles = [
            {"type": "flight", "label": "BlockedFlight", "departure_time": blocked_departure},
            {
                "type": "activity",
                "label": "Hard Hike",
                "scheduled_time": early_activity,
                "meta": {"skill_level": "advanced"},
            },
            {"type": "hotel", "label": "Lodge"},
        ]
        constraints = [
            {"rule": "min_24h_buffer_after_dive"},
            {"rule": "altitude_acclimatization"},
        ]
        context = {
            "last_dive_time": dive_time,
            "arrival_time": arrival,
            "destination_altitude": 3500,
        }

        result = self.engine.apply_constraints(tiles, constraints, context)

        assert len(result.blocked_items) == 2
        blocked_labels = {t["label"] for t in result.blocked_items}
        assert "BlockedFlight" in blocked_labels
        assert "Hard Hike" in blocked_labels
        assert len(result.safe_items) == 1
        assert result.safe_items[0]["label"] == "Lodge"

    def test_blocked_summary_present_when_items_blocked(self) -> None:
        dive_time = datetime(2026, 3, 1, 16, 0)
        blocked_departure = dive_time + timedelta(hours=10)
        tiles = [
            {"type": "flight", "label": "EK203", "departure_time": blocked_departure},
        ]
        constraints = [{"rule": "min_24h_buffer_after_dive"}]
        context = {"last_dive_time": dive_time}

        result = self.engine.apply_constraints(tiles, constraints, context)

        assert result.blocked_summary is not None
        assert result.blocked_summary["count"] == 1
        assert isinstance(result.blocked_summary["reasons"], list)

    def test_no_blocked_summary_when_all_safe(self) -> None:
        tiles = [{"type": "hotel", "label": "Hotel"}]
        constraints = [{"rule": "min_24h_buffer_after_dive"}]
        context = {"last_dive_time": datetime(2026, 3, 1, 16, 0)}

        result = self.engine.apply_constraints(tiles, constraints, context)

        # Hotel is not a flight, so not filtered by diving constraint
        assert len(result.safe_items) == 1
        assert result.blocked_summary is None

    def test_empty_constraints_list(self) -> None:
        tiles = [{"type": "flight", "label": "EK203"}]
        result = self.engine.apply_constraints(tiles, [], {})
        assert len(result.safe_items) == 1
        assert len(result.blocked_items) == 0

    def test_empty_tiles_list(self) -> None:
        constraints = [{"rule": "min_24h_buffer_after_dive"}]
        context = {"last_dive_time": datetime(2026, 3, 1, 16, 0)}
        result = self.engine.apply_constraints([], constraints, context)
        assert result.safe_items == []
        assert result.blocked_items == []

    def test_last_dive_time_as_iso_string_in_context(self) -> None:
        """apply_constraints parses string last_dive_time from context."""
        dive_time = datetime(2026, 3, 1, 16, 0)
        blocked_departure = dive_time + timedelta(hours=10)
        tiles = [
            {"type": "flight", "label": "EK203", "departure_time": blocked_departure},
        ]
        constraints = [{"rule": "min_24h_buffer_after_dive"}]
        context = {"last_dive_time": dive_time.isoformat()}

        result = self.engine.apply_constraints(tiles, constraints, context)
        assert len(result.blocked_items) == 1


# =============================================================================
# ConstraintEngine constants
# =============================================================================


class TestConstraintEngineConstants:
    """Verify safety-critical constants are correct."""

    def test_diving_no_fly_hours(self) -> None:
        assert ConstraintEngine.DIVING_NO_FLY_HOURS == 24

    def test_diving_no_fly_single(self) -> None:
        assert ConstraintEngine.DIVING_NO_FLY_SINGLE == 12

    def test_altitude_acclimatization_days(self) -> None:
        assert ConstraintEngine.ALTITUDE_ACCLIMATIZATION_DAYS == 2
