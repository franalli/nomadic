# backend/app/planner/meta.py
"""
Metadata helper functions for planner state.

Provides safe accessors for metadata keys with type checking and
consistent initialization patterns.

PR2: Metadata helpers + centralized turn init
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from app.planner.meta_keys import (
    CACHE_EVENTS,
    DELTAS_APPLIED_THIS_TURN,
    DUPLICATION_CLASS,
    LLM_CALL_BLOCKED_REASON,
    LLM_CALL_SITES,
    LLM_CALLS_THIS_TURN,
    MUTATION_COUNTER,
    NODE_RUN_JOURNAL,
    PLANNER_SNAPSHOT,
    RESPONSE_CLAIMED_BY,
    RESPONSE_GENERATION_PROVENANCE,
    RESPONSE_SOURCE_NODE,
    STEP_COUNT,
    TRIPWIRE_TRIGGERED,
    TURN_CANARY,
    VISITED_NODES,
)

logger = logging.getLogger(__name__)


def _is_test_mode_internal() -> bool:
    """
    Internal check for test mode.

    Note: For external use, prefer app.planner.test_mode.is_test_mode()
    to avoid potential circular imports.
    """
    import os

    return os.environ.get("PYTEST_RUNNING", "").lower() in ("1", "true", "yes")


def meta_get(state: Any, key: str, default: Any = None) -> Any:
    """
    Safely get a metadata value from state.

    Args:
        state: GraphState or any object with .metadata dict
        key: Metadata key to retrieve
        default: Default value if key not found

    Returns:
        The metadata value or default
    """
    if not hasattr(state, "metadata"):
        return default
    return state.metadata.get(key, default)


def meta_set(state: Any, key: str, value: Any) -> None:
    """
    Set a metadata value on state.

    Args:
        state: GraphState or any object with .metadata dict
        key: Metadata key to set
        value: Value to set
    """
    if not hasattr(state, "metadata"):
        return
    state.metadata[key] = value


def meta_set_once(
    state: Any, key: str, value: Any, *, allow_overwrite_in_prod: bool = True
) -> bool:
    """
    Set a metadata value only if not already set.

    In test mode (PR4), raises AssertionError if key already has a different value.
    In prod mode, logs and optionally overwrites based on allow_overwrite_in_prod.

    Args:
        state: GraphState or any object with .metadata dict
        key: Metadata key to set
        value: Value to set
        allow_overwrite_in_prod: If True, overwrite in prod; if False, skip

    Returns:
        True if value was set, False if skipped

    Raises:
        AssertionError: In test mode if key already set with different value
    """
    if not hasattr(state, "metadata"):
        return False

    existing = state.metadata.get(key)

    if existing is None:
        state.metadata[key] = value
        return True

    if existing == value:
        # Same value, no-op
        return True

    # Different value already set
    if _is_test_mode_internal():
        raise AssertionError(
            f"meta_set_once: key '{key}' already set to {existing!r}, attempted to set to {value!r}"
        )

    # Prod mode
    if allow_overwrite_in_prod:
        logger.warning("meta_set_once overwriting key=%s old=%r new=%r", key, existing, value)
        state.metadata[key] = value
        return True
    else:
        logger.warning(
            "meta_set_once skipping key=%s existing=%r attempted=%r", key, existing, value
        )
        return False


def meta_append(state: Any, key: str, item: Any) -> None:
    """
    Append an item to a list in metadata, creating the list if needed.

    Args:
        state: GraphState or any object with .metadata dict
        key: Metadata key for the list
        item: Item to append
    """
    if not hasattr(state, "metadata"):
        return

    if key not in state.metadata:
        state.metadata[key] = []

    lst = state.metadata[key]
    if not isinstance(lst, list):
        # Convert to list if not already
        state.metadata[key] = [lst, item]
    else:
        lst.append(item)


def meta_increment(state: Any, key: str, amount: int = 1) -> int:
    """
    Increment an integer counter in metadata.

    Args:
        state: GraphState or any object with .metadata dict
        key: Metadata key for the counter
        amount: Amount to increment by (default 1)

    Returns:
        The new counter value
    """
    if not hasattr(state, "metadata"):
        return amount

    current = state.metadata.get(key, 0)
    if not isinstance(current, int):
        current = 0
    new_value = current + amount
    state.metadata[key] = new_value
    return new_value


def init_turn_metadata(
    metadata: Dict[str, Any],
    *,
    planner_snapshot_fn: Optional[Callable[[], Dict[str, Any]]] = None,
) -> str:
    """
    Initialize per-turn metadata at the start of run_turn/run_turn_streaming.

    This consolidates all per-turn resets into a single function to ensure
    consistent state initialization.

    Args:
        metadata: The metadata dict to initialize
        planner_snapshot_fn: Optional callable to get planner snapshot dict

    Returns:
        turn_canary: UUID for validating state mutations persist
    """
    turn_canary = uuid4().hex

    # LLM budget tracking (reset each turn)
    metadata[LLM_CALLS_THIS_TURN] = 0
    metadata[LLM_CALL_SITES] = []
    metadata[LLM_CALL_BLOCKED_REASON] = {}

    # Node execution instrumentation
    metadata[NODE_RUN_JOURNAL] = []
    metadata[VISITED_NODES] = set()
    metadata[STEP_COUNT] = 0

    # Response writer guard
    metadata[RESPONSE_CLAIMED_BY] = None

    # Turn validation
    metadata[TURN_CANARY] = turn_canary
    metadata[MUTATION_COUNTER] = 0

    # Tripwire (cleared each turn)
    metadata.pop(TRIPWIRE_TRIGGERED, None)

    # Duplication class (cleared each turn)
    metadata.pop(DUPLICATION_CLASS, None)

    # Field change tracking
    metadata[DELTAS_APPLIED_THIS_TURN] = []

    # Response provenance
    metadata[RESPONSE_SOURCE_NODE] = None
    metadata[RESPONSE_GENERATION_PROVENANCE] = None

    # Planner snapshot (if function provided)
    if planner_snapshot_fn is not None:
        metadata[PLANNER_SNAPSHOT] = planner_snapshot_fn()

    # Cache events (cleared each turn)
    # Note: The actual cache event list is module-level in plan_graph.py
    # This key is for observability when events are copied to metadata
    metadata[CACHE_EVENTS] = []

    return turn_canary


def validate_turn_metadata(metadata: Dict[str, Any]) -> List[str]:
    """
    Validate that all required per-turn metadata keys exist and have correct types.

    Args:
        metadata: The metadata dict to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []

    # Required keys with expected types
    required_keys = {
        LLM_CALLS_THIS_TURN: int,
        LLM_CALL_SITES: list,
        LLM_CALL_BLOCKED_REASON: dict,
        NODE_RUN_JOURNAL: list,
        VISITED_NODES: set,
        STEP_COUNT: int,
        RESPONSE_CLAIMED_BY: (type(None), str),
        TURN_CANARY: str,
        MUTATION_COUNTER: int,
        DELTAS_APPLIED_THIS_TURN: list,
    }

    for key, expected_type in required_keys.items():
        if key not in metadata:
            errors.append(f"Missing required key: {key}")
        elif isinstance(expected_type, tuple):
            if not isinstance(metadata[key], expected_type):
                errors.append(
                    f"Key {key} has wrong type: expected one of {expected_type}, "
                    f"got {type(metadata[key])}"
                )
        elif not isinstance(metadata[key], expected_type):
            errors.append(
                f"Key {key} has wrong type: expected {expected_type}, got {type(metadata[key])}"
            )

    return errors
