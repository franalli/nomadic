"""
Tests for generate request pattern detection and routing.

This module tests:
1. GENERATE_REQUEST_PATTERN matches explicit generate phrases
2. _detect_short_circuit returns generate_plan action for ready plans
3. GateEvaluator routes to generate_responder when generate_requested is set
4. Strategy expansion gate routes to strategy_node for "Show more details"
"""

import pytest

from app.pattern_matching import GENERATE_REQUEST_PATTERN
from app.plan_graph import (
    GateEvaluator,
    GatePrecedence,
    GraphState,
    TripInputs,
    _detect_short_circuit,
    _extract_message_from_malformed_json,
    _is_strategy_expansion_request,
)


class TestGenerateRequestPattern:
    """Tests for GENERATE_REQUEST_PATTERN regex."""

    @pytest.mark.parametrize(
        "text",
        [
            "Yes, generate my itinerary!",
            "generate my plan",
            "Generate the itinerary",
            "create my trip",
            "show me the plan",
            "I'm ready",
            "ready to go",
            "ready to generate",
            "looks good, go ahead",
            "sounds good, let's go",
            "let's go",
            "let's do it",
            "go ahead",
            "go ahead and generate",
            "book it",
            "book it now",
            "do it now",  # More specific - requires "now" or "happen"
            "make it happen",
            "yes please generate",
            "yes generate",
        ],
    )
    def test_pattern_matches_generate_requests(self, text: str) -> None:
        """Test that common generate request phrases are matched."""
        assert GENERATE_REQUEST_PATTERN.search(text) is not None, f"Pattern should match: {text}"

    @pytest.mark.parametrize(
        "text",
        [
            "hello",
            "do it all together",  # Multi-city intent, NOT generate request
            "do it",  # Too ambiguous without "now" or "happen"
            "what hotels are available",
            "I want to go to Paris",
            "December 15th",
            "2 adults",
            "maybe",
            "I'm not sure",
            "what do you think",
        ],
    )
    def test_pattern_does_not_match_non_generate_requests(self, text: str) -> None:
        """Test that non-generate phrases are not matched."""
        assert GENERATE_REQUEST_PATTERN.search(text) is None, f"Pattern should NOT match: {text}"


class TestDetectShortCircuitGenerateRequest:
    """Tests for _detect_short_circuit with generate requests."""

    def _make_ready_state(self) -> GraphState:
        """Create a state with all core fields complete."""
        return GraphState(
            user_text="",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date="2025-06-01",
                end_date="2025-06-08",
                adults=2,
            ),
            metadata={},
        )

    def _make_incomplete_state(self) -> GraphState:
        """Create a state with missing core fields."""
        return GraphState(
            user_text="",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                # Missing: origin, dates
            ),
            metadata={},
        )

    @pytest.mark.parametrize(
        "text",
        [
            "Yes, generate my itinerary!",
            "generate my plan",
            "I'm ready",
            "let's go",
            "go ahead",
        ],
    )
    def test_generate_request_triggers_when_plan_ready(self, text: str) -> None:
        """Test that generate requests trigger generate_plan action when core complete."""
        state = self._make_ready_state()
        result = _detect_short_circuit(text, state)

        assert result is not None
        assert result["type"] == "generate_request"
        assert result["action"] == "generate_plan"
        assert result.get("user_request_type") == "generate"

    @pytest.mark.parametrize(
        "text",
        [
            "Yes, generate my itinerary!",
            "generate my plan",
            "I'm ready",
        ],
    )
    def test_generate_request_bypassed_when_plan_incomplete(self, text: str) -> None:
        """Test that generate requests are bypassed when core fields missing."""
        state = self._make_incomplete_state()
        result = _detect_short_circuit(text, state)

        # Should NOT trigger generate_plan since plan is not ready
        if result is not None:
            assert result.get("action") != "generate_plan"


class TestStrategyExpansionGate:
    """Tests for STRATEGY_EXPANSION gate routing."""

    def test_expansion_request_detected(self) -> None:
        """Test that expansion requests are properly detected."""
        result = _is_strategy_expansion_request("Show more details")
        assert result.is_expansion is True
        # The pattern matches "more details" from the generic triggers
        assert "more details" in result.matched_phrase.lower()

    def test_non_expansion_request_not_detected(self) -> None:
        """Test that non-expansion requests are not falsely detected."""
        result = _is_strategy_expansion_request("I want to go hiking")
        assert result.is_expansion is False

    @pytest.mark.parametrize(
        "text",
        [
            "Show more details",
            "expand",
            "tell me more",
            "more details",
            "elaborate",
            "go deeper",
        ],
    )
    def test_generic_expansion_triggers(self, text: str) -> None:
        """Test that generic expansion phrases trigger expansion."""
        result = _is_strategy_expansion_request(text)
        assert result.is_expansion is True

    def test_gate_evaluator_routes_expansion_when_pending(self) -> None:
        """Test that GateEvaluator routes to strategy_node for expansion requests."""
        state = GraphState(
            user_text="Show more details",
            trip_inputs=TripInputs(
                destinations=["Alps"],
                origin="London",
                start_date="2025-07-01",
                end_date="2025-07-08",
                adults=2,
            ),
            metadata={"last_strategy_topic": "hiking"},
            pending_strategy_expansion=True,
        )

        result = GateEvaluator.evaluate(state)

        assert result.gate_fired == GatePrecedence.STRATEGY_EXPANSION
        assert result.destination == "strategy_node"
        assert "expansion" in result.reason


class TestJsonRecovery:
    """Tests for malformed JSON recovery in strategy_node."""

    def test_extract_complete_message(self) -> None:
        """Test extraction of complete assistant_message from truncated JSON."""
        malformed = (
            '{"assistant_message": "Great choice with Patagonia! '
            'Here are some hiking options.", "suggested_responses": ['
        )
        result = _extract_message_from_malformed_json(malformed)
        assert result is not None
        assert "Patagonia" in result
        assert "hiking" in result

    def test_extract_with_escaped_quotes(self) -> None:
        """Test extraction handles escaped quotes in message."""
        # Message needs to be >50 chars to be accepted
        malformed = (
            '{"assistant_message": "I\'d love to help you plan your amazing '
            'adventure trip to the beautiful mountains of Patagonia!"}'
        )
        result = _extract_message_from_malformed_json(malformed)
        assert result is not None
        assert "love to help" in result

    def test_extract_returns_none_for_empty(self) -> None:
        """Test that empty input returns None."""
        assert _extract_message_from_malformed_json("") is None
        assert _extract_message_from_malformed_json(None) is None

    def test_extract_returns_none_for_no_message(self) -> None:
        """Test that JSON without assistant_message returns None."""
        result = _extract_message_from_malformed_json('{"other_field": "value"}')
        assert result is None

    def test_extract_returns_none_for_short_message(self) -> None:
        """Test that very short messages are rejected."""
        result = _extract_message_from_malformed_json('{"assistant_message": "Hi"}')
        assert result is None  # Too short (< 50 chars)


class TestGatePrecedenceOrder:
    """Tests for gate precedence ordering."""

    def test_strategy_expansion_has_highest_priority(self) -> None:
        """Test that STRATEGY_EXPANSION has higher priority than GENERATE_REQUESTED."""
        assert GatePrecedence.STRATEGY_EXPANSION < GatePrecedence.GENERATE_REQUESTED

    def test_generate_requested_before_short_circuit(self) -> None:
        """Test that GENERATE_REQUESTED comes before SHORT_CIRCUIT."""
        assert GatePrecedence.GENERATE_REQUESTED < GatePrecedence.SHORT_CIRCUIT

    def test_ready_no_fields_after_short_circuit(self) -> None:
        """Test that READY_NO_FIELDS comes after SHORT_CIRCUIT."""
        assert GatePrecedence.SHORT_CIRCUIT < GatePrecedence.READY_NO_FIELDS

    def test_intuitive_numbering(self) -> None:
        """Test that gate precedence uses intuitive increments of 10."""
        assert GatePrecedence.STRATEGY_EXPANSION == 10
        assert GatePrecedence.GENERATE_REQUESTED == 20
        assert GatePrecedence.SHORT_CIRCUIT == 30
        assert GatePrecedence.READY_NO_FIELDS == 40
