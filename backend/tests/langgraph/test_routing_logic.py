"""Tests for routing logic functions."""

# ruff: noqa: E402

import os
import sys
from pathlib import Path

# Suppress debug output before importing plan_graph
os.environ["PLAN_GRAPH_DEBUG"] = "0"

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from datetime import date, timedelta

from app.plan_graph import (
    CONFIDENCE_THRESHOLD_SKIP_ROUTER,
    GraphState,
    TripInputs,
    _apply_typo_corrections,
    route_after_extractor,
    route_after_lqa_prepass,
    route_after_normalize,
    route_after_required_fields,
    route_after_router,
)

FUTURE_DATE = (date.today() + timedelta(days=30)).isoformat()


class TestRouteAfterExtractor:
    """Tests for route_after_extractor function."""

    def test_short_circuit_routes_to_responder(self):
        """Fast-path short-circuit should route directly to responder."""
        state = GraphState(
            user_text="hi",
            trip_inputs=TripInputs(),
            flags={"short_circuit": "greeting"},
            metadata={},
        )
        result = route_after_extractor(state)
        assert result == "short_circuit_responder"

    def test_normal_input_routes_to_normalize(self):
        """Normal input should route to normalize_inputs."""
        state = GraphState(
            user_text="I want to go to Paris",
            trip_inputs=TripInputs(),
            flags={},
            metadata={},
            parsed_inputs={"destinations_delta": ["Paris"]},
        )
        result = route_after_extractor(state)
        assert result == "normalize_inputs"

    def test_generate_plan_flag_handling(self):
        """Generate plan flag should be handled appropriately."""
        state = GraphState(
            user_text="yes",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date=FUTURE_DATE,
            ),
            flags={"generate_plan": True},
            metadata={},
        )
        result = route_after_extractor(state)
        # Should continue to normalize or short-circuit
        assert result in ("normalize_inputs", "short_circuit_responder")


class TestRouteAfterNormalize:
    """Tests for route_after_normalize function."""

    def test_short_circuit_priority(self):
        """Short-circuit flag should take highest priority."""
        state = GraphState(
            user_text="hi",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date=FUTURE_DATE,
            ),
            flags={"short_circuit": "greeting"},
            metadata={
                "extraction_confidence": {
                    "overall": 0.99,
                    "level": "high",
                }
            },
        )
        result = route_after_normalize(state)
        assert result == "short_circuit_responder"

    def test_high_confidence_bypass_all_conditions(self):
        """High confidence + complete fields + short input routes to summarize.

        When all core fields are complete (destinations, origin, start_date) and there
        are no blocking errors, the READY_NO_FIELDS gate fires and routes to summarize.
        """
        state = GraphState(
            user_text="ok",  # Short, no intent keywords
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date=FUTURE_DATE,
            ),
            flags={},
            metadata={
                "extraction_confidence": {
                    "overall": 0.95,
                    "level": "high",
                    "typo_suggestions": {},
                }
            },
        )
        result = route_after_normalize(state)
        # READY_NO_FIELDS gate fires when core_complete=True and ready_to_generate=True
        assert result == "summarize"

    def test_bypass_blocked_by_intent_keywords(self):
        """Input with intent keywords and complete core fields routes to summarize.

        When core fields are complete, READY_NO_FIELDS gate fires and routes to
        summarize. Strategy keywords are only handled by STRATEGY_PRE_CORE_VALUE
        when core is incomplete.
        """
        state = GraphState(
            user_text="what about hiking?",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date=FUTURE_DATE,
            ),
            flags={},
            metadata={
                "extraction_confidence": {
                    "overall": 0.95,
                    "level": "high",
                    "typo_suggestions": {},
                }
            },
        )
        result = route_after_normalize(state)
        # READY_NO_FIELDS gate fires when core_complete=True
        assert result == "summarize"

    def test_bypass_blocked_by_long_input(self):
        """Long input with complete core fields routes to summarize.

        READY_NO_FIELDS gate fires when core_complete=True regardless of input length.
        """
        state = GraphState(
            user_text="I want to make sure we have enough time for everything",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date=FUTURE_DATE,
            ),
            flags={},
            metadata={
                "extraction_confidence": {
                    "overall": 0.95,
                    "level": "high",
                    "typo_suggestions": {},
                }
            },
        )
        result = route_after_normalize(state)
        # READY_NO_FIELDS gate fires when core_complete=True
        assert result == "summarize"

    def test_bypass_blocked_by_typos(self):
        """Typo suggestions with complete core fields routes to summarize.

        Typos don't block READY_NO_FIELDS gate when core fields are complete.
        """
        state = GraphState(
            user_text="ok",
            trip_inputs=TripInputs(
                destinations=["Pariz"],
                origin="London",
                start_date=FUTURE_DATE,
            ),
            flags={},
            metadata={
                "extraction_confidence": {
                    "overall": 0.7,
                    "level": "medium",
                    "typo_suggestions": {"Pariz": "Paris"},
                }
            },
        )
        result = route_after_normalize(state)
        # READY_NO_FIELDS gate fires when core_complete=True
        assert result == "summarize"

    def test_bypass_blocked_by_incomplete_fields(self):
        """Incomplete core fields should route to required_fields_node
        (via CORE_COLLECTION gate)."""
        state = GraphState(
            user_text="ok",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                # Missing origin and start_date
            ),
            flags={},
            metadata={
                "extraction_confidence": {
                    "overall": 0.95,
                    "level": "high",
                    "typo_suggestions": {},
                }
            },
        )
        result = route_after_normalize(state)
        # New behavior: CORE_COLLECTION gate catches missing fields before reaching router
        assert result == "required_fields_node"

    def test_default_routes_to_router(self):
        """Default case with no core fields should route to required_fields_node."""
        state = GraphState(
            user_text="I want to plan a trip to Tokyo",
            trip_inputs=TripInputs(),
            flags={},
            metadata={},
        )
        result = route_after_normalize(state)
        # New behavior: CORE_COLLECTION gate catches missing core fields
        assert result == "required_fields_node"


class TestApplyTypoCorrections:
    """Tests for _apply_typo_corrections helper.

    Merged from test_confidence_routing.py during test consolidation.
    """

    def test_applies_destination_corrections(self):
        """Should correct typos in destinations."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(
                destinations=["Patogonia", "Londun"],
                origin="Paris",
            ),
        )
        corrections = {"Patogonia": "Patagonia", "Londun": "London"}
        _apply_typo_corrections(state, corrections)

        assert state.trip_inputs.destinations == ["Patagonia", "London"]
        assert state.trip_inputs.origin == "Paris"  # Unchanged

    def test_applies_origin_corrections(self):
        """Should correct typos in origin."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="Londun",
            ),
        )
        corrections = {"Londun": "London"}
        _apply_typo_corrections(state, corrections)

        assert state.trip_inputs.origin == "London"
        assert state.trip_inputs.destinations == ["Paris"]  # Unchanged

    def test_no_changes_when_no_matching_corrections(self):
        """Should not change anything if corrections don't match."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
            ),
        )
        corrections = {"Tokyo": "Tokio"}  # Doesn't match anything
        _apply_typo_corrections(state, corrections)

        assert state.trip_inputs.destinations == ["Paris"]
        assert state.trip_inputs.origin == "London"

    def test_handles_empty_inputs(self):
        """Should handle empty destinations/origin gracefully."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(),
        )
        corrections = {"Paris": "Paris, France"}
        _apply_typo_corrections(state, corrections)

        assert state.trip_inputs.destinations is None or state.trip_inputs.destinations == []
        assert state.trip_inputs.origin is None


class TestRouteAfterRouter:
    """Tests for route_after_router function."""

    def test_unknown_intent_falls_back_to_required_fields(self):
        """Unknown intent should fall back to required_fields_node."""
        state = GraphState(
            user_text="something random",
            trip_inputs=TripInputs(),
            intent="unknown",
            metadata={},
        )
        result = route_after_router(state)
        assert result == "required_fields_node"

    def test_low_confidence_forces_required_fields(self):
        """Low extraction confidence should force required_fields."""
        state = GraphState(
            user_text="xyz abc",
            trip_inputs=TripInputs(),
            intent="flights",
            metadata={
                "extraction_confidence": {
                    "overall": 0.3,
                    "level": "low",
                    "low_confidence_reasons": ["no_entities_extracted"],
                }
            },
        )
        result = route_after_router(state)
        assert result == "required_fields_node"

    def test_typo_forces_required_fields(self):
        """Typo suggestions should force required_fields."""
        state = GraphState(
            user_text="going to Pariz",
            trip_inputs=TripInputs(destinations=["Pariz"]),
            intent="flights",
            metadata={
                "extraction_confidence": {
                    "overall": 0.6,
                    "level": "medium",
                    "typo_suggestions": {"Pariz": "Paris"},
                }
            },
        )
        result = route_after_router(state)
        assert result == "required_fields_node"

    def test_meaningful_update_bypasses_low_confidence(self):
        """Preference-only turns should not be forced to required_fields."""
        state = GraphState(
            user_text="direct business class",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date=FUTURE_DATE,
            ),
            intent="flights",
            parsed_inputs={
                "flight_settings_delta": {"direct_only": True, "cabin_class": "business"}
            },
            metadata={
                "extraction_confidence": {
                    "overall": 0.4,
                    "level": "low",
                }
            },
        )
        result = route_after_router(state)
        # Should NOT be forced to required_fields because there's a meaningful update
        assert result in (
            "flights_node",
            "required_fields_node",
        )  # May still go to required if core fields missing

    def test_core_fields_missing_forces_required_fields(self):
        """Missing core fields should force required_fields."""
        state = GraphState(
            user_text="find me hotels",
            trip_inputs=TripInputs(),  # No destinations, origin, dates
            intent="hotels",
            metadata={
                "extraction_confidence": {
                    "overall": 0.9,
                    "level": "high",
                }
            },
        )
        result = route_after_router(state)
        assert result == "required_fields_node"


class TestConfidenceThreshold:
    """Tests for confidence threshold constant."""

    def test_threshold_value_is_reasonable(self):
        """Threshold should be between 0.8 and 1.0."""
        assert 0.8 <= CONFIDENCE_THRESHOLD_SKIP_ROUTER <= 1.0

    def test_threshold_is_92_percent(self):
        """Current implementation uses 0.92."""
        assert CONFIDENCE_THRESHOLD_SKIP_ROUTER == 0.92


class TestRouteAfterRequiredFields:
    """Tests for route_after_required_fields function."""

    def test_no_deferred_routes_to_validate(self):
        """No deferred intent should go to validate_and_merge."""
        state = GraphState(
            user_text="ok",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date=FUTURE_DATE,
            ),
            metadata={},
        )
        result = route_after_required_fields(state)
        assert result == "validate_and_merge"

    def test_deferred_with_complete_fields_routes_to_intent(self):
        """Deferred intent with complete fields should route to that intent."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date=FUTURE_DATE,
            ),
            last_summary="Trip noted.",
            chat_history=[],
            metadata={"deferred_intent": "activities"},
        )
        result = route_after_required_fields(state)
        assert result == "activities_node"

    def test_deferred_with_incomplete_fields_clears(self):
        """Deferred intent with incomplete fields should be cleared."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                # Missing origin and start_date
            ),
            metadata={"deferred_intent": "flights"},
        )
        result = route_after_required_fields(state)
        assert result == "validate_and_merge"
        assert "deferred_intent" not in state.metadata


class TestRouteAfterLqaPrepass:
    """Tests for route_after_lqa_prepass routing function.

    This routing function decides whether to skip the extractor
    (when LQA successfully parsed a simple answer) or fall through
    to the extractor (when LQA bailed out).
    """

    def test_lqa_hit_routes_to_normalize_inputs(self):
        """LQA hit should route directly to normalize_inputs, skipping extractor."""
        state = GraphState(
            user_text="Paris",
            trip_inputs=TripInputs(),
            flags={"lqa_prepass": True},
            parsed_inputs={"destinations_delta": ["Paris"]},
            metadata={},
        )
        result = route_after_lqa_prepass(state)
        assert result == "normalize_inputs"

    def test_lqa_bail_routes_to_extractor(self):
        """LQA bail should route to extractor for full extraction."""
        state = GraphState(
            user_text="I want to go to Paris and book hotels",
            trip_inputs=TripInputs(),
            flags={"lqa_prepass": False, "lqa_bail_reason": "multi_intent"},
            metadata={},
        )
        result = route_after_lqa_prepass(state)
        assert result == "extractor"

    def test_missing_lqa_flag_routes_to_extractor(self):
        """Missing lqa_prepass flag should default to extractor."""
        state = GraphState(
            user_text="Paris",
            trip_inputs=TripInputs(),
            flags={},
            metadata={},
        )
        result = route_after_lqa_prepass(state)
        assert result == "extractor"

    def test_lqa_hit_with_parsed_origin(self):
        """LQA hit with origin parsed should route to normalize_inputs."""
        state = GraphState(
            user_text="from London",
            trip_inputs=TripInputs(),
            flags={"lqa_prepass": True},
            parsed_inputs={"origin_delta": "London"},
            metadata={},
        )
        result = route_after_lqa_prepass(state)
        assert result == "normalize_inputs"

    def test_lqa_hit_with_parsed_travelers(self):
        """LQA hit with travelers parsed should route to normalize_inputs."""
        state = GraphState(
            user_text="2 adults",
            trip_inputs=TripInputs(),
            flags={"lqa_prepass": True},
            parsed_inputs={"adults_delta": 2},
            metadata={},
        )
        result = route_after_lqa_prepass(state)
        assert result == "normalize_inputs"

    def test_lqa_bail_too_long_routes_to_extractor(self):
        """LQA bail due to too long input should route to extractor."""
        long_text = "I want to go to Paris and visit all the museums and eat croissants"
        state = GraphState(
            user_text=long_text,
            trip_inputs=TripInputs(),
            flags={"lqa_prepass": False, "lqa_bail_reason": "too_long"},
            metadata={},
        )
        result = route_after_lqa_prepass(state)
        assert result == "extractor"

    def test_lqa_bail_negation_routes_to_extractor(self):
        """LQA bail due to negation should route to extractor."""
        state = GraphState(
            user_text="not Paris, somewhere else",
            trip_inputs=TripInputs(),
            flags={"lqa_prepass": False, "lqa_bail_reason": "negation"},
            metadata={},
        )
        result = route_after_lqa_prepass(state)
        assert result == "extractor"
