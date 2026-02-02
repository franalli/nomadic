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
            assert (
                CONSTRAINT_SEVERITY_MAP.get(rule) == ConstraintSeverity.BLOCKING
            ), f"Rule '{rule}' should be BLOCKING"

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
            assert (
                CONSTRAINT_SEVERITY_MAP.get(rule) == ConstraintSeverity.STRONG
            ), f"Rule '{rule}' should be STRONG"

    def test_soft_constraints_mapped_correctly(self):
        """Verify preference constraints are classified as SOFT."""
        soft_rules = [
            "scenic_route",
            "photo_opportunity",
            "early_start_preferred",
            "minimize_walking",
        ]
        for rule in soft_rules:
            assert (
                CONSTRAINT_SEVERITY_MAP.get(rule) == ConstraintSeverity.SOFT
            ), f"Rule '{rule}' should be SOFT"

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

    def test_insufficient_days_triggers_conflict(
        self, builder: ItineraryBuilder, short_trip_input: ItineraryBuilderInput
    ):
        """4-day trip with 4 activities + 1 buffer = insufficient days."""
        result = builder.build(short_trip_input)

        # Should fail due to insufficient days
        assert not result.success
        assert result.error == "CONSTRAINT_CONFLICT"
        assert len(result.conflicts) > 0
        assert any(c.type == "insufficient_days" for c in result.conflicts)

    def test_extend_trip_resolution_generated(
        self, builder: ItineraryBuilder, short_trip_input: ItineraryBuilderInput
    ):
        """Conflict generates 'extend trip' resolution."""
        result = builder.build(short_trip_input)

        assert not result.success
        assert len(result.resolutions) > 0

        extend_resolutions = [r for r in result.resolutions if r.action == "extend_trip"]
        assert len(extend_resolutions) >= 1
        assert extend_resolutions[0].new_duration is not None
        assert extend_resolutions[0].feasibility == "recommended"

    def test_reduce_activities_resolution_generated(
        self, builder: ItineraryBuilder, short_trip_input: ItineraryBuilderInput
    ):
        """Conflict generates 'focus on X only' resolutions."""
        result = builder.build(short_trip_input)

        assert not result.success
        assert len(result.resolutions) > 0

        reduce_resolutions = [r for r in result.resolutions if r.action == "reduce_activities"]
        assert len(reduce_resolutions) >= 2  # One per specialist

        # Check that both specialists are offered
        kept_specialists = {r.keep_specialist for r in reduce_resolutions}
        assert "diving" in kept_specialists
        assert "hiking" in kept_specialists


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
