"""
Tests for Stage 11: Activity Day Preferences + Smart Suggestion Chips

Session A: RouterOutput parsing, builder day-preference capping, constraint guard capacity
Session B: Suggestion chip metadata population
"""

import pytest

from app.planner.nodes.router_extraction import RouterOutput, _parse_day_preferences
from app.services.itinerary_builder import ItineraryBuilder, ItineraryBuilderInput

# =============================================================================
# Session A: Router Extraction — RouterOutput parsing
# =============================================================================


class TestRouterOutputDayPreferences:
    """RouterOutput parses activity_day_preferences correctly (JSON string field)."""

    def test_day_preferences_extracted(self):
        """Explicit day counts are parsed from JSON string."""
        raw = {
            "intent": "PLANNING",
            "confidence": 0.9,
            "reasoning": "User wants diving and hiking with specific day counts",
            "destination": "Bali",
            "activity_day_preferences": '{"diving": 3, "hiking": 2}',
        }
        output = RouterOutput(**raw)
        assert _parse_day_preferences(output.activity_day_preferences) == {"diving": 3, "hiking": 2}

    def test_day_preferences_empty_when_not_specified(self):
        """No day preferences → None (default)."""
        raw = {
            "intent": "PLANNING",
            "confidence": 0.9,
            "reasoning": "User wants Bali",
            "destination": "Bali",
        }
        output = RouterOutput(**raw)
        assert _parse_day_preferences(output.activity_day_preferences) == {}

    def test_day_preferences_null_explicit(self):
        """Explicit null when no counts mentioned."""
        raw = {
            "intent": "PLANNING",
            "confidence": 0.9,
            "reasoning": "Vague request",
            "destination": "Bali",
            "activity_day_preferences": None,
        }
        output = RouterOutput(**raw)
        assert _parse_day_preferences(output.activity_day_preferences) == {}

    def test_single_activity_preference(self):
        """Single activity with day count."""
        raw = {
            "intent": "PLANNING",
            "confidence": 0.9,
            "reasoning": "Week of surfing",
            "destination": "Bali",
            "activity_day_preferences": '{"surfing": 7}',
        }
        output = RouterOutput(**raw)
        assert _parse_day_preferences(output.activity_day_preferences) == {"surfing": 7}

    def test_invalid_json_returns_empty(self):
        """Invalid JSON string → empty dict."""
        assert _parse_day_preferences("not valid json") == {}
        assert _parse_day_preferences('["list"]') == {}
        assert _parse_day_preferences("") == {}


# =============================================================================
# Session A: Builder — Day Preference Capping
# =============================================================================


class TestBuilderDayPreferences:
    """Builder respects day_preferences by capping activity counts per specialist."""

    @pytest.fixture
    def builder(self) -> ItineraryBuilder:
        return ItineraryBuilder()

    def test_day_preferences_cap_activities(self, builder: ItineraryBuilder):
        """Builder caps specialist activities to user-requested day count."""
        input_data = ItineraryBuilderInput(
            start_date="2026-02-15",
            end_date="2026-02-22",  # 8 days
            strategy_sections=[
                {
                    "specialist_type": "diving",
                    "content_added": [
                        {"title": f"Dive Site {i}", "duration_hours": 3.0}
                        for i in range(5)  # 5 dive activities
                    ],
                    "constraints_applied": [],
                },
                {
                    "specialist_type": "hiking",
                    "content_added": [
                        {"title": f"Trail {i}", "duration_hours": 3.0}
                        for i in range(4)  # 4 hiking activities
                    ],
                    "constraints_applied": [],
                },
            ],
            tiles={},
            destination="Bali",
            activity_day_preferences={"diving": 3, "hiking": 2},
        )

        result = builder.build(input_data)
        assert result.success

        # Count activity blocks per specialist
        diving_blocks = [
            b
            for dc in result.day_cards
            for b in dc.blocks
            if b.specialist_type == "diving" and not b.is_buffer
        ]
        hiking_blocks = [
            b
            for dc in result.day_cards
            for b in dc.blocks
            if b.specialist_type == "hiking" and not b.is_buffer
        ]

        # Should be capped to preferences
        assert len(diving_blocks) <= 3, f"Expected ≤3 diving, got {len(diving_blocks)}"
        assert len(hiking_blocks) <= 2, f"Expected ≤2 hiking, got {len(hiking_blocks)}"

    def test_day_preferences_cap_when_fewer_available(self, builder: ItineraryBuilder):
        """If specialist has fewer activities than requested, place all of them."""
        input_data = ItineraryBuilderInput(
            start_date="2026-02-15",
            end_date="2026-02-22",  # 8 days
            strategy_sections=[
                {
                    "specialist_type": "diving",
                    "content_added": [
                        {"title": "Dive Site 1", "duration_hours": 3.0},
                        {"title": "Dive Site 2", "duration_hours": 3.0},
                    ],
                    "constraints_applied": [],
                },
            ],
            tiles={},
            destination="Bali",
            activity_day_preferences={"diving": 5},  # Request 5 but only 2 available
        )

        result = builder.build(input_data)
        assert result.success

        diving_blocks = [
            b
            for dc in result.day_cards
            for b in dc.blocks
            if b.specialist_type == "diving" and not b.is_buffer
        ]

        # Should place all 2 available (not crash trying to find 5)
        assert len(diving_blocks) == 2

    def test_no_preferences_unchanged_behavior(self, builder: ItineraryBuilder):
        """Empty day_preferences = existing round-robin behavior (all activities placed)."""
        input_data = ItineraryBuilderInput(
            start_date="2026-02-15",
            end_date="2026-02-22",  # 8 days
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
            # No activity_day_preferences
        )

        result = builder.build(input_data)
        assert result.success

        diving_blocks = [
            b
            for dc in result.day_cards
            for b in dc.blocks
            if b.specialist_type == "diving" and not b.is_buffer
        ]
        hiking_blocks = [
            b
            for dc in result.day_cards
            for b in dc.blocks
            if b.specialist_type == "hiking" and not b.is_buffer
        ]

        # All activities placed (no capping)
        assert len(diving_blocks) == 3
        assert len(hiking_blocks) == 3

    def test_partial_preferences_only_caps_specified(self, builder: ItineraryBuilder):
        """Day preferences for one specialist don't affect others."""
        input_data = ItineraryBuilderInput(
            start_date="2026-02-15",
            end_date="2026-02-22",  # 8 days
            strategy_sections=[
                {
                    "specialist_type": "diving",
                    "content_added": [
                        {"title": f"Dive Site {i}", "duration_hours": 3.0} for i in range(4)
                    ],
                    "constraints_applied": [],
                },
                {
                    "specialist_type": "hiking",
                    "content_added": [
                        {"title": f"Trail {i}", "duration_hours": 3.0} for i in range(4)
                    ],
                    "constraints_applied": [],
                },
            ],
            tiles={},
            destination="Bali",
            activity_day_preferences={"diving": 2},  # Only cap diving, hiking uncapped
        )

        result = builder.build(input_data)
        assert result.success

        diving_blocks = [
            b
            for dc in result.day_cards
            for b in dc.blocks
            if b.specialist_type == "diving" and not b.is_buffer
        ]
        hiking_blocks = [
            b
            for dc in result.day_cards
            for b in dc.blocks
            if b.specialist_type == "hiking" and not b.is_buffer
        ]

        assert len(diving_blocks) <= 2, f"Diving should be capped to 2, got {len(diving_blocks)}"
        # Hiking should get all 4 (or as many as fit, uncapped)
        assert len(hiking_blocks) >= 3, f"Hiking should be uncapped, got {len(hiking_blocks)}"


# =============================================================================
# Session A: Constraint Guard — Day Preference Capacity (Unit-Level)
# =============================================================================


class TestDayPreferenceCapacityViolation:
    """Test DAY_PREFERENCE_EXCEEDS_CAPACITY detection.

    The capacity check lives inside the constraint_guard() node function,
    not ConstraintGuard.check_all(). We test it via the ActivitySettings schema
    and verify the violation model works.
    """

    def test_activity_settings_accepts_day_preferences(self):
        """ActivitySettings schema accepts day_preferences dict."""
        from app.schemas import ActivitySettings

        settings = ActivitySettings(
            categories=["diving", "hiking"],
            day_preferences={"diving": 3, "hiking": 2},
        )
        assert settings.day_preferences == {"diving": 3, "hiking": 2}

    def test_activity_settings_default_empty(self):
        """ActivitySettings defaults day_preferences to empty dict."""
        from app.schemas import ActivitySettings

        settings = ActivitySettings()
        assert settings.day_preferences == {}

    def test_constraint_violation_model(self):
        """ConstraintViolation accepts all required fields for day preference check."""
        from app.planner.nodes.constraint_guard import ConstraintViolation

        v = ConstraintViolation(
            code="DAY_PREFERENCE_EXCEEDS_CAPACITY",
            message="Requested 8 activity days but only 5 available (1 buffer day(s) required)",
            severity="blocking",
            category="capacity",
            suggested_action="Extend trip by 3 days",
        )
        assert v.code == "DAY_PREFERENCE_EXCEEDS_CAPACITY"
        assert v.severity == "blocking"
        assert v.category == "capacity"
        assert "Extend trip by 3 days" in v.suggested_action


# =============================================================================
# Session B: Suggestion Chip Metadata
# =============================================================================


class TestSuggestionChipMetaSchema:
    """Test SuggestionChipMeta Pydantic model."""

    def test_schema_defaults(self):
        """SuggestionChipMeta has correct defaults."""
        from app.schemas import SuggestionChipMeta

        meta = SuggestionChipMeta()
        assert meta.chip_type == "follow_up"
        assert meta.category == ""
        assert meta.icon is None

    def test_schema_cta(self):
        """CTA chip type with icon."""
        from app.schemas import SuggestionChipMeta

        meta = SuggestionChipMeta(
            chip_type="cta",
            category="date_prompt",
            icon="calendar",
        )
        assert meta.chip_type == "cta"
        assert meta.category == "date_prompt"
        assert meta.icon == "calendar"

    def test_schema_setting_type(self):
        """Setting chip type."""
        from app.schemas import SuggestionChipMeta

        meta = SuggestionChipMeta(
            chip_type="setting",
            category="plan_hotel_pref",
            icon="sliders-horizontal",
        )
        assert meta.chip_type == "setting"

    def test_plan_document_data_has_meta_field(self):
        """PlanDocumentData includes suggested_response_meta field."""
        from app.schemas import PlanDocumentData

        doc = PlanDocumentData(
            suggested_responses=["Plan my trip", "Show me flights"],
            suggested_response_meta=[
                {"chip_type": "cta", "category": "destination_choice", "icon": None},
                {"chip_type": "follow_up", "category": "logistics", "icon": "compass"},
            ],
        )
        assert len(doc.suggested_response_meta) == 2
        assert doc.suggested_response_meta[0]["chip_type"] == "cta"
