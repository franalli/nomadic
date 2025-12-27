"""Consolidated test fixtures for langgraph tests.

This module provides reusable state builders and fixtures to eliminate
duplication across test files. All test files should import fixtures
from here rather than defining their own.

Usage:
    from tests.langgraph.fixtures import (
        complete_trip_inputs,
        complete_state,
        incomplete_state_factory,
        empty_state,
        FUTURE_DATE,
        FUTURE_END_DATE,
    )
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable

import pytest

from app.plan_graph import GraphState, TripInputs

# =============================================================================
# Future Date Constants
# =============================================================================
# Tests should use these to avoid infeasibility detection for past dates.
# 30 days ahead is sufficient to avoid any "too soon" warnings.


def get_future_date(days_ahead: int = 30) -> str:
    """Get an ISO date string for a future date."""
    return (date.today() + timedelta(days=days_ahead)).isoformat()


FUTURE_DATE = get_future_date(30)  # Start date (e.g., "2026-01-18")
FUTURE_END_DATE = get_future_date(40)  # End date (e.g., "2026-01-28")


# =============================================================================
# TripInputs Builders
# =============================================================================


def make_complete_trip_inputs(**overrides: Any) -> TripInputs:
    """Create TripInputs with all core fields filled.

    Args:
        **overrides: Field values to override defaults.

    Returns:
        TripInputs with destinations, origin, dates, and adults set.
    """
    defaults = {
        "destinations": ["Paris"],
        "origin": "London",
        "start_date": FUTURE_DATE,
        "end_date": FUTURE_END_DATE,
        "adults": 2,
        "children": 0,
    }
    defaults.update(overrides)
    return TripInputs(**defaults)


def make_incomplete_trip_inputs(missing_field: str, **overrides: Any) -> TripInputs:
    """Create TripInputs missing a specific core field.

    Args:
        missing_field: The field to omit (destinations, origin, start_date,
                       end_date, or adults).
        **overrides: Additional field overrides.

    Returns:
        TripInputs missing the specified field.
    """
    fields = {
        "destinations": ["Paris"],
        "origin": "London",
        "start_date": FUTURE_DATE,
        "end_date": FUTURE_END_DATE,
        "adults": 2,
    }

    # Handle field name normalization
    field_map = {
        "dates": ["start_date", "end_date"],
        "travelers": ["adults"],
    }

    if missing_field in field_map:
        for f in field_map[missing_field]:
            fields.pop(f, None)
    elif missing_field == "destinations":
        fields["destinations"] = []
    else:
        fields.pop(missing_field, None)

    fields.update(overrides)
    return TripInputs(**fields)


def make_empty_trip_inputs() -> TripInputs:
    """Create empty TripInputs with no fields set."""
    return TripInputs()


# =============================================================================
# GraphState Builders
# =============================================================================


def make_complete_state(
    user_text: str = "show me options",
    turn_number: int = 3,
    **metadata_overrides: Any,
) -> GraphState:
    """Create a complete GraphState with all core fields.

    Args:
        user_text: The user's input text.
        turn_number: Current turn number in conversation.
        **metadata_overrides: Additional metadata key-value pairs.

    Returns:
        GraphState ready for routing (should never go to required_fields).
    """
    metadata = {
        "thread_id": "test_complete",
        "today_iso": date.today().isoformat(),
    }
    metadata.update(metadata_overrides)

    return GraphState(
        user_text=user_text,
        trip_inputs=make_complete_trip_inputs(),
        metadata=metadata,
        turn_number=turn_number,
    )


def make_incomplete_state(
    missing_field: str,
    user_text: str = "",
    turn_number: int = 1,
    **metadata_overrides: Any,
) -> GraphState:
    """Create GraphState missing a specific core field.

    Args:
        missing_field: The field to omit.
        user_text: The user's input text.
        turn_number: Current turn number.
        **metadata_overrides: Additional metadata.

    Returns:
        GraphState that should route to required_fields.
    """
    metadata = {
        "thread_id": f"test_missing_{missing_field}",
        "today_iso": date.today().isoformat(),
    }
    metadata.update(metadata_overrides)

    return GraphState(
        user_text=user_text,
        trip_inputs=make_incomplete_trip_inputs(missing_field),
        metadata=metadata,
        turn_number=turn_number,
    )


def make_empty_state(
    user_text: str = "",
    **metadata_overrides: Any,
) -> GraphState:
    """Create empty GraphState for first-turn scenarios.

    Args:
        user_text: The user's input text.
        **metadata_overrides: Additional metadata.

    Returns:
        GraphState with no trip inputs (first turn).
    """
    metadata = {
        "thread_id": "test_empty",
        "today_iso": date.today().isoformat(),
    }
    metadata.update(metadata_overrides)

    return GraphState(
        user_text=user_text,
        trip_inputs=make_empty_trip_inputs(),
        metadata=metadata,
        turn_number=0,
    )


def make_state_with_question_target(
    question_target: str,
    user_text: str = "",
    complete: bool = False,
    **metadata_overrides: Any,
) -> GraphState:
    """Create GraphState with a specific question_target set.

    Args:
        question_target: The question target to set.
        user_text: The user's input text.
        complete: Whether to use complete or incomplete trip inputs.
        **metadata_overrides: Additional metadata.

    Returns:
        GraphState with question_target set in metadata.
    """
    metadata = {
        "thread_id": f"test_qt_{question_target}",
        "today_iso": date.today().isoformat(),
        "question_target": question_target,
    }
    metadata.update(metadata_overrides)

    trip_inputs = (
        make_complete_trip_inputs() if complete else make_incomplete_trip_inputs(question_target)
    )

    return GraphState(
        user_text=user_text,
        trip_inputs=trip_inputs,
        metadata=metadata,
        question_target=question_target,
        turn_number=2 if complete else 1,
    )


def make_strategy_state(
    topic: str = "hiking",
    stage: int = 0,
    user_text: str = "I want to go hiking",
    complete: bool = False,
    pending_expansion: bool = False,
    **metadata_overrides: Any,
) -> GraphState:
    """Create GraphState configured for strategy node testing.

    Args:
        topic: Strategy topic (hiking, diving, skiing, cycling, boating).
        stage: Strategy stage (0=pre-core, 1=outline, 2=expansion).
        user_text: The user's input text.
        complete: Whether core fields are complete.
        pending_expansion: Whether stage 1 is complete and awaiting expansion.
        **metadata_overrides: Additional metadata.

    Returns:
        GraphState configured for strategy testing.
    """
    metadata = {
        "thread_id": f"test_strategy_{topic}",
        "today_iso": date.today().isoformat(),
        "strategy_stage": stage,
        "strategy_topic": topic,
    }
    metadata.update(metadata_overrides)

    trip_inputs = (
        make_complete_trip_inputs() if complete else make_incomplete_trip_inputs("destinations")
    )

    return GraphState(
        user_text=user_text,
        trip_inputs=trip_inputs,
        metadata=metadata,
        strategy_topic=topic,
        pending_strategy_expansion=pending_expansion,
        turn_number=3 if complete else 1,
    )


# =============================================================================
# Pytest Fixtures
# =============================================================================


@pytest.fixture
def complete_trip_inputs() -> TripInputs:
    """Fixture: Complete TripInputs with all core fields."""
    return make_complete_trip_inputs()


@pytest.fixture
def complete_state() -> GraphState:
    """Fixture: Complete GraphState ready for routing."""
    return make_complete_state()


@pytest.fixture
def incomplete_state_factory() -> Callable[[str], GraphState]:
    """Fixture: Factory to create states missing specific fields.

    Usage:
        def test_missing_origin(incomplete_state_factory):
            state = incomplete_state_factory("origin")
            assert state.trip_inputs.origin is None
    """
    return make_incomplete_state


@pytest.fixture
def empty_state() -> GraphState:
    """Fixture: Empty state for first-turn testing."""
    return make_empty_state()


@pytest.fixture
def question_target_state_factory() -> Callable[..., GraphState]:
    """Fixture: Factory to create states with question_target.

    Usage:
        def test_dates_target(question_target_state_factory):
            state = question_target_state_factory("dates", user_text="next week")
    """
    return make_state_with_question_target


@pytest.fixture
def strategy_state_factory() -> Callable[..., GraphState]:
    """Fixture: Factory to create strategy-configured states.

    Usage:
        def test_hiking_stage0(strategy_state_factory):
            state = strategy_state_factory("hiking", stage=0)
    """
    return make_strategy_state


# =============================================================================
# Parametrize Helpers
# =============================================================================

# Core fields that can be missing
CORE_FIELDS = ["destinations", "origin", "start_date", "end_date", "adults"]

# Canonical question targets
QUESTION_TARGETS = ["destinations", "origin", "dates", "travelers", "budget"]

# Strategy topics
STRATEGY_TOPICS = ["hiking", "diving", "skiing", "cycling", "boating"]

# Short-circuit inputs (greetings, confirmations, etc.)
SHORT_CIRCUIT_INPUTS = [
    # Greetings
    "hi",
    "hello",
    "hey",
    "hey there",
    # Confirmations
    "yes",
    "yeah",
    "yep",
    "sure",
    # Negations
    "no",
    "nope",
    "cancel",
    # Acknowledgments
    "ok",
    "okay",
    "thanks",
    "thank you",
    "got it",
]

# Generate request phrases
GENERATE_REQUEST_PHRASES = [
    "generate my itinerary",
    "generate the trip",
    "create my plan",
    "book it",
    "let's do it",
    "I'm ready",
]
