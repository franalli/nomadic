"""
Unit Tests for ItineraryBuilder Service

Tests multi-specialist orchestration, constraint priority, and conflict resolution.
"""

import pytest

from app.services.itinerary_builder import (
    CONSTRAINT_SEVERITY_MAP,
    DAY_CAPACITY_HOURS,
    MAX_BLOCKS_PER_DAY,
    ConstraintSeverity,
    DayBlockOutput,
    DayCardOutput,
    ItineraryBuilder,
    ItineraryBuilderInput,
    PreferenceOverrideInput,
    _parse_duration_hours,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def builder() -> ItineraryBuilder:
    """Fresh ItineraryBuilder instance."""
    return ItineraryBuilder()


@pytest.fixture
def basic_input() -> ItineraryBuilderInput:
    """Basic 6-day trip input with diving activities."""
    return ItineraryBuilderInput(
        start_date="2024-03-15",
        end_date="2024-03-20",
        strategy_sections=[
            {
                "specialist_type": "diving",
                "content_added": [
                    {"title": "USAT Liberty Wreck", "duration_hours": 3.0},
                    {"title": "Manta Point", "duration_hours": 3.0},
                ],
                "constraints_applied": [
                    {"rule": "min_24h_buffer_after_dive", "reason": "PADI safety"},
                ],
            }
        ],
        tiles={},
        destination="Bali",
    )


@pytest.fixture
def multi_specialist_input() -> ItineraryBuilderInput:
    """8-day trip with diving + hiking specialists (enough days for all activities + buffer)."""
    return ItineraryBuilderInput(
        start_date="2024-03-15",
        end_date="2024-03-22",  # 8 days: arrival + 4 activities + 1 buffer + departure + 1 extra
        strategy_sections=[
            {
                "specialist_type": "diving",
                "content_added": [
                    {"title": "USAT Liberty Wreck", "duration_hours": 3.0},
                    {"title": "Manta Point", "duration_hours": 3.0},
                ],
                "constraints_applied": [
                    {"rule": "min_24h_buffer_after_dive", "reason": "PADI safety"},
                ],
            },
            {
                "specialist_type": "hiking",
                "content_added": [
                    {"title": "Mount Batur Sunrise", "duration_hours": 4.0},
                    {"title": "Campuhan Ridge Walk", "duration_hours": 2.5},
                ],
                "constraints_applied": [
                    {"rule": "early_start_preferred", "reason": "Beat the heat"},
                ],
            },
        ],
        tiles={},
        destination="Bali",
    )


@pytest.fixture
def short_trip_input() -> ItineraryBuilderInput:
    """4-day trip (insufficient for diving + hiking + buffer)."""
    return ItineraryBuilderInput(
        start_date="2024-03-15",
        end_date="2024-03-18",
        strategy_sections=[
            {
                "specialist_type": "diving",
                "content_added": [
                    {"title": "USAT Liberty Wreck", "duration_hours": 3.0},
                    {"title": "Manta Point", "duration_hours": 3.0},
                ],
                "constraints_applied": [
                    {"rule": "min_24h_buffer_after_dive"},
                ],
            },
            {
                "specialist_type": "hiking",
                "content_added": [
                    {"title": "Mount Batur Sunrise", "duration_hours": 4.0},
                    {"title": "Campuhan Ridge Walk", "duration_hours": 2.5},
                ],
                "constraints_applied": [],
            },
        ],
        tiles={},
        destination="Bali",
    )


@pytest.fixture
def input_with_tiles() -> ItineraryBuilderInput:
    """Trip input with flight and hotel tiles."""
    return ItineraryBuilderInput(
        start_date="2024-03-15",
        end_date="2024-03-20",
        strategy_sections=[
            {
                "specialist_type": "diving",
                "content_added": [
                    {"title": "USAT Liberty Wreck", "duration_hours": 3.0},
                ],
                "constraints_applied": [],
            }
        ],
        tiles={
            "flight_001": {
                "type": "flight",
                "title": "Inbound - SFO to DPS",
                "subtitle": "United 1234",
                "meta": {"arrival_time": "14:30"},
            },
            "flight_002": {
                "type": "flight",
                "title": "Outbound - DPS to SFO",
                "subtitle": "United 5678",
                "meta": {"departure_time": "22:00"},
            },
            "hotel_001": {
                "type": "hotel",
                "title": "Ayana Resort",
                "location_label": "Jimbaran, Bali",
            },
        },
        destination="Bali",
        origin="San Francisco",
        preferences=PreferenceOverrideInput(preferred_hotel_ids=["hotel_001"]),
    )


# =============================================================================
# Test: Constraint Severity Priority
# =============================================================================


class TestConstraintSeverityPriority:
    """Test that BLOCKING > STRONG > SOFT constraint priority is enforced."""

    def test_severity_enum_ordering(self):
        """Verify severity enum values are distinct."""
        assert ConstraintSeverity.BLOCKING.value == "blocking"
        assert ConstraintSeverity.STRONG.value == "strong"
        assert ConstraintSeverity.SOFT.value == "soft"

    def test_blocking_constraints_mapped_correctly(self):
        """Verify safety constraints are classified as BLOCKING."""
        blocking_rules = [
            "min_24h_buffer_after_dive",
            "decompression_stop",
            "altitude_limit",
            "visa_requirement",
            "permit_required",
            "certification_required",
        ]
        for rule in blocking_rules:
            assert CONSTRAINT_SEVERITY_MAP.get(rule) == ConstraintSeverity.BLOCKING, (
                f"Rule '{rule}' should be BLOCKING"
            )

    def test_strong_constraints_mapped_correctly(self):
        """Verify optimization constraints are classified as STRONG."""
        strong_rules = [
            "altitude_acclimatization",
            "best_weather_window",
            "crowd_avoidance",
            "equipment_rental",
            "opening_hours",
        ]
        for rule in strong_rules:
            assert CONSTRAINT_SEVERITY_MAP.get(rule) == ConstraintSeverity.STRONG, (
                f"Rule '{rule}' should be STRONG"
            )

    def test_soft_constraints_mapped_correctly(self):
        """Verify preference constraints are classified as SOFT."""
        soft_rules = [
            "scenic_route",
            "photo_opportunity",
            "early_start_preferred",
            "minimize_walking",
        ]
        for rule in soft_rules:
            assert CONSTRAINT_SEVERITY_MAP.get(rule) == ConstraintSeverity.SOFT, (
                f"Rule '{rule}' should be SOFT"
            )

    def test_merge_constraints_sorts_by_priority(self, builder: ItineraryBuilder):
        """Verify _merge_constraints sorts BLOCKING first, then STRONG, then SOFT."""
        constraints = [
            {"rule": "early_start_preferred", "source": "hiking"},  # SOFT
            {"rule": "min_24h_buffer_after_dive", "source": "diving"},  # BLOCKING
            {"rule": "best_weather_window", "source": "hiking"},  # STRONG
        ]

        merged = builder._merge_constraints(constraints)

        assert len(merged) == 3
        assert merged[0].severity == ConstraintSeverity.BLOCKING
        assert merged[0].rule == "min_24h_buffer_after_dive"
        assert merged[1].severity == ConstraintSeverity.STRONG
        assert merged[1].rule == "best_weather_window"
        assert merged[2].severity == ConstraintSeverity.SOFT
        assert merged[2].rule == "early_start_preferred"


# =============================================================================
# Test: Activity Interleaving
# =============================================================================


class TestActivityInterleaving:
    """Test that activities from multiple specialists are interleaved across days."""

    def test_single_specialist_distribution(
        self, builder: ItineraryBuilder, basic_input: ItineraryBuilderInput
    ):
        """Single specialist activities are distributed across available days."""
        result = builder.build(basic_input)

        assert result.success
        # Should have 6 days
        assert len(result.day_cards) == 6

        # Count diving activities (excluding buffer blocks)
        diving_blocks = []
        for day in result.day_cards:
            for block in day.blocks:
                if block.specialist_type == "diving" and not block.is_buffer:
                    diving_blocks.append(block)

        assert len(diving_blocks) == 2

    def test_multi_specialist_interleaving(
        self, builder: ItineraryBuilder, multi_specialist_input: ItineraryBuilderInput
    ):
        """Multiple specialists' activities are interleaved (not clustered)."""
        result = builder.build(multi_specialist_input)

        assert result.success

        # Collect activity days per specialist
        diving_days = set()
        hiking_days = set()

        for day in result.day_cards:
            for block in day.blocks:
                if block.specialist_type == "diving":
                    diving_days.add(day.day_number)
                elif block.specialist_type == "hiking":
                    hiking_days.add(day.day_number)

        # Both specialists should have activities
        assert len(diving_days) > 0, "Should have diving activities"
        assert len(hiking_days) > 0, "Should have hiking activities"

        # Activities should be on different days (interleaved, not clustered)
        all_days = diving_days | hiking_days
        assert len(all_days) > 1, "Activities should span multiple days"

    def test_round_robin_distribution(self, builder: ItineraryBuilder):
        """Verify round-robin algorithm alternates between specialists."""
        # Create input with balanced activities
        input_data = ItineraryBuilderInput(
            start_date="2024-03-15",
            end_date="2024-03-22",  # 8 days for more room
            strategy_sections=[
                {
                    "specialist_type": "diving",
                    "content_added": [
                        {"title": f"Dive Site {i}", "duration_hours": 3.0} for i in range(3)
                    ],
                    "constraints_applied": [],
                },
                {
                    "specialist_type": "hiking",
                    "content_added": [
                        {"title": f"Trail {i}", "duration_hours": 3.0} for i in range(3)
                    ],
                    "constraints_applied": [],
                },
            ],
            tiles={},
            destination="Bali",
        )

        result = builder.build(input_data)
        assert result.success

        # Check that activities are distributed
        activity_days = []
        for day in result.day_cards:
            day_specialists = []
            for block in day.blocks:
                if block.specialist_type in ("diving", "hiking"):
                    day_specialists.append(block.specialist_type)
            if day_specialists:
                activity_days.append(day_specialists)

        # Should have activities on multiple days
        assert len(activity_days) >= 2


# =============================================================================
# Test: Diving + Hiking Combo with Buffer
# =============================================================================


# =============================================================================
# Test: Temporal Capacity (11h limit)
# =============================================================================


class TestTemporalCapacity:
    """Test that days don't exceed 11h capacity."""

    def test_day_capacity_constant(self):
        """Verify DAY_CAPACITY_HOURS is 11."""
        assert DAY_CAPACITY_HOURS == 11.0

    def test_max_blocks_per_day(self):
        """Verify MAX_BLOCKS_PER_DAY is 3."""
        assert MAX_BLOCKS_PER_DAY == 3

    def test_overflow_detection(self, builder: ItineraryBuilder):
        """Detect when a day exceeds capacity."""
        # Create day cards with overflow
        days = [
            DayCardOutput(
                day_number=1,
                label="Day 1",
                blocks=[
                    DayBlockOutput(
                        period="morning",
                        activity_type="dive",
                        summary="Morning dive",
                        duration="4h",
                        specialist_type="diving",
                    ),
                    DayBlockOutput(
                        period="afternoon",
                        activity_type="dive",
                        summary="Afternoon dive",
                        duration="4h",
                        specialist_type="diving",
                    ),
                    DayBlockOutput(
                        period="evening",
                        activity_type="hike",
                        summary="Evening hike",
                        duration="4h",
                        specialist_type="hiking",
                    ),
                ],
            )
        ]

        conflicts = builder._detect_temporal_conflicts(days)

        assert len(conflicts) == 1
        assert conflicts[0].type == "temporal_capacity"
        assert conflicts[0].day == 1
        assert conflicts[0].overflow_hours == 1.0  # 12h - 11h = 1h

    def test_normal_day_no_conflict(self, builder: ItineraryBuilder):
        """Day within capacity should have no conflicts."""
        days = [
            DayCardOutput(
                day_number=1,
                label="Day 1",
                blocks=[
                    DayBlockOutput(
                        period="morning",
                        activity_type="dive",
                        summary="Morning dive",
                        duration="3h",
                        specialist_type="diving",
                    ),
                    DayBlockOutput(
                        period="afternoon",
                        activity_type="hike",
                        summary="Afternoon hike",
                        duration="3h",
                        specialist_type="hiking",
                    ),
                ],
            )
        ]

        conflicts = builder._detect_temporal_conflicts(days)
        assert len(conflicts) == 0

    def test_buffer_blocks_excluded_from_capacity(self, builder: ItineraryBuilder):
        """Buffer blocks don't count toward capacity."""
        days = [
            DayCardOutput(
                day_number=1,
                label="Day 1",
                blocks=[
                    DayBlockOutput(
                        period="morning",
                        activity_type="arrival",
                        summary="Arrive",
                        is_buffer=True,
                        buffer_type="arrival",
                    ),
                    DayBlockOutput(
                        period="afternoon",
                        activity_type="dive",
                        summary="Afternoon dive",
                        duration="4h",
                        specialist_type="diving",
                    ),
                ],
            )
        ]

        conflicts = builder._detect_temporal_conflicts(days)
        assert len(conflicts) == 0


# =============================================================================
# Test: Conflict Resolution Generation
# =============================================================================


class TestConflictResolutionGeneration:
    """Test that conflict resolutions are properly generated."""

    def test_insufficient_days_auto_adjusts(
        self, builder: ItineraryBuilder, short_trip_input: ItineraryBuilderInput
    ):
        """4-day trip with 4 activities + buffer: builder auto-adjusts dive count."""
        result = builder.build(short_trip_input)

        # Builder auto-adjusts by reducing dives instead of failing
        assert result.success is True
        assert len(result.warnings) > 0
        assert any("adjusted" in w.lower() or "fit" in w.lower() for w in result.warnings)


# =============================================================================
# Test: Day Skeleton Creation
# =============================================================================


class TestDaySkeleton:
    """Test day card skeleton creation."""

    def test_correct_day_count(self, builder: ItineraryBuilder):
        """6-day trip creates 6 day cards."""
        start = builder._parse_date("2024-03-15")
        end = builder._parse_date("2024-03-20")

        days = builder._create_day_skeleton(start, end)

        assert len(days) == 6

    def test_arrival_departure_labels(self, builder: ItineraryBuilder):
        """First day is 'Arrival Day', last is 'Departure Day'."""
        start = builder._parse_date("2024-03-15")
        end = builder._parse_date("2024-03-20")

        days = builder._create_day_skeleton(start, end)

        assert days[0].label == "Arrival Day"
        assert days[-1].label == "Departure Day"
        assert days[2].label == "Day 3"

    def test_day_numbering(self, builder: ItineraryBuilder):
        """Days are numbered 1 through N."""
        start = builder._parse_date("2024-03-15")
        end = builder._parse_date("2024-03-20")

        days = builder._create_day_skeleton(start, end)

        for i, day in enumerate(days):
            assert day.day_number == i + 1


# =============================================================================
# Test: Anchor Placement (Flights)
# =============================================================================


class TestAnchorPlacement:
    """Test arrival/departure block placement from flight tiles."""

    def test_arrival_block_on_day_1(
        self, builder: ItineraryBuilder, input_with_tiles: ItineraryBuilderInput
    ):
        """Arrival block placed on day 1."""
        result = builder.build(input_with_tiles)

        assert result.success
        day_1 = result.day_cards[0]

        arrival_blocks = [b for b in day_1.blocks if b.buffer_type == "arrival"]
        assert len(arrival_blocks) == 1
        assert arrival_blocks[0].booking_category == "flight"

    def test_departure_block_on_last_day(
        self, builder: ItineraryBuilder, input_with_tiles: ItineraryBuilderInput
    ):
        """Departure block placed on last day."""
        result = builder.build(input_with_tiles)

        assert result.success
        last_day = result.day_cards[-1]

        departure_blocks = [b for b in last_day.blocks if b.buffer_type == "departure"]
        assert len(departure_blocks) == 1
        assert departure_blocks[0].booking_category == "flight"

    def test_flight_tile_attached(
        self, builder: ItineraryBuilder, input_with_tiles: ItineraryBuilderInput
    ):
        """Flight tiles are attached to arrival/departure blocks."""
        result = builder.build(input_with_tiles)

        assert result.success

        # Check arrival has tile
        day_1 = result.day_cards[0]
        arrival_block = next(b for b in day_1.blocks if b.buffer_type == "arrival")
        assert arrival_block.booked_tile is not None
        assert "Inbound" in arrival_block.booked_tile.get("title", "")

        # Check departure has tile
        last_day = result.day_cards[-1]
        departure_block = next(b for b in last_day.blocks if b.buffer_type == "departure")
        assert departure_block.booked_tile is not None
        assert "Outbound" in departure_block.booked_tile.get("title", "")


# =============================================================================
# Test: Hotel Tile Matching
# =============================================================================


class TestTileMatching:
    """Test hotel tile matching to day cards."""

    def test_hotel_checkin_on_day_1(
        self, builder: ItineraryBuilder, input_with_tiles: ItineraryBuilderInput
    ):
        """Hotel check-in block added to day 1."""
        result = builder.build(input_with_tiles)

        assert result.success
        day_1 = result.day_cards[0]

        checkin_blocks = [b for b in day_1.blocks if b.activity_type == "check-in"]
        assert len(checkin_blocks) == 1
        assert "Ayana Resort" in checkin_blocks[0].summary

    def test_hotel_checkout_on_last_day(
        self, builder: ItineraryBuilder, input_with_tiles: ItineraryBuilderInput
    ):
        """Hotel check-out block added to last day."""
        result = builder.build(input_with_tiles)

        assert result.success
        last_day = result.day_cards[-1]

        checkout_blocks = [b for b in last_day.blocks if b.activity_type == "check-out"]
        assert len(checkout_blocks) == 1
        assert "Ayana Resort" in checkout_blocks[0].summary


# =============================================================================
# Test: Overview Computation
# =============================================================================


class TestOverviewComputation:
    """Test itinerary overview stats generation."""

    def test_duration_label(self, builder: ItineraryBuilder, basic_input: ItineraryBuilderInput):
        """Overview shows correct duration label."""
        result = builder.build(basic_input)

        assert result.success
        assert result.overview is not None
        # basic_input is 6 days (Mar 15-20)
        assert "days" in result.overview.duration_label

    def test_multi_specialist_structure_label(
        self, builder: ItineraryBuilder, multi_specialist_input: ItineraryBuilderInput
    ):
        """Multi-specialist trips show 'Multi-activity adventure'."""
        result = builder.build(multi_specialist_input)

        assert result.success
        assert result.overview is not None
        assert "multi" in result.overview.base_structure.lower()


# =============================================================================
# Test: Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_invalid_dates_return_error(self, builder: ItineraryBuilder):
        """Invalid dates return error result."""
        input_data = ItineraryBuilderInput(
            start_date="invalid",
            end_date="2024-03-20",
            strategy_sections=[],
            tiles={},
        )

        result = builder.build(input_data)

        assert not result.success
        assert result.error is not None
        assert "date" in result.error.lower()

    def test_end_before_start_returns_error(self, builder: ItineraryBuilder):
        """End date before start date returns error."""
        input_data = ItineraryBuilderInput(
            start_date="2024-03-20",
            end_date="2024-03-15",
            strategy_sections=[],
            tiles={},
        )

        result = builder.build(input_data)

        assert not result.success
        assert "after" in result.error.lower()

    def test_empty_strategy_sections_succeeds(self, builder: ItineraryBuilder):
        """Empty strategy sections produces basic skeleton."""
        input_data = ItineraryBuilderInput(
            start_date="2024-03-15",
            end_date="2024-03-20",
            strategy_sections=[],
            tiles={},
        )

        result = builder.build(input_data)

        assert result.success
        assert len(result.day_cards) == 6

    def test_minimum_two_day_trip(self, builder: ItineraryBuilder):
        """Minimum 2-day trip (arrival + departure) handles gracefully."""
        input_data = ItineraryBuilderInput(
            start_date="2024-03-15",
            end_date="2024-03-16",
            strategy_sections=[],
            tiles={},
        )

        result = builder.build(input_data)

        assert result.success
        assert len(result.day_cards) == 2
        assert result.day_cards[0].label == "Arrival Day"
        assert result.day_cards[1].label == "Departure Day"


# =============================================================================
# Test: Specialist Content Extraction
# =============================================================================


class TestSpecialistContentExtraction:
    """Test extraction of activities and constraints from specialist sections."""

    def test_extracts_activities_from_content_added(self, builder: ItineraryBuilder):
        """Activities are extracted from content_added field."""
        sections = [
            {
                "specialist_type": "diving",
                "content_added": [
                    {
                        "title": "USAT Liberty",
                        "description": "Famous wreck dive",
                        "duration_hours": 3.0,
                        "intensity": "moderate",
                    }
                ],
                "constraints_applied": [],
            }
        ]

        activities, constraints = builder._extract_specialist_content(sections)

        assert "diving" in activities
        assert len(activities["diving"]) == 1
        assert activities["diving"][0].title == "USAT Liberty"
        assert activities["diving"][0].duration_hours == 3.0

    def test_skips_local_expert_for_activities(self, builder: ItineraryBuilder):
        """local_expert sections provide context, not bookable activities."""
        sections = [
            {
                "specialist_type": "local_expert",
                "content_added": [{"title": "Cultural Context", "description": "Local info"}],
                "constraints_applied": [],
            }
        ]

        activities, constraints = builder._extract_specialist_content(sections)

        assert "local_expert" not in activities

    def test_extracts_constraints_from_all_specialists(self, builder: ItineraryBuilder):
        """Constraints are collected from all specialists including local_expert."""
        sections = [
            {
                "specialist_type": "local_expert",
                "content_added": [],
                "constraints_applied": [{"rule": "visa_requirement"}],
            },
            {
                "specialist_type": "diving",
                "content_added": [],
                "constraints_applied": [{"rule": "min_24h_buffer_after_dive"}],
            },
        ]

        activities, constraints = builder._extract_specialist_content(sections)

        assert len(constraints) == 2
        rules = {c["rule"] for c in constraints}
        assert "visa_requirement" in rules
        assert "min_24h_buffer_after_dive" in rules


# =============================================================================
# Test: Duration Parsing Helper
# =============================================================================


class TestParseDurationHours:
    """Test _parse_duration_hours utility."""

    def test_parse_standard(self):
        assert _parse_duration_hours("4h") == 4.0

    def test_parse_decimal(self):
        assert _parse_duration_hours("1.5h") == 1.5

    def test_parse_none(self):
        assert _parse_duration_hours(None) == 3.0

    def test_parse_none_custom_default(self):
        assert _parse_duration_hours(None, 5.0) == 5.0

    def test_parse_empty(self):
        assert _parse_duration_hours("") == 3.0

    def test_parse_invalid(self):
        assert _parse_duration_hours("abc") == 3.0


# =============================================================================
# Test: Day Remaining Capacity
# =============================================================================


class TestDayRemainingCapacity:
    """Test _day_remaining_capacity helper."""

    def test_arrival_day_zero_capacity(self, builder: ItineraryBuilder):
        """Arrival day returns (0, 0)."""
        day = DayCardOutput(
            day_number=1,
            label="Arrival",
            blocks=[
                DayBlockOutput(
                    period="morning",
                    activity_type="arrival",
                    summary="Arrive",
                    is_buffer=True,
                    buffer_type="arrival",
                )
            ],
        )
        hours, blocks = builder._day_remaining_capacity(day)
        assert hours == 0.0
        assert blocks == 0

    def test_departure_day_zero_capacity(self, builder: ItineraryBuilder):
        """Departure day returns (0, 0)."""
        day = DayCardOutput(
            day_number=8,
            label="Departure",
            blocks=[
                DayBlockOutput(
                    period="morning",
                    activity_type="departure",
                    summary="Depart",
                    is_buffer=True,
                    buffer_type="departure",
                )
            ],
        )
        hours, blocks = builder._day_remaining_capacity(day)
        assert hours == 0.0
        assert blocks == 0

    def test_specialist_day_remaining(self, builder: ItineraryBuilder):
        """Day with 4h specialist has 7h remaining, 2 block slots."""
        day = DayCardOutput(
            day_number=2,
            label="Diving Day",
            blocks=[
                DayBlockOutput(
                    period="morning",
                    activity_type="usat_liberty_wreck",
                    summary="USAT Liberty Wreck",
                    specialist_type="diving",
                    duration="4h",
                )
            ],
        )
        hours, blocks = builder._day_remaining_capacity(day)
        assert hours == 7.0
        assert blocks == 2

    def test_free_day_full_capacity(self, builder: ItineraryBuilder):
        """Free day placeholder doesn't consume capacity."""
        day = DayCardOutput(
            day_number=3,
            label="Free Day",
            blocks=[
                DayBlockOutput(
                    period="morning",
                    activity_type="free_day",
                    summary="Free Day",
                )
            ],
        )
        hours, blocks = builder._day_remaining_capacity(day)
        assert hours == DAY_CAPACITY_HOURS
        assert blocks == MAX_BLOCKS_PER_DAY

    def test_full_day_zero_capacity(self, builder: ItineraryBuilder):
        """Day at capacity returns (0, 0)."""
        day = DayCardOutput(
            day_number=2,
            label="Full Day",
            blocks=[
                DayBlockOutput(
                    period="morning", activity_type="hike1", summary="Hike 1", duration="5h"
                ),
                DayBlockOutput(
                    period="afternoon", activity_type="hike2", summary="Hike 2", duration="4h"
                ),
                DayBlockOutput(
                    period="evening", activity_type="yoga", summary="Yoga", duration="2h"
                ),
            ],
        )
        hours, blocks = builder._day_remaining_capacity(day)
        assert hours == 0.0
        assert blocks == 0

    def test_buffer_blocks_dont_consume(self, builder: ItineraryBuilder):
        """Buffer blocks (no-fly) don't consume capacity."""
        day = DayCardOutput(
            day_number=4,
            label="Buffer Day",
            blocks=[
                DayBlockOutput(
                    period="morning",
                    activity_type="dive",
                    summary="Dive",
                    specialist_type="diving",
                    duration="4h",
                ),
                DayBlockOutput(
                    period="evening",
                    activity_type="no_fly_buffer",
                    summary="No-Fly Buffer",
                    is_buffer=True,
                    buffer_type="no_fly",
                ),
            ],
        )
        hours, blocks = builder._day_remaining_capacity(day)
        # Only the dive counts: 11 - 4 = 7h; buffer counts as a block slot
        # (matches frontend content policy guard)
        assert hours == 7.0
        assert blocks == 1


# =============================================================================
# Test: Time Slot Complementarity Score
# =============================================================================


class TestTimeSlotScore:
    """Test _time_slot_score helper."""

    def test_evening_on_morning_max_score(self, builder: ItineraryBuilder):
        """Evening tile on morning-only day scores 1.0."""
        day = DayCardOutput(
            day_number=2,
            label="Dive Day",
            blocks=[
                DayBlockOutput(
                    period="morning", activity_type="dive", summary="Dive", duration="4h"
                )
            ],
        )
        assert builder._time_slot_score(day, "evening") == 1.0

    def test_same_slot_low_score(self, builder: ItineraryBuilder):
        """Same-slot tile scores 0.1."""
        day = DayCardOutput(
            day_number=2,
            label="Dive Day",
            blocks=[
                DayBlockOutput(
                    period="morning", activity_type="dive", summary="Dive", duration="4h"
                )
            ],
        )
        assert builder._time_slot_score(day, "morning") == 0.1

    def test_adjacent_slot_mid_score(self, builder: ItineraryBuilder):
        """Adjacent slot scores 0.5."""
        day = DayCardOutput(
            day_number=2,
            label="Dive Day",
            blocks=[
                DayBlockOutput(
                    period="morning", activity_type="dive", summary="Dive", duration="4h"
                )
            ],
        )
        assert builder._time_slot_score(day, "afternoon") == 0.5

    def test_empty_day_max_score(self, builder: ItineraryBuilder):
        """Empty day accepts any slot at max score."""
        day = DayCardOutput(day_number=3, label="Empty", blocks=[])
        assert builder._time_slot_score(day, "evening") == 1.0


# =============================================================================
# Test: Phase 5.6 Co-Scheduling
# =============================================================================


class TestPhase56CoScheduling:
    """Test two-pass experience tile placement."""

    def _make_specialist_day(
        self, day_num: int, specialist: str, duration: str = "4h", period: str = "morning"
    ) -> DayCardOutput:
        """Helper: create a day with one specialist block."""
        return DayCardOutput(
            day_number=day_num,
            label=f"{specialist.title()} Day",
            blocks=[
                DayBlockOutput(
                    period=period,
                    activity_type=f"{specialist}_activity",
                    summary=f"{specialist.title()} Activity",
                    specialist_type=specialist,
                    duration=duration,
                )
            ],
        )

    def _make_experience_tile(
        self,
        tile_id: str,
        title: str,
        category: str = "yoga",
        time_of_day: str = "evening",
        duration_hours: float = 1.5,
    ) -> dict:
        """Helper: create an experience tile dict."""
        return {
            "id": tile_id,
            "title": title,
            "type": "activity",
            "source_agent": "experience_generator",
            "image_url": None,
            "meta": {
                "category": category,
                "time_of_day": time_of_day,
                "duration_hours": duration_hours,
            },
        }

    def test_coschedule_no_free_days(self, builder: ItineraryBuilder):
        """With 0 free days and experience tiles, tiles are co-scheduled on specialist days."""
        days = [
            DayCardOutput(
                day_number=1,
                label="Arrival",
                blocks=[
                    DayBlockOutput(
                        period="morning",
                        activity_type="arrival",
                        summary="Arrive",
                        is_buffer=True,
                        buffer_type="arrival",
                    )
                ],
            ),
            self._make_specialist_day(2, "diving"),
            self._make_specialist_day(3, "diving"),
            self._make_specialist_day(4, "hiking", duration="3h"),
            DayCardOutput(
                day_number=5,
                label="Departure",
                blocks=[
                    DayBlockOutput(
                        period="morning",
                        activity_type="departure",
                        summary="Depart",
                        is_buffer=True,
                        buffer_type="departure",
                    )
                ],
            ),
        ]

        tiles = {
            "exp_1": self._make_experience_tile("exp_1", "Sunset Yoga", "yoga", "evening", 1.5),
            "exp_2": self._make_experience_tile(
                "exp_2", "Cooking Class", "cooking", "afternoon", 2.0
            ),
        }

        result = builder._place_experience_tiles(days, tiles)

        # Arrival and departure untouched
        assert len(result[0].blocks) == 1
        assert len(result[-1].blocks) == 1

        # Specialist days should have co-scheduled blocks
        all_exp_blocks = [
            b for dc in result[1:-1] for b in dc.blocks if b.booking_category == "activity"
        ]
        assert len(all_exp_blocks) == 2

    def test_mixed_free_and_specialist(self, builder: ItineraryBuilder):
        """Free days filled first, overflow co-scheduled on specialist days."""
        days = [
            DayCardOutput(
                day_number=1,
                label="Arrival",
                blocks=[
                    DayBlockOutput(
                        period="morning",
                        activity_type="arrival",
                        summary="Arrive",
                        is_buffer=True,
                        buffer_type="arrival",
                    )
                ],
            ),
            self._make_specialist_day(2, "diving"),
            DayCardOutput(
                day_number=3,
                label="Free Day",
                blocks=[
                    DayBlockOutput(period="morning", activity_type="free_day", summary="Free Day")
                ],
            ),
            self._make_specialist_day(4, "hiking"),
            DayCardOutput(
                day_number=5,
                label="Departure",
                blocks=[
                    DayBlockOutput(
                        period="morning",
                        activity_type="departure",
                        summary="Depart",
                        is_buffer=True,
                        buffer_type="departure",
                    )
                ],
            ),
        ]

        # 3 tiles: 2 fit on free day, 1 overflows to specialist day
        tiles = {
            "exp_1": self._make_experience_tile("exp_1", "Yoga AM", "yoga", "morning", 1.5),
            "exp_2": self._make_experience_tile("exp_2", "Yoga PM", "yoga", "evening", 1.5),
            "exp_3": self._make_experience_tile(
                "exp_3", "Cooking Class", "cooking", "afternoon", 2.0
            ),
        }

        result = builder._place_experience_tiles(days, tiles)

        # Free day should have gotten tiles, no more free_day placeholder
        free_day = result[2]
        assert not any(b.activity_type == "free_day" for b in free_day.blocks)
        assert any(b.booking_category == "activity" for b in free_day.blocks)

        # Third tile co-scheduled on a specialist day
        specialist_exp = [
            b
            for dc in [result[1], result[3]]
            for b in dc.blocks
            if b.booking_category == "activity"
        ]
        assert len(specialist_exp) == 1

    def test_preserves_current_behavior_all_free(self, builder: ItineraryBuilder):
        """With only free days, tiles placed on free days (Pass 1 only, no Pass 2)."""
        days = [
            DayCardOutput(
                day_number=1,
                label="Arrival",
                blocks=[
                    DayBlockOutput(
                        period="morning",
                        activity_type="arrival",
                        summary="Arrive",
                        is_buffer=True,
                        buffer_type="arrival",
                    )
                ],
            ),
            DayCardOutput(
                day_number=2,
                label="Free Day",
                blocks=[
                    DayBlockOutput(period="morning", activity_type="free_day", summary="Free Day")
                ],
            ),
            DayCardOutput(
                day_number=3,
                label="Free Day",
                blocks=[
                    DayBlockOutput(period="morning", activity_type="free_day", summary="Free Day")
                ],
            ),
            DayCardOutput(
                day_number=4,
                label="Departure",
                blocks=[
                    DayBlockOutput(
                        period="morning",
                        activity_type="departure",
                        summary="Depart",
                        is_buffer=True,
                        buffer_type="departure",
                    )
                ],
            ),
        ]

        tiles = {
            "exp_1": self._make_experience_tile("exp_1", "Yoga", "yoga", "morning", 1.5),
        }

        result = builder._place_experience_tiles(days, tiles)

        # Tile placed on a free day
        exp_blocks = [b for dc in result for b in dc.blocks if b.booking_category == "activity"]
        assert len(exp_blocks) == 1

        # No free_day placeholders remain on days that got tiles
        day2_free = any(b.activity_type == "free_day" for b in result[1].blocks)
        day3_free = any(b.activity_type == "free_day" for b in result[2].blocks)
        # One of them should still have free_day (only 1 tile for 2 free days)
        assert day2_free != day3_free or (not day2_free and not day3_free)

    def test_no_tiles_noop(self, builder: ItineraryBuilder):
        """No experience tiles → no-op."""
        days = [
            DayCardOutput(
                day_number=1,
                label="Day 1",
                blocks=[
                    DayBlockOutput(period="morning", activity_type="free_day", summary="Free Day")
                ],
            )
        ]
        result = builder._place_experience_tiles(days, {})
        assert len(result) == 1
        assert result[0].blocks[0].activity_type == "free_day"

    def test_complementarity_scoring(self, builder: ItineraryBuilder):
        """Evening tile prefers morning-specialist day over afternoon-specialist day."""
        days = [
            DayCardOutput(
                day_number=1,
                label="Arrival",
                blocks=[
                    DayBlockOutput(
                        period="morning",
                        activity_type="arrival",
                        summary="Arrive",
                        is_buffer=True,
                        buffer_type="arrival",
                    )
                ],
            ),
            # Morning specialist — evening tile = max complement (score 1.0)
            self._make_specialist_day(2, "diving", "4h", "morning"),
            # Afternoon specialist — evening tile = adjacent (score 0.5)
            self._make_specialist_day(3, "hiking", "4h", "afternoon"),
            DayCardOutput(
                day_number=4,
                label="Departure",
                blocks=[
                    DayBlockOutput(
                        period="morning",
                        activity_type="departure",
                        summary="Depart",
                        is_buffer=True,
                        buffer_type="departure",
                    )
                ],
            ),
        ]

        tiles = {
            "exp_1": self._make_experience_tile("exp_1", "Sunset Yoga", "yoga", "evening", 1.5),
        }

        result = builder._place_experience_tiles(days, tiles)

        # Evening yoga should land on Day 2 (morning specialist, max complement)
        day2_exp = [b for b in result[1].blocks if b.booking_category == "activity"]
        assert len(day2_exp) == 1
        assert day2_exp[0].summary == "Sunset Yoga"


# =============================================================================
# Test: Phase 5.25 Co-Scheduling Fallback
# =============================================================================


class TestPhase525CoScheduling:
    """Test deferred co-scheduling in preferred activities placement."""

    def test_preferred_coschedule_no_free_days(self, builder: ItineraryBuilder):
        """Hearted activity is co-scheduled when no free days exist."""
        days = [
            DayCardOutput(
                day_number=1,
                label="Arrival",
                blocks=[
                    DayBlockOutput(
                        period="morning",
                        activity_type="arrival",
                        summary="Arrive",
                        is_buffer=True,
                        buffer_type="arrival",
                    )
                ],
            ),
            DayCardOutput(
                day_number=2,
                label="Diving Day",
                blocks=[
                    DayBlockOutput(
                        period="morning",
                        activity_type="dive",
                        summary="Dive",
                        specialist_type="diving",
                        duration="4h",
                    )
                ],
            ),
            DayCardOutput(
                day_number=3,
                label="Hiking Day",
                blocks=[
                    DayBlockOutput(
                        period="morning",
                        activity_type="hike",
                        summary="Hike",
                        specialist_type="hiking",
                        duration="4h",
                    )
                ],
            ),
            DayCardOutput(
                day_number=4,
                label="Departure",
                blocks=[
                    DayBlockOutput(
                        period="morning",
                        activity_type="departure",
                        summary="Depart",
                        is_buffer=True,
                        buffer_type="departure",
                    )
                ],
            ),
        ]

        tiles = {
            "yoga_1": {
                "id": "yoga_1",
                "title": "Sunset Yoga",
                "type": "activity",
                "image_url": None,
                "duration": "1.5h",
                "meta": {"time_of_day": "evening", "duration_hours": 1.5},
            },
        }

        preferences = PreferenceOverrideInput(preferred_activity_ids=["yoga_1"])

        result, dropped = builder._populate_free_days_with_preferences(days, tiles, preferences)

        # Yoga should be co-scheduled via Pass 2 (all slots full in Pass 1)
        assert dropped == 0

        # Find the preferred block
        pref_blocks = [
            b for dc in result for b in dc.blocks if b.preference_status == "user_preferred"
        ]
        assert len(pref_blocks) == 1
        assert pref_blocks[0].summary == "Sunset Yoga"

    def test_preferred_activity_skips_duplicate_existing_title(self, builder: ItineraryBuilder):
        """Preferred tile with an already-scheduled title should be skipped."""
        days = [
            DayCardOutput(
                day_number=1,
                label="Arrival",
                blocks=[
                    DayBlockOutput(
                        period="morning",
                        activity_type="arrival",
                        summary="Arrive",
                        is_buffer=True,
                        buffer_type="arrival",
                    )
                ],
            ),
            DayCardOutput(
                day_number=2,
                label="Surf Day",
                blocks=[
                    DayBlockOutput(
                        period="morning",
                        activity_type="surfing_at_uluwatu",
                        summary="Surfing at Uluwatu",
                        specialist_type="surfing",
                    )
                ],
            ),
            DayCardOutput(
                day_number=3,
                label="Departure",
                blocks=[
                    DayBlockOutput(
                        period="morning",
                        activity_type="departure",
                        summary="Depart",
                        is_buffer=True,
                        buffer_type="departure",
                    )
                ],
            ),
        ]

        tiles = {
            "surf_pref_1": {
                "id": "surf_pref_1",
                "title": "Surfing at Uluwatu",
                "type": "activity",
                "duration": "2h",
                "meta": {"time_of_day": "afternoon", "duration_hours": 2.0},
            }
        }
        preferences = PreferenceOverrideInput(preferred_activity_ids=["surf_pref_1"])

        result, dropped = builder._populate_free_days_with_preferences(days, tiles, preferences)

        assert dropped == 0
        pref_blocks = [
            b for dc in result for b in dc.blocks if b.preference_status == "user_preferred"
        ]
        assert len(pref_blocks) == 0

    def test_preferred_pass2_skips_duplicate_title_after_first_placement(
        self, builder: ItineraryBuilder
    ):
        """Pass 2 should not co-schedule a duplicate title from another preferred tile."""
        days = [
            DayCardOutput(
                day_number=1,
                label="Arrival",
                blocks=[
                    DayBlockOutput(
                        period="morning",
                        activity_type="arrival",
                        summary="Arrive",
                        is_buffer=True,
                        buffer_type="arrival",
                    )
                ],
            ),
            DayCardOutput(day_number=2, label="Free Day", blocks=[]),
            DayCardOutput(
                day_number=3,
                label="Departure",
                blocks=[
                    DayBlockOutput(
                        period="afternoon",
                        activity_type="departure",
                        summary="Depart",
                        is_buffer=True,
                        buffer_type="departure",
                    )
                ],
            ),
        ]

        tiles = {
            "surf_pref_1": {
                "id": "surf_pref_1",
                "title": "Surfing at Uluwatu",
                "type": "activity",
                "duration": "2h",
                "meta": {
                    "time_of_day": "afternoon",
                    "duration_hours": 2.0,
                    "specialist_type": "surfing",
                },
            },
            "surf_pref_2": {
                "id": "surf_pref_2",
                "title": "Surfing at Uluwatu",
                "type": "activity",
                "duration": "2h",
                "meta": {
                    "time_of_day": "afternoon",
                    "duration_hours": 2.0,
                    "specialist_type": "surfing",
                },
            },
        }
        preferences = PreferenceOverrideInput(
            preferred_activity_ids=["surf_pref_1", "surf_pref_2"],
            pinned_day_map={"surf_pref_1": 2, "surf_pref_2": 2},
        )

        result, dropped = builder._populate_free_days_with_preferences(days, tiles, preferences)

        assert dropped == 0
        uluwatu_blocks = [
            b for dc in result for b in dc.blocks if b.summary == "Surfing at Uluwatu"
        ]
        assert len(uluwatu_blocks) == 1


# =============================================================================
# Test: Phase 5.5 Handle Empty Days
# =============================================================================


class TestHandleEmptyDays:
    """Tests for Phase 5.5 _handle_empty_days() — free day placeholder injection."""

    def test_buffer_day_gets_free_day_after_buffer(self, builder: ItineraryBuilder):
        """Day with only a buffer block gets a free_day block appended after the buffer."""
        days = [
            DayCardOutput(day_number=1, label="Arrival Day", blocks=[]),
            DayCardOutput(
                day_number=2,
                label="Day 2",
                blocks=[
                    DayBlockOutput(
                        period="morning",
                        activity_type="no_fly_buffer",
                        summary="No-fly buffer day",
                        is_buffer=True,
                        buffer_type="no_fly",
                        specialist_type="diving",
                    )
                ],
            ),
            DayCardOutput(day_number=3, label="Departure Day", blocks=[]),
        ]

        result = builder._handle_empty_days(days, {}, tier2_categories=None)

        day2 = result[1]
        assert len(day2.blocks) == 2
        # Buffer stays at index 0
        assert day2.blocks[0].is_buffer is True
        # Free day block inserted after buffer
        free_block = day2.blocks[1]
        assert free_block.id.startswith("free_day_")
        assert free_block.activity_type == "free_day"

    def test_day_with_buffer_plus_activity_no_free_day(self, builder: ItineraryBuilder):
        """Day with buffer + real activity does NOT get a free_day block."""
        days = [
            DayCardOutput(day_number=1, label="Arrival Day", blocks=[]),
            DayCardOutput(
                day_number=2,
                label="Day 2",
                blocks=[
                    DayBlockOutput(
                        period="morning",
                        activity_type="no_fly_buffer",
                        summary="No-fly buffer",
                        is_buffer=True,
                        buffer_type="no_fly",
                    ),
                    DayBlockOutput(
                        period="afternoon",
                        activity_type="hike",
                        summary="Ridge walk",
                        specialist_type="hiking",
                    ),
                ],
            ),
            DayCardOutput(day_number=3, label="Departure Day", blocks=[]),
        ]

        result = builder._handle_empty_days(days, {}, tier2_categories=None)

        day2 = result[1]
        assert len(day2.blocks) == 2
        free_day_blocks = [b for b in day2.blocks if b.activity_type == "free_day"]
        assert len(free_day_blocks) == 0

    def test_arrival_departure_never_get_free_day(self, builder: ItineraryBuilder):
        """Day 0 (arrival) and Day N-1 (departure) with no blocks should NOT get free_day."""
        days = [
            DayCardOutput(day_number=1, label="Arrival Day", blocks=[]),
            DayCardOutput(
                day_number=2,
                label="Day 2",
                blocks=[
                    DayBlockOutput(
                        period="morning",
                        activity_type="hike",
                        summary="Trail hike",
                        specialist_type="hiking",
                    ),
                ],
            ),
            DayCardOutput(day_number=3, label="Departure Day", blocks=[]),
        ]

        result = builder._handle_empty_days(days, {}, tier2_categories=None)

        # Arrival day (index 0) should remain empty
        assert len(result[0].blocks) == 0
        # Departure day (last index) should remain empty
        assert len(result[-1].blocks) == 0

    def test_genuine_empty_day_gets_free_day(self, builder: ItineraryBuilder):
        """A middle day with zero blocks gets a free_day block."""
        days = [
            DayCardOutput(day_number=1, label="Arrival Day", blocks=[]),
            DayCardOutput(day_number=2, label="Day 2", blocks=[]),
            DayCardOutput(day_number=3, label="Departure Day", blocks=[]),
        ]

        result = builder._handle_empty_days(days, {}, tier2_categories=None)

        day2 = result[1]
        assert len(day2.blocks) == 1
        free_block = day2.blocks[0]
        assert free_block.activity_type == "free_day"
        assert free_block.id.startswith("free_day_")

    def test_tier2_label_applied_to_free_day(self, builder: ItineraryBuilder):
        """Free day block summary starts with the Tier 2 category label."""
        days = [
            DayCardOutput(day_number=1, label="Arrival Day", blocks=[]),
            DayCardOutput(day_number=2, label="Day 2", blocks=[]),
            DayCardOutput(day_number=3, label="Departure Day", blocks=[]),
        ]

        result = builder._handle_empty_days(days, {}, tier2_categories=["yoga"])

        day2 = result[1]
        free_block = day2.blocks[0]
        assert free_block.summary.startswith("Yoga")


# =============================================================================
# Test: Cross-Domain Dive → Buffer → Altitude Ordering
# =============================================================================


class TestCrossDomainOrdering:
    """Tests for cross-domain ordering: diving before hiking with buffer in between.

    Cross-domain clustering requires the explicit `no_altitude_after_dive` constraint
    in strategy_sections. The builder only activates clustering logic when that
    specific constraint is present via _find_constraint().
    """

    @pytest.fixture
    def cross_domain_input(self) -> ItineraryBuilderInput:
        """8-day trip with diving + hiking AND cross-domain constraint."""
        return ItineraryBuilderInput(
            start_date="2024-03-15",
            end_date="2024-03-22",  # 8 days
            strategy_sections=[
                {
                    "specialist_type": "diving",
                    "content_added": [
                        {"title": "USAT Liberty Wreck", "duration_hours": 3.0},
                        {"title": "Manta Point", "duration_hours": 3.0},
                    ],
                    "constraints_applied": [
                        {"rule": "min_24h_buffer_after_dive", "reason": "PADI safety"},
                        {"rule": "no_altitude_after_dive", "reason": "24h buffer before altitude"},
                    ],
                },
                {
                    "specialist_type": "hiking",
                    "content_added": [
                        {"title": "Mount Batur Sunrise", "duration_hours": 4.0},
                        {"title": "Campuhan Ridge Walk", "duration_hours": 2.5},
                    ],
                    "constraints_applied": [],
                },
            ],
            tiles={},
            destination="Bali",
        )

    def test_cross_domain_dive_buffer_altitude_ordering(
        self, builder: ItineraryBuilder, cross_domain_input: ItineraryBuilderInput
    ):
        """With no_altitude_after_dive: diving activities cluster before hiking."""
        result = builder.build(cross_domain_input)

        assert result.success

        # Collect specialist days
        diving_days = []
        hiking_days = []
        for day in result.day_cards:
            for block in day.blocks:
                if block.specialist_type == "diving" and not block.is_buffer:
                    diving_days.append(day.day_number)
                    break
            for block in day.blocks:
                if block.specialist_type == "hiking" and not block.is_buffer:
                    hiking_days.append(day.day_number)
                    break

        assert len(diving_days) > 0, "Should have diving activity days"
        assert len(hiking_days) > 0, "Should have hiking activity days"

        # Diving should come before hiking (cross-domain clustering)
        last_dive_day = max(diving_days)
        first_hike_day = min(hiking_days)
        assert last_dive_day < first_hike_day, (
            f"Diving (last day {last_dive_day}) should come before "
            f"hiking (first day {first_hike_day})"
        )

    def test_buffer_day_has_correct_metadata(
        self, builder: ItineraryBuilder, cross_domain_input: ItineraryBuilderInput
    ):
        """Cross-domain buffer block has is_buffer=True and meaningful summary."""
        result = builder.build(cross_domain_input)

        assert result.success

        # Find cross-domain buffer blocks (rest_day type, placed between dive and altitude)
        buffer_blocks = []
        for day in result.day_cards:
            for block in day.blocks:
                if block.is_buffer and block.buffer_type not in ("arrival", "departure"):
                    buffer_blocks.append(block)

        assert len(buffer_blocks) >= 1, "Should have at least one cross-domain buffer block"

        buf = buffer_blocks[0]
        assert buf.is_buffer is True
        # Cross-domain buffer uses rest_day type
        assert buf.buffer_type in ("rest_day", "no_fly")
        # Summary should reference the buffer purpose (decompression/safety/altitude/buffer)
        summary_lower = buf.summary.lower()
        assert any(
            kw in summary_lower
            for kw in ("buffer", "24h", "no-fly", "no fly", "decompression", "safety", "altitude")
        ), f"Buffer summary should reference its safety purpose, got: '{buf.summary}'"
