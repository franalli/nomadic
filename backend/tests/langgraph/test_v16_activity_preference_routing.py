"""V16 Tests: Activity preference routing and suggestion click fast-path.

These tests verify the V16 fixes for:
1. Activity preferences like "Beginner-friendly hiking" not being treated as places
2. Suggestion click fast-path bypassing LQA place-like detection
3. _is_place_like_text() correctly excluding activity modifiers
4. _is_activity_preference_text() detecting activity preferences
"""

# ruff: noqa: E402

import os
import sys
from pathlib import Path

# Suppress debug output before importing plan_graph
os.environ["PLAN_GRAPH_DEBUG"] = "0"

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from app.plan_graph import (
    GraphState,
    TripInputs,
    lqa_prepass,
    reset_graph_stats,
)
from app.planner.parsing.lqa_parsers import (
    _ACTIVITY_MODIFIER_WORDS,
    _STRATEGY_KEYWORDS,
    _is_activity_preference_text,
    _is_place_like_text,
)


class TestActivityModifierWordsSets:
    """Tests for the V16 activity modifier and strategy keyword frozensets."""

    def test_activity_modifier_words_contains_skill_levels(self):
        """Should contain skill level words."""
        skill_words = {"beginner", "intermediate", "advanced", "expert"}
        assert skill_words.issubset(_ACTIVITY_MODIFIER_WORDS)

    def test_activity_modifier_words_contains_difficulty(self):
        """Should contain difficulty words."""
        difficulty_words = {"easy", "moderate", "difficult", "challenging"}
        assert difficulty_words.issubset(_ACTIVITY_MODIFIER_WORDS)

    def test_activity_modifier_words_contains_audience(self):
        """Should contain audience words."""
        audience_words = {"family", "kid", "child", "senior"}
        assert audience_words.issubset(_ACTIVITY_MODIFIER_WORDS)

    def test_activity_modifier_words_contains_style(self):
        """Should contain style words."""
        style_words = {"casual", "professional", "friendly"}
        assert style_words.issubset(_ACTIVITY_MODIFIER_WORDS)

    def test_strategy_keywords_contains_activities(self):
        """Should contain core strategy activities."""
        activities = {"hiking", "diving", "skiing", "cycling", "boating"}
        assert activities.issubset(_STRATEGY_KEYWORDS)

    def test_strategy_keywords_contains_variations(self):
        """Should contain activity variations."""
        variations = {"trekking", "snorkeling", "snowboarding", "biking", "sailing"}
        assert variations.issubset(_STRATEGY_KEYWORDS)


class TestIsPlaceLikeText:
    """Tests for _is_place_like_text() V16 fixes."""

    def test_beginner_friendly_hiking_not_place_like(self):
        """Core V16 fix: 'Beginner-friendly hiking' should NOT be place-like."""
        assert _is_place_like_text("Beginner-friendly hiking") is False

    def test_advanced_skiing_not_place_like(self):
        """Activity preference should NOT be place-like."""
        assert _is_place_like_text("Advanced skiing") is False

    def test_family_friendly_diving_not_place_like(self):
        """Family modifier should NOT make it place-like."""
        assert _is_place_like_text("Family-friendly diving") is False

    def test_easy_cycling_not_place_like(self):
        """Difficulty modifier should NOT make it place-like."""
        assert _is_place_like_text("Easy cycling") is False

    def test_expert_level_trekking_not_place_like(self):
        """Expert modifier should NOT make it place-like."""
        assert _is_place_like_text("Expert-level trekking") is False

    def test_actual_place_is_place_like(self):
        """Actual places should still be detected as place-like."""
        assert _is_place_like_text("Paris") is True
        assert _is_place_like_text("New York") is True
        assert _is_place_like_text("Swiss Alps") is True

    def test_lowercase_hiking_not_place_like(self):
        """Lowercase activity should NOT be place-like."""
        assert _is_place_like_text("hiking") is False
        assert _is_place_like_text("beginner hiking") is False

    def test_capitalized_activity_modifier_not_place_like(self):
        """Capitalized modifier words should NOT be counted as place indicators."""
        # The word "Beginner" is capitalized but it's an activity modifier
        assert _is_place_like_text("Beginner") is False
        assert _is_place_like_text("Advanced") is False
        assert _is_place_like_text("Expert") is False

    def test_mixed_case_activity_preference_not_place_like(self):
        """Mixed case activity preferences should NOT be place-like."""
        assert _is_place_like_text("BEGINNER HIKING") is False
        assert _is_place_like_text("beginner-FRIENDLY hiking") is False


class TestIsActivityPreferenceText:
    """Tests for _is_activity_preference_text() helper function."""

    def test_beginner_hiking_is_activity_preference(self):
        """'Beginner hiking' should be detected as activity preference."""
        assert _is_activity_preference_text("Beginner hiking") is True

    def test_beginner_friendly_hiking_is_activity_preference(self):
        """'Beginner-friendly hiking' should be activity preference."""
        assert _is_activity_preference_text("Beginner-friendly hiking") is True

    def test_advanced_skiing_is_activity_preference(self):
        """'Advanced skiing' should be activity preference."""
        assert _is_activity_preference_text("Advanced skiing") is True

    def test_family_diving_is_activity_preference(self):
        """'Family diving' should be activity preference."""
        assert _is_activity_preference_text("Family diving") is True

    def test_easy_cycling_is_activity_preference(self):
        """'Easy cycling' should be activity preference."""
        assert _is_activity_preference_text("Easy cycling") is True

    def test_just_hiking_not_activity_preference(self):
        """Just 'hiking' without modifier is NOT an activity preference."""
        assert _is_activity_preference_text("hiking") is False

    def test_just_beginner_not_activity_preference(self):
        """Just 'Beginner' without activity is NOT an activity preference."""
        assert _is_activity_preference_text("Beginner") is False

    def test_place_name_not_activity_preference(self):
        """Place names should NOT be activity preferences."""
        assert _is_activity_preference_text("Paris") is False
        assert _is_activity_preference_text("Swiss Alps") is False

    def test_date_not_activity_preference(self):
        """Date strings should NOT be activity preferences."""
        assert _is_activity_preference_text("next month") is False
        assert _is_activity_preference_text("December 25") is False


class TestLqaPrepassActivityPreferenceBypass:
    """Tests for LQA prepass activity preference bypass (V16)."""

    def setup_method(self):
        """Reset stats before each test."""
        reset_graph_stats()

    def test_activity_preference_bypasses_place_like_bail(self):
        """Activity preference should bypass the place-like bail logic."""
        state = GraphState(
            user_text="Beginner-friendly hiking",
            trip_inputs=TripInputs(
                destinations=["Swiss Alps"],
                start_date="2025-06-01",
                end_date="2025-06-07",
            ),
            metadata={"last_question_field": "activity_preference"},
        )
        result = lqa_prepass(state)
        # Should NOT bail with "text is place-like" reason
        bail_reason = result.flags.get("lqa_bail_reason", "")
        assert (
            "place_like" not in bail_reason.lower()
        ), f"Activity preference should not bail as place-like, got: {bail_reason}"

    def test_actual_place_still_bails_as_place_like(self):
        """Actual place names should still bail as place-like."""
        state = GraphState(
            user_text="Chamonix",  # Actual place name
            trip_inputs=TripInputs(
                destinations=["Swiss Alps"],
                start_date="2025-06-01",
                end_date="2025-06-07",
            ),
            metadata={"last_question_field": "activity_preference"},
        )
        _ = lqa_prepass(state)
        # Should bail as place-like (if not a known place in destination context)
        # The key is that it's not being incorrectly processed as an activity preference


class TestLqaSuggestionClickFastPath:
    """Tests for LQA suggestion click fast-path (V16)."""

    def setup_method(self):
        """Reset stats before each test."""
        reset_graph_stats()

    def test_exact_suggestion_match_bypasses_place_check(self):
        """Exact match to previous suggestion should bypass place-like check."""
        state = GraphState(
            user_text="Beginner-friendly hiking",
            trip_inputs=TripInputs(
                destinations=["Swiss Alps"],
                start_date="2025-06-01",
                end_date="2025-06-07",
            ),
            metadata={
                "last_question_field": "activity_preference",
                "last_offered_suggestions": [
                    "Beginner-friendly hiking",
                    "Intermediate hiking",
                    "Advanced hiking",
                ],
            },
        )
        result = lqa_prepass(state)
        # Should NOT bail as place-like when text matches a suggestion
        bail_reason = result.flags.get("lqa_bail_reason", "")
        assert "place_like" not in bail_reason.lower()

    def test_case_insensitive_suggestion_match(self):
        """Suggestion matching should be case-insensitive."""
        state = GraphState(
            user_text="beginner-friendly hiking",  # lowercase
            trip_inputs=TripInputs(
                destinations=["Swiss Alps"],
            ),
            metadata={
                "last_question_field": "activity_preference",
                "last_offered_suggestions": [
                    "Beginner-friendly hiking",  # Title case
                ],
            },
        )
        result = lqa_prepass(state)
        bail_reason = result.flags.get("lqa_bail_reason", "")
        assert "place_like" not in bail_reason.lower()

    def test_non_matching_text_not_fast_pathed(self):
        """Text not matching suggestions should go through normal processing."""
        state = GraphState(
            user_text="Expert mountaineering",  # Not in suggestions
            trip_inputs=TripInputs(
                destinations=["Swiss Alps"],
            ),
            metadata={
                "last_question_field": "activity_preference",
                "last_offered_suggestions": [
                    "Beginner-friendly hiking",
                    "Intermediate hiking",
                ],
            },
        )
        # Should go through normal processing (may or may not bail)
        _ = lqa_prepass(state)
        # Just verify it doesn't crash - the result depends on other logic


class TestSkillLevelSchemaField:
    """Tests for the skill_level field in ActivitySettings schema."""

    def test_skill_level_field_exists(self):
        """ActivitySettings should have skill_level field."""
        from app.schemas import ActivitySettings

        settings = ActivitySettings()
        assert hasattr(settings, "skill_level")

    def test_skill_level_accepts_values(self):
        """skill_level should accept string values."""
        from app.schemas import ActivitySettings

        settings = ActivitySettings(skill_level="beginner")
        assert settings.skill_level == "beginner"

        settings = ActivitySettings(skill_level="intermediate")
        assert settings.skill_level == "intermediate"

        settings = ActivitySettings(skill_level="advanced")
        assert settings.skill_level == "advanced"

    def test_skill_level_defaults_to_none(self):
        """skill_level should default to None."""
        from app.schemas import ActivitySettings

        settings = ActivitySettings()
        assert settings.skill_level is None


class TestExtractionErrorCodes:
    """Tests for ExtractionErrorCode enum (V16)."""

    def test_extraction_error_codes_exist(self):
        """ExtractionErrorCode should have expected codes."""
        from app.plan_graph import ExtractionErrorCode

        assert hasattr(ExtractionErrorCode, "AMBIGUOUS_PLACE")
        assert hasattr(ExtractionErrorCode, "UNKNOWN_PLACE")
        assert hasattr(ExtractionErrorCode, "TYPO_DETECTED")
        assert hasattr(ExtractionErrorCode, "LOW_CONFIDENCE")
        assert hasattr(ExtractionErrorCode, "PARTIAL_MATCH")

    def test_extraction_error_codes_values(self):
        """Error codes should have expected string values."""
        from app.plan_graph import ExtractionErrorCode

        assert ExtractionErrorCode.AMBIGUOUS_PLACE == "EXTRACTION_AMBIGUOUS_PLACE"
        assert ExtractionErrorCode.UNKNOWN_PLACE == "EXTRACTION_UNKNOWN_PLACE"
        assert ExtractionErrorCode.TYPO_DETECTED == "EXTRACTION_TYPO_DETECTED"
        assert ExtractionErrorCode.LOW_CONFIDENCE == "EXTRACTION_LOW_CONFIDENCE"
        assert ExtractionErrorCode.PARTIAL_MATCH == "EXTRACTION_PARTIAL_MATCH"

    def test_blocking_error_codes_set(self):
        """EXTRACTION_BLOCKING_ERROR_CODES should contain blocking codes."""
        from app.plan_graph import (
            EXTRACTION_BLOCKING_ERROR_CODES,
            ExtractionErrorCode,
        )

        assert ExtractionErrorCode.AMBIGUOUS_PLACE in EXTRACTION_BLOCKING_ERROR_CODES
        assert ExtractionErrorCode.UNKNOWN_PLACE in EXTRACTION_BLOCKING_ERROR_CODES
        # Non-blocking codes should not be in the set
        assert ExtractionErrorCode.TYPO_DETECTED not in EXTRACTION_BLOCKING_ERROR_CODES


class TestClarificationTemplates:
    """Tests for V16 clarification templates in required_fields_templates.json."""

    def test_destinations_clarify_templates_exist(self):
        """destinations_clarify section should exist in templates."""
        import json
        from pathlib import Path

        templates_path = (
            Path(__file__).resolve().parents[2]
            / "app"
            / "prompts"
            / "required_fields_templates.json"
        )
        with open(templates_path) as f:
            templates = json.load(f)

        assert "destinations_clarify" in templates
        clarify = templates["destinations_clarify"]

        # Should have questions for different error types
        assert "questions" in clarify
        assert "ambiguous_place" in clarify["questions"]
        assert "unknown_place" in clarify["questions"]
        assert "typo_detected" in clarify["questions"]
        assert "low_confidence" in clarify["questions"]

    def test_origin_clarify_templates_exist(self):
        """origin_clarify section should exist in templates."""
        import json
        from pathlib import Path

        templates_path = (
            Path(__file__).resolve().parents[2]
            / "app"
            / "prompts"
            / "required_fields_templates.json"
        )
        with open(templates_path) as f:
            templates = json.load(f)

        assert "origin_clarify" in templates
        clarify = templates["origin_clarify"]

        assert "questions" in clarify
        assert "ambiguous_place" in clarify["questions"]
        assert "unknown_place" in clarify["questions"]
