"""
Trace Replay Test Harness for Plan Graph Routing Correctness.

This module provides a reusable harness for replaying conversation traces
to validate routing decisions, state transitions, and invariants.

Usage:
    pytest backend/tests/langgraph/test_trace_replay.py -v

The harness validates:
1. Gate/routing correctness per turn
2. Question_target consistency
3. No-stale-summary invariant
4. Suggestion contract (suggestions match question_target)
5. Selected specialist matches expected
6. ErrorRecord schema compatibility (V8)
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

from app.schemas import ErrorRecord


@dataclass
class TurnExpectation:
    """Expected outcomes for a single turn in a trace."""

    # Input
    user_text: str

    # Expected routing
    expected_gate: Optional[str] = None  # e.g., "STRATEGY_PRE_CORE_VALUE"
    expected_destination: Optional[str] = None  # e.g., "strategy_node"
    expected_routing_reason: Optional[str] = None

    # Expected state after turn
    expected_question_target: Optional[str] = None
    expected_selected_specialist: Optional[str] = None

    # Invariants to check
    check_no_stale_summary: bool = True
    check_suggestion_contract: bool = True

    # Expected state changes (field -> expected value)
    expected_state_updates: Dict[str, Any] = field(default_factory=dict)

    # Optional: expected errors
    expected_error_codes: List[str] = field(default_factory=list)


@dataclass
class TraceFixture:
    """A complete conversation trace for replay testing."""

    name: str
    description: str
    turns: List[TurnExpectation]
    initial_state: Dict[str, Any] = field(default_factory=dict)

    # Expected final state
    expected_final_destinations: Optional[List[str]] = None
    expected_final_origin: Optional[str] = None


# =============================================================================
# TRACE FIXTURES
# =============================================================================

DIVING_SPECIALIST_TRACE = TraceFixture(
    name="diving_specialist_routing",
    description="User requests diving trip, verifies specialist is executed",
    turns=[
        TurnExpectation(
            user_text="I want to plan a diving trip",
            expected_gate="STRATEGY_PRE_CORE_VALUE",
            expected_destination="strategy_node",
            expected_question_target="dates",
            expected_selected_specialist="strategy_diving",
        ),
        TurnExpectation(
            user_text="March 2025",
            expected_question_target="origin",
        ),
        TurnExpectation(
            user_text="New York",
            expected_question_target="destinations",
        ),
    ],
)

DESTINATION_SUGGESTION_CLICK_TRACE = TraceFixture(
    name="destination_suggestion_click",
    description="User clicks destination suggestion when dates were asked",
    initial_state={
        "question_target": "dates",
        "suggested_responses": ["Swiss Alps", "Patagonia", "Nepal"],
    },
    turns=[
        TurnExpectation(
            user_text="Patagonia",
            # Should parse as destination, not fail LQA
            expected_state_updates={"destinations": ["Patagonia"]},
            check_suggestion_contract=True,
        ),
    ],
)

TOPIC_SWITCH_TURN_1_TRACE = TraceFixture(
    name="topic_switch_turn_1_guard",
    description="Verify STRATEGY_TOPIC_SWITCH doesn't fire on turn 1",
    turns=[
        TurnExpectation(
            user_text="I wanna go hiking",
            # Should use STRATEGY_PRE_CORE_VALUE (priority 5), not TOPIC_SWITCH (priority 4)
            expected_gate="STRATEGY_PRE_CORE_VALUE",
            expected_destination="strategy_node",
        ),
    ],
)

MULTI_CITY_INFERENCE_TRACE = TraceFixture(
    name="multi_city_inference",
    description="Verify multi-city requires two signals",
    initial_state={
        "trip_inputs": {"destinations": ["Paris"]},
    },
    turns=[
        TurnExpectation(
            user_text="I want to visit Rome too",
            expected_state_updates={
                "destinations": ["Paris", "Rome"],
                "multi_city_intent": "multi_city",
            },
        ),
    ],
)


# =============================================================================
# REGRESSION TEST FIXTURES (V8: ErrorRecord + Destination-Known Gate)
# =============================================================================

DIVING_IN_MALDIVES_TRACE = TraceFixture(
    name="diving_in_maldives_destination_known",
    description="Verify STRATEGY_PRE_CORE_VALUE_WITH_DEST fires for 'diving in maldives'",
    turns=[
        TurnExpectation(
            user_text="I want to go diving in the Maldives",
            expected_gate="STRATEGY_PRE_CORE_VALUE_WITH_DEST",
            expected_destination="strategy_node",
            expected_question_target="dates",  # Always ask dates when destination known
            expected_selected_specialist="strategy_diving",
            expected_state_updates={
                "destinations": ["Maldives"],
            },
        ),
    ],
)

DATE_AMBIGUITY_ERROR_RECORD_TRACE = TraceFixture(
    name="date_ambiguity_error_record",
    description="Verify date ambiguity produces ErrorRecord without crash",
    initial_state={
        "trip_inputs": {"destinations": ["Paris"], "origin": "New York"},
    },
    turns=[
        TurnExpectation(
            user_text="December 20-27",  # Ambiguous year when today is Dec 23
            expected_error_codes=["DATE_AMBIGUOUS_YEAR"],
            expected_question_target="dates",  # Should ask for clarification
        ),
    ],
)

VALUE_FIRST_NOT_STICKY_TRACE = TraceFixture(
    name="value_first_not_sticky",
    description="After dates answered, next question should be origin (not stuck on dates)",
    turns=[
        TurnExpectation(
            user_text="I want to go diving in the Maldives",
            expected_gate="STRATEGY_PRE_CORE_VALUE_WITH_DEST",
            expected_question_target="dates",
        ),
        TurnExpectation(
            user_text="March 2025",
            expected_question_target="origin",  # Should ask origin, not repeat dates
        ),
    ],
)

BLOCKING_ERROR_GUARDS_DEST_KNOWN_TRACE = TraceFixture(
    name="blocking_error_guards_dest_known",
    description="Blocking date errors should prevent destination-known value-first gate",
    initial_state={
        "trip_inputs": {"destinations": ["Maldives"]},
        "metadata": {"date_clarify_mode": True},
    },
    turns=[
        TurnExpectation(
            user_text="Let's go diving",
            # Should NOT fire STRATEGY_PRE_CORE_VALUE_WITH_DEST due to blocking errors
            # Instead should route to required_fields for date clarification
            expected_destination="required_fields_node",
            expected_question_target="dates",
        ),
    ],
)


# =============================================================================
# TEST HARNESS
# =============================================================================


class TraceReplayHarness:
    """
    Harness for replaying conversation traces and validating invariants.
    """

    def __init__(self, fixture: TraceFixture):
        self.fixture = fixture
        self.session_state = dict(fixture.initial_state)
        self.turn_results: List[Dict[str, Any]] = []
        self.violations: List[str] = []

    async def replay(self) -> bool:
        """
        Replay all turns in the fixture and validate expectations.

        Returns:
            True if all expectations met, False otherwise
        """
        from app.plan_graph import run_turn

        for i, turn in enumerate(self.fixture.turns):
            turn_num = i + 1

            # Execute turn
            result = await run_turn(
                user_text=turn.user_text,
                session_state=self.session_state,
            )
            self.turn_results.append(result)

            # Update session state for next turn
            self.session_state = result.get("session_state", {})

            # Validate expectations
            self._validate_turn(turn_num, turn, result)

        return len(self.violations) == 0

    def _validate_turn(
        self,
        turn_num: int,
        expectation: TurnExpectation,
        result: Dict[str, Any],
    ) -> None:
        """Validate a single turn against expectations."""

        session_state = result.get("session_state", {})
        metadata = session_state.get("metadata", {})

        # Read from canonical gate_result object (SSoT for routing decisions)
        gate_result = metadata.get("gate_result", {})

        # Check gate fired
        if expectation.expected_gate:
            # gate_result may be a dataclass or dict depending on serialization
            if hasattr(gate_result, "gate_fired"):
                actual_gate = (
                    gate_result.gate_fired.name
                    if hasattr(gate_result.gate_fired, "name")
                    else str(gate_result.gate_fired)
                )
            else:
                # Fallback to dict access or legacy keys
                if isinstance(gate_result, dict):
                    actual_gate = gate_result.get("gate_fired")
                else:
                    actual_gate = None
                if not actual_gate:
                    actual_gate = metadata.get("_gate_result_gate_fired")
            if actual_gate != expectation.expected_gate:
                self.violations.append(
                    f"Turn {turn_num}: Expected gate {expectation.expected_gate}, "
                    f"got {actual_gate}"
                )

        # Check destination
        if expectation.expected_destination:
            if hasattr(gate_result, "destination"):
                actual_dest = gate_result.destination  # type: ignore
            else:
                if isinstance(gate_result, dict):
                    actual_dest = gate_result.get("destination")
                else:
                    actual_dest = None
                if not actual_dest:
                    actual_dest = metadata.get("_gate_result_destination")
            if actual_dest != expectation.expected_destination:
                self.violations.append(
                    f"Turn {turn_num}: Expected destination {expectation.expected_destination}, "
                    f"got {actual_dest}"
                )

        # Check question_target
        if expectation.expected_question_target:
            actual_target = session_state.get("question_target")
            if actual_target != expectation.expected_question_target:
                self.violations.append(
                    (
                        f"Turn {turn_num}: Expected question_target "
                        f"{expectation.expected_question_target}, got {actual_target}"
                    )
                )

        # Check selected specialist
        if expectation.expected_selected_specialist:
            actual_specialist = metadata.get("selected_specialist")
            if actual_specialist != expectation.expected_selected_specialist:
                self.violations.append(
                    (
                        f"Turn {turn_num}: Expected specialist "
                        f"{expectation.expected_selected_specialist}, got {actual_specialist}"
                    )
                )

        # Check no-stale-summary invariant
        if expectation.check_no_stale_summary:
            last_response_turn = metadata.get("last_response_turn")
            if last_response_turn is not None:
                current_turn = session_state.get("turn_number", turn_num)
                if last_response_turn != current_turn:
                    self.violations.append(
                        f"Turn {turn_num}: Stale summary violation - "
                        f"last_response_turn={last_response_turn}, current={current_turn}"
                    )

        # Check suggestion contract
        if expectation.check_suggestion_contract:
            violation = metadata.get("suggestion_contract_violation")
            if violation:
                self.violations.append(
                    f"Turn {turn_num}: Suggestion contract violation - {violation}"
                )

        # Check state updates
        trip_inputs = result.get("trip_inputs", {})
        for expected_field, expected_value in expectation.expected_state_updates.items():
            actual_value = trip_inputs.get(expected_field)
            if actual_value != expected_value:
                self.violations.append(
                    (
                        f"Turn {turn_num}: Expected {expected_field}="
                        f"{expected_value}, got {actual_value}"
                    )
                )

        # Check error codes (supports ErrorRecord objects and legacy formats)
        if expectation.expected_error_codes:
            actual_errors = result.get("errors", [])
            actual_codes = []
            for e in actual_errors:
                if hasattr(e, "code"):
                    # ErrorRecord object
                    actual_codes.append(e.code)
                elif isinstance(e, dict):
                    actual_codes.append(e.get("code", ""))
                else:
                    actual_codes.append(str(e))
            for expected_code in expectation.expected_error_codes:
                if expected_code not in actual_codes:
                    self.violations.append(
                        f"Turn {turn_num}: Expected error code {expected_code} not found"
                    )


# =============================================================================
# PYTEST TESTS
# =============================================================================


@pytest.fixture
def mock_llm():
    """Mock LLM calls for deterministic testing."""
    with patch("app.plan_graph.call_llm_with_timeout") as mock:
        mock.return_value = '{"assistant_message": "Test response", "suggested_responses": []}'
        yield mock


# =============================================================================
# UNIT TESTS (no full app context required)
# =============================================================================


def test_error_record_schema():
    """Test that ErrorRecord model works correctly."""
    # Test creating ErrorRecord
    err = ErrorRecord(
        code="DATE_AMBIGUOUS_YEAR",
        node="normalize_inputs",
        severity="blocking",
        message="Year is ambiguous for date range Dec 20-27",
    )
    assert err.code == "DATE_AMBIGUOUS_YEAR"
    assert err.node == "normalize_inputs"
    assert err.severity == "blocking"
    assert "ambiguous" in err.message.lower()


def test_error_record_default_severity():
    """Test ErrorRecord defaults severity to 'warning'."""
    err = ErrorRecord(
        code="LLM_FAILED",
        node="router",
        message="LLM call timed out",
    )
    assert err.severity == "warning"  # Default value


def test_error_record_in_list():
    """Test that ErrorRecord works in a list (simulating GraphState.errors)."""
    errors: List[ErrorRecord] = [
        ErrorRecord(
            code="DATE_AMBIGUOUS_YEAR",
            node="normalize",
            severity="blocking",
            message="Year unclear",
        ),
        ErrorRecord(
            code="LLM_FAILED",
            node="router",
            severity="warning",
            message="Timeout",
        ),
    ]

    # Extract blocking codes (as compute_trip_readiness does)
    blocking_codes = [e.code for e in errors if e.severity == "blocking"]
    assert blocking_codes == ["DATE_AMBIGUOUS_YEAR"]


@pytest.mark.asyncio
async def test_trace_replay_harness_structure():
    """Test that the harness structure is valid."""
    harness = TraceReplayHarness(DIVING_SPECIALIST_TRACE)
    assert harness.fixture.name == "diving_specialist_routing"
    assert len(harness.fixture.turns) == 3


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires full app context - enable in integration tests")
async def test_diving_specialist_routing(mock_llm):
    """Test diving specialist is routed correctly."""
    harness = TraceReplayHarness(DIVING_SPECIALIST_TRACE)
    success = await harness.replay()

    if not success:
        for v in harness.violations:
            print(f"VIOLATION: {v}")

    assert success, f"Trace replay failed: {harness.violations}"


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires full app context - enable in integration tests")
async def test_topic_switch_turn_1_guard(mock_llm):
    """Test that STRATEGY_TOPIC_SWITCH doesn't fire on turn 1."""
    harness = TraceReplayHarness(TOPIC_SWITCH_TURN_1_TRACE)
    success = await harness.replay()

    assert success, f"Trace replay failed: {harness.violations}"


# =============================================================================
# V8 REGRESSION TESTS: ErrorRecord + Destination-Known Gate
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires full app context - enable in integration tests")
async def test_diving_in_maldives_destination_known(mock_llm):
    """
    Test 'diving in maldives' routes to STRATEGY_PRE_CORE_VALUE_WITH_DEST.

    This validates that when user provides both strategy topic AND destination,
    the new gate fires and asks for dates (not origin).
    """
    harness = TraceReplayHarness(DIVING_IN_MALDIVES_TRACE)
    success = await harness.replay()

    if not success:
        for v in harness.violations:
            print(f"VIOLATION: {v}")

    assert success, f"Trace replay failed: {harness.violations}"


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires full app context - enable in integration tests")
async def test_date_ambiguity_error_record(mock_llm):
    """
    Test that date ambiguity produces ErrorRecord without Pydantic crash.

    This validates that GraphState.errors: List[ErrorRecord] works correctly
    and blocking date errors are properly recorded.
    """
    harness = TraceReplayHarness(DATE_AMBIGUITY_ERROR_RECORD_TRACE)
    success = await harness.replay()

    if not success:
        for v in harness.violations:
            print(f"VIOLATION: {v}")

    assert success, f"Trace replay failed: {harness.violations}"


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires full app context - enable in integration tests")
async def test_value_first_not_sticky(mock_llm):
    """
    Test that value-first mode doesn't suppress core collection indefinitely.

    After destination-known stage0 fires and user answers dates,
    the next question should be origin (not stuck on dates).
    """
    harness = TraceReplayHarness(VALUE_FIRST_NOT_STICKY_TRACE)
    success = await harness.replay()

    if not success:
        for v in harness.violations:
            print(f"VIOLATION: {v}")

    assert success, f"Trace replay failed: {harness.violations}"


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires full app context - enable in integration tests")
async def test_blocking_error_guards_dest_known(mock_llm):
    """
    Test that blocking date errors prevent destination-known value-first gate.

    When date_clarify_mode is set (blocking errors), the
    STRATEGY_PRE_CORE_VALUE_WITH_DEST gate should NOT fire.
    """
    harness = TraceReplayHarness(BLOCKING_ERROR_GUARDS_DEST_KNOWN_TRACE)
    success = await harness.replay()

    if not success:
        for v in harness.violations:
            print(f"VIOLATION: {v}")

    assert success, f"Trace replay failed: {harness.violations}"


# =============================================================================
# UTILITY: Load production trace from JSON
# =============================================================================


def load_trace_from_json(json_path: str) -> TraceFixture:
    """
    Load a trace fixture from a JSON file.

    Expected format:
    {
        "name": "trace_name",
        "description": "...",
        "initial_state": {...},
        "turns": [
            {
                "user_text": "...",
                "expected_gate": "...",
                "expected_question_target": "...",
                ...
            }
        ]
    }
    """
    import json

    with open(json_path, "r") as f:
        data = json.load(f)

    turns = [TurnExpectation(**turn_data) for turn_data in data.get("turns", [])]

    return TraceFixture(
        name=data.get("name", "unnamed"),
        description=data.get("description", ""),
        turns=turns,
        initial_state=data.get("initial_state", {}),
    )
