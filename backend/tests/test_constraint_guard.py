"""
Unit tests for ConstraintGuard validation functions.

Tests the individual pure functions in constraint_guard.py:
- ConstraintViolation.to_dict()
- _get_budget_allocation()
- check_budget_constraint()
- check_temporal_constraints()
- _check_departure_buffer_conflict()
- check_specialist_constraints()
- _check_cross_domain_from_sections()
- check_route_constraint()

Does NOT test the full constraint_guard() node function (requires full GraphState
wiring with typed metadata). Focuses on deterministic validation logic only.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.planner.nodes.constraint_guard import (
    BUDGET_ALLOCATIONS,
    ConstraintViolation,
    _check_cross_domain_from_sections,
    _check_departure_buffer_conflict,
    _get_budget_allocation,
    check_budget_constraint,
    check_route_constraint,
    check_specialist_constraints,
    check_temporal_constraints,
)
from app.planner.state.graph_state import ItineraryBlock, TripPlan

# =============================================================================
# Helpers
# =============================================================================


def _make_plan(**kwargs) -> TripPlan:
    """Create a TripPlan with sensible defaults overridden by kwargs."""
    return TripPlan(**kwargs)


def _make_activity_block(day: int, specialist: str) -> ItineraryBlock:
    """Create a minimal activity ItineraryBlock."""
    return ItineraryBlock(
        day=day,
        title=f"{specialist} activity day {day}",
        description="Test activity",
        type="activity",
        source_specialist=specialist,
    )


def _make_buffer_block(day: int, specialist: str) -> ItineraryBlock:
    """Create a buffer ItineraryBlock (should NOT trigger constraint checks)."""
    return ItineraryBlock(
        day=day,
        title="No-fly buffer",
        description="Rest day before departure",
        type="buffer",
        source_specialist=specialist,
        is_buffer=True,
        buffer_type="no_fly",
    )


# =============================================================================
# 1. ConstraintViolation.to_dict()
# =============================================================================


class TestConstraintViolationToDict:
    """Tests for ConstraintViolation serialization."""

    def test_to_dict_all_fields_populated(self):
        """to_dict includes optional fields when they are set."""
        v = ConstraintViolation(
            code="TEST_CODE",
            message="Something went wrong",
            severity="blocking",
            category="budget",
            suggested_action="Fix the budget",
            suggested_specialist="hiking",
            conflicting_specialists=["diving", "skiing"],
        )
        d = v.to_dict()

        assert d["code"] == "TEST_CODE"
        assert d["message"] == "Something went wrong"
        assert d["severity"] == "blocking"
        assert d["category"] == "budget"
        assert d["suggested_action"] == "Fix the budget"
        assert d["suggested_specialist"] == "hiking"
        assert d["conflicting_specialists"] == ["diving", "skiing"]

    def test_to_dict_optional_fields_none(self):
        """to_dict omits optional fields when they are None/empty."""
        v = ConstraintViolation(
            code="MINIMAL",
            message="Bare violation",
        )
        d = v.to_dict()

        assert d["code"] == "MINIMAL"
        assert d["message"] == "Bare violation"
        assert d["severity"] == "warning"  # default
        assert d["category"] == "general"  # default
        assert "suggested_action" not in d
        assert "suggested_specialist" not in d
        assert "conflicting_specialists" not in d

    def test_to_dict_empty_conflicting_specialists_omitted(self):
        """Empty conflicting_specialists list is treated as falsy and omitted."""
        v = ConstraintViolation(
            code="X",
            message="Y",
            conflicting_specialists=[],
        )
        d = v.to_dict()
        assert "conflicting_specialists" not in d


# =============================================================================
# 2. _get_budget_allocation
# =============================================================================


class TestGetBudgetAllocation:
    """Tests for budget allocation percentage lookup."""

    def test_flights_allocation(self):
        allocation = _get_budget_allocation(10000.0, "flights")
        assert allocation == 10000.0 * BUDGET_ALLOCATIONS["flights"]

    def test_hotels_allocation(self):
        allocation = _get_budget_allocation(10000.0, "hotels")
        assert allocation == 10000.0 * BUDGET_ALLOCATIONS["hotels"]

    def test_activities_allocation(self):
        allocation = _get_budget_allocation(10000.0, "activities")
        assert allocation == 10000.0 * BUDGET_ALLOCATIONS["activities"]

    def test_unknown_category_falls_back_to_025(self):
        """Unknown categories get 25% allocation."""
        allocation = _get_budget_allocation(10000.0, "car_rentals")
        assert allocation == 10000.0 * 0.25

    def test_zero_budget(self):
        allocation = _get_budget_allocation(0.0, "flights")
        assert allocation == 0.0


# =============================================================================
# 3. check_budget_constraint
# =============================================================================


class TestCheckBudgetConstraint:
    """Tests for budget violation detection."""

    def test_no_budget_set_returns_empty(self):
        """No budget means no violations possible."""
        plan = _make_plan(budget=None)
        tiles = {"flights": [{"price_estimate": 5000}]}

        violations = check_budget_constraint(plan, tiles)
        assert violations == []

    def test_category_cost_exceeds_allocation_warning(self):
        """Single category over allocation produces a warning."""
        plan = _make_plan(budget=1000.0)
        # Flights allocation = 1000 * 0.30 = 300
        tiles = {"flights": [{"price_estimate": 400}]}

        violations = check_budget_constraint(plan, tiles)

        category_violations = [v for v in violations if "FLIGHTS" in v.code]
        assert len(category_violations) == 1
        assert category_violations[0].severity == "warning"
        assert category_violations[0].category == "budget"

    def test_total_cost_exceeds_budget_blocking(self):
        """Total cost exceeding budget produces a blocking violation."""
        plan = _make_plan(budget=1000.0)
        tiles = {
            "flights": [{"price_estimate": 500}],
            "hotels": [{"price_estimate": 600}],
        }
        # Total = 1100 > 1000

        violations = check_budget_constraint(plan, tiles)

        total_violations = [v for v in violations if v.code == "BUDGET_TOTAL_EXCEEDED"]
        assert len(total_violations) == 1
        assert total_violations[0].severity == "blocking"

    def test_within_budget_no_violations(self):
        """All costs within allocation produces no violations."""
        plan = _make_plan(budget=10000.0)
        tiles = {
            "flights": [{"price_estimate": 100}],
            "hotels": [{"price_estimate": 200}],
            "activities": [{"price_estimate": 50}],
        }

        violations = check_budget_constraint(plan, tiles)
        assert violations == []

    def test_empty_tiles_no_violations(self):
        """No tiles means zero cost, no violations."""
        plan = _make_plan(budget=1000.0)
        violations = check_budget_constraint(plan, {})
        assert violations == []

    def test_uses_live_price_fallback(self):
        """Tiles with live_price instead of price_estimate are counted."""
        plan = _make_plan(budget=100.0)
        # Flights allocation = 100 * 0.30 = 30
        tiles = {"flights": [{"live_price": 50}]}

        violations = check_budget_constraint(plan, tiles)
        category_violations = [v for v in violations if "FLIGHTS" in v.code]
        assert len(category_violations) == 1  # 50 > 30 allocation

    def test_tile_without_price_treated_as_zero(self):
        """Tiles missing price fields are treated as zero cost."""
        plan = _make_plan(budget=1000.0)
        tiles = {"flights": [{"carrier": "TestAir"}]}

        violations = check_budget_constraint(plan, tiles)
        assert violations == []


# =============================================================================
# 4. check_temporal_constraints
# =============================================================================


class TestCheckTemporalConstraints:
    """Tests for date/duration validation."""

    def test_end_before_start_date_order_invalid(self):
        """End date before start date produces DATE_ORDER_INVALID."""
        plan = _make_plan(start_date="2026-06-10", end_date="2026-06-05")

        violations = check_temporal_constraints(plan, {})

        codes = [v.code for v in violations]
        assert "DATE_ORDER_INVALID" in codes
        invalid = next(v for v in violations if v.code == "DATE_ORDER_INVALID")
        assert invalid.severity == "blocking"
        assert invalid.category == "temporal"

    def test_trip_over_30_days_info(self):
        """Trip > 30 days produces TRIP_TOO_LONG info violation."""
        plan = _make_plan(start_date="2026-06-01", end_date="2026-08-01")

        violations = check_temporal_constraints(plan, {})

        codes = [v.code for v in violations]
        assert "TRIP_TOO_LONG" in codes
        long_v = next(v for v in violations if v.code == "TRIP_TOO_LONG")
        assert long_v.severity == "info"

    def test_trip_less_than_1_day_warning(self):
        """Same start and end date (0 duration) produces TRIP_TOO_SHORT."""
        plan = _make_plan(start_date="2026-06-01", end_date="2026-06-01")

        violations = check_temporal_constraints(plan, {})

        codes = [v.code for v in violations]
        assert "TRIP_TOO_SHORT" in codes
        short_v = next(v for v in violations if v.code == "TRIP_TOO_SHORT")
        assert short_v.severity == "warning"

    def test_valid_dates_no_violations(self):
        """A normal future trip produces no violations."""
        plan = _make_plan(start_date="2026-06-01", end_date="2026-06-10")

        violations = check_temporal_constraints(plan, {})
        assert violations == []

    def test_no_dates_set_returns_empty(self):
        """No dates means no temporal check is possible."""
        plan = _make_plan()

        violations = check_temporal_constraints(plan, {})
        assert violations == []

    def test_only_start_date_no_violations(self):
        """Only start_date set (no end_date) skips temporal checks."""
        plan = _make_plan(start_date="2026-06-01")

        violations = check_temporal_constraints(plan, {})
        assert violations == []

    def test_exactly_30_days_no_too_long(self):
        """Trip exactly 30 days should NOT trigger TRIP_TOO_LONG."""
        plan = _make_plan(start_date="2026-06-01", end_date="2026-07-01")

        violations = check_temporal_constraints(plan, {})

        codes = [v.code for v in violations]
        assert "TRIP_TOO_LONG" not in codes

    def test_exactly_1_day_no_too_short(self):
        """Trip of exactly 1 day should NOT trigger TRIP_TOO_SHORT."""
        plan = _make_plan(start_date="2026-06-01", end_date="2026-06-02")

        violations = check_temporal_constraints(plan, {})

        codes = [v.code for v in violations]
        assert "TRIP_TOO_SHORT" not in codes

    def test_invalid_date_format_passes(self):
        """Invalid date format is silently ignored (no crash)."""
        plan = _make_plan(start_date="not-a-date", end_date="also-not")

        violations = check_temporal_constraints(plan, {})
        assert violations == []


# =============================================================================
# 5. _check_departure_buffer_conflict
# =============================================================================


class TestCheckDepartureBufferConflict:
    """Tests for specialist activity proximity to departure."""

    def test_activity_within_buffer_returns_true(self):
        """Activity on last day within buffer triggers conflict."""
        # 5-day trip (days 1-5), buffer_days=1
        # trip_days = 5, so conflict if last_day >= 5 - 1 = 4
        plan = _make_plan(start_date="2026-06-01", end_date="2026-06-05")
        tiles = {"flights": [{"carrier": "TestAir"}]}
        blocks = [_make_activity_block(day=4, specialist="diving")]

        result = _check_departure_buffer_conflict(plan, tiles, "diving", blocks, buffer_days=1)
        assert result is True

    def test_activity_outside_buffer_returns_false(self):
        """Activity well before departure does not conflict."""
        # 10-day trip, buffer_days=1
        # trip_days = 10, conflict if last_day >= 9
        plan = _make_plan(start_date="2026-06-01", end_date="2026-06-10")
        tiles = {"flights": [{"carrier": "TestAir"}]}
        blocks = [_make_activity_block(day=3, specialist="diving")]

        result = _check_departure_buffer_conflict(plan, tiles, "diving", blocks, buffer_days=1)
        assert result is False

    def test_no_flights_returns_false(self):
        """Without flights, no departure conflict is possible."""
        plan = _make_plan(start_date="2026-06-01", end_date="2026-06-05")
        tiles = {}  # No flights
        blocks = [_make_activity_block(day=5, specialist="diving")]

        result = _check_departure_buffer_conflict(plan, tiles, "diving", blocks, buffer_days=1)
        assert result is False

    def test_no_dates_returns_false(self):
        """Missing dates means no conflict check is possible."""
        plan = _make_plan()
        tiles = {"flights": [{"carrier": "TestAir"}]}
        blocks = [_make_activity_block(day=1, specialist="diving")]

        result = _check_departure_buffer_conflict(plan, tiles, "diving", blocks, buffer_days=1)
        assert result is False

    def test_no_blocks_returns_false(self):
        """Empty blocks list means no activity conflict."""
        plan = _make_plan(start_date="2026-06-01", end_date="2026-06-05")
        tiles = {"flights": [{"carrier": "TestAir"}]}

        result = _check_departure_buffer_conflict(plan, tiles, "diving", [], buffer_days=1)
        assert result is False

    def test_activity_exactly_on_boundary_returns_true(self):
        """Activity exactly at boundary (trip_days - buffer_days) triggers conflict."""
        # 5-day trip, buffer_days=1, conflict threshold = day >= 4
        plan = _make_plan(start_date="2026-06-01", end_date="2026-06-05")
        tiles = {"flights": [{"carrier": "TestAir"}]}
        blocks = [
            _make_activity_block(day=2, specialist="diving"),
            _make_activity_block(day=4, specialist="diving"),  # exactly on boundary
        ]

        result = _check_departure_buffer_conflict(plan, tiles, "diving", blocks, buffer_days=1)
        assert result is True

    def test_activity_one_before_boundary_returns_false(self):
        """Activity one day before boundary is safe."""
        # 5-day trip, buffer_days=1, conflict threshold = day >= 4
        plan = _make_plan(start_date="2026-06-01", end_date="2026-06-05")
        tiles = {"flights": [{"carrier": "TestAir"}]}
        blocks = [_make_activity_block(day=3, specialist="diving")]

        result = _check_departure_buffer_conflict(plan, tiles, "diving", blocks, buffer_days=1)
        assert result is False

    def test_buffer_blocks_not_counted_as_activities(self):
        """Buffer blocks (is_buffer=True) should not have day=0 and thus are ignored.

        Note: _check_departure_buffer_conflict filters on b.day being truthy,
        so blocks with day > 0 are considered. The filtering by type happens in
        check_specialist_constraints which only passes activity-typed blocks.
        """
        plan = _make_plan(start_date="2026-06-01", end_date="2026-06-05")
        tiles = {"flights": [{"carrier": "TestAir"}]}
        # Only safe activity on day 2, buffer on day 4 (would conflict if counted)
        blocks = [
            _make_activity_block(day=2, specialist="diving"),
        ]

        result = _check_departure_buffer_conflict(plan, tiles, "diving", blocks, buffer_days=1)
        assert result is False

    def test_invalid_dates_returns_false(self):
        """Invalid date strings return False (no crash)."""
        plan = _make_plan(start_date="bad", end_date="worse")
        tiles = {"flights": [{"carrier": "TestAir"}]}
        blocks = [_make_activity_block(day=1, specialist="diving")]

        result = _check_departure_buffer_conflict(plan, tiles, "diving", blocks, buffer_days=1)
        assert result is False


# =============================================================================
# 6. check_specialist_constraints (requires specialist_registry mocking)
# =============================================================================


class TestCheckSpecialistConstraints:
    """Tests for registry-driven specialist constraint checks."""

    def test_diving_near_departure_with_flights(self):
        """Diving activity near departure with flights triggers surface interval violation."""
        # 5-day trip: trip_days = 5. Diving has 24h buffer → buffer_days = 1
        # Conflict if last activity day >= 5 - 1 = 4
        plan = _make_plan(start_date="2026-06-01", end_date="2026-06-05")
        plan.itinerary_blocks = [
            _make_activity_block(day=4, specialist="diving"),
        ]
        tiles = {"flights": [{"carrier": "TestAir"}]}

        violations = check_specialist_constraints(plan, tiles)

        surface_violations = [v for v in violations if "SURFACE_INTERVAL" in v.code]
        assert len(surface_violations) >= 1
        assert surface_violations[0].severity == "blocking"
        assert surface_violations[0].category == "specialist"

    def test_no_specialist_config_skips(self):
        """Blocks from an unknown specialist are silently skipped."""
        plan = _make_plan(start_date="2026-06-01", end_date="2026-06-05")
        plan.itinerary_blocks = [
            _make_activity_block(day=4, specialist="basket_weaving"),
        ]
        tiles = {"flights": [{"carrier": "TestAir"}]}

        violations = check_specialist_constraints(plan, tiles)
        assert violations == []

    def test_diving_safe_schedule_no_violations(self):
        """Diving activity safely before departure produces no violations."""
        # 10-day trip, diving on day 2 — well within buffer
        plan = _make_plan(start_date="2026-06-01", end_date="2026-06-10")
        plan.itinerary_blocks = [
            _make_activity_block(day=2, specialist="diving"),
        ]
        tiles = {"flights": [{"carrier": "TestAir"}]}

        violations = check_specialist_constraints(plan, tiles)
        assert violations == []

    def test_buffer_blocks_excluded_from_checks(self):
        """Buffer-type blocks are filtered out before constraint checks.

        check_specialist_constraints only considers type=='activity' blocks.
        """
        plan = _make_plan(start_date="2026-06-01", end_date="2026-06-05")
        plan.itinerary_blocks = [
            _make_activity_block(day=2, specialist="diving"),
            _make_buffer_block(day=4, specialist="diving"),  # buffer, not activity
        ]
        tiles = {"flights": [{"carrier": "TestAir"}]}

        violations = check_specialist_constraints(plan, tiles)
        # Day 2 activity is safe. Day 4 buffer is excluded. No violations.
        assert violations == []

    def test_no_itinerary_blocks_returns_empty(self):
        """No itinerary blocks means nothing to check."""
        plan = _make_plan(start_date="2026-06-01", end_date="2026-06-05")
        tiles = {"flights": [{"carrier": "TestAir"}]}

        violations = check_specialist_constraints(plan, tiles)
        assert violations == []

    def test_specialist_without_nofly_no_departure_violation(self):
        """Hiking (no nofly buffer) near departure does not trigger departure conflict."""
        plan = _make_plan(start_date="2026-06-01", end_date="2026-06-05")
        plan.itinerary_blocks = [
            _make_activity_block(day=4, specialist="hiking"),
        ]
        tiles = {"flights": [{"carrier": "TestAir"}]}

        violations = check_specialist_constraints(plan, tiles)
        departure_violations = [v for v in violations if "SURFACE_INTERVAL" in v.code]
        assert len(departure_violations) == 0


# =============================================================================
# 7. _check_cross_domain_from_sections
# =============================================================================


class TestCheckCrossDomainFromSections:
    """Tests for stateless cross-domain check using strategy sections."""

    def test_two_conflicting_specialists_short_trip(self):
        """Diving + hiking on a short trip triggers cross-domain violation."""
        sections = [
            {"specialist_type": "diving"},
            {"specialist_type": "hiking"},
        ]
        # 4-day trip: total=4, usable=2, available_after_buffer = 2 - 1 = 1
        # 1 < 2 → violation emitted
        violations = _check_cross_domain_from_sections(
            sections,
            start_date="2026-06-01",
            end_date="2026-06-04",
        )

        assert len(violations) >= 1
        codes = [v.code for v in violations]
        assert "ALTITUDE_AFTER_DIVE" in codes

    def test_two_conflicting_specialists_long_trip(self):
        """Diving + hiking on a long trip does NOT trigger violation (builder handles it)."""
        sections = [
            {"specialist_type": "diving"},
            {"specialist_type": "hiking"},
        ]
        # 10-day trip: total=10, usable=8, available_after_buffer = 8 - 1 = 7 >= 2 → no violation
        violations = _check_cross_domain_from_sections(
            sections,
            start_date="2026-06-01",
            end_date="2026-06-10",
        )

        codes = [v.code for v in violations]
        assert "ALTITUDE_AFTER_DIVE" not in codes

    def test_single_specialist_no_violations(self):
        """Single specialist cannot have cross-domain conflicts."""
        sections = [
            {"specialist_type": "diving"},
        ]
        violations = _check_cross_domain_from_sections(
            sections,
            start_date="2026-06-01",
            end_date="2026-06-04",
        )
        assert violations == []

    def test_no_dates_emits_violation(self):
        """Missing dates triggers violation (cannot verify capacity)."""
        sections = [
            {"specialist_type": "diving"},
            {"specialist_type": "hiking"},
        ]
        violations = _check_cross_domain_from_sections(
            sections,
            start_date=None,
            end_date=None,
        )

        # Should still emit the violation since capacity can't be verified
        assert len(violations) >= 1
        codes = [v.code for v in violations]
        assert "ALTITUDE_AFTER_DIVE" in codes

    def test_non_conflicting_specialists_no_violations(self):
        """Specialists without cross-domain blocks do not conflict."""
        sections = [
            {"specialist_type": "surfing"},
            {"specialist_type": "cycling"},
        ]
        violations = _check_cross_domain_from_sections(
            sections,
            start_date="2026-06-01",
            end_date="2026-06-04",
        )
        assert violations == []

    def test_local_expert_excluded(self):
        """local_expert sections are filtered out of cross-domain checks."""
        sections = [
            {"specialist_type": "diving"},
            {"specialist_type": "local_expert"},
        ]
        violations = _check_cross_domain_from_sections(
            sections,
            start_date="2026-06-01",
            end_date="2026-06-04",
        )
        # local_expert excluded → only 1 active specialist → no cross-domain
        assert violations == []

    def test_general_excluded(self):
        """'general' sections are filtered out of cross-domain checks."""
        sections = [
            {"specialist_type": "diving"},
            {"specialist_type": "general"},
        ]
        violations = _check_cross_domain_from_sections(
            sections,
            start_date="2026-06-01",
            end_date="2026-06-04",
        )
        assert violations == []

    def test_diving_and_skiing_conflict(self):
        """Diving + skiing also triggers ALTITUDE_AFTER_DIVE (skiing is a target)."""
        sections = [
            {"specialist_type": "diving"},
            {"specialist_type": "skiing"},
        ]
        violations = _check_cross_domain_from_sections(
            sections,
            start_date="2026-06-01",
            end_date="2026-06-04",
        )

        codes = [v.code for v in violations]
        assert "ALTITUDE_AFTER_DIVE" in codes

    def test_diving_and_climbing_conflict(self):
        """Diving + climbing also triggers ALTITUDE_AFTER_DIVE (climbing is a target)."""
        sections = [
            {"specialist_type": "diving"},
            {"specialist_type": "climbing"},
        ]
        violations = _check_cross_domain_from_sections(
            sections,
            start_date="2026-06-01",
            end_date="2026-06-04",
        )

        codes = [v.code for v in violations]
        assert "ALTITUDE_AFTER_DIVE" in codes


# =============================================================================
# 8. check_route_constraint (async)
# =============================================================================


class TestCheckRouteConstraint:
    """Tests for route validation (origin/destination checks)."""

    @pytest.mark.asyncio
    async def test_same_origin_and_destination(self):
        """Same city for origin and destination triggers SAME_CITY_ERROR."""
        plan = _make_plan(origin="London", destination="London")

        with patch(
            "app.planner.nodes.constraint_guard.validate_place_exists",
            new_callable=AsyncMock,
            return_value=(True, None),
        ):
            violations = await check_route_constraint(plan)

        same_city = [v for v in violations if v.code == "SAME_CITY_ERROR"]
        assert len(same_city) == 1
        assert same_city[0].severity == "blocking"
        assert same_city[0].category == "route"

    @pytest.mark.asyncio
    async def test_same_city_case_insensitive(self):
        """Same-city check is case-insensitive."""
        plan = _make_plan(origin="london", destination="LONDON")

        with patch(
            "app.planner.nodes.constraint_guard.validate_place_exists",
            new_callable=AsyncMock,
            return_value=(True, None),
        ):
            violations = await check_route_constraint(plan)

        same_city = [v for v in violations if v.code == "SAME_CITY_ERROR"]
        assert len(same_city) == 1

    @pytest.mark.asyncio
    async def test_different_origin_and_destination_no_violations(self):
        """Different origin/destination with valid place returns no violations."""
        plan = _make_plan(origin="London", destination="Paris")

        with patch(
            "app.planner.nodes.constraint_guard.validate_place_exists",
            new_callable=AsyncMock,
            return_value=(True, None),
        ):
            violations = await check_route_constraint(plan)

        assert violations == []

    @pytest.mark.asyncio
    async def test_unknown_destination_error(self):
        """Invalid destination triggers UNKNOWN_DESTINATION_ERROR."""
        plan = _make_plan(destination="Xyzzyplugh")

        with patch(
            "app.planner.nodes.constraint_guard.validate_place_exists",
            new_callable=AsyncMock,
            return_value=(False, "'Xyzzyplugh' is not a recognized place"),
        ):
            violations = await check_route_constraint(plan)

        unknown = [v for v in violations if v.code == "UNKNOWN_DESTINATION_ERROR"]
        assert len(unknown) == 1
        assert unknown[0].severity == "blocking"
        assert unknown[0].category == "route"
        assert "Xyzzyplugh" in unknown[0].message

    @pytest.mark.asyncio
    async def test_no_destination_skips_place_validation(self):
        """No destination set skips the place validation check entirely."""
        plan = _make_plan(destination=None)

        # validate_place_exists should NOT be called
        with patch(
            "app.planner.nodes.constraint_guard.validate_place_exists",
            new_callable=AsyncMock,
        ) as mock_validate:
            violations = await check_route_constraint(plan)
            mock_validate.assert_not_called()

        assert violations == []

    @pytest.mark.asyncio
    async def test_single_char_destination_skips_validation(self):
        """Destination with 1 char or less skips LLM validation."""
        plan = _make_plan(destination="X")

        with patch(
            "app.planner.nodes.constraint_guard.validate_place_exists",
            new_callable=AsyncMock,
        ) as mock_validate:
            violations = await check_route_constraint(plan)
            mock_validate.assert_not_called()

        assert violations == []

    @pytest.mark.asyncio
    async def test_no_origin_no_same_city_error(self):
        """Missing origin means SAME_CITY_ERROR cannot trigger."""
        plan = _make_plan(origin=None, destination="Bali")

        with patch(
            "app.planner.nodes.constraint_guard.validate_place_exists",
            new_callable=AsyncMock,
            return_value=(True, None),
        ):
            violations = await check_route_constraint(plan)

        same_city = [v for v in violations if v.code == "SAME_CITY_ERROR"]
        assert len(same_city) == 0

    @pytest.mark.asyncio
    async def test_unknown_destination_uses_reason_in_message(self):
        """When validate returns a custom reason, it is used as the violation message."""
        plan = _make_plan(destination="Atlantis")

        custom_reason = "Atlantis is a mythical city, not a real destination"
        with patch(
            "app.planner.nodes.constraint_guard.validate_place_exists",
            new_callable=AsyncMock,
            return_value=(False, custom_reason),
        ):
            violations = await check_route_constraint(plan)

        unknown = [v for v in violations if v.code == "UNKNOWN_DESTINATION_ERROR"]
        assert len(unknown) == 1
        assert unknown[0].message == custom_reason

    @pytest.mark.asyncio
    async def test_unknown_destination_none_reason_fallback(self):
        """When validate returns None reason, a default message is used."""
        plan = _make_plan(destination="Zzzland")

        with patch(
            "app.planner.nodes.constraint_guard.validate_place_exists",
            new_callable=AsyncMock,
            return_value=(False, None),
        ):
            violations = await check_route_constraint(plan)

        unknown = [v for v in violations if v.code == "UNKNOWN_DESTINATION_ERROR"]
        assert len(unknown) == 1
        assert "Zzzland" in unknown[0].message
